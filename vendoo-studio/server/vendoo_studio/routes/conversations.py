from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import (
    BUSY_LISTING_STATUSES,
    ConversationRepo,
)
from vendoo_studio.models.conversation import Photo as PhotoModel, utcnow
from vendoo_studio.services.photos import delete_thumbnails

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# Sidebar thumbnails render at 40px, so 96px covers high-DPI screens.
COVER_THUMB_SIZE = 96


class ConversationCreate(BaseModel):
    title: str | None = None
    notes: str | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    notes: str | None
    status: str
    settled_at: str | None = None
    unsettled_at: str | None = None
    created_at: str
    updated_at: str
    cover_photo_url: str | None = None
    # Vendoo's own label for a bound item, and its image as a thumbnail fallback.
    vendoo_status: str | None = None
    vendoo_cover_url: str | None = None
    # What the sidebar filters on: the listing's own SKU and price, the Vendoo
    # labels it wears, and the marketplaces it is live on.
    sku: str | None = None
    price: float | None = None
    vendoo_labels: list[str] = []
    vendoo_marketplaces: list[str] = []
    # Vendoo's own time tracking for the item: when it was created, last
    # modified, last went live (a relist moves this) and sold, plus the listing
    # date per marketplace. "listed" drives the staleness filter and sort.
    vendoo_created_at: str | None = None
    vendoo_modified_at: str | None = None
    vendoo_listed_at: str | None = None
    vendoo_sold_at: str | None = None
    vendoo_listed_dates: dict[str, str] = {}
    vendoo_sold_dates: dict[str, str] = {}


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    text: str
    provider: str | None
    model: str | None
    created_at: str


class PhotoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    original_filename: str
    mime_type: str
    size_bytes: int
    display_order: int
    width: int | None
    height: int | None
    created_at: str
    url: str


@router.post("", response_model=ConversationResponse)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.create(title=body.title, notes=body.notes)
    return _conv_response(conv)


@router.get("", response_model=list[ConversationResponse])
def list_conversations(db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    repo.reconcile_job_statuses()
    covers = repo.cover_photo_ids()
    facets = repo.listing_facets()
    return [
        _conv_response(c, _extras(_cover_photo_url(covers.get(c.id)), facets.get(c.id)))
        for c in repo.list_all()
    ]


@router.get("/{conv_id}", response_model=ConversationResponse)
def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return _conv_response(conv, _extras_for(db, conv_id))


class ConversationUpdate(BaseModel):
    """Title and notes only: a listing's status is Vendoo's to report."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    notes: str | None = None


class DeleteConversationResponse(BaseModel):
    ok: bool
    deleted_jobs: int
    deleted_photos: int


@router.post("/{conv_id}/settle", response_model=ConversationResponse)
def settle_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.status in BUSY_LISTING_STATUSES:
        raise HTTPException(409, "Cannot settle a listing that is still in progress")
    return _conv_response(repo.settle(conv_id), _extras_for(db, conv_id))


@router.post("/{conv_id}/unsettle", response_model=ConversationResponse)
def unsettle_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return _conv_response(repo.unsettle(conv_id), _extras_for(db, conv_id))


class VendooLinkRequest(BaseModel):
    url_or_id: str


class VendooLinkResponse(BaseModel):
    conversation: ConversationResponse
    vendoo_item_id: str
    vendoo_url: str


@router.post("/{conv_id}/vendoo-link", response_model=VendooLinkResponse)
def link_vendoo_draft(conv_id: str, body: VendooLinkRequest, db: Session = Depends(get_db)):
    """Bind this Studio listing to an existing Vendoo draft via URL or item ID."""
    from vendoo_studio.models.job import Job
    from vendoo_studio.services.vendoo_import import merge_notes, parse_vendoo_draft_ref, vendoo_binding

    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    try:
        binding = parse_vendoo_draft_ref(body.url_or_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    item_id = binding["vendooItemId"]
    item_url = binding["vendooUrl"]
    other = repo.find_by_vendoo_item_id(item_id)
    if other and other.id != conv_id:
        title = other.title or "Untitled"
        raise HTTPException(
            409,
            f"That Vendoo draft is already linked to another listing ({title}).",
        )

    conv.notes = merge_notes(conv.notes, binding)
    conv.updated_at = utcnow()

    # Keep any existing jobs pointed at the same draft so Fields can refresh.
    jobs = (
        db.query(Job)
        .filter(Job.conversation_id == conv_id, Job.status != "cancelled")
        .all()
    )
    for job in jobs:
        job.vendoo_item_id = item_id
        job.vendoo_url = item_url

    db.commit()
    db.refresh(conv)
    linked = vendoo_binding(conv.notes)
    return VendooLinkResponse(
        conversation=_conv_response(conv, _extras_for(db, conv_id)),
        vendoo_item_id=linked.get("vendooItemId") or item_id,
        vendoo_url=linked.get("vendooUrl") or item_url,
    )


@router.patch("/{conv_id}")
def update_conversation(conv_id: str, body: ConversationUpdate, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    changed = False
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "Title cannot be empty")
        if title != (conv.title or ""):
            conv.title = title
            conv.updated_at = utcnow()
            changed = True
    if body.notes is not None:
        from vendoo_studio.services.vendoo_import import merge_notes, parse_notes
        incoming = parse_notes(body.notes)
        if incoming:
            conv.notes = merge_notes(conv.notes, incoming)
        else:
            conv.notes = body.notes
        changed = True
    if changed:
        db.commit()
        db.refresh(conv)
    return _conv_response(conv, _extras_for(db, conv_id))


@router.get("/{conv_id}/messages")
def get_messages(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    msgs = repo.get_messages(conv_id)
    return [_msg_response(m) for m in msgs]


class ActivityResponse(BaseModel):
    busy: bool
    items: list[str]
    message_count: int
    last_message_id: str | None


def _job_activity_label(job) -> str:
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    if is_schema_probe_job(job):
        return "Discovering fields in Chrome…"
    if job.status in ("queued", "awaiting_extension"):
        return "Vendoo draft waiting for Chrome…"
    return "Working on the Vendoo draft…"


@router.get("/{conv_id}/activity", response_model=ActivityResponse)
def get_activity(conv_id: str, db: Session = Depends(get_db)):
    """Everything still running for this listing — chat is only done when this is empty."""
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job
    from vendoo_studio.models.conversation import Message
    from vendoo_studio.services import activity
    from vendoo_studio.services.listing_completion import completion_running
    from vendoo_studio.services.streaming import active_generation

    items: list[str] = []
    run = active_generation(conv_id)
    if run is not None:
        items.append(run.last_status or "Generating listing…")
    items.extend(activity.running(conv_id))
    for job in db.query(Job).filter(Job.conversation_id == conv_id).all():
        if job.status in ACTIVE_JOB_STATUSES or completion_running(job.id):
            items.append(_job_activity_label(job))
    items = list(dict.fromkeys(items))

    messages = db.query(Message).filter(Message.conversation_id == conv_id)
    last = messages.order_by(Message.created_at.desc()).first()
    return ActivityResponse(
        busy=bool(items),
        items=items,
        message_count=messages.count(),
        last_message_id=last.id if last else None,
    )


async def cancel_conversation_jobs(db: Session, conv_id: str) -> int:
    """Cancel this listing's running Chrome/Vendoo jobs and their field repair."""
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job
    from vendoo_studio.models.protocol import ProtocolMessage
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.routes.extension import dispatch_queued_jobs, extension_manager
    from vendoo_studio.services.listing_completion import cancel_completion, completion_running

    jobs = [
        job
        for job in db.query(Job).filter(Job.conversation_id == conv_id).all()
        if job.status in ACTIVE_JOB_STATUSES or completion_running(job.id)
    ]
    for job in jobs:
        cancel_completion(job.id)
        if job.status not in ACTIVE_JOB_STATUSES:
            continue
        job.status = "cancelled"
        job.current_step = None
        db.commit()
        JobRepo(db).add_event(job.id, "cancelled")
        extension_manager.cancel_waits_for_job(job.id)
        await extension_manager.send_message(ProtocolMessage(
            type="job.cancel",
            job_id=job.id,
            payload={"job_id": job.id},
        ).model_dump(mode="json"))
    if jobs:
        await dispatch_queued_jobs()
    return len(jobs)


@router.get("/{conv_id}/photos")
def get_photos(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    return [_photo_response(p) for p in repo.get_photos(conv_id)]



def _wipe_conversation_contents(
    db: Session, conv_id: str, *, keep_photos: bool = False
) -> tuple[int, int]:
    import os as _os

    repo = ConversationRepo(db)
    photos = [] if keep_photos else repo.get_photos(conv_id)
    deleted_photos = len(photos)
    for photo in photos:
        filepath = Path(PHOTOS_DIR) / photo.stored_filename
        if filepath.exists():
            _os.remove(filepath)
        delete_thumbnails(photo.stored_filename)

    from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation
    from vendoo_studio.models.fill_log import FillLogEntry
    from vendoo_studio.models.job import Job, JobEvent
    from vendoo_studio.models.listing import Listing, ListingRevision
    from vendoo_studio.models.conversation import Message

    job_ids = [row[0] for row in db.query(Job.id).filter(Job.conversation_id == conv_id).all()]
    if job_ids:
        db.query(FieldObservation).filter(
            FieldObservation.diagnostic_run_id.in_(
                db.query(DiagnosticRun.id).filter(DiagnosticRun.job_id.in_(job_ids))
            )
        ).delete(synchronize_session=False)
        db.query(DiagnosticRun).filter(DiagnosticRun.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(FillLogEntry).filter(FillLogEntry.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(JobEvent).filter(JobEvent.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.conversation_id == conv_id).delete(synchronize_session=False)

    db.query(ListingRevision).filter(ListingRevision.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conv_id).delete(synchronize_session=False)
    if not keep_photos:
        db.query(PhotoModel).filter(PhotoModel.conversation_id == conv_id).delete(synchronize_session=False)
    return len(job_ids), deleted_photos


@router.delete("/{conv_id}/photos/{photo_id}")
def delete_photo(conv_id: str, photo_id: str, db: Session = Depends(get_db)):
    import os

    repo = ConversationRepo(db)
    photos = repo.get_photos(conv_id)
    target = next((p for p in photos if p.id == photo_id), None)
    if not target:
        raise HTTPException(404, "Photo not found")

    filepath = Path(PHOTOS_DIR) / target.stored_filename
    if filepath.exists():
        os.remove(filepath)
    delete_thumbnails(target.stored_filename)

    repo.delete_photo(conv_id, photo_id)
    return {"ok": True}


class ResetRequest(BaseModel):
    # Regenerate: drop chat, jobs and generated fields but keep photos and item
    # details, so the next generate starts from the same inputs as a new listing.
    keep_inputs: bool = False


@router.post("/{conv_id}/reset", response_model=ConversationResponse)
async def reset_conversation(
    conv_id: str, body: ResetRequest | None = None, db: Session = Depends(get_db)
):
    keep_inputs = bool(body and body.keep_inputs)
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    from vendoo_studio.repositories.queries import JobRepo, ListingRepo
    from vendoo_studio.services.streaming import stop_generation
    from vendoo_studio.services.hidden_fields import clear_listing_hidden_fields
    from vendoo_studio.services.listing_carryover import carryover_updates
    from vendoo_studio.services.vendoo_create import (
        LOOKUP_TIMEOUT_SEC,
        apply_label_display_names,
        label_display_map,
    )
    from vendoo_studio.services.vendoo_import import (
        merge_notes,
        parse_notes,
        split_vendoo_labels,
        vendoo_binding,
    )

    from vendoo_studio.services import activity

    stop_generation(conv_id, discard=True)
    # Post-generate field fills would otherwise write into the cleared chat.
    activity.cancel(conv_id)

    # Keep the Vendoo draft link across Clear; wipe only Studio form contents.
    binding = vendoo_binding(conv.notes)
    notes = conv.notes

    if keep_inputs:
        # Regenerate starts from Item Details, so the facts that only lived on
        # the listing — cost of goods, labels, internal notes, and the
        # measurements and flaws in the description — move there first.
        revisions = ListingRepo(db).get_revisions(conv_id)
        latest = dict(revisions[0].listing_json) if revisions else None
        label_job = next(
            (
                job
                for job in JobRepo(db).list_by_conversation(conv_id)
                if job.status != "cancelled"
            ),
            None,
        )
        # One bounded catalog read for both label lists: Regenerate must not sit
        # on a silent Chrome, and label names are a nicety, not the reset.
        latest_labels = latest.get("labels") if isinstance(latest, dict) else None
        label_names: dict[str, str] = {}
        if label_job and (
            latest_labels or split_vendoo_labels(parse_notes(notes).get("vendooLabels"))
        ):
            label_names = await label_display_map(label_job, timeout=LOOKUP_TIMEOUT_SEC)
        if label_names and isinstance(latest, dict) and latest.get("labels"):
            latest["labels"] = apply_label_display_names(latest["labels"], label_names)
        carried = carryover_updates(latest, parse_notes(notes))
        if carried:
            notes = merge_notes(notes, carried)
        # Fix opaque label ids already sitting in Item Details from an earlier import.
        if label_names:
            existing = split_vendoo_labels(parse_notes(notes).get("vendooLabels"))
            if existing:
                named = apply_label_display_names(existing, label_names)
                if named != existing:
                    notes = merge_notes(notes, {"vendooLabels": ", ".join(named)})

    # Stop Chrome fill/repair before the wipe deletes the job rows.
    await cancel_conversation_jobs(db, conv_id)

    _wipe_conversation_contents(db, conv_id, keep_photos=keep_inputs)
    db.expire_all()
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.title = "New Listing"
    if keep_inputs:
        conv.notes = notes
    else:
        conv.notes = merge_notes(None, binding) if binding else None
    conv.status = "draft"
    conv.settled_at = None
    conv.unsettled_at = None
    conv.updated_at = utcnow()
    if binding:
        # Blank revision so Fields / ensure-draft can reattach to the same Vendoo item.
        revision = ListingRepo(db).save_revision(conv_id, {}, source="reset")
        if keep_inputs:
            # Regenerate remounts the editor with photos still present. Without a
            # job row it looks like a fresh Link and auto-imports the draft —
            # that opens Chrome and walks every marketplace tab. Reattach Fields
            # here so remount never starts that scrape.
            item_id = str(binding.get("vendooItemId") or "").strip()
            item_url = str(binding.get("vendooUrl") or "").strip()
            if item_id and item_id.lower() not in {"new", "edit", "create"}:
                if not item_url:
                    item_url = f"https://web.vendoo.co/app/item/{item_id}"
                JobRepo(db).create(
                    conv_id=conv_id,
                    approved_revision_id=revision.id,
                    listing_snapshot={},
                    vendoo_item_id=item_id,
                    vendoo_url=item_url,
                    status="completed",
                    current_step="fields_applied",
                )
    db.commit()
    db.refresh(conv)
    clear_listing_hidden_fields(conv_id)
    return _conv_response(conv, _extras_for(db, conv_id))


@router.delete("/{conv_id}", response_model=DeleteConversationResponse)
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job

    active_jobs = db.query(Job).filter(
        Job.conversation_id == conv_id,
        Job.status.in_(ACTIVE_JOB_STATUSES),
    ).all()
    if active_jobs:
        raise HTTPException(400, "Cannot delete a listing with an active automation job")

    deleted_jobs, deleted_photos = _wipe_conversation_contents(db, conv_id)
    db.expire_all()
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    db.delete(conv)
    db.commit()
    return DeleteConversationResponse(ok=True, deleted_jobs=deleted_jobs, deleted_photos=deleted_photos)


def _msg_response(msg) -> dict:
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role,
        "text": msg.text,
        "provider": msg.provider,
        "model": msg.model,
        "created_at": msg.created_at.isoformat() if msg.created_at else "",
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _cover_photo_url(photo_id: str | None) -> str | None:
    return f"/api/photos/{photo_id}/thumb?size={COVER_THUMB_SIZE}" if photo_id else None


def _extras(cover_photo_url: str | None, facet: dict | None) -> dict:
    """The per-row fields the sidebar needs alongside the conversation itself."""
    return {
        "cover_photo_url": cover_photo_url,
        "sku": (facet or {}).get("sku"),
        "price": (facet or {}).get("price"),
    }


def _extras_for(db: Session, conv_id: str) -> dict:
    repo = ConversationRepo(db)
    return _extras(_cover_photo_url(repo.cover_photo_id(conv_id)), repo.listing_facet(conv_id))


def _vendoo_dates(notes: dict) -> dict:
    """Vendoo's time tracking for the row, as the sidebar and details read it."""
    dates = notes.get("vendooDates") if isinstance(notes.get("vendooDates"), dict) else {}

    def text(key: str) -> str | None:
        return str(dates.get(key) or "") or None

    def mapping(key: str) -> dict[str, str]:
        raw = dates.get(key)
        if not isinstance(raw, dict):
            return {}
        return {str(market): str(stamp) for market, stamp in raw.items() if stamp}

    return {
        "vendoo_created_at": text("created"),
        "vendoo_modified_at": text("modified"),
        "vendoo_listed_at": text("listed"),
        "vendoo_sold_at": text("sold"),
        "vendoo_listed_dates": mapping("listedByMarketplace"),
        "vendoo_sold_dates": mapping("soldByMarketplace"),
    }


def _conv_response(conv, extras: dict | None = None) -> ConversationResponse:
    from vendoo_studio.services.vendoo_import import parse_notes, split_vendoo_labels

    notes = parse_notes(conv.notes)
    row = extras or {}
    marketplaces = notes.get("vendooMarketplaces")
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        notes=conv.notes,
        status=conv.status,
        settled_at=_iso(conv.settled_at),
        unsettled_at=_iso(conv.unsettled_at),
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        cover_photo_url=row.get("cover_photo_url"),
        vendoo_status=str(notes.get("vendooStatus") or "") or None,
        vendoo_cover_url=str(notes.get("vendooCoverUrl") or "") or None,
        sku=row.get("sku"),
        price=row.get("price"),
        vendoo_labels=split_vendoo_labels(notes.get("vendooLabels")),
        vendoo_marketplaces=[str(m) for m in marketplaces] if isinstance(marketplaces, list) else [],
        **_vendoo_dates(notes),
    )


def _photo_response(photo) -> PhotoResponse:
    return PhotoResponse(
        id=photo.id,
        conversation_id=photo.conversation_id,
        original_filename=photo.original_filename,
        mime_type=photo.mime_type,
        size_bytes=photo.size_bytes,
        display_order=photo.display_order,
        width=photo.width,
        height=photo.height,
        created_at=photo.created_at.isoformat() if photo.created_at else "",
        url=f"/api/photos/{photo.id}",
    )
