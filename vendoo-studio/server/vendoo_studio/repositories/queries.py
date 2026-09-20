from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import Conversation, Message, Photo, new_id, utcnow
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.models.job import (
    ACTIVE_JOB_STATUSES,
    DISPATCHABLE_JOB_STATUSES,
    RUNNING_JOB_STATUSES,
    Job,
    JobEvent,
)
from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation
from vendoo_studio.models.registry import FieldRegistry
from vendoo_studio.models.fill_log import FillLogEntry

BUSY_LISTING_STATUSES = ("in_progress", "listing")
# Vendoo's own inventory labels, plus the one state Vendoo has no name for.
# Studio reports these; nothing outside it sets one.
LISTING_STATUSES = ("draft", "active", "sold", "failed")
# Statuses a Vendoo item can report for itself.
VENDOO_LISTING_STATUSES = ("draft", "active", "sold")


def _settle(conv: Conversation, when, *, backfill: bool = False, force: bool = False) -> bool:
    if conv.settled_at is not None:
        return False
    if not force and conv.unsettled_at is not None:
        return False
    conv.settled_at = conv.updated_at if backfill and conv.updated_at else when
    conv.unsettled_at = None
    return True


def _unsettle(conv: Conversation, when) -> bool:
    if conv.settled_at is None:
        return False
    conv.settled_at = None
    conv.unsettled_at = when
    return True


def _sync_settlement(conv: Conversation, status: str, *, backfill: bool = False) -> bool:
    now = utcnow()
    if status in BUSY_LISTING_STATUSES:
        return _unsettle(conv, now)
    if status == "sold":
        return _settle(conv, now, backfill=backfill, force=not backfill)
    return False


def _facet(sku: Any, price: Any) -> dict[str, Any]:
    text = str(sku or "").strip()
    try:
        amount = float(price) if price is not None and str(price) != "" else None
    except (TypeError, ValueError):
        amount = None
    return {"sku": text or None, "price": amount}


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

    def find_by_vendoo_item_id(self, item_id: str) -> Conversation | None:
        item_id = (item_id or "").strip()
        if not item_id:
            return None
        from vendoo_studio.services.vendoo_import import vendoo_binding
        rows = (
            self.db.query(Conversation)
            .filter(Conversation.notes.contains(item_id))
            .order_by(Conversation.updated_at.desc())
            .all()
        )
        for conv in rows:
            if vendoo_binding(conv.notes).get("vendooItemId") == item_id:
                return conv
        return None

    def list_all(self) -> list[Conversation]:
        return self.db.query(Conversation).order_by(Conversation.updated_at.desc()).all()

    def listing_facets(self) -> dict[str, dict[str, Any]]:
        """SKU and price for every listing, read inside SQLite.

        The sidebar filters and sorts on both. Loading whole revisions to reach
        two fields would mean hauling the entire inventory's listing JSON into
        Python on every sidebar read, so SQLite extracts them instead.
        """
        rows = (
            self.db.query(
                Listing.conversation_id,
                func.json_extract(ListingRevision.listing_json, "$.sku"),
                func.json_extract(ListingRevision.listing_json, "$.price"),
            )
            .join(ListingRevision, ListingRevision.id == Listing.current_revision_id)
            .all()
        )
        return {conv_id: _facet(sku, price) for conv_id, sku, price in rows}

    def listing_facet(self, conv_id: str) -> dict[str, Any]:
        row = (
            self.db.query(
                func.json_extract(ListingRevision.listing_json, "$.sku"),
                func.json_extract(ListingRevision.listing_json, "$.price"),
            )
            .join(Listing, ListingRevision.id == Listing.current_revision_id)
            .filter(Listing.conversation_id == conv_id)
            .first()
        )
        return _facet(*row) if row else _facet(None, None)

    def cover_photo_ids(self) -> dict[str, str]:
        """Map each conversation to its first photo, for sidebar thumbnails."""
        rows = (
            self.db.query(Photo.conversation_id, Photo.id)
            .order_by(Photo.conversation_id, Photo.display_order, Photo.created_at)
            .all()
        )
        covers: dict[str, str] = {}
        for conv_id, photo_id in rows:
            covers.setdefault(conv_id, photo_id)
        return covers

    def cover_photo_id(self, conv_id: str) -> str | None:
        row = (
            self.db.query(Photo.id)
            .filter(Photo.conversation_id == conv_id)
            .order_by(Photo.display_order, Photo.created_at)
            .first()
        )
        return row[0] if row else None

    def write_notes(
        self,
        conv_id: str,
        notes: str,
        *,
        bump_updated_at: bool = True,
    ) -> Conversation | None:
        """Store notes, optionally leaving ``updated_at`` where it was.

        Vendoo bookkeeping — the inventory label sweep — writes notes for
        listings the seller never touched. Restamping those would make every
        swept item look like recent activity and reshuffle the sidebar under
        the reader, so the quiet path keeps the stamp the listing already had.
        """
        conv = self.get(conv_id)
        if not conv:
            return None
        if conv.notes == notes:
            return conv
        values: dict[str, Any] = {"notes": notes}
        # Naming updated_at in the UPDATE suppresses the column's own onupdate.
        if not bump_updated_at:
            values["updated_at"] = conv.updated_at
        self.db.query(Conversation).filter(Conversation.id == conv_id).update(
            values, synchronize_session=False
        )
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def update_status(
        self,
        conv_id: str,
        status: str,
        *,
        touch_updated_at: bool = False,
    ) -> Conversation | None:
        conv = self.get(conv_id)
        if not conv:
            return None
        conv.status = status
        if touch_updated_at:
            conv.updated_at = utcnow()
        _sync_settlement(conv, status)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def settle(self, conv_id: str) -> Conversation | None:
        conv = self.get(conv_id)
        if not conv:
            return None
        _settle(conv, utcnow(), force=True)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def unsettle(self, conv_id: str) -> Conversation | None:
        conv = self.get(conv_id)
        if not conv:
            return None
        _unsettle(conv, utcnow())
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def _latest_jobs(self) -> dict[str, tuple[str, Any]]:
        """Newest job status per conversation, as ``{conv_id: (status, updated_at)}``.

        The sidebar reconciles every row on each refresh, so this reads the two
        columns it needs rather than whole jobs with their listing snapshots.
        """
        latest: dict[str, tuple[str, Any]] = {}
        rows = (
            self.db.query(Job.conversation_id, Job.status, Job.updated_at)
            .order_by(Job.conversation_id, Job.created_at.desc())
            .all()
        )
        for conv_id, status, updated_at in rows:
            latest.setdefault(conv_id, (status, updated_at))
        return latest

    def reconcile_job_statuses(self) -> None:
        """Keep each listing's label in step with its job and its Vendoo item.

        A listing bound to Vendoo wears Vendoo's own label (draft / active /
        sold); a send in flight reads ``listing`` and a send that broke reads
        ``failed``.
        """
        from vendoo_studio.services.vendoo_import import parse_notes

        busy_map = {
            "queued": "listing",
            "awaiting_extension": "listing",
            "dispatched": "listing",
        }
        latest_jobs = self._latest_jobs()
        changed = False
        for conv in self.db.query(Conversation).all():
            if conv.status == "in_progress":
                if _sync_settlement(conv, conv.status):
                    changed = True
                continue
            vendoo_status = str(parse_notes(conv.notes).get("vendooStatus") or "")
            if vendoo_status not in VENDOO_LISTING_STATUSES:
                vendoo_status = "draft"
            latest_job = latest_jobs.get(conv.id)
            if latest_job:
                job_status, job_updated_at = latest_job
                skip_job = (
                    conv.updated_at
                    and job_updated_at
                    and job_updated_at < conv.updated_at
                )
                if not skip_job:
                    if job_status in busy_map:
                        next_status = busy_map[job_status]
                    elif job_status == "failed":
                        next_status = "failed"
                    else:
                        next_status = vendoo_status
                    if conv.status != next_status:
                        conv.status = next_status
                        changed = True
            if conv.status not in LISTING_STATUSES + BUSY_LISTING_STATUSES:
                conv.status = vendoo_status
                changed = True
            if _sync_settlement(conv, conv.status, backfill=True):
                changed = True
        if changed:
            self.db.commit()

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

        title = (listing_json.get("title") or "").strip()
        if title:
            conv = self.db.query(Conversation).filter(Conversation.id == conv_id).first()
            if conv:
                conv.title = title

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

    def create(
        self,
        conv_id: str,
        approved_revision_id: str,
        listing_snapshot: dict,
        vendoo_item_id: str | None = None,
        vendoo_url: str | None = None,
        *,
        status: str = "queued",
        current_step: str | None = None,
    ) -> Job:
        job = Job(
            conversation_id=conv_id,
            approved_revision_id=approved_revision_id,
            listing_snapshot=listing_snapshot,
            vendoo_item_id=vendoo_item_id,
            vendoo_url=vendoo_url,
            status=status,
            current_step=current_step if current_step is not None else ("queued" if status == "queued" else status),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.db.query(Job).filter(Job.id == job_id).first()

    def get_active(self) -> list[Job]:
        return (
            self.db.query(Job)
            .filter(Job.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(Job.created_at.asc())
            .all()
        )

    def get_running(self) -> list[Job]:
        """Jobs currently using Chrome (excludes waiting queue entries)."""
        return (
            self.db.query(Job)
            .filter(Job.status.in_(RUNNING_JOB_STATUSES))
            .order_by(Job.created_at.asc())
            .all()
        )

    def get_dispatchable(self) -> list[Job]:
        return (
            self.db.query(Job)
            .filter(Job.status.in_(DISPATCHABLE_JOB_STATUSES))
            .order_by(Job.created_at.asc())
            .all()
        )

    def requeue_interrupted(self) -> list[Job]:
        from vendoo_studio.models.job import is_vendoo_api_step

        jobs = self.db.query(Job).filter(Job.status == "dispatched").all()
        for job in jobs:
            if is_vendoo_api_step(job.current_step):
                # Must not become a form-filler queue entry — that path opens a
                # Vendoo tab and fills the SPA instead of calling createItem.
                job.status = "failed"
                job.last_error = (
                    "Chrome reconnected during Send to Vendoo. "
                    "Click Send to Vendoo again."
                )
            elif job.current_step in {"filling_fields", "resolving_fields", "verifying_draft"}:
                job.status = "failed"
                job.last_error = (
                    "Chrome disconnected during leftover field fill. "
                    "Retry the leftover fill from Fields."
                )
            else:
                job.status = "queued"
                job.current_step = "queued"
                job.last_error = None
        if jobs:
            self.db.commit()
            for job in jobs:
                self.db.refresh(job)
        return jobs

    def list_all(self) -> list[Job]:
        return self.db.query(Job).order_by(Job.created_at.desc()).limit(50).all()

    def list_by_conversation(self, conv_id: str) -> list[Job]:
        return self.db.query(Job).filter(Job.conversation_id == conv_id).order_by(Job.created_at.desc()).all()

    def update_status(self, job_id: str, status: str, current_step: str | None = None, error: str | None = None, vendoo_item_id: str | None = None, vendoo_url: str | None = None) -> Job | None:
        from vendoo_studio.models.job import is_terminal_job_status

        job = self.db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        if is_terminal_job_status(job.status) and status != job.status:
            self.db.refresh(job)
            return job
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
        event = JobEvent(
            id=new_id(),
            job_id=job_id,
            sequence=count,
            event_type=event_type,
            step=step,
            payload=payload,
        )
        self.db.add(event)
        self.db.commit()
        return event

    def get_events(self, job_id: str) -> list[JobEvent]:
        return self.db.query(JobEvent).filter(JobEvent.job_id == job_id).order_by(JobEvent.sequence).all()

    def latest_event(self, job_id: str, event_type: str) -> JobEvent | None:
        return (
            self.db.query(JobEvent)
            .filter(JobEvent.job_id == job_id, JobEvent.event_type == event_type)
            .order_by(JobEvent.sequence.desc())
            .first()
        )

    def latest_vendoo_drafts(self, job_ids: list[str]) -> dict[str, dict]:
        """Newest cached draft for many jobs at once.

        The sidebar badges every rendered row, so a whole inventory would
        otherwise mean one query per listing on each refresh.
        """
        if not job_ids:
            return {}
        rows = (
            self.db.query(JobEvent)
            .filter(JobEvent.job_id.in_(job_ids), JobEvent.event_type == "vendoo_draft")
            .order_by(JobEvent.job_id, JobEvent.sequence.desc())
            .all()
        )
        drafts: dict[str, dict] = {}
        for event in rows:
            if event.job_id in drafts or not isinstance(event.payload, dict):
                continue
            payload = event.payload
            if not payload.get("item") and not payload.get("form"):
                continue
            drafts[event.job_id] = payload
        return drafts

    def save_vendoo_draft(
        self,
        job_id: str,
        *,
        item: dict | None = None,
        form: dict | None = None,
        item_id: str | None = None,
        url: str | None = None,
        source: str | None = None,
        step: str | None = None,
        statuses: dict | None = None,
    ) -> JobEvent:
        return self.add_event(
            job_id,
            "vendoo_draft",
            step,
            {
                "ok": True,
                "source": source or "cache",
                "item_id": item_id,
                "url": url,
                "item": item,
                "form": form,
                "statuses": statuses,
            },
        )

    def get_vendoo_draft(self, job_id: str) -> dict | None:
        event = self.latest_event(job_id, "vendoo_draft")
        if not event or not isinstance(event.payload, dict):
            return None
        payload = event.payload
        if not payload.get("item") and not payload.get("form"):
            return None
        return payload


class DiagnosticRepo:
    def __init__(self, db: Session):
        self.db = db

    def save_observation(self, payload: dict) -> DiagnosticRun | None:
        observation_id = payload.get("observation_id")
        if not observation_id:
            return None

        existing = self.db.query(DiagnosticRun).filter(
            DiagnosticRun.observation_id == observation_id
        ).first()
        if existing:
            return existing

        run = DiagnosticRun(
            observation_id=observation_id,
            job_id=payload.get("job_id", ""),
            step=payload.get("step", ""),
            collector_version=payload.get("collector_version", "unknown"),
            mode=payload.get("mode", "unknown"),
            url=payload.get("url", ""),
            title=payload.get("title", ""),
            timestamp=payload.get("timestamp", ""),
            field_count=payload.get("field_count", 0),
            dropdown_count=payload.get("dropdown_count", 0),
            dropdowns_with_options=payload.get("dropdowns_with_options", 0),
            live_dropdowns_with_options=payload.get("live_dropdowns_with_options", 0),
            total_dropdown_options=payload.get("total_dropdown_options", 0),
            expanded_sections=payload.get("expanded_sections", []),
            headings=payload.get("headings", []),
        )
        self.db.add(run)
        self.db.flush()

        fields = payload.get("fields", [])
        for f in fields:
            obs = FieldObservation(
                diagnostic_run_id=run.id,
                observation_id=observation_id,
                label=f.get("label", ""),
                label_sources=f.get("label_sources", []),
                section_path=f.get("section_path", []),
                selector=f.get("selector", ""),
                tag=f.get("tag", ""),
                control_type=f.get("control_type", ""),
                role=f.get("role", ""),
                name=f.get("name", ""),
                control_id=f.get("control_id", ""),
                placeholder=f.get("placeholder", ""),
                classes=f.get("classes", ""),
                is_dropdown=1 if f.get("is_dropdown") else 0,
                option_count=f.get("option_count", 0),
                options=f.get("options", []),
                options_source=f.get("options_source", "unknown"),
            )
            self.db.add(obs)

        self.db.commit()
        self.db.refresh(run)

        self._upsert_registry(payload)

        return run

    def get_by_job(self, job_id: str) -> list[DiagnosticRun]:
        return self.db.query(DiagnosticRun).filter(
            DiagnosticRun.job_id == job_id
        ).order_by(DiagnosticRun.created_at).all()

    def get_fields(self, diagnostic_run_id: str) -> list[FieldObservation]:
        return self.db.query(FieldObservation).filter(
            FieldObservation.diagnostic_run_id == diagnostic_run_id
        ).order_by(FieldObservation.created_at).all()

    def _upsert_registry(self, payload: dict):
        step = payload.get("step", "")
        marketplace = _step_to_marketplace(step)
        category_path = payload.get("category_path", "") or None

        registry_repo = RegistryRepo(self.db)

        for f in payload.get("fields", []):
            label = _normalize_label(f.get("label", ""))
            if not label:
                continue

            known = registry_repo.get_by_identity(marketplace, category_path, label)
            selectors = _build_selector_entry(f, known)

            if known:
                known.control_type = f.get("control_type") or known.control_type
                known.is_dropdown = 1 if f.get("is_dropdown") else known.is_dropdown
                known.known_selectors = _merge_selectors(
                    known.known_selectors or [], selectors
                )
                known.known_options = sorted(set(
                    (known.known_options or []) + (f.get("options") or [])
                ))
                known.observation_count = (known.observation_count or 0) + 1
            else:
                registry_repo.create(
                    marketplace=marketplace,
                    category_path=category_path,
                    normalized_label=label,
                    control_type=f.get("control_type"),
                    is_dropdown=1 if f.get("is_dropdown") else 0,
                    known_selectors=selectors,
                    known_options=f.get("options") or [],
                )
        self.db.commit()


def _step_to_marketplace(step: str) -> str:
    for mp in ("general", "ebay", "etsy", "poshmark", "mercari", "depop", "facebook", "grailed", "whatnot", "shopify"):
        if mp in step.lower():
            return mp
    return "unknown"


def _normalize_label(label: str) -> str:
    normalized = label.strip().lower()
    for suffix in (" (required)", " (optional)", " *", "*"):
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]
    return normalized.strip()


def _build_selector_entry(field: dict, known) -> list[dict]:
    selector = field.get("selector", "")
    if not selector:
        return known.known_selectors if known else []
    return [{"selector": selector, "success_count": 0, "failure_count": 0}]


def _merge_selectors(existing: list, new: list) -> list[dict]:
    merged = list(existing)
    for entry in new:
        sel = entry["selector"]
        found = False
        for m in merged:
            if m["selector"] == sel:
                found = True
                break
        if not found:
            merged.append(entry)
    return merged[:20]


class RegistryRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_identity(self, marketplace: str, category_path: str | None, normalized_label: str) -> FieldRegistry | None:
        if category_path:
            entry = self.db.query(FieldRegistry).filter(
                FieldRegistry.marketplace == marketplace,
                FieldRegistry.category_path == category_path,
                FieldRegistry.normalized_label == normalized_label,
            ).first()
            if entry:
                return entry
        return self.db.query(FieldRegistry).filter(
            FieldRegistry.marketplace == marketplace,
            FieldRegistry.category_path.is_(None),
            FieldRegistry.normalized_label == normalized_label,
        ).first()

    def create(self, marketplace: str, category_path: str | None, normalized_label: str, **kwargs) -> FieldRegistry:
        entry = FieldRegistry(
            marketplace=marketplace,
            category_path=category_path,
            normalized_label=normalized_label,
            **kwargs,
        )
        self.db.add(entry)
        self.db.flush()
        return entry

    def get_valid_options(self, marketplace: str, field_label: str, category_path: str | None = None) -> list[str]:
        label = _normalize_label(field_label)
        entry = self.get_by_identity(marketplace, category_path, label)
        if not entry and category_path:
            entry = self.get_by_identity(marketplace, None, label)
        return sorted(entry.known_options) if entry else []

    def upsert_schema_fields(
        self,
        marketplace: str,
        category_path: str | None,
        fields: list[dict],
    ) -> int:
        """Merge schema-probe fields (with live dropdown options) into the registry.

        Unlike the diagnostics path this is keyed by an explicit marketplace, because
        one probe walks every marketplace panel in a single step.
        """
        touched = 0
        for field in fields or []:
            if not isinstance(field, dict):
                continue
            label = _normalize_label(str(field.get("label") or ""))
            if not label or label == "category":
                continue

            options = [
                str(option.get("label") or "").strip() if isinstance(option, dict) else str(option).strip()
                for option in (field.get("options") or [])
            ]
            options = [option for option in options if option]
            source = str(field.get("options_source") or "").strip() or None
            # A complete read of an open menu is ground truth: replace rather than
            # union, so options Vendoo has removed stop being offered as matches.
            authoritative = bool(options) and source in {"live-dropdown", "native-select"}

            known = self.get_by_identity(marketplace, category_path, label)
            selectors = _build_selector_entry(field, known)

            if known and known.category_path == category_path:
                known.known_selectors = _merge_selectors(known.known_selectors or [], selectors)
                if field.get("is_dropdown"):
                    known.is_dropdown = 1
                if authoritative:
                    known.known_options = sorted(set(options))
                    known.options_source = source
                elif options:
                    known.known_options = sorted(set((known.known_options or []) + options))
                    known.options_source = known.options_source or source
                known.observation_count = (known.observation_count or 0) + 1
            else:
                # Category-specific option sets differ from the category-less entry,
                # so a probe for a new category creates its own row.
                self.create(
                    marketplace=marketplace,
                    category_path=category_path,
                    normalized_label=label,
                    is_dropdown=1 if field.get("is_dropdown") else 0,
                    known_selectors=selectors,
                    known_options=sorted(set(options)),
                    options_source=source,
                    observation_count=1,
                )
            touched += 1

        self.db.commit()
        return touched

    def options_by_label(
        self,
        marketplace: str,
        category_path: str | None = None,
    ) -> dict[str, list[str]]:
        """Known dropdown options for a marketplace, keyed by normalized label."""
        entries = self.list_fields(marketplace, category_path)

        # Category-less rows first so category-specific ones overwrite them.
        result: dict[str, list[str]] = {}
        for entry in sorted(entries, key=lambda e: 1 if e.category_path else 0):
            if not entry.known_options:
                continue
            result[entry.normalized_label] = sorted(entry.known_options)
        return result

    def get_best_selectors(self, marketplace: str, field_label: str, category_path: str | None = None) -> list[dict]:
        label = _normalize_label(field_label)
        entry = self.get_by_identity(marketplace, category_path, label)
        if not entry and category_path:
            entry = self.get_by_identity(marketplace, None, label)
        if not entry or not entry.known_selectors:
            return []
        selectors = sorted(
            entry.known_selectors,
            key=lambda s: -(s.get("success_count", 0) - s.get("failure_count", 0) * 2),
        )
        return [s["selector"] for s in selectors if s.get("selector")]

    def record_fill_result(self, marketplace: str, field_label: str, selector: str, success: bool, category_path: str | None = None):
        label = _normalize_label(field_label)
        if not label or not selector:
            return
        entry = self.get_by_identity(marketplace, category_path, label)
        if not entry:
            self.create(
                marketplace=marketplace,
                category_path=category_path,
                normalized_label=label,
                known_selectors=[{
                    "selector": selector,
                    "success_count": 1 if success else 0,
                    "failure_count": 0 if success else 1,
                }],
            )
            self.db.commit()
            return
        selectors = list(entry.known_selectors or [])
        found = False
        for s in selectors:
            if s.get("selector") == selector:
                if success:
                    s["success_count"] = (s.get("success_count") or 0) + 1
                else:
                    s["failure_count"] = (s.get("failure_count") or 0) + 1
                found = True
                break
        if not found:
            selectors.append({
                "selector": selector,
                "success_count": 1 if success else 0,
                "failure_count": 0 if success else 1,
            })
        entry.known_selectors = selectors
        self.db.commit()

    def ensure_field(self, marketplace: str, field_label: str, selector: str = "", category_path: str | None = None):
        label = _normalize_label(field_label)
        if not label:
            return
        entry = self.get_by_identity(marketplace, category_path, label)
        if not entry:
            selectors = [{"selector": selector, "success_count": 0, "failure_count": 0}] if selector else []
            self.create(
                marketplace=marketplace,
                category_path=category_path,
                normalized_label=label,
                known_selectors=selectors,
            )
            self.db.commit()
            return
        if selector:
            selectors = list(entry.known_selectors or [])
            if not any(s.get("selector") == selector for s in selectors):
                selectors.append({"selector": selector, "success_count": 0, "failure_count": 0})
                entry.known_selectors = selectors
                self.db.commit()

    def list_fields(
        self,
        marketplace: str | None = None,
        category_path: str | None = None,
        *,
        all_categories: bool = False,
    ) -> list[FieldRegistry]:
        query = self.db.query(FieldRegistry)
        if marketplace:
            query = query.filter(FieldRegistry.marketplace == marketplace)
        if category_path:
            query = query.filter(
                (FieldRegistry.category_path == category_path) |
                (FieldRegistry.category_path.is_(None))
            )
        elif not all_categories:
            query = query.filter(FieldRegistry.category_path.is_(None))
        return query.order_by(
            FieldRegistry.marketplace,
            FieldRegistry.category_path,
            FieldRegistry.normalized_label,
        ).all()

    def get_registry_context(self, marketplace: str, category_path: str | None = None) -> str:
        query = self.db.query(FieldRegistry).filter(
            FieldRegistry.marketplace == marketplace
        )
        if category_path:
            query = query.filter(
                (FieldRegistry.category_path == category_path) |
                (FieldRegistry.category_path.is_(None))
            )
        entries = query.order_by(FieldRegistry.normalized_label).all()

        if not entries:
            return ""

        lines = []
        for e in entries:
            cat = f" [{e.category_path}]" if e.category_path else ""
            opts = ", ".join(e.known_options[:30]) if e.known_options else ""
            lines.append(f"- {e.normalized_label}{cat}: {opts}" if opts else f"- {e.normalized_label}{cat}")
        return "\n".join(lines)


class FillLogRepo:
    def __init__(self, db: Session):
        self.db = db

    def replace_step(
        self,
        job_id: str,
        conversation_id: str,
        step: str,
        marketplace: str,
        entries: list[dict],
    ) -> list[FillLogEntry]:
        self.db.query(FillLogEntry).filter(
            FillLogEntry.job_id == job_id,
            FillLogEntry.step == step,
        ).delete(synchronize_session=False)
        saved = []
        for item in entries:
            entry = FillLogEntry(
                job_id=job_id,
                conversation_id=conversation_id,
                step=step,
                marketplace=item.get("marketplace") or marketplace,
                field=item["field"],
                status=item["status"],
                reason=item.get("reason") or "",
                selector=item.get("selector") or "",
                value_preview=item.get("value_preview") or "",
            )
            self.db.add(entry)
            saved.append(entry)
        self.db.commit()
        for entry in saved:
            self.db.refresh(entry)
        return saved

    def add_entries(
        self,
        job_id: str,
        conversation_id: str,
        step: str,
        marketplace: str,
        entries: list[dict],
    ) -> list[FillLogEntry]:
        saved: list[FillLogEntry] = []
        for item in entries:
            entry = FillLogEntry(
                job_id=job_id,
                conversation_id=conversation_id,
                step=step,
                marketplace=item.get("marketplace") or marketplace,
                field=item["field"],
                status=item["status"],
                reason=item.get("reason") or "",
                selector=item.get("selector") or "",
                value_preview=item.get("value_preview") or "",
            )
            self.db.add(entry)
            saved.append(entry)
        self.db.commit()
        for entry in saved:
            self.db.refresh(entry)
        return saved

    def get_for_job_ids(self, job_id: str, ids: list[str]) -> list[FillLogEntry]:
        if not ids:
            return []
        return self.db.query(FillLogEntry).filter(
            FillLogEntry.job_id == job_id,
            FillLogEntry.id.in_(ids),
        ).all()

    def list_for_job(self, job_id: str) -> list[FillLogEntry]:
        return self.db.query(FillLogEntry).filter(
            FillLogEntry.job_id == job_id
        ).order_by(FillLogEntry.created_at, FillLogEntry.field).all()

    def list_for_conversation(self, conversation_id: str) -> list[FillLogEntry]:
        return self.db.query(FillLogEntry).filter(
            FillLogEntry.conversation_id == conversation_id
        ).order_by(FillLogEntry.created_at.desc()).all()

    def delete_for_job(self, job_id: str) -> None:
        self.db.query(FillLogEntry).filter(FillLogEntry.job_id == job_id).delete(synchronize_session=False)
        self.db.commit()

    def delete_for_step(self, job_id: str, step: str) -> None:
        if not step:
            return
        self.db.query(FillLogEntry).filter(
            FillLogEntry.job_id == job_id,
            FillLogEntry.step == step,
        ).delete(synchronize_session=False)
        self.db.commit()

    def delete_for_jobs(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        self.db.query(FillLogEntry).filter(FillLogEntry.job_id.in_(job_ids)).delete(synchronize_session=False)
