"""The in-repo FVG detector against ``smc.fvg``: same columns, same zones, same replay signals."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_scanner import zones
from smc_scanner.backtest.replay import Signal, replay
from smc_scanner.config import DEFAULT_DEMO_SYMBOLS, TIMEFRAMES
from smc_scanner.loaders.csv_loader import CsvLoader
from smc_scanner.loaders.demo import DemoLoader
from smc_scanner.models import BEARISH, BULLISH, Zone
from smc_scanner.smc_lib import smc
from smc_scanner.strategy.builtin import SMC_DEFAULT
from smc_scanner.zones import FVG_TOUCH_OFFSET, detect_fvgs, fvg_frame

COLUMNS = ["FVG", "Top", "Bottom"]
DEMO_BARS = 2000
REPLAY_BARS = 600
# Real GBPUSD 1h candles (Dukascopy mid, 2022, broker clock GMT+2 EU-DST) via smc-resample-ticks.
SAMPLE_CSV = Path(__file__).parent / "fixtures" / "GBPUSD_1h_sample.csv"
SAMPLE_BARS = 3000
RANDOM_SEEDS = range(20)
RANDOM_LENGTHS = (0, 1, 2, 3, 4, 50, 500)


def _reference_detect_fvgs(ohlc: pd.DataFrame) -> list[Zone]:
    """``detect_fvgs`` as it was before TRAD-48, still calling ``smc.fvg``."""
    frame = smc.fvg(ohlc)
    last_index = len(ohlc) - 1
    found: list[Zone] = []
    for index, flag, top, bottom in zip(
        frame.index,
        frame["FVG"].to_numpy(),
        frame["Top"].to_numpy(),
        frame["Bottom"].to_numpy(),
        strict=True,
    ):
        if np.isnan(flag):
            continue
        formed = int(index)
        if formed + 1 >= last_index:
            continue
        found.append(
            Zone(
                kind="FVG",
                direction=BULLISH if int(flag) == 1 else BEARISH,
                top=float(top),
                bottom=float(bottom),
                formed_index=formed,
                touch_start=formed + FVG_TOUCH_OFFSET,
            )
        )
    return found


def _assert_columns_match_library(ohlc: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(fvg_frame(ohlc), smc.fvg(ohlc)[COLUMNS], check_exact=True)


@pytest.fixture(scope="module")
def demo_frames() -> list[tuple[str, str, pd.DataFrame]]:
    loader = DemoLoader()
    return [
        (symbol, timeframe, loader.load(symbol, timeframe, DEMO_BARS))
        for symbol in DEFAULT_DEMO_SYMBOLS
        for timeframe in TIMEFRAMES
    ]


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return CsvLoader().load(str(SAMPLE_CSV), "1h", SAMPLE_BARS)


def _random_frame(rng: np.random.Generator, length: int) -> pd.DataFrame:
    """Coarse prices (2 decimals, small range) so ties, dojis and touching gaps are common."""
    open_ = np.round(rng.uniform(99.0, 101.0, length), 2)
    moved = np.round(rng.uniform(99.0, 101.0, length), 2)
    close = np.where(rng.random(length) < 0.15, open_, moved)
    high = np.maximum(open_, close) + np.round(rng.uniform(0.0, 0.3, length), 2)
    low = np.minimum(open_, close) - np.round(rng.uniform(0.0, 0.3, length), 2)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


def test_demo_columns_match_library(demo_frames: list[tuple[str, str, pd.DataFrame]]) -> None:
    flags = []
    for symbol, timeframe, ohlc in demo_frames:
        try:
            _assert_columns_match_library(ohlc)
        except AssertionError as exc:
            raise AssertionError(f"{symbol} {timeframe}: {exc}") from exc
        flags.append(fvg_frame(ohlc)["FVG"])
    counts = pd.concat(flags).value_counts()
    assert counts.get(1.0, 0) > 0 and counts.get(-1.0, 0) > 0  # both directions exercised


def test_sample_columns_match_library(sample: pd.DataFrame) -> None:
    assert len(sample) == SAMPLE_BARS
    _assert_columns_match_library(sample)
    counts = fvg_frame(sample)["FVG"].value_counts()
    assert counts.get(1.0, 0) > 0 and counts.get(-1.0, 0) > 0


@pytest.mark.parametrize("length", RANDOM_LENGTHS)
@pytest.mark.parametrize("seed", RANDOM_SEEDS)
def test_random_columns_match_library(seed: int, length: int) -> None:
    _assert_columns_match_library(_random_frame(np.random.default_rng(seed), length))


def test_random_frames_include_ties_and_both_directions() -> None:
    """Guards the generator: the property test above must see the edge cases it targets."""
    ohlc = _random_frame(np.random.default_rng(0), 500)
    flags = fvg_frame(ohlc)["FVG"]
    assert (ohlc["close"] == ohlc["open"]).any()
    assert (ohlc["high"].shift(1) == ohlc["low"].shift(-1)).any()
    assert (flags == 1.0).any() and (flags == -1.0).any()


def test_demo_zones_match_reference(demo_frames: list[tuple[str, str, pd.DataFrame]]) -> None:
    for symbol, timeframe, ohlc in demo_frames:
        assert detect_fvgs(ohlc) == _reference_detect_fvgs(ohlc), f"{symbol} {timeframe}"


@pytest.mark.parametrize("length", range(5))
@pytest.mark.parametrize("seed", RANDOM_SEEDS)
def test_random_short_zones_match_reference(seed: int, length: int) -> None:
    """Very short frames, down to empty (``last_index`` of -1)."""
    ohlc = _random_frame(np.random.default_rng(seed), length)
    assert detect_fvgs(ohlc) == _reference_detect_fvgs(ohlc)


def test_sample_zones_match_reference(sample: pd.DataFrame) -> None:
    found = detect_fvgs(sample)
    assert found  # the real sample has gaps
    assert found == _reference_detect_fvgs(sample)


def test_replay_signals_match_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stride-1 replay is unchanged. 600 bars keep the slow library reference affordable;
    1500 bars (and 5000 at stride 10) were verified once during TRAD-48 with identical signals.
    """
    ohlc = DemoLoader().load("EURUSD", "1h", REPLAY_BARS)
    with monkeypatch.context() as patch:
        patch.setattr(zones, "detect_fvgs", _reference_detect_fvgs)
        expected: tuple[Signal, ...] = replay("EURUSD", ohlc, SMC_DEFAULT)

    signals = replay("EURUSD", ohlc, SMC_DEFAULT)

    assert any(signal.zone.kind == "FVG" for signal in expected)
    assert signals == expected
