#!/usr/bin/env python3
"""Compatibility alias: --plan prints the installer plan, --check runs `ravel doctor`.

Prefer `bash scripts/setup/install.sh --plan` and `ravel doctor` directly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ravel.setup import doctor, installer  # noqa: E402
from ravel.setup import manifest as mf  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--mode", help="limit to the groups one science mode needs")
    parser.add_argument("--profile")
    parser.add_argument("--prefix")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        forwarded = ["--json"] + (["--mode", args.mode] if args.mode else []) + \
            (["--profile", args.profile] if args.profile else []) + (["--prefix", args.prefix] if args.prefix else []) + \
            (["--strict"] if args.strict else [])
        return doctor.main(forwarded, repo=ROOT)
    manifest, catalog = mf.load(ROOT)
    groups = doctor.select_groups(manifest, profile=args.profile, mode=args.mode)
    tool = installer.Installer(ROOT, installer.resolve_prefix(ROOT, args.prefix), manifest=manifest, catalog=catalog)
    print(json.dumps(tool.plan(only=groups), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
