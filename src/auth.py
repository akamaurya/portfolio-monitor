"""
Kite Connect authentication via direct HTTP requests.

Replaces Playwright browser automation with pure HTTP calls, which is
far more reliable in headless CI environments like GitHub Actions.

Flow (per Kite Connect v3 docs):
  1. POST credentials to https://kite.zerodha.com/api/login → get request_id
  2. POST TOTP to https://kite.zerodha.com/api/twofa → session cookies set
  3. GET the Kite Connect login URL (with session) → redirects with request_token
  4. Exchange request_token for access_token via kite.generate_session()
"""

import os
import logging
from urllib.parse import urlparse, parse_qs

import pyotp
import requests
from kiteconnect import KiteConnect

logger = logging.getLogger(__name__)


def authenticate() -> KiteConnect:
    """
    Authenticate with Kite Connect using direct HTTP requests.
    Returns an authenticated KiteConnect instance.
    """
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]
    user_id = os.environ["KITE_USER_ID"]
    password = os.environ["KITE_PASSWORD"]
    totp_secret = os.environ["KITE_TOTP_SECRET"]

    kite = KiteConnect(api_key=api_key)

    # ── Step 1: Create HTTP session ─────────────────────────────
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "X-Kite-Version": "3",
    })

    # GET the Kite Connect login URL first to capture the
    # redirect URL (contains sess_id). We'll re-use this later.
    login_url = f"https://kite.trade/connect/login?v=3&api_key={api_key}"
    logger.info("Fetching initial login URL…")
    initial_resp = session.get(login_url)
    kite_login_url = initial_resp.url  # e.g. https://kite.zerodha.com/connect/login?v=3&api_key=xxx&sess_id=yyy
    logger.info("Got Kite login page URL: %s", kite_login_url)

    # ── Step 2: POST login credentials ───────────────────────────
    logger.info("Posting login credentials…")
    login_resp = session.post(
        "https://kite.zerodha.com/api/login",
        data={"user_id": user_id, "password": password},
    )
    login_resp.raise_for_status()
    login_data = login_resp.json()

    if login_data.get("status") != "success":
        raise RuntimeError(
            f"Login failed: {login_data.get('message', login_data)}"
        )

    request_id = login_data["data"]["request_id"]
    logger.info("Login successful, got request_id.")

    # ── Step 3: Submit TOTP ──────────────────────────────────────
    totp_code = pyotp.TOTP(totp_secret).now()
    logger.info("Generated TOTP code: %s", totp_code)

    twofa_resp = session.post(
        "https://kite.zerodha.com/api/twofa",
        data={
            "user_id": user_id,
            "request_id": request_id,
            "twofa_value": totp_code,
        },
    )

    if twofa_resp.status_code != 200:
        logger.error(
            "TOTP request failed (HTTP %s): %s",
            twofa_resp.status_code, twofa_resp.text,
        )
        twofa_resp.raise_for_status()

    twofa_data = twofa_resp.json()

    if twofa_data.get("status") != "success":
        raise RuntimeError(
            f"TOTP verification failed: {twofa_data.get('message', twofa_data)}"
        )

    logger.info("TOTP verification successful.")

    # ── Step 4: Get request_token ────────────────────────────────
    # After login+TOTP, re-visit the original login URL with
    # &skip_session=true to bypass the authorize page and get
    # redirected directly to the callback with request_token.
    redirect_url = kite_login_url + "&skip_session=true"
    logger.info("Fetching redirect URL to get request_token…")

    token_resp = session.get(redirect_url, allow_redirects=True)
    final_url = token_resp.url
    logger.info("Final redirect URL: %s", final_url)

    parsed = urlparse(final_url)
    qs = parse_qs(parsed.query)
    request_token = qs.get("request_token", [None])[0]

    if not request_token:
        raise RuntimeError(
            f"request_token not found in redirect URL: {final_url}"
        )

    logger.info("Got request_token: %s…", request_token[:8])

    # ── Step 4: Exchange request_token for access_token ──────────
    session_data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session_data["access_token"]
    kite.set_access_token(access_token)
    logger.info("Authenticated successfully. Access token set.")

    return kite
