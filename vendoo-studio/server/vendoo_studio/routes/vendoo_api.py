"""Create Vendoo items through Vendoo's own item API — no form filling.

``create`` works on a conversation, not a job: every existing job path queues
the form-filler, which would create the Vendoo item itself. The job this route
makes is held in ``dispatched`` while it runs, so the Send queue waits for it
instead of picking it up.
"""
from __future__ import annotations

import logging

from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.vendoo_create import VendooCreateError

router = APIRouter(tags=["vendoo-api"])
log = logging.getLogger("vendoo_studio.vendoo_api_routes")

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
    unfilled: list[dict] = []
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


@router.get("/api/conversations/{conv_id}/vendoo-api/fields")
async def listing_fields(conv_id: str, db: Session = Depends(get_db)):
    """Every field each marketplace form renders for *this* listing's categories.

    One row per field with what the listing currently answers, so the app can
    show a form per marketplace rather than a flat blob: the label Vendoo uses,
    whether it insists on it, whether it takes several values, and the exact
    options it accepts.
    """
    from vendoo_studio.services.category_fields import listing_category_ids, load_fields
    from vendoo_studio.services.fill_log import listing_value_for_field

    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    revisions = ListingRepo(db).get_revisions(conv_id)
    listing = revisions[0].listing_json if revisions else {}

    from vendoo_studio.models.listing_values import marketplace_dropdown_forms

    static_forms = marketplace_dropdown_forms()
    out: list[dict] = []
    for marketplace, category_id in sorted(listing_category_ids(listing).items()):
        specs = load_fields(marketplace, category_id)
        static = static_forms.get(marketplace) or {}
        static_by_fold = {key.casefold(): values for key, values in static.items()}
        if not specs:
            out.append({
                "marketplace": marketplace, "category_id": category_id,
                "known": False, "fields": [],
            })
            continue
        fields = []
        for spec in specs.values():
            label = spec.display or spec.key
            options = sorted(spec.options.values())
            if not options:
                # Category schema sometimes omits the closed list; fall back to
                # the skill scrape so the Forms editor still offers choices.
                options = list(
                    static.get(spec.key)
                    or static.get(label)
                    or static_by_fold.get(str(spec.key).casefold())
                    or static_by_fold.get(str(label).casefold())
                    or []
                )
            fields.append({
                "key": spec.key,
                "label": label,
                "value": listing_value_for_field(listing, marketplace, label),
                "required": spec.required,
                "multi": spec.multi,
                "selection_only": spec.selection_only,
                "options": options,
            })
        fields.sort(key=lambda row: (not row["required"], row["label"]))
        out.append({
            "marketplace": marketplace, "category_id": category_id,
            "known": True, "fields": fields,
        })
    return {"ok": True, "forms": out}


class SaveResponse(BaseModel):
    ok: bool
    item_id: str
    updated: list[str] = []


@router.post("/api/conversations/{conv_id}/vendoo-api/save", response_model=SaveResponse)
async def save_to_vendoo(conv_id: str, db: Session = Depends(get_db)):
    """Push this conversation's edits onto its Vendoo draft.

    Writes only the fields that differ, the way Vendoo's own form save does, so
    anything the seller changed in Vendoo and Studio does not know about is
    left alone. This edits a draft; it does not list.
    """
    from vendoo_studio.services.job_snapshot import prepare_listing_snapshot
    from vendoo_studio.services.vendoo_api import build_vendoo_item, changed_fields
    from vendoo_studio.services.vendoo_create import fetch_listing_specifics, load_schema, run_ops
    from vendoo_studio.services.vendoo_import import vendoo_binding

    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    item_id = vendoo_binding(conv.notes).get("vendooItemId")
    if not item_id:
        raise HTTPException(409, "This listing has no Vendoo draft to save to.")
    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions:
        raise HTTPException(400, "No listing to save.")

    snapshot = prepare_listing_snapshot(db, conv, revisions[0].listing_json)
    job = SimpleNamespace(id=None)
    try:
        reply = await run_ops(job, [{"op": "get_item", "item_id": item_id}])
        current = next(
            (r.get("item") for r in reply.get("results", []) if r.get("op") == "get_item"), None
        ) or {}
        specifics = await fetch_listing_specifics(job, snapshot)
        desired, _unresolved = build_vendoo_item(
            snapshot, load_schema(), images=[], user_id=str(current.get("userID") or ""),
            item_id=item_id, specifics=specifics,
        )
        updates = changed_fields(current, desired)
        if updates:
            await run_ops(job, [{"op": "update_item", "item_id": item_id, "updates": updates}])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    return SaveResponse(ok=True, item_id=item_id, updated=sorted(updates))


@router.post("/api/conversations/{conv_id}/vendoo-api/pull")
async def pull_from_vendoo(conv_id: str, db: Session = Depends(get_db)):
    """Bring edits made in Vendoo back into Studio as a new revision."""
    from vendoo_studio.services.vendoo_create import run_ops
    from vendoo_studio.services.vendoo_import import listing_from_vendoo, vendoo_binding

    conv_repo = ConversationRepo(db)
    conv = conv_repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    item_id = vendoo_binding(conv.notes).get("vendooItemId")
    if not item_id:
        raise HTTPException(409, "This listing has no Vendoo draft to pull from.")
    try:
        reply = await run_ops(SimpleNamespace(id=None), [{"op": "get_item", "item_id": item_id}])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    item = next((r.get("item") for r in reply.get("results", []) if r.get("op") == "get_item"), None)
    if not isinstance(item, dict):
        raise HTTPException(502, "Vendoo returned no item")

    listing_repo = ListingRepo(db)
    revisions = listing_repo.get_revisions(conv_id)
    listing = listing_from_vendoo(item, None)
    revision = listing_repo.save_revision(
        conv_id, listing, source="vendoo_pull",
        parent_revision_id=revisions[0].id if revisions else None,
    )
    return {"ok": True, "item_id": item_id, "revision_id": revision.id}


class ListRequest(BaseModel):
    """Marketplaces must be named, and the seller must confirm in the same call.

    No default of "everywhere": publishing is not something to get by omission.
    """
    marketplaces: list[str] = Field(min_length=1, max_length=15)
    confirm: bool = False


@router.post("/api/conversations/{conv_id}/vendoo-api/list")
async def list_item(conv_id: str, body: ListRequest, db: Session = Depends(get_db)):
    """Publish this conversation's Vendoo draft. Seller-triggered only.

    AGENTS.md: automation must never publish. This route exists for a person
    pressing a button, which is what ``confirm`` records; nothing in Studio
    calls it on its own.

    Only reaches Vendoo's "server marketplaces" — the ones it holds an API
    connection for. Poshmark and Depop come back "Not a server marketplace":
    those are listed by Vendoo's own extension calling each site's internal
    API, and its manifest accepts messages from web.vendoo.co alone, so
    driving it would mean a Vendoo page and their undocumented message
    format. Listing those from here is not wired, and would not be one call.
    """
    return await _list_or_delist(conv_id, body, db, delist=False)


@router.post("/api/conversations/{conv_id}/vendoo-api/delist")
async def delist_item(conv_id: str, body: ListRequest, db: Session = Depends(get_db)):
    """Take this conversation's listings down. Seller-triggered only."""
    return await _list_or_delist(conv_id, body, db, delist=True)


async def _list_or_delist(conv_id: str, body: ListRequest, db: Session, *, delist: bool):
    from vendoo_studio.services.vendoo_create import run_ops
    from vendoo_studio.services.vendoo_import import vendoo_binding

    action = "delist" if delist else "list"
    if not body.confirm:
        raise HTTPException(400, f"Confirm the {action} before it is sent to the marketplaces.")
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    item_id = vendoo_binding(conv.notes).get("vendooItemId")
    if not item_id:
        raise HTTPException(409, "This listing has no Vendoo draft to " + action + ".")
    op = {
        "op": "delist_item" if delist else "list_item",
        "item_id": item_id,
        "marketplaces": [str(mp).strip().lower() for mp in body.marketplaces if str(mp or "").strip()],
    }
    log.warning("seller-triggered %s of %s to %s", action, item_id, op["marketplaces"])
    try:
        reply = await run_ops(SimpleNamespace(id=None), [op])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    hit = next((r for r in reply.get("results", []) if r.get("op") == op["op"]), {})
    return {"ok": True, "action": action, "item_id": item_id,
            "marketplaces": op["marketplaces"], "result": hit.get("result")}


class MapRequest(BaseModel):
    general_category: dict
    marketplace_ids: list[str] = Field(default_factory=list, max_length=12)
    reverse: bool = False


@router.post("/api/vendoo-api/category-map")
async def category_map(body: MapRequest):
    """Map one general category to each marketplace, the way Vendoo's forms do."""
    from vendoo_studio.services.vendoo_create import run_ops

    ops = [{
        "op": "category_map",
        "marketplace_id": mp,
        "general_category": body.general_category,
        "reverse": body.reverse,
        "throttle_ms": 150,
    } for mp in body.marketplace_ids]
    if not ops:
        raise HTTPException(400, "Pass at least one marketplace id")
    try:
        reply = await run_ops(SimpleNamespace(id=None), ops)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    return {"ok": True, "matches": {
        r.get("marketplace_id"): {"match": r.get("match"), "recommendations": r.get("recommendations")}
        for r in reply.get("results", []) if r.get("op") == "category_map"
    }}


@router.post("/api/conversations/{conv_id}/vendoo-api/sync")
async def sync_with_vendoo(conv_id: str, db: Session = Depends(get_db)):
    """Bring in Vendoo's changes when it is safe to, and say so when it is not.

    Called when a listing is opened or the app regains focus, so the request
    pattern follows the seller rather than a clock. Pulls only when Studio has
    nothing outstanding of its own; when both sides moved, neither wins and the
    conflict is reported.
    """
    from vendoo_studio.services.vendoo_create import run_ops
    from vendoo_studio.services.vendoo_import import vendoo_binding
    from vendoo_studio.services.vendoo_watch import apply_pull, mark_synced, sync_state

    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    item_id = vendoo_binding(conv.notes).get("vendooItemId")
    if not item_id:
        return {"ok": True, "action": "none", "reason": "no vendoo draft"}
    try:
        reply = await run_ops(SimpleNamespace(id=None), [{"op": "get_item", "item_id": item_id}])
    except BrowserBridgeError:
        # No browser is not a failure worth interrupting the seller over.
        return {"ok": True, "action": "none", "reason": "chrome unavailable"}
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    item = next((r.get("item") for r in reply.get("results", []) if r.get("op") == "get_item"), None)
    if not isinstance(item, dict):
        return {"ok": True, "action": "none", "reason": "no item"}

    state = sync_state(db, conv_id, item)
    if state["action"] == "pull":
        revision_id = apply_pull(db, conv_id, item)
        return {"ok": True, "action": "pull", "reason": state["reason"], "revision_id": revision_id}
    if state["action"] == "conflict":
        return {"ok": True, "action": "conflict", "reason": state["reason"], "item_id": item_id}
    mark_synced(db, conv_id, item, state.get("revision"))
    return {"ok": True, "action": "none", "reason": state["reason"]}


class DeleteRequest(BaseModel):
    """Items must be named and the call confirmed. Deleting cannot be undone."""
    item_ids: list[str] = Field(min_length=1, max_length=50)
    confirm: bool = False


@router.post("/api/vendoo-api/delete")
async def delete_items(body: DeleteRequest, db: Session = Depends(get_db)):
    """Remove Vendoo drafts by id, refusing any a conversation still points at."""
    from vendoo_studio.services.vendoo_create import run_ops
    from vendoo_studio.services.vendoo_import import vendoo_binding

    if not body.confirm:
        raise HTTPException(400, "Confirm the delete: it cannot be undone.")
    bound = {
        vendoo_binding(conv.notes).get("vendooItemId")
        for conv in ConversationRepo(db).list_all()
    }
    wanted = [str(i).strip() for i in body.item_ids if str(i or "").strip()]
    refused = sorted({i for i in wanted if i in bound})
    targets = [i for i in wanted if i not in bound]
    if not targets:
        return {"ok": True, "deleted": [], "refused": refused}
    log.warning("seller-triggered delete of %s", targets)
    try:
        reply = await run_ops(
            SimpleNamespace(id=None),
            [{"op": "delete_item", "item_id": i, "throttle_ms": 150} for i in targets],
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    deleted = [r.get("deleted") for r in reply.get("results", []) if r.get("op") == "delete_item" and r.get("ok")]
    return {"ok": True, "deleted": deleted, "refused": refused}


class UpdateRequest(BaseModel):
    item_id: str
    updates: dict = Field(default_factory=dict)


@router.post("/api/vendoo-api/update")
async def update_item_fields(body: UpdateRequest):
    """Write specific dotted paths onto a Vendoo item.

    The field-level counterpart to reading one back: needed whenever Studio
    has to correct state Vendoo set, such as a listing status left behind by a
    failed delist.
    """
    from vendoo_studio.services.vendoo_create import run_ops

    if not body.updates:
        raise HTTPException(400, "Pass at least one field to update")
    try:
        reply = await run_ops(SimpleNamespace(id=None), [{
            "op": "update_item", "item_id": body.item_id, "updates": body.updates,
        }])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    hit = next((r for r in reply.get("results", []) if r.get("op") == "update_item"), {})
    return {"ok": True, "item_id": body.item_id, "updated": hit.get("updated") or []}


class SizesRequest(BaseModel):
    category_id: str
    marketplace_id: str = "vendoo"


@router.post("/api/vendoo-api/sizes")
async def category_sizes(body: SizesRequest):
    """The sizes and size types one category offers, coded as the form stores them."""
    from vendoo_studio.services.vendoo_create import run_ops

    try:
        reply = await run_ops(SimpleNamespace(id=None), [{
            "op": "size_query",
            "category_id": body.category_id,
            "marketplace_id": body.marketplace_id,
        }])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        raise _http_error(exc) from exc
    hit = next((r for r in reply.get("results", []) if r.get("op") == "size_query"), {})
    return {"ok": True, "sizes": hit.get("sizes")}


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
    from vendoo_studio.services.listing_generate import latest_photo_analysis
    from vendoo_studio.services.listing_provider import get_listing_provider, provider_is_configured
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
    # The model answers the category's fields before the item goes up, so the
    # draft is created complete instead of bare.
    provider = get_listing_provider() if provider_is_configured() else None
    # The vision pass already ran during generation and its result is still on
    # the conversation, so reuse it rather than paying for it again. Seller
    # notes stand in when there is none.
    evidence = latest_photo_analysis(conv_repo.get_messages(conv_id)) or str(conv.notes or "")
    job = job_repo.create(
        conv_id=conv_id,
        approved_revision_id=revisions[0].id,
        listing_snapshot=snapshot,
        status="dispatched",
        current_step=CREATE_STEP,
    )
    try:
        out = await create_item(job, snapshot, photos, provider=provider, evidence=evidence)
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        job = job_repo.get(job.id) or job
        if str(getattr(job, "status", "") or "") in {"cancelled", "failed"} or "cancelled" in str(exc).lower():
            raise HTTPException(409, str(exc) or "Send was cancelled") from exc
        job_repo.update_status(job.id, "failed", CREATE_STEP, error=str(exc))
        job_repo.add_event(job.id, "vendoo_api_create_failed", CREATE_STEP, {"error": str(exc)})
        raise _http_error(exc) from exc

    job = job_repo.get(job.id) or job
    if str(getattr(job, "status", "") or "") == "cancelled":
        # Draft may already exist on Vendoo; do not bind or flip the cancelled job.
        raise HTTPException(409, "Send was cancelled")

    conv.notes = merge_notes(conv.notes, {"vendooItemId": out["item_id"], "vendooUrl": out["url"]})
    db.commit()
    job_repo.update_status(
        job.id, "completed", CREATED_STEP, vendoo_item_id=out["item_id"], vendoo_url=out["url"]
    )
    job_repo.add_event(job.id, "vendoo_api_created", CREATED_STEP, {
        "item_id": out["item_id"],
        "unresolved": out["unresolved"],
        "unfilled": out.get("unfilled") or [],
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
        unfilled=out.get("unfilled") or [],
        diff=out["diff"],
    )
