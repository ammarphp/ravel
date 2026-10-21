"""stat_mode_decision: the coded statistical-mode ladder, its record, CLI and result-pack label."""
import copy
import hashlib
import json

import pytest

from ravel.validation import validate_task_contract
from ravel.workflow import stat_mode_decision as smd


def evidence(*, likelihood=None, blocking=None, covariance=False, source="published covariance table",
             registry=False, yields=False, exclusive=None):
    review = None
    if likelihood is not None and likelihood != "unassessed":
        review = {"path": "inputs/likelihood_appropriateness.json", "verdict": likelihood}
        if blocking is not None:
            review["blocking_codes"] = blocking
    return {
        "published_likelihood": {"available": likelihood is not None,
                                 "path": "inputs/bkg_only.json" if likelihood is not None else None,
                                 "appropriateness": review},
        "covariance": {"available": covariance, "path": "inputs/covariance.json" if covariance else None,
                       "source": source if covariance else None},
        "systematics_registry": {"available": registry, "path": "inputs/systematics.json" if registry else None},
        "yields": {"available": yields, "path": "outputs/sr_yields.json" if yields else None},
        "mutually_exclusive_regions": exclusive,
    }


def statuses(record):
    return [(row["stat_mode"], row["status"]) for row in record["ladder"]]


@pytest.mark.parametrize("verdict", ["appropriate", "appropriate-with-cautions"])
def test_published_likelihood_selected_when_appropriate(verdict):
    record = smd.decide(evidence(likelihood=verdict, covariance=True, yields=True, registry=True))
    assert record["status"] == "resolved" and record["selected"] == "published-likelihood"
    assert statuses(record) == [("published-likelihood", "selected"), ("simplified-likelihood", "not-reached"),
                                ("constructed-likelihood", "not-reached"), ("best-sr-counting", "not-reached")]
    assert record["downgrades"] == [] and record["label"] is None and record["correlations_statement"] is None
    assert smd.validate_record(record) == []


def test_unassessed_likelihood_is_rejected_and_downgraded():
    record = smd.decide(evidence(likelihood="unassessed", covariance=True))
    assert record["selected"] == "simplified-likelihood"
    assert record["ladder"][0]["status"] == "rejected"
    assert record["ladder"][0]["reason"] == "appropriateness not assessed"
    assert record["downgrades"] == [{"from": "published-likelihood", "to": "simplified-likelihood",
                                     "reason": "appropriateness not assessed"}]
    assert record["label"] == ("Statistical model downgraded: published-likelihood → simplified-likelihood "
                               "because appropriateness not assessed")


def test_inappropriate_likelihood_names_its_blocking_codes():
    record = smd.decide(evidence(likelihood="inappropriate", blocking=["selection-changed", "missing-channels"],
                                 yields=True, registry=True))
    assert record["selected"] == "constructed-likelihood"
    assert record["ladder"][0] == dict(record["ladder"][0], status="rejected",
                                       reason="appropriateness verdict inappropriate: missing-channels, selection-changed")
    assert record["ladder"][1]["status"] == "unavailable"
    assert [d["from"] for d in record["downgrades"]] == ["published-likelihood", "simplified-likelihood"]
    assert record["label"].count("→ constructed-likelihood because") == 2


def test_covariance_without_source_is_rejected():
    record = smd.decide(evidence(covariance=True, source="  ", yields=True))
    assert record["ladder"][1]["status"] == "rejected"
    assert record["ladder"][1]["reason"] == "covariance source not recorded"
    assert record["selected"] == "best-sr-counting"


def test_constructed_requires_both_yields_and_registry():
    only_registry = smd.decide(evidence(registry=True))
    assert only_registry["status"] == "unresolved"
    assert only_registry["ladder"][2] == dict(only_registry["ladder"][2], status="unavailable",
                                              reason="no published per-region yields")
    only_yields = smd.decide(evidence(yields=True))
    assert only_yields["ladder"][2]["reason"] == "no declared systematics registry"
    assert only_yields["selected"] == "best-sr-counting"


def test_best_sr_counting_states_its_correlation_assumption():
    record = smd.decide(evidence(yields=True, exclusive=False))
    assert record["selected"] == "best-sr-counting"
    assert record["correlations_statement"] == (
        "background correlations between regions not published; constraints assumed independent; "
        "limit quoted from the single most sensitive region")
    assert len(record["downgrades"]) == 3
    assert record["label"].startswith("Statistical model downgraded: published-likelihood → best-sr-counting "
                                      "because no published likelihood recorded; ")


def test_combined_counting_only_when_regions_are_mutually_exclusive():
    record = smd.decide(evidence(yields=True, exclusive=True))
    assert record["selected"] == "combined-counting"
    assert record["ladder"][3]["stat_mode"] == "combined-counting"
    assert record["ladder"][3]["evidence"]["mutually_exclusive_regions"] is True
    assert "mutually exclusive" in record["correlations_statement"]
    assert smd.decide(evidence(yields=True, exclusive=None))["selected"] == "best-sr-counting"


def test_nothing_available_is_unresolved():
    record = smd.decide(evidence())
    assert record["status"] == "unresolved" and record["selected"] is None
    assert [row["status"] for row in record["ladder"]] == ["unavailable"] * 4
    assert record["downgrades"] == [] and record["label"] is None
    assert smd.validate_record(record) == []


def test_every_selectable_mode_is_a_contract_stat_mode():
    for mode in (*smd.LADDER, smd.COUNTING_ALTERNATIVE):
        assert mode in validate_task_contract.STAT_MODES


@pytest.mark.parametrize("mutate", [
    lambda e: e.update(extra=1),
    lambda e: e.pop("yields"),
    lambda e: e["yields"].update(note="x"),
    lambda e: e["yields"].pop("path"),
    lambda e: e["yields"].update(available="yes"),
    lambda e: e["yields"].update(available=True, path=None),
    lambda e: e["covariance"].update(source=3),
    lambda e: e.update(mutually_exclusive_regions="yes"),
    lambda e: e["published_likelihood"].update(available=True, path="p",
                                               appropriateness={"path": "a", "verdict": "fine"}),
    lambda e: e["published_likelihood"].update(available=True, path="p",
                                               appropriateness={"path": "a", "verdict": "inappropriate"}),
    lambda e: e["published_likelihood"].update(available=True, path="p",
                                               appropriateness={"path": "a", "verdict": "appropriate", "x": 1}),
])
def test_evidence_schema_refusals(mutate):
    bad = evidence(yields=True)
    mutate(bad)
    assert smd.evidence_errors(bad)
    with pytest.raises(ValueError):
        smd.decide(bad)


def test_validate_record_detects_edits_that_do_not_follow_from_evidence():
    record = smd.decide(evidence(yields=True, covariance=True))
    assert smd.validate_record(record) == []
    for key, value in (("selected", "best-sr-counting"), ("label", None), ("downgrades", []),
                       ("status", "unresolved"), ("selected", "not-a-mode")):
        assert smd.validate_record(dict(record, **{key: value})), key
    forged = copy.deepcopy(record)
    forged["ladder"][0]["status"] = "unavailable"
    forged["ladder"][0]["reason"] = "edited"
    assert smd.validate_record(forged)
    assert smd.validate_record(dict(record, unknown=1))
    assert smd.validate_record(dict(record, supersedes={"sha256": "nothex"}))
    assert smd.validate_record(dict(record, supersedes={"sha256": "a" * 64})) == []


# --------------------------------------------------------------------------- CLI

def _rundir(tmp_path, stat_mode="best-sr-counting"):
    rd = tmp_path / "2026-10-21_decision"
    (rd / "inputs").mkdir(parents=True)
    (rd / "outputs").mkdir()
    (rd / "inputs/task_contract.json").write_text(json.dumps({"stat_mode": stat_mode}))
    (rd / "outputs/sr_yields.json").write_text("[]")
    return rd


def _evidence_file(tmp_path, value, name="evidence.json"):
    path = tmp_path / name
    path.write_text(json.dumps(value))
    return str(path)


def test_cli_write_then_check(tmp_path, capsys):
    rd = _rundir(tmp_path)
    ev = _evidence_file(tmp_path, evidence(yields=True))
    assert smd.main(["--rundir", str(rd), "--evidence", ev, "--write"]) == 0
    record = json.loads((rd / smd.RECORD).read_text())
    assert record["selected"] == "best-sr-counting" and smd.validate_record(record) == []
    assert smd.main(["--rundir", str(rd), "--check"]) == 0
    # identical evidence again is a no-op
    assert smd.main(["--rundir", str(rd), "--evidence", ev, "--write"]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_cli_check_fails_on_mode_mismatch_invalid_or_unresolved(tmp_path):
    rd = _rundir(tmp_path, stat_mode="simplified-likelihood")
    assert smd.main(["--rundir", str(rd), "--check"]) == 1          # no record
    assert smd.main(["--rundir", str(rd), "--evidence", _evidence_file(tmp_path, evidence(yields=True)),
                     "--write"]) == 0
    assert smd.main(["--rundir", str(rd), "--check"]) == 1          # selected != contract
    record = json.loads((rd / smd.RECORD).read_text())
    (rd / smd.RECORD).write_text(json.dumps(dict(record, selected="simplified-likelihood")))
    assert smd.main(["--rundir", str(rd), "--check"]) == 1          # invalid
    unresolved = tmp_path / "u"
    unresolved.mkdir()
    rd2 = _rundir(unresolved)
    (rd2 / "inputs/task_contract.json").write_text(json.dumps({}))
    (rd2 / smd.RECORD).write_text(json.dumps(smd.decide(evidence())))
    assert smd.main(["--rundir", str(rd2), "--check"]) == 1          # unresolved never matches


def test_cli_refuses_to_overwrite_a_different_record_without_force(tmp_path):
    rd = _rundir(tmp_path)
    (rd / "inputs/covariance.json").write_text("{}")
    assert smd.main(["--rundir", str(rd), "--evidence", _evidence_file(tmp_path, evidence(yields=True)),
                     "--write"]) == 0
    first = (rd / smd.RECORD).read_bytes()
    other = _evidence_file(tmp_path, evidence(yields=True, covariance=True), "other.json")
    assert smd.main(["--rundir", str(rd), "--evidence", other, "--write"]) == 1
    assert (rd / smd.RECORD).read_bytes() == first
    assert smd.main(["--rundir", str(rd), "--evidence", other, "--write", "--force"]) == 0
    record = json.loads((rd / smd.RECORD).read_text())
    assert record["selected"] == "simplified-likelihood"
    assert record["supersedes"] == {"sha256": hashlib.sha256(first).hexdigest()}
    assert smd.validate_record(record) == []


def test_cli_refuses_evidence_files_that_do_not_exist_or_disagree(tmp_path):
    rd = _rundir(tmp_path, stat_mode="published-likelihood")
    ev = evidence(likelihood="appropriate")
    assert smd.main(["--rundir", str(rd), "--evidence", _evidence_file(tmp_path, ev), "--write"]) == 1
    (rd / "inputs/bkg_only.json").write_text("{}")
    from ravel.validation import likelihood_appropriateness as la
    doc = {"schema_version": 1, "kind": "likelihood-appropriateness", "verdict": "appropriate-with-cautions",
           "findings": [{"code": "selection-unverified", "severity": "caution", "evidence": {}, "reason": "-"}],
           "checks": [], "thresholds": {}, "inputs": [], "scope": la.SCOPE}
    (rd / "inputs/likelihood_appropriateness.json").write_text(json.dumps(doc))
    assert smd.main(["--rundir", str(rd), "--evidence", _evidence_file(tmp_path, ev), "--write"]) == 1
    ev["published_likelihood"]["appropriateness"]["verdict"] = "appropriate-with-cautions"
    assert smd.main(["--rundir", str(rd), "--evidence", _evidence_file(tmp_path, ev), "--write"]) == 0
    assert smd.main(["--rundir", str(rd), "--check"]) == 0


def test_cli_usage_errors_exit_2(tmp_path):
    rd = _rundir(tmp_path)
    assert smd.main(["--rundir", str(rd)]) == 2
    assert smd.main(["--rundir", str(rd), "--write"]) == 2
    assert smd.main(["--rundir", str(tmp_path / "absent"), "--check"]) == 2
    (tmp_path / "bad.json").write_text("{")
    assert smd.main(["--rundir", str(rd), "--evidence", str(tmp_path / "bad.json"), "--write"]) == 2
    bad = evidence(yields=True)
    bad["extra"] = 1
    assert smd.main(["--rundir", str(rd), "--evidence", _evidence_file(tmp_path, bad), "--write"]) == 2


# --------------------------------------------------------------------------- result pack

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    for key in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "RAVEL_SESSION_ID", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _pack_argv(rd, *extra):
    return ["--rundir", str(rd), "--stat-mode", "best-sr-counting", "--detector-mode", "particle-level",
            "--normalization-ledger", "outputs/normalization-ledger.json", *extra]


def _packable_run(tmp_path):
    from test_host_governance import _packable
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    (rd / "inputs").mkdir()
    (rd / smd.RECORD).write_text(json.dumps(smd.decide(evidence(yields=True))))
    return rd


def test_result_pack_without_the_flag_is_unchanged(tmp_path, isolated):
    from ravel.workflow import result_pack
    rd = _packable_run(tmp_path)
    assert result_pack.main(_pack_argv(rd)) == 0
    result = json.loads((rd / "result.json").read_text())
    assert "stat_mode_decision" not in result
    assert not any(row.get("key") == "stat-mode-downgrade" for row in result["limitations"])


def test_result_pack_carries_the_decision_and_its_downgrade_label(tmp_path, isolated):
    from ravel.workflow import result_pack
    rd = _packable_run(tmp_path)
    assert result_pack.main(_pack_argv(rd, "--stat-mode-decision", smd.RECORD)) == 0
    result = json.loads((rd / "result.json").read_text())
    record = json.loads((rd / smd.RECORD).read_text())
    block = result["stat_mode_decision"]
    assert block["selected"] == "best-sr-counting" and block["status"] == "resolved"
    assert block["downgrades"] == record["downgrades"] and block["label"] == record["label"]
    assert block["ladder"] == [{"stat_mode": r["stat_mode"], "status": r["status"]} for r in record["ladder"]]
    assert block["record_sha256"] == hashlib.sha256((rd / smd.RECORD).read_bytes()).hexdigest()
    rows = [row for row in result["limitations"] if row["key"] == "stat-mode-downgrade"]
    assert rows == [{"key": "stat-mode-downgrade", "note": record["label"]}]


def test_result_pack_does_not_duplicate_a_supplied_downgrade_limitation(tmp_path, isolated):
    from ravel.workflow import result_pack
    rd = _packable_run(tmp_path)
    argv = _pack_argv(rd, "--stat-mode-decision", smd.RECORD, "--limitations", "stat-mode-downgrade:own note")
    assert result_pack.main(argv) == 0
    rows = [row for row in json.loads((rd / "result.json").read_text())["limitations"]
            if row["key"] == "stat-mode-downgrade"]
    assert rows == [{"key": "stat-mode-downgrade", "note": "own note"}]


def test_result_pack_refuses_a_decision_for_another_mode_or_an_invalid_record(tmp_path, isolated):
    from ravel.workflow import result_pack
    rd = _packable_run(tmp_path)
    (rd / smd.RECORD).write_text(json.dumps(smd.decide(evidence(yields=True, exclusive=True))))
    with pytest.raises(result_pack.PackError, match="combined-counting"):
        result_pack.main(_pack_argv(rd, "--stat-mode-decision", smd.RECORD))
    record = smd.decide(evidence(yields=True))
    (rd / smd.RECORD).write_text(json.dumps(dict(record, label="edited")))
    with pytest.raises(result_pack.PackError, match="invalid"):
        result_pack.main(_pack_argv(rd, "--stat-mode-decision", smd.RECORD))
    assert not (rd / "result.json").exists()
