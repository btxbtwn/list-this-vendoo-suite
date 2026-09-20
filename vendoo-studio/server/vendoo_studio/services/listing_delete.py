"""Removing a listing, and everything hanging off it.

The sidebar's delete, Regenerate's wipe, and the bulk import's sweep over items
Vendoo no longer has all take the same cascade, so it lives here rather than in
the route that happened to need it first.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.models.conversation import Message, Photo as PhotoModel
from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation
from vendoo_studio.models.fill_log import FillLogEntry
from vendoo_studio.models.job import ACTIVE_JOB_STATUSES, Job, JobEvent
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.photos import delete_thumbnails

log = logging.getLogger("vendoo_studio.listing_delete")


class ListingBusy(RuntimeError):
    """A listing cannot be deleted while automation is running on it."""


def wipe_contents(db: Session, conv_id: str, *, keep_photos: bool = False) -> tuple[int, int]:
    """Delete a listing's jobs, revisions, messages and photos, keeping the row."""
    repo = ConversationRepo(db)
    photos = [] if keep_photos else repo.get_photos(conv_id)
    deleted_photos = len(photos)
    for photo in photos:
        filepath = Path(PHOTOS_DIR) / photo.stored_filename
        if filepath.exists():
            os.remove(filepath)
        delete_thumbnails(photo.stored_filename)

    job_ids = [row[0] for row in db.query(Job.id).filter(Job.conversation_id == conv_id).all()]
    if job_ids:
        db.query(FieldObservation).filter(
            FieldObservation.diagnostic_run_id.in_(
                db.query(DiagnosticRun.id).filter(DiagnosticRun.job_id.in_(job_ids))
            )
        ).delete(synchronize_session=False)
        db.query(DiagnosticRun).filter(DiagnosticRun.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(FillLogEntry).filter(FillLogEntry.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(JobEvent).filter(JobEvent.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.conversation_id == conv_id).delete(synchronize_session=False)

    db.query(ListingRevision).filter(ListingRevision.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Listing).filter(Listing.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == conv_id).delete(synchronize_session=False)
    if not keep_photos:
        db.query(PhotoModel).filter(PhotoModel.conversation_id == conv_id).delete(synchronize_session=False)
    return len(job_ids), deleted_photos


def delete_listing(db: Session, conv_id: str) -> tuple[int, int]:
    """Delete a listing outright. Returns the jobs and photos that went with it.

    Raises ``LookupError`` when there is no such listing and ``ListingBusy``
    when automation is still running on it.
    """
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if conv is None:
        raise LookupError("Conversation not found")

    active_jobs = db.query(Job).filter(
        Job.conversation_id == conv_id,
        Job.status.in_(ACTIVE_JOB_STATUSES),
    ).all()
    if active_jobs:
        raise ListingBusy("Cannot delete a listing with an active automation job")

    deleted_jobs, deleted_photos = wipe_contents(db, conv_id)
    db.expire_all()
    conv = repo.get(conv_id)
    if conv is None:
        raise LookupError("Conversation not found")
    db.delete(conv)
    db.commit()
    return deleted_jobs, deleted_photos
