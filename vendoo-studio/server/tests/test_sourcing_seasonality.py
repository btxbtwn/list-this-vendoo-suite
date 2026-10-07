from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base, load_models
from vendoo_studio.models.listing_evidence import SaleSnapshot
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.listing_evidence import sale_key
from vendoo_studio.services.sourcing_seasonality import historical_windows, seasonal_sales_context, selling_window


@pytest.fixture
def db():
    load_models()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def record(db, *, sold="2025-11-10", price=20, quantity=1, category="Clothing > Coats", status="sold", identity=None):
    conv = ConversationRepo(db).create(title="Wool coat")
    conv.status = status
    sale = {"price": price, "marketplace": "ebay"}
    dates = {"sold": sold}
    notes = {"vendooSale": sale, "vendooDates": dates, "vendooStatus": "sold", "private": "PRIVATE-NOTE"}
    if identity:
        notes["vendooItemId"] = identity
    conv.notes = json.dumps(notes)
    listing = {"title": "Wool coat", "quantity": quantity, "category_path": category,
               "ebay_specifics": {"type": "Coat"}, "price": 999, "internal_notes": "PRIVATE-LISTING", "sku": "PRIVATE-SKU"}
    ListingRepo(db).save_revision(conv.id, listing, source="vendoo_import")
    db.commit()
    return conv, listing, sale, dates


def context(db):
    today = date(2026, 10, 7)
    return seasonal_sales_context(db, selling_window({"ready_in_weeks": 4, "selling_window_weeks": 4}, today), today)


def test_window_uses_preparation_time_and_inclusive_end():
    window = selling_window({"ready_in_weeks": 4, "selling_window_weeks": 4}, date(2026, 10, 7))
    assert (window["start_date"], window["end_date"]) == ("2026-11-04", "2026-12-01")
    immediate = selling_window({"ready_in_weeks": 0, "selling_window_weeks": 1}, date(2026, 10, 7))
    assert (immediate["start_date"], immediate["end_date"]) == ("2026-10-07", "2026-10-13")


def test_historical_windows_handle_year_boundaries_and_leap_days():
    periods = historical_windows({"start_date": "2026-12-20", "end_date": "2027-01-16"}, date(2026, 11, 22))
    assert periods[0] == {"start_date": "2025-12-20", "end_date": "2026-01-16"}
    leap = historical_windows({"start_date": "2028-02-29", "end_date": "2028-03-06"}, date(2028, 2, 1))
    assert leap[0]["start_date"] == "2027-02-28"
    future = historical_windows({"start_date": "2027-04-07", "end_date": "2027-10-07"}, date(2026, 10, 7))
    assert all(period["end_date"] < "2026-10-07" for period in future)


def test_same_calendar_history_is_bounded_and_does_not_expose_private_fields(db):
    for index in range(5):
        record(db, price=10 + index * 5)
    record(db, sold="2025-07-10", price=500)
    record(db, sold="2026-10-01", price=500)
    record(db, sold="2022-11-10", price=500)
    result = context(db)
    assert result["dated_recorded_sales"] == 8
    assert result["matching_window_sales"] == 5
    group = result["groups"][0]
    assert (group["count"], group["historical_median_price"]) == (5, 20)
    assert group["period_counts"]["2025-11-04"] == 5
    assert len(group["examples"]) == 3
    assert group["examples"][0]["listing_source"] == "current_listing_not_verified_at_sale"
    assert "PRIVATE" not in json.dumps(result)
    assert "inventory exposure unknown" in result["coverage"]


def test_missing_actual_amount_invalid_dates_bundles_and_busy_items_are_excluded(db):
    for changes in ({"price": None}, {"price": False}, {"price": "NaN"}, {"price": -1},
                    {"sold": ""}, {"sold": "2026-12-01"}, {"quantity": 2}, {"quantity": None},
                    {"status": "in_progress"}, {"category": "Coats"}):
        record(db, **changes)
    conv, *_ = record(db)
    conv.notes = "ordinary non-JSON notes"
    db.commit()
    result = context(db)
    assert result["matching_window_sales"] == 0
    assert result["groups"] == []


def test_duplicate_remote_items_cannot_supply_sample_floor(db):
    for _index in range(5):
        record(db, identity="same-item")
    result = context(db)
    assert result["matching_window_sales"] == 1
    assert result["groups"] == []


def test_frozen_sale_facets_survive_later_listing_edits_and_snapshots_are_not_extra_sales(db):
    for _index in range(5):
        conv, listing, sale, dates = record(db)
        db.add(SaleSnapshot(conversation_id=conv.id, sale_key=sale_key(sale, dates), listing=listing,
                            source="vendoo_first_observed_sold"))
        ListingRepo(db).save_revision(conv.id, {**listing, "category_path": "Other > Pants", "title": "Edited pants"}, source="user_form")
    db.commit()
    result = context(db)
    assert result["matching_window_sales"] == 5
    assert result["groups"][0]["category_path"] == "Clothing > Coats"
    assert all(example["title"] == "Wool coat" and example["listing_source"] == "first_observed_sold"
               for example in result["groups"][0]["examples"])


def test_sale_dates_are_compared_in_utc_and_exact_types_have_separate_sample_floors(db):
    for _index in range(4):
        record(db, sold="2025-11-04T00:30:00+02:00")
    for _index in range(4):
        record(db)
    conv, listing, *_ = record(db)
    ListingRepo(db).save_revision(conv.id, {**listing, "ebay_specifics": {"type": "Jacket"}}, source="user_form")
    db.commit()
    result = context(db)
    assert result["matching_window_sales"] == 5
    assert result["groups"] == []
