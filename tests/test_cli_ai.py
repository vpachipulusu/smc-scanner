"""``smc-scan --ai``: flags, verdict columns, and AI failures that never hide the scan."""

import csv
import sqlite3
from pathlib import Path

import pytest

from smc_scanner import ai_cli
from smc_scanner.ai.providers import AiError, AiReply
from smc_scanner.cli import main
from smc_scanner.models import ScanRow
from smc_scanner.report import AiCells, csv_safe, render_table, write_csv
from smc_scanner.scanner import ScanOptions

DEMO = ["--demo", "--symbols", "USDJPY", "EURUSD", "AUDUSD", "--bars", "300"]
AI = ["--ai", "--ai-provider", "fake", "--ai-min-score", "0"]


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "smc.db"
    monkeypatch.setenv("SMC_DB_PATH", str(path))
    return path


def _demo_db(db: Path) -> Path:
    return db.with_name(db.stem + ".demo.db")


def _read(out: Path) -> list[dict[str, str]]:
    with out.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _stored(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0])


@pytest.mark.parametrize(
    "argv",
    [
        [*DEMO, "--ai", "--ai-provider", "fake", "--ai-min-score", "5"],
        [*DEMO, "--ai", "--ai-provider", "fake", "--ai-min-score", "-1"],
        [*DEMO, "--ai", "--ai-provider", "fake", "--ai-max", "0"],
        [*DEMO, "--ai", "--ai-provider", "fake", "--ai-max", "51"],
        [*DEMO, "--ai-min-score", "2"],
        [*DEMO, "--ai-max", "3"],
        [*DEMO, "--ai-provider", "claude"],
        ["--source", "csv", "--symbols", "x.csv", "--ai", "--ai-provider", "fake"],
        [*DEMO, "--ai", "--ai-provider", "openai"],
    ],
)
def test_ai_flags_are_validated(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(argv)


def test_demo_ai_runs_end_to_end_with_the_fake_provider(tmp_path: Path, db_path: Path) -> None:
    out = tmp_path / "scan.csv"

    code = main([*DEMO, *AI, "--out", str(out)])

    rows = _read(out)
    assert code == 0
    assert rows and {r["ai_action"] for r in rows} == {"HOLD"}
    assert {r["ai_note"] for r in rows} <= {"", "score below minimum"}
    assert _stored(_demo_db(db_path)) == len(rows)
    assert not db_path.exists()  # demo verdicts never touch the real store


def test_csv_has_verdict_columns_only_with_ai(tmp_path: Path, db_path: Path) -> None:
    plain = tmp_path / "plain.csv"
    with_ai = tmp_path / "ai.csv"

    main([*DEMO, "--out", str(plain)])
    main([*DEMO, *AI, "--out", str(with_ai)])

    assert "ai_action" not in _read(plain)[0]
    assert {"ai_action", "ai_confidence", "ai_entry", "ai_stop", "ai_target", "ai_note"} <= set(
        _read(with_ai)[0]
    )
    assert _demo_db(db_path).exists()


def test_without_ai_no_database_is_created(tmp_path: Path, db_path: Path) -> None:
    main([*DEMO, "--out", str(tmp_path / "x.csv")])

    assert not db_path.exists()


def test_second_run_makes_no_second_provider_call(
    tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ai_cli.DemoProvider()
    monkeypatch.setattr(ai_cli, "build_provider", lambda name: provider)
    out = tmp_path / "scan.csv"

    main([*DEMO, *AI, "--out", str(out)])
    first = len(provider.calls)
    main([*DEMO, *AI, "--out", str(out)])

    assert first >= 1
    assert len(provider.calls) == first
    assert {r["ai_note"] for r in _read(out)} == {"already analysed"}


def test_low_score_and_cap_rows_report_the_reason(tmp_path: Path, db_path: Path) -> None:
    out = tmp_path / "scan.csv"

    main([*DEMO, "--ai", "--ai-provider", "fake", "--ai-min-score", "4", "--out", str(out)])
    low = _read(out)
    main([*DEMO, *AI, "--ai-max", "1", "--out", str(out)])
    capped = _read(out)

    assert low and {r["ai_note"] for r in low} == {"score below minimum"}
    assert sum(1 for r in capped if r["ai_action"] and not r["ai_note"]) == 1
    assert sum(1 for r in capped if r["ai_note"] == "over the per-run cap") == len(capped) - 1


def test_missing_key_never_hides_the_scan(
    tmp_path: Path,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(name: str | None) -> object:
        raise AiError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(ai_cli, "build_provider", broken)
    out = tmp_path / "scan.csv"

    code = main([*DEMO, *AI, "--out", str(out)])

    rows = _read(out)
    assert code == 0
    assert rows and rows[0]["instrument"]
    assert all(r["ai_action"] == "" for r in rows)
    assert all("ANTHROPIC_API_KEY" in r["ai_note"] for r in rows)
    assert any("ANTHROPIC_API_KEY" in m for m in caplog.messages)


def test_provider_failures_are_recorded_per_row(
    tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Exploding(ai_cli.DemoProvider):
        def complete(self, system: str, user: str) -> AiReply:
            raise AiError("provider down")

    monkeypatch.setattr(ai_cli, "build_provider", lambda name: Exploding())
    out = tmp_path / "scan.csv"

    code = main([*DEMO, *AI, "--out", str(out)])

    rows = _read(out)
    assert code == 0 and rows
    assert all(r["ai_action"] == "" and "provider down" in r["ai_note"] for r in rows)


def test_store_error_never_hides_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "no_such_dir" / "smc.db"))
    out = tmp_path / "scan.csv"

    code = main([*DEMO, *AI, "--out", str(out)])

    rows = _read(out)
    assert code == 0 and rows
    assert all(r["ai_action"] == "" and r["ai_note"] for r in rows)
    assert any("database" in m for m in caplog.messages)


def test_csv_cells_that_look_like_formulas_are_neutralised() -> None:
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("@x") == "'@x"
    assert csv_safe("normal") == "normal"
    assert AiCells(note="=HYPERLINK()").csv_row()["ai_note"] == "'=HYPERLINK()"


def test_every_loop_runs_the_analysis_each_cycle(
    tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ai_cli.DemoProvider()
    monkeypatch.setattr(ai_cli, "build_provider", lambda name: provider)
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep)

    code = main([*DEMO, *AI, "--every", "1", "--out", str(tmp_path / "s.csv")])

    assert code == 0 and len(sleeps) == 2
    assert 1 <= len(provider.calls) <= 3  # three cycles ran, only the first paid for hits


def test_markup_in_notes_cannot_break_the_table(
    tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Hostile(ai_cli.DemoProvider):
        def complete(self, system: str, user: str) -> AiReply:
            raise AiError("[/oops] [link=https://evil.example]x[/link]")

    monkeypatch.setattr(ai_cli, "build_provider", lambda name: Hostile())
    out = tmp_path / "scan.csv"

    code = main([*DEMO, *AI, "--out", str(out)])

    assert code == 0 and _read(out)


def test_store_path_is_not_written_to_the_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "secret_dir" / "smc.db"))
    out = tmp_path / "scan.csv"

    main([*DEMO, *AI, "--out", str(out)])

    assert all("secret_dir" not in r["ai_note"] for r in _read(out))


def test_unexpected_errors_in_the_analysis_are_contained(
    tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise KeyError("secret-looking-detail")

    monkeypatch.setattr(ai_cli, "analyse_hits", boom)
    out = tmp_path / "scan.csv"

    code = main([*DEMO, *AI, "--out", str(out)])

    rows = _read(out)
    assert code == 0 and rows
    assert all("KeyError" in r["ai_note"] and "secret" not in r["ai_note"] for r in rows)


def test_fake_provider_is_refused_in_the_ai_layer_without_demo() -> None:
    row = ScanRow(
        "X", "TOUCHING", "bull OB", 1.0, 2.0, 1.5, 0.0, "bullish", True, True, True, 4, 1, 0, "t"
    )

    cells = ai_cli.analyse_for_cli(
        [row], {}, ScanOptions(), "1h", ai_cli.AiSettings("fake", 0, 5, demo=False)
    )

    assert cells[0].note.startswith("unavailable") and cells[0].action == ""


def test_misaligned_ai_cells_are_rejected_before_writing(tmp_path: Path) -> None:
    row = ScanRow(
        "X", "TOUCHING", "bull OB", 1.0, 2.0, 1.5, 0.0, "bullish", True, True, True, 4, 1, 0, "t"
    )
    out = tmp_path / "keep.csv"
    out.write_text("previous")

    with pytest.raises(ValueError, match="AI cell sets"):
        write_csv([row], out, [])
    assert out.read_text() == "previous"
    with pytest.raises(ValueError, match="AI cell sets"):
        render_table([row], ai=[])


def test_all_symbols_failing_with_ai_creates_no_store(tmp_path: Path, db_path: Path) -> None:
    code = main(
        [
            "--source",
            "csv",
            "--symbols",
            str(tmp_path / "gone.csv"),
            "--ai",
            "--out",
            str(tmp_path / "o.csv"),
        ]
    )

    assert code == 1
    assert not db_path.exists()
