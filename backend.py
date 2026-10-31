#!/usr/bin/env python3
"""Compatibility entry point.

Kept so existing deployments whose start command is `python backend.py`
continue to work. New setups should use `uvicorn app.main:app`.
"""

import os

import uvicorn

from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
