#!/usr/bin/env bash
# Shared native locations. Existing source toolchains keep their original bytes.
# Source it from bash or zsh: `source native/scripts/paths.sh`.
#
# Prefix order (identical in src/ravel/paths.py): RAVEL_NATIVE_BUILD (or its alias BUILD_DIR),
# then the installer's pointer file .ravel/native-prefix (this checkout, then the main checkout
# of a linked worktree). Without either, the first existing directory wins:
#   <checkout>/stages/01-event-generation/build, <checkout>/native/build,
#   the same two in the main checkout when <checkout> is a linked git worktree,
#   ${XDG_DATA_HOME:-$HOME/.local/share}/ravel-native.
# RAVEL_NATIVE_BIN defaults to <prefix>/bin for an explicitly chosen prefix; otherwise to the
# first existing native/build/bin (checkout, main checkout), then $RAVEL_NATIVE_BUILD/bin.
# When no build exists the helper stops with the searched list; set RAVEL_NATIVE_PROVISION=1 for a first installation into <checkout>/native/build.
_ravel_src="${BASH_SOURCE[0]:-${(%):-%x}}"
RAVEL_REPO="$(cd "$(dirname "$_ravel_src")/../.." && pwd)"

_ravel_main=""
if [ -f "$RAVEL_REPO/.git" ]; then
  _ravel_gitdir="$(sed -n 's/^gitdir:[[:space:]]*//p' "$RAVEL_REPO/.git" | head -n 1)"
  case "$_ravel_gitdir" in /*) ;; ?*) _ravel_gitdir="$RAVEL_REPO/$_ravel_gitdir" ;; esac
  if [ -n "$_ravel_gitdir" ] && [ -f "$_ravel_gitdir/commondir" ]; then
    _ravel_common="$(head -n 1 "$_ravel_gitdir/commondir")"
    case "$_ravel_common" in /*) ;; *) _ravel_common="$_ravel_gitdir/$_ravel_common" ;; esac
    _ravel_common="$(cd "$_ravel_common" 2>/dev/null && pwd)"
    case "$_ravel_common" in */.git) _ravel_main="${_ravel_common%/.git}" ;; esac
  fi
fi
_ravel_shared="${XDG_DATA_HOME:-$HOME/.local/share}/ravel-native"

if [ -n "${BUILD_DIR:-}" ]; then
  if [ -n "${RAVEL_NATIVE_BUILD:-}" ] && [ "$BUILD_DIR" != "$RAVEL_NATIVE_BUILD" ]; then
    echo 'ERROR: BUILD_DIR and RAVEL_NATIVE_BUILD disagree; use one native prefix' >&2
    unset _ravel_src _ravel_main _ravel_gitdir _ravel_common _ravel_shared
    return 1
  fi
  RAVEL_NATIVE_BUILD="$BUILD_DIR"
fi

_ravel_prefix_chosen=0
if [ -z "${RAVEL_NATIVE_BUILD:-}" ]; then
  for _ravel_root in "$RAVEL_REPO" "$_ravel_main"; do
    if [ -n "$_ravel_root" ] && [ -z "${RAVEL_NATIVE_BUILD:-}" ] && [ -f "$_ravel_root/.ravel/native-prefix" ]; then
      RAVEL_NATIVE_BUILD="$(head -n 1 "$_ravel_root/.ravel/native-prefix")"
      case "$RAVEL_NATIVE_BUILD" in "~"*) RAVEL_NATIVE_BUILD="$HOME${RAVEL_NATIVE_BUILD#\~}" ;; esac
    fi
  done
fi

if [ -n "${RAVEL_NATIVE_BUILD:-}" ]; then
  _ravel_prefix_chosen=1
  if [ ! -d "$RAVEL_NATIVE_BUILD" ]; then
    echo "NOTE: RAVEL_NATIVE_BUILD=$RAVEL_NATIVE_BUILD does not exist yet; provisioning creates it." >&2
  fi
else
  _ravel_searched=""
  for _ravel_root in "$RAVEL_REPO" "$_ravel_main"; do
    [ -n "$_ravel_root" ] || continue
    for _ravel_cand in "$_ravel_root/stages/01-event-generation/build" "$_ravel_root/native/build"; do
      _ravel_searched="$_ravel_searched
  $_ravel_cand"
      if [ -z "${RAVEL_NATIVE_BUILD:-}" ] && [ -d "$_ravel_cand" ]; then
        RAVEL_NATIVE_BUILD="$_ravel_cand"
      fi
    done
  done
  _ravel_searched="$_ravel_searched
  $_ravel_shared"
  if [ -z "${RAVEL_NATIVE_BUILD:-}" ] && [ -d "$_ravel_shared" ]; then
    RAVEL_NATIVE_BUILD="$_ravel_shared"
  fi
  if [ -z "${RAVEL_NATIVE_BUILD:-}" ]; then
    if [ "${RAVEL_NATIVE_PROVISION:-}" = "1" ]; then
      RAVEL_NATIVE_BUILD="$RAVEL_REPO/native/build"
    else
      echo "ERROR: no RAVEL native build found. Searched:$_ravel_searched" >&2
      echo "Set RAVEL_NATIVE_BUILD to an existing toolchain prefix, or set RAVEL_NATIVE_PROVISION=1" >&2
      echo "to install a new one at $RAVEL_REPO/native/build (docs/reference/environment.md)." >&2
      unset _ravel_src _ravel_main _ravel_gitdir _ravel_common _ravel_shared _ravel_searched _ravel_root _ravel_cand \
        _ravel_prefix_chosen
      return 1
    fi
  fi
fi

if [ -z "${RAVEL_NATIVE_BIN:-}" ] && [ "$_ravel_prefix_chosen" = 1 ]; then
  RAVEL_NATIVE_BIN="$RAVEL_NATIVE_BUILD/bin"
elif [ -z "${RAVEL_NATIVE_BIN:-}" ]; then
  for _ravel_cand in "$RAVEL_REPO/native/build/bin" "${_ravel_main:+$_ravel_main/native/build/bin}" \
      "$RAVEL_NATIVE_BUILD/bin" "$_ravel_shared/bin"; do
    if [ -z "${RAVEL_NATIVE_BIN:-}" ] && [ -n "$_ravel_cand" ] && [ -d "$_ravel_cand" ]; then
      RAVEL_NATIVE_BIN="$_ravel_cand"
    fi
  done
  RAVEL_NATIVE_BIN="${RAVEL_NATIVE_BIN:-$RAVEL_REPO/native/build/bin}"
fi
unset _ravel_src _ravel_main _ravel_gitdir _ravel_common _ravel_shared _ravel_searched _ravel_root _ravel_cand \
  _ravel_prefix_chosen
case "$RAVEL_NATIVE_BUILD" in /*) ;; *) echo 'ERROR: RAVEL_NATIVE_BUILD must be absolute' >&2; return 1 ;; esac
case "$RAVEL_NATIVE_BIN" in /*) ;; *) echo 'ERROR: RAVEL_NATIVE_BIN must be absolute' >&2; return 1 ;; esac
export RAVEL_NATIVE_BUILD RAVEL_NATIVE_BIN
