#!/usr/bin/env bash
# Export the explicit public layout; preserve original archive bytes and Git history.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
USAGE="usage: export-distribution.sh <empty-stage> [--self-url URL] [--push URL [--push-branch BRANCH] [--message TEXT] [--allow-new-identity]]"
STAGE="${1:?$USAGE}"
shift
ALLOW_PLACEHOLDER=0; PUSH=""; SELF_URL=""; BRANCH="main"; MESSAGE=""; NEW_IDENTITY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-placeholder-license) ALLOW_PLACEHOLDER=1; shift;;
    --push) PUSH="${2:?--push needs a remote url}"; shift 2;;
    --push-branch) BRANCH="${2:?--push-branch needs a branch name}"; shift 2;;
    --message) MESSAGE="${2:?--message needs the commit message}"; shift 2;;
    --allow-new-identity) NEW_IDENTITY=1; shift;;
    --self-url) SELF_URL="${2:?--self-url needs a repo url}"; shift 2;;
    *) echo "unknown arg: $1"; exit 64;;
  esac
done
if [ -z "$PUSH" ] && { [ "$BRANCH" != main ] || [ -n "$MESSAGE" ] || [ "$NEW_IDENTITY" = 1 ]; }; then
  echo "--push-branch, --message and --allow-new-identity apply only with --push"; exit 64
fi
if ! git check-ref-format --branch "$BRANCH" >/dev/null 2>&1; then
  echo "invalid --push-branch: $BRANCH"; exit 64
fi
# Every check below runs under the python3 first on PATH. The public CI and CONTRIBUTING.md use Python
# 3.12, and pinned evidence (the native fidelity audit's AST digests) verifies only under the version it
# was recorded with, so any other interpreter fails late in check_publication. Stop early and say why.
EXPORT_PYTHON="3.12"
FOUND_PYTHON="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$FOUND_PYTHON" != "$EXPORT_PYTHON" ]; then
  echo "FAIL: python3 on PATH is $FOUND_PYTHON; the export checks need Python $EXPORT_PYTHON (the CI version)."
  echo "Put a $EXPORT_PYTHON interpreter first on PATH, for example the development venv's bin directory."
  exit 3
fi
# The checks below import the staged code; no bytecode cache may land in the stage (a .pyc embeds the
# absolute source path, and the leak check has already run).
export PYTHONDONTWRITEBYTECODE=1
LEAK="$HOME"
STAGE="$(python3 "$REPO/scripts/export_safety.py" prepare "$STAGE" "$REPO")"
python3 "$REPO/scripts/export_safety.py" assemble "$STAGE" "$REPO"
SANITIZE_ARGS=("$STAGE" "$LEAK")
[ -z "$SELF_URL" ] || SANITIZE_ARGS+=(--self-url "$SELF_URL")
python3 "$REPO/scripts/export_safety.py" sanitize "${SANITIZE_ARGS[@]}"
# Every staged file, text or binary, and every staged path: the home directory, its dash-encoded form
# (-Users-<name>-...) and the bare account name. Only the home directory is redacted above.
if ! python3 "$REPO/scripts/export_safety.py" leak-check "$STAGE" "$LEAK"; then
  echo "FAIL: home-rooted paths or the account name remain in the staged export"; exit 2
fi
if grep -q "example.invalid" "$STAGE/CITATION.cff" || grep -qi "to be finalized" "$STAGE/LICENSE"; then
  if [ "$ALLOW_PLACEHOLDER" != 1 ]; then
    echo "FAIL: publication metadata contains placeholders"; exit 5
  fi
fi
BIND_ARGS=("$STAGE" "$REPO" "$LEAK")
[ -z "$SELF_URL" ] || BIND_ARGS+=(--self-url "$SELF_URL")
python3 "$REPO/scripts/export_safety.py" bind-evidence "${BIND_ARGS[@]}"
python3 "$REPO/scripts/check_evidence.py" --check --root "$STAGE"
python3 "$STAGE/scripts/run.py" ravel.validation.check_agent_surface --stage "$STAGE"
python3 "$STAGE/scripts/check_publication.py"
# Every campaign build freezes the whole task bank from pinned files (E-136, E-152). Build it from the stage,
# so a pin that the sanitizer breaks fails here rather than in the public CI.
BANK_CHECK="$(mktemp -d "${TMPDIR:-/tmp}/ravel-bank-check.XXXXXX")"
(cd "$STAGE" && PYTHONPATH="$STAGE/src:$STAGE/benchmarks" python3 -c '
import sys
from governance.tasks import registry
tasks = registry.build_bank(sys.argv[1] + "/bank")["tasks"]
print("task bank from the stage: OK (%d tasks)" % len(tasks))' "$BANK_CHECK")
rm -rf "$BANK_CHECK"
cache=$(find "$STAGE" -name __pycache__ -o -name '*.pyc')
if [ -n "$cache" ]; then echo "FAIL: bytecode caches in the stage:"; echo "$cache"; exit 4; fi
big=$(find "$STAGE" -type f -size +5M)
if [ -n "$big" ]; then echo "FAIL: oversized files:"; echo "$big"; exit 4; fi
echo "export ready: $STAGE"

if [ -n "$PUSH" ]; then
  echo "== 6. append a distribution commit to the remote history -> $PUSH (branch $BRANCH)"
  # A fresh source snapshot must never replace the published commit graph. Clone the
  # remote, apply the reviewed curated tree, and use a normal fast-forward push. A
  # concurrent publisher causes rejection; there is no force-push fallback.
  PUBLISH_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ravel-publish.XXXXXX")
  git clone --branch main --single-branch "$PUSH" "$PUBLISH_DIR/repo"
  cd "$PUBLISH_DIR/repo"
  # The fresh clone has no local identity: git takes it from GIT_AUTHOR_*/GIT_COMMITTER_* or the global
  # configuration. It must be the identity of the published history's last commit, so that a machine's
  # default identity is never attached to the public repository by accident.
  ident() { git var "$1" | sed -E 's/ [0-9]+ [-+][0-9]{4}$//'; }
  AUTHOR=$(ident GIT_AUTHOR_IDENT) || { echo "FAIL: git has no author identity for the publish commit"; exit 7; }
  COMMITTER=$(ident GIT_COMMITTER_IDENT) || { echo "FAIL: git has no committer identity for the publish commit"; exit 7; }
  LAST_AUTHOR=$(git log -1 --format='%an <%ae>')
  LAST_COMMITTER=$(git log -1 --format='%cn <%ce>')
  if [ "$AUTHOR" != "$LAST_AUTHOR" ] || [ "$COMMITTER" != "$LAST_COMMITTER" ]; then
    if [ "$NEW_IDENTITY" != 1 ]; then
      echo "FAIL: the publish identity differs from the published history's last commit:"
      echo "  author    $AUTHOR (last commit: $LAST_AUTHOR)"
      echo "  committer $COMMITTER (last commit: $LAST_COMMITTER)"
      echo "Set GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME and GIT_COMMITTER_EMAIL, or pass"
      echo "--allow-new-identity to publish under a new identity deliberately. Nothing was committed."
      exit 7
    fi
    echo "WARNING: publishing under a new identity, as requested: $AUTHOR / $COMMITTER"
  fi
  rsync -a --delete --exclude='.git' "$STAGE/" "$PUBLISH_DIR/repo/"
  git add -A
  if git diff --cached --quiet; then
    echo "No distribution changes."
    TARGET=main
  else
    SRC_HEAD=$(git -C "$REPO" rev-parse --short HEAD)
    git commit -m "${MESSAGE:-Distribution update from dev repo @ $SRC_HEAD}"
    git push origin "HEAD:refs/heads/$BRANCH"
    TARGET="$BRANCH"
  fi
  LOCAL_SHA=$(git rev-parse HEAD)
  REMOTE_SHA=$(git ls-remote origin "refs/heads/$TARGET" | cut -f1)
  if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "FAIL: remote $TARGET ($REMOTE_SHA) != reviewed export ($LOCAL_SHA)."; exit 6
  fi
  echo "remote-verified ($TARGET = $LOCAL_SHA); checkout retained at $PUBLISH_DIR/repo"
  if [ "$TARGET" != main ]; then
    echo "main is unchanged: open a pull request from $TARGET so CI runs before main moves."
  fi
fi
