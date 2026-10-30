"""Smoke test of every front-end page against a RUNNING backend (no browser needed).

    uvicorn backend.main:app --port 8000      # in another terminal
    python scripts/check_frontend.py
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "frontend" / "app.py")
PAGES = ["home.py", "views/1_check_order.py", "views/2_whatsapp.py", "views/3_dashboard.py",
         "views/4_ops_vs_marketing.py", "views/5_settings.py"]


def run_page(page, timeout=120):
    at = AppTest.from_file(APP, default_timeout=timeout)
    at.run()
    if page != "home.py":
        at.switch_page(page)
        at.run()
    return at


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failed = 0
    for page in PAGES:
        at = run_page(page)
        errors = [e.value for e in at.exception] + [e.value for e in at.error]
        title = at.title[0].value if at.title else "?"
        print(f"{'FAIL' if errors else 'ok  '} {page:32s} title={title!r} metrics={len(at.metric)} tables={len(at.dataframe)}")
        for e in errors:
            print("     ", str(e)[:300])
        failed += bool(errors)

    # Interactions: decide an order (rules only), then place it and reply on WhatsApp.
    at = run_page("views/1_check_order.py")
    at.selectbox[0].select("Hinglish address, first order, Gorakhpur").run()
    at.toggle[0].set_value(False).run()
    at.button[0].click().run()                       # Check only
    shown = [m.value for m in at.markdown if "Reason" in m.value]
    print("decide:", shown[0][:140] if shown else "NO REASON SHOWN")
    failed += not shown
    at.button[1].click().run()                       # Place order
    ok = [s.value for s in at.success]
    print("placed:", ok[0][:100] if ok else "NOT PLACED")
    failed += not ok

    at2 = run_page("views/2_whatsapp.py")
    at2.session_state["chat_order"] = at.session_state["chat_order"]
    at2.run()
    before = len(at2.chat_message)
    at2.chat_input[0].set_value("haan bhej do").run()
    after = len(at2.chat_message)
    status = [m.value for m in at2.markdown if m.value.startswith("### ")]
    print(f"whatsapp: chat bubbles {before} -> {after}, status {status[:1]}")
    failed += not (after > before)

    print("\nALL PAGES OK" if not failed else f"\n{failed} PROBLEM(S)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
