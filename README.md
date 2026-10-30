# COD Order Guard - RTO decision engine

Take-home assignment: an AI-assisted system that checks every Cash-on-Delivery order **before it ships** and decides
one of four actions, each with a plain-English reason:

| Action | Typical case | What happens next |
|---|---|---|
| ✅ **Ship as-is** | low risk | ships |
| 💳 **Nudge to prepaid** | medium risk | WhatsApp: "pay online, save ₹50". No reply in 12h → ships as COD |
| 💬 **Ship after confirmation** | high risk | WhatsApp: reply YES. No reply in 24h → cancelled |
| ⛔ **Hold / cancel** | unusable address, fake name, 2+ past refusals, very high risk | customer must fix the address or pay online, otherwise cancelled |

**Result on September 2026's real orders (which the model never saw):** returns shipped fall by a third (86 → 58)
while losing about **4** genuine orders a month. The Operations proposal ("cancel risky orders, stop COD in bad
pincodes") would lose **35** genuine orders and **₹93k/month**. → [docs/MONEY_REASONING.md](docs/MONEY_REASONING.md)

---

## For the reviewer: where each requirement is

| Assignment asks for | Where |
|---|---|
| **Part 1** - decision engine on `orders_sample.csv`, 4 actions | `rto/engine.py` · screen **1 · Check an order** · `POST /decide` |
| Use an LLM only where it helps, and say where the line is | [section below](#where-the-llm-is-used-and-where-it-isnt) · `rto/llm.py`, `rto/assess.py` · [docs/DECISION_LOG.md](docs/DECISION_LOG.md) |
| Plain-English reason for every decision | `reason` field on every decision (shown on screens 1-3) |
| Thresholds changeable without code | [`config/rules.yaml`](config/rules.yaml) (commented, plain text) **or** the **Settings** screen |
| **Part 2** - WhatsApp flow: message, language, timing, yes / no / random / no reply in 24h | [docs/WHATSAPP_FLOW.md](docs/WHATSAPP_FLOW.md) · `rto/whatsapp.py` · screen **2 · WhatsApp simulator** (working mock) |
| Prepaid discount amount and the maths | [docs/WHATSAPP_FLOW.md § 3](docs/WHATSAPP_FLOW.md#3-the-prepaid-discount-50-and-why) |
| **Part 3** - founder dashboard: buckets yesterday, ₹ saved, ₹ lost on maybe-genuine cancels, net ₹ | screen **3 · Founder dashboard** · `rto/dashboard.py` · `GET /dashboard` |
| **Part 4** - business memo (1-2 pages, for the founder) | [docs/BUSINESS_MEMO.pdf](docs/BUSINESS_MEMO.pdf) ([markdown](docs/BUSINESS_MEMO.md)) |
| Ops vs Marketing explained in ₹ | [docs/MONEY_REASONING.md](docs/MONEY_REASONING.md) · screen **4 · Ops vs Marketing** |
| Decision log | [docs/DECISION_LOG.md](docs/DECISION_LOG.md) |
| AI usage log (with cases where the AI was wrong) | [docs/AI_USAGE_LOG.md](docs/AI_USAGE_LOG.md) |
| Data findings behind the memo | [docs/DATA_FINDINGS.md](docs/DATA_FINDINGS.md) |

---

## 1. Setup (about 5 minutes)

Needs **Python 3.10 or newer** (tested on 3.12) and nothing else: no Node, no database server, no Docker.

```bash
git clone https://github.com/hiteshsaini19/cod-rto-decision-engine.git
cd cod-rto-decision-engine
python -m venv .venv
```
Activate the environment:

| System | Command |
|---|---|
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |
| macOS / Linux | `source .venv/bin/activate` |

```bash
pip install -r requirements.txt        # ~1 minute
```

> On macOS/Linux use `python3` if `python` isn't found. If PowerShell says *"running scripts is disabled"*, run
> `Set-ExecutionPolicy -Scope Process Bypass` once in that window, or use the cmd command above.

### Optional: free AI key (OpenRouter), about 2 minutes

**Everything works without a key**: messy addresses and WhatsApp replies are then judged by rules only.
With a key, a free LLM also reads Hinglish addresses, spots odd names and understands free-text replies.

1. Go to <https://openrouter.ai> → **Sign in** (Google / GitHub) → **Keys** → **Create key**. No card needed.
2. Create the `.env` file and paste the key:
   ```bash
   cp .env.example .env          # Windows cmd: copy .env.example .env
   ```
   ```
   OPENROUTER_API_KEY=sk-or-v1-...
   ```
3. Optional check (uses 2 of the 50 free requests per day): `python scripts/smoke_llm.py`

Free models on OpenRouter change often. If the defaults stop working, pick any `:free` model from
<https://openrouter.ai/models?q=free> and set `OPENROUTER_MODELS=model-a:free,model-b:free` in `.env`.
If the AI fails or takes longer than 45s, the app uses the rules automatically and says so on screen.

## 2. Run it (two terminals, environment activated in both)

**Terminal 1: backend API**
```bash
uvicorn backend.main:app --port 8000
```
Interactive API docs: <http://localhost:8000/docs>

**Terminal 2: frontend**
```bash
streamlit run frontend/app.py
```
Opens <http://localhost:8501> (if it asks for an email on first run, just press Enter).

## 3. Try it (about 5 minutes)

1. **3 · Founder dashboard** → click **Load demo data**. September's 329 real orders are replayed as the last 30
   days through the real engine and WhatsApp flows, with simulated customer replies. You see yesterday's
   4 buckets, ₹ saved, ₹ lost and net ₹ impact, plus a 30-day trend and every order with its reason.
2. **1 · Check an order** → pick each example from the dropdown and click **Check only**:

   | Example | Decision |
   |---|---|
   | Clean repeat customer, Mumbai | Ship as-is (6%) |
   | Medium risk: first order, Lucknow | Nudge to prepaid (33%) |
   | Hinglish address, first order, Gorakhpur | Ship after confirmation: 76% risk, but a first-time buyer is never held on risk alone |
   | Junk address 'xyz' / Fake name 'asdf' | Hold: ask for the full address |
   | Refused 2 orders before | Hold: pay online only |
   | Invalid phone (9 digits) | Hold: ops team to call |

   Edit any field and check again. The tabs show **why** (risk points), **what the rules / AI said** about the
   text, and the **₹ check** (expected ₹ of each action).
3. On a risky example click **Place order & start WhatsApp**, then open **2 · WhatsApp simulator**:
   - reply `haan bhej do` → confirmed · `NO` → cancelled · `PAY` → payment link → **Customer pays the link**
   - reply something random twice → handed to a person
   - **⏩ +12 h** → reminder · **⏩ +24 h** → no reply → cancelled
   - reply `hindi` → messages switch to Hindi · with an AI key, try `kal shaam ko bhejna, abhi bahar hu`
4. **4 · Ops vs Marketing** → every policy on September's real orders, in ₹ per month.
5. **Settings** → set *Nudge to prepaid from risk %* to **5**, **Save**, and check *Clean repeat customer, Mumbai*
   again: Ship → Nudge. The change is written to `config/rules.yaml` (undo with `git checkout config/rules.yaml`).

### Automated checks
```bash
pytest                                        # 134 tests: rules, ₹ maths, engine, WhatsApp flows, full API flow
python scripts/check_frontend.py              # every screen, against the running backend (Terminal 1)
python scripts/run_backtest.py                # Ops vs Marketing vs our system, in the terminal
python scripts/check_dashboard_vs_actual.py   # dashboard estimate vs what really happened (after loading demo data)
```
Tests never call the real LLM and never touch your database or `rules.yaml`.

---

## How it works

```
order ─► rule checks (phone, address, name, pincode) ──unclear text only──► LLM via OpenRouter
              │                                                  (cached, batched, 45s cap, falls back to rules)
              ▼                                                                   │
       risk % = logistic regression on 10 facts ◄─────────────────────────────────┘
       (area return rate, first order, past refusals, address quality, order value, ad source…)
              │
              ▼
   hard red flag? ──yes──► HOLD
              │ no
              ▼
   thresholds in config/rules.yaml ─► SHIP / NUDGE / CONFIRM / HOLD
   + guardrails (first-time buyers never held on risk alone, duplicate orders confirmed)
              │
              ▼
   plain-English reason + expected ₹ of every action ─► WhatsApp flow (mock) ─► dashboard
```

The risk model was learnt on April-August 2026 and tested on September: **AUC 0.744**, and predicted risk matches
reality (e.g. predicted 80% → 80% actually came back). Details: [docs/DATA_FINDINGS.md](docs/DATA_FINDINGS.md).

### Where the LLM is used, and where it isn't

| Job | Done by | Why |
|---|---|---|
| Is "Station chowk se left, Hanuman Mandir ke saamne" deliverable? | **LLM**, only when rules can't tell | Open-ended Hinglish text; no rule list covers every way people write addresses |
| Is "qwerty" / "Test Order" a fake name? | Rules first, **LLM** for odd ones | Obvious fakes are a short list; rare cases need judgement |
| What does "kal shaam ko bhejna, abhi bahar hu" mean? | Rules for YES / NO / 1 / 2 / haan / nahi, **LLM** for the rest | Most replies are one word; free text needs language understanding |
| Phone valid? Pincode matches the state? Duplicate order? | Code | Exact checks: an LLM would be slower, cost money and sometimes be wrong |
| Risk %, thresholds, ₹ maths, dashboard numbers | Code / maths | Must be exact, repeatable and auditable. An LLM gives different answers on reruns |
| The plain-English reason | Code (filled from the facts actually used) | The reason must match the real calculation |

Only ~25% of orders have text the rules can't judge. Those answers are cached (the same address is never sent
twice) and sent 20 per request. A guardrail stops an LLM "unusable address" opinion from holding an order on its own.

## Project layout

```
README.md
docs/                    ← memo (PDF + md), money reasoning, WhatsApp flow, data findings, decision & AI logs
config/rules.yaml        ← thresholds, costs, assumptions: edit freely (or use the Settings screen)
config/risk_model.json   ← learnt risk weights (rebuild: python scripts/build_model.py)
rto/                     ← the engine
  text_checks.py, assess.py, llm.py   rule checks + LLM (OpenRouter) with cache, guardrail & fallback
  model.py                            risk % (logistic regression, area rates)
  economics.py                        all ₹ maths
  engine.py                           Part 1: the decision + reason
  whatsapp.py                         Part 2: templates (English / Hinglish / Hindi), timing, reply handling
  dashboard.py                        Part 3: the founder's numbers
  backtest.py                         every policy on last month's orders (Part 4 numbers)
  data.py, store.py, demo.py          cleaning, SQLite storage, demo data
backend/main.py          ← FastAPI
frontend/                ← Streamlit screens (app.py + views/)
scripts/                 ← build model, fill LLM cache, backtest, demo data, checks
tests/                   ← pytest
data/raw/orders_sample.csv   the dataset provided
data/llm_cache.json          LLM answers for the dataset's messy addresses (so nothing needs re-asking)
```

## Rebuilding from scratch (optional)
```bash
python scripts/fill_llm_cache.py   # ask the LLM about every unclear address once (~10 requests; needs a key)
python scripts/build_model.py      # clean the data, learn weights on Apr-Aug, test on Sep
```

## Troubleshooting
- **"Can't reach the backend"** on a screen: start Terminal 1 first.
- **Sidebar says the AI failed → rules used**: the free model was busy (HTTP 429) or the 50 daily free requests ran
  out. Decisions still work. Try later or change `OPENROUTER_MODELS`.
- **Port already in use**: `uvicorn backend.main:app --port 8001`, then start the frontend with
  `BACKEND_URL=http://localhost:8001` set in the environment (or in `.env`).
- **Fresh start**: stop the backend and delete `data/app.db`.
