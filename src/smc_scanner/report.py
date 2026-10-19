"""Console table and CSV output for scan rows."""

import csv
from collections.abc import Iterable
from dataclasses import asdict, fields
from pathlib import Path

from rich.table import Table

from smc_scanner.models import ScanRow

COLUMNS: tuple[str, ...] = tuple(field.name for field in fields(ScanRow))


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        # Full quote precision without float noise (1.08235 stays 1.08235, 65432.1 stays).
        return f"{value:.10f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def render_table(rows: Iterable[ScanRow], title: str = "SMC scan") -> Table:
    table = Table(title=title)
    for column in COLUMNS:
        table.add_column(column)
    count = 0
    for row in rows:
        style = "bold green" if row.status == "TOUCHING" else ""
        table.add_row(*(_cell(value) for value in asdict(row).values()), style=style)
        count += 1
    if count == 0:
        table.caption = "no instruments touching or near a fresh zone"
    return table


def write_csv(rows: Iterable[ScanRow], path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return path


def rows_to_dicts(rows: Iterable[ScanRow]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]
