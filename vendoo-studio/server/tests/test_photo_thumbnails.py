from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo


def _jpeg(width: int, height: int, color: str = "red") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "JPEG")
    return buffer.getvalue()


class PhotoThumbnailTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.photos_tmp = tempfile.TemporaryDirectory()
        self.photos_dir = Path(self.photos_tmp.name)

        repo = ConversationRepo(self.db)
        self.conv = repo.create(title="Nike tee")
        self.photos = []
        for name in ("back.jpg", "front.jpg"):
            (self.photos_dir / name).write_bytes(_jpeg(1200, 900))
            photo = repo.add_photo(
                self.conv.id,
                name,
                name,
                "image/jpeg",
                len(_jpeg(1200, 900)),
            )
            self.photos.append(photo)
        # Make the second upload the cover, the way a reorder in the tray would.
        repo.reorder_photos(self.conv.id, [self.photos[1].id, self.photos[0].id])

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.photos_tmp.cleanup()

    def test_list_returns_cover_photo_url_for_first_photo(self):
        response = self.client.get("/api/conversations")
        self.assertEqual(response.status_code, 200, response.text)
        row = next(c for c in response.json() if c["id"] == self.conv.id)
        self.assertEqual(
            row["cover_photo_url"], f"/api/photos/{self.photos[1].id}/thumb?size=96"
        )

    def test_cover_photo_url_is_null_without_photos(self):
        empty = ConversationRepo(self.db).create(title="Empty")
        response = self.client.get(f"/api/conversations/{empty.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["cover_photo_url"])

    def test_thumbnail_is_smaller_than_the_original_and_cached(self):
        photo_id = self.photos[0].id
        with patch("vendoo_studio.services.photos.PHOTOS_DIR", str(self.photos_dir)):
            first = self.client.get(f"/api/photos/{photo_id}/thumb?size=96")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.headers["content-type"], "image/jpeg")

            with Image.open(BytesIO(first.content)) as img:
                self.assertLessEqual(max(img.size), 96)
            self.assertLess(len(first.content), (self.photos_dir / "back.jpg").stat().st_size)

            cached = list((self.photos_dir / "thumbs").glob("*.jpg"))
            self.assertEqual(len(cached), 1)
            written_at = cached[0].stat().st_mtime_ns

            second = self.client.get(f"/api/photos/{photo_id}/thumb?size=96")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(cached[0].stat().st_mtime_ns, written_at)

    def test_thumbnail_rejects_unsupported_size(self):
        response = self.client.get(f"/api/photos/{self.photos[0].id}/thumb?size=1000")
        self.assertEqual(response.status_code, 400)

    def test_deleting_a_photo_removes_its_thumbnail(self):
        photo_id = self.photos[0].id
        with patch("vendoo_studio.services.photos.PHOTOS_DIR", str(self.photos_dir)), patch(
            "vendoo_studio.routes.conversations.PHOTOS_DIR", str(self.photos_dir)
        ):
            self.client.get(f"/api/photos/{photo_id}/thumb?size=96")
            self.assertTrue(list((self.photos_dir / "thumbs").glob("*.jpg")))

            response = self.client.delete(
                f"/api/conversations/{self.conv.id}/photos/{photo_id}"
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(list((self.photos_dir / "thumbs").glob("*.jpg")), [])


if __name__ == "__main__":
    unittest.main()
