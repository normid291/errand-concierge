"""
google_auth.py — Handles Google OAuth (Calendar-only scope) for Errand Concierge.

This is a THIN auth layer: it does NOT create user accounts. It only stores
a single set of Google tokens (assume single-user/demo deployment), enabling
add_errand / reschedule_errand to sync to the connected Google Calendar.

Setup required (Google Cloud Console):
1. Enable "Google Calendar API" for your project.
2. Create OAuth 2.0 Client ID (type: Web application).
3. Add authorized redirect URI matching REDIRECT_URI below.
4. Add your own Google account as a "Test user" under OAuth consent screen
   (you'll stay in "Testing" publish status — fine for a hackathon demo).
5. Set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET as env vars (or paste below).

Token storage: tokens.json (local file, gitignore this!).
"""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

# ---- Config: fill these in (or set as env vars) ----
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback"
)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

TOKENS_FILE = Path(__file__).parent / "tokens.json"


# ---------------- Token storage ----------------

def _load_tokens() -> dict | None:
    if not TOKENS_FILE.exists():
        return None
    try:
        return json.loads(TOKENS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_tokens(tokens: dict) -> None:
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def _clear_tokens() -> None:
    if TOKENS_FILE.exists():
        TOKENS_FILE.unlink()


# ---------------- OAuth flow ----------------

def get_authorization_url() -> str:
    """Step 1: URL to send the user to for Google consent."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",   # required to get a refresh_token
        "prompt": "consent",        # forces refresh_token on repeat connects too
        "include_granted_scopes": "true",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    """Step 2: exchange the auth code (from callback) for tokens."""
    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    token_data = resp.json()
    token_data["obtained_at"] = time.time()

    # Fetch email for display purposes in the Integrations tab
    try:
        userinfo = requests.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            timeout=10,
        )
        if userinfo.ok:
            token_data["email"] = userinfo.json().get("email")
    except requests.RequestException:
        pass

    _save_tokens(token_data)
    return token_data


def _refresh_access_token(tokens: dict) -> dict:
    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "refresh_token": tokens["refresh_token"],
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    resp.raise_for_status()
    new_data = resp.json()
    tokens["access_token"] = new_data["access_token"]
    tokens["expires_in"] = new_data.get("expires_in", 3600)
    tokens["obtained_at"] = time.time()
    _save_tokens(tokens)
    return tokens


def get_valid_access_token() -> str | None:
    """Returns a usable access token, refreshing if needed. None if not connected."""
    tokens = _load_tokens()
    if not tokens:
        return None

    expires_in = tokens.get("expires_in", 3600)
    obtained_at = tokens.get("obtained_at", 0)
    # Refresh if within 60s of expiry
    if time.time() > obtained_at + expires_in - 60:
        if "refresh_token" not in tokens:
            # No refresh token — connection is dead, must reconnect
            _clear_tokens()
            return None
        try:
            tokens = _refresh_access_token(tokens)
        except requests.RequestException:
            return None

    return tokens["access_token"]


def get_connection_status() -> dict:
    """For the Integrations tab: is Calendar connected, and as whom?"""
    tokens = _load_tokens()
    if not tokens:
        return {"connected": False}
    # Confirm the token is actually still valid/refreshable
    token = get_valid_access_token()
    if not token:
        return {"connected": False}
    return {"connected": True, "email": tokens.get("email")}


def disconnect() -> None:
    """Revoke the token with Google and clear local storage."""
    tokens = _load_tokens()
    if tokens and tokens.get("refresh_token"):
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": tokens["refresh_token"]},
                timeout=10,
            )
        except requests.RequestException:
            pass  # best-effort; clear local state regardless
    _clear_tokens()
