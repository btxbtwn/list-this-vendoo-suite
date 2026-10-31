from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing_promotion import ListingPromotion, MarketplaceOfferFloor
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo
from vendoo_studio.services import browser_bridge, listing_promotions
from vendoo_studio.services.vendoo_import import merge_notes

POST = "6aae234280cb08338a8cb591"
DISCOUNT = "c" * 24
URL = f"https://poshmark.com/listing/Vintage-Tee-{POST}"


class ListingPromotionsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Vintage tee")
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {"poshmark": URL}})
        self.db.commit()
        self.bridge = self.enterContext(patch("vendoo_studio.services.listing_promotions.browser_bridge.request", new_callable=AsyncMock))
        self.bridge.side_effect = self.answer
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=True)))
        self.enterContext(patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue", lambda: None))
        self.check = {"ok": True, "price_cents": 5000, "like_count": 3, "minimum_discount_percent": 10,
                      "maximum_discount_percent": 79, "offer_price_cents": 4000,
                      "shipping_discounts": [{"id": DISCOUNT, "label": "-$1.50", "min_offer_cents": 500}]}
        self.sent = {"ok": True, "state": "done"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    async def answer(self, _job, message_type, payload, timeout=0):
        if message_type == "marketplace.promotion_check":
            return self.check
        if message_type == "marketplace.promote":
            if isinstance(self.sent, Exception):
                raise self.sent
            return self.sent
        return {"finished": False, "known": False}

    def calls(self, kind):
        return [call for call in self.bridge.call_args_list if call.args[1] == kind]

    def preview(self, **body):
        response = self.client.post("/api/promotions/preview", json={"conversation_ids": [self.conv.id], "marketplace": "poshmark", **body})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["rows"][0]

    def test_share_is_reviewed_then_sent_once(self):
        row = self.preview(action="share")
        self.assertEqual((row["state"], row["listing_id"], row["price"]), ("preview", POST, "50.00"))
        self.assertEqual(self.calls("marketplace.promote"), [])
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={}).status_code, 422)
        done = self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["state"], "done")
        payload = self.calls("marketplace.promote")[0].args[2]
        self.assertEqual((payload["action_id"], payload["action"], payload["listing_id"], payload["confirm"]), (row["id"], "share", POST, True))
        # The same reviewed row is never sent twice.
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).status_code, 409)
        self.assertEqual(len(self.calls("marketplace.promote")), 1)
        job = self.db.query(Job).one()
        self.assertEqual((job.current_step, job.status), ("native_promote", "completed"))

    def test_only_named_supported_marketplaces_and_actions(self):
        for body in ({"marketplace": "vinted", "action": "share"}, {"marketplace": "poshmark", "action": "refresh"}, {"action": "share"}):
            response = self.client.post("/api/promotions/preview", json={"conversation_ids": [self.conv.id], **body})
            self.assertEqual(response.status_code, 422, body)
        self.assertEqual(self.client.post("/api/promotions/preview", json={"conversation_ids": [self.conv.id], "marketplace": "mercari",
                                                                           "action": "share"}).status_code, 400)
        self.bridge.assert_not_called()

    def test_depop_offer_finishes_without_claiming_the_preview_count_was_delivered(self):
        conv = ConversationRepo(self.db).create(title="Depop tee")
        conv.notes = merge_notes(conv.notes, {"vendooListingUrls": {"depop": "https://www.depop.com/products/seller-vintage-tee/"}})
        self.db.commit()
        self.check = {"ok": True, "price_cents": 5000, "like_count": 4, "minimum_discount_percent": 5,
                      "maximum_discount_percent": 90, "offer_price_cents": 4250, "shipping_discounts": []}
        self.sent = {"ok": True, "state": "done"}
        response = self.client.post("/api/promotions/preview", json={"conversation_ids": [conv.id], "marketplace": "depop",
                                                                     "action": "offer", "discount_percent": 15, "floors": {conv.id: "40"}})
        row = response.json()["rows"][0]
        self.assertEqual((row["state"], row["listing_id"], row["offer_price"], row["like_count"]), ("preview", "seller-vintage-tee", "42.50", 4))
        done = self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).json()
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["note"], "Offer of $42.50 sent to likers.")
        payload = self.calls("marketplace.promote")[0].args[2]
        self.assertEqual((payload["marketplace"], payload["offer_price_cents"], payload["floor_cents"]), ("depop", 4250, 4000))
        self.assertEqual(len(self.calls("marketplace.promote")), 1)

    def test_mercari_offer_has_no_shipping_choice(self):
        item = "m12345678901"
        conv = ConversationRepo(self.db).create(title="Mercari jacket")
        conv.notes = merge_notes(conv.notes, {"vendooListingUrls": {"mercari": f"https://www.mercari.com/us/item/{item}/"}})
        self.db.commit()
        self.check = {"ok": True, "price_cents": 5000, "like_count": 4, "minimum_discount_percent": 20,
                      "maximum_discount_percent": 48, "offer_price_cents": 4000, "shipping_discounts": []}
        response = self.client.post("/api/promotions/preview", json={"conversation_ids": [conv.id], "marketplace": "mercari",
                                                                     "action": "offer", "discount_percent": 20, "floors": {conv.id: "30"}})
        row = response.json()["rows"][0]
        self.assertEqual((row["state"], row["listing_id"], row["offer_price"]), ("preview", item, "40.00"))
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True, "shipping_discount_id": DISCOUNT}).status_code, 400)
        done = self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).json()
        self.assertEqual(done["state"], "done")
        payload = self.calls("marketplace.promote")[0].args[2]
        self.assertEqual((payload["marketplace"], payload["offer_price_cents"], payload["shipping_discount_id"]), ("mercari", 4000, None))

    def test_an_unconfirmed_share_blocks_sharing_that_listing(self):
        row = self.preview(action="share")
        self.sent = browser_bridge.BrowserBridgeError("Chrome did not answer in time.")
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).json()["state"], "unknown")
        again = self.preview(action="share")
        self.assertEqual(again["state"], "skipped")
        self.assertIn("unconfirmed", again["note"])
        self.assertEqual(len(self.calls("marketplace.promote")), 1)

    def test_offer_needs_a_floor_and_never_goes_below_it(self):
        row = self.preview(action="offer", discount_percent=20)
        self.assertEqual(row["state"], "skipped")
        self.assertIn("lowest price you accept", row["note"])
        self.assertEqual(self.calls("marketplace.promotion_check"), [])
        low = self.preview(action="offer", discount_percent=20, floors={self.conv.id: "45"})
        self.assertEqual(low["state"], "skipped")
        self.assertIn("below your floor", low["note"])
        ok = self.preview(action="offer", discount_percent=20, floors={self.conv.id: "35.00"})
        self.assertEqual((ok["state"], ok["offer_price"], ok["floor"]), ("preview", "40.00", "35.00"))
        # A later, higher floor blocks the reviewed offer.
        self.db.query(MarketplaceOfferFloor).one().floor_cents = 4500
        self.db.commit()
        refused = self.client.post(f"/api/promotions/{ok['id']}/perform", json={"confirm": True, "shipping_discount_id": DISCOUNT})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.calls("marketplace.promote"), [])

    def test_offer_needs_an_explicit_reviewed_shipping_choice(self):
        row = self.preview(action="offer", discount_percent=20, floors={self.conv.id: "30"})
        for choice in (None, "d" * 24):
            body = {"confirm": True, **({"shipping_discount_id": choice} if choice else {})}
            self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json=body).status_code, 400)
        self.assertEqual(self.calls("marketplace.promote"), [])
        done = self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True, "shipping_discount_id": DISCOUNT}).json()
        self.assertEqual((done["state"], done["shipping_discount_label"]), ("done", "-$1.50"))
        payload = self.calls("marketplace.promote")[0].args[2]
        self.assertEqual((payload["offer_price_cents"], payload["floor_cents"], payload["shipping_discount_id"]), (4000, 3000, DISCOUNT))
        # One offer per listing per day.
        again = self.preview(action="offer", discount_percent=20)
        self.assertEqual(again["state"], "skipped")
        self.assertIn("last 24 hours", again["note"])

    def test_no_likers_or_a_discount_poshmark_refuses_is_skipped(self):
        self.check = {**self.check, "like_count": 0}
        self.assertIn("Nobody has liked", self.preview(action="offer", discount_percent=20, floors={self.conv.id: "1"})["note"])
        self.check = {**self.check, "like_count": 3, "offer_price_cents": None}
        self.assertIn("between 10% and 79%", self.preview(action="offer", discount_percent=5)["note"])
        # A marketplace whose limits leave no valid discount says so instead of "None%".
        self.check = {**self.check, "minimum_discount_percent": None, "maximum_discount_percent": None}
        note = self.preview(action="offer", discount_percent=5)["note"]
        self.assertIn("leave no discount", note)
        self.assertNotIn("None", note)

    def test_lost_reply_is_unknown_blocks_offers_and_check_only_reads(self):
        row = self.preview(action="offer", discount_percent=20, floors={self.conv.id: "30"})
        self.sent = browser_bridge.BrowserBridgeError("Chrome did not answer in time.")
        result = self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True, "shipping_discount_id": "none"}).json()
        self.assertEqual(result["state"], "unknown")
        self.assertIn("unconfirmed", self.preview(action="offer", discount_percent=20)["note"])
        checked = self.client.post(f"/api/promotions/{row['id']}/check").json()
        self.assertEqual(checked["state"], "unknown")
        self.assertEqual(len(self.calls("marketplace.promote")), 1)
        self.assertEqual(self.calls("marketplace.promotion_result")[0].args[2], {"action_id": row["id"]})
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/checked", json={"confirm": True}).json()["state"], "checked")

    def test_check_settles_from_the_extension_journal(self):
        row = self.preview(action="share")
        self.sent = {"ok": False, "safe_to_retry": False, "error_code": "uncertain"}
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).json()["state"], "unknown")
        self.bridge.side_effect = None
        self.bridge.return_value = {"finished": True, "result": {"ok": True, "state": "done"}}
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/check").json()["state"], "done")

    def test_a_refusal_is_failed_and_a_rate_limit_stops_the_batch(self):
        row = self.preview(action="share")
        self.sent = {"ok": False, "safe_to_retry": True, "error_code": "rate_limited", "error": "Poshmark is limiting requests"}
        result = self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).json()
        self.assertEqual((result["state"], result["stop"]), ("failed", True))

    def test_sold_items_and_busy_slot_send_nothing(self):
        row = self.preview(action="share")
        JobRepo(self.db).create(self.conv.id, "", {}, status="dispatched", current_step="native_delist")
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).status_code, 409)
        self.conv.status = "sold"
        self.db.commit()
        self.assertIn("sold", self.preview(action="share")["note"])
        self.assertEqual(self.calls("marketplace.promote"), [])

    def test_expired_review_is_refused(self):
        row = self.preview(action="share")
        self.db.get(ListingPromotion, row["id"]).expires_at -= timedelta(hours=1)
        self.db.commit()
        self.assertEqual(self.client.post(f"/api/promotions/{row['id']}/perform", json={"confirm": True}).status_code, 409)
        self.assertEqual(self.calls("marketplace.promote"), [])

    def test_interrupted_sends_become_unknown(self):
        row = self.preview(action="share")
        stored = self.db.get(ListingPromotion, row["id"])
        stored.state, stored.job_id = "sending", "job-1"
        self.db.commit()
        self.assertEqual(listing_promotions.mark_interrupted(self.db, "other-job"), 0)
        self.assertEqual(listing_promotions.mark_interrupted(self.db, "job-1"), 1)
        self.assertEqual(self.db.get(ListingPromotion, row["id"]).state, "unknown")
        history = self.client.get("/api/promotions").json()
        self.assertEqual(history["supported"], {"poshmark": ["offer", "share"], "mercari": ["offer"], "depop": ["offer"]})
        self.assertEqual(history["awaiting_capture"], {})
        self.assertEqual(history["history"][0]["state"], "unknown")
