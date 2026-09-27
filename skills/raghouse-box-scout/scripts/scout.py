#!/usr/bin/env python3
"""Rank raghouse.com clothing boxes by landed cost per usable piece and demand.

Reads the store's public Shopify catalog (/products.json), estimates UPS Ground
shipping to the destination in references/shipping-70115.json from each box's
listed shipping weight, and scores every in-stock box. Standard library only.

    python3 scout.py --trend "carhartt,y2k,harley" --top 20
    python3 scout.py --json > boxes.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

STORE = "https://raghouse.com"
STORE_TZ = ZoneInfo("America/Phoenix")  # lot date tags are the warehouse's local dates
USER_AGENT = "Mozilla/5.0 (raghouse-box-scout; personal sourcing research)"
SHIPPING = Path(__file__).resolve().parent.parent / "references" / "shipping-70115.json"

# Product types that are not boxes of clothes.
SKIP_TYPES = {"Singles", "Membership", "Accessories", "Shoes", ""}

# Share of a box that is resellable. Raghouse says "Recycle" lots need TLC and are
# priced for it; "Recycle & Good" lots are mixed. These are starting assumptions:
# replace them with your own counts after unpacking a few boxes.
GRADE_YIELD = {"good": 0.90, "mixed": 0.75, "recycle": 0.60}

# Title words that describe grade, count or filler rather than what is in the box.
STOPWORDS = {
    "recycle",
    "recyle",
    "good",
    "pcs",
    "pc",
    "and",
    "more",
    "the",
    "for",
    "with",
    "style",
    "unsorted",
    "mix",
    "mixed",
    "of",
    "a",
    "in",
    "new",
}

PCS_RE = re.compile(r"(\d+)\s*pcs?\b", re.IGNORECASE)
DATE_TAG_RE = re.compile(r"^(\d\d)-(\d\d)-(\d{4})$")
TOKEN_RE = re.compile(r"[a-z0-9']+")
# Titles misspell it ("Recyle", "Recycle4") and put it anywhere ("Abbie Recycle Tees").
RECYCLE_RE = re.compile(r"\brecyc?le\d*\b", re.IGNORECASE)
MIXED_RE = re.compile(r"\brecyc?le\d*\s*(?:&|\+|and)\s*good\b", re.IGNORECASE)


def fetch_catalog() -> list[dict]:
    products: list[dict] = []
    page = 1
    while True:
        url = f"{STORE}/products.json?limit=250&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)["products"]
        if not batch:
            return products
        products.extend(batch)
        page += 1
        time.sleep(1)


def store_today() -> dt.date:
    return dt.datetime.now(STORE_TZ).date()


def lot_date(product: dict) -> dt.date | None:
    for tag in product["tags"]:
        if m := DATE_TAG_RE.match(tag):
            return dt.date(int(m[3]), int(m[1]), int(m[2]))
    return None


def grade(title: str) -> str:
    if MIXED_RE.search(title):
        return "mixed"
    if RECYCLE_RE.search(title):
        return "recycle"
    return "good"


def terms(title: str) -> set[str]:
    words = TOKEN_RE.findall(PCS_RE.sub(" ", title.lower()))
    return {w for w in words if w not in STOPWORDS and not w.isdigit() and len(w) > 1}


def is_box(product: dict) -> bool:
    return (
        product["product_type"] not in SKIP_TYPES
        and PCS_RE.search(product["title"]) is not None
    )


def demand_model(products: list[dict], days: int, today: dt.date):
    """Sell-out rate per title term over lots dated in the last `days` days.

    Rates are smoothed toward the store-wide rate so a term seen twice cannot
    dominate. Returns (baseline rate, term -> smoothed rate).
    """
    cutoff = today - dt.timedelta(days=days)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = sold = 0
    for p in products:
        d = lot_date(p)
        if not is_box(p) or d is None or d < cutoff:
            continue
        gone = not p["variants"][0]["available"]
        total += 1
        sold += gone
        for w in terms(p["title"]):
            counts[w][0] += 1
            counts[w][1] += gone
    baseline = sold / total if total else 0.2
    prior = 10
    rates = {
        w: (s + prior * baseline) / (n + prior)
        for w, (n, s) in counts.items()
        if n >= 3
    }
    return baseline, rates


def ship_estimate(grams: int, cfg: dict, fuel_pct: float) -> float | None:
    if grams <= 0:
        return None
    lb = math.ceil(grams / 453.59237)
    table = cfg["rates_by_lb"]
    if lb > len(table):
        return None
    base = table[lb - 1] + cfg["residential_surcharge"]
    return round(base * (1 + fuel_pct / 100) * cfg["ship_factor"], 2)


@dataclass(frozen=True)
class Filters:
    trend: tuple[str, ...] = ()
    min_pcs: int = 20
    max_pcs: int = 0  # 0 = no limit
    target_cog: float = 2.00
    max_cog: float = 4.00
    max_price: float = 0  # 0 = no limit
    no_vip: bool = False
    days: int = 60
    fuel: float | None = None  # None = the reference file's fuel surcharge


def parse_terms(text: str) -> tuple[str, ...]:
    return tuple(t.strip().lower() for t in text.split(",") if t.strip())


def load_shipping() -> dict:
    return json.loads(SHIPPING.read_text())


def score_boxes(products: list[dict], cfg: dict, f: Filters, today: dt.date):
    """Return (store-wide sell-out rate, ranked boxes) for in-stock boxes passing `f`."""
    baseline, rates = demand_model(products, f.days, today)
    fuel = cfg["fuel_surcharge_pct"] if f.fuel is None else f.fuel
    rows = []
    for p in products:
        v = p["variants"][0]
        if not is_box(p) or not v["available"]:
            continue
        vip = "VIP_Product" in p["tags"]
        if vip and f.no_vip:
            continue
        pcs = int(PCS_RE.search(p["title"])[1])
        price = float(v["price"])
        ship = ship_estimate(v["grams"], cfg, fuel)
        if ship is None:
            continue
        landed = price + ship
        g = grade(p["title"])
        usable = pcs * GRADE_YIELD[g]
        cog = landed / pcs
        cog_usable = landed / usable
        if pcs < f.min_pcs or (f.max_pcs and pcs > f.max_pcs):
            continue
        if cog_usable > f.max_cog or (f.max_price and price > f.max_price):
            continue
        box_terms = terms(p["title"])
        known = [rates[w] for w in box_terms if w in rates]
        demand = (sum(known) / len(known) / baseline) if known and baseline else 1.0
        hits = [
            t
            for t in f.trend
            if re.search(rf"\b{re.escape(t)}\b", p["title"], re.IGNORECASE)
        ]
        trend_boost = 1 + 0.25 * min(len(hits), 2)
        d = lot_date(p)
        rows.append(
            {
                "title": p["title"],
                "url": f"{STORE}/products/{p['handle']}",
                "price": price,
                "compare_at": float(v["compare_at_price"])
                if v["compare_at_price"]
                else None,
                "pcs": pcs,
                "grade": g,
                "lbs": round(v["grams"] / 453.59237, 1),
                "ship_est": ship,
                "landed": round(landed, 2),
                "cog_per_pc": round(cog, 2),
                "cog_per_usable_pc": round(cog_usable, 2),
                "demand": round(demand, 2),
                "trend_hits": hits,
                "vip": vip,
                "lot_date": d.isoformat() if d else None,
                # Boxes at or under the target cost compete on demand alone; dearer ones
                # are discounted in proportion to how far over the target they are.
                "score": round(
                    demand * trend_boost * min(1.0, f.target_cog / cog_usable), 3
                ),
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["cog_per_usable_pc"]))
    return baseline, rows


def print_table(rows, baseline, cfg, args):
    print(f"# Raghouse boxes: best value to {cfg['destination_zip']}\n")
    print(
        f"Shipping: UPS Ground zone {cfg['zone']} list rate + ${cfg['residential_surcharge']:.2f} residential"
        f" + {args.fuel:g}% fuel, x{cfg['ship_factor']:g} calibration. "
        f"Store-wide sell-out rate, last {args.days} days: {baseline:.0%}.\n"
    )
    print(
        "| # | Box | Grade | Pcs | Price | Ship est | Landed | $/pc | $/usable pc | Demand | Trend | VIP |"
    )
    print(
        "|---|-----|-------|-----|-------|----------|--------|------|-------------|--------|-------|-----|"
    )
    for i, r in enumerate(rows[: args.top], 1):
        price = f"${r['price']:.0f}"
        if r["compare_at"]:
            price += f" (was ${r['compare_at']:.0f})"
        print(
            f"| {i} | [{r['title']}]({r['url']}) | {r['grade']} | {r['pcs']} | {price} | ${r['ship_est']:.0f} ({r['lbs']:g} lb)"
            f" | ${r['landed']:.0f} | ${r['cog_per_pc']:.2f} | ${r['cog_per_usable_pc']:.2f} | {r['demand']:.2f}x"
            f" | {', '.join(r['trend_hits']) or '-'} | {'yes' if r['vip'] else ''} |"
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--trend", default="", help="comma-separated resale trend terms to boost"
    )
    ap.add_argument("--min-pcs", type=int, default=20)
    ap.add_argument("--max-pcs", type=int, default=0, help="0 = no limit")
    ap.add_argument(
        "--target-cog",
        type=float,
        default=2.00,
        help="landed $ per usable piece that counts as a good buy",
    )
    ap.add_argument(
        "--max-cog",
        type=float,
        default=4.00,
        help="drop boxes above this landed $ per usable piece",
    )
    ap.add_argument(
        "--max-price", type=float, default=0, help="max box price, 0 = no limit"
    )
    ap.add_argument("--no-vip", action="store_true", help="drop VIP-only boxes")
    ap.add_argument("--days", type=int, default=60, help="sell-out history window")
    ap.add_argument(
        "--fuel",
        type=float,
        help="UPS Ground fuel surcharge %% (default from references)",
    )
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument(
        "--json", action="store_true", help="print every ranked box as JSON"
    )
    ap.add_argument(
        "--catalog", type=Path, help="read a saved products list instead of crawling"
    )
    args = ap.parse_args()

    cfg = load_shipping()
    if args.fuel is None:
        args.fuel = cfg["fuel_surcharge_pct"]
    filters = Filters(
        trend=parse_terms(args.trend),
        min_pcs=args.min_pcs,
        max_pcs=args.max_pcs,
        target_cog=args.target_cog,
        max_cog=args.max_cog,
        max_price=args.max_price,
        no_vip=args.no_vip,
        days=args.days,
        fuel=args.fuel,
    )
    products = json.loads(args.catalog.read_text()) if args.catalog else fetch_catalog()
    baseline, rows = score_boxes(products, cfg, filters, store_today())
    if args.json:
        json.dump({"baseline_sellout": baseline, "boxes": rows}, sys.stdout, indent=2)
        print()
    else:
        print_table(rows, baseline, cfg, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
