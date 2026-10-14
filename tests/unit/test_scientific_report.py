"""Useful report construction/revision controls; no native or model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from ravel.physics import quantities
from ravel.workflow import scientific_context as sc, scientific_report as report


def write(path, value):
    path.write_text(value if type(value) is str else json.dumps(value, allow_nan=False) + "\n")
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}


def selector(point, pointer="/scores"):
    return {"kind": "record", "pointer": pointer, "id_field": "point", "row_id": point, "field": "value"}


def fixture(base, rows=None):
    rows = rows or [{"point": "0", "value": -.225}, {"point": "1", "value": 0.0}]
    artifact = {"schema_version": 1, "basis": [write(base / "basis.txt", "Fixed source-nuisance scores; no fits.")],
        "tools": {"probe": write(base / "probe.json", {"scores": rows})},
        "contract": {"source_scope": "Synthetic fixed-point supplied report controls; zero native operations.",
            "tool_fields": [{"field": "scores", "type": {"type": "array", "items": {"type": "object", "properties": {
                "point": "string", "value": "number"}}, "max_items": 2},
                "source": {"kind": "direct", "tool_id": "probe", "pointer": "/scores"}}],
            "interpretation_fields": ["recommendation"], "unresolved_semantics": [], "max_artifact_bytes": 4096},
        "interpretation": {"recommendation": "Consider a future admitted API experiment."}}
    facts = [{"id": f"score{point}", "selector": selector(point), "quantity_id": None, "context_selector": None,
              "label": f"Raw score at point{point}", "unit": "1", "scope": "raw_nll_at_source_nuisance_values",
              "population": f"point{point} on the fixed supplied workspace", "limitations": ["Not a saved fit or optimum."]}
             for point in ("0", "1")]
    sections = [{"id": kind, "kind": kind, "caption": "Complete declared two-point population.",
                 "columns": ["Raw source-nuisance NLL"],
                 "rows": [{"id": "point" + point, "facts": ["score" + point]} for point in ("0", "1")]} for kind in ("table", "figure-data")]
    return {"schema_version": 1, "title": "Fixed-point diagnostic", "artifact_request": artifact,
            "context": None, "facts": facts, "sections": sections,
            "interpretation": ["A future study might test another API implementation; this is an unverified hypothesis."]}


def draft(base, request):
    return {"slots": report.compose(request, base_dir=base)["expected_slots"], "interpretation": ["Author interpretation remains unchanged."]}


def attach_context(base, request):
    source = base / "api.py"; source.write_text("def requested_api(data):\n    return data\n")
    context_request = {"schema_version": 1, "task_id": "report-scores", "task": "Deliver both supplied fixed scores.",
        "source_capsules": [], "api_documents": [{"id": "api", "pin": {"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
            "language": "python", "role": "api", "version": "Synthetic source-only control", "dependencies": []}],
        "queries": [{"id": "definition", "symbol": "requested_api", "mode": "definition", "documents": ["api"], "required": True}],
        "requested_quantities": [{"id": "scores", "artifact": "probe", "pointer": "/scores",
            "check": {"kind": "record-census", "id_field": "point", "expected_ids": ["0", "1"], "finite_fields": ["value"]},
            "meaning": "Complete supplied two-point population; no actual runtime consumption claim."}],
        "compatibility_groups": [{"id": "current", "artifacts": ["probe"], "carryover": False, "basis": "Current candidate only."}],
        "max_source_bytes": 128000, "max_context_bytes": 16000, "max_steps": 2}
    context = sc.compile_context(context_request, base)
    pin = request["artifact_request"]["tools"]["probe"]
    context = sc.apply_step(context, {"id": "attempt1", "outputs": {"probe": {"path": pin["path"], "sha256": pin["sha256"]}},
        "code_status": "failure", "actor_complete": False, "question": "Incidental stage error remains.",
        "next_experiment": {"hypothesis": "The failure is separate from supplied fixed quantities.", "change": "Inspect the logger only.",
            "measurement": "Preserve both current scores.", "if_supported": "Review the narrowly scoped evidence.", "if_not_supported": "Retain the error."}}, base)
    request["context"] = write(base / "context.json", context)
    for fact in request["facts"]:
        fact.update(quantity_id="scores", context_selector=selector(fact["selector"]["row_id"], ""))
    return context


def test_actual_text_table_and_plot_data_are_constructed_from_same_complete_facts(tmp_path):
    request = fixture(tmp_path)
    out = report.compose(request, base_dir=tmp_path)
    assert "| -0.225 |" in out["report_text"] and "| 0.0 |" in out["report_text"]
    assert out["plot_data"]["figure-data"]["rows"] == [[-.225], [0.0]]
    assert out["plot_data"]["figure-data"]["csv_text"].splitlines() == ["Raw source-nuisance NLL", "-0.225", "0.0"]
    assert "Not a saved fit or optimum" in out["report_text"]
    assert not out["scientific_acceptance"] and not out["plot_data"]["figure-data"]["image_pixels_verified"]


@pytest.mark.parametrize("field,value", [("value", .225), ("unit", "pb"), ("scope", "globally_profiled_fit"),
                                        ("population", "all possible parameter points"), ("fact_id", "score1")])
def test_wrong_value_unit_scope_population_or_fact_gets_concrete_applied_revision(tmp_path, field, value):
    request = fixture(tmp_path); original = draft(tmp_path, request)
    original["slots"]["table/point0/0"][field] = value
    revised = report.revise(request, original, base_dir=tmp_path)
    assert revised["inspection"]["changes"] == [{"slot": "table/point0/0", "field": field,
        "before": value, "after": report.compose(request, base_dir=tmp_path)["expected_slots"]["table/point0/0"][field],
        "reason": "draft differs from delivered value or declared quantity meaning"}]
    assert revised["inspection"]["complete_underlying_draft"] == original
    assert revised["revised_draft"]["slots"]["table/point0/0"] == revised["expected_slots"]["table/point0/0"]
    assert revised["revised_draft"]["interpretation"] == original["interpretation"]
    assert report.inspect_draft(request, revised["revised_draft"], base_dir=tmp_path)["declared_slots_match"]


def test_figure_table_disagreement_is_not_hidden_by_correct_prose_or_table(tmp_path):
    request = fixture(tmp_path); original = draft(tmp_path, request)
    original["slots"]["figure-data/point0/0"]["value"] = 1.0
    out = report.revise(request, original, base_dir=tmp_path)
    assert len(out["inspection"]["changes"]) == 1
    assert out["plot_data"]["figure-data"]["rows"][0] == [-.225]


def test_missing_population_slot_is_materialized_and_foreign_claim_remains_explicit(tmp_path):
    request = fixture(tmp_path); original = draft(tmp_path, request)
    original["slots"].pop("table/point1/0")
    original["slots"]["invented/global/0"] = {"value": 999}
    out = report.revise(request, original, base_dir=tmp_path)
    assert out["inspection"]["changes"][0]["field"] == "complete_slot"
    assert "table/point1/0" in out["revised_draft"]["slots"]
    assert out["unrequested_slots_still_unresolved"]
    assert out["inspection"]["unrequested_slots"] == {"invented/global/0": {"value": 999}}


def test_identity_selection_survives_reordered_data_without_point_swapping(tmp_path):
    request = fixture(tmp_path, [{"point": "1", "value": 0.0}, {"point": "0", "value": -.225}])
    assert report.compose(request, base_dir=tmp_path)["facts"][0]["value"] == -.225


@pytest.mark.parametrize("rows", [[{"point": "0", "value": 1.0}], [{"point": "0", "value": 1.0}, {"point": "0", "value": 2.0}]])
def test_missing_or_duplicate_declared_point_cannot_silently_replace_requested_population(tmp_path, rows):
    with pytest.raises(ValueError):
        report.compose(fixture(tmp_path, rows), base_dir=tmp_path)


def test_model_string_cannot_be_bound_as_numerical_report_fact(tmp_path):
    request = fixture(tmp_path); request["facts"][0]["selector"] = {"kind": "direct", "pointer": "/recommendation"}
    with pytest.raises(ValueError, match="model interpretation"):
        report.compose(request, base_dir=tmp_path)


def test_context_is_replayed_and_failed_code_can_still_supply_requested_quantities(tmp_path):
    request = fixture(tmp_path); context = attach_context(tmp_path, request)
    out = report.compose(request, base_dir=tmp_path)
    assert context["quantity_completion"] and context["steps"][0]["code_status_reported"] == "failure"
    assert out["context_sha256"] == context["context_sha256"]
    assert all(row["requested_quantity_checked"] == "scores" for row in out["facts"])
    assert {pin["path"] for pin in report.input_pins(request, base_dir=tmp_path)} >= {"probe.json", "context.json", str(tmp_path / "api.py")}


def test_changed_context_output_or_different_delivered_tool_value_refuses(tmp_path):
    request = fixture(tmp_path); attach_context(tmp_path, request)
    new = write(tmp_path / "other.json", {"scores": [{"point": "0", "value": 7.0}, {"point": "1", "value": 0.0}]})
    request["artifact_request"]["tools"]["probe"] = new
    with pytest.raises(ValueError, match="differs from current requested quantity"):
        report.compose(request, base_dir=tmp_path)
    (tmp_path / "probe.json").write_text('{}')
    with pytest.raises(ValueError, match="input bytes changed"):
        report.compose(request, base_dir=tmp_path)


def test_cached_context_numbers_cannot_be_forged_even_with_a_new_checksum(tmp_path):
    request = fixture(tmp_path); context = attach_context(tmp_path, request)
    context["measured_quantities"][0]["value"][0]["value"] = 7.0
    context.pop("context_sha256"); context["context_sha256"] = sc._digest(context)
    request["context"] = write(tmp_path / "context.json", context)
    with pytest.raises(ValueError, match="replayed requested quantities"):
        report.compose(request, base_dir=tmp_path)


def test_full_underlying_tool_provenance_and_unverified_interpretation_survive_revision(tmp_path):
    request = fixture(tmp_path); original = draft(tmp_path, request)
    original["interpretation"] = ["An unsupported global conclusion remains author prose, not a checked fact."]
    out = report.revise(request, original, base_dir=tmp_path)
    assert out["delivered_artifact"]["tool_provenance"]
    assert original["interpretation"][0] in out["report_text"]
    assert "Unverified interpretation" in out["report_text"]
    assert not out["free_prose_scientifically_checked"] and not out["interpretation_revised"]




def test_grouped_signed_quantity_table_does_not_replace_covariance_by_native_marginals(tmp_path):
    contract = {"schema_version": 1, "axes": [{"name": "x", "unit": "1"}],
        "bins": [{"id": "a", "low": [0], "high": [1]}, {"id": "b", "low": [1], "high": [2]}],
        "weight_names": ["nominal"], "input_weight_unit": "1", "representation": "integrated",
        "normalization": {"kind": "normalized", "scope": "all_events"}}
    records = [{"event_id": str(i), "group_id": str(i), "shard_id": "s", "weights": {"nominal": weight}, "fills": fills}
               for i, (weight, fills) in enumerate([(2, [[.5], [1.5]]), (-1, [[.5]]), (1, [[1.5]]), (0, [])])]
    data = quantities.calculate(contract, records)
    request = fixture(tmp_path)
    request["artifact_request"]["tools"]["probe"] = write(tmp_path / "grouped.json", data)
    fields = [{"field": name, "type": "number", "source": {"kind": "direct", "tool_id": "probe", "pointer": pointer}}
              for name, pointer in (("a", "/values/nominal/0"), ("b", "/values/nominal/1"), ("cross", "/covariance/0/1"))]
    request["artifact_request"]["contract"]["tool_fields"] = fields
    request["facts"] = [{"id": name, "selector": {"kind": "direct", "pointer": "/" + name}, "quantity_id": None, "context_selector": None,
        "label": name, "unit": "1", "scope": data["uncertainty_scope"], "population": "Four supplied signed/zero synthetic records, common denominator.",
        "limitations": data["limitations"]} for name in ("a", "b", "cross")]
    request["sections"] = [{"id": "moments", "kind": "table", "caption": "Normalized components and their shared-group covariance.",
                            "columns": ["a", "b", "Cov(a,b)"], "rows": [{"id": "nominal", "facts": ["a", "b", "cross"]}]}]
    original = draft(tmp_path, request); original["slots"]["moments/nominal/2"]["value"] = 0.0
    out = report.revise(request, original, base_dir=tmp_path)
    assert data["covariance"][0][1] != 0 and out["revised_draft"]["slots"]["moments/nominal/2"]["value"] == data["covariance"][0][1]
    assert "Poissonized independent-group" in out["report_text"]
    assert not out["tool_truth_verified"]


def test_partial_useful_report_exposes_complete_requested_quantity_census(tmp_path):
    request = fixture(tmp_path); context = attach_context(tmp_path, request)
    specification=deepcopy(context['request'])
    specification['requested_quantities'].append({'id':'missing-fit','artifact':'separate-fit','pointer':'/score','check':{'kind':'finite'},'meaning':'New requested fit not supplied by these fixed-point records.'})
    specification['compatibility_groups'].append({'id':'fit','artifacts':['separate-fit'],'carryover':False,'basis':'Separate requested artifact; no coupling inferred.'})
    current=sc.compile_context(specification,tmp_path)
    step=context['steps'][0]
    current=sc.apply_step(current,{'id':step['id'],'outputs':{row['id']:{'path':row['path'],'sha256':row['sha256']} for row in step['outputs']},'code_status':step['code_status_reported'],'actor_complete':step['actor_complete_reported'],'question':'Where is the independently requested fit artifact?', 'next_experiment':{'hypothesis':'No fit result was supplied.','change':'Request a separate admitted fit.','measurement':'Check the separate-fit artifact.','if_supported':'Review its own evidence.','if_not_supported':'Preserve the missing quantity.'}},tmp_path)
    request['context']=write(tmp_path/'context.json',current)
    out=report.compose(request,base_dir=tmp_path)
    assert not out['requested_quantity_completion']
    assert out['requested_quantity_census']==[{'id':'scores','passed':True,'exposed_fact_ids':['score0','score1']},{'id':'missing-fit','passed':False,'exposed_fact_ids':[]}]
    assert '| -0.225 |' in out['report_text'] and not out['scientific_acceptance']
    assert '| missing-fit | not completed | not exposed |' in out['report_text']
    assert 'Supplied context quantity completion: incomplete.' in out['report_text']
    revised=report.revise(request,draft(tmp_path,request),base_dir=tmp_path)
    assert '| missing-fit | not completed | not exposed |' in revised['report_text']
    assert 'Full-task scientific acceptance: unchecked.' in revised['report_text']


def test_passed_but_unexposed_requested_quantity_remains_visible(tmp_path):
    request=fixture(tmp_path);context=attach_context(tmp_path,request)
    specification=deepcopy(context['request'])
    specification['requested_quantities'].append({'id':'auxiliary-score','artifact':'probe','pointer':'/scores/0/value',
        'check':{'kind':'finite'},'meaning':'A distinct supplied scalar request, not exposed by these report facts.'})
    current=sc.compile_context(specification,tmp_path);step=context['steps'][0]
    current=sc.apply_step(current,{'id':step['id'],
        'outputs':{row['id']:{'path':row['path'],'sha256':row['sha256']} for row in step['outputs']},
        'code_status':step['code_status_reported'],'actor_complete':step['actor_complete_reported'],
        'question':step['question'],'next_experiment':step['next_experiment']},tmp_path)
    request['context']=write(tmp_path/'context.json',current)
    out=report.compose(request,base_dir=tmp_path)
    assert out['requested_quantity_completion'] is True
    assert out['requested_quantity_census'][-1]=={'id':'auxiliary-score','passed':True,'exposed_fact_ids':[]}
    assert '| auxiliary-score | passed | not exposed |' in out['report_text']
    assert not out['whole_quantity_exposure_checked'] and not out['scientific_acceptance']


def test_one_selected_record_is_not_whole_population_exposure(tmp_path):
    request=fixture(tmp_path);attach_context(tmp_path,request)
    request['facts']=request['facts'][:1]
    for section in request['sections']:
        section['rows']=section['rows'][:1]
        section['caption']='Only the first requested record is exposed here.'
    out=report.compose(request,base_dir=tmp_path)
    assert out['requested_quantity_completion'] is True
    assert out['requested_quantity_census']==[{'id':'scores','passed':True,'exposed_fact_ids':['score0']}]
    assert '| scores | passed | score0 |' in out['report_text']
    assert '"row_id": "0"' in out['report_text'] and '"row_id": "1"' not in out['report_text']
    assert 'does not establish complete record/vector coverage' in out['report_text']
    assert not out['whole_quantity_exposure_checked'] and not out['scientific_acceptance']


@pytest.mark.parametrize('action',['compose','revise'])
def test_contextless_report_leaves_requested_completion_unchecked(tmp_path,action):
    request=fixture(tmp_path)
    out=report.compose(request,base_dir=tmp_path) if action=='compose' else report.revise(request,draft(tmp_path,request),base_dir=tmp_path)
    assert out['requested_quantity_completion'] is None and out['requested_quantity_census']==[]
    assert 'Requested-quantity checks: unchecked; no scientific context was supplied.' in out['report_text']
    assert 'Full-task scientific acceptance: unchecked.' in out['report_text']
    assert not out['whole_quantity_exposure_checked']


@pytest.mark.parametrize('point', [False, 0])
def test_typed_record_identity_does_not_coerce_boolean_or_numeric_to_string(tmp_path,point):
    request=fixture(tmp_path);request['facts'][0]['selector']['row_id']=point
    with pytest.raises(ValueError,match='record absent'):report.compose(request,base_dir=tmp_path)


def test_complete_report_text_budget_refuses_without_silent_truncation(tmp_path):
    request=fixture(tmp_path)
    request['interpretation']=['x'*8000 for _ in range(32)]
    with pytest.raises(ValueError,match='complete report exceeds'):report.compose(request,base_dir=tmp_path)


def test_final_report_emits_procedure_after_completion_gate(tmp_path, monkeypatch):
    from ravel.workflow import task_completion as tc, procedure_export as pe
    from test_worker_audit import put
    request = fixture(tmp_path)
    completion_pin = put(tmp_path / 'inputs/task_completion.json', {'parent_review': {'rundir': str(tmp_path)}})
    request.update(task_completion=completion_pin, delivery='final')
    payload = {'parent_task_accepted': True, 'original_request': 'Synthetic diagnostic', 'obligation_census': [],
               'report_recipe_sha256': report.ce.digest({k: v for k, v in request.items() if k not in ('task_completion', 'delivery')})}
    monkeypatch.setattr(tc, 'require_final', lambda *a, **k: payload)
    result = report.compose(request, base_dir=tmp_path)
    assert (Path(result['procedure_export']['directory']) / 'procedure.md').exists()
    monkeypatch.setattr(tc, 'require_final', lambda *a, **k: (_ for _ in ()).throw(ValueError('parent open')))
    with pytest.raises(ValueError, match='parent open'): report.compose(request, base_dir=tmp_path)
