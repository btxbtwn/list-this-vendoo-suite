import gzip
import json
import tempfile
import unittest
from pathlib import Path

from vendoo_studio.services.category_tree import MARKETPLACES
from vendoo_studio.services.category_tree_seed import (
    ensure_seeded_category_trees,
    export_seed,
    import_seed,
    trees_complete,
)


class CategoryTreeSeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.db"
        self.target = self.root / "target.db"
        self.seed = self.root / "seed.json.gz"
        import sqlite3

        con = sqlite3.connect(self.source)
        con.executescript(
            """
            CREATE TABLE category_trees (
                marketplace VARCHAR NOT NULL PRIMARY KEY,
                roots_loaded BOOLEAN NOT NULL,
                status VARCHAR NOT NULL,
                error VARCHAR,
                source VARCHAR,
                updated_at DATETIME
            );
            CREATE TABLE category_tree_nodes (
                marketplace VARCHAR NOT NULL,
                category_id VARCHAR NOT NULL,
                parent_id VARCHAR NOT NULL,
                path VARCHAR NOT NULL,
                label VARCHAR NOT NULL,
                is_leaf BOOLEAN NOT NULL,
                has_children BOOLEAN NOT NULL,
                children_loaded BOOLEAN NOT NULL,
                PRIMARY KEY (marketplace, category_id)
            );
            """
        )
        for marketplace in MARKETPLACES:
            con.execute(
                "INSERT INTO category_trees VALUES (?, 1, 'complete', NULL, 'seed-test', '2026-01-01')",
                (marketplace,),
            )
            con.execute(
                "INSERT INTO category_tree_nodes VALUES (?, ?, '__root', ?, ?, 1, 0, 1)",
                (marketplace, f"{marketplace}-root", marketplace.title(), marketplace.title()),
            )
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_requires_complete_trees(self):
        import sqlite3

        con = sqlite3.connect(self.source)
        con.execute("UPDATE category_trees SET status='paused' WHERE marketplace='ebay'")
        con.commit()
        con.close()
        with self.assertRaisesRegex(RuntimeError, "Incomplete marketplaces: ebay"):
            export_seed(self.source, self.seed)

    def test_round_trip_replaces_trees_and_marks_complete(self):
        result = export_seed(self.source, self.seed)
        self.assertEqual(result["nodes"], len(MARKETPLACES))
        self.assertTrue(self.seed.is_file())
        payload = json.loads(gzip.decompress(self.seed.read_bytes()))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(set(payload["node_counts"]), set(MARKETPLACES))

        import sqlite3

        con = sqlite3.connect(self.target)
        con.execute(
            "CREATE TABLE category_trees (marketplace VARCHAR PRIMARY KEY, roots_loaded BOOLEAN, "
            "status VARCHAR, error VARCHAR, source VARCHAR, updated_at DATETIME)"
        )
        con.execute(
            "CREATE TABLE category_tree_nodes (marketplace VARCHAR, category_id VARCHAR, "
            "parent_id VARCHAR, path VARCHAR, label VARCHAR, is_leaf BOOLEAN, "
            "has_children BOOLEAN, children_loaded BOOLEAN, PRIMARY KEY (marketplace, category_id))"
        )
        con.execute(
            "INSERT INTO category_trees VALUES ('ebay', 0, 'pending', 'old', NULL, NULL)"
        )
        con.execute(
            "INSERT INTO category_tree_nodes VALUES ('ebay', 'stale', '__root', 'Stale', 'Stale', 1, 0, 1)"
        )
        con.commit()
        con.close()

        imported = import_seed(self.target, self.seed)
        self.assertTrue(all(status == "complete" for status in imported["statuses"].values()))
        self.assertEqual(imported["node_counts"]["ebay"], 1)

        con = sqlite3.connect(self.target)
        stale = con.execute(
            "SELECT COUNT(*) FROM category_tree_nodes WHERE category_id='stale'"
        ).fetchone()[0]
        self.assertEqual(stale, 0)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM category_trees").fetchone()[0],
            len(MARKETPLACES),
        )
        con.close()

    def test_ensure_imports_when_incomplete_and_skips_when_complete(self):
        export_seed(self.source, self.seed)
        self.assertIsNone(ensure_seeded_category_trees(self.source, self.seed))
        self.assertTrue(trees_complete(self.source))

        result = ensure_seeded_category_trees(self.target, self.seed)
        self.assertIsNotNone(result)
        self.assertTrue(trees_complete(self.target))
        self.assertIsNone(ensure_seeded_category_trees(self.target, self.seed))


if __name__ == "__main__":
    unittest.main()
