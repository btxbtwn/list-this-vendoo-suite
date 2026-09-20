from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vendoo_studio.services import category_fields, vendoo_create
from vendoo_studio.services.vendoo_specifics import normalize_specifics
from vendoo_studio.services.vendoo_create import (
    VendooCreateError,
    create_item,
    load_schema,
    probe_schema,
    resolve_label_display_names,
    resolve_listing_categories,
    resolve_listing_labels,
)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


JOB = SimpleNamespace(id="job-1", conversation_id="conv-1")
PHOTOS = [
    SimpleNamespace(id="p1", mime_type="image/jpeg", width=1600, height=1200),
    SimpleNamespace(id="p2", mime_type="image/png", width=800, height=900),
]
LISTING = {"title": "Levi's 501", "description": "Classic", "price": 48, "condition": "Pre-Owned - Good"}
PROBED = {"generalDetails": {"condition": {"value": "v_pre_owned_good", "displayName": "Pre-Owned - Good"}}, "itemID": "old1"}


def ops_for(fake, name):
    """The ops list of the request that carried this op."""
    for _type, payload in fake.sent:
        ops = (payload or {}).get("ops") or []
        if any(op.get("op") == name for op in ops):
            return ops
    raise AssertionError(f"no request carried {name}")


def every_op(fake, name):
    """Every op of this kind, across all requests."""
    found = []
    for _type, payload in fake.sent:
        found.extend(op for op in ((payload or {}).get("ops") or []) if op.get("op") == name)
    return found


def specifics_reply(fields=None):
    """A ``category_specifics`` reply shaped like Vendoo's payload."""
    return {"ok": True, "results": [
        {"op": "category_specifics", "ok": True, "specifics": fields or {}},
    ]}


class FakeBridge:
    """Scripted replies, with the optional category-schema fetch auto-answered.

    ``fetch_listing_specifics`` is best-effort and asks once per resolved
    marketplace, so tests that are not about it answer "no schema" and exercise
    the fallback. Pass ``specifics`` to script a real one.
    """

    def __init__(self, replies, specifics=None, mapped=None, recommended=None):
        self.replies = list(replies)
        self.specifics = specifics
        # {marketplace: match}. Unset means Vendoo maps nothing, so the caller
        # falls back to searching each marketplace.
        self.mapped = mapped
        # {marketplace: [alternate, …]} the mapper returns beside its match.
        self.recommended = recommended
        self.sent = []

    async def request(self, job, message_type, payload=None, *, timeout=0):
        self.sent.append((message_type, payload))
        ops = (payload or {}).get("ops") or []
        if ops and all(op.get("op") == "category_specifics" for op in ops):
            return self.specifics or specifics_reply()
        if ops and all(op.get("op") == "category_map" for op in ops):
            return {"ok": True, "results": [{
                "op": "category_map", "ok": True,
                "marketplace_id": op["marketplace_id"],
                "match": (self.mapped or {}).get(op["marketplace_id"]),
                "recommendations": (self.recommended or {}).get(op["marketplace_id"], []),
            } for op in ops]}
        # Post-create brand/style repair: answer without consuming scripted replies.
        if ops and ops[0].get("op") == "update_item":
            results = []
            for op in ops:
                if op.get("op") == "update_item":
                    results.append({"op": "update_item", "ok": True, "item_id": op.get("item_id")})
                elif op.get("op") == "get_item":
                    results.append({
                        "op": "get_item", "ok": True,
                        "item_id": op.get("item_id"),
                        "item": {"itemID": op.get("item_id")},
                    })
                else:
                    raise AssertionError(f"unexpected op in update batch: {op.get('op')}")
            return {"ok": True, "results": results}
        return self.replies.pop(0)


class _TmpSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(vendoo_create, "schema_path", lambda: Path(self.tmp.name) / "schema.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()


class ProbeTest(_TmpSchema):
    def test_learns_and_persists_merged_schema(self):
        fake = FakeBridge([
            {"ok": True, "results": [{"op": "get_item", "ok": True, "item_id": "old1", "item": PROBED},
                                     {"op": "get_item", "ok": False, "item_id": "old2", "error": "404"}]},
        ])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(probe_schema(JOB, ["old1", "old2"]))
        self.assertEqual(out["learned_from"], 1)
        self.assertEqual(out["failures"], [{"item_id": "old2", "error": "404"}])
        self.assertEqual(out["schema"]["fields"]["condition"]["labels"]["pre owned good"], "v_pre_owned_good")
        self.assertEqual(load_schema()["item_count"], 1)
        ops = fake.sent[0][1]["ops"]
        self.assertEqual([op["op"] for op in ops], ["get_item", "get_item"])

        # A second probe widens rather than replaces.
        fake2 = FakeBridge([{"ok": True, "results": [{"op": "get_item", "ok": True, "item": {
            "generalDetails": {"condition": {"value": "v_new", "displayName": "New With Tags/Box"}}}}]}])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake2.request):
            run(probe_schema(JOB, ["old3"]))
        labels = load_schema()["fields"]["condition"]["labels"]
        self.assertEqual(set(labels), {"pre owned good", "new with tags box"})
        self.assertEqual(load_schema()["item_count"], 2)

    def test_requires_ids(self):
        with self.assertRaises(VendooCreateError):
            run(probe_schema(JOB, []))


class _NoExtraMapping(_TmpSchema):
    """Target only the marketplaces a test names, not this machine's settings."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(vendoo_create, "_mappable_marketplaces", return_value=())
        patch.start()
        self.addCleanup(patch.stop)


class CreateTest(_NoExtraMapping):
    def _replies(self):
        return [
            {"ok": True, "uid": "u1", "results": [
                {"op": "session", "ok": True, "uid": "u1"},
                {"op": "new_item_id", "ok": True, "item_id": "NEWid1234567890abcde"},
                {"op": "subscription", "ok": True, "version": "v2"},
                {"op": "upload_photo", "ok": True, "photo_id": "p1", "image": {"version": 3, "id": "images/u1/a.jpg", "originalMaxDimension": 1600}},
                {"op": "upload_photo", "ok": True, "photo_id": "p2", "image": {"version": 3, "id": "images/u1/b.png", "originalMaxDimension": 900}},
            ]},
            {"ok": True, "uid": "u1", "results": [
                {"op": "create_item", "ok": True, "result": {"ok": True}},
                {"op": "get_item", "ok": True, "item_id": "NEWid1234567890abcde", "item": {
                    "itemID": "NEWid1234567890abcde",
                    "generalDetails": {"title": "Levi's 501", "description": "Classic", "price": 48,
                                       "condition": {"value": "v_pre_owned_good", "displayName": "Pre-Owned - Good"}},
                }},
            ]},
        ]

    def test_creates_item_and_verifies(self):
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {"condition": {
            "labels": {"pre owned good": "v_pre_owned_good"}, "codes": ["v_pre_owned_good"], "shape": "object"}}, "item_count": 1}))
        fake = FakeBridge(self._replies())
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, LISTING, PHOTOS))

        self.assertEqual(out["item_id"], "NEWid1234567890abcde")
        self.assertEqual(out["url"], "https://web.vendoo.co/app/item/NEWid1234567890abcde")
        self.assertEqual(out["unresolved"], [])
        self.assertEqual(out["diff"], [])

        prep_ops = fake.sent[0][1]["ops"]
        self.assertEqual([op["op"] for op in prep_ops], ["session", "new_item_id", "subscription", "upload_photo", "upload_photo"])
        self.assertEqual(prep_ops[3]["photo"]["url"], "http://127.0.0.1:4318/api/jobs/job-1/photos/p1")
        self.assertEqual(prep_ops[3]["photo"]["extension"], "jpg")
        self.assertEqual(prep_ops[4]["photo"]["extension"], "png")
        self.assertEqual(prep_ops[4]["photo"]["max_dimension"], 900)

        create_ops = fake.sent[1][1]["ops"]
        self.assertEqual(create_ops[0]["op"], "create_item")
        self.assertEqual(create_ops[0]["subscription_version"], "v2")
        item = create_ops[0]["item"]
        self.assertEqual(item["itemID"], "NEWid1234567890abcde")
        self.assertEqual(item["userID"], "u1")
        self.assertEqual(item["generalDetails"]["condition"]["value"], "v_pre_owned_good")
        self.assertEqual([img["id"] for img in item["generalDetails"]["images"]], ["images/u1/a.jpg", "images/u1/b.png"])
        self.assertEqual(create_ops[1], {"op": "get_item", "item_id": "NEWid1234567890abcde"})

    def test_sends_label_ids_not_names(self):
        """Vendoo's label box only shows ids it finds in the seller's labels."""
        resolved = {"ok": True, "uid": "u1", "results": [
            {"op": "resolve_labels", "ok": True, "ids": ["lblToList"], "created": []},
        ]}
        fake = FakeBridge([resolved, *self._replies()])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            run(create_item(JOB, {**LISTING, "labels": ["To List"]}, PHOTOS))

        self.assertEqual(ops_for(fake, "resolve_labels"), [{"op": "resolve_labels", "names": ["To List"]}])
        self.assertEqual(ops_for(fake, "create_item")[0]["item"]["labels"], ["lblToList"])

    def test_resolve_label_display_names_maps_ids_to_catalog_names(self):
        from vendoo_studio.services import vendoo_label_catalog

        vendoo_label_catalog.clear_for_tests()
        fake = FakeBridge([{
            "ok": True,
            "results": [{
                "op": "list_labels",
                "ok": True,
                "labels": [
                    {"id": "g8MHWF7KiscANFLZRGyM", "name": "Women"},
                    {"id": "0kGVwda9cRk55wmfd3Bq", "name": "To List"},
                ],
            }],
        }])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            names = run(resolve_label_display_names(
                JOB,
                ["g8MHWF7KiscANFLZRGyM", "Already A Name", "0kGVwda9cRk55wmfd3Bq"],
            ))
        self.assertEqual(names, ["Women", "Already A Name", "To List"])
        self.assertEqual(ops_for(fake, "list_labels"), [{"op": "list_labels"}])
        self.assertEqual(
            vendoo_label_catalog.load()["g8MHWF7KiscANFLZRGyM"],
            "Women",
        )

    def test_resolve_label_display_names_uses_cache_when_chrome_is_silent(self):
        from vendoo_studio.services import vendoo_label_catalog
        from vendoo_studio.services.browser_bridge import BrowserBridgeError

        vendoo_label_catalog.clear_for_tests()
        vendoo_label_catalog.remember({"g8MHWF7KiscANFLZRGyM": "Women"})

        async def boom(*_a, **_k):
            raise BrowserBridgeError("Chrome did not answer in time.")

        with mock.patch.object(vendoo_create.browser_bridge, "request", boom):
            names = run(resolve_label_display_names(
                JOB,
                ["g8MHWF7KiscANFLZRGyM", "Bin 4"],
                timeout=0.2,
            ))
        self.assertEqual(names, ["Women", "Bin 4"])

    def test_reports_unresolved_and_diff(self):
        replies = self._replies()
        replies[1]["results"][1]["item"]["generalDetails"]["price"] = 50
        fake = FakeBridge(replies)
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, LISTING, PHOTOS))
        self.assertEqual([u["field"] for u in out["unresolved"]], ["condition"])
        # Vendoo turning our plain label into its coded object is not a mismatch;
        # the changed price is.
        self.assertEqual([d["field"] for d in out["diff"]], ["price"])

    def test_failed_upload_stops_before_create(self):
        replies = self._replies()
        replies[0] = {"ok": False, "results": [
            {"op": "session", "ok": True, "uid": "u1"},
            {"op": "new_item_id", "ok": True, "item_id": "x"},
            {"op": "subscription", "ok": True, "version": None},
            {"op": "upload_photo", "ok": False, "error": "Vendoo image slot returned 401"},
        ]}
        fake = FakeBridge(replies)
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request), self.assertRaises(VendooCreateError) as ctx:
            run(create_item(JOB, LISTING, PHOTOS))
        self.assertIn("401", str(ctx.exception))
        self.assertEqual(len(fake.sent), 1)

    def test_needs_photos(self):
        with self.assertRaises(VendooCreateError):
            run(create_item(JOB, LISTING, []))

    def test_resolves_categories_before_create(self):
        listing = {
            **LISTING,
            "category_path": "Clothing > Men > Jeans",
            "marketplace_categories": {"poshmark": "Men > Jeans > Straight"},
        }
        replies = [
            {"ok": True, "results": [
                {"op": "category_search", "ok": True, "leaf": {"id": "gen1", "is_leaf": True, "path": "Clothing > Men > Jeans"},
                 "matches": [{"id": "gen1", "is_leaf": True, "path": "Clothing > Men > Jeans"}]},
            ]},
            {"ok": True, "results": [
                {"op": "category_search", "ok": True, "leaf": {"id": "posh1", "is_leaf": True, "path": "Men > Jeans > Straight"},
                 "matches": [{"id": "posh1", "is_leaf": True, "path": "Men > Jeans > Straight"}]},
            ]},
            *self._replies(),
        ]
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {"condition": {
            "labels": {"pre owned good": "v_pre_owned_good"}, "codes": ["v_pre_owned_good"], "shape": "object"}}, "item_count": 1}))
        fake = FakeBridge(replies)
        with mock.patch.object(vendoo_create, "tree_leaf", return_value=None), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, listing, PHOTOS))
        self.assertEqual(out["item_id"], "NEWid1234567890abcde")
        # General is settled on its own first, then Vendoo is asked to map it.
        # Poshmark is only searched because this mapper answers nothing.
        search_ops = every_op(fake, "category_search")
        self.assertEqual([op["marketplace_id"] for op in search_ops], ["vendoo", "poshmark"])
        self.assertEqual([op["marketplace_id"] for op in every_op(fake, "category_map")], ["poshmark"])
        self.assertEqual([op["op"] for op in ops_for(fake, "session")][:3], ["session", "new_item_id", "subscription"])
        item = ops_for(fake, "create_item")[0]["item"]
        self.assertEqual(item["generalDetails"]["categoryV2"]["id"], "gen1")
        self.assertEqual(item["listings"]["poshmark"]["overrides"]["categoryV2"]["id"], "posh1")

    def test_vendoo_maps_the_marketplaces_from_one_general_choice(self):
        """Each marketplace follows from the general category, not its own search."""
        listing = {
            **LISTING,
            "category_path": "Clothing > Men > Jeans",
            "marketplace_categories": {
                "ebay": "Clothing > Men > Jeans",
                "poshmark": "Men > Jeans > Straight",
            },
        }
        replies = [
            {"ok": True, "results": [
                {"op": "category_search", "ok": True,
                 "leaf": {"id": "gen1", "is_leaf": True, "path": "Clothing > Men > Jeans",
                          "parent_category_id_path": ["clothing", "clothing__men"]},
                 "matches": []},
            ]},
            *self._replies(),
        ]
        mapped = {
            "ebay": {"id": "1154", "is_leaf": True, "all_category_label": ["Clothing", "Men", "Jeans"],
                     "parent_category_id_path": ["11450", "1059"]},
            "poshmark": {"id": "posh1", "is_leaf": True,
                         "all_category_label": ["Men", "Jeans", "Straight"],
                         "parent_category_id_path": ["men", "men_jeans"]},
        }
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {}, "item_count": 0}))
        fake = FakeBridge(replies, mapped=mapped)
        with mock.patch.object(vendoo_create, "tree_leaf", return_value=None), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, listing, PHOTOS))

        self.assertEqual(out["item_id"], "NEWid1234567890abcde")
        # Only the general tree is searched; the rest are mapped from it.
        self.assertEqual([op["marketplace_id"] for op in every_op(fake, "category_search")], ["vendoo"])
        self.assertEqual(
            sorted(op["marketplace_id"] for op in every_op(fake, "category_map")),
            ["ebay", "poshmark"],
        )
        # The mapper is handed the general category it maps from.
        self.assertEqual(every_op(fake, "category_map")[0]["general_category"]["id"], "gen1")
        item = ops_for(fake, "create_item")[0]["item"]
        self.assertEqual(item["listings"]["ebay"]["overrides"]["categoryV2"]["id"], "1154")
        self.assertEqual(item["listings"]["poshmark"]["overrides"]["categoryV2"]["id"], "posh1")
        self.assertEqual([r for r in out["unresolved"] if r["field"].startswith("category:")], [])

    def test_a_marketplace_the_mapper_skips_is_still_searched(self):
        """A partial mapping leaves the rest to the old path, not unresolved."""
        listing = {
            **LISTING,
            "category_path": "Clothing > Men > Jeans",
            "marketplace_categories": {
                "ebay": "Clothing > Men > Jeans",
                "poshmark": "Men > Jeans > Straight",
            },
        }
        replies = [
            {"ok": True, "results": [
                {"op": "category_search", "ok": True,
                 "leaf": {"id": "gen1", "is_leaf": True, "path": "Clothing > Men > Jeans"},
                 "matches": []},
            ]},
            {"ok": True, "results": [
                {"op": "category_search", "ok": True,
                 "leaf": {"id": "posh1", "is_leaf": True, "path": "Men > Jeans > Straight"},
                 "matches": []},
            ]},
            *self._replies(),
        ]
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {}, "item_count": 0}))
        fake = FakeBridge(replies, mapped={"ebay": {
            "id": "1154", "is_leaf": True, "all_category_label": ["Clothing", "Men", "Jeans"],
        }})
        with mock.patch.object(vendoo_create, "tree_leaf", return_value=None), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, listing, PHOTOS))

        # eBay came from the mapper, Poshmark from its own search.
        self.assertEqual([op["marketplace_id"] for op in every_op(fake, "category_search")], ["vendoo", "poshmark"])
        item = ops_for(fake, "create_item")[0]["item"]
        self.assertEqual(item["listings"]["ebay"]["overrides"]["categoryV2"]["id"], "1154")
        self.assertEqual(item["listings"]["poshmark"]["overrides"]["categoryV2"]["id"], "posh1")
        self.assertEqual([r for r in out["unresolved"] if r["field"].startswith("category:")], [])

    def test_a_marketplace_with_no_breadcrumb_is_mapped_anyway(self):
        """Generation need not pick a category per marketplace any more."""
        listing = {**LISTING, "category_path": "Clothing > Men > Jeans"}
        replies = [
            {"ok": True, "results": [
                {"op": "category_search", "ok": True,
                 "leaf": {"id": "gen1", "is_leaf": True, "path": "Clothing > Men > Jeans"},
                 "matches": []},
            ]},
            *self._replies(),
        ]
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {}, "item_count": 0}))
        fake = FakeBridge(replies, mapped={"ebay": {
            "id": "1154", "is_leaf": True, "all_category_label": ["Clothing", "Men", "Jeans"],
        }})
        with mock.patch.object(vendoo_create, "_mappable_marketplaces", return_value=("ebay", "etsy")), \
                mock.patch.object(vendoo_create, "tree_leaf", return_value=None), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, listing, PHOTOS))

        # Only the general tree is searched; eBay and Etsy are mapping targets.
        self.assertEqual([op["marketplace_id"] for op in every_op(fake, "category_search")], ["vendoo"])
        self.assertEqual(
            sorted(op["marketplace_id"] for op in every_op(fake, "category_map")), ["ebay", "etsy"]
        )
        item = ops_for(fake, "create_item")[0]["item"]
        self.assertEqual(item["listings"]["ebay"]["overrides"]["categoryV2"]["id"], "1154")
        # Etsy mapped to nothing and had no breadcrumb, so it is simply absent
        # rather than reported as something the seller must fix.
        self.assertNotIn("categoryV2", item["listings"]["etsy"]["overrides"])
        self.assertEqual([r for r in out["unresolved"] if r["field"].startswith("category:")], [])

    def test_falls_back_to_local_tree_when_search_finds_nothing(self):
        """Search runs first for ``extras``/``path``; the tree still covers a miss."""
        listing = {
            **LISTING,
            "category_path": "Clothing > Men > Jeans",
            "marketplace_categories": {"ebay": "Clothing > Men > Jeans"},
        }

        def fake_tree(marketplace, path):
            if marketplace == "general":
                return {"id": "slug_jeans", "is_leaf": True, "has_children": False,
                        "last_subcategory_label": "Jeans", "all_category_label": path.split(" > "),
                        "parent_category_id_path": ["slug_clothing", "slug_men"]}
            if marketplace == "ebay":
                return {"id": "1154", "is_leaf": True, "has_children": False,
                        "last_subcategory_label": "Jeans", "all_category_label": path.split(" > "),
                        "parent_category_id_path": ["11450", "1059"]}
            return None

        replies = [
            {"ok": True, "results": [
                {"op": "category_search", "ok": True, "leaf": None, "matches": []},
            ]},
            {"ok": True, "results": [
                {"op": "category_search", "ok": True, "leaf": None, "matches": []},
            ]},
            *self._replies(),
        ]
        Path(self.tmp.name, "schema.json").write_text(json.dumps({"fields": {}, "item_count": 0}))
        fake = FakeBridge(replies)
        with mock.patch.object(vendoo_create, "tree_leaf", side_effect=fake_tree), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out = run(create_item(JOB, listing, PHOTOS))
        self.assertEqual(out["item_id"], "NEWid1234567890abcde")
        self.assertEqual([op["marketplace_id"] for op in every_op(fake, "category_search")], ["vendoo", "ebay"])
        item = ops_for(fake, "create_item")[0]["item"]
        general = item["generalDetails"]["categoryV2"]
        self.assertEqual(general["id"], "slug_jeans")
        self.assertEqual(general["path"], ["slug_clothing", "slug_men", "slug_jeans"])
        ebay = item["listings"]["ebay"]["overrides"]["categoryV2"]
        self.assertEqual(ebay["id"], "1154")
        self.assertEqual(ebay["path"], ["11450", "1059", "1154"])
        self.assertEqual(ebay["displayName"], "Jeans")
        self.assertIs(ebay["isLeaf"], True)


class ResolveCategoriesTest(_NoExtraMapping):
    def test_asks_each_leaf_for_its_field_schema(self):
        """The fetch passes the leaf's ancestor chain and extras through.

        eBay resolves a category's fields from those two, so a request without
        them comes back empty and the encoding falls back to guesswork.
        """
        listing = {
            "marketplace_category_objects": {
                "general": {"id": "slug_tops"},
                "ebay": {
                    "id": "53159",
                    "path": ["11450", "260010", "53159"],
                    "extras": {"siteId": "0"},
                },
            }
        }
        fake = FakeBridge([], specifics=specifics_reply({
            "Season": {"id": "Season", "display": "Season", "options": {
                "0": {"id": "Spring", "display": "Spring"}},
                "rules": {"fieldOptions": {"minValues": 0, "maxValues": 100,
                                           "selectionMode": "SelectionOnly"}}},
        }))
        saved = []
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request), \
                mock.patch.object(category_fields, "load_fields", return_value=None), \
                mock.patch.object(category_fields, "save_fields",
                                  side_effect=lambda mp, cid, sp: saved.append((mp, cid, sp))):
            specs = run(vendoo_create.fetch_listing_specifics(JOB, listing))

        # One request, for the marketplace leaf only — general has no schema.
        self.assertEqual(len(fake.sent), 1)
        op = fake.sent[0][1]["ops"][0]
        self.assertEqual(op["op"], "category_specifics")
        self.assertEqual(op["marketplace_id"], "ebay")
        self.assertEqual(op["category_id"], "53159")
        self.assertEqual(op["path"], ["11450", "260010", "53159"])
        self.assertEqual(op["extras"], {"siteId": "0"})
        self.assertTrue(specs["ebay"]["Season"].multi)
        self.assertEqual(specs["ebay"]["Season"].options, {"Spring": "Spring"})
        # and what it fetched is cached so the next listing costs nothing
        self.assertEqual([(mp, cid) for mp, cid, _ in saved], [("ebay", "53159")])

    def test_a_cached_leaf_is_not_fetched_again(self):
        """The cache is the point: one round trip per category, ever."""
        listing = {"marketplace_category_objects": {"ebay": {"id": "53159"}}}
        cached = normalize_specifics({
            "Size": {"id": "Size", "display": "Size", "options": {},
                     "rules": {"fieldOptions": {"minValues": 1, "maxValues": 1,
                                                "selectionMode": "FreeText"}}},
        })
        fake = FakeBridge([])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request), \
                mock.patch.object(category_fields, "load_fields", return_value=cached):
            specs = run(vendoo_create.fetch_listing_specifics(JOB, listing))
        self.assertEqual(fake.sent, [])
        self.assertEqual(sorted(specs["ebay"]), ["Size"])

    def test_a_marketplace_without_a_schema_is_skipped(self):
        """Vendoo serves no schema for some marketplaces; that is not fatal."""
        listing = {"marketplace_category_objects": {"shopify": {"id": "9526"}}}
        fake = FakeBridge([], specifics={"ok": True, "results": [
            {"op": "category_specifics", "ok": False, "error": "400"},
        ]})
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request), \
                mock.patch.object(category_fields, "load_fields", return_value=None):
            self.assertEqual(run(vendoo_create.fetch_listing_specifics(JOB, listing)), {})

    def test_mercari_comes_from_its_static_file_not_the_bridge(self):
        """Mercari's only category field ships as a public asset."""
        listing = {"marketplace_category_objects": {"mercari": {"id": "12"}}}
        fake = FakeBridge([])
        size = normalize_specifics({
            "Size": {"id": "Size", "display": "Size",
                     "options": {"0": {"id": "4", "display": "M (8-10)"}},
                     "rules": {"fieldOptions": {"minValues": 0, "maxValues": 1,
                                                "selectionMode": "SelectionOnly"}}},
        })
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request), \
                mock.patch.object(category_fields, "load_fields", return_value=None), \
                mock.patch.object(category_fields, "save_fields"), \
                mock.patch.object(vendoo_create, "mercari_fields",
                                  new=mock.AsyncMock(return_value=size)) as fetch:
            specs = run(vendoo_create.fetch_listing_specifics(JOB, listing))
        self.assertEqual(fake.sent, [])
        fetch.assert_awaited_once_with("12")
        self.assertEqual(sorted(specs["mercari"]), ["Size"])

    def _blouse_listing(self):
        """A women's button-down: general says "Tops", Poshmark says "Blouses"."""
        return {
            "category_id": "gen_tops",
            "category_path": "Clothing > Women > Tops",
            "marketplace_categories": {"poshmark": "Women > Tops > Blouses"},
        }

    def test_the_marketplace_breadcrumb_decides_between_the_mapper_answers(self):
        """The general category says "Tops"; only the breadcrumb says which top.

        Scoring the mapper's answers against the general category alone lets it
        settle on whichever subtype it guessed first — a button-down filed under
        Tees — while the leaf the listing asked for sits in the alternates.
        """
        fake = FakeBridge(
            [],
            mapped={"poshmark": {"id": "posh_tee", "is_leaf": True,
                                 "all_category_label": ["Women", "Tops", "Tees - Short Sleeve"]}},
            recommended={"poshmark": [{"id": "posh_blouse", "is_leaf": True,
                                       "all_category_label": ["Women", "Tops", "Blouses"]}]},
        )
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out, unresolved = run(resolve_listing_categories(JOB, self._blouse_listing()))

        self.assertEqual(out["marketplace_category_ids"]["poshmark"], "posh_blouse")
        self.assertEqual(out["poshmark_specifics"]["categoryPath"], ["Women", "Tops", "Blouses"])
        self.assertEqual(unresolved, [])
        # The mapper answered, so nothing had to be searched for.
        self.assertEqual(every_op(fake, "category_search"), [])

    def test_a_mapped_leaf_that_contradicts_the_breadcrumb_is_searched_for(self):
        """With no alternate to pick, the breadcrumb is still worth a search."""
        fake = FakeBridge(
            [{"ok": True, "results": [
                {"op": "category_search", "ok": True,
                 "leaf": {"id": "posh_blouse", "is_leaf": True, "path": "Women > Tops > Blouses"},
                 "matches": []},
            ]}],
            mapped={"poshmark": {"id": "posh_tee", "is_leaf": True,
                                 "all_category_label": ["Women", "Tops", "Tees - Short Sleeve"]}},
        )
        with mock.patch.object(vendoo_create, "tree_leaf", return_value=None), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out, unresolved = run(resolve_listing_categories(JOB, self._blouse_listing()))

        self.assertEqual([op["text"] for op in every_op(fake, "category_search")],
                         ["Women > Tops > Blouses"])
        self.assertEqual(out["marketplace_category_ids"]["poshmark"], "posh_blouse")
        self.assertEqual(unresolved, [])

    def test_the_mapped_leaf_stands_when_the_breadcrumb_finds_nothing(self):
        """A category Vendoo cannot find beats no category: the form locks without one."""
        fake = FakeBridge(
            [{"ok": True, "results": [{"op": "category_search", "ok": False, "error": "404"}]}],
            mapped={"poshmark": {"id": "posh_tee", "is_leaf": True,
                                 "all_category_label": ["Women", "Tops", "Tees - Short Sleeve"]}},
        )
        with mock.patch.object(vendoo_create, "tree_leaf", return_value=None), \
                mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out, unresolved = run(resolve_listing_categories(JOB, self._blouse_listing()))

        self.assertEqual(out["marketplace_category_ids"]["poshmark"], "posh_tee")
        self.assertEqual(unresolved, [])

    def test_a_poshmark_breadcrumb_is_mapped_onto_a_real_leaf_first(self):
        """Poshmark has no "Women's Clothing > Tops"; resolving that finds nothing."""
        listing = {
            "category_id": "gen_tops",
            "category_path": "Clothing > Women > Tops",
            "title": "REAL Comfort XL Minimalist Button-Down Brown Oversized",
            "marketplace_categories": {"poshmark": "Women's Clothing > Tops"},
        }
        fake = FakeBridge(
            [],
            mapped={"poshmark": {"id": "posh_blouse", "is_leaf": True,
                                 "all_category_label": ["Women", "Tops", "Blouses"]}},
        )
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out, _unresolved = run(resolve_listing_categories(JOB, listing))

        # Mapped to Blouses before anything resolved, so the mapper's own
        # Blouses answer agrees with it and no search is needed.
        self.assertEqual(out["marketplace_category_ids"]["poshmark"], "posh_blouse")
        self.assertEqual(every_op(fake, "category_search"), [])

    def test_skips_when_already_resolved(self):
        listing = {"category_path": "A > B", "category_id": "already"}
        fake = FakeBridge([])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            out, unresolved = run(resolve_listing_categories(JOB, listing))
        self.assertEqual(out["category_id"], "already")
        self.assertEqual(unresolved, [])
        self.assertEqual(fake.sent, [])


if __name__ == "__main__":
    unittest.main()


class ResolveLabelsTest(unittest.TestCase):
    def test_no_labels_sends_nothing(self):
        fake = FakeBridge([])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            listing, unresolved = run(resolve_listing_labels(JOB, dict(LISTING)))
        self.assertEqual(fake.sent, [])
        self.assertEqual(unresolved, [])
        self.assertNotIn("labels", listing)

    def test_an_extension_that_cannot_resolve_drops_the_names(self):
        """A name would be saved but never shown, so report it instead."""
        failed = {"ok": False, "results": [
            {"op": "resolve_labels", "ok": False, "error": "Unknown Vendoo API op: resolve_labels"},
        ]}
        fake = FakeBridge([failed])
        with mock.patch.object(vendoo_create.browser_bridge, "request", fake.request):
            listing, unresolved = run(resolve_listing_labels(JOB, {**LISTING, "labels": ["To List", "Bin 4"]}))
        self.assertEqual(listing["labels"], [])
        self.assertEqual(unresolved, [{"field": "labels", "value": "To List, Bin 4"}])
