from __future__ import annotations

from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import Conversation, Message, Photo, new_id
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.models.job import Job, JobEvent


class ConversationRepo:
    def __init__(self, db: Session):
        self.db = db

    def create(self, title: str | None = None, notes: str | None = None) -> Conversation:
        conv = Conversation(title=title, notes=notes)
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def get(self, conv_id: str) -> Conversation | None:
        return self.db.query(Conversation).filter(Conversation.id == conv_id).first()

    def list_all(self) -> list[Conversation]:
        return self.db.query(Conversation).order_by(Conversation.updated_at.desc()).all()

    def add_message(self, conv_id: str, role: str, text: str, provider: str | None = None, model: str | None = None) -> Message:
        msg = Message(conversation_id=conv_id, role=role, text=text, provider=provider, model=model)
        self.db.add(msg)
        conv = self.db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv:
            conv.updated_at = msg.created_at
        self.db.commit()
        return msg

    def get_messages(self, conv_id: str) -> list[Message]:
        return self.db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()

    def add_photo(self, conv_id: str, original_filename: str, stored_filename: str, mime_type: str, size_bytes: int, checksum: str | None = None, width: int | None = None, height: int | None = None) -> Photo:
        max_order = self.db.query(Photo).filter(Photo.conversation_id == conv_id).count()
        photo = Photo(
            conversation_id=conv_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            display_order=max_order,
            checksum=checksum,
            width=width,
            height=height,
        )
        self.db.add(photo)
        self.db.commit()
        self.db.refresh(photo)
        return photo

    def get_photos(self, conv_id: str) -> list[Photo]:
        return self.db.query(Photo).filter(Photo.conversation_id == conv_id).order_by(Photo.display_order).all()

    def delete_photo(self, conv_id: str, photo_id: str) -> bool:
        photo = self.db.query(Photo).filter(Photo.id == photo_id, Photo.conversation_id == conv_id).first()
        if not photo:
            return False
        self.db.delete(photo)
        self.db.commit()
        return True

    def reorder_photos(self, conv_id: str, ordered_ids: list[str]) -> list[Photo]:
        for idx, photo_id in enumerate(ordered_ids):
            photo = self.db.query(Photo).filter(Photo.id == photo_id, Photo.conversation_id == conv_id).first()
            if photo:
                photo.display_order = idx
        self.db.commit()
        return self.get_photos(conv_id)


class ListingRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_current(self, conv_id: str) -> Listing | None:
        return self.db.query(Listing).filter(Listing.conversation_id == conv_id).first()

    def save_revision(self, conv_id: str, listing_json: dict, source: str, parent_revision_id: str | None = None) -> ListingRevision:
        revision = ListingRevision(
            conversation_id=conv_id,
            listing_json=listing_json,
            source=source,
            parent_revision_id=parent_revision_id,
        )
        self.db.add(revision)
        self.db.flush()

        listing = self.db.query(Listing).filter(Listing.conversation_id == conv_id).first()
        if listing:
            listing.current_revision_id = revision.id
        else:
            listing = Listing(conversation_id=conv_id, current_revision_id=revision.id)
            self.db.add(listing)

        self.db.commit()
        self.db.refresh(revision)
        return revision

    def get_revision(self, revision_id: str) -> ListingRevision | None:
        return self.db.query(ListingRevision).filter(ListingRevision.id == revision_id).first()

    def get_revisions(self, conv_id: str) -> list[ListingRevision]:
        return self.db.query(ListingRevision).filter(ListingRevision.conversation_id == conv_id).order_by(ListingRevision.created_at.desc()).all()


class JobRepo:
    def __init__(self, db: Session):
        self.db = db

    def create(self, conv_id: str, approved_revision_id: str, listing_snapshot: dict) -> Job:
        job = Job(
            conversation_id=conv_id,
            approved_revision_id=approved_revision_id,
            listing_snapshot=listing_snapshot,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.db.query(Job).filter(Job.id == job_id).first()

    def get_active(self) -> list[Job]:
        return self.db.query(Job).filter(Job.status == "queued").all()

    def list_all(self) -> list[Job]:
        return self.db.query(Job).order_by(Job.created_at.desc()).limit(50).all()

    def list_by_conversation(self, conv_id: str) -> list[Job]:
        return self.db.query(Job).filter(Job.conversation_id == conv_id).order_by(Job.created_at.desc()).all()

    def update_status(self, job_id: str, status: str, current_step: str | None = None, error: str | None = None, vendoo_item_id: str | None = None, vendoo_url: str | None = None) -> Job | None:
        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        job.status = status
        if current_step is not None:
            job.current_step = current_step
        if error is not None:
            job.last_error = error
        if vendoo_item_id is not None:
            job.vendoo_item_id = vendoo_item_id
        if vendoo_url is not None:
            job.vendoo_url = vendoo_url
        self.db.commit()
        self.db.refresh(job)
        return job

    def add_event(self, job_id: str, event_type: str, step: str | None = None, payload: dict | None = None) -> JobEvent:
        count = self.db.query(JobEvent).filter(JobEvent.job_id == job_id).count()
        event = JobEvent(job_id=job_id, sequence=count, event_type=event_type, step=step, payload=payload)
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_events(self, job_id: str) -> list[JobEvent]:
        return self.db.query(JobEvent).filter(JobEvent.job_id == job_id).order_by(JobEvent.sequence).all()
