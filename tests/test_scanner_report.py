"""Sort order, per-symbol failure handling, option validation, table and CSV output."""

import csv
from pathlib import Path

import pandas as pd
import pytest
from conftest import FLAT, frame
from rich.console import Console

from smc_scanner.loaders.base import LoaderError
from smc_scanner.models import Bias, ScanRow, Status
from smc_scanner.report import COLUMNS, render_table, rows_to_dicts, write_csv
from smc_scanner.scanner import ScanOptions, run_scan, scan_instrument, scan_watchlist, sort_rows


def _row(instrument: str, status: Status, score: int, dist: float) -> ScanRow:
    bias: Bias = "range"
    return ScanRow(
        instrument=instrument,
        status=status,
        zone="bull FVG",
        zone_low=1.08123,
        zone_high=1.08127,
        price=65432.1,
        dist_atr=dist,
        bias=bias,
        in_ote=False,
        trendline_ok=False,
        ob_fvg=False,
        score=score,
        zone_age=3,
        prior_touches=0,
        bar_time="t",
    )


def test_sort_touching_first_then_score_then_distance() -> None:
    rows = [
        _row("a", "NEAR", 4, 0.1),
        _row("b", "TOUCHING", 1, 0.0),
        _row("c", "TOUCHING", 3, 0.0),
        _row("d", "NEAR", 2, 0.3),
        _row("e", "NEAR", 2, 0.2),
    ]

    assert [row.instrument for row in sort_rows(rows)] == ["c", "b", "a", "e", "d"]


class _Loader:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.closed = False

    def load(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        if symbol not in self.frames:
            raise LoaderError(f"no data for {symbol}")
        return self.frames[symbol]

    def close(self) -> None:
        self.closed = True


def test_failing_symbol_is_recorded_and_others_still_scanned(
    fvg_touching: pd.DataFrame, caplog: pytest.LogCaptureFixture
) -> None:
    loader = _Loader({"GOOD": fvg_touching})

    result = scan_watchlist(loader, ["BAD", "GOOD"], "1h", 50, ScanOptions(swing_length=2))

    assert {row.instrument for row in result.rows} == {"GOOD"}
    assert [failure.symbol for failure in result.failures] == ["BAD"]
    assert "LoaderError" in result.failures[0].error
    assert result.scanned == 1
    assert not result.all_failed
    assert any("'BAD': skipped" in message for message in caplog.messages)


def test_all_failed_is_distinguishable_from_no_hits(fvg_touching: pd.DataFrame) -> None:
    loader = _Loader({})

    result = scan_watchlist(loader, ["A", "B"], "1h", 50, ScanOptions())

    assert result.rows == ()
    assert result.all_failed


def test_run_scan_closes_the_loader_even_when_everything_fails() -> None:
    loader = _Loader({})

    result = run_scan(loader, ["A"], "1h", 50, ScanOptions())

    assert loader.closed
    assert result.all_failed


def test_too_few_candles_is_an_error() -> None:
    with pytest.raises(ValueError, match="need at least"):
        scan_instrument("X", frame([FLAT] * 5), ScanOptions())


@pytest.mark.parametrize(
    "kwargs", [{"swing_length": 0}, {"near_atr": float("nan")}, {"near_atr": -0.1}]
)
def test_scan_options_reject_bad_values(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        ScanOptions(**kwargs)  # type: ignore[arg-type]


def test_write_csv_has_all_columns(tmp_path: Path) -> None:
    out = tmp_path / "scan.csv"
    write_csv([_row("a", "TOUCHING", 2, 0.0)], out)

    with out.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["instrument"] == "a"
    assert tuple(rows[0].keys()) == COLUMNS


def test_render_table_keeps_full_price_precision() -> None:
    console = Console(width=300, record=True)
    console.print(render_table([_row("a", "NEAR", 1, 0.25)]))

    text = console.export_text()
    assert "1.08123" in text and "1.08127" in text and "65432.1" in text and "0.25" in text


def test_render_table_marks_empty_result() -> None:
    console = Console(width=200, record=True)
    console.print(render_table([]))

    assert "no instruments" in console.export_text()


def test_rows_to_dicts_round_trips_fields() -> None:
    assert rows_to_dicts([_row("a", "NEAR", 1, 0.2)])[0]["dist_atr"] == 0.2
