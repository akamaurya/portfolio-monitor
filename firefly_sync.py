#!/usr/bin/env python3
"""
Weekly Zerodha → Firefly sync.

Totals the Zerodha account (equity holdings + Coin MFs + cash in Kite) and posts
the change since the last sync to the Firefly asset account "Zerodha", as a
deposit from "Market gains" or a withdrawal to "Market losses".

Usage:
    python firefly_sync.py            # live
    python firefly_sync.py --dry-run  # compute, write nothing

This repo is public, so CI logs are too: amounts are only ever printed locally.
Re-running is safe: it posts the gap to the true value, which is ~0 the second time.
"""

import datetime as dt
import logging
import os
import sys

import requests

from src.auth import authenticate
from src.portfolio import get_holdings

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("firefly-sync")

ACCOUNT = "Zerodha"
MAX_SWING = 0.20  # a week's move above this is a missed transfer, not the market
IN_CI = bool(os.environ.get("GITHUB_ACTIONS"))


def zerodha_total(data: dict, cash: float) -> float:
    equity = sum((h["quantity"] + h["t1_quantity"]) * h["last_kite_price"] for h in data["holdings"])
    mf = sum(m["current_value"] for m in data["mf_holdings"])
    return round(equity + mf + cash, 2)


def plan(total: float, balance: float) -> float:
    """Amount to post (+gain / -loss). Raises when the gap is too big to be market movement."""
    delta = round(total - balance, 2)
    base = max(abs(total), abs(balance))
    if base and abs(delta) > MAX_SWING * base:
        raise RuntimeError(
            f"Kite and Firefly differ by more than {MAX_SWING:.0%}. Likely a transfer to or from "
            f"Zerodha that isn't booked as a transfer in Firefly, or Kite returned empty data. Nothing posted."
        )
    return delta if abs(delta) >= 1 else 0.0


def transaction(delta: float, account_id: str, day: str) -> dict:
    gain = delta > 0
    split = {
        "type": "deposit" if gain else "withdrawal",
        "date": day,
        "amount": f"{abs(delta):.2f}",
        "description": f"Kite weekly sync: market {'gain' if gain else 'loss'}",
        # ponytail: plain deposit/withdrawal, so losses show in expense charts under this
        # category. Switch to Firefly's reconciliation type if that gets noisy.
        "category_name": "Market P&L",
        "tags": ["kite-sync"],
    }
    if gain:
        split |= {"source_name": "Market gains", "destination_id": account_id}
    else:
        split |= {"source_id": account_id, "destination_name": "Market losses"}
    return {"apply_rules": False, "transactions": [split]}


class Firefly:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/") + "/api/v1"
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "portfolio-monitor/1",  # Cloudflare blocks default library agents
        })

    def account(self, name: str) -> tuple[str, float]:
        r = self.s.get(f"{self.base}/accounts", params={"type": "asset", "limit": 100}, timeout=30)
        r.raise_for_status()
        for a in r.json()["data"]:
            if a["attributes"]["name"] == name:
                return a["id"], float(a["attributes"]["current_balance"])
        raise RuntimeError(f'Firefly asset account "{name}" not found. Create it first.')

    def post(self, body: dict) -> None:
        self.s.post(f"{self.base}/transactions", json=body, timeout=30).raise_for_status()


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not IN_CI:
        from dotenv import load_dotenv
        load_dotenv()

    kite = authenticate()
    total = zerodha_total(get_holdings(kite), kite.margins()["equity"]["available"]["live_balance"])
    ff = Firefly(os.environ["FIREFLY_URL"], os.environ["FIREFLY_TOKEN"])
    account_id, balance = ff.account(ACCOUNT)
    delta = plan(total, balance)

    if not IN_CI:
        logger.info("Kite ₹%.2f, Firefly ₹%.2f, change ₹%.2f", total, balance, delta)
    if not delta:
        logger.info("Already in sync, nothing to post.")
    elif dry:
        logger.info("Dry run, nothing posted.")
    else:
        ff.post(transaction(delta, account_id, dt.date.today().isoformat()))
        logger.info("Posted market %s to Firefly.", "gain" if delta > 0 else "loss")


if __name__ == "__main__":
    main()
