"""Pure planning logic for FileFlow.

Callers hand in scanned file entries; this module returns a deterministic
plan of actions. No filesystem reads or writes happen here, so the whole
decision layer is unit-testable with plain values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

CATEGORY_ORDER: tuple[str, ...] = (
    "images",
    "docs",
    "audio",
    "data",
    "code",
    "archives",
    "other",
)

EXTENSION_CATEGORY: dict[str, str] = {}
for _category, _extensions in {
    "images": ("jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tiff", "heic"),
    "docs": ("pdf", "doc", "docx", "txt", "md", "rtf", "odt", "ppt", "pptx", "xls", "xlsx"),
    "audio": ("mp3", "wav", "flac", "ogg", "m4a", "aac"),
    "data": ("csv", "tsv", "json", "xml", "parquet", "sqlite"),
    "code": ("py", "js", "ts", "html", "css", "sql", "sh", "java", "cpp", "rb", "go", "rs"),
    "archives": ("zip", "tar", "gz", "rar", "7z", "bz2"),
}.items():
    for _ext in _extensions:
        EXTENSION_CATEGORY[_ext] = _category

ACTION_MOVE = "move"
ACTION_SKIP_DUPLICATE = "skip_duplicate"
ACTION_ORGANIZED = "organized"

BY_CHOICES: tuple[str, ...] = ("type", "ext")

_UNSAFE_CHARS = re.compile(r"[^a-z0-9]+")


def categorize(path: Path | str) -> str:
    """Map a filename to its category using the extension table."""
    extension = Path(path).suffix.lower().lstrip(".")
    return EXTENSION_CATEGORY.get(extension, "other")


def slugify(name: str) -> str:
    """Lowercase a stem and collapse anything unsafe to underscores."""
    slug = _UNSAFE_CHARS.sub("_", name.lower()).strip("_")
    return slug or "file"


def _unique_dest(candidate: str, used: set[str]) -> str:
    if candidate not in used:
        return candidate
    path = Path(candidate)
    counter = 2
    while True:
        alt = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if alt.as_posix() not in used:
            return alt.as_posix()
        counter += 1


@dataclass(frozen=True)
class FileEntry:
    """One scanned file: absolute path plus content facts."""

    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class PlannedAction:
    """A single decision: what happens to one source file."""

    action: str
    src: str
    dest: str
    category: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Plan:
    """Ordered, deterministic list of actions rooted at ``root``."""

    root: Path
    dest_base: str
    by: str
    rename: bool
    actions: tuple[PlannedAction, ...]

    @property
    def moves(self) -> tuple[PlannedAction, ...]:
        return tuple(a for a in self.actions if a.action == ACTION_MOVE)

    @property
    def duplicates(self) -> tuple[PlannedAction, ...]:
        return tuple(a for a in self.actions if a.action == ACTION_SKIP_DUPLICATE)

    @property
    def categories(self) -> tuple[str, ...]:
        seen = {a.category for a in self.actions}
        ordered = [c for c in CATEGORY_ORDER if c in seen]
        return tuple(ordered)

    def stats(self) -> dict[str, int]:
        return {
            "files": len(self.actions),
            "move": len(self.moves),
            "skip_duplicate": len(self.duplicates),
            "categories": len(self.categories),
        }


def _relativize(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes directory {root}: {path}") from exc


def build_plan(
    root: Path,
    dest_base: Path,
    files: Sequence[FileEntry],
    *,
    by: str = "type",
    rename: bool = False,
) -> Plan:
    """Decide where every scanned file should go.

    ``root`` and ``dest_base`` must already be absolute and validated;
    every source entry is asserted to live inside ``root``.
    """
    if by not in BY_CHOICES:
        raise ValueError(f"unsupported grouping: {by!r} (choose from {', '.join(BY_CHOICES)})")

    root_resolved = root.resolve()
    dest_resolved = dest_base.resolve()
    if dest_resolved == root_resolved:
        raise ValueError("destination must be a subdirectory of DIR, not DIR itself")
    dest_base_rel = _relativize(root_resolved, dest_resolved)

    ordered = sorted(files, key=lambda entry: entry.path.as_posix())
    seen_hashes: dict[str, str] = {}
    counters: dict[str, int] = {}
    used_dests: set[str] = set()
    actions: list[PlannedAction] = []

    for entry in ordered:
        src_rel = _relativize(root_resolved, entry.path)
        category = categorize(src_rel)

        if entry.sha256 in seen_hashes:
            actions.append(
                PlannedAction(
                    action=ACTION_SKIP_DUPLICATE,
                    src=src_rel,
                    dest="",
                    category=category,
                    size=entry.size,
                    sha256=entry.sha256,
                )
            )
            continue
        seen_hashes[entry.sha256] = src_rel

        source = Path(src_rel)
        if rename:
            extension = source.suffix.lower()
            scope = category if by == "type" else (extension or "none")
            counters[scope] = counters.get(scope, 0) + 1
            filename = f"{counters[scope]:03d}_{slugify(source.stem)}{extension}"
        else:
            filename = source.name

        dest_path = _unique_dest(f"{dest_base_rel}/{category}/{filename}", used_dests)
        used_dests.add(dest_path)
        actions.append(
            PlannedAction(
                action=ACTION_MOVE,
                src=src_rel,
                dest=dest_path,
                category=category,
                size=entry.size,
                sha256=entry.sha256,
            )
        )

    return Plan(
        root=root_resolved,
        dest_base=dest_base_rel,
        by=by,
        rename=rename,
        actions=tuple(actions),
    )
