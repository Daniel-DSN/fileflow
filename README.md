# FileFlow

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-38%20passed-brightgreen)](#testing)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Deps](https://img.shields.io/badge/dependencies-zero-orange)](#quick-start)

**Deterministic folder organizer with dry-run planning, duplicate detection and CSV reports.**

Point it at a messy directory, preview exactly what would move where, then execute with one confirmed command.

```
messy DIR → plan (table, zero writes) → apply --yes → DIR/_organized/{images,docs,audio,data,code,archives,other}
```

---

## Why this exists

"Download (3).pdf", `IMG_2847.JPG` in six folders, three copies of the same contract —
manual folder tidying is slow, irreversible when done badly, and impossible to audit.
FileFlow does the boring half safely:

- **Plan first, touch nothing** — `plan` is a true dry run: hashes, categories and destinations are computed, disk is untouched
- **7 categories** from an extension map: images / docs / audio / data / code / archives / other
- **Duplicate detection by sha256** — byte-identical files are never copied twice; the 2nd+ occurrence is `skip_duplicate`
- **Optional rename** to `NNN_name.ext` — slugified, lowercased, zero-padded per category (or per extension with `--by ext`)
- **Refuses to run without `--yes`** and asserts every source and destination stays inside `DIR`
- **CSV report** with size and short hash — an audit trail of what happened

## Quick start

No third-party packages — Python 3.10+ standard library only.

```bash
PYTHONPATH=src python3 -m fileflow.cli --help
PYTHONPATH=src python3 -m fileflow.cli plan  ./inbox --rename   # dry run
PYTHONPATH=src python3 -m fileflow.cli apply ./inbox --yes --rename
```

Build the seeded demo workspace (16 files, 2 duplicate pairs, nested folders,
a file with spaces/UPPERCASE, an empty file):

```bash
python3 -m fileflow.cli init-demo demo/demo_workspace
```

## Full CLI

| Command | Purpose |
|---------|---------|
| `fileflow init-demo DIR` | create the messy but deterministic demo workspace |
| `fileflow plan DIR` | dry run — print `action / src / dest` table, write nothing |
| `--rename` | rename to `NNN_name.ext` (slugified, zero-padded) |
| `--by type\|ext` | rename sequence per category (default) or per extension |
| `--dest DEST` | output folder inside DIR (default: `DIR/_organized`) |
| `fileflow apply DIR --yes` | execute the plan; without `--yes` → exit 1 + hint |
| `fileflow report DIR -o report.csv` | CSV: `file, category, size_bytes, sha256_8, action` |

Exit codes: `0` success, `1` error (missing dir, unsafe `--dest`, `apply` without `--yes`).

### What a plan looks like (excerpt — full table in [`demo/demo_run1.txt`](demo/demo_run1.txt))

```
$ python3 -m fileflow.cli plan demo/demo_workspace --rename
FileFlow 1.0.0 — plan for demo/demo_workspace
  by=type rename=yes dest=_organized
ACTION          SRC                            DEST
--------------  -----------------------------  ------------------------------------------
move            deep/nested/folder/readme.md   _organized/docs/001_readme.md
move            downloads/backup_archive.zip   _organized/archives/001_backup_archive.zip
move            inbox/Quarterly Report.PDF     _organized/docs/002_quarterly_report.pdf
move            media/IMG_0001.jpg             _organized/images/002_img_0001.jpg
skip_duplicate  media/banner.png               -
skip_duplicate  shared/contract.docx           -
[stats] 16 files · 14 move · 2 skip_duplicate · 7 categories
[dry-run] nothing was written — run `apply demo/demo_workspace --yes` to execute
```

## Safety policy

| Guarantee | How |
|-----------|-----|
| Dry run by default | `plan` only reads; `apply` requires `--yes` or exits 1 |
| No writes outside DIR | every src and dest is `resolve()`d and asserted inside the root |
| `--dest` must nest in DIR | `--dest /elsewhere` or `--dest .` → error, exit 1 |
| Output dir never re-scanned | `_organized` (or `--dest`) subtree is excluded from planning |
| Duplicates never multiplied | sha256 match → `skip_duplicate`, original stays in place |
| Collisions handled | same target name from two folders → `name_2.ext` |
| No blind overwrite | existing destination file → error instead of clobbering |
| Empty leftovers cleaned | vacated folders are pruned bottom-up after `apply` |

## Live demo (real captured output)

Everything below is committed under [`demo/`](demo) — raw terminal captures, not edited:

| File | Contents |
|------|----------|
| [`demo/demo_run1.txt`](demo/demo_run1.txt) | `init-demo` + listing **before** + full plan table |
| [`demo/demo_run2.txt`](demo/demo_run2.txt) | refusal without `--yes` (exit 1) + `apply --yes` + listing **after** |
| [`demo/demo_run3.txt`](demo/demo_run3.txt) | `report -o demo/report.csv` + the CSV itself |
| [`demo/report.csv`](demo/report.csv) | 16-row audit report |
| [`demo/demo_workspace/`](demo/demo_workspace) | the organized workspace |

Real numbers from those runs:

| Metric | Value |
|--------|-------|
| Files seeded / scanned | **16** (635 bytes) |
| Moved into categories | **14** |
| Duplicates skipped | **2** (`banner.png`, `contract.docx`) |
| Categories created | **7** |
| Empty dirs pruned | **8** |
| Report rows | **16** (14 `organized` + 2 `skip_duplicate`) |

```
$ python3 -m fileflow.cli apply demo/demo_workspace --yes --rename
[skip] media/banner.png (duplicate of downloads/banner.png)
[skip] shared/contract.docx (duplicate of shared/contract signed.docx)
[stats] 14 moved · 2 duplicates skipped · 7 categories created · 8 empty dirs pruned
[ok] organized → .../demo/demo_workspace/_organized

$ python3 -m fileflow.cli report demo/demo_workspace -o demo/report.csv
[stats] 16 files · 7 categories · 2 duplicates
[ok] 16 rows → demo/report.csv
```

Replay it from scratch:

```bash
make demo        # init-demo → plan → apply --yes → report
```

## Architecture

```
src/fileflow/
├── cli.py         argparse + commands (init-demo / plan / apply / report)
├── planner.py     pure: categorize, slugify, build_plan (paths + duplicates)
├── workspace.py   fs: seeded demo, sha256 scan, containment, apply + prune
└── report.py      CSV rows: pure to_csv(), fs write_csv()
```

- **Planning is pure** — `build_plan(root, dest, entries)` takes values and returns decisions → unit-tested with no disk
- **Filesystem is isolated** in `workspace.py` — hashing, moving and pruning are the only mutating functions
- **Every path is resolved and contained** before a single `mkdir`/`move` happens

## Testing

```bash
cd fileflow
PYTHONPATH=src python3 -m pytest -q
```

```
38 passed in 1.42s
```

Fully offline — tests build tiny fixtures under `tmp_path`. Coverage: extension
categorization, slugify, sequence numbering (`--by type` and `--by ext`),
collision dedupe, duplicate detection, dry-run guarantee, containment
rejections, demo determinism, apply + prune, CSV columns/round-trip and CLI
exit codes (including `apply` without `--yes`).

## Use cases

| Who | Uses FileFlow for |
|-----|-------------------|
| Freelancers | tidy client deliveries / exports before upload |
| Ops | scheduled download-folder cleanup (`apply --yes` from cron) |
| Data teams | split mixed exports into `csv/json/parquet` with hash audit |
| Support | deduplicate attachment dumps before archiving |
| Anyone | "my Desktop has 400 loose files" — one dry run, one confirm |

## License

MIT — see [LICENSE](LICENSE).
