"""Chat-directed fix agent on the open Vendoo draft."""
from __future__ import annotations

import asyncio
import copy
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import browser_bridge
from vendoo_studio.services.browser_agent import (
    SAVE_SELECTOR,
    FixAgent,
    FixRequest,
    field_changes,
    parse_action,
)


def field(marketplace, label, value="", **extra):
    return {
        "marketplace": marketplace,
        "label": label,
        "key": label.lower(),
        "selector": f"#listings\\\\.{marketplace}\\\\.{label.lower().replace(' ', '')}",
        "value": value,
        "filled": bool(value),
        "rect": {"x": 10, "y": 100, "width": 200, "height": 40},
        **extra,
    }


class FakeDraft:
    """A tiny Vendoo form that reacts to the agent's browser actions."""

    def __init__(self):
        self.fields = [field("general", "Title", "Vintage Tee"), field("ebay", "Return Policy", account_managed=True)]
        self.hidden = [field("ebay", "Neckline")]
        self.focused = None
        self.saved = 0
        self.actions: list[dict] = []

    async def snapshot(self, job):
        return {
            "ok": True,
            "viewport": {"width": 800, "height": 600},
            "fields": copy.deepcopy(self.fields),
            "controls": [{"text": "Show optional fields"}] if self.hidden else [],
            "open_options": [],
        }

    async def act(self, job, payload):
        self.actions.append(payload)
        if payload.get("text") == "Show optional fields" and payload["action"] == "click":
            self.fields += self.hidden
            self.hidden = []
            return {"ok": True}
        if payload["action"] == "click" and payload.get("selector") == SAVE_SELECTOR:
            self.saved += 1
            return {"ok": True}
        if payload["action"] == "click" and payload.get("selector"):
            self.focused = next((f for f in self.fields if f["selector"] == payload["selector"]), None)
            return {"ok": bool(self.focused)}
        if payload["action"] == "type" and self.focused:
            self.focused["value"] += payload["text"]
            return {"ok": True}
        return {"ok": False, "error": "unexpected action"}


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, stream=True):
        self.calls += 1
        yield self.replies.pop(0) if self.replies else '{"action":"done","message":"Nothing left."}'


class CapturingProvider(ScriptedProvider):
    """Keeps every turn the agent built, so tests can read what the model saw."""

    def __init__(self, replies):
        super().__init__(replies)
        self.turns: list[str] = []

    async def chat(self, messages, stream=True):
        self.turns.append(messages[1]["content"])
        async for item in super().chat(messages, stream=stream):
            yield item


class AgentTestBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        conv = ConversationRepo(db).create(title="Tee")
        revision = ListingRepo(db).save_revision(conv.id, {"title": "Vintage Tee", "ebay_specifics": {}}, source="user")
        job = JobRepo(db).create(conv_id=conv.id, approved_revision_id=revision.id,
                                 listing_snapshot={"title": "Vintage Tee", "platforms": ["ebay"]},
                                 vendoo_item_id="draft-1", status="completed")
        self.conv_id, self.job_id = conv.id, job.id
        db.close()
        self.draft = FakeDraft()
        self.patches = [
            patch.object(browser_bridge, "snapshot", side_effect=self.draft.snapshot),
            patch.object(browser_bridge, "act", side_effect=self.draft.act),
            patch("vendoo_studio.services.browser_agent.SETTLE_SEC", 0),
            patch("vendoo_studio.services.browser_agent.SAVE_SETTLE_SEC", 0),
        ]
        for item in self.patches:
            item.start()
        browser_bridge._last_human_input.clear()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def run_agent(self, provider, instruction="Set the neckline to Crew Neck", picked=None):
        request = FixRequest(job_id=self.job_id, conversation_id=self.conv_id, instruction=instruction, picked=picked or [])
        agent = FixAgent(request, provider, db_factory=self.Session)

        async def collect():
            return [item async for item in agent.run()]

        return asyncio.run(collect())


class FixAgentLoopTest(AgentTestBase):
    def test_opens_section_types_value_and_saves_before_reporting(self):
        provider = ScriptedProvider([
            '{"action":"click","text":"Show optional fields"}',
            '```json\n{"action":"click_field","marketplace":"ebay","field":"Neckline"}\n```',
            '{"action":"type","text":"Crew Neck"}',
            '{"action":"done","message":"Neckline is now Crew Neck."}',
        ])
        events = self.run_agent(provider)
        final = events[-1]
        self.assertEqual(final[0], "final")
        self.assertIn("Neckline is now Crew Neck.", final[1])
        self.assertIn("eBay / Neckline: empty → Crew Neck", final[1])
        self.assertEqual(self.draft.saved, 1, "raw edits must be saved even when the model forgets")
        self.assertIn(("status", "Clicking \"Show optional fields\"…"), events)
        self.assertEqual(provider.calls, 4)

    def test_fill_skips_account_settings_and_uses_live_selector(self):
        provider = ScriptedProvider([
            json.dumps({"action": "fill", "fields": [
                {"marketplace": "general", "field": "Title", "value": "Vintage Tee 90s"},
                {"marketplace": "ebay", "field": "Return Policy", "value": "30 days"},
            ]}),
            '{"action":"done","message":"Updated the title."}',
        ])

        async def apply(db, job, listing, patches, announce=True):
            self.assertFalse(announce)
            self.draft.fields[0]["value"] = patches[0]["value"]
            return True, None

        with patch("vendoo_studio.services.auto_apply.apply_patches", side_effect=apply) as applied:
            final = self.run_agent(provider, "Add 90s to the title")[-1][1]
        patches = applied.call_args.args[3]
        self.assertEqual(patches, [{"marketplace": "general", "field": "Title", "value": "Vintage Tee 90s",
                                    "selector": self.draft.fields[0]["selector"]}])
        self.assertIn("skipped account settings: Return Policy", final)
        self.assertIn("Vendoo / Title: Vintage Tee → Vintage Tee 90s", final)
        db = self.Session()
        latest = ListingRepo(db).get_revisions(self.conv_id)[0]
        db.close()
        self.assertEqual(latest.source, "browser_fix")
        self.assertEqual(latest.listing_json["title"], "Vintage Tee 90s")
        self.assertEqual(self.draft.saved, 0, "the filler saves on its own")

    def test_click_field_refuses_account_setting(self):
        provider = ScriptedProvider([
            '{"action":"click_field","marketplace":"ebay","field":"Return Policy"}',
            '{"action":"done","message":"Left it."}',
        ])
        final = self.run_agent(provider)[-1][1]
        self.assertIn("refused: account settings stay as they are", final)
        self.assertEqual(self.draft.actions, [])

    def test_pauses_when_seller_takes_over(self):
        provider = ScriptedProvider(['{"action":"click","text":"Show optional fields"}'])
        browser_bridge._last_human_input[self.job_id] = time.monotonic() + 60
        final = self.run_agent(provider)[-1][1]
        self.assertIn("Paused because you started using the draft", final)
        self.assertEqual(provider.calls, 0)

    def test_stops_after_two_unusable_replies(self):
        provider = ScriptedProvider(["I will fix it now.", "Sure thing!"])
        final = self.run_agent(provider)[-1][1]
        self.assertIn("did not return a usable action", final)
        self.assertEqual(provider.calls, 2)

    def test_ask_returns_question_without_acting(self):
        provider = ScriptedProvider(['{"action":"ask","message":"Which size, M or L?"}'])
        final = self.run_agent(provider, "fix the size")[-1][1]
        self.assertEqual(final, "Which size, M or L?")
        self.assertEqual(self.draft.actions, [])

    def test_early_ask_about_pointed_empty_fields_is_pushed_back_once(self):
        self.draft.fields += self.draft.hidden
        self.draft.hidden = []
        provider = ScriptedProvider([
            '{"action":"ask","message":"Which material should I pick?"}',
            '{"action":"ask","message":"Still unsure about material."}',
        ])
        picked = [{"marketplace": "ebay", "label": "Neckline", "value": ""}]
        final = self.run_agent(provider, "fill these", picked)[-1][1]
        self.assertTrue(final.startswith("Still unsure about material."))
        self.assertIn("not yet: fill every pointed-at field", final)
        self.assertEqual(provider.calls, 2)

    def test_fill_with_pointed_fields_skips_others_and_checks_the_form(self):
        self.draft.fields += self.draft.hidden
        self.draft.hidden = []
        provider = ScriptedProvider([
            json.dumps({"action": "fill", "fields": [
                {"marketplace": "general", "field": "Title", "value": "Other"},
                {"marketplace": "ebay", "field": "Neckline", "value": "V-Neck"},
            ]}),
            '{"action":"done","message":"Tried."}',
        ])

        async def silent(db, job, listing, patches, announce=True):
            return True, None

        picked = [{"marketplace": "ebay", "label": "Neckline", "value": ""}]
        with patch("vendoo_studio.services.auto_apply.apply_patches", side_effect=silent) as applied:
            final = self.run_agent(provider, "fill these", picked)[-1][1]
        self.assertEqual([p["field"] for p in applied.call_args.args[3]], ["Neckline"])
        self.assertIn("failed: the form still shows these empty: Neckline", final)
        self.assertIn("skipped fields the seller did not point at: Title", final)

    def test_empty_fields_are_listed_and_survive_the_prompt_cap(self):
        from vendoo_studio.services.browser_agent import MAX_PROMPT_FIELDS, build_turn

        # A draft with every marketplace open has more fields than fit in one prompt.
        filled = [field("ebay", f"Spec {i}", f"value {i}") for i in range(MAX_PROMPT_FIELDS)]
        snapshot = {"viewport": {"height": 600}, "fields": filled + [
            field("ebay", "Character"),
            field("ebay", "Return Policy", account_managed=True),
            field("ebay", "Item Id", disabled=True),
        ]}
        request = FixRequest(job_id="j", conversation_id="c", instruction="fill the blank fields")
        turn = build_turn(request, snapshot, [], {}, "")
        self.assertIn("Every empty field on the form: eBay / Character", turn)
        # The blank field beats the filled ones into the capped field list.
        self.assertIn('"field": "Character"', turn)
        self.assertNotIn(f'"field": "Spec {MAX_PROMPT_FIELDS - 1}"', turn)
        # Account settings and disabled fields are not the seller's blanks to fill.
        self.assertNotIn("Return Policy", turn.split("Listing summary")[0])
        self.assertNotIn("Item Id", turn.split("Listing summary")[0])

    def test_registry_options_reach_the_prompt_for_mui_dropdowns(self):
        from vendoo_studio.repositories.queries import RegistryRepo

        db = self.Session()
        RegistryRepo(db).upsert_schema_fields("ebay", None, [{
            "label": "Neckline", "selector": "#listings.ebay.neckline",
            "is_dropdown": True, "options": ["Crew Neck", "V-Neck"], "options_source": "live-dropdown",
        }])
        db.commit()
        db.close()
        self.draft.fields += [field("ebay", "Neckline", is_dropdown=True, options=[])]

        provider = CapturingProvider(['{"action":"done","message":"Looked."}'])
        self.run_agent(provider, "fill the neckline")
        turn = provider.turns[0]
        self.assertIn('"options": ["Crew Neck", "V-Neck"]', turn)

    def test_a_value_the_form_rejected_is_not_filled_again(self):
        self.draft.fields += [field("ebay", "Material")]
        provider = CapturingProvider([
            json.dumps({"action": "fill", "fields": [{"marketplace": "ebay", "field": "Material", "value": "Polyester"}]}),
            json.dumps({"action": "fill", "fields": [{"marketplace": "ebay", "field": "Material", "value": "Polyester"}]}),
            '{"action":"done","message":"Gave up on material."}',
        ])

        async def silent(db, job, listing, patches, announce=True):
            return True, None

        with patch("vendoo_studio.services.auto_apply.apply_patches", side_effect=silent) as applied:
            final = self.run_agent(provider, "set the material")[-1][1]
        self.assertEqual(applied.call_count, 1, "the same failed value must not go to the form twice")
        self.assertIn("skipped values the form already rejected: Material", final)

    def test_listing_photos_go_to_the_vision_model(self):
        import tempfile
        from pathlib import Path

        from PIL import Image

        seen = []

        class VisionProvider(ScriptedProvider):
            async def vision_chat(self, messages):
                seen.append(messages)
                yield '{"action":"done","message":"Looked."}'

        with tempfile.TemporaryDirectory() as tmp:
            Image.new("RGB", (40, 40), "red").save(Path(tmp) / "shirt.jpg")
            db = self.Session()
            ConversationRepo(db).add_photo(self.conv_id, "shirt.jpg", "shirt.jpg", "image/jpeg", 100)
            db.close()
            with patch("vendoo_studio.config.PHOTOS_DIR", tmp):
                events = self.run_agent(VisionProvider([]), "fill these")
        self.assertEqual(events[-1][1], "Looked.")
        user = seen[0][1]["content"]
        self.assertEqual(user[0]["type"], "text")
        self.assertTrue(user[1]["image_url"]["url"].startswith("data:image/"))

    def test_turn_shows_known_listing_value_for_empty_field(self):
        from vendoo_studio.services.browser_agent import build_turn

        request = FixRequest(job_id="j", conversation_id="c", instruction="fill these",
                             picked=[{"marketplace": "ebay", "label": "Material"}])
        snapshot = {"viewport": {"height": 600}, "fields": [field("ebay", "Material")]}
        turn = build_turn(request, snapshot, [], {"material": "Polyester", "ebay_specifics": {}}, "")
        self.assertIn('"pointed_at": true', turn)
        self.assertIn('"known_value": "Polyester"', turn)


class HelpersTest(unittest.TestCase):
    def test_parse_action_skips_non_action_objects(self):
        self.assertEqual(parse_action('{"a": 1} then {"action": "done", "message": "ok {x}"}'),
                         {"action": "done", "message": "ok {x}"})
        self.assertIsNone(parse_action("no json here"))

    def test_hover_is_not_a_takeover(self):
        browser_bridge._last_human_input.clear()

        class Job:
            id = "job-hover"

        with patch.object(browser_bridge, "_manager") as manager:
            manager.return_value.connected = False
            since = time.monotonic() - 1
            asyncio.run(browser_bridge.send_input(Job, [{"kind": "mouse", "type": "mouseMoved"}]))
            self.assertFalse(browser_bridge.human_input_since("job-hover", since))
            asyncio.run(browser_bridge.send_input(Job, [{"kind": "mouse", "type": "mousePressed"}]))
            self.assertTrue(browser_bridge.human_input_since("job-hover", since))

    def test_field_changes_reports_edits_and_revealed_fields(self):
        before = {"fields": [field("general", "Title", "Tee")]}
        after = {"fields": [field("general", "Title", "Tee 90s"), field("ebay", "Neckline", "Crew"), field("ebay", "Season")]}
        self.assertEqual(field_changes(before, after), [
            "- Vendoo / Title: Tee → Tee 90s",
            "- eBay / Neckline: empty → Crew",
        ])


class ChatRoutesToAgentTest(AgentTestBase):
    def test_browser_message_streams_agent_and_saves_reply(self):
        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        async def fake_run(agent):
            yield "status", "Reading the Vendoo draft…"
            yield "final", f"Fixed for {agent.request.instruction} with {len(agent.request.picked)} field(s)."

        app.dependency_overrides[get_db] = override_get_db
        try:
            with patch("vendoo_studio.routes.chat.get_listing_provider", return_value=ScriptedProvider([])), \
                 patch("vendoo_studio.routes.chat.SessionLocal", self.Session), \
                 patch.object(FixAgent, "run", fake_run):
                client = TestClient(app)
                response = client.post(f"/api/conversations/{self.conv_id}/messages", json={
                    "text": "Neckline should be crew",
                    "browser": {"job_id": self.job_id, "fields": [{"marketplace": "ebay", "label": "Neckline", "value": ""}]},
                })
                other = ConversationRepo(self.Session()).create(title="Other")
                wrong = client.post(f"/api/conversations/{other.id}/messages", json={
                    "text": "x", "browser": {"job_id": self.job_id, "fields": []},
                })
        finally:
            app.dependency_overrides.pop(get_db, None)
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: status\ndata: Reading the Vendoo draft…", response.text)
        self.assertIn("data: Fixed for Neckline should be crew with 1 field(s).", response.text)
        self.assertEqual(wrong.status_code, 404)
        messages = ConversationRepo(self.Session()).get_messages(self.conv_id)
        self.assertIn("Pointed at in the Vendoo browser: eBay / Neckline", messages[0].text)
        self.assertEqual(messages[-1].role, "assistant")
        self.assertIn("with 1 field(s)", messages[-1].text)


if __name__ == "__main__":
    unittest.main()
