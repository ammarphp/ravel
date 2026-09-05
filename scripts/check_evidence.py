#!/usr/bin/env python3
"""Verify evidence/manifest.json against real files on disk -- PRODUCT-CONTRACT section 7
(CR-030): every SHIPPED headline/served claim must have >=1 present, sha256-matching artifact, or
this exits 1. The read-only counterpart to `scripts/build_evidence.py` (the writer).

Runs against the DEV tree by default (`--root` defaults to the repo root); Task 6.2's export
stage gate calls `--check --root $STAGE` against the staged export tree, where dev-only
(`trial-runs/2026-*`, `trial-runs/sleptonscan_*`) artifacts are EXPECTED to be absent by policy
(`docs/development/distribution.md`) -- that absence is tolerated exactly when the claim still carries a
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
    python3 scripts/check_evidence.py [--check] [--root DIR]
    python3 scripts/check_evidence.py --write            # delegates to build_evidence.py
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
from ravel import evidence_layout

MANIFEST_NAME = "evidence/manifest.json"
SERVED_STATUSES = ("served", "served-with-refusal")
STATUSES = {*SERVED_STATUSES, "partial", "unbuilt", "blocked", "historical"}


def _structure_errors(claim):
    """Reject malformed metadata before it can weaken an integrity obligation."""
    if not isinstance(claim, dict):
        return ["claim must be an object"]
    errors = []
    if not isinstance(claim.get("claim_id"), str) or not claim["claim_id"].strip():
        errors.append("claim_id must be a nonempty string")
    if not isinstance(claim.get("status"), str) or claim["status"] not in STATUSES:
        errors.append("unknown or missing claim status")
    artifacts = claim.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return errors + ["artifacts must be a nonempty list"]
    seen = set()
    for a in artifacts:
        if not isinstance(a, dict):
            errors.append("artifact must be an object")
            continue
        path = a.get("path")
        if (not isinstance(path, str) or not path or "\\" in path
                or "\x00" in path or PurePosixPath(path).is_absolute()
                or any(p in ("", ".", "..") for p in path.split("/"))):
            errors.append("artifact path must be a normalized repository-relative path")
        elif path in seen:
            errors.append(f"duplicate artifact path {path!r}")
        else:
            seen.add(path)
        if not isinstance(a.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", a["sha256"]):
            errors.append("artifact sha256 must be 64 lowercase hexadecimal characters")
        if type(a.get("shipped")) is not bool or type(a.get("dev_only")) is not bool:
            errors.append("artifact shipped/dev_only must be booleans")
        elif a["shipped"] == a["dev_only"]:
            errors.append("artifact shipped/dev_only must be complements")
        if type(a.get("bytes")) is not int or a["bytes"] < 0:
            errors.append("artifact bytes must be a nonnegative integer")
    return errors


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON number {value}")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _present_matching(artifact, root):
    """Returns (ok: bool, why: str) for one manifest artifact record re-checked under `root`."""
    try:
        full = evidence_layout.resolve(root, artifact["path"])
        if "source_path" in artifact and artifact["source_path"] != evidence_layout.source_path(artifact["path"], root):
            return False, "source_path differs from explicit layout registry"
        Path(full).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError, RuntimeError):
        return False, "path escapes artifact root (including symlinks)"
    if not os.path.isfile(full):
        return False, "missing"
    try:
        got = sha256_of(full)
    except OSError as e:
        return False, f"unreadable: {e}"
    if got != artifact.get("sha256"):
        want = str(artifact.get("sha256"))[:12]
        return False, f"sha256 mismatch (manifest {want}, on-disk {got[:12]})"
    if os.path.getsize(full) != artifact["bytes"]:
        return False, "byte count mismatch"
    return True, "ok"


def check_claim(claim, root):
    """Re-verifies every artifact of one manifest claim against `root`. Returns
    (verdict, detail) with verdict in ('PASS', 'WARN', 'FAIL')."""
    errors = _structure_errors(claim)
    if errors:
        return "FAIL", "; ".join(errors)
    artifacts = claim["artifacts"]
    per_artifact = [(a, *_present_matching(a, root)) for a in artifacts]
    if any("escapes artifact root" in why or "source_path differs" in why for _a, _ok, why in per_artifact):
        return "FAIL", "artifact path escapes artifact root (including symlinks)"

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
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int \
            or manifest["schema_version"] != 1:
        return [("manifest", "FAIL", "schema_version must be integer 1")]
    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        return [("manifest", "FAIL", "claims must be a nonempty list")]
    rows, seen = [], set()
    for c in claims:
        cid = c.get("claim_id", "?") if isinstance(c, dict) else "?"
        if not isinstance(cid, str):
            cid = "?"
        if cid in seen:
            rows.append((cid, "FAIL", "duplicate claim_id"))
        else:
            rows.append((cid, *check_claim(c, root)))
        seen.add(cid)
    return rows


def _source_specs(root):
    spec = importlib.util.spec_from_file_location("ravel_evidence_sources", os.path.join(HERE, "build_evidence.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with open(os.path.join(root, "benchmarks/capabilities.json")) as f:
        matrix = json.load(f, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    with open(os.path.join(root, "benchmarks/cases.json")) as f:
        cases = json.load(f, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    specs = module.enumerate_specs(matrix, cases)
    return [(s, [evidence_layout.public_path(path, root) for path, _role in s["candidates"] if module.is_shipped(path, root)]) for s in specs]


def check_completeness(manifest, root):
    """A locally coherent manifest cannot silently drop or downgrade source claims."""
    try:
        specs = _source_specs(root)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return [("sources", "FAIL", f"cannot enumerate authoritative claims: {exc}")]
    expected = {s["claim_id"]: (s, required) for s, required in specs}
    actual = {c["claim_id"]: c for c in manifest["claims"]}
    rows = []
    if set(expected) != set(actual):
        rows.append(("sources", "FAIL", f"claim set mismatch: missing={sorted(set(expected)-set(actual))}; "
                     f"extra={sorted(set(actual)-set(expected))}"))
    for cid in expected.keys() & actual.keys():
        source, required = expected[cid]
        claim = actual[cid]
        shipped = {a["path"] for a in claim["artifacts"] if a["shipped"]}
        if claim["status"] != source["status"]:
            rows.append((cid, "FAIL", "claim status disagrees with authoritative source"))
        if not set(required) <= shipped:
            rows.append((cid, "FAIL", f"mandatory shipped evidence omitted: {sorted(set(required)-shipped)}"))
    return rows


def cmd_check(args):
    root = os.path.abspath(args.root) if args.root else ROOT
    # --root selects BOTH the manifest and the artifacts. Checking the source manifest
    # against staged files could otherwise bless a missing or doctored staged manifest.
    manifest_path = os.path.join(root, MANIFEST_NAME)
    if not os.path.exists(manifest_path):
        print(f"check_evidence --check: FAIL -- {manifest_path} does not exist "
              f"(run `python3 scripts/build_evidence.py --write` first)", file=sys.stderr)
        return 1
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f, object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
    except (OSError, ValueError) as e:
        print(f"check_evidence --check: FAIL -- {manifest_path} unreadable/invalid JSON: {e}",
              file=sys.stderr)
        return 1

    rows = check_manifest(manifest, root)
    if not any(v == "FAIL" for _, v, _ in rows):
        rows += check_completeness(manifest, root)
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
                     help="(default action regardless of this flag) verify evidence/manifest.json"
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
