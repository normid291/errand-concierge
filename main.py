"""Compatibility shim for the old CLI entry point (`python main.py`)."""

from app.cli import main

if __name__ == "__main__":
    main()
