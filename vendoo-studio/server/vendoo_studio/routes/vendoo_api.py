"""Create Vendoo items through Vendoo's own item API — no form filling.

``create`` works on a conversation, not a job: every existing job path queues
the form-filler, which would create the Vendoo item itself. The job this route
makes is held in ``dispatched`` while it runs, so the Send queue waits for it
instead of picking it up.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

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
# Update Vendoo starts on categories so the editor's job card lights up the
# same way first Send does, instead of sitting on a silent HTTP wait.
SAVE_STEP = "vendoo_api_categories"
SAVED_STEP = "vendoo_api_saved"
PATCH_STEP = "vendoo_api_patch"


def _mark_vendoo_api_step(job, step: str) -> None:
    """Advance a dispatched create/save job so the editor progress card moves."""
    from sqlalchemy.orm import object_session

    try:
        session = object_session(job)
    except Exception:  # noqa: BLE001 - tests pass a plain namespace
        return
    if session is None:
        return
    JobRepo(session).update_status(job.id, "dispatched", step)
    session.refresh(job)
    status = str(getattr(job, "status", "") or "")
    if status in {"cancelled", "failed"}:
        raise VendooCreateError(getattr(job, "last_error", None) or f"Send was {status}")


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


def _fold_field_name(text: str) -> str:
    """"attribute_body-fit", "Body Fit" and "bodyFit" all name one control."""
    folded = re.sub(r"[^a-z0-9]", "", str(text or "").lower())
    return folded[9:] if folded.startswith("attribute") else folded


def _humanize_field_key(key: str) -> str:
    """"parcelSize" -> "Parcel Size". Keys already written as labels pass through."""
    text = re.sub(r"[_-]+", " ", str(key or "")).strip()
    if " " in text:
        return text[:1].upper() + text[1:]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return spaced[:1].upper() + spaced[1:]


def _scraped_only_fields(
    listing: dict,
    marketplace: str,
    static: dict[str, list[str]],
    fields: list[dict],
) -> list[dict]:
    """Form controls the category schema never mentions.

    Vendoo's ``category/specifics`` answers with a leaf's attributes alone, so a
    marketplace's own item-level controls — Depop material, style, age — are
    missing from a category that does not happen to list them, and the seller
    cannot see or clear a value validation is rejecting. The skill's form scrape
    has those controls with their options, so they are shown too.
    """
    from vendoo_studio.services.fill_log import listing_value_for_field

    seen = {_fold_field_name(row["key"]) for row in fields}
    seen |= {_fold_field_name(row["label"]) for row in fields}
    extra: list[dict] = []
    for key, options in (static or {}).items():
        folded = _fold_field_name(key)
        if not folded or folded in seen or not options:
            continue
        seen.add(folded)
        label = _humanize_field_key(key)
        extra.append({
            "key": key,
            "label": label,
            "value": (
                listing_value_for_field(listing, marketplace, key)
                or listing_value_for_field(listing, marketplace, label)
            ),
            "required": False,
            "multi": False,
            "selection_only": False,
            "options": list(options),
        })
    return extra


async def _fetch_specs(listing: dict, marketplace: str, category_id: str):
    """Vendoo's schema for one leaf, fetched now when nothing is cached.

    The cache fills on create/send and when a bound draft syncs from Vendoo, so
    a listing whose category was picked elsewhere — or changed since — used to
    show a form with the handful of fields some earlier leaf happened to teach
    us. Asking Vendoo for this listing's own leaf is one round trip, and the
    answer is stored, so the form is the one that category really renders.
    """
    from vendoo_studio.routes.extension import extension_manager
    from vendoo_studio.services.category_fields import save_fields
    from vendoo_studio.services.vendoo_create import mercari_fields, run_ops
    from vendoo_studio.services.vendoo_specifics import normalize_specifics

    if marketplace == "general" or not category_id:
        return None
    if marketplace == "mercari":
        # Mercari's schema is a public static file, not an API answer.
        specs = await mercari_fields(category_id)
        if specs:
            save_fields(marketplace, category_id, specs)
        return specs or None
    if not extension_manager.connected:
        return None
    objects = listing.get("marketplace_category_objects")
    resolved = (objects or {}).get(marketplace) if isinstance(objects, dict) else None
    resolved = resolved if isinstance(resolved, dict) else {}
    try:
        reply = await run_ops(SimpleNamespace(id=None), [{
            "op": "category_specifics",
            "category_id": category_id,
            "marketplace_id": marketplace,
            "path": [str(part) for part in (resolved.get("path") or []) if str(part or "").strip()],
            "extras": resolved.get("extras") if isinstance(resolved.get("extras"), dict) else {},
        }])
    except Exception as exc:  # noqa: BLE001 - a missing schema is not fatal
        log.info("No live %s schema for category %s: %s", marketplace, category_id, exc)
        return None
    hit = next(
        (r for r in (reply.get("results") or []) if r.get("op") == "category_specifics"), {}
    )
    if not hit.get("ok"):
        log.info("No live %s schema for category %s: %s", marketplace, category_id,
                 hit.get("error") or "empty reply")
        return None
    specs = normalize_specifics(hit.get("specifics"))
    if specs:
        save_fields(marketplace, category_id, specs)
    return specs or None


# Keys Studio keeps in <marketplace>_specifics that no form ever renders.
_NON_FORM_SPECIFIC_KEYS = frozenset({
    "categorypath", "categoryid", "categoryspecifics", "category",
})


def _listing_only_fields(
    listing: dict,
    marketplace: str,
    fields: list[dict],
) -> list[dict]:
    """Values this listing holds that neither the schema nor the scrape names.

    Without these a stray key — one an older run wrote, or one Vendoo renamed —
    stays in the listing JSON, keeps failing validation, and has no row the
    seller can clear it from.
    """
    raw = listing.get(f"{marketplace}_specifics")
    if not isinstance(raw, dict):
        return []
    seen = {_fold_field_name(row["key"]) for row in fields}
    seen |= {_fold_field_name(row["label"]) for row in fields}
    extra: list[dict] = []
    for key, value in raw.items():
        folded = _fold_field_name(key)
        if not folded or folded in seen or folded in _NON_FORM_SPECIFIC_KEYS:
            continue
        text = ", ".join(str(v).strip() for v in value if str(v).strip()) if isinstance(value, list) else str(value or "").strip()
        if not text:
            continue
        seen.add(folded)
        extra.append({
            "key": str(key),
            "label": _humanize_field_key(str(key)),
            "value": text,
            "required": False,
            "multi": isinstance(value, list),
            "selection_only": False,
            "options": [],
        })
    return extra


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
        specs = load_fields(marketplace, category_id) or await _fetch_specs(
            listing, marketplace, category_id
        )
        static = static_forms.get(marketplace) or {}
        static_by_fold = {key.casefold(): values for key, values in static.items()}
        if not specs:
            # No schema for this leaf, live or cached. Show the marketplace's
            # own controls and whatever the listing holds, so the form is never
            # blank and a rejected value is still reachable.
            fallback = _scraped_only_fields(listing, marketplace, static, [])
            fallback.extend(_listing_only_fields(listing, marketplace, fallback))
            fallback.sort(key=lambda row: row["label"])
            out.append({
                "marketplace": marketplace, "category_id": category_id,
                "known": False, "fields": fallback,
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
        fields.extend(_scraped_only_fields(listing, marketplace, static, fields))
        fields.extend(_listing_only_fields(listing, marketplace, fields))
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
    # Marketplaces still carrying the listing Vendoo posted before this write.
    # They keep the old copy until the seller delists and relists in Vendoo, so
    # the app says so rather than letting a saved form read as published.
    relist_needed: list[str] = []


@router.post("/api/conversations/{conv_id}/vendoo-api/save", response_model=SaveResponse)
async def save_to_vendoo(conv_id: str, db: Session = Depends(get_db)):
    """Push this conversation's listing onto its Vendoo draft.

    Uses the same prepare path as first Send — resolve categories, fill leaf
    fields, build complete marketplace forms — then writes only the paths that
    differ. After Regenerate, marketplace condition, Mercari Ground Advantage,
    and form saved stamps land the same way a brand-new draft does. This edits
    a draft; it does not list.

    A write onto an item that is already live leaves the marketplace listings
    themselves untouched — Vendoo only carries new copy across by delisting and
    relisting. So the write is stamped in notes (``vendooFormUpdatedAt``) and
    the live marketplaces come back as ``relist_needed``, which is what the
    "Relist in Vendoo" badge reads.

    Either way the conversation is marked level with Vendoo afterwards. Without
    that the next sync reads our own write as Vendoo moving and pulls it back
    over the seller's next edit — and the "unsent edits" badge would never clear.

    The job is held in ``dispatched`` while it runs (same as first Send) so the
    editor can show step progress instead of a silent wait on the button.
    """
    from vendoo_studio.models.job import ACTIVE_JOB_STATUSES
    from vendoo_studio.services.job_snapshot import prepare_listing_snapshot
    from vendoo_studio.services.listing_generate import latest_photo_analysis
    from vendoo_studio.services.listing_provider import get_listing_provider, provider_is_configured
    from vendoo_studio.services.vendoo_api import (
        LISTINGS_KEY,
        apply_update_all,
        build_vendoo_item,
        changed_fields,
        force_condition_updates,
    )
    from vendoo_studio.services.vendoo_create import prepare_listing_for_vendoo, run_ops
    from vendoo_studio.services.vendoo_import import (
        merge_notes,
        parse_notes,
        vendoo_binding,
        vendoo_relistable_marketplaces,
    )
    from vendoo_studio.services.vendoo_watch import mark_synced

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

    job_repo = JobRepo(db)
    if job_repo.get_running():
        raise HTTPException(409, "Chrome is busy with another Vendoo job. Try again when it finishes.")
    if any(job.status in ACTIVE_JOB_STATUSES for job in job_repo.list_by_conversation(conv_id)):
        raise HTTPException(409, "This listing is already queued or sending to Vendoo.")

    snapshot = prepare_listing_snapshot(db, conv, revisions[0].listing_json)
    provider = get_listing_provider() if provider_is_configured() else None
    evidence = latest_photo_analysis(conv_repo.get_messages(conv_id)) or str(conv.notes or "")
    job = job_repo.create(
        conv_id=conv_id,
        approved_revision_id=revisions[0].id,
        listing_snapshot=snapshot,
        vendoo_item_id=item_id,
        status="dispatched",
        current_step=SAVE_STEP,
    )

    def mark(step: str) -> None:
        _mark_vendoo_api_step(job, step)

    updates: dict = {}
    current: dict = {}
    desired: dict = {}
    try:
        reply = await run_ops(job, [{"op": "get_item", "item_id": item_id}])
        current = next(
            (r.get("item") for r in reply.get("results", []) if r.get("op") == "get_item"), None
        ) or {}
        snapshot, specifics, schema, _unresolved, _unfilled = await prepare_listing_for_vendoo(
            job, snapshot, provider=provider, evidence=evidence, mark=mark,
        )
        # Keep the photos already on the draft — save never re-uploads them.
        current_images = (
            (current.get("generalDetails") or {}).get("images")
            if isinstance(current.get("generalDetails"), dict) else None
        )
        desired, _build_unresolved = build_vendoo_item(
            snapshot,
            schema,
            images=current_images if isinstance(current_images, list) else [],
            user_id=str(current.get("userID") or ""),
            item_id=item_id,
            specifics=specifics,
        )
        apply_update_all(current, desired, schema=schema)
        updates = changed_fields(current, desired)
        # The general form is saved on its own first, the way Vendoo's own save
        # runs it: anything that save copies down onto the marketplace forms
        # lands before Studio writes those forms, so Studio's values are the
        # ones left standing. Poshmark's and Mercari's condition rides along
        # with the forms whether or not it changed — it is not an edit of the
        # item, so it stays out of ``updates`` and the relist reminder.
        general_updates = {k: v for k, v in updates.items() if not k.startswith(f"{LISTINGS_KEY}.")}
        form_updates = force_condition_updates(
            desired, {k: v for k, v in updates.items() if k.startswith(f"{LISTINGS_KEY}.")}
        )
        mark(PATCH_STEP)
        for batch in (general_updates, form_updates):
            if batch:
                await run_ops(job, [{"op": "update_item", "item_id": item_id, "updates": batch}])
    except Exception as exc:  # noqa: BLE001 - surfaced as HTTP
        job = job_repo.get(job.id) or job
        if str(getattr(job, "status", "") or "") in {"cancelled", "failed"} or "cancelled" in str(exc).lower():
            raise HTTPException(409, str(exc) or "Update was cancelled") from exc
        job_repo.update_status(job.id, "failed", SAVE_STEP, error=str(exc))
        job_repo.add_event(job.id, "vendoo_api_save_failed", SAVE_STEP, {"error": str(exc)})
        raise _http_error(exc) from exc

    job = job_repo.get(job.id) or job
    if str(getattr(job, "status", "") or "") == "cancelled":
        raise HTTPException(409, "Update was cancelled")

    relist_needed: list[str] = []
    if updates:
        # Stamped from the write, not from Vendoo's own dateLastModified: the
        # badge clears when a marketplace's listing date passes this stamp,
        # which only a delist-and-relist in Vendoo can do.
        relist_needed = vendoo_relistable_marketplaces(current)
        # Remembered, not re-derived, because the seller's next step deletes the
        # evidence: once Delist Item runs in Vendoo the item is live nowhere, and
        # a badge that reads the live listings alone would vanish in the middle
        # of the job — exactly where it is needed to say "now list it again".
        pending = parse_notes(conv.notes).get("vendooRelistPending")
        pending = pending if isinstance(pending, list) else []
        conv.notes = merge_notes(conv.notes, {
            "vendooFormUpdatedAt": datetime.now(UTC).isoformat(),
            "vendooRelistPending": sorted({*map(str, pending), *relist_needed}),
        })
        db.commit()
    # Level with Vendoo on the revision that was just written. The stamp the
    # item was *read* with is deliberately dropped: it predates this write, and
    # keeping it would leave the next sync thinking Vendoo had moved on alone.
    # Without one of its own, mark_synced stamps the moment of the write.
    synced_item = {key: value for key, value in current.items() if key != "dateLastModified"}
    if desired.get("dateLastModified"):
        synced_item["dateLastModified"] = desired["dateLastModified"]
    mark_synced(db, conv_id, synced_item, revisions[0].id)
    job_repo.update_status(job.id, "completed", SAVED_STEP, vendoo_item_id=item_id)
    job_repo.add_event(job.id, "vendoo_api_saved", SAVED_STEP, {
        "item_id": item_id,
        "updated": sorted(updates),
        "relist_needed": relist_needed,
    })
    return SaveResponse(
        ok=True, item_id=item_id, updated=sorted(updates), relist_needed=relist_needed,
    )


@router.post("/api/conversations/{conv_id}/vendoo-api/relist-done")
async def clear_relist_reminder(conv_id: str, db: Session = Depends(get_db)):
    """Drop the relist reminder because the seller says it is handled.

    Normally the badge clears itself: Vendoo reports a listing date newer than
    Studio's write and the item is current again. This is for the cases that
    never produce one — the seller relisted on a marketplace Studio cannot see,
    or decided the edit is not worth a relist. Both stamps go, so nothing
    re-derives the reminder on the next read.
    """
    from vendoo_studio.services.vendoo_import import merge_notes

    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.notes = merge_notes(conv.notes, {"vendooFormUpdatedAt": "", "vendooRelistPending": []})
    db.commit()
    return {"ok": True}


@router.post("/api/conversations/{conv_id}/vendoo-api/pull")
async def pull_from_vendoo(conv_id: str, db: Session = Depends(get_db)):
    """Take Vendoo's version even when Studio has edits of its own."""
    from vendoo_studio.services.vendoo_create import run_ops
    from vendoo_studio.services.vendoo_import import vendoo_binding
    from vendoo_studio.services.vendoo_watch import apply_pull

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

    # Refresh listing revision + job draft cache (sidebar status) in one path.
    revision_id = apply_pull(db, conv_id, item, source="vendoo_pull")
    return {"ok": True, "item_id": item_id, "revision_id": revision_id}


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
    """Level with Vendoo: label-only when status/dates moved, else pull content.

    Form-content changes take Vendoo's copy (including over Studio edits).
    Called when a listing is opened or the app regains focus, so the request
    pattern follows the seller rather than a clock.
    """
    from vendoo_studio.services.vendoo_watch import sync_conversation

    if not ConversationRepo(db).get(conv_id):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True, **await sync_conversation(db, conv_id)}


@router.get("/api/conversations/{conv_id}/vendoo-api/sync")
def vendoo_sync_status(conv_id: str, db: Session = Depends(get_db)):
    """When Studio last checked Vendoo for this listing. Reads SQLite only."""
    from vendoo_studio.services.vendoo_watch import sync_status

    if not ConversationRepo(db).get(conv_id):
        raise HTTPException(404, "Conversation not found")
    return sync_status(db, conv_id)


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
        # The draft was built from this revision, so the two start out level —
        # otherwise a brand-new item reads as edited-but-unsent straight away.
        from vendoo_studio.services.vendoo_watch import mark_synced

        revision = ListingRepo(db).get_revisions(conv_id)
        mark_synced(db, conv_id, out["stored"], revision[0].id if revision else None)
    return CreateResponse(
        ok=True,
        job_id=job.id,
        item_id=out["item_id"],
        url=out["url"],
        unresolved=out["unresolved"],
        unfilled=out.get("unfilled") or [],
        diff=out["diff"],
    )
