"""Create Vendoo items through Vendoo's own item API — no form filling.

``create`` works on a conversation, not a job: every existing job path queues
the form-filler, which would create the Vendoo item itself. The job this route
makes is held in ``dispatched`` while it runs, so the Send queue waits for it
instead of picking it up.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.vendoo_create import VendooCreateError

router = APIRouter(tags=["vendoo-api"])

CREATE_STEP = "vendoo_api_create"
CREATED_STEP = "vendoo_api_created"


class ProbeRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list, max_length=50)
    reset: bool = False


class ProbeResponse(BaseModel):
    ok: bool
    learned_from: int
    item_count: int
    fields: list[str]
    failures: list[dict] = []


class ItemsRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list, min_length=1, max_length=20)


class CategorySearchRequest(BaseModel):
    text: str
    marketplace_id: str = "ebay"


class SpecificsRequest(BaseModel):
    category_id: str
    marketplace_id: str = "ebay"
    path: list[str] = Field(default_factory=list)
    extras: dict = Field(default_factory=dict)


class CreateResponse(BaseModel):
    ok: bool
    job_id: str
    item_id: str
    url: str
    unresolved: list[dict] = []
    diff: list[dict] = []


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BrowserBridgeError):
        return HTTPException(400, str(exc))
    if isinstance(exc, VendooCreateError):
        return HTTPException(502, str(exc))
    return HTTPException(500, str(exc))


def _known_item_ids(db: Session) -> list[str]:
    from vendoo_studio.services.vendoo_import import vendoo_binding

    ids: list[str] = []
    for conv in ConversationRepo(db).list_all():
        bound = vendoo_binding(conv.notes).get("vendooItemId")
        if bound and bound not in ids:
            ids.append(bound)
    for job in JobRepo(db).list_all():
        if job.vendoo_item_id and job.vendoo_item_id not in ids:
            ids.append(job.vendoo_item_id)
    return ids


@router.post("/api/vendoo-api/probe", response_model=ProbeResponse)
async def probe(body: ProbeRequest, db: Session = Depends(get_db)):
    """Learn Vendoo's condition/colour encodings from the user's own items.

    With no ids, reads every Vendoo item Studio already knows about.
    """
    from vendoo_studio.services.vendoo_create import probe_schema

    item_ids = list(body.item_ids) or _known_item_ids(db)
    if not item_ids:
        raise HTTPException(400, "No Vendoo items to learn from yet. Pass item_ids or import a draft first.")
    try:
        out = await probe_schema(SimpleNamespace(id=None), item_ids[:50], reset=body.reset)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    schema = out["schema"]
    return ProbeResponse(
        ok=True,
        learned_from=out["learned_from"],
        item_count=int(schema.get("item_count") or 0),
        fields=sorted((schema.get("fields") or {}).keys()),
        failures=out["failures"],
    )


@router.post("/api/vendoo-api/items")
async def read_items(body: ItemsRequest):
    """Read raw Vendoo items back, unmodified.

    ``probe`` only reports the encodings it learned; comparing a hand-built
    item against one Vendoo's own form wrote needs the untouched documents.
    """
    from vendoo_studio.services.vendoo_create import run_ops

    ops = [{"op": "get_item", "item_id": item_id, "throttle_ms": 250} for item_id in body.item_ids]
    try:
        reply = await run_ops(SimpleNamespace(id=None), ops)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    return {
        "ok": True,
        "items": {
            r.get("item_id"): r.get("item")
            for r in reply.get("results", [])
            if r.get("op") == "get_item"
        },
    }


@router.post("/api/vendoo-api/category-search")
async def category_search(body: CategorySearchRequest):
    """Raw ``/api/category/search`` hits, so a leaf's full shape stays visible."""
    from vendoo_studio.services.vendoo_create import run_ops

    try:
        reply = await run_ops(
            SimpleNamespace(id=None),
            [{"op": "category_search", "text": body.text, "marketplace_id": body.marketplace_id}],
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    hit = next((r for r in reply.get("results", []) if r.get("op") == "category_search"), {})
    return {"ok": True, "leaf": hit.get("leaf"), "matches": hit.get("matches", [])}


@router.post("/api/vendoo-api/category-specifics")
async def category_specifics(body: SpecificsRequest):
    """The field schema Vendoo's own forms render a category from."""
    from vendoo_studio.services.vendoo_create import run_ops

    try:
        reply = await run_ops(
            SimpleNamespace(id=None),
            [{
                "op": "category_specifics",
                "category_id": body.category_id,
                "marketplace_id": body.marketplace_id,
                "path": body.path,
                "extras": body.extras,
            }],
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    hit = next((r for r in reply.get("results", []) if r.get("op") == "category_specifics"), {})
    raw = hit.get("specifics")
    # Cache it the same way the create path does, so /api/catalog/fields can
    # serve this category without another Chrome round trip.
    from vendoo_studio.services.category_fields import save_fields
    from vendoo_studio.services.vendoo_specifics import normalize_specifics

    specs = normalize_specifics(raw)
    if specs:
        save_fields(body.marketplace_id, body.category_id, specs)
    return {"ok": True, "cached": bool(specs), "specifics": raw}


@router.post("/api/conversations/{conv_id}/vendoo-api/create", response_model=CreateResponse)
async def create(conv_id: str, db: Session = Depends(get_db)):
    """Create this conversation's latest listing as a Vendoo draft."""
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.services.job_snapshot import prepare_listing_snapshot
    from vendoo_studio.services.vendoo_create import create_item
    from vendoo_studio.services.vendoo_import import merge_notes, vendoo_binding

    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    bound = vendoo_binding(conv.notes).get("vendooItemId")
    if bound:
        raise HTTPException(409, f"This listing is already bound to Vendoo item {bound}")
    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions:
        raise HTTPException(400, "No listing yet. Generate or edit a listing first.")
    photos = conv_repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "Add at least one photo first.")

    job_repo = JobRepo(db)
    if job_repo.get_running():
        raise HTTPException(409, "Chrome is busy with another Vendoo job. Try again when it finishes.")
    if any(job.status in ACTIVE_JOB_STATUSES for job in job_repo.list_by_conversation(conv_id)):
        raise HTTPException(409, "This listing is already queued or sending to Vendoo.")

    snapshot = prepare_listing_snapshot(db, conv, revisions[0].listing_json)
    job = job_repo.create(
        conv_id=conv_id,
        approved_revision_id=revisions[0].id,
        listing_snapshot=snapshot,
        status="dispatched",
        current_step=CREATE_STEP,
    )
    try:
        out = await create_item(job, snapshot, photos)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        job_repo.update_status(job.id, "failed", CREATE_STEP, error=str(exc))
        job_repo.add_event(job.id, "vendoo_api_create_failed", CREATE_STEP, {"error": str(exc)})
        raise _http_error(exc) from exc

    conv.notes = merge_notes(conv.notes, {"vendooItemId": out["item_id"], "vendooUrl": out["url"]})
    db.commit()
    job_repo.update_status(
        job.id, "completed", CREATED_STEP, vendoo_item_id=out["item_id"], vendoo_url=out["url"]
    )
    job_repo.add_event(job.id, "vendoo_api_created", CREATED_STEP, {
        "item_id": out["item_id"],
        "unresolved": out["unresolved"],
        "diff": out["diff"],
    })
    if out.get("stored"):
        job_repo.save_vendoo_draft(job.id, item=out["stored"], item_id=out["item_id"], url=out["url"], source="api")
    return CreateResponse(
        ok=True,
        job_id=job.id,
        item_id=out["item_id"],
        url=out["url"],
        unresolved=out["unresolved"],
        diff=out["diff"],
    )
