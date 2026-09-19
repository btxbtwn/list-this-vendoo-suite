from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes
from vendoo_studio.services.vendoo_pull_offers import (
    clear_all,
    clear_offer,
    get_offer,
    list_offers,
    offer_pull,
)
from vendoo_studio.services.vendoo_watch import SYNCED_REVISION, studio_has_unpushed_edits


class PullOffersTest(unittest.TestCase):
    def setUp(self):
        clear_all()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Tee"}, source="model")
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "itm1", SYNCED_REVISION: self.rev.id})
        self.db.commit()

    def tearDown(self):
        clear_all()
        self.db.close()

    def test_offer_records_and_lists(self):
        offer_pull(conversation_id=self.conv.id, item_id="itm1", conflict=False)
        offers = list_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].conversation_id, self.conv.id)
        self.assertFalse(offers[0].conflict)

    def test_conflict_flag_and_dismiss(self):
        offer_pull(conversation_id=self.conv.id, item_id="itm1", conflict=True)
        self.assertTrue(get_offer(self.conv.id).conflict)
        self.assertTrue(clear_offer(self.conv.id))
        self.assertIsNone(get_offer(self.conv.id))

    def test_find_bound_conversation_for_save_notify(self):
        found = ConversationRepo(self.db).find_by_vendoo_item_id("itm1")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, self.conv.id)
        self.assertFalse(studio_has_unpushed_edits(self.db, self.conv.id))
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Edited"}, source="user")
        self.assertTrue(studio_has_unpushed_edits(self.db, self.conv.id))


if __name__ == "__main__":
    unittest.main()
