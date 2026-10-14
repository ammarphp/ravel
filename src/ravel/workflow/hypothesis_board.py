"""Bounded, ADVISORY commit/reveal journal for scientific hypotheses.

Participants commit a digest before any initial submission can be revealed.
All initial reveals precede followups. Exact categorical prediction vectors are
deduplicated without removing provenance, dissent, or unknown predictions.

This reader is not an isolation mechanism. Declared model, session and freshness
metadata cannot prove separate models or fresh generation, prevent out-of-band
reading, or provide OS sandboxing/privacy. Retain charter and head digests
externally: a coordinated rewrite of all local files is outside the journal's
tamper-detection boundary.

A version 2 charter is one board season. It binds
each participant to a broker identity and admits typed ``post`` entries, whose
actor is the broker's and whose custody reservation is checked against the run's
broker ledger, and code-written ``transition`` entries. Entries carry idempotent
keys, so a resumed reveal or post returns the retained entry. ``research_board``
holds the post schemas, projections and register replay.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import secrets
import stat

DEFAULT_LIMITS = {"max_records": 256, "max_payload_bytes": 65536,
                  "max_hypotheses": 64, "max_artifacts": 64}
MAX_LIMITS = {"max_records": 4096, "max_payload_bytes": 1048576,
              "max_hypotheses": 256, "max_artifacts": 256}
KINDS = {"measurement", "configuration", "source", "derivation",
         "external_reference", "narrative"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LIMITATION = ("ADVISORY only: no execution/check-in approval or scientific validity. "
              "Actor/model/session IDs and fresh_generation are declarations, not proof of "
              "distinct models, independent reasoning or fresh generation. This journal cannot "
              "prevent out-of-band reading or provide OS sandboxing/privacy. Artifact digests "
              "and frozen bytes establish local custody, not the truth or authority of narrative. "
              "Keep charter and head digests outside the board to detect coordinated local rewrites. "
              "Record publication precedes the head update. The next open rolls forward one verified "
              "record beyond the head and breaks a lock only when its recorded holder process is gone; "
              "any other mismatch or lock still refuses and requires manual inspection.")
CODE_ACTOR = "code"
CHARTER_V1 = {"schema_version", "board_id", "participants", "prediction_keys", "limits", "artifact_pins"}
EVENT_V1 = {"schema_version", "sequence", "previous_sha256", "event", "actor_id", "submission_sha256",
            "payload", "sha256"}
EVENT_V2 = EVENT_V1 | {"season", "auth"}
AUTH = {"node_id", "attempt", "action", "args_sha256", "reservation"}
POST_ACTION = "board post"
APPEND_ACTION = "board append"
# Initial commits and reveals of a version 2 season are written only by the code
# reveal path; their authentication names the season's frozen record.
CODE_AUTH = {"producer", "season_record_sha256"}
SEASON_PRODUCER = "board.season"
REGISTER_DECLARATION = {"identity_signature", "kill_condition", "reopening_trigger", "operator", "what_is_new"}
# Register transitions: the rule decides the edge and the evidence it needs. The
# evidence is a registered comparator's output (a prediction comparison naming
# the hypothesis, with an optional passed sensitivity check), a budget boundary,
# a reopening receipt that satisfies the declared predicate, or an RDJ
# authorization of exactly this transition.
TESTABLE = ("proposed", "active", "reopened", "survived_test", "inconclusive", "prediction_mismatch",
            "execution_failure")
TRANSITION_RULES = {
    "comparator_matches": {"from": TESTABLE, "to": "survived_test", "evidence": "comparison", "comparison": "matches"},
    "comparator_differs": {"from": TESTABLE, "to": "prediction_mismatch", "evidence": "comparison",
                           "comparison": "differs", "sensitivity": False},
    "scoped_exclusion": {"from": TESTABLE, "to": "rejected_in_scope", "evidence": "comparison",
                         "comparison": "differs", "sensitivity": True},
    "comparator_unknown": {"from": TESTABLE, "to": "inconclusive", "evidence": "comparison", "comparison": "unknown"},
    "execution_failed": {"from": TESTABLE, "to": "execution_failure", "evidence": "comparison", "execution": "failed"},
    "budget_exhausted": {"from": TESTABLE, "to": "parked", "evidence": "budget"},
    "reopening": {"from": ("rejected_in_scope", "parked"), "to": "reopened", "evidence": "reopening"},
    "rdj_admission": {"from": ("proposed",), "to": "active", "evidence": "rdj"},
    "rdj_supersession": {"from": TESTABLE + ("rejected_in_scope", "parked"), "to": "superseded", "evidence": "rdj"},
}


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} needs exactly {sorted(keys)}")


def _text(value, label, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a nonblank string of at most {maximum} characters")
    return value


def _id(value, label):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded identifier")
    return value


def _sha(value, label):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _list(value, label, maximum, *, empty=True):
    if not isinstance(value, list) or len(value) > maximum or (not value and not empty):
        raise ValueError(f"{label} must be a bounded {'nonempty ' if not empty else ''}list")
    return value


def _distinct(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be distinct")


def canonical_charter(charter):
    """Validate and detach the frozen charter, with unordered collections sorted."""
    version = charter.get("schema_version") if isinstance(charter, dict) else None
    if type(version) is not int or version not in (1, 2):
        raise ValueError("charter schema_version must be integer 1 or 2")
    _object(charter, CHARTER_V1 | ({"season", "mode"} if version == 2 else set()), "charter")
    _id(charter["board_id"], "board_id")
    if version == 2:
        _id(charter["season"], "season")
        if charter["mode"] not in ("production", "evaluation"):
            raise ValueError("charter mode must be production or evaluation")
    _object(charter["limits"], DEFAULT_LIMITS, "limits")
    for key, maximum in MAX_LIMITS.items():
        value = charter["limits"][key]
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"{key} must be an exact integer from 1 to {maximum}")
    participants = _list(charter["participants"], "participants", 64, empty=False)
    for row in participants:
        _object(row, {"actor_id", "model_id", "session_id", "fresh_generation"}
                | ({"broker"} if version == 2 else set()), "participant")
        for key in ("actor_id", "session_id"):
            _id(row[key], key)
        if version == 2:
            if row["actor_id"] == CODE_ACTOR:
                raise ValueError("the code actor is reserved for code-written entries")
            _object(row["broker"], {"node_id", "attempt"}, "participant broker identity")
            _id(row["broker"]["node_id"], "broker node_id")
            if type(row["broker"]["attempt"]) is not int or row["broker"]["attempt"] < 1:
                raise ValueError("broker attempt must be a positive integer")
        _text(row["model_id"], "model_id", 200)
        if type(row["fresh_generation"]) is not bool:
            raise ValueError("fresh_generation must be a declared boolean")
    for key in ("actor_id", "session_id"):
        _distinct([row[key] for row in participants], key)
    if version == 2:
        _distinct([_digest(row["broker"]) for row in participants], "participant broker identities")
    if (charter["limits"]["max_records"] < 2 * len(participants)
            or charter["limits"]["max_hypotheses"] < len(participants)):
        raise ValueError("limits must accommodate one initial submission per participant")
    keys = _list(charter["prediction_keys"], "prediction_keys", 64, empty=False)
    for key in keys:
        _id(key, "prediction key")
    _distinct(keys, "prediction keys")
    pins = _list(charter["artifact_pins"], "artifact_pins", charter["limits"]["max_artifacts"])
    for pin in pins:
        _object(pin, {"id", "kind", "sha256", "size", "custody"}, "artifact pin")
        _id(pin["id"], "artifact id")
        _sha(pin["sha256"], "artifact digest")
        if (not isinstance(pin["kind"], str) or pin["kind"] not in KINDS
                or not isinstance(pin["custody"], str) or pin["custody"] not in {"declared_digest", "frozen_bytes"}):
            raise ValueError("artifact kind or custody is invalid")
        if type(pin["size"]) is not int or not 0 <= pin["size"] <= charter["limits"]["max_payload_bytes"]:
            raise ValueError("artifact size must be a bounded exact integer")
    _distinct([pin["id"] for pin in pins], "artifact ids")
    result = {**charter, "participants": sorted(participants, key=lambda row: row["actor_id"]),
              "prediction_keys": sorted(keys), "artifact_pins": sorted(pins, key=lambda row: row["id"])}
    return json.loads(_bytes(result))


def canonical_payload(charter, payload):
    """Validate categorical claims. Only JSON null represents an unknown prediction."""
    charter = canonical_charter(charter)
    _object(payload, {"schema_version", "actor_id", "session_id", "nonce", "hypotheses"}, "submission")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("submission schema_version must be integer 1")
    actor = next((row for row in charter["participants"] if row["actor_id"] == payload["actor_id"]), None)
    if actor is None or payload["session_id"] != actor["session_id"]:
        raise ValueError("submission actor/session is outside the frozen charter")
    _text(payload["nonce"], "nonce", 128)
    if len(payload["nonce"]) < 16:
        raise ValueError("nonce must contain at least 16 characters")
    hypotheses = _list(payload["hypotheses"], "hypotheses", charter["limits"]["max_hypotheses"], empty=False)
    normalized = []
    pins = {pin["id"]: pin for pin in charter["artifact_pins"]}
    for hypothesis in hypotheses:
        _object(hypothesis, {"id", "statement", "predictions", "artifact_refs", "contradicts"}
                | ({"register"} if isinstance(hypothesis, dict) and "register" in hypothesis else set()), "hypothesis")
        if "register" in hypothesis:
            # The research register declaration (section 18); the cycle replay validates its content.
            _object(hypothesis["register"], REGISTER_DECLARATION, "hypothesis register declaration")
        _id(hypothesis["id"], "hypothesis id")
        _text(hypothesis["statement"], "statement")
        _object(hypothesis["predictions"], charter["prediction_keys"], "predictions")
        for value in hypothesis["predictions"].values():
            if value is not None:
                _text(value, "categorical prediction", 128)
                if value != value.strip():
                    raise ValueError("categorical predictions cannot contain surrounding whitespace")
        refs = _list(hypothesis["artifact_refs"], "artifact_refs", charter["limits"]["max_artifacts"])
        for ref in refs:
            _object(ref, {"id", "kind", "sha256"}, "artifact reference")
            _id(ref["id"], "artifact reference id")
            pin = pins.get(ref["id"])
            if pin is None or ref != {key: pin[key] for key in ("id", "kind", "sha256")}:
                raise ValueError("artifact reference must match a charter pin's identity, kind and digest")
        _distinct([ref["id"] for ref in refs], "artifact references")
        contradicts = _list(hypothesis["contradicts"], "contradicts", charter["limits"]["max_hypotheses"])
        for target in contradicts:
            _sha(target, "contradiction target")
        _distinct(contradicts, "contradiction targets")
        normalized.append({**hypothesis, "artifact_refs": sorted(refs, key=lambda ref: ref["id"]),
                           "contradicts": sorted(contradicts)})
    _distinct([row["id"] for row in normalized], "hypothesis ids")
    result = {**payload, "hypotheses": sorted(normalized, key=lambda row: row["id"])}
    if len(_bytes(result)) > charter["limits"]["max_payload_bytes"]:
        raise ValueError("submission exceeds the frozen payload byte bound")
    return json.loads(_bytes(result))


def submission_digest(charter, payload):
    """Commit to the entire canonical payload and the participant/evidence charter."""
    charter = canonical_charter(charter)
    return _digest({"charter_sha256": _digest(charter), "payload": canonical_payload(charter, payload)})


def prediction_signature(predictions):
    """Exact content signature; names, authors, prose and artifacts do not add novelty."""
    if not isinstance(predictions, dict) or not predictions:
        raise ValueError("predictions must be a nonempty mapping")
    for key, value in predictions.items():
        _id(key, "prediction key")
        if value is not None:
            _text(value, "categorical prediction", 128)
    return _digest(predictions)


def _hypothesis_digest(hypothesis):
    return _digest({key: value for key, value in hypothesis.items() if key != "id"})


def hypothesis_ref(actor_id, hypothesis):
    """Opaque register reference: distinct actors with equal content stay distinct entries."""
    return _digest({"actor_id": actor_id, "hypothesis": hypothesis})


def _absolute(path):
    value = Path(path).expanduser().absolute()
    if ".." in value.parts:
        raise ValueError("board paths cannot traverse parent components")
    return value


def _directory(path):
    """Open every path component without following symlinks, retaining a directory fd."""
    path = _absolute(path)
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ValueError("board paths must be existing directories without symlinks") from exc


def _read_bytes(directory, name, maximum):
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("board inputs must be regular files")
            data = stream.read(maximum + 1)
            if len(data) > maximum:
                raise ValueError("board file exceeds its byte bound")
            return data
    except OSError as exc:
        raise ValueError(f"board file is missing, unreadable or a symlink: {name}") from exc


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON fields are invalid")
        result[key] = value
    return result


def _read_json(directory, name, maximum):
    try:
        return json.loads(_read_bytes(directory, name, maximum), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed board JSON: {name}") from exc


def _write(directory, name, content, *, replace=False):
    """Atomically publish bytes; new immutable files use an exclusive hard link."""
    temporary = ".pending-" + secrets.token_hex(16)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _holder_gone(raw):
    """True only for a lock this module wrote whose recorded process no longer exists."""
    try:
        holder = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        return False
    if (not isinstance(holder, dict) or set(holder) != {"pid", "token"} or type(holder["pid"]) is not int
            or holder["pid"] <= 0 or holder["pid"] == os.getpid()
            or not isinstance(holder["token"], str) or not re.fullmatch(r"[0-9a-f]{32}", holder["token"])):
        return False
    try:
        os.kill(holder["pid"], 0)  # existence probe only; no signal is delivered
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _break_stale_lock(directory):
    try:
        raw = _read_bytes(directory, ".lock", 256)
    except ValueError:
        return False
    if not _holder_gone(raw):
        return False
    # Move the judged file aside, then confirm it is the one judged before deleting it.
    aside = ".stale-lock-" + secrets.token_hex(16)
    try:
        os.rename(".lock", aside, src_dir_fd=directory, dst_dir_fd=directory)
    except FileNotFoundError:
        return True
    if _read_bytes(directory, aside, 256) != raw:
        try:
            os.link(aside, ".lock", src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            pass
        os.unlink(aside, dir_fd=directory)
        return False
    os.unlink(aside, dir_fd=directory)
    return True


def _acquire(directory):
    body = _bytes({"pid": os.getpid(), "token": secrets.token_hex(16)})
    for attempt in range(2):
        try:
            descriptor = os.open(".lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
        except FileExistsError as exc:
            if attempt == 0 and _break_stale_lock(directory):
                continue
            raise ValueError("board is locked; a lock with a live or unrecognised holder "
                             "requires manual inspection") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
        return


def _discard_pending(directory):
    """Unpublished temporaries are orphans once the exclusive lock is held."""
    with os.scandir(directory) as entries:
        names = [entry.name for entry in itertools.islice(entries, 8192)
                 if entry.name.startswith(".pending-") and entry.is_file(follow_symlinks=False)]
    for name in names:
        os.unlink(name, dir_fd=directory)


@contextmanager
def _locked(root, *, rundir=None):
    directory = _directory(root)
    locked = False
    try:
        _acquire(directory)
        locked = True
        _recover(directory, rundir)
        yield directory
    finally:
        if locked:
            os.unlink(".lock", dir_fd=directory)
        os.close(directory)


def create(root, charter, *, artifacts=None):
    """Create an exclusive board. Optional frozen bytes must match their charter pins.

    ``artifacts`` maps frozen pin IDs to source paths. Sources and board paths may
    not traverse symlinks. Declared-only pins are never silently upgraded to custody.
    The destination's parent must already exist; an existing destination is refused.
    """
    charter = canonical_charter(charter)
    frozen = {pin["id"]: pin for pin in charter["artifact_pins"] if pin["custody"] == "frozen_bytes"}
    artifacts = {} if artifacts is None else artifacts
    if not isinstance(artifacts, dict) or set(artifacts) != set(frozen):
        raise ValueError("artifacts must supply exactly the frozen_bytes pin IDs")
    content = {}
    for identity, pin in frozen.items():
        source = _absolute(artifacts[identity])
        directory = _directory(source.parent)
        try:
            data = _read_bytes(directory, source.name, charter["limits"]["max_payload_bytes"])
        finally:
            os.close(directory)
        if len(data) != pin["size"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise ValueError("frozen artifact bytes do not match the charter pin")
        content[identity] = data
    root = _absolute(root)
    if not root.name:
        raise ValueError("board destination must name a new directory")
    parent = _directory(root.parent)
    try:
        os.mkdir(root.name, mode=0o700, dir_fd=parent)
        directory = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        for name in ("records", "artifacts"):
            os.mkdir(name, mode=0o700, dir_fd=directory)
        artifact_directory = os.open("artifacts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            for identity, data in content.items():
                _write(artifact_directory, identity + ".bin", data)
        finally:
            os.close(artifact_directory)
        digest = _digest(charter)
        _write(directory, "charter.json", _bytes({"charter": charter, "sha256": digest}))
        _write(directory, "head.json", _bytes({"schema_version": 1, "sequence": 0, "sha256": digest}))
    finally:
        os.close(directory)
    return snapshot(root)


def _key(charter, event):
    """Idempotent entry key: (season, actor, kind) plus the kind's own discriminator."""
    kind, actor, payload = event["event"], event["actor_id"], event["payload"]
    extra = {"append": lambda: [payload["nonce"]], "post": lambda: [payload["actor_sequence"]],
             "transition": lambda: [payload["hypothesis"], payload["to"], payload["rule_id"],
                                    payload["receipt_pin"]["sha256"]]}.get(kind, list)
    return _bytes([charter["season"], actor, kind, *extra()])


def _content(event):
    # A resumed post arrives through a new broker call, so its authentication differs.
    return {key: event[key] for key in ("event", "actor_id", "submission_sha256", "payload")}


def _custody(state, event, label):
    """Custody ledgers of the run; a new entry always needs them, a replay may be structural."""
    if state["rundir"] is None:
        if event.get("sha256") is None:
            raise ValueError(f"{label} needs the run directory to verify broker custody")
        return None
    from . import broker
    return broker, Path(state["rundir"])


def _verify_receipt(state, event, pin, label):
    custody = _custody(state, event, label)
    if custody is None:
        return
    broker, rundir = custody
    try:
        broker.verify_broker_receipt(rundir, pin, verify_outputs=False)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise ValueError(f"{label} receipt is not in the broker index") from exc


def _authenticate(charter, state, event, action=POST_ACTION):
    """The actor of a post or append is the broker's: charter binding and custody reservation must agree."""
    auth = event["auth"]
    label = "post" if action == POST_ACTION else "append"
    if not isinstance(auth, dict):
        raise ValueError(f"{label} requires broker authentication on a version 2 season")
    _object(auth, AUTH, f"{label} authentication")
    participant = next(row for row in charter["participants"] if row["actor_id"] == event["actor_id"])
    if {"node_id": auth["node_id"], "attempt": auth["attempt"]} != participant["broker"]:
        raise ValueError(f"{label} broker identity does not match the participant's charter binding")
    if auth["action"] != action or not isinstance(auth["reservation"], str) or not auth["reservation"]:
        raise ValueError(f"{label} authentication must name its broker reservation")
    _sha(auth["args_sha256"], f"{label} broker request digest")
    if auth["args_sha256"] != _digest({label: event["payload"]}):
        raise ValueError(f"{label} broker request does not match the {label} body")
    if auth["reservation"] in state["reservations"]:
        raise ValueError("post broker reservation already authorised an entry")
    custody = _custody(state, event, "post authentication")
    if custody is not None:
        broker, rundir = custody
        rows = [row["record"] for row in broker.ledger(rundir, "broker-reservations")]
        if not any(row.get("receipt_id") == auth["reservation"] and row.get("node_id") == auth["node_id"]
                   and row.get("attempt") == auth["attempt"] and row.get("action") == action
                   and row.get("args_sha256") == auth["args_sha256"] for row in rows):
            raise ValueError(f"{label} lacks its broker reservation in custody")
    state["reservations"].add(auth["reservation"])


def _authenticate_code(charter, state, event):
    """A version 2 commit or reveal is written by the code reveal path for this season."""
    auth = event["auth"]
    if not isinstance(auth, dict):
        raise ValueError("version 2 commits and reveals are written only by the code reveal path")
    _object(auth, CODE_AUTH, "code reveal authentication")
    if auth["producer"] != SEASON_PRODUCER:
        raise ValueError("version 2 commits and reveals are written only by the code reveal path")
    _sha(auth["season_record_sha256"], "season record digest")
    custody = _custody(state, event, "code reveal authentication")
    if custody is None:
        return
    _, rundir = custody
    path = rundir / "research/board" / (charter["season"] + ".season.json")
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("the season's frozen record is missing") from exc
    if (_digest(record) != auth["season_record_sha256"] or record.get("kind") != "board-season-record"
            or record.get("charter", {}).get("season") != charter["season"]
            or event["actor_id"] not in {p.get("actor_id") for p in record["charter"].get("participants", [])}):
        raise ValueError("code reveal authentication does not name this season's frozen record")


def _apply_post(charter, state, event):
    from . import research_board
    if state["reveals"] != state["actors"]:
        raise ValueError("posts require every initial submission to be revealed")
    body = research_board.validate_post(charter, event["payload"])
    if body != event["payload"] or event["submission_sha256"] != _digest(body):
        raise ValueError("post entry is not its canonical body")
    actor = event["actor_id"]
    if body["actor_sequence"] != state["actor_sequences"].get(actor, 0) + 1:
        raise ValueError("post actor_sequence must be the actor's next sequence")
    if not set(body["parents"]) <= {row["sha256"] for row in state["entries"]}:
        raise ValueError("post parents must be retained entries")
    fields, kind = body["fields"], body["kind"]
    refs = {"prediction": lambda: [fields["hypothesis"], *fields["discriminates_against"]],
            "rival": lambda: [fields["world_a"], fields["world_b"]],
            "evidence_request": lambda: fields["discriminates"],
            "finding": lambda: fields["affects"], "pre_mortem": lambda: fields["affects"],
            "refutation": lambda: [fields["target"]["hypothesis"]],
            "hypothesis": lambda: fields["rival_of"]}.get(kind, list)()
    if not set(refs) <= state["refs"]:
        raise ValueError("post references must name retained hypotheses")
    if kind == "refutation" and fields["target"].get("key") not in charter["prediction_keys"]:
        raise ValueError("refutation target key must be a charter prediction key")
    _authenticate(charter, state, event)
    if kind in research_board.RECEIPT_KINDS:
        _verify_receipt(state, event, fields["receipt_pin"], kind)
    if kind == "hypothesis":
        if (actor, fields["id"]) in state["hypothesis_ids"]:
            raise ValueError("hypothesis identity is immutable; append a new identifier")
        if state["hypothesis_count"] + 1 > charter["limits"]["max_hypotheses"]:
            raise ValueError("board exceeds the frozen total hypothesis bound")
        state["hypothesis_count"] += 1
        state["hypothesis_ids"].add((actor, fields["id"]))
        ref = hypothesis_ref(actor, fields)
        state["refs"].add(ref)
        state["status"][ref] = "proposed"
        if "register" in fields:
            _object(fields["register"], REGISTER_DECLARATION, "hypothesis register declaration")
            state["declarations"][ref] = fields["register"]
    state["actor_sequences"][actor] = body["actor_sequence"]


def register_id(ref):
    """The identifier a board hypothesis has in the research-cycle register (bounded, deterministic)."""
    return "board-" + ref[:40]


def _declaration(state, ref):
    return state["declarations"].get(ref)


def transition_evidence(rundir, ref, rule_id, receipt_pin, declaration):
    """Code reads the transition evidence named by ``receipt_pin``; nothing is caller supplied.

    Returns the snapshots retained in the transition entry (digest -> text) and the
    observation the research register replays. A comparator rule needs a successful
    ``registered_validator`` broker receipt whose outputs hold a ``prediction-comparison``
    record naming this hypothesis (and, for a scoped exclusion, a passed
    ``sensitivity-check``). Other rules read their typed receipt from the run.
    """
    rule = TRANSITION_RULES[rule_id]
    from . import broker
    run = Path(rundir)
    def text(path):
        raw = path.read_bytes().decode("utf-8")
        return raw, json.loads(raw)
    snapshots, observation = {}, None
    if rule["evidence"] == "comparison":
        receipt = broker.verify_broker_receipt(run, receipt_pin, verify_outputs=True)
        if receipt.get("status") != "ok" or receipt.get("derivation") != "registered_validator":
            raise ValueError("transition requires a successful registered comparator receipt")
        found = {}
        for pin in receipt["output_pins"]:
            raw, value = text(broker.locate(run, pin["path"]))
            if isinstance(value, dict) and value.get("kind") in {"prediction-comparison", "sensitivity-check"}:
                found.setdefault(value["kind"], (pin, raw, value))
        if "prediction-comparison" not in found:
            raise ValueError("comparator receipt holds no prediction-comparison output")
        cpin, craw, compared = found["prediction-comparison"]
        if compared.get("hypothesis_id") != register_id(ref):
            raise ValueError("comparator output names another hypothesis")
        status = compared.get("execution_status")
        if rule.get("execution") == "failed":
            if status != "failed":
                raise ValueError("execution_failed needs a failed comparator execution")
        elif status not in ("success", "succeeded") or compared.get("comparison") != rule["comparison"]:
            raise ValueError(f"{rule_id} needs a successful {rule['comparison']} comparison")
        sensitivity = None
        if rule.get("sensitivity"):
            if declaration is None:
                raise ValueError("a scoped exclusion needs the hypothesis register declaration")
            if "sensitivity-check" not in found or found["sensitivity-check"][2].get("status") != "passed":
                raise ValueError("a scoped exclusion needs a passed sensitivity check")
            spin, sraw, _ = found["sensitivity-check"]
            sensitivity = {"path": spin["path"], "sha256": spin["sha256"]}
            snapshots[spin["sha256"]] = sraw
        elif "sensitivity-check" in found and rule_id == "comparator_differs":
            raise ValueError("a differing comparison with a passed sensitivity check is a scoped exclusion")
        snapshots[cpin["sha256"]] = craw
        observation = {"execution_status": status, "comparison": compared.get("comparison"),
                       "residual": compared.get("residual"), "experiment_id": compared.get("experiment_id"),
                       "comparator": {"path": cpin["path"], "sha256": cpin["sha256"]}, "sensitivity": sensitivity}
    else:
        path = broker.locate(run, receipt_pin["path"])
        raw, value = text(path)
        if hashlib.sha256(raw.encode()).hexdigest() != receipt_pin["sha256"]:
            raise ValueError("transition receipt bytes differ from their pin")
        snapshots[receipt_pin["sha256"]] = raw
        if rule["evidence"] == "budget":
            if (value.get("kind") != "research-budget-boundary" or type(value.get("spent")) not in (int, float)
                    or type(value.get("cap")) not in (int, float) or value["cap"] <= 0 or value["spent"] < value["cap"]):
                raise ValueError("budget_exhausted needs an exhausted budget receipt")
            observation = {"execution_status": "budget_exhausted", "comparison": "unknown",
                           "residual": None, "experiment_id": None, "budget_receipt": dict(receipt_pin)}
        elif rule["evidence"] == "reopening":
            predicate = (declaration or {}).get("reopening_trigger")
            if not isinstance(predicate, dict) or value.get("kind") != predicate.get("kind") \
                    or value.get(predicate.get("field")) != predicate.get("value"):
                raise ValueError("reopening needs a receipt that satisfies the declared predicate")
        else:
            action = {"scope": "board_transition", "hypothesis": ref, "to": rule["to"], "rule_id": rule_id}
            if (value.get("kind") != "rdj-receipt" or value.get("outcome") != "authorize"
                    or value.get("action_digest") != _digest(action)):
                raise ValueError(f"{rule_id} needs an RDJ authorization of exactly this transition")
    return snapshots, observation


def _apply_transition(charter, state, event):
    from . import research_board
    record = event["payload"]
    _object(record, {"hypothesis", "from", "to", "rule_id", "receipt_pin", "evidence_snapshots", "observation"},
            "transition")
    if event["auth"] is not None:
        raise ValueError("transitions are code-written and carry no broker authentication")
    if record["hypothesis"] not in state["refs"]:
        raise ValueError("transition must name a retained hypothesis")
    if record["to"] not in research_board.REGISTER_STATES:
        raise ValueError("transition target is not a register state")
    if record["from"] != state["status"][record["hypothesis"]] or record["to"] == record["from"]:
        raise ValueError("transition must start from the computed register state")
    _id(record["rule_id"], "transition rule_id")
    rule = TRANSITION_RULES.get(record["rule_id"])
    if rule is None:
        raise ValueError("transition rule is not a registered register rule")
    if record["to"] != rule["to"] or record["from"] not in rule["from"]:
        raise ValueError(f"rule {record['rule_id']} does not permit {record['from']} -> {record['to']}")
    _object(record["receipt_pin"], {"path", "sha256"}, "transition receipt pin")
    _sha(record["receipt_pin"]["sha256"], "transition receipt digest")
    if event["submission_sha256"] != _digest(record):
        raise ValueError("transition entry digest does not match its record")
    declaration = _declaration(state, record["hypothesis"])
    custody = _custody(state, event, "transition")
    if custody is not None:
        # The retained evidence must be exactly what code reads from the run now.
        snapshots, observation = transition_evidence(custody[1], record["hypothesis"], record["rule_id"],
                                                     record["receipt_pin"], declaration)
        if snapshots != record["evidence_snapshots"] or observation != record["observation"]:
            raise ValueError("transition evidence differs from the receipt it names")
    else:
        for digest, raw in record["evidence_snapshots"].items():
            if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != digest:
                raise ValueError("transition evidence snapshot changed")
    state["status"][record["hypothesis"]] = record["to"]


def _apply(charter, state, event):
    actor_id, kind = event["actor_id"], event["event"]
    _id(actor_id, "event actor_id")
    _text(kind, "event kind", 100)
    version = charter["schema_version"]
    if version == 2:
        if event["season"] != charter["season"]:
            raise ValueError("entry season differs from the charter season")
        if kind == "transition" and actor_id == CODE_ACTOR:
            _apply_transition(charter, state, event)
            state["keys"][_key(charter, event)] = event
            return
    if actor_id not in state["actors"]:
        raise ValueError("event actor is outside the frozen charter")
    if kind == "post" and version == 2:
        _apply_post(charter, state, event)
        state["keys"][_key(charter, event)] = event
        return
    if version == 2 and _key(charter, event) in state["keys"]:
        raise ValueError("duplicate entry for an idempotent key")
    if version == 2:
        if kind in {"commit", "reveal"}:
            _authenticate_code(charter, state, event)
        elif kind == "append":
            _authenticate(charter, state, event, APPEND_ACTION)
    if version == 2:
        state["keys"][_key(charter, event)] = event
    if kind == "commit":
        if event["payload"] is not None or actor_id in state["commits"] or state["reveals"]:
            raise ValueError("invalid or duplicate initial commit")
        state["commits"][actor_id] = event["submission_sha256"]
        return
    if kind not in {"reveal", "append"}:
        raise ValueError("unknown hypothesis board event")
    payload = canonical_payload(charter, event["payload"])
    if payload != event["payload"] or payload["actor_id"] != actor_id:
        raise ValueError("event payload is not the matching canonical submission")
    if submission_digest(charter, payload) != event["submission_sha256"]:
        raise ValueError("submission digest does not match revealed payload")
    if kind == "reveal":
        if set(state["commits"]) != state["actors"]:
            raise ValueError("initial reveal barrier requires every participant to commit")
        if actor_id in state["reveals"]:
            raise ValueError("duplicate initial reveal")
        if state["commits"][actor_id] != event["submission_sha256"]:
            raise ValueError("initial reveal does not match the sealed commit digest")
        if any(row["contradicts"] for row in payload["hypotheses"]):
            raise ValueError("initial sealed submissions cannot target unpublished hypotheses")
    elif state["reveals"] != state["actors"]:
        raise ValueError("followups require every initial submission to be revealed")
    if (actor_id, payload["nonce"]) in state["nonces"]:
        raise ValueError("submission nonce has already been used by this actor")
    if state["hypothesis_count"] + len(payload["hypotheses"]) > charter["limits"]["max_hypotheses"]:
        raise ValueError("board exceeds the frozen total hypothesis bound")
    for row in payload["hypotheses"]:
        if (actor_id, row["id"]) in state["hypothesis_ids"]:
            raise ValueError("hypothesis identity is immutable; append a new identifier")
        if not set(row["contradicts"]) <= state["hypothesis_digests"]:
            raise ValueError("contradiction targets must refer to previously retained hypotheses")
    state["nonces"].add((actor_id, payload["nonce"]))
    state["hypothesis_count"] += len(payload["hypotheses"])
    for row in payload["hypotheses"]:
        state["hypothesis_ids"].add((actor_id, row["id"]))
        state["hypothesis_digests"].add(_hypothesis_digest(row))
        ref = hypothesis_ref(actor_id, row)
        state["refs"].add(ref)
        state["status"][ref] = "proposed"
        if "register" in row:
            state["declarations"][ref] = row["register"]
    if kind == "reveal":
        state["reveals"].add(actor_id)
    state["submissions"].append({"phase": "initial" if kind == "reveal" else "followup",
                                 "submission_sha256": event["submission_sha256"], "payload": payload})


def _recover(directory, rundir):
    """Close the publish-before-head window: roll forward one verified record, never more."""
    _discard_pending(directory)
    try:
        records = os.open("records", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError:
        return
    try:
        _discard_pending(records)
        head = _read_json(directory, "head.json", 1024)
        sequence = head.get("sequence") if isinstance(head, dict) else None
        if type(sequence) is not int or sequence < 0:
            return
        with os.scandir(records) as entries:
            names = sorted(entry.name for entry in itertools.islice(entries, MAX_LIMITS["max_records"] + 2))
        expected = [f"{index:08d}.json" for index in range(1, sequence + 2)]
        if names != expected:
            return
        event = _read_json(records, expected[-1], MAX_LIMITS["max_payload_bytes"] + 4096)
    except ValueError:
        return
    finally:
        os.close(records)
    if not isinstance(event, dict) or not SHA256.fullmatch(str(event.get("sha256"))):
        return
    if event.get("previous_sha256") != head.get("sha256"):
        raise ValueError("a record beyond the retained head does not extend it; manual inspection required")
    registration = _read_json(directory, "charter.json", 262144)
    if rundir is None and registration.get("charter", {}).get("schema_version") == 2:
        # A version 2 record rolls forward only after its custody is verified.
        return
    candidate = {"schema_version": 1, "sequence": sequence + 1, "sha256": event["sha256"]}
    try:
        _read(directory, rundir=rundir, head=candidate)
    except ValueError as exc:
        if rundir is not None:
            # Our writer verifies before it publishes, so an unverifiable record is
            # not a crashed write. It is moved aside, retained and never applied.
            name = expected[-1]
            records = os.open("records", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                try:
                    os.mkdir("quarantine", dir_fd=directory)
                except FileExistsError:
                    pass
                quarantine = os.open("quarantine", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    os.rename(name, f"{name}.{secrets.token_hex(4)}", src_dir_fd=records, dst_dir_fd=quarantine)
                finally:
                    os.close(quarantine)
            finally:
                os.close(records)
            return
        raise ValueError("a record beyond the retained head does not verify; manual inspection required") from exc
    _write(directory, "head.json", _bytes(candidate), replace=True)


def _read(directory, *, rundir=None, head=None):
    registration = _read_json(directory, "charter.json", 262144)
    _object(registration, {"charter", "sha256"}, "charter registration")
    charter = canonical_charter(registration["charter"])
    if charter != registration["charter"] or _digest(charter) != registration["sha256"]:
        raise ValueError("frozen charter digest changed")
    head = _read_json(directory, "head.json", 1024) if head is None else head
    _object(head, {"schema_version", "sequence", "sha256"}, "head checkpoint")
    if (type(head["schema_version"]) is not int or head["schema_version"] != 1
            or type(head["sequence"]) is not int or not 0 <= head["sequence"] <= charter["limits"]["max_records"]):
        raise ValueError("invalid head checkpoint")
    _sha(head["sha256"], "head digest")
    state = {"actors": {row["actor_id"] for row in charter["participants"]}, "commits": {},
             "reveals": set(), "nonces": set(), "hypothesis_count": 0,
             "hypothesis_ids": set(), "hypothesis_digests": set(), "submissions": [],
             "entries": [], "keys": {}, "refs": set(), "status": {}, "reservations": set(),
             "actor_sequences": {}, "declarations": {}, "rundir": rundir}
    version = charter["schema_version"]
    previous = registration["sha256"]
    try:
        records = os.open("records", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as exc:
        raise ValueError("board custody directories are missing or symlinks") from exc
    try:
        artifacts = os.open("artifacts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as exc:
        os.close(records)
        raise ValueError("board custody directories are missing or symlinks") from exc
    try:
        with os.scandir(records) as entries:
            names = [entry.name for entry in itertools.islice(entries, charter["limits"]["max_records"] + 1)]
        expected = [f"{sequence:08d}.json" for sequence in range(1, head["sequence"] + 1)]
        if sorted(names) != expected:
            raise ValueError("journal records were added, removed or renamed outside the retained head")
        for sequence, name in enumerate(expected, 1):
            event = _read_json(records, name, charter["limits"]["max_payload_bytes"] + 4096)
            _object(event, EVENT_V2 if version == 2 else EVENT_V1, "journal event")
            if (type(event["schema_version"]) is not int or event["schema_version"] != version
                    or type(event["sequence"]) is not int or event["sequence"] != sequence
                    or event["previous_sha256"] != previous
                    or _digest({key: value for key, value in event.items() if key != "sha256"}) != event["sha256"]):
                raise ValueError("journal event digest or hash chain changed")
            _sha(event["submission_sha256"], "submission digest")
            _apply(charter, state, event)
            state["entries"].append(event)
            previous = event["sha256"]
        if previous != head["sha256"]:
            raise ValueError("journal does not match the retained head checkpoint")
        for pin in charter["artifact_pins"]:
            if pin["custody"] == "frozen_bytes":
                data = _read_bytes(artifacts, pin["id"] + ".bin", charter["limits"]["max_payload_bytes"])
                if len(data) != pin["size"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
                    raise ValueError("frozen artifact custody changed")
    finally:
        os.close(records)
        os.close(artifacts)
    return charter, registration["sha256"], head, state


def _record(root, kind, actor_id, submission_sha256, payload=None, *, auth=None, rundir=None, prepare=None):
    _id(actor_id, "actor_id")
    with _locked(root, rundir=rundir) as directory:
        charter, _, head, state = _read(directory, rundir=rundir)
        if prepare is not None:
            payload = prepare(state)
            submission_sha256 = _digest(payload)
        _sha(submission_sha256, "submission digest")
        if payload is not None and kind in {"reveal", "append"}:
            payload = canonical_payload(charter, payload)
        event = {"schema_version": charter["schema_version"], "sequence": head["sequence"] + 1,
                 "previous_sha256": head["sha256"], "event": kind, "actor_id": actor_id,
                 "submission_sha256": submission_sha256, "payload": payload}
        if charter["schema_version"] == 2:
            event.update(season=charter["season"], auth=auth)
            retained = state["keys"].get(_key(charter, event))
            if retained is not None:
                if _content(retained) != _content(event):
                    raise ValueError("idempotent key reused with different content")
                return retained
        if head["sequence"] >= charter["limits"]["max_records"]:
            raise ValueError("board exceeds the frozen record bound")
        _apply(charter, state, event)
        event["sha256"] = _digest(event)
        records = os.open("records", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            _write(records, f"{event['sequence']:08d}.json", _bytes(event))
        finally:
            os.close(records)
        _write(directory, "head.json", _bytes({"schema_version": 1, "sequence": event["sequence"],
                                                "sha256": event["sha256"]}), replace=True)
        return event


def commit(root, actor_id, submission_sha256, *, auth=None, rundir=None):
    """Append only a sealed digest; no payload is stored at this stage.

    On a version 2 season only the code reveal path commits, with ``auth`` naming
    the season's frozen record (``research_board.reveal_season``).
    """
    return _record(root, "commit", actor_id, submission_sha256, auth=auth, rundir=rundir)


def post(root, body, *, actor_id, auth, rundir):
    """Append a typed post whose actor and reservation come from the broker (``research_board.post_action``)."""
    with _locked(root, rundir=rundir) as directory:
        charter, _, _, _ = _read(directory, rundir=rundir)
    if charter["schema_version"] != 2:
        raise ValueError("posts require a version 2 (season) charter")
    from . import research_board
    body = research_board.validate_post(charter, body)
    return _record(root, "post", actor_id, _digest(body), body, auth=auth, rundir=rundir)


def transition(root, *, hypothesis, to, rule_id, receipt_pin, rundir):
    """Code-written register transition from its rule and the evidence code reads from the receipt.

    The starting state is computed from the journal; the edge must be one the rule
    permits; the evidence snapshots and the observation are read here, never supplied.
    """
    if rundir is None:
        raise ValueError("a transition needs the run directory to read its evidence")
    def prepare(state):
        if hypothesis not in state["status"]:
            raise ValueError("transition must name a retained hypothesis")
        if rule_id not in TRANSITION_RULES:
            raise ValueError("transition rule is not a registered register rule")
        current = state["status"][hypothesis]
        rule = TRANSITION_RULES[rule_id]
        if to != rule["to"] or (current not in rule["from"] and not any(
                row["event"] == "transition" and row["payload"]["hypothesis"] == hypothesis
                and row["payload"]["to"] == to and row["payload"]["rule_id"] == rule_id for row in state["entries"])):
            raise ValueError(f"rule {rule_id} does not permit {current} -> {to}")
        for row in state["entries"]:
            if (row["event"] == "transition" and row["payload"]["hypothesis"] == hypothesis
                    and row["payload"]["to"] == to and row["payload"]["rule_id"] == rule_id
                    and row["payload"]["receipt_pin"] == receipt_pin):
                return row["payload"]  # a resumed transition returns the retained entry
        snapshots, observation = transition_evidence(rundir, hypothesis, rule_id, receipt_pin,
                                                     _declaration(state, hypothesis))
        return {"hypothesis": hypothesis, "from": current, "to": to, "rule_id": rule_id,
                "receipt_pin": receipt_pin, "evidence_snapshots": snapshots, "observation": observation}
    return _record(root, "transition", CODE_ACTOR, None, rundir=rundir, prepare=prepare)


def journal(root, *, rundir=None):
    """Verified entries in order, the head, and the computed snapshot from the same read.

    With ``rundir`` every post's broker reservation and every receipt is re-verified
    against the run's custody ledgers; without it the replay is structural only.
    """
    with _locked(root, rundir=rundir) as directory:
        charter, charter_digest, head, state = _read(directory, rundir=rundir)
    return {"charter": charter, "charter_sha256": charter_digest, "head": head,
            "entries": state["entries"], "snapshot": _view(charter, charter_digest, head, state)}


def _publish(root, kind, payload, *, auth=None, rundir=None):
    # _record rereads and validates under its exclusive lock before any write.
    with _locked(root, rundir=rundir) as directory:
        charter, _, _, _ = _read(directory, rundir=rundir)
        canonical = canonical_payload(charter, payload)
        digest = submission_digest(charter, canonical)
    return _record(root, kind, canonical["actor_id"], digest, canonical, auth=auth, rundir=rundir)


def reveal(root, payload, *, auth=None, rundir=None):
    """Reveal exactly the initial commitment, after all participants have committed."""
    return _publish(root, "reveal", payload, auth=auth, rundir=rundir)


def append(root, payload, *, auth=None, rundir=None):
    """Append a new immutable submission only after all initial reveals.

    On a version 2 season ``auth`` is the participant's broker authentication for
    a ``board append`` call (``research_board.append_action``).
    """
    return _publish(root, "append", payload, auth=auth, rundir=rundir)


def snapshot(root, *, expected_charter_sha256=None, expected_head_sha256=None, rundir=None):
    """Return a canonical advisory view, invariant to valid publication order.

    Journal chronology remains in the retained events. It is deliberately absent
    from this view so publication order cannot become a hypothesis ranking.
    ``contradicts`` records author assertions; ``known_conflicts`` compares only
    different known categorical values on the same declared key. Null is not a
    contradiction, and this comparison supplies no scientific adjudication.
    """
    with _locked(root, rundir=rundir) as directory:
        charter, charter_digest, head, state = _read(directory, rundir=rundir)
    for expected, actual, label in ((expected_charter_sha256, charter_digest, "charter"),
                                    (expected_head_sha256, head["sha256"], "head")):
        if expected is not None and _sha(expected, "expected digest") != actual:
            raise ValueError(f"board differs from the externally retained {label} digest")
    return _view(charter, charter_digest, head, state)


def _view(charter, charter_digest, head, state):
    submissions = sorted(state["submissions"], key=lambda row: (row["payload"]["actor_id"], row["submission_sha256"]))
    hypotheses, groups = [], {}
    for submission in submissions:
        payload = submission["payload"]
        for hypothesis in payload["hypotheses"]:
            signature = prediction_signature(hypothesis["predictions"])
            member = {"actor_id": payload["actor_id"], "session_id": payload["session_id"],
                      "hypothesis_id": hypothesis["id"], "hypothesis_sha256": _hypothesis_digest(hypothesis),
                      "submission_sha256": submission["submission_sha256"], "phase": submission["phase"]}
            hypotheses.append({**member, **hypothesis, "prediction_signature": signature})
            # Equality uses actual canonical content. The digest is only a report
            # identifier, so even a digest collision cannot merge unlike vectors.
            group = groups.setdefault(_bytes(hypothesis["predictions"]), {"prediction_signature": signature,
                "predictions": hypothesis["predictions"], "known_prediction_count": sum(
                    value is not None for value in hypothesis["predictions"].values()), "members": []})
            group["members"].append(member)
    hypotheses.sort(key=lambda row: (row["actor_id"], row["hypothesis_id"]))
    prediction_groups = [groups[key] for key in sorted(groups)]
    for group in prediction_groups:
        group["members"].sort(key=lambda row: (row["actor_id"], row["hypothesis_id"]))
    conflicts = []
    for left, right in itertools.combinations(prediction_groups, 2):
        keys = [key for key in charter["prediction_keys"]
                if left["predictions"][key] is not None and right["predictions"][key] is not None
                and left["predictions"][key] != right["predictions"][key]]
        if keys:
            conflicts.append({"left_signature": left["prediction_signature"],
                "right_signature": right["prediction_signature"], "differences": [
                    {"key": key, "left": left["predictions"][key], "right": right["predictions"][key]} for key in keys]})
    phase = ("followups_open" if state["reveals"] == state["actors"] else
             "initial_reveals_open" if set(state["commits"]) == state["actors"] else "sealed_commits")
    season = {}
    if charter["schema_version"] == 2:
        posts = [row for row in state["entries"] if row["event"] == "post"]
        season = {"season": charter["season"], "mode": charter["mode"], "head_sha256": head["sha256"],
                  "posts_by_kind": {kind: sum(row["payload"]["kind"] == kind for row in posts)
                                    for kind in sorted({row["payload"]["kind"] for row in posts})},
                  "open_requests": sorted(({"observable": row["payload"]["fields"]["observable"],
                                            "cost_class": row["payload"]["fields"]["cost_class"],
                                            "feasibility": row["payload"]["fields"]["feasibility"],
                                            "discriminates": row["payload"]["fields"]["discriminates"]}
                                           for row in posts if row["payload"]["kind"] == "evidence_request"),
                                          key=_bytes),
                  "register_states": {status: sum(value == status for value in state["status"].values())
                                      for status in sorted(set(state["status"].values()))}}
    return {**season, "schema_version": 1, "kind": "advisory_hypothesis_board", "authority": "ADVISORY",
            "board_id": charter["board_id"], "charter_sha256": charter_digest, "phase": phase,
            "participants": charter["participants"], "artifact_pins": charter["artifact_pins"],
            "commits": [{"actor_id": actor, "submission_sha256": state["commits"][actor]}
                        for actor in sorted(state["commits"])], "submissions": submissions,
            "hypotheses": hypotheses, "prediction_groups": prediction_groups, "known_conflicts": conflicts,
            "counts": {"committed": len(state["commits"]), "initial_revealed": len(state["reveals"]),
                       "submissions": len(submissions), "hypotheses": len(hypotheses),
                       "prediction_groups": len(prediction_groups),
                       "informative_prediction_groups": sum(group["known_prediction_count"] > 0 for group in prediction_groups),
                       "duplicate_predictions": len(hypotheses) - len(prediction_groups),
                       "known_conflicts": len(conflicts)}, "limitations": LIMITATION}


def _version(root):
    with _locked(root) as directory:
        registration = _read_json(directory, "charter.json", 262144)
    return registration.get("charter", {}).get("schema_version") if isinstance(registration, dict) else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="ADVISORY sealed hypothesis board; never execution approval")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "digest", "commit", "reveal", "append", "snapshot"):
        command = commands.add_parser(name)
        command.add_argument("--board", required=True)
        if name == "create":
            command.add_argument("--charter", required=True)
            command.add_argument("--artifacts", help="JSON map from frozen pin IDs to source paths")
        if name in {"digest", "reveal", "append"}:
            command.add_argument("--submission", required=True)
        if name == "commit":
            command.add_argument("--actor", required=True)
            command.add_argument("--digest", required=True)
        if name == "snapshot":
            command.add_argument("--expected-charter-sha256")
            command.add_argument("--expected-head-sha256")
    args = parser.parse_args(argv)
    def load(path):
        path = _absolute(path)
        directory = _directory(path.parent)
        try:
            return _read_json(directory, path.name, 1048576)
        finally:
            os.close(directory)
    try:
        if args.command == "create":
            result = create(args.board, load(args.charter), artifacts=load(args.artifacts) if args.artifacts else None)
        elif args.command in {"commit", "reveal", "append"} and _version(args.board) == 2:
            raise ValueError("version 2 seasons commit and reveal through the board.season graph "
                             "and append through the broker's board append action")
        elif args.command == "commit":
            result = commit(args.board, args.actor, args.digest)
        elif args.command == "snapshot":
            result = snapshot(args.board, expected_charter_sha256=args.expected_charter_sha256,
                              expected_head_sha256=args.expected_head_sha256)
        elif args.command == "digest":
            with _locked(args.board) as directory:
                charter, _, _, _ = _read(directory)
            result = {"submission_sha256": submission_digest(charter, load(args.submission))}
        else:
            result = (reveal if args.command == "reveal" else append)(args.board, load(args.submission))
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"hypothesis board: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
