from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.services.comp_research import (
    comps_search_available,
    comps_usable,
    format_chatgpt_comps,
    research_sold_comps,
)
from vendoo_studio.services.sold_comps import SoldCompsReport, format_sold_comps


ANALYSIS = "Photo analysis:\n- brand: Levi's\n- style: Slim shorts"
CHATGPT_COMPS = (
    "Sold comps:\n"
    "Query: Levi's Slim shorts sold comps\n"
    "Source: ChatGPT web search\n"
    "Market: $18–$25\n"
    "\n"
    "- $22 · eBay · Good · Levi's 511 Slim Shorts\n"
    "  https://www.ebay.com/itm/1\n"
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
    "\n"
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
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


class CompAvailabilityTest(unittest.TestCase):
    def test_available_when_chatgpt_or_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            self.assertFalse(comps_search_available())
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            self.assertTrue(comps_search_available())
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            self.assertTrue(comps_search_available())


class FormatChatGPTCompsTest(unittest.TestCase):
    def test_includes_answer_and_sources(self):
        text = format_chatgpt_comps(
            "Levi's shorts sold comps",
            '{"market":"$18-$25","comps":[{"title":"eBay sold listing","price":22,"marketplace":"eBay","url":"https://www.ebay.com/itm/1"}]}',
            [],
        )
        self.assertIn("Source: ChatGPT web search", text)
        self.assertIn("$22 · eBay", text)
        self.assertIn("https://www.ebay.com/itm/1", text)

    def test_keeps_markdown_research_when_no_listings(self):
        text = format_chatgpt_comps(
            "Sauza tee sold comps",
            "## Research note — Sauza Tequila T-shirt\n"
            "**Typical sold-price range:** **$10–$25 USD** for a standard tee.",
            [],
        )
        self.assertIn("Source: ChatGPT web search", text)
        self.assertIn("Market: $10–$25", text)
        self.assertIn("Typical sold-price range", text)
        self.assertNotIn("No sold listings found", text)
        self.assertFalse(comps_usable(text))

    def test_empty_json_does_not_become_the_note(self):
        text = format_chatgpt_comps("Nike tee sold comps", '{"market":"","comps":[]}', [])
        self.assertIn("No sold listings found", text)
        self.assertNotIn('"comps":[]', text)


class ResearchFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_chatgpt_success_wins_over_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=AsyncMock(return_value=CHATGPT_COMPS)) as chatgpt,
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=AsyncMock(return_value=BRAVE_COMPS)) as brave,
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        chatgpt.assert_awaited_once()
        self.assertIn("Source: ChatGPT web search", text)

    async def test_chatgpt_failure_uses_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=AsyncMock(side_effect=RuntimeError("ChatGPT HTTP 400"))),
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=AsyncMock(return_value=BRAVE_COMPS)) as brave,
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        brave.assert_awaited_once()
        self.assertIn("site:ebay.com", brave.await_args.args[0])
        self.assertIn("Source: Brave Search", text)

    async def test_thin_chatgpt_result_uses_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch(
                "vendoo_studio.services.comp_research.research_chatgpt_comps",
                new=AsyncMock(return_value=EMPTY_COMPS),
            ),
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=AsyncMock(return_value=BRAVE_COMPS)),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        self.assertIn("Source: Brave Search", text)

    async def test_unusable_brave_keeps_chatgpt_note(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=AsyncMock(return_value=EMPTY_COMPS)),
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=AsyncMock(return_value=EMPTY_COMPS.replace("ChatGPT web search", "Brave Search"))),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        self.assertIn("Source: ChatGPT web search", text)
        self.assertFalse(comps_usable(text))

    async def test_searches_run_concurrently(self):
        import asyncio

        started: list[str] = []
        both_started = asyncio.Event()

        async def chatgpt(_query: str) -> str:
            started.append("chatgpt")
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 1)
            return CHATGPT_COMPS

        async def brave(_query: str) -> str:
            started.append("brave")
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 1)
            return BRAVE_COMPS

        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=chatgpt),
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=brave),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        self.assertEqual(sorted(started), ["brave", "chatgpt"])
        self.assertIn("Source: ChatGPT web search", text)

    async def test_slow_chatgpt_falls_back_to_brave_after_grace(self):
        import asyncio

        async def slow_chatgpt(_query: str) -> str:
            await asyncio.sleep(60)
            return CHATGPT_COMPS

        with (
            patch("vendoo_studio.services.comp_research.CHATGPT_GRACE_SEC", 0.05),
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=slow_chatgpt),
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=AsyncMock(return_value=BRAVE_COMPS)),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        self.assertIn("Source: Brave Search", text)

    async def test_skips_when_no_search_provider(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            text = await research_sold_comps(ANALYSIS)
        self.assertEqual(text, "")

    async def test_timeout_returns_empty_instead_of_hanging(self):
        import asyncio

        async def hang(_query: str) -> str:
            await asyncio.sleep(60)
            return CHATGPT_COMPS

        with (
            patch("vendoo_studio.services.comp_research.SOLD_COMPS_TIMEOUT_SEC", 0.05),
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=hang),
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value=None),
        ):
            text = await research_sold_comps(ANALYSIS)
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
