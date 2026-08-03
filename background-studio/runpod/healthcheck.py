from __future__ import annotations

import http.client
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


APP_HOST = os.getenv("BACKGROUND_STUDIO_APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("BACKGROUND_STUDIO_APP_PORT", "8000"))
HEALTH_PORT = int(os.getenv("PORT_HEALTH", "80"))
READY_WAIT_SECONDS = int(
    os.getenv("BACKGROUND_STUDIO_READY_WAIT_SECONDS", "300")
)
STARTUP_LOG_PATH = os.getenv(
    "BACKGROUND_STUDIO_STARTUP_LOG",
    "/workspace/background-studio-worker/startup.log",
)
MAX_REQUEST_BYTES = 12 * 1024 * 1024
MAX_STARTUP_LOG_BYTES = 8 * 1024


def app_is_ready() -> bool:
    connection = http.client.HTTPConnection(
        APP_HOST,
        APP_PORT,
        timeout=0.5,
    )
    try:
        connection.request("GET", "/ping")
        response = connection.getresponse()
        response.read()
        return response.status == 200
    except OSError:
        return False
    finally:
        connection.close()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/startup":
            self._startup_status()
            return
        if self.path not in {"/ping", "/ready"}:
            self.send_response(404)
            self.end_headers()
            return

        body = json.dumps(
            {"ok": True, "model_ready": app_is_ready()}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _startup_status(self) -> None:
        try:
            with open(STARTUP_LOG_PATH, "rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - MAX_STARTUP_LOG_BYTES))
                body = stream.read(MAX_STARTUP_LOG_BYTES)
        except OSError:
            body = b"startup log is not available"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/remove":
            self.send_response(404)
            self.end_headers()
            return

        content_length = self.headers.get("Content-Length")
        try:
            size = int(content_length or "")
        except ValueError:
            self._json_error(411, "Content-Length is required.")
            return
        if size < 1 or size > MAX_REQUEST_BYTES:
            self._json_error(413, "Request body is too large.")
            return
        body = self.rfile.read(size)

        deadline = time.monotonic() + READY_WAIT_SECONDS
        while not app_is_ready():
            if time.monotonic() >= deadline:
                self._json_error(503, "Worker is still starting.")
                return
            time.sleep(1)

        connection = http.client.HTTPConnection(
            APP_HOST,
            APP_PORT,
            timeout=READY_WAIT_SECONDS,
        )
        try:
            headers = {
                "Content-Type": self.headers.get(
                    "Content-Type",
                    "application/json",
                ),
                "Content-Length": str(len(body)),
            }
            worker_token = self.headers.get(
                "X-Background-Studio-Token"
            )
            if worker_token:
                headers["X-Background-Studio-Token"] = worker_token
            connection.request("POST", "/remove", body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read(MAX_REQUEST_BYTES + 1)
            if len(response_body) > MAX_REQUEST_BYTES:
                self._json_error(502, "Worker response is too large.")
                return
            self.send_response(response.status)
            self.send_header(
                "Content-Type",
                response.getheader(
                    "Content-Type",
                    "application/json",
                ),
            )
            self.send_header(
                "Content-Length",
                str(len(response_body)),
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(response_body)
        except OSError:
            self._json_error(502, "Worker connection failed.")
        finally:
            connection.close()

    def _json_error(self, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
