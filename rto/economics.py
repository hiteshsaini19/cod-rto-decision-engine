"""All the Rs maths. Every number comes from config/rules.yaml.

For one COD order of value V with risk p (chance it comes back):

  Profit if delivered  D = V x margin - forward shipping - packaging
  Loss if returned     L = forward + return shipping + packaging + damaged% x product cost
  Losing a genuine customer also costs C = acquisition cost (to win a replacement);
  C = 0 for customers who already refused an earlier COD order

Expected Rs of each action (what we expect to make on average):

  Ship     = (1-p) D - p L
  Confirm  = (1-p)(1-g) D - (1-p) g C - p (1-c) L - messages
             c = share of would-be returns stopped, g = share of genuine buyers lost
  Nudge    = genuine: (1-p)[D - ug x discount]
             would-be returns: p [ur x prepaid result - (1-ur) L]   - messages
             ug / ur = share who switch to prepaid
  Hold     = (1-p)[h D - (1-h) C] - p (1-k) L - messages
  (fix address / details)
             h = share of genuine buyers who fix it, k = share of would-be returns who never do
  Hold     = like "Nudge", but anyone who doesn't pay online is cancelled
  (pay online only)
  Cancel   = -(1-p) C                              (Ops' "just cancel it")
"""
from __future__ import annotations


def unit_economics(order_value: float, rules: dict, past_rto: int = 0) -> dict:
    m = rules["money"]
    D = order_value * m["gross_margin_pct"] / 100 - m["forward_shipping_rs"] - m["packaging_handling_rs"]
    L = (m["forward_shipping_rs"] + m["return_shipping_rs"] + m["packaging_handling_rs"]
         + m["damaged_return_pct"] / 100 * m["avg_product_cost_rs"])
    return {
        "delivered_profit": D,
        "rto_loss": L,
        # We'd pay to win back a good customer, not one who already refused orders.
        "lost_customer_cost": m["customer_acquisition_cost_rs"] if past_rto == 0 else 0.0,
        "prepaid_rto": m["prepaid_rto_pct"] / 100,
        "discount": m["prepaid_discount_rs"],
        "msg_utility": m["whatsapp_utility_msg_rs"],
        "msg_marketing": m["whatsapp_marketing_msg_rs"],
    }


def outcome_parts(action: str, p_rto: float, order_value: float, rules: dict, hold_ask: str | None = None,
                  past_rto: int = 0) -> dict:
    """Expected Rs pieces of an action. p_rto can be a probability or, in a backtest,
    exactly 0 or 1 (the real outcome). Pieces add up to the action's expected Rs.
    hold_ask: "pay_online" for a pay-online-only hold; anything else = fix address / details."""
    u = unit_economics(order_value, rules, past_rto)
    a = rules["assumptions"]
    D, L, C, q, d = u["delivered_profit"], u["rto_loss"], u["lost_customer_cost"], u["prepaid_rto"], u["discount"]
    p, g_ = p_rto, 1 - p_rto
    parts = {"delivered_profit": 0.0, "rto_loss": 0.0, "genuine_lost": 0.0, "discount": 0.0, "messages": 0.0,
             "rto_avoided": 0.0, "genuine_orders_lost": 0.0, "rto_orders_shipped": 0.0}

    if action == "ship":
        parts.update(delivered_profit=g_ * D, rto_loss=-p * L, rto_orders_shipped=p)
    elif action == "confirm":
        c, g = a["confirm_catches_rto_pct"] / 100, a["confirm_loses_genuine_pct"] / 100
        parts.update(delivered_profit=g_ * (1 - g) * D, rto_loss=-p * (1 - c) * L,
                     genuine_lost=-g_ * g * C, messages=-2 * u["msg_utility"],
                     rto_avoided=p * c * L, genuine_orders_lost=g_ * g, rto_orders_shipped=p * (1 - c))
    elif action == "nudge":
        ug, ur = a["nudge_converts_genuine_pct"] / 100, a["nudge_converts_rto_pct"] / 100
        # A would-be return that pays online now behaves like a prepaid order.
        parts.update(
            delivered_profit=g_ * D + p * ur * (1 - q) * D,
            discount=-(g_ * ug + p * ur * (1 - q)) * d,
            rto_loss=-p * (1 - ur) * L - p * ur * q * L,
            messages=-(u["msg_marketing"] + u["msg_utility"]),
            rto_avoided=p * ur * (1 - q) * L,
            rto_orders_shipped=p * (1 - ur) + p * ur * q,
        )
    elif action == "hold" and hold_ask == "pay_online":
        hg, ur = a["hold_pay_online_genuine_pct"] / 100, a["nudge_converts_rto_pct"] / 100
        parts.update(delivered_profit=g_ * hg * D + p * ur * (1 - q) * D,
                     discount=-(g_ * hg + p * ur * (1 - q)) * d,
                     rto_loss=-p * ur * q * L, genuine_lost=-g_ * (1 - hg) * C,
                     messages=-(u["msg_marketing"] + u["msg_utility"]),
                     rto_avoided=p * (1 - ur * q) * L, genuine_orders_lost=g_ * (1 - hg),
                     rto_orders_shipped=p * ur * q)
    elif action == "hold":
        h, k = a["hold_recovers_genuine_pct"] / 100, a["hold_catches_rto_pct"] / 100
        parts.update(delivered_profit=g_ * h * D, genuine_lost=-g_ * (1 - h) * C,
                     rto_loss=-p * (1 - k) * L, messages=-2 * u["msg_utility"],
                     rto_avoided=p * k * L, genuine_orders_lost=g_ * (1 - h), rto_orders_shipped=p * (1 - k))
    elif action == "cancel":
        parts.update(genuine_lost=-g_ * C, rto_avoided=p * L, genuine_orders_lost=g_)
    elif action == "prepaid_only":
        # Ops' "stop COD in this pincode": only people who agree to pay online get the order.
        ug, ur = a["nudge_converts_genuine_pct"] / 100, a["nudge_converts_rto_pct"] / 100
        parts.update(delivered_profit=g_ * ug * D + p * ur * (1 - q) * D, rto_loss=-p * ur * q * L,
                     genuine_lost=-g_ * (1 - ug) * C, rto_avoided=p * (1 - ur * q) * L,
                     genuine_orders_lost=g_ * (1 - ug), rto_orders_shipped=p * ur * q)
    else:
        raise ValueError(f"unknown action {action}")

    parts["total"] = (parts["delivered_profit"] + parts["rto_loss"] + parts["genuine_lost"]
                      + parts["discount"] + parts["messages"])
    # The profit we gave up on genuine orders that never shipped.
    parts["genuine_profit_forgone"] = parts["genuine_orders_lost"] * D
    return parts


def expected_values(p: float, order_value: float, rules: dict, hold_ask: str | None = None,
                    past_rto: int = 0) -> dict:
    return {act: round(outcome_parts(act, p, order_value, rules, hold_ask, past_rto)["total"], 2)
            for act in ("ship", "nudge", "confirm", "hold")}


def best_action_by_money(p: float, order_value: float, rules: dict) -> str:
    ev = expected_values(p, order_value, rules)
    return max(ev, key=ev.get)


def suggest_thresholds(rules: dict, order_value: float = 649) -> dict:
    """Walk risk from 0% to 100% and note where the money-best action changes.
    Gives ops a starting point for the thresholds, worked out from the Rs maths."""
    switches, prev = [], None
    for pct in range(0, 101):
        act = best_action_by_money(pct / 100, order_value, rules)
        if act != prev:
            switches.append({"from_risk_pct": pct, "best_action": act})
            prev = act
    first = {s["best_action"]: s["from_risk_pct"] for s in reversed(switches)}
    u = unit_economics(order_value, rules)
    # Ship stops making money when (1-p) D = p L
    breakeven = u["delivered_profit"] / (u["delivered_profit"] + u["rto_loss"])
    return {
        "order_value": order_value,
        "switches": switches,
        "suggested": {
            "nudge_from_risk_pct": first.get("nudge"),
            "confirm_from_risk_pct": first.get("confirm"),
            "hold_from_risk_pct": first.get("hold"),
        },
        "ship_breakeven_risk_pct": round(breakeven * 100, 1),
        "delivered_profit": round(u["delivered_profit"], 2),
        "rto_loss": round(u["rto_loss"], 2),
    }


def max_affordable_discount(p_switcher: float, order_value: float, rules: dict) -> float:
    """Most we can give a customer who switches to prepaid before we lose money on them.

    A switcher with COD risk p_switcher is worth  (p - q)(D + L) / (1 - q)  more as prepaid.
    """
    u = unit_economics(order_value, rules)
    q = u["prepaid_rto"]
    return max(0.0, (p_switcher - q) * (u["delivered_profit"] + u["rto_loss"]) / (1 - q))
