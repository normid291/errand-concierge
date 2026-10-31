"""Google OAuth 2.0 (Calendar events scope) with token storage in SQLite.

Single-user by design: there is one connected Google account for the whole
deployment, which is documented as a demo-scope limitation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests

from app.config import Settings
from app.db import transaction, utc_now

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

STATE_MAX_AGE = 15 * 60


class GoogleAuthError(RuntimeError):
    pass


class TokenStore:
    def __init__(self, database_path):
        self.path = database_path

    def load(self, provider: str = "google") -> dict[str, Any] | None:
        with transaction(self.path) as conn:
            row = conn.execute("SELECT data FROM oauth_tokens WHERE provider = ?", (provider,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["data"])
        except json.JSONDecodeError:
            return None

    def save(self, data: dict[str, Any], provider: str = "google") -> None:
        with transaction(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO oauth_tokens (provider, data, updated_at) VALUES (?, ?, ?)",
                (provider, json.dumps(data), utc_now()),
            )

    def clear(self, provider: str = "google") -> None:
        with transaction(self.path) as conn:
            conn.execute("DELETE FROM oauth_tokens WHERE provider = ?", (provider,))


class GoogleOAuth:
    def __init__(self, settings: Settings, token_store: TokenStore):
        self.settings = settings
        self.tokens = token_store

    # ------------------------------------------------------------------ state
    def _sign(self, payload: str) -> str:
        signature = hmac.new(self.settings.app_secret.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature).decode().rstrip("=")

    def make_state(self) -> str:
        payload = f"{int(time.time())}:{secrets.token_urlsafe(12)}"
        raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        return f"{raw}.{self._sign(raw)}"

    def verify_state(self, state: str) -> bool:
        if not state or "." not in state:
            return False
        raw, signature = state.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(raw)):
            return False
        try:
            payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
            timestamp = int(payload.split(":", 1)[0])
        except (ValueError, UnicodeDecodeError):
            return False
        return time.time() - timestamp <= STATE_MAX_AGE

    # ------------------------------------------------------------------ OAuth
    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.google_client_id,
            "redirect_uri": self.settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        try:
            response = requests.post(
                TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self.settings.google_client_id,
                    "client_secret": self.settings.google_client_secret,
                    "redirect_uri": self.settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise GoogleAuthError("Could not reach Google to finish sign-in.") from exc

        if not response.ok:
            raise GoogleAuthError(f"Google rejected the authorization code ({response.status_code}).")

        data = response.json()
        data["obtained_at"] = time.time()
        data["expires_at"] = time.time() + int(data.get("expires_in", 3600))

        access_token = data.get("access_token")
        if access_token:
            try:
                userinfo = requests.get(
                    USERINFO_ENDPOINT,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if userinfo.ok:
                    data["email"] = userinfo.json().get("email")
            except requests.RequestException:
                pass

        self.tokens.save(data)
        return data

    def _refresh(self, tokens: dict[str, Any]) -> dict[str, Any] | None:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            self.tokens.clear()
            return None
        try:
            response = requests.post(
                TOKEN_ENDPOINT,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self.settings.google_client_id,
                    "client_secret": self.settings.google_client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
        except requests.RequestException:
            return None

        if not response.ok:
            # invalid_grant means the user revoked access; drop the dead token.
            self.tokens.clear()
            return None

        refreshed = response.json()
        tokens["access_token"] = refreshed["access_token"]
        tokens["expires_in"] = refreshed.get("expires_in", 3600)
        tokens["expires_at"] = time.time() + int(tokens["expires_in"])
        tokens["obtained_at"] = time.time()
        self.tokens.save(tokens)
        return tokens

    def access_token(self) -> str | None:
        tokens = self.tokens.load()
        if not tokens:
            return None
        expires_at = tokens.get("expires_at") or (
            float(tokens.get("obtained_at", 0)) + int(tokens.get("expires_in", 3600))
        )
        if time.time() > float(expires_at) - 120:
            tokens = self._refresh(tokens)
            if not tokens:
                return None
        return tokens.get("access_token")

    def status(self) -> dict[str, Any]:
        if not self.settings.google_configured:
            return {"connected": False, "configured": False}
        tokens = self.tokens.load()
        if not tokens:
            return {"connected": False, "configured": True}
        if not self.access_token():
            return {"connected": False, "configured": True}
        return {"connected": True, "configured": True, "email": tokens.get("email")}

    def disconnect(self) -> None:
        tokens = self.tokens.load() or {}
        token = tokens.get("refresh_token") or tokens.get("access_token")
        if token:
            try:
                requests.post(REVOKE_ENDPOINT, params={"token": token}, timeout=10)
            except requests.RequestException:
                pass
        self.tokens.clear()
