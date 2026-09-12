"""
Tools available to the Errand Concierge agent.

Each function decorated with @tool becomes something the LLM can call.
The docstring is what the model reads to decide when/how to use it, so
keep them clear and specific.
"""

from strands import tool
import storage
import calendar_tools
from datetime import datetime


def datetime_now_iso() -> str:
    return datetime.now().isoformat()


@tool
def add_errand(title: str, due: str = None, notes: str = None) -> str:
    """
    Add a new errand or task to the user's list.

    Args:
        title: Short description of the errand (e.g. "Pay electricity bill", "Dentist appointment")
        due: When it's due, in plain language (e.g. "Friday", "2026-09-20", "next week"). Optional.
        notes: Any extra detail worth remembering about this errand. Optional.

    Returns:
        Confirmation message with the new errand's id.
    """
    task = storage.add_task(title=title, due=due, notes=notes)

    # Best-effort Calendar sync — silently no-ops if not connected or unparseable
    due_iso = calendar_tools.parse_due_to_iso(due)
    if due_iso:
        event_id = calendar_tools.create_calendar_event(title=title, due_iso=due_iso, notes=notes or "")
        if event_id:
            storage.update_task(task["id"], calendar_event_id=event_id)

    return f"Added: '{task['title']}' (id: {task['id']}, due: {task['due'] or 'no due date set'})"


@tool
def list_errands(status: str = "pending") -> str:
    """
    List the user's errands.

    Args:
        status: Filter by status - "pending", "done", "cancelled", or "all" to show everything.

    Returns:
        A formatted list of matching errands.
    """
    filter_status = None if status == "all" else status
    tasks = storage.list_tasks(status=filter_status)
    if not tasks:
        return f"No errands found with status '{status}'."

    lines = []
    for t in tasks:
        due_str = f" (due: {t['due']})" if t.get("due") else ""
        notes_str = f" - {t['notes']}" if t.get("notes") else ""
        lines.append(f"[{t['id']}] {t['title']}{due_str} - {t['status']}{notes_str}")
    return "\n".join(lines)


@tool
def reschedule_errand(title_fragment: str, new_due: str) -> str:
    """
    Change the due date/time of an existing errand. Use this when the user says
    things like "push X to tomorrow" or "move the dentist to Friday".

    Args:
        title_fragment: A word or phrase that identifies which errand (e.g. "dentist", "electricity bill")
        new_due: The new due date/time in plain language (e.g. "Friday", "tomorrow", "2026-09-20")

    Returns:
        Confirmation message, or a note if no matching errand or multiple matches were found.
    """
    matches = storage.find_task_by_title_fragment(title_fragment)
    pending_matches = [t for t in matches if t.get("status") == "pending"]

    if not pending_matches:
        return f"No pending errand found matching '{title_fragment}'."
    if len(pending_matches) > 1:
        titles = ", ".join(f"'{t['title']}' (id: {t['id']})" for t in pending_matches)
        return f"Found multiple matches: {titles}. Please specify which one by id."

    task = pending_matches[0]
    old_due = task.get("due") or "no due date"
    storage.update_task(task["id"], due=new_due)

    # Sync to Calendar if this errand has a linked event
    if task.get("calendar_event_id"):
        due_iso = calendar_tools.parse_due_to_iso(new_due)
        if due_iso:
            calendar_tools.update_calendar_event(task["calendar_event_id"], due_iso=due_iso)

    return f"Rescheduled '{task['title']}' from {old_due} to {new_due}."


@tool
def complete_errand(title_fragment: str) -> str:
    """
    Mark an errand as done. Use this when the user says they've finished/completed a task.

    Args:
        title_fragment: A word or phrase that identifies which errand (e.g. "dentist")

    Returns:
        Confirmation message, or a note if no matching errand or multiple matches were found.
    """
    matches = storage.find_task_by_title_fragment(title_fragment)
    pending_matches = [t for t in matches if t.get("status") == "pending"]

    if not pending_matches:
        return f"No pending errand found matching '{title_fragment}'."
    if len(pending_matches) > 1:
        titles = ", ".join(f"'{t['title']}' (id: {t['id']})" for t in pending_matches)
        return f"Found multiple matches: {titles}. Please specify which one by id."

    task = pending_matches[0]
    storage.update_task(task["id"], status="done", completed_at=datetime_now_iso())
    return f"Marked '{task['title']}' as done. Nice work."


@tool
def cancel_errand(title_fragment: str) -> str:
    """
    Cancel/remove an errand the user no longer needs to do.

    Args:
        title_fragment: A word or phrase that identifies which errand (e.g. "dentist")

    Returns:
        Confirmation message, or a note if no matching errand or multiple matches were found.
    """
    matches = storage.find_task_by_title_fragment(title_fragment)
    pending_matches = [t for t in matches if t.get("status") == "pending"]

    if not pending_matches:
        return f"No pending errand found matching '{title_fragment}'."
    if len(pending_matches) > 1:
        titles = ", ".join(f"'{t['title']}' (id: {t['id']})" for t in pending_matches)
        return f"Found multiple matches: {titles}. Please specify which one by id."

    task = pending_matches[0]
    storage.update_task(task["id"], status="cancelled", cancelled_at=datetime_now_iso())

    if task.get("calendar_event_id"):
        calendar_tools.delete_calendar_event(task["calendar_event_id"])

    return f"Cancelled '{task['title']}'."
