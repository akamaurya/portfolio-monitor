"""
Send the portfolio report as a beautifully styled HTML email via Gmail SMTP.
"""

import os
import ssl
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import markdown

logger = logging.getLogger(__name__)

# ── HTML email template ──────────────────────────────────────────
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: #0f172a; color: #e2e8f0;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}
  .wrapper {{
    max-width: 720px; margin: 0 auto;
    background: #1e293b;
  }}

  /* ── Header ────────────────────────────────────────── */
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0d9488 100%);
    padding: 32px 28px 24px;
    text-align: center;
  }}
  .header h1 {{
    margin: 0; font-size: 22px; font-weight: 700;
    color: #fff; letter-spacing: -0.3px;
  }}
  .header .subtitle {{
    margin-top: 6px; font-size: 13px;
    color: rgba(255,255,255,0.65);
  }}

  /* ── Summary Cards ─────────────────────────────────── */
  .cards {{
    display: flex; flex-wrap: wrap; gap: 0;
    background: #0f172a;
  }}
  .card {{
    flex: 1 1 33%; min-width: 140px;
    padding: 20px 24px;
    border-bottom: 1px solid #334155;
    border-right: 1px solid #334155;
  }}
  .card:last-child {{ border-right: none; }}
  .card-label {{
    font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px;
    color: #94a3b8; margin-bottom: 4px;
  }}
  .card-value {{
    font-size: 24px; font-weight: 700;
    color: #f1f5f9;
  }}
  .card-value.positive {{ color: #34d399; }}
  .card-value.negative {{ color: #f87171; }}
  .card-sub {{
    font-size: 12px; color: #94a3b8; margin-top: 2px;
  }}

  /* ── Breakdown bar ─────────────────────────────────── */
  .breakdown {{
    display: flex; gap: 0;
    background: #0f172a;
    border-bottom: 1px solid #334155;
  }}
  .breakdown-item {{
    flex: 1; padding: 14px 24px;
    border-right: 1px solid #334155;
  }}
  .breakdown-item:last-child {{ border-right: none; }}
  .breakdown-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; }}
  .breakdown-val {{ font-size: 16px; font-weight: 600; color: #cbd5e1; }}
  .breakdown-pnl {{ font-size: 12px; font-weight: 600; }}
  .breakdown-pnl.positive {{ color: #34d399; }}
  .breakdown-pnl.negative {{ color: #f87171; }}

  /* ── Content ───────────────────────────────────────── */
  .content {{
    padding: 24px 28px 36px;
    color: #cbd5e1;
    font-size: 14px;
  }}
  .content h1 {{
    font-size: 20px; color: #f1f5f9;
    border-bottom: 2px solid #334155;
    padding-bottom: 8px; margin-top: 32px;
    font-weight: 700;
  }}
  .content h1:first-child {{ margin-top: 0; }}
  .content h2 {{
    font-size: 16px; color: #e2e8f0;
    margin-top: 24px; font-weight: 600;
  }}
  .content h3 {{
    font-size: 14px; color: #94a3b8;
    font-weight: 600; margin-top: 16px;
  }}
  .content p {{ margin: 8px 0; }}
  .content strong {{ color: #f1f5f9; }}
  .content em {{ color: #94a3b8; }}
  .content a {{ color: #38bdf8; text-decoration: none; }}

  /* ── Tables ────────────────────────────────────────── */
  table {{
    width: 100%; border-collapse: collapse;
    margin: 12px 0; font-size: 13px;
  }}
  th {{
    background: #334155; color: #e2e8f0;
    text-align: left; padding: 10px 12px;
    font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
  td {{
    padding: 9px 12px;
    border-bottom: 1px solid #2d3748;
    color: #cbd5e1;
  }}
  tr:nth-child(even) td {{ background: rgba(255,255,255,0.02); }}
  tr:hover td {{ background: rgba(255,255,255,0.04); }}

  /* ── Lists ─────────────────────────────────────────── */
  .content ul, .content ol {{
    padding-left: 20px; margin: 8px 0;
  }}
  .content li {{ margin: 4px 0; }}

  /* ── Code blocks ───────────────────────────────────── */
  code, pre {{
    background: #0f172a; padding: 2px 6px;
    border-radius: 4px; font-size: 12px;
    font-family: 'SF Mono', 'Fira Code', monospace;
    color: #38bdf8;
  }}
  pre {{ padding: 12px; overflow-x: auto; border-radius: 6px; }}

  /* ── Footer ────────────────────────────────────────── */
  .footer {{
    background: #0f172a; padding: 20px 28px;
    font-size: 11px; color: #475569;
    text-align: center;
    border-top: 1px solid #1e293b;
  }}

  /* ── Responsive ────────────────────────────────────── */
  @media (max-width: 480px) {{
    .card {{ flex: 1 1 100%; border-right: none; }}
    .breakdown-item {{ flex: 1 1 100%; border-right: none; }}
    .content {{ padding: 16px 16px 24px; }}
    .header {{ padding: 24px 16px 20px; }}
    .card-value {{ font-size: 20px; }}
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>📊 Portfolio Review — {month_year}</h1>
    <div class="subtitle">{generated_at}</div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="card-label">Portfolio Value</div>
      <div class="card-value">₹{current_value}</div>
    </div>
    <div class="card">
      <div class="card-label">Total P&amp;L</div>
      <div class="card-value {pnl_class}">{pnl_pct}%</div>
      <div class="card-sub">₹{pnl_abs}</div>
    </div>
    <div class="card">
      <div class="card-label">Invested</div>
      <div class="card-value">₹{invested}</div>
    </div>
  </div>

  <div class="breakdown">
    <div class="breakdown-item">
      <div class="breakdown-label">Equity</div>
      <div class="breakdown-val">₹{eq_current}</div>
      <div class="breakdown-pnl {eq_pnl_class}">{eq_pnl_pct}%</div>
    </div>
    <div class="breakdown-item">
      <div class="breakdown-label">Mutual Funds</div>
      <div class="breakdown-val">₹{mf_current}</div>
      <div class="breakdown-pnl {mf_pnl_class}">{mf_pnl_pct}%</div>
    </div>
  </div>

  <div class="content">
    {report_html}
  </div>

  <div class="footer">
    Portfolio Monitor · Auto-generated on {generated_at}
  </div>
</div>
</body>
</html>
"""


def _format_inr(val) -> str:
    """Format a number with comma grouping."""
    if val is None:
        return "—"
    try:
        val = float(val)
        sign = "-" if val < 0 else ""
        val = abs(val)
        s = f"{val:,.0f}" if val >= 1000 else f"{val:,.2f}"
        return f"{sign}{s}"
    except (ValueError, TypeError):
        return str(val)


def send_report(report_markdown: str, portfolio_summary: dict) -> None:
    """Convert markdown report to styled HTML and send via Gmail SMTP."""
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    now = datetime.now()
    month_year = now.strftime("%B %Y")
    generated_at = now.strftime("%d %b %Y, %I:%M %p IST")

    # Convert markdown → HTML
    md_extensions = ["tables", "fenced_code", "nl2br"]
    report_html = markdown.markdown(report_markdown, extensions=md_extensions)

    # Summary values
    current_value = _format_inr(portfolio_summary.get("total_current_value"))
    invested = _format_inr(portfolio_summary.get("total_invested"))
    pnl_abs = _format_inr(portfolio_summary.get("total_unrealized_pnl_abs"))
    pnl_pct = portfolio_summary.get("total_unrealized_pnl_pct", 0)
    pnl_class = "positive" if pnl_pct >= 0 else "negative"

    eq_current = _format_inr(portfolio_summary.get("equity_current"))
    eq_pnl_pct = portfolio_summary.get("equity_pnl_pct", 0)
    eq_pnl_class = "positive" if eq_pnl_pct >= 0 else "negative"

    mf_current = _format_inr(portfolio_summary.get("mf_current"))
    mf_pnl_pct = portfolio_summary.get("mf_pnl_pct", 0)
    mf_pnl_class = "positive" if mf_pnl_pct >= 0 else "negative"

    full_html = _HTML_TEMPLATE.format(
        month_year=month_year,
        generated_at=generated_at,
        current_value=current_value,
        invested=invested,
        pnl_abs=pnl_abs,
        pnl_pct=f"{pnl_pct:+.2f}",
        pnl_class=pnl_class,
        eq_current=eq_current,
        eq_pnl_pct=f"{eq_pnl_pct:+.2f}",
        eq_pnl_class=eq_pnl_class,
        mf_current=mf_current,
        mf_pnl_pct=f"{mf_pnl_pct:+.2f}",
        mf_pnl_class=mf_pnl_class,
        report_html=report_html,
    )

    # Build email
    subject = (
        f"📊 Portfolio — {month_year} "
        f"| ₹{current_value} | {pnl_pct:+.2f}%"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = recipient

    # Plain‑text fallback
    msg.attach(MIMEText(report_markdown, "plain", "utf-8"))
    # Rich HTML
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    # Send via Gmail SMTP‑SSL
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_address, gmail_password)
        server.sendmail(gmail_address, recipient, msg.as_string())

    logger.info("Report email sent to %s.", recipient)


def send_failure_notification(error_msg: str) -> None:
    """Send a short failure alert so broken runs don't go unnoticed."""
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("RECIPIENT_EMAIL")

    if not all([gmail_address, gmail_password, recipient]):
        logger.error("Cannot send failure email — SMTP env vars missing.")
        return

    now = datetime.now()
    subject = f"⚠️ Portfolio Monitor FAILED — {now.strftime('%d %b %Y')}"
    body = (
        f"The monthly portfolio report failed at {now.isoformat()}.\n\n"
        f"Error:\n{error_msg}\n\n"
        "Check the GitHub Actions log for full details."
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = recipient

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipient, msg.as_string())
        logger.info("Failure notification sent to %s.", recipient)
    except Exception as exc:
        logger.error("Could not send failure notification: %s", exc)
