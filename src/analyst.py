"""
Generate a research‑grade monthly portfolio report via Google Gemini.
"""

import os
import json
import logging
from datetime import datetime

import google.generativeai as genai

logger = logging.getLogger(__name__)

# ── System instruction ───────────────────────────────────────────
_SYSTEM_INSTRUCTION = (
    "You are a senior equity research analyst specializing in Indian "
    "markets with deep expertise in value investing (Buffett/Munger/"
    "Pabrai school), macroeconomics, and global capital flows accessible "
    "to Indian retail investors. You write like a sell-side research "
    "report — direct, opinionated, data-referenced. You never hedge "
    "every statement. When something looks overvalued or risky, you say "
    "so explicitly."
)

# ── Prompt template ──────────────────────────────────────────────
_PROMPT_TEMPLATE = """\
MONTHLY PORTFOLIO REVIEW — {month_year}
Generated: {today}

PORTFOLIO DATA:
{portfolio_data}

PORTFOLIO SUMMARY:
{portfolio_summary}

Generate a comprehensive monthly portfolio review with these sections:

# 1. Executive Summary
One-paragraph snapshot: overall performance, key macro themes affecting this portfolio this month, and the single most important action item.

# 2. Portfolio Snapshot
Table showing each holding: symbol, quantity, avg cost, current price, current value, unrealized P&L (abs and %), 1-month return, sector.
Then: total invested, total current value, total P&L.

# 3. Macro — India
Cover all of the following with current analysis:
- RBI policy stance and repo rate trajectory
- CPI and WPI inflation trends
- INR/USD dynamics and implications for import-heavy vs export companies
- FII and DII net flows (equity and debt)
- Government capex momentum (railways, defence, infrastructure)
- Key sector-specific policy developments (PLI, FAME, PTC, SEBI actions)
- Any earnings season themes if applicable

# 4. Macro — Global
- US Federal Reserve posture and rate trajectory
- US yield curve shape (2Y-10Y spread) and what it signals
- Dollar Index (DXY) trend and EM implications
- China economic recovery status and commodity demand
- Oil price trajectory (Brent) — impact on India CAD and inflation
- Any geopolitical risks relevant to markets (Middle East, Russia, Taiwan, trade policy)

# 5. Sectoral Deep Dive
For each sector present in this portfolio, write 2-3 paragraphs:
- What happened in this sector this month
- Regulatory/policy changes
- Competitive dynamics
- Tailwinds and headwinds
- How it affects the specific holdings in this portfolio

# 6. Individual Holding Review
For EACH holding, write a structured review:

**[SYMBOL] — [Company/ETF Name]**
- Current valuation: P/E [x] vs sector avg [x], P/B [x]
- Business quality: [moat assessment, management quality]
- What happened this month: [price action + business news]
- Value investing verdict: Undervalued / Fair value / Overvalued
- Recommendation: HOLD / ADD on dips below ₹X / TRIM above ₹X
- Key risk: [one specific risk]
- Key catalyst: [one upcoming catalyst]

# 7. International & ETF Exposure
Specifically analyze:
- Gold ETF exposure: role in portfolio, current gold macro thesis
- Any US-exposed funds or ETFs: currency impact, US market valuation
- Overall hedging adequacy

# 8. Portfolio Construction Review
- Concentration: is any single stock or sector oversized?
- Gaps: what's missing from a well-constructed India-focused value portfolio?
- Suggested rebalancing with specific rationale
- Target allocation you'd recommend vs current allocation

# 9. Watchlist for Next 30 Days
2-3 specific opportunities worth tracking given the current macro setup. Include why and at what price you'd act.

# 10. Key Risks to Monitor
3 specific tail risks that could affect this portfolio in the next month, with mitigation thought.

Be thorough, specific, and direct. This report is for a sophisticated individual investor who understands finance.
"""


def generate_report(enriched_holdings: list[dict], portfolio_summary: dict) -> str:
    """
    Call Gemini to produce a full markdown report.

    Tries gemini-3.1-pro-preview first, falls back to
    gemini-3.1-flash-preview if the primary model errors.
    """
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])

    now = datetime.now()
    prompt = _PROMPT_TEMPLATE.format(
        month_year=now.strftime("%B %Y"),
        today=now.strftime("%d %B %Y"),
        portfolio_data=json.dumps(enriched_holdings, indent=2, default=str),
        portfolio_summary=json.dumps(portfolio_summary, indent=2, default=str),
    )

    gen_config = genai.GenerationConfig(
        temperature=0.3,
        max_output_tokens=8192,
    )

    models_to_try = [
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
    ]

    last_err = None
    for model_name in models_to_try:
        try:
            logger.info("Calling Gemini model: %s", model_name)
            model = genai.GenerativeModel(
                model_name,
                system_instruction=_SYSTEM_INSTRUCTION,
                generation_config=gen_config,
            )
            response = model.generate_content(prompt)

            # Log token usage if available
            if hasattr(response, "usage_metadata"):
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
            logger.warning("Model %s failed: %s", model_name, exc)
            last_err = exc

    raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")
