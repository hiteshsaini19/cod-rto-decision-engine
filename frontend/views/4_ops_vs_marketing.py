"""Supports Part 4 - every policy on last month's real orders, in ₹."""
import altair as alt
import pandas as pd
import streamlit as st

from api import get, rs

SERIES = "#2a78d6"
NAMES = {"marketing": "Marketing: ship every COD order", "operations": "Ops: cancel risky (≥50%) + stop COD in bad pincodes",
         "ours": "Our system", "hindsight": "Perfect hindsight (ceiling)"}

st.title("⚖️ Ops vs Marketing, in ₹")
with st.spinner("Running every policy on September's orders…"):
    b = get("/backtest")
mo = b["month"]
st.caption(f"{mo['orders']} real COD orders from {mo['from']} to {mo['until']} that the risk model never saw · "
           f"{mo['rto_orders']} came back ({mo['rto_rate']:.0%}) · {mo['first_time_orders']} first-time buyers. "
           f"Monthly figures × {b['scale_to_month']} to match 1,650 COD orders/month.")

p = b["policies"]
rows = []
for k in ("marketing", "operations", "ours", "hindsight"):
    x = p[k]
    rows.append({"Policy": NAMES[k], "₹ per month vs Marketing": x["monthly_vs_marketing"],
                 "Returns shipped (Sept)": round(x["rto_orders_shipped"], 1),
                 "Genuine orders lost (Sept)": round(x["genuine_orders_lost"], 1),
                 "…of which first-time buyers": round(x["first_time_genuine_lost"], 1),
                 "Discounts (Sept)": rs(-x["discount"])})
df = pd.DataFrame(rows)

short = df.assign(Short=["Marketing (ship all)", "Ops plan", "Our system", "Perfect hindsight"],
                  Label=df["₹ per month vs Marketing"].map(rs))
chart = alt.Chart(short).mark_bar(color=SERIES, cornerRadiusEnd=4, height=22).encode(
    x=alt.X("₹ per month vs Marketing:Q", title="₹ per month compared with shipping everything"),
    y=alt.Y("Short:N", sort=None, title=None, axis=alt.Axis(labelLimit=200)),
    tooltip=[alt.Tooltip("Policy:N"), alt.Tooltip("Label:N", title="₹ / month vs Marketing")])
# Value labels sit just outside the bar end: right of positive bars, left of negative ones.
pos = alt.Chart(short[short["₹ per month vs Marketing"] >= 0]).mark_text(align="left", dx=6, color="#52514e") \
    .encode(x="₹ per month vs Marketing:Q", y=alt.Y("Short:N", sort=None), text="Label:N")
neg = alt.Chart(short[short["₹ per month vs Marketing"] < 0]).mark_text(align="right", dx=-6, color="#52514e") \
    .encode(x="₹ per month vs Marketing:Q", y=alt.Y("Short:N", sort=None), text="Label:N")
zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#888").encode(x="x:Q")
lo = min(short["₹ per month vs Marketing"].min(), 0) * 1.25
hi = max(short["₹ per month vs Marketing"].max(), 0) * 1.2
chart = chart.encode(x=alt.X("₹ per month vs Marketing:Q", title="₹ per month compared with shipping everything",
                             scale=alt.Scale(domain=[lo, hi])))
st.altair_chart((chart + pos + neg + zero).properties(height=200), width="stretch")

show = df.copy()
show["₹ per month vs Marketing"] = show["₹ per month vs Marketing"].map(rs)
st.dataframe(show, hide_index=True, width="stretch")

st.subheader("How sure are we?")
sens = b["sensitivity"]
st.markdown(
    f"Our system depends on how customers react to WhatsApp, which we can only estimate until it runs. "
    f"With **pessimistic** reactions it's **{rs(sens['pessimistic']['ours']['monthly_vs_marketing'])}/month**, "
    f"with **optimistic** ones **{rs(sens['optimistic']['ours']['monthly_vs_marketing'])}/month** "
    f"(expected: {rs(p['ours']['monthly_vs_marketing'])}). Ops' plan stays between "
    f"{rs(sens['pessimistic']['operations']['monthly_vs_marketing'])} and "
    f"{rs(sens['optimistic']['operations']['monthly_vs_marketing'])}/month in every case.")

st.subheader("Ops' plan at different strictness levels")
ov = pd.DataFrame(b["ops_variants"])
ov["Rule"] = ov.apply(lambda r: f"cancel ≥{r.cancel_from_risk_pct}% risk" + (" + stop COD in bad pincodes"
                                                                                if r.block_bad_pincodes else ""), axis=1)
ov["₹ per month vs Marketing"] = ov["monthly_vs_marketing"].map(rs)
st.dataframe(ov[["Rule", "orders_not_shipped_cod", "genuine_orders_lost", "₹ per month vs Marketing"]]
             .rename(columns={"orders_not_shipped_cod": "Orders not shipped as COD (Sept)",
                              "genuine_orders_lost": "Genuine orders lost (Sept)"}), hide_index=True,
             width="stretch")
o = b["ops_rules"]
st.caption(f"'Bad pincode' = 2+ past orders and half or more came back: {o['bad_pincodes']} pincodes. "
           f"In September those pincodes had {o['orders_in_bad_pincodes']} orders and their return rate was "
           f"{o['rto_rate_in_bad_pincodes']:.0%} - about the same as everywhere else. "
           "Most pincodes have only 1-2 orders, so their 'history' is mostly luck.")

st.subheader("Our 4 buckets on September's orders")
bk = pd.DataFrame(b["our_buckets"])
bk["Share"] = (bk["share"] * 100).round(0).astype(int).astype(str) + "%"
bk["Predicted risk"] = (bk["avg_predicted_risk"] * 100).round(0).astype(int).astype(str) + "%"
bk["Actually came back"] = (bk["actual_rto_rate"] * 100).round(0).astype(int).astype(str) + "%"
st.dataframe(bk[["label", "orders", "Share", "Predicted risk", "Actually came back", "first_time_buyers"]]
             .rename(columns={"label": "Bucket", "orders": "Orders", "first_time_buyers": "First-time buyers"}),
             hide_index=True, width="stretch")
st.caption("Predicted risk matches what really happened, so the buckets separate safe orders from risky ones.")
