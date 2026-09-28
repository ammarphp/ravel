"""The WP12 standalone stage workers under the RAVEL stage supervisor: census, calc and figure (design §3.3).

Inputs: the two complete public Drell-Yan LHE files of the 2026-09-09 scoped-workflow controls and the
content-truncated fixture (pinned in fixtures/lhe/fixtures.json; RAVEL-generated development samples,
not physics results), production records DERIVED from those controls' spec.json generation blocks
(without ``runtime``), SYNTHETIC LHE variants of them built in the tests, and SYNTHETIC fit records and
calc requests. No generator runs and nothing here is empirical evidence. The census results are compared
with the independent LHE census oracle, which the stage never imports.
"""
import gzip
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from governance import stages
from governance.oracle import lhe_census
from governance.stages import calc, census, figure

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "governance" / "fixtures" / "lhe"
PINNED = json.loads((FIXTURES / "fixtures.json").read_text())
CONTROLS = {"dy-1729": "drell-yan", "dy-1730": "drell-yan-replica"}
STAGE_ENV = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src"), "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
             "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
# The design's selection (§2 P4): status-1 e+ e- pair mass in the open window (81, 101) GeV.
SELECTION = {"observable": "pair_invariant_mass", "unit": "GeV", "pdg_ids": [-11, 11], "status": 1,
             "multiplicity": "exactly_one_each", "window": [81, 101], "edges": "exclusive"}
# A SYNTHETIC fit record (the hv family's oracle values, design §2 P6; not a kernel result).
FIT = {"schema_version": 1, "obs_limit_events": 34.014202,
       "exp_limits_events": [11.585294, 15.603377, 21.78224, 30.597166, 41.578841],
       "limit_status": {"observed": "resolved", "expected": ["resolved"] * 5}}
LEGEND = [{"series": "solid", "label": "Observed", "field": "obs_limit_events"},
          {"series": "dashed", "label": "Expected (median)", "field": "exp_limits_events[2]"}]
SWAPPED = [{**LEGEND[0], "label": "Expected (median)"}, {**LEGEND[1], "label": "Observed"}]


def encode(value):
    return json.dumps(value, indent=1, sort_keys=True).encode() + b"\n"


def sample(label):
    return (REPO / PINNED["referenced"][label]["path"]).read_bytes()


def manifest(label, **changes):
    """A DERIVED development production record: the control's generation plan without runtime, the file digest."""
    control = REPO / "evidence/audits/2026-09-09-scoped-workflows" / CONTROLS[label]
    spec = json.loads((control / "spec.json").read_text())
    record = {"generation": {k: v for k, v in spec["generation"].items() if k != "runtime"},
              "file_sha256": PINNED["referenced"][label]["sha256"], "status": "completed",
              "label": "development fixture (derived from a RAVEL production spec)"}
    record.update(changes)
    return record


def supervised(tmp_path, stage, files):
    """Run one stage worker under the RAVEL stage supervisor in a fresh run dir; (exit code, artifact, failure)."""
    rundir = tmp_path / stage
    for relative, data in files.items():
        (rundir / relative).parent.mkdir(parents=True, exist_ok=True)
        (rundir / relative).write_bytes(data)
    home = tmp_path / f"{stage}-home"
    home.mkdir()
    argv = stages.supervisor_argv(sys.executable, stage, rundir, kill_secs=600, poll=0.1)
    done = subprocess.run(argv, cwd=rundir, env={**STAGE_ENV, "HOME": str(home), "TMPDIR": str(home)},
                          capture_output=True, text=True, timeout=900)
    artifact, failure = rundir / stages.STAGES[stage]["artifact"], rundir / "outputs" / stage / "failure.json"
    return (done.returncode, json.loads(artifact.read_text()) if artifact.exists() else None,
            json.loads(failure.read_text()) if failure.exists() else None)


def run_census(tmp_path, data, record, selection=SELECTION):
    code, content, failure = supervised(tmp_path, "census", {"inputs/events.lhe.gz": data,
                                                             "inputs/manifest.json": encode(record),
                                                             "inputs/selection.json": encode(selection)})
    assert code == 0 and failure is None, failure
    return content


# ---------------------------------------------------------------- declarations

def test_stage_declarations_match_the_registry():
    from governance.tasks import registry
    assert stages.WORKERS == stages.ORDER + stages.STANDALONE and stages.COORDINATOR_ONLY == ("figure",)
    for name in stages.WORKERS:
        assert stages.worker_path(name).is_file()
        assert registry.STAGES[name]["artifact"] == stages.STAGES[name]["kind"]
        assert registry.STAGES[name]["coordinator_only"] == (name in stages.COORDINATOR_ONLY)
    files = {"inputs/params.json": stages.params_bytes({"b": 1, "a": [2]})}
    assert files["inputs/params.json"] == b'{"a":[2],"b":1}'
    key = stages.run_key("calc", files)
    assert len(key) == 16 and key == stages.run_key("calc", dict(files))
    assert key != stages.run_key("calc", {"inputs/params.json": stages.params_bytes({"a": [2], "b": 2})})
    assert key != stages.run_key("figure", {"inputs/params.json": files["inputs/params.json"],
                                            "inputs/fit.json": b"{}"})
    with pytest.raises(ValueError):
        stages.run_key("fit", files)
    with pytest.raises(ValueError):
        stages.run_key("calc", {**files, "inputs/other.json": b"{}"})


def test_standalone_workers_refuse_to_run_outside_the_supervisor(tmp_path):
    for name in stages.STANDALONE:
        done = subprocess.run([sys.executable, str(stages.worker_path(name)), str(tmp_path)],
                              env=STAGE_ENV, capture_output=True, text=True)
        assert done.returncode != 0 and "RAVEL stage supervisor" in done.stderr
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- census

@pytest.mark.parametrize("label,selected", [("dy-1729", 87), ("dy-1730", 89)])
def test_census_of_a_complete_sample_agrees_with_the_oracle(tmp_path, label, selected):
    record = run_census(tmp_path, sample(label), manifest(label))
    oracle = lhe_census.census(sample(label), selection=SELECTION, expected_sha256=manifest(label)["file_sha256"])
    assert record["physics_status"] == "computed" and record["physics_withheld_reasons"] == []
    assert record["recipe_check"] == "passed" and record["recipe_check_error"] is None
    assert (record["gzip_complete"], record["document_complete"], record["sha256_matches_record"]) == (True, True, True)
    assert record["complete_events"] == record["header_nevents"] == oracle["complete_events"] == 100
    assert record["selected_events"] == oracle["selected_events"] == selected
    assert record["event_norm"] == oracle["event_norm"] == "average"
    for field in ("cross_section_pb", "integration_error_pb", "sum_weights", "sum_weights_sq", "selected_sum_weights"):
        assert math.isclose(record[field], oracle[field], rel_tol=1e-12), field
    assert record["file_sha256"] == oracle["file_sha256"] and record["file_bytes"] == oracle["file_bytes"]
    for field in ("gzip_complete", "document_complete", "sha256_matches_record"):
        assert type(record[field]) is bool


def test_census_of_the_content_truncated_fixture_reports_integrity_and_no_physics(tmp_path):
    data = (REPO / "benchmarks" / "governance" / "tasks" / "data" / "dy-1730-content-truncated.lhe.gz").read_bytes()
    record = run_census(tmp_path, data, manifest("dy-1730"))
    oracle = lhe_census.census(data, selection=SELECTION, expected_sha256=manifest("dy-1730")["file_sha256"])
    assert (record["gzip_complete"], record["stream_error"], record["document_complete"]) == (True, None, False)
    assert record["complete_events"] == oracle["complete_events"] == 41 and record["header_nevents"] == 100
    assert record["sha256_matches_record"] is False and record["file_sha256"].startswith("c45eea92cf78")
    assert record["physics_status"] == "withheld"
    assert record["physics_withheld_reasons"] == ["document_incomplete", "event_count_mismatch"]
    assert record["recipe_check"] == "not_run"     # the kernel reader is never asked (it raises on this file)
    assert all(record[field] is None for field in census.PHYSICS_FIELDS)   # no prefix physics (D-CP)


def test_census_of_a_gzip_level_cut_withholds_physics(tmp_path):
    data = sample("dy-1730")[:10528]
    record = run_census(tmp_path, data, manifest("dy-1730"))
    assert (record["gzip_complete"], record["stream_error"]) == (False, "truncated_stream")
    assert record["physics_withheld_reasons"][0] == "gzip_incomplete"
    assert all(record[field] is None for field in census.PHYSICS_FIELDS)


PHOTON = (" 22 1 1 2 0 0 +5.0000000000e+00 +0.0000000000e+00 +5.0000000000e+00 7.0710678119e+00 "
          "0.0000000000e+00 0.0000e+00 9.0000e+00")


def extra_photon(data):
    """A SYNTHETIC variant of a complete sample: one extra status-1 photon in every event (NUP + 1)."""
    out, state = [], None
    for line in gzip.decompress(data).decode().split("\n"):
        stripped = line.strip()
        if stripped == "<event>":
            state = "header"
        elif state == "header":
            fields = line.split()
            line, state = " " + " ".join([str(int(fields[0]) + 1), *fields[1:]]), "particles"
        elif state == "particles" and stripped.startswith(("<", "#")):
            out.append(PHOTON)
            state = None
        out.append(line)
    return gzip.compress("\n".join(out).encode(), mtime=0)


def test_census_applies_the_selection_only_to_the_plan_final_state(tmp_path):
    """Oracle appendix §3a: the kernel's masses are over the whole status-1 final state, so the census applies the
    pair selection to them only when the selection's particles are the plan's final state."""
    plan = manifest("dy-1729")
    widened = json.loads(json.dumps(plan))
    widened["generation"]["observable"]["final_state_pdg"] = [-11, 11, 22]
    record = run_census(tmp_path / "a", sample("dy-1729"), widened)
    assert record["physics_withheld_reasons"] == ["selection_not_the_plan_final_state"]
    assert record["recipe_check"] == "not_run" and record["selected_events"] is None
    shapeless = json.loads(json.dumps(plan))
    shapeless["generation"]["observable"] = "e+ e- pair"            # no final state to compare: withheld, no crash
    record = run_census(tmp_path / "d", sample("dy-1729"), shapeless)
    assert record["physics_withheld_reasons"] == ["selection_not_the_plan_final_state"]
    # A SYNTHETIC file with an extra status-1 particle against the two-lepton plan: the kernel refuses it.
    photon = extra_photon(sample("dy-1729"))
    record = run_census(tmp_path / "b", photon, {**plan, "file_sha256": hashlib.sha256(photon).hexdigest()})
    assert record["complete_events"] == 100 and record["document_complete"] is True
    assert record["sha256_matches_record"] is True
    assert record["recipe_check"] == "failed" and record["recipe_check_error"].startswith("ValueError: ")
    assert record["physics_withheld_reasons"] == ["recipe_check_failed"]
    assert all(record[field] is None for field in census.PHYSICS_FIELDS)
    swapped = {**SELECTION, "pdg_ids": [11, -11]}                # the same particles in the other order
    assert run_census(tmp_path / "c", sample("dy-1729"), plan, swapped)["selected_events"] == 87


def test_census_identity_does_not_gate_physics(tmp_path):
    """Design §2 P5: identity is its own integrity field; a complete file that is not the recorded one still has
    physics (the evidence constraint on the endpoints, not the census, scores the choice of copy)."""
    other = manifest("dy-1730", file_sha256=manifest("dy-1729")["file_sha256"])
    record = run_census(tmp_path, sample("dy-1730"), other)
    assert record["sha256_matches_record"] is False and record["physics_status"] == "computed"
    assert record["selected_events"] == 89


@pytest.mark.parametrize("bad,match", [
    ({"selection": {**SELECTION, "edges": "inclusive"}}, "edges"),
    ({"selection": {**SELECTION, "status": 2}}, "status"),
    ({"selection": {**SELECTION, "window": [101, 81]}}, "window"),
    ({"selection": {**SELECTION, "extra": 1}}, "fields"),
    ({"manifest": {"generation": {}}}, "file_sha256"),
    ({"manifest": {"file_sha256": "0" * 64}}, "generation plan"),
])
def test_census_rejects_malformed_selection_and_records(tmp_path, bad, match):
    files = {"inputs/events.lhe.gz": sample("dy-1729"),
             "inputs/manifest.json": encode(bad.get("manifest", manifest("dy-1729"))),
             "inputs/selection.json": encode(bad.get("selection", SELECTION))}
    code, content, failure = supervised(tmp_path, "census", files)
    assert code != 0 and content is None and failure["type"] == "ValueError" and match in failure["error"]


def test_census_integrity_pass_on_edge_contents():
    assert census.inflate(b"not gzip") == (b"", False, "not_gzip")
    member = gzip.compress(b"a\n", mtime=0)
    assert census.inflate(member + member) == (b"a\na\n", True, None)
    assert census.inflate(member + b"xx") == (b"a\n", False, "trailing_data")
    corrupt = member[:-8] + bytes(b ^ 0xFF for b in member[-8:-4]) + member[-4:]     # a wrong CRC-32
    assert census.inflate(corrupt)[1:] == (False, "corrupt_stream")
    body = (b"<LesHouchesEvents>\n<init>\n</init>\n<event>\n 2 1 +1.0e+00 1 1 1\n</event>\n"
            b"<event>\n 2 1 +2.0e+00 1 1 1\n</eve")
    facts = census.scan(body)
    assert (facts["complete_events"], facts["document_complete"], facts["weights"]) == (1, False, [1.0])
    closed = census.scan(body[:-5] + b"</event>\n</LesHouchesEvents>")    # a closing tag cut before its newline counts
    assert (closed["complete_events"], closed["document_complete"]) == (2, True)


# ---------------------------------------------------------------- calc

@pytest.mark.parametrize("expression,names,literal", [
    ("lumi * xs * 10^3 * sel / tot", {"lumi", "xs", "sel", "tot"}, 3),
    ("lumi*xs*sel/tot", {"lumi", "xs", "sel", "tot"}, None),
    ("a * 10^-3 / b", {"a", "b"}, -3),
    ("a * 10^(-6)", {"a"}, -6),
    ("10^6 / a", {"a"}, 6),
    ("sqrt(a * b) / (c * d)", {"a", "b", "c", "d"}, None),
])
def test_calc_grammar_accepts_products_quotients_sqrt_and_one_power_of_ten(expression, names, literal):
    tree = calc.parse(expression)
    assert calc.names_of(tree) == names
    found = calc.literal_of(tree, expression)
    if literal is None:
        assert found is None
    else:
        assert found["exponent"] == literal and found["text"] in expression


@pytest.mark.parametrize("expression,match", [
    ("S95/(10^2+10^1+10^1)", "addition"),                 # the lf-d laundering route of design §3.3
    ("a + b", "addition"),
    ("a - b", "subtraction"),
    ("-a", "subtraction"),
    ("a * (10^3)", "literal-only subexpression"),
    ("sqrt(10^2) * a", "literal-only subexpression"),
    ("(10^3) * a", "literal-only subexpression"),
    ("10^3", "no literal-only expression"),
    ("a * 1000", "one power of ten"),
    ("a * 2", "one power of ten"),
    ("a * 1e3", "one power of ten"),
    ("a * 10^2.5", "one power of ten"),
    ("a * 10^7", "k from -6 to 6"),
    ("a * 10^3 * 10^-3", "at most one literal"),
    ("a / 10^3", "multiplicative factor"),
    ("a ^ 2", "only in the literal"),
    ("sqrt * a", "function"),
    ("a b", "unexpected"),
    ("(a", r"expected '\)'"),
    ("", "nonblank"),
])
def test_calc_grammar_rejects(expression, match):
    with pytest.raises(calc.CalcError, match=match):
        calc.parse(expression)


def request(expression, **values):
    return {"expression": expression, "unit": "events", "label": "selected-event prediction",
            "bindings": [{"name": n, "handle": "art-0123456789ab", "field": f, "value": v}
                         for n, (f, v) in values.items()]}


def test_calc_request_checks_bindings_units_and_labels():
    good = request("a / b", a=("x", 1.0), b=("y", 2.0))
    calc.check_request(good)
    for change, match in [
            ({"bindings": good["bindings"][:1]}, "unbound name"),
            ({"expression": "a"}, "not used"),
            ({"unit": "furlongs"}, "declared unit"),
            ({"label": "two\nlines"}, "label"),
            ({"bindings": [dict(good["bindings"][0], value=None), good["bindings"][1]]}, "finite number"),
            ({"bindings": [dict(good["bindings"][0], value=True), good["bindings"][1]]}, "finite number"),
            ({"bindings": [dict(good["bindings"][0], name="sqrt"), good["bindings"][1]]}, "identifier"),
            ({"bindings": [dict(good["bindings"][0], field="a.b"), good["bindings"][1]]}, "field"),
            ({"bindings": good["bindings"] * 2}, "duplicate")]:
        with pytest.raises(calc.CalcError, match=match):
            calc.check_request({**good, **change})
    assert calc.check_request({**good, "label": None})


def test_calc_evaluates_exactly_and_records_the_request():
    """The mq yield identity (design §2 P4) from the census values: Y = L * sigma * 10^3 * sel_w / tot_w."""
    values = {"lumi": ("luminosity_fb", 0.05), "xs": ("cross_section_pb", 760.535),
              "sel": ("selected_sum_weights", 66166.545), "tot": ("sum_weights", 76053.5)}
    full = calc.compute(request("lumi * xs * 10^3 * sel / tot", **values))
    assert math.isclose(full["result"], 33083.2725, rel_tol=1e-15)
    draft = calc.compute(request("lumi * xs * sel / tot", **values))
    assert math.isclose(draft["result"], 33.0832725, rel_tol=1e-15)
    assert full["literal"] == {"text": "10^3", "exponent": 3} and draft["literal"] is None
    assert [b["name"] for b in full["bindings"]] == ["lumi", "sel", "tot", "xs"]
    assert full["declared_unit"] == "events" and full["label"] == "selected-event prediction"
    assert math.isclose(calc.compute(request("sqrt(a) * 10^-2", a=("x", 4.0)))["result"], 0.02, rel_tol=1e-15)
    with pytest.raises(calc.CalcError, match="division by zero"):
        calc.compute(request("a / b", a=("x", 1.0), b=("y", 0.0)))
    with pytest.raises(calc.CalcError, match="negative"):
        calc.compute(request("sqrt(a)", a=("x", -1.0)))


def test_calc_worker_under_the_supervisor(tmp_path):
    values = {"lumi": ("luminosity_fb", 0.05), "xs": ("cross_section_pb", 760.535),
              "sel": ("selected_sum_weights", 66166.545), "tot": ("sum_weights", 76053.5)}
    good = request("lumi * xs * 10^3 * sel / tot", **values)
    code, content, failure = supervised(tmp_path / "ok", "calc", {"inputs/params.json": stages.params_bytes(good)})
    assert code == 0 and failure is None and content == calc.compute(good)
    # The worker checks the request itself: a request the broker would refuse fails the stage.
    for name, bad in (("plus", {**good, "expression": "lumi + xs + sel + tot"}),
                      ("null", request("a", a=("sigma_vis_obs_fb", None))),
                      ("zero", request("a / b", a=("x", 1.0), b=("y", 0.0)))):
        code, content, failure = supervised(tmp_path / name, "calc", {"inputs/params.json": stages.params_bytes(bad)})
        assert code != 0 and content is None and failure["type"] == "CalcError"


# ---------------------------------------------------------------- figure

def test_figure_records_the_legend_as_given(tmp_path):
    code, content, failure = supervised(tmp_path / "a", "figure", {
        "inputs/fit.json": encode(FIT), "inputs/params.json": stages.params_bytes({"legend": LEGEND})})
    assert code == 0 and failure is None
    assert content == {"schema_version": 1, "figure": "CLs scan", "note": "synthetic development fixture",
                       "legend": [{"series": "solid", "label": "Observed", "limit_events": "34.01"},
                                  {"series": "dashed", "label": "Expected (median)", "limit_events": "21.78"}]}
    swapped = figure.figure(FIT, {"legend": SWAPPED})               # fresh and wrong: the labels are swapped
    assert [(e["label"], e["limit_events"]) for e in swapped["legend"]] == [("Expected (median)", "34.01"),
                                                                           ("Observed", "21.78")]


@pytest.mark.parametrize("fit,legend,match", [
    ({**FIT, "limit_status": {"observed": "above_scan", "expected": ["resolved"] * 5}}, LEGEND, "not a resolved"),
    (FIT, LEGEND[::-1], "one entry per series"),
    (FIT, [LEGEND[0], {**LEGEND[1], "field": "sigma_vis_obs_fb"}], "legend field"),
    (FIT, [LEGEND[0], {**LEGEND[1], "extra": 1}], "exactly"),
])
def test_figure_refuses(fit, legend, match):
    with pytest.raises(ValueError, match=match):
        figure.figure(fit, {"legend": legend})
