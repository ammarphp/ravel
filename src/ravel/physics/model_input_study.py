"""Supervised static model-input diagnosis, separate from execution policy.

The adapter delivers source-pinned findings even for a card refused by the
strict inventory contract. Successful diagnostic delivery never means the card
is physically valid, supported by a downstream consumer, or approved to run.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.physics import model_inputs, model_kinematics
from ravel.workflow.state_io import atomic_json, _unique

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CENSUS_HEADERS = 2048
REVIEW_SCOPE = "Source syntax, declaration ambiguity and supplied-card arithmetic only; no model, spectrum, decay or generator validation."


def validate(task):
    """Validate an immutable source card and completeness-file task shape."""
    required = {"slha_file", "source_sha256", "completeness_file"}
    if type(task) is not dict or not required <= set(task) or set(task) - required - {"kinematics_file"}:
        raise ValueError("model-inputs task requires slha_file, source_sha256, completeness_file and optional kinematics_file")
    for key in ("slha_file", "completeness_file", *(["kinematics_file"] if "kinematics_file" in task else [])):
        value = task[key]
        if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 4096:
            raise ValueError(key + " requires a bounded nonempty trimmed file path")
    model_inputs._pinned_hash(task["source_sha256"], "task source_sha256")
    return deepcopy(task)


def _regular(name, base):
    path = Path(name).expanduser()
    path = path if path.is_absolute() else Path(base) / path
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("model-input study requires a regular file without symlinks: " + str(path))
    return path.resolve()


def _raw(path, maximum):
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("model-input study input exceeds its declared byte bound: " + str(path))
    return raw


def _manifest(raw):
    def reject(value):
        raise ValueError("nonfinite completeness JSON: " + value)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("completeness file is not strict UTF-8 JSON") from exc


def _read_inputs(task, base):
    validate(task)
    source = _regular(task["slha_file"], base)
    declaration = _regular(task["completeness_file"], base)
    if source == declaration:
        raise ValueError("SLHA and completeness source files must be distinct")
    raw = _raw(source, model_inputs.MAX_BYTES)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != task["source_sha256"]:
        raise ValueError("SLHA source differs from the external task source_sha256")
    declaration_raw = _raw(declaration, MAX_MANIFEST_BYTES)
    manifest = _manifest(declaration_raw)
    # Source/configuration custody defects fail intake, independently of any
    # supported or unsupported data contained in the card being diagnosed.
    model_inputs._validate_completeness_manifest(manifest, digest)
    context, context_pins = None, []
    if "kinematics_file" in task:
        context, context_pins = model_kinematics.read_context(task["kinematics_file"], digest, base)
        if {source, declaration} & {Path(pin["path"]) for pin in context_pins}:
            raise ValueError("kinematic evidence and original study input paths must be distinct")
    return source, declaration, raw, declaration_raw, manifest, context, context_pins


def inputs(task, base):
    """Enumerate every consumed file and validate custody without executing it."""
    source, declaration, _, _, _, _, context_pins = _read_inputs(task, base)
    return sorted([source, declaration, *(Path(pin["path"]) for pin in context_pins)])


def _duplicate_declarations(raw):
    """Inventory DECAY headers only; do not parse/repair a refused card.

The production strict parser remains the only inventory parser. This small
source census merely exposes every repeated source assignment and differing
literal widths instead of reporting only the first refused header.
"""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {"groups": [], "observed_header_count": None, "parsed_header_count": None,
                "malformed_header_count": None, "retained_header_limit": MAX_CENSUS_HEADERS,
                "truncated": False, "source_text_supported": False, "declaration_equivalence_assessed": False}
    parents = defaultdict(list)
    observed = parsed = malformed = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        tokens = line.split("#", 1)[0].split()
        if not tokens or tokens[0].casefold() != "decay":
            continue
        observed += 1
        if len(tokens) != 3:
            malformed += 1
            continue
        try:
            pdg = abs(model_inputs._integer(tokens[1], "DECAY header PDG"))
            width = model_inputs._fraction(tokens[2], "DECAY header width")
        except ValueError:
            malformed += 1
            continue  # The strict parser reports malformed unsupported data.
        parsed += 1
        if parsed > MAX_CENSUS_HEADERS:
            continue
        parents[pdg].append({"source_line": line_number, "declared_pdg_token": tokens[1],
                             "total_width_source_token": tokens[2],
                             "total_width_GeV_exact": model_inputs._rational(width)})
    groups = [{"pdg": pdg, "declarations": headers,
             "conflicting_supplied_widths": len({row["total_width_GeV_exact"] for row in headers}) > 1,
             "interpretation": "Repeated source assignments retained; no first-wins or last-wins choice."}
            for pdg, headers in sorted(parents.items()) if len(headers) > 1]
    return {"groups": groups, "observed_header_count": observed, "parsed_header_count": parsed,
            "malformed_header_count": malformed, "retained_header_limit": MAX_CENSUS_HEADERS,
            "truncated": parsed > MAX_CENSUS_HEADERS, "source_text_supported": True,
            "declaration_equivalence_assessed": False}


def _refusal_class(reason):
    if "negative BR is unsupported" in reason:
        return "unsupported_consumer_semantics"
    if "multiple BLOCK MASS" in reason or "outside bounded parser range" in reason:
        return "adapter_unsupported_scope"
    if "complete channel declaration" in reason:
        return "completeness_declaration_inconsistent"
    if "duplicate DECAY" in reason or "duplicate MASS" in reason or "duplicate decay channel" in reason:
        return "source_declaration_anomaly"
    if "branching fraction" in reason or "known BR sum" in reason or "negative total width" in reason:
        return "source_arithmetic_anomaly"
    return "source_format_or_adapter_scope_anomaly"


def _diagnose(task, source, raw, manifest):
    duplicates = _duplicate_declarations(raw)
    try:
        inventory = model_inputs.audit_slha_bytes(raw, source_name=str(source),
                        expected_sha256=task["source_sha256"], completeness_manifest=manifest)
    except ValueError as exc:
        reason = str(exc)[:2048]
        if "completeness manifest refers to absent DECAY" in reason:
            raise  # Manifest/configuration mismatch is an intake defect.
        return None, "refused", [{"id": "strict-preflight-refusal", "classification": _refusal_class(reason),
                "observation": reason, "physics_conclusion": "unresolved",
                "scope": "Strict static preflight refused this source condition; downstream consumer semantics and physics remain separate."}], duplicates
    findings = []
    unknown = [row["pdg"] for row in inventory["decays"]
               if row["channel_completeness"].startswith("unresolved")]
    if unknown:
        findings.append({"id": "channel-completeness", "classification": "physics_unresolved",
                         "pdgs": unknown, "observation": "Physical channel completeness is not established by the supplied source declarations."})
    missing = inventory["mass_pdgs_without_decay_record"]
    if missing:
        findings.append({"id": "missing-decay-record", "classification": "physics_unresolved", "pdgs": missing,
                         "observation": "MASS entries lack DECAY records; no stability or missing width is inferred."})
    if inventory["decay_pdgs_without_mass_record"]:
        findings.append({"id": "missing-mass-record", "classification": "physics_unresolved",
                         "pdgs": inventory["decay_pdgs_without_mass_record"],
                         "observation": "DECAY entries lack MASS records; model-wide mass coverage is unresolved."})
    signed = [row["pdg"] for row in inventory["masses"] if row["sign_interpretation"] == "preserved_uninterpreted"]
    if signed:
        findings.append({"id": "signed-mass-convention", "classification": "physics_unresolved", "pdgs": signed,
                         "observation": "Negative source mass signs are preserved without a tachyon or threshold judgment."})
    if inventory["opaque_blocks"]:
        findings.append({"id": "opaque-source-blocks", "classification": "adapter_unsupported_scope",
                         "blocks": inventory["opaque_blocks"],
                         "does_not_refuse_static_inventory": True,
                         "observation": "These source blocks have byte custody but no numerical/model audit in this adapter."})
    return inventory, "static_inventory", findings, duplicates


def run(task, base, output):
    """Deliver immutable-source diagnosis; card refusal is a finding, not approval.

``passed`` means the bounded diagnostic delivered its honest source findings.
Custody, configuration and output defects still raise rather than being turned
into model observations. Existing workflow policy owns every subsequent action.
"""
    source, declaration, raw, declaration_raw, manifest, context, context_pins = _read_inputs(task, base)
    inventory, disposition, findings, duplicates = _diagnose(task, source, raw, manifest)
    kinematics = None if context is None else model_kinematics.audit(inventory, context)
    if kinematics is not None:
        for channel in kinematics["channels"]:
            if channel["status"] == "on_shell_necessary_condition_violated":
                findings.append({"id": "conditional-decay-threshold-" + str(channel["source_line"]),
                    "classification": "source_conditional_kinematic_anomaly", "source_line": channel["source_line"],
                    "parent_pdg": channel["parent_pdg"], "daughter_pdgs": channel["daughter_pdgs"],
                    "mass_slack_GeV_exact": channel["mass_slack_GeV_exact"],
                    "physics_conclusion": "Necessary mass condition violated conditional on the pinned mass and on-shell final-state assertions; overall model validity unresolved.",
                    "observation": "Supplied positive width/BR channel has parent mass below summed declared on-shell daughter rest masses."})
        findings.append({"id": "conditional-kinematic-scope", "classification": "physics_unresolved",
                         "status_counts": kinematics.get("status_counts", {}),
                         "observation": "This is a conditional necessary-condition test; unknown masses and inclusive off-shell interpretations remain unresolved or outside scope."})
    out = Path(output).expanduser().absolute()
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("model-input output must not traverse a symlink")
    out = out.resolve()
    if any(path.is_relative_to(out) for path in [source, declaration, *(Path(pin["path"]) for pin in context_pins)]):
        raise ValueError("model-input outputs must not contain or overwrite supplied input files")
    # The source originals are re-read before publishing a result. The outer
    # supervisor independently provides complete stage input/output custody.
    if _raw(source, model_inputs.MAX_BYTES) != raw or _raw(declaration, MAX_MANIFEST_BYTES) != declaration_raw:
        raise ValueError("model-input source changed during static diagnosis")
    model_kinematics.verify_pins(context_pins)
    source_pins = [{"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                   for path, data in ((source, raw), (declaration, declaration_raw))] + context_pins
    details = {"checks_passed": True, "diagnostic_delivery_complete": True,
               "preflight_disposition": disposition, "static_preflight_supported": inventory is not None,
               "inventory": inventory, "findings": findings, "duplicate_decay_declarations": duplicates,
               "conditional_kinematics": kinematics,
               "source_pins": source_pins, "source_bytes_unchanged": True,
               "postcondition_scope": "Diagnostic source custody and honest findings delivery, not card or physical model acceptance."}
    result = {"schema_version": 1, "kind": "model_input_study", "status": "passed",
              "status_scope": "Source-pinned static diagnosis completed; source refusal findings remain unresolved.",
              "scope": REVIEW_SCOPE, "physics_validated": False, "execution_authorized": False,
              "preflight_disposition": disposition, "details": details,
              "review_scope": REVIEW_SCOPE if context is None else REVIEW_SCOPE + " Optional conditional on-shell rest-mass necessary conditions use explicit source-bound mass and channel assertions.",
              "review_obligations": ["Assess source assignments and consumer-specific unsupported conditions without silently repairing originals.",
                 "Treat completeness declarations and implied Gamma*BR widths as supplied bookkeeping, not independent physical calculations.",
                 "Physical model, spectrum, decay, production, detector and downstream applicability require separate evidence."],
              "downstream_policy": {"execution_authorized": False, "physics_validated": False,
                 "source_findings_do_not_set_workflow_approval": True,
                 "owner": "Existing downstream workflow gates and independent review."},
              "limitations": ["No UFO/Python import, generator, spectrum/decay calculator or model consumer was executed.",
                 "Diagnostic passed status does not mean static preflight support, card validity or scientific acceptance.",
                 "The duplicate census exposes supplied DECAY header widths only; it is not a permissive replacement parser.",
                 "Source anomalies, adapter scope and physics-unresolved findings remain separate from execution policy."]}
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "model-input-findings.json", {"preflight_disposition": disposition,
                "findings": findings, "duplicate_decay_declarations": duplicates, "source_pins": source_pins,
                "physics_validated": False, "execution_authorized": False})
    if inventory is not None:
        atomic_json(out / "model-input-inventory.json", inventory)
    if kinematics is not None:
        atomic_json(out / "model-input-kinematics.json", kinematics)
    return result
