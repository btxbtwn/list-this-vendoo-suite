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
# Girls'/boys' items were read as having no gender at all, which threw away
# half the query on every kids' listing.
_GIRLS_RE = re.compile(r"\bgirls?(?:['’]s)?\b", re.I)
_BOYS_RE = re.compile(r"\bboys?(?:['’]s)?\b", re.I)
# The vision pass states what the item is. Nothing else in the analysis comes
# close as a category signal, and it was being dropped.
_ANALYSIS_CATEGORY_RE = re.compile(r"^\s*[-*]?\s*category\s*:\s*(.+)$", re.I | re.M)
# The vision pass states who the item is cut for. Nothing else in the analysis
# carries it reliably: a women's tee often names no department anywhere, and
# the category trees split on department before anything else.
_ANALYSIS_DEPARTMENT_RE = re.compile(r"^\s*[-*]?\s*department\s*:\s*(.+)$", re.I | re.M)
_DEPARTMENT_WORDS = {
    "women": "women", "womens": "women", "woman": "women", "ladies": "women",
    "men": "men", "mens": "men", "man": "men",
    "girls": "girls", "girl": "girls",
    "boys": "boys", "boy": "boys",
    "baby": "baby", "infant": "baby", "toddler": "baby",
}
# Roots / leaves that "tee" keyword ranking kept confusing with clothing.
_NON_APPAREL_PATH_RE = re.compile(
    r"(^|\s)(business\s*&\s*industrial|toys?\s*&\s*collectibles|electronics|motors|"
    r"home\s*&\s*garden|pet\s*supplies|everything\s*else)\b|"
    r"\b(fastener\s*nuts?|tee\s*nuts?|play\s*teepees?|bottle\s*caps?)\b",
    re.I,
)
_APPAREL_GENERAL_RE = re.compile(
    r"\b(clothing|shoes|accessories|women|men|kids|girls|boys|baby)\b",
    re.I,
)
_APPAREL_MARKET_RE = re.compile(
    r"\b(clothing|fashion|women|men|kids|girls|boys|baby|tops?|tees?|t-?shirts?|"
    r"blouses?|shirts?|dresses?|jeans?|pants?|skirts?|shoes|accessories)\b",
    re.I,
)


def _path_leaf(category: str) -> str:
    parts = [part.strip() for part in str(category or "").split(">") if part.strip()]
    return parts[-1] if parts else ""


def is_apparel_general(path: str) -> bool:
    """True when the general breadcrumb is clothing/fashion rather than hardware."""
    text = str(path or "").strip()
    if not text or _NON_APPAREL_PATH_RE.search(text):
        return False
    return bool(_APPAREL_GENERAL_RE.search(text))


def is_non_apparel_path(path: str) -> bool:
    """True for hardware/toys paths that keyword search used to score for \"tee\"."""
    return bool(_NON_APPAREL_PATH_RE.search(str(path or "")))


def marketplace_path_fits_general(general_path: str, marketplace_path: str) -> bool:
    """Reject cached or ranked marketplace leaves that cannot belong under this general.

    A women's Tops general must not reuse a remembered Fastener Nuts / Play Teepees
    leaf from an earlier poisoned cache entry.
    """
    market = str(marketplace_path or "").strip()
    if not market:
        return False
    if not is_apparel_general(general_path):
        return True
    if is_non_apparel_path(market):
        return False
    return bool(_APPAREL_MARKET_RE.search(market))


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


_STYLE_RE = re.compile(
    r"\b(straight[\s-]?leg|skinny|boot\s?cut|flare|wide[\s-]?leg|boyfriend|relaxed|slim)\b",
    re.I,
)
_TOPS_RE = re.compile(r"\btops?\b", re.I)
_SEARCH_STOPWORDS = frozenset({
    "photo", "photos", "photograph", "photographed", "photography", "analysis", "detailed",
    "images", "image", "background", "visible", "appears", "appear", "seller", "details",
    "json", "condition", "notes", "please", "classify", "product", "type", "across",
    "marketplaces", "additional", "observations", "lighting", "wrinkles", "removed",
    "pair", "flat", "white", "show", "shows", "shown", "item", "based", "about",
})


def condense_category_search_query(*texts: str, override: str = "") -> str:
    """Short catalog query from free-form analysis — drops photo-analysis noise words."""
    override = str(override or "").strip()
    joined = "\n".join(str(text or "").strip() for text in (*texts, override) if str(text or "").strip())
    leaf = _path_leaf(override)
    garment = _first_garment(override, joined)
    gender = _gender(joined)
    # Sellers often say "women's top" — treat that as tops intent when no sharper garment matched.
    if not garment and gender == "women" and _TOPS_RE.search(joined):
        garment = "tops"
    parts: list[str] = []
    if gender:
        parts.append(gender)
    if garment:
        parts.append(garment)
    elif leaf:
        parts.append(leaf)
    if garment and re.search(r"jeans?", garment, re.I):
        style = _STYLE_RE.search(joined)
        if style:
            parts.append(re.sub(r"[\s-]+", " ", style.group(1)).strip())
    # The analysis already classified the item; a bare garment word like "Tee"
    # matches Fastener Nuts as readily as it matches a t-shirt.
    stated = _analysis_category(joined) if not override else ""
    if stated:
        seen = {part.casefold() for part in parts}
        for word in re.findall(r"[A-Za-z0-9']+", stated):
            if len(word) > 2 and word.casefold() not in seen and word.casefold() not in _SEARCH_STOPWORDS:
                seen.add(word.casefold())
                parts.append(word)
    if parts:
        return " ".join(parts)
    if override:
        return override
    tokens = [
        token for token in re.findall(r"[a-z0-9']+", joined.casefold())
        if len(token) > 2 and token not in _SEARCH_STOPWORDS
    ]
    return " ".join(tokens[:8]).strip()


def _stated_department(text: str) -> str | None:
    """The department the analysis named outright, if it named one."""
    match = _ANALYSIS_DEPARTMENT_RE.search(text or "")
    if not match:
        return None
    for word in re.findall(r"[a-z]+", match.group(1).casefold()):
        if word in _DEPARTMENT_WORDS:
            return _DEPARTMENT_WORDS[word]
    return None


def _gender(text: str) -> str | None:
    text = text or ""
    # An explicit department beats inferring one from stray words: "men" shows
    # up inside plenty of listings that are not menswear.
    stated = _stated_department(text)
    if stated:
        return stated
    has_women = bool(_WOMEN_RE.search(text))
    has_men = bool(_MEN_RE.search(text))
    if has_men and not has_women:
        return "men"
    if has_women and not has_men:
        return "women"
    if has_women and has_men:
        return None
    # Only consider kids when neither adult department was named, so "women's"
    # beside a girls' size still reads as womenswear.
    has_girls = bool(_GIRLS_RE.search(text))
    has_boys = bool(_BOYS_RE.search(text))
    if has_girls and not has_boys:
        return "girls"
    if has_boys and not has_girls:
        return "boys"
    return None


def _analysis_category(text: str) -> str:
    """What the photo analysis called the item, e.g. "Girls' Graphic T-Shirt"."""
    match = _ANALYSIS_CATEGORY_RE.search(text or "")
    if not match:
        return ""
    value = re.sub(r"\s+", " ", match.group(1)).strip()
    # Strip a trailing parenthetical source note the analysis sometimes adds.
    value = re.sub(r"\s*\((?:source|from)[^)]*\)\s*$", "", value, flags=re.I).strip()
    return value if len(value) <= 60 else ""


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
        except TimeoutError:
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
