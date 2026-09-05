#!/usr/bin/env bash
# Export the explicit public layout; preserve original archive bytes and Git history.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="${1:?usage: export-distribution.sh <empty-stage> [--self-url URL] [--push URL]}"
shift
ALLOW_PLACEHOLDER=0; PUSH=""; SELF_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-placeholder-license) ALLOW_PLACEHOLDER=1; shift;;
    --push) PUSH="${2:?--push needs a remote url}"; shift 2;;
    --self-url) SELF_URL="${2:?--self-url needs a repo url}"; shift 2;;
    *) echo "unknown arg: $1"; exit 64;;
  esac
done
LEAK="$HOME"
STAGE="$(python3 "$REPO/scripts/export_safety.py" prepare "$STAGE" "$REPO")"
python3 "$REPO/scripts/export_safety.py" assemble "$STAGE" "$REPO"
SANITIZE_ARGS=("$STAGE" "$LEAK")
[ -z "$SELF_URL" ] || SANITIZE_ARGS+=(--self-url "$SELF_URL")
python3 "$REPO/scripts/export_safety.py" sanitize "${SANITIZE_ARGS[@]}"
if grep -rIq "$LEAK" "$STAGE"; then
  echo "FAIL: home-rooted paths remain in the staged export"; exit 2
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
big=$(find "$STAGE" -type f -size +5M)
if [ -n "$big" ]; then echo "FAIL: oversized files:"; echo "$big"; exit 4; fi
echo "export ready: $STAGE"

if [ -n "$PUSH" ]; then
  echo "== 6. append a distribution commit to the remote history -> $PUSH"
  # A fresh source snapshot must never replace the published commit graph. Clone the
  # remote, apply the reviewed curated tree, and use a normal fast-forward push. A
  # concurrent publisher causes rejection; there is no force-push fallback.
  PUBLISH_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ravel-publish.XXXXXX")
  git clone --branch main --single-branch "$PUSH" "$PUBLISH_DIR/repo"
  rsync -a --delete --exclude='.git' "$STAGE/" "$PUBLISH_DIR/repo/"
  cd "$PUBLISH_DIR/repo"
  git add -A
  if git diff --cached --quiet; then
    echo "No distribution changes."
  else
    SRC_HEAD=$(git -C "$REPO" rev-parse --short HEAD)
    git commit -m "Distribution update from dev repo @ $SRC_HEAD"
    git push origin HEAD:main
  fi
  LOCAL_SHA=$(git rev-parse HEAD)
  REMOTE_SHA=$(git ls-remote origin refs/heads/main | cut -f1)
  if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "FAIL: remote main ($REMOTE_SHA) != reviewed export ($LOCAL_SHA)."; exit 6
  fi
  echo "pushed + remote-verified ($LOCAL_SHA); checkout retained at $PUBLISH_DIR/repo"
fi
