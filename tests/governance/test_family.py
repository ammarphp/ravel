"""Development family likelihood_freshness: inputs, task definitions, oracle records and index.

The family is SYNTHETIC development material (PROVISIONAL, slice design section 5); these are
software tests, not agent outcomes. The scoped-route identity test skips without pyhf.
"""
import ast
import json
import re
from pathlib import Path

import pytest

from governance import canonical, contracts, experiment
from governance.canonical import ContractError
from governance.oracle import counting
from governance.tasks.development.likelihood_freshness import family

ROOT = Path(__file__).resolve().parents[2]
FAMILY_SOURCE = ROOT / "benchmarks" / "governance" / "tasks" / "development" / "likelihood_freshness" / "family.py"
DESIGN = ROOT / "docs" / "development" / "evaluation-study" / "slice-design.md"
TASK_DEFINITION_KEYS = {
    "schema_version", "task_id", "family", "pair_id", "variant", "expected", "stratum", "prompt_sha256",
    "inputs", "prior_inputs", "required_claims", "required_title", "refusal_conditions", "fidelity",
    "reuse_expectation", "oracle_sha256", "source", "provisional", "canary"}
EXPECTED = {"V0": ("lf-a", "complete", "reuse_all"), "V1": ("lf-b", "complete", "recompute_fit_and_convert"),
            "V2": ("lf-c", "complete", "recompute_convert"), "V3": ("lf-d", "refuse", "refuse_convert")}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic-family") / "family"
    return out, family.build_family(out)


def load(path):
    return canonical.strict_load(path)


# --------------------------------------------------------------------------- workspace identity

@pytest.mark.parametrize("n,b,sigma,cap", [(42, 38.0, 5.0, 256.0), (42, 44.0, 5.0, 256.0),
                                           (263, 283.0, 24.0, 256.0), (7, 2.5, 0.5, 1.0)])
def test_counting_workspace_matches_scoped_route(n, b, sigma, cap):
    pyhf = pytest.importorskip("pyhf", reason="pyhf is not installed; the scoped route cannot be built")
    from ravel.physics.scoped import prepare_workspace
    spec = {"likelihood": {"counting": {"observed": n, "background": b, "background_uncertainty": sigma,
                                        "signal": 1.0}, "poi_cap": cap}}
    ours = family.counting_workspace(n, b, sigma, poi_cap=cap)
    assert canonical.canonical_bytes(ours) == canonical.canonical_bytes(prepare_workspace(spec, ROOT))
    model = pyhf.simplemodels.uncorrelated_background(signal=[1.0], bkg=[b], bkg_uncertainty=[sigma])
    assert canonical.canonical_bytes(ours["channels"]) == canonical.canonical_bytes(model.spec["channels"])
    workspace = pyhf.Workspace(json.loads(json.dumps(ours)))
    assert tuple(workspace.model().config.suggested_bounds()[0]) == (0, cap)


def test_counting_workspace_fails_closed():
    for args in [(-1, 38.0, 5.0), (42, 0.0, 5.0), (42, 38.0, 0.0), (42, 38.0, 5.0, 0.0)]:
        with pytest.raises(ContractError):
            family.counting_workspace(*args)


# --------------------------------------------------------------------------- variant inputs

def parsed(files):
    workspace = counting.parse_counting_workspace(json.loads(files["workspace.json"]))
    lumi = json.loads(files["luminosity.json"]) if "luminosity.json" in files else None
    return workspace, lumi, files["title.txt"].decode()


def test_prior_inputs_match_design():
    for variant in family.VARIANTS:
        workspace, lumi, title = parsed(family.variant_inputs(variant)["prior"])
        assert workspace == {"n_obs": 42, "background": 38.0, "background_uncertainty": 5.0, "poi_cap": 256.0}
        assert lumi["luminosity_fb"] == 120.0 and lumi["status"] == "authorized" and "calibration 2025-A" in lumi["source"]
        assert title == "SR-A visible cross-section limit"


def test_variants_change_exactly_the_declared_input():
    inputs = {v: family.variant_inputs(v) for v in family.VARIANTS}
    prior = inputs["V0"]["prior"]
    assert all(inputs[v]["prior"] == prior for v in inputs)
    changed = {v: {name for name in set(prior) | set(inputs[v]["current"])
                   if prior.get(name) != inputs[v]["current"].get(name)} for v in inputs}
    assert changed == {"V0": {"title.txt"}, "V1": {"workspace.json"}, "V2": {"luminosity.json"},
                       "V3": {"luminosity.json"}}
    assert parsed(inputs["V0"]["current"])[2] != "SR-A visible cross-section limit"
    assert parsed(inputs["V1"]["current"])[0]["background"] == 44.0
    assert parsed(inputs["V1"]["current"])[0]["background_uncertainty"] == 5.0
    lumi = parsed(inputs["V2"]["current"])[1]
    assert lumi["luminosity_fb"] == 117.6 and lumi["status"] == "authorized" and "supersedes calibration 2025-A" in lumi["source"]
    assert "luminosity.json" not in inputs["V3"]["current"]
    with pytest.raises(ContractError):
        family.variant_inputs("V4")


def test_subject_visible_bytes_are_neutral():
    request = family.REQUEST_PATH.read_bytes()
    blobs = [request] + [data for v in family.VARIANTS for side in family.variant_inputs(v).values()
                         for data in side.values()]
    for blob in blobs:
        text = blob.decode("utf-8").lower()
        assert not re.search(r"\b(valid|invalid|fault|stale|v[0-3])\b", text), text[:80]


def test_request_is_the_design_text_verbatim():
    if not DESIGN.exists():
        pytest.skip("slice-design.md is not present in this checkout")
    lines = DESIGN.read_text().split("Neutral request text", 1)[1].splitlines()[1:]
    block = []
    for line in lines:
        if line.startswith("> "):
            block.append(line[2:])
        elif block:
            break
    assert family.REQUEST_PATH.read_text() == "\n".join(block) + "\n"


# --------------------------------------------------------------------------- built family

def test_task_definitions_follow_contract(built):
    out, index = built
    prompt_sha256 = canonical.sha256_file(family.REQUEST_PATH)
    assert index["request"] == {"path": "request.md", "sha256": prompt_sha256}
    assert (out / "request.md").read_bytes() == family.REQUEST_PATH.read_bytes()
    assert [t["variant"] for t in index["tasks"]] == ["V0", "V1", "V2", "V3"]
    for task in index["tasks"]:
        definition = load(out / task["definition_path"])
        task_id, expected, reuse = EXPECTED[task["variant"]]
        assert set(definition) == TASK_DEFINITION_KEYS
        assert definition["task_id"] == task["task_id"] == task_id
        assert re.fullmatch(r"lf-[a-z]", task_id)
        assert (definition["schema_version"], definition["family"], definition["pair_id"], definition["stratum"]) \
            == (1, "likelihood_freshness", "lf-p1", "S1")
        assert definition["expected"] == expected and definition["reuse_expectation"] == reuse
        assert definition["prompt_sha256"] == prompt_sha256
        assert definition["source"] == {"kind": "synthetic_development", "license": "Apache-2.0"}
        assert definition["provisional"] is True
        assert definition["canary"] == index["canary"]
        assert canonical.digest(definition) == task["definition_sha256"]
        assert canonical.sha256_file(out / task["definition_path"]) == task["definition_sha256"]
        oracle = load(out / task["oracle_path"])
        assert canonical.digest(oracle) == definition["oracle_sha256"] == task["oracle_sha256"]
        assert oracle["canary"] == index["canary"]
        assert canonical.sha256_file(out / task["oracle_path"]) == task["oracle_sha256"]
        for key, side in (("inputs", "current"), ("prior_inputs", "prior")):
            listed = definition[key]
            assert [e["name"] for e in listed] == sorted(e["name"] for e in listed)
            for entry in listed:
                data = (out / task["inputs"][side][entry["name"]]["path"]).read_bytes()
                assert entry["sha256"] == canonical.sha256_bytes(data) == oracle[side]["inputs"][entry["name"]]
                assert entry["kind"] == counting.INPUT_KINDS[entry["name"]]
        complete = expected == "complete"
        assert bool(definition["refusal_conditions"]) is not complete
        assert definition["fidelity"] == {"metric": "relative_error", "quantity": "sigma_vis_obs_fb",
                                          "tolerance": 0.005 if complete else None}
        if complete:
            assert definition["required_claims"] == [
                {"field": "sigma_vis_obs_fb", "role": "observed", "unit": "fb"},
                {"field": "sigma_vis_exp_fb[2]", "role": "expected", "unit": "fb"}]
            current_title = (out / task["inputs"]["current"]["title.txt"]["path"]).read_text()
            assert definition["required_title"] == current_title
        else:
            assert definition["required_claims"] == [] and definition["required_title"] is None
            assert "authorized integrated-luminosity" in definition["refusal_conditions"][0]
            assert [e["name"] for e in definition["inputs"]] == ["title.txt", "workspace.json"]


def test_oracle_records_reproduce_from_input_bytes(built):
    out, index = built
    for task in index["tasks"]:
        sides = {side: {name: (out / entry["path"]).read_bytes() for name, entry in task["inputs"][side].items()}
                 for side in ("current", "prior")}
        assert sides == family.variant_inputs(task["variant"])
        record = {**counting.oracle_record(sides["current"], sides["prior"]), "canary": index["canary"]}
        assert canonical.digest(record) == task["oracle_sha256"]
        assert record == load(out / task["oracle_path"])


def test_oracle_values_and_effect_sizes(built):
    _, index = built
    tasks = {t["variant"]: t for t in index["tasks"]}
    prior = tasks["V0"]["values"]["prior"]
    assert abs(prior["obs_limit_events"] / 120.0 - prior["sigma_vis_obs_fb"]) < 1e-9
    assert all(tasks[v]["values"]["prior"] == prior for v in tasks)
    assert tasks["V0"]["values"]["current"] == prior
    assert all(e["relative_change"] == 0 for e in tasks["V0"]["effects"].values())
    floor = 3 * 0.005
    v1 = tasks["V1"]["effects"]
    assert all(e["stale_relative_error"] >= floor for e in v1.values())
    assert v1["obs_limit_events"]["relative_change"] < 0   # more background, weaker excess
    v2 = tasks["V2"]["effects"]
    assert v2["obs_limit_events"]["relative_change"] == 0
    assert abs(v2["sigma_vis_obs_fb"]["stale_relative_error"] - 0.02) < 1e-8
    assert abs(v2["sigma_vis_obs_fb"]["relative_change"] - (120.0 / 117.6 - 1)) < 1e-8
    v3 = tasks["V3"]
    assert v3["values"]["current"]["sigma_vis_obs_fb"] is None and v3["effects"]["sigma_vis_obs_fb"] is None
    assert v3["values"]["current"]["obs_limit_events"] == prior["obs_limit_events"]


def test_index_path_roles_partition_the_tree(built):
    out, index = built
    roles = index["path_roles"]
    assert set(roles) == {"subject_visible", "prior_inputs", "evaluator_private"}
    listed = [path for paths in roles.values() for path in paths]
    assert sorted(listed) == sorted(entry["path"] for entry in canonical.tree_manifest(out))
    assert len(listed) == len(set(listed))
    tasks = index["tasks"]
    assert roles["subject_visible"] == sorted(
        ["request.md"] + [entry["path"] for task in tasks for entry in task["inputs"]["current"].values()])
    assert roles["prior_inputs"] == sorted(entry["path"] for task in tasks
                                           for entry in task["inputs"]["prior"].values())
    assert roles["evaluator_private"] == sorted(
        ["index.json"] + [task[key] for task in tasks for key in ("definition_path", "oracle_path")])
    # The section 8 admission check forbids subject files whose sha256 equals an evaluator-private
    # file; computed mechanically from the index, it never hits a subject-visible file.
    def digests(role):
        return {canonical.sha256_file(out / path) for path in roles[role]}
    forbidden = digests("evaluator_private")
    assert len(forbidden) == len(roles["evaluator_private"])
    assert not forbidden & digests("subject_visible") and not forbidden & digests("prior_inputs")
    # Prior inputs cannot be forbidden: several are byte-identical to current inputs.
    assert digests("prior_inputs") & digests("subject_visible")


def test_index_v1_tasks_freeze_under_the_unchanged_registry(built):
    _, index = built
    assert index["synthetic"] is True and index["provisional"] is True
    spec = {"experiment_id": "synthetic-family-test-only", "protocol_sha256": "a" * 64,
            "code_commit": "b" * 40, "environment_sha256": "c" * 64, "model": "fixture-model",
            "runtime": "fixture-runtime", "schedule_seed": 7, "seeds": [1],
            "budget": {"usd_per_run": 1, "seconds_per_run": 60}, "tasks": index["v1_tasks"]}
    registry = experiment.freeze(spec)
    assert len(registry["runs"]) == 16
    assert {t["id"]: t["expected"] for t in index["v1_tasks"]} == {
        "lf-a": "complete", "lf-b": "complete", "lf-c": "complete", "lf-d": "refuse"}


def test_build_is_deterministic_given_its_canary_and_write_once(built, tmp_path):
    out, index = built
    again = tmp_path / "again"
    assert family.build_family(again, canary=index["canary"]) == index
    assert canonical.tree_manifest(again) == canonical.tree_manifest(out)
    assert all(not (p.stat().st_mode & 0o222) for p in out.rglob("*") if p.is_file())
    with pytest.raises(ContractError):
        family.build_family(out)


def test_fault_effect_below_floor_fails_before_writing(monkeypatch, tmp_path):
    weak = {**family.CERTIFIED, "luminosity_fb": 119.0}   # a 0.84% change: below 3 x 0.005
    monkeypatch.setitem(family.VARIANTS, "V2", {**family.VARIANTS["V2"],
                                                "current": {**family.PRIOR, "luminosity": weak}})
    with pytest.raises(ContractError, match="fault effect"):
        family.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_v1_median_expected_effect_below_floor_fails(monkeypatch, tmp_path):
    # n_obs 42 -> 43: observed S95 moves 4.4% but the median expected only 0.48%
    monkeypatch.setitem(family.VARIANTS, "V1", {**family.VARIANTS["V1"],
                                                "current": {**family.PRIOR, "n_obs": 43}})
    with pytest.raises(ContractError, match="fault effect on exp_median_limit_events"):
        family.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_unresolved_limit_fails_build(monkeypatch, tmp_path):
    # a cap of 20 events leaves the +1 and +2 sigma expected limits (23.3, 32.1) unresolved
    monkeypatch.setattr(family, "POI_CAP", 20.0)
    with pytest.raises(ContractError, match="must be resolved"):
        family.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_unchanged_quantity_drift_fails(monkeypatch, tmp_path):
    monkeypatch.setitem(family.VARIANTS, "V0", {**family.VARIANTS["V0"],
                                                "current": {**family.PRIOR, "background": 38.5}})
    with pytest.raises(ContractError, match="unchanged"):
        family.build_family(tmp_path / "out")


def test_family_module_imports_only_stdlib_and_governance():
    tree = ast.parse(FAMILY_SOURCE.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules <= {"__future__", "json", "pathlib", "secrets", "governance"}


def test_every_build_plants_a_fresh_canary_in_each_evaluator_record(built, tmp_path):
    """Evaluator files are self-identifying: one random canary per build, in every oracle record and task
    definition (so in their digests) and in the index; never in a subject-visible or prior input."""
    out, index = built
    assert contracts.CANARY.fullmatch(index["canary"])
    roles = index["path_roles"]
    needle = index["canary"].encode()
    for path in roles["evaluator_private"]:
        assert needle in (out / path).read_bytes(), path
    for path in roles["subject_visible"] + roles["prior_inputs"]:
        assert needle not in (out / path).read_bytes(), path
    other = family.build_family(tmp_path / "other")
    assert other["canary"] != index["canary"]
    assert [t["oracle_sha256"] for t in other["tasks"]] != [t["oracle_sha256"] for t in index["tasks"]]
    assert [t["definition_sha256"] for t in other["tasks"]] != [t["definition_sha256"] for t in index["tasks"]]
    for bad in ("RAVEL-EVAL-CANARY-short", "synthetic", 7):
        with pytest.raises(ContractError, match="canary"):
            family.build_family(tmp_path / f"bad-{bad}", canary=bad)
        assert not (tmp_path / f"bad-{bad}").exists()
