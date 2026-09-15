from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategorySchema
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.services.listing_field_gaps import (
    build_missing_fields_request,
    collect_empty_discovered_fields,
    remaining_discovered_gap_count,
)


class ListingFieldGapsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(CategorySchema(
            general_path="Clothing > Tops",
            marketplace="etsy",
            category_path="Clothing > Tops > Blouses",
            fields=[
                {"label": "Pattern", "required": True, "options": ["Solid", "Floral"]},
                {"label": "Holiday", "required": False},
            ],
        ))
        self.db.commit()

    def test_collect_empty_discovered_fields_from_category_schema(self):
        listing = {
            "title": "Blouse",
            "category_path": "Clothing > Tops",
            "etsy_specifics": {"pattern": "Solid"},
        }
        gaps = collect_empty_discovered_fields(self.db, listing)
        labels = {(gap["marketplace"], gap["field"]) for gap in gaps}
        self.assertNotIn(("etsy", "Pattern"), labels)
        self.assertIn(("etsy", "Holiday"), labels)

    def test_build_missing_fields_request_lists_empty_fields(self):
        listing = {"title": "Blouse", "category_path": "Clothing > Tops"}
        gaps = [{"marketplace": "etsy", "field": "Holiday", "options": ["Christmas"]}]
        request = build_missing_fields_request(listing, gaps)
        self.assertIn("missing_fields", request)
        self.assertIn("Holiday", request)
        self.assertIn("Allowed options: Christmas", request)

    def test_remaining_discovered_gap_count_uses_merged_keys(self):
        listing = {
            "title": "Blouse",
            "category_path": "Clothing > Tops",
            "etsy_specifics": {},
        }
        self.assertEqual(remaining_discovered_gap_count(self.db, listing), 2)


if __name__ == "__main__":
    unittest.main()
