"""The "edited here, not sent to Vendoo yet" flag the sidebar chip reads.

It is derived from the sync machinery's own marker — the revision Studio and
Vendoo were last level on — rather than from revision timestamps, because a
pull writes a revision too and dating the comparison would call Vendoo's own
copy an unsent edit the moment it landed.
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes

LISTING = {"title": "Levi's 501", "description": "Classic fit.", "price": 48}


class UnsentEditsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        def override():
            yield self.db

        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Jeans")
        self.revision = ListingRepo(self.db).save_revision(self.conv.id, LISTING, source="model")

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def mark_synced_on(self, revision_id: str) -> None:
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {
            "vendooItemId": "itm1", "vendooSyncedRevision": revision_id,
        })
        self.db.commit()

    def flag(self, conv_id: str | None = None) -> bool:
        res = self.client.get(f"/api/conversations/{conv_id or self.conv.id}")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["unsent_edits"]

    def test_level_with_vendoo_reads_as_sent(self):
        self.mark_synced_on(self.revision.id)
        self.assertFalse(self.flag())

    def test_an_edit_after_the_last_sync_is_unsent(self):
        self.mark_synced_on(self.revision.id)
        ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "price": 42}, source="user_form")
        self.assertTrue(self.flag())

    def test_a_pull_from_vendoo_is_not_an_unsent_edit(self):
        """The revision came *from* Vendoo, so the two are level, not ahead."""
        self.mark_synced_on(self.revision.id)
        pulled = ListingRepo(self.db).save_revision(
            self.conv.id, {**LISTING, "title": "Vendoo's title"}, source="vendoo_pull",
        )
        self.mark_synced_on(pulled.id)
        self.assertFalse(self.flag())

    def test_an_unbound_listing_has_nothing_to_be_ahead_of(self):
        ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "price": 42}, source="user_form")
        self.assertFalse(self.flag())

    def test_the_sidebar_list_carries_the_same_answer(self):
        self.mark_synced_on(self.revision.id)
        ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "price": 42}, source="user_form")
        rows = self.client.get("/api/conversations").json()
        row = next(item for item in rows if item["id"] == self.conv.id)
        self.assertTrue(row["unsent_edits"])


if __name__ == "__main__":
    unittest.main()
