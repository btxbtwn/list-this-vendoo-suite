from __future__ import annotations

from sqlalchemy.orm import Session

from vendoo_studio.models.conversation import Conversation, Message, Photo, new_id
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.models.job import Job, JobEvent
from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation
from vendoo_studio.models.registry import FieldRegistry
from vendoo_studio.models.fill_log import FillLogEntry


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

    def update_status(self, conv_id: str, status: str) -> Conversation | None:
        conv = self.get(conv_id)
        if not conv:
            return None
        conv.status = status
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def reconcile_job_statuses(self) -> None:
        status_map = {
            "queued": "listing",
            "dispatched": "listing",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "draft",
        }
        changed = False
        for conv in self.db.query(Conversation).all():
            if conv.status == "in_progress":
                continue
            latest_job = self.db.query(Job).filter(
                Job.conversation_id == conv.id
            ).order_by(Job.created_at.desc()).first()
            if not latest_job or latest_job.status not in status_map:
                continue
            if conv.updated_at and latest_job.updated_at and latest_job.updated_at < conv.updated_at:
                continue
            next_status = status_map[latest_job.status]
            if conv.status != next_status:
                conv.status = next_status
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
    for mp in ("general", "ebay", "etsy", "poshmark", "mercari", "depop"):
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
            FieldRegistry.category_path == None,
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

    def get_registry_context(self, marketplace: str, category_path: str | None = None) -> str:
        query = self.db.query(FieldRegistry).filter(
            FieldRegistry.marketplace == marketplace
        )
        if category_path:
            query = query.filter(
                (FieldRegistry.category_path == category_path) |
                (FieldRegistry.category_path == None)
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

    def delete_for_jobs(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        self.db.query(FillLogEntry).filter(FillLogEntry.job_id.in_(job_ids)).delete(synchronize_session=False)

