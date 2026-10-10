"""Keep a buy list of wholesale clothing boxes ready without anyone asking for it.

Every few hours Studio crawls Raghouse and Thrift Vintage Fashion, refreshes the
trending words and comparable sales once a week with the listing model's web
search (the same one sold comps use), and picks qualifying boxes
within the seller's budget. The crawl, scoring and buy list live in the box-scout
skill's script, loaded from the skills directory, so Studio and the skill agree.

Nothing here buys anything. The Sourcing page links to each store's cart with the
picks already in it; the seller reviews and pays there.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import math
import re
import statistics
import sys
import threading
import urllib.error
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

from vendoo_studio.config import skills_dir, user_data_root
from vendoo_studio.services.inventory_analytics import AnalyticsItem
from vendoo_studio.services.sourcing_seasonality import planning_context, research_context
from vendoo_studio.services.sold_comps import (
    MIN_CONFIDENT_COMPS,
    extract_live_price,
    extract_sold_price,
    marketplace_from_url,
    trim_outliers,
)

log = logging.getLogger("vendoo_studio.box_scout")

REFRESH_INTERVAL = timedelta(hours=6)
TREND_MAX_AGE = timedelta(days=7)
RESALE_MAX_AGE = timedelta(days=7)
RESEARCH_RETRY = timedelta(days=1)  # before asking again about a theme the web could not price
RESEARCH_THEMES = 24  # themes priced per refresh at most
RESEARCH_BATCH = 4  # each theme needs several sold and active source pages
MODEL_TIMEOUT_SEC = 240
ZONE_CHART_MAX_AGE = timedelta(days=30)
RECENT_ZIPS = 4
# Bump when the snapshot's shape changes: a snapshot written by another build is
# a stale cache, dropped and rebuilt rather than served to a page that cannot
# read it.
SNAPSHOT_FORMAT = 4

DEFAULT_PREFS = {
    "budget": 300.0, "min_roi": 1.0, "raghouse_vip": False, "zip": "70115", "recent_zips": ["70115"],
    "sell_through": 0.5, "fees": 0.2,
    "cost_per_piece": 2.0,
    "ready_in_weeks": 4, "selling_window_weeks": 4,
}
PLAN_PREFS = ("budget", "min_roi", "raghouse_vip", "zip", "sell_through", "fees", "cost_per_piece",
              "ready_in_weeks", "selling_window_weeks")

TRENDS_PROMPT = (
    "You track what secondhand and vintage clothing sells fastest on eBay, Poshmark, Depop "
    "and Mercari. Plan sourcing for the supplied future selling window. Search the live web "
    "for seasonal resale trends, upcoming holidays, marketplace reports and "
    "trend pages and reseller \"what's selling\" posts from the last 30 days. Return JSON "
    'only: {"terms":["carhartt","y2k"]} with 10 to 20 lowercase terms of one or two words: '
    "brands, eras, themes and garment types, spelled the way wholesale lot titles spell "
    'them (for example "harley", "cartoon", "workwear", "90s"). No commentary.'
)

RESALE_PROMPT = (
    "You price wholesale clothing lots for a reseller. For each category below, search sold "
    "listings from the last 90 days on eBay, Poshmark, Depop and Mercari and estimate what "
    "ONE typical piece from a mixed wholesale lot of that category sells for. Look for "
    "comparable everyday pieces with matching garment type, brand tier, era and condition, "
    "not premium finds, multi-item bundles, new-with-tags pieces or rare examples. "
    "Give each listing's own title, word for word: listings whose title shows another "
    "garment, a bundle or new with tags are discarded. "
    "Return actual sold listings, never active asking prices or supplier resale claims. "
    "Collect at least 3 distinct sales per theme in the last 30 days, 5 when you can, so "
    "discarded ones do not sink the theme. Older sales within "
    "90 days can provide context, but cannot qualify a theme or set today's price. "
    "Use USD item prices excluding shipping, and exclude "
    "accepted offers when the actual price is hidden. Return JSON only: "
    '{"prices":[{"theme":"<exactly as given>","comps":[{"url":"https://www.ebay.com/itm/...",'
    '"title":"Cartoon T-shirt","sold_at":"YYYY-MM-DD","currency":"USD",'
    '"snippet":"Exact source text showing this item sold and its actual USD sale price"}],'
    '"active":[{"url":"https://www.ebay.com/itm/...","title":"Comparable T-shirt",'
    '"currency":"USD","snippet":"Exact source text showing an item for sale and asking price"}]}]}. '
    "Also collect 3 comparable active listings per theme to check current competition. "
    "Use ordinary items, excluding condition or rarity mismatches, for both samples. "
    "Copy each theme exactly as given. Open sources and quote the sale evidence; dates "
    "must be sale dates, not crawl or listing dates. Skip themes without enough evidence. "
    "Do not invent sales, dates, snippets or URLs. Trends never prove that an item will sell."
)

_state_lock = threading.RLock()
_refresh_lock = threading.Lock()
# The last crawl, so a new ZIP or budget re-prices boxes without asking the stores again.
_catalogs: dict[str, list[dict]] = {}
_timer_stop = threading.Event()
_timer: threading.Thread | None = None


# --- The skill's script -----------------------------------------------------------------


@lru_cache(maxsize=1)
def scout() -> ModuleType:
    path = skills_dir() / "box-scout" / "scripts" / "scout.py"
    spec = importlib.util.spec_from_file_location("box_scout_skill", path)
    if spec is None or spec.loader is None or not path.is_file():
        raise RuntimeError(f"The box-scout skill is missing at {path}.")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up in sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- State file ---------------------------------------------------------------------------


def state_path() -> Path:
    return user_data_root() / "sourcing.json"


def read_state() -> dict:
    with _state_lock:
        try:
            state = json.loads(state_path().read_text())
        except (OSError, json.JSONDecodeError):
            state = {}
    state.setdefault("prefs", {})
    state["prefs"] = {**DEFAULT_PREFS, **{k: v for k, v in state["prefs"].items() if k in DEFAULT_PREFS}}
    state.setdefault("trend", {"terms": [], "updated_at": None, "source": None})
    state.setdefault("resale", {})
    state.setdefault("zone_charts", {})
    state.setdefault("snapshot", None)
    # Sourcing snapshots are disposable caches; rebuild when the plan format changes.
    if state["snapshot"] and (state["snapshot"].get("format") != SNAPSHOT_FORMAT
                              or not all(key in state["snapshot"].get("preferences", {}) for key in PLAN_PREFS)):
        state["snapshot"] = None
    return state


def _write_state(state: dict, *, preserve_prefs: bool = False) -> None:
    with _state_lock:
        path = state_path()
        if preserve_prefs:
            try:
                latest = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                latest = {}
            state["prefs"] = {**DEFAULT_PREFS, **latest.get("prefs", state["prefs"])}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        tmp.replace(path)


def _now() -> datetime:
    return datetime.now(UTC)


def _age(iso: str | None, now: datetime) -> timedelta | None:
    if not iso:
        return None
    try:
        return now - datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None


def set_prefs(
    *,
    budget: float | None = None,
    min_roi: float | None = None,
    raghouse_vip: bool | None = None,
    zip: str | None = None,
    sell_through: float | None = None,
    fees: float | None = None,
    cost_per_piece: float | None = None,
    ready_in_weeks: int | None = None,
    selling_window_weeks: int | None = None,
) -> dict:
    with _state_lock:
        state = read_state()
        prefs = state["prefs"]
        for name, value in (("budget", budget), ("min_roi", min_roi), ("sell_through", sell_through),
                            ("fees", fees), ("cost_per_piece", cost_per_piece)):
            if value is not None and (not math.isfinite(value) or
                                     (value <= 0 if name in {"budget", "sell_through"} else value < 0) or
                                     (name == "sell_through" and value > 1) or (name == "fees" and value >= 1)):
                raise ValueError(f"Invalid {name.replace('_', ' ')}.")
        for name, value, minimum in (("ready_in_weeks", ready_in_weeks, 0),
                                      ("selling_window_weeks", selling_window_weeks, 1)):
            if value is not None:
                if type(value) is not int or not minimum <= value <= 26:
                    raise ValueError(f"Invalid {name.replace('_', ' ')}.")
                prefs[name] = value
        if zip is not None:
            if not scout().valid_zip(zip):
                raise ValueError("A ZIP code is five digits.")
            if scout().OUTSIDE_48.match(zip):
                raise ValueError("Shipping estimates cover the 48 contiguous states only.")
            prefs["zip"] = zip
            prefs["recent_zips"] = [zip, *[z for z in prefs["recent_zips"] if z != zip]][:RECENT_ZIPS]
        if budget is not None:
            prefs["budget"] = float(budget)
        if min_roi is not None:
            prefs["min_roi"] = float(min_roi)
        if raghouse_vip is not None:
            prefs["raghouse_vip"] = bool(raghouse_vip)
        if sell_through is not None:
            prefs["sell_through"] = float(sell_through)
        if fees is not None:
            prefs["fees"] = float(fees)
        if cost_per_piece is not None:
            prefs["cost_per_piece"] = float(cost_per_piece)
        _write_state(state)
        return prefs


# --- Web research with the connected models ---------------------------------------------


def _json_object(text: str) -> dict | None:
    candidates = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text or "", re.I)
    if match := re.search(r"\{[\s\S]*\}", text or ""):
        candidates.append(match.group())
    for raw in candidates:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def research_available() -> bool:
    from vendoo_studio.services.comp_research import model_search

    return model_search() is not None


async def _ask(system: str, user: str, key: str) -> tuple[dict | None, str | None]:
    """Ask the listing model, with web search, for JSON holding `key`."""
    from vendoo_studio.services.comp_research import model_search

    search = model_search()
    if search is None:
        return None, None
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        result = await asyncio.wait_for(search.search(messages), timeout=MODEL_TIMEOUT_SEC)
    except Exception as exc:  # a failed lookup is retried on the next refresh
        log.warning("%s web search for sourcing failed: %s", search.label, exc)
        return None, None
    payload = _json_object(str(result.get("answer") or ""))
    if payload and isinstance(payload.get(key), list):
        return payload, search.label
    return None, None


def clean_terms(raw: list) -> list[str]:
    terms: list[str] = []
    for item in raw:
        term = re.sub(r"\s+", " ", str(item)).strip().lower()
        if term and len(term) <= 30 and len(term.split()) <= 3 and term not in terms:
            terms.append(term)
    return terms[:20]


def _listing_identity(url: str, marketplace: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return f"{marketplace}:{path.rsplit('/', 1)[-1] if marketplace == 'eBay' else path}"


def validate_research(raw: list, asked: set[str], *, now: datetime | None = None) -> dict[str, dict]:
    """The dated, distinct, explicitly sold USD examples and comparable asking prices
    reported by research, per asked theme, whether or not they are enough to price it.
    An example counts only when its title fits the theme (the skill's `sale_mismatch`).

    This validates the supplied evidence, not the source pages themselves. The
    seller can inspect every retained example; no probability of sale is inferred.
    """
    today = (now or _now()).date()
    research: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("theme") or "").strip().lower()
        if name not in asked or not isinstance(item.get("comps"), list):
            continue
        comps = []
        seen = set()
        for comp in item["comps"]:
            if not isinstance(comp, dict) or comp.get("currency") != "USD":
                continue
            url = str(comp.get("url") or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
            try:
                marketplace = marketplace_from_url(url)
                identity = _listing_identity(url, marketplace)
            except ValueError:
                continue
            if marketplace not in {"eBay", "Poshmark", "Mercari", "Depop"} or identity in seen:
                continue
            snippet = str(comp.get("snippet") or "").strip()
            price = extract_sold_price(snippet)
            try:
                sold_at = date.fromisoformat(str(comp.get("sold_at") or ""))
            except ValueError:
                continue
            age = (today - sold_at).days
            if not 0 <= age <= 90 or price is None or not math.isfinite(price) or not 1 <= price <= 500:
                continue
            title = str(comp.get("title") or "").strip()
            if not title or scout().sale_mismatch(name, title, snippet):
                continue
            seen.add(identity)
            comps.append({"url": url, "title": title[:200], "sold_at": sold_at.isoformat(),
                          "price": price, "marketplace": marketplace, "snippet": snippet[:1500], "currency": "USD"})
        active = []
        for comp in item.get("active", []) if isinstance(item.get("active"), list) else []:
            if not isinstance(comp, dict) or comp.get("currency") != "USD":
                continue
            url = str(comp.get("url") or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
            try:
                marketplace = marketplace_from_url(url)
                identity = _listing_identity(url, marketplace)
            except ValueError:
                continue
            price = extract_live_price(str(comp.get("snippet") or ""))
            title = str(comp.get("title") or "").strip()
            if identity in seen or marketplace not in {"eBay", "Poshmark", "Mercari", "Depop"} or not title:
                continue
            if scout().sale_mismatch(name, title, str(comp.get("snippet") or "")):
                continue
            if price is None or not math.isfinite(price) or not 1 <= price <= 500:
                continue
            seen.add(identity)
            active.append({"url": url, "title": title[:200], "price": price, "marketplace": marketplace,
                           "snippet": str(comp["snippet"])[:1500], "currency": "USD"})
        research[name] = {"comps": comps, "active": active[:8]}
    return research


def price_evidence(web: dict, own: list[dict], *, now: datetime | None = None) -> dict | None:
    """One theme's price from the seller's own sales and validated web sales
    together: the median of distinct sales within 30 days, at least
    MIN_CONFIDENT_COMPS of them, capped by the asking-price median when enough
    current listings were found. Older sales within 90 days stay as context."""
    today = (now or _now()).date()
    comps = [c for c in own if 0 <= (today - date.fromisoformat(c["sold_at"])).days <= 90 and 1 <= c["price"] <= 500]
    comps += [c for c in web.get("comps") or [] if isinstance(c, dict) and c.get("url")]
    comps.sort(key=lambda comp: comp["sold_at"], reverse=True)
    recent = [c for c in comps if (today - date.fromisoformat(c["sold_at"])).days <= 30]
    kept_prices = trim_outliers([c["price"] for c in recent])
    recent = [c for c in recent if c["price"] in kept_prices][:16]
    if len(recent) < MIN_CONFIDENT_COMPS:
        return None
    comps = [*recent, *(c for c in comps if (today - date.fromisoformat(c["sold_at"])).days > 30)][:16]
    values = [comp["price"] for comp in recent]
    active = web.get("active") or []
    sold_median = statistics.median(values)
    active_median = statistics.median(trim_outliers([c["price"] for c in active])) if len(active) >= MIN_CONFIDENT_COMPS else None
    return {
        "per_piece": round(min(sold_median, active_median) if active_median is not None else sold_median, 2),
        "sold_median": round(sold_median, 2), "active_median": active_median, "active": active,
        "low": min(values), "high": max(values), "comps": comps,
    }


def clean_prices(raw: list, asked: set[str], *, now: datetime | None = None,
                 own: dict[str, list[dict]] | None = None) -> dict[str, dict]:
    """The themes reported research and the seller's own sales can price, with their prices."""
    research = validate_research(raw, asked, now=now)
    prices = {}
    for name in asked:
        priced = price_evidence(research.get(name, {}), (own or {}).get(name, []), now=now)
        if priced:
            prices[name] = priced
    return prices


async def _research_trends(context: dict) -> tuple[list[str], str | None]:
    payload, source = await _ask(TRENDS_PROMPT, research_context(context), "terms")
    return (clean_terms(payload["terms"]) if payload else []), source


async def _research_prices(themes: list[str], examples: dict[str, str], context: dict) -> tuple[dict[str, dict], str | None]:
    lines = "\n".join(f"- {t} (example lot: {examples.get(t, t)})" for t in themes)
    payload, source = await _ask(RESALE_PROMPT, f"{research_context(context)}\nCategories:\n{lines}", "prices")
    return (validate_research(payload["prices"], set(themes)) if payload else {}), source


# --- Refresh --------------------------------------------------------------------------------


def _fresh_research(state: dict, now: datetime, own: dict[str, list[dict]]) -> dict[str, dict]:
    """Themes with enough current evidence: cached web research under a week old,
    rechecked as its sale dates age out and against the theme its examples must fit,
    together with the seller's own sales."""
    fresh = {}
    for name in set(state["resale"]) | set(own):
        entry = _cached_research(state, name, now, RESALE_MAX_AGE)
        if entry:
            entry = {**entry, **{key: [c for c in entry.get(key) or [] if isinstance(c, dict) and not scout().sale_mismatch(
                name, str(c.get("title") or ""), str(c.get("snippet") or ""))] for key in ("comps", "active")}}
        if priced := price_evidence(entry or {}, own.get(name, []), now=now):
            fresh[name] = {**(entry or {"updated_at": now.isoformat(), "source": OWN_SOURCE}), **priced}
    return fresh


def _cached_research(state: dict, name: str, now: datetime, max_age: timedelta) -> dict | None:
    entry = state["resale"].get(name)
    age = _age(entry and entry.get("updated_at"), now)
    return entry if age is not None and timedelta(0) <= age < max_age else None


FETCH_ERRORS = (urllib.error.URLError, TimeoutError, ValueError, KeyError)


def _crawl(errors: dict[str, str], *, recrawl: bool) -> dict[str, list[dict]]:
    catalogs = {}
    for store in scout().STORES:
        if not recrawl and store in _catalogs:
            catalogs[store] = _catalogs[store]
            continue
        try:
            catalogs[store] = _catalogs[store] = scout().fetch_catalog(store)
        except FETCH_ERRORS as exc:
            errors[store] = f"{scout().STORES[store]['name']} did not return its catalog: {exc}"
            log.warning(errors[store])
    return catalogs


def _zone_chart(state: dict, origin: str, now: datetime) -> dict | None:
    """The USPS chart from a 3-digit origin, kept for a month; None when unreadable."""
    cached = state["zone_charts"].get(origin)
    age = _age(cached and cached.get("fetched_at"), now)
    if age is None or age >= ZONE_CHART_MAX_AGE:
        try:
            chart = scout().fetch_zone_chart(origin)
            cached = state["zone_charts"][origin] = {"chart": chart, "fetched_at": now.isoformat()}
        except FETCH_ERRORS as exc:
            log.warning("Could not read the USPS zone chart for origin %s: %s", origin, exc)
    return cached["chart"] if cached else None


def _zones(state: dict, cfg: dict, catalogs: dict[str, list[dict]], dest_zip: str, now: datetime,
           errors: dict[str, str]) -> dict[str, int | dict[str, int]]:
    """Each store's shipping zone to `dest_zip`: one zone for a warehouse store,
    {state: zone} for a marketplace whose lots ship from each seller's state."""
    s = scout()
    zones: dict[str, int | dict[str, int]] = {}
    for store, info in cfg["stores"].items():
        origins = s.origin_zip3s(store, catalogs.get(store, []), cfg)
        by_origin: dict[str, int] = {}
        unreadable = []
        for label, origin in origins.items():
            chart = _zone_chart(state, origin, now)
            if chart is None:
                unreadable.append(label or info["origin"])
                continue
            zone = s.zone_for(chart, dest_zip)
            if zone is None:
                errors.setdefault(store, f"{dest_zip} is outside the 48 contiguous states the shipping rates cover.")
                break
            by_origin[label] = zone
        else:
            if origins and not by_origin:
                errors.setdefault(store, f"Could not read the USPS zone chart for {', '.join(unreadable)}.")
            elif by_origin:
                zones[store] = by_origin[""] if list(by_origin) == [""] else by_origin
    return zones


OWN_SOURCE = "Your sales"


def _own_sales() -> list[AnalyticsItem]:
    """The seller's recorded sales, read from the same rows Analytics uses."""
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.services.inventory_analytics import load_rows

    db = SessionLocal()
    try:
        return [item for item in load_rows(db) if item.status == "sold" and item.sold_price and item.sold_at]
    finally:
        db.close()


def own_evidence(sales: list[AnalyticsItem], themes: set[str]) -> dict[str, list[dict]]:
    """The seller's own sales that sold the kind of piece each theme names, newest
    first, as comps alongside the web's. A sale matches a theme when it is the same
    garment and carries every style the theme names."""
    s = scout()
    parts = [(item, *s.theme_parts(item.title)) for item in sales]
    evidence: dict[str, list[dict]] = {}
    for name in themes:
        matches = [item for item, styles, garment in parts if s.theme_matches(name, styles, garment)]
        if matches:
            evidence[name] = [{
                "url": "", "conversation_id": item.conversation_id, "title": item.title[:200],
                "sold_at": item.sold_at.date().isoformat(), "price": float(item.sold_price),
                "marketplace": item.marketplace, "currency": "USD",
                "snippet": f"Your sale on {item.marketplace}, recorded in Studio.",
            } for item in sorted(matches, key=lambda item: item.sold_at, reverse=True)]
    return evidence


def _lot_themes(catalogs: dict[str, list[dict]]) -> set[str]:
    s = scout()
    return {lot["theme"] for store, products in catalogs.items() for lot in s.ADAPTERS[store](products)}


def evidence(theme: str) -> dict | None:
    """Everything behind one theme's resale estimate, for the seller to inspect."""
    state = read_state()
    own = own_evidence(_own_sales(), {theme})
    entry = _fresh_research(state, _now(), own).get(theme)
    if entry is None:
        return None
    return {"theme": theme, **{key: entry.get(key) for key in (
        "per_piece", "sold_median", "active_median", "low", "high", "comps", "active", "updated_at", "source")}}


def _calibration() -> dict[str, dict]:
    """How the seller's own sales from each store compare with the resale estimates."""
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.services.boxes import resale_calibration

    db = SessionLocal()
    try:
        return resale_calibration(db)
    finally:
        db.close()


def _shipping_calibration() -> dict[str, dict]:
    """What each store charged the seller's own orders against the carrier list rate."""
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.services.boxes import shipping_calibration

    db = SessionLocal()
    try:
        return shipping_calibration(db)
    finally:
        db.close()


RAGHOUSE_VIP_MONTHLY = 64.0


def refresh(*, recrawl: bool = True, research: bool = True) -> dict:
    """Crawl, research what is stale, rebuild the buy list and save it."""
    with _refresh_lock:
        return _refresh(recrawl=recrawl, research=research)


def _refresh(*, recrawl: bool, research: bool) -> dict:
    s = scout()
    now = _now()
    state = read_state()
    prefs = state["prefs"]
    errors: dict[str, str] = {}
    cfg = s.load_shipping()
    shipping_calibration = _shipping_calibration()
    for store, entry in shipping_calibration.items():
        if entry["factor"] is not None and store in cfg["stores"]:
            cfg["stores"][store]["ship_factor"] = entry["factor"]
    crawled = _crawl(errors, recrawl=recrawl)
    zones = _zones(state, cfg, crawled, prefs["zip"], now, errors)
    catalogs = {k: v for k, v in crawled.items() if k in zones}
    can_research = research and research_available()

    context = planning_context(prefs, now)
    # Reuse current-price comps across horizons, but never reuse themes for another
    # selling window. Weekly buckets avoid repeating trend research every crawl.
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    trend_key = hashlib.sha256(json.dumps({
        "week": week, "ready": prefs["ready_in_weeks"], "duration": prefs["selling_window_weeks"],
        "groups": [{key: group[key] for key in ("category_path", "item_type", "count", "historical_median_price")}
                   for group in context["seller_history"]["groups"]],
    }, sort_keys=True).encode()).hexdigest()
    trend_age = _age(state["trend"].get("updated_at"), now)
    if (state["trend"].get("context_key") != trend_key or trend_age is None
            or trend_age < timedelta(0) or trend_age >= TREND_MAX_AGE):
        state["trend"] = {"terms": [], "updated_at": None, "source": None}
        if can_research:
            terms, source = asyncio.run(_research_trends(context))
            if terms:
                state["trend"] = {"terms": terms, "updated_at": now.isoformat(), "source": source,
                                  "context_key": trend_key}

    # Members-only Raghouse boxes are scored and researched too, so a seller who
    # is not a VIP can see what joining would add to the list.
    filters = s.Filters(trend=tuple(state["trend"]["terms"]), include_vip=True,
                        sell_through=prefs["sell_through"], fees=prefs["fees"], cost_per_piece=prefs["cost_per_piece"])
    calibration = _calibration()
    factors = {store: c["factor"] for store, c in calibration.items() if c["factor"] is not None}
    own = own_evidence(_own_sales(), _lot_themes(catalogs))
    fresh = _fresh_research(state, now, own)
    baselines, all_rows = s.score_lots(catalogs, cfg, zones, filters, {k: v["per_piece"] for k, v in fresh.items()}, factors,
                                     resale_low={k: v["low"] for k, v in fresh.items()})

    if can_research:
        research_rows = [r for r in all_rows if r["price"] <= prefs["budget"]]
        missing = s.research_themes([r for r in research_rows if r["theme"] not in fresh
                                     and _cached_research(state, r["theme"], now, RESEARCH_RETRY) is None],
                                    limit=RESEARCH_THEMES)
        examples = {}
        for row in research_rows:
            examples.setdefault(row["theme"], row["title"])
        for start in range(0, len(missing), RESEARCH_BATCH):
            batch = missing[start : start + RESEARCH_BATCH]
            prices, source = asyncio.run(_research_prices(batch, examples, context))
            for name, entry in prices.items():
                state["resale"][name] = {**entry, "updated_at": now.isoformat(), "source": source}
        fresh = _fresh_research(state, now, own)
        baselines, all_rows = s.score_lots(catalogs, cfg, zones, filters, {k: v["per_piece"] for k, v in fresh.items()}, factors,
                                         resale_low={k: v["low"] for k, v in fresh.items()})
    rows = [r for r in all_rows if prefs["raghouse_vip"] or not r["vip"]]

    planning = {"budget": prefs["budget"], "min_roi": prefs["min_roi"],
                "sell_through": prefs["sell_through"], "fees": prefs["fees"],
                "cost_per_piece": prefs["cost_per_piece"]}
    plan = s.buy_list(rows, cfg, **planning)
    store_plans = {
        store: s.buy_list([r for r in rows if r["store"] == store], cfg, **planning)
        for store in s.STORES
    }
    vip_upside = None
    if not prefs["raghouse_vip"]:
        # What the members-only Raghouse boxes would add to this same list.
        vip_plan = s.buy_list(all_rows, cfg, **planning)
        vip_upside = {
            "boxes": sum(1 for c in vip_plan["carts"] for p in c["lots"] if p["vip"]),
            "extra_profit": round(vip_plan["expected_profit"] - plan["expected_profit"], 2),
            "monthly_fee": RAGHOUSE_VIP_MONTHLY,
        }
    for lot in [*rows, *(p for choice in [plan, *store_plans.values()]
                          for c in choice["carts"] for p in c["lots"])]:
        # The examples themselves are served by `evidence` when the seller opens them.
        entry = fresh.get(lot["theme"], {})
        lot["comps_count"] = len(entry.get("comps", []))
        lot["active_median"] = entry.get("active_median")
        lot["research_at"] = entry.get("updated_at")
        lot["research_source"] = entry.get("source")
    _announce_new_picks(state["snapshot"], plan, prefs)
    state["snapshot"] = {
        "format": SNAPSHOT_FORMAT,
        "updated_at": now.isoformat(),
        "destination_zip": prefs["zip"],
        "preferences": {key: prefs[key] for key in PLAN_PREFS},
        "stores": {
            store: {"name": s.STORES[store]["name"], "error": errors.get(store),
                    "sellout": baselines.get(store),
                    "zone": zones[store] if isinstance(zones.get(store), int) else None,
                    "origins": len(zones[store]) if isinstance(zones.get(store), dict) else 1}
            for store in s.STORES
        },
        "research": can_research,
        "priced_themes": len(fresh),
        "shipping": {"residential_surcharge": cfg["residential_surcharge"],
                     "fuel_surcharge_pct": cfg["fuel_surcharge_pct"],
                     "fuel_surcharge_as_of": cfg["fuel_surcharge_as_of"],
                     "factors": {store: cfg["stores"][store]["ship_factor"] for store in s.STORES},
                     "calibration": shipping_calibration},
        "vip_upside": vip_upside,
        "assumptions": {"sell_through": prefs["sell_through"], "fees": prefs["fees"],
                        "grade_yield": s.GRADE_YIELD, "cost_per_piece": prefs["cost_per_piece"]},
        "buy_list": plan,
        "store_buy_lists": store_plans,
        "lots": rows,
        "calibration": calibration,
        "seasonality": context,
    }
    _write_state(state, preserve_prefs=True)
    return state["snapshot"]


def _announce_new_picks(previous: dict | None, plan: dict, prefs: dict) -> None:
    """Tell the seller when a box joins the buy list between two checks of the
    same plan, so a Raghouse drop is not missed while the page is closed."""
    if not previous or any(previous["preferences"].get(key) != prefs[key] for key in PLAN_PREFS):
        return
    known = {f"{p['store']}:{p['variant_id']}" for c in previous["buy_list"]["carts"] for p in c["lots"]}
    new = [p for c in plan["carts"] for p in c["lots"] if f"{p['store']}:{p['variant_id']}" not in known]
    if not new:
        return
    from vendoo_studio.desktop import notify

    first = new[0]
    more = f" and {len(new) - 1} more" if len(new) > 1 else ""
    notify(f"New on your buy list: {first['title']} ({scout().STORES[first['store']]['name']}, "
           f"${first['landed']:,.0f} landed){more}.")


def refreshing() -> bool:
    return _refresh_lock.locked()


def refresh_in_background(*, recrawl: bool = True) -> bool:
    """Start a refresh unless one is running. Returns whether one was started."""
    if not _refresh_lock.acquire(blocking=False):
        return False

    def _run() -> None:
        try:
            _refresh(recrawl=recrawl, research=True)
        except Exception:
            log.exception("Sourcing refresh failed")
        finally:
            _refresh_lock.release()

    try:
        threading.Thread(target=_run, name="sourcing-refresh", daemon=True).start()
    except Exception:
        _refresh_lock.release()
        raise
    return True


def refresh_is_due(*, now: datetime | None = None) -> bool:
    state = read_state()
    snapshot = state["snapshot"]
    if snapshot and any(snapshot["preferences"][key] != state["prefs"][key] for key in PLAN_PREFS):
        return True
    age = _age(snapshot and snapshot.get("updated_at"), now or _now())
    return age is None or age < timedelta(0) or age >= REFRESH_INTERVAL


def start_sourcing_timer() -> threading.Thread | None:
    """Refresh on startup when one is due, then every REFRESH_INTERVAL."""
    global _timer
    if _timer is not None and _timer.is_alive():
        return None

    def _run() -> None:
        while True:
            if refresh_is_due():
                try:
                    refresh()
                except Exception:
                    log.exception("Sourcing refresh failed")
            if _timer_stop.wait(timedelta(minutes=15).total_seconds()):
                return

    _timer_stop.clear()
    _timer = threading.Thread(target=_run, name="sourcing-timer", daemon=True)
    _timer.start()
    return _timer


def stop_sourcing_timer(timeout: float = 5.0) -> None:
    _timer_stop.set()
    if _timer is not None and _timer.is_alive():
        _timer.join(timeout=timeout)
