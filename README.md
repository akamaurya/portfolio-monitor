# 📊 Portfolio Monitor

[![Tests](https://github.com/akamaurya/portfolio-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/akamaurya/portfolio-monitor/actions/workflows/tests.yml)
[![Monthly Report](https://github.com/akamaurya/portfolio-monitor/actions/workflows/monthly_report.yml/badge.svg)](https://github.com/akamaurya/portfolio-monitor/actions/workflows/monthly_report.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)

An unattended monthly research report on your own Zerodha portfolio, delivered to your inbox.

On the 1st of every month a GitHub Actions cron logs into Kite, pulls your equity and mutual fund holdings, enriches them with live market data, gathers current market research, has Gemini write an analyst-style review grounded in that research, and emails it as a formatted HTML report. No laptop, no manual steps, no servers, ₹0/month.

> 🌐 **[Project showcase →](https://akamaurya.github.io/portfolio-monitor/)** · **[Sample report →](https://akamaurya.github.io/portfolio-monitor/sample-report.html)**

<p align="center">
  <img src="docs/assets/report-email-top.png" width="46%" alt="Top of the report email: a Portfolio Desk masthead, a net portfolio value of ₹1,11,953 up 11.69%, and an allocation bar splitting equity from mutual funds." />
  <img src="docs/assets/report-email-holdings.png" width="46%" alt="Holdings section: a ruled table of eight equity positions with quantity, average cost, market price, value, P&L and a one-word call." />
</p>

<p align="center"><sub>The monthly note, rendered from a hypothetical demo portfolio.</sub></p>

---

## Architecture

```
GitHub Actions (cron: 1st of month, 09:30 IST)
  │
  ├─ 1. auth.py       HTTP login + TOTP → enctoken-authenticated Kite client
  ├─ 2. portfolio.py  Equity holdings, mutual fund (Coin) holdings, open positions
  ├─ 3. prices.py     yfinance enrichment (price, sector, P/E, 52w range) + aggregation
  ├─ 4. research.py   FII/DII flows, brokerage report PDFs, macro indicators
  ├─ 5. analyst.py    Gemini → 7-section markdown note
  └─ 6. emailer.py    Table-based HTML email via Gmail SMTP (+ failure alerts)
```

`main.py` runs these as a 7-step pipeline (auth → fetch → enrich → summarise → research → generate → send) and, if any step raises, emails the traceback before exiting non-zero.

### Authentication without Kite Connect

Kite Connect's OAuth flow needs a paid app and a browser redirect that can't be automated cleanly from CI. This project instead uses the same `enctoken` mechanism Kite's own web frontend uses:

1. `POST /api/login` with user ID + password → `request_id`
2. `POST /api/twofa` with a TOTP generated from your secret → `enctoken` cookie
3. Send `Authorization: enctoken <token>` on every subsequent Kite web API call

The result is headless, dependency-light (`requests` + `pyotp`, no browser), and free. The trade-off is that these are undocumented internal endpoints, so `src/auth.py` is the module most likely to need maintenance if Zerodha changes them — see [Troubleshooting](#troubleshooting).

### Design notes

A few decisions worth calling out, since they're what make an unattended monthly job trustworthy:

- **Degrade, don't crash.** A missing Yahoo ticker, an empty mutual fund account or an unreachable brokerage PDF each log a warning and continue. Only auth, Gemini and SMTP failures are fatal.
- **Fallback chain for the LLM.** Qwen 3.8 (27B) on Groq first, then two Gemini models × up to three keys — seven combinations in all. Groq speaks the OpenAI chat-completions protocol, so adding another such provider is a dict entry. A response that comes back empty, blocked, truncated, or missing most of its sections is treated as a failure so the next combination is tried — a note cut off mid-table is worse than none at all, because it still looks deliverable.
- **Fail loudly when it does fail.** Any unhandled exception triggers a failure-alert email with the traceback, so a broken run can't quietly go unnoticed for a month.
- **Everything is bounded.** Every HTTP and SMTP call has an explicit timeout, and the workflow has a 15-minute cap — a hung request can't burn CI minutes.
- **IST everywhere.** Runners are UTC, but this is an India-market report; all dates and timestamps go through `src/clock.py` so month labels and the "generated at" stamp are correct.
- **Built as email, not as a web page.** The template is nested tables. Gmail and Outlook strip flexbox and grid, which silently collapses a flex row into a stack — tables render identically in every client, on desktop and phone.
- **A demo mode that can't be mistaken for real.** `--demo` swaps in a hypothetical portfolio and logs the substitution as a warning; everything downstream still runs for real. See [Demo mode](#demo-mode).
- **Pure logic is tested.** Ticker mapping, portfolio aggregation, currency formatting and holdings cleaning are covered by offline unit tests that run on every push.

---

## Setup

### 1. Get your TOTP secret

1. Log in to [kite.zerodha.com](https://kite.zerodha.com)
2. Go to **My Profile → App Authentication (External TOTP)**
3. During setup Zerodha shows a QR code **and** a text secret key — the base32 string (like `JBSWY3DPEHPK3PXP`) is your `KITE_TOTP_SECRET`
4. ⚠️ This is *not* the 6-digit code. It's the secret that generates those codes, so treat it like a password.

### 2. Get Gemini API keys

1. Go to [aistudio.google.com](https://aistudio.google.com) → **Get API key**
2. Create up to three keys (from different projects) for redundancy — only the first is required
3. The free tier is far more than enough: this runs one request per month

### 2b. Optional: a Groq key (main choice)

Set `GROQ_API_KEY` (from [console.groq.com](https://console.groq.com)) and the
pipeline asks `qwen/qwen3.8-27b` first, with its reasoning hidden so only the
note comes back. The endpoint is OpenAI-compatible, so this needs no extra
dependency. If Groq is rate-limited or the model is unavailable, the run falls
back to Gemini automatically.

### 3. Create a Gmail app password

1. **Google Account → Security → 2-Step Verification → App passwords**
2. Create one for "Mail" and copy the 16-character password

### 4. Add GitHub secrets

Push the repo, then go to **Settings → Secrets and variables → Actions** and add:

| Secret               | Required | Description                                        |
|----------------------|----------|----------------------------------------------------|
| `KITE_USER_ID`       | ✅        | Zerodha login ID (e.g. `AB1234`)                   |
| `KITE_PASSWORD`      | ✅        | Zerodha login password                             |
| `KITE_TOTP_SECRET`   | ✅        | Base32 TOTP secret (not the 6-digit code)          |
| `GEMINI_API_KEY1`    | ✅        | Gemini API key from Google AI Studio               |
| `GROQ_API_KEY`       | —        | Groq key; Qwen 3.8 tried first when set            |
| `GEMINI_API_KEY2`    | —        | Fallback Gemini key                                |
| `GEMINI_API_KEY3`    | —        | Second fallback Gemini key                         |
| `GMAIL_ADDRESS`      | ✅        | Gmail address to send from                         |
| `GMAIL_APP_PASSWORD` | ✅        | 16-character Gmail app password                    |
| `RECIPIENT_EMAIL`    | ✅        | Where the report is delivered                      |

### 5. Test it

**Actions → Monthly Portfolio Report → Run workflow** triggers a run immediately.

---

## Local development

```bash
git clone https://github.com/akamaurya/portfolio-monitor.git
cd portfolio-monitor

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in your credentials
python main.py
```

### Demo mode

To show the pipeline without exposing real holdings — a screen recording, a
walkthrough, or just a first run before your credentials are set up:

```bash
python main.py --demo             # hypothetical portfolio, real everything else
python main.py --demo --preview   # …and write the email to out/preview.html instead of sending
```

`--demo` substitutes `src/demo.py` for the Kite login and the holdings fetch,
and nothing else. Live prices, the research scrape, the Gemini call and the
email delivery all still happen, so what you are watching is the real pipeline
on invented holdings — eight liquid NSE names and two funds, with average
costs spread either side of their usual bands so the note has genuine winners
and losers to discuss. The run logs `DEMO MODE` at WARNING level so a demo can
never be mistaken for a live report.

`--preview` writes the rendered email to `out/preview.html` and sends nothing.
It works with or without `--demo`, and is the fastest way to iterate on the
template.

`.env` is git-ignored and secrets are never logged — the Gemini key is truncated to four characters in log output, and nothing else prints credentials.

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite is fully offline — no Kite, Yahoo, Gemini or SMTP calls — and runs in CI on every push.

---

## What the report contains

Gemini returns markdown with a fixed seven-section structure — tables over
prose, no emoji, and every numeric column right-aligned so the figures line up
down the page:

| # | Section | Contents |
|---|---------|----------|
| 1 | The month in one line | The single thing that moved the portfolio, and the three figures that matter |
| 2 | Holdings | Every equity position and every fund, each with a one-word call: ADD / HOLD / TRIM / EXIT |
| 3 | What moved | Three winners and three laggards, each with its reason — or marked as unexplained |
| 4 | Allocation | Sector weights, and a plain reading of where the book is concentrated |
| 5 | Market backdrop | India first (FII/DII flows, RBI, earnings), then the Fed, US yields, Brent and the dollar |
| 6 | The calls | 3–5 actions, most important first, each with the price that would trigger it |
| 7 | Watchlist | 2–3 names not currently held, with the level worth buying below |

The prompt in `src/analyst.py` fixes the section list, the table shapes and the
column alignment, and bans invented figures: anything not present in the
supplied data is to be omitted rather than estimated. The ▲/▼ direction markers
and the one-word call column are what `emailer._style_markers` keys off to
colour the numbers and render the call chips.

### Report design

The email is a research note rather than a dashboard: a masthead with a
stacked thick/thin rule, one dominant figure, an equity-versus-funds allocation
bar, and ruled tables with no zebra striping. Type does three jobs — a
humanist serif for voice, the system sans for utility text, and a monospace
reserved for figures. `docs/style.css` shares the same palette and type stacks,
so the showcase site and the email it advertises look like one system.

### Research grounding

Before the report is generated, `research.py` collects live context so the analysis references current data rather than the model's training cut-off:

- **FII/DII flows** — monthly net buy/sell figures via web search
- **Brokerage reports** — PDFs from ICICI Direct (sector updates, market strategy, model portfolio) and HDFC Securities, with text extracted via `pypdf`
- **Macro indicators** — Nifty 50, repo rate, CPI, Brent crude, INR/USD

Each source is best-effort: whatever is reachable that month goes into the prompt, and the report is still generated if none of it is.

---

## Cost

| Service            | Free tier                          | This project uses     |
|--------------------|------------------------------------|-----------------------|
| Zerodha Kite       | Free — no Kite Connect app needed  | 1 login/month         |
| Yahoo Finance      | Unlimited                          | ~20–50 lookups/month  |
| Google Gemini API  | Generous free tier                 | 1 request/month       |
| Groq               | Free tier, optional                | 1 request/month       |
| Gmail SMTP         | 500 emails/day                     | 1–2 emails/month      |
| GitHub Actions     | 2,000 minutes/month                | ~5 minutes/month      |

**Total: ₹0/month.**

---

## Troubleshooting

**Login fails.** `src/auth.py` uses undocumented Kite web endpoints. Check that `/api/login` still returns `{"status": "success", "data": {"request_id": ...}}` and that `/api/twofa` still sets an `enctoken` cookie; compare against Kite's own network traffic in browser DevTools.

**TOTP rejected.** `pyotp` uses the system clock. Runners are NTP-synced; if you're running locally, check your machine's time.

**A stock shows no price.** Some Indian ETFs have irregular Yahoo tickers. The code falls back to Kite's last traded price and logs a warning; add a permanent mapping to `_TICKER_OVERRIDES` in `src/prices.py`.

**No email arrived.** Check spam, confirm `GMAIL_APP_PASSWORD` is an app password rather than the account password, and that 2-Step Verification is on.

**Gemini errors.** Up to nine model/key combinations are attempted — the logs name the failure for each. Preview model IDs change; update `models_to_try` in `src/analyst.py` if they're retired.

**Provider errors.** The logs print Groq's own message rather than the bare HTTP status, so a rate limit or a retired model ID is named. Neither is fatal — the run falls back to Gemini.

**The report arrives half-written.** It shouldn't: a truncated response is rejected and the next model is tried. If it happens anyway, the note ran long enough to exhaust `max_output_tokens` in `src/analyst.py` — raise it. Gemini 3 counts thinking tokens against that same budget, which is why it is set well above the length of the note itself.

---

## Project structure

```
portfolio-monitor/
├── .github/workflows/
│   ├── monthly_report.yml   ← cron + manual trigger for the report
│   └── tests.yml            ← pytest on every push
├── docs/                    ← GitHub Pages showcase (static HTML/CSS)
│   ├── assets/              ← Report screenshots used here and on the site
│   └── sample-report.html   ← A rendered demo note, published as-is
├── src/
│   ├── auth.py              ← HTTP login + TOTP → enctoken client
│   ├── portfolio.py         ← Holdings, MF holdings, positions
│   ├── prices.py            ← yfinance enrichment + portfolio aggregation
│   ├── research.py          ← FII/DII flows, brokerage PDFs, indicators
│   ├── analyst.py           ← Gemini report generation with fallbacks
│   ├── emailer.py           ← Table-based HTML email + failure alerts
│   ├── demo.py              ← Hypothetical portfolio for --demo runs
│   └── clock.py             ← IST-aware clock for a UTC runner
├── tests/                   ← Offline unit tests
├── main.py                  ← Pipeline entry point
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Tech stack

| Component    | Technology                                        |
|--------------|---------------------------------------------------|
| Language     | Python 3.11                                       |
| Auth         | `requests` + `pyotp` (enctoken flow)              |
| Market data  | `yfinance`                                        |
| Research     | DuckDuckGo HTML search + `pypdf` PDF extraction   |
| AI           | `google-genai` (Gemini 3.1 Pro / Flash)           |
| Email        | `smtplib` + `markdown` → styled HTML              |
| Automation   | GitHub Actions (monthly cron)                     |
| Showcase     | GitHub Pages                                      |

---

## Disclaimer

A personal project, not affiliated with or endorsed by Zerodha, Google or Yahoo. It automates a login flow using undocumented endpoints, which Zerodha may change or disallow at any time. Nothing it produces is investment advice.
