"""One-time import of the original JSON storage files."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.factory import create_app


def test_legacy_json_is_imported_and_renamed(tmp_path: Path):
    tasks = [
        {
            "id": "abc12345",
            "title": "Pay rent",
            "due": "Friday",
            "notes": "From the old app",
            "status": "pending",
            "created_at": "2026-09-01T10:00:00",
            "calendar_event_id": None,
        },
        {
            "id": "def67890",
            "title": "Old completed thing",
            "due": None,
            "notes": None,
            "status": "done",
            "created_at": "2026-08-01T10:00:00",
            "calendar_event_id": None,
        },
    ]
    trash = [{"id": "zzz99999", "title": "Deleted thing", "deleted_at": "2026-09-02T10:00:00"}]
    (tmp_path / "tasks.json").write_text(json.dumps(tasks))
    (tmp_path / "tasks_trash.json").write_text(json.dumps(trash))

    settings = Settings(
        base_dir=tmp_path,
        database_path=tmp_path / "errands.db",
        demo_mode=True,
        app_secret="test",
    )
    with TestClient(create_app(settings)) as client:
        errands = client.get("/api/errands?status=all").json()["errands"]
        assert {item["title"] for item in errands} == {"Pay rent", "Old completed thing"}
        assert client.get("/api/errands/trash").json()["errands"][0]["title"] == "Deleted thing"

        # The import is idempotent and the source files are moved aside.
        app_again = create_app(settings)
        with TestClient(app_again) as second_client:
            assert len(second_client.get("/api/errands?status=all").json()["errands"]) == 2

    assert (tmp_path / "tasks.json.migrated").exists()
    assert (tmp_path / "tasks_trash.json.migrated").exists()
