"""The business assistant's chat. These routes read Studio's data and change none of it."""
from __future__ import annotations

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
    sse_event,
    sse_for_stream_item,
)

log = logging.getLogger("vendoo_studio.assistant")

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@router.get("/messages")
def get_messages(db: Session = Depends(get_db)):
    return [business_assistant.message_view(row) for row in business_assistant.list_messages(db)]


@router.delete("/messages")
def clear_messages(db: Session = Depends(get_db)):
    business_assistant.clear_messages(db)
    return {"ok": True}


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
        try:
            yield sse_event("status", "Reading your shop…")
            build_db = SessionLocal()
            try:
                messages = business_assistant.build_messages(build_db, question)
            finally:
                build_db.close()
            async for item in iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                payload, content = sse_for_stream_item(item)
                answer += content
                if payload:
                    yield payload
            if not answer.strip():
                yield sse_event("error", "The assistant returned an empty answer. Ask again.")
        except Exception as exc:
            log.exception("business assistant failed")
            yield sse_event("error", str(exc).strip() or type(exc).__name__)
        finally:
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
