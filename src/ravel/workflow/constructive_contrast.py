"""Construct one controlled alternative from a public scientific objection.

No source execution, semantic-equivalence proof, causal certification or launch
authority. Rival predictions and next actions are supplied scientific judgments;
results use RAVEL's actual supplied-evidence diagnostic engine.
"""
from __future__ import annotations

from copy import deepcopy
import difflib
import hashlib
import json
from pathlib import Path

from ravel.physics import event_contrasts
from ravel.workflow import diagnostic_plan as dp
from ravel.workflow.execution import digest

MAX_SOURCE_BYTES = 128 * 1024
MAX_COMPONENT_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 512 * 1024
STATUSES = ("supported", "contradicted", "unresolved")
ACTIONS = ("request_evidence", "revise_hypothesis", "retain_incumbent", "propose_challenger_review")


def _bounded_text(value, label, maximum=4096):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError(label + " requires bounded nonempty text")


def _bounded_json(value):
    raw = json.dumps(value, allow_nan=False, sort_keys=True).encode()
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("constructive contrast request exceeds byte bound")
    return json.loads(raw)


def _read(pin, base_dir, *, maximum=MAX_SOURCE_BYTES):
    dp.binding(pin)
    p = Path(pin["path"]).expanduser()
    p = p if p.is_absolute() else Path(base_dir) / p
    if any(q.is_symlink() for q in (p, *p.parents)) or not p.is_file():
        raise ValueError("source must be a regular file without symlinks")
    if p.stat().st_size > maximum:
        raise ValueError("constructive source exceeds byte bound")
    raw = p.read_bytes()
    if len(raw) > maximum or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("constructive source bytes changed: " + pin["path"])
    return raw.decode("utf-8")


def _validate_contract(contract):
    """Scientific projection of diagnostic schema 2, without invented data pins."""
    dp.keys(contract, {"schema_version", "source", "question", "manipulation", "fixed_artifacts", "comparison",
                       "hypotheses", "precision", "data_use", "budget", "stopping", "applicability", "capacity",
                       "expected_exposure", "expected_scales", "original_census"}, "evaluation contract")
    if type(contract["schema_version"]) is not int or contract["schema_version"] != 2:
        raise ValueError("new constructive evaluation requires diagnostic schema 2")
    for key in ("source", "question"):
        dp.text(contract[key], key)
    dp.keys(contract["manipulation"], {"variable", "baseline", "candidate"}, "manipulation")
    for key, value in contract["manipulation"].items():
        dp.text(value, key)
    if type(contract["fixed_artifacts"]) is not list or not 1 <= len(contract["fixed_artifacts"]) <= 32:
        raise ValueError("contract needs bounded fixed artifacts")
    for pin in contract["fixed_artifacts"]:
        dp.binding(pin)
    comp = contract["comparison"]
    required = {"kind", "basis", "require_complete_exposure"}
    if type(comp) is dict and comp.get("kind") == "independent":
        required.add("uncertainty_relationship")
    dp.keys(comp, required, "prospective comparison")
    if comp["kind"] not in ("paired_events", "independent") or comp["require_complete_exposure"] is not True:
        raise ValueError("comparison requires paired/independent and complete exposure")
    dp.basis(comp["basis"])
    dp.keys(contract["expected_exposure"], {"baseline", "candidate"}, "prospective expected exposure")
    for value in contract["expected_exposure"].values():
        dp.integer(value, "expected exposure")
    if comp["kind"] == "paired_events":
        dp.binding(contract["original_census"])
        dp.keys(contract["expected_scales"], {"baseline", "candidate"}, "prospective normalization scales")
        for value in contract["expected_scales"].values():
            if dp.number(value, "prospective scale") <= 0:
                raise ValueError("paired scales must be explicitly positive")
    elif contract["original_census"] is not None or contract["expected_scales"] is not None:
        raise ValueError("independent estimates cannot claim paired census or event scales")
    if "uncertainty_relationship" in comp:
        rel = comp["uncertainty_relationship"]
        if type(rel) is not dict or rel.get("status") not in ("unavailable", "uncorrelated", "supplied"):
            raise ValueError("explicit uncertainty relationship status required")
        dp.keys(rel, {"status", "reason"} if rel["status"] == "unavailable" else {"status"}, "prospective uncertainty relationship")
        if rel["status"] == "unavailable":
            dp.text(rel["reason"], "uncertainty relationship reason")
    hypotheses = contract["hypotheses"]
    if type(hypotheses) is not list or not 1 <= len(hypotheses) <= 16:
        raise ValueError("bounded diagnostic criteria required")
    ids, channels = [], set()
    for h in hypotheses:
        dp.keys(h, {"id", "statement", "channels", "direction", "relative_tolerance"}, "criterion")
        ids.append(dp.text(h["id"], "criterion id")); dp.text(h["statement"], "criterion statement")
        dp.unique(h["channels"], "criterion channels")
        if not set(h["channels"]) <= set(comp["basis"]["channels"]):
            raise ValueError("criterion names unknown channel")
        channels.update(h["channels"])
        if h["direction"] not in ("equivalent", "increase", "decrease") or dp.number(h["relative_tolerance"], "tolerance") < 0:
            raise ValueError("invalid supplied directional criterion")
    dp.unique(ids, "criterion ids")
    if channels != set(comp["basis"]["channels"]):
        raise ValueError("every channel requires a criterion")
    precision = contract["precision"]
    dp.keys(precision, {"max_relative_mc_error", "envelope_sigma", "reference_covariance"}, "precision")
    if not 0 < dp.number(precision["max_relative_mc_error"], "precision") <= 1 or not 0 < dp.number(precision["envelope_sigma"], "envelope") <= 10:
        raise ValueError("invalid supplied precision")
    if precision["reference_covariance"] not in ("required", "exact_reference"):
        raise ValueError("explicit reference covariance semantics required")
    uses = contract["data_use"]
    if type(uses) is not list or not 1 <= len(uses) <= 32:
        raise ValueError("bounded prospective data use required")
    populations = {}
    for use in uses:
        dp.keys(use, {"population_id", "role"}, "prospective data use")
        dp.text(use["population_id"], "population id")
        if use["role"] not in ("calibration", "validation"):
            raise ValueError("unknown data role")
        populations.setdefault(use["population_id"], set()).add(use["role"])
    if any(len(x) != 1 for x in populations.values()):
        raise ValueError("calibration cannot become validation")
    dp.keys(contract["budget"], {"max_attempts", "max_seconds", "max_new_events"}, "budget")
    for key in contract["budget"]:
        dp.integer(contract["budget"][key], key, zero=key == "max_new_events")
    if contract["stopping"] != {"success": "all_criteria_supported", "failure": "any_criterion_contradicted", "unresolved": "stop_without_conclusion"}:
        raise ValueError("stopping must preserve adverse and unresolved results")
    dp.keys(contract["applicability"], {"status", "reason"}, "applicability")
    if contract["applicability"]["status"] not in ("established", "unresolved"):
        raise ValueError("unknown applicability")
    dp.text(contract["applicability"]["reason"], "applicability reason")
    if contract["capacity"] is not None:
        dp.keys(contract["capacity"], {"artifact", "lower_pointer", "upper_pointer", "target_pointer", "reason"}, "capacity")
        dp.binding(contract["capacity"]["artifact"])
        for key in ("lower_pointer", "upper_pointer", "target_pointer", "reason"):
            dp.text(contract["capacity"][key], key)
    return deepcopy(contract)


def _projection(plan):
    plan = dp.validate(plan)
    contract = deepcopy(plan)
    for role in ("baseline", "candidate"):
        del contract["comparison"][role]
    rel = contract["comparison"].get("uncertainty_relationship")
    if rel and rel["status"] != "unavailable":
        del rel["artifact"]
    contract["data_use"] = [{"population_id": use["population_id"], "role": use["role"]} for use in plan["data_use"]]
    return contract


def _bound_json(pin, base_dir):
    # Use the actual event adapter's artifact admission bound, before parsing.
    raw = _read(pin, base_dir, maximum=event_contrasts.resource_limits()["artifact_bytes"])
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate evidence JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite evidence JSON constant")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def freeze_contract(plan, *, original_census=None, base_dir="."):
    """Freeze all supplied scientific choices; measurement pins may arrive later.

    This does not create missing thresholds or measurement files. Callers may
    also supply this projected contract directly for a prospective experiment.
    """
    plan = dp.validate(plan)
    contract = _projection(plan)
    data = {role: _bound_json(plan["comparison"][role], base_dir) for role in ("baseline", "candidate")}
    contract["expected_exposure"] = {role: data[role]["expected_exposure"] for role in data}
    contract["original_census"] = deepcopy(original_census)
    contract["expected_scales"] = {role: data[role]["scale"] for role in data} if plan["comparison"]["kind"] == "paired_events" else None
    if contract["comparison"]["kind"] == "paired_events":
        if original_census is None:
            raise ValueError("paired constructive contract needs an actual original_event_census")
        event_contrasts.validate_census(_bound_json(original_census, base_dir))
    return _validate_contract(contract)


def input_pins(request):
    """Embedded source inputs that a graph host must bind explicitly."""
    pins = [request[key] for key in ("baseline", "compound_candidate", "license")]
    contract = request.get("evaluation_contract")
    if contract is not None:
        pins += contract["fixed_artifacts"]
        if contract["original_census"] is not None:
            pins.append(contract["original_census"])
        if contract["capacity"] is not None:
            pins.append(contract["capacity"]["artifact"])
    return deepcopy(pins)


def evaluation_pins(plan):
    plan = dp.validate(plan)
    pins = [*plan["fixed_artifacts"], plan["comparison"]["baseline"], plan["comparison"]["candidate"],
            *[u["artifact"] for u in plan["data_use"]]]
    rel = plan["comparison"].get("uncertainty_relationship", {})
    if "artifact" in rel:
        pins.append(rel["artifact"])
    if plan["capacity"] is not None:
        pins.append(plan["capacity"]["artifact"])
    return deepcopy(pins)


def _diff(before, after):
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="controlled_baseline", tofile="observed_candidate"))


def prepare(request, base_dir="."):
    request = _bounded_json(request)
    dp.keys(request, {"schema_version", "finding", "baseline", "compound_candidate", "license", "component",
                      "control_probes", "rivals", "next_actions", "evaluation_contract"}, "constructive request")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("unsupported constructive request")
    dp.keys(request["finding"], {"id", "claim", "objection"}, "critic finding")
    for key, value in request["finding"].items():
        _bounded_text(value, key)
    component = request["component"]
    dp.keys(component, {"id", "before", "after"}, "component")
    _bounded_text(component["id"], "component id")
    for key in ("before", "after"):
        _bounded_text(component[key], key, MAX_COMPONENT_BYTES)
    baseline = _read(request["baseline"], base_dir)
    compound = _read(request["compound_candidate"], base_dir)
    license_text = _read(request["license"], base_dir, maximum=64 * 1024)
    if component["before"] == component["after"] or baseline.count(component["before"]) != 1:
        raise ValueError("component requires exactly one distinct literal match in baseline")
    controlled = baseline.replace(component["before"], component["after"], 1)
    if len(controlled.encode()) > MAX_SOURCE_BYTES:
        raise ValueError("controlled alternative exceeds source bound")
    probes = request["control_probes"]
    if type(probes) is not list or len(probes) > 16:
        raise ValueError("control probes exceed bound")
    observations, labels = [], set()
    for probe in probes:
        dp.keys(probe, {"label", "baseline_literal", "compound_literal", "interpretation"}, "control probe")
        for key, value in probe.items():
            _bounded_text(value, key)
        if probe["label"] in labels:
            raise ValueError("duplicate control label")
        labels.add(probe["label"])
        counts = {"baseline": baseline.count(probe["baseline_literal"]), "compound": compound.count(probe["compound_literal"]),
                  "controlled_baseline_literal": controlled.count(probe["baseline_literal"])}
        observations.append({**probe, "literal_counts": counts, "verified_literal_observation": all(n > 0 for n in counts.values()),
                             "different_supplied_literals": probe["baseline_literal"] != probe["compound_literal"],
                             "causal_effect_measured": False})
    contract = request["evaluation_contract"]
    if contract is not None:
        contract = _validate_contract(contract)
        for pin in input_pins(request)[3:]:
            dp.bound_file(pin, base_dir)
        if contract["original_census"] is not None:
            census = event_contrasts.validate_census(_bound_json(contract["original_census"], base_dir))
            if any(n != len(census["records"]) for n in contract["expected_exposure"].values()):
                raise ValueError("prospective exposure must equal the complete original census")
        criterion_ids = {h["id"] for h in contract["hypotheses"]}
    else:
        criterion_ids = None
    rivals = request["rivals"]
    if type(rivals) is not list or not 2 <= len(rivals) <= 8:
        raise ValueError("two to eight competing explanations required")
    ids, signatures = set(), set()
    for rival in rivals:
        dp.keys(rival, {"id", "statement", "predictions"}, "rival")
        _bounded_text(rival["id"], "rival id"); _bounded_text(rival["statement"], "rival statement")
        if rival["id"] in ids:
            raise ValueError("duplicate rival id")
        ids.add(rival["id"])
        predictions = rival["predictions"]
        if type(predictions) is not dict or not 1 <= len(predictions) <= 16:
            raise ValueError("bounded criterion prediction table required")
        if criterion_ids is None:
            criterion_ids = set(predictions)
        if set(predictions) != criterion_ids:
            raise ValueError("every rival must predict the same declared diagnostic criteria")
        for key, values in predictions.items():
            _bounded_text(key, "predicted criterion")
            if type(values) is not list or not 1 <= len(values) <= 2 or len(set(values)) != len(values) or any(x not in ("supported", "contradicted") for x in values):
                raise ValueError("predictions require resolved supported/contradicted status sets; unresolved evidence retains all rivals")
        signatures.add(tuple((key, tuple(sorted(values))) for key, values in sorted(predictions.items())))
    dp.keys(request["next_actions"], set(STATUSES), "prospective next actions")
    for status, action in request["next_actions"].items():
        dp.keys(action, {"action", "reason"}, "next action")
        if action["action"] not in ACTIONS:
            raise ValueError("next action cannot authorize execution or promotion")
        _bounded_text(action["reason"], "next-action reason")
    if request["next_actions"]["unresolved"]["action"] != "request_evidence":
        raise ValueError("unresolved evidence must request evidence")
    # Recheck the originals after preparation; returned source still is not a receipt.
    for key in ("baseline", "compound_candidate", "license"):
        _read(request[key], base_dir)
    return {"schema_version": 1, "kind": "constructive_contrast_preparation", "request": request, "request_sha256": digest(request),
            "controlled_source": controlled, "controlled_source_sha256": hashlib.sha256(controlled.encode()).hexdigest(),
            "license_text": license_text, "component_diff": _diff(baseline, controlled),
            "concomitant_diff": _diff(controlled, compound), "control_observations": observations,
            "rivals": deepcopy(rivals), "discriminating_predictions": len(signatures) > 1,
            "evaluation_contract_sha256": digest(contract) if contract is not None else None,
            "readiness": "prospective_contract_supplied" if contract is not None else "needs_evaluation_contract",
            "review_required": True, "execution_authorized": False, "physics_validated": False,
            "limitations": ["Literal edits and caller-designated probes do not establish semantic or causal equivalence.",
                            "All concomitant source changes remain visible; probe interpretations are supplied judgments.",
                            "Runtime source consumption and scientific applicability require separate evidence."]}


def _fresh(preparation, base_dir):
    if type(preparation) is not dict or preparation.get("kind") != "constructive_contrast_preparation":
        raise ValueError("constructive preparation required")
    refreshed = prepare(preparation["request"], base_dir)
    if refreshed != preparation:
        raise ValueError("preparation changed; make a new prospective preparation")
    return refreshed


def materialize(preparation, outdir, base_dir="."):
    """Write a reviewable private alternative, preserving license and originals."""
    prep = _fresh(preparation, base_dir)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=False)
    (out / "controlled-source.txt").write_text(prep["controlled_source"], encoding="utf-8")
    (out / "LICENSE").write_text(prep["license_text"], encoding="utf-8")
    (out / "MODIFICATIONS.md").write_text("Private derivative: apply only the explicitly declared component replacement. Source consumption and scientific effect are unverified.\n" + prep["component_diff"], encoding="utf-8")
    (out / "preparation.json").write_text(json.dumps(prep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"source_path": str((out / "controlled-source.txt").resolve()), "source_sha256": prep["controlled_source_sha256"], "executed": False}


def apply_results(preparation, completed_plan=None, base_dir="."):
    """Evaluate actual supplied evidence, then apply the frozen prediction table.

    Only measurement/covariance artifact pins may arrive after preparation. All
    scientific choices, roles, population identities and budgets must match.
    No supplied result label is trusted in place of the diagnostic calculation.
    """
    prep = _fresh(preparation, base_dir)
    contract = prep["request"]["evaluation_contract"]
    unresolved = {"action": "request_evidence", "reason": "Supply the prospective evaluation contract and its actual measured evidence; no criterion or threshold is inferred."}
    if contract is None or completed_plan is None:
        return {"kind": "constructive_contrast_application", "status": "unresolved", "diagnostic": None,
                "surviving_rivals": [r["id"] for r in prep["rivals"]], "next_action": unresolved,
                "review_required": True, "execution_authorized": False, "physics_validated": False}
    scientific_projection = {key: value for key, value in contract.items() if key not in ("expected_exposure", "expected_scales", "original_census")}
    if _projection(completed_plan) != scientific_projection:
        raise ValueError("completed diagnostic changed the prospective scientific contract")
    result = dp.evaluate(completed_plan, base_dir)
    _fresh(preparation, base_dir)
    # A contradicted integrity check is a broken experiment, not a scientific objection resolved.
    integrity_failure = any(c["status"] == "contradicted" for c in result["integrity_checks"])
    observed = {row["id"]: row["status"] for row in result["criterion_outcomes"]}
    incomplete = set(observed) != {h["id"] for h in contract["hypotheses"]}
    application_errors = []
    if not integrity_failure and not incomplete:
        try:
            census_map = None
            if contract["original_census"] is not None:
                census = event_contrasts.validate_census(_bound_json(contract["original_census"], base_dir))
                census_map = {r["event_id"]: r["group_id"] for r in census["records"]}
            for role in ("baseline", "candidate"):
                data = _bound_json(completed_plan["comparison"][role], base_dir)
                if data["expected_exposure"] != contract["expected_exposure"][role]:
                    application_errors.append(role + " expected exposure differs from prospective count")
                if census_map is not None:
                    if data["scale"] != contract["expected_scales"][role]:
                        application_errors.append(role + " numeric normalization scale changed")
                    if {r["event_id"]: r["group_id"] for r in data["records"]} != census_map:
                        application_errors.append(role + " IDs/groups do not match the complete original census")
        except (OSError, ValueError, KeyError, TypeError):
            application_errors.append("prospective exposure/census/normalization evidence could not be verified")
    if integrity_failure or incomplete or application_errors:
        status = "unresolved"
        survivors = [r["id"] for r in prep["rivals"]]
        next_action = {"action": "request_evidence", "reason": "Diagnostic integrity, prospective exposure/normalization/census or complete criterion evidence failed; retain adverse receipts and repair the evidence before scientific interpretation."}
    else:
        status = result["status"]
        survivors = [r["id"] for r in prep["rivals"] if all(value == "unresolved" or value in r["predictions"][key] for key, value in observed.items())]
        next_action = deepcopy(prep["request"]["next_actions"][status])
        if not survivors and status != "unresolved":
            next_action = {"action": "revise_hypothesis", "reason": "No declared rival predicts these resolved criteria; preserve the result and revise the explanations rather than asserting an undeclared winner."}
        elif not prep["discriminating_predictions"] and status != "unresolved":
            next_action = {"action": "revise_hypothesis", "reason": "The supplied rivals make identical predictions; retain the measurement and propose a distinguishing intervention within the remaining envelope."}
    return {"kind": "constructive_contrast_application", "preparation_sha256": digest(prep), "completed_plan_sha256": digest(dp.validate(completed_plan)),
            "status": status, "diagnostic": result, "application_evidence_errors": application_errors, "observed_criteria": observed, "surviving_rivals": survivors,
            "next_action": next_action, "review_required": True, "execution_authorized": False, "physics_validated": False,
            "limitations": ["Compatibility with supplied predictions is not causal proof or exhaustive explanation.",
                            "A proposed challenger still needs the existing fresh full-case review and execution authorization."]}
