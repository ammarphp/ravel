"""Controls reach actual native cards; card custody never claims tool consumption."""
import copy
import json
from pathlib import Path

import pytest

from ravel.physics import native_effective_config as effective
from ravel.physics import native_pipeline as pipeline
from ravel.physics import prepare_native_slepton as preparation
from test_native_dispatch import configuration, approve_fixture


INTERFACE_CARD = """Main:numberOfEvents = -1
HEPMCoutput:file = auto
JetMatching:qCut = -1.0
JetMatching:nJetMax = -1
JetMatching:doShowerKt = off
Merging:TMS = -1.0
Merging:Process = <set_by_user>
Merging:nJetMax = -1
SysCalc:fullCutVariation = off
!partonlevel:mpi = off
"""


def slepton_configuration(root, monkeypatch, *, extra="", mpi="off"):
    from analysis_package_fixtures import native_package
    native_package(root/'packages'/'renderer', 'FictionalRoutine701', ['selected'], models=['slepton-bino'],
                   statistics=['yields'], preparations=['slepton-bino', 'explicit-cards'])
    cards = root/"cards"; cards.mkdir(parents=True)
    (cards/"param.slha").write_text("Block MASS\n" + "".join(f" {p} {{{{MSLEP}}}}\n" for p in
        (1000011, 2000011, 1000013, 2000013, 1000015, 2000015)) + " 1000022 {{MN1}}\n")
    (cards/"run.dat").write_text("0 = nevents\n0 = iseed\n6500 = ebeam1\n6500 = ebeam2\n"
        "0 = ickkw\ncteq6l1 = pdlabel\n0 = lhaid\nFalse = use_syst\n0 = ptj1min\n20 = ptj\n-1 = ktdurham\n-1 = xqcut\n")
    (cards/"pythia.dat").write_text(INTERFACE_CARD)
    (cards/"isrslep").write_text("import model MSSM_SLHA2\ndefine produced = el- el+ er- er+ mul- mul+ mur- mur+ ta1- ta1+ ta2- ta2+\ngenerate p p > produced produced j\n")
    (cards/"launch.txt").write_text("{{PROCESS}}\noutput PROC_madgraph\nlaunch PROC_madgraph\nmadspin=OFF\nshower=OFF\nreweight=OFF\ndone\n{{PARAM_CARD}}\n{{RUN_CARD}}\ndone\n")
    (cards/"detector.tcl").write_text("# synthetic detector fixture, not physics evidence\n")
    path = root/"config.toml"
    path.write_text(f'''[base]
pythia_path = "{{{{PWD}}}}/cards"
run_path = "{{{{PWD}}}}/cards"
param_path = "{{{{PWD}}}}/cards"
process_path = "{{{{PWD}}}}/cards"
[madgraph]
params = "SleptonBino"
version = "madgraph:2.9.3"
paramcard = "param.slha"
[madgraph.proc]
name = "isrslep"
card = "{{{{madgraph['proc']['name']}}}}"
[madgraph.masses]
MSLEP = 150
MN1 = 140
[madgraph.run]
card = "run.dat"
nevents = 100
seed = 3
ecms = 13000
[madgraph.run.options]
ptj1min = 50
ptj = 20
ktdurham = -1
xqcut = -1
[pythia]
card = "pythia.dat"
mpi = "{mpi}"
additional_opts = {json.dumps(extra)}
[analysis]
script = "Delphes2SA.py"
lumi = 139000
kfactor = 1.18
[simpleanalysis]
name = "FictionalRoutine701"
[ravel.native]
model = "slepton-bino"
preparation = "slepton-bino"
detector = "simpleanalysis-delphes"
statistics = "yields"
analysis_package = "packages/renderer/manifest.json"
pdf = "cteq6l1"
[ravel.native.rendering]
schema_version = 1
parameters = {{parent = 150, child = 140}}
bindings = [{{parameter = "parent", placeholder = "MSLEP"}}, {{parameter = "child", placeholder = "MN1"}}]
run_controls = {{pdlabel = "cteq6l1", ickkw = 0, use_syst = false}}
expected_masses = {{"1000011" = 150, "2000011" = 150, "1000013" = 150, "2000013" = 150, "1000015" = 150, "2000015" = 150, "1000022" = 140}}
[ravel.native.inputs]
delphes_card = "cards/detector.tcl"
param_template = "cards/param.slha"
run_template = "cards/run.dat"
process_card = "cards/isrslep"
launch_template = "cards/launch.txt"
pythia_card = "cards/pythia.dat"
''')
    monkeypatch.setattr(pipeline, "native_build_root", lambda: root/"native-build")
    return path


def prepared(root, monkeypatch, **kwargs):
    plan = pipeline.build_execution_plan(root, slepton_configuration(root, monkeypatch, **kwargs))
    pipeline.write_plan(plan)
    pipeline.prepare(plan)
    return plan


def test_lost_mpi_and_additional_options_reach_actual_shower_card(tmp_path, monkeypatch):
    plan = prepared(tmp_path, monkeypatch, extra="TimeShower:alphaSvalue = 0.12\nRandom:setSeed = on\nRandom:seed = 17")
    card = effective.assignments((tmp_path/"output/shower.cfg").read_text())
    assert card["PartonLevel:MPI"] == "off"
    assert card["TimeShower:alphaSvalue"] == "0.12"
    assert card["Random:seed"] == "17"
    assert card["Main:numberOfEvents"] == "100"
    assert all(key.lower() not in effective.INTERFACE_SENTINELS for key in card)
    record = json.loads((tmp_path/effective.MANIFEST).read_text())
    assert record["effective"]["generation"]["ptj1min"] == "50"
    assert record["requested_controls"]["statistics"]["kfactor"] == 1.18
    assert record["requested_controls"]["tool_version_labels"]["madgraph"]["declared"] == "madgraph:2.9.3"
    assert "unverified" in record["requested_controls"]["tool_version_labels"]["madgraph"]["disposition"]
    assert effective.validate(plan) == []
    assert effective.runtime_evidence(plan)["status"] == "unverified"
    assert all(item["status"] == "unverified" for item in effective.runtime_evidence(plan)["stages"])
    manifest = str(tmp_path/effective.MANIFEST)
    assert manifest in plan["stages"][0]["outputs"]
    assert all(manifest in item["inputs"] for item in plan["stages"][1:])
    assert any(source["path"].endswith("native_effective_config.py") for source in plan["sources"])
    assert record["stage_bindings"]["pythia"]["command"] == next(x["command"] for x in plan["stages"] if x["stage"] == "pythia")


def test_explicit_mpi_override_is_recorded(tmp_path):
    source = tmp_path/"pythia.dat"; source.write_text("partonlevel:mpi = on\n")
    text, translation = effective.translate_shower({"pythia": {"mpi": "off"}}, source, lhe="events.lhe", nevents=2)
    assert "PartonLevel:MPI = off" in text
    assert any(item["disposition"] == "explicit_mpi_override" for item in translation["dispositions"])


def test_tune_precedes_explicit_settings_and_seed_activation_required(tmp_path):
    source = tmp_path/"card.dat"; source.write_text(INTERFACE_CARD)
    text, _ = effective.translate_shower({"pythia": {"additional_opts": "TimeShower:alphaSvalue = 0.12"}},
                                         source, lhe="events.lhe", nevents=2)
    assert text.index("Tune:pp =") < text.index("TimeShower:alphaSvalue =")
    with pytest.raises(ValueError, match="otherwise Pythia ignores"):
        effective.translate_shower({"pythia": {"additional_opts": "Random:seed = 17"}}, source, lhe="events.lhe", nevents=2)


@pytest.mark.parametrize("setting", ["PartonLevel:MPI = perhaps", "TimeShower:alphaSvalue = text", "Random:seed = 1.5",
                                     "Random:seed = 900000001", "PDF:useLHAPDF = on"])
def test_invalid_or_obsolete_typed_setting_is_refused(tmp_path, setting):
    source = tmp_path/"card.dat"; source.write_text(setting+"\n")
    with pytest.raises(ValueError): effective.translate_shower({}, source, lhe="events.lhe", nevents=2)


@pytest.mark.parametrize("extra", ["PartonLevel:MPI = on", "Beams:frameType = 1", "Main:numberOfEvents = 5"])
def test_override_conflicts_fail_before_preparation(tmp_path, monkeypatch, extra):
    config = slepton_configuration(tmp_path, monkeypatch, extra=extra)
    with pytest.raises(ValueError, match="conflict"):
        pipeline.build_execution_plan(tmp_path, config)
    assert not (tmp_path/"output").exists()


def test_card_and_additional_option_conflict_requires_source_copy(tmp_path, monkeypatch):
    config = slepton_configuration(tmp_path, monkeypatch, extra="Tune:pp = 14")
    source = tmp_path/"cards/pythia.dat"; source.write_text(source.read_text()+"Tune:pp = 21\n")
    with pytest.raises(ValueError, match="source card"):
        pipeline.build_execution_plan(tmp_path, config)


@pytest.mark.parametrize("setting", ["Merging:TMS = 30", "HEPMCoutput:file = /dev/null", "Unsupported:knob = on",
                                     "Random:seed = nan", "not a Pythia assignment"])
def test_unsupported_controls_fail_loudly(tmp_path, setting):
    source = tmp_path/"card.dat"; source.write_text(setting+"\n")
    with pytest.raises(ValueError): effective.translate_shower({}, source, lhe="events.lhe", nevents=2)


def test_unknown_toml_control_is_not_silently_ignored(tmp_path, monkeypatch):
    config = slepton_configuration(tmp_path, monkeypatch)
    config.write_text(config.read_text().replace('mpi = "off"', 'mpi = "off"\noptions = "silent-loss"'))
    with pytest.raises(ValueError, match="unsupported native"):
        pipeline.build_execution_plan(tmp_path, config)


def test_matching_requested_through_run_options_is_refused(tmp_path, monkeypatch):
    config = slepton_configuration(tmp_path, monkeypatch)
    config.write_text(config.read_text().replace("ktdurham = -1", "ktdurham = 30"))
    with pytest.raises(ValueError, match="matching/merging"):
        pipeline.build_execution_plan(tmp_path, config)


def test_named_template_paths_and_missing_or_unresolved_paths(tmp_path):
    share = tmp_path/"share"; (share/"cards/pythia").mkdir(parents=True)
    source = share/"cards/pythia/custom.dat"; source.write_text("PartonLevel:MPI = off\n")
    cfg = {"base": {"pythia_path": "{{ MAPYDE_CARDS }}/pythia"}, "pythia": {"card": "custom.dat"},
           "madgraph": {"params": "SleptonBino", "proc": {"name": "isrslep"}}}
    assert effective.configured_card(cfg, "pythia", rundir=tmp_path, share=share) == source
    assert effective.resolve_path("{{madgraph['params']}}.slha", rundir=tmp_path, share=share, cfg=cfg) == tmp_path/"SleptonBino.slha"
    assert effective.resolve_path("{{madgraph['proc']['name']}}", rundir=tmp_path, share=share, cfg=cfg) == tmp_path/"isrslep"
    cfg["pythia"]["card"] = "missing.dat"
    with pytest.raises(ValueError, match="missing or empty"): effective.configured_card(cfg, "pythia", rundir=tmp_path, share=share)
    with pytest.raises(ValueError, match="unsupported/unresolved"):
        effective.resolve_path("{{ dangerous() }}", rundir=tmp_path, share=share, cfg=cfg)


def test_custom_run_card_selection_is_not_ignored(tmp_path, monkeypatch):
    config = slepton_configuration(tmp_path, monkeypatch)
    custom = tmp_path/"cards/custom.dat"
    custom.write_text((tmp_path/"cards/run.dat").read_text()+"1.5 = custom_cut\n")
    config.write_text(config.read_text().replace('cards/run.dat', 'cards/custom.dat').replace('card = "run.dat"', 'card = "custom.dat"'))
    plan = pipeline.build_execution_plan(tmp_path, config)
    assert plan["inputs"]["run_template"] == str(custom)
    assert "1.5 = custom_cut" in plan["rendered"]["run_card.dat"]


def test_configured_process_path_is_verified_and_never_silently_replaced(tmp_path, monkeypatch):
    config = slepton_configuration(tmp_path, monkeypatch)
    plan = pipeline.build_execution_plan(tmp_path, config)
    assert any(source["path"] == str(tmp_path/"cards/isrslep") for source in plan["sources"])
    assert "authoritative" in plan["effective_controls"]["process"]["disposition"]
    path = tmp_path/"cards/isrslep"; path.write_text(path.read_text()+"set iseed 9\n")
    with pytest.raises(ValueError, match="conflicts with supplied generation"):
        pipeline.build_execution_plan(tmp_path, config)


def test_inherited_template_is_refused_until_resolved(tmp_path, monkeypatch):
    config = slepton_configuration(tmp_path, monkeypatch)
    config.write_text(config.read_text().replace("[base]", '[base]\ntemplate = "upstream.toml"'))
    with pytest.raises(ValueError, match="resolved TOML"):
        pipeline.build_execution_plan(tmp_path, config)


@pytest.mark.parametrize("card, change", [("run_card.dat", lambda s: s.replace("cteq6l1", "nn23nlo")),
                                          ("shower.cfg", lambda s: s.replace("PartonLevel:MPI = off", "PartonLevel:MPI = on")),
                                          ("run.mg5", lambda s: s+"set iseed 99\n")])
def test_altered_prepared_card_invalidates_effective_settings(tmp_path, monkeypatch, card, change):
    plan = prepared(tmp_path, monkeypatch)
    path = tmp_path/"output"/card; path.write_text(change(path.read_text()))
    assert effective.validate(plan)
    with pytest.raises(ValueError, match="effective settings refused"):
        pipeline.verify_effective_settings(plan)


def test_manifest_tamper_cannot_relabel_actual_settings(tmp_path, monkeypatch):
    plan = prepared(tmp_path, monkeypatch)
    record = json.loads((tmp_path/effective.MANIFEST).read_text())
    record["effective"]["shower"]["PartonLevel:MPI"] = "on"
    assert effective.validate(plan, record)


def test_source_card_drift_invalidates_manifest(tmp_path, monkeypatch):
    plan = prepared(tmp_path, monkeypatch)
    path = tmp_path/"cards/pythia.dat"; path.write_text(path.read_text()+"! altered source\n")
    assert "source changed" in effective.validate(plan)[0]


@pytest.mark.parametrize("resume", [True, False])
def test_validation_precedes_next_stage_or_reuse(tmp_path, monkeypatch, resume):
    plan = pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    pipeline.write_plan(plan)
    monkeypatch.setattr(pipeline, "verify_execution_approval", lambda plan: True)
    monkeypatch.setattr(pipeline.os, "access", lambda *args: True)
    plan["required_tools"] = []; plan["required_backend_files"] = []
    plan["plan_sha256"] = pipeline.plan_hash(plan); pipeline.write_plan(plan)
    calls = []
    def supervisor(stage, *args, **kwargs):
        calls.append(stage)
        pipeline.prepare(plan)
        path = tmp_path/"output/shower.cfg"; path.write_text(path.read_text()+"PartonLevel:MPI = off\n")
        return 0
    with pytest.raises(ValueError, match="effective settings refused"):
        pipeline.execute_plan(plan, supervisor=supervisor, resume=resume)
    assert calls == ["prepare"]


def test_receipt_evidence_allows_supervisor_expansion_and_rejects_command_drift(tmp_path, monkeypatch):
    plan = prepared(tmp_path, monkeypatch)
    from ravel.workflow import execution
    stages = {}
    for item in plan["stages"]:
        stages[item["stage"]] = {"command": item["command"], "inputs": [*item["inputs"], "/extra/supervisor/source.py"],
                                 "receipt_sha256": "fixture-only"}
    monkeypatch.setattr(execution, "load_execution", lambda _: {"stages": stages})
    monkeypatch.setattr(execution, "stage_errors", lambda *args: [])
    assert effective.runtime_evidence(plan)["status"] == "receipt_verified"
    stages["pythia"]["command"] = ["different"]
    result = effective.runtime_evidence(plan)
    assert result["status"] == "unverified"
    assert next(item for item in result["stages"] if item["stage"] == "pythia")["status"] == "invalid"


def test_standalone_preparation_uses_same_shower_translation(tmp_path):
    source = tmp_path/"card.dat"; source.write_text(INTERFACE_CARD)
    output = tmp_path/"shower.cfg"
    preparation.write_shower_cfg(str(tmp_path), output, cfg={"pythia": {"mpi": "off"}}, source=source, nevents=2)
    settings = effective.assignments(output.read_text())
    assert settings["PartonLevel:MPI"] == "off"
    assert settings["Beams:LHEF"].endswith("output/PROC_madgraph/Events/run_01/unweighted_events.lhe")


def test_explicit_cards_keep_bytes_and_reject_lost_overlay(tmp_path):
    config = configuration(tmp_path)
    shower = tmp_path/"cards/shower.cfg"
    shower.write_text(shower.read_text()+"PartonLevel:MPI = off ! keep this comment\n")
    config.write_text(config.read_text()+'\n[pythia]\nmpi = "off"\n')
    plan = pipeline.build_execution_plan(tmp_path, config)
    pipeline.prepare(plan)
    expected = shower.read_text().replace("Beams:LHEF = supplied-by-plan", f"Beams:LHEF = {tmp_path}/output/madgraph/unweighted_events.lhe")
    assert (tmp_path/"output/shower.cfg").read_text() == expected
    assert (tmp_path/"output/run_card.dat").read_bytes() == (tmp_path/"cards/run.dat").read_bytes()
    config.write_text(config.read_text().replace('mpi = "off"', 'mpi = "on"'))
    with pytest.raises(ValueError, match="explicit shower_card"): pipeline.build_execution_plan(tmp_path, config)


def test_explicit_pdf_declaration_and_run_option_cannot_be_dropped(tmp_path):
    config = configuration(tmp_path)
    config.write_text(config.read_text().replace('[ravel.native.inputs]', 'pdf = "nn23nlo"\n[ravel.native.inputs]'))
    with pytest.raises(ValueError, match="PDF|pdf"): pipeline.build_execution_plan(tmp_path, config)
    config.write_text(config.read_text().replace('pdf = "nn23nlo"', '')+'\n[madgraph.run.options]\nptj1min = 50\n')
    with pytest.raises(ValueError, match="requested generation control"): pipeline.build_execution_plan(tmp_path, config)


def test_historical_plan_inspection_does_not_claim_new_custody(tmp_path):
    plan = pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    old = copy.deepcopy(plan)
    for key in ("effective_settings", "shower_translation", "effective_controls"): old.pop(key)
    old["plan_sha256"] = pipeline.plan_hash(old)
    path = pipeline.write_plan(old)
    assert pipeline.plan_hash(pipeline.load_plan(path)) == pipeline.plan_hash(old)
    assert "historical plan" in effective.validate(old)[0]
    with pytest.raises(ValueError, match="historical plan"): pipeline.prepare(old)


def correction_fixture(root, monkeypatch, *, stage="pythia"):
    """Real CI1/envelope; mock independently tested review journal at its public boundary."""
    from ravel.workflow import physics_review as review, execution
    from test_native_dispatch import synthetic_build
    synthetic_build(root, monkeypatch)  # the approved plan names no host installation
    config = configuration(root)
    config.write_text(config.read_text().replace("nevents = 2", "nevents = 2000"))
    run = root/"cards/run.dat"; run.write_text(run.read_text().replace("2 = nevents", "2000 = nevents"))
    original = pipeline.build_execution_plan(root, config)
    approve_fixture(original)
    from ravel.workflow.workflow_state import verify_approval
    assert verify_approval(str(root), required_plan="full")  # no Check In 2 GO
    derivative = pipeline.correction_derivative(original, plan_path=root/"inputs/native_derivative.json")
    derivative["required_tools"] = []; derivative["required_backend_files"] = []
    derivative["plan_sha256"] = pipeline.plan_hash(derivative)
    pipeline.write_plan(derivative); pipeline.prepare(derivative)
    paths = [derivative["plan_path"], derivative["effective_settings"], *(source["path"] for source in derivative["sources"])]
    correction = {"correction_id": "synthetic-journal-boundary", "stages": [item["stage"] for item in derivative["stages"]],
        "snapshots": [{"path": path, "sha256": effective.fingerprint(path)["sha256"]} for path in paths],
        "effective_settings": [{"path": derivative["plan_path"]}, {"path": derivative["effective_settings"]}]}
    monkeypatch.setattr(review, "active", lambda _: True)
    # Preparation still inspects journal status; current amendment retrieval
    # and execution authority are distinct public calls, not interchangeable.
    monkeypatch.setattr(review, "status", lambda _: {"state":"correction_admitted"})
    # The native caller uses this authenticated current-amendment inspection
    # API, while launch-specific exact stage checks stay separate below.
    monkeypatch.setattr(review, "current_correction", lambda _: correction)
    observed = []
    def exact(root, name, command, inputs, outputs, dependencies, cwd, log=None):
        observed.append((name, command, inputs, outputs, dependencies, cwd))
        return [] if name in correction["stages"] else ["action is outside admitted correction"]
    monkeypatch.setattr(review, "correction_execution_errors", exact)
    def expanded(root, name, command, inputs, outputs, dependencies, cwd):
        return {"command":command,"inputs":[*inputs,"/supervisor/expanded.py"],"outputs":outputs,
                "parents":{},"input_snapshot":{"fixture":"expanded"},"cwd":cwd}
    monkeypatch.setattr(execution, "plan_stage", expanded)
    return derivative, correction, observed


def test_exact_native_correction_uses_unchanged_envelope_and_all_admitted_descendants(tmp_path, monkeypatch):
    plan, _, observed = correction_fixture(tmp_path, monkeypatch)
    assert pipeline.verify_execution_approval(plan) is True
    calls = []
    def supervisor(stage, *args, **kwargs):
        calls.append((stage, kwargs["resume"]))
        return 0
    assert pipeline.execute_plan(plan, supervisor=supervisor) == 0
    assert calls == [(item["stage"], False) for item in plan["stages"]]
    assert observed[0][0] == "prepare" and "/supervisor/expanded.py" in observed[0][2]
    with pytest.raises(ValueError, match="before admission"):
        pipeline.prepare(plan)
    with pytest.raises(ValueError, match="absent"):
        pipeline.verify_native_stage_authority(plan, "unregistered-stage")


def test_native_correction_cannot_drop_derivative_plan_or_manifest_binding(tmp_path, monkeypatch):
    plan, correction, _ = correction_fixture(tmp_path, monkeypatch)
    correction["effective_settings"] = correction["effective_settings"][:1]
    with pytest.raises(ValueError, match="explicitly bound"):
        pipeline.verify_execution_approval(plan)


def test_native_correction_cannot_widen_original_event_budget(tmp_path, monkeypatch):
    plan, correction, _ = correction_fixture(tmp_path, monkeypatch)
    plan["nevents"] = 2001; plan["plan_sha256"] = pipeline.plan_hash(plan)
    pipeline.write_plan(plan)
    # Skip card custody here to exercise the separately checked CI1 budget.
    monkeypatch.setattr(pipeline, "native_correction", lambda _: correction)
    with pytest.raises(ValueError, match="event budget"):
        pipeline.verify_execution_approval(plan)


@pytest.mark.parametrize("mutation", ["missing_stage", "missing_parent"])
def test_native_amendment_cannot_truncate_approved_graph(tmp_path, monkeypatch, mutation):
    plan, correction, _ = correction_fixture(tmp_path, monkeypatch)
    if mutation == "missing_stage":
        plan["stages"] = plan["stages"][:-1]
        correction["stages"] = [item["stage"] for item in plan["stages"]]
    else:
        plan["stages"][1]["depends_on"] = []
    plan["plan_sha256"] = pipeline.plan_hash(plan)
    with pytest.raises(ValueError, match="complete approved stage graph"):
        pipeline.native_correction(plan)


def test_native_derivative_updates_activated_generator_plan_reference(tmp_path):
    original = pipeline.build_execution_plan(tmp_path, configuration(tmp_path))
    original["generator_command"] = pipeline.module_command("ravel.physics.native_pipeline", "generate-activated", "--plan", original["plan_path"])
    path = tmp_path/"inputs/native_derivative.json"
    derivative = pipeline.correction_derivative(original, plan_path=path)
    assert derivative["generator_command"][-1] == str(path)
    with pytest.raises(ValueError, match="distinct derivative"):
        pipeline.correction_derivative(original, plan_path=tmp_path/"inputs/cost_preflight.json")


def test_direct_native_correction_generation_requires_running_exact_supervision(tmp_path, monkeypatch):
    plan, _, _ = correction_fixture(tmp_path, monkeypatch, stage="madgraph")
    from ravel.workflow import execution
    monkeypatch.setattr(execution, "load_execution", lambda _: {"stages": {}})
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **kw: pytest.fail("must refuse before generation"))
    with pytest.raises(ValueError, match="exact running supervised"):
        pipeline.generate(plan)
