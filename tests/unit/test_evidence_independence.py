"""Labels, semantics and exact numerics are separate evidence identities."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import evidence_independence as ei


def estimate():
    return {"schema_version":1,"kind":"estimates","population_id":"first population",
            "basis":{"quantity":"yield","unit":"pb","normalization":"absolute","role":"expected",
                     "definition":"Free prose","channels":["A","B"]},
            "expected_exposure":100,"actual_exposure":100,"values":[1,2],
            "covariance":[[1,0],[0,1]],"covariance_status":"supplied","uncertainty_scope":"Supplied covariance prose"}


def raw(value):
    return json.dumps(value,allow_nan=False).encode()


def test_all_prose_and_channel_relabeling_cannot_create_new_numerical_evidence():
    first = estimate(); second = deepcopy(first)
    second["population_id"] = "independent sounding source"
    second["uncertainty_scope"] = "different source description"
    second["basis"]["definition"] = "entirely different narrative"
    second["basis"]["channels"] = ["one","two"]
    report = ei.report({"first":raw(first),"relabelled":raw(second)})
    a,b = report["artifacts"]
    assert a["source_sha256"] != b["source_sha256"]
    assert a["numerical_sha256"] == b["numerical_sha256"]
    assert a["semantic_sha256"] != b["semantic_sha256"]
    assert report["status"] == "unresolved" and len(report["obligations"]) == 1
    assert report["physics_validated"] is report["independence_certified"] is report["quarantine_applied"] is False


def test_numeric_inequality_never_certifies_independence():
    first = estimate(); second = deepcopy(first); second["values"][0] = 3
    report = ei.report({"first":raw(first),"second":raw(second)})
    assert report["obligations"] == []
    assert report["independence_certified"] is False
    assert all(x["independence_status"] == "unresolved" for x in report["artifacts"])


def test_decimal_spellings_canonicalize_without_losing_tiny_differences():
    source = raw(estimate())
    same = source.replace(b'"values": [1, 2]',b'"values": [1.000, 2e0]')
    different = source.replace(b'"values": [1, 2]',b'"values": [1.000000000000000000000000000001, 2]')
    assert ei.fingerprints(source)["numerical_sha256"] == ei.fingerprints(same)["numerical_sha256"]
    assert ei.fingerprints(source)["numerical_sha256"] != ei.fingerprints(different)["numerical_sha256"]


@pytest.mark.parametrize("field,value",[("unit","fb"),("normalization","normalized"),("role","observed")])
def test_semantic_changes_are_separate_from_same_numeric_payload(field,value):
    first = estimate(); second = deepcopy(first); second["basis"][field] = value
    a,b = ei.fingerprints(raw(first)),ei.fingerprints(raw(second))
    assert a["numerical_sha256"] == b["numerical_sha256"]
    assert a["semantic_sha256"] != b["semantic_sha256"]


def test_zero_payload_is_reported_and_missing_covariance_is_not_zero():
    data = estimate(); data["values"] = [0,0]
    assert ei.fingerprints(raw(data))["all_zero_values"] is True
    missing = deepcopy(data); missing.update(covariance=None,covariance_status="unavailable")
    exact = deepcopy(data); exact.update(covariance=[[0,0],[0,0]],covariance_status="exact")
    assert ei.fingerprints(raw(missing))["numerical_sha256"] != ei.fingerprints(raw(exact))["numerical_sha256"]


@pytest.mark.parametrize("mutation",["empty","boolean","covariance","unknown"])
def test_malformed_payload_cannot_be_an_independent_anchor(mutation):
    data = estimate()
    if mutation == "empty": data["values"] = []
    elif mutation == "boolean": data["values"][0] = True
    elif mutation == "covariance": data["covariance"] = [[1]]
    else: data["new_numbers"] = [100]
    with pytest.raises(ValueError): ei.fingerprints(raw(data))


@pytest.mark.parametrize("raw_json",[b'{"a":1,"a":2}',b'{"a":Infinity}',b'{"a":1e999999999}',b'{"a":'+b'1'*129+b'}'])
def test_strict_bounded_json_loader(raw_json):
    with pytest.raises(ValueError): ei.loads(raw_json)


def test_cli_prints_report_and_preserves_existing_output(tmp_path,capsys):
    source,out = tmp_path/"source.json",tmp_path/"report.json"
    source.write_bytes(raw(estimate()))
    assert ei.main(["--artifact","source="+str(source),"--out",str(out)]) == 0
    before = out.read_bytes()
    assert json.loads(before)["status"] == "unresolved"
    with pytest.raises(SystemExit): ei.main(["--artifact","source="+str(source),"--out",str(out)])
    assert out.read_bytes() == before


def paired():
    return {"schema_version":1,"kind":"paired_normalized_rows","original_source_sha256":"0"*64,
            "uncertainty_model":"poissonized_independent_groups","exposure":{"original_events":2,"derived_records":4},
            "basis":{"quantity":"fraction","unit":"1","normalization":"all_events","role":"nominal",
                     "channels":["A","B"],"checked_weight_stream":"nominal","representation":"integrated","bin_volumes":[1,1]},
            "records":[{"event_id":"e0","group_id":"g0","shard_id":"s0","baseline":{"bins":[2,0],"denominator":2},
                        "candidate":{"bins":[0,2],"denominator":2}},
                       {"event_id":"e1","group_id":"g0","shard_id":"s0","baseline":{"bins":[-1,0],"denominator":-1},
                        "candidate":{"bins":[0,-1],"denominator":-1}}]}


def test_group_partition_survives_name_and_order_changes_in_numerical_digest():
    data = paired(); renamed = deepcopy(data)
    for i,row in enumerate(renamed["records"]):
        row.update(event_id=f"new{i}",group_id="renamed",shard_id="newshard")
    renamed["records"].reverse()
    assert ei.fingerprints(raw(data))["numerical_sha256"] == ei.fingerprints(raw(renamed))["numerical_sha256"]
    renamed["records"][0]["group_id"] = "separate-group"
    assert ei.fingerprints(raw(data))["numerical_sha256"] != ei.fingerprints(raw(renamed))["numerical_sha256"]


@pytest.mark.parametrize("mutation",["source","shard","exposure"])
def test_malformed_paired_schema_does_not_receive_a_content_identity(mutation):
    data = paired()
    if mutation == "source": data["original_source_sha256"] = "not-a-source-pin"
    elif mutation == "shard": data["records"][0]["shard_id"] = "elsewhere"
    else: data["exposure"]["original_events"] = 1
    with pytest.raises(ValueError): ei.fingerprints(raw(data))


def test_exact_covariance_status_requires_explicit_zero_covariance():
    data = estimate(); data["covariance_status"] = "exact"
    with pytest.raises(ValueError,match="nonzero covariance"): ei.fingerprints(raw(data))
