"""Fix a saved Vendoo draft from chat, one checked action at a time.

The seller opens the draft in Studio's browser, optionally points at fields,
and says what is wrong in chat. The agent reads the live form, chooses one
action, runs it through the extension, and reads the form again. It prefers
Studio's field filler and falls back to clicking and typing. It never
publishes: the extension refuses publish, list, delist, and delete controls
and keeps every action on the open draft.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from vendoo_studio.services import browser_bridge
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.fill_log import (
    MAX_PATCH_VALUE,
    FillLogService,
    field_lookup_key,
    listing_value_for_field,
    normalize_field_label,
    write_values_into_listing,
)
from vendoo_studio.services.registry import SELLER_SETTING_LABELS, is_account_managed_field

log = logging.getLogger(__name__)

MAX_STEPS = 24
MAX_PROMPT_FIELDS = 120
MAX_PROMPT_EMPTY = 60
MAX_PROMPT_OPTIONS = 40
MAX_EVIDENCE_CHARS = 3000
MAX_AGENT_PHOTOS = 6
AGENT_PHOTO_MAX_SIDE = 1024
SCROLL_PX = 500
SETTLE_SEC = 0.5
SAVE_SETTLE_SEC = 2.0
SAVE_SELECTOR = '[data-testid="save-item-button"]'
PRESS_KEYS = frozenset({"Enter", "Escape", "Tab", "Backspace", "ArrowDown", "ArrowUp", " "})
BRIEF_KEYS = (
    "title", "description", "brand", "size", "color", "condition", "category_path",
    "material", "style", "pattern", "department", "category_specifics", "ebay_specifics",
)
MAX_BRIEF_CHARS = 4000
MARKETPLACES = frozenset({"general", "ebay", "etsy", "poshmark", "mercari", "depop"})
MARKET_LABELS = {
    "general": "Vendoo",
    "ebay": "eBay",
    "etsy": "Etsy",
    "poshmark": "Poshmark",
    "mercari": "Mercari",
    "depop": "Depop",
}

AGENT_SYSTEM = """You fix a saved Vendoo listing draft. The seller has it open in Studio's browser and told you in chat what to change.

Each turn you get the seller's request, any fields they pointed at, the listing's product photos, the live form, and your previous steps.
Look at the photos for every field: tags and care labels give brand, size, material, and origin; the garment itself shows neckline, sleeves, closure, pattern, fit, accents, and features.
Reply with exactly ONE JSON object and nothing else. Actions:
{"action":"fill","fields":[{"marketplace":"ebay","field":"Size","value":"M"}]}
{"action":"click_field","marketplace":"ebay","field":"Size"}
{"action":"click","text":"Show optional fields"}
{"action":"type","text":"text to type into the focused field"}
{"action":"press","key":"Enter"}
{"action":"scroll","direction":"down"}
{"action":"save"}
{"action":"ask","message":"one short question for the seller"}
{"action":"done","message":"one or two sentences for the seller"}

Rules:
- Change only what the seller asked for. When they pointed at fields, fill only those fields; leave every other field alone, even if it looks wrong or already has a value.
- When the seller asks you to fill pointed-at or empty fields, fill every one you can in a single fill action first. Do not stop to ask about one field while others can be filled.
- "Every empty field on the form" lists the blanks. When the seller asks for empty or missing fields and pointed at nothing, work that list and fill each one the evidence supports; do not revisit fields that already show a value.
- Values come from, in order: the seller's request, known_value on the field, the listing summary, the photos and photo evidence (tag text, care tag, measurements), then what the photos and title plainly show (neckline, sleeve length, pattern, closure, fit, occasion, character, accents, features). Using that evidence is not inventing.
- For dropdowns, pick the closest allowed option: a care tag of 92% polyester, 8% spandex means Material "Polyester"; a machine-wash care tag means Garment Care "Machine Washable". Set Handmade to "No" unless the listing says handmade.
- Leave a field empty only when nothing supports a value (for example MPN, or Country of Origin with no tag). List those fields in your done message instead of asking.
- Prefer fill. Studio's filler types text, selects dropdown options, and saves the draft. When a step reports fields still empty, switch to click_field on each one: for text and tag fields (Accents, Features, Character, Fabric Weight, MPN) type the value and press Enter; for dropdowns read open_options and click the option text. Save when finished.
- If a field is missing from the live form, click "Show Optional Fields" or scroll to reveal it.
- Keys for press: Enter, Escape, Tab, Backspace, ArrowDown, ArrowUp, and " " for Space.
- Fields marked account are the seller's marketplace settings. Never change them.
- You cannot publish, list, delist, or delete a listing. Never try.
- After clicking or typing values, save before done.
- Check the live form after each step. A value only counts when the form shows it. A fill of the same field and value that already failed is refused, so switch to click_field or a different value instead.
- When a field lists options, the value must be one of them, copied exactly. When it lists none, type what the evidence supports.
- Ask only when you cannot tell which field the seller means, or when every remaining field needs a fact that is nowhere in the evidence. Never make up brand, size, measurements, or origin.
- If the form already shows what the seller wants, reply done."""


@dataclass
class FixRequest:
    job_id: str
    conversation_id: str
    instruction: str
    picked: list[dict[str, Any]] = field(default_factory=list)


_cancelled: set[str] = set()


def cancel(conversation_id: str) -> None:
    _cancelled.add(conversation_id)


def _take_cancel(conversation_id: str) -> bool:
    if conversation_id in _cancelled:
        _cancelled.discard(conversation_id)
        return True
    return False


def market_label(marketplace: str) -> str:
    return MARKET_LABELS.get(marketplace, marketplace)


def is_account_field(marketplace: str, label: str, flagged: bool = False) -> bool:
    return bool(flagged) or field_lookup_key(label) in SELLER_SETTING_LABELS or is_account_managed_field(marketplace, label)


def field_key(marketplace: str, label: str) -> tuple[str, str]:
    return (str(marketplace or "general").strip().lower(), normalize_field_label(str(label or "")))


def parse_action(text: str) -> dict[str, Any] | None:
    """First JSON object with an action in the model reply."""
    if not text:
        return None
    candidates = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text) + [text]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("action"), str):
                return value
    return None


def describe_action(action: dict[str, Any]) -> str:
    kind = action.get("action")
    if kind == "fill":
        names = [
            f"{market_label(str(f.get('marketplace') or 'general'))} / {f.get('field')} = {str(f.get('value'))[:40]}"
            for f in action.get("fields") or [] if isinstance(f, dict)
        ]
        return "Filling " + "; ".join(names[:6])
    if kind == "click_field":
        return f"Opening {market_label(str(action.get('marketplace') or 'general'))} / {action.get('field')}"
    if kind == "click":
        return f"Clicking \"{action.get('text')}\""
    if kind == "type":
        return f"Typing \"{str(action.get('text'))[:40]}\""
    if kind == "press":
        return f"Pressing {action.get('key')}"
    if kind == "scroll":
        return f"Scrolling {action.get('direction') or 'down'}"
    if kind == "save":
        return "Saving the draft"
    return str(kind)


def _prompt_field(
    entry: dict[str, Any],
    viewport_height: int,
    picked: set[tuple[str, str]],
    listing: dict,
    known_options: dict[tuple[str, str], list[str]] | None = None,
) -> dict[str, Any]:
    rect = entry.get("rect") or {}
    row: dict[str, Any] = {
        "marketplace": entry.get("marketplace"),
        "field": entry.get("label"),
        "value": entry.get("value") or "",
    }
    if field_key(entry.get("marketplace"), entry.get("label")) in picked:
        row["pointed_at"] = True
    if not row["value"] and entry.get("label"):
        # What Studio's listing already holds for this field, if anything.
        known = listing_value_for_field(listing, str(entry.get("marketplace") or "general"), str(entry["label"]))
        if known:
            row["known_value"] = known[:200]
    if entry.get("required"):
        row["required"] = True
    if entry.get("is_dropdown"):
        row["dropdown"] = True
    # Only native selects carry their options in the snapshot. Vendoo's MUI dropdowns
    # come back empty, so fall back to the options the registry learned from probes.
    options = entry.get("options") or (known_options or {}).get(
        field_key(entry.get("marketplace"), entry.get("label")), []
    )
    if options:
        row["options"] = options[:MAX_PROMPT_OPTIONS]
    if entry.get("error"):
        row["error"] = entry["error"]
    if entry.get("disabled"):
        row["disabled"] = True
    if entry.get("account_managed"):
        row["account"] = True
    y = rect.get("y")
    if isinstance(y, (int, float)) and viewport_height:
        row["on_screen"] = 0 <= y < viewport_height
    return row


def build_turn(
    request: FixRequest,
    snapshot: dict[str, Any],
    history: list[str],
    listing: dict,
    evidence: str,
    known_options: dict[tuple[str, str], list[str]] | None = None,
) -> str:
    picked = {field_key(f.get("marketplace"), f.get("label") or f.get("field")) for f in request.picked}
    viewport = snapshot.get("viewport") or {}
    live = snapshot.get("fields") or []
    # Pointed-at fields first, then empty ones: a draft with every marketplace open has
    # more fields than the cap, and the blanks are the whole point of the request. The
    # cut falls on fields that already hold a value, which the agent leaves alone anyway.
    live = sorted(live, key=lambda entry: (
        field_key(entry.get("marketplace"), entry.get("label")) not in picked,
        bool(entry.get("value")),
    ))
    fields = [
        _prompt_field(entry, int(viewport.get("height") or 0), picked, listing, known_options)
        for entry in live[:MAX_PROMPT_FIELDS]
    ]
    pointed = [
        f"{market_label(str(f.get('marketplace') or 'general'))} / {f.get('label') or f.get('field')}"
        for f in request.picked
    ]
    brief = {key: listing.get(key) for key in BRIEF_KEYS if listing.get(key)}
    def _name(row: dict[str, Any]) -> str:
        return f"{market_label(str(row.get('marketplace') or 'general'))} / {row.get('field')}"

    empty = [
        row for row in fields
        if not row.get("value") and not row.get("account") and not row.get("disabled")
    ]
    still_empty = [_name(row) for row in empty if row.get("pointed_at")]
    blanks = [_name(row) for row in empty[:MAX_PROMPT_EMPTY]]
    parts = [
        f"Seller request: {request.instruction.strip() or '(no text) Fix the fields I pointed at.'}",
        f"Fields the seller pointed at: {', '.join(pointed) if pointed else 'none'}",
        f"Pointed-at fields still empty on the form: {', '.join(still_empty) if still_empty else 'none'}",
        f"Every empty field on the form: {', '.join(blanks) if blanks else 'none'}",
        f"Listing summary: {json.dumps(brief, ensure_ascii=False)[:MAX_BRIEF_CHARS]}",
        f"Photo evidence:\n{evidence[:MAX_EVIDENCE_CHARS] or '(none)'}",
        "Live form fields:\n" + json.dumps(fields, ensure_ascii=False),
        "Visible buttons and tabs: " + json.dumps([c.get("text") for c in snapshot.get("controls") or []], ensure_ascii=False),
        "Open dropdown options: " + json.dumps(snapshot.get("open_options") or [], ensure_ascii=False),
        "Your steps so far:\n" + ("\n".join(history) if history else "(none)"),
        "Reply with one JSON action.",
    ]
    return "\n\n".join(parts)


def _find_field(snapshot: dict[str, Any], marketplace: str, label: str) -> dict[str, Any] | None:
    wanted = field_key(marketplace, label)
    for entry in snapshot.get("fields") or []:
        if field_key(entry.get("marketplace"), entry.get("label")) == wanted:
            return entry
    return None


def field_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Form values that differ between two snapshots, as seller-facing lines."""
    old = {field_key(f.get("marketplace"), f.get("label")): f for f in before.get("fields") or []}
    lines = []
    for entry in after.get("fields") or []:
        key = field_key(entry.get("marketplace"), entry.get("label"))
        previous = old.get(key)
        was = (previous or {}).get("value") or ""
        now = entry.get("value") or ""
        # Fields revealed during the fix count too, once they hold a value.
        if (previous is None and now) or (previous is not None and was != now):
            lines.append(f"- {market_label(key[0])} / {entry.get('label')}: {was or 'empty'} → {now or 'empty'}")
    return lines


class FixAgent:
    def __init__(self, request: FixRequest, provider, *, db_factory):
        self.request = request
        self.provider = provider
        self.db_factory = db_factory
        self.history: list[str] = []
        self.unsaved = False
        self.photos: list[str] = []
        # Values that reached the form and did not stick, so a fill is never retried blind.
        self.failed: dict[tuple[str, str], set[str]] = {}
        # Dropdown options the registry knows, keyed like the live fields.
        self.options: dict[tuple[str, str], list[str]] = {}
        # Set by _fill so the loop reuses the snapshot it already paid for.
        self.fresh: dict[str, Any] | None = None

    def _empty_pointed(self, snapshot: dict[str, Any]) -> bool:
        for picked in self.request.picked:
            live = _find_field(snapshot, str(picked.get("marketplace") or "general"), str(picked.get("label") or picked.get("field") or ""))
            if live is not None and not live.get("value") and not live.get("account_managed"):
                return True
        return False

    def _job(self, db):
        from vendoo_studio.repositories.queries import JobRepo

        job = JobRepo(db).get(self.request.job_id)
        if job is None:
            raise BrowserBridgeError("This listing's Vendoo job no longer exists.")
        return job

    async def _snapshot(self) -> dict[str, Any]:
        db = self.db_factory()
        try:
            job = self._job(db)
        finally:
            db.close()
        result = await browser_bridge.snapshot(job)
        if not result.get("ok"):
            raise BrowserBridgeError(result.get("error") or "Could not read the Vendoo draft.")
        return result

    async def _act(self, payload: dict[str, Any]) -> dict[str, Any]:
        db = self.db_factory()
        try:
            job = self._job(db)
        finally:
            db.close()
        return await browser_bridge.act(job, payload)

    def _context(self) -> tuple[dict, str, list[str]]:
        from pathlib import Path

        from vendoo_studio.config import PHOTOS_DIR
        from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
        from vendoo_studio.services.listing_generate import latest_photo_analysis

        db = self.db_factory()
        try:
            revisions = ListingRepo(db).get_revisions(self.request.conversation_id)
            listing = dict(revisions[0].listing_json) if revisions and isinstance(revisions[0].listing_json, dict) else {}
            conversations = ConversationRepo(db)
            evidence = latest_photo_analysis(conversations.get_messages(self.request.conversation_id)) or ""
            paths = [str(Path(PHOTOS_DIR) / photo.stored_filename) for photo in conversations.get_photos(self.request.conversation_id)]
        finally:
            db.close()
        return listing, evidence, [path for path in paths if Path(path).is_file()][:MAX_AGENT_PHOTOS]

    async def _load_photos(self, paths: list[str]) -> None:
        if not paths or not callable(getattr(self.provider, "vision_chat", None)):
            return
        from vendoo_studio.providers.xiaomi_mimo import encode_images

        try:
            self.photos = await encode_images(paths, AGENT_PHOTO_MAX_SIDE)
        except Exception:
            log.exception("could not encode listing photos for the fix agent")
            self.photos = []

    async def _ask_model(self, messages: list[dict[str, Any]]) -> str:
        from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
        from vendoo_studio.services.listing_generate import collect_provider_text

        if not self.photos:
            return await collect_provider_text(self.provider, messages)
        # Photos ride on the first user turn so every decision can look at the item itself.
        first = messages[1]
        with_photos = [
            messages[0],
            {"role": "user", "content": [{"type": "text", "text": first["content"]}]
             + [{"type": "image_url", "image_url": {"url": url}} for url in self.photos]},
            *messages[2:],
        ]
        try:
            parts = []
            async for item in self.provider.vision_chat(with_photos):
                kind, text = unpack_stream_item(item)
                if kind == "content" and text:
                    parts.append(text)
            return "".join(parts)
        except Exception:
            log.exception("fix agent photo call failed; continuing with the photo analysis text only")
            self.photos = []
            return await collect_provider_text(self.provider, messages)

    def _load_options(self, snapshot: dict[str, Any], listing: dict) -> None:
        """Learn allowed options for dropdowns the snapshot could not read itself."""
        from vendoo_studio.repositories.queries import RegistryRepo

        wanted = [
            entry for entry in snapshot.get("fields") or []
            if entry.get("is_dropdown") and not entry.get("options")
            and field_key(entry.get("marketplace"), entry.get("label")) not in self.options
        ]
        if not wanted:
            return
        category_path = str(listing.get("category_path") or "") or None
        db = self.db_factory()
        try:
            registry = RegistryRepo(db)
            for entry in wanted:
                key = field_key(entry.get("marketplace"), entry.get("label"))
                try:
                    self.options[key] = registry.get_valid_options(key[0], str(entry.get("label") or ""), category_path)
                except Exception:
                    self.options[key] = []
        finally:
            db.close()

    async def _decide(self, snapshot: dict[str, Any], listing: dict, evidence: str) -> dict[str, Any] | None:
        self._load_options(snapshot, listing)
        messages = [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": build_turn(self.request, snapshot, self.history, listing, evidence, self.options)},
        ]
        text = await self._ask_model(messages)
        action = parse_action(text)
        if action is None:
            messages += [
                {"role": "assistant", "content": text[:2000]},
                {"role": "user", "content": "That was not a JSON action. Reply with exactly one JSON object."},
            ]
            action = parse_action(await self._ask_model(messages))
        return action

    async def _fill(self, action: dict[str, Any], snapshot: dict[str, Any]) -> str:
        from vendoo_studio.repositories.queries import ListingRepo
        from vendoo_studio.services.auto_apply import apply_patches

        patches: list[dict[str, str]] = []
        refused: list[str] = []
        unpicked: list[str] = []
        repeated: list[str] = []
        picked = {field_key(f.get("marketplace"), f.get("label") or f.get("field")) for f in self.request.picked}
        for raw in action.get("fields") or []:
            if not isinstance(raw, dict):
                continue
            marketplace = str(raw.get("marketplace") or "general").strip().lower()
            label = str(raw.get("field") or "").strip()
            value = raw.get("value")
            if isinstance(value, list):
                value = ", ".join(str(part).strip() for part in value if str(part).strip())
            value = str(value if value is not None else "").strip()[:MAX_PATCH_VALUE]
            if marketplace not in MARKETPLACES or not label or not value:
                continue
            if picked and field_key(marketplace, label) not in picked:
                unpicked.append(label)
                continue
            if value in self.failed.get(field_key(marketplace, label), ()):
                repeated.append(label)
                continue
            live = _find_field(snapshot, marketplace, label)
            if is_account_field(marketplace, label, bool(live and live.get("account_managed"))):
                refused.append(label)
                continue
            patches.append({
                "marketplace": marketplace,
                "field": (live or {}).get("label") or label,
                "value": value,
                "selector": (live or {}).get("selector") or "",
            })
        notes = []
        if unpicked:
            notes.append(f"skipped fields the seller did not point at: {', '.join(unpicked)}")
        if refused:
            notes.append(f"skipped account settings: {', '.join(refused)}")
        if repeated:
            notes.append(
                f"skipped values the form already rejected: {', '.join(repeated)}"
                " — use click_field on them, or a different value"
            )
        note = f" ({'; '.join(notes)})" if notes else ""
        if not patches:
            if refused and not unpicked and not repeated:
                return "refused: account settings stay as they are" + note
            return "nothing to fill" + note

        db = self.db_factory()
        try:
            job = self._job(db)
            listing_repo = ListingRepo(db)
            revisions = listing_repo.get_revisions(job.conversation_id)
            current = dict(revisions[0].listing_json) if revisions and isinstance(revisions[0].listing_json, dict) else {}
            updated = write_values_into_listing(current, patches)
            listing_repo.save_revision(
                job.conversation_id,
                updated,
                source="browser_fix",
                parent_revision_id=revisions[0].id if revisions else None,
            )
            FillLogService(db).record_generated_values(job.conversation_id, patches)
            ok, error = await apply_patches(db, job, updated, patches, announce=False)
        finally:
            db.close()
        self.unsaved = False
        if not ok:
            return f"failed: {error or 'fill did not finish'}" + note
        # The filler can report success without the value landing; trust only the live form.
        after = await self._snapshot()
        self.fresh = after
        missing = []
        for patch in patches:
            landed = ((_find_field(after, patch["marketplace"], patch["field"]) or {}).get("value") or "").strip()
            if landed:
                continue
            missing.append(patch["field"])
            self.failed.setdefault(field_key(patch["marketplace"], patch["field"]), set()).add(patch["value"])
        if not missing:
            return "ok, the form shows every value" + note
        if len(missing) == len(patches):
            return ("failed: the form still shows these empty: " + ", ".join(missing)
                    + ". Use click_field, type the value, then press Enter or click the option") + note
        return ("partly: still empty on the form: " + ", ".join(missing)
                + ". Use click_field, type the value, then press Enter or click the option") + note

    async def _execute(self, action: dict[str, Any], snapshot: dict[str, Any]) -> str:
        kind = action.get("action")
        if kind == "fill":
            return await self._fill(action, snapshot)
        if kind == "click_field":
            marketplace = str(action.get("marketplace") or "general").strip().lower()
            label = str(action.get("field") or "")
            live = _find_field(snapshot, marketplace, label)
            if live is None:
                return "failed: no such field on screen; scroll or open its section first"
            if is_account_field(marketplace, label, bool(live.get("account_managed"))):
                return "refused: account settings stay as they are"
            payload: dict[str, Any] = {"action": "click"}
            if live.get("selector"):
                payload["selector"] = live["selector"]
            else:
                rect, viewport = live.get("rect") or {}, snapshot.get("viewport") or {}
                if not viewport.get("width") or not viewport.get("height"):
                    return "failed: field has no position"
                payload["x_ratio"] = min(1, max(0, (rect.get("x", 0) + rect.get("width", 0) / 2) / viewport["width"]))
                payload["y_ratio"] = min(1, max(0, (rect.get("y", 0) + rect.get("height", 0) / 2) / viewport["height"]))
            result = await self._act(payload)
        elif kind == "click":
            result = await self._act({"action": "click", "text": str(action.get("text") or "")[:120]})
            self.unsaved = True
        elif kind == "type":
            result = await self._act({"action": "type", "text": str(action.get("text") or "")[:2000]})
            self.unsaved = True
        elif kind == "press":
            key = str(action.get("key") or "")
            if key not in PRESS_KEYS:
                return f"failed: unsupported key {key}"
            result = await self._act({"action": "press", "key": key})
            self.unsaved = True
        elif kind == "scroll":
            delta = -SCROLL_PX if str(action.get("direction") or "").lower() == "up" else SCROLL_PX
            result = await self._act({"action": "scroll", "delta_y": delta})
        elif kind == "save":
            result = await self._act({"action": "click", "selector": SAVE_SELECTOR})
            if result.get("ok"):
                self.unsaved = False
                await asyncio.sleep(SAVE_SETTLE_SEC)
        else:
            return f"failed: unknown action {kind}"
        await asyncio.sleep(SETTLE_SEC)
        return "ok" if result.get("ok") else f"failed: {result.get('error') or 'no reason given'}"

    async def run(self) -> AsyncIterator[tuple[str, str]]:
        """Yield ("status", text) while working and one ("final", text) at the end."""
        request = self.request
        _take_cancel(request.conversation_id)
        started = time.monotonic()
        listing, evidence, photo_paths = self._context()
        if photo_paths:
            yield "status", "Loading the listing photos…"
            await self._load_photos(photo_paths)
        try:
            yield "status", "Reading the Vendoo draft…"
            first = snapshot = await self._snapshot()
        except BrowserBridgeError as exc:
            yield "final", f"I could not read the Vendoo draft: {exc}"
            return

        outcome = ""
        pushed_back = False
        for _ in range(MAX_STEPS):
            if _take_cancel(request.conversation_id):
                outcome = "Stopped."
                break
            if browser_bridge.human_input_since(request.job_id, started):
                outcome = "Paused because you started using the draft. Send another message when you want me to continue."
                break
            yield "status", "Deciding the next step…"
            try:
                action = await self._decide(snapshot, listing, evidence)
            except Exception as exc:
                log.exception("fix agent model call failed")
                outcome = f"The listing assistant failed: {exc}"
                break
            if action is None:
                outcome = "The listing assistant did not return a usable action, so I stopped."
                break
            if action.get("action") == "ask" and not pushed_back and not self.history and self._empty_pointed(snapshot):
                # Models tend to ask about the first unclear field and stop. Make them fill the rest first.
                pushed_back = True
                self.history.append(
                    f"{len(self.history) + 1}. Wanted to ask \"{str(action.get('message') or '')[:160]}\" → "
                    "not yet: fill every pointed-at field the evidence supports first, pick the closest "
                    "dropdown option, and name the fields you had to leave empty in done"
                )
                continue
            if action.get("action") in {"done", "ask"}:
                outcome = str(action.get("message") or "").strip() or ("Done." if action["action"] == "done" else "What should I change?")
                break
            label = describe_action(action)
            yield "status", f"{label}…"
            try:
                result = await self._execute(action, snapshot)
                snapshot, self.fresh = self.fresh or await self._snapshot(), None
            except BrowserBridgeError as exc:
                outcome = f"The Vendoo browser stopped responding: {exc}"
                break
            self.history.append(f"{len(self.history) + 1}. {label} → {result}")
        else:
            outcome = "I reached my step limit before finishing. Tell me what is still wrong and I will keep going."

        if self.unsaved:
            yield "status", "Saving the draft…"
            try:
                saved = await self._act({"action": "click", "selector": SAVE_SELECTOR})
                await asyncio.sleep(SAVE_SETTLE_SEC)
                snapshot = await self._snapshot()
                if not saved.get("ok"):
                    outcome += f"\n\nI could not save the draft: {saved.get('error')}. Save it in Vendoo."
            except BrowserBridgeError as exc:
                outcome += f"\n\nI could not save the draft: {exc}. Save it in Vendoo."

        changes = field_changes(first, snapshot)
        text = outcome
        if changes:
            text += "\n\nChanged on the draft:\n" + "\n".join(changes)
        elif self.history:
            text += "\n\nNo field values changed on the draft."
        if self.history:
            text += "\n\nSteps:\n" + "\n".join(self.history)
        yield "final", text
