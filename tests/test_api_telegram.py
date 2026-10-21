"""POST /telegram/test: sends a fixed message with the env token and never echoes it."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smc_scanner import api
from smc_scanner.api import app
from smc_scanner.api import deps as deps_module
from smc_scanner.api.routes import schedules as schedules_routes
from smc_scanner.notify.telegram import SendResult

client = TestClient(app, base_url="http://localhost")
TOKEN = "123456:ABC-def_ghi"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    monkeypatch.setattr(schedules_routes, "_telegram_test_at", -1000.0)
    yield
    app.dependency_overrides.clear()


def _sender(result: SendResult) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def send(token: str, chat_id: str) -> SendResult:
        calls.append((token, chat_id))
        return result

    app.dependency_overrides[api.get_telegram_sender] = lambda: send
    return calls


def test_sends_to_the_default_chat() -> None:
    calls = _sender(SendResult(ok=True))

    response = client.post("/telegram/test")

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert calls == [(TOKEN, "42")]
    assert TOKEN not in response.text


def test_a_body_chat_id_overrides_the_default() -> None:
    calls = _sender(SendResult(ok=True))

    assert client.post("/telegram/test", json={"chat_id": "@my_channel"}).status_code == 200
    assert calls == [(TOKEN, "@my_channel")]


@pytest.mark.parametrize("chat", ["nope", "", "12\n", 5, "@ab"])
def test_a_bad_chat_id_is_422(chat: Any) -> None:
    calls = _sender(SendResult(ok=True))

    response = client.post("/telegram/test", json={"chat_id": chat})

    assert response.status_code == 422
    assert calls == []


def test_unknown_body_fields_are_422() -> None:
    assert client.post("/telegram/test", json={"token": "x"}).status_code == 422


def test_missing_token_is_503_and_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    calls = _sender(SendResult(ok=True))

    response = client.post("/telegram/test")

    assert response.status_code == 503
    assert "TELEGRAM_BOT_TOKEN" in response.json()["error"]
    assert calls == []


def test_missing_chat_id_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    calls = _sender(SendResult(ok=True))

    response = client.post("/telegram/test")

    assert response.status_code == 422
    assert calls == []


def test_a_failed_send_is_502_with_a_fixed_message() -> None:
    _sender(SendResult(ok=False, error=f"HTTP 400: chat not found {TOKEN}"))

    response = client.post("/telegram/test")

    assert response.status_code == 502
    assert response.json() == {"success": False, "error": "Telegram rejected the test message"}
    assert TOKEN not in response.text


def test_a_raising_sender_is_a_502_without_the_token(caplog: pytest.LogCaptureFixture) -> None:
    def send(token: str, chat_id: str) -> SendResult:
        raise RuntimeError(f"boom {token}")

    app.dependency_overrides[api.get_telegram_sender] = lambda: send

    response = client.post("/telegram/test")

    assert response.status_code == 502
    assert TOKEN not in response.text
    assert TOKEN not in caplog.text


def test_the_default_sender_is_the_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake(token: str, chat_id: str | int) -> SendResult:
        seen.append((token, str(chat_id)))
        return SendResult(ok=True)

    monkeypatch.setattr(deps_module, "send_test_message", fake)

    assert client.post("/telegram/test").status_code == 200
    assert seen == [(TOKEN, "42")]


def test_a_second_test_message_within_the_cooldown_is_429() -> None:
    calls = _sender(SendResult(ok=True))

    first = client.post("/telegram/test")
    second = client.post("/telegram/test")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["success"] is False
    assert len(calls) == 1
