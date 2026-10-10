"""The business assistant's chat. These routes read Studio's data and change none of it."""
from __future__ import annotations

import asyncio
import functools
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import SessionLocal, get_db
from vendoo_studio.services import business_assistant
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.streaming import (
    GenerationRun,
    active_generation,
    await_with_pulses,
    iter_with_keepalives,
    sse_data,
    sse_event,
    start_generation,
    stop_generation,
    stream_finished,
    stream_generation,
    wait_generation,
)
from vendoo_studio.services.user_settings import (
    MAX_BUSINESS_NOTE_CHARS,
    get_business_note,
    set_business_note,
)

log = logging.getLogger("vendoo_studio.assistant")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# The one answer that can be in progress, in the registry listing generations use.
ANSWER_RUN = "assistant"


class AssistantQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class BusinessNote(BaseModel):
    note: str = Field(max_length=MAX_BUSINESS_NOTE_CHARS)


@router.get("/messages")
def get_messages(db: Session = Depends(get_db)):
    return [business_assistant.message_view(row) for row in business_assistant.list_messages(db)]


@router.delete("/messages")
def clear_messages(db: Session = Depends(get_db)):
    business_assistant.clear_messages(db)
    return {"ok": True}


@router.get("/note")
def get_note():
    return {"note": get_business_note()}


@router.put("/note")
def save_note(body: BusinessNote):
    return {"note": set_business_note(body.note)}


def _prepare(question: str):
    """Read the shop and build the prompt, on a worker thread with its own session."""
    db = SessionLocal()
    try:
        shop = business_assistant.read_shop(db)
        return business_assistant.build_messages(db, question, shop), shop
    finally:
        db.close()


async def _answer(run: GenerationRun, provider, question: str) -> None:
    """Answer in the background and publish each piece to whoever is following.

    The answer belongs to Studio, not to the connection that asked: a phone
    that locks or drops off the network mid-answer finds it when it comes back.
    """
    answer = ""
    shop = None
    try:
        run.publish(sse_event("status", "Reading your shop…"))
        messages, shop = await await_with_pulses(run, asyncio.to_thread(_prepare, question), [])
        async for item in iter_with_keepalives(business_assistant.answer(provider, messages, shop)):
            if item is None:
                # A comment alone does not keep some mobile connections open; pulse repeats the status too.
                run.pulse()
                continue
            kind, text = item
            if kind == "text":
                answer += text
                run.publish(sse_data(text))
            else:
                run.publish(sse_event(kind, text))
        if not answer.strip():
            run.publish(sse_event("error", "The assistant returned an empty answer. Ask again."))
    except Exception as exc:
        log.exception("business assistant failed")
        run.publish(sse_event("error", str(exc).strip() or type(exc).__name__))
    finally:
        if shop is not None:
            shop.lookups.close()
        # Also reached when the seller presses Stop: keep what was written so far.
        if answer.strip():
            save_db = SessionLocal()
            try:
                business_assistant.add_message(
                    save_db, "assistant", answer,
                    provider=getattr(provider, "name", None),
                    model=getattr(provider, "listing_model", None),
                )
            finally:
                save_db.close()


@router.post("/messages")
async def ask(body: AssistantQuestion, db: Session = Depends(get_db)):
    question = body.text.strip()
    if not question:
        raise HTTPException(422, "Ask a question first.")
    if active_generation(ANSWER_RUN) is not None:
        raise HTTPException(409, "The assistant is still answering your last question.")
    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(400, "Sign in with ChatGPT in Settings, or add a MiMo or Cursor API key.")
    business_assistant.add_message(db, "user", question)
    # Release the request-scoped session before background work opens its own.
    db.close()
    run = start_generation(ANSWER_RUN, functools.partial(_answer, provider=provider, question=question))
    await asyncio.sleep(0)
    return stream_generation(run)


@router.post("/messages/resume")
async def resume():
    """Follow the answer in progress from its start, or finish at once when there is none."""
    run = active_generation(ANSWER_RUN)
    return stream_generation(run) if run is not None else stream_finished()


@router.post("/messages/stop")
async def stop():
    stop_generation(ANSWER_RUN)
    # What was written so far is saved as the run unwinds; answer once it is there to read.
    await wait_generation(ANSWER_RUN)
    return {"ok": True}
