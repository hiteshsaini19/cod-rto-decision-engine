"""Part 3 - the founder's one screen for the morning."""
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from api import STATUS_LABEL, call, get, rs

SERIES = "#2a78d6"   # single-series colour (validated reference palette, slot 1)

st.title("📊 Founder dashboard")

dates = get("/dashboard/dates")
yesterday = date.today() - timedelta(days=1)

top = st.columns([2, 1, 1])
if not dates:
    st.info("No orders processed yet. Load demo data: September 2026's real orders replayed as the last "
            "30 days (decisions by the real engine; customer WhatsApp replies simulated).")
if top[1].button("🎬 Load demo data", width="stretch",
                 help="Replays September's 329 real orders as the last 30 days. Replaces earlier demo data."):
    with st.spinner("Running 329 orders through the engine…"):
        out, err = call("POST", "/demo/seed", timeout=300)
    st.success(f"Loaded {out['orders']} orders ({out['from']} → {out['to']}).") if out else st.error(err)
    st.rerun()
if dates and top[2].button("🗑️ Clear demo data", width="stretch"):
    call("DELETE", "/orders", params={"demo_only": True})
    st.rerun()
if not dates:
    st.stop()

day = top[0].date_input("Day", value=yesterday, max_value=date.today())
s = get("/dashboard", day=day.isoformat())
label = "Yesterday" if s["is_yesterday"] else day.strftime("%d %b %Y")
if s["has_demo_data"]:
    st.caption("Demo data: real September orders and real decisions; customer replies simulated with the "
               "assumptions in Settings.")
if s["orders"] == 0:
    st.warning(f"No orders on {day:%d %b %Y}. Days with orders: "
               + ", ".join(d["date"] for d in dates[:7]) + ("…" if len(dates) > 7 else ""))
    st.stop()

# ---- 1. buckets
st.subheader(f"{label}: {s['orders']} COD orders")
b = s["bucket_keys"]
c = st.columns(4)
c[0].metric("✅ Ship as-is", b["ship"])
c[1].metric("💬 Ship after confirmation", b["confirm"])
c[2].metric("💳 Nudge to prepaid", b["nudge"])
c[3].metric("⛔ Hold / cancel", b["hold"])

# ---- 2. money
m = s["money"]
st.subheader("₹ impact vs shipping every COD order as-is")
c = st.columns(3)
c[0].metric("Est. ₹ saved from avoided RTOs", rs(m["saved_from_avoided_rto"]),
            help="Return costs (₹169 each) we didn't pay: customers who said NO, orders we cancelled "
                 "(× their risk %), and orders that switched to prepaid.")
c[1].metric("Est. ₹ lost: cancelled, maybe genuine", rs(-m["lost_from_cancelled_genuine"]),
            help="For each order WE cancelled (no reply / hold not fixed): chance it was genuine × "
                 "(profit we missed + ₹300 to win the customer back). Customers who said NO themselves are not counted.")
c[2].metric("Net ₹ impact", rs(m["net_impact"]),
            help="Saved + extra profit from prepaid switches − lost − discounts − WhatsApp messages.")
st.caption(f"Net = {rs(m['saved_from_avoided_rto'])} saved + {rs(m['extra_profit_from_prepaid'])} extra profit from "
           f"prepaid switches − {rs(m['lost_from_cancelled_genuine'])} lost − {rs(m['discounts_given'])} discounts − "
           f"{rs(m['whatsapp_cost'])} WhatsApp. "
           f"{s['counts']['cancelled_by_customer']} customers said NO · {s['counts']['cancelled_by_us']} cancelled by us "
           f"(~{s['counts']['est_genuine_among_cancelled_by_us']} likely genuine, "
           f"{s['counts']['first_time_buyers_cancelled_by_us']} first-time buyers) · "
           f"{s['counts']['converted_to_prepaid']} switched to prepaid · {s['still_open']} still waiting / with team.")

# ---- 3. trend
start = (day - timedelta(days=29)).isoformat()
trend = pd.DataFrame(get("/dashboard/range", start=start, end=day.isoformat()))
if len(trend) > 1:
    st.subheader("Net ₹ impact per day (last 30 days)")
    trend["date"] = pd.to_datetime(trend["date"])
    trend["Net ₹"] = trend["net_impact"]
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False)
    base = alt.Chart(trend).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b", grid=False)))
    line = base.mark_line(color=SERIES, strokeWidth=2).encode(
        y=alt.Y("Net ₹:Q", title="Net ₹ per day", axis=alt.Axis(gridOpacity=0.3)))
    points = base.mark_circle(color=SERIES, size=70).encode(
        y="Net ₹:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("date:T", format="%d %b"), alt.Tooltip("orders:Q", title="Orders"),
                 alt.Tooltip("saved_from_avoided_rto:Q", title="Saved ₹", format=",.0f"),
                 alt.Tooltip("lost_from_cancelled_genuine:Q", title="Lost ₹", format=",.0f"),
                 alt.Tooltip("net_impact:Q", title="Net ₹", format=",.0f")]).add_params(hover)
    rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#888", strokeDash=[3, 3]).encode(y="y:Q")
    st.altair_chart((line + points + rule).properties(height=240), width="stretch")
    st.caption(f"30-day total net: {rs(trend['net_impact'].sum())} · "
               f"orders: {int(trend['orders'].sum())}")

# ---- 4. the orders
with st.expander(f"{label}'s orders and reasons"):
    rows = get("/orders", date=day.isoformat(), limit=500)
    df = pd.DataFrame(rows)
    df["status"] = df["status"].map(lambda x: STATUS_LABEL.get(x, x))
    st.dataframe(df[["order_id", "customer_name", "city", "order_value", "action_label", "risk_pct", "status", "reason"]]
                 .rename(columns={"order_id": "Order", "customer_name": "Customer", "city": "City",
                                  "order_value": "₹", "action_label": "Decision", "risk_pct": "Risk %",
                                  "status": "Now", "reason": "Reason"}),
                 hide_index=True, width="stretch")
