"""Part 3 - the founder's morning numbers for one day.

All Rs figures are ESTIMATES built from each order's risk % (we don't know yet which
shipped orders will come back). Compared against "ship every COD order as-is".

  Saved from avoided RTOs
    - customer said NO / cancelled            -> we avoided the full return loss L
      (people who say no to their own order almost never accept the parcel)
    - cancelled by us (no reply / hold)       -> risk% x L
    - switched to prepaid                     -> (risk% - prepaid RTO%) x L
  Lost from cancelled orders that might have been genuine
    - cancelled by us                         -> (1 - risk%) x (profit + cost to win the customer back)

  "risk%" here is UPDATED with what the customer did (see updated_risk): ignoring a
  confirmation makes a return much more likely; paying online makes it less likely.
  Costs                                        -> discounts given + WhatsApp messages
  Extra profit                                 -> would-be returns that now deliver because they paid online
  Net = saved + extra profit - lost - costs
"""
from __future__ import annotations

from .config import ACTION_LABELS
from .economics import unit_economics


def updated_risk(p: float, flow: str, outcome: str, rules: dict, hold_ask: str | None = None) -> float:
    """Risk after we've seen what the customer did.

    Someone who ignores a confirmation is far more likely to be a would-be return than the
    order's starting risk says; someone who pays online is less likely. Same assumptions as the
    backtest:  P(return | what they did) = p x P(did it | return) / P(did it).
    """
    a = {k: v / 100 for k, v in rules["assumptions"].items()}
    if outcome == "cancelled_no_reply":
        if flow == "confirm":
            if_rto, if_genuine = a["confirm_catches_rto_pct"], a["confirm_loses_genuine_pct"]
        elif hold_ask == "pay_online":
            if_rto, if_genuine = 1 - a["nudge_converts_rto_pct"], 1 - a["hold_pay_online_genuine_pct"]
        else:
            if_rto, if_genuine = a["hold_catches_rto_pct"], 1 - a["hold_recovers_genuine_pct"]
    elif outcome == "converted_prepaid":
        if_rto = a["nudge_converts_rto_pct"]
        if_genuine = a["hold_pay_online_genuine_pct"] if flow == "hold" else a["nudge_converts_genuine_pct"]
    else:
        return p
    den = p * if_rto + (1 - p) * if_genuine
    return p * if_rto / den if den > 0 else p


def day_summary(rows: list[dict], rules: dict) -> dict:
    buckets = {a: 0 for a in ACTION_LABELS}
    outcomes: dict[str, int] = {}
    saved = lost = discounts = msg_cost = extra = 0.0
    cancelled_by_customer = cancelled_by_us = genuine_lost_est = 0.0
    first_time_cancelled = 0
    pending = 0
    q = rules["money"]["prepaid_rto_pct"] / 100

    for r in rows:
        d, conv = r["decision"], r.get("conversation")
        buckets[d["action"]] += 1
        outcomes[r["status"]] = outcomes.get(r["status"], 0) + 1
        p = d["risk_pct"] / 100
        value = float(r["order"].get("order_value") or 0)
        u = unit_economics(value, rules, int(d.get("past_rto", 0)))
        D, L, C = u["delivered_profit"], u["rto_loss"], u["lost_customer_cost"]

        if conv:
            for m in conv["messages"]:
                if m["direction"] == "out":
                    msg_cost += u["msg_marketing"] if m["kind"] == "marketing" else u["msg_utility"]
        outcome = conv["outcome"] if conv else None
        if r["status"] in ("waiting_on_customer", "with_team", "manual_review"):
            pending += 1
            continue
        if outcome in ("cancelled_no_reply", "converted_prepaid"):
            p = updated_risk(p, conv["flow"], outcome, rules, conv.get("hold_ask"))
        if outcome == "cancelled_by_customer":
            saved += L
            cancelled_by_customer += 1
        elif outcome == "cancelled_no_reply":
            saved += p * L
            lost += (1 - p) * (D + C)
            genuine_lost_est += 1 - p
            cancelled_by_us += 1
            first_time_cancelled += int(d.get("first_order", False))
        elif outcome == "converted_prepaid":
            saved += max(p - q, 0) * L
            extra += max(p - q, 0) * D
            discounts += u["discount"]

    net = saved + extra - lost - discounts - msg_cost
    return {
        "orders": len(rows),
        "buckets": {ACTION_LABELS[a]: n for a, n in buckets.items()},
        "bucket_keys": buckets,
        "outcomes": outcomes,
        "still_open": pending,
        "money": {
            "saved_from_avoided_rto": round(saved, 0),
            "lost_from_cancelled_genuine": round(lost, 0),
            "extra_profit_from_prepaid": round(extra, 0),
            "discounts_given": round(discounts, 0),
            "whatsapp_cost": round(msg_cost, 0),
            "net_impact": round(net, 0),
        },
        "counts": {
            "cancelled_by_customer": int(cancelled_by_customer),
            "cancelled_by_us": int(cancelled_by_us),
            "est_genuine_among_cancelled_by_us": round(genuine_lost_est, 1),
            "first_time_buyers_cancelled_by_us": first_time_cancelled,
            "converted_to_prepaid": outcomes.get("ship_prepaid", 0),
        },
    }
