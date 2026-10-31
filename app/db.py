"""SQLite persistence layer.

The original app wrote a single JSON file from multiple request threads, which
could lose writes when two requests overlapped. SQLite gives us atomic writes,
indexes, and a schema we can grow without rewriting the storage code.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS errands (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    notes             TEXT,
    due_text          TEXT,
    due_at            TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'done', 'cancelled')),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    completed_at      TEXT,
    cancelled_at      TEXT,
    calendar_event_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_errands_status ON errands(status);
CREATE INDEX IF NOT EXISTS idx_errands_due ON errands(due_at);

CREATE TABLE IF NOT EXISTS trash (
    id         TEXT PRIMARY KEY,
    snapshot   TEXT NOT NULL,
    deleted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider   TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(path: Path | str) -> None:
    with transaction(path) as conn:
        conn.executescript(SCHEMA)


def migrate_json_files(path: Path | str, directory: Path, timezone: str) -> int:
    """Best-effort one-time import of the old `tasks.json` / `tasks_trash.json`.

    Returns the number of errands imported. The legacy files are renamed so the
    import never runs twice.
    """
    from app.dates import parse_due

    imported = 0
    legacy_tasks = Path(directory) / "tasks.json"
    legacy_trash = Path(directory) / "tasks_trash.json"
    if not legacy_tasks.exists() and not legacy_trash.exists():
        return 0

    def load(file: Path) -> list:
        try:
            data = json.loads(file.read_text())
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    tasks = load(legacy_tasks)
    trash = load(legacy_trash)

    with transaction(path) as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM errands").fetchone()["n"]
        imported_tasks = existing == 0
        if imported_tasks:
            for task in tasks:
                title = str(task.get("title") or "").strip()
                if not title:
                    continue
                due_text = task.get("due")
                due_at = None
                if due_text:
                    parsed = parse_due(str(due_text), timezone)
                    due_at = parsed.isoformat() if parsed else None
                created = task.get("created_at") or utc_now()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO errands
                        (id, title, notes, due_text, due_at, status, created_at,
                         updated_at, completed_at, cancelled_at, calendar_event_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(task.get("id") or uuid.uuid4().hex[:8]),
                        title,
                        task.get("notes"),
                        due_text,
                        due_at,
                        task.get("status") if task.get("status") in {"pending", "done", "cancelled"} else "pending",
                        created,
                        task.get("updated_at") or created,
                        task.get("completed_at"),
                        task.get("cancelled_at"),
                        task.get("calendar_event_id"),
                    ),
                )
                imported += 1

        for entry in trash:
            task_id = str(entry.get("id") or "")
            if not task_id:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO trash (id, snapshot, deleted_at) VALUES (?, ?, ?)",
                (task_id, json.dumps(entry), entry.get("deleted_at") or utc_now()),
            )

    files_to_move = []
    if legacy_tasks.exists() and imported_tasks:
        files_to_move.append(legacy_tasks)
    if legacy_trash.exists():
        files_to_move.append(legacy_trash)
    for file in files_to_move:
        try:
            file.rename(file.with_suffix(file.suffix + ".migrated"))
        except OSError:
            pass

    return imported
