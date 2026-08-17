#!/usr/bin/env python3
"""provenance.py -- the SINGLE source of the run_state / lifecycle-required-artifact provenance
fingerprint.  stdlib-only.

Emitters of a --verify-provenance-checked (lifecycle-required) artifact stamp two fields so a gate
can PROVE the artifact was produced by its tool, not hand-written/backfilled (design principle 5 --
closes the backfill loophole):
  generated_by      -- the tool id that wrote the artifact (e.g. "workflow_state.py")
  input_fingerprint -- sha256 over the artifact's DECLARED inputs (e.g. task_contract.json)

Presence alone never satisfies a gate: validate_run_state.py --verify-provenance recomputes
input_fingerprint from the same declared inputs and rejects a mismatch or a missing/handwritten
generated_by.

DOMAIN SEPARATION (D-7): this is the ONE formula for the lifecycle-required domain -- any emitter of
a --verify-provenance-checked artifact imports provenance and calls provenance_pair(...), never
reimplementing the fingerprint. A domain-specific artifact (e.g. sr_plausibility.json, Phase 4a)
deliberately computes its OWN input_fingerprint over a DIFFERENT canonicalization for its own domain
and is NOT verified against this formula -- the two domains are kept disjoint on purpose.

Usage:
  provenance.py --selftest
Exit codes: 0 PASS * 1 selftest FAIL * 2 usage
"""
import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PROV_KEYS = ("generated_by", "input_fingerprint")
_MISSING = "<missing-input>"


def _resolve_timestamp(env_var="WORKFLOW_STATE_UTC", cli_timestamp=None):
    """A diff-stable UTC string: cli override, else $<env_var>, else "" -- NEVER datetime.now()
    (wall-clock timestamps break emitter tests; mirrors shape_fit._resolve_timestamp)."""
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get(env_var, "")


def sha256_bytes(b):
    """sha256 hexdigest of a bytes object."""
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    """sha256 hexdigest of a file's bytes, or a stable sentinel hash if the file is absent."""
    try:
        with open(path, "rb") as fh:
            return sha256_bytes(fh.read())
    except OSError:
        return sha256_bytes(_MISSING.encode("utf-8"))


def fingerprint(input_paths):
    """Deterministic sha256 over an ORDERED list of input files: hash of the concatenation of each
    file's own sha256 (order-preserving so callers control input order). An empty list fingerprints
    the empty string -- a stable, reproducible value."""
    h = hashlib.sha256()
    for p in input_paths:
        h.update(sha256_file(p).encode("utf-8"))
    return h.hexdigest()


def provenance_pair(tool_id, input_paths):
    """The two-field provenance stamp every lifecycle-required (--verify-provenance-checked) emitter
    merges into its artifact dict -- provenance.py is the single source of THIS fingerprint (D-7); a
    domain-specific emitter (e.g. sr_plausibility.py) owns a separate one and does not call this.
    tool_id: the writer's basename (e.g. "workflow_state.py"). input_paths: ORDERED paths of the
    artifact's declared inputs."""
    return {"generated_by": tool_id, "input_fingerprint": fingerprint(input_paths)}


def verify_pair(record, tool_id, input_paths):
    """(ok, reason). ok iff `record` carries a non-empty generated_by == tool_id AND its
    input_fingerprint recomputes to fingerprint(input_paths). A hand-written artifact (no/blank
    generated_by) or a stale/edited one (fingerprint drift) returns (False, reason)."""
    gb = record.get("generated_by")
    if not gb:
        return False, "generated_by absent/blank (hand-written?)"
    if gb != tool_id:
        return False, f"generated_by={gb!r} != expected {tool_id!r}"
    want = fingerprint(input_paths)
    got = record.get("input_fingerprint")
    if got != want:
        return False, f"input_fingerprint mismatch (recomputed {want[:12]}.., stored {str(got)[:12]}..)"
    return True, "provenance ok"


def selftest():
    import json
    import tempfile
    fails = []

    def check(label, ok, detail=""):
        print(f"[selftest] {label}: {detail}  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append(label)

    with tempfile.TemporaryDirectory(prefix="provenance_selftest_") as td:
        p = os.path.join(td, "task_contract.json")
        with open(p, "w") as fh:
            json.dump({"task_mode": "scan"}, fh)
        fp1, fp2 = fingerprint([p]), fingerprint([p])
        check("1 fingerprint deterministic", fp1 == fp2 and len(fp1) == 64, fp1[:12])
        pair = provenance_pair("workflow_state.py", [p])
        check("2 pair carries both keys", set(pair) == set(PROV_KEYS)
              and pair["generated_by"] == "workflow_state.py", str(sorted(pair)))
        ok, _ = verify_pair(dict(pair), "workflow_state.py", [p])
        check("3 genuine record verifies", ok)
        ok, _ = verify_pair({"input_fingerprint": fp1}, "workflow_state.py", [p])
        check("4 hand-written record rejected", not ok)
        with open(p, "w") as fh:
            json.dump({"task_mode": "reproduce"}, fh)
        ok, _ = verify_pair(dict(pair), "workflow_state.py", [p])
        check("5 fingerprint-drift record rejected", not ok)
        check("6 empty-input fingerprint stable", fingerprint([]) == fingerprint([]) and len(fingerprint([])) == 64)

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("provenance selftest: PASS (6 case(s))")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
