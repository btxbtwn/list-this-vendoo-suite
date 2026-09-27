from __future__ import annotations

import unittest

from vendoo_studio.services.sold_comps import (
    INSTRUCTION,
    MAX_COMPS,
    SoldComp,
    SoldCompsReport,
    comps_confident,
    comps_from_model_answer,
    listings_from_web_results,
    merge_reports,
    comps_usable,
    live_ceiling,
    format_sold_comps,
    parse_sold_comps,
    research_note,
)


def sold_from_web_results(results, **kwargs):
    return listings_from_web_results(results, **kwargs)[0]


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
        comps = sold_from_web_results([LISTING, HOWTO, SEARCH_PAGE])
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].price, 22)
        self.assertEqual(comps[0].marketplace, "eBay")
        self.assertEqual(comps[0].url, LISTING["url"])
        self.assertEqual(comps[0].condition, "Good")

    def test_drops_listings_without_prices(self):
        comps = sold_from_web_results([
            {"title": "Levi's shorts", "url": "https://www.ebay.com/itm/9", "description": "Great condition"},
        ])
        self.assertEqual(comps, [])

    def test_drops_active_listing_without_sold_evidence(self):
        comps = sold_from_web_results([{
            "title": "Levi's 511 Slim Shorts",
            "url": "https://www.ebay.com/itm/9",
            "description": "$22.00 Buy It Now",
        }])
        self.assertEqual(comps, [])

    def test_drops_negative_or_retail_sold_language(self):
        for description in ("Not sold. Asking $22.", "Sold out online. Retail price $22."):
            with self.subTest(description=description):
                comps = sold_from_web_results([{
                    "title": "Levi's 511 Slim Shorts",
                    "url": "https://www.ebay.com/itm/9",
                    "description": description,
                }])
                self.assertEqual(comps, [])

    def test_ignores_was_price_and_keeps_the_remaining_sold_price(self):
        comps = sold_from_web_results([{
            "title": "Levi's 511 Slim Shorts - Sold",
            "url": "https://www.ebay.com/itm/9",
            "description": "Was $60, now $22",
        }])
        self.assertEqual([comp.price for comp in comps], [22])

    def test_drops_retail_price_copied_from_the_title(self):
        # The seller wrote the tag price into the title and the description.
        # The listing is still for sale; "items sold" is the seller's feedback.
        comps = sold_from_web_results([{
            "title": "Breckenridge Womens Blue Fleece Holiday Sweatshirt Small NWT $44 | eBay",
            "url": "https://www.ebay.com/itm/204478063754",
            "description": (
                "Breckenridge Womens Blue Fleece Holiday Sweatshirt Small NWT $44 - "
                "Features: Brand: Breckenridge. Retail: $44.00. Style: Sweatshirt."
            ),
            "extra_snippets": ["countrycorner4281 100% positive feedback • 6.3K items sold"],
        }])
        self.assertEqual(comps, [])

    def test_drops_active_listing_with_elided_seller_count_and_shipping_banner(self):
        # Brave's snippet of a live $3.99 listing: the seller card's "44K items
        # sold" is elided to "... sold", and the store banner's shipping amount
        # is the only dollar figure on it.
        comps = sold_from_web_results([{
            "title": "Womens Forever 21 red crop top sz S | eBay",
            "url": "https://www.ebay.com/itm/404418932403",
            "description": (
                "FOREVER 21 · Fit · Regular · ... sold · Joined Sep 2020 · Usually responds "
                "within 24 hours · Over 3,000 items in store with items being listed everyday!!!"
            ),
            "extra_snippets": [
                "99.4% positive feedback•44K items sold · Joined Sep 2020 · when you add 2 or more "
                "items to your checkout cart you get 50% off on all items with $15 shipping at the "
                "CHECKOUT CART!!!"
            ],
        }])
        self.assertEqual(comps, [])

    def test_shipping_and_fees_are_not_the_sold_price(self):
        for description in (
            "Sold. $15 combined shipping of up to 40 items.",
            "Item sold. Shipping: $7.99",
            "Item sold · +$4.99 Buyer Protection fee",
        ):
            with self.subTest(description=description):
                comps = sold_from_web_results([{
                    "title": "Levi's 511 Slim Shorts",
                    "url": "https://www.ebay.com/itm/9",
                    "description": description,
                }])
                self.assertEqual(comps, [])

    def test_keeps_sold_price_listed_beside_shipping(self):
        comps = sold_from_web_results([{
            "title": "Levi's 511 Slim Shorts",
            "url": "https://www.ebay.com/itm/9",
            "description": "Sold for $22.00 · Shipping: $7.99",
        }])
        self.assertEqual([comp.price for comp in comps], [22])

    def test_keeps_selling_price_when_retail_is_also_listed(self):
        comps = sold_from_web_results([{
            "title": "Breckenridge Womens Blue Fleece Holiday Sweatshirt Small NWT $44",
            "url": "https://www.ebay.com/itm/204478063754",
            "description": "Sold. US $18.00. Retail: $44.00. 6.3K items sold.",
        }])
        self.assertEqual([comp.price for comp in comps], [18])

    def test_keeps_explicit_sold_price_when_other_prices_exist(self):
        comps = sold_from_web_results([{
            "title": "Levi's 511 Slim Shorts - Sold",
            "url": "https://www.ebay.com/itm/9",
            "description": "Originally $60. Sold for $22.",
        }])
        self.assertEqual([comp.price for comp in comps], [22])

    def test_drops_foreign_dollar_prices(self):
        for description in (
            "Sold for HK$1990.",
            "NT$1990 · Sold",
            "Sold for AU $19.90.",
            "Sold for CAD $40.",
        ):
            with self.subTest(description=description):
                comps = sold_from_web_results([{
                    "title": "Levi's 511 Slim Shorts - Sold",
                    "url": "https://www.ebay.com/itm/9",
                    "description": description,
                }])
                self.assertEqual(comps, [])

    def test_reads_us_dollar_and_thousands_prices(self):
        for description, price in (
            ("Sold for US $19.90, great shape.", 19.9),
            ("Sold for US$22.", 22),
            ("Sold for $1,250.", 1250),
        ):
            with self.subTest(description=description):
                comps = sold_from_web_results([{
                    "title": "Levi's 511 Slim Shorts - Sold",
                    "url": "https://www.ebay.com/itm/9",
                    "description": description,
                }])
                self.assertEqual([comp.price for comp in comps], [price])

    def test_drops_wrong_brand(self):
        comps = sold_from_web_results([{
            "title": "Wrangler Slim Shorts - Sold",
            "url": "https://www.ebay.com/itm/9",
            "description": "Sold for $22.",
        }], expected_names=("Levi's",))
        self.assertEqual(comps, [])


    def test_keeps_character_titled_listings_without_the_brand(self):
        names = ("Peanuts", "Snoopy and Woodstock")
        kept = sold_from_web_results([{
            "title": "Snoopy Woodstock Women's XS Gray Tee",
            "url": "https://www.ebay.com/itm/10",
            "description": "Sold for $14.",
        }], expected_names=names)
        self.assertEqual([comp.price for comp in kept], [14])
        dropped = sold_from_web_results([{
            "title": "Woodstock 1969 Festival Tee",
            "url": "https://www.ebay.com/itm/11",
            "description": "Sold for $30.",
        }], expected_names=names)
        self.assertEqual(dropped, [])

class ModelAnswerParseTest(unittest.TestCase):
    def test_reads_json_comps(self):
        answer = """```json
{"market":"$18-$25","comps":[
  {"title":"Levi's 511 Slim Shorts","price":22,"marketplace":"eBay","condition":"Good","url":"https://www.ebay.com/itm/1"}
]}
```"""
        market, comps, _live = comps_from_model_answer(answer, [])
        self.assertEqual(market, "$18–$25")
        self.assertEqual(comps[0].price, 22)
        self.assertEqual(comps[0].url, "https://www.ebay.com/itm/1")

    def test_reads_markdown_list_when_json_missing(self):
        answer = (
            "Typical range $18-$25.\n"
            "1. $18 Poshmark Levi's slim shorts Good\n"
            "   https://poshmark.com/listing/abc\n"
        )
        market, comps, _live = comps_from_model_answer(answer, [])
        self.assertEqual(market, "$18–$25")
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].title, "Levi's slim shorts")

    def test_merges_listing_sources_and_drops_guides(self):
        answer = '{"market":"","comps":[]}'
        market, comps, _live = comps_from_model_answer(answer, [LISTING, HOWTO])
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].price, 22)
        self.assertEqual(market, "$22")

    def test_does_not_invent_comps_from_a_price_mention(self):
        market, comps, _live = comps_from_model_answer("Typical sold price $20 on eBay.", [])
        self.assertEqual(comps, [])
        self.assertEqual(market, "")

    def test_drops_model_comp_without_listing_url(self):
        answer = '{"market":"$20-$25","comps":[{"title":"Levi shorts","price":22,"marketplace":"eBay"}]}'
        _market, comps, _live = comps_from_model_answer(answer, [])
        self.assertEqual(comps, [])

    def test_listing_url_is_authoritative_for_marketplace(self):
        answer = (
            '{"market":"$22","comps":[{"title":"Levi shorts","price":22,'
            '"marketplace":"Etsy","url":"https://www.ebay.com/itm/1"}]}'
        )
        _market, comps, _live = comps_from_model_answer(answer, [])
        self.assertEqual(comps[0].marketplace, "eBay")


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
        comps = sold_from_web_results(results)
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


class LiveListingTest(unittest.TestCase):
    def test_priced_active_listing_is_live(self):
        sold, live = listings_from_web_results([{
            "title": "Levi's 511 Slim Shorts",
            "url": "https://www.ebay.com/itm/9",
            "description": "US $24.00 · Buy It Now · Free shipping",
        }])
        self.assertEqual(sold, [])
        self.assertEqual([(comp.price, comp.url) for comp in live], [(24, "https://www.ebay.com/itm/9")])

    def test_active_listing_without_one_clear_price_is_dropped(self):
        sold, live = listings_from_web_results([{
            "title": "Levi's 511 Slim Shorts",
            "url": "https://www.ebay.com/itm/9",
            "description": "$24.00 or Best Offer · was $40 · 2 for $30",
        }])
        self.assertEqual((sold, live), ([], []))

    def test_model_live_entries_never_include_a_sold_url(self):
        answer = (
            '{"comps":[{"title":"Levi\'s 511","price":22,"url":"https://www.ebay.com/itm/1"}],'
            '"live":[{"title":"Levi\'s 511","price":30,"url":"https://www.ebay.com/itm/1"},'
            '{"title":"Levi\'s Slim","price":28,"url":"https://poshmark.com/listing/2"}]}'
        )
        _market, comps, live = comps_from_model_answer(answer, [])
        self.assertEqual([comp.url for comp in comps], ["https://www.ebay.com/itm/1"])
        self.assertEqual([comp.url for comp in live], ["https://poshmark.com/listing/2"])

    def test_merge_dedupes_across_sources(self):
        shared = SoldComp(price=22, marketplace="eBay", title="Levi's 511", url="https://www.ebay.com/itm/1")
        merged = merge_reports("q", [
            SoldCompsReport(query="q", source="ChatGPT", comps=[shared]),
            SoldCompsReport(
                query="q",
                source="Cursor",
                comps=[shared, SoldComp(price=19, marketplace="Poshmark", title="Levi's", url="https://poshmark.com/listing/2")],
                live=[SoldComp(price=30, marketplace="eBay", title="Levi's 511", url="https://www.ebay.com/itm/1")],
            ),
        ])
        self.assertEqual(merged.source, "ChatGPT + Cursor")
        self.assertEqual([comp.price for comp in merged.comps], [22, 19])
        self.assertEqual(merged.live, [])
        self.assertEqual(merged.market, "$19–$22")

    def test_live_listings_round_trip_and_do_not_count_as_comps(self):
        text = format_sold_comps(SoldCompsReport(
            query="q",
            source="Brave",
            live=[SoldComp(price=4, marketplace="eBay", title="Forever 21 crop top", url="https://www.ebay.com/itm/9")],
        ))
        self.assertIn("No sold listings found", text)
        self.assertIn("asking prices, not sales", text)
        # One asking price is a hope, not a market: no ceiling.
        self.assertNotIn("Live asking median", text)
        report = parse_sold_comps(text)
        self.assertEqual(report.comps, [])
        self.assertEqual([(comp.price, comp.url) for comp in report.live], [(4, "https://www.ebay.com/itm/9")])
        self.assertFalse(comps_usable(text))
        self.assertIn("No sold listings found", report.note)

    def test_three_live_listings_state_a_ceiling_that_round_trips(self):
        live = [
            SoldComp(price=12, marketplace="Poshmark", title="Paper Crane crop top", url="https://poshmark.com/listing/1"),
            SoldComp(price=23, marketplace="Poshmark", title="Paper Crane bustier", url="https://poshmark.com/listing/2"),
            SoldComp(price=3, marketplace="Depop", title="Paper Crane crop", url="https://www.depop.com/products/3"),
        ]
        comps = [SoldComp(price=12, marketplace="Poshmark", title="Paper Crane smocked top", url="https://poshmark.com/listing/4")]
        text = format_sold_comps(SoldCompsReport(query="q", source="Cursor", comps=comps, live=live))
        self.assertIn("Live asking median $12 — list at or below it", text)
        report = parse_sold_comps(text)
        self.assertEqual(len(report.live), 3)
        self.assertEqual(len(report.comps), 1)
        self.assertEqual(live_ceiling(report), 12.0)

    def test_blocks_with_the_old_live_header_still_parse(self):
        text = (
            "Sold comps:\n"
            "Query: q\n"
            "Source: Brave\n"
            "No sold listings found.\n"
            "\n"
            "Live listings (for sale now — asking prices, not sales; do not price from these):\n"
            "- $4 · eBay · Forever 21 crop top\n"
            "  https://www.ebay.com/itm/9\n"
        )
        report = parse_sold_comps(text)
        self.assertEqual(report.comps, [])
        self.assertEqual([comp.price for comp in report.live], [4])


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
