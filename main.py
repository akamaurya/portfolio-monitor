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

from src.analyst import generate_report
from src.auth import authenticate
from src.emailer import send_failure_notification, send_report
from src.portfolio import get_holdings
from src.prices import build_portfolio_summary, enrich_with_prices
from src.research import gather_research_context

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("portfolio-monitor")

TOTAL_STEPS = 7


def _step(number: int, msg: str) -> None:
    logger.info("Step %d/%d — %s", number, TOTAL_STEPS, msg)


def main() -> None:
    # ── Load .env (skip in CI where secrets are injected) ─────────
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
            logger.info("Loaded .env file.")
        except ImportError:
            logger.info("python-dotenv not installed — assuming env vars are already set.")

    # ── 1. Authenticate with Kite ────────────────────────────────
    _step(1, "Authenticating with Kite…")
    kite = authenticate()
    logger.info("Authentication successful.")

    # ── 2. Fetch holdings & positions ────────────────────────────
    _step(2, "Fetching holdings and positions…")
    portfolio_data = get_holdings(kite)
    holdings = portfolio_data["holdings"]
    mf_holdings = portfolio_data["mf_holdings"]
    logger.info(
        "Fetched %d equity holdings, %d MF holdings, %d open positions.",
        len(holdings), len(mf_holdings), len(portfolio_data["positions"]),
    )

    if not holdings and not mf_holdings:
        logger.info("No holdings found — nothing to report. Exiting.")
        return

    # ── 3. Enrich equity holdings with Yahoo Finance prices ──────
    _step(3, "Enriching equity holdings with live prices…")
    enriched = enrich_with_prices(holdings)
    logger.info("Price enrichment complete.")

    # ── 4. Build portfolio summary ───────────────────────────────
    _step(4, "Building portfolio summary…")
    summary = build_portfolio_summary(enriched, mf_holdings)
    logger.info(
        "Summary: invested ₹%s, current ₹%s, P&L %+.2f%%",
        f"{summary['total_invested']:,.2f}",
        f"{summary['total_current_value']:,.2f}",
        summary["total_unrealized_pnl_pct"],
    )

    # ── 5. Gather market research context ────────────────────────
    _step(5, "Gathering market research context…")
    research_context = gather_research_context()
    logger.info("Research context gathered (%d chars).", len(research_context))

    # ── 6. Generate Gemini report ────────────────────────────────
    _step(6, "Generating report via Gemini API…")
    report = generate_report(enriched, mf_holdings, summary, research_context)
    logger.info("Report generated (%d chars).", len(report))

    # ── 7. Send email ────────────────────────────────────────────
    _step(7, "Sending HTML email…")
    send_report(report, summary)
    logger.info("Done. Report sent to %s", os.environ.get("RECIPIENT_EMAIL", "(unknown)"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        logger.error("Pipeline failed:\n%s", tb)

        # Best-effort alert so a broken run doesn't go unnoticed
        # (send_failure_notification never raises).
        send_failure_notification(tb)

        sys.exit(1)
