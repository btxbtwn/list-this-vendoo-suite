from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import (
    BUSY_LISTING_STATUSES,
    ConversationRepo,
    ListingRepo,
)
from vendoo_studio.models.conversation import utcnow
from vendoo_studio.services import boxes
from vendoo_studio.services.listing_copy import CopyRequest
from vendoo_studio.services.listing_delete import ListingBusy, delete_listing, wipe_contents
from vendoo_studio.services.photos import cover_thumb_url, delete_photo_files, photo_url

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# Sidebar thumbnails render at 40px, so 96px covers high-DPI screens.


class ConversationCreate(BaseModel):
    title: str | None = None
    notes: str | None = None
    box_id: str | None = None


class ConversationSummary(BaseModel):
    """One inventory row. The sidebar polls the whole inventory, so the seller's
    notes stay out: they are most of the payload and only the open listing reads them."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    status: str
    # The wholesale box this item came out of.
    box_id: str | None = None
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
    # Marketplaces Anteroom published directly. Vendoo may still call the item a draft.
    direct_marketplaces: list[str] = []
    # Marketplaces Anteroom delisted directly. Vendoo may still call the item listed there.
    removed_marketplaces: list[str] = []
    # Units sold on Anteroom's sales ledger, and the most the item was offered
    # with. An Active row with some sold reads "1 of 3 sold".
    units_sold: int = 0
    quantity: int | None = None
    # Each marketplace listing's own page, where Vendoo recorded one.
    vendoo_listing_urls: dict[str, str] = {}
    # Vendoo's own time tracking for the item: when it was created, last
    # modified, last went live (a relist moves this) and sold, plus the listing
    # date per marketplace. "listed" drives the staleness filter and sort.
    vendoo_created_at: str | None = None
    vendoo_modified_at: str | None = None
    vendoo_listed_at: str | None = None
    vendoo_sold_at: str | None = None
    vendoo_listed_dates: dict[str, str] = {}
    vendoo_sold_dates: dict[str, str] = {}
    # When Studio last wrote this listing onto its Vendoo item. A marketplace
    # whose listing date is older than this is still showing the copy from
    # before that write, and only a delist + relist in Vendoo replaces it.
    vendoo_form_updated_at: str | None = None
    # Edited here since Studio and Vendoo were last level: the Vendoo form does
    # not have this version yet, so Update Vendoo is the step that is owed.
    unsent_edits: bool = False
    # The marketplaces that write left on old copy. Kept rather than re-derived
    # so the reminder survives the delist, when the item is live nowhere.
    vendoo_relist_pending: list[str] = []
    # False for modern resale: Etsy removes those, so Send leaves its form
    # empty and no reminder asks for an Etsy relist.
    etsy_eligible: bool = True


class ConversationResponse(ConversationSummary):
    notes: str | None


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
    edits: dict | None = None
    marketplace: str | None = None


@router.post("", response_model=ConversationResponse)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    if body.box_id and boxes.get_box(db, body.box_id) is None:
        raise HTTPException(404, "Box not found")
    conv = repo.create(title=body.title, notes=body.notes, box_id=body.box_id)
    return _conv_response(conv)


@router.get("", response_model=list[ConversationSummary])
def list_conversations(db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    repo.reconcile_job_statuses()
    covers = repo.cover_photos()
    facets = repo.listing_facets()
    revisions = repo.current_revision_ids()
    conversations = repo.list_all()
    unsent = _unsent_edits(db, conversations, revisions)
    from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo

    records = MarketplaceListingRepo(db)
    live = records.live_marketplaces()
    links = records.listing_urls()
    from vendoo_studio.services.item_status import sold_units

    sold = sold_units(db, conversations)
    return [
        _conv_response(c, _extras(
            _cover_photo_url(covers.get(c.id)), facets.get(c.id), revisions.get(c.id), c.id in unsent,
            live.get(c.id, []), links.get(c.id, {}), sold.get(c.id),
        ))
        for c in conversations
    ]


class DuplicateVendooListing(BaseModel):
    id: str
    title: str


class DuplicateVendooLink(BaseModel):
    vendoo_item_id: str
    vendoo_url: str
    listings: list[DuplicateVendooListing]


@router.get("/vendoo-link-duplicates", response_model=list[DuplicateVendooLink])
def duplicate_vendoo_links(db: Session = Depends(get_db)):
    return ConversationRepo(db).duplicate_vendoo_links()


@router.get("/{conv_id}", response_model=ConversationResponse)
def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return _conv_response(conv, _extras_for(db, conv_id))


@router.get("/{conv_id}/copy-preview")
def preview_copy(conv_id: str, response: Response, db: Session = Depends(get_db)):
    from vendoo_studio.services import listing_copy

    response.headers["Cache-Control"] = "no-store"
    try:
        return listing_copy.preview(db, conv_id)
    except listing_copy.CopyError as exc:
        raise HTTPException(exc.status, str(exc), headers={"Cache-Control": "no-store"}) from exc


@router.post("/{conv_id}/copy", response_model=ConversationResponse)
def copy_conversation(conv_id: str, body: CopyRequest, db: Session = Depends(get_db)):
    from vendoo_studio.services import listing_copy

    try:
        new_id = listing_copy.create_copy(db, conv_id, body)
    except listing_copy.CopyError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return _conv_response(ConversationRepo(db).get(new_id), _extras_for(db, new_id))


@router.get("/{conv_id}/copy-result/{request_id}", response_model=ConversationResponse)
def copy_result(conv_id: str, request_id: str, response: Response, db: Session = Depends(get_db)):
    from vendoo_studio.services import listing_copy

    response.headers["Cache-Control"] = "no-store"
    try:
        new_id = listing_copy.copy_result(db, conv_id, request_id)
    except listing_copy.CopyError as exc:
        raise HTTPException(exc.status, str(exc), headers={"Cache-Control": "no-store"}) from exc
    return _conv_response(ConversationRepo(db).get(new_id), _extras_for(db, new_id))


class ConversationUpdate(BaseModel):
    """Title, notes and box only: a listing's status is Vendoo's to report."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    notes: str | None = None
    # Null takes the listing out of its box; leaving it out changes nothing.
    box_id: str | None = None


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
    other = repo.find_by_vendoo_item_id(item_id, exclude_conv_id=conv_id)
    if other:
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
    renamed = False
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "Title cannot be empty")
        renamed = title != (conv.title or "")
        if renamed:
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
    if renamed:
        from vendoo_studio.services.vendoo_import import merge_notes

        # A listing the seller renamed keeps that name when the listing saves
        # or regenerates, instead of following the listing's title.
        conv.notes = merge_notes(conv.notes, {"titlePinned": True})
    if "box_id" in body.model_fields_set and body.box_id != conv.box_id:
        try:
            boxes.assign_box(db, conv, body.box_id)
        except LookupError as exc:
            raise HTTPException(404, "Box not found") from exc
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
    # The latest state of each parallel agent in this listing's current
    # generation, in the same shape as the generate stream's ``agent`` events.
    # Marketplace fields are filled after that stream ends; this is how the
    # client still sees those agents.
    agents: list[dict] = []
    locked_fields: list[str] = []


def _job_activity_label(job) -> str:
    from vendoo_studio.services.schema_probe import is_schema_probe_job

    if is_schema_probe_job(job):
        return "Discovering fields in Chrome…"
    if str(job.current_step or "").startswith("native_"):
        from vendoo_studio.services.native_marketplaces import NAMES, STEP_LABEL

        _, marketplace, step = str(job.current_step).split("_", 2)
        return f"{NAMES.get(marketplace, marketplace)}: {STEP_LABEL.get(step, 'Working')}…"
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
    # Polled about once a second per open listing: read only ids and statuses,
    # and load a job (and its listing snapshot) only when it is still running.
    jobs = db.query(Job.id, Job.status).filter(Job.conversation_id == conv_id).all()
    for job_id, status in jobs:
        if status in ACTIVE_JOB_STATUSES or completion_running(job_id):
            job = db.get(Job, job_id)
            if job is not None:
                items.append(_job_activity_label(job))
    items = list(dict.fromkeys(items))

    message_count = (
        db.query(func.count(Message.id)).filter(Message.conversation_id == conv_id).scalar() or 0
    )
    last_id = (
        db.query(Message.id)
        .filter(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .scalar()
    )
    return ActivityResponse(
        busy=bool(items),
        items=items,
        message_count=message_count,
        last_message_id=last_id,
        agents=activity.agents(conv_id),
        locked_fields=activity.locked_fields(conv_id),
    )


@router.get("/{conv_id}/generation-timings")
def get_generation_timings(conv_id: str, limit: int = 20, db: Session = Depends(get_db)):
    """Seconds per stage of this listing's recent generations, newest first."""
    from vendoo_studio.services.generation_timing import for_conversation

    if not ConversationRepo(db).get(conv_id):
        raise HTTPException(404, "Conversation not found")
    return for_conversation(db, conv_id, limit=max(1, min(limit, 100)))


async def cancel_conversation_jobs(db: Session, conv_id: str) -> int:
    """Cancel this listing's running Chrome/Vendoo jobs and their field repair."""
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job
    from vendoo_studio.models.protocol import ProtocolMessage
    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.extension_connection import dispatch_queued_jobs, extension_manager
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
        if str(job.current_step or "").startswith("native_"):
            from vendoo_studio.services import native_marketplaces

            # Stops at its next safe point; the record says what happened.
            await native_marketplaces.cancel_job(db, job)
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
def get_photos(conv_id: str, marketplace: str | None = None, db: Session = Depends(get_db)):
    """The item's photos, or with ``marketplace`` the photos added on that marketplace's form only."""
    repo = ConversationRepo(db)
    photos = repo.get_photos(conv_id) if marketplace is None else [
        p for p in repo.get_all_photos(conv_id) if p.marketplace == marketplace]
    return [_photo_response(p) for p in photos]


@router.delete("/{conv_id}/photos/{photo_id}")
def delete_photo(conv_id: str, photo_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    photos = repo.get_all_photos(conv_id)
    target = next((p for p in photos if p.id == photo_id), None)
    if not target:
        raise HTTPException(404, "Photo not found")

    delete_photo_files(target)
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
    from vendoo_studio.services.native_marketplaces import running_marketplace

    busy = running_marketplace(db, conv_id)
    if busy:
        # The marketplace record outlives Clear; the action writing it has to finish first.
        raise HTTPException(409, f"Wait for the {busy} listing to finish, or cancel it, before clearing.")

    from vendoo_studio.repositories.queries import JobRepo, ListingRepo
    from vendoo_studio.services.streaming import stop_generation
    from vendoo_studio.services.hidden_fields import clear_listing_hidden_fields
    from vendoo_studio.services.listing_carryover import carryover_updates
    from vendoo_studio.services.vendoo_import import (
        merge_notes,
        parse_notes,
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
        carried = carryover_updates(latest, parse_notes(notes))
        if carried:
            notes = merge_notes(notes, carried)

    # Stop Chrome fill/repair before the wipe deletes the job rows.
    await cancel_conversation_jobs(db, conv_id)

    # Marketplace records survive Clear and Regenerate, with the jobs they name.
    wipe_contents(db, conv_id, keep_photos=keep_inputs, keep_marketplace_listings=True)
    db.expire_all()
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    # A name the seller gave the listing outlives Regenerate; Clear drops it.
    if not (keep_inputs and parse_notes(notes).get("titlePinned")):
        conv.title = "New Listing"
    if keep_inputs:
        conv.notes = notes
    else:
        conv.notes = merge_notes(None, binding) if binding else None
        # Clear removes this item's facts as well as its visible form. Otherwise
        # generation and chat reuse corrections from the listing just erased.
        from vendoo_studio.models.listing_evidence import ListingCorrection

        db.query(ListingCorrection).filter_by(conversation_id=conv_id).delete(synchronize_session=False)
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
    try:
        deleted_jobs, deleted_photos = delete_listing(db, conv_id)
    except ListingBusy as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
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
        "attachments": msg.attachments or [],
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _cover_photo_url(cover: tuple[str, str | None] | None) -> str | None:
    return cover_thumb_url(*cover) if cover else None


def _extras(
    cover_photo_url: str | None,
    facet: dict | None,
    revision_id: str | None = None,
    unsent_edits: bool = False,
    direct_marketplaces: list[str] | None = None,
    direct_listing_urls: dict[str, str] | None = None,
    sold=None,
) -> dict:
    """The per-row fields the sidebar needs alongside the conversation itself."""
    return {
        "cover_photo_url": cover_photo_url,
        "sku": (facet or {}).get("sku"),
        "price": (facet or {}).get("price"),
        "current_revision_id": revision_id,
        "unsent_edits": unsent_edits,
        "etsy_eligible": (facet or {}).get("etsy_eligible", True),
        "direct_marketplaces": list(direct_marketplaces or []),
        "direct_listing_urls": dict(direct_listing_urls or {}),
        "units_sold": sold.units_sold if sold else 0,
        "quantity": sold.quantity if sold else None,
    }


def _extras_for(db: Session, conv_id: str) -> dict:
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    revision_id = repo.current_revision_id(conv_id)
    unsent = _unsent_edits(db, [conv] if conv else [], {conv_id: revision_id} if revision_id else {})
    from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo

    records = MarketplaceListingRepo(db)
    from vendoo_studio.services.item_status import sold_units

    return _extras(
        _cover_photo_url(repo.cover_photo(conv_id)),
        repo.listing_facet(conv_id),
        revision_id,
        conv_id in unsent,
        records.live_marketplaces(conv_id).get(conv_id, []),
        records.listing_urls(conv_id).get(conv_id, {}),
        sold_units(db, [conv] if conv else []).get(conv_id),
    )


# Revisions are never rewritten, so whether two of them hold the same listing
# is settled the first time it is asked. Normalizing both sides costs about a
# millisecond per listing, and the sidebar polls the whole inventory: answered
# fresh every time, it held the GIL for over a second per poll and stalled
# every other request behind it.
_REVISIONS_MATCH: dict[tuple[str, str], bool] = {}
_REVISIONS_MATCH_MAX = 20_000


def _unsent_edits(db: Session, conversations: list, revisions: dict[str, str]) -> set[str]:
    """Conversations whose listing moved on after it was last sent.

    A listing live on a marketplace through Anteroom is measured against what
    those listings were written from, and Vendoo's copy no longer counts:
    Direct List and Update are where its edits go. Any other listing is
    measured against the sync machinery's marker for Vendoo, not against
    revision timestamps: a pull writes a revision too, and dating the
    comparison would call Vendoo's own copy an unsent edit the moment it
    arrived. A differing revision only counts when its content differs too,
    so a revision that just normalized Vendoo's copy is not an edit. A listing
    sent nowhere has nothing to be ahead of.
    """
    from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
    from vendoo_studio.services.vendoo_import import parse_notes
    from vendoo_studio.services.vendoo_watch import SYNCED_REVISION, listings_match

    ids = [conv.id for conv in conversations]
    direct = MarketplaceListingRepo(db).live_revisions(ids[0] if len(ids) == 1 else None)
    pairs: dict[str, set[tuple[str, str]]] = {}
    for conv in conversations:
        current = revisions.get(conv.id)
        if conv.id in direct:
            sent = direct[conv.id]
        else:
            sent = {str(parse_notes(conv.notes).get(SYNCED_REVISION) or "")} - {""}
        differing = {(current, rev) for rev in sent if current and rev != current}
        if differing:
            pairs[conv.id] = differing
    wanted = {pair for group in pairs.values() for pair in group}
    unknown = wanted - _REVISIONS_MATCH.keys()
    if len(_REVISIONS_MATCH) + len(unknown) > _REVISIONS_MATCH_MAX:
        _REVISIONS_MATCH.clear()
        unknown = wanted
    if unknown:
        bodies = ListingRepo(db).revision_bodies({rev for pair in unknown for rev in pair})
        for current, sent in unknown:
            _REVISIONS_MATCH[(current, sent)] = listings_match(bodies.get(current), bodies.get(sent))
    return {conv_id for conv_id, group in pairs.items() if not all(_REVISIONS_MATCH[pair] for pair in group)}


def _relist_pending(notes: dict) -> list[str]:
    """Marketplaces still owed a relist after Studio's last write to Vendoo."""
    raw = notes.get("vendooRelistPending")
    if not isinstance(raw, list):
        return []
    return [str(market).strip() for market in raw if str(market).strip()]


def _listing_urls(notes: dict) -> dict[str, str]:
    raw = notes.get("vendooListingUrls")
    if not isinstance(raw, dict):
        return {}
    return {str(market): str(url) for market, url in raw.items() if url}


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
        "vendoo_form_updated_at": str(notes.get("vendooFormUpdatedAt") or "") or None,
        "vendoo_relist_pending": _relist_pending(notes),
        "vendoo_created_at": text("created"),
        "vendoo_modified_at": text("modified"),
        "vendoo_listed_at": text("listed"),
        "vendoo_sold_at": text("sold"),
        "vendoo_listed_dates": mapping("listedByMarketplace"),
        "vendoo_sold_dates": mapping("soldByMarketplace"),
    }


def _conv_response(conv, extras: dict | None = None) -> ConversationResponse:
    from vendoo_studio.services.marketplace_delist import removed_marketplaces
    from vendoo_studio.services.vendoo_import import parse_notes, split_vendoo_labels

    notes = parse_notes(conv.notes)
    notes_json = conv.notes
    raw_labels = split_vendoo_labels(notes.get("vendooLabels"))

    row = extras or {}
    marketplaces = notes.get("vendooMarketplaces")
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        notes=notes_json,
        status=conv.status,
        box_id=conv.box_id,
        settled_at=_iso(conv.settled_at),
        unsettled_at=_iso(conv.unsettled_at),
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        cover_photo_url=row.get("cover_photo_url"),
        vendoo_status=str(notes.get("vendooStatus") or "") or None,
        vendoo_cover_url=str(notes.get("vendooCoverUrl") or "") or None,
        sku=row.get("sku"),
        price=row.get("price"),
        vendoo_labels=raw_labels,
        vendoo_marketplaces=[str(m) for m in marketplaces] if isinstance(marketplaces, list) else [],
        direct_marketplaces=[str(m) for m in row.get("direct_marketplaces") or []],
        removed_marketplaces=removed_marketplaces(notes, row.get("direct_listing_urls") or {}),
        units_sold=int(row.get("units_sold") or 0),
        quantity=row.get("quantity"),
        vendoo_listing_urls=_listing_urls(notes),
        unsent_edits=bool(row.get("unsent_edits")),
        etsy_eligible=bool(row.get("etsy_eligible", True)),
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
        url=photo_url(photo.id, photo.checksum),
        edits=photo.edits,
        marketplace=photo.marketplace,
    )
