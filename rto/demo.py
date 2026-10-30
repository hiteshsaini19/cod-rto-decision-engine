"""Demo data for the dashboard: replay September's real orders as if they happened recently.

Dates are shifted so the last September day becomes "yesterday". Every order goes through
the real engine and the real WhatsApp flow; only the customer's replies are simulated - using
each order's REAL outcome plus the behaviour assumptions in rules.yaml (e.g. 45% of would-be
returns say NO or ignore the confirmation). Demo rows are flagged and can be cleared.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pandas as pd

from .config import load_rules
from .data import load_clean
from .engine import decide
from .llm import LLMClient
from .model import load_model
from .store import Store
from .whatsapp import handle_reply, payment_completed, start_conversation, tick

YES_REPLIES = ["YES", "haan bhej do", "ok", "Yes please", "👍", "ji haan", "confirm"]
NO_REPLIES = ["NO", "nahi chahiye", "cancel", "no thanks", "mat bhejo"]
STREETS = ["MG Road", "Station Road", "Gandhi Nagar", "Nehru Marg", "Tilak Road", "Ring Road"]


def _simulate(conv, rto: bool, rules, rnd: random.Random):
    """Play the customer's side of the chat."""
    a = rules["assumptions"]
    t = datetime.fromisoformat(conv["send_at"]) + timedelta(minutes=rnd.randint(10, 360))

    def reply(text):
        nonlocal t
        handle_reply(conv, text, rules, now=t)
        t += timedelta(minutes=rnd.randint(1, 30))

    def pay():
        reply("1" if conv["flow"] != "confirm" else "PAY")
        payment_completed(conv, rules, now=t)

    if conv["flow"] == "confirm":
        if rto and rnd.random() < a["confirm_catches_rto_pct"] / 100:
            if rnd.random() < 0.5:
                reply(rnd.choice(NO_REPLIES))
        elif not rto and rnd.random() < a["confirm_loses_genuine_pct"] / 100:
            pass                                    # genuine buyer who never sees the message
        else:
            if rnd.random() < 0.15:
                reply("kab tak aayega?")
            reply(rnd.choice(YES_REPLIES))
    elif conv["flow"] == "nudge":
        rate = a["nudge_converts_rto_pct"] if rto else a["nudge_converts_genuine_pct"]
        if rnd.random() < rate / 100:
            pay()
        elif rnd.random() < (0.3 if rto else 0.5):
            reply("2")
    else:  # hold
        if not rto and rnd.random() < a["hold_recovers_genuine_pct"] / 100:
            if conv["status"] == "awaiting_address":
                o = conv["order"]
                reply(f"House No. {rnd.randint(1, 999)}, {rnd.choice(STREETS)}, {o.get('city') or ''} {o.get('pincode') or ''}")
            else:
                pay()
        elif rnd.random() < 0.2:
            reply(rnd.choice(NO_REPLIES))
    tick(conv, datetime.fromisoformat(conv["deadline"]) + timedelta(minutes=1), rules)


def seed_demo(days: int = 30, seed: int = 7, store: Store | None = None, yesterday: date | None = None) -> dict:
    rules, model = load_rules(), load_model()
    store = store or Store()
    store.clear(demo_only=True)
    df = load_clean()
    last = df["order_datetime"].max().normalize()
    month = df[df["order_datetime"] >= last - pd.Timedelta(days=days - 1)]
    yesterday = yesterday or (date.today() - timedelta(days=1))
    shift = pd.Timestamp(yesterday) - last
    rnd = random.Random(seed)
    llm = LLMClient()
    recent = [{"order_id": r.order_id, "order_datetime": r.order_datetime + shift, "phone": r.phone_clean}
              for r in df.itertuples()]
    counts = {}
    for o in month.to_dict("records"):
        o = dict(o)
        o["order_datetime"] = (o["order_datetime"] + shift).to_pydatetime()
        o["phone"] = o["phone_clean"] or o["phone"]
        d = decide(o, rules=rules, model=model, llm=llm, llm_cache_only=True, recent_orders=recent)
        conv = start_conversation(o, d, rules)
        if conv:
            _simulate(conv, bool(o["rto"]), rules, rnd)
        clean = {k: v for k, v in o.items() if k not in ("rto", "final_status", "phone_valid", "phone_clean")}
        store.save_order(clean, d, conv, demo=True, actual_outcome="RTO" if o["rto"] else "DELIVERED")
        counts[d["action"]] = counts.get(d["action"], 0) + 1
    return {"orders": len(month), "from": str((month["order_datetime"].min() + shift).date()),
            "to": str(yesterday), "actions": counts}
