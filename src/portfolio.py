"""
Fetch and clean holdings + positions from Kite.
"""

import logging
from src.auth import KiteWeb

logger = logging.getLogger(__name__)


def get_holdings(kite: KiteWeb) -> dict:
    """
    Return cleaned holdings and positions from Kite.

    Returns
    -------
    dict  {"holdings": [...], "positions": [...]}
    """
    # ── Holdings ─────────────────────────────────────────────────
    raw_holdings = kite.holdings()
    holdings = []

    for h in raw_holdings:
        qty = h.get("quantity", 0) + h.get("t1_quantity", 0)
        if qty <= 0:
            continue

        holdings.append({
            "symbol": h["tradingsymbol"],
            "exchange": h["exchange"],
            "quantity": h["quantity"],
            "t1_quantity": h.get("t1_quantity", 0),
            "avg_cost": h["average_price"],
            "last_kite_price": h["last_price"],
            "isin": h.get("isin"),
            "pnl": h.get("pnl"),
        })

    logger.info("Fetched %d holdings (non-zero quantity).", len(holdings))

    # ── Positions (day + net) ────────────────────────────────────
    raw_positions = kite.positions()
    positions = []

    for bucket in ("day", "net"):
        for p in raw_positions.get(bucket, []):
            if p.get("quantity", 0) == 0:
                continue
            positions.append({
                "bucket": bucket,
                "symbol": p["tradingsymbol"],
                "exchange": p["exchange"],
                "quantity": p["quantity"],
                "avg_price": p.get("average_price"),
                "last_price": p.get("last_price"),
                "pnl": p.get("pnl"),
                "product": p.get("product"),
            })

    logger.info("Fetched %d open positions.", len(positions))

    return {"holdings": holdings, "positions": positions}
