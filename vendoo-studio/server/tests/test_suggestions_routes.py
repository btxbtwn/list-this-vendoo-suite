from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from vendoo_studio.main import app


class SuggestionsRouteTest(unittest.TestCase):
    def test_lists_suggestions(self):
        client = TestClient(app)
        response = client.get("/api/suggestions")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("suggestions", body)
        self.assertIsInstance(body["suggestions"], list)
        for card in body["suggestions"]:
            self.assertIn(card["kind"], {
                "failed",
                "ready_to_generate",
                "fix_validation",
                "stale_active",
                "ready_to_review",
            })
            self.assertEqual(card["action"], "open")
            self.assertIn("conversation_id", card)


if __name__ == "__main__":
    unittest.main()
