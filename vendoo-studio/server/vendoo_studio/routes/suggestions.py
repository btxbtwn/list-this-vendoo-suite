from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.services.suggestions import list_suggestions

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


class SuggestionCard(BaseModel):
    conversation_id: str
    kind: str
    title: str
    reason: str
    action: str
    score: int
    cover_photo_url: str | None = None


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionCard]


@router.get("", response_model=SuggestionsResponse)
def get_suggestions(db: Session = Depends(get_db)):
    return SuggestionsResponse(suggestions=[
        SuggestionCard.model_validate(card) for card in list_suggestions(db)
    ])
