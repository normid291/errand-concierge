"""Chat endpoint."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException, Request

from app.schemas import ChatRequest, ChatResponse
from app.services.assistant import AssistantError

router = APIRouter(tags=["chat"])

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _session_id(raw: str | None) -> str:
    if raw and SESSION_RE.fullmatch(raw):
        return raw
    return uuid.uuid4().hex


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request):
    assistant = request.app.state.assistant
    limit = request.app.state.settings.max_message_chars
    if len(payload.message) > limit:
        raise HTTPException(status_code=413, detail=f"Message is longer than the {limit}-character limit.")
    session_id = _session_id(payload.session_id)
    try:
        reply = assistant.reply(session_id, payload.message)
    except AssistantError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply, "session_id": session_id, "mode": assistant.mode}


@router.delete("/chat/{session_id}")
def reset_chat(session_id: str, request: Request):
    request.app.state.assistant.reset(session_id)
    return {"reset": session_id}
