"""Loaders: normalisation, CSV, demo, and MT5 through an injected fake module."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from smc_scanner.loaders import LoaderError, make_loader, normalise
from smc_scanner.loaders.csv_loader import CsvLoader
from smc_scanner.loaders.demo import MT5_RATES_DTYPE, DemoLoader, simulate_rates
from smc_scanner.loaders.mt5 import MT5_MODULE_NAME, Mt5Loader, rates_to_frame


def _raw(**overrides: list[object]) -> pd.DataFrame:
    base: dict[str, list[object]] = {
        "time": list(pd.to_datetime(["2026-01-01", "2026-01-02"])),
        "open": [1.0, 2.0],
        "high": [2.0, 3.0],
        "low": [0.5, 1.5],
        "close": [1.5, 2.5],
    }
    return pd.DataFrame({**base, **overrides})


def test_normalise_lowercases_sorts_and_fills_volume() -> None:
    raw = pd.DataFrame(
        {
            "Time": pd.to_datetime(["2026-01-02", "2026-01-01"]),
            "Open": [2, 1],
            "High": [3, 2],
            "Low": [1, 0],
            "Close": [2.5, 1.5],
        }
    )

    out = normalise(raw)

    assert list(out.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert out["open"].tolist() == [1.0, 2.0]
    assert out["volume"].tolist() == [1.0, 1.0]
    assert list(out.index) == [0, 1]


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (pd.DataFrame({"time": [], "open": []}), "missing columns"),
        (pd.DataFrame({c: [] for c in ("time", "open", "high", "low", "close")}), "no candles"),
        (_raw(close=[1.5, float("inf")]), "infinite"),
        (_raw(close=[1.5, "x"]), "non-numeric"),
        (_raw(high=[2.0, 1.0]), "high below low"),
    ],
)
def test_normalise_rejects_bad_data(frame: pd.DataFrame, message: str) -> None:
    with pytest.raises(LoaderError, match=message):
        normalise(frame)


def test_normalise_rejects_duplicate_columns_and_keeps_last_duplicate_time() -> None:
    with pytest.raises(LoaderError, match="duplicate column"):
        normalise(pd.concat([_raw(), _raw()[["close"]].rename(columns={"close": "Close"})], axis=1))

    same_time = _raw(time=list(pd.to_datetime(["2026-01-01", "2026-01-01"])))
    out = normalise(same_time)

    assert len(out) == 1
    assert out["close"].iloc[0] == 2.5


def test_csv_loader_reads_file_and_keeps_last_bars(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text(
        "time,open,high,low,close,volume\n"
        "2026-01-01T00:00:00,1,2,0,1.5,10\n"
        "2026-01-01T01:00:00,1.5,2.5,1,2,20\n"
        "2026-01-01T02:00:00,2,3,1.5,2.5,30\n"
    )

    out = CsvLoader().load(str(path), "1h", 2)

    assert len(out) == 2
    assert out["close"].tolist() == [2.0, 2.5]
    assert out["volume"].tolist() == [20.0, 30.0]


def test_csv_loader_read_all_returns_the_whole_file(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    rows = [f"2026-01-01T{h:02d}:00:00,1,2,0,{h}.5" for h in range(12)]
    path.write_text("time,open,high,low,close\n" + "\n".join(reversed(rows)) + "\n")

    whole = CsvLoader().read_all(str(path))

    assert len(whole) == 12 and whole["close"].iloc[-1] == 11.5
    assert list(whole.index) == list(range(12))
    assert CsvLoader().load(str(path), "1h", 5).equals(whole.tail(5).reset_index(drop=True))


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("missing.csv", None, "not found"),
        ("bad.csv", "open,high,low,close\n1,2,0,1\n", "time"),
        ("bad_time.csv", "time,open,high,low,close\nnot-a-date,1,2,0,1\n", "timestamps"),
        ("empty.csv", "", "cannot parse"),
    ],
)
def test_csv_loader_errors(tmp_path: Path, name: str, content: str | None, message: str) -> None:
    path = tmp_path / name
    if content is not None:
        path.write_text(content)
    with pytest.raises(LoaderError, match=message):
        CsvLoader().load(str(path), "1h", 10)


def test_demo_loader_is_deterministic_per_symbol() -> None:
    loader = DemoLoader()
    first = loader.load("EURUSD", "1h", 100)
    second = loader.load("eurusd", "1h", 100)
    other = loader.load("XAUUSD", "1h", 100)

    assert len(first) == 100
    assert first["close"].tolist() == second["close"].tolist()
    assert first["close"].tolist() != other["close"].tolist()
    assert (first["high"] >= first[["open", "close"]].max(axis=1)).all()
    assert (first["low"] <= first[["open", "close"]].min(axis=1)).all()
    with pytest.raises(LoaderError, match="timeframe"):
        loader.load("EURUSD", "2h", 10)


def test_rates_to_frame_maps_mt5_fields() -> None:
    rates = simulate_rates("EURUSD", "5m", 20, seed=1)

    out = rates_to_frame(rates)

    assert rates.dtype == MT5_RATES_DTYPE
    assert list(out.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert pd.api.types.is_datetime64_any_dtype(out["time"])
    assert out["volume"].iloc[0] == float(rates["tick_volume"][0])


class _FakeMt5:
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 16385

    def __init__(self, rates: np.ndarray | None, init_ok: bool = True) -> None:
        self.rates = rates
        self.init_ok = init_ok
        self.tick_time = int(rates["time"][-1]) + 60 if rates is not None and len(rates) else 0
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.init_kwargs: dict[str, object] = {}
        self.init_count = 0

    def initialize(self, **kwargs: object) -> bool:
        self.init_count += 1
        self.init_kwargs = kwargs
        return self.init_ok

    def shutdown(self) -> None:
        self.calls.append(("shutdown", ()))

    def last_error(self) -> tuple[int, str]:
        return (-1, "fake error")

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        return symbol != "UNKNOWN"

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(time=self.tick_time)

    def copy_rates_from_pos(
        self, symbol: str, tf: int, start: int, count: int
    ) -> np.ndarray | None:
        self.calls.append(("copy_rates_from_pos", (symbol, tf, start, count)))
        return None if self.rates is None else self.rates[-count:]


HOUR = 3600


@pytest.fixture
def fake_mt5(monkeypatch: pytest.MonkeyPatch) -> _FakeMt5:
    fake = _FakeMt5(simulate_rates("EURUSD", "1h", 40, seed=3))
    # Broker "now" is a minute after the latest bar opened, so that bar is still forming.
    fake.tick_time = _last_open(fake) + 60
    monkeypatch.setitem(sys.modules, MT5_MODULE_NAME, fake)
    return fake


def _last_open(fake: _FakeMt5) -> int:
    assert fake.rates is not None
    return int(fake.rates["time"][-1])


def test_mt5_loader_loads_and_shuts_down(fake_mt5: _FakeMt5) -> None:
    with Mt5Loader() as loader:
        out = loader.load("EURUSD", "1h", 30)

    assert len(out) == 30
    # One extra bar is requested so dropping the forming bar still leaves 30.
    assert ("copy_rates_from_pos", ("EURUSD", 16385, 0, 31)) in fake_mt5.calls
    assert ("shutdown", ()) in fake_mt5.calls


def test_mt5_loader_drops_the_forming_bar_by_default(fake_mt5: _FakeMt5) -> None:
    forming_open = pd.Timestamp(_last_open(fake_mt5), unit="s")

    out = Mt5Loader().load("EURUSD", "1h", 30)

    assert len(out) == 30
    assert out["time"].iloc[-1] == forming_open - pd.Timedelta(hours=1)


def test_mt5_loader_keeps_the_last_bar_once_it_has_closed(fake_mt5: _FakeMt5) -> None:
    fake_mt5.tick_time = _last_open(fake_mt5) + HOUR  # the next period has begun

    out = Mt5Loader().load("EURUSD", "1h", 30)

    assert len(out) == 30
    assert out["time"].iloc[-1] == pd.Timestamp(_last_open(fake_mt5), unit="s")


def test_mt5_loader_treats_the_last_bar_as_forming_when_tick_time_is_unknown(
    fake_mt5: _FakeMt5,
) -> None:
    fake_mt5.tick_time = 0
    forming_open = pd.Timestamp(_last_open(fake_mt5), unit="s")

    out = Mt5Loader().load("EURUSD", "1h", 30)

    assert out["time"].iloc[-1] == forming_open - pd.Timedelta(hours=1)


def test_mt5_loader_bars_1_returns_the_last_closed_bar(fake_mt5: _FakeMt5) -> None:
    out = Mt5Loader().load("EURUSD", "1h", 1)

    assert len(out) == 1
    assert out["time"].iloc[-1] == pd.Timestamp(_last_open(fake_mt5) - HOUR, unit="s")


def test_mt5_loader_errors_when_only_a_forming_bar_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMt5(simulate_rates("EURUSD", "1h", 1, seed=3))
    fake.tick_time = _last_open(fake) + 60
    monkeypatch.setitem(sys.modules, MT5_MODULE_NAME, fake)

    with pytest.raises(LoaderError, match="no closed candles"):
        Mt5Loader().load("EURUSD", "1h", 5)


def test_mt5_loader_can_include_the_forming_bar(fake_mt5: _FakeMt5) -> None:
    out = Mt5Loader(closed_only=False).load("EURUSD", "1h", 30)

    assert len(out) == 30
    assert out["time"].iloc[-1] == pd.Timestamp(_last_open(fake_mt5), unit="s")
    assert ("copy_rates_from_pos", ("EURUSD", 16385, 0, 30)) in fake_mt5.calls


def test_make_loader_passes_closed_only_to_mt5() -> None:
    loader = make_loader("mt5", closed_only=False)

    assert isinstance(loader, Mt5Loader)
    assert loader.closed_only is False


def test_mt5_loader_reads_login_from_environment(
    fake_mt5: _FakeMt5, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MT5_LOGIN", "12345")
    monkeypatch.setenv("MT5_PASSWORD", "x")
    monkeypatch.setenv("MT5_SERVER", "Demo")
    monkeypatch.setenv("MT5_PATH", "C:/mt5/terminal64.exe")

    Mt5Loader().connect()

    assert fake_mt5.init_kwargs == {
        "path": "C:/mt5/terminal64.exe",
        "login": 12345,
        "password": "x",
        "server": "Demo",
    }


def test_mt5_loader_rejects_non_integer_login(
    fake_mt5: _FakeMt5, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MT5_LOGIN", "abc")
    with pytest.raises(LoaderError, match="integer"):
        Mt5Loader().connect()


def test_mt5_loader_symbol_and_timeframe_errors(fake_mt5: _FakeMt5) -> None:
    with pytest.raises(LoaderError, match="unknown symbol"):
        Mt5Loader().load("UNKNOWN", "1h", 10)
    with pytest.raises(LoaderError, match="unsupported timeframe"):
        Mt5Loader().load("EURUSD", "2h", 10)


def test_mt5_loader_no_candles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, MT5_MODULE_NAME, _FakeMt5(None))
    with pytest.raises(LoaderError, match="no candles"):
        Mt5Loader().load("EURUSD", "1h", 10)


def test_mt5_loader_failed_initialize_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeMt5(None, init_ok=False)
    monkeypatch.setitem(sys.modules, MT5_MODULE_NAME, fake)
    loader = Mt5Loader()

    for _ in range(3):
        with pytest.raises(LoaderError, match="initialize failed"):
            loader.load("EURUSD", "1h", 10)

    assert fake.init_count == 1


def test_mt5_loader_warns_when_last_bar_is_far_behind_last_tick(
    fake_mt5: _FakeMt5, caplog: pytest.LogCaptureFixture
) -> None:
    fake_mt5.tick_time += 3 * 24 * 3600  # weekend: ticks resumed days after the last bar

    Mt5Loader().load("EURUSD", "1h", 30)

    assert any("market may be closed" in message for message in caplog.messages)


def test_mt5_loader_is_quiet_when_bar_is_current(
    fake_mt5: _FakeMt5, caplog: pytest.LogCaptureFixture
) -> None:
    Mt5Loader().load("EURUSD", "1h", 30)

    assert not any("market may be closed" in message for message in caplog.messages)


def test_make_loader_picks_by_name() -> None:
    assert isinstance(make_loader("csv"), CsvLoader)
    assert isinstance(make_loader("demo"), DemoLoader)
    assert isinstance(make_loader("mt5"), Mt5Loader)
    with pytest.raises(LoaderError, match="unknown source"):
        make_loader("oanda")
