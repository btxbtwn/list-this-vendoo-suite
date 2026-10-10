"""The business assistant's chat. These routes read Studio's data and change none of it."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vendoo_studio.database import SessionLocal, get_db
from vendoo_studio.services import business_assistant
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.streaming import (
    KEEPALIVE,
    SSE_HEADERS,
    iter_with_keepalives,
    sse_data,
    sse_event,
)
from vendoo_studio.services.user_settings import (
    MAX_BUSINESS_NOTE_CHARS,
    get_business_note,
    set_business_note,
)

log = logging.getLogger("vendoo_studio.assistant")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


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


@router.post("/messages")
async def ask(body: AssistantQuestion, db: Session = Depends(get_db)):
    question = body.text.strip()
    if not question:
        raise HTTPException(422, "Ask a question first.")
    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(400, "Sign in with ChatGPT in Settings, or add a MiMo or Cursor API key.")
    business_assistant.add_message(db, "user", question)
    # FastAPI keeps a yield dependency open until the response finishes, so the
    # request session would hold a pool connection for the whole stream.
    db.close()

    async def stream():
        answer = ""
        shop = None
        try:
            yield sse_event("status", "Reading your shop…")
            messages, shop = await asyncio.to_thread(_prepare, question)
            async for item in iter_with_keepalives(business_assistant.answer(provider, messages, shop)):
                if item is None:
                    yield KEEPALIVE
                    continue
                kind, text = item
                if kind == "text":
                    answer += text
                    yield sse_data(text)
                else:
                    yield sse_event(kind, text)
            if not answer.strip():
                yield sse_event("error", "The assistant returned an empty answer. Ask again.")
        except Exception as exc:
            log.exception("business assistant failed")
            yield sse_event("error", str(exc).strip() or type(exc).__name__)
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
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
