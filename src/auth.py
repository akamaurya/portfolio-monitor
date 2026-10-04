"""
Kite authentication via direct HTTP requests + enctoken.

Uses the same login flow as Kite's own web frontend:
  1. POST credentials to /api/login  → request_id
  2. POST TOTP to /api/twofa         → enctoken cookie set
  3. Use enctoken to call Kite web API endpoints directly

This avoids the fragile Kite Connect OAuth redirect flow entirely
and is the approach used by all reliable community implementations.
"""

import os
import logging

import pyotp
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://kite.zerodha.com"

# Every network call is bounded — an unbounded request would hang the whole
# scheduled run until the GitHub Actions job timeout kills it.
_TIMEOUT = 30


class KiteWeb:
    """
    Lightweight Kite web-API client authenticated via enctoken.
    Exposes .holdings() and .positions() matching the KiteConnect SDK interface.
    """

    def __init__(self, enctoken: str, user_id: str):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Authorization": f"enctoken {enctoken}",
            "X-Kite-Version": "3",
        })
        self.user_id = user_id

    def _get(self, path: str) -> dict:
        url = f"{BASE_URL}{path}"
        resp = self._session.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error":
            raise RuntimeError(f"Kite API error: {data.get('message')}")
        return data.get("data", data)

    def holdings(self) -> list:
        """Fetch equity holdings."""
        return self._get("/oms/portfolio/holdings")

    def positions(self) -> dict:
        """Fetch positions (day + net)."""
        return self._get("/oms/portfolio/positions")

    def mf_holdings(self) -> list:
        """Fetch mutual fund (Coin) holdings."""
        return self._get("/oms/mf/holdings")

    def margins(self) -> dict:
        """Fetch funds (cash sitting in the Kite account)."""
        return self._get("/oms/user/margins")

    def profile(self) -> dict:
        """Fetch user profile (useful for verifying auth)."""
        return self._get("/oms/user/profile")


def authenticate() -> KiteWeb:
    """
    Authenticate with Kite using direct HTTP requests.
    Returns a KiteWeb instance with enctoken-based auth.
    """
    user_id = os.environ["KITE_USER_ID"]
    password = os.environ["KITE_PASSWORD"]
    totp_secret = os.environ["KITE_TOTP_SECRET"]

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })

    # ── Step 1: POST login credentials ───────────────────────────
    logger.info("Posting login credentials…")
    login_resp = session.post(
        f"{BASE_URL}/api/login",
        data={"user_id": user_id, "password": password},
        timeout=_TIMEOUT,
    )
    login_resp.raise_for_status()
    login_data = login_resp.json()

    if login_data.get("status") != "success":
        raise RuntimeError(
            f"Login failed: {login_data.get('message', login_data)}"
        )

    request_id = login_data["data"]["request_id"]
    logger.info("Login successful, got request_id.")

    # ── Step 2: POST TOTP ────────────────────────────────────────
    totp_code = pyotp.TOTP(totp_secret).now()
    logger.info("Submitting TOTP…")

    twofa_resp = session.post(
        f"{BASE_URL}/api/twofa",
        data={
            "user_id": user_id,
            "request_id": request_id,
            "twofa_value": totp_code,
        },
        timeout=_TIMEOUT,
    )

    if twofa_resp.status_code != 200:
        logger.error(
            "TOTP failed (HTTP %s): %s",
            twofa_resp.status_code, twofa_resp.text,
        )
        twofa_resp.raise_for_status()

    twofa_data = twofa_resp.json()
    if twofa_data.get("status") != "success":
        raise RuntimeError(
            f"TOTP verification failed: {twofa_data.get('message', twofa_data)}"
        )

    logger.info("TOTP verification successful.")

    # ── Step 3: Extract enctoken from cookies ────────────────────
    enctoken = session.cookies.get("enctoken")
    if not enctoken:
        raise RuntimeError(
            f"enctoken not found in cookies. "
            f"Available cookies: {list(session.cookies.keys())}"
        )

    logger.info("Got enctoken. Creating authenticated client.")

    # ── Step 4: Build authenticated KiteWeb client ───────────────
    kite = KiteWeb(enctoken=enctoken, user_id=user_id)

    # Verify by fetching profile
    profile = kite.profile()
    logger.info("Authenticated (profile %s).", "ok" if profile else "empty")

    return kite
