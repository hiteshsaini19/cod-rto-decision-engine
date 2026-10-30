"""Run every policy on last month's real orders (September 2026 - the model never saw them).

Policies
  marketing  : ship every COD order (what Marketing wants)
  operations : cancel every risky order + stop COD in pincodes with bad history (what Ops wants)
  ours       : the decision engine (ship / nudge / confirm / hold)
  hindsight  : cancel exactly the orders that came back - the best anyone could do

We know each order's real outcome (delivered / RTO). Where a policy depends on how a customer
would react (reply to WhatsApp, pay online), the assumptions in rules.yaml are applied as
expected values - and a pessimistic / optimistic run shows how much that matters.
"""
from __future__ import annotations

import copy

import pandas as pd

from .config import ACTION_LABELS, load_rules
from .data import load_clean
from .economics import outcome_parts
from .engine import decide
from .llm import LLMClient
from .model import load_model

SCENARIOS = {
    "pessimistic": {"confirm_catches_rto_pct": 25, "confirm_loses_genuine_pct": 10,
                    "nudge_converts_genuine_pct": 15, "nudge_converts_rto_pct": 5,
                    "hold_recovers_genuine_pct": 60, "hold_catches_rto_pct": 50, "hold_pay_online_genuine_pct": 25},
    "optimistic": {"confirm_catches_rto_pct": 60, "confirm_loses_genuine_pct": 3,
                   "nudge_converts_genuine_pct": 40, "nudge_converts_rto_pct": 15,
                   "hold_recovers_genuine_pct": 90, "hold_catches_rto_pct": 85, "hold_pay_online_genuine_pct": 55},
}
SUM_KEYS = ("total", "delivered_profit", "rto_loss", "genuine_lost", "discount", "messages",
            "rto_avoided", "genuine_orders_lost", "rto_orders_shipped")


def bad_pincodes(train: pd.DataFrame, min_orders: int = 2, min_rate: float = 0.5) -> set:
    """Ops' idea of a 'bad history' pincode: 2+ past orders and half or more came back."""
    g = train.dropna(subset=["pincode"]).groupby("pincode")["rto"].agg(["size", "mean"])
    return set(g[(g["size"] >= min_orders) & (g["mean"] >= min_rate)].index)


def decide_month(rules: dict | None = None, model: dict | None = None) -> pd.DataFrame:
    """Run the engine on every test-month order. Returns one row per order with its decision."""
    rules = rules or load_rules()
    model = model or load_model()
    df = load_clean()
    start = pd.Timestamp(model["tested_on"]["from"])
    test = df[df["order_datetime"] >= start]
    recent = [{"order_id": r.order_id, "order_datetime": r.order_datetime, "phone": r.phone_clean}
              for r in df.itertuples()]
    llm = LLMClient()
    rows = []
    for o in test.to_dict("records"):
        d = decide(o, rules=rules, model=model, llm=llm, llm_cache_only=True, recent_orders=recent)
        rows.append({"order_id": o["order_id"], "order_datetime": o["order_datetime"], "rto": int(o["rto"]),
                     "order_value": float(o["order_value"]), "first_order": d["first_order"],
                     "risk": d["risk_pct"] / 100, "action": d["action"], "pincode": o["pincode"],
                     "hold_ask": d["hold_ask"], "past_rto": int(o["customer_prior_rto"]), "reason": d["reason"], "decision": d})
    return pd.DataFrame(rows)


def _policy_totals(month: pd.DataFrame, actions: pd.Series, rules: dict) -> dict:
    tot = {k: 0.0 for k in SUM_KEYS}
    first_lost = 0.0
    for (_, r), act in zip(month.iterrows(), actions):
        parts = outcome_parts(act, float(r["rto"]), r["order_value"], rules, r["hold_ask"], r["past_rto"])
        for k in SUM_KEYS:
            tot[k] += parts[k]
        if r["first_order"]:
            first_lost += parts["genuine_orders_lost"]
    tot["first_time_genuine_lost"] = first_lost
    tot["orders_not_shipped_cod"] = int((actions != "ship").sum())
    return tot


OPS_CANCEL_FROM_RISK = 0.50   # Ops' "risky": more likely than a coin flip to come back


def ops_actions(month: pd.DataFrame, bad_pins: set, ops_cut: float = OPS_CANCEL_FROM_RISK) -> pd.Series:
    return month.apply(lambda r: "cancel" if r["risk"] >= ops_cut
                      else ("prepaid_only" if r["pincode"] in bad_pins else "ship"), axis=1)


def policy_actions(month: pd.DataFrame, rules: dict, bad_pins: set) -> dict[str, pd.Series]:
    ops = ops_actions(month, bad_pins)
    return {
        "marketing": pd.Series(["ship"] * len(month), index=month.index),
        "operations": ops,
        "ours": month["action"],
        "hindsight": month["rto"].map(lambda y: "cancel" if y else "ship"),
    }


def run_backtest(rules: dict | None = None, model: dict | None = None, month: pd.DataFrame | None = None) -> dict:
    rules = rules or load_rules()
    model = model or load_model()
    month = month if month is not None else decide_month(rules, model)
    df = load_clean()
    train = df[df["order_datetime"] < pd.Timestamp(model["tested_on"]["from"])]
    pins = bad_pincodes(train)
    scale = rules["money"]["cod_orders_per_month"] / len(month)
    acts = policy_actions(month, rules, pins)

    def summarise(rules_used):
        out = {}
        for name, a in acts.items():
            t = _policy_totals(month, a, rules_used)
            out[name] = {k: round(v, 1) for k, v in t.items()}
            out[name]["monthly_total"] = round(t["total"] * scale)
        base = out["marketing"]["total"]
        for name in out:
            out[name]["vs_marketing"] = round(out[name]["total"] - base, 1)
            out[name]["monthly_vs_marketing"] = round((out[name]["total"] - base) * scale)
        return out

    policies = summarise(rules)
    base_total = policies["marketing"]["total"]
    ops_variants = []
    for cut in (0.35, 0.50, 0.70):
        for block in (True, False):
            t = _policy_totals(month, ops_actions(month, pins if block else set(), cut), rules)
            ops_variants.append({"cancel_from_risk_pct": int(cut * 100), "block_bad_pincodes": block,
                                 "orders_not_shipped_cod": t["orders_not_shipped_cod"],
                                 "genuine_orders_lost": round(t["genuine_orders_lost"], 1),
                                 "monthly_vs_marketing": round((t["total"] - base_total) * scale)})
    sensitivity = {}
    for scen, vals in SCENARIOS.items():
        r2 = copy.deepcopy(rules)
        r2["assumptions"].update(vals)
        s = summarise(r2)
        sensitivity[scen] = {n: {"monthly_vs_marketing": s[n]["monthly_vs_marketing"]} for n in s}

    buckets = []
    for act in ("ship", "nudge", "confirm", "hold"):
        m = month[month["action"] == act]
        buckets.append({"action": act, "label": ACTION_LABELS[act], "orders": int(len(m)),
                        "share": round(len(m) / len(month), 3),
                        "avg_predicted_risk": round(float(m["risk"].mean()), 3) if len(m) else None,
                        "actual_rto_rate": round(float(m["rto"].mean()), 3) if len(m) else None,
                        "first_time_buyers": int(m["first_order"].sum())})
    return {
        "month": {"from": str(month["order_datetime"].min().date()), "until": str(month["order_datetime"].max().date()),
                  "orders": int(len(month)), "rto_orders": int(month["rto"].sum()),
                  "rto_rate": round(float(month["rto"].mean()), 3),
                  "first_time_orders": int(month["first_order"].sum())},
        "scale_to_month": round(scale, 2),
        "ops_rules": {"cancel_from_risk_pct": int(OPS_CANCEL_FROM_RISK * 100),
                      "bad_pincodes": len(pins),
                      "orders_in_bad_pincodes": int(month["pincode"].isin(pins).sum()),
                      "rto_rate_in_bad_pincodes": round(float(month[month["pincode"].isin(pins)]["rto"].mean()), 3)
                      if month["pincode"].isin(pins).any() else None},
        "policies": policies,
        "ops_variants": ops_variants,
        "sensitivity": sensitivity,
        "our_buckets": buckets,
    }
