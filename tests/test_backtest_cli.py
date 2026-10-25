"""``smc-backtest``: arguments, the table, files, storing, the csv spread default."""

import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from backtest_job_support import SECRET, FakeRunner

from smc_scanner.backtest import cli
from smc_scanner.backtest.report import ROW_COLUMNS
from smc_scanner.backtest.store import SqliteBacktestRepository
from smc_scanner.config import MAX_BARS
from smc_scanner.loaders import LoaderError
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.strategy.builtin import BUILTIN_STRATEGIES

DEMO = ["--source", "demo", "--symbols", "EURUSD", "XAUUSD", "--bars", "200"]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "smc.db"))
    monkeypatch.setenv("COLUMNS", "200")  # a wide table, so cells are not truncated


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(cli, "walk_forward_runner", lambda: fake)
    return fake


def test_demo_run_prints_one_row_per_strategy_with_the_verdict(
    runner: FakeRunner, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main([*DEMO, "--strategy", "smc-default", "--strategy", "fresh-ob-trend"])

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "smc-default" in out and "fresh-ob-trend" in out
    assert "pass" in out and "+0.200 [+0.000, +0.400]" in out  # out-of-sample, with its CI
    assert "+0.300 [+0.100, +0.500]" in out  # in-sample
    assert "-0.100" in out and "-0.300" in out  # the random and flipped baselines
    assert [call["strategy"] for call in runner.calls] == ["smc-default", "fresh-ob-trend"]
    assert runner.calls[0]["loaded"] == [200, 200]


def test_the_default_is_every_builtin_and_duplicates_run_once(runner: FakeRunner) -> None:
    assert cli.main(DEMO) == cli.EXIT_OK
    every = [call["strategy"] for call in runner.calls]
    runner.calls.clear()

    assert cli.main([*DEMO, "--strategy", "smc-default", "--strategy", "smc-default"]) == 0

    assert every == list(BUILTIN_STRATEGIES)
    assert [call["strategy"] for call in runner.calls] == ["smc-default"]


def test_the_rules_split_seed_and_stride_reach_the_runner(runner: FakeRunner) -> None:
    args = [
        *DEMO,
        "--strategy",
        "smc-default",
        "--rr",
        "3",
        "--stop-buffer-atr",
        "0.5",
        "--time-stop",
        "20",
        "--spread",
        "0.0001",
        "--split",
        "symbols",
        "--train-fraction",
        "0.5",
        "--seed",
        "9",
        "--stride",
        "4",
    ]

    assert cli.main(args) == cli.EXIT_OK

    call = runner.calls[0]
    rules = call["rules"]
    assert (rules.rr, rules.stop_buffer_atr, rules.time_stop_bars) == (3.0, 0.5, 20)
    assert rules.spread == 0.0001
    assert (call["split"].kind, call["split"].train_fraction) == ("symbols", 0.5)
    assert (call["seed"], call["stride"], call["bars"]) == (9, 4, 200)


def test_out_writes_a_csv_per_strategy_and_a_summary(runner: FakeRunner, tmp_path: Path) -> None:
    out = tmp_path / "results"
    args = ["--source", "demo", "--symbols", "EURUSD", "--bars", "300", "--stride", "5"]

    code = cli.main([*args, "--strategy", "smc-default", "--out", str(out)])

    assert code == cli.EXIT_OK
    with (out / "smc-default.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == list(ROW_COLUMNS)
    assert rows and {row["symbol"] for row in rows} == {"EURUSD"}  # replayed for the rows
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    entry = summary["strategies"][0]
    assert entry["strategy"] == "smc-default" and entry["verdict"] == "pass"
    assert entry["stats"]["pooled"]["n"] >= 0 and entry["stats"]["out_of_sample"]["n"] == 20
    assert "signals" not in entry["stats"] and summary["split"]["kind"] == "time"
    assert SECRET not in json.dumps(summary)


def test_csv_cells_that_look_like_formulas_are_neutralised(tmp_path: Path) -> None:
    stats = {"signals": [{"symbol": "EURUSD", "zone": "=HYPERLINK()", "r_multiple": 1.0}]}
    result = cli.StrategyResult("s", stats, None, 0.0)
    settings = cli._settings(cli.build_parser().parse_args(DEMO), cli.build_parser())

    cli.write_outputs([result], settings, tmp_path)

    with (tmp_path / "s.csv").open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["zone"] == "'=HYPERLINK()" and row["r_multiple"] == "1.0"


def test_save_stores_one_done_row_per_strategy(runner: FakeRunner, tmp_path: Path) -> None:
    code = cli.main([*DEMO, "--strategy", "smc-default", "--save"])

    rows = SqliteBacktestRepository(tmp_path / "smc.db").list()
    assert code == cli.EXIT_OK and len(rows) == 1
    row = rows[0]
    assert row.status == "done" and row.verdict == "pass" and row.source == "demo"
    assert row.symbols == ("EURUSD", "XAUUSD") and row.stats is not None
    assert "signals" not in row.stats and row.duration_seconds is not None
    assert SECRET not in str(row.stats)


def test_the_real_walk_forward_prints_a_verdict(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    args = ["--source", "demo", "--symbols", "EURUSD", "XAUUSD", "--bars", "150", "--stride", "10"]

    code = cli.main([*args, "--strategy", "smc-default", "--save"])

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert any(verdict in out for verdict in ("pass", "fail", "insufficient"))
    row = SqliteBacktestRepository(tmp_path / "smc.db").list()[0]
    assert row.verdict in {"pass", "fail", "insufficient"} and row.stats is not None
    assert "random_baseline" in row.stats and "pooled" not in row.stats


def _csv(path: Path, spread: list[float] | None, rows: int = 60) -> Path:
    frame = DemoLoader(seed=2).load("EURUSD", "1h", rows)
    if spread is not None:
        frame["Spread"] = (spread * rows)[:rows]
    frame.to_csv(path, index=False)
    return path


def test_csv_spread_defaults_to_the_mean_spread_column(runner: FakeRunner, tmp_path: Path) -> None:
    first = _csv(tmp_path / "a.csv", [0.0002, 0.0004])
    second = _csv(tmp_path / "b.csv", None)

    code = cli.main(["--source", "csv", "--symbols", str(first), str(second), "--save"])

    assert code == cli.EXIT_OK
    assert runner.calls[0]["rules"].spread == pytest.approx(0.0003)
    assert runner.calls[0]["bars"] == MAX_BARS
    row = SqliteBacktestRepository(tmp_path / "smc.db").list()[0]
    assert row.symbols == ("a.csv", "b.csv")  # file names only, never paths
    assert str(tmp_path) not in json.dumps(row.stats)


def test_an_explicit_spread_wins_over_the_csv_column(runner: FakeRunner, tmp_path: Path) -> None:
    path = _csv(tmp_path / "a.csv", [0.5])

    assert cli.main(["--source", "csv", "--symbols", str(path), "--spread", "0"]) == 0

    assert runner.calls[0]["rules"].spread == 0.0


def test_csv_spread_without_a_column_or_readable_file_is_zero(tmp_path: Path) -> None:
    plain = _csv(tmp_path / "plain.csv", None)
    (tmp_path / "broken.csv").write_bytes(b"\xff\xfe\x00garbage")

    assert cli.csv_spread([str(plain), str(tmp_path / "missing.csv")], 100) == 0.0
    assert cli.csv_spread([str(tmp_path / "broken.csv")], 100) == 0.0


def test_csv_spread_uses_only_the_last_bars_rows(tmp_path: Path) -> None:
    path = _csv(tmp_path / "a.csv", [1.0] * 50 + [3.0] * 10)

    assert cli.csv_spread([str(path)], 10) == 3.0


def test_csv_spread_ignores_a_non_numeric_column(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    pd.DataFrame({"time": ["x"], "spread": ["wide"]}).to_csv(path, index=False)

    assert cli.csv_spread([str(path)], 10) == 0.0


@pytest.mark.parametrize(
    "extra",
    [
        ["--bars", "1"],
        ["--bars", str(MAX_BARS + 1)],
        ["--seed", "-1"],
        ["--seed", str(2**32)],
        ["--stride", "0"],
        ["--strategy", "Bad Slug"],
        ["--rr", "0"],
        ["--time-stop", "0"],
        ["--spread", "-1"],
        ["--train-fraction", "1.5"],
        ["--split", "dates"],
        ["--symbols", "EUR/USD"],
        ["--symbols", *(f"S{i}" for i in range(51))],
    ],
)
def test_invalid_arguments_exit_with_a_usage_error(
    extra: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--source", "demo", *extra])

    assert raised.value.code == 2
    assert "smc-backtest" in capsys.readouterr().err


def test_an_unknown_strategy_fails(runner: FakeRunner) -> None:
    assert cli.main([*DEMO, "--strategy", "nope"]) == cli.EXIT_FAILED
    assert runner.calls == []


class _DeadLoader:
    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        raise LoaderError("terminal down")

    def close(self) -> None:
        return None


def test_nothing_loaded_fails(runner: FakeRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "make_loader", lambda _: _DeadLoader())

    assert cli.main(DEMO) == cli.EXIT_FAILED
    assert runner.calls == []


def test_an_unusable_database_fails_the_save(
    runner: FakeRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SMC_DB_PATH", str(tmp_path / "missing" / "smc.db"))

    assert cli.main([*DEMO, "--strategy", "smc-default", "--save"]) == cli.EXIT_FAILED


def test_an_unwritable_out_directory_fails(runner: FakeRunner, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")

    assert cli.main([*DEMO, "--strategy", "smc-default", "--out", str(blocker)]) == 1


def test_a_missing_watchlist_fails(runner: FakeRunner, tmp_path: Path) -> None:
    code = cli.main(["--source", "mt5", "--watchlist", str(tmp_path / "none.yaml")])

    assert code == cli.EXIT_FAILED


def test_ctrl_c_stops_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(*_: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run", interrupted)

    assert cli.main(DEMO) == cli.EXIT_INTERRUPTED == 130


def test_a_value_error_after_the_run_is_reported(
    runner: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    def too_big(*_: object) -> None:
        raise ValueError("backtest stats exceed 100000 characters")

    monkeypatch.setattr(cli, "save_results", too_big)

    assert cli.main([*DEMO, "--strategy", "smc-default", "--save"]) == cli.EXIT_FAILED


def test_a_symbol_split_needs_two_symbols(runner: FakeRunner) -> None:
    args = ["--source", "demo", "--symbols", "EURUSD", "--split", "symbols"]

    assert cli.main(args) == cli.EXIT_FAILED
    assert runner.calls == []


def test_render_shows_dashes_for_missing_parts() -> None:
    result = cli.StrategyResult("s", {"pooled": {"n": True}}, None, 0.0)

    table = cli.render([result], "t")

    cells = [column._cells[0] for column in table.columns]
    assert str(cells[1]) == "-" and str(cells[-1]) == "-"
