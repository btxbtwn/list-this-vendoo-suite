from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.services.comp_research import (
    comps_search_available,
    comps_usable,
    format_chatgpt_comps,
    research_sold_comps,
)


ANALYSIS = "Photo analysis:\n- brand: Levi's\n- style: Slim shorts"
CHATGPT_COMPS = (
    "Sold comps:\n"
    "Query: Levi's Slim shorts sold comps\n"
    "Source: ChatGPT web search\n"
    "Sold recently for $18-$25 on eBay.\n"
    "https://www.ebay.com/itm/1\n"
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
)
BRAVE_COMPS = (
    "Sold comps:\n"
    "Query: Levi's Slim shorts sold comps\n"
    "Source: Brave Search\n"
    "- Levi's 511 Slim Shorts - Sold\n"
    "  Sold for $22.\n"
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
)


class CompUsableTest(unittest.TestCase):
    def test_requires_price_or_url(self):
        self.assertFalse(comps_usable(""))
        self.assertFalse(comps_usable("Sold comps:\nNo sold listings found."))
        self.assertFalse(comps_usable("Sold comps:\nSearch failed (timeout)."))
        self.assertTrue(comps_usable(CHATGPT_COMPS))
        self.assertTrue(comps_usable("Typical sold price $20"))


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
            "Sold $18-$25.",
            [{"title": "eBay sold listing", "url": "https://www.ebay.com/itm/1"}],
        )
        self.assertIn("Source: ChatGPT web search", text)
        self.assertIn("Sold $18-$25.", text)
        self.assertIn("https://www.ebay.com/itm/1", text)


class ResearchFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_chatgpt_success_skips_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.comp_research.research_chatgpt_comps", new=AsyncMock(return_value=CHATGPT_COMPS)) as chatgpt,
            patch("vendoo_studio.services.comp_research.research_brave_comps", new=AsyncMock(return_value=BRAVE_COMPS)) as brave,
            patch("vendoo_studio.services.comp_research.get_brave_api_key", return_value="BSA-test"),
        ):
            text = await research_sold_comps(ANALYSIS)
        chatgpt.assert_awaited_once()
        brave.assert_not_awaited()
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
        self.assertIn("Source: Brave Search", text)

    async def test_thin_chatgpt_result_uses_brave(self):
        with (
            patch("vendoo_studio.services.comp_research.chatgpt_signed_in", return_value=True),
            patch(
                "vendoo_studio.services.comp_research.research_chatgpt_comps",
                new=AsyncMock(return_value="Sold comps:\nNo sold listings found."),
            ),
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


if __name__ == "__main__":
    unittest.main()
