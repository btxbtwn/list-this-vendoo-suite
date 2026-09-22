#!/usr/bin/env python3
"""Fail when Studio's release version manifests disagree."""

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    versions = {
        "VERSION": version,
        "package.json": package.get("version"),
        "package-lock.json": package_lock.get("version"),
        'package-lock.json packages[""]': package_lock.get("packages", {}).get("", {}).get("version"),
        "pyproject.toml": pyproject.get("project", {}).get("version"),
    }

    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"VERSION must be a semantic version, got {version!r}")

    mismatches = {name: value for name, value in versions.items() if value != version}
    if mismatches:
        details = "\n".join(f"  {name}: {value!r}" for name, value in versions.items())
        raise SystemExit(
            f"Studio versions are out of sync:\n{details}\n"
            "Run vendoo-studio/scripts/bump-version.sh and commit every changed manifest."
        )

    print(f"Studio version manifests agree: {version}")


if __name__ == "__main__":
    main()
