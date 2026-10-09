from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import ResultMessage, StreamEvent

from vendoo_studio.providers.claude_agent import SIGNED_OUT, ClaudeProvider, to_claude_turn
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.services import claude_auth


def _text_delta(text: str) -> StreamEvent:
    return StreamEvent(
        uuid="u",
        session_id="s",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    )


def _result(text: str, *, is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        subtype="error_during_execution" if is_error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s",
        result=text,
    )


def _fake_query(messages, captured: dict):
    async def query(*, prompt, options):
        captured["options"] = options
        captured["turns"] = [turn async for turn in prompt]
        for message in messages:
            yield message

    return query


def _collect(provider_call) -> list[tuple[str, str]]:
    async def run():
        return [unpack_stream_item(chunk) async for chunk in provider_call]

    return asyncio.run(run())


class ToClaudeTurnTest(unittest.TestCase):
    def test_folds_history_into_system_prompt_and_one_user_turn(self):
        system, blocks = to_claude_turn(
            [
                {"role": "system", "content": "Listing rules."},
                {"role": "user", "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ]},
                {"role": "assistant", "content": "A jacket."},
                {"role": "user", "content": "Brand?"},
            ],
            "Preamble.",
        )
        self.assertEqual(system, "Preamble.\n\nListing rules.")
        self.assertEqual(
            blocks[0],
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
        )
        self.assertEqual(
            blocks[1]["text"],
            "USER:\nWhat is this?\n\nASSISTANT:\nA jacket.\n\nUSER:\nBrand?",
        )


class ClaudeProviderRunTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(claude_auth, "claude_cli_path", return_value="/usr/bin/claude")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_chat_streams_text_with_no_tools_and_no_user_settings(self):
        captured: dict = {}
        with patch(
            "claude_agent_sdk.query",
            _fake_query([_text_delta("Lev"), _text_delta("i's"), _result("Levi's")], captured),
        ):
            chunks = _collect(ClaudeProvider().chat([{"role": "user", "content": "Brand?"}]))
        self.assertEqual(chunks, [("content", "Lev"), ("content", "i's")])
        options = captured["options"]
        self.assertEqual(options.tools, [])
        self.assertEqual(options.setting_sources, [])
        self.assertEqual(options.cli_path, "/usr/bin/claude")
        self.assertEqual(captured["turns"][0]["message"]["content"][-1]["text"], "USER:\nBrand?")

    def test_web_search_returns_only_the_final_answer(self):
        captured: dict = {}
        with patch(
            "claude_agent_sdk.query",
            _fake_query([_text_delta("Let me search."), _result('{"comps": []}')], captured),
        ):
            result = asyncio.run(ClaudeProvider().web_search([{"role": "user", "content": "comps"}]))
        self.assertEqual(result, {"answer": '{"comps": []}', "sources": []})
        self.assertEqual(captured["options"].tools, ["WebSearch", "WebFetch"])

    def test_signed_out_run_asks_to_sign_in_again(self):
        with patch(
            "claude_agent_sdk.query",
            _fake_query([_result("Not logged in · Please run /login", is_error=True)], {}),
        ):
            with self.assertRaisesRegex(RuntimeError, SIGNED_OUT):
                _collect(ClaudeProvider().chat([{"role": "user", "content": "hi"}]))


class ClaudeAuthStatusTest(unittest.TestCase):
    def test_reads_account_from_claude_auth_status(self):
        payload = {"loggedIn": True, "email": "seller@example.com", "subscriptionType": "max"}
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
        with (
            patch.object(claude_auth, "claude_cli_path", return_value="/usr/bin/claude"),
            patch("vendoo_studio.services.claude_auth.subprocess.run", return_value=done) as run,
        ):
            status = claude_auth._read_status()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/claude", "auth", "status"])
        self.assertTrue(status.signed_in)
        self.assertEqual(status.email, "seller@example.com")
        self.assertEqual(status.plan, "max")

    def test_not_installed_without_a_cli(self):
        with patch.object(claude_auth, "claude_cli_path", return_value=None):
            status = claude_auth._read_status()
        self.assertFalse(status.installed)
        self.assertFalse(status.signed_in)


FAKE_LOGIN = textwrap.dedent("""\
    #!/bin/sh
    echo "Opening browser to sign in…"
    echo "If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true"
    printf "Paste code here if prompted > "
    read code
    if [ "$code" = "good#state" ]; then echo "Login successful."; exit 0; fi
    echo "Login failed: Request failed with status code 400"
    exit 1
""")


class ClaudeLoginTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.cli = Path(tmp) / "claude"
        self.cli.write_text(FAKE_LOGIN)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        patcher = patch.object(claude_auth, "claude_cli_path", return_value=os.fspath(self.cli))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _login(self, code: str) -> tuple[dict, str | None]:
        async def run():
            started = await claude_auth.start_login()
            self.assertEqual(claude_auth.pending_login(), started)
            error = None
            try:
                await claude_auth.submit_code(code)
            except RuntimeError as exc:
                error = str(exc)
            return started, error

        return asyncio.run(run())

    def test_pasted_code_finishes_the_login(self):
        started, error = self._login("good#state")
        self.assertEqual(started["url"], "https://claude.com/cai/oauth/authorize?code=true")
        self.assertIsNone(error)
        self.assertIsNone(claude_auth.pending_login())
        self.assertIsNone(claude_auth.login_error())

    def test_rejected_code_reports_the_cli_error(self):
        _, error = self._login("bad")
        self.assertEqual(
            error, "Claude did not accept that code. Sign in again and paste the newest code."
        )
        self.assertEqual(claude_auth.login_error(), error)


class ListingProviderClaudeTest(unittest.TestCase):
    def test_claude_runs_listings_when_primary_and_signed_in(self):
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("claude", "none"),
            ),
            patch("vendoo_studio.services.listing_provider.claude_signed_in", return_value=True),
        ):
            self.assertIsInstance(listing_provider.get_listing_provider(), ClaudeProvider)
            self.assertTrue(listing_provider.provider_is_configured())

    def test_settings_report_the_claude_account(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        signed_in = claude_auth._Status(
            installed=True, signed_in=True, email="seller@example.com", plan="pro"
        )
        with (
            patch.object(claude_auth, "_read_status", return_value=signed_in),
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("claude", "none"),
            ),
            patch(
                "vendoo_studio.services.user_settings.get_listing_provider_order",
                return_value=("claude", "none"),
            ),
        ):
            claude_auth.forget_status()
            body = TestClient(app).get("/api/settings/provider").json()
        self.assertEqual(body["provider"], "claude")
        self.assertEqual(body["primary"], "claude")
        self.assertEqual(body["claude"]["email"], "seller@example.com")
        self.assertEqual(body["claude"]["plan"], "pro")
        self.assertTrue(body["claude"]["signed_in"])
