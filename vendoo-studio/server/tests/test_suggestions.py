"""Ranked inventory suggestions from local listing state."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, load_models
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.suggestions import list_suggestions


NOW = datetime(2026, 9, 20, tzinfo=UTC)


class SuggestionsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        load_models()
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.convs = ConversationRepo(self.db)
        self.listings = ListingRepo(self.db)

    def tearDown(self):
        self.db.close()

    def _kinds(self) -> list[str]:
        return [card["kind"] for card in list_suggestions(self.db, now=NOW)]

    def _by_title(self, title: str) -> dict:
        cards = {card["title"]: card for card in list_suggestions(self.db, now=NOW)}
        self.assertIn(title, cards)
        return cards[title]

    def test_skips_sold_and_settled(self):
        sold = self.convs.create(title="Sold tee")
        self.convs.update_status(sold.id, "sold")
        settled = self.convs.create(title="Settled draft")
        self.convs.add_photo(settled.id, "a.jpg", "a.jpg", "image/jpeg", 12)
        self.convs.settle(settled.id)
        self.assertEqual(self._kinds(), [])

    def test_failed_ranks_above_generate(self):
        failed = self.convs.create(title="Failed send")
        self.convs.update_status(failed.id, "failed")
        draft = self.convs.create(title="Needs generate")
        self.convs.add_photo(draft.id, "a.jpg", "a.jpg", "image/jpeg", 12)
        kinds = self._kinds()
        self.assertEqual(kinds[0], "failed")
        self.assertIn("ready_to_generate", kinds)

    def test_photos_without_revision_are_ready_to_generate(self):
        conv = self.convs.create(title="New photos")
        self.convs.add_photo(conv.id, "a.jpg", "a.jpg", "image/jpeg", 12)
        card = self._by_title("New photos")
        self.assertEqual(card["kind"], "ready_to_generate")
        self.assertTrue(card["cover_photo_url"].startswith("/api/photos/"))
        self.assertEqual(card["action"], "open")

    def test_validation_error_beats_stale(self):
        conv = self.convs.create(title="Broken active")
        conv.notes = json.dumps({
            "vendooMarketplaces": ["ebay"],
            "vendooDates": {"listed": "2026-01-01T00:00:00Z"},
        })
        self.db.commit()
        self.convs.update_status(conv.id, "active")
        self.listings.save_revision(conv.id, {"title": "Broken active", "price": 20}, "test")
        listing = self.listings.get_current(conv.id)
        listing.validation_status = "error"
        self.db.commit()
        self.assertEqual(self._by_title("Broken active")["kind"], "fix_validation")

    def test_stale_starts_at_thirty_days_and_older_ranks_first(self):
        thirty = self.convs.create(title="Thirty")
        sixty = self.convs.create(title="Sixty")
        ninety = self.convs.create(title="Ninety")
        fresh = self.convs.create(title="Fresh")
        for conv, listed in (
            (thirty, "2026-08-21T00:00:00Z"),
            (sixty, "2026-07-22T00:00:00Z"),
            (ninety, "2026-06-22T00:00:00Z"),
            (fresh, "2026-08-22T00:00:00Z"),
        ):
            conv.notes = json.dumps({
                "vendooMarketplaces": ["ebay"],
                "vendooDates": {"listed": listed},
            })
            self.convs.update_status(conv.id, "active")
        self.db.commit()
        cards = [card for card in list_suggestions(self.db, now=NOW) if card["kind"] == "stale_active"]
        self.assertEqual([card["title"] for card in cards], ["Ninety", "Sixty", "Thirty"])
        self.assertIn("30 days", cards[-1]["reason"])
        self.assertIn("eBay", cards[-1]["reason"])
        self.assertTrue(cards[0]["score"] > cards[1]["score"] > cards[2]["score"])

    def test_draft_with_revision_is_ready_to_review(self):
        conv = self.convs.create(title="Ready draft")
        self.listings.save_revision(conv.id, {"title": "Ready draft", "price": 18}, "generation")
        card = self._by_title("Ready draft")
        self.assertEqual(card["kind"], "ready_to_review")

    def test_caps_at_twenty(self):
        for index in range(25):
            conv = self.convs.create(title=f"Fail {index:02d}")
            self.convs.update_status(conv.id, "failed")
        self.assertEqual(len(list_suggestions(self.db, now=NOW)), 20)


if __name__ == "__main__":
    unittest.main()
