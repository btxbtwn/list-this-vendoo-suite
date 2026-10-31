from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.marketplace_sale import MarketplaceSale
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services import chrome_sales, marketplace_accounts, user_settings
from vendoo_studio.services.marketplace_identity import listing_id, listing_reference
from vendoo_studio.services.vendoo_import import merge_notes

# The form Vendoo stored for the seller's 23 Facebook listings.
FACEBOOK = "https://www.facebook.com/marketplace/item/1234567890123456"
POSHMARK = "https://poshmark.com/listing/Vintage-Tee-6aae234280cb08338a8cb591"


@pytest.mark.parametrize(("url", "item_id"), [
    (FACEBOOK, "1234567890123456"),
    ("https://www.facebook.com/marketplace/item/12345678901234567/?ref=search&tracking=private", "12345678901234567"),
    ("https://m.facebook.com/marketplace/item/1234567890123456/", "1234567890123456"),
    ("https://web.facebook.com/marketplace/item/1234567890123456", "1234567890123456"),
])
def test_facebook_links_name_the_listing_and_drop_tracking(url, item_id):
    assert listing_reference("facebook", url) == (item_id, f"https://www.facebook.com/marketplace/item/{item_id}/")


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/marketplace/you/selling",
    "https://www.facebook.com/marketplace/item/12ab/",
    "https://www.facebook.com.evil/marketplace/item/1234567890123456",
    "https://evil.example/www.facebook.com/marketplace/item/1234567890123456",
    "http://www.facebook.com/marketplace/item/1234567890123456",
    "https://www.facebook.com/groups/1/marketplace/item/1234567890123456",
])
def test_other_facebook_pages_are_not_listings(url):
    assert listing_id("facebook", url) is None


class FacebookListingTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Vintage tee")
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {"facebook": FACEBOOK, "poshmark": POSHMARK},
                                                        "vendooMarketplaces": ["facebook", "poshmark"]})
        self.db.commit()
        self.base = f"/api/conversations/{self.conv.id}/marketplace-listings"
        self.bridge = self.enterContext(patch("vendoo_studio.services.browser_bridge.request", new_callable=AsyncMock))
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=True)))

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_a_vendoo_facebook_link_shows_as_live_and_cannot_be_delisted_from_anteroom(self):
        body = self.client.get(self.base).json()
        self.assertEqual(body["facebook"]["listing_id"], "1234567890123456")
        self.assertEqual((body["facebook"]["state"], body["facebook"]["source"]), ("live", "vendoo"))
        self.assertFalse(body["facebook"]["can_delist"])
        self.assertTrue(body["poshmark"]["can_delist"])

    def test_delist_refuses_facebook_and_touches_nothing(self):
        for names in (["facebook"], ["poshmark", "facebook"]):
            response = self.client.post(f"{self.base}/delist", json={"marketplaces": names, "confirm": True})
            self.assertEqual(response.status_code, 409)
            self.assertIn("Delete it on Facebook", response.json()["detail"])
        self.bridge.assert_not_called()
        self.assertEqual(self.client.get(self.base).json()["poshmark"]["state"], "live")

    def test_the_seller_can_link_a_facebook_listing_or_mark_it_not_listed(self):
        body = self.client.post(f"{self.base}/facebook/mark", json={"state": "not_listed"}).json()
        self.assertNotIn("facebook", body)
        other = "https://www.facebook.com/marketplace/item/7654321098765432/?ref=share"
        body = self.client.post(f"{self.base}/facebook/mark", json={"state": "listed", "url": other}).json()
        self.assertEqual(body["facebook"]["url"], "https://www.facebook.com/marketplace/item/7654321098765432/")
        self.assertEqual(body["facebook"]["source"], "seller")

    def test_check_reads_the_listing_through_chrome_and_reports_its_state(self):
        self.bridge.return_value = {"ok": True, "state": "pending", "owner": "you", "title": "Secret tee"}
        response = self.client.post(f"{self.base}/facebook/check")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["ok"], body["state"], body["owner"], body["sale_recorded"]), (True, "pending", "you", False))
        self.assertNotIn("Secret tee", response.text)
        args = self.bridge.call_args.args
        self.assertEqual((args[1], args[2]), ("marketplace.listing_state", {"marketplace": "facebook", "listing_id": "1234567890123456"}))

    def test_a_sold_listing_is_recorded_like_sale_detection_would(self):
        self.bridge.return_value = {"ok": True, "state": "sold", "owner": "you"}
        with patch.object(chrome_sales, "record_reported_sales", return_value=["sale-1"]) as record, \
                patch.object(marketplace_accounts, "announce_sales", new_callable=AsyncMock) as announce:
            body = self.client.post(f"{self.base}/facebook/check").json()
        # The item is named, so the sale protects the listing even if its link is odd.
        record.assert_called_once_with("facebook", ["1234567890123456"],
                                       conversation_ids={"1234567890123456": self.conv.id})
        announce.assert_awaited_once_with(["sale-1"])
        self.assertTrue(body["sale_recorded"])

    def test_a_listing_on_another_account_or_a_failed_read_records_nothing(self):
        with patch.object(chrome_sales, "record_reported_sales") as record:
            self.bridge.return_value = {"ok": True, "state": "sold", "owner": "other"}
            self.assertFalse(self.client.post(f"{self.base}/facebook/check").json()["sale_recorded"])
            self.bridge.return_value = {"ok": False, "error_code": "signed_out", "error": "Facebook asked to sign in again.",
                                        "marketplace_message": "token=abcdef"}
            body = self.client.post(f"{self.base}/facebook/check").json()
        record.assert_not_called()
        self.assertEqual((body["ok"], body["error_code"]), (False, "signed_out"))
        self.assertNotIn("abcdef", json.dumps(body))

    def test_check_needs_a_linked_listing(self):
        self.client.post(f"{self.base}/facebook/mark", json={"state": "not_listed"})
        self.assertEqual(self.client.post(f"{self.base}/facebook/check").status_code, 409)
        self.bridge.assert_not_called()

    def test_a_recorded_sale_offers_to_delist_only_what_anteroom_can_delist(self):
        response = self.client.post(f"{self.base}/sold", json={"marketplace": "other", "sold_on": "2026-10-01",
                                                              "currency": "USD", "request_id": uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["delist_offer"], ["poshmark"])

    def test_a_facebook_sale_can_be_recorded_by_hand(self):
        response = self.client.post(f"{self.base}/sold", json={"marketplace": "facebook", "sold_on": "2026-10-01",
                                                              "currency": "USD", "request_id": uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["listings"]["facebook"]["sold_here"])

    def test_autodelist_leaves_facebook_to_the_seller(self):
        self.db.add(MarketplaceSale(id="sale-ebay", marketplace="ebay", order_id="o1", line_id="l1",
                                    conversation_id=self.conv.id, order_status="paid"))
        self.db.commit()
        delist = AsyncMock(return_value={"poshmark": {"state": "deleted"}})
        with patch("vendoo_studio.services.user_settings.autodelist_enabled", return_value=True), \
                patch("vendoo_studio.services.marketplace_delist.delist", delist):
            notes = asyncio.run(marketplace_accounts.autodelist_for_sales(["sale-ebay"], session_factory=self.Session))
        self.assertEqual(delist.await_args.args[2], ["poshmark"])
        self.assertEqual(notes["sale-ebay"], "Delisted from Poshmark. Delete it on Facebook yourself; Anteroom can't delist it there.")


class FacebookSaleCheckTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        chrome_sales._turn.clear()

    def tearDown(self):
        user_settings.set_sale_detection("facebook", False)
        chrome_sales._turn.clear()
        chrome_sales._errors.clear()

    def test_live_facebook_listings_come_from_vendoo_links(self):
        with self.Session() as db:
            conv = ConversationRepo(db).create(title="coat")
            conv.notes = json.dumps({"vendooListingUrls": {"facebook": FACEBOOK}})
            db.commit()
        self.assertEqual(list(chrome_sales.live_listing_ids("facebook", session_factory=self.Session)), ["1234567890123456"])

    def test_each_check_reads_the_next_few_listings_in_turn(self):
        ids = [str(1000000 + index) for index in range(14)]
        first = chrome_sales.next_batch("facebook", ids)
        second = chrome_sales.next_batch("facebook", ids)
        third = chrome_sales.next_batch("facebook", ids)
        self.assertEqual((len(first), len(second), len(third)), (6, 6, 6))
        self.assertEqual(first + second, ids[:12])
        self.assertEqual(third, ids[12:] + ids[:4])
        self.assertEqual(chrome_sales.next_batch("poshmark", ids), ids)

    def test_facebook_checks_are_spaced_further_apart(self):
        due = chrome_sales.arm_next("facebook", 0)
        self.assertGreaterEqual(due, 20 * 60)
        self.assertLessEqual(due, 40 * 60)

    def test_facebook_is_not_checked_until_the_seller_turns_it_on(self):
        bridge = AsyncMock(return_value={"ok": True, "sales": []})
        with patch("vendoo_studio.services.browser_bridge.request", bridge), \
                patch.object(chrome_sales, "live_listing_ids", return_value={"1234567890123456": "conv"}):
            self.assertTrue(asyncio.run(chrome_sales.check_marketplace("facebook")))
            bridge.assert_not_called()
            user_settings.set_sale_detection("facebook", True)
            self.assertTrue(asyncio.run(chrome_sales.check_marketplace("facebook")))
        self.assertEqual(bridge.await_args.args[2], {"marketplace": "facebook", "listing_ids": ["1234567890123456"]})

    def test_a_reported_facebook_sale_is_kept_by_listing_id(self):
        found = chrome_sales.normalize_sales("facebook", {"ok": True, "sales": [
            {"listing_id": "1234567890123456", "price": "20"}, {"listing_id": "12ab"}]})
        self.assertEqual(found, ["1234567890123456"])
