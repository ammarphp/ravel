#!/usr/bin/env python3
"""framework/verify_fixes.py — the ONE aggregated `verify:` board for the audit-and-fix CRs.

The hybrid verification layer (Task 9): the durable green is a DETERMINISTIC command per
audit-and-fix item (CR-030..CR-043 in `framework/CHANGES-REGISTRY.md`), not a hand-maintained
second JSON. This script parses each CR's `- **Verify:** \\`<cmd>\\`` line, runs the command as a
subprocess FROM THE REPO ROOT, and prints one board:

    CR-NNN | <verify cmd> | PASS/FAIL

Exit 0 iff every runnable verify passed; exit 1 listing the failures. This is the ONE aggregated
board — no `verification_board.json` (or any other second source of truth) is written to disk.
`framework/CODEX-RECOMPUTE.md` is the recipe for an external panel to reproduce this same board
from the shipped, deterministic scripts.

A verify value that starts with `(decision` or `(deferred` is an INFORMATIONAL marker, not a
command — it is never executed as a subprocess, and always counts as PASS (it documents a
CR with no testable artifact, e.g. a declined build, or a build not yet landed).

Usage:
    python3 framework/verify_fixes.py             # human board, exit 0/1
    python3 framework/verify_fixes.py --json       # machine board on stdout, same exit code
    python3 framework/verify_fixes.py --registry P # override CHANGES-REGISTRY.md path (tests)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "framework" / "CHANGES-REGISTRY.md"

# The audit-and-fix batch this board covers (2026-07-08): the PRODUCT-CONTRACT scope-only
# registrations (CR-030..036) plus the builds that land/embed them (CR-037..043).
CR_RANGE = tuple(f"CR-{n:03d}" for n in range(30, 44))  # CR-030..CR-043 inclusive

_HEADING_RE = re.compile(r"^#{2,3}\s")
_CR_HEADING_RE = re.compile(r"^###\s+(CR-\d{3})\b")

# Non-greedy: capture only the FIRST backtick-delimited span after the `**Verify:**` label — a CR
# entry may append trailing prose (a caveat, a cross-reference) after the closing backtick, which
# may itself contain further backticked tokens; that trailing prose is not part of the command.
_VERIFY_LINE_RE = re.compile(r"^\s*-\s*\*\*Verify:\*\*\s*`(.+?)`")

DEFAULT_TIMEOUT_S = 600


def parse_verify_entries(text: str) -> dict:
    """Return {CR-NNN: verify_cmd_string} for every `### CR-NNN` section (NNN in CR_RANGE) that
    carries a `- **Verify:** \\`...\\`` line before the next `##`/`###` heading."""
    entries: dict[str, str] = {}
    current_cr = None
    for line in text.splitlines():
        cr_heading = _CR_HEADING_RE.match(line)
        if cr_heading:
            current_cr = cr_heading.group(1)
            continue
        if _HEADING_RE.match(line):
            current_cr = None
            continue
        if current_cr is not None and current_cr in CR_RANGE:
            m = _VERIFY_LINE_RE.match(line)
            if m:
                entries[current_cr] = m.group(1).strip()
    return entries


def is_informational(cmd: str) -> bool:
    stripped = cmd.strip()
    return stripped.startswith("(decision") or stripped.startswith("(deferred")


def run_verify(cr_id: str, cmd: str, timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    """Run one CR's verify command from the repo root. A `(decision...)`/`(deferred...)` marker
    is never shelled out to — it is an informational PASS by construction."""
    if is_informational(cmd):
        return {"cr": cr_id, "cmd": cmd, "status": "PASS", "informational": True,
                "returncode": None, "stderr_tail": ""}
    try:
        result = subprocess.run(cmd, shell=True, cwd=REPO_ROOT, capture_output=True, text=True,
                                 timeout=timeout)
        returncode = result.returncode
        stderr_tail = result.stderr[-2000:] if returncode != 0 else ""
    except subprocess.TimeoutExpired:
        returncode = None
        stderr_tail = f"TIMEOUT after {timeout}s"
    status = "PASS" if returncode == 0 else "FAIL"
    return {"cr": cr_id, "cmd": cmd, "status": status, "informational": False,
            "returncode": returncode, "stderr_tail": stderr_tail}


def build_board(registry_path: Path) -> list:
    text = registry_path.read_text()
    entries = parse_verify_entries(text)
    return [run_verify(cr, cmd) for cr, cmd in sorted(entries.items())]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="machine-readable board on stdout")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY),
                         help="override framework/CHANGES-REGISTRY.md path (test hook)")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    registry_path = Path(args.registry)
    if not registry_path.is_file():
        print(f"verify_fixes: registry not found: {registry_path}", file=sys.stderr)
        return 1

    results = build_board(registry_path)

    if not results:
        print(f"verify_fixes: no `- **Verify:**` lines found for {CR_RANGE[0]}..{CR_RANGE[-1]} "
              f"in {registry_path}", file=sys.stderr)
        return 1

    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    all_pass = n_fail == 0

    if args.json:
        print(json.dumps({"registry": str(registry_path), "results": results,
                           "n_pass": n_pass, "n_fail": n_fail, "all_pass": all_pass}, indent=2))
    else:
        for r in results:
            tag = "  (informational)" if r["informational"] else ""
            print(f"{r['cr']} | {r['cmd']} | {r['status']}{tag}")
        print(f"\nverify_fixes: {n_pass} PASS / {n_fail} FAIL of {len(results)} CR(s)")
        if not all_pass:
            print("\nFAILing:")
            for r in results:
                if r["status"] == "FAIL":
                    print(f"  {r['cr']}: {r['cmd']}  (exit {r['returncode']})")
                    if r["stderr_tail"]:
                        print(f"    stderr: {r['stderr_tail'].strip()[-500:]}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
