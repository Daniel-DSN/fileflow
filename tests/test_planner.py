"""Planner tests — pure decisions, no filesystem access required."""

from pathlib import Path

import pytest

from fileflow.planner import (
    ACTION_MOVE,
    ACTION_SKIP_DUPLICATE,
    FileEntry,
    build_plan,
    categorize,
    slugify,
)

ROOT = Path("/tmp/fileflow-tests/root")
DEST = ROOT / "_organized"


def _entry(relative: str, payload: str) -> FileEntry:
    return FileEntry(path=ROOT / relative, size=len(payload), sha256=payload)


def _plan(files, *, by="type", rename=False, dest=DEST):
    return build_plan(ROOT, dest, files, by=by, rename=rename)


def test_categorize_known_extensions():
    assert categorize("photo.JPG") == "images"
    assert categorize("report.pdf") == "docs"
    assert categorize("song.mp3") == "audio"
    assert categorize("table.csv") == "data"
    assert categorize("script.py") == "code"
    assert categorize("backup.zip") == "archives"


def test_categorize_unknown_and_missing_extension():
    assert categorize("setup.exe") == "other"
    assert categorize("notes.dat") == "other"
    assert categorize("LICENSE") == "other"


def test_categorize_is_case_insensitive():
    assert categorize("QUARTERLY REPORT.PDF") == "docs"
    assert categorize("Banner.PNG") == "images"


def test_slugify_lowercases_and_sanitizes():
    assert slugify("Quarterly Report") == "quarterly_report"
    assert slugify("contract signed 2026 (final)") == "contract_signed_2026_final"
    assert slugify("__weird--name!!") == "weird_name"


def test_slugify_falls_back_when_empty():
    assert slugify("!!!") == "file"
    assert slugify("") == "file"


def test_plan_moves_every_unique_file_into_category_folders():
    plan = _plan(
        [
            _entry("inbox/a.pdf", "aaa"),
            _entry("media/pic.png", "bbb"),
            _entry("dump/x.exe", "ccc"),
        ]
    )
    assert [a.action for a in plan.actions] == [ACTION_MOVE, ACTION_MOVE, ACTION_MOVE]
    assert [a.dest for a in plan.actions] == [
        "_organized/other/x.exe",
        "_organized/docs/a.pdf",
        "_organized/images/pic.png",
    ]
    assert plan.stats() == {"files": 3, "move": 3, "skip_duplicate": 0, "categories": 3}


def test_plan_is_deterministic_regardless_of_input_order():
    entries = [_entry("b/two.txt", "2"), _entry("a/one.txt", "1"), _entry("c/three.txt", "3")]
    first = _plan(entries)
    second = _plan(list(reversed(entries)))
    assert first.actions == second.actions
    assert [a.src for a in first.actions] == ["a/one.txt", "b/two.txt", "c/three.txt"]


def test_plan_marks_second_occurrence_of_same_bytes_as_duplicate():
    plan = _plan(
        [
            _entry("downloads/banner.png", "same-bytes"),
            _entry("media/banner copy.png", "same-bytes"),
            _entry("media/solo.png", "other-bytes"),
        ]
    )
    by_src = {a.src: a for a in plan.actions}
    assert by_src["downloads/banner.png"].action == ACTION_MOVE
    assert by_src["media/banner copy.png"].action == ACTION_SKIP_DUPLICATE
    assert by_src["media/banner copy.png"].dest == ""
    assert by_src["media/solo.png"].action == ACTION_MOVE
    assert plan.stats()["skip_duplicate"] == 1


def test_plan_rename_zero_pads_sequence_per_category():
    plan = _plan(
        [
            _entry("a/notes.txt", "1"),
            _entry("b/readme.md", "2"),
            _entry("c/report.pdf", "3"),
            _entry("d/song.mp3", "4"),
        ],
        rename=True,
    )
    dests = {a.src: a.dest for a in plan.actions}
    assert dests["a/notes.txt"] == "_organized/docs/001_notes.txt"
    assert dests["b/readme.md"] == "_organized/docs/002_readme.md"
    assert dests["c/report.pdf"] == "_organized/docs/003_report.pdf"
    assert dests["d/song.mp3"] == "_organized/audio/001_song.mp3"


def test_plan_rename_by_ext_scopes_sequence_per_extension():
    plan = _plan(
        [
            _entry("a/notes.txt", "1"),
            _entry("b/readme.md", "2"),
            _entry("c/report.pdf", "3"),
        ],
        rename=True,
        by="ext",
    )
    dests = {a.src: a.dest for a in plan.actions}
    assert dests["a/notes.txt"] == "_organized/docs/001_notes.txt"
    assert dests["b/readme.md"] == "_organized/docs/001_readme.md"
    assert dests["c/report.pdf"] == "_organized/docs/001_report.pdf"


def test_plan_without_rename_keeps_names_and_dedupes_collisions():
    plan = _plan(
        [
            _entry("left/data.csv", "1"),
            _entry("right/data.csv", "2"),
            _entry("left/Quarterly Report.PDF", "3"),
        ]
    )
    dests = [a.dest for a in plan.actions]
    assert dests == [
        "_organized/docs/Quarterly Report.PDF",
        "_organized/data/data.csv",
        "_organized/data/data_2.csv",
    ]


def test_plan_rejects_entries_outside_root():
    with pytest.raises(ValueError, match="escapes directory"):
        _plan([FileEntry(path=Path("/etc/passwd"), size=1, sha256="x")])


def test_plan_rejects_destination_equal_to_root():
    with pytest.raises(ValueError, match="subdirectory of DIR"):
        build_plan(ROOT, ROOT, [])


def test_plan_rejects_destination_outside_root():
    with pytest.raises(ValueError, match="escapes directory"):
        build_plan(ROOT, Path("/tmp/somewhere-else"), [])


def test_plan_rejects_unknown_grouping():
    with pytest.raises(ValueError, match="unsupported grouping"):
        _plan([], by="size")
