from __future__ import annotations

import asyncio
import contextvars
import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.providers.xiaomi_mimo import StreamChunk
from vendoo_studio.services import live_trace
from vendoo_studio.services.brave_search import search_all


def _traced(coro_factory):
    """Run a coroutine with a bound sink in a fresh context; return (result, events)."""
    events: list[tuple[str, str]] = []

    async def main():
        live_trace.bind(lambda kind, text: events.append((kind, text)))
        return await coro_factory()

    result = contextvars.Context().run(asyncio.run, main())
    return result, events


class LiveTraceTest(unittest.TestCase):
    def test_emit_without_a_sink_is_a_no_op(self):
        contextvars.Context().run(live_trace.emit, "step", "nothing listens")

    def test_child_tasks_inherit_the_sink(self):
        async def child():
            live_trace.emit("step", "from a child")

        async def work():
            await asyncio.create_task(child())

        _, events = _traced(work)
        self.assertEqual(events, [("step", "from a child")])

    def test_a_failing_sink_does_not_break_the_caller(self):
        def run():
            live_trace.bind(lambda kind, text: 1 / 0)
            live_trace.emit("thinking", "still fine")

        contextvars.Context().run(run)

    def test_brave_reports_each_finished_query(self):
        with patch(
            "vendoo_studio.services.brave_search.search_web",
            new=AsyncMock(return_value=[{"title": "x"}]),
        ), patch("vendoo_studio.services.brave_search.BRAVE_QUERY_STAGGER_SEC", 0):
            _, events = _traced(lambda: search_all(["levis sold", "levis 501 sold"], "BSA-test"))
        self.assertEqual(
            sorted(events),
            [("step", "Searched Brave: levis 501 sold"), ("step", "Searched Brave: levis sold")],
        )


class ChatGPTTraceTest(unittest.TestCase):
    def _provider(self):
        from vendoo_studio.providers import chatgpt_codex

        with patch.object(chatgpt_codex, "resolved_chatgpt_models", return_value=("gpt-5.5", "gpt-5.5")), \
                patch.object(chatgpt_codex, "resolved_chatgpt_reasoning", return_value="low"):
            return chatgpt_codex.ChatGPTCodexProvider()

    def test_photo_analysis_streams_its_reasoning(self):
        provider = self._provider()

        async def fake_stream(messages, model, **kwargs):
            yield StreamChunk("Reading the size tag", "thinking")
            yield StreamChunk('{"brand": {"value": "Levi\'s"}}', "content")

        provider._stream = fake_stream
        with patch("vendoo_studio.providers.chatgpt_codex.encode_images", new=AsyncMock(return_value=[])):
            result, events = _traced(lambda: provider.analyze_photos([]))
        self.assertEqual(result["evidence"]["brand"]["value"], "Levi's")
        self.assertEqual(events, [("thinking", "Reading the size tag")])

    def test_web_search_reports_its_queries(self):
        import json

        provider = self._provider()
        call = {"type": "web_search_call", "action": {"type": "search", "query": "levis 501 sold ebay"}}
        answer = {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}

        async def fake_search(messages, **kwargs):
            yield StreamChunk(json.dumps([call]), "output")
            yield StreamChunk(json.dumps([answer]), "output")

        provider._stream_search = fake_search
        _, events = _traced(
            lambda: provider._web_search_once([], tools=[], tool_choice="required")
        )
        self.assertEqual(events, [("step", "ChatGPT searched: levis 501 sold ebay")])


if __name__ == "__main__":
    unittest.main()
