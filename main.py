#!/usr/bin/env python3
"""
Portfolio Monitor — main entry point.

Usage:
    python main.py

Requires environment variables (see .env.example).
"""

import os
import sys
import logging
import traceback
from datetime import datetime

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("portfolio-monitor")


def _timestamp(msg: str) -> None:
    logger.info(msg)


def main() -> None:
    # ── 1. Load .env (skip in CI where secrets are injected) ─────
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
            _timestamp("Loaded .env file.")
        except ImportError:
            _timestamp("python-dotenv not installed — assuming env vars are already set.")

    # ── 2. Authenticate with Kite Connect ────────────────────────
    from src.auth import authenticate

    _timestamp("Step 1/6 — Authenticating with Kite Connect…")
    kite = authenticate()
    _timestamp("Authentication successful.")

    # ── 3. Fetch holdings & positions ────────────────────────────
    from src.portfolio import get_holdings

    _timestamp("Step 2/6 — Fetching holdings and positions…")
    portfolio_data = get_holdings(kite)
    holdings = portfolio_data["holdings"]
    positions = portfolio_data["positions"]
    _timestamp(f"Fetched {len(holdings)} holdings, {len(positions)} positions.")

    if not holdings:
        _timestamp("No holdings found — nothing to report. Exiting.")
        return

    # ── 4. Enrich with Yahoo Finance prices ──────────────────────
    from src.prices import enrich_with_prices, build_portfolio_summary

    _timestamp("Step 3/6 — Enriching holdings with live prices…")
    enriched = enrich_with_prices(holdings)
    _timestamp("Price enrichment complete.")

    # ── 5. Build portfolio summary ───────────────────────────────
    _timestamp("Step 4/6 — Building portfolio summary…")
    summary = build_portfolio_summary(enriched)
    _timestamp(
        f"Summary: invested ₹{summary['total_invested']:,.2f}, "
        f"current ₹{summary['total_current_value']:,.2f}, "
        f"P&L {summary['total_unrealized_pnl_pct']:+.2f}%"
    )

    # ── 6. Generate Gemini report ────────────────────────────────
    from src.analyst import generate_report

    _timestamp("Step 5/6 — Generating report via Gemini API…")
    report = generate_report(enriched, summary)
    _timestamp(f"Report generated ({len(report)} chars).")

    # ── 7. Send email ────────────────────────────────────────────
    from src.emailer import send_report

    _timestamp("Step 6/6 — Sending HTML email…")
    send_report(report, summary)

    recipient = os.environ.get("RECIPIENT_EMAIL", "(unknown)")
    _timestamp(f"Done. Report sent to {recipient}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", tb)

        # Try to send a failure notification so you know it broke
        try:
            from src.emailer import send_failure_notification
            send_failure_notification(tb)
        except Exception as mail_err:
            logger.error("Could not send failure notification: %s", mail_err)

        sys.exit(1)
