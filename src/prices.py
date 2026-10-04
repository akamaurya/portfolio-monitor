"""
Enrich holdings with live price data from Yahoo Finance.
"""

import time
import logging
from datetime import datetime, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

# ── Special‑case Yahoo Finance ticker mappings ──────────────────
_TICKER_OVERRIDES: dict[str, str] = {
    "GOLDBEES": "GOLDBEES.NS",
    "SILVERBEES": "SILVERBEES.NS",
    "MON100": "MON100.NS",
    "NIFTYBEES": "NIFTYBEES.NS",
    "LIQUIDBEES": "LIQUIDBEES.NS",
    "BANKBEES": "BANKBEES.NS",
    "JUNIORBEES": "JUNIORBEES.NS",
    "ITBEES": "ITBEES.NS",
    "CPSEETF": "CPSEETF.NS",
    "SETFNIF50": "SETFNIF50.NS",
    "MOM100": "MOM100.NS",
}


def _build_ticker(symbol: str, exchange: str) -> str:
    """Convert a Kite symbol + exchange into a Yahoo Finance ticker."""
    # removesuffix, not rstrip: rstrip("-E") strips *characters*, which would
    # turn HDFCLIFE into HDFCLIF and PERSISTENT into PERSISTEN.
    clean = symbol.removesuffix("-E").removesuffix("-T")   # settlement suffixes

    if clean in _TICKER_OVERRIDES:
        return _TICKER_OVERRIDES[clean]

    suffix = ".NS" if exchange == "NSE" else ".BO"
    return f"{clean}{suffix}"


def _safe_get(info: dict, *keys, default=None):
    """Return the first non-None value from info for the given keys."""
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return default


def _calc_period_return(history, months: int) -> float | None:
    """Return percentage return over the last `months` months from a price history DataFrame."""
    if history is None or history.empty:
        return None
    try:
        end_price = history["Close"].iloc[-1]
        cutoff = datetime.now() - timedelta(days=months * 30)
        older = history.loc[history.index <= cutoff.strftime("%Y-%m-%d")]
        start_price = older["Close"].iloc[-1] if not older.empty else history["Close"].iloc[0]
        if start_price == 0:
            return None
        return round((end_price - start_price) / start_price * 100, 2)
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════

def enrich_with_prices(holdings: list[dict]) -> list[dict]:
    """
    Add live Yahoo Finance data to each holding dict.

    Fields added: current_price, currency, sector, industry, market_cap,
    pe_ratio, pb_ratio, dividend_yield, 52w_high, 52w_low,
    1mo_return_pct, 3mo_return_pct, current_value, unrealized_pnl_abs,
    unrealized_pnl_pct, distance_from_52w_high_pct.
    """
    enriched = []

    # Log positions, not symbols: Actions logs on this public repo are public.
    for i, h in enumerate(holdings, 1):
        ticker_str = _build_ticker(h["symbol"], h["exchange"])
        logger.info("Fetching yfinance data for holding %d/%d", i, len(holdings))

        try:
            ticker = yf.Ticker(ticker_str)
            info = ticker.info or {}
            hist = ticker.history(period="3mo")

            current_price = _safe_get(
                info, "currentPrice", "regularMarketPrice", "previousClose"
            )

            # Fall back to Kite's last price if Yahoo returns nothing useful
            if current_price is None:
                current_price = h.get("last_kite_price")
                logger.warning("Holding %d: Yahoo returned no price — falling back to Kite last_price.", i)

            high_52w = _safe_get(info, "fiftyTwoWeekHigh")
            low_52w = _safe_get(info, "fiftyTwoWeekLow")

            qty = h["quantity"] + h.get("t1_quantity", 0)
            avg_cost = h["avg_cost"]

            current_value = round(current_price * qty, 2) if current_price else None
            pnl_abs = round((current_price - avg_cost) * qty, 2) if current_price else None
            pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2) if (current_price and avg_cost) else None
            dist_high = (
                round((current_price - high_52w) / high_52w * 100, 2)
                if (current_price and high_52w) else None
            )

            h.update({
                "yahoo_ticker": ticker_str,
                "current_price": current_price,
                "currency": _safe_get(info, "currency"),
                "sector": _safe_get(info, "sector"),
                "industry": _safe_get(info, "industry"),
                "market_cap": _safe_get(info, "marketCap"),
                "pe_ratio": _safe_get(info, "trailingPE"),
                "pb_ratio": _safe_get(info, "priceToBook"),
                "dividend_yield": _safe_get(info, "dividendYield"),
                "52w_high": high_52w,
                "52w_low": low_52w,
                "1mo_return_pct": _calc_period_return(hist, 1),
                "3mo_return_pct": _calc_period_return(hist, 3),
                "current_value": current_value,
                "unrealized_pnl_abs": pnl_abs,
                "unrealized_pnl_pct": pnl_pct,
                "distance_from_52w_high_pct": dist_high,
            })

        except Exception as exc:
            logger.warning("Failed to fetch data for holding %d: %s", i, type(exc).__name__)
            # Attach None placeholders so downstream code doesn't crash
            h.update({
                "yahoo_ticker": ticker_str,
                "current_price": h.get("last_kite_price"),
                "currency": None, "sector": None, "industry": None,
                "market_cap": None, "pe_ratio": None, "pb_ratio": None,
                "dividend_yield": None, "52w_high": None, "52w_low": None,
                "1mo_return_pct": None, "3mo_return_pct": None,
                "current_value": None, "unrealized_pnl_abs": None,
                "unrealized_pnl_pct": None, "distance_from_52w_high_pct": None,
            })

        enriched.append(h)
        time.sleep(0.5)  # avoid Yahoo rate‑limiting

    return enriched


def build_portfolio_summary(
    enriched_holdings: list[dict],
    mf_holdings: list[dict] | None = None,
) -> dict:
    """
    Aggregate portfolio‑level stats from enriched equity + MF holdings.
    """
    total_invested = 0.0
    total_current = 0.0
    sector_map: dict[str, float] = {}
    scored: list[dict] = []

    # ── Equity holdings ──────────────────────────────────────────
    for h in enriched_holdings:
        qty = h["quantity"] + h.get("t1_quantity", 0)
        invested = h["avg_cost"] * qty
        total_invested += invested

        cv = h.get("current_value")
        if cv is not None:
            total_current += cv

        sector = h.get("sector") or "Unknown"
        sector_map[sector] = sector_map.get(sector, 0) + (cv or 0)

        if h.get("unrealized_pnl_pct") is not None:
            scored.append(h)

    scored.sort(key=lambda x: x["unrealized_pnl_pct"], reverse=True)

    # ── MF holdings ──────────────────────────────────────────────
    mf_total_invested = 0.0
    mf_total_current = 0.0
    mf_summary_list = []

    for mf in (mf_holdings or []):
        mf_inv = mf.get("invested", 0)
        mf_cur = mf.get("current_value", 0)
        mf_total_invested += mf_inv
        mf_total_current += mf_cur

        sector_map["Mutual Funds"] = sector_map.get("Mutual Funds", 0) + mf_cur

        mf_summary_list.append({
            "fund_name": mf.get("fund_name", mf.get("symbol")),
            "invested": mf_inv,
            "current_value": mf_cur,
            "pnl": mf.get("pnl", 0),
            "pnl_pct": mf.get("pnl_pct", 0),
        })

    total_invested += mf_total_invested
    total_current += mf_total_current

    total_pnl_abs = round(total_current - total_invested, 2)
    total_pnl_pct = round(total_pnl_abs / total_invested * 100, 2) if total_invested else 0

    # Equity-only P&L
    eq_invested = total_invested - mf_total_invested
    eq_current = total_current - mf_total_current
    eq_pnl_abs = round(eq_current - eq_invested, 2)
    eq_pnl_pct = round(eq_pnl_abs / eq_invested * 100, 2) if eq_invested else 0

    return {
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "total_unrealized_pnl_abs": total_pnl_abs,
        "total_unrealized_pnl_pct": total_pnl_pct,
        "equity_invested": round(eq_invested, 2),
        "equity_current": round(eq_current, 2),
        "equity_pnl_abs": eq_pnl_abs,
        "equity_pnl_pct": eq_pnl_pct,
        "mf_invested": round(mf_total_invested, 2),
        "mf_current": round(mf_total_current, 2),
        "mf_pnl_abs": round(mf_total_current - mf_total_invested, 2),
        "mf_pnl_pct": round((mf_total_current - mf_total_invested) / mf_total_invested * 100, 2) if mf_total_invested else 0,
        "mf_funds": mf_summary_list,
        "sector_breakdown": {k: round(v, 2) for k, v in sorted(sector_map.items(), key=lambda x: -x[1])},
        "top_3_winners": [
            {"symbol": s["symbol"], "pnl_pct": s["unrealized_pnl_pct"]}
            for s in scored[:3]
        ],
        # Worst first, and never repeating a holding already listed as a winner
        # (which is what a naive scored[-3:] does with fewer than 6 holdings).
        "top_3_laggards": [
            {"symbol": s["symbol"], "pnl_pct": s["unrealized_pnl_pct"]}
            for s in reversed(scored[max(len(scored) - 3, 3):])
        ],
    }

