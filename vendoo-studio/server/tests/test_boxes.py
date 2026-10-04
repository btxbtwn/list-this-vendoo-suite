from __future__ import annotations

import json
import unittest
import uuid

from fastapi.testclient import TestClient

from vendoo_studio.database import SessionLocal
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services import boxes
from vendoo_studio.services.inventory_analytics import load_rows
from vendoo_studio.services.job_snapshot import prepare_listing_snapshot


def _sold(price: float, *, fees: float = 0, shipping_cost: float = 0, days: int = 10) -> str:
    return json.dumps({
        "vendooStatus": "sold",
        "vendooSale": {"price": price, "fees": fees, "shippingCost": shipping_cost, "marketplace": "ebay"},
        "vendooDates": {
            "listed": "2026-09-01T00:00:00+00:00",
            "sold": f"2026-09-{1 + days:02d}T00:00:00+00:00",
        },
    })


class BoxResultsTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        # Each test gets its own store name, since the database is shared.
        self.store = f"Raghouse {uuid.uuid4().hex[:6]}"
        self.box = boxes.create_box(
            self.db, store=self.store, title="Carhartt mix 25 pcs", price=180, shipping=34, pieces=20,
        )
        repo = ConversationRepo(self.db)
        self.sold_a = repo.create(title="Jacket", notes=_sold(80, fees=10, shipping_cost=8, days=6), box_id=self.box.id)
        self.sold_b = repo.create(title="Vest", notes=_sold(50, fees=6, days=20), box_id=self.box.id)
        self.active = repo.create(title="Pants", notes=json.dumps({"vendooStatus": "active"}), box_id=self.box.id)
        self.loose = repo.create(title="Not from a box", notes=_sold(30))

    def tearDown(self):
        self.db.close()

    def _row(self, payload, box_id):
        return next(row for row in payload["boxes"] if row["id"] == box_id)

    def test_a_box_reports_money_in_against_what_its_sales_brought_back(self):
        row = self._row(boxes.results(self.db), self.box.id)
        self.assertEqual(row["spent"], 214)
        self.assertEqual(row["cost_per_piece"], 10.7)
        self.assertEqual(row["listings"], 3)
        self.assertEqual(row["listed"], 3)
        self.assertEqual(row["sold"], 2)
        # (80 - 10 - 8) + (50 - 6)
        self.assertEqual(row["returned"], 106)
        self.assertEqual(row["profit"], -108)
        self.assertEqual(row["sell_through"], 0.1)
        self.assertEqual(row["median_days"], 13)

    def test_stores_add_up_their_boxes(self):
        boxes.create_box(self.db, store=self.store, title="Second box", price=100, shipping=0, pieces=10)
        store = next(row for row in boxes.results(self.db)["stores"] if row["store"] == self.store)
        self.assertEqual(store["boxes"], 2)
        self.assertEqual(store["spent"], 314)
        self.assertEqual(store["sold"], 2)
        self.assertEqual(store["sell_through"], round(2 / 30, 3))

    def test_an_item_with_no_cost_carries_its_share_of_the_box(self):
        rows = {row.conversation_id: row for row in load_rows(self.db)}
        self.assertEqual(rows[self.sold_a.id].cost, 10.7)
        self.assertIsNone(rows[self.loose.id].cost)

    def test_the_vendoo_form_gets_the_box_share_unless_cog_was_typed(self):
        snapshot = prepare_listing_snapshot(self.db, self.active, {"title": "Pants", "price": 40})
        self.assertEqual(snapshot["cost"], 10.7)
        self.active.notes = json.dumps({"cog": "4"})
        self.db.commit()
        snapshot = prepare_listing_snapshot(self.db, self.active, {"title": "Pants", "price": 40})
        self.assertEqual(snapshot["cost"], 4)

    def test_deleting_a_box_keeps_its_listings(self):
        boxes.delete_box(self.db, self.box)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Conversation, self.sold_a.id).box_id)


class BoxRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_create_assign_and_clear_a_box(self):
        store = f"Thrift Vintage Fashion {uuid.uuid4().hex[:6]}"
        created = self.client.post("/api/boxes", json={
            "store": store, "title": "Y2K 50 lb", "price": 250, "shipping": 0, "pieces": 100,
        })
        self.assertEqual(created.status_code, 200, created.text)
        box = next(row for row in created.json()["boxes"] if row["store"] == store)

        conv = self.client.post("/api/conversations", json={"title": "Tee", "box_id": box["id"]}).json()
        self.assertEqual(conv["box_id"], box["id"])

        renamed = self.client.patch(f"/api/conversations/{conv['id']}", json={"title": "Band tee"}).json()
        self.assertEqual(renamed["box_id"], box["id"])

        cleared = self.client.patch(f"/api/conversations/{conv['id']}", json={"box_id": None}).json()
        self.assertIsNone(cleared["box_id"])

        missing = self.client.patch(f"/api/conversations/{conv['id']}", json={"box_id": "nope"})
        self.assertEqual(missing.status_code, 404)

        edited = self.client.patch(f"/api/boxes/{box['id']}", json={"shipping": 40}).json()
        self.assertEqual(next(row for row in edited["boxes"] if row["id"] == box["id"])["spent"], 290)

        gone = self.client.delete(f"/api/boxes/{box['id']}").json()
        self.assertFalse(any(row["id"] == box["id"] for row in gone["boxes"]))

    def test_unknown_box_on_create_is_refused(self):
        response = self.client.post("/api/conversations", json={"title": "Tee", "box_id": "nope"})
        self.assertEqual(response.status_code, 404)
