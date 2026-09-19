"""Background listing generation that survives client disconnects."""

from __future__ import annotations

import asyncio
import logging
import time

from vendoo_studio.database import SessionLocal
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.chat_prompts import (
    listing_generation_messages,
    load_skill_rules,
)
from vendoo_studio.services.comp_research import (
    comps_search_available,
    research_sold_comps,
)
from vendoo_studio.services.listing_generate import (
    PHOTO_ANALYSIS_RETRY_MESSAGE,
    PhotoAnalysisError,
    analysis_with_photo_count,
    analyze_photos_with_tag_retry,
    extract_listing_json,
    latest_photo_analysis,
    listing_save_summary,
    persist_generated_listing_with_repair,
    require_photo_analysis,
)
from vendoo_studio.services.schema_probe import (
    await_deferred_schema,
    prepare_generation_schema,
)
from vendoo_studio.services.streaming import (
    GenerationRun,
    await_with_pulses,
    iter_with_keepalives,
    spawn,
    sse_data,
    sse_event,
    sse_for_stream_item,
    wait_task_keepalives,
)

log = logging.getLogger("vendoo_studio.chat")


async def run_listing_generation(
    run: GenerationRun,
    *,
    conv_id: str,
    provider,
    vision_name: str,
    vision_model: str,
    notes: str,
    item_details: str,
    seller_answers: str,
    paths: list[str],
    photo_count: int,
) -> None:
    """Analyze photos, pick categories, stream the listing, and save it."""
    run.publish(sse_event("status", "Analyzing photos…"))
    stream_db = SessionLocal()
    stream_repo = ConversationRepo(stream_db)
    skill_rules = load_skill_rules(item_details, stream_db)
    full_text = ""
    child_tasks: list[asyncio.Task] = []
    stage_started = time.monotonic()
    timings: dict[str, float] = {}

    def mark(stage: str) -> None:
        nonlocal stage_started
        now = time.monotonic()
        timings[stage] = round(now - stage_started, 2)
        stage_started = now

    try:
        evidence: dict = {}
        existing = latest_photo_analysis(stream_repo.get_messages(conv_id))
        listing_rules = skill_rules
        if existing:
            analysis_text = existing
        else:
            analysis_task = asyncio.create_task(
                analyze_photos_with_tag_retry(
                    provider,
                    paths,
                    notes=item_details,
                    listing_rules=listing_rules[:8000],
                )
            )
            child_tasks.append(analysis_task)
            async for _ in wait_task_keepalives(analysis_task):
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

        mark("photo_analysis")
        listing_rules = load_skill_rules(
            f"{prompt_analysis}\n{item_details}",
            stream_db,
        )

        if comps_search_available():
            run.publish(sse_event("status", "Identifying category and looking up comps…"))
        else:
            run.publish(sse_event("status", "Choosing marketplace categories…"))
        schema_task = asyncio.create_task(prepare_generation_schema(
            stream_db,
            conv_id,
            provider,
            prompt_analysis + "\nSeller answers:\n" + seller_answers,
            notes,
            on_status=lambda message: run.publish(sse_event("status", message)),
        ))
        child_tasks.append(schema_task)
        comps_task = None
        if comps_search_available():
            comps_task = asyncio.create_task(research_sold_comps(prompt_analysis, evidence))
            child_tasks.append(comps_task)

        pending = {schema_task, *([comps_task] if comps_task else [])}
        while pending:
            done, pending = await asyncio.wait(pending, timeout=10.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                run.pulse()
                continue
            run.pulse()
        mark("categories_and_comps")
        schema_seed = schema_task.result()
        comps_text = ""
        if comps_task is not None:
            comps_text = comps_task.result() or ""
            if comps_text:
                source = "chatgpt" if "Source: ChatGPT" in comps_text else "brave"
                stream_repo.add_message(conv_id, "system", comps_text, provider=source, model="web-search")

        messages = listing_generation_messages(
            listing_rules,
            item_details,
            prompt_analysis,
            stream_db,
            conv_id,
            comps_text,
            photo_count=photo_count,
        )
        run.publish(sse_event("status", "thinking"))

        async for item in iter_with_keepalives(provider.chat(messages, stream=True)):
            if item is None:
                run.pulse()
                continue
            payload, content = sse_for_stream_item(item)
            if content:
                full_text += content
            if payload:
                run.publish(payload)

        mark("listing_stream")
        if not full_text.strip() or full_text.lstrip().lower().startswith("error:"):
            raise RuntimeError(full_text.strip() or "Listing generation returned no text")
        if not extract_listing_json(full_text):
            run.publish(sse_event("status", "Repairing listing JSON…"))
        needed_repair = not extract_listing_json(full_text)
        run.publish(sse_event("status", "Filling required fields…"))
        listing = await await_with_pulses(
            run,
            persist_generated_listing_with_repair(
                stream_db, conv_id, full_text, provider, final_announce=False,
            ),
            child_tasks,
        )
        if listing:
            stream_repo.add_message(
                conv_id,
                "system",
                listing_save_summary(stream_db, conv_id, listing, repaired=needed_repair),
                provider="system",
                model="",
            )
        mark("repair_and_finalize")
        log.info(
            "generation timing conv=%s total=%.2fs %s",
            conv_id,
            sum(timings.values()),
            " ".join(f"{stage}={seconds}s" for stage, seconds in timings.items()),
        )
        stream_repo.update_status(conv_id, "draft")
        run.publish("data: [DONE]\n\n")
        if listing:
            evidence_text = "\n\n".join(
                part for part in (prompt_analysis, item_details, comps_text) if part
            )
            schema_meta = {
                "_schema_source": (schema_seed or {}).get("_schema_source") if isinstance(schema_seed, dict) else None,
                "_schema_probe_job_id": (schema_seed or {}).get("_schema_probe_job_id") if isinstance(schema_seed, dict) else None,
            }
            spawn(_finish_generation_background(
                conv_id,
                listing,
                evidence=evidence_text,
                schema_meta=schema_meta,
                provider=provider,
            ))
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
            stage = (run.last_status or "").strip()
            if stage:
                message = (
                    f"Timed out during “{stage}”. "
                    "Retry generate. If Chrome is stuck on field discovery, Cancel discovery first."
                )
            else:
                message = (
                    "Timed out while generating the listing. "
                    "Retry generate. If Chrome was discovering fields, cancel discovery and retry."
                )
        log.warning("listing generation failed for %s: %s", conv_id, message)
        try:
            run.publish(sse_data(f"Error: {message}"))
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


async def _finish_generation_background(
    conv_id: str,
    listing: dict,
    *,
    evidence: str,
    schema_meta: dict | None,
    provider,
) -> None:
    """Fill remaining discovered fields after the generate stream ends.

    Generation stops at a saved listing. Nothing here reaches Vendoo: the
    seller presses Send, and Send is one Vendoo API call (``vendoo-api/create``
    or ``vendoo-api/save``). An automatic push from here used to type the
    values into the Vendoo form instead, which is the old path and is gone.
    """
    db = SessionLocal()
    repo = ConversationRepo(db)
    try:
        current = dict(listing) if isinstance(listing, dict) else {}
        if isinstance(schema_meta, dict) and schema_meta.get("_schema_source") in {
            "deferred_probe",
            "deferred_busy",
        }:
            seed = {
                "_schema_source": schema_meta.get("_schema_source"),
                "_schema_probe_job_id": schema_meta.get("_schema_probe_job_id"),
            }
            await await_deferred_schema(db, seed)

        from vendoo_studio.services.listing_field_gaps import fill_listing_field_gaps

        await fill_listing_field_gaps(
            db,
            conv_id,
            current,
            provider,
            evidence=evidence,
        )
    except Exception:
        log.exception("post-generate finish failed for %s", conv_id)
        try:
            repo.add_message(
                conv_id,
                "system",
                "Listing saved, but finishing discovered fields failed. Retry generate.",
                provider="system",
                model="",
            )
        except Exception:
            log.exception("failed to report post-generate finish error for %s", conv_id)
    finally:
        db.close()
