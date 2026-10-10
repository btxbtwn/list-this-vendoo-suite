from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vendoo_studio.static_files import IMMUTABLE, REVALIDATE, FrontendFiles, cache_control


class FrontendCacheHeadersTest(unittest.TestCase):
    """A browser must re-check the page shell on every load and may keep hashed chunks forever."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dist = Path(tmp.name)
        (dist / "index.html").write_text("<html></html>")
        (dist / "build-stamp.json").write_text("{}")
        (dist / "assets").mkdir()
        (dist / "assets" / "index-1a4b581.js").write_text("console.log(1)")
        app = FastAPI()
        app.mount("/", FrontendFiles(directory=str(dist), html=True), name="static")
        self.client = TestClient(app)

    def test_the_page_shell_is_revalidated_and_hashed_chunks_are_immutable(self):
        for path in ("/", "/index.html", "/build-stamp.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).headers["cache-control"], REVALIDATE)
        self.assertEqual(self.client.get("/assets/index-1a4b581.js").headers["cache-control"], IMMUTABLE)

    def test_a_not_modified_answer_carries_the_same_policy(self):
        etag = self.client.get("/index.html").headers["etag"]
        response = self.client.get("/index.html", headers={"If-None-Match": etag})
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers["cache-control"], REVALIDATE)

    def test_cache_control_by_path(self):
        self.assertEqual(cache_control("assets/x.js"), IMMUTABLE)
        self.assertEqual(cache_control("favicon.png"), REVALIDATE)
