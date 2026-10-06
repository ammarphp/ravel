"""Checked launches with retained authorization snapshots and append-only events.

Local hash chains detect inconsistent records; they are not authentication or an
external, tamper-proof clock. Only this interface's launches have ordering evidence.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess

from . import provenance
from .execution import digest, file_hash, utc_now
from .state_io import file_lock, read_json

JOURNAL = "logs/authorization"


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("operational timestamp must be nonblank UTC")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("operational timestamp must include UTC timezone")
    return stamp


def operational_utc():
    """Real clock by default; an explicit fixed clock keeps tests deterministic."""
    value = os.environ.get("WORKFLOW_STATE_UTC") or utc_now()
    parse_utc(value)
    return value


def _events(root):
    records = []
    previous = ""
    previous_time = None
    for sequence, path in enumerate(sorted((Path(root) / JOURNAL).glob("*.json")), 1):
        event = read_json(path)
        if (not isinstance(event, dict) or type(event.get("schema_version")) is not int
                or event["schema_version"] != 1 or event.get("event") not in ("authorized", "launched")
                or type(event.get("sequence")) is not int
                or event["sequence"] != sequence or path.name != f"{sequence:08d}.json"
                or event.get("previous_sha256") != previous
                or event.get("sha256") != digest({k: v for k, v in event.items() if k != "sha256"})):
            raise ValueError("authorization event sequence or hash chain changed")
        stamp = parse_utc(event.get("utc"))
        if previous_time is not None and stamp < previous_time:
            raise ValueError("authorization event clock moved backwards")
        previous, previous_time = event["sha256"], stamp
        records.append(event)
    return records


def _append(root, payload):
    directory = Path(root) / JOURNAL
    with file_lock(directory / "write.lock"):
        records = _events(root)
        event = {"schema_version": 1, "sequence": len(records) + 1,
                 "previous_sha256": records[-1]["sha256"] if records else "",
                 "utc": operational_utc(), **payload}
        if records and parse_utc(event["utc"]) < parse_utc(records[-1]["utc"]):
            raise ValueError("authorization event clock moved backwards")
        event["sha256"] = digest(event)
        # Exclusive creation: existing events are never updated or replaced.
        with (directory / f"{event['sequence']:08d}.json").open("x", encoding="utf-8") as stream:
            json.dump(event, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return event


def _pin(path, *, document=False):
    path = Path(path).resolve()
    entry = {"path": str(path), "sha256": file_hash(path)}
    if document:
        # Preserve CRLF and other valid JSON whitespace in the byte commitment.
        entry["text"] = path.read_bytes().decode("utf-8")
        if provenance.sha256_bytes(entry["text"].encode()) != entry["sha256"]:
            raise ValueError("authorization document changed while capturing it")
    return entry


def _capture(root, required_plan):
    from . import workflow_state as ws
    errors = ws.verify_approval(str(root), required_plan=required_plan)
    if errors:
        raise ValueError("launch authorization refused: " + "; ".join(errors))
    approval = _pin(Path(root) / "inputs/checkin1_approval.json", document=True)
    inputs = [_pin(p, document=True) for p in ws.approval_input_paths(str(root))]
    contract = read_json(inputs[0]["path"])
    needs_go = required_plan in ws.BULK_PLANS and contract.get("task_mode") not in ws.NO_CHECKIN2_TASK_MODES
    snapshot = {"required_plan": required_plan, "approval": approval, "approval_inputs": inputs,
                "go": None, "go_inputs": []}
    if needs_go:
        snapshot["go"] = _pin(Path(root) / "inputs/checkin2_go.json", document=True)
        snapshot["go_inputs"] = [_pin(p, document=i in (0, 1, 2, 5))
                                 for i, p in enumerate(ws.checkin2_go_input_paths(str(root)))]
    # Recheck both the approval language and the captured bytes before recording.
    errors = ws.verify_approval(str(root), required_plan=required_plan)
    pins = [approval, *inputs, *snapshot["go_inputs"]]
    if snapshot["go"]:
        pins.append(snapshot["go"])
    if errors or any(file_hash(p["path"]) != p["sha256"] for p in pins):
        raise ValueError("authorization inputs changed while preparing launch")
    return snapshot


def _historical_errors(event):
    """Use frozen approval bytes/digests, never today's approval as a substitute."""
    from . import workflow_state as ws
    snapshot = event["authorization"]
    rung = snapshot["required_plan"]
    if rung not in ws.APPROVAL_PLANS:
        raise ValueError("unknown launch compute rung")
    contract = json.loads(snapshot["approval_inputs"][0]["text"])
    needs_go = rung in ws.BULK_PLANS and contract.get("task_mode") not in ws.NO_CHECKIN2_TASK_MODES
    if needs_go and snapshot["go"] is None:
        raise ValueError("bulk launch has no retained GO")
    for pin in [*snapshot["approval_inputs"], *snapshot["go_inputs"]]:
        if "text" in pin and provenance.sha256_bytes(pin["text"].encode()) != pin["sha256"]:
            raise ValueError("retained authorization input changed")
    for key, tool, version in (("approval", ws.APPROVAL_GENERATOR, ws.APPROVAL_VERSION),
                               ("go", ws.CHECKIN2_GO_GENERATOR, ws.CHECKIN2_GO_VERSION)):
        pin = snapshot[key]
        if pin is None:
            if key == "approval":
                raise ValueError("launch receipt has no first approval")
            continue
        record = json.loads(pin["text"])
        if provenance.sha256_bytes(pin["text"].encode()) != pin["sha256"]:
            raise ValueError(f"retained {key} digest changed")
        if (type(record.get("schema_version")) is not int or record["schema_version"] != version
                or record.get("generated_by") != tool
                or record.get("input_fingerprint") != provenance.sha256_bytes(
                    "".join(p["sha256"] for p in snapshot[key + "_inputs"]).encode("utf-8"))):
            raise ValueError(f"retained {key} binding is invalid")
        if parse_utc(record.get("generated_utc")) > parse_utc(event["utc"]):
            raise ValueError(f"{key} was recorded after authorization")
        if key == "approval" and ws.APPROVAL_PLANS.index(record["approved_plan"]) < ws.APPROVAL_PLANS.index(rung):
            raise ValueError("launch exceeded its retained first approval")
        if key == "go":
            if record.get("decision") != "GO" or len(snapshot["go_inputs"]) < 7:
                raise ValueError("launch did not retain evidence-bound GO")
            if snapshot["go_inputs"][1]["sha256"] != snapshot["approval"]["sha256"]:
                raise ValueError("GO was bound to a different first approval")
            manifest = json.loads(snapshot["go_inputs"][2]["text"])
            comparison = json.loads(snapshot["go_inputs"][5]["text"])
            entries = [manifest[k] for k in ("produced", "reference", "comparison")] + manifest["inputs"]
            if (manifest["result"] != comparison or [p["sha256"] for p in entries]
                    != [p["sha256"] for p in snapshot["go_inputs"][3:]]):
                raise ValueError("retained waypoint comparison or evidence identities changed")


def authorized_popen(root, required_plan, command, *, context, **kwargs):
    """Check and retain approval immediately before Popen; retain a separate launch event."""
    command = list(map(str, command))
    if not command or not isinstance(context, dict):
        raise ValueError("launch needs a command and context object")
    authorization = _capture(root, required_plan)
    event = {"event": "authorized", "command": command, "context": context,
             "authorization": authorization}
    # Historical checks reject empty/future-dated operational approval records.
    _historical_errors({**event, "utc": operational_utc()})
    event = _append(root, event)
    pins = [authorization["approval"], *authorization["approval_inputs"], *authorization["go_inputs"]]
    if authorization["go"]:
        pins.append(authorization["go"])
    if any(file_hash(pin["path"]) != pin["sha256"] for pin in pins):
        raise ValueError("authorization evidence changed before Popen")
    process = subprocess.Popen(command, **kwargs)
    try:
        launched = _append(root, {"event": "launched", "authorization_sequence": event["sequence"],
                                 "authorization_sha256": event["sha256"], "pid": process.pid})
    except BaseException:
        try:
            if kwargs.get("start_new_session"):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.wait()
        raise
    process.ravel_authorization = {"sequence": launched["sequence"], "sha256": launched["sha256"]}
    return process


def audit_launches(root, *, plan_sha256=None, require_generation=False):
    try:
        events = _events(root)
        authorized, launches, started = {}, [], {}
        for event in events:
            if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
                raise ValueError("invalid authorization event schema")
            if event.get("event") == "authorized":
                _historical_errors(event)
                authorized[event["sequence"]] = event
            elif event.get("event") == "launched":
                sequence = event.get("authorization_sequence")
                if type(sequence) is not int or sequence not in authorized:
                    raise ValueError("launch has no earlier authorization event")
                auth = authorized[sequence]
                if event.get("authorization_sha256") != auth["sha256"] or type(event.get("pid")) is not int or event["pid"] <= 0:
                    raise ValueError("launch authorization digest or process identity is invalid")
                launches.append(auth)
                started[event["sequence"]] = (event, auth)
            else:
                raise ValueError("unknown authorization event")
        ledger = Path(root) / "execution_state.json"
        if ledger.exists():
            for stage, record in read_json(ledger)["stages"].items():
                if record.get("child_pid") is None:
                    continue
                receipt = record.get("authorization_receipt")
                if not isinstance(receipt, dict) or receipt.get("sequence") not in started:
                    raise ValueError(f"stage {stage} has no retained launch authorization")
                event, auth = started[receipt["sequence"]]
                if (receipt.get("sha256") != event["sha256"] or record["child_pid"] != event["pid"]
                        or auth["command"] != record["command"] or auth["context"].get("stage") != stage):
                    raise ValueError(f"stage {stage} launch authorization disagrees with its execution receipt")
        bulk = [e for e in launches if e["authorization"]["required_plan"] in ("full", "scan")]
        if plan_sha256 is not None:
            bulk = [e for e in bulk if e["context"].get("plan_sha256") == plan_sha256]
        if require_generation:
            bulk = [e for e in bulk if e["context"].get("kind") == "native-generation"
                    or e["context"].get("stage") == "madgraph"]
        if not bulk:
            raise ValueError("recorded bulk compute has no matching launch-time authorization receipt; a later GO cannot backfill it")
        return []
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        return [str(exc)]


def audit_scan_launches(root, manifest, scan):
    """An aggregate has no process of its own; audit every reported point's receipts."""
    try:
        from . import workflow_state as ws
        from .result_pack import _repo_root
        points, results = manifest["points"], scan["points"]
        if not isinstance(points, list) or not points or not isinstance(results, list) or not results:
            raise ValueError("scan authorization needs nonempty manifest and result points")
        by_tag = {}
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("tag"), str) or point["tag"] in by_tag:
                raise ValueError("scan manifest needs distinct string point tags")
            by_tag[point["tag"]] = point
        seen, paths, errors = set(), set(), []
        for row in results:
            tag = row.get("tag") if isinstance(row, dict) else None
            if not isinstance(tag, str) or tag not in by_tag or tag in seen:
                raise ValueError("scan result has a missing, duplicate or unmanifested point tag")
            seen.add(tag)
            value = by_tag[tag].get("run_dir")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"scan point {tag} needs a run_dir")
            path = Path(value)
            if not path.is_absolute():
                path = Path(_repo_root(root)) / path
            path = path.resolve()
            if path == Path(root).resolve():
                raise ValueError("scan aggregate cannot stand in for its point's launch history")
            if path in paths:
                raise ValueError("distinct scan points cannot reuse one run's launch history")
            paths.add(path)
            plan = read_json(path / "inputs/native_execution_plan.json")
            if plan.get("required_compute_plan") not in ("full", "scan"):
                raise ValueError(f"scan point {tag} has no recorded bulk compute plan")
            errors += [f"point {tag}: {e}" for e in [*ws.verify_checkin2_go(str(path)),
                        *audit_launches(path, plan_sha256=plan["plan_sha256"], require_generation=True)]]
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return [f"scan launch authorization unavailable: {exc}"]
