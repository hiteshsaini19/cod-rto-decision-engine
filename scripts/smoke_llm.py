"""Check your OpenRouter key and model with ONE real request (uses 1-2 of the 50 free daily requests).

    python scripts/smoke_llm.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rto.llm import LLMClient  # noqa: E402


def main():
    llm = LLMClient(use_cache=False)
    if not llm.available:
        sys.exit("No OPENROUTER_API_KEY in .env - the app will use rules only.")
    print("Models tried in order:", ", ".join(llm.models))
    t = time.time()
    out = llm.check_texts([{"id": 0, "name": "Sunita Devi", "address": "Hanuman mandir wali gali, 3rd ghar left side",
                            "city": "Darbhanga", "state": "Bihar", "pincode": "846004",
                            "need_address": True, "need_name": True}])
    print(f"Address check ({time.time() - t:.0f}s):", out[0], "| error:", llm.last_error)
    t = time.time()
    print(f"Reply check:", llm.classify_reply("kal subah bhejna, abhi ghar pe nahi hu", "confirm"),
          f"({time.time() - t:.0f}s) | error:", llm.last_error)


if __name__ == "__main__":
    main()
