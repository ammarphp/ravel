"""Dated evidence arithmetic, missingness, lineage and standalone transport tests."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "evidence/audits/2026-09-06-rrr-cut-dependence"
SPEC = importlib.util.spec_from_file_location("rrr_cut_bundle_verify", BUNDLE / "verify.py")
verify = importlib.util.module_from_spec(SPEC)
# This directory is an exact immutable evidence inventory. Ordinary pytest
# must not create an unmanifested verifier cache inside it.
exec(compile((BUNDLE / "verify.py").read_bytes(), str(BUNDLE / "verify.py"), "exec"), verify.__dict__)


@pytest.fixture
def evidence():
    return verify.read_json(BUNDLE / "data/evidence.json")


@pytest.fixture
def sources():
    return verify.read_json(BUNDLE / "source-map.json")


def mutate(data, path, value):
    for key in path[:-1]:
        data = data[key]
    data[path[-1]] = value


@pytest.mark.parametrize("path,value", [
    (("catalog","physics_certified"), True),
    (("catalog","unique_mass_points"), True),
    (("catalog","original_selected_stream_exposure"), 140000),
    (("reference","point_id"), "m150_m130"),
    (("reference","observed_sigma95_fb"), 48.0),
    (("normalization","K"), 1.0),
    (("normalization","luminosity_applied"), True),
    (("native",0,"mu","observed"), .2),
    (("native",0,"sigma95_fb","observed"), .3063582660172587),
    (("native",0,"roots",0,"status"), "above_cap"),
    (("native",0,"roots",0,"scan_cls"), .2),
    (("native",0,"roots",0,"bracket"), [.4,.5]),
    (("native",0,"flags","at_mu_floor"), True),
    (("native",0,"inference","fresh_check_evaluations"), 0),
    (("native",0,"inference","coverage_validated"), True),
    (("native",0,"profile_consistency","passed"), False),
    (("native",0,"profile_consistency","twice_nll","free_data"), 1000.),
    (("official","arms",0,"final_evaluations",0,"status"), "rejected"),
    (("official","arms",0,"n_parameters"), 191),
    (("official","rows",0,"signal_nominal_only_over_full"), 1.),
    (("official","native_uncertainty_transfer"), True),
    (("official","compiled","signal_mc_only","nominal_expected_main",0), 0.),
    (("official","compiled","full","bounds",0), [1.,2.]),
    (("official","modifier_settings","normsys","interpcode"), "code1"),
    (("lower","policy","minimum_selected_and_unselected_per_stream"), 1),
    (("lower","policy","equivalence_interval"), [0.5,2.]),
    (("lower","recipe","ptj1min_GeV"), [20.,20.,20.]),
    (("lower","rows",0,"nominal_60k","streams",0,"N"), 39),
    (("lower","rows",0,"nominal_60k","streams",0,"selected"), True),
    (("lower","rows",0,"nominal_60k","histogram_relative_mc_error"), 0.),
    (("lower","rows",0,"lower_over_nominal","selected_rate","conditional_95pct_interval"), [.9,1.1]),
    (("lower","rows",0,"lower_over_nominal","selected_rate","equivalence"), "supported_within_prespecified_interval"),
    (("lineage","pool","parents"), ["nominal_40k","nominal_20k"]),
    (("lineage","pool","alpha"), [.5,.5]),
    (("lineage","pool","independent_of_parents"), True),
    (("lineage","pool","K"), 2.),
    (("lineage","runs",0,"stages","pyhf","exit_code"), 124),
    (("lineage","runs",0,"stages","pyhf","parents","sa2json"), "0"*64),
    (("failures",0,"accepted_result"), True),
    (("failures",0,"elapsed_seconds"), 3600.),
])
def test_scientific_mutations_reject(evidence, sources, path, value):
    mutate(evidence, path, value)
    with pytest.raises(ValueError):
        verify.validate_data(evidence, sources)


@pytest.mark.parametrize("value", [float("nan"),float("inf"),float("-inf"),"NaN",True])
def test_nonfinite_and_non_numeric_roots_reject(evidence, sources, value):
    evidence["native"][0]["mu"]["observed"] = value
    with pytest.raises(ValueError):
        verify.validate_data(evidence, sources)


@pytest.mark.parametrize("population", ["native","channels","rows","official","lineage","failures","fresh"])
def test_denominator_loss_rejects(evidence, sources, population):
    rows = {"native":evidence["native"],"channels":evidence["model_channels"],
            "rows":evidence["lower"]["rows"],"official":evidence["official"]["arms"],
            "lineage":evidence["lineage"]["runs"],"failures":evidence["failures"],
            "fresh":evidence["official"]["arms"][0]["final_evaluations"]}[population]
    rows.pop()
    with pytest.raises(ValueError):
        verify.validate_data(evidence, sources)


def test_zero_or_sparse_precision_cannot_be_replaced_with_zero(evidence, sources):
    row = next(r for r in evidence["lower"]["rows"] if r["lower_over_nominal"]["selected_rate"]["equivalence"] == "unresolved")
    row["lower_over_nominal"]["selected_rate"]["conditional_95pct_interval"] = [0.,0.]
    with pytest.raises(ValueError):
        verify.validate_data(evidence, sources)


def test_explicit_alias_and_all_six_quantiles_positive(evidence, sources):
    result = verify.validate_data(evidence, sources)
    assert result["native_roots"] == 24
    assert result["official_roots"] == 18
    assert result["lower_ratio_checks"] == 120
    assert evidence["native"][2]["source_sample_id"] == "nominal_pool_60k"
    assert all(r["final_evaluations"] is None for r in evidence["native"])


def test_duplicate_json_and_nonfinite_load_reject(tmp_path):
    path = tmp_path/"x.json"
    for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
        path.write_text(text)
        with pytest.raises(ValueError):
            verify.read_json(path)


def test_rehashed_transport_does_not_hide_wrong_units(tmp_path):
    target = tmp_path/"bundle"
    shutil.copytree(BUNDLE,target)
    path = target/"data/evidence.json"
    data = verify.read_json(path)
    data["native"][0]["sigma95_fb"]["observed"] /= 1000
    path.write_bytes(verify.encode(data))
    manifest = verify.read_json(target/"manifest.json")
    manifest["files"]["data/evidence.json"] = {"sha256":verify.digest(path.read_bytes()),"bytes":path.stat().st_size}
    (target/"manifest.json").write_bytes(verify.encode(manifest))
    with pytest.raises(ValueError, match="Arithmetic"):
        verify.verify_bundle(target)


@pytest.mark.parametrize("path", ["../outside", "/absolute", "a/../b", "a\\b", "a//b"])
def test_source_path_rejections(tmp_path, path):
    with pytest.raises(ValueError):
        verify.path_under(tmp_path, path)


def test_standalone_no_repository_or_site_imports(tmp_path):
    target = tmp_path/"bundle"
    shutil.copytree(BUNDLE,target)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH",None)
    command = [sys.executable,"-I","-S","-B",str(target/"verify.py")]
    result = subprocess.run(command,cwd=tmp_path,env=env,text=True,capture_output=True,timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_artifacts"] >= 98
    assert not list(target.rglob("*.pyc"))


def test_actual_bundle_inventory():
    assert verify.verify_bundle()["status"] == "verified"


def test_selected_source_archive_relocation_and_drift(tmp_path, sources):
    available = [(ROOT / pin["path"]).exists() for pin in sources["sources"].values()]
    # The public checkout retains the predecessor's manifest. Its presence does
    # not mean any private research archive was distributed.
    private = [pin for pin in sources["sources"].values()
               if Path(pin["path"]).parts[0] in ("trial-runs", "local-runs")]
    assert private, "Selected original private archive must be identified"
    if not any((ROOT / pin["path"]).exists() for pin in private):
        pytest.skip("Selected original research archive is not shipped in the public distribution")
    assert all(available), "Selected original archive is partially missing"
    target = tmp_path/"bundle"
    shutil.copytree(BUNDLE,target)
    original = tmp_path/"relocated-originals"
    for pin in sources["sources"].values():
        path = original/pin["path"]
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/pin["path"],path)
    env = dict(os.environ,PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH",None)
    command = [sys.executable,"-B",str(target/"verify.py"),"--source-root",str(original)]
    result = subprocess.run(command,cwd=tmp_path,env=env,text=True,capture_output=True,timeout=20)
    assert result.returncode == 0, result.stderr
    selected = original/sources["sources"]["nominal_20k_result"]["path"]
    selected.write_bytes(selected.read_bytes()+b" ")
    result = subprocess.run(command,cwd=tmp_path,env=env,text=True,capture_output=True,timeout=20)
    assert result.returncode != 0
    assert "Selected original source changed: nominal_20k_result" in result.stderr


def test_published_checkout_without_private_sources_or_bytecode_policy(tmp_path):
    root = tmp_path / "public"
    bundle = root / BUNDLE.relative_to(ROOT)
    shutil.copytree(BUNDLE, bundle)
    sources = json.loads((BUNDLE / "source-map.json").read_text())
    # Exercise the real distribution shape, including its still-public source
    # commitment, rather than an empty ancestor archive that hid this failure.
    for pin in sources["sources"].values():
        if Path(pin["path"]).parts[0] == "evidence":
            target = root / pin["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / pin["path"], target)
    test = root / "tests/unit/test_rrr_cut_dependence_bundle.py"
    test.parent.mkdir(parents=True)
    shutil.copyfile(__file__, test)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test), "-q", "-k",
         "not published_checkout_without_private_sources_or_bytecode_policy"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "63 passed, 1 skipped, 1 deselected" in result.stdout
    assert not list(bundle.rglob("*.pyc"))
    assert not (bundle / "__pycache__").exists()
