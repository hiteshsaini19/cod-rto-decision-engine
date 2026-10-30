# Part 2 - WhatsApp confirmation & prepaid nudge

Working mock: **2 · WhatsApp simulator** screen, or the API (`/whatsapp/{order}/reply`, `/whatsapp/{order}/advance`,
`/payments/{order}/complete`). Code: `rto/whatsapp.py`. Every timing and amount below is set in `config/rules.yaml`.

## 1. Which message, in which language, when

| Decision | Message | Buttons | Type (Meta pricing) |
|---|---|---|---|
| Ship after confirmation | order summary + amount + address, "Reply YES to confirm or NO to cancel" + "Reply PAY to save ₹50" | YES · NO · PAY | utility |
| Nudge to prepaid | "Pay online now and get ₹50 off, you pay only ₹549" | 1 Pay online · 2 Keep COD | marketing (it's an offer) |
| Hold: bad address | "Our courier can't find 'xyz'. Please send house/flat no., street, area, pincode" | (free text) | utility |
| Hold: fake-looking name | "Please reply with your full name and complete address" | (free text) | utility |
| Hold: 2+ past refusals | "Cash on Delivery isn't available for this order. Pay online, ₹50 off" | 1 · NO | marketing |
| Hold: invalid phone / ₹0 order | **no message**: ops team checks by hand | | |

**When**
- Straight after the order, **except 9 pm - 9 am**: night orders get the message at 9 am (people ignore or resent
  late-night messages, and an ignored message becomes a cancellation).
- Confirmation / hold: **one reminder at 12 h**, decision at **24 h**.
- Prepaid nudge: **no reminder** (it's an offer, not a requirement), decision at **12 h**.

**Language**
- **Hinglish** (Hindi in English letters) for Hindi-belt states (UP, Bihar, MP, Rajasthan, Delhi, Haryana, Jharkhand,
  Chhattisgarh, Uttarakhand, HP) **or** when the customer typed their address in Hinglish. This is how most people
  in these places write on WhatsApp.
- **English** everywhere else.
- **Hindi (Devanagari)** on request: the customer replies `HINDI`, and `ENGLISH` / `HINGLISH` switch back.
- Example (Hinglish confirmation):
  > Namaste Lakshmi ji! Haircare Store pe aapka order KT101941 mil gaya 🛍️
  > Items: Satin Pillowcase, Scrunchies 6pk · Delivery pe dena hoga: ₹998 · Address: ph krke aana, Masjid ke paas, Gorakhpur 273085
  > Order confirm karne ke liye **YES** likhein, cancel ke liye **NO**. ₹50 bachana hai? Online pay ke liye **PAY** likhein.

## 2. What happens with each reply

| Customer does | Confirmation | Prepaid nudge | Hold |
|---|---|---|---|
| **"yes"** (YES, haan, ok, 👍, "bhej do", "kal bhejna"…) | ✅ confirmed → ships COD | → payment link | → payment link (pay-online hold) |
| **"no"** (NO, nahi, "mat bhejo"…) | ❌ cancelled, nothing charged | keeps COD → ships (a "no" to a discount isn't a "no" to the order) | ❌ cancelled |
| "cancel" | ❌ cancelled | ❌ cancelled | ❌ cancelled |
| PAY / 1 | payment link → paid → ships prepaid | same | same |
| a full address ("House No. 12, Sector 4…") | address updated → confirmed | address updated → ships | address fixed → ships |
| a question ("kab aayega?") | answered, asked again | answered | answered |
| **something random** | asked again once; 2nd unclear reply → **handed to a person** | asked again; 2nd unclear → **ships as COD** (never lose a sale over an offer) | asked again; 2nd → person |
| `HINDI` / `ENGLISH` | message re-sent in that language | same | same |
| **no reply** | reminder at 12h → **cancelled at 24h** ("reply anytime to re-order") | **ships as COD at 12h** | reminder at 12h → **cancelled at 24h** |
| replies after it's closed | polite note, flagged for the support team | same | same |

**How replies are understood:** word rules first (YES/haan/ji/ok/1, NO/nahi/2, cancel, pay/upi, cod/cash, address,
question words). This covers almost all replies, instantly and for free. Anything else goes to the LLM, which returns
one of `yes / no / pay_online / keep_cod / cancel / change_address / question / unclear`. With no LLM available, it's
treated as unclear and asked again. Example the rules can't read: *"kal shaam ko bhejna, abhi bahar hu"* ("send it
tomorrow evening, I'm out right now") → LLM: **yes**.

Bugs we found and fixed with tests: "House **No.** 12" used to be read as **NO** and cancelled the order. "no thanks"
to the discount offer used to be missed.

## 3. The prepaid discount: ₹50, and why

**What a switch to prepaid is worth.** An order that would have come back now pays upfront and is delivered:
we avoid the ₹169 loss **and** earn the ₹312 profit. An order that would have been delivered anyway just costs us
the discount. So the most we can offer is:

> max discount = (switcher's COD risk − 4% prepaid risk) × (₹312 + ₹169) ÷ (1 − 4%)

**The catch: the people who switch are the safer ones.** We assume 30% of genuine buyers switch but only 10% of
would-be returners do (people planning to refuse don't pay upfront). So in the nudge band (25-35% risk) the
*switchers'* risk is only 10-15%:

| Order risk (nudge band) | Risk of those who switch | Max discount, ₹649 order | Max discount, ₹919 order (data average) |
|---|---|---|---|
| 25% | 10% | ₹42 | ₹58 |
| 29% | 12% | ₹51 | ₹70 |
| 35% | 15% | ₹66 | ₹90 |

(Max discount here = the discount at which the nudge earns exactly the same as shipping as-is, at the assumed switch rates.)

**Why ₹50:**
- It sits inside the affordable range for the nudge band (₹42-66 at ₹649, ₹58-90 at the data's ₹919 average). Above
  ~₹66 we'd pay more than the returns we prevent.
- It's ~8% of a ₹649 order: big enough to notice (₹549 is a different price point), in line with common 5-10% prepaid offers.
- A flat amount is simpler to say on WhatsApp than a percentage.
- ₹30 would be cheaper per switch but probably convert fewer people. We don't know by how much, so the first test is
  **₹30 vs ₹50 on a random half of nudged orders each**. The dashboard shows the switch rate.

**Honest note:** the nudge is roughly break-even in ₹ (+₹655 in September, about ₹3k/month). Its real job is to give
medium-risk buyers, mostly first-timers who chose COD because they don't trust us yet, a no-pressure option that
doesn't hold up their order. The money mostly comes from confirmation and holds.

## 4. Message costs

Meta charges per message: about ₹0.15 for order updates (utility) and ₹0.90 for offers (marketing). These are
estimates; check current rates. A confirmation chat costs well under ₹1, against ₹169 per return it prevents.
September's whole WhatsApp bill in the backtest: **₹86** for 329 orders.
