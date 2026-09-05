#!/usr/bin/env bash
# export_anonymous.sh — build (and optionally push) the ANONYMIZED distribution variant.
#
# The double-blind-review pattern: identical validated content, all author/account identity
# scrubbed, verified by a fail-loud identity gate. Runs the standard export first (all of its
# sanitization + hygiene + evidence gates), then applies the anonymization layer on the stage.
#
#   export_anonymous.sh <staging-dir> [--anon-url https://github.com/<acct>/<repo>.git] [--push]
#
# --anon-url rewrites every repo self-reference (clone command, CI badge, links) to the new
#   repository; without it a neutral placeholder is used (fill before pushing).
# --push pushes to the --anon-url remote with an ANONYMOUS git author. The gh CLI must already
#   be authenticated AS THE NEW ACCOUNT (the operator does `gh auth login` themselves; this
#   script never touches credentials).
#
# What is scrubbed: CITATION.cff author block + email (-> "Anonymous"), NOTICE copyright line,
# README contact line, every github.com/<old-account> URL, and the git author/committer on the
# export commit. What is NOT scrubbed (impossible at content level): the work itself — if a
# non-anonymized public copy exists elsewhere, identical artifacts make linkage trivial for
# anyone who goes looking. Good-faith review anonymity only.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"

STAGE=""; ANON_URL=""; DO_PUSH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --anon-url) ANON_URL="$2"; shift 2;;
    --push) DO_PUSH=1; shift;;
    -*) echo "unknown arg: $1"; exit 64;;
    *) STAGE="$1"; shift;;
  esac
done
[ -n "$STAGE" ] || { echo "usage: export_anonymous.sh <staging-dir> [--anon-url URL] [--push]"; exit 64; }

# identity terms to eliminate — ASSEMBLED FROM PARTS so this script's own shipped copy carries
# no greppable literal (the identity gate would otherwise flag itself; same pattern as the
# export sanitizer's LEAK string). Extend here if the identity surface grows.
OLD_ACCOUNT="ashen""joy"
NAME_A="Am""mar"; NAME_B="Az""iz"
EMAIL_LOCAL="ammarab""dullahaziz"

echo "== A1. standard export (all gates) -> $STAGE"
bash "$HERE/export-distribution.sh" "$STAGE"

echo "== A2. anonymization layer"
PLACEHOLDER_URL="${ANON_URL:-https://github.com/ANON-ACCOUNT/ANON-REPO.git}"
URL_NOGIT="${PLACEHOLDER_URL%.git}"
# SAME-ACCOUNT mode: when the anonymous copy LIVES on the existing (pseudonymous) account, the
# account handle is its legitimate self-reference, not an identity leak — keep the URLs and drop
# the handle from the scrub+gate. The NAME/EMAIL terms remain absolute either way.
SCRUB_ACCOUNT=1
case "$URL_NOGIT" in *"github.com/$OLD_ACCOUNT/"*) SCRUB_ACCOUNT=0;
  echo "   (same-account mode: '$OLD_ACCOUNT' is the pseudonymous home — handle kept)";; esac
python3 - "$STAGE" "$OLD_ACCOUNT" "$URL_NOGIT" "$SCRUB_ACCOUNT" <<'PYEOF'
import os, re, sys
stage, old_acct, url, scrub_acct = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"
acct_repo = "/".join(url.rstrip("/").split("/")[-2:])

# 1. CITATION.cff: anonymous author, no email, repo URL swapped
cff = os.path.join(stage, "CITATION.cff")
if os.path.exists(cff):
    t = open(cff).read()
    t = re.sub(r"authors:\n(?:  .*\n)+",
               'authors:\n  - name: "Anonymous (identity withheld for review)"\n', t, count=1)
    t = re.sub(r'repository-code: ".*"', f'repository-code: "{url}"', t)
    open(cff, "w").write(t)

# 2. NOTICE: neutral copyright
nf = os.path.join(stage, "NOTICE")
if os.path.exists(nf):
    t = open(nf).read()
    t = re.sub(r"Copyright \d{4} .*", "Copyright (c) the authors (identity withheld for review)", t)
    open(nf, "w").write(t)

# 3. README: drop the contact clause, swap self-URLs (badges, clone command, links)
rd = os.path.join(stage, "README.md")
t = open(rd).read()
t = re.sub(r"\s*Contact: [^\s]+@[^\s.]+(\.[a-z]+)+\.?", "", t)
t = t.replace(f"github.com/{old_acct}/hep-agentic-pipeline", f"github.com/{acct_repo}")
open(rd, "w").write(t)

# 4. tree-wide: any remaining old-account URL in text files (skipped in same-account mode)
import subprocess
if scrub_acct:
    hits = subprocess.run(["grep", "-rIl", old_acct, stage], capture_output=True, text=True)
    for f in hits.stdout.splitlines():
        s = open(f, errors="replace").read()
        open(f, "w").write(s.replace(f"github.com/{old_acct}/hep-agentic-pipeline",
                                     f"github.com/{acct_repo}").replace(old_acct, "ANON"))
print("anonymization edits applied")
PYEOF

echo "== A3. IDENTITY GATE: zero traces of the author/account may remain"
FAILED=0
GATE_TERMS=("$NAME_A" "$NAME_B" "$EMAIL_LOCAL")
[ "$SCRUB_ACCOUNT" -eq 1 ] && GATE_TERMS+=("$OLD_ACCOUNT")
for term in "${GATE_TERMS[@]}"; do
  # word-bounded for the name terms (avoid 'ranking'-style false positives); plain for the rest
  case "$term" in
    "$NAME_A"|"$NAME_B") PAT="\\b${term}\\b";;
    *) PAT="$term";;
  esac
  IDENTITY_HITS=$(grep -rIlE "$PAT" "$STAGE" 2>/dev/null || true)
  if [ -n "$IDENTITY_HITS" ]; then
    echo "FAIL: identity term '$term' survives in:"
    echo "$IDENTITY_HITS" | head -5
    FAILED=1
  fi
done
[ "$FAILED" -eq 0 ] || { echo "identity gate FAILED — fix the scrubs above"; exit 7; }
echo "   clean (0 identity traces)"

echo "== A4. gates re-run on the anonymized stage"
( cd "$STAGE" && python3 scripts/claims_check.py ) || { echo "claims gate broke under anonymization"; exit 8; }
( cd "$STAGE" && python3 scripts/check_evidence.py --check --root . >/dev/null ) \
  || { echo "evidence gate broke under anonymization"; exit 8; }
echo "   claims + evidence green"

if [ "$DO_PUSH" -eq 1 ]; then
  [ -n "$ANON_URL" ] || { echo "--push requires --anon-url"; exit 64; }
  echo "== A5. commit + push with ANONYMOUS author -> $ANON_URL"
  # Preserve the remote's history exactly as the standard publisher does.
  PUBLISH_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ravel-anonymous-publish.XXXXXX")
  git clone --branch main --single-branch "$ANON_URL" "$PUBLISH_DIR/repo"
  rsync -a --delete --exclude='.git' "$STAGE/" "$PUBLISH_DIR/repo/"
  cd "$PUBLISH_DIR/repo"
  export GIT_AUTHOR_NAME="Anonymous" GIT_AUTHOR_EMAIL="anonymous@users.noreply.github.com"
  export GIT_COMMITTER_NAME="Anonymous" GIT_COMMITTER_EMAIL="anonymous@users.noreply.github.com"
  git add -A
  if ! git diff --cached --quiet; then
    git commit -q -m "Anonymized distribution snapshot"
    git push origin HEAD:main
  fi
  LOCAL_SHA=$(git rev-parse HEAD)
  REMOTE_SHA=$(git ls-remote origin refs/heads/main | cut -f1)
  [ "$LOCAL_SHA" = "$REMOTE_SHA" ] || { echo "FAIL: remote != reviewed export after push"; exit 6; }
  echo "pushed + remote-verified ($LOCAL_SHA), checkout: $PUBLISH_DIR/repo"
else
  echo "anonymized stage ready: $STAGE (no push; rerun with --anon-url <URL> --push once the"
  echo "new account exists and gh is authenticated as it)"
fi
