"""
Playwright-based Kite Connect authentication.

Automates the full Zerodha login flow in headless Chromium:
  Login URL → User ID + Password → (optional PIN) → TOTP → redirect with request_token
"""

import os
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
        "input#userid",           # Kite re-uses #userid for TOTP on some flows
        "input[type='number']",
        "input[autocomplete='one-time-code']",
        "input#totp",
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


def _debug_screenshot(page, name: str):
    """Save a screenshot if DEBUG_AUTH is set."""
    if os.environ.get("DEBUG_AUTH"):
        path = f"debug_{name}.png"
        page.screenshot(path=path)
        logger.info("Debug screenshot saved: %s", path)


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

        try:
            # ── Step 1: Navigate to login ────────────────────────
            page.goto(login_url, wait_until="networkidle")
            _debug_screenshot(page, "01_login_page")

            # ── Step 2: Fill user ID & password ──────────────────
            _find_and_fill(page, _SELECTORS["userid"], user_id, "User ID")
            _find_and_fill(page, _SELECTORS["password"], password, "Password")
            _debug_screenshot(page, "02_credentials_filled")

            _click_submit(page)
            page.wait_for_load_state("networkidle")
            _debug_screenshot(page, "03_after_login_submit")

            # ── Step 3 (optional): PIN entry ─────────────────────
            if pin:
                try:
                    _find_and_fill(page, _SELECTORS["pin"], pin, "PIN", timeout=5_000)
                    _click_submit(page)
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

            _click_submit(page)

            # ── Step 5: Wait for redirect with request_token ─────
            page.wait_for_url("**request_token**", timeout=30_000)
            redirect_url = page.url
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
