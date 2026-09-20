from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation  # noqa: F401
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import hidden_fields


JPEG_BYTES = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
])


class ConversationResetTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.photos_tmp = tempfile.TemporaryDirectory()
        self.data_tmp = tempfile.TemporaryDirectory()
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        os.environ["VENDOO_STUDIO_DATA_DIR"] = self.data_tmp.name

        self.conv = ConversationRepo(self.db).create(title="Nike tee", notes=json.dumps({"condition": "Good"}))
        ConversationRepo(self.db).update_status(self.conv.id, "completed")
        ConversationRepo(self.db).add_message(self.conv.id, "user", "make it cheaper")
        stored = "front.jpg"
        (Path(self.photos_tmp.name) / stored).write_bytes(JPEG_BYTES)
        ConversationRepo(self.db).add_photo(
            self.conv.id,
            "front.jpg",
            stored,
            "image/jpeg",
            len(JPEG_BYTES),
        )
        revision = ListingRepo(self.db).save_revision(
            self.conv.id,
            {"title": "Nike tee", "description": "Soft cotton", "price": 20},
            "generate",
        )
        JobRepo(self.db).create(
            self.conv.id,
            revision.id,
            revision.listing_json,
            status="dispatched",
            current_step="filling_fields",
        )
        hidden_fields.hide_field("ebay", "Department", "always", label="Department")
        hidden_fields.hide_field(
            "depop",
            "Source",
            "listing",
            conversation_id=self.conv.id,
            label="Source",
        )

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.photos_tmp.cleanup()
        self.data_tmp.cleanup()
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data

    def test_reset_wipes_listing_and_keeps_conversation(self):
        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name):
            response = self.client.post(f"/api/conversations/{self.conv.id}/reset")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], self.conv.id)
        self.assertEqual(body["title"], "New Listing")
        self.assertIsNone(body["notes"])
        self.assertEqual(body["status"], "draft")
        self.assertIsNone(body["settled_at"])

        self.db.expire_all()
        self.assertEqual(ConversationRepo(self.db).get_photos(self.conv.id), [])
        self.assertEqual(ConversationRepo(self.db).get_messages(self.conv.id), [])
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id), [])
        self.assertIsNone(ListingRepo(self.db).get_current(self.conv.id))
        self.assertEqual(self.db.query(Job).filter(Job.conversation_id == self.conv.id).count(), 0)
        self.assertFalse((Path(self.photos_tmp.name) / "front.jpg").exists())

        listing = self.client.get(f"/api/conversations/{self.conv.id}/listing")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["listing"], {})

        hidden = hidden_fields.hidden_fields(self.conv.id)
        self.assertEqual(len(hidden["always"]), 1)
        self.assertEqual(hidden["listing"], [])

    def test_reset_keeps_vendoo_binding(self):
        from vendoo_studio.services.vendoo_import import vendoo_binding

        self.conv.notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "vendooUrl": "https://web.vendoo.co/app/item/QVzIZuKs",
            "condition": "Good",
            "categoryOverride": "Men > Tops",
        })
        self.db.commit()

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name):
            response = self.client.post(f"/api/conversations/{self.conv.id}/reset")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "New Listing")
        self.assertEqual(body["status"], "draft")
        binding = vendoo_binding(body["notes"])
        self.assertEqual(binding["vendooItemId"], "QVzIZuKs")
        self.assertEqual(binding["vendooUrl"], "https://web.vendoo.co/app/item/QVzIZuKs")
        notes = json.loads(body["notes"])
        self.assertNotIn("condition", notes)
        self.assertNotIn("categoryOverride", notes)

        self.db.expire_all()
        self.assertEqual(ConversationRepo(self.db).get_photos(self.conv.id), [])
        self.assertEqual(ConversationRepo(self.db).get_messages(self.conv.id), [])
        self.assertEqual(self.db.query(Job).filter(Job.conversation_id == self.conv.id).count(), 0)
        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].listing_json, {})
        self.assertEqual(revisions[0].source, "reset")

        ensure = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id})
        self.assertEqual(ensure.status_code, 200, ensure.text)
        self.assertEqual(ensure.json()["vendoo_item_id"], "QVzIZuKs")

    def test_reset_keep_inputs_reattaches_fields_job_without_chrome_import(self):
        """Regenerate must not leave the editor looking like a fresh Link."""
        self.conv.notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "vendooUrl": "https://web.vendoo.co/app/item/QVzIZuKs",
        })
        self.db.commit()

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name), \
             patch(
                 "vendoo_studio.services.vendoo_create.resolve_label_display_names",
                 new=AsyncMock(side_effect=lambda _job, labels: list(labels)),
             ):
            response = self.client.post(
                f"/api/conversations/{self.conv.id}/reset",
                json={"keep_inputs": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        jobs = JobRepo(self.db).list_by_conversation(self.conv.id)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.current_step, "fields_applied")
        self.assertEqual(job.vendoo_item_id, "QVzIZuKs")
        self.assertEqual(job.vendoo_url, "https://web.vendoo.co/app/item/QVzIZuKs")
        # ensure-draft should reuse this row instead of creating another.
        ensure = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id})
        self.assertEqual(ensure.status_code, 200, ensure.text)
        self.assertEqual(ensure.json()["id"], job.id)

    def test_reset_does_not_wait_out_a_silent_chrome_for_label_names(self):
        """A Chrome that never answers list_labels must not stall Regenerate.

        The label catalog only prettifies carried-over labels, so it gets the
        short lookup budget rather than the 4-minute form-fill one.
        """
        from vendoo_studio.services import vendoo_label_catalog

        vendoo_label_catalog.clear_for_tests()
        self.conv.notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "vendooLabels": "0GbMUqtBqPkGDcEyNqYQ",
        })
        self.db.commit()

        class SilentChrome:
            """Connected, accepts the message, never sends a result back."""

            connected = True

            def register_wait(self, request_id: str, job_id: str | None = None):
                return asyncio.get_running_loop().create_future()

            async def send_message(self, _message) -> bool:
                return True

            def cancel_wait(self, _request_id: str) -> None:
                return None

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name), \
             patch(
                 "vendoo_studio.services.browser_bridge._manager",
                 return_value=SilentChrome(),
             ), \
             patch("vendoo_studio.services.vendoo_create.LOOKUP_TIMEOUT_SEC", 0.2):
            started = time.monotonic()
            response = self.client.post(
                f"/api/conversations/{self.conv.id}/reset",
                json={"keep_inputs": True},
            )
            elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 200, response.text)
        self.assertLess(elapsed, 10.0, "reset waited out the label catalog read")
        self.assertEqual(response.json()["title"], "New Listing")
        # The label id survives unresolved rather than blocking the reset.
        self.assertEqual(
            json.loads(response.json()["notes"])["vendooLabels"],
            "0GbMUqtBqPkGDcEyNqYQ",
        )

    def test_reset_renames_opaque_labels_from_cached_catalog_when_chrome_is_silent(self):
        """Cached id→name mappings still paint chips when list_labels never answers."""
        from vendoo_studio.services import vendoo_label_catalog

        vendoo_label_catalog.clear_for_tests()
        vendoo_label_catalog.remember({"0GbMUqtBqPkGDcEyNqYQ": "Women"})
        self.conv.notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "vendooLabels": "0GbMUqtBqPkGDcEyNqYQ",
        })
        self.db.commit()

        class SilentChrome:
            connected = True

            def register_wait(self, request_id: str, job_id: str | None = None):
                return asyncio.get_running_loop().create_future()

            async def send_message(self, _message) -> bool:
                return True

            def cancel_wait(self, _request_id: str) -> None:
                return None

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name), \
             patch(
                 "vendoo_studio.services.browser_bridge._manager",
                 return_value=SilentChrome(),
             ), \
             patch("vendoo_studio.services.vendoo_create.LOOKUP_TIMEOUT_SEC", 0.2):
            response = self.client.post(
                f"/api/conversations/{self.conv.id}/reset",
                json={"keep_inputs": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(response.json()["notes"])["vendooLabels"], "Women")

    def test_reset_keep_inputs_keeps_photos_and_notes(self):
        notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "condition": "Good",
            "categoryOverride": "Men > Tops",
        })
        self.conv.notes = notes
        self.db.commit()

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name), \
             patch(
                 "vendoo_studio.services.vendoo_create.resolve_label_display_names",
                 new=AsyncMock(side_effect=lambda _job, labels: list(labels)),
             ):
            response = self.client.post(
                f"/api/conversations/{self.conv.id}/reset",
                json={"keep_inputs": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "New Listing")
        self.assertEqual(body["status"], "draft")
        # Item Details survive, plus the listing's price so the rewrite reuses it.
        self.assertEqual(
            json.loads(body["notes"]),
            {**json.loads(notes), "askingPrice": "20.00"},
        )

        self.db.expire_all()
        self.assertEqual(len(ConversationRepo(self.db).get_photos(self.conv.id)), 1)
        self.assertTrue((Path(self.photos_tmp.name) / "front.jpg").exists())
        self.assertEqual(ConversationRepo(self.db).get_messages(self.conv.id), [])
        # Regenerate keeps the Vendoo link and reattaches Fields so remount does
        # not look like a fresh Link (which would open Chrome and re-import).
        jobs = self.db.query(Job).filter(Job.conversation_id == self.conv.id).all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, "completed")
        self.assertEqual(jobs[0].current_step, "fields_applied")
        self.assertEqual(jobs[0].vendoo_item_id, "QVzIZuKs")
        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertEqual([r.listing_json for r in revisions], [{}])

    def test_reset_keep_inputs_carries_listing_facts_into_item_details(self):
        self.conv.notes = json.dumps({"condition": "Good"})
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {
                "title": "Nike tee",
                "description": (
                    "Cozy oversized grunge tee.\n\n"
                    "Flaws: small stain near the hem.\n\n"
                    'Measurements: Pit to pit 20"; Length 27"'
                ),
                "cost": 1.5,
                "sku": "NIKE-TEE-M",
                "package_dimensions_in": "12x10x2",
                "poshmark_specifics": {"originalPrice": 45},
                "labels": ["Bin 4"],
                "internal_notes": "Bought at the bins",
            },
            "generate",
        )
        self.db.commit()

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name), \
             patch(
                 "vendoo_studio.services.vendoo_create.resolve_label_display_names",
                 new=AsyncMock(side_effect=lambda _job, labels: list(labels)),
             ):
            response = self.client.post(
                f"/api/conversations/{self.conv.id}/reset",
                json={"keep_inputs": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        notes = json.loads(response.json()["notes"])
        self.assertEqual(notes["sku"], "NIKE-TEE-M")
        self.assertEqual(notes["packageDimensions"], "12x10x2")
        self.assertEqual(notes["poshmarkOriginalPrice"], "45")
        self.assertEqual(notes["cog"], "1.50")
        self.assertEqual(notes["vendooLabels"], "Bin 4")
        self.assertEqual(notes["sellerNotes"], "Bought at the bins")
        self.assertEqual(notes["knownFlaws"], "small stain near the hem")
        self.assertEqual(notes["descriptionMeasurements"], 'Pit to pit 20"; Length 27"')

        self.db.expire_all()
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id), [])

    def test_reset_without_keep_inputs_carries_nothing(self):
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {"title": "Nike tee", "description": "Flaws: small stain near the hem.", "cost": 1.5},
            "generate",
        )
        self.db.commit()

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name):
            response = self.client.post(f"/api/conversations/{self.conv.id}/reset")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["notes"])

    def test_reset_missing_conversation_is_404(self):
        response = self.client.post("/api/conversations/missing/reset")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
