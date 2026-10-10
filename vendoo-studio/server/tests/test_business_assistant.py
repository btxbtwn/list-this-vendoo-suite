"""The business assistant: what it is told about the shop, and its read-only chat."""
import json
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db, load_models
from vendoo_studio.models.ad_spend import AdSpend
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.routes import assistant as assistant_route
from vendoo_studio.services import boxes, business_assistant

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def add_listing(db, title, listing, notes=None, box_id=None):
    conv = ConversationRepo(db).create(title=title, notes=json.dumps(notes) if notes else None, box_id=box_id)
    ListingRepo(db).save_revision(conv.id, {"title": title, **listing}, source="user")
    return conv


def sold(price, market, listed, sold_at, **sale):
    return {
        "vendooStatus": "sold",
        "vendooSale": {"price": price, "marketplace": market, "soldAt": sold_at, **sale},
        "vendooDates": {"listed": listed, "sold": sold_at},
    }


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    load_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(assistant_route, "SessionLocal", factory)
    monkeypatch.setattr("vendoo_studio.services.box_scout.state_path", lambda: tmp_path / "sourcing.json")
    db = factory()
    app = FastAPI()
    app.include_router(assistant_route.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield db, client
    db.close()
    engine.dispose()


def seed(db):
    box = boxes.create_box(db, store="Raghouse", title="Mixed denim", price=80, shipping=20, pieces=10)
    add_listing(
        db, "Levi's 501 Jeans", {"price": 60, "brand": "Levi's", "category_path": "Men > Jeans"},
        sold(48, "ebay", "2026-08-01T00:00:00+00:00", "2026-09-10T00:00:00+00:00", fees=6), box_id=box.id,
    )
    add_listing(
        db, "Carhartt | Chore Coat", {"price": 120, "cost": 25, "brand": "Carhartt", "category_path": "Men > Coats"},
        {"vendooStatus": "active", "vendooDates": {"listed": "2026-07-03T00:00:00+00:00"}},
    )
    add_listing(db, "Unfinished draft", {"price": 15})
    db.add(AdSpend(marketplace="etsy", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), spend=31.0))
    db.commit()
    return box


def test_the_brief_carries_every_listing_and_the_figures_behind_it(workspace):
    db, _client = workspace
    box = seed(db)
    brief = business_assistant.business_brief(db, now=NOW)

    assert "--- Every listing (3) ---" in brief
    # The sale is a row with its box's cost share, its fees and what it cleared.
    assert f"Levi's 501 Jeans | sold | Levi's | Jeans | 60 | 10 | 48 | 6 | 32 | ebay | 2026-08-01 | 2026-09-10 | 40 | {box.id}" in brief
    # An active listing counts the days it has been up; a pipe cannot split its columns.
    assert "Carhartt / Chore Coat | active | Carhartt | Coats | 120 | 25 |  |  |  |  | 2026-07-03 |  | 90 | " in brief
    assert "Unfinished draft | draft" in brief
    for heading in ("Inventory now", "Sales, last 30 days", "Sales, all time", "Wholesale boxes bought",
                    "Ad spend the seller recorded", "Sale events", "Sourcing checks"):
        assert f"--- {heading}" in brief
    assert '"store":"Raghouse"' in brief and '"spend":31.0' in brief
    assert "--- Sourcing buy list ---\nNothing recorded." in brief


def test_rows_past_the_budget_are_left_out_and_counted(workspace, monkeypatch):
    db, _client = workspace
    seed(db)
    monkeypatch.setattr(business_assistant, "LISTING_ROWS_BUDGET", 150)
    brief = business_assistant.business_brief(db, now=NOW)
    # Sales come first, so the draft is what gives way.
    assert "Levi's 501 Jeans | sold" in brief and "Unfinished draft | draft" not in brief
    assert "2 listings did not fit" in brief


def test_a_question_is_sent_with_the_brief_and_earlier_turns(workspace):
    db, _client = workspace
    seed(db)
    business_assistant.add_message(db, "user", "What sold?")
    business_assistant.add_message(db, "assistant", "One pair of jeans.")
    business_assistant.add_message(db, "user", "For how much?")
    messages = business_assistant.build_messages(db, "For how much?", now=NOW)
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(business_assistant.INSTRUCTIONS)
    assert "Levi's 501 Jeans | sold" in messages[0]["content"]
    assert [(m["role"], m["content"]) for m in messages[1:]] == [
        ("user", "What sold?"), ("assistant", "One pair of jeans."), ("user", "For how much?"),
    ]


class Provider:
    name = "chatgpt"
    listing_model = "test-model"

    def __init__(self, pieces=("You sold ", "one item."), fail=False):
        self.pieces, self.fail, self.seen = pieces, fail, None

    async def chat(self, messages, stream=True):
        self.seen = messages
        for piece in self.pieces:
            yield piece
        if self.fail:
            raise RuntimeError("provider went away")


def test_asking_streams_the_answer_and_keeps_both_turns(workspace, monkeypatch):
    db, client = workspace
    seed(db)
    provider = Provider()
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: provider)

    response = client.post("/api/assistant/messages", json={"text": "  What sold last month?  "})
    assert response.status_code == 200
    assert "event: status\ndata: Reading your shop…" in response.text
    assert "data: You sold \n\n" in response.text and response.text.endswith("data: [DONE]\n\n")
    assert provider.seen[-1] == {"role": "user", "content": "What sold last month?"}
    assert "Levi's 501 Jeans | sold" in provider.seen[0]["content"]

    saved = client.get("/api/assistant/messages").json()
    assert [(row["role"], row["text"]) for row in saved] == [
        ("user", "What sold last month?"), ("assistant", "You sold one item."),
    ]
    assert client.delete("/api/assistant/messages").json() == {"ok": True}
    assert client.get("/api/assistant/messages").json() == []


def test_a_failed_answer_reports_the_error_and_keeps_what_arrived(workspace, monkeypatch):
    _db, client = workspace
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: Provider(pieces=("Half an",), fail=True))
    response = client.post("/api/assistant/messages", json={"text": "Anything stale?"})
    assert "event: error\ndata: provider went away" in response.text
    assert [row["text"] for row in client.get("/api/assistant/messages").json()] == ["Anything stale?", "Half an"]


def test_no_provider_or_no_question_saves_nothing(workspace, monkeypatch):
    _db, client = workspace
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: None)
    assert client.post("/api/assistant/messages", json={"text": "Hello"}).status_code == 400
    assert client.post("/api/assistant/messages", json={"text": "   "}).status_code == 422
    assert client.post("/api/assistant/messages", json={"text": ""}).status_code == 422
    assert client.get("/api/assistant/messages").json() == []
