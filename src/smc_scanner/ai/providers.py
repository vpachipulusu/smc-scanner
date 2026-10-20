"""One seam for LLM calls: a Claude implementation and a fake for tests.

Secrets: the API key is read from ANTHROPIC_API_KEY only. Neither the key nor the request text
is ever logged or placed in an error message; logs carry provider, model and token counts.

The `anthropic` SDK is an optional extra (`ai`); it is imported lazily so the fake provider
works without it.
"""

import logging
import math
import os
import random
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

if TYPE_CHECKING:
    import anthropic

log = logging.getLogger(__name__)

PROVIDER_ENV = "AI_PROVIDER"
MODEL_ENV = "AI_MODEL"
TIMEOUT_ENV = "AI_TIMEOUT_SECONDS"
RETRIES_ENV = "AI_MAX_RETRIES"
TEMPERATURE_ENV = "AI_TEMPERATURE"
API_KEY_ENV = "ANTHROPIC_API_KEY"
BASE_URL_ENV = "AI_BASE_URL"

DEFAULT_PROVIDER = "claude"
PROVIDER_NAMES = ("claude",)  # the fake is built directly by tests, never selected by name
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 5
DEFAULT_BASE_URL = "https://api.anthropic.com"
MODEL_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
# Headroom so adaptive thinking cannot starve the short JSON verdict of output tokens.
MAX_TOKENS = 8000
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
SERVER_ERROR_FLOOR = 500


class AiError(Exception):
    """Any failure of the AI layer. Messages never contain the API key or request text."""


@dataclass(frozen=True)
class AiReply:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class AiProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str | None: ...

    def complete(self, system: str, user: str) -> AiReply: ...


def _validated_timeout(value: float, source: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise AiError(f"{source} must be a positive, finite number, got {value!r}")
    return value


def _validated_retries(value: int, source: str) -> int:
    if not 0 <= value <= MAX_RETRIES_LIMIT:
        raise AiError(f"{source} must be between 0 and {MAX_RETRIES_LIMIT}, got {value!r}")
    return value


def _validated_model(value: str, source: str) -> str:
    if not MODEL_PATTERN.fullmatch(value):
        raise AiError(f"{source} must match [A-Za-z0-9._-]+, got {value!r}")
    return value


def _base_url() -> str:
    """The API endpoint: fixed unless AI_BASE_URL overrides it, and then only with https."""
    raw = os.environ.get(BASE_URL_ENV, "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AiError(f"{BASE_URL_ENV} must be an https URL")
    return raw


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise AiError(f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise AiError(f"{name} must be a finite number, got {raw!r}")
    return value


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise AiError(f"{name} must be a whole number, got {raw!r}") from None


def _require_sdk() -> None:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise AiError(
            "the claude provider needs the anthropic SDK; install it with: uv sync --extra ai"
        ) from None


def _is_retryable(exc: "anthropic.AnthropicError") -> bool:
    import anthropic

    if isinstance(exc, anthropic.APIConnectionError | anthropic.RateLimitError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code >= SERVER_ERROR_FLOOR


def _describe(exc: "anthropic.AnthropicError") -> str:
    """Class name and status only: SDK messages can echo request details."""
    import anthropic

    if isinstance(exc, anthropic.APIStatusError):
        return f"{type(exc).__name__} (HTTP {exc.status_code})"
    return type(exc).__name__


def _retry_after(exc: "anthropic.AnthropicError") -> float | None:
    """A usable Retry-After (seconds) from a 429, capped; None means use computed backoff."""
    import anthropic

    if not isinstance(exc, anthropic.RateLimitError):
        return None
    try:
        seconds = float(exc.response.headers.get("retry-after", ""))
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, BACKOFF_CAP_SECONDS)


class ClaudeProvider:
    """Claude via the official SDK; SDK retries are off, ours cover 429/5xx/network errors."""

    name = "claude"

    def __init__(
        self,
        client: "anthropic.Anthropic | None" = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        _require_sdk()
        if model:
            self.model = _validated_model(model, "model")
        else:
            self.model = _validated_model(
                os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL, MODEL_ENV
            )
        if timeout is not None:
            self.timeout = _validated_timeout(timeout, "timeout")
        else:
            env_timeout = _env_float(TIMEOUT_ENV)
            self.timeout = (
                DEFAULT_TIMEOUT_SECONDS
                if env_timeout is None
                else _validated_timeout(env_timeout, TIMEOUT_ENV)
            )
        if max_retries is not None:
            self.max_retries = _validated_retries(max_retries, "max_retries")
        else:
            env_retries = _env_int(RETRIES_ENV)
            self.max_retries = (
                DEFAULT_MAX_RETRIES
                if env_retries is None
                else _validated_retries(env_retries, RETRIES_ENV)
            )
        # Newer models (incl. the default) reject non-default sampling params, so opt-in only.
        self._temperature = _env_float(TEMPERATURE_ENV)
        self._sleep = sleep
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> "anthropic.Anthropic":
        import anthropic

        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise AiError(f"{API_KEY_ENV} is not set; it is required for the claude provider")
        # Explicit endpoint and no bearer token: the SDK would otherwise honour ANTHROPIC_BASE_URL
        # and ANTHROPIC_AUTH_TOKEN and could send the key and prompts to another host.
        return anthropic.Anthropic(
            api_key=api_key,
            auth_token=None,
            base_url=_base_url(),
            timeout=self.timeout,
            max_retries=0,
        )

    def complete(self, system: str, user: str) -> AiReply:
        message = self._create_with_retry(system, user)
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text:
            raise AiError(f"claude returned no text content (model {self.model})")
        reply = AiReply(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            model=message.model,
        )
        log.info(
            "ai provider=%s model=%r input_tokens=%d output_tokens=%d",
            self.name,
            reply.model,
            reply.input_tokens,
            reply.output_tokens,
        )
        return reply

    def _create_with_retry(self, system: str, user: str) -> "anthropic.types.Message":
        import anthropic

        temperature = anthropic.omit if self._temperature is None else self._temperature
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                return self._client.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    system=[
                        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                    ],
                    messages=[{"role": "user", "content": user}],
                    temperature=temperature,
                )
            except anthropic.AnthropicError as exc:
                reason = _describe(exc)
                if not _is_retryable(exc):
                    log.warning("ai provider=%s model=%r failed: %s", self.name, self.model, reason)
                    raise AiError(f"claude request failed: {reason}") from None
                if attempt == attempts - 1:
                    log.warning(
                        "ai provider=%s model=%r gave up: %s", self.name, self.model, reason
                    )
                    raise AiError(
                        f"claude request failed after {attempts} attempts: {reason}"
                    ) from None
                delay = _retry_after(exc)
                if delay is None:
                    delay = min(BACKOFF_BASE_SECONDS * 2**attempt, BACKOFF_CAP_SECONDS)
                    delay += random.uniform(0, delay / 4)  # noqa: S311 - jitter, not security
                log.info(
                    "ai provider=%s retry %d in %.1fs: %s", self.name, attempt + 1, delay, reason
                )
                self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover


class FakeProvider:
    """Replays canned replies in order and records each (system, user) call."""

    name = "fake"
    model = "fake"

    def __init__(self, replies: Iterable[AiReply | str] = ()) -> None:
        self._replies = [r if isinstance(r, AiReply) else AiReply(r, 0, 0, "fake") for r in replies]
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> AiReply:
        self.calls.append((system, user))
        if len(self.calls) > len(self._replies):
            raise AiError(f"fake provider exhausted after {len(self._replies)} replies")
        return self._replies[len(self.calls) - 1]


def make_provider(name: str | None = None) -> AiProvider:
    chosen = (name or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()
    if chosen == "claude":
        return ClaudeProvider()
    allowed = ", ".join(PROVIDER_NAMES)
    raise AiError(f"unknown AI provider {chosen!r}; allowed values: {allowed}")
