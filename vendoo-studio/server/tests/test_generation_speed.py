from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategorySchema
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ListingRepo
from vendoo_studio.services import chat_prompts
from vendoo_studio.services.listing_generate import collect_provider_text, repair_listing_json


class ListingPromptOrderTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = Conversation(title="Blouse")
        self.db.add(self.conv)
        self.db.add(CategorySchema(
            general_path="Clothing > Tops",
            marketplace="etsy",
            category_path="Clothing > Tops > Blouses",
            fields=[
                {"label": "Pattern", "required": True, "options": ["Solid", "Floral"]},
                {"label": "Holiday", "required": False},
            ],
        ))
        self.db.commit()
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {"category_path": "Clothing > Tops", "etsy_specifics": {"pattern": "Solid"}},
            source="category_analysis",
        )

    def test_static_rules_lead_and_item_evidence_follows(self):
        messages = chat_prompts.listing_generation_messages(
            "RULES-BLOCK", "SELLER-DETAILS", "Photo analysis:\n- brand: Zara", self.db, self.conv.id,
            comps_text="COMPS-BLOCK", photo_count=3,
        )
        content = messages[0]["content"]
        self.assertTrue(content.startswith(chat_prompts.LISTING_INSTRUCTIONS))
        rules = content.index("RULES-BLOCK")
        item = content.index("--- This item ---")
        self.assertLess(rules, item)
        for marker in ("uploaded 3 product photo", "SELLER-DETAILS", "brand: Zara", "COMPS-BLOCK", "Saved listing JSON"):
            self.assertGreater(content.index(marker), item)

    def test_empty_discovered_fields_are_listed_for_one_pass_fill(self):
        content = chat_prompts.listing_generation_messages("R", "", "", self.db, self.conv.id)[0]["content"]
        section = content[content.index("--- Discovered fields still empty ---"):]
        self.assertIn("- etsy: Holiday", section)
        self.assertNotIn("Pattern", section)

    def test_prompt_requires_vendoo_general_color_options(self):
        self.assertIn("Colors must be exact Vendoo General dropdown values", chat_prompts.LISTING_INSTRUCTIONS)
        self.assertIn("Use Blue for navy", chat_prompts.LISTING_INSTRUCTIONS)

    def test_first_generation_receives_required_flags_and_exact_allowed_options(self):
        ListingRepo(self.db).save_revision(self.conv.id, {"category_path": "Clothing > Tops"}, source="category_analysis")
        content = chat_prompts.listing_generation_messages("R", "", "", self.db, self.conv.id)[0]["content"]
        section = content[content.index("--- Discovered fields still empty ---"):]
        self.assertIn('etsy: Pattern (required) — allowed options: ["Solid", "Floral"]', section)

    def test_api_schema_options_reach_first_generation_and_large_lists_are_bounded(self):
        from vendoo_studio.services.vendoo_specifics import FieldSpec

        spec = FieldSpec("style", display="Style", required=True, options={
            **{str(i): f"Other option {i}" for i in range(200)},
            "floral": "Floral Blouse", "none": "Does Not Apply",
        })
        with (
            patch("vendoo_studio.services.listing_field_gaps.listing_category_ids", return_value={"ebay": "123"}),
            patch("vendoo_studio.services.listing_field_gaps.load_fields", return_value={"style": spec}),
        ):
            content = chat_prompts.listing_generation_messages(
                "R", "", "Photo analysis:\n- style: Floral Blouse", self.db, self.conv.id,
            )[0]["content"]
        section = content[content.index("--- Discovered fields still empty ---"):]
        self.assertIn("ebay: Style (required)", section)
        self.assertIn("Floral Blouse", section)
        self.assertIn("relevant subset", section)
        self.assertLess(section.count("Other option"), 30)


class _QuickProvider:
    def __init__(self):
        self.quick_calls = 0
        self.chat_calls = 0

    async def quick_chat(self, messages):
        self.quick_calls += 1
        yield '```json\n{"title": "Fixed", "price": 20}\n```'

    async def chat(self, messages, stream=True):
        self.chat_calls += 1
        yield "slow"


class _PlainProvider:
    async def chat(self, messages, stream=True):
        yield "plain"


class QuickRepairTest(unittest.TestCase):
    def test_json_repair_uses_quick_path(self):
        provider = _QuickProvider()
        parsed = asyncio.run(repair_listing_json(provider, '```json\n{"title": "Broken", "price": 20,,\n```'))
        self.assertEqual(parsed["title"], "Fixed")
        self.assertEqual((provider.quick_calls, provider.chat_calls), (1, 0))

    def test_providers_without_quick_path_use_chat(self):
        self.assertEqual(asyncio.run(collect_provider_text(_PlainProvider(), [], quick=True)), "plain")


class CodexPayloadTest(unittest.TestCase):
    def test_payload_carries_prompt_cache_key(self):
        from vendoo_studio.providers import chatgpt_codex

        with patch.object(chatgpt_codex, "resolved_chatgpt_models", return_value=("gpt-5.5", "gpt-5.5")), \
                patch.object(chatgpt_codex, "resolved_chatgpt_reasoning", return_value="low"):
            provider = chatgpt_codex.ChatGPTCodexProvider()
        payload = provider._payload([{"role": "user", "content": "hi"}], "gpt-5.5", True)
        self.assertEqual(payload["prompt_cache_key"], chatgpt_codex.PROMPT_CACHE_KEY)
