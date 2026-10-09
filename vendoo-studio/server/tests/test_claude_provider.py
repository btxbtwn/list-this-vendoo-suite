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
    [ -t 0 ] && echo "on a terminal: $*"
    printf "Paste code here if prompted > "
    read code
    if [ "$code" = "good#state" ]; then echo "Login successful."; exit 0; fi
    echo "Login failed"
    exit 1
""")


class ClaudeLoginTerminalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.cli = Path(tmp) / "claude"
        self.cli.write_text(FAKE_LOGIN)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        patcher = patch.object(claude_auth, "claude_cli_path", return_value=os.fspath(self.cli))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _login(self, code: str) -> tuple[str, dict]:
        from fastapi.testclient import TestClient

        from vendoo_studio.config import CORS_ORIGINS
        from vendoo_studio.main import app

        output = ""
        with TestClient(app).websocket_connect(
            "/api/settings/claude/terminal?cols=100&rows=30",
            headers={"origin": CORS_ORIGINS[0]},
        ) as ws:
            while "prompted >" not in output:
                output += ws.receive_bytes().decode()
            ws.send_text(json.dumps({"type": "input", "data": code + "\r"}))
            while True:
                message = ws.receive()
                if message.get("bytes") is not None:
                    output += message["bytes"].decode()
                else:
                    return output, json.loads(message["text"])

    def test_runs_the_login_on_a_terminal_and_reports_success(self):
        output, last = self._login("good#state")
        self.assertIn("on a terminal: auth login --claudeai", output)
        self.assertIn("Login successful.", output)
        self.assertEqual(last, {"type": "exit", "code": 0})

    def test_a_failed_login_reports_its_exit_code(self):
        output, last = self._login("bad")
        self.assertIn("Login failed", output)
        self.assertEqual(last, {"type": "exit", "code": 1})

    def test_other_origins_cannot_open_it(self):
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        from vendoo_studio.main import app

        with self.assertRaises(WebSocketDisconnect):
            with TestClient(app).websocket_connect(
                "/api/settings/claude/terminal", headers={"origin": "https://example.com"}
            ) as ws:
                ws.receive()


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


class ClaudeModelSettingsTest(unittest.TestCase):
    def setUp(self):
        from vendoo_studio.services import user_settings

        def forget_models():
            user_settings.update_settings(lambda payload: payload.pop(user_settings.CLAUDE_MODELS_KEY, None))

        forget_models()
        self.addCleanup(forget_models)
        patcher = patch.object(claude_auth, "claude_cli_path", return_value="/usr/bin/claude")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_runs_use_the_saved_models_and_effort(self):
        from vendoo_studio.services.user_settings import set_claude_models

        set_claude_models(vision_model="haiku", listing_model="opus", effort="low")
        provider = ClaudeProvider()
        self.assertEqual((provider.vision_model, provider.listing_model), ("haiku", "opus"))
        captured: dict = {}
        with patch("claude_agent_sdk.query", _fake_query([_result("OK")], captured)):
            _collect(provider.chat([{"role": "user", "content": "hi"}]))
        self.assertEqual(captured["options"].model, "opus")
        self.assertEqual(captured["options"].effort, "low")

    def test_default_effort_hands_the_choice_back_to_claude_code(self):
        from vendoo_studio.services.user_settings import get_claude_models, set_claude_models

        set_claude_models(listing_model="opus", effort="max")
        set_claude_models(effort="default")
        self.assertEqual(get_claude_models(), {"listing_model": "opus"})
        self.assertIsNone(ClaudeProvider().effort)

    def test_settings_list_the_account_models_and_save_a_pick(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app
        from vendoo_studio.services.user_settings import get_claude_models

        catalog = [
            {"value": "sonnet", "label": "Sonnet", "efforts": ["low", "high"]},
            {"value": "claude-haiku-4-5", "label": "Haiku 4.5", "efforts": []},
        ]
        signed_in = claude_auth._Status(installed=True, signed_in=True)
        client = TestClient(app)
        with (
            patch.object(claude_auth, "_read_status", return_value=signed_in),
            patch("vendoo_studio.providers.claude_agent.list_models", return_value=catalog),
        ):
            claude_auth.forget_status()
            saved = client.put("/api/settings/claude/models", json={"effort": "high"})
            body = client.get("/api/settings/claude/models").json()
            client.put("/api/settings/claude/models", json={"listing_model": "claude-haiku-4-5"})
            haiku = client.get("/api/settings/claude/models").json()
        claude_auth.forget_status()
        self.assertEqual(saved.status_code, 200)
        self.assertEqual([item["value"] for item in body["models"]], ["sonnet", "claude-haiku-4-5"])
        self.assertEqual((body["listing_model"], body["effort"], body["efforts"]), ("sonnet", "high", ["low", "high"]))
        self.assertEqual((haiku["effort"], haiku["efforts"]), (None, []))
        self.assertEqual(get_claude_models()["listing_model"], "claude-haiku-4-5")

    def test_provider_status_keeps_the_photo_choice_while_claude_writes(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        signed_in = claude_auth._Status(installed=True, signed_in=True)
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
            patch(
                "vendoo_studio.services.user_settings.get_photo_provider_choice",
                return_value="chatgpt",
            ),
        ):
            claude_auth.forget_status()
            body = TestClient(app).get("/api/settings/provider").json()
        claude_auth.forget_status()
        self.assertEqual(body["provider"], "claude")
        self.assertEqual(body["photo_provider"], "chatgpt")
