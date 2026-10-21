"""Typed final-state observables, PDF selection and the optional shower stage."""
from copy import deepcopy
import gzip
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from ravel.physics import final_state_observables as fso
from ravel.physics.scoped import audit_lhe
from ravel.workflow import scoped_spec


def typed_generation(observables=None, **settings):
    run = {"ebeam1": 6500, "ebeam2": 6500, "lpp1": 1, "lpp2": 1, "pdlabel": "nn23lo1", "lhaid": 247000,
           "fixed_ren_scale": False, "fixed_fac_scale": False, "dynamical_scale_choice": 4, "scalefact": 1}
    run.update(settings)
    return {"schema_version": 1, "mode": "generate", "source": "SM parton control",
            "assumptions": ["Unmerged LO"], "max_seconds": 120, "approval_mode": "scripted_yes",
            "generation": {"runtime": {"madgraph": "/installed/mg5", "python": "/installed/python", "compiler": "/installed/gfortran"},
                           "model": "sm", "definitions": {}, "process": "p p > w+ > e+ ve", "events": 2, "seed": 7,
                           "beam_pdg": [2212, 2212], "run_settings": run,
                           "observables": observables or [
                               {"id": "met", "kind": "missing_et", "pdg": [12, 14, 16], "abs_pdg": True,
                                "bin_edges": [0, 20, 40, 60], "normalization": "unit_area"},
                               {"id": "pt_e", "kind": "pt", "pdg": [-11], "combine": "leading", "count": 1,
                                "bin_edges": [0, 25, 50], "normalization": "events"},
                               {"id": "eta_e", "kind": "eta", "pdg": [11], "abs_pdg": True, "combine": "each",
                                "bin_edges": [-5, 0, 5], "normalization": "cross_section"},
                               {"id": "mt_pair", "kind": "invariant_mass", "pdg": [-11, 12], "combine": "system",
                                "count": 2, "bin_edges": [0, 50, 100, 200], "normalization": "events"}]}}


def test_typed_observables_and_builtin_pdf_are_valid():
    assert not scoped_spec.validate(typed_generation())


@pytest.mark.parametrize("change", ["lhaid", "kind", "count", "units", "both", "edges", "duplicate", "lhapdf_runtime"])
def test_invalid_typed_specs(change):
    spec = typed_generation()
    g = spec["generation"]
    if change == "lhaid":
        g["run_settings"]["lhaid"] = 10042
    elif change == "kind":
        g["observables"][0]["kind"] = "sphericity"
    elif change == "count":
        g["observables"][3]["count"] = 0
    elif change == "units":
        g["observables"][0]["normalization"] = "per_gev"
    elif change == "both":
        g["observable"] = {"kind": "final_state_mass", "final_state_pdg": [11], "bin_edges_gev": [0, 1, 2]}
    elif change == "edges":
        g["observables"][1]["bin_edges"] = [0, 50, 25]
    elif change == "duplicate":
        g["observables"][1]["id"] = "met"
    else:
        g["run_settings"].update(pdlabel="lhapdf", lhaid=303400)
    assert scoped_spec.validate(spec)


def test_lhapdf_set_needs_an_lhapdf_runtime():
    spec = typed_generation(pdlabel="lhapdf", lhaid=260000)
    spec["generation"]["runtime"]["lhapdf_config"] = "/installed/lhapdf-config"
    assert not scoped_spec.validate(spec)


def particles():
    # (pdg, px, py, pz, e): a W-like e+ nu pair and a soft extra neutrino.
    return [(-11, 30., 0., 40., 50.), (12, -20., 0., 0., 20.), (14, 0., 5., 0., 5.)]


def test_observable_functions_are_exact():
    obs = typed_generation()["generation"]["observables"]
    values = fso.evaluate(particles(), obs)
    assert values["met"] == [pytest.approx(math.hypot(-20., 5.))]
    assert values["pt_e"] == [30.]
    assert values["eta_e"] == [pytest.approx(math.asinh(40. / 30.))]
    total = (10., 0., 40., 70.)
    assert values["mt_pair"] == [pytest.approx(math.sqrt(70. ** 2 - 10. ** 2 - 40. ** 2))]


def test_missing_selection_is_an_unfilled_event_not_a_value():
    obs = [{"id": "pair", "kind": "invariant_mass", "pdg": [11, -11], "combine": "system", "count": 2, "bin_edges": [0, 1]}]
    assert fso.evaluate(particles(), obs) == {"pair": []}


def test_histogram_normalizations():
    edges = [0., 1., 3.]
    h = fso.histogram([0.5, 2., 2.5, 7.], edges, "events", events=4, cross_section_pb=8.)
    assert h["counts"] == [1, 2] and h["overflow"] == 1 and h["values"] == [1, 2]
    u = fso.histogram([0.5, 2., 2.5], edges, "unit_area", events=3, cross_section_pb=8.)
    assert sum(v * w for v, w in zip(u["values"], [1., 2.])) == pytest.approx(1.)
    x = fso.histogram([0.5, 2., 2.5], edges, "cross_section", events=4, cross_section_pb=8.)
    assert x["values"] == pytest.approx([2., 2.]) and x["unit"].startswith("pb")


def lhe(events):
    head = """<LesHouchesEvents version="1.0">
<header>
<MGRunCard>
1=lpp1
1=lpp2
6500=ebeam1
6500=ebeam2
nn23lo1=pdlabel
247000=lhaid
2=nevents
7=iseed
False=use_syst
none=systematics_program
0=ickkw
</MGRunCard>
<MG5ProcCard>
import model sm
generate p p &gt; w+ &gt; e+ ve
</MG5ProcCard>
<slha>
BLOCK MASS
24 80.4
</slha>
</header>
<init>
2212 2212 6500 6500 0 0 247000 247000 -4 1
1.5e4 30 1 1
</init>
"""
    event = """<event>
5 1 1.0 80 0.007 0.118
2 -1 0 0 501 0 0 0 40 40 0 0 9
-1 -1 0 0 0 501 0 0 -20 20 0 0 9
24 2 1 2 0 0 0 0 20 60 56.568542494923804 0 9
-11 1 3 3 0 0 28.284271247461902 0 10 30 0 0 9
12 1 3 3 0 0 -28.284271247461902 0 10 30 0 0 9
</event>
"""
    return head + event * events + "</LesHouchesEvents>\n"


def test_audit_fills_typed_observables_from_every_event(tmp_path):
    spec = typed_generation()["generation"]
    spec["observables"] = spec["observables"][:2]
    spec["run_settings"] = {"ebeam1": 6500, "ebeam2": 6500, "pdlabel": "nn23lo1", "lhaid": 247000}
    p = tmp_path / "events.lhe.gz"
    p.write_bytes(gzip.compress(lhe(2).encode()))
    result = audit_lhe(p, spec)
    assert result["observables"]["met"] == pytest.approx([28.284271247461902] * 2)
    assert result["observables"]["pt_e"] == pytest.approx([28.284271247461902] * 2)
    assert result["recipe"]["pdf_ids"] == [247000, 247000]
    assert "masses_gev" not in result


def pythia_python():
    value = os.environ.get("RAVEL_TEST_PYTHIA_PYTHON")
    return value if value and Path(value).is_file() else None


@pytest.mark.skipif(pythia_python() is None, reason="set RAVEL_TEST_PYTHIA_PYTHON to a Python with pythia8 bindings")
def test_real_pythia_shower_fills_particle_level_observables(tmp_path):
    from ravel.physics import scoped_shower
    lhe_path = tmp_path / "events.lhe"
    lhe_path.write_text(lhe(20))
    obs = [{"id": "met", "kind": "missing_et", "pdg": [12, 14, 16], "abs_pdg": True, "bin_edges": [0, 50, 100],
            "normalization": "events"},
           {"id": "pt_e", "kind": "pt", "pdg": [-11], "combine": "leading", "count": 1, "bin_edges": [0, 50, 100],
            "normalization": "events"}]
    shower = {"engine": "pythia8", "python": pythia_python(), "seed": 11,
              "settings": ["PartonLevel:MPI = off", "HadronLevel:all = off"]}
    result = scoped_shower.run_shower(lhe_path, shower, obs, tmp_path / "shower")
    assert result["events_read"] == 20 and result["events_showered"] == 20
    assert len(result["observables"]["pt_e"]) == 20
    assert all(v > 0 for v in result["observables"]["met"])


def fake_native(tmp_path):
    import sys
    native = tmp_path / "native"
    (native / "bin").mkdir(parents=True)
    (native / "bin/mg5_aMC").write_text("# fixture only; never executed\n")
    (native / "VERSION").write_text("fixture\n")
    (native / "models/sm").mkdir(parents=True)
    (native / "models/sm/particles.py").write_text("# fixture\n")
    data = tmp_path / "lhapdf-data"
    (data / "NNPDF30_nlo_as_0118").mkdir(parents=True)
    (data / "NNPDF30_nlo_as_0118/NNPDF30_nlo_as_0118.info").write_text(
        "SetDesc: fixture\nFlavors: [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 21]\n")
    (data / "pdfsets.index").write_text("260000 NNPDF30_nlo_as_0118 1\n")
    config = tmp_path / "lhapdf-config"
    config.write_text(f"#!/bin/sh\necho {data}\n")
    config.chmod(0o755)
    compiler = tmp_path / "gfortran"
    compiler.write_text("# fixture compiler; never executed\n")
    # The interpreter is named by its real file: where the environment's python is a symlink (the
    # usual Linux layout) the runtime and the shower would otherwise declare one file by two paths.
    return native, config, str(Path(sys.executable).resolve()), str(compiler)


def test_plan_binds_lhapdf_set_and_shower_runtime(tmp_path, monkeypatch):
    from ravel.cli import main
    from ravel.physics import scoped_shower
    from ravel.workflow import scoped
    from ravel.workflow.state_io import atomic_json, read_json
    native, config, python, compiler = fake_native(tmp_path)
    binding = tmp_path / "pythia8.py"
    binding.write_text("# fixture binding\n")
    monkeypatch.setattr(scoped_shower, "probe", lambda p: [binding])
    rd = tmp_path / "generation"
    assert main(["initiate", "--prompt", "Generate a generation-only parton control.", "--out", str(rd)]) == 0
    spec = typed_generation(pdlabel="lhapdf", lhaid=260000)
    g = spec["generation"]
    g["runtime"] = {"madgraph": str(native), "python": python, "compiler": compiler, "lhapdf_config": str(config)}
    g["shower"] = {"engine": "pythia8", "python": python, "seed": 3, "settings": ["PartonLevel:MPI = off"]}
    from model_validation_fixture import scoped_evidence
    scoped_evidence(g, tmp_path)
    atomic_json(tmp_path / "spec.json", spec)
    plan = scoped.plan(rd, tmp_path / "spec.json")
    assert str(binding) in plan["stages"][0]["inputs"]
    assert str(tmp_path / "lhapdf-data/NNPDF30_nlo_as_0118/NNPDF30_nlo_as_0118.info") in plan["stages"][0]["inputs"]
    assert plan["pdf"]["name"] == "NNPDF30_nlo_as_0118" and plan["pdf"]["flavours"][-1] == 21
    contract = read_json(rd / "inputs/task_contract.json")
    assert contract["detector_mode"] == "particle-level"
    assert "particle level" in (rd / "CHECKIN1.md").read_text()


def test_plan_refuses_an_lhapdf_set_that_is_not_installed(tmp_path):
    from ravel.cli import main
    from ravel.workflow import scoped
    from ravel.workflow.state_io import atomic_json
    native, config, python, compiler = fake_native(tmp_path)
    rd = tmp_path / "generation"
    main(["initiate", "--prompt", "Generate a generation-only parton control.", "--out", str(rd)])
    spec = typed_generation(pdlabel="lhapdf", lhaid=82400)
    spec["generation"]["runtime"] = {"madgraph": str(native), "python": python, "compiler": compiler, "lhapdf_config": str(config)}
    atomic_json(tmp_path / "spec.json", spec)
    with pytest.raises(ValueError, match="82400"):
        scoped.plan(rd, tmp_path / "spec.json")


def test_parton_and_particle_histograms_and_figure(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("mplhep")
    from ravel.physics import scoped as worker
    g = typed_generation()["generation"]
    result = {"events": 4, "cross_section_pb": 2.0,
              "observables": {"met": [5., 25., 30., 45.], "pt_e": [10., 30., 35.], "eta_e": [-1., 1., 2.], "mt_pair": [60., 70.]},
              "particle_level": {"events": 4, "observables": {"met": [6., 22., 31., 50.], "pt_e": [9., 28., 33., 40.],
                                                                "eta_e": [-1.1, .9], "mt_pair": [61.]}}}
    result["histograms"] = worker.histograms(result, g)
    assert set(result["histograms"]) == {"parton", "particle"}
    assert result["histograms"]["parton"]["met"]["normalization"] == "unit_area"
    assert result["histograms"]["parton"]["eta_e"]["values"] == pytest.approx([2. / 4 / 5, 4. / 4 / 5 * 1])
    worker.plot_observables(tmp_path, result, g)
    figure = json.loads((tmp_path / "figure.json").read_text())
    assert figure["plot_lint"] == "PASS" and figure["levels"] == ["parton", "particle"]
    assert (tmp_path / "figure.png").stat().st_size > 0
