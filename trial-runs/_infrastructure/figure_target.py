#!/usr/bin/env python
"""The FIGURE CONTRACT: declare WHICH published figure a run reproduces, echo it, emit it side-by-side.

A reproduction is only checkable if the run states, up front, the specific published figure it is
reproducing (e.g. "Figure 16a of arXiv:1911.12606") -- and, at the end, shows the generated
counterpart NEXT TO it. This tool owns that contract file, <rundir>/inputs/figure_target.json
(schema_version 1), and its lifecycle:

  declare          write/merge a figure target (normalizes 'fig 16a' / 'Fig. 16(a)' -> 'Figure 16a')
  resolve          rank candidate figures from a hepdata_fetch.py manifest's figure_index by role +
                   model keywords, PRINT them and exit -- it NEVER auto-picks ([Opus] chooses, then
                   calls declare)
  attach-image     record the extracted published image (route: arxiv-tex-map | pdf-page | none)
  attach-generated record this pipeline's counterpart figure (--step 05-visualize | 08-scan)
  show             print the CHECK-IN-ready block (paper ids, figure id, caption, image or its
                   precise textual reference)
  compose          side-by-side PNG: published (left) vs this pipeline (right); PDF pages are
                   rasterized via gs; with NO extracted image it emits the generated figure under a
                   textual-reference banner (a VALID terminal state -- the reference suffices)
  critique         CR-026 structural-critique loop: EMIT the critique task (composite + declared
                   style facts + rubric) for a FRESH-CONTEXT agent, or --record its findings
                   (surviving structural mismatches become caption'd deviations; loop bounded at 2)

Resolution precedence for the figure id (docs: workflow/checklists/figure-contract.md):
  user-prompt > registry-hint (figure_manifest.FIGURE_HINTS) > hepdata-table-name (figure_index)
  > paper-inspection > description-only + CHECK-IN.
An extracted_image route of "none" is VALID provided figure_id + caption_snippet are populated:
the physicist verifies against the printed textual reference instead of a pixel echo.

AXES ARE FACTS, NOT DEFAULTS (workflow/checklists/plot-guidelines.md): the published figure's axis
scales are read off the extracted figure at declaration time and recorded per target as
  "axes": {"x": "linear|log", "y": "linear|log", "source": "read-from-published|assumed"}
via --axes-x/--axes-y (+ --axes-source) on declare or attach-image. The renderers
(scan_contour.py, mass_plane_overlay.py) CONSUME the record via read_axes() / --figure-target,
so the produced counterpart matches the published scales instead of guessing from heuristics
(we have failed BOTH ways: linear-where-published-log AND log-where-published-linear).

STYLE IS FACTS TOO (CR-026 M4b, the R6-content half; CR-016 lint owns the R6-layout half): beyond
axes, the published figure's VISUAL GRAMMAR is read off the extracted figure and recorded per
target as a "style" block over {binning, error_band_style, marker_conventions, color_encoding,
annotation_set, hatching, legend_order, panel_structure} (+ source), via --style-json on declare.
The `critique` subcommand then runs the bounded structural-critique loop: a FRESH-CONTEXT agent
sees ONLY the side-by-side composite + these facts and lists STRUCTURAL mismatches (never
aesthetics); ≤2 fix iterations; surviving mismatches become caption'd deviations in the deck.

Stdlib + PIL only; fail-loud (a malformed contract or missing prerequisite exits nonzero).

Usage:
  figure_target.py declare --rundir R --role summary|overlay --figure-id "fig 16a"
                   [--caption "..."] [--source user-prompt|registry-hint|hepdata-table-name|
                    paper-inspection|description-only] [--arxiv A] [--inspire I] [--code C]
                   [--hepdata-table T ...] [--axes-x linear|log] [--axes-y linear|log]
                   [--axes-source read-from-published|assumed] [--primary] [--no-checkin]
  figure_target.py resolve --analysis <alias> --hepdata-manifest <manifest.json>
                   --role summary|overlay [--model-keywords "slepton left-handed"]
  figure_target.py attach-image --rundir R --figure-id ID --route arxiv-tex-map|pdf-page|none
                   [--path P] [--pdf-page N] [--axes-x linear|log] [--axes-y linear|log]
                   [--axes-source read-from-published|assumed]
  figure_target.py attach-generated --rundir R --figure-id ID --path P --step 05-visualize|08-scan
  figure_target.py show --rundir R
  figure_target.py compose --rundir R [--figure-id ID] [--out PNG]  # omit id -> primary
  figure_target.py primary --rundir R [--figure-id ID | --role summary|overlay]
  figure_target.py checkin --rundir R [--figure-id ID]
  figure_target.py fulfil-primary --rundir R --by WHO [--utc TS] [--note "..."]

`verified_by_physicist` is a WRITTEN lifecycle field: `fulfil-primary` is its only write site, and it
refuses unless the single primary already has a composed `side_by_side` on disk (the physicist signs
off against the side-by-side, not a bare number).
"""
import argparse
import json
import os
import re
import subprocess
import sys

SCHEMA_VERSION = 1
ROLES = ("summary", "overlay")
SOURCES = ("user-prompt", "registry-hint", "hepdata-table-name", "paper-inspection",
           "description-only")
ROUTES = ("arxiv-tex-map", "pdf-page", "none")
STEPS = ("05-visualize", "08-scan")
AXIS_SCALES = ("linear", "log")
AXES_SOURCES = ("read-from-published", "assumed")
GS = "/usr/local/bin/gs"

# CR-026 (M4b) — the STYLE block: the published figure's visual grammar, read off the extracted
# figure at declaration (protocol P1 look-first), a FACT per field, never a default. `axes` (above)
# owns the scales; this owns everything else a referee compares at a glance. Rendering consumes it
# like `axes`; the critique loop (cmd_critique) scores the generated counterpart AGAINST it.
STYLE_FIELDS = (
    "binning",            # e.g. "uniform 100 GeV" / "variable, matching Table 3" / "n/a (contour)"
    "error_band_style",   # e.g. "hatched grey total-bkg band" / "±1σ,±2σ green/yellow (Brazil)"
    "marker_conventions", # e.g. "black points+error bars = data; solid line = S+B"
    "color_encoding",     # e.g. "bwr diverging, white at 0" / "Okabe-Ito per process"
    "annotation_set",     # e.g. "ATLAS label UL; lumi+√s UR; SR labels on panels"
    "hatching",           # e.g. "45° hatch on excluded region" / "none"
    "legend_order",       # e.g. "data, tt̄, W+jets, S+B" (top-to-bottom)
    "panel_structure",    # e.g. "single" / "main + ratio(data/bkg) below" / "2x2 grid"
)

# Role -> the table-name/description keywords that identify the figure KIND (general physics
# vocabulary, not analysis-specific): the summary figure is the exclusion contour/limit; the
# overlay figure is a yield/distribution comparison.
ROLE_KEYWORDS = {
    "summary": ("exclusion", "contour", "limit", "sensitivity"),
    "overlay": ("yield", "distribution", "events", "cutflow"),
}


def die(msg):
    print(f"ERROR (figure_target): {msg}", file=sys.stderr)
    sys.exit(1)


def _load_json_arg(spec, flag):
    """Parse a JSON CLI argument: inline JSON object, or @path to a JSON file."""
    try:
        if spec.startswith("@"):
            with open(spec[1:]) as f:
                return json.load(f)
        return json.loads(spec)
    except (OSError, json.JSONDecodeError) as e:
        die(f"{flag}: could not parse {spec!r} as JSON (inline object or @file): {e}")


def normalize_figure_id(raw):
    """'fig 16a' / 'Fig. 16(a)' / 'FIGURE 16 a' / '16a' -> 'Figure 16a'; None if unparseable."""
    if not raw:
        return None
    m = re.match(r"(?i)^\s*(?:fig(?:ure)?\.?\s*)?(\d+)\s*\(?\s*([a-z]?)\s*\)?\s*$", raw.strip())
    if not m:
        return None
    return f"Figure {m.group(1)}{m.group(2).lower()}"


def contract_path(rundir):
    return os.path.join(os.path.abspath(rundir), "inputs", "figure_target.json")


def load_contract(rundir, must_exist=False):
    path = contract_path(rundir)
    if not os.path.isfile(path):
        if must_exist:
            die(f"no figure contract at {path} -- run `figure_target.py declare` first")
        return {"schema_version": SCHEMA_VERSION, "targets": []}
    try:
        with open(path) as f:
            doc = json.load(f)
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")
    if doc.get("schema_version") != SCHEMA_VERSION:
        die(f"{path} has schema_version {doc.get('schema_version')!r}; this tool writes "
            f"{SCHEMA_VERSION}")
    if not isinstance(doc.get("targets"), list):
        die(f"{path} carries no 'targets' list")
    return doc


def save_contract(rundir, doc):
    path = contract_path(rundir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    return path


def find_target(doc, figure_id=None, role=None):
    """Match a target by normalized figure id (preferred) or by role."""
    if figure_id:
        for t in doc["targets"]:
            if t.get("figure_id") == figure_id:
                return t
    if role:
        for t in doc["targets"]:
            if t.get("role") == role:
                return t
    return None


def merge_axes(tgt, axes_x, axes_y, axes_source):
    """Merge the published-axis-scale record into a target (an explicit flag wins; absent flags
    leave the stored value alone). The axes are FACTS read off the published figure at declaration
    time -- source defaults to 'read-from-published'; pass --axes-source assumed when the published
    figure could not actually be inspected (and fix it once it can be)."""
    if not (axes_x or axes_y or axes_source):
        return
    ax = tgt.get("axes") or {}
    if axes_x:
        ax["x"] = axes_x
    if axes_y:
        ax["y"] = axes_y
    if axes_source:
        ax["source"] = axes_source
    elif not ax.get("source"):
        ax["source"] = "read-from-published"
    tgt["axes"] = ax


def merge_style(tgt, style_updates):
    """Merge a partial style dict into a target's `style` block (each key a visual-grammar FACT).
    Only recognized STYLE_FIELDS are accepted; a `source` key records provenance. An explicit
    value wins; absent keys leave the stored value alone."""
    if not style_updates:
        return
    st = tgt.get("style") or {}
    for k, v in style_updates.items():
        if k == "source":
            st["source"] = v
            continue
        if k not in STYLE_FIELDS:
            die(f"unknown style field {k!r}; allowed: {', '.join(STYLE_FIELDS)} (+ source)")
        st[k] = v
    if not st.get("source"):
        st["source"] = "read-from-published"
    tgt["style"] = st


def _resolve_target(contract, figure_id=None, role=None):
    """Shared target resolver for the consumption APIs (read_axes/read_style/critique)."""
    path = contract
    if os.path.isdir(path):
        path = contract_path(path)
    if not os.path.isfile(path):
        die(f"figure contract not found: {path}")
    try:
        with open(path) as f:
            doc = json.load(f)
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")
    targets = doc.get("targets") or []
    if not targets:
        die(f"{path} declares no targets")
    tgt = None
    if figure_id:
        fid = normalize_figure_id(figure_id)
        tgt = next((t for t in targets if t.get("figure_id") == fid), None)
        if tgt is None:
            die(f"{path}: no target with figure_id {fid!r}")
    elif role:
        tgt = next((t for t in targets if t.get("role") == role), None)
    if tgt is None:
        tgt = next((t for t in targets if t.get("primary")), None)
    if tgt is None and len(targets) == 1:
        tgt = targets[0]
    if tgt is None:
        die(f"{path}: several targets and none is primary -- disambiguate with a figure id")
    return tgt


def read_axes(contract, figure_id=None, role=None):
    """CONSUMPTION API for the renderers (scan_contour.py / mass_plane_overlay.py --figure-target):
    return one target's declared published-axis record
    {"x": "linear|log", "y": "linear|log", "source": "read-from-published|assumed"}, or None when
    the target exists but no axes were recorded (the renderer then falls back to its default).

    `contract` is the rundir OR the figure_target.json path itself. Target selection: figure_id
    match > role match > the primary target > a sole target. Fails loud on a missing/malformed
    contract or an unresolvable target -- the caller asked for the contract explicitly."""
    return _resolve_target(contract, figure_id, role).get("axes")


def read_style(contract, figure_id=None, role=None):
    """CONSUMPTION API (renderers + the critique loop): one target's declared `style` block, or
    None when none was recorded. Same target selection as read_axes."""
    return _resolve_target(contract, figure_id, role).get("style")


# --------------------------------------------------------------------------- declare
def cmd_declare(args):
    fig_id = None
    if args.figure_id:
        fig_id = normalize_figure_id(args.figure_id)
        if fig_id is None:
            die(f"could not parse figure id {args.figure_id!r} (expected e.g. 'fig 16a', "
                f"'Fig. 16(a)', 'Figure 3')")
    if fig_id is None and not args.caption:
        die("a target needs a --figure-id or at least a --caption (description-only)")
    doc = load_contract(args.rundir)
    # Match by figure id when one is given; only a description-only declare (no id) may merge
    # by role — otherwise a second same-role figure (e.g. two 'summary' targets, Figs 5+6 of one
    # paper) silently overwrites the first instead of appending.
    tgt = find_target(doc, figure_id=fig_id, role=None if fig_id else args.role)
    if tgt is None:
        tgt = {
            "primary": bool(args.primary),
            "role": args.role,
            "paper": {"arxiv": None, "inspire": None, "code": None},
            "figure_id": None,
            "caption_snippet": None,
            "source": None,
            "hepdata_tables": [],
            "axes": None,
            "style": None,
            "extracted_image": {"path": None, "route": "none", "pdf_page": None},
            "generated_counterpart": None,
            "side_by_side": None,
            "critique": None,
            "declared_at_checkin": False,
            "verified_by_physicist": None,
        }
        doc["targets"].append(tgt)
    # merge (an explicit flag always wins; absent flags leave the stored value alone)
    if args.primary:
        tgt["primary"] = True
    tgt["role"] = args.role
    if fig_id:
        tgt["figure_id"] = fig_id
    if args.caption:
        tgt["caption_snippet"] = args.caption
    if args.source:
        tgt["source"] = args.source
    for key, val in (("arxiv", args.arxiv), ("inspire", args.inspire), ("code", args.code)):
        if val:
            tgt["paper"][key] = val
    if args.hepdata_table:
        tgt["hepdata_tables"] = list(args.hepdata_table)
    merge_axes(tgt, args.axes_x, args.axes_y, args.axes_source)
    if args.style_json:
        merge_style(tgt, _load_json_arg(args.style_json, "--style-json"))
    tgt["declared_at_checkin"] = not args.no_checkin
    if tgt["source"] is None:
        die("--source is required on first declare (one of: " + ", ".join(SOURCES) + ")")
    if not any(tgt["paper"].values()):
        die("give at least one paper id (--arxiv / --inspire / --code) so the reference is precise")
    path = save_contract(args.rundir, doc)
    print(f"declared figure target: {tgt['figure_id'] or '(description-only)'}  role={tgt['role']}  "
          f"source={tgt['source']}")
    ax = tgt.get("axes")
    if ax:
        print(f"published axes: x={ax.get('x', '?')}  y={ax.get('y', '?')}  "
              f"(source: {ax.get('source')})")
    else:
        print("published axes: NOT recorded -- read them off the published figure and declare "
              "--axes-x/--axes-y (plot-guidelines.md: scales are facts, not defaults)")
    print(f"contract -> {path}")


# --------------------------------------------------------------------------- resolve
def cmd_resolve(args):
    if args.role not in ROLES:
        die(f"--role must be one of {ROLES}")
    if not os.path.isfile(args.hepdata_manifest):
        die(f"manifest not found: {args.hepdata_manifest}")
    with open(args.hepdata_manifest) as f:
        manifest = json.load(f)
    fig_index = manifest.get("figure_index") or {}
    tables = {t.get("name"): (t.get("description") or "") for t in manifest.get("tables", [])}
    if not fig_index:
        print("manifest carries NO figure_index (older manifest, or table names carry no "
              "'Figure N' prefix) -- re-run hepdata_fetch.py, or fall back to paper-inspection "
              "(fetch_figures.py --figure) / description-only + CHECK-IN.", file=sys.stderr)
        sys.exit(1)

    # registry hint (optional accelerator -- figure_manifest.FIGURE_HINTS; never required)
    hint = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import figure_manifest as _fm
        hint = (_fm.FIGURE_HINTS.get(_fm.canon_analysis(args.analysis)) or {}).get(args.role)
    except Exception:
        pass

    role_kw = ROLE_KEYWORDS[args.role]
    model_kw = [w for w in re.split(r"[,\s]+", (args.model_keywords or "").lower()) if w]
    hint_fid = None
    if hint:
        m = re.match(r"(?i)figure\s+(\S+)", hint)
        hint_fid = (m.group(1) if m else hint).lower()

    # Rank: a registry-hint match first (annotated -- it is a curated accelerator, and the hit is
    # shown, not silently trusted), then model-keyword hits counted in the table DESCRIPTIONS
    # (a table NAME that itself carries the model word would double-count it per table), then
    # role-keyword hits. The ranking is a HINT; [Opus] reads the descriptions and chooses.
    ranked = []
    for fid, names in sorted(fig_index.items()):
        blob = " ".join(n + " " + tables.get(n, "") for n in names).lower()
        descs = " ".join(tables.get(n, "") for n in names).lower()
        role_hits = sum(1 for k in role_kw if k in blob)
        model_hits = sum(descs.count(k) for k in model_kw)
        if role_hits == 0:
            continue
        ranked.append((int(fid == hint_fid), model_hits, role_hits, fid, names))
    ranked.sort(key=lambda r: (-r[0], -r[1], -r[2], r[3]))

    print(f"=== figure-target candidates  (role={args.role}; keywords: "
          f"{', '.join(model_kw) or '-'}) ===")
    if hint:
        print(f"registry hint ({args.analysis}): {hint}   <- cross-check, do not blindly trust")
    if not ranked:
        print(f"no figure matched the {args.role} role keywords {role_kw}; inspect the manifest's "
              f"figure_index by hand, or use paper-inspection / description-only.")
        # non-figure tables that DID match the role vocabulary are a useful pointer for the
        # paper-inspection fallback (e.g. cutflow/yield content published as "Table N")
        other = [t.get("name") for t in manifest.get("tables", [])
                 if not re.match(r"(?i)^\s*fig", t.get("name") or "")
                 and any(k in ((t.get("description") or "") + (t.get("name") or "")).lower()
                         for k in role_kw)]
        if other:
            print(f"note: non-figure tables matching the {args.role} vocabulary exist "
                  f"({', '.join(other[:5])}{', ...' if len(other) > 5 else ''}) -- they may back "
                  f"the figure you want; identify the figure itself from the paper.")
        sys.exit(1)
    for hinted, model_hits, role_hits, fid, names in ranked[: args.top]:
        tag = "  [registry hint]" if hinted else ""
        print(f"\nFigure {fid}   (model-keyword hits: {model_hits}, role hits: {role_hits}){tag}")
        for n in names:
            desc = tables.get(n, "").strip().replace("\n", " ")
            print(f"  - {n}: {desc[:110]}")
    print(f"\n[Opus] CHOOSE one candidate above (read the descriptions -- the ranking is a hint, "
          f"not a decision), then declare it:\n"
          f"  figure_target.py declare --rundir <rundir> --role {args.role} "
          f"--figure-id 'Figure <N>' --source hepdata-table-name --caption '<table description>' "
          f"--inspire {manifest.get('inspire') or '<insNNNN>'} [--hepdata-table '<name>' ...]")


# --------------------------------------------------------------------------- attach-*
def cmd_attach_image(args):
    fig_id = normalize_figure_id(args.figure_id)
    if fig_id is None:
        die(f"could not parse figure id {args.figure_id!r}")
    doc = load_contract(args.rundir, must_exist=True)
    tgt = find_target(doc, figure_id=fig_id)
    if tgt is None:
        die(f"no declared target with figure_id {fig_id!r} -- declare it first")
    if args.route != "none":
        if not args.path:
            die(f"route {args.route!r} needs --path (the extracted image/PDF)")
        if not os.path.isfile(args.path):
            die(f"extracted image not found: {args.path}")
    elif not (tgt.get("figure_id") and tgt.get("caption_snippet")):
        die("route 'none' is only a valid terminal state when figure_id AND caption_snippet are "
            "populated (the textual reference must be precise) -- declare a --caption first")
    tgt["extracted_image"] = {"path": os.path.abspath(args.path) if args.path else None,
                              "route": args.route, "pdf_page": args.pdf_page}
    merge_axes(tgt, args.axes_x, args.axes_y, args.axes_source)
    save_contract(args.rundir, doc)
    print(f"attached published image for {fig_id}: route={args.route}  "
          f"path={tgt['extracted_image']['path'] or '(textual reference only)'}")
    ax = tgt.get("axes")
    if ax:
        print(f"published axes: x={ax.get('x', '?')}  y={ax.get('y', '?')}  "
              f"(source: {ax.get('source')})")
    elif args.route != "none":
        print("published axes: NOT recorded -- you have the extracted image in hand, read the "
              "scales off it now (--axes-x/--axes-y)")


def cmd_attach_generated(args):
    fig_id = normalize_figure_id(args.figure_id)
    if fig_id is None:
        die(f"could not parse figure id {args.figure_id!r}")
    if not os.path.isfile(args.path):
        die(f"generated figure not found: {args.path}")
    doc = load_contract(args.rundir, must_exist=True)
    tgt = find_target(doc, figure_id=fig_id)
    if tgt is None:
        die(f"no declared target with figure_id {fig_id!r} -- declare it first")
    tgt["generated_counterpart"] = {"path": os.path.abspath(args.path), "step": args.step}
    save_contract(args.rundir, doc)
    print(f"attached generated counterpart for {fig_id} (step {args.step}): {args.path}")


# --------------------------------------------------------------------------- show
def cmd_show(args):
    doc = load_contract(args.rundir, must_exist=True)
    if not doc["targets"]:
        die("contract exists but declares no targets")
    print("=== FIGURE TARGET (check-in block) ===")
    for tgt in doc["targets"]:
        paper = tgt.get("paper", {})
        ids = ", ".join(f"{k}:{v}" for k, v in paper.items() if v) or "(no paper id!)"
        print(f"\nrole      : {tgt.get('role')}" + ("   [PRIMARY]" if tgt.get("primary") else ""))
        print(f"paper     : {ids}")
        print(f"figure    : {tgt.get('figure_id') or '(description-only)'}   "
              f"(source: {tgt.get('source')})")
        print(f"caption   : {tgt.get('caption_snippet') or '-'}")
        ax = tgt.get("axes")
        if ax:
            print(f"axes      : x={ax.get('x', '?')}  y={ax.get('y', '?')}   "
                  f"(source: {ax.get('source')})")
        else:
            print("axes      : NOT recorded -- read them off the published figure "
                  "(declare/attach-image --axes-x/--axes-y)")
        st = tgt.get("style")
        if st:
            n = sum(1 for k in STYLE_FIELDS if st.get(k))
            print(f"style     : {n}/{len(STYLE_FIELDS)} visual-grammar facts recorded "
                  f"(source: {st.get('source')})")
            for k in STYLE_FIELDS:
                if st.get(k):
                    print(f"            - {k}: {st[k]}")
        else:
            print("style     : NOT recorded -- read the visual grammar off the published figure "
                  "(declare --style-json; CR-026 M4b)")
        cr = tgt.get("critique")
        if cr:
            surv = cr.get("surviving_mismatches") or []
            print(f"critique  : {cr.get('iterations', '?')} iteration(s); "
                  f"{len(surv)} surviving structural mismatch(es)"
                  + ("  -> caption'd deviations" if surv else "  (form verified)"))
        ex = tgt.get("extracted_image") or {}
        if ex.get("path"):
            page = f"  (PDF page {ex['pdf_page']})" if ex.get("pdf_page") else ""
            print(f"published : {ex['path']}  [route: {ex.get('route')}]{page}")
        else:
            print(f"published : NOT EXTRACTED -- verify via figure id + caption above")
        gen = tgt.get("generated_counterpart")
        print(f"generated : " + (f"{gen['path']}  (step {gen['step']})" if gen
                                 else "not yet attached (declared, unfulfilled)"))
        print(f"side-by-side: {tgt.get('side_by_side') or '-'}")
        print(f"verified by physicist: {tgt.get('verified_by_physicist')}")


# --------------------------------------------------------------------------- compose
def _rasterize(path, workdir):
    """Return a PNG path for `path`, rasterizing PDF via gs when needed."""
    if not path.lower().endswith(".pdf"):
        return path
    out = os.path.join(workdir, os.path.splitext(os.path.basename(path))[0] + "__r200.png")
    cmd = [GS, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", "-r200",
           f"-sOutputFile={out}", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out):
        die(f"gs rasterization failed for {path}: {r.stderr.strip()[:200]}")
    return out


def resolve_compose_target(doc, figure_id):
    """compose's target resolver: an explicit --figure-id, else the single PRIMARY target (the deck
    default). Mirrors find_target on the ALREADY-LOADED doc so compose keeps mutating and saving the
    SAME doc (NOT _resolve_target, which reloads a detached copy you cannot save through)."""
    if figure_id:
        fig_id = normalize_figure_id(figure_id)
        if fig_id is None:
            die(f"could not parse figure id {figure_id!r}")
        tgt = find_target(doc, figure_id=fig_id)
        if tgt is None:
            die(f"no declared target with figure_id {fig_id!r}")
        return tgt, fig_id
    primaries = [t for t in doc["targets"] if t.get("primary")]
    if len(primaries) != 1:
        die(f"--figure-id omitted and there is not exactly one primary target (found "
            f"{len(primaries)}) -- pass --figure-id or set the primary with `primary --figure-id ID`")
    tgt = primaries[0]
    return tgt, (tgt.get("figure_id") or "primary")


def cmd_compose(args):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        die("PIL (pillow) is required for compose -- run in the rivet env")
    doc = load_contract(args.rundir, must_exist=True)
    tgt, fig_id = resolve_compose_target(doc, args.figure_id)
    gen = tgt.get("generated_counterpart")
    if not gen or not gen.get("path") or not os.path.isfile(gen["path"]):
        die(f"target {fig_id} has no generated counterpart on disk -- attach-generated first")
    out = args.out or os.path.join(os.path.abspath(args.rundir), "plots",
                                   f"figure_target__{fig_id.replace(' ', '')}__side_by_side.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    workdir = os.path.dirname(out)

    paper = tgt.get("paper", {})
    ref = paper.get("arxiv") and f"arXiv:{paper['arxiv']}" or paper.get("inspire") \
        or paper.get("code") or "published"

    def _font(size):
        try:
            return ImageFont.load_default(size=size)     # PIL >= 10
        except TypeError:
            return ImageFont.load_default()

    right = Image.open(_rasterize(gen["path"], workdir)).convert("RGB")
    ex = tgt.get("extracted_image") or {}
    if ex.get("path") and os.path.isfile(ex["path"]):
        left = Image.open(_rasterize(ex["path"], workdir)).convert("RGB")
        h = max(left.height, right.height)
        # label strip + font scale with the canvas so the labels stay legible at any size
        fsize = max(14, h // 40)
        pad, strip = max(12, h // 80), int(fsize * 2.2)
        font = _font(fsize)
        lw = int(left.width * h / left.height)
        rw = int(right.width * h / right.height)
        canvas = Image.new("RGB", (lw + rw + 3 * pad, h + strip + 2 * pad), (255, 255, 255))
        canvas.paste(left.resize((lw, h)), (pad, strip + pad))
        canvas.paste(right.resize((rw, h)), (lw + 2 * pad, strip + pad))
        d = ImageDraw.Draw(canvas)
        d.text((pad, pad), f"published ({ref}, {fig_id})", fill=(0, 0, 0), font=font)
        d.text((lw + 2 * pad, pad), "this pipeline", fill=(0, 0, 0), font=font)
        d.line([(lw + pad + pad // 2, strip), (lw + pad + pad // 2, h + strip + pad)],
               fill=(160, 160, 160), width=max(1, h // 800))
    else:
        # VALID degraded terminal state: no extracted image -- emit the generated figure under
        # a textual-reference banner so the physicist verifies against the printed reference.
        fsize = max(14, right.height // 40)
        pad = max(12, right.height // 80)
        font = _font(fsize)
        head = f"published reference NOT extracted -- verify against {ref}, {fig_id}: "
        cap = (tgt.get("caption_snippet") or "")[:120]
        probe = ImageDraw.Draw(right)
        while cap and probe.textlength(f'{head}"{cap}..."', font=font) > right.width:
            cap = cap[:-4]                      # truncate the caption to fit the banner width
        banner = f'{head}"{cap}..."' if cap else head.rstrip(": ")
        strip2 = int(fsize * 3.6)
        canvas = Image.new("RGB", (right.width + 2 * pad, right.height + strip2 + 2 * pad),
                           (255, 255, 255))
        canvas.paste(right, (pad, strip2 + pad))
        d = ImageDraw.Draw(canvas)
        d.text((pad, pad), banner, fill=(180, 0, 0), font=font)
        d.text((pad, pad + int(fsize * 1.5)), "this pipeline (below):", fill=(0, 0, 0), font=font)
    canvas.save(out)
    tgt["side_by_side"] = os.path.abspath(out)
    # A2 (trial QI.2): stamp provenance so a hand-populated side_by_side path is distinguishable
    # from a composed one -- validate_run_state's primary gate requires this stamp post-epoch.
    tgt["composed_by"] = {"tool": "figure_target.py compose",
                          "utc": os.environ.get("FIGURE_TARGET_UTC", "")}
    save_contract(args.rundir, doc)
    print(f"side-by-side -> {out}")


# --------------------------------------------------------------------------- critique (CR-026)
CRITIQUE_RUBRIC = [
    "panel_structure: same number/arrangement of panels (single / main+ratio / grid)?",
    "axes: same x/y SCALE (linear vs log) and the same plotted quantities + units?",
    "binning: same bin widths / edges where a binned quantity is shown?",
    "error_band_style: background/uncertainty band drawn the same way (hatched total, Brazil "
    "±1σ/±2σ, none)?",
    "marker_conventions: data as points+errors, S+B as a line, etc. — matched?",
    "color_encoding: same diverging/sequential/per-process scheme and zero-point?",
    "annotation_set: experiment label, lumi, √s, region/SR labels all present and placed like "
    "the published figure?",
    "legend_order + hatching: same series order; excluded-region hatching matches?",
    "curve topology: do the drawn curves/contours have the same SHAPE and crossings as published "
    "(a form check, not a numeric one)?",
]


def cmd_critique(args):
    """The bounded structural-critique loop (CR-026 M4b). Two modes:

      (no --record)  EMIT the critique task: the side-by-side path + the declared style facts +
                     the structural-mismatch rubric, for a FRESH-CONTEXT agent to answer. The
                     agent compares ONLY the composite against the spec and lists STRUCTURAL
                     mismatches (never aesthetics). This tool does not look at pixels.
      (--record J)   STORE that agent's findings: J = {"iterations":N, "mismatches":[...],
                     "surviving_mismatches":[...]} (inline JSON or @file). Surviving mismatches
                     become caption'd deviations in the deck. >2 iterations is flagged (the loop
                     is bounded)."""
    tgt = _resolve_target(args.rundir, figure_id=args.figure_id and normalize_figure_id(args.figure_id))
    if args.record:
        rec = _load_json_arg(args.record, "--record")
        if not isinstance(rec, dict):
            die("--record must be a JSON object {iterations, mismatches, surviving_mismatches}")
        iters = int(rec.get("iterations", 1))
        if iters > 2:
            print(f"WARNING: {iters} critique iterations recorded — the loop is bounded at 2; "
                  "surviving mismatches after 2 become caption'd deviations, not more iterations.",
                  file=sys.stderr)
        tgt["critique"] = {
            "iterations": iters,
            "mismatches": rec.get("mismatches") or [],
            "surviving_mismatches": rec.get("surviving_mismatches") or [],
            "recorded_at": rec.get("recorded_at"),
        }
        # reload the whole doc to save (tgt is a live reference into it)
        doc = load_contract(args.rundir, must_exist=True)
        for t in doc["targets"]:
            if t.get("figure_id") == tgt.get("figure_id") and t.get("role") == tgt.get("role"):
                t["critique"] = tgt["critique"]
        save_contract(args.rundir, doc)
        surv = tgt["critique"]["surviving_mismatches"]
        print(f"recorded critique: {iters} iteration(s), {len(surv)} surviving mismatch(es)"
              + (" -> caption'd deviations:" if surv else " (form verified, none surviving)"))
        for s in surv:
            print(f"  - {s}")
        return
    # EMIT mode
    sbs = tgt.get("side_by_side")
    if not sbs or not os.path.isfile(sbs):
        die("no side-by-side composite on disk -- run `compose` first (the critic sees only it)")
    st = tgt.get("style") or {}
    print("=== FIGURE CRITIQUE TASK (hand to a FRESH-CONTEXT agent) ===")
    print(f"composite : {sbs}")
    print(f"figure    : {tgt.get('figure_id')}  (published LEFT/TOP, this pipeline RIGHT/BELOW)")
    print("\nDeclared published STYLE facts (the spec to check against):")
    if st:
        for k in STYLE_FIELDS:
            if st.get(k):
                print(f"  - {k}: {st[k]}")
    else:
        print("  (no style block recorded -- critique falls back to the generic rubric only)")
    print("\nList STRUCTURAL mismatches only (NOT aesthetics/anti-aliasing/pixel colour). For each "
          "rubric item, PASS or a one-line mismatch:")
    for r in CRITIQUE_RUBRIC:
        print(f"  [ ] {r}")
    print("\nReturn JSON {\"iterations\":N,\"mismatches\":[...],\"surviving_mismatches\":[...]} and "
          "record it with:  figure_target.py critique --rundir R --figure-id ID --record @findings.json")


# --------------------------------------------------------------------------- primary
def cmd_primary(args):
    """Mark/query the SINGLE primary target. Enforces the single-primary invariant nothing else
    does today (declare's --primary only SETS True, never clears -- two targets can both be
    primary). With --figure-id/--role: make exactly that target primary and clear every other.
    With neither: QUERY -- print the current primary, or die if none/several."""
    doc = load_contract(args.rundir, must_exist=True)
    targets = doc["targets"]
    if not targets:
        die("no targets declared -- run `declare` first")
    if not args.figure_id and not args.role:
        primaries = [t for t in targets if t.get("primary")]
        if len(primaries) == 1:
            t = primaries[0]
            print(f"primary: {t.get('figure_id') or '(description-only)'}  role={t.get('role')}")
            return
        if not primaries:
            die("no primary target set -- `primary --figure-id ID` to set one")
        names = ", ".join(t.get("figure_id") or t.get("role") or "?" for t in primaries)
        die(f"AMBIGUOUS: {len(primaries)} targets marked primary ({names}) -- "
            "`primary --figure-id ID` to make exactly one primary")
    fid = normalize_figure_id(args.figure_id) if args.figure_id else None
    if args.figure_id and fid is None:
        die(f"could not parse figure id {args.figure_id!r}")
    chosen = None
    for t in targets:
        if (fid and t.get("figure_id") == fid) or (not fid and args.role and t.get("role") == args.role):
            chosen = t
            break
    if chosen is None:
        die("no declared target matches " + (f"figure-id {fid!r}" if fid else f"role {args.role!r}"))
    for t in targets:                       # SINGLE-PRIMARY invariant: exactly one, others cleared
        t["primary"] = (t is chosen)
    save_contract(args.rundir, doc)
    n = sum(1 for t in targets if t["primary"])
    print(f"primary -> {chosen.get('figure_id') or '(description-only)'}  role={chosen.get('role')}  "
          f"(single-primary invariant: {n} primary)")


# --------------------------------------------------------------------------- checkin
def cmd_checkin(args):
    """Record the CHECK-IN-time primary declaration: flip `declared_at_checkin=True` on the primary
    (or the --figure-id target) at ACTUAL check-in time, and echo the check-in-ready block. Distinct
    from declare (which sets the field eagerly): this is the lifecycle step the CHECK-IN-2 waypoint
    gate keys on -- only a target echoed here counts as bound to the approved contract."""
    doc = load_contract(args.rundir, must_exist=True)
    targets = doc["targets"]
    if not targets:
        die("no targets declared -- run `declare` first")
    if args.figure_id:
        fid = normalize_figure_id(args.figure_id)
        tgt = next((t for t in targets if t.get("figure_id") == fid), None)
        if tgt is None:
            die(f"no declared target with figure_id {fid!r}")
    else:
        primaries = [t for t in targets if t.get("primary")]
        if len(primaries) != 1:
            die(f"need exactly one primary target to check in (found {len(primaries)}) -- set it "
                "with `primary --figure-id ID` or pass --figure-id")
        tgt = primaries[0]
    tgt["declared_at_checkin"] = True       # tgt is a live ref into doc; save the whole doc
    save_contract(args.rundir, doc)
    print(f"checked in figure target: {tgt.get('figure_id') or '(description-only)'}  "
          f"role={tgt.get('role')}  declared_at_checkin=True")
    ex = tgt.get("extracted_image") or {}
    print("  published : " + (f"{ex['path']}  [route: {ex.get('route')}]" if ex.get("path")
                              else "NOT EXTRACTED -- verify via figure id + caption"))
    gen = tgt.get("generated_counterpart")
    print("  generated : " + (f"{gen['path']}  (step {gen['step']})" if gen else "not yet attached"))
    print(f"  side-by-side: {tgt.get('side_by_side') or '-'}")


# --------------------------------------------------------------------------- fulfil-primary
def cmd_fulfil_primary(args):
    """Finally WRITE verified_by_physicist (the dead field: init None @:294, printed @:506, zero
    write sites) on the primary target -- but ONLY after the composed side_by_side exists on disk.
    load_contract gives a LIVE reference into doc, so mutate + save_contract(doc) directly (no
    _resolve_target reload dance -- that returns a detached copy you cannot save through)."""
    doc = load_contract(args.rundir, must_exist=True)
    primaries = [t for t in doc["targets"] if t.get("primary")]
    if len(primaries) != 1:
        die(f"need exactly one primary target to fulfil (found {len(primaries)}) -- set it with "
            "`primary --figure-id ID`")
    tgt = primaries[0]
    sbs = tgt.get("side_by_side")
    if not sbs or not os.path.isfile(sbs):
        die("primary target has no composed side_by_side on disk -- run `compose` first (the "
            "physicist verifies against the side-by-side, not a bare number)")
    tgt["verified_by_physicist"] = {"by": args.by, "utc": args.utc, "note": args.note}
    save_contract(args.rundir, doc)
    print(f"fulfilled primary: {tgt.get('figure_id') or '(description-only)'}  "
          f"verified_by_physicist set (by={args.by})")


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("declare", help="write/merge a figure target into the contract")
    p.add_argument("--rundir", required=True)
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--figure-id", help="any common form: 'fig 16a', 'Fig. 16(a)', 'Figure 3'")
    p.add_argument("--caption", help="caption snippet (first sentence is enough)")
    p.add_argument("--source", choices=SOURCES)
    p.add_argument("--arxiv"); p.add_argument("--inspire"); p.add_argument("--code")
    p.add_argument("--hepdata-table", action="append",
                   help="HEPData table name backing this figure (repeatable)")
    p.add_argument("--axes-x", choices=AXIS_SCALES,
                   help="the PUBLISHED figure's x-axis scale, read off the extracted figure")
    p.add_argument("--axes-y", choices=AXIS_SCALES,
                   help="the PUBLISHED figure's y-axis scale, read off the extracted figure")
    p.add_argument("--axes-source", choices=AXES_SOURCES,
                   help="provenance of the axes record (default read-from-published; use "
                        "'assumed' only when the published figure could not be inspected)")
    p.add_argument("--style-json", metavar="JSON|@FILE",
                   help="visual-grammar FACTS read off the published figure (CR-026): a JSON "
                        "object over {" + ",".join(STYLE_FIELDS) + "} (+source). Inline or @file.")
    p.add_argument("--primary", action="store_true")
    p.add_argument("--no-checkin", action="store_true",
                   help="mark the target as NOT yet echoed at a check-in")
    p.set_defaults(fn=cmd_declare)

    p = sub.add_parser("resolve", help="rank candidate figures from a manifest's figure_index "
                                       "(prints candidates; NEVER auto-picks)")
    p.add_argument("--analysis", required=True,
                   help="analysis id/alias (for the optional registry hint)")
    p.add_argument("--hepdata-manifest", required=True)
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--model-keywords", help="model words to rank by (e.g. 'slepton left-handed')")
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("attach-image", help="record the extracted published image")
    p.add_argument("--rundir", required=True)
    p.add_argument("--figure-id", required=True)
    p.add_argument("--route", required=True, choices=ROUTES)
    p.add_argument("--path")
    p.add_argument("--pdf-page", type=int)
    p.add_argument("--axes-x", choices=AXIS_SCALES,
                   help="the PUBLISHED figure's x-axis scale, read off the image just attached")
    p.add_argument("--axes-y", choices=AXIS_SCALES,
                   help="the PUBLISHED figure's y-axis scale, read off the image just attached")
    p.add_argument("--axes-source", choices=AXES_SOURCES,
                   help="provenance of the axes record (default read-from-published)")
    p.set_defaults(fn=cmd_attach_image)

    p = sub.add_parser("attach-generated", help="record this pipeline's counterpart figure")
    p.add_argument("--rundir", required=True)
    p.add_argument("--figure-id", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--step", required=True, choices=STEPS)
    p.set_defaults(fn=cmd_attach_generated)

    p = sub.add_parser("show", help="print the check-in-ready figure-target block")
    p.add_argument("--rundir", required=True)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("compose", help="published|generated side-by-side PNG")
    p.add_argument("--rundir", required=True)
    p.add_argument("--figure-id", help="omit to compose the single PRIMARY target (deck default)")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_compose)

    p = sub.add_parser("critique", help="CR-026 structural-critique loop: emit the critique task, "
                                        "or --record a fresh-context agent's findings")
    p.add_argument("--rundir", required=True)
    p.add_argument("--figure-id")
    p.add_argument("--record", metavar="JSON|@FILE",
                   help="store findings {iterations,mismatches,surviving_mismatches}; surviving "
                        "ones become caption'd deviations")
    p.set_defaults(fn=cmd_critique)

    p = sub.add_parser("primary", help="mark/query the SINGLE primary target (enforces exactly one)")
    p.add_argument("--rundir", required=True)
    p.add_argument("--figure-id", help="target to make primary (any common form)")
    p.add_argument("--role", choices=ROLES, help="alt selector when no figure id")
    p.set_defaults(fn=cmd_primary)

    p = sub.add_parser("checkin", help="record the CHECK-IN-time primary declaration "
                                       "(sets declared_at_checkin on the primary)")
    p.add_argument("--rundir", required=True)
    p.add_argument("--figure-id", help="target to check in (default: the single primary)")
    p.set_defaults(fn=cmd_checkin)

    p = sub.add_parser("fulfil-primary", help="write verified_by_physicist on the primary "
                                              "(requires a composed side_by_side on disk)")
    p.add_argument("--rundir", required=True)
    p.add_argument("--by", required=True, help="who verified (physicist name/id)")
    p.add_argument("--utc", help="verification timestamp")
    p.add_argument("--note", help="one-line verification note")
    p.set_defaults(fn=cmd_fulfil_primary)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
