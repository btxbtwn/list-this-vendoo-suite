from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import JobEvent, VendooDraftCache
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.draft_cache import draft_has_status_signal, slim_vendoo_draft_payload
from vendoo_studio.services.maintenance import prune_event_bloat, table_sizes


class _DbTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Tee"}, source="model")
        self.repo = JobRepo(self.db)
        self.job = self.repo.create(
            self.conv.id, self.rev.id, {"title": "Tee"}, vendoo_item_id="itm1", status="completed",
        )

    def tearDown(self):
        self.db.close()


class SlimPayloadTest(unittest.TestCase):
    def test_only_the_status_slices_survive(self):
        payload = slim_vendoo_draft_payload(
            item={
                "generalDetails": {"title": "Tee", "description": "x" * 4000, "price": "24.00"},
                "listings": {
                    "ebay": {"status": {"listed": True}, "marketplaceSpecifics": {"type": "Tee"}},
                    "etsy": {"marketplaceSpecifics": {"type": "Tee"}},
                },
            },
            form={"statuses": {"general": "DRAFT"}, "fields": {"title": "Tee"}},
            statuses={"ebay": "LISTED"},
        )
        self.assertEqual(payload, {
            "item": {"listings": {"ebay": {"status": {"listed": True}}}},
            "form": {"statuses": {"general": "DRAFT"}},
            "statuses": {"ebay": "LISTED"},
        })

    def test_an_item_with_nothing_to_report_says_nothing(self):
        payload = slim_vendoo_draft_payload(item={"generalDetails": {"title": "Tee"}})
        self.assertEqual(payload, {})
        self.assertFalse(draft_has_status_signal(payload))


class EventBloatTest(_DbTest):
    def test_progress_and_review_keep_one_row_each(self):
        for step in ("filling_general", "saving_general", "filling_ebay"):
            self.repo.add_event(self.job.id, "progress", step, {"step": step})
        self.repo.add_event(self.job.id, "completion_review", "verifying_draft", {"readback": True})
        self.repo.add_event(self.job.id, "completion_review", "verifying_draft", {"readback": False})

        events = self.repo.get_events(self.job.id)
        self.assertEqual([event.event_type for event in events], ["progress", "completion_review"])
        self.assertEqual(events[0].step, "filling_ebay")
        self.assertEqual(events[1].payload, {"readback": False})

    def test_step_results_keep_their_timings_and_drop_their_blobs(self):
        self.repo.add_event(self.job.id, "step_completed", "filling_ebay", {
            "step": "filling_ebay",
            "duration_ms": 4200,
            "item": {"generalDetails": {"description": "x" * 4000}},
            "schema": {"ebay": {"fields": [{"label": "Type"}]}},
            "fill_log": {"entries": [{"status": "filled"}]},
            "verification": {"readback": True},
        })
        event = self.repo.latest_event(self.job.id, "step_completed")
        self.assertEqual(event.payload, {"step": "filling_ebay", "duration_ms": 4200})

    def test_pruning_clears_what_older_builds_left_behind(self):
        for sequence in range(5):
            self.db.add(JobEvent(
                id=f"old{sequence}",
                job_id=self.job.id,
                sequence=sequence,
                event_type="vendoo_draft",
                payload={"item": {"generalDetails": {"description": "x" * 4000}}},
            ))
        for sequence in range(5, 9):
            self.db.add(JobEvent(
                id=f"prog{sequence}",
                job_id=self.job.id,
                sequence=sequence,
                event_type="progress",
                payload={"step": "filling_ebay"},
            ))
        self.db.commit()

        pruned = prune_event_bloat(self.db)

        self.assertEqual(pruned["vendoo_drafts"], 5)
        self.assertEqual(pruned["duplicate_events"], 3)
        self.assertEqual(self.db.query(JobEvent).count(), 1)

    def test_a_pull_per_minute_cannot_grow_the_database(self):
        """The regression that filled a disk: one cache row, no events, ever."""
        for _ in range(50):
            self.repo.save_vendoo_draft(
                self.job.id,
                item={"itemID": "itm1", "listings": {"ebay": {"status": {"listed": True}}}},
                item_id="itm1",
                source="vendoo_sync",
            )
        self.assertEqual(self.db.query(VendooDraftCache).count(), 1)
        self.assertEqual(
            self.db.query(JobEvent).filter(JobEvent.event_type == "vendoo_draft").count(), 0
        )


class TableSizesTest(_DbTest):
    def test_the_report_names_the_tables_and_counts_their_rows(self):
        self.repo.add_event(self.job.id, "dispatched")
        sizes = table_sizes(self.db, limit=100)

        by_table = {entry["table"]: entry for entry in sizes}
        self.assertEqual(by_table["jobs"]["rows"], 1)
        self.assertEqual(by_table["job_events"]["rows"], 1)
        self.assertEqual(sizes, sorted(sizes, key=lambda entry: -(entry["bytes"] or 0)))


if __name__ == "__main__":
    unittest.main()
