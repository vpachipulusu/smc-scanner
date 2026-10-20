"""GET /config, the optional internal key and the error envelope of the scanner API."""

import pytest
from fastapi.testclient import TestClient

from smc_scanner import __version__
from smc_scanner.api import INTERNAL_KEY_ENV, INTERNAL_KEY_HEADER, app

client = TestClient(app, base_url="http://localhost")


def test_health_reports_the_version() -> None:
    assert client.get("/health").json() == {"status": "ok", "version": __version__}


def test_config_lists_choices_defaults_limits_and_watchlist() -> None:
    response = client.get("/config")

    body = response.json()
    assert response.status_code == 200
    assert body["sources"] == ["mt5", "demo"]
    assert body["timeframes"] == ["5m", "15m", "30m", "1h", "4h", "1d"]
    assert body["defaults"] == {"source": "mt5", "tf": "1h", "bars": 500, "swing": 10, "near": 0.5}
    assert body["limits"]["min_bars"] == 15 and body["limits"]["max_symbols"] == 50
    assert "EURUSD" in body["watchlist"]["demo"]
    assert isinstance(body["watchlist"]["mt5"], list)


def test_internal_key_is_required_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(INTERNAL_KEY_ENV, "s3cret")

    assert client.get("/config").json() == {"success": False, "error": "Unauthorized"}
    assert client.get("/config", headers={INTERNAL_KEY_HEADER: "wrong"}).status_code == 401
    assert client.get("/config", headers={INTERNAL_KEY_HEADER: "s3cret"}).status_code == 200
    assert client.get("/scan", params={"source": "demo", "bars": 5}).status_code == 401

    monkeypatch.delenv(INTERNAL_KEY_ENV)
    assert client.get("/config").status_code == 200


def test_validation_errors_use_the_envelope() -> None:
    response = client.get("/scan", params={"source": "demo", "bars": 5})

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid request"}


def test_symbol_errors_are_curated_envelope_messages() -> None:
    response = client.get("/scan", params={"source": "demo", "symbols": "../x"})

    assert response.status_code == 422
    assert response.json() == {"success": False, "error": "Invalid symbol name: '../x'"}


def test_scan_rows_match_the_response_model() -> None:
    response = client.get("/scan", params={"source": "demo", "symbols": "EURUSD", "bars": 300})

    body = response.json()
    assert response.status_code == 200
    assert body["source"] == "demo" and body["tf"] == "1h"
    assert body["count"] == len(body["rows"]) >= 1
    assert set(body["rows"][0]) == {
        "instrument",
        "status",
        "zone",
        "zone_low",
        "zone_high",
        "price",
        "dist_atr",
        "bias",
        "in_ote",
        "trendline_ok",
        "ob_fvg",
        "score",
        "zone_age",
        "prior_touches",
        "bar_time",
    }
    assert body["failures"] == []
