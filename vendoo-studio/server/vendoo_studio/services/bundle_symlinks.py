"""Helpers for Mac app bundle symlinks in packaging and update zips."""

from __future__ import annotations

import os
import shutil
import stat
import zipfile
from pathlib import Path


class BundleSymlinkError(RuntimeError):
    pass


def flatten_symlinks(root: Path) -> int:
    """Replace every symlink under root with a real file/directory copy.

    Older Studio builds rejected every symlink zip member, so release zips must
    ship without them. Returns the number of links replaced.
    """
    root = root.resolve()
    if not root.is_dir():
        raise BundleSymlinkError(f"Not a directory: {root}")
    links = sorted(
        (path for path in root.rglob("*") if path.is_symlink()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for link in links:
        target = link.resolve()
        if target != root and not str(target).startswith(str(root) + os.sep):
            raise BundleSymlinkError(f"Refusing to flatten external symlink: {link} -> {target}")
        link.unlink()
        if target.is_dir():
            shutil.copytree(target, link, symlinks=False)
        else:
            shutil.copy2(target, link)
    return len(links)


def zip_symlink_members(archive: Path) -> list[tuple[str, str]]:
    """Return (member_name, link_target) for every symlink stored in the zip."""
    found: list[tuple[str, str]] = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            if mode != stat.S_IFLNK:
                continue
            target = bundle.read(info).decode("utf-8", errors="surrogateescape")
            found.append((info.filename, target))
    return found


def assert_zip_has_no_symlinks(archive: Path) -> None:
    links = zip_symlink_members(archive)
    if not links:
        return
    sample = ", ".join(f"{name} -> {target}" for name, target in links[:5])
    extra = "" if len(links) <= 5 else f" (+{len(links) - 5} more)"
    raise BundleSymlinkError(
        f"Update zip contains {len(links)} symbolic link(s); expected none after flatten. "
        f"Examples: {sample}{extra}"
    )
