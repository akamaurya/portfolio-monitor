"""
Render the portfolio report as an HTML email and send it via Gmail SMTP.

Design notes
------------
The layout is built from nested ``<table>`` elements rather than flexbox or
grid. Gmail, Outlook and most mobile clients strip modern layout CSS, so a
flex row silently collapses into stacked blocks — the reason the earlier
template left a dead gap beside its summary cards. Tables render identically
everywhere.

The visual language is a broker research note: a masthead with a double rule,
a serif for prose, a system sans for utility text, and a monospace reserved
for the headline figures — machine readout set against desk voice.
"""

import os
import re
import ssl
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import markdown

from src.clock import now_ist

logger = logging.getLogger(__name__)

# ── Type stacks ──────────────────────────────────────────────────
# Iowan Old Style ships with macOS/iOS and Palatino with Windows, so the
# serif keeps its humanist character on both before falling back to Georgia.
_SERIF = "'Iowan Old Style', 'Palatino Linotype', Palatino, 'Book Antiqua', Georgia, serif"
_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
_MONO = "'SF Mono', 'IBM Plex Mono', Menlo, Consolas, 'Liberation Mono', monospace"

# ── Palette ──────────────────────────────────────────────────────
# Cool paper rather than cream: this is a printed statement, not stationery.
_C = {
    "canvas": "#EDEEF0",
    "sheet": "#FFFFFF",
    "ink": "#16191E",
    "ink_2": "#4A525E",
    "ink_3": "#858D99",
    "rule": "#E2E5E9",
    "accent": "#17457A",
    "accent_soft": "#9FB6CE",
    "up": "#0B6E4F",
    "down": "#A32C22",
    "up_bg": "#E8F2ED",
    "down_bg": "#FBEBE9",
}

_CSS = f"""
  :root {{ color-scheme: light only; supported-color-schemes: light; }}

  body {{
    margin: 0;
    padding: 0;
    background: {_C['canvas']};
    color: {_C['ink']};
    font-family: {_SANS};
    font-size: 15px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    -webkit-text-size-adjust: 100%;
  }}
  table {{ border-collapse: collapse; }}
  .canvas {{ background: {_C['canvas']}; padding: 32px 16px; }}
  .sheet {{ background: {_C['sheet']}; width: 640px; max-width: 100%; }}

  /* ── Masthead ─────────────────────────────────────── */
  .masthead {{ padding: 28px 40px 10px; }}
  .desk {{
    font-size: 11px; font-weight: 700; letter-spacing: 1.4px;
    text-transform: uppercase; color: {_C['accent']};
  }}
  .dateline {{
    font-family: {_MONO};
    font-size: 11px; letter-spacing: 0.4px; color: {_C['ink_3']};
  }}
  /* The stacked thick/thin rule is the masthead device of a printed note. */
  .rule-double {{ padding: 0 40px; }}
  .rule-double div {{ border-top: 2px solid {_C['ink']}; }}
  .rule-double div + div {{ border-top: 1px solid {_C['rule']}; margin-top: 2px; }}

  .title-block {{ padding: 22px 40px 0; }}
  .doc-title {{
    margin: 0;
    font-family: {_SERIF};
    font-size: 30px; font-weight: 400; letter-spacing: -0.3px;
    line-height: 1.15; color: {_C['ink']};
  }}
  .doc-sub {{
    margin-top: 5px;
    font-size: 13px; color: {_C['ink_3']};
  }}

  /* ── Hero figure ──────────────────────────────────── */
  .eyebrow {{
    font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
    text-transform: uppercase; color: {_C['ink_3']};
  }}
  .hero {{ padding: 26px 40px 0; }}
  .hero-figure {{
    margin-top: 4px;
    font-family: {_SERIF};
    font-size: 46px; font-weight: 400; letter-spacing: -0.5px;
    line-height: 1.1; color: {_C['ink']};
  }}
  .hero-delta {{
    margin-top: 8px;
    font-size: 13px; color: {_C['ink_2']};
  }}
  .hero-delta .figure {{ font-family: {_MONO}; font-size: 12px; }}
  .sep {{ color: {_C['ink_3']}; padding: 0 7px; }}

  /* ── Allocation ───────────────────────────────────── */
  .alloc {{ padding: 26px 40px 26px; }}
  .bar {{ margin-top: 9px; }}
  .bar td {{ height: 8px; line-height: 8px; font-size: 0; }}
  .alloc-row td {{
    padding: 9px 0 0;
    font-size: 13px; color: {_C['ink_2']};
    border-bottom: none;
  }}
  .swatch {{
    display: inline-block; width: 8px; height: 8px;
    margin-right: 8px; vertical-align: middle;
  }}
  .alloc-name {{ color: {_C['ink']}; }}
  .alloc-figure {{
    font-family: {_MONO}; font-size: 12px; color: {_C['ink']};
    white-space: nowrap;
  }}

  /* ── Report content ───────────────────────────────── */
  .content {{ padding: 26px 40px 8px; color: {_C['ink_2']}; }}
  .content h1 {{
    margin: 34px 0 12px;
    padding-top: 14px;
    border-top: 1px solid {_C['rule']};
    font-family: {_SERIF};
    font-size: 20px; font-weight: 400; letter-spacing: -0.2px;
    color: {_C['ink']};
  }}
  .content h1:first-child {{ margin-top: 0; padding-top: 0; border-top: none; }}
  .content h2 {{
    margin: 22px 0 8px;
    font-size: 11px; font-weight: 700; letter-spacing: 1.3px;
    text-transform: uppercase; color: {_C['ink_3']};
  }}
  .content h3 {{
    margin: 16px 0 6px;
    font-size: 14px; font-weight: 600; color: {_C['ink']};
  }}
  .content p {{ margin: 9px 0; }}
  .content strong {{ color: {_C['ink']}; font-weight: 600; }}
  .content em {{ color: {_C['ink_2']}; }}
  .content a {{ color: {_C['accent']}; text-decoration: underline; }}
  .content ul, .content ol {{ margin: 9px 0; padding-left: 20px; }}
  .content li {{ margin: 5px 0; }}
  .content blockquote {{
    margin: 14px 0; padding: 2px 0 2px 16px;
    border-left: 2px solid {_C['accent_soft']};
    color: {_C['ink_2']};
  }}

  /* ── Data tables ──────────────────────────────────── */
  /* Rules, not fills: research tables are ruled, and a striped background is
     one of the first things Outlook renders inconsistently. */
  .content table {{
    width: 100%; margin: 14px 0; font-size: 13px;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
  }}
  .content th {{
    padding: 0 10px 7px;
    border-bottom: 1px solid {_C['ink']};
    font-size: 10px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: {_C['ink_3']};
    text-align: left;
  }}
  .content td {{
    padding: 9px 10px;
    border-bottom: 1px solid {_C['rule']};
    color: {_C['ink_2']};
  }}
  .content th:first-child, .content td:first-child {{ padding-left: 0; }}
  .content th:last-child, .content td:last-child {{ padding-right: 0; }}
  .content td strong {{ color: {_C['ink']}; }}

  /* nowrap keeps the marker with its figure — a long fund name otherwise
     pushes the number onto a line of its own, orphaning the ▲. */
  .up {{ color: {_C['up']}; font-weight: 600; white-space: nowrap; }}
  .down {{ color: {_C['down']}; font-weight: 600; white-space: nowrap; }}

  /* Verdict chips, applied to whole-cell matches only. */
  .verdict {{
    display: inline-block; padding: 3px 8px;
    min-width: 42px; text-align: center;
    font-size: 10px; font-weight: 700; letter-spacing: 0.8px;
    text-transform: uppercase;
    border: 1px solid {_C['rule']}; color: {_C['ink_2']};
  }}
  .verdict-add {{ border-color: {_C['up']}; color: {_C['up']}; background: {_C['up_bg']}; }}
  .verdict-trim {{ border-color: {_C['down']}; color: {_C['down']}; background: {_C['down_bg']}; }}
  .verdict-hold {{ border-color: {_C['rule']}; color: {_C['ink_2']}; }}

  code, pre {{
    font-family: {_MONO}; font-size: 12px;
    background: {_C['canvas']}; color: {_C['ink']};
    padding: 1px 5px;
  }}
  pre {{ padding: 12px; overflow-x: auto; }}
  pre code {{ padding: 0; background: none; }}

  /* ── Footer ───────────────────────────────────────── */
  .footer {{ padding: 26px 40px 34px; }}
  .footer .rule {{ border-top: 1px solid {_C['rule']}; margin-bottom: 16px; }}
  .footer p {{
    margin: 0 0 6px;
    font-size: 11px; line-height: 1.5; color: {_C['ink_3']};
  }}
  .footer .disclaimer {{ font-family: {_SERIF}; font-style: italic; font-size: 12px; }}

  /* ── Small screens ────────────────────────────────── */
  @media only screen and (max-width: 600px) {{
    .canvas {{ padding: 0; }}
    .masthead, .title-block, .hero, .alloc, .content, .footer, .rule-double {{
      padding-left: 20px; padding-right: 20px;
    }}
    .doc-title {{ font-size: 25px; }}
    .hero-figure {{ font-size: 36px; }}
    /* The holdings table is seven columns wide; at 11px with tight gutters it
       fits a 390pt phone instead of forcing the client to scale the message. */
    .content table {{ font-size: 11px; }}
    .content th, .content td {{ padding-left: 3px; padding-right: 3px; }}
    .verdict {{ min-width: 0; padding: 2px 5px; font-size: 9px; }}
  }}
"""

# ── HTML shell ───────────────────────────────────────────────────
# `{css}` is passed as a *value* to .format(), so the stylesheet above is
# written as ordinary CSS instead of doubling every brace.
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{subject}</title>
<style>{css}</style>
</head>
<body>
<table role="presentation" class="canvas" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td align="center">

<table role="presentation" class="sheet" width="640" cellpadding="0" cellspacing="0" border="0">

  <tr><td class="masthead">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td class="desk">Portfolio Desk</td>
      <td class="dateline" align="right">{dateline}</td>
    </tr></table>
  </td></tr>

  <tr><td class="rule-double"><div></div><div></div></td></tr>

  <tr><td class="title-block">
    <h1 class="doc-title">Monthly Review</h1>
    <div class="doc-sub">{month_year} &middot; Equity and mutual funds</div>
  </td></tr>

  <tr><td class="hero">
    <div class="eyebrow">Net portfolio value</div>
    <div class="hero-figure">&#8377;{current_value}</div>
    <div class="hero-delta">
      <span class="{pnl_class}">{pnl_arrow} {pnl_pct}%</span>
      <span class="sep">|</span>
      <span class="figure">{pnl_sign}&#8377;{pnl_abs}</span> on <span class="figure">&#8377;{invested}</span> invested
    </div>
  </td></tr>

  <tr><td class="alloc">
    <div class="eyebrow">Allocation</div>
    {alloc_bar}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      {alloc_rows}
    </table>
  </td></tr>

  <tr><td class="rule-double"><div></div><div></div></td></tr>

  <tr><td class="content">
{report_html}
  </td></tr>

  <tr><td class="footer">
    <div class="rule"></div>
    <p>Portfolio Monitor &middot; generated {generated_at}</p>
    <p>Holdings from Zerodha Kite. Prices and fundamentals from Yahoo Finance.</p>
    <p class="disclaimer">Analysis is model-generated and is not investment advice.</p>
  </td></tr>

</table>

</td></tr>
</table>
</body>
</html>
"""


def _format_inr(val) -> str:
    """
    Format a number using the Indian digit grouping convention
    (₹12,34,567 rather than ₹1,234,567).
    """
    if val is None:
        return "—"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return str(val)

    sign = "-" if val < 0 else ""
    val = abs(val)

    if val < 1000:
        return f"{sign}{val:,.2f}"

    whole = f"{val:.0f}"
    # Last 3 digits, then groups of 2: 1234567 → 12,34,567
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        head, group = head[:-2], head[-2:]
        groups.insert(0, group)
    if head:
        groups.insert(0, head)

    return f"{sign}{','.join(groups + [tail])}"


# ── Markdown post-processing ─────────────────────────────────────
_VERDICTS = {
    "ADD": "verdict-add",
    "ACCUMULATE": "verdict-add",
    "TRIM": "verdict-trim",
    "REDUCE": "verdict-trim",
    "EXIT": "verdict-trim",
    "HOLD": "verdict-hold",
    "WATCH": "verdict-hold",
}

# A direction marker plus the figure it qualifies, e.g. "▲ 12.40%".
_MOVE_RE = re.compile(r"([▲▼])\s*([+\-]?[\d,]+(?:\.\d+)?%?)?")

# Whole-cell verdicts only — matching bare words would also colour the word
# "hold" wherever it appears in the commentary.
_VERDICT_RE = re.compile(
    r"<td([^>]*)>\s*(" + "|".join(_VERDICTS) + r")\s*</td>", re.IGNORECASE
)


def _style_markers(html: str) -> str:
    """Colour direction markers and turn verdict cells into chips."""

    def move(m):
        cls = "up" if m.group(1) == "▲" else "down"
        figure = f" {m.group(2)}" if m.group(2) else ""
        return f'<span class="{cls}">{m.group(1)}{figure}</span>'

    def verdict(m):
        word = m.group(2).upper()
        return (
            f'<td{m.group(1)}>'
            f'<span class="verdict {_VERDICTS[word]}">{word}</span>'
            f'</td>'
        )

    return _MOVE_RE.sub(move, _VERDICT_RE.sub(verdict, html))


def _build_allocation(summary: dict) -> tuple[str, str]:
    """
    Return (bar_html, rows_html) for the equity/mutual-fund split.

    The bar is a two-cell table with percentage widths, which every mail
    client can lay out; segments worth nothing are dropped so they don't
    leave a hairline artefact.
    """
    segments = [
        ("Equity", summary.get("equity_current") or 0,
         summary.get("equity_pnl_pct", 0), _C["accent"]),
        ("Mutual funds", summary.get("mf_current") or 0,
         summary.get("mf_pnl_pct", 0), _C["accent_soft"]),
    ]
    total = sum(value for _, value, _, _ in segments)
    if total <= 0:
        return "", ""

    cells, rows = [], []
    for name, value, pnl_pct, colour in segments:
        share = value / total * 100
        if share <= 0:
            continue

        cells.append(
            f'<td width="{share:.4f}%" style="width:{share:.4f}%;'
            f'background:{colour};">&nbsp;</td>'
        )

        cls = "up" if pnl_pct >= 0 else "down"
        arrow = "▲" if pnl_pct >= 0 else "▼"
        rows.append(
            '<tr class="alloc-row">'
            f'<td><span class="swatch" style="background:{colour};"></span>'
            f'<span class="alloc-name">{name}</span> {share:.1f}%</td>'
            f'<td align="right" class="alloc-figure">&#8377;{_format_inr(value)}'
            f'&nbsp;&nbsp;<span class="{cls}">{arrow} {abs(pnl_pct):.2f}%</span></td>'
            '</tr>'
        )

    bar = (
        '<table role="presentation" class="bar" width="100%" '
        'cellpadding="0" cellspacing="0" border="0"><tr>'
        + "".join(cells) +
        '</tr></table>'
    )
    return bar, "".join(rows)


def render_email(report_markdown: str, portfolio_summary: dict) -> tuple[str, str]:
    """
    Render the report into (subject, html_body).

    Kept separate from sending so the template can be exercised in tests —
    a missing placeholder here would otherwise only surface once a month.
    """
    now = now_ist()
    month_year = now.strftime("%B %Y")
    generated_at = now.strftime("%d %b %Y, %I:%M %p IST")
    dateline = now.strftime("%d %b %Y").upper()

    report_html = _style_markers(
        markdown.markdown(report_markdown, extensions=["tables", "fenced_code", "nl2br"])
    )

    current_value = _format_inr(portfolio_summary.get("total_current_value"))
    invested = _format_inr(portfolio_summary.get("total_invested"))

    pnl_raw = portfolio_summary.get("total_unrealized_pnl_abs") or 0
    pnl_abs = _format_inr(abs(pnl_raw))
    pnl_pct = portfolio_summary.get("total_unrealized_pnl_pct", 0)
    positive = pnl_pct >= 0

    alloc_bar, alloc_rows = _build_allocation(portfolio_summary)

    subject = f"Portfolio Review — {month_year} · ₹{current_value} · {pnl_pct:+.2f}%"

    full_html = _HTML_TEMPLATE.format(
        css=_CSS,
        subject=subject,
        month_year=month_year,
        dateline=dateline,
        generated_at=generated_at,
        current_value=current_value,
        invested=invested,
        pnl_abs=pnl_abs,
        pnl_pct=f"{abs(pnl_pct):.2f}",
        pnl_sign="+" if positive else "−",
        pnl_arrow="▲" if positive else "▼",
        pnl_class="up" if positive else "down",
        alloc_bar=alloc_bar,
        alloc_rows=alloc_rows,
        report_html=report_html,
    )

    return subject, full_html


def _send(subject: str, parts: list[tuple[str, str]]) -> str:
    """Send a message built from (content, subtype) parts. Returns recipient."""
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = recipient
    for content, subtype in parts:
        msg.attach(MIMEText(content, subtype, "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=60) as server:
        server.login(gmail_address, gmail_password)
        server.sendmail(gmail_address, recipient, msg.as_string())

    return recipient


def send_report(report_markdown: str, portfolio_summary: dict) -> None:
    """Render the report as styled HTML and send it via Gmail SMTP."""
    subject, full_html = render_email(report_markdown, portfolio_summary)
    recipient = _send(subject, [(report_markdown, "plain"), (full_html, "html")])
    logger.info("Report email sent to %s.", recipient)


def send_failure_notification(error_msg: str) -> None:
    """Send a short failure alert so broken runs don't go unnoticed."""
    if not all(os.environ.get(k) for k in
               ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL")):
        logger.error("Cannot send failure email — SMTP env vars missing.")
        return

    now = now_ist()
    subject = f"Portfolio Monitor failed — {now.strftime('%d %b %Y')}"
    body = (
        f"The monthly portfolio report failed at {now.isoformat()}.\n\n"
        f"Error:\n{error_msg}\n\n"
        "Check the GitHub Actions log for full details."
    )

    try:
        recipient = _send(subject, [(body, "plain")])
        logger.info("Failure notification sent to %s.", recipient)
    except Exception as exc:
        logger.error("Could not send failure notification: %s", exc)
