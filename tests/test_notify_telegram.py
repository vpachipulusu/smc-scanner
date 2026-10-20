"""Telegram notifier: formatting, escaping, truncation and failure handling (no real network)."""

import json
import logging
import re
import socket
from collections.abc import Callable
from typing import Any, NoReturn

import httpx
import pytest

from smc_scanner.ai.verdict import AiVerdict
from smc_scanner.notify import telegram
from smc_scanner.notify.telegram import (
    ADVISORY_LINE,
    MAX_MESSAGE_CHARS,
    SendResult,
    format_verdict_message,
    send_error_alert,
    send_message,
    send_test_message,
    truncate_html,
)

TOKEN = "123456789:AAH-secret_Token-xyz"
CHAT_ID = "-1001234567890"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("real network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def make_client(handler: Handler) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(recording)), seen


def ok_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def buy_verdict(**overrides: Any) -> AiVerdict:
    fields: dict[str, Any] = {
        "action": "BUY",
        "confidence": 72.0,
        "quality": "A",
        "entry": 1.1,
        "stop": 1.095,
        "targets": (1.11, 1.12),
        "risk_reward": 2.0,
        "invalidation": 1.09,
        "reasons": ("Fresh bullish OB", "HTF aligned"),
        "summary": "Price tapped the zone.",
    }
    return AiVerdict(**{**fields, **overrides})


def test_send_message_posts_html_to_bot_api() -> None:
    client, seen = make_client(ok_response)

    result = send_message(TOKEN, CHAT_ID, "<b>hi</b>", client=client)

    assert result == SendResult(ok=True, error=None)
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = json.loads(request.content)
    assert body["chat_id"] == CHAT_ID
    assert body["text"] == "<b>hi</b>"
    assert body["parse_mode"] == "HTML"
    assert body["link_preview_options"] == {"is_disabled": True}


def test_default_client_is_built_when_none_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    client, seen = make_client(ok_response)
    monkeypatch.setattr(telegram, "_new_client", lambda: client)

    assert send_message(TOKEN, CHAT_ID, "x").ok
    assert len(seen) == 1


def test_missing_credentials_fail_without_a_request() -> None:
    client, seen = make_client(ok_response)

    assert not send_message("", CHAT_ID, "x", client=client).ok
    assert not send_message(TOKEN, "  ", "x", client=client).ok
    assert seen == []


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"}),
            "400",
        ),
        (httpx.Response(401, json={"ok": False, "description": "Unauthorized"}), "401"),
        (httpx.Response(500, text="<html>boom</html>"), "500"),
        (httpx.Response(200, text="not json"), "unexpected"),
        (httpx.Response(200, json={"ok": False}), "unexpected"),
    ],
)
def test_http_failures_return_a_failed_result(response: httpx.Response, expected: str) -> None:
    client, seen = make_client(lambda _r: response)

    result = send_message(TOKEN, CHAT_ID, "x", client=client)

    assert not result.ok
    assert result.error is not None
    assert expected in result.error
    assert len(seen) == 1  # no retry outside 429


def test_error_description_is_cleaned_and_bounded() -> None:
    nasty = {"ok": False, "description": "bad\n" + "x" * 1000 + TOKEN}
    client, _ = make_client(lambda _r: httpx.Response(400, json=nasty))

    result = send_message(TOKEN, CHAT_ID, "x", client=client)

    assert result.error is not None
    assert len(result.error) <= telegram.MAX_ERROR_CHARS
    assert "\n" not in result.error
    assert TOKEN not in result.error


def test_429_retries_once_after_retry_after() -> None:
    responses = iter(
        [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 2}}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client, seen = make_client(lambda _r: next(responses))
    sleeps: list[float] = []

    result = send_message(TOKEN, CHAT_ID, "x", client=client, sleep=sleeps.append)

    assert result.ok
    assert len(seen) == 2
    assert sleeps == [2.0]


def test_429_wait_is_capped_and_retry_happens_once_only() -> None:
    client, seen = make_client(
        lambda _r: httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 3600}})
    )
    sleeps: list[float] = []

    result = send_message(TOKEN, CHAT_ID, "x", client=client, sleep=sleeps.append)

    assert not result.ok
    assert result.error is not None
    assert "429" in result.error
    assert len(seen) == 2
    assert sleeps == [telegram.MAX_RETRY_AFTER_SECONDS]


@pytest.mark.parametrize("body", [{"ok": False}, {"parameters": {"retry_after": "soon"}}, None])
def test_429_without_a_usable_retry_after_still_retries_once(body: object) -> None:
    response = httpx.Response(429, json=body) if body is not None else httpx.Response(429)
    client, seen = make_client(lambda _r: response)
    sleeps: list[float] = []

    result = send_message(TOKEN, CHAT_ID, "x", client=client, sleep=sleeps.append)

    assert not result.ok
    assert len(seen) == 2
    assert sleeps == [telegram.DEFAULT_RETRY_AFTER_SECONDS]


@pytest.mark.parametrize(
    ("make_error", "expected"),
    [
        (lambda r: httpx.ReadTimeout("read timed out", request=r), "timeout"),
        (lambda r: httpx.ConnectTimeout("connect timed out", request=r), "timeout"),
        (lambda r: httpx.ConnectError(f"cannot reach {r.url}", request=r), "network"),
        (lambda r: httpx.ReadError(f"reset {r.url}", request=r), "network"),
        (lambda r: RuntimeError(f"weird {r.url}"), "unexpected"),
    ],
)
def test_transport_errors_never_raise_or_leak_the_token(
    make_error: Callable[[httpx.Request], Exception],
    expected: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise make_error(request)

    client, seen = make_client(boom)
    caplog.set_level(logging.DEBUG)

    result = send_message(TOKEN, CHAT_ID, "secret body text", client=client)

    assert not result.ok
    assert result.error is not None
    assert expected in result.error
    assert len(seen) == 1
    assert TOKEN not in result.error
    assert TOKEN not in repr(result)
    assert TOKEN not in caplog.text
    assert "secret body text" not in caplog.text


def test_token_never_reaches_any_log_record(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    ok_client, _ = make_client(ok_response)
    bad_client, _ = make_client(lambda _r: httpx.Response(400, json={"ok": False}))

    send_message(TOKEN, CHAT_ID, "body-one", client=ok_client)
    send_message(TOKEN, CHAT_ID, "body-two", client=bad_client)
    send_test_message(TOKEN, CHAT_ID, client=ok_client)

    assert caplog.records, "expected the notifier to have logged the failure"
    for record in caplog.records:
        rendered = record.getMessage()
        assert TOKEN not in rendered
        assert TOKEN not in str(record.args)
        assert "body-one" not in rendered
        assert "body-two" not in rendered
        assert record.exc_info is None


def test_http_request_lines_are_silenced_even_with_a_caller_client(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger("httpx").setLevel(logging.INFO)  # as a host app might configure it
    client, _ = make_client(ok_response)
    caplog.set_level(logging.DEBUG)

    send_message(TOKEN, CHAT_ID, "x", client=client)

    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
    assert not [r for r in caplog.records if r.name.startswith(("httpx", "httpcore"))]


def test_redaction_filter_rewrites_url_tokens() -> None:
    record = logging.LogRecord(
        "httpx", logging.WARNING, __file__, 1, "POST %s", (f"https://x/bot{TOKEN}/send",), None
    )

    assert telegram._RedactTokenFilter().filter(record)  # noqa: SLF001
    assert TOKEN not in record.getMessage()
    assert "/bot<redacted>/send" in record.getMessage()


@pytest.mark.parametrize(
    "bad", ["abc", "123:", ":abc", "123:ab cd", "12/3:abc", "123:ab\n", "x" * 5]
)
def test_invalid_token_fails_without_request_or_echo(bad: str) -> None:
    client, seen = make_client(ok_response)

    result = send_message(bad, CHAT_ID, "x", client=client)

    assert result == SendResult(ok=False, error="invalid bot token")
    assert seen == []


def test_symbol_and_tf_are_cleaned_like_model_fields() -> None:
    text = format_verdict_message("EUR\nUSD‮", "M​15\r\n", buy_verdict())

    first = text.splitlines()[0]
    assert first == "<b>BUY</b> EUR USD M15"


def test_send_test_message_sends_a_marked_message() -> None:
    client, seen = make_client(ok_response)

    assert send_test_message(TOKEN, CHAT_ID, client=client).ok
    text = json.loads(seen[0].content)["text"]
    assert "test" in text.lower()
    assert ADVISORY_LINE in text


def test_send_error_alert_escapes_and_truncates() -> None:
    client, seen = make_client(ok_response)

    result = send_error_alert(TOKEN, CHAT_ID, "<script>x</script> & " + "z" * 10_000, client=client)

    assert result.ok
    text = json.loads(seen[0].content)["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text
    assert len(text) <= MAX_MESSAGE_CHARS


def test_format_contains_the_trade_facts_and_advisory_line() -> None:
    text = format_verdict_message("EURUSD", "M15", buy_verdict(), zone=(1.099, 1.101))

    for needle in ("EURUSD", "M15", "BUY", "72", "1.1", "1.095", "1.11", "1.12", "1.09"):
        assert needle in text
    assert "1.099" in text
    assert "Price tapped the zone." in text
    assert "Fresh bullish OB" in text
    assert text.endswith(ADVISORY_LINE)
    assert "no orders are placed" in ADVISORY_LINE


def test_format_hold_has_no_levels() -> None:
    hold = AiVerdict(action="HOLD", confidence=30.0, summary="Nothing to do.")

    text = format_verdict_message("XAUUSD", "H1", hold)

    assert "HOLD" in text
    assert "Entry" not in text
    assert "Stop" not in text


def test_format_marks_downgraded_verdicts() -> None:
    hold = AiVerdict(
        action="HOLD",
        confidence=0.0,
        summary="Downgraded",
        downgraded=True,
        downgrade_reason="reply is not valid JSON",
    )

    assert "reply is not valid JSON" in format_verdict_message("EURUSD", "M5", hold)


def test_format_escapes_every_dynamic_value() -> None:
    evil = "<script>alert(1)</script>"
    verdict = buy_verdict(summary=f"{evil} & [x](http://evil.example)", reasons=(evil, "a<b"))

    text = format_verdict_message(evil, "<i>M1</i>", verdict, link="https://ok.example/?a=1&b=<2>")

    assert "<script>" not in text
    assert "<i>M1</i>" not in text
    assert "&lt;script&gt;" in text
    assert "a&lt;b" in text
    assert "&amp;b=&lt;2&gt;" in text
    tags = set(re.findall(r"</?([a-z]+)", text))
    assert tags <= {"b", "code", "a"}


def test_model_text_is_never_a_live_link() -> None:
    verdict = buy_verdict(summary="see https://evil.example and [x](http://evil.example)")

    text = format_verdict_message("EURUSD", "M15", verdict)

    assert "<a " not in text
    # model text sits inside <code>, which Telegram never auto-links
    assert re.search(r"<code>[^<]*evil\.example[^<]*</code>", text)


def test_only_http_links_are_rendered() -> None:
    good = format_verdict_message("EURUSD", "M15", buy_verdict(), link="https://x.example/c")
    assert '<a href="https://x.example/c">' in good
    for bad in ("javascript:alert(1)", "tg://resolve?domain=x", "ftp://x", ""):
        assert "<a " not in format_verdict_message("EURUSD", "M15", buy_verdict(), link=bad)


def test_oversize_message_is_truncated_safely() -> None:
    verdict = buy_verdict(summary="<" * 600, reasons=("<&>" * 66,) * 8)

    text = format_verdict_message("<" * 50, "M15", verdict)

    assert len(text) <= MAX_MESSAGE_CHARS
    assert text.endswith(ADVISORY_LINE)
    assert not re.search(r"&(?!(?:amp|lt|gt|quot|#\d+);)", text)
    assert text.count("<code>") == text.count("</code>")
    assert text.count("<b>") == text.count("</b>")


def test_truncate_html_short_text_is_unchanged() -> None:
    assert truncate_html("<b>a</b>", 50) == "<b>a</b>"


def test_truncate_html_never_cuts_inside_an_entity_or_tag() -> None:
    for pad in range(0, 8):
        text = "a" * (95 + pad) + "&amp;&lt;<code>" + "b" * 50
        out = truncate_html(text, 100)
        assert len(out) <= 100
        assert not re.search(r"&[^;\s]{0,5}$", out)
        assert not re.search(r"<[^>]*$", out)
        assert out.count("<code>") == out.count("</code>")


def test_truncate_html_closes_open_tags() -> None:
    out = truncate_html("<b>" + "x" * 200, 50)

    assert out.endswith("</b>")
    assert len(out) <= 50


def test_send_message_truncates_oversize_text() -> None:
    client, seen = make_client(ok_response)

    send_message(TOKEN, CHAT_ID, "&amp;" * 3000, client=client)

    text = json.loads(seen[0].content)["text"]
    assert len(text) <= MAX_MESSAGE_CHARS
    assert text.endswith("…")
    assert not re.search(r"&[^;\s]{0,4}…$", text)


@pytest.mark.parametrize("token", ["", "   ", "	"])
def test_blank_token_gives_the_exact_error_on_every_sender(token: str) -> None:
    client, seen = make_client(ok_response)
    expected = SendResult(ok=False, error="missing bot token or chat id")

    assert send_message(token, CHAT_ID, "x", client=client) == expected
    assert send_test_message(token, CHAT_ID, client=client) == expected
    assert send_error_alert(token, CHAT_ID, "boom", client=client) == expected
    assert seen == []


def test_fail_does_not_garble_text_for_a_blank_token() -> None:
    assert telegram._fail("  ", "keep me intact").error == "keep me intact"  # noqa: SLF001


def test_redaction_filter_survives_a_malformed_record() -> None:
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "%s %s", ("only-one",), None)

    assert telegram._RedactTokenFilter().filter(record)  # noqa: SLF001


def test_redaction_filter_is_installed_once_and_only_on_send() -> None:
    client, _ = make_client(ok_response)
    for _ in range(2):
        send_message(TOKEN, CHAT_ID, "x", client=client)

    filters = [
        f for f in logging.getLogger("httpx").filters if isinstance(f, telegram._RedactTokenFilter)
    ]  # noqa: SLF001
    assert len(filters) == 1


def test_default_client_applies_the_request_timeout() -> None:
    client = telegram._new_client()  # noqa: SLF001
    try:
        assert client.timeout == httpx.Timeout(telegram.REQUEST_TIMEOUT_SECONDS)
    finally:
        client.close()


def test_429_followed_by_a_transport_error_fails_cleanly() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"parameters": {"retry_after": 1}})
        raise httpx.ConnectError(f"down {request.url}", request=request)

    client, seen = make_client(handler)

    result = send_message(TOKEN, CHAT_ID, "x", client=client, sleep=lambda _s: None)

    assert not result.ok
    assert result.error is not None
    assert "network" in result.error
    assert TOKEN not in result.error
    assert len(seen) == 2


def test_link_with_a_quote_cannot_break_out_of_the_attribute() -> None:
    text = format_verdict_message(
        "EURUSD", "M15", buy_verdict(), link='https://x.example/?a="onclick="evil'
    )

    anchor = re.search(r"<a href=\"([^\"]*)\">", text)
    assert anchor is not None
    assert "&quot;" in anchor.group(1)
    assert 'onclick="' not in text


def test_oversize_message_keeps_the_link_and_advisory_line() -> None:
    verdict = buy_verdict(summary="<" * 600, reasons=("<&>" * 66,) * 8)

    text = format_verdict_message("<" * 50, "M15", verdict, link="https://x.example/c")

    assert len(text) <= MAX_MESSAGE_CHARS
    assert '<a href="https://x.example/c">Open chart</a>' in text
    assert text.endswith(ADVISORY_LINE)
    assert text.count("<code>") == text.count("</code>")


def test_truncate_html_inside_an_anchor_tag_leaves_no_partial_tag() -> None:
    text = "x" * 60 + '<a href="https://x.example/very/long/path">link</a>' + "y" * 50

    for limit in range(60, 100):
        out = truncate_html(text, limit)
        assert len(out) <= limit
        assert not re.search(r"<[^>]*$", out)
        assert out.count("<a ") == out.count("</a>")


def test_truncate_html_closes_nested_tags_in_order() -> None:
    out = truncate_html("<b><i>" + "x" * 200, 60)

    assert out.endswith("…</i></b>")
    assert len(out) <= 60
