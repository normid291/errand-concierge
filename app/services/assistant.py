"""Conversational assistant.

Two interchangeable implementations:

* ``StrandsAssistant`` – the real LLM agent (Strands SDK + Bedrock Mantle).
* ``DemoAssistant`` – a small deterministic fallback so the product is fully
  usable in local development without credentials. It understands the core
  intents (add / list / reschedule / complete / cancel) and uses the exact same
  errand service, so behaviour and storage stay consistent.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from app.config import Settings
from app.dates import get_timezone, now_in, parse_due
from app.services.errands import ErrandService

logger = logging.getLogger(__name__)


class AssistantError(RuntimeError):
    """Raised when the model or its tools fail unexpectedly."""


def build_system_prompt(timezone: str) -> str:
    current = now_in(get_timezone(timezone))
    today = current.strftime("%A, %B %d, %Y")
    return f"""You are Errand Concierge, a warm, efficient personal assistant who keeps track of
errands, appointments, and small tasks.

Today is {today}. The user's timezone is {timezone}. Trust the date above over any
instinct you have about the calendar.

Your tools:
- add_errand(title, due, notes)
- list_errands(status)
- reschedule_errand(title_fragment, new_due)
- complete_errand(title_fragment)
- cancel_errand(title_fragment)

Rules:
1. If the user brain-dumps several things, split them into separate errands and add each one.
2. Never calculate, reformat, or "correct" a due date yourself. Pass the user's phrase
   ("friday", "next week", "in 3 days", "Nov 3") to the tool almost verbatim. The parser
   resolves it against the real date.
3. The errand list can change outside this chat because the user also has an errands UI.
   Whenever they ask about current errands or refer to one by name, call list_errands in
   this turn. Do not answer from conversation memory.
4. Never refuse to add an errand because "it already exists" based on memory. The user may
   have completed or deleted it in the UI. Add it unless list_errands in this same turn
   shows it is still pending.
5. When a tool reports multiple matches, ask which one they mean instead of guessing.
6. Be brief and human. Confirm in one or two sentences. Do not dump the whole list unless
   asked. Do not invent details the tools did not return.
7. If the request is unrelated to errands, answer briefly and steer back to what you can do.
"""


# --------------------------------------------------------------------------- demo
class DemoAssistant:
    mode = "demo"

    def __init__(self, settings: Settings, errands: ErrandService):
        self.settings = settings
        self.errands = errands

    def reset(self, session_id: str) -> None:  # nothing to reset
        return None

    # -- intent helpers -----------------------------------------------------
    def _add_many(self, parts: list[str]) -> list[dict[str, Any]]:
        added = []
        for part in parts:
            parsed = self._parse_add(part)
            if parsed:
                added.append(self.errands.create(**parsed))
        return added

    def _parse_add(self, text: str) -> dict[str, str] | None:
        original = text.strip(" .!?")
        cleaned = re.sub(
            r"^(?:please\s+)?(?:add|remember|note|create|put)\s+(?:that\s+)?",
            "",
            original,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(?:i\s+(?:need|have|must|gotta)\s+to|i\s+should)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        if cleaned == original and not re.search(
            r"\b(by|before|tomorrow|today|tonight|next\s+\w+|on\s+\w+|in\s+\d+\s+(day|week))",
            original,
            re.IGNORECASE,
        ):
            return None

        due = None
        title = cleaned
        for pattern in (
            r"^(?P<title>.+?)\s+(?:by|before|due|on)\s+(?P<due>.+)$",
            r"^(?P<title>.+?)\s+(?P<due>today|tonight|tomorrow|next week|next month)\s*$",
            r"^(?P<title>.+?)\s+(?P<due>this\s+\w+|next\s+\w+)\s*$",
            r"^(?P<title>.+?)\s+(?P<due>in\s+\d+\s+(?:days?|weeks?|months?))\s*$",
        ):
            match = re.match(pattern, cleaned, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group("due").strip()
            if parse_due(candidate, self.settings.calendar_timezone):
                title, due = match.group("title").strip(), candidate
                break

        title = title.strip(" ,.-")
        if not title:
            return None
        title = title[:1].upper() + title[1:]
        return {"title": title[:200], "due": due}

    def _find_one(self, fragment: str):
        pending = self.errands.find_pending(fragment)
        if not pending:
            return None, f"I couldn't find a pending errand matching “{fragment}”."
        if len(pending) > 1:
            options = "; ".join(f"“{task['title']}”" for task in pending[:5])
            return None, f"That matches more than one errand: {options}. Which one did you mean?"
        return pending[0], None

    @staticmethod
    def _describe(task: dict[str, Any]) -> str:
        if task.get("due_text"):
            return f"“{task['title']}” (due {task['due_text']})"
        return f"“{task['title']}”"

    # -- main ---------------------------------------------------------------
    def reply(self, session_id: str, message: str) -> str:
        text = message.strip()
        lowered = text.lower()

        if re.search(r"^(hi|hello|hey|yo|good (morning|afternoon|evening))\b", lowered):
            return "Hi! Tell me what's on your plate — bills, appointments, errands, anything you keep forgetting."

        if re.search(r"\b(help|what can you do|how does this work)\b", lowered):
            return (
                "I can capture errands from plain language, list what's pending, reschedule things, "
                "and mark them done or cancelled. Try: “pay rent by Friday, call mum tomorrow”."
            )

        reschedule = re.search(
            r"^(?:please\s+)?(?:move|push|reschedule|shift|change)\s+(.+?)\s+(?:to|until|for)\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if reschedule:
            task, problem = self._find_one(reschedule.group(1).strip(" “”\"'"))
            if not task:
                return problem
            new_due = reschedule.group(2).strip(" .!?")
            if not parse_due(new_due, self.settings.calendar_timezone):
                return (
                    f"I couldn't understand the date “{new_due}”. "
                    "Try something like “Friday” or “next week”."
                )
            updated = self.errands.update(task["id"], due=new_due)
            return f"Done — moved {self._describe(updated)} to {new_due}."

        complete = re.search(
            r"^(?:please\s+)?(?:i\s+)?(?:finished|completed|did|done with|mark)\s+(.+?)"
            r"(?:\s+(?:as\s+)?done)?[.!]?$",
            text,
            re.IGNORECASE,
        )
        if complete:
            task, problem = self._find_one(complete.group(1).strip(" “”\"'"))
            if not task:
                return problem
            self.errands.set_status(task["id"], "done")
            return f"Nice — marked {self._describe(task)} as done."

        cancel = re.search(r"^(?:please\s+)?(?:cancel|drop|remove|delete)\s+(.+)$", text, re.IGNORECASE)
        if cancel:
            task, problem = self._find_one(cancel.group(1).strip(" “”\"'"))
            if not task:
                return problem
            self.errands.set_status(task["id"], "cancelled")
            return f"Cancelled {self._describe(task)}."

        due_question = re.search(
            r"\b(?:when|what time)\b.*\b(?:is|does)\b\s+(?:the\s+)?(.+?)(?:\s+due)?[?]?$",
            text,
            re.IGNORECASE,
        )
        if due_question:
            fragment = due_question.group(1).strip(" “”\"'")
            task, problem = self._find_one(fragment)
            if task:
                return f"{self._describe(task).capitalize()} is due {task.get('due_text') or 'with no date set'}."

        if re.search(
            r"\b(pending|on my plate|what do i have|my errands|show|list|due today|overdue|anything due)\b",
            lowered,
        ):
            pending = self.errands.list(status="pending")
            if not pending:
                return "Your list is clear — nothing pending right now."
            lines = [f"• {self._describe(task)}" for task in pending[:12]]
            extra = f"\n…and {len(pending) - 12} more." if len(pending) > 12 else ""
            return f"You have {len(pending)} pending:\n" + "\n".join(lines) + extra

        # A brain dump can contain several errands separated by new lines or semicolons.
        parts = [part.strip() for part in re.split(r"[\n;]+", text) if part.strip()]
        if len(parts) == 1 and text.count(",") >= 1:
            comma_parts = [part.strip() for part in text.split(",") if part.strip()]
            if len([part for part in comma_parts if self._parse_add(part)]) >= 2:
                parts = comma_parts
        added = self._add_many(parts) if len(parts) > 1 else []
        if added:
            names = ", ".join(f"“{task['title']}”" for task in added)
            return f"Added {len(added)} errands: {names}."

        parsed = self._parse_add(text)
        if parsed:
            task = self.errands.create(**parsed)
            return f"Added {self._describe(task)}."

        return (
            "I can add, list, reschedule, complete, or cancel errands. "
            "Try “add pay rent by Friday” or “what's pending?”"
        )


# --------------------------------------------------------------------- strands
class _Session:
    __slots__ = ("agent", "lock", "last_used", "day")

    def __init__(self, agent, day: str):
        self.agent = agent
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.day = day


class StrandsAssistant:
    mode = "bedrock"

    def __init__(self, settings: Settings, errands: ErrandService):
        self.settings = settings
        self.errands = errands
        self._sessions: dict[str, _Session] = {}
        self._sessions_lock = threading.Lock()
        self._model = self._build_model()
        self._tools = self._build_tools()

    # -- construction -------------------------------------------------------
    def _build_model(self):
        from strands.models.openai import OpenAIModel

        return OpenAIModel(
            client_args={
                "base_url": self.settings.bedrock_base_url,
                "api_key": self.settings.bedrock_api_key,
            },
            model_id=self.settings.bedrock_model_id,
            stream=False,
        )

    def _build_tools(self):
        from strands import tool

        errands = self.errands

        @tool
        def add_errand(title: str, due: str = None, notes: str = None) -> str:
            """Add one errand for the user.

            Args:
                title: Short description, e.g. "Pay electricity bill".
                due: The user's own due phrase, e.g. "Friday", "next week", "2026-11-03". Optional.
                notes: Extra detail. Optional.

            Returns:
                Confirmation with the errand id and resolved due date.
            """
            task = errands.create(title=title, due=due, notes=notes)
            resolved = ""
            if task.get("due_at"):
                resolved = f", resolved to {task['due_at']}"
            return f"Added '{task['title']}' (id {task['id']}, due: {task.get('due_text') or 'none'}{resolved})."

        @tool
        def list_errands(status: str = "pending") -> str:
            """List errands. Always call this before answering questions about current errands.

            Args:
                status: "pending", "done", "cancelled", or "all".

            Returns:
                One errand per line with id, title, due, status, and notes.
            """
            tasks = errands.list(status=status)
            if not tasks:
                return f"No errands with status '{status}'."
            lines = []
            for task in tasks:
                due = task.get("due_text") or task.get("due_at") or "no due date"
                notes = f" | notes: {task['notes']}" if task.get("notes") else ""
                lines.append(f"[{task['id']}] {task['title']} | due: {due} | {task['status']}{notes}")
            return "\n".join(lines)

        def _single(fragment: str):
            pending = errands.find_pending(fragment)
            if not pending:
                return None, f"No pending errand matches '{fragment}'."
            if len(pending) > 1:
                options = ", ".join(f"'{task['title']}' (id {task['id']})" for task in pending[:6])
                return None, f"Multiple pending errands match: {options}. Ask the user which one."
            return pending[0], None

        @tool
        def reschedule_errand(title_fragment: str, new_due: str) -> str:
            """Change the due date of an existing errand.

            Args:
                title_fragment: Words identifying the errand, e.g. "dentist".
                new_due: The user's new due phrase, e.g. "Friday", "tomorrow".

            Returns:
                Confirmation, or a message describing missing/ambiguous matches.
            """
            task, problem = _single(title_fragment)
            if not task:
                return problem
            updated = errands.update(task["id"], due=new_due)
            return f"Rescheduled '{updated['title']}' from {task.get('due_text') or 'no date'} to {new_due}."

        @tool
        def complete_errand(title_fragment: str) -> str:
            """Mark a pending errand as done.

            Args:
                title_fragment: Words identifying the errand.

            Returns:
                Confirmation, or a message describing missing/ambiguous matches.
            """
            task, problem = _single(title_fragment)
            if not task:
                return problem
            errands.set_status(task["id"], "done")
            return f"Marked '{task['title']}' as done."

        @tool
        def cancel_errand(title_fragment: str) -> str:
            """Cancel a pending errand the user no longer needs.

            Args:
                title_fragment: Words identifying the errand.

            Returns:
                Confirmation, or a message describing missing/ambiguous matches.
            """
            task, problem = _single(title_fragment)
            if not task:
                return problem
            errands.set_status(task["id"], "cancelled")
            return f"Cancelled '{task['title']}'."

        return [add_errand, list_errands, reschedule_errand, complete_errand, cancel_errand]

    def _new_agent(self):
        from strands import Agent

        return Agent(
            model=self._model,
            tools=self._tools,
            system_prompt=build_system_prompt(self.settings.calendar_timezone),
            callback_handler=None,
        )

    def _session(self, session_id: str) -> _Session:
        now = time.monotonic()
        with self._sessions_lock:
            self._evict(now)
            session = self._sessions.get(session_id)
            today = now_in(get_timezone(self.settings.calendar_timezone)).strftime("%Y-%m-%d")
            if session is None:
                session = _Session(self._new_agent(), today)
                self._sessions[session_id] = session
            elif session.day != today:
                # Refresh the prompt so the model knows today's real date.
                try:
                    session.agent.system_prompt = build_system_prompt(self.settings.calendar_timezone)
                except Exception:
                    pass
                session.day = today
            session.last_used = now
            return session

    def _evict(self, now: float) -> None:
        ttl = self.settings.session_ttl_hours * 3600
        stale = [key for key, session in self._sessions.items() if now - session.last_used > ttl]
        for key in stale:
            self._sessions.pop(key, None)
        while len(self._sessions) >= max(1, self.settings.max_sessions):
            oldest = min(self._sessions, key=lambda key: self._sessions[key].last_used)
            self._sessions.pop(oldest, None)

    # -- main ---------------------------------------------------------------
    def reply(self, session_id: str, message: str) -> str:
        session = self._session(session_id)
        with session.lock:
            try:
                result = session.agent(message)
            except Exception as exc:  # model/network failure
                logger.exception("Agent call failed")
                raise AssistantError(
                    "The concierge model is unavailable right now. Check the Bedrock key and try again."
                ) from exc
        text = str(result).strip()
        return text or "I did that, but I don't have anything to add."

    def reset(self, session_id: str) -> None:
        with self._sessions_lock:
            self._sessions.pop(session_id, None)


def build_assistant(settings: Settings, errands: ErrandService):
    if settings.assistant_mode == "demo":
        logger.info("Assistant running in demo mode (no BEDROCK_API_KEY set).")
        return DemoAssistant(settings, errands)
    try:
        assistant = StrandsAssistant(settings, errands)
        logger.info("Assistant running in Bedrock mode (%s).", settings.bedrock_model_id)
        return assistant
    except Exception as exc:
        logger.exception("Could not initialise the Bedrock assistant; falling back to demo mode: %s", exc)
        return DemoAssistant(settings, errands)
