"""The scanner must never trade: an AST check of every MetaTrader5 attribute the package
touches, plus a text scan for trading vocabulary."""

import ast
import re
from pathlib import Path

import pytest

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


AI_PACKAGE = PACKAGE / "ai"
NOTIFY_PACKAGE = PACKAGE / "notify"
GUARDED_PACKAGES = (AI_PACKAGE, NOTIFY_PACKAGE)
NETWORK_ALLOWLIST = frozenset({AI_PACKAGE / "providers.py", NOTIFY_PACKAGE / "telegram.py"})

ALWAYS_BANNED_MODULES = {"MetaTrader5", "subprocess"}
# Network, process and native-code escape hatches; only allowlisted modules may use them.
RESTRICTED_MODULES = {
    "httpx",
    "requests",
    "anthropic",
    "aiohttp",
    "urllib3",
    "http",
    "websockets",
    "openai",
    "ssl",
    "smtplib",
    "ftplib",
    "asyncio",
    "ctypes",
    "multiprocessing",
    "socket",
    "importlib",
}
URLLIB_SAFE_PREFIX = "urllib.parse"
RESTRICTED_BUILTINS = {"__import__", "eval", "exec", "compile"}
DYNAMIC_ATTR_BUILTINS = {"getattr", "setattr", "delattr"}
OS_EXACT = {"system", "popen", "startfile", "add_dll_directory"}
OS_PREFIXES = ("exec", "spawn", "posix_spawn")
ORDER_PHRASES = [
    ("order", "send"),
    ("order", "check"),
    ("order", "calc"),
    ("orders", "get"),
    ("positions", "get"),
    ("send", "order"),
    ("place", "order"),
    ("close", "position"),
    ("position", "close"),
    ("modify", "position"),
    ("ordersend",),
    ("positionclose",),
]
ORDER_WHOLE_NAMES = {"buy", "sell"}

Import = tuple[int, str, str | None]  # (relative level, module, imported name)


def _imports(tree: ast.AST) -> list[Import]:
    found: list[Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((0, alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.extend((node.level, node.module or "", alias.name) for alias in node.names)
    return found


def _dotted(imp: Import) -> str:
    _, module, name = imp
    return ".".join(part for part in (module, name) if part)


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """Local name -> dotted import target (``import os as o`` gives ``o -> os``)."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                aliases[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                target = ".".join(p for p in (node.module or "", alias.name) if p)
                aliases[alias.asname or alias.name] = target
    return aliases


def _resolve(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """Dotted name of a Name/Attribute chain with its root resolved through the aliases."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, aliases)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _is_order_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in ORDER_WHOLE_NAMES:
        return True
    tokens = [t for t in lowered.split("_") if t]
    return any(
        tuple(tokens[i : i + len(phrase)]) == phrase
        for phrase in ORDER_PHRASES
        for i in range(len(tokens) - len(phrase) + 1)
    )


def _is_forbidden_os(dotted: str) -> bool:
    head, _, rest = dotted.partition(".")
    if head != "os":
        return False
    first = rest.split(".")[0]
    return first in OS_EXACT or first.startswith(OS_PREFIXES)


def _import_violations(tree: ast.AST, allow_restricted: bool) -> list[str]:
    found: list[str] = []
    for imp in _imports(tree):
        dotted = _dotted(imp)
        parts = dotted.split(".")
        root = parts[0]
        if "loaders" in parts:
            found.append(f"imports loaders: {dotted}")
        elif root in ALWAYS_BANNED_MODULES:
            found.append(f"imports {root}")
        elif _is_forbidden_os(dotted):
            found.append(f"imports {dotted}")
        elif allow_restricted:
            continue
        elif root in RESTRICTED_MODULES:
            found.append(f"imports restricted module {root}")
        elif root == "urllib" and not dotted.startswith(URLLIB_SAFE_PREFIX):
            found.append(f"imports restricted module {dotted}")
    return found


def _getattr_violations(
    call: ast.Call, aliases: dict[str, str], allow_restricted: bool
) -> list[str]:
    if len(call.args) < 2:
        return ["getattr-style call with no attribute name"]
    name = call.args[1]
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        return [] if allow_restricted else ["dynamic getattr/setattr name"]
    target = _resolve(call.args[0], aliases)
    found: list[str] = []
    if target is not None and _is_forbidden_os(f"{target}.{name.value}"):
        found.append(f"getattr reaches {target}.{name.value}")
    if _is_order_name(name.value):
        found.append(f"getattr reaches order-like name {name.value}")
    return found


def _call_violations(call: ast.Call, aliases: dict[str, str], allow_restricted: bool) -> list[str]:
    func = call.func
    if isinstance(func, ast.Name) and func.id in DYNAMIC_ATTR_BUILTINS:
        return _getattr_violations(call, aliases, allow_restricted)
    if isinstance(func, ast.Name) and func.id in RESTRICTED_BUILTINS and not allow_restricted:
        return [f"calls {func.id}"]
    if isinstance(func, ast.Subscript):
        index = func.slice
        if (
            isinstance(index, ast.Constant)
            and isinstance(index.value, str)
            and _is_order_name(index.value)
        ):
            return [f"calls order-like subscript {ast.unparse(func)}"]
        return [] if allow_restricted else [f"calls dynamic subscript {ast.unparse(func)}"]
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return [f"calls order-like function {name}"] if _is_order_name(name) else []


def ai_safety_violations(source: str, *, allow_network: bool = False) -> list[str]:
    """Why a guarded (``ai/`` or ``notify/``) module breaks the read-only rules."""
    tree = ast.parse(source)
    aliases = _alias_map(tree)
    found = _import_violations(tree, allow_network)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted = _resolve(node, aliases)
            if dotted is not None and (
                _is_forbidden_os(dotted) or dotted.split(".")[0] == "subprocess"
            ):
                found.append(f"uses {dotted}")
        elif isinstance(node, ast.Call):
            found.extend(_call_violations(node, aliases, allow_network))
    return found


def network_allowed(path: Path) -> bool:
    return path in NETWORK_ALLOWLIST


def _guarded_modules() -> list[Path]:
    return sorted(p for pkg in GUARDED_PACKAGES for p in pkg.rglob("*.py"))


def test_guarded_packages_obey_the_read_only_rules() -> None:
    modules = _guarded_modules()
    assert AI_PACKAGE / "providers.py" in modules
    for path in modules:
        violations = ai_safety_violations(
            path.read_text(encoding="utf-8"), allow_network=network_allowed(path)
        )
        assert violations == [], path


def test_allowlist_is_exact_and_tolerates_missing_paths() -> None:
    assert network_allowed(AI_PACKAGE / "providers.py")
    assert network_allowed(NOTIFY_PACKAGE / "telegram.py")
    assert not network_allowed(AI_PACKAGE / "sub" / "providers.py")
    assert not network_allowed(NOTIFY_PACKAGE / "providers.py")
    assert not network_allowed(AI_PACKAGE / "telegram.py")
    assert not network_allowed(AI_PACKAGE / "verdict.py")


OFFENDERS = [
    ("import MetaTrader5 as mt5", "imports MetaTrader5"),
    ("import subprocess", "imports subprocess"),
    ("from subprocess import run", "imports subprocess"),
    ("import subprocess as sp\nsp.run([])", "uses subprocess.run"),
    ("from smc_scanner.loaders import mt5", "imports loaders"),
    ("from smc_scanner.loaders.mt5 import Mt5Loader", "imports loaders"),
    ("from ..loaders import base", "imports loaders"),
    ("from .. import loaders", "imports loaders"),
    ("from smc_scanner import loaders", "imports loaders"),
    ("import smc_scanner.loaders.mt5", "imports loaders"),
    ("import os\nos.system('ls')", "uses os.system"),
    ("import os\nos.popen('ls')", "uses os.popen"),
    ("import os as o\no.system('ls')", "uses os.system"),
    ("import os as o\nrun = o.popen", "uses os.popen"),
    ("from os import system", "imports os.system"),
    ("from os import system as s\ns('ls')", "imports os.system"),
    ("import os\nos.execv('/bin/sh', [])", "uses os.execv"),
    ("import os\nos.execvp('sh', [])", "uses os.execvp"),
    ("import os\nos.spawnl(0, 'sh')", "uses os.spawnl"),
    ("import os\nos.startfile('x')", "uses os.startfile"),
    ("import os\nos.posix_spawn('x', [], {})", "uses os.posix_spawn"),
    ("import os\nos.add_dll_directory('x')", "uses os.add_dll_directory"),
    ("def f(m):\n    m.order_send({})", "order-like function order_send"),
    ("def f(m):\n    m.OrderSend({})", "order-like function OrderSend"),
    ("def f():\n    place_order()", "order-like function place_order"),
    ("def f():\n    mt5_order_check()", "order-like function mt5_order_check"),
    ("def f(m):\n    m.close_position(1)", "order-like function close_position"),
    ("def f(m):\n    m.modify_position(1)", "order-like function modify_position"),
    ("def f(m):\n    m.buy(1)", "order-like function buy"),
    ("def f(m):\n    m.sell(1)", "order-like function sell"),
    ("import importlib\nimportlib.import_module('MetaTrader5')", "restricted module importlib"),
    ("from importlib import import_module", "restricted module importlib"),
    ("__import__('subprocess')", "calls __import__"),
    ("eval('1')", "calls eval"),
    ("exec('x = 1')", "calls exec"),
    ("compile('1', 'f', 'eval')", "calls compile"),
    ("import os\ngetattr(os, 'system')", "getattr reaches os.system"),
    ("import os as o\ngetattr(o, 'popen')", "getattr reaches os.popen"),
    ("def f(m, n):\n    getattr(m, n)", "dynamic getattr"),
    ("def f(m):\n    getattr(m, 'order_' + 'send')()", "dynamic getattr"),
    ("def f(m):\n    setattr(m, 'x' + 'y', 1)", "dynamic getattr"),
    ("def f(m):\n    getattr(m, 'order_send')", "getattr reaches order-like"),
    ("def f(m):\n    m['order_send']()", "order-like subscript"),
    ("def f(m, k):\n    m[k]()", "dynamic subscript"),
    ("import httpx", "restricted module httpx"),
    ("import requests", "restricted module requests"),
    ("import anthropic", "restricted module anthropic"),
    ("import aiohttp", "restricted module aiohttp"),
    ("import urllib3", "restricted module urllib3"),
    ("import http.client", "restricted module http"),
    ("from http import client", "restricted module http"),
    ("import websockets", "restricted module websockets"),
    ("import openai", "restricted module openai"),
    ("import ssl", "restricted module ssl"),
    ("import smtplib", "restricted module smtplib"),
    ("import ftplib", "restricted module ftplib"),
    ("import asyncio", "restricted module asyncio"),
    ("import ctypes", "restricted module ctypes"),
    ("import multiprocessing", "restricted module multiprocessing"),
    ("import socket", "restricted module socket"),
    ("import urllib.request", "restricted module urllib.request"),
    ("from urllib import request", "restricted module urllib.request"),
    ("from urllib.request import urlopen", "restricted module urllib.request"),
    ("import urllib", "restricted module urllib"),
    ("from httpx import Client", "restricted module httpx"),
]


@pytest.mark.parametrize(("source", "expected"), OFFENDERS)
def test_rule_rejects_offending_module(source: str, expected: str) -> None:
    violations = ai_safety_violations(source)

    assert any(expected in v for v in violations), violations


ALWAYS_FORBIDDEN = [
    "import subprocess",
    "import MetaTrader5",
    "from smc_scanner.loaders import mt5",
    "import os as o\no.system('x')",
    "import os\nos.execv('x', [])",
    "def f(m):\n    m.order_send({})",
    "def f(m):\n    m['order_send']()",
    "import os\ngetattr(os, 'system')",
]


@pytest.mark.parametrize("source", ALWAYS_FORBIDDEN)
def test_allowlist_never_exempts_trading_or_shell_access(source: str) -> None:
    assert ai_safety_violations(source, allow_network=True) != []


def test_allowlisted_module_may_use_network_libraries_and_lazy_imports() -> None:
    source = (
        "import httpx\nimport anthropic\nimport ssl\nimport asyncio\n"
        "from urllib.request import urlopen\n"
        "def f(m, n):\n    return getattr(m, n)\n"
    )

    assert ai_safety_violations(source) != []
    assert ai_safety_violations(source, allow_network=True) == []


CLEAN = [
    "import json\nfrom smc_scanner.ai.verdict import parse_verdict\nparse_verdict('', 1)\n",
    "from urllib.parse import urlparse\nimport urllib.parse\nurlparse('x')\n",
    "import os\nos.environ.get('X')\nos.getenv('Y')\nos.path.join('a', 'b')\n",
    "import os as o\no.environ.get('X')\n",
    "import random\nimport logging\nimport time\n",
    "def f(m):\n    return getattr(m, 'name')\n",
    "def f(xs):\n    return sorted(xs, key=lambda x: x)\n",
]


@pytest.mark.parametrize("source", CLEAN)
def test_rule_passes_clean_module(source: str) -> None:
    assert ai_safety_violations(source) == []


@pytest.mark.parametrize(
    "name",
    [
        "order_send",
        "OrderSend",
        "place_order",
        "send_order",
        "mt5_order_check",
        "buy",
        "sell",
        "close_position",
        "position_close",
        "modify_position",
        "ORDER_SEND",
        "positions_get",
    ],
)
def test_order_name_matching_hits_trading_names(name: str) -> None:
    assert _is_order_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "sort_order",
        "reorder",
        "border",
        "ordered",
        "sorted_orders",
        "order",
        "orders",
        "is_buyer",
        "buyer",
        "seller",
        "position",
        "closest_position_to",
        "disorder",
        "recorder",
    ],
)
def test_order_name_matching_ignores_innocent_names(name: str) -> None:
    assert not _is_order_name(name)


def test_order_like_call_names_only_trip_on_whole_tokens() -> None:
    assert ai_safety_violations("def f(x):\n    x.sort_order()\n    x.reorder()\n") == []
    assert ai_safety_violations("def f(x):\n    x.order_send()\n") != []
