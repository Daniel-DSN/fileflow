"""FileFlow command-line interface.

Commands
--------
    fileflow init-demo DIR
    fileflow plan   DIR [--by ext|type] [--rename] [--dest DEST]
    fileflow apply  DIR --yes [--by ext|type] [--rename] [--dest DEST]
    fileflow report DIR [-o report.csv] [--dest DEST]

Exit codes: 0 = success, 1 = error (including running apply without --yes).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .planner import ACTION_SKIP_DUPLICATE, Plan, PlannedAction, build_plan
from .report import build_rows, summarize, write_csv
from .workspace import apply_plan, init_demo, require_dir, resolve_dest, scan


def format_table(actions: Sequence[PlannedAction]) -> str:
    header = ("ACTION", "SRC", "DEST")
    body = [(a.action, a.src, a.dest or "-") for a in actions]
    widths = [
        max(len(row[column]) for row in (header, *body)) for column in range(len(header))
    ]

    def render(row: tuple[str, str, str]) -> str:
        cells = [row[i].ljust(widths[i]) for i in range(len(header))]
        return "  ".join(cells).rstrip()

    lines = [render(header), render(tuple("-" * w for w in widths))]
    lines.extend(render(row) for row in body)
    return "\n".join(lines)


def _plan_stats_line(plan: Plan) -> str:
    stats = plan.stats()
    return (
        f"[stats] {stats['files']} files · {stats['move']} move · "
        f"{stats['skip_duplicate']} skip_duplicate · {stats['categories']} categories"
    )


def _header(title: str, plan: Plan) -> str:
    mode = f"by={plan.by} rename={'yes' if plan.rename else 'no'} dest={plan.dest_base}"
    return f"FileFlow {__version__} — {title}\n  {mode}"


def _build_plan(args: argparse.Namespace) -> tuple[Plan, Path]:
    root = require_dir(args.dir)
    dest = resolve_dest(root, args.dest)
    files = scan(root, exclude=dest)
    plan = build_plan(root, dest, files, by=args.by, rename=args.rename)
    return plan, root


def cmd_init_demo(args: argparse.Namespace) -> int:
    stats = init_demo(Path(args.dir))
    print(f"FileFlow {__version__} — created demo workspace at {stats.root}")
    print(
        f"[stats] {stats.files} files · {stats.bytes} bytes · "
        f"{stats.categories} categories"
    )
    print(f"[ok] dry run: python -m fileflow.cli plan {args.dir} --rename")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    plan, root = _build_plan(args)
    print(_header(f"plan for {args.dir}", plan))
    if not plan.actions:
        print("[warn] no files found — nothing to plan", file=sys.stderr)
        return 1
    print(format_table(plan.actions))
    print(_plan_stats_line(plan))
    print(f"[dry-run] nothing was written — run `apply {args.dir} --yes` to execute")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    if not args.yes:
        print("[error] refusing to modify files without confirmation", file=sys.stderr)
        print(
            f"[hint] re-run with --yes: python -m fileflow.cli apply {args.dir} --yes --rename",
            file=sys.stderr,
        )
        return 1

    plan, root = _build_plan(args)
    print(_header(f"applying plan to {args.dir}", plan))
    if not plan.actions:
        print("[warn] no files found — nothing to apply", file=sys.stderr)
        return 1

    originals = {a.sha256: a.src for a in plan.moves}
    for action in plan.actions:
        if action.action == ACTION_SKIP_DUPLICATE:
            print(f"[skip] {action.src} (duplicate of {originals.get(action.sha256, '?')})")
        else:
            print(f"[move] {action.src} -> {action.dest}")

    stats = apply_plan(plan)
    print(
        f"[stats] {stats.moved} moved · {stats.skipped} duplicates skipped · "
        f"{len(stats.categories)} categories created · {stats.pruned_dirs} empty dirs pruned"
    )
    print(f"[ok] organized → {root / plan.dest_base}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = require_dir(args.dir)
    dest = resolve_dest(root, args.dest)
    rows = build_rows(root, dest)
    if not rows:
        print("[warn] no files found — empty report", file=sys.stderr)
        return 1

    stats = summarize(rows)
    print(f"FileFlow {__version__} — report for {args.dir}")
    print(
        f"[stats] {stats['files']} files · {stats['categories']} categories · "
        f"{stats['duplicates']} duplicates"
    )
    out = write_csv(rows, Path(args.output))
    print(f"[ok] {len(rows)} rows → {out}")
    return 0


def _add_plan_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--by",
        choices=["ext", "type"],
        default="type",
        help="rename sequence scope: per category (type) or per extension (ext)",
    )
    parser.add_argument(
        "--rename",
        action="store_true",
        help="rename files to NNN_name.ext (slugified, zero-padded per scope)",
    )
    parser.add_argument(
        "--dest",
        help="organized output directory inside DIR (default: DIR/_organized)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fileflow",
        description="Deterministic folder organizer with dry-run planning and CSV reports.",
    )
    parser.add_argument("--version", action="version", version=f"fileflow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("init-demo", help="create a messy but realistic demo workspace")
    demo.add_argument("dir", help="target directory (must be empty or missing)")
    demo.set_defaults(func=cmd_init_demo)

    plan = sub.add_parser("plan", help="dry run: print actions without touching disk")
    plan.add_argument("dir", help="directory to organize")
    _add_plan_flags(plan)
    plan.set_defaults(func=cmd_plan)

    apply_cmd = sub.add_parser("apply", help="execute a plan (requires --yes)")
    apply_cmd.add_argument("dir", help="directory to organize")
    apply_cmd.add_argument(
        "--yes",
        action="store_true",
        help="confirm that files may be moved (required)",
    )
    _add_plan_flags(apply_cmd)
    apply_cmd.set_defaults(func=cmd_apply)

    report = sub.add_parser("report", help="write a CSV inventory of DIR")
    report.add_argument("dir", help="directory to inventory")
    report.add_argument("-o", "--output", default="report.csv", help="output CSV path")
    report.add_argument(
        "--dest",
        help="organized output directory inside DIR (default: DIR/_organized)",
    )
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[abort] interrupted", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
