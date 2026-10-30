# Memo: what to do with risky COD orders

**To:** Founder · **From:** Hitesh Saini · **Date:** 31 October 2026

**Bottom line:** don't cancel risky orders; **ask first**. Checking every COD order before it ships, and asking the
risky ones to confirm on WhatsApp, would have shipped **a third fewer returns** last month while losing about
**4 genuine orders**. The Operations proposal would have lost **35 genuine orders and ~₹93,000 a month**.

## 1. What the data showed (2,018 COD orders, Apr-Sep 2026)

1. **The address tells you more than the place.** Orders with a junk address ("xyz", ".", "call me", or just the city
   name) came back **62%** of the time, vs **23%** for addresses with a house/flat number. Junk address *and* a fake
   name ("asdf", "Test Order"): **78%**.
2. **"Bad pincodes" are mostly bad luck.** Most pincodes have only 1-2 orders. The 157 pincodes that looked bad
   before September returned **25.6%** in September, the same as everywhere else (26.1%). Blocking COD there would
   turn away genuine buyers for nothing. Cities do show real patterns: Gorakhpur 62%, Darbhanga 59%, Patna 48% vs Mumbai and Pune 18%.
3. **A return costs less than you'd think; a lost customer costs more.** A return costs **₹169**
   (₹65 + ₹65 + ₹25 + damaged stock). A delivered ₹649 order earns **₹312**, and losing a genuine new customer costs
   another **₹300** to replace. **Shipping a COD order is worth it until it has a 65% chance of coming back**, and
   only ~4% of orders are that risky. The whole RTO problem is worth about **₹75,000 a month**.
4. Customers who refused **2 earlier** orders refuse again **76%** of the time. **11 internal "Test Order"** shipments
   went out; 9 came back.

## 2. Recommended rules, and what they'd have done to September

| Action | When | September orders | Actually came back |
|---|---|---|---|
| ✅ Ship as-is | risk below 25% | 189 (57%) | 12% |
| 💳 Offer ₹50 off to pay online (no reply in 12h → ships COD) | 25-35% | 56 (17%) | 34% |
| 💬 Ship only after WhatsApp YES (no reply in 24h → cancel) | 35-75% | 45 (14%) | 44% |
| ⛔ Hold: fix address / pay online, else cancel | junk address, fake name, 2+ refusals, >75% | 39 (12%) | 62% |

Rules always on: **a first-time buyer is never held on risk alone** (they get a confirmation); duplicate orders
get confirmed; invalid phones go to ops. Every decision comes with a one-line reason, e.g. *"Confirm on WhatsApp:
42% chance this comes back (Patna: 46% of past COD orders came back; first order; no house number)."*
All thresholds and costs can be changed on a Settings screen without code.

**Result on September's 329 real orders** (the risk score never saw them), scaled to 1,650 COD orders/month:

| | ₹ / month vs shipping everything | Returns shipped | Genuine orders lost |
|---|---|---|---|
| Ship everything (Marketing) | 0 | 86 | 0 |
| Cancel risky + block bad pincodes (Ops) | **−₹93,474** | 54 | 35 (28 first-time) |
| **Recommended rules** | **+₹9,517** (range −₹16k to +₹25k) | **58** | **4** |
| Perfect foresight (the ceiling) | +₹73,063 | 0 | 0 |

## 3. Balancing Operations and Marketing

Both are right about something, and the ₹ shows where:

- **Ops is right** that some orders are bad bets. Junk addresses, fake names and repeat refusers are held, and every
  high-risk order needs a YES before we spend ₹130 shipping it. Returns shipped fall by a third.
- **Marketing is right** that cancelling a genuine buyer is expensive: **₹612** (₹312 profit + ₹300 to replace them)
  vs **₹169** for a return. So one wrongly cancelled customer costs as much as ~4 returns. That's why the system
  **asks instead of cancels**: a WhatsApp message costs under ₹1 and sorts the real buyers from the rest.
- **The trade-off:** we only stop an order when it's clearly more likely to be a return than a real customer, and
  even then we give the customer a chance to confirm, fix the address or pay online. Ops' plan cuts more returns
  (32 vs 28) but loses 35 genuine buyers to do it, which is why it's ₹93k/month worse.

## 4. What could go wrong, and how we'd notice

| Risk | How we'd notice |
|---|---|
| Customers react differently than assumed (e.g. fewer genuine buyers reply), which is the biggest uncertainty (the range is −₹16k to +₹25k) | Dashboard: reply / no-reply / switch-to-prepaid rates per day. Compare with the assumptions weekly and update Settings |
| Genuine first-time buyers miss the message and get cancelled | "First-time buyers cancelled by us" on the dashboard; complaints; re-orders after a cancellation |
| Risk score drifts (new cities, festive season, a new ad campaign) | Weekly: predicted vs actual return rate per bucket (they match today: 12% / 34% / 44% / 62%). Retrain monthly |
| Free AI is slow or down | Automatic fallback to rules (decisions continue); shown on screen |
| People learn to game it (typing a fake house number) | Return rate of "complete address" orders creeping up |

## 5. Next two weeks

1. **Go live with a 10% control group** that is shipped as today. It's the only way to measure the real effect and
   pin down the −₹16k to +₹25k range.
2. **Connect the real pipes:** Shopify order webhook → decision → tag the order; WhatsApp Business API (Interakt /
   Gupshup); courier delivery status back in, so the dashboard uses real outcomes instead of estimates.
3. **Customer history by phone number** across orders (the current "past orders" field is unreliable), plus a proper pincode database.
4. **Test ₹30 vs ₹50** prepaid discounts, and a ₹99 "token prepaid" for high-risk orders.
5. **Stop test orders reaching the courier** (11 did; 9 came back).

*Details in the repo's docs/ folder: MONEY_REASONING.md (every policy in ₹), DATA_FINDINGS.md, WHATSAPP_FLOW.md, DECISION_LOG.md.*
