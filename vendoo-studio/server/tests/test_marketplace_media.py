"""Each marketplace form's own photos, like Vendoo's Photo Manager. Every image here is drawn by the test."""
from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db, load_models
from vendoo_studio.main import app
from vendoo_studio.models.job import Job
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.marketplace_media import PHOTO_LIMITS, keep_media, photos_for
from vendoo_studio.services.photo_store import LocalPhotoStore


def _photo(photo_id: str, marketplace: str | None = None):
    return SimpleNamespace(id=photo_id, marketplace=marketplace)


ITEM = [_photo("front"), _photo("back"), _photo("tag")]
EXTRAS = [_photo("stock", "ebay"), _photo("model", "poshmark")]


def test_a_form_without_a_pick_sends_the_item_photos_in_item_order():
    sent, warning = photos_for({}, [*ITEM, *EXTRAS], "ebay")
    assert [photo.id for photo in sent] == ["front", "back", "tag"]
    assert warning == ""


def test_a_pick_sends_only_its_ticked_photos_in_its_order_including_that_forms_own():
    listing = {"marketplace_photos": {"ebay": ["stock", "tag", "front"]}}
    assert [photo.id for photo in photos_for(listing, [*ITEM, *EXTRAS], "ebay")[0]] == ["stock", "tag", "front"]
    # Another form keeps the item photos, and never sends a photo added on a different form.
    assert [photo.id for photo in photos_for(listing, [*ITEM, *EXTRAS], "etsy")[0]] == ["front", "back", "tag"]
    other = {"marketplace_photos": {"etsy": ["model", "back"]}}
    assert [photo.id for photo in photos_for(other, [*ITEM, *EXTRAS], "etsy")[0]] == ["back"]


def test_a_pick_whose_photos_were_all_deleted_goes_back_to_the_item_photos():
    listing = {"marketplace_photos": {"mercari": ["gone"]}}
    assert [photo.id for photo in photos_for(listing, ITEM, "mercari")[0]] == ["front", "back", "tag"]


def test_each_marketplace_keeps_its_own_number_of_photos_and_says_which_are_left_off():
    many = [_photo(str(index)) for index in range(13)]
    sent, warning = photos_for({}, many, "mercari")
    assert len(sent) == PHOTO_LIMITS["mercari"] == 12
    assert warning.startswith("Mercari keeps 12 photos. The first 12 of 13 are sent.")
    assert photos_for({}, many, "ebay") == (many, "")


def test_regenerate_keeps_the_sellers_photo_picks_and_videos():
    previous = {"marketplace_photos": {"depop": ["back"]}, "ebay_specifics": {"videoId": "v1", "price": 10},
                "etsy_specifics": {"videoId": ""}}
    listing = {"title": "New", "ebay_specifics": {"price": 12}}
    keep_media(previous, listing)
    assert listing["marketplace_photos"] == {"depop": ["back"]}
    assert listing["ebay_specifics"] == {"price": 12, "videoId": "v1"}
    assert listing["etsy_specifics"] == {"videoId": ""}
    assert "poshmark_specifics" not in listing


def _jpeg(color=(20, 40, 200)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    load_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    monkeypatch.setattr("vendoo_studio.services.photo_store._store", LocalPhotoStore(str(tmp_path)))
    repo = ConversationRepo(db)
    conv = repo.create(title="Denim jacket")
    app.dependency_overrides[get_db] = lambda: db
    yield SimpleNamespace(db=db, sessions=sessions, repo=repo, conv=conv, client=TestClient(app),
                          base=f"/api/conversations/{conv.id}/photos")
    app.dependency_overrides.clear()
    db.close()


def _upload(env, marketplace=None, count=1):
    files = [("files", (f"photo{index}.jpg", _jpeg(), "image/jpeg")) for index in range(count)]
    return env.client.post(env.base, files=files, data={"marketplace": marketplace} if marketplace else {})


def test_a_photo_added_on_one_form_stays_off_the_item_photos(env):
    item = _upload(env).json()["photos"][0]
    own = _upload(env, "ebay").json()["photos"][0]
    assert (item["marketplace"], own["marketplace"]) == (None, "ebay")
    assert [photo["id"] for photo in env.client.get(env.base).json()] == [item["id"]]
    assert [photo["id"] for photo in env.client.get(env.base, params={"marketplace": "ebay"}).json()] == [own["id"]]
    assert env.client.get(env.base, params={"marketplace": "etsy"}).json() == []
    # The photo editor works on it like any other photo, and it can be deleted.
    assert env.client.post(f"{env.base}/{own['id']}/rotate", json={"degrees": 90}).status_code == 200
    assert env.client.delete(f"{env.base}/{own['id']}").json() == {"ok": True}
    assert env.client.get(env.base, params={"marketplace": "ebay"}).json() == []


def test_a_form_takes_no_more_of_its_own_photos_than_the_marketplace_does(env):
    assert _upload(env, "nowhere").status_code == 400
    assert _upload(env, "depop", count=8).status_code == 200
    refused = _upload(env, "depop")
    assert refused.status_code == 400
    assert "8" in refused.json()["detail"]


def test_the_rules_name_every_marketplaces_photo_limit_and_its_video_rules(env):
    body = env.client.get("/api/marketplace-media").json()
    assert body["photo_limits"] == PHOTO_LIMITS
    assert set(body["video_rules"]) == {"ebay", "etsy", "poshmark"}


def test_changing_a_forms_photos_needs_a_new_review(env):
    from vendoo_studio.services.send_review import review_inputs

    _upload(env)
    ListingRepo(env.db).save_revision(env.conv.id, {"title": "Denim jacket", "price": 30}, "user_form")
    first = review_inputs(env.db, env.conv.id)[1]
    _upload(env, "poshmark")
    second = review_inputs(env.db, env.conv.id)[1]
    assert second != first
    own = env.repo.get_all_photos(env.conv.id)[-1]
    ListingRepo(env.db).save_revision(env.conv.id, {"title": "Denim jacket", "price": 30,
                                                    "marketplace_photos": {"poshmark": [own.id]}}, "user_form")
    assert review_inputs(env.db, env.conv.id)[1] != second


def test_an_approved_send_waits_for_a_new_review_after_a_form_photo_change(env):
    from vendoo_studio.services.send_queue import run_send
    from vendoo_studio.services.send_review import photo_versions

    _upload(env)
    listing = {"title": "Denim jacket", "price": 30}
    revision = ListingRepo(env.db).save_revision(env.conv.id, listing, "user_form")
    job = Job(conversation_id=env.conv.id, approved_revision_id=revision.id, listing_snapshot=listing,
              status="dispatched", current_step="vendoo_api_create")
    env.db.add(job)
    env.db.commit()
    JobRepo(env.db).add_event(job.id, "vendoo_review", payload={
        "photo_versions": photo_versions(env.repo.get_all_photos(env.conv.id), listing)})
    [front] = env.repo.get_photos(env.conv.id)
    ListingRepo(env.db).save_revision(env.conv.id, {**listing, "marketplace_photos": {"etsy": [front.id]}}, "user_form")
    with patch("vendoo_studio.services.send_queue.SessionLocal", env.sessions), \
         patch("vendoo_studio.routes.vendoo_api._create_claimed_draft") as create, \
         patch("vendoo_studio.services.listing_provider.provider_is_configured", return_value=False), \
         patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"):
        asyncio.run(run_send(job.id))
    create.assert_not_called()
    env.db.expire_all()
    failed = env.db.get(Job, job.id)
    assert failed.status == "failed"
    assert "Review the listing again" in failed.last_error
