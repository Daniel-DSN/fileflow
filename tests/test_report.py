"""Report tests — CSV text is pure, row building runs on tmp_path files."""

import csv
import io
from pathlib import Path

from fileflow.planner import ACTION_MOVE, ACTION_SKIP_DUPLICATE, build_plan
from fileflow.report import CSV_COLUMNS, build_rows, summarize, to_csv, write_csv
from fileflow.workspace import apply_plan, init_demo, resolve_dest, scan


def _demo(tmp_path: Path) -> Path:
    return init_demo(tmp_path / "ws").root


def test_to_csv_emits_required_columns_and_rows(tmp_path: Path):
    root = _demo(tmp_path)
    rows = build_rows(root, resolve_dest(root, None))
    text = to_csv(rows)

    parsed = list(csv.DictReader(io.StringIO(text)))
    assert tuple(parsed[0].keys()) == CSV_COLUMNS
    assert len(parsed) == 16
    assert text.splitlines()[0] == "file,category,size_bytes,sha256_8,action"


def test_rows_before_apply_are_moves_and_duplicates(tmp_path: Path):
    root = _demo(tmp_path)
    rows = build_rows(root, resolve_dest(root, None))
    actions = {row.file: row.action for row in rows}

    assert actions["inbox/Quarterly Report.PDF"] == ACTION_MOVE
    assert actions["deep/nested/folder/readme.md"] == ACTION_MOVE
    assert actions["media/banner.png"] == ACTION_SKIP_DUPLICATE
    assert actions["shared/contract.docx"] == ACTION_SKIP_DUPLICATE
    assert summarize(rows) == {"files": 16, "categories": 7, "duplicates": 2}


def test_rows_carry_category_size_and_short_hash(tmp_path: Path):
    root = _demo(tmp_path)
    rows = {row.file: row for row in build_rows(root, resolve_dest(root, None))}

    pdf = rows["inbox/Quarterly Report.PDF"]
    assert pdf.category == "docs"
    assert pdf.size_bytes == (root / "inbox/Quarterly Report.PDF").stat().st_size
    assert len(pdf.sha256_8) == 8
    assert all(c in "0123456789abcdef" for c in pdf.sha256_8)

    empty = rows["shared/empty.dat"]
    assert empty.size_bytes == 0
    assert empty.category == "other"
    assert empty.sha256_8 == "e3b0c442"


def test_rows_after_apply_mark_organized_and_keep_loose_duplicates(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    apply_plan(build_plan(root, dest, scan(root, exclude=dest), rename=True))

    rows = build_rows(root, dest)
    actions = {row.file: row.action for row in rows}
    assert actions["_organized/docs/001_readme.md"] == "organized"
    assert actions["_organized/images/001_banner.png"] == "organized"
    assert actions["media/banner.png"] == ACTION_SKIP_DUPLICATE
    assert actions["shared/contract.docx"] == ACTION_SKIP_DUPLICATE
    assert "move" not in actions.values()
    assert summarize(rows) == {"files": 16, "categories": 7, "duplicates": 2}


def test_build_rows_is_deterministic(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    assert build_rows(root, dest) == build_rows(root, dest)


def test_write_csv_creates_parent_and_roundtrips(tmp_path: Path):
    root = _demo(tmp_path)
    rows = build_rows(root, resolve_dest(root, None))
    out = write_csv(rows, tmp_path / "nested" / "report.csv")

    assert out.is_file()
    with out.open(encoding="utf-8", newline="") as handle:
        parsed = list(csv.DictReader(handle))
    assert len(parsed) == 16
    assert parsed[0]["file"] == rows[0].file
    assert parsed[-1]["sha256_8"] == rows[-1].sha256_8


def test_summarize_counts_each_category_present(tmp_path: Path):
    root = _demo(tmp_path)
    rows = build_rows(root, resolve_dest(root, None))
    present = {row.category for row in rows}
    assert present == {"images", "docs", "audio", "data", "code", "archives", "other"}
