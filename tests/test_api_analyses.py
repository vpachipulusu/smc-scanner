"""POST /analyse and GET /analyses[/{id}] on the demo source with an injected provider."""

import base64
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_scanner import api
from smc_scanner.ai.analyst import AnalysisResult
from smc_scanner.ai.providers import AiError, AiReply
from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, SqliteAnalysisStore, StoreError
from smc_scanner.ai.verdict import AiVerdict
from smc_scanner.ai_cli import DemoProvider
from smc_scanner.api import app
from smc_scanner.api import deps as deps_module
from smc_scanner.api.routes import analyses as analyses_routes
from smc_scanner.loaders.mt5 import MT5_MODULE_NAME
from smc_scanner.models import ScanRow

SECRET = "sk-ant-test-secret-value"
BODY = {
    "source": "demo",
    "symbols": ["USDJPY", "EURUSD", "AUDUSD"],
    "bars": 300,
    "min_score": 0,
    "max_rows": 10,
}
client = TestClient(app, base_url="http://localhost")


@pytest.fixture(autouse=True)
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "smc.db"
    monkeypatch.setenv("SMC_DB_PATH", str(path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.delenv("SMC_INTERNAL_KEY", raising=False)
    yield path
    app.dependency_overrides.clear()


def _inject(provider: DemoProvider) -> None:
    app.dependency_overrides[api.get_provider_factory] = lambda: lambda: provider


@pytest.fixture
def empty_db(db_path: Path) -> Path:
    SqliteAnalysisStore(db_path)
    return db_path


@pytest.fixture
def provider() -> DemoProvider:
    demo = DemoProvider()
    _inject(demo)
    return demo


def _seed(
    db: Path, symbol: str, action: str, confidence: float, n: int = 1, base: float = 1.0
) -> None:
    store = SqliteAnalysisStore(db)
    for i in range(n):
        verdict: dict[str, object] = {"action": action, "confidence": confidence, "summary": "s"}
        if action != "HOLD":
            verdict |= {"entry": 1.5, "stop": 1.0, "targets": [2.0], "risk_reward": 2.0}
        store.save(
            AnalysisRecord(
                key=AnalysisKey(symbol, "H1", "OB", base + i, base + 1 + i, "2026-01-01T00:00:00"),
                created_at="2026-01-01T00:00:00+00:00",
                zone={"label": "Bull OB"},
                context=None,
                verdict=verdict,
                provider="claude",
                model="m",
                prompt_version="v1",
                tokens_in=1,
                tokens_out=1,
                cost_estimate=None,
                error=None,
            )
        )


# --- POST /analyse -----------------------------------------------------------------------


def test_analyse_returns_rows_with_ai_results(provider: DemoProvider) -> None:
    response = client.post("/analyse", json=BODY)

    body = response.json()
    assert response.status_code == 200
    assert body["count"] == len(body["rows"]) >= 1
    assert len(provider.calls) >= 1
    analysed = [row for row in body["rows"] if row["ai"]["status"] == "analysed"]
    assert analysed
    assert analysed[0]["ai"]["verdict"]["action"] == "HOLD"
    assert {"instrument", "score", "ai"} <= set(body["rows"][0])
    assert SECRET not in response.text


def test_analyse_marks_low_score_and_cap(provider: DemoProvider) -> None:
    response = client.post("/analyse", json={**BODY, "max_rows": 1})

    rows = response.json()["rows"]
    statuses = [row["ai"]["status"] for row in rows]
    assert statuses.count("analysed") == 1
    assert len(provider.calls) == 1
    capped = [row["ai"] for row in rows if row["ai"]["status"] == "skipped_cap"]
    assert all(ai["verdict"] is None and ai["note"] for ai in capped)


def test_second_run_reports_duplicates_without_calls(provider: DemoProvider) -> None:
    client.post("/analyse", json=BODY)
    calls = len(provider.calls)

    again = client.post("/analyse", json=BODY).json()

    assert len(provider.calls) == calls
    assert any(row["ai"]["status"] == "skipped_duplicate" for row in again["rows"])


def test_scan_lock_is_not_held_during_provider_call() -> None:
    seen: list[bool] = []

    class _Probe(DemoProvider):
        def complete(self, system: str, user: str) -> AiReply:
            seen.append(api._scan_lock.locked())
            return super().complete(system, user)

    _inject(_Probe())

    assert client.post("/analyse", json=BODY).status_code == 200
    assert seen
    assert not any(seen)
    assert not api._scan_lock.locked()


@pytest.mark.parametrize(
    "patch",
    [
        {"source": "oanda"},
        {"source": "csv"},
        {"bars": 5},
        {"swing": 0},
        {"near": -1},
        {"symbols": ["../../etc/passwd"]},
        {"symbols": [f"S{i}" for i in range(60)]},
        {"provider": "fake"},
        {"provider": "openai"},
        {"min_score": 5},
        {"min_score": -1},
        {"max_rows": 0},
        {"max_rows": 1000},
        {"unknown_field": 1},
    ],
)
def test_analyse_validates_body(patch: dict[str, object], provider: DemoProvider) -> None:
    response = client.post("/analyse", json={**BODY, **patch})

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert provider.calls == []


def test_analyse_503_when_ai_disabled_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["error"]
    assert response.json()["success"] is False


def test_scan_still_works_without_an_ai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    response = client.get("/scan", params={"source": "demo", "symbols": "EURUSD", "bars": 300})

    assert response.status_code == 200


def test_analyse_503_when_every_symbol_fails(
    monkeypatch: pytest.MonkeyPatch, provider: DemoProvider
) -> None:
    class _Down:
        def initialize(self, **_: object) -> bool:
            return False

        def last_error(self) -> tuple[int, str]:
            return (-10005, "IPC timeout")

    monkeypatch.setitem(sys.modules, MT5_MODULE_NAME, _Down())

    response = client.post("/analyse", json={**BODY, "source": "mt5", "symbols": ["EURUSD"]})

    assert response.status_code == 503
    assert "IPC timeout" not in response.text
    assert provider.calls == []


def test_analyse_502_when_provider_fails_for_the_whole_run(db_path: Path) -> None:
    class _Broken(DemoProvider):
        def complete(self, system: str, user: str) -> AiReply:
            raise AiError(f"upstream said no, key {SECRET}")

    _inject(_Broken())

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 502
    assert response.json() == {"success": False, "error": "AI provider failed"}
    assert SECRET not in response.text
    assert str(db_path) not in response.text


def test_partial_provider_failure_is_a_200_with_failed_rows() -> None:
    class _Flaky(DemoProvider):
        def complete(self, system: str, user: str) -> AiReply:
            if self.calls:
                raise AiError("boom")
            return super().complete(system, user)

    _inject(_Flaky())

    response = client.post("/analyse", json=BODY)

    rows = response.json()["rows"]
    failed = [row["ai"] for row in rows if row["ai"]["status"] == "failed"]
    assert response.status_code == 200
    assert failed
    assert all("boom" not in ai["note"] for ai in failed)


def test_analyse_requires_internal_key_when_set(
    monkeypatch: pytest.MonkeyPatch, provider: DemoProvider
) -> None:
    monkeypatch.setenv("SMC_INTERNAL_KEY", "k")

    assert client.post("/analyse", json=BODY).status_code == 401
    assert client.get("/analyses").status_code == 401
    assert client.get("/analyses/1").status_code == 401
    assert client.post("/analyse", json=BODY, headers={"X-Internal-Key": "k"}).status_code == 200


def test_store_failure_hides_the_database_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: DemoProvider
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "no_such_dir" / "smc.db"))

    for response in (client.post("/analyse", json=BODY), client.get("/analyses")):
        assert response.status_code == 503
        assert response.json() == {"success": False, "error": "Analysis database unavailable"}
        assert "no_such_dir" not in response.text


# --- GET /analyses -----------------------------------------------------------------------


def test_list_is_empty_on_a_fresh_database(empty_db: Path) -> None:
    response = client.get("/analyses")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_returns_saved_analyses_newest_first(provider: DemoProvider) -> None:
    client.post("/analyse", json=BODY)

    body = client.get("/analyses").json()

    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids, reverse=True)
    assert len(ids) >= 1
    item = body["items"][0]
    assert item["status"] == "ok"
    assert item["verdict"]["action"] == "HOLD"
    assert "context" not in item
    assert SECRET not in str(body)


def test_list_filters(db_path: Path) -> None:
    _seed(db_path, "EURUSD", "BUY", 80)
    _seed(db_path, "EURUSD", "SELL", 40, base=10.0)
    _seed(db_path, "XAUUSD", "BUY", 60)

    def symbols(**params: str | int) -> list[str]:
        items = client.get("/analyses", params=params).json()["items"]
        return [item["symbol"] for item in items]

    assert sorted(symbols(symbol="EURUSD")) == ["EURUSD", "EURUSD"]
    assert symbols(action="SELL") == ["EURUSD"]
    assert sorted(symbols(min_confidence=60)) == ["EURUSD", "XAUUSD"]
    assert symbols(symbol="XAUUSD", action="BUY", min_confidence=61) == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"action": "MAYBE"},
        {"symbol": "../x"},
        {"min_confidence": -1},
        {"min_confidence": 101},
        {"cursor": "not-a-cursor"},
        {"cursor": base64.urlsafe_b64encode(b"abc").decode()},
    ],
)
def test_list_validates_params(params: dict[str, str | int]) -> None:
    response = client.get("/analyses", params=params)

    assert response.status_code == 422
    assert response.json()["success"] is False


def test_list_cursor_paging_covers_every_row_once(db_path: Path) -> None:
    _seed(db_path, "EURUSD", "BUY", 80, n=5)

    seen: list[int] = []
    cursor: str | None = None
    pages = 0
    while pages < 10:
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/analyses", params=params).json()
        seen += [item["id"] for item in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == [5, 4, 3, 2, 1]
    assert pages == 3


def test_last_full_page_has_no_cursor(db_path: Path) -> None:
    _seed(db_path, "EURUSD", "BUY", 80, n=2)

    page = client.get("/analyses", params={"limit": 2}).json()

    assert len(page["items"]) == 2
    assert page["next_cursor"] is None


def test_failed_attempts_are_listed_without_error_text(db_path: Path) -> None:
    SqliteAnalysisStore(db_path).save(
        AnalysisRecord(
            key=AnalysisKey("EURUSD", "H1", "OB", 1.0, 2.0, "2026-01-01T00:00:00"),
            created_at="2026-01-01T00:00:00+00:00",
            zone={"label": "Bull OB"},
            context=None,
            verdict=None,
            provider="claude",
            model="m",
            prompt_version="v1",
            tokens_in=None,
            tokens_out=None,
            cost_estimate=None,
            error=f"AiError: secret detail {SECRET}",
        )
    )

    item = client.get("/analyses").json()["items"][0]

    assert item["status"] == "failed"
    assert item["verdict"] is None
    assert SECRET not in str(item)


# --- GET /analyses/{id} ------------------------------------------------------------------


def test_get_analysis_by_id(db_path: Path) -> None:
    _seed(db_path, "EURUSD", "BUY", 80)

    response = client.get("/analyses/1")

    assert response.status_code == 200
    assert response.json()["symbol"] == "EURUSD"
    assert response.json()["verdict"]["action"] == "BUY"


@pytest.mark.parametrize("path", ["/analyses/999", "/analyses/1"])
def test_unknown_id_is_a_404_envelope(path: str, empty_db: Path) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "Analysis not found"}


@pytest.mark.parametrize("path", ["/analyses/abc", "/analyses/0", "/analyses/-1"])
def test_bad_id_is_422(path: str) -> None:
    assert client.get(path).status_code == 422


def test_ids_beyond_sqlite_integers_are_422_not_500() -> None:
    too_big = 2**63
    cursor = base64.urlsafe_b64encode(f"id:{too_big}".encode()).decode()

    assert client.get(f"/analyses/{too_big}").status_code == 422
    assert client.get("/analyses", params={"cursor": cursor}).status_code == 422
    ok = base64.urlsafe_b64encode(f"id:{2**63 - 1}".encode()).decode()
    assert client.get("/analyses", params={"cursor": ok}).status_code == 503  # no database yet


def test_reads_never_create_the_database(db_path: Path) -> None:
    for path in ("/analyses", "/analyses/1"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"success": False, "error": "Analysis database unavailable"}
    assert not db_path.exists()


def test_reads_do_not_write_to_an_existing_database(empty_db: Path) -> None:
    before = empty_db.stat().st_mtime_ns

    assert client.get("/analyses").status_code == 200
    assert empty_db.stat().st_mtime_ns == before


def test_invalid_body_is_422_even_when_ai_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    assert client.post("/analyse", json={**BODY, "bars": 5}).status_code == 422
    assert client.post("/analyse", json={**BODY, "symbols": []}).status_code == 422


def test_unavailable_provider_with_a_key_gets_a_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_: str | None = None) -> None:
        raise AiError(f"AI_BASE_URL must be an https URL, key {SECRET}")

    monkeypatch.setattr(deps_module, "make_provider", broken)

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "error": "AI analysis is unavailable; see the server log",
    }


def test_cursor_paging_with_a_filter(db_path: Path) -> None:
    _seed(db_path, "EURUSD", "BUY", 80, n=3)
    _seed(db_path, "XAUUSD", "BUY", 80, n=2, base=50.0)
    _seed(db_path, "EURUSD", "SELL", 80, n=2, base=100.0)

    first = client.get("/analyses", params={"symbol": "EURUSD", "action": "BUY", "limit": 2}).json()
    second = client.get(
        "/analyses",
        params={"symbol": "EURUSD", "action": "BUY", "limit": 2, "cursor": first["next_cursor"]},
    ).json()

    assert [i["id"] for i in first["items"]] == [3, 2]
    assert [i["id"] for i in second["items"]] == [1]
    assert second["next_cursor"] is None


def test_concurrent_identical_runs_call_the_provider_once_per_hit() -> None:
    gate = threading.Event()

    class _Slow(DemoProvider):
        def complete(self, system: str, user: str) -> AiReply:
            gate.wait(0.2)
            return super().complete(system, user)

    slow = _Slow()
    _inject(slow)
    codes: list[int] = []

    def run() -> None:
        codes.append(client.post("/analyse", json=BODY).status_code)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert codes == [200, 200]
    assert len(slow.calls) == len({call[1] for call in slow.calls})  # no hit asked twice


# --- store failures after the store opened ------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("list_filtered", "/analyses"), ("get_by_id", "/analyses/1")],
)
def test_store_errors_while_reading_are_503(
    method: str, path: str, monkeypatch: pytest.MonkeyPatch, db_path: Path
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise StoreError(f"analysis database {db_path}: disk I/O error")

    monkeypatch.setattr(SqliteAnalysisStore, method, broken)

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"success": False, "error": "Analysis database unavailable"}
    assert str(db_path) not in response.text


def test_store_errors_while_analysing_are_503(
    monkeypatch: pytest.MonkeyPatch, provider: DemoProvider, db_path: Path
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise StoreError(f"analysis database {db_path}: locked")

    monkeypatch.setattr(analyses_routes, "analyse_hits", broken)

    response = client.post("/analyse", json=BODY)

    assert response.status_code == 503
    assert str(db_path) not in response.text


def test_cursor_with_non_numeric_id_is_rejected() -> None:
    bad = base64.urlsafe_b64encode(b"id:abc").decode()
    undecodable = base64.urlsafe_b64encode(b"\xff\xfe").decode()

    assert client.get("/analyses", params={"cursor": bad}).status_code == 422
    assert client.get("/analyses", params={"cursor": undecodable}).status_code == 422


def test_note_texts_for_downgraded_and_unsaved_results(provider: DemoProvider) -> None:
    row = ScanRow(
        "EURUSD",
        "NEAR",
        "Bull OB",
        1.0,
        2.0,
        1.5,
        0.5,
        "bullish",
        False,
        False,
        False,
        1,
        3,
        0,
        "t",
    )
    held = AiVerdict(action="HOLD", confidence=0, downgraded=True, downgrade_reason="too wide")

    assert api._note(AnalysisResult(row, "analysed", held)) == "too wide"
    assert "not saved" in api._note(
        AnalysisResult(
            row,
            "analysed",
            held.model_copy(update={"downgraded": False, "downgrade_reason": None}),
            "StoreError",
        )
    )
