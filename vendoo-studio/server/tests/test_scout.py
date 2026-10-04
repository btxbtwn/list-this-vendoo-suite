from __future__ import annotations

import asyncio
import io
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from vendoo_studio.database import SessionLocal
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.scout import ScoutCheck
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services import scout
from vendoo_studio.services.listing_delete import delete_listing
from vendoo_studio.services.sold_comps import SoldComp, SoldCompsReport, format_sold_comps

EVIDENCE = {
    "brand": {"value": "Carhartt", "confidence": 0.9},
    "category": {"value": "Jackets"},
    "color": {"value": "Brown"},
}


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "brown").save(buffer, "JPEG")
    return buffer.getvalue()


def _comps(*prices: float) -> str:
    return format_sold_comps(SoldCompsReport(
        query="Carhartt Jackets",
        source="ChatGPT",
        comps=[
            SoldComp(price=price, marketplace="ebay", title=f"Carhartt jacket {i}", url=f"https://www.ebay.com/itm/{i}")
            for i, price in enumerate(prices)
        ],
    ))


class FakeProvider:
    async def analyze_photos(self, paths, **kwargs):
        return {"evidence": EVIDENCE}


class VerdictTest(unittest.TestCase):
    def test_buy_when_it_doubles_the_money_and_clears_ten_dollars(self):
        self.assertEqual(scout.verdict(50, 15), {"net": 40, "pay_up_to": 20, "profit": 25, "verdict": "buy"})

    def test_maybe_between_buy_and_pass(self):
        self.assertEqual(scout.verdict(50, 25)["verdict"], "maybe")

    def test_pass_when_there_is_too_little_in_it(self):
        self.assertEqual(scout.verdict(20, 14)["verdict"], "pass")

    def test_without_an_asking_price_it_says_what_to_pay(self):
        self.assertEqual(scout.verdict(45, None), {"net": 36, "pay_up_to": 18, "profit": None, "verdict": None})

    def test_without_comps_it_is_unsure(self):
        self.assertEqual(scout.verdict(None, 5)["verdict"], "unsure")


class ScoutFlowTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def _create(self, asking="15"):
        with mock.patch.object(scout, "start"):
            response = self.client.post(
                "/api/scout",
                files=[("files", ("tag.jpg", _jpeg(), "image/jpeg"))],
                data={"asking_price": asking},
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _run(self, check_id, comps):
        with (
            mock.patch("vendoo_studio.services.listing_provider.get_listing_provider", return_value=FakeProvider()),
            mock.patch(
                "vendoo_studio.services.comp_research.research_sold_comps",
                new=mock.AsyncMock(return_value=comps),
            ),
        ):
            asyncio.run(scout.run_check(check_id))

    def test_photos_to_verdict_to_draft(self):
        created = self._create()
        self.assertEqual(created["status"], "checking")
        self.assertEqual(len(created["photo_urls"]), 1)
        self.assertEqual(self.client.get(created["photo_urls"][0]).status_code, 200)

        self._run(created["id"], _comps(40, 50, 60))
        check = self.client.get(f"/api/scout/{created['id']}").json()
        self.assertEqual(check["status"], "done")
        self.assertEqual(check["estimate"], 50)
        self.assertEqual(check["comps_count"], 3)
        self.assertIn("Carhartt", check["title"])
        self.assertEqual(check["verdict"], "buy")

        repriced = self.client.patch(f"/api/scout/{created['id']}", json={"asking_price": 36}).json()
        self.assertEqual(repriced["verdict"], "pass")

        bought = self.client.post(f"/api/scout/{created['id']}/decision", json={"decision": "bought"}).json()
        self.assertEqual(bought["decision"], "bought")
        conv = self.db.get(Conversation, bought["conversation_id"])
        self.assertEqual(json.loads(conv.notes), {"cog": "36"})
        repo = ConversationRepo(self.db)
        self.assertEqual(len(repo.get_photos(conv.id)), 1)
        self.assertTrue(any(m.text.startswith("Photo analysis:") for m in repo.get_messages(conv.id)))

    def test_a_sold_listing_counts_toward_the_track_record(self):
        created = self._create(asking="10")
        self._run(created["id"], _comps(40, 50, 60))
        bought = self.client.post(f"/api/scout/{created['id']}/decision", json={"decision": "bought"}).json()
        conv = self.db.get(Conversation, bought["conversation_id"])
        conv.notes = json.dumps({"vendooStatus": "sold", "vendooSale": {"price": 45}})
        self.db.commit()

        listed = self.client.get("/api/scout").json()
        row = next(c for c in listed["checks"] if c["id"] == created["id"])
        self.assertEqual(row["sold_price"], 45)
        self.assertGreaterEqual(listed["track_record"]["sold"], 1)

        delete_listing(self.db, conv.id)
        self.db.expire_all()
        self.assertIsNone(self.db.get(ScoutCheck, created["id"]).conversation_id)

    def test_thin_comps_leave_it_unsure(self):
        created = self._create()
        self._run(created["id"], _comps(40))
        check = self.client.get(f"/api/scout/{created['id']}").json()
        self.assertIsNone(check["estimate"])
        self.assertEqual(check["verdict"], "unsure")

    def test_no_provider_fails_with_a_reason(self):
        created = self._create()
        with mock.patch("vendoo_studio.services.listing_provider.get_listing_provider", return_value=None):
            asyncio.run(scout.run_check(created["id"]))
        check = self.client.get(f"/api/scout/{created['id']}").json()
        self.assertEqual(check["status"], "failed")
        self.assertIn("Connect", check["error"])

    def test_cannot_buy_before_the_check_finishes(self):
        created = self._create()
        response = self.client.post(f"/api/scout/{created['id']}/decision", json={"decision": "bought"})
        self.assertEqual(response.status_code, 409)
