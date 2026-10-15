#!/usr/bin/env python3
"""Agent-surface consistency gate: the routing/docs/skills layer must be mechanically coherent.

The failure class this catches: a fresh cheap-model session routed by CLAUDE.md/AGENTS.md into
files that disagree, 404, or contradict each other. Run it per session (fast, stdlib-only,
read-only); the pre-commit hook runs it with --stage:

  check_agent_surface.py                # this tree's checks
  check_agent_surface.py --stage DIR    # ALSO: dead-reference check over a copy of the tree
  check_agent_surface.py --public       # public-tree mode (automatic in this repository)
  check_agent_surface.py --project DIR  # a project with an installed RAVEL agent surface

The development route is CONTRIBUTING.md -> DIRECTORY.md unless an optional settings file
declares another (`development_route`); only the documents the tree carries are checked.
Public mode also rejects routing docs that name material outside the distribution selection.

Checks (each PASS/FAIL, exit 1 on any FAIL):
  fork        CLAUDE.md + AGENTS.md agree: physicist route -> docs/workflow/start.md; the
              development read order is the configured one, in order
  refs        every backticked path in the routing docs / workflow docs / skills EXISTS
  skills      every SKILL.md has valid frontmatter (name == dir, trigger-rich description)
  mirror      .claude/skills <-> .agents/skills byte-identical (single source: sync_skills.py)
  dirmap      every DIRECTORY.md table path exists (local-only rows may name gitignored paths); unmapped top-level entries reported (WARN)
  readiness   readiness percentages quoted in the routing docs equal the committed audit report
  stepcount   'N steps' claims across routing docs == the actual count of docs/workflow/steps/*.md
  hygiene     no trial-run tokens in docs/workflow/ + .claude/skills + .claude/rules + README
  handbooks   runtime tool handbooks (src/ravel/data/skills/tools): closed six-key frontmatter,
              token budget (--token-budget, line proxy), pitfalls name a RAVEL check or are
              advisory, parameters are listed operation.field paths, upstream versions match the
              toolchain manifest and Python pins, review records list the tested code blocks
  installed   (--installed DIR) installed handbook copies are byte-identical to the package
  skill-keys  report-only: workflow skills using frontmatter keys outside the six-key set
  collisions  report-only: skill descriptions that overlap strongly
  stage       (--stage) every path referenced by files IN the stage exists IN the stage

  --doctor-report FILE prints the handbook unavailable ledger from a `ravel doctor --json` (or
  native_doctor) report.
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

from ravel.paths import require_repository_root, repository_root
from ravel import evidence_layout

import argparse
import glob as globmod
import json
import os
import re
import subprocess
import sys

REPO = repository_root()

# The development route; an optional settings file may configure another (`development_route`).
PUBLIC_DEV_READ_ORDER = ("CONTRIBUTING.md", "DIRECTORY.md")
ROUTING_DOCS = ("CLAUDE.md", "AGENTS.md", "README.md", "docs/reference/scope.md")
STEPCOUNT_DOCS = ROUTING_DOCS + ("docs/workflow/orchestration.md", "docs/workflow/README.md", "DIRECTORY.md")


def _source(root):
    """The optional settings for these checks, or {} for a tree without them."""
    return evidence_layout.source_settings(root)


def _setting(root, key):
    return tuple(_source(root).get(key, ()))
HYGIENE_TOKENS = re.compile(r"gluino-pair|squark-pair|slepton_200|2026-\d{2}-\d{2}_|C1N2-WZ")
HYGIENE_ALLOW = re.compile(r"µ₉₅ *= *1|mu95 *= *1")

# ref extraction: backticked tokens that look like repo paths
REF_RE = re.compile(r"`([^`\s]+)`")
EXTS = (".md", ".py", ".sh", ".json", ".cfg", ".toml", ".slha", ".yaml", ".yml", ".cc", ".mg5",
        ".dat", ".tcl", ".cff")
SKIP_REF = re.compile(r"[<>$|,;()\[\]]|^https?://|^--|^-[a-z]|[=:]|\.\.\.|…|\bNN-|X{2,}|Y{4}")


def _expand_braces(tok):
    """Expand {a,b,c} and {1..4} shell-brace groups into concrete variants."""
    m = re.search(r"\{([^{}]+)\}", tok)
    if not m:
        return [tok]
    body = m.group(1)
    rng = re.match(r"^(\d+)\.\.(\d+)$", body)
    parts = ([str(i) for i in range(int(rng.group(1)), int(rng.group(2)) + 1)] if rng
             else body.split(","))
    out = []
    for p in parts:
        out.extend(_expand_braces(tok[:m.start()] + p.strip() + tok[m.end():]))
    return out


def _is_pathlike(tok):
    if SKIP_REF.search(tok):
        return False
    is_dir = tok.endswith("/")
    tok = tok.rstrip("/")
    if "/" in tok:
        head = tok.split("/", 1)[0].replace("{", "").replace("}", "")
        tail = tok.rsplit("/", 1)[-1]
        if tail.isdigit():          # prose like `ebeam1/2`
            return False
        return bool(re.match(r"^[A-Za-z0-9_.~{}-]+$", head)) and not tok.startswith("~")
    return is_dir or tok.endswith(EXTS)


# Refs that are RUN-ARTIFACT conventions (a run PRODUCES them), upstream-install files, or
# pattern mentions — legitimate in prose, not statically checkable against the repo tree.
RUNTIME_PREFIX = re.compile(r"^(output|outputs|logs|inputs|plots|config|analysis|delphes|"
                            r"figures|build|Events|cards|templates/PROC)[/]")
RUNTIME_BARE_EXT = (".json", ".root", ".txt", ".png", ".pdf", ".yoda", ".hepmc", ".toml",
                    ".slha", ".mg5", ".dat", ".cfg", ".cmnd")
RUNTIME_NAMES = {"INDEX.md", "RESULT.md", "RESUME.md", "DEVIATIONS.md", "STATUS.txt",
                 "VERIFICATION-LADDER.md",
                 # compiled-on-host build products (their build scripts ship instead):
                 "rjr_resolve", "pythia_shower", "pythia_shower_merged"}


def _runtime_or_pattern(tok, root):
    t = tok.rstrip("/")
    if t.startswith("."):                                   # pure extension mention: `.mg5`
        return True
    if tok.endswith("/") and "/" not in t:                  # run-dir convention: `plots/`, `inputs/`
        return True
    if t.startswith("trial-runs/") and any(ch in t for ch in "*?"):
        return True  # generated run-layout conventions, not a shipped archive path
    if RUNTIME_PREFIX.match(t):
        return True
    if "/build/" in t or t.startswith("build/") or t.endswith("/build"):
        return True                                         # toolchain paths: regenerated by step 01
    if t in RUNTIME_NAMES or os.path.basename(t) in RUNTIME_NAMES:
        return True
    if "/" not in t and (t.endswith(RUNTIME_BARE_EXT) or "*" in t):
        return True                                         # bare artifact name / bare glob
    if t.endswith((".h", ".hh")):                           # upstream C++ headers
        return True
    if re.search(r"(^|/)_[^/]+_(/|$)", t):                  # grep-pattern segments: _SUSY_/...
        return True
    last = t.rsplit("/", 1)[-1]
    first = t.split("/", 1)[0]
    if "/" in t and not os.path.splitext(last)[1] and "*" not in t \
            and not os.path.exists(os.path.join(root, first)):
        return True                                         # keyword alternation: search/susy/...
    return False


_BASENAME_INDEX = {}


def _basename_index(root):
    """basename -> exists; built once per root over the doc/tool trees (a bare-filename
    mention like `pyhf_exclude.py` passes if the file exists ANYWHERE findable)."""
    if root in _BASENAME_INDEX:
        return _BASENAME_INDEX[root]
    names = set()
    prune = {".git", "build", "__pycache__", "output", "outputs", "PROC_madgraph", "logs",
             "plots", "inputs", "hepdata"}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in prune]
        names.update(fn)
        names.update(dn)
    _BASENAME_INDEX[root] = names
    return names


_LISTING = {}


def _listing(directory):
    if directory not in _LISTING:
        try:
            _LISTING[directory] = frozenset(os.listdir(directory))
        except OSError:
            _LISTING[directory] = frozenset()
    return _LISTING[directory]


def _exists_exact(base, rel):
    """True when `rel` exists under `base` with every written name spelled as the directory
    lists it. `os.path.exists` alone follows the filesystem, so on a case-insensitive one a
    differently-cased name would resolve there and nowhere else."""
    cand = os.path.normpath(os.path.join(base, rel))
    if not os.path.exists(cand):
        return False
    base = os.path.normpath(base)
    below = os.path.relpath(cand, base)
    if below == os.curdir:
        return True
    here = base
    for part in below.split(os.sep):
        if part == os.pardir:
            here = os.path.dirname(here)
            continue
        if part not in _listing(here):
            return False
        here = os.path.join(here, part)
    return True


def _resolve(tok, base_dirs, root=None):
    """A ref counts as existing if any brace-variant resolves (file/dir/glob) from ANY base,
    or, for a bare filename mention only, its basename exists in the tree. Names match with
    exact case on every filesystem."""
    for var in _expand_braces(tok.rstrip("/")):
        for base in base_dirs:
            if _exists_exact(base, var):
                return True
            cand = os.path.normpath(os.path.join(base, var))
            if any(ch in var for ch in "*?") and any(
                    _exists_exact(base, os.path.relpath(hit, base)) for hit in globmod.glob(cand)):
                return True
    if root is not None and "/" not in tok.rstrip("/"):
        base = os.path.basename(tok.rstrip("/"))
        if base and "*" not in base and "{" not in base and base in _basename_index(root):
            return True
    return False


def _md_files(root, rels):
    out = []
    for rel in rels:
        p = os.path.join(root, rel)
        if os.path.isdir(p):
            for dp, _dn, fn in os.walk(p):
                out.extend(os.path.join(dp, f) for f in fn if f.endswith(".md"))
        elif os.path.exists(p):
            out.append(p)
    return out


def check_refs(root, files, label):
    """Every path-like backticked ref in `files` must exist under `root` (or doc-relative).
    In STAGE mode, glob refs are POLICY-pattern mentions (quarantine rules naming namespaces a
    distribution does not carry) — not routes — and are skipped."""
    missing = []
    stage_mode = label == "stage"
    _LISTING.clear()
    for f in files:
        try:
            txt = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fdir = os.path.dirname(f)
        # workflow docs use workflow-relative refs (checklists/x.md); skills use repo-relative;
        # also accept one level up (docs/workflow/analysis-simpleanalysis uses ../)
        bases = (root, fdir, os.path.dirname(fdir))
        for tok in set(REF_RE.findall(txt)):
            if not _is_pathlike(tok) or _runtime_or_pattern(tok, root):
                continue
            if stage_mode and any(ch in tok for ch in "*?"):
                continue
            if not _resolve(tok, bases, root=root):
                missing.append(f"{os.path.relpath(f, root)}: `{tok}`")
    return missing if not missing else [f"[{label}] missing: {m}" for m in sorted(missing)]


def is_public(root):
    """A distributed tree (its provenance record and a registry without further declarations)."""
    return evidence_layout.is_public_tree(root)


def check_fork(root, public=False):
    errs = []
    docs = {}
    route = _setting(root, "development_route")
    order = PUBLIC_DEV_READ_ORDER if public or not route else route
    for name in ("CLAUDE.md", "AGENTS.md"):
        p = os.path.join(root, name)
        if not os.path.exists(p):
            errs.append(f"{name} missing")
            continue
        docs[name] = open(p, encoding="utf-8").read()
        if name == 'CLAUDE.md' and docs[name].splitlines()[0:1] == ['@AGENTS.md']:
            agents = os.path.join(root, 'AGENTS.md')
            if os.path.isfile(agents):
                docs[name] += '\n' + open(agents, encoding='utf-8').read()
    for name, txt in docs.items():
        if "docs/workflow/start.md" not in txt:
            errs.append(f"{name}: physicist route does not name docs/workflow/start.md")
        development = re.search(r"^[-*] \*\*Development request\*\*.*?(?=\n\n|\Z)", txt, re.M | re.S)
        if development is None:
            errs.append(f"{name}: development request route missing")
            continue
        route_text = development.group(0)
        idx = [route_text.find(x) for x in order]
        if any(i < 0 for i in idx):
            miss = [x for x, i in zip(order, idx) if i < 0]
            errs.append(f"{name}: dev read order missing {miss} "
                        f"(canonical: {' -> '.join(order)})")
        elif idx != sorted(idx):
            errs.append(f"{name}: dev read order out of canonical order "
                        f"{' -> '.join(order)}")
        if public:
            # A configured route's records, and anything the registry declares undistributed.
            try:
                named = evidence_layout.internal_mentions(txt, evidence_layout.internal_patterns(root))
            except (ValueError, OSError):
                named = []
            named += [doc for doc in route if doc not in order and doc in txt]
            if named:
                errs.append(f"{name}: names undistributed material {sorted(set(named))}, "
                            "which a public tree does not carry")
    return errs


def check_skills(root):
    errs = []
    skdir = os.path.join(root, ".claude", "skills")
    if not os.path.isdir(skdir):
        return [f".claude/skills missing under {root}"]
    for d in sorted(os.listdir(skdir)):
        sk = os.path.join(skdir, d, "SKILL.md")
        if not os.path.isfile(sk):
            if os.path.isdir(os.path.join(skdir, d)):
                errs.append(f"skill dir {d}/ has no SKILL.md")
            continue
        txt = open(sk, encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
        if not m:
            errs.append(f"{d}: no YAML frontmatter")
            continue
        fm = m.group(1)
        nm = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
        if not nm or nm.group(1) != d:
            errs.append(f"{d}: frontmatter name {nm.group(1) if nm else None!r} != dir name")
        desc = re.search(r"^description:\s*(.+?)(?=^\w+:|\Z)", fm, re.M | re.S)
        if not desc or len(" ".join(desc.group(1).split())) < 40:
            errs.append(f"{d}: description missing or too thin to trigger (<40 chars)")
    return errs


def check_mirror(root):
    src = os.path.join(root, ".claude", "skills")
    dst = os.path.join(root, ".agents", "skills")
    if not os.path.isdir(dst):
        return [".agents/skills does not exist — run sync_skills.py (single source = "
                ".claude/skills; AGENTS.md promises the mirror)"]
    errs = []
    def rel_files(base):
        out = {}
        for dp, _dn, fn in os.walk(base):
            for f in fn:
                if f == ".DS_Store":
                    continue
                p = os.path.join(dp, f)
                out[os.path.relpath(p, base)] = p
        return out
    s, t = rel_files(src), rel_files(dst)
    for r in sorted(set(s) - set(t)):
        errs.append(f"mirror missing: .agents/skills/{r}")
    for r in sorted(set(t) - set(s)):
        errs.append(f"mirror orphan: .agents/skills/{r} (no source in .claude/skills)")
    for r in sorted(set(s) & set(t)):
        if open(s[r], "rb").read() != open(t[r], "rb").read():
            errs.append(f"mirror drift: {r} differs — re-run sync_skills.py")
    return errs


def _gitignored(root, rel):
    """True when git ignores `rel` under `root` (a local-only path never present in a checkout)."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=root,
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def check_dirmap(root):
    """DIRECTORY.md is SECTIONED: '## `docs/workflow/` ...' headers set the base its rows are
    relative to ('## Repository root' -> the root). A row's first cell may carry several
    refs ('a.md + b.cfg', brace groups); the row passes if EVERY extracted ref resolves."""
    p = os.path.join(root, "DIRECTORY.md")
    if not os.path.exists(p):
        return ["DIRECTORY.md missing"], []
    errs, warns = [], []
    mapped = set()
    base = ""
    for line in open(p, encoding="utf-8"):
        h = re.match(r"^#{2,3}\s+(.*)", line)
        if h:
            hb = re.search(r"`([^`]+?)/?`", h.group(1))
            base = hb.group(1).rstrip("/") if hb else ""
            if base:
                mapped.add(base.split("/", 1)[0])
            continue
        row = re.match(r"^\|\s*(.+?)\s*\|", line)
        if not row:
            continue
        cell = row.group(1)
        if cell.lower() in ("path", "---", ":---") or set(cell) <= {"-", ":", " "}:
            continue
        toks = [t for t in REF_RE.findall(cell)
                if _is_pathlike(t) or os.path.exists(os.path.join(root, base, t))]
        if not toks:
            toks = [t for t in re.split(r"[`\s+]+", cell) if t and _is_pathlike(t)]
        if not toks:
            bare = cell.strip("`").strip()
            if bare and os.path.exists(os.path.join(root, base, bare)):
                mapped.add(bare.split("/", 1)[0] if not base else base)  # extension-less row: LICENSE
            continue
        planned = "(planned)" in line
        local_only = bool(re.match(r"^\|[^|]*\|\s*local-only\s*\|", line))
        for tok in toks:
            mapped.add(os.path.join(base, tok).split("/", 1)[0] if not base else base)
            if planned:
                continue
            if local_only and _gitignored(root, os.path.join(base, tok)):
                continue  # local-only row for a gitignored path: absent in a clean checkout
            bases = (os.path.join(root, base) if base else root, root)
            if not _resolve(tok, bases, root=root):
                errs.append(f"DIRECTORY.md [{base or 'root'}] row not on disk: {tok}")
    # inverse: unmapped top-level entries (WARN — directory-keeper's job)
    for e in sorted(os.listdir(root)):
        if e.startswith(".") or e in ("__pycache__", "py.py", "parser.out", "MG5_debug", "logs"):  # gitignored scratch
            continue
        if e not in mapped:
            warns.append(f"top-level {e} has no DIRECTORY.md row")
    return errs, warns


def check_readiness(root, public=False):
    """Assert every CURRENT readiness claim equals the committed audit report's headline. Keyed to
    the labeled claim forms only — dated HISTORY lines ('audit 96%→100%') are records, not
    claims. Only a tree whose settings name a committed audit report (`audit_report`) has one."""
    audit_rel = _source(root).get("audit_report")
    if not audit_rel:
        return []
    audit = os.path.join(root, audit_rel)
    if public and not os.path.exists(audit):
        return []
    if not os.path.exists(audit):
        return [f"{audit_rel} missing"]
    m = re.search(r"readiness\s*·\s*(\d+)%", open(audit, encoding="utf-8").read())
    if not m:
        return [f"{audit_rel} carries no 'readiness · N%' headline"]
    truth = m.group(1)
    claim_res = (re.compile(r"^\s*-?\s*\*\*Audit:\s*(\d+)%", re.M),      # a bold "Audit: N%" claim line
                 re.compile(r"AUDIT\.md`?\s*[,(]?\s*\*\*(\d+)%\*\*"),    # README/CLAUDE inline
                 re.compile(r"currently\s*\*\*(\d+)%\*\*"))              # DIRECTORY/WORKFLOW form
    errs = []
    for rel in ("README.md", *_setting(root, "readiness_claim_files"), "DIRECTORY.md", "CLAUDE.md",
                "docs/workflow/README.md"):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        for rx in claim_res:
            for got in rx.findall(txt):
                if got != truth:
                    errs.append(f"{rel}: claims {got}% but {audit_rel} says {truth}%")
    return errs


def check_stepcount(root):
    steps = globmod.glob(os.path.join(root, "docs", "workflow", "steps", "[0-9]*.md"))
    n = len(steps)
    if n == 0:
        return [f"no docs/workflow/steps/*.md found under {root}"]
    errs = []
    for rel in STEPCOUNT_DOCS + _setting(root, "stepcount_files"):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        for m in re.finditer(r"\b(\d+)\s+steps?\b(?!-)", open(p, encoding="utf-8").read()):
            if int(m.group(1)) not in (n,):
                errs.append(f"{rel}: says '{m.group(0)}' but docs/workflow/steps has {n} files")
    return errs


def check_hygiene(root):
    errs = []
    files = _md_files(root, ("docs/workflow", ".claude/skills", ".claude/rules", "README.md"))
    for f in files:
        if os.path.basename(f) == "distribution.md":
            continue
        for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
            if HYGIENE_TOKENS.search(line) and not HYGIENE_ALLOW.search(line):
                errs.append(f"{os.path.relpath(f, root)}:{i}: dev trial-run token: "
                            f"{line.strip()[:80]}")
    return errs


# ---------------------------------------------------------------------------
# Runtime tool handbooks (src/ravel/data/skills/tools). The contract lives in
# ravel.validation.tool_handbooks; these wrappers bind it to a tree.
# ---------------------------------------------------------------------------
HANDBOOK_ROOT = os.path.join("src", "ravel", "data", "skills", "tools")


def _tree_json(root, rel):
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        return None
    return json.loads(open(path, encoding="utf-8").read())


def check_handbooks(root, budget=None):
    """(errors, notes) for every packaged handbook in this tree."""
    from ravel.validation import tool_handbooks as hb
    if not os.path.isdir(os.path.join(root, HANDBOOK_ROOT)):
        return [f"{HANDBOOK_ROOT} missing"], []
    modes = (_tree_json(root, "src/ravel/data/mode_descriptors.json") or {}).get("modes", {})
    pyproject = os.path.join(root, "pyproject.toml")
    tests = os.path.join(root, "tests", "skills")
    from ravel.setup.manifest import view
    return hb.check_all(os.path.join(root, HANDBOOK_ROOT), modes=set(modes),
                        budget=budget or hb.TOKEN_BUDGET,
                        manifest=view(root) if os.path.exists(os.path.join(root, "native/setup/toolchain-manifest.json")) else None,
                        pyproject_text=open(pyproject, encoding="utf-8").read() if os.path.exists(pyproject) else "",
                        fields_path=os.path.join(root, "src/ravel/data/skills/operation-fields.json"),
                        src_root=os.path.join(root, "src"),
                        tests_root=tests if os.path.isdir(tests) else None)


def check_installed_handbooks(root, dirs):
    from ravel.validation import tool_handbooks as hb
    return hb.check_installed(dirs, os.path.join(root, HANDBOOK_ROOT))


def check_skill_keys(root):
    """Report-only: workflow skills whose frontmatter leaves the six-key set."""
    from ravel.validation import tool_handbooks as hb
    warns = []
    for path in sorted(globmod.glob(os.path.join(root, ".claude", "skills", "*", "SKILL.md"))):
        try:
            front, _ = hb.split_frontmatter(open(path, encoding="utf-8").read())
        except hb.FrontmatterError as error:
            warns.append(f"{os.path.relpath(path, root)}: {str(error).splitlines()[0]}")
            continue
        extra = sorted(set(front) - set(hb.FRONTMATTER_KEYS))
        if extra:
            warns.append(f"{os.path.relpath(path, root)}: keys {extra} outside the six-key set")
    return warns


def check_skill_collisions(root):
    """Report-only description overlap across workflow skills and handbooks."""
    from ravel.validation import tool_handbooks as hb
    files = globmod.glob(os.path.join(root, ".claude", "skills", "*", "SKILL.md"))
    files += globmod.glob(os.path.join(root, HANDBOOK_ROOT, "*", "SKILL.md"))
    return [f"descriptions of {a} and {b} overlap ({score})" for a, b, score in hb.collisions(files)]


def handbook_ledger(root, report_path):
    from ravel.validation import tool_handbooks as hb
    report = json.loads(open(report_path, encoding="utf-8").read())
    return hb.format_ledger(hb.availability(report, os.path.join(root, HANDBOOK_ROOT)))


def check_knowledge(root=None):
    """One structural atlas check; strict operation curation has its own gate."""
    from ravel.validation.check_knowledge import validate
    return validate(root, require_curation=False)


def check_roles(root):
    from ravel.workflow import role_registry
    return role_registry.validate_registry(root=root) + role_registry.check_rendered(root)


def main():
    global REPO
    if "--project" in sys.argv[1:]:
        # External installations retain merged project instructions; source
        # checkouts use the strict registry, atlas and instruction checks below.
        project = argparse.ArgumentParser()
        project.add_argument("--project", required=True)
        requested = os.path.abspath(project.parse_known_args(sys.argv[1:])[0].project)
        if not os.path.isfile(os.path.join(requested, 'src/ravel/data/roles/registry.json')):
            from ravel.workflow.agent_surface import check
            errs = check(requested)
            errs += check_knowledge()
            print(f"[{'FAIL' if errs else 'PASS'}] installed agent surface" + (f"  ({len(errs)} problem(s))" if errs else ""))
            for e in errs:
                print(f"    - {e}")
            sys.exit(1 if errs else 0)
        REPO = requested
    else:
        REPO = str(require_repository_root())
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', help='check a source checkout or installed project')
    ap.add_argument("--stage", help="ALSO check a staged export tree for dead refs")
    ap.add_argument("--public", action="store_true",
                    help="public-tree mode (automatic in a staged or published export)")
    ap.add_argument("--installed", action="append", default=[], metavar="DIR",
                    help="a skills directory holding installed handbook copies (repeatable)")
    ap.add_argument("--token-budget", type=int, default=None,
                    help="handbook token budget (default 5000; line proxy)")
    ap.add_argument("--doctor-report", metavar="FILE",
                    help="print the handbook unavailable ledger from a doctor JSON report")
    args = ap.parse_args()
    public = args.public or is_public(REPO)

    results = []  # (name, errs, warns)
    results.append(("fork", check_fork(REPO, public), []))
    results.append(("roles", check_roles(REPO), []))
    results.append(("knowledge", check_knowledge(REPO), []))
    ref_files = _md_files(REPO, ("docs/workflow", ".claude/skills", HANDBOOK_ROOT)) + [
        os.path.join(REPO, r) for r in ROUTING_DOCS if os.path.exists(os.path.join(REPO, r))]
    results.append(("refs", check_refs(REPO, ref_files, "dev"), []))
    results.append(("skills", check_skills(REPO), []))
    results.append(("mirror", check_mirror(REPO), []))
    dm_errs, dm_warns = check_dirmap(REPO)
    results.append(("dirmap", dm_errs, dm_warns))
    results.append(("readiness", check_readiness(REPO, public), []))
    results.append(("stepcount", check_stepcount(REPO), []))
    results.append(("hygiene", check_hygiene(REPO), []))
    hb_errs, hb_notes = check_handbooks(REPO, args.token_budget)
    results.append(("handbooks", hb_errs, hb_notes))
    if args.installed:
        results.append(("installed", check_installed_handbooks(REPO, args.installed), []))
    results.append(("skill-keys", [], check_skill_keys(REPO)))
    results.append(("collisions", [], check_skill_collisions(REPO)))
    if args.stage:
        # DIRECTORY.md is a map, not a route; the ROUTE surfaces must be dead-ref-free in the stage.
        st = os.path.abspath(args.stage)
        st_files = [f for f in _md_files(st, ("docs/workflow", ".claude/skills"))
                    if os.path.basename(f) != "distribution.md"] + [
            os.path.join(st, r) for r in ROUTING_DOCS
            if os.path.exists(os.path.join(st, r))]
        results.append(("stage", check_refs(st, st_files, "stage"), []))

    any_fail = False
    for name, errs, warns in results:
        tag = "FAIL" if errs else "PASS"
        any_fail |= bool(errs)
        print(f"[{tag}] {name}" + (f"  ({len(errs)} problem(s))" if errs else ""))
        for e in errs[:40]:
            print(f"    - {e}")
        if len(errs) > 40:
            print(f"    ... {len(errs) - 40} more")
        for w in warns[:15]:
            print(f"    ~ WARN: {w}")
    if args.doctor_report:
        print("\nhandbook availability (from the doctor report):")
        for line in handbook_ledger(REPO, args.doctor_report):
            print(f"    {line}")
    print(f"\nagent surface: {'FAIL' if any_fail else 'OK'}" + (" (public tree)" if public else ""))
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
