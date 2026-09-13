from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.services.brave_search import (
    BRAVE_SEARCH_URL,
    brave_sold_query,
    fields_from_analysis,
    format_comp_results,
    research_brave_comps,
    search_web,
    sold_comps_query,
)


BRAVE_PAYLOAD = {
    "web": {
        "results": [
            {
                "title": "Levi's 511 Slim Shorts - Sold",
                "url": "https://www.ebay.com/itm/123",
                "description": "Sold for $22. Similar Levi's shorts.",
                "extra_snippets": ["Completed listing $18 to $25"],
            }
        ]
    }
}


class CompQueryTest(unittest.TestCase):
    def test_query_uses_brand_and_item_type(self):
        query = sold_comps_query({"brand": "Levi's", "style": "slim shorts", "size": "33"})
        self.assertEqual(query, "Levi's slim shorts sold comps")

    def test_query_prefers_category_over_style(self):
        query = sold_comps_query({"brand": "Nike", "category": "T-Shirt", "style": "Graphic Tee"})
        self.assertEqual(query, "Nike T-Shirt sold comps")

    def test_query_empty_without_brand_or_item(self):
        self.assertEqual(sold_comps_query({"size": "M"}), "")

    def test_brave_query_targets_marketplace_sites(self):
        query = brave_sold_query({"brand": "Levi's", "style": "slim shorts"})
        self.assertTrue(query.startswith("Levi's slim shorts sold"))
        self.assertIn("site:ebay.com", query)

    def test_fields_from_analysis_text(self):
        text = "Photo analysis:\n- brand: Levi's (source: tag)\n- style: Slim shorts\n- size: 33"
        fields = fields_from_analysis(text)
        self.assertEqual(fields["brand"], "Levi's")
        self.assertEqual(fields["style"], "Slim shorts")


class FormatCompsTest(unittest.TestCase):
    def test_formats_results_for_prompt(self):
        text = format_comp_results("Levi's slim shorts sold comps", [
            BRAVE_PAYLOAD["web"]["results"][0],
            {
                "title": "How to find sold comps on eBay",
                "url": "https://www.terapeak.com/blog/sold-comps-guide",
                "description": "Learn how to search sold listings for $20.",
            },
        ])
        self.assertTrue(text.startswith("Sold comps:"))
        self.assertIn("Query: Levi's slim shorts sold comps", text)
        self.assertIn("Source: Brave Search", text)
        self.assertIn("$22 · eBay", text)
        self.assertIn("https://www.ebay.com/itm/123", text)
        self.assertIn("market × 1.35", text)
        self.assertNotIn("How to", text)

    def test_empty_results_asks_for_baseline(self):
        text = format_comp_results("Nike tee sold comps", [])
        self.assertIn("No sold listings found", text)
        self.assertIn("estimated baseline", text)


class ResearchCompsTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_no_api_key(self):
        with patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value=None):
            text = await research_brave_comps("Levi's shorts sold comps")
        self.assertEqual(text, "")

    async def test_searches_and_formats_when_key_present(self):
        with (
            patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value="BSA-test"),
            patch("vendoo_studio.services.brave_search.search_web", new=AsyncMock(return_value=BRAVE_PAYLOAD["web"]["results"])) as search,
        ):
            text = await research_brave_comps("Levi's Slim shorts sold comps")
        search.assert_awaited_once()
        self.assertEqual(search.await_args.args[0], "Levi's Slim shorts sold comps")
        self.assertIn("$22 · eBay", text)

    async def test_search_failure_returns_baseline_note(self):
        with (
            patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value="BSA-test"),
            patch("vendoo_studio.services.brave_search.search_web", new=AsyncMock(side_effect=RuntimeError("Brave HTTP 401: invalid token"))),
        ):
            text = await research_brave_comps("Nike Tee sold comps")
        self.assertTrue(text.startswith("Sold comps:"))
        self.assertIn("Search failed", text)
        self.assertIn("estimated baseline", text)


class SearchWebTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_brave_web_search_endpoint(self):
        captured = {}

        class FakeResp:
            status_code = 200
            text = ""

            def json(self):
                return BRAVE_PAYLOAD

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, headers=None, params=None):
                captured["url"] = url
                captured["headers"] = headers
                captured["params"] = params
                return FakeResp()

        with patch("vendoo_studio.services.brave_search.httpx.AsyncClient", FakeClient):
            results = await search_web("Levi's shorts sold comps", "BSA-test")
        self.assertEqual(captured["url"], BRAVE_SEARCH_URL)
        self.assertEqual(captured["headers"]["X-Subscription-Token"], "BSA-test")
        self.assertEqual(captured["params"]["q"], "Levi's shorts sold comps")
        self.assertEqual(results[0]["title"], "Levi's 511 Slim Shorts - Sold")


class BraveSettingsRouteTest(unittest.TestCase):
    def test_get_unconfigured(self):
        from fastapi.testclient import TestClient
        from vendoo_studio.main import app

        with patch("vendoo_studio.services.keychain.get_brave_api_key", return_value=None):
            resp = TestClient(app).get("/api/settings/brave")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"configured": False, "masked_key": None})

    def test_put_requires_key(self):
        from fastapi.testclient import TestClient
        from vendoo_studio.main import app

        resp = TestClient(app).put("/api/settings/brave", json={"api_key": "  "})
        self.assertEqual(resp.status_code, 400)
