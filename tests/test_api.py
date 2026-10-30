"""End-to-end through the HTTP API (no LLM, temp database, temp rules file)."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.main import app, store

client = TestClient(app)

GOOD = dict(customer_name="Neha Mishra", phone="9876543210", address="Flat 408, Royal Apartments, Mall Road",
            city="Mumbai", state="Maharashtra", pincode="400050", order_value=599, items="Satin Bonnet",
            customer_prior_orders=3, customer_prior_rto=0, utm_source="direct")
RISKY_FIRST = dict(GOOD, customer_prior_orders=0, city="Gorakhpur", state="Uttar Pradesh", pincode="273085",
                   address="gali no 4 ke andar, Masjid ke paas", order_value=1598, utm_source="meta_ads")


@pytest.fixture(autouse=True)
def clean_db():
    store.clear()
    yield
    store.clear()


def _post(order, oid, when="2026-10-30 11:00"):
    r = client.post("/orders?use_llm=false", json={**order, "order_id": oid, "order_datetime": when})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_model():
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["llm_configured"] is False and h["model_test_auc"] >= 0.7
    assert "weights" in client.get("/model").json()


def test_decide_does_not_save():
    d = client.post("/decide?use_llm=false", json={**GOOD, "order_id": "X1"}).json()
    assert d["action"] == "ship" and client.get("/orders/X1").status_code == 404


def test_validation_errors():
    assert client.post("/decide", json={**GOOD, "order_value": -5}).status_code == 422
    _post(GOOD, "DUP1")
    assert client.post("/orders?use_llm=false", json={**GOOD, "order_id": "DUP1"}).status_code == 409


def test_ship_order_has_no_chat():
    out = _post(GOOD, "S1")
    assert out["decision"]["action"] == "ship" and out["conversation"] is None and out["status"] == "ship_cod"
    assert client.get("/conversations/S1").status_code == 404


def test_confirmation_flow_over_http():
    out = _post(RISKY_FIRST, "C1")
    assert out["decision"]["action"] == "confirm" and out["status"] == "waiting_on_customer"
    assert out["conversation"]["language"] == "hinglish"
    r = client.post("/whatsapp/C1/reply?use_llm=false", json={"text": "haan bhej do"}).json()
    assert r["result"]["outcome"] == "confirmed" and r["order_status"] == "ship_cod"
    assert client.get("/orders/C1").json()["status"] == "ship_cod"


def test_no_reply_flow_over_http():
    _post(RISKY_FIRST, "C2")
    r = client.post("/whatsapp/C2/advance", json={"hours": 13}).json()
    assert r["events"] == ["reminder"]
    r = client.post("/whatsapp/C2/advance", json={"hours": 12}).json()
    assert r["order_status"] == "cancelled"
    # a late reply is routed to the team, the order stays cancelled
    r = client.post("/whatsapp/C2/reply?use_llm=false", json={"text": "yes"}).json()
    assert r["result"]["intent"] == "after_close" and r["order_status"] == "cancelled"


def test_payment_flow_over_http():
    _post(RISKY_FIRST, "C3")
    assert client.post("/payments/C3/complete").status_code == 400      # nothing to pay yet
    client.post("/whatsapp/C3/reply?use_llm=false", json={"text": "PAY"})
    r = client.post("/payments/C3/complete").json()
    assert r["order_status"] == "ship_prepaid"


def test_hold_address_flow_over_http():
    out = _post(dict(GOOD, address="xyz", customer_prior_orders=0), "H1")
    assert out["decision"]["action"] == "hold" and out["conversation"]["status"] == "awaiting_address"
    r = client.post("/whatsapp/H1/reply?use_llm=false",
                    json={"text": "Flat 12, Lotus Apartments, Ring Road, Mumbai 400050"}).json()
    assert r["order_status"] == "ship_cod"


def test_manual_review_hold():
    out = _post(dict(GOOD, phone="723013610"), "M1")
    assert out["status"] == "manual_review" and out["conversation"] is None


def test_dashboard_for_a_day():
    _post(GOOD, "D1")
    _post(RISKY_FIRST, "D2")
    _post(dict(GOOD, address="xyz", customer_prior_orders=0), "D3")
    _post(dict(RISKY_FIRST, phone="9811111111"), "D4")
    client.post("/whatsapp/D2/reply?use_llm=false", json={"text": "NO"})          # customer cancels
    client.post("/whatsapp/D3/advance", json={"hours": 25})                        # we cancel, no reply
    client.post("/whatsapp/D4/reply?use_llm=false", json={"text": "PAY"})
    client.post("/payments/D4/complete")
    d = client.get("/dashboard?day=2026-10-30").json()
    assert d["orders"] == 4
    assert d["bucket_keys"] == {"ship": 1, "confirm": 2, "nudge": 0, "hold": 1}
    m = d["money"]
    assert m["saved_from_avoided_rto"] > 169            # at least the full loss on the customer's "NO"
    assert m["lost_from_cancelled_genuine"] > 0         # D3 might have been genuine
    assert m["discounts_given"] == 50
    assert m["net_impact"] == pytest.approx(m["saved_from_avoided_rto"] + m["extra_profit_from_prepaid"]
                                            - m["lost_from_cancelled_genuine"] - m["discounts_given"]
                                            - m["whatsapp_cost"], abs=2)
    assert client.get("/dashboard/dates").json()[0] == {"date": "2026-10-30", "orders": 4}


def test_dashboard_defaults_to_yesterday():
    d = client.get("/dashboard").json()
    assert d["date"] == (date.today() - timedelta(days=1)).isoformat() and d["is_yesterday"]


def test_settings_change_applies_to_next_order(tmp_rules_file):
    assert client.get("/settings").json()["rules"]["thresholds"]["hold_from_risk_pct"] == 75
    bad = client.put("/settings", json={"thresholds": {"nudge_from_risk_pct": 80}})
    assert bad.status_code == 400 and "order" in bad.json()["detail"]
    assert client.put("/settings", json={"thresholds": {"nope": 1}}).status_code == 400
    ok = client.put("/settings", json={"thresholds": {"nudge_from_risk_pct": 1, "confirm_from_risk_pct": 2}})
    assert ok.status_code == 200
    assert client.post("/decide?use_llm=false", json=GOOD).json()["action"] == "confirm"
    assert "# =====" in tmp_rules_file.read_text(encoding="utf-8")            # comments kept


def test_backtest_endpoint():
    b = client.get("/backtest").json()
    p = b["policies"]
    assert b["month"]["orders"] > 300
    assert p["hindsight"]["total"] >= p["ours"]["total"] > p["operations"]["total"]
    assert p["ours"]["rto_orders_shipped"] < p["marketing"]["rto_orders_shipped"]
    assert sum(x["orders"] for x in b["our_buckets"]) == b["month"]["orders"]


def test_demo_seed_fills_yesterday():
    out = client.post("/demo/seed?days=3").json()
    assert out["to"] == (date.today() - timedelta(days=1)).isoformat() and out["orders"] > 0
    d = client.get("/dashboard").json()
    assert d["orders"] > 0 and d["has_demo_data"] and d["still_open"] <= d["orders"]
    assert client.delete("/orders?demo_only=true").json()["deleted"] == out["orders"]
