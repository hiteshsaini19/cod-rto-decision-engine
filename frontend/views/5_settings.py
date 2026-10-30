"""Change the rules without touching code (writes config/rules.yaml)."""
import streamlit as st

from api import call, get, rs

st.title("⚙️ Settings")
st.caption("Everything here is saved to `config/rules.yaml`. You can edit either; the next order uses the new values.")

data = get("/settings")
r, sug = data["rules"], data["suggested"]
t, hr, cp, ck, mo, asm, wa = (r[k] for k in ("thresholds", "hold_rules", "customer_protection", "checks", "money",
                                             "assumptions", "whatsapp"))

with st.expander("💡 What the ₹ maths suggests for the thresholds (₹649 order)", expanded=True):
    s = sug["suggested"]
    st.markdown(
        f"- Shipping a COD order stops making money above **{sug['ship_breakeven_risk_pct']}%** risk "
        f"(profit if delivered {rs(sug['delivered_profit'])} vs loss if returned {rs(sug['rto_loss'])}).\n"
        f"- Best action by ₹: nudge from **{s['nudge_from_risk_pct']}%**, confirm from "
        f"**{s['confirm_from_risk_pct']}%**, hold from **{s['hold_from_risk_pct']}%**.\n"
        f"- Most we can give as a prepaid discount before losing money: "
        + ", ".join(f"{k} risk → {rs(v)}" for k, v in data["max_discount_examples"].items()))

with st.form("settings"):
    st.subheader("1. Which action for which risk")
    c = st.columns(3)
    nudge = c[0].slider("Nudge to prepaid from risk %", 0, 100, t["nudge_from_risk_pct"])
    confirm = c[1].slider("Confirm on WhatsApp from risk %", 0, 100, t["confirm_from_risk_pct"])
    hold = c[2].slider("Hold from risk %", 0, 100, t["hold_from_risk_pct"])

    st.subheader("2. Always hold when…")
    c = st.columns(5)
    h1 = c[0].checkbox("Address unusable", hr["hold_if_address_unusable"])
    h2 = c[1].checkbox("Name looks fake", hr["hold_if_fake_name"])
    h3 = c[2].checkbox("Phone invalid", hr["hold_if_phone_invalid"])
    h4 = c[3].checkbox("Order value ₹0", hr["hold_if_order_value_zero"])
    h5 = c[4].number_input("Past refusals ≥", 0, 20, hr["hold_if_past_returns_at_least"],
                           help="0 = switch this rule off")
    st.subheader("3. Protect new customers")
    prot = st.checkbox("Never hold a first-time buyer on risk % alone (confirm instead)",
                       cp["never_hold_first_order_on_risk_alone"])

    st.subheader("4. Money (₹)")
    c = st.columns(4)
    money = {}
    for i, (k, label) in enumerate([
        ("forward_shipping_rs", "Forward shipping ₹"), ("return_shipping_rs", "Return shipping ₹"),
        ("packaging_handling_rs", "Packing & handling ₹"), ("damaged_return_pct", "Damaged returns %"),
        ("avg_product_cost_rs", "Avg product cost ₹"), ("gross_margin_pct", "Gross margin %"),
        ("customer_acquisition_cost_rs", "Cost to win a customer ₹"), ("prepaid_rto_pct", "Prepaid RTO %"),
        ("prepaid_discount_rs", "Prepaid discount ₹"), ("whatsapp_utility_msg_rs", "WhatsApp msg ₹"),
        ("whatsapp_marketing_msg_rs", "WhatsApp offer msg ₹"), ("cod_orders_per_month", "COD orders / month")]):
        money[k] = c[i % 4].number_input(label, min_value=0.0, value=float(mo[k]), step=1.0, key=k)

    st.subheader("5. How customers behave (estimates - update once real data comes in)")
    c = st.columns(4)
    assumptions = {}
    for i, (k, label) in enumerate([
        ("confirm_catches_rto_pct", "Confirmation stops % of would-be returns"),
        ("confirm_loses_genuine_pct", "Confirmation loses % of genuine buyers"),
        ("nudge_converts_genuine_pct", "Genuine buyers who switch to prepaid %"),
        ("nudge_converts_rto_pct", "Would-be returners who switch %"),
        ("hold_recovers_genuine_pct", "Held genuine buyers who fix it %"),
        ("hold_catches_rto_pct", "Held would-be returners who never fix it %"),
        ("hold_pay_online_genuine_pct", "Pay-online-only: genuine who pay %")]):
        assumptions[k] = c[i % 4].slider(label, 0, 100, int(asm[k]), key=k)

    st.subheader("6. WhatsApp timing")
    c = st.columns(4)
    rem = c[0].number_input("Reminder after (h)", 1, 48, int(wa["reminder_after_hours"]))
    give = c[1].number_input("Decide after (h)", 2, 72, int(wa["give_up_after_hours"]))
    nwait = c[2].number_input("Prepaid offer wait (h)", 1, 48, int(wa["nudge_wait_hours"]))
    noreply = c[3].selectbox("Confirmation, no reply →", ["cancel", "ship"],
                             index=["cancel", "ship"].index(wa["confirm_no_reply_action"]))
    saved = st.form_submit_button("💾 Save", type="primary")

if saved:
    updates = {
        "thresholds": {"nudge_from_risk_pct": nudge, "confirm_from_risk_pct": confirm, "hold_from_risk_pct": hold},
        "hold_rules": {"hold_if_address_unusable": h1, "hold_if_fake_name": h2, "hold_if_phone_invalid": h3,
                       "hold_if_order_value_zero": h4, "hold_if_past_returns_at_least": int(h5)},
        "customer_protection": {"never_hold_first_order_on_risk_alone": prot},
        "money": money, "assumptions": assumptions,
        "whatsapp": {"reminder_after_hours": int(rem), "give_up_after_hours": int(give),
                     "nudge_wait_hours": int(nwait), "confirm_no_reply_action": noreply},
    }
    out, err = call("PUT", "/settings", json=updates)
    if err:
        st.error(f"Not saved - {err}")
    else:
        st.success("Saved. The next order uses these rules.")
