"""check:status_packet_resumable -- a status packet regenerated from records alone gives a
byte-identical next work item.

A resumed session reads `current_state.json` (written by `ravel status --write`) to decide what
to do next. That packet must be a pure view of the run's records: regenerating it from a copy of
the run without `current_state.json` must give the same next work item, byte for byte. A
difference means the packet carried state the records do not (or the records changed after it
was written), and a resumed session would act on the wrong item.

The next work item is `{"next_required", "next_instruction"}` serialized canonically
(the shared JSON digest); the copy's path is mapped back to the run's path first.

  python -m ravel.validation.check_status_packet <rundir> [<rundir> ...] [--json]

Exit 0 when every run passes, 1 otherwise. Read-only on the run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

PACKET = "current_state.json"


def next_item(packet):
    return {"next_required": packet.get("next_required"), "next_instruction": packet.get("next_instruction")}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def regenerate(rundir):
    """The next work item derived from a copy of the run's records without its packet."""
    from ravel.workflow.current_state import build_packet
    rundir = Path(rundir).absolute()
    with tempfile.TemporaryDirectory(prefix="ravel-status-packet-") as tmp:
        copy = Path(tmp).resolve() / rundir.name
        shutil.copytree(rundir, copy, symlinks=True, copy_function=_link_or_copy,
                        ignore=lambda d, names: [n for n in names if Path(d) == rundir and n == PACKET])
        text = _canonical(next_item(build_packet(copy)))
    return text.replace(str(copy), str(rundir))


def check(rundir):
    rundir = Path(rundir).absolute()
    report = {"schema_version": 1, "kind": "status-packet-resumable", "rundir": str(rundir)}
    try:
        regenerated = regenerate(rundir)
        again = regenerate(rundir)
    except Exception as exc:  # an underivable packet cannot be resumed from
        return {**report, "status": "fail", "detail": f"the status packet does not derive from records: {exc}"}
    report["regenerated_next_sha256"] = hashlib.sha256(regenerated.encode()).hexdigest()
    if again != regenerated:
        return {**report, "status": "fail",
                "detail": "two regenerations from the same records give different next work items"}
    recorded_path = rundir / PACKET
    if not recorded_path.is_file():
        return {**report, "status": "pass", "recorded_next_sha256": None,
                "detail": "no recorded packet; regeneration is deterministic"}
    try:
        recorded = _canonical(next_item(json.loads(recorded_path.read_text(encoding="utf-8"))))
    except (OSError, ValueError, AttributeError) as exc:
        return {**report, "status": "fail", "detail": f"recorded packet is unreadable: {exc}"}
    report["recorded_next_sha256"] = hashlib.sha256(recorded.encode()).hexdigest()
    if recorded != regenerated:
        return {**report, "status": "fail",
                "detail": "the recorded packet's next work item differs from the one regenerated from records; "
                          "refresh it with `ravel status --rundir <run> --write` and resume from the refreshed packet"}
    return {**report, "status": "pass", "detail": "byte-identical next work item"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ravel.validation.check_status_packet", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rundirs", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    reports = [check(rd) for rd in args.rundirs]
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for r in reports:
            print(f"[{'PASS' if r['status'] == 'pass' else 'FAIL'}] {r['rundir']}: {r['detail']}")
    return 0 if all(r["status"] == "pass" for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
