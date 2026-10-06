"""Adversarial contracts and custody controls; no native event generation here."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.cli import main
from ravel.physics.scoped import parameter_recipe, prepare_workspace, run_card
from ravel.validation.validate_run_state import evaluate
from ravel.validation.validate_task_contract import validate as validate_contract
from ravel.workflow import execution, scoped, scoped_spec
from ravel.workflow.route_prompt import route
from ravel.workflow.state_io import atomic_json, read_json


def counting_spec():
    return {"schema_version": 1, "mode": "likelihood", "source": "ATLAS 2jl counting approximation: n=263, b=283 +/-24",
            "assumptions": ["One bin with a gamma/Poisson background constraint; not the full ATLAS likelihood"],
            "max_seconds": 120, "approval_mode": "scripted_yes",
            "likelihood": {"counting": {"observed": 263, "background": 283, "background_uncertainty": 24, "signal": 1},
                           "poi_cap": 256, "normalization": {"kind": "signal_events", "luminosity_fb": 3.2}}}


def generation_spec():
    return {"schema_version": 1, "mode": "generate", "source": "SM parton control",
            "assumptions": ["Unmerged LO, no shower or detector"], "max_seconds": 120, "approval_mode": "scripted_yes",
            "generation": {"runtime": {"madgraph": "/installed/mg5", "python": "/installed/python", "compiler": "/installed/gfortran"},
                "model": "sm-no_b_mass", "definitions": {"p": "g u c d s b u~ c~ d~ s~ b~"}, "process": "p p > e+ e-",
                "events": 100, "seed": 1729, "beam_pdg": [2212, 2212],
                "run_settings": {"ebeam1": 6500, "ebeam2": 6500, "lpp1": 1, "lpp2": 1, "pdlabel": "cteq6l1", "lhaid": 10042,
                                 "fixed_ren_scale": False, "fixed_fac_scale": False, "dynamical_scale_choice": 4, "scalefact": 1},
                "observable": {"kind": "final_state_mass", "final_state_pdg": [-11, 11], "bin_edges_gev": [40, 60, 120, 200]}}}


@pytest.fixture
def planned(tmp_path):
    rd = tmp_path / "run"
    assert main(["initiate", "--prompt", "Compute a likelihood-only control for the supplied counting model.", "--out", str(rd)]) == 0
    source = tmp_path / "spec.json"
    atomic_json(source, counting_spec())
    scoped.plan(rd, source)
    return rd


@pytest.mark.parametrize("prompt,mode", [
    ("Generate 100 parton-level Drell-Yan events without a shower or detector.", "generate"),
    ("Produce a generation-only SM sample.", "generate"),
    ("Compute a likelihood-only limit.", "likelihood"),
    ("Fit the supplied workspace and calculate its observed and expected limits.", "likelihood"),
    ("Reproduce the ATLAS analysis using a likelihood and parton-level generation.", "reproduce"),
    ("Do not generate parton-level events. Compute a statistics-only limit.", "likelihood"),
    ("Reproduce arXiv:1911.12606 with detector simulation and a likelihood-only cross-check.", "reproduce"),
    ("Do not compute a likelihood-only result. Reproduce the analysis.", "reproduce"),
])
def test_scope_does_not_truncate_broader_requests(prompt, mode):
    contract = route(prompt)
    assert contract["task_mode"] == mode
    assert not validate_contract(contract)


@pytest.mark.parametrize("path,value", [
    (("max_seconds",), True), (("max_seconds",), 0), (("max_seconds",), 86401),
    (("likelihood", "poi_cap"), float("inf")), (("likelihood", "poi_cap"), 0),
    (("likelihood", "counting", "observed"), -1),
    (("likelihood", "counting", "observed"), 2.5),
    (("likelihood", "counting", "background_uncertainty"), -1),
    (("likelihood", "counting", "background"), 0), (("likelihood", "counting", "signal"), 0),
    (("likelihood", "counting", "signal"), 2),
    (("likelihood", "normalization", "luminosity_fb"), 0),
    (("likelihood", "normalization", "kind"), "signal_strength"),
    (("assumptions",), []), (("approval_mode",), "automatic_expert_review"),
    (("invented",), "ignored"),
])
def test_bad_statistics_specs(path, value):
    spec = counting_spec()
    target = spec
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert scoped_spec.validate(spec)


@pytest.mark.parametrize("path,value", [
    (("generation", "events"), True), (("generation", "events"), 0),
    (("generation", "events"), 2.5), (("generation", "events"), 1000001),
    (("generation", "seed"), 0), (("generation", "seed"), 30082),
    (("generation", "process"), "p p > e+ e-\nlaunch /tmp/escape"),
    (("generation", "process"), "p p > e+ e- [QCD]"),
    (("generation", "model"), "../../models"),
    (("generation", "definitions"), {"p\noutput elsewhere": "g u d"}),
    (("generation", "run_settings", "nevents"), 100000),
    (("generation", "run_settings", "ickkw"), 1),
    (("generation", "run_settings", "ebeam1"), -1),
    (("generation", "run_settings", "fixed_ren_scale"), "False"),
    (("generation", "run_settings", "fixed_ren_scale"), True),
    (("generation", "run_settings", "pdlabel"), "lhapdf"),
    (("generation", "observable", "bin_edges_gev"), [0, 100, 50]),
])
def test_bad_generation_specs(path, value):
    spec = generation_spec()
    target = spec
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert scoped_spec.validate(spec)


def test_valid_specs():
    assert not scoped_spec.validate(counting_spec())
    assert not scoped_spec.validate(generation_spec())


def test_plan_is_concrete_but_not_execution(planned):
    assert not (planned / "execution_state.json").exists()
    assert not (planned / "outputs").exists()
    checkin = read_json(planned / "inputs/checkin1.json")
    assert checkin["sections"]["i-b"]["recipe"]["likelihood"]["counting"]["observed"] == 263
    contract = read_json(planned / "inputs/task_contract.json")
    result = evaluate(str(planned), contract, strict=True)
    assert result["verdict"] == "FAIL"
    assert next(s for s in result["stages"] if s["name"] == "generation")["status"] == "N/A"
    with pytest.raises(ValueError, match="approval"):
        scoped.run(planned)
    assert not (planned / "execution_attempt.json").exists()


def test_scripted_is_not_expert_review(planned):
    with pytest.raises(ValueError, match="approval mode"):
        scoped.approve(planned, "yes")
    assert scoped.approve(planned, "Authorized experimental YES to this concrete plan", scripted=True) == 0
    assert read_json(planned / "inputs/scoped-plan.json")["expert_review"] is False
    scoped.verify_plan(planned, require_approval=True)


@pytest.mark.parametrize("file", ["inputs/scoped.json", "inputs/workspace.json", "inputs/scoped-plan.json", "inputs/checkin1.json", "inputs/task_contract.json"])
def test_stale_inputs_never_launch(planned, file, monkeypatch):
    scoped.approve(planned, "yes", scripted=True)
    p = planned / file
    p.write_text(p.read_text() + "\n")
    from ravel.workflow import stage_supervisor
    monkeypatch.setattr(stage_supervisor, "supervise", lambda *a, **k: pytest.fail("stale input launched compute"))
    with pytest.raises(ValueError):
        scoped.run(planned)


def test_failed_attempt_spends_budget_and_preserves_failure(planned, monkeypatch):
    scoped.approve(planned, "yes", scripted=True)
    from ravel.workflow import stage_supervisor
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        return 124
    monkeypatch.setattr(stage_supervisor, "supervise", fail)
    assert scoped.run(planned) == 124
    for resume in (False, True):
        with pytest.raises(ValueError, match="attempt is already spent"):
            scoped.run(planned, resume=resume)
    assert len(calls) == 1
    assert read_json(planned / "execution_attempt.json")["attempt"] == 1


def test_exit_zero_without_scientific_delivery_fails(planned, monkeypatch):
    scoped.approve(planned, "yes", scripted=True)
    from ravel.workflow import stage_supervisor
    monkeypatch.setattr(stage_supervisor, "supervise", lambda *a, **k: 0)
    assert scoped.run(planned) == 3


def test_scoped_artifact_roots_reject_symlinks(planned, tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (planned / "outputs").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        scoped.verify_plan(planned)
    assert not list(target.iterdir())


@pytest.mark.parametrize("missing", ["model", "restriction"])
def test_native_plan_rejects_missing_model_inputs(tmp_path, missing):
    import sys
    native = tmp_path / "native"
    (native / "bin").mkdir(parents=True)
    (native / "bin/mg5_aMC").write_text("# fixture only; never executed\n")
    (native / "VERSION").write_text("fixture\n")
    (native / "models").mkdir()
    if missing == "restriction":
        (native / "models/sm").mkdir()
    rd = tmp_path / "generation"
    main(["initiate", "--prompt", "Generate a generation-only parton control.", "--out", str(rd)])
    spec = generation_spec()
    spec["generation"]["runtime"] = {"madgraph": str(native), "python": sys.executable, "compiler": sys.executable}
    atomic_json(tmp_path / "spec.json", spec)
    with pytest.raises(ValueError, match="model"):
        scoped.plan(rd, tmp_path / "spec.json")
    assert not (rd / "execution_attempt.json").exists()


def test_installed_bootstrap_does_not_duplicate_package_discovery(monkeypatch):
    import sys
    from ravel import _bootstrap
    parent = str(Path(_bootstrap.__file__).resolve().parents[1])
    paths = [parent, *sys.path]
    monkeypatch.setattr(sys, "path", paths.copy())
    monkeypatch.setattr(sys, "argv", ["ravel", "original"])
    monkeypatch.setattr(_bootstrap.runpy, "run_module", lambda *a, **k: None)
    _bootstrap.main(["ravel.__main__", "--help"])
    assert sys.path == paths


def test_cannot_overwrite_a_plan(planned, tmp_path):
    source = tmp_path / "another.json"
    atomic_json(source, counting_spec())
    with pytest.raises(ValueError, match="already exists"):
        scoped.plan(planned, source)


def test_receipt_absence_is_not_comparability(planned):
    result = scoped.compare(planned, planned)
    assert not result["comparable"] and result["errors"]


def test_direct_worker_cannot_bypass_attempt_budget(planned):
    scoped.approve(planned, "yes", scripted=True)
    with pytest.raises((OSError, ValueError)):
        scoped.verify_worker(planned)
    assert not (planned / "outputs").exists()


def test_bounded_roots_are_retained_but_not_delivered(tmp_path, monkeypatch):
    from ravel.physics import scoped as worker, pyhf_exclude
    spec = counting_spec()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "outputs").mkdir()
    atomic_json(tmp_path / "inputs/workspace.json", prepare_workspace(spec, tmp_path))
    def unresolved(*args, **kwargs):
        kwargs["diagnostic_record"]["reason"] = "root above cap"
        return {"obs_limit": 10., "exp_limits": [10.] * 5,
                "limit_status": {"observed": "above_scan", "expected": ["above_scan"] * 5}}
    monkeypatch.setattr(pyhf_exclude, "compute", unresolved)
    with pytest.raises(ValueError, match="not all six"):
        worker.likelihood(tmp_path, spec)
    result = read_json(tmp_path / "outputs/result.json")
    assert result["obs_limit"] == 10.  # preserved legacy bound, explicitly above_scan
    assert result["visible_cross_section_fb"]["observed"] is None
    assert not (tmp_path / "outputs/figure.png").exists()
    assert (tmp_path / "outputs/fit-diagnostics.json").exists()


def test_recipe_gate_refuses_tampered_deliveries(planned, monkeypatch):
    scoped.approve(planned, "yes", scripted=True)
    # The comparator must call both approval and completion validation. Merely
    # placing an equal-looking recipe at each path is never sufficient.
    (planned / "outputs").mkdir()
    recipe = {"kind": "supplied_likelihood", "workspace": {"identical": True}}
    atomic_json(planned / "outputs/recipe.json", {"recipe": recipe, "sha256": execution.digest(recipe)})
    assert not scoped.compare(planned, planned)["comparable"]


@pytest.mark.parametrize("change", ["fixed", "zero_signal", "bounds", "negative_data", "second_measurement"])
def test_supplied_workspace_failures(tmp_path, change):
    spec = counting_spec()
    workspace = prepare_workspace(spec, tmp_path)
    par = workspace["measurements"][0]["config"]["parameters"][0]
    if change == "fixed":
        par["fixed"] = True
    elif change == "zero_signal":
        workspace["channels"][0]["samples"][0]["data"] = [0]
    elif change == "bounds":
        par["bounds"] = [[0, 10]]
    elif change == "negative_data":
        workspace["observations"][0]["data"] = [-1]
    else:
        second = deepcopy(workspace["measurements"][0])
        second["name"] = "ambiguous"
        workspace["measurements"].append(second)
    atomic_json(tmp_path / "workspace.json", workspace)
    spec["likelihood"] = {"workspace": "workspace.json", "poi_cap": 256, "normalization": {"kind": "signal_strength"}}
    with pytest.raises(ValueError):
        prepare_workspace(spec, tmp_path)


def test_recipe_retains_defaults_and_semantic_changes():
    a = run_card("6.500D+03 = ebeam1 ! beam\n.false. = fixed_ren_scale\n'cteq6l1'=pdlabel\n4=dynamical_scale_choice")
    b = run_card("6500=ebeam1\nFalse=fixed_ren_scale\ncteq6l1=pdlabel\n4.0=dynamical_scale_choice")
    assert not scoped.differences(a, b)
    b["dynamical_scale_choice"] = 3.0
    assert scoped.differences(a, b)[0]["field"] == "recipe.dynamical_scale_choice"
    del b["ebeam1"]
    assert any(d["field"] == "recipe.ebeam1" for d in scoped.differences(a, b))
    with pytest.raises(ValueError, match="duplicate"):
        run_card("1=ebeam1\n2=ebeam1")
    assert parameter_recipe("BLOCK MASS # comment\n23 9.1188d1") == parameter_recipe("block mass\n23 91.188")


def test_duplicate_json_rejected_before_plan(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"mode":"generate", "mode":"likelihood"}')
    with pytest.raises(ValueError, match="duplicate"):
        read_json(p)
