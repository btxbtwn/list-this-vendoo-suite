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
    model_searches,
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


def patched(models: list[ModelSearch], *, brave=None, brave_key: str | None = "BSA-test"):
    return (
        patch("vendoo_studio.services.comp_research.model_searches", return_value=models),
        patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=brave_key),
        patch(
            "vendoo_studio.services.comp_research.research_brave_report",
            new=brave or AsyncMock(return_value=brave_report()),
        ),
    )


class CompAvailabilityTest(unittest.TestCase):
    def test_available_with_any_model_or_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.model_searches", return_value=[]),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            self.assertFalse(comps_search_available())
        with (
            patch("vendoo_studio.services.comp_research.model_searches", return_value=[ModelSearch("Cursor", searcher())]),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            self.assertTrue(comps_search_available())
        with (
            patch("vendoo_studio.services.comp_research.model_searches", return_value=[]),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            self.assertTrue(comps_search_available())

    def test_lists_every_connected_model(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.get_cursor_api_key", return_value="cur-key"),
            patch("vendoo_studio.services.comp_research.get_api_key", return_value="mimo-key"),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={"listing_model": "gpt-5.5"}),
        ):
            labels = [search.label for search in model_searches()]
        self.assertEqual(labels, ["ChatGPT", "Cursor", "MiMo"])


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
    async def test_merges_every_model_and_skips_brave_when_confident(self):
        brave = AsyncMock(return_value=brave_report())
        chatgpt_calls: list = []
        models = [
            ModelSearch("ChatGPT", searcher(listing_json(
                (22, "511 Slim Shorts", "https://www.ebay.com/itm/1"),
                (19, "Slim Shorts", "https://poshmark.com/listing/2"),
            ), calls=chatgpt_calls, delay=0.05)),
            ModelSearch("Cursor", searcher(listing_json(
                (22, "511 Slim Shorts", "https://www.ebay.com/itm/1"),
                (25, "511 Shorts", "https://www.mercari.com/us/item/m3"),
            ))),
        ]
        first, second, third = patched(models, brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        report = parse_sold_comps(text)
        self.assertEqual(sorted(comp.price for comp in report.comps), [19, 22, 25])
        self.assertEqual(report.source, "ChatGPT + Cursor")
        brave.assert_not_awaited()
        self.assertIn("Require explicit evidence that the item sold", chatgpt_calls[0][0]["content"])
        self.assertIn("Levi's", chatgpt_calls[0][1]["content"])

    async def test_brave_fills_in_when_models_are_thin(self):
        brave = AsyncMock(return_value=brave_report(
            (21, "Slim Shorts", "https://www.ebay.com/itm/5"),
            (24, "511 Shorts", "https://www.ebay.com/itm/6"),
        ))
        models = [ModelSearch("MiMo", searcher(listing_json((22, "511 Shorts", "https://www.ebay.com/itm/1"))))]
        first, second, third = patched(models, brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        brave.assert_awaited_once()
        self.assertIn("site:ebay.com", brave.await_args.args[0][0])
        self.assertEqual(brave.await_args.kwargs["expected_names"], ("Levi's",))
        report = parse_sold_comps(text)
        self.assertEqual(report.source, "MiMo + Brave")
        self.assertEqual(len(report.comps), 3)
        self.assertTrue(comps_confident(text))

    async def test_failed_models_fall_back_to_brave(self):
        brave = AsyncMock(return_value=brave_report(
            (21, "Slim Shorts", "https://www.ebay.com/itm/5"),
        ))
        models = [ModelSearch("ChatGPT", searcher(error=RuntimeError("ChatGPT HTTP 400")))]
        first, second, third = patched(models, brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        self.assertEqual(parse_sold_comps(text).source, "Brave")
        self.assertTrue(comps_usable(text))

    async def test_brave_alone_when_no_model_is_connected(self):
        brave = AsyncMock(return_value=brave_report((21, "Slim Shorts", "https://www.ebay.com/itm/5")))
        first, second, third = patched([], brave=brave)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        brave.assert_awaited_once()
        self.assertEqual(parse_sold_comps(text).source, "Brave")

    async def test_models_run_concurrently(self):
        started: list[str] = []
        both = asyncio.Event()

        def tracked(label: str):
            async def search(_messages: list[dict]) -> dict:
                started.append(label)
                if len(started) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 1)
                return {"answer": THREE_SOLD, "sources": []}

            return search

        first, second, third = patched([ModelSearch("ChatGPT", tracked("ChatGPT")), ModelSearch("Cursor", tracked("Cursor"))])
        with first, second, third:
            await research_sold_comps(ANALYSIS)
        self.assertEqual(sorted(started), ["ChatGPT", "Cursor"])

    async def test_slow_model_is_cut_off_and_the_rest_are_kept(self):
        models = [
            ModelSearch("ChatGPT", searcher(THREE_SOLD)),
            ModelSearch("Cursor", searcher(THREE_SOLD, delay=60)),
        ]
        first, second, third = patched(models)
        with first, second, third, patch("vendoo_studio.services.comp_research.MODEL_SEARCH_TIMEOUT_SEC", 0.1):
            events = [event async for event in stream_sold_comps(ANALYSIS)]
        states = {(event.source, event.state) for event in events if event.kind == "source"}
        self.assertIn(("Cursor", "timeout"), states)
        self.assertIn(("ChatGPT", "done"), states)
        self.assertEqual(parse_sold_comps(events[-1].text).source, "ChatGPT")

    async def test_streams_each_source_then_the_merged_report(self):
        first, second, third = patched([ModelSearch("MiMo", searcher(THREE_SOLD))])
        with first, second, third:
            events = [event async for event in stream_sold_comps(ANALYSIS)]
        kinds = [(event.kind, event.source, event.state) for event in events]
        self.assertEqual(kinds[0], ("source", "MiMo", "searching"))
        self.assertIn(("source", "MiMo", "done"), kinds)
        self.assertEqual(events[-1].kind, "done")
        self.assertTrue(comps_confident(events[-1].text))

    async def test_skips_when_nothing_can_search(self):
        first, second, third = patched([], brave_key=None)
        with first, second, third:
            text = await research_sold_comps(ANALYSIS)
        self.assertIn(COMPS_SETUP_NOTE, text)

    async def test_overall_timeout_returns_a_note(self):
        first, second, third = patched([ModelSearch("ChatGPT", searcher(THREE_SOLD, delay=60))], brave_key=None)
        with first, second, third, patch("vendoo_studio.services.comp_research.SOLD_COMPS_TIMEOUT_SEC", 0.05):
            text = await research_sold_comps(ANALYSIS)
        self.assertIn(COMPS_TIMEOUT_NOTE, text)

    async def test_every_source_failing_returns_the_failure_note(self):
        first, second, third = patched(
            [ModelSearch("ChatGPT", searcher(error=RuntimeError("ChatGPT HTTP 401")))], brave_key=None,
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
