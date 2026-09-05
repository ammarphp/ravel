#!/usr/bin/env python3
"""validate_checkin.py -- validate an emitted CHECK-IN artifact against checklists/check-ins.md.

stdlib-only, no network (any conda env, or none, can run it -- mirrors validate_task_contract.py).
Encodes the required SECTIONS/fields of each check-in as assertions:
  checkin1 -> the SEVEN lettered sections (i, i-b, ii, iii, iv, v, vi); F-numbered flags in (v);
              three response modes in (vi).
  checkin2 -> waypoint + expectation + the ask's two named options GO and ADJUST.
  deck     -> the 8 numbered sections incl. the verbatim verification-panel verdict.

Usage:
  validate_checkin.py <checkin.json>        # exit 0 valid, exit 1 + itemized errors
  validate_checkin.py --schema
  validate_checkin.py --selftest
"""
import json
import os, re, sys

CHECKIN_KINDS = ("checkin1", "checkin2", "deck")
CHECKIN1_SECTIONS = ("i", "i-b", "ii", "iii", "iv", "v", "vi")
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
    "checkin1_rules": ["(v) is a list of numbered flags, each id matching ^F<number>",
                       "(vi) names the THREE response modes (answer/ask/propose)",
                       "(iii) carries the declared figure contract + the waypoint"],
    "checkin2_sections": list(CHECKIN2_SECTIONS),
    "checkin2_rules": ["ask.options names exactly the two options GO and ADJUST"],
    "deck_sections": list(DECK_SECTIONS),
    "deck_rules": ["(7) panel_verdict carries the step-9 verification-panel verdict verbatim"],
}


def _sibling_contract(base_dir):
    """Best-effort read of the rundir's inputs/task_contract.json (None on any failure)."""
    try:
        with open(os.path.join(base_dir, "inputs", "task_contract.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def validate(c, base_dir=None):
    """Return a list of error strings (empty = valid).

    base_dir (A6, trial QD.1/QM.1): when given, every path-like image token (.png/.pdf) cited in
    the CHECK-IN 1 gallery section must exist under it (or absolutely), and file:// URIs are
    rejected outright -- the "un-viewable deck" was link-only delivery of files the physicist
    could not open. base_dir also enables the CR-134 route-surfacing rule against the sibling
    task_contract.json. base_dir=None keeps the pure-schema mode (back-compat)."""
    errs = []
    if not isinstance(c, dict):
        return ["check-in is not a JSON object"]
    if c.get("schema_version") != 1:
        errs.append(f"schema_version must be 1, got {c.get('schema_version')!r}")
    kind = c.get("kind")
    if kind not in CHECKIN_KINDS:
        errs.append(f"kind {kind!r} not in {CHECKIN_KINDS}")
    secs = c.get("sections")
    if not isinstance(secs, dict):
        errs.append("missing required 'sections' object")
        secs = {}

    if kind == "checkin1":
        for k in CHECKIN1_SECTIONS:
            if not secs.get(k):
                errs.append(f"CHECK-IN 1 missing required section ({k})")
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
        iii = secs.get("iii")
        if isinstance(iii, dict) and not iii.get("waypoint"):
            errs.append("section (iii) must propose the EARLY-VERIFICATION waypoint")
        if base_dir is not None:
            blob = json.dumps(secs.get("ii"))
            if "file://" in blob:
                errs.append("gallery (ii) cites a file:// URI -- embed repo-relative paths and "
                            "attach/render the images, never bare file links (trial QM.1)")
            for tok in re.findall(r"[\w][\w./-]*\.(?:png|pdf)", blob):
                p = tok if os.path.isabs(tok) else os.path.join(base_dir, tok)
                if not os.path.isfile(p):
                    errs.append(f"gallery (ii) references a missing file: {tok}")
            # CR-134 (adjudication section II.4 item 6): an uncertified-custom-Delphes route must
            # be physicist-VISIBLE at CHECK-IN 1, never buried in a contract assumptions note
            contract = _sibling_contract(base_dir)
            if (contract or {}).get("detector_mode") == "delphes-custom-uncertified" \
                    and "uncertified" not in json.dumps(secs).lower():
                errs.append("contract detector_mode=delphes-custom-uncertified but no CHECK-IN 1 "
                            "section surfaces the uncertified-Delphes status -- state the "
                            "proxy/no-exclusion-of-record label in the plan or a numbered flag "
                            "(CR-134)")

    elif kind == "checkin2":
        for k in CHECKIN2_SECTIONS:
            if not secs.get(k):
                errs.append(f"CHECK-IN 2 missing required section ({k})")
        ask = secs.get("ask") or {}
        opts = ask.get("options") if isinstance(ask, dict) else None
        names = set()
        if isinstance(opts, list):
            names = {(o.get("name") if isinstance(o, dict) else o) for o in opts}
        if not {"GO", "ADJUST"}.issubset(names):
            errs.append("CHECK-IN 2 ask must offer exactly the two named options GO and ADJUST")

    elif kind == "deck":
        for k in DECK_SECTIONS:
            if not secs.get(k):
                errs.append(f"RESULTS DECK missing required section ({k})")
        if not secs.get("panel_verdict"):
            errs.append("deck section (7) panel_verdict must carry the step-9 verification-panel "
                        "verdict verbatim")
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
    cases = [(good1, None), (good2, None), (goodd, None)]
    bads = [
        ({**good1, "sections": {k: v for k, v in good1["sections"].items() if k != "ii"}}, "(ii)"),
        ({**good1, "sections": {**good1["sections"], "v": [{"id": "X1"}]}}, "F<number>"),
        ({**good1, "sections": {**good1["sections"], "vi": ["only-one"]}}, "THREE response modes"),
        ({**good2, "sections": {**good2["sections"], "ask": {"options": [{"name": "GO"}]}}},
         "GO and ADJUST"),
        ({**goodd, "sections": {k: v for k, v in goodd["sections"].items() if k != "panel_verdict"}},
         "panel_verdict"),
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
        obj = json.load(open(argv[0]))
    except (OSError, json.JSONDecodeError) as e:
        print(f"validate_checkin: cannot read {argv[0]}: {e}", file=sys.stderr)
        return 2
    # A6: a checkin under <rundir>/inputs/ is validated WITH gallery-file existence (base_dir =
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
