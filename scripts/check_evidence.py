#!/usr/bin/env python3
"""Verify evidence/manifest.json against real files on disk -- docs/reference/scope.md section 7
(CR-030): every SHIPPED headline/served claim must have >=1 present, sha256-matching artifact, or
this exits 1. The read-only counterpart to `scripts/build_evidence.py` (the writer).

Runs against this tree by default (`--root` defaults to the repo root); `--root DIR` checks another
tree. In this repository, historical artifacts that it does not carry (`trial-runs/2026-*`,
`trial-runs/sleptonscan_*`) are EXPECTED to be absent by policy (the registry,
`evidence/collections.json`) -- that absence is tolerated exactly when the
claim still carries a present+matching `shipped:true` surrogate artifact.

Per-claim verdict (PASS / WARN / FAIL), evaluated over every artifact recorded for that claim:
  FAIL  1. any artifact recorded `shipped: true` is missing, or its sha256 no longer matches,
           under --root -- a `shipped:true` label is a hard promise in every tree.
        2. a served or refusal claim has ZERO present+sha-matching
           artifacts under --root (an undistributed `dev_only:true` artifact absent under --root is fine
           exactly when rule 1's shipped artifact/surrogate is intact -- THAT is the required
           >=1 present+matching artifact).
  WARN  a `partial`-status claim whose artifact list is ALL `dev_only` (no shipped artifact at
        all) -- structurally under-evidenced for public audit, but a partial claim is not held
        to the served bar.
  PASS  other structurally valid claims. A custody PASS for a refusal is not
        delivery credit; capability scoring assesses that separately.

Curated records: `evidence/curation.json` maps each hash-pinned or historical record whose wording
was curated from its original identity to its curated one. A
manifest artifact whose curated copy ships keeps its original digest in the manifest and matches
only as exactly the curated copy that the record maps from it.
Every entry's pinning records must still carry the original digest, and each curated file must
have exactly its curated identity (`evidence_layout.curation_errors`).

Public mode (`--public`, automatic in this repository): no manifest artifact or claim source names
material outside the distribution selection.

Usage:
    python3 scripts/check_evidence.py [--check] [--root DIR] [--public]
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
EVIDENCE_REQUIRED_STATUSES = ("served", "served-with-refusal", "refused")
STATUSES = {*EVIDENCE_REQUIRED_STATUSES, "partial", "unbuilt", "blocked", "historical"}


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
        # A historical record curated for the distribution keeps its original digest here; the
        # curation record maps exactly that original to exactly this copy.
        try:
            entry = evidence_layout.load_curation_record(root).get(artifact["path"])
        except (ValueError, OSError):
            entry = None
        if (entry and evidence_layout.pin_matches(root, artifact["path"], artifact.get("sha256"), got)
                and artifact["bytes"] == entry["original_bytes"]
                and os.path.getsize(full) == entry["curated_bytes"]):
            return True, "ok (curated copy)"
        want = str(artifact.get("sha256"))[:12]
        return False, f"sha256 mismatch (manifest {want}, on-disk {got[:12]})"
    if os.path.getsize(full) != artifact["bytes"]:
        return False, "byte count mismatch"
    return True, "ok"


def check_claim(claim, root, pinned=frozenset(), public=False):
    """Re-verifies every artifact of one manifest claim against `root`. Returns
    (verdict, detail) with verdict in ('PASS', 'WARN', 'FAIL'). `pinned` names undistributed
    artifacts that a tree declaring them must hold byte-for-byte."""
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
    pinned_fails = [f"undistributed artifact {a['path']!r} {why}"
                    for a, ok, why in per_artifact if a["path"] in pinned and not ok]
    if pinned_fails:
        return "FAIL", "; ".join(pinned_fails)

    ok_count = sum(1 for _a, ok, _why in per_artifact if ok)
    status = claim.get("status")
    stale = [(a, why) for a, ok, why in per_artifact if not ok and not a.get("shipped")]
    if public:
        # A distributed tree carries no historical run records by design: count them only.
        absent = sum(1 for _a, why in stale if why == "missing")
        other = [f"{a['path']!r} ({why})" for a, why in stale if why != "missing"]
        notes = ([f"{absent} historical artifact(s) not distributed"] if absent else []) + (
            [f"{len(other)} historical artifact(s) present but not matching (not fatal): {other}"]
            if other else [])
        stale_note = "".join("; " + note for note in notes)
    else:
        listed = [f"{a['path']!r} ({why})" for a, why in stale]
        stale_note = (f"; {len(stale)} undistributed artifact(s) not present+matching (not fatal): {listed}"
                      if stale else "")

    if status in EVIDENCE_REQUIRED_STATUSES:
        if ok_count == 0:
            return "FAIL", f"'{status}' claim has no present+sha-matching artifact under {root}"
        return "PASS", f"{ok_count}/{len(artifacts)} artifact(s) present+matching{stale_note}"

    if status == "partial":
        if not any(a.get("shipped") for a in artifacts):
            return "WARN", "partial claim has only undistributed artifacts (no public surrogate)"
        return "PASS", f"partial claim carries a shipped artifact{stale_note}"

    return "PASS", f"status={status!r} not held to the served bar{stale_note}"


def check_manifest(manifest, root, pinned=frozenset(), public=False):
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
            rows.append((cid, *check_claim(c, root, pinned, public)))
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
    specs = module.enumerate_specs(matrix, cases, root)
    return [(s, [evidence_layout.public_path(path, root) for path, _role in s["candidates"] if module.is_shipped(path, root)],
             [path for path, _role in s["candidates"] if evidence_layout.declared_internal(path, root)])
            for s in specs]


def check_completeness(manifest, root, public=False):
    """A locally coherent manifest cannot silently drop or downgrade source claims. Outside public
    mode it also keeps every undistributed record that a claim's sources name."""
    try:
        specs = _source_specs(root)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return [("sources", "FAIL", f"cannot enumerate authoritative claims: {exc}")]
    expected, internal = {}, {}
    for s, required, *records in specs:
        expected[s["claim_id"]] = (s, required)
        internal[s["claim_id"]] = records[0] if records else []
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
        listed = {a["path"] for a in claim["artifacts"] if not a["shipped"]}
        if not public and not set(internal[cid]) <= listed:
            rows.append((cid, "FAIL", f"undistributed record omitted: {sorted(set(internal[cid]) - listed)}"))
    return rows


def pinned_internal(manifest, root):
    """Undistributed artifacts recorded in a manifest (hard-pinned where the registry declares them).
    A tree without an evidence registry declares none."""
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("claims"), list)
            or not os.path.isfile(os.path.join(root, evidence_layout.REGISTRY))):
        return frozenset()
    return frozenset(a["path"] for c in manifest["claims"] if isinstance(c, dict)
                     for a in c.get("artifacts") or [] if isinstance(a, dict) and isinstance(a.get("path"), str)
                     and evidence_layout.declared_internal(a["path"], root))


def check_public_scope(manifest, root):
    """Public-tree obligations: the manifest lists no undistributed artifact and cites no
    undistributed material, under the registry patterns of this tree and of `root`."""
    patterns = set()
    for base in {ROOT, root}:
        try:
            patterns.update(evidence_layout.internal_patterns(base))
        except (ValueError, OSError) as exc:
            return [("public-scope", "FAIL", f"cannot read the evidence registry of {base}: {exc}")]
    rows = []
    for claim in manifest["claims"]:
        cid = claim.get("claim_id", "?")
        listed = [a["path"] for a in claim["artifacts"] if evidence_layout.internal_mentions(a["path"], patterns)]
        if listed:
            rows.append((cid, "FAIL", f"undistributed artifact(s) listed in a public manifest: {listed}"))
        cited = evidence_layout.internal_mentions(str(claim.get("source", "")), patterns)
        if cited:
            rows.append((cid, "FAIL", f"source statement cites undistributed material {cited}"))
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

    public = getattr(args, "public", False) or evidence_layout.is_public_tree(root)
    try:
        pinned = frozenset() if public else pinned_internal(manifest, root)
    except (ValueError, OSError) as exc:
        print(f"check_evidence --check: FAIL -- cannot read the evidence registry: {exc}", file=sys.stderr)
        return 1
    rows = check_manifest(manifest, root, pinned, public)
    if not any(v == "FAIL" for _, v, _ in rows):
        rows += check_completeness(manifest, root, public)
        if public:
            rows += check_public_scope(manifest, root)
    if not rows:
        print("check_evidence --check: FAIL -- manifest carries zero claims", file=sys.stderr)
        return 1

    any_fail = False
    for claim_id, verdict, detail in rows:
        print(f"[{verdict}] {claim_id}: {detail}")
        any_fail = any_fail or (verdict == "FAIL")
    try:
        layout = evidence_layout.source_module(root)
        curation = (layout or evidence_layout).curation_errors(root)
    except (ValueError, OSError) as exc:
        curation = [str(exc)]
    for error in curation:
        print(f"[FAIL] curation: {error}")
        any_fail = True

    n = len(rows)
    n_fail = sum(1 for _c, v, _d in rows if v == "FAIL")
    n_warn = sum(1 for _c, v, _d in rows if v == "WARN")
    n_pass = n - n_fail - n_warn
    print(f"\ncheck_evidence: {n_pass} PASS / {n_warn} WARN / {n_fail} FAIL of {n} claim(s)"
          + (f"; curation: {len(curation)} FAIL" if curation else "")
          + f", root={root}" + (" (public tree)" if public else ""))
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
    ap.add_argument("--public", action="store_true",
                     help="public-tree obligations (automatic when --root is a distributed tree)")
    ap.add_argument("--root", default=None,
                     help="tree to verify artifacts against (default: repo root; pass another"
                          " checkout to check it)")
    args = ap.parse_args()

    if args.write:
        sys.exit(cmd_write())
    sys.exit(cmd_check(args))


if __name__ == "__main__":
    main()
