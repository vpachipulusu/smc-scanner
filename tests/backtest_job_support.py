"""A fake walk-forward runner and stats shared by the backtest job, CLI and API tests."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from smc_scanner.backtest.jobs import SplitSpec
from smc_scanner.backtest.outcome import ExitRules
from smc_scanner.loaders.base import Loader
from smc_scanner.strategy.models import Strategy

SECRET = "C:/secret/path boom"


def stats(n: int = 40, expectancy: float = 0.25, **overrides: Any) -> dict[str, Any]:
    """A ``BacktestStats``-shaped dict, as ``to_dict()`` gives it."""
    base: dict[str, Any] = {
        "n": n,
        "n_open": 1,
        "n_void": 2,
        "low_sample": n < 30,
        "hit_rate": 0.45,
        "average_r": expectancy,
        "expectancy_r": expectancy,
        "median_r": -1.0,
        "best_r": 2.0,
        "worst_r": -1.2,
        "total_r": expectancy * n,
        "profit_factor": 1.4,
        "max_drawdown_r": 5.5,
        "avg_bars_held": 12.0,
        "ci_low": expectancy - 0.2,
        "ci_high": expectancy + 0.2,
    }
    return {**base, **overrides}


@dataclass
class FakeResult:
    verdict: str = "pass"
    in_sample: object = None
    out_of_sample: object = None
    baselines: object = None

    def to_dict(self) -> dict[str, Any]:
        """The shape of ``walkforward.WalkForwardResult.to_dict()`` (TRAD-44)."""
        return {
            "timeframe": "1h",
            "split": "time",
            "train_fraction": 0.6,
            "verdict": self.verdict,
            "in_sample": stats(n=40, expectancy=0.3),
            "out_of_sample": stats(n=20, expectancy=0.2),
            "random_baseline": stats(expectancy=-0.1),
            "flipped_baseline": stats(expectancy=-0.3),
            "windows": [{"symbol": "EURUSD", "boundary": 120}],
            "failures": [{"symbol": "BAD", "error": f"LoaderError: {SECRET}"}],
        }


@dataclass
class FakeRunner:
    """Records each call and loads every symbol it is given, like the real runner."""

    verdict: str = "pass"
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(
        self,
        loader: Loader,
        symbols: Sequence[str],
        timeframe: str,
        bars: int,
        strategy: Strategy,
        rules: ExitRules,
        *,
        split: SplitSpec,
        seed: int,
        stride: int,
    ) -> FakeResult:
        loaded = []
        for symbol in symbols:
            try:
                loaded.append(len(loader.load(symbol, timeframe, bars)))
            except Exception:  # noqa: BLE001 - mirrors the real runner's per-symbol skip
                loaded.append(0)
        self.calls.append(
            {
                "symbols": list(symbols),
                "timeframe": timeframe,
                "bars": bars,
                "strategy": strategy.slug,
                "rules": rules,
                "split": split,
                "seed": seed,
                "stride": stride,
                "loaded": loaded,
            }
        )
        if self.error is not None:
            raise self.error
        return FakeResult(verdict=self.verdict)
