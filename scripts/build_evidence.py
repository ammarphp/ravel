#!/usr/bin/env python3
"""Build evidence/manifest.json + docs/validation/evidence.md -- PRODUCT-CONTRACT section 7 (CR-030): every
SHIPPED headline/served claim must map to a shipped, sha256-checksummed artifact on disk, or the
export aborts (scripts/check_evidence.py's job, Task 6.2). This script is the BUILDER half: it
enumerates claims from three machine sources -- never a hand-maintained parallel list -- sha256-
checksums every artifact that exists, and fails loud if a served claim ends up with zero evidence.

Claim sources:
  1. `benchmarks/capabilities.json` `prompts` entries carrying an `evidence_artifacts` list
     (retained for P1/P4 component evidence even when their full-task status is partial -- a future
     served prompt must add its own list the same way, or this build FAILS LOUD naming it).
  2. `benchmarks/cases.json` `cases[].provenance.require_files` -- reused verbatim
     (resolved under the case's own `run_dir`) as that reproduction case's artifact list.
  3. HEADLINE_CLAIMS below -- a small curated block for engine-layer claims that live in SHIPPED
     docs (`docs/workflow/reference/native-pipeline.md`, `docs/development/status.md`, ...) but are not
     capability-matrix prompts (the 141/141 native-SR bit-for-bit claim, the native mu95 0.51%
     agreement, the Fig-3 52/52-point scan residual).

`shipped` classification mirrors `scripts/maintenance/export-distribution.sh`'s ACTUAL copy
list (the ground truth for what leaves the machine at export time) -- NOT the prose table in
`docs/development/distribution.md`, which has visibly drifted from that script (e.g. the script ships
`CAPABILITY-ROADMAP.md`/`OPERABILITY-CHARTER.md`/`DECISION-SHAPE-FIT.md`, the prose table says two
of those three are dev-only). See `is_shipped()`. An artifact whose run record is dev-only-by-
policy (`trial-runs/2026-*/`, `trial-runs/sleptonscan_*/`, per DISTRIBUTION.md) is marked
`shipped:false, dev_only:true`; its claim then carries an additional `shipped:true` SURROGATE
artifact (the matrix / the benchmark registry / the doc that states the claim) so the claim stays
publicly auditable even though the raw run record itself does not ship.

Usage:
    python3 scripts/build_evidence.py [--write] [--timestamp T] [--commit SHA]

--write is the default action (this generator has no separate read-only report mode -- writing
IS the point; `scripts/check_evidence.py --check` is the read-only verifier). `--timestamp`/
`--commit` default to "" / a best-effort `git rev-parse --short HEAD` respectively -- this script
never calls `datetime.now()` on its own (determinism; pass `--timestamp` explicitly when a stamp
is wanted).
"""
import argparse
from fnmatch import fnmatchcase
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def p(*a):
    return os.path.join(ROOT, *a)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class BuildError(RuntimeError):
    """A served claim ended up with no evidence, or a declared surrogate is itself missing --
    the build refuses to emit a manifest that silently drops a claim's evidence."""


# --------------------------------------------------------------------------- #
# shipped / dev-only classification
# --------------------------------------------------------------------------- #

# One registry drives both the exporter and the evidence integrity obligations.
sys.path.insert(0, os.path.join(ROOT, "src"))
from ravel import evidence_layout


def is_shipped(relpath, root=ROOT):
    return evidence_layout.is_shipped(relpath, root)


# --------------------------------------------------------------------------- #
# per-artifact role inference (cosmetic -- docs/validation/evidence.md readability only, never gates a verdict)
# --------------------------------------------------------------------------- #

_ROLE_BASENAMES = {
    "summary_audit.json": "gate-result",
    "survey.json": "survey-data",
    "basis_manifest.json": "basis-manifest",
    "verification-ladder.md": "verification-ladder",
    "shape_fit.py": "engine-code",
    "decision-shape-fit.md": "decision-record",
    "result.md": "result-record",
    "provenance.json": "provenance",
    "exclusion.json": "exclusion-result",
    "cases.json": "benchmark-registry",
    "capability-matrix.json": "matrix-entry",
    "ewkcompressed2018.txt": "native-sr-yields",
    "scan.json": "scan-aggregate",
}


def _infer_role(relpath):
    base = os.path.basename(relpath).lower()
    if base in _ROLE_BASENAMES:
        return _ROLE_BASENAMES[base]
    if base.startswith("qa_") and base.endswith((".png", ".pdf")):
        return "qa-plot"
    if base.endswith((".png", ".pdf")):
        return "headline-figure"
    if "sr_yields" in base:
        return "sr-yields"
    if "cutflow_cert" in base:
        return "cutflow-cert"
    if "axe_compare" in base:
        return "axe-comparison"
    if base.endswith(".yoda"):
        return "yoda-output"
    if base.endswith(".cc"):
        return "patched-routine"
    return "artifact"


# --------------------------------------------------------------------------- #
# source 3: curated headline claims (engine-layer claims living in shipped docs, not prompts)
# --------------------------------------------------------------------------- #

HEADLINE_CLAIMS = [
    {
        "claim_id": "HEADLINE_rrr_m150_m140_waypoint",
        "headline": "Completed 20k four-state m150/m140 waypoint: conditional inclusive "
                    "sigma95 48.83 fb observed and 54.69 fb median expected; "
                    "not acceptance, coverage or full mass-plane certification",
        "doc_source": "README.md",
        "artifacts": [
            "evidence/audits/2026-09-06-rrr-waypoint/waypoint.json",
            "evidence/audits/2026-09-06-rrr-waypoint/manifest.json",
            "evidence/audits/2026-09-06-rrr-waypoint/fits/anchor20k.json",
            "evidence/audits/2026-09-06-rrr-waypoint/inclusive-normalization.json",
            "evidence/audits/2026-09-06-rrr-waypoint/published-limits-52.json",
        ],
        "surrogate": "evidence/audits/2026-09-06-rrr-waypoint/README.md",
    },
    {
        "claim_id": "HEADLINE_native_141_bitforbit",
        "headline": "Native SimpleAnalysis (EwkCompressed2018) reproduces the container's "
                     "per-SR yields bit-for-bit: 141/141 SRs",
        "doc_source": "docs/workflow/reference/native-pipeline.md",
        "artifacts": ["trial-runs/2026-06-16_slepton_200-150_native/output/EwkCompressed2018.txt"],
        "surrogate": "docs/workflow/reference/native-pipeline.md",
    },
    {
        "claim_id": "HEADLINE_native_mu95_0p51pct",
        "headline": "Native slepton 200/150 point's mu95 agrees with the container to 0.51% "
                     "(6.333 vs 6.366)",
        "doc_source": "docs/workflow/reference/native-pipeline.md",
        "artifacts": ["trial-runs/2026-06-16_slepton_200-150_native/output/exclusion.json"],
        "surrogate": "docs/workflow/reference/native-pipeline.md",
    },
    {
        "claim_id": "HEADLINE_fig3_scan_same_basis_residual",
        "headline": "Fig-3 52/52-point native slepton-bino scan: ~24-25% median same-basis "
                     "residual vs the published ATLAS contour",
        "doc_source": "docs/development/status.md",
        "artifacts": ["trial-runs/sleptonscan_fig3_SCAN/scan.json"],
        "surrogate": "docs/development/status.md",
    },
]

# short human headline for the two artifact-bearing matrix prompts (cosmetic; the claim's real
# evidence is its artifact list + gate, not this string)
PROMPT_HEADLINES = {
    "P1_hvt_zprime_ww_summary": "HVT Z' -> WW low-mass summary plot (survey/summary track)",
    "P4_dijet_photon_widths": "Dijet/diphoton resonance widths via the scoped shape-fit engine",
}

SERVED_STATUSES = ("served", "served-with-refusal")


def _matrix_gate_label(gate):
    if not gate:
        return "none"
    kind = gate.get("kind")
    if kind == "artifact":
        art = gate.get("artifact", "")
        return os.path.splitext(os.path.basename(art))[0] or "artifact"
    if kind == "selftest":
        ref = gate.get("ref", "")
        stem = os.path.splitext(os.path.basename(ref))[0]
        return f"{stem}_selftest" if stem else "selftest"
    return kind or "none"


# --------------------------------------------------------------------------- #
# claim-spec enumeration (source 1/2/3 -> a uniform spec dict, no disk I/O beyond the 2 JSON reads)
# --------------------------------------------------------------------------- #

def prompt_specs(matrix):
    specs = []
    for key, v in sorted(matrix.get("prompts", {}).items()):
        artifacts = v.get("evidence_artifacts")
        if not artifacts:
            if v.get("status") not in SERVED_STATUSES:
                continue
            raise BuildError(
                f"{key}: status={v.get('status')!r} but capability-matrix.json carries no "
                f"'evidence_artifacts' list for it -- a served prompt needs a named artifact "
                f"list (add one to benchmarks/capabilities.json, see this script's module "
                f"docstring source 1)")
        specs.append({
            "claim_id": key,
            "source": f"benchmarks/capabilities.json:prompts.{key}",
            "headline": PROMPT_HEADLINES.get(key, key),
            "status": v.get("status"),
            "gate": _matrix_gate_label(v.get("gate")),
            "candidates": [(a, _infer_role(a)) for a in artifacts],
            "surrogate": ("benchmarks/capabilities.json", "matrix-entry"),
        })
    return specs


def benchmark_specs(cases_doc):
    specs = []
    for c in cases_doc.get("cases", []):
        cid = c["case_id"]
        run_dir = c["run_dir"]
        files = c.get("provenance", {}).get("require_files", [])
        candidates = [(f"{run_dir}/{f}", _infer_role(f)) for f in files]
        model = c.get("model", cid)
        analysis = c.get("analysis_id", "?")
        specs.append({
            "claim_id": f"BENCH_{cid}",
            "source": f"benchmarks/cases.json:cases.{cid}",
            "headline": f"Historical benchmark record: {model} vs published {analysis}; "
                        "see scoped statistical and acceptance verdicts in docs/validation",
            "status": "historical",
            "gate": c.get("cert", {}).get("engine", "benchmark_cert"),
            "candidates": candidates,
            "surrogate": ("benchmarks/cases.json", "benchmark-registry"),
        })
    return specs


def headline_specs():
    specs = []
    for hc in HEADLINE_CLAIMS:
        specs.append({
            "claim_id": hc["claim_id"],
            "source": f"scripts/build_evidence.py:HEADLINE_CLAIMS.{hc['claim_id']} "
                      f"(stated in {hc['doc_source']})",
            "headline": hc["headline"],
            "status": "served",
            "gate": "curated",
            "candidates": [(a, _infer_role(a)) for a in hc["artifacts"]],
            "surrogate": (hc["surrogate"], "doc-citation"),
        })
    return specs


def enumerate_specs(matrix, cases_doc):
    return prompt_specs(matrix) + benchmark_specs(cases_doc) + headline_specs()


# --------------------------------------------------------------------------- #
# materialization: spec -> claim record (this is where disk I/O + sha256 happens)
# --------------------------------------------------------------------------- #

def _artifact_record(relpath, role, root):
    full = evidence_layout.resolve(root, relpath)
    if not os.path.isfile(full):
        return None
    shipped = is_shipped(relpath, root)
    public = evidence_layout.public_path(relpath, root)
    return {
        "path": public,
        **({"source_path": evidence_layout.source_path(public, root)} if public != relpath else {}),
        "sha256": sha256_of(full),
        "bytes": os.path.getsize(full),
        "shipped": shipped,
        "dev_only": not shipped,
        "role": role,
    }


def materialize_claim(spec, root=ROOT, warn=None):
    """spec: {claim_id, source, headline, status, gate, candidates:[(path,role)],
    surrogate:(path,role) or None}. Resolves candidates against `root`, sha256-checksums every
    one that exists, and adds the surrogate ONLY if none of the claim's own artifacts already
    ships. Raises BuildError if the claim ends up with literally zero evidence (all candidates
    missing AND no usable surrogate) -- never silently emits a claim with an empty artifact list."""
    warn = warn if warn is not None else (lambda msg: print(msg, file=sys.stderr))
    claim_id = spec["claim_id"]
    artifacts, missing = [], []
    for relpath, role in spec["candidates"]:
        rec = _artifact_record(relpath, role, root)
        if rec is None:
            if is_shipped(relpath, root):
                raise BuildError(f"{claim_id}: mandatory shipped evidence missing: {relpath}; "
                                 "a registry or documentation surrogate cannot replace it")
            missing.append(relpath)
        else:
            artifacts.append(rec)
    if missing:
        warn(f"  WARN {claim_id}: candidate artifact(s) not found under {root}, skipped: {missing}")
    if not artifacts and not spec.get("surrogate"):
        raise BuildError(f"{claim_id}: ZERO of its {len(spec['candidates'])} candidate "
                          f"artifact(s) exist on disk and no surrogate is declared -- refusing "
                          f"to emit a claim with no evidence")

    surrogate = spec.get("surrogate")
    if surrogate and not any(a["shipped"] for a in artifacts):
        srel, srole = surrogate
        srec = _artifact_record(srel, srole, root)
        if srec is None:
            if not artifacts:
                raise BuildError(f"{claim_id}: all candidate artifacts are missing/dev-only and "
                                  f"its declared shipped surrogate {srel!r} does not exist under "
                                  f"{root} either -- refusing to emit a claim with no evidence")
            warn(f"  WARN {claim_id}: surrogate {srel!r} not found under {root} (claim still has "
                 f"{len(artifacts)} dev-only artifact(s), but no shipped one)")
        else:
            artifacts.append(srec)

    if not artifacts:
        raise BuildError(f"{claim_id}: ZERO existing artifacts -- refusing to emit a claim with "
                          f"no evidence")

    return {
        "claim_id": claim_id,
        "source": spec["source"],
        "headline": spec["headline"],
        "status": spec["status"],
        "gate": spec["gate"],
        "evidence_scope": "artifact integrity; this does not certify scientific correctness",
        "artifacts": artifacts,
    }


# --------------------------------------------------------------------------- #
# manifest assembly + rendering
# --------------------------------------------------------------------------- #

def _git_commit(root=ROOT):
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def build_manifest(root=ROOT, timestamp="", commit=""):
    with open(os.path.join(root, "benchmarks", "capabilities.json"), encoding="utf-8") as f:
        matrix = json.load(f)
    with open(os.path.join(root, "benchmarks", "cases.json"), encoding="utf-8") as f:
        cases_doc = json.load(f)
    specs = enumerate_specs(matrix, cases_doc)
    claims = [materialize_claim(s, root=root) for s in specs]
    return {
        "schema_version": 1,
        "generated": timestamp,
        "source_commit": commit if commit else _git_commit(root),
        "claims": claims,
    }


def render_evidence_md(manifest):
    lines = [
        "# Evidence and artifact integrity", "",
        "_Generated by `scripts/build_evidence.py` from `benchmarks/capabilities.json` prompts, "
        "`benchmarks/cases.json`, and a curated `HEADLINE_CLAIMS` block. "
        "`scripts/check_evidence.py --check` verifies this table against real files on disk "
        "(sha256, per artifact); it must pass before any export ships (PRODUCT-CONTRACT "
        "section 7, CR-030)._", "",
        "A checksum establishes artifact integrity, not scientific correctness. A registry or "
        "documentation surrogate establishes that a historical claim was recorded; it does "
        "not replace missing raw validation evidence. Benchmark certification verdicts and "
        "unscorable cases are listed in [validation pages](README.md).", "",
    ]
    if manifest.get("generated"):
        lines.append(f"Generated: {manifest['generated']}")
    if manifest.get("source_commit"):
        lines.append(f"Source commit: `{manifest['source_commit']}`")
    lines += ["", "| Claim | Headline | Status | Gate | Shipped artifacts | Dev-only artifacts |",
              "|---|---|---|---|---|---|"]
    for c in manifest["claims"]:
        headline = c["headline"].replace("|", "\\|")
        shipped = [f"`{a['path']}` (`{a['sha256'][:12]}`)" for a in c["artifacts"] if a["shipped"]]
        dev_only = [f"`{a['path']}` (`{a['sha256'][:12]}`)" for a in c["artifacts"]
                    if not a["shipped"]]
        lines.append(f"| `{c['claim_id']}` | {headline} | {c['status']} | {c['gate']} | "
                     f"{'<br>'.join(shipped) or '—'} | {'<br>'.join(dev_only) or '—'} |")
    n_served = sum(1 for c in manifest["claims"] if c["status"] in SERVED_STATUSES)
    n_artifacts = sum(len(c["artifacts"]) for c in manifest["claims"])
    lines += ["", f"**{len(manifest['claims'])} claim(s)** ({n_served} served/served-with-"
              f"refusal), **{n_artifacts} artifact(s)** sha256-checksummed. Every claim above "
              f"carries >=1 present, sha256-verified artifact as of the last "
              f"`build_evidence.py --write` (verify freshness with "
              f"`scripts/check_evidence.py --check`)."]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_write(args):
    try:
        manifest = build_manifest(timestamp=args.timestamp, commit=args.commit)
    except (BuildError, ValueError, OSError) as e:
        print(f"build_evidence --write: FAIL -- {e}", file=sys.stderr)
        return 1
    manifest_path = p("evidence/manifest.json")
    md_path = p("docs/validation/evidence.md")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)
        f.write("\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_evidence_md(manifest))
    n_served = sum(1 for c in manifest["claims"] if c["status"] in SERVED_STATUSES)
    n_artifacts = sum(len(c["artifacts"]) for c in manifest["claims"])
    print(f"build_evidence --write: OK -- {len(manifest['claims'])} claim(s) "
          f"({n_served} served), {n_artifacts} artifact(s) sha256'd -> "
          f"{rel(manifest_path)}, {rel(md_path)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                     help="(default action regardless of this flag) build + write "
                          "evidence/manifest.json + docs/validation/evidence.md")
    ap.add_argument("--timestamp", default="",
                     help="ISO timestamp for the 'generated' field (default: left empty -- this "
                          "script never calls datetime.now() itself)")
    ap.add_argument("--commit", default="",
                     help="override source_commit (default: best-effort "
                          "`git rev-parse --short HEAD`, '' on failure)")
    args = ap.parse_args()
    sys.exit(cmd_write(args))


if __name__ == "__main__":
    main()
