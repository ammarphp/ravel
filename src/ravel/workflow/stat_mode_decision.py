#!/usr/bin/env python3
"""stat_mode_decision -- the coded statistical-mode ladder and its decision record.

After data acquisition the run chooses its statistical model from what the analysis actually
published, strongest first:

  1. published-likelihood    the published workspace, when its appropriateness record says
                             ``appropriate`` or ``appropriate-with-cautions``
  2. simplified-likelihood   a published covariance with a recorded source
  3. constructed-likelihood  published per-region yields plus a declared systematics registry
  4. best-sr-counting        published per-region yields; ``combined-counting`` instead only
                             when the regions are recorded mutually exclusive

The first rung whose evidence suffices is selected. Every rung above it becomes a downgrade
row and the delivery carries the label "Statistical model downgraded: <from> -> <to> because
<reason>; ...". With no sufficient rung the record is ``unresolved`` and no limit may be
delivered. The record lives at ``inputs/stat_mode_decision.json`` (``RECORD``); the run-state
gate and the result pack read it from there.

CLI:
  python -m ravel.workflow.stat_mode_decision --rundir R --evidence evidence.json --write [--force]
  python -m ravel.workflow.stat_mode_decision --rundir R --check
Exit codes: 0 ok * 1 refused, invalid or mismatched * 2 usage or unreadable input
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import copy
import hashlib
import json
import os
import re
import sys

from ravel.validation.validate_task_contract import STAT_MODES as CONTRACT_STAT_MODES

SCHEMA_VERSION = 1
KIND = "stat-mode-decision"
RECORD = "inputs/stat_mode_decision.json"
LADDER = ("published-likelihood", "simplified-likelihood", "constructed-likelihood", "best-sr-counting")
COUNTING_ALTERNATIVE = "combined-counting"
ROW_STATUSES = ("selected", "rejected", "unavailable", "not-reached")
APPROPRIATENESS_VERDICTS = ("appropriate", "appropriate-with-cautions", "inappropriate")
ACCEPTED_VERDICTS = ("appropriate", "appropriate-with-cautions")
BEST_SR_STATEMENT = ("background correlations between regions not published; constraints assumed "
                     "independent; limit quoted from the single most sensitive region")
COMBINED_STATEMENT = ("regions recorded mutually exclusive; their counting constraints are combined "
                      "as independent terms; background correlations between regions not published")

_EVIDENCE_KEYS = ("published_likelihood", "covariance", "systematics_registry", "yields",
                  "mutually_exclusive_regions")
_COMPONENT_KEYS = {
    "published_likelihood": ("available", "path", "appropriateness"),
    "covariance": ("available", "path", "source"),
    "systematics_registry": ("available", "path"),
    "yields": ("available", "path"),
}
_RECORD_KEYS = ("schema_version", "kind", "status", "selected", "ladder", "downgrades", "label",
                "correlations_statement", "evidence")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


# --------------------------------------------------------------------------- evidence

def evidence_errors(evidence):
    """Strict schema errors of a decision's evidence ([] when valid). Unknown keys are refused."""
    if not isinstance(evidence, dict):
        return ["evidence must be an object"]
    errors = []
    unknown, absent = set(evidence) - set(_EVIDENCE_KEYS), set(_EVIDENCE_KEYS) - set(evidence)
    if unknown:
        errors.append(f"evidence has unknown keys {sorted(unknown)}")
    if absent:
        errors.append(f"evidence lacks keys {sorted(absent)}")
    for name, keys in _COMPONENT_KEYS.items():
        part = evidence.get(name)
        if name not in evidence:
            continue
        if not isinstance(part, dict):
            errors.append(f"{name} must be an object")
            continue
        extra, missing = set(part) - set(keys), set(keys) - set(part)
        if extra:
            errors.append(f"{name} has unknown keys {sorted(extra)}")
        if missing:
            errors.append(f"{name} lacks keys {sorted(missing)}")
            continue
        if type(part["available"]) is not bool:
            errors.append(f"{name}.available must be a boolean")
        if part["path"] is not None and not isinstance(part["path"], str):
            errors.append(f"{name}.path must be a string or null")
        if part["available"] is True and not _text(part["path"]):
            errors.append(f"{name}.path is required when {name} is available")
        if name == "covariance" and part["source"] is not None and not isinstance(part["source"], str):
            errors.append("covariance.source must be a string or null")
        if name == "published_likelihood" and part["appropriateness"] is not None:
            errors += _appropriateness_errors(part["appropriateness"])
    exclusive = evidence.get("mutually_exclusive_regions")
    if "mutually_exclusive_regions" in evidence and exclusive is not None and type(exclusive) is not bool:
        errors.append("mutually_exclusive_regions must be a boolean or null")
    return errors


def _appropriateness_errors(value):
    if not isinstance(value, dict):
        return ["published_likelihood.appropriateness must be an object or null"]
    errors = []
    extra = set(value) - {"path", "verdict", "blocking_codes"}
    if extra:
        errors.append(f"published_likelihood.appropriateness has unknown keys {sorted(extra)}")
    if not _text(value.get("path")):
        errors.append("published_likelihood.appropriateness.path is required")
    if value.get("verdict") not in APPROPRIATENESS_VERDICTS:
        errors.append(f"published_likelihood.appropriateness.verdict must be one of {APPROPRIATENESS_VERDICTS}")
    codes = value.get("blocking_codes")
    if codes is not None and not (isinstance(codes, list) and all(_text(c) for c in codes)):
        errors.append("published_likelihood.appropriateness.blocking_codes must be a list of codes")
    if value.get("verdict") == "inappropriate" and not codes:
        errors.append("an inappropriate verdict must carry its blocking_codes")
    return errors


# --------------------------------------------------------------------------- the ladder

def _published(part):
    if not part["available"]:
        return "unavailable", "no published likelihood recorded"
    review = part["appropriateness"]
    if review is None:
        return "rejected", "appropriateness not assessed"
    if review["verdict"] == "inappropriate":
        return "rejected", "appropriateness verdict inappropriate: " + ", ".join(sorted(review["blocking_codes"]))
    return "selected", f"published likelihood with appropriateness verdict {review['verdict']}"


def _simplified(part):
    if not part["available"]:
        return "unavailable", "no published covariance recorded"
    if not _text(part["source"]):
        return "rejected", "covariance source not recorded"
    return "selected", f"published covariance from {part['source'].strip()}"


def _constructed(yields, registry):
    if not yields["available"] and not registry["available"]:
        return "unavailable", "no published yields and no declared systematics registry"
    if not yields["available"]:
        return "unavailable", "no published per-region yields"
    if not registry["available"]:
        return "unavailable", "no declared systematics registry"
    return "selected", "published yields with a declared systematics registry"


def _counting(yields, exclusive):
    if not yields["available"]:
        return LADDER[3], "unavailable", "no published per-region yields"
    if exclusive is True:
        return COUNTING_ALTERNATIVE, "selected", "published per-region yields; regions recorded mutually exclusive"
    return LADDER[3], "selected", "published per-region yields; single most sensitive region"


def decide(evidence):
    """The decision record for one run's evidence. Raises ValueError on invalid evidence."""
    errors = evidence_errors(evidence)
    if errors:
        raise ValueError("invalid stat-mode evidence: " + "; ".join(errors))
    counting_mode, counting_status, counting_reason = _counting(evidence["yields"],
                                                                evidence["mutually_exclusive_regions"])
    outcomes = [
        (LADDER[0],) + _published(evidence["published_likelihood"]),
        (LADDER[1],) + _simplified(evidence["covariance"]),
        (LADDER[2],) + _constructed(evidence["yields"], evidence["systematics_registry"]),
        (counting_mode, counting_status, counting_reason),
    ]
    rung_evidence = [
        {"published_likelihood": evidence["published_likelihood"]},
        {"covariance": evidence["covariance"]},
        {"yields": evidence["yields"], "systematics_registry": evidence["systematics_registry"]},
        {"yields": evidence["yields"], "mutually_exclusive_regions": evidence["mutually_exclusive_regions"]},
    ]
    ladder, selected = [], None
    for (mode, status, reason), facts in zip(outcomes, rung_evidence):
        if selected is not None:
            status, reason = "not-reached", f"a stronger rung ({selected}) was selected"
        elif status == "selected":
            selected = mode
        ladder.append({"stat_mode": mode, "status": status, "reason": reason,
                       "evidence": copy.deepcopy(facts)})
    downgrades = []
    if selected is not None:
        for row in ladder:
            if row["status"] == "selected":
                break
            downgrades.append({"from": row["stat_mode"], "to": selected, "reason": row["reason"]})
    label = None
    if downgrades:
        label = "Statistical model downgraded: " + "; ".join(
            f"{d['from']} → {d['to']} because {d['reason']}" for d in downgrades)
    statement = {LADDER[3]: BEST_SR_STATEMENT, COUNTING_ALTERNATIVE: COMBINED_STATEMENT}.get(selected)
    return {"schema_version": SCHEMA_VERSION, "kind": KIND,
            "status": "resolved" if selected else "unresolved", "selected": selected,
            "ladder": ladder, "downgrades": downgrades, "label": label,
            "correlations_statement": statement, "evidence": copy.deepcopy(evidence)}


def validate_record(record):
    """Errors of a decision record ([] when valid): its shape, and agreement with decide(evidence)."""
    if not isinstance(record, dict):
        return ["record must be an object"]
    errors = []
    unknown = set(record) - set(_RECORD_KEYS) - {"supersedes"}
    absent = set(_RECORD_KEYS) - set(record)
    if unknown:
        errors.append(f"record has unknown keys {sorted(unknown)}")
    if absent:
        return errors + [f"record lacks keys {sorted(absent)}"]
    if record["kind"] != KIND or record["schema_version"] != SCHEMA_VERSION:
        errors.append(f"record must be kind {KIND!r} schema_version {SCHEMA_VERSION}")
    if record["selected"] is not None and record["selected"] not in CONTRACT_STAT_MODES:
        errors.append(f"selected {record['selected']!r} is not a task-contract stat_mode")
    if record["status"] not in ("resolved", "unresolved") \
            or (record["status"] == "resolved") != (record["selected"] is not None):
        errors.append("status must be resolved exactly when a stat_mode is selected")
    if "supersedes" in record:
        prior = record["supersedes"]
        if not (isinstance(prior, dict) and set(prior) == {"sha256"} and isinstance(prior["sha256"], str)
                and _SHA256.match(prior["sha256"])):
            errors.append("supersedes must be {sha256: <hex digest of the previous record>}")
    rows = record["ladder"]
    if not isinstance(rows, list) or len(rows) != len(LADDER) or not all(
            isinstance(r, dict) and r.get("status") in ROW_STATUSES and _text(r.get("reason")) for r in rows):
        errors.append("ladder must hold one row per rung with a status and a reason")
    try:
        expected = decide(record["evidence"])
    except ValueError as exc:
        return errors + [str(exc)]
    for key in ("status", "selected", "ladder", "downgrades", "label", "correlations_statement"):
        if record[key] != expected[key]:
            errors.append(f"{key} does not follow from the recorded evidence")
    return errors


# --------------------------------------------------------------------------- CLI

def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _resolve(rundir, path):
    return path if os.path.isabs(path) else os.path.join(rundir, path)


def evidence_file_errors(rundir, evidence):
    """Recorded evidence must name existing files; an appropriateness record must say what it claims."""
    errors = []
    for name in _COMPONENT_KEYS:
        part = evidence[name]
        if part["available"] and not os.path.isfile(_resolve(rundir, part["path"])):
            errors.append(f"{name}.path {part['path']!r} is not a file")
    review = evidence["published_likelihood"]["appropriateness"]
    if review is not None:
        from ravel.validation.likelihood_appropriateness import blocking_codes, validate_record as check
        path = _resolve(rundir, review["path"])
        try:
            with open(path) as fh:
                document = json.load(fh)
        except (OSError, ValueError) as exc:
            return errors + [f"appropriateness record {review['path']!r} unreadable: {exc}"]
        problems = check(document)
        if problems:
            errors.append(f"appropriateness record {review['path']!r} invalid: " + "; ".join(problems))
        elif document["verdict"] != review["verdict"]:
            errors.append(f"appropriateness record verdict {document['verdict']!r} differs from the "
                          f"evidence verdict {review['verdict']!r}")
        elif review["verdict"] == "inappropriate" and sorted(set(review["blocking_codes"])) != blocking_codes(document):
            errors.append("evidence blocking_codes differ from the appropriateness record's blocking findings")
    return errors


def _write(rundir, record, force):
    path = os.path.join(rundir, RECORD)
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            raw = fh.read()
        try:
            previous = json.loads(raw)
        except ValueError:
            previous = None
        same = isinstance(previous, dict) and {k: v for k, v in previous.items() if k != "supersedes"} == record
        if same:
            print(f"stat-mode decision unchanged: {RECORD}")
            return 0
        if not force:
            print(f"refused: {RECORD} holds a different decision; pass --force to supersede it",
                  file=sys.stderr)
            return 1
        record = dict(record, supersedes={"sha256": hashlib.sha256(raw).hexdigest()})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(record, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    print(f"stat-mode decision: {record['status']} selected={record['selected']} -> {RECORD}")
    if record["label"]:
        print(record["label"])
    return 0


def _check(rundir):
    path = os.path.join(rundir, RECORD)
    try:
        with open(path) as fh:
            record = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"stat-mode decision unreadable ({RECORD}): {exc}", file=sys.stderr)
        return 1
    try:
        with open(os.path.join(rundir, "inputs", "task_contract.json")) as fh:
            contract = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"task contract unreadable: {exc}", file=sys.stderr)
        return 2
    errors = validate_record(record)
    declared = contract.get("stat_mode") if isinstance(contract, dict) else None
    if not errors and record["status"] != "resolved":
        errors.append("the decision is unresolved: no statistical model is available and no limit may be delivered")
    elif not errors and record["selected"] != declared:
        errors.append(f"selected {record['selected']!r} differs from the contract stat_mode {declared!r}")
    for error in errors:
        print(f"stat-mode decision: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"stat-mode decision consistent: selected={record['selected']}"
          + (f"; {len(record['downgrades'])} downgrade(s)" if record["downgrades"] else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir", required=True, help="the run directory")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help=f"decide from --evidence and write {RECORD}")
    mode.add_argument("--check", action="store_true", help="validate the record against the task contract")
    ap.add_argument("--evidence", help="evidence JSON (required with --write)")
    ap.add_argument("--force", action="store_true", help="supersede a different existing record")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    rundir = args.rundir
    if not os.path.isdir(rundir):
        print(f"not a directory: {rundir}", file=sys.stderr)
        return 2
    if args.check:
        return _check(rundir)
    if not args.evidence:
        print("--write requires --evidence", file=sys.stderr)
        return 2
    try:
        with open(args.evidence) as fh:
            evidence = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"evidence unreadable: {exc}", file=sys.stderr)
        return 2
    try:
        record = decide(evidence)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors = evidence_file_errors(rundir, evidence)
    if errors:
        for error in errors:
            print(f"refused: {error}", file=sys.stderr)
        return 1
    return _write(rundir, record, args.force)


if __name__ == "__main__":
    sys.exit(main())
