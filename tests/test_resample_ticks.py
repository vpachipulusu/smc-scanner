"""Tick resampler: OHLC, tick counts and spread per candle from small synthetic tick files."""

import dataclasses
import logging
import zipfile
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_scanner.config import MIN_BARS, TIMEFRAMES
from smc_scanner.data.resample_ticks import (
    OUTPUT_COLUMNS,
    ResampleError,
    ResampleOptions,
    build_parser,
    default_symbol,
    main,
    resample,
)
from smc_scanner.loaders.csv_loader import CsvLoader
from smc_scanner.scanner import ScanOptions, scan_instrument

# Two 5m candles at 10:00 and 10:05 inside the 10:00 hour, then one tick in the 11:00 hour.
TICKS: list[str] = [
    "2024.01.02 10:00:00.100,1.10000,1.10020",  # mid 1.10010, spread 0.00020
    "2024.01.02 10:01:30.000,1.10050,1.10060",  # mid 1.10055, spread 0.00010
    "2024.01.02 10:03:00.000,1.09980,1.10000",  # mid 1.09990, spread 0.00020
    "2024.01.02 10:04:59.999,1.10010,1.10030",  # mid 1.10020, spread 0.00020
    "2024.01.02 10:05:00.000,1.10100,1.10110",  # mid 1.10105, spread 0.00010
    "2024.01.02 10:09:00.000,1.10070,1.10090",  # mid 1.10080, spread 0.00020
    "2024.01.02 11:00:00.000,1.10200,1.10220",  # mid 1.10210, spread 0.00020
]


def _write(path: Path, lines: Sequence[str]) -> Path:
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii", newline="")  # as exported
    return path


def _zip(tmp_path: Path, lines: Sequence[str], member: str = "EURUSD_GMT+2_EU-DST.csv") -> Path:
    path = tmp_path / "EURUSD_GMT+2_EU-DST.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "\r\n".join(lines) + "\r\n")
    return path


def _ticks_file(tmp_path: Path, lines: Sequence[str] = TICKS) -> Path:
    return _write(tmp_path / "EURUSD_GMT+2_EU-DST.csv", lines)


def _run(source: Path, out: Path, *extra: str) -> int:
    return main([str(source), "--out", str(out), *extra])


def _read(out: Path, timeframe: str, symbol: str = "EURUSD") -> pd.DataFrame:
    return pd.read_csv(out / f"{symbol}_{timeframe}.csv")


def test_five_minute_mid_candles_match_hand_computed_values(tmp_path: Path) -> None:
    out = tmp_path / "out"

    code = _run(_ticks_file(tmp_path), out, "--timeframes", "5m")

    assert code == 0
    frame = _read(out, "5m")
    assert list(frame.columns) == list(OUTPUT_COLUMNS)
    assert frame["time"].tolist() == [
        "2024-01-02T10:00:00",
        "2024-01-02T10:05:00",
        "2024-01-02T11:00:00",
    ]
    assert frame["open"].tolist() == pytest.approx([1.10010, 1.10105, 1.10210])
    assert frame["high"].tolist() == pytest.approx([1.10055, 1.10105, 1.10210])
    assert frame["low"].tolist() == pytest.approx([1.09990, 1.10080, 1.10210])
    assert frame["close"].tolist() == pytest.approx([1.10020, 1.10080, 1.10210])
    assert frame["volume"].tolist() == [4, 2, 1]
    assert frame["spread"].tolist() == pytest.approx([0.000175, 0.00015, 0.0002])


def test_one_hour_candles_from_a_zip_member(tmp_path: Path) -> None:
    out = tmp_path / "out"

    code = _run(_zip(tmp_path, TICKS), out, "--timeframes", "1h")

    assert code == 0
    frame = _read(out, "1h")
    assert frame["time"].tolist() == ["2024-01-02T10:00:00", "2024-01-02T11:00:00"]
    assert frame["open"].tolist() == pytest.approx([1.10010, 1.10210])
    assert frame["high"].tolist() == pytest.approx([1.10105, 1.10210])
    assert frame["low"].tolist() == pytest.approx([1.09990, 1.10210])
    assert frame["close"].tolist() == pytest.approx([1.10080, 1.10210])
    assert frame["volume"].tolist() == [6, 1]
    assert frame["spread"].tolist() == pytest.approx([0.0010 / 6, 0.0002], abs=1e-6)


def test_bar_time_is_the_bar_open_for_every_timeframe(tmp_path: Path) -> None:
    out = tmp_path / "out"
    lines = ["2024.01.02 13:47:12.345,1.20000,1.20010"]

    _run(_ticks_file(tmp_path, lines), out)

    expected = {
        "5m": "2024-01-02T13:45:00",
        "15m": "2024-01-02T13:45:00",
        "30m": "2024-01-02T13:30:00",
        "1h": "2024-01-02T13:00:00",
        "4h": "2024-01-02T12:00:00",
        "1d": "2024-01-02T00:00:00",
    }
    for timeframe, bar_open in expected.items():
        assert _read(out, timeframe)["time"].tolist() == [bar_open]


def test_bid_price_builds_candles_from_bid_only(tmp_path: Path) -> None:
    out = tmp_path / "out"

    _run(_ticks_file(tmp_path), out, "--timeframes", "1h", "--price", "bid")

    first = _read(out, "1h").iloc[0]
    assert (first["open"], first["high"], first["low"], first["close"]) == pytest.approx(
        (1.10000, 1.10100, 1.09980, 1.10070)
    )
    assert first["spread"] == pytest.approx(0.0010 / 6, abs=1e-6)


def test_prices_are_rounded_to_the_input_precision(tmp_path: Path) -> None:
    out = tmp_path / "out"
    lines = ["2024.01.02 10:00:00.000,150.123,150.126", "2024.01.02 10:01:00.000,150.124,150.125"]

    _run(_ticks_file(tmp_path, lines), out, "--timeframes", "5m", "--price", "bid")
    _run(_ticks_file(tmp_path, lines), tmp_path / "mid", "--timeframes", "5m")

    raw = (out / "EURUSD_5m.csv").read_text(encoding="ascii").splitlines()
    assert raw[1] == "2024-01-02T10:00:00,150.123,150.124,150.123,150.124,2,0.00200"
    mid = (tmp_path / "mid" / "EURUSD_5m.csv").read_text(encoding="ascii").splitlines()
    assert mid[1] == "2024-01-02T10:00:00,150.1245,150.1245,150.1245,150.1245,2,0.00200"


@pytest.mark.parametrize("chunk_rows", ["1", "2", "3"])
def test_candles_spanning_chunks_are_stitched(tmp_path: Path, chunk_rows: str) -> None:
    source = _ticks_file(tmp_path)
    whole, chunked = tmp_path / "whole", tmp_path / "chunked"

    _run(source, whole, "--timeframes", "5m,1h")
    code = _run(source, chunked, "--timeframes", "5m,1h", "--chunk-rows", chunk_rows)

    assert code == 0
    for timeframe in ("5m", "1h"):
        pd.testing.assert_frame_equal(_read(chunked, timeframe), _read(whole, timeframe))


def test_weekend_gap_produces_no_empty_candles(tmp_path: Path) -> None:
    out = tmp_path / "out"
    lines = ["2024.01.05 23:59:59.000,1.1,1.1002", "2024.01.08 00:00:01.000,1.1010,1.1012"]

    _run(_ticks_file(tmp_path, lines), out, "--timeframes", "1h,1d")

    assert _read(out, "1h")["time"].tolist() == ["2024-01-05T23:00:00", "2024-01-08T00:00:00"]
    assert _read(out, "1d")["time"].tolist() == ["2024-01-05T00:00:00", "2024-01-08T00:00:00"]


def test_from_drops_ticks_before_the_date(tmp_path: Path) -> None:
    out = tmp_path / "out"
    lines = ["2024.01.01 23:59:59.999,1.1,1.1002", *TICKS]

    _run(_ticks_file(tmp_path, lines), out, "--timeframes", "1d", "--from", "2024-01-02")

    frame = _read(out, "1d")
    assert frame["time"].tolist() == ["2024-01-02T00:00:00"]
    assert frame["volume"].tolist() == [len(TICKS)]


@pytest.mark.parametrize(
    "bad_line",
    [
        "garbage",
        "2024.01.02 10:02:00.000,1.10000",  # a missing field
        "2024.01.02 10:02:00.000,1.1,1.2,9",  # one extra field
        "2024.01.02 10:02:00.000,1.1,1.2,9,9,9",  # several extra fields
        "2024.13.02 10:02:00.000,1.1,1.2",  # impossible date
        "2024.01.02 10:02:00.000,abc,1.2",  # a price that is not a number
        "2024.01.02 10:02:00.000,0,0",  # no price
        "2024.01.02 10:02:00.000,1.2,1.1",  # ask below bid
        "",  # a blank line
        "2024.01.02 09:00:00.000,1.1,1.2",  # older than the tick before it
    ],
)
def test_malformed_line_is_skipped_counted_and_fails_the_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, bad_line: str
) -> None:
    out = tmp_path / "out"
    lines = [*TICKS[:3], bad_line, *TICKS[3:]]

    with caplog.at_level(logging.WARNING):
        code = _run(_ticks_file(tmp_path, lines), out, "--timeframes", "5m", "--chunk-rows", "2")

    assert code == 1  # 1 of 8 lines is far above the 0.01% limit
    assert "line 4" in caplog.text
    assert "1 of 8 lines skipped" in caplog.text
    assert _read(out, "5m")["volume"].tolist() == [4, 2, 1]


def test_lines_after_a_wide_bad_line_keep_their_line_numbers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lines = [TICKS[0], "x,1,2,3,4,5", TICKS[1], "2024.01.02 10:02:00.000,nope,1", *TICKS[2:]]

    with caplog.at_level(logging.WARNING):
        _run(_ticks_file(tmp_path, lines), tmp_path / "out", "--chunk-rows", "1")

    assert "line 2:" in caplog.text
    assert "line 4:" in caplog.text
    assert "2 of 9 lines skipped" in caplog.text


def test_a_rare_malformed_line_does_not_fail_the_run(tmp_path: Path) -> None:
    times = pd.date_range("2024-01-02", periods=20_000, freq="1s")
    lines = [f"{t:%Y.%m.%d %H:%M:%S}.000,1.10000,1.10010" for t in times]
    lines.insert(500, "broken")

    code = _run(_ticks_file(tmp_path, lines), tmp_path / "out", "--timeframes", "1d")

    assert code == 0
    assert _read(tmp_path / "out", "1d")["volume"].tolist() == [20_000]


def test_unknown_timeframe_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(_ticks_file(tmp_path), tmp_path / "out", "--timeframes", "1h,2h")

    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--chunk-rows", "0"],
        ["--chunk-rows", "many"],
        ["--from", "2024-13-01"],
        ["--symbol", "../evil"],
        ["--symbol", ""],
        ["--timeframes", ","],
        ["--price", "ask"],
    ],
)
def test_invalid_options_are_rejected(tmp_path: Path, extra: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(_ticks_file(tmp_path), tmp_path / "out", *extra)

    assert exit_info.value.code == 2


def test_duplicate_timeframes_are_written_once(tmp_path: Path) -> None:
    options = _options(_ticks_file(tmp_path), tmp_path / "out")
    args = build_parser().parse_args(["x.csv", "--out", "o", "--timeframes", "1h,5m,1h"])

    assert ResampleOptions.from_args(args).timeframes == ("1h", "5m")
    assert options.timeframes == ("5m", "15m", "30m", "1h", "4h", "1d")


def test_refuses_to_overwrite_without_force(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "EURUSD_1h.csv"
    existing.write_text("keep me", encoding="ascii")

    with caplog.at_level(logging.ERROR):
        code = _run(_ticks_file(tmp_path), out, "--timeframes", "5m,1h")

    assert code == 1
    assert existing.read_text(encoding="ascii") == "keep me"
    assert not (out / "EURUSD_5m.csv").exists()
    assert "--force" in caplog.text

    assert _run(_ticks_file(tmp_path), out, "--timeframes", "5m,1h", "--force") == 0
    assert _read(out, "1h")["volume"].tolist() == [6, 1]


def test_symbol_defaults_to_the_file_name_before_the_first_underscore() -> None:
    assert default_symbol(Path("GBPUSD_GMT+2_EU-DST.zip")) == "GBPUSD"
    assert default_symbol(Path("XAUUSD.csv")) == "XAUUSD"


def test_symbol_override_names_the_output(tmp_path: Path) -> None:
    out = tmp_path / "out"

    _run(_ticks_file(tmp_path), out, "--timeframes", "1h", "--symbol", "EURUSD.x")

    assert (out / "EURUSD.x_1h.csv").is_file()


def test_a_symbol_from_an_unusable_file_name_is_refused(tmp_path: Path) -> None:
    source = _write(tmp_path / "_ticks.csv", TICKS)

    with pytest.raises(SystemExit) as exit_info:
        _run(source, tmp_path / "out")

    assert exit_info.value.code == 2


@pytest.mark.parametrize(
    ("members", "message"),
    [([], "no CSV member"), (["a.csv", "b.csv"], "2 CSV members")],
)
def test_zip_must_hold_exactly_one_csv(tmp_path: Path, members: list[str], message: str) -> None:
    path = tmp_path / "EURUSD.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "hello")
        for member in members:
            archive.writestr(member, "\r\n".join(TICKS))

    with pytest.raises(ResampleError, match=message):
        resample(_options(path, tmp_path / "out"))


def test_zip_member_name_is_never_used_as_a_path(tmp_path: Path) -> None:
    out = tmp_path / "out"

    code = _run(_zip(tmp_path, TICKS, member="../../escape.csv"), out, "--timeframes", "1h")

    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == ["EURUSD_1h.csv"]
    assert not (tmp_path.parent / "escape.csv").exists()


def test_not_a_zip_or_missing_file_fails_cleanly(tmp_path: Path) -> None:
    fake = tmp_path / "EURUSD.zip"
    fake.write_text("not a zip", encoding="ascii")

    assert _run(fake, tmp_path / "out") == 1
    assert _run(tmp_path / "EURUSD_missing.csv", tmp_path / "out") == 1


def test_no_ticks_after_filtering_fails_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"

    code = _run(_ticks_file(tmp_path), out, "--from", "2030-01-01")

    assert code == 1
    assert not out.exists() or list(out.iterdir()) == []


def test_an_empty_file_fails_and_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "EURUSD.csv"
    source.write_text("", encoding="ascii")

    assert _run(source, tmp_path / "out") == 1
    assert not (tmp_path / "out" / "EURUSD_1h.csv").exists()


def _options(source: Path, out: Path, timeframes: tuple[str, ...] = TIMEFRAMES) -> ResampleOptions:
    args = build_parser().parse_args([str(source), "--out", str(out)])
    return dataclasses.replace(ResampleOptions.from_args(args), timeframes=timeframes)


def test_resample_reports_lines_and_candles(tmp_path: Path) -> None:
    options = _options(_ticks_file(tmp_path), tmp_path / "out", timeframes=("5m", "1h"))

    report = resample(options)

    assert report.lines == len(TICKS)
    assert report.skipped == 0
    assert report.candles == {"5m": 3, "1h": 2}


def _random_walk_ticks(hours: int) -> list[str]:
    rng = np.random.default_rng(7)
    times = pd.date_range("2024-01-01", periods=hours * 6, freq="10min")
    bids = 1.25 + np.cumsum(rng.normal(0, 0.0008, len(times)))
    return [
        f"{t:%Y.%m.%d %H:%M:%S}.000,{b:.5f},{b + 0.00012:.5f}"
        for t, b in zip(times, bids, strict=True)
    ]


def test_output_loads_through_csv_loader_and_scans(tmp_path: Path) -> None:
    out = tmp_path / "out"
    hours = 20 * MIN_BARS
    _run(_ticks_file(tmp_path, _random_walk_ticks(hours)), out, "--timeframes", "1h")

    frame = CsvLoader().load(str(out / "EURUSD_1h.csv"), "1h", 5000)

    assert len(frame) == hours
    assert list(frame.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert (frame["volume"] == 6).all()
    assert isinstance(scan_instrument("EURUSD", frame, ScanOptions()), list)


def test_a_leftover_part_file_is_replaced_not_appended(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "EURUSD_1h.csv.part").write_text("stale\n", encoding="ascii")

    assert _run(_ticks_file(tmp_path), out, "--timeframes", "1h") == 0

    assert _read(out, "1h")["volume"].tolist() == [6, 1]
    assert not (out / "EURUSD_1h.csv.part").exists()


def test_the_input_is_never_overwritten_even_with_force(tmp_path: Path) -> None:
    source = _write(tmp_path / "EURUSD_1h.csv", TICKS)

    code = _run(source, tmp_path, "--timeframes", "1h", "--force")

    assert code == 1
    assert source.read_text(encoding="ascii").startswith("2024.01.02 10:00:00.100")


@pytest.mark.parametrize("first_line", ["x,1,2,3,4", "x,1,2,3,4,5", "time,bid,ask"])
def test_a_bad_first_line_is_skipped_like_any_other(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, first_line: str
) -> None:
    out = tmp_path / "out"

    with caplog.at_level(logging.WARNING):
        code = _run(_ticks_file(tmp_path, [first_line, *TICKS]), out, "--timeframes", "5m")

    assert code == 1
    assert "line 1:" in caplog.text
    assert _read(out, "5m")["volume"].tolist() == [4, 2, 1]


def test_many_bad_lines_are_numbered_across_chunks_and_logging_is_capped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lines = list(TICKS)
    for line in (2, 4, 5):  # 1-based positions in the final file
        lines.insert(line - 1, "x,1,2,3,4,5" if line == 4 else "junk")
    lines += ["junk"] * 60

    with caplog.at_level(logging.WARNING):
        _run(_ticks_file(tmp_path, lines), tmp_path / "out", "--chunk-rows", "2")

    assert all(f"line {n}:" in caplog.text for n in (2, 4, 5, 11))
    assert "further skipped lines are counted but not logged" in caplog.text
    assert "line 70:" not in caplog.text
    assert "63 of 70 lines skipped" in caplog.text


def test_a_corrupt_future_timestamp_stops_the_run_early(tmp_path: Path) -> None:
    times = pd.date_range("2024-01-02", periods=120_000, freq="1s")
    lines = ["2030.01.01 00:00:00.000,1.1,1.1001"]
    lines += [f"{t:%Y.%m.%d %H:%M:%S}.000,1.10000,1.10010" for t in times]
    out = tmp_path / "out"

    code = _run(_ticks_file(tmp_path, lines), out, "--timeframes", "1h", "--chunk-rows", "50000")

    assert code == 1
    assert list(out.iterdir()) == []


def test_corrupt_zip_data_fails_cleanly_and_leaves_no_files(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    lines = [f"2024.01.02 10:{m:02d}:00.000,{1 + rng.random():.5f},2.00000" for m in range(60)]
    path = _zip(tmp_path, lines * 200)
    data = bytearray(path.read_bytes())
    middle = len(data) // 2
    data[middle : middle + 64] = bytes(64)
    path.write_bytes(bytes(data))
    out = tmp_path / "out"

    assert _run(path, out, "--timeframes", "1h") == 1
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"timeframes": ("2h",)}, "timeframes"),
        ({"timeframes": ()}, "timeframes"),
        ({"price": "ask"}, "price"),
    ],
)
def test_options_reject_bad_values_when_built_directly(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    base = _options(_ticks_file(tmp_path), tmp_path / "out")

    with pytest.raises(ValueError, match=message):
        dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def test_too_many_wide_lines_stop_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("smc_scanner.data.resample_ticks.MAX_WIDE_LINES", 2)
    lines = [*TICKS, *(["x,1,2,3,4,5"] * 3)]
    out = tmp_path / "out"

    assert _run(_ticks_file(tmp_path, lines), out, "--timeframes", "1h") == 1
    assert list(out.iterdir()) == []
