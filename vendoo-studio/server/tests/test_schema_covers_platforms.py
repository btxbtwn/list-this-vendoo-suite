from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.services.category_catalog import (
    cached_schema_payload,
    remember_schema,
    schema_covers_platforms,
)


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

    def test_cached_schema_payload_builds_probe_shape(self) -> None:
        path = "Clothing > Tops"
        remember_schema(self.db, path, {
            "general": {
                "category": {"path": path},
                "fields": [{"label": "Title", "type": "text", "value": "drop me"}],
            },
            "ebay": {
                "category": {"path": "Clothing > Shirts"},
                "fields": [{"label": "Brand", "type": "text", "selector": "#x"}],
            },
        })
        payload = cached_schema_payload(self.db, path, ["general", "ebay"])
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["general"]["category"]["path"], path)
        self.assertEqual(payload["general"]["category"]["status"], "cached")
        self.assertEqual(payload["ebay"]["fields"], [{"label": "Brand", "type": "text"}])
        self.assertNotIn("selector", payload["ebay"]["fields"][0])
        self.assertIsNone(cached_schema_payload(self.db, path, ["general", "ebay", "depop"]))

    def test_poisoned_tee_nuts_cache_is_ignored(self) -> None:
        """Earlier tee→Fastener Nuts probes must not stick under women's Tops."""
        from vendoo_studio.models.catalog import CategorySchema
        from vendoo_studio.models.conversation import utcnow

        path = "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops"
        self.db.add(CategorySchema(
            general_path=path,
            marketplace="ebay",
            category_path="Business & Industrial > Fasteners & Hardware > Fastener Nuts > Tee Nuts",
            fields=[{"label": "Brand", "type": "text"}],
            observed_at=utcnow(),
        ))
        self.db.add(CategorySchema(
            general_path=path,
            marketplace="mercari",
            category_path="Toys & Collectibles > Dress Up & Pretend Play > Play Teepees",
            fields=[{"label": "Brand", "type": "text"}],
            observed_at=utcnow(),
        ))
        self.db.commit()
        self.assertIsNone(cached_schema_payload(self.db, path, ["ebay", "mercari"]))
        self.assertFalse(schema_covers_platforms(self.db, path, ["ebay", "mercari"]))

        # Fresh writes of hardware under an apparel general are refused.
        remember_schema(self.db, path, {
            "poshmark": {
                "category": {"path": "Business & Industrial > Fasteners & Hardware > Fastener Nuts > Tee Nuts"},
                "fields": [{"label": "Brand", "type": "text"}],
            },
        })
        self.assertIsNone(
            self.db.query(CategorySchema).filter_by(general_path=path, marketplace="poshmark").one_or_none()
        )


if __name__ == "__main__":
    unittest.main()
