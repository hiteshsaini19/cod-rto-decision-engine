# AI usage log

## Tools used

| Tool | Used for |
|---|---|
| **Claude Code** (Anthropic, Claude Opus model) | Exploring the data, writing the code and tests, running the backtests, drafting these documents. I reviewed the outputs, questioned the numbers and steered decisions (e.g. choosing OpenRouter, the "explain in ₹" structure, plain-language docs). |
| **OpenRouter free LLMs** (inside the product): `dots-studio/dots-3-note-preview`, `nvidia/nemotron-3.5-lightning`, `nvidia/nemotron-3.5-super-vl`, `google/gemma-4-31b-it` | Judging messy / Hinglish addresses, odd names, and free-text WhatsApp replies |
| (rejected) `liquid/lfm-2.5-2.6b`, `thinkingmachines/inkling-small` | Tested; wrong answers / access errors |

## Where the AI was wrong or weak, and how it was caught

### 1. The LLM gave different answers for the same kind of address
**What happened:** while caching LLM answers for the dataset, addresses of the form *"ph krke aana, Masjid ke paas"*
("call before coming, near the mosque") were marked **unusable** 3 times and **incomplete** ~40 times.
"Unusable" triggers a hold, so 3 real orders would have been held at random.
**Caught by:** counting the cached labels per address pattern instead of trusting them.
**Fixed:** guardrail in `rto/assess.py`. If the LLM says "unusable" but the text names a real place (near / chowk /
mandir / masjid / gali…), it's downgraded to "incomplete". A hold never rests on one LLM opinion. Cached answers
also keep repeat decisions consistent. (A later live call rated a similar Bihar address "complete" while the
probe minutes earlier said "incomplete". Borderline addresses really do flip between models.)

### 2. A small free model misread a Hinglish WhatsApp reply
**What happened:** *"kal subah bhejna bhai, abhi ghar pe nahi hu"* ("send it tomorrow morning, I'm not home now")
was read as **keep_cod** by the small Liquid model, and as **unclear** by the bigger models. The customer clearly
wants the order.
**Caught by:** probing candidate models with real-style replies before choosing the default list.
**Fixed:** dropped the small model; added an explicit rule to the prompt ("send it tomorrow / not home now = yes,
only the timing differs"). Now: "yes". Also: "paise nahi hai abhi" ("no money right now") → "no", which is exactly
the would-be return we want to catch.

### 3. Claude's dashboard maths showed the wrong sign
**What happened:** the first dashboard valued every order *we* cancelled using its starting risk (e.g. 42%). Over
30 demo days it showed **−₹3,027**, while the backtest on the same orders said the system makes money.
**Caught by:** reconciling the dashboard with the backtest, then writing `scripts/check_dashboard_vs_actual.py`,
which compares the estimate with the orders' real outcomes.
**Fixed:** the estimate now updates the risk with what the customer did. Someone who ignores a confirmation for 24h
is ~87% likely to be a would-be return under our assumptions, not 42%. Result: estimate **+₹2,127** vs actual
**+₹4,893**: right sign, cautious.

### 4. Claude's WhatsApp parser would have cancelled real orders
**What happened:** a customer replying with *"House **No.** 12, Sector 4, …"* was read as **"NO"** and the order
was cancelled. "no thanks" (to the discount) was also missed.
**Caught by:** the automated tests (`tests/test_whatsapp.py`) failed.
**Fixed:** "No. 12" is treated as "number 12"; anything that looks like a full address is checked as an address
before looking for yes/no; word-level matching for short words.

### 5. Claude's first hold assumptions were inconsistent
**What happened:** it assumed 95% of genuine buyers answer a confirmation but only 50% fix their address, and that
held would-be returners *never* fix theirs. It also charged ₹300 "win-back cost" for customers who had already
refused 2 orders. Together these made holds look money-losing (the system showed −₹2.6k/month).
**Caught by:** breaking the backtest down per bucket and per hold reason, then checking that the assumptions
described the same customers consistently.
**Fixed:** separate, consistent assumptions for "fix address" and "pay online" holds; win-back cost ₹0 for past
refusers. Expected result became +₹9.5k/month, with the pessimistic/optimistic range shown, not hidden.

### 6. Overclaiming in chat
**What happened:** while planning, Claude said its first address check had "missed" city-only addresses ("Mumbai").
On re-checking, that wasn't true: the length rule had caught them by accident. It also first said ~6% of orders are
riskier than 65%; the real figure is ~4%.
**Caught by:** re-running the numbers before putting them in documents.
**Fixed:** added an explicit "address = city name" rule; every number in these documents comes from a script run.

## How I used AI

- Every claimed number was re-run from code before it went into a document.
- Tests were written for the behaviour that matters (e.g. "a first-time buyer is never held on risk alone"), and they caught real bugs.
- LLM output is treated as an opinion with a guardrail and a fallback, never as the decision.
