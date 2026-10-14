"""Pure structural/adversarial controls, never a substitute for the real MG5 witness."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import pytest

from ravel.physics import model_probe as probe
from ravel.validation import model_probe_witness as witness


def points():
    return {"schema_version": 1, "energy_unit": "GeV", "component_order": ["E", "px", "py", "pz"],
            "leg_pdgs": [-11, 11, -13, 13], "points": [
                {"id": "transverse", "momenta": [[50, 0, 0, 50], [50, 0, 0, -50], [50, 50, 0, 0], [50, -50, 0, 0]]},
                {"id": "angled", "momenta": [[50, 0, 0, 50], [50, 0, 0, -50], [50, 40, 0, 30], [50, -40, 0, -30]]}]}


EXPECTED = {"aEWM1": 128.0, "Me": 0.0, "MM": 0.0}


def oracle():
    # These decimal fixtures were derived independently from e^4(1+cos^2(theta)).
    return {"schema_version": 1, "kind": "qed-massless-tree-spin-average",
            "source": "Independent massless QED spin trace, distinct color-singlet fermions, frozen before generator execution",
            "formula": "2*e^4*(t^2+u^2)/s^2; e^2=4*pi/alpha_inverse", "alpha_inverse": 128.0,
            "atol": 1e-12, "rtol": 1e-8,
            "expected_m2": {"transverse": 0.009638285547938826, "angled": 0.013108068345196804}}


def measured():
    refs = oracle()["expected_m2"]
    return {"parameters": {"aEWM1": 128.0, "ee": math.sqrt(math.pi / 32)}, "masses_gev": [0.0] * 4,
            "m2": {key: refs[p["id"]] for p in points()["points"]
                   for key in (p["id"], p["id"] + "__boost_z")}}


@pytest.fixture
def config(tmp_path):
    runtime = tmp_path / "mg5"
    for name, content in {"bin/mg5_aMC": "not executable by these pure tests\n", "VERSION": "version = 2.9.27\n",
                          "models/sm/parameters.py": "# structural fixture only\n", "models/sm/restrict_default.dat": "# fixture\n"}.items():
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for name in ("compiler", "make"):
        path = tmp_path / name
        path.write_text("#!/bin/sh\nexit 99\n")
        path.chmod(0o755)
    (tmp_path / "param.dat").write_text("Block SMINPUTS\n 1 128\nBlock MASS\n 11 0\n 13 0\nDECAY 23 2.0\n")
    for name, content in (("points.json", points()), ("oracle.json", oracle())):
        (tmp_path / name).write_text(json.dumps(content))
    return {"operation": probe.OPERATION,
            "runtime": {"madgraph": str(runtime), "python": str(Path(sys.executable).resolve()),
                        "compiler": str(tmp_path / "compiler"), "make": str(tmp_path / "make"), "artifacts": [], "environment": {}},
            "parameter_card": "param.dat", "phase_space_file": "points.json", "oracle_file": "oracle.json",
            "expected_parameters": dict(EXPECTED), "required_checks": list(witness.MANDATORY_CHECKS), "max_seconds": 60}


def test_exact_qed_oracle_and_parameter_scaling():
    for point in witness.validate_points(points()):
        actual = witness.qed_m2(point["momenta"], 128)
        assert actual == pytest.approx(oracle()["expected_m2"][point["id"]], rel=1e-14)
        assert witness.qed_m2(point["momenta"], 256) == pytest.approx(actual / 4, rel=1e-14)
        assert witness.qed_m2(witness.boost_z(point["momenta"]), 128) == pytest.approx(actual, rel=1e-14)


def test_exact_nine_generated_standalone_aliases_become_regular_bytes(tmp_path):
    work = tmp_path / "work"
    source = work / "PROC_probe/Source"
    sub = work / "PROC_probe/SubProcesses"
    (source / "MODEL").mkdir(parents=True)
    sub.mkdir()
    original = source / "MODEL/coupl.inc"
    original.write_text("C known generated data\n")
    original.chmod(0o640)
    (source / "coupl.inc").symlink_to("MODEL/coupl.inc")
    (sub / "coupl.inc").symlink_to("../Source/MODEL/coupl.inc")
    (sub / "check_sa.f").write_text("C already successfully evaluated driver\n")
    (sub / "makefileP").write_text("C generated makefile\n")
    specific = sub / "P1_epem_mupmum_no_zh"
    specific.mkdir()
    for name, target in {"coupl.inc": "../coupl.inc", "check_sa.f": "../check_sa.f", "makefile": "../makefileP"}.items():
        (specific / name).symlink_to(target)
    for name in ("lhe_event_infos", "run_config", "maxparticles", "run"):
        (sub / (name + ".inc")).symlink_to("../Source/" + name + ".inc")
    records = probe._materialize_aliases(work)
    assert len(records) == 9
    assert sum(row["action"] == "materialized_internal_file" for row in records) == 5
    assert sum(row["action"] == "removed_unused_standalone_placeholder" for row in records) == 4
    assert not any(path.is_symlink() for path in work.rglob("*"))
    for path in (source / "coupl.inc", sub / "coupl.inc", specific / "coupl.inc"):
        assert path.read_bytes() == original.read_bytes()
        assert path.stat().st_mode & 0o777 == 0o640
    assert all(row["source"]["sha256"] == row["materialized"]["sha256"]
               and row["source"]["mode"] == row["materialized"]["mode"] for row in records if "source" in row)


@pytest.mark.parametrize("defect", ["escape", "directory", "unknown_dangling", "wrong_placeholder", "cycle", "temporary_collision", "special_permissions"])
def test_generated_alias_defects_refuse_before_any_mutation(tmp_path, defect):
    work = tmp_path / "work"
    work.mkdir()
    data = work / "data.inc"
    data.write_text("unchanged\n")
    good = work / "a-good.inc"
    good.symlink_to("data.inc")
    bad = work / "z-bad.inc"
    if defect == "escape":
        outside = tmp_path / "outside.inc"
        outside.write_text("not private\n")
        bad.symlink_to(outside)
    elif defect == "directory":
        directory = work / "directory"
        directory.mkdir()
        bad.symlink_to(directory, target_is_directory=True)
    elif defect == "unknown_dangling":
        bad.symlink_to("missing.inc")
    elif defect == "wrong_placeholder":
        bad = work / "PROC_probe/SubProcesses/run.inc"
        bad.parent.mkdir(parents=True)
        bad.symlink_to("../Source/other.inc")
    elif defect == "temporary_collision":
        bad.symlink_to("data.inc")
        (work / "z-bad.inc.ravel-materialization").write_text("reserved\n")
    elif defect == "special_permissions":
        target = work / "special.inc"
        target.write_text("special\n")
        target.chmod(0o1644)
        bad.symlink_to("special.inc")
    else:
        bad.symlink_to(bad.name)
    with pytest.raises(ValueError):
        probe._materialize_aliases(work)
    assert good.is_symlink()
    assert bad.is_symlink()
    assert data.read_text() == "unchanged\n"


@pytest.mark.parametrize("scale", [2e-8, 1.0, 1e150])
def test_kinematic_validation_is_relative_to_physical_scale(scale):
    data = deepcopy(points())
    for point in data["points"]:
        point["momenta"] = [[component * scale for component in momentum] for momentum in point["momenta"]]
    checked = witness.validate_points(data)
    for point in checked:
        assert witness.qed_m2(point["momenta"], 128) == pytest.approx(oracle()["expected_m2"][point["id"]], rel=1e-14)
    invalid = deepcopy(data)
    invalid["points"][0]["momenta"][0][3] *= 2
    invalid["points"][0]["momenta"][1][3] *= 2
    with pytest.raises(ValueError, match="massless"):
        witness.validate_points(invalid)
    invalid = deepcopy(data)
    invalid["points"][0]["momenta"][2] = [component * 1.001 for component in invalid["points"][0]["momenta"][2]]
    with pytest.raises(ValueError, match="conservation"):
        witness.validate_points(invalid)


def test_tiny_amplitude_cannot_hide_behind_an_absolute_tolerance():
    expected = {**EXPECTED, "aEWM1": 1e9}
    data = oracle()
    data["alpha_inverse"] = expected["aEWM1"]
    data["expected_m2"] = {p["id"]: witness.qed_m2(p["momenta"], 1e9) for p in points()["points"]}
    data["atol"] = 1e-10
    with pytest.raises(ValueError, match="absolute tolerance"):
        witness.validate_oracle(data, points()["points"], expected)
    data["atol"] = 0
    witness.validate_oracle(data, points()["points"], expected)
    actual = {"parameters": {"aEWM1": 1e9, "ee": math.sqrt(4 * math.pi / 1e9)}, "masses_gev": [0.0] * 4,
              "m2": {key: data["expected_m2"][p["id"]] * 1000 for p in points()["points"]
                     for key in (p["id"], p["id"] + "__boost_z")}}
    result = witness.compare(points()["points"], data, expected, actual, witness.MANDATORY_CHECKS)
    assert result["checks_passed"] is False
    assert result["required_unresolved"] == ["amplitude_reference"]
    corrupted = deepcopy(data)
    corrupted["expected_m2"]["transverse"] *= 100
    with pytest.raises(ValueError, match="frozen reference"):
        witness.validate_oracle(corrupted, points()["points"], expected)


def test_relative_parameter_and_residual_checks_have_no_absolute_floor():
    expected = {**EXPECTED, "aEWM1": 1e50}
    data = oracle()
    data.update(alpha_inverse=1e50, atol=0)
    data["expected_m2"] = {p["id"]: witness.qed_m2(p["momenta"], 1e50) for p in points()["points"]}
    witness.validate_oracle(data, points()["points"], expected)
    actual = {"parameters": {"aEWM1": 1e50, "ee": 1e-14}, "masses_gev": [0.0] * 4,
              "m2": {key: data["expected_m2"][p["id"]] for p in points()["points"]
                     for key in (p["id"], p["id"] + "__boost_z")}}
    result = witness.compare(points()["points"], data, expected, actual, witness.MANDATORY_CHECKS)
    assert result["required_unresolved"] == ["effective_parameters"]
    assert witness.relative_delta(1e300, 1e-300) is None


@pytest.mark.parametrize("alpha_inverse", [1e-200, 1e200])
def test_unrepresentable_analytic_amplitudes_are_refused(alpha_inverse):
    with pytest.raises(ValueError, match="representable analytic"):
        witness.qed_m2(points()["points"][0]["momenta"], alpha_inverse)


@pytest.mark.parametrize("defect", ["version_bool", "version_float", "units", "order", "legs", "negative_energy", "mass", "conservation", "duplicate", "one_angle", "nan", "bool"])
def test_invalid_phase_space_is_refused(defect):
    data = deepcopy(points())
    if defect == "version_bool": data["schema_version"] = True
    elif defect == "version_float": data["schema_version"] = 1.0
    elif defect == "units": data["energy_unit"] = "MeV"
    elif defect == "order": data["component_order"] = ["px", "py", "pz", "E"]
    elif defect == "legs": data["leg_pdgs"][0] = 11
    elif defect == "negative_energy": data["points"][0]["momenta"][0][0] = -50
    elif defect == "mass": data["points"][0]["momenta"][0][0] = 51
    elif defect == "conservation": data["points"][0]["momenta"][2] = [50, 0, 50, 0]
    elif defect == "duplicate": data["points"][1]["id"] = "transverse"
    elif defect == "one_angle": data["points"][1]["momenta"] = deepcopy(data["points"][0]["momenta"])
    elif defect == "nan": data["points"][0]["momenta"][0][0] = float("nan")
    elif defect == "bool": data["points"][0]["momenta"][0][0] = True
    with pytest.raises(ValueError): witness.validate_points(data)


@pytest.mark.parametrize("defect", ["version_bool", "version_float", "wrong_reference", "missing_point", "coupling", "wide_tolerance", "no_source", "wrong_spin_average"])
def test_oracle_defects_are_refused(defect):
    data = oracle()
    if defect == "version_bool": data["schema_version"] = True
    elif defect == "version_float": data["schema_version"] = 1.0
    elif defect == "wrong_reference": data["expected_m2"]["transverse"] *= 4
    elif defect == "missing_point": del data["expected_m2"]["angled"]
    elif defect == "coupling": data["alpha_inverse"] = 256
    elif defect == "wide_tolerance": data["rtol"] = 0.1
    elif defect == "no_source": data["source"] = ""
    elif defect == "wrong_spin_average": data["kind"] = "helicity-sum"
    with pytest.raises(ValueError): witness.validate_oracle(data, points()["points"], EXPECTED)


def test_required_unsupported_or_inapplicable_check_never_passes():
    base = witness.compare(points()["points"], oracle(), EXPECTED, measured(), witness.MANDATORY_CHECKS)
    assert base["checks_passed"] is True
    assert {c["name"] for c in base["checks"]} == set(witness.CHECK_NAMES)
    for name in ("ward_massless", "gauge_pair", "partial_width", "resonance", "spin_correlations", "permutation"):
        result = witness.compare(points()["points"], oracle(), EXPECTED, measured(), [*witness.MANDATORY_CHECKS, name])
        assert result["checks_passed"] is False
        assert result["required_unresolved"] == [name]


@pytest.mark.parametrize("defect", ["amplitude", "boost", "effective_alpha", "effective_ee", "effective_mass", "missing", "zero", "nan"])
def test_false_measured_witnesses_fail(defect):
    data = measured()
    if defect == "amplitude": data["m2"]["transverse"] *= 4
    elif defect == "boost": data["m2"]["transverse__boost_z"] *= 2
    elif defect == "effective_alpha": data["parameters"]["aEWM1"] = 256
    elif defect == "effective_ee": data["parameters"]["ee"] *= 2
    elif defect == "effective_mass": data["masses_gev"][2] = 0.105
    elif defect == "missing": del data["m2"]["angled"]
    elif defect == "zero": data["m2"]["angled"] = 0
    elif defect == "nan": data["m2"]["angled"] = float("nan")
    if defect in {"missing", "zero", "nan"}:
        with pytest.raises(ValueError): witness.compare(points()["points"], oracle(), EXPECTED, data, witness.MANDATORY_CHECKS)
    else:
        result = witness.compare(points()["points"], oracle(), EXPECTED, data, witness.MANDATORY_CHECKS)
        assert result["checks_passed"] is False


def test_compiled_dump_requires_exact_nonduplicate_finite_measurements():
    data = measured()
    text = "\n".join(["irrelevant generator banner", *[f"RAVEL_PARAMETER {k} {v:.17e}" for k, v in data["parameters"].items()],
                      *[f"RAVEL_MASS {i} 0.0D+00" for i in range(1, 5)],
                      *[f"RAVEL_M2 {k} {v:.17e}" for k, v in data["m2"].items()]])
    assert probe.parse_measurements(text, data["m2"]) == data
    for bad in (text + "\nRAVEL_M2 angled 1", text.replace("RAVEL_MASS 4 0.0D+00", ""),
                text + "\nRAVEL_M2 foreign 1", text.replace("RAVEL_M2 angled ", "RAVEL_M2 angled nan # ")):
        with pytest.raises(ValueError): probe.parse_measurements(bad, data["m2"])


def test_inputs_bind_runtime_card_references_and_exclude_unusable_caches(config, tmp_path):
    files = probe.inputs(config, tmp_path)
    runtime = Path(config["runtime"]["madgraph"])
    (runtime / "models/sm/py3_model.pkl").write_text("a stale mutable cache must not be used")
    assert probe.inputs(config, tmp_path) == files
    before = [probe.fingerprint(path) for path in files]
    (runtime / "models/sm/restrict_default.dat").write_text("different restriction")
    assert [probe.fingerprint(path) for path in probe.inputs(config, tmp_path)] != before
    assert tmp_path / "oracle.json" in files
    assert runtime / "models/sm/restrict_default.dat" in files


def test_card_mismatch_duplicate_and_auto_refused(config, tmp_path):
    path = tmp_path / "param.dat"
    original = path.read_text()
    for text in (original.replace("1 128", "1 256"), original.replace("1 128", "1 128\n1 128"),
                 original.replace("DECAY 23 2.0", "DECAY 23 Auto")):
        path.write_text(text)
        with pytest.raises(ValueError): probe.inputs(config, tmp_path)


def test_runtime_symlink_escape_and_json_duplicate_refused(config, tmp_path):
    runtime = Path(config["runtime"]["madgraph"])
    (runtime / "outside.py").symlink_to(tmp_path / "param.dat")
    with pytest.raises(ValueError): probe.inputs(config, tmp_path)
    (runtime / "outside.py").unlink()
    (tmp_path / "points.json").write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError): probe.inputs(config, tmp_path)


def test_no_external_command_without_current_approved_worker(config, tmp_path, monkeypatch):
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: pytest.fail("unapproved external command"))
    out = tmp_path / "not-an-approved-output"
    with pytest.raises(ValueError, match="approved supervised"):
        probe.run(config, tmp_path, out)
    assert not out.exists()


def test_command_and_driver_surface_are_bounded(config):
    script = probe.commands(config["runtime"], Path("/private/PROC_probe"))
    assert "output standalone" in script and "launch " not in script
    assert script.count("generate ") == 1
    assert probe.PROCESS in script
    text = probe.driver(witness.evaluations(points()["points"]), "mdl_aewm1", "mdl_ee")
    assert "CALL SMATRIX(P,ANS)" in text
    assert "CALL SETPARA('param_card.dat')" in text
    assert "PARAMETER (ZERO=0D0)" in text
    assert "INCLUDE '../../Source/MODEL/input.inc'" in text
    assert all(len(line) <= 72 for line in text.splitlines())
    assert text.count("RAVEL_M2 ") == 4
    with pytest.raises(ValueError): probe.driver([], "bad;name", "ee")


@pytest.mark.parametrize("defect", ["events", "process", "timeout", "required", "injection", "model", "artifact_shape"])
def test_strict_config_prevents_execution_scope_growth(config, defect):
    if defect == "events": config["events"] = 100
    elif defect == "process": config["process"] = "p p > j j"
    elif defect == "timeout": config["max_seconds"] = 3601
    elif defect == "required": config["required_checks"] = ["amplitude_reference"]
    elif defect == "injection": config["runtime"]["environment"]["PYTHONPATH"] = "/unbound/code"
    elif defect == "model": config["operation"] = "arbitrary-ufo"
    elif defect == "artifact_shape": config["runtime"]["artifacts"] = [{}]
    with pytest.raises(ValueError): probe.validate(config)


@pytest.mark.parametrize("selected", ["attempt-1", "repair-2"])
def test_private_workspace_is_unique_and_outside_delivered_output(tmp_path, selected):
    parent = tmp_path / "run"
    output = parent / "outputs" / selected
    output.mkdir(parents=True)
    work = probe._private_workspace(parent, output)
    assert work == parent / "work/model-probe" / selected
    assert work.is_dir() and not work.is_relative_to(output)
    with pytest.raises(ValueError, match="already exists"):
        probe._private_workspace(parent, output)


@pytest.mark.parametrize("defect", ["nested_output", "other_root", "zero_attempt", "workspace_alias",
                                    "work_parent_alias", "output_alias", "root_alias"])
def test_private_workspace_refuses_unprescribed_or_alias_paths(tmp_path, defect):
    parent = tmp_path / "run"
    output = parent / "outputs/attempt-1"
    output.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    if defect == "nested_output": output /= "nested"
    elif defect == "other_root": output = outside
    elif defect == "zero_attempt": output = parent / "outputs/attempt-0"
    elif defect == "workspace_alias":
        work = parent / "work/model-probe/attempt-1"
        work.parent.mkdir(parents=True)
        work.symlink_to(outside, target_is_directory=True)
    elif defect == "work_parent_alias":
        (parent / "work").symlink_to(outside, target_is_directory=True)
    elif defect == "output_alias":
        output.rmdir()
        output.symlink_to(outside, target_is_directory=True)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(parent, target_is_directory=True)
        parent, output = alias, alias / "outputs/attempt-1"
    with pytest.raises(ValueError):
        probe._private_workspace(parent, output)
    assert not list(outside.iterdir())


def test_approved_worker_binds_exact_selected_attempt(config, tmp_path, monkeypatch):
    from ravel.workflow import science
    parent = tmp_path / "run"
    (parent / "inputs").mkdir(parents=True)
    (parent / "inputs/science-plan.json").write_text("{}\n")
    selected = parent / "outputs/attempt-1"
    monkeypatch.setattr(science, "verify_worker", lambda root: {
        "max_seconds": 60, "output_directory": "outputs/attempt-1"})
    monkeypatch.setattr(science, "execution_spec", lambda root: {
        "mode": "domain", "task": {"domain": "model-probe", "config": config}})
    assert probe._approved_worker(config, selected) == parent
    for out in (parent / "outputs", selected / "nested", parent / "outputs/attempt-2"):
        with pytest.raises(ValueError, match="exact currently selected"):
            probe._approved_worker(config, out)
    assert not (parent / "work").exists()


def capsule_fixture(tmp_path):
    parent = tmp_path / "run"
    output = parent / "outputs/attempt-1"
    output.mkdir(parents=True)
    work = probe._private_workspace(parent, output)
    process = work / "PROC_probe"
    subdir = process / "SubProcesses/P1_epem_mupmum_no_zh"
    files = {
        subdir / "check": b"engineering fixture binary: never executed\n",
        process / "Cards/param_card.dat": b"Block SMINPUTS\n 1 128\nBlock MASS\n 11 0\n 13 0\n",
        work / "commands.mg5": b"generate e+ e- > mu+ mu- / z h QED=2\n",
        subdir / "check_sa.f": b"      PROGRAM TEST\n      END\n",
        subdir / "matrix.f": b"C engineering source fixture\n",
        subdir / "nexternal.inc": b"      PARAMETER (NEXTERNAL=4)\n",
        subdir / "pmass.inc": b"      PMASS(1)=0D0\n",
        process / "Source/MODEL/input.inc": b"      REAL*8 MDL_AEWM1\n",
        process / "Source/MODEL/coupl.inc": b"      REAL*8 MDL_EE\n",
        work / "export.log": b"fixture, no generator invoked\n",
        work / "build-model.log": b"fixture, no compiler invoked\n",
        work / "build-driver.log": b"fixture, no compiler invoked\n",
        work / "mg5/__init__.py": b"",
        work / "mg5/tests/invalid.json": b'{"intentionally invalid third party fixture":',
    }
    actual = measured()
    log = "\n".join([*[f"RAVEL_PARAMETER {k} {v:.17e}" for k, v in actual["parameters"].items()],
                     *[f"RAVEL_MASS {i} 0.0" for i in range(1, 5)],
                     *[f"RAVEL_M2 {k} {v:.17e}" for k, v in actual["m2"].items()]]) + "\n"
    files[work / "evaluate.log"] = log.encode()
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o640)
    (subdir / "check").chmod(0o750)
    return parent, work, process, subdir, output, actual


def test_capsule_preserves_complete_private_evidence_and_delivers_exact_copies(tmp_path):
    from ravel.workflow import execution
    parent, work, process, subdir, output, actual = capsule_fixture(tmp_path)
    before = execution.snapshot(parent, [str(work)])
    receipt = probe._deliver_capsule(work, process, subdir, output, actual)
    manifest = probe._load(Path(receipt["manifest"]["path"]))
    assert execution.snapshot(parent, [str(work)]) == before
    assert manifest["physics_validated"] is False
    assert "Supplemental" in manifest["retained_workspace"]["custody"]
    assert "does not automatically rehash WORK" in manifest["retained_workspace"]["custody"]
    assert len(manifest["empty_workspace_files_retained"]) == 1
    assert (work / "mg5/__init__.py").stat().st_size == 0
    assert (work / "mg5/tests/invalid.json").read_bytes().endswith(b":")
    for row in manifest["copies"]:
        assert row["source"]["sha256"] == row["delivered"]["sha256"]
        assert row["source"]["size"] == row["delivered"]["size"]
        assert row["source"]["mode"] == row["delivered"]["mode"]
    assert len(manifest["witness_files"]) == 6
    for path in manifest["witness_files"].values():
        assert Path(path).is_file() and Path(path).stat().st_size
    assert probe.parse_measurements(Path(receipt["measurement_log"]["path"]).read_text(), actual["m2"]) == actual
    assert Path(receipt["compiled_binary"]["path"]).stat().st_mode & 0o7777 == 0o750
    output_snapshot = execution.snapshot(parent, ["outputs/attempt-1"], outputs=True)
    assert len(next(iter(output_snapshot.values()))["files"]) == 14


@pytest.mark.parametrize("defect", ["missing_driver", "missing_binary", "empty_binary", "special_mode",
                                    "source_alias", "unknown_workspace_alias", "existing_capsule",
                                    "output_alias", "foreign_process"])
def test_capsule_refuses_bad_source_topology_before_any_delivery(tmp_path, defect):
    parent, work, process, subdir, output, actual = capsule_fixture(tmp_path)
    if defect == "missing_driver": (subdir / "check_sa.f").unlink()
    elif defect == "missing_binary": (subdir / "check").unlink()
    elif defect == "empty_binary": (subdir / "check").write_bytes(b"")
    elif defect == "special_mode": (subdir / "matrix.f").chmod(0o1640)
    elif defect == "source_alias":
        (subdir / "check_sa.f").unlink()
        (subdir / "check_sa.f").symlink_to("matrix.f")
    elif defect == "unknown_workspace_alias": (work / "unexpected").symlink_to("missing")
    elif defect == "existing_capsule": (output / "compiled-witness").mkdir()
    elif defect == "output_alias":
        alias = parent / "outputs/alias"
        alias.symlink_to(output, target_is_directory=True)
        output = alias
    else: process = tmp_path
    before = (subdir / "check").read_bytes() if (subdir / "check").exists() else None
    with pytest.raises(ValueError):
        probe._deliver_capsule(work, process, subdir, output, actual)
    if before is not None:
        assert (subdir / "check").read_bytes() == before
    assert not list((output / "compiled-witness").rglob("*"))


def test_capsule_measurement_copy_must_match_observed_values(tmp_path):
    _, work, process, subdir, output, actual = capsule_fixture(tmp_path)
    actual["m2"]["transverse"] *= 2
    with pytest.raises(ValueError, match="delivered measurement byte copy"):
        probe._deliver_capsule(work, process, subdir, output, actual)


@pytest.mark.parametrize("defect", ["empty", "symlink", "invalid_json", "duplicate_json", "nonfinite_json"])
def test_actual_output_guard_keeps_rejecting_bad_delivered_files(tmp_path, defect):
    from ravel.workflow import execution
    parent, work, process, subdir, output, actual = capsule_fixture(tmp_path)
    probe._deliver_capsule(work, process, subdir, output, actual)
    if defect == "empty": (output / "empty").write_bytes(b"")
    elif defect == "symlink": (output / "alias").symlink_to("compiled-witness/check")
    elif defect == "invalid_json": (output / "bad.json").write_text('{"incomplete":')
    elif defect == "duplicate_json": (output / "bad.json").write_text('{"a":1,"a":2}')
    else: (output / "bad.json").write_text('{"a":NaN}')
    with pytest.raises(ValueError):
        execution.snapshot(parent, ["outputs/attempt-1"], outputs=True)


def test_actual_stage_finalization_and_reuse_consume_capsule_not_private_tree(tmp_path):
    from ravel.workflow import execution
    parent, work, process, subdir, output, actual = capsule_fixture(tmp_path)
    specification = execution.plan_stage(parent, "engineering-custody", [sys.executable, "-B", "-c", "pass"],
        inputs=[str(process / "Cards/param_card.dat")], outputs=["outputs/attempt-1"], depends_on=[], cwd=".")
    record = execution.begin_attempt(parent, "engineering-custody", specification, "logs/engineering-custody.log")
    output.mkdir(parents=True)
    probe._deliver_capsule(work, process, subdir, output, actual)
    # A pure engineering fixture for the same strict JSON/markdown wrapper boundary.
    for name in ("model-probe-result.json", "domain-result.json", "result.json", "figures.json",
                 "recipe.json", "verification.json", "checkin2.json"):
        (output / name).write_text('{"kind":"engineering fixture","physics_validated":false}\n')
    (output / "RESULT.md").write_text("Engineering final-custody fixture, no native execution.\n")
    (parent / "logs/engineering-custody.log").write_text("No process executed in this unit control.\n")
    assert execution.finish_attempt(parent, record, 0) == 0
    assert execution.load_execution(parent)["stages"]["engineering-custody"]["status"] == "succeeded"
    assert execution.reusable(parent, "engineering-custody", specification)
    copied_driver = output / "compiled-witness/generated/SubProcesses/P1_epem_mupmum_no_zh/check_sa.f"
    copied_driver.write_text("changed delivered driver\n")
    assert not execution.reusable(parent, "engineering-custody", specification)
