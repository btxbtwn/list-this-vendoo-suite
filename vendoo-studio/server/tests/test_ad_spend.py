"""Ad spend entries, their share of a range, and the local-only routes."""
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db, load_models
from vendoo_studio.routes.ad_spend import router
from vendoo_studio.services.ad_spend import summarize_ads
from vendoo_studio.services.inventory_analytics import inventory_analytics


def entry(market="poshmark", start=date(2026, 9, 1), end=date(2026, 9, 10), spend=50.0, **figures):
    return SimpleNamespace(marketplace=market, start_date=start, end_date=end, spend=spend,
                           clicks=figures.get("clicks"), orders=figures.get("orders"),
                           revenue=figures.get("revenue"))


def test_all_time_counts_every_entry_and_reads_the_dashboard_figures():
    ads = summarize_ads(
        [entry(clicks=100, orders=2, revenue=150), entry("etsy", spend=20)],
        start=None, marketplace_revenue={"poshmark": 500.0}, profit=300.0,
    )
    assert ads["spend"] == 70
    assert ads["profit_after_ads"] == 230
    posh, etsy = ads["marketplaces"]
    assert posh == {"id": "poshmark", "entries": 1, "spend": 50, "clicks": 100, "orders": 2,
                    "revenue": 150, "roas": 3.0, "cost_per_click": 0.5,
                    "sales_revenue": 500, "spend_percent": 10.0}
    # Figures the seller left blank stay unknown rather than reading as zero.
    assert etsy["revenue"] is None and etsy["roas"] is None and etsy["cost_per_click"] is None
    assert etsy["spend_percent"] is None


def test_a_range_carries_only_the_days_it_covers():
    ads = summarize_ads(
        [entry(spend=100, revenue=40), entry(start=date(2026, 8, 1), end=date(2026, 8, 31))],
        start=datetime(2026, 9, 7, tzinfo=UTC), marketplace_revenue={}, profit=None,
    )
    # Four of the ten days fall in the range; the August entry falls outside it.
    assert ads["spend"] == 40
    assert ads["marketplaces"][0]["revenue"] == 16
    assert ads["marketplaces"][0]["entries"] == 1
    assert ads["profit_after_ads"] is None


def test_no_entries_reports_no_marketplaces():
    assert summarize_ads([], start=None, marketplace_revenue={}, profit=10.0) == {
        "spend": 0, "profit_after_ads": 10, "marketplaces": [],
    }


@pytest.fixture
def workspace():
    load_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield db, client
    engine.dispose()


def test_routes_save_edit_and_remove_entries(workspace):
    db, client = workspace
    body = {"marketplace": "etsy", "start_date": "2026-09-01", "end_date": "2026-09-30",
            "spend": 31, "clicks": 62, "orders": 1, "revenue": 45}
    created = client.post("/api/analytics/ads", json=body)
    assert created.status_code == 201
    assert created.json()["roas"] == 1.45
    assert created.json()["cost_per_click"] == 0.5
    entry_id = created.json()["id"]

    edited = client.put(f"/api/analytics/ads/{entry_id}", json={**body, "spend": 45, "notes": "Sept statement"})
    assert edited.json()["roas"] == 1.0 and edited.json()["notes"] == "Sept statement"
    assert [row["spend"] for row in client.get("/api/analytics/ads").json()] == [45]

    ads = inventory_analytics(db, range_id="all", now=datetime(2026, 10, 1, tzinfo=UTC))["ads"]
    assert ads["spend"] == 45 and ads["marketplaces"][0]["id"] == "etsy"

    assert client.delete(f"/api/analytics/ads/{entry_id}").json() == {"ok": True}
    assert client.get("/api/analytics/ads").json() == []
    assert client.delete(f"/api/analytics/ads/{entry_id}").status_code == 404


@pytest.mark.parametrize("change", [
    {"marketplace": "ebay"},
    {"end_date": "2026-08-31"},
    {"spend": -1},
    {"clicks": -3},
    {"unexpected": True},
])
def test_routes_reject_bad_entries(workspace, change):
    _db, client = workspace
    body = {"marketplace": "poshmark", "start_date": "2026-09-01", "end_date": "2026-09-07", "spend": 10}
    assert client.post("/api/analytics/ads", json={**body, **change}).status_code == 422
