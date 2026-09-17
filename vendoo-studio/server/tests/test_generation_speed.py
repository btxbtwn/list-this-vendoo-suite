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
from vendoo_studio.routes import chat as chat_routes
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
        messages = chat_routes._listing_messages(
            "RULES-BLOCK", "SELLER-DETAILS", "Photo analysis:\n- brand: Zara", self.db, self.conv.id,
            comps_text="COMPS-BLOCK", photo_count=3,
        )
        content = messages[0]["content"]
        self.assertTrue(content.startswith(chat_routes.LISTING_INSTRUCTIONS))
        rules = content.index("RULES-BLOCK")
        item = content.index("--- This item ---")
        self.assertLess(rules, item)
        for marker in ("uploaded 3 product photo", "SELLER-DETAILS", "brand: Zara", "COMPS-BLOCK", "Saved listing JSON"):
            self.assertGreater(content.index(marker), item)

    def test_empty_discovered_fields_are_listed_for_one_pass_fill(self):
        content = chat_routes._listing_messages("R", "", "", self.db, self.conv.id)[0]["content"]
        section = content[content.index("--- Discovered fields still empty ---"):]
        self.assertIn("- etsy: Holiday", section)
        self.assertNotIn("Pattern", section)


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
