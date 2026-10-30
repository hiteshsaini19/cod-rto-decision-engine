# Decision log

The important choices, in roughly the order they were made: what I picked, what else I considered, and why.

## Approach & stack

- **Decide by ₹, not by gut.** Every action is compared on expected ₹ (profit if delivered, loss if returned, cost of
  losing a genuine customer). *Alternatives:* a pure "risk score → cancel" rule (Ops' idea), or ship everything
  (Marketing's). *Why:* the brief asks for reasoning in ₹, and the ₹ maths settles the argument: cancelling only pays
  above ~65% risk.
- **Python: FastAPI backend + Streamlit frontend + SQLite.** *Alternatives:* Node/React, a single Streamlit app.
  *Why:* one language end to end; the data work was already in pandas; no Node or database server, so it runs in
  under 10 minutes; a separate API means the WhatsApp mock and engine can be called like real services
  (`/docs` lets the reviewer try them).
- **LLM provider: OpenRouter free models** (my choice). *Alternatives:* Google Gemini free tier (easiest key),
  Groq, local Ollama (no key, but a multi-GB download breaks the 10-minute rule). *Why:* free, no card, and one key
  covers many models, so a dead model is a one-line `.env` change.
- **Model list tested on our own data, not picked by name.** I probed 7 free models on real messy addresses.
  `dots-3-note-preview` and `nemotron-3.5-lightning` were correct on all test cases. A small Liquid model misread
  replies and was dropped; Gemma models were often rate-limited (HTTP 429).

## Where the LLM line is drawn

- **LLM only for open-ended text:** address deliverability (incl. Hinglish), odd names, free-text WhatsApp replies.
  **Code for everything exact:** phone format, pincode vs state, duplicates, risk %, thresholds, ₹ maths, reasons.
  *Why:* the code parts must be exact, repeatable and auditable; an LLM would be slower, cost money and sometimes be wrong.
- **Rules first, LLM second.** Rules settle ~75% of orders (clear junk like `xyz`, clear house-number addresses);
  only "unclear" text goes to the LLM. *Why:* free tier = 50 requests/day, and the obvious cases don't need judgement.
- **Cache + batch + time budget + fallback.** Same text never sent twice; 20 texts per request (the whole dataset
  took 10 requests); max 45s per order, then rules. *Why:* free models time out (seen: 90s+) and get rate-limited.
  A slow AI must never block an order.
- **Guardrail on LLM "unusable".** If the LLM calls an address unusable but it names a real place
  ("Masjid ke paas"), it's downgraded to "incomplete". *Why:* the LLM was inconsistent on identical patterns
  (see AI usage log), and "unusable" triggers a hold. A hold should never rest on one shaky LLM opinion.
- **Reasons are templates filled from the actual facts used**, not LLM-written. *Why:* the explanation must match
  the calculation exactly.

## Risk model

- **Logistic regression on 10 yes/no facts.** *Alternatives:* hand-set points, gradient boosting.
  *Why:* 2,000 rows is small; logistic regression gives honest probabilities (checked: predicted 80% → actual 80%),
  and each fact's weight turns into a readable "+17 points: address can't be delivered". Boosting might gain a
  little AUC but loses the explanation.
- **Train on April-August, test on September.** *Why:* tests on orders it never saw; September is also "last month"
  for the memo's backtest. AUC 0.744.
- **City rate (smoothed toward state) instead of pincode.** *Why:* 1,066 pincodes with ~2 orders each. Pincodes that
  looked bad returned at the average rate the next month. Cities need ≥15 past orders (editable) or the state rate is used.
- **No courier, hour or weekday.** *Why:* courier differences vanish within a region; time effects are small and noisy.
- **Leave-one-out area rates when training.** *Why:* otherwise each order's own outcome leaks into its city rate.

## Decision rules

- **Thresholds are simple % cut-offs in `rules.yaml` (25 / 35 / 75)**, plus a Settings screen. *Alternative:* always
  pick the action with the best expected ₹ (no thresholds). *Why:* the brief wants thresholds a non-technical
  person can change. The ₹ maths still sets the defaults and is shown beside them ("best by ₹: nudge 29%, confirm 30%, hold 69%").
- **Hold default at 75%, above the ₹-optimal ~69-74%.** *Why:* errs toward Marketing; the extra 5-6% get a
  confirmation instead, which costs little.
- **Hard red flags hold regardless of risk %:** unusable address, fake name, 2+ past refusals, invalid phone,
  ₹0 order. Each can be switched off. *Why:* these groups return 62-78% of the time, or can't be contacted.
- **First-time buyers are never held on risk % alone** (they get a confirmation). *Why:* Marketing's ₹300 CAC
  point. Losing a genuine first order costs ~₹612 vs ₹169 for a return.
- **Possible duplicate (same phone, <60 min) → confirm.** *Why:* double checkouts are common; ask instead of
  shipping two parcels.
- **Invalid phone / ₹0 order → manual check, no WhatsApp.** *Why:* we can't message them, and ₹0 COD is a data error.

## Money assumptions

- **"Cost of losing a genuine customer" = ₹300 CAC**, but **₹0 for customers who already refused orders.**
  *Why:* that's what it costs to replace a good customer; nobody pays to win back a serial refuser.
  First version charged ₹300 for everyone, which made holding serial refusers look wrong.
- **Two hold types with their own assumptions:** "fix your address" (80% of genuine fix it, 70% of would-be
  returners never do) and "pay online only" (40% of genuine pay). *Why:* the first version assumed 95% of genuine
  buyers reply to a confirmation but only 50% fix an address, and that held returners *never* come back.
  That was inconsistent and made holds look like they lost money.
- **Customer-behaviour assumptions are explicit and editable**, with a pessimistic/optimistic run in the backtest.
  *Why:* they can't be measured until WhatsApp runs, so the memo shows the range, not one number.
- **Used each order's real value, not the brief's ₹649 average.** *Why:* the data's average is ₹919; using real
  values is more honest. The ₹649 figure is used for the threshold suggestions, as stated in the brief.

## WhatsApp flow

- **No reply to confirmation → cancel at 24h** (setting: can be "ship"). *Why:* a non-reply is the strongest
  return signal we get (by our assumptions ~87% of no-replies are would-be returns). Shipping them anyway defeats the point.
- **Prepaid nudge: no reply → ship as COD at 12h, no reminder.** *Alternative:* 24h like confirmation.
  *Why:* it's an optional offer; waiting a full day delays every medium-risk order, and genuine buyers get their parcel later.
- **"No" means different things per flow:** in the nudge, "no" = keep COD, not "cancel my order".
- **Two unclear replies → a person** (confirmation/hold) or **ships COD** (nudge).
- **Quiet hours 9 pm - 9 am.**
- **Hinglish by default for Hindi-belt states, Devanagari on request.** *Alternative:* Devanagari Hindi by default.
  *Why:* most people there type Hinglish on WhatsApp; Devanagari is one reply away.
- **Flat ₹50 discount** (maths in WHATSAPP_FLOW.md). *Alternatives:* ₹30, ₹100, a percentage. *Why:* inside the
  affordable range for the nudge band; simple to say. ₹30 vs ₹50 is the first thing to test.
- **Mock with a per-chat virtual clock** (`advance` endpoint). *Why:* lets a reviewer test "no reply in 24h" in one click.

## Dashboard & backtest

- **"Yesterday" = real date; demo data replays September as the last 30 days.** *Why:* the dataset ends in
  September, but the founder screen should open on yesterday. The demo uses the real engine; only customer replies
  are simulated, from each order's real outcome and the assumptions.
- **Dashboard ₹ figures update the risk after what the customer did.** *Why:* the first version used the starting risk,
  which undervalued cancellations of non-responders (showed −₹3k when the truth was +₹4.9k). Now it estimates
  +₹2.1k vs +₹4.9k actual, cautious but with the right sign. Check script: `scripts/check_dashboard_vs_actual.py`.
- **Ops' policy for comparison = cancel ≥50% risk + stop COD in pincodes with 2+ orders and ≥50% returns**, plus a
  table at 35% / 50% / 70%, with and without pincodes. *Why:* "risky" wasn't defined, so every reading of it is shown.
  All of them lose money.
- **Monthly = September × 5.02** (1,650 COD orders/month from the brief).

## Data cleaning

- Dropped 30 exact duplicate rows and 1 in-transit order; normalised status spellings and +91 phones.
- **Kept "Test Order" rows** in learning: they really shipped (9 of 11 came back), and the fake-name rule catches them.
- Brand name in messages is a placeholder ("Haircare Store", set `BRAND_NAME` in `.env`). I didn't guess the real brand.
