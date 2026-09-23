"""Snapshot listing, on-demand snapshots, and the off-machine backup folder."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vendoo_studio.services.backups import (
    BackupError,
    backup_folder,
    list_snapshots,
    set_backup_folder,
    storage_status,
    take_snapshot,
)

router = APIRouter(prefix="/api/backups", tags=["backups"])


class BackupFolderConfig(BaseModel):
    folder: str | None = None


@router.get("")
def get_backups():
    snapshots = list_snapshots()
    folder = backup_folder()
    return {
        "snapshots": [snapshot.as_dict() for snapshot in snapshots],
        "folder": str(folder) if folder else None,
        "latest": snapshots[0].as_dict() if snapshots else None,
        **storage_status(),
    }


@router.post("")
def create_backup():
    try:
        snapshot = take_snapshot("manual")
    except BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "snapshot": snapshot.as_dict()}


@router.put("/folder")
def put_backup_folder(config: BackupFolderConfig):
    try:
        folder = set_backup_folder(config.folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "folder": str(folder) if folder else None}
