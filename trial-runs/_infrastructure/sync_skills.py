#!/usr/bin/env python3
"""Mirror .claude/skills -> .agents/skills (charter section 4.3: single source + sync script).

.claude/skills/ is the SINGLE SOURCE OF TRUTH (Claude Code loads it natively); .agents/skills/
is the generated Codex-side mirror AGENTS.md points at. Never hand-edit the mirror — edit the
source and re-run this. check_agent_surface.py's `mirror` assertion fails on any drift/orphan.

Usage: sync_skills.py [--check]     # --check: report drift, change nothing, exit 1 on drift
"""
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, ".claude", "skills")
DST = os.path.join(REPO, ".agents", "skills")


def rel_files(base):
    out = {}
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f == ".DS_Store":
                continue
            p = os.path.join(dp, f)
            out[os.path.relpath(p, base)] = p
    return out


def main():
    check = "--check" in sys.argv[1:]
    if not os.path.isdir(SRC):
        sys.exit(f"sync_skills: source missing: {SRC}")
    src = rel_files(SRC)
    dst = rel_files(DST) if os.path.isdir(DST) else {}
    copied, removed, drift = [], [], []
    for r in sorted(set(src) - set(dst)):
        drift.append(f"missing in mirror: {r}")
        if not check:
            t = os.path.join(DST, r)
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(src[r], t)
            copied.append(r)
    for r in sorted(set(dst) - set(src)):
        drift.append(f"orphan in mirror: {r}")
        if not check:
            os.remove(dst[r])
            removed.append(r)
    for r in sorted(set(src) & set(dst)):
        if open(src[r], "rb").read() != open(dst[r], "rb").read():
            drift.append(f"content drift: {r}")
            if not check:
                shutil.copy2(src[r], dst[r])
                copied.append(r)
    if not check:
        # prune emptied dirs
        for dp, dn, fn in list(os.walk(DST, topdown=False)):
            if not os.listdir(dp):
                os.rmdir(dp)
        print(f"sync_skills: {len(copied)} copied, {len(removed)} removed "
              f"({len(src)} files in source)")
    else:
        for d in drift:
            print(f"  {d}")
        print(f"sync_skills --check: {'DRIFT' if drift else 'in sync'} "
              f"({len(src)} source files)")
        sys.exit(1 if drift else 0)


if __name__ == "__main__":
    main()
