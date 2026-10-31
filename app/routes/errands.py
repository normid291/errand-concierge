"""Errand CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ErrandCreate, ErrandList, ErrandOut, ErrandUpdate, TrashResponse
from app.services.errands import NotFoundError, ValidationError

router = APIRouter(prefix="/errands", tags=["errands"])


def _service(request: Request):
    return request.app.state.errands


@router.get("", response_model=ErrandList)
def list_errands(
    request: Request,
    status: str = Query(default="all", pattern="^(all|pending|done|cancelled)$"),
    q: str | None = Query(default=None, max_length=100),
):
    return {"errands": _service(request).list(status=status, query=q)}


@router.post("", response_model=ErrandOut, status_code=201)
def create_errand(payload: ErrandCreate, request: Request):
    try:
        return _service(request).create(title=payload.title, due=payload.due, notes=payload.notes)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trash", response_model=TrashResponse)
def list_trash(request: Request):
    return {"errands": request.app.state.repo.list_trash()}


@router.post("/trash/clear")
def clear_trash(request: Request):
    deleted = request.app.state.repo.clear_trash()
    return {"deleted": deleted}


@router.post("/trash/{trash_id}/restore", response_model=ErrandOut)
def restore_errand(trash_id: str, request: Request):
    try:
        return _service(request).restore(trash_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Trash entry not found") from exc


@router.delete("/trash/{trash_id}")
def delete_trash_entry(trash_id: str, request: Request):
    if not request.app.state.repo.delete_trash(trash_id):
        raise HTTPException(status_code=404, detail="Trash entry not found")
    return {"deleted": trash_id}


@router.get("/{errand_id}", response_model=ErrandOut)
def get_errand(errand_id: str, request: Request):
    try:
        return _service(request).get(errand_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Errand not found") from exc


@router.patch("/{errand_id}", response_model=ErrandOut)
def update_errand(errand_id: str, payload: ErrandUpdate, request: Request):
    fields = payload.model_dump(exclude_unset=True)
    try:
        return _service(request).update(errand_id, **fields)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Errand not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{errand_id}")
def delete_errand(errand_id: str, request: Request):
    try:
        _service(request).delete(errand_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Errand not found") from exc
    return {"deleted": errand_id}


@router.post("/{errand_id}/complete", response_model=ErrandOut)
def complete_errand(errand_id: str, request: Request):
    try:
        return _service(request).set_status(errand_id, "done")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Errand not found") from exc


@router.post("/{errand_id}/cancel", response_model=ErrandOut)
def cancel_errand(errand_id: str, request: Request):
    try:
        return _service(request).set_status(errand_id, "cancelled")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Errand not found") from exc


@router.post("/{errand_id}/reopen", response_model=ErrandOut)
def reopen_errand(errand_id: str, request: Request):
    try:
        return _service(request).set_status(errand_id, "pending")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Errand not found") from exc
