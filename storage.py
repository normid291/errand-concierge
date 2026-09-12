"""
Simple JSON-backed storage for the Errand Concierge agent.

This keeps things simple for the hackathon demo. Tasks persist between
runs in a local tasks.json file. If there's time later, this can be
swapped for DynamoDB without changing the tool functions that use it.
"""

import json
import os
import uuid
from datetime import datetime

STORAGE_FILE = os.path.join(os.path.dirname(__file__), "tasks.json")
TRASH_FILE = os.path.join(os.path.dirname(__file__), "tasks_trash.json")


def _load() -> list:
    if not os.path.exists(STORAGE_FILE):
        return []
    with open(STORAGE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save(tasks: list) -> None:
    with open(STORAGE_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


def add_task(title: str, due: str = None, notes: str = None) -> dict:
    """Add a new task/errand to storage. Returns the created task."""
    tasks = _load()
    task = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "due": due,
        "notes": notes,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "calendar_event_id": None,
    }
    tasks.append(task)
    _save(tasks)
    return task


def list_tasks(status: str = None) -> list:
    """List all tasks, optionally filtered by status (pending/done/cancelled)."""
    tasks = _load()
    if status:
        return [t for t in tasks if t.get("status") == status]
    return tasks


def find_task_by_title_fragment(fragment: str) -> list:
    """Find tasks whose title contains the given fragment (case-insensitive)."""
    tasks = _load()
    fragment_lower = fragment.lower()
    return [t for t in tasks if fragment_lower in t.get("title", "").lower()]


def update_task(task_id: str, **changes) -> dict:
    """Update fields on a task by id. Returns the updated task, or None if not found."""
    tasks = _load()
    for t in tasks:
        if t["id"] == task_id:
            t.update(changes)
            _save(tasks)
            return t
    return None


def delete_task(task_id: str) -> bool:
    """Delete a task by id. Returns True if deleted, False if not found."""
    tasks = _load()
    new_tasks = [t for t in tasks if t["id"] != task_id]
    if len(new_tasks) == len(tasks):
        return False
    _save(new_tasks)
    return True


def _load_trash() -> list:
    if not os.path.exists(TRASH_FILE):
        return []
    with open(TRASH_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save_trash(entries: list) -> None:
    with open(TRASH_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def log_deleted_task(task: dict) -> None:
    """Save a snapshot of a task to the trash log before it's hard-deleted.
    This is purely a record for display in the Trash tab - it does not affect
    the live task store, which stays a true hard delete."""
    entries = _load_trash()
    snapshot = dict(task)
    snapshot["deleted_at"] = datetime.now().isoformat()
    entries.append(snapshot)
    _save_trash(entries)


def list_deleted_tasks() -> list:
    """List trashed task snapshots, most recently deleted first."""
    entries = _load_trash()
    return sorted(entries, key=lambda t: t.get("deleted_at", ""), reverse=True)
