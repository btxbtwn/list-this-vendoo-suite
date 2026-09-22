"""Prompt construction for listing chat and listing generation."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR, skills_dir
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.comp_research import research_sold_comps
from vendoo_studio.services.listing_generate import (
    PHOTO_ANALYSIS_RETRY_MESSAGE,
    PhotoAnalysisError,
    analysis_with_photo_count,
    analyze_photos_with_tag_retry,
    latest_photo_analysis,
    photo_analysis_usable,
    require_photo_analysis,
    seller_item_details,
)
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.registry import MEN_TSHIRT_PATH, WOMEN_TOPS_PATH

log = logging.getLogger("vendoo_studio.chat")


def load_skill_rules(query: str = "", db: Session | None = None) -> str:
    from vendoo_studio.services.skill_formulas import with_pinned_formulas

    skill_md = skills_dir() / "list-this" / "SKILL.md"
    template_md = skills_dir() / "list-this" / "references" / "vendoo_listing_template.md"

    def _file_rules() -> str:
        parts = []
        if skill_md.exists():
            parts.append(skill_md.read_text())
        if template_md.exists():
            parts.append(template_md.read_text())
        return with_pinned_formulas("\n\n---\n\n".join(parts) if parts else "")

    if db is not None and str(query or "").strip():
        try:
            from vendoo_studio.services.catalog_index import relevant_skill_rules
            rules = relevant_skill_rules(db, query)
            if str(rules or "").strip():
                return with_pinned_formulas(rules)
        except Exception:
            log.exception("catalog skill rules unavailable; falling back to SKILL.md")
    return _file_rules()


def learned_fields_prompt(db: Session, conv_id: str) -> str:
    from vendoo_studio.services.registry import RegistryService

    category_path = None
    revisions = ListingRepo(db).get_revisions(conv_id)
    if revisions and isinstance(revisions[0].listing_json, dict):
        category_path = revisions[0].listing_json.get("category_path") or None
    from vendoo_studio.services.category_catalog import schema_context
    text = RegistryService(db).generation_context(category_path) + schema_context(db, category_path or "")
    if not text:
        return ""
    return f"\n\n--- Learned fields ---\n\n{text}"


def current_listing_prompt(db: Session, conv_id: str) -> str:
    import json
    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions or not isinstance(revisions[0].listing_json, dict):
        return ""
    listing = revisions[0].listing_json
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    return (
        "\n\n--- Current listing ---\n"
        f"Saved listing JSON: {json.dumps(listing, ensure_ascii=False)}\n"
        f"department: {listing.get('department') or ''}\n"
        f"category_path: {listing.get('category_path') or ''}\n"
        f"ebay_specifics.department: {(ebay or {}).get('department') or ''}\n"
        "If the seller changes gender or category, replace department, category_path, "
        "and ebay_specifics.department together. Do not leave a women's category on a men's item.\n"
    )


async def build_chat_messages(conv_id: str, db: Session, user_message: str) -> list[dict]:
    repo = ConversationRepo(db)
    history = repo.get_messages(conv_id)
    photos = repo.get_photos(conv_id)
    conv = repo.get(conv_id)
    notes = (conv.notes if conv else "") or ""

    skill_rules = load_skill_rules(user_message, db)

    photo_analysis_text = ""
    comps_text = ""
    evidence: dict = {}
    existing_analysis = latest_photo_analysis(history)
    if photos and existing_analysis and photo_analysis_usable(existing_analysis):
        photo_analysis_text = analysis_with_photo_count(len(photos), existing_analysis)
        skill_rules = load_skill_rules(
            f"{user_message}\n{photo_analysis_text}\n{seller_item_details(notes)}",
            db,
        )
    elif photos:
        provider = get_listing_provider()
        if provider:
            paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
            try:
                result = await analyze_photos_with_tag_retry(provider, paths, notes="", listing_rules=skill_rules[:8000])
            except Exception as exc:
                raise PhotoAnalysisError(PHOTO_ANALYSIS_RETRY_MESSAGE) from exc
            evidence, analysis_note = require_photo_analysis(result)
            analysis_note = analysis_note.replace(
                "Photo analysis:",
                "Photo analysis of the uploaded product images:",
                1,
            )
            repo.add_message(conv_id, "system", analysis_note)
            photo_analysis_text = analysis_with_photo_count(len(photos), analysis_note)
            skill_rules = load_skill_rules(
                f"{user_message}\n{photo_analysis_text}\n{seller_item_details(notes)}",
                db,
            )
            comps_text = await research_sold_comps(photo_analysis_text, evidence)
            if comps_text:
                repo.add_message(conv_id, "system", comps_text, provider="brave", model="web-search")
        else:
            photo_analysis_text = analysis_with_photo_count(len(photos), existing_analysis)

    comps_block = f"\n\n--- Sold comps ---\n\n{comps_text}\n" if comps_text else ""

    from vendoo_studio.services.fill_log import is_missing_fields_request

    ask_missing_fields = is_missing_fields_request(user_message)
    if ask_missing_fields:
        change_instructions = (
            "The seller asked you to fill specific empty/leftover fields.\n"
            "1. Write one short sentence confirming which fields you filled.\n"
            "2. Then include a fenced json code block with this exact shape so Studio saves them "
            "into the listing JSON automatically:\n"
            "```json\n"
            '{"missing_fields":[{"marketplace":"etsy","field":"Pattern","value":"Solid"}]}\n'
            "```\n"
            "Use the marketplace ids and field names from the seller request exactly. "
            "Do not use a JSON Patch array. Do not rewrite unrelated listing fields.\n"
            "Studio saves the listing JSON and refreshes the Forms/Fields UI; "
            "filling the live Vendoo draft is a separate later step.\n\n"
        )
    else:
        change_instructions = (
            "When the user asks you to change an existing listing:\n"
            "1. Write a short confirmation of what you changed (department, category, marketplace fields).\n"
            "2. Then include a JSON Patch array in a fenced json code block so the listing can be saved. "
            "The seller will not see that block.\n"
            'Example confirmation: "This is a men\'s T-shirt. I moved it to Men > Men\'s Clothing > Shirts > T-Shirts."\n'
            "Example patch:\n"
            "```json\n"
            '[{"op": "replace", "path": "/department", "value": "Men"},'
            f'{{"op": "replace", "path": "/category_path", "value": "{MEN_TSHIRT_PATH}"}},'
            '{"op": "replace", "path": "/ebay_specifics/department", "value": "Men"}]\n'
            "```\n\n"
        )

    system_prompt = {
        "role": "system",
        "content": (
            "You are a product listing assistant talking to a seller. Write in plain English.\n"
            "Never reply with JSON-only output, status objects, or a bare JSON Patch array.\n\n"
            + change_instructions
            +             "When generating a listing from scratch, infer every supportable field from the photos and initial seller notes, "
            "note remaining uncertainties about the item itself in the description without asking questions, "
            "then the full listing JSON in a fenced json code block.\n\n"
            "If you are not changing the listing, reply in plain English only. "
            "If asked whether the listing was updated, say yes only when a system message in this "
            "conversation confirms the listing JSON was saved; otherwise say no.\n\n"
            "Key rules:\n"
            "- Never publish. Stop at saved drafts.\n"
            "- Never ask the seller clarifying questions. Infer from the photos and notes already provided.\n"
            "- Never ask the seller to upload or attach photos when product photos are already present.\n"
            "- Be conservative with brand and size: use photo/tag/logo evidence and seller notes only; leave unsupported facts empty and flag uncertainty — never invent, never ask.\n"
            f"- General Vendoo category paths must use Vendoo taxonomy: women's shirts and T-shirts end at {WOMEN_TOPS_PATH}, never Shirts & Blouses. Men's T-shirts use {MEN_TSHIRT_PATH}.\n"
            "- Title MUST follow Brand Size Vibe Item Color Fit exactly (max 80 chars) from the Formula Reference below.\n"
            "- The size in the title must be the size field verbatim. Men's bottoms size as waist x inseam (30x30), never a bare waist.\n"
            "- Description MUST follow the physical-item formula exactly (line breaks; trendy keyword sentence, Flaws:, Measurements:) unless this is an Etsy digital download.\n"
            "- NEVER put pricing details in the description: no prices, dollar amounts, comps, sold-listing counts, market/resale value, MSRP, discounts, offers, or pricing uncertainty. Pricing lives in the price field only.\n"
            "- Do not invent catchy titles or prose that break those formulas.\n"
            "- Resolve every applicable discovered field with a real value or Does Not Apply when the field truly does not apply.\n"
            "- Fill every discovered category/marketplace field in the JSON. Do not leave applicable fields empty.\n"
            "- Never tell the seller the listing is complete, ready, or done while any discovered field is still empty.\n"
            "- Estimate packaged shipping weight and mailer dimensions from the item type; do not ask the seller for those.\n"
            "- Depop: exactly 3 style tags from the allowed values list.\n"
            + (f"\n{photo_analysis_text}\n\n" if photo_analysis_text else "") +
            comps_block +
            f"\n--- Listing Rules ---\n\n{skill_rules}"
            if skill_rules
            else ""
        ) + current_listing_prompt(db, conv_id) + learned_fields_prompt(db, conv_id),
    }

    import json

    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.completion_gaps import review_fields
    for job in JobRepo(db).list_by_conversation(conv_id):
        if job.current_step == "awaiting_answers":
            review = JobRepo(db).latest_event(job.id, "completion_review")
            if review:
                system_prompt["content"] += "\nUnresolved saved-form fields:\n" + json.dumps(
                    review_fields(review.payload or {}, job.listing_snapshot or {}), ensure_ascii=False)
                system_prompt["content"] += "\nUse photo evidence and the seller's notes or later replies to update these fields. Never claim completion before verification. Never ask clarifying questions."
            break
    messages = [system_prompt]
    for msg in history[-20:]:
        role = msg.role
        if role == "model":
            role = "assistant"
        messages.append({"role": role, "content": msg.text})

    messages.append({"role": "user", "content": user_message})
    return messages


LISTING_INSTRUCTIONS = (
    "You are a product listing generator. Generate an evidence-backed Vendoo listing JSON "
    "from the photo analysis and listing rules below.\n\n"
    "Preserve category_path and marketplace_categories from the verified category selections below. "
    "Each marketplace uses its own category tree; do not substitute another form's breadcrumb.\n\n"
    "Always include sku (BRAND-SIZE slug, e.g. DISNEY-PARKS-M), primaryColor, and secondaryColor "
    "when a second color is visible. Colors must be exact Vendoo General dropdown values from "
    "the listing rules below. Use Blue for navy; Navy is only a Depop option. "
    "Use Vendoo general condition values such as "
    '"Pre-Owned - Good". Keep tags to 5 or fewer. Depop needs source and age. '
    "Mercari shippingLabel must be USPS Ground Advantage.\n\n"
    "TITLE and DESCRIPTION are non-negotiable skill formulas — copy the structure from "
    "Formula Reference below. Title order is Brand Size Vibe Item Color Fit (max 80 chars), "
    "and the title's size is the size field verbatim — men's bottoms size as waist x inseam (30x30). "
    "Physical descriptions must keep the mandatory blank lines and the Flaws:/Measurements: "
    "blocks after a short trendy keyword sentence. Do not write freeform marketing copy that breaks those formulas.\n\n"
    "If seller-provided measurements (Pit to pit, Length, Sleeve) are given, use them exactly as-is in the description.\n"
    "Do not modify, estimate, or replace seller-provided measurements.\n"
    "If the seller lists known flaws, repeat every one of them in the Flaws: block, "
    "in the seller's own words. Never drop a flaw or soften it to \"none noted\".\n"
    "Use the discovered category fields below. Fill every applicable field with a real value or Does Not Apply. "
    "Only leave a field empty when you must ask the seller a precise question in prose — and never claim the listing is complete while any applicable discovered field is still empty. "
    "Estimate packaged shipping weight (weight_lb/weight_oz) and package_dimensions_in from the item type — "
    "do not ask the seller for routine apparel shipping weight or mailer size. "
    "Never invent brand, size, material, age, or other product facts without photo or seller evidence. "
    "Prefer verbatim tag text from the photo analysis for brand, size, and material. "
    "Studio applies generated values onto the bound Vendoo draft automatically when Chrome is connected. "
    "Price from the sold comps block when it has three or more sold listings: market price × 1.35, whole dollars. "
    "One or two sold listings is a single data point, not a market — with fewer than three, or with none, "
    "use a conservative baseline and price conservatively. Never mention pricing in the description.\n"
    "The description is buyer-facing copy about the item: never include prices, dollar amounts, comps, "
    "sold-listing counts, market or resale value, MSRP, discounts, offers, or any note about pricing "
    "confidence. Those belong in the price field only.\n\n"
    "Return ONLY one fenced ```json code block with the full listing object. "
    "No prose before or after the fence. Valid JSON only (no trailing commas).\n\n"
    "```json\n"
    "{\n"
    '  "title": "...",\n'
    '  "description": "...",\n'
    '  "price": ...,\n'
    '  "cost": ...,\n'
    '  "quantity": 1,\n'
    '  "brand": "...",\n'
    '  "condition": "...",\n'
    '  "primaryColor": "...",\n'
    '  "secondaryColor": "...",\n'
    '  "sku": "...",\n'
    '  "size": "...",\n'
    '  "sizeType": "...",\n'
    '  "tags": [...],\n'
    '  "package_dimensions_in": "...",\n'
    '  "ebay_specifics": {...},\n'
    '  "depop_specifics": {"source": "Preloved", "age": "Modern"},\n'
    '  "etsy_specifics": {...},\n'
    '  "poshmark_specifics": {"originalPrice": 0},\n'
    '  "mercari_specifics": {"shippingLabel": "USPS Ground Advantage"}\n'
    "}\n"
    "```"
)


def _empty_discovered_fields_prompt(db: Session, conv_id: str) -> str:
    """List discovered fields still empty so generation fills them in one pass, not a later gap round."""
    from copy import deepcopy

    from vendoo_studio.services.listing_field_gaps import collect_empty_discovered_fields
    from vendoo_studio.services.registry import RegistryService

    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions or not isinstance(revisions[0].listing_json, dict):
        return ""
    probe = deepcopy(revisions[0].listing_json)
    if not str(probe.get("category_path") or "").strip():
        return ""
    RegistryService(db).merge_learned_fields(probe)
    gaps = collect_empty_discovered_fields(db, probe)
    if not gaps:
        return ""
    lines = [f"- {gap['marketplace']}: {gap['field']}" for gap in gaps]
    return (
        "\n\n--- Discovered fields still empty ---\n"
        "Fill each of these in the listing JSON (root fields or the marketplace *_specifics) using exact "
        "allowed options from the category fields above, or Does Not Apply when the field truly does not apply:\n"
        + "\n".join(lines)
    )


def listing_generation_messages(
    skill_rules: str,
    item_details: str,
    analysis_text: str,
    db: Session,
    conv_id: str,
    comps_text: str = "",
    photo_count: int = 0,
) -> list[dict]:
    comps_block = f"\n\n--- Sold comps ---\n\n{comps_text}" if comps_text else ""
    photo_line = (
        f"The seller already uploaded {photo_count} product photo(s). "
        "Never ask them to attach or re-upload photos — generate the listing now.\n\n"
        if photo_count
        else ""
    )
    # Static instructions and rules lead so provider prefix caches hit across items;
    # per-item evidence follows.
    system_content = (
        f"{LISTING_INSTRUCTIONS}\n\n"
        f"--- Listing Rules ---\n\n{skill_rules}"
        f"{learned_fields_prompt(db, conv_id)}"
        "\n\n--- This item ---\n\n"
        f"{photo_line}"
        f"{item_details}\n\n"
        f"{analysis_text}"
        f"{comps_block}"
        f"{current_listing_prompt(db, conv_id)}"
        f"{_empty_discovered_fields_prompt(db, conv_id)}"
    )
    return [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": (
                f"Generate a complete listing from the {photo_count} uploaded product photos. "
                "Reply with only the ```json listing block."
                if photo_count
                else "Generate a complete listing from these product photos. Reply with only the ```json listing block."
            ),
        },
    ]
