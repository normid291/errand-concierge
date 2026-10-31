"""Pydantic request/response models (the HTTP contract)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal["pending", "done", "cancelled"]


class ErrandOut(BaseModel):
    id: str
    title: str
    notes: str | None = None
    due_text: str | None = None
    due_at: str | None = None
    status: Status
    created_at: str
    updated_at: str
    completed_at: str | None = None
    cancelled_at: str | None = None
    calendar_event_id: str | None = None
    deleted_at: str | None = None


class ErrandCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("title", "due", "notes")
    @classmethod
    def strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ErrandUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("title", "due", "notes")
    @classmethod
    def strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=80)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be empty")
        return value


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    mode: Literal["demo", "bedrock"]


class Counts(BaseModel):
    pending: int
    done: int
    cancelled: int
    total: int
    overdue: int
    due_today: int


class TrashEntry(BaseModel):
    """A deleted errand snapshot. Legacy imports may be incomplete, so most
    fields are optional on purpose."""

    id: str
    title: str
    notes: str | None = None
    due_text: str | None = None
    due_at: str | None = None
    status: Status | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    cancelled_at: str | None = None
    calendar_event_id: str | None = None
    deleted_at: str | None = None


class TrashResponse(BaseModel):
    errands: list[TrashEntry]


class ErrandList(BaseModel):
    errands: list[ErrandOut]


class IntegrationStatus(BaseModel):
    connected: bool
    email: str | None = None
    configured: bool = False


class AppConfig(BaseModel):
    mode: Literal["demo", "bedrock"]
    google_configured: bool
    calendar_timezone: str
    app_name: str = "Errand Concierge"
