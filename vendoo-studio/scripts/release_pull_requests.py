#!/usr/bin/env python3
"""Collect pull requests included since the previously published Studio build."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def first_parent_commits(repo: Path, base: str | None, head: str) -> list[str]:
    if base == head:
        return []
    revision = f"{base}..{head}" if base else head
    command = ["git", "-C", str(repo), "rev-list", "--first-parent"]
    if not base:
        command.append("--max-count=1")
    command.append(revision)
    return [line.strip() for line in _run(command).splitlines() if line.strip()]


def pull_requests_for_commits(
    repository: str,
    commits: list[str],
    *,
    base_ref: str,
) -> list[dict[str, object]]:
    pull_requests: list[dict[str, object]] = []
    seen: set[int] = set()
    for sha in commits:
        payload = json.loads(
            _run(
                [
                    "gh",
                    "api",
                    f"repos/{repository}/commits/{sha}/pulls",
                    "-H",
                    "Accept: application/vnd.github+json",
                ]
            )
        )
        for pull_request in payload:
            base = pull_request.get("base") or {}
            if not pull_request.get("merged_at") or base.get("ref") != base_ref:
                continue
            number = int(pull_request["number"])
            title = str(pull_request.get("title") or "").strip()
            if number in seen or not title:
                continue
            seen.add(number)
            pull_requests.append(
                {
                    "number": number,
                    "title": title,
                    "url": str(pull_request.get("html_url") or "").strip(),
                }
            )
    return pull_requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base")
    parser.add_argument("--head", required=True)
    parser.add_argument("--base-ref", default="main")
    args = parser.parse_args()

    commits = first_parent_commits(args.repo_path, args.base, args.head)
    pull_requests = pull_requests_for_commits(
        args.repository,
        commits,
        base_ref=args.base_ref,
    )
    print(json.dumps(pull_requests, separators=(",", ":")))


if __name__ == "__main__":
    main()
