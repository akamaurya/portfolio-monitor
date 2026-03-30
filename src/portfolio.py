"""
Fetch and clean equity holdings, mutual fund holdings, and positions from Kite.
"""

import logging
from src.auth import KiteWeb

logger = logging.getLogger(__name__)


def get_holdings(kite: KiteWeb) -> dict:
    """
    Return cleaned holdings, MF holdings, and positions from Kite.

    Returns
    -------
    dict  {"holdings": [...], "mf_holdings": [...], "positions": [...]}
    """
    # ── Equity Holdings ──────────────────────────────────────────
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
            "type": "equity",
        })

    logger.info("Fetched %d equity holdings.", len(holdings))

    # ── Mutual Fund (Coin) Holdings ──────────────────────────────
    mf_holdings = []
    try:
        raw_mf = kite.mf_holdings()
        for mf in raw_mf:
            if mf.get("quantity", 0) <= 0:
                continue

            invested = mf.get("average_price", 0) * mf.get("quantity", 0)
            current = mf.get("last_price", 0) * mf.get("quantity", 0)
            pnl_abs = current - invested

            mf_holdings.append({
                "symbol": mf.get("tradingsymbol", mf.get("fund", "Unknown")),
                "fund_name": mf.get("fund", mf.get("tradingsymbol", "Unknown")),
                "folio": mf.get("folio"),
                "quantity": mf.get("quantity", 0),
                "avg_cost": mf.get("average_price", 0),
                "last_price": mf.get("last_price", 0),
                "invested": round(invested, 2),
                "current_value": round(current, 2),
                "pnl": round(pnl_abs, 2),
                "pnl_pct": round(pnl_abs / invested * 100, 2) if invested else 0,
                "type": "mutual_fund",
            })

        logger.info("Fetched %d mutual fund holdings.", len(mf_holdings))

    except Exception as exc:
        logger.warning("Could not fetch MF holdings (may not have any): %s", exc)

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

    return {"holdings": holdings, "mf_holdings": mf_holdings, "positions": positions}
