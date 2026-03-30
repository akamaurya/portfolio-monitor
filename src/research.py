"""
Gather market research context to feed into the Gemini report.

Fetches:
  1. FII/DII monthly flow data (via web search)
  2. Recent equity research reports from ICICI Direct, HDFC Securities, etc.
     - Scrapes known URL patterns for PDF reports
     - Extracts text from PDFs for Gemini context
  3. Key Indian market indicators

All data is aggregated as text to feed into the Gemini prompt.
"""

import io
import logging
import re
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ── Max chars to extract per PDF (keep prompt tokens manageable) ──
_MAX_PDF_CHARS = 3000


# ─────────────────────────────────────────────────────────────────
# PDF text extraction
# ─────────────────────────────────────────────────────────────────
def _extract_pdf_text(pdf_bytes: bytes, max_chars: int = _MAX_PDF_CHARS) -> str:
    """Extract text from PDF bytes. Returns empty string on failure."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
            if len(text) >= max_chars:
                break
        return text[:max_chars].strip()
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


def _download_pdf(url: str, timeout: int = 20) -> bytes | None:
    """Download a PDF file. Returns bytes or None on failure."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        logger.info("PDF not found or too small: %s (HTTP %s)", url, resp.status_code)
        return None
    except Exception as exc:
        logger.warning("Failed to download %s: %s", url, exc)
        return None


# ─────────────────────────────────────────────────────────────────
# ICICI Direct reports
# ─────────────────────────────────────────────────────────────────
def _fetch_icici_reports() -> list[dict]:
    """
    Try known ICICI Direct report URL patterns.
    Their PDFs live at: https://www.icicidirect.com/mailcontent/
    Naming convention: idirect_{topic}_{date}.pdf
    """
    now = datetime.now()
    year_short = now.strftime("%y")  # e.g. "26"
    month_short = now.strftime("%b").lower()  # e.g. "mar"
    month_num = now.strftime("%m")  # e.g. "03"
    year_full = now.strftime("%Y")  # e.g. "2026"
    day = now.strftime("%d")

    base = "https://www.icicidirect.com/mailcontent"

    # Generate candidate URLs based on known naming patterns
    candidates = [
        # Market strategy
        (f"{base}/idirect_marketstrategy_{year_full}.pdf", "ICICI Market Strategy"),
        (f"{base}/idirect_marketstrategy_{month_short}{year_short}.pdf", "ICICI Market Strategy"),
        # Sector updates
        (f"{base}/idirect_itsectorupdate_{month_short}{year_short}.pdf", "ICICI IT Sector Update"),
        (f"{base}/idirect_bankingsectorupdate_{month_short}{year_short}.pdf", "ICICI Banking Sector Update"),
        (f"{base}/idirect_autosectorupdate_{month_short}{year_short}.pdf", "ICICI Auto Sector Update"),
        (f"{base}/idirect_pharmasectorupdate_{month_short}{year_short}.pdf", "ICICI Pharma Sector Update"),
        (f"{base}/idirect_realtysectorupdate_{month_short}{year_short}.pdf", "ICICI Realty Sector Update"),
        (f"{base}/idirect_cementsectorupdate_{month_short}{year_short}.pdf", "ICICI Cement Sector Update"),
        (f"{base}/idirect_metalsectorupdate_{month_short}{year_short}.pdf", "ICICI Metal Sector Update"),
        (f"{base}/idirect_fmcgsectorupdate_{month_short}{year_short}.pdf", "ICICI FMCG Sector Update"),
        # Market wraps (try a few recent dates)
        (f"{base}/idirect_marketwrap_{day}{month_num}{year_short}.pdf", "ICICI Market Wrap"),
        (f"{base}/idirect_marketwrap_{int(day)-1:02d}{month_num}{year_short}.pdf", "ICICI Market Wrap"),
        # Model portfolio
        (f"{base}/idirect_modelportfolio_{month_short}{year_short}.pdf", "ICICI Model Portfolio"),
        # Monthly outlook
        (f"{base}/idirect_monthlyoutlook_{month_short}{year_short}.pdf", "ICICI Monthly Outlook"),
        (f"{base}/idirect_equitystrategy_{month_short}{year_short}.pdf", "ICICI Equity Strategy"),
    ]

    reports = []
    for url, label in candidates:
        logger.info("Trying ICICI report: %s", url)
        pdf_bytes = _download_pdf(url, timeout=10)
        if pdf_bytes:
            text = _extract_pdf_text(pdf_bytes)
            if text and len(text) > 100:
                reports.append({
                    "source": "ICICI Direct",
                    "title": label,
                    "url": url,
                    "text": text,
                })
                logger.info("✓ Found: %s (%d chars)", label, len(text))
            # Stop after finding 3 reports to avoid slow CI
            if len(reports) >= 3:
                break

    return reports


# ─────────────────────────────────────────────────────────────────
# HDFC Securities reports
# ─────────────────────────────────────────────────────────────────
def _fetch_hdfc_reports() -> list[dict]:
    """
    Try to find recent HDFC Securities reports.
    Their PDFs use hash-based filenames under:
    https://static.hdfcsec.com/research/reports/
    Since we can't list the directory, we use search to find URLs.
    """
    reports = []

    # Search DuckDuckGo for recent HDFC reports
    now = datetime.now()
    month = now.strftime("%B %Y")
    query = f"site:hdfcsec.com research report {month} sector strategy"

    results = _web_search_snippets(query, num_results=5)
    for r in results:
        url = r.get("url", "")
        if ".pdf" in url.lower():
            pdf_bytes = _download_pdf(url, timeout=10)
            if pdf_bytes:
                text = _extract_pdf_text(pdf_bytes)
                if text and len(text) > 100:
                    reports.append({
                        "source": "HDFC Securities",
                        "title": r.get("title", "HDFC Report"),
                        "url": url,
                        "text": text,
                    })
                    logger.info("✓ Found HDFC report: %s", r.get("title"))
                    if len(reports) >= 2:
                        break
        else:
            # Non-PDF results — include the snippet as context
            reports.append({
                "source": "HDFC Securities",
                "title": r.get("title", "HDFC Report"),
                "url": url,
                "text": r.get("snippet", ""),
            })

    return reports[:3]


# ─────────────────────────────────────────────────────────────────
# Web search helper
# ─────────────────────────────────────────────────────────────────
def _web_search_snippets(query: str, num_results: int = 5) -> list[dict]:
    """
    Perform a lightweight web search via DuckDuckGo HTML.
    Returns list of {title, snippet, url}.
    """
    results = []
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text

        result_blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )

        for url, title, snippet in result_blocks[:num_results]:
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


# ─────────────────────────────────────────────────────────────────
# FII/DII flow data
# ─────────────────────────────────────────────────────────────────
def fetch_fii_dii_data() -> str:
    """Fetch recent FII/DII flow data via web search."""
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


# ─────────────────────────────────────────────────────────────────
# Equity research reports
# ─────────────────────────────────────────────────────────────────
def fetch_research_reports() -> str:
    """
    Fetch equity research reports from ICICI Direct and HDFC Securities.
    Downloads PDFs and extracts key text.
    """
    all_reports = []

    # ── ICICI Direct (known URL patterns) ────────────────────────
    logger.info("Fetching ICICI Direct reports…")
    icici_reports = _fetch_icici_reports()
    all_reports.extend(icici_reports)
    logger.info("Found %d ICICI Direct reports.", len(icici_reports))

    # ── HDFC Securities (via search) ─────────────────────────────
    logger.info("Fetching HDFC Securities reports…")
    hdfc_reports = _fetch_hdfc_reports()
    all_reports.extend(hdfc_reports)
    logger.info("Found %d HDFC Securities reports.", len(hdfc_reports))

    # ── Other brokerages (via search) ────────────────────────────
    now = datetime.now()
    month = now.strftime("%B %Y")
    extra_queries = [
        f"Motilal Oswal India strategy report {month}",
        f"Kotak Institutional Equities India market outlook {month}",
    ]
    for q in extra_queries:
        results = _web_search_snippets(q, num_results=2)
        for r in results:
            all_reports.append({
                "source": "Search",
                "title": r["title"],
                "url": r["url"],
                "text": r["snippet"],
            })

    if not all_reports:
        return f"No recent research reports found for {month}."

    # Format for Gemini prompt
    sections = [f"## Equity Research Reports — {month}\n"]
    for rpt in all_reports:
        sections.append(
            f"### {rpt['source']}: {rpt['title']}\n"
            f"URL: {rpt['url']}\n"
            f"{'---'}\n"
            f"{rpt['text']}\n"
        )

    return "\n".join(sections)


# ─────────────────────────────────────────────────────────────────
# Market indicators
# ─────────────────────────────────────────────────────────────────
def fetch_market_indicators() -> str:
    """Fetch key market indicators via web search."""
    now = datetime.now()
    month = now.strftime("%B %Y")

    queries = [
        f"Nifty 50 performance {month} monthly return",
        f"India RBI repo rate CPI inflation {month}",
        f"crude oil Brent price {month} India impact",
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


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────
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
