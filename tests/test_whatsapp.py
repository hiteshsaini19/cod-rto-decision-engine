import copy
from datetime import datetime, timedelta

import pytest

from rto.engine import decide, normalize_order
from rto.whatsapp import (
    choose_language,
    handle_reply,
    next_send_time,
    payment_completed,
    rule_intent,
    start_conversation,
    tick,
)

from conftest import FakeLLM


def _conv(order, rules, model, action=None, **changes):
    o = normalize_order({**order, **changes})
    d = decide(o, rules=rules, model=model)
    if action:
        d["action"] = action
    return start_conversation(o, d, rules)


def _after(conv, hours):
    return datetime.fromisoformat(conv["send_at"]) + timedelta(hours=hours)


# ---------------------------------------------------------------- language & timing
def test_language_choice():
    assert choose_language("Uttar Pradesh", "Flat 1, MG Road") == "hinglish"
    assert choose_language("Karnataka", "Flat 1, MG Road") == "english"
    assert choose_language("Karnataka", "Mandir ke saamne, gali no 2 ke andar") == "hinglish"


def test_quiet_hours(rules):
    assert next_send_time(datetime(2026, 10, 30, 22, 30), rules) == datetime(2026, 10, 31, 9, 0)
    assert next_send_time(datetime(2026, 10, 30, 3, 0), rules) == datetime(2026, 10, 30, 9, 0)
    assert next_send_time(datetime(2026, 10, 30, 14, 0), rules) == datetime(2026, 10, 30, 14, 0)


def test_night_order_message_waits_till_9am(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm", order_datetime="2026-10-30 23:15")
    assert c["send_at"] == "2026-10-31 09:00:00"
    assert c["messages"][0]["direction"] == "system"


def test_ship_decision_starts_no_chat(good_order, rules, model):
    o = normalize_order(good_order)
    assert start_conversation(o, decide(o, rules=rules, model=model), rules) is None


# ---------------------------------------------------------------- reply understanding
@pytest.mark.parametrize("text,flow,intent", [
    ("YES", "confirm", "yes"), ("haan bhej do", "confirm", "yes"), ("Ok", "confirm", "yes"), ("👍", "confirm", "yes"),
    ("NO", "confirm", "no"), ("nahi chahiye", "confirm", "no"), ("cancel kar do", "confirm", "cancel"),
    ("PAY", "confirm", "pay_online"), ("1", "nudge", "pay_online"), ("2", "nudge", "keep_cod"),
    ("no", "nudge", "keep_cod"),            # "no" to a discount is not "cancel my order"
    ("cancel", "nudge", "cancel"), ("cod", "nudge", "keep_cod"), ("yes", "nudge", "pay_online"),
    ("kab tak aayega?", "confirm", "question"), ("address change karna hai", "confirm", "change_address"),
    ("hindi", "confirm", "lang_hindi"), ("asdkjh", "confirm", None),
])
def test_rule_intent(text, flow, intent):
    assert rule_intent(text, flow, "waiting") == intent


# ---------------------------------------------------------------- confirmation flow
def test_confirm_yes_ships(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    assert "YES" in c["messages"][-1]["text"] and c["messages"][-1]["buttons"] == ["YES", "NO", "PAY"]
    r = handle_reply(c, "haan bhej do", rules, now=_after(c, 1))
    assert r["outcome"] == "confirmed" and c["status"] == "closed"


def test_confirm_no_cancels(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    assert handle_reply(c, "NO", rules, now=_after(c, 1))["outcome"] == "cancelled_by_customer"


def test_confirm_random_text_reasks_then_hands_to_human(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    handle_reply(c, "asdkjh", rules, now=_after(c, 1))
    assert c["status"] == "waiting" and c["messages"][-1]["template"] == "unclear_confirm"
    handle_reply(c, "???!!", rules, now=_after(c, 2))
    assert c["outcome"] == "handed_to_human" and c["needs_human"]


def test_confirm_no_reply_reminds_then_cancels(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm", order_datetime="2026-10-30 10:00")
    tick(c, _after(c, 13), rules)
    assert c["messages"][-1]["template"] == "confirm_reminder" and c["status"] == "waiting"
    tick(c, _after(c, 24.1), rules)
    assert c["outcome"] == "cancelled_no_reply"
    assert c["messages"][-1]["template"] == "cancelled_no_reply"


def test_confirm_no_reply_can_be_set_to_ship(good_order, rules, model):
    r = copy.deepcopy(rules)
    r["whatsapp"]["confirm_no_reply_action"] = "ship"
    c = _conv(good_order, r, model, "confirm")
    tick(c, _after(c, 25), r)
    assert c["outcome"] == "shipped_no_reply"


def test_confirm_pay_online_then_paid(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    handle_reply(c, "PAY", rules, now=_after(c, 1))
    assert c["status"] == "awaiting_payment" and "pay.mock" in c["messages"][-1]["text"]
    assert payment_completed(c, rules, now=_after(c, 1.2))
    assert c["outcome"] == "converted_prepaid"


def test_confirm_change_address(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    handle_reply(c, "address change karna hai", rules, now=_after(c, 1))
    assert c["status"] == "awaiting_address"
    handle_reply(c, "Flat 22, Lotus Apartments, Ring Road, Mumbai 400050", rules, now=_after(c, 1.5))
    assert c["outcome"] == "address_fixed" and "Lotus" in c["order"]["address"]


def test_question_gets_an_answer_and_keeps_waiting(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    handle_reply(c, "kab tak aayega?", rules, now=_after(c, 1))
    assert c["status"] == "waiting" and c["messages"][-1]["template"] == "question"


def test_llm_reads_unusual_replies(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    llm = FakeLLM(replies={"kal subah bhejna bhai": {"intent": "yes", "summary": "send tomorrow morning"}})
    r = handle_reply(c, "kal subah bhejna bhai", rules, llm=llm, now=_after(c, 1))
    assert r["source"] == "llm" and r["outcome"] == "confirmed"


def test_switch_to_hindi(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    handle_reply(c, "hindi", rules, now=_after(c, 1))
    assert c["language"] == "hindi" and "ऑर्डर" in c["messages"][-1]["text"]


def test_reply_after_close_goes_to_team(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    tick(c, _after(c, 25), rules)
    r = handle_reply(c, "yes please send", rules, now=_after(c, 30))
    assert r["intent"] == "after_close" and c["needs_human"] and c["outcome"] == "cancelled_no_reply"


# ---------------------------------------------------------------- prepaid nudge
def test_nudge_message_shows_discount_maths(good_order, rules, model):
    c = _conv(good_order, rules, model, "nudge")
    text = c["messages"][-1]["text"]
    assert "₹50" in text and "₹549" in text          # Rs 599 order - Rs 50


@pytest.mark.parametrize("reply,outcome", [("2", "kept_cod"), ("no thanks", "kept_cod"), ("cancel", "cancelled_by_customer")])
def test_nudge_replies(good_order, rules, model, reply, outcome):
    c = _conv(good_order, rules, model, "nudge")
    assert handle_reply(c, reply, rules, now=_after(c, 1))["outcome"] == outcome


def test_nudge_pay(good_order, rules, model):
    c = _conv(good_order, rules, model, "nudge")
    handle_reply(c, "1", rules, now=_after(c, 1))
    assert payment_completed(c, rules, now=_after(c, 1.1)) and c["outcome"] == "converted_prepaid"


def test_nudge_no_reply_ships_cod_without_reminder(good_order, rules, model):
    c = _conv(good_order, rules, model, "nudge")
    tick(c, _after(c, rules["whatsapp"]["nudge_wait_hours"] - 0.5), rules)
    assert c["status"] == "waiting" and len([m for m in c["messages"] if m["direction"] == "out"]) == 1
    tick(c, _after(c, rules["whatsapp"]["nudge_wait_hours"] + 0.1), rules)
    assert c["outcome"] == "shipped_no_reply"


def test_nudge_link_but_never_paid_ships_cod(good_order, rules, model):
    c = _conv(good_order, rules, model, "nudge")
    handle_reply(c, "1", rules, now=_after(c, 1))
    tick(c, _after(c, 13), rules)
    assert c["outcome"] == "shipped_no_reply"


def test_nudge_confusing_replies_never_block_the_sale(good_order, rules, model):
    c = _conv(good_order, rules, model, "nudge")
    handle_reply(c, "asdkjh", rules, now=_after(c, 1))
    handle_reply(c, "hmm", rules, now=_after(c, 2))
    assert c["outcome"] == "kept_cod"


# ---------------------------------------------------------------- hold
def test_hold_fix_address(good_order, rules, model):
    c = _conv(good_order, rules, model, address="xyz")
    assert c["flow"] == "hold" and c["status"] == "awaiting_address"
    handle_reply(c, "near", rules, now=_after(c, 1))
    assert c["messages"][-1]["template"] == "address_still_bad"
    handle_reply(c, "House No. 12, Sector 4, Gandhi Nagar, Mumbai 400050", rules, now=_after(c, 2))
    assert c["outcome"] == "address_fixed"


def test_address_with_house_no_is_never_read_as_no(good_order, rules, model):
    c = _conv(good_order, rules, model, "confirm")
    r = handle_reply(c, "House No. 7, Sector 9, Tilak Nagar, Mumbai", rules, now=_after(c, 1))
    assert r["outcome"] == "address_fixed"


def test_address_does_not_bypass_pay_online_hold(good_order, rules, model):
    c = _conv(good_order, rules, model, customer_prior_orders=4, customer_prior_rto=2)
    handle_reply(c, "House No. 7, Sector 9, Tilak Nagar, Mumbai", rules, now=_after(c, 1))
    assert c["status"] == "waiting" and c["outcome"] is None


def test_hold_no_reply_cancels(good_order, rules, model):
    c = _conv(good_order, rules, model, address="xyz")
    tick(c, _after(c, 13), rules)
    assert c["messages"][-1]["template"] == "hold_reminder"
    tick(c, _after(c, 25), rules)
    assert c["outcome"] == "cancelled_no_reply"


def test_hold_pay_online_only(good_order, rules, model):
    c = _conv(good_order, rules, model, customer_prior_orders=4, customer_prior_rto=2)
    assert c["flow"] == "hold" and c["hold_ask"] == "pay_online"
    handle_reply(c, "cod", rules, now=_after(c, 1))          # COD is not on offer
    assert c["status"] == "waiting" and c["unclear_count"] == 1
    handle_reply(c, "1", rules, now=_after(c, 2))
    assert payment_completed(c, rules, now=_after(c, 2.1)) and c["outcome"] == "converted_prepaid"


def test_hold_pay_online_link_unpaid_cancels(good_order, rules, model):
    c = _conv(good_order, rules, model, customer_prior_orders=4, customer_prior_rto=2)
    handle_reply(c, "1", rules, now=_after(c, 1))
    tick(c, _after(c, 25), rules)
    assert c["outcome"] == "cancelled_no_reply"


def test_manual_holds_get_no_whatsapp(good_order, rules, model):
    assert _conv(good_order, rules, model, phone="723013610") is None
