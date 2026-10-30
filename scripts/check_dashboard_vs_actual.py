"""Sanity check: does the dashboard's ESTIMATE match what really happened?

Demo orders keep their real outcome (delivered / RTO), so we can compare the dashboard's
estimated net Rs with the real net Rs for the same chats.

    python scripts/check_dashboard_vs_actual.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rto.config import load_rules  # noqa: E402
from rto.dashboard import day_summary  # noqa: E402
from rto.economics import unit_economics  # noqa: E402
from rto.store import Store  # noqa: E402


def actual_net(rows, rules):
    q = rules["money"]["prepaid_rto_pct"] / 100
    total = 0.0
    for r in rows:
        if r["actual_outcome"] is None:
            continue
        rto = r["actual_outcome"] == "RTO"
        u = unit_economics(float(r["order"]["order_value"] or 0), rules, int(r["decision"].get("past_rto", 0)))
        D, L, C = u["delivered_profit"], u["rto_loss"], u["lost_customer_cost"]
        msgs = sum((u["msg_marketing"] if m["kind"] == "marketing" else u["msg_utility"])
                   for m in (r["conversation"] or {}).get("messages", []) if m["direction"] == "out")
        total -= msgs
        if r["status"] == "cancelled":
            total += L if rto else -(D + C)
        elif r["status"] == "ship_prepaid":
            total += ((1 - q) * (L + D) if rto else 0) - u["discount"]
    return total


def main():
    rules = load_rules()
    rows = [r for r in Store().list_orders(limit=1000000, with_conversations=True) if r["demo"]]
    if not rows:
        sys.exit("No demo data - click 'Load demo data' on the dashboard (or POST /demo/seed) first.")
    est = day_summary(rows, rules)["money"]["net_impact"]
    act = actual_net(rows, rules)
    print(f"{len(rows)} demo orders | dashboard estimate {est:+,.0f} Rs | what really happened {act:+,.0f} Rs")


if __name__ == "__main__":
    main()
