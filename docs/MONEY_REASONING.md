# Operations vs Marketing, in ₹

> "You don't have to pick a side. But your solution has to deal with both concerns, and you must explain your
> reasoning in money (₹), not opinions."

Every figure below comes from `python scripts/run_backtest.py` (also on the **Ops vs Marketing** screen).
Costs and assumptions are in `config/rules.yaml`, so changing a number there changes these results.

## 1. What one order is worth

| | ₹ | How |
|---|---|---|
| Profit if a ₹649 COD order is delivered | **+312** | 62% × 649 − 65 forward shipping − 25 packing |
| Loss if it comes back (RTO) | **−169** | 65 + 65 + 25 + 8% damaged × ₹180 |
| Cost of losing a genuine customer | **−300** | the ad money to win a replacement (Marketing's ₹300 CAC). ₹0 for customers who already refused orders |

**Break-even:** shipping a COD order makes money until its return chance passes **65%**
(312 × (1 − p) = 169 × p). Below that, even a risky order is worth shipping on average. This one line is why
"just cancel risky orders" loses money.

## 2. Expected ₹ of each action (₹649 order)

| Return chance | Ship | Nudge (₹50) | Confirm | Hold |
|---|---|---|---|---|
| 10% | **+264** | +254 | +244 | +166 |
| 30% | +168 | +169 | **+169** | +117 |
| 50% | +71 | +84 | **+94** | +69 |
| 70% | −25 | −1 | +19 | **+21** |

Working these out across every risk level gives the default thresholds: **nudge from ~25-29%, confirm from
~30-38%, hold from ~69-75%** (the exact point depends on order value). They are in `rules.yaml`;
the Settings screen shows the ₹-maths suggestion next to them.

## 3. Every policy on last month's real orders

September 2026: **329 COD orders the model never saw, 86 came back (26%), 241 were first-time buyers.**
Monthly = September × 5.02, to match 1,650 COD orders a month (3,000 × 55%).

| Policy | ₹ / month vs "ship everything" | Returns shipped (Sept) | Genuine orders lost (Sept) | …first-time buyers |
|---|---|---|---|---|
| **Marketing**: ship every COD order | 0 | 86 | 0 | 0 |
| **Ops**: cancel ≥50% risk + stop COD in "bad" pincodes | **−₹93,474** | 54 | 35.3 | 27.6 |
| **Our system** | **+₹9,517** | 57.8 | 4.2 | 3.6 |
| Perfect hindsight (cancel exactly the returns) | +₹73,063 | 0 | 0 | 0 |

**Ops' plan at any strictness loses money:**

| Ops rule | Orders not shipped as COD (Sept) | Genuine lost | ₹ / month |
|---|---|---|---|
| cancel ≥35% + block pincodes | 107 | 53.8 | −₹1,65,963 |
| cancel ≥35% | 79 | 37.0 | −₹1,15,858 |
| cancel ≥50% + block pincodes | 76 | 35.3 | −₹93,474 |
| cancel ≥50% | 38 | 15.0 | −₹41,264 |
| cancel ≥70% + block pincodes | 49 | 22.3 | −₹56,544 |
| cancel ≥70% | 10 | 2.0 | −₹5,241 |

The pincode block is the costliest part: those pincodes returned 25.6% in September, the same as average.

**How sure are we?** Our system depends on how customers react to WhatsApp, which can only be measured once it runs:

| Customer reactions | Our system, ₹ / month | Ops' plan, ₹ / month |
|---|---|---|
| Pessimistic (confirmation stops only 25% of returns, loses 10% of genuine buyers…) | −₹16,356 | −₹1,08,311 |
| Expected (rules.yaml) | **+₹9,517** | −₹93,474 |
| Optimistic | +₹25,203 | −₹83,113 |

## 4. How both concerns are handled

**Where Ops is right, and what we do about it:**
- Some orders really are bad bets: a junk address (62% return), fake name + junk address (78%), a customer who refused
  2 orders (76%). These are **held**: they ship only if the customer fixes the address or pays online.
- High-risk orders don't ship blind: they need a WhatsApp **YES**. Customers who say NO or ignore it are cancelled
  *before* we pay ₹130 in shipping.
- Result: **one-third fewer returns shipped** (86 → 58 in September).

**Where Marketing is right, and what we do about it:**
- A cancelled genuine first order costs ₹312 profit + ₹300 to replace the customer = **₹612**, almost 4× the ₹169 a
  return costs. So the system almost never cancels on a guess. It **asks** first.
- **A first-time buyer is never held on risk % alone.** Without a hard red flag (junk address, fake name…) they get a
  confirmation instead.
- The prepaid offer never blocks a sale: no reply in 12h → ships as COD.
- Result: about **4 genuine orders lost a month**, versus 35 with the Ops plan (28 of them first-time buyers).

**The trade-off in one line:** each would-be return we stop saves ₹169. Each genuine buyer we lose costs ₹612.
So we only stop an order when we're about 4× more likely to be stopping a return than a real customer, and
WhatsApp confirmation is the cheap way to find out which one it is.

## 5. Honest caveats

- The upside is modest (**+₹9.5k/month expected, between −₹16k and +₹25k**) because the whole RTO problem is only
  ~₹73-78k/month. The bigger win is **not** doing the Ops plan (₹93k/month saved).
- The range depends on 7 behaviour assumptions (reply rates, prepaid uptake). They're our best estimates.
  The first 2-4 weeks should measure them (see the memo) and update `rules.yaml`.
- Not counted (all would make the system look better): COD remittance delays, courier RTO penalties, warehouse time
  on returns, and repeat purchases from customers we didn't lose.
- At the brief's ₹649 average order (the data's is ₹919), returns cost relatively more, so stopping them is worth slightly more.
