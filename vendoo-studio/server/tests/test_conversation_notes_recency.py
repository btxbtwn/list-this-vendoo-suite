from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo


class WriteNotesRecencyTest(unittest.TestCase):
    """Notes carry Vendoo bookkeeping, which is not always seller activity."""

    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.repo = ConversationRepo(self.db)
        self.conv = self.repo.create(title="Tee", notes='{"vendooStatus": "draft"}')

    def tearDown(self):
        self.db.close()

    def test_a_quiet_write_stores_notes_without_moving_the_listing(self):
        before = self.conv.updated_at
        self.repo.write_notes(self.conv.id, '{"vendooStatus": "active"}', bump_updated_at=False)

        conv = self.repo.get(self.conv.id)
        self.assertEqual(conv.notes, '{"vendooStatus": "active"}')
        self.assertEqual(conv.updated_at, before)

    def test_an_ordinary_write_counts_as_activity(self):
        before = self.conv.updated_at
        self.repo.write_notes(self.conv.id, '{"vendooStatus": "sold"}')

        conv = self.repo.get(self.conv.id)
        self.assertEqual(conv.notes, '{"vendooStatus": "sold"}')
        self.assertGreater(conv.updated_at, before)

    def test_rewriting_the_same_notes_changes_nothing(self):
        before = self.conv.updated_at
        self.repo.write_notes(self.conv.id, '{"vendooStatus": "draft"}')

        self.assertEqual(self.repo.get(self.conv.id).updated_at, before)


if __name__ == "__main__":
    unittest.main()
