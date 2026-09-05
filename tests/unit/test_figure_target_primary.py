"""figure_target.py {primary, checkin, fulfil-primary} + primary-aware compose (Phase 3, D5/D9).

Import the module under test by FILE PATH (the repo root carries a py.py that shadows the real
py package pytest needs if the repo root lands on sys.path). Drive the CLI subcommands via
subprocess (they are stdlib-only; only `compose` needs PIL, and we unit-test its resolver
function directly). Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FT_PY = REPO / "src" / "ravel" / "plotting" / "figure_target.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("figure_target_under_test", FT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*args):
    return subprocess.run([sys.executable, str(FT_PY), *args], capture_output=True, text=True)


def _declare(rd, figure_id, role="summary", primary=False, arxiv="2306.11055"):
    args = ["declare", "--rundir", str(rd), "--role", role, "--figure-id", figure_id,
            "--source", "paper-inspection", "--arxiv", arxiv, "--no-checkin"]
    if primary:
        args.append("--primary")
    return _run(*args)


def _contract(rd):
    return json.load(open(Path(rd) / "inputs" / "figure_target.json"))


def test_primary_enforces_single_primary(tmp_path):
    rd = tmp_path / "run"
    assert _declare(rd, "Figure 3", primary=True).returncode == 0
    assert _declare(rd, "Figure 5", role="overlay", primary=True).returncode == 0
    # bug repro: declare --primary only ever SETS True, so two targets are both primary
    assert sum(1 for t in _contract(rd)["targets"] if t.get("primary")) == 2
    r = _run("primary", "--rundir", str(rd), "--figure-id", "Figure 3")
    assert r.returncode == 0, r.stderr
    prim = [t for t in _contract(rd)["targets"] if t.get("primary")]
    assert len(prim) == 1 and prim[0]["figure_id"] == "Figure 3"
    q = _run("primary", "--rundir", str(rd))
    assert q.returncode == 0 and "Figure 3" in q.stdout


def test_primary_query_ambiguous_when_two_primaries(tmp_path):
    rd = tmp_path / "run"
    _declare(rd, "Figure 3", primary=True)
    _declare(rd, "Figure 5", role="overlay", primary=True)
    q = _run("primary", "--rundir", str(rd))
    assert q.returncode == 1
    assert "AMBIGUOUS" in (q.stdout + q.stderr)


def test_checkin_marks_declared_at_checkin_on_primary(tmp_path):
    rd = tmp_path / "run"
    _declare(rd, "Figure 3", primary=True)                 # --no-checkin => declared_at_checkin False
    assert _contract(rd)["targets"][0]["declared_at_checkin"] is False
    r = _run("checkin", "--rundir", str(rd))
    assert r.returncode == 0, r.stderr
    assert _contract(rd)["targets"][0]["declared_at_checkin"] is True
    assert "declared_at_checkin=True" in r.stdout


def test_checkin_refuses_without_a_single_primary(tmp_path):
    rd = tmp_path / "run"
    _declare(rd, "Figure 3", primary=True)
    _declare(rd, "Figure 5", role="overlay", primary=True)  # two primaries -> ambiguous
    r = _run("checkin", "--rundir", str(rd))
    assert r.returncode == 1


def test_fulfil_primary_writes_verified_by_physicist(tmp_path):
    rd = tmp_path / "run"
    _declare(rd, "Figure 3", primary=True)
    # no side_by_side yet -> refuse (the physicist verifies AGAINST the composite)
    assert _run("fulfil-primary", "--rundir", str(rd), "--by", "Dr X").returncode == 1
    # inject a real side_by_side file + record it in the contract
    sbs = rd / "plots" / "sbs.png"
    sbs.parent.mkdir(parents=True, exist_ok=True)
    sbs.write_bytes(b"PNG")
    doc = _contract(rd)
    doc["targets"][0]["side_by_side"] = str(sbs)
    json.dump(doc, open(rd / "inputs" / "figure_target.json", "w"), indent=2)
    r = _run("fulfil-primary", "--rundir", str(rd), "--by", "Dr X", "--note", "verified")
    assert r.returncode == 0, r.stderr
    vp = _contract(rd)["targets"][0]["verified_by_physicist"]
    assert vp and vp["by"] == "Dr X" and vp["note"] == "verified"


import pytest


def test_resolve_compose_target_falls_back_to_primary():
    ft = _load_module()
    doc = {"schema_version": 1, "targets": [
        {"figure_id": "Figure 3", "role": "summary", "primary": True},
        {"figure_id": "Figure 5", "role": "overlay", "primary": False}]}
    tgt, fid = ft.resolve_compose_target(doc, None)
    assert fid == "Figure 3" and tgt["role"] == "summary"
    tgt2, fid2 = ft.resolve_compose_target(doc, "fig 5")
    assert fid2 == "Figure 5" and tgt2["role"] == "overlay"


def test_resolve_compose_target_ambiguous_without_id_raises():
    ft = _load_module()
    doc = {"schema_version": 1, "targets": [
        {"figure_id": "Figure 3", "primary": True},
        {"figure_id": "Figure 5", "primary": True}]}
    with pytest.raises(SystemExit):
        ft.resolve_compose_target(doc, None)


def test_compose_figure_id_is_optional_in_argparse():
    # the compose subparser must NOT require --figure-id (missing id -> primary fallback path);
    # with no contract at all the code should reach load_contract (a die), NOT an argparse error.
    r = _run("compose", "--rundir", "/nonexistent-run-dir")
    assert r.returncode == 1
    assert "figure-id" not in r.stderr.lower()      # not an argparse "required" error


# ---------------------------------------------------------------- Task 2 (A2): compose provenance
VRS_PY = REPO / "src" / "ravel" / "validation" / "validate_run_state.py"


def _load_vrs():
    spec = importlib.util.spec_from_file_location("vrs_under_test_a2", VRS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _a2_run(tmp_path, side_by_side, composed_by, create_file=False):
    """A run dir whose PRIMARY (declared at check-in) carries a generated counterpart and the
    given side_by_side/composed_by fields; generation_hits present so the primary block fires."""
    vrs = _load_vrs()
    rd = tmp_path / "2026-08-02_TEST_a2-primary"
    (rd / "inputs").mkdir(parents=True)
    (rd / "outputs").mkdir()
    contract = vrs._base_contract(task_mode="reproduce", compute_plan="smoke")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    vrs._write_json(str(rd / "outputs" / "sr_yields.json"), {"srs": {"SR1": 1.0}})
    cp = rd / "plots" / "counterpart.png"
    cp.parent.mkdir()
    cp.write_bytes(b"\x89PNG\r\n\x1a\n")
    tgt = {"figure_id": "Figure 5", "role": "exclusion", "primary": True,
           "declared_at_checkin": True,
           "generated_counterpart": str(cp), "side_by_side": side_by_side}
    if composed_by is not None:
        tgt["composed_by"] = composed_by
    if create_file and side_by_side:
        p = Path(side_by_side)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
    vrs._write_json(str(rd / "inputs" / "figure_target.json"),
                    {"schema_version": 1, "targets": [tgt]})
    return vrs, rd, contract


def test_primary_handpopulated_fails(tmp_path):
    """QI.2: a side_by_side path written by hand (file absent, no composed_by stamp) must FAIL."""
    vrs, rd, contract = _a2_run(tmp_path, str(tmp_path / "nope.png"), composed_by=None)
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_figure_contract_fulfilled(str(rd), contract, facts, False, False)
    assert status == "FAIL", (status, detail)
    assert "composed_by" in detail or "not on disk" in detail


def test_primary_file_on_disk_but_unstamped_fails(tmp_path):
    """The hand-populate hole precisely: the file EXISTS but nothing proves compose produced it."""
    vrs, rd, contract = _a2_run(tmp_path, str(tmp_path / "sbs.png"), composed_by=None,
                                create_file=True)
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_figure_contract_fulfilled(str(rd), contract, facts, False, False)
    assert status == "FAIL", (status, detail)
    assert "composed_by" in detail


def test_primary_composed_and_stamped_passes(tmp_path):
    vrs, rd, contract = _a2_run(tmp_path, str(tmp_path / "sbs.png"),
                                composed_by={"tool": "figure_target.py compose", "utc": ""},
                                create_file=True)
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_figure_contract_fulfilled(str(rd), contract, facts, False, False)
    assert status in ("PASS", "N/A"), (status, detail)


def test_primary_handpopulated_legacy_warns(tmp_path):
    vrs, rd, contract = _a2_run(tmp_path, str(tmp_path / "nope.png"), composed_by=None)
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_figure_contract_fulfilled(str(rd), contract, facts, True, False)
    assert status == "WARN", (status, detail)


def test_compose_write_site_stamps_provenance():
    """The compose write-site must stamp composed_by alongside side_by_side (source contract:
    the stamp line sits between the side_by_side assignment and save_contract, so every compose
    output is stamped -- no code path writes side_by_side unstamped)."""
    src = FT_PY.read_text(encoding="utf-8")
    i = src.index('tgt["side_by_side"] = os.path.abspath(out)')
    j = src.index("save_contract(args.rundir, doc)", i)
    stamp = src[i:j]
    assert 'tgt["composed_by"]' in stamp and "figure_target.py compose" in stamp
