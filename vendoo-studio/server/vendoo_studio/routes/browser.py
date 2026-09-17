from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
from vendoo_studio.repositories.queries import JobRepo
from vendoo_studio.services import browser_bridge
from vendoo_studio.services.browser_bridge import BrowserBridgeError

router = APIRouter(prefix="/api/jobs/{job_id}/browser", tags=["browser"])



class OpenRequest(BaseModel):
    marketplace: str | None = Field(default=None, max_length=20)


class InputEvent(BaseModel):
    kind: Literal["mouse", "key", "text"]
    type: str | None = Field(default=None, max_length=20)
    x_ratio: float | None = Field(default=None, ge=0, le=1)
    y_ratio: float | None = Field(default=None, ge=0, le=1)
    button: str | None = Field(default=None, max_length=10)
    buttons: int | None = Field(default=None, ge=0, le=31)
    click_count: int | None = Field(default=None, ge=0, le=3)
    delta_x: float | None = Field(default=None, ge=-2000, le=2000)
    delta_y: float | None = Field(default=None, ge=-2000, le=2000)
    modifiers: int | None = Field(default=None, ge=0, le=15)
    key: str | None = Field(default=None, max_length=20)
    code: str | None = Field(default=None, max_length=30)
    text: str | None = Field(default=None, max_length=2000)


class InputRequest(BaseModel):
    events: list[InputEvent] = Field(max_length=40)


class PickRequest(BaseModel):
    x_ratio: float = Field(ge=0, le=1)
    y_ratio: float = Field(ge=0, le=1)


class ActRequest(BaseModel):
    action: Literal["click", "type", "press", "scroll", "wait"]
    selector: str | None = Field(default=None, max_length=300)
    x_ratio: float | None = Field(default=None, ge=0, le=1)
    y_ratio: float | None = Field(default=None, ge=0, le=1)
    text: str | None = Field(default=None, max_length=2000)
    key: str | None = Field(default=None, max_length=20)
    delta_x: float | None = Field(default=None, ge=-2000, le=2000)
    delta_y: float | None = Field(default=None, ge=-2000, le=2000)
    ms: int | None = Field(default=None, ge=0, le=15000)


class DirectTarget(BaseModel):
    marketplace: str = Field(max_length=20)
    field: str = Field(min_length=1, max_length=120)
    value: str | None = Field(default=None, max_length=2000)
    selector: str | None = Field(default=None, max_length=300)
    options: list[str] = Field(default_factory=list, max_length=200)
    account_managed: bool = False


class DirectRequest(BaseModel):
    note: str = Field(default="", max_length=2000)
    targets: list[DirectTarget] = Field(min_length=1, max_length=60)


def _job(db: Session, job_id: str):
    job = JobRepo(db).get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _reply(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(409, result.get("error") or "The Vendoo browser could not do that.")
    return result


@router.post("/open")
async def open_browser(job_id: str, body: OpenRequest, db: Session = Depends(get_db)):
    job = _job(db, job_id)
    try:
        return _reply(await browser_bridge.open_session(job, body.marketplace))
    except BrowserBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/close")
async def close_browser(job_id: str, db: Session = Depends(get_db)):
    job = _job(db, job_id)
    try:
        return await browser_bridge.close_session(job)
    except BrowserBridgeError:
        return {"ok": True}


@router.post("/input")
async def browser_input(job_id: str, body: InputRequest, db: Session = Depends(get_db)):
    job = _job(db, job_id)
    events = [event.model_dump(exclude_none=True) for event in body.events]
    return {"sent": await browser_bridge.send_input(job, events)}


@router.post("/pick")
async def pick_field(job_id: str, body: PickRequest, db: Session = Depends(get_db)):
    job = _job(db, job_id)
    try:
        return _reply(await browser_bridge.pick(job, body.x_ratio, body.y_ratio))
    except BrowserBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/snapshot")
async def snapshot_fields(job_id: str, db: Session = Depends(get_db)):
    job = _job(db, job_id)
    try:
        return _reply(await browser_bridge.snapshot(job))
    except BrowserBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/act")
async def act(job_id: str, body: ActRequest, db: Session = Depends(get_db)):
    """Agent actions on the open draft. Publish and delete controls are refused in Chrome."""
    job = _job(db, job_id)
    try:
        return _reply(await browser_bridge.act(job, body.model_dump(exclude_none=True)))
    except BrowserBridgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/direct")
async def direct_fill(job_id: str, body: DirectRequest, db: Session = Depends(get_db)):
    from vendoo_studio.routes.extension import extension_manager
    from vendoo_studio.services.browser_direct import direct_fill as run_direct_fill
    from vendoo_studio.services.listing_provider import get_listing_provider

    job = _job(db, job_id)
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(409, "Studio is already working on this draft. Wait for it to finish.")
    if not extension_manager.connected:
        raise HTTPException(400, "Connect Chrome to fill the Vendoo draft.")
    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(400, "Sign in with ChatGPT in Settings, or add a MiMo API key.")
    targets = [target.model_dump() for target in body.targets]
    return await run_direct_fill(db, job, provider, targets, body.note)
