from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db, load_models
from vendoo_studio.main import app
from vendoo_studio.models.listing_evidence import ListingCorrection, ListingEvidence, SaleSnapshot
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.generation_history import seller_history_context
from vendoo_studio.services.listing_delete import delete_listing, wipe_contents
from vendoo_studio.services.listing_evidence import (
    EngagementOutcome, ShippingOutcome, capture_sale_snapshot, corrections_context,
    explicit_changes, generation_evidence_prompt, record_correction,
)
from vendoo_studio.services.registry import MEN_TSHIRT_PATH
from vendoo_studio.services.vendoo_import import merge_notes, vendoo_dates, vendoo_sale
from vendoo_studio.services.vendoo_watch import refresh_inventory_label


@pytest.fixture
def workspace():
    load_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda connection, record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    conv = ConversationRepo(db).create(title="Nike L Cotton Tee")
    listing = {"title": conv.title, "brand": "Nike", "size": "L", "condition": "Pre-Owned - Good",
               "category_path": MEN_TSHIRT_PATH, "price": 32, "quantity": 1}
    revision = ListingRepo(db).save_revision(conv.id, listing, source="generation")
    app.dependency_overrides[get_db] = lambda: db
    yield db, conv, revision, TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    db.close()
    engine.dispose()


def sold_item(title="Nike L Original Tee"):
    return {"sold": True, "generalDetails": {
        "title": title, "brand": "Nike", "size": "L", "quantity": 1,
        "category": MEN_TSHIRT_PATH, "condition": "Good", "notes": "PRIVATE-REMOTE-NOTE",
    }, "saleRecord": {"date_sold": "2026-10-01T12:00:00Z", "marketplace": "ebay", "price_sold": 24},
        "listings": {"ebay": {"status": {"sold": True}, "dateListed": "2026-09-01T12:00:00Z"}}}


def test_form_records_only_raw_changes_before_automatic_normalization(workspace):
    db, conv, revision, client = workspace
    submitted = {**revision.listing_json, "size": "M"}
    reply = client.put(f"/api/conversations/{conv.id}/listing", json={"listing": submitted})
    assert reply.status_code == 200
    correction = db.query(ListingCorrection).one()
    assert correction.changes == {"size": {"before": "L", "after": "M"}}
    current = ListingRepo(db).get_revision(reply.json()["revision_id"])
    assert "M" in current.listing_json["title"]
    assert correction.revision_id == current.id


def test_automated_and_legacy_revisions_do_not_become_corrections(workspace):
    db, conv, revision, _client = workspace
    for source in ("user_form", "generation", "dropdown_normalize", "vendoo_import"):
        ListingRepo(db).save_revision(conv.id, {**revision.listing_json, "size": "M"}, source=source)
    assert not corrections_context(db, conv.id, revision.listing_json)["current_item_corrections"]


def test_clears_are_recorded_private_fields_are_excluded_and_input_is_not_mutated():
    previous = {"brand": "Nike", "description": "Long text", "sku": "secret", "internal_notes": "private", "unknown": "secret"}
    submitted = {**previous, "brand": "", "sku": "new-secret", "internal_notes": "new-private", "unknown": "new"}
    before = copy.deepcopy(previous)
    assert explicit_changes(previous, submitted) == {"brand": {"before": "Nike", "after": ""}}
    assert previous == before


def test_related_edits_are_copy_examples_only_and_latest_current_clear_wins(workspace):
    db, conv, revision, _client = workspace
    record_correction(db, conv.id, revision.id, revision.listing_json, {"brand": {"before": "Nike", "after": ""}})
    other = ConversationRepo(db).create(title="Other")
    record_correction(db, other.id, "r2", revision.listing_json, {
        "brand": {"before": "Unknown", "after": "Nike"},
        "title": {"before": "NIKE SHIRT!!!", "after": "Nike M Cotton Tee"},
    })
    db.commit()
    context = corrections_context(db, conv.id, revision.listing_json)
    assert context["current_item_corrections"]["brand"]["value"] == ""
    assert set(context["related_copy_edits"][0]["changes"]) == {"title"}
    prompt = generation_evidence_prompt(db, conv.id)
    assert "NIKE SHIRT!!!" in prompt
    assert '"r2"' not in prompt


def test_sale_snapshot_is_remote_immutable_and_idempotent(workspace):
    db, conv, revision, _client = workspace
    item = sold_item()
    capture_sale_snapshot(db, conv.id, item)
    db.commit()
    snapshot = db.query(SaleSnapshot).one()
    assert snapshot.listing["title"] == "Nike L Original Tee"
    assert snapshot.source == "vendoo_first_observed_sold"
    observed = snapshot.observed_at
    capture_sale_snapshot(db, conv.id, sold_item("Later changed remote title"))
    db.commit()
    assert db.query(SaleSnapshot).count() == 1
    db.refresh(snapshot)
    assert snapshot.listing["title"] == "Nike L Original Tee"
    assert snapshot.observed_at == observed
    assert revision.listing_json["title"] != snapshot.listing["title"]


def test_missing_dates_and_unsold_items_do_not_fabricate_snapshots(workspace):
    db, conv, _, _client = workspace
    item = sold_item()
    item["saleRecord"].pop("date_sold")
    capture_sale_snapshot(db, conv.id, item)
    capture_sale_snapshot(db, conv.id, {"generalDetails": {"title": "Draft"}})
    assert db.query(SaleSnapshot).count() == 0


def test_sync_captures_sales_amount_and_first_observed_snapshot(workspace):
    db, conv, _, _client = workspace
    refresh_inventory_label(db, conv.id, sold_item())
    notes = json.loads(conv.notes)
    assert notes["vendooSale"]["price"] == 24
    assert db.query(SaleSnapshot).one().listing["title"] == "Nike L Original Tee"


def test_history_matches_snapshot_instead_of_later_edited_brand_and_title(workspace):
    db, conv, revision, _client = workspace
    other = ConversationRepo(db).create(title="Sold")
    item = sold_item()
    other.notes = merge_notes(None, {"vendooStatus": "sold", "vendooSale": vendoo_sale(item), "vendooDates": vendoo_dates(item)})
    db.commit()
    capture_sale_snapshot(db, other.id, item)
    ListingRepo(db).save_revision(other.id, {**revision.listing_json, "brand": "Adidas", "title": "Edited after sale"}, source="user_form")
    context = seller_history_context(db, conv.id, "- brand: Nike\n- condition: Good", now=datetime(2026, 10, 7, tzinfo=UTC))
    assert context["sales"]["count"] == 1
    example = context["sales"]["examples"][0]
    assert example["title"] == "Nike L Original Tee"
    assert example["listing_text_source"] == "vendoo_first_observed_sold"
    assert example["snapshot_observed_at"]
    assert "PRIVATE-REMOTE-NOTE" not in json.dumps(context)


def test_shipping_and_overlapping_reports_reach_generation_without_summing(workspace):
    db, conv, _, client = workspace
    path = f"/api/conversations/{conv.id}/evidence"
    shipping = {"shipped_on": "2026-10-01", "packed_weight_oz": 12, "postage_paid": 0}
    response = client.put(path + "/shipping", json={"shipping": shipping})
    assert response.status_code == 200
    assert response.json()["shipping"]["postage_paid"] == 0
    assert response.json()["shipping"]["length_in"] is None
    assert response.json()["shipping"]["source"] == "seller_measured"
    for start in ("2026-09-01", "2026-09-15"):
        response = client.put(path + "/engagement", json={"marketplace": "ebay", "start_date": start,
            "end_date": "2026-10-01", "impressions": 100, "views": 0})
        assert response.status_code == 200
    prompt = generation_evidence_prompt(db, conv.id)
    assert prompt.count('"impressions": 100') == 2
    assert '"impressions": 200' not in prompt
    assert '"offers": null' in prompt
    assert '"views": 0' in prompt
    assert "seller_measured" in prompt
    assert client.put(path + "/shipping", json={"shipping": None}).status_code == 200
    assert client.get(path).json()["shipping"] is None
    assert client.delete(path + "/engagement?marketplace=ebay&start_date=2026-09-01&end_date=2026-10-01").status_code == 200
    assert len(client.get(path).json()["engagement"]) == 1


def test_same_reporting_period_updates_in_place(workspace):
    _, conv, _, client = workspace
    path = f"/api/conversations/{conv.id}/evidence/engagement"
    report = {"marketplace": "ebay", "start_date": "2026-09-01", "end_date": "2026-10-01", "views": 10}
    client.put(path, json=report)
    response = client.put(path, json={**report, "views": 20})
    assert len(response.json()["engagement"]) == 1
    assert response.json()["engagement"][0]["views"] == 20


@pytest.mark.parametrize("changes", [{"packed_weight_oz": 0}, {"packed_weight_oz": -1},
    {"length_in": 10}, {"shipped_on": "2099-01-01"}, {"packed_weight_oz": "NaN"}])
def test_shipping_rejects_unverified_or_invalid_measurements(changes):
    with pytest.raises(ValidationError):
        ShippingOutcome.model_validate({"shipped_on": "2026-10-01", "packed_weight_oz": 12, **changes})


@pytest.mark.parametrize("changes", [{"views": -1}, {"views": True}, {"views": 1.5},
    {"end_date": "2099-01-01"}, {"end_date": "2026-08-01"}, {"views": None},
    {"return_reason": "fit"}, {"marketplace": "unknown"}])
def test_engagement_requires_dated_actual_counts(changes):
    with pytest.raises(ValidationError):
        EngagementOutcome.model_validate({"marketplace": "ebay", "start_date": "2026-09-01", "end_date": "2026-10-01", "views": 10, **changes})


def test_evidence_survives_regeneration_and_is_deleted_with_listing(workspace):
    db, conv, revision, client = workspace
    record_correction(db, conv.id, revision.id, revision.listing_json, {"size": {"before": "L", "after": "M"}})
    capture_sale_snapshot(db, conv.id, sold_item())
    client.put(f"/api/conversations/{conv.id}/evidence/shipping", json={"shipping": {"shipped_on": "2026-10-01", "packed_weight_oz": 12}})
    wipe_contents(db, conv.id, keep_photos=True)
    db.commit()
    assert db.query(ListingCorrection).count() == 1
    assert db.query(SaleSnapshot).count() == 1
    assert db.get(ListingEvidence, conv.id)
    delete_listing(db, conv.id)
    assert db.query(ListingCorrection).count() == db.query(SaleSnapshot).count() == db.query(ListingEvidence).count() == 0


def test_missing_conversation_is_rejected(workspace):
    _, _, _, client = workspace
    assert client.get("/api/conversations/missing/evidence").status_code == 404


def test_revision_restore_supersedes_current_corrections_without_teaching_related_preferences(workspace):
    db, conv, original, client = workspace
    changed = client.put(f"/api/conversations/{conv.id}/listing", json={"listing": {**original.listing_json, "size": "M"}}).json()
    response = client.post(f"/api/conversations/{conv.id}/revisions/{original.id}/restore", json={"expected_revision_id": changed["revision_id"]})
    assert response.status_code == 200
    context = corrections_context(db, conv.id, original.listing_json)
    assert context["current_item_corrections"]["size"]["value"] == "L"
    assert context["current_item_corrections"]["size"]["source"] == "restore"


def test_observed_outcomes_and_corrections_reach_initial_generation_with_canonical_rules(workspace):
    from vendoo_studio.services.chat_prompts import listing_generation_messages
    from vendoo_studio.services.skill_formulas import with_pinned_formulas
    db, conv, original, client = workspace
    client.put(f"/api/conversations/{conv.id}/listing", json={"listing": {**original.listing_json, "size": "M"}})
    client.put(f"/api/conversations/{conv.id}/evidence/shipping", json={"shipping": {"shipped_on": "2026-10-01", "packed_weight_oz": 12}})
    prompt = listing_generation_messages(with_pinned_formulas(""), "", "- brand: Nike", db, conv.id)[0]["content"]
    assert "Seller corrections and observed outcomes" in prompt
    assert '"size": {"value": "M"' in prompt
    assert '"packed_weight_oz": 12.0' in prompt
    assert "never add them" in prompt
    assert "buyer-facing listing copy" in prompt
