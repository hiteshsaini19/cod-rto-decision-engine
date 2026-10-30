"""Part 1 - the decision engine.

decide(order) -> one of: ship | nudge | confirm | hold, with a plain-English reason.

Order of checks:
  1. Address / name / phone checks (rules first, LLM only for messy text)
  2. Risk % from the learnt weights (maths, not the LLM)
  3. Hard red flags from rules.yaml -> hold, whatever the risk %
  4. Otherwise the risk % picks the action using the thresholds in rules.yaml
  5. Guardrails: first-time buyers aren't held on risk alone; possible duplicate orders get confirmed
  6. Expected Rs of every action is attached so anyone can check the decision in money
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .assess import assess_orders
from .config import ACTION_LABELS, load_rules
from .economics import expected_values, unit_economics
from .model import load_model, score

ORDER_DEFAULTS = {
    "order_id": None, "order_datetime": None, "customer_name": "", "phone": "", "address": "",
    "city": "", "state": "", "pincode": "", "order_value": 0, "items": "", "num_items": 1,
    "customer_prior_orders": 0, "customer_prior_rto": 0, "utm_source": "", "courier": "",
    "payment_method": "COD",
}


def normalize_order(order: dict) -> dict:
    o = {**ORDER_DEFAULTS, **{k: v for k, v in order.items() if v is not None}}
    for k in ("customer_name", "phone", "address", "city", "state", "pincode", "items", "utm_source", "courier"):
        o[k] = "" if o[k] is None or (isinstance(o[k], float) and o[k] != o[k]) else str(o[k]).strip()
    if o["pincode"].endswith(".0"):
        o["pincode"] = o["pincode"][:-2]
    o["order_value"] = float(o["order_value"] or 0)
    for k in ("num_items", "customer_prior_orders", "customer_prior_rto"):
        o[k] = int(o[k] or 0)
    dt = o["order_datetime"]
    o["order_datetime"] = (pd.Timestamp(dt).to_pydatetime() if dt else datetime.now()).replace(microsecond=0)
    if not o["order_id"]:
        o["order_id"] = "NEW" + o["order_datetime"].strftime("%y%m%d%H%M%S")
    return o


def find_duplicate(order: dict, recent_orders, window_minutes: int) -> dict | None:
    """Another order from the same phone shortly before this one?"""
    if not recent_orders or not order.get("_phone"):
        return None
    t = order["order_datetime"]
    for r in recent_orders:
        if r.get("order_id") == order["order_id"] or r.get("phone") != order["_phone"]:
            continue
        rt = pd.Timestamp(r["order_datetime"]).to_pydatetime()
        if timedelta(0) <= t - rt <= timedelta(minutes=window_minutes):
            return {"order_id": r.get("order_id"), "minutes_before": int((t - rt).total_seconds() // 60)}
    return None


def _band(risk_pct: float, t: dict) -> str:
    if risk_pct >= t["hold_from_risk_pct"]:
        return "hold"
    if risk_pct >= t["confirm_from_risk_pct"]:
        return "confirm"
    if risk_pct >= t["nudge_from_risk_pct"]:
        return "nudge"
    return "ship"


def _hard_flags(order: dict, a: dict, hr: dict) -> list[dict]:
    flags = []
    if hr["hold_if_address_unusable"] and a["address"]["quality"] == "unusable":
        flags.append({"code": "address_unusable", "ask": "fix_address",
                      "text": a["address"]["issue"] or "address can't be delivered"})
    if hr["hold_if_fake_name"] and a["name"]["quality"] == "fake":
        flags.append({"code": "fake_name", "ask": "confirm_details", "text": a["name"]["issue"] or "name looks fake"})
    if hr["hold_if_phone_invalid"] and not a["phone"]["valid"]:
        flags.append({"code": "phone_invalid", "ask": "manual_call", "text": a["phone"]["issue"]})
    n = hr["hold_if_past_returns_at_least"]
    if n and order["customer_prior_rto"] >= n:
        flags.append({"code": "past_returns", "ask": "pay_online",
                      "text": f"customer refused {order['customer_prior_rto']} earlier COD orders"})
    if hr["hold_if_order_value_zero"] and order["order_value"] <= 0:
        flags.append({"code": "zero_value", "ask": "manual_check", "text": "order value is Rs 0 - check the order in Shopify"})
    return flags


def _hold_ask(flags: list[dict]) -> str:
    """What we ask a held customer to do (most important first)."""
    asks = [f["ask"] for f in flags]
    for a in ("manual_call", "manual_check", "fix_address", "confirm_details", "pay_online"):
        if a in asks:
            return a
    return "pay_online"


def _top_reasons(factors: list[dict], n: int = 3, raising: bool = True) -> str:
    picked = [f for f in factors if (f["points"] > 0) == raising][:n]
    # Area labels start with a place name, so keep their capital letter.
    return "; ".join(f["label"] if f["feature"] == "area_risk" else f["label"][0].lower() + f["label"][1:]
                     for f in picked)


def _reason(action: str, risk_pct: float, factors, flags, notes, rules, ask) -> str:
    up, down = _top_reasons(factors), _top_reasons(factors, 2, raising=False)
    d = rules["money"]["prepaid_discount_rs"]
    hrs = rules["whatsapp"]["give_up_after_hours"]
    if action == "hold":
        why = "; ".join(f["text"] for f in flags) or f"very high risk ({risk_pct:.0f}%): {up}"
        nxt = {
            "fix_address": f"We ask the customer on WhatsApp for the full address; cancel if not fixed in {hrs}h.",
            "confirm_details": f"We ask the customer on WhatsApp to confirm name and address; cancel if no reply in {hrs}h.",
            "pay_online": f"Cash on delivery not offered: we send a pay-online link (Rs {d} off); cancel if unpaid in {hrs}h.",
            "manual_call": "Can't reach them on WhatsApp - ops team to call or check the order.",
            "manual_check": "Ops team to check the order before anything ships.",
        }[ask]
        return f"Hold - {why}. {nxt}"
    if action == "confirm":
        main = f"Confirm on WhatsApp before shipping - {risk_pct:.0f}% chance this COD order comes back"
        main += f" ({up})." if up else "."
    elif action == "nudge":
        main = (f"Offer Rs {d} off to pay online - medium risk ({risk_pct:.0f}%)"
                + (f": {up}." if up else ".") + " If they don't switch, it ships as COD.")
    else:
        main = f"Ship as-is - low risk ({risk_pct:.0f}%)" + (f": {down}." if down else ".")
    return " ".join([main] + notes)


def decide(order: dict, *, rules: dict | None = None, model: dict | None = None, llm=None,
           recent_orders: list[dict] | None = None, llm_cache_only: bool = False,
           assessment: dict | None = None) -> dict:
    rules = rules or load_rules()
    model = model or load_model()
    o = normalize_order(order)

    a = assessment or assess_orders([o], llm=llm, cache_only=llm_cache_only)[0]
    o["_phone"] = a["phone"]["number"]
    sc = score(o, a, model, rules["checks"]["min_orders_to_trust_city_rate"])
    risk_pct = round(sc["risk"] * 100, 1)

    flags = _hard_flags(o, a, rules["hold_rules"])
    band = _band(risk_pct, rules["thresholds"])
    notes, guardrails = [], []
    first_order = o["customer_prior_orders"] == 0

    if flags:
        action = "hold"
    else:
        action = band
        if (action == "hold" and first_order
                and rules["customer_protection"]["never_hold_first_order_on_risk_alone"]):
            action = "confirm"
            guardrails.append("first_order_protected")
            notes.append("Risk is in the hold range, but this is a first-time buyer with no hard red flag, "
                         "so we confirm instead of holding.")
        dup = find_duplicate(o, recent_orders, rules["checks"]["duplicate_window_minutes"])
        if dup and action in ("ship", "nudge"):
            action = "confirm"
            guardrails.append("possible_duplicate")
            notes.append(f"Same phone placed order {dup['order_id']} {dup['minutes_before']} min earlier - "
                         "confirm they want both.")
        if not a["phone"]["valid"] and action in ("confirm", "nudge"):
            # Only reachable if hold_if_phone_invalid was switched off.
            notes.append("Phone looks invalid, so the WhatsApp message may not reach them.")

    ask = _hold_ask(flags) if action == "hold" else None
    evs = (expected_values(sc["risk"], o["order_value"], rules, ask, o["customer_prior_rto"])
           if o["order_value"] > 0 else {})
    unit = unit_economics(o["order_value"], rules, o["customer_prior_rto"])
    from .whatsapp import choose_language  # local import: whatsapp imports engine helpers

    return {
        "order_id": o["order_id"],
        "order_datetime": o["order_datetime"].isoformat(sep=" "),
        "action": action,
        "action_label": ACTION_LABELS[action],
        "risk_pct": risk_pct,
        "risk_band_action": band,
        "reason": _reason(action, risk_pct, sc["factors"], flags, notes, rules, ask),
        "hold_ask": ask,
        "hard_flags": flags,
        "guardrails": guardrails,
        "factors": sc["factors"],
        "base_points": sc["base_points"],
        "checks": {
            "address": a["address"], "name": a["name"], "phone": a["phone"],
            "hinglish_address": a["hinglish"],
            "area": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sc["area"].items()},
        },
        "money": {
            "expected_rs": evs,
            "best_by_money": max(evs, key=evs.get) if evs else None,
            "profit_if_delivered": round(unit["delivered_profit"], 2),
            "loss_if_returned": round(unit["rto_loss"], 2),
            "cost_if_genuine_customer_lost": round(unit["lost_customer_cost"], 2),
        },
        "first_order": first_order,
        "past_rto": o["customer_prior_rto"],
        "whatsapp_language": choose_language(o["state"], o["address"]),
        "llm_used": "llm" in (a["address"]["source"], a["name"]["source"]),
    }
