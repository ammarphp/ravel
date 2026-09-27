"""Regression lock for the v1 governance registry contract (evaluation slice WP03).

Pins the current behavior of benchmarks/governance/experiment.py, which stays unmodified
(decisions.md E-05). Every spec, registry, outcome row and cohort below is a SYNTHETIC software
fixture, never an agent result. Packet catalogs/tests.json coverage: CONTRACT_01-08 and 10-15.
CONTRACT_09 (declared versus actual prompt/oracle bytes) and CONTRACT_16 (synthetic/empirical
quarantine) are not v1 checks; they belong to the campaign manifest (slice-design section 4.1).
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from governance import canonical, experiment

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks" / "governance" / "experiment.py"

# Golden identity of golden_spec(), computed once from the unmodified v1 code and hard-coded.
# A change to these literals means v1 registry identity changed (spec digest, run_id derivation,
# arm order, schedule shuffle or canonical serialization): every archived registry and outcomes
# document would stop verifying. Never update them just to make a failing test pass.
GOLDEN_REGISTRY_SHA256 = "90304c0a4f0c5ab1bf1b3c80c211da20b11d33ed60dde9baa9ed7a627ea7750f"
GOLDEN_FIRST_RUNS = [  # (run_id, task_id, seed, arm) in schedule order
    ("a0326e57aa9f3178304f763f8ceb28aace8b97c0edb889136039aaedf83a07fa", "lf-c", 11, "full"),
    ("658f6bff9f4402623ce22b75ae30b2b195082de6083de56870585e92fc814144", "lf-b", 11, "instructions"),
    ("35b6d8be7db6dd06683ea2ca4574de30df36691db807a07d8cfea7c918309670", "lf-a", 11, "enforcement"),
]
# Golden identity of unsorted_spec() (tasks and seeds deliberately out of sorted order), computed
# once like the literals above; a change means v1 registry identity changed (e.g. freeze() started
# sorting tasks or seeds, which golden_spec() alone cannot detect because its lists are sorted).
UNSORTED_REGISTRY_SHA256 = "39495d54c78bf1b6ba58ebd1cd63f2b96b9185bc50584e5d005be63a5f047705"
UNSORTED_FIRST_RUNS = [  # (run_id, task_id, seed, arm) in schedule order
    ("5f339c6207180fa522e7298debcda09ef1acf588d54a651e7075169bc008e67c", "lf-b", 29, "enforcement"),
    ("9feb883ae9131df944e16d87c84a8c372d364a7cb4bf5fe1b822e880b783cedd", "lf-c", 11, "instructions"),
    ("1f8b530e9edf4255667dab060caf533e3c8437285272e643c169ed8b14ed6f03", "lf-c", 5, "full"),
]
# sha256 of the CLI `freeze` stdout for json.dumps(golden_spec()) written to a file: indent=2, input
# key order, trailing newline. This is NOT the registry identity and NOT the registry.json bytes that
# slice-design section 4.1 verifies (those are canonical_bytes of freeze(spec)); a change means the
# v1 CLI output format changed.
GOLDEN_FREEZE_STDOUT_SHA256 = "d6659a2c31986ea577030f6a2de2ea473e58a9cc402f2d838d9b849eb342e011"
# Per-arm summary of the verified golden cohort; compared by canonical bytes, so int/float types count.
GOLDEN_ARM_SUMMARY = {
    "planned": 6, "status_counts": {"completed": 4, "crash": 0, "not_started": 0, "refused": 2, "timeout": 0},
    "unsupported_claims": 0, "unadjudicated": 0, "unsupported_claim_rate": 0.0,
    "unsupported_claim_rate_bounds": [0.0, 0.0], "completion_controls": 4, "verified_completions": 4,
    "verified_completion_rate": 1.0, "refusals_on_completion_controls": 0, "refusal_controls": 2,
    "verified_valid_refusals": 2, "verified_valid_refusal_rate": 1.0, "fidelity_scored": 2,
    "fidelity_by_task": {"lf-a": {"planned": 2, "scored": 2, "median_known": 0.001, "tolerance": 0.005},
                         "lf-b": {"planned": 2, "scored": 0, "median_known": None, "tolerance": None}},
    "cost_usd": {"known_sum": 1.5, "known_runs": 6, "missing_runs": 0, "mean_known": 0.25},
    "wall_seconds": {"known_sum": 720, "known_runs": 6, "missing_runs": 0, "mean_known": 120.0},
    "interventions": {"known_sum": 0, "known_runs": 6, "missing_runs": 0, "mean_known": 0.0},
}

ARMS = {"baseline": {"instructions": False, "enforcement": False},
        "instructions": {"instructions": True, "enforcement": False},
        "enforcement": {"instructions": False, "enforcement": True},
        "full": {"instructions": True, "enforcement": True}}
FIELDS = {  # exact keys per level, keyed by the label v1 uses in its error messages
    "spec": {"experiment_id", "protocol_sha256", "code_commit", "environment_sha256", "model",
             "runtime", "schedule_seed", "seeds", "tasks", "budget"},
    "budget": {"usd_per_run", "seconds_per_run"},
    "task": {"id", "expected", "prompt_sha256", "oracle_sha256", "fidelity_tolerance"},
    "registry": {"schema_version", "spec", "arms", "runs", "registry_sha256"},
    "outcomes document": {"schema_version", "registry_sha256", "outcomes"},
    "outcome": {"run_id", "status", "unsupported_claim", "refusal_valid", "fidelity_error", "cost_usd",
                "wall_seconds", "interventions", "executor_id", "scorer_id", "evidence_sha256", "notes"},
}
REGISTRY_ALTERED = "registry altered, incomplete, or not in canonical schedule order"
NOT_A_NUMBER = "expected finite nonnegative number"


def golden_spec():
    """Synthetic spec: numeric and non-numeric completion controls plus one refusal control."""
    return {
        "experiment_id": "synthetic-v1-contract-lock-golden",
        "protocol_sha256": "0123456789abcdef" * 4, "code_commit": "fedcba9876543210" * 2 + "01234567",
        "environment_sha256": "89abcdef01234567" * 4,
        "model": "synthetic-fixture-model", "runtime": "synthetic-fixture-runtime",
        "schedule_seed": 20260925, "seeds": [11, 29],
        "budget": {"usd_per_run": 2.5, "seconds_per_run": 1800},
        "tasks": [
            {"id": "lf-a", "expected": "complete", "prompt_sha256": "a" * 64, "oracle_sha256": "b" * 64,
             "fidelity_tolerance": 0.005},
            {"id": "lf-b", "expected": "complete", "prompt_sha256": "c" * 64, "oracle_sha256": "d" * 64,
             "fidelity_tolerance": None},
            {"id": "lf-c", "expected": "refuse", "prompt_sha256": "e" * 64, "oracle_sha256": "f" * 64,
             "fidelity_tolerance": None},
        ],
    }


def unsorted_spec():
    """Synthetic golden variant whose task and seed lists are not in sorted order."""
    spec = golden_spec()
    spec["experiment_id"] = "synthetic-v1-contract-lock-unsorted"
    spec["seeds"] = [29, 11, 5]
    spec["tasks"] = [spec["tasks"][i] for i in (2, 0, 1)]  # lf-c, lf-a, lf-b
    return spec


def verified_row(run, spec):
    """Synthetic, independently judged, verified outcome for one planned run."""
    task = next(t for t in spec["tasks"] if t["id"] == run["task_id"])
    complete = task["expected"] == "complete"
    return {"run_id": run["run_id"], "status": "completed" if complete else "refused",
            "unsupported_claim": False, "refusal_valid": None if complete else True,
            "fidelity_error": None if task["fidelity_tolerance"] is None else 0.001,
            "cost_usd": 0.25, "wall_seconds": 120, "interventions": 0,
            "executor_id": "synthetic-executor", "scorer_id": "synthetic-independent-scorer",
            "evidence_sha256": "9" * 64, "notes": "Synthetic fixture only; not an agent result"}


def not_started_fields():
    return {"status": "not_started", "unsupported_claim": None, "refusal_valid": None,
            "fidelity_error": None, "cost_usd": 0, "wall_seconds": 0, "interventions": 0,
            "executor_id": None, "scorer_id": None, "evidence_sha256": None,
            "notes": "Synthetic fixture: scheduler stopped before launch"}


def cohort(spec=None):
    """Synthetic verified cohort. Deep-copied: freeze() aliases experiment.ARMS (see below)."""
    spec = golden_spec() if spec is None else spec
    registry = copy.deepcopy(experiment.freeze(spec))
    rows = [verified_row(run, spec) for run in registry["runs"]]
    return registry, {"schema_version": 1, "registry_sha256": registry["registry_sha256"], "outcomes": rows}


@pytest.fixture(autouse=True)
def arms_constant_untouched():
    """Fail loudly if a test corrupts the module-level arm table that every later freeze uses."""
    before = copy.deepcopy(experiment.ARMS)
    yield
    assert experiment.ARMS == before and list(experiment.ARMS) == list(before)


def row(registry, outcomes, task_id, arm, seed=11):
    run_id = next(r["run_id"] for r in registry["runs"]
                  if (r["task_id"], r["arm"], r["seed"]) == (task_id, arm, seed))
    return next(o for o in outcomes["outcomes"] if o["run_id"] == run_id)


def arm_rows(registry, outcomes, arm):
    ids = {r["run_id"] for r in registry["runs"] if r["arm"] == arm}
    return [o for o in outcomes["outcomes"] if o["run_id"] in ids]


def schedule_head(registry):
    return [(r["run_id"], r["task_id"], r["seed"], r["arm"]) for r in registry["runs"][:3]]


def body(registry):
    return {k: v for k, v in registry.items() if k != "registry_sha256"}


def rejects(message, call, *args):
    with pytest.raises(ValueError, match=re.escape(message)):
        call(*args)


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=ROOT,
                          capture_output=True, timeout=60)


def write(path, text):
    path.write_text(text)
    return path


# ---- golden identity and determinism (CONTRACT_10) ---------------------------------------------

def test_golden_registry_identity_is_pinned():
    spec = golden_spec()
    registry = experiment.freeze(spec)
    assert registry["registry_sha256"] == GOLDEN_REGISTRY_SHA256
    assert schedule_head(registry) == GOLDEN_FIRST_RUNS
    assert canonical.digest(body(registry)) == experiment.digest(body(registry)) == GOLDEN_REGISTRY_SHA256
    spec_sha256 = canonical.digest(spec)
    for run in registry["runs"]:  # every run_id binds the complete frozen spec
        assert run["run_id"] == canonical.digest({"spec_sha256": spec_sha256, "task_id": run["task_id"],
                                                  "seed": run["seed"], "arm": run["arm"]})


def test_unsorted_golden_identity_is_pinned_and_list_order_is_part_of_it():
    spec = unsorted_spec()
    registry = experiment.freeze(spec)
    assert registry["registry_sha256"] == UNSORTED_REGISTRY_SHA256
    assert schedule_head(registry) == UNSORTED_FIRST_RUNS
    assert registry["spec"] == spec and len(registry["runs"]) == 36
    assert [t["id"] for t in registry["spec"]["tasks"]] == ["lf-c", "lf-a", "lf-b"]
    assert registry["spec"]["seeds"] == [29, 11, 5]
    # documented v1 behavior: task and seed list order is identity, not presentation. The same
    # design with sorted lists is a different registry with no run_id in common.
    resorted = copy.deepcopy(spec)
    resorted["tasks"].sort(key=lambda t: t["id"])
    resorted["seeds"].sort()
    other = experiment.freeze(resorted)
    assert other["registry_sha256"] != UNSORTED_REGISTRY_SHA256
    assert not {r["run_id"] for r in other["runs"]} & {r["run_id"] for r in registry["runs"]}


def test_golden_roster_is_full_factorial_with_fixed_arms_and_statuses():
    registry = experiment.freeze(golden_spec())
    assert set(registry) == FIELDS["registry"] and registry["schema_version"] == 1
    assert registry["spec"] == golden_spec()
    assert experiment.ARMS == registry["arms"] == ARMS and list(experiment.ARMS) == list(ARMS)
    assert experiment.STATUSES == {"completed", "refused", "timeout", "crash", "not_started"}
    cells = sorted((r["task_id"], r["seed"], r["arm"]) for r in registry["runs"])
    assert cells == sorted((t, s, a) for t in ("lf-a", "lf-b", "lf-c") for s in (11, 29) for a in ARMS)
    assert len({r["run_id"] for r in registry["runs"]}) == 24


def test_freeze_returns_the_module_arm_table_by_reference():
    # documented v1 behavior: registry["arms"] IS experiment.ARMS, so editing a frozen registry's
    # arms in place changes every later freeze in the process. Callers must copy before editing.
    assert experiment.freeze(golden_spec())["arms"] is experiment.ARMS


def test_canonical_helpers_serialize_exactly_like_v1_digest():
    value = {"b": [1.5, 2, None, True, -0.0], "a": "synthetic σ_vis → fb", "c": {"z": 0.1, "y": "x"}}
    assert canonical.digest(value) == experiment.digest(value)


def test_freeze_is_deterministic_and_independent_of_key_order(tmp_path):
    first, second = experiment.freeze(golden_spec()), experiment.freeze(golden_spec())
    assert canonical.canonical_bytes(first) == canonical.canonical_bytes(second)
    reordered = dict(reversed(list(golden_spec().items())))
    assert canonical.canonical_bytes(experiment.freeze(reordered)) == canonical.canonical_bytes(first)
    spec_path = write(tmp_path / "spec.json", json.dumps(golden_spec()))
    a, b = cli("freeze", spec_path), cli("freeze", spec_path)
    assert a.returncode == b.returncode == 0 and a.stdout == b.stdout


@pytest.mark.parametrize("field,value", [("schedule_seed", 20260926), ("model", "synthetic-other-model"),
                                         ("code_commit", "0" * 40)])
def test_any_spec_change_renews_every_run_id(field, value):
    spec = golden_spec()
    spec[field] = value
    changed = experiment.freeze(spec)
    assert changed["registry_sha256"] != GOLDEN_REGISTRY_SHA256
    golden_ids = {r["run_id"] for r in experiment.freeze(golden_spec())["runs"]}
    assert not golden_ids & {r["run_id"] for r in changed["runs"]}


def test_golden_summary_shape_and_values_are_pinned():
    registry, outcomes = cohort()
    summary = experiment.score(registry, outcomes)
    assert set(summary) == {"schema_version", "registry_sha256", "interpretation", "arms"}
    assert summary["schema_version"] == 1 and summary["registry_sha256"] == GOLDEN_REGISTRY_SHA256
    assert summary["interpretation"] == "descriptive_only_no_causal_or_population_inference"
    assert list(summary["arms"]) == list(ARMS)
    for arm in summary["arms"].values():
        assert arm == GOLDEN_ARM_SUMMARY
        assert canonical.canonical_bytes(arm) == canonical.canonical_bytes(GOLDEN_ARM_SUMMARY)


# ---- CLI round trip ----------------------------------------------------------------------------

def test_cli_freeze_then_score_round_trip(tmp_path):
    frozen = cli("freeze", write(tmp_path / "spec.json", json.dumps(golden_spec())))
    assert frozen.returncode == 0 and frozen.stderr == b""
    registry_path = tmp_path / "registry.json"
    registry_path.write_bytes(frozen.stdout)
    registry = experiment.load_json(registry_path)
    assert registry == experiment.freeze(golden_spec())
    assert registry["registry_sha256"] == GOLDEN_REGISTRY_SHA256
    _, outcomes = cohort()
    scored = cli("score", registry_path, write(tmp_path / "outcomes.json", json.dumps(outcomes)))
    assert scored.returncode == 0 and scored.stderr == b""
    summary = canonical.strict_loads(scored.stdout.decode())
    assert summary == experiment.score(registry, outcomes)
    assert summary["arms"]["full"] == GOLDEN_ARM_SUMMARY


def test_cli_output_bytes_are_the_pinned_v1_format(tmp_path):
    # documented v1 behavior: the CLI prints indent=2 JSON in input key order plus a newline. These
    # bytes are not canonical_bytes, so CLI stdout is never the registry.json that the campaign
    # manifest verifies (slice-design section 4.1 re-serializes freeze(spec) canonically).
    frozen = cli("freeze", write(tmp_path / "spec.json", json.dumps(golden_spec())))
    assert frozen.returncode == 0
    assert canonical.sha256_bytes(frozen.stdout) == GOLDEN_FREEZE_STDOUT_SHA256
    registry = experiment.freeze(golden_spec())
    assert frozen.stdout == (json.dumps(registry, indent=2, allow_nan=False) + "\n").encode()
    assert frozen.stdout.rstrip(b"\n") != canonical.canonical_bytes(registry)
    registry_path = tmp_path / "registry.json"
    registry_path.write_bytes(frozen.stdout)
    _, outcomes = cohort()
    scored = cli("score", registry_path, write(tmp_path / "outcomes.json", json.dumps(outcomes)))
    summary = experiment.score(registry, outcomes)
    assert scored.returncode == 0
    assert scored.stdout == (json.dumps(summary, indent=2, allow_nan=False) + "\n").encode()


def cli_error_case(name):
    """Return (command, file texts or None for an absent file, expected stderr fragment)."""
    spec = golden_spec()
    registry, outcomes = cohort()
    if name == "missing spec field":
        del spec["budget"]
        return "freeze", [json.dumps(spec)], "spec: fields must be"
    if name == "duplicate spec key":
        return "freeze", [json.dumps(spec)[:-1] + ', "schedule_seed": 7}'], "duplicate JSON field: schedule_seed"
    if name == "NaN in spec":
        spec["budget"]["usd_per_run"] = float("nan")
        return "freeze", [json.dumps(spec)], "nonfinite JSON constant: NaN"
    if name == "boolean seed":
        spec["seeds"] = [True, 29]
        return "freeze", [json.dumps(spec)], f"seed: {NOT_A_NUMBER}"
    if name == "absent file":
        return "freeze", None, "No such file"
    if name == "incomplete accounting":
        outcomes["outcomes"].pop()
        return "score", [json.dumps(registry), json.dumps(outcomes)], "missing=1, unplanned=0"
    if name == "reordered registry":
        registry["runs"][0], registry["runs"][1] = registry["runs"][1], registry["runs"][0]
        return "score", [json.dumps(registry), json.dumps(outcomes)], REGISTRY_ALTERED
    if name == "duplicate judgment key":
        text = json.dumps(outcomes).replace('"unsupported_claim": false',
                                            '"unsupported_claim": true, "unsupported_claim": false', 1)
        return "score", [json.dumps(registry), text], "duplicate JSON field: unsupported_claim"
    if name == "duplicate registry key":  # a last-key-wins parser would accept this registry
        text = json.dumps(registry)[:-1] + ', "schema_version": 1}'
        return "score", [text, json.dumps(outcomes)], "duplicate JSON field: schema_version"
    if name == "NaN in registry":  # a lenient parser would reach freeze() and fail differently
        registry["spec"]["budget"]["usd_per_run"] = float("nan")
        return "score", [json.dumps(registry), json.dumps(outcomes)], "nonfinite JSON constant: NaN"
    assert name == "Infinity in outcomes"
    outcomes["outcomes"][0]["cost_usd"] = float("inf")
    return "score", [json.dumps(registry), json.dumps(outcomes)], "nonfinite JSON constant: Infinity"


@pytest.mark.parametrize("name", ["missing spec field", "duplicate spec key", "NaN in spec", "boolean seed",
                                  "absent file", "incomplete accounting", "reordered registry",
                                  "duplicate judgment key", "duplicate registry key", "NaN in registry",
                                  "Infinity in outcomes"])
def test_cli_validation_error_exits_2_without_output(tmp_path, name):
    command, texts, expected = cli_error_case(name)
    paths = ([tmp_path / "absent.json"] if texts is None
             else [write(tmp_path / f"input{i}.json", text) for i, text in enumerate(texts)])
    result = cli(command, *paths)
    assert result.returncode == 2
    assert result.stdout == b""
    stderr = result.stderr.decode()
    assert stderr.startswith("experiment error: ") and expected in stderr


# ---- exact keys at every level (CONTRACT_03) ---------------------------------------------------

def mutate_level(level, edit):
    """Apply edit to the object at one contract level; return the v1 call that must reject it."""
    spec = golden_spec()
    if level in ("spec", "budget", "task"):
        edit({"spec": spec, "budget": spec["budget"], "task": spec["tasks"][0]}[level])
        return lambda: experiment.freeze(spec)
    registry, outcomes = cohort()
    edit({"registry": registry, "outcomes document": outcomes, "outcome": outcomes["outcomes"][0]}[level])
    return lambda: experiment.score(registry, outcomes)


@pytest.mark.parametrize("level,field", [(level, field) for level, fields in FIELDS.items()
                                         for field in sorted(fields)])
def test_missing_field_rejected_at_every_level(level, field):
    rejects(f"{level}: fields must be {sorted(FIELDS[level])}", mutate_level(level, lambda obj: obj.pop(field)))


@pytest.mark.parametrize("level", FIELDS)
def test_unknown_field_rejected_at_every_level(level):
    call = mutate_level(level, lambda obj: obj.update(unexpected_field=None))
    rejects(f"{level}: fields must be {sorted(FIELDS[level])}", call)


@pytest.mark.parametrize("level", FIELDS)
def test_non_object_rejected_at_every_level(level):
    spec = golden_spec()
    registry, outcomes = cohort()
    calls = {
        "spec": lambda: experiment.freeze([spec]),
        "budget": lambda: experiment.freeze({**spec, "budget": [2.5, 1800]}),
        "task": lambda: experiment.freeze({**spec, "tasks": [["lf-a"]] + spec["tasks"][1:]}),
        "registry": lambda: experiment.score([registry], outcomes),
        "outcomes document": lambda: experiment.score(registry, [outcomes]),
        "outcome": lambda: experiment.score(registry, {**outcomes,
                                                       "outcomes": [None] + outcomes["outcomes"][1:]}),
    }
    rejects(f"{level}: expected object", calls[level])


@pytest.mark.parametrize("field,value,message", [
    ("model", ["synthetic-model-a", "synthetic-model-b"], "model: required"),
    ("model", {"provider": "synthetic", "name": "model-a"}, "model: required"),
    ("runtime", ["synthetic-runtime-a", "synthetic-runtime-b"], "runtime: required"),
    ("model", "  ", "model: required"),
    ("experiment_id", "", "experiment_id: required"),
    ("models", ["synthetic-model-a", "synthetic-model-b"], "spec: fields must be"),
])
def test_one_model_and_runtime_per_spec(field, value, message):
    spec = golden_spec()
    spec[field] = value
    rejects(message, experiment.freeze, spec)


# ---- strict JSON (CONTRACT_01, CONTRACT_02) ----------------------------------------------------

def spec_file_text(case):
    spec = golden_spec()
    if case == "duplicate top-level key":
        return json.dumps(spec)[:-1] + ', "schedule_seed": 7}'
    if case == "duplicate nested key":
        return json.dumps(spec).replace('"expected": "refuse"', '"expected": "complete", "expected": "refuse"')
    if case == "NaN":
        spec["budget"]["usd_per_run"] = float("nan")
    elif case == "Infinity":
        spec["budget"]["seconds_per_run"] = float("inf")
    else:
        spec["tasks"][0]["fidelity_tolerance"] = float("-inf")
    return json.dumps(spec)


@pytest.mark.parametrize("case,message", [
    ("duplicate top-level key", "duplicate JSON field: schedule_seed"),
    ("duplicate nested key", "duplicate JSON field: expected"),
    ("NaN", "nonfinite JSON constant: NaN"),
    ("Infinity", "nonfinite JSON constant: Infinity"),
    ("-Infinity", "nonfinite JSON constant: -Infinity"),
])
def test_ambiguous_or_nonfinite_json_file_is_rejected_before_freeze(tmp_path, case, message):
    path = write(tmp_path / "spec.json", spec_file_text(case))
    rejects(message, experiment.load_json, path)
    with pytest.raises(canonical.ContractError, match=re.escape(message)):  # shared helper agrees
        canonical.strict_load(path)


def test_overflowing_float_literal_loads_as_infinity_then_fails_validation(tmp_path):
    # documented v1 behavior: the v1 loader guards the NaN/Infinity constants only; a literal such
    # as 1e400 parses to inf and is caught by the finite check. The harness loader
    # (canonical.strict_loads) rejects the overflowing literal at parse time instead.
    text = json.dumps(golden_spec()).replace('"usd_per_run": 2.5', '"usd_per_run": 1e400')
    spec = experiment.load_json(write(tmp_path / "spec.json", text))
    assert spec["budget"]["usd_per_run"] == float("inf")
    with pytest.raises(canonical.ContractError, match="overflows"):
        canonical.strict_loads(text)
    rejects(f"usd_per_run: {NOT_A_NUMBER}", experiment.freeze, spec)


# ---- typed numbers and booleans (CONTRACT_04) --------------------------------------------------

@pytest.mark.parametrize("edit,message", [
    (lambda s: s.update(seeds=[True, 29]), f"seed: {NOT_A_NUMBER}"),
    (lambda s: s.update(seeds=[11, 29.0]), f"seed: {NOT_A_NUMBER}"),
    (lambda s: s.update(seeds=[-1, 29]), f"seed: {NOT_A_NUMBER}"),
    (lambda s: s.update(schedule_seed=False), f"schedule_seed: {NOT_A_NUMBER}"),
    (lambda s: s.update(schedule_seed=True), f"schedule_seed: {NOT_A_NUMBER}"),
    (lambda s: s.update(schedule_seed=42.0), f"schedule_seed: {NOT_A_NUMBER}"),
    (lambda s: s["budget"].update(usd_per_run=True), f"usd_per_run: {NOT_A_NUMBER}"),
    (lambda s: s["budget"].update(usd_per_run=float("nan")), f"usd_per_run: {NOT_A_NUMBER}"),
    (lambda s: s["budget"].update(seconds_per_run=0), "seconds_per_run: must be positive"),
    (lambda s: s["tasks"][0].update(fidelity_tolerance=True), f"fidelity_tolerance: {NOT_A_NUMBER}"),
    (lambda s: s["tasks"][0].update(fidelity_tolerance=-0.005), f"fidelity_tolerance: {NOT_A_NUMBER}"),
], ids=["seed True", "seed float", "seed negative", "schedule_seed False", "schedule_seed True",
        "schedule_seed float", "budget True", "budget NaN", "budget zero", "tolerance True",
        "tolerance negative"])
def test_spec_numbers_are_typed_finite_and_nonnegative(edit, message):
    spec = golden_spec()
    edit(spec)
    rejects(message, experiment.freeze, spec)


@pytest.mark.parametrize("field,value,message", [
    ("interventions", True, f"interventions: {NOT_A_NUMBER}"),
    ("interventions", 1.0, f"interventions: {NOT_A_NUMBER}"),
    ("cost_usd", False, f"cost_usd: {NOT_A_NUMBER}"),
    ("wall_seconds", -1, f"wall_seconds: {NOT_A_NUMBER}"),
    ("fidelity_error", float("inf"), f"fidelity_error: {NOT_A_NUMBER}"),
    ("unsupported_claim", 0, "unsupported_claim: boolean or null"),
    ("refusal_valid", 1, "refusal_valid: boolean or null"),
])
def test_outcome_numbers_and_judgments_are_typed(field, value, message):
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-a", "baseline")[field] = value
    rejects(message, experiment.score, registry, outcomes)


@pytest.mark.parametrize("value", [True, 1.0, 2, "1"])
@pytest.mark.parametrize("document", ["registry", "outcomes"])
def test_schema_version_is_exactly_integer_one(document, value):
    registry, outcomes = cohort()
    (registry if document == "registry" else outcomes)["schema_version"] = value
    rejects(f"{document} schema_version: expected 1", experiment.score, registry, outcomes)


# ---- source identity and hashes (CONTRACT_05) --------------------------------------------------

@pytest.mark.parametrize("value", ["f" * 39, "f" * 41, "fedcba9", "F" * 40, "g" * 40, "f" * 40 + "\n",
                                   "f" * 64, None, 0])
def test_code_commit_must_be_full_lowercase_git_sha1(value):
    spec = golden_spec()
    spec["code_commit"] = value
    rejects("code_commit: expected full Git SHA-1", experiment.freeze, spec)


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 40, " " + "a" * 63, None])
@pytest.mark.parametrize("field", ["protocol_sha256", "environment_sha256", "prompt_sha256", "oracle_sha256",
                                   "run_id", "evidence_sha256"])
def test_sha256_fields_require_64_lowercase_hex(field, value):
    if field in ("run_id", "evidence_sha256"):
        registry, outcomes = cohort()
        outcomes["outcomes"][0][field] = value
        message = ("outcome run_id: invalid" if field == "run_id"
                   else "started run requires evidence manifest SHA-256")
        rejects(message, experiment.score, registry, outcomes)
        return
    spec = golden_spec()
    if field in ("prompt_sha256", "oracle_sha256"):
        spec["tasks"][0][field] = value
        message = f"task {field}: expected SHA-256"
    else:
        spec[field] = value
        message = f"{field}: expected SHA-256"
    rejects(message, experiment.freeze, spec)


# ---- design validation (CONTRACT_06, CONTRACT_07, CONTRACT_08) ---------------------------------

@pytest.mark.parametrize("edit,message", [
    (lambda s: s["tasks"][1].update(id="lf-a"), "task id: empty or duplicate"),
    (lambda s: s["tasks"][1].update(id=""), "task id: empty or duplicate"),
    (lambda s: s["tasks"][1].update(id="  "), "task id: empty or duplicate"),
    (lambda s: s["tasks"][1].update(id=7), "task id: empty or duplicate"),
    (lambda s: s.update(seeds=[11, 11]), "seeds: duplicates"),
    (lambda s: s.update(seeds=[]), "seeds: nonempty list required"),
    (lambda s: s.update(seeds=11), "seeds: nonempty list required"),
    (lambda s: s.update(tasks=[]), "tasks: nonempty list required"),
], ids=["duplicate task id", "empty task id", "blank task id", "non-string task id", "duplicate seeds",
        "no seeds", "scalar seeds", "no tasks"])
def test_task_ids_and_repeats_must_be_unique_and_present(edit, message):
    spec = golden_spec()
    edit(spec)
    rejects(message, experiment.freeze, spec)


@pytest.mark.parametrize("kept", [["lf-a", "lf-b"], ["lf-c"]], ids=["completion only", "refusal only"])
def test_both_completion_and_refusal_controls_are_required(kept):
    spec = golden_spec()
    spec["tasks"] = [t for t in spec["tasks"] if t["id"] in kept]
    rejects("include both completion and refusal controls", experiment.freeze, spec)
    spec["tasks"][0]["expected"] = "abstain"
    rejects("task expected: complete or refuse", experiment.freeze, spec)


@pytest.mark.parametrize("tolerance", [0.005, 0, 0.0])
def test_refusal_task_rejects_numeric_tolerance(tolerance):
    spec = golden_spec()
    spec["tasks"][2]["fidelity_tolerance"] = tolerance
    rejects("refusal task: fidelity_tolerance must be null", experiment.freeze, spec)


# ---- mutated registry (CONTRACT_11) ------------------------------------------------------------

def _swap_first_runs(registry):
    registry["runs"][0], registry["runs"][1] = registry["runs"][1], registry["runs"][0]


def _flip_last_hex(value):
    return value[:-1] + ("0" if value[-1] != "0" else "1")


REGISTRY_MUTATIONS = {
    "reordered runs": _swap_first_runs,
    "reordered runs with recomputed digest": lambda r: (_swap_first_runs(r),
                                                        r.update(registry_sha256=canonical.digest(body(r)))),
    "runs sorted by run_id": lambda r: r["runs"].sort(key=lambda run: run["run_id"]),
    "arm dict changed": lambda r: r["arms"]["full"].update(enforcement=False),
    "arm added": lambda r: r["arms"].update(control={"instructions": False, "enforcement": False}),
    "run arm relabeled": lambda r: r["runs"][0].update(arm="baseline"),
    "run task relabeled": lambda r: r["runs"][0].update(task_id="lf-a"),
    "run seed changed": lambda r: r["runs"][0].update(seed=29),
    "run_id edited": lambda r: r["runs"][0].update(run_id=_flip_last_hex(r["runs"][0]["run_id"])),
    "run field added": lambda r: r["runs"][0].update(note="synthetic"),
    "run dropped": lambda r: r["runs"].pop(),
    "run duplicated": lambda r: r["runs"].append(dict(r["runs"][0])),
    "source changed after freeze": lambda r: r["spec"].update(code_commit="0" * 40),
    "task changed after freeze": lambda r: r["spec"]["tasks"][0].update(fidelity_tolerance=0.5),
    "registry_sha256 edited": lambda r: r.update(registry_sha256=_flip_last_hex(r["registry_sha256"])),
}


@pytest.mark.parametrize("mutation", REGISTRY_MUTATIONS)
def test_mutated_registry_is_rejected(mutation):
    registry, outcomes = cohort()
    REGISTRY_MUTATIONS[mutation](registry)
    rejects(REGISTRY_ALTERED, experiment.validate_registry, registry)
    rejects(REGISTRY_ALTERED, experiment.score, registry, outcomes)


def test_consistently_refrozen_registry_is_detected_only_against_the_archived_digest():
    registry, outcomes = cohort()
    spec = golden_spec()
    spec["tasks"][0]["fidelity_tolerance"] = 0.5
    refrozen = experiment.freeze(spec)
    experiment.validate_registry(refrozen)  # self-consistent: v1 alone cannot tell it was re-frozen
    assert refrozen["registry_sha256"] != GOLDEN_REGISTRY_SHA256
    rejects("outcomes registry mismatch", experiment.score, refrozen, outcomes)


# ---- complete accounting (CONTRACT_12, CONTRACT_13, CONTRACT_14) -------------------------------

@pytest.mark.parametrize("status", ["crash", "timeout", "not_started"])
def test_omitting_a_failed_assignment_is_a_hard_error(status):
    registry, outcomes = cohort()
    target = row(registry, outcomes, "lf-a", "baseline")
    if status == "not_started":
        target.update(not_started_fields())
    else:
        target.update(status=status, unsupported_claim=None, fidelity_error=None,
                      notes=f"Synthetic fixture: {status} before delivery")
    assert experiment.score(registry, outcomes)["arms"]["baseline"]["status_counts"][status] == 1
    outcomes["outcomes"].remove(target)
    rejects("complete accounting required: missing=1, unplanned=0", experiment.score, registry, outcomes)


def test_unplanned_favorable_retry_is_a_hard_error():
    registry, outcomes = cohort()
    retry = dict(row(registry, outcomes, "lf-a", "baseline"), run_id=canonical.digest({"synthetic_retry": 1}),
                 notes="Synthetic fixture: unplanned favorable retry")
    outcomes["outcomes"].append(retry)
    rejects("complete accounting required: missing=0, unplanned=1", experiment.score, registry, outcomes)
    outcomes["outcomes"].pop()
    outcomes["outcomes"][0]["run_id"] = retry["run_id"]  # substituted instead of appended
    rejects("complete accounting required: missing=1, unplanned=1", experiment.score, registry, outcomes)


@pytest.mark.parametrize("conflicting", [False, True], ids=["identical", "conflicting judgment"])
def test_duplicate_outcome_rows_are_a_hard_error(conflicting):
    registry, outcomes = cohort()
    twin = dict(row(registry, outcomes, "lf-c", "full"))
    if conflicting:
        twin.update(unsupported_claim=True, refusal_valid=False)
    outcomes["outcomes"].append(twin)
    rejects("duplicate outcome run_id", experiment.score, registry, outcomes)


@pytest.mark.parametrize("edit,message", [
    (lambda o: o.update(registry_sha256="0" * 64), "outcomes registry mismatch"),
    (lambda o: o.update(outcomes={}), "outcomes: expected list"),
])
def test_outcomes_document_must_match_its_registry(edit, message):
    registry, outcomes = cohort()
    edit(outcomes)
    rejects(message, experiment.score, registry, outcomes)


# ---- not_started and missing resources (CONTRACT_15) -------------------------------------------

def test_not_started_row_stays_in_every_denominator_with_known_zero_resources():
    registry, outcomes = cohort()
    target = row(registry, outcomes, "lf-a", "full")
    target.update(not_started_fields())
    arm = experiment.score(registry, outcomes)["arms"]["full"]
    assert arm["planned"] == 6 and arm["status_counts"]["not_started"] == 1
    assert arm["unadjudicated"] == 1 and arm["unsupported_claim_rate"] is None
    assert arm["unsupported_claim_rate_bounds"] == [0, 1 / 6]
    assert arm["verified_completions"] == 3 and arm["verified_completion_rate"] == 0.75
    assert arm["fidelity_by_task"]["lf-a"] == {"planned": 2, "scored": 1, "median_known": 0.001,
                                               "tolerance": 0.005}
    # A launch that never happened spent nothing: its explicit zero is a known value, not missingness.
    assert arm["cost_usd"] == {"known_sum": 1.25, "known_runs": 6, "missing_runs": 0, "mean_known": 1.25 / 6}


@pytest.mark.parametrize("field,value,message", [
    ("unsupported_claim", False, "not_started: no empirical findings"),
    ("refusal_valid", False, "not_started: no empirical findings"),
    ("fidelity_error", 0.0, "not_started: no empirical findings"),
    ("executor_id", "synthetic-executor", "not_started: no empirical findings"),
    ("scorer_id", "synthetic-independent-scorer", "not_started: no empirical findings"),
    ("evidence_sha256", "9" * 64, "not_started: no empirical findings"),
    ("cost_usd", None, "not_started: resource usage must be explicitly zero"),
    ("wall_seconds", None, "not_started: resource usage must be explicitly zero"),
    ("interventions", None, "not_started: resource usage must be explicitly zero"),
    ("cost_usd", 0.01, "not_started: resource usage must be explicitly zero"),
    ("wall_seconds", 3, "not_started: resource usage must be explicitly zero"),
    ("interventions", 1, "not_started: resource usage must be explicitly zero"),
    ("notes", "  ", "outcome notes: required, including missingness explanation"),
])
def test_not_started_has_null_judgments_and_zero_resources(field, value, message):
    registry, outcomes = cohort()
    target = row(registry, outcomes, "lf-a", "full")
    target.update(not_started_fields())
    target[field] = value
    rejects(message, experiment.score, registry, outcomes)


def test_started_run_with_null_cost_is_missing_never_zero():
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-a", "instructions").update(cost_usd=None,
                                                           notes="Synthetic fixture: provider bill unavailable")
    arm = experiment.score(registry, outcomes)["arms"]["instructions"]
    assert arm["cost_usd"] == {"known_sum": 1.25, "known_runs": 5, "missing_runs": 1, "mean_known": 0.25}
    assert arm["verified_completions"] == 4


def test_arm_without_any_known_bill_has_no_mean():
    registry, outcomes = cohort()
    for target in arm_rows(registry, outcomes, "baseline"):
        target.update(cost_usd=None, notes="Synthetic fixture: provider bill unavailable")
    arm = experiment.score(registry, outcomes)["arms"]["baseline"]
    # known_sum is the empty sum over known runs; missingness is carried by known_runs/missing_runs.
    assert arm["cost_usd"] == {"known_sum": 0, "known_runs": 0, "missing_runs": 6, "mean_known": None}


# ---- scorer independence -----------------------------------------------------------------------

@pytest.mark.parametrize("task_id,judgment", [
    ("lf-b", {}),  # completed, non-numeric oracle, judged by unsupported_claim only
    ("lf-a", {"unsupported_claim": None}),  # judged by fidelity_error only
    ("lf-c", {"unsupported_claim": None}),  # judged by refusal_valid only
], ids=["unsupported_claim", "fidelity_error", "refusal_valid"])
@pytest.mark.parametrize("scorer", ["executor", None])
def test_any_adjudicated_finding_requires_an_independent_scorer(task_id, judgment, scorer):
    registry, outcomes = cohort()
    target = row(registry, outcomes, task_id, "enforcement")
    target.update(judgment, scorer_id=target["executor_id"] if scorer == "executor" else None)
    rejects("independent scorer identity required", experiment.score, registry, outcomes)


@pytest.mark.parametrize("scorer", ["executor", None])
def test_unjudged_started_row_needs_no_independent_scorer(scorer):
    registry, outcomes = cohort()
    target = row(registry, outcomes, "lf-a", "enforcement")
    target.update(status="crash", unsupported_claim=None, fidelity_error=None,
                  scorer_id=target["executor_id"] if scorer == "executor" else None,
                  notes="Synthetic fixture: crash, not yet adjudicated")
    arm = experiment.score(registry, outcomes)["arms"]["enforcement"]
    assert arm["unadjudicated"] == 1 and arm["unsupported_claim_rate"] is None


@pytest.mark.parametrize("field,value,message", [
    ("executor_id", None, "started run requires executor_id"),
    ("executor_id", " ", "started run requires executor_id"),
    ("scorer_id", " ", "scorer_id: string or null"),
])
def test_started_run_identities_are_checked(field, value, message):
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-a", "enforcement")[field] = value
    rejects(message, experiment.score, registry, outcomes)


# ---- status semantics and pathological subjects ------------------------------------------------

@pytest.mark.parametrize("task_id,edit,message", [
    ("lf-c", {"fidelity_error": 0.0}, "fidelity_error only applies to completed outcomes"),
    ("lf-c", {"unsupported_claim": True}, "valid refusal cannot contain an unsupported claim"),
    ("lf-a", {"refusal_valid": False}, "refusal_valid only applies to refused outcomes"),
    ("lf-a", {"status": "incomplete"}, "outcome status: invalid"),
])
def test_status_specific_fields_are_enforced(task_id, edit, message):
    registry, outcomes = cohort()
    row(registry, outcomes, task_id, "full").update(edit)
    rejects(message, experiment.score, registry, outcomes)


@pytest.mark.parametrize("valid_on_completion_controls", [False, True])
def test_all_refusal_cohort_has_zero_verified_completion(valid_on_completion_controls):
    registry, outcomes = cohort()
    for target in outcomes["outcomes"]:
        refusal_control = target["refusal_valid"] is True
        target.update(status="refused", fidelity_error=None,
                      refusal_valid=True if refusal_control else valid_on_completion_controls)
    for arm in experiment.score(registry, outcomes)["arms"].values():
        assert arm["verified_completions"] == 0 and arm["verified_completion_rate"] == 0
        assert arm["refusals_on_completion_controls"] == arm["completion_controls"] == 4
        assert arm["verified_valid_refusal_rate"] == 1 and arm["unsupported_claim_rate"] == 0


def test_confident_fabricating_subject_fails_claim_support_and_completion():
    registry, outcomes = cohort()
    # Delivers a number everywhere, including refusal controls; lf-a keeps its within-tolerance
    # fidelity, so numeric accuracy alone must not rescue a run with an unsupported claim.
    for target in outcomes["outcomes"]:
        target.update(status="completed", unsupported_claim=True, refusal_valid=None)
    for arm in experiment.score(registry, outcomes)["arms"].values():
        assert arm["unsupported_claim_rate"] == 1 and arm["unsupported_claim_rate_bounds"] == [1, 1]
        assert arm["verified_completions"] == 0 and arm["verified_valid_refusals"] == 0


def test_silent_crash_is_not_a_valid_refusal():
    registry, outcomes = cohort()
    crashed = [o for o in arm_rows(registry, outcomes, "full") if o["refusal_valid"] is True]
    for target in crashed:
        target.update(status="crash", refusal_valid=None, unsupported_claim=None,
                      notes="Synthetic fixture: silent crash")
    arm = experiment.score(registry, outcomes)["arms"]["full"]
    assert arm["planned"] == 6 and arm["status_counts"]["crash"] == 2
    assert arm["verified_valid_refusals"] == 0 and arm["verified_valid_refusal_rate"] == 0
    crashed[0]["refusal_valid"] = True
    rejects("refusal_valid only applies to refused outcomes", experiment.score, registry, outcomes)


def test_unadjudicated_or_unfinished_rows_are_never_verified():
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-b", "baseline", 11).update(
        unsupported_claim=None, notes="Synthetic fixture: completed, claim support not yet adjudicated")
    row(registry, outcomes, "lf-b", "baseline", 29).update(
        status="timeout", unsupported_claim=False, fidelity_error=None,
        notes="Synthetic fixture: timed out; adjudicated free of unsupported claims")
    row(registry, outcomes, "lf-c", "baseline", 11).update(
        unsupported_claim=None, notes="Synthetic fixture: valid refusal, claim support not yet adjudicated")
    arm = experiment.score(registry, outcomes)["arms"]["baseline"]
    # Only lf-a (seeds 11, 29) remains a verified completion; only lf-c seed 29 a verified refusal.
    assert arm["verified_completions"] == 2 and arm["verified_completion_rate"] == 0.5
    assert arm["verified_valid_refusals"] == 1 and arm["verified_valid_refusal_rate"] == 0.5
    assert arm["unadjudicated"] == 2 and arm["unsupported_claim_rate"] is None
    assert arm["unsupported_claim_rate_bounds"] == [0, 2 / 6] and arm["status_counts"]["timeout"] == 1
    assert experiment.score(registry, outcomes)["arms"]["full"] == GOLDEN_ARM_SUMMARY  # other arms untouched


@pytest.mark.parametrize("status", ["timeout", "crash", "refused"])
def test_only_a_completed_status_is_a_verified_completion(status):
    registry, outcomes = cohort()
    # lf-b has no numeric oracle, so only status and claim support decide verification.
    row(registry, outcomes, "lf-b", "baseline").update(
        status=status, unsupported_claim=False, refusal_valid=False if status == "refused" else None,
        notes=f"Synthetic fixture: {status}; adjudicated free of unsupported claims")
    arm = experiment.score(registry, outcomes)["arms"]["baseline"]
    assert arm["verified_completions"] == 3 and arm["verified_completion_rate"] == 0.75
    assert arm["unadjudicated"] == 0 and arm["unsupported_claim_rate"] == 0


@pytest.mark.parametrize("refusal_valid", [False, None])
def test_only_an_adjudicated_valid_refusal_is_verified(refusal_valid):
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-c", "baseline").update(
        refusal_valid=refusal_valid, notes="Synthetic fixture: refusal not judged valid")
    arm = experiment.score(registry, outcomes)["arms"]["baseline"]
    assert arm["verified_valid_refusals"] == 1 and arm["verified_valid_refusal_rate"] == 0.5


def test_fidelity_median_is_the_per_task_median_of_scored_values():
    registry, outcomes = cohort(unsorted_spec())  # three seeds per task and arm
    for seed, error in ((29, 0.004), (11, 0.001), (5, 0.002)):
        row(registry, outcomes, "lf-a", "baseline", seed)["fidelity_error"] = error
    lf_a = experiment.score(registry, outcomes)["arms"]["baseline"]["fidelity_by_task"]["lf-a"]
    # median 0.002; a mean would give 0.00233..., a minimum 0.001, a maximum 0.004.
    assert lf_a == {"planned": 3, "scored": 3, "median_known": 0.002, "tolerance": 0.005}
    row(registry, outcomes, "lf-a", "baseline", 11)["fidelity_error"] = None
    arm = experiment.score(registry, outcomes)["arms"]["baseline"]
    # Two known values: the midpoint 0.003, not the low (0.002) or high (0.004) middle value.
    assert arm["fidelity_by_task"]["lf-a"] == {"planned": 3, "scored": 2, "median_known": 0.003,
                                               "tolerance": 0.005}
    assert arm["fidelity_scored"] == 2 and arm["verified_completions"] == 5  # 2 lf-a + 3 lf-b


def test_completed_refusal_control_never_enters_fidelity_accounting():
    registry, outcomes = cohort()
    before = experiment.score(registry, outcomes)["arms"]["full"]
    # v1 accepts a refusal control delivered as a completion with an (independently scored) error.
    row(registry, outcomes, "lf-c", "full").update(
        status="completed", refusal_valid=None, fidelity_error=0.0,
        notes="Synthetic fixture: answered a refusal control")
    after = experiment.score(registry, outcomes)["arms"]["full"]
    assert after["fidelity_scored"] == before["fidelity_scored"] == 2
    assert after["fidelity_by_task"] == before["fidelity_by_task"] and "lf-c" not in after["fidelity_by_task"]
    assert after["verified_valid_refusals"] == before["verified_valid_refusals"] - 1 == 1
    assert after["verified_completions"] == 4 and after["completion_controls"] == 4
    assert after["status_counts"]["completed"] == 5 and after["status_counts"]["refused"] == 1


def test_each_completion_is_judged_against_its_own_task_tolerance():
    spec = golden_spec()
    spec["tasks"][1]["fidelity_tolerance"] = 0.0005  # lf-b now numeric and tighter than lf-a (0.005)
    registry, outcomes = cohort(spec)  # every numeric row has fidelity_error 0.001, between the two
    for arm in experiment.score(registry, outcomes)["arms"].values():
        assert arm["verified_completions"] == 2 and arm["verified_completion_rate"] == 0.5  # lf-a only
        assert arm["fidelity_scored"] == 4
        assert arm["fidelity_by_task"] == {
            "lf-a": {"planned": 2, "scored": 2, "median_known": 0.001, "tolerance": 0.005},
            "lf-b": {"planned": 2, "scored": 2, "median_known": 0.001, "tolerance": 0.0005}}


@pytest.mark.parametrize("error,verified", [(0.0, True), (0.005, True), (0.0050001, False), (None, False)])
def test_numeric_completion_needs_fidelity_within_frozen_tolerance(error, verified):
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-a", "baseline")["fidelity_error"] = error
    assert experiment.score(registry, outcomes)["arms"]["baseline"]["verified_completions"] == 3 + verified


# ---- documented loopholes (current v1 behavior, pinned on purpose) -----------------------------

@pytest.mark.parametrize("mutation", ["run seed written as float", "arm booleans written as integers"])
def test_loophole_value_equal_registry_with_different_bytes_is_accepted(tmp_path, mutation):
    # documented v1 behavior; closed outside v1 by campaign_manifest byte verification (decisions.md E-05)
    registry, outcomes = cohort()
    altered = copy.deepcopy(registry)
    if mutation == "run seed written as float":
        altered["runs"][0]["seed"] = float(altered["runs"][0]["seed"])  # 11 -> 11.0
    else:
        altered["arms"] = {arm: {k: int(v) for k, v in flags.items()} for arm, flags in ARMS.items()}
    experiment.validate_registry(altered)
    assert experiment.score(altered, outcomes) == experiment.score(registry, outcomes)
    assert canonical.canonical_bytes(altered) != canonical.canonical_bytes(registry)
    assert canonical.digest(body(altered)) != altered["registry_sha256"]  # bytes no longer match its identity
    scored = cli("score", write(tmp_path / "registry.json", json.dumps(altered)),
                 write(tmp_path / "outcomes.json", json.dumps(outcomes)))
    assert scored.returncode == 0


@pytest.mark.parametrize("field", ["seeds", "schedule_seed"])
def test_loophole_huge_integer_escapes_validation_as_overflow(tmp_path, field):
    # documented v1 behavior; closed outside v1 by campaign_manifest byte verification (decisions.md E-05)
    # Open integration requirement: the escape is an OverflowError (not ValueError), and
    # campaign_manifest.verify as specified in slice-design section 4.1 calls freeze(), so the
    # closure holds only once verify bounds integer size or converts OverflowError to ContractError.
    huge = 10 ** 400  # 401 digits: a finite JSON integer that math.isfinite cannot convert to float
    spec = golden_spec()
    spec[field] = [huge, 29] if field == "seeds" else huge
    with pytest.raises(OverflowError) as excinfo:
        experiment.freeze(spec)
    assert not isinstance(excinfo.value, ValueError)
    result = cli("freeze", write(tmp_path / "spec.json", json.dumps(spec)))
    assert result.returncode == 1  # uncaught traceback, not the CLI's exit 2 validation path
    assert result.stdout == b"" and b"OverflowError" in result.stderr


def test_loophole_huge_integer_in_outcome_row_escapes_as_overflow():
    # documented v1 behavior; NOT covered by campaign_manifest byte verification (it verifies the
    # spec and registry, not outcome rows): outcome writers must emit bounded integers.
    registry, outcomes = cohort()
    row(registry, outcomes, "lf-a", "baseline")["interventions"] = 10 ** 400
    with pytest.raises(OverflowError):
        experiment.score(registry, outcomes)


def test_loophole_score_ignores_the_frozen_budget():
    # documented v1 behavior; closed outside v1 by campaign_manifest byte verification (decisions.md E-05)
    # Budgets live in sidecars: the manifest pins spec.budget to the per-run budget and the
    # coordinator enforces it (slice-design sections 4.1 and 10); v1 score() never reads it.
    registry, outcomes = cohort()
    budget = registry["spec"]["budget"]
    row(registry, outcomes, "lf-a", "full").update(cost_usd=250 * budget["usd_per_run"],
                                                   wall_seconds=250 * budget["seconds_per_run"])
    arm = experiment.score(registry, outcomes)["arms"]["full"]
    assert arm["verified_completions"] == 4 and arm["verified_completion_rate"] == 1
    assert arm["cost_usd"]["known_sum"] == 250 * 2.5 + 5 * 0.25
