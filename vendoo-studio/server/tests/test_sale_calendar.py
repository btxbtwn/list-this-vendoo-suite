"""Promotion persistence, sample gating, margin protection, and local-only routes."""
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db, load_models
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.routes.sale_calendar import router
from vendoo_studio.services.inventory_analytics import AnalyticsItem
from vendoo_studio.services.sale_calendar import SalePlan, estimated_profit, event_result, weekday_patterns

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def sale(day, *, market="ebay", cid="sold", cost=10, fees=5):
    return AnalyticsItem(cid, cid, "sold", 50, cost, "", "", 40, day,
                         NOW - timedelta(days=120), market, 20, fees)


def plan(**changes):
    return {"title": "Weekend sale", "marketplace": "ebay", "start_date": "2026-10-09",
            "end_date": "2026-10-11", "timezone": "UTC", "discount_percent": 10,
            "fee_percent": 15, "shipping_cost": 2, "minimum_profit": 5,
            "item_ids": ["active"], "notes": "", **changes}


@pytest.fixture
def workspace():
    load_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for cid, cost, markets in [("active", 10, ["ebay", "depop"]), ("no-cost", None, ["ebay"]),
                                  ("not-listed", 1, []), ("expensive", 44, ["ebay"])]:
            db.add(Conversation(id=cid, title=cid, status="active", notes=json.dumps({
                "vendooStatus": "active", "vendooMarketplaces": markets,
                "vendooDates": {"listed": "2026-06-01"},
            })))
            db.add(ListingRevision(id=cid, conversation_id=cid, source="manual",
                                   listing_json={"price": 50, "cost": cost}))
            db.add(Listing(conversation_id=cid, current_revision_id=cid))
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield db, client
    engine.dispose()


def test_local_event_lifecycle_and_snapshots(workspace):
    db, client = workspace
    response = client.post("/api/analytics/calendar", json=plan())
    assert response.status_code == 201, response.text
    eid = response.json()["id"]
    payload = client.get("/api/analytics/calendar?timezone=UTC").json()
    assert payload["events"][0]["items"][0]["estimated_profit"] == 26.25
    assert payload["events"][0]["result"] is None
    assert {item["id"] for item in payload["items"]} == {"active", "no-cost", "expensive"}
    db.get(ListingRevision, "active").listing_json = {"price": 60, "cost": 10}
    db.commit()
    assert client.get("/api/analytics/calendar").json()["events"][0]["items"][0]["price"] == 50
    assert client.put(f"/api/analytics/calendar/{eid}", json=plan(title="Revised")).status_code == 200
    assert client.patch(f"/api/analytics/calendar/{eid}/status", json={"status": "ran"}).status_code == 422
    assert client.put(f"/api/analytics/calendar/{eid}", json=plan(start_date="2020-01-03", end_date="2020-01-05")).status_code == 200
    assert client.patch(f"/api/analytics/calendar/{eid}/status", json={"status": "ran"}).status_code == 200
    assert client.put(f"/api/analytics/calendar/{eid}", json=plan()).status_code == 422
    assert db.query(Conversation).filter(Conversation.status != "active").count() == 0
    assert db.execute(Base.metadata.tables["jobs"].select()).all() == []
    assert client.delete(f"/api/analytics/calendar/{eid}").status_code == 200
    assert db.query(SaleEvent).count() == 0
    assert client.delete(f"/api/analytics/calendar/{eid}").status_code == 404


@pytest.mark.parametrize("changes", [
    {"item_ids": ["no-cost"]}, {"item_ids": ["expensive"]}, {"item_ids": ["missing"]},
    {"item_ids": ["not-listed"]}, {"marketplace": "etsy"}, {"marketplace": "all"},
    {"minimum_profit": 30}, {"item_ids": []}, {"item_ids": ["active", "active"]},
    {"end_date": "2026-10-08"}, {"end_date": "2027-10-09"}, {"discount_percent": 99},
    {"fee_percent": -1}, {"timezone": "unknown/timezone"}, {"title": "   "}, {"confirm": True},
])
def test_invalid_plans_never_save(workspace, changes):
    db, client = workspace
    assert client.post("/api/analytics/calendar", json=plan(**changes)).status_code == 422
    assert db.query(SaleEvent).count() == 0


def test_overlapping_items_and_cancellation(workspace):
    _db, client = workspace
    eid = client.post("/api/analytics/calendar", json=plan()).json()["id"]
    assert client.post("/api/analytics/calendar", json=plan()).status_code == 422
    assert client.post("/api/analytics/calendar", json=plan(marketplace="depop")).status_code == 201
    assert client.patch(f"/api/analytics/calendar/{eid}/status", json={"status": "cancelled"}).status_code == 200
    assert client.post("/api/analytics/calendar", json=plan()).status_code == 201


def test_rounding_and_zero_cost():
    assert estimated_profit({"price": 19.99, "cost": 0}, SalePlan(**plan(discount_percent=50, fee_percent=0, shipping_cost=0))) == 10
    assert estimated_profit({"price": 50, "cost": None}, SalePlan(**plan())) is None


def test_complete_weeks_sample_threshold_and_sunday_monday_window():
    start = NOW - timedelta(weeks=12)
    rows = [sale(start)]
    for week in range(12):
        rows.extend([sale(start + timedelta(weeks=week, days=6, hours=1)),
                     sale(start + timedelta(weeks=week, days=6, hours=2)),
                     sale(start + timedelta(weeks=week, hours=3))])
    rows += [sale(None), sale(NOW + timedelta(days=1)), sale(NOW)]
    ebay, depop, etsy = weekday_patterns(rows, "UTC", now=NOW)
    assert ebay["weeks"] == 12
    assert ebay["sales"] == 37
    assert ebay["suggested_start"] == "2026-10-11"
    assert ebay["suggested_end"] == "2026-10-12"
    assert depop["suggested_start"] is None and etsy["suggested_start"] is None
    assert weekday_patterns(rows[-3:], "UTC", now=NOW)[0]["suggested_start"] is None


def test_window_length_follows_the_data():
    start = NOW - timedelta(weeks=12)
    one_day = [sale(start + timedelta(weeks=week, days=3, hours=hour)) for week in range(12) for hour in (1, 2)]
    one_day += [sale(start + timedelta(weeks=week, days=day, hours=1)) for week in (0, 4, 8) for day in (0, 1, 2, 4, 5, 6)]
    pattern = weekday_patterns(one_day, "UTC", now=NOW)[0]
    assert (pattern["suggested_start"], pattern["suggested_end"]) == ("2026-10-08", "2026-10-08")
    assert pattern["reason"].startswith("Thursday had 24 of 42") and "Run sales on Thursday." in pattern["reason"]

    three_days = [sale(start + timedelta(weeks=week, days=day, hours=1)) for week in range(12) for day in (4, 5, 6)]
    three_days += [sale(start + timedelta(weeks=week, hours=1)) for week in (0, 6)]
    pattern = weekday_patterns(three_days, "UTC", now=NOW)[0]
    assert (pattern["suggested_start"], pattern["suggested_end"]) == ("2026-10-09", "2026-10-11")
    assert pattern["reason"].startswith("Friday–Sunday had 36 of 38")


def test_weak_peak_is_reported_as_possible_chance():
    start = NOW - timedelta(weeks=26)
    counts = [5, 1, 3, 8, 4, 3, 3]  # one seller's eBay weekdays: Thursday leads, but not clearly
    rows = [sale(start + timedelta(weeks=n, days=day, hours=1)) for day, count in enumerate(counts) for n in range(count)]
    pattern = weekday_patterns(rows, "UTC", now=NOW)[0]
    assert (pattern["suggested_start"], pattern["suggested_end"]) == ("2026-10-08", "2026-10-08")
    assert "may be chance" in pattern["reason"]


def test_tied_weekdays_do_not_generate_a_suggestion():
    start = NOW - timedelta(weeks=12)
    rows = [sale(start + timedelta(days=day, hours=1)) for day in range(84)]
    pattern = weekday_patterns(rows, "UTC", now=NOW)[0]
    assert pattern["sales"] == 84 and pattern["suggested_start"] is None
    assert "No clear" in pattern["reason"]


def event():
    return SimpleNamespace(id="event", status="ran", marketplace="ebay", timezone="America/New_York",
                           start_date=date(2026, 9, 25), end_date=date(2026, 9, 27), items=[{"id": "selected"}])


def test_result_timezone_matched_weekdays_and_incomplete_profit():
    e = event()
    rows = [sale(datetime(2026, 8, 1, tzinfo=UTC)),
            sale(datetime(2026, 9, 25, 2, tzinfo=UTC), cid="before"),
            sale(datetime(2026, 9, 28, 2, tzinfo=UTC), cid="selected"),
            sale(datetime(2026, 9, 26, 12, tzinfo=UTC), cid="other", cost=None),
            sale(datetime(2026, 9, 19, 12, tzinfo=UTC), cid="comparison"),
            sale(NOW + timedelta(days=1)), sale(None),
            sale(datetime(2026, 9, 26, tzinfo=UTC), market="etsy")]
    result = event_result(e, [e], rows, now=NOW)
    assert result["selected"] == {"count": 1, "revenue": 40, "revenue_known": 1, "profit": 25, "profit_known": 1}
    assert result["marketplace"]["count"] == 2 and result["marketplace"]["profit"] is None
    assert result["comparison"]["count"] == 1
    assert result["comparison_start"] == "2026-09-18" and result["comparison_end"] == "2026-09-20"


def test_results_exclude_promotional_baselines_and_missing_history():
    e = event()
    other = SimpleNamespace(id="other", status="ran", marketplace="ebay", start_date=date(2026, 9, 18), end_date=date(2026, 9, 20))
    rows = [sale(datetime(2026, 8, 1, tzinfo=UTC))]
    assert event_result(e, [e, other], rows, now=NOW)["comparison"] is None
    assert "promotion" in event_result(e, [e, other], rows, now=NOW)["comparison_unavailable"]
    assert "history" in event_result(e, [e], [], now=NOW)["comparison_unavailable"]
    e.status = "planned"
    assert event_result(e, [e], rows, now=NOW) is None


def test_ongoing_results_compare_only_elapsed_days():
    e = event()
    e.start_date, e.end_date = date(2026, 10, 4), date(2026, 10, 8)
    result = event_result(e, [e], [sale(NOW)], now=NOW)
    assert result["through"] == "2026-10-05" and result["ongoing"]
    assert result["comparison_start"] == "2026-09-27" and result["comparison_end"] == "2026-09-28"


def test_migration_preserves_data_on_previous_release_snapshot(tmp_path):
    import sqlite3
    from alembic import command
    from vendoo_studio.services.schema_migrations import alembic_config

    previous, snapshot = tmp_path / "previous.db", tmp_path / "snapshot.db"
    command.upgrade(alembic_config(f"sqlite:///{previous}"), "26082cbdc6ea")
    with sqlite3.connect(previous) as conn:
        conn.execute("INSERT INTO conversations (id, title) VALUES ('keep', 'Keep this listing')")
        conn.execute("INSERT INTO sale_events (id, name, starts_on, ends_on, marketplaces, discount_percent) VALUES ('history', 'Cyber week', '2025-11-25', '2025-11-30', ?, 25)", (json.dumps(['ebay', 'depop']),))
        conn.execute("INSERT INTO sale_events (id, name, starts_on, ends_on, marketplaces) VALUES ('all', 'Whole shop', '2025-11-01', '2025-11-02', '[]')")
        conn.commit()
        conn.execute("VACUUM INTO ?", (str(snapshot),))
    command.upgrade(alembic_config(f"sqlite:///{snapshot}"), "head")
    with sqlite3.connect(snapshot) as conn:
        assert conn.execute("SELECT title FROM conversations WHERE id='keep'").fetchone() == ("Keep this listing",)
        history = conn.execute("SELECT title, marketplace, start_date, end_date, status, items, timezone FROM sale_events WHERE title='Cyber week' ORDER BY marketplace").fetchall()
        assert history == [('Cyber week', 'depop', '2025-11-25', '2025-11-30', 'ran', '[]', 'UTC'), ('Cyber week', 'ebay', '2025-11-25', '2025-11-30', 'ran', '[]', 'UTC')]
        assert conn.execute("SELECT marketplace FROM sale_events WHERE id='all'").fetchone() == ('all',)


def test_past_marketplace_records_need_no_item_selection_and_can_be_corrected(workspace):
    db, client = workspace
    body = {key: value for key, value in plan(start_date='2020-01-03', end_date='2020-01-05').items()
            if key not in {'fee_percent', 'shipping_cost', 'minimum_profit', 'item_ids'}}
    body['discount_percent'] = None
    response = client.post('/api/analytics/calendar/records', json=body)
    assert response.status_code == 201, response.text
    eid = response.json()['id']
    assert db.get(SaleEvent, eid).status == 'ran'
    assert db.get(SaleEvent, eid).items == []
    body['timezone'] = 'America/New_York'
    assert client.put(f'/api/analytics/calendar/records/{eid}', json=body).status_code == 200
    data = client.get('/api/analytics/calendar').json()['events'][0]
    assert data['result']['scope'] == 'marketplace'
    assert data['fee_percent'] is None
    body['marketplace'] = 'all'
    assert client.post('/api/analytics/calendar/records', json=body).status_code == 422
    body.update(marketplace='ebay', start_date='2099-01-01', end_date='2099-01-02')
    assert client.post('/api/analytics/calendar/records', json=body).status_code == 422


def test_cancelled_plan_cannot_be_restored_into_a_conflict(workspace):
    _db, client = workspace
    eid = client.post('/api/analytics/calendar', json=plan()).json()['id']
    assert client.patch(f'/api/analytics/calendar/{eid}/status', json={'status': 'cancelled'}).status_code == 200
    assert client.post('/api/analytics/calendar', json=plan()).status_code == 201
    assert client.patch(f'/api/analytics/calendar/{eid}/status', json={'status': 'planned'}).status_code == 422


def test_missing_sale_prices_never_become_zero_cost_profit():
    e = event()
    row = sale(datetime(2026, 9, 26, 12, tzinfo=UTC), cid='selected')
    from dataclasses import replace
    result = event_result(e, [e], [replace(row, sold_price=None)], now=NOW)
    assert result['selected']['revenue_known'] == 0
    assert result['selected']['profit'] is None


def test_records_track_post_event_sales_for_at_most_fourteen_days():
    e = event()
    clock = datetime(2026, 10, 20, tzinfo=UTC)
    rows = [sale(datetime(2026, 9, 28, 18, tzinfo=UTC)),
            sale(datetime(2026, 10, 11, 18, tzinfo=UTC)),
            sale(datetime(2026, 10, 12, 18, tzinfo=UTC))]
    result = event_result(e, [e], rows, now=clock)
    assert result['after_days'] == 14
    assert result['after']['count'] == 2
