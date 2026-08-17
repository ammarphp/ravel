#!/usr/bin/env python3
"""Verify evidence_manifest.json against real files on disk -- PRODUCT-CONTRACT section 7
(CR-030): every SHIPPED headline/served claim must have >=1 present, sha256-matching artifact, or
this exits 1. The read-only counterpart to `framework/build_evidence.py` (the writer).

Runs against the DEV tree by default (`--root` defaults to the repo root); Task 6.2's export
stage gate calls `--check --root $STAGE` against the staged export tree, where dev-only
(`trial-runs/2026-*`, `trial-runs/sleptonscan_*`) artifacts are EXPECTED to be absent by policy
(`workflow/DISTRIBUTION.md`) -- that absence is tolerated exactly when the claim still carries a
present+matching `shipped:true` surrogate artifact.

Per-claim verdict (PASS / WARN / FAIL), evaluated over every artifact recorded for that claim:
  FAIL  1. any artifact recorded `shipped: true` is missing, or its sha256 no longer matches,
           under --root -- a `shipped:true` label is a hard promise regardless of dev-tree vs.
           stage root.
        2. a claim whose status is `served`/`served-with-refusal` has ZERO present+sha-matching
           artifacts under --root (a `dev_only:true` artifact absent under a stage root is fine
           exactly when rule 1's shipped artifact/surrogate is intact -- THAT is the required
           >=1 present+matching artifact).
  WARN  a `partial`-status claim whose artifact list is ALL dev_only (no shipped artifact at
        all) -- structurally under-evidenced for public audit, but a partial claim is not held
        to the served bar.
  PASS  everything else (including any claim status outside served/served-with-refusal/partial,
        which is not held to any bar here).

Usage:
    python3 framework/check_evidence.py [--check] [--root DIR]
    python3 framework/check_evidence.py --write            # delegates to build_evidence.py
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST_NAME = "evidence_manifest.json"
SERVED_STATUSES = ("served", "served-with-refusal")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _present_matching(artifact, root):
    """Returns (ok: bool, why: str) for one manifest artifact record re-checked under `root`."""
    full = os.path.join(root, artifact["path"])
    if not os.path.isfile(full):
        return False, "missing"
    try:
        got = sha256_of(full)
    except OSError as e:
        return False, f"unreadable: {e}"
    if got != artifact.get("sha256"):
        want = str(artifact.get("sha256"))[:12]
        return False, f"sha256 mismatch (manifest {want}, on-disk {got[:12]})"
    return True, "ok"


def check_claim(claim, root):
    """Re-verifies every artifact of one manifest claim against `root`. Returns
    (verdict, detail) with verdict in ('PASS', 'WARN', 'FAIL')."""
    artifacts = claim.get("artifacts", [])
    per_artifact = [(a, *_present_matching(a, root)) for a in artifacts]

    shipped_fails = [f"shipped artifact {a['path']!r} {why}"
                      for a, ok, why in per_artifact if a.get("shipped") and not ok]
    if shipped_fails:
        return "FAIL", "; ".join(shipped_fails)

    ok_count = sum(1 for _a, ok, _why in per_artifact if ok)
    status = claim.get("status")
    stale = [f"{a['path']!r} ({why})" for a, ok, why in per_artifact
             if not ok and not a.get("shipped")]
    stale_note = f"; {len(stale)} dev-only artifact(s) not present+matching (not fatal): {stale}" \
        if stale else ""

    if status in SERVED_STATUSES:
        if ok_count == 0:
            return "FAIL", f"'{status}' claim has no present+sha-matching artifact under {root}"
        return "PASS", f"{ok_count}/{len(artifacts)} artifact(s) present+matching{stale_note}"

    if status == "partial":
        if not any(a.get("shipped") for a in artifacts):
            return "WARN", "partial claim has only dev-only artifacts (no public surrogate)"
        return "PASS", f"partial claim carries a shipped artifact{stale_note}"

    return "PASS", f"status={status!r} not held to the served bar{stale_note}"


def check_manifest(manifest, root):
    return [(c.get("claim_id", "?"), *check_claim(c, root)) for c in manifest.get("claims", [])]


def cmd_check(args):
    manifest_path = os.path.join(ROOT, MANIFEST_NAME)
    if not os.path.exists(manifest_path):
        print(f"check_evidence --check: FAIL -- {manifest_path} does not exist "
              f"(run `python3 framework/build_evidence.py --write` first)", file=sys.stderr)
        return 1
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        print(f"check_evidence --check: FAIL -- {manifest_path} unreadable/invalid JSON: {e}",
              file=sys.stderr)
        return 1

    root = os.path.abspath(args.root) if args.root else ROOT
    rows = check_manifest(manifest, root)
    if not rows:
        print("check_evidence --check: FAIL -- manifest carries zero claims", file=sys.stderr)
        return 1

    any_fail = False
    for claim_id, verdict, detail in rows:
        print(f"[{verdict}] {claim_id}: {detail}")
        any_fail = any_fail or (verdict == "FAIL")

    n = len(rows)
    n_fail = sum(1 for _c, v, _d in rows if v == "FAIL")
    n_warn = sum(1 for _c, v, _d in rows if v == "WARN")
    n_pass = n - n_fail - n_warn
    print(f"\ncheck_evidence: {n_pass} PASS / {n_warn} WARN / {n_fail} FAIL of {n} claim(s), "
          f"root={root}")
    return 1 if any_fail else 0


def cmd_write():
    build_evidence = os.path.join(HERE, "build_evidence.py")
    r = subprocess.run([sys.executable, build_evidence, "--write"], cwd=ROOT)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                     help="(default action regardless of this flag) verify evidence_manifest.json"
                          " against --root")
    ap.add_argument("--write", action="store_true",
                     help="delegate to build_evidence.py --write, then exit with its code")
    ap.add_argument("--root", default=None,
                     help="tree to verify artifacts against (default: repo root; the export-stage"
                          " gate passes the staged tree here)")
    args = ap.parse_args()

    if args.write:
        sys.exit(cmd_write())
    sys.exit(cmd_check(args))


if __name__ == "__main__":
    main()
