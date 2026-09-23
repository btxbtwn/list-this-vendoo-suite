from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation  # noqa: F401
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo


class MessageStampsConversationTest(unittest.TestCase):
    """A sent prompt must leave the listing with a real activity stamp.

    ``Message.created_at`` is a column default, so it is only populated once the
    INSERT is flushed. Reading it too early wrote NULL into the conversation's
    ``updated_at``, which drops the listing out of the sidebar's recency order.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        # Must mirror SessionLocal: with autoflush on, the conversation lookup
        # would flush the INSERT for us and hide the bug.
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.repo = ConversationRepo(self.db)

    def tearDown(self):
        self.db.close()

    def test_add_message_stamps_updated_at_from_the_message(self):
        conv = self.repo.create()
        msg = self.repo.add_message(conv.id, "user", "make this a listing")

        self.assertIsNotNone(msg.created_at)
        stored = self.repo.get(conv.id)
        self.assertIsNotNone(stored.updated_at)
        self.assertEqual(stored.updated_at, msg.created_at.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
