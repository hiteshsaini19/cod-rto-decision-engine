"""Part 2 - play the customer in a mock WhatsApp chat."""
import streamlit as st

from api import STATUS_LABEL, call, get

st.title("💬 WhatsApp simulator")
st.caption("You are the customer. Reply with the buttons or type anything (English / Hinglish / Hindi). "
           "Use *Skip time* to see what happens when nobody replies.")

open_only = st.toggle("Only chats still waiting", value=False)
convs = get("/conversations", open_only=open_only, limit=300)
if not convs:
    st.info("No WhatsApp chats yet. Place an order on **1 · Check an order** (one that isn't 'Ship as-is'), "
            "or load demo data on the **Founder dashboard**.")
    st.stop()

FLOW = {"confirm": "Confirmation", "nudge": "Prepaid nudge", "hold": "Hold"}
ids = [c["order_id"] for c in convs]
labels = {c["order_id"]: f"{c['order_id']} · {c['customer_name']} · {FLOW[c['flow']]} · "
                         f"{'🟢 waiting' if c['status'] != 'closed' else '⚪ ' + (c['outcome'] or '')}" for c in convs}
default = st.session_state.get("chat_order")
idx = ids.index(default) if default in ids else 0
order_id = st.selectbox("Chat", ids, index=idx, format_func=labels.get)
st.session_state["chat_order"] = order_id

data = get(f"/conversations/{order_id}")
conv, status = data["conversation"], data["order_status"]


def act(method, path, **kw):
    with st.spinner("…"):
        out, err = call(method, path, **kw)
    if err:
        st.error(err)
    else:
        st.rerun()


left, right = st.columns([3, 1.3])
with right:
    st.markdown("**Order status**")
    st.markdown(f"### {STATUS_LABEL.get(status, status)}")
    st.markdown(f"Flow: **{FLOW[conv['flow']]}**" + (f" ({conv['hold_ask'].replace('_', ' ')})" if conv["hold_ask"] else ""))
    st.markdown(f"Risk: **{conv['risk_pct']:.0f}%** · Language: **{conv['language']}**")
    st.markdown(f"Chat clock: `{conv['clock'][5:16]}`  \nDecides at: `{conv['deadline'][5:16]}`")
    if conv["status"] != "closed":
        st.markdown("**Skip time (no reply)**")
        c1, c2 = st.columns(2)
        if c1.button("⏩ +12 h", width="stretch"):
            act("POST", f"/whatsapp/{order_id}/advance", json={"hours": 12})
        if c2.button("⏩ +24 h", width="stretch"):
            act("POST", f"/whatsapp/{order_id}/advance", json={"hours": 24})
    if conv["status"] == "awaiting_payment":
        if st.button("💳 Customer pays the link", type="primary", width="stretch"):
            act("POST", f"/payments/{order_id}/complete")
    use_llm = st.toggle("Use AI for unusual replies", value=True)
    if conv.get("needs_human"):
        st.warning("Flagged for the support team.")

with left:
    box = st.container(height=520)
    with box:
        for m in conv["messages"]:
            if m["direction"] == "system":
                st.caption(f"🕒 {m['at'][5:16]} · {m['text']}")
                continue
            role = "assistant" if m["direction"] == "out" else "user"
            with st.chat_message(role, avatar="🏪" if role == "assistant" else "🙋"):
                st.markdown(m["text"].replace("\n", "  \n"))
                tail = m["at"][5:16]
                if m.get("buttons"):
                    tail += " · buttons: " + " | ".join(m["buttons"])
                st.caption(tail)
    last_out = next((m for m in reversed(conv["messages"]) if m["direction"] == "out"), None)
    if conv["status"] != "closed" and last_out and last_out.get("buttons"):
        cols = st.columns(len(last_out["buttons"]))
        for col, b in zip(cols, last_out["buttons"]):
            if col.button(b, key=f"btn_{b}", width="stretch"):
                act("POST", f"/whatsapp/{order_id}/reply", params={"use_llm": use_llm}, json={"text": b})
    text = st.chat_input("Type a reply as the customer… (e.g. 'haan bhej do', 'kal bhejna', 'address change karna hai')")
    if text:
        act("POST", f"/whatsapp/{order_id}/reply", params={"use_llm": use_llm}, json={"text": text})

with st.expander("How the flows work"):
    st.markdown(
        """
- **Confirmation**: YES → ships as COD · NO / cancel → cancelled · PAY → payment link (₹50 off) · a full address → address updated and confirmed ·
  something unclear → asked again; after 2 unclear replies → a person takes over · reminder at 12 h · **no reply in 24 h → cancelled**.
- **Prepaid nudge**: 1 / pay → payment link · 2 / no → ships as COD · cancel → cancelled ·
  **no reply in 12 h → ships as COD** (we never lose a sale over a discount offer).
- **Hold**: customer must send a full address (or pay online, for repeat refusers). Reminder at 12 h, **no reply in 24 h → cancelled**.
- Messages are never sent between 9 pm and 9 am; they wait until 9 am.
- Language: Hinglish for Hindi-belt states or Hinglish addresses, English otherwise. The customer can reply HINDI or ENGLISH to switch.
"""
    )
