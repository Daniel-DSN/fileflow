"""Filesystem layer for FileFlow: demo workspace, scanning, safe applying.

Every operation that touches disk lives here, so the planner and the report
stay pure. All paths are resolved and asserted to stay inside the target
directory before anything is created, moved or removed.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from .planner import ACTION_SKIP_DUPLICATE, CATEGORY_ORDER, FileEntry, Plan, categorize

CHUNK_SIZE = 1024 * 1024
DEFAULT_DEST_NAME = "_organized"

DEMO_FILES: dict[str, str] = {
    "inbox/Quarterly Report.PDF": "%PDF-1.4\nFileFlow quarterly report 2026 Q3\n",
    "inbox/notes.txt": "Call vendor at 10:00\nRenew domain before Friday\n",
    "inbox/invoice_2024.csv": "invoice_id,client,amount\n1001,Acme Corp,1250.00\n1002,Globex,890.50\n",
    "downloads/installer_setup.exe": "MZ fake installer payload for demo purposes\n",
    "downloads/backup_archive.zip": "PK\x03\x04 demo archive payload\n",
    "downloads/song.mp3": "ID3 demo audio frame payload\n",
    "downloads/banner.png": "PNG-DEMO-BANNER-CONTENT identical copy\n",
    "media/IMG_0001.jpg": "JFIF demo photo payload of a mountain sunset\n",
    "media/banner.png": "PNG-DEMO-BANNER-CONTENT identical copy\n",
    "media/thumbnails/thumb_a.png": "PNG-DEMO-THUMB-A payload\n",
    "projects/etl/clean_data.py": '"""Demo ETL cleaner."""\n\ndef clean(rows):\n    return [r.strip() for r in rows]\n',
    "projects/etl/export_data.csv": "id,name\n1,alpha\n2,beta\n",
    "shared/contract.docx": "PK\x03\x04 demo master services agreement v2\n",
    "shared/contract signed.docx": "PK\x03\x04 demo master services agreement v2\n",
    "shared/empty.dat": "",
    "deep/nested/folder/readme.md": "# Deep folder\n\nThis file hides three levels deep.\n",
}


@dataclass(frozen=True)
class DemoStats:
    root: Path
    files: int
    bytes: int
    categories: int


@dataclass(frozen=True)
class ApplyStats:
    moved: int
    skipped: int
    categories: tuple[str, ...]
    pruned_dirs: int


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_contained(root: Path, target: Path) -> Path:
    """Resolve ``target`` and fail unless it lives inside ``root``."""
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved == root_resolved or root_resolved in target_resolved.parents:
        return target_resolved
    raise ValueError(f"path escapes directory {root_resolved}: {target_resolved}")


def require_dir(path: Path | str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise ValueError(f"not a directory: {resolved}")
    return resolved


def resolve_dest(root: Path, dest: str | Path | None) -> Path:
    """Pick the organized-output directory and prove it nests under root."""
    root_resolved = root.resolve()
    candidate = Path(dest) if dest else Path(DEFAULT_DEST_NAME)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    resolved = assert_contained(root_resolved, candidate)
    if resolved == root_resolved:
        raise ValueError("destination must be a subdirectory of DIR, not DIR itself")
    return resolved


def init_demo(target: Path | str) -> DemoStats:
    """Create the seeded demo workspace; refuse to overwrite an existing one."""
    root = Path(target).resolve()
    if root.exists():
        if not root.is_dir():
            raise ValueError(f"not a directory: {root}")
        if any(root.iterdir()):
            raise ValueError(f"directory is not empty: {root}")
    else:
        root.mkdir(parents=True)

    total = 0
    for relative, content in DEMO_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        path.write_bytes(data)
        total += len(data)

    categories = {categorize(name) for name in DEMO_FILES}
    return DemoStats(
        root=root,
        files=len(DEMO_FILES),
        bytes=total,
        categories=len(categories),
    )


def scan(root: Path, exclude: Path | None = None) -> list[FileEntry]:
    """Hash every regular file under ``root``, skipping the excluded subtree."""
    root_resolved = root.resolve()
    excluded = exclude.resolve() if exclude else None
    entries: list[FileEntry] = []
    for path in sorted(root_resolved.rglob("*"), key=lambda p: p.as_posix()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if excluded is not None and (resolved == excluded or excluded in resolved.parents):
            continue
        entries.append(
            FileEntry(path=resolved, size=resolved.stat().st_size, sha256=sha256_of(resolved))
        )
    return entries


def _prune_empty_dirs(root: Path, keep: Path) -> int:
    pruned = 0
    directories = sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for directory in directories:
        if directory == keep or keep in directory.parents:
            continue
        try:
            directory.rmdir()
            pruned += 1
        except OSError:
            continue
    return pruned


def apply_plan(plan: Plan) -> ApplyStats:
    """Execute a plan: move files into category folders, never outside root."""
    root = plan.root
    dest_base = assert_contained(root, root / plan.dest_base)

    moved = 0
    skipped = 0
    created: set[str] = set()

    for action in plan.actions:
        if action.action == ACTION_SKIP_DUPLICATE:
            skipped += 1
            continue
        source = assert_contained(root, root / action.src)
        destination = assert_contained(root, root / action.dest)
        if not source.is_file():
            raise FileNotFoundError(f"source disappeared: {action.src}")
        if destination.exists():
            raise FileExistsError(f"destination already exists: {action.dest}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        created.add(action.category)
        moved += 1

    pruned = _prune_empty_dirs(root, dest_base)
    ordered_categories = tuple(c for c in CATEGORY_ORDER if c in created)
    return ApplyStats(
        moved=moved,
        skipped=skipped,
        categories=ordered_categories,
        pruned_dirs=pruned,
    )
