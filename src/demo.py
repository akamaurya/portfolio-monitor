"""
A hypothetical portfolio for demos and screen recordings.

`DemoKite` stands in for an authenticated `KiteWeb` client and returns data in
the raw shape Kite's API uses. Substituting it swaps out the login and the
holdings fetch and nothing else: `get_holdings()` still cleans the payload,
Yahoo Finance is still queried for live prices, the research scrape still runs
and Gemini still writes the report. Only the holdings are invented.

The symbols are real and liquid so the live price lookups resolve, and the
average costs are spread either side of their usual trading bands so the
report has genuine winners and losers to talk about rather than a wall of
green.
"""

import logging

logger = logging.getLogger(__name__)

# tradingsymbol, exchange, qty, avg cost, ISIN
#
# Average costs are set as a ratio of the live price (calibrated August 2026)
# so the note has a believable spread — roughly -12% to +32%, five up and
# three down — instead of one position dominating it. Setting them against
# current prices also keeps corporate actions out of the picture: HDFC Bank's
# 1:1 bonus and the ITC hotels demerger both reset the quoted price, and a
# cost carried over from before either one shows as a ~50% crash that never
# happened. If the demo ever starts showing an implausible move, recalibrate
# here against a fresh `python main.py --demo --preview` run.
_EQUITY = [
    ("NIFTYBEES",  "NSE",  48,  243.00, "INF204KB14I2"),   # ~ +14%
    ("LT",         "NSE",   3, 3277.00, "INE018A01030"),   # ~ +24%
    ("GOLDBEES",   "NSE",  95,  100.40, "INF204KB17I5"),   # ~ +32%
    ("TITAN",      "NSE",   2, 4320.00, "INE280A01028"),   # ~ +18%
    ("HDFCBANK",   "NSE",  13,  668.00, "INE040A01034"),   # ~  +9%
    ("SUNPHARMA",  "NSE",   5, 2035.00, "INE044A01036"),   # ~  -6%
    ("ITC",        "NSE",  34,  297.40, "INE154A01025"),   # ~  -9%
    ("INFY",       "NSE",   8, 1275.00, "INE009A01021"),   # ~ -12%
]

# tradingsymbol, fund name, folio, units, avg NAV, current NAV
_MUTUAL_FUNDS = [
    ("INF879O01027", "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
     "10294412/47", 210.442, 61.50, 82.40),
    ("INF109K012B0", "ICICI Prudential Liquid Fund - Direct Plan - Growth",
     "18820147/22", 24.001, 352.10, 381.20),
]


class DemoKite:
    """Mirrors the `KiteWeb` surface that `get_holdings()` depends on."""

    user_id = "DEMO01"

    def holdings(self) -> list:
        return [
            {
                "tradingsymbol": symbol,
                "exchange": exchange,
                "quantity": qty,
                "t1_quantity": 0,
                "average_price": avg_cost,
                # Kite's own last price; the pipeline overwrites this with the
                # live Yahoo quote and only falls back to it if Yahoo fails.
                "last_price": round(avg_cost * 1.1, 2),
                "isin": isin,
                "pnl": 0.0,
                "product": "CNC",
            }
            for symbol, exchange, qty, avg_cost, isin in _EQUITY
        ]

    def mf_holdings(self) -> list:
        return [
            {
                "tradingsymbol": symbol,
                "fund": fund,
                "folio": folio,
                "quantity": units,
                "average_price": avg_nav,
                "last_price": last_nav,
            }
            for symbol, fund, folio, units, avg_nav, last_nav in _MUTUAL_FUNDS
        ]

    def positions(self) -> dict:
        # A long-term portfolio with nothing open intraday.
        return {"day": [], "net": []}


def demo_kite() -> DemoKite:
    """Return the stand-in client, logging loudly so a demo run is never
    mistaken for a real one."""
    logger.warning(
        "DEMO MODE — using a hypothetical portfolio (%d equity holdings, "
        "%d mutual funds). No Kite login, no real holdings.",
        len(_EQUITY), len(_MUTUAL_FUNDS),
    )
    return DemoKite()
