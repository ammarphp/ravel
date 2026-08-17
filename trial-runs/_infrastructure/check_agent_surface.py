#!/usr/bin/env python3
"""Agent-surface consistency gate: the routing/docs/skills layer must be mechanically coherent.

The failure class this kills (charter F1 + audit S0-4/A1-04/A1-05): a fresh cheap-model session
routed by CLAUDE.md/AGENTS.md into files that disagree, 404, or contradict each other. Run it
per session (fast, stdlib-only, read-only) and in P3/pre-export:

  check_agent_surface.py                # dev-tree checks
  check_agent_surface.py --stage DIR    # ALSO: dead-reference check over a staged export tree

Checks (each PASS/FAIL, exit 1 on any FAIL):
  fork        CLAUDE.md + AGENTS.md agree: physicist route -> workflow/INITIATE.md; dev read
              order = DIRECTORY.md -> framework/STATUS.md -> framework/PLAN-OF-RECORD.md
  refs        every backticked path in the routing docs / workflow docs / skills EXISTS
  skills      every SKILL.md has valid frontmatter (name == dir, trigger-rich description)
  mirror      .claude/skills <-> .agents/skills byte-identical (single source: sync_skills.py)
  dirmap      every DIRECTORY.md table path exists; unmapped top-level entries reported (WARN)
  statefresh  the reconciliation-enforcement gate (CR-036/Task 2B): (1) gen_status.py --check is
              clean (generated blocks fresh vs capability-matrix.json) — incl. the old AUDIT.md
              %-claim comparison; (2) served/partial/unbuilt counts + readiness% + R9 status/score
              quoted in the CURRENT-CLAIM docs equal the LIVE matrix-derived truth; (3) no
              forbidden stale-claim phrasing (shape-fit "still blocked", "D2 design", "unbuilt"
              on a built capability, ...) survives once its matrix guard has flipped. Dated
              history (session logs, dated bullets, (historical)/SUPERSEDED/kept-for-the-record
              lines, the gen_status.py marker blocks themselves) is exempt by construction.
  stepcount   'N steps' claims across routing docs == the actual count of workflow/steps/*.md
  hygiene     no dev trial-run tokens in workflow/ + .claude/skills + .claude/rules + README
  stage       (--stage) every path referenced by files IN the stage exists IN the stage
"""
import argparse
import glob as globmod
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEV_READ_ORDER = ("DIRECTORY.md", "framework/STATUS.md", "framework/PLAN-OF-RECORD.md")
ROUTING_DOCS = ("CLAUDE.md", "AGENTS.md", "README.md", "PRODUCT-CONTRACT.md")
STEPCOUNT_DOCS = ROUTING_DOCS + ("ORCHESTRATION.md", "shared/agent/ORCHESTRATION.md",
                                 "framework/STATUS.md", "workflow/WORKFLOW.md", "DIRECTORY.md")
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
                 # compiled-on-host build products (their build scripts ship instead):
                 "rjr_resolve", "pythia_shower", "pythia_shower_merged"}


def _runtime_or_pattern(tok, root):
    t = tok.rstrip("/")
    if t.startswith("."):                                   # pure extension mention: `.mg5`
        return True
    if tok.endswith("/") and "/" not in t:                  # run-dir convention: `plots/`, `inputs/`
        return True
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


def _resolve(tok, base_dirs, root=None):
    """A ref counts as existing if any brace-variant resolves (file/dir/glob) from ANY base,
    or -- for a bare filename / unresolved relative ref -- its basename exists in the tree."""
    for var in _expand_braces(tok.rstrip("/")):
        for base in base_dirs:
            cand = os.path.normpath(os.path.join(base, var))
            if os.path.exists(cand):
                return True
            if any(ch in var for ch in "*?") and globmod.glob(cand):
                return True
    if root is not None:
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


# Paths deliberately ABSENT from the distribution export (dev-only records/ops; see
# export_distribution.sh). In a tree WITHOUT the dev sentinel (ORCHESTRATION.md at root — i.e.
# a public clone / staged export), shipped docs may cite them as dev-side provenance without
# making them routes; the refs gate skips them there instead of failing (2026-07-30 audit).
DEV_ONLY_REFS = ("ORCHESTRATION.md", "OPS-PUBLISHING.md", "OPTION-C-DESIGN.md", "SESSIONS/")


def check_refs(root, files, label):
    """Every path-like backticked ref in `files` must exist under `root` (or doc-relative).
    In STAGE mode, glob refs are POLICY-pattern mentions (quarantine rules naming dev-only
    namespaces) — not routes — and are skipped."""
    missing = []
    stage_mode = label == "stage"
    dist_tree = not os.path.exists(os.path.join(root, "ORCHESTRATION.md"))
    for f in files:
        try:
            txt = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fdir = os.path.dirname(f)
        # workflow docs use workflow-relative refs (checklists/x.md); skills use repo-relative;
        # also accept one level up (workflow/analysis-simpleanalysis uses ../)
        bases = (root, fdir, os.path.dirname(fdir))
        for tok in set(REF_RE.findall(txt)):
            if not _is_pathlike(tok) or _runtime_or_pattern(tok, root):
                continue
            if stage_mode and any(ch in tok for ch in "*?"):
                continue
            if dist_tree and any(d in tok for d in DEV_ONLY_REFS):
                continue
            if not _resolve(tok, bases, root=root):
                missing.append(f"{os.path.relpath(f, root)}: `{tok}`")
    return missing if not missing else [f"[{label}] missing: {m}" for m in sorted(missing)]


def check_fork(root):
    errs = []
    docs = {}
    for name in ("CLAUDE.md", "AGENTS.md"):
        p = os.path.join(root, name)
        if not os.path.exists(p):
            errs.append(f"{name} missing")
            continue
        docs[name] = open(p, encoding="utf-8").read()
    for name, txt in docs.items():
        if "workflow/INITIATE.md" not in txt:
            errs.append(f"{name}: physicist route does not name workflow/INITIATE.md")
        idx = [txt.find(x) for x in DEV_READ_ORDER]
        if any(i < 0 for i in idx):
            miss = [x for x, i in zip(DEV_READ_ORDER, idx) if i < 0]
            errs.append(f"{name}: dev read order missing {miss} "
                        f"(canonical: {' -> '.join(DEV_READ_ORDER)})")
        elif idx != sorted(idx):
            errs.append(f"{name}: dev read order out of canonical order "
                        f"{' -> '.join(DEV_READ_ORDER)}")
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


def check_dirmap(root):
    """DIRECTORY.md is SECTIONED: '## `workflow/` ...' headers set the base its rows are
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
        toks = [t for t in REF_RE.findall(cell) if _is_pathlike(t)]
        if not toks:
            toks = [t for t in re.split(r"[`\s+]+", cell) if t and _is_pathlike(t)]
        if not toks:
            bare = cell.strip("`").strip()
            if bare and os.path.exists(os.path.join(root, base, bare)):
                mapped.add(bare.split("/", 1)[0] if not base else base)  # extension-less row: LICENSE
            continue
        planned = "(planned)" in line
        for tok in toks:
            mapped.add(os.path.join(base, tok).split("/", 1)[0] if not base else base)
            if planned:
                continue
            bases = (os.path.join(root, base) if base else root, root)
            if not _resolve(tok, bases, root=root):
                # distribution tree (no dev sentinel): the map documents the FULL project
                # incl. dev-side records a clone deliberately lacks — warn, don't fail (2026-07-30)
                if not os.path.exists(os.path.join(root, "ORCHESTRATION.md")):
                    warns.append(f"DIRECTORY.md [{base or 'root'}] row is dev-only (not shipped): {tok}")
                else:
                    errs.append(f"DIRECTORY.md [{base or 'root'}] row not on disk: {tok}")
    # inverse: unmapped top-level entries (WARN — directory-keeper's job)
    for e in sorted(os.listdir(root)):
        if e.startswith(".") or e in ("__pycache__", "py.py", "parser.out"):  # gitignored scratch
            continue
        if e not in mapped:
            warns.append(f"top-level {e} has no DIRECTORY.md row")
    return errs, warns


def check_readiness(root):
    """Assert every CURRENT readiness claim equals AUDIT.md's headline. Keyed to the labeled
    claim forms only — session-log HISTORY lines ('audit 96%→100%') are records, not claims."""
    audit = os.path.join(root, "framework", "AUDIT.md")
    if not os.path.exists(audit):
        return ["framework/AUDIT.md missing"]
    m = re.search(r"readiness\s*·\s*(\d+)%", open(audit, encoding="utf-8").read())
    if not m:
        return ["framework/AUDIT.md carries no 'readiness · N%' headline"]
    truth = m.group(1)
    claim_res = (re.compile(r"^\s*-?\s*\*\*Audit:\s*(\d+)%", re.M),      # STATUS.md state board
                 re.compile(r"AUDIT\.md`?\s*[,(]?\s*\*\*(\d+)%\*\*"),    # README/CLAUDE inline
                 re.compile(r"currently\s*\*\*(\d+)%\*\*"))              # DIRECTORY/WORKFLOW form
    errs = []
    for rel in ("README.md", "framework/STATUS.md", "DIRECTORY.md", "CLAUDE.md",
                "workflow/WORKFLOW.md"):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        for rx in claim_res:
            for got in rx.findall(txt):
                if got != truth:
                    errs.append(f"{rel}: claims {got}% but framework/AUDIT.md says {truth}%")
    return errs


# ---------------------------------------------------------------------------
# statefresh (Task 2B, CR-036): the reconciliation-ENFORCEMENT gate.
#
# check_readiness above catches only one headline % in a fixed label set. statefresh replaces it
# as the registered check: it re-derives the matrix truth LIVE (never from the possibly-stale
# committed AUDIT.md — same technique as framework/gen_status.py), then asserts (1) the
# gen_status.py generated blocks are fresh, (2) every served/partial/unbuilt/readiness/R9
# number quoted in the CURRENT-CLAIM docs matches that truth, and (3) no forbidden stale-claim
# phrasing survives once its matrix guard has flipped true. Dated HISTORY is exempt by
# construction (file scope + line-level exemptions below) — the CRITICAL requirement: a gate
# that cries wolf on legitimate history gets disabled, which is worse than no gate at all.
# ---------------------------------------------------------------------------

# The CURRENT-CLAIM surface: prose here is a live assertion about pipeline state and must
# reconcile to capability-matrix.json. Deliberately EXCLUDES history/records (session logs,
# overnight-roadmap ledgers, interrogation reports, SESSIONS/*) — those are records of what WAS
# true, not claims about what IS true.
STATEFRESH_FILES = (
    "framework/STATUS.md", "README.md", "framework/KNOWN-LIMITATIONS.md", "CLAUDE.md",
    "DIRECTORY.md", "PRODUCT-CONTRACT.md", "workflow/steps/04-analyze.md",
    "workflow/reference/projection-replane.md", "workflow/reference/effmap-folding.md",
    "framework/DECISION-SHAPE-FIT.md",
)
# Intent/roadmap docs get only the light stamp check (they narrate INTENT/SEQUENCING, not
# current claims — CAPABILITY-ROADMAP.md/PLAN-OF-RECORD.md deliberately keep costed alternatives
# and superseded plans in prose).
STATEFRESH_ROADMAP_FILES = ("framework/CAPABILITY-ROADMAP.md", "framework/PLAN-OF-RECORD.md")

_SF_DATED_BULLET_RE = re.compile(r"^\s*[-*]\s*\*{0,2}\d{4}-\d{2}-\d{2}")
_SF_NEW_BULLET_RE = re.compile(r"^\s*[-*]\s")
_SF_HISTORY_MARK_RE = re.compile(r"\(historical\)|SUPERSEDED|kept for the record")
_SF_MARKER_BEGIN_RE = re.compile(r"<!-- CAPABILITY-STATUS:(\S+?):BEGIN")
_SF_MARKER_END_RE = re.compile(r"<!-- CAPABILITY-STATUS:(\S+?):END -->")
# a match immediately preceded by a negation ("NO LONGER a blanket refusal") asserts the
# OPPOSITE of the forbidden claim and must not fire — e.g. PRODUCT-CONTRACT.md's own §6 lede.
_SF_NEGATION_RE = re.compile(r"no longer", re.I)


def _statefresh_guarded_lines(path, rel):
    """Yield (1-indexed lineno, line) for every line in `path` that is IN SCOPE for Parts 2/3:
    not inside a <!-- CAPABILITY-STATUS:*:BEGIN/END --> marker block (Part 1 governs those —
    they are authoritative by construction), not in STATUS.md's '## Session log' region, not
    under a dated bullet (`- 2026-07-06 ...` and its indented wrapped-sentence continuation
    lines), and not carrying a (historical)/SUPERSEDED/kept-for-the-record marker."""
    text = open(path, encoding="utf-8", errors="replace").read()
    in_marker = False
    dated_block = False
    session_log = False
    is_status_board = rel.endswith("STATUS.md")
    for i, line in enumerate(text.split("\n"), 1):
        if is_status_board:
            if re.match(r"^#{2,3}\s+Session log", line):
                session_log = True
            elif re.match(r"^#{1,3}\s+", line) or line.strip() == "---":
                session_log = False
        if _SF_MARKER_BEGIN_RE.search(line):
            in_marker = True
        if not line.strip():
            dated_block = False                              # blank line ends a list block
        elif _SF_NEW_BULLET_RE.match(line):
            dated_block = bool(_SF_DATED_BULLET_RE.match(line))
        exempt = in_marker or session_log or dated_block or _SF_HISTORY_MARK_RE.search(line)
        if _SF_MARKER_END_RE.search(line):
            in_marker = False
        if not exempt:
            yield i, line


def _matrix_truths(root):
    """The matrix-derived truth, computed LIVE — mirrors framework/gen_status.py's own
    technique exactly (import framework/audit.py for readiness/R9; read capability-matrix.json
    directly for the per-prompt/per-capability buckets) so statefresh can never disagree with
    gen_status.py about what 'fresh' means. Returns None if either input is unavailable."""
    fw = os.path.join(root, "framework")
    matrix_path = os.path.join(fw, "capability-matrix.json")
    if not os.path.exists(matrix_path):
        return None
    try:
        matrix = json.loads(open(matrix_path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None
    if not os.path.exists(os.path.join(fw, "audit.py")):
        return None
    if fw not in sys.path:
        sys.path.insert(0, fw)
    import audit  # framework/audit.py — stdlib-only, read-only (same import gen_status.py does)
    rows = [f() for f in audit.CHECKS]
    if not rows:
        return None
    readiness = round(100 * sum(r[2] for r in rows) / len(rows))
    r9 = next((r for r in rows if r[0] == "R9"), None)
    if r9 is None:
        return None
    r9_score, r9_status = r9[2], r9[3]
    prompts = matrix.get("prompts", {})
    full, partial_st, unbuilt_st = ("served", "served-with-refusal"), ("partial",), \
        ("unbuilt", "decision-pending")
    served = sum(1 for v in prompts.values() if v.get("status") in full)
    partial = sum(1 for v in prompts.values() if v.get("status") in partial_st)
    unbuilt = sum(1 for v in prompts.values() if v.get("status") in unbuilt_st)
    caps = matrix.get("capabilities", {})
    built_caps = {k for k, v in caps.items() if v.get("status") == "built"}
    return {
        "matrix": matrix, "readiness": readiness, "r9_score": r9_score, "r9_status": r9_status,
        "served": served, "partial": partial, "unbuilt": unbuilt, "built_caps": built_caps,
        "prompts": prompts,
    }


def check_statefresh_part1(root):
    """Part 1 — block freshness: `python3 framework/gen_status.py --check` must exit 0 (every
    generated block is fresh vs capability-matrix.json)."""
    gen_status = os.path.join(root, "framework", "gen_status.py")
    if not os.path.exists(gen_status):
        return ["framework/gen_status.py missing"]
    proc = subprocess.run([sys.executable, gen_status, "--check"], cwd=root,
                           capture_output=True, text=True)
    if proc.returncode == 0:
        return []
    diff = (proc.stdout + proc.stderr).strip()
    return [f"gen_status.py --check FAIL (generated blocks stale vs capability-matrix.json):\n"
            f"{diff}"]


# Part 2 — count/number consistency (CURRENT-CLAIM scope only). Patterns beyond the % form are
# additive to check_readiness's existing comparison (kept, called separately in check_statefresh).
_SF_READY_PATTERNS = (
    re.compile(r"readiness\s*[·:]?\s*(\d+)%", re.I),
    re.compile(r"\*\*Audit:\s*(\d+)%"),
    re.compile(r"AUDIT\.md[^%]{0,20}\*\*(\d+)%"),
    re.compile(r"headline\s+(\d+)%", re.I),
)
_SF_SERVED_RE = re.compile(r"(\d+)\s*/\s*7\s+(?:fully\s+)?served", re.I)
_SF_PARTIAL_RE = re.compile(r"(\d+)\s+partial\b", re.I)
_SF_UNBUILT_RE = re.compile(r"(\d+)\s+unbuilt\b", re.I)
_SF_NEAR_RE = re.compile(r"/7|prompt|board", re.I)
_SF_R9_STATUS_RE = re.compile(r"R9\s+(WARN|PASS|FAIL)")
_SF_R9_SCORE_RE = re.compile(r"R9[^0-9]{0,12}(\d\.\d{1,2})")


def _statefresh_num_mismatches(line, truths):
    """Yield (found, expected, field) for every Part-2 numeric claim on `line` that disagrees
    with the matrix-derived truth."""
    for m in _SF_SERVED_RE.finditer(line):
        got = int(m.group(1))
        if got != truths["served"]:
            yield (str(got), str(truths["served"]), "served count")
    if _SF_NEAR_RE.search(line):
        for m in _SF_PARTIAL_RE.finditer(line):
            got = int(m.group(1))
            if got != truths["partial"]:
                yield (str(got), str(truths["partial"]), "partial count")
        for m in _SF_UNBUILT_RE.finditer(line):
            got = int(m.group(1))
            if got != truths["unbuilt"]:
                yield (str(got), str(truths["unbuilt"]), "unbuilt count")
    for pat in _SF_READY_PATTERNS:
        for m in pat.finditer(line):
            got = int(m.group(1))
            if got != truths["readiness"]:
                yield (str(got), str(truths["readiness"]), "readiness %")
    for m in _SF_R9_STATUS_RE.finditer(line):
        got = m.group(1)
        if got != truths["r9_status"]:
            yield (got, truths["r9_status"], "R9 status")
    for m in _SF_R9_SCORE_RE.finditer(line):
        got = m.group(1)
        decimals = len(got.split(".")[1])
        expected = round(truths["r9_score"], decimals)
        if abs(float(got) - expected) > 1e-9:
            yield (got, f"{truths['r9_score']:.2f}", "R9 score")


def check_statefresh_counts(root, truths):
    """Part 2 — every served/partial/unbuilt/readiness%/R9 number quoted in a CURRENT-CLAIM doc
    (outside history/marker exemptions) must equal the live matrix-derived truth."""
    errs = []
    for rel in STATEFRESH_FILES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        for lineno, line in _statefresh_guarded_lines(path, rel):
            for got, expected, field in _statefresh_num_mismatches(line, truths):
                errs.append(f"{rel}:{lineno}: claims {field}={got!r} but the matrix says "
                            f"{expected!r} — {line.strip()[:120]!r}")
    return errs


# Part 3 — forbidden-contradiction prose (regex -> matrix guard). Each rule fires only when its
# matrix guard is currently true AND its pattern (with the optional same-line context) matches an
# in-scope line. `guard(truths, ctx_text)` receives the matched context substring (needed only by
# unbuilt-word, whose guard depends on WHICH capability name matched).
def _sf_cap_for_context(text):
    """Map an unbuilt-word context match ('G2b', 'shape-fit', 'effmap', ...) to its matrix
    capability key. Uses the ACTUAL matrix keys (read from capability-matrix.json's own schema,
    not hardcoded guesses)."""
    t = text.lower()
    for prefix, key in (("g1", "G1_summary_track"), ("g2a", "G2a_effmap_folding"),
                        ("g2b", "G2b_shape_fit"), ("g2c", "G2c_projection"),
                        ("g2d", "G2d_replane"), ("g4", "G4_basis_manifest"),
                        ("g5", "G5_trap_sweep"), ("g6", "G6_ladder")):
        if t.startswith(prefix):
            return key
    if t.startswith("summary"):
        return "G1_summary_track"
    if t.startswith("effmap"):
        return "G2a_effmap_folding"
    if re.match(r"shape.?fit", t):
        return "G2b_shape_fit"
    if t.startswith("projection"):
        return "G2c_projection"
    if t.startswith("replane"):
        return "G2d_replane"
    return None


CONTRADICTION_RULES = (
    dict(id="sf-blocked",
         pattern=re.compile(r"paradigm[- ]?blocked|NAMED refusal|blanket refusal|"
                            r"(?:binned )?shape[- ]?fits?[^.]*Phase-?2|Phase-?2\s+scope", re.I),
         context=re.compile(r"shape[-/ ]?fit|shape/template|bump|binned", re.I),
         guard=lambda t, ctx: (t["prompts"].get("P4_dijet_photon_widths", {}).get("status")
                               in ("served", "served-with-refusal")
                               or "G2b_shape_fit" in t["built_caps"]),
         rationale="shape-fit is a served engine now"),
    dict(id="sf-active-build",
         pattern=re.compile(r"execution tracks?[^.]*active build|capability layer\s+unbuilt", re.I),
         context=None,
         guard=lambda t, ctx: any(c in t["built_caps"] for c in
                                  ("G1_summary_track", "G2a_effmap_folding", "G2b_shape_fit",
                                   "G2c_projection", "G2d_replane")),
         rationale="those tracks are built"),
    dict(id="proj-next-session",
         pattern=re.compile(r"SPEC'D[^.]*build\s*=\s*next|build\s*=\s*next session|next session",
                            re.I),
         context=re.compile(r"projection|replane|G2c|G2d", re.I),
         guard=lambda t, ctx: ("G2c_projection" in t["built_caps"]
                               and "G2d_replane" in t["built_caps"]),
         rationale="built, not next-session"),
    dict(id="d2-design",
         pattern=re.compile(r"D2\s*\((?:design|spec)\)|D2[^.\n]*\bdesign\b"),
         context=None,
         guard=lambda t, ctx: "G2a_effmap_folding" in t["built_caps"],
         rationale="D2 is built"),
    dict(id="decision-pending",
         pattern=re.compile(r"DECISION PENDING[^.]*nothing[^.]*built|nothing below is built",
                            re.I),
         context=None,
         guard=lambda t, ctx: "G2b_shape_fit" in t["built_caps"],
         rationale="signed + built"),
    dict(id="unbuilt-word",
         pattern=re.compile(r"\bunbuilt\b|not yet built", re.I),
         context=re.compile(r"G1\b|G2[abcd]\b|G4\b|G5\b|G6\b|summary|effmap|shape.?fit|"
                            r"projection|replane", re.I),
         guard=lambda t, ctx: bool(ctx) and _sf_cap_for_context(ctx) in t["built_caps"],
         rationale='"unbuilt" on a built capability'),
)


def check_statefresh_contradictions(root, truths):
    """Part 3 — forbidden stale-claim phrasing whose matrix guard is currently true."""
    errs = []
    for rel in STATEFRESH_FILES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        for lineno, line in _statefresh_guarded_lines(path, rel):
            for rule in CONTRADICTION_RULES:
                for m in rule["pattern"].finditer(line):
                    ctx_text = None
                    if rule["context"] is not None:
                        cm = rule["context"].search(line)
                        if not cm:
                            continue
                        ctx_text = cm.group(0)
                    if not rule["guard"](truths, ctx_text):
                        continue
                    window = line[max(0, m.start() - 25):m.start()]
                    if _SF_NEGATION_RE.search(window):
                        continue                             # "NO LONGER a blanket refusal" etc.
                    errs.append(f"{rel}:{lineno} [{rule['id']}]: {rule['rationale']} — "
                                f"{line.strip()[:140]!r}")
    return errs


_SF_STAMP_RE = re.compile(r"LAST-RECONCILED-AGAINST:\s*capability-matrix\.json@(\d{4}-\d{2}-\d{2})")


def check_statefresh_roadmap_stamp(root, truths):
    """Intent/roadmap docs get a LIGHT check only: the reconciliation stamp must exist, and if
    the matrix moved on since it was stamped, the body must not still carry a bare (undated)
    contradiction token."""
    errs = []
    matrix_updated = truths["matrix"].get("updated", "")
    for rel in STATEFRESH_ROADMAP_FILES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        m = _SF_STAMP_RE.search(text)
        if not m:
            errs.append(f"{rel}: missing '<!-- LAST-RECONCILED-AGAINST: "
                        f"capability-matrix.json@YYYY-MM-DD -->' stamp")
            continue
        if matrix_updated and matrix_updated > m.group(1):
            for lineno, line in _statefresh_guarded_lines(path, rel):
                for rule in CONTRADICTION_RULES:
                    if rule["pattern"].search(line):
                        errs.append(f"{rel}:{lineno}: stamp @{m.group(1)} predates matrix update "
                                    f"{matrix_updated} and still carries a contradiction token: "
                                    f"{line.strip()[:100]!r}")
    return errs


def check_statefresh(root):
    """The composed statefresh guard: Parts 1-3 + the roadmap stamp check + (kept, per the
    task spec) the old %-only comparison against the committed AUDIT.md headline."""
    errs = list(check_statefresh_part1(root))
    truths = _matrix_truths(root)
    if truths is None:
        errs.append("framework/capability-matrix.json or framework/audit.py unavailable — "
                    "cannot compute the matrix-derived truth for Parts 2/3")
        return errs
    errs.extend(check_readiness(root))
    errs.extend(check_statefresh_counts(root, truths))
    errs.extend(check_statefresh_contradictions(root, truths))
    errs.extend(check_statefresh_roadmap_stamp(root, truths))
    return errs


def check_stepcount(root):
    steps = globmod.glob(os.path.join(root, "workflow", "steps", "[0-9]*.md"))
    n = len(steps)
    if n == 0:
        return [f"no workflow/steps/*.md found under {root}"]
    errs = []
    for rel in STEPCOUNT_DOCS:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        for m in re.finditer(r"\b(\d+)\s+steps?\b(?!-)", open(p, encoding="utf-8").read()):
            if int(m.group(1)) not in (n,):
                errs.append(f"{rel}: says '{m.group(0)}' but workflow/steps has {n} files")
    return errs


def check_hygiene(root):
    errs = []
    files = _md_files(root, ("workflow", ".claude/skills", ".claude/rules", "README.md"))
    for f in files:
        if os.path.basename(f) == "DISTRIBUTION.md":
            continue
        for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
            if HYGIENE_TOKENS.search(line) and not HYGIENE_ALLOW.search(line):
                errs.append(f"{os.path.relpath(f, root)}:{i}: dev trial-run token: "
                            f"{line.strip()[:80]}")
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", help="ALSO check a staged export tree for dead refs")
    args = ap.parse_args()

    results = []  # (name, errs, warns)
    results.append(("fork", check_fork(REPO), []))
    ref_files = _md_files(REPO, ("workflow", ".claude/skills")) + [
        os.path.join(REPO, r) for r in ROUTING_DOCS if os.path.exists(os.path.join(REPO, r))]
    results.append(("refs", check_refs(REPO, ref_files, "dev"), []))
    results.append(("skills", check_skills(REPO), []))
    results.append(("mirror", check_mirror(REPO), []))
    dm_errs, dm_warns = check_dirmap(REPO)
    results.append(("dirmap", dm_errs, dm_warns))
    results.append(("statefresh", check_statefresh(REPO), []))
    results.append(("stepcount", check_stepcount(REPO), []))
    results.append(("hygiene", check_hygiene(REPO), []))
    if args.stage:
        # DIRECTORY.md + STATUS.md ship but describe dev-repo content with explicit annotations —
        # they are maps, not routes; the ROUTE surfaces must be dead-ref-free in the stage.
        st = os.path.abspath(args.stage)
        st_files = [f for f in _md_files(st, ("workflow", ".claude/skills"))
                    if os.path.basename(f) != "DISTRIBUTION.md"] + [
            os.path.join(st, r) for r in ROUTING_DOCS
            if os.path.exists(os.path.join(st, r))]  # DISTRIBUTION.md names dev-only rows by design
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
    print(f"\nagent surface: {'FAIL' if any_fail else 'OK'}")
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
