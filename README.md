# 📊 Indian Equity & Mutual Fund Portfolio Monitor

Fully automated monthly portfolio reporting for Zerodha users. Runs on a cron via GitHub Actions — **no laptop needed, no manual steps**.

On the 1st of every month it will: authenticate with Kite Connect (headless Playwright + TOTP), fetch your holdings, enrich them with live Yahoo Finance data, generate a deep research-grade report via Google Gemini, and email you a beautifully formatted HTML report.

---

## Architecture

```
GitHub Actions (cron: 1st of month, 9:30 AM IST)
  │
  ├─ 1. auth.py        Playwright headless login → Kite access_token
  ├─ 2. portfolio.py    Fetch holdings & positions from Kite API
  ├─ 3. prices.py       Enrich with yfinance (price, sector, P/E, 52w range…)
  ├─ 4. analyst.py      Gemini API → 10-section research report
  └─ 5. emailer.py      Send styled HTML email via Gmail SMTP
```

---

## One-Time Setup

### a. Create a Kite Connect App

1. Go to [kite.trade/connect/apps](https://kite.trade/connect/apps)
2. Create a **Personal** app
3. Set **Redirect URL** to: `http://127.0.0.1`
4. Note your **API Key** and **API Secret**

### b. Get Your TOTP Secret Key

1. Log in to [kite.zerodha.com](https://kite.zerodha.com)
2. Go to **My Profile → App Authentication (External TOTP)**
3. When setting up an authenticator app, Zerodha shows a **QR code** and a **text secret key**
4. The **text secret key** (base32 string like `JBSWY3DPEHPK3PXP`) is your `KITE_TOTP_SECRET`
5. ⚠️ This is **NOT** the 6-digit code — it's the underlying secret that *generates* the codes

### c. Get a Gemini API Key

1. Go to [aistudio.google.com](https://aistudio.google.com) → **Get API Key**
2. The free tier is more than sufficient (1 request/month)

### d. Set Up Gmail App Password

1. Go to **Google Account → Security → 2-Step Verification → App Passwords**
2. Create an App Password for "Mail"
3. Copy the 16-character password — this is your `GMAIL_APP_PASSWORD`

### e. Push Code & Add Secrets

1. Create a GitHub repo and push this project
2. Go to **Settings → Secrets and variables → Actions**
3. Add each secret:

| Secret Name       | Description                                     |
|--------------------|------------------------------------------------|
| `KITE_API_KEY`     | From Kite Connect dashboard                    |
| `KITE_API_SECRET`  | From Kite Connect dashboard                    |
| `KITE_USER_ID`     | Your Zerodha login ID (e.g. `AB1234`)          |
| `KITE_PASSWORD`    | Your Zerodha login password                    |
| `KITE_TOTP_SECRET` | Base32 TOTP secret string (NOT the 6-digit code) |
| `KITE_PIN`         | *(Optional)* Your Zerodha PIN, if required     |
| `GEMINI_API_KEY`   | From Google AI Studio                          |
| `GMAIL_ADDRESS`    | Gmail address to send from                     |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password                   |
| `RECIPIENT_EMAIL`  | Email address to receive the report            |

### f. Test It

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

# 4. Install Playwright browser
playwright install chromium

# 5. Run
python main.py
```

---

## Cost

| Service               | Free Tier                          | This Project Uses        |
|------------------------|------------------------------------|--------------------------|
| Kite Connect           | Free for personal use              | 1 login/month            |
| Yahoo Finance (yfinance)| Unlimited                         | ~20-50 ticker lookups    |
| Google Gemini API      | 50 requests/day (Pro), 1500/day (Flash) | **1 request/month** |
| Gmail SMTP             | 500 emails/day                     | 1 email/month            |
| GitHub Actions         | 2000 min/month (free tier)         | ~5 min/month             |

**Total cost: ₹0/month.**

---

## What the Report Covers

The Gemini-generated report includes 10 sections:

1. **Executive Summary** — overall snapshot + top action item
2. **Portfolio Snapshot** — full holdings table with P&L
3. **Macro — India** — RBI, inflation, FII/DII flows, capex, policy
4. **Macro — Global** — Fed, DXY, oil, China, geopolitics
5. **Sectoral Deep Dive** — per-sector analysis for your holdings
6. **Individual Holding Review** — valuation, moat, recommendation per stock
7. **International & ETF Exposure** — gold, global ETFs, hedging
8. **Portfolio Construction** — concentration, gaps, rebalancing
9. **Watchlist** — 2-3 opportunities to track
10. **Key Risks** — tail risks + mitigation

---

## Troubleshooting

### TOTP Issues
`pyotp` generates codes using the system clock. On GitHub Actions runners, the clock is always synced. If testing locally, ensure your machine's time is accurate.

### Playwright Selector Errors
Kite occasionally updates their login page HTML. If auth fails:
1. Set `DEBUG_AUTH=1` in your `.env`
2. Run `python main.py`
3. Check the `debug_*.png` screenshots to see what page Playwright is seeing
4. Update selectors in `src/auth.py` if needed

### yfinance Failures
Some Indian ETFs and mutual funds have inconsistent Yahoo Finance tickers. The code:
- Falls back to Kite's last price if Yahoo returns nothing
- Logs a warning but **never crashes** on a single ticker failure
- Has a hardcoded override map in `src/prices.py` — add new mappings there

### Email Not Received
- Check spam/junk folder
- Verify `GMAIL_APP_PASSWORD` is an **App Password**, not your login password
- Ensure 2-Step Verification is enabled on the Gmail account

---

## Project Structure

```
portfolio-monitor/
├── .github/workflows/monthly_report.yml   ← GitHub Actions cron
├── src/
│   ├── __init__.py
│   ├── auth.py          ← Playwright Kite login + TOTP
│   ├── portfolio.py     ← Kite holdings fetcher
│   ├── prices.py        ← yfinance enrichment
│   ├── analyst.py       ← Gemini report generator
│   └── emailer.py       ← Gmail HTML email sender
├── main.py              ← Single entry point
├── requirements.txt
├── .env.example
└── README.md
```

---

## License

Private use. Not affiliated with Zerodha, Google, or Yahoo.
