from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo, JobRepo
from vendoo_studio.services.vendoo_import import (
    image_urls_from_vendoo,
    listing_from_vendoo,
    parse_notes,
    vendoo_binding,
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

    @patch("vendoo_studio.routes.imports.download_vendoo_photos", new_callable=AsyncMock)
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
        self.assertTrue(draft.get("item") or draft.get("form"))

    @patch("vendoo_studio.routes.imports.download_vendoo_photos", new_callable=AsyncMock)
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

    @patch("vendoo_studio.routes.imports.download_vendoo_photos", new_callable=AsyncMock)
    def test_photo_download_failure_still_imports(self, download):
        download.return_value = []
        response = self._import()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["photo_count"], 0)
        self.assertTrue(body["photo_warnings"])
        listing_resp = self.client.get(f"/api/conversations/{body['conversation_id']}/listing")
        self.assertEqual(listing_resp.status_code, 200, listing_resp.text)
        self.assertTrue(listing_resp.json()["can_send"])

    def test_import_requires_item_id(self):
        response = self.client.post("/api/imports/vendoo", json={"item_id": "new", "item": VENDOO_ITEM})
        self.assertEqual(response.status_code, 400)

    @patch("vendoo_studio.routes.imports.download_vendoo_photos", new_callable=AsyncMock)
    def test_import_draft_available_without_chrome(self, download):
        download.return_value = []
        imported = self._import().json()
        job_id = imported["job_id"]
        with patch("vendoo_studio.routes.extension.extension_manager") as manager:
            manager.connected = False
            response = self.client.post(f"/api/jobs/{job_id}/vendoo-item")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body.get("item") or body.get("form"))
        self.assertEqual(body.get("item_id"), "abc123")

    @patch("vendoo_studio.routes.imports.download_vendoo_photos", new_callable=AsyncMock)
    def test_create_job_copies_vendoo_binding(self, download):
        download.return_value = [{
            "original_filename": "a.jpg",
            "stored_filename": "stored.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 12,
            "checksum": "abc",
            "width": 10,
            "height": 10,
        }]
        imported = self._import().json()
        conv_id = imported["conversation_id"]
        with patch("vendoo_studio.routes.jobs.JobRepo.get_active", return_value=[]), patch(
            "vendoo_studio.routes.extension.dispatch_queued_jobs", new_callable=AsyncMock
        ):
            response = self.client.post("/api/jobs", json={"conversation_id": conv_id})
        self.assertEqual(response.status_code, 200, response.text)
        job = JobRepo(self.db).get(response.json()["id"])
        self.assertEqual(job.vendoo_item_id, "abc123")
        self.assertEqual(job.vendoo_url, "https://web.vendoo.co/app/item/abc123")

    @patch("vendoo_studio.routes.imports.download_vendoo_photos", new_callable=AsyncMock)
    def test_create_job_allows_imported_listing_without_photos(self, download):
        download.return_value = []
        imported = self._import().json()
        conv_id = imported["conversation_id"]
        with patch("vendoo_studio.routes.jobs.JobRepo.get_active", return_value=[]), patch(
            "vendoo_studio.routes.extension.dispatch_queued_jobs", new_callable=AsyncMock
        ):
            response = self.client.post("/api/jobs", json={"conversation_id": conv_id})
        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
