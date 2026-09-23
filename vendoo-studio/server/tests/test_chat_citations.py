import json
from urllib.parse import quote, urlencode

from vendoo_studio.services.chat_citations import (
    citations_to_plain_text,
    expand_citations_for_provider,
    parse_citation_href,
)


def href(message_id="m1", text="The lining is silk.", start=20, end=39, comment=None):
    query = {"text": text, "start": start, "end": end, "prefix": "", "suffix": ""}
    if comment is not None:
        query["comment"] = comment
    return f"studio-citation://v1/{quote(message_id, safe='')}?{urlencode(query)}"


def link(**kwargs):
    return f"[Quoted text]({href(**kwargs)})"


class TestParseCitationHref:
    def test_reads_a_quote(self):
        citation = parse_citation_href(href())
        assert citation is not None
        assert citation.message_id == "m1"
        assert citation.text == "The lining is silk."
        assert citation.comment is None

    def test_reads_a_message_id_with_a_slash(self):
        citation = parse_citation_href(href(message_id="msg 1/2"))
        assert citation is not None and citation.message_id == "msg 1/2"

    def test_rejects_other_hrefs(self):
        assert parse_citation_href("https://example.com") is None
        assert parse_citation_href("studio-citation://v2/m1?text=hi&start=0&end=2&prefix=&suffix=") is None
        assert parse_citation_href("studio-citation://v1/m1?text=hi") is None

    def test_rejects_an_empty_quote_or_backwards_range(self):
        assert parse_citation_href(href(text="   ")) is None
        assert parse_citation_href(href(start=39, end=20)) is None


class TestExpandCitationsForProvider:
    def test_leaves_a_message_without_quotes_alone(self):
        assert expand_citations_for_provider("Change the title") == "Change the title"

    def test_replaces_each_quote_with_an_id_and_appends_the_data(self):
        prompt = f"{link()}\n\nFix this."
        expanded = expand_citations_for_provider(prompt)
        assert expanded.startswith("[quote-1]\n\nFix this.\n\n<quoted_text>")
        block = expanded.split("<quoted_text>\n", 1)[1].rsplit("\n</quoted_text>", 1)[0]
        data = json.loads(block.split("\n", 1)[1])
        assert data == [{"id": "quote-1", "citation": {"message_id": "m1", "text": "The lining is silk."}}]

    def test_reuses_one_id_for_a_repeated_quote(self):
        expanded = expand_citations_for_provider(f"{link()} and again {link()}")
        assert expanded.count("[quote-1]") == 2
        assert "quote-2" not in expanded

    def test_carries_the_comment_and_says_it_is_the_seller_s(self):
        expanded = expand_citations_for_provider(f"{link(comment='wrong fibre')}\n\nFix.")
        assert '"comment": "wrong fibre"' in expanded
        assert "seller's request or remark" in expanded

    def test_escapes_angle_brackets_in_the_data(self):
        expanded = expand_citations_for_provider(link(text="<script>"))
        assert "<script>" not in expanded
        assert "\\u003cscript\\u003e" in expanded


class TestCitationsToPlainText:
    def test_replaces_the_link_with_the_quote(self):
        assert citations_to_plain_text(f"{link()}\n\nFix this.") == "The lining is silk.\n\nFix this."

    def test_keeps_the_comment_beside_the_quote(self):
        assert citations_to_plain_text(link(comment="wrong fibre")) == (
            "The lining is silk.\nComment: wrong fibre"
        )
