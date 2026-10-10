"""The business assistant: what it is told about the shop, and its read-only chat."""
import asyncio
import functools
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
    jeans = add_listing(
        db, "Levi's 501 Jeans",
        {"price": 60, "brand": "Levi's", "category_path": "Men > Jeans", "size": "34", "sku": "A-12",
         "condition": "Pre-Owned - Good", "primaryColor": "Blue", "labels": ["Bin 4"],
         "description": "Classic straight leg denim.", "ebay_specifics": {"Rise": "Mid"}},
        {**sold(48, "ebay", "2026-08-01T00:00:00+00:00", "2026-09-10T00:00:00+00:00", fees=6),
         "vendooMarketplaces": ["ebay", "depop"]},
        box_id=box.id,
    )
    coat = add_listing(
        db, "Carhartt | Chore Coat", {"price": 150, "cost": 25, "brand": "Carhartt", "category_path": "Men > Coats"},
        {"vendooStatus": "active", "vendooDates": {"listed": "2026-07-03T00:00:00+00:00"}},
    )
    ListingRepo(db).save_revision(coat.id, {"title": coat.title, "price": 120, "cost": 25, "brand": "Carhartt",
                                            "category_path": "Men > Coats"}, source="user")
    add_listing(db, "Unfinished draft", {"price": 15})
    db.add(AdSpend(marketplace="etsy", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), spend=31.0))
    db.commit()
    return box, jeans, coat


def test_the_brief_carries_every_listing_and_the_figures_behind_it(workspace):
    db, _client = workspace
    box, jeans, coat = seed(db)
    brief = business_assistant.read_shop(db, now=NOW).brief

    assert "--- Every listing (3) ---" in brief
    # The sale is a row with what it is, where it is listed, its box's cost share and what it cleared.
    assert (
        f"{jeans.id} | Levi's 501 Jeans | sold | Levi's | Jeans | 34 | Pre-Owned - Good | Blue | Bin 4 | A-12"
        f" | ebay, depop | 60 | 10 | 48 | 6 | 32 | ebay | 2026-08-01 | 2026-09-10 | 40 | {box.id}"
    ) in brief
    # An active listing counts the days it has been up; a pipe cannot split its columns.
    assert f"{coat.id} | Carhartt / Chore Coat | active | Carhartt | Coats |  |  |  |  |  |  | 120 | 25 |" in brief
    assert "| 2026-07-03 |  | 90 | " in brief
    assert "Unfinished draft | draft" in brief
    # The coat's asking price was cut once; nothing else moved.
    assert "--- Asking-price changes (1) ---" in brief
    assert f"{coat.id} | " in brief.split("--- Asking-price changes")[1] and " | 150 | 120" in brief
    for heading in ("Inventory now", "Sales, last 30 days", "Sales, all time", "Wholesale boxes bought",
                    "Ad spend the seller recorded", "Sale events", "Sourcing checks"):
        assert f"--- {heading}" in brief
    assert '"store":"Raghouse"' in brief and '"spend":31.0' in brief
    assert "--- Sourcing buy list ---\nNothing recorded." in brief
    assert "What the seller says" not in brief


def test_the_sellers_note_about_the_business_leads_the_brief(workspace, monkeypatch):
    db, client = workspace
    assert client.get("/api/assistant/note").json() == {"note": ""}
    assert client.put("/api/assistant/note", json={"note": "  I want 50% margins.  "}).json() == {
        "note": "I want 50% margins.",
    }
    brief = business_assistant.read_shop(db, now=NOW).brief
    assert "--- What the seller says about their business ---\nI want 50% margins." in brief
    assert client.put("/api/assistant/note", json={"note": "x" * 4001}).status_code == 422
    assert client.put("/api/assistant/note", json={"note": ""}).json() == {"note": ""}
    assert "What the seller says" not in business_assistant.read_shop(db, now=NOW).brief


def test_rows_past_the_budget_are_left_out_and_counted(workspace, monkeypatch):
    db, _client = workspace
    seed(db)
    monkeypatch.setattr(business_assistant, "LISTING_ROWS_BUDGET", 200)
    shop = business_assistant.read_shop(db, now=NOW)
    # Sales come first, so the draft is what gives way.
    assert "Levi's 501 Jeans | sold" in shop.brief and "Unfinished draft | draft" not in shop.brief
    assert "2 listings did not fit" in shop.brief
    # A lookup still reaches what the brief left out.
    assert "Unfinished draft" in business_assistant.run_lookup(shop.lookups, "SELECT title FROM listings")


def test_a_lookup_reads_the_copy_and_nothing_else(workspace, tmp_path):
    db, _client = workspace
    _box, jeans, coat = seed(db)
    lookups = business_assistant.read_shop(db, now=NOW).lookups

    assert business_assistant.run_lookup(
        lookups, "-- sold sizes\nSELECT size, sold_for, json_extract(details, '$.ebay_specifics.Rise') AS rise,"
                 " description FROM listings WHERE status = 'sold';",
    ) == "Lookup result (1 rows):\nsize | sold_for | rise | description\n34 | 48.0 | Mid | Classic straight leg denim."
    assert f"{coat.id} | 150.0 | 120.0" in business_assistant.run_lookup(
        lookups, "SELECT listing_id, old_price, new_price FROM price_changes")
    assert "Raghouse | 1" in business_assistant.run_lookup(lookups, "SELECT store, sold FROM boxes")

    # Nothing but reading the copy is allowed, and a mistake comes back as text the model can fix.
    for refused in (
        "DELETE FROM listings",
        "UPDATE listings SET asking = 1",
        "DROP TABLE listings",
        f"ATTACH DATABASE '{tmp_path / 'real.db'}' AS real",
        "PRAGMA database_list",
        "SELECT 1; DELETE FROM listings",
        "SELECT nope FROM listings",
    ):
        assert business_assistant.run_lookup(lookups, refused).startswith("Lookup failed:"), refused
    assert not (tmp_path / "real.db").exists()
    assert f"{jeans.id}" in business_assistant.run_lookup(lookups, "SELECT id FROM listings")


def test_a_long_result_is_cut_and_says_so(workspace, monkeypatch):
    db, _client = workspace
    seed(db)
    monkeypatch.setattr(business_assistant, "LOOKUP_ROWS", 2)
    result = business_assistant.run_lookup(business_assistant.read_shop(db, now=NOW).lookups, "SELECT title FROM listings")
    assert result.startswith("Lookup result (the first 2 rows; there are more") and len(result.splitlines()) == 4


def test_a_runaway_lookup_is_stopped(workspace, monkeypatch):
    db, _client = workspace
    monkeypatch.setattr(business_assistant, "LOOKUP_SECONDS", 0.05)
    runaway = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) FROM n"
    assert business_assistant.run_lookup(business_assistant.read_shop(db, now=NOW).lookups, runaway).startswith("Lookup failed:")


def test_a_question_is_sent_with_the_brief_and_earlier_turns(workspace):
    db, _client = workspace
    seed(db)
    business_assistant.add_message(db, "user", "What sold?")
    business_assistant.add_message(db, "assistant", "One pair of jeans.")
    business_assistant.add_message(db, "user", "For how much?")
    messages = business_assistant.build_messages(db, "For how much?", business_assistant.read_shop(db, now=NOW))
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(business_assistant.INSTRUCTIONS)
    assert "- price_changes(listing_id, changed_on, old_price, new_price)" in messages[0]["content"]
    assert "Levi's 501 Jeans | sold" in messages[0]["content"]
    assert [(m["role"], m["content"]) for m in messages[1:]] == [
        ("user", "What sold?"), ("assistant", "One pair of jeans."), ("user", "For how much?"),
    ]


def test_a_reply_is_a_lookup_only_when_it_is_nothing_else():
    assert business_assistant.lookup_sql("  ```sql\n-- sales by size\nSELECT 1\n```") == "-- sales by size\nSELECT 1"
    assert business_assistant.lookup_sql("```SQL\nSELECT 2") == "SELECT 2"
    assert business_assistant.lookup_sql("Here is how:\n```sql\nSELECT 1\n```") is None
    assert business_assistant.lookup_sql("```sql\n```") is None
    assert business_assistant.lookup_label("-- sales by size.\nSELECT 1") == "Looking up sales by size…"
    assert business_assistant.lookup_label("SELECT 1") == "Looking up more detail…"


class Provider:
    """Replies with each scripted turn in order, in pieces, and records what it was sent."""

    name = "chatgpt"
    listing_model = "test-model"

    def __init__(self, *turns, fail=False):
        self.turns, self.fail, self.calls = list(turns) or [("You sold ", "one item.")], fail, []

    @property
    def seen(self):
        return self.calls[-1]

    async def chat(self, messages, stream=True):
        self.calls.append(list(messages))
        for piece in self.turns[min(len(self.calls), len(self.turns)) - 1]:
            yield piece
        if self.fail:
            raise RuntimeError("provider went away")


def test_a_lookup_is_run_and_fed_back_before_the_answer(workspace, monkeypatch):
    db, client = workspace
    seed(db)
    provider = Provider(
        ("``", "`sql\n-- sales by size\nSELECT size, count(*) ", "FROM listings WHERE status = 'sold' GROUP BY size\n```"),
        ("Size 34 ", "sold once."),
    )
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: provider)
    response = client.post("/api/assistant/messages", json={"text": "Which sizes sell?"})

    # The seller sees what is being looked up and then the answer, never the query.
    assert "event: status\ndata: Looking up sales by size…" in response.text
    assert "sql" not in response.text and "SELECT" not in response.text
    assert provider.calls[1][-2]["role"] == "assistant" and provider.calls[1][-2]["content"].startswith("```sql")
    assert provider.calls[1][-1] == {
        "role": "user", "content": "Lookup result (1 rows):\nsize | count(*)\n34 | 1",
    }
    assert [row["text"] for row in client.get("/api/assistant/messages").json()] == ["Which sizes sell?", "Size 34 sold once."]


def test_lookups_are_capped(workspace, monkeypatch):
    _db, client = workspace
    provider = Provider(("```sql\nSELECT 1\n```",))
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: provider)
    response = client.post("/api/assistant/messages", json={"text": "Loop forever"})
    assert "event: error\ndata: The assistant kept looking things up" in response.text
    assert len(provider.calls) == business_assistant.MAX_LOOKUPS + 1
    assert provider.calls[-1][-1]["content"].endswith("Answer now with what you have.")
    assert [row["text"] for row in client.get("/api/assistant/messages").json()] == ["Loop forever"]


def test_a_short_answer_is_not_held_back(workspace, monkeypatch):
    _db, client = workspace
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: Provider(("No.",)))
    assert "data: No.\n\n" in client.post("/api/assistant/messages", json={"text": "Any sales?"}).text


def test_asking_streams_the_answer_and_keeps_both_turns(workspace, monkeypatch):
    db, client = workspace
    seed(db)
    provider = Provider()
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: provider)

    response = client.post("/api/assistant/messages", json={"text": "  What sold last month?  "})
    assert response.status_code == 200
    assert "event: status\ndata: Reading your shop…" in response.text
    assert response.text.endswith("data: You sold \n\ndata: one item.\n\n")
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
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: Provider(("Half an",), fail=True))
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


class SlowProvider:
    """Writes half an answer, then waits to be let go."""

    name = "chatgpt"
    listing_model = "test-model"

    def __init__(self):
        self.release = asyncio.Event()

    async def chat(self, messages, stream=True):
        yield "Half of it "
        await self.release.wait()
        yield "done."


async def start_answer(db, provider, question="What sold?"):
    from vendoo_studio.services.streaming import start_generation

    business_assistant.add_message(db, "user", question)
    run = start_generation(
        assistant_route.ANSWER_RUN, functools.partial(assistant_route._answer, provider=provider, question=question),
    )
    for _ in range(200):
        if any("Half" in item for item in run.history):
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("the answer never started")


async def read(response) -> str:
    return "".join([chunk async for chunk in response.body_iterator])


def test_the_answer_finishes_with_nobody_connected_and_a_late_follower_gets_all_of_it(workspace):
    db, _client = workspace

    async def scenario():
        provider = SlowProvider()
        run = await start_answer(db, provider)
        # Whoever asked has gone; someone reattaches while it is still being written.
        follower = asyncio.create_task(read(await assistant_route.resume()))
        await asyncio.sleep(0.05)
        provider.release.set()
        await run.task
        return await follower, await read(await assistant_route.resume())

    followed, afterwards = asyncio.run(scenario())
    assert followed.endswith("data: Half of it \n\ndata: done.\n\n") and "Reading your shop…" in followed
    # Once it has ended there is nothing to follow, and nothing starts a second answer.
    assert afterwards == "data: [DONE]\n\n"
    assert [row.text for row in business_assistant.list_messages(db)] == ["What sold?", "Half of it done."]


def test_stop_keeps_what_was_written_and_a_second_question_waits_its_turn(workspace, monkeypatch):
    db, client = workspace
    monkeypatch.setattr(assistant_route, "get_listing_provider", lambda: SlowProvider())

    async def scenario():
        from fastapi import HTTPException

        run = await start_answer(db, SlowProvider())
        try:
            await assistant_route.ask(assistant_route.AssistantQuestion(text="And yesterday?"), db=db)
        except HTTPException as refused:
            status = refused.status_code
        await assistant_route.stop()
        await asyncio.gather(run.task, return_exceptions=True)
        return status

    assert asyncio.run(scenario()) == 409
    assert [row.text for row in business_assistant.list_messages(db)] == ["What sold?", "Half of it "]
