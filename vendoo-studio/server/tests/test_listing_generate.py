from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation, Message
from vendoo_studio.models.listing import ListingRevision
from vendoo_studio.providers.xiaomi_mimo import StreamChunk, chunk_text, chunk_thinking
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.routes import chat as chat_routes
from vendoo_studio.services.listing_generate import (
    PhotoAnalysisError,
    analysis_with_photo_count,
    extract_listing_json,
    format_photo_analysis,
    latest_photo_analysis,
    looks_like_listing_attempt,
    persist_generated_listing,
    persist_generated_listing_with_repair,
    photo_analysis_usable,
    repair_listing_json,
    seller_item_details,
)
from vendoo_studio.services.registry import MEN_TSHIRT_PATH


LISTING_JSON = {
    "title": "M&O GOLD S Graphic T-Shirt Green Tie-Dye Regular",
    "description": "Graphic tee.",
    "price": 18,
}


class FakeProvider:
    def __init__(self, chunks=None, analysis=None, analyze_delay=0.0, chat_delay=0.0, analyze_gate=None):
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
        self.analyze_gate = analyze_gate
        self.analyze_calls = 0
        self.chat_calls = 0
        self.chat_messages = None

    async def analyze_photos(self, *args, **kwargs):
        self.analyze_calls += 1
        if self.analyze_gate is not None:
            await self.analyze_gate.wait()
        if self.analyze_delay:
            await asyncio.sleep(self.analyze_delay)
        return self.analysis

    async def chat(self, messages, stream=True):
        self.chat_calls += 1
        self.chat_messages = messages
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

    def test_looks_like_listing_attempt(self):
        self.assertTrue(looks_like_listing_attempt('{"title": "Tee", "price":'))
        self.assertTrue(looks_like_listing_attempt("```json\n{broken\n```"))
        self.assertFalse(looks_like_listing_attempt("Sure, I can help with that."))
        self.assertFalse(looks_like_listing_attempt("Error: boom"))

    def test_seller_item_details_from_notes(self):
        notes = json.dumps({
            "condition": "Good",
            "cog": "1.72",
            "pitToPit": "16.5",
            "length": "26.5",
            "sleeve": "8",
        })
        details = seller_item_details(notes)
        self.assertIn("Good", details)
        self.assertIn('Pit to pit: 16.5"', details)
        self.assertIn('Length: 26.5"', details)
        self.assertIn('Sleeve: 8"', details)

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

    def test_latest_photo_analysis_skips_empty_header(self):
        class Msg:
            def __init__(self, role, text):
                self.role = role
                self.text = text

        messages = [
            Msg("system", "Photo analysis:\n"),
            Msg("assistant", "I need the photos"),
        ]
        self.assertIsNone(latest_photo_analysis(messages))
        self.assertFalse(photo_analysis_usable("Photo analysis:\n"))

    def test_format_photo_analysis(self):
        text = format_photo_analysis({
            "brand": {"value": "M&O Gold"},
            "size": {"value": "S", "source": "tag"},
        })
        self.assertIn("brand: M&O Gold", text)
        self.assertIn("source: tag", text)

    def test_format_photo_analysis_accepts_string_fields(self):
        text = format_photo_analysis({"brand": "Fruit of the Loom", "size": "M"})
        self.assertIn("brand: Fruit of the Loom", text)
        self.assertIn("size: M", text)
        self.assertTrue(photo_analysis_usable(text))

    def test_analysis_with_photo_count_never_asks_for_uploads(self):
        text = analysis_with_photo_count(7, "Photo analysis:\n- brand: M&O Gold")
        self.assertIn("already uploaded 7 product photo", text)
        self.assertIn("Do not ask", text)

    def test_analysis_with_photo_count_rejects_missing_evidence(self):
        with self.assertRaisesRegex(PhotoAnalysisError, "Retry to analyze"):
            analysis_with_photo_count(7, "Photo analysis:\n")

    def test_seller_item_details_includes_category_and_labels(self):
        notes = json.dumps({
            "condition": "Good",
            "categoryOverride": "Clothing > Women > Tops",
            "vendooLabels": "A19, DomStaleInventory",
            "cog": "1.72",
        })
        details = seller_item_details(notes)
        self.assertIn("Category: Clothing > Women > Tops", details)
        self.assertIn("Labels: A19, DomStaleInventory", details)

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

    def test_chunk_thinking_reads_reasoning_content(self):
        self.assertEqual(
            chunk_thinking({"choices": [{"delta": {"reasoning_content": "looking at the photos"}}]}),
            "looking at the photos",
        )
        self.assertEqual(chunk_thinking({"choices": [{"delta": {"content": "Hello"}}]}), "")


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

    def test_persist_waits_for_seller_when_model_asks_questions(self):
        text = (
            "Please confirm the packaged shipping weight in pounds and ounces?\n"
            "```json\n" + json.dumps(LISTING_JSON) + "\n```"
        )
        persist_generated_listing(self.db, self.conv.id, text)
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        notes = [m.text for m in messages if m.role == "system"]
        self.assertTrue(any("Answer the questions above" in note for note in notes))
        self.assertFalse(any("ready for review" in note for note in notes))

    def test_generated_listing_preserves_categories_after_field_discovery(self):
        ListingRepo(self.db).save_revision(self.conv.id, {
            "category_path": "Clothing > Women's Tops",
            "marketplace_categories": {"ebay": "Fashion > Shirts"},
        }, source="fill_learned_fields")
        parsed = persist_generated_listing(self.db, self.conv.id, "", parsed={
            **LISTING_JSON, "category_path": "Wrong > Category", "marketplace_categories": {},
        })
        self.assertEqual(parsed["category_path"], "Clothing > Women's Tops")
        self.assertEqual(parsed["marketplace_categories"], {"ebay": "Fashion > Shirts"})

    def test_persist_with_repair_saves_repaired_listing(self):
        broken = 'Here is the listing:\n```json\n{"title": "Broken Tee", "price": 12,\n```'

        class RepairProvider:
            def __init__(self):
                self.chat_calls = 0

            async def chat(self, messages, stream=True):
                self.chat_calls += 1
                yield "```json\n" + json.dumps(LISTING_JSON) + "\n```"

        provider = RepairProvider()

        async def run():
            return await persist_generated_listing_with_repair(
                self.db, self.conv.id, broken, provider
            )

        parsed = asyncio.run(run())
        self.assertEqual(parsed["title"], LISTING_JSON["title"])
        self.assertEqual(provider.chat_calls, 1)
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        self.assertTrue(any("repaired" in (m.text or "").lower() for m in messages))
        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertEqual(len(revisions), 1)

    def test_repair_listing_json_skips_plain_chat(self):
        class BoomProvider:
            async def chat(self, messages, stream=True):
                raise AssertionError("should not call provider")

        async def run():
            return await repair_listing_json(BoomProvider(), "Looks good to me.")

        self.assertIsNone(asyncio.run(run()))

    def test_apply_payload_saves_mixed_json_patch_with_list_indexes(self):
        listing_repo = ListingRepo(self.db)
        self.conv.notes = json.dumps({
            "categoryOverride": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
        })
        self.db.commit()
        listing_repo.save_revision(self.conv.id, {
            "title": "Casa San Bord M Graphic T-Shirt",
            "department": "Women",
            "category_path": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
            "ebay_specifics": {"department": "Women", "Primary Store Category": "Women's Clothing"},
            "poshmark_specifics": {"styleTags": ["Graphic Tee", "Casual", "Cotton"]},
        }, source="model")
        chat_routes._apply_listing_payload(self.db, self.conv.id, (
            "This is a men's t-shirt, not women's.\n"
            "```json\n"
            '[{"op":"replace","path":"/department","value":"Men"},'
            '{"op":"replace","path":"/ebay_specifics/primaryStoreCategory","value":"Men\'s Clothing"},'
            '{"op":"replace","path":"/poshmark_specifics/styleTags/0","value":"Casual"},'
            '{"op":"replace","path":"/poshmark_specifics/styleTags/1","value":"Streetwear"},'
            '{"op":"replace","path":"/poshmark_specifics/styleTags/2","value":"Embroidered"}]\n'
            "```"
        ))
        saved = listing_repo.get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(saved["department"], "Men")
        self.assertEqual(saved["category_path"], MEN_TSHIRT_PATH)
        self.assertEqual(saved["ebay_specifics"]["department"], "Men")
        self.assertEqual(saved["ebay_specifics"]["Primary Store Category"], "Men's Clothing")
        self.assertEqual(saved["poshmark_specifics"]["styleTags"], ["Casual", "Streetwear", "Embroidered"])
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(notes["categoryOverride"], MEN_TSHIRT_PATH)
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        self.assertTrue(any("Saved those changes to the listing." in (m.text or "") for m in messages))

    def test_apply_payload_keeps_sweatshirt_category(self):
        listing_repo = ListingRepo(self.db)
        sweatshirt_path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters"
        listing_repo.save_revision(self.conv.id, {
            "title": "Fruit of the Loom M Retro Graphic Sweatshirt Blue",
            "department": "Men",
            "category_path": MEN_TSHIRT_PATH,
            "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
        }, source="model")
        chat_routes._apply_listing_payload(self.db, self.conv.id, (
            "I changed this to a men's sweatshirt.\n"
            "```json\n"
            '[{"op":"replace","path":"/category_path","value":"' + sweatshirt_path + '"},'
            '{"op":"replace","path":"/ebay_specifics/type","value":"Sweatshirt"}]\n'
            "```"
        ))
        saved = listing_repo.get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(saved["category_path"], sweatshirt_path)
        self.assertEqual(saved["ebay_specifics"]["type"], "Sweatshirt")


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
            patch("vendoo_studio.routes.chat.research_sold_comps", new=AsyncMock(return_value="")),
            patch("vendoo_studio.routes.chat.comps_search_available", return_value=False),
            patch("vendoo_studio.routes.chat.prepare_generation_schema", new=AsyncMock(return_value={})),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        await chat_routes.reset_generations()
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
        self.assertIn("event: status", body)
        self.assertIn("Analyzing photos", body)
        self.assertIn(LISTING_JSON["title"], body)

    async def test_generate_stream_forwards_thinking_without_persisting(self):
        self.provider.chunks = [
            StreamChunk("looking at the photos", "thinking"),
            "```json\n",
            json.dumps(LISTING_JSON),
            "\n```",
        ]
        transport = ASGITransport(app=app)
        body = ""
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                self.assertEqual(resp.status_code, 200)
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("event: thinking", body)
        self.assertIn("looking at the photos", body)
        db = self.Session()
        messages = ConversationRepo(db).get_messages(self.conv_id)
        assistant = [m for m in messages if m.role == "assistant"]
        db.close()
        self.assertTrue(assistant)
        self.assertNotIn("looking at the photos", assistant[0].text)
        self.assertIn(LISTING_JSON["title"], assistant[0].text)

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
        prompt = self.provider.chat_messages[0]["content"]
        self.assertIn("already uploaded 1 product photo", prompt)
        self.assertIn("Never ask them to attach", prompt)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        conv = ConversationRepo(db).get(self.conv_id)
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0].listing_json["title"], LISTING_JSON["title"])
        self.assertEqual(conv.status, "draft")
        db.close()

    async def test_generate_repairs_malformed_listing_json(self):
        class RepairingProvider(FakeProvider):
            async def chat(self, messages, stream=True):
                self.chat_calls += 1
                self.chat_messages = messages
                contents = " ".join(str(m.get("content") or "") for m in messages).lower()
                if "malformed" in contents:
                    yield "```json\n" + json.dumps(LISTING_JSON) + "\n```"
                    return
                yield '```json\n{"title": "Broken Tee", "price": 12,\n```'

        self.provider = RepairingProvider()
        self.patches[0].stop()
        provider_patch = patch("vendoo_studio.routes.chat.get_listing_provider", return_value=self.provider)
        provider_patch.start()
        self.patches[0] = provider_patch

        transport = ASGITransport(app=app)
        body = ""
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                self.assertEqual(resp.status_code, 200)
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("Repairing listing JSON", body)
        self.assertGreaterEqual(self.provider.chat_calls, 2)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        messages = ConversationRepo(db).get_messages(self.conv_id)
        db.close()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].listing_json["title"], LISTING_JSON["title"])
        self.assertTrue(any("repaired" in (m.text or "").lower() for m in messages))

    async def test_generate_reanalyzes_when_prior_analysis_was_empty(self):
        db = self.Session()
        ConversationRepo(db).add_message(self.conv_id, "system", "Photo analysis:\n")
        db.close()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                async for _ in resp.aiter_text():
                    pass
        self.assertEqual(self.provider.analyze_calls, 1)
        prompt = self.provider.chat_messages[0]["content"]
        self.assertIn("already uploaded 1 product photo", prompt)
        self.assertIn("brand: M&O Gold", prompt)

    async def test_generate_injects_sold_comps_into_prompt(self):
        comps = (
            "Sold comps:\n"
            "Query: M&O Gold Graphic T-Shirt sold comps\n"
            "- Similar tees sold $12-$18\n"
            "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
        )
        self.patches[2].stop()
        self.patches[3].stop()
        comps_patch = patch("vendoo_studio.routes.chat.research_sold_comps", new=AsyncMock(return_value=comps))
        key_patch = patch("vendoo_studio.routes.chat.comps_search_available", return_value=True)
        comps_patch.start()
        key_patch.start()
        self.patches[2] = comps_patch
        self.patches[3] = key_patch
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("Looking up sold comps", body)
        prompt = self.provider.chat_messages[0]["content"]
        self.assertIn("Similar tees sold $12-$18", prompt)
        db = self.Session()
        messages = ConversationRepo(db).get_messages(self.conv_id)
        db.close()
        self.assertTrue(any((m.text or "").startswith("Sold comps:") for m in messages))

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

    async def test_generate_stops_and_offers_retry_when_photo_analysis_fails(self):
        self.provider.analysis = {"error": "TLS connection failed", "evidence": {}}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("Error: Photo analysis failed. Retry to analyze the photos again.", body)
        self.assertEqual(self.provider.chat_calls, 0)
        db = self.Session()
        conv = ConversationRepo(db).get(self.conv_id)
        messages = ConversationRepo(db).get_messages(self.conv_id)
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        db.close()
        self.assertEqual(conv.status, "draft")
        self.assertEqual(revisions, [])
        self.assertFalse(any("contextual knowledge" in message.text for message in messages))

    async def test_message_stops_and_offers_retry_when_photo_analysis_fails(self):
        self.provider.analysis = {"error": "TLS connection failed", "evidence": {}}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/conversations/{self.conv_id}/messages",
                json={"text": "Make the listing"},
            )
        # Initial photo chat uses the streaming discovery/generation pipeline.
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "Error: Photo analysis failed. Retry to analyze the photos again.",
            resp.text,
        )
        self.assertEqual(self.provider.chat_calls, 0)
        db = self.Session()
        conv = ConversationRepo(db).get(self.conv_id)
        self.assertEqual(ListingRepo(db).get_revisions(self.conv_id), [])
        db.close()
        self.assertEqual(conv.status, "draft")

    async def test_analyze_photos_endpoint_offers_retry_on_failure(self):
        self.provider.analysis = {"error": "TLS connection failed", "evidence": {}}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/conversations/{self.conv_id}/analyze-photos")
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(
            resp.json()["detail"],
            "Photo analysis failed. Retry to analyze the photos again.",
        )

    async def _wait_until_generating(self, timeout: float = 5.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if chat_routes._active_generation(self.conv_id) is not None:
                return
            await asyncio.sleep(0.05)
        self.fail("listing generation did not start")

    async def test_generate_finishes_after_client_disconnect(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def read_stream():
                async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                    self.assertEqual(resp.status_code, 200)
                    async for _ in resp.aiter_text():
                        pass

            reader = asyncio.create_task(read_stream())
            await self._wait_until_generating()
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
            self.assertIsNotNone(chat_routes._active_generation(self.conv_id))
        await chat_routes.wait_generation(self.conv_id)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        conv = ConversationRepo(db).get(self.conv_id)
        db.close()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].listing_json["title"], LISTING_JSON["title"])
        self.assertEqual(conv.status, "draft")

    async def test_generate_reattach_reuses_in_flight_run(self):
        gate = asyncio.Event()
        self.provider.analyze_gate = gate
        body = ""
        first_body = ""
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client1,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client2,
        ):
            async def first_stream():
                async with client1.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                    return "".join([chunk async for chunk in resp.aiter_text()])

            first = asyncio.create_task(first_stream())
            await self._wait_until_generating()
            gate.set()
            async with client2.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                self.assertEqual(resp.status_code, 200)
                body = "".join([chunk async for chunk in resp.aiter_text()])
            first_body = await first
        self.assertEqual(self.provider.analyze_calls, 1)
        self.assertEqual(self.provider.chat_calls, 1)
        self.assertIn(LISTING_JSON["title"], body)
        self.assertIn(LISTING_JSON["title"], first_body)

    async def test_generate_cancel_stops_run(self):
        gate = asyncio.Event()
        self.provider.analyze_gate = gate
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def read_stream():
                async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                    async for _ in resp.aiter_text():
                        pass

            reader = asyncio.create_task(read_stream())
            await self._wait_until_generating()
            cancel = await client.post(f"/api/conversations/{self.conv_id}/generate/cancel")
            self.assertEqual(cancel.status_code, 200)
            await chat_routes.wait_generation(self.conv_id)
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
        gate.set()
        db = self.Session()
        conv = ConversationRepo(db).get(self.conv_id)
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        db.close()
        self.assertEqual(conv.status, "draft")
        self.assertEqual(revisions, [])
        self.assertIsNone(chat_routes._active_generation(self.conv_id))


if __name__ == "__main__":
    unittest.main()
