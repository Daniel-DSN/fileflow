"""Workspace tests — real files in tmp_path, real moves, real safety checks."""

import hashlib
from pathlib import Path

import pytest

from fileflow.cli import main
from fileflow.planner import ACTION_MOVE, ACTION_SKIP_DUPLICATE, PlannedAction, build_plan
from fileflow.workspace import (
    DEMO_FILES,
    apply_plan,
    assert_contained,
    init_demo,
    require_dir,
    resolve_dest,
    scan,
)


def _demo(tmp_path: Path, name: str = "ws") -> Path:
    return init_demo(tmp_path / name).root


def test_init_demo_creates_seeded_tree(tmp_path: Path):
    stats = init_demo(tmp_path / "ws")
    root = stats.root
    created = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert created == sorted(DEMO_FILES)
    assert stats.files == len(DEMO_FILES)
    assert stats.bytes == sum(len(v.encode("utf-8")) for v in DEMO_FILES.values())
    assert stats.categories == 7


def test_init_demo_is_deterministic(tmp_path: Path):
    first = _demo(tmp_path, "one")
    second = _demo(tmp_path, "two")
    dump_one = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    dump_two = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
    assert dump_one == dump_two


def test_init_demo_includes_empty_file_and_duplicate_pairs(tmp_path: Path):
    root = _demo(tmp_path)
    assert (root / "shared/empty.dat").stat().st_size == 0
    banner_a = (root / "downloads/banner.png").read_bytes()
    banner_b = (root / "media/banner.png").read_bytes()
    docx_a = (root / "shared/contract.docx").read_bytes()
    docx_b = (root / "shared/contract signed.docx").read_bytes()
    assert banner_a == banner_b and len(banner_a) > 0
    assert docx_a == docx_b
    assert banner_a != docx_a


def test_init_demo_refuses_non_empty_directory(tmp_path: Path):
    root = _demo(tmp_path)
    with pytest.raises(ValueError, match="not empty"):
        init_demo(root)


def test_scan_hashes_every_file_and_honours_exclusion(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    everything = scan(root)
    assert len(everything) == len(DEMO_FILES)

    (dest / "docs").mkdir(parents=True)
    (dest / "docs/kept.md").write_text("kept\n", encoding="utf-8")
    excluded = scan(root, exclude=dest)
    assert len(excluded) == len(DEMO_FILES)
    assert all(not str(e.path).startswith(str(dest)) for e in excluded)

    note = next(e for e in everything if e.path.name == "notes.txt")
    expected = hashlib.sha256((root / "inbox/notes.txt").read_bytes()).hexdigest()
    assert note.sha256 == expected
    assert note.size == (root / "inbox/notes.txt").stat().st_size


def test_assert_contained_allows_inside_and_rejects_outside(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    inside = tmp_path / "root" / "sub" / "file.txt"
    outside = tmp_path / "elsewhere.txt"
    assert assert_contained(root, inside) == inside.resolve()
    assert assert_contained(root, root) == root.resolve()
    with pytest.raises(ValueError, match="escapes directory"):
        assert_contained(root, outside)


def test_resolve_dest_defaults_and_custom_paths(tmp_path: Path):
    root = _demo(tmp_path)
    assert resolve_dest(root, None) == root / "_organized"
    assert resolve_dest(root, "sorted") == root / "sorted"
    assert resolve_dest(root, "a/b/out") == root / "a" / "b" / "out"
    with pytest.raises(ValueError, match="escapes directory"):
        resolve_dest(root, tmp_path / "outside")
    with pytest.raises(ValueError, match="subdirectory of DIR"):
        resolve_dest(root, ".")


def test_require_dir_rejects_missing_path(tmp_path: Path):
    with pytest.raises(ValueError, match="not a directory"):
        require_dir(tmp_path / "nope")
    assert require_dir(tmp_path) == tmp_path.resolve()


def test_planning_is_a_true_dry_run(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    build_plan(root, dest, scan(root, exclude=dest), rename=True)
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after
    assert not dest.exists()


def test_apply_moves_files_skips_duplicates_and_prunes_empty_dirs(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    plan = build_plan(root, dest, scan(root, exclude=dest), rename=True)
    stats = apply_plan(plan)

    assert stats.moved == 14
    assert stats.skipped == 2
    assert len(stats.categories) == 7
    assert stats.pruned_dirs >= 1

    assert (root / "_organized/docs/001_readme.md").is_file()
    assert (root / "_organized/images/001_banner.png").is_file()
    assert (root / "_organized/other/002_empty.dat").stat().st_size == 0
    assert (root / "media/banner.png").is_file()
    assert (root / "shared/contract.docx").is_file()
    assert not (root / "deep/nested/folder").exists()
    assert len([p for p in root.rglob("*") if p.is_file()]) == len(DEMO_FILES)


def test_apply_never_touches_paths_outside_root(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    plan = build_plan(root, dest, scan(root, exclude=dest), rename=True)
    escaped = PlannedAction(
        action=ACTION_MOVE,
        src="../outside.txt",
        dest="_organized/docs/001_outside.txt",
        category="docs",
        size=1,
        sha256="x",
    )
    tampered = type(plan)(root=plan.root, dest_base=plan.dest_base, by=plan.by,
                          rename=plan.rename, actions=(escaped, *plan.actions))
    with pytest.raises(ValueError, match="escapes directory"):
        apply_plan(tampered)


def test_apply_refuses_existing_destination_file(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    plan = build_plan(root, dest, scan(root, exclude=dest), rename=True)
    first = plan.moves[0]
    blocked = root / first.dest
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("collision\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="destination already exists"):
        apply_plan(plan)


def test_cli_plan_is_dry_run_and_apply_requires_yes(tmp_path: Path):
    root = _demo(tmp_path)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

    assert main(["plan", str(root), "--rename"]) == 0
    after_plan = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert after_plan == before

    assert main(["apply", str(root)]) == 1

    assert main(["apply", str(root), "--yes", "--rename"]) == 0
    assert (root / "_organized/docs/001_readme.md").is_file()


def test_cli_reports_errors_with_exit_code_one(tmp_path: Path):
    assert main(["plan", str(tmp_path / "missing")]) == 1
    assert main(["report", str(tmp_path / "missing")]) == 1
    (tmp_path / "blocker.txt").write_text("occupied\n", encoding="utf-8")
    assert main(["init-demo", str(tmp_path)]) == 1
    assert main(["apply", str(tmp_path / "missing"), "--yes"]) == 1


def test_cli_init_demo_and_plan_on_empty_dir(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["plan", str(empty)]) == 1
    assert main(["init-demo", str(tmp_path / "fresh")]) == 0
    assert main(["plan", str(tmp_path / "fresh")]) == 0


def test_duplicate_actions_in_plan_match_workspace_scan(tmp_path: Path):
    root = _demo(tmp_path)
    dest = resolve_dest(root, None)
    plan = build_plan(root, dest, scan(root, exclude=dest))
    dupes = [a for a in plan.actions if a.action == ACTION_SKIP_DUPLICATE]
    assert sorted(a.src for a in dupes) == ["media/banner.png", "shared/contract.docx"]
