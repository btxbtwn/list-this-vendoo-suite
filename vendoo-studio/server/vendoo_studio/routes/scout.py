from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.database import get_db
from vendoo_studio.models.scout import ScoutCheck
from vendoo_studio.services import scout
from vendoo_studio.services.photos import process_bytes

router = APIRouter(prefix="/api/scout", tags=["scout"])


class ScoutCheckResponse(BaseModel):
    id: str
    status: str
    asking_price: float | None
    photo_urls: list[str]
    title: str | None
    estimate: float | None
    comps_count: int | None
    comps: str | None
    error: str | None
    decision: str | None
    conversation_id: str | None
    sold_price: float | None
    created_at: str | None
    net: float | None
    pay_up_to: float | None
    profit: float | None
    verdict: str | None


class ScoutTrackRecord(BaseModel):
    checks: int
    bought: int
    sold: int
    median_ratio: float | None
    close: int


class ScoutResponse(BaseModel):
    checks: list[ScoutCheckResponse]
    track_record: ScoutTrackRecord


class AskingPriceUpdate(BaseModel):
    asking_price: float | None = Field(None, ge=0)


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(bought|passed)$")


def _check(db: Session, check_id: str) -> ScoutCheck:
    check = db.get(ScoutCheck, check_id)
    if check is None:
        raise HTTPException(404, "Check not found")
    return check


def _response(db: Session, check: ScoutCheck) -> ScoutCheckResponse:
    return ScoutCheckResponse.model_validate(scout.to_dict(check, scout.outcomes(db).get(check.id)))


@router.get("", response_model=ScoutResponse)
def list_checks(db: Session = Depends(get_db)):
    sold = scout.outcomes(db)
    return ScoutResponse(
        checks=[ScoutCheckResponse.model_validate(scout.to_dict(c, sold.get(c.id))) for c in scout.recent(db)],
        track_record=ScoutTrackRecord.model_validate(scout.track_record(db, sold)),
    )


@router.post("", response_model=ScoutCheckResponse)
async def create_check(
    files: list[UploadFile] = File(...),
    asking_price: float | None = Form(None, ge=0),
    db: Session = Depends(get_db),
):
    if len(files) > scout.MAX_PHOTOS:
        raise HTTPException(400, f"Up to {scout.MAX_PHOTOS} photos per check")
    photos = []
    for upload in files:
        try:
            photos.append(process_bytes(await upload.read(), upload.filename, upload.content_type))
        except ValueError as exc:
            raise HTTPException(400, f"{upload.filename or 'Photo'}: {exc}") from exc
    check = scout.create_check(db, photos, asking_price)
    scout.start(check.id)
    return _response(db, check)


@router.get("/{check_id}", response_model=ScoutCheckResponse)
def get_check(check_id: str, db: Session = Depends(get_db)):
    return _response(db, _check(db, check_id))


@router.patch("/{check_id}", response_model=ScoutCheckResponse)
def update_check(check_id: str, body: AskingPriceUpdate, db: Session = Depends(get_db)):
    check = scout.set_asking_price(db, _check(db, check_id), body.asking_price)
    return _response(db, check)


@router.post("/{check_id}/decision", response_model=ScoutCheckResponse)
def decide(check_id: str, body: DecisionRequest, db: Session = Depends(get_db)):
    check = _check(db, check_id)
    if check.status != "done" and body.decision == "bought":
        raise HTTPException(409, "Wait for the check to finish")
    return _response(db, scout.decide(db, check, body.decision))


@router.get("/{check_id}/photos/{index}")
def serve_photo(check_id: str, index: int, db: Session = Depends(get_db)):
    check = _check(db, check_id)
    if not 0 <= index < len(check.photos or []):
        raise HTTPException(404, "Photo not found")
    path = Path(PHOTOS_DIR) / check.photos[index]
    if not path.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path)
