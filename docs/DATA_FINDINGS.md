# What the data shows

Source: `orders_sample.csv`, 2,018 past COD orders (April - September 2026).
All numbers are reproducible with `python scripts/build_model.py` and `python scripts/run_backtest.py`.

## 1. Data problems (fixed before learning anything)

| Problem | Count | What we did |
|---|---|---|
| Exact duplicate rows (same order twice) | 30 | removed |
| `final_status` spelt 5 ways (`RTO`, `Rto`, `RTO `, `delivered`, `DELIVERED`) | 4 rows | normalised |
| Order still `IN_TRANSIT` (no outcome yet) | 1 | removed |
| Phones as `+91 98xxx xxxxx` | 15 | normalised to 10 digits (valid) |
| Phones with only 9 digits | 17 | flagged invalid (47% of these came back) |
| Missing pincode / missing city | 12 / 4 | kept; flagged as an address problem / state rate used |
| Pincode from another state (e.g. Chennai order with 400080) | 3 | flagged as an address problem |
| ₹0 COD orders | 3 | kept out of learning; the engine sends them to ops to check |
| Internal **"Test Order"** rows in live data | 11 | kept (they are real shipments: 9 of 11 came back) |
| Same product priced anywhere from ₹299 to ₹2,999 | many | used each order's real value |
| `customer_prior_orders` disagrees with the phone's own history (same phone: "3 prior", later "0") | common | used as given (it's what Shopify gives at order time), noted as a risk |

After cleaning: **1,987 orders, 28.4% RTO.** Average order value in the data is **₹919** (median ₹748),
higher than the ₹649 in the brief. The ₹ maths uses each order's real value.

## 2. What predicts a return

| Signal | Orders | Came back |
|---|---|---|
| **All orders** | 1,987 | **28%** |
| Address is junk (`.`, `xyz`, `home`, `call me`, `near station`) or just the city name | 183 | **62%** |
| Fake-looking name (`asdf`, `qwerty`, `Test Order`…) | 44 | **64%** |
| Fake name **and** junk address | 36 | **78%** |
| Address with a house/flat number | 1,314 | 23% |
| Landmark-only / Hinglish address ("chowk se left, Mandir ke saamne") | 490 | 31% |
| Customer refused **2** earlier COD orders | 34 | **76%** |
| Customer refused 1 earlier order | 108 | 35% |
| First order from the customer | 1,495 | 30% |
| Repeat customer | 492 | 23% |
| Order ₹1,500+ | 281 | 39% (₹1,000-1,499: 20%) |
| Meta-ads first-time buyers | 563 | 34% (all direct traffic: 23%) |

**By place** (the strongest structural signal):

| State | Came back | | City | Came back |
|---|---|---|---|---|
| Bihar | 54% | | Gorakhpur | 62% |
| Uttar Pradesh | 44% | | Bareilly | 61% |
| Madhya Pradesh | 38% | | Darbhanga | 59% |
| Assam | 35% | | Sagar | 49% |
| … | | | Patna | 48% |
| Delhi | 22% | | Pune | 18% |
| Tamil Nadu | 21% | | Mumbai | 18% |
| Maharashtra | 18% | | | |

**Weak or misleading signals (not used):**
- **Courier** (26-31%): the gap disappears once you compare within the same region. Inside high-risk states
  every courier is 42-47%. Couriers just serve different areas.
- **Hour / day of week**: small and noisy (25-34%).
- **Pincode history**: see surprise #2 below.

## 3. Surprises

1. **The address text says more than the place.** A junk address roughly triples the return chance (62% vs 23%),
   and reading it needs language understanding. That is the LLM's job.
2. **"Bad pincodes" are mostly luck.** There are 1,066 pincodes with 1.9 orders each on average; 77% have only 1-2 orders.
   The 157 pincodes that looked "bad" before September (2+ orders, half or more came back) had a **25.6%** return
   rate in September, the same as everywhere else (26.1%). Blocking COD there would turn away genuine buyers for nothing.
   City and state rates, which have enough orders behind them, do hold up.
3. **Cancelling almost never pays.** A return costs **₹169** (₹65 + ₹65 + ₹25 + 8% × ₹180), while a delivered
   ₹649 order earns **₹312** after shipping and packing. Shipping only stops paying when the return chance is
   above **65%**, and only ~4% of orders are that risky (14 of 329 in September). The whole RTO problem is worth about **₹73-78k a month**
   (1,650 COD orders × 28% × ₹169).
4. **Past refusals are the strongest single fact**: 2 earlier refusals → 76% come back.
5. **Internal test orders reach the courier**: 11 "Test Order" shipments, 9 returned.

## 4. The risk model

Logistic regression on 10 facts, learnt on **April-August (1,655 orders)** and tested on **September (329 orders it never saw)**.

| Fact | Effect (log-odds) |
|---|---|
| Refused 2+ earlier COD orders | +2.50 |
| Address can't be delivered | +1.67 |
| Refused 1 earlier COD order | +1.19 |
| Phone invalid | +0.96 |
| Area's past return rate (city, else state) | +0.93 per log-odds step |
| First order | +0.90 |
| Order ₹1,500+ | +0.54 |
| Name looks fake | +0.36 |
| Address has no house/flat number | +0.28 |
| Came from a Meta ad | +0.24 |

**September test: AUC 0.744** (picks the returner over the delivered order 74% of the time), and the predicted risk matches reality:

| Predicted risk | Orders | Predicted | Actually came back |
|---|---|---|---|
| 0-15% | 71 | 11% | 7% |
| 15-25% | 125 | 20% | 16% |
| 25-35% | 54 | 30% | 35% |
| 35-50% | 41 | 41% | 46% |
| 50-70% | 28 | 58% | 54% |
| 70%+ | 10 | 80% | 80% |
