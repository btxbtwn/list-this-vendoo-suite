#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
)

KEYWORD_GROUPS = {
    "graphic": ("graphic",),
    "statement": ("statement",),
    "destination": ("destination", "travel", "tourist"),
    "sports": ("sport", "athletic", "jersey", "team"),
    "y2k": ("y2k",),
    "vintage": ("vintage", "retro", "70s", "80s", "90s"),
    "festival": ("festival", "boho", "coachella"),
    "mesh": ("mesh", "sheer"),
    "blouse": ("blouse",),
    "summer": ("summer", "tropical"),
    "beach": ("beach", "cover up", "swim"),
    "mini": ("mini",),
    "wrap": ("wrap", "kimono"),
    "baby tee": ("baby tee",),
    "crop": ("crop", "cropped"),
    "dress": ("dress",),
    "shorts": ("shorts",),
    "denim": ("denim", "jean"),
}

SEASONAL_KEYWORDS = {
    "spring_summer": {
        "summer",
        "beach",
        "festival",
        "mesh",
        "blouse",
        "mini",
        "baby tee",
        "crop",
        "dress",
        "shorts",
    },
    "fall_winter": {
        "vintage",
        "denim",
    },
}

TAG_EXACT_EXCLUSIONS = {
    "clothing",
    "raghouse",
}

TAG_PREFIX_EXCLUSIONS = (
    "cog:",
)

TAG_PATTERN_EXCLUSIONS = (
    re.compile(r"^\d+days\+?$"),
    re.compile(r"^[a-z]{1,3}\d{1,4}$"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a Vendoo export and summarize recent demand signals."
    )
    parser.add_argument("--input", help="Path to a specific Vendoo CSV file.")
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Auto-discover the freshest Vendoo export from common local paths.",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        help="Override today's date (YYYY-MM-DD) for rolling-window analysis.",
    )
    parser.add_argument("--output", help="Write the JSON summary to this path.")
    return parser.parse_args()


def parse_date(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_number(value: str) -> float:
    text = (value or "").strip().replace("$", "").replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def canonical_candidate_patterns() -> list[str]:
    home = Path.home()
    workspace = home / ".openclaw" / "workspace"
    return [
        str(workspace / "vendoo-analytics" / "public" / "data" / "vendoo.csv"),
        str(workspace / "**" / "vendoo-full-*.csv"),
        str(home / "Downloads" / "vendoo-full-*.csv"),
    ]


def discover_latest_export() -> Path:
    explicit = os.environ.get("VENDOO_EXPORT_PATH")
    candidates: list[Path] = []
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            candidates.append(path)
    for pattern in canonical_candidate_patterns():
        for match in glob.glob(pattern, recursive=True):
            path = Path(match).expanduser()
            if path.is_file():
                candidates.append(path)
    unique_candidates = {path.resolve(): path.resolve() for path in candidates}
    if not unique_candidates:
        raise FileNotFoundError(
            "No Vendoo export found. Checked workspace vendoo.csv, workspace vendoo-full-*.csv, and Downloads."
        )
    return max(unique_candidates.values(), key=lambda path: path.stat().st_mtime)


def split_unique_values(raw: str) -> list[str]:
    unique_values: dict[str, str] = {}
    cleaned = (raw or "").replace("[", " ").replace("]", " ")
    for token in cleaned.split(","):
        value = re.sub(r"\s+", " ", token).strip().lower()
        if not value:
            continue
        if value not in unique_values:
            unique_values[value] = value
    return list(unique_values.values())


def is_signal_tag(tag: str) -> bool:
    if tag in TAG_EXACT_EXCLUSIONS:
        return False
    if any(tag.startswith(prefix) for prefix in TAG_PREFIX_EXCLUSIONS):
        return False
    if any(pattern.fullmatch(tag) for pattern in TAG_PATTERN_EXCLUSIONS):
        return False
    return True


def normalize_tags(raw: str) -> list[str]:
    return [tag for tag in split_unique_values(raw) if is_signal_tag(tag)]


def normalize_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sold_dt = parse_date(row.get("Sold Date", ""))
            listed_dt = parse_date(row.get("Listed Date", ""))
            status = (row.get("Status") or "").strip().lower()
            brand = (row.get("Brand") or "").strip() or "(blank)"
            category = (row.get("Category") or "").strip() or "(blank)"
            sold_platform = (row.get("Sold Platform") or "").strip() or "(blank)"
            title = (row.get("Title") or "").strip()
            description = (row.get("Description") or "").strip()
            tag_list = normalize_tags(row.get("Tags", ""))
            price_sold = parse_number(row.get("Price Sold", ""))
            cost_of_goods = parse_number(row.get("Cost of Goods", ""))
            marketplace_fees = parse_number(row.get("Marketplace Fees", ""))
            shipping_expenses = parse_number(row.get("Shipping Expenses", ""))
            text = " ".join(
                [
                    title.lower(),
                    description.lower(),
                    " ".join(tag_list),
                    category.lower(),
                    brand.lower(),
                ]
            )
            rows.append(
                {
                    "status": status,
                    "brand": brand,
                    "category": category,
                    "sold_platform": sold_platform,
                    "sold_dt": sold_dt,
                    "listed_dt": listed_dt,
                    "tags": tag_list,
                    "price_sold": price_sold,
                    "profit": price_sold - cost_of_goods - marketplace_fees - shipping_expenses,
                    "text": text,
                }
            )
    return rows


def counter_to_rows(
    sold_counter: Counter[str], active_counter: Counter[str], *, min_sold: int, min_active: int
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    keys = set(sold_counter) | set(active_counter)
    for key in keys:
        sold_count = sold_counter[key]
        active_count = active_counter[key]
        total = sold_count + active_count
        if sold_count < min_sold and active_count < min_active:
            continue
        rows.append(
            {
                "name": key,
                "sold_90": sold_count,
                "active": active_count,
                "sell_through_proxy": round(sold_count / total, 3) if total else 0.0,
            }
        )
    rows.sort(key=lambda row: (-int(row["sold_90"]), -float(row["sell_through_proxy"]), int(row["active"]), str(row["name"])))
    return rows


def overstock_rows(sold_counter: Counter[str], active_counter: Counter[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key, active_count in active_counter.items():
        sold_count = sold_counter[key]
        total = sold_count + active_count
        proxy = sold_count / total if total else 0.0
        if active_count >= 5 and proxy <= 0.15:
            rows.append(
                {
                    "name": key,
                    "sold_90": sold_count,
                    "active": active_count,
                    "sell_through_proxy": round(proxy, 3),
                }
            )
    rows.sort(key=lambda row: (-int(row["active"]), float(row["sell_through_proxy"]), -int(row["sold_90"]), str(row["name"])))
    return rows[:10]


def count_list_values(rows: Iterable[dict[str, object]], field: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        values = row.get(field) or []
        for value in values:
            counter[str(value)] += 1
    return counter


def name_matches_terms(name: str, terms: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(term in lowered for term in terms)


def seasonal_terms(season_bucket: str) -> tuple[str, ...]:
    terms: list[str] = []
    for keyword in SEASONAL_KEYWORDS[season_bucket]:
        terms.append(keyword)
        terms.extend(KEYWORD_GROUPS.get(keyword, ()))
    return tuple(dict.fromkeys(term.lower() for term in terms))


def window_summary_from_counters(
    sold_90_counter: Counter[str],
    sold_30_counter: Counter[str],
    sold_prev_60_counter: Counter[str],
    active_counter: Counter[str],
    *,
    min_sold: int,
    min_active: int,
    season_bucket: str,
) -> dict[str, object]:
    season_terms = seasonal_terms(season_bucket)
    raw_rows: list[dict[str, object]] = []
    for name in set(sold_90_counter) | set(sold_30_counter) | set(sold_prev_60_counter) | set(active_counter):
        sold_90_count = sold_90_counter[name]
        sold_30_count = sold_30_counter[name]
        sold_prev_60_count = sold_prev_60_counter[name]
        active_count = active_counter[name]
        if sold_90_count < min_sold and active_count < min_active and sold_30_count == 0:
            continue
        next_score = sold_30_count * 2 + max(0, sold_30_count - sold_prev_60_count)
        if name_matches_terms(name, season_terms):
            next_score += 2
        total = sold_90_count + active_count
        raw_rows.append(
            {
                "name": name,
                "sold_90": sold_90_count,
                "sold_30": sold_30_count,
                "sold_prev_60": sold_prev_60_count,
                "active": active_count,
                "sell_through_proxy": round(sold_90_count / total, 3) if total else 0.0,
                "trend": trend_label(sold_30_count, sold_prev_60_count, sold_90_count),
                "next_score": next_score,
            }
        )

    hot_now = [row for row in raw_rows if int(row["sold_90"]) >= min_sold or int(row["sold_30"]) >= 2]
    hot_now.sort(
        key=lambda row: (
            -int(row["sold_90"]),
            -int(row["sold_30"]),
            -float(row["sell_through_proxy"]),
            int(row["active"]),
            str(row["name"]),
        )
    )

    next_window = [
        row
        for row in raw_rows
        if int(row["next_score"]) > 0 and (name_matches_terms(str(row["name"]), season_terms) or int(row["sold_30"]) >= 2)
    ]
    next_window.sort(key=lambda row: (-int(row["next_score"]), -int(row["sold_30"]), str(row["name"])))

    active_pressure = [
        row
        for row in raw_rows
        if int(row["active"]) >= max(min_active, 6) and int(row["sold_90"]) <= max(2, min_sold - 1)
    ]
    active_pressure.sort(
        key=lambda row: (
            -int(row["active"]),
            float(row["sell_through_proxy"]),
            -int(row["sold_90"]),
            str(row["name"]),
        )
    )

    return {
        "hot_now": hot_now[:12],
        "next_60_90": next_window[:10],
        "active_pressure": active_pressure[:10],
        "raw": raw_rows,
        "season_bucket": season_bucket,
    }


def platform_tag_winners(sold_rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    platform_sales_with_tags: Counter[str] = Counter()
    platform_tag_counts: dict[str, Counter[str]] = {}
    for row in sold_rows:
        tags = row.get("tags") or []
        if not tags:
            continue
        platform = str(row["sold_platform"])
        platform_sales_with_tags[platform] += 1
        if platform not in platform_tag_counts:
            platform_tag_counts[platform] = Counter()
        platform_tag_counts[platform].update(str(tag) for tag in tags)

    rows: list[dict[str, object]] = []
    for platform, tagged_sales in platform_sales_with_tags.most_common(10):
        top_tags = [
            {"name": name, "sold_90": count}
            for name, count in platform_tag_counts[platform].most_common(5)
            if count >= 2
        ]
        if not top_tags:
            continue
        rows.append(
            {
                "platform": platform,
                "sales_with_tags": tagged_sales,
                "top_tags": top_tags,
            }
        )
    return rows


def count_keyword(rows: Iterable[dict[str, object]], terms: tuple[str, ...]) -> int:
    total = 0
    for row in rows:
        text = str(row["text"])
        if any(term in text for term in terms):
            total += 1
    return total


def current_season_bucket(as_of: datetime) -> str:
    if as_of.month in (3, 4, 5, 6, 7, 8):
        return "spring_summer"
    return "fall_winter"


def keyword_summary(
    sold_90: list[dict[str, object]],
    sold_30: list[dict[str, object]],
    sold_prev_60: list[dict[str, object]],
    active_rows: list[dict[str, object]],
    *,
    as_of: datetime,
) -> dict[str, object]:
    season_bucket = current_season_bucket(as_of)
    raw_rows: list[dict[str, object]] = []
    for keyword, terms in KEYWORD_GROUPS.items():
        sold_90_count = count_keyword(sold_90, terms)
        sold_30_count = count_keyword(sold_30, terms)
        sold_prev_60_count = count_keyword(sold_prev_60, terms)
        active_count = count_keyword(active_rows, terms)
        next_score = sold_30_count * 2 + max(0, sold_30_count - sold_prev_60_count)
        if keyword in SEASONAL_KEYWORDS[season_bucket]:
            next_score += 2
        row = {
            "keyword": keyword,
            "sold_90": sold_90_count,
            "sold_30": sold_30_count,
            "sold_prev_60": sold_prev_60_count,
            "active": active_count,
            "trend": trend_label(sold_30_count, sold_prev_60_count, sold_90_count),
            "next_score": next_score,
        }
        raw_rows.append(row)

    hot_now = [row for row in raw_rows if int(row["sold_90"]) >= 3 or int(row["sold_30"]) >= 2]
    hot_now.sort(key=lambda row: (-int(row["sold_90"]), -int(row["sold_30"]), str(row["keyword"])))

    next_window = [
        row
        for row in raw_rows
        if int(row["next_score"]) > 0 and (row["keyword"] in SEASONAL_KEYWORDS[season_bucket] or int(row["sold_30"]) >= 2)
    ]
    next_window.sort(key=lambda row: (-int(row["next_score"]), -int(row["sold_30"]), str(row["keyword"])))

    active_pressure = [
        row
        for row in raw_rows
        if int(row["active"]) >= 6 and int(row["sold_90"]) <= 2
    ]
    active_pressure.sort(key=lambda row: (-int(row["active"]), int(row["sold_90"]), str(row["keyword"])))

    return {
        "hot_now": hot_now[:10],
        "next_60_90": next_window[:10],
        "active_pressure": active_pressure[:10],
        "raw": raw_rows,
        "season_bucket": season_bucket,
    }


def tag_summary(
    sold_90: list[dict[str, object]],
    sold_30: list[dict[str, object]],
    sold_prev_60: list[dict[str, object]],
    active_rows: list[dict[str, object]],
    *,
    as_of: datetime,
) -> dict[str, object]:
    season_bucket = current_season_bucket(as_of)
    summary = window_summary_from_counters(
        count_list_values(sold_90, "tags"),
        count_list_values(sold_30, "tags"),
        count_list_values(sold_prev_60, "tags"),
        count_list_values(active_rows, "tags"),
        min_sold=3,
        min_active=6,
        season_bucket=season_bucket,
    )
    summary["platform_winners"] = platform_tag_winners(sold_90)
    return summary


def trend_label(sold_30: int, sold_prev_60: int, sold_90: int) -> str:
    if sold_30 >= 3 and sold_30 >= sold_prev_60:
        return "accelerating"
    if sold_90 >= 5:
        return "steady"
    if sold_30 >= 1:
        return "emerging"
    return "quiet"


def simple_takeaways(
    category_hot: list[dict[str, object]],
    category_overstock: list[dict[str, object]],
    keyword_data: dict[str, object],
    tag_data: dict[str, object],
) -> dict[str, list[str]]:
    buy_more_of = [str(row["name"]) for row in category_hot[:4]]
    buy_more_of.extend(str(row["name"]) for row in tag_data["hot_now"][:4])
    buy_more_of.extend(str(row["keyword"]) for row in keyword_data["hot_now"][:4])

    deprioritize = [str(row["name"]) for row in category_overstock[:4]]
    deprioritize.extend(str(row["name"]) for row in tag_data["active_pressure"][:4])
    deprioritize.extend(str(row["keyword"]) for row in keyword_data["active_pressure"][:3])

    watch_next = [str(row["name"]) for row in tag_data["next_60_90"][:6]]
    watch_next.extend(str(row["keyword"]) for row in keyword_data["next_60_90"][:6])

    return {
        "buy_more_of": dedupe_preserve_order(buy_more_of)[:8],
        "deprioritize": dedupe_preserve_order(deprioritize)[:8],
        "watch_next": dedupe_preserve_order(watch_next)[:8],
    }


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def build_summary(path: Path, *, as_of: datetime) -> dict[str, object]:
    rows = normalize_rows(path)

    sold_rows = [row for row in rows if row["sold_dt"]]
    active_rows = [row for row in rows if str(row["status"]) == "active"]
    sold_30 = [row for row in sold_rows if row["sold_dt"] >= as_of - timedelta(days=30)]
    sold_90 = [row for row in sold_rows if row["sold_dt"] >= as_of - timedelta(days=90)]
    sold_prev_60 = [
        row
        for row in sold_rows
        if as_of - timedelta(days=90) <= row["sold_dt"] < as_of - timedelta(days=30)
    ]

    category_sold = Counter(str(row["category"]) for row in sold_90)
    category_active = Counter(str(row["category"]) for row in active_rows)
    brand_sold = Counter(str(row["brand"]) for row in sold_90)
    brand_active = Counter(str(row["brand"]) for row in active_rows)
    platform_sold = Counter(str(row["sold_platform"]) for row in sold_90)

    keyword_data = keyword_summary(sold_90, sold_30, sold_prev_60, active_rows, as_of=as_of)
    tag_data = tag_summary(sold_90, sold_30, sold_prev_60, active_rows, as_of=as_of)

    category_hot = counter_to_rows(category_sold, category_active, min_sold=2, min_active=5)
    brand_hot = counter_to_rows(brand_sold, brand_active, min_sold=2, min_active=4)
    category_overstock = overstock_rows(category_sold, category_active)
    brand_overstock = overstock_rows(brand_sold, brand_active)

    file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
    file_age_days = (as_of - file_mtime).days

    warnings: list[str] = []
    if len(sold_90) < 25:
        warnings.append("Recent 90-day sold sample is thin; treat the signal as low confidence.")
    if file_age_days > 30:
        warnings.append("Vendoo export looks older than 30 days; trends may be stale.")
    if not tag_data["hot_now"] and not tag_data["next_60_90"]:
        warnings.append("Vendoo tags were sparse or mostly operational; lean more on keywords and categories than tag trends.")

    return {
        "selected_file": str(path),
        "selected_file_modified_at": file_mtime.isoformat(),
        "file_age_days": file_age_days,
        "as_of": as_of.date().isoformat(),
        "counts": {
            "rows": len(rows),
            "sold_rows": len(sold_rows),
            "active_rows": len(active_rows),
            "recent_30_sold": len(sold_30),
            "recent_90_sold": len(sold_90),
            "rows_with_tags": sum(1 for row in rows if row["tags"]),
            "recent_90_sold_with_tags": sum(1 for row in sold_90 if row["tags"]),
        },
        "platforms_recent_90": [
            {"name": name, "count": count}
            for name, count in platform_sold.most_common(10)
        ],
        "categories": {
            "hot": category_hot[:12],
            "overstock": category_overstock,
        },
        "brands": {
            "hot": brand_hot[:12],
            "overstock": brand_overstock,
        },
        "tags": tag_data,
        "keywords": keyword_data,
        "takeaways": simple_takeaways(category_hot, category_overstock, keyword_data, tag_data),
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    if args.input:
        path = Path(args.input).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Vendoo CSV not found: {path}")
    else:
        if not args.latest:
            raise SystemExit("Pass --input PATH or --latest.")
        path = discover_latest_export()

    as_of = parse_date(args.as_of) if args.as_of else datetime.now()
    if as_of is None:
        raise SystemExit(f"Could not parse --as-of value: {args.as_of}")

    summary = build_summary(path, as_of=as_of)
    rendered = json.dumps(summary, indent=2)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
