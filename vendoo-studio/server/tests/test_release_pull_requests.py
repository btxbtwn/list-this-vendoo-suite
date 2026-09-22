from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[2] / "scripts" / "release_pull_requests.py"
SPEC = importlib.util.spec_from_file_location("release_pull_requests", SCRIPT)
assert SPEC and SPEC.loader
release_pull_requests = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_pull_requests)


def test_first_parent_range_is_newest_first() -> None:
    with patch.object(
        release_pull_requests,
        "_run",
        return_value="newest\nolder\n",
    ) as run:
        commits = release_pull_requests.first_parent_commits(Path("/repo"), "old", "new")
    assert commits == ["newest", "older"]
    assert run.call_args.args[0][-1] == "old..new"


def test_same_build_has_no_new_commits() -> None:
    with patch.object(release_pull_requests, "_run") as run:
        commits = release_pull_requests.first_parent_commits(Path("/repo"), "same", "same")
    assert commits == []
    run.assert_not_called()


def test_pull_requests_are_filtered_and_deduplicated() -> None:
    responses = [
        json.dumps(
            [
                {
                    "number": 12,
                    "title": "Newest",
                    "html_url": "https://example.test/12",
                    "merged_at": "2026-09-22T00:00:00Z",
                    "base": {"ref": "main"},
                },
                {
                    "number": 99,
                    "title": "Other branch",
                    "merged_at": "2026-09-22T00:00:00Z",
                    "base": {"ref": "release"},
                },
            ]
        ),
        json.dumps(
            [
                {
                    "number": 12,
                    "title": "Newest",
                    "merged_at": "2026-09-22T00:00:00Z",
                    "base": {"ref": "main"},
                },
                {
                    "number": 11,
                    "title": "Older",
                    "html_url": "https://example.test/11",
                    "merged_at": "2026-09-21T00:00:00Z",
                    "base": {"ref": "main"},
                },
            ]
        ),
    ]
    with patch.object(release_pull_requests, "_run", side_effect=responses):
        pulls = release_pull_requests.pull_requests_for_commits(
            "owner/repo",
            ["newest", "older"],
            base_ref="main",
        )
    assert pulls == [
        {"number": 12, "title": "Newest", "url": "https://example.test/12"},
        {"number": 11, "title": "Older", "url": "https://example.test/11"},
    ]
