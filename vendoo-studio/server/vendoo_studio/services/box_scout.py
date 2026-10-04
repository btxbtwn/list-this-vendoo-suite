"""Keep a buy list of wholesale clothing boxes ready without anyone asking for it.

Every few hours Studio crawls Raghouse and Thrift Vintage Fashion, refreshes the
trending words once a week and the resale price of each promising theme once a
fortnight with the listing model's web search (the same one sold comps use), and picks the boxes worth buying
within the seller's budget. The crawl, scoring and buy list live in the box-scout
skill's script, loaded from the skills directory, so Studio and the skill agree.

Nothing here buys anything. The Sourcing page links to each store's cart with the
picks already in it; the seller reviews and pays there.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import re
import sys
import threading
import urllib.error
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from vendoo_studio.config import skills_dir, user_data_root

log = logging.getLogger("vendoo_studio.box_scout")

REFRESH_INTERVAL = timedelta(hours=6)
TREND_MAX_AGE = timedelta(days=7)
RESALE_MAX_AGE = timedelta(days=14)
RESEARCH_THEMES = 24  # themes priced per refresh at most
RESEARCH_BATCH = 12  # themes per web-search request
MODEL_TIMEOUT_SEC = 240
KEEP_LOTS = 80  # ranked lots kept in the snapshot for the page
ZONE_CHART_MAX_AGE = timedelta(days=30)
RECENT_ZIPS = 4

DEFAULT_PREFS = {"budget": 300.0, "min_roi": 1.0, "raghouse_vip": False, "zip": "70115", "recent_zips": ["70115"]}

TRENDS_PROMPT = (
    "You track what secondhand and vintage clothing sells fastest on eBay, Poshmark, Depop "
    "and Mercari. Search the live web for this month's resale trend reports, marketplace "
    "trend pages and reseller \"what's selling\" posts from the last 30 days. Return JSON "
    'only: {"terms":["carhartt","y2k"]} with 10 to 20 lowercase terms of one or two words: '
    "brands, eras, themes and garment types, spelled the way wholesale lot titles spell "
    'them (for example "harley", "cartoon", "workwear", "90s"). No commentary.'
)

RESALE_PROMPT = (
    "You price wholesale clothing lots for a reseller. For each category below, search sold "
    "listings from the last 90 days on eBay, Poshmark, Depop and Mercari and estimate what "
    "ONE typical piece from a mixed wholesale lot of that category sells for: the median "
    "piece, not the best finds. Return JSON only: "
    '{"prices":[{"theme":"<exactly as given>","per_piece":12,"low":8,"high":20,'
    '"evidence":["https://www.ebay.com/itm/..."]}]}. Copy each theme exactly as given. '
    "Skip a theme you cannot price rather than guessing. Do not invent prices or URLs."
)

_state_lock = threading.Lock()
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
    state["prefs"] = {**DEFAULT_PREFS, **state["prefs"]}
    state.setdefault("trend", {"terms": [], "updated_at": None, "source": None})
    state.setdefault("resale", {})
    state.setdefault("zone_charts", {})
    state.setdefault("snapshot", None)
    # Sourcing snapshots are disposable caches; rebuild when the plan format changes.
    if state["snapshot"] and "store_buy_lists" not in state["snapshot"]:
        state["snapshot"] = None
    return state


def _write_state(state: dict) -> None:
    with _state_lock:
        path = state_path()
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
    except ValueError:
        return None


def set_prefs(
    *,
    budget: float | None = None,
    min_roi: float | None = None,
    raghouse_vip: bool | None = None,
    zip: str | None = None,
) -> dict:
    state = read_state()
    prefs = state["prefs"]
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


def clean_prices(raw: list, asked: set[str]) -> dict[str, dict]:
    prices: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("theme") or "").strip().lower()
        try:
            per_piece = float(item.get("per_piece"))
        except (TypeError, ValueError):
            continue
        if name not in asked or not 1 <= per_piece <= 500:
            continue
        evidence = [str(url) for url in item.get("evidence") or [] if str(url).startswith("http")]
        prices[name] = {
            "per_piece": round(per_piece, 2),
            "low": item.get("low") if isinstance(item.get("low"), int | float) else None,
            "high": item.get("high") if isinstance(item.get("high"), int | float) else None,
            "evidence": evidence[:5],
        }
    return prices


async def _research_trends() -> tuple[list[str], str | None]:
    payload, source = await _ask(TRENDS_PROMPT, "What is selling right now?", "terms")
    return (clean_terms(payload["terms"]) if payload else []), source


async def _research_prices(themes: list[str], examples: dict[str, str]) -> tuple[dict[str, dict], str | None]:
    lines = "\n".join(f"- {t} (example lot: {examples.get(t, t)})" for t in themes)
    payload, source = await _ask(RESALE_PROMPT, f"Categories:\n{lines}", "prices")
    return (clean_prices(payload["prices"], set(themes)) if payload else {}), source


# --- Refresh --------------------------------------------------------------------------------


def _fresh_resale(state: dict, now: datetime) -> dict[str, float]:
    fresh = {}
    for name, entry in state["resale"].items():
        age = _age(entry.get("updated_at"), now)
        if age is not None and age < RESALE_MAX_AGE:
            fresh[name] = entry["per_piece"]
    return fresh


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


def _zones(state: dict, cfg: dict, dest_zip: str, now: datetime, errors: dict[str, str]) -> dict[str, int]:
    """Each store's shipping zone to `dest_zip`, from USPS charts kept for a month."""
    zones = {}
    for store, info in cfg["stores"].items():
        origin = info["origin_zip3"]
        cached = state["zone_charts"].get(origin)
        age = _age(cached and cached.get("fetched_at"), now)
        if age is None or age >= ZONE_CHART_MAX_AGE:
            try:
                chart = scout().fetch_zone_chart(origin)
                cached = state["zone_charts"][origin] = {"chart": chart, "fetched_at": now.isoformat()}
            except FETCH_ERRORS as exc:
                if not cached:
                    errors.setdefault(store, f"Could not read the USPS zone chart for {info['origin']}: {exc}")
                    continue
        zone = scout().zone_for(cached["chart"], dest_zip)
        if zone is None:
            errors.setdefault(store, f"{dest_zip} is outside the 48 contiguous states the shipping rates cover.")
            continue
        zones[store] = zone
    return zones


def _calibration() -> dict[str, dict]:
    """How the seller's own sales from each store compare with the resale estimates."""
    from vendoo_studio.database import SessionLocal
    from vendoo_studio.services.boxes import resale_calibration

    db = SessionLocal()
    try:
        return resale_calibration(db)
    finally:
        db.close()


def refresh(*, recrawl: bool = True, research: bool = True) -> dict:
    """Crawl, research what is stale, rebuild the buy list and save it. Returns the snapshot.

    ``recrawl=False`` reuses the last crawl, for a new ZIP, budget or VIP setting.
    """
    with _refresh_lock:
        s = scout()
        now = _now()
        state = read_state()
        prefs = state["prefs"]
        errors: dict[str, str] = {}
        cfg = s.load_shipping()
        zones = _zones(state, cfg, prefs["zip"], now, errors)
        catalogs = {k: v for k, v in _crawl(errors, recrawl=recrawl).items() if k in zones}
        can_research = research and research_available()

        trend_age = _age(state["trend"].get("updated_at"), now)
        if can_research and (trend_age is None or trend_age >= TREND_MAX_AGE):
            terms, source = asyncio.run(_research_trends())
            if terms:
                state["trend"] = {"terms": terms, "updated_at": now.isoformat(), "source": source}

        filters = s.Filters(trend=tuple(state["trend"]["terms"]), include_vip=prefs["raghouse_vip"])
        calibration = _calibration()
        factors = {store: c["factor"] for store, c in calibration.items() if c["factor"] is not None}
        baselines, rows = s.score_lots(catalogs, cfg, zones, filters, _fresh_resale(state, now), factors)

        if can_research:
            fresh = _fresh_resale(state, now)
            missing = s.research_themes([r for r in rows if r["theme"] not in fresh], limit=RESEARCH_THEMES)
            examples = {}
            for row in rows:
                examples.setdefault(row["theme"], row["title"])
            for start in range(0, len(missing), RESEARCH_BATCH):
                batch = missing[start : start + RESEARCH_BATCH]
                prices, source = asyncio.run(_research_prices(batch, examples))
                for name, entry in prices.items():
                    state["resale"][name] = {**entry, "updated_at": now.isoformat(), "source": source}
            baselines, rows = s.score_lots(catalogs, cfg, zones, filters, _fresh_resale(state, now), factors)

        plan = s.buy_list(rows, cfg, budget=prefs["budget"], min_roi=prefs["min_roi"])
        store_plans = {
            store: s.buy_list([r for r in rows if r["store"] == store], cfg,
                              budget=prefs["budget"], min_roi=prefs["min_roi"])
            for store in s.STORES
        }
        evidence = {name: entry.get("evidence", []) for name, entry in state["resale"].items()}
        for lot in [*rows, *(p for choice in [plan, *store_plans.values()]
                              for c in choice["carts"] for p in c["lots"])]:
            lot["evidence"] = evidence.get(lot["theme"], [])
        state["snapshot"] = {
            "updated_at": now.isoformat(),
            "destination_zip": prefs["zip"],
            "stores": {
                store: {
                    "name": s.STORES[store]["name"],
                    "error": errors.get(store),
                    "sellout": baselines.get(store),
                    "zone": zones.get(store),
                }
                for store in s.STORES
            },
            "research": can_research,
            "priced_themes": len(_fresh_resale(state, now)),
            "shipping": {
                "residential_surcharge": cfg["residential_surcharge"],
                "fuel_surcharge_pct": cfg["fuel_surcharge_pct"],
                "fuel_surcharge_as_of": cfg["fuel_surcharge_as_of"],
            },
            "assumptions": {
                "sell_through": s.BASE_SELL_THROUGH,
                "fees": s.MARKETPLACE_FEES,
                "grade_yield": s.GRADE_YIELD,
            },
            "buy_list": plan,
            "store_buy_lists": store_plans,
            "lots": rows[:KEEP_LOTS],
            "calibration": calibration,
        }
        _write_state(state)
        return state["snapshot"]


def refreshing() -> bool:
    return _refresh_lock.locked()


def refresh_in_background(*, recrawl: bool = True) -> bool:
    """Start a refresh unless one is running. Returns whether one was started."""
    if refreshing():
        return False

    def _run() -> None:
        try:
            refresh(recrawl=recrawl)
        except Exception:
            log.exception("Sourcing refresh failed")

    threading.Thread(target=_run, name="sourcing-refresh", daemon=True).start()
    return True


def refresh_is_due(*, now: datetime | None = None) -> bool:
    snapshot = read_state()["snapshot"]
    age = _age(snapshot and snapshot.get("updated_at"), now or _now())
    return age is None or age >= REFRESH_INTERVAL


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
