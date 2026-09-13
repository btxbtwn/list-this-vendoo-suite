from __future__ import annotations

import json
import subprocess
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
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"
JPEG_BYTES = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
])


class UploadPhotosExtensionTest(unittest.TestCase):
    def test_content_script_does_not_fetch_studio_from_vendoo_page(self) -> None:
        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("async function fetchStudioPhotoFiles", background)
        self.assertIn("/api/jobs/${jobId}/photos/", background)
        self.assertIn("type: 'UPLOAD_PHOTOS'", background)
        self.assertIn("files,", background)
        self.assertNotIn("studioUrl}/api/jobs/", content)
        self.assertNotIn("studio_url", content)
        self.assertIn("uploadStudioPhotos(msg.files || [])", content)

    def test_upload_photos_timeout_scales_with_file_count(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function commandTimeoutMs")
        end = text.index("function compactVendooValue")
        script = text[start:end] + """
const result = {
  none: commandTimeoutMs({ type: 'UPLOAD_PHOTOS' }),
  empty: commandTimeoutMs({ type: 'UPLOAD_PHOTOS', files: [] }),
  four: commandTimeoutMs({ type: 'UPLOAD_PHOTOS', files: Array(4).fill({}) }),
  twenty: commandTimeoutMs({ type: 'UPLOAD_PHOTOS', files: Array(20).fill({}) }),
  saveGeneral: commandTimeoutMs({ type: 'SAVE_GENERAL' }),
  defaultType: commandTimeoutMs({ type: 'UNKNOWN_COMMAND' }),
};
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["none"], 60000)
        self.assertEqual(result["empty"], 60000)
        self.assertEqual(result["four"], 60000)
        self.assertEqual(result["twenty"], 180000)
        self.assertEqual(result["saveGeneral"], 60000)
        self.assertEqual(result["defaultType"], 45000)

    def test_background_fetches_job_photos_and_encodes_files(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function arrayBufferToBase64")
        end = text.index("async function uploadPhotos")
        script = (
            "const STUDIO_URL = 'http://127.0.0.1:4318';\n"
            "function log() {}\n"
            + text[start:end]
            + """
const jpeg = Uint8Array.from([255, 216, 255, 217]);
globalThis.fetch = async (url) => {
  if (String(url).includes('missing')) {
    return { ok: false, status: 404, headers: { get: () => '' }, arrayBuffer: async () => new ArrayBuffer(0) };
  }
  return {
    ok: true,
    headers: { get: () => 'image/jpeg' },
    arrayBuffer: async () => jpeg.buffer,
  };
};
(async () => {
  const encoded = arrayBufferToBase64(jpeg.buffer);
  const result = await fetchStudioPhotoFiles('job1', [
    { id: 'photo-ok', name: 'front.jpg' },
    { id: 'missing' },
    {},
  ]);
  console.log(JSON.stringify({
    encoded,
    fileCount: result.files.length,
    fileName: result.files[0] && result.files[0].name,
    fileType: result.files[0] && result.files[0].type,
    fileData: result.files[0] && result.files[0].data,
    errors: result.errors,
  }));
})();
"""
        )
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["fileCount"], 1)
        self.assertEqual(result["fileName"], "front.jpg")
        self.assertEqual(result["fileType"], "image/jpeg")
        self.assertEqual(result["fileData"], result["encoded"])
        self.assertEqual(result["errors"], ["missing: HTTP 404", "Photo is missing an id"])


class JobPhotoRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()
        self.conv = Conversation(title="Bamboo jeans")
        self.db.add(self.conv)
        self.db.commit()
        self.job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Bamboo jeans"},
            status="dispatched",
        )
        self.db.add(self.job)
        self.db.commit()
        self.tmp = tempfile.TemporaryDirectory()
        stored = "front.jpg"
        (Path(self.tmp.name) / stored).write_bytes(JPEG_BYTES)
        self.photo = ConversationRepo(self.db).add_photo(
            self.conv.id,
            "front.jpg",
            stored,
            "image/jpeg",
            len(JPEG_BYTES),
        )

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
        self.tmp.cleanup()

    def test_job_photo_is_served_for_matching_conversation(self):
        with patch("vendoo_studio.routes.jobs.PHOTOS_DIR", self.tmp.name):
            response = self.client.get(f"/api/jobs/{self.job.id}/photos/{self.photo.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, JPEG_BYTES)
        self.assertIn("image/jpeg", response.headers.get("content-type", ""))

    def test_job_photo_rejects_unknown_photo(self):
        with patch("vendoo_studio.routes.jobs.PHOTOS_DIR", self.tmp.name):
            response = self.client.get(f"/api/jobs/{self.job.id}/photos/does-not-exist")
        self.assertEqual(response.status_code, 404)
