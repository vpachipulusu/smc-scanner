"""Console table and CSV output for scan rows."""

import csv
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from rich.table import Table
from rich.text import Text

from smc_scanner.models import ScanRow

COLUMNS: tuple[str, ...] = tuple(field.name for field in fields(ScanRow))
AI_COLUMNS: tuple[str, ...] = (
    "ai_action",
    "ai_confidence",
    "ai_entry",
    "ai_stop",
    "ai_target",
    "ai_note",
)
TEXT_COLUMNS = ("ai_action", "ai_note")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(text: str) -> str:
    """Neutralise spreadsheet formulas: a leading quote makes the cell plain text."""
    return f"'{text}" if text.lstrip().startswith(FORMULA_PREFIXES) else text


@dataclass(frozen=True)
class AiCells:
    """The AI columns for one row; every field is empty when there is no verdict."""

    action: str = ""
    confidence: float | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    note: str = ""

    def display_row(self) -> dict[str, str]:
        """Raw text for the console table."""
        return {
            "ai_action": self.action,
            "ai_confidence": _optional(self.confidence),
            "ai_entry": _optional(self.entry),
            "ai_stop": _optional(self.stop),
            "ai_target": _optional(self.target),
            "ai_note": self.note,
        }

    def csv_row(self) -> dict[str, str]:
        """Same cells with spreadsheet formulas neutralised."""
        return {
            name: csv_safe(text) if name in TEXT_COLUMNS else text
            for name, text in self.display_row().items()
        }


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        # Full quote precision without float noise (1.08235 stays 1.08235, 65432.1 stays).
        return f"{value:.10f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _optional(value: float | None) -> str:
    return "" if value is None else _cell(value)


def _check_alignment(rows: Sequence[ScanRow], ai: Sequence[AiCells] | None) -> None:
    if ai is not None and len(ai) != len(rows):
        raise ValueError(f"{len(ai)} AI cell sets for {len(rows)} rows")


def render_table(
    rows: Iterable[ScanRow], title: str = "SMC scan", ai: Sequence[AiCells] | None = None
) -> Table:
    listed = list(rows)
    _check_alignment(listed, ai)
    table = Table(title=title)
    for column in COLUMNS:
        table.add_column(column)
    if ai is not None:
        for column in AI_COLUMNS:
            table.add_column(column)
    count = 0
    for index, row in enumerate(listed):
        style = "bold green" if row.status == "TOUCHING" else ""
        cells = [_cell(value) for value in asdict(row).values()]
        if ai is not None:
            cells.extend(ai[index].display_row().values())
        # Text() so '[' in model or error text is never parsed as console markup.
        table.add_row(*(Text(cell) for cell in cells), style=style)
        count += 1
    if count == 0:
        table.caption = "no instruments touching or near a fresh zone"
    return table


def write_csv(rows: Iterable[ScanRow], path: Path, ai: Sequence[AiCells] | None = None) -> Path:
    """The scan columns, plus the ``ai_*`` columns only when ``ai`` is given."""
    listed = list(rows)
    _check_alignment(listed, ai)  # before the file is opened and truncated
    names = COLUMNS if ai is None else COLUMNS + AI_COLUMNS
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for index, row in enumerate(listed):
            record: dict[str, object] = dict(asdict(row))
            if ai is not None:
                record.update(ai[index].csv_row())
            writer.writerow(record)
    return path


def rows_to_dicts(rows: Iterable[ScanRow]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]
