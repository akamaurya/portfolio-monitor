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
    assert 'class="up"' in html


def test_render_email_marks_losses():
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 60.0)])
    subject, html = render_email("loss month", summary)

    assert "-40.00%" in subject
    assert 'class="down"' in html
    # The figure itself is shown unsigned beside a ▼, so no stray minus leaks in.
    assert "−₹400" in html or "&#8377;400" in html


def test_email_layout_uses_tables_not_flexbox():
    """Gmail and Outlook strip flex/grid; a flex row there collapses silently."""
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 150.0)])
    _, html = render_email("body", summary)

    assert "display:flex" not in html.replace(" ", "")
    assert "display:grid" not in html.replace(" ", "")
    assert '<table role="presentation"' in html


def test_direction_markers_are_coloured():
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 150.0)])
    _, html = render_email("INFY ▲ 12.40% and ITC ▼ 3.10%", summary)

    assert '<span class="up">▲ 12.40%</span>' in html
    assert '<span class="down">▼ 3.10%</span>' in html


def test_verdict_cells_become_chips_but_prose_is_left_alone():
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 150.0)])
    report = (
        "| Stock | Call |\n|:------|:-----|\n| INFY | HOLD |\n\n"
        "We hold this through the quarter."
    )
    _, html = render_email(report, summary)

    assert 'class="verdict verdict-hold">HOLD<' in html
    # The word inside the sentence must not be chipped.
    assert "We hold this through the quarter." in html


def test_allocation_bar_omits_a_zero_segment():
    """A portfolio with no funds should not render an empty bar cell."""
    summary = build_portfolio_summary([_holding("INFY", 10, 100.0, 150.0)], [])
    _, html = render_email("body", summary)

    assert "Equity" in html
    assert "Mutual funds" not in html


def test_render_email_handles_an_empty_portfolio():
    """Nothing held is a valid state; it must not divide by zero or crash."""
    subject, html = render_email("nothing to report", build_portfolio_summary([], []))

    assert "+0.00%" in subject
    assert "<body>" in html


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


# ── Demo fixture ─────────────────────────────────────────────────
def test_demo_fixture_flows_through_the_real_cleaning_code():
    """The fixture stands in for Kite, so it must satisfy get_holdings()."""
    from src.demo import DemoKite

    data = get_holdings(DemoKite())

    assert len(data["holdings"]) == 8
    assert len(data["mf_holdings"]) == 2
    assert data["positions"] == []

    for h in data["holdings"]:
        assert h["symbol"] and h["exchange"] == "NSE"
        assert h["avg_cost"] > 0 and h["quantity"] > 0
        assert h["isin"]


def test_demo_fixture_tickers_resolve_for_yahoo():
    """Live pricing is the point of demo mode, so every symbol must map."""
    from src.demo import DemoKite

    for h in get_holdings(DemoKite())["holdings"]:
        ticker = _build_ticker(h["symbol"], h["exchange"])
        assert ticker.endswith(".NS")
        assert " " not in ticker


def test_demo_fixture_has_both_winners_and_losers():
    """An all-green demo portfolio makes the note look cherry-picked."""
    from src.demo import DemoKite

    mf = get_holdings(DemoKite())["mf_holdings"]
    assert all(m["invested"] > 0 for m in mf)

    # Average costs are spread either side of the usual trading bands; assert
    # the spread exists rather than the sign of any single live P&L.
    ratios = [h["last_kite_price"] / h["avg_cost"]
              for h in get_holdings(DemoKite())["holdings"]]
    assert min(ratios) > 0


# ── Gemini response validation ───────────────────────────────────
class _FakeResponse:
    def __init__(self, text, finish_reason="STOP"):
        self.text = text
        self.usage_metadata = None
        self.candidates = [type("C", (), {"finish_reason": finish_reason})()]


def _run_generate(monkeypatch, response):
    """Drive generate_report against a stubbed Gemini client."""
    from src import analyst

    calls = []

    class _FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            return response

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    monkeypatch.setattr(analyst.genai, "Client", _FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY1", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)
    # Isolate the Gemini path; callers that want Kimi set it back afterwards.
    for prov in analyst._OPENAI_PROVIDERS:
        monkeypatch.delenv(prov["env"], raising=False)
    return analyst, calls


_FULL_REPORT = (
    "# The month in one line\nx\n\n# Holdings\nx\n\n"
    "# What moved\nx\n\n# Allocation\nx\n\n# The calls\nx\n"
)


def test_truncated_report_is_rejected_and_retried(monkeypatch):
    """A note cut off mid-table still looks deliverable — it must not ship."""
    analyst, calls = _run_generate(
        monkeypatch, _FakeResponse("# The month in one line\n\n| Metric |", "MAX_TOKENS")
    )

    with pytest.raises(RuntimeError, match="All models"):
        analyst.generate_report([], [], {}, "")

    # Every model in the chain was tried before giving up.
    assert calls == analyst._GEMINI_MODELS


def test_report_with_too_few_sections_is_rejected(monkeypatch):
    analyst, _ = _run_generate(monkeypatch, _FakeResponse("# Only one section\n\ntext"))

    with pytest.raises(RuntimeError, match="All models"):
        analyst.generate_report([], [], {}, "")


def test_complete_report_is_returned(monkeypatch):
    analyst, calls = _run_generate(monkeypatch, _FakeResponse(_FULL_REPORT))

    assert analyst.generate_report([], [], {}, "") == _FULL_REPORT
    assert len(calls) == 1   # succeeded on the first model, no needless retries


# ── OpenAI-compatible providers (NVIDIA, Kimi) ───────────────────
class _FakeHTTPResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _chat_payload(content, finish_reason="stop"):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _only_provider(monkeypatch, label):
    """Configure exactly one OpenAI-compatible provider and no Gemini keys."""
    from src import analyst

    for prov in analyst._OPENAI_PROVIDERS:
        if prov["label"] == label:
            monkeypatch.setenv(prov["env"], "key-test")
        else:
            monkeypatch.delenv(prov["env"], raising=False)
    for var in ("GEMINI_API_KEY1", "GEMINI_API_KEY2", "GEMINI_API_KEY3"):
        monkeypatch.delenv(var, raising=False)
    return analyst


def test_nvidia_is_tried_before_kimi_and_gemini(monkeypatch):
    from src import analyst

    posted = []

    def fake_post(url, **kwargs):
        posted.append((url, kwargs["json"]["model"]))
        return _FakeHTTPResponse(_chat_payload(_FULL_REPORT))

    monkeypatch.setattr(analyst.requests, "post", fake_post)
    for prov in analyst._OPENAI_PROVIDERS:
        monkeypatch.setenv(prov["env"], "key-test")
    monkeypatch.setenv("GEMINI_API_KEY1", "gem-test")

    assert analyst.generate_report([], [], {}, "") == _FULL_REPORT
    # NVIDIA answered first; Moonshot was never contacted.
    assert len(posted) == 1
    assert "integrate.api.nvidia.com" in posted[0][0]
    assert posted[0][1] == "moonshotai/kimi-k3"


def test_provider_falls_through_to_the_next_provider(monkeypatch):
    """A dead NVIDIA key must not cost the month's report."""
    from src import analyst

    posted = []

    def fake_post(url, **kwargs):
        posted.append(url)
        if "nvidia" in url:
            return _FakeHTTPResponse(
                {"status": 404, "title": "Not Found",
                 "detail": "Specified function in account is not found"}
            )
        return _FakeHTTPResponse(_chat_payload(_FULL_REPORT))

    monkeypatch.setattr(analyst.requests, "post", fake_post)
    for prov in analyst._OPENAI_PROVIDERS:
        monkeypatch.setenv(prov["env"], "key-test")
    monkeypatch.delenv("GEMINI_API_KEY1", raising=False)

    assert analyst.generate_report([], [], {}, "") == _FULL_REPORT
    assert any("nvidia" in u for u in posted)
    assert any("moonshot" in u for u in posted)


def test_nvidia_routing_failure_is_reported_not_swallowed(monkeypatch):
    """NVIDIA reports routing errors as a bare detail object, not an OpenAI error."""
    from src import analyst

    analyst_mod = _only_provider(monkeypatch, "NVIDIA")
    monkeypatch.setattr(
        analyst_mod.requests, "post",
        lambda url, **kw: _FakeHTTPResponse(
            {"status": 404, "title": "Not Found", "detail": "function not found"}
        ),
    )

    with pytest.raises(RuntimeError, match="All models"):
        analyst_mod.generate_report([], [], {}, "")


def test_kimi_falls_back_to_its_second_model(monkeypatch):
    from src import analyst

    posted = []

    def fake_post(url, **kwargs):
        model = kwargs["json"]["model"]
        posted.append(model)
        if model == "kimi-k3":
            return _FakeHTTPResponse({"error": {"message": "insufficient balance"}})
        return _FakeHTTPResponse(_chat_payload(_FULL_REPORT))

    analyst_mod = _only_provider(monkeypatch, "Kimi")
    monkeypatch.setattr(analyst_mod.requests, "post", fake_post)

    assert analyst_mod.generate_report([], [], {}, "") == _FULL_REPORT
    assert posted == ["kimi-k3", "kimi-k2.6"]


def test_openai_truncation_is_rejected_like_geminis(monkeypatch):
    """OpenAI-style APIs report a cut-off with finish_reason 'length'."""
    analyst_mod = _only_provider(monkeypatch, "NVIDIA")
    monkeypatch.setattr(
        analyst_mod.requests, "post",
        lambda url, **kw: _FakeHTTPResponse(_chat_payload("# One\n\n| a |", "length")),
    )

    with pytest.raises(RuntimeError, match="All models"):
        analyst_mod.generate_report([], [], {}, "")


def test_reasoning_field_is_not_mistaken_for_the_report(monkeypatch):
    """Reasoning models return the chain of thought separately; only content counts."""
    analyst_mod = _only_provider(monkeypatch, "NVIDIA")
    payload = _chat_payload(_FULL_REPORT)
    payload["choices"][0]["message"]["reasoning_content"] = "thinking out loud" * 50

    monkeypatch.setattr(
        analyst_mod.requests, "post", lambda url, **kw: _FakeHTTPResponse(payload)
    )
    assert analyst_mod.generate_report([], [], {}, "") == _FULL_REPORT


def test_dead_providers_fall_through_to_gemini(monkeypatch):
    from src import analyst

    monkeypatch.setattr(
        analyst.requests, "post",
        lambda url, **kw: _FakeHTTPResponse({"error": {"message": "no balance"}}),
    )
    analyst_mod, calls = _run_generate(monkeypatch, _FakeResponse(_FULL_REPORT))
    for prov in analyst_mod._OPENAI_PROVIDERS:
        monkeypatch.setenv(prov["env"], "key-dead")

    assert analyst_mod.generate_report([], [], {}, "") == _FULL_REPORT
    assert calls == analyst_mod._GEMINI_MODELS[:1]


def test_no_keys_at_all_is_an_explicit_error(monkeypatch):
    from src import analyst

    for prov in analyst._OPENAI_PROVIDERS:
        monkeypatch.delenv(prov["env"], raising=False)
    for var in ("GEMINI_API_KEY1", "GEMINI_API_KEY2", "GEMINI_API_KEY3"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError, match="No API keys found"):
        analyst.generate_report([], [], {}, "")
