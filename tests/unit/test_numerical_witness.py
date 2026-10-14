"""Independent hand-frozen arithmetic and adverse witness controls."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.validation import numerical_witness as nw


def raw(value):
    return json.dumps(value,allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fixture(*,signed=False,normalization="all_events",model="poissonized_independent_groups"):
    weights = [2,-1,1,2] if signed else [1,1,1,1]
    groups = ["g0","g0","g1","g1"] if signed else ["g0","g1","g2","g3"]
    census = {"schema_version":1,"kind":"original_event_census","records":[
        {"event_id":f"e{i}","group_id":groups[i],"shard_id":"s0"} for i in range(4)]}
    original = raw(census)
    data = {"schema_version":1,"kind":"paired_normalized_rows",
            "basis":{"quantity":"regional_fraction","unit":"1","normalization":normalization,
                     "role":"nominal","channels":["lo","hi"],"checked_weight_stream":"A::nominal->B::nominal",
                     "representation":"integrated","bin_volumes":[1,1]},
            "uncertainty_model":model,"original_source_sha256":sha(original),
            "exposure":{"original_events":4,"derived_records":8},"records":[]}
    for i,w in enumerate(weights):
        data["records"].append({**census["records"][i],
            "baseline":{"bins":[w,0] if i<3 else [0,w],"denominator":w},
            "candidate":{"bins":[w,0] if i<2 else [0,w],"denominator":w}})
    return data,original


def verify(data,original,claim=None,**kwargs):
    source = raw(data)
    claim = raw(nw.derive(source) if claim is None else claim)
    pins = {"expected_checker_sha256":nw.checker_sha256(),"expected_input_sha256":sha(source),
            "expected_output_sha256":sha(claim),"original_source_bytes":original,
            "expected_original_source_sha256":sha(original)}
    pins.update(kwargs)
    return nw.verify(source,claim,**pins)


def matrix(value):
    from fractions import Fraction
    v = Fraction(value)
    return [[str(v),str(-v)],[str(-v),str(v)]]


def test_four_original_events_verify_exact_shared_denominator_cross_covariance():
    data,original = fixture()
    claim = nw.derive(raw(data))
    assert claim["values"] == {"baseline":["3/4","1/4"],"candidate":["1/2","1/2"],"difference":["-1/4","1/4"]}
    assert claim["covariance"] == {"baseline":matrix("3/64"),"candidate":matrix("1/16"),
                                   "cross":matrix("1/32"),"difference":matrix("3/64")}
    assert claim["exposure"] == {"original_events":4,"derived_records":8,"independent_groups":4}
    assert claim["arithmetic_verified"] is False
    receipt = verify(data,original)
    assert receipt["status"] == "verified" and receipt["arithmetic_verified"]
    assert receipt["physics_validated"] is False


def test_signed_subevents_are_grouped_before_squaring():
    data,original = fixture(signed=True)
    claim = nw.derive(data)
    assert claim["values"]["baseline"] == ["1/2","1/2"]
    assert claim["values"]["candidate"] == ["1/4","3/4"]
    assert claim["covariance"] == {"baseline":matrix("1/32"),"candidate":matrix("9/128"),
                                   "cross":matrix("3/64"),"difference":matrix("1/128")}
    assert verify(data,original)["status"] == "verified"


def test_fixed_iid_groups_is_an_explicit_exact_covariance_convention():
    data,original = fixture(model="fixed_iid_groups")
    claim = nw.derive(data)
    assert claim["covariance"]["difference"] == matrix("1/16")
    assert verify(data,original)["status"] == "verified"
    data["uncertainty_model"] = "poissonized_independent_groups"
    assert verify(data,original,claim)["status"] == "mismatch"


def test_density_divides_values_and_both_covariance_axes_by_declared_volumes():
    data,_ = fixture()
    data["basis"].update(representation="differential",bin_volumes=[2,4])
    claim = nw.derive(data)
    assert claim["values"]["baseline"] == ["3/8","1/16"]
    assert claim["covariance"]["difference"] == [["3/256","-3/512"],["-3/512","3/1024"]]


def test_unselected_original_events_distinguish_in_range_from_all_events():
    data,_ = fixture()
    data["records"][3]["baseline"]["bins"] = [0,0]
    assert nw.derive(data)["values"]["baseline"] == ["3/4","0"]
    data["basis"]["normalization"] = "in_range"
    with pytest.raises(ValueError,match="in_range denominator"):
        nw.derive(data)
    data["records"][3]["baseline"]["denominator"] = 0
    assert nw.derive(data)["values"]["baseline"] == ["1","0"]


def test_unchanged_arms_have_zero_paired_covariance():
    data,original = fixture(signed=True)
    for row in data["records"]:
        row["candidate"] = deepcopy(row["baseline"])
    assert nw.derive(data)["covariance"]["difference"] == matrix("0")
    assert verify(data,original)["status"] == "verified"


@pytest.mark.parametrize("mutation",["independent","covariance","denominator"])
def test_wrong_claim_fails_even_with_correct_claim_hash(mutation):
    data,original = fixture()
    claim = nw.derive(data)
    if mutation == "independent": claim["covariance"]["difference"] = matrix("7/64")
    elif mutation == "covariance": claim["covariance"]["cross"][0][1] = "0"
    else: claim["denominators"]["baseline"] = "8"
    receipt = verify(data,original,claim)
    assert receipt["status"] == "mismatch" and receipt["mismatches"]


@pytest.mark.parametrize("mutation",["missing","duplicate","group","shard","exposure"])
def test_projection_cannot_change_original_membership_or_grouping(mutation):
    data,original = fixture(signed=True)
    if mutation == "missing":
        data["records"].pop(); data["exposure"] = {"original_events":3,"derived_records":6}
    elif mutation == "duplicate": data["records"][1]["event_id"] = "e0"
    elif mutation == "group": data["records"][0]["group_id"] = "invented"
    elif mutation == "shard": data["records"][0]["shard_id"] = "different"
    else: data["exposure"]["derived_records"] = 4
    with pytest.raises(ValueError): verify(data,original)


@pytest.mark.parametrize("pin",["expected_checker_sha256","expected_input_sha256","expected_output_sha256","expected_original_source_sha256"])
def test_external_expected_identities_are_required(pin):
    data,original = fixture()
    with pytest.raises(ValueError,match="identity"):
        verify(data,original,**{pin:"0"*64})


def test_exact_decimal_tokens_and_explicit_rounding_tolerance():
    data,original = fixture()
    claim = nw.derive(data)
    claim["values"]["baseline"][0] = "0.750000000000000000000000000001"
    assert verify(data,original,claim)["status"] == "mismatch"
    assert verify(data,original,claim,atol="1e-29")["status"] == "verified"
    claim["basis"]["bin_volumes"][0] = "1.00000000000000000000001"
    assert verify(data,original,claim,atol="1")["status"] == "mismatch"


def test_zero_signed_denominator_and_one_fixed_group_do_not_verify():
    data,original = fixture()
    for row in data["records"]:
        row["baseline"] = {"bins":[0,0],"denominator":0}
    assert verify(data,original)["status"] == "unresolved"
    assert nw.derive(data)["values"] is None
    data,_ = fixture(model="fixed_iid_groups")
    for row in data["records"]: row["group_id"] = "single"
    assert nw.derive(data)["status"] == "unresolved"


@pytest.mark.parametrize("raw_json",[b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999999999}',b'{"a":'+b'1'*129+b'}'])
def test_malformed_or_unbounded_number_tokens_are_rejected(raw_json):
    with pytest.raises(ValueError): nw.loads(raw_json)


def test_permutation_is_irrelevant_and_checker_has_no_producer_imports():
    data,original = fixture(signed=True)
    expected = nw.derive(data)
    data["records"].reverse()
    assert nw.derive(data) == expected
    assert verify(data,original)["status"] == "verified"
    tree = ast.parse(Path(nw.__file__).read_text())
    roots = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
    roots |= {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
    assert roots <= {"__future__","argparse","decimal","fractions","hashlib","json","math","pathlib","sys"}


def test_cli_derive_preserves_existing_output(tmp_path,capsys):
    data,_ = fixture()
    source,out = tmp_path/"input.json",tmp_path/"claim.json"
    source.write_bytes(raw(data))
    assert nw.main(["derive","--input",str(source),"--out",str(out)]) == 0
    before = out.read_bytes()
    assert json.loads(before)["arithmetic_verified"] is False
    with pytest.raises(SystemExit): nw.main(["derive","--input",str(source),"--out",str(out)])
    assert out.read_bytes() == before
