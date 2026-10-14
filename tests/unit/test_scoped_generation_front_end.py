"""Scoped generation front end with a mocked MadGraph: versions, beams, batches, transforms, models."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import sys

import pytest

from ravel.cli import main
from ravel.physics import generation_receipt
from ravel.physics import scoped as worker
from ravel.workflow import scoped, scoped_spec
from ravel.workflow.state_io import atomic_json, read_json

LUX = "LUXlep-NNPDF31_nlo_as_0118_luxqed"
FAKE_MG = r'''
import gzip, os, re, sys
from pathlib import Path
lines = Path(sys.argv[1]).read_text().splitlines()
defaults = {"lpp1": "1", "lpp2": "1"}
model, defines, generate, proc = None, [], None, None
launches = []
for line in lines:
    if line.startswith("import model "): model = line
    elif line.startswith("define "): defines.append(line)
    elif line.startswith("generate "): generate = line
    elif line.startswith("output "): proc = Path(line.split()[1])
    elif line.startswith("launch "):
        m = re.search(r"--name=(\S+)", line)
        launches.append({"name": m.group(1) if m else "run_01", "settings": dict(defaults), "card": None, "overrides": []})
    elif launches and line.startswith("/"):
        launches[-1]["card"] = Path(line).read_text()
    elif launches and line.startswith("set "):
        parts = line.split()
        if parts[1] in ("mass", "decay") or parts[1].isupper():
            launches[-1]["overrides"].append(parts[1:])
        else:
            launches[-1]["settings"][parts[1]] = parts[2]
if os.environ.get("FAKE_MG_LPP2_ZERO"):
    for run in launches: run["settings"]["lpp2"] = "0"
def card(text, overrides):
    rows, block, out = text.splitlines(), None, []
    values = {}
    for name, *rest in overrides:
        values[(name.upper(), rest[0])] = rest[-1]
    for row in rows:
        f = row.split()
        if f and f[0].upper() == "BLOCK": block = f[1].upper(); out.append(row); continue
        if f and f[0].upper() == "DECAY":
            key = ("DECAY", f[1])
            if key in values:
                v = values[key]
                row = f"DECAY {f[1]} " + ("4.07e-03" if v.lower() == "auto" else v)
                if v.lower() == "auto": row += "\n  1.0 2 5 -5"
            out.append(row); continue
        if f and block and (block, f[0]) in values:
            row = f"  {f[0]} {values[(block, f[0])]}"
        out.append(row)
    return "\n".join(out)
for run in launches:
    s = run["settings"]
    n = int(s["nevents"])
    mass = 125.0
    for name, *rest in run["overrides"]:
        if name.upper() == "MASS" and rest[0] == "25": mass = float(rest[-1])
    xs = 1.0e3 / mass
    idb2 = "2212" if s["lpp2"] == "1" else "0"
    run_card = "\n".join(f"{v}={k}" for k, v in s.items())
    proc_card = "\n".join([model, *defines, generate])
    slha = card(run["card"] or "BLOCK MASS\n  25 125\nDECAY 25 4.07e-03\n", run["overrides"])
    pdfid = s.get("lhaid", "0")
    head = (f'<LesHouchesEvents version="3.0">\n<header>\n<MGRunCard>\n{run_card}\n</MGRunCard>\n'
            f'<MG5ProcCard>\n{proc_card.replace(">", "&gt;")}\n</MG5ProcCard>\n<slha>\n{slha}\n</slha>\n</header>\n'
            f'<init>\n2212 {idb2} {s["ebeam1"]} {s["ebeam2"]} 0 0 {pdfid} {pdfid} -4 1\n{xs} {xs * 0.01} {xs} 1\n</init>\n')
    px = (350.0 ** 2 - 50.0 ** 2) ** .5
    event = (f"<event>\n4 1 {xs} 1.0e+03 7.5e-03 1.1e-01\n"
             "-11 -1 0 0 0 0 0 0 +4.0e+02 4.0e+02 0.0 0 9\n"
             "2 -1 0 0 501 0 0 0 -3.0e+02 3.0e+02 0.0 0 9\n"
             f"-11 1 1 2 0 0 {px!r} 0 +5.0e+01 3.5e+02 0.0 0 9\n"
             f"2 1 1 2 501 0 -{px!r} 0 +5.0e+01 3.5e+02 0.0 0 9\n</event>\n")
    target = proc / "Events" / run["name"]
    target.mkdir(parents=True, exist_ok=True)
    with gzip.open(target / "unweighted_events.lhe.gz", "wt") as f:
        f.write(head + event * n + "</LesHouchesEvents>\n")
    print(f"  Cross-section :   {xs} +- {xs * 0.01} pb")
'''


def native(tmp_path, version="3.7.0"):
    root = tmp_path / f"mg-{version}"
    if root.exists():
        return {"madgraph": str(root), "python": sys.executable, "compiler": str(tmp_path / "gfortran"),
                "lhapdf_config": str(tmp_path / "lhapdf-config")}
    (root / "bin").mkdir(parents=True)
    (root / "bin/mg5_aMC").write_text(FAKE_MG)
    (root / "VERSION").write_text(f"version = {version}\ndate = fixture\n")
    (root / "models/sm").mkdir(parents=True)
    (root / "models/sm/particles.py").write_text("# fixture\n")
    data = tmp_path / "lhapdf-data"
    if not data.exists():
        for name, flavours in ((LUX, "[-15, -13, -11, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 11, 13, 15, 21, 22]"),
                               ("NNPDF30_nlo_as_0118", "[-5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 21]")):
            (data / name).mkdir(parents=True)
            (data / name / f"{name}.info").write_text(f"SetDesc: fixture\nFlavors: {flavours}\n")
        (data / "pdfsets.index").write_text(f"82400 {LUX} 1\n260000 NNPDF30_nlo_as_0118 1\n")
        config = tmp_path / "lhapdf-config"
        config.write_text(f"#!/bin/sh\necho {data}\n")
        config.chmod(0o755)
    compiler = tmp_path / "gfortran"
    compiler.write_text("# fixture compiler; never executed\n")
    return {"madgraph": str(root), "python": sys.executable, "compiler": str(compiler),
            "lhapdf_config": str(tmp_path / "lhapdf-config")}


def lepton_spec(runtime, **extra):
    g = {"runtime": runtime, "model": "sm", "definitions": {}, "process": "e+ u > e+ u", "events": 3, "seed": 11,
         "beam_pdg": [2212, 2212],
         "run_settings": {"ebeam1": 6500, "ebeam2": 6500, "lpp1": 1, "lpp2": 1, "pdlabel": "lhapdf", "lhaid": 82400,
                          "fixed_ren_scale": False, "fixed_fac_scale": False, "dynamical_scale_choice": 4,
                          "scalefact": 1},
         "cross_section_only": True}
    g.update(extra)
    return {"schema_version": 1, "mode": "generate", "source": "lepton-quark control",
            "assumptions": ["LO, lepton PDF of the proton"], "max_seconds": 600, "approval_mode": "scripted_yes",
            "generation": g}


def fresh_run(tmp_path, name="run"):
    rd = tmp_path / name
    assert main(["initiate", "--prompt", "Generate a generation-only parton control.", "--out", str(rd)]) == 0
    return rd


def plan(tmp_path, spec, name="run"):
    rd = fresh_run(tmp_path, name)
    atomic_json(tmp_path / f"{name}.json", spec)
    proposal = scoped.plan(rd, tmp_path / f"{name}.json")
    from method_decision_fixture import admit_method
    admit_method(rd, "new_events")
    return rd, proposal


def execute(rd):
    """Run the worker body directly (the supervisor and approval are tested elsewhere)."""
    (rd / "outputs").mkdir()
    return worker.generate(rd, read_json(rd / "inputs/scoped.json"))


def test_luxlep_lepton_partons_admitted_under_madgraph_3(tmp_path):
    rd, proposal = plan(tmp_path, lepton_spec(native(tmp_path)))
    assert proposal["beam_content"]["lepton_or_photon_partons"] == [-11]
    assert proposal["pdf"]["name"] == LUX and 11 in proposal["pdf"]["flavours"]
    checkin = read_json(rd / "inputs/checkin1.json")
    assert checkin["sections"]["i-b"]["beam_content"]["minimum_generator_version"] == "3.0.0"
    assert "Lepton or photon partons" in (rd / "CHECKIN1.md").read_text()


def test_same_plan_refused_with_nnpdf30_and_with_madgraph_2(tmp_path):
    spec = lepton_spec(native(tmp_path))
    spec["generation"]["run_settings"]["lhaid"] = 260000
    with pytest.raises(ValueError, match=r"does not carry partons \[-11\]"):
        plan(tmp_path, spec, "nnpdf")
    with pytest.raises(ValueError, match="MadGraph 3.0.0 or later"):
        plan(tmp_path, lepton_spec(native(tmp_path, "2.9.27")), "mg2")


def test_declared_proton_beam_with_lpp_zero_is_refused():
    spec = lepton_spec({"madgraph": "/x", "python": "/x", "compiler": "/x", "lhapdf_config": "/x"})
    spec["generation"]["run_settings"]["lpp2"] = 0
    assert any("lpp2=0" in e for e in scoped_spec.validate(spec))


def test_madgraph_default_lpp2_zero_fails_readback(tmp_path, monkeypatch):
    rd, _ = plan(tmp_path, lepton_spec(native(tmp_path)))
    monkeypatch.setenv("FAKE_MG_LPP2_ZERO", "1")
    with pytest.raises(ValueError, match="lpp2"):
        execute(rd)


def test_cross_section_only_batch_records_sigma_per_point(tmp_path):
    card = tmp_path / "param_card.dat"
    card.write_text("BLOCK MASS\n  23 91.188\n  25 125.0\nDECAY 23 2.44\nDECAY 25 4.07e-03\n")
    points = [{"id": f"m{m}", "overrides": [{"block": "MASS", "code": [25], "value": float(m)},
                                            {"block": "DECAY", "code": [25], "value": "Auto"}]} for m in (100, 200, 400)]
    spec = lepton_spec(native(tmp_path), parameter_card=str(card), parameter_points=points)
    rd, proposal = plan(tmp_path, spec)
    assert set(proposal["spec_reconciliation"]) == {"m100", "m200", "m400"}
    assert read_json(rd / "inputs/cost_preflight.json")["points"] == 3
    execute(rd)
    commands = (rd / "outputs/commands.mg5").read_text()
    assert "--name=point_m200" in commands and "set mass 25 200.0" in commands and "set decay 25 Auto" in commands
    result = read_json(rd / "outputs/result.json")
    assert [p["id"] for p in result["points"]] == ["m100", "m200", "m400"]
    assert [p["seed"] for p in result["points"]] == [11, 12, 13]
    assert result["points"][1]["cross_section_pb"] == pytest.approx(5.0)
    assert result["points"][1]["integration_error_pb"] == pytest.approx(0.05)
    receipt = read_json(rd / "outputs/generation-receipt.json")
    assert not generation_receipt.validate(receipt)
    assert receipt["cross_section_only"] and receipt["generator"]["version"] == "3.7.0"
    assert [p["cross_section"]["value_pb"] for p in receipt["points"]] == pytest.approx([10.0, 5.0, 2.5])
    assert receipt["points"][0]["cross_section"]["source"].startswith("LHE <init>")
    assert not generation_receipt.check_files(receipt, rd / "outputs")
    assert read_json(rd / "outputs/figure.json")["points"] == ["m100", "m200", "m400"]


def test_mass_scan_without_a_width_declaration_is_refused(tmp_path):
    card = tmp_path / "param_card.dat"
    card.write_text("BLOCK MASS\n  25 125.0\nDECAY 25 4.07e-03\n")
    points = [{"id": "m300", "overrides": [{"block": "MASS", "code": [25], "value": 300.0}]}]
    with pytest.raises(ValueError, match="declare Auto or the fixed width"):
        plan(tmp_path, lepton_spec(native(tmp_path), parameter_card=str(card), parameter_points=points))


def test_override_must_reach_the_executed_card(tmp_path):
    header = {"slha": "BLOCK MASS\n  25 125.0\n"}
    with pytest.raises(ValueError, match="did not reach"):
        worker.overrides_reached(header, [{"block": "MASS", "code": [25], "value": 300.0}])
    worker.overrides_reached(header, [{"block": "MASS", "code": [25], "value": 125.0}])


def test_physics_intent_mismatch_refuses_the_plan(tmp_path):
    spec = lepton_spec(native(tmp_path), physics_intent={"pdf": {"lhaid": 260000}})
    with pytest.raises(ValueError, match="PDF set"):
        plan(tmp_path, spec)


def test_lhe_transform_runs_before_delivery_and_is_recorded(tmp_path):
    rules = Path(worker.__file__).resolve().parents[1] / "data/lhe_transforms/lepton-to-photon-proxy.json"
    spec = lepton_spec(native(tmp_path), lhe_transform=str(rules))
    del spec["generation"]["cross_section_only"]
    spec["generation"]["observables"] = [{"id": "pt_e", "kind": "pt", "pdg": [-11], "combine": "leading", "count": 1,
                                          "bin_edges": [0, 200, 400], "normalization": "events"}]
    rd, proposal = plan(tmp_path, spec)
    assert proposal["lhe_transform"]["required_downstream_settings"] == ["Check:event = off"]
    assert "lepton-to-photon-proxy" in (rd / "DEVIATIONS.md").read_text()
    assert "Check:event = off" in (rd / "CHECKIN1.md").read_text()
    execute(rd)
    receipt = read_json(rd / "outputs/generation-receipt.json")
    assert receipt["transform"]["required_downstream_settings"] == ["Check:event = off"]
    assert receipt["transform"]["points"]["single"]["census"] == {"incoming-leptons": {"-11->22": 3}}
    assert (rd / "outputs/events.transformed.lhe.gz").is_file()
    assert read_json(rd / "outputs/result.json")["recipe"]["lhe_transform"]["rules_sha256"]


def test_shower_without_the_required_setting_is_refused(tmp_path, monkeypatch):
    from ravel.physics import scoped_shower
    monkeypatch.setattr(scoped_shower, "probe", lambda p: [])
    rules = Path(worker.__file__).resolve().parents[1] / "data/lhe_transforms/lepton-to-photon-proxy.json"
    spec = lepton_spec(native(tmp_path), lhe_transform=str(rules))
    del spec["generation"]["cross_section_only"]
    spec["generation"]["observables"] = [{"id": "pt_e", "kind": "pt", "pdg": [-11], "combine": "leading", "count": 1,
                                          "bin_edges": [0, 200, 400], "normalization": "events"}]
    spec["generation"]["shower"] = {"engine": "pythia8", "python": sys.executable, "seed": 3,
                                    "settings": ["PartonLevel:MPI = off"]}
    with pytest.raises(ValueError, match="Check:event = off"):
        plan(tmp_path, spec)


def qualified_ufo(tmp_path, *, reviewed=True):
    from ravel.physics import model_derivation_bridge as bridge
    from ravel.physics import model_tool_bridge as custody
    out = tmp_path / "derivation"
    ufo = out / "lq_model"
    ufo.mkdir(parents=True)
    for name in bridge.REQUIRED_UFO:
        (ufo / name).write_text(f"# {name}\n")
    manifest = out / "ufo-manifest.json"
    manifest.write_text(json.dumps(custody.source_tree(ufo)))
    attempt = out / "record.json"
    attempt.write_text("{}\n")
    doc = {"ufo": str(ufo), "ufo_manifest": {"path": str(manifest), "sha256": custody._hash(manifest)},
           "qualified_for_scoped_reuse": reviewed, "execution_authority_granted": False,
           "successful_derivation_attempt": {"id": "a1", "path": str(attempt), "sha256": custody._hash(attempt)},
           "accepted_review": {"cycle_id": "c1", "claim_scope": "model_source_derivation", "attestation": "fixture"}}
    path = out / "qualified-ufo.json"
    path.write_text(json.dumps(doc))
    return path, ufo


def test_reviewed_derived_ufo_is_generated_without_touching_the_toolchain(tmp_path):
    handoff, ufo = qualified_ufo(tmp_path)
    runtime = native(tmp_path)
    spec = lepton_spec(runtime, model="lq_model", model_origin=str(handoff))
    rd, proposal = plan(tmp_path, spec)
    assert proposal["model_origin"]["kind"] == "qualified_ufo"
    assert (rd / "inputs/madgraph/models/lq_model/particles.py").is_file()
    assert not (Path(runtime["madgraph"]) / "models/lq_model").exists()
    execute(rd)
    receipt = read_json(rd / "outputs/generation-receipt.json")
    assert receipt["model"]["origin"]["kind"] == "qualified_ufo"


def test_unreviewed_or_changed_ufo_is_refused(tmp_path):
    handoff, ufo = qualified_ufo(tmp_path, reviewed=False)
    with pytest.raises(ValueError, match="not a qualified UFO handoff"):
        plan(tmp_path, lepton_spec(native(tmp_path), model="lq_model", model_origin=str(handoff)), "unreviewed")
    handoff, ufo = qualified_ufo(tmp_path / "second")
    (ufo / "couplings.py").write_text("# edited after review\n")
    with pytest.raises(ValueError, match="changed since review"):
        plan(tmp_path, lepton_spec(native(tmp_path), model="lq_model", model_origin=str(handoff)), "edited")
    with pytest.raises(ValueError, match="reviewed model_origin"):
        plan(tmp_path, lepton_spec(native(tmp_path), model="lq_model"), "absent")


def test_generator_version_auto_selects_madgraph_3_for_lepton_partons(tmp_path, monkeypatch):
    from ravel.physics import generator_versions
    two, three = native(tmp_path, "2.9.27"), native(tmp_path, "3.7.0")
    entries = [{"version": "2.9.27", "tree": two["madgraph"], "python": two["python"], "compiler": two["compiler"],
                "lhapdf_config": two["lhapdf_config"], "installed": True, "source_commit": "a" * 40},
               {"version": "3.7.0", "tree": three["madgraph"], "python": three["python"], "compiler": three["compiler"],
                "lhapdf_config": three["lhapdf_config"], "installed": True, "source_commit": "b" * 40}]
    monkeypatch.setattr(generator_versions, "installed_madgraph", lambda prefix=None, **k: entries)
    spec = lepton_spec(None)
    del spec["generation"]["runtime"]
    spec["generation"]["generator"] = {"name": "madgraph", "version": "auto"}
    rd, proposal = plan(tmp_path, spec)
    assert proposal["generator_selection"]["selected"] == "3.7.0"
    assert "MadGraph 3.7.0" in (rd / "CHECKIN1.md").read_text()
    sm = deepcopy(spec)
    sm["generation"]["process"] = "u u~ > e+ e-"
    sm["generation"]["run_settings"].update(pdlabel="nn23lo1", lhaid=247000)
    _, proposal = plan(tmp_path, sm, "sm")
    assert proposal["generator_selection"]["selected"] == "2.9.27"
