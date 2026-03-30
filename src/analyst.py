"""
Generate a visual, concise portfolio report via Google Gemini.
"""

import os
import json
import logging
from datetime import datetime

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# ── System instruction ───────────────────────────────────────────
_SYSTEM_INSTRUCTION = (
    "You are a senior equity research analyst specializing in Indian "
    "markets. You write concise, visual, and actionable investment reports. "
    "Use tables, bullet points, and clear visual formatting. Avoid long "
    "paragraphs — prefer scannable sections with key data points. "
    "When something looks overvalued or risky, say so directly. "
    "Use emojis sparingly for visual scanners (📈📉🟢🔴⚠️🎯). "
    "Format all currency in Indian Rupees (₹) with comma grouping."
)

# ── Prompt template ──────────────────────────────────────────────
_PROMPT_TEMPLATE = """\
MONTHLY PORTFOLIO REVIEW — {month_year}
Generated: {today}

EQUITY HOLDINGS DATA:
{portfolio_data}

MUTUAL FUND HOLDINGS DATA:
{mf_data}

PORTFOLIO SUMMARY:
{portfolio_summary}

MARKET RESEARCH CONTEXT (use this data to ground your analysis):
{research_context}

Generate a visually rich, scannable monthly portfolio review. Use tables,
bullet points, and visual indicators (🟢🔴📈📉) heavily. Minimize long
prose — this should be easy to scan on a phone.

IMPORTANT: Reference the FII/DII flow data and research reports provided
above in your market context section. Cite specific numbers and sources.

Output the report in this exact structure:

# 📊 Portfolio Snapshot

Show a clear summary table:
| Metric | Value |
|--------|-------|
| Total Value | ₹X |
| Total Invested | ₹X |
| Total P&L | ₹X (X%) |
| Equity Value | ₹X (X%) |
| Mutual Funds Value | ₹X (X%) |

# 📈 Equity Holdings

Table with ALL equity holdings:
| Stock | Qty | Avg Cost | CMP | Value | P&L | P&L % | Verdict |
Use 🟢 for profit, 🔴 for loss in the P&L column.
Add a one-word verdict: HOLD / ADD / TRIM / WATCH

# 🏦 Mutual Fund Holdings

Table with ALL mutual fund holdings:
| Fund | Invested | Current | P&L | P&L % |
Use 🟢 for profit, 🔴 for loss.

# 🥇 Winners & Losers

Show the top 3 performers and bottom 3 performers with:
- Symbol, P&L %, one-line reason

# 🏗️ Sector Allocation

Show sector breakdown as a table:
| Sector | Value | % of Portfolio |
Include both equity sectors and mutual funds.

# 💰 FII/DII Flows

Summarize the latest FII/DII activity using the research data provided:
- Monthly FII net buy/sell (₹ crores) and trend
- Monthly DII net buy/sell (₹ crores) and trend
- What this means for the portfolio
Cite specific numbers from the data above.

# 🌍 Market Context

**India** (4-5 bullets):
- RBI stance, repo rate
- FII/DII flow implications
- Key policy changes, earnings themes
- Reference any insights from the research reports above

**Global** (3-4 bullets):
- Fed, US yields
- Oil (Brent), DXY
- Geopolitical risks

# 📑 Research Report Highlights

Summarize key insights from the equity research reports listed above.
Reference specific reports by name and source.

# 🔍 Key Holdings Review

For each holding worth > 5% of portfolio, write 2-3 bullet points:
- What happened this month
- Valuation assessment (Undervalued/Fair/Overvalued)
- Action: HOLD / ADD on dips below ₹X / TRIM above ₹X

# ⚠️ Action Items

Numbered list of 3-5 specific actions to take this month:
1. [Action] — [Rationale]

# 🎯 Watchlist

2-3 stocks/funds worth watching with target entry price.

Keep the ENTIRE report under 3500 words. Be direct, visual, and actionable.
"""


def generate_report(
    enriched_holdings: list[dict],
    mf_holdings: list[dict],
    portfolio_summary: dict,
    research_context: str = "",
) -> str:
    """
    Call Gemini to produce a concise, visual markdown report
    grounded in live market research data.
    """
    api_keys = [
        os.environ.get("GEMINI_API_KEY1"),
        os.environ.get("GEMINI_API_KEY2"),
        os.environ.get("GEMINI_API_KEY3"),
    ]
    api_keys = [k for k in api_keys if k and k.strip()]

    if not api_keys:
        raise ValueError("No Gemini API keys found in environment variables.")

    now = datetime.now()
    prompt = _PROMPT_TEMPLATE.format(
        month_year=now.strftime("%B %Y"),
        today=now.strftime("%d %B %Y"),
        portfolio_data=json.dumps(enriched_holdings, indent=2, default=str),
        mf_data=json.dumps(mf_holdings, indent=2, default=str),
        portfolio_summary=json.dumps(portfolio_summary, indent=2, default=str),
        research_context=research_context or "No research data available.",
    )

    gen_config = types.GenerateContentConfig(
        system_instruction=_SYSTEM_INSTRUCTION,
        temperature=0.3,
        max_output_tokens=8192,
    )

    models_to_try = [
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash",
    ]

    last_err = None
    for model_name in models_to_try:
        for api_key in api_keys:
            try:
                client = genai.Client(api_key=api_key)

                logger.info("Calling Gemini model: %s with key starting %s***", model_name, api_key[:4])
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=gen_config,
                )

                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    meta = response.usage_metadata
                    logger.info(
                        "Tokens — prompt: %s, response: %s, total: %s",
                        getattr(meta, "prompt_token_count", "?"),
                        getattr(meta, "candidates_token_count", "?"),
                        getattr(meta, "total_token_count", "?"),
                    )

                report_text = response.text
                logger.info("Report generated (%d chars) using %s.", len(report_text), model_name)
                return report_text

            except Exception as exc:
                logger.warning("Model %s with key %s*** failed: %s", model_name, api_key[:4], exc)
                last_err = exc

    raise RuntimeError(f"All Gemini models with all available keys failed. Last error: {last_err}")
