"""Interactive terminal client: `python -m app.cli`."""

from __future__ import annotations

import uuid

from app.config import Settings
from app.factory import create_app
from app.services.assistant import AssistantError

BANNER = """
Errand Concierge — terminal mode
Type an errand or question. 'quit' to exit.
"""


def main() -> None:
    app = create_app(Settings.load())
    assistant = app.state.assistant
    session_id = uuid.uuid4().hex
    print(BANNER)
    print(f"Assistant mode: {assistant.mode}\n")

    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return
        if not message:
            continue
        if message.lower() in {"quit", "exit", "q"}:
            print("Goodbye!")
            return
        try:
            reply = assistant.reply(session_id, message)
        except AssistantError as exc:
            print(f"\nConcierge: {exc}\n")
            continue
        print(f"\nConcierge: {reply}\n")


if __name__ == "__main__":
    main()
