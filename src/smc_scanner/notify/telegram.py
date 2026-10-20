"""Telegram Bot API notifier: plain httpx call to sendMessage with parse_mode HTML.

The bot token and chat id are ARGUMENTS; nothing here reads the environment. A Telegram failure
or timeout never raises: every send function returns a `SendResult`.

Secrets and privacy: the token lives in the request URL, so it is never placed in a log record,
exception text, repr or result string (the httpx request logger is filtered to redact it, and only
exception class names are reported). Message bodies are never logged.

Escaping: every dynamic value is `html.escape`d. Model-supplied text (summary, reasons) is shown
inside <code>, which Telegram does not auto-link or parse for mentions, so a model can never make
a clickable link. The only anchor is the caller-supplied `link`, restricted to http(s).
"""

import html
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from smc_scanner.ai.verdict import AiVerdict, clean_text

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RETRY_AFTER_SECONDS = 5.0
DEFAULT_RETRY_AFTER_SECONDS = 1.0
MAX_ERROR_CHARS = 200
ELLIPSIS = "…"
ADVISORY_LINE = "Advisory only - no orders are placed."

_TOO_MANY_REQUESTS = 429
_TOKEN_SHAPE = re.compile(r"\d+:[A-Za-z0-9_-]+")
_TOKEN_IN_URL = re.compile(r"/bot[^/\s\"']+")
_TAG = re.compile(r"<(/?)(b|i|u|s|code|pre|a)\b[^>]*>")
_TRAILING_ENTITY = re.compile(r"&[#\w]{0,10}$")
_TRAILING_TAG = re.compile(r"<[^>]*$")


@dataclass(frozen=True)
class SendResult:
    """Outcome of a send. `error` is a short, token-free description when `ok` is False."""

    ok: bool
    error: str | None = None


class _RedactTokenFilter(logging.Filter):
    """Rewrite `/bot<token>/` in httpx's own request log line, which carries the full URL."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed record (bad args): never let logging take the caller down
            return True
        if "/bot" in message:
            record.msg = _TOKEN_IN_URL.sub("/bot<redacted>", message)
            record.args = None
        return True


def _quiet_http_loggers() -> None:
    """Keep httpx/httpcore from logging request URLs (token included) at INFO/DEBUG.

    Called whenever this module sends, so it also covers a caller-provided client. Besides
    raising the levels it installs the redaction filter (once) as a backstop for WARNING+ lines.
    The guarantee holds for sends made through this module; it cannot cover other code that
    reconfigures these loggers afterwards.
    """
    httpx_logger = logging.getLogger("httpx")
    if not any(isinstance(f, _RedactTokenFilter) for f in httpx_logger.filters):
        httpx_logger.addFilter(_RedactTokenFilter())
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _new_client() -> httpx.Client:
    _quiet_http_loggers()
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)


def _fail(token: str, reason: str) -> SendResult:
    text = clean_text(reason)
    if token.strip():
        text = text.replace(token, "<redacted>")
    safe = _TOKEN_IN_URL.sub("/bot<redacted>", text)
    safe = safe[:MAX_ERROR_CHARS]
    log.warning("telegram send failed: %s", safe)
    return SendResult(ok=False, error=safe)


def truncate_html(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    """Cut `text` to `limit` chars without leaving a partial entity, partial tag or open tag."""
    if len(text) <= limit:
        return text
    cut = limit - 1
    while cut > 0:
        head = _TRAILING_TAG.sub("", _TRAILING_ENTITY.sub("", text[:cut]))
        stack: list[str] = []
        for closing, name in _TAG.findall(head):
            if not closing:
                stack.append(name)
            elif stack and stack[-1] == name:
                stack.pop()
        candidate = head + ELLIPSIS + "".join(f"</{name}>" for name in reversed(stack))
        if len(candidate) <= limit:
            return candidate
        cut -= len(candidate) - limit
    return ELLIPSIS


def _retry_after(response: httpx.Response) -> float:
    try:
        value = response.json()["parameters"]["retry_after"]
    except (ValueError, KeyError, TypeError):
        return DEFAULT_RETRY_AFTER_SECONDS
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return DEFAULT_RETRY_AFTER_SECONDS
    return float(min(value, MAX_RETRY_AFTER_SECONDS))


def _describe_failure(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
        description = payload.get("description", "") if isinstance(payload, dict) else ""
    except ValueError:
        description = ""
    detail = f": {description}" if isinstance(description, str) and description else ""
    return f"HTTP {response.status_code}{detail}"


def _attempt(
    client: httpx.Client, token: str, payload: dict[str, object], sleep: Callable[[float], None]
) -> SendResult:
    url = f"{API_BASE}/bot{token}/sendMessage"
    response = client.post(url, json=payload)
    if response.status_code == _TOO_MANY_REQUESTS:
        sleep(_retry_after(response))
        response = client.post(url, json=payload)
    if response.status_code == httpx.codes.OK:
        try:
            if response.json().get("ok") is True:
                return SendResult(ok=True)
        except (ValueError, AttributeError):
            pass
        return _fail(token, "unexpected response from Telegram")
    return _fail(token, _describe_failure(response))


def send_message(
    token: str,
    chat_id: str | int,
    text: str,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SendResult:
    """Send `text` as a Telegram HTML message. Never raises.

    `text` is sent as-is (parse_mode HTML): the caller MUST already have escaped every dynamic
    value (use `format_verdict_message`, or `html.escape`). Only length is enforced here.
    """
    if not token.strip() or not str(chat_id).strip():
        return _fail("", "missing bot token or chat id")
    if not _TOKEN_SHAPE.fullmatch(token):
        return _fail("", "invalid bot token")
    _quiet_http_loggers()
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": truncate_html(text),
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    owned = client is None
    http = _new_client() if client is None else client
    try:
        return _attempt(http, token, payload, sleep)
    except httpx.TimeoutException:
        return _fail(token, "timeout talking to Telegram")
    except httpx.TransportError as exc:
        return _fail(token, f"network error ({type(exc).__name__})")
    except Exception as exc:  # a notifier must never take the caller down
        return _fail(token, f"unexpected error ({type(exc).__name__})")
    finally:
        if owned:
            http.close()


def _price(value: float) -> str:
    return html.escape(f"{value:.5f}".rstrip("0").rstrip("."), quote=False)


def _esc(value: str) -> str:
    return html.escape(clean_text(value), quote=False)


def _safe_link(link: str | None) -> str | None:
    if not link:
        return None
    parsed = urlparse(link)
    return link if parsed.scheme in ("http", "https") and parsed.netloc else None


def _verdict_lines(verdict: AiVerdict, zone: tuple[float, float] | None) -> list[str]:
    lines: list[str] = []
    if zone is not None:
        lines.append(f"Zone: {_price(zone[0])} - {_price(zone[1])}")
    if verdict.entry is not None and verdict.stop is not None:
        levels = f"Entry: {_price(verdict.entry)} | Stop: {_price(verdict.stop)}"
        if verdict.risk_reward is not None:
            levels += f" | R:R {verdict.risk_reward:.1f}"
        lines.append(levels)
    if verdict.targets:
        lines.append("Targets: " + ", ".join(_price(t) for t in verdict.targets))
    if verdict.invalidation is not None:
        lines.append(f"Invalidation: {_price(verdict.invalidation)}")
    if verdict.downgrade_reason:
        lines.append(f"Downgraded: <code>{_esc(verdict.downgrade_reason)}</code>")
    if verdict.summary:
        lines.append(f"<code>{_esc(verdict.summary)}</code>")
    lines.extend(f"- <code>{_esc(reason)}</code>" for reason in verdict.reasons)
    return lines


def format_verdict_message(
    symbol: str,
    tf: str,
    verdict: AiVerdict,
    link: str | None = None,
    *,
    zone: tuple[float, float] | None = None,
) -> str:
    """Render a verdict as Telegram HTML, at most 4096 chars, advisory line always last."""
    quality = f" | Quality {_esc(verdict.quality)}" if verdict.quality else ""
    lines = [
        f"<b>{_esc(verdict.action)}</b> {_esc(symbol)} {_esc(tf)}",
        f"Confidence: {verdict.confidence:.0f}%{quality}",
        *_verdict_lines(verdict, zone),
    ]
    safe = _safe_link(link)
    tail = "\n" + ADVISORY_LINE
    if safe is not None:  # kept whole: only the summary/reasons above are ever truncated
        tail = f'\n<a href="{html.escape(safe, quote=True)}">Open chart</a>' + tail
    return truncate_html("\n".join(lines), MAX_MESSAGE_CHARS - len(tail)) + tail


def send_test_message(
    token: str,
    chat_id: str | int,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SendResult:
    """Send a fixed test message so the user can confirm the bot and chat are wired up."""
    text = f"<b>SMC Scanner test</b>\nTelegram alerts are working.\n{ADVISORY_LINE}"
    return send_message(token, chat_id, text, client=client, sleep=sleep)


def send_error_alert(
    token: str,
    chat_id: str | int,
    summary: str,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SendResult:
    """Alert that something failed; `summary` is escaped and length-bounded here."""
    footer = "\n" + ADVISORY_LINE
    body = truncate_html(
        f"<b>SMC Scanner error</b>\n<code>{_esc(clean_text(summary))}</code>",
        MAX_MESSAGE_CHARS - len(footer),
    )
    return send_message(token, chat_id, body + footer, client=client, sleep=sleep)
