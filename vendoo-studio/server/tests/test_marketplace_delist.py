from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.marketplace_sale import MarketplaceSale
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.marketplace_delist import listing_id
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes

URLS = {
    "ebay": "https://www.ebay.com/itm/377507697747",
    "etsy": "https://www.etsy.com/listing/4578284433/vintage-tee",
    "poshmark": "https://poshmark.com/listing/Vintage-Tee-6aae234280cb08338a8cb591",
    "mercari": "https://www.mercari.com/us/item/m70565754838",
    "depop": "https://www.depop.com/products/shop-classic-tee-136d/",
    "sellwild": "https://sellwild.com/product/105190104/vintage-tee",
    "vinted": "https://www.vinted.com/items/42-black-tee",
}


class MarketplaceDelistTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Vintage tee")
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": URLS})
        self.db.commit()
        self.base = f"/api/conversations/{self.conv.id}/marketplace-listings"
        self.bridge = self.enterContext(patch("vendoo_studio.services.marketplace_delist.browser_bridge.request", new_callable=AsyncMock))
        self.bridge.return_value = {"ok": True, "state": "deleted"}
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=True)))
        self.ebay = self.enterContext(patch("vendoo_studio.services.marketplace_delist._delete_ebay", new_callable=AsyncMock))
        self.ebay.return_value = {"ok": True, "state": "deleted"}
        self.etsy = self.enterContext(patch("vendoo_studio.services.marketplace_delist._delete_etsy", new_callable=AsyncMock))
        self.etsy.return_value = {"ok": True, "state": "deleted"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_listing_ids_come_from_each_marketplace_link(self):
        self.assertEqual({m: listing_id(m, u) for m, u in URLS.items()}, {
            "ebay": "377507697747", "etsy": "4578284433", "poshmark": "6aae234280cb08338a8cb591",
            "mercari": "m70565754838", "depop": "shop-classic-tee-136d", "sellwild": "105190104", "vinted": "42"})
        self.assertIsNone(listing_id("ebay", "https://evil.example/itm/377507697747"))
        self.assertIsNone(listing_id("mercari", "https://www.mercari.com/us/item/m1/../x"))

    def test_lists_every_live_marketplace(self):
        result = self.client.get(self.base).json()
        self.assertEqual(set(result), set(URLS))
        self.assertTrue(all(entry["state"] == "live" and not entry["sold_here"] for entry in result.values()))

    def test_delist_needs_confirmation_and_named_marketplaces(self):
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["poshmark"]}).status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": [], "confirm": True}).status_code, 422)
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["whatnot"], "confirm": True}).status_code, 400)
        self.bridge.assert_not_called()
        self.ebay.assert_not_called()

    def test_delist_deletes_only_the_named_marketplaces(self):
        result = self.client.post(f"{self.base}/delist", json={"marketplaces": ["poshmark", "ebay"], "confirm": True})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual((body["poshmark"]["state"], body["ebay"]["state"], body["mercari"]["state"]), ("deleted", "deleted", "live"))
        self.assertEqual(self.bridge.call_count, 1)
        args = self.bridge.call_args.args
        self.assertEqual(args[1], "marketplace.delete")
        self.assertEqual(args[2], {"marketplace": "poshmark", "listing_id": "6aae234280cb08338a8cb591", "confirm": True})
        self.ebay.assert_awaited_once()
        # The listing ID, and the eBay record that says whether it is a group with variations.
        self.assertEqual(self.ebay.await_args.args[0], "377507697747")
        self.assertIsInstance(self.ebay.await_args.args[1], dict)
        self.etsy.assert_not_called()

    def test_the_marketplace_it_sold_on_is_never_deleted(self):
        self.db.add(MarketplaceSale(marketplace="ebay", order_id="o1", line_id="l1", conversation_id=self.conv.id))
        self.db.commit()
        self.assertTrue(self.client.get(self.base).json()["ebay"]["sold_here"])
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["ebay"], "confirm": True}).status_code, 409)
        self.conv.notes = merge_notes(self.conv.notes, {"vendooSale": {"marketplace": "depop"}})
        self.db.commit()
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["mercari", "depop"], "confirm": True}).status_code, 409)
        self.ebay.assert_not_called()
        self.bridge.assert_not_called()

    def _store_vendoo_dates(self, dates: dict) -> None:
        """Write the dates straight into the notes, the way an older import left them."""
        notes = json.loads(self.conv.notes)
        notes["vendooDates"] = dates
        self.conv.notes = json.dumps(notes)
        self.db.commit()

    def test_a_zero_sold_date_from_vendoo_is_not_a_sale(self):
        """Vendoo's "never sold" zero must not read as a Poshmark sale in 1970."""
        self._store_vendoo_dates({
            "listed": "2026-09-27T18:59:11+00:00",
            "sold": "1970-01-01T00:00:00+00:00",
            "soldByMarketplace": {"poshmark": "1970-01-01T00:00:00+00:00"},
        })
        entry = self.client.get(self.base).json()["poshmark"]
        self.assertFalse(entry["sold_here"])
        self.assertEqual(entry["state"], "live")
        gone = self.client.post(f"{self.base}/delist", json={"marketplaces": ["poshmark"], "confirm": True})
        self.assertEqual(gone.status_code, 200, gone.text)

    def test_a_real_sold_date_from_vendoo_still_blocks_that_marketplace(self):
        self._store_vendoo_dates({
            "sold": "2026-08-02T00:00:00+00:00",
            "soldByMarketplace": {"poshmark": "2026-08-02T00:00:00+00:00"},
        })
        self.assertTrue(self.client.get(self.base).json()["poshmark"]["sold_here"])
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["poshmark"], "confirm": True}).status_code, 409)
        self.bridge.assert_not_called()

    def test_a_failure_is_recorded_and_others_still_run(self):
        self.bridge.side_effect = [{"ok": False, "error": "Poshmark rejected the delete (HTTP 500)."}, {"ok": True, "state": "deleted"}]
        body = self.client.post(f"{self.base}/delist", json={"marketplaces": ["poshmark", "mercari"], "confirm": True}).json()
        self.assertEqual(body["poshmark"]["state"], "failed")
        self.assertIn("HTTP 500", body["poshmark"]["error"])
        self.assertEqual(body["mercari"]["state"], "deleted")

    def test_a_newer_listing_after_a_delete_is_live_again(self):
        self.client.post(f"{self.base}/delist", json={"marketplaces": ["mercari"], "confirm": True})
        self.assertEqual(self.client.get(self.base).json()["mercari"]["state"], "deleted")
        notes = parse_notes(self.conv.notes)
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {**notes["vendooListingUrls"],
                                                                              "mercari": "https://www.mercari.com/us/item/m99999999999"}})
        self.db.commit()
        self.assertEqual(self.client.get(self.base).json()["mercari"]["state"], "live")

    def test_marking_listed_links_the_pasted_listing_without_touching_the_marketplace(self):
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {"ebay": URLS["ebay"]}})
        self.db.commit()
        bad = self.client.post(f"{self.base}/mercari/mark", json={"state": "listed", "url": "https://evil.example/us/item/m1"})
        self.assertEqual(bad.status_code, 400)
        body = self.client.post(f"{self.base}/mercari/mark", json={"state": "listed", "url": URLS["mercari"]}).json()
        self.assertEqual((body["mercari"]["listing_id"], body["mercari"]["source"], body["mercari"]["state"]), ("m70565754838", "seller", "live"))
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["mercari"], "confirm": True}).json()["mercari"]["state"], "deleted")
        self.client.post(f"{self.base}/mercari/mark", json={"state": "listed", "url": URLS["mercari"]})
        self.assertEqual(self.client.get(self.base).json()["mercari"]["state"], "live")
        self.ebay.assert_not_called()

    def test_a_seller_linked_listing_matches_relay_sales(self):
        from vendoo_studio.services.relay_sales import find_listing

        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {}})
        self.db.commit()
        self.assertIsNone(find_listing(self.db, "ebay", "377507697747"))
        self.client.post(f"{self.base}/ebay/mark", json={"state": "listed", "url": URLS["ebay"]})
        self.assertEqual(find_listing(self.db, "ebay", "377507697747").id, self.conv.id)

    def test_linking_a_listing_already_attached_to_another_item_is_refused(self):
        other = ConversationRepo(self.db).create(title="Duplicate import")
        response = self.client.post(f"/api/conversations/{other.id}/marketplace-listings/ebay/mark",
                                    json={"state": "listed", "url": "https://ebay.co.uk/itm/377507697747?tracking=private"})
        self.assertEqual(response.status_code, 409)
        self.db.refresh(other)
        self.assertNotIn("marketplaceMarks", parse_notes(other.notes))
        self.ebay.assert_not_called()
        self.bridge.assert_not_called()

    def test_seller_link_is_normalized_and_can_be_saved_again_for_the_same_item(self):
        response = self.client.post(f"{self.base}/ebay/mark",
                                    json={"state": "listed", "url": "https://ebay.com/itm/377507697747?tracking=private#details"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ebay"]["url"], URLS["ebay"])
        self.assertEqual(self.client.post(f"{self.base}/ebay/mark", json={"state": "listed", "url": URLS["ebay"]}).status_code, 200)

    def test_a_direct_listing_matches_relay_sales(self):
        from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
        from vendoo_studio.services.relay_sales import find_listing

        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {}})
        self.db.commit()
        self.assertIsNone(find_listing(self.db, "ebay", "377507697747"))
        MarketplaceListingRepo(self.db).save(self.conv.id, "ebay", {"state": "published", "listing_url": URLS["ebay"]})
        self.assertEqual(find_listing(self.db, "ebay", "377507697747").id, self.conv.id)

    def test_marking_sold_blocks_delist_and_marking_listed_clears_an_older_sale(self):
        body = self.client.post(f"{self.base}/depop/mark", json={"state": "sold"}).json()
        self.assertTrue(body["depop"]["sold_here"])
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["depop"], "confirm": True}).status_code, 409)
        self.db.add(MarketplaceSale(marketplace="ebay", order_id="o1", line_id="l1", conversation_id=self.conv.id))
        self.db.commit()
        self.assertFalse(self.client.post(f"{self.base}/ebay/mark", json={"state": "listed", "url": URLS["ebay"]}).json()["ebay"]["sold_here"])

    def test_marking_not_listed_hides_the_link_until_a_different_listing_appears(self):
        self.assertNotIn("poshmark", self.client.post(f"{self.base}/poshmark/mark", json={"state": "not_listed"}).json())
        self.assertNotIn("sellwild", self.client.post(f"{self.base}/sellwild/mark", json={"state": "not_listed"}).json())
        notes = parse_notes(self.conv.notes)
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {
            **notes["vendooListingUrls"], "poshmark": "https://poshmark.com/listing/Tee-7aae234280cb08338a8cb592"}})
        self.db.commit()
        self.assertEqual(self.client.get(self.base).json()["poshmark"]["listing_id"], "7aae234280cb08338a8cb592")
        self.assertEqual(self.client.post(f"{self.base}/whatnot/mark", json={"state": "sold"}).status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/ebay/mark", json={"state": "gone"}).status_code, 400)

    def test_marks_settle_unconfirmed_records_and_wait_only_for_a_running_one(self):
        from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
        from vendoo_studio.services.api_job_lock import claim_api_job, release_api_job

        records = MarketplaceListingRepo(self.db)
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {}})
        self.db.commit()
        records.save(self.conv.id, "depop", {"state": "published", "listing_url": URLS["depop"]})
        records.save(self.conv.id, "mercari", {"state": "unknown", "job_id": "j1", "draft_url": "https://www.mercari.com/sell/draft/x/"})
        records.save(self.conv.id, "poshmark", {"state": "publishing", "job_id": "j2"})
        self.assertNotIn("depop", self.client.post(f"{self.base}/depop/mark", json={"state": "not_listed"}).json())
        self.assertEqual(records.get(self.conv.id, "depop")["state"], "not_saved")
        # The seller looked: an unconfirmed Mercari listing that is not there goes back to its draft.
        self.assertEqual(self.client.post(f"{self.base}/mercari/mark", json={"state": "not_listed"}).status_code, 200)
        self.assertEqual(records.get(self.conv.id, "mercari")["state"], "draft")
        claim_api_job("j2")
        try:
            self.assertEqual(self.client.post(f"{self.base}/poshmark/mark", json={"state": "sold"}).status_code, 409)
        finally:
            release_api_job("j2")
        listed = self.client.post(f"{self.base}/poshmark/mark", json={"state": "listed", "url": URLS["poshmark"]})
        self.assertEqual(listed.json()["poshmark"]["listing_id"], "6aae234280cb08338a8cb591")
        self.assertEqual(records.get(self.conv.id, "poshmark")["state"], "published")

    def test_marking_listed_revives_a_record_reset_to_draft(self):
        """A publish Anteroom could not confirm is reset to draft; the seller's Looked mark still makes it live."""
        from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
        from vendoo_studio.services.native_marketplaces import reset

        records = MarketplaceListingRepo(self.db)
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {}})
        self.db.commit()
        records.save(self.conv.id, "depop", {"state": "unknown", "job_id": "j3", "action": "publish",
                                              "draft_url": "https://www.depop.com/sellinghub/drafts/edit/abc/"})
        # What the seller's "I checked it myself" does: the draft is all that is left.
        self.assertEqual(reset(self.conv.id, "depop", self.db)["state"], "draft")
        body = self.client.post(f"{self.base}/depop/mark", json={"state": "listed", "url": URLS["depop"]}).json()
        self.assertIn("depop", body)
        self.assertEqual(records.get(self.conv.id, "depop")["state"], "published")
        self.assertEqual(body["depop"]["listing_id"], "shop-classic-tee-136d")
        self.assertIn("depop", self.client.get(f"{self.base}").json())

    def test_marking_sold_does_not_revive_a_settled_draft(self):
        from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo

        records = MarketplaceListingRepo(self.db)
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {}})
        self.db.commit()
        records.save(self.conv.id, "depop", {"state": "draft", "draft_url": "https://www.depop.com/sellinghub/drafts/edit/abc/"})
        self.client.post(f"{self.base}/depop/mark", json={"state": "sold"})
        self.assertEqual(records.get(self.conv.id, "depop")["state"], "draft")

    def test_delist_holds_the_automation_slot_and_keeps_the_marketplace_message(self):
        from vendoo_studio.repositories.queries import JobRepo

        seen = []

        async def delete(job, kind, payload, timeout):
            seen.append([j.current_step for j in JobRepo(self.db).get_running()])
            return {"ok": False, "error": "Mercari did not delete it.", "marketplace_message": "Item is in a transaction. token=abc"}

        self.bridge.side_effect = delete
        result = self.client.post(f"{self.base}/delist", json={"marketplaces": ["mercari"], "confirm": True}).json()
        self.assertEqual(seen, [["native_delist"]])
        self.assertEqual(result["mercari"]["state"], "failed")
        self.assertEqual(result["mercari"]["marketplace_message"], "Item is in a transaction. token=[redacted]")
        self.assertFalse(JobRepo(self.db).get_running())
        JobRepo(self.db).create(self.conv.id, "r", {}, status="dispatched", current_step="vendoo_api_create")
        self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["ebay"], "confirm": True}).status_code, 409)

    def test_vinted_is_deleted_through_chrome(self):
        result = self.client.post(f"{self.base}/delist", json={"marketplaces": ["vinted"], "confirm": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["vinted"]["state"], "deleted")
        self.assertEqual(self.bridge.call_args.args[1], "marketplace.delete")
        self.assertEqual(self.bridge.call_args.args[2], {"marketplace": "vinted", "listing_id": "42", "confirm": True})
        self.ebay.assert_not_called()
        self.etsy.assert_not_called()

    def test_browser_marketplaces_need_chrome(self):
        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["depop"], "confirm": True}).status_code, 409)
            self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["vinted"], "confirm": True}).status_code, 409)
            self.assertEqual(self.client.post(f"{self.base}/delist", json={"marketplaces": ["etsy"], "confirm": True}).status_code, 200)


class MarketplaceStepsTest(unittest.IsolatedAsyncioTestCase):
    async def test_etsy_checks_the_shop_then_deletes(self):
        from vendoo_studio.services import marketplace_delist as d

        calls = []

        async def api(method, path, **_):
            calls.append((method, path))
            return {"shop_id": 42, "state": "active"} if method == "GET" else {}

        with patch("vendoo_studio.services.etsy_listings.connected_shop_id", return_value="42"), \
                patch.object(d.marketplace_accounts, "etsy_api", side_effect=api):
            self.assertEqual((await d._delete_etsy("4578284433"))["state"], "deleted")
        self.assertEqual(calls, [("GET", "listings/4578284433"), ("DELETE", "listings/4578284433")])

    async def test_etsy_refuses_another_shop(self):
        from vendoo_studio.services import marketplace_delist as d

        api = AsyncMock(return_value={"shop_id": 7, "state": "active"})
        with patch("vendoo_studio.services.etsy_listings.connected_shop_id", return_value="42"), \
                patch.object(d.marketplace_accounts, "etsy_api", api):
            with self.assertRaises(ValueError):
                await d._delete_etsy("4578284433")
        self.assertEqual(api.await_count, 1)

    async def test_ebay_ends_the_item_and_treats_already_ended_as_done(self):
        from vendoo_studio.services import marketplace_delist as d
        from vendoo_studio.services.ebay_client import EbayFailure

        client = SimpleNamespace(trading=AsyncMock(return_value={}))
        with patch("vendoo_studio.services.ebay_client.EbayClient.connect", AsyncMock(return_value=client)):
            self.assertEqual((await d._delete_ebay("377507697747"))["state"], "deleted")
            client.trading.assert_awaited_once_with("EndFixedPriceItem", {"ItemID": "377507697747", "EndingReason": "NotAvailable"})
            client.trading.side_effect = EbayFailure("eBay rejected the listing request. Error code: 1047.")
            self.assertTrue((await d._delete_ebay("377507697747"))["already"])
            client.trading.side_effect = EbayFailure("eBay rejected the listing request. Error code: 17.")
            with self.assertRaises(EbayFailure):
                await d._delete_ebay("377507697747")

    async def test_the_end_request_declares_xml_so_ebay_parses_it(self):
        from vendoo_studio.services.ebay_client import EbayClient

        client = EbayClient("token", ("seller", "connected"))
        sent = {}

        async def request(_method, _path, **kwargs):
            sent["xml"] = kwargs.get("xml")
            return {"xml": None}

        with patch.object(client, "request", request):
            await client.trading("EndFixedPriceItem", {"ItemID": "377507697747", "EndingReason": "NotAvailable"})
        self.assertTrue(sent["xml"].startswith('<?xml version="1.0" encoding="utf-8"?>'))
        self.assertIn("<ItemID>377507697747</ItemID>", sent["xml"])
        self.assertIn("<EndingReason>NotAvailable</EndingReason>", sent["xml"])
