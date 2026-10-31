"""Errand repository — all SQL lives here, nowhere else."""

from __future__ import annotations

import builtins
import json
import uuid
from pathlib import Path
from typing import Any

from app.db import transaction, utc_now

STATUSES = ("pending", "done", "cancelled")
EDITABLE_FIELDS = {
    "title",
    "notes",
    "due_text",
    "due_at",
    "status",
    "completed_at",
    "cancelled_at",
    "calendar_event_id",
}


def _row(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class ErrandRepository:
    def __init__(self, database_path: Path | str):
        self.path = database_path

    # ------------------------------------------------------------------ reads
    def get(self, errand_id: str) -> dict[str, Any] | None:
        with transaction(self.path) as conn:
            row = conn.execute("SELECT * FROM errands WHERE id = ?", (errand_id,)).fetchone()
        return _row(row)

    def list(self, status: str | None = None, query: str | None = None) -> builtins.list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status in STATUSES:
            clauses.append("status = ?")
            params.append(status)
        if query and query.strip():
            escaped = query.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(LOWER(title) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(notes, '')) LIKE ? ESCAPE '\\')")
            params.extend([f"%{escaped}%", f"%{escaped}%"])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT * FROM errands
            {where}
            ORDER BY
                CASE status WHEN 'pending' THEN 0 WHEN 'done' THEN 1 ELSE 2 END,
                CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
                due_at ASC,
                created_at DESC
        """
        with transaction(self.path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with transaction(self.path) as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM errands GROUP BY status").fetchall()
        counts = {status: 0 for status in STATUSES}
        counts.update({row["status"]: row["n"] for row in rows})
        counts["total"] = sum(counts[status] for status in STATUSES)
        return counts

    def find_by_title_fragment(self, fragment: str) -> builtins.list[dict[str, Any]]:
        fragment = (fragment or "").strip().lower()
        if not fragment:
            return []
        escaped = fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with transaction(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM errands WHERE LOWER(title) LIKE ? ESCAPE '\\' ORDER BY created_at DESC",
                (f"%{escaped}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    # ----------------------------------------------------------------- writes
    def create(
        self,
        title: str,
        notes: str | None = None,
        due_text: str | None = None,
        due_at: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        errand = {
            "id": uuid.uuid4().hex[:8],
            "title": title.strip(),
            "notes": notes.strip() if notes else None,
            "due_text": due_text.strip() if due_text else None,
            "due_at": due_at,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "cancelled_at": None,
            "calendar_event_id": None,
        }
        with transaction(self.path) as conn:
            conn.execute(
                """
                INSERT INTO errands
                    (id, title, notes, due_text, due_at, status, created_at,
                     updated_at, completed_at, cancelled_at, calendar_event_id)
                VALUES (:id, :title, :notes, :due_text, :due_at, :status, :created_at,
                        :updated_at, :completed_at, :cancelled_at, :calendar_event_id)
                """,
                errand,
            )
        return errand

    def update(self, errand_id: str, **fields: Any) -> dict[str, Any] | None:
        changes = {key: value for key, value in fields.items() if key in EDITABLE_FIELDS}
        if not changes:
            return self.get(errand_id)
        changes["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = :{key}" for key in changes)
        changes["id"] = errand_id
        with transaction(self.path) as conn:
            cursor = conn.execute(f"UPDATE errands SET {assignments} WHERE id = :id", changes)
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM errands WHERE id = ?", (errand_id,)).fetchone()
        return _row(row)

    def delete(self, errand_id: str) -> dict[str, Any] | None:
        with transaction(self.path) as conn:
            row = conn.execute("SELECT * FROM errands WHERE id = ?", (errand_id,)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM errands WHERE id = ?", (errand_id,))
        return dict(row)

    # ------------------------------------------------------------------ trash
    def log_trash(self, errand: dict[str, Any]) -> None:
        entry = dict(errand)
        entry["deleted_at"] = utc_now()
        with transaction(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trash (id, snapshot, deleted_at) VALUES (?, ?, ?)",
                (entry["id"], json.dumps(entry), entry["deleted_at"]),
            )

    def list_trash(self) -> builtins.list[dict[str, Any]]:
        with transaction(self.path) as conn:
            rows = conn.execute("SELECT id, deleted_at FROM trash ORDER BY deleted_at DESC").fetchall()
            entries = []
            for row in rows:
                snapshot_row = conn.execute("SELECT snapshot FROM trash WHERE id = ?", (row["id"],)).fetchone()
                try:
                    snapshot = json.loads(snapshot_row["snapshot"])
                except (TypeError, json.JSONDecodeError):
                    snapshot = {"id": row["id"], "title": "Unreadable entry"}
                snapshot["deleted_at"] = row["deleted_at"]
                entries.append(snapshot)
        return entries

    def restore(self, trash_id: str) -> dict[str, Any] | None:
        with transaction(self.path) as conn:
            row = conn.execute("SELECT snapshot FROM trash WHERE id = ?", (trash_id,)).fetchone()
            if row is None:
                return None
            try:
                snapshot = json.loads(row["snapshot"])
            except json.JSONDecodeError:
                return None

            new_id = snapshot.get("id") or trash_id
            if conn.execute("SELECT 1 FROM errands WHERE id = ?", (new_id,)).fetchone():
                new_id = uuid.uuid4().hex[:8]

            now = utc_now()
            record = {
                "id": new_id,
                "title": snapshot.get("title") or "Untitled errand",
                "notes": snapshot.get("notes"),
                "due_text": snapshot.get("due_text") or snapshot.get("due"),
                "due_at": snapshot.get("due_at"),
                "status": snapshot.get("status") if snapshot.get("status") in STATUSES else "pending",
                "created_at": snapshot.get("created_at") or now,
                "updated_at": now,
                "completed_at": snapshot.get("completed_at"),
                "cancelled_at": snapshot.get("cancelled_at"),
                "calendar_event_id": None,
            }
            conn.execute(
                """
                INSERT INTO errands
                    (id, title, notes, due_text, due_at, status, created_at,
                     updated_at, completed_at, cancelled_at, calendar_event_id)
                VALUES (:id, :title, :notes, :due_text, :due_at, :status, :created_at,
                        :updated_at, :completed_at, :cancelled_at, :calendar_event_id)
                """,
                record,
            )
            conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
        return record

    def delete_trash(self, trash_id: str) -> bool:
        with transaction(self.path) as conn:
            cursor = conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
            return cursor.rowcount > 0

    def clear_trash(self) -> int:
        with transaction(self.path) as conn:
            cursor = conn.execute("DELETE FROM trash")
            return cursor.rowcount
