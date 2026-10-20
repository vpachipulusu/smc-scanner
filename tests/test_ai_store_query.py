"""``get_by_id`` and ``list_filtered`` on the SQLite store."""

from pathlib import Path

import pytest

from smc_scanner.ai.store import AnalysisKey, AnalysisRecord, SqliteAnalysisStore


def _record(symbol: str, low: float, verdict: dict[str, object] | None) -> AnalysisRecord:
    return AnalysisRecord(
        key=AnalysisKey(symbol, "H1", "OB", low, low + 1, "2026-01-01T00:00:00"),
        created_at="2026-01-01T00:00:00+00:00",
        zone={"label": "Bull OB"},
        context=None,
        verdict=verdict,
        provider="claude",
        model="m",
        prompt_version="v1",
        tokens_in=None,
        tokens_out=None,
        cost_estimate=None,
        error=None if verdict else "AiError: x",
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteAnalysisStore:
    store = SqliteAnalysisStore(tmp_path / "q.db")
    store.save(_record("EURUSD", 1, {"action": "BUY", "confidence": 80}))
    store.save(_record("EURUSD", 3, {"action": "SELL", "confidence": 30}))
    store.save(_record("XAUUSD", 5, None))
    return store


def test_get_by_id(store: SqliteAnalysisStore) -> None:
    found = store.get_by_id(2)

    assert found is not None
    assert found.id == 2
    assert found.key.symbol == "EURUSD"
    assert store.get_by_id(99) is None


def test_list_filtered_newest_first_and_keyset(store: SqliteAnalysisStore) -> None:
    assert [r.id for r in store.list_filtered()] == [3, 2, 1]
    assert [r.id for r in store.list_filtered(before_id=3)] == [2, 1]
    assert [r.id for r in store.list_filtered(limit=1)] == [3]


def test_list_filtered_filters_and_skips_failed_for_verdict_filters(
    store: SqliteAnalysisStore,
) -> None:
    assert [r.id for r in store.list_filtered(symbol="XAUUSD")] == [3]
    assert [r.id for r in store.list_filtered(action="BUY")] == [1]
    assert [r.id for r in store.list_filtered(min_confidence=0)] == [2, 1]


def test_list_filtered_treats_input_as_data(store: SqliteAnalysisStore) -> None:
    assert store.list_filtered(symbol="EURUSD' OR '1'='1") == []


def test_list_filtered_rejects_bad_limit(store: SqliteAnalysisStore) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        store.list_filtered(limit=0)
