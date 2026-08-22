"""
Unit tests for the pure logic in the pipeline — ticker mapping, portfolio
aggregation, currency formatting, search-URL resolution and holdings cleaning.

Everything here runs offline: no Kite, Yahoo, Gemini or SMTP calls.
"""

import pytest

from src.emailer import _format_inr, render_email
from src.portfolio import get_holdings
from src.prices import _build_ticker, build_portfolio_summary
from src.research import _resolve_ddg_url


# ── Ticker mapping ───────────────────────────────────────────────
@pytest.mark.parametrize("symbol, exchange, expected", [
    ("INFY", "NSE", "INFY.NS"),
    ("INFY", "BSE", "INFY.BO"),
    ("GOLDBEES", "NSE", "GOLDBEES.NS"),      # override map
    ("HDFCLIFE", "NSE", "HDFCLIFE.NS"),      # must not be trimmed to HDFCLIF
    ("PERSISTENT", "NSE", "PERSISTENT.NS"),  # must not be trimmed to PERSISTEN
    ("IDEA-E", "NSE", "IDEA.NS"),            # settlement suffix stripped
])
def test_build_ticker(symbol, exchange, expected):
    assert _build_ticker(symbol, exchange) == expected


# ── Portfolio aggregation ────────────────────────────────────────
def _holding(symbol, qty, avg_cost, price, sector="IT", t1=0):
    return {
        "symbol": symbol,
        "quantity": qty,
        "t1_quantity": t1,
        "avg_cost": avg_cost,
        "sector": sector,
        "current_value": round(price * (qty + t1), 2),
        "unrealized_pnl_pct": round((price - avg_cost) / avg_cost * 100, 2),
    }


def test_summary_totals_include_mutual_funds():
    holdings = [_holding("INFY", 10, 100.0, 150.0)]
    mf = [{"fund_name": "Some Fund", "invested": 1000.0, "current_value": 1200.0,
           "pnl": 200.0, "pnl_pct": 20.0}]

    summary = build_portfolio_summary(holdings, mf)

    assert summary["equity_invested"] == 1000.0
    assert summary["equity_current"] == 1500.0
    assert summary["mf_invested"] == 1000.0
    assert summary["total_invested"] == 2000.0
    assert summary["total_current_value"] == 2700.0
    assert summary["total_unrealized_pnl_abs"] == 700.0
    assert summary["total_unrealized_pnl_pct"] == 35.0
    assert summary["sector_breakdown"]["Mutual Funds"] == 1200.0


def test_summary_counts_t1_quantity_as_invested():
    """Shares still in T+1 settlement are owned and must be valued."""
    summary = build_portfolio_summary([_holding("INFY", 0, 100.0, 150.0, t1=10)])
    assert summary["equity_invested"] == 1000.0
    assert summary["equity_current"] == 1500.0


def test_empty_portfolio_does_not_divide_by_zero():
    summary = build_portfolio_summary([], [])
    assert summary["total_invested"] == 0
    assert summary["total_unrealized_pnl_pct"] == 0
    assert summary["top_3_winners"] == []
    assert summary["top_3_laggards"] == []


def test_winners_and_laggards_never_overlap():
    holdings = [
        _holding("WIN1", 1, 100.0, 200.0),
        _holding("WIN2", 1, 100.0, 180.0),
        _holding("WIN3", 1, 100.0, 160.0),
        _holding("LOSS", 1, 100.0, 50.0),
    ]
    summary = build_portfolio_summary(holdings)

    winners = [w["symbol"] for w in summary["top_3_winners"]]
    laggards = [l["symbol"] for l in summary["top_3_laggards"]]

    assert winners == ["WIN1", "WIN2", "WIN3"]
    assert laggards == ["LOSS"]
    assert not set(winners) & set(laggards)


def test_laggards_are_ordered_worst_first():
    holdings = [_holding(f"S{i}", 1, 100.0, price) for i, price in
                enumerate([200.0, 180.0, 160.0, 90.0, 70.0, 50.0])]
    summary = build_portfolio_summary(holdings)

    assert [l["symbol"] for l in summary["top_3_laggards"]] == ["S5", "S4", "S3"]


def test_holdings_missing_price_do_not_break_totals():
    """A Yahoo failure leaves current_value None; invested must still count."""
    broken = _holding("INFY", 10, 100.0, 150.0)
    broken["current_value"] = None
    broken["unrealized_pnl_pct"] = None

    summary = build_portfolio_summary([broken])
    assert summary["total_invested"] == 1000.0
    assert summary["total_current_value"] == 0
    assert summary["top_3_winners"] == []


# ── Currency formatting (Indian grouping) ────────────────────────
@pytest.mark.parametrize("value, expected", [
    (None, "—"),
    (0, "0.00"),
    (999.5, "999.50"),
    (1000, "1,000"),
    (123456, "1,23,456"),
    (1234567, "12,34,567"),
    (12345678.9, "1,23,45,679"),
    (-123456, "-1,23,456"),
])
def test_format_inr(value, expected):
    assert _format_inr(value) == expected


# ── Email rendering ──────────────────────────────────────────────
def test_render_email_fills_template_and_subject():
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 150.0)])
    subject, html = render_email("# Heading\n\n| A | B |\n|---|---|\n| 1 | 2 |", summary)

    assert "+50.00%" in subject
    assert "1,500" in subject
    assert "<table>" in html          # markdown tables extension is enabled
    assert "<h1>Heading</h1>" in html
    assert "{" not in html.split("<body>")[1]   # no unfilled placeholders
    assert "positive" in html


def test_render_email_marks_losses_negative():
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 60.0)])
    subject, html = render_email("loss month", summary)

    assert "-40.00%" in subject
    assert 'card-value negative' in html


# ── DuckDuckGo redirect resolution ───────────────────────────────
def test_resolve_ddg_redirect_url():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fhdfcsec.com%2Freport.pdf&rut=abc"
    assert _resolve_ddg_url(href) == "https://hdfcsec.com/report.pdf"


def test_resolve_plain_url_is_unchanged():
    assert _resolve_ddg_url("https://example.com/a.pdf") == "https://example.com/a.pdf"


# ── Holdings cleaning ────────────────────────────────────────────
class _FakeKite:
    """Stands in for KiteWeb — same method surface, canned responses."""

    def holdings(self):
        return [
            {"tradingsymbol": "INFY", "exchange": "NSE", "quantity": 10,
             "t1_quantity": 0, "average_price": 1400.0, "last_price": 1500.0},
            {"tradingsymbol": "SOLD", "exchange": "NSE", "quantity": 0,
             "t1_quantity": 0, "average_price": 100.0, "last_price": 120.0},
            {"tradingsymbol": "NEWBUY", "exchange": "NSE", "quantity": 0,
             "t1_quantity": 5, "average_price": 200.0, "last_price": 210.0},
        ]

    def mf_holdings(self):
        return [{"tradingsymbol": "MF1", "fund": "Some Fund", "quantity": 100.0,
                 "average_price": 10.0, "last_price": 12.0}]

    def positions(self):
        return {
            "day": [{"tradingsymbol": "NIFTY", "exchange": "NFO", "quantity": 50}],
            "net": [{"tradingsymbol": "CLOSED", "exchange": "NFO", "quantity": 0}],
        }


def test_get_holdings_filters_and_shapes_data():
    data = get_holdings(_FakeKite())

    assert [h["symbol"] for h in data["holdings"]] == ["INFY", "NEWBUY"]
    assert data["mf_holdings"][0]["invested"] == 1000.0
    assert data["mf_holdings"][0]["pnl_pct"] == 20.0
    assert [p["symbol"] for p in data["positions"]] == ["NIFTY"]


def test_get_holdings_survives_accounts_without_mutual_funds():
    class NoMF(_FakeKite):
        def mf_holdings(self):
            raise RuntimeError("Kite API error: no MF account")

    data = get_holdings(NoMF())
    assert data["mf_holdings"] == []
    assert len(data["holdings"]) == 2
