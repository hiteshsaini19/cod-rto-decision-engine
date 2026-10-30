import pytest

from rto.economics import (
    expected_values,
    max_affordable_discount,
    outcome_parts,
    suggest_thresholds,
    unit_economics,
)


def test_unit_economics_match_the_brief(rules):
    u = unit_economics(649, rules)
    assert u["rto_loss"] == pytest.approx(65 + 65 + 25 + 0.08 * 180)          # Rs 169.4
    assert u["delivered_profit"] == pytest.approx(649 * 0.62 - 65 - 25)       # Rs 312.38
    assert u["lost_customer_cost"] == 300
    assert unit_economics(649, rules, past_rto=2)["lost_customer_cost"] == 0


def test_ship_ev_endpoints(rules):
    u = unit_economics(649, rules)
    assert outcome_parts("ship", 0.0, 649, rules)["total"] == pytest.approx(u["delivered_profit"])
    assert outcome_parts("ship", 1.0, 649, rules)["total"] == pytest.approx(-u["rto_loss"])


@pytest.mark.parametrize("action,ask", [("ship", None), ("confirm", None), ("nudge", None), ("hold", "fix_address"),
                                        ("hold", "pay_online"), ("cancel", None), ("prepaid_only", None)])
@pytest.mark.parametrize("p", [0.0, 0.3, 1.0])
def test_parts_add_up(rules, action, ask, p):
    parts = outcome_parts(action, p, 799, rules, ask)
    assert parts["total"] == pytest.approx(parts["delivered_profit"] + parts["rto_loss"] + parts["genuine_lost"]
                                           + parts["discount"] + parts["messages"])


def test_cancelling_a_certain_return_costs_nothing_and_a_genuine_order_costs_cac(rules):
    assert outcome_parts("cancel", 1.0, 649, rules)["total"] == 0
    assert outcome_parts("cancel", 0.0, 649, rules)["total"] == -300


def test_breakeven_and_suggested_thresholds(rules):
    s = suggest_thresholds(rules, 649)
    assert s["ship_breakeven_risk_pct"] == pytest.approx(64.8, abs=0.1)
    sug = s["suggested"]
    assert sug["confirm_from_risk_pct"] < sug["hold_from_risk_pct"]
    # At 10% risk shipping is best; at 90% shipping is worst.
    ev_low, ev_high = expected_values(0.10, 649, rules), expected_values(0.90, 649, rules)
    assert max(ev_low, key=ev_low.get) == "ship"
    assert min(ev_high, key=ev_high.get) == "ship"


def test_max_affordable_discount(rules):
    assert max_affordable_discount(0.04, 649, rules) == 0                       # switcher as safe as prepaid
    assert max_affordable_discount(0.20, 649, rules) == pytest.approx(80.3, abs=0.2)
    # The Rs 50 discount pays for itself once a switcher's COD risk is ~15%+
    assert max_affordable_discount(0.15, 649, rules) > rules["money"]["prepaid_discount_rs"]
