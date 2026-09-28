"""WP12 task-bank registry (taskbank design §3.1): the registered families and the bank-wide vocabulary.

``FAMILIES`` maps a family name to its module, imported lazily by ``family_module`` so that
``contracts.py`` can read the vocabulary below without importing a family (every family imports
``contracts``). Each family module exports ``SPEC`` (checked by ``validate_spec``) and
``build_family(out_dir, *, canary=None, budget=None)``, which writes the family's evaluator tree and
returns its index. ``build_bank`` builds every registered family under one build canary and one task
budget and writes the bank index the runner freezes as ``coordinator/family/index.json``.

The vocabulary is the bank's: input kinds with their dependency class (which stale code a changed
input of that kind implies), stages, subject operations and artifact fields (numeric or categorical,
with role, expected quantile and unit). The stages (``stages/``) and the broker produce every artifact kind
here since design plan steps 4-5 (``census``, ``calc``, the coordinator-only ``figure`` step and the fit's
``cls_at_cap`` fields). The delivery guard reads its claim vocabulary from here (the field registry, the
dependency classes, ``ARTIFACT_DEPENDS`` and the units of supplied numbers; plan step 6) and judges claim
schema version 2; the broker accepts version 2 claims since the evaluator's task-bank profiles score them (plan
step 8). Standard library only.
"""
from __future__ import annotations

import importlib
import json
import re
import secrets
from pathlib import Path

from .. import canonical
from ..canonical import require as _require

# The bank version: frozen with the a/b draw seed of its new pairs; a task definition names it.
BANK_VERSION = "wp12-dev-1"
# bank version -> the seed of its a/b draw (design §0 Ids: which letter of a new pair is the valid twin;
# builder.valid_letter). Drawn once with secrets.token_hex(16) on 2026-09-27 and frozen with the version. The seed
# is committed here and valid_letter is public, so the draw is reproducible from the repository and blinds no one who
# reads it (decision E-153); only its result is written into subject-invisible files (family indexes, definitions).
# Subjects never see task ids (run ids are opaque). The LF letters stay lf-a..lf-d.
BANK_SEEDS = {"wp12-dev-1": "2184667441a027c05797e3c7031bbd6d"}
# name -> family module (relative to this package), in bank order: likelihood_freshness stays in every bank
# (design §3.1), then the counting families, then the LHE families (design §4 step 7).
FAMILIES = {"likelihood_freshness": ".development.likelihood_freshness.family",
            "poi_domain_limit": ".development.poi_domain_limit.family",
            "limit_summary": ".development.limit_summary.family",
            "yield_normalization": ".development.yield_normalization.family",
            "sample_census": ".development.sample_census.family"}
REQUIRED_FAMILIES = ("likelihood_freshness",)
# The families a campaign may schedule: those whose evaluator profile (plan step 8: audit.py for
# likelihood_freshness, audit_bank.py for the others) and fake-subject behaviours (step 9) exist, now every
# registered family (decision E-136). Every registered family is built into every frozen bank (so the bank rules,
# the admission canaries and the separation checks cover it); the runner selects tasks of these families only.
RUNNABLE_FAMILIES = ("likelihood_freshness", "poi_domain_limit", "limit_summary", "yield_normalization",
                     "sample_census")

# The uniform estimand clause every likelihood request carries verbatim (design §1.4 rule 1); a family whose
# oracle is the counting oracle must carry it once in its request. Toy-based CLs are not a convention
# alternative under it (taskbank-oracle-appendix §5 item 2, decision E-110).
ESTIMAND_CLAUSE = ("95% CLs upper limits on the number of signal events (asymptotic q-tilde, computed with the "
                   "task tool)")

# The subject-facing per-run limits a v2 task definition records (its ``budget``); equal to the campaign's. The
# broker enforces the three counts (max_stage_executions: census and calc operations, design §1.8).
TASK_BUDGET_FIELDS = ("max_broker_ops", "max_fits", "max_stage_executions", "seconds_per_run")
DESIGN_BUDGET = {"max_broker_ops": 30, "max_fits": 3, "max_stage_executions": 6, "seconds_per_run": 900}

DEPENDENCY_CLASSES = ("numerical", "conversion", "display", "none")
# input kind -> dependency class (design §3.1, §3.4), which chooses the guard's code for an artifact derived from a
# version of that input other than the current one: numerical (every value computed from it is invalid:
# stale_numerical_dependency), conversion (only the values that depend on it, ARTIFACT_DEPENDS:
# stale_conversion_dependency), display (a report under another title: display_outdated, informational) and none
# (an approval record is read, never computed from). The event files, the production record and the selection
# decide every census value, so they are numerical.
INPUT_KINDS = {
    "workspace": "numerical", "luminosity": "conversion", "title": "display",
    "events": "numerical", "archive_events": "numerical", "manifest": "numerical", "selection": "numerical",
    "approval": "none",
}
# input kind -> how the broker reads its bytes: a JSON object, UTF-8 text, or gzip bytes it never parses.
INPUT_FORMATS = {"workspace": "json", "luminosity": "json", "title": "text", "events": "gzip",
                 "archive_events": "gzip", "manifest": "json", "selection": "json", "approval": "json"}
# stage -> {artifact kind, coordinator_only}; a prior recipe may use every stage, a subject only the others.
STAGES = {
    "fit": {"artifact": "fit", "coordinator_only": False},
    "convert": {"artifact": "conversion", "coordinator_only": False},
    "report": {"artifact": "report", "coordinator_only": False},
    "census": {"artifact": "census", "coordinator_only": False},
    "calc": {"artifact": "calc", "coordinator_only": False},
    "figure": {"artifact": "figure", "coordinator_only": True},
}
# Every subject operation the bank may name; ``figure`` is a coordinator-only prior-recipe step, never one.
OPERATIONS = ("calc", "census", "convert", "fit", "inputs", "note", "report", "show", "status", "submit")
REQUIRED_OPERATIONS = ("inputs", "submit")
# The operations every task of this bank version allows: the broker's (the runner checks equality with
# broker.OPERATIONS); census and calc are available in every family (design §3.3).
CAMPAIGN_OPERATIONS = ("calc", "census", "convert", "fit", "inputs", "note", "report", "show", "status", "submit")

QUANTILES = ("-2", "-1", "0", "+1", "+2")   # index 0..4 of an expected band, -2 sigma .. +2 sigma
FIELD_TYPES = ("numeric", "boolean", "string")   # boolean and string fields are categorical


def _field(artifact, kind, role, quantile, unit):
    return {"artifact": artifact, "type": kind, "role": role, "quantile": quantile, "unit": unit}


# artifact field -> {artifact, type, role, quantile, unit}. unit None: dimensionless or categorical; "declared":
# the unit a calc artifact declares for its result. The first twelve are the v1 fields (contracts.ARTIFACT_FIELDS).
ARTIFACT_FIELDS = {"obs_limit_events": _field("fit", "numeric", "observed", None, "events"),
                   "sigma_vis_obs_fb": _field("conversion", "numeric", "observed", None, "fb")}
for _i, _q in enumerate(QUANTILES):
    ARTIFACT_FIELDS[f"exp_limits_events[{_i}]"] = _field("fit", "numeric", "expected", _q, "events")
    ARTIFACT_FIELDS[f"sigma_vis_exp_fb[{_i}]"] = _field("conversion", "numeric", "expected", _q, "fb")
V1_ARTIFACT_FIELDS = tuple(ARTIFACT_FIELDS)   # the version 1 claim vocabulary (contracts.ARTIFACT_FIELDS)
ARTIFACT_FIELDS["cls_at_cap_obs"] = _field("fit", "numeric", "observed", None, None)
for _i, _q in enumerate(QUANTILES):
    ARTIFACT_FIELDS[f"cls_at_cap_exp[{_i}]"] = _field("fit", "numeric", "expected", _q, None)
ARTIFACT_FIELDS.update({   # census integrity, then census physics (design §2 P5), then calc (§3.3)
    "gzip_complete": _field("census", "boolean", "not_applicable", None, None),
    "document_complete": _field("census", "boolean", "not_applicable", None, None),
    "complete_events": _field("census", "numeric", "not_applicable", None, "events"),
    "header_nevents": _field("census", "numeric", "not_applicable", None, "events"),
    "file_sha256": _field("census", "string", "not_applicable", None, None),
    "sha256_matches_record": _field("census", "boolean", "not_applicable", None, None),
    "stream_error": _field("census", "string", "not_applicable", None, None),
    "cross_section_pb": _field("census", "numeric", "not_applicable", None, "pb"),
    "integration_error_pb": _field("census", "numeric", "not_applicable", None, "pb"),
    "event_norm": _field("census", "string", "not_applicable", None, None),
    "sum_weights": _field("census", "numeric", "not_applicable", None, "pb"),
    "sum_weights_sq": _field("census", "numeric", "not_applicable", None, None),
    "selected_events": _field("census", "numeric", "not_applicable", None, "events"),
    "selected_sum_weights": _field("census", "numeric", "not_applicable", None, "pb"),
    "recipe_check": _field("census", "string", "not_applicable", None, None),
    "result": _field("calc", "numeric", "not_applicable", None, "declared"),
})
ARTIFACT_KINDS = tuple(sorted({spec["artifact"] for spec in STAGES.values()}))
# artifact kind -> the input kinds its values depend on (the guard's conversion-class check: a superseded luminosity
# invalidates cross sections, never event counts; design §3.4); None: whatever the artifact derives from (a calc
# combines the values it binds, so it depends on every input they derive from).
ARTIFACT_DEPENDS = {"fit": ("workspace",), "conversion": ("workspace", "luminosity"),
                    "report": ("workspace", "luminosity", "title"),
                    "census": ("events", "archive_events", "manifest", "selection"), "figure": ("workspace",),
                    "calc": None}
# Units a number carries (a field's, a calc's declared unit, a supplied record's); GeV and dimensionless numbers
# are not unit-bearing for the guard's prose check.
NUMBER_UNITS = ("events", "fb", "pb", "fb^-1", "pb^-1")
# The unit of every number of a supplied JSON input of these kinds (as in version 1: a workspace holds counts, a
# luminosity record an integrated luminosity); a number of another JSON input carries its key's unit (key_unit).
INPUT_RECORD_UNITS = {"workspace": "events", "luminosity": "fb^-1"}


def key_unit(key):
    """The unit of the numbers under one JSON key (design §3.4: a number licenses the pool its field unit implies):
    a registered artifact field's unit (its key without the index; a calc result's declared unit is the record's,
    so None here), ``fb^-1`` for ``luminosity_fb``, ``events`` for ``events`` and any key ending in ``_events``,
    otherwise None (not unit-bearing)."""
    if not isinstance(key, str):
        return None
    unit = _KEY_UNITS.get(key)
    if unit is not None or key in _KEY_UNITS:
        return unit
    if key == "luminosity_fb":
        return "fb^-1"
    return "events" if key == "events" or key.endswith("_events") else None


_KEY_UNITS = {}
for _name, _spec in ARTIFACT_FIELDS.items():
    _KEY_UNITS[_name.split("[")[0]] = _spec["unit"] if _spec["unit"] in NUMBER_UNITS else None

# Names the evaluator implements for refusal validity (design §1.7) and endpoint evidence constraints (§1.6).
REFUSAL_MATCHERS = ("luminosity_reason", "domain_no_crossing")
REFUSAL_EVIDENCE = ("inputs_listing_without_luminosity", "fit_on_current_workspace_not_resolved")
EVIDENCE_CONSTRAINTS = ("derived_from_current_input", "file_sha256_matches_record")

SPEC_FIELDS = ("family", "request", "oracle_kind", "approval_mode", "input_kinds", "stages", "artifact_fields",
               "prior_recipe", "pairs", "contrasts", "scoring_profile")
PAIR_FIELDS = ("id", "valid", "fault", "exposure_class", "naive")
SAFE = re.compile(r"[a-z][a-z0-9_]{0,63}")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def new_canary() -> str:
    """A fresh build canary (contracts.CANARY): planted in every oracle record, task definition and index."""
    return "RAVEL-EVAL-CANARY-" + secrets.token_hex(16)


def family_module(name):
    """The registered family's module (imported on first use)."""
    _require(name in FAMILIES, f"unknown family {name!r}; registered: {sorted(FAMILIES)}")
    return importlib.import_module(FAMILIES[name], __package__)


def families() -> dict:
    """{name: module} of every registered family, in registration order."""
    return {name: family_module(name) for name in FAMILIES}


def is_categorical(field) -> bool:
    return ARTIFACT_FIELDS[field]["type"] != "numeric"


# The CLs values at the POI cap are diagnostics of the observed and expected curves; a claim may give them the role
# the field registry names (observed, expected with its quantile) or the claim role ``diagnostic`` (with no quantile:
# the claim contract allows one only for role expected), which the tool guide offers (decision E-148).
DIAGNOSTIC_FIELDS = ("cls_at_cap_obs",) + tuple(f"cls_at_cap_exp[{i}]" for i in range(len(QUANTILES)))


def role_accepted(field, role, quantile) -> bool:
    """True when a claim's (role, expected_quantile) is the registered field's, or ``diagnostic`` on a diagnostic
    field (DIAGNOSTIC_FIELDS)."""
    spec = ARTIFACT_FIELDS[field]
    if (role, quantile) == (spec["role"], spec["quantile"]):
        return True
    return field in DIAGNOSTIC_FIELDS and role == "diagnostic" and quantile is None


def validate_spec(spec, label="SPEC"):
    """Structural rules of a family SPEC (design §3.1). Raises ContractError."""
    _require(isinstance(spec, dict) and set(spec) == set(SPEC_FIELDS),
             f"{label}: fields must be {list(SPEC_FIELDS)}")
    _require(isinstance(spec["family"], str) and SAFE.fullmatch(spec["family"]) is not None,
             f"{label}.family: lowercase identifier required")
    _require(isinstance(spec["request"], str) and spec["request"].endswith(".md") and "/" not in spec["request"],
             f"{label}.request: a .md file beside the family module")
    kinds = spec["input_kinds"]
    _require(isinstance(kinds, dict) and kinds, f"{label}.input_kinds: nonempty object required")
    for kind, dependency in kinds.items():
        _require(INPUT_KINDS.get(kind) == dependency,
                 f"{label}.input_kinds.{kind}: must be a registry input kind with its dependency class "
                 f"({INPUT_KINDS.get(kind)!r})")
    stages = spec["stages"]
    _require(isinstance(stages, list) and stages and len(set(stages)) == len(stages)
             and all(s in STAGES for s in stages), f"{label}.stages: registry stages, unique")
    fields = spec["artifact_fields"]
    _require(isinstance(fields, list) and fields and len(set(fields)) == len(fields)
             and all(f in ARTIFACT_FIELDS and ARTIFACT_FIELDS[f]["artifact"] in
                     {STAGES[s]["artifact"] for s in stages} for f in fields),
             f"{label}.artifact_fields: registry fields of the family's stages, unique")
    recipe = spec["prior_recipe"]
    _require(isinstance(recipe, list) and all(isinstance(step, dict) and set(step) == {"op", "params"}
                                              and step["op"] in stages and isinstance(step["params"], dict)
                                              for step in recipe),
             f"{label}.prior_recipe: [{{op, params}}] over the family's stages")
    pairs = spec["pairs"]
    _require(isinstance(pairs, list) and pairs, f"{label}.pairs: nonempty list required")
    for i, pair in enumerate(pairs):
        _require(isinstance(pair, dict) and set(pair) == set(PAIR_FIELDS), f"{label}.pairs[{i}]: fields must be "
                                                                           f"{list(PAIR_FIELDS)}")
        for name in ("id", "valid", "fault"):
            _require(isinstance(pair[name], str) and SAFE_ID.fullmatch(pair[name]) is not None,
                     f"{label}.pairs[{i}].{name}: identifier required")
        _require(pair["valid"] != pair["fault"], f"{label}.pairs[{i}]: valid and fault twins differ")
        _require(isinstance(pair["naive"], str) and SAFE.fullmatch(pair["naive"]) is not None,
                 f"{label}.pairs[{i}].naive: a fake-subject behavior name")
    _require(len({p["id"] for p in pairs}) == len(pairs), f"{label}.pairs: duplicate id")
    twins = [t for p in pairs for t in (p["valid"], p["fault"])]
    _require(len(set(twins)) == len(twins), f"{label}.pairs: a task belongs to one primary pair")
    contrasts = spec["contrasts"]
    _require(isinstance(contrasts, list) and len({c.get("id") for c in contrasts if isinstance(c, dict)})
             == len(contrasts), f"{label}.contrasts: list with unique ids")
    for pair in pairs:
        _require({"id": pair["id"], "valid": pair["valid"], "fault": pair["fault"],
                  "exposure_class": pair["exposure_class"]}.items()
                 <= next((c for c in contrasts if isinstance(c, dict) and c.get("id") == pair["id"]), {}).items(),
                 f"{label}.contrasts: pair {pair['id']} needs its primary contrast (same id, twins and class)")
    _require(all(isinstance(c, dict) and {c.get("valid"), c.get("fault")} <= set(twins) for c in contrasts),
             f"{label}.contrasts: every contrast compares tasks of the family's pairs")
    _require(isinstance(spec["scoring_profile"], str) and SAFE.fullmatch(spec["scoring_profile"]) is not None,
             f"{label}.scoring_profile: identifier required")


def _pretty(value) -> bytes:
    return json.dumps(value, indent=1, sort_keys=True, allow_nan=False).encode() + b"\n"


def build_bank(out_dir, *, canary=None, budget=None) -> dict:
    """Build every registered family under ``out_dir/<family>/`` with one build canary and one task budget,
    check the bank (contracts.validate_task_bank over every definition, the estimand clause in every counting
    family's request) and write the bank index ``out_dir/index.json``; return it.

    The bank index lists every task with its paths relative to ``out_dir`` (so the runner and
    campaign_manifest read one index), each task's request, the merged path roles (the family indexes are
    evaluator-private too), the contrasts, the families and the v1 tasks. A failure raises; the family trees
    already written stay (the runner builds under a temporary directory it removes)."""
    from .. import contracts   # contracts imports this module: the validators are loaded on use
    out = Path(out_dir)
    _require(not out.exists() or (out.is_dir() and not any(out.iterdir())),
             f"{out}: output directory must be new or empty")
    for name in REQUIRED_FAMILIES + RUNNABLE_FAMILIES:
        _require(name in FAMILIES, f"family {name} must be registered in every bank")
    modules = families()
    canary = new_canary() if canary is None else canary
    budget = dict(DESIGN_BUDGET if budget is None else budget)
    _require(set(budget) == set(TASK_BUDGET_FIELDS), f"budget: fields must be {list(TASK_BUDGET_FIELDS)}")
    tasks, contrasts, visible, v1_tasks, definitions, listed = [], [], [], [], [], {}
    roles = {"subject_visible": [], "prior_inputs": [], "evaluator_private": ["index.json"]}
    for name, module in modules.items():
        validate_spec(module.SPEC, f"{name}.SPEC")
        _require(module.SPEC["family"] == name, f"{name}.SPEC.family: must be the registered name")
        index = module.build_family(out / name, canary=canary, budget=budget)
        _require(index["canary"] == canary, f"{name}: family index canary differs from the bank's")
        request = (out / name / index["request"]["path"]).read_bytes()
        if module.SPEC["oracle_kind"] == "counting":
            _require(request.decode("utf-8").replace("\n", " ").count(ESTIMAND_CLAUSE) == 1,
                     f"{name}: a counting family's request must carry the estimand clause once: {ESTIMAND_CLAUSE!r}")
        for role, paths in index["path_roles"].items():
            roles[role] += [f"{name}/{path}" for path in paths]
        listed[name] = {"path": name, "index_path": f"{name}/index.json",
                        "index_sha256": canonical.sha256_file(out / name / "index.json")}
        for task in index["tasks"]:
            entry = dict(task)
            entry["family"] = name
            entry["request_path"] = f"{name}/{index['request']['path']}"
            entry["prompt_sha256"] = index["request"]["sha256"]
            for key in ("definition_path", "oracle_path"):
                entry[key] = f"{name}/{task[key]}"
            entry["inputs"] = {side: {n: {**e, "path": f"{name}/{e['path']}"} for n, e in files.items()}
                               for side, files in task["inputs"].items()}
            definition = canonical.strict_load(out / entry["definition_path"])
            _require(definition["task_id"] == task["task_id"] and definition["family"] == name
                     and definition["prompt_sha256"] == entry["prompt_sha256"]
                     and canonical.canonical_bytes(definition["budget"]) == canonical.canonical_bytes(budget)
                     and definition["allowed_operations"] == list(CAMPAIGN_OPERATIONS),
                     f"{name}/{task['task_id']}: the definition's family, request, budget or operations differ from "
                     "the bank's")
            tasks.append(entry)
            definitions.append(definition)
        contrasts += index["contrasts"]
        visible += index["visible_oracle_values"]
        v1_tasks += index["v1_tasks"]
    contracts.validate_task_bank(definitions, contrasts, visible_oracle_values=visible)
    for task in tasks:
        _require(isinstance(task.get("value_canaries"), list) and all(isinstance(c, str) and c
                                                                      for c in task["value_canaries"]),
                 f"{task['family']}/{task['task_id']}: the family index lists no value_canaries")
    needles = sorted({c for task in tasks for c in task["value_canaries"]})
    for path in roles["subject_visible"]:          # every family's value canaries, against every visible byte
        data = (out / path).read_bytes()
        hits = [c for c in needles if c.encode() in data]
        _require(not hits, f"{path}: a subject-visible file holds the value canaries {hits}")
    bank = {"schema_version": 2, "bank_version": BANK_VERSION, "canary": canary, "synthetic": True,
            "provisional": True, "evaluator_private": True, "budget": budget,
            "allowed_operations": list(CAMPAIGN_OPERATIONS), "families": listed,
            "runnable_families": [name for name in FAMILIES if name in RUNNABLE_FAMILIES],
            "path_roles": {role: sorted(paths) for role, paths in roles.items()},
            "tasks": tasks, "contrasts": contrasts, "visible_oracle_values": visible, "v1_tasks": v1_tasks}
    written = sorted(e["path"] for e in canonical.tree_manifest(out)) + ["index.json"]
    _require(sorted(written) == sorted(p for paths in bank["path_roles"].values() for p in paths),
             "bank: every written path must have exactly one role")
    canonical.write_once(out / "index.json", _pretty(bank))
    return bank
