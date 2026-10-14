"""The replay corpus itself: complete, well formed, label-free and frozen where it says so."""
import collections
import hashlib
import json
import re

import pytest

import intake_records as ir

FIELD_GROUPS = ("theory", "phenomenology", "searches", "measurements", "eft-flavour", "cosmology", "ml-method",
                "supplied-data", "manuscripts", "literature", "open-questions")
FROZEN_SHA256 = "476e80c3b4b13e7c23c876395d3af2cb82f9b18e44f148bebf493226471fd9f5"
IDENTITY_LABELS = re.compile(r"evaluation suite, task|example suite, item|Shared-task submission|Task label:", re.I)


def test_named_sets_are_complete():
    ported = ir.load_cases("ported.json")
    assert len(ported) == 26
    assert {c["id"] for c in ported} == {f"B{i:02d}" for i in range(1, 25) if i not in (5, 6, 7, 15, 16)} | {"B14b", "S01", "S02", "S03", "S04", "S05", "S05b"}
    coverage = ir.load_cases("coverage.json")
    assert [c["id"] for c in coverage] == [f"Q{i:02d}" for i in range(1, 41)]
    assert len(ir.load_cases("probes.json")) == 9
    assert len(ir.load_cases("generic.json")) >= 60


def test_case_ids_are_unique_and_cases_well_formed():
    cases = ir.load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    errors = {c["id"]: ir.shape_errors(c) for c in cases}
    assert not {k: v for k, v in errors.items() if v}
    for case in cases:
        assert case["prompt"].strip() and case.get("expect"), case["id"]
        assert set(case) <= {"id", "group", "prompt", "expect", "split", "counterfactual_of", "file"}, case["id"]


def test_every_field_and_boundary_class_has_at_least_four_cases():
    cases = ir.load_cases()
    groups = collections.Counter(c["group"] for c in cases)
    assert all(groups[g] >= 4 for g in FIELD_GROUPS), groups
    classes = collections.Counter(b for c in cases
                                  for b in set(c["expect"].get("boundaries", []) + c["expect"].get("boundaries_any", [])))
    assert all(classes[b] >= 4 for b in ir.BOUNDARY_CLASSES), classes


def test_scan_shaped_requests_assert_against_one_point_plans():
    scans = [c for c in ir.load_cases() if "scan_range" in c["expect"]]
    assert len(scans) >= 6


def test_cases_assert_no_task_mode():
    for case in ir.load_cases():
        assert "task_mode" not in json.dumps(case["expect"]), case["id"]


def test_identity_labels_appear_only_in_label_cases():
    for case in ir.load_cases():
        labelled = bool(IDENTITY_LABELS.search(case["prompt"]))
        expects_label = (any(c["type"] == "identity_context" for c in case["expect"].get("constraints", []))
                         or "ungrounded_identifier" in case["expect"].get("boundaries", []))
        assert labelled == expects_label, case["id"]


def test_counterfactuals_differ_only_by_their_label_or_delegation():
    cases = {c["id"]: c for c in ir.load_cases("ported.json")}
    for case in cases.values():
        base = case.get("counterfactual_of")
        if base:
            assert case["prompt"].endswith(cases[base]["prompt"]), case["id"]
            assert case["prompt"] != cases[base]["prompt"]


def test_frozen_subset_is_unchanged():
    frozen = [{"id": c["id"], "prompt": c["prompt"], "expect": c["expect"]}
              for c in ir.load_cases("generic.json") if c.get("split") == "frozen"]
    assert len(frozen) >= 10
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == FROZEN_SHA256, "the frozen subset changed; frozen cases are never edited to fit a reader"


@pytest.mark.parametrize("case", ir.case_params("ported.json", "coverage.json", "probes.json"))
def test_open_requests_expect_no_hold(case):
    expect = case["expect"]
    if case["id"] == "Q32":
        assert expect["boundaries"] == ["inaccessible_input"]
    else:
        assert expect.get("held") is False, "every ordinary request must state that it is not held"
