"""scripts/build_evidence.py + scripts/check_evidence.py -- docs/reference/scope.md section 7
(CR-030): every SHIPPED headline/served claim must map to a shipped, sha256-checksummed artifact,
or the evidence check fails. This pins:
  - build_evidence.is_shipped(): the registry-driven shipped/undistributed classifier
  - build_evidence.materialize_claim(): sha256 capture, the undistributed+surrogate substitution rule,
    and the "refuse to emit a claim with zero evidence" BuildError
  - build_evidence.enumerate_specs(): the live repo's benchmarks/capabilities.json / benchmarks/cases.json
    resolve to exactly the expected claim_id set (no silent drops, no hand-maintained duplicate)
  - check_evidence.check_claim(): the FAIL/WARN/PASS verdict rules --
      * an intact claim passes
      * a tampered or absent SHIPPED artifact fails the claim outright
      * a served claim with zero present+matching artifacts fails
      * a dev_only artifact absent (the distributed-tree scenario) is fine as long as a shipped
        surrogate is present+matching
      * a tampered dev_only artifact next to an intact shipped one does NOT fail the claim
        (only the >=1-present-match + shipped-integrity rules are load-bearing, by design)
      * a partial claim with only undistributed artifacts WARNs, not FAILs
  - the live integration: `python3 scripts/check_evidence.py --check` exits 0 against the
    committed manifest (evidence/manifest.json at the repo root).

Import both modules by file path, not by package import: the repo root carries a `py.py` file
that shadows the real `py` package pytest depends on internally if the repo root ends up on
sys.path. Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BUILD_EVIDENCE_PY = REPO / "scripts" / "build_evidence.py"
CHECK_EVIDENCE_PY = REPO / "scripts" / "check_evidence.py"


@pytest.fixture(autouse=True)
def layout_registry(tmp_path):
    """The real registry's selection in its distributed form: a fixture tree carries no
    undistributed declarations or settings files."""
    target = tmp_path / "evidence/collections.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    registry = json.loads((REPO / "evidence/collections.json").read_text())
    registry["distribution"] = {k: registry["distribution"][k] for k in ("files", "trees", "extra_files", "exclude")}
    target.write_text(json.dumps(registry))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_build_evidence():
    return _load(BUILD_EVIDENCE_PY, "build_evidence_under_test")


def _load_check_evidence():
    return _load(CHECK_EVIDENCE_PY, "check_evidence_under_test")


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# build_evidence.is_shipped
# --------------------------------------------------------------------------- #

def test_is_shipped_curated_headlines_are_mandatory():
    be = _load_build_evidence()
    assert be.is_shipped("src/ravel/physics/shape_fit.py") is True
    assert be.is_shipped("trial-runs/2026-06-16_slepton_200-150_native/output/exclusion.json") \
        is True
    assert be.is_shipped("trial-runs/sleptonscan_fig3_SCAN/scan.json") is True
    assert be.is_shipped("trial-runs/unpublished-private/RESULT.md") is False


def test_is_shipped_unregistered_directory_row_by_row():
    be = _load_build_evidence()
    assert be.is_shipped("benchmarks/cases.json") is True
    assert be.is_shipped("notes/trial-notes.md") is False
    assert be.is_shipped("notes/planning/foo.md") is False


def test_is_shipped_top_level():
    be = _load_build_evidence()
    assert be.is_shipped("docs/workflow/reference/native-pipeline.md") is True
    assert be.is_shipped("docs/reference/scope.md") is True
    assert be.is_shipped("notes/session-1.md") is False


# --------------------------------------------------------------------------- #
# build_evidence.materialize_claim
# --------------------------------------------------------------------------- #

def test_materialize_claim_hashes_existing_candidates(tmp_path):
    be = _load_build_evidence()
    (tmp_path / "src" / "ravel" / "physics").mkdir(parents=True)
    art = tmp_path / "src" / "ravel" / "physics" / "tool.py"
    art.write_text("print('hi')\n")
    spec = {"claim_id": "C1", "source": "test", "headline": "h", "status": "served",
            "gate": "g", "candidates": [("src/ravel/physics/tool.py", "engine-code")],
            "surrogate": None}
    claim = be.materialize_claim(spec, root=tmp_path)
    assert len(claim["artifacts"]) == 1
    a = claim["artifacts"][0]
    assert a["sha256"] == _sha("print('hi')\n")
    assert a["shipped"] is True
    assert a["dev_only"] is False


def test_materialize_claim_zero_candidates_and_no_surrogate_raises(tmp_path):
    be = _load_build_evidence()
    spec = {"claim_id": "C_MISSING", "source": "test", "headline": "h", "status": "served",
            "gate": "g", "candidates": [("does/not/exist.json", "artifact")], "surrogate": None}
    with pytest.raises(be.BuildError, match="C_MISSING"):
        be.materialize_claim(spec, root=tmp_path, warn=lambda _m: None)


def test_materialize_claim_falls_back_to_surrogate_when_all_candidates_missing(tmp_path):
    be = _load_build_evidence()
    (tmp_path / "benchmarks").mkdir()
    surrogate_file = tmp_path / "benchmarks" / "capabilities.json"
    surrogate_file.write_text("{}")
    spec = {"claim_id": "C_DEV_ONLY", "source": "test", "headline": "h", "status": "served",
            "gate": "g", "candidates": [("trial-runs/2026-01-01_run/RESULT.md", "result-record")],
            "surrogate": ("benchmarks/capabilities.json", "matrix-entry")}
    claim = be.materialize_claim(spec, root=tmp_path, warn=lambda _m: None)
    assert len(claim["artifacts"]) == 1
    assert claim["artifacts"][0]["path"] == "benchmarks/capabilities.json"
    assert claim["artifacts"][0]["shipped"] is True


def test_materialize_claim_raises_when_surrogate_also_missing(tmp_path):
    be = _load_build_evidence()
    spec = {"claim_id": "C_NOTHING", "source": "test", "headline": "h", "status": "served",
            "gate": "g", "candidates": [("trial-runs/2026-01-01_run/RESULT.md", "result-record")],
            "surrogate": ("benchmarks/capabilities.json", "matrix-entry")}
    with pytest.raises(be.BuildError, match="C_NOTHING"):
        be.materialize_claim(spec, root=tmp_path, warn=lambda _m: None)


def test_materialize_claim_skips_surrogate_when_a_real_artifact_already_ships(tmp_path):
    be = _load_build_evidence()
    (tmp_path / "src" / "ravel" / "physics").mkdir(parents=True)
    (tmp_path / "src" / "ravel" / "physics" / "tool.py").write_text("x")
    spec = {"claim_id": "C2", "source": "test", "headline": "h", "status": "served", "gate": "g",
            "candidates": [("src/ravel/physics/tool.py", "engine-code")],
            "surrogate": ("benchmarks/capabilities.json", "matrix-entry")}  # deliberately absent
    claim = be.materialize_claim(spec, root=tmp_path, warn=lambda _m: None)
    assert len(claim["artifacts"]) == 1   # surrogate never consulted -- the real artifact ships


# --------------------------------------------------------------------------- #
# build_evidence: served prompt with no evidence_artifacts -> loud failure
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("status", ["served", "served-with-refusal", "refused"])
def test_prompt_specs_requires_evidence_artifacts_on_served_or_refusal_claims(status):
    be = _load_build_evidence()
    matrix = {"prompts": {"PX_served_but_bare": {"status": status, "gate": {}}}}
    with pytest.raises(be.BuildError, match="evidence_artifacts"):
        be.prompt_specs(matrix)


def test_evidence_headline_does_not_count_refusals_as_served():
    be = _load_build_evidence()
    claims = [{"claim_id": str(i), "status": status, "headline": "test", "gate": "artifact", "artifacts": []}
              for i, status in enumerate(("served", "served-with-refusal", "refused"))]
    page = be.render_evidence_md({"claims": claims})
    assert "1 labeled served; 2 refusals remain unmet requests" in page


def test_prompt_specs_skips_non_served_prompts():
    be = _load_build_evidence()
    matrix = {"prompts": {"PY_partial": {"status": "partial", "gate": {}}}}
    assert be.prompt_specs(matrix) == []


def test_partial_prompt_retains_declared_component_evidence():
    be = _load_build_evidence()
    specs = be.prompt_specs({"prompts": {"PY_partial": {"status": "partial", "gate": {},
                            "evidence_artifacts": ["outputs/component.json"]}}})
    assert len(specs) == 1 and specs[0]["status"] == "partial"
    assert specs[0]["candidates"][0][0] == "outputs/component.json"


# --------------------------------------------------------------------------- #
# build_evidence: live-repo enumeration (pure function of the real matrix/cases -- no disk writes)
# --------------------------------------------------------------------------- #

def test_enumerate_specs_matches_live_repo_sources():
    be = _load_build_evidence()
    matrix = json.loads((REPO / "benchmarks" / "capabilities.json").read_text())
    cases_doc = json.loads((REPO / "benchmarks" / "cases.json").read_text())
    specs = be.enumerate_specs(matrix, cases_doc)
    claim_ids = {s["claim_id"] for s in specs}
    assert "P1_hvt_zprime_ww_summary" in claim_ids
    assert "P4_dijet_photon_widths" in claim_ids
    assert "P2_toponium_heavy_higgs_summary" not in claim_ids   # no declared artifact list
    for case in cases_doc["cases"]:
        assert f"BENCH_{case['case_id']}" in claim_ids
    for hc in be.HEADLINE_CLAIMS:
        assert hc["claim_id"] in claim_ids
    assert len(specs) == 2 + len(cases_doc["cases"]) + len(be.HEADLINE_CLAIMS)


# --------------------------------------------------------------------------- #
# check_evidence.check_claim -- the FAIL/WARN/PASS verdict rules
# --------------------------------------------------------------------------- #

def _artifact(path, content, shipped):
    return {"path": path, "sha256": _sha(content), "bytes": len(content), "shipped": shipped,
            "dev_only": not shipped, "role": "artifact"}


def _write(root, relpath, content):
    full = root / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def test_check_claim_intact_manifest_passes(tmp_path):
    ce = _load_check_evidence()
    _write(tmp_path, "a.txt", "hello")
    claim = {"claim_id": "C1", "status": "served",
             "artifacts": [_artifact("a.txt", "hello", shipped=True)]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "PASS", detail


def test_check_claim_tampered_shipped_artifact_fails(tmp_path):
    ce = _load_check_evidence()
    _write(tmp_path, "a.txt", "TAMPERED")
    claim = {"claim_id": "C1", "status": "served",
             "artifacts": [_artifact("a.txt", "hello", shipped=True)]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "FAIL"
    assert "sha256 mismatch" in detail


def test_check_claim_absent_shipped_artifact_fails(tmp_path):
    ce = _load_check_evidence()
    claim = {"claim_id": "C1", "status": "served",
             "artifacts": [_artifact("missing.txt", "hello", shipped=True)]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "FAIL"
    assert "missing" in detail


@pytest.mark.parametrize("status", ["served", "served-with-refusal", "refused"])
def test_check_claim_served_or_refusal_claim_with_zero_present_artifacts_fails(tmp_path, status):
    ce = _load_check_evidence()
    claim = {"claim_id": "C1", "status": status,
             "artifacts": [_artifact("gone.txt", "x", shipped=False)]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "FAIL"
    assert "no present+sha-matching artifact" in detail


def test_check_claim_dev_only_absent_ok_when_shipped_surrogate_present(tmp_path):
    """The distributed-tree scenario: the raw undistributed run record is not in the tree, but the
    claim's shipped surrogate (the matrix / registry / doc) is -- and is intact."""
    ce = _load_check_evidence()
    _write(tmp_path, "benchmarks/capabilities.json", "{}")
    claim = {"claim_id": "P1", "status": "served", "artifacts": [
        _artifact("trial-runs/2026-01-01_run/plot.png", "binary-ish", shipped=False),
        _artifact("benchmarks/capabilities.json", "{}", shipped=True),
    ]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "PASS", detail
    assert "1/2" in detail


def test_check_claim_tampered_dev_only_artifact_is_not_fatal(tmp_path):
    """Only shipped:true artifacts are individually load-bearing; a stale/tampered undistributed
    sibling next to an intact shipped artifact must not sink the claim (by design -- see the
    module docstring's FAIL-condition list)."""
    ce = _load_check_evidence()
    _write(tmp_path, "trial-runs/2026-01-01_run/plot.png", "TAMPERED")
    _write(tmp_path, "benchmarks/capabilities.json", "{}")
    claim = {"claim_id": "P1", "status": "served", "artifacts": [
        _artifact("trial-runs/2026-01-01_run/plot.png", "original", shipped=False),
        _artifact("benchmarks/capabilities.json", "{}", shipped=True),
    ]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "PASS", detail
    assert "not fatal" in detail


def test_check_claim_partial_all_dev_only_warns():
    ce = _load_check_evidence()
    claim = {"claim_id": "P2", "status": "partial",
             "artifacts": [_artifact("trial-runs/x/RESULT.md", "x", shipped=False)]}
    verdict, detail = ce.check_claim(claim, Path("/nonexistent"))
    assert verdict == "WARN"
    assert "no public surrogate" in detail


def test_check_claim_partial_with_shipped_artifact_passes(tmp_path):
    ce = _load_check_evidence()
    _write(tmp_path, "docs/notes/status.md", "status")
    claim = {"claim_id": "P2", "status": "partial", "artifacts": [
        _artifact("trial-runs/x/RESULT.md", "x", shipped=False),
        _artifact("docs/notes/status.md", "status", shipped=True),
    ]}
    verdict, detail = ce.check_claim(claim, tmp_path)
    assert verdict == "PASS", detail


# --------------------------------------------------------------------------- #
# check_evidence.check_manifest / cmd_check -- CLI-adjacent, module-ROOT redirected to tmp_path
# --------------------------------------------------------------------------- #

def test_cmd_check_fails_loud_when_manifest_missing(tmp_path, capsys):
    ce = _load_check_evidence()
    ce.ROOT = str(tmp_path)   # no evidence/manifest.json under here
    rc = ce.cmd_check(types.SimpleNamespace(root=None))
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err


def test_cmd_check_exits_zero_on_intact_manifest_nonzero_on_tampered(tmp_path, capsys):
    ce = _load_check_evidence()
    ce._source_specs = lambda root: [({"claim_id": "C1", "status": "served"}, ["a.txt"])]
    _write(tmp_path, "a.txt", "hello")
    manifest = {"schema_version": 1, "generated": "", "source_commit": "",
                "claims": [{"claim_id": "C1", "status": "served",
                            "artifacts": [_artifact("a.txt", "hello", shipped=True)]}]}
    (tmp_path / "evidence/manifest.json").write_text(json.dumps(manifest))
    ce.ROOT = str(tmp_path)
    rc = ce.cmd_check(types.SimpleNamespace(root=None))
    assert rc == 0
    assert "1 PASS / 0 WARN / 0 FAIL" in capsys.readouterr().out

    # now tamper the artifact in place -- the same manifest must now FAIL
    (tmp_path / "a.txt").write_text("TAMPERED")
    rc2 = ce.cmd_check(types.SimpleNamespace(root=None))
    assert rc2 == 1
    assert "0 PASS / 0 WARN / 1 FAIL" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# live integration: the committed manifest must check clean
# --------------------------------------------------------------------------- #

def test_live_evidence_manifest_checks_clean():
    manifest_path = REPO / "evidence/manifest.json"
    assert manifest_path.is_file(), \
        "evidence/manifest.json missing at repo root -- run `python3 scripts/build_evidence.py --write`"
    result = subprocess.run([sys.executable, str(CHECK_EVIDENCE_PY), "--check"],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert " 0 FAIL" in result.stdout


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(status="servde"),
    lambda c: c.update(status=[]),
    lambda c: c["artifacts"][0].update(shipped="false"),
    lambda c: c["artifacts"][0].update(dev_only=True),
    lambda c: c["artifacts"][0].update(bytes=True),
    lambda c: c["artifacts"][0].update(path="../outside.txt"),
    lambda c: c["artifacts"][0].update(path="/outside.txt"),
    lambda c: c["artifacts"].append(c["artifacts"][0].copy()),
])
def test_malformed_metadata_cannot_downgrade_integrity(tmp_path, mutate):
    ce = _load_check_evidence()
    _write(tmp_path, "a.txt", "hello")
    claim = {"claim_id": "C1", "status": "served",
             "artifacts": [_artifact("a.txt", "hello", True)]}
    mutate(claim)
    assert ce.check_claim(claim, tmp_path)[0] == "FAIL"


def test_symlink_cannot_substitute_external_evidence(tmp_path):
    ce = _load_check_evidence()
    root = tmp_path / "repo"
    root.mkdir()
    _write(tmp_path, "external.txt", "hello")
    (root / "a.txt").symlink_to(tmp_path / "external.txt")
    claim = {"claim_id": "C1", "status": "served",
             "artifacts": [_artifact("a.txt", "hello", True)]}
    assert ce.check_claim(claim, root)[0] == "FAIL"


def test_duplicate_claims_and_empty_or_unknown_schema_fail(tmp_path):
    ce = _load_check_evidence()
    _write(tmp_path, "a.txt", "hello")
    c = {"claim_id": "C1", "status": "served", "artifacts": [_artifact("a.txt", "hello", True)]}
    for m in ({}, [], {"schema_version": True, "claims": [c]},
              {"schema_version": 1, "claims": []}, {"schema_version": 1, "claims": [c, c]}):
        assert any(v == "FAIL" for _, v, _ in ce.check_manifest(m, tmp_path))


def test_root_uses_staged_manifest_not_source_manifest(tmp_path, capsys):
    ce = _load_check_evidence()
    _write(tmp_path, "a.txt", "hello")
    # The source manifest exists, but the requested stage has no manifest. This used
    # to validate ROOT's manifest against unrelated files and bypass the stage's metadata.
    ce.ROOT = str(REPO)
    assert ce.cmd_check(types.SimpleNamespace(root=str(tmp_path))) == 1
    assert str(tmp_path / "evidence/manifest.json") in capsys.readouterr().err
    (tmp_path / "evidence/manifest.json").write_text('{"schema_version":1,"claims":[],"claims":[]}')
    assert ce.cmd_check(types.SimpleNamespace(root=str(tmp_path))) == 1
    assert "duplicate JSON key" in capsys.readouterr().err


def test_curated_evidence_cannot_be_replaced_by_registry_after_deletion(tmp_path):
    be = _load_build_evidence()
    _write(tmp_path, "docs/notes/status.md", "a historical claim")
    spec = {"claim_id": "C1", "source": "test", "headline": "scan", "status": "served",
            "gate": "g", "candidates": [("trial-runs/sleptonscan_fig3_SCAN/scan.json", "scan-aggregate")],
            "surrogate": ("docs/notes/status.md", "doc-citation")}
    with pytest.raises(be.BuildError, match="mandatory shipped evidence missing"):
        be.materialize_claim(spec, tmp_path)


def test_manifest_cannot_drop_or_downgrade_source_claims(tmp_path):
    ce = _load_check_evidence()
    ce._source_specs = lambda root: [({"claim_id": "C1", "status": "served"}, ["a.txt"]),
                                    ({"claim_id": "C2", "status": "historical"}, [])]
    c = {"claim_id": "C1", "status": "partial", "artifacts": [_artifact("b.txt", "x", True)]}
    rows = ce.check_completeness({"claims": [c]}, tmp_path)
    assert len(rows) == 3
    assert all(v == "FAIL" for _, v, _ in rows)


# --------------------------------------------------------------------------- #
# undistributed records: hard-pinned where the registry declares them, never in a public manifest
# --------------------------------------------------------------------------- #

def _declaring_tree(tmp_path, internal=("notes/private/**",)):
    ce = _load_check_evidence()
    registry = json.loads((REPO / "evidence/collections.json").read_text())
    registry["distribution"] = {k: registry["distribution"][k] for k in ("files", "trees", "extra_files", "exclude")}
    if internal:
        registry["distribution"]["internal"] = list(internal)
    _write(tmp_path, "evidence/collections.json", json.dumps(registry))
    _write(tmp_path, "a.txt", "hello")
    _write(tmp_path, "notes/private/decision.md", "decided")
    ce.ROOT = str(tmp_path)
    ce._source_specs = lambda root: [({"claim_id": "C1", "status": "served"}, ["a.txt"],
                                      ["notes/private/decision.md"])]
    return ce


def _manifest(tmp_path, *artifacts):
    manifest = {"schema_version": 1, "generated": "", "source_commit": "",
                "claims": [{"claim_id": "C1", "status": "served", "artifacts": list(artifacts)}]}
    (tmp_path / "evidence/manifest.json").write_text(json.dumps(manifest))


def test_a_declaring_tree_hard_pins_undistributed_records(tmp_path, capsys):
    ce = _declaring_tree(tmp_path)
    shipped, record = _artifact("a.txt", "hello", True), _artifact("notes/private/decision.md", "decided", False)
    _manifest(tmp_path, shipped, record)
    assert ce.cmd_check(types.SimpleNamespace(root=None)) == 0
    capsys.readouterr()
    (tmp_path / "notes/private/decision.md").write_text("edited")
    assert ce.cmd_check(types.SimpleNamespace(root=None)) == 1
    assert "undistributed artifact 'notes/private/decision.md' sha256 mismatch" in capsys.readouterr().out
    (tmp_path / "notes/private/decision.md").unlink()
    assert ce.cmd_check(types.SimpleNamespace(root=None)) == 1
    assert "undistributed artifact 'notes/private/decision.md' missing" in capsys.readouterr().out
    # A record that the registry does not declare keeps the tolerant note.
    ce = _declaring_tree(tmp_path, internal=())
    _manifest(tmp_path, shipped, _artifact("notes/private/decision.md", "other", False))
    assert ce.cmd_check(types.SimpleNamespace(root=None)) == 0


def test_a_declaring_tree_requires_the_undistributed_records_a_claim_names(tmp_path, capsys):
    ce = _declaring_tree(tmp_path)
    _manifest(tmp_path, _artifact("a.txt", "hello", True))
    assert ce.cmd_check(types.SimpleNamespace(root=None)) == 1
    assert "undistributed record omitted: ['notes/private/decision.md']" in capsys.readouterr().out
    # A public tree's manifest omits it by design.
    assert ce.cmd_check(types.SimpleNamespace(root=None, public=True)) == 0


def test_public_mode_rejects_a_listed_undistributed_record(tmp_path, capsys):
    ce = _declaring_tree(tmp_path)
    _manifest(tmp_path, _artifact("a.txt", "hello", True), _artifact("notes/private/decision.md", "decided", False))
    assert ce.cmd_check(types.SimpleNamespace(root=None, public=True)) == 1
    assert "undistributed artifact(s) listed in a public manifest" in capsys.readouterr().out
