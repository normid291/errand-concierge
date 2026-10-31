"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.factory import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        base_dir=tmp_path,
        database_path=tmp_path / "errands.db",
        demo_mode=True,
        app_secret="test-secret",
        calendar_timezone="Africa/Lagos",
    )


@pytest.fixture()
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client
