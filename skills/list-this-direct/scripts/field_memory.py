#!/usr/bin/env python3
"""
Persistent field-memory helper for list-this-direct.

Builds a seed from the current markdown references, initializes a local SQLite
database, looks up known field options/patterns, and merges post-run
field_memory_delta JSON artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
DATA_DIR = SKILL_DIR / "data"
SCHEMA_PATH = DATA_DIR / "field_memory_schema.sql"
SEED_PATH = DATA_DIR / "field_memory_seed.json"
DEFAULT_DB_PATH = DATA_DIR / "field_memory.sqlite3"
LIST_THIS_PATH = SKILL_DIR.parent / "list-this" / "SKILL.md"
TEMPLATE_PATH = SKILL_DIR.parent / "list-this" / "references" / "vendoo_listing_template.md"
STALE_AFTER_DAYS = 45
SEED_VERSION = 3

OPTION_SECTION_MAP = {
    "eBay optional fields - value lists": "ebay",
    "Etsy optional fields - value lists": "etsy",
    "Poshmark style tags - master list": "poshmark",
    "Depop tags + style + parcel sizes": "depop",
}

FIELD_GROUP_MAP = {
    "**Main Vendoo Fields:**": "vendoo",
    "**eBay Specifics:**": "ebay",
    "**Etsy Specifics:**": "etsy",
    "**Poshmark Specifics:**": "poshmark",
    "**Depop Specifics:**": "depop",
}

SINGLE_VALUE_LABELS = {
    "category",
    "location",
    "shipping",
    "qty",
    "unit quantity",
    "unit type",
    "mpn",
    "upc",
    "size",
    "ship from zip",
    "delivery method",
}

SEEDED_PATTERNS = [
    {
        "platform": "vendoo",
        "context_key": "global",
        "field_key": "condition",
        "field_label": "Condition",
        "pattern_key": "visible-option-commit",
        "pattern_kind": "interaction",
        "pattern_text": "Type or set the candidate value, wait for visible options, click the matching option row, then verify the field visibly changed.",
    },
    {
        "platform": "vendoo",
        "context_key": "global",
        "field_key": "primaryColor",
        "field_label": "Primary Color",
        "pattern_key": "visible-option-commit",
        "pattern_kind": "interaction",
        "pattern_text": "Treat color fields as commit-required selects and verify the visible option rendered before saving.",
    },
    {
        "platform": "vendoo",
        "context_key": "global",
        "field_key": "secondaryColor",
        "field_label": "Secondary Color",
        "pattern_key": "visible-option-commit",
        "pattern_kind": "interaction",
        "pattern_text": "Treat color fields as commit-required selects and verify the visible option rendered before saving.",
    },
    {
        "platform": "vendoo",
        "context_key": "global",
        "field_key": "category_path",
        "field_label": "Category",
        "pattern_key": "hierarchy-click-through",
        "pattern_kind": "interaction",
        "pattern_text": "Open the category picker, click through the visible hierarchy, verify the final path renders, and close the picker before save.",
    },
    {
        "platform": "vendoo",
        "context_key": "global",
        "field_key": "tags",
        "field_label": "Tags",
        "pattern_key": "token-one-at-a-time",
        "pattern_kind": "interaction",
        "pattern_text": "Enter one tag at a time and press Enter after each tag. Do not bulk-insert comma-separated tokens.",
    },
    {
        "platform": "ebay",
        "context_key": "global",
        "field_key": "optionalFields",
        "field_label": "Optional Fields",
        "pattern_key": "show-optional-first",
        "pattern_kind": "interaction",
        "pattern_text": "Click Show Optional Fields as soon as the form is ready, wait until the section is visibly expanded, then fill supported optional fields before save.",
    },
    {
        "platform": "etsy",
        "context_key": "global",
        "field_key": "materials",
        "field_label": "Materials",
        "pattern_key": "strict-pointer-flow",
        "pattern_kind": "interaction",
        "pattern_text": "Click the field, wait for the option list, click the real option row, then verify the chosen value renders in the field.",
    },
    {
        "platform": "depop",
        "context_key": "global",
        "field_key": "optionalFields",
        "field_label": "Optional Fields",
        "pattern_key": "expand-and-verify",
        "pattern_kind": "interaction",
        "pattern_text": "Expand optional fields, fill supported values, and verify commit-required selects visibly changed before save.",
    },
]

SEEDED_PREFERENCES = [
    {
        "platform": "depop",
        "context_key": "global",
        "field_key": "brand",
        "field_label": "Brand",
        "preference_kind": "fallback",
        "value_text": "Other",
        "reason": "Use when the actual brand is unavailable in the live Depop brand list.",
    },
    {
        "platform": "vendoo",
        "context_key": "global",
        "field_key": "package_dimensions_in",
        "field_label": "Package Dimensions",
        "preference_kind": "preferred",
        "value_text": "13x10x3",
        "reason": "Default packaging rule unless the user explicitly overrides it.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def portable_path(path: Path) -> str:
    return Path(os.path.relpath(path, SKILL_DIR)).as_posix()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = clean_text(value)
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_stale(value: str | None) -> bool:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return False
    age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
    return age.days >= STALE_AFTER_DAYS


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def humanize_field_name(field_name: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field_name)
    value = value.replace("_", " ")
    return " ".join(part.capitalize() if not part.isupper() else part for part in value.split())


def slugify(value: str | None) -> str:
    cleaned = clean_text(value)
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", cleaned)
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", cleaned)
    cleaned = cleaned.strip("-").lower()
    return cleaned or "unknown"


def normalize_option(value: str) -> str:
    return slugify(value)


def merge_unique_text(existing: str | None, incoming: str | None) -> str | None:
    parts = []
    for item in (existing, incoming):
        for part in clean_text(item).split(" | "):
            if part and part not in parts:
                parts.append(part)
    return " | ".join(parts) if parts else None


def split_text_parts(value: str | None) -> list[str]:
    parts = []
    for part in clean_text(value).split(" | "):
        if part and part not in parts:
            parts.append(part)
    return parts


def infer_widget_type(field_key: str | None, field_label: str | None, has_options: bool = False) -> str:
    raw = f"{field_key or ''} {field_label or ''}".lower()
    if "optional fields" in raw:
        return "button"
    if any(token in raw for token in ("description", "notes")):
        return "textarea"
    if any(token in raw for token in ("title", "price", "cost", "zip", "weight", "dimensions", "quantity")):
        return "text"
    if any(token in raw for token in ("tags", "materials", "style tags")):
        return "token_input"
    if has_options or any(
        token in raw
        for token in (
            "category",
            "condition",
            "color",
            "size",
            "brand",
            "shipping",
            "carrier",
            "age",
            "source",
            "style",
            "occasion",
            "fit",
            "material",
            "pattern",
            "theme",
            "closure",
            "fabric",
            "season",
            "parcel",
            "who made",
            "what is",
            "when made",
        )
    ):
        return "select"
    return "unknown"


def split_field_segments(content: str) -> list[str]:
    segments = [segment.strip() for segment in content.split(";") if segment.strip()]
    if len(segments) > 1 and all(":" in segment for segment in segments):
        return segments
    return [content]


def parse_option_values(label: str, raw_values: str) -> list[str]:
    values = clean_text(raw_values).strip()
    label_slug = slugify(label).replace("-", " ")
    if not values:
        return []
    if values.startswith("(") and values.endswith(")"):
        values = values[1:-1].strip()

    lower = values.lower()
    quoted = re.findall(r'["“]([^"”]+)["”]', values)
    if "from list or" in lower and quoted:
        return quoted
    if lower in {"from list", "exact", "required", "blank"}:
        return []
    if label_slug in SINGLE_VALUE_LABELS:
        return [values]
    if re.fullmatch(r"yes\s*/\s*no", values, flags=re.IGNORECASE):
        return ["Yes", "No"]
    if ";" in values:
        parts = [part.strip() for part in values.split(";")]
    elif ", " in values:
        parts = [part.strip() for part in values.split(",")]
    else:
        return [values]
    cleaned = []
    for part in parts:
        part = clean_text(part).strip("() ")
        if part and part not in cleaned:
            cleaned.append(part)
    return cleaned


def ensure_entry(
    seed_entries: dict[tuple[str, str, str], dict[str, Any]],
    platform: str,
    context_key: str = "global",
    field_key: str | None = None,
    field_label: str | None = None,
    widget_type: str | None = None,
    source_path: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    field_slug = slugify(field_key or field_label)
    key = (platform, context_key, field_slug)
    entry = seed_entries.get(key)
    if entry is None:
        entry = {
            "platform": platform,
            "context_key": context_key,
            "field_slug": field_slug,
            "field_key": field_key,
            "field_label": field_label or humanize_field_name(field_key or field_slug),
            "widget_type": widget_type or infer_widget_type(field_key, field_label),
            "sources": [],
            "notes": [],
            "options": [],
            "patterns": [],
            "preferences": [],
        }
        seed_entries[key] = entry
    if field_key and not entry["field_key"]:
        entry["field_key"] = field_key
    if field_label and not entry["field_label"]:
        entry["field_label"] = field_label
    if widget_type and entry["widget_type"] == "unknown":
        entry["widget_type"] = widget_type
    if source_path and source_path not in entry["sources"]:
        entry["sources"].append(source_path)
    if note and note not in entry["notes"]:
        entry["notes"].append(note)
    return entry


def add_option(entry: dict[str, Any], value: str) -> None:
    option_value = clean_text(value)
    if not option_value:
        return
    normalized = normalize_option(option_value)
    if not any(option["option_normalized"] == normalized for option in entry["options"]):
        entry["options"].append(
            {
                "option_value": option_value,
                "option_normalized": normalized,
            }
        )


def add_pattern(entry: dict[str, Any], pattern_key: str, pattern_kind: str, pattern_text: str) -> None:
    normalized_key = slugify(pattern_key)
    if any(
        pattern["pattern_key"] == normalized_key and pattern["pattern_kind"] == pattern_kind
        for pattern in entry["patterns"]
    ):
        return
    entry["patterns"].append(
        {
            "pattern_key": normalized_key,
            "pattern_kind": pattern_kind,
            "pattern_text": clean_text(pattern_text),
        }
    )


def add_preference(
    entry: dict[str, Any],
    preference_kind: str,
    value_text: str,
    reason: str | None = None,
) -> None:
    value = clean_text(value_text)
    if not value:
        return
    if any(
        preference["preference_kind"] == preference_kind and preference["value_text"] == value
        for preference in entry["preferences"]
    ):
        return
    entry["preferences"].append(
        {
            "preference_kind": preference_kind,
            "value_text": value,
            "reason": clean_text(reason) or None,
        }
    )


def parse_template_fields(seed_entries: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    lines = TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
    current_platform = None
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped in FIELD_GROUP_MAP:
            current_platform = FIELD_GROUP_MAP[stripped]
            continue
        if stripped.startswith("**") and stripped.endswith("**") and stripped not in FIELD_GROUP_MAP:
            current_platform = None
            continue
        if current_platform and stripped.startswith("- "):
            field_keys = re.findall(r"`([^`]+)`", stripped)
            for field_key in field_keys:
                ensure_entry(
                    seed_entries,
                    platform=current_platform,
                    field_key=field_key,
                    field_label=humanize_field_name(field_key),
                    source_path=f"{TEMPLATE_PATH.name}:{line_number}",
                )


def parse_option_sections(seed_entries: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    lines = TEMPLATE_PATH.read_text(encoding="utf-8").splitlines()
    current_platform = None
    parcel_mode = False
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("### "):
            current_platform = OPTION_SECTION_MAP.get(stripped[4:].strip())
            parcel_mode = False
            continue
        if not current_platform or not stripped.startswith("* "):
            continue

        content = clean_text(stripped[2:])
        lower = content.lower()
        if "show optional fields" in lower:
            ensure_entry(
                seed_entries,
                platform=current_platform,
                field_key="optionalFields",
                field_label="Optional Fields",
                widget_type="button",
                source_path=f"{TEMPLATE_PATH.name}:{line_number}",
                note=content,
            )
            continue
        if current_platform == "depop" and lower.startswith("depop parcel sizes"):
            parcel_mode = True
            ensure_entry(
                seed_entries,
                platform=current_platform,
                field_key="parcelSize",
                field_label="Parcel Size",
                widget_type="select",
                source_path=f"{TEMPLATE_PATH.name}:{line_number}",
            )
            continue
        if parcel_mode and ":" in content and lower.startswith(
            ("extra extra small", "extra small", "small", "medium", "large", "extra large")
        ):
            entry = ensure_entry(
                seed_entries,
                platform=current_platform,
                field_key="parcelSize",
                field_label="Parcel Size",
                widget_type="select",
                source_path=f"{TEMPLATE_PATH.name}:{line_number}",
            )
            add_option(entry, content)
            continue

        for segment in split_field_segments(content):
            if ":" not in segment:
                continue
            label, raw_values = [part.strip() for part in segment.split(":", 1)]
            label = re.sub(r"\s*\([^)]*\)", "", label).strip()
            if not label:
                continue

            field_key = None
            if current_platform == "depop" and slugify(label) == "shipping":
                field_key = "shippingMethod"
            elif current_platform == "depop" and slugify(label) == "style-tags":
                field_key = "styleTags"

            entry = ensure_entry(
                seed_entries,
                platform=current_platform,
                field_key=field_key,
                field_label=label,
                source_path=f"{TEMPLATE_PATH.name}:{line_number}",
            )
            options = parse_option_values(label, raw_values)
            if options:
                for option in options:
                    add_option(entry, option)
                entry["widget_type"] = infer_widget_type(entry["field_key"], entry["field_label"], has_options=True)
            else:
                note = clean_text(raw_values)
                if note:
                    entry["notes"].append(note)


def apply_seed_patterns(seed_entries: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    for item in SEEDED_PATTERNS:
        entry = ensure_entry(
            seed_entries,
            platform=item["platform"],
            context_key=item["context_key"],
            field_key=item["field_key"],
            field_label=item["field_label"],
            source_path="seeded-patterns",
        )
        add_pattern(
            entry,
            pattern_key=item["pattern_key"],
            pattern_kind=item["pattern_kind"],
            pattern_text=item["pattern_text"],
        )


def apply_seed_preferences(seed_entries: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    for item in SEEDED_PREFERENCES:
        entry = ensure_entry(
            seed_entries,
            platform=item["platform"],
            context_key=item["context_key"],
            field_key=item["field_key"],
            field_label=item["field_label"],
            source_path="seeded-preferences",
        )
        add_preference(
            entry,
            preference_kind=item["preference_kind"],
            value_text=item["value_text"],
            reason=item["reason"],
        )


def build_seed_data() -> dict[str, Any]:
    seed_entries: dict[tuple[str, str, str], dict[str, Any]] = {}
    parse_template_fields(seed_entries)
    parse_option_sections(seed_entries)
    apply_seed_patterns(seed_entries)
    apply_seed_preferences(seed_entries)

    serialized_entries = []
    for entry in sorted(
        seed_entries.values(),
        key=lambda item: (item["platform"], item["context_key"], item["field_slug"]),
    ):
        serialized_entries.append(
            {
                "platform": entry["platform"],
                "context_key": entry["context_key"],
                "field_slug": entry["field_slug"],
                "field_key": entry["field_key"],
                "field_label": entry["field_label"],
                "widget_type": entry["widget_type"],
                "sources": sorted(entry["sources"]),
                "notes": sorted(set(clean_text(note) for note in entry["notes"] if clean_text(note))),
                "options": sorted(entry["options"], key=lambda item: item["option_value"]),
                "patterns": sorted(
                    entry["patterns"],
                    key=lambda item: (item["pattern_kind"], item["pattern_key"]),
                ),
                "preferences": sorted(
                    entry["preferences"],
                    key=lambda item: (item["preference_kind"], item["value_text"]),
                ),
            }
        )

    return {
        "seed_version": SEED_VERSION,
        "generated_at": utc_now(),
        "source_files": [portable_path(LIST_THIS_PATH), portable_path(TEMPLATE_PATH)],
        "entries": serialized_entries,
    }


def write_seed_file(output_path: Path) -> dict[str, Any]:
    seed_data = build_seed_data()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(seed_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return seed_data


def load_seed_file(seed_path: Path) -> dict[str, Any]:
    return json.loads(seed_path.read_text(encoding="utf-8"))


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(db_path: Path, seed_data: dict[str, Any], force: bool = False) -> sqlite3.Connection:
    if force and db_path.exists():
        db_path.unlink()
    connection = connect(db_path)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    seed_database(connection, seed_data)
    connection.commit()
    return connection


def get_entry_row(
    connection: sqlite3.Connection,
    platform: str,
    context_key: str,
    field_slug: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM field_entries
        WHERE platform = ? AND context_key = ? AND field_slug = ?
        """,
        (platform, context_key, field_slug),
    ).fetchone()


def upsert_entry_record(
    connection: sqlite3.Connection,
    *,
    platform: str,
    context_key: str,
    field_slug: str,
    field_key: str | None,
    field_label: str | None,
    widget_type: str | None,
    source: str,
    notes: str | None,
    seen_at: str,
) -> int:
    existing = get_entry_row(connection, platform, context_key, field_slug)
    if existing is None:
        cursor = connection.execute(
            """
            INSERT INTO field_entries (
              platform,
              context_key,
              field_slug,
              field_key,
              field_label,
              widget_type,
              source_scope,
              source,
              notes,
              first_seen_at,
              last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'global', ?, ?, ?, ?)
            """,
            (
                platform,
                context_key,
                field_slug,
                field_key,
                field_label,
                widget_type or infer_widget_type(field_key, field_label),
                source,
                notes,
                seen_at,
                seen_at,
            ),
        )
        return int(cursor.lastrowid)

    merged_notes = merge_unique_text(existing["notes"], notes)
    merged_source = merge_unique_text(existing["source"], source)
    connection.execute(
        """
        UPDATE field_entries
        SET field_key = COALESCE(field_key, ?),
            field_label = COALESCE(field_label, ?),
            widget_type = CASE
              WHEN widget_type = 'unknown' AND ? IS NOT NULL AND ? != 'unknown' THEN ?
              ELSE widget_type
            END,
            source = ?,
            notes = ?,
            last_seen_at = ?
        WHERE id = ?
        """,
        (
            field_key,
            field_label,
            widget_type,
            widget_type,
            widget_type,
            merged_source,
            merged_notes,
            seen_at,
            existing["id"],
        ),
    )
    return int(existing["id"])


def upsert_option_record(
    connection: sqlite3.Connection,
    *,
    entry_id: int,
    option_value: str,
    source: str,
    seen_at: str,
    observed_delta: int = 0,
    commit_delta: int = 0,
    reject_delta: int = 0,
    is_seeded: int = 0,
) -> None:
    normalized = normalize_option(option_value)
    existing = connection.execute(
        """
        SELECT *
        FROM field_options
        WHERE entry_id = ? AND option_normalized = ?
        """,
        (entry_id, normalized),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO field_options (
              entry_id,
              option_value,
              option_normalized,
              source,
              first_seen_at,
              last_seen_at,
              observed_count,
              commit_count,
              reject_count,
              is_seeded
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                option_value,
                normalized,
                source,
                seen_at,
                seen_at,
                observed_delta,
                commit_delta,
                reject_delta,
                is_seeded,
            ),
        )
        return

    merged_source = merge_unique_text(existing["source"], source)
    connection.execute(
        """
        UPDATE field_options
        SET option_value = ?,
            source = ?,
            last_seen_at = ?,
            observed_count = observed_count + ?,
            commit_count = commit_count + ?,
            reject_count = reject_count + ?,
            is_seeded = CASE WHEN is_seeded = 1 OR ? = 1 THEN 1 ELSE 0 END
        WHERE id = ?
        """,
        (
            option_value,
            merged_source,
            seen_at,
            observed_delta,
            commit_delta,
            reject_delta,
            is_seeded,
            existing["id"],
        ),
    )


def upsert_pattern_record(
    connection: sqlite3.Connection,
    *,
    entry_id: int,
    pattern_key: str,
    pattern_kind: str,
    pattern_text: str,
    source: str,
    seen_at: str,
    success_delta: int = 0,
    failure_delta: int = 0,
) -> None:
    normalized_key = slugify(pattern_key)
    existing = connection.execute(
        """
        SELECT *
        FROM field_patterns
        WHERE entry_id = ? AND pattern_key = ? AND pattern_kind = ?
        """,
        (entry_id, normalized_key, pattern_kind),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO field_patterns (
              entry_id,
              pattern_key,
              pattern_kind,
              pattern_text,
              source,
              first_seen_at,
              last_seen_at,
              success_count,
              failure_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                normalized_key,
                pattern_kind,
                pattern_text,
                source,
                seen_at,
                seen_at,
                success_delta,
                failure_delta,
            ),
        )
        return

    merged_source = merge_unique_text(existing["source"], source)
    connection.execute(
        """
        UPDATE field_patterns
        SET pattern_text = ?,
            source = ?,
            last_seen_at = ?,
            success_count = success_count + ?,
            failure_count = failure_count + ?
        WHERE id = ?
        """,
        (
            pattern_text,
            merged_source,
            seen_at,
            success_delta,
            failure_delta,
            existing["id"],
        ),
    )


def upsert_preference_record(
    connection: sqlite3.Connection,
    *,
    entry_id: int,
    preference_kind: str,
    value_text: str,
    reason: str | None,
    source: str,
    seen_at: str,
    success_delta: int = 0,
    failure_delta: int = 0,
) -> None:
    existing = connection.execute(
        """
        SELECT *
        FROM field_preferences
        WHERE entry_id = ? AND preference_kind = ? AND value_text = ?
        """,
        (entry_id, preference_kind, value_text),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO field_preferences (
              entry_id,
              preference_kind,
              value_text,
              reason,
              source,
              first_seen_at,
              last_seen_at,
              success_count,
              failure_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                preference_kind,
                value_text,
                reason,
                source,
                seen_at,
                seen_at,
                success_delta,
                failure_delta,
            ),
        )
        return

    merged_source = merge_unique_text(existing["source"], source)
    merged_reason = merge_unique_text(existing["reason"], reason)
    connection.execute(
        """
        UPDATE field_preferences
        SET reason = ?,
            source = ?,
            last_seen_at = ?,
            success_count = success_count + ?,
            failure_count = failure_count + ?
        WHERE id = ?
        """,
        (
            merged_reason,
            merged_source,
            seen_at,
            success_delta,
            failure_delta,
            existing["id"],
        ),
    )


def seed_database(connection: sqlite3.Connection, seed_data: dict[str, Any]) -> None:
    seen_at = seed_data.get("generated_at") or utc_now()
    for entry in seed_data["entries"]:
        entry_seen_at = clean_text(entry.get("last_seen_at")) or seen_at
        entry_id = upsert_entry_record(
            connection,
            platform=entry["platform"],
            context_key=entry.get("context_key", "global"),
            field_slug=entry["field_slug"],
            field_key=entry.get("field_key"),
            field_label=entry.get("field_label"),
            widget_type=entry.get("widget_type"),
            source="seed",
            notes=" | ".join(entry.get("notes", [])) if entry.get("notes") else None,
            seen_at=entry_seen_at,
        )
        for option in entry.get("options", []):
            upsert_option_record(
                connection,
                entry_id=entry_id,
                option_value=option["option_value"],
                source=clean_text(option.get("source")) or "seed",
                seen_at=clean_text(option.get("last_seen_at")) or entry_seen_at,
                observed_delta=int(option.get("observed_count") or 0),
                commit_delta=int(option.get("commit_count") or 0),
                reject_delta=int(option.get("reject_count") or 0),
                is_seeded=1 if option.get("is_seeded", 1) else 0,
            )
        for pattern in entry.get("patterns", []):
            upsert_pattern_record(
                connection,
                entry_id=entry_id,
                pattern_key=pattern["pattern_key"],
                pattern_kind=pattern["pattern_kind"],
                pattern_text=pattern["pattern_text"],
                source=clean_text(pattern.get("source")) or "seed",
                seen_at=clean_text(pattern.get("last_seen_at")) or entry_seen_at,
                success_delta=int(pattern.get("success_count") or 0),
                failure_delta=int(pattern.get("failure_count") or 0),
            )
        for preference in entry.get("preferences", []):
            upsert_preference_record(
                connection,
                entry_id=entry_id,
                preference_kind=preference["preference_kind"],
                value_text=preference["value_text"],
                reason=preference.get("reason"),
                source=clean_text(preference.get("source")) or "seed",
                seen_at=clean_text(preference.get("last_seen_at")) or entry_seen_at,
                success_delta=int(preference.get("success_count") or 0),
                failure_delta=int(preference.get("failure_count") or 0),
            )


def ensure_database(db_path: Path, seed_path: Path) -> sqlite3.Connection:
    if not seed_path.exists():
        write_seed_file(seed_path)
    seed_data = load_seed_file(seed_path)
    return initialize_database(db_path, seed_data, force=False)


def option_confidence(row: sqlite3.Row) -> str:
    if is_stale(row["last_seen_at"]):
        return "low"
    if row["commit_count"] >= 3 and row["reject_count"] == 0:
        return "high"
    if row["commit_count"] >= 1:
        return "medium"
    return "low" if row["is_seeded"] else "medium" if row["observed_count"] >= 2 else "low"


def pattern_confidence(row: sqlite3.Row) -> str:
    if is_stale(row["last_seen_at"]):
        return "low"
    if row["success_count"] >= 3 and row["failure_count"] == 0:
        return "high"
    if row["success_count"] >= 1:
        return "medium"
    return "low"


def preference_confidence(row: sqlite3.Row) -> str:
    if is_stale(row["last_seen_at"]):
        return "low"
    if row["success_count"] >= 2 and row["failure_count"] == 0:
        return "high"
    if row["failure_count"] > row["success_count"]:
        return "low"
    return "medium" if row["success_count"] else "low"


def lookup_field_memory(
    connection: sqlite3.Connection,
    *,
    platform: str,
    context_key: str,
    field_key: str | None,
    field_label: str | None,
) -> dict[str, Any]:
    slug_candidates = []
    for candidate in (field_key, field_label):
        candidate_slug = slugify(candidate)
        if candidate_slug not in slug_candidates:
            slug_candidates.append(candidate_slug)
    if not slug_candidates:
        raise ValueError("lookup requires --field-key or --field-label")

    placeholders = ",".join("?" for _ in slug_candidates)
    rows = connection.execute(
        f"""
        SELECT *
        FROM field_entries
        WHERE platform = ?
          AND field_slug IN ({placeholders})
          AND context_key IN (?, 'global')
        ORDER BY CASE WHEN context_key = ? THEN 0 ELSE 1 END, last_seen_at DESC
        """,
        [platform, *slug_candidates, context_key, context_key],
    ).fetchall()

    if not rows:
        return {
            "platform": platform,
            "requested_context_key": context_key,
            "field_key": field_key,
            "field_label": field_label,
            "matches": [],
            "warnings": ["No field-memory match found; use live inspection and record a new delta after the run."],
        }

    entry_ids = [row["id"] for row in rows]
    entry_placeholders = ",".join("?" for _ in entry_ids)

    options = connection.execute(
        f"""
        SELECT *
        FROM field_options
        WHERE entry_id IN ({entry_placeholders})
        ORDER BY commit_count DESC, observed_count DESC, option_value ASC
        """,
        entry_ids,
    ).fetchall()
    patterns = connection.execute(
        f"""
        SELECT *
        FROM field_patterns
        WHERE entry_id IN ({entry_placeholders})
        ORDER BY success_count DESC, pattern_kind ASC, pattern_key ASC
        """,
        entry_ids,
    ).fetchall()
    preferences = connection.execute(
        f"""
        SELECT *
        FROM field_preferences
        WHERE entry_id IN ({entry_placeholders})
        ORDER BY success_count DESC, preference_kind ASC, value_text ASC
        """,
        entry_ids,
    ).fetchall()

    warnings = []
    matched_contexts = []
    if not any(row["context_key"] == context_key for row in rows):
        warnings.append("No exact context match; using global memory only.")
    if any(row["source"] == "seed" and row["last_seen_at"] == row["first_seen_at"] for row in rows):
        warnings.append("Some results are seeded reference data only; verify live before trusting them.")
    if any(is_stale(row["last_seen_at"]) for row in options) or any(
        is_stale(row["last_seen_at"]) for row in patterns
    ) or any(is_stale(row["last_seen_at"]) for row in preferences):
        warnings.append("Some remembered values are stale; verify the live UI carefully and record drift if the cache is wrong.")

    for row in rows:
        if row["context_key"] not in matched_contexts:
            matched_contexts.append(row["context_key"])

    return {
        "platform": platform,
        "requested_context_key": context_key,
        "matched_contexts": matched_contexts,
        "field_key": rows[0]["field_key"] or field_key,
        "field_label": rows[0]["field_label"] or field_label,
        "field_slug": rows[0]["field_slug"],
        "widget_type": rows[0]["widget_type"],
        "known_options": [
            {
                "value": row["option_value"],
                "observed_count": row["observed_count"],
                "commit_count": row["commit_count"],
                "reject_count": row["reject_count"],
                "confidence": option_confidence(row),
                "source": row["source"],
                "last_seen_at": row["last_seen_at"],
            }
            for row in options
        ],
        "interaction_patterns": [
            {
                "pattern_key": row["pattern_key"],
                "pattern_kind": row["pattern_kind"],
                "pattern_text": row["pattern_text"],
                "success_count": row["success_count"],
                "failure_count": row["failure_count"],
                "confidence": pattern_confidence(row),
                "source": row["source"],
                "last_seen_at": row["last_seen_at"],
            }
            for row in patterns
        ],
        "preferred_values": [
            {
                "preference_kind": row["preference_kind"],
                "value": row["value_text"],
                "reason": row["reason"],
                "success_count": row["success_count"],
                "failure_count": row["failure_count"],
                "confidence": preference_confidence(row),
                "source": row["source"],
                "last_seen_at": row["last_seen_at"],
            }
            for row in preferences
        ],
        "warnings": warnings,
    }


def load_json_payload(input_path: str) -> Any:
    if input_path == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(input_path).read_text(encoding="utf-8"))


def is_successful_observation(item: dict[str, Any]) -> bool:
    blockers = clean_text(item.get("blockers"))
    save_outcome = clean_text(item.get("save_outcome")).lower()
    if blockers and blockers.lower() not in {"none", "n/a"}:
        return False
    if any(token in save_outcome for token in ("blocked", "failed", "error")):
        return False
    return True


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(str(item)) for item in value if clean_text(str(item))]
    text = clean_text(str(value))
    return [text] if text else []


def merge_delta_payload(connection: sqlite3.Connection, payload: Any, run_id_override: str | None = None) -> dict[str, Any]:
    if isinstance(payload, dict):
        items = payload.get("field_memory_delta", payload.get("items", []))
        run_id = run_id_override or clean_text(payload.get("run_id")) or f"field-memory-{utc_now()}"
        observed_at = clean_text(payload.get("observed_at")) or utc_now()
        source = clean_text(payload.get("source")) or "field_memory_delta"
        notes = clean_text(payload.get("notes")) or None
    elif isinstance(payload, list):
        items = payload
        run_id = run_id_override or f"field-memory-{utc_now()}"
        observed_at = utc_now()
        source = "field_memory_delta"
        notes = None
    else:
        raise ValueError("field memory delta must be a JSON object or a JSON list")

    if not isinstance(items, list):
        raise ValueError("field_memory_delta must be a list")

    connection.execute(
        """
        INSERT OR REPLACE INTO field_runs (run_id, observed_at, source, notes)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, observed_at, source, notes),
    )

    merged_count = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every field_memory_delta entry must be an object")
        platform = clean_text(item.get("platform"))
        if not platform:
            raise ValueError("field_memory_delta entry is missing platform")
        context_key = clean_text(item.get("context_key")) or "global"
        field_key = clean_text(item.get("field_key")) or None
        field_label = clean_text(item.get("field_label")) or None
        if not field_key and not field_label:
            raise ValueError("field_memory_delta entry needs field_key or field_label")

        seen_at = clean_text(item.get("observed_at")) or observed_at
        entry_id = upsert_entry_record(
            connection,
            platform=platform,
            context_key=context_key,
            field_slug=slugify(field_key or field_label),
            field_key=field_key,
            field_label=field_label,
            widget_type=clean_text(item.get("widget_type")) or infer_widget_type(field_key, field_label),
            source=source,
            notes=clean_text(item.get("notes")) or None,
            seen_at=seen_at,
        )

        visible_options = coerce_list(item.get("visible_options"))
        attempted_value = clean_text(item.get("attempted_value")) or None
        committed_value = clean_text(item.get("committed_value")) or None
        blockers = clean_text(item.get("blockers")) or None
        successful = is_successful_observation(item)

        for option in visible_options:
            upsert_option_record(
                connection,
                entry_id=entry_id,
                option_value=option,
                source=source,
                seen_at=seen_at,
                observed_delta=1,
            )

        if attempted_value and attempted_value != committed_value and blockers and blockers.lower() not in {"none", "n/a"}:
            upsert_option_record(
                connection,
                entry_id=entry_id,
                option_value=attempted_value,
                source=source,
                seen_at=seen_at,
                reject_delta=1,
            )

        if committed_value:
            upsert_option_record(
                connection,
                entry_id=entry_id,
                option_value=committed_value,
                source=source,
                seen_at=seen_at,
                commit_delta=1,
            )

        interaction_pattern = clean_text(item.get("interaction_pattern"))
        if interaction_pattern:
            upsert_pattern_record(
                connection,
                entry_id=entry_id,
                pattern_key=clean_text(item.get("interaction_pattern_key")) or interaction_pattern,
                pattern_kind="interaction",
                pattern_text=interaction_pattern,
                source=source,
                seen_at=seen_at,
                success_delta=1 if successful else 0,
                failure_delta=0 if successful else 1,
            )

        for value in coerce_list(item.get("preferred_values")) + coerce_list(item.get("preferred_value")):
            upsert_preference_record(
                connection,
                entry_id=entry_id,
                preference_kind="preferred",
                value_text=value,
                reason="Promoted from field_memory_delta",
                source=source,
                seen_at=seen_at,
                success_delta=1 if successful else 0,
                failure_delta=0 if successful else 1,
            )
        for value in coerce_list(item.get("fallback_values")) + coerce_list(item.get("fallback_value")):
            upsert_preference_record(
                connection,
                entry_id=entry_id,
                preference_kind="fallback",
                value_text=value,
                reason="Recorded fallback from field_memory_delta",
                source=source,
                seen_at=seen_at,
                success_delta=1 if successful else 0,
                failure_delta=0 if successful else 1,
            )
        for value in coerce_list(item.get("avoid_values")) + coerce_list(item.get("avoid_value")):
            upsert_preference_record(
                connection,
                entry_id=entry_id,
                preference_kind="avoid",
                value_text=value,
                reason="Recorded avoid-value from field_memory_delta",
                source=source,
                seen_at=seen_at,
                success_delta=0,
                failure_delta=1,
            )

        connection.execute(
            """
            INSERT INTO field_observations (
              run_id,
              entry_id,
              trace_step_goal,
              target_ui,
              visible_options_json,
              attempted_value,
              committed_value,
              interaction_pattern,
              save_outcome,
              blockers,
              confidence,
              observed_at,
              source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                entry_id,
                clean_text(item.get("trace_step_goal")) or None,
                clean_text(item.get("target_ui")) or None,
                json.dumps(visible_options) if visible_options else None,
                attempted_value,
                committed_value,
                interaction_pattern or None,
                clean_text(item.get("save_outcome")) or None,
                blockers,
                clean_text(item.get("confidence")) or None,
                seen_at,
                source,
            ),
        )
        merged_count += 1

    connection.commit()
    return {
        "run_id": run_id,
        "merged_entries": merged_count,
        "observed_at": observed_at,
        "source": source,
    }


def summarize_database(connection: sqlite3.Connection) -> dict[str, Any]:
    counts = {
        "entries": connection.execute("SELECT COUNT(*) FROM field_entries").fetchone()[0],
        "options": connection.execute("SELECT COUNT(*) FROM field_options").fetchone()[0],
        "patterns": connection.execute("SELECT COUNT(*) FROM field_patterns").fetchone()[0],
        "preferences": connection.execute("SELECT COUNT(*) FROM field_preferences").fetchone()[0],
        "runs": connection.execute("SELECT COUNT(*) FROM field_runs").fetchone()[0],
        "observations": connection.execute("SELECT COUNT(*) FROM field_observations").fetchone()[0],
    }
    by_platform = connection.execute(
        """
        SELECT platform, COUNT(*) AS count
        FROM field_entries
        GROUP BY platform
        ORDER BY platform
        """
    ).fetchall()
    counts["by_platform"] = {row["platform"]: row["count"] for row in by_platform}
    return counts


def export_seed_data(connection: sqlite3.Connection) -> dict[str, Any]:
    entries = connection.execute(
        """
        SELECT *
        FROM field_entries
        ORDER BY platform, context_key, field_slug
        """
    ).fetchall()
    if not entries:
        return {
            "seed_version": SEED_VERSION,
            "generated_at": utc_now(),
            "source_files": [portable_path(LIST_THIS_PATH), portable_path(TEMPLATE_PATH)],
            "entries": [],
        }

    entry_ids = [row["id"] for row in entries]
    placeholders = ",".join("?" for _ in entry_ids)

    options = connection.execute(
        f"""
        SELECT *
        FROM field_options
        WHERE entry_id IN ({placeholders})
        ORDER BY entry_id, commit_count DESC, observed_count DESC, option_value ASC
        """,
        entry_ids,
    ).fetchall()
    patterns = connection.execute(
        f"""
        SELECT *
        FROM field_patterns
        WHERE entry_id IN ({placeholders})
        ORDER BY entry_id, success_count DESC, pattern_kind ASC, pattern_key ASC
        """,
        entry_ids,
    ).fetchall()
    preferences = connection.execute(
        f"""
        SELECT *
        FROM field_preferences
        WHERE entry_id IN ({placeholders})
        ORDER BY entry_id, success_count DESC, preference_kind ASC, value_text ASC
        """,
        entry_ids,
    ).fetchall()

    options_by_entry: dict[int, list[sqlite3.Row]] = {entry_id: [] for entry_id in entry_ids}
    for row in options:
        options_by_entry[int(row["entry_id"])].append(row)

    patterns_by_entry: dict[int, list[sqlite3.Row]] = {entry_id: [] for entry_id in entry_ids}
    for row in patterns:
        patterns_by_entry[int(row["entry_id"])].append(row)

    preferences_by_entry: dict[int, list[sqlite3.Row]] = {entry_id: [] for entry_id in entry_ids}
    for row in preferences:
        preferences_by_entry[int(row["entry_id"])].append(row)

    exported_entries = []
    for entry in entries:
        entry_id = int(entry["id"])
        exported_entries.append(
            {
                "platform": entry["platform"],
                "context_key": entry["context_key"],
                "field_slug": entry["field_slug"],
                "field_key": entry["field_key"],
                "field_label": entry["field_label"],
                "widget_type": entry["widget_type"],
                "sources": split_text_parts(entry["source"]),
                "notes": split_text_parts(entry["notes"]),
                "first_seen_at": entry["first_seen_at"],
                "last_seen_at": entry["last_seen_at"],
                "options": [
                    {
                        "option_value": row["option_value"],
                        "option_normalized": row["option_normalized"],
                        "source": row["source"],
                        "first_seen_at": row["first_seen_at"],
                        "last_seen_at": row["last_seen_at"],
                        "observed_count": row["observed_count"],
                        "commit_count": row["commit_count"],
                        "reject_count": row["reject_count"],
                        "is_seeded": bool(row["is_seeded"]),
                    }
                    for row in options_by_entry[entry_id]
                ],
                "patterns": [
                    {
                        "pattern_key": row["pattern_key"],
                        "pattern_kind": row["pattern_kind"],
                        "pattern_text": row["pattern_text"],
                        "source": row["source"],
                        "first_seen_at": row["first_seen_at"],
                        "last_seen_at": row["last_seen_at"],
                        "success_count": row["success_count"],
                        "failure_count": row["failure_count"],
                    }
                    for row in patterns_by_entry[entry_id]
                ],
                "preferences": [
                    {
                        "preference_kind": row["preference_kind"],
                        "value_text": row["value_text"],
                        "reason": row["reason"],
                        "source": row["source"],
                        "first_seen_at": row["first_seen_at"],
                        "last_seen_at": row["last_seen_at"],
                        "success_count": row["success_count"],
                        "failure_count": row["failure_count"],
                    }
                    for row in preferences_by_entry[entry_id]
                ],
            }
        )

    return {
        "seed_version": SEED_VERSION,
        "generated_at": utc_now(),
        "source_files": [portable_path(LIST_THIS_PATH), portable_path(TEMPLATE_PATH)],
        "entries": exported_entries,
    }


def write_export_seed_file(connection: sqlite3.Connection, output_path: Path) -> dict[str, Any]:
    seed_data = export_seed_data(connection)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(seed_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return seed_data


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_build_seed(args: argparse.Namespace) -> int:
    seed_data = write_seed_file(Path(args.output))
    print_json(
        {
            "seed_path": str(Path(args.output)),
            "entries": len(seed_data["entries"]),
            "generated_at": seed_data["generated_at"],
        }
    )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    seed_path = Path(args.seed)
    seed_data = load_seed_file(seed_path) if seed_path.exists() else write_seed_file(seed_path)
    with initialize_database(Path(args.db), seed_data, force=args.force) as connection:
        print_json(
            {
                "db_path": str(Path(args.db)),
                "seed_path": str(seed_path),
                "force": bool(args.force),
                "summary": summarize_database(connection),
            }
        )
    return 0


def cmd_lookup(args: argparse.Namespace) -> int:
    with ensure_database(Path(args.db), Path(args.seed)) as connection:
        payload = lookup_field_memory(
            connection,
            platform=args.platform,
            context_key=args.context_key,
            field_key=args.field_key,
            field_label=args.field_label,
        )
        print_json(payload)
    return 0


def cmd_merge_delta(args: argparse.Namespace) -> int:
    payload = load_json_payload(args.input)
    with ensure_database(Path(args.db), Path(args.seed)) as connection:
        result = merge_delta_payload(connection, payload, run_id_override=args.run_id)
        result["summary"] = summarize_database(connection)
        print_json(result)
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    with ensure_database(Path(args.db), Path(args.seed)) as connection:
        print_json(
            {
                "db_path": str(Path(args.db)),
                "summary": summarize_database(connection),
            }
        )
    return 0


def cmd_export_seed(args: argparse.Namespace) -> int:
    with ensure_database(Path(args.db), Path(args.seed)) as connection:
        seed_data = write_export_seed_file(connection, Path(args.output))
        print_json(
            {
                "db_path": str(Path(args.db)),
                "seed_path": str(Path(args.output)),
                "entries": len(seed_data["entries"]),
                "generated_at": seed_data["generated_at"],
            }
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent field-memory helper for list-this-direct")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the SQLite field-memory database")
    parser.add_argument("--seed", default=str(SEED_PATH), help="Path to the field-memory seed JSON file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_seed = subparsers.add_parser("build-seed", help="Build seed JSON from the current markdown references")
    build_seed.add_argument(
        "--output",
        default=str(SEED_PATH),
        help="Where to write the generated seed JSON",
    )
    build_seed.set_defaults(func=cmd_build_seed)

    init = subparsers.add_parser("init", help="Initialize or refresh the persistent field-memory database")
    init.add_argument("--force", action="store_true", help="Recreate the database file from scratch")
    init.set_defaults(func=cmd_init)

    lookup = subparsers.add_parser("lookup", help="Look up known options, patterns, and preferences for a field")
    lookup.add_argument("--platform", required=True, help="Platform name such as vendoo, ebay, etsy, poshmark, or depop")
    lookup.add_argument("--context-key", default="global", help="Context scope such as global or women-pants")
    lookup.add_argument("--field-key", help="Stable field key when known")
    lookup.add_argument("--field-label", help="Visible field label when the key is unknown")
    lookup.set_defaults(func=cmd_lookup)

    merge_delta = subparsers.add_parser("merge-delta", help="Merge a field_memory_delta JSON artifact into the database")
    merge_delta.add_argument("--input", required=True, help="Path to a JSON file or - for stdin")
    merge_delta.add_argument("--run-id", help="Optional override for the stored run_id")
    merge_delta.set_defaults(func=cmd_merge_delta)

    summary = subparsers.add_parser("summary", help="Show counts and platform coverage for the database")
    summary.set_defaults(func=cmd_summary)

    export_seed = subparsers.add_parser(
        "export-seed",
        help="Export the current database contents as a portable seed JSON snapshot",
    )
    export_seed.add_argument(
        "--output",
        default=str(SEED_PATH),
        help="Where to write the exported seed JSON",
    )
    export_seed.set_defaults(func=cmd_export_seed)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
