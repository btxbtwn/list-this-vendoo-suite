from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.services.registry import align_listing_gender
from vendoo_studio.services.category_catalog import remember_path

log = logging.getLogger("vendoo_studio.category_lookup")

CATEGORY_SEARCH_TIMEOUT_SEC = 45

_GARMENT_RE = re.compile(
    r"\b(sweatshirts?|hoodies?|sweaters?|t-?shirts?|tees?|polos?|dresses?|"
    r"jeans?|pants?|shorts?|skirts?|jackets?|coats?|blouses?|tanks?)\b",
    re.I,
)
_TEE_LEAF_RE = re.compile(r"\bt-?shirts?\b|\btees?\b", re.I)
_SWEAT_RE = re.compile(r"\bsweatshirts?\b|\bhoodies?\b|\bsweaters?\b", re.I)
_WOMEN_RE = re.compile(r"\bwomen(?:['’]s)?\b", re.I)
_MEN_RE = re.compile(r"\bmen(?:['’]s)?\b", re.I)


def _path_leaf(category: str) -> str:
    parts = [part.strip() for part in str(category or "").split(">") if part.strip()]
    return parts[-1] if parts else ""


def _listing_department(listing: dict | None) -> str:
    listing = listing or {}
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    for value in (listing.get("department"), ebay.get("department") if isinstance(ebay, dict) else None):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _listing_type(listing: dict | None) -> str:
    listing = listing or {}
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    for value in (ebay.get("type") if isinstance(ebay, dict) else None, listing.get("type")):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_garment(*texts: str) -> str:
    found: list[str] = []
    for text in texts:
        for match in _GARMENT_RE.finditer(text or ""):
            found.append(match.group(1))
    if not found:
        return ""
    for item in found:
        if _SWEAT_RE.search(item):
            return item
    return found[0]


def category_search_query(listing: dict | None, requested: str | None = None) -> str:
    """Build a short picker query from the listing and an optional requested path."""
    listing = listing if isinstance(listing, dict) else {}
    requested = str(requested or "").strip()
    department = _listing_department(listing)
    listing_path = str(listing.get("category_path") or "").strip()
    leaf = _path_leaf(requested) or _path_leaf(listing_path)
    garment = _first_garment(requested, _listing_type(listing), str(listing.get("title") or ""), leaf)
    parts: list[str] = []
    for part in (department, garment or leaf or requested):
        text = str(part or "").strip()
        if not text:
            continue
        if parts and text.lower() in parts[-1].lower():
            continue
        parts.append(text)
    return " ".join(parts).strip()


def _gender(text: str) -> str | None:
    has_women = bool(_WOMEN_RE.search(text or ""))
    has_men = bool(_MEN_RE.search(text or ""))
    if has_men and not has_women:
        return "men"
    if has_women and not has_men:
        return "women"
    return None


def _wrong_garment(path: str, query: str, listing: dict | None) -> bool:
    haystack = f"{query} {_listing_type(listing)} {str((listing or {}).get('title') or '')}"
    leaf = _path_leaf(path)
    if _SWEAT_RE.search(haystack) and _TEE_LEAF_RE.search(leaf) and not _SWEAT_RE.search(leaf):
        return True
    return False


def _match_path(match: dict | None) -> str:
    if not isinstance(match, dict):
        return ""
    return str(match.get("path") or match.get("text") or "").strip()


def pick_category_path(
    matches: list[dict] | None,
    listing: dict | None = None,
    query: str = "",
    selected: str | None = None,
) -> str:
    """Prefer a picker leaf that matches gender and garment over a leftover T-shirt."""
    listing = listing if isinstance(listing, dict) else {}
    candidates = [str(selected or "").strip()]
    for match in matches or []:
        path = _match_path(match)
        if path:
            candidates.append(path)
    want_gender = _gender(query) or _gender(_listing_department(listing))
    ranked: list[str] = []
    for path in candidates:
        if not path or path in ranked:
            continue
        if _wrong_garment(path, query, listing):
            continue
        path_gender = _gender(path)
        if want_gender and path_gender and path_gender != want_gender:
            continue
        ranked.append(path)
    return ranked[0] if ranked else str(selected or "").strip() or _match_path((matches or [None])[0])


def _job_for_conversation(db: Session, conv_id: str):
    from vendoo_studio.repositories.queries import JobRepo

    jobs = JobRepo(db).list_by_conversation(conv_id)
    for job in jobs:
        if job.status == "cancelled":
            continue
        if job.vendoo_item_id or job.vendoo_url:
            return job
    return None


def apply_resolved_category(db: Session, conv_id: str, path: str) -> dict:
    from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
    from vendoo_studio.services.vendoo_import import merge_notes

    path = str(path or "").strip()
    if not path:
        return {}
    revisions = ListingRepo(db).get_revisions(conv_id)
    listing = dict(revisions[0].listing_json) if revisions and isinstance(revisions[0].listing_json, dict) else {}
    listing["category_path"] = path
    listing = align_listing_gender(listing)
    ListingRepo(db).save_revision(
        conv_id,
        listing,
        source="vendoo_category",
        parent_revision_id=revisions[0].id if revisions else None,
    )
    conv = ConversationRepo(db).get(conv_id)
    if conv:
        conv.notes = merge_notes(conv.notes, {"categoryOverride": path})
        db.commit()
    return listing


async def resolve_listing_category(
    db: Session,
    conv_id: str,
    *,
    query: str | None = None,
    job: Any = None,
) -> dict[str, Any]:
    """Search the live Vendoo category picker and save the matching leaf onto the listing."""
    from vendoo_studio.repositories.queries import ListingRepo
    from vendoo_studio.routes.extension import (
        dispatch_search_categories,
        extension_manager,
    )

    job = job or _job_for_conversation(db, conv_id)
    if not job or not (job.vendoo_item_id or job.vendoo_url):
        return {"ok": False, "skipped": True, "error": "No Vendoo draft is available yet. Send the listing first."}
    if job.status == "dispatched" and job.current_step == "filling_fields":
        return {"ok": False, "skipped": True, "error": "A Vendoo fill is already running."}
    if not extension_manager.connected:
        return {"ok": False, "skipped": True, "error": "Chrome is not connected"}

    revisions = ListingRepo(db).get_revisions(conv_id)
    listing = dict(revisions[0].listing_json) if revisions and isinstance(revisions[0].listing_json, dict) else {}
    search = category_search_query(listing, query)
    if not search:
        return {"ok": False, "error": "No category search query"}

    request_id = uuid.uuid4().hex[:12]
    waiter = extension_manager.register_wait(request_id)
    try:
        sent = await dispatch_search_categories(job, request_id, search)
        if not sent:
            return {"ok": False, "error": "Could not reach the Chrome extension"}
        try:
            payload = await asyncio.wait_for(waiter, timeout=CATEGORY_SEARCH_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": "Chrome did not return Vendoo category matches in time. Open the listing tab and try again.",
            }
    finally:
        extension_manager.cancel_wait(request_id)

    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    for match in matches:
        if _match_path(match):
            remember_path(db, "general", _match_path(match))
    db.commit()
    path = pick_category_path(matches, listing, search, str(payload.get("path") or "").strip())
    if not payload.get("ok") and not path:
        return {
            "ok": False,
            "query": search,
            "matches": matches,
            "error": payload.get("error") or "No matching Vendoo category",
        }
    if not path:
        return {"ok": False, "query": search, "matches": matches, "error": "No matching Vendoo category"}

    saved = apply_resolved_category(db, conv_id, path)
    return {
        "ok": True,
        "query": search,
        "path": path,
        "matches": matches,
        "listing": saved,
    }
