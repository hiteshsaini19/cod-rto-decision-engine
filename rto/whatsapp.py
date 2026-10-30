"""Part 2 - WhatsApp confirmation / prepaid-nudge / hold flows (mock - no real WhatsApp).

A conversation is a small state machine:

  flow "confirm": ask YES/NO  -> yes: ship COD | no: cancel | pay: payment link
                  reminder at 12h, no reply at 24h -> cancel (rules.yaml: confirm_no_reply_action)
  flow "nudge":   offer Rs 50 off to pay online -> 1/pay: link | 2/no: ship COD | cancel: cancel
                  no reply by nudge_wait_hours -> ship COD (we never block a sale over a discount)
  flow "hold":    ask for full address / details / online payment
                  reminder at 12h, no reply at 24h -> cancel (hold_no_reply_action)

Replies are understood by simple word rules first (YES/haan/1/NO/nahi/2...). Only replies
the rules can't read go to the LLM. Confusing replies are re-asked; after a few, a person takes over.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from .assess import assess_orders
from .text_checks import is_hinglish, rule_address

BRAND = os.getenv("BRAND_NAME", "Haircare Store")
HINDI_BELT = {"Uttar Pradesh", "Bihar", "Madhya Pradesh", "Rajasthan", "Delhi", "Haryana",
              "Jharkhand", "Chhattisgarh", "Uttarakhand", "Himachal Pradesh"}

# ------------------------------------------------------------------ templates
T = {
    "confirm": {
        "english": ("Hi {name}! Thanks for your {brand} order {order_id} 🛍️\n"
                    "Items: {items}\nPay on delivery: ₹{amount}\nDeliver to: {address}, {city} {pincode}\n\n"
                    "Reply *YES* to confirm or *NO* to cancel. We ship as soon as you confirm.\n"
                    "Want to save ₹{discount}? Reply *PAY* to pay online instead."),
        "hinglish": ("Namaste {name} ji! {brand} pe aapka order {order_id} mil gaya 🛍️\n"
                     "Items: {items}\nDelivery pe dena hoga: ₹{amount}\nAddress: {address}, {city} {pincode}\n\n"
                     "Order confirm karne ke liye *YES* likhein, cancel ke liye *NO*. Confirm hote hi ship karenge.\n"
                     "₹{discount} bachana hai? Online pay ke liye *PAY* likhein."),
        "hindi": ("नमस्ते {name} जी! {brand} पर आपका ऑर्डर {order_id} मिल गया है 🛍️\n"
                  "सामान: {items}\nडिलीवरी पर देना होगा: ₹{amount}\nपता: {address}, {city} {pincode}\n\n"
                  "ऑर्डर कन्फर्म करने के लिए *YES* लिखें, कैंसल करने के लिए *NO*।\n"
                  "₹{discount} बचाने के लिए *PAY* लिखें और ऑनलाइन पेमेंट करें।"),
    },
    "confirm_reminder": {
        "english": "Hi {name}, should we ship your order {order_id} (₹{amount}, cash on delivery)? Reply *YES* to confirm or *NO* to cancel. We'll keep it for {hours_left} more hours.",
        "hinglish": "{name} ji, aapka order {order_id} (₹{amount}, COD) abhi ruka hua hai. Bhejna hai to *YES* likhein, nahi to *NO*. Hum {hours_left} ghante aur rukenge.",
        "hindi": "{name} जी, आपका ऑर्डर {order_id} (₹{amount}, COD) अभी रुका हुआ है। भेजना है तो *YES* लिखें, नहीं तो *NO*। हम {hours_left} घंटे और रुकेंगे।",
    },
    "nudge": {
        "english": ("Hi {name}! Your {brand} order {order_id} (₹{amount}) is ready to ship 🎉\n"
                    "Pay online now and get *₹{discount} OFF* - you pay only ₹{pay_amount}, and prepaid orders ship first.\n\n"
                    "Reply *1* to pay online (UPI/card)\nReply *2* to keep Cash on Delivery"),
        "hinglish": ("Namaste {name} ji! Aapka {brand} order {order_id} (₹{amount}) ship hone ke liye ready hai 🎉\n"
                     "Abhi online pay karein aur *₹{discount} ki chhoot* paayein - sirf ₹{pay_amount} dena hoga.\n\n"
                     "Online pay ke liye *1* likhein\nCash on Delivery ke liye *2* likhein"),
        "hindi": ("नमस्ते {name} जी! आपका {brand} ऑर्डर {order_id} (₹{amount}) भेजने के लिए तैयार है 🎉\n"
                  "अभी ऑनलाइन पेमेंट करें और *₹{discount} की छूट* पाएं - सिर्फ ₹{pay_amount} देने होंगे।\n\n"
                  "ऑनलाइन पेमेंट के लिए *1* लिखें\nकैश ऑन डिलीवरी के लिए *2* लिखें"),
    },
    "hold_fix_address": {
        "english": ("Hi {name}! We're ready to send your {brand} order {order_id} (₹{amount}), but our courier can't find "
                    "\"{address}\" 📦\nPlease reply with your full address: house/flat no., street, area, landmark and pincode."),
        "hinglish": ("Namaste {name} ji! Aapka order {order_id} (₹{amount}) ready hai, par courier ko \"{address}\" "
                     "se ghar nahi milega 📦\nKripya poora address bhejein: ghar/flat no., gali, area, landmark aur pincode."),
        "hindi": ("नमस्ते {name} जी! आपका ऑर्डर {order_id} (₹{amount}) तैयार है, पर \"{address}\" से कूरियर को घर नहीं "
                  "मिलेगा 📦\nकृपया पूरा पता भेजें: मकान/फ्लैट नंबर, गली, एरिया, लैंडमार्क और पिनकोड।"),
    },
    "hold_confirm_details": {
        "english": ("Hi! We received {brand} order {order_id} (₹{amount}) under the name \"{name}\".\n"
                    "Please reply with your full name and complete delivery address so we can ship it."),
        "hinglish": ("Namaste! {brand} pe order {order_id} (₹{amount}) \"{name}\" naam se aaya hai.\n"
                     "Ship karne ke liye apna poora naam aur poora address bhejein."),
        "hindi": ("नमस्ते! {brand} पर ऑर्डर {order_id} (₹{amount}) \"{name}\" नाम से आया है।\n"
                  "भेजने के लिए अपना पूरा नाम और पूरा पता भेजें।"),
    },
    "hold_pay_online": {
        "english": ("Hi {name}! Cash on Delivery isn't available for order {order_id} (₹{amount}).\n"
                    "Pay online and get *₹{discount} OFF* - only ₹{pay_amount}. Reply *1* for the payment link, or *NO* to cancel."),
        "hinglish": ("Namaste {name} ji! Order {order_id} (₹{amount}) ke liye Cash on Delivery available nahi hai.\n"
                     "Online pay karein aur *₹{discount} ki chhoot* paayein - sirf ₹{pay_amount}. Link ke liye *1* likhein, cancel ke liye *NO*."),
        "hindi": ("नमस्ते {name} जी! ऑर्डर {order_id} (₹{amount}) के लिए कैश ऑन डिलीवरी उपलब्ध नहीं है।\n"
                  "ऑनलाइन पेमेंट करें और *₹{discount} की छूट* पाएं - सिर्फ ₹{pay_amount}। लिंक के लिए *1* लिखें, कैंसल के लिए *NO*।"),
    },
    "hold_reminder": {
        "english": "Hi {name}, your order {order_id} is still on hold. Please reply in the next {hours_left} hours, otherwise it will be cancelled.",
        "hinglish": "{name} ji, aapka order {order_id} abhi ruka hua hai. Agle {hours_left} ghante mein reply karein, warna order cancel ho jayega.",
        "hindi": "{name} जी, आपका ऑर्डर {order_id} अभी रुका हुआ है। अगले {hours_left} घंटे में जवाब दें, वरना ऑर्डर कैंसल हो जाएगा।",
    },
    "pay_link": {
        "english": "Great! Pay ₹{pay_amount} here: {link}\nThe ₹{discount} discount is already applied. Your order ships as soon as the payment is done.",
        "hinglish": "Badhiya! Yahan ₹{pay_amount} pay karein: {link}\n₹{discount} ki chhoot lag chuki hai. Payment hote hi order ship hoga.",
        "hindi": "बढ़िया! यहाँ ₹{pay_amount} का पेमेंट करें: {link}\n₹{discount} की छूट लग चुकी है। पेमेंट होते ही ऑर्डर भेज दिया जाएगा।",
    },
    "paid": {
        "english": "Payment of ₹{pay_amount} received ✅ Order {order_id} ships today.",
        "hinglish": "₹{pay_amount} ka payment mil gaya ✅ Order {order_id} aaj ship hoga.",
        "hindi": "₹{pay_amount} का पेमेंट मिल गया ✅ ऑर्डर {order_id} आज भेजा जाएगा।",
    },
    "confirmed": {
        "english": "Thank you! Order {order_id} is confirmed ✅ It ships within 24 hours. Please keep ₹{amount} ready at delivery.",
        "hinglish": "Shukriya! Order {order_id} confirm ho gaya ✅ 24 ghante mein ship hoga. Delivery pe ₹{amount} ready rakhein.",
        "hindi": "धन्यवाद! ऑर्डर {order_id} कन्फर्म हो गया ✅ 24 घंटे में भेजा जाएगा। डिलीवरी पर ₹{amount} तैयार रखें।",
    },
    "kept_cod": {
        "english": "No problem! Order {order_id} will ship as Cash on Delivery. Please keep ₹{amount} ready.",
        "hinglish": "Koi baat nahi! Order {order_id} Cash on Delivery se ship hoga. ₹{amount} ready rakhein.",
        "hindi": "कोई बात नहीं! ऑर्डर {order_id} कैश ऑन डिलीवरी से भेजा जाएगा। ₹{amount} तैयार रखें।",
    },
    "shipped_cod_no_reply": {
        "english": "Your order {order_id} is on its way as Cash on Delivery 🚚 Please keep ₹{amount} ready.",
        "hinglish": "Aapka order {order_id} Cash on Delivery se ship ho gaya 🚚 ₹{amount} ready rakhein.",
        "hindi": "आपका ऑर्डर {order_id} कैश ऑन डिलीवरी से भेज दिया गया है 🚚 ₹{amount} तैयार रखें।",
    },
    "cancelled_by_customer": {
        "english": "Okay, order {order_id} is cancelled. You won't be charged anything. Hope to see you again! 🙏",
        "hinglish": "Theek hai, order {order_id} cancel kar diya. Aapse koi paisa nahi liya jayega. Phir milenge! 🙏",
        "hindi": "ठीक है, ऑर्डर {order_id} कैंसल कर दिया गया है। आपसे कोई पैसा नहीं लिया जाएगा। फिर मिलेंगे! 🙏",
    },
    "cancelled_no_reply": {
        "english": "We didn't hear back, so order {order_id} has been cancelled. Still want it? Just reply here or order again anytime.",
        "hinglish": "Aapka reply nahi aaya, isliye order {order_id} cancel ho gaya. Abhi bhi chahiye? Yahan reply karein ya dobara order karein.",
        "hindi": "आपका जवाब नहीं आया, इसलिए ऑर्डर {order_id} कैंसल हो गया। अभी भी चाहिए? यहाँ जवाब दें या फिर से ऑर्डर करें।",
    },
    "ask_address": {
        "english": "Sure! Please send your full address: house/flat no., street, area, landmark and pincode.",
        "hinglish": "Zaroor! Poora address bhejein: ghar/flat no., gali, area, landmark aur pincode.",
        "hindi": "ज़रूर! पूरा पता भेजें: मकान/फ्लैट नंबर, गली, एरिया, लैंडमार्क और पिनकोड।",
    },
    "address_updated": {
        "english": "Thanks! Address updated to: {address}. Order {order_id} is confirmed ✅ and ships within 24 hours.",
        "hinglish": "Shukriya! Naya address: {address}. Order {order_id} confirm ✅ - 24 ghante mein ship hoga.",
        "hindi": "धन्यवाद! नया पता: {address}। ऑर्डर {order_id} कन्फर्म ✅ - 24 घंटे में भेजा जाएगा।",
    },
    "address_still_bad": {
        "english": "Sorry, we still can't find a house/flat number in that. Please send the full address (house no., street, area, pincode).",
        "hinglish": "Maaf kijiye, isme ghar/flat number nahi mila. Poora address bhejein (ghar no., gali, area, pincode).",
        "hindi": "माफ़ कीजिए, इसमें मकान/फ्लैट नंबर नहीं मिला। पूरा पता भेजें (मकान नंबर, गली, एरिया, पिनकोड)।",
    },
    "unclear_confirm": {
        "english": "Sorry, we didn't get that 🙏 Please reply *YES* to confirm order {order_id} or *NO* to cancel.",
        "hinglish": "Maaf kijiye, samajh nahi aaya 🙏 Order {order_id} confirm karne ke liye *YES*, cancel ke liye *NO* likhein.",
        "hindi": "माफ़ कीजिए, समझ नहीं आया 🙏 ऑर्डर {order_id} कन्फर्म करने के लिए *YES*, कैंसल के लिए *NO* लिखें।",
    },
    "unclear_nudge": {
        "english": "Sorry, we didn't get that 🙏 Reply *1* to pay online (₹{discount} off) or *2* to keep Cash on Delivery.",
        "hinglish": "Maaf kijiye, samajh nahi aaya 🙏 Online pay (₹{discount} off) ke liye *1*, COD ke liye *2* likhein.",
        "hindi": "माफ़ कीजिए, समझ नहीं आया 🙏 ऑनलाइन पेमेंट (₹{discount} छूट) के लिए *1*, COD के लिए *2* लिखें।",
    },
    "question": {
        "english": "Your order {order_id}: ₹{amount}, delivered in 3-5 days after dispatch. Reply *YES* to confirm or *NO* to cancel - for anything else our team will help you here.",
        "hinglish": "Aapka order {order_id}: ₹{amount}, ship hone ke 3-5 din mein delivery. Confirm ke liye *YES*, cancel ke liye *NO* - aur kuch ho to hamari team yahin madad karegi.",
        "hindi": "आपका ऑर्डर {order_id}: ₹{amount}, भेजने के 3-5 दिन में डिलीवरी। कन्फर्म के लिए *YES*, कैंसल के लिए *NO* - और कुछ हो तो हमारी टीम यहीं मदद करेगी।",
    },
    "handoff": {
        "english": "Thanks! Someone from our team will message you shortly about order {order_id} 🙏",
        "hinglish": "Shukriya! Hamari team ka koi member jaldi hi order {order_id} ke baare mein message karega 🙏",
        "hindi": "धन्यवाद! हमारी टीम जल्दी ही ऑर्डर {order_id} के बारे में आपसे बात करेगी 🙏",
    },
    "closed": {
        "english": "Thanks for your message! Order {order_id} is already {status}. Our team will reply here if you need anything.",
        "hinglish": "Message ke liye shukriya! Order {order_id} pehle hi {status} hai. Kuch chahiye to hamari team yahin reply karegi.",
        "hindi": "संदेश के लिए धन्यवाद! ऑर्डर {order_id} पहले ही {status} है। कुछ चाहिए तो हमारी टीम यहीं जवाब देगी।",
    },
}
BUTTONS = {
    "confirm": ["YES", "NO", "PAY"],
    "confirm_reminder": ["YES", "NO"],
    "nudge": ["1", "2"],
    "unclear_confirm": ["YES", "NO"],
    "unclear_nudge": ["1", "2"],
    "hold_pay_online": ["1", "NO"],
    "question": ["YES", "NO"],
}
# Which messages count as marketing (an offer) for message pricing
MARKETING_TEMPLATES = {"nudge", "hold_pay_online"}

OUTCOME_TO_STATUS = {
    "confirmed": "ship_cod", "kept_cod": "ship_cod", "shipped_no_reply": "ship_cod",
    "address_fixed": "ship_cod", "converted_prepaid": "ship_prepaid",
    "cancelled_by_customer": "cancelled", "cancelled_no_reply": "cancelled",
    "handed_to_human": "with_team",
}

# ------------------------------------------------------------------ reply understanding
YES = {"yes", "y", "ya", "yeah", "yep", "yup", "haan", "han", "haa", "ha", "hn", "ji", "ji haan", "ok", "okay",
       "k", "confirm", "confirmed", "sure", "done", "theek hai", "thik hai", "theek", "bhej do", "bhejo",
       "send", "ship", "ship it", "haan ji", "yes please", "👍", "✅", "हाँ", "हां", "जी", "जी हाँ", "ठीक है"}
NO = {"no", "n", "nahi", "nahin", "nhi", "nai", "na", "nope", "mat bhejo", "nahi chahiye", "don't want",
      "dont want", "not interested", "👎", "❌", "नहीं", "नही", "नहीं चाहिए"}
YES_WORDS = {"yes", "yeah", "yep", "yup", "haan", "haa", "ok", "okay", "confirm", "confirmed", "sure", "done",
             "theek", "bhejo", "👍", "✅", "हाँ", "हां"}
NO_WORDS = {"no", "nahi", "nahin", "nhi", "nai", "nope", "👎", "❌", "नहीं", "नही"}
CANCEL = {"cancel", "cancel karo", "cancel kar do", "cancel it", "cancel order", "band karo", "रद्द", "कैंसल"}
PAY = {"pay", "pay online", "online", "prepaid", "upi", "link", "payment", "pay now", "card", "gpay", "paytm"}
COD = {"cod", "cash", "cash on delivery", "keep cod", "delivery pe", "delivery pe dunga", "delivery pe dungi"}
ADDRESS_WORDS = re.compile(r"\b(address|addr|pata|location|ghar badal|naya address)\b", re.I)
QUESTION_WORDS = re.compile(r"(\?|^(kab|when|how|kitna|kitne|kya|what|where|kaise|why|kyu))", re.I)


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\bno\.?\s*(?=\d)", "number ", t)      # "House No. 12" is not a "no"
    t = re.sub(r"[!.,;:*\"'()\[\]]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _has(t: str, words: set) -> bool:
    if t in words:
        return True
    padded = f" {t} "
    return any(f" {w} " in padded for w in words if " " in w or len(w) > 2 or not w.isalpha())


def rule_intent(text: str, flow: str, status: str) -> str | None:
    """Understand common replies without the LLM. None = couldn't tell."""
    t = _norm(text)
    if not t:
        return None
    if t in ("hindi", "हिंदी", "हिन्दी"):
        return "lang_hindi"
    if t in ("english", "angrezi"):
        return "lang_english"
    if t in ("hinglish",):
        return "lang_hinglish"

    tokens = set(t.split())
    is_cancel = _has(t, CANCEL)
    # Very short words ("na", "ha", "k", "y") only count when they are the whole reply.
    is_no = t in NO or bool(tokens & NO_WORDS) or _has(t, {w for w in NO if " " in w})
    is_yes = t in YES or bool(tokens & YES_WORDS) or _has(t, {w for w in YES if " " in w})
    is_pay = _has(t, PAY)
    is_cod = _has(t, COD)

    if flow == "nudge" and status == "waiting":
        if t == "1" or (is_pay and not is_cod):
            return "pay_online"
        if t == "2" or (is_cod and not is_pay):
            return "keep_cod"
        if is_cancel:
            return "cancel"
        if is_yes and not is_no:
            return "pay_online"   # "yes" to "want ₹50 off?"
        if is_no and not is_yes:
            return "keep_cod"     # "no" to the offer is not "cancel my order"
    elif flow == "hold" and status == "waiting":   # pay-online hold
        if t == "1" or is_pay or (is_yes and not is_no):
            return "pay_online"
        if is_no or is_cancel:
            return "cancel"
    else:
        if is_cancel:
            return "cancel"
        if status == "awaiting_payment" and (is_cod or t == "2"):
            return "keep_cod"
        if t == "pay" or is_pay:
            return "pay_online"
        if (t == "1" or is_yes) and not is_no:
            return "yes"
        if (t == "2" or is_no) and not is_yes:
            return "no"
    if ADDRESS_WORDS.search(t):
        return "change_address"
    if len(re.findall(r"[a-zऀ-ॿ]", t)) >= 3 and QUESTION_WORDS.search(t):
        return "question"
    return None


def understand_reply(text: str, flow: str, status: str, llm=None) -> dict:
    intent = rule_intent(text, flow, status)
    if intent:
        return {"intent": intent, "source": "rules"}
    if llm is not None:
        r = llm.classify_reply(text, flow)
        if r:
            return {"intent": r["intent"], "source": "llm", "summary": r.get("summary", "")}
    return {"intent": "unclear", "source": "rules"}


# ------------------------------------------------------------------ timing / language
def choose_language(state: str, address: str) -> str:
    """Hindi-belt states and Hinglish addresses get Hinglish (Hindi in English letters - how most
    people type on WhatsApp); everyone else English. Customers can reply HINDI / ENGLISH to switch."""
    if (state or "").strip() in HINDI_BELT or is_hinglish(address or ""):
        return "hinglish"
    return "english"


def next_send_time(t: datetime, rules: dict) -> datetime:
    """Push messages that fall in quiet hours (9pm-9am) to 9am."""
    start, end = rules["whatsapp"]["quiet_hours_start"], rules["whatsapp"]["quiet_hours_end"]
    if t.hour >= start:
        return (t + timedelta(days=1)).replace(hour=end, minute=0, second=0, microsecond=0)
    if t.hour < end:
        return t.replace(hour=end, minute=0, second=0, microsecond=0)
    return t


def _ts(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat(sep=" ")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ------------------------------------------------------------------ conversation
def _vars(conv: dict, rules: dict, **extra) -> dict:
    o = conv["order"]
    d = rules["money"]["prepaid_discount_rs"]
    amount = float(o["order_value"])
    v = {"brand": BRAND, "name": o["customer_name"] or "there", "order_id": conv["order_id"],
         "items": (o.get("items") or "").replace("|", ", ") or "your items", "amount": f"{amount:,.0f}",
         "address": o.get("address") or "", "city": o.get("city") or "", "pincode": o.get("pincode") or "",
         "discount": f"{d:,.0f}", "pay_amount": f"{max(amount - d, 0):,.0f}",
         "link": f"https://pay.mock/{conv['order_id']}", "hours_left": "", "status": ""}
    v.update(extra)
    return v


def _say(conv: dict, template: str, at: datetime, rules: dict, **extra) -> dict:
    text = T[template][conv["language"]].format(**_vars(conv, rules, **extra))
    msg = {"at": _ts(at), "direction": "out", "template": template, "text": text,
           "buttons": BUTTONS.get(template, []),
           "kind": "marketing" if template in MARKETING_TEMPLATES else "utility"}
    conv["messages"].append(msg)
    return msg


def _note(conv: dict, at: datetime, text: str) -> None:
    conv["messages"].append({"at": _ts(at), "direction": "system", "text": text, "template": None,
                             "buttons": [], "kind": None})


def _close(conv: dict, outcome: str, at: datetime) -> None:
    conv["status"] = "closed"
    conv["outcome"] = outcome
    conv["closed_at"] = _ts(at)


def start_conversation(order: dict, decision: dict, rules: dict, now: datetime | None = None) -> dict | None:
    """Create the conversation and its first message. None if we can't / shouldn't message."""
    action = decision["action"]
    if action not in ("confirm", "nudge", "hold"):
        return None
    ask = decision.get("hold_ask")
    if action == "hold" and ask in ("manual_call", "manual_check"):
        return None   # ops handles these by hand
    created = _dt(decision["order_datetime"]) if now is None else now
    send_at = next_send_time(created, rules)
    w = rules["whatsapp"]
    wait = w["nudge_wait_hours"] if action == "nudge" else w["give_up_after_hours"]
    conv = {
        "order_id": decision["order_id"], "flow": action, "hold_ask": ask,
        "language": decision.get("whatsapp_language") or choose_language(order.get("state"), order.get("address")),
        "status": "waiting", "outcome": None, "unclear_count": 0, "reminded": False,
        "created_at": _ts(created), "send_at": _ts(send_at), "clock": _ts(send_at),
        "reminder_at": _ts(send_at + timedelta(hours=w["reminder_after_hours"])) if action != "nudge" else None,
        "deadline": _ts(send_at + timedelta(hours=wait)), "closed_at": None,
        "risk_pct": decision["risk_pct"],
        "order": {k: order.get(k) for k in ("customer_name", "order_value", "items", "address", "city",
                                              "state", "pincode", "phone")},
        "messages": [],
    }
    if send_at > created:
        _note(conv, created, f"Order placed in quiet hours - message scheduled for {send_at:%d %b %I:%M %p}.")
    if action == "confirm":
        _say(conv, "confirm", send_at, rules)
    elif action == "nudge":
        _say(conv, "nudge", send_at, rules)
    else:
        if ask in ("fix_address", "confirm_details"):
            conv["status"] = "awaiting_address"
            _say(conv, "hold_fix_address" if ask == "fix_address" else "hold_confirm_details", send_at, rules)
        else:
            _say(conv, "hold_pay_online", send_at, rules)
    return conv


def _looks_like_address(text: str, order: dict, llm=None) -> dict:
    o = {**order, "address": text, "customer_name": order.get("customer_name") or "Customer"}
    return assess_orders([o], llm=llm)[0]["address"]


def handle_reply(conv: dict, text: str, rules: dict, llm=None, now: datetime | None = None) -> dict:
    """Process one customer message. Returns {intent, source, outcome}."""
    now = now or _dt(conv["clock"])
    conv["clock"] = _ts(max(now, _dt(conv["clock"])))
    conv["messages"].append({"at": _ts(now), "direction": "in", "text": text, "template": None,
                             "buttons": [], "kind": None})

    if conv["status"] == "closed":
        status = {"ship_cod": "confirmed", "ship_prepaid": "paid and confirmed",
                  "cancelled": "cancelled", "with_team": "with our team"}.get(
            OUTCOME_TO_STATUS.get(conv["outcome"], ""), "closed")
        _say(conv, "closed", now, rules, status=status)
        _note(conv, now, "Reply after the order was closed - flagged for the support team.")
        conv["needs_human"] = True
        return {"intent": "after_close", "source": "rules", "outcome": conv["outcome"]}

    # A message that is clearly a full address (house no. + street) is a new address - except on a
    # pay-online-only hold, where a new address doesn't change that COD isn't offered.
    if (conv.get("hold_ask") != "pay_online" and len(text.strip()) >= 15
            and rule_address(text, conv["order"].get("city"), conv["order"].get("state"),
                             conv["order"].get("pincode"))["quality"] == "complete"):
        return _address_fixed(conv, text, {"quality": "complete", "source": "rules"}, now, rules)

    # Expecting an address: check for an address first ("House No. 12" must not read as "no").
    if conv["status"] == "awaiting_address":
        addr = _looks_like_address(text, conv["order"], llm) if len(text.strip()) >= 12 else {"quality": "unusable"}
        if addr["quality"] in ("complete", "incomplete"):
            return _address_fixed(conv, text, addr, now, rules)
        quick = rule_intent(text, conv["flow"], "waiting")
        if quick in ("no", "cancel"):
            _say(conv, "cancelled_by_customer", now, rules)
            _close(conv, "cancelled_by_customer", now)
            return {"intent": quick, "source": "rules", "outcome": conv["outcome"]}
        if quick and quick.startswith("lang_"):
            return _switch_language(conv, quick, now, rules)
        return _unclear(conv, now, rules, template="address_still_bad")

    u = understand_reply(text, conv["flow"], conv["status"], llm)
    intent = u["intent"]
    if intent.startswith("lang_"):
        return _switch_language(conv, intent, now, rules)

    # Same word means different things in different flows.
    if conv["status"] == "awaiting_payment":
        if intent == "yes":
            intent = "pay_online"                       # "ok" after a link -> resend the link
        elif intent == "no":
            intent = "cancel" if conv["flow"] == "hold" else "keep_cod"   # they still want the order
    if conv["flow"] == "nudge":
        intent = {"yes": "pay_online", "no": "keep_cod"}.get(intent, intent)
    if conv["flow"] == "hold":
        intent = {"yes": "pay_online", "no": "cancel"}.get(intent, intent)

    if intent == "yes":
        _say(conv, "confirmed", now, rules)
        _close(conv, "confirmed", now)
    elif intent in ("no", "cancel"):
        _say(conv, "cancelled_by_customer", now, rules)
        _close(conv, "cancelled_by_customer", now)
    elif intent == "pay_online":
        conv["status"] = "awaiting_payment"
        _say(conv, "pay_link", now, rules)
    elif intent == "keep_cod":
        if conv["flow"] == "hold":
            # COD isn't offered on hold; treat like an unclear reply.
            return _unclear(conv, now, rules, u)
        _say(conv, "kept_cod", now, rules)
        _close(conv, "kept_cod", now)
    elif intent == "change_address":
        conv["status"] = "awaiting_address"
        _say(conv, "ask_address", now, rules)
    elif intent == "question":
        _say(conv, "question", now, rules)
    else:
        return _unclear(conv, now, rules, u)
    return {**u, "intent": intent, "outcome": conv["outcome"]}


def _address_fixed(conv, text, addr, now, rules):
    conv["order"]["address"] = text.strip()
    conv["new_address"] = {"text": text.strip(), **addr}
    _say(conv, "address_updated", now, rules)
    _close(conv, "address_fixed", now)
    return {"intent": "address", "source": addr.get("source", "rules"), "outcome": conv["outcome"]}


def _switch_language(conv, intent, now, rules):
    conv["language"] = intent.split("_", 1)[1]
    first = {"confirm": "confirm", "nudge": "nudge"}.get(conv["flow"])
    if conv["status"] == "awaiting_address":
        first = "ask_address"
    elif conv["flow"] == "hold":
        first = "hold_pay_online"
    _say(conv, first, now, rules)
    return {"intent": intent, "source": "rules", "outcome": conv["outcome"]}


def _unclear(conv, now, rules, u=None, template=None):
    conv["unclear_count"] += 1
    if conv["unclear_count"] >= rules["whatsapp"]["max_unclear_replies"]:
        if conv["flow"] == "nudge":
            # Never block a sale over a discount offer: ship as COD.
            _say(conv, "kept_cod", now, rules)
            _close(conv, "kept_cod", now)
        else:
            _say(conv, "handoff", now, rules)
            _close(conv, "handed_to_human", now)
            conv["needs_human"] = True
    else:
        _say(conv, template or ("unclear_nudge" if conv["flow"] == "nudge" else "unclear_confirm"), now, rules)
    return {"intent": "unclear", "source": (u or {}).get("source", "rules"), "outcome": conv["outcome"]}


def payment_completed(conv: dict, rules: dict, now: datetime | None = None) -> bool:
    now = now or _dt(conv["clock"])
    if conv["status"] != "awaiting_payment":
        return False
    conv["clock"] = _ts(max(now, _dt(conv["clock"])))
    _note(conv, now, "Payment received (mock payment gateway).")
    _say(conv, "paid", now, rules)
    _close(conv, "converted_prepaid", now)
    return True


def tick(conv: dict, now: datetime, rules: dict) -> list[str]:
    """Move the clock forward: send reminders, apply no-reply timeouts. Returns what happened."""
    events = []
    if conv["status"] == "closed":
        conv["clock"] = _ts(max(now, _dt(conv["clock"])))
        return events
    conv["clock"] = _ts(max(now, _dt(conv["clock"])))
    w = rules["whatsapp"]
    deadline = _dt(conv["deadline"])

    if conv["reminder_at"] and not conv["reminded"] and now >= _dt(conv["reminder_at"]) and now < deadline:
        rem_at = next_send_time(_dt(conv["reminder_at"]), rules)
        if rem_at < deadline:
            hours_left = max(1, round((deadline - rem_at).total_seconds() / 3600))
            tpl = "confirm_reminder" if conv["flow"] == "confirm" else "hold_reminder"
            _say(conv, tpl, rem_at, rules, hours_left=hours_left)
            events.append("reminder")
        conv["reminded"] = True

    if now >= deadline:
        hours = round((deadline - _dt(conv["send_at"])).total_seconds() / 3600)
        _note(conv, deadline, f"{hours}h passed with no final answer.")
        if conv["flow"] == "nudge" or (conv["status"] == "awaiting_payment" and conv["flow"] == "confirm"):
            # They wanted the order (or ignored an optional offer) -> ship as COD.
            _say(conv, "shipped_cod_no_reply", deadline, rules)
            _close(conv, "shipped_no_reply", deadline)
        else:
            act = w["confirm_no_reply_action"] if conv["flow"] == "confirm" else w["hold_no_reply_action"]
            if act == "ship":
                _say(conv, "shipped_cod_no_reply", deadline, rules)
                _close(conv, "shipped_no_reply", deadline)
            else:
                _say(conv, "cancelled_no_reply", deadline, rules)
                _close(conv, "cancelled_no_reply", deadline)
        events.append(conv["outcome"])
    return events
