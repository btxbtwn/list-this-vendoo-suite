from __future__ import annotations

import unittest
from unittest.mock import patch

from vendoo_studio.services import tailscale_serve as ts


class TailscaleServeTests(unittest.TestCase):
    def test_status_missing_when_not_installed(self):
        with patch.object(ts, "_which_tailscale", return_value=None):
            payload = ts.status()
        self.assertFalse(payload["installed"])
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["state"], "missing")
        self.assertIn("not installed", payload["error"].lower())

    def test_classify_configured_route(self):
        host = "mac.tailnet.ts.net"
        config = {
            "TCP": {str(ts.HTTPS_PORT): {"HTTPS": True}},
            "Web": {f"{host}:{ts.HTTPS_PORT}": {"Handlers": {"/": {"Proxy": ts.TARGET}}}},
            "AllowFunnel": {},
        }
        self.assertEqual(ts._classify_route(config, host), "configured")

    def test_classify_funnel(self):
        host = "mac.tailnet.ts.net"
        config = {
            "TCP": {str(ts.HTTPS_PORT): {"HTTPS": True}},
            "Web": {f"{host}:{ts.HTTPS_PORT}": {"Handlers": {"/": {"Proxy": ts.TARGET}}}},
            "AllowFunnel": {f"{host}:{ts.HTTPS_PORT}": True},
        }
        self.assertEqual(ts._classify_route(config, host), "funnel")

    def test_classify_conflict_different_proxy(self):
        host = "mac.tailnet.ts.net"
        config = {
            "TCP": {str(ts.HTTPS_PORT): {"HTTPS": True}},
            "Web": {
                f"{host}:{ts.HTTPS_PORT}": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}
            },
        }
        self.assertEqual(ts._classify_route(config, host), "conflict")

    def test_enable_is_idempotent_when_configured(self):
        configured = {
            "available": True,
            "installed": True,
            "enabled": True,
            "https_port": ts.HTTPS_PORT,
            "target": ts.TARGET,
            "dns_name": "mac.tailnet.ts.net",
            "url": f"https://mac.tailnet.ts.net:{ts.HTTPS_PORT}",
            "state": "configured",
            "error": None,
            "funnel": False,
        }
        with patch.object(ts, "status", return_value=configured) as status_mock:
            with patch.object(ts, "_run") as run_mock:
                result = ts.enable()
        self.assertTrue(result["enabled"])
        run_mock.assert_not_called()
        status_mock.assert_called()

    def test_enable_runs_serve_when_free(self):
        free = {
            "available": True,
            "installed": True,
            "enabled": False,
            "https_port": ts.HTTPS_PORT,
            "target": ts.TARGET,
            "dns_name": "mac.tailnet.ts.net",
            "url": f"https://mac.tailnet.ts.net:{ts.HTTPS_PORT}",
            "state": "free",
            "error": None,
            "funnel": False,
        }
        configured = {**free, "enabled": True, "state": "configured"}

        def status_side_effect():
            return configured if status_side_effect.calls else free

        status_side_effect.calls = 0

        def status_wrapper():
            payload = configured if status_side_effect.calls else free
            status_side_effect.calls += 1
            return payload

        with patch.object(ts, "status", side_effect=status_wrapper):
            with patch.object(ts, "_run") as run_mock:
                run_mock.return_value.returncode = 0
                run_mock.return_value.stdout = ""
                run_mock.return_value.stderr = ""
                result = ts.enable()
        self.assertTrue(result["enabled"])
        run_mock.assert_called_once()
        args = run_mock.call_args[0][0]
        self.assertEqual(args[:2], ["serve", "--bg"])
        self.assertIn(f"--https={ts.HTTPS_PORT}", args)
        self.assertIn(ts.TARGET, args)

    def test_disable_refuses_foreign_route(self):
        conflict = {
            "available": True,
            "installed": True,
            "enabled": False,
            "https_port": ts.HTTPS_PORT,
            "target": ts.TARGET,
            "dns_name": "mac.tailnet.ts.net",
            "url": f"https://mac.tailnet.ts.net:{ts.HTTPS_PORT}",
            "state": "conflict",
            "error": "port busy",
            "funnel": False,
        }
        with patch.object(ts, "status", return_value=conflict):
            with patch.object(ts, "_serve_status", return_value={"TCP": {}, "Web": {}}):
                with patch.object(ts, "_classify_route", return_value="conflict"):
                    with self.assertRaises(ts.TailscaleServeError) as ctx:
                        ts.disable()
        self.assertIn("not Studio", str(ctx.exception))

    def test_dns_name_from_status_json(self):
        payload = {"Self": {"DNSName": "criss-mac-mini-1.tail6c7361.ts.net."}}
        with patch.object(ts, "_run_json", return_value=payload):
            self.assertEqual(ts.dns_name(), "criss-mac-mini-1.tail6c7361.ts.net")


if __name__ == "__main__":
    unittest.main()
