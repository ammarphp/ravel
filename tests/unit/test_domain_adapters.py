"""Independent analytic controls for bounded domain operations; no event generation."""
import copy
import json
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ravel.physics import domain_adapters as da


def write(tmp_path, filename, data):
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return str(path)


def execute(tmp_path, spec, name="out"):
    result = da.run(spec, tmp_path, tmp_path/name)
    assert json.loads((tmp_path/name/"domain-result.json").read_text()) == result
    assert result["physics_validated"] is False
    assert result["limitations"]
    return result


@pytest.fixture
def eft(tmp_path):
    def value(a,b):
        return [10+2*a-4*b+3*a*a+5*a*b+6*b*b, -1+3*a-2*b*b]
    points = [(0,0),(1,0),(-1,0),(0,1),(0,-1),(1,1)]
    data = {"coefficient_units":{"a":"TeV^-2","b":"TeV^-2"}, "prediction_unit":"pb", "bins":["one","two"],
            "samples":[{"point":{"a":a,"b":b},"values":value(a,b)} for a,b in points],
            "controls":[{"point":{"a":.5,"b":-.5},"values":value(.5,-.5)}],"source":"analytic polynomial test control"}
    spec = {"domain":"eft", "config":{"basis_file":write(tmp_path,"basis.json",data), "coefficients":["a","b"],
            "coefficient_units":data["coefficient_units"], "validity":{"a":[-1,1],"b":[-1,1]},
            "queries":[{"a":.5,"b":-.5}], "atol":1e-10,"rtol":1e-10}}
    return spec, data


def test_eft_reconstructs_all_interference_and_preserves_negative_bins(tmp_path, eft):
    spec, _ = eft
    result = execute(tmp_path,spec)
    details = result["details"]
    prediction = details["predictions"][0]
    for actual, expected in zip(details["coefficients_by_term"], [[10,-1],[2,3],[-4,0],[3,0],[5,0],[6,-2]]):
        assert actual == pytest.approx(expected, abs=1e-12)
    assert prediction["total"] == pytest.approx([14,0], abs=1e-12)
    spec["config"]["queries"] = [{"a":0,"b":0}]
    signed = execute(tmp_path,spec,"signed")["details"]["predictions"][0]
    assert signed["total"][1] == pytest.approx(-1)
    assert signed["nonnegative_for_poisson"] is False
    assert details["clipping_applied"] is False


@pytest.mark.parametrize("defect", ["rank","duplicate","control-reused","control-fail","unit","unknown","extrapolation","nan"])
def test_eft_rejects_or_retains_defects(tmp_path, eft, defect):
    spec, data = eft
    if defect == "rank": data["samples"] = data["samples"][:-1]
    elif defect == "duplicate": data["samples"].append(data["samples"][0])
    elif defect == "control-reused": data["controls"] = [data["samples"][0]]
    elif defect == "control-fail": data["controls"][0]["values"][0] += 1
    elif defect == "unit": data["coefficient_units"]["a"]="GeV^-2"; spec["config"]["coefficient_units"]={"a":"TeV^-2","b":"TeV^-2"}
    elif defect == "unknown": spec["config"]["clip_negative"] = True
    elif defect == "extrapolation": spec["config"]["queries"][0]["a"] = 2
    elif defect == "nan": data["samples"][0]["values"][0] = float("nan")
    write(tmp_path,"basis.json",data)
    if defect == "control-fail":
        result = execute(tmp_path,spec)
        assert result["status"] == "failed"
        assert not result["details"]["control_passed"]
    else:
        with pytest.raises(ValueError): execute(tmp_path,spec)


@pytest.fixture
def ufo(tmp_path):
    model = tmp_path/"model"
    model.mkdir()
    content = {
        "parameters.py":"""mass = Parameter(name='mass', nature='external', value=100., lhablock='MASS', lhacode=[100])
width = Parameter(name='width', nature='external', value=1., lhablock='DECAY', lhacode=[100])
""",
        "particles.py":"particle = Particle(name='X', pdg_code=100, mass=Param.mass, width=Param.width)\n",
        "couplings.py":"coupling = Coupling(name='gc', value='2*mass', order={'NP':1})\n",
        "coupling_orders.py":"NP = CouplingOrder(name='NP', expansion_order=2, hierarchy=1)\n",
        "vertices.py":"v = Vertex(name='V1', particles=[P.X], color=['1'], lorentz=[L.L1], couplings={(0,0):C.gc})\n",
        "lorentz.py":"# supplied symbolic Lorentz structures\n", "object_library.py":"# fixture, never imported\n",
        "__init__.py":f"raise RuntimeError('UFO must never be imported')\nopen({str(tmp_path/'SENTINEL')!r}, 'w').write('bad')\n",
    }
    for file,text in content.items(): (model/file).write_text(text)
    bench = {"model_parameters":{"mass":100}, "coupling_orders":{"NP":2},
             "checks":[{"name":"width control", "actual":1, "reference":1, "unit":"GeV", "atol":1e-9,"rtol":0,"source":"analytic fixture"}]}
    spec = {"domain":"ufo", "config":{"model_dir":str(model),"parameters":{"mass":100},"orders":{"NP":2},
                                    "benchmarks_file":write(tmp_path,"bench.json",bench)}}
    return spec, bench, model


def test_ufo_is_static_and_preserves_benchmark_scope(tmp_path,ufo):
    spec, _, _ = ufo
    result = execute(tmp_path,spec)
    assert result["status"] == "passed"
    assert result["details"]["counts"]["Particle"] == 1
    assert not (tmp_path/"SENTINEL").exists()
    assert len(result["inputs"]) == 9


@pytest.mark.parametrize("defect", ["missing-file","bad-order","missing-parameter","duplicate-lha","wrong-recipe","failed-benchmark","symlink"])
def test_ufo_defects(tmp_path,ufo,defect):
    spec, bench, model = ufo
    if defect == "missing-file": (model/"lorentz.py").unlink()
    elif defect == "bad-order": (model/"couplings.py").write_text("C=Coupling(name='C',value='1',order={'UNKNOWN':1})")
    elif defect == "missing-parameter": spec["config"]["parameters"]={"UNKNOWN":1}
    elif defect == "duplicate-lha":
        with (model/"parameters.py").open("a") as handle:
            handle.write("q = Parameter(name='q', nature='external', value=1, lhablock='mass', lhacode=[100])\n")
    elif defect == "wrong-recipe": bench["model_parameters"]["mass"]=200; write(tmp_path,"bench.json",bench)
    elif defect == "failed-benchmark": bench["checks"][0]["actual"]=2; write(tmp_path,"bench.json",bench)
    elif defect == "symlink": (model/"hidden.py").symlink_to(tmp_path/"bench.json")
    if defect == "failed-benchmark": assert execute(tmp_path,spec)["status"] == "failed"
    else:
        with pytest.raises(ValueError): execute(tmp_path,spec)


def llp(tmp_path, events, operation="decay-probability", **config):
    return {"domain":"llp","config":{"operation":operation,"events_file":write(tmp_path,"llp.json",events),
            "target_ctau":{"value":10,"unit":"mm"}, **config}}


def momentum(px=100,py=0,pz=0,mass=100):
    return {"px_GeV":px,"py_GeV":py,"pz_GeV":pz,"mass_GeV":mass}


def event(particles, weight=1, ident="one"):
    return {"event_id":ident,"weight":weight,"particles":particles}


def test_llp_cylinder_exact_limits_and_signed_weights(tmp_path):
    events = [event([momentum()],2),event([momentum(px=0,pz=100)],-3,"axis"),event([momentum(px=0,pz=0)],1,"rest")]
    spec = llp(tmp_path,events, geometry={"r_min_mm":10,"r_max_mm":20,"z_half_mm":30}, combination="all")
    result = execute(tmp_path,spec)["details"]
    exact = math.exp(-1)-math.exp(-2)
    assert result["events"][0]["factor"] == pytest.approx(exact)
    assert result["events"][1]["factor"] == 0
    assert result["events"][2]["factor"] == 0
    assert result["sumw"] == pytest.approx(2*exact)
    assert result["sumw2"] == pytest.approx((2*exact)**2)
    spec["config"]["geometry"]["r_min_mm"]=0
    revised = execute(tmp_path,spec,"revised")["details"]["events"]
    assert revised[1]["factor"] == pytest.approx(1-math.exp(-3))
    assert revised[2]["factor"] == 1


def test_llp_joint_probability_boost_and_length_units(tmp_path):
    spec=llp(tmp_path,[event([momentum(),momentum()])], geometry={"r_min_mm":0,"r_max_mm":10,"z_half_mm":100},combination="at-least-one")
    spec["config"]["target_ctau"]={"value":1,"unit":"cm"}
    assert execute(tmp_path,spec)["details"]["events"][0]["factor"] == pytest.approx(1-math.exp(-2))
    spec["config"]["combination"]="all"
    assert execute(tmp_path,spec,"all")["details"]["events"][0]["factor"] == pytest.approx((1-math.exp(-1))**2)


def test_llp_right_censoring_uses_survival_not_density_ratio(tmp_path):
    spec=llp(tmp_path,[event([{"proper_length_mm":5,"right_censored":False}],2),
                       event([{"proper_length_mm":5,"right_censored":True}],-1,"censored")],
             "reweight",source_ctau={"value":20,"unit":"mm"})
    result=execute(tmp_path,spec)["details"]
    assert result["events"][0]["factor"] == pytest.approx(2*math.exp(-.25))
    assert result["events"][1]["factor"] == pytest.approx(math.exp(-.25))
    assert result["sumw"] == pytest.approx(3*math.exp(-.25))


@pytest.mark.parametrize("defect", ["seconds","zero-mass","duplicate-event","empty-particles","bad-censor","unstable","extra"])
def test_llp_defects(tmp_path, defect):
    spec=llp(tmp_path,[event([momentum()])],geometry={"r_min_mm":0,"r_max_mm":10,"z_half_mm":100},combination="all")
    if defect=="seconds":spec["config"]["target_ctau"]["unit"]="s"
    elif defect=="zero-mass":write(tmp_path,"llp.json",[event([momentum(mass=0)])])
    elif defect=="duplicate-event":write(tmp_path,"llp.json",[event([momentum()]),event([momentum()])])
    elif defect=="empty-particles":write(tmp_path,"llp.json",[event([])])
    elif defect=="extra":spec["config"]["source_ctau"]={"value":10,"unit":"mm"}
    else:
        spec=llp(tmp_path,[event([{"proper_length_mm":100000 if defect=="unstable" else 5,
                                 "right_censored":"false" if defect=="bad-censor" else False}])],
                 "reweight", source_ctau={"value":1,"unit":"mm"})
    with pytest.raises(ValueError):execute(tmp_path,spec)


def domain_spec(tmp_path,family,data):
    return {"domain":"applicability","config":{"family":family,"data_file":write(tmp_path,"data.json",data)}}


def neutrino_data():
    return {"flavor_pdg":14,"target":"tungsten","target_basis":"nucleon","n_targets":1e30,
            "flux_unit":"cm^-2/bin","cross_section_unit":"cm^2/nucleon","flux_exposure":"integrated",
            "cross_section_averaging":"flux-weighted-per-bin","source":"analytic control",
            "bins":[{"energy_low_GeV":10,"energy_high_GeV":20,"flux":1e7,"cross_section":1e-36,"efficiency":.5}]}


def test_neutrino_flux_fold_does_not_multiply_bin_width_twice(tmp_path):
    result=execute(tmp_path,domain_spec(tmp_path,"neutrino",neutrino_data()))
    assert result["details"]["expected_events"] == pytest.approx(5)


@pytest.mark.parametrize("key,value", [("cross_section_unit","cm^2/nucleus"),("flux_unit","cm^-2/GeV"),
                                      ("flux_exposure","per-second"),("cross_section_averaging","bin-center"),
                                      ("flavor_pdg",13),("n_targets",-1)])
def test_neutrino_semantic_mismatch(tmp_path,key,value):
    data=neutrino_data();data[key]=value
    with pytest.raises(ValueError):execute(tmp_path,domain_spec(tmp_path,"neutrino",data))


def test_nuclear_density_unequal_bins_and_centrality(tmp_path):
    data={"beam_mass_numbers":[208,208],"sqrt_sNN_GeV":5020,"centrality_percent":[0,10],
          "centrality_definition":"supplied centrality estimator", "event_exposure":100,"observable_unit":"GeV",
          "source":"analytic control","bins":[{"low":0,"high":1,"sumw":100,"sumw2":100},
                                                  {"low":1,"high":3,"sumw":100,"sumw2":100}]}
    result=execute(tmp_path,domain_spec(tmp_path,"heavy-ion",data))["details"]["bins"]
    assert [r["per_event_density"] for r in result]==[1,.5]
    assert [r["conditional_variance"] for r in result]==[.01,.0025]
    data["beam_mass_numbers"]=[1,1]
    with pytest.raises(ValueError):execute(tmp_path,domain_spec(tmp_path,"heavy-ion",data),"pp")


def test_forward_vacuum_aperture_boundary_and_wrong_direction(tmp_path):
    row={"event_id":"one","weight":-2,"x_mm":0,"y_mm":0,"z_mm":0,"px_GeV":1,"py_GeV":0,"pz_GeV":100,"charge":0}
    data={"plane_z_mm":1000,"radius_mm":10,"transport":"neutral-straight-line-vacuum","source":"analytic control", "events":[row,{**row,"event_id":"backwards","pz_GeV":-100}]}
    result=execute(tmp_path,domain_spec(tmp_path,"forward",data))["details"]
    assert result["selected_sumw"]==-2
    assert result["selected_sumw2"]==4
    assert result["events"][0]["selected"] is True
    assert result["events"][1]["selected"] is False
    data["events"][0]["charge"]=1
    with pytest.raises(ValueError):execute(tmp_path,domain_spec(tmp_path,"forward",data),"charged")


def classifier_fixture(tmp_path):
    onnx=pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import helper, TensorProto
    model=helper.make_model(helper.make_graph([helper.make_node("Mul",["features","weights"],["weighted"]),
                          helper.make_node("ReduceSum",["weighted"],["score"],axes=[1],keepdims=0)],
                          "analytic-sum",[helper.make_tensor_value_info("features",TensorProto.FLOAT,[None,2])],
                          [helper.make_tensor_value_info("score",TensorProto.FLOAT,[None])],
                          [helper.make_tensor("weights",TensorProto.FLOAT,[2],[2.,1.])]),
                          opset_imports=[helper.make_opsetid("",11)])
    model.ir_version=8
    onnx.save(model,str(tmp_path/"model.onnx"))
    rows={"units":{"a":"GeV","b":"1"}, "events":[{"event_id":"one","weight":-2,"values":{"b":.5,"a":3}}]}
    spec={"domain":"classifier","config":{"model_file":str(tmp_path/"model.onnx"),
          "events_file":write(tmp_path,"features.json",rows),
          "controls_file":write(tmp_path,"control.json",{**rows,"expected_scores":[2.5]}),
          "features":[{"name":"a","unit":"GeV","mean":1,"scale":2},{"name":"b","unit":"1","mean":0,"scale":1}],
          "dtype":"float32","input_name":"features","output_name":"score","score_index":None,
          "threshold":2.5,"comparison":">=","score_range":[-10,10],"atol":1e-6,"rtol":1e-6}}
    return spec, rows


def test_actual_onnx_order_normalization_and_threshold_boundary(tmp_path):
    spec,_=classifier_fixture(tmp_path)
    result=execute(tmp_path,spec)["details"]
    assert result["checks_passed"]
    assert result["events"][0]["score"]==2.5
    assert result["selected_sumw"]==-2
    spec["config"]["comparison"]=">"
    assert execute(tmp_path,spec,"strict")["details"]["selected_sumw"]==0


@pytest.mark.parametrize("defect", ["order","unit","dtype","missing-feature","nan","score-index","failed-control","external-data"])
def test_actual_onnx_rejects_or_retains_defects(tmp_path,defect):
    spec,rows=classifier_fixture(tmp_path)
    if defect=="order":
        spec["config"]["features"].reverse()
    elif defect=="unit":rows["units"]["a"]="MeV";write(tmp_path,"features.json",rows)
    elif defect=="dtype":spec["config"]["dtype"]="float64"
    elif defect=="missing-feature":del rows["events"][0]["values"]["b"];write(tmp_path,"features.json",rows)
    elif defect=="nan":rows["events"][0]["values"]["a"]=float("nan");write(tmp_path,"features.json",rows)
    elif defect=="score-index":spec["config"]["score_index"]=0
    elif defect=="failed-control":write(tmp_path,"control.json",{**rows,"expected_scores":[1]})
    else:
        import onnx
        model=onnx.load(tmp_path/"model.onnx")
        tensor=model.graph.initializer.add();tensor.name="external";tensor.data_type=onnx.TensorProto.FLOAT;tensor.dims.append(1)
        tensor.data_location=onnx.TensorProto.EXTERNAL
        entry=tensor.external_data.add();entry.key="location";entry.value="outside.bin"
        (tmp_path/"model.onnx").write_bytes(model.SerializeToString())
    if defect in {"order","failed-control"}:assert execute(tmp_path,spec)["status"]=="failed"
    else:
        with pytest.raises(ValueError):execute(tmp_path,spec)


def test_input_mutation_during_execution_and_output_overwrite_fail(tmp_path,eft,monkeypatch):
    spec,_=eft
    execute(tmp_path,spec)
    with pytest.raises(FileExistsError):execute(tmp_path,spec)
    original=da._eft
    def mutate(c,base):
        result=original(c,base)
        with Path(c["basis_file"]).open("a") as handle:handle.write(" ")
        return result
    monkeypatch.setattr(da,"_eft",mutate)
    with pytest.raises(ValueError,match="changed"):execute(tmp_path,spec,"mutated")
    assert not (tmp_path/"mutated"/"domain-result.json").exists()


def test_duplicate_json_keys_and_parent_symlink_fail(tmp_path,eft):
    spec,_=eft
    (tmp_path/"basis.json").write_text('{"source":"one","source":"two"}')
    with pytest.raises(ValueError,match="duplicate JSON"):execute(tmp_path,spec)
    (tmp_path/"link").symlink_to(tmp_path,target_is_directory=True)
    spec["config"]["basis_file"]=str(tmp_path/"link"/"basis.json")
    with pytest.raises(ValueError,match="symlink"):da.inputs(spec,tmp_path)


def efficiency_map_fixture(tmp_path):
    """Small standalone fixture also usable by the supervised CLI control harness."""
    grid = {"map_id":"analytic-two-point-v1", "topology":"supplied-neutral-pair",
            "coordinate_units":{"mass":"GeV"}, "response_kind":"event-selection-probability",
            "source":"analytic control; not detector evidence",
            "nodes":[{"node_id":"m100","coordinates":{"mass":100},"efficiency":.5},
                     {"node_id":"m200","coordinates":{"mass":200},"efficiency":.25}],
            "uncertainty":{"kind":"absolute-probability-covariance", "node_ids":["m100","m200"],
                           "covariance":[[.01,.005],[.005,.04]],"source":"supplied analytic covariance"}}
    data = {"map_id":grid["map_id"], "topology":grid["topology"], "coordinate_units":grid["coordinate_units"],
            "node_semantics":"alternative-model-points", "weight_unit":"events", "source":"signed analytic weights",
            "events":[{"event_id":"a","group_id":"g1","node_id":"m100","coordinates":{"mass":100},"weight":3},
                      {"event_id":"b","group_id":"g1","node_id":"m100","coordinates":{"mass":100},"weight":-1},
                      {"event_id":"c","group_id":"g1","node_id":"m200","coordinates":{"mass":200},"weight":-2},
                      {"event_id":"d","group_id":"g2","node_id":"m200","coordinates":{"mass":200},"weight":3}]}
    task = {"domain":"efficiency-map","config":{"map_file":write(tmp_path,"map.json",grid),
                                                  "events_file":write(tmp_path,"map-events.json",data)}}
    return task, grid, data


def test_efficiency_map_exact_nodes_grouped_mc_and_response_covariance(tmp_path):
    task,_,_=efficiency_map_fixture(tmp_path)
    result=execute(tmp_path,task)["details"]
    assert result["yield_by_node"]==[1,.25]
    assert result["input_group_second_moments"]==[[4,-4],[-4,13]]
    assert result["conditional_mc_covariance"]==[[1,-.5],[-.5,.8125]]
    assert result["supplied_response_covariance"]==[[.04,.01],[.01,.04]]
    assert result["total_yield"] is None
    assert result["conditional_mc_total_variance"] is None
    assert result["supplied_response_total_variance"] is None
    assert not result["interpolation_applied"]
    assert not result["clipping_applied"]


def test_efficiency_map_exclusive_kinematics_total_and_signed_preservation(tmp_path):
    task,grid,data=efficiency_map_fixture(tmp_path)
    # These coordinates now describe disjoint kinematic event subsets, not masses.
    grid["coordinate_units"]={"pt":"GeV"}; data["coordinate_units"]={"pt":"GeV"}
    data["node_semantics"]="event-kinematics"
    for row in grid["nodes"]+data["events"]:
        row["coordinates"]={"pt":row["coordinates"]["mass"]}
    write(tmp_path,"map.json",grid);write(tmp_path,"map-events.json",data)
    result=execute(tmp_path,task)["details"]
    assert result["total_yield"]==1.25
    assert result["conditional_mc_total_variance"]==.8125
    assert result["supplied_response_total_variance"]==pytest.approx(.10)
    data["events"][-1]["weight"]=1
    write(tmp_path,"map-events.json",data)
    signed=execute(tmp_path,task,"signed")["details"]
    assert signed["yield_by_node"]==[1,-.25]
    assert signed["nonnegative_for_poisson"] is False


@pytest.mark.parametrize("defect", ["topology","units","map-identity","unknown-node","between-nodes","duplicate-node",
                                     "duplicate-coordinate","percent","negative-efficiency","per-object","order",
                                     "indefinite","asymmetric","nan","duplicate-event","missing-group","unknown-semantics"])
def test_efficiency_map_rejects_ambiguous_or_unphysical_transport(tmp_path,defect):
    task,grid,data=efficiency_map_fixture(tmp_path)
    if defect=="topology":data["topology"]="different-decay-chain"
    elif defect=="units":data["coordinate_units"]={"mass":"TeV"}
    elif defect=="map-identity":data["map_id"]="different-map"
    elif defect=="unknown-node":data["events"][0]["node_id"]="uncovered"
    elif defect=="between-nodes":data["events"][0]["coordinates"]["mass"]=150
    elif defect=="duplicate-node":grid["nodes"][1]["node_id"]="m100"
    elif defect=="duplicate-coordinate":grid["nodes"][1]["coordinates"]["mass"]=100
    elif defect=="percent":grid["nodes"][0]["efficiency"]=50
    elif defect=="negative-efficiency":grid["nodes"][0]["efficiency"]=-.5
    elif defect=="per-object":grid["response_kind"]="per-object-efficiency"
    elif defect=="order":grid["uncertainty"]["node_ids"].reverse()
    elif defect=="indefinite":grid["uncertainty"]["covariance"]=[[.01,.03],[.03,.01]]
    elif defect=="asymmetric":grid["uncertainty"]["covariance"][0][1]=0
    elif defect=="nan":grid["uncertainty"]["covariance"][0][0]=float("nan")
    elif defect=="duplicate-event":data["events"][1]["event_id"]="a"
    elif defect=="missing-group":del data["events"][0]["group_id"]
    elif defect=="unknown-semantics":data["node_semantics"]="sum-hypotheses"
    write(tmp_path,"map.json",grid);write(tmp_path,"map-events.json",data)
    with pytest.raises(ValueError):execute(tmp_path,task)
