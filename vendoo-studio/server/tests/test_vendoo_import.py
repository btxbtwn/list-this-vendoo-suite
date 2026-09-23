from __future__ import annotations

import asyncio
import json
import socket
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo, JobRepo
from vendoo_studio.services.vendoo_import import (
    _download_public_image,
    vendoo_dates,
    image_urls_from_vendoo,
    import_vendoo_item,
    listing_from_vendoo,
    parse_notes,
    vendoo_binding,
    vendoo_image_url,
)


VENDOO_ITEM = {
    "itemID": "abc123",
    "generalDetails": {
        "title": "Nike Air Tee",
        "description": "Soft cotton tee",
        "price": "24.00",
        "cost": 5,
        "quantity": 1,
        "brand": "Nike",
        "condition": "Pre-Owned - Good",
        "primaryColor": "Black",
        "secondaryColor": "White",
        "categoryV2": {"displayPath": ["Clothing", "Men", "Tops"]},
        "size": {"option": {"value": "M"}, "scale": {"value": "Regular"}},
        "sku": "NIKE-M",
        "tags": ["nike", "tee"],
        "labels": ["To List"],
        "weight": {"pounds": 0, "ounces": 8},
        "dimensions": {"length": 13, "width": 10, "height": 3},
        "notes": "Small stain",
        "images": [
            {"url": "https://cdn.example/a.jpg"},
            {"originalUrl": "https://cdn.example/b.png"},
        ],
    },
    "listings": {
        "ebay": {
            "marketplaceSpecifics": {
                "type": "T-Shirt",
                "department": "Men",
                "sizeType": "Regular",
                "size": "M",
            },
            "categorySpecifics": {"material": "Cotton"},
        },
        "poshmark": {
            "marketplaceSpecifics": {
                "categoryPath": ["Women", "Tops"],
                "originalPrice": 40,
            }
        },
        "mercari": {
            "marketplaceSpecifics": {"shippingLabel": "USPS Ground Advantage"}
        },
        "depop": {
            "marketplaceSpecifics": {"source": "Preloved", "style": ["Streetwear"]}
        },
        "etsy": {
            "marketplaceSpecifics": {
                "whoMade": "Another company or person",
                "whatIs": "A finished product",
                "whenMade": "1990s",
            },
            "categorySpecifics": {"sleeveLength": "Short Sleeve"},
        },
    },
}

VENDOO_FORM = {
    "generalDetails": {
        "title": "Form title ignored",
        "description": "Form description ignored",
    }
}


class VendooImportMapperTest(unittest.TestCase):
    def test_maps_general_and_marketplace_fields(self):
        listing = listing_from_vendoo(VENDOO_ITEM, VENDOO_FORM)
        self.assertEqual(listing["title"], "Nike Air Tee")
        self.assertEqual(listing["description"], "Soft cotton tee")
        self.assertEqual(listing["price"], 24.0)
        self.assertEqual(listing["cost"], 5.0)
        self.assertEqual(listing["brand"], "Nike")
        self.assertEqual(listing["size"], "M")
        self.assertEqual(listing["sizeType"], "Regular")
        self.assertEqual(listing["category_path"], "Clothing > Men > Tops")
        self.assertEqual(listing["tags"], ["nike", "tee"])
        self.assertEqual(listing["package_dimensions_in"], "13x10x3")
        self.assertEqual(listing["internal_notes"], "Small stain")
        self.assertEqual(listing["ebay_specifics"]["type"], "T-Shirt")
        self.assertEqual(listing["ebay_specifics"]["material"], "Cotton")
        self.assertEqual(listing["poshmark_specifics"]["originalPrice"], 40)
        self.assertEqual(listing["poshmark_specifics"]["categoryPath"], ["Women", "Tops"])
        self.assertEqual(listing["mercari_specifics"]["shippingLabel"], "USPS Ground Advantage")
        self.assertEqual(listing["depop_specifics"]["source"], "Preloved")
        self.assertEqual(listing["etsy_specifics"]["who_made"], "Another company or person")
        self.assertEqual(listing["etsy_specifics"]["category_specifics"]["sleeveLength"], "Short Sleeve")
        self.assertEqual(listing["labels"], ["To List"])

    def test_label_details_replace_opaque_ids_with_names(self):
        item = {
            "labels": ["g8MHWF7KiscANFLZRGyM", "0kGVwda9cRk55wmfd3Bq"],
            "labelDetails": [
                {"id": "g8MHWF7KiscANFLZRGyM", "name": "Women"},
                {"id": "0kGVwda9cRk55wmfd3Bq", "displayName": "To List"},
            ],
            "generalDetails": {"title": "Blouse", "price": 12},
        }
        listing = listing_from_vendoo(item, None)
        self.assertEqual(listing["labels"], ["Women", "To List"])

    def test_extracts_nested_and_marketplace_image_urls(self):
        item = {
            "images": [{
                "original": {"location": "https://storage.googleapis.com/vendoo/a.jpg"},
                "url": "https://cdn.example/thumb.jpg",
            }],
            "listings": {
                "ebay": {
                    "images": [{"src": "https://images.cloudinary.com/b.png"}],
                }
            },
        }
        urls = image_urls_from_vendoo(item, None)
        self.assertEqual(urls, [
            "https://storage.googleapis.com/vendoo/a.jpg",
            "https://cdn.example/thumb.jpg",
            "https://images.cloudinary.com/b.png",
        ])

    def test_extracts_explicit_image_urls(self):
        urls = image_urls_from_vendoo(None, None, ["https://cdn.example/extra.webp"])
        self.assertEqual(urls, ["https://cdn.example/extra.webp"])

    def test_maps_vendoo_option_ids_and_ebay_path_objects(self):
        item = {
            "generalDetails": {
                "title": "Sauza Tee",
                "description": "Graphic tee",
                "price": 20,
                "condition": "v_preowned",
                "primaryColor": "v_Gray",
            },
            "listings": {
                "ebay": {
                    "marketplaceSpecifics": {
                        "type": {"displayName": "T-Shirt", "displayPath": ["Clothing", "Tops", "T-Shirt"]},
                        "department": {"displayPath": ["Women"]},
                    }
                }
            },
        }
        listing = listing_from_vendoo(item, None)
        self.assertEqual(listing["condition"], "Pre-Owned - Good")
        self.assertEqual(listing["primaryColor"], "Gray")
        self.assertEqual(listing["ebay_specifics"]["type"], "T-Shirt")
        self.assertEqual(listing["ebay_specifics"]["department"], "Women")
        from vendoo_studio.models.schema import ListingSchema
        ListingSchema.model_validate(listing)

    def test_extracts_image_urls(self):
        urls = image_urls_from_vendoo(VENDOO_ITEM, None)
        self.assertEqual(urls, ["https://cdn.example/a.jpg", "https://cdn.example/b.png"])

    def test_binding_from_notes(self):
        notes = json.dumps({"vendooItemId": "abc123", "vendooLabels": "To List"})
        self.assertEqual(vendoo_binding(notes)["vendooItemId"], "abc123")
        self.assertEqual(vendoo_binding(notes)["vendooUrl"], "https://web.vendoo.co/app/item/abc123")
        self.assertEqual(parse_notes(notes)["vendooLabels"], "To List")


class SafePhotoDownloadTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _public_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))]

    async def test_download_connects_to_validated_ip_with_original_host_and_sni(self):
        requests = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"jpeg")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            with patch("vendoo_studio.services.safe_fetch.socket.getaddrinfo", side_effect=self._public_dns) as resolve:
                content, content_type, final_url = await _download_public_image(
                    client,
                    "https://cdn.example/photo.jpg",
                )

        self.assertEqual(content, b"jpeg")
        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(final_url, "https://cdn.example/photo.jpg")
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(requests[0].url.host, "93.184.216.34")
        self.assertEqual(requests[0].headers["host"], "cdn.example")
        self.assertEqual(requests[0].extensions["sni_hostname"], "cdn.example")

    async def test_dns_rebinding_cannot_change_the_connect_address(self):
        resolutions = [
            self._public_dns(),
            [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 0))],
        ]
        connected_hosts = []

        async def handler(request: httpx.Request) -> httpx.Response:
            connected_hosts.append(request.url.host)
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            with patch("vendoo_studio.services.safe_fetch.socket.getaddrinfo", side_effect=resolutions) as resolve:
                await _download_public_image(client, "https://rebind.example/photo.png")

        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(connected_hosts, ["93.184.216.34"])

    async def test_redirect_to_private_host_is_rejected_before_request(self):
        requested = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(302, headers={"location": "https://127.0.0.1/private.jpg"})

        from vendoo_studio.services.safe_fetch import UnsafeURLError

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            with patch("vendoo_studio.services.safe_fetch.socket.getaddrinfo", side_effect=self._public_dns):
                with self.assertRaises(UnsafeURLError):
                    await _download_public_image(client, "https://cdn.example/photo.jpg")

        self.assertEqual(len(requested), 1)


class VendooDatesTest(unittest.TestCase):
    """Vendoo's time tracking, read off whatever shape the payload arrived in."""

    ITEM = {
        "dateCreated": {"_seconds": 1735689600, "_nanoseconds": 0},  # 2025-01-01
        "dateLastModified": 1757000000000,  # epoch millis
        "listings": {
            "ebay": {
                "dateListed": "2026-03-01T00:00:00Z",
                # A relist moves the listing date forward.
                "lastDateListed": ["2026-05-02T00:00:00Z"],
                "lastStatusDate": {"listed": {"_seconds": 1752000000}},
            },
            "poshmark": {"dateListed": "2026-01-15T00:00:00Z", "dateSold": "2026-08-02T00:00:00Z"},
            "validate": {"ignored": True},
        },
        "saleRecord": {"date_sold": "2026-08-02T00:00:00Z", "marketplace": "poshmark"},
    }

    def test_reads_every_stamp(self):
        dates = vendoo_dates(self.ITEM)
        self.assertEqual(dates["created"], "2025-01-01T00:00:00+00:00")
        self.assertEqual(dates["modified"], "2025-09-04T15:33:20+00:00")
        # The newest listing date across the marketplaces, relists included.
        self.assertEqual(dates["listed"], "2026-05-02T00:00:00+00:00")
        self.assertEqual(dates["sold"], "2026-08-02T00:00:00+00:00")
        self.assertEqual(
            dates["listedByMarketplace"],
            {"ebay": "2026-05-02T00:00:00+00:00", "poshmark": "2026-01-15T00:00:00+00:00"},
        )
        self.assertEqual(dates["soldByMarketplace"], {"poshmark": "2026-08-02T00:00:00+00:00"})

    def test_item_that_never_went_live_falls_back_to_its_creation(self):
        dates = vendoo_dates({"dateCreated": "2026-09-01T00:00:00Z"})
        self.assertEqual(dates["listed"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(dates["modified"], "2026-09-01T00:00:00+00:00")
        self.assertEqual(dates["sold"], "")
        self.assertEqual(dates["listedByMarketplace"], {})

    def test_junk_dates_are_dropped_rather_than_guessed(self):
        dates = vendoo_dates({"dateCreated": "not a date", "listings": {"ebay": {"dateListed": None}}})
        self.assertEqual(dates["created"], "")
        self.assertEqual(dates["listed"], "")


class VendooImageUrlTest(unittest.TestCase):
    """Vendoo stores image records, not links; these are the shapes it keeps."""

    def test_image_server_record_becomes_a_full_size_url(self):
        self.assertEqual(
            vendoo_image_url({"version": 3, "id": "images/u1/abc.jpg", "originalMaxDimension": 1600}),
            "https://images.vendoo.co/images/u1/abc.jpg",
        )
        self.assertEqual(
            vendoo_image_url({"version": 2, "id": "eu/images/u1/abc.png"}),
            "https://images.vendoo.co/eu/images/u1/abc.png",
        )

    def test_legacy_cloudinary_records_keep_their_own_url(self):
        record = {"id": "abc", "url": "https://res.cloudinary.com/vendoo/image/upload/abc.jpg"}
        self.assertEqual(vendoo_image_url(record), record["url"])

    def test_records_carrying_their_own_link_are_left_to_the_url_walk(self):
        self.assertEqual(vendoo_image_url({"url": "https://cdn.example/a.jpg"}), "")
        self.assertEqual(vendoo_image_url({}), "")
        # The walk still finds them, preferring an original over a thumbnail.
        item = {"images": [{"original": {"location": "https://cdn.example/full.jpg"},
                            "url": "https://cdn.example/thumb.jpg"}]}
        self.assertEqual(
            image_urls_from_vendoo(item, None),
            ["https://cdn.example/full.jpg", "https://cdn.example/thumb.jpg"],
        )

    def test_item_images_are_collected_in_order(self):
        item = {"generalDetails": {"images": [
            {"version": 3, "id": "images/u1/one.jpg"},
            {"version": 3, "id": "images/u1/two.jpg"},
        ]}}
        self.assertEqual(
            image_urls_from_vendoo(item, None),
            ["https://images.vendoo.co/images/u1/one.jpg", "https://images.vendoo.co/images/u1/two.jpg"],
        )


class VendooImportRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def _import(self, item_id="abc123", item=None):
        return self.client.post("/api/imports/vendoo", json={
            "item_id": item_id,
            "url": f"https://web.vendoo.co/app/item/{item_id}",
            "item": item or VENDOO_ITEM,
            "form": VENDOO_FORM,
        })

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_import_creates_conversation_and_listing(self, download):
        download.return_value = [{
            "original_filename": "a.jpg",
            "stored_filename": "stored.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 12,
            "checksum": "abc",
            "width": 10,
            "height": 10,
        }]
        response = self._import()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["reused"])
        self.assertEqual(body["photo_count"], 1)
        self.assertTrue(body.get("job_id"))
        conv = ConversationRepo(self.db).get(body["conversation_id"])
        self.assertIsNotNone(conv)
        self.assertEqual(vendoo_binding(conv.notes)["vendooItemId"], "abc123")
        listing = ListingRepo(self.db).get_revisions(conv.id)[0].listing_json
        self.assertEqual(listing["title"], "Nike Air Tee")
        self.assertEqual(listing["ebay_specifics"]["type"], "T-Shirt")
        job = JobRepo(self.db).get(body["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "imported")
        self.assertEqual(job.vendoo_item_id, "abc123")
        draft = JobRepo(self.db).get_vendoo_draft(job.id)
        self.assertIsNotNone(draft)
        self.assertEqual(draft["item_id"], "abc123")

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_import_same_item_updates_existing_conversation(self, download):
        download.return_value = []
        first = self._import()
        conv_id = first.json()["conversation_id"]
        updated_item = json.loads(json.dumps(VENDOO_ITEM))
        updated_item["generalDetails"]["title"] = "Nike Air Tee Updated"
        second = self._import(item=updated_item)
        self.assertEqual(second.status_code, 200, second.text)
        body = second.json()
        self.assertTrue(body["reused"])
        self.assertEqual(body["conversation_id"], conv_id)
        listing = ListingRepo(self.db).get_revisions(conv_id)[0].listing_json
        self.assertEqual(listing["title"], "Nike Air Tee Updated")
        self.assertEqual(len(ConversationRepo(self.db).list_all()), 1)

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_photo_download_failure_still_imports(self, download):
        download.return_value = []
        response = self._import()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["photo_count"], 0)
        self.assertTrue(body["photo_warnings"])
        listing_resp = self.client.get(f"/api/conversations/{body['conversation_id']}/listing")
        self.assertEqual(listing_resp.status_code, 200, listing_resp.text)
        self.assertFalse(listing_resp.json()["can_send"])

    def test_import_requires_item_id(self):
        response = self.client.post("/api/imports/vendoo", json={"item_id": "new", "item": VENDOO_ITEM})
        self.assertEqual(response.status_code, 400)

    def test_import_rejects_all_route_item_ids(self):
        for item_id in ("new", "edit", "create", "NEW"):
            response = self.client.post("/api/imports/vendoo", json={"item_id": item_id, "item": VENDOO_ITEM})
            self.assertEqual(response.status_code, 400, item_id)

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_the_cached_draft_still_answers_without_chrome(self, download):
        """Fields come from Vendoo, but the binding Studio last saw survives Chrome being away."""
        download.return_value = []
        imported = self._import().json()
        job_id = imported["job_id"]
        with patch("vendoo_studio.routes.extension.extension_manager") as manager:
            manager.connected = False
            response = self.client.post(f"/api/jobs/{job_id}/vendoo-item")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body.get("item_id"), "abc123")

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_import_records_vendoos_label_and_cover(self, download):
        """An imported item wears Vendoo's own label and keeps its image as a fallback."""
        download.return_value = []
        asyncio.run(import_vendoo_item(self.db, item_id="abc123", item=VENDOO_ITEM))
        download.assert_awaited_once()

        listed = self.client.get("/api/conversations").json()
        self.assertEqual(listed[0]["vendoo_status"], "draft")
        self.assertEqual(listed[0]["vendoo_cover_url"], "https://cdn.example/a.jpg")
        self.assertEqual(listed[0]["status"], "draft")
        # This fixture carries no Vendoo dates, so the row says so rather than
        # inventing one.
        self.assertIsNone(listed[0]["vendoo_listed_at"])

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_import_records_vendoos_dates(self, download):
        """Vendoo's time tracking rides along on the row the sidebar sorts on."""
        download.return_value = []
        dated = {
            **VENDOO_ITEM,
            "dateCreated": "2026-02-01T00:00:00Z",
            "dateLastModified": "2026-08-30T00:00:00Z",
            "listings": {"ebay": {"dateListed": "2026-03-04T00:00:00Z"}},
        }
        asyncio.run(import_vendoo_item(self.db, item_id="abc123", item=dated))

        row = self.client.get("/api/conversations").json()[0]
        self.assertEqual(row["vendoo_created_at"], "2026-02-01T00:00:00+00:00")
        self.assertEqual(row["vendoo_modified_at"], "2026-08-30T00:00:00+00:00")
        self.assertEqual(row["vendoo_listed_at"], "2026-03-04T00:00:00+00:00")
        self.assertEqual(row["vendoo_listed_dates"], {"ebay": "2026-03-04T00:00:00+00:00"})
        self.assertIsNone(row["vendoo_sold_at"])


if __name__ == "__main__":
    unittest.main()
