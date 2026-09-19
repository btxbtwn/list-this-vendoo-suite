from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_reset_keep_inputs_keeps_photos_and_notes(self):
        notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "condition": "Good",
            "categoryOverride": "Men > Tops",
        })
        self.conv.notes = notes
        self.db.commit()

        with patch("vendoo_studio.routes.conversations.PHOTOS_DIR", self.photos_tmp.name):
            response = self.client.post(
                f"/api/conversations/{self.conv.id}/reset",
                json={"keep_inputs": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "New Listing")
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["notes"], notes)

        self.db.expire_all()
        self.assertEqual(len(ConversationRepo(self.db).get_photos(self.conv.id)), 1)
        self.assertTrue((Path(self.photos_tmp.name) / "front.jpg").exists())
        self.assertEqual(ConversationRepo(self.db).get_messages(self.conv.id), [])
        self.assertEqual(self.db.query(Job).filter(Job.conversation_id == self.conv.id).count(), 0)
        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertEqual([r.listing_json for r in revisions], [{}])

    def test_reset_missing_conversation_is_404(self):
        response = self.client.post("/api/conversations/missing/reset")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
