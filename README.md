# 📊 Indian Equity & Mutual Fund Portfolio Monitor

Fully automated monthly portfolio reporting for Zerodha users. Runs on a cron via GitHub Actions — **no laptop needed, no manual steps**.

On the 1st of every month it will: authenticate with Zerodha Kite (enctoken-based HTTP login + TOTP), fetch your equity and mutual fund holdings, enrich them with live Yahoo Finance data, gather market research context (FII/DII flows, brokerage reports, key indicators), generate a deep research-grade report via Google Gemini, and email you a beautifully formatted HTML report.

> 🌐 **[Project Showcase →](https://akamaurya.github.io/portfolio-monitor/)**

---

## Architecture

```
GitHub Actions (cron: 1st of month, 9:30 AM IST)
  │
  ├─ 1. auth.py        HTTP login + TOTP → enctoken-based Kite client
  ├─ 2. portfolio.py    Fetch equity holdings, MF (Coin) holdings & positions
  ├─ 3. prices.py       Enrich equities with yfinance (price, sector, P/E, 52w range…)
  ├─ 4. research.py     Gather market research (FII/DII flows, brokerage PDFs, indicators)
  ├─ 5. analyst.py      Gemini API → visual, scannable research report
  └─ 6. emailer.py      Send styled HTML email via Gmail SMTP (+ failure alerts)
```

### How Authentication Works

The project authenticates using Zerodha's **enctoken** method — the same mechanism used by Kite's frontend:

1. `POST /api/login` with credentials → `request_id`
2. `POST /api/twofa` with TOTP code → `enctoken` cookie
3. Use `enctoken` header for all subsequent Kite web API calls

This is fast, headless, and doesn't require a Kite Connect app or OAuth flow.

---

## One-Time Setup

### a. Get Your TOTP Secret Key

1. Log in to [kite.zerodha.com](https://kite.zerodha.com)
2. Go to **My Profile → App Authentication (External TOTP)**
3. When setting up an authenticator app, Zerodha shows a **QR code** and a **text secret key**
4. The **text secret key** (base32 string like `JBSWY3DPEHPK3PXP`) is your `KITE_TOTP_SECRET`
5. ⚠️ This is **NOT** the 6-digit code — it's the underlying secret that *generates* the codes

### b. Get Gemini API Keys

1. Go to [aistudio.google.com](https://aistudio.google.com) → **Get API Key**
2. Create **up to 3 API keys** for redundancy — the system tries each key with a fallback model chain
3. The free tier is more than sufficient (1 request/month)

### c. Set Up Gmail App Password

1. Go to **Google Account → Security → 2-Step Verification → App Passwords**
2. Create an App Password for "Mail"
3. Copy the 16-character password — this is your `GMAIL_APP_PASSWORD`

### d. Push Code & Add Secrets

1. Create a GitHub repo and push this project
2. Go to **Settings → Secrets and variables → Actions**
3. Add each secret:

| Secret Name         | Description                                          |
|---------------------|------------------------------------------------------|
| `KITE_USER_ID`      | Your Zerodha login ID (e.g. `AB1234`)                |
| `KITE_PASSWORD`     | Your Zerodha login password                          |
| `KITE_TOTP_SECRET`  | Base32 TOTP secret string (NOT the 6-digit code)     |
| `GEMINI_API_KEY1`   | Primary Gemini API key from Google AI Studio         |
| `GEMINI_API_KEY2`   | *(Optional)* Fallback Gemini API key                 |
| `GEMINI_API_KEY3`   | *(Optional)* Second fallback Gemini API key          |
| `GMAIL_ADDRESS`     | Gmail address to send from                           |
| `GMAIL_APP_PASSWORD`| 16-char Gmail App Password                           |
| `RECIPIENT_EMAIL`   | Email address to receive the report                  |

### e. Test It

Go to **Actions → Monthly Portfolio Report → Run workflow** (manual trigger) and check output.

---

## Local Development

```bash
# 1. Clone the repo
git clone <your-repo-url> && cd portfolio-monitor

# 2. Create & fill .env
cp .env.example .env
# Edit .env with your real credentials

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

---

## Cost

| Service                | Free Tier                                     | This Project Uses         |
|------------------------|-----------------------------------------------|---------------------------|
| Zerodha (enctoken)     | Free — no Kite Connect app needed             | 1 login/month             |
| Yahoo Finance (yfinance)| Unlimited                                    | ~20-50 ticker lookups     |
| Google Gemini API      | 50 req/day (Pro), 1500/day (Flash)            | **1 request/month**       |
| Gmail SMTP             | 500 emails/day                                | 1-2 emails/month          |
| GitHub Actions         | 2000 min/month (free tier)                    | ~3 min/month              |

**Total cost: ₹0/month.**

---

## What the Report Covers

The Gemini-generated report is visually rich, scannable, and uses tables & emoji indicators throughout:

1. **📊 Portfolio Snapshot** — total value, invested, P&L with equity/MF breakdown
2. **📈 Equity Holdings** — full table with qty, avg cost, CMP, value, P&L %, and verdict (HOLD/ADD/TRIM/WATCH)
3. **🏦 Mutual Fund Holdings** — all MF holdings with invested vs. current value
4. **🥇 Winners & Losers** — top 3 performers and bottom 3 with reasons
5. **🏗️ Sector Allocation** — sector breakdown table including MF allocation
6. **💰 FII/DII Flows** — latest foreign & domestic institutional flow data with portfolio implications
7. **🌍 Market Context** — India macro (RBI, inflation, policy) and Global (Fed, DXY, oil, geopolitics)
8. **📑 Research Report Highlights** — insights from brokerage reports (ICICI Direct, HDFC Securities, etc.)
9. **🔍 Key Holdings Review** — deep dive on top holdings with valuation & action items
10. **⚠️ Action Items** — 3-5 specific actions for the month
11. **🎯 Watchlist** — 2-3 stocks/funds to track with target entry prices

### Market Research Integration

Before generating the report, the pipeline gathers live market research context:

- **FII/DII flow data** — scraped via web search (monthly net buy/sell in ₹ crores)
- **Brokerage reports** — downloads PDFs from ICICI Direct (sector updates, market strategy, model portfolio) and HDFC Securities, extracts key text
- **Market indicators** — Nifty 50, RBI repo rate, CPI inflation, Brent crude, INR/USD rate

This grounding data is passed to Gemini so the report references real, current market data — not just the model's training knowledge.

---

## Gemini Model Fallback

The system tries multiple Gemini models with multiple API keys for maximum reliability:

```
gemini-3.1-pro-preview  →  gemini-3-flash-preview  →  gemini-3.1-flash-lite-preview
         ×                          ×                            ×
     Key 1, 2, 3              Key 1, 2, 3                 Key 1, 2, 3
```

If a model + key combination fails, it moves to the next. Only if **all** combinations fail does the pipeline error out — and even then, a failure notification email is sent so you know it broke.

---

## Failure Notifications

If the pipeline crashes at any step, the system attempts to send a failure notification email with the full stack trace. This ensures broken runs never go unnoticed, even if you're not checking GitHub Actions.

---

## Troubleshooting

### TOTP Issues
`pyotp` generates codes using the system clock. On GitHub Actions runners, the clock is always synced. If testing locally, ensure your machine's time is accurate.

### Login Failures
The auth module uses Kite's web API endpoints (`/api/login` and `/api/twofa`). If Zerodha changes their API:
1. Check the response from `/api/login` — it should return `{"status": "success", "data": {"request_id": "..."}}`
2. Check the response from `/api/twofa` — it should set an `enctoken` cookie
3. Compare with Kite's frontend behavior in browser DevTools

### yfinance Failures
Some Indian ETFs and mutual funds have inconsistent Yahoo Finance tickers. The code:
- Falls back to Kite's last price if Yahoo returns nothing
- Logs a warning but **never crashes** on a single ticker failure
- Has a hardcoded override map in `src/prices.py` — add new mappings there

### Email Not Received
- Check spam/junk folder
- Verify `GMAIL_APP_PASSWORD` is an **App Password**, not your login password
- Ensure 2-Step Verification is enabled on the Gmail account

### Gemini API Errors
- Verify your API keys are valid at [aistudio.google.com](https://aistudio.google.com)
- The system tries 3 models × 3 keys (up to 9 attempts) — check logs for specific error messages
- Model names may change; update `models_to_try` in `src/analyst.py` if needed

---

## Project Structure

```
portfolio-monitor/
├── .github/workflows/
│   └── monthly_report.yml      ← GitHub Actions cron + manual trigger
├── docs/
│   ├── index.html              ← GitHub Pages showcase site
│   ├── style.css
│   └── script.js
├── src/
│   ├── __init__.py
│   ├── auth.py                 ← HTTP login + TOTP → enctoken client
│   ├── portfolio.py            ← Equity + MF holdings + positions fetcher
│   ├── prices.py               ← yfinance enrichment + portfolio summary
│   ├── research.py             ← Market research context (FII/DII, reports, indicators)
│   ├── analyst.py              ← Gemini report generator (multi-model/key fallback)
│   └── emailer.py              ← Gmail HTML email sender + failure notifications
├── main.py                     ← Single entry point (7-step pipeline)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Tech Stack

| Component       | Technology                                         |
|-----------------|---------------------------------------------------|
| Language        | Python 3.11                                        |
| Auth            | `requests` + `pyotp` (enctoken method)             |
| Market Data     | `yfinance`                                         |
| Research        | Web scraping + `pypdf` for brokerage PDF extraction |
| AI              | Google `google-genai` SDK (Gemini 3.1 Pro/Flash)   |
| Email           | `smtplib` + `markdown` → styled HTML               |
| Automation      | GitHub Actions (monthly cron)                      |
| Showcase        | GitHub Pages (static HTML/CSS/JS)                  |

---

## License

Private use. Not affiliated with Zerodha, Google, or Yahoo.
