"""CLI and FastAPI wiring using the demo source (no terminal, no keys)."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_scanner.api import app
from smc_scanner.cli import build_parser, main, resolve_symbols
from smc_scanner.loaders.mt5 import MT5_MODULE_NAME
from smc_scanner.watchlist import WatchlistError, load_watchlist, symbols_for
from smc_scanner.watchlist import resolve_symbols as from_file


def test_demo_scan_writes_csv_with_rows(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "scan.csv"

    code = main(["--demo", "--symbols", "EURUSD", "XAUUSD", "--bars", "300", "--out", str(out)])

    assert code == 0
    lines = out.read_text().splitlines()
    assert lines[0].startswith("instrument,status,zone")
    assert len(lines) >= 2  # seeded demo data has at least one hit at 300 bars
    assert not any("skipped" in message for message in caplog.messages)


@pytest.mark.parametrize(
    "argv",
    [
        ["--demo", "--bars", "0"],
        ["--demo", "--bars", "10"],
        ["--demo", "--every", "0"],
        ["--demo", "--near", "nan"],
        ["--demo", "--near", "-1"],
        ["--demo", "--swing", "0"],
    ],
)
def test_cli_rejects_bad_numbers(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(argv)


def test_missing_watchlist_is_an_error_for_non_demo(tmp_path: Path) -> None:
    code = main(["--source", "csv", "--watchlist", str(tmp_path / "none.yaml")])

    assert code == 1


def test_all_symbols_failing_exits_1_and_keeps_previous_csv(tmp_path: Path) -> None:
    out = tmp_path / "scan.csv"
    out.write_text("previous results\n")

    code = main(["--source", "csv", "--symbols", str(tmp_path / "missing.csv"), "--out", str(out)])

    assert code == 1
    assert out.read_text() == "previous results\n"


def test_unwritable_csv_is_reported_not_raised(tmp_path: Path) -> None:
    code = main(["--demo", "--symbols", "EURUSD", "--out", str(tmp_path / "no_dir" / "x.csv")])

    assert code == 1


def test_demo_falls_back_to_default_symbols(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--demo", "--watchlist", str(tmp_path / "none.yaml")])

    assert "EURUSD" in resolve_symbols(args, "demo")


def test_every_loop_scans_then_stops_on_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    def interrupt(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr("smc_scanner.cli.time.sleep", interrupt)
    out = tmp_path / "o.csv"

    code = main(["--demo", "--symbols", "EURUSD", "--every", "2", "--out", str(out)])

    assert code == 0
    assert sleeps == [120]
    assert out.is_file()


def test_watchlist_parsing(tmp_path: Path) -> None:
    path = tmp_path / "w.yaml"
    path.write_text("mt5: [EURUSD, ' XAUUSD ']\ncsv: []\n")

    watchlist = load_watchlist(path)

    assert symbols_for(watchlist, "mt5") == ["EURUSD", "XAUUSD"]
    with pytest.raises(WatchlistError, match="no symbols"):
        symbols_for(watchlist, "csv")
    assert from_file(path, "demo") == ["EURUSD", "XAUUSD", "NAS100", "UK100", "BTCUSD"]
    assert from_file(path, "mt5") == ["EURUSD", "XAUUSD"]


def test_watchlist_rejects_unknown_source_and_bad_shape(tmp_path: Path) -> None:
    bad_source = tmp_path / "a.yaml"
    bad_source.write_text("oanda: [EUR_USD]\n")
    with pytest.raises(WatchlistError, match="unknown source"):
        load_watchlist(bad_source)
    bad_shape = tmp_path / "b.yaml"
    bad_shape.write_text("- EURUSD\n")
    with pytest.raises(WatchlistError, match="mapping"):
        load_watchlist(bad_shape)
    bad_yaml = tmp_path / "c.yaml"
    bad_yaml.write_text("mt5: [EURUSD\n")
    with pytest.raises(WatchlistError, match="invalid YAML"):
        load_watchlist(bad_yaml)


client = TestClient(app, base_url="http://localhost")


def test_health() -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_untrusted_host_is_rejected() -> None:
    assert TestClient(app, base_url="http://evil.example").get("/health").status_code == 400


def test_scan_endpoint_with_demo_source() -> None:
    params = {"source": "demo", "symbols": "EURUSD,BTCUSD", "bars": 300}
    response = client.get("/scan", params=params)

    body = response.json()
    assert response.status_code == 200
    assert body["source"] == "demo"
    assert body["failures"] == []
    assert body["count"] == len(body["rows"]) >= 1
    for row in body["rows"]:
        assert row["status"] in {"TOUCHING", "NEAR"}
        assert 0 <= row["score"] <= 4


@pytest.mark.parametrize(
    "params",
    [
        {"source": "oanda"},
        {"source": "csv", "symbols": "C:/Windows/win.ini"},
        {"source": "demo", "bars": 5},
        {"source": "demo", "symbols": "../../etc/passwd"},
        {"source": "demo", "symbols": r"\\attacker\share\x.csv"},
        {"source": "demo", "symbols": ",".join(f"S{i}" for i in range(60))},
        {"source": "demo", "symbols": "A" * 1001},
    ],
)
def test_scan_endpoint_validates_parameters(params: dict[str, object]) -> None:
    assert client.get("/scan", params=params).status_code == 422


def test_scan_endpoint_returns_503_when_nothing_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Down:
        def initialize(self, **_: object) -> bool:
            return False

        def last_error(self) -> tuple[int, str]:
            return (-10005, "IPC timeout")

    monkeypatch.setitem(sys.modules, MT5_MODULE_NAME, _Down())

    response = client.get("/scan", params={"source": "mt5", "symbols": "EURUSD"})

    assert response.status_code == 503
    assert "IPC timeout" not in response.text  # internals stay in the server log
