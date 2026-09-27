"""CSV inventory reports for FileFlow.

Row building reads the workspace through ``workspace.scan``; the CSV text
itself is produced by a pure function so tests can assert on the output
without touching disk.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .planner import ACTION_MOVE, ACTION_ORGANIZED, ACTION_SKIP_DUPLICATE, categorize
from .workspace import scan

CSV_COLUMNS: tuple[str, ...] = ("file", "category", "size_bytes", "sha256_8", "action")


@dataclass(frozen=True)
class ReportRow:
    file: str
    category: str
    size_bytes: int
    sha256_8: str
    action: str


def build_rows(root: Path, dest_base: Path) -> list[ReportRow]:
    """Inventory every file under ``root`` with category, hash and action."""
    root_resolved = root.resolve()
    dest_resolved = dest_base.resolve()
    dest_rel = dest_resolved.relative_to(root_resolved).as_posix()

    rows: list[ReportRow] = []
    seen_hashes: set[str] = set()
    for entry in scan(root_resolved):
        relative = entry.path.relative_to(root_resolved).as_posix()
        inside_dest = relative == dest_rel or relative.startswith(f"{dest_rel}/")
        if inside_dest:
            action = ACTION_ORGANIZED
        elif entry.sha256 in seen_hashes:
            action = ACTION_SKIP_DUPLICATE
        else:
            action = ACTION_MOVE
        seen_hashes.add(entry.sha256)
        rows.append(
            ReportRow(
                file=relative,
                category=categorize(relative),
                size_bytes=entry.size,
                sha256_8=entry.sha256[:8],
                action=action,
            )
        )
    return rows


def to_csv(rows: Sequence[ReportRow]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([row.file, row.category, row.size_bytes, row.sha256_8, row.action])
    return buffer.getvalue()


def write_csv(rows: Sequence[ReportRow], out: Path) -> Path:
    out = Path(out)
    if out.parent != Path("."):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_csv(rows), encoding="utf-8")
    return out


def summarize(rows: Sequence[ReportRow]) -> dict[str, int]:
    categories = {row.category for row in rows}
    duplicates = sum(1 for row in rows if row.action == ACTION_SKIP_DUPLICATE)
    return {
        "files": len(rows),
        "categories": len(categories),
        "duplicates": duplicates,
    }
