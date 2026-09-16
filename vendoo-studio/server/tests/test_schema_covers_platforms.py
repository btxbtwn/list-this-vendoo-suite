from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.services.category_catalog import remember_schema, schema_covers_platforms


class SchemaCoversPlatformsTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self) -> None:
        self.db.close()

    def test_requires_fields_and_category_for_every_platform(self) -> None:
        path = "Clothing > Tops > T-Shirts"
        remember_schema(self.db, path, {
            "ebay": {
                "category": {"path": "Clothing > Tops > T-Shirts"},
                "fields": [{"label": "Brand", "type": "text"}],
            },
            "poshmark": {
                "category": {"path": "Women > Tops > Tees"},
                "fields": [{"label": "Brand", "type": "text"}],
            },
        })
        self.assertTrue(schema_covers_platforms(self.db, path, ["ebay", "poshmark"]))
        self.assertFalse(schema_covers_platforms(self.db, path, ["ebay", "poshmark", "depop"]))
        self.assertFalse(schema_covers_platforms(self.db, path, []))
        self.assertFalse(schema_covers_platforms(self.db, "", ["ebay"]))

    def test_incomplete_section_does_not_cover(self) -> None:
        path = "Clothing > Tops"
        remember_schema(self.db, path, {
            "ebay": {
                "category": {"path": "Clothing > Tops"},
                "fields": [],
                "error": "No form fields were found",
            },
        })
        self.assertFalse(schema_covers_platforms(self.db, path, ["ebay"]))


if __name__ == "__main__":
    unittest.main()
