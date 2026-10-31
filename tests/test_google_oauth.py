"""Google OAuth helpers that do not need network access."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.db import init_db
from app.services.google_oauth import GoogleOAuth, TokenStore


def build_oauth(tmp_path: Path) -> GoogleOAuth:
    database = tmp_path / "oauth.db"
    init_db(database)
    settings = Settings(
        base_dir=tmp_path,
        database_path=database,
        demo_mode=True,
        app_secret="unit-test-secret",
        google_client_id="client-id",
        google_client_secret="client-secret",
    )
    return GoogleOAuth(settings, TokenStore(database))


def test_signed_state_round_trip(tmp_path: Path):
    oauth = build_oauth(tmp_path)
    state = oauth.make_state()
    assert oauth.verify_state(state)


def test_tampered_state_is_rejected(tmp_path: Path):
    oauth = build_oauth(tmp_path)
    state = oauth.make_state()
    assert not oauth.verify_state(state[:-1] + ("a" if state[-1] != "a" else "b"))
    assert not oauth.verify_state("nonsense")
    assert not oauth.verify_state("")


def test_status_without_tokens(tmp_path: Path):
    oauth = build_oauth(tmp_path)
    status = oauth.status()
    assert status == {"connected": False, "configured": True}
