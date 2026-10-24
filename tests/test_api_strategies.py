"""Strategy CRUD (/strategies), the /config catalogue and the ``strategy`` choice on /scan."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smc_scanner.ai.store import StoreError
from smc_scanner.api import app
from smc_scanner.api import deps as deps_module
from smc_scanner.api.constants import SLUG_REGEX
from smc_scanner.config import DEFAULT_TIMEFRAME
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.ratelimit import RateLimiter
from smc_scanner.scanner import ScanOptions, run_scan
from smc_scanner.strategy import SLUG_PATTERN, Strategy
from smc_scanner.strategy import store as store_module
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES, PRESETS
from smc_scanner.strategy.conditions import conditions
from smc_scanner.strategy.service import StrategyService

client = TestClient(app, base_url="http://localhost")

PAYLOAD: dict[str, Any] = {
    "slug": "my-ob",
    "name": "My OB",
    "description": "Order blocks with the trend",
    "zone_kinds": ["OB"],
    "swing_length": 10,
    "near_atr": 0.5,
    "require": [{"key": "aligned"}],
    "score": [{"key": "in_ote"}, {"key": "max_zone_age", "params": {"bars": 50}}],
    "min_score": 0,
    "statuses": ["TOUCHING", "NEAR"],
}
SYMBOLS = "EURUSD,XAUUSD,USDJPY"
SCAN: dict[str, Any] = {"source": "demo", "symbols": SYMBOLS, "bars": 300}
NEW_ROW_FIELDS = {"strategy", "conditions"}


@pytest.fixture(autouse=True)
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "smc.db"
    monkeypatch.setenv("SMC_DB_PATH", str(path))
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    yield path
    app.dependency_overrides.clear()


def _create(**changes: Any) -> dict[str, Any]:
    response = client.post("/strategies", json={**PAYLOAD, **changes})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


class _BrokenRepository:
    def _fail(self, *_: object) -> Any:
        raise StoreError("strategy database C:/secret/smc.db: disk I/O error")

    list = get = create = update = delete = _fail


def _broken_service() -> StrategyService:
    return StrategyService(_BrokenRepository(), BUILTIN_STRATEGIES)


# --- list / get ------------------------------------------------------------------------------


def test_list_returns_the_builtins_first_then_stored_strategies() -> None:
    _create(slug="b-custom")
    _create(slug="a-custom")

    body = client.get("/strategies").json()

    slugs = [item["slug"] for item in body["items"]]
    assert slugs == [*(p.slug for p in PRESETS), "a-custom", "b-custom"]
    assert [item["builtin"] for item in body["items"]] == [True] * len(PRESETS) + [False] * 2


def test_get_returns_a_builtin_with_its_full_definition() -> None:
    response = client.get("/strategies/fresh-ob-trend")

    body = response.json()
    assert response.status_code == 200
    assert body["builtin"] is True
    assert body["zone_kinds"] == ["OB"]
    assert body["require"] == [{"key": "fresh", "params": {}}, {"key": "aligned", "params": {}}]
    assert Strategy.model_validate(body) == BUILTIN_STRATEGIES["fresh-ob-trend"]


def test_get_unknown_slug_is_404() -> None:
    response = client.get("/strategies/no-such")

    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "Strategy not found"}


@pytest.mark.parametrize("slug", ["Bad_Slug", "-lead", "x" * 33, "a.b", "a%0A"])
def test_malformed_path_slug_is_422_before_any_lookup(slug: str) -> None:
    app.dependency_overrides[deps_module.get_strategy_service] = _broken_service

    assert client.get(f"/strategies/{slug}").status_code == 422
    assert client.delete(f"/strategies/{slug}").status_code == 422


def test_api_slug_regex_agrees_with_the_model_pattern() -> None:
    api_pattern = re.compile(SLUG_REGEX)
    for slug in ["a", "smc-default", "0-9", "a" * 32, "a" * 33, "-a", "A", "a_b", "a\n", ""]:
        assert bool(api_pattern.fullmatch(slug)) == bool(SLUG_PATTERN.fullmatch(slug)), slug


# --- create ----------------------------------------------------------------------------------


def test_create_returns_201_with_the_stored_strategy() -> None:
    body = _create()

    assert body["slug"] == "my-ob"
    assert body["builtin"] is False
    assert body["score"][1] == {"key": "max_zone_age", "params": {"bars": 50}}
    assert client.get("/strategies/my-ob").json() == body


def test_create_fills_defaults_for_omitted_fields() -> None:
    response = client.post("/strategies", json={"slug": "bare", "name": "Bare"})

    body = response.json()
    assert response.status_code == 201, response.text
    assert body["zone_kinds"] == ["FVG", "OB"]
    assert body["statuses"] == ["TOUCHING", "NEAR"]
    assert body["require"] == [] and body["score"] == [] and body["min_score"] == 0
    assert body["description"] == ""


def test_create_never_takes_builtin_from_the_body() -> None:
    response = client.post("/strategies", json={**PAYLOAD, "builtin": True})

    assert response.status_code == 422
    assert client.get("/strategies/my-ob").status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"require": [{"key": "no_such_condition"}]},
        {"score": [{"key": "max_zone_age", "params": {"bars": 0}}]},
        {"score": [{"key": "max_zone_age", "params": {"weeks": 3}}]},
        {"min_score": 5},
        {"name": "<script>"},
        {"require": [{"key": "aligned"}], "score": [{"key": "aligned"}]},
        {"require_htf_aligned": True},
    ],
)
def test_invalid_strategies_are_422_with_a_fixed_message(changes: dict[str, Any]) -> None:
    response = client.post("/strategies", json={**PAYLOAD, **changes})

    assert response.status_code == 422
    assert response.json()["error"] in {"Invalid strategy", "Invalid request"}
    assert "no_such_condition" not in response.text and "weeks" not in response.text


def test_create_with_a_builtin_or_taken_slug_is_409() -> None:
    _create()

    assert client.post("/strategies", json={**PAYLOAD, "slug": "smc-default"}).status_code == 409
    response = client.post("/strategies", json=PAYLOAD)
    assert response.status_code == 409
    assert response.json()["error"] == "A strategy with this slug already exists"


def test_create_past_the_cap_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "MAX_STRATEGIES", 1)
    _create()

    response = client.post("/strategies", json={**PAYLOAD, "slug": "second"})

    assert response.status_code == 409
    assert response.json()["error"] == "Strategy limit reached"


# --- update / delete -------------------------------------------------------------------------


def test_update_replaces_the_definition_and_keeps_the_path_slug() -> None:
    _create()
    changed = {k: v for k, v in PAYLOAD.items() if k != "slug"} | {"name": "Renamed", "mtf": True}

    response = client.put("/strategies/my-ob", json=changed)

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed" and response.json()["mtf"] is True
    assert client.get("/strategies/my-ob").json()["name"] == "Renamed"


def test_update_rejects_a_slug_or_builtin_in_the_body() -> None:
    _create()
    body = {k: v for k, v in PAYLOAD.items() if k != "slug"}

    assert client.put("/strategies/my-ob", json={**body, "slug": "other"}).status_code == 422
    assert client.put("/strategies/my-ob", json={**body, "builtin": True}).status_code == 422


def test_update_unknown_is_404_and_builtin_is_409() -> None:
    body = {k: v for k, v in PAYLOAD.items() if k != "slug"}

    assert client.put("/strategies/no-such", json=body).status_code == 404
    response = client.put("/strategies/smc-default", json=body)
    assert response.status_code == 409
    assert response.json()["error"] == "Built-in strategies cannot be changed"


def test_update_validates_conditions() -> None:
    _create()
    body = {k: v for k, v in PAYLOAD.items() if k != "slug"} | {"score": [{"key": "nope"}]}

    response = client.put("/strategies/my-ob", json=body)

    assert response.status_code == 422
    assert response.json()["error"] == "Invalid strategy"


def test_delete_is_204_then_404() -> None:
    _create()

    response = client.delete("/strategies/my-ob")

    assert response.status_code == 204
    assert response.content == b""
    assert client.delete("/strategies/my-ob").status_code == 404
    assert client.get("/strategies/my-ob").status_code == 404


def test_delete_builtin_is_409() -> None:
    assert client.delete("/strategies/smc-default").status_code == 409
    assert client.get("/strategies/smc-default").status_code == 200


# --- store failures, rate limit, key ---------------------------------------------------------


def test_store_failure_is_503_without_the_database_path() -> None:
    app.dependency_overrides[deps_module.get_strategy_service] = _broken_service

    for response in (
        client.get("/strategies"),
        client.get("/strategies/my-ob"),
        client.post("/strategies", json=PAYLOAD),
    ):
        assert response.status_code == 503
        assert response.json()["error"] == "Strategy database unavailable"
        assert "secret" not in response.text


def test_builtins_still_resolve_when_the_store_is_down() -> None:
    app.dependency_overrides[deps_module.get_strategy_service] = _broken_service

    assert client.get("/strategies/smc-default").status_code == 200


def test_strategy_routes_are_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(deps_module.RATE_LIMITERS, "strategies", RateLimiter(1, 60.0))

    assert client.get("/strategies").status_code == 200
    response = client.get("/strategies/smc-default")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_strategy_routes_need_the_internal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", "s3cret")

    assert client.get("/strategies").status_code == 401
    assert client.post("/strategies", json=PAYLOAD).status_code == 401


# --- /config catalogue -----------------------------------------------------------------------


def test_config_lists_strategy_summaries_and_the_condition_catalogue() -> None:
    _create()

    body = client.get("/config").json()

    assert body["strategies"][0] == {
        "slug": "smc-default",
        "name": "SMC default",
        "builtin": True,
        "swing_length": 10,
        "near_atr": 0.5,
    }
    assert [s["slug"] for s in body["strategies"]][-1] == "my-ob"
    assert [c["key"] for c in body["conditions"]] == [c.key for c in conditions()]
    by_key = {c["key"]: c for c in body["conditions"]}
    assert "bars" in by_key["max_zone_age"]["params_schema"]["properties"]
    assert by_key["aligned"]["label"] == "Zone direction matches the trend"


def test_config_falls_back_to_builtins_when_the_store_is_down() -> None:
    app.dependency_overrides[deps_module.get_strategy_service] = _broken_service

    response = client.get("/config")

    assert response.status_code == 200
    assert [s["slug"] for s in response.json()["strategies"]] == [p.slug for p in PRESETS]


# --- /scan with a strategy -------------------------------------------------------------------


def _legacy_rows() -> list[dict[str, Any]]:
    """The rows ``/scan`` returned before strategies, rebuilt from the old scanner path."""
    result = run_scan(DemoLoader(), SYMBOLS.split(","), DEFAULT_TIMEFRAME, 300, ScanOptions())
    from smc_scanner.api.schemas import ScanRowOut

    old_fields = set(ScanRowOut.model_fields) - NEW_ROW_FIELDS
    return [
        ScanRowOut.from_row(row).model_dump(mode="json", include=old_fields) for row in result.rows
    ]


def test_scan_without_strategy_matches_the_pre_strategy_rows() -> None:
    plain = client.get("/scan", params=SCAN).json()
    default = client.get("/scan", params={**SCAN, "strategy": "smc-default"}).json()

    assert plain == default
    assert plain["strategy"] == "smc-default"
    assert plain["rows"], "the demo data should give hits"
    stripped = [{k: v for k, v in row.items() if k not in NEW_ROW_FIELDS} for row in plain["rows"]]
    assert stripped == _legacy_rows()
    for row in plain["rows"]:
        assert row["strategy"] == "smc-default"
        assert set(row["conditions"]) == {"aligned", "in_ote", "trendline_ok", "stacked"}
        assert sum(row["conditions"].values()) == row["score"]


def test_scan_with_a_builtin_strategy_applies_its_filters() -> None:
    response = client.get("/scan", params={**SCAN, "strategy": "fvg-ote-reversal"})

    body = response.json()
    assert response.status_code == 200
    assert body["strategy"] == "fvg-ote-reversal"
    for row in body["rows"]:
        assert row["strategy"] == "fvg-ote-reversal"
        assert row["zone"].endswith("FVG") and row["status"] == "TOUCHING"
        assert row["conditions"]["in_ote"] is True and row["conditions"]["touching"] is True


def test_scan_with_a_stored_strategy() -> None:
    _create(zone_kinds=["FVG", "OB"], require=[], score=[{"key": "fresh"}])

    body = client.get("/scan", params={**SCAN, "strategy": "my-ob", "all_touches": True}).json()

    assert body["strategy"] == "my-ob"
    assert all(set(row["conditions"]) == {"fresh"} for row in body["rows"])


def test_scan_with_an_unknown_strategy_is_422_with_a_fixed_message() -> None:
    response = client.get("/scan", params={**SCAN, "strategy": "no-such"})

    assert response.status_code == 422
    assert response.json()["error"] == "Unknown strategy"


@pytest.mark.parametrize("slug", ["Bad Slug", "smc-default" + chr(10)])
def test_scan_with_a_malformed_strategy_is_422(slug: str) -> None:
    assert client.get("/scan", params={**SCAN, "strategy": slug}).status_code == 422


def test_default_scan_needs_no_strategy_database() -> None:
    app.dependency_overrides[deps_module.get_strategy_service] = _broken_service

    assert client.get("/scan", params=SCAN).status_code == 200
    assert client.get("/scan", params={**SCAN, "strategy": "my-ob"}).status_code == 503
