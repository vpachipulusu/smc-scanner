"""AI provider seam: selection, Claude retry behaviour and the fake. No network, ever."""

import socket
import sys
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx
import pytest

from smc_scanner.ai.providers import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    AiError,
    AiProvider,
    AiReply,
    ClaudeProvider,
    FakeProvider,
    make_provider,
)

SECRET_KEY = "sk-ant-test-SECRET-1234567890"
SECRET_PROMPT = "PRIVATE-PROMPT-TEXT"
_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted in a unit test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AI_PROVIDER",
        "AI_MODEL",
        "AI_TIMEOUT_SECONDS",
        "AI_MAX_RETRIES",
        "AI_TEMPERATURE",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _message(text: str = "ok", input_tokens: int = 11, output_tokens: int = 7) -> Any:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        model="claude-sonnet-5-5",
    )


def _status_error(status: int, retry_after: str | None = None) -> anthropic.APIStatusError:
    headers = {} if retry_after is None else {"retry-after": retry_after}
    response = httpx.Response(status, headers=headers, request=_REQUEST)
    cls: Callable[..., anthropic.APIStatusError] = (
        anthropic.RateLimitError if status == 429 else anthropic.APIStatusError
    )
    return cls("boom " + SECRET_KEY, response=response, body=None)


def _factory(status: int) -> Callable[[], Exception]:
    return lambda: _status_error(status)


class FakeClient:
    """Stands in for anthropic.Anthropic: replays outcomes (replies or exceptions) in order."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider(
    outcomes: list[Any], sleeps: list[float] | None = None, **kwargs: Any
) -> tuple[ClaudeProvider, FakeClient]:
    client = FakeClient(outcomes)
    provider = ClaudeProvider(
        client=cast(anthropic.Anthropic, client),
        sleep=(sleeps if sleeps is not None else []).append,
        **kwargs,
    )
    return provider, client


# --- selection -------------------------------------------------------------------------


def test_make_provider_defaults_to_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    assert isinstance(make_provider(), ClaudeProvider)


def test_make_provider_reads_ai_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv("AI_PROVIDER", "claude")
    assert isinstance(make_provider(), ClaudeProvider)


def test_make_provider_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    assert isinstance(make_provider(" CLAUDE "), ClaudeProvider)


@pytest.mark.parametrize("name", ["openai", "fake"])
def test_unknown_or_fake_provider_is_not_selectable(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    with pytest.raises(AiError) as by_arg:
        make_provider(name)
    monkeypatch.setenv("AI_PROVIDER", name)
    with pytest.raises(AiError) as by_env:
        make_provider()
    for err in (by_arg, by_env):
        assert "allowed values: claude" in str(err.value)
        assert name in str(err.value)


def test_missing_key_fails_fast_naming_variable() -> None:
    with pytest.raises(AiError, match="ANTHROPIC_API_KEY"):
        make_provider("claude")


def test_blank_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    with pytest.raises(AiError, match="ANTHROPIC_API_KEY"):
        ClaudeProvider()


def test_env_configures_model_timeout_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv("AI_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AI_MAX_RETRIES", "4")
    provider = ClaudeProvider()
    assert provider.model == "claude-haiku-5-5"
    assert provider.timeout == 12.5
    assert provider.max_retries == 4


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    provider = ClaudeProvider()
    assert provider.model == "claude-sonnet-5-5"
    assert provider.timeout == 60.0
    assert provider.max_retries == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AI_TIMEOUT_SECONDS", "soon"),
        ("AI_TIMEOUT_SECONDS", "0"),
        ("AI_TIMEOUT_SECONDS", "-3"),
        ("AI_TIMEOUT_SECONDS", "nan"),
        ("AI_TIMEOUT_SECONDS", "inf"),
        ("AI_MAX_RETRIES", "many"),
        ("AI_MAX_RETRIES", "-1"),
        ("AI_MAX_RETRIES", "6"),
        ("AI_BASE_URL", "http://api.anthropic.com"),
        ("AI_BASE_URL", "https://"),
        ("AI_BASE_URL", "evil.example.com"),
        ("AI_MODEL", "claude sonnet"),
        ("AI_MODEL", "x/../y"),
        ("AI_MODEL", "m\nX-Injected: 1"),
        ("AI_TEMPERATURE", "warm"),
        ("AI_TEMPERATURE", "nan"),
    ],
)
def test_bad_numeric_env_raises_naming_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv(name, value)
    with pytest.raises(AiError, match=name):
        ClaudeProvider()


def test_blank_model_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv("AI_MODEL", "   ")
    assert ClaudeProvider().model == "claude-sonnet-5-5"


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_constructor_rejects_bad_timeout(timeout: float) -> None:
    with pytest.raises(AiError, match="timeout"):
        ClaudeProvider(client=cast(anthropic.Anthropic, FakeClient([])), timeout=timeout)


@pytest.mark.parametrize("retries", [-1, 6])
def test_constructor_rejects_out_of_range_retries(retries: int) -> None:
    with pytest.raises(AiError, match="max_retries"):
        ClaudeProvider(client=cast(anthropic.Anthropic, FakeClient([])), max_retries=retries)


def test_constructor_rejects_bad_model() -> None:
    with pytest.raises(AiError, match="model"):
        ClaudeProvider(client=cast(anthropic.Anthropic, FakeClient([])), model="a b")


def _capture_client_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def stub(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return FakeClient([])

    monkeypatch.setattr(anthropic, "Anthropic", stub)
    return captured


def test_build_client_pins_endpoint_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_client_kwargs(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", f"  {SECRET_KEY}  ")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stolen")
    ClaudeProvider()
    assert captured == {
        "api_key": SECRET_KEY,
        "auth_token": None,
        "base_url": "https://api.anthropic.com",
        "timeout": 12.0,
        "max_retries": 0,
    }


def test_ai_base_url_override_allowed_over_https(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_client_kwargs(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv("AI_BASE_URL", "https://gateway.example.com/anthropic")
    ClaudeProvider()
    assert captured["base_url"] == "https://gateway.example.com/anthropic"


def test_real_sdk_client_ignores_ambient_endpoint_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stolen")
    provider = ClaudeProvider()
    sdk = provider._client  # noqa: SLF001
    assert str(sdk.base_url).startswith("https://api.anthropic.com")
    assert sdk.auth_token is None


def test_fake_provider_works_without_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` fail
    fake = FakeProvider()
    with pytest.raises(AiError, match="exhausted"):
        fake.complete("s", "u")


def test_claude_without_the_sdk_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    with pytest.raises(AiError, match="--extra ai"):
        make_provider("claude")


# --- Claude request / response ----------------------------------------------------------


def test_complete_maps_text_and_token_counts() -> None:
    provider, _ = _provider([_message("verdict", 123, 45)])
    reply = provider.complete("sys", "user")
    assert reply == AiReply(
        text="verdict", input_tokens=123, output_tokens=45, model="claude-sonnet-5-5"
    )


def test_request_shape_caches_system_block() -> None:
    provider, client = _provider([_message()])
    provider.complete("SYSTEM", "USER")
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["system"] == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    assert call["messages"] == [{"role": "user", "content": "USER"}]
    assert call["max_tokens"] >= 1024
    assert call["temperature"] is anthropic.omit


def test_temperature_sent_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_TEMPERATURE", "0.2")
    provider, client = _provider([_message()])
    provider.complete("s", "u")
    assert client.calls[0]["temperature"] == 0.2


def test_reply_without_text_block_raises() -> None:
    empty = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model="m",
    )
    provider, _ = _provider([empty])
    with pytest.raises(AiError, match="no text"):
        provider.complete("s", "u")


# --- retries ----------------------------------------------------------------------------


@pytest.mark.parametrize("make_failure", [_factory(429), _factory(503), _factory(529)])
def test_retries_then_succeeds(make_failure: Callable[[], Exception]) -> None:
    sleeps: list[float] = []
    provider, client = _provider([make_failure(), _message("fine")], sleeps)
    assert provider.complete("s", "u").text == "fine"
    assert len(client.calls) == 2
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_retries_on_connection_and_timeout_errors() -> None:
    errors = [
        anthropic.APIConnectionError(request=_REQUEST),
        anthropic.APITimeoutError(request=_REQUEST),
    ]
    sleeps: list[float] = []
    provider, client = _provider([*errors, _message("fine")], sleeps)
    assert provider.complete("s", "u").text == "fine"
    assert len(client.calls) == 3


def test_backoff_grows() -> None:
    sleeps: list[float] = []
    failures = [_status_error(429) for _ in range(3)]
    provider, _ = _provider([*failures, _message()], sleeps, max_retries=3)
    provider.complete("s", "u")
    assert sleeps == sorted(sleeps)
    assert sleeps[2] > sleeps[0]


def test_retry_after_header_is_honoured() -> None:
    sleeps: list[float] = []
    provider, _ = _provider([_status_error(429, retry_after="7"), _message()], sleeps)
    provider.complete("s", "u")
    assert sleeps == [7.0]


def test_retry_after_is_capped() -> None:
    sleeps: list[float] = []
    provider, _ = _provider([_status_error(429, retry_after="86400"), _message()], sleeps)
    provider.complete("s", "u")
    assert sleeps == [BACKOFF_CAP_SECONDS]


@pytest.mark.parametrize("header", ["soon", "-5", "nan", "inf", ""])
def test_unusable_retry_after_falls_back_to_backoff(header: str) -> None:
    sleeps: list[float] = []
    provider, _ = _provider([_status_error(429, retry_after=header), _message()], sleeps)
    provider.complete("s", "u")
    assert len(sleeps) == 1
    assert BACKOFF_BASE_SECONDS <= sleeps[0] <= BACKOFF_BASE_SECONDS * 1.25


def test_retry_exhaustion_raises_ai_error() -> None:
    sleeps: list[float] = []
    failures = [_status_error(500) for _ in range(3)]
    provider, client = _provider(failures, sleeps, max_retries=2)
    with pytest.raises(AiError, match="500"):
        provider.complete("s", "u")
    assert len(client.calls) == 3
    assert len(sleeps) == 2


def test_zero_retries_means_single_attempt() -> None:
    provider, client = _provider([_status_error(429)], max_retries=0)
    with pytest.raises(AiError):
        provider.complete("s", "u")
    assert len(client.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_non_retryable_4xx_raises_immediately(status: int) -> None:
    sleeps: list[float] = []
    provider, client = _provider([_status_error(status), _message()], sleeps)
    with pytest.raises(AiError, match=str(status)):
        provider.complete("s", "u")
    assert len(client.calls) == 1
    assert sleeps == []


# --- secrets ----------------------------------------------------------------------------


def test_error_text_contains_no_key_or_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    for make_failure in (_factory(401), _factory(500)):
        provider, _ = _provider([make_failure() for _ in range(3)])
        with pytest.raises(AiError) as err:
            provider.complete("s", SECRET_PROMPT)
        text = str(err.value)
        assert SECRET_KEY not in text
        assert SECRET_PROMPT not in text
        assert err.value.__cause__ is None


def test_logs_hold_no_key_or_prompt(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    provider, _ = _provider([_status_error(429), _message()])
    provider.complete("SYSTEM-TEXT", SECRET_PROMPT)
    logged = caplog.text
    assert SECRET_PROMPT not in logged
    assert "SYSTEM-TEXT" not in logged
    assert SECRET_KEY not in logged
    assert "claude" in logged
    assert "model='claude-sonnet-5-5'" in logged
    assert "input_tokens=11" in logged
    assert "output_tokens=7" in logged


# --- fake -------------------------------------------------------------------------------


def test_fake_replays_in_order_and_records_calls() -> None:
    first = AiReply("one", 1, 2, "fake")
    second = AiReply("two", 3, 4, "fake")
    fake = FakeProvider([first, second])
    assert fake.complete("s1", "u1") == first
    assert fake.complete("s2", "u2") == second
    assert fake.calls == [("s1", "u1"), ("s2", "u2")]


def test_fake_accepts_plain_strings() -> None:
    reply = FakeProvider(["hello"]).complete("s", "u")
    assert reply.text == "hello"
    assert reply.model == "fake"


def test_fake_exhaustion_raises_ai_error() -> None:
    fake = FakeProvider(["only"])
    fake.complete("s", "u")
    with pytest.raises(AiError, match="exhausted"):
        fake.complete("s", "u")


def test_fake_without_replies_is_exhausted() -> None:
    with pytest.raises(AiError):
        FakeProvider().complete("s", "u")


def test_providers_satisfy_protocol() -> None:
    providers: list[AiProvider] = [FakeProvider(), _provider([])[0]]
    assert len(providers) == 2
