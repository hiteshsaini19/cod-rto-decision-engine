import copy

import numpy as np

from rto.engine import decide
from rto.model import auc, fit_logistic

from conftest import FakeLLM


def test_model_file_is_sane(model):
    assert model["tested_on"]["auc"] >= 0.70
    w = model["weights"]
    assert w["past_rto_2plus"] > w["past_rto_1"] > 0
    assert w["addr_unusable"] > w["addr_incomplete"] > 0
    assert w["first_order"] > 0


def test_fit_logistic_recovers_known_weights():
    rng = np.random.default_rng(0)
    X = rng.integers(0, 2, size=(20000, 2)).astype(float)
    true = np.array([-1.0, 1.5, -0.7])
    y = (rng.random(20000) < 1 / (1 + np.exp(-(true[0] + X @ true[1:])))).astype(float)
    w = fit_logistic(X, y, l2=0.0)
    assert np.allclose(w, true, atol=0.1)
    assert auc(y, X @ w[1:]) > 0.6


def test_clean_repeat_customer_ships(good_order, rules, model):
    d = decide(good_order, rules=rules, model=model)
    assert d["action"] == "ship"
    assert d["risk_pct"] < rules["thresholds"]["nudge_from_risk_pct"]
    assert d["reason"].startswith("Ship as-is")
    assert "Mumbai" in d["reason"]                     # place names keep their capital letter
    assert set(d["money"]["expected_rs"]) == {"ship", "nudge", "confirm", "hold"}


def test_junk_address_is_held_and_asked_to_fix(good_order, rules, model):
    d = decide({**good_order, "address": "xyz"}, rules=rules, model=model)
    assert d["action"] == "hold" and d["hold_ask"] == "fix_address"
    assert 'address is just "xyz"' in d["reason"]


def test_fake_name_is_held(good_order, rules, model):
    d = decide({**good_order, "customer_name": "asdf"}, rules=rules, model=model)
    assert d["action"] == "hold" and d["hold_ask"] == "confirm_details"


def test_serial_refuser_must_pay_online(good_order, rules, model):
    d = decide({**good_order, "customer_prior_orders": 4, "customer_prior_rto": 2}, rules=rules, model=model)
    assert d["action"] == "hold" and d["hold_ask"] == "pay_online"
    assert "pay-online link" in d["reason"]


def test_invalid_phone_and_zero_value_go_to_ops(good_order, rules, model):
    assert decide({**good_order, "phone": "723013610"}, rules=rules, model=model)["hold_ask"] == "manual_call"
    assert decide({**good_order, "order_value": 0}, rules=rules, model=model)["hold_ask"] == "manual_check"


def test_hard_rules_can_be_switched_off(good_order, rules, model):
    r = copy.deepcopy(rules)
    r["hold_rules"]["hold_if_fake_name"] = False
    assert decide({**good_order, "customer_name": "asdf"}, rules=r, model=model)["action"] != "hold"


def _risky_first_order(good_order):
    return {**good_order, "customer_prior_orders": 0, "city": "Gorakhpur", "state": "Uttar Pradesh",
            "pincode": "273085", "address": "gali no 4 ke andar, Masjid ke paas", "order_value": 1598,
            "utm_source": "meta_ads"}


def test_first_time_buyer_is_confirmed_not_held(good_order, rules, model):
    o = _risky_first_order(good_order)
    r = copy.deepcopy(rules)
    r["thresholds"]["hold_from_risk_pct"] = 40
    d = decide(o, rules=r, model=model)
    assert d["risk_pct"] >= 40
    assert d["action"] == "confirm" and "first_order_protected" in d["guardrails"]
    r["customer_protection"]["never_hold_first_order_on_risk_alone"] = False
    assert decide(o, rules=r, model=model)["action"] == "hold"


def test_thresholds_from_rules_change_the_action(good_order, rules, model):
    o = _risky_first_order(good_order)
    base = decide(o, rules=rules, model=model)
    r = copy.deepcopy(rules)
    r["thresholds"].update(nudge_from_risk_pct=99, confirm_from_risk_pct=99, hold_from_risk_pct=99)
    assert decide(o, rules=r, model=model)["action"] == "ship"
    r["thresholds"].update(nudge_from_risk_pct=1, confirm_from_risk_pct=2, hold_from_risk_pct=99)
    assert decide(o, rules=r, model=model)["action"] == "confirm"
    assert base["action"] in ("confirm", "nudge")


def test_possible_duplicate_is_confirmed(good_order, rules, model):
    recent = [{"order_id": "T-EARLIER", "order_datetime": "2026-10-30 13:50", "phone": "9876543210"}]
    d = decide(good_order, rules=rules, model=model, recent_orders=recent)
    assert d["action"] == "confirm" and "possible_duplicate" in d["guardrails"]
    assert "T-EARLIER" in d["reason"]
    far = [{"order_id": "T-OLD", "order_datetime": "2026-10-29 10:00", "phone": "9876543210"}]
    assert decide(good_order, rules=rules, model=model, recent_orders=far)["action"] == "ship"


def test_llm_used_for_hinglish_address(good_order, rules, model):
    addr = "Station chowk se left, Hanuman Mandir ke saamne"
    llm = FakeLLM(address={addr: {"quality": "incomplete", "issue": "only landmarks", "english": "x"}})
    d = decide({**good_order, "address": addr}, rules=rules, model=model, llm=llm)
    assert d["llm_used"] and d["checks"]["address"]["source"] == "llm"
    assert d["whatsapp_language"] == "hinglish"


def test_every_decision_has_a_plain_reason(good_order, rules, model):
    variants = [good_order, {**good_order, "address": "xyz"}, _risky_first_order(good_order),
                {**good_order, "customer_prior_rto": 1, "customer_prior_orders": 2}]
    for o in variants:
        d = decide(o, rules=rules, model=model)
        assert len(d["reason"]) > 20
        assert "logit" not in d["reason"] and "nan" not in d["reason"].lower()
