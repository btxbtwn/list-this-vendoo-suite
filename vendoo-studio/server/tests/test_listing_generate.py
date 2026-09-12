from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation, Message
from vendoo_studio.models.listing import ListingRevision
from vendoo_studio.providers.xiaomi_mimo import chunk_text
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.routes import chat as chat_routes
from vendoo_studio.services.listing_generate import (
    extract_listing_json,
    format_photo_analysis,
    latest_photo_analysis,
    persist_generated_listing,
    seller_item_details,
)


LISTING_JSON = {
    "title": "M&O GOLD S Graphic T-Shirt Green Tie-Dye Regular",
    "description": "Graphic tee.",
    "price": 18,
}


class FakeProvider:
    def __init__(self, chunks=None, analysis=None, analyze_delay=0.0, chat_delay=0.0):
        self.chunks = chunks or [
            "```json\n",
            json.dumps(LISTING_JSON),
            "\n```",
        ]
        self.analysis = analysis or {
            "evidence": {
                "brand": {"value": "M&O Gold"},
                "size": {"value": "S", "source": "tag"},
            }
        }
        self.analyze_delay = analyze_delay
        self.chat_delay = chat_delay
        self.analyze_calls = 0
        self.chat_calls = 0

    async def analyze_photos(self, *args, **kwargs):
        self.analyze_calls += 1
        if self.analyze_delay:
            await asyncio.sleep(self.analyze_delay)
        return self.analysis

    async def chat(self, messages, stream=True):
        self.chat_calls += 1
        if self.chat_delay:
            await asyncio.sleep(self.chat_delay)
        for chunk in self.chunks:
            yield chunk


class ListingGenerateHelpersTest(unittest.TestCase):
    def test_extracts_fenced_json(self):
        text = "Here you go\n```json\n" + json.dumps(LISTING_JSON) + "\n```\n"
        parsed = extract_listing_json(text)
        self.assertEqual(parsed["title"], LISTING_JSON["title"])

    def test_extracts_raw_json(self):
        parsed = extract_listing_json(json.dumps(LISTING_JSON))
        self.assertEqual(parsed["price"], 18)

    def test_rejects_error_text(self):
        self.assertIsNone(extract_listing_json("Error: timeout"))

    def test_seller_item_details_from_notes(self):
        notes = json.dumps({"condition": "Good", "cog": "1.72", "pitToPit": "16.5", "length": "26.5"})
        details = seller_item_details(notes)
        self.assertIn("Good", details)
        self.assertIn('Pit to pit: 16.5"', details)

    def test_latest_photo_analysis(self):
        class Msg:
            def __init__(self, role, text):
                self.role = role
                self.text = text

        messages = [
            Msg("system", "Photo analysis:\n- brand: M&O Gold"),
            Msg("assistant", "working"),
        ]
        self.assertTrue(latest_photo_analysis(messages).startswith("Photo analysis:"))

    def test_format_photo_analysis(self):
        text = format_photo_analysis({
            "brand": {"value": "M&O Gold"},
            "size": {"value": "S", "source": "tag"},
        })
        self.assertIn("brand: M&O Gold", text)
        self.assertIn("source: tag", text)

    def test_chunk_text_reads_delta_content(self):
        self.assertEqual(chunk_text({"choices": [{"delta": {"content": "Hello"}}]}), "Hello")

    def test_chunk_text_raises_on_error_payload(self):
        with self.assertRaises(RuntimeError):
            chunk_text({"error": {"message": "context length exceeded"}})

    def test_chunk_text_ignores_reasoning_only_delta(self):
        self.assertEqual(
            chunk_text({"choices": [{"delta": {"reasoning_content": "thinking"}}]}),
            "",
        )


class PersistListingTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        repo = ConversationRepo(self.db)
        self.conv = repo.create(title="New Listing")

    def tearDown(self):
        self.db.close()

    def test_persist_saves_revision_from_fenced_json(self):
        text = "```json\n" + json.dumps(LISTING_JSON) + "\n```"
        parsed = persist_generated_listing(self.db, self.conv.id, text)
        self.assertEqual(parsed["title"], LISTING_JSON["title"])
        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertEqual(len(revisions), 1)
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        self.assertTrue(any(m.role == "assistant" for m in messages))
        self.assertTrue(any("Listing extracted" in m.text for m in messages))


class GenerateStreamTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.provider = FakeProvider(analyze_delay=0.25)
        self._orig_session = chat_routes.SessionLocal
        chat_routes.SessionLocal = self.Session

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        db = self.Session()
        repo = ConversationRepo(db)
        conv = repo.create(title="New Listing")
        repo.add_photo(conv.id, "a.jpg", "a.jpg", "image/jpeg", 10)
        self.conv_id = conv.id
        db.close()

        self.patches = [
            patch("vendoo_studio.routes.chat.get_listing_provider", return_value=self.provider),
            patch("vendoo_studio.routes.chat._load_skill_rules", return_value="rules"),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        app.dependency_overrides.pop(get_db, None)
        chat_routes.SessionLocal = self._orig_session

    async def test_generate_stream_includes_keepalive_and_listing(self):
        transport = ASGITransport(app=app)
        body = ""
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                self.assertEqual(resp.status_code, 200)
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn(": keepalive", body)
        self.assertIn(LISTING_JSON["title"], body)

    async def test_generate_persists_listing_and_skips_repeat_analysis(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                async for _ in resp.aiter_text():
                    pass
            self.assertEqual(self.provider.analyze_calls, 1)
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                async for _ in resp.aiter_text():
                    pass
        self.assertEqual(self.provider.analyze_calls, 1)
        self.assertEqual(self.provider.chat_calls, 2)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        conv = ConversationRepo(db).get(self.conv_id)
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0].listing_json["title"], LISTING_JSON["title"])
        self.assertEqual(conv.status, "draft")
        db.close()

    async def test_keepalives_emit_while_waiting_for_model(self):
        async def slow():
            await asyncio.sleep(0.2)
            yield "hello"

        items = []
        async for item in chat_routes._iter_with_keepalives(slow(), timeout=0.05):
            items.append(item)
        self.assertIn(None, items)
        self.assertEqual(items[-1], "hello")

    async def test_generate_reports_error_when_model_returns_nothing(self):
        self.provider.chunks = []
        transport = ASGITransport(app=app)
        body = ""
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("Error:", body)
        db = self.Session()
        conv = ConversationRepo(db).get(self.conv_id)
        self.assertEqual(conv.status, "draft")
        self.assertEqual(ListingRepo(db).get_revisions(self.conv_id), [])
        db.close()


if __name__ == "__main__":
    unittest.main()
