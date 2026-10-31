"""Errand business logic, including best-effort Google Calendar sync."""

from __future__ import annotations

import builtins
import re
from datetime import datetime
from typing import Any

from app.dates import get_timezone, now_in, parse_due
from app.db import utc_now
from app.repository import ErrandRepository
from app.services.google_calendar import GoogleCalendar

_UNSET = object()


class NotFoundError(LookupError):
    pass


class ValidationError(ValueError):
    pass


class ErrandService:
    def __init__(self, repository: ErrandRepository, calendar: GoogleCalendar, timezone: str):
        self.repo = repository
        self.calendar = calendar
        self.timezone = timezone

    # ---------------------------------------------------------------- helpers
    def _resolve_due(self, due: str | None) -> tuple[str | None, str | None]:
        if not due or not str(due).strip():
            return None, None
        text = str(due).strip()
        parsed = parse_due(text, self.timezone)
        return text, parsed.isoformat() if parsed else None

    def _connected(self) -> bool:
        try:
            return self.calendar.is_connected()
        except Exception:  # calendar must never break errand management
            return False

    def _attach_calendar(self, errand: dict[str, Any]) -> None:
        if not errand.get("due_at") or errand.get("calendar_event_id") or not self._connected():
            return
        try:
            start = datetime.fromisoformat(errand["due_at"])
        except ValueError:
            return
        event_id = self.calendar.create(errand["title"], start, errand.get("notes"))
        if event_id:
            updated = self.repo.update(errand["id"], calendar_event_id=event_id)
            if updated:
                errand.update(updated)

    def _remove_calendar(self, errand: dict[str, Any]) -> None:
        event_id = errand.get("calendar_event_id")
        if not event_id:
            return
        if self._connected():
            self.calendar.delete(event_id)
        updated = self.repo.update(errand["id"], calendar_event_id=None)
        if updated:
            errand.update(updated)

    # ------------------------------------------------------------------ write
    def create(self, title: str, due: str | None = None, notes: str | None = None) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise ValidationError("An errand needs a title.")
        due_text, due_at = self._resolve_due(due)
        errand = self.repo.create(title=title, notes=notes, due_text=due_text, due_at=due_at)
        self._attach_calendar(errand)
        return errand

    def update(self, errand_id: str, **fields: Any) -> dict[str, Any]:
        errand = self.repo.get(errand_id)
        if errand is None:
            raise NotFoundError(errand_id)

        changes: dict[str, Any] = {}
        due_changed = False

        if fields.get("title", _UNSET) is not _UNSET:
            title = (fields["title"] or "").strip()
            if not title:
                raise ValidationError("An errand needs a title.")
            changes["title"] = title
        if fields.get("notes", _UNSET) is not _UNSET:
            notes = fields["notes"]
            changes["notes"] = notes.strip() if notes and notes.strip() else None
        if fields.get("due", _UNSET) is not _UNSET:
            due_text, due_at = self._resolve_due(fields["due"])
            changes["due_text"] = due_text
            changes["due_at"] = due_at
            due_changed = True

        if not changes:
            return errand

        if due_changed and not changes["due_at"]:
            self._remove_calendar(errand)

        updated = self.repo.update(errand_id, **changes)
        if updated is None:
            raise NotFoundError(errand_id)

        if due_changed and updated.get("due_at"):
            if updated.get("calendar_event_id") and self._connected():
                try:
                    start = datetime.fromisoformat(updated["due_at"])
                    if not self.calendar.update(
                        updated["calendar_event_id"],
                        title=updated["title"],
                        start=start,
                        notes=updated.get("notes"),
                    ):
                        # The event may have been deleted in Google; recreate it.
                        self.repo.update(updated["id"], calendar_event_id=None)
                        updated["calendar_event_id"] = None
                        self._attach_calendar(updated)
                except ValueError:
                    pass
            elif not updated.get("calendar_event_id"):
                self._attach_calendar(updated)
        elif changes.get("title") and updated.get("calendar_event_id") and self._connected():
            self.calendar.update(updated["calendar_event_id"], title=updated["title"])

        return updated

    def set_status(self, errand_id: str, status: str) -> dict[str, Any]:
        errand = self.repo.get(errand_id)
        if errand is None:
            raise NotFoundError(errand_id)
        if status not in {"pending", "done", "cancelled"}:
            raise ValidationError("Unknown status.")

        now = utc_now()
        fields: dict[str, Any] = {"status": status}
        if status == "done":
            fields["completed_at"] = now
            fields["cancelled_at"] = None
            self._remove_calendar(errand)
        elif status == "cancelled":
            fields["cancelled_at"] = now
            fields["completed_at"] = None
            self._remove_calendar(errand)
        else:  # reopen
            fields["completed_at"] = None
            fields["cancelled_at"] = None

        updated = self.repo.update(errand_id, **fields)
        if updated is None:
            raise NotFoundError(errand_id)
        if status == "pending":
            self._attach_calendar(updated)
        return updated

    def delete(self, errand_id: str) -> dict[str, Any]:
        errand = self.repo.get(errand_id)
        if errand is None:
            raise NotFoundError(errand_id)
        if errand.get("calendar_event_id"):
            self._remove_calendar(errand)
        self.repo.log_trash(errand)
        deleted = self.repo.delete(errand_id)
        if deleted is None:
            raise NotFoundError(errand_id)
        return deleted

    def restore(self, trash_id: str) -> dict[str, Any]:
        restored = self.repo.restore(trash_id)
        if restored is None:
            raise NotFoundError(trash_id)
        self._attach_calendar(restored)
        return restored

    # ------------------------------------------------------------------- read
    def get(self, errand_id: str) -> dict[str, Any]:
        errand = self.repo.get(errand_id)
        if errand is None:
            raise NotFoundError(errand_id)
        return errand

    def list(self, status: str | None = None, query: str | None = None) -> builtins.list[dict[str, Any]]:
        if status in {"all", ""}:
            status = None
        return self.repo.list(status=status, query=query)

    def find_pending(self, fragment: str) -> builtins.list[dict[str, Any]]:
        pending = [task for task in self.repo.find_by_title_fragment(fragment) if task["status"] == "pending"]
        if pending:
            return pending

        # The model (or the demo parser) often includes filler words such as
        # "the" or "my". Fall back to matching every meaningful token.
        stop = {
            "the", "a", "an", "my", "our", "this", "that", "to", "for", "of",
            "and", "errand", "task",
        }
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", (fragment or "").lower())
            if token not in stop and len(token) > 1
        ]
        if not tokens:
            return []
        return [
            task
            for task in self.repo.list(status="pending")
            if all(token in task["title"].lower() for token in tokens)
        ]

    def stats(self) -> dict[str, int]:
        counts = self.repo.counts()
        tz = get_timezone(self.timezone)
        current = now_in(tz)
        today = current.date()
        overdue = 0
        due_today = 0
        for errand in self.repo.list(status="pending"):
            if not errand.get("due_at"):
                continue
            try:
                due = datetime.fromisoformat(errand["due_at"]).astimezone(tz)
            except ValueError:
                continue
            if due.date() == today:
                due_today += 1
            elif due < current:
                overdue += 1
        counts.update({"overdue": overdue, "due_today": due_today})
        return counts
