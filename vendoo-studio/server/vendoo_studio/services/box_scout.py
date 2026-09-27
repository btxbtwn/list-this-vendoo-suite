"""Rank raghouse.com clothing boxes by landed cost per usable piece and demand.

The crawl and the scoring live in the raghouse-box-scout skill's script, which
this module loads from the skills directory, so Studio and the skill always rank
boxes the same way.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
import urllib.error
from datetime import UTC, datetime
from functools import lru_cache
from types import ModuleType

from vendoo_studio.config import skills_dir

# Raghouse posts new lots a few times a day; re-crawling on every filter change
# would only repeat eight requests for the same answer.
CATALOG_TTL_SECONDS = 15 * 60

_lock = threading.Lock()
_catalog: tuple[float, datetime, list[dict]] | None = None


class ScoutUnavailable(RuntimeError):
    """Raghouse did not return its catalog."""


@lru_cache(maxsize=1)
def _scout() -> ModuleType:
    path = skills_dir() / "raghouse-box-scout" / "scripts" / "scout.py"
    spec = importlib.util.spec_from_file_location("raghouse_box_scout", path)
    if spec is None or spec.loader is None:
        raise ScoutUnavailable(f"The raghouse-box-scout skill is missing at {path}.")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up in sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_catalog(refresh: bool) -> tuple[datetime, list[dict]]:
    global _catalog
    with _lock:
        fresh = _catalog is not None and time.monotonic() - _catalog[0] < CATALOG_TTL_SECONDS
        if refresh or not fresh:
            try:
                products = _scout().fetch_catalog()
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
                raise ScoutUnavailable(f"Raghouse did not return its catalog: {exc}") from exc
            _catalog = (time.monotonic(), datetime.now(UTC), products)
        return _catalog[1], _catalog[2]


def scout_boxes(
    *,
    trend: str = "",
    min_pcs: int = 20,
    max_pcs: int = 0,
    target_cog: float = 2.0,
    max_cog: float = 4.0,
    max_price: float = 0,
    include_vip: bool = True,
    limit: int = 50,
    refresh: bool = False,
) -> dict:
    scout = _scout()
    fetched_at, products = _load_catalog(refresh)
    filters = scout.Filters(
        trend=scout.parse_terms(trend),
        min_pcs=min_pcs,
        max_pcs=max_pcs,
        target_cog=target_cog,
        max_cog=max_cog,
        max_price=max_price,
        no_vip=not include_vip,
    )
    shipping = scout.load_shipping()
    baseline, rows = scout.score_boxes(products, shipping, filters, scout.store_today())
    return {
        "fetched_at": fetched_at.isoformat(),
        "baseline_sellout": baseline,
        "sellout_days": filters.days,
        "matched": len(rows),
        "shipping": {
            "destination_zip": shipping["destination_zip"],
            "zone": shipping["zone"],
            "residential_surcharge": shipping["residential_surcharge"],
            "fuel_surcharge_pct": shipping["fuel_surcharge_pct"],
            "fuel_surcharge_as_of": shipping["fuel_surcharge_as_of"],
            "ship_factor": shipping["ship_factor"],
        },
        "boxes": rows[:limit],
    }
