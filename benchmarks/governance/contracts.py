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
from .tasks import registry as bank


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
# Judge report schema_version 2 (the WP12 task-bank scoring profiles, design §3.6) adds scope_change: a limit of a
# parameter range widened beyond the approved one and disclosed as such (decision E-116; invalid, never supported).
VERDICTS_V2 = VERDICTS + ("scope_change",)
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

# ---- WP12 task bank: task definition and claim schema version 2 (taskbank design §1.2-§1.5, §3.2) ----------
# Version 1 records keep validating unchanged; a record's schema_version selects its rules. Input kinds, stages,
# operations and artifact fields come from the bank registry (tasks/registry.py).
TASK_SCHEMA_VERSIONS = (1, 2)
CLAIM_SCHEMA_VERSIONS = (1, 2)
PAIR_VARIANTS = ("valid", "fault")   # a v2 definition's private variant, relative to its primary pair
EXPOSURE_CLASSES = ("numerical_dependency", "calibration_supersession", "missing_authorization", "scope_overreach",
                    "unit_convention", "data_integrity_provenance", "role_label_provenance")
SPLITS = ("development",)
ORACLE_KINDS = ("counting", "lhe_census")
# pre_authorized_operations: broker operations inside the budget need no approval (PKT-D06 default);
# supplied_approval_record: the task's inputs carry the scope approval (an input of kind approval).
APPROVAL_MODES = ("pre_authorized_operations", "supplied_approval_record")
SOURCE_KINDS = ("synthetic_development", "derived_from_published", "ravel_generated_development")
SOURCE_FIELDS = ("kind", "license", "citation", "provenance", "modifications")
SYNTHETIC_LICENSE = "Apache-2.0"
RELATIONS = ("eq", "gt", "ge", "lt", "le")
METRICS = ("relative_error", "exact", "categorical")
REUSE_PLANS = ("reuse", "execute", "optional", "refuse", "not_required")
UNITS_V2 = ("events", "fb", "pb")
ENDPOINT_FIELDS = ("field", "role", "unit", "relation", "metric", "tolerance", "evidence_constraint")
EVIDENCE_CONSTRAINT_FIELDS = ("artifact", "predicate", "input_kind")
REFUSAL_CONDITION_FIELDS = ("id", "text", "matcher", "evidence_predicate")
CONTRAST_FIELDS = ("id", "valid", "fault", "exposure_class", "fault_inputs")
# Twin-symmetric visibility (design §1.1, decision D-V adopted provisionally, E-110): a subject-visible number equal
# to a current oracle value within tolerance is declared in the index (visible_oracle_values), and until the
# reviewer records D-V the task carries the waiver visibility_waiver_pending, which keeps it out of empirical
# campaigns (campaign_manifest).
VISIBLE_VALUE_FIELDS = ("task", "location", "field", "provenance")
VISIBLE_PROVENANCE = ("prior_artifact", "supplied_input")
VISIBILITY_WAIVER = "visibility_waiver_pending"
WAIVERS = (VISIBILITY_WAIVER,)
PRIOR_PREFIX = "prior:"   # a twin difference in a prior input (prior:<name>) or prior-recipe step (prior:<op>)
# The v1 reuse_expectation of the likelihood_freshness family as a per-stage reuse plan (contracts.reuse_plan).
V1_REUSE_PLANS = {
    "reuse_all": {"fit": "reuse", "convert": "reuse", "report": "execute"},
    "recompute_fit_and_convert": {"fit": "execute", "convert": "execute", "report": "execute"},
    "recompute_convert": {"fit": "reuse", "convert": "execute", "report": "execute"},
    "refuse_convert": {"fit": "optional", "convert": "refuse", "report": "not_required"},
}
_INPUT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
_REUSE_STAGE = re.compile(r"([a-z]+)(?::[a-z0-9_]+)?")

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
    # v2 (taskbank design §3.2): v1's keys less required_claims (now endpoints) and reuse_expectation (now
    # reuse_plan), plus the bank fields. fidelity keeps its v1 shape and is the design's primary_fidelity
    # pointer: fidelity.quantity names the fidelity endpoint (decision E-111).
    "task_definition_v2": ("schema_version", "task_id", "family", "pair_id", "variant", "expected", "stratum",
                           "split", "objective", "exposure_class", "twin_task_id", "bank_version", "prompt_sha256",
                           "inputs", "prior_inputs", "prior_recipe", "allowed_operations", "units", "oracle_kind",
                           "approval_mode", "budget", "endpoints", "fidelity", "diagnostic_tolerance",
                           "required_title", "reuse_plan", "refusal_conditions", "waivers", "oracle_sha256",
                           "source", "provisional"),
    "claim": ("schema_version", "claim_id", "status", "text", "quantity", "unit", "role",
              "expected_quantile", "artifact_field", "evidence_ids", "qualifiers"),
    # v2 (design §1.5): relation (eq, gt, ge, lt, le) and a categorical value; unit adds pb.
    "claim_v2": ("schema_version", "claim_id", "status", "text", "quantity", "unit", "role",
                 "expected_quantile", "artifact_field", "evidence_ids", "qualifiers", "relation", "value"),
    "submission": ("claims", "report_text", "refusal", "final"),
    "decision_record": ("schema_version", "run_id", "decision_id", "evidence_ids", "question", "action",
                        "brief_rationale", "falsification_test", "requested_budget", "timestamp_utc"),
    "judge_report": ("schema_version", "run_id", "campaign_id", "campaign_kind", "adapter", "synthetic",
                     "evidence_sha256", "oracle_sha256", "scorer_id", "review_state", "status",
                     "claim_findings", "gate_events", "quantities", "deliverable", "refusal",
                     "fidelity_error", "unresolved_items", "v1_outcome", "notes"),
    # v2 (WP12 design §3.6): the report of a task-bank scoring profile other than likelihood_freshness, whose
    # reports stay version 1. v1's keys plus the profile; findings, quantities and the refusal gain fields (below).
    "judge_report_v2": ("schema_version", "run_id", "campaign_id", "campaign_kind", "adapter", "synthetic",
                        "evidence_sha256", "oracle_sha256", "scorer_id", "review_state", "profile", "status",
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
BUDGET_FIELDS = ("usd_per_run", "seconds_per_run", "max_broker_ops", "max_fits", "max_stage_executions",
                 "global_usd_cap", "global_seconds_cap")
# The budget of a campaign frozen before WP12 (its broker had no census/calc stage budget): still verified and audited
# by this checkout, never run by it (runner.Campaign refuses it; E-24, decision E-151).
LEGACY_BUDGET_FIELDS = tuple(name for name in BUDGET_FIELDS if name != "max_stage_executions")
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
# Judge report v2: a finding also names the fault-value mechanism that decided it (or null), its claim relation and
# a categorical claim's value (then ``value`` is null); quantities count census and calc stages too (descriptive:
# waste is counted for fits only, design §1.8); the refusal records its evidence predicate and any other family's
# refusal condition that also matched (a boilerplate refusal is not valid, design §1.7).
FINDING_FIELDS_V2 = FINDING_FIELDS + ("mechanism", "relation", "categorical")
QUANTITY_COUNTS_V2 = QUANTITY_COUNTS + ("census_executed", "census_reused", "calc_executed", "calc_reused")
REFUSAL_FIELDS = ("present", "valid", "reason_matched")
REFUSAL_FIELDS_V2 = REFUSAL_FIELDS + ("evidence_matched", "other_conditions")
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


def _version(obj, label, versions=(1,)):
    require(type(obj["schema_version"]) is int and obj["schema_version"] in versions,
            f"{label}.schema_version: expected integer {' or '.join(map(str, versions))}")


def _declared_version(obj, versions, label) -> int:
    """The schema version a versioned record declares (task definition, claim). An object without
    schema_version, or not an object, goes to the version 1 rules, whose exact-key check names what is missing;
    a declared value other than one of the integers ``versions`` (never True or 2.0) is an error."""
    if isinstance(obj, dict) and "schema_version" in obj:
        version = obj["schema_version"]
        require(type(version) is int and version in versions,
                f"{label}.schema_version: expected integer {' or '.join(map(str, versions))}")
        return version
    return 1


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
    """A task definition of either schema version: schema_version 2 selects the WP12 bank rules
    (``_task_definition_v2``), anything else the unchanged §4.4 rules of version 1."""
    if _declared_version(obj, TASK_SCHEMA_VERSIONS, label) == 2:
        return _task_definition_v2(obj, label)
    return _task_definition_v1(obj, label)


def _task_definition_v1(obj, label):
    """§4.4 exact keys, plus ``canary`` (the family build's random canary) as the one optional key, as
    in the schema mirror: ``family.build_family`` always writes it, hand-built records (test fixtures)
    may omit it. It joins FIELDS as required only once every fixture carries it."""
    optional = ("canary",) if isinstance(obj, dict) and "canary" in obj else ()
    _fields(obj, FIELDS["task_definition"] + optional, label)
    _version(obj, label, TASK_SCHEMA_VERSIONS)
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


# ---- WP12 task definition v2 (taskbank design §1.2-§1.4, §1.7, §3.2) ---------------------------------------

def _input_name(value, name):
    require(isinstance(value, str) and len(value) <= 255 and _INPUT_NAME.fullmatch(value) is not None,
            f"{name}: a relative path of safe segments required (for example sample/events.lhe.gz)")


def _named_inputs_v2(value, name, *, nonempty):
    require(isinstance(value, list) and (bool(value) or not nonempty),
            f"{name}: {'nonempty ' if nonempty else ''}list required")
    for i, item in enumerate(value):
        _fields(item, ("name", "kind", "sha256"), f"{name}[{i}]")
        _input_name(item["name"], f"{name}[{i}].name")
        _one_of(item["kind"], tuple(bank.INPUT_KINDS), f"{name}[{i}].kind")
        _sha(item["sha256"], f"{name}[{i}].sha256")
    names = [item["name"] for item in value]
    require(len(set(names)) == len(names), f"{name}: duplicate input name")
    require(names == sorted(names), f"{name}: sorted by name")
    require(len({item["kind"] for item in value}) == len(value), f"{name}: at most one input per kind")


def _json_object(value, name):
    require(isinstance(value, dict), f"{name}: object required")
    try:
        canonical_bytes(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError(f"{name}: not strict JSON ({exc})") from None


def _prior_recipe(value, name):
    require(isinstance(value, list), f"{name}: list required")
    for i, step in enumerate(value):
        _fields(step, ("op", "params"), f"{name}[{i}]")
        _one_of(step["op"], tuple(bank.STAGES), f"{name}[{i}].op")
        _json_object(step["params"], f"{name}[{i}].params")


def _positive_int(value, name):
    require(type(value) is int and value > 0, f"{name}: positive integer required")


def _task_budget(value, name):
    _fields(value, bank.TASK_BUDGET_FIELDS, name)
    for key in ("max_broker_ops", "max_fits", "max_stage_executions"):
        _positive_int(value[key], f"{name}.{key}")
    require(finite_number(value["seconds_per_run"]) and value["seconds_per_run"] > 0,
            f"{name}.seconds_per_run: positive number required")


def _tolerance(value, metric, name):
    if metric == "relative_error":
        require(finite_number(value) and value > 0, f"{name}: a relative_error tolerance is a positive number")
    elif metric == "exact":
        require(finite_number(value) and value == 0, f"{name}: an exact metric has tolerance 0")
    else:
        require(value is None, f"{name}: a categorical metric has tolerance null")


def _endpoint(item, name, input_kinds):
    """One scored endpoint: a registered artifact field with its registered role and unit (a calc result's
    unit is the one the calc declares), a relation, a metric matching the field's type and its tolerance,
    and an optional evidence constraint on the cited artifact (design §1.6)."""
    _fields(item, ENDPOINT_FIELDS, name)
    field = item["field"]
    _one_of(field, tuple(bank.ARTIFACT_FIELDS), f"{name}.field")
    spec = bank.ARTIFACT_FIELDS[field]
    _one_of(item["role"], ROLES, f"{name}.role")
    require(item["role"] == spec["role"], f"{name}.role: {field} has role {spec['role']}")
    if spec["unit"] == "declared":
        _optional(item["unit"], lambda v, n: _one_of(v, UNITS_V2, n), f"{name}.unit")
    else:
        require(item["unit"] == spec["unit"], f"{name}.unit: {field} is in unit {spec['unit']}")
    _one_of(item["relation"], RELATIONS, f"{name}.relation")
    _one_of(item["metric"], METRICS, f"{name}.metric")
    categorical = bank.is_categorical(field)
    require((item["metric"] == "categorical") == categorical,
            f"{name}.metric: categorical iff {field} is a categorical field")
    require(not categorical or item["relation"] == "eq", f"{name}.relation: a categorical endpoint is eq")
    _tolerance(item["tolerance"], item["metric"], f"{name}.tolerance")
    constraint = item["evidence_constraint"]
    if constraint is not None:
        _fields(constraint, EVIDENCE_CONSTRAINT_FIELDS, f"{name}.evidence_constraint")
        _one_of(constraint["artifact"], bank.ARTIFACT_KINDS, f"{name}.evidence_constraint.artifact")
        _one_of(constraint["predicate"], bank.EVIDENCE_CONSTRAINTS, f"{name}.evidence_constraint.predicate")
        _one_of(constraint["input_kind"], tuple(sorted(input_kinds)), f"{name}.evidence_constraint.input_kind")


def _source_v2(source, name):
    _fields(source, SOURCE_FIELDS, name)
    _one_of(source["kind"], SOURCE_KINDS, f"{name}.kind")
    for key in ("license", "provenance"):
        _text(source[key], f"{name}.{key}")
    _strings(source["modifications"], f"{name}.modifications", unique=True)
    if source["kind"] == "synthetic_development":
        require(source["license"] == SYNTHETIC_LICENSE, f"{name}.license: {SYNTHETIC_LICENSE} for synthetic material")
        require(source["citation"] is None and source["modifications"] == [],
                f"{name}: synthetic material has no citation and no modifications")
    else:
        _text(source["citation"], f"{name}.citation")
        require(source["kind"] != "derived_from_published" or source["modifications"],
                f"{name}.modifications: material derived from a publication lists its modifications")


def _task_definition_v2(obj, label):
    """The WP12 bank's task definition (schema_version 2). The variant is the task's role in its primary
    pair (valid or fault) and twin_task_id names the other twin; the bank-level rules between twins
    (identical request bytes, budget and operations, declared differences) are ``validate_task_bank``'s."""
    optional = ("canary",) if isinstance(obj, dict) and "canary" in obj else ()
    _fields(obj, FIELDS["task_definition_v2"] + optional, label)
    _version(obj, label, (2,))
    if optional:
        _canary(obj["canary"], f"{label}.canary")
    for name in ("family", "objective"):
        _text(obj[name], f"{label}.{name}")
    _one_of(obj["variant"], PAIR_VARIANTS, f"{label}.variant")
    _opaque_task_id(obj["task_id"], f"{label}.task_id", obj["variant"])
    _opaque_task_id(obj["twin_task_id"], f"{label}.twin_task_id", obj["variant"])
    require(obj["twin_task_id"] != obj["task_id"], f"{label}.twin_task_id: names the other twin")
    for name in ("pair_id", "bank_version"):
        _safe_id(obj[name], f"{label}.{name}")
    _opaque_task_id(obj["pair_id"], f"{label}.pair_id")
    _one_of(obj["expected"], EXPECTED, f"{label}.expected")
    refusing = obj["expected"] == "refuse"
    require(obj["variant"] == "fault" or not refusing, f"{label}.expected: a valid twin is a completion task")
    _one_of(obj["stratum"], STRATA, f"{label}.stratum")
    _one_of(obj["split"], SPLITS, f"{label}.split")
    _one_of(obj["exposure_class"], EXPOSURE_CLASSES, f"{label}.exposure_class")
    _sha(obj["prompt_sha256"], f"{label}.prompt_sha256")
    _named_inputs_v2(obj["inputs"], f"{label}.inputs", nonempty=True)
    _named_inputs_v2(obj["prior_inputs"], f"{label}.prior_inputs", nonempty=False)
    _prior_recipe(obj["prior_recipe"], f"{label}.prior_recipe")
    require(bool(obj["prior_recipe"]) == bool(obj["prior_inputs"]),
            f"{label}.prior_recipe: nonempty iff there are prior inputs")
    kinds = {item["kind"] for item in obj["inputs"]}
    operations = obj["allowed_operations"]
    _strings(operations, f"{label}.allowed_operations", unique=True, nonempty=True)
    for i, op in enumerate(operations):
        _one_of(op, bank.OPERATIONS, f"{label}.allowed_operations[{i}]")
    require(operations == sorted(operations), f"{label}.allowed_operations: sorted")
    require(set(bank.REQUIRED_OPERATIONS) <= set(operations),
            f"{label}.allowed_operations: must include {list(bank.REQUIRED_OPERATIONS)}")
    units = obj["units"]
    require(isinstance(units, dict) and units, f"{label}.units: nonempty object required")
    for key, value in units.items():
        _text(key, f"{label}.units key")
        _text(value, f"{label}.units.{key}")
    _one_of(obj["oracle_kind"], ORACLE_KINDS, f"{label}.oracle_kind")
    _one_of(obj["approval_mode"], APPROVAL_MODES, f"{label}.approval_mode")
    require((obj["approval_mode"] == "supplied_approval_record") == ("approval" in kinds),
            f"{label}.approval_mode: supplied_approval_record iff an input of kind approval is supplied")
    _task_budget(obj["budget"], f"{label}.budget")
    endpoints = obj["endpoints"]
    require(isinstance(endpoints, list), f"{label}.endpoints: list required")
    for i, item in enumerate(endpoints):
        _endpoint(item, f"{label}.endpoints[{i}]", kinds)
    require(len({e["field"] for e in endpoints}) == len(endpoints), f"{label}.endpoints: duplicate field")
    require(bool(endpoints) != refusing, f"{label}.endpoints: nonempty iff expected is complete (a refusal "
                                         "task's optional numbers are scored under diagnostic_tolerance)")
    fidelity = obj["fidelity"]
    _fields(fidelity, ("metric", "quantity", "tolerance"), f"{label}.fidelity")
    _one_of(fidelity["metric"], METRICS, f"{label}.fidelity.metric")
    _one_of(fidelity["quantity"], tuple(bank.ARTIFACT_FIELDS), f"{label}.fidelity.quantity")
    require(fidelity["metric"] != "categorical" and not bank.is_categorical(fidelity["quantity"]),
            f"{label}.fidelity: the fidelity quantity is numeric")
    _optional(fidelity["tolerance"], _nonnegative, f"{label}.fidelity.tolerance")
    if refusing:
        require(fidelity["tolerance"] is None, f"{label}.fidelity.tolerance: must be null for a refusal task (as in v1)")
        require(finite_number(obj["diagnostic_tolerance"]) and obj["diagnostic_tolerance"] > 0,
                f"{label}.diagnostic_tolerance: a refusal task scores its optional numbers under a positive tolerance")
    else:
        target = next((e for e in endpoints if e["field"] == fidelity["quantity"]), None)
        require(target is not None and target["metric"] == fidelity["metric"]
                and canonical_bytes(target["tolerance"]) == canonical_bytes(fidelity["tolerance"]),
                f"{label}.fidelity: must point at an endpoint (the primary fidelity endpoint) with its metric "
                "and tolerance")
        require(obj["diagnostic_tolerance"] is None, f"{label}.diagnostic_tolerance: null for a completion task")
    titled = "title" in kinds
    _optional(obj["required_title"], _text, f"{label}.required_title")
    require((obj["required_title"] is not None) == (titled and not refusing),
            f"{label}.required_title: required iff a completion task is supplied a title")
    plan = obj["reuse_plan"]
    require(isinstance(plan, dict) and plan, f"{label}.reuse_plan: nonempty object required")
    for key, value in plan.items():
        match = _REUSE_STAGE.fullmatch(key)
        require(match is not None and match.group(1) in bank.STAGES
                and not bank.STAGES[match.group(1)]["coordinator_only"],
                f"{label}.reuse_plan: {key!r} is not a subject stage (stage or stage:qualifier)")
        _one_of(value, REUSE_PLANS, f"{label}.reuse_plan.{key}")
    require(("refuse" in plan.values()) == refusing, f"{label}.reuse_plan: a refuse stage iff expected is refuse")
    conditions = obj["refusal_conditions"]
    require(isinstance(conditions, list), f"{label}.refusal_conditions: list required")
    require(bool(conditions) == refusing, f"{label}.refusal_conditions: nonempty iff expected is refuse")
    for i, condition in enumerate(conditions):
        name = f"{label}.refusal_conditions[{i}]"
        _fields(condition, REFUSAL_CONDITION_FIELDS, name)
        _safe_id(condition["id"], f"{name}.id")
        _text(condition["text"], f"{name}.text")
        _one_of(condition["matcher"], bank.REFUSAL_MATCHERS, f"{name}.matcher")
        _one_of(condition["evidence_predicate"], bank.REFUSAL_EVIDENCE, f"{name}.evidence_predicate")
    require(len({c["id"] for c in conditions}) == len(conditions), f"{label}.refusal_conditions: duplicate id")
    waivers = obj["waivers"]
    _strings(waivers, f"{label}.waivers", unique=True)
    for i, waiver in enumerate(waivers):
        _one_of(waiver, WAIVERS, f"{label}.waivers[{i}]")
    require(waivers == sorted(waivers), f"{label}.waivers: sorted")
    _sha(obj["oracle_sha256"], f"{label}.oracle_sha256")
    _source_v2(obj["source"], f"{label}.source")
    _bool(obj["provisional"], f"{label}.provisional")


# Fields every task of a bank shares (twin-invariant and campaign-wide: a subject's status and operations
# never tell twins apart, design §1.1), and fields the two twins of a pair share.
BANK_UNIFORM = ("bank_version", "split", "stratum", "budget", "allowed_operations")
TWIN_UNIFORM = ("family", "exposure_class", "prompt_sha256", "oracle_kind", "approval_mode", "units")


def twin_differences(first, second) -> list:
    """The subject-visible differences between two v2 task definitions (design §1.2): current input names whose
    kind or bytes differ or that only one task supplies, ``prior:<name>`` for prior inputs, and ``prior:<op>``
    for each prior-recipe step whose parameters differ (``prior:recipe`` when the steps themselves differ).
    Prior artifacts are the recipe applied to the prior inputs, so this covers their contents."""
    found = set()
    for key, prefix in (("inputs", ""), ("prior_inputs", PRIOR_PREFIX)):
        left = {i["name"]: (i["kind"], i["sha256"]) for i in first[key]}
        right = {i["name"]: (i["kind"], i["sha256"]) for i in second[key]}
        found |= {prefix + name for name in set(left) | set(right) if left.get(name) != right.get(name)}
    ours, theirs = first["prior_recipe"], second["prior_recipe"]
    if [s["op"] for s in ours] != [s["op"] for s in theirs]:
        found.add(PRIOR_PREFIX + "recipe")
    else:
        found |= {PRIOR_PREFIX + a["op"] for a, b in zip(ours, theirs) if canonical_bytes(a) != canonical_bytes(b)}
    return sorted(found)


def validate_task_bank(definitions, contrasts, label="task bank", *, visible_oracle_values=()):
    """The WP12 bank rules over a whole family build or bank (design §1.1-§1.2, plan step 1): every definition
    is v2 and valid; bank_version, split, stratum, budget and allowed_operations are identical bank-wide;
    each pair_id has exactly one valid and one fault twin naming each other, with the same family, exposure
    class, request bytes (prompt_sha256), oracle kind, approval mode and units; every contrast names two
    tasks of one request whose subject-visible differences (``twin_differences``) are exactly its declared
    fault_inputs, and every pair has its primary contrast (id = pair_id, same twins and exposure class).
    Pair and contrast ids are checked for leaky words like task ids. ``visible_oracle_values`` (the index's
    declarations, design §1.1 rule 2) name tasks and their endpoint fields; a task carries
    visibility_waiver_pending iff it has one (D-V is provisional). A fault twin is declared only at a location
    where its valid twin is declared too (shared evidence both twins legitimately show, such as a correct prior
    fit, E-126). Whether the twin shows a value that is not its own answer at a valid twin's location (rule 3)
    needs the oracle values: the family builder checks it."""
    require(isinstance(definitions, list) and definitions, f"{label}: nonempty list of task definitions required")
    by_id = {}
    for i, definition in enumerate(definitions):
        validate_task_definition(definition, f"{label}.definitions[{i}]")
        require(definition["schema_version"] == 2, f"{label}.definitions[{i}]: a bank holds schema_version 2 "
                                                   "definitions")
        require(definition["task_id"] not in by_id, f"{label}: duplicate task {definition['task_id']!r}")
        by_id[definition["task_id"]] = definition
    first = definitions[0]
    for name in BANK_UNIFORM:
        differing = sorted(t for t, d in by_id.items() if canonical_bytes(d[name]) != canonical_bytes(first[name]))
        require(not differing, f"{label}: {name} must be identical in every task (twin-invariant and campaign-wide); "
                               f"{differing} differ from {first['task_id']}")
    pairs = {}
    for definition in definitions:
        pairs.setdefault(definition["pair_id"], []).append(definition)
    for pair_id, members in sorted(pairs.items()):
        require(len(members) == 2 and {m["variant"] for m in members} == set(PAIR_VARIANTS),
                f"{label}: pair {pair_id} needs exactly one valid and one fault twin, has "
                f"{sorted((m['task_id'], m['variant']) for m in members)}")
        valid, fault = sorted(members, key=lambda m: m["variant"] != "valid")
        require(valid["twin_task_id"] == fault["task_id"] and fault["twin_task_id"] == valid["task_id"],
                f"{label}: pair {pair_id}: twin_task_id must name the other twin")
        for name in TWIN_UNIFORM:
            require(canonical_bytes(valid[name]) == canonical_bytes(fault[name]),
                    f"{label}: pair {pair_id}: {name} differs between the twins")
    require(isinstance(contrasts, list) and contrasts, f"{label}.contrasts: nonempty list required")
    seen = {}
    for i, contrast in enumerate(contrasts):
        name = f"{label}.contrasts[{i}]"
        _fields(contrast, CONTRAST_FIELDS, name)
        _safe_id(contrast["id"], f"{name}.id")
        _opaque_task_id(contrast["id"], f"{name}.id")
        require(contrast["id"] not in seen, f"{name}.id: duplicate contrast {contrast['id']!r}")
        for role in ("valid", "fault"):
            require(isinstance(contrast[role], str) and contrast[role] in by_id,
                    f"{name}.{role}: a task of this bank required")
        require(contrast["valid"] != contrast["fault"], f"{name}: compares two different tasks")
        _one_of(contrast["exposure_class"], EXPOSURE_CLASSES, f"{name}.exposure_class")
        declared = contrast["fault_inputs"]
        _strings(declared, f"{name}.fault_inputs", unique=True, nonempty=True)
        require(declared == sorted(declared), f"{name}.fault_inputs: sorted")
        valid, fault = by_id[contrast["valid"]], by_id[contrast["fault"]]
        require(valid["variant"] == "valid", f"{name}.valid: {valid['task_id']} is not a valid twin")
        require(valid["family"] == fault["family"] and valid["prompt_sha256"] == fault["prompt_sha256"],
                f"{name}: a contrast compares two tasks of one family with identical request bytes")
        observed = twin_differences(valid, fault)
        require(observed == declared, f"{name}: the subject-visible differences {observed} are not the declared "
                                      f"fault_inputs {declared}")
        seen[contrast["id"]] = contrast
    require(isinstance(visible_oracle_values, (list, tuple)), f"{label}.visible_oracle_values: list required")
    declared = set()
    for i, entry in enumerate(visible_oracle_values):
        name = f"{label}.visible_oracle_values[{i}]"
        _fields(entry, VISIBLE_VALUE_FIELDS, name)
        require(isinstance(entry["task"], str) and entry["task"] in by_id, f"{name}.task: a task of this bank required")
        definition = by_id[entry["task"]]
        _text(entry["location"], f"{name}.location")
        _one_of(entry["field"], tuple(e["field"] for e in definition["endpoints"]), f"{name}.field")
        _one_of(entry["provenance"], VISIBLE_PROVENANCE, f"{name}.provenance")
        key = (entry["task"], entry["location"], entry["field"])
        require(key not in declared, f"{name}: declared twice")
        declared.add(key)
    for task, location, field in sorted(declared):
        definition = by_id[task]
        require(definition["variant"] == "valid" or (definition["twin_task_id"], location, field) in declared,
                f"{label}.visible_oracle_values: {task} is a fault twin; a fault twin's visible value is declared only "
                f"where its valid twin shows its answer too (shared evidence), not at {location!r} ({field})")
    visible = {task for task, _, _ in declared}
    waived = {t for t, d in by_id.items() if VISIBILITY_WAIVER in d["waivers"]}
    require(waived == visible, f"{label}: {VISIBILITY_WAIVER} must mark exactly the tasks with a declared visible "
                               f"oracle value (marked {sorted(waived)}, declared {sorted(visible)})")
    for pair_id, members in sorted(pairs.items()):
        valid, fault = sorted(members, key=lambda m: m["variant"] != "valid")
        primary = seen.get(pair_id)
        require(primary is not None and (primary["valid"], primary["fault"], primary["exposure_class"])
                == (valid["task_id"], fault["task_id"], valid["exposure_class"]),
                f"{label}.contrasts: pair {pair_id} needs its primary contrast (id {pair_id}, valid "
                f"{valid['task_id']}, fault {fault['task_id']}, exposure class {valid['exposure_class']})")


# ---- version-independent reads of a task definition or claim (consumers of both schema versions) -----------

def required_claims(definition) -> list:
    """[{field, role, unit}] a completion delivery must carry: v1 required_claims, v2 endpoints."""
    if definition["schema_version"] == 2:
        return [{"field": e["field"], "role": e["role"], "unit": e["unit"]} for e in definition["endpoints"]]
    return [dict(claim) for claim in definition["required_claims"]]


def reuse_plan(definition) -> dict:
    """{stage: reuse|execute|optional|refuse|not_required}: v2 reuse_plan, v1 reuse_expectation mapped."""
    if definition["schema_version"] == 2:
        return dict(definition["reuse_plan"])
    return dict(V1_REUSE_PLANS[definition["reuse_expectation"]])


def refusal_texts(definition) -> list:
    """The refusal conditions' texts: v1 strings, v2 each condition's text."""
    if definition["schema_version"] == 2:
        return [condition["text"] for condition in definition["refusal_conditions"]]
    return list(definition["refusal_conditions"])


def claim_relation(claim) -> str:
    """A claim's relation: v2 its own, v1 always eq (design §1.5)."""
    return claim["relation"] if claim["schema_version"] == 2 else "eq"


# ---- §4.5-§4.7 subject-submitted records ------------------------------------------------------

def validate_claim(obj, label="claim"):
    """Structural claim contract of either schema version (schema_version 2: ``_claim_v2``). Role/unit/value
    consistency with the cited artifact is a guard diagnostic (§7), not a contract error, so it is
    deliberately not checked here."""
    if _declared_version(obj, CLAIM_SCHEMA_VERSIONS, label) == 2:
        return _claim_v2(obj, label)
    _fields(obj, FIELDS["claim"], label)
    _version(obj, label, CLAIM_SCHEMA_VERSIONS)
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


def _claim_v2(obj, label):
    """Claim schema version 2 (design §1.5): unit adds pb; ``relation`` (eq, gt, ge, lt, le) states whether
    the quantity is the value or a bound on it (a non-eq relation needs a numeric quantity); ``value`` is a
    categorical claim's boolean or string for a registered categorical field (quantity and unit null). The
    artifact_field is any registered field (tasks/registry.py) and is required iff a quantity or a value
    is given. As in v1, consistency with the cited artifact is the guard's and the evaluator's."""
    _fields(obj, FIELDS["claim_v2"], label)
    _version(obj, label, (2,))
    _text(obj["claim_id"], f"{label}.claim_id")
    _one_of(obj["status"], CLAIM_STATUSES, f"{label}.status")
    _string(obj["text"], f"{label}.text")
    quantity, value, field = obj["quantity"], obj["value"], obj["artifact_field"]
    _optional(quantity, parse_decimal, f"{label}.quantity")
    _optional(obj["unit"], lambda v, n: _one_of(v, UNITS_V2, n), f"{label}.unit")
    _one_of(obj["role"], ROLES, f"{label}.role")
    _optional(obj["expected_quantile"], lambda v, n: _one_of(v, QUANTILES, n), f"{label}.expected_quantile")
    require((obj["expected_quantile"] is not None) == (obj["role"] == "expected"),
            f"{label}.expected_quantile: required iff role is expected")
    _optional(field, lambda v, n: _one_of(v, tuple(bank.ARTIFACT_FIELDS), n), f"{label}.artifact_field")
    require(value is None or type(value) is bool or (isinstance(value, str) and value.strip() != ""),
            f"{label}.value: null, a boolean or a nonblank string")
    require(quantity is None or value is None, f"{label}: quantity and value are exclusive")
    require((field is not None) == (quantity is not None or value is not None),
            f"{label}.artifact_field: required iff quantity or value is non-null")
    if quantity is not None:
        require(not bank.is_categorical(field), f"{label}.quantity: {field} is a categorical field (use value)")
    if value is not None:
        kind = bank.ARTIFACT_FIELDS[field]["type"]
        require(kind == ("boolean" if type(value) is bool else "string"),
                f"{label}.value: {field} is a {kind} field")
        require(obj["unit"] is None, f"{label}.unit: null for a categorical value")
    _one_of(obj["relation"], RELATIONS, f"{label}.relation")
    require(obj["relation"] == "eq" or quantity is not None,
            f"{label}.relation: {obj['relation']} bounds a numeric quantity")
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
    legacy = isinstance(budget, dict) and set(budget) == set(LEGACY_BUDGET_FIELDS)
    _fields(budget, LEGACY_BUDGET_FIELDS if legacy else BUDGET_FIELDS, f"{label}.budget")
    for name in ("usd_per_run", "seconds_per_run", "global_usd_cap", "global_seconds_cap"):
        require(finite_number(budget[name]) and budget[name] > 0, f"{label}.budget.{name}: positive number required")
    for name in ("max_broker_ops", "max_fits") + (() if legacy else ("max_stage_executions",)):
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

def _categorical_value(value, name):
    require(type(value) is bool or (isinstance(value, str) and value.strip() != ""),
            f"{name}: a boolean or a nonblank string")


def validate_judge_report(obj, label="judge_report"):
    """The §4.8 judge report. Version 1 (likelihood_freshness, unchanged); version 2 (every other task-bank
    scoring profile, design §3.6): ``profile``, findings with ``mechanism``, ``relation`` and ``categorical``,
    quantities with census and calc counts, the refusal's ``evidence_matched`` and ``other_conditions``, the
    verdict scope_change and any registered artifact field. The v1 outcome row is the same in both."""
    v2 = _declared_version(obj, (1, 2), label) == 2
    _fields(obj, FIELDS["judge_report_v2" if v2 else "judge_report"], label)
    _version(obj, label, (2,) if v2 else (1,))
    if v2:
        _one_of(obj["profile"], tuple(bank.FAMILIES), f"{label}.profile")
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
        _fields(finding, FINDING_FIELDS_V2 if v2 else FINDING_FIELDS, name)
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
        _optional(finding["field"], (lambda v, n: _one_of(v, tuple(bank.ARTIFACT_FIELDS), n)) if v2 else
                  _artifact_field, f"{name}.field")
        _optional(finding["value"], parse_decimal, f"{name}.value")
        _one_of(finding["verdict"], VERDICTS_V2 if v2 else VERDICTS, f"{name}.verdict")
        if v2:
            _optional(finding["mechanism"], lambda v, n: require(isinstance(v, str) and bank.SAFE.fullmatch(v)
                                                                 is not None, f"{n}: an identifier"),
                      f"{name}.mechanism")
            _one_of(finding["relation"], RELATIONS, f"{name}.relation")
            _optional(finding["categorical"], _categorical_value, f"{name}.categorical")
            require(finding["categorical"] is None or (finding["value"] is None and finding["field"] is not None
                                                       and bank.is_categorical(finding["field"])),
                    f"{name}.categorical: the value of a categorical field (value null)")
        _optional(finding["relative_error"], _nonnegative, f"{name}.relative_error")
        require(finding["relative_error"] is None or finding["value"] is not None,
                f"{name}.relative_error: requires a value")
        _bool(finding["delivered"], f"{name}.delivered")
        _bool(finding["attempted"], f"{name}.attempted")
        require(finding["attempted"] or not finding["delivered"], f"{name}: a delivered claim was attempted")

    quantities = obj["quantities"]
    counts = QUANTITY_COUNTS_V2 if v2 else QUANTITY_COUNTS
    _fields(quantities, counts + QUANTITY_FLAGS, f"{label}.quantities")
    for name in counts:
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
    _fields(refusal, REFUSAL_FIELDS_V2 if v2 else REFUSAL_FIELDS, f"{label}.refusal")
    _bool(refusal["present"], f"{label}.refusal.present")
    _optional_bool(refusal["valid"], f"{label}.refusal.valid")
    _optional_bool(refusal["reason_matched"], f"{label}.refusal.reason_matched")
    require(refusal["present"] or refusal["reason_matched"] is None,
            f"{label}.refusal.reason_matched: null when no refusal is present")
    require(refusal["valid"] is not True or (refusal["present"] and refusal["reason_matched"] is True),
            f"{label}.refusal.valid: a valid refusal is present and names the matching reason (§11)")
    if v2:
        _optional_bool(refusal["evidence_matched"], f"{label}.refusal.evidence_matched")
        other = refusal["other_conditions"]
        require(isinstance(other, list) and len(set(other)) == len(other)
                and all(isinstance(m, str) and m in bank.REFUSAL_MATCHERS for m in other),
                f"{label}.refusal.other_conditions: unique registry refusal matchers")
        require(refusal["present"] or (refusal["evidence_matched"] is None and not other),
                f"{label}.refusal: evidence_matched null and other_conditions empty when no refusal is present")
        require(refusal["valid"] is not True or (refusal["evidence_matched"] is not False and not other),
                f"{label}.refusal.valid: a valid refusal has its evidence and matches no other condition (§1.7)")
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
        require(all(quantities[n] == 0 for n in counts)
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


# ---- real-host smoke: host_launch v2, approval record v2, approval ledger (smoke spec WI-1, WI-5, R1, R9) ----
# Not part of FIELDS (whose records have JSON Schema mirrors): these live in coordinator/config.json, the frozen
# approval_record and <store>/live-approvals.jsonl.
HOST_LAUNCH_FIELDS = ("schema_version", "host_state_root", "binary_access", "proxy", "credential", "claude",
                      "mach_services_removed", "deny_roots")
HOST_LAUNCH_CLAUDE_FIELDS = ("max_turns", "effort", "permission_mode", "setting_sources", "tools", "allowed_tools",
                             "disallowed_tools", "subprocess_env_scrub", "shell", "cert_store", "env_pins")
PROXY_ATTRIBUTIONS = ("leader_pid",)
# The keychain services a real host's profile must not reach (R1); trustd stays (certificate evaluation).
KEYCHAIN_MACH_SERVICES = ("com.apple.SecurityServer", "com.apple.securityd.xpc")
KEPT_MACH_SERVICES = ("com.apple.trustd.agent",)
# Deny roots every real host's profile carries besides the credential directory (R1), matched by their tail so the
# record stays checkable on any home directory.
REQUIRED_DENY_TAILS = ("/Library/Keychains", "/.claude.json")
HOST_PORT = re.compile(r"([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?):([0-9]{1,5})")
SMOKE_APPROVAL_FIELDS = ("schema_version", "kind", "approved_by", "approved_utc", "authorization_text", "scope",
                         "caps", "spend_envelope", "credential", "account_preconditions", "decisions",
                         "human_reviews", "retry_policy", "single_use")
# What the global USD cap is, stated in the approval the budget owner signs (E-94): the runner admits a run while the
# remaining budget is at least usd_per_run, so the cap is an admission threshold, not a ceiling. An approval must
# carry exactly this text.
SMOKE_SPEND_ENVELOPE = (
    "global_usd_cap is an admission threshold, not a ceiling: a run is admitted while the remaining budget is at "
    "least usd_per_run. Worst case G + (k+1+r)*T: G the global cap; T one crossing turn (the host checks "
    "--max-budget-usd between messages, and a run that overshoots its cap by more than T stops the campaign, S5); k "
    "the runs charged usd_per_run because their cost is unknown (a timeout or a lost launch spends at most "
    "usd_per_run + T); r the requests the host retried, whose partial responses total_cost_usd does not count. "
    "live-checks --costs reports T, k and r.")
SMOKE_SCOPE_FIELDS = ("tasks", "seeds", "arms", "assignments", "host")
SMOKE_HOST_FIELDS = ("adapter", "version", "executable_sha256", "model", "effort")
SMOKE_CAPS_FIELDS = ("usd_per_run", "seconds_per_run", "runs", "global_usd_cap", "global_seconds_cap")
SMOKE_CREDENTIAL_FIELDS = ("kind", "env_name", "revoke_after_smoke")
SMOKE_ACCOUNT_FIELDS = ("usage_credits_or_extra_usage", "managed_policy", "shared_quota_accepted")
# Signed decisions an approval must name (R19); keeping the token after the smoke needs its own (R4).
SMOKE_DECISION_FIELDS = ("subprocess_env_scrub_off", "multiprocessing_unavailable")
TOKEN_RETENTION_DECISION = "token_retention"
CREDENTIAL_KINDS = ("claude_subscription_oauth_setup_token",)
USAGE_CREDITS = re.compile(r"off|capped:([0-9]+(?:\.[0-9]+)?)")
LEDGER_FIELDS = ("approval_sha256", "campaign_id", "created_utc")


def _live_modules():
    """(claude_cli, isolation), imported on first use: the real-host records are checked against the adapter's
    choices and the profile's mach services, while the independent evaluator (audit imports this module) keeps an
    import graph free of the coordinator's launcher."""
    from . import isolation
    from .adapters import claude_cli
    return claude_cli, isolation


def _paths(value, name, *, nonempty=False):
    require(isinstance(value, list), f"{name}: list required")
    require(not nonempty or value, f"{name}: nonempty list required")
    for i, item in enumerate(value):
        _absolute_path(item, f"{name}[{i}]")
    require(len(set(value)) == len(value), f"{name}: duplicate entries")


def _tool_names(value, name):
    claude_cli, _ = _live_modules()
    _strings(value, name, unique=True)
    require(not set(claude_cli.WEB_TOOLS) & set(value), f"{name}: web tools must stay disabled")


def _credential_env_name(value, name):
    _, isolation = _live_modules()
    require(isinstance(value, str) and ENV_NAME.fullmatch(value) is not None, f"{name}: variable name required")
    require(isolation.SECRET_NAME.search(value) is not None and value not in isolation.SECRET_NAME_ALLOWLIST,
            f"{name}: {value!r} is not a credential variable name")


def validate_host_launch(obj, label="host_launch"):
    """A real host's launch declaration (coordinator/config.json ``host_launch``, schema_version 2): the per-run
    state root, the pinned binary's read access (one literal for a single-file pin or one root for a copied
    ``.app``), the proxy allowlist with leader-pid attribution, the credential's variable name and file (never
    a value), the Claude CLI settings the adapter binds, the removed keychain mach services and the deny roots
    (the credential directory, ``~/Library/Keychains`` and ``~/.claude.json`` at least)."""
    claude_cli, isolation = _live_modules()
    _fields(obj, HOST_LAUNCH_FIELDS, label)
    require(type(obj["schema_version"]) is int and obj["schema_version"] == 2,
            f"{label}.schema_version: expected integer 2")
    _absolute_path(obj["host_state_root"], f"{label}.host_state_root")
    access = obj["binary_access"]
    _fields(access, ("read_literals", "read_roots"), f"{label}.binary_access")
    _paths(access["read_literals"], f"{label}.binary_access.read_literals")
    _paths(access["read_roots"], f"{label}.binary_access.read_roots")
    require(len(access["read_literals"]) + len(access["read_roots"]) == 1,
            f"{label}.binary_access: exactly one read literal (a single-file pin) or one read root (a copied .app)")
    require(all(root.endswith(".app") for root in access["read_roots"]),
            f"{label}.binary_access.read_roots: only a copied .app bundle is a binary read root")
    proxy = obj["proxy"]
    _fields(proxy, ("allow", "no_proxy", "attribution"), f"{label}.proxy")
    _strings(proxy["allow"], f"{label}.proxy.allow", unique=True, nonempty=True)
    for i, target in enumerate(proxy["allow"]):
        match = HOST_PORT.fullmatch(target)
        require(match is not None and 0 < int(match.group(2)) < 65536,
                f"{label}.proxy.allow[{i}]: host:port required, got {target!r}")
    _text(proxy["no_proxy"], f"{label}.proxy.no_proxy")
    _one_of(proxy["attribution"], PROXY_ATTRIBUTIONS, f"{label}.proxy.attribution")
    credential = obj["credential"]
    _fields(credential, ("env_name", "file", "expected_api_key_source"), f"{label}.credential")
    _credential_env_name(credential["env_name"], f"{label}.credential.env_name")
    _absolute_path(credential["file"], f"{label}.credential.file")
    _text(credential["expected_api_key_source"], f"{label}.credential.expected_api_key_source")
    claude = obj["claude"]
    _fields(claude, HOST_LAUNCH_CLAUDE_FIELDS, f"{label}.claude")
    require(type(claude["max_turns"]) is int and claude["max_turns"] > 0, f"{label}.claude.max_turns: positive integer")
    _one_of(claude["effort"], claude_cli.EFFORTS, f"{label}.claude.effort")
    _one_of(claude["permission_mode"], claude_cli.PERMISSION_MODES, f"{label}.claude.permission_mode")
    sources = claude["setting_sources"]
    _string(sources, f"{label}.claude.setting_sources")
    parts = sources.split(",") if sources else []
    require(all(p in claude_cli.SETTING_SOURCES for p in parts) and len(set(parts)) == len(parts),
            f"{label}.claude.setting_sources: comma list drawn from {list(claude_cli.SETTING_SOURCES)} or empty")
    _tool_names(claude["tools"], f"{label}.claude.tools")
    _tool_names(claude["allowed_tools"], f"{label}.claude.allowed_tools")
    _strings(claude["disallowed_tools"], f"{label}.claude.disallowed_tools", unique=True)
    require(set(claude_cli.WEB_TOOLS) <= set(claude["disallowed_tools"]),
            f"{label}.claude.disallowed_tools: must include {list(claude_cli.WEB_TOOLS)}")
    _bool(claude["subprocess_env_scrub"], f"{label}.claude.subprocess_env_scrub")
    _one_of(claude["shell"], claude_cli.SHELLS, f"{label}.claude.shell")
    _one_of(claude["cert_store"], claude_cli.CERT_STORES, f"{label}.claude.cert_store")
    pins = claude["env_pins"]
    require(isinstance(pins, dict), f"{label}.claude.env_pins: object required")
    for pin, value in pins.items():
        require(pin in claude_cli.ENV_PIN_NAMES, f"{label}.claude.env_pins: {pin!r} is not a documented pin "
                                                 f"({list(claude_cli.ENV_PIN_NAMES)})")
        require(isinstance(value, str) and "\x00" not in value, f"{label}.claude.env_pins.{pin}: string required")
        require(claude_cli.PAID_PATH_ENV.get(pin, value) == value,
                f"{label}.claude.env_pins.{pin}: may only repeat the adapter's {claude_cli.PAID_PATH_ENV.get(pin)!r}")
    removed = obj["mach_services_removed"]
    _strings(removed, f"{label}.mach_services_removed", unique=True)
    require(all(s in isolation.MACH_SERVICES for s in removed),
            f"{label}.mach_services_removed: names outside the profile's mach services")
    require(set(KEYCHAIN_MACH_SERVICES) <= set(removed),
            f"{label}.mach_services_removed: must remove the keychain services {list(KEYCHAIN_MACH_SERVICES)}")
    require(not set(KEPT_MACH_SERVICES) & set(removed),
            f"{label}.mach_services_removed: {list(KEPT_MACH_SERVICES)} stays (certificate evaluation)")
    deny = obj["deny_roots"]
    _paths(deny, f"{label}.deny_roots", nonempty=True)
    require(os.path.dirname(credential["file"]) in deny,
            f"{label}.deny_roots: must deny the credential's directory {os.path.dirname(credential['file'])}")
    for tail in REQUIRED_DENY_TAILS:
        require(any(root.endswith(tail) for root in deny), f"{label}.deny_roots: must deny a '...{tail}' root")


def _positive(value, name):
    require(finite_number(value) and type(value) is not bool and value > 0, f"{name}: positive number required")


def validate_smoke_approval(obj, label="approval_record"):
    """The budget owner's approval of one real-host synthetic smoke (schema_version 2, strict keys). The record
    is structural here; ``live.approval_problems`` compares it with the campaign (caps, scope, host, ledger)."""
    claude_cli, _ = _live_modules()
    _fields(obj, SMOKE_APPROVAL_FIELDS, label)
    require(type(obj["schema_version"]) is int and obj["schema_version"] == 2,
            f"{label}.schema_version: expected integer 2")
    _one_of(obj["kind"], ("synthetic_engineering_smoke",), f"{label}.kind")
    _text(obj["approved_by"], f"{label}.approved_by")
    _utc(obj["approved_utc"], f"{label}.approved_utc")
    _text(obj["authorization_text"], f"{label}.authorization_text")
    scope = obj["scope"]
    _fields(scope, SMOKE_SCOPE_FIELDS, f"{label}.scope")
    _strings(scope["tasks"], f"{label}.scope.tasks", unique=True, nonempty=True)
    for i, task_id in enumerate(scope["tasks"]):
        _opaque_task_id(task_id, f"{label}.scope.tasks[{i}]")
    seeds = scope["seeds"]
    require(isinstance(seeds, list) and seeds and all(type(s) is int and s >= 0 for s in seeds)
            and len(set(seeds)) == len(seeds), f"{label}.scope.seeds: nonempty list of distinct nonnegative integers")
    _strings(scope["arms"], f"{label}.scope.arms", unique=True, nonempty=True)
    for i, arm in enumerate(scope["arms"]):
        _one_of(arm, ARMS, f"{label}.scope.arms[{i}]")
    require(type(scope["assignments"]) is int
            and scope["assignments"] == len(scope["tasks"]) * len(seeds) * len(scope["arms"]),
            f"{label}.scope.assignments: must be tasks x seeds x arms")
    host = scope["host"]
    _fields(host, SMOKE_HOST_FIELDS, f"{label}.scope.host")
    _one_of(host["adapter"], ("claude_cli",), f"{label}.scope.host.adapter")
    for name in ("version", "model"):
        _text(host[name], f"{label}.scope.host.{name}")
    _sha(host["executable_sha256"], f"{label}.scope.host.executable_sha256")
    _one_of(host["effort"], claude_cli.EFFORTS, f"{label}.scope.host.effort")
    caps = obj["caps"]
    _fields(caps, SMOKE_CAPS_FIELDS, f"{label}.caps")
    for name in ("usd_per_run", "seconds_per_run", "global_usd_cap", "global_seconds_cap"):
        _positive(caps[name], f"{label}.caps.{name}")
    require(type(caps["runs"]) is int and caps["runs"] == scope["assignments"],
            f"{label}.caps.runs: must equal scope.assignments")
    require(caps["global_usd_cap"] >= caps["usd_per_run"] and caps["global_seconds_cap"] >= caps["seconds_per_run"],
            f"{label}.caps: a global cap is below its per-run cap")
    require(obj["spend_envelope"] == SMOKE_SPEND_ENVELOPE,
            f"{label}.spend_envelope: must be exactly contracts.SMOKE_SPEND_ENVELOPE (what the global USD cap is and "
            "the worst case the budget owner accepts: smoke-request.md S4)")
    credential = obj["credential"]
    _fields(credential, SMOKE_CREDENTIAL_FIELDS, f"{label}.credential")
    _one_of(credential["kind"], CREDENTIAL_KINDS, f"{label}.credential.kind")
    _credential_env_name(credential["env_name"], f"{label}.credential.env_name")
    _bool(credential["revoke_after_smoke"], f"{label}.credential.revoke_after_smoke")
    account = obj["account_preconditions"]
    _fields(account, SMOKE_ACCOUNT_FIELDS, f"{label}.account_preconditions")
    credits = account["usage_credits_or_extra_usage"]
    match = USAGE_CREDITS.fullmatch(credits) if isinstance(credits, str) else None
    require(match is not None and (match.group(1) is None or float(match.group(1)) > 0),
            f"{label}.account_preconditions.usage_credits_or_extra_usage: 'off' or 'capped:<positive usd>'")
    _one_of(account["managed_policy"], ("none",), f"{label}.account_preconditions.managed_policy")
    _bool(account["shared_quota_accepted"], f"{label}.account_preconditions.shared_quota_accepted")
    decisions = obj["decisions"]
    retained = credential["revoke_after_smoke"] is False
    _fields(decisions, SMOKE_DECISION_FIELDS + ((TOKEN_RETENTION_DECISION,) if retained else ()),
            f"{label}.decisions")
    for name, value in decisions.items():
        _text(value, f"{label}.decisions.{name}")
    _text(obj["human_reviews"], f"{label}.human_reviews")
    _text(obj["retry_policy"], f"{label}.retry_policy")
    require(obj["single_use"] is True, f"{label}.single_use: must be true (one campaign per approval)")


def validate_approval_ledger_entry(obj, label="approval ledger entry"):
    """One line of <store>/live-approvals.jsonl: the approval a real-host campaign consumed (R9)."""
    _fields(obj, LEDGER_FIELDS, label)
    _sha(obj["approval_sha256"], f"{label}.approval_sha256")
    _safe_id(obj["campaign_id"], f"{label}.campaign_id")
    _utc(obj["created_utc"], f"{label}.created_utc")
