"""Clean the data and (re)learn the risk weights -> config/risk_model.json

    python scripts/build_model.py                    # learn on Apr-Aug, test on Sep (default)
    python scripts/build_model.py --train-until 2026-10-01   # learn on everything

Uses only cached LLM answers (data/llm_cache.json), so it costs no API requests.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rto.config import load_rules  # noqa: E402
from rto.data import build_clean, load_clean  # noqa: E402
from rto.llm import LLMClient  # noqa: E402
from rto.model import build_model, save_model  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-until", default="2026-09-01",
                    help="learn from orders before this date; later orders are used to test")
    args = ap.parse_args()

    report = build_clean()
    print("Cleaning:", json.dumps(report))
    rules = load_rules()
    model = build_model(load_clean(), args.train_until, rules["checks"]["min_orders_to_trust_city_rate"],
                        llm=LLMClient())
    save_model(model)
    print("Trained on:", model["trained_on"])
    print("Weights (log-odds):")
    for f, w in sorted(model["weights"].items(), key=lambda x: -abs(x[1])):
        print(f"  {f:16s} {w:+.2f}   {model['labels'][f]}")
    print(f"  intercept        {model['intercept']:+.2f}")
    if "tested_on" in model:
        t = model["tested_on"]
        print(f"Tested on {t['orders']} orders {t['from']}..{t['until']}: AUC {t['auc']}")
        for c in t["calibration"]:
            print(f"  risk {c['band']:12s} orders {c['orders']:4d}  predicted {c['predicted']:.0%}  actual {c['actual']:.0%}")


if __name__ == "__main__":
    main()
