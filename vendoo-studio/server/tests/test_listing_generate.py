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
from vendoo_studio.providers.xiaomi_mimo import StreamChunk, chunk_text, chunk_thinking
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.routes import chat as chat_routes
from vendoo_studio.services import chat_listing, listing_generation, streaming
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
        self.chat_history: list = []

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
        self.chat_history.append(messages)
        if self.chat_delay:
            await asyncio.sleep(self.chat_delay)
        for chunk in self.chunks:
            yield chunk


def _first_generate_prompt(provider) -> str:
    """Prompt from the initial generate call (before repair/finalize passes)."""
    for messages in getattr(provider, "chat_history", []) or []:
        content = str((messages[0] or {}).get("content") or "")
        if "Finish this Vendoo listing" in content or "malformed" in content.lower():
            continue
        return content
    messages = provider.chat_messages or []
    return str((messages[0] or {}).get("content") or "") if messages else ""


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

    def test_extract_softens_trailing_commas(self):
        parsed = extract_listing_json('```json\n{"title": "Tee", "price": 12,}\n```')
        self.assertEqual(parsed["title"], "Tee")
        self.assertEqual(parsed["price"], 12)

    def test_looks_like_listing_attempt(self):
        self.assertTrue(looks_like_listing_attempt('{"title": "Tee", "price":'))
        self.assertTrue(looks_like_listing_attempt("```json\n{broken\n```"))
        self.assertFalse(looks_like_listing_attempt("Sure, I can help with that."))
        self.assertFalse(looks_like_listing_attempt("Error: boom"))

    def test_seller_item_details_from_notes(self):
        notes = json.dumps({
            "sellerNotes": "Small stain near hem",
            "cog": "1.72",
            "garment": "top",
            "measurements": {
                "top": {"pitToPit": "16.5", "length": "26.5", "sleeve": "8"},
                "pants": {"waist": "15", "inseam": "5"},
            },
        })
        details = seller_item_details(notes)
        self.assertIn("Notes: Small stain near hem", details)
        self.assertIn('Measurements (top): Pit to pit: 16.5"; Length: 26.5"; Sleeve: 8"', details)
        self.assertNotIn("Inseam", details)

    def test_seller_item_details_states_the_carried_price(self):
        details = seller_item_details(json.dumps({"askingPrice": "34.00"}))
        self.assertIn("List price: $34 (the seller set this — use it exactly)", details)
        self.assertNotIn("List price", seller_item_details(json.dumps({"askingPrice": "0"})))

    def test_seller_item_details_uses_pants_for_bottoms(self):
        measurements = {"pants": {"waist": "16", "rise": "11", "inseam": "30", "legOpening": "8"}}
        pants = seller_item_details(json.dumps({"garment": "pants", "measurements": measurements}))
        self.assertIn('Measurements (pants): Waist: 16"; Rise: 11"; Inseam: 30"; Leg opening: 8"', pants)

    def test_seller_item_details_reads_legacy_shorts_as_pants(self):
        notes = json.dumps({"garment": "shorts", "measurements": {"shorts": {"waist": "15", "inseam": "5"}}})
        self.assertIn('Measurements (pants): Waist: 15"; Inseam: 5"', seller_item_details(notes))

    def test_seller_item_details_includes_carried_flaws_and_measurements(self):
        notes = json.dumps({
            "knownFlaws": "small stain near the hem",
            "descriptionMeasurements": 'Pit to pit 20"; Length 27"',
        })
        details = seller_item_details(notes)
        self.assertIn("Known flaws: small stain near the hem", details)
        self.assertIn('Measurements: Pit to pit 20"; Length 27"', details)

    def test_seller_measurement_fields_win_over_carried_text(self):
        notes = json.dumps({
            "garment": "top",
            "measurements": {"top": {"pitToPit": "16.5"}},
            "descriptionMeasurements": 'Pit to pit 20"',
        })
        details = seller_item_details(notes)
        self.assertIn('Measurements (top): Pit to pit: 16.5"', details)
        self.assertNotIn('20"', details)

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
            "sku": "SAG-HARBOR-L",
            "vendooLabels": "A19, DomStaleInventory",
            "cog": "1.72",
        })
        details = seller_item_details(notes)
        self.assertIn("Category: Clothing > Women > Tops", details)
        self.assertIn("SKU: SAG-HARBOR-L", details)
        self.assertIn("Labels: A19, DomStaleInventory", details)

    def test_listing_formula_rules_come_from_skill(self):
        from vendoo_studio.services.skill_formulas import listing_formula_rules, with_pinned_formulas

        formulas = listing_formula_rules()
        self.assertIn("TITLE Formula", formulas)
        self.assertIn("{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}", formulas)
        self.assertIn("DESCRIPTION Formula", formulas)
        self.assertIn("Flaws: {none noted or specific}", formulas)
        pinned = with_pinned_formulas("### Some other rule\nNever invent brands.")
        self.assertTrue(pinned.startswith("## Formula Reference"))
        self.assertIn("Never invent brands", pinned)

    def test_preserve_formula_copy_keeps_good_title_and_description(self):
        from vendoo_studio.services.listing_generate import _preserve_formula_copy

        original = {
            "brand": "Notations",
            "size": "XL",
            "title": "Notations XL Floral Tunic Top Black Relaxed",
            "description": (
                "Black floral tunic blouse, relaxed woven fit.\n\n"
                "Flaws: none noted. See photos for details.\n\n"
                "Measurements: Pit to pit: 21\""
            ),
        }
        updated = {
            **original,
            "title": "Beautiful Black Floral Tunic - Must See!",
            "description": "Gorgeous top, offers welcome!",
            "ebay_specifics": {"season": "Summer"},
        }
        kept = _preserve_formula_copy(
            original,
            updated,
            [{"field": "ebay_specifics.season", "message": "bad season"}],
        )
        self.assertEqual(kept["title"], original["title"])
        self.assertEqual(kept["description"], original["description"])
        self.assertEqual(kept["ebay_specifics"]["season"], "Summer")

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

    def test_persist_ready_even_when_model_prose_has_question_mark(self):
        text = (
            "Estimated shipping weight for a tee — does this look right?\n"
            "```json\n" + json.dumps(LISTING_JSON) + "\n```"
        )
        persist_generated_listing(self.db, self.conv.id, text)
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        notes = [m.text for m in messages if m.role == "system"]
        self.assertTrue(any("ready for review" in note for note in notes))
        self.assertFalse(any("Answer the questions above" in note for note in notes))

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

    def test_carried_price_wins_over_a_reinvented_one(self):
        """Regenerate rewrites the copy, not the price the seller confirmed."""
        ConversationRepo(self.db).write_notes(self.conv.id, json.dumps({"askingPrice": "34.00"}))
        parsed = persist_generated_listing(
            self.db, self.conv.id, "", parsed={**LISTING_JSON, "price": 99},
        )
        self.assertEqual(parsed["price"], 34.0)

    def test_saved_dimension_default_wins_over_model_estimate(self):
        with patch(
            "vendoo_studio.services.user_settings.package_dimensions_string",
            return_value="14x11x4",
        ):
            parsed = persist_generated_listing(
                self.db,
                self.conv.id,
                "",
                parsed={**LISTING_JSON, "package_dimensions_in": "9x6x1"},
            )
        self.assertEqual(parsed["package_dimensions_in"], "14x11x4")

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
        self.assertGreaterEqual(provider.chat_calls, 1)
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        self.assertTrue(any("repaired" in (m.text or "").lower() for m in messages))
        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertGreaterEqual(len(revisions), 1)

    def test_send_readiness_fixes_description_weight_and_dropdowns(self):
        from vendoo_studio.services.listing_generate import apply_send_readiness_fixes

        listing = {
            "title": "Notations XL Floral Tunic Top Black Relaxed",
            "description": (
                "Notations brand women's tunic. Measurements: Pit to pit: 21 inches, Length: 24 inches."
            ),
            "price": 25,
            "brand": "Notations",
            "size": "XL",
            "sku": "notations-XL",
            "condition": "Pre-Owned - Good",
            "ebay_specifics": {
                "season": "All Season",
                "type": "Blouse",
                "department": "Women",
                "sizeType": "Regular",
                "size": "XL",
                "brand": "Notations",
                "fit": "Regular",
                "material": "Cotton",
                "pattern": "Floral",
                "style": "Tunic",
                "accents": "None",
                "features": "None",
                "neckline": "Collar",
                "closure": "Button",
                "countryOfOrigin": "Unknown",
                "fabricType": "Woven",
                "garmentCare": "Unknown",
                "handmade": "No",
                "personalize": "No",
                "vintage": "No",
                "occasion": "Casual",
                "theme": "Floral",
                "unitQuantity": "1",
                "unitType": "Unit",
                "pounds": 0,
                "ounces": 8,
            },
            "depop_specifics": {"source": "Preloved", "age": "Modern", "style": "Tunic"},
            "etsy_specifics": {
                "whoMadeIt": "Another company or person",
                "whatIsIt": "A finished product",
                "whenWasItMade": "2010 - 2019 (Recently)",
            },
        }
        self.assertTrue(apply_send_readiness_fixes(listing))
        self.assertIn("Flaws:", listing["description"])
        self.assertIn("Measurements:", listing["description"])
        self.assertEqual(listing.get("weight_oz"), 8)
        self.assertEqual(listing["ebay_specifics"]["season"], "Spring")
        self.assertEqual(listing["depop_specifics"]["style"], ["Casual", "Boho", "Minimalist"])
        self.assertEqual(listing["etsy_specifics"]["who_made"], "Another company or person")

    def test_send_readiness_uses_dimension_setting_without_inventing_weight(self):
        from unittest.mock import patch

        from vendoo_studio.services.listing_generate import apply_send_readiness_fixes

        listing = {
            "title": "Unbranded L Graphic Tee Navy Regular",
            "description": "Graphic tee.\n\nFlaws: none noted.\n\nMeasurements: See photos",
        }
        with patch(
            "vendoo_studio.services.user_settings.package_dimensions_string",
            return_value="14x11x4",
        ):
            self.assertTrue(apply_send_readiness_fixes(listing))
        self.assertEqual(listing["package_dimensions_in"], "14x11x4")
        self.assertNotIn("weight_lb", listing)
        self.assertNotIn("weight_oz", listing)

        with_ounces = {**listing, "weight_oz": 8}
        self.assertTrue(apply_send_readiness_fixes(with_ounces))
        self.assertEqual(with_ounces["weight_lb"], 0)
        self.assertEqual(with_ounces["weight_oz"], 8)

    def test_send_readiness_fixes_strip_pricing_from_description(self):
        from vendoo_studio.services.listing_generate import strip_pricing_from_description

        listing = {
            "title": "Spectra S Casual Graphic Tee Black Soft",
            "description": (
                "Casual streetwear graphic cotton tee with soft short-sleeve fit; limited sold comps so "
                "price is approximate.\n\n"
                "Flaws: none noted. See photos for details.\n\n"
                "Measurements: Pit to pit: 19\""
            ),
        }
        self.assertTrue(strip_pricing_from_description(listing))
        self.assertNotIn("comps", listing["description"].lower())
        self.assertNotIn("price", listing["description"].lower())
        self.assertIn("Flaws: none noted.", listing["description"])
        self.assertIn('Measurements: Pit to pit: 19"', listing["description"])
        self.assertFalse(strip_pricing_from_description(listing))

    def test_strip_pricing_keeps_opening_line_when_only_sentence_is_pricing(self):
        from vendoo_studio.services.listing_generate import strip_pricing_from_description

        listing = {
            "title": "Spectra S Casual Graphic Tee Black Soft",
            "description": (
                "Priced to move, offers welcome.\n\n"
                "Flaws: none noted. See photos for details.\n\n"
                "Measurements: See photos"
            ),
        }
        self.assertTrue(strip_pricing_from_description(listing))
        self.assertTrue(
            listing["description"].startswith("Spectra S Casual Graphic Tee Black Soft.")
        )
        self.assertIn("Flaws:", listing["description"])

    def test_sanitize_listing_sizes_strips_approx_prefix(self):
        from vendoo_studio.services.listing_generate import (
            apply_send_readiness_fixes,
            propagate_general_size,
            sanitize_listing_sizes,
            sanitize_size_value,
        )

        self.assertEqual(sanitize_size_value("approx 10"), "10")
        self.assertEqual(sanitize_size_value("Approximately: M"), "M")
        self.assertEqual(sanitize_size_value("~ 30x29"), "30x29")
        self.assertEqual(sanitize_size_value("10"), "10")

        listing = {
            "title": "Test",
            "description": "x",
            "price": 10,
            "size": "approx 10",
            "ebay_specifics": {"size": "approx 10", "type": "Jeans"},
            "depop_specifics": {"size": "about 10", "source": "Preloved"},
        }
        self.assertTrue(sanitize_listing_sizes(listing))
        self.assertEqual(listing["size"], "10")
        self.assertEqual(listing["ebay_specifics"]["size"], "10")
        self.assertEqual(listing["depop_specifics"]["size"], "10")

        listing["size"] = "12"
        self.assertTrue(propagate_general_size(listing))
        self.assertEqual(listing["ebay_specifics"]["size"], "12")
        self.assertEqual(listing["depop_specifics"]["size"], "12")

        dirty = {
            "title": "Test Tee",
            "description": "Short description without formula markers here.",
            "price": 12,
            "size": "approx M",
            "condition": "Pre-Owned - Good",
            "ebay_specifics": {"size": "approx M"},
        }
        self.assertTrue(apply_send_readiness_fixes(dirty))
        self.assertEqual(dirty["size"], "M")
        self.assertEqual(dirty["ebay_specifics"]["size"], "M")

    def test_mens_bottoms_size_becomes_waist_by_inseam(self):
        from vendoo_studio.services.listing_generate import (
            normalize_mens_bottoms_size,
            sync_title_size,
        )

        listing = {
            "title": "Levi's 30 Y2K 501 Straight Jeans Blue Denim",
            "brand": "Levi's",
            "size": "30",
            "department": "Men",
            "description": "Y2K straight jeans.\n\nFlaws: none noted.\n\nMeasurements: Waist: 15\"; Inseam: 32\"",
            "ebay_specifics": {"type": "Jeans", "size": "30"},
        }
        self.assertTrue(normalize_mens_bottoms_size(listing))
        self.assertEqual(listing["size"], "30x32")
        self.assertTrue(sync_title_size(listing))
        self.assertEqual(listing["title"], "Levi's 30x32 Y2K 501 Straight Jeans Blue Denim")

        # The title's own waist x inseam is enough when no measurements exist.
        from_title = {
            "title": "Dickies 34x30 Workwear Carpenter Pants Tan Relaxed",
            "brand": "Dickies",
            "size": "34",
            "department": "Men",
            "description": "Workwear pants.",
        }
        self.assertTrue(normalize_mens_bottoms_size(from_title))
        self.assertEqual(from_title["size"], "34x30")

        spaced = {
            "title": "Wrangler 32 x 34 Vintage Cowboy Jeans Blue Straight",
            "brand": "Wrangler",
            "size": "32 x 34",
            "department": "Men",
            "ebay_specifics": {"type": "Jeans"},
        }
        self.assertTrue(normalize_mens_bottoms_size(spaced))
        self.assertEqual(spaced["size"], "32x34")

    def test_mens_bottoms_size_left_alone_without_an_inseam(self):
        from vendoo_studio.services.listing_generate import normalize_mens_bottoms_size

        no_inseam = {
            "title": "Levi's 30 Y2K 501 Straight Jeans Blue Denim",
            "size": "30",
            "department": "Men",
            "description": "Y2K straight jeans.\n\nMeasurements: Waist: 15\"",
            "ebay_specifics": {"type": "Jeans"},
        }
        self.assertFalse(normalize_mens_bottoms_size(no_inseam))
        self.assertEqual(no_inseam["size"], "30")

        womens = {
            "title": "Levi's 30 Y2K 501 Straight Jeans Blue Denim",
            "size": "30",
            "department": "Women",
            "description": "Measurements: Waist: 15\"; Inseam: 30\"",
            "ebay_specifics": {"type": "Jeans"},
        }
        self.assertFalse(normalize_mens_bottoms_size(womens))
        self.assertEqual(womens["size"], "30")

        mens_top = {
            "title": "Nike L Vintage Swoosh Tee Black Relaxed",
            "size": "L",
            "department": "Men",
            "description": "Measurements: Inseam: 30\"",
            "ebay_specifics": {"type": "T-Shirt"},
        }
        self.assertFalse(normalize_mens_bottoms_size(mens_top))
        self.assertEqual(mens_top["size"], "L")

    def test_sync_title_size_matches_the_size_field(self):
        from vendoo_studio.services.listing_generate import sync_title_size

        missing = {
            "title": "Nike Y2K Swoosh Tee Black Relaxed",
            "brand": "Nike",
            "size": "L",
        }
        self.assertTrue(sync_title_size(missing))
        self.assertEqual(missing["title"], "Nike L Y2K Swoosh Tee Black Relaxed")

        already = {
            "title": "Nike L Y2K Swoosh Tee Black Relaxed",
            "brand": "Nike",
            "size": "L",
        }
        self.assertFalse(sync_title_size(already))

        # A full 80-character title keeps its own wording rather than being truncated.
        packed = {
            "title": "Patagonia " + "Vintage Outdoor Fleece Snap Pullover Jacket Brown Relaxed Cozy Warm Fit",
            "brand": "Patagonia",
            "size": "XL",
        }
        self.assertFalse(sync_title_size(packed))

    def test_send_readiness_fixes_align_mens_bottoms_size_and_title(self):
        from vendoo_studio.services.listing_generate import apply_send_readiness_fixes

        listing = {
            "title": "Levi's 30 Y2K 501 Straight Jeans Blue Denim",
            "brand": "Levi's",
            "size": "approx 30",
            "department": "Men",
            "price": 48,
            "condition": "Pre-Owned - Good",
            "description": "Y2K straight jeans.\n\nFlaws: none noted. See photos for details.\n\nMeasurements: Waist: 15\"; Inseam: 32\"",
            "ebay_specifics": {"type": "Jeans", "size": "30"},
            "depop_specifics": {"size": "30", "source": "Preloved"},
        }
        self.assertTrue(apply_send_readiness_fixes(listing))
        self.assertEqual(listing["size"], "30x32")
        self.assertEqual(listing["ebay_specifics"]["size"], "30x32")
        self.assertEqual(listing["depop_specifics"]["size"], "30x32")
        self.assertEqual(listing["title"], "Levi's 30x32 Y2K 501 Straight Jeans Blue Denim")

    def test_finalize_calls_model_when_send_blockers_remain(self):
        incomplete = {
            "title": "Notations XL Floral Tunic Top Black Relaxed",
            "description": "Missing formula text without line breaks.",
            "price": 25,
            "ebay_specifics": {"season": "All Season"},
            "depop_specifics": {"source": "Preloved", "age": "Modern", "style": "Tunic"},
            "etsy_specifics": {
                "whoMadeIt": "Another company or person",
                "whatIsIt": "A finished product",
                "whenWasItMade": "2010 - 2019 (Recently)",
            },
        }
        fixed = {
            **incomplete,
            "brand": "Notations",
            "size": "XL",
            "sku": "notations-XL",
            "condition": "Pre-Owned - Good",
            "description": (
                "Black floral tunic blouse, relaxed woven fit.\n\n"
                "Flaws: none noted. See photos for details.\n\n"
                "Measurements: Pit to pit: 21\""
            ),
            "weight_lb": 0,
            "weight_oz": 8,
            "package_dimensions_in": "13x10x3",
            "ebay_specifics": {"season": "Summer"},
            "depop_specifics": {"source": "Preloved", "age": "Modern", "style": ["Casual", "Retro"]},
            "etsy_specifics": {
                "who_made": "Another company or person",
                "what_is": "A finished product",
                "when_made": "2010 - 2019 (Recently)",
            },
        }

        class Provider:
            def __init__(self):
                self.chat_calls = 0

            async def chat(self, messages, stream=True):
                self.chat_calls += 1
                yield "```json\n" + json.dumps(fixed) + "\n```"

        provider = Provider()

        async def run():
            with patch(
                "vendoo_studio.services.marketplaces.get_selected_marketplaces",
                return_value=["ebay", "depop", "etsy"],
            ):
                return await persist_generated_listing_with_repair(
                    self.db,
                    self.conv.id,
                    "```json\n" + json.dumps(incomplete) + "\n```",
                    provider,
                )

        parsed = asyncio.run(run())
        self.assertEqual(parsed.get("brand"), "Notations")
        self.assertIn("Flaws:", parsed["description"])
        self.assertGreaterEqual(provider.chat_calls, 1)
        notes = [m.text for m in ConversationRepo(self.db).get_messages(self.conv.id) if m.role == "system"]
        self.assertTrue(any("ready for review" in (note or "").lower() for note in notes))

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
        chat_listing.apply_listing_payload(self.db, self.conv.id, (
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
        chat_listing.apply_listing_payload(self.db, self.conv.id, (
            "I changed this to a men's sweatshirt.\n"
            "```json\n"
            '[{"op":"replace","path":"/category_path","value":"' + sweatshirt_path + '"},'
            '{"op":"replace","path":"/ebay_specifics/type","value":"Sweatshirt"}]\n'
            "```"
        ))
        saved = listing_repo.get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(saved["category_path"], sweatshirt_path)
        self.assertEqual(saved["ebay_specifics"]["type"], "Sweatshirt")

    def test_apply_payload_saves_missing_fields_into_listing_json(self):
        listing_repo = ListingRepo(self.db)
        listing_repo.save_revision(self.conv.id, {
            "title": "Chaos Ink Graphic Tee",
            "etsy_specifics": {"Occasion": ""},
        }, source="model")
        ops, saved = chat_listing.apply_listing_payload(self.db, self.conv.id, (
            "Filled the empty Etsy fields.\n"
            "```json\n"
            '{"missing_fields":['
            '{"marketplace":"etsy","field":"Holiday","value":"Does Not Apply"},'
            '{"marketplace":"etsy","field":"Occasion","value":"Does Not Apply"},'
            '{"marketplace":"etsy","field":"Pattern","value":"Solid"}'
            "]}\n"
            "```"
        ))
        self.assertIsNone(ops)
        self.assertTrue(saved)
        saved_listing = listing_repo.get_revisions(self.conv.id)[0].listing_json
        etsy = saved_listing["etsy_specifics"]
        self.assertEqual(etsy.get("Holiday") or etsy.get("holiday"), "Does Not Apply")
        self.assertEqual(etsy.get("Occasion") or etsy.get("occasion"), "Does Not Apply")
        self.assertEqual(etsy.get("Pattern") or etsy.get("pattern"), "Solid")
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        self.assertTrue(any("Saved to the listing JSON" in (m.text or "") for m in messages))

    def test_apply_missing_fields_repairs_and_saves_when_ask_chat_format_breaks(self):
        listing_repo = ListingRepo(self.db)
        listing_repo.save_revision(self.conv.id, {
            "title": "Chaos Ink Graphic Tee",
            "etsy_specifics": {},
        }, source="model")
        user_request = (
            'These listing fields are still empty on listing "Chaos Ink Graphic Tee". '
            "Generate values for ONLY these fields.\n\n"
            "Reply with JSON in this exact shape so Studio can save the values into the listing JSON:\n\n"
            '```json\n{"missing_fields":[{"marketplace":"etsy","field":"Pattern","value":"..."}]}\n```\n\n'
            "Empty fields:\n- Marketplace: etsy\n  Field: Pattern"
        )

        class RepairProvider:
            async def chat(self, messages, stream=True):
                yield (
                    "```json\n"
                    '{"missing_fields":[{"marketplace":"etsy","field":"Pattern","value":"Solid"}]}\n'
                    "```"
                )

        async def run():
            return await chat_listing.apply_listing_payload_with_repair(
                self.db,
                self.conv.id,
                "Pattern should be Solid for this tee.",
                RepairProvider(),
                user_message=user_request,
            )

        ops, saved = asyncio.run(run())
        self.assertIsNone(ops)
        self.assertTrue(saved)
        saved_listing = listing_repo.get_revisions(self.conv.id)[0].listing_json
        etsy = saved_listing["etsy_specifics"]
        self.assertEqual(etsy.get("Pattern") or etsy.get("pattern"), "Solid")
        messages = ConversationRepo(self.db).get_messages(self.conv.id)
        self.assertTrue(any("Saved to the listing JSON" in (m.text or "") for m in messages))


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
        listing_generation.SessionLocal = self.Session

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
            patch("vendoo_studio.services.listing_generation.load_skill_rules", return_value="rules"),
            patch("vendoo_studio.services.listing_generation.research_sold_comps", new=AsyncMock(return_value="")),
            patch("vendoo_studio.services.listing_generation.comps_search_available", return_value=False),
            patch("vendoo_studio.services.listing_generation.prepare_generation_schema", new=AsyncMock(return_value={})),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        await streaming.reset_generations()
        for p in self.patches:
            p.stop()
        app.dependency_overrides.pop(get_db, None)
        chat_routes.SessionLocal = self._orig_session
        listing_generation.SessionLocal = self._orig_session

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

    async def test_generation_pulse_repeats_status_without_bloating_history(self):
        run = streaming.GenerationRun()
        run.publish(streaming.sse_event("status", "Identifying category…"))
        queue = run.subscribe()
        while not queue.empty():
            queue.get_nowait()
        run.pulse()
        self.assertEqual(queue.get_nowait(), streaming.KEEPALIVE)
        pulsed = queue.get_nowait()
        self.assertIn("event: status", pulsed)
        self.assertIn("Identifying category", pulsed)
        self.assertEqual(
            run.history,
            [streaming.sse_event("status", "Identifying category…")],
        )

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
        self.assertEqual(self.provider.chat_calls, 4)
        prompt = _first_generate_prompt(self.provider)
        self.assertIn("already uploaded 1 product photo", prompt)
        self.assertIn("Never ask them to attach", prompt)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        conv = ConversationRepo(db).get(self.conv_id)
        self.assertGreaterEqual(len(revisions), 2)
        self.assertEqual(revisions[0].listing_json["title"], LISTING_JSON["title"])
        self.assertEqual(conv.status, "draft")
        db.close()

    async def test_generate_repairs_malformed_listing_json(self):
        class RepairingProvider(FakeProvider):
            async def chat(self, messages, stream=True):
                self.chat_calls += 1
                self.chat_messages = messages
                self.chat_history.append(messages)
                contents = " ".join(str(m.get("content") or "") for m in messages).lower()
                if "malformed" in contents or "finish this vendoo listing" in contents:
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
        self.assertIn("Filling required fields", body)
        self.assertGreaterEqual(self.provider.chat_calls, 2)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        messages = ConversationRepo(db).get_messages(self.conv_id)
        db.close()
        self.assertGreaterEqual(len(revisions), 1)
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
        prompt = _first_generate_prompt(self.provider)
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
        comps_patch = patch("vendoo_studio.services.listing_generation.research_sold_comps", new=AsyncMock(return_value=comps))
        key_patch = patch("vendoo_studio.services.listing_generation.comps_search_available", return_value=True)
        comps_patch.start()
        key_patch.start()
        self.patches[2] = comps_patch
        self.patches[3] = key_patch
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("Identifying category and looking up comps", body)
        prompt = _first_generate_prompt(self.provider)
        self.assertIn("Similar tees sold $12-$18", prompt)
        db = self.Session()
        messages = ConversationRepo(db).get_messages(self.conv_id)
        db.close()
        self.assertTrue(any((m.text or "").startswith("Sold comps:") for m in messages))

    async def test_generate_surfaces_comps_setup_when_search_unavailable(self):
        """Cursor/MiMo generate without ChatGPT must still show a SOLD COMPS card."""
        from vendoo_studio.services.comp_research import COMPS_SETUP_NOTE

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                async for _ in resp.aiter_text():
                    pass
        db = self.Session()
        messages = ConversationRepo(db).get_messages(self.conv_id)
        db.close()
        comps = [m for m in messages if (m.text or "").startswith("Sold comps:")]
        self.assertEqual(len(comps), 1)
        self.assertIn(COMPS_SETUP_NOTE, comps[0].text)
        prompt = _first_generate_prompt(self.provider)
        self.assertIn(COMPS_SETUP_NOTE, prompt)

    async def test_keepalives_emit_while_waiting_for_model(self):
        async def slow():
            await asyncio.sleep(0.2)
            yield "hello"

        items = []
        async for item in streaming.iter_with_keepalives(slow(), timeout=0.05):
            items.append(item)
        self.assertIn(None, items)
        self.assertEqual(items[-1], "hello")

    async def test_wait_task_keepalives_default_interval_is_mobile_safe(self):
        import inspect
        params = inspect.signature(streaming.wait_task_keepalives).parameters
        self.assertEqual(params["timeout"].default, 3.0)
        params = inspect.signature(streaming.iter_with_keepalives).parameters
        self.assertEqual(params["timeout"].default, 3.0)

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
            if streaming.active_generation(self.conv_id) is not None:
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
            self.assertIsNotNone(streaming.active_generation(self.conv_id))
        await streaming.wait_generation(self.conv_id)
        db = self.Session()
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        conv = ConversationRepo(db).get(self.conv_id)
        db.close()
        self.assertGreaterEqual(len(revisions), 1)
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
        self.assertEqual(self.provider.chat_calls, 2)
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
            await streaming.wait_generation(self.conv_id)
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
        self.assertIsNone(streaming.active_generation(self.conv_id))

    async def test_resume_after_run_finished_does_not_start_a_second_run(self):
        """A dropped connection reconnects; it must not generate the listing twice."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", f"/api/conversations/{self.conv_id}/generate") as resp:
                async for _ in resp.aiter_text():
                    pass
            analyze_calls = self.provider.analyze_calls
            chat_calls = self.provider.chat_calls
            async with client.stream(
                "POST", f"/api/conversations/{self.conv_id}/generate?resume=1"
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                body = "".join([chunk async for chunk in resp.aiter_text()])
        self.assertIn("[DONE]", body)
        self.assertEqual(self.provider.analyze_calls, analyze_calls)
        self.assertEqual(self.provider.chat_calls, chat_calls)

    async def test_discarded_run_stops_writing_into_the_wiped_chat(self):
        """Regenerate wipes the chat; the old run must not post cards into it."""
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
            run = streaming.active_generation(self.conv_id)
            # The run is let go of while it is mid-step, so its cancellation
            # lands only after the analysis it is waiting on comes back.
            streaming._generations.pop(self.conv_id, None)
            gate.set()
            if run and run.task:
                try:
                    await run.task
                except asyncio.CancelledError:
                    pass
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
        db = self.Session()
        messages = ConversationRepo(db).get_messages(self.conv_id)
        revisions = ListingRepo(db).get_revisions(self.conv_id)
        db.close()
        self.assertEqual([m.text for m in messages], [])
        self.assertEqual(revisions, [])


if __name__ == "__main__":
    unittest.main()
