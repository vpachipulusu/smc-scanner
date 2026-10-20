"""Write the API's OpenAPI schema to ``nextjs-frontend/openapi.json``.

    uv run python -m smc_scanner.openapi_export          # write
    uv run python -m smc_scanner.openapi_export --check  # exit 1 when the file is stale

The frontend builds its typed client from that file (``npm run generate:client``), and
``npm run check:client`` compares the generated client with the committed one, so both
halves are checked. ``tests/test_openapi.py`` runs the same comparison under pytest.
LF newlines keep the committed file byte-identical on Windows and elsewhere.
"""

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from smc_scanner.api import app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "nextjs-frontend" / "openapi.json"


def schema_text() -> str:
    return json.dumps(app.openapi(), indent=2) + "\n"


def export_schema(path: Path = DEFAULT_OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema_text(), encoding="utf-8", newline="\n")
    return path


def is_current(path: Path = DEFAULT_OUTPUT) -> bool:
    if not path.is_file():
        return False
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") == schema_text()


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        if is_current():
            print(f"openapi: {DEFAULT_OUTPUT} is up to date")
            return 0
        print(
            f"openapi: {DEFAULT_OUTPUT} is out of date; run "
            "`uv run python -m smc_scanner.openapi_export`, then `npm run generate:client` "
            "in nextjs-frontend/"
        )
        return 1
    if args:
        print("usage: python -m smc_scanner.openapi_export [--check]")
        return 2
    print(f"openapi: wrote {export_schema()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
