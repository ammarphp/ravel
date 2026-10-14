"""Refresh src/ravel/data/workflow from the canonical workflow instructions.

The package ships a byte-identical copy of every file in paths.WORKFLOW_INSTRUCTIONS;
hatch_build.py refuses a build when the copy differs or carries an undeclared file.
Run after editing any declared instruction:

    python scripts/maintenance/sync_instruction_bundle.py          # write
    python scripts/maintenance/sync_instruction_bundle.py --check  # report only, exit 1 on drift
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ravel.paths import WORKFLOW_INSTRUCTIONS  # noqa: E402

BUNDLE = ROOT / "src/ravel/data/workflow"


def drift():
    declared = set(WORKFLOW_INSTRUCTIONS)
    bundled = {p.relative_to(BUNDLE).as_posix() for p in BUNDLE.rglob("*") if p.is_file()}
    stale = sorted(l for l in declared if not (BUNDLE / l).is_file()
                   or (BUNDLE / l).read_bytes() != (ROOT / l).read_bytes())
    return stale, sorted(bundled - declared)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale, extra = drift()
    if args.check:
        for logical in stale:
            print("stale:", logical)
        for logical in extra:
            print("undeclared:", logical)
        return 1 if stale or extra else 0
    for logical in stale:
        target = BUNDLE / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / logical, target)
    for logical in extra:
        (BUNDLE / logical).unlink()
    print(f"synced {len(stale)}, removed {len(extra)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
