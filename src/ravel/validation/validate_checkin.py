#!/usr/bin/env python3
"""validate_checkin.py -- validate an emitted CHECK-IN artifact against checklists/check-ins.md.

stdlib-only, no network (any conda env, or none, can run it -- mirrors validate_task_contract.py).
Encodes the required SECTIONS/fields of each check-in as assertions:
  checkin1 -> core sections (i, iv, v, vi) plus the sections of its variant, selected by the
              task contract or declared as top-level `variant`: reproduction (i-b, ii, iii),
              calculation, method_study, survey, manuscript, generate or new_search.
              F-numbered flags in (v); three response modes in (vi); no placeholder content.
  checkin2 -> waypoint + expectation + the ask's two named options GO and ADJUST.
  deck     -> the 8 numbered sections incl. the verbatim verification-panel verdict.

Usage:
  validate_checkin.py <checkin.json>        # exit 0 valid, exit 1 + itemized errors
  validate_checkin.py --schema
  validate_checkin.py --selftest
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import json
import os, re, sys
from copy import deepcopy
from importlib import import_module
from importlib.resources import files
from ravel.workflow.state_io import read_json
from ravel.validation import checkin_withheld

CHECKIN_KINDS = ("checkin1", "checkin2", "deck")
CHECKIN1_SECTIONS = ("i", "i-b", "ii", "iii", "iv", "v", "vi")
# Every CHECK-IN 1: preamble, plan, numbered flags, response modes.
CHECKIN1_CORE = ("i", "iv", "v", "vi")
# The task-specific sections each variant adds to the core.
CHECKIN1_VARIANTS = {
    "reproduction": ("i-b", "ii", "iii"),
    "reference_withheld": ("i-b", "withheld_waypoints"),
    "calculation": ("formula", "conventions", "inputs", "precision", "check_value"),
    "method_study": ("dataset", "splits", "baselines", "calibration"),
    "survey": ("census_table", "coverage_gaps"),
    "manuscript": ("source_runs", "template"),
    "generate": ("recipe", "observable"),
    "new_search": ("blinding", "regions", "validation"),
}
# Variants a contract admits, keyed by intake kind or task_mode. A single entry is
# selected automatically; a broader task declares its variant in the check-in.
VARIANTS_BY_TASK = {
    "reproduce": ("reproduction", "reference_withheld"), "reinterpret": ("reproduction", "reference_withheld"),
    "projection": ("reproduction", "reference_withheld"), "scan": ("reproduction", "reference_withheld"),
    "no_routine": ("reproduction", "reference_withheld", "new_search"),
    "calculation": ("calculation",), "likelihood": ("calculation",),
    "generate": ("generate",),
    "survey": ("survey",), "summary_plot": ("survey",),
    "anomaly_search": ("new_search",),
    "method_study": ("method_study",), "manuscript": ("manuscript",),
    "research": tuple(CHECKIN1_VARIANTS), "unsupported": tuple(CHECKIN1_VARIANTS),
}
# Intake kinds that select their own variant regardless of task_mode.
INTAKE_VARIANT_KINDS = ("method_study", "manuscript")
PLACEHOLDERS = {"", "n/a", "na", "not applicable", "none", "tbd", "todo", "-", "--", "...",
                "null", "unknown", "placeholder", "to follow", "later"}
ROW_IDENTIFIERS = ("analysis", "id", "source", "reference", "paper", "inspire", "arxiv", "hepdata", "title")
CHECKIN2_SECTIONS = ("waypoint", "expectation", "ask")
DECK_SECTIONS = ("title", "headline_figures", "key_numbers", "validation_verdict",
                 "limitations", "deviations", "panel_verdict", "next_steps")

SCHEMA = {
    "schema_version": 1,
    "required": {
        "schema_version": "const 1",
        "kind": f"enum {CHECKIN_KINDS}",
        "sections": "obj -- keyed by the required section tokens for this kind",
    },
    "checkin1_sections": list(CHECKIN1_SECTIONS),
    "checkin1_core": list(CHECKIN1_CORE),
    "checkin1_variants": {k: list(v) for k, v in CHECKIN1_VARIANTS.items()},
    "checkin1_variants_by_task": {k: list(v) for k, v in VARIANTS_BY_TASK.items()},
    "checkin1_rules": ["optional top-level variant names one of checkin1_variants; without it the "
                       "task contract selects the variant, and the seven lettered sections select reproduction",
                       "every required section carries content; N/A, TBD and empty values are not content",
                       "(v) is a list of numbered flags, each id matching ^F<number>",
                       "(vi) names the THREE response modes (answer/ask/propose)",
                       "(iii) carries the declared figure contract + the waypoint",
                       "survey census_table rows name their source; manuscript source_runs give a path"],
    "checkin2_sections": list(CHECKIN2_SECTIONS),
    "checkin2_rules": ["ask.options names exactly the two options GO and ADJUST",
                       "sections.evidence_manifest is required for an operational GO; local validation checks its files"],
    "deck_sections": list(DECK_SECTIONS),
    "deck_rules": ["(7) panel_verdict carries the step-9 verification-panel verdict verbatim"],
}


def _sibling_contract(base_dir):
    """Best-effort read of the rundir's inputs/task_contract.json (None on any failure)."""
    try:
        return read_json(os.path.join(base_dir, "inputs", "task_contract.json"))
    except (OSError, ValueError):
        return None


def section_registry(registry=None):
    """Read trusted package registrations, ordered by (order, id).

    A row has id/order and either content or module/render. Optional validate
    names a function in that same module. ``applicable: false`` declares a row whose
    producer has not landed; it is skipped by declaration, never by a missing function. Callbacks receive one context mapping;
    render returns JSON content or None when its section does not apply, and
    validate(content, context) returns error strings. Run inputs never select code.
    """
    resource = registry or files('ravel').joinpath('data/checkin/sections.json')
    record = read_json(resource)
    if type(record) is not dict or record.get('schema_version') != 1 or type(record.get('sections')) is not list:
        raise ValueError('invalid CHECK-IN section registry')
    seen = set()
    for row in record['sections']:
        if (type(row) is not dict or type(row.get('id')) is not str or not row['id']
                or row['id'] in seen or type(row.get('order')) is not int):
            raise ValueError('distinct named CHECK-IN sections with integer order required')
        seen.add(row['id'])
        if set(row) - {'id', 'order', 'content', 'module', 'render', 'validate', 'applicable'}:
            raise ValueError('unknown CHECK-IN registration field')
        if 'applicable' in row and type(row['applicable']) is not bool:
            raise ValueError('CHECK-IN registration applicable must be a boolean')
        if ('content' in row) == ('module' in row):
            raise ValueError('section requires content or a module provider')
        if 'module' in row and (not isinstance(row['module'], str) or not row['module'].startswith('ravel.')
                or not isinstance(row.get('render'), str)):
            raise ValueError('section requires a trusted ravel module and render function')
        if 'content' in row and ('render' in row or 'validate' in row):
            raise ValueError('literal section cannot name callbacks')
    return sorted((row for row in record['sections'] if row.get('applicable', True)),
                  key=lambda row: (row['order'], row['id']))


def _section_context(c, base_dir, context):
    result = dict(context or {})
    result.update(document=c, base_dir=base_dir)
    result.setdefault('contract', _sibling_contract(base_dir) if base_dir is not None else None)
    return result


def _section_content(row, context):
    if 'content' in row:
        return deepcopy(row['content'])
    return getattr(import_module(row['module']), row['render'])(deepcopy(context))


def review_points_section(context):
    """One producer call for computed review points.

    The review-points owner implements checkin_section(context) -> JSON or None. While it
    has not landed the registry row says ``applicable: false``; an applicable row whose
    producer is missing is refused rather than silently omitted.
    """
    section = getattr(import_module('ravel.workflow.review_points'), 'checkin_section', None)
    if section is None:
        raise ValueError('the registered review_points CHECK-IN section has no producer '
                         '(ravel.workflow.review_points.checkin_section); mark the row applicable: false until it lands')
    return section(context)


def with_registered_sections(c, base_dir=None, *, registry=None, context=None):
    """Return a new CHECK-IN with applicable extension sections in stable order."""
    result = deepcopy(c)
    if result.get('kind') != 'checkin1':
        return result
    ctx = _section_context(c, base_dir, context)
    sections = result.setdefault('sections', {})
    for row in section_registry(registry):
        content = _section_content(row, ctx)
        if content is None:
            continue
        if row['id'] in sections and sections[row['id']] != content:
            raise ValueError('registered CHECK-IN section conflicts: ' + row['id'])
        sections.pop(row['id'], None)
        sections[row['id']] = content
    return result


def checkin_bytes(c, base_dir=None, *, registry=None, context=None):
    """Exact state_io JSON encoding of a CHECK-IN, including registered sections."""
    return (json.dumps(with_registered_sections(c, base_dir, registry=registry, context=context),
                       indent=2, allow_nan=False) + '\n').encode('utf-8')


def registered_section_errors(c, base_dir=None, *, registry=None, context=None):
    if c.get('kind') != 'checkin1':
        return []
    errors = []
    ctx = _section_context(c, base_dir, context)
    for row in section_registry(registry):
        content = _section_content(row, ctx)
        if content is None:
            continue
        actual = c.get('sections', {}).get(row['id'])
        if actual != content:
            errors.append('CHECK-IN 1 missing or changed registered section (' + row['id'] + ')')
        if 'validate' in row:
            errors.extend(getattr(import_module(row['module']), row['validate'])(actual, deepcopy(ctx)))
    return errors


def source_section_errors(secs, contract, kind='checkin1'):
    """Admission of declared CHECK-IN sources, returning the full refusal receipt.

    CHECK-IN 1 under restrictions must carry a nonempty census; a run that reads no
    external source lists the single row ``{"none": "<reason>"}``. Later check-ins
    admit whatever sources they list.
    """
    if not isinstance(contract, dict) or not contract.get('forbidden_sources'):
        return []
    from ravel.workflow.source_policy import read_receipt
    errors = []
    sources = secs.get('sources', None if kind == 'checkin1' else [])
    if type(sources) is not list or (kind == 'checkin1' and not sources):
        # Under restrictions the census is the admission record, so it cannot be omitted.
        return ['CHECK-IN sources census is required when the contract restricts sources: '
                'list every source descriptor the run reads']
    empty = [s for s in sources if isinstance(s, dict) and 'none' in s]
    if empty:
        # A run that reads no external source says so with one reason, and lists nothing else.
        if len(sources) != 1 or set(empty[0]) != {'none'} or not isinstance(empty[0]['none'], str) \
                or not empty[0]['none'].strip():
            return ['CHECK-IN sources census row "none" declares zero sources: it must be the only row and '
                    'give a nonempty reason']
        return []
    for source in sources:
        receipt = read_receipt(contract['forbidden_sources'], source)
        if not receipt['allowed']:
            errors.append('forbidden_source: ' + json.dumps(receipt, sort_keys=True))
    return errors


def _is_placeholder(value):
    """True when a section holds no content: empty, or only N/A-style strings."""
    if value is None or isinstance(value, bool):
        return value is None
    if isinstance(value, (int, float)):
        return False
    if isinstance(value, str):
        return value.strip().strip(".").strip().lower() in PLACEHOLDERS
    if isinstance(value, dict):
        return not value or all(_is_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return not value or all(_is_placeholder(v) for v in value)
    return False


def checkin_variant(contract):
    """The CHECK-IN 1 content a contract requires.

    This is the one place that maps a contract to CHECK-IN 1 sections. Callers
    depend only on the returned shape {"core", "allowed", "sections"}: "allowed" is the tuple of variants the contract admits
    (None without a readable contract) and "sections" maps each admitted variant to
    its added sections. The key may later come from the plan's operations and the
    deliverable's claims instead of task_mode.
    """
    allowed = None
    if isinstance(contract, dict):
        kind = (contract.get("intake") or {}).get("kind")
        allowed = VARIANTS_BY_TASK.get(kind if kind in INTAKE_VARIANT_KINDS else contract.get("task_mode"))
    return {"core": CHECKIN1_CORE, "allowed": allowed,
            "sections": {v: CHECKIN1_VARIANTS[v] for v in (allowed or CHECKIN1_VARIANTS)}}


def checkin1_variant(c, contract=None):
    """The CHECK-IN 1 variant: declared, selected by the contract, or the seven-section form."""
    declared = c.get("variant") if isinstance(c, dict) else None
    if declared is not None:
        return declared
    secs = c.get("sections") if isinstance(c, dict) and isinstance(c.get("sections"), dict) else {}
    if all(secs.get(k) for k in CHECKIN1_SECTIONS):
        return "reproduction"
    allowed = checkin_variant(contract)["allowed"]
    if allowed == ("reproduction", "reference_withheld"):
        return "reproduction"
    if allowed and len(allowed) == 1:
        return allowed[0]
    if allowed:
        return None
    return "reproduction"


def _variant_errors(variant, sections, secs):
    errs = []
    for k in sections:
        value = secs.get(k)
        if variant == "survey" and k == "coverage_gaps" and value == []:
            continue  # an explicit empty list states that no gap was found
        if k not in secs or _is_placeholder(value):
            errs.append(f"CHECK-IN 1 ({variant}) missing required section ({k})")
    if variant == "reproduction":
        iii = secs.get("iii")
        if isinstance(iii, dict) and not iii.get("waypoint"):
            errs.append("section (iii) must propose the EARLY-VERIFICATION waypoint")
    elif variant == "survey":
        rows = secs.get("census_table")
        if "census_table" in secs and not _is_placeholder(rows):
            if not isinstance(rows, list) or not all(
                    isinstance(r, dict) and any(isinstance(r.get(k), str) and r[k].strip() for k in ROW_IDENTIFIERS)
                    for r in rows):
                errs.append("section (census_table) must be a list of rows, each naming its source "
                            f"({', '.join(ROW_IDENTIFIERS)})")
        gaps = secs.get("coverage_gaps")
        if isinstance(gaps, list) and any(_is_placeholder(g) for g in gaps):
            errs.append("section (coverage_gaps) lists an empty gap")
    elif variant == "manuscript":
        runs = secs.get("source_runs")
        if "source_runs" in secs and not _is_placeholder(runs):
            if not isinstance(runs, list) or not all(
                    isinstance(r, dict) and any(isinstance(r.get(k), str) and r[k].strip() for k in ("path", "run"))
                    for r in runs):
                errs.append("section (source_runs) must list each source run with its path")
    return errs


# A pinned request plan adds these sections and checks that they equal the plan
# (intake architecture section 2.7.4). Contracts without pins are unaffected.
PLAN_SECTIONS = ("plan", "claims", "coverage", "ambiguities")
UNCERTIFIED_PREFIXES = ("uncertified", "blinded-prediction", "conditional", "not certified on this route")
MIN_EXPLANATION_WORDS = 8


def _rows(value):
    return value if isinstance(value, list) and all(isinstance(r, dict) for r in value) else None


def _ids(rows):
    return [r.get("id") for r in rows]


def _same_ids(section, rows, expected):
    if rows is None:
        return [f"CHECK-IN 1 section ({section}) must be a list of rows, one per plan id"]
    ids = _ids(rows)
    if len(ids) != len(set(map(str, ids))) or set(ids) != set(expected):
        return [f"CHECK-IN 1 section ({section}) must list exactly {sorted(expected)}; it lists {ids}"]
    return []


def _mentions(flags, ident, text=None):
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(ident)}(?![0-9])")
    for flag in flags if isinstance(flags, list) else ():
        blob = json.dumps(flag, ensure_ascii=False)
        if pattern.search(blob) and (text is None or text.lower() in blob.lower()):
            return True
    return False


def is_uncertified(fidelity):
    return isinstance(fidelity, str) and fidelity.strip().lower().startswith(UNCERTIFIED_PREFIXES)


def needs_route_label(claim, plan):
    """A claim served by children whose basis needs a certificate (rule P0-S1').

    The plan check decides this (validate_request_plan.served_off_route_a), so CHECK-IN 1 and the
    plan's flags name the same claims.
    """
    from ravel.validation.validate_request_plan import served_off_route_a
    return served_off_route_a(plan, claim["id"])


def _plain(value, minimum):
    return (isinstance(value, str) and not _is_placeholder(value)
            and len(value.split()) >= minimum and not is_uncertified(value))


def plan_section_errors(secs, reading, plan):
    """Content checks of the CHECK-IN 1 plan sections against the pinned reading and plan."""
    from ravel.validation.intake_records import NOT_CERTIFIED
    errs = []
    nodes = plan["nodes"]
    for k in PLAN_SECTIONS:
        empty_ok = (k == "ambiguities" and not reading["ambiguities"]) or (k == "claims" and not plan["claims"])
        if k not in secs or (_is_placeholder(secs[k]) and not (empty_ok and secs[k] == [])):
            errs.append(f"CHECK-IN 1 (pinned plan) missing required section ({k})")
    if errs:
        return errs
    flags = secs.get("v")
    errs += _same_ids("plan", _rows(secs["plan"]), [n["id"] for n in nodes])
    claims = _rows(secs["claims"])
    errs += _same_ids("claims", claims, [c["id"] for c in plan["claims"]])
    by_id = {c["id"]: c for c in plan["claims"]}
    for row in claims or ():
        claim = by_id.get(row.get("id"))
        if claim is None:
            continue
        if row.get("kind") != claim["kind"] or row.get("statement") != claim["statement"]:
            errs.append(f"CHECK-IN 1 section (claims) row {claim['id']} must show the plan's kind and statement")
        fidelity = row.get("fidelity")
        if not isinstance(fidelity, str) or _is_placeholder(fidelity):
            errs.append(f"CHECK-IN 1 section (claims) row {claim['id']} must state its fidelity")
            continue
        if needs_route_label(claim, plan) and fidelity.strip().lower() != NOT_CERTIFIED:
            errs.append(f"CHECK-IN 1 section (claims) row {claim['id']} is served by children with a "
                        f"certificate-relevant basis: its fidelity must read '{NOT_CERTIFIED}'")
        if claim["kind"] == "agreement" and (claim.get("comparison") or {}).get("tolerance") is None \
                and not is_uncertified(fidelity):
            errs.append(f"CHECK-IN 1 claim {claim['id']} is delivered certified but its plan declares no agreement "
                        "tolerance: declare the tolerance in the plan or deliver the claim uncertified")
        if is_uncertified(fidelity):
            if not _plain(row.get("explanation"), MIN_EXPLANATION_WORDS):
                errs.append(f"CHECK-IN 1 claim {claim['id']} is delivered uncertified: give a plain-language "
                            f"explanation for the reviewer (at least {MIN_EXPLANATION_WORDS} words) in explanation")
            if not _plain(row.get("certifiable_route"), 4):
                errs.append(f"CHECK-IN 1 claim {claim['id']} is delivered uncertified: propose a route that "
                            "could certify it in certifiable_route")
            if not _mentions(flags, claim["id"], fidelity.strip()):
                errs.append(f"CHECK-IN 1 claim {claim['id']} needs a numbered flag in (v) naming its "
                            f"fidelity '{fidelity.strip()}'")
    coverage = _rows(secs["coverage"])
    want = sorted((c["obligation_id"], tuple(sorted(c["by"]))) for c in plan["coverage"])
    got = None if coverage is None else sorted(
        (r.get("obligation_id"), tuple(sorted(r.get("by") or ())) if isinstance(r.get("by"), list) else None)
        for r in coverage)
    if got != want:
        errs.append("CHECK-IN 1 section (coverage) must equal the plan's coverage rows")
    ambiguities = _rows(secs["ambiguities"])
    errs += _same_ids("ambiguities", ambiguities, [a["id"] for a in reading["ambiguities"]])
    status = {a["id"]: a["status"] for a in reading["ambiguities"]}
    for row in ambiguities or ():
        if row.get("id") in status and row.get("status") != status[row["id"]]:
            errs.append(f"CHECK-IN 1 section (ambiguities) row {row['id']} must show status {status[row['id']]}")
    for ident, state in status.items():
        if state == "open" and not _mentions(flags, ident):
            errs.append(f"open ambiguity row {ident} must appear as a numbered flag in (v)")
    if plan["boundaries"]:
        if "boundaries" not in secs or _is_placeholder(secs["boundaries"]):
            errs.append("CHECK-IN 1 (pinned plan) missing required section (boundaries)")
        else:
            errs += _same_ids("boundaries", _rows(secs["boundaries"]), plan["boundaries"])
    authored = [n["id"] for n in nodes if n["kind"] == "authored"]
    if authored:
        if "authored" not in secs or _is_placeholder(secs["authored"]):
            errs.append("CHECK-IN 1 (pinned plan) missing required section (authored)")
        else:
            errs += _same_ids("authored", _rows(secs["authored"]), authored)
    return errs


def pinned_records(base_dir, contract):
    """(reading, plan) for a contract that pins a request plan, else (None, None). Raises ValueError."""
    if not isinstance(contract, dict) or "request_plan" not in contract:
        return None, None
    from ravel.validation import validate_task_contract
    errors = validate_task_contract.validate_pins(base_dir, contract)
    if errors:
        raise ValueError("; ".join(errors))
    return (validate_task_contract.load_pinned(base_dir, contract, "reading"),
            validate_task_contract.load_pinned(base_dir, contract, "request_plan"))


def adopted_default_errors(secs, base_dir):
    """The final deck lists every recorded adapter default a delegated plan adopted."""
    from ravel.validation.intake_records import DELEGATED_DEFAULTS_PATH, load_delegated_defaults
    record, errors = load_delegated_defaults(base_dir, _sibling_contract(base_dir))
    if errors:
        return [f"RESULTS DECK cannot list adopted adapter defaults: {'; '.join(errors)}"[:2000]]
    entries = (record or {}).get("entries") or []
    if not entries:
        return []
    rows = _rows(secs.get("adopted_defaults"))
    want = sorted((e["id"], e["node"], e["pointer"]) for e in entries)
    got = None if rows is None else sorted((r.get("id"), r.get("node"), r.get("pointer")) for r in rows)
    if got != want or any(_is_placeholder(r.get("justification")) for r in rows or ()):
        return [f"RESULTS DECK must list every adopted adapter default in {DELEGATED_DEFAULTS_PATH} "
                "(id, node, pointer and justification) in section (adopted_defaults)"]
    return []


def validate(c, base_dir=None):
    """Return a list of error strings (empty = valid).

    base_dir: when given, every path-like image token (.png/.pdf) cited in
    the CHECK-IN 1 gallery section must exist under it (or absolutely), and file:// URIs are
    rejected outright -- the "un-viewable deck" was link-only delivery of files the physicist
    could not open. base_dir also enables the route-surfacing rule against the sibling
    task_contract.json. base_dir=None keeps the pure-schema mode (back-compat)."""
    errs = []
    if not isinstance(c, dict):
        return ["check-in is not a JSON object"]
    if type(c.get("schema_version")) is not int or c.get("schema_version") != 1:
        errs.append(f"schema_version must be 1, got {c.get('schema_version')!r}")
    kind = c.get("kind")
    if kind not in CHECKIN_KINDS:
        errs.append(f"kind {kind!r} not in {CHECKIN_KINDS}")
    secs = c.get("sections")
    if not isinstance(secs, dict):
        errs.append("missing required 'sections' object")
        secs = {}

    if kind == "checkin1":
        if "site_tools" in secs:
            try:
                from ravel.workflow.site_tools import _validate
                _validate(secs["site_tools"], "scope")
            except Exception:
                errs.append("CHECK-IN 1 site_tools must validate against the site-tool scope schema")
        contract = _sibling_contract(base_dir) if base_dir is not None else None
        shape = checkin_variant(contract)
        allowed = shape["allowed"]
        declared = c.get("variant")
        variant = checkin1_variant(c, contract)
        if declared is not None and declared not in CHECKIN1_VARIANTS:
            errs.append(f"variant {declared!r} not in {tuple(CHECKIN1_VARIANTS)}")
            variant = None
        elif declared is not None and allowed is not None and declared not in allowed:
            errs.append(f"variant {declared!r} does not fit task_mode {contract.get('task_mode')} "
                        f"(allowed: {', '.join(allowed)})")
        if variant is None and declared is None:
            errs.append(f"declare the CHECK-IN 1 variant for task_mode {contract.get('task_mode')}: "
                        f"set top-level variant to one of {', '.join(allowed)}")
        for k in shape["core"]:
            if not secs.get(k) or _is_placeholder(secs.get(k)):
                errs.append(f"CHECK-IN 1 missing required section ({k})")
        if variant in CHECKIN1_VARIANTS:
            task_mode = contract.get("task_mode") if isinstance(contract, dict) else None
            sections = shape["sections"].get(variant, CHECKIN1_VARIANTS[variant])
            variant_errs = _variant_errors(variant, sections, secs)
            if variant_errs and declared is None and allowed and variant not in allowed:
                variant_errs.append(f"task_mode {task_mode} uses the {' or '.join(allowed)} variant: "
                                    "set top-level variant and write its sections instead")
            errs.extend(variant_errs)
        errs.extend(checkin_withheld.checkin_errors(c, contract, variant, base_dir=base_dir))
        flags = secs.get("v")
        if isinstance(flags, list):
            if not flags:
                errs.append("section (v) has no numbered flags (need >=1 F-numbered assumption)")
            for fl in flags:
                fid = fl.get("id") if isinstance(fl, dict) else fl
                if not (isinstance(fid, str) and re.match(r"^F\d+$", fid)):
                    errs.append(f"section (v) flag id {fid!r} must match F<number> (e.g. F1)")
        elif secs.get("v") is not None:
            errs.append("section (v) must be a list of numbered flags")
        modes = secs.get("vi")
        if not (isinstance(modes, list) and len(modes) >= 3):
            errs.append("section (vi) must name the THREE response modes (answer/ask/propose)")
        if base_dir is not None:
            blob = json.dumps(secs.get("ii"))
            if "file://" in blob:
                errs.append("gallery (ii) cites a file:// URI -- embed repo-relative paths and "
                            "attach/render the images, never bare file links")
            # Keep absolute and parent-relative prefixes. Dropping the leading
            # slash or ../ resolves a different file beneath the run directory.
            for tok in re.findall(r"[./]*[\w][\w./-]*\.(?:png|pdf)", blob):
                p = tok if os.path.isabs(tok) else os.path.join(base_dir, tok)
                if not os.path.isfile(p):
                    errs.append(f"gallery (ii) references a missing file: {tok}")
            try:
                reading, plan = pinned_records(base_dir, contract)
            except ValueError as exc:
                errs.append(f"CHECK-IN 1 cannot check its pinned plan sections: {exc}"[:2000])
            else:
                if plan is not None:
                    errs.extend(plan_section_errors(secs, reading, plan))
            # An uncertified-custom-Delphes route must
            # be physicist-VISIBLE at CHECK-IN 1, never buried in a contract assumptions note
            if isinstance(contract, dict) and contract.get("detector_mode") == "delphes-custom-uncertified" \
                    and "uncertified" not in json.dumps(secs).lower():
                errs.append("contract detector_mode=delphes-custom-uncertified but no CHECK-IN 1 "
                            "section surfaces the uncertified-Delphes status -- state the "
                            "proxy/no-exclusion-of-record label in the plan or a numbered flag")

    elif kind == "checkin2":
        for k in CHECKIN2_SECTIONS:
            if not secs.get(k):
                errs.append(f"CHECK-IN 2 missing required section ({k})")
        ask = secs.get("ask") or {}
        opts = ask.get("options") if isinstance(ask, dict) else None
        names = []
        if isinstance(opts, list):
            names = [(o.get("name") if isinstance(o, dict) else o) for o in opts]
        if not (len(names) == 2 and all(isinstance(n, str) for n in names)
                and set(names) == {"GO", "ADJUST"}):
            errs.append("CHECK-IN 2 ask must offer exactly the two named options GO and ADJUST")
        if "evidence_manifest" in secs and not isinstance(secs["evidence_manifest"], str):
            errs.append("CHECK-IN 2 evidence_manifest must be a path string")
        if base_dir is not None:
            bound = None
            if "evidence_manifest" in secs:
                from ravel.workflow import waypoint_evidence
                try:
                    bound = set(waypoint_evidence.bound_paths(base_dir))
                except (OSError, ValueError, TypeError) as exc:
                    errs.append(f"CHECK-IN 2 evidence_manifest: {exc}")
            for tok in re.findall(r"[./]*[\w][\w./-]*\.(?:png|pdf)", json.dumps(secs.get("waypoint"))):
                path = os.path.abspath(tok if os.path.isabs(tok) else os.path.join(base_dir, tok))
                if not os.path.isfile(path):
                    errs.append(f"waypoint references a missing file: {tok}")
                elif bound is not None and os.path.realpath(path) not in bound:
                    errs.append(f"waypoint figure is not bound by evidence_manifest: {tok}")

    elif kind == "deck":
        for k in DECK_SECTIONS:
            if not secs.get(k):
                errs.append(f"RESULTS DECK missing required section ({k})")
        if base_dir is not None:
            errs.extend(adopted_default_errors(secs, base_dir))
            from ravel.workflow.completion_choices import checkin_errors
            errs.extend(checkin_errors(secs, base_dir))
        if not secs.get("panel_verdict"):
            errs.append("deck section (7) panel_verdict must carry the step-9 verification-panel "
                        "verdict verbatim")
    from ravel.workflow.completion_claims import checkin_errors
    errs.extend(checkin_errors(secs, base_dir, kind=kind))
    try:
        errs.extend(source_section_errors(secs, _sibling_contract(base_dir) if base_dir is not None else None, kind))
    except (ValueError, TypeError) as exc:
        errs.append(f'CHECK-IN source policy refused: {exc}')
    try:
        errs.extend(registered_section_errors(c, base_dir))
    except (ValueError, OSError, ImportError, AttributeError, TypeError) as exc:
        errs.append(f'CHECK-IN section provider refused: {exc}')
    return errs


def selftest():
    good1 = {"schema_version": 1, "kind": "checkin1", "sections": {
        "i": "preamble", "i-b": "census", "ii": "gallery",
        "iii": {"figure_id": "Figure 3", "waypoint": "grey QCD-MC line"},
        "iv": "plan", "v": [{"id": "F1", "why": "x"}], "vi": ["answer", "ask", "propose"]}}
    good2 = {"schema_version": 1, "kind": "checkin2", "sections": {
        "waypoint": "side-by-side", "expectation": "match@stats",
        "ask": {"options": [{"name": "GO"}, {"name": "ADJUST"}]}}}
    goodd = {"schema_version": 1, "kind": "deck", "sections": {
        s: "x" for s in DECK_SECTIONS}}
    goodc = {"schema_version": 1, "kind": "checkin1", "variant": "calculation", "sections": {
        "i": "preamble", "iv": "plan", "v": [{"id": "F1", "why": "x"}], "vi": ["answer", "ask", "propose"],
        "formula": "a*b", "conventions": "natural units", "inputs": {"a": 2, "b": 3},
        "precision": "exact", "check_value": "a=1 returns b"}}
    cases = [(good1, None), (good2, None), (goodd, None), (goodc, None)]
    bads = [
        ({**good1, "sections": {k: v for k, v in good1["sections"].items() if k != "ii"}}, "(ii)"),
        ({**good1, "sections": {**good1["sections"], "v": [{"id": "X1"}]}}, "F<number>"),
        ({**good1, "sections": {**good1["sections"], "vi": ["only-one"]}}, "THREE response modes"),
        ({**good2, "sections": {**good2["sections"], "ask": {"options": [{"name": "GO"}]}}},
         "GO and ADJUST"),
        ({**goodd, "sections": {k: v for k, v in goodd["sections"].items() if k != "panel_verdict"}},
         "panel_verdict"),
        ({**goodc, "sections": {**goodc["sections"], "precision": "N/A"}}, "(precision)"),
        ({**goodc, "variant": "free-form"}, "variant"),
    ]
    for obj, _ in cases:
        errs = validate(obj)
        if errs:
            sys.exit(f"validate_checkin selftest: a GOOD example failed: {errs}")
    for obj, needle in bads:
        errs = validate(obj)
        if not any(needle in e for e in errs):
            sys.exit(f"validate_checkin selftest: BAD example did not flag {needle!r}: {errs}")
    print(f"validate_checkin selftest: PASS ({len(cases)} good + {len(bads)} bad)")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    if argv[0] == "--schema":
        print(json.dumps(SCHEMA, indent=2))
        return 0
    if argv[0] == "--selftest":
        selftest()
        return 0
    try:
        obj = read_json(argv[0])
    except (OSError, ValueError) as e:
        print(f"validate_checkin: cannot read {argv[0]}: {e}", file=sys.stderr)
        return 2
    # A checkin under <rundir>/inputs/ is validated WITH gallery-file existence (base_dir =
    # the rundir); any other path keeps the pure-schema mode.
    base_dir = None
    ap = os.path.abspath(argv[0])
    if os.path.basename(os.path.dirname(ap)) == "inputs":
        base_dir = os.path.dirname(os.path.dirname(ap))
    errs = validate(obj, base_dir=base_dir)
    if errs:
        print(f"INVALID check-in ({argv[0]}):")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"valid check-in: kind={obj.get('kind')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
