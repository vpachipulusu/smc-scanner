"""The scanner must never trade: an AST check of every MetaTrader5 attribute the package
touches, plus a text scan for trading vocabulary."""

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "smc_scanner"
MT5_LOADER = PACKAGE / "loaders" / "mt5.py"

ALLOWED_MT5_CALLS = {
    "initialize",
    "shutdown",
    "last_error",
    "symbol_select",
    "symbol_info_tick",
    "copy_rates_from_pos",
}
TRADING_WORDS = re.compile(
    r"order_send|order_check|order_calc|positions_get|positions_total|orders_get|orders_total|"
    r"history_orders|history_deals|TRADE_ACTION|OrderSend|PositionClose|\.login\(",
)


def _mt5_bases(node: ast.AST) -> bool:
    """True for ``mt5.<x>`` and ``self._mt5.<x>`` / ``<anything>._mt5.<x>``."""
    if isinstance(node, ast.Name):
        return node.id == "mt5"
    return isinstance(node, ast.Attribute) and node.attr == "_mt5"


def _mt5_attributes(tree: ast.AST) -> set[str]:
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and _mt5_bases(node.value)
    }


def _dynamic_mt5_getattrs(tree: ast.AST) -> list[str]:
    """``getattr(mt5, X)`` is allowed only with ``MT5_TIMEFRAME_ATTR[...]`` as X."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "getattr" or not node.args or not _mt5_bases(node.args[0]):
            continue
        name = node.args[1]
        ok = (
            isinstance(name, ast.Subscript)
            and isinstance(name.value, ast.Name)
            and name.value.id == "MT5_TIMEFRAME_ATTR"
        )
        if not ok:
            offenders.append(ast.unparse(node))
    return offenders


def test_mt5_loader_uses_only_the_allowed_calls() -> None:
    tree = ast.parse(MT5_LOADER.read_text(encoding="utf-8"))

    used = _mt5_attributes(tree)

    assert used <= ALLOWED_MT5_CALLS, used - ALLOWED_MT5_CALLS
    assert _dynamic_mt5_getattrs(tree) == []


def test_only_the_mt5_loader_touches_the_module() -> None:
    for path in PACKAGE.rglob("*.py"):
        if path == MT5_LOADER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        }
        assert "MetaTrader5" not in imported, path
        assert _mt5_attributes(tree) == set(), path


def test_no_trading_vocabulary_in_package() -> None:
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in PACKAGE.rglob("*.py")
        for match in TRADING_WORDS.finditer(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
