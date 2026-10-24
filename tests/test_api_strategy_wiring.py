"""The ``strategy`` field on /schedules and /analyse, and on the stored analyses."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smc_scanner import api
from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, SqliteAnalysisStore
from smc_scanner.ai_cli import DemoProvider
from smc_scanner.api import app

client = TestClient(app, base_url="http://localhost")

SCHEDULE: dict[str, Any] = {
    "name": "Majors hourly",
    "source": "demo",
    "tf": "1h",
    "symbols": ["EURUSD"],
    "frequency": "1h",
}
ANALYSE = {"source": "demo", "symbols": ["USDJPY", "EURUSD", "AUDUSD"], "bars": 300, "min_score": 0}
CUSTOM = {"slug": "my-ob", "name": "My OB", "zone_kinds": ["OB"]}


@pytest.fixture(autouse=True)
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "smc.db"
    monkeypatch.setenv("SMC_DB_PATH", str(path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    yield path
    app.dependency_overrides.clear()


@pytest.fixture
def provider() -> DemoProvider:
    demo = DemoProvider()
    app.dependency_overrides[api.get_provider_factory] = lambda: lambda: demo
    return demo


# --- schedules -------------------------------------------------------------------------------


def test_schedule_strategy_defaults_to_smc_default() -> None:
    response = client.post("/schedules", json=SCHEDULE)

    assert response.status_code == 201
    assert response.json()["strategy"] == "smc-default"


def test_schedule_takes_a_builtin_or_stored_strategy() -> None:
    assert client.post("/strategies", json=CUSTOM).status_code == 201

    builtin = client.post("/schedules", json={**SCHEDULE, "strategy": "fresh-ob-trend"})
    stored = client.post("/schedules", json={**SCHEDULE, "strategy": "my-ob"})

    assert builtin.json()["strategy"] == "fresh-ob-trend"
    assert stored.json()["strategy"] == "my-ob"
    assert client.get(f"/schedules/{stored.json()['id']}").json()["strategy"] == "my-ob"


@pytest.mark.parametrize("slug", ["no-such", "Bad Slug"])
def test_schedule_with_an_unknown_strategy_is_422(slug: str) -> None:
    response = client.post("/schedules", json={**SCHEDULE, "strategy": slug})

    assert response.status_code == 422
    assert client.get("/schedules").json()["items"] == []


def test_patch_changes_the_strategy_and_validates_it() -> None:
    created = client.post("/schedules", json=SCHEDULE).json()
    url = f"/schedules/{created['id']}"

    changed = client.patch(url, json={"strategy": "fvg-ote-reversal"})
    unknown = client.patch(url, json={"strategy": "no-such"})
    untouched = client.patch(url, json={"name": "renamed"})

    assert changed.status_code == 200 and changed.json()["strategy"] == "fvg-ote-reversal"
    assert unknown.status_code == 422
    assert unknown.json()["error"] == "Unknown strategy"
    assert untouched.json()["strategy"] == "fvg-ote-reversal"


# --- /analyse --------------------------------------------------------------------------------


@pytest.mark.usefixtures("provider")
def test_analyse_with_a_strategy_tags_rows_and_stored_analyses() -> None:
    response = client.post("/analyse", json={**ANALYSE, "strategy": "smc-default"})

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["strategy"] == "smc-default"
    assert body["rows"] and all(row["strategy"] == "smc-default" for row in body["rows"])
    assert all(set(row["conditions"]) == {"aligned", "in_ote", "trendline_ok", "stacked"}
               for row in body["rows"])  # fmt: skip
    items = client.get("/analyses").json()["items"]
    assert items and all(item["strategy"] == "smc-default" for item in items)
    assert all(item["prompt_version"] == "smc-verdict-4" for item in items)


@pytest.mark.usefixtures("provider")
def test_analyse_with_a_strategy_that_needs_the_higher_timeframe() -> None:
    response = client.post("/analyse", json={**ANALYSE, "strategy": "htf-aligned-touch"})

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["strategy"] == "htf-aligned-touch"
    for row in body["rows"]:  # the strategy turned mtf on although the body left it off
        assert "htf_aligned" in row["conditions"]
        assert row["status"] == "TOUCHING"


@pytest.mark.usefixtures("provider")
def test_analyse_without_a_strategy_is_the_default() -> None:
    body = client.post("/analyse", json=ANALYSE).json()

    assert body["strategy"] == "smc-default"


def test_analyse_with_an_unknown_strategy_is_422_before_the_provider_is_built() -> None:
    def no_provider() -> Any:
        raise AssertionError("the provider must not be built")

    app.dependency_overrides[api.get_provider_factory] = lambda: no_provider

    response = client.post("/analyse", json={**ANALYSE, "strategy": "no-such"})

    assert response.status_code == 422
    assert response.json()["error"] == "Unknown strategy"


def test_stored_analyses_without_a_strategy_read_as_the_default(db_path: Path) -> None:
    store = SqliteAnalysisStore(db_path)
    for strategy, low in ((None, 1.1), ("fresh-ob-trend", 1.3), ("BAD slug!", 1.5)):
        store.save(
            AnalysisRecord(
                key=AnalysisKey("EURUSD", "1h", "FVG", low, low + 0.1, "2026-03-01T11:00:00+00:00"),
                created_at="2026-03-01T12:00:00+00:00",
                zone={"label": "bull FVG"},
                context=None,
                verdict=None,
                provider="fake",
                model="f",
                prompt_version="smc-verdict-3",
                tokens_in=None,
                tokens_out=None,
                cost_estimate=None,
                error="x",
                strategy=strategy,
            )
        )

    items = client.get("/analyses").json()["items"]

    assert [item["strategy"] for item in items] == ["smc-default", "fresh-ob-trend", "smc-default"]
    assert client.get(f"/analyses/{items[1]['id']}").json()["strategy"] == "fresh-ob-trend"
