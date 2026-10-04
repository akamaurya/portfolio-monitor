"""
Generate the monthly portfolio note via Google Gemini.

The prompt fixes the section list, the table shapes and the column alignment
so the markdown lands predictably in the email template — the ▲/▼ markers and
the one-word Call column are what `emailer._style_markers` keys off.
"""

import os
import json
import logging

import requests
from google import genai
from google.genai import types

from src.clock import now_ist

logger = logging.getLogger(__name__)

# ── System instruction ───────────────────────────────────────────
_SYSTEM_INSTRUCTION = (
    "You write the monthly note for an Indian equity research desk. Your "
    "reader is the portfolio's owner: numerate, short on time, reading on a "
    "phone.\n\n"
    "Voice: plain, direct, unhedged. State the call and the number that "
    "supports it. No hype, no filler openings ('In this report we will…'), "
    "no restating the question. If a position looks expensive or a thesis has "
    "broken, say so in the first sentence about it.\n\n"
    "Formatting rules, which matter as much as the analysis:\n"
    "- NEVER use emoji. Use the characters ▲ and ▼ for direction, nothing else.\n"
    "- Prefer tables to prose. Prefer bullets to paragraphs. A paragraph may "
    "not exceed three sentences.\n"
    "- In markdown tables, right-align every numeric column using the |---:| "
    "alignment marker, and left-align text columns with |:---|.\n"
    "- Money is ₹ with Indian grouping (₹1,04,230 not ₹104,230). Percentages "
    "carry two decimals and a sign.\n"
    "- Do not restate a table's contents in prose underneath it.\n"
    "- Never invent a figure. Every number must come from the data supplied. "
    "If something is not in the data, omit it rather than estimating."
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

MARKET RESEARCH CONTEXT (ground your analysis in this; cite its numbers):
{research_context}

Write the note using exactly the section headings below, in this order, as
markdown H1 (#). Do not add sections, and do not number them.

# The month in one line

One sentence naming the single most important thing that happened to this
portfolio, then a two-column table of the three figures that matter most.

# Holdings

Under an H2 heading "## Equity", one table with every equity holding, sorted
by value descending:

| Stock | Qty | Avg cost | CMP | Value | P&L % | Call |
|:------|----:|---------:|----:|------:|------:|:-----|

Every money cell in this table — Avg cost, CMP, Value — must carry the ₹
symbol and exactly two decimals (₹1,275.00, ₹13,302.24). Every P&L % must be
prefixed with ▲ or ▼ and carry two decimals (▲14.05%, ▼6.02%). The Call column
is exactly one of ADD, HOLD, TRIM, EXIT — no other words, no punctuation.

Then, under an H2 heading "## Mutual funds", a second table:

| Fund | Invested | Current | P&L % |
|:-----|---------:|--------:|------:|

The same rules apply here: ₹ and two decimals on Invested and Current, and a
▲ or ▼ prefix on every P&L %. Shorten each fund name to its recognisable part
("Parag Parikh Flexi Cap", "ICICI Prudential Liquid") rather than repeating
the full "- Direct Plan - Growth" suffix.

# What moved

Three winners and three laggards as bullets, each one line:
**SYMBOL** ▲X.XX% — the reason, from the research data or the fundamentals
supplied. If you do not know why something moved, write "no clear driver in
the data" rather than speculating.

# Allocation

A sector table with a concentration read underneath it:

| Sector | Value | Weight |
|:-------|------:|-------:|

Follow it with one or two bullets on concentration risk — name any single
holding or sector above 25% of the portfolio explicitly.

# Market backdrop

Two subsections as H2 (##): "India" and "Global". Four bullets each, maximum
two lines per bullet. For India, lead with the FII/DII flow numbers from the
research data above, cited with their actual figures, then RBI policy and
earnings themes. For Global, cover the Fed, US yields, Brent and the dollar.

# The calls

A numbered list of three to five actions, most important first. Each one:

**Action** — the reason, and the specific price or level that would trigger
it. An action is something the reader could place as an order tomorrow, not
a sentiment ("stay diversified" is not an action; "trim 2 units of TITAN
above ₹3,800" is).

# Watchlist

Two or three names not currently held, as a table:

| Name | Why now | Entry below |
|:-----|:--------|------------:|

Hard limits: 1200 words total. No emoji anywhere. No preamble before the
first heading and no summary after the last one.
"""


# ── Response validation ──────────────────────────────────────────
def _validate(report_text: str | None, finish_reason) -> str:
    """
    Return the report, or raise so the caller falls through to the next
    provider. A blocked response yields no text; one that ran out of budget
    yields a note cut off mid-sentence, which is worse than none at all
    because it still looks deliverable.
    """
    if not report_text or not report_text.strip():
        raise RuntimeError(f"empty response (finish_reason: {finish_reason})")

    if str(finish_reason).endswith(("MAX_TOKENS", "length")):
        raise RuntimeError(
            f"truncated response — hit the output token cap "
            f"({len(report_text)} chars)"
        )

    # The prompt asks for seven H1 sections; markedly fewer means the model
    # drifted or stopped early.
    sections = report_text.count("\n# ") + report_text.startswith("# ")
    if sections < 4:
        raise RuntimeError(f"incomplete report — only {sections} sections")

    return report_text


# ── OpenAI-compatible providers ──────────────────────────────────
# NVIDIA and Moonshot both speak the OpenAI chat-completions protocol, so one
# function serves both and plain requests does the job — no extra dependency.
#
# Providers are tried top to bottom, and each of a provider's models in turn,
# before falling through to Gemini. NVIDIA leads because it is the one that
# currently answers.
#
# deepseek-ai/deepseek-v4-flash-0731 is listed in NVIDIA's catalogue but its
# inference function is not provisioned for this account — it returns
# "Specified function in account ... is not found". Add it to the model list
# below if that access is ever granted.
_OPENAI_PROVIDERS = [
    {
        "label": "NVIDIA",
        "env": "NVIDIA_API_KEY",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "models": ["moonshotai/kimi-k3"],
    },
    {
        "label": "Kimi",
        "env": "KIMI_API_KEY",
        "url": "https://api.moonshot.ai/v1/chat/completions",
        "models": ["kimi-k3", "kimi-k2.6"],
    },
]

_OPENAI_TIMEOUT = 180
# Reasoning models spend part of this budget thinking before they write, so it
# has to comfortably exceed the length of the note itself.
_OPENAI_MAX_TOKENS = 16384


def _generate_via_openai_api(prompt: str, provider: dict, api_key: str) -> str:
    """
    Try each of a provider's models in turn over the OpenAI chat-completions
    protocol. Raises if none produce a valid report.
    """
    label = provider["label"]
    last_err = None

    for model in provider["models"]:
        try:
            logger.info("Calling %s model: %s with key starting %s***", label, model, api_key[:4])
            resp = requests.post(
                provider["url"],
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_INSTRUCTION},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": _OPENAI_MAX_TOKENS,
                },
                timeout=_OPENAI_TIMEOUT,
            )

            # Read the body before raising: both providers put the useful part
            # ("insufficient balance", "function not found") in the payload,
            # and raise_for_status alone reduces that to "429 Client Error".
            try:
                data = resp.json()
            except ValueError:
                data = {}

            if isinstance(data, dict) and "error" in data:
                err = data["error"]
                raise RuntimeError(
                    f"{err.get('type', 'error')}: {err.get('message', 'unknown error')}"
                )

            # NVIDIA reports routing failures as a bare {status, title, detail}
            # object rather than an OpenAI-shaped error.
            if isinstance(data, dict) and "choices" not in data and data.get("detail"):
                raise RuntimeError(f"{data.get('title', 'error')}: {data['detail']}")

            resp.raise_for_status()

            usage = data.get("usage") or {}
            logger.info(
                "Tokens — prompt: %s, response: %s, total: %s",
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
                usage.get("total_tokens", "?"),
            )

            # Reasoning models return their chain of thought in a separate
            # field; only the content is the report.
            choice = (data.get("choices") or [{}])[0]
            text = _validate(
                (choice.get("message") or {}).get("content"),
                choice.get("finish_reason"),
            )
            logger.info("Report generated (%d chars) using %s via %s.", len(text), model, label)
            return text

        except Exception as exc:
            logger.warning("%s model %s failed: %s", label, model, exc)
            last_err = exc

    raise RuntimeError(f"All {label} models failed. Last error: {last_err}")


# ── Gemini ───────────────────────────────────────────────────────
# gemini-3.1-pro-preview is deliberately absent: its free-tier quota is
# exhausted on this account, so every run spent three 429s working down the
# keys before reaching flash. Add it back once the quota allows.
_GEMINI_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
]


def generate_report(
    enriched_holdings: list[dict],
    mf_holdings: list[dict],
    portfolio_summary: dict,
    research_context: str = "",
) -> str:
    """
    Produce the monthly markdown note, grounded in live market research.

    Kimi is tried first when KIMI_API_KEY is set, then the Gemini chain.
    Whichever provider answers, the result must survive the same validation:
    a truncated or half-written note is rejected rather than delivered.
    """
    api_keys = [
        os.environ.get("GEMINI_API_KEY1"),
        os.environ.get("GEMINI_API_KEY2"),
        os.environ.get("GEMINI_API_KEY3"),
    ]
    api_keys = [k for k in api_keys if k and k.strip()]

    configured = [
        (prov, (os.environ.get(prov["env"]) or "").strip())
        for prov in _OPENAI_PROVIDERS
    ]
    configured = [(prov, key) for prov, key in configured if key]

    if not api_keys and not configured:
        raise ValueError(
            "No API keys found in environment variables — set at least one of "
            "NVIDIA_API_KEY, KIMI_API_KEY or GEMINI_API_KEY1."
        )

    now = now_ist()
    prompt = _PROMPT_TEMPLATE.format(
        month_year=now.strftime("%B %Y"),
        today=now.strftime("%d %B %Y"),
        portfolio_data=json.dumps(enriched_holdings, indent=2, default=str),
        mf_data=json.dumps(mf_holdings, indent=2, default=str),
        portfolio_summary=json.dumps(portfolio_summary, indent=2, default=str),
        research_context=research_context or "No research data available.",
    )

    # Gemini 3 counts thinking tokens against max_output_tokens. At 8192 a
    # long reasoning pass left ~300 tokens for the answer and the note came
    # back cut off mid-table, so the budget has to cover both — and the
    # thinking itself is capped, since an unbounded pass burned 31k tokens
    # and two minutes to write a report the prompt already fully specifies.
    gen_config = types.GenerateContentConfig(
        system_instruction=_SYSTEM_INSTRUCTION,
        temperature=0.3,
        max_output_tokens=32768,
        thinking_config=types.ThinkingConfig(thinking_budget=8192),
    )

    last_err = None

    for prov, key in configured:
        try:
            return _generate_via_openai_api(prompt, prov, key)
        except Exception as exc:
            logger.warning("%s unavailable, trying the next provider: %s", prov["label"], exc)
            last_err = exc

    for model_name in _GEMINI_MODELS:
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

                candidates = getattr(response, "candidates", None) or []
                finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
                report_text = _validate(response.text, finish_reason)

                logger.info("Report generated (%d chars) using %s.", len(report_text), model_name)
                return report_text

            except Exception as exc:
                logger.warning("Model %s with key %s*** failed: %s", model_name, api_key[:4], exc)
                last_err = exc

    raise RuntimeError(f"All models with all available keys failed. Last error: {last_err}")
