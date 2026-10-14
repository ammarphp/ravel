"""Native contract/result controls. These tests do not qualify a Combine build."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import os
import shutil
import time
from types import SimpleNamespace

import pytest

from ravel.physics import native_likelihood as native
from test_eft_functions import CARD, SOURCE


VERSION_SOURCE = '''std::string combineTagString = "v9.2.1";
if(datacard == "") {
    cerr << "Missing datacard file" << endl;
    cout << "Usage: combine [options]\\n";
    return 1002;
}
if (seed == -1) { /* no-datacard returns before RNG */ }
combiner.applyOptions(vm);
'''
VERSION_LOG = " <<< Combine >>> \n <<< v9.2.1 >>>\nMissing datacard file\nUsage: combine [options]\n"


@pytest.mark.parametrize("has_nuisances,has_globals", [(True, True), (True, False), (False, True), (False, False)])
def test_generated_probe_uses_derived_cpp_nll_signature_without_dropping_options(has_nuisances, has_globals):
    """Regression for the actual RooSimultaneousOpt vararg TypeError, no ROOT run."""
    workspace = next(node for node in ast.parse(native.NATIVE_PROBE).body
                     if isinstance(node, ast.If) and ast.unparse(node.test) == "len(sys.argv) > 2")
    start = next(i for i, node in enumerate(workspace.body)
                 if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "opts")
    stop = next(i for i, node in enumerate(workspace.body)
                if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "nll")
    block = ast.Module(body=workspace.body[start:stop + 1], type_ignores=[])
    class LinkedList:
        def __init__(self): self.options = []
        def Add(self, option): self.options.append(option)
    nuisance = object() if has_nuisances else None
    globals_ = object() if has_globals else None
    data, nll = object(), object()
    seen = []
    class DerivedPDF:
        # The source-declared custom C++ overload has only these two arguments.
        def createNLL(self, actual_data, command_list):
            assert actual_data is data and isinstance(command_list, LinkedList)
            seen.extend(command_list.options)
            return nll
    pdf = DerivedPDF()
    root = SimpleNamespace(RooLinkedList=LinkedList, RooFit=SimpleNamespace(
        Constrain=lambda values: ("Constrain", values),
        GlobalObservables=lambda values: ("GlobalObservables", values)))
    mc = SimpleNamespace(GetNuisanceParameters=lambda: nuisance,
                         GetGlobalObservables=lambda: globals_, GetPdf=lambda: pdf)
    namespace = {"ROOT": root, "mc": mc, "data": data}
    exec(compile(block, "actual_generated_native_probe", "exec"), namespace)
    expected = ([("Constrain", nuisance)] if has_nuisances else []) + ([("GlobalObservables", globals_)] if has_globals else [])
    assert seen == expected == namespace["opts"]
    assert namespace["nll"] is nll


def counting_card():
    return CARD.replace(b"BSM", b"sig").replace(b"background", b"bkg").replace(b"rate 2.5 10 0.25 20", b"rate 2.5 1 0.25 1")


def replacement():
    return {"source": "Synthetic independent new signal and uncertainty control, including CR contamination.",
            "columns": [{"channel": "SR", "process": "sig", "rate": "3.0", "nuisances": {"shared": "0.9/1.15"}},
                        {"channel": "CR", "process": "sig", "rate": "0.75", "nuisances": {"shared": "1.25"}}]}


def test_all_region_signal_and_explicit_nuisance_replacement():
    raw = counting_card()
    changed, receipt = native.replace_counting_signal(raw, replacement())
    census = native.eft.parse_datacard(changed)
    assert [c["rate"] for c in census["columns"]] == ["3.0", "1", "0.75", "1"]
    assert b"shared lnN 0.9/1.15 1.2 1.25 1.2\n" in changed
    assert receipt["replaced_signal_columns"] == 2
    assert receipt["replaced_nuisance_rows"] == ["shared"]
    assert raw == counting_card()


@pytest.mark.parametrize("mutation", [
    lambda r: r["columns"].pop(),
    lambda r: r["columns"].reverse(),
    lambda r: r["columns"][1]["nuisances"].clear(),
    lambda r: r["columns"][0]["nuisances"].update({"invented": "1.1"}),
    lambda r: r["columns"][1].update({"rate": "-1"}),
    lambda r: r["columns"][1]["nuisances"].update({"shared": "0.0/1.1"}),
])
def test_missing_swapped_cr_or_stale_signal_uncertainty_refuses(mutation):
    rep = replacement()
    mutation(rep)
    with pytest.raises(ValueError):
        native.replace_counting_signal(counting_card(), rep)


def test_counting_replacement_refuses_shape_model():
    with pytest.raises(ValueError, match="shape histograms"):
        native.replace_counting_signal(b"shapes * * model.root $PROCESS\n" + counting_card(), replacement())


def fit(method="AsymptoticLimits"):
    return {"method": method, "data": "observed", "poi": "r", "domain": ["0", "10"], "mass": 120,
            "seed": 12345, "points": None if method == "AsymptoticLimits" else 3, "minimizer": None,
            "fixed_witness_points": ["0", "1"], "reference_quantiles": None}


def quantiles():
    return [{"quantileExpected": q, "limit": v} for q, v in [(0.025, 1), (0.1599999, 2), (0.5, 3), (0.8399999, 4), (0.975, 5), (-1, 2.5)]]


def test_native_quantile_extraction_requires_full_exact_denominator():
    result = native.extract_rows(quantiles(), fit())
    assert result["quantiles"] == {"minus2sigma": 1, "minus1sigma": 2, "median": 3, "plus1sigma": 4, "plus2sigma": 5, "observed": 2.5}
    for rows in [quantiles()[:-1], quantiles() + [quantiles()[0]],
                 [{"quantileExpected": 0.5, "limit": float("nan")}],
                 [dict(r, quantileExpected=0.99) if i == 4 else r for i, r in enumerate(quantiles())]]:
        with pytest.raises(ValueError):
            native.extract_rows(rows, fit())


def test_reference_disagreement_is_a_failed_delivered_comparison():
    cfg = fit()
    values = native.extract_rows(quantiles(), cfg)["quantiles"]
    cfg["reference_quantiles"] = {"source": "synthetic source", "values": dict(values, median=3.1), "absolute_tolerance": 1e-4, "relative_tolerance": 1e-4}
    result = native.extract_rows(quantiles(), cfg)
    assert result["passed"] is False
    assert result["rows"] == quantiles()


def test_native_result_diagnostics_are_retained_and_failing_fits_do_not_pass():
    cfg = dict(fit("MultiDimFit"), poi="fm0", domain=["-15", "15"])
    rows = [{"fm0": p, "deltaNLL": d, "quantileExpected": q} for p, d, q in [(2, 0, -1), (-10, 2, .1), (0, 0, 1), (10, 1, .2)]]
    diagnostic = {"name": "fit_mdf", "status": 0, "covariance_quality": 3,
                  "edm": 0.0001, "minimum_nll": 8.0, "invalid_nll_evaluations": 0,
                  "status_history": [{"label": "MIGRAD", "status": 0}]}
    def probe(fits):
        return "RAVEL_NATIVE_RESULT=" + json.dumps({"rows": rows, "fit_results": fits})
    result = native.extract_native_result(probe([diagnostic]), cfg)
    assert result["passed"] and result["fit_diagnostics"]["saved_fit_results"] == [diagnostic]
    failed = native.extract_native_result(probe([dict(diagnostic, status=1)]), cfg)
    assert failed["passed"] is False and failed["fit_diagnostics"]["suspect_results"] == ["fit_mdf"]
    absent = native.extract_native_result(probe([]), cfg)
    assert absent["passed"] and absent["fit_diagnostics"]["saved_result_available"] is False
    asymptotic = native.extract_native_result("RAVEL_NATIVE_RESULT=" + json.dumps({"rows": quantiles(), "fit_results": []}), fit())
    assert asymptotic["passed"] and asymptotic["fit_diagnostics"]["saved_fit_results"] == []


def test_signed_nonmonotonic_profile_preserves_all_rows_and_refuses_missing_grid():
    cfg = dict(fit("MultiDimFit"), poi="fm0", domain=["-15", "15"])
    rows = [{"fm0": p, "deltaNLL": nll, "quantileExpected": q} for p, nll, q in [(2, 0, -1), (-10, 5, .1), (0, 2, .2), (10, 1, .3)]]
    assert native.extract_rows(rows, cfg)["rows"] == rows
    with pytest.raises(ValueError, match="coverage"):
        native.extract_rows(rows[:2], cfg)
    with pytest.raises(ValueError, match="signed domain"):
        native.extract_rows([*rows, {"fm0": 16, "deltaNLL": 1, "quantileExpected": .2}], cfg)
    suspect = native.extract_rows([dict(r, deltaNLL=999) if i == 3 else r for i, r in enumerate(rows)], cfg)
    assert suspect["passed"] is False and suspect["suspect_fit_rows"] == [3]
    # A best-fit row must never cover a missing grid position.
    with pytest.raises(ValueError, match="coverage"):
        native.extract_rows(rows[:-1], cfg)
    with pytest.raises(ValueError, match="duplicate"):
        native.extract_rows([*rows, rows[1]], cfg)


def fixture(tmp_path):
    def pin(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    card = tmp_path / "card.txt"
    card.write_bytes(counting_card())
    binary = tmp_path / "tool"
    binary.write_text("#!/bin/sh\nexit 99\n")
    binary.chmod(0o755)
    library = tmp_path / "libHiggsAnalysisCombinedLimit.so"
    library.write_bytes(b"synthetic ABI input; not a runtime qualification")
    module = tmp_path / "PhysicsModel.py"
    module.write_text("# synthetic pinned module, never imported\n")
    version_source = tmp_path / "combine.cpp"
    version_source.write_text(VERSION_SOURCE)
    config = {"schema_version": 1, "source": "Synthetic contract, not native physics.", "max_seconds": 10,
              "model": {"files": [{**pin(card), "staged_path": "source/card.txt"}], "card": "source/card.txt",
                        "regions": [{"channel": "SR", "role": "signal_region"}, {"channel": "CR", "role": "control_region"}],
                        "physics_model": None, "signal_replacement": None},
              "runtime": {"tools": {key: pin(binary) for key in ("combine", "text2workspace", "python")},
                          "transport": {"kind": "local"},
                          "artifacts": [pin(library), pin(module)], "environment": {"PATH": "/usr/bin:/bin"},
                          "version_proof": {"kind": "missing_datacard_diagnostic", "source": pin(version_source), "expected_returncode": 234},
                          "expected": {"combine_version": "9.2.1", "root_version": "6.24/00", "cmssw_version": None,
                                       "architecture": "x86_64", "custom_classes": ["RooParametricHist"]}},
              "fit": fit()}
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps(config))
    return cp, config, card, binary, library


def observation_fixture(tmp_path):
    """Actual Podman admission contract with tiny files, never a native job."""
    cp, config, card, binary, _ = fixture(tmp_path)
    archive = tmp_path / 'image.tar';archive.write_bytes(b'synthetic image byte control' * 1024)
    manifest = tmp_path / 'image-manifest.json'
    manifest.write_text(json.dumps({'config': {'digest': 'sha256:' + 'a' * 64}}))
    def pin(path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest_pin = pin(manifest)
    config['runtime']['transport'] = {'kind': 'podman', 'executable': pin(binary),
        'connection': 'synthetic-read-only', 'image_archive': pin(archive), 'image_manifest': manifest_pin,
        'image_id': 'sha256:' + 'a' * 64, 'manifest_digest': 'sha256:' + manifest_pin['sha256'],
        'client_environment': {'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin'}}
    cp.write_text(json.dumps(config))
    return cp, config, card, binary, archive, manifest


def observation_spec(cp, *, ceiling=10):
    return {'mode': 'native-likelihood', 'task': {'input': str(cp)}, 'max_seconds': ceiling}


def forbid_native(monkeypatch):
    # Warm only local host identity before requiring no process calls in the
    # actual adapter/planner observation, as the retained CMS profile does.
    import platform
    platform.platform()
    def forbidden(*args, **kwargs):
        pytest.fail('input/resource observation started native or model work')
    monkeypatch.setattr(native.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(native, 'run', forbidden)
    monkeypatch.setattr(native, '_run', forbidden)


def test_native_one_observation_shares_each_digest_and_next_observation_is_fresh(tmp_path,monkeypatch):
    from ravel.workflow import execution, science
    from ravel.workflow.validation_io import ValidationSession
    cp, _, card, binary, archive, manifest = observation_fixture(tmp_path)
    expected = [cp, card, binary, archive, manifest, tmp_path/'combine.cpp']
    assert native.inputs({'input': str(cp)}, tmp_path) == expected
    assert native.execution_seconds({'input': str(cp)}, tmp_path) == 10
    hashed=[];original=ValidationSession.hash_file
    def counted(session,path):
        before=session.hash_calls;result=original(session,path)
        if session.hash_calls>before:hashed.append((id(session),Path(path)))
        return result
    monkeypatch.setattr(ValidationSession,'hash_file',counted)
    forbid_native(monkeypatch)
    phases=[]
    for _ in range(2):
        with science._validation_scope(tmp_path) as session:
            phases.append(session)
            for _ in range(4):
                assert science.task_inputs(observation_spec(cp),tmp_path,_session=session)==expected
            assert session.hash_calls==len(expected)
    assert len(hashed)==2*len(expected)
    assert all({path for sid,path in hashed if sid==id(session)}==set(expected) for session in phases)
    assert phases[0] is not phases[1] and all(s.closed and not s.hashes for s in phases)


def test_native_resource_hook_shares_only_inside_supplied_session(tmp_path,monkeypatch):
    from ravel.workflow import science
    cp, _, _, _, archive, _ = observation_fixture(tmp_path)
    opened=[];original=Path.open
    def counted(path,*args,**kwargs):
        if path==archive:opened.append(path)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',counted)
    forbid_native(monkeypatch)
    with science._validation_scope(tmp_path) as session:
        native._validation_inputs({'input': str(cp)},tmp_path,session)
        native._validation_execution_seconds({'input': str(cp)},tmp_path,session)
        assert len(opened)==1
    native.execution_seconds({'input': str(cp)},tmp_path)
    native.execution_seconds({'input': str(cp)},tmp_path)
    assert len(opened)==3


@pytest.mark.parametrize('change',['outer_ceiling','task_schema','expected_pin'])
def test_cached_native_bytes_do_not_skip_resource_schema_or_expected_pin_checks(tmp_path,monkeypatch,change):
    from ravel.workflow import science
    cp, config, _, _, archive, _ = observation_fixture(tmp_path)
    forbid_native(monkeypatch)
    with science._validation_scope(tmp_path) as session:
        science.task_inputs(observation_spec(cp),tmp_path,_session=session)
        with pytest.raises(ValueError):
            if change=='outer_ceiling':
                science.task_inputs(observation_spec(cp,ceiling=9),tmp_path,_session=session)
            elif change=='task_schema':
                native._validation_execution_seconds({'input': str(cp),'unknown':True},tmp_path,session)
            else:
                native._pin({'path':str(archive),'sha256':'0'*64},tmp_path,_session=session)


@pytest.mark.parametrize('change',['same_size_restored_mtime','same_bytes_replacement','same_target_symlink',
                                   'parent_symlink','executable_mode','missing_archive','version_source','configuration'])
def test_native_cached_input_or_budget_mutation_refuses_before_authority(tmp_path,monkeypatch,change):
    from ravel.workflow import science
    assets=tmp_path/'assets';assets.mkdir()
    cp, _, _, binary, archive, _ = observation_fixture(assets)
    forbid_native(monkeypatch)
    with pytest.raises((ValueError,OSError)):
        with science._validation_scope(tmp_path) as session:
            science.task_inputs(observation_spec(cp),tmp_path,_session=session)
            before=archive.stat()
            if change=='same_size_restored_mtime':
                raw=archive.read_bytes();archive.write_bytes(b'X'+raw[1:])
                os.utime(archive,ns=(before.st_atime_ns,before.st_mtime_ns))
            elif change=='same_bytes_replacement':
                replacement=assets/'replacement';replacement.write_bytes(archive.read_bytes());replacement.replace(archive)
            elif change=='same_target_symlink':
                target=assets/'original.tar';archive.rename(target);archive.symlink_to(target)
            elif change=='parent_symlink':
                moved=tmp_path/'moved';assets.rename(moved);assets.symlink_to(moved,target_is_directory=True)
            elif change=='executable_mode':binary.chmod(0o644)
            elif change=='missing_archive':archive.unlink()
            elif change=='version_source':(assets/'combine.cpp').write_text(VERSION_SOURCE.replace('v9.2.1','v9.2.0'))
            else:cp.write_text(cp.read_text().replace('"max_seconds": 10','"max_seconds": 11'))
            native._validation_execution_seconds({'input':str(cp)},tmp_path,session)


@pytest.mark.parametrize('change',['add_file','add_empty_directory','replace_directory','parent_symlink'])
def test_native_observation_preserves_ending_membership_and_ancestry_checks(tmp_path,monkeypatch,change):
    from ravel.workflow import science
    assets=tmp_path/'assets';assets.mkdir();cp,*_=observation_fixture(assets)
    forbid_native(monkeypatch)
    with pytest.raises(ValueError,match='inventory changed|symlink|identity changed'):
        with science._validation_scope(tmp_path) as session:
            science.task_inputs(observation_spec(cp),tmp_path,_session=session)
            session.require_inventory(assets)
            if change=='add_file':(assets/'unexpected').write_bytes(b'new member')
            elif change=='add_empty_directory':(assets/'unexpected').mkdir()
            else:
                moved=tmp_path/'original';assets.rename(moved)
                if change=='replace_directory':shutil.copytree(moved,assets)
                else:assets.symlink_to(moved,target_is_directory=True)


def test_native_fresh_next_observation_rehashes_and_refuses_restored_mtime(tmp_path,monkeypatch):
    from ravel.workflow import science
    cp,_,_,_,archive,_=observation_fixture(tmp_path)
    reads=[];original=Path.open
    def counted(path,*args,**kwargs):
        if path==archive:reads.append(path)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',counted);forbid_native(monkeypatch)
    with science._validation_scope(tmp_path) as session:
        science.task_inputs(observation_spec(cp),tmp_path,_session=session)
    before=archive.stat();raw=archive.read_bytes();archive.write_bytes(b'X'+raw[1:])
    os.utime(archive,ns=(before.st_atime_ns,before.st_mtime_ns));reads.clear()
    with pytest.raises(ValueError,match='changed source/runtime'):
        with science._validation_scope(tmp_path) as second:
            science.task_inputs(observation_spec(cp),tmp_path,_session=second)
    assert reads==[archive] and second.closed and not second.hashes


def test_native_version_text_read_remains_bound_to_ending_identity_check(tmp_path,monkeypatch):
    from ravel.workflow import science
    cp,*_=observation_fixture(tmp_path);source=tmp_path/'combine.cpp'
    old=Path.read_text;done=[];forbid_native(monkeypatch)
    def changed(path,*args,**kwargs):
        text=old(path,*args,**kwargs)
        if path==source and not done:
            done.append(True);before=source.stat()
            source.write_text(text.replace('v9.2.1','v9.2.0'))
            os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
        return text
    monkeypatch.setattr(Path,'read_text',changed)
    with pytest.raises(ValueError,match='identity changed'):
        with science._validation_scope(tmp_path) as session:
            # The old text still passes its source grammar; ending file identity
            # must refuse authority after that text read changed the underlying file.
            assert native._validation_execution_seconds({'input':str(cp)},tmp_path,session)==10


def test_planning_binds_source_runtime_and_all_regions_without_execution(tmp_path, monkeypatch):
    cp, config, card, binary, library = fixture(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("planning executed native code")
    monkeypatch.setattr(native.subprocess, "Popen", forbidden)
    assert native.inputs({"input": cp.name}, tmp_path) == [cp, card, binary, library, tmp_path / "PhysicsModel.py", tmp_path / "combine.cpp"]
    assert native.execution_seconds({"input": cp.name}, tmp_path) == 10
    config["model"]["regions"].pop()
    cp.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="region"):
        native.inputs({"input": cp.name}, tmp_path)


def test_native_commands_preserve_requested_fit_semantics(tmp_path):
    _, cfg, _, binary, _ = fixture(tmp_path)
    tools = {key: binary for key in ("combine", "text2workspace", "python")}
    build, command = native.commands(cfg, tools, tmp_path / "work")
    assert "-P" not in build and command[command.index("-M") + 1] == "AsymptoticLimits"
    assert command[command.index("--cl") + 1] == "0.95"
    cfg["fit"] = dict(fit("MultiDimFit"), poi="fm0", domain=["-15", "15"], points=101)
    build, command = native.commands(cfg, tools, tmp_path / "work", has_response=True)
    assert build[build.index("-P") + 1] == "ravel_source_response:model"
    assert "fm0=-15.0,15.0" in command and "--saveNLL" in command and "--saveFitResult" in command
    assert "--freezeParameters" not in command


def test_actual_probe_identity_and_custom_classes_not_metadata_alone():
    expected = {"combine_version": "9.2.1", "root_version": "6.24/00", "cmssw_version": None,
                "architecture": "x86_64", "custom_classes": ["RooParametricHist"]}
    probe = {"architecture": "arm64", "root_version": "6.24/00", "cmssw_version": None,
             "custom_classes": {"RooParametricHist": True}}
    with pytest.raises(ValueError, match="architecture"):
        native._check_probe(probe, expected)
    probe["architecture"] = "x86_64"
    probe["custom_classes"]["RooParametricHist"] = False
    with pytest.raises(ValueError, match="custom-class"):
        native._check_probe(probe, expected)


def test_missing_abi_assets_extra_options_and_unbound_shapes_refuse(tmp_path):
    cp, config, card, _, _ = fixture(tmp_path)
    changes = [lambda c: c["runtime"].update({"artifacts": []}),
               lambda c: c["fit"].update({"options": ["--freezeParameters", "all"]}),
               lambda c: c["model"]["files"][0].update({"staged_path": "../card.txt"}),
               lambda c: c["model"]["files"][0].update({"staged_path": "source/multidimfit.ravel.root"})]
    for change in changes:
        mutated = deepcopy(config)
        change(mutated)
        cp.write_text(json.dumps(mutated))
        with pytest.raises(ValueError):
            native.inputs({"input": cp.name}, tmp_path)
    card.write_bytes(b"shapes * * absent.root $PROCESS\n" + counting_card())
    config["model"]["files"][0]["sha256"] = native._hash(card)
    cp.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="unbound datacard asset"):
        native.inputs({"input": cp.name}, tmp_path)


def test_native_eft_requires_source_poi_full_signed_domain(tmp_path):
    cp, config, card, _, _ = fixture(tmp_path)
    card.write_bytes(CARD)
    config["model"]["files"][0]["sha256"] = native._hash(card)
    source = tmp_path / "model.py"
    source.write_text(SOURCE)
    config["model"]["physics_model"] = {"path": str(source), "sha256": native._hash(source)}
    cp.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="EFT uses native"):
        native.inputs({"input": cp.name}, tmp_path)
    config["fit"] = dict(fit("MultiDimFit"), poi="fm0", domain=["-15", "15"])
    cp.write_text(json.dumps(config))
    assert source in native.inputs({"input": cp.name}, tmp_path)


def test_podman_command_keeps_image_custody_and_bounded_owned_container(tmp_path):
    transport = {"executable": {"path": "/tools/podman"}, "connection": "owned-vm",
                 "image_id": "sha256:" + "b" * 64}
    command = native.container_command(["/opt/conda/bin/python3.8", "probe.py"], tmp_path / "work", {"PATH": "/image/bin"},
                                       transport, tmp_path, 30, tmp_path / "probe.cid")
    for option in ("--pull=never", "--platform=linux/amd64", "--network=none", "--cpus=1", "--memory=4g", "--pids-limit=512", "--user=0"):
        assert option in command
    assert command[command.index("--timeout") + 1] == "30"
    assert command[command.index("--cidfile") + 1] == str(tmp_path / "probe.cid")
    assert command[-2:] == [transport["image_id"], "probe.py"]
    assert command[command.index("--volume") + 1] == str(tmp_path) + ":" + str(tmp_path) + ":rw"


def test_podman_planning_pins_client_archive_manifest_without_launch(tmp_path, monkeypatch):
    cp, config, card, binary, library = fixture(tmp_path)
    config_digest = "sha256:" + "f" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"config": {"digest": config_digest}}))
    archive = tmp_path / "image.oci.tar"
    archive.write_bytes(b"synthetic planning control; not an image qualification")
    def pin(path):
        return {"path": str(path), "sha256": native._hash(path)}
    config["runtime"]["transport"] = {"kind": "podman", "executable": pin(binary), "connection": "owned-vm",
        "image_archive": pin(archive), "image_manifest": pin(manifest), "manifest_digest": "sha256:" + native._hash(manifest),
        "image_id": config_digest, "client_environment": {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}}
    for name, row in config["runtime"]["tools"].items():
        row["path"] = "/image/bin/" + name
    for row in config["runtime"]["artifacts"]:
        row["path"] = "/image/lib/" + Path(row["path"]).name
    cp.write_text(json.dumps(config))
    monkeypatch.setattr(native.subprocess, "Popen", lambda *a, **k: pytest.fail("planning started container"))
    assert native.inputs({"input": cp.name}, tmp_path) == [cp, card, binary, archive, manifest, tmp_path / "combine.cpp"]
    config["runtime"]["transport"]["image_id"] = "sha256:" + "c" * 64
    cp.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="digest binding"):
        native.inputs({"input": cp.name}, tmp_path)


def test_failed_native_command_delivers_explicit_failure_and_retained_log(tmp_path, monkeypatch):
    out = tmp_path / "attempt"
    def failed(task, base, destination):
        destination.mkdir()
        (destination / "fit-failure.log").write_text("actual native fit failed; no accepted result\n")
        raise ValueError("native fit command failed")
    monkeypatch.setattr(native, "_run", failed)
    result = native.run({"input": "synthetic-unused-control.json"}, tmp_path, out)
    assert result["status"] == "failed" and result["physics_validated"] is False
    assert result["runtime_qualified_for_this_workspace"] is False
    assert result["retained_artifacts"][0]["path"] == "fit-failure.log"
    assert "not reached" in result["custody_status"]
    assert json.loads((out / "native-likelihood.json").read_text()) == result


@pytest.mark.parametrize("change", [
    lambda p: p.update({"kind": "help"}),
    lambda p: p.update({"expected_returncode": 0}),
    lambda p: p.update({"expected_returncode": True}),
    lambda p: p.update({"argv": ["--help"]}),
    lambda p: p["source"].update({"sha256": "0" * 64}),
])
def test_version_proof_schema_and_expected_diagnostic_exit_refuse_before_execution(tmp_path, monkeypatch, change):
    cp, config, *_ = fixture(tmp_path)
    change(config["runtime"]["version_proof"])
    cp.write_text(json.dumps(config))
    monkeypatch.setattr(native.subprocess, "Popen", lambda *a, **k: pytest.fail("admission executed a tool"))
    with pytest.raises(ValueError):
        native.inputs({"input": cp.name}, tmp_path)


@pytest.mark.parametrize("changed", [
    VERSION_SOURCE.replace("v9.2.1", "v9.2.2"),
    VERSION_SOURCE.replace("return 1002", "return 0"),
    VERSION_SOURCE.replace('"Missing datacard file"', '"No input"'),
    "combiner.applyOptions(vm);\n" + VERSION_SOURCE,
    VERSION_SOURCE + 'std::string combineTagString = "v9.2.1";\n',
])
def test_version_source_pin_cannot_establish_another_tag_or_later_exit(tmp_path, changed):
    cp, config, *_ = fixture(tmp_path)
    source = tmp_path / "combine.cpp"
    source.write_text(changed)
    config["runtime"]["version_proof"]["source"]["sha256"] = native._hash(source)
    cp.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="diagnostic boundary"):
        native.inputs({"input": cp.name}, tmp_path)


def test_help_is_not_compiled_version_evidence_even_if_options_mention_a_version():
    help_log = "RooFit v3.60\nUsage: combine datacard [options]\nExample from v9.2.1\n"
    with pytest.raises(ValueError, match="compiled version"):
        native._combine_version_identity(help_log, "9.2.1")
    assert native._combine_version_identity(VERSION_LOG, "9.2.1")["combine_version"] == "9.2.1"
    for log in (VERSION_LOG.replace("v9.2.1", "v9.2.2"), VERSION_LOG.replace("Missing datacard file\n", ""),
                VERSION_LOG + " <<< v9.2.1 >>>\n", VERSION_LOG + "Missing datacard file\n"):
        with pytest.raises(ValueError, match="compiled version"):
            native._combine_version_identity(log, "9.2.1")


def test_diagnostic_exit_is_retained_and_scientific_commands_still_require_zero(tmp_path):
    tool = tmp_path / "diagnostic"
    tool.write_text("#!/bin/sh\nprintf ' <<< Combine >>> \\n <<< v9.2.1 >>>\\nMissing datacard file\\n'\nexit 234\n")
    tool.chmod(0o755)
    log = tmp_path / "diagnostic.log"
    result = native._process([str(tool)], tmp_path, {"PATH": "/usr/bin:/bin"}, log,
                             time.monotonic() + 10, expected_returncode=234)
    assert native._combine_version_identity(result, "9.2.1")["expected_returncode"] == 234
    receipt = json.loads(log.with_suffix(".command.json").read_text())
    assert receipt["actual_returncode"] == receipt["expected_returncode"] == 234
    for command in ([str(tool)], [str(tool), "workspace.root", "-M", "AsymptoticLimits"]):
        with pytest.raises(ValueError, match="native command failed"):
            native._process(command, tmp_path, {"PATH": "/usr/bin:/bin"}, tmp_path / "fit.log", time.monotonic() + 10)
    with pytest.raises(ValueError, match="no-argument"):
        native._process([str(tool), "workspace.root"], tmp_path, {}, log, time.monotonic() + 10, expected_returncode=234)
    for wrong_exit in (0, 231):
        tool.write_text("#!/bin/sh\nexit " + str(wrong_exit) + "\n")
        with pytest.raises(ValueError, match="native command failed"):
            native._process([str(tool)], tmp_path, {"PATH": "/usr/bin:/bin"}, log, time.monotonic() + 10, expected_returncode=234)
