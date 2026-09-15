from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR, skills_dir
from vendoo_studio.database import SessionLocal, get_db
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.comp_research import comps_search_available, research_sold_comps
from vendoo_studio.services.listing_generate import (
    PHOTO_ANALYSIS_RETRY_MESSAGE,
    PhotoAnalysisError,
    analysis_with_photo_count,
    extract_listing_json,
    latest_photo_analysis,
    looks_like_listing_attempt,
    persist_generated_listing_with_repair,
    photo_analysis_usable,
    repair_listing_json,
    require_photo_analysis,
    seller_item_details,
)
from vendoo_studio.services.listing_patch import apply_json_patch, extract_json_patch
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.registry import MEN_TSHIRT_PATH, WOMEN_TOPS_PATH, align_listing_gender
from vendoo_studio.services.schema_probe import prepare_generation_schema


def _require_provider():
    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(
            400,
            "Sign in with ChatGPT in Settings, or add a MiMo API key.",
        )
    return provider


def _provider_meta(provider) -> tuple[str, str]:
    return (
        getattr(provider, "name", "xiaomi-mimo"),
        getattr(provider, "listing_model", "mimo-v2.5-pro"),
    )


def _vision_meta(provider) -> tuple[str, str]:
    return (
        getattr(provider, "name", "xiaomi-mimo"),
        getattr(provider, "vision_model", "mimo-v2.5"),
    )

log = logging.getLogger("vendoo_studio.chat")

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
KEEPALIVE = ": keepalive\n\n"
_DONE = object()
_generation_tasks: set[asyncio.Task] = set()
_generations: dict[str, "_GenerationRun"] = {}


class _GenerationRun:
    def __init__(self) -> None:
        self.history: list[str] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.done = False
        self.cancelling = False
        self.last_status = ""

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        for item in self.history:
            queue.put_nowait(item)
        if self.done:
            queue.put_nowait(_DONE)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def publish(self, item: str, *, record: bool = True) -> None:
        if record and item != KEEPALIVE:
            self.history.append(item)
            if item.startswith("event: status\n"):
                for line in item.splitlines():
                    if line.startswith("data:"):
                        self.last_status = line[5:].lstrip()
                        break
        for queue in list(self.subscribers):
            queue.put_nowait(item)

    def pulse(self) -> None:
        """Keep mobile fetch/SSE alive with a comment and a status data frame.

        Comment-only keepalives are ignored by some mobile stacks, which then
        drop the connection during long category discovery waits.
        """
        self.publish(KEEPALIVE, record=False)
        if self.last_status:
            self.publish(_sse_event("status", self.last_status), record=False)

    def finish(self) -> None:
        self.done = True
        for queue in list(self.subscribers):
            queue.put_nowait(_DONE)


def _active_generation(conv_id: str) -> _GenerationRun | None:
    run = _generations.get(conv_id)
    if run and not run.done and not run.cancelling:
        return run
    return None


def stop_generation(conv_id: str, *, discard: bool = False) -> None:
    run = _generations.get(conv_id)
    if not run:
        return
    run.cancelling = True
    if run.task and not run.task.done():
        run.task.cancel()
    if discard:
        _generations.pop(conv_id, None)


def _spawn(coro) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _generation_tasks.add(task)
    task.add_done_callback(_generation_tasks.discard)
    return task


async def _pump_generation(run: _GenerationRun, work) -> None:
    try:
        await work(run)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("listing generation pump failed")
    finally:
        run.finish()


async def _follow_generation(run: _GenerationRun):
    queue = run.subscribe()
    try:
        yield KEEPALIVE
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item
    finally:
        run.unsubscribe(queue)


async def wait_generation(conv_id: str) -> None:
    run = _generations.get(conv_id)
    if run and run.task:
        try:
            await run.task
        except asyncio.CancelledError:
            pass


async def reset_generations() -> None:
    for run in list(_generations.values()):
        if run.task and not run.task.done():
            run.cancelling = True
            run.task.cancel()
    _generations.clear()
    _generation_tasks.clear()


def _stream_generation(run: _GenerationRun) -> StreamingResponse:
    return StreamingResponse(_follow_generation(run), media_type="text/event-stream", headers=SSE_HEADERS)


class ChatMessage(BaseModel):
    text: str


def _sse_encode(text: str) -> str:
    return text.replace("\n", "\ndata: ")


def _sse_data(text: str) -> str:
    return f"data: {_sse_encode(text)}\n\n"


def _sse_event(event: str, text: str) -> str:
    return f"event: {event}\n{_sse_data(text)}"


def _sse_for_stream_item(item) -> tuple[str | None, str]:
    kind, text = unpack_stream_item(item)
    if not text:
        return None, ""
    if kind == "thinking":
        return _sse_event("thinking", text), ""
    return _sse_data(text), text


def _load_skill_rules(query: str = "", db: Session | None = None) -> str:
    if db is not None and str(query or "").strip():
        from vendoo_studio.services.catalog_index import relevant_skill_rules
        return relevant_skill_rules(db, query)
    skill_md = skills_dir() / "list-this" / "SKILL.md"
    template_md = skills_dir() / "list-this" / "references" / "vendoo_listing_template.md"

    parts = []
    if skill_md.exists():
        parts.append(skill_md.read_text())
    if template_md.exists():
        parts.append(template_md.read_text())

    return "\n\n---\n\n".join(parts) if parts else ""


async def _iter_with_keepalives(source, timeout: float = 10.0):
    iterator = source.__aiter__()
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if not done:
                yield None
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration, Exception):
                pass


async def _wait_task_keepalives(task: asyncio.Task, timeout: float = 10.0):
    while not task.done():
        yield
        await asyncio.wait({task}, timeout=timeout)


def _learned_fields_prompt(db: Session, conv_id: str) -> str:
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


def _current_listing_prompt(db: Session, conv_id: str) -> str:
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


def _sync_category_override(db: Session, conv_id: str, listing: dict) -> None:
    from vendoo_studio.services.vendoo_import import merge_notes, parse_notes

    category = str((listing or {}).get("category_path") or "").strip()
    if not category:
        return
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        return
    current = str(parse_notes(conv.notes).get("categoryOverride") or "").strip()
    if not current or current == category:
        return
    conv.notes = merge_notes(conv.notes, {"categoryOverride": category})
    db.commit()


def _save_listing_revision(db: Session, conv_id: str, listing: dict, *, operations: list[dict] | None = None) -> dict:
    updated = align_listing_gender(listing, operations)
    stamped = _stamp_learned_fields(db, updated)
    revisions = ListingRepo(db).get_revisions(conv_id)
    parent_id = revisions[0].id if revisions else None
    ListingRepo(db).save_revision(
        conv_id,
        stamped,
        source="model_refinement",
        parent_revision_id=parent_id,
    )
    _sync_category_override(db, conv_id, stamped)
    return stamped


def _stamp_learned_fields(db: Session, listing: dict) -> dict:
    from vendoo_studio.services.registry import RegistryService

    if isinstance(listing, dict):
        RegistryService(db).merge_learned_fields(listing)
    return listing


async def _build_messages(conv_id: str, db: Session, user_message: str) -> list[dict]:
    repo = ConversationRepo(db)
    history = repo.get_messages(conv_id)
    photos = repo.get_photos(conv_id)
    conv = repo.get(conv_id)
    notes = (conv.notes if conv else "") or ""

    skill_rules = _load_skill_rules(user_message, db)

    photo_analysis_text = ""
    comps_text = ""
    evidence: dict = {}
    existing_analysis = latest_photo_analysis(history)
    if photos and existing_analysis and photo_analysis_usable(existing_analysis):
        photo_analysis_text = analysis_with_photo_count(len(photos), existing_analysis)
        skill_rules = _load_skill_rules(
            f"{user_message}\n{photo_analysis_text}\n{seller_item_details(notes)}",
            db,
        )
    elif photos:
        provider = get_listing_provider()
        if provider:
            paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
            try:
                result = await provider.analyze_photos(paths, notes="", listing_rules=skill_rules[:8000])
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
            skill_rules = _load_skill_rules(
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
            + "When generating a listing from scratch, explain any missing facts without claiming it is complete, "
            "then the full listing JSON in a fenced json code block.\n\n"
            "If you are not changing the listing, reply in plain English only. "
            "If asked whether the listing was updated, say yes only when a system message in this "
            "conversation confirms the listing JSON was saved; otherwise say no.\n\n"
            "Key rules:\n"
            "- Never publish. Stop at saved drafts.\n"
            "- Never ask the seller to upload or attach photos when product photos are already present.\n"
            "- Be conservative with brand and size. Ask when uncertain instead of guessing.\n"
            f"- General Vendoo category paths must use Vendoo taxonomy: women's shirts and T-shirts end at {WOMEN_TOPS_PATH}, never Shirts & Blouses. Men's T-shirts use {MEN_TSHIRT_PATH}.\n"
            "- Follow the title and description formulas EXACTLY from the rules below.\n"
            "- Resolve every applicable discovered field. Ask about unknown product facts; never invent brand, size, material, or age.\n"
            "- Estimate packaged shipping weight and mailer dimensions from the item type; do not ask the seller for those.\n"
            "- Depop: exactly 3 style tags from the allowed values list.\n"
            + (f"\n{photo_analysis_text}\n\n" if photo_analysis_text else "") +
            comps_block +
            f"\n--- Listing Rules ---\n\n{skill_rules}"
            if skill_rules
            else ""
        ) + _current_listing_prompt(db, conv_id) + _learned_fields_prompt(db, conv_id),
    }

    from vendoo_studio.repositories.queries import JobRepo
    from vendoo_studio.services.listing_completion import review_fields
    import json
    for job in JobRepo(db).list_by_conversation(conv_id):
        if job.current_step == "awaiting_answers":
            review = JobRepo(db).latest_event(job.id, "completion_review")
            if review:
                system_prompt["content"] += "\nUnresolved saved-form fields:\n" + json.dumps(
                    review_fields(review.payload or {}, job.listing_snapshot or {}), ensure_ascii=False)
                system_prompt["content"] += "\nUse the seller's answer to update these fields. Never claim completion before verification."
            break
    messages = [system_prompt]
    for msg in history[-20:]:
        role = msg.role
        if role == "model":
            role = "assistant"
        messages.append({"role": role, "content": msg.text})

    messages.append({"role": "user", "content": user_message})
    return messages


def _patch_changes_category(operations: list[dict] | None) -> bool:
    for op in operations or []:
        if not isinstance(op, dict):
            continue
        path = str(op.get("path") or "").replace("~1", "/").rstrip("/").lower()
        if path.endswith("category_path") or path.endswith("categorypath"):
            return True
    return False


def _requested_category_path(operations: list[dict] | None) -> str:
    requested = ""
    for op in operations or []:
        if not isinstance(op, dict) or op.get("op") not in {"replace", "add"}:
            continue
        path = str(op.get("path") or "").replace("~1", "/").rstrip("/").lower()
        if path.endswith("category_path") or path.endswith("categorypath"):
            requested = str(op.get("value") or "").strip()
    return requested


async def _maybe_resolve_vendoo_category(
    db: Session,
    conv_id: str,
    *,
    operations: list[dict] | None = None,
) -> None:
    if not _patch_changes_category(operations):
        return
    from vendoo_studio.services.category_lookup import resolve_listing_category

    result = await resolve_listing_category(
        db,
        conv_id,
        query=_requested_category_path(operations),
    )
    repo = ConversationRepo(db)
    if result.get("skipped"):
        return
    if result.get("ok") and result.get("path"):
        repo.add_message(
            conv_id,
            "system",
            f"Matched Vendoo category: {result['path']}",
            provider="system",
            model="",
        )
        return
    if result.get("error"):
        repo.add_message(
            conv_id,
            "system",
            f"Could not match a Vendoo category yet: {result['error']}",
            provider="system",
            model="",
        )


def _save_missing_fields(db: Session, conv_id: str, missing_fields: list[dict]) -> bool:
    from vendoo_studio.services.fill_log import (
        FillLogService,
        summarize_missing_fields,
        write_values_into_listing,
    )

    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions:
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Could not save field values — generate a listing first, then Ask chat again.",
            provider="system",
            model="",
        )
        return False
    updated = write_values_into_listing(dict(revisions[0].listing_json), missing_fields)
    _save_listing_revision(db, conv_id, updated)
    FillLogService(db).record_generated_values(conv_id, missing_fields)
    ConversationRepo(db).add_message(
        conv_id,
        "system",
        summarize_missing_fields(missing_fields),
        provider="system",
        model="",
    )
    return True


def _apply_listing_payload(db: Session, conv_id: str, full_text: str) -> tuple[list[dict] | None, bool]:
    from vendoo_studio.services.fill_log import extract_missing_fields

    missing_fields = extract_missing_fields(full_text)
    if missing_fields:
        return None, _save_missing_fields(db, conv_id, missing_fields)

    parsed_ops = extract_json_patch(full_text)
    if parsed_ops:
        lr = ListingRepo(db)
        revisions = lr.get_revisions(conv_id)
        if not revisions:
            return None, False
        updated = apply_json_patch(dict(revisions[0].listing_json), parsed_ops)
        _save_listing_revision(db, conv_id, updated, operations=parsed_ops)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Saved those changes to the listing.",
            provider="system",
            model="",
        )
        return parsed_ops, True

    parsed = extract_listing_json(full_text)
    if parsed:
        _save_listing_revision(db, conv_id, parsed)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Listing generated. Review the fields on the right.",
            provider="system",
            model="",
        )
        return None, True
    return None, False


async def _apply_listing_payload_with_repair(
    db: Session,
    conv_id: str,
    full_text: str,
    provider,
    *,
    user_message: str = "",
) -> tuple[list[dict] | None, bool]:
    from vendoo_studio.services.fill_log import (
        is_missing_fields_request,
        looks_like_missing_fields_attempt,
        repair_missing_fields,
    )

    operations, saved = _apply_listing_payload(db, conv_id, full_text)
    if saved:
        return operations, True

    ask_fields = is_missing_fields_request(user_message)
    if ask_fields or looks_like_missing_fields_attempt(full_text):
        repaired_fields = await repair_missing_fields(provider, full_text, user_message)
        if repaired_fields and _save_missing_fields(db, conv_id, repaired_fields):
            return None, True
        if ask_fields:
            ConversationRepo(db).add_message(
                conv_id,
                "system",
                "Could not save field values into the listing JSON. Retry Ask chat.",
                provider="system",
                model="",
            )
        return None, False

    if extract_listing_json(full_text):
        return None, False
    if extract_json_patch(full_text):
        return None, False
    if not looks_like_listing_attempt(full_text):
        return None, False

    repaired = await repair_listing_json(provider, full_text)
    if not repaired:
        return None, False
    _save_listing_revision(db, conv_id, repaired)
    ConversationRepo(db).add_message(
        conv_id,
        "system",
        "Repaired malformed listing JSON and saved it for review.",
        provider="system",
        model="",
    )
    return None, True


async def _persist_chat_result(
    db: Session,
    conv_id: str,
    full_text: str,
    provider,
    *,
    provider_name: str,
    provider_model: str,
    stream_error: str,
    user_message: str,
) -> tuple[list[dict] | None, bool]:
    stream_repo = ConversationRepo(db)
    usable = full_text.strip() and not full_text.lstrip().lower().startswith("error:")
    saved = False
    operations: list[dict] | None = None
    if usable and not stream_error:
        stream_repo.add_message(conv_id, "assistant", full_text, provider=provider_name, model=provider_model)
        operations, saved = await _apply_listing_payload_with_repair(
            db, conv_id, full_text, provider, user_message=user_message
        )
        if saved:
            await _maybe_resolve_vendoo_category(db, conv_id, operations=operations)
        from vendoo_studio.repositories.queries import JobRepo
        from vendoo_studio.routes.jobs import resume_completion

        for job in JobRepo(db).list_by_conversation(conv_id):
            if job.current_step == "awaiting_answers":
                try:
                    await resume_completion(job.id, db)
                except HTTPException as exc:
                    stream_repo.add_message(conv_id, "system", str(exc.detail), provider="system", model="")
                break
    elif stream_error or not full_text.strip():
        stream_repo.add_message(
            conv_id,
            "system",
            stream_error or "The listing assistant returned an empty response. Retry this prompt.",
            provider="system",
            model="",
        )

    from vendoo_studio.repositories.queries import JobRepo

    active = any(job.conversation_id == conv_id for job in JobRepo(db).get_active())
    stream_repo.update_status(conv_id, "listing" if active else "draft")
    return operations, saved


@router.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: ChatMessage, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    repo.add_message(conv_id, "user", body.text)
    provider = get_listing_provider()
    if provider is None:
        repo.add_message(
            conv_id,
            "system",
            "Sign in with ChatGPT in Settings, or add a MiMo API key, then retry this prompt.",
            provider="system",
            model="",
        )
        repo.update_status(conv_id, "draft")
        raise HTTPException(
            400,
            "Sign in with ChatGPT in Settings, or add a MiMo API key.",
        )
    provider_name, provider_model = _provider_meta(provider)

    revisions = ListingRepo(db).get_revisions(conv_id)
    if repo.get_photos(conv_id) and (not revisions or revisions[0].source == "category_analysis"
                                   or not (revisions[0].listing_json or {}).get("title")):
        # Seller answers during category discovery resume the same generation
        # pipeline; chat must not bypass the schema prerequisite.
        return await generate_listing(conv_id, db)

    repo.update_status(conv_id, "in_progress")

    try:
        messages = await _build_messages(conv_id, db, body.text)
    except PhotoAnalysisError as exc:
        repo.update_status(conv_id, "draft")
        raise HTTPException(502, str(exc)) from exc

    async def stream_response():
        stream_db = SessionLocal()
        full_text = ""
        stream_error = ""
        try:
            async for item in _iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                payload, content = _sse_for_stream_item(item)
                if content:
                    full_text += content
                if payload:
                    yield payload
            if not full_text.strip():
                stream_error = "The listing assistant returned an empty response. Retry this prompt."
                yield _sse_event("error", stream_error)

            # Persist before [DONE] so Forms/Fields refetch the updated listing JSON.
            yield _sse_event("status", "Saving listing…")
            persist_task = asyncio.create_task(
                _persist_chat_result(
                    stream_db,
                    conv_id,
                    full_text,
                    provider,
                    provider_name=provider_name,
                    provider_model=provider_model,
                    stream_error=stream_error,
                    user_message=body.text,
                )
            )
            async for _ in _wait_task_keepalives(persist_task, timeout=2.0):
                yield KEEPALIVE
            try:
                _operations, saved = persist_task.result()
            except Exception:
                log.exception("failed to persist chat result for %s", conv_id)
                try:
                    ConversationRepo(stream_db).update_status(conv_id, "draft")
                except Exception:
                    log.exception("failed to reset status after chat persist error for %s", conv_id)
                saved = False
            if saved:
                yield _sse_event("listing_updated", "1")
            yield "data: [DONE]\n\n"
        except Exception as e:
            message = str(e).strip() or type(e).__name__
            log.exception("chat stream failed for %s: %s", conv_id, message)
            stream_error = message
            yield _sse_data(f"Error: {message}")
            try:
                ConversationRepo(stream_db).update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to reset status after chat stream error for %s", conv_id)
            yield "data: [DONE]\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(stream_response(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/api/conversations/{conv_id}/analyze-photos")
async def analyze_photos(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    provider = _require_provider()
    vision_name, vision_model = _vision_meta(provider)

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to analyze")

    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]

    try:
        result = await provider.analyze_photos(paths, notes=conv.notes or "")
    except Exception as exc:
        raise HTTPException(502, PHOTO_ANALYSIS_RETRY_MESSAGE) from exc
    try:
        require_photo_analysis(result)
    except PhotoAnalysisError as exc:
        raise HTTPException(502, str(exc)) from exc

    repo.add_message(
        conv_id,
        "system",
        f"Photo analysis complete. Found: {len(photos)} photos analyzed.",
        provider=vision_name,
        model=vision_model,
    )

    return result


@router.post("/api/conversations/{conv_id}/generate")
async def generate_listing(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    provider = _require_provider()
    vision_name, vision_model = _vision_meta(provider)

    existing = _active_generation(conv_id)
    if existing is not None:
        return _stream_generation(existing)

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to generate from. Upload product photos first.")

    repo.update_status(conv_id, "in_progress")
    notes = conv.notes or ""
    item_details = seller_item_details(notes)
    seller_answers = "\n".join(message.text for message in repo.get_messages(conv_id) if message.role == "user")
    if seller_answers:
        item_details += "\nSeller answers:\n" + seller_answers
    skill_rules = _load_skill_rules(item_details, db)
    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
    photo_count = len(photos)
    # Release the request-scoped session before background work opens its own.
    db.close()

    async def run_generation(run: _GenerationRun):
        run.publish(_sse_event("status", "Analyzing photos…"))
        stream_db = SessionLocal()
        stream_repo = ConversationRepo(stream_db)
        full_text = ""
        child_tasks: list[asyncio.Task] = []
        try:
            evidence: dict = {}
            existing = latest_photo_analysis(stream_repo.get_messages(conv_id))
            listing_rules = skill_rules
            if existing:
                analysis_text = existing
            else:
                analysis_task = asyncio.create_task(
                    provider.analyze_photos(
                        paths,
                        notes=item_details,
                        listing_rules=listing_rules[:8000],
                    )
                )
                child_tasks.append(analysis_task)
                async for _ in _wait_task_keepalives(analysis_task):
                    run.pulse()
                try:
                    result = analysis_task.result()
                    evidence, analysis_text = require_photo_analysis(result)
                except PhotoAnalysisError:
                    raise
                except Exception as exc:
                    raise PhotoAnalysisError(PHOTO_ANALYSIS_RETRY_MESSAGE) from exc
                prompt_analysis = analysis_with_photo_count(photo_count, analysis_text)
                stream_repo.add_message(conv_id, "system", analysis_text, provider=vision_name, model=vision_model)

            if existing:
                prompt_analysis = analysis_with_photo_count(photo_count, analysis_text)

            listing_rules = _load_skill_rules(
                f"{prompt_analysis}\n{item_details}",
                stream_db,
            )

            run.publish(_sse_event("status", "Identifying category and discovering its fields…"))
            schema_task = asyncio.create_task(prepare_generation_schema(
                stream_db, conv_id, provider, prompt_analysis + "\nSeller answers:\n" + seller_answers, notes,
            ))
            child_tasks.append(schema_task)
            async for _ in _wait_task_keepalives(schema_task):
                run.pulse()
            schema_task.result()

            comps_text = ""
            if comps_search_available():
                run.publish(_sse_event("status", "Looking up sold comps…"))
                comps_task = asyncio.create_task(research_sold_comps(prompt_analysis, evidence))
                child_tasks.append(comps_task)
                async for _ in _wait_task_keepalives(comps_task):
                    run.pulse()
                comps_text = comps_task.result()
                if comps_text:
                    source = "chatgpt" if "Source: ChatGPT" in comps_text else "brave"
                    stream_repo.add_message(conv_id, "system", comps_text, provider=source, model="web-search")

            messages = _listing_messages(
                listing_rules,
                item_details,
                prompt_analysis,
                stream_db,
                conv_id,
                comps_text,
                photo_count=photo_count,
            )
            run.publish(_sse_event("status", "thinking"))

            async for item in _iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    run.pulse()
                    continue
                payload, content = _sse_for_stream_item(item)
                if content:
                    full_text += content
                if payload:
                    run.publish(payload)

            if not full_text.strip() or full_text.lstrip().lower().startswith("error:"):
                raise RuntimeError(full_text.strip() or "Listing generation returned no text")
            if not extract_listing_json(full_text):
                run.publish(_sse_event("status", "Repairing listing JSON…"))
            listing = await persist_generated_listing_with_repair(stream_db, conv_id, full_text, provider)
            stream_repo.update_status(conv_id, "draft")
            run.publish("data: [DONE]\n\n")
        except asyncio.CancelledError:
            log.warning("listing generation cancelled for %s; saving any completed text", conv_id)
            for task in child_tasks:
                if not task.done():
                    task.cancel()
            if full_text.strip() and not full_text.lstrip().lower().startswith("error:"):
                try:
                    await persist_generated_listing_with_repair(
                        stream_db, conv_id, full_text, provider
                    )
                except Exception:
                    log.exception("failed to persist cancelled listing for %s", conv_id)
            try:
                stream_repo.update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to reset status after cancelled listing for %s", conv_id)
            raise
        except Exception as e:
            message = str(e).strip() or type(e).__name__
            if isinstance(e, TimeoutError) and not str(e).strip():
                message = (
                    "Timed out while generating the listing. "
                    "If Chrome was discovering fields, cancel discovery and retry."
                )
            log.warning("listing generation failed for %s: %s", conv_id, message)
            try:
                run.publish(_sse_data(f"Error: {message}"))
                stream_repo.add_message(conv_id, "system", message, provider="system", model="")
                run.publish("data: [DONE]\n\n")
                stream_repo.update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to report listing generation error for %s", conv_id)
        finally:
            for task in child_tasks:
                if not task.done():
                    task.cancel()
            stream_db.close()

    run = _GenerationRun()
    _generations[conv_id] = run
    run.task = _spawn(_pump_generation(run, run_generation))
    await asyncio.sleep(0)
    return _stream_generation(run)


@router.post("/api/conversations/{conv_id}/generate/cancel")
async def cancel_generate_listing(conv_id: str):
    stop_generation(conv_id)
    db = SessionLocal()
    try:
        ConversationRepo(db).update_status(conv_id, "draft")
    finally:
        db.close()
    return {"ok": True}


@router.post("/api/conversations/{conv_id}/messages/cancel")
async def cancel_chat_message(conv_id: str):
    db = SessionLocal()
    try:
        ConversationRepo(db).update_status(conv_id, "draft")
    finally:
        db.close()
    return {"ok": True}


def _listing_messages(
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
    system_content = (
        "You are a product listing generator. Generate an evidence-backed Vendoo listing JSON "
        "from the photo analysis and listing rules below.\n\n"
        f"{photo_line}"
        "Preserve category_path and marketplace_categories from the verified category selections below. "
        "Each marketplace uses its own category tree; do not substitute another form's breadcrumb.\n\n"
        "Always include sku (BRAND-SIZE slug, e.g. DISNEY-PARKS-M), primaryColor, and secondaryColor "
        "when a second color is visible. Use Vendoo general condition values such as "
        '"Pre-Owned - Good". Keep tags to 5 or fewer. Depop needs source and age. '
        "Mercari shippingLabel must be USPS Ground Advantage.\n\n"
        "If seller-provided measurements (Pit to pit, Length, Sleeve) are given, use them exactly as-is in the description.\n"
        "Do not modify, estimate, or replace seller-provided measurements.\n"
        "Use the discovered category fields below. Leave unknown product facts empty and ask precise questions in prose. "
        "Estimate packaged shipping weight (weight_lb/weight_oz) and package_dimensions_in from the item type — "
        "do not ask the seller for routine apparel shipping weight or mailer size. "
        "Never invent brand, size, material, age, or other product facts. Completion requires saved-form verification.\n"
        "Price from the sold comps block when it is present: market price × 1.35, whole dollars. "
        "If comps are missing or thin, use a conservative baseline and flag uncertainty.\n\n"
        "Output the full listing JSON inside a fenced code block:\n\n"
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
        "```\n\n"
        f"{item_details}\n\n"
        f"{analysis_text}"
        f"{comps_block}\n\n"
        f"--- Listing Rules ---\n\n{skill_rules}"
        f"{_current_listing_prompt(db, conv_id)}"
        f"{_learned_fields_prompt(db, conv_id)}"
    )
    return [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": (
                f"Generate a complete listing from the {photo_count} uploaded product photos."
                if photo_count
                else "Generate a complete listing from these product photos."
            ),
        },
    ]
