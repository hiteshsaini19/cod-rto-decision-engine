"""Print the Ops vs Marketing vs our-system comparison on last month's orders.

    python scripts/run_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rto.backtest import run_backtest  # noqa: E402

NAMES = {"marketing": "Marketing - ship every COD order", "operations": "Ops - cancel >=50% risk + stop COD in bad pincodes",
         "ours": "Our system", "hindsight": "Perfect hindsight (ceiling)"}


def main():
    b = run_backtest()
    m = b["month"]
    print(f"{m['orders']} COD orders {m['from']}..{m['until']} (not used for training), {m['rto_rate']:.0%} came back.")
    print(f"Monthly = Sept x {b['scale_to_month']} (1,650 COD orders/month)\n")
    print(f"{'Policy':52s} {'Rs/month vs Mktg':>16s} {'returns shipped':>16s} {'genuine lost':>13s}")
    for k, name in NAMES.items():
        p = b["policies"][k]
        print(f"{name:52s} {p['monthly_vs_marketing']:>16,} {p['rto_orders_shipped']:>16.1f} {p['genuine_orders_lost']:>13.1f}")
    s = b["sensitivity"]
    print(f"\nOur system if customers react worse / better than assumed: "
          f"{s['pessimistic']['ours']['monthly_vs_marketing']:,} / {s['optimistic']['ours']['monthly_vs_marketing']:,} Rs/month")
    print("\nOur buckets in September:")
    for x in b["our_buckets"]:
        print(f"  {x['label']:26s} {x['orders']:4d} orders ({x['share']:.0%})  predicted {x['avg_predicted_risk']:.0%}  actual {x['actual_rto_rate']:.0%}")


if __name__ == "__main__":
    main()
