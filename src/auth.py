"""
Playwright-based Kite Connect authentication.

Automates the full Zerodha login flow in headless Chromium:
  Login URL → User ID + Password → (optional PIN) → TOTP → redirect with request_token

Per Kite Connect v3 docs (https://kite.trade/docs/connect/v3/user/):
  1. Navigate to https://kite.zerodha.com/connect/login?v=3&api_key=xxx
  2. Successful login redirects to registered URL with ?request_token=xxx
  3. POST request_token + checksum to /session/token for access_token
"""

import os
import time
import logging
from urllib.parse import urlparse, parse_qs

import pyotp
from kiteconnect import KiteConnect
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

logger = logging.getLogger(__name__)

# ── Selector candidates (Kite may update their frontend) ────────────
_SELECTORS = {
    "userid": [
        "input#userid",
        "input[type='text'][autocomplete='username']",
        "input[type='text']",
    ],
    "password": [
        "input#password",
        "input[type='password']",
    ],
    "pin": [
        "input#pin",
        "input[label='PIN']",
    ],
    "totp": [
        "input[type='number']",
        "input[autocomplete='one-time-code']",
        "input#totp",
        "input#userid",           # Kite re-uses #userid for TOTP on some flows
    ],
    "submit": [
        "button[type='submit']",
        ".button-orange",
    ],
}


def _find_and_fill(page, candidates: list[str], value: str, label: str, timeout: int = 10_000):
    """Try each selector candidate until one is visible, then fill it."""
    for sel in candidates:
        try:
            el = page.wait_for_selector(sel, state="visible", timeout=timeout)
            if el:
                el.fill(value)
                logger.debug("Filled '%s' using selector: %s", label, sel)
                return
        except PwTimeout:
            continue
    raise RuntimeError(f"Could not find a visible element for '{label}'. Tried: {candidates}")


def _click_submit(page, timeout: int = 10_000):
    """Click the submit / continue button."""
    for sel in _SELECTORS["submit"]:
        try:
            btn = page.wait_for_selector(sel, state="visible", timeout=timeout)
            if btn:
                btn.click()
                logger.debug("Clicked submit using selector: %s", sel)
                return
        except PwTimeout:
            continue
    raise RuntimeError("Could not find a submit button.")


def _try_click_submit(page, timeout: int = 5_000):
    """Try to click submit, but don't fail if button is gone (auto-submit)."""
    try:
        _click_submit(page, timeout=timeout)
    except (RuntimeError, Exception) as exc:
        logger.debug("Submit click skipped (likely auto-submit): %s", exc)


def _debug_screenshot(page, name: str):
    """Save a screenshot if DEBUG_AUTH is set."""
    if os.environ.get("DEBUG_AUTH"):
        path = f"debug_{name}.png"
        page.screenshot(path=path)
        logger.info("Debug screenshot saved: %s", path)


def _wait_for_request_token_url(page, timeout: int = 30_000) -> str:
    """
    Wait for the page URL to contain 'request_token'.
    
    This handles two scenarios:
    1. Redirect to a reachable URL (e.g. a local server)
    2. Redirect to an unreachable URL (e.g. http://127.0.0.1 on GitHub Actions)
       In this case, the page may show an error, but the URL still contains the token.
    """
    start = time.time()
    timeout_secs = timeout / 1000

    while time.time() - start < timeout_secs:
        current_url = page.url
        if "request_token" in current_url:
            return current_url
        # Also check if navigation failed but URL changed to redirect target
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass

    raise RuntimeError(
        f"Timed out waiting for request_token redirect after {timeout_secs}s. "
        f"Last URL: {page.url}"
    )


def authenticate() -> KiteConnect:
    """
    Run the full Kite Connect headless login flow and return an
    authenticated KiteConnect instance.
    """
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]
    user_id = os.environ["KITE_USER_ID"]
    password = os.environ["KITE_PASSWORD"]
    totp_secret = os.environ["KITE_TOTP_SECRET"]
    pin = os.environ.get("KITE_PIN")          # optional

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()
    logger.info("Login URL: %s", login_url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # Capture redirect URL even if the page itself fails to load
        # (e.g. redirect to http://127.0.0.1 which isn't running)
        captured_redirect_url = None

        def on_response(response):
            nonlocal captured_redirect_url
            if "request_token" in response.url:
                captured_redirect_url = response.url

        def on_request(request):
            nonlocal captured_redirect_url
            if "request_token" in request.url:
                captured_redirect_url = request.url

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            # ── Step 1: Navigate to login ────────────────────────
            page.goto(login_url, wait_until="networkidle")
            page.wait_for_timeout(1000)  # Let page fully render
            _debug_screenshot(page, "01_login_page")

            # ── Step 2: Fill user ID & password ──────────────────
            _find_and_fill(page, _SELECTORS["userid"], user_id, "User ID")
            _find_and_fill(page, _SELECTORS["password"], password, "Password")
            _debug_screenshot(page, "02_credentials_filled")

            _click_submit(page)
            page.wait_for_timeout(3000)  # Wait for next page to load
            page.wait_for_load_state("networkidle")
            _debug_screenshot(page, "03_after_login_submit")

            # ── Step 3 (optional): PIN entry ─────────────────────
            if pin:
                try:
                    _find_and_fill(page, _SELECTORS["pin"], pin, "PIN", timeout=5_000)
                    _click_submit(page)
                    page.wait_for_timeout(2000)
                    page.wait_for_load_state("networkidle")
                    _debug_screenshot(page, "04_after_pin")
                except RuntimeError:
                    logger.debug("No PIN field found — skipping PIN step.")

            # ── Step 4: TOTP ─────────────────────────────────────
            totp = pyotp.TOTP(totp_secret)
            code = totp.now()
            logger.info("Generated TOTP code: %s", code)

            _find_and_fill(page, _SELECTORS["totp"], code, "TOTP")
            _debug_screenshot(page, "05_totp_filled")

            # Kite's modern UI may auto-submit after 6 digits.
            # Try clicking submit, but don't fail if element is gone.
            page.wait_for_timeout(500)
            _try_click_submit(page, timeout=3_000)

            # ── Step 5: Wait for redirect with request_token ─────
            # The redirect URL may be unreachable (e.g. http://127.0.0.1),
            # so we use multiple strategies to capture it.
            redirect_url = None

            # Strategy 1: Check if we already captured it via event listeners
            page.wait_for_timeout(5000)  # Give time for redirect
            if captured_redirect_url and "request_token" in captured_redirect_url:
                redirect_url = captured_redirect_url
                logger.info("Captured redirect URL via request listener.")

            # Strategy 2: Check current page URL
            if not redirect_url and "request_token" in page.url:
                redirect_url = page.url
                logger.info("Found request_token in current page URL.")

            # Strategy 3: Wait longer for URL to change
            if not redirect_url:
                try:
                    page.wait_for_url("**request_token**", timeout=15_000)
                    redirect_url = page.url
                    logger.info("Got redirect URL via wait_for_url.")
                except PwTimeout:
                    # Check captured URL one more time
                    if captured_redirect_url and "request_token" in captured_redirect_url:
                        redirect_url = captured_redirect_url

            if not redirect_url:
                _debug_screenshot(page, "error_no_redirect")
                raise RuntimeError(
                    f"Could not capture request_token redirect. "
                    f"Page title: '{page.title()}', URL: '{page.url}'"
                )

            _debug_screenshot(page, "06_redirect")
            logger.info("Redirect URL: %s", redirect_url)

            # ── Step 6: Extract request_token ────────────────────
            parsed = urlparse(redirect_url)
            qs = parse_qs(parsed.query)
            request_token = qs.get("request_token", [None])[0]

            if not request_token:
                raise RuntimeError(
                    f"request_token not found in redirect URL: {redirect_url}"
                )

            logger.info("Got request_token: %s…", request_token[:8])

        except Exception as exc:
            _debug_screenshot(page, "error_state")
            logger.error(
                "Auth failed — page title: '%s', URL: '%s'",
                page.title(), page.url,
            )
            raise RuntimeError(f"Kite authentication failed: {exc}") from exc
        finally:
            browser.close()

    # ── Step 7: Generate session ─────────────────────────────────
    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]
    kite.set_access_token(access_token)
    logger.info("Authenticated successfully. Access token set.")

    return kite
