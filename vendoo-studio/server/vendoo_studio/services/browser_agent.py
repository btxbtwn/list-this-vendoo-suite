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
    normalize_field_label,
    write_values_into_listing,
)
from vendoo_studio.services.registry import SELLER_SETTING_LABELS, is_account_managed_field

log = logging.getLogger(__name__)

MAX_STEPS = 24
MAX_PROMPT_FIELDS = 120
MAX_PROMPT_OPTIONS = 40
MAX_EVIDENCE_CHARS = 3000
SCROLL_PX = 500
SETTLE_SEC = 0.5
SAVE_SETTLE_SEC = 2.0
SAVE_SELECTOR = '[data-testid="save-item-button"]'
PRESS_KEYS = frozenset({"Enter", "Escape", "Tab", "Backspace", "ArrowDown", "ArrowUp", " "})
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

Each turn you get the seller's request, any fields they pointed at, the live form, and your previous steps.
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
- Change only what the seller asked for. When they pointed at fields, work on those fields.
- Prefer fill. Studio's filler types text, selects dropdown options, and saves the draft. Use clicks and typing only when fill failed or a section must be opened first.
- Dropdown values must match an allowed option. To see options, click_field the dropdown, then read open_options and click the option text.
- Keys for press: Enter, Escape, Tab, Backspace, ArrowDown, ArrowUp, and " " for Space.
- Fields marked account are the seller's marketplace settings. Never change them.
- You cannot publish, list, delist, or delete a listing. Never try.
- After clicking or typing values, save before done.
- Check the live form after each step. A value only counts when the form shows it.
- Ask when you cannot tell which field or value the seller means. Never invent brand, size, material, measurements, or origin.
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


def _prompt_field(entry: dict[str, Any], viewport_height: int, picked: set[tuple[str, str]]) -> dict[str, Any]:
    rect = entry.get("rect") or {}
    row: dict[str, Any] = {
        "marketplace": entry.get("marketplace"),
        "field": entry.get("label"),
        "value": entry.get("value") or "",
    }
    if field_key(entry.get("marketplace"), entry.get("label")) in picked:
        row["pointed_at"] = True
    if entry.get("required"):
        row["required"] = True
    if entry.get("is_dropdown"):
        row["dropdown"] = True
    if entry.get("options"):
        row["options"] = entry["options"][:MAX_PROMPT_OPTIONS]
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


def build_turn(request: FixRequest, snapshot: dict[str, Any], history: list[str], listing: dict, evidence: str) -> str:
    picked = {field_key(f.get("marketplace"), f.get("label") or f.get("field")) for f in request.picked}
    viewport = snapshot.get("viewport") or {}
    fields = [
        _prompt_field(entry, int(viewport.get("height") or 0), picked)
        for entry in (snapshot.get("fields") or [])[:MAX_PROMPT_FIELDS]
    ]
    pointed = [
        f"{market_label(str(f.get('marketplace') or 'general'))} / {f.get('label') or f.get('field')}"
        for f in request.picked
    ]
    brief = {key: listing.get(key) for key in ("title", "brand", "size", "color", "condition", "category_path") if listing.get(key)}
    parts = [
        f"Seller request: {request.instruction.strip() or '(no text) Fix the fields I pointed at.'}",
        f"Fields the seller pointed at: {', '.join(pointed) if pointed else 'none'}",
        f"Listing summary: {json.dumps(brief, ensure_ascii=False)}",
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

    def _context(self) -> tuple[dict, str]:
        from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
        from vendoo_studio.services.listing_generate import latest_photo_analysis

        db = self.db_factory()
        try:
            revisions = ListingRepo(db).get_revisions(self.request.conversation_id)
            listing = dict(revisions[0].listing_json) if revisions and isinstance(revisions[0].listing_json, dict) else {}
            evidence = latest_photo_analysis(ConversationRepo(db).get_messages(self.request.conversation_id)) or ""
        finally:
            db.close()
        return listing, evidence

    async def _decide(self, snapshot: dict[str, Any], listing: dict, evidence: str) -> dict[str, Any] | None:
        from vendoo_studio.services.listing_generate import collect_provider_text

        messages = [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": build_turn(self.request, snapshot, self.history, listing, evidence)},
        ]
        text = await collect_provider_text(self.provider, messages)
        action = parse_action(text)
        if action is None:
            messages += [
                {"role": "assistant", "content": text[:2000]},
                {"role": "user", "content": "That was not a JSON action. Reply with exactly one JSON object."},
            ]
            action = parse_action(await collect_provider_text(self.provider, messages))
        return action

    async def _fill(self, action: dict[str, Any], snapshot: dict[str, Any]) -> str:
        from vendoo_studio.repositories.queries import ListingRepo
        from vendoo_studio.services.auto_apply import apply_patches

        patches: list[dict[str, str]] = []
        refused: list[str] = []
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
        if not patches:
            return "refused: account settings stay as they are" if refused else "nothing to fill"

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
        note = f" (skipped account settings: {', '.join(refused)})" if refused else ""
        return ("ok, filler typed and saved" if ok else f"failed: {error or 'fill did not finish'}") + note

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
        listing, evidence = self._context()
        try:
            yield "status", "Reading the Vendoo draft…"
            first = snapshot = await self._snapshot()
        except BrowserBridgeError as exc:
            yield "final", f"I could not read the Vendoo draft: {exc}"
            return

        outcome = ""
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
            if action.get("action") in {"done", "ask"}:
                outcome = str(action.get("message") or "").strip() or ("Done." if action["action"] == "done" else "What should I change?")
                break
            label = describe_action(action)
            yield "status", f"{label}…"
            try:
                result = await self._execute(action, snapshot)
                snapshot = await self._snapshot()
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
