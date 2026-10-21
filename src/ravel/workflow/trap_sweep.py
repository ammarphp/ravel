"""Write and check a run's physics trap sweep (``inputs/trap_sweep.json``).

The sweep follows docs/workflow/checklists/physics-traps.md. The host records a
verdict for every trap T1..T12; this tool writes the record the lifecycle
validator reads and checks it with that same validator.

    python -m ravel.workflow.trap_sweep write --rundir RUN --input verdicts.json [--replace]
    python -m ravel.workflow.trap_sweep validate --rundir RUN [--require-discharged] [--json]

Input for ``write``::

    {"verdicts": [{"id": "T1", "hit": false, "evidence": "..."},
                  {"id": "T8", "hit": true, "evidence": "...", "consequence": "...", "flag_number": 3},
                  ...one row for each of T1..T12],
     "escalations": [{"id": "T5", "reason": "..."}],
     "obligations": [{"trap": "T8", "obligation_kind": "...", "artifact": null, "status": "PENDING"}]}

``escalations`` and ``obligations`` are optional. A hit needs a ``consequence``
and either a positive ``flag_number`` or an escalation row. Every hit except T3
and T9 (handled by the basis manifest) gets a PENDING obligation when none is
supplied. Exit codes: 0 success/PASS, 1 FAIL, 2 input or write error.
"""
import argparse
import json
import sys
from pathlib import Path

TRAP_IDS = tuple(f"T{i}" for i in range(1, 13))
BASIS_TRAPS = ("T3", "T9")
OBLIGATION_STATUS = ("PENDING", "PASS", "FAIL")
RELATIVE_PATH = "inputs/trap_sweep.json"


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonblank text")
    return value


def _keys(row, required, optional, label):
    if not isinstance(row, dict):
        raise ValueError(f"{label} must be an object")
    missing = [k for k in required if k not in row]
    extra = sorted(set(row) - set(required) - set(optional))
    if missing:
        raise ValueError(f"{label} is missing {missing}")
    if extra:
        raise ValueError(f"{label} has unknown fields {extra}")


def _verdict(row):
    _keys(row, ("id", "hit", "evidence"), ("consequence", "flag_number"), "verdict")
    trap = row["id"]
    if trap not in TRAP_IDS:
        raise ValueError(f"unknown trap id {trap!r}; expected one of T1..T12")
    if type(row["hit"]) is not bool:
        raise ValueError(f"{trap}: hit must be true or false")
    _text(row["evidence"], f"{trap} evidence")
    flag = row.get("flag_number")
    if flag is not None and (type(flag) is not int or flag < 1):
        raise ValueError(f"{trap}: flag_number must be a positive integer")
    consequence = row.get("consequence")
    if row["hit"]:
        _text(consequence, f"{trap} consequence")
    elif consequence is not None:
        _text(consequence, f"{trap} consequence")
    return {"id": trap, "hit": row["hit"], "evidence": row["evidence"],
            "consequence": consequence, "flag_number": flag}


def _escalation(row):
    _keys(row, ("id", "reason"), (), "escalation")
    if row["id"] not in TRAP_IDS:
        raise ValueError(f"escalation names unknown trap {row['id']!r}")
    _text(row["reason"], f"{row['id']} escalation reason")
    return {"id": row["id"], "reason": row["reason"]}


def _obligation(row):
    _keys(row, ("trap", "obligation_kind", "artifact", "status"), (), "obligation")
    if row["trap"] not in TRAP_IDS:
        raise ValueError(f"obligation names unknown trap {row['trap']!r}")
    _text(row["obligation_kind"], f"{row['trap']} obligation_kind")
    if row["status"] not in OBLIGATION_STATUS:
        raise ValueError(f"{row['trap']} obligation status must be one of {list(OBLIGATION_STATUS)}")
    if row["artifact"] is not None:
        if type(row['artifact']) is dict:
            from .task_completion import _pin_shape
            _pin_shape(row['artifact'])
        else:
            _text(row["artifact"], f"{row['trap']} obligation artifact")
    elif row["status"] == "PASS":
        raise ValueError(f"{row['trap']}: a PASS obligation needs the artifact that discharges it")
    return dict(row)


def build(document):
    """Return the complete trap-sweep record for a host's verdicts."""
    _keys(document, ("verdicts",), ("escalations", "obligations"), "trap sweep input")
    rows = document["verdicts"]
    if not isinstance(rows, list):
        raise ValueError("verdicts must be a list")
    verdicts = [_verdict(row) for row in rows]
    ids = [v["id"] for v in verdicts]
    duplicate = sorted({i for i in ids if ids.count(i) > 1})
    if duplicate:
        raise ValueError(f"duplicate verdicts for {duplicate}")
    missing = [t for t in TRAP_IDS if t not in ids]
    if missing:
        raise ValueError(f"every trap needs a verdict; missing {missing}")
    escalations = [_escalation(row) for row in document.get("escalations") or []]
    escalated = {row["id"] for row in escalations}
    for verdict in verdicts:
        if verdict["hit"] and verdict["flag_number"] is None and verdict["id"] not in escalated:
            raise ValueError(f"{verdict['id']}: a hit needs a flag_number or an escalations entry")
    verdicts.sort(key=lambda v: TRAP_IDS.index(v["id"]))
    hits = [v for v in verdicts if v["hit"]]
    obligations = [_obligation(row) for row in document.get("obligations") or []]
    covered = {row["trap"] for row in obligations}
    for verdict in hits:
        if verdict["id"] not in BASIS_TRAPS and verdict["id"] not in covered:
            obligations.append({"trap": verdict["id"], "obligation_kind": "route-consequence",
                                "artifact": None, "status": "PENDING"})
    return {"schema_version": 1, "generated_by": "ravel.workflow.trap_sweep",
            "traps_checked": list(TRAP_IDS), "none_hit": not hits, "verdicts": verdicts,
            "traps_hit": [{"id": v["id"], "evidence": v["evidence"], "consequence": v["consequence"],
                           "flag_number": v["flag_number"]} for v in hits],
            "escalations": escalations, "obligations": obligations}


def write(rundir, document, *, replace=False):
    """Validate the host's verdicts and write ``inputs/trap_sweep.json``."""
    from .state_io import atomic_json
    record = build(document)
    path = Path(rundir) / RELATIVE_PATH
    if path.is_symlink():
        raise ValueError(f"{path} is a symbolic link")
    if path.exists() and not replace:
        raise FileExistsError(f"{path} exists; pass --replace to record a revised sweep")
    atomic_json(path, record)
    return path


def validate(rundir, *, require_discharged=False, relative=RELATIVE_PATH):
    """Check the sweep with the lifecycle validator and report open obligations.

    ``relative`` locates the record inside ``rundir``; a controller run reads it where the governed
    step adopted it (``steps/<step>/...``).
    """
    from ravel.validation.validate_run_state import check_trap_sweep
    rundir = Path(rundir)
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("the trap sweep path is relative to the run directory")
    path = rundir / relative
    if path.is_symlink() or not path.is_file():
        return {"status": "FAIL", "path": str(path), "checks": [
            {"name": "presence", "level": "FAIL", "msg": f"{relative} not found"}],
            "traps_hit": [], "undischarged": []}
    status, _, checks = check_trap_sweep(str(rundir), {}, {"trap_sweep_path": str(relative)}, "R", False)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    hits = []
    for row in doc.get("traps_hit") or []:
        trap = row if isinstance(row, str) else row.get("id") if isinstance(row, dict) else None
        if isinstance(trap, str):
            hits.append(trap)
    obligations = [o for o in doc.get("obligations") or [] if isinstance(o, dict)]
    undischarged = [h for h in hits if h not in BASIS_TRAPS and not any(
        o.get("trap") == h and o.get("status") == "PASS" for o in obligations)]
    if require_discharged and undischarged:
        checks = checks + [{"name": "obligations", "level": "FAIL",
                            "msg": f"obligations not PASS for {undischarged}"}]
        status = "FAIL"
    return {"status": status, "path": str(path), "checks": checks, "traps_hit": hits,
            "undischarged": undischarged}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ravel.workflow.trap_sweep",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write", help="write inputs/trap_sweep.json from the host's verdicts")
    w.add_argument("--rundir", type=Path, required=True)
    w.add_argument("--input", type=Path, required=True, help="verdicts JSON (see module help)")
    w.add_argument("--replace", action="store_true", help="replace an existing sweep record")
    v = sub.add_parser("validate", help="check inputs/trap_sweep.json")
    v.add_argument("--rundir", type=Path, required=True)
    v.add_argument("--require-discharged", action="store_true",
                   help="also fail while an obligation-bearing hit has no PASS obligation")
    v.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "write":
        try:
            from .state_io import read_json
            path = write(args.rundir, read_json(args.input), replace=args.replace)
        except (OSError, ValueError) as exc:
            print(f"trap_sweep: {exc}", file=sys.stderr)
            return 2
        print(f"trap sweep -> {path}")
        return 0
    report = validate(args.rundir, require_discharged=args.require_discharged)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"trap sweep [{report['status']}] {report['path']}")
        for check in report["checks"]:
            print(f"  {check['level']:5} {check['name']}: {check['msg']}")
        if report["undischarged"]:
            print(f"  open obligations: {report['undischarged']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
