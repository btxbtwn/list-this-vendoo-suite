from __future__ import annotations

import http.client

from runpod import healthcheck


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def read(self) -> bytes:
        return b""


class FakeConnection:
    def __init__(self, status: int | None) -> None:
        self.status = status
        self.closed = False

    def request(self, method: str, path: str) -> None:
        assert method == "GET"
        assert path == "/ping"
        if self.status is None:
            raise ConnectionRefusedError

    def getresponse(self) -> FakeResponse:
        assert self.status is not None
        return FakeResponse(self.status)

    def close(self) -> None:
        self.closed = True


def test_app_is_ready_when_worker_ping_returns_200(monkeypatch) -> None:
    connection = FakeConnection(200)
    monkeypatch.setattr(
        http.client,
        "HTTPConnection",
        lambda *args, **kwargs: connection,
    )

    assert healthcheck.app_is_ready() is True
    assert connection.closed is True


def test_app_is_not_ready_before_worker_accepts_connections(
    monkeypatch,
) -> None:
    connection = FakeConnection(None)
    monkeypatch.setattr(
        http.client,
        "HTTPConnection",
        lambda *args, **kwargs: connection,
    )

    assert healthcheck.app_is_ready() is False
    assert connection.closed is True


def test_app_is_not_ready_for_non_200_response(monkeypatch) -> None:
    connection = FakeConnection(503)
    monkeypatch.setattr(
        http.client,
        "HTTPConnection",
        lambda *args, **kwargs: connection,
    )

    assert healthcheck.app_is_ready() is False
    assert connection.closed is True
