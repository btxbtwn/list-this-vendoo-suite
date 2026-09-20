from __future__ import annotations

import unittest

from vendoo_studio.services.sold_comps import (
    INSTRUCTION,
    MAX_COMPS,
    SoldComp,
    SoldCompsReport,
    comps_confident,
    comps_from_chatgpt,
    comps_from_web_results,
    comps_usable,
    format_sold_comps,
    parse_sold_comps,
    research_note,
)


LISTING = {
    "title": "Levi's 511 Slim Shorts - Sold",
    "url": "https://www.ebay.com/itm/123",
    "description": "Sold for $22. Similar Levi's shorts.",
    "extra_snippets": ["Condition: Good"],
}

HOWTO = {
    "title": "How to find sold comps on eBay",
    "url": "https://www.terapeak.com/blog/sold-comps-guide",
    "description": "Learn how to search sold listings for $20.",
}

SEARCH_PAGE = {
    "title": "Levi's slim shorts",
    "url": "https://www.ebay.com/sch/i.html?_nkw=levis+shorts",
    "description": "Shop Levi's shorts sold for $18.",
}


class WebResultFilterTest(unittest.TestCase):
    def test_keeps_listing_urls_with_sold_prices(self):
        comps = comps_from_web_results([LISTING, HOWTO, SEARCH_PAGE])
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].price, 22)
        self.assertEqual(comps[0].marketplace, "eBay")
        self.assertEqual(comps[0].url, LISTING["url"])
        self.assertEqual(comps[0].condition, "Good")

    def test_drops_listings_without_prices(self):
        comps = comps_from_web_results([
            {"title": "Levi's shorts", "url": "https://www.ebay.com/itm/9", "description": "Great condition"},
        ])
        self.assertEqual(comps, [])


class ChatGPTParseTest(unittest.TestCase):
    def test_reads_json_comps(self):
        answer = """```json
{"market":"$18-$25","comps":[
  {"title":"Levi's 511 Slim Shorts","price":22,"marketplace":"eBay","condition":"Good","url":"https://www.ebay.com/itm/1"}
]}
```"""
        market, comps = comps_from_chatgpt(answer, [])
        self.assertEqual(market, "$18–$25")
        self.assertEqual(comps[0].price, 22)
        self.assertEqual(comps[0].url, "https://www.ebay.com/itm/1")

    def test_reads_markdown_list_when_json_missing(self):
        answer = (
            "Typical range $18-$25.\n"
            "1. $18 Poshmark Levi's slim shorts Good\n"
            "   https://poshmark.com/listing/abc\n"
        )
        market, comps = comps_from_chatgpt(answer, [])
        self.assertEqual(market, "$18–$25")
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].title, "Levi's slim shorts")

    def test_merges_listing_sources_and_drops_guides(self):
        answer = '{"market":"","comps":[]}'
        market, comps = comps_from_chatgpt(answer, [LISTING, HOWTO])
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].price, 22)
        self.assertEqual(market, "$22")

    def test_does_not_invent_comps_from_a_price_mention(self):
        market, comps = comps_from_chatgpt("Typical sold price $20 on eBay.", [])
        self.assertEqual(comps, [])
        self.assertEqual(market, "")


class FormatParseTest(unittest.TestCase):
    def test_round_trip(self):
        report = SoldCompsReport(
            query="Levi's slim shorts sold comps",
            source="ChatGPT web search",
            market="$18–$25",
            comps=[
                SoldComp(22, "eBay", "Levi's 511 Slim Shorts", "https://www.ebay.com/itm/123", "Good"),
                SoldComp(18, "Poshmark", "Levi's shorts 33", "https://poshmark.com/listing/abc"),
            ],
        )
        text = format_sold_comps(report)
        parsed = parse_sold_comps(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.query, report.query)
        self.assertEqual(parsed.market, "$18–$25")
        self.assertEqual(len(parsed.comps), 2)
        self.assertEqual(parsed.comps[0].url, report.comps[0].url)
        self.assertEqual(parsed.comps[1].marketplace, "Poshmark")
        self.assertTrue(comps_usable(text))

    def test_keeps_and_prints_up_to_max_comps(self):
        results = [
            {
                "url": f"https://www.ebay.com/itm/{index}",
                "title": f"Levi's 511 Slim Shorts {index}",
                "description": f"Sold for ${20 + index}.",
            }
            for index in range(MAX_COMPS + 6)
        ]
        comps = comps_from_web_results(results)
        self.assertEqual(len(comps), MAX_COMPS)
        text = format_sold_comps(SoldCompsReport(query="q", source="Brave Search", comps=comps))
        parsed = parse_sold_comps(text)
        self.assertEqual(len(parsed.comps), MAX_COMPS)

    def test_thin_report_warns_instead_of_pricing_from_it(self):
        report = SoldCompsReport(
            query="Levi's slim shorts sold comps",
            source="Brave Search",
            comps=[SoldComp(22, "eBay", "Levi's 511 Slim Shorts", "https://www.ebay.com/itm/123")],
        )
        text = format_sold_comps(report)
        self.assertIn("Only 1 sold listing found", text)
        self.assertNotIn(INSTRUCTION, text)
        self.assertTrue(comps_usable(text))
        self.assertFalse(comps_confident(text))
        parsed = parse_sold_comps(text)
        self.assertEqual(len(parsed.comps), 1)
        self.assertEqual(parsed.note, "")

    def test_three_comps_keep_the_pricing_instruction(self):
        report = SoldCompsReport(
            query="Levi's slim shorts sold comps",
            source="Brave Search",
            comps=[
                SoldComp(22, "eBay", "Levi's 511 Slim Shorts", "https://www.ebay.com/itm/1"),
                SoldComp(18, "Poshmark", "Levi's shorts 33", "https://poshmark.com/listing/2"),
                SoldComp(25, "Mercari", "Levi's 511 Shorts", "https://www.mercari.com/item/3"),
            ],
        )
        text = format_sold_comps(report)
        self.assertIn(INSTRUCTION, text)
        self.assertTrue(comps_confident(text))

    def test_empty_report_is_not_usable(self):
        text = format_sold_comps(SoldCompsReport(query="Nike tee sold comps", source="Brave Search"))
        self.assertIn("No sold listings found", text)
        self.assertFalse(comps_usable(text))
        self.assertFalse(comps_usable("Typical sold price $20"))

    def test_keeps_research_note_and_market_without_listings(self):
        text = format_sold_comps(
            SoldCompsReport(
                query="Sauza tee sold comps",
                source="ChatGPT web search",
                market="$10–$25",
                note=(
                    "## Research note — Sauza Tequila T-shirt\n"
                    "**Typical sold-price range:** **$10–$25 USD** for a standard tee."
                ),
            )
        )
        parsed = parse_sold_comps(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.market, "$10–$25")
        self.assertIn("Typical sold-price range", parsed.note)
        self.assertFalse(parsed.comps)
        self.assertFalse(comps_usable(text))


class ResearchNoteTest(unittest.TestCase):
    def test_keeps_markdown_prose(self):
        note = research_note(
            "## Research note — Sauza Tequila T-shirt\n"
            "**Typical sold-price range:** **$10–$25 USD** for a standard tee."
        )
        self.assertIn("Typical sold-price range", note)
        self.assertIn("## Research note", note)

    def test_drops_json_only_payloads(self):
        self.assertEqual(research_note('{"market":"","comps":[]}'), "")
        self.assertEqual(research_note('```json\n{"market":"$18-$25","comps":[]}\n```'), "")

    def test_keeps_prose_around_json(self):
        note = research_note(
            "Typical sold-price range $10-$25.\n"
            '```json\n{"market":"$10-$25","comps":[]}\n```'
        )
        self.assertIn("Typical sold-price range $10-$25.", note)
        self.assertNotIn("```", note)
