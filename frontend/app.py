"""Streamlit front-end.  Run:  streamlit run frontend/app.py"""
import streamlit as st

from api import get

st.set_page_config(page_title="COD Order Guard", page_icon="📦", layout="wide")

home = st.Page("home.py", title="Home", icon="🏠", default=True)
pages = [
    home,
    st.Page("views/1_check_order.py", title="1 · Check an order", icon="🧾"),
    st.Page("views/2_whatsapp.py", title="2 · WhatsApp simulator", icon="💬"),
    st.Page("views/3_dashboard.py", title="3 · Founder dashboard", icon="📊"),
    st.Page("views/4_ops_vs_marketing.py", title="4 · Ops vs Marketing (₹)", icon="⚖️"),
    st.Page("views/5_settings.py", title="Settings (rules)", icon="⚙️"),
]
nav = st.navigation(pages)

with st.sidebar:
    h = get("/health")
    st.caption("Backend: 🟢 running")
    if h["llm_configured"]:
        st.caption("AI (OpenRouter): 🟢 key found")
        if h.get("llm_last_error"):
            st.caption(f"Last AI call failed → rules used instead ({h['llm_last_error'][:80]}…)")
    else:
        st.caption("AI (OpenRouter): ⚪ no key — rules only (everything still works)")
    st.caption(f"Risk model tested on Sep 2026 · AUC {h['model_test_auc']}")

nav.run()
