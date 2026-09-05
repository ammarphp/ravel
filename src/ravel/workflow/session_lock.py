#!/usr/bin/env python3
"""session_lock -- run-dir ownership marks (CR-022; mining proposal #5).

The incident class: two concurrent sessions silently shared one run dir 18 s apart; a charter
session and a supervisor session raced edits. This is the minimal guard: a SESSION.lock at the
run root naming the owning session; writers CHECK it before touching a run dir and refuse on a
live foreign lock (steal only explicitly, with the takeover recorded in the lock history).

Not a kernel lock: cooperative, human-readable, crash-tolerant (a lock with no heartbeat for
--stale-hours is offered for takeover). Sessions have no pids; identity = a caller-supplied
label (session id, "overnight-2", a user name).

Usage:
  session_lock.py acquire <rundir> --owner <label>      exit 0 = acquired/renewed (same owner)
                                                        exit 3 = HELD by another live owner
  session_lock.py check   <rundir> [--owner <label>]    exit 0 free/yours; 3 = foreign+live
  session_lock.py release <rundir> --owner <label>
  session_lock.py steal   <rundir> --owner <label>      records the takeover in the history
Options: --stale-hours 24 (a lock older than this counts as dead and may be acquired).
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import datetime
import json
import os
import sys

LOCK = "SESSION.lock"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _read(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def _age_hours(stamp):
    try:
        t = datetime.datetime.fromisoformat(stamp)
        return (datetime.datetime.now() - t).total_seconds() / 3600.0
    except Exception:
        return 1e9


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["acquire", "check", "release", "steal"])
    ap.add_argument("rundir")
    ap.add_argument("--owner", default=None)
    ap.add_argument("--stale-hours", type=float, default=24.0)
    a = ap.parse_args()
    path = os.path.join(a.rundir, LOCK)
    lock = _read(path)
    live = lock and _age_hours(lock.get("renewed", lock.get("acquired", ""))) < a.stale_hours

    if a.action == "check":
        if not lock:
            print("free")
            return 0
        who = lock.get("owner")
        state = "LIVE" if live else f"STALE (> {a.stale_hours:g} h)"
        print(f"held by '{who}' since {lock.get('acquired')} [{state}]")
        if live and a.owner and who != a.owner:
            print("refusing: a live foreign lock — coordinate or `steal` explicitly (recorded).",
                  file=sys.stderr)
            return 3
        return 0

    if a.owner is None:
        sys.exit("session_lock: --owner required for acquire/release/steal")

    if a.action == "acquire":
        if live and lock.get("owner") != a.owner:
            print(f"HELD by '{lock['owner']}' since {lock.get('acquired')} (live). "
                  f"Coordinate, or `steal` explicitly.", file=sys.stderr)
            return 3
        hist = (lock or {}).get("history", [])
        if lock and lock.get("owner") != a.owner:
            hist.append({"event": "stale-takeover", "from": lock.get("owner"),
                         "to": a.owner, "at": _now()})
        os.makedirs(a.rundir, exist_ok=True)
        json.dump({"owner": a.owner,
                   "acquired": (lock or {}).get("acquired", _now()) if lock and
                   lock.get("owner") == a.owner else _now(),
                   "renewed": _now(), "history": hist}, open(path, "w"), indent=1)
        print(f"acquired by '{a.owner}'")
        return 0

    if a.action == "release":
        if lock and lock.get("owner") == a.owner:
            os.remove(path)
            print("released")
            return 0
        print("not yours (or no lock) — nothing released", file=sys.stderr)
        return 0 if not lock else 3

    if a.action == "steal":
        hist = (lock or {}).get("history", [])
        hist.append({"event": "STEAL", "from": (lock or {}).get("owner"),
                     "to": a.owner, "at": _now(),
                     "note": "explicit takeover — the previous owner's work may be in flight"})
        json.dump({"owner": a.owner, "acquired": _now(), "renewed": _now(),
                   "history": hist}, open(path, "w"), indent=1)
        print(f"STOLEN by '{a.owner}' (recorded in lock history)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
