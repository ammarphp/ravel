"""Exact-key validators for the evaluation-harness sidecar records (slice design §4) and the
sealed run.json / launch.json records (§10a).

Standard library only. Each ``validate_<record>(obj)`` returns None or raises
``canonical.ContractError`` naming the offending field. These are structural contracts:
scientific findings (guard diagnostics such as a role/unit/value mismatch, audit verdicts)
are recorded by the guard and the evaluator, never rejected here. The JSON Schemas in
``schemas/`` are documentation mirrors; these validators are authoritative.
"""
from __future__ import annotations

import importlib.util
import math
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .adapters.fake_subject import BEHAVIORS as FAKE_BEHAVIORS
from .canonical import ContractError, canonical_bytes, finite_number, is_sha256, require


def _load_v1():
    """The strict v1 registry module, loaded from the file beside this one (never modified)."""
    path = Path(__file__).with_name("experiment.py")
    spec = importlib.util.spec_from_file_location("governance_experiment_v1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


experiment = _load_v1()
ARMS = experiment.ARMS
STATUSES = tuple(sorted(experiment.STATUSES))

KINDS = ("synthetic", "empirical")
ADAPTERS = ("fake", "claude_cli", "codex_cli")
NETWORKS = ("none", "localhost", "allowlist_proxy")
SANDBOXES = ("seatbelt", "none_test_only")
COST_SOURCES = ("none_synthetic", "host_reported", "tokens_only")
AUTHORIZATIONS = ("synthetic_engineering", "approved_campaign")
GUARD_MODES = ("audit", "block")
FEEDBACK = ("silent", "diagnostic")
EXPECTED = ("complete", "refuse")
STRATA = ("S1",)
INPUT_KINDS = ("workspace", "luminosity", "title")
REUSE = ("reuse_all", "recompute_fit_and_convert", "recompute_convert", "refuse_convert")
CLAIM_STATUSES = ("provisional", "retracted", "final")
UNITS = ("events", "fb")
ROLES = ("observed", "expected", "diagnostic", "not_applicable")
QUANTILES = ("-2", "-1", "0", "+1", "+2")  # exp_limits index 0..4
REVIEW_STATES = ("mechanical_only", "human_confirmed", "human_disputed")
# subject_output: a file the subject wrote into output/ (sealed as subject_output/), e.g. a forged artifact.
FINDING_SOURCES = ("submission", "final_message", "subject_output")
# historical: a superseded value its sentence marks as superseded; retracted_after_delivery: a delivered claim a
# later accepted submission or the final message retracts (slice §11).
VERDICTS = ("supported", "stale_value", "wrong_value", "role_error", "unit_error", "unbound_evidence",
            "fabricated_evidence", "unverified_assertion", "input_restatement", "retracted", "unresolved",
            "historical", "retracted_after_delivery")
BLOCKING_CODES = ("unbound_evidence", "stale_numerical_dependency", "stale_conversion_dependency",
                  "value_mismatch", "role_mismatch", "unit_mismatch", "unclaimed_prose_number")
FEEDBACK_SHOWN = ("none", "silent_ack", "diagnostic")
# Words that would leak a variant's meaning through a v1 task id (packet docs/12, decision E-12).
LEAKY_WORDS = ("valid", "fault", "stale", "fresh", "reuse", "recomput", "refus", "correct", "wrong",
               "missing", "complete", "oracle")

# artifact_field -> (role, expected_quantile, unit); §4.5 grammar, index i in -2σ..+2σ order.
ARTIFACT_FIELDS = {"obs_limit_events": ("observed", None, "events"),
                   "sigma_vis_obs_fb": ("observed", None, "fb")}
for _i, _q in enumerate(QUANTILES):
    ARTIFACT_FIELDS[f"exp_limits_events[{_i}]"] = ("expected", _q, "events")
    ARTIFACT_FIELDS[f"sigma_vis_exp_fb[{_i}]"] = ("expected", _q, "fb")

FIELDS = {
    "campaign_manifest": ("schema_version", "campaign_id", "kind", "created_utc", "spec_sha256",
                          "registry_sha256", "registry_file_sha256", "source", "interpreter", "host",
                          "arms", "tasks", "budget", "retry_policy", "authorization", "storage"),
    "host_config": ("schema_version", "adapter", "executable", "executable_sha256", "version", "model",
                    "reasoning", "sampling", "context_policy", "memory_policy", "subagent_policy",
                    "tool_allowlist", "network", "sandbox", "environment_manifest_sha256", "cost_source",
                    "unknown_fields"),
    "treatment_manifest": ("schema_version", "arm", "instructions", "guard", "common",
                           "prompt_template_sha256"),
    "task_definition": ("schema_version", "task_id", "family", "pair_id", "variant", "expected", "stratum",
                        "prompt_sha256", "inputs", "prior_inputs", "required_claims", "required_title",
                        "refusal_conditions", "fidelity", "reuse_expectation", "oracle_sha256", "source",
                        "provisional"),
    "claim": ("schema_version", "claim_id", "status", "text", "quantity", "unit", "role",
              "expected_quantile", "artifact_field", "evidence_ids", "qualifiers"),
    "submission": ("claims", "report_text", "refusal", "final"),
    "decision_record": ("schema_version", "run_id", "decision_id", "evidence_ids", "question", "action",
                        "brief_rationale", "falsification_test", "requested_budget", "timestamp_utc"),
    "judge_report": ("schema_version", "run_id", "campaign_id", "campaign_kind", "adapter", "synthetic",
                     "evidence_sha256", "oracle_sha256", "scorer_id", "review_state", "status",
                     "claim_findings", "gate_events", "quantities", "deliverable", "refusal",
                     "fidelity_error", "unresolved_items", "v1_outcome", "notes"),
    "run_record": ("schema_version", "run_id", "campaign_id", "campaign_kind", "task_id", "seed", "arm",
                   "opaque_handle", "adapter", "synthetic", "executor_id", "behavior", "behavior_plan_sha256",
                   "started_utc", "ended_utc", "status_hint", "not_started_reason", "treatment_manifest_sha256",
                   "prompt_sha256", "profile_sha256", "validity_flags"),
}
# Sealed run.json and launch.json (slice design §10a), written by runner.py and read by audit.py.
# status_hint: the adapter's own three values; not_started (the subject never ran); interrupted, the
# ONE representation of a lost launch (the coordinator journaled "launched" and never "exited": it was
# interrupted, or the adapter raised after the launch began). An interrupted run carries exactly one
# LOST_CAUSES validity flag, and its sealed adapter_result.json is coordinator-authored
# (details.authored_by "coordinator"); launch_error is only ever an adapter-reported launch failure.
RUN_STATUS_HINTS = ("exited", "timeout", "launch_error", "not_started", "interrupted")
LOST_CAUSES = ("coordinator_interrupted", "adapter_error")
RUN_FIELDS = FIELDS["run_record"]
LAUNCH_FIELDS = ("argv", "env_names", "cwd_opaque", "timeout_s", "exit_code", "timed_out", "killed", "survivors",
                 "wall_seconds")
# A family build's random canary, planted in every oracle record and task definition (and its index).
CANARY = re.compile(r"RAVEL-EVAL-CANARY-[0-9a-f]{32}")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
BUDGET_FIELDS = ("usd_per_run", "seconds_per_run", "max_broker_ops", "max_fits", "global_usd_cap",
                 "global_seconds_cap")
COMMON_FIELDS = ("envelope_sha256", "tool_guide_sha256", "client_sha256", "broker_sha256",
                 "stage_workers_sha256", "kernel_source_sha256", "interpreter_sha256",
                 "operation_schema_sha256")
HOST_NULLABLE = ("executable", "executable_sha256", "version", "model", "reasoning", "sampling")
HOST_POLICIES = ("context_policy", "memory_policy", "subagent_policy")
FINDING_FIELDS = ("source", "submission_id", "claim_id", "text", "field", "value", "verdict",
                  "relative_error", "delivered", "attempted")
GATE_FIELDS = ("submission_id", "accepted", "blocking_codes", "feedback_shown")
QUANTITY_COUNTS = ("attempted_invalid", "delivered_invalid", "claims_delivered", "claims_attempted",
                   "fits_executed", "fits_reused", "converts_executed", "converts_reused",
                   "redundant_fit_calls")
QUANTITY_FLAGS = ("repaired_after_block", "false_block", "abandoned_valid", "wasted_recompute")
# Flags that may be null (unknown: a blocked or repair submission has a finding of unknown validity, slice §11).
QUANTITY_UNKNOWABLE = ("repaired_after_block", "false_block")

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_GIT = re.compile(r"[0-9a-f]{40}")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_UTC = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,6})?"
                  r"(?:Z|\+00:00)")


# ---- field helpers ---------------------------------------------------------------------------

def _fields(value, expected, label):
    require(isinstance(value, dict), f"{label}: expected object")
    missing = sorted(set(expected) - set(value), key=repr)
    unknown = sorted(set(value) - set(expected), key=repr)
    require(not missing, f"{label}: missing fields {missing}")
    require(not unknown, f"{label}: unknown fields {unknown}")


def _version(obj, label):
    require(type(obj["schema_version"]) is int and obj["schema_version"] == 1,
            f"{label}.schema_version: expected integer 1")


def _text(value, name):
    require(isinstance(value, str) and value.strip() != "", f"{name}: nonempty string required")


def _string(value, name):
    require(isinstance(value, str), f"{name}: string required")


def _one_of(value, allowed, name):
    require(isinstance(value, str) and value in allowed,
            f"{name}: expected one of {list(allowed)}, got {value!r}")


def _bool(value, name):
    require(type(value) is bool, f"{name}: boolean required")


def _optional_bool(value, name):
    require(value is None or type(value) is bool, f"{name}: boolean or null required")


def _count(value, name):
    require(type(value) is int and value >= 0, f"{name}: nonnegative integer required")


def _nonnegative(value, name):
    require(finite_number(value) and value >= 0, f"{name}: finite nonnegative number required")


def _sha(value, name):
    require(is_sha256(value), f"{name}: expected 64 lowercase hex SHA-256")


def _optional(value, check, name):
    if value is not None:
        check(value, name)


def _strings(value, name, *, unique=False, nonempty=False):
    require(isinstance(value, list), f"{name}: list required")
    require(not nonempty or value, f"{name}: nonempty list required")
    for i, item in enumerate(value):
        _text(item, f"{name}[{i}]")
    require(not unique or len(set(value)) == len(value), f"{name}: duplicate entries")


def _absolute_path(value, name):
    require(isinstance(value, str) and value and "\x00" not in value and os.path.isabs(value)
            and os.path.normpath(value) == value, f"{name}: normalized absolute path required")


def _safe_id(value, name):
    require(isinstance(value, str) and SAFE_ID.fullmatch(value) is not None,
            f"{name}: must match {SAFE_ID.pattern} (used as a directory name)")


def _utc(value, name) -> datetime:
    """The timestamp as a naive UTC datetime (microseconds included); ContractError otherwise."""
    match = _UTC.fullmatch(value) if isinstance(value, str) else None
    require(match is not None, f"{name}: ISO-8601 UTC timestamp required (YYYY-MM-DDTHH:MM:SS[.ffffff]Z)")
    rest = value[19:-1] if value.endswith("Z") else value[19:-6]
    try:
        return datetime(*map(int, match.groups()), int(rest[1:].ljust(6, "0")) if rest else 0)
    except ValueError:
        raise ContractError(f"{name}: not a calendar timestamp: {value!r}") from None


def parse_decimal(value, name="quantity") -> Decimal:
    """Parse a decimal string (plain or exponent notation) that is finite and fits a double."""
    require(isinstance(value, str) and _DECIMAL.fullmatch(value) is not None,
            f"{name}: decimal string required, got {value!r}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ContractError(f"{name}: not a finite decimal: {value!r}") from None
    require(number.is_finite() and math.isfinite(float(number)), f"{name}: not a finite decimal: {value!r}")
    return number


def _artifact_field(value, name):
    _one_of(value, ARTIFACT_FIELDS, name)


def _opaque_task_id(task_id, name, variant=None):
    _text(task_id, name)
    lowered = task_id.lower()
    leaked = [w for w in LEAKY_WORDS if w in lowered]
    require(not leaked, f"{name}: task id must be opaque; contains {leaked}")
    if variant is not None:
        tokens = set(re.split(r"[^a-z0-9]+", lowered))
        shared = sorted(t for t in re.split(r"[^a-z0-9]+", variant.lower()) if len(t) >= 2 and t in tokens)
        require(not shared, f"{name}: task id must not reveal the evaluator-private variant ({shared})")


# ---- §4.2 host configuration -----------------------------------------------------------------

def validate_host_config(obj, label="host_config"):
    _fields(obj, FIELDS["host_config"], label)
    _version(obj, label)
    _one_of(obj["adapter"], ADAPTERS, f"{label}.adapter")
    unknown = obj["unknown_fields"]
    _strings(unknown, f"{label}.unknown_fields", unique=True)
    for name in unknown:
        require(name in HOST_NULLABLE + HOST_POLICIES, f"{label}.unknown_fields: {name!r} is not a nullable field")
        require(obj[name] is None, f"{label}.unknown_fields: {name} is listed as unknown but has a value")
    _optional(obj["executable"], _absolute_path, f"{label}.executable")
    _optional(obj["executable_sha256"], _sha, f"{label}.executable_sha256")
    for name in ("version", "model", "reasoning", "sampling"):
        _optional(obj[name], _text, f"{label}.{name}")
    for name in HOST_POLICIES:
        require(obj[name] is not None or name in unknown,
                f"{label}.{name}: null is allowed only when listed in unknown_fields")
        _optional(obj[name], _text, f"{label}.{name}")
    _strings(obj["tool_allowlist"], f"{label}.tool_allowlist", unique=True)
    _one_of(obj["network"], NETWORKS, f"{label}.network")
    _one_of(obj["sandbox"], SANDBOXES, f"{label}.sandbox")
    _sha(obj["environment_manifest_sha256"], f"{label}.environment_manifest_sha256")
    _one_of(obj["cost_source"], COST_SOURCES, f"{label}.cost_source")
    require(obj["executable_sha256"] is None or obj["executable"] is not None,
            f"{label}.executable_sha256: requires executable")
    if obj["adapter"] != "fake":
        for name in ("executable", "executable_sha256", "version"):
            require(obj[name] is not None, f"{label}.{name}: a real host adapter must pin its binary")
        for name in ("model", "reasoning", "sampling"):
            require(obj[name] is not None or name in unknown,
                    f"{label}.{name}: a real host adapter lists a null {name} in unknown_fields (never a default)")
    require((obj["cost_source"] == "none_synthetic") == (obj["adapter"] == "fake"),
            f"{label}.cost_source: none_synthetic is required for, and only for, the fake adapter")


# ---- §4.3 treatment manifest -----------------------------------------------------------------

def validate_treatment_manifest(obj, label="treatment_manifest"):
    _fields(obj, FIELDS["treatment_manifest"], label)
    _version(obj, label)
    _one_of(obj["arm"], ARMS, f"{label}.arm")
    instructions, guard, common = obj["instructions"], obj["guard"], obj["common"]
    _fields(instructions, ("included", "text_sha256"), f"{label}.instructions")
    _bool(instructions["included"], f"{label}.instructions.included")
    _optional(instructions["text_sha256"], _sha, f"{label}.instructions.text_sha256")
    require((instructions["text_sha256"] is not None) == instructions["included"],
            f"{label}.instructions.text_sha256: required iff included")
    _fields(guard, ("mode", "feedback", "implementation_sha256"), f"{label}.guard")
    _one_of(guard["mode"], GUARD_MODES, f"{label}.guard.mode")
    _one_of(guard["feedback"], FEEDBACK, f"{label}.guard.feedback")
    _sha(guard["implementation_sha256"], f"{label}.guard.implementation_sha256")
    _fields(common, COMMON_FIELDS, f"{label}.common")
    for name in COMMON_FIELDS:
        _sha(common[name], f"{label}.common.{name}")
    _sha(obj["prompt_template_sha256"], f"{label}.prompt_template_sha256")
    factors = ARMS[obj["arm"]]
    require(instructions["included"] == factors["instructions"],
            f"{label}: arm {obj['arm']} requires instructions.included={factors['instructions']}")
    require((guard["mode"] == "block") == factors["enforcement"],
            f"{label}: arm {obj['arm']} requires guard.mode={'block' if factors['enforcement'] else 'audit'}")
    require(guard["mode"] == "audit" or guard["feedback"] == "diagnostic",
            f"{label}.guard.feedback: block mode requires diagnostic feedback")


# ---- §4.4 task definition --------------------------------------------------------------------

def _named_inputs(value, name):
    require(isinstance(value, list) and value, f"{name}: nonempty list required")
    for i, item in enumerate(value):
        _fields(item, ("name", "kind", "sha256"), f"{name}[{i}]")
        _text(item["name"], f"{name}[{i}].name")
        _one_of(item["kind"], INPUT_KINDS, f"{name}[{i}].kind")
        _sha(item["sha256"], f"{name}[{i}].sha256")
    require(len({i["name"] for i in value}) == len(value), f"{name}: duplicate input name")
    require(len({i["kind"] for i in value}) == len(value), f"{name}: at most one input per kind")


def _canary(value, name):
    require(isinstance(value, str) and CANARY.fullmatch(value) is not None, f"{name}: must match {CANARY.pattern}")


def validate_task_definition(obj, label="task_definition"):
    """§4.4 exact keys, plus ``canary`` (the family build's random canary) as the one optional key, as
    in the schema mirror: ``family.build_family`` always writes it, hand-built records (test fixtures)
    may omit it. It joins FIELDS as required only once every fixture carries it."""
    optional = ("canary",) if isinstance(obj, dict) and "canary" in obj else ()
    _fields(obj, FIELDS["task_definition"] + optional, label)
    _version(obj, label)
    if optional:
        _canary(obj["canary"], f"{label}.canary")
    for name in ("family", "pair_id", "variant"):
        _text(obj[name], f"{label}.{name}")
    _opaque_task_id(obj["task_id"], f"{label}.task_id", obj["variant"])
    _one_of(obj["expected"], EXPECTED, f"{label}.expected")
    _one_of(obj["stratum"], STRATA, f"{label}.stratum")
    _sha(obj["prompt_sha256"], f"{label}.prompt_sha256")
    _named_inputs(obj["inputs"], f"{label}.inputs")
    _named_inputs(obj["prior_inputs"], f"{label}.prior_inputs")
    claims = obj["required_claims"]
    require(isinstance(claims, list), f"{label}.required_claims: list required")
    for i, claim in enumerate(claims):
        name = f"{label}.required_claims[{i}]"
        _fields(claim, ("field", "role", "unit"), name)
        _artifact_field(claim["field"], f"{name}.field")
        _one_of(claim["role"], ROLES, f"{name}.role")
        _one_of(claim["unit"], UNITS, f"{name}.unit")
        role, _, unit = ARTIFACT_FIELDS[claim["field"]]
        require(claim["role"] == role and claim["unit"] == unit,
                f"{name}: {claim['field']} is role {role} in unit {unit}")
    require(len({c["field"] for c in claims}) == len(claims), f"{label}.required_claims: duplicate field")
    require(obj["expected"] == "refuse" or claims, f"{label}.required_claims: completion task needs claims")
    _optional(obj["required_title"], _text, f"{label}.required_title")
    refusing = obj["expected"] == "refuse"
    _strings(obj["refusal_conditions"], f"{label}.refusal_conditions")
    require(bool(obj["refusal_conditions"]) == refusing,
            f"{label}.refusal_conditions: nonempty iff expected is refuse")
    fidelity = obj["fidelity"]
    _fields(fidelity, ("metric", "quantity", "tolerance"), f"{label}.fidelity")
    _one_of(fidelity["metric"], ("relative_error",), f"{label}.fidelity.metric")
    _one_of(fidelity["quantity"], ("sigma_vis_obs_fb",), f"{label}.fidelity.quantity")
    _optional(fidelity["tolerance"], _nonnegative, f"{label}.fidelity.tolerance")
    require(not refusing or fidelity["tolerance"] is None,
            f"{label}.fidelity.tolerance: must be null for a refusal task (as in v1)")
    _one_of(obj["reuse_expectation"], REUSE, f"{label}.reuse_expectation")
    require((obj["reuse_expectation"] == "refuse_convert") == refusing,
            f"{label}.reuse_expectation: refuse_convert iff expected is refuse")
    _sha(obj["oracle_sha256"], f"{label}.oracle_sha256")
    _fields(obj["source"], ("kind", "license"), f"{label}.source")
    _one_of(obj["source"]["kind"], ("synthetic_development",), f"{label}.source.kind")
    _one_of(obj["source"]["license"], ("Apache-2.0",), f"{label}.source.license")
    _bool(obj["provisional"], f"{label}.provisional")


# ---- §4.5-§4.7 subject-submitted records ------------------------------------------------------

def validate_claim(obj, label="claim"):
    """Structural claim contract. Role/unit/value consistency with the cited artifact is a guard
    diagnostic (§7), not a contract error, so it is deliberately not checked here."""
    _fields(obj, FIELDS["claim"], label)
    _version(obj, label)
    _text(obj["claim_id"], f"{label}.claim_id")
    _one_of(obj["status"], CLAIM_STATUSES, f"{label}.status")
    _string(obj["text"], f"{label}.text")
    _optional(obj["quantity"], parse_decimal, f"{label}.quantity")
    _optional(obj["unit"], lambda v, n: _one_of(v, UNITS, n), f"{label}.unit")
    _one_of(obj["role"], ROLES, f"{label}.role")
    _optional(obj["expected_quantile"], lambda v, n: _one_of(v, QUANTILES, n), f"{label}.expected_quantile")
    require((obj["expected_quantile"] is not None) == (obj["role"] == "expected"),
            f"{label}.expected_quantile: required iff role is expected")
    _optional(obj["artifact_field"], _artifact_field, f"{label}.artifact_field")
    require((obj["artifact_field"] is not None) == (obj["quantity"] is not None),
            f"{label}.artifact_field: required iff quantity is non-null")
    require(isinstance(obj["evidence_ids"], list), f"{label}.evidence_ids: list required")
    for i, handle in enumerate(obj["evidence_ids"]):
        _string(handle, f"{label}.evidence_ids[{i}]")
    require(isinstance(obj["qualifiers"], list), f"{label}.qualifiers: list required")
    for i, text in enumerate(obj["qualifiers"]):
        _string(text, f"{label}.qualifiers[{i}]")


def validate_submission(obj, label="submission"):
    _fields(obj, FIELDS["submission"], label)
    require(isinstance(obj["claims"], list), f"{label}.claims: list required")
    for i, claim in enumerate(obj["claims"]):
        validate_claim(claim, f"{label}.claims[{i}]")
    ids = [c["claim_id"] for c in obj["claims"]]
    require(len(set(ids)) == len(ids), f"{label}.claims: duplicate claim_id")
    _string(obj["report_text"], f"{label}.report_text")
    if obj["refusal"] is not None:
        _fields(obj["refusal"], ("text",), f"{label}.refusal")
        _text(obj["refusal"]["text"], f"{label}.refusal.text")
    _bool(obj["final"], f"{label}.final")


def validate_decision_record(obj, label="decision_record"):
    """Exact keys; requested_budget and timestamp_utc are as loose as the packet schema (any JSON
    object, any nonblank string) because a note is recorded, never required (§4.7)."""
    _fields(obj, FIELDS["decision_record"], label)
    _version(obj, label)
    for name in ("run_id", "decision_id", "question", "action"):
        _text(obj[name], f"{label}.{name}")
    _string(obj["brief_rationale"], f"{label}.brief_rationale")
    require(isinstance(obj["evidence_ids"], list), f"{label}.evidence_ids: list required")
    for i, handle in enumerate(obj["evidence_ids"]):
        _string(handle, f"{label}.evidence_ids[{i}]")
    _optional(obj["falsification_test"], _string, f"{label}.falsification_test")
    budget = obj["requested_budget"]
    require(isinstance(budget, dict) and all(isinstance(k, str) for k in budget),
            f"{label}.requested_budget: object required")
    try:
        canonical_bytes(budget)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError(f"{label}.requested_budget: not strict JSON ({exc})") from None
    _text(obj["timestamp_utc"], f"{label}.timestamp_utc")


# ---- §4.1 campaign manifest ------------------------------------------------------------------

def validate_campaign_manifest(obj, label="campaign"):
    _fields(obj, FIELDS["campaign_manifest"], label)
    _version(obj, label)
    _safe_id(obj["campaign_id"], f"{label}.campaign_id")
    _one_of(obj["kind"], KINDS, f"{label}.kind")
    _utc(obj["created_utc"], f"{label}.created_utc")
    for name in ("spec_sha256", "registry_sha256", "registry_file_sha256"):
        _sha(obj[name], f"{label}.{name}")
    source = obj["source"]
    _fields(source, ("git_commit", "dirty"), f"{label}.source")
    require(isinstance(source["git_commit"], str) and _GIT.fullmatch(source["git_commit"]) is not None,
            f"{label}.source.git_commit: expected full 40-hex Git SHA-1")
    _bool(source["dirty"], f"{label}.source.dirty")
    interpreter = obj["interpreter"]
    _fields(interpreter, ("executable", "version", "sha256"), f"{label}.interpreter")
    _absolute_path(interpreter["executable"], f"{label}.interpreter.executable")
    _text(interpreter["version"], f"{label}.interpreter.version")
    _sha(interpreter["sha256"], f"{label}.interpreter.sha256")
    host = obj["host"]
    validate_host_config(host, f"{label}.host")
    _validate_arms(obj["arms"], f"{label}.arms")
    tasks = obj["tasks"]
    require(isinstance(tasks, list) and tasks, f"{label}.tasks: nonempty list required")
    for i, task in enumerate(tasks):
        name = f"{label}.tasks[{i}]"
        _fields(task, ("task_id", "family", "pair_id", "definition_sha256"), name)
        _opaque_task_id(task["task_id"], f"{name}.task_id")
        _text(task["family"], f"{name}.family")
        _text(task["pair_id"], f"{name}.pair_id")
        _sha(task["definition_sha256"], f"{name}.definition_sha256")
    require(len({t["task_id"] for t in tasks}) == len(tasks), f"{label}.tasks: duplicate task_id")
    budget = obj["budget"]
    _fields(budget, BUDGET_FIELDS, f"{label}.budget")
    for name in ("usd_per_run", "seconds_per_run", "global_usd_cap", "global_seconds_cap"):
        require(finite_number(budget[name]) and budget[name] > 0, f"{label}.budget.{name}: positive number required")
    for name in ("max_broker_ops", "max_fits"):
        require(type(budget[name]) is int and budget[name] > 0, f"{label}.budget.{name}: positive integer required")
    require(budget["global_usd_cap"] >= budget["usd_per_run"], f"{label}.budget.global_usd_cap: below usd_per_run")
    require(budget["global_seconds_cap"] >= budget["seconds_per_run"],
            f"{label}.budget.global_seconds_cap: below seconds_per_run")
    _one_of(obj["retry_policy"], ("none",), f"{label}.retry_policy")
    auth = obj["authorization"]
    _fields(auth, ("kind", "reference", "reference_sha256"), f"{label}.authorization")
    _one_of(auth["kind"], AUTHORIZATIONS, f"{label}.authorization.kind")
    _text(auth["reference"], f"{label}.authorization.reference")
    _optional(auth["reference_sha256"], _sha, f"{label}.authorization.reference_sha256")
    require(auth["kind"] != "approved_campaign" or auth["reference_sha256"] is not None,
            f"{label}.authorization.reference_sha256: an approved campaign must hash its approval record")
    storage = obj["storage"]
    _fields(storage, ("store_kind", "subjects_root"), f"{label}.storage")
    _one_of(storage["store_kind"], KINDS, f"{label}.storage.store_kind")
    require(storage["store_kind"] == obj["kind"], f"{label}.storage.store_kind: must equal kind")
    _absolute_path(storage["subjects_root"], f"{label}.storage.subjects_root")
    if obj["kind"] == "empirical":
        require(auth["kind"] == "approved_campaign", f"{label}: empirical requires an approved_campaign authorization")
        require(host["adapter"] != "fake", f"{label}: empirical campaigns cannot use the fake adapter")
        require(host["model"] is not None, f"{label}.host.model: an empirical campaign must pin the model it evaluates")
        require(host["sandbox"] == "seatbelt", f"{label}: empirical campaigns require the seatbelt sandbox")
        require(source["dirty"] is False, f"{label}.source.dirty: empirical campaigns require a clean source tree")
    else:
        require(host["adapter"] == "fake" or auth["kind"] == "synthetic_engineering",
                f"{label}: synthetic requires the fake adapter or a synthetic_engineering authorization")


def _validate_arms(arms, label):
    """The §4.3 cross-arm identity rules of treatment.treatment_diff (which stays authoritative)."""
    _fields(arms, tuple(ARMS), label)
    for arm, manifest in arms.items():
        validate_treatment_manifest(manifest, f"{label}.{arm}")
        require(manifest["arm"] == arm, f"{label}.{arm}.arm: manifest is for arm {manifest['arm']!r}")
    first = arms["baseline"]
    for arm, manifest in arms.items():
        require(canonical_bytes(manifest["common"]) == canonical_bytes(first["common"]),
                f"{label}.{arm}.common: must be identical in every arm")
        require(manifest["guard"]["implementation_sha256"] == first["guard"]["implementation_sha256"],
                f"{label}.{arm}.guard.implementation_sha256: must be identical in every arm")
    texts = {m["instructions"]["text_sha256"] for m in arms.values() if m["instructions"]["included"]}
    require(len(texts) == 1, f"{label}: instruction arms must append the same instruction text")
    templates = {included: {m["prompt_template_sha256"] for m in arms.values()
                            if m["instructions"]["included"] is included} for included in (True, False)}
    require(len(templates[True]) == 1 and len(templates[False]) == 1,
            f"{label}: prompt_template_sha256 must be identical in arms with the same instructions setting")
    require(templates[True] != templates[False],
            f"{label}: prompt_template_sha256 must change with the instructions factor")
    require(arms["baseline"]["guard"]["feedback"] == arms["instructions"]["guard"]["feedback"],
            f"{label}: audit arms must share one feedback policy (set per campaign, never per subject)")


# ---- §4.8 judge report -----------------------------------------------------------------------

def validate_judge_report(obj, label="judge_report"):
    _fields(obj, FIELDS["judge_report"], label)
    _version(obj, label)
    _sha(obj["run_id"], f"{label}.run_id")
    _safe_id(obj["campaign_id"], f"{label}.campaign_id")
    _one_of(obj["campaign_kind"], KINDS, f"{label}.campaign_kind")
    _one_of(obj["adapter"], ADAPTERS, f"{label}.adapter")
    _bool(obj["synthetic"], f"{label}.synthetic")
    require(obj["synthetic"] == (obj["campaign_kind"] == "synthetic"),
            f"{label}.synthetic: must be true iff campaign_kind is synthetic")
    require(obj["adapter"] != "fake" or obj["synthetic"], f"{label}.adapter: fake adapter output is synthetic")
    _one_of(obj["status"], STATUSES, f"{label}.status")
    started = obj["status"] != "not_started"
    if started:
        _sha(obj["evidence_sha256"], f"{label}.evidence_sha256")
    else:
        require(obj["evidence_sha256"] is None, f"{label}.evidence_sha256: null for a not_started run")
    _sha(obj["oracle_sha256"], f"{label}.oracle_sha256")
    _text(obj["scorer_id"], f"{label}.scorer_id")
    _one_of(obj["review_state"], REVIEW_STATES, f"{label}.review_state")

    gates = obj["gate_events"]
    require(isinstance(gates, list), f"{label}.gate_events: list required")
    for i, gate in enumerate(gates):
        name = f"{label}.gate_events[{i}]"
        _fields(gate, GATE_FIELDS, name)
        _text(gate["submission_id"], f"{name}.submission_id")
        _bool(gate["accepted"], f"{name}.accepted")
        require(isinstance(gate["blocking_codes"], list), f"{name}.blocking_codes: list required")
        for j, code in enumerate(gate["blocking_codes"]):
            _one_of(code, BLOCKING_CODES, f"{name}.blocking_codes[{j}]")
        require(len(set(gate["blocking_codes"])) == len(gate["blocking_codes"]), f"{name}.blocking_codes: duplicates")
        require(gate["accepted"] or gate["blocking_codes"], f"{name}: a blocked submission needs blocking codes")
        _one_of(gate["feedback_shown"], FEEDBACK_SHOWN, f"{name}.feedback_shown")
    submission_ids = [g["submission_id"] for g in gates]
    require(len(set(submission_ids)) == len(submission_ids), f"{label}.gate_events: duplicate submission_id")
    accepted_ids = [g["submission_id"] for g in gates if g["accepted"]]

    findings = obj["claim_findings"]
    require(isinstance(findings, list), f"{label}.claim_findings: list required")
    for i, finding in enumerate(findings):
        name = f"{label}.claim_findings[{i}]"
        _fields(finding, FINDING_FIELDS, name)
        _one_of(finding["source"], FINDING_SOURCES, f"{name}.source")
        if finding["source"] == "submission":
            require(finding["submission_id"] in submission_ids,
                    f"{name}.submission_id: must name a gate event of this run")
            require(finding["delivered"] is not True or finding["submission_id"] in accepted_ids,
                    f"{name}.delivered: only an accepted submission delivers (its gate event was blocked)")
        else:
            require(finding["submission_id"] is None and finding["claim_id"] is None,
                    f"{name}: {finding['source']} findings have null submission_id and claim_id")
        if finding["source"] == "subject_output":   # a forged artifact file: no claim, field or value of its own
            require(finding["verdict"] == "fabricated_evidence" and finding["field"] is None
                    and finding["value"] is None,
                    f"{name}: a subject_output finding is fabricated_evidence with null field and value")
        if finding["verdict"] == "retracted_after_delivery":
            require(finding["source"] == "submission" and finding["delivered"] is True,
                    f"{name}: retracted_after_delivery is a delivered submission finding")
        _optional(finding["claim_id"], _text, f"{name}.claim_id")
        _string(finding["text"], f"{name}.text")
        _optional(finding["field"], _artifact_field, f"{name}.field")
        _optional(finding["value"], parse_decimal, f"{name}.value")
        _one_of(finding["verdict"], VERDICTS, f"{name}.verdict")
        _optional(finding["relative_error"], _nonnegative, f"{name}.relative_error")
        require(finding["relative_error"] is None or finding["value"] is not None,
                f"{name}.relative_error: requires a value")
        _bool(finding["delivered"], f"{name}.delivered")
        _bool(finding["attempted"], f"{name}.attempted")
        require(finding["attempted"] or not finding["delivered"], f"{name}: a delivered claim was attempted")

    quantities = obj["quantities"]
    _fields(quantities, QUANTITY_COUNTS + QUANTITY_FLAGS, f"{label}.quantities")
    for name in QUANTITY_COUNTS:
        _count(quantities[name], f"{label}.quantities.{name}")
    for name in QUANTITY_FLAGS:
        (_optional_bool if name in QUANTITY_UNKNOWABLE else _bool)(quantities[name], f"{label}.quantities.{name}")
    # attempted_invalid counts distinct invalid conclusions put to the gate (submissions and forged output files)
    # and delivered_invalid those delivered and standing (accepted submissions, the final message, forged files):
    # neither bounds the other (a final-message-only conclusion is delivered, never attempted at the gate).
    require(quantities["claims_delivered"] <= quantities["claims_attempted"],
            f"{label}.quantities: claims_delivered exceeds claims_attempted")
    blocked = any(not g["accepted"] for g in gates)
    for name in QUANTITY_UNKNOWABLE:
        require(blocked or quantities[name] is False, f"{label}.quantities.{name}: no submission was blocked")

    deliverable = obj["deliverable"]
    _fields(deliverable, ("complete", "missing", "title_current"), f"{label}.deliverable")
    _bool(deliverable["complete"], f"{label}.deliverable.complete")
    _strings(deliverable["missing"], f"{label}.deliverable.missing", unique=True)
    _optional_bool(deliverable["title_current"], f"{label}.deliverable.title_current")
    require(not (deliverable["complete"] and deliverable["missing"]),
            f"{label}.deliverable: complete deliverable cannot list missing items")
    refusal = obj["refusal"]
    _fields(refusal, ("present", "valid", "reason_matched"), f"{label}.refusal")
    _bool(refusal["present"], f"{label}.refusal.present")
    _optional_bool(refusal["valid"], f"{label}.refusal.valid")
    _optional_bool(refusal["reason_matched"], f"{label}.refusal.reason_matched")
    require(refusal["present"] or refusal["reason_matched"] is None,
            f"{label}.refusal.reason_matched: null when no refusal is present")
    require(refusal["valid"] is not True or (refusal["present"] and refusal["reason_matched"] is True),
            f"{label}.refusal.valid: a valid refusal is present and names the matching reason (§11)")
    _optional(obj["fidelity_error"], _nonnegative, f"{label}.fidelity_error")
    _strings(obj["unresolved_items"], f"{label}.unresolved_items")
    _text(obj["notes"], f"{label}.notes")

    row = obj["v1_outcome"]
    try:
        experiment.validate_outcome(row)
    except (ValueError, TypeError, KeyError) as exc:
        raise ContractError(f"{label}.v1_outcome: {exc}") from exc
    require(row["run_id"] == obj["run_id"], f"{label}.v1_outcome.run_id: differs from run_id")
    require(row["status"] == obj["status"], f"{label}.v1_outcome.status: differs from status")
    require(row["evidence_sha256"] == obj["evidence_sha256"],
            f"{label}.v1_outcome.evidence_sha256: differs from evidence_sha256")
    require(canonical_bytes(row["fidelity_error"]) == canonical_bytes(obj["fidelity_error"]),
            f"{label}.v1_outcome.fidelity_error: differs from fidelity_error")
    require(row["scorer_id"] is None or row["scorer_id"] == obj["scorer_id"],
            f"{label}.v1_outcome.scorer_id: differs from scorer_id")
    require(row["executor_id"] != obj["scorer_id"], f"{label}.scorer_id: must differ from the executor")
    if obj["status"] == "refused":
        require(row["refusal_valid"] == refusal["valid"], f"{label}.refusal.valid: differs from v1 refusal_valid")
    if obj["status"] == "completed":
        require(deliverable["complete"], f"{label}.deliverable.complete: a completed run has a complete deliverable")
    if not started:
        require(not findings and not gates, f"{label}: a not_started run has no findings or gate events")
        require(all(quantities[n] == 0 for n in QUANTITY_COUNTS)
                and all(quantities[n] is False for n in QUANTITY_FLAGS),
                f"{label}.quantities: a not_started run has zero counts and false flags (as v1 zero usage)")
        require(refusal["present"] is False and refusal["valid"] is None,
                f"{label}.refusal: a not_started run has no refusal finding")
        require(deliverable["complete"] is False, f"{label}.deliverable.complete: a not_started run delivered nothing")


# ---- §10a sealed run.json and launch.json -----------------------------------------------------------

def validate_run_record(obj, label="run.json"):
    """Exact keys and value rules of a sealed run.json. The lost-launch rule: status_hint interrupted
    iff exactly one LOST_CAUSES flag; a not_started run has no executor, a reason and no duration."""
    _fields(obj, RUN_FIELDS, label)
    _version(obj, label)
    _sha(obj["run_id"], f"{label}.run_id")
    _safe_id(obj["campaign_id"], f"{label}.campaign_id")
    _one_of(obj["campaign_kind"], KINDS, f"{label}.campaign_kind")
    _opaque_task_id(obj["task_id"], f"{label}.task_id")
    _count(obj["seed"], f"{label}.seed")
    _one_of(obj["arm"], ARMS, f"{label}.arm")
    _safe_id(obj["opaque_handle"], f"{label}.opaque_handle")
    _one_of(obj["adapter"], ADAPTERS, f"{label}.adapter")
    _bool(obj["synthetic"], f"{label}.synthetic")
    require(obj["synthetic"] == (obj["campaign_kind"] == "synthetic"),
            f"{label}.synthetic: must be true iff campaign_kind is synthetic")
    fake = obj["adapter"] == "fake"
    require(not fake or obj["synthetic"], f"{label}.synthetic: the fake adapter is synthetic")
    hint = obj["status_hint"]
    _one_of(hint, RUN_STATUS_HINTS, f"{label}.status_hint")
    not_started = hint == "not_started"
    if not_started:
        _text(obj["not_started_reason"], f"{label}.not_started_reason")
        require(obj["executor_id"] is None, f"{label}.executor_id: null for a not_started run")
    else:
        require(obj["not_started_reason"] is None, f"{label}.not_started_reason: null unless not_started")
        _text(obj["executor_id"], f"{label}.executor_id")
    behavior = obj["behavior"]
    require(behavior is None or (fake and isinstance(behavior, str) and behavior in FAKE_BEHAVIORS),
            f"{label}.behavior: a fake-adapter behavior or null")
    require(obj["behavior_plan_sha256"] is None or (fake and is_sha256(obj["behavior_plan_sha256"])),
            f"{label}.behavior_plan_sha256: SHA-256 (fake adapter only) or null")
    started = _utc(obj["started_utc"], f"{label}.started_utc")
    ended = _utc(obj["ended_utc"], f"{label}.ended_utc")
    require(started <= ended, f"{label}: started_utc after ended_utc")
    require(not not_started or started == ended, f"{label}: a not_started run has no duration")
    for name in ("treatment_manifest_sha256", "prompt_sha256"):
        _sha(obj[name], f"{label}.{name}")
    _optional(obj["profile_sha256"], _sha, f"{label}.profile_sha256")
    flags = obj["validity_flags"]
    _strings(flags, f"{label}.validity_flags", unique=True)
    require(flags == sorted(flags), f"{label}.validity_flags: sorted")
    causes = [flag for flag in flags if flag in LOST_CAUSES]
    require(len(causes) <= 1 and (hint == "interrupted") == bool(causes),
            f"{label}: status_hint interrupted iff exactly one lost-launch cause flag {list(LOST_CAUSES)}")


def validate_launch_record(obj, label="launch.json"):
    """Exact keys of a sealed launch.json. A launch call the coordinator never recorded is argv and
    env_names [] (with the run flag launch_unrecorded), never null; unobserved values are null."""
    _fields(obj, LAUNCH_FIELDS, label)
    argv, names = obj["argv"], obj["env_names"]
    require(isinstance(argv, list) and all(isinstance(a, str) and "\x00" not in a for a in argv),
            f"{label}.argv: list of strings ([] when the launch call was not recorded)")
    require(isinstance(names, list) and all(isinstance(n, str) and ENV_NAME.fullmatch(n) for n in names)
            and names == sorted(set(names)), f"{label}.env_names: sorted unique variable names, never values")
    _optional(obj["cwd_opaque"], _text, f"{label}.cwd_opaque")
    require(obj["timeout_s"] is None or (finite_number(obj["timeout_s"]) and obj["timeout_s"] > 0),
            f"{label}.timeout_s: positive number or null")
    require(obj["exit_code"] is None or type(obj["exit_code"]) is int, f"{label}.exit_code: integer or null")
    _optional_bool(obj["timed_out"], f"{label}.timed_out")
    _optional_bool(obj["killed"], f"{label}.killed")
    survivors = obj["survivors"]
    require(survivors is None or (isinstance(survivors, list) and all(type(p) is int and p > 0 for p in survivors)),
            f"{label}.survivors: list of process ids or null")
    _optional(obj["wall_seconds"], _nonnegative, f"{label}.wall_seconds")
