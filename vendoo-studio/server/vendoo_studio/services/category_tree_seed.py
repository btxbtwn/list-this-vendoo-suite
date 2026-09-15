"""Export and import the six marketplace category trees (no listings or secrets)."""
from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from vendoo_studio.services.category_tree import MARKETPLACES

SEED_VERSION = 1
SEED_NAME = "category-trees-seed.json.gz"
PACKAGED_DB = Path.home() / "Library" / "Application Support" / "List This Studio" / "vendoo_studio.db"

_CREATE_TREES = """
CREATE TABLE IF NOT EXISTS category_trees (
    marketplace VARCHAR NOT NULL PRIMARY KEY,
    roots_loaded BOOLEAN NOT NULL,
    status VARCHAR NOT NULL,
    error VARCHAR,
    source VARCHAR,
    updated_at DATETIME
)
"""
_CREATE_NODES = """
CREATE TABLE IF NOT EXISTS category_tree_nodes (
    marketplace VARCHAR NOT NULL,
    category_id VARCHAR NOT NULL,
    parent_id VARCHAR NOT NULL,
    path VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    is_leaf BOOLEAN NOT NULL,
    has_children BOOLEAN NOT NULL,
    children_loaded BOOLEAN NOT NULL,
    PRIMARY KEY (marketplace, category_id)
)
"""


def default_seed_path() -> Path:
    from vendoo_studio.config import resource_root

    bundled = resource_root() / "data" / SEED_NAME
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[3] / "data" / SEED_NAME


def default_db_path() -> Path:
    """Packaged Mac app DB path (CLI default)."""
    return PACKAGED_DB


def active_db_path() -> Path:
    from vendoo_studio.config import DATABASE_PATH

    return Path(DATABASE_PATH)


def trees_complete(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    con = sqlite3.connect(db_path)
    try:
        names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "category_trees" not in names:
            return False
        rows = {
            marketplace: status
            for marketplace, status in con.execute(
                "SELECT marketplace, status FROM category_trees WHERE marketplace IN ({})".format(
                    ",".join("?" * len(MARKETPLACES))
                ),
                MARKETPLACES,
            )
        }
        return all(rows.get(marketplace) == "complete" for marketplace in MARKETPLACES)
    finally:
        con.close()


def ensure_seeded_category_trees(
    db_path: Path | None = None,
    seed_path: Path | None = None,
) -> dict | None:
    """Import the bundled seed when any of the six trees is missing or incomplete."""
    db = db_path or active_db_path()
    if trees_complete(db):
        return None
    seed = seed_path or default_seed_path()
    if not seed.is_file():
        return None
    return import_seed(db, seed)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _read_seed(path: Path) -> dict:
    raw = path.read_bytes()
    if path.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("version") != SEED_VERSION:
        raise ValueError(f"Unsupported seed version: {payload.get('version')!r}")
    trees = payload.get("category_trees")
    nodes = payload.get("category_tree_nodes")
    if not isinstance(trees, list) or not isinstance(nodes, list):
        raise ValueError("Seed must include category_trees and category_tree_nodes lists")
    return payload


def export_seed(db_path: Path, seed_path: Path) -> dict:
    """Write only category_trees + category_tree_nodes for the six marketplaces."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "category_trees" not in names or "category_tree_nodes" not in names:
            raise RuntimeError(f"{db_path} has no category tree tables")
        placeholders = ",".join("?" * len(MARKETPLACES))
        trees = []
        for row in con.execute(
            f"SELECT marketplace, roots_loaded, status, error, source, updated_at "
            f"FROM category_trees WHERE marketplace IN ({placeholders}) ORDER BY marketplace",
            MARKETPLACES,
        ):
            item = dict(row)
            item["roots_loaded"] = bool(item["roots_loaded"])
            trees.append(item)
        found = {tree["marketplace"] for tree in trees}
        missing = [mp for mp in MARKETPLACES if mp not in found]
        if missing:
            raise RuntimeError("Missing marketplaces in category_trees: " + ", ".join(missing))
        incomplete = [tree["marketplace"] for tree in trees if tree["status"] != "complete"]
        if incomplete:
            raise RuntimeError("Incomplete marketplaces: " + ", ".join(incomplete))
        nodes = []
        for row in con.execute(
            f"SELECT marketplace, category_id, parent_id, path, label, is_leaf, has_children, children_loaded "
            f"FROM category_tree_nodes WHERE marketplace IN ({placeholders}) "
            f"ORDER BY marketplace, path",
            MARKETPLACES,
        ):
            item = dict(row)
            for key in ("is_leaf", "has_children", "children_loaded"):
                item[key] = bool(item[key])
            nodes.append(item)
        counts = {mp: 0 for mp in MARKETPLACES}
        for node in nodes:
            counts[node["marketplace"]] += 1
        empty = [mp for mp, count in counts.items() if count == 0]
        if empty:
            raise RuntimeError("Marketplaces with zero nodes: " + ", ".join(empty))
        payload = {
            "version": SEED_VERSION,
            "marketplaces": list(MARKETPLACES),
            "exported_at": _utcnow(),
            "node_counts": counts,
            "category_trees": trees,
            "category_tree_nodes": nodes,
        }
    finally:
        con.close()

    seed_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if seed_path.suffix == ".gz" or str(seed_path).endswith(".json.gz"):
        seed_path.write_bytes(gzip.compress(body, compresslevel=9))
    else:
        seed_path.write_bytes(body)
    return {"seed": str(seed_path), "node_counts": counts, "nodes": len(nodes)}


def import_seed(db_path: Path, seed_path: Path | None = None) -> dict:
    """Replace category_trees / category_tree_nodes and mark all six marketplaces complete."""
    seed_path = seed_path or default_seed_path()
    if not seed_path.is_file():
        raise FileNotFoundError(f"Seed not found: {seed_path}")
    payload = _read_seed(seed_path)
    trees = payload["category_trees"]
    nodes = payload["category_tree_nodes"]
    by_marketplace = {tree["marketplace"]: tree for tree in trees}
    missing = [mp for mp in MARKETPLACES if mp not in by_marketplace]
    if missing:
        raise RuntimeError("Seed missing marketplaces: " + ", ".join(missing))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(_CREATE_TREES)
        con.execute(_CREATE_NODES)
        con.execute("DELETE FROM category_tree_nodes")
        con.execute("DELETE FROM category_trees")
        now = _utcnow()
        for marketplace in MARKETPLACES:
            tree = by_marketplace[marketplace]
            con.execute(
                "INSERT INTO category_trees "
                "(marketplace, roots_loaded, status, error, source, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    marketplace,
                    1 if tree.get("roots_loaded", True) else 0,
                    "complete",
                    None,
                    tree.get("source"),
                    tree.get("updated_at") or now,
                ),
            )
        con.executemany(
            "INSERT INTO category_tree_nodes "
            "(marketplace, category_id, parent_id, path, label, is_leaf, has_children, children_loaded) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    node["marketplace"],
                    node["category_id"],
                    node["parent_id"],
                    node["path"],
                    node["label"],
                    1 if node["is_leaf"] else 0,
                    1 if node["has_children"] else 0,
                    1 if node.get("children_loaded", True) else 0,
                )
                for node in nodes
                if node["marketplace"] in MARKETPLACES
            ],
        )
        con.commit()
        counts = {
            mp: con.execute(
                "SELECT COUNT(*) FROM category_tree_nodes WHERE marketplace = ?", (mp,)
            ).fetchone()[0]
            for mp in MARKETPLACES
        }
        statuses = {
            mp: con.execute(
                "SELECT status FROM category_trees WHERE marketplace = ?", (mp,)
            ).fetchone()[0]
            for mp in MARKETPLACES
        }
    finally:
        con.close()

    incomplete = [mp for mp, status in statuses.items() if status != "complete"]
    if incomplete:
        raise RuntimeError("Import left incomplete marketplaces: " + ", ".join(incomplete))
    return {"db": str(db_path), "seed": str(seed_path), "node_counts": counts, "statuses": statuses}
