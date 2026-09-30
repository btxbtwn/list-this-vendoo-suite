from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.services.brave_search import (
    BRAVE_SEARCH_URL,
    MARKETPLACE_SITES,
    brave_active_queries,
    brave_sold_queries,
    brave_sold_query,
    comp_identities,
    search_all,
    fields_from_analysis,
    comp_report,
    research_brave_report,
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
        self.assertEqual(query, "Levi's slim shorts 33 sold comps")

    def test_query_prefers_category_over_style(self):
        query = sold_comps_query({"brand": "Nike", "category": "T-Shirt", "style": "Graphic Tee"})
        self.assertEqual(query, "Nike Graphic Tee T-Shirt sold comps")

    def test_query_uses_category_path_leaf(self):
        query = sold_comps_query({"brand": "GB Girls", "category": "Tops > T-Shirts"})
        self.assertEqual(query, "GB Girls T-Shirts sold comps")

    def test_query_empty_without_brand_or_item(self):
        self.assertEqual(sold_comps_query({"size": "M"}), "")

    def test_brave_query_targets_marketplace_sites(self):
        query = brave_sold_query({"brand": "Levi's", "style": "slim shorts"})
        self.assertTrue(query.startswith("Levi's slim shorts sold"))
        self.assertIn("site:ebay.com", query)

    def test_fields_from_analysis_text(self):
        text = (
            "Photo analysis:\n- brand: Levi's (source: tag)\n- style: Slim shorts\n"
            "- size: 33\n- material: Cotton\n- graphic: Red Tab logo\n- department: Men"
        )
        fields = fields_from_analysis(text)
        self.assertEqual(fields["brand"], "Levi's")
        self.assertEqual(fields["style"], "Slim shorts")
        self.assertEqual(fields["material"], "Cotton")
        self.assertEqual(fields["department"], "Men")
        self.assertEqual(fields["graphic"], "Red Tab logo")

    def test_query_reads_like_a_listing_title(self):
        query = sold_comps_query({
            "brand": "Patagonia",
            "category": "Jackets",
            "style": "Nano Puff",
            "size": "M",
            "color": "Blue",
            "material": "Polyester",
            "department": "Men",
        })
        self.assertEqual(query, "Patagonia Nano Puff Jackets men's M sold comps")

    def test_long_analysis_values_stay_out_of_the_query(self):
        # The fields photo analysis produced for a Peanuts tee that found no comps.
        fields = {
            "brand": "Peanuts",
            "style": "Short-sleeve graphic t-shirt with scoop neck and side hem slit",
            "graphic": "Snoopy and Woodstock",
            "category": "T-shirt",
            "size": "XS",
            "color": "Charcoal heather gray",
            "material": "65% polyester, 35% cotton",
            "department": "Women",
        }
        self.assertEqual(
            sold_comps_query(fields),
            "Peanuts Snoopy and Woodstock T-shirt women's XS sold comps",
        )
        queries = brave_sold_queries(fields)
        self.assertTrue(queries[0].startswith("Peanuts Snoopy and Woodstock T-shirt women's XS sold ("))
        # A looser query drops department and size for when that size never sold.
        self.assertTrue(queries[-1].startswith("Peanuts Snoopy and Woodstock T-shirt sold ("))
        for query in queries:
            self.assertNotIn("scoop", query)
            self.assertNotIn("polyester", query)

    def test_category_is_not_repeated_inside_a_longer_word(self):
        query = sold_comps_query({"brand": "Topshop", "category": "Tops"})
        self.assertEqual(query, "Topshop Tops sold comps")

    def test_comp_identities_accept_the_graphic(self):
        self.assertEqual(
            comp_identities({"brand": "Peanuts", "graphic": "Snoopy and Woodstock"}),
            ("Peanuts", "Snoopy and Woodstock"),
        )
        self.assertEqual(comp_identities({"brand": "Levi's"}), ("Levi's",))
        self.assertEqual(comp_identities({"graphic": "Snoopy"}), ())


class CompQueryFanOutTest(unittest.TestCase):
    def test_one_query_per_marketplace_plus_the_broad_one(self):
        queries = brave_sold_queries({"brand": "Levi's", "category": "Tops > Shorts"})
        self.assertEqual(queries[0], brave_sold_query({"brand": "Levi's", "category": "Tops > Shorts"}))
        for site in MARKETPLACE_SITES:
            self.assertTrue(
                any(query.endswith(f"site:{site}") for query in queries),
                f"no per-site query for {site}",
            )
        for query in queries:
            self.assertIn("Levi's", query)
            self.assertIn("sold", query)

    def test_active_queries_target_each_site_without_sold_terms(self):
        queries = brave_active_queries({"brand": "Nike", "category": "Shoes", "size": "10"})
        self.assertEqual(len(queries), len(MARKETPLACE_SITES))
        for site, query in zip(MARKETPLACE_SITES, queries, strict=True):
            self.assertEqual(query, f"Nike Shoes 10 site:{site}")
        self.assertEqual(brave_active_queries({"size": "M"}), [])

    def test_short_style_joins_the_query(self):
        queries = brave_sold_queries(
            {"brand": "Nike", "category": "Tops > T-Shirts", "style": "Graphic Tee"}
        )
        self.assertTrue(all("Nike Graphic Tee T-Shirts" in query for query in queries))

    def test_no_queries_without_brand_or_item(self):
        self.assertEqual(brave_sold_queries({"size": "M"}), [])


class SearchAllTest(unittest.IsolatedAsyncioTestCase):
    async def test_merges_results_and_survives_a_failed_query(self):
        async def fake_search(query: str, _key: str, *, count: int = 8) -> list[dict]:
            if "poshmark" in query:
                raise RuntimeError("Brave HTTP 422: bad query")
            return [{"url": f"https://www.ebay.com/itm/{query[-1]}", "title": query}]

        with (
            patch("vendoo_studio.services.brave_search.search_web", new=fake_search),
            patch("vendoo_studio.services.brave_search.BRAVE_QUERY_STAGGER_SEC", 0),
        ):
            results, errors = await search_all(["a site:ebay.com", "b site:poshmark.com", "c"], "BSA-test")
        self.assertEqual(len(results), 2)
        self.assertEqual(len(errors), 1)

    async def test_retries_once_when_rate_limited(self):
        calls: list[str] = []

        async def fake_search(query: str, _key: str, *, count: int = 8) -> list[dict]:
            calls.append(query)
            if len(calls) == 1:
                raise RuntimeError("Brave HTTP 429: Too Many Requests")
            return [{"url": "https://www.ebay.com/itm/1", "title": query}]

        with (
            patch("vendoo_studio.services.brave_search.search_web", new=fake_search),
            patch("vendoo_studio.services.brave_search.BRAVE_QUERY_STAGGER_SEC", 0),
            patch("vendoo_studio.services.brave_search.BRAVE_RETRY_SEC", 0),
        ):
            results, errors = await search_all(["levis sold"], "BSA-test")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(errors, [])


class CompReportTest(unittest.TestCase):
    def test_keeps_sold_listings_and_drops_guides(self):
        report = comp_report("Levi's slim shorts sold comps", [
            BRAVE_PAYLOAD["web"]["results"][0],
            {
                "title": "How to find sold comps on eBay",
                "url": "https://www.terapeak.com/blog/sold-comps-guide",
                "description": "Learn how to search sold listings for $20.",
            },
        ])
        self.assertEqual(report.query, "Levi's slim shorts sold comps")
        self.assertEqual(report.source, "Brave")
        self.assertEqual([(comp.price, comp.url) for comp in report.comps], [(22, "https://www.ebay.com/itm/123")])

    def test_priced_listing_still_for_sale_is_live_not_sold(self):
        report = comp_report("Levi's slim shorts", [{
            "title": "Levi's 511 Slim Shorts",
            "url": "https://www.ebay.com/itm/9",
            "description": "US $24.00 Buy It Now · Add to cart",
        }])
        self.assertEqual(report.comps, [])
        self.assertEqual([(comp.price, comp.marketplace) for comp in report.live], [(24, "eBay")])

    def test_empty_results_are_an_empty_report(self):
        report = comp_report("Nike tee sold comps", [])
        self.assertEqual((report.comps, report.live), ([], []))


class ResearchCompsTest(unittest.IsolatedAsyncioTestCase):
    async def test_raises_without_api_key(self):
        with patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value=None):
            with self.assertRaises(RuntimeError):
                await research_brave_report("Levi's shorts sold comps")

    async def test_searches_when_key_present(self):
        with (
            patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value="BSA-test"),
            patch("vendoo_studio.services.brave_search.search_web", new=AsyncMock(return_value=BRAVE_PAYLOAD["web"]["results"])) as search,
        ):
            report = await research_brave_report("Levi's Slim shorts sold comps")
        search.assert_awaited_once()
        self.assertEqual(search.await_args.args[0], "Levi's Slim shorts sold comps")
        self.assertEqual([comp.price for comp in report.comps], [22])

    async def test_query_list_merges_every_marketplace(self):
        per_site = {
            "ebay.com": {"url": "https://www.ebay.com/itm/1", "title": "Levi's 511 - Sold", "description": "Sold for $22."},
            "poshmark.com": {"url": "https://poshmark.com/listing/2", "title": "Levi's Shorts", "description": "Sold for $19."},
            "mercari.com": {"url": "https://www.mercari.com/us/item/m3", "title": "Levi's 511", "description": "Sold for $25."},
        }

        async def fake_search(query: str, _key: str, *, count: int = 8) -> list[dict]:
            return [item for site, item in per_site.items() if site in query]

        with (
            patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value="BSA-test"),
            patch("vendoo_studio.services.brave_search.search_web", new=fake_search),
            patch("vendoo_studio.services.brave_search.BRAVE_QUERY_STAGGER_SEC", 0),
        ):
            report = await research_brave_report(
                brave_sold_queries({"brand": "Levi's", "category": "Bottoms > Shorts"})
            )
        self.assertEqual(
            sorted((comp.price, comp.marketplace) for comp in report.comps),
            [(19, "Poshmark"), (22, "eBay"), (25, "Mercari")],
        )

    async def test_search_failure_raises(self):
        with (
            patch("vendoo_studio.services.brave_search.get_brave_api_key", return_value="BSA-test"),
            patch("vendoo_studio.services.brave_search.search_web", new=AsyncMock(side_effect=RuntimeError("Brave HTTP 401: invalid token"))),
        ):
            with self.assertRaisesRegex(RuntimeError, "401"):
                await research_brave_report("Nike Tee sold comps")


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
        self.assertEqual(captured["params"]["freshness"], "py")
        self.assertEqual(captured["params"]["result_filter"], "web")
        self.assertEqual(captured["params"]["spellcheck"], "false")
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
