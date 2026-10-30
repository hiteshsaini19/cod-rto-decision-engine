"""Backend API (FastAPI).

Run:  uvicorn backend.main:app --reload --port 8000
Docs: http://localhost:8000/docs  (try every endpoint from the browser)
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from rto import config  # noqa: E402
from rto.backtest import run_backtest  # noqa: E402
from rto.config import load_rules, save_rules  # noqa: E402
from rto.dashboard import day_summary  # noqa: E402
from rto.demo import seed_demo  # noqa: E402
from rto.economics import max_affordable_discount, suggest_thresholds  # noqa: E402
from rto.engine import decide, normalize_order  # noqa: E402
from rto.llm import get_llm  # noqa: E402
from rto.model import load_model  # noqa: E402
from rto.store import Store  # noqa: E402
from rto.whatsapp import handle_reply, payment_completed, start_conversation, tick  # noqa: E402

app = FastAPI(title="COD RTO Decision Engine", version="1.0",
              description="Decides ship / confirm / nudge / hold for every COD order, runs the mock "
                          "WhatsApp flows and serves the founder dashboard.")
store = Store(config.DB_PATH)
_backtest_cache: dict = {}


class OrderIn(BaseModel):
    order_id: str | None = None
    order_datetime: str | None = Field(None, description="YYYY-MM-DD HH:MM; empty = now")
    customer_name: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    pincode: str = ""
    order_value: float = Field(..., ge=0)
    items: str = ""
    num_items: int = Field(1, ge=0)
    customer_prior_orders: int = Field(0, ge=0)
    customer_prior_rto: int = Field(0, ge=0)
    utm_source: str = ""
    courier: str = ""
    payment_method: str = "COD"


class ReplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class AdvanceIn(BaseModel):
    hours: float = Field(..., gt=0, le=72)


def _decide(order: dict, use_llm: bool) -> tuple[dict, dict]:
    o = normalize_order(order)
    since = (o["order_datetime"] - timedelta(days=1)).isoformat(sep=" ")
    d = decide(o, rules=load_rules(), llm=get_llm() if use_llm else None,
               recent_orders=store.recent_orders(since))
    return o, d


# ------------------------------------------------------------------ health / model
@app.get("/health")
def health():
    llm = get_llm()
    m = load_model()
    return {"status": "ok", "llm_configured": llm.available, "llm_models": llm.models,
            "llm_last_error": llm.last_error, "model_trained_on": m["trained_on"],
            "model_test_auc": m.get("tested_on", {}).get("auc")}


@app.get("/model")
def model_info():
    m = load_model()
    return {k: m[k] for k in ("built_at", "trained_on", "tested_on", "intercept", "weights", "labels")}


# ------------------------------------------------------------------ Part 1: decisions
@app.post("/decide", summary="Decide an order without saving it")
def decide_only(order: OrderIn, use_llm: bool = True):
    _, d = _decide(order.model_dump(), use_llm)
    return d


@app.post("/orders", summary="Decide, save and start the WhatsApp flow")
def create_order(order: OrderIn, use_llm: bool = True):
    if order.order_id and store.get_order(order.order_id):
        raise HTTPException(409, f"Order {order.order_id} already exists")
    o, d = _decide(order.model_dump(), use_llm)
    conv = start_conversation(o, d, load_rules())
    store.save_order(o, d, conv)
    return {"decision": d, "conversation": conv, "status": store.status_for(d, conv)}


@app.get("/orders")
def list_orders(date: str | None = None, limit: int = 200):
    rows = store.list_orders(date, limit)
    return [{"order_id": r["order_id"], "order_datetime": r["decision"]["order_datetime"],
             "customer_name": r["order"].get("customer_name"), "city": r["order"].get("city"),
             "order_value": r["order"].get("order_value"), "action": r["action"],
             "action_label": r["decision"]["action_label"], "risk_pct": r["risk_pct"],
             "status": r["status"], "reason": r["decision"]["reason"], "demo": r["demo"]} for r in rows]


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    r = store.get_order(order_id)
    if not r:
        raise HTTPException(404, "Order not found")
    return r


@app.delete("/orders")
def clear_orders(demo_only: bool = True):
    return {"deleted": store.clear(demo_only=demo_only)}


# ------------------------------------------------------------------ Part 2: mock WhatsApp
def _conv_or_404(order_id: str) -> dict:
    conv = store.get_conversation(order_id)
    if not conv:
        raise HTTPException(404, "No WhatsApp conversation for this order")
    return conv


@app.get("/conversations")
def list_conversations(open_only: bool = False, limit: int = 200):
    return store.list_conversations(open_only, limit)


@app.get("/conversations/{order_id}")
def get_conversation(order_id: str):
    conv = _conv_or_404(order_id)
    return {"conversation": conv, "order_status": store.get_order(order_id)["status"]}


@app.post("/whatsapp/{order_id}/reply", summary="Mock incoming WhatsApp message from the customer")
def customer_reply(order_id: str, body: ReplyIn, use_llm: bool = True):
    rules = load_rules()
    conv = _conv_or_404(order_id)
    now = datetime.fromisoformat(conv["clock"]) + timedelta(minutes=2)
    tick(conv, now, rules)            # anything that was due happens first
    result = handle_reply(conv, body.text, rules, llm=get_llm() if use_llm else None, now=now)
    status = store.save_conversation(conv)
    return {"result": result, "order_status": status, "conversation": conv}


@app.post("/whatsapp/{order_id}/advance", summary="Move this chat's clock forward (test 'no reply')")
def advance_time(order_id: str, body: AdvanceIn):
    rules = load_rules()
    conv = _conv_or_404(order_id)
    events = tick(conv, datetime.fromisoformat(conv["clock"]) + timedelta(hours=body.hours), rules)
    status = store.save_conversation(conv)
    return {"events": events, "order_status": status, "conversation": conv}


@app.post("/payments/{order_id}/complete", summary="Mock payment gateway: customer paid the link")
def complete_payment(order_id: str):
    rules = load_rules()
    conv = _conv_or_404(order_id)
    if not payment_completed(conv, rules, datetime.fromisoformat(conv["clock"]) + timedelta(minutes=3)):
        raise HTTPException(400, "This order is not waiting for a payment")
    status = store.save_conversation(conv)
    return {"order_status": status, "conversation": conv}


# ------------------------------------------------------------------ Part 3: dashboard
@app.get("/dashboard/dates")
def dashboard_dates():
    return store.dates()


@app.get("/dashboard")
def dashboard(day: str | None = None):
    """Founder's numbers for one day (default: yesterday)."""
    day = day or (date.today() - timedelta(days=1)).isoformat()
    rows = store.list_orders(day, limit=100000, with_conversations=True)
    out = day_summary(rows, load_rules())
    out["date"] = day
    out["is_yesterday"] = day == (date.today() - timedelta(days=1)).isoformat()
    out["has_demo_data"] = any(r["demo"] for r in rows)
    return out


@app.get("/dashboard/range", summary="Daily numbers for a date range (for the trend chart)")
def dashboard_range(start: str, end: str):
    rows = [r for r in store.list_orders(None, limit=1000000, with_conversations=True)
            if start <= r["order_date"] <= end]
    by_day: dict[str, list] = {}
    for r in rows:
        by_day.setdefault(r["order_date"], []).append(r)
    rules = load_rules()
    out = []
    for day in sorted(by_day):
        s = day_summary(by_day[day], rules)
        out.append({"date": day, "orders": s["orders"], **s["bucket_keys"], **s["money"]})
    return out


@app.post("/demo/seed", summary="Replay September's real orders as the last 30 days (simulated replies)")
def demo_seed(days: int = 30):
    return seed_demo(days=days, store=store)


# ------------------------------------------------------------------ settings
@app.get("/settings")
def get_settings():
    rules = load_rules()
    return {"rules": rules, "suggested": suggest_thresholds(rules, 649),
            "max_discount_examples": {f"{p}%": round(max_affordable_discount(p / 100, 649, rules), 0)
                                      for p in (10, 15, 20, 25, 30)}}


@app.put("/settings", summary="Change rules (same as editing config/rules.yaml)")
def put_settings(updates: dict):
    try:
        rules = save_rules(updates)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))
    _backtest_cache.clear()
    return {"rules": rules}


# ------------------------------------------------------------------ Part 4 support: backtest
@app.get("/backtest", summary="All policies on last month's real orders (Ops vs Marketing vs ours)")
def backtest():
    key = (config.RULES_PATH.stat().st_mtime, config.MODEL_PATH.stat().st_mtime)
    if key not in _backtest_cache:
        _backtest_cache.clear()
        _backtest_cache[key] = run_backtest()
    return _backtest_cache[key]
