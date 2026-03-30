"""
Gather market research context to feed into the Gemini report.

Fetches:
  1. FII/DII monthly flow data (via web search)
  2. Recent equity research reports from ICICI Direct, HDFC Securities, etc.
  3. Key Indian market indicators

All data is fetched as text summaries (not full PDFs) to keep the
pipeline lean and fast in CI.
"""

import logging
import re
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# ── Google Custom Search config ──────────────────────────────────
# Uses SerpAPI-like approach with Google search via requests
_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _web_search_snippets(query: str, num_results: int = 5) -> list[dict]:
    """
    Perform a lightweight web search and return snippet results.
    Uses DuckDuckGo's HTML endpoint (no API key needed).
    """
    results = []
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=_SEARCH_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text

        # Parse results from DuckDuckGo HTML response
        # Each result is in a <div class="result__body"> block
        result_blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for url, title, snippet in result_blocks[:num_results]:
            # Clean HTML tags from title and snippet
            title_clean = re.sub(r'<[^>]+>', '', title).strip()
            snippet_clean = re.sub(r'<[^>]+>', '', snippet).strip()
            results.append({
                "title": title_clean,
                "snippet": snippet_clean,
                "url": url,
            })

    except Exception as exc:
        logger.warning("Web search failed for '%s': %s", query, exc)

    return results


def fetch_fii_dii_data() -> str:
    """
    Fetch recent FII/DII flow data via web search.
    Returns a text summary suitable for feeding into the Gemini prompt.
    """
    now = datetime.now()
    month = now.strftime("%B %Y")

    queries = [
        f"FII DII activity {month} India equity net buy sell crores monthly",
        f"FII FPI outflow inflow {month} India market crores",
    ]

    all_snippets = []
    for q in queries:
        logger.info("Searching: %s", q)
        results = _web_search_snippets(q, num_results=4)
        for r in results:
            all_snippets.append(f"- [{r['title']}]: {r['snippet']}")

    if not all_snippets:
        return f"No FII/DII data found for {month}. Use your knowledge of recent trends."

    header = f"## FII/DII Flow Data — {month}\n"
    return header + "\n".join(all_snippets)


def fetch_research_reports() -> str:
    """
    Fetch recent equity research report titles and summaries
    from major Indian brokerages via web search.
    Returns a text summary suitable for the Gemini prompt.
    """
    now = datetime.now()
    month = now.strftime("%B %Y")
    year = now.strftime("%Y")

    queries = [
        f"ICICI direct market strategy report {month} pdf",
        f"HDFC securities equity research report {month} {year}",
        f"India equity market outlook {month} institutional research report",
        f"Motilal Oswal OR Kotak OR Axis capital India strategy {month}",
    ]

    all_reports = []
    seen_titles = set()

    for q in queries:
        logger.info("Searching: %s", q)
        results = _web_search_snippets(q, num_results=3)
        for r in results:
            # Deduplicate
            title_key = r["title"].lower()[:50]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            all_reports.append(
                f"- **{r['title']}**\n  {r['snippet']}\n  Source: {r['url']}"
            )

    if not all_reports:
        return f"No recent research reports found for {month}."

    header = f"## Recent Equity Research Reports — {month}\n"
    return header + "\n".join(all_reports)


def fetch_market_indicators() -> str:
    """
    Fetch key market indicator data via web search.
    """
    now = datetime.now()
    month = now.strftime("%B %Y")

    queries = [
        f"Nifty 50 performance {month} monthly return",
        f"India RBI repo rate CPI inflation {month}",
        f"crude oil Brent price March {now.year} India impact",
        f"INR USD exchange rate {month} trend",
    ]

    all_data = []
    for q in queries:
        logger.info("Searching: %s", q)
        results = _web_search_snippets(q, num_results=2)
        for r in results:
            all_data.append(f"- [{r['title']}]: {r['snippet']}")

    if not all_data:
        return "No market indicator data found."

    header = f"## Market Indicators — {month}\n"
    return header + "\n".join(all_data)


def gather_research_context() -> str:
    """
    Main function: gather all research context into a single text block
    to feed into the Gemini report generation prompt.
    """
    logger.info("Gathering market research context…")

    sections = []

    fii_dii = fetch_fii_dii_data()
    sections.append(fii_dii)
    logger.info("FII/DII data: %d chars", len(fii_dii))

    reports = fetch_research_reports()
    sections.append(reports)
    logger.info("Research reports: %d chars", len(reports))

    indicators = fetch_market_indicators()
    sections.append(indicators)
    logger.info("Market indicators: %d chars", len(indicators))

    context = "\n\n".join(sections)
    logger.info("Total research context: %d chars", len(context))

    return context
