"""A Chrome bridge that pairs and drops in a loop must not re-run reconnect work.

An accepted pairing is not by itself a reconnect: a worker that drops every half
second looks paired each time, and resuming interrupted sends or asking Chrome
to check a listing on every tick re-queues work until the check times out.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.services.extension_connection import (
    RECONNECT_SETTLE_SEC,
    ExtensionManager,
    _after_pairing,
    _reconnect_tasks,
    _run_reconnect_work,
)


class FakeSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True


class NoteHandshakeTest(unittest.TestCase):
    def test_the_first_pairing_stands_on_its_own(self):
        self.assertTrue(ExtensionManager().note_handshake(100.0))

    def test_a_pairing_within_the_settle_window_is_a_flap(self):
        manager = ExtensionManager()
        self.assertTrue(manager.note_handshake(100.0))
        self.assertFalse(manager.note_handshake(101.0))
        self.assertFalse(manager.note_handshake(103.0))
        self.assertTrue(manager.note_handshake(100.0 + 2 * RECONNECT_SETTLE_SEC))

    def test_disconnecting_keeps_the_time_of_the_last_pairing(self):
        manager = ExtensionManager()
        manager.note_handshake(100.0)
        manager._mark_disconnected()
        self.assertFalse(manager.note_handshake(101.0))


class ReconnectWorkTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)

    def _patch_work(self, manager, settle=RECONNECT_SETTLE_SEC):
        """Stand the bridge up around a manager and watch the reconnect work."""
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", manager))
        self.enterContext(patch("vendoo_studio.services.extension_connection.RECONNECT_SETTLE_SEC", settle))
        resume = self.enterContext(patch("vendoo_studio.services.extension_connection._resume_interrupted_sends"))
        warm = self.enterContext(
            patch("vendoo_studio.services.extension_connection._warm_label_catalog", new=AsyncMock())
        )
        # Imported inside the work, so it is patched where it is defined.
        self.enterContext(
            patch("vendoo_studio.services.native_marketplaces.reconcile_then_dispatch", new=AsyncMock())
        )
        return resume, warm

    async def test_a_settled_pairing_resumes_and_reconciles(self):
        manager = ExtensionManager()
        manager.connection = FakeSocket()
        manager.paired = True
        resume, warm = self._patch_work(manager)
        self.assertTrue(_run_reconnect_work(self.db))
        await asyncio.sleep(0)
        resume.assert_called_once()
        warm.assert_called_once()

    async def test_a_flapping_pairing_holds_the_work_until_it_settles(self):
        manager = ExtensionManager()
        ws = FakeSocket()
        manager.connection = ws
        manager.paired = True
        resume, warm = self._patch_work(manager, settle=0.5)
        manager.note_handshake()  # the pairing that just flapped
        _after_pairing(self.db, ws)
        resume.assert_not_called()
        # The socket outlives the window, so the work runs after it. Shorten the
        # window now: the deferred check reads it when it wakes.
        self.enterContext(patch("vendoo_studio.services.extension_connection.RECONNECT_SETTLE_SEC", 0.01))
        await asyncio.sleep(0.1)
        resume.assert_called_once()
        warm.assert_called_once()
        self.assertEqual(_reconnect_tasks, set())

    async def test_a_flapping_pairing_that_drops_again_does_nothing(self):
        manager = ExtensionManager()
        ws = FakeSocket()
        manager.connection = ws
        manager.paired = True
        resume, warm = self._patch_work(manager, settle=0.5)
        manager.note_handshake()  # the pairing that just flapped
        _after_pairing(self.db, ws)
        manager.connection = FakeSocket()  # the worker paired again already
        self.enterContext(patch("vendoo_studio.services.extension_connection.RECONNECT_SETTLE_SEC", 0.01))
        await asyncio.sleep(0.1)
        resume.assert_not_called()
        warm.assert_not_called()
        self.assertEqual(_reconnect_tasks, set())
