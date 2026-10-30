"""Part 1 - check one COD order and see the decision + reason."""
from datetime import datetime

import pandas as pd
import streamlit as st

from api import badge, call, rs

st.title("🧾 Check an order")
st.caption("Fill in a COD order (or pick an example) and see what the engine decides, and why.")

STATES = ["Maharashtra", "Delhi", "Karnataka", "Tamil Nadu", "Telangana", "West Bengal", "Rajasthan",
          "Uttar Pradesh", "Bihar", "Madhya Pradesh", "Assam", "Gujarat", "Kerala", "Punjab", "Haryana", "Odisha"]
SOURCES = ["meta_ads", "google_ads", "instagram_organic", "influencer", "whatsapp_broadcast", "direct"]
BASE = dict(customer_name="Neha Mishra", phone="9876543210", address="Flat 408, Royal Apartments, Mall Road",
            city="Mumbai", state="Maharashtra", pincode="400050", order_value=599, items="Satin Bonnet",
            customer_prior_orders=3, customer_prior_rto=0, utm_source="direct")
EXAMPLES = {
    "Clean repeat customer, Mumbai": BASE,
    "Hinglish address, first order, Gorakhpur": dict(BASE, customer_name="Lakshmi Pillai", phone="8640777068",
        address="ph krke aana, Masjid ke paas", city="Gorakhpur", state="Uttar Pradesh", pincode="273085",
        order_value=1598, items="Satin Pillowcase|Scrunchies 6pk|Hair Oil 100ml", customer_prior_orders=0,
        utm_source="meta_ads"),
    "Medium risk: first order, Lucknow": dict(BASE, customer_name="Meera Pillai", phone="9109605378",
        address="784/17, MG Nagar, Opp. Hanuman Mandir", city="Lucknow", state="Uttar Pradesh", pincode="226036",
        order_value=699, customer_prior_orders=0, utm_source="meta_ads"),
    "Junk address 'xyz'": dict(BASE, customer_name="Deepika Yadav", address="xyz", city="Bengaluru",
        state="Karnataka", pincode="560084", customer_prior_orders=0, utm_source="google_ads"),
    "Fake name 'asdf'": dict(BASE, customer_name="asdf", address=".", city="Kolkata", state="West Bengal",
        pincode="700001", customer_prior_orders=0),
    "Refused 2 orders before": dict(BASE, customer_name="Pooja Joshi", phone="8636516371",
        address="182/9, Ring Nagar, Opp. SBI Bank", city="Jaipur", state="Rajasthan", pincode="302087",
        order_value=299, customer_prior_orders=4, customer_prior_rto=2, utm_source="google_ads"),
    "Invalid phone (9 digits)": dict(BASE, phone="723013610", city="Chennai", state="Tamil Nadu", pincode="600060"),
}

pick = st.selectbox("Start from an example", list(EXAMPLES))
ex = EXAMPLES[pick]

with st.form("order"):
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Customer name", ex["customer_name"])
    phone = c2.text_input("Phone", ex["phone"])
    value = c3.number_input("Order value (₹)", min_value=0, value=int(ex["order_value"]), step=50)
    address = st.text_input("Address (as typed by the customer)", ex["address"])
    c1, c2, c3 = st.columns(3)
    city = c1.text_input("City", ex["city"])
    state = c2.selectbox("State", STATES, index=STATES.index(ex["state"]))
    pincode = c3.text_input("Pincode", ex["pincode"])
    c1, c2, c3, c4 = st.columns(4)
    prior = c1.number_input("Customer's past orders", 0, 50, ex["customer_prior_orders"])
    prior_rto = c2.number_input("…of which refused (RTO)", 0, 50, ex["customer_prior_rto"])
    source = c3.selectbox("Came from", SOURCES, index=SOURCES.index(ex["utm_source"]))
    items = c4.text_input("Items", ex["items"])
    use_llm = st.toggle("Use AI for messy text (address / name)", value=True,
                        help="Off = rules only. The AI is only called when rules can't judge the text.")
    b1, b2 = st.columns(2)
    check = b1.form_submit_button("🔍 Check only", width="stretch")
    place = b2.form_submit_button("📦 Place order & start WhatsApp", type="primary", width="stretch")

if check or place:
    if prior_rto > prior:
        st.error("Refused orders can't be more than past orders.")
        st.stop()
    body = dict(customer_name=name, phone=phone, address=address, city=city, state=state, pincode=pincode,
                order_value=value, items=items, num_items=max(1, len(items.split("|"))),
                customer_prior_orders=int(prior), customer_prior_rto=int(prior_rto), utm_source=source,
                order_datetime=datetime.now().strftime("%Y-%m-%d %H:%M"))
    with st.spinner("Checking… (the free AI can take up to ~45s; rules take over if it's slow)"):
        if place:
            out, err = call("POST", "/orders", params={"use_llm": use_llm}, json=body)
            d = out["decision"] if out else None
        else:
            d, err = call("POST", "/decide", params={"use_llm": use_llm}, json=body)
    if err:
        st.error(err)
        st.stop()
    st.session_state["last_decision"] = d
    if place:
        st.session_state["chat_order"] = d["order_id"]
        st.session_state["last_conv_started"] = out["conversation"] is not None

d = st.session_state.get("last_decision")
if d:
    st.divider()
    c1, c2 = st.columns([2, 1])
    c1.markdown(f"### {badge(d['action'])}")
    c1.markdown(f"**Reason:** {d['reason']}")
    c2.metric("Chance this COD order comes back", f"{d['risk_pct']:.0f}%")
    if st.session_state.get("last_conv_started") and st.session_state.get("chat_order") == d["order_id"]:
        st.success(f"Order **{d['order_id']}** saved and the WhatsApp message is out → open **2 · WhatsApp simulator** to reply as the customer.")

    t1, t2, t3 = st.tabs(["Why this risk %", "Text checks (rules / AI)", "₹ check"])
    with t1:
        f = pd.DataFrame(d["factors"])
        if len(f):
            f = f[["label", "points", "effect"]].rename(columns={"label": "Fact about this order", "points": "Points",
                                                                   "effect": "Effect"})
            st.dataframe(f, hide_index=True, width="stretch")
        st.caption(f"Every order starts at {d['base_points']} points; more points = higher risk %. "
                   "Points come from past orders (Apr–Aug 2026).")
    with t2:
        ch = d["checks"]
        rows = [
            {"Check": "Address", "Result": ch["address"]["quality"], "Detail": ch["address"].get("issue") or "—",
             "Judged by": "AI" if ch["address"]["source"] == "llm" else "rules"},
            {"Check": "Name", "Result": ch["name"]["quality"], "Detail": ch["name"].get("issue") or "—",
             "Judged by": "AI" if ch["name"]["source"] == "llm" else "rules"},
            {"Check": "Phone", "Result": "valid" if ch["phone"]["valid"] else "invalid",
             "Detail": ch["phone"].get("issue") or "—", "Judged by": "rules"},
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if ch["address"].get("english"):
            st.markdown(f"**Address in plain English (for the courier):** {ch['address']['english']}")
        st.caption(f"WhatsApp language for this customer: **{d['whatsapp_language']}**")
    with t3:
        m = d["money"]
        if m["expected_rs"]:
            ev = pd.DataFrame([{"Action": {"ship": "Ship as-is", "nudge": "Nudge to prepaid",
                                           "confirm": "Ship after confirmation", "hold": "Hold / cancel"}[k],
                                "Expected ₹ on this order": rs(v), "Best by ₹": "⭐" if k == m["best_by_money"] else ""}
                               for k, v in m["expected_rs"].items()])
            st.dataframe(ev, hide_index=True, width="stretch")
            st.caption(f"If delivered we make {rs(m['profit_if_delivered'])}; if it comes back we lose "
                       f"{rs(m['loss_if_returned'])}; cancelling a genuine buyer costs "
                       f"{rs(m['cost_if_genuine_customer_lost'])} to win them back. "
                       "The action follows the thresholds in Settings; this table shows the ₹ maths behind them.")
        else:
            st.info("₹0 order - no money maths.")
