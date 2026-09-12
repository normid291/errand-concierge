"""
Errand Concierge - backend API.

Run with: python3 backend.py
Serves the agent + task storage over HTTP for the custom frontend (index.html).
"""

import logging
import warnings

logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
from datetime import datetime

from agent import agent
import storage
import calendar_tools
from integrations_routes import router as integrations_router

app = FastAPI(title="Errand Concierge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(integrations_router)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")
    response = agent(req.message)
    return ChatResponse(reply=str(response))


@app.get("/api/errands")
def get_errands(status: str = "all"):
    filter_status = None if status == "all" else status
    tasks = storage.list_tasks(status=filter_status)
    tasks_sorted = sorted(tasks, key=lambda t: t.get("created_at", ""), reverse=True)
    return {"errands": tasks_sorted}


@app.get("/api/errands/trash")
def get_trash():
    return {"errands": storage.list_deleted_tasks()}


@app.delete("/api/errands/{task_id}")
def delete_errand_endpoint(task_id: str):
    tasks = storage.list_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task and task.get("calendar_event_id"):
        calendar_tools.delete_calendar_event(task["calendar_event_id"])

    if task:
        storage.log_deleted_task(task)

    deleted = storage.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Errand not found")
    return {"deleted": task_id}


@app.post("/api/errands/{task_id}/complete")
def complete_errand_endpoint(task_id: str):
    task = storage.update_task(task_id, status="done", completed_at=datetime.now().isoformat())
    if not task:
        raise HTTPException(status_code=404, detail="Errand not found")
    return task


@app.post("/api/errands/{task_id}/cancel")
def cancel_errand_endpoint(task_id: str):
    task = storage.update_task(task_id, status="cancelled", cancelled_at=datetime.now().isoformat())
    if not task:
        raise HTTPException(status_code=404, detail="Errand not found")
    if task.get("calendar_event_id"):
        calendar_tools.delete_calendar_event(task["calendar_event_id"])
    return task


@app.post("/api/errands/{task_id}/reopen")
def reopen_errand_endpoint(task_id: str):
    task = storage.update_task(task_id, status="pending", completed_at=None, cancelled_at=None)
    if not task:
        raise HTTPException(status_code=404, detail="Errand not found")
    return task


# Serve the custom frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
