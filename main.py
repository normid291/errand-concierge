"""
Errand Concierge - CLI demo loop.

Run with: python3 main.py
Type your errands/requests, type 'quit' to exit.
"""

import logging
import warnings

# Silence noisy internal warnings from the model client (e.g. "reasoningContent is not
# supported in multi-turn conversations") so the demo output stays clean.
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

from agent import agent

BANNER = """
=====================================
  Errand Concierge
  Dump your errands, I'll handle the rest.
  (type 'quit' to exit)
=====================================
"""


def main():
    print(BANNER)
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        response = agent(user_input)
        print(f"\nConcierge: {response}\n")


if __name__ == "__main__":
    main()
