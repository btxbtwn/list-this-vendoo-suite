"""Synced Vendoo drafts grow the category field / LLM schema caches."""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategoryFieldSchema, CategorySchema
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.category_learn import (
    category_seed_from_vendoo_item,
    learn_category_schemas_from_item,
    specs_as_remember_schema,
)
from vendoo_studio.services.vendoo_import import listing_from_vendoo, merge_notes
from vendoo_studio.services.vendoo_specifics import FieldSpec, normalize_specifics
from vendoo_studio.services.vendoo_watch import SYNCED_AT, SYNCED_REVISION, sync_conversation


ITEM = {
    "itemID": "itm1",
    "dateLastModified": 2000,
    "generalDetails": {
        "title": "Tee",
        "categoryV2": {
            "id": "gen_tops",
            "displayPath": ["Clothing", "Women", "Tops"],
        },
    },
    "listings": {
        "ebay": {
            "overrides": {
                "categoryV2": {
                    "id": "53159",
                    "displayPath": ["Clothing", "Women", "Tops"],
                },
            },
        },
        "poshmark": {
            "overrides": {"categoryV2": {"id": "posh_tops"}},
            "marketplaceSpecifics": {"categoryPath": ["Women", "Tops", "T-Shirts"]},
        },
    },
}

RAW_EBAY = {
    "Season": {
        "id": "Season",
        "display": "Season",
        "rules": {"fieldOptions": {"minValues": 0, "maxValues": 2, "selectionMode": "SelectionOnly"}},
        "options": {
            "0": {"id": "Spring", "display": "Spring"},
            "1": {"id": "Fall", "display": "Fall"},
        },
    },
    "Department": {
        "id": "Department",
        "display": "Department",
        "rules": {"fieldOptions": {"minValues": 1, "maxValues": 1, "selectionMode": "SelectionOnly"}},
        "options": {"0": {"id": "Women", "display": "Women"}},
    },
}


class CategorySeedFromItemTest(unittest.TestCase):
    def test_extracts_leaf_ids_paths_and_objects(self):
        seed = category_seed_from_vendoo_item(ITEM)
        self.assertEqual(seed["category_path"], "Clothing > Women > Tops")
        self.assertEqual(seed["category_id"], "gen_tops")
        self.assertEqual(seed["marketplace_category_ids"]["ebay"], "53159")
        self.assertEqual(seed["marketplace_category_ids"]["poshmark"], "posh_tops")
        self.assertEqual(seed["marketplace_categories"]["ebay"], "Clothing > Women > Tops")
        self.assertEqual(seed["marketplace_categories"]["poshmark"], "Women > Tops > T-Shirts")
        self.assertEqual(seed["marketplace_category_objects"]["ebay"]["id"], "53159")

    def test_listing_from_vendoo_carries_leaf_ids(self):
        listing = listing_from_vendoo(ITEM, None)
        self.assertEqual(listing["marketplace_category_ids"]["ebay"], "53159")
        self.assertEqual(listing["marketplace_categories"]["poshmark"], "Women > Tops > T-Shirts")


class SpecsAsRememberSchemaTest(unittest.TestCase):
    def test_includes_dropdown_options_as_complete(self):
        specs = normalize_specifics(RAW_EBAY)
        schema = specs_as_remember_schema(
            {"ebay": specs},
            {"ebay": "Clothing > Women > Tops"},
        )
        fields = {row["key"]: row for row in schema["ebay"]["fields"]}
        self.assertEqual(schema["ebay"]["category"]["path"], "Clothing > Women > Tops")
        self.assertTrue(fields["Department"]["required"])
        self.assertTrue(fields["Season"]["multiple"])
        self.assertTrue(fields["Season"]["options_complete"])
        self.assertEqual(
            [opt["label"] for opt in fields["Season"]["options"]],
            ["Spring", "Fall"],
        )

    def test_skips_marketplaces_without_a_path(self):
        specs = {"ebay": {"Size": FieldSpec("Size", display="Size")}}
        self.assertEqual(specs_as_remember_schema(specs, {}), {})


class LearnFromSyncedItemTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self._session_cm = mock.patch(
            "vendoo_studio.services.category_fields.SessionLocal",
            self._session_factory,
        )
        self._session_cm.start()

    def _session_factory(self):
        """``save_fields`` / ``load_fields`` open their own session; reuse ours."""
        return _SessionProxy(self.db)

    def tearDown(self):
        self._session_cm.stop()
        self.db.close()

    def test_uncached_leaf_is_fetched_saved_and_remembered(self):
        saved: list[tuple[str, str]] = []

        async def fake_fetch(job, listing):
            from vendoo_studio.services.category_fields import save_fields

            specs = normalize_specifics(RAW_EBAY)
            save_fields("ebay", "53159", specs)
            saved.append(("ebay", "53159"))
            return {"ebay": specs}

        with mock.patch(
            "vendoo_studio.services.vendoo_create.fetch_listing_specifics",
            fake_fetch,
        ):
            result = asyncio.run(learn_category_schemas_from_item(self.db, ITEM))

        self.assertEqual(result["learned"], ["ebay"])
        self.assertEqual(saved, [("ebay", "53159")])
        row = (
            self.db.query(CategoryFieldSchema)
            .filter_by(marketplace="ebay", category_id="53159")
            .one()
        )
        self.assertTrue(any(field.get("key") == "Season" for field in row.fields))
        remembered = (
            self.db.query(CategorySchema)
            .filter_by(general_path="Clothing > Women > Tops", marketplace="ebay")
            .one()
        )
        season = next(field for field in remembered.fields if field["key"] == "Season")
        self.assertTrue(season["options_complete"])
        self.assertEqual([opt["label"] for opt in season["options"]], ["Spring", "Fall"])

    def test_already_cached_leaf_skips_fetch(self):
        from vendoo_studio.services.category_catalog import remember_schema
        from vendoo_studio.services.category_fields import save_fields

        specs = normalize_specifics(RAW_EBAY)
        save_fields("ebay", "53159", specs)
        remember_schema(
            self.db,
            "Clothing > Women > Tops",
            specs_as_remember_schema({"ebay": specs}, {"ebay": "Clothing > Women > Tops"}),
        )
        # Poshmark leaf is also required by the short-circuit only when *all*
        # ids are covered; seed only ebay in a shrunk item.
        item = {
            **ITEM,
            "listings": {"ebay": ITEM["listings"]["ebay"]},
        }

        with mock.patch(
            "vendoo_studio.services.vendoo_create.fetch_listing_specifics",
            mock.AsyncMock(side_effect=AssertionError("should not fetch")),
        ) as fetch:
            result = asyncio.run(learn_category_schemas_from_item(self.db, item))

        self.assertEqual(result["reason"], "already cached")
        self.assertEqual(result["learned"], [])
        fetch.assert_not_called()

    def test_missing_category_ids_is_a_noop(self):
        result = asyncio.run(learn_category_schemas_from_item(self.db, {
            "generalDetails": {"title": "No cats"},
        }))
        self.assertEqual(result["reason"], "no category ids")


class _SessionProxy:
    """Context-manager stand-in for ``SessionLocal`` that yields a fixed session."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


class SyncConversationLearnsSchemasTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Tee"}, source="model")
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {
            "vendooItemId": "itm1",
            SYNCED_AT: "1000",
            SYNCED_REVISION: self.rev.id,
        })
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_successful_sync_learns_schemas(self):
        async def fake_run_ops(job, ops):
            return {"ok": True, "results": [{"op": "get_item", "ok": True, "item": ITEM}]}

        async def fake_learn(db, item):
            self.assertEqual(item["itemID"], "itm1")
            return {"learned": ["ebay"], "reason": "ok"}

        with mock.patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops), \
                mock.patch(
                    "vendoo_studio.services.category_learn.learn_category_schemas_from_item",
                    fake_learn,
                ):
            result = asyncio.run(sync_conversation(self.db, self.conv.id))

        self.assertEqual(result["action"], "pull")
        self.assertEqual(result["schemas_learned"], ["ebay"])


if __name__ == "__main__":
    unittest.main()
