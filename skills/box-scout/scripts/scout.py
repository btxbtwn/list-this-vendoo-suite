#!/usr/bin/env python3
"""Find the wholesale clothing boxes worth buying on raghouse.com and thriftvintagefashion.com.

Both stores are Shopify shops, so their public /products.json feeds list every lot
with its price, stock and shipping weight. This script turns each in-stock lot into
the same shape, estimates UPS Ground shipping to the destination in
references/shipping.json, scores demand from what has sold out, and, given resale
prices per theme, picks a buy list within a budget. Standard library only.

    python3 scout.py --trend "carhartt,y2k,harley" --top 25
    python3 scout.py --resale resale.json --budget 300    # adds the buy list
    python3 scout.py --themes                             # themes that need a resale price
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import re
import sys
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from zoneinfo import ZoneInfo

USER_AGENT = "Mozilla/5.0 (box-scout; personal sourcing research)"
SHIPPING = Path(__file__).resolve().parent.parent / "references" / "shipping.json"
ZONE_CHART_URL = (
    "https://postcalc.usps.com/DomesticZoneChart/GetZoneChart?zipCode3Digit={origin}&shippingDate={date}"
)
# The rate table covers the 48 contiguous states: not Alaska, Hawaii, Puerto Rico or
# military and territory ZIPs.
OUTSIDE_48 = re.compile(r"^(?:00[6-9]|09\d|340|96[2-9]|99[5-9])")

STORES = {
    "raghouse": {"name": "Raghouse", "url": "https://raghouse.com", "tz": "America/Phoenix"},
    "tvf": {"name": "Thrift Vintage Fashion", "url": "https://thriftvintagefashion.com", "tz": "America/New_York"},
}

# Share of a lot that is resellable. Raghouse sells "Recycle" lots as needing TLC;
# TVF grades lots A/B/C and says a plain lot "may contain up to 15% Grade B".
# Starting assumptions: replace them with your own counts after unpacking a few.
GRADE_YIELD = {
    "good": 0.90,
    "mixed": 0.75,
    "recycle": 0.60,
    "a": 0.95,
    "ab": 0.85,
    "b": 0.60,
    "bc": 0.55,
    "c": 0.50,
}

# Pieces per pound, for lots sold by weight (TVF bales and "by LB" mixes).
# A tee weighs about 5 oz, a sweatshirt about a pound, jeans a little over, a jacket 1.5 lb.
PCS_PER_LB = {"tee": 3.0, "shirt": 2.0, "sweat": 1.0, "bottoms": 0.9, "jacket": 0.6, "mix": 1.6}
PACKAGING_LB = 1.0

# Planning assumptions, not measurements of resale marketplace demand.
BASE_SELL_THROUGH = 0.50
MARKETPLACE_FEES = 0.20  # fees and payment processing on each sale
OPERATING_COST_PER_PIECE = 2.00  # planning allowance per usable piece; replace with actual costs
REWORK_GRADES = {"mixed", "recycle", "b", "bc", "c"}

SKIP_TYPES = {"Singles", "Membership", "Accessories", "Shoes"}
SKIP_TITLE_RE = re.compile(r"gift card|membership|auction items|sample (?:tee|sweats) stock", re.I)

PCS_RE = re.compile(r"(\d+)\s*pcs?\b", re.I)
UNIT_RE = re.compile(
    r"(\d+)\s*(?:pcs?|pieces?|tees?|t-shirts?|sweatshirts?|sweats|hoodies?|shirts?|jerseys?|pairs?|jackets?)\b",
    re.I,
)
LB_RE = re.compile(r"(\d+)\s*(?:lbs?|pounds?)\b", re.I)
DATE_TAG_RE = re.compile(r"^(\d\d)-(\d\d)-(\d{4})$")
TOKEN_RE = re.compile(r"[a-z0-9']+")
# Raghouse titles misspell it ("Recyle", "Recycle4") and put it anywhere ("Abbie Recycle Tees").
RECYCLE_RE = re.compile(r"\brecyc?le\d*\b", re.I)
MIXED_RE = re.compile(r"\brecyc?le\d*\s*(?:&|\+|and)\s*good\b", re.I)
RESALE_RE = re.compile(r"Estimated Resale Value:?\s*\+?\s*\$\s*(\d+(?:\.\d+)?)", re.I)

STOPWORDS = {
    "recycle", "recyle", "good", "pcs", "pc", "pieces", "piece", "and", "more", "the", "for",
    "with", "style", "unsorted", "mix", "mixed", "of", "a", "in", "new", "wholesale", "bale",
    "lb", "lbs", "pounds", "pound", "by", "grade", "default", "title",
}
# Words stripped from a lot's title to name its theme: what a buyer would search for.
THEME_DROP_RE = re.compile(
    r"\([^)]*\)|~|\bwholesale\b|\bbales?\b|\bby\s+(?:lb|pound)s?\b|\b\d+\s*(?:pcs?|pieces?|lbs?|pounds?)\b"
    r"|\brecyc?le\d*\b|\bgood\b|\bunsorted\b|\b[abc](?:/[abc])?\s+grade\b|\bgrade\s+[abc]\b"
    r"|\bdeal zone\b|\b\d+%\s*off\b|\bdefault title\b|\ball sizes\b",
    re.I,
)


@dataclass(frozen=True)
class Filters:
    trend: tuple[str, ...] = ()
    min_pcs: int = 10
    max_price: float = 0  # 0 = no limit
    include_vip: bool = False
    target_cog: float = 2.00  # landed $ per usable piece that ranks as a good buy without a resale price
    days: int = 60  # Raghouse sell-out history window
    sell_through: float = BASE_SELL_THROUGH
    fees: float = MARKETPLACE_FEES
    cost_per_piece: float = OPERATING_COST_PER_PIECE


def parse_terms(text: str) -> tuple[str, ...]:
    return tuple(t.strip().lower() for t in text.split(",") if t.strip())


def load_shipping() -> dict:
    return json.loads(SHIPPING.read_text())


def store_today(store: str) -> dt.date:
    return dt.datetime.now(ZoneInfo(STORES[store]["tz"])).date()


def fetch_catalog(store: str) -> list[dict]:
    products: list[dict] = []
    page = 1
    while True:
        url = f"{STORES[store]['url']}/products.json?limit=250&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)["products"]
        if not batch:
            return products
        products.extend(batch)
        page += 1
        time.sleep(1)


def terms(text: str) -> set[str]:
    words = TOKEN_RE.findall(PCS_RE.sub(" ", text.lower()))
    return {w for w in words if w not in STOPWORDS and not w.isdigit() and len(w) > 1}


def theme(text: str) -> str:
    cleaned = THEME_DROP_RE.sub(" ", text.lower())
    cleaned = re.sub(r"[/|+·]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -&,.")
    return cleaned


def garment(text: str) -> str:
    t = text.lower()
    if re.search(r"jacket|windbreaker|fleece|coat|outerwear|vest", t):
        return "jacket"
    if re.search(r"sweat|hood|crewneck", t):
        return "sweat"
    if re.search(r"jean|denim|pant|jort|short|overall|bottom|skirt", t):
        return "bottoms"
    if re.search(r"tee|t-shirt|tank", t):
        return "tee"
    if re.search(r"shirt|flannel|polo|jersey|blouse|top", t):
        return "shirt"
    return "mix"


def _date_tag(product: dict) -> dt.date | None:
    for tag in product["tags"]:
        if m := DATE_TAG_RE.match(tag):
            return dt.date(int(m[3]), int(m[1]), int(m[2]))
    return None


def fetch_zone_chart(origin_zip3: str) -> dict[str, int]:
    """USPS zones from a 3-digit origin: destination 3-digit prefix -> zone."""
    url = ZONE_CHART_URL.format(origin=origin_zip3, date=dt.date.today().strftime("%m%%2F%d%%2F%Y"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    chart: dict[str, int] = {}
    for key, rows in payload.items():
        if not key.startswith("Column") or not isinstance(rows, list):
            continue
        for row in rows:
            zone = re.match(r"\d+", row.get("Zone") or "")
            bounds = [int(part) for part in re.findall(r"\d{3}", row.get("ZipCodes") or "")]
            if not zone or not bounds:
                continue
            for prefix in range(bounds[0], bounds[-1] + 1):
                chart[f"{prefix:03d}"] = int(zone[0])
    if not chart:
        raise ValueError(f"USPS returned no zones for origin {origin_zip3}")
    return chart


def valid_zip(text: str) -> bool:
    return bool(re.fullmatch(r"\d{5}", text or ""))


def zone_for(chart: dict[str, int], dest_zip: str) -> int | None:
    """The ground zone for a destination, or None outside the 48 contiguous states."""
    if not valid_zip(dest_zip) or OUTSIDE_48.match(dest_zip):
        return None
    zone = chart.get(dest_zip[:3])
    # Zone 1 is local delivery; the Ground tables start at zone 2.
    return None if zone is None or zone > 8 else max(zone, 2)


def ship_estimate(lbs: float, cfg: dict, store: str, zone: int) -> float | None:
    if lbs <= 0:
        return None
    store_cfg = cfg["stores"][store]
    carrier = store_cfg.get("carrier", "ups")
    rates = cfg[f"{carrier}_ground_by_zone"][str(zone)]
    billable = math.ceil(lbs)
    if billable > len(rates):
        return None
    residential = store_cfg.get("residential_surcharge", cfg["residential_surcharge"])
    fuel_pct = store_cfg.get("fuel_surcharge_pct", cfg["fuel_surcharge_pct"])
    base = rates[billable - 1] + residential
    fuel = 1 + fuel_pct / 100
    return round(base * fuel * store_cfg["ship_factor"], 2)


# --- Store adapters: each returns one dict per buyable lot, in stock or not ---------


def raghouse_lots(products: list[dict]) -> list[dict]:
    lots = []
    for p in products:
        m = PCS_RE.search(p["title"])
        if p["product_type"] in SKIP_TYPES or not p["product_type"] or not m:
            continue
        v = p["variants"][0]
        grade = "mixed" if MIXED_RE.search(p["title"]) else "recycle" if RECYCLE_RE.search(p["title"]) else "good"
        lots.append({
            "store": "raghouse",
            "variant_id": v["id"],
            "title": p["title"],
            "url": f"{STORES['raghouse']['url']}/products/{p['handle']}",
            "available": v["available"],
            "price": float(v["price"]),
            "compare_at": float(v["compare_at_price"]) if v["compare_at_price"] else None,
            "pcs": int(m[1]),
            "pcs_estimated": "~" in p["title"],
            "grade": grade,
            "lbs": v["grams"] / 453.59237,
            "lbs_estimated": False,
            "vip": "VIP_Product" in p["tags"],
            "listed": (_date_tag(p) or None),
            "seller_resale": None,
            "theme": theme(p["title"]),
        })
    return lots


def _tvf_grade(text: str) -> str:
    t = text.lower()
    for pattern, grade in (
        (r"\bb/c\b", "bc"),
        (r"\ba/b\b", "ab"),
        (r"\bc grade\b|\bgrade c\b", "c"),
        (r"\bb grade\b|\bgrade b\b", "b"),
        (r"\ba grade\b|\bgrade a\b", "a"),
    ):
        if re.search(pattern, t):
            return grade
    return "good"


def tvf_lots(products: list[dict]) -> list[dict]:
    lots = []
    for p in products:
        if SKIP_TITLE_RE.search(p["title"]):
            continue
        body = html.unescape(re.sub(r"<[^>]+>", " ", p.get("body_html") or ""))
        resale = RESALE_RE.search(body)
        kind = garment(p["title"])
        for v in p["variants"]:
            price = float(v["price"])
            if price <= 0:
                continue
            variant = "" if v["title"] == "Default Title" else v["title"]
            full = f"{p['title']} {variant}".strip()
            pcs, estimated, lbs_stated = None, False, None
            if m := UNIT_RE.search(variant) or UNIT_RE.search(p["title"]):
                pcs = int(m[1])
            elif m := re.match(r"\s*(\d+)\s", p["title"]):
                pcs = int(m[1])  # "200 Modern Graphic T-Shirts"
            if lb := LB_RE.search(variant) or LB_RE.search(p["title"]):
                lbs_stated = float(lb[1])
                if pcs is None:
                    pcs, estimated = round(lbs_stated * PCS_PER_LB[kind]), True
            if not pcs:
                continue
            if lbs_stated:
                lbs, lbs_estimated = lbs_stated + PACKAGING_LB, False
            elif v["grams"] > 0:
                lbs, lbs_estimated = v["grams"] / 453.59237, False
            else:
                lbs, lbs_estimated = pcs / PCS_PER_LB[kind] + PACKAGING_LB, True
            lots.append({
                "store": "tvf",
                "variant_id": v["id"],
                "title": f"{p['title']} · {variant}" if variant else p["title"],
                "url": f"{STORES['tvf']['url']}/products/{p['handle']}?variant={v['id']}",
                "available": v["available"],
                "price": price,
                "compare_at": float(v["compare_at_price"]) if v.get("compare_at_price") else None,
                "pcs": pcs,
                "pcs_estimated": estimated,
                "grade": _tvf_grade(full),
                "lbs": lbs,
                "lbs_estimated": lbs_estimated,
                "vip": False,
                "listed": None,
                "seller_resale": float(resale[1]) if resale else None,
                "theme": theme(full),
            })
    return lots


ADAPTERS = {"raghouse": raghouse_lots, "tvf": tvf_lots}


# --- Scoring --------------------------------------------------------------------------


def demand_rates(lots: list[dict], days: int, today: dt.date) -> tuple[float, dict[str, float]]:
    """Sell-out rate per title term, smoothed toward the store-wide rate.

    Raghouse lots carry a listing date, so only the last `days` days count; TVF
    restocks the same products, so all of its lots count.
    """
    cutoff = today - dt.timedelta(days=days)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = sold = 0
    for lot in lots:
        if lot["listed"] is not None and lot["listed"] < cutoff:
            continue
        gone = not lot["available"]
        total += 1
        sold += gone
        for w in terms(lot["title"]):
            counts[w][0] += 1
            counts[w][1] += gone
    baseline = sold / total if total else 0.2
    prior = 10
    rates = {w: (s + prior * baseline) / (n + prior) for w, (n, s) in counts.items() if n >= 3}
    return baseline, rates


def score_lots(
    catalogs: dict[str, list[dict]],
    cfg: dict,
    zones: dict[str, int],
    f: Filters,
    resale: dict[str, float] | None = None,
    resale_factor: dict[str, float] | None = None,
    *, resale_low: dict[str, float] | None = None,
):
    """Return {store: baseline sell-out rate} and every in-stock lot passing `f`, ranked.

    `catalogs` maps a store id to its raw products and `zones` each store to its
    shipping zone for the destination. `resale` maps a theme to the typical sold
    price of one piece; lots with a price get an expected profit and ROI.
    `resale_factor` scales those prices per store, for a seller whose own sales
    from that store's boxes run below the estimates. Stronger past sales never
    lift forecasts above current researched prices.
    """
    resale = resale or {}
    resale_low = resale_low or {}
    resale_factor = resale_factor or {}
    baselines: dict[str, float] = {}
    rows = []
    for store, products in catalogs.items():
        lots = ADAPTERS[store](products)
        baseline, rates = demand_rates(lots, f.days, store_today(store))
        baselines[store] = baseline
        for lot in lots:
            if not lot["available"] or lot["pcs"] < f.min_pcs:
                continue
            if lot["vip"] and not f.include_vip:
                continue
            if f.max_price and lot["price"] > f.max_price:
                continue
            ship = ship_estimate(lot["lbs"], cfg, store, zones[store])
            if ship is None:
                continue
            threshold = cfg["stores"][store]["free_shipping_over"]
            if threshold is not None and lot["price"] >= threshold:
                ship = 0.0
            known = [rates[w] for w in terms(lot["title"]) if w in rates]
            demand = (sum(known) / len(known) / baseline) if known and baseline else 1.0
            hits = [t for t in f.trend if re.search(rf"\b{re.escape(t)}\b", lot["title"], re.I)]
            usable = lot["pcs"] * GRADE_YIELD[lot["grade"]]
            row = {
                **lot,
                "listed": lot["listed"].isoformat() if lot["listed"] else None,
                "lbs": round(lot["lbs"], 1),
                "usable_pcs": round(usable, 1),
                "demand": round(demand, 2),
                "trend_hits": hits,
                "resale_low": resale_low.get(lot["theme"], resale.get(lot["theme"])),
            }
            # Historical underperformance can reduce forecasts; it cannot lift
            # them above current comparable-sale/asking-price evidence.
            factor = min(1.0, resale_factor.get(store, 1.0))
            per_piece = resale.get(lot["theme"])
            row["resale_factor"] = factor
            if row["resale_low"] is not None:
                row["resale_low"] = round(row["resale_low"] * factor, 2)
            rows.append(price_lot(row, ship, round(per_piece * factor, 2) if per_piece else per_piece,
                                  sell_through=f.sell_through, fees=f.fees, cost_per_piece=f.cost_per_piece))
    for row in rows:
        boost = 1 + 0.25 * min(len(row["trend_hits"]), 2)
        if row["roi"] is not None:
            row["score"] = round((1 + row["roi"]) * boost, 3)
        else:
            # Without a resale price, cheap usable pieces in demand rank highest.
            row["score"] = round(row["demand"] * boost * min(1.0, f.target_cog / row["cog_per_usable_pc"]), 3)
    rows.sort(key=lambda r: (r["roi"] is None, -r["score"], r["cog_per_usable_pc"]))
    return baselines, rows


def price_lot(
    row: dict, ship: float, per_piece: float | None,
    *, sell_through: float = BASE_SELL_THROUGH, fees: float = MARKETPLACE_FEES,
    cost_per_piece: float = OPERATING_COST_PER_PIECE,
) -> dict:
    """Fill in landed cost and, when the theme has a resale price, profit and ROI."""
    landed = row["price"] + ship
    operating_cost = row["usable_pcs"] * cost_per_piece
    row.update({
        "ship_est": round(ship, 2),
        "landed": round(landed, 2),
        "cog_per_pc": round(landed / row["pcs"], 2),
        "cog_per_usable_pc": round(landed / row["usable_pcs"], 2),
        "resale_per_pc": per_piece,
        "sell_through": round(sell_through, 2),
        "expected_revenue": None,
        "expected_profit": None,
        "operating_cost": round(operating_cost, 2),
        "break_even_pcs": None,
        "downside_profit": None,
        "roi": None,
    })
    if per_piece:
        revenue = per_piece * row["usable_pcs"] * sell_through * (1 - fees)
        row["expected_revenue"] = round(revenue, 2)
        row["expected_profit"] = round(revenue - operating_cost - landed, 2)
        row["roi"] = round((revenue - operating_cost - landed) / landed, 2)
        row["break_even_pcs"] = math.ceil((landed + operating_cost) / (per_piece * (1 - fees)))
        low = min(row.get("resale_low") or per_piece, per_piece)
        row["downside_profit"] = round(low * row["usable_pcs"] * sell_through / 2 * (1 - fees)
                                       - operating_cost - landed, 2)
    return row


def research_themes(rows: list[dict], limit: int = 24) -> list[str]:
    """Themes worth pricing, best demand first per store, shared evenly between stores."""
    if limit <= 0:
        return []
    best: dict[str, dict[str, float]] = {}
    for row in rows:
        weight = row["demand"] * (1 + 0.25 * min(len(row["trend_hits"]), 2))
        store = best.setdefault(row["store"], {})
        store[row["theme"]] = max(store.get(row["theme"], 0.0), weight)
    ranked = [[theme for theme, _ in sorted(themes.items(), key=lambda kv: -kv[1])]
              for themes in best.values()]
    result: list[str] = []
    # Alternate stores so a larger catalog cannot use the entire research allowance.
    for index in range(max((len(themes) for themes in ranked), default=0)):
        for themes in ranked:
            if index < len(themes) and themes[index] not in result:
                result.append(themes[index])
                if len(result) >= limit:
                    return result
    return result


def buy_list(
    rows: list[dict], cfg: dict, *, budget: float, min_roi: float = 1.0,
    sell_through: float = BASE_SELL_THROUGH, fees: float = MARKETPLACE_FEES,
    cost_per_piece: float = OPERATING_COST_PER_PIECE, include_rework: bool = False,
) -> dict:
    """Pick by incremental return, one per theme, within `budget`.

    Evaluate shipping on the complete proposed cart. Also consider two-lot
    bundles that unlock free shipping even when neither lot qualifies alone.
    This is a greedy recommendation, not an exhaustive portfolio optimizer.
    """
    picks: list[dict] = []
    seen: set[str] = set()
    priced = [r for r in rows if r["roi"] is not None and (include_rework or r["grade"] not in REWORK_GRADES)]

    def evaluate(additions: list[dict]) -> list[dict]:
        proposed = [*picks, *additions]
        free_stores = {
            store for store in STORES
            if (threshold := cfg["stores"][store]["free_shipping_over"]) is not None
            and sum(p["price"] for p in proposed if p["store"] == store) >= threshold
        }
        return [price_lot(dict(p), 0.0 if p["store"] in free_stores else p["ship_est"],
                          p["resale_per_pc"], sell_through=sell_through, fees=fees,
                          cost_per_piece=cost_per_piece) for p in proposed]

    while True:
        remaining = [r for r in priced if r["theme"] not in seen]
        options = ([row] for row in remaining)

        def bundles():
            for store in STORES:
                threshold = cfg["stores"][store]["free_shipping_over"]
                subtotal = sum(p["price"] for p in picks if p["store"] == store)
                if threshold is None or subtotal >= threshold:
                    continue
                mine = [r for r in remaining if r["store"] == store and subtotal + r["price"] < threshold]
                for index, first in enumerate(mine):
                    for second in mine[index + 1:]:
                        if first["theme"] != second["theme"] and subtotal + first["price"] + second["price"] >= threshold:
                            yield [first, second]

        best = None
        best_rank = None
        current_total = sum(p["landed"] for p in picks)
        current_profit = sum(p["expected_profit"] for p in picks)
        for additions in chain(options, bundles()):
            candidate = evaluate(additions)
            total = round(sum(p["landed"] for p in candidate), 2)
            if total > budget or any(p["roi"] < min_roi or p["downside_profit"] < 0 for p in candidate):
                continue
            profit = sum(p["expected_profit"] for p in candidate)
            extra_cost = total - current_total
            extra_profit = profit - current_profit
            rank = (extra_profit / extra_cost if extra_cost > 0 else float("inf"), extra_profit, -total)
            if best_rank is None or rank > best_rank:
                best, best_rank = candidate, rank
        if best is None:
            break
        picks = best
        seen = {p["theme"] for p in picks}
    carts = []
    for store in STORES:
        mine = [p for p in picks if p["store"] == store]
        if not mine:
            continue
        subtotal = sum(p["price"] for p in mine)
        threshold = cfg["stores"][store]["free_shipping_over"]
        free = threshold is not None and subtotal >= threshold
        if free:
            for p in mine:
                price_lot(p, 0.0, p["resale_per_pc"], sell_through=sell_through, fees=fees,
                          cost_per_piece=cost_per_piece)
        carts.append({
            "store": store,
            "name": STORES[store]["name"],
            "subtotal": round(subtotal, 2),
            "shipping": round(sum(p["ship_est"] for p in mine), 2),
            "free_shipping": free,
            "free_shipping_over": threshold,
            "cart_url": f"{STORES[store]['url']}/cart/" + ",".join(f"{p['variant_id']}:1" for p in mine),
            "lots": mine,
        })
    total = sum(p["landed"] for c in carts for p in c["lots"])
    profit = sum(p["expected_profit"] for c in carts for p in c["lots"])
    selected = {(p["store"], p["variant_id"]) for p in picks}
    exclusions = {}
    for row in rows:
        if (row["store"], row["variant_id"]) in selected:
            continue
        if not include_rework and row["grade"] in REWORK_GRADES:
            reason = "rework"
        elif row["roi"] is None:
            reason = "needs_research"
        elif row["theme"] in seen:
            reason = "same_theme"
        else:
            candidate = evaluate([row])
            lot = candidate[-1]
            if lot["roi"] < min_roi:
                reason = "return_target"
            elif lot["downside_profit"] < 0:
                reason = "downside"
            elif round(sum(p["landed"] for p in candidate), 2) > budget:
                reason = "budget"
            else:
                reason = "alternative"
        exclusions[f"{row['store']}:{row['variant_id']}"] = reason
    return {"budget": budget, "total": round(total, 2), "expected_profit": round(profit, 2),
            "carts": carts, "exclusions": exclusions}


# --- CLI ------------------------------------------------------------------------------


def print_table(rows, baselines, dest_zip, top):
    print(f"# Wholesale boxes to {dest_zip}\n")
    rates = ", ".join(f"{STORES[s]['name']} {b:.0%}" for s, b in baselines.items())
    print(f"Sell-out rates: {rates}.\n")
    print("| # | Store | Lot | Pcs | Landed | $/usable pc | Resale/pc | Profit | ROI | Demand | Trend |")
    print("|---|-------|-----|-----|--------|-------------|-----------|--------|-----|--------|-------|")
    for i, r in enumerate(rows[:top], 1):
        resale = f"${r['resale_per_pc']:.0f}" if r["resale_per_pc"] else "-"
        profit = f"${r['expected_profit']:.0f}" if r["expected_profit"] is not None else "-"
        roi = f"{r['roi']:.0%}" if r["roi"] is not None else "-"
        print(
            f"| {i} | {r['store']} | [{r['title']}]({r['url']}) | {r['pcs']}{'~' if r['pcs_estimated'] else ''}"
            f" | ${r['landed']:.0f} | ${r['cog_per_usable_pc']:.2f} | {resale} | {profit} | {roi}"
            f" | {r['demand']:.2f}x | {', '.join(r['trend_hits']) or '-'} |"
        )


def print_buy_list(plan):
    print(f"\n## Buy list (budget ${plan['budget']:.0f})\n")
    if not plan["carts"]:
        print("Nothing clears the ROI bar within the budget.")
        return
    for cart in plan["carts"]:
        ship = "free shipping" if cart["free_shipping"] else f"~${cart['shipping']:.0f} shipping"
        print(f"**{cart['name']}**: ${cart['subtotal']:.0f} + {ship}. Cart: {cart['cart_url']}")
        for p in cart["lots"]:
            print(f"- [{p['title']}]({p['url']}): ${p['landed']:.0f} landed, ~${p['expected_profit']:.0f} profit ({p['roi']:.0%})")
    print(f"\nTotal ${plan['total']:.0f}, expected profit ${plan['expected_profit']:.0f}.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stores", default="raghouse,tvf", help="comma-separated: raghouse, tvf")
    ap.add_argument("--zip", default="70115", help="5-digit ZIP the boxes ship to")
    ap.add_argument("--trend", default="", help="comma-separated resale trend terms to boost")
    ap.add_argument("--min-pcs", type=int, default=10)
    ap.add_argument("--max-price", type=float, default=0, help="max lot price, 0 = no limit")
    ap.add_argument("--vip", action="store_true", help="include Raghouse VIP-only boxes")
    ap.add_argument("--resale", type=Path, help='JSON {"theme": price per piece}; adds profit, ROI and a buy list')
    ap.add_argument("--budget", type=float, default=300)
    ap.add_argument("--min-roi", type=float, default=1.0, help="1.0 = expected profit at least equals cost")
    ap.add_argument("--sell-through", type=float, default=BASE_SELL_THROUGH, help="share of usable pieces expected to sell, 0–1")
    ap.add_argument("--fees", type=float, default=MARKETPLACE_FEES, help="marketplace and payment fee share, 0–1")
    ap.add_argument("--cost-per-piece", type=float, default=OPERATING_COST_PER_PIECE,
                    help="operating cost allowance for each usable piece, including prep, labor and sale expenses")
    ap.add_argument("--include-rework", action="store_true", help="allow damaged/rework grades in recommendations")
    ap.add_argument("--themes", action="store_true", help="print the themes that most need a resale price")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json", action="store_true", help="print every ranked lot as JSON")
    ap.add_argument("--catalog", type=Path, help='read saved catalogs {"raghouse": [...], "tvf": [...]}')
    args = ap.parse_args()
    if not 0 < args.sell_through <= 1 or not 0 <= args.fees < 1:
        ap.error("--sell-through must be above 0 and at most 1; --fees must be at least 0 and below 1")
    if not math.isfinite(args.budget) or args.budget <= 0 or not math.isfinite(args.min_roi) or args.min_roi < 0:
        ap.error("--budget must be positive and --min-roi must be nonnegative")
    if not math.isfinite(args.cost_per_piece) or args.cost_per_piece < 0:
        ap.error("--cost-per-piece must be a finite, nonnegative amount")

    cfg = load_shipping()
    if not valid_zip(args.zip):
        ap.error("--zip takes a 5-digit ZIP code")
    stores = [s for s in parse_terms(args.stores) if s in STORES]
    zones = {}
    for store in stores:
        zones[store] = zone_for(fetch_zone_chart(cfg["stores"][store]["origin_zip3"]), args.zip)
        if zones[store] is None:
            ap.error(f"{args.zip} is outside the 48 contiguous states the rate table covers")
    if args.catalog:
        saved = json.loads(args.catalog.read_text())
        catalogs = {s: saved[s] for s in stores if s in saved}
    else:
        catalogs = {s: fetch_catalog(s) for s in stores}
    filters = Filters(
        trend=parse_terms(args.trend), min_pcs=args.min_pcs, max_price=args.max_price, include_vip=args.vip,
        sell_through=args.sell_through, fees=args.fees, cost_per_piece=args.cost_per_piece,
    )
    resale = json.loads(args.resale.read_text()) if args.resale else {}
    baselines, rows = score_lots(catalogs, cfg, zones, filters, resale)
    if args.themes:
        print("\n".join(research_themes(rows)))
        return 0
    plan = buy_list(rows, cfg, budget=args.budget, min_roi=args.min_roi,
                    sell_through=args.sell_through, fees=args.fees, cost_per_piece=args.cost_per_piece,
                    include_rework=args.include_rework) if resale else None
    if args.json:
        json.dump({"baselines": baselines, "lots": rows, "buy_list": plan}, sys.stdout, indent=2)
        print()
        return 0
    print_table(rows, baselines, args.zip, args.top)
    if plan:
        print_buy_list(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
