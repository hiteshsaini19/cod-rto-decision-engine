import streamlit as st

st.title("📦 COD Order Guard")
st.markdown(
    """
Every Cash-on-Delivery order is checked **before it ships** and gets one of four actions:

| Action | When | What happens |
|---|---|---|
| ✅ **Ship as-is** | low risk | ships straight away |
| 💳 **Nudge to prepaid** | medium risk | WhatsApp offer: pay online and save ₹50. No reply → ships as COD |
| 💬 **Ship after confirmation** | high risk | customer must reply YES on WhatsApp. No reply in 24h → cancelled |
| ⛔ **Hold / cancel** | unusable address, fake name, 2+ past refusals, very high risk | customer must fix the address or pay online; otherwise cancelled |

**Risk %** = the chance the COD order is refused at the door. It comes from simple maths on past orders
(area return rate, first order or repeat, past refusals, address quality, order value).
The **AI** is used only to read messy text: Hinglish addresses, fake names, and free-text WhatsApp replies.

### Try it
1. **Check an order** - type an order (or pick an example) and see the decision and why.
2. **WhatsApp simulator** - play the customer: reply YES / NO / anything, or skip 24 hours.
3. **Founder dashboard** - yesterday's buckets and ₹ impact. Click *Load demo data* first.
4. **Ops vs Marketing** - every policy run on last month's real orders, in ₹.
5. **Settings** - change thresholds and costs without touching code.
"""
)
