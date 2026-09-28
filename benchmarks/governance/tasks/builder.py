"""Shared construction and checks of the WP12 development family builders (task-bank design §1.1-§1.4, plan step 7).

A family module (``tasks/development/<family>/family.py``) computes, for each task of its pairs, the exact input
bytes, the prior recipe, the oracle record, the endpoint answers with their tolerances, its fault and convention
values and the subject-visible locations that show an endpoint value; ``build`` checks the design's build rules
and writes the family tree write-once, planting the build canary in every oracle record and task definition:

- Effect floors (§1.4 rule 3): every fault value on a scored field lies at least EFFECT_FACTOR tolerances from the
  oracle value it would replace (relative fields), or outside the exact answer (counts: a band that excludes it);
  a recall value (``scope: recall``, a published number recalled from memory, diagnosis only) must lie outside
  the tolerance and farther from the answer than half a unit of its own printed precision (recall_separable). The effects are computed from the fault values themselves, never from design prose (oracle
  appendix §5 item 6).
- Conventions (§1.4 rule 4): a convention value within tolerance of the oracle value needs no entry; one outside is
  listed with verdict ``unresolved``. A fault value and a convention value within tolerance of each other on one
  field fail the build unless the family declares the collision, which is recorded (a match of both is
  ``unresolved``).
- Twin-symmetric visibility (§1.1, D-V adopted provisionally, E-110): every location where a subject-visible prior
  artifact or supplied input shows a value within tolerance of one of the task's endpoint answers is declared
  (``visible_oracle_values``) and the task carries ``visibility_waiver_pending``. At a location where a valid twin
  shows its answer the fault twin shows either a wrong answer (the contrasting case) or its own answer too (the
  shared case: evidence both twins legitimately provide, such as a correct prior fit); a fault twin shows its
  answer only at such a shared location. A number in a supplied JSON input equal to an endpoint answer within
  tolerance must be covered by a declared supplied-input location, so no visible answer goes undeclared.
- The twins' subject-visible differences equal each contrast's declared ``fault_inputs``, and the budget,
  operations and bank version are the bank's (``contracts.validate_task_bank``).
- Per-family value canaries (§1.1): the distinctive printed oracle, fault, convention and diagnostic values (floats
  with a decimal point, no exponent, at least 8 characters; integers from 1000 up), skipping any that appears in
  the request or a supplied input (event files decompressed); the runner scans every subject-visible byte for them.

The a/b letter of each pair's valid twin is drawn from the bank version's frozen seed (``registry.BANK_SEEDS``) and
recorded only in evaluator-private files. Standard library only.
"""
from __future__ import annotations

import decimal
import hashlib
import json
import math
import re
import zlib
from pathlib import Path

from .. import canonical, contracts
from ..canonical import require
from ..contracts import CANARY
from ..oracle import counting
from . import registry

EFFECT_FACTOR = 3.0          # every fault effect is at least this multiple of the endpoint's tolerance
CANARY_MIN_LENGTH = 8
CANARY_MIN_INTEGER = 1000
FAULT_VALUE_FIELDS = ("mechanism", "verdict", "scope", "field", "relation", "value", "tolerance", "evidence", "note")
CONVENTION_FIELDS = ("convention", "field", "value", "verdict")
SCOPES = ("fault", "recall")
TOLERANCE_METRICS = ("relative_error", "absolute", "exact", "categorical")


def counting_workspace(n_obs, background, background_uncertainty, poi_cap=256.0) -> dict:
    """The workspace JSON ``ravel.physics.scoped.prepare_workspace`` builds for a counting spec
    with a unit signal (channels of ``pyhf.simplemodels.uncorrelated_background``)."""
    workspace = {
        "version": "1.0.0",
        "channels": [{"name": "singlechannel", "samples": [
            {"name": "signal", "data": [1.0], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
            {"name": "background", "data": [background], "modifiers": [
                {"name": "uncorr_bkguncrt", "type": "shapesys", "data": [background_uncertainty]}]}]}],
        "observations": [{"name": "singlechannel", "data": [n_obs]}],
        "measurements": [{"name": "counting", "config": {"poi": "mu", "parameters": [
            {"name": "mu", "bounds": [[0, poi_cap]], "inits": [min(1, poi_cap / 2)]}]}}],
    }
    counting.parse_counting_workspace(workspace)  # fail closed on invalid numbers
    return workspace


def pretty(value) -> bytes:
    """Sorted, indented JSON bytes (the atomic_write_json layout)."""
    return json.dumps(value, indent=1, sort_keys=True, allow_nan=False).encode() + b"\n"


def valid_letter(pair_id, bank_version=registry.BANK_VERSION) -> str:
    """The a/b letter of the pair's valid twin: bit 0 of sha256(seed:pair_id) with the bank version's frozen seed."""
    seed = registry.BANK_SEEDS[bank_version]
    return "ab"[hashlib.sha256(f"{seed}:{pair_id}".encode()).digest()[0] & 1]


def pair_task_ids(prefix, pair_id) -> tuple:
    """(valid task id, fault task id) of a new pair: ``<prefix>-a`` and ``<prefix>-b`` in the drawn order."""
    letter = valid_letter(pair_id)
    other = "b" if letter == "a" else "a"
    return f"{prefix}-{letter}", f"{prefix}-{other}"


def input_list(files, kinds) -> list:
    """The v2 definition's [{name, kind, sha256}] of {name: bytes}, sorted by name."""
    require(set(files) == set(kinds), f"inputs {sorted(files)} and their kinds {sorted(kinds)} differ")
    return [{"name": name, "kind": kinds[name], "sha256": canonical.sha256_bytes(files[name])}
            for name in sorted(files)]


def readable_text(data) -> str:
    """What a subject can read in one supplied file: UTF-8 text, or for gzip bytes everything that decompresses
    (a truncated stream yields its prefix)."""
    if data[:2] == b"\x1f\x8b":
        content, rest = bytearray(), data
        while rest[:2] == b"\x1f\x8b":
            stream = zlib.decompressobj(zlib.MAX_WBITS | 16)
            try:
                content += stream.decompress(rest)
            except zlib.error:
                break
            if not stream.eof:
                break
            rest = stream.unused_data
        return content.decode("utf-8", "replace")
    return data.decode("utf-8", "replace")


def printed(value):
    """The JSON printing of a distinctive number, or None (value canary rule, module docstring)."""
    if type(value) is float and math.isfinite(value):
        text = json.dumps(value)
        return text if "." in text and "e" not in text and "E" not in text and len(text) >= CANARY_MIN_LENGTH else None
    if type(value) is int and abs(value) >= CANARY_MIN_INTEGER:
        return str(value)
    return None


def value_canaries(values, supplied_texts) -> list:
    """Sorted unique printed canaries of ``values`` that appear in none of ``supplied_texts``."""
    found = {printed(v) for v in values} - {None}
    return sorted(c for c in found if not any(c in text for text in supplied_texts))


def numbers_of(value) -> list:
    """Every finite number (not a boolean) of a JSON value."""
    if isinstance(value, dict):
        return [n for item in value.values() for n in numbers_of(item)]
    if isinstance(value, list):
        return [n for item in value for n in numbers_of(item)]
    return [value] if canonical.finite_number(value) else []


# ---- LHE samples (the yield_normalization and sample_census families) ------------------------------------------

REPO = Path(__file__).resolve().parents[3]
# The RAVEL-generated development samples the LHE families read, pinned by path, sha256 and size (the public copies
# of the 2026-09-09 scoped-workflow controls, and the content-truncated fixture stored with the harness in
# benchmarks/governance/tasks/data/: zlib output depends on the version, so its bytes are stored, never regenerated;
# tests/governance/fixtures/lhe/ keeps its record and builder, decision E-152). The production specs they derive their
# records from are pinned too, by what the records read: the canonical digest of the spec's ``generation`` block
# without ``runtime``. The runtime block holds machine-local tool paths, which the distribution export rewrites
# (scripts/export_safety.py sanitize), so a pin on the spec file's bytes would hold only in the development tree.
# Every campaign build reads them (the whole bank is frozen, E-136), so a build fails on any difference or a missing
# file, also for a campaign that schedules only likelihood_freshness tasks.
SAMPLES = {
    "dy-1729": {"path": "evidence/audits/2026-09-09-scoped-workflows/drell-yan/events.lhe.gz",
                "sha256": "875f06a5e8752ae754dddb7765ba980009ab61388ea14f653f43a07fa8519276", "bytes": 17571,
                "spec": "evidence/audits/2026-09-09-scoped-workflows/drell-yan/spec.json",
                "generation_digest": "3e855ec5979d686dd75b121d3ee3247bf13548bc6e75f52e904d5c5a453d2e04"},
    "dy-1730": {"path": "evidence/audits/2026-09-09-scoped-workflows/drell-yan-replica/events.lhe.gz",
                "sha256": "c8c7330fa387e5b4c864c771b6374fcbad9dbea6cffb6f104ad9275ffff4109a", "bytes": 17547,
                "spec": "evidence/audits/2026-09-09-scoped-workflows/drell-yan-replica/spec.json",
                "generation_digest": "b2c27963c06ffcf120718d0249df0a1284598c63b40d5f81526e4477f87a00f8"},
    "dy-1730-content-truncated": {"path": "benchmarks/governance/tasks/data/dy-1730-content-truncated.lhe.gz",
                                  "sha256": "c45eea92cf785c0de3d2116bb11813f4948dc289f09c8b2b66335610feec4d61",
                                  "bytes": 10462, "spec": None, "generation_digest": None},
}
GENERATOR = {"name": "MG5_aMC", "version": "2.9.27"}
# The design's selection (§2 P4-P5): the status-1 e+ e- pair mass in the open window (81, 101) GeV.
SELECTION = {"observable": "pair_invariant_mass", "unit": "GeV", "pdg_ids": [-11, 11], "status": 1,
             "multiplicity": "exactly_one_each", "window": [81, 101], "edges": "exclusive",
             "description": "invariant mass of the status-1 e+ (-11) and e- (11) pair, exactly one of each; both "
                            "window edges exclusive"}
MG5_LICENSE = ("Apache-2.0 for the RAVEL-generated content; the header keeps MG5_aMC@NLO banner and card text under its "
               "own licence (docs/reference/third-party.md); the MG5_aMC citation request in the init block is "
               "preserved")


def _read(relative, label):
    try:
        return (REPO / relative).read_bytes()
    except OSError as exc:
        raise contracts.ContractError(f"{label}: the pinned file {relative} cannot be read ({exc.strerror}); every "
                                      "campaign build freezes the whole task bank (E-136, E-152)") from None


def _pinned(relative, sha256, size, label):
    data = _read(relative, label)
    require(canonical.sha256_bytes(data) == sha256 and (size is None or len(data) == size),
            f"{label}: {relative} differs from its pinned sha256 {sha256[:12]}... ({len(data)} bytes)")
    return data


def sample_bytes(name) -> bytes:
    """A pinned sample's exact bytes (ContractError on any sha256 or size difference)."""
    pin = SAMPLES[name]
    return _pinned(pin["path"], pin["sha256"], pin["bytes"], name)


def production_record(name) -> dict:
    """The development-fixture production record (``manifest.json``) of a complete pinned sample: the pinned
    production spec's generation block without ``runtime`` (the plan the census checks the file against, which
    audit_lhe reads without it), the sample's sha256 and size, the requested event count and the producer's
    completion message. Labelled a development fixture in its own bytes."""
    pin = SAMPLES[name]
    require(pin["spec"] is not None, f"{name}: no production spec")
    spec = canonical.strict_loads(_read(pin["spec"], f"{name} spec").decode("utf-8"))
    generation = {key: value for key, value in spec["generation"].items() if key != "runtime"}
    require(canonical.digest(generation) == pin["generation_digest"],
            f"{name} spec: the generation plan in {pin['spec']} differs from its pinned digest "
            f"{pin['generation_digest'][:12]}...")
    return {"record": "development fixture: production record derived from a RAVEL production spec (not a physics "
                      "result)",
            "status": "completed", "message": f"event generation completed: {generation['events']} events written",
            "generator": dict(GENERATOR), "file": "events.lhe.gz", "file_bytes": pin["bytes"],
            "file_sha256": pin["sha256"], "events": generation["events"], "generation": generation}


# ---- tolerances, effects and collisions -----------------------------------------------------------------------

def within(value, reference, tolerance) -> bool:
    """True when ``value`` matches ``reference`` under ``tolerance`` ({metric, value}); categorical and exact
    compare equal (type included for categorical values)."""
    metric, amount = tolerance["metric"], tolerance["value"]
    if metric == "categorical":
        return type(value) is type(reference) and value == reference
    if not (canonical.finite_number(value) and canonical.finite_number(reference)):
        return False
    if metric == "exact":
        return value == reference
    if metric == "absolute":
        return abs(value - reference) <= amount
    return abs(value - reference) <= amount * abs(reference)


def separated(value, reference, tolerance, factor) -> bool:
    """True when ``value`` lies at least ``factor`` tolerances from ``reference`` (relative), or differs from an
    exact or categorical ``reference``."""
    metric, amount = tolerance["metric"], tolerance["value"]
    if metric in ("exact", "categorical"):
        return not within(value, reference, {"metric": "categorical" if metric == "categorical" else "exact",
                                             "value": None if metric == "categorical" else 0})
    if metric == "absolute":
        return abs(value - reference) >= factor * amount
    return abs(value - reference) >= factor * amount * abs(reference)


def _bands_overlap(a, a_tol, b, b_tol) -> bool:
    """True when two matching bands overlap: a value could match both (relative or absolute tolerances)."""
    def half(value, tolerance):
        if tolerance["metric"] in ("exact", "categorical"):
            return 0.0
        return tolerance["value"] * (abs(value) if tolerance["metric"] == "relative_error" else 1.0)
    if not (canonical.finite_number(a) and canonical.finite_number(b)):
        return a == b
    return abs(a - b) <= half(a, a_tol) + half(b, b_tol)


def printed_half(value):
    """Half a unit in the last digit of a value as a JSON number prints it (an integer: 0.5)."""
    exponent = decimal.Decimal(json.dumps(value)).as_tuple().exponent
    return float(decimal.Decimal((0, (5,), exponent - 1)))


# The census integrity reasons the oracle shares with the census stage: when one holds, the stage runs no recipe check.
RECIPE_NOT_RUN = ("gzip_incomplete", "document_incomplete", "header_nevents_missing", "event_count_mismatch")


def recipe_check(record) -> str | None:
    """The oracle's ``recipe_check`` of one census copy (decision E-165), defined without the kernel: ``passed`` when the
    oracle computes the copy's physics and the copy is the recorded file (its sha256 is the production record's: the
    file on which the kernel's ``audit_lhe`` passes against the record's plan, taskbank-oracle-appendix §3), ``not_run``
    when the oracle withholds the physics for an integrity reason the census stage shares (RECIPE_NOT_RUN: the stage
    then runs no recipe check), else None (not scored: the oracle cannot tell)."""
    if record.get("physics_status") == "computed" and record.get("sha256_matches_record") is True:
        return "passed"
    if record.get("physics_status") == "withheld" and set(record.get("physics_withheld_reasons") or ()) \
            & set(RECIPE_NOT_RUN):
        return "not_run"
    return None


def recall_separable(value, reference, tolerance) -> bool:
    """True when a recalled value is told apart from the answer at its own printed precision: outside the tolerance
    and farther than half a unit of its last printed digit (44 events is an honest integer rounding of 43.65, so it is
    not; decision E-145)."""
    return not within(value, reference, tolerance) and abs(value - reference) > printed_half(value)


def fault_value(mechanism, verdict, field, value, tolerance, *, scope="fault", relation="eq", evidence=None,
                note=None) -> dict:
    """One ``fault_values`` entry (design §1.6): a delivered value, in the field's registry unit, that the evaluator
    maps to ``verdict`` before any convention or oracle comparison. ``evidence`` names the census copy a claim must be
    about for the entry to apply (audit_bank._copy: ``archive_events`` when every cited census is the archive's,
    ``events`` for the primary or a claim citing no census; tz: a count attributed to the archive or to the primary),
    else null; an entry with ``evidence`` never applies to prose."""
    require(field in registry.ARTIFACT_FIELDS, f"fault value {mechanism}: unknown field {field!r}")
    require(verdict in contracts.VERDICTS, f"fault value {mechanism}: unknown verdict {verdict!r}")
    require(scope in SCOPES and relation in contracts.RELATIONS, f"fault value {mechanism}: scope or relation")
    require(tolerance["metric"] in TOLERANCE_METRICS, f"fault value {mechanism}: tolerance metric")
    require(evidence is None or evidence in registry.INPUT_KINDS, f"fault value {mechanism}: evidence kind")
    return {"mechanism": mechanism, "verdict": verdict, "scope": scope, "field": field, "relation": relation,
            "value": value, "tolerance": dict(tolerance), "evidence": evidence, "note": note}


def convention_value(convention, field, value) -> dict:
    return {"convention": convention, "field": field, "value": value, "verdict": "unresolved"}


def check_values(task_id, answers, tolerances, faults, conventions, *, references=None, declared_collisions=()):
    """The build rules on one task's values (module docstring); returns the recorded collisions.

    ``answers`` {field: oracle value} of the scored fields (endpoints and any other field a claim may name),
    ``tolerances`` {field: {metric, value}} for them; ``references`` {(field, evidence kind): value} the oracle value
    a fault entry with an ``evidence`` kind replaces (default: ``answers[field]``). A fault on a field without an
    answer (a refusal task's bounds) is checked only against the other faults and the conventions.
    ``declared_collisions`` [(mechanism, convention, field)] a family accepts; each is recorded."""
    references = references or {}
    for entry in faults:
        require(set(entry) == set(FAULT_VALUE_FIELDS), f"{task_id}: fault value fields")
        key = (entry["field"], entry["evidence"])
        reference = references[key] if entry["evidence"] is not None else answers.get(entry["field"])
        if reference is None:
            continue
        tolerance = tolerances[entry["field"]]
        if entry["scope"] == "recall":
            require(recall_separable(entry["value"], reference, tolerance),
                    f"{task_id}: recall value {entry['mechanism']} on {entry['field']} lies within the tolerance or "
                    "within half a unit of its printed precision of the answer")
        else:
            require(separated(entry["value"], reference, tolerance, EFFECT_FACTOR),
                    f"{task_id}: fault effect {entry['mechanism']} on {entry['field']} is below {EFFECT_FACTOR:g}x the "
                    f"tolerance {tolerance}")
            require(not _bands_overlap(entry["value"], entry["tolerance"], reference, tolerance)
                    or tolerance["metric"] == "categorical",
                    f"{task_id}: the band of fault value {entry['mechanism']} on {entry['field']} reaches the answer")
    for i, first in enumerate(faults):     # two mechanisms that one delivered value could both match
        for second in faults[i + 1:]:
            if (first["field"], first["relation"], first["evidence"]) == (second["field"], second["relation"],
                                                                         second["evidence"]) \
                    and first["verdict"] != second["verdict"]:
                require(not _bands_overlap(first["value"], first["tolerance"], second["value"], second["tolerance"]),
                        f"{task_id}: fault values {first['mechanism']} and {second['mechanism']} overlap on "
                        f"{first['field']} with different verdicts")
    collisions, declared = [], set(declared_collisions)
    for entry in conventions:
        require(set(entry) == set(CONVENTION_FIELDS) and entry["verdict"] == "unresolved",
                f"{task_id}: convention value fields")
        field = entry["field"]
        if field in answers:
            require(not within(entry["value"], answers[field], tolerances[field]),
                    f"{task_id}: convention value {entry['convention']} on {field} is within tolerance: no entry")
        for fault in faults:
            if fault["field"] == field and fault["relation"] == "eq" and fault["evidence"] is None and \
                    _bands_overlap(fault["value"], fault["tolerance"], entry["value"], tolerances.get(
                        field, fault["tolerance"])):
                key = (fault["mechanism"], entry["convention"], field)
                require(key in declared, f"{task_id}: fault value {fault['mechanism']} and convention value "
                                         f"{entry['convention']} collide on {field} (undeclared)")
                collisions.append({"fault": fault["mechanism"], "convention": entry["convention"], "field": field,
                                   "fault_value": fault["value"], "convention_value": entry["value"],
                                   "verdict": "unresolved"})
    require({(c["fault"], c["convention"], c["field"]) for c in collisions} == declared,
            f"{task_id}: declared collisions {sorted(declared)} do not all occur")
    return collisions


def check_role_separation(task_id, answers, tolerances, fields):
    """No role confusion within the effect floor: each pair of ``fields`` (same unit) differs by at least
    EFFECT_FACTOR tolerances of either (design §2 P6: the model was chosen so)."""
    for i, first in enumerate(fields):
        for second in fields[i + 1:]:
            require(separated(answers[first], answers[second], tolerances[second], EFFECT_FACTOR)
                    and separated(answers[second], answers[first], tolerances[first], EFFECT_FACTOR),
                    f"{task_id}: {first} and {second} are within {EFFECT_FACTOR:g} tolerances (a role confusion "
                    "could be scored supported)")


# ---- twin-symmetric visibility --------------------------------------------------------------------------------

def visibility(tasks) -> list:
    """The ``visible_oracle_values`` declarations of a family's tasks (module docstring); raises ContractError when a
    visible answer breaks the twin-symmetric rule or a supplied JSON number equals an answer undeclared.

    ``tasks`` {task_id: {variant, twin, answers, tolerances, shown, json_inputs}}: ``shown`` {location:
    {provenance, values: {field: shown value}}}, ``json_inputs`` the parsed current JSON inputs."""
    declared = []
    for task_id, task in tasks.items():
        twin = tasks[task["twin"]]
        for location, entry in sorted(task["shown"].items()):
            require(entry["provenance"] in contracts.VISIBLE_PROVENANCE, f"{task_id}: {location}: provenance")
            for field, shown in sorted(entry["values"].items()):
                if field not in task["answers"] or not within(shown, task["answers"][field], task["tolerances"][field]):
                    continue
                other = twin["shown"].get(location, {}).get("values", {})
                require(field in other, f"{task_id}: {location} shows its {field} answer but its twin has no value "
                                        "there (the location would identify the variant)")
                twin_answer = twin["answers"].get(field)
                twin_at = twin_answer is not None and within(other[field], twin_answer, twin["tolerances"][field])
                require(task["variant"] == "valid" or twin_at,
                        f"{task_id}: a fault twin shows its {field} answer at {location}, where its valid twin does not")
                declared.append({"task": task_id, "location": location, "field": field,
                                 "provenance": entry["provenance"]})
        covered = {field for entry in task["shown"].values() if entry["provenance"] == "supplied_input"
                   for field in entry["values"]}
        numbers = [n for record in task["json_inputs"].values() for n in numbers_of(record)]
        for field, answer in task["answers"].items():
            tolerance = task["tolerances"][field]
            if tolerance["metric"] == "categorical" or field in covered:
                continue
            require(not any(within(n, answer, tolerance) for n in numbers),
                    f"{task_id}: a supplied JSON input shows the {field} answer at an undeclared location")
    return declared


# ---- the family tree --------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _scannable(data, kind):
    """A supplied JSON record parsed, or a text input's numbers, for the visibility scan (event files are
    covered by the family's declared locations: their momenta are not answers)."""
    text = data.decode("utf-8")
    if registry.INPUT_FORMATS[kind] == "json":
        return canonical.strict_loads(text)
    return [float(n) for n in _NUMBER.findall(text)]


def definition(task, *, family, prompt_sha256, oracle_sha256, canary, budget, waivers) -> dict:
    """The v2 task definition (contracts._task_definition_v2) of one task spec (``build``)."""
    return {
        "schema_version": 2, "task_id": task["task_id"], "family": family, "pair_id": task["pair_id"],
        "variant": task["variant"], "expected": task["expected"], "stratum": "S1", "split": "development",
        "objective": task["objective"], "exposure_class": task["exposure_class"], "twin_task_id": task["twin"],
        "bank_version": registry.BANK_VERSION, "prompt_sha256": prompt_sha256,
        "inputs": input_list(task["inputs"], task["kinds"]),
        "prior_inputs": input_list(task["prior_inputs"], task["prior_kinds"]),
        "prior_recipe": json.loads(json.dumps(task["prior_recipe"])),
        "allowed_operations": list(registry.CAMPAIGN_OPERATIONS), "units": dict(task["units"]),
        "oracle_kind": task["oracle_kind"], "approval_mode": task["approval_mode"], "budget": dict(budget),
        "endpoints": [dict(e) for e in task["endpoints"]], "fidelity": dict(task["fidelity"]),
        "diagnostic_tolerance": task["diagnostic_tolerance"], "required_title": task["required_title"],
        "reuse_plan": dict(task["reuse_plan"]), "refusal_conditions": [dict(c) for c in task["refusal_conditions"]],
        "waivers": sorted(waivers), "oracle_sha256": oracle_sha256,
        "source": json.loads(json.dumps(task["source"])), "provisional": True, "canary": canary,
    }


def build(out_dir, *, spec, request_path, tasks, canary=None, budget=None, index_extra=None) -> dict:
    """Check and write one family (module docstring) into a new or empty ``out_dir``; return its index.

    ``tasks`` is a list of task specs in index order: {task_id, variant, pair_id, twin, expected, exposure_class,
    label, objective, inputs {name: bytes}, kinds {name: kind}, prior_inputs, prior_kinds, prior_recipe, units,
    oracle_kind, approval_mode, endpoints, fidelity, diagnostic_tolerance, required_title, reuse_plan,
    refusal_conditions, source, oracle (record without canary), answers, tolerances, shown, canary_values}.
    Nothing is written unless every check passes. Layout as the likelihood_freshness family's: request.md,
    tasks/<id>/inputs/{current,prior}/<name>, tasks/<id>/{task_definition,oracle}.json, index.json; every path
    has exactly one role (subject_visible, prior_inputs, evaluator_private)."""
    out = Path(out_dir)
    require(not out.exists() or (out.is_dir() and not any(out.iterdir())),
            f"{out}: output directory must be new or empty")
    canary = registry.new_canary() if canary is None else canary
    require(isinstance(canary, str) and CANARY.fullmatch(canary) is not None, f"canary: must match {CANARY.pattern}")
    budget = dict(registry.DESIGN_BUDGET if budget is None else budget)
    family = spec["family"]
    registry.validate_spec(spec, f"{family}.SPEC")
    request = Path(request_path).read_bytes()
    prompt_sha256 = canonical.sha256_bytes(request)
    by_id = {task["task_id"]: task for task in tasks}
    require(len(by_id) == len(tasks), f"{family}: duplicate task id")
    visible = visibility({task_id: {
        "variant": task["variant"], "twin": task["twin"], "answers": task["answers"], "tolerances": task["tolerances"],
        "shown": task["shown"], "json_inputs": {name: _scannable(task["inputs"][name], kind)
                                                for name, kind in task["kinds"].items()
                                                if registry.INPUT_FORMATS[kind] in ("json", "text")}}
        for task_id, task in by_id.items()})
    supplied = [request.decode("utf-8")] + [readable_text(data) for task in tasks
                                            for side in ("inputs", "prior_inputs") for data in task[side].values()]
    files, entries, v1_tasks, definitions = {"request.md": request}, [], [], []
    roles = {"subject_visible": ["request.md"], "prior_inputs": [], "evaluator_private": ["index.json"]}
    for task in tasks:
        oracle = {**task["oracle"], "canary": canary}
        oracle_sha256 = canonical.digest(oracle)
        waivers = [contracts.VISIBILITY_WAIVER] if any(e["task"] == task["task_id"] for e in visible) else []
        record = definition(task, family=family, prompt_sha256=prompt_sha256, oracle_sha256=oracle_sha256,
                            canary=canary, budget=budget, waivers=waivers)
        definitions.append(record)
        base = f"tasks/{task['task_id']}"
        files[f"{base}/oracle.json"] = canonical.canonical_bytes(oracle)
        files[f"{base}/task_definition.json"] = canonical.canonical_bytes(record)
        roles["evaluator_private"] += [f"{base}/oracle.json", f"{base}/task_definition.json"]
        paths = {}
        for side, key, role in (("current", "inputs", "subject_visible"), ("prior", "prior_inputs", "prior_inputs")):
            paths[side] = {}
            for name, data in sorted(task[key].items()):
                files[f"{base}/inputs/{side}/{name}"] = data
                roles[role].append(f"{base}/inputs/{side}/{name}")
                paths[side][name] = {"path": f"{base}/inputs/{side}/{name}", "sha256": canonical.sha256_bytes(data)}
        entries.append({
            "task_id": task["task_id"], "label": task["label"], "pair_id": task["pair_id"],
            "pair_variant": task["variant"], "twin_task_id": task["twin"], "exposure_class": task["exposure_class"],
            "expected": task["expected"], "definition_path": f"{base}/task_definition.json",
            "definition_sha256": canonical.digest(record), "oracle_path": f"{base}/oracle.json",
            "oracle_sha256": oracle_sha256, "inputs": paths,
            "value_canaries": value_canaries(task["canary_values"], supplied)})
        v1_tasks.append({"id": task["task_id"], "expected": task["expected"], "prompt_sha256": prompt_sha256,
                         "oracle_sha256": oracle_sha256, "fidelity_tolerance": record["fidelity"]["tolerance"]})
    contracts.validate_task_bank(definitions, spec["contrasts"], f"{family} bank", visible_oracle_values=visible)
    index = {
        "schema_version": 2, "family": family, "bank_version": registry.BANK_VERSION, "synthetic": True,
        "provisional": True, "evaluator_private": True, "canary": canary,
        "request": {"path": "request.md", "sha256": prompt_sha256},
        "effect_factor": EFFECT_FACTOR,
        "ab_draw": {"bank_version": registry.BANK_VERSION, "rule": "valid letter = 'ab'[sha256(seed:pair_id)[0] & 1]",
                    "valid_letters": {pair["id"]: valid_letter(pair["id"]) for pair in spec["pairs"]}},
        "digest_convention": "definition_sha256 and oracle_sha256 are governance.canonical.digest of the parsed JSON "
                             "object; those files are canonical JSON, so sha256 of their bytes is the same value",
        "pairs": [dict(pair) for pair in spec["pairs"]],
        "contrasts": [dict(c, fault_inputs=list(c["fault_inputs"])) for c in spec["contrasts"]],
        "visible_oracle_values": visible,
        "path_roles": {role: sorted(listed) for role, listed in roles.items()},
        "tasks": entries, "v1_tasks": v1_tasks, **(index_extra or {}),
    }
    files["index.json"] = pretty(index)
    require(sorted(files) == sorted(path for listed in roles.values() for path in listed),
            "every written path must have exactly one role")
    for relative, data in files.items():
        canonical.write_once(out / relative, data)
    return index
