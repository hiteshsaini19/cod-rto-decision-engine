"""Send every 'unclear' address/name in the dataset to the LLM once and cache the answers.

The cache (data/llm_cache.json) is committed, so the risk model can be rebuilt
without spending API requests. Safe to re-run: cached texts are skipped.

    python scripts/fill_llm_cache.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rto.assess import assess_orders  # noqa: E402
from rto.data import load_clean  # noqa: E402
from rto.llm import LLMClient  # noqa: E402


def main():
    llm = LLMClient(timeout=120)
    llm.total_budget = 300          # batch job: slow is fine
    if not llm.available:
        sys.exit("No OPENROUTER_API_KEY in .env - nothing to do (the app still works with rules only).")
    orders = load_clean().to_dict("records")
    res = assess_orders(orders, llm=llm)
    by_source = {}
    for r in res:
        for part in ("address", "name"):
            k = (part, r[part]["source"])
            by_source[k] = by_source.get(k, 0) + 1
    print("requests made:", llm.requests_made, "| last error:", llm.last_error)
    for k, v in sorted(by_source.items()):
        print(k, v)


if __name__ == "__main__":
    main()
