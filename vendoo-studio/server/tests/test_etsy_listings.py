from __future__ import annotations

import asyncio
import copy
import io
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.services.photo_store import LocalPhotoStore
from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import etsy_listings, native_marketplaces, relay_client

LISTING = {"title": "Private api check - do not publish", "description": "Private draft check.", "price": 12,
           "direct_category_ids": {"etsy": "482"}, "etsy_specifics": {
               "who_made": "Another company or person", "what_is": "A finished product", "when_made": "1990s (Vintage)",
               "shipping_profile_id": "99", "readiness_state_id": "88", "return_policy_id": "77"}}
URL = "https://www.etsy.com/your/shops/me/listing-editor/edit/123456"


class EtsyListingsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        self.db = self.sessions()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title=LISTING["title"])
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, copy.deepcopy(LISTING), "model")
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("vendoo_studio.services.photo_store._store", LocalPhotoStore(self.temp)))
        for index in range(2):
            name = f"test-{index}.jpg"
            Path(self.temp, name).write_bytes(b"image")
            ConversationRepo(self.db).add_photo(self.conv.id, name, name, "image/jpeg", 5)
        self.enterContext(patch.object(etsy_listings, "get_marketplace_accounts", return_value={"etsy": {"accountId": "123", "accessToken": "never-expose"}}))
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)))
        self.enterContext(patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"))
        self.bridge = self.enterContext(patch("vendoo_studio.services.native_marketplaces.browser_bridge.request", new_callable=AsyncMock))
        self.calls = []
        self.remote = None
        self.inventory = None
        self.failure = None
        self.calculated = False
        self.uploaded = 0
        self.other_drafts = []
        self.properties = []
        self.listing_properties = {}
        self.drop_properties = False
        # Each test answers Etsy's schema itself; nothing is kept between tests.
        self.enterContext(patch("vendoo_studio.services.marketplace_schemas.load_rows", return_value=None))
        self.enterContext(patch("vendoo_studio.services.marketplace_schemas.save_rows"))
        self.enterContext(patch.dict("vendoo_studio.services.marketplace_schemas._etsy_taxonomy", {"at": 0.0, "leaves": ()}))
        self.api = self.enterContext(patch.object(etsy_listings.marketplace_accounts, "etsy_api", side_effect=self.request))
        self.enterContext(patch("vendoo_studio.database.SessionLocal", self.sessions))
        self.enterContext(patch("vendoo_studio.services.user_settings.get_etsy_listing_defaults", return_value={}))
        self.launched = []
        self.enterContext(patch.object(native_marketplaces, "_launch", self.launched.append))
        self.base = f"/api/conversations/{self.conv.id}/native-marketplaces/etsy"

    def tearDown(self):
        for coro in self.launched:
            coro.close()
        app.dependency_overrides.clear()
        self.db.close()

    async def request(self, method, path, **kwargs):
        data = copy.deepcopy(kwargs.get("data") or kwargs.get("json_body") or {})
        self.calls.append((method, path, data, bool(kwargs.get("files"))))
        if self.failure:
            result = self.failure(method, path)
            if result:
                raise result
        if "/videos" in path:
            return self.video_request(method, path, kwargs)
        if path.endswith("/shipping-profiles"):
            return {"results": [{"shipping_profile_id": 99, "title": "Buyer pays", "origin_postal_code": "never-expose",
                                 "profile_type": "calculated" if self.calculated else "manual"}]}
        if path.endswith("/policies/return"):
            return {"results": [{"return_policy_id": 77, "accepts_returns": True, "accepts_exchanges": False, "return_deadline": 30}]}
        if path == "seller-taxonomy/nodes":
            return {"results": [{"id": 1, "children": [{"id": 482, "children": []}, {"id": 600, "children": [{"id": 601}]}]}]}
        if path.startswith("seller-taxonomy/nodes/"):
            return {"results": copy.deepcopy(self.properties)}
        if method == "PUT" and "/properties/" in path:
            if not self.drop_properties:
                self.listing_properties[path.rsplit("/", 1)[-1]] = data
            return {}
        if method == "GET" and path.endswith("/properties"):
            if path != "shops/123/listings/123456/properties":
                raise httpx.HTTPStatusError("Resource not found", request=httpx.Request(method, "https://example.test/" + path),
                                            response=httpx.Response(404, json={"error": "Resource not found"}))
            return {"results": [{"property_id": int(pid), "value_ids": [int(v) for v in d["value_ids"].split(",") if v],
                                 "values": d["values"].split(",")} for pid, d in self.listing_properties.items()]}
        if path.endswith("/readiness-state-definitions"):
            return {"results": [{"readiness_state_id": 88, "readiness_state": "ready_to_ship", "processing_days_display_label": "1-2 days"}]}
        if method == "GET" and path == "shops/123/listings":
            drafts = [self.remote] if self.remote and self.remote["state"] == "draft" else []
            return {"results": copy.deepcopy(drafts + self.other_drafts)}
        if method == "GET":
            return copy.deepcopy(self.inventory if path.endswith("/inventory") else self.remote)
        if method == "DELETE":
            image_id = int(path.rsplit("/", 1)[-1])
            self.remote["images"] = [image for image in self.remote["images"] if image["listing_image_id"] != image_id]
            return {}
        if method == "PUT":
            self.inventory = copy.deepcopy(data)
            for product in self.inventory["products"]:
                for offering in product["offerings"]:
                    offering["price"] = {"amount": int(Decimal(str(offering["price"])) * 100), "divisor": 100, "currency_code": "USD"}
            self.remote["price"] = self.inventory["products"][0]["offerings"][0]["price"]
            return copy.deepcopy(self.inventory)
        if path.endswith("/images"):
            self.uploaded += 1
            image = {"listing_image_id": 1000 + self.uploaded, "rank": int(data["rank"])}
            self.remote["images"].append(image)
            return image
        if method == "POST":
            self.remote = {**data, "listing_id": 123456, "shop_id": 123, "state": "draft", "images": []}
        else:
            self.remote.update(data)
        if "price" in data:
            self.remote["price"] = {"amount": int(Decimal(data["price"]) * 100), "divisor": 100, "currency_code": "USD"}
        if method == "POST":
            self.inventory = {"products": [{"sku": "keep-sku", "property_values": [], "offerings": [{
                "price": copy.deepcopy(self.remote["price"]), "quantity": 1, "is_enabled": True, "readiness_state_id": 88}]}]}
        return copy.deepcopy(self.remote)

    def video_request(self, method, path, kwargs):
        videos = self.__dict__.setdefault("videos", [])
        if method == "GET":
            return {"count": len(videos), "results": copy.deepcopy(videos)}
        if method == "DELETE":
            video_id = int(path.rsplit("/", 1)[-1])
            for video in videos:
                if video["video_id"] == video_id:
                    video["video_state"] = "deleted"
            return {}
        data = kwargs.get("data") or {}
        if "video_id" in data:
            video = next(video for video in videos if video["video_id"] == int(data["video_id"]))
            video["video_state"] = "active"
            return copy.deepcopy(video)
        self.video_uploads = getattr(self, "video_uploads", 0) + 1
        video = {"video_id": 5000 + self.video_uploads, "video_state": "active"}
        videos.append(video)
        return copy.deepcopy(video)

    # --- helpers -----------------------------------------------------------------

    def list(self, **extra):
        """List on Etsy through the route, running its background job to the end."""
        response = self.client.post(self.base + "/list", json={"revision_id": self.rev.id, "confirm": True, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        while self.launched:
            asyncio.run(self.launched.pop(0))
        self.db.expire_all()
        return self.record()

    def record(self):
        return MarketplaceListingRepo(self.db).get(self.conv.id, "etsy")

    def execute(self, action, binding, photos=None, **kwargs):
        """One Etsy step straight through the service, the way a List job runs it."""
        def record(values):
            binding.update(values)

        photos = photos if photos is not None else ConversationRepo(self.db).get_photos(self.conv.id)
        return asyncio.run(etsy_listings.execute(action, copy.deepcopy(LISTING) if "snapshot" not in kwargs else kwargs.pop("snapshot"),
                                                 photos, binding, record, lambda: True, confirm=True,
                                                 shipping_profile_id="99", readiness_state_id="88", return_policy_id="77", **kwargs))

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def test_property_readback_uses_shop_endpoint(self):
        assignments = [{"property_id": 200, "name": "Color", "value_ids": [1], "values": ["White"]}]
        self.listing_properties["200"] = {"value_ids": "1", "values": "White"}
        self.assertEqual(asyncio.run(etsy_listings.unkept_properties("123", "123456", assignments)), [])
        self.assertEqual(self.calls[-1][1], "shops/123/listings/123456/properties")

    def test_category_property_readback_allows_photos_and_same_draft_retry(self):
        assignments = [{"property_id": 200, "name": "Color", "value_ids": [1], "values": ["White"]}]
        binding = {}
        with patch.object(etsy_listings, "property_values", return_value=assignments):
            first = self.execute("save_draft", binding)
            self.assertEqual(first["state"], "draft", first)
            self.assertEqual(len(self.remote["images"]), 2)
            second = self.execute("save_draft", binding)
        self.assertEqual(second["state"], "draft", second)
        self.assertEqual(sum(method == "POST" and path == "shops/123/listings" for method, path, *_ in self.calls), 1)

    def test_profile_ids_survive_vendoo_camel_case(self):
        details = {key: value for key, value in LISTING["etsy_specifics"].items()
                   if key not in {"shipping_profile_id", "return_policy_id", "readiness_state_id"}}
        details.update(shippingProfileId="99", returnPolicyId="77", readinessStateId="88")
        fields = etsy_listings.draft_fields({**LISTING, "etsy_specifics": details}, creating=True)
        self.assertEqual(fields["shipping_profile_id"], "99")
        self.assertEqual(fields["return_policy_id"], "77")
        self.assertEqual(fields["readiness_state_id"], "88")

    def test_editor_camel_case_answers_are_read(self):
        # The Etsy tab saves whoMade, whatIsIt and whenMade.
        details = {key: value for key, value in LISTING["etsy_specifics"].items()
                   if key not in {"who_made", "what_is", "when_made"}}
        details.update(whoMade="Another company or person", whatIsIt="A finished product", whenMade="Before 2007 (Vintage)")
        fields = etsy_listings.draft_fields({**LISTING, "etsy_specifics": details}, creating=True)
        self.assertEqual((fields["who_made"], fields["when_made"], fields["is_supply"]), ("someone_else", "before_2007", "false"))

    def test_non_vintage_when_made_is_a_year_range(self):
        made = {**LISTING, "etsy_specifics": {**LISTING["etsy_specifics"], "who_made": "I did", "when_made": "Made To Order (Not Yet Made)"}}
        self.assertEqual(etsy_listings.draft_fields(made, creating=True)["when_made"], "2010_2019")
        recent = {**LISTING, "etsy_specifics": {**LISTING["etsy_specifics"], "who_made": "I did", "when_made": "non-vintage"}}
        self.assertEqual(etsy_listings.draft_fields(recent, creating=True)["when_made"], "2010_2019")
        vintage = {**LISTING, "etsy_specifics": {**LISTING["etsy_specifics"], "when_made": "1990s (Vintage)"}}
        self.assertEqual(etsy_listings.draft_fields(vintage, creating=True)["when_made"], "1990s")

    def test_when_made_follows_etsys_ranges_for_the_year(self):
        from datetime import date

        from vendoo_studio.models import etsy_fields

        self.assertEqual(etsy_fields.etsy_when_made_codes(date(2026, 10, 25)), (
            "made_to_order", "2020_2026", "2010_2019", "2007_2009", "before_2007", "2000_2006", "1990s", "1980s",
            "1970s", "1960s", "1950s", "1940s", "1930s", "1920s", "1910s", "1900s", "1800s", "1700s", "before_1700"))
        new_year = date(2027, 1, 1)
        for label, code in {"2020 - 2026 (Recently)": "2020_2027", "2007 - 2009 (Recently)": "2008_2009",
                            "Before 2007 (Vintage)": "before_2008", "2000 - 2006 (Vintage)": "2000_2007",
                            "2020_2026": "2020_2027", "1900 - 1909 (Vintage)": "1900s", "Before 1700 (Vintage)": "before_1700",
                            "1990s (Vintage)": "1990s", "2010 - 2019 (Recently)": "2010_2019", "Sometime": ""}.items():
            self.assertEqual(etsy_fields.etsy_when_made_code(label, new_year), code, label)
        turned = date(2029, 1, 1)
        self.assertEqual(etsy_fields.etsy_when_made_codes(turned)[:6], (
            "made_to_order", "2020_2029", "2010_2019", "before_2010", "2000_2009", "1990s"))
        self.assertNotIn("2010_2009", etsy_fields.etsy_when_made_codes(turned))
        for label, code in {"2020 - 2026 (Recently)": "2020_2029", "2007 - 2009 (Recently)": "before_2010",
                            "Before 2007 (Vintage)": "before_2010", "2000 - 2006 (Vintage)": "2000_2009",
                            "2010 - 2019 (Recently)": "2010_2019"}.items():
            self.assertEqual(etsy_fields.etsy_when_made_code(label, turned), code, label)
        aged = date(2030, 6, 1)
        self.assertIn("2011_2019", etsy_fields.etsy_when_made_codes(aged))
        self.assertIn("2000_2010", etsy_fields.etsy_when_made_codes(aged))
        self.assertNotIn("2010_2019", etsy_fields.etsy_when_made_codes(aged))
        self.assertEqual(etsy_fields.etsy_when_made_code("2010 - 2019 (Recently)", aged), "2011_2019")

        class NewYear(date):
            @classmethod
            def today(cls):
                return new_year

        vintage = {**LISTING, "etsy_specifics": {**LISTING["etsy_specifics"], "when_made": "Before 2007 (Vintage)"}}
        with patch.object(etsy_fields, "date", NewYear):
            self.assertEqual(etsy_listings.draft_fields(vintage, creating=True)["when_made"], "before_2008")

    def test_list_creates_uploads_and_activates_in_one_job_without_chrome(self):
        record = self.list()
        self.assertEqual(record["state"], "published", record)
        self.assertEqual(record["listing_url"], "https://www.etsy.com/listing/123456")
        self.assertEqual(record["draft_url"], URL)
        self.assertEqual(len(record["etsy_image_ids"]), 2)
        created = next(c[2] for c in self.calls if c[0] == "POST" and c[1].endswith("/listings"))
        self.assertEqual(created["price"], "12.00")
        self.assertEqual(created["who_made"], "someone_else")
        self.assertEqual(created["when_made"], "1990s")
        self.assertEqual(created["should_auto_renew"], "false")
        self.assertEqual(sum(c[3] for c in self.calls), 2)
        self.assertEqual(self.calls[-1], ("PATCH", "shops/123/listings/123456", {"state": "active"}, False))
        self.assertNotIn("never-expose", str(record))
        self.bridge.assert_not_called()
        job = JobRepo(self.db).get(record["job_id"])
        self.assertEqual((job.status, job.current_step), ("completed", "native_etsy_publish"))
        count = len(self.calls)
        self.assertEqual(self.client.post(self.base + "/list", json={"revision_id": self.rev.id, "confirm": True}).status_code, 409)
        self.assertEqual(len(self.calls), count)

    def test_an_ineligible_item_is_refused_before_any_job_or_write(self):
        modern = {**LISTING, "etsy_specifics": {**LISTING["etsy_specifics"], "when_made": "2020 - 2026"}}
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, modern, "user")
        response = self.client.post(self.base + "/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Etsy only allows vintage (20+ years), handmade or craft supplies", response.text)
        self.assertFalse(self.calls)
        self.assertFalse(JobRepo(self.db).list_all())
        result = self.execute("save_draft", {}, snapshot=modern)
        self.assertEqual(result["error"], etsy_listings.NOT_ELIGIBLE)
        self.assertFalse(self.writes())

    def test_saving_an_existing_draft_keeps_native_photos_and_checks_new_price(self):
        binding = {}
        self.assertEqual(self.execute("save_draft", binding)["state"], "draft")
        self.calls.clear()
        result = self.execute("save_draft", binding, snapshot={**LISTING, "price": 13})
        self.assertEqual(result["state"], "draft", result)
        # The category-property schema is read before the draft is touched.
        self.assertEqual([c[0] for c in self.calls], ["GET", "GET", "GET", "PUT", "PATCH", "GET", "GET"])
        self.assertTrue(self.calls[0][1].startswith("seller-taxonomy/nodes/"))
        self.assertNotIn("price", next(c[2] for c in self.calls if c[0] == "PATCH"))
        inventory = next(c[2] for c in self.calls if c[0] == "PUT")
        self.assertEqual(inventory["products"][0]["sku"], "keep-sku")
        self.assertEqual(inventory["products"][0]["offerings"][0], {"price": 13.0, "quantity": 1, "is_enabled": True, "readiness_state_id": 88})
        self.assertEqual(len(self.remote["images"]), 2)

    def test_changed_photos_are_resynced_on_the_same_draft(self):
        binding = {}
        self.execute("save_draft", binding)
        photos = ConversationRepo(self.db).get_photos(self.conv.id)
        Path(self.temp, "test-2.jpg").write_bytes(b"new image")
        added = ConversationRepo(self.db).add_photo(self.conv.id, "test-2.jpg", "test-2.jpg", "image/jpeg", 9)
        kept = [photos[1], added]
        self.calls.clear()
        result = self.execute("save_draft", binding, photos=kept)
        self.assertEqual(result["state"], "draft", result)
        self.assertEqual([c[:2] for c in self.writes()], [("PATCH", "shops/123/listings/123456"),
                                                           ("DELETE", "shops/123/listings/123456/images/1001"),
                                                           ("POST", "shops/123/listings/123456/images")])
        self.assertEqual(set(binding["etsy_image_ids"]), {photos[1].id, added.id})
        self.assertEqual(binding["etsy_photo_ids"], [photos[1].id, added.id])
        self.assertTrue(binding["etsy_photos_complete"])
        self.calls.clear()
        self.execute("save_draft", binding, photos=kept)
        self.assertFalse(any(c[3] for c in self.calls))

    def test_an_edited_photo_is_uploaded_again_in_its_place(self):
        binding = {}
        self.execute("save_draft", binding)
        photos = ConversationRepo(self.db).get_photos(self.conv.id)
        Path(self.temp, "edited.jpg").write_bytes(b"edited image")
        ConversationRepo(self.db).replace_photo_file(
            photos[0], {"stored_filename": "edited.jpg", "size_bytes": 12, "checksum": "e" * 64, "width": 1, "height": 1},
            source_filename=photos[0].stored_filename, edits={"rotate": 90})
        self.calls.clear()
        result = self.execute("save_draft", binding, photos=photos)
        self.assertEqual(result["state"], "draft", result)
        self.assertEqual([c[:2] for c in self.writes()], [("PATCH", "shops/123/listings/123456"),
                                                           ("DELETE", "shops/123/listings/123456/images/1001"),
                                                           ("POST", "shops/123/listings/123456/images")])
        self.assertEqual(binding["etsy_image_checksums"][photos[0].id], "e" * 64)
        self.calls.clear()
        self.execute("save_draft", binding, photos=photos)
        self.assertFalse(any(c[3] for c in self.calls))

    def test_update_changes_the_live_listing_and_does_not_create_another(self):
        self.assertEqual(self.list()["state"], "published")
        self.calls.clear()
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "title": "Updated tee", "price": 13}, "user")
        response = self.client.post(self.base + "/update", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        while self.launched:
            asyncio.run(self.launched.pop(0))
        self.db.expire_all()
        updated = self.record()
        self.assertEqual(updated["state"], "published", updated)
        self.assertEqual(updated["listing_url"], "https://www.etsy.com/listing/123456")
        self.assertNotIn(("POST", "shops/123/listings"), [(c[0], c[1]) for c in self.calls])
        self.assertFalse(any(c[2].get("state") for c in self.calls))
        self.assertEqual(self.remote["title"], "Updated tee")

    def test_changed_remote_fields_or_shop_cannot_be_published(self):
        binding = {}
        self.execute("save_draft", binding)
        for changes in [{"title": "Changed"}, {"shop_id": 999}]:
            previous = copy.deepcopy(self.remote)
            self.remote.update(changes)
            self.calls.clear()
            self.assertFalse(self.execute("publish", dict(binding))["ok"])
            self.assertFalse(self.writes())
            self.remote = previous

    def test_a_lost_activation_is_checked_in_the_same_job_and_never_replayed(self):
        def lost(method, path):
            if method == "PATCH" and self.remote["state"] == "draft" and len(self.remote["images"]) == 2:
                self.remote["state"] = "active"
                return httpx.ReadTimeout("lost response")
        self.failure = lost
        record = self.list()
        # The lost reply was read back while the job still held the slot.
        self.assertEqual(record["state"], "published", record)
        self.assertEqual(sum(c[2] == {"state": "active"} for c in self.calls), 1)

    def test_a_timed_out_activation_that_reads_back_as_a_draft_can_be_listed_again(self):
        self.failure = lambda method, path: httpx.ReadTimeout("lost activation") if method == "PATCH" and self.remote["images"] else None
        record = self.list()
        self.assertEqual(record["state"], "draft", record)
        self.assertIn("List again to publish it", record["error"])
        self.failure = None
        self.assertEqual(self.list()["state"], "published")

    def test_a_lost_create_reply_is_found_among_the_shop_drafts(self):
        def lost(method, path):
            if method == "POST" and path == "shops/123/listings":
                self.failure = None
                self.remote = {**self.calls[-1][2], "listing_id": 123456, "shop_id": 123, "state": "draft", "images": []}
                self.inventory = {"products": [{"sku": "", "property_values": [], "offerings": [{
                    "price": {"amount": 1200, "divisor": 100, "currency_code": "USD"}, "quantity": 1, "is_enabled": True}]}]}
                self.remote["price"] = {"amount": 1200, "divisor": 100, "currency_code": "USD"}
                return httpx.ReadTimeout("lost create")
        self.failure = lost
        record = self.list()
        # Check found the draft by its title: the record has its link, nothing was created twice.
        self.assertEqual(record["draft_url"], URL)
        self.assertEqual(record["state"], "draft", record)
        self.assertEqual(sum(c[0] == "POST" and c[1] == "shops/123/listings" for c in self.calls), 1)
        self.assertEqual(self.list()["state"], "published")
        self.assertEqual(sum(c[0] == "POST" and c[1] == "shops/123/listings" for c in self.calls), 1)

    def test_a_create_that_never_landed_is_safe_to_list_again(self):
        self.failure = lambda method, path: httpx.ReadTimeout("lost create") if method == "POST" and path == "shops/123/listings" else None
        record = self.list()
        self.assertEqual(record["state"], "not_saved", record)
        self.assertIn("no draft from this listing", record["error"])

    def test_several_matching_drafts_stay_unconfirmed(self):
        self.other_drafts = [{"listing_id": 1, "shop_id": 123, "title": LISTING["title"], "state": "draft"},
                             {"listing_id": 2, "shop_id": 123, "title": LISTING["title"], "state": "draft"}]
        self.failure = lambda method, path: httpx.ReadTimeout("lost create") if method == "POST" and path == "shops/123/listings" else None
        record = self.list()
        self.assertEqual((record["state"], record["error_code"]), ("unknown", "uncertain"))
        self.assertIn("2 drafts", record["error"])

    def test_rejected_authorization_is_signed_out_without_an_unknown_create(self):
        self.failure = lambda method, path: etsy_listings.marketplace_accounts.SignInRequired("Sign in to Etsy again.") if method == "POST" else None
        record = self.list()
        self.assertEqual((record["state"], record["error_code"]), ("not_saved", "signed_out"))
        self.failure = None
        self.assertEqual(self.list()["state"], "published")

    def test_rate_limits_say_when_to_try_again_and_keep_etsys_words(self):
        def limited(method, path):
            if method == "POST":
                response = httpx.Response(429, headers={"retry-after": "30"}, json={"error": "Too many requests"},
                                          request=httpx.Request(method, "https://api.etsy.com/"))
                return httpx.HTTPStatusError("limited", request=response.request, response=response)
        self.failure = limited
        record = self.list()
        self.assertEqual((record["state"], record["error_code"]), ("not_saved", "rate_limited"))
        self.assertEqual(record["marketplace_message"], "Too many requests")
        self.assertTrue(record["retry_after"])

    def test_a_refused_listing_keeps_etsys_message_verbatim(self):
        def refused(method, path):
            if method == "POST" and path == "shops/123/listings":
                response = httpx.Response(400, json={"error": "Oh dear, you cannot sell this item on Etsy"},
                                          request=httpx.Request(method, "https://api.etsy.com/"))
                return httpx.HTTPStatusError("refused", request=response.request, response=response)
        self.failure = refused
        record = self.list()
        self.assertEqual((record["state"], record["error_code"]), ("not_saved", "rejected"))
        self.assertEqual(record["marketplace_message"], "Oh dear, you cannot sell this item on Etsy")
        self.assertNotIn("Oh dear", record["error"])

    def test_rejected_photo_resumes_same_draft_without_duplicate_images(self):
        def reject(method, path):
            if path.endswith("/images") and len(self.remote["images"]) == 1:
                response = httpx.Response(400, request=httpx.Request(method, "https://api.etsy.com/"))
                return httpx.HTTPStatusError("rejected", request=response.request, response=response)
        self.failure = reject
        record = self.list()
        self.assertEqual(record["state"], "draft")
        self.assertIsNone(record.get("revision_id"))
        self.assertEqual(len(self.remote["images"]), 1)
        self.failure = None
        self.assertEqual(self.list()["state"], "published")
        self.assertEqual(len(self.remote["images"]), 2)
        self.assertEqual(sum(c[0] == "POST" and c[1] == "shops/123/listings" for c in self.calls), 1)

    def test_lost_last_photo_receipt_can_be_verified_without_reuploading(self):
        binding = {"action": "save_draft"}

        def lost(method, path):
            if path.endswith("/images") and len(self.remote["images"]) == 1:
                self.remote["images"].append({"listing_image_id": 1002, "rank": 2})
                return httpx.ReadTimeout("lost photo receipt")
        self.failure = lost
        result = self.execute("save_draft", binding)
        self.assertEqual(result["error_code"], "uncertain")
        self.failure = None
        self.calls.clear()
        checked = asyncio.run(etsy_listings.check(LISTING, binding, binding["draft_url"]))
        self.assertEqual(checked["state"], "draft", checked)
        self.assertTrue(all(c[0] == "GET" for c in self.calls))

    def test_disconnected_account_fails_before_a_job_or_write(self):
        with patch.object(etsy_listings, "get_marketplace_accounts", return_value={}):
            r = self.client.post(self.base + "/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(r.status_code, 409)
        self.assertFalse(self.calls)
        self.assertFalse(JobRepo(self.db).list_all())

    def test_listing_profiles_expose_only_ids_and_titles(self):
        r = self.client.get("/api/etsy/listing-profiles")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"shipping": [{"id": "99", "title": "Buyer pays", "is_calculated": False}],
                                    "processing": [{"id": "88", "title": "Ready to ship · 1-2 days"}],
                                    "returns": [{"id": "77", "title": "Returns within 30 days"}]})
        self.assertNotIn("never-expose", r.text)

    def test_another_shops_shipping_profile_cannot_create_a_draft(self):
        record = self.list(shipping_profile_id="999")
        self.assertEqual(record["state"], "not_saved", record)
        self.assertFalse(self.writes())

    def test_new_draft_requires_an_explicit_shipping_profile(self):
        result = asyncio.run(etsy_listings.execute("save_draft", {**LISTING, "etsy_specifics": {
            key: value for key, value in LISTING["etsy_specifics"].items() if key != "shipping_profile_id"}},
            ConversationRepo(self.db).get_photos(self.conv.id), {}, lambda values: None, lambda: True))
        self.assertEqual(result["safe_to_retry"], True)
        self.assertIn("shipping profile", result["error"])
        self.assertFalse(self.writes())

    def test_calculated_shipping_requires_explicit_positive_package_measurements(self):
        self.calculated = True
        self.assertEqual(self.list()["state"], "not_saved")
        self.assertFalse(self.writes())
        package = {"item_weight": 8, "item_weight_unit": "oz", "item_length": 12, "item_width": 9, "item_height": 1, "item_dimensions_unit": "in"}
        r = self.client.post(self.base + "/list", json={"revision_id": self.rev.id, "confirm": True, "etsy_package": {**package, "item_weight": 0}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.list(etsy_package=package)["state"], "published")
        created = next(c[2] for c in self.calls if c[0] == "POST" and c[1].endswith("/listings"))
        self.assertEqual(created["item_weight"], "8.0")
        self.assertEqual(created["item_dimensions_unit"], "in")

    def test_variation_prices_are_preserved_instead_of_flattened(self):
        binding = {}
        self.execute("save_draft", binding)
        self.inventory["products"].append(copy.deepcopy(self.inventory["products"][0]))
        self.calls.clear()
        result = self.execute("save_draft", binding, snapshot={**LISTING, "price": 13})
        self.assertFalse(result["ok"])
        self.assertTrue(all(c[0] == "GET" for c in self.calls))

    def test_price_recovery_uses_inventory_when_listing_summary_is_stale(self):
        binding = {"action": "save_draft"}
        self.execute("save_draft", binding)

        def lost(method, path):
            if method == "PUT":
                self.inventory["products"][0]["offerings"][0]["price"]["amount"] = 1300
                return httpx.ReadTimeout("lost price receipt")
        self.failure = lost
        changed = {**LISTING, "price": 13}
        self.assertEqual(self.execute("save_draft", binding, snapshot=changed)["error_code"], "uncertain")
        self.assertEqual(self.remote["price"]["amount"], 1200)
        self.failure = None
        self.calls.clear()
        checked = asyncio.run(etsy_listings.check(changed, binding, URL))
        self.assertEqual(checked["state"], "draft", checked)
        self.assertTrue(all(c[0] == "GET" for c in self.calls))

    def test_invalid_or_ineligible_details_never_create_a_listing(self):
        for changes in [{"direct_category_ids": {}}, {"etsy_specifics": {}}, {"price": "NaN"}, {"price": "0.001"}]:
            with self.assertRaises(ValueError):
                etsy_listings.draft_fields({**LISTING, **changes}, creating=True)

    def test_missing_details_name_the_fields_to_fix(self):
        result = self.execute("save_draft", {}, snapshot={**LISTING, "direct_category_ids": {}})
        self.assertEqual(result["error_code"], "missing_fields")
        self.assertEqual(result["fields"][0]["field"], "direct_category_ids.etsy")

    def test_a_recent_item_can_still_be_prepared_for_etsy(self):
        fields = etsy_listings.draft_fields({**LISTING, "etsy_specifics": {**LISTING["etsy_specifics"], "when_made": "2010 - 2019 (Recently)"}}, creating=True)
        self.assertEqual(fields["when_made"], "2010_2019")

    def test_validation_errors_name_fields_in_our_words_and_keep_etsys_scrubbed(self):
        response = httpx.Response(400, json={"error": "shipping_profile_id is required; token=never-expose"},
                                  request=httpx.Request("POST", "https://api.etsy.com/"))
        error = httpx.HTTPStatusError("never-expose", request=response.request, response=response)
        message = etsy_listings._error_text(error)
        self.assertIn("shipping_profile_id", message)
        self.assertNotIn("never-expose", message)
        result = etsy_listings._failure(error, safe=True)
        self.assertEqual(result["error_code"], "missing_fields")
        self.assertEqual(result["fields"][0]["field"], "etsy_specifics.shipping_profile_id")
        self.assertEqual(result["marketplace_message"], "shipping_profile_id is required; token=[redacted]")


class RelayMultipartTest(unittest.IsolatedAsyncioTestCase):
    async def test_form_and_photo_bytes_reach_the_relay_without_json_wrapping(self):
        requests = []
        async def handle(request):
            requests.append(request)
            return httpx.Response(201, json={"listing_image_id": 1})
        real_client = httpx.AsyncClient
        with patch.object(relay_client, "ensure_device", new_callable=AsyncMock, return_value={"token": "test-only"}), \
             patch.object(relay_client.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs)):
            await relay_client.relay_request("POST", "/studio/etsy/v3/application/shops/123/listings/456/images",
                                             data={"rank": "1"}, files={"image": ("test.jpg", io.BytesIO(b"photo-bytes"), "image/jpeg")})
        self.assertIn("multipart/form-data; boundary=", requests[0].headers["content-type"])
        self.assertIn(b"photo-bytes", requests[0].content)
        self.assertIn(b'name="rank"', requests[0].content)


class EtsyVideoTest(EtsyListingsTest):
    """Listing videos on Etsy, through the same fake shop. Only the video tests run here."""

    def setUp(self):
        import hashlib

        from vendoo_studio.services import listing_videos

        super().setUp()
        self.videos = []
        self.enterContext(patch.object(listing_videos, "VIDEOS_DIR", Path(self.temp)))
        Path(self.temp, "clip.video").write_bytes(b"clip-bytes")
        self.video = {"id": "vid1", "stored_filename": "clip.video", "size_bytes": 10, "mime_type": "video/mp4",
                      "duration_seconds": 8, "checksum": hashlib.sha256(b"clip-bytes").hexdigest()}
        self.snapshot = {**copy.deepcopy(LISTING), "_native_video": self.video}
        self.snapshot["etsy_specifics"]["videoId"] = "vid1"

    def video_writes(self):
        return [call for call in self.calls if "/videos" in call[1] and call[0] != "GET"]

    def save(self, binding, snapshot=None):
        return self.execute("save_draft", binding, snapshot=copy.deepcopy(snapshot or self.snapshot))

    def test_save_draft_uploads_the_video_once_and_reads_it_back(self):
        binding = {}
        result = self.save(binding)
        self.assertTrue(result["ok"], result)
        uploads = [call for call in self.video_writes() if call[0] == "POST"]
        self.assertEqual(len(uploads), 1)
        self.assertTrue(uploads[0][3], "the file goes as multipart")
        self.assertEqual(uploads[0][2]["name"], "vid1.mp4")
        self.assertEqual(binding["etsy_video"], {"checksum": self.video["checksum"], "video_id": "5001"})
        self.calls.clear()
        self.assertTrue(self.save(binding)["ok"])
        self.assertFalse(self.video_writes(), "saving the same revision again uploads nothing")

    def test_a_lost_upload_reply_is_adopted_not_repeated(self):
        binding = {}
        self.assertTrue(self.save(binding)["ok"])
        self.calls.clear()
        binding["etsy_video"] = {"checksum": self.video["checksum"], "pending": True}
        self.assertTrue(self.save(binding)["ok"])
        self.assertFalse(self.video_writes())
        self.assertEqual(binding["etsy_video"]["video_id"], "5001")
        self.videos.append({"video_id": 7000, "video_state": "active"})
        binding["etsy_video"] = {"checksum": self.video["checksum"], "pending": True}
        result = self.save(binding)
        self.assertFalse(result["ok"])
        self.assertIn("more than one video", result["error"])

    def test_a_removed_video_is_attached_again_without_uploading(self):
        binding = {}
        self.assertTrue(self.save(binding)["ok"])
        self.videos[0]["video_state"] = "inactive"
        self.calls.clear()
        self.assertTrue(self.save(binding)["ok"])
        self.assertEqual([call[2] for call in self.video_writes()], [{"video_id": "5001"}])

    def test_clearing_deletes_the_video_and_a_new_file_replaces_it(self):
        binding = {}
        self.assertTrue(self.save(binding)["ok"])
        cleared = copy.deepcopy(self.snapshot)
        cleared["etsy_specifics"]["videoId"] = ""
        cleared["_native_video"] = None
        self.calls.clear()
        self.assertTrue(self.save(binding, cleared)["ok"])
        self.assertEqual([call[:2] for call in self.video_writes()], [("DELETE", "shops/123/listings/123456/videos/5001")])
        self.assertIsNone(binding["etsy_video"])
        Path(self.temp, "clip.video").write_bytes(b"clip-bytes")
        self.assertTrue(self.save(binding)["ok"])
        self.assertEqual([video["video_state"] for video in self.videos], ["deleted", "active"])

    def test_publish_refuses_a_flagged_or_missing_video(self):
        binding = {}
        self.assertTrue(self.save(binding)["ok"])
        self.videos[0]["video_state"] = "flagged"
        self.calls.clear()
        result = self.execute("publish", binding, snapshot=copy.deepcopy(self.snapshot))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "missing_fields")
        self.assertEqual(result["fields"][0]["field"], "etsy_specifics.videoId")
        self.assertFalse(self.writes())
        result = self.save(binding)
        self.assertFalse(result["ok"])
        self.assertIn("flagged", result["error"])

    def test_publish_lists_with_the_active_video(self):
        binding = {}
        self.assertTrue(self.save(binding)["ok"])
        result = self.execute("publish", binding, snapshot=copy.deepcopy(self.snapshot))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "published")

    def test_check_matches_the_video_without_writing(self):
        binding = {}
        self.assertTrue(self.save(binding)["ok"])
        binding["action"] = "save_draft"
        self.calls.clear()
        self.assertTrue(asyncio.run(etsy_listings.check(self.snapshot, binding, URL))["ok"])
        self.videos[0]["video_state"] = "deleted"
        self.assertFalse(asyncio.run(etsy_listings.check(self.snapshot, binding, URL))["ok"])
        self.assertFalse(self.writes())

    def test_a_changed_file_never_reaches_etsy(self):
        Path(self.temp, "clip.video").write_bytes(b"other-byte")
        binding = {}
        result = self.save(binding)
        self.assertFalse(result["ok"])
        self.assertIn("changed", result["error"])
        self.assertFalse([call for call in self.video_writes() if call[0] == "POST"])


# Only the video tests run in the subclass; the inherited ones already ran above.
for _name in [name for name in vars(EtsyListingsTest) if name.startswith("test_")]:
    setattr(EtsyVideoTest, _name, None)
