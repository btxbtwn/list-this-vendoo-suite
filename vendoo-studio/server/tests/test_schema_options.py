from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import JobRepo, RegistryRepo
from vendoo_studio.services.registry import RegistryService


ETSY_PATH = "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops"


def _field(label, options, source="live-dropdown", selector=""):
    return {
        "label": label,
        "selector": selector or f"#listings.etsy.{label.replace(' ', '')}",
        "is_dropdown": True,
        "options": options,
        "options_source": source,
    }


class SchemaOptionIngestTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.repo = RegistryRepo(self.db)

    def tearDown(self):
        self.db.close()

    def test_probe_stores_live_options_per_marketplace(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"]),
        ])
        self.repo.upsert_schema_fields("depop", ETSY_PATH, [
            _field("Parcel Size", ["Small", "Medium", "Large"]),
        ])

        self.assertEqual(
            self.repo.get_valid_options("etsy", "When Made", ETSY_PATH),
            ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"],
        )
        self.assertEqual(
            self.repo.get_valid_options("depop", "Parcel Size", ETSY_PATH),
            ["Large", "Medium", "Small"],
        )
        # Options must not bleed across marketplaces.
        self.assertEqual(self.repo.get_valid_options("depop", "When Made", ETSY_PATH), [])

    def test_authoritative_capture_drops_removed_options(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2026 (Recently)", "Made To Order (Not Yet Made)"]),
        ])
        # Vendoo renames the recent bucket; the dead label must not survive.
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2027 (Recently)", "Made To Order (Not Yet Made)"]),
        ])

        options = self.repo.get_valid_options("etsy", "When Made", ETSY_PATH)
        self.assertIn("2020 - 2027 (Recently)", options)
        self.assertNotIn("2020 - 2026 (Recently)", options)

    def test_native_schema_options_store_labels_without_losing_catalog_values(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", [{"label": "Before 2004 (Vintage)", "value": "vintage"}],
                   source="native-select"),
        ])
        self.assertEqual(self.repo.get_valid_options("etsy", "When Made", ETSY_PATH),
                         ["Before 2004 (Vintage)"])

    def test_partial_capture_does_not_replace_known_options(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"]),
        ])
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["Before 2004 (Vintage)"], source="unavailable"),
        ])

        options = self.repo.get_valid_options("etsy", "When Made", ETSY_PATH)
        self.assertIn("2020 - 2026 (Recently)", options)
        self.assertIn("Before 2004 (Vintage)", options)

    def test_category_specific_options_win_over_generic(self):
        self.repo.create(
            marketplace="etsy",
            category_path=None,
            normalized_label="when made",
            known_options=["Generic Option"],
        )
        self.db.commit()
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2026 (Recently)"]),
        ])

        by_label = self.repo.options_by_label("etsy", ETSY_PATH)
        self.assertEqual(by_label["when made"], ["2020 - 2026 (Recently)"])

    def test_category_picker_is_not_stored(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("Category", ["Tops", "Bottoms"]),
        ])
        self.assertEqual(self.repo.get_valid_options("etsy", "Category", ETSY_PATH), [])

    def test_generation_prompt_lists_allowed_values(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"]),
        ])
        text = RegistryService(self.db).generation_context(ETSY_PATH)
        self.assertIn("when_made", text)
        self.assertIn("2020 - 2026 (Recently)", text)
        self.assertIn("Before 2004 (Vintage)", text)
        self.assertIn("copy one of them exactly", text)

    def test_generation_prompt_truncates_huge_option_sets(self):
        from vendoo_studio.services.registry import MAX_PROMPT_OPTIONS

        many = [f"Option {i:03d}" for i in range(MAX_PROMPT_OPTIONS + 25)]
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [_field("Holiday", many)])
        text = RegistryService(self.db).generation_context(ETSY_PATH)
        self.assertIn("Option 000", text)
        self.assertNotIn(f"Option {MAX_PROMPT_OPTIONS + 24:03d}", text)
        self.assertIn("…", text)

    def test_fields_without_options_still_appear_in_the_prompt(self):
        self.repo.ensure_field("etsy", "Holiday", category_path=ETSY_PATH)
        text = RegistryService(self.db).generation_context(ETSY_PATH)
        self.assertIn("holiday", text)
        self.assertNotIn("one of:", text)

    def test_stored_options_repair_a_stale_value(self):
        self.repo.upsert_schema_fields("etsy", ETSY_PATH, [
            _field("When Made", ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"]),
        ])
        value, ok, _ = RegistryService(self.db).normalize_value(
            "etsy", "When Made", "2020 - 2026 (recently)", ETSY_PATH,
        )
        self.assertTrue(ok)
        self.assertEqual(value, "2020 - 2026 (Recently)")


class SchemaPayloadRoundTripTest(unittest.TestCase):
    """The probe payload used to dead-end at an event holding field counts."""

    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = Conversation(title="Tee")
        self.db.add(self.conv)
        self.db.commit()
        self.job = JobRepo(self.db).create(
            conv_id=self.conv.id,
            approved_revision_id="schema-probe",
            listing_snapshot={"category_path": ETSY_PATH, "_schema_probe": True},
        )

    def tearDown(self):
        self.db.close()

    def test_probe_options_reach_the_extension_payload(self):
        from vendoo_studio.routes.extension import (
            _build_registry_options,
            _learn_schema_options,
        )

        schema = {
            "etsy": {"fields": [
                _field("When Made", ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"]),
                _field("Holiday", [], source="unavailable"),
            ]},
            "depop": {"fields": [
                _field("Parcel Size", ["Small", "Medium", "Large"]),
            ]},
        }

        learned = _learn_schema_options(self.db, self.job, schema)
        self.assertEqual(learned, {"etsy": 1, "depop": 1})

        payload = _build_registry_options(self.db, ["etsy", "depop"], ETSY_PATH)
        self.assertEqual(
            payload["etsy"]["when made"],
            ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"],
        )
        self.assertEqual(payload["depop"]["parcel size"], ["Large", "Medium", "Small"])
        self.assertNotIn("holiday", payload["etsy"])

    def test_options_are_scoped_to_the_probed_category(self):
        from vendoo_studio.routes.extension import (
            _build_registry_options,
            _learn_schema_options,
        )

        _learn_schema_options(self.db, self.job, {
            "etsy": {"fields": [_field("When Made", ["2020 - 2026 (Recently)"])]},
        })

        other = _build_registry_options(self.db, ["etsy"], "Home & Garden > Kitchen")
        self.assertEqual(other, {})


if __name__ == "__main__":
    unittest.main()
