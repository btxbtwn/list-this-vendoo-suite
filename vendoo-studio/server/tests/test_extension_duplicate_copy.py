"""Two copies of the bridge must not take turns on one connection.

Everyday Chrome can hold the app's unpacked folder and an older data folder at
the same time. Each pairing used to close the other copy's socket, so the two
reconnected at half-second intervals and dropped whatever was in flight: a form
read failed, a listing check never finished.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.services.extension_connection import ExtensionManager


class Incumbent:
    """The already-paired copy's socket, which must keep working unless replaced."""

    def __init__(self):
        self.closed = False

    async def send_json(self, message):
        pass

    async def close(self):
        self.closed = True

    async def receive_text(self):
        await asyncio.sleep(3600)


class DuplicateCopyTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        app.dependency_overrides[get_db] = lambda: self.Session()
        self.manager = ExtensionManager()
        self.incumbent = Incumbent()
        self.manager.connection = self.incumbent
        self.manager.paired = True

    def tearDown(self):
        app.dependency_overrides.clear()

    def _connect(self, ready: dict, lockstep, *, expect_reply: bool):
        """Pair one more socket while ``lockstep`` decides which copy runs this build."""

        async def handshake(*_args):
            return True

        patches = [
            patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session),
            patch("vendoo_studio.services.extension_connection.extension_manager", self.manager),
            patch.object(self.manager, "verify_token", return_value=True),
            patch("vendoo_studio.services.extension_connection._websocket_allowed", return_value=True),
            patch("vendoo_studio.services.extension_connection.handshake_extension", side_effect=handshake),
            patch("vendoo_studio.services.extension_connection.dispatch_queued_jobs", AsyncMock()),
            patch("vendoo_studio.services.extension_connection.extension_in_lockstep", side_effect=lockstep),
        ]
        for patch_object in patches:
            patch_object.start()
            self.addCleanup(patch_object.stop)
        client = TestClient(app)
        with client.websocket_connect("/api/extension/ws") as ws:
            ws.send_json({"type": "extension.ready", "payload": ready})
            client.get("/api/health")
            # The socket's own close clears these, so read them while it is open.
            return {
                "reply": ws.receive_json() if expect_reply else None,
                "connection": self.manager.connection,
                "version": self.manager.version,
                "build": self.manager.build,
                "paired": self.manager.paired,
                "duplicate_bridge": self.manager.duplicate_bridge,
            }

    def test_a_second_copy_is_told_to_stand_down_and_the_paired_one_keeps_the_socket(self):
        self.manager.version = "0.2.37"
        self.manager.build = "same-build"
        seen = self._connect({"token": "test", "version": "0.2.37", "build": "same-build"},
                            lambda build, version=None: build == "same-build", expect_reply=True)
        self.assertEqual(seen["reply"]["type"], "error")
        self.assertTrue(seen["reply"]["duplicate_bridge"])
        self.assertIn("chrome://extensions", seen["reply"]["message"])
        self.assertFalse(self.incumbent.closed)
        self.assertIs(seen["connection"], self.incumbent)
        self.assertTrue(seen["paired"])
        self.assertTrue(seen["duplicate_bridge"])

    def test_the_copy_that_runs_this_build_takes_the_socket_from_a_stale_one(self):
        self.manager.version = "0.2.30"
        self.manager.build = None
        seen = self._connect({"token": "test", "version": "0.2.37", "build": "this-build"},
                            lambda build, version=None: build == "this-build", expect_reply=False)
        self.assertTrue(self.incumbent.closed)
        self.assertIsNot(seen["connection"], self.incumbent)
        self.assertEqual((seen["version"], seen["build"]), ("0.2.37", "this-build"))
        self.assertTrue(seen["paired"])
        self.assertFalse(seen["duplicate_bridge"])
