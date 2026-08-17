#!/usr/bin/env bash
# export_distribution.sh — build the DISTRIBUTABLE subset of hep-agentic-pipeline as a clean tree,
# sanitize it, hygiene-check it, and (optionally) push it to the colleague-facing remote.
#
# Policy source: workflow/DISTRIBUTION.md (this script implements EXACTLY its tables).
#   PUBLISHABLE : workflow/  trial-runs/_infrastructure/  pedagogical/ (minus design-review)
#                 framework/ selected rows (incl. CAPABILITY-ROADMAP/OPERABILITY-CHARTER/
#                 DECISION-SHAPE-FIT/capability-matrix.json/LIMITATIONS-TRIAGE)
#                 PRODUCT-CONTRACT.md  README  CITATION.cff  LICENSE  DIRECTORY.md  AGENTS.md
#                 shared/  stages/01-event-generation/{README,scripts,changes,docs} (agent/ stays
#                 dev-only)  .claude/{skills,rules,agents}  .agents/ (the scaffolding IS the
#                 product)  evidence_manifest.json + EVIDENCE.md (CR-030/CR-042 evidence pack)
#                 + a curated evidence subset (explicit files, NOT whole run dirs) from 3
#                 trial-runs/ run dirs backing the served claims -- see "1b." below
#   DEV-ONLY    : trial-runs run records (minus the curated subset above)  SESSIONS/
#                 ORCHESTRATION.md  framework/{overnight*,OPTION-C-DESIGN,TRIAL-*,OPS-PUBLISHING}
#                 stages build/  .claude/hooks+settings (operator/machine-specific)
#   GATE        : after assembly, framework/check_evidence.py --check --root <stage> re-verifies
#                 every served claim's shipped artifact against the ACTUAL staged files (sha256) --
#                 the export aborts (no push) if any is missing or mismatched (PRODUCT-CONTRACT
#                 sec 7 / CR-030)
#   SANITIZE    : CLAUDE.md (absolute /Users/... paths -> $DSRLAB_ROOT); LICENSE/CITATION
#                 placeholders FAIL LOUD unless --allow-placeholder-license
#
# The export is REPEATABLE: run it again after workflow changes and push the refreshed tree.
# Fail-loud: any sanitization or hygiene failure aborts before anything leaves the machine.
#
# Usage:
#   export_distribution.sh <staging-dir> [--allow-placeholder-license]   # build + verify
#   export_distribution.sh <staging-dir> [--allow-placeholder-license] --push <remote>
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"  # repo root (location-relative)
STAGE="${1:?usage: export_distribution.sh <staging-dir> [--allow-placeholder-license] [--push <remote-url>]}"
shift
ALLOW_PLACEHOLDER=0; PUSH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-placeholder-license) ALLOW_PLACEHOLDER=1; shift;;
    --push) PUSH="${2:?--push needs a remote url}"; shift 2;;
    --self-url) SELF_URL="${2:?--self-url needs a repo url}"; shift 2;;
    *) echo "unknown arg: $1"; exit 64;;
  esac
done
# leak pattern derived at runtime (the operator's home prefix): no username literal ships in
# the exported copy of THIS script, and the check still catches any home-rooted absolute path.
LEAK="$HOME"

echo "== 1. assemble the publishable subset -> $STAGE"
rm -rf "$STAGE"; mkdir -p "$STAGE"
rsync -a --exclude='__pycache__' --exclude='.DS_Store' --exclude='logs' \
  "$REPO/workflow" "$STAGE/"
rsync -a --exclude='__pycache__' --exclude='.DS_Store' --exclude='logs' --exclude='pythia_shower' \
  --exclude='pythia_shower_merged' --exclude='rjr_resolve' \
  "$REPO/trial-runs/_infrastructure" "$STAGE/trial-runs/"
rsync -a --exclude='design-review' --exclude='*.aux' --exclude='*.log' --exclude='*.out' \
  --exclude='*.fls' --exclude='*.fdb_latexmk' --exclude='*.synctex.gz' --exclude='*.toc' \
  --exclude='.DS_Store' \
  "$REPO/pedagogical" "$STAGE/"
# framework: protocol + audit + benchmark + validation, NOT the dev-narrative dirs
mkdir -p "$STAGE/framework"
for f in PLAN-OF-RECORD.md STATUS.md AUDIT.md audit.py KNOWN-LIMITATIONS.md ENVIRONMENT.md \
         CHANGES-REGISTRY.md FAILURE-CATALOGUE.md AUDIT-OPERABILITY.md ROUTING-EVALS.md \
         CAPABILITY-ROADMAP.md capability-matrix.json LIMITATIONS-TRIAGE.md \
         DECISION-SHAPE-FIT.md OPERABILITY-CHARTER.md \
         green_board.py gen_status.py check_evidence.py build_evidence.py verify_fixes.py; do
  [ -f "$REPO/framework/$f" ] && cp "$REPO/framework/$f" "$STAGE/framework/"
done
# the SPINE itself (gate tools the spine_sim cases drive + the tests exercise)
[ -d "$REPO/framework/spine" ] && rsync -a --exclude='__pycache__' --exclude='.DS_Store' \
  "$REPO/framework/spine" "$STAGE/framework/"
# tests + spine_sim SHIP (2026-07-30 policy change, repo-audit spec: the verification surface IS
# the credibility artifact — an engineer must be able to clone and run the 344-test suite + the
# 30-case adversarial gate board; live-state pins auto-skip outside the dev repo via conftest)
for d in benchmark validation crosscheck interrogations tests spine_sim; do
  [ -d "$REPO/framework/$d" ] && rsync -a --exclude='.work' --exclude='__pycache__' \
    --exclude='.DS_Store' --exclude='.pytest_cache' "$REPO/framework/$d" "$STAGE/framework/"
done
for f in README.md CITATION.cff LICENSE DIRECTORY.md AGENTS.md PRODUCT-CONTRACT.md \
         evidence_manifest.json EVIDENCE.md Makefile THIRD_PARTY.md requirements-replay.txt \
         NOTICE CHANGELOG.md; do
  [ -f "$REPO/$f" ] && cp "$REPO/$f" "$STAGE/"
done
# the evidence layer + CI (repo-audit spec E1/E2/E3/C1): claims manifest, claim-check + page
# generators, validation pages + case studies, and the workflow definitions
for d in results docs scripts .github; do
  [ -d "$REPO/$d" ] && rsync -a --exclude='__pycache__' --exclude='.DS_Store' \
    --exclude='superpowers' "$REPO/$d" "$STAGE/"   # docs/superpowers = dev planning material
done
# DIRECTORY.md maps the FULL research repo; tag rows whose paths are dev-only so a cold reader
# is never sent hunting for files this snapshot deliberately omits (coldread 2026-08-16).
python3 - "$STAGE" << 'PYD'
import os, re, sys
stage = sys.argv[1]
p = os.path.join(stage, "DIRECTORY.md")
out, tagged = [], 0
for line in open(p).read().splitlines():
    m = re.match(r"^\| `([^`]+)`", line)
    if m and line.count("|") >= 3 and "dev repo only" not in line:
        tok = m.group(1).split()[0].rstrip("/")
        if not os.path.exists(os.path.join(stage, tok)):
            line = re.sub(r"\s*\|\s*$", " *(dev repo only — not in this snapshot)* |", line)
            tagged += 1
    out.append(line)
if tagged and "full map of the research repository" not in out[2]:
    for i, l in enumerate(out):
        if l.startswith("# "):
            out.insert(i + 1, "\n> This is the full map of the research repository; rows tagged"
                              " *(dev repo only)* describe files kept in the private working tree"
                              " and deliberately absent from this public snapshot.")
            break
open(p, "w").write("\n".join(out) + "\n")
print(f"   DIRECTORY.md: {tagged} dev-only rows tagged")
PYD
# orientation/conventions + the environment bootstrap (shipped step 01 needs the scripts tree)
rsync -a --exclude='.DS_Store' "$REPO/shared" "$STAGE/"
mkdir -p "$STAGE/stages/01-event-generation"
[ -f "$REPO/stages/01-event-generation/README.md" ] && \
  cp "$REPO/stages/01-event-generation/README.md" "$STAGE/stages/01-event-generation/"
for d in scripts changes docs; do   # agent/ = the superseded per-stage scaffolding, dev-only
  [ -d "$REPO/stages/01-event-generation/$d" ] && \
    rsync -a --exclude='.DS_Store' "$REPO/stages/01-event-generation/$d" "$STAGE/stages/01-event-generation/"
done
# the agent scaffolding IS the product: skills + rules + the ENFORCEMENT LAYER ship
# (2026-07-30 policy change: hooks + settings are the approval/self-protection gates the README
# and the enforcement tests describe — a clone without them cannot run the advertised guarantees;
# they are sanitized like everything else and carry no personal data)
mkdir -p "$STAGE/.claude"
rsync -a --exclude='__pycache__' --exclude='.DS_Store' "$REPO/.claude/skills" "$STAGE/.claude/"
rsync -a "$REPO/.claude/rules" "$STAGE/.claude/"
rsync -a --exclude='.DS_Store' "$REPO/.claude/agents" "$STAGE/.claude/"
rsync -a --exclude='.DS_Store' "$REPO/.claude/hooks" "$STAGE/.claude/"
[ -f "$REPO/.claude/settings.json" ] && cp "$REPO/.claude/settings.json" "$STAGE/.claude/"
rsync -a --exclude='.DS_Store' "$REPO/.agents" "$STAGE/"

echo "== 1b. ship the curated EVIDENCE subset (served-claim artifacts, see evidence_manifest.json) --"
echo "       an explicit file list per run, NOT the whole run dirs (those stay dev-only)"
# flagship scan: trial-runs/sleptonscan_fig3_SCAN -- backs HEADLINE_fig3_scan_same_basis_residual
SCANSRC="$REPO/trial-runs/sleptonscan_fig3_SCAN"; SCANDST="$STAGE/trial-runs/sleptonscan_fig3_SCAN"
mkdir -p "$SCANDST/inputs" "$SCANDST/plots"
for f in scan.json scan_manifest.json RESULT.md verification.json; do
  [ -f "$SCANSRC/$f" ] && cp "$SCANSRC/$f" "$SCANDST/"
done
cp "$SCANSRC"/inputs/*.json "$SCANDST/inputs/" 2>/dev/null || true
cp "$SCANSRC"/plots/*.png "$SCANSRC"/plots/*.pdf "$SCANDST/plots/" 2>/dev/null || true

# native slepton 200/150 point: trial-runs/2026-06-16_slepton_200-150_native/output --
# backs HEADLINE_native_141_bitforbit / HEADLINE_native_mu95_0p51pct
NATSRC="$REPO/trial-runs/2026-06-16_slepton_200-150_native/output"
NATDST="$STAGE/trial-runs/2026-06-16_slepton_200-150_native/output"
mkdir -p "$NATDST"
for f in exclusion.json EwkCompressed2018.txt; do
  [ -f "$NATSRC/$f" ] && cp "$NATSRC/$f" "$NATDST/"
done
cp "$NATSRC"/*_patch.json "$NATDST/" 2>/dev/null || true

# CR-004 paired-rescan SUMMARY (the README's +6.5% PDF-term statement + the scan_scale claim's
# second manifest): curated top-level artifacts only, no per-point dirs.
RSSRC="$REPO/trial-runs/CR004rescan_SCAN"; RSDST="$STAGE/trial-runs/CR004rescan_SCAN"
mkdir -p "$RSDST/plots"
for f in scan_manifest.json scan.json CR004-FULL-RESULT.md; do
  [ -f "$RSSRC/$f" ] && cp "$RSSRC/$f" "$RSDST/"
done
cp "$RSSRC"/plots/*.png "$RSDST/plots/" 2>/dev/null || true

# REPLAY-MODE bundle (spec E4 / README quickstart): the benchmark FAST case's cached inputs so
# `make replay` re-fits a real published benchmark through pyhf on a fresh clone (<1MB total).
FASTSRC="$REPO/trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-pair"
FASTDST="$STAGE/trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-pair"
mkdir -p "$FASTDST/outputs/pyhf_exclusion" \
         "$FASTDST/plots/ATLAS_2016_I1458270/named"
for f in RESULT.md provenance.json; do
  [ -f "$FASTSRC/$f" ] && cp "$FASTSRC/$f" "$FASTDST/"
done
for f in sr_yields_fitted.json sr_yields.json squark.yoda; do
  [ -f "$FASTSRC/outputs/$f" ] && cp "$FASTSRC/outputs/$f" "$FASTDST/outputs/"
done
cp "$FASTSRC/outputs/pyhf_exclusion/exclusion.json" "$FASTDST/outputs/pyhf_exclusion/" 2>/dev/null || true
cp "$FASTSRC/plots/ATLAS_2016_I1458270/named/ATLAS_2016_I1458270__d04-x01-y01__meff-incl_SR-2jl.png" \
   "$FASTDST/plots/ATLAS_2016_I1458270/named/" 2>/dev/null || true
rsync -a "$FASTSRC/outputs/hepdata" "$FASTDST/outputs/"

# CR-005 ORACLE-VALIDATION evidence (the native_ported_routines claim's artifacts): per-routine
# native txt + container-oracle txt + config + STATUS logs — curated trio only, no event files.
for run in CR005_refactor_smoke CR005_c1n2_sample CR005_squark_sample; do
  mkdir -p "$STAGE/trial-runs/$run/output" "$STAGE/trial-runs/$run/config" "$STAGE/trial-runs/$run/logs"
  cp "$REPO/trial-runs/$run"/output/*.txt "$STAGE/trial-runs/$run/output/" 2>/dev/null || true
  rm -f "$STAGE/trial-runs/$run/output/native_objects.txt" 2>/dev/null   # 8MB/pt dump, not evidence
  cp "$REPO/trial-runs/$run"/config/*.toml "$STAGE/trial-runs/$run/config/" 2>/dev/null || true
  [ -f "$REPO/trial-runs/$run/logs/STATUS.txt" ] && \
    cp "$REPO/trial-runs/$run/logs/STATUS.txt" "$STAGE/trial-runs/$run/logs/"
done

# ARM64 case-study TIMING evidence (docs/arm64-case-study.md links both STATUS.txt logs):
# the per-stage timestamp logs of the emulated-container 50k run and the native 50k run.
for run in 2026-06-06_slepton_200-150_50k 2026-06-16_slepton_200-150_native; do
  mkdir -p "$STAGE/trial-runs/$run/logs"
  [ -f "$REPO/trial-runs/$run/logs/STATUS.txt" ] && \
    cp "$REPO/trial-runs/$run/logs/STATUS.txt" "$STAGE/trial-runs/$run/logs/"
  [ -f "$REPO/trial-runs/$run/RESULT.md" ] && \
    cp "$REPO/trial-runs/$run/RESULT.md" "$STAGE/trial-runs/$run/"
done

# HVT Z' -> WW low-mass summary: trial-runs/2026-07-06_SURVEY_hvt-zprime-ww-lowmass --
# backs P1_hvt_zprime_ww_summary
HVTSRC="$REPO/trial-runs/2026-07-06_SURVEY_hvt-zprime-ww-lowmass"
HVTDST="$STAGE/trial-runs/2026-07-06_SURVEY_hvt-zprime-ww-lowmass"
mkdir -p "$HVTDST/outputs" "$HVTDST/inputs" "$HVTDST/plots"
[ -f "$HVTSRC/VERIFICATION-LADDER.md" ] && cp "$HVTSRC/VERIFICATION-LADDER.md" "$HVTDST/"
for f in survey.json summary_audit.json; do
  [ -f "$HVTSRC/outputs/$f" ] && cp "$HVTSRC/outputs/$f" "$HVTDST/outputs/"
done
[ -f "$HVTSRC/inputs/basis_manifest.json" ] && \
  cp "$HVTSRC/inputs/basis_manifest.json" "$HVTDST/inputs/"
cp "$HVTSRC"/plots/hvt_zprime_ww_summary.* "$HVTDST/plots/" 2>/dev/null || true
cp "$HVTSRC"/plots/qa_*.png "$HVTDST/plots/" 2>/dev/null || true

echo "== 2. sanitize CLAUDE.md (absolute paths -> \$DSRLAB_ROOT) and include it"
sed -e "s|${LEAK}/Documents/DSRLab|\$DSRLAB_ROOT|g" "$REPO/CLAUDE.md" > "$STAGE/CLAUDE.md"

echo "== 2b. belt-and-braces: sanitize remaining absolute paths in EVERY text file (grep -I)"
# no extension list (the old 7-extension list let .cc/.txt/.dat/.cfg/.mg5 escape — audit 2026-07-30):
# grep -rIl finds every TEXT file containing the leak prefix; sed rewrites in place.
grep -rIl "$LEAK" "$STAGE" 2>/dev/null | while IFS= read -r f; do
  sed -i '' -e "s|${LEAK}/Documents/DSRLab|\$DSRLAB_ROOT|g" -e "s|${LEAK}|\$OPERATOR_HOME|g" "$f"
done

# optional: re-home every repo self-reference (badges, clone commands, links) to a different
# hosting account/repo — used for the identified public copy on the author's own account.
if [ -n "${SELF_URL:-}" ]; then
  SU="${SELF_URL%.git}"; SU="${SU#https://}"; SU="${SU#http://}"
  OLDREF="github.com/ashen""joy/hep-agentic-pipeline"
  echo "== 2c. re-home self-references -> $SU"
  grep -rIl "$OLDREF" "$STAGE" 2>/dev/null | while IFS= read -r f; do
    perl -pi -e "s{\Q$OLDREF\E}{$SU}g" "$f"
  done
fi

echo "== 3. sanitization check: NO home-rooted absolute paths may remain in ANY text file"
if grep -rIl "$LEAK" "$STAGE" 2>/dev/null | head -5 | grep -q .; then
  echo "FAIL: absolute home-rooted paths remain in:"; grep -rIl "$LEAK" "$STAGE" | head -10
  echo "Sanitize or exclude these before pushing."; exit 2
fi
echo "   clean"

echo "== 4. DISTRIBUTION hygiene grep (no dev trial-run leakage into ANY agent-facing surface)"
HYG_SCOPE=("$STAGE/workflow" "$STAGE/.claude" "$STAGE/.agents" "$STAGE/shared" "$STAGE/README.md" "$STAGE/CLAUDE.md")
if grep -rnE "gluino-pair|squark-pair|slepton_200|2026-[0-9]{2}-[0-9]{2}_|C1N2-WZ" \
     "${HYG_SCOPE[@]}" --exclude=DISTRIBUTION.md 2>/dev/null \
     | grep -vE "µ₉₅ *= *1|mu95 *= *1" | head -5 | grep -q .; then
  echo "FAIL: dev trial-run references leaked into agent-facing surfaces:"; \
  grep -rnE "gluino-pair|squark-pair|slepton_200|2026-[0-9]{2}-[0-9]{2}_|C1N2-WZ" \
    "${HYG_SCOPE[@]}" --exclude=DISTRIBUTION.md 2>/dev/null | head -10; exit 3
fi
echo "   clean"

echo "== 4b. placeholder-license guard (publication honesty)"
if grep -q "example.invalid" "$STAGE/CITATION.cff" 2>/dev/null || \
   grep -qi "to be finalized" "$STAGE/LICENSE" 2>/dev/null; then
  if [ "$ALLOW_PLACEHOLDER" = 1 ]; then
    echo "   WARNING: placeholder LICENSE/CITATION shipping (explicitly allowed by flag)"
  else
    echo "FAIL: LICENSE/CITATION still carry placeholders (example.invalid / 'to be finalized')."
    echo "Finalize them, or pass --allow-placeholder-license to ship anyway (repo is already"
    echo "public in this state — see framework/OPS-PUBLISHING.md)."; exit 5
  fi
else
  echo "   clean"
fi

echo "== 4c. staged-tree dead-reference scan (check_agent_surface --stage)"
if python3 "$REPO/trial-runs/_infrastructure/check_agent_surface.py" --stage "$STAGE" \
     | tail -3 | grep -q "agent surface: OK"; then
  echo "   clean"
else
  echo "FAIL: the staged tree has dead references or dev-tree drift:"
  python3 "$REPO/trial-runs/_infrastructure/check_agent_surface.py" --stage "$STAGE" | grep -A3 FAIL | head -20
  exit 6
fi

echo "== 4d. evidence gate: every served claim's shipped artifact must be present + sha256-matching"
echo "       in the stage (PRODUCT-CONTRACT sec 7 / CR-030) -- check_evidence.py --check --root \$STAGE"
if python3 "$REPO/framework/check_evidence.py" --check --root "$STAGE"; then
  echo "   clean"
else
  echo "FAIL: the staged export is missing, or sha-mismatches, a shipped evidence artifact -- see"
  echo "the [FAIL] rows above. Ship the missing artifact (Part A whitelist) or fix evidence_manifest.json"
  echo "(framework/build_evidence.py --write) before exporting."; exit 7
fi

echo "== 5. size guard (no blob >5MB)"
big=$(find "$STAGE" -type f -size +5M | head -5)
if [ -n "$big" ]; then echo "FAIL: oversized files:"; echo "$big"; exit 4; fi
echo "   clean"
echo "export ready: $STAGE  ($(du -sh "$STAGE" | cut -f1), $(find "$STAGE" -type f | wc -l | tr -d ' ') files)"

if [ -n "$PUSH" ]; then
  echo "== 6. commit + push -> $PUSH"
  cd "$STAGE"
  if [ ! -d .git ]; then
    git init -q
    git symbolic-ref HEAD refs/heads/main   # portable "main" (old git lacks init -b)
  fi
  # GitHub HTTPS rejects this host's chunked transfer on multi-MB packs (RPC 400 / curl 56 --
  # observed 2026-07-06, silently stranding 14 dev commits); buffer the whole pack instead.
  git config http.postBuffer 524288000
  git add -A
  SRC_HEAD=$(git -C "$REPO" rev-parse --short HEAD)
  git commit -q -m "Distribution export from dev repo @ $SRC_HEAD" || echo "(nothing new to commit)"
  git remote remove origin 2>/dev/null || true
  git remote add origin "$PUSH"
  # CR-003: a lease needs a remote-tracking ref to compare against -- fetch first; and NEVER
  # fall back to an un-leased force push (it would silently clobber a concurrent push).
  if git fetch origin main 2>/dev/null; then
    git push -u origin main --force-with-lease=main:origin/main
  else
    # brand-new/empty remote: nothing to clobber; a plain push creates the branch
    git push -u origin main
  fi
  # CR-003 addendum: do NOT trust the push's exit path (a transport failure once printed
  # "Everything up-to-date" and stranded 14 commits) -- verify the remote ref itself.
  LOCAL_SHA=$(git rev-parse main)
  REMOTE_SHA=$(git ls-remote origin main | cut -f1)
  if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "FAIL: remote main ($REMOTE_SHA) != staged export ($LOCAL_SHA) after push."; exit 6
  fi
  echo "pushed + remote-verified ($(git rev-parse --short main))."
fi
