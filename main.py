#!/usr/bin/env python3
"""
Portfolio Monitor — main entry point.

Usage:
    python main.py                  # live run: real holdings, real email
    python main.py --demo           # hypothetical portfolio, everything else live
    python main.py --demo --preview # …and write the email to disk instead of sending

Requires environment variables (see .env.example).
"""

import os
import sys
import logging
import pathlib
import traceback

from src.analyst import generate_report
from src.auth import authenticate
from src.emailer import render_email, send_failure_notification, send_report
from src.portfolio import get_holdings
from src.prices import build_portfolio_summary, enrich_with_prices
from src.research import gather_research_context

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# yfinance's own errors name the ticker ("$RCOM.NS: No data found"), which would
# publish holdings in the public Actions log.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger("portfolio-monitor")

TOTAL_STEPS = 7

PREVIEW_PATH = pathlib.Path("out/preview.html")


def _step(number: int, msg: str) -> None:
    logger.info("Step %d/%d — %s", number, TOTAL_STEPS, msg)


def _write_preview(report: str, summary: dict) -> None:
    """Render the email to a file so the template can be reviewed without
    sending anything."""
    _, html = render_email(report, summary)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.write_text(html, encoding="utf-8")
    logger.info("Preview written to %s (nothing sent).", PREVIEW_PATH.resolve())


def main() -> None:
    demo = "--demo" in sys.argv or os.environ.get("DEMO_MODE") == "1"
    preview = "--preview" in sys.argv

    # ── Load .env (skip in CI where secrets are injected) ─────────
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
            logger.info("Loaded .env file.")
        except ImportError:
            logger.info("python-dotenv not installed — assuming env vars are already set.")

    # ── 1. Authenticate with Kite ────────────────────────────────
    if demo:
        _step(1, "Authenticating with Kite… [DEMO — skipped]")
        from src.demo import demo_kite
        kite = demo_kite()
    else:
        _step(1, "Authenticating with Kite…")
        kite = authenticate()
        logger.info("Authentication successful.")

    # ── 2. Fetch holdings & positions ────────────────────────────
    _step(2, "Fetching holdings and positions…" + (" [DEMO fixture]" if demo else ""))
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
    logger.info("Summary built.")  # no amounts: Actions logs on this public repo are public

    # ── 5. Gather market research context ────────────────────────
    _step(5, "Gathering market research context…")
    research_context = gather_research_context()
    logger.info("Research context gathered (%d chars).", len(research_context))

    # ── 6. Generate the report ───────────────────────────────────
    _step(6, "Generating report…")
    report = generate_report(enriched, mf_holdings, summary, research_context)
    logger.info("Report generated (%d chars).", len(report))

    # ── 7. Send email ────────────────────────────────────────────
    if preview:
        _step(7, "Rendering HTML email… [PREVIEW — not sending]")
        _write_preview(report, summary)
        return

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
