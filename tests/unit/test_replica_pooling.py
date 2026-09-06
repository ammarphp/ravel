"""Source-bound pooling uses original exposure; real ROOT I/O needs uproot."""
import copy
import gzip
import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from ravel.physics import pool_replicas as pooling
from ravel.physics.native_normalization import fingerprint, reconcile_weights, resolve_normalization
from ravel.physics.native_pipeline import plan_hash
from ravel.physics.native_simpleanalysis import sr_order, cr_order
from ravel.paths import module_command
from ravel.workflow.execution import digest, snapshot


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def numerical_replica(n, selected, seed, xs=1):
    values = np.full(selected, xs/n)
    return {"original_generated_events": n, "normalized_cross_section_pb": xs,
        "physics": {"model": "identical"}, "mg_seed": seed, "shower_seed": seed+100,
        "detector_seed": seed+1000, "lhe_sha256": str(seed), "region_names": ["SR"],
        "original_row_index": np.arange(selected), "arrays": {"Event": np.arange(selected)+100,
            "eventWeight": values, "isee": np.ones(selected,dtype=np.int32),
            "ismm": np.zeros(selected,dtype=np.int32), "SR": values}}


def test_original_exposure_not_selected_rows_or_additive_yields():
    arrays, record = pooling.combine([numerical_replica(2,1,1), numerical_replica(6,2,2,xs=2)])
    assert [r["alpha"] for r in record["replicas"]] == [.25,.75]
    assert record["original_generated_events"] == 8
    assert record["retained_analysis_rows"] == 3
    assert record["normalized_cross_section_pb"] == 1.75
    np.testing.assert_array_equal(arrays["Event"], [0,2,3])
    np.testing.assert_array_equal(arrays["sourceEvent"], [100,100,101])
    np.testing.assert_array_equal(arrays["replicaIndex"], [0,1,1])
    assert record["moments"]["SR"]["sumw_pb"] == .625
    assert record["moments"]["SR"]["sumw2_pb2"] == .140625
    assert "distinct" in record["detector_seed_policy"]
    assert "Poissonized independent-event" in record["statistical_scope"]


def test_zero_selected_precision_unresolved():
    _, record = pooling.combine([numerical_replica(2,0,1), numerical_replica(6,0,2)])
    assert record["moments"]["SR"]["sumw_pb"] == 0
    assert record["moments"]["SR"]["absolute_mc_error_pb"] is None


@pytest.mark.parametrize("field", ["mg_seed", "shower_seed", "detector_seed", "lhe_sha256"])
def test_duplicate_streams_rejected(field):
    a, b = numerical_replica(2,1,1), numerical_replica(6,1,2)
    b[field] = a[field]
    with pytest.raises(ValueError, match="duplicate replica"):
        pooling.combine([a,b])


def test_additive_processes_rejected():
    a, b = numerical_replica(2,1,1), numerical_replica(6,1,2)
    b["physics"] = {"model":"other"}
    with pytest.raises(ValueError, match="different physics"):
        pooling.combine([a,b])


@pytest.mark.parametrize("exposure", [True, 0, -1, 1.5])
def test_invalid_original_exposure_rejected(exposure):
    a, b = numerical_replica(2,1,1), numerical_replica(6,1,2)
    a["original_generated_events"] = exposure
    with pytest.raises(ValueError, match="generated exposure"):
        pooling.combine([a,b])


@pytest.mark.parametrize("weights", [[1,-1], [1,0], [1,1.01], [float("nan")], []])
def test_nonuniform_signed_missing_weights_rejected(weights):
    with pytest.raises(ValueError):
        pooling.uniform_positive(weights, "test")


def test_unresolved_seed_and_tcl_include_rejected(tmp_path):
    shower = tmp_path/"shower.cfg"; shower.write_text("Random:setSeed = on\nRandom:seed = 0\n")
    with pytest.raises(ValueError, match="shower seed"):
        pooling.shower_physics(shower)
    detector = tmp_path/"detector.tcl"; detector.write_text("set RandomSeed 1\nsource other.tcl\n")
    with pytest.raises(ValueError, match="transitive source"):
        pooling.detector_physics(detector)


@pytest.fixture
def native_replicas(tmp_path):
    uproot = pytest.importorskip("uproot")
    ak = pytest.importorskip("awkward")
    converter = tmp_path/"converter.py"; converter.write_text("# synthetic converter identity, never executed\n")
    plans = []
    for index, (n, selected, xs) in enumerate([(2,1,1.), (6,2,2.)]):
        root = tmp_path/f"run{index}"; cards=root/"inputs/cards"; cards.mkdir(parents=True)
        output=root/"output"; output.mkdir(); (root/"logs").mkdir()
        seed = index+10
        (cards/"process.dat").write_text("import model MSSM_SLHA2\ngenerate p p > el+ el-\n")
        (cards/"param.dat").write_text("Block MASS\n 1000011 150\n 1000022 140\nDECAY 1000011 1\n 1 2 1000022 11\nDECAY 1000022 0\n")
        (cards/"run.dat").write_text(f"{n} = nevents\n{seed} = iseed\n0 = ickkw\nFalse = use_syst\n'cteq6l1' = pdlabel\n6500 = ebeam1\n6500 = ebeam2\n")
        (cards/"shower.cfg").write_text(f"Beams:frameType = 4\nBeams:LHEF = generated.lhe\nRandom:setSeed = on\nRandom:seed = {100+index}\n")
        (cards/"detector.tcl").write_text(f"set RandomSeed {1000+index}\n# synthetic detector\n")
        config=root/"config.toml"
        config.write_text(f'''[madgraph.run]
nevents = {n}
seed = {seed}
ecms = 13000
[analysis]
lumi = 139000
kfactor = 1.0
[ravel.native]
model = "slepton-bino"
compressed_signal_model = "full"
[ravel.native.inputs]
process_card = "inputs/cards/process.dat"
''')
        lhe=output/"unweighted_events.lhe"
        body=f"<LesHouchesEvents>\n# independent fixture seed {seed}\n<init>\n2212 2212 6500 6500 0 0 0 0 3 1\n{xs} .01 1 1\n</init>\n"
        body += "<event>\n1 1 1.0 1 1 1\n1000022 1 0 0 0 0 0 0 0 140 140 0 9\n</event>\n"*n
        body += "</LesHouchesEvents>\n"; lhe.write_text(body)
        compressed=output/"unweighted_events.lhe.gz"
        with gzip.open(compressed,"wt") as stream: stream.write(body)
        mglog=root/"logs/madgraph.log"; mglog.write_text(f"Cross-section : {xs} pb\n")
        showerlog=root/"logs/pythia.log"; showerlog.write_text(f"pythia_shower: wrote {n} events; sigma = {xs/1e9} mb\n")
        norm=output/"normalization.json"; write_json(norm,resolve_normalization(lhe,mglog,showerlog,1.,n))
        detector=output/"delphes.root"
        with uproot.recreate(detector) as stream:
            stream.mktree("Delphes", {"Event.Weight": "var * float64"})
            stream["Delphes"].extend({"Event.Weight":ak.Array([[1.]]*n)})
        converted=output/"Delphes2SA.root"; events=np.arange(n,dtype=np.int64)*3+100
        weights=np.full(n,xs/n)
        with uproot.recreate(converted) as stream: stream["ntuple"]={"Event":events,"mcWeights":ak.Array([[w] for w in weights])}
        conversion=reconcile_weights(np.ones(n),weights,xs)
        conversion.update(schema_version=1,luminosity_pb_inverse=139000.,generation_reconciled=True,
                          sources=[fingerprint(detector),fingerprint(converter)],output=fingerprint(converted),normalization=fingerprint(norm))
        conversion_path=Path(str(converted)+".normalization.json"); write_json(conversion_path,conversion)
        analysis=output/"EwkCompressed2018.root"
        arrays={"Event":events[:selected],"eventWeight":weights[:selected],"isee":np.ones(selected,dtype=np.int32),"ismm":np.zeros(selected,dtype=np.int32)}
        arrays.update({name:weights[:selected].copy() if name=="SR_S_high_eMT2a" else np.zeros(selected) for name in sr_order()+cr_order()})
        with uproot.recreate(analysis) as stream: stream["ntuple"]=arrays
        dummy={}
        for name in ["prepared","lhe_check","shower"]:
            path=output/(name+".json");write_json(path,{"synthetic_fixture":True});dummy[name]=path
        stage_outputs={"prepare":[dummy["prepared"]],"madgraph":[compressed],"unpack_lhe":[lhe],"lhe_check":[dummy["lhe_check"]],"pythia":[dummy["shower"]],"normalization":[norm],"delphes":[detector],"analysis":[converted,conversion_path],"simpleanalysis":[analysis]}
        inputs={key:str(cards/name) for key,name in [("process_card","process.dat"),("param_card","param.dat"),("run_card","run.dat"),("shower_card","shower.cfg"),("delphes_card","detector.tcl")]}
        all_sources=[config,*map(Path,inputs.values()),converter]
        planpath=root/"inputs/native_execution_plan.json"
        stages=[];previous=[]
        for name,outputs in stage_outputs.items():
            stages.append({"stage":name,"command":[sys.executable,"-c","# synthetic receipt fixture"],
                "inputs":[str(p) for p in [*all_sources,planpath,mglog,showerlog]],"outputs":list(map(str,outputs)),"depends_on":previous})
            previous=[name]
        plan={"schema_version":1,"rundir":str(root),"plan_path":str(planpath),"config":str(config),"sources":[fingerprint(p) for p in all_sources],"inputs":inputs,"stages":stages,
            "capability":{"preparation":"explicit-cards","routine":"EwkCompressed2018","model":"slepton-bino"},"compressed_signal_model":"full","nevents":n,"seed":seed,"kfactor":1.,"ecms_gev":13000.,"expected_masses_gev":{"1000011":150.,"1000022":140.}}
        plan["plan_sha256"]=plan_hash(plan);write_json(planpath,plan)
        records={}
        for stage in stages:
            name=stage["stage"]
            spec={k:stage[k] for k in ["command","inputs","outputs"]}
            spec.update(cwd=str(root),runtime={"historical_interpreter":"synthetic old runtime; reader may differ"},input_snapshot=snapshot(root,stage["inputs"]),parents={p:records[p]["receipt_sha256"] for p in stage["depends_on"]})
            spec["fingerprint"]=digest(spec);spec["output_snapshot"]=snapshot(root,stage["outputs"],outputs=True)
            spec["receipt_sha256"]=digest({k:spec[k] for k in ["fingerprint","output_snapshot"]})
            spec.update(status="succeeded",attempt_record=f"logs/execution/{name}/fixture/record.json")
            records[name]=spec;write_json(root/spec["attempt_record"],spec)
        write_json(root/"execution_state.json",{"schema_version":1,"revision":len(records),"stages":records})
        plans.append({"plan":fingerprint(planpath)})
    manifest=tmp_path/"replicas.json";write_json(manifest,{"schema_version":1,"input_combination":"pool-independent-replicas","replicas":plans})
    return manifest


def test_real_root_source_receipts_and_moment_roundtrip(native_replicas,tmp_path):
    result=pooling.pool(native_replicas,tmp_path/"pooled")
    assert result["original_generated_events"]==8
    assert result["retained_analysis_rows"]==3
    assert result["normalized_cross_section_pb"]==1.75
    assert result["moments"]["SR_S_high_eMT2a"]["sumw_pb"]==.625
    assert result["moments"]["SR_S_high_eMT2a"]["sumw2_pb2"]==.140625
    assert result["output_roundtrip_verified"] is True
    assert fingerprint(tmp_path/"pooled/pooled.root")["sha256"]==result["output"]["sha256"]
    assert all(fingerprint(s["path"])["sha256"]==s["sha256"] for s in result["source_files"])
    assert any(s["path"].endswith("logs/madgraph.log") for s in result["source_files"])
    assert any(s["path"].endswith("unweighted_events.lhe.gz") for s in result["source_files"])
    assert not any(s["path"].endswith("execution_state.json") for s in result["source_files"])
    from ravel.physics.sa2json_native import build_signal_patch
    workspace={"version":"1.0.0","channels":[{"name":"A","samples":[{"name":"bkg","data":[2.],"modifiers":[]}]}],
               "observations":[{"name":"A","data":[2]}],"measurements":[{"name":"Measurement","config":{"poi":"mu","parameters":[]}}]}
    patch, signal=build_signal_patch(workspace,[pooling.scalar_arrays(tmp_path/"pooled/pooled.root")],name="pooled_signal",
        mapping={"A":{"region":"SR_S_high_eMT2a","flavour":"isee"}},lumi=1000,mc_stat="shapesys")
    assert patch[0]["value"]["data"]==[625.]
    assert signal["channels"][0]["mc_stat_error"]==375.


def test_existing_output_preserved(native_replicas,tmp_path):
    out=tmp_path/"existing";out.mkdir();(out/"sentinel").write_text("keep")
    with pytest.raises(ValueError,match="new nonsymlink"):
        pooling.pool(native_replicas,out)
    assert (out/"sentinel").read_text()=="keep"


def test_tampered_root_rejected_by_receipt(native_replicas,tmp_path):
    path=tmp_path/"run0/output/EwkCompressed2018.root"
    with path.open("ab") as stream:stream.write(b"tamper")
    with pytest.raises(ValueError,match="artifacts changed"):
        pooling.pool(native_replicas,tmp_path/"pool")
    assert not (tmp_path/"pool").exists()


def test_missing_receipt_rejected(native_replicas,tmp_path):
    path=tmp_path/"run0/execution_state.json";state=json.loads(path.read_text());state["stages"].pop("pythia");write_json(path,state)
    with pytest.raises(ValueError,match="missing successful"):
        pooling.pool(native_replicas,tmp_path/"pool")


def test_unpinned_and_additive_manifest_rejected(native_replicas,tmp_path):
    manifest=json.loads(native_replicas.read_text());manifest["input_combination"]="sum-independent-components";write_json(native_replicas,manifest)
    with pytest.raises(ValueError,match="explicit independent-replica"):
        pooling.pool(native_replicas,tmp_path/"pool")


def test_changed_card_rejected_before_root_pooling(native_replicas,tmp_path):
    path=tmp_path/"run0/inputs/cards/run.dat";path.write_text(path.read_text()+"70 = ptj\n")
    with pytest.raises(ValueError,match="source pin changed"):
        pooling.pool(native_replicas,tmp_path/"pool")


def test_predecessor_output_not_allowed(native_replicas,tmp_path):
    with pytest.raises(ValueError,match="predecessor run"):
        pooling.pool(native_replicas,tmp_path/"run0/new-pool")


def test_manifest_write_failure_does_not_publish_success_root(native_replicas,tmp_path,monkeypatch):
    original=Path.open
    def fail_manifest(path,*args,**kwargs):
        if path.name=="pooling.json":
            raise OSError("simulated manifest write failure")
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,"open",fail_manifest)
    with pytest.raises(OSError,match="simulated manifest"):
        pooling.pool(native_replicas,tmp_path/"failed-pool")
    assert not (tmp_path/"failed-pool/pooled.root").exists()
    assert json.loads((tmp_path/"failed-pool/FAILED.json").read_text())["status"]=="failed"


def test_cli_emits_coherent_pair(native_replicas,tmp_path):
    import subprocess
    out=tmp_path/"cli-pool"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result=subprocess.run(module_command("ravel.physics.pool_replicas","--manifest",str(native_replicas),"--out",str(out),python=[sys.executable,"-B"]),capture_output=True,text=True,env=env,cwd=tmp_path)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)["original_generated_events"]==8
    receipt=json.loads((out/"pooling.json").read_text())
    assert receipt["output"]["sha256"]==fingerprint(out/"pooled.root")["sha256"]


def test_ancestor_source_change_during_write_fails_closed(native_replicas,tmp_path,monkeypatch):
    original=pooling.scalar_arrays
    def change_ancestor(path):
        result=original(path)
        if Path(path).name=="pooled.root.partial":
            source=tmp_path/"run0/logs/madgraph.log"
            source.write_text(source.read_text()+"changed during pooled write\n")
        return result
    monkeypatch.setattr(pooling,"scalar_arrays",change_ancestor)
    with pytest.raises(ValueError,match="source changed while writing"):
        pooling.pool(native_replicas,tmp_path/"failed-pool")
    assert not (tmp_path/"failed-pool/pooled.root").exists()
