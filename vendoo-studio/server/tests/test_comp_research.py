from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.services.comp_research import (
    COMPS_FAILED_NOTE,
    COMPS_SETUP_NOTE,
    COMPS_TIMEOUT_NOTE,
    ModelSearch,
    comps_search_available,
    comps_setup_note,
    model_report,
    model_search,
    research_sold_comps,
    stream_sold_comps,
)
from vendoo_studio.services.sold_comps import (
    SoldComp,
    SoldCompsReport,
    comps_confident,
    comps_usable,
    format_sold_comps,
    parse_sold_comps,
)


ANALYSIS = "Photo analysis:\n- brand: Levi's\n- style: Slim shorts"
CHATGPT_COMPS = (
    "Sold comps:\n"
    "Query: Levi's Slim shorts sold comps\n"
    "Source: ChatGPT web search\n"
    "Market: $18–$25\n"
    "\n"
    "- $22 · eBay · Good · Levi's 511 Slim Shorts\n"
    "  https://www.ebay.com/itm/1\n"
    "- $19 · Poshmark · Good · Levi's Slim Shorts\n"
    "  https://poshmark.com/listing/2\n"
    "- $25 · Mercari · Levi's 511 Shorts\n"
    "  https://www.mercari.com/item/3\n"
    "\n"
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
)
BRAVE_COMPS = (
    "Sold comps:\n"
    "Query: Levi's Slim shorts sold (site:ebay.com OR site:poshmark.com OR site:mercari.com OR site:depop.com OR site:etsy.com)\n"
    "Source: Brave Search\n"
    "Market: $22\n"
    "\n"
    "- $22 · eBay · Levi's 511 Slim Shorts - Sold\n"
    "  https://www.ebay.com/itm/123\n"
    "- $21 · Poshmark · Levi's Slim Shorts - Sold\n"
    "  https://poshmark.com/listing/124\n"
    "- $24 · Depop · Levi's 511 Shorts\n"
    "  https://www.depop.com/products/125\n"
    "\n"
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
)
THIN_BRAVE_COMPS = (
    "Sold comps:\n"
    "Query: Levi's Slim shorts sold\n"
    "Source: Brave Search\n"
    "Market: $22\n"
    "\n"
    "- $22 · eBay · Levi's 511 Slim Shorts - Sold\n"
    "  https://www.ebay.com/itm/123\n"
    "\n"
    "Only 1 sold listing found — too thin to price from. Treat it as a weak signal, "
    "lean on an estimated baseline, and note pricing uncertainty in the description."
)
EMPTY_COMPS = format_sold_comps(
    SoldCompsReport(query="Levi's Slim shorts sold comps", source="ChatGPT web search")
)


class CompUsableTest(unittest.TestCase):
    def test_requires_structured_sold_items(self):
        self.assertFalse(comps_usable(""))
        self.assertFalse(comps_usable(EMPTY_COMPS))
        self.assertFalse(comps_usable("Sold comps:\nSearch failed (timeout)."))
        self.assertFalse(comps_usable("Typical sold price $20"))
        self.assertTrue(comps_usable(CHATGPT_COMPS))

    def test_confident_needs_three_sold_listings(self):
        self.assertTrue(comps_usable(THIN_BRAVE_COMPS))
        self.assertFalse(comps_confident(THIN_BRAVE_COMPS))
        self.assertFalse(comps_confident(EMPTY_COMPS))
        self.assertTrue(comps_confident(CHATGPT_COMPS))


def listing_json(*comps: tuple[int, str, str], live: tuple[tuple[int, str, str], ...] = ()) -> str:
    def entries(items):
        return ",".join(
            f'{{"title":"Levi\'s {title}","price":{price},"url":"{url}"}}' for price, title, url in items
        )

    return f'{{"market":"","comps":[{entries(comps)}],"live":[{entries(live)}]}}'


THREE_SOLD = listing_json(
    (22, "511 Slim Shorts", "https://www.ebay.com/itm/1"),
    (19, "Slim Shorts", "https://poshmark.com/listing/2"),
    (25, "511 Shorts", "https://www.mercari.com/us/item/m3"),
)


def searcher(answer: str = "", *, error: Exception | None = None, delay: float = 0.0, calls: list | None = None):
    async def search(messages: list[dict]) -> dict:
        if calls is not None:
            calls.append(messages)
        if delay:
            await asyncio.sleep(delay)
        if error:
            raise error
        return {"answer": answer, "sources": []}

    return search


def brave_report(*comps: tuple[int, str, str]) -> SoldCompsReport:
    return SoldCompsReport(
        query="q",
        source="Brave",
        comps=[SoldComp(price=price, marketplace="eBay", title=f"Levi's {title}", url=url) for price, title, url in comps],
    )


def patched(model: ModelSearch | None, *, brave=None, brave_key: str | None = "BSA-test"):
    return (
        patch("vendoo_studio.services.comp_research.model_search", return_value=model),
        patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=brave_key),
        patch(
            "vendoo_studio.services.comp_research.research_brave_report",
            new=brave or AsyncMock(return_value=brave_report()),
        ),
    )


class CompAvailabilityTest(unittest.TestCase):
    def test_available_with_a_listing_model_or_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.model_search", return_value=None),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            self.assertFalse(comps_search_available())
        with (
            patch("vendoo_studio.services.comp_research.model_search", return_value=ModelSearch("Cursor", searcher())),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            self.assertTrue(comps_search_available())
        with (
            patch("vendoo_studio.services.comp_research.model_search", return_value=None),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            self.assertTrue(comps_search_available())

    def test_searches_with_the_listing_model_only(self):
        from vendoo_studio.providers.cursor_agent import CursorProvider

        provider = CursorProvider(api_key="cur-key")
        with patch("vendoo_studio.services.comp_research.get_listing_provider", return_value=provider):
            search = model_search()
        self.assertEqual(search.label, "Cursor")
        self.assertEqual(search.search, provider.web_search)
        with patch("vendoo_studio.services.comp_research.get_listing_provider", return_value=None):
            self.assertIsNone(model_search())


class ModelReportTest(unittest.TestCase):
    def test_reads_sold_and_live_listings(self):
        report = model_report(
            "Cursor",
            "Levi's shorts sold comps",
            listing_json(
                (22, "511 Shorts", "https://www.ebay.com/itm/1"),
                live=((30, "Slim Shorts", "https://poshmark.com/listing/9"),),
            ),
            [],
        )
        self.assertEqual(report.source, "Cursor")
        self.assertEqual([comp.price for comp in report.comps], [22])
        self.assertEqual([comp.price for comp in report.live], [30])

    def test_keeps_markdown_research_when_no_listings(self):
        text = format_sold_comps(model_report(
            "ChatGPT",
            "Sauza tee sold comps",
            "## Research note — Sauza Tequila T-shirt\n"
            "**Typical sold-price range:** **$10–$25 USD** for a standard tee.",
            [],
        ))
        self.assertIn("Market: $10–$25", text)
        self.assertIn("Typical sold-price range", text)
        self.assertFalse(comps_usable(text))

    def test_empty_json_does_not_become_the_note(self):
        text = format_sold_comps(model_report("MiMo", "Nike tee sold comps", '{"market":"","comps":[]}', []))
        self.assertIn("No sold listings found", text)
        self.assertNotIn('"comps":[]', text)


class ResearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_model_comps_skip_brave(self):
        brave = AsyncMock(return_value=brave_report())
        calls: list = []
        model = ModelSearch("ChatGPT", searcher(listing_json((22, "511 Slim Shorts", "https://www.ebay.com/itm/1")), calls=calls))
        first, second, third = patched(model, brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        brave.assert_not_awaited()
        report = parse_sold_comps(text)
        self.assertEqual(report.source, "ChatGPT")
        self.assertEqual([comp.price for comp in report.comps], [22])
        self.assertIn("Require explicit evidence that the item sold", calls[0][0]["content"])
        self.assertIn("Levi's", calls[0][1]["content"])

    async def test_no_sold_comps_falls_back_to_brave_and_keeps_live(self):
        brave = AsyncMock(return_value=brave_report((21, "Slim Shorts", "https://www.ebay.com/itm/5")))
        model = ModelSearch("Cursor", searcher(listing_json(live=((30, "Slim Shorts", "https://poshmark.com/listing/9"),))))
        first, second, third = patched(model, brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        brave.assert_awaited_once()
        self.assertIn("site:ebay.com", brave.await_args.args[0][0])
        self.assertEqual(brave.await_args.kwargs["expected_names"], ("Levi's",))
        report = parse_sold_comps(text)
        self.assertEqual(report.source, "Cursor + Brave")
        self.assertEqual([comp.price for comp in report.comps], [21])
        self.assertEqual([comp.price for comp in report.live], [30])

    async def test_failed_model_falls_back_to_brave(self):
        brave = AsyncMock(return_value=brave_report((21, "Slim Shorts", "https://www.ebay.com/itm/5")))
        first, second, third = patched(ModelSearch("MiMo", searcher(error=RuntimeError("MiMo HTTP 401"))), brave=brave)
        with first, second, third:
            events = [event async for event in stream_sold_comps(ANALYSIS)]
        states = [(event.source, event.state) for event in events if event.kind == "source"]
        self.assertEqual(states, [("MiMo", "searching"), ("MiMo", "failed"), ("Brave", "searching"), ("Brave", "done")])
        self.assertEqual(parse_sold_comps(events[-1].text).source, "Brave")

    async def test_slow_model_times_out_to_brave(self):
        brave = AsyncMock(return_value=brave_report((21, "Slim Shorts", "https://www.ebay.com/itm/5")))
        first, second, third = patched(ModelSearch("Cursor", searcher(THREE_SOLD, delay=60)), brave=brave)
        with first, second, third, patch("vendoo_studio.services.comp_research.MODEL_SEARCH_TIMEOUT_SEC", 0.05):
            events = [event async for event in stream_sold_comps(ANALYSIS)]
        self.assertIn(("Cursor", "timeout"), [(event.source, event.state) for event in events])
        brave.assert_awaited_once()
        self.assertEqual(parse_sold_comps(events[-1].text).source, "Brave")

    async def test_brave_alone_when_no_model_is_connected(self):
        brave = AsyncMock(return_value=brave_report((21, "Slim Shorts", "https://www.ebay.com/itm/5")))
        first, second, third = patched(None, brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        brave.assert_awaited_once()
        self.assertEqual(parse_sold_comps(text).source, "Brave")

    async def test_skips_when_nothing_can_search(self):
        first, second, third = patched(None, brave_key=None)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        self.assertIn(COMPS_SETUP_NOTE, text)

    async def test_overall_timeout_returns_a_note(self):
        first, second, third = patched(ModelSearch("ChatGPT", searcher(THREE_SOLD, delay=60)), brave_key=None)
        with first, second, third, patch("vendoo_studio.services.comp_research.SOLD_COMPS_TIMEOUT_SEC", 0.05):
            text = await research_sold_comps(ANALYSIS)
        self.assertIn(COMPS_TIMEOUT_NOTE, text)

    async def test_every_source_failing_returns_the_failure_note(self):
        first, second, third = patched(
            ModelSearch("ChatGPT", searcher(error=RuntimeError("ChatGPT HTTP 401"))), brave_key=None,
        )
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        self.assertIn(COMPS_FAILED_NOTE, text)
        self.assertIn("ChatGPT HTTP 401", text)

    def test_setup_note_is_parseable_sold_comps_card(self):
        text = comps_setup_note()
        self.assertTrue(text.startswith("Sold comps:"))
        self.assertIn(COMPS_SETUP_NOTE, text)
        self.assertFalse(comps_usable(text))


if __name__ == "__main__":
    unittest.main()
