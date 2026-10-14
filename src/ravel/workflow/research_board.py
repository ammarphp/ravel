"""Board season journal: typed posts, projections and replay.

``hypothesis_board`` keeps the hash-chained journal; this module supplies the closed
post kinds, the broker action that posts as the broker's authenticated actor, the
per-role read projections computed by code, the register replayed from the journal
and the check that a channel head is a verified ancestor of the journal head.

Posts are data. No function here reads prose for control, and the board never
dispatches or approves. Board content is ``generated`` and cannot ground a path.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import math
from pathlib import Path

from . import hypothesis_board as board

SCHEMAS = json.loads((Path(__file__).parents[1] / "data/research/board/posts.json").read_text())
KINDS = SCHEMAS["kinds"]
ABSENT_BY_DESIGN = frozenset(SCHEMAS["absent_by_design"])
CONTROL_FIELDS = frozenset(SCHEMAS["control_fields"])
EVALUATION_ONLY = frozenset(SCHEMAS["evaluation_only"])
RECEIPT_KINDS = frozenset(SCHEMAS["receipt_kinds"])
REGISTER_STATES = tuple(SCHEMAS["register_states"])
PROSE_MINIMUM = 16
MAX_OBJECT_BYTES = 4096


class BoardAccessRefused(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _controls(value, path="post"):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in CONTROL_FIELDS:
                raise ValueError(f"control field {key!r} is refused in a board post ({path})")
            _controls(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _controls(item, f"{path}[{index}]")


def _typed(value, kind, label, charter):
    if kind.endswith("[]"):
        board._list(value, label, 64)
        for item in value:
            _typed(item, kind[:-2], label + " item", charter)
        if kind == "sha256[]":
            board._distinct(value, label)
    elif kind.startswith("enum:"):
        if value not in kind[5:].split("|"):
            raise ValueError(f"{label} must be one of {kind[5:]}")
    elif kind == "id":
        board._id(value, label)
    elif kind == "text":
        board._text(value, label)
    elif kind == "sha256":
        board._sha(value, label)
    elif kind == "pin":
        board._object(value, {"path", "sha256"}, label)
        board._text(value["path"], label + " path", 512)
        board._sha(value["sha256"], label + " digest")
    elif kind == "bool":
        if type(value) is not bool:
            raise ValueError(f"{label} must be a boolean")
    elif kind == "probability":
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{label} must be a probability")
    elif kind == "predictions":
        board._object(value, charter["prediction_keys"], label)
        for item in value.values():
            if item is not None and (board._text(item, label, 128) != item.strip()):
                raise ValueError(f"{label} values cannot contain surrounding whitespace")
    elif kind == "object":
        if not isinstance(value, dict) or not value or len(board._bytes(value)) > MAX_OBJECT_BYTES:
            raise ValueError(f"{label} must be a nonempty bounded object")
    else:
        raise ValueError(f"undeclared field type {kind}")


def validate_post(charter, body):
    """Canonical post body, or ValueError: closed kinds, no control fields, typed fields."""
    if not isinstance(body, dict):
        raise ValueError("a board post must be an object")
    _controls(body)
    board._object(body, SCHEMAS["envelope"], "board post")
    kind = body["kind"]
    if kind in ABSENT_BY_DESIGN:
        raise ValueError(f"post kind {kind!r} is absent by design")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("undeclared board post kind")
    if kind in EVALUATION_ONLY and charter.get("mode") != "evaluation":
        raise ValueError(f"{kind} posts exist only in evaluation arms")
    if type(body["actor_sequence"]) is not int or not 1 <= body["actor_sequence"] <= charter["limits"]["max_records"]:
        raise ValueError("actor_sequence must be a bounded positive integer")
    _typed(body["parents"], "sha256[]", "parents", charter)
    declared = KINDS[kind]["fields"]
    required = {name for name in declared if not name.endswith("?")}
    optional = {name[:-1] for name in declared if name.endswith("?")}
    fields = body["fields"]
    if not isinstance(fields, dict) or not required <= set(fields) <= required | optional:
        raise ValueError(f"{kind} post needs fields {sorted(required)} (optional {sorted(optional)})")
    for name, value in fields.items():
        _typed(value, declared.get(name) or declared[name + "?"], f"{kind}.{name}", charter)
    if kind == "refutation":
        board._object(fields["target"], {"hypothesis", "key"}, "refutation target")
        board._sha(fields["target"]["hypothesis"], "refutation target hypothesis")
    result = json.loads(board._bytes(body))
    if len(board._bytes(result)) > charter["limits"]["max_payload_bytes"]:
        raise ValueError("post exceeds the frozen payload byte bound")
    return result


def create(root, charter):
    """Create a season journal; the charter must be version 2."""
    if not isinstance(charter, dict) or charter.get("schema_version") != 2:
        raise ValueError("a board season needs a version 2 charter")
    return board.create(root, charter)


def post_action(broker, root):
    """Trusted handler for the broker action ``board post``; the actor is the broker's.

    The broker appends its reservation before calling a handler, so the journal can
    verify that this exact request was made by the participant's bound broker.
    """
    from .broker import Refusal, digest, ledger

    def handler(args):
        if not isinstance(args, dict) or set(args) != {"post"}:
            raise Refusal("invalid_args", "board post requires post only")
        if not isinstance(broker.actor_id, str) or not broker.actor_id:
            raise Refusal("board_post_refused", "the broker has no authenticated actor")
        request = digest(args)
        rows = [row["record"] for row in ledger(broker.rundir, "broker-reservations")
                if row["record"]["node_id"] == broker.node_id and row["record"]["attempt"] == broker.attempt
                and row["record"]["action"] == board.POST_ACTION and row["record"]["args_sha256"] == request]
        if not rows:
            raise Refusal("board_post_refused", "no broker reservation for this post")
        auth = {"node_id": broker.node_id, "attempt": broker.attempt, "action": board.POST_ACTION,
                "args_sha256": request, "reservation": rows[-1]["receipt_id"]}
        try:
            entry = board.post(root, args["post"], actor_id=broker.actor_id, auth=auth, rundir=broker.rundir)
        except ValueError as exc:
            raise Refusal("board_post_refused", str(exc)) from None
        return {"stdout": json.dumps({"sequence": entry["sequence"], "sha256": entry["sha256"]}, sort_keys=True)}
    return handler


def append_action(broker, root):
    """Trusted handler for ``board append``: a follow-up submission whose actor is the broker's."""
    from .broker import Refusal, digest, ledger

    def handler(args):
        if not isinstance(args, dict) or set(args) != {"append"}:
            raise Refusal("invalid_args", "board append requires append only")
        if not isinstance(broker.actor_id, str) or not broker.actor_id:
            raise Refusal("board_append_refused", "the broker has no authenticated actor")
        if not isinstance(args["append"], dict) or args["append"].get("actor_id") != broker.actor_id:
            raise Refusal("board_append_refused", "a participant appends only as itself")
        request = digest(args)
        rows = [row["record"] for row in ledger(broker.rundir, "broker-reservations")
                if row["record"]["node_id"] == broker.node_id and row["record"]["attempt"] == broker.attempt
                and row["record"]["action"] == board.APPEND_ACTION and row["record"]["args_sha256"] == request]
        if not rows:
            raise Refusal("board_append_refused", "no broker reservation for this append")
        auth = {"node_id": broker.node_id, "attempt": broker.attempt, "action": board.APPEND_ACTION,
                "args_sha256": request, "reservation": rows[-1]["receipt_id"]}
        try:
            entry = board.append(root, args["append"], auth=auth, rundir=broker.rundir)
        except ValueError as exc:
            raise Refusal("board_append_refused", str(exc)) from None
        return {"stdout": json.dumps({"sequence": entry["sequence"], "sha256": entry["sha256"]}, sort_keys=True)}
    return handler


def code_auth(rundir, season_id):
    """The code reveal path's authentication: the digest of the season's frozen record."""
    record = season_record(rundir, season_id)
    if record is None:
        raise ValueError("the season's frozen record is missing; open the season first")
    return {"producer": board.SEASON_PRODUCER, "season_record_sha256": board._digest(record)}


def season(root, *, rundir):
    """The verified season view: entries, head and snapshot, re-verified against custody."""
    view = board.journal(root, rundir=rundir)
    if view["charter"]["schema_version"] != 2:
        raise ValueError("a board season needs a version 2 charter")
    return view


def record_transition(root, *, rundir, hypothesis, to, rule_id, receipt_pin):
    """Code-written register transition from a registered comparator or RDJ receipt."""
    if to not in REGISTER_STATES:
        raise ValueError("transition target is not a register state")
    return board.transition(root, hypothesis=hypothesis, to=to, rule_id=rule_id,
                            receipt_pin=receipt_pin, rundir=rundir)


def _hypotheses(view):
    """(ref, actor, origin, hypothesis) for sealed submissions and hypothesis posts, in journal order."""
    for entry in view["entries"]:
        if entry["event"] in {"reveal", "append"}:
            for row in entry["payload"]["hypotheses"]:
                yield (board.hypothesis_ref(entry["actor_id"], row), entry["actor_id"],
                       "initial" if entry["event"] == "reveal" else "followup", row)
        elif entry["event"] == "post" and entry["payload"]["kind"] == "hypothesis":
            fields = entry["payload"]["fields"]
            yield board.hypothesis_ref(entry["actor_id"], fields), entry["actor_id"], "post", fields


def register(view):
    """Hypothesis register: a pure function of the journal entries (and their verified receipts)."""
    rows = {}
    for ref, actor, origin, hypothesis in _hypotheses(view):
        rows[ref] = {"ref": ref, "actor_id": actor, "hypothesis_id": hypothesis["id"], "origin": origin,
                     "predictions": hypothesis["predictions"], "status": "proposed", "transitions": [],
                     "predictions_posted": [], "findings": [], "refutations": []}
    requests = []
    for entry in view["entries"]:
        payload = entry["payload"]
        if entry["event"] == "transition":
            row = rows[payload["hypothesis"]]
            row["status"] = payload["to"]
            row["transitions"].append({"entry_sha256": entry["sha256"], **payload})
        elif entry["event"] == "post":
            kind, fields = payload["kind"], payload["fields"]
            if kind == "prediction":
                rows[fields["hypothesis"]]["predictions_posted"].append(entry["sha256"])
            elif kind == "finding":
                for ref in fields["affects"]:
                    rows[ref]["findings"].append({"entry_sha256": entry["sha256"], "receipt_pin": fields["receipt_pin"]})
            elif kind == "refutation":
                rows[fields["target"]["hypothesis"]]["refutations"].append(
                    {"entry_sha256": entry["sha256"], "key": fields["target"]["key"], "receipt_pin": fields["receipt_pin"]})
            elif kind == "evidence_request":
                requests.append({"entry_sha256": entry["sha256"], "observable": fields["observable"],
                                 "discriminates": fields["discriminates"], "cost_class": fields["cost_class"],
                                 "feasibility": fields["feasibility"]})
    return {"schema_version": 1, "kind": "board-register", "season": view["charter"]["season"],
            "charter_sha256": view["charter_sha256"], "head_sha256": view["head"]["sha256"],
            "hypotheses": [rows[ref] for ref in sorted(rows)], "open_requests": requests,
            "authority": "computed; not a vote, approval or scientific validity"}


def register_bytes(view):
    return board._bytes(register(view))


# Board register state <-> research-cycle register state (section 18). The cycle
# replay recomputes its state from the same evidence; the two must agree.
CYCLE_STATES = {"proposed": "active", "active": "active", "reopened": "active", "survived_test": "survived_test",
                "prediction_mismatch": "weakened", "rejected_in_scope": "refuted", "parked": "untestable_within_budget",
                "inconclusive": None, "execution_failure": None, "superseded": None}


def cycle_events(view):
    """The register as research-cycle ``hypothesis``, ``test`` and ``transition`` events.

    Every hypothesis with a register declaration becomes a complete cycle hypothesis
    event (identifier: its board ref). Every comparator or budget transition becomes
    the cycle ``test`` the transition read, with its evidence snapshots, followed by
    the cycle ``transition`` the replay must recompute. Rules with no cycle test
    (RDJ admission or supersession, reopening) emit nothing; the cycle reopens with a
    fresh declared hypothesis. A transition on an undeclared hypothesis is refused.
    """
    from .research_cycle import replay_register
    declared, events = {}, []
    for ref, _, _, row in _hypotheses(view):
        if "register" in row:
            declared[ref] = row
            events.append({"kind": "hypothesis", "hypothesis": {"id": cycle_id(ref), "statement": row["statement"],
                                                                **deepcopy(row["register"])}})
    for entry in view["entries"]:
        if entry["event"] != "transition":
            continue
        payload = entry["payload"]
        rule = board.TRANSITION_RULES[payload["rule_id"]]
        if rule["evidence"] not in ("comparison", "budget"):
            continue
        if payload["hypothesis"] not in declared:
            raise ValueError("a tested hypothesis needs its register declaration")
        identity = cycle_id(payload["hypothesis"])
        before = replay_register(events)[identity]["status"]
        events.append({"kind": "test", "hypothesis_id": identity,
                       "observation": deepcopy(payload["observation"]),
                       "evidence_snapshots": deepcopy(payload["evidence_snapshots"])})
        after = replay_register(events)[identity]["status"]
        expected = CYCLE_STATES[payload["to"]]
        if expected is not None and after != expected:
            raise ValueError(f"board state {payload['to']} disagrees with the cycle register state {after}")
        events.append({"kind": "transition", "hypothesis_id": identity, "from": before, "to": after})
    return events


cycle_id = board.register_id


def _strip(kind, fields):
    hidden = set(KINDS[kind]["rationale"]) | {"id"}
    result = {key: value for key, value in fields.items() if key not in hidden}
    if "receipt_pin" in result:
        # A receipt path names the producing worker's workspace; the digest identifies the receipt.
        result["receipt_sha256"] = result.pop("receipt_pin")["sha256"]
    return result


def _ordered(rows):
    """Content-addressed rows with no chronology: sorted by their own digest."""
    return sorted(({"ref": board._digest(row), **row} for row in rows), key=lambda row: row["ref"])


def _profile(card):
    sees = card.get("sees") if isinstance(card, dict) else None
    if not isinstance(sees, dict) or not isinstance(sees.get("profile"), str):
        raise BoardAccessRefused("board_profile_undeclared", "card declares no sees.profile")
    forbidden = sees.get("forbidden_inputs", [])
    if not isinstance(forbidden, list):
        raise BoardAccessRefused("board_profile_undeclared", "card forbidden_inputs must be a list")
    return sees["profile"], forbidden


def forbidden_inputs(card):
    """A blind card's forbidden inputs always include ``board_prose``."""
    profile, forbidden = _profile(card)
    return sorted(set(forbidden) | ({"board_prose"} if profile == "blind" else set()))


def project(card, season):
    """The board as one role may read it, computed by code from the verified season view."""
    profile, forbidden = _profile(card)
    charter, snapshot = season["charter"], season["snapshot"]
    if profile == "blind":
        raise BoardAccessRefused("board_prose_forbidden", "blind roles read nothing from the board")
    if profile == "full":  # coordinator and decide: the computed snapshot only, without identities
        keep = ("phase", "counts", "prediction_groups", "known_conflicts", "open_requests",
                "register_states", "head_sha256")
        view = {key: deepcopy(snapshot[key]) for key in keep if key in snapshot}
        for group in view.get("prediction_groups", []):
            group["members"] = sorted(({"hypothesis_sha256": m["hypothesis_sha256"], "phase": m["phase"]}
                                       for m in group["members"]), key=lambda m: (m["hypothesis_sha256"], m["phase"]))
        return {"profile": profile, "season": charter["season"], "snapshot": view}
    if "board_prose" in forbidden and profile != "spec-denied":
        raise BoardAccessRefused("board_prose_forbidden", "this card reads no board prose")
    if profile == "workspace":
        opened = snapshot["phase"] == "followups_open"
        return {"profile": profile, "season": charter["season"], "phase": snapshot["phase"],
                "entries": deepcopy(season["entries"]) if opened else []}
    if profile != "spec-denied":
        raise BoardAccessRefused("board_profile_undeclared", f"no board projection for profile {profile!r}")
    # The critic reference is keyed by the journal head, so a critic cannot recompute
    # it from a guessed (actor, hypothesis) pair; lineage keeps digests, not paths.
    key = season["head"]["sha256"]
    def critic_ref(ref):
        return board._digest({"head": key, "ref": ref})
    hypotheses = []
    for ref, _, _, row in _hypotheses(season):
        value = {k: v for k, v in row.items() if k not in {"id", *KINDS["hypothesis"]["rationale"]}}
        if "source_lineage" in value:
            value["source_lineage"] = [pin["sha256"] for pin in value["source_lineage"]]
        hypotheses.append({"ref": critic_ref(ref), **value})
    posts = [entry["payload"] for entry in season["entries"] if entry["event"] == "post"]
    predictions = _ordered(_strip("prediction", row["fields"]) for row in posts if row["kind"] == "prediction")
    receipts = _ordered({"kind": row["kind"], **_strip(row["kind"], row["fields"])}
                        for row in posts if row["kind"] in RECEIPT_KINDS)
    requests = _ordered(_strip("evidence_request", row["fields"]) for row in posts if row["kind"] == "evidence_request")
    result = {"profile": profile, "season": charter["season"], "prediction_keys": charter["prediction_keys"],
              "hypotheses": sorted(hypotheses, key=lambda row: row["ref"]), "predictions": predictions,
              "receipts": receipts, "open_requests": requests}
    if "board_prose" in forbidden:
        # A spec-denied card that forbids board prose keeps the structural critic
        # projection: every free-text value is removed, digests and categories stay.
        result = _without_prose(result)
    return result


def _without_prose(value):
    if isinstance(value, dict):
        return {k: _without_prose(v) for k, v in value.items() if not _is_prose(v)}
    if isinstance(value, list):
        return [_without_prose(v) for v in value if not _is_prose(v)]
    return value


def _is_prose(value):
    return isinstance(value, str) and (" " in value.strip() or len(value) > 128)


def _normal(text):
    """Compare text after Unicode compatibility folding, case folding, JSON unescaping
    and whitespace collapse, with every dash and space variant treated alike."""
    import re, unicodedata
    try:
        decoded = json.loads(f'"{text}"') if "\\" in text else text
    except ValueError:
        decoded = text
    folded = unicodedata.normalize("NFKC", decoded).casefold()
    folded = re.sub(r"[\u2010-\u2015\u2212\u00ad-]", "-", folded)
    return " ".join(re.sub(r"[\s\u00a0\u2000-\u200b\u202f\u205f\u3000]+", " ", folded).split())


SHINGLE_WORDS = 3


def _shingles(text):
    # JSON structure is not prose: quotes, braces, colons and commas separate words.
    words = re.sub(r'[{}\[\]",:]', " ", _normal(text)).split()
    if len(words) < SHINGLE_WORDS:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def _prose(season):
    """Every retained free-text value of the season (all hypothesis and post fields), plus entry digests."""
    found = set()
    def walk(value):
        if isinstance(value, str) and value.strip():
            found.add(value.strip())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for entry in season["entries"]:
        found.add(entry["sha256"])
        if entry["event"] in {"reveal", "append"}:
            for row in entry["payload"]["hypotheses"]:
                walk({key: value for key, value in row.items() if key not in {"artifact_refs", "contradicts"}})
        elif entry["event"] == "post":
            walk({key: value for key, value in entry["payload"]["fields"].items()
                  if key not in {"receipt_pin", "source_lineage", "visible_agreement_pins", "held_fixed_inputs"}})
    return found


def check_bundle(card, bundle, season):
    """Refuse a blind role's input bundle that carries board prose; return it unchanged otherwise.

    Matching is on normalized text: a statement or prediction survives case, JSON
    escaping, whitespace and dash variants. Values of three or more words match on
    any shared three-word shingle; shorter values (a categorical prediction) match when quoted
    or as the whole item; entry digests match anywhere.
    """
    import re
    profile, forbidden = _profile(card)
    if profile != "blind" and "board_prose" not in forbidden:
        return bundle
    prose = _prose(season)
    digests = {text for text in prose if board.SHA256.fullmatch(text)}
    prose = prose - digests
    long_shingles = set().union(*(_shingles(text) for text in prose if len(_normal(text).split()) >= SHINGLE_WORDS))
    short = {_normal(text) for text in prose if 0 < len(_normal(text).split()) < SHINGLE_WORDS}
    for item in bundle:
        path = str(item.get("path", ""))
        parts = Path(path).parts
        content = item.get("content", "")
        content = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        normal = _normal(content)
        if (item.get("origin") == "board" or "board" in parts[:2]
                or any(parts[index:index + 2] == ("research", "board") for index in range(len(parts)))
                or any(digest in content for digest in digests)
                or _shingles(content) & long_shingles
                # A short value (a categorical prediction) is board content as a quoted
                # value or as the whole item; ordinary prose words are not refused.
                or normal in short
                or any(re.search(r"[\"']" + re.escape(text) + r"[\"']", normal) for text in short)):
            raise BoardAccessRefused("board_prose_forbidden", f"blind bundle contains board prose: {path}")
    return bundle


def verify_extension(channel_head, journal, *, rundir=None):
    """Is ``channel_head`` a verified ancestor of the journal head?

    ``current``: equal heads. ``extension``: every later entry links, has an admitted
    kind and (with ``rundir``) its broker reservation and receipts; replay those entries.
    ``divergence``: the channel head is not an ancestor, or the chain or an admission
    check fails; the caller holds with ``board_divergence``.
    """
    base = {"channel_head": channel_head}
    try:
        board._sha(channel_head, "channel head")
        view = journal if isinstance(journal, dict) else board.journal(journal, rundir=rundir)
    except ValueError as exc:
        return {**base, "status": "divergence", "journal_head": None, "entries": [],
                "reason": f"journal chain or admission check failed: {exc}"}
    chain = [view["charter_sha256"], *(entry["sha256"] for entry in view["entries"])]
    result = {**base, "journal_head": view["head"]["sha256"]}
    if channel_head not in chain:
        return {**result, "status": "divergence", "entries": [],
                "reason": "channel head is not an ancestor of the journal head"}
    later = view["entries"][chain.index(channel_head):]
    return {**result, "status": "extension" if later else "current", "entries": later, "reason": None}


# ---- seasons on the substrate -------------------------------------------------------------
#
# A season is the ``board.season`` graph: code freezes the charter, each participant's
# ``board.producer`` subgraph runs as a ``Send`` branch on its own projected packet, the
# sealed commits land in write-once channels at the superstep boundary, and the reveal
# effect writes commits and reveals to the journal in order. The journal charter is
# written at the reveal boundary with the committed population, so a ``no_commit``
# participant is excluded rather than blocking the journal's reveal barrier; the frozen
# season record keeps the declared population.

SEASON_GRAPH = "board.season"
PRODUCER_GRAPH = "board.producer"
STORE = "framework/store.sqlite"          # graph_substrate.STORE: runner-private, advisory
SEASON_KEYS = {"board_id", "season", "mode", "participants", "prediction_keys", "limits",
               "artifact_pins", "max_wall_seconds", "opened_utc"}
MAX_WALL_SECONDS = 86400
FIND_LIMIT = 50
PROFILE_CARDS = {profile: {"sees": {"profile": profile, "forbidden_inputs": []}}
                 for profile in ("workspace", "spec-denied", "full")}
# Trusted Python registrations only: name -> function(packet) -> {"submission", "receipt"}.
# The research loop registers the agent-backed producer; tests register stubs.
PRODUCERS = {}


class NoCommit(Exception):
    """A producer's worker supervisor reported no commit within ``max_wall_seconds``."""


class RevealRefused(ValueError):
    """The reveal barrier: every participant committed, or its timeout passed."""


def register_producer(name, function, *, replace=False):
    if not callable(function) or not isinstance(name, str) or not board.ID.fullmatch(name):
        raise ValueError("a producer is a named trusted callable")
    if name in PRODUCERS and not replace:
        raise ValueError(f"producer {name!r} is already registered")
    PRODUCERS[name] = function


def _utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds(text):
    from datetime import datetime, timezone
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def journal_root(rundir, season_id):
    return Path(rundir) / "research/board" / board._id(season_id, "season")


def _record_path(rundir, season_id):
    return Path(rundir) / "research/board" / (board._id(season_id, "season") + ".season.json")


def _sealed_path(rundir, season_id, actor):
    return Path(rundir) / "framework/board" / board._id(season_id, "season") / "sealed" / (actor + ".json")


def journal_charter(charter, actors=None):
    """The version 2 journal charter for the committed population (default: every participant)."""
    keep = set(actors) if actors is not None else {p["actor_id"] for p in charter["participants"]}
    return board.canonical_charter({
        "schema_version": 2, "board_id": charter["board_id"], "season": charter["season"], "mode": charter["mode"],
        "participants": [p for p in charter["participants"] if p["actor_id"] in keep],
        "prediction_keys": charter["prediction_keys"], "limits": charter["limits"],
        "artifact_pins": charter["artifact_pins"]})


def freeze_charter(request):
    """First phase: the frozen season charter, computed by code from the request."""
    board._object(request, SEASON_KEYS, "season charter request")
    if type(request["max_wall_seconds"]) is not int or not 1 <= request["max_wall_seconds"] <= MAX_WALL_SECONDS:
        raise ValueError(f"max_wall_seconds must be an integer from 1 to {MAX_WALL_SECONDS}")
    if request["opened_utc"] is not None:
        raise ValueError("opened_utc is stamped by code when the season opens; a supplied time is refused")
    opened = _utc()
    if any(p.get("actor_id") == "season" for p in request["participants"] if isinstance(p, dict)):
        raise ValueError("the actor id 'season' is reserved for the season result")
    canonical = journal_charter({**request, "participants": request["participants"]})
    charter = {"schema_version": 1, "kind": "board-season-charter",
               **{key: canonical[key] for key in ("board_id", "season", "mode", "participants",
                                                  "prediction_keys", "limits", "artifact_pins")},
               "max_wall_seconds": request["max_wall_seconds"], "opened_utc": opened,
               "visibility": "sealed_commit_then_simultaneous_reveal"}
    return {**charter, "charter_sha256": board._digest(charter)}


def _write_once(path, record):
    """An equal rewrite is a replay; a different one is refused."""
    from .state_io import atomic_json, read_json
    if path.exists():
        if read_json(path) != record:
            raise ValueError(f"a different {record['kind']} already exists for this season")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, record)
    return {"path": str(path), "sha256": board._digest(record)}


def open_season(rundir, charter):
    """Write the frozen season record (the declared population) once."""
    return _write_once(_record_path(rundir, charter["season"]),
                       {"schema_version": 1, "kind": "board-season-record", "charter": charter})


def season_record(rundir, season_id, kind="season"):
    """The frozen ``season`` record or the write-once ``reveal`` record, or None."""
    from .state_io import read_json
    path = _record_path(rundir, season_id).with_name(f"{season_id}.{kind}.json")
    return read_json(path) if path.exists() else None


def check_reveal(charter, commits, *, no_commit, now):
    """Refuse a reveal before every participant commits or its ``max_wall_seconds`` passes.

    Returns the excluded ``no_commit`` actors. A participant that neither committed nor
    reported ``no_commit`` (a failed or held producer) always refuses the reveal.
    """
    actors = {p["actor_id"] for p in charter["participants"]}
    excluded = set(no_commit)
    if not set(commits) <= actors or not excluded <= actors or excluded & set(commits):
        raise RevealRefused("commits and no_commit must partition charter participants")
    missing = actors - set(commits)
    if missing - excluded:
        raise RevealRefused("reveal requires every participant to commit or record no_commit after its timeout")
    if missing and _seconds(now) - _seconds(charter["opened_utc"]) < charter["max_wall_seconds"]:
        raise RevealRefused(f"no_commit recorded before the {charter['max_wall_seconds']} s timeout")
    if isinstance(no_commit, dict):
        # Each exclusion is the participant's own observation, made after its timeout.
        for actor, row in no_commit.items():
            observed = row.get("observed_utc") if isinstance(row, dict) else None
            if (not isinstance(observed, str)
                    or _seconds(observed) - _seconds(charter["opened_utc"]) < charter["max_wall_seconds"]):
                raise RevealRefused(f"{actor} reported no_commit before its {charter['max_wall_seconds']} s timeout")
    if not commits:
        raise RevealRefused("no participant committed")
    return sorted(missing)


def sealing(rundir, participants, receipts):
    """``sealed`` only when every participant has a transport-attested, isolated, distinct session.

    A participant's evidence is its worker receipt in the broker ``worker-receipts`` ledger
    (the rule of ``broker.Broker.sealing_status``). Otherwise the season is ``unsealed``
    and carries no independence label.
    """
    from . import broker
    from .state_io import read_json
    known = [row["record"] for row in broker.ledger(rundir, "worker-receipts")]
    rows, sessions = [], []
    for participant in participants:
        pin, reason = receipts.get(participant["actor_id"]), None
        try:
            if pin is None:
                raise ValueError("no worker receipt")
            ledger_rows = [row for row in known if row["pin"] == pin]
            if not ledger_rows:
                raise ValueError("receipt is not in the worker-receipts ledger")
            # The receipt must be this participant's: its broker node and attempt
            # and its session are the ones the charter binds.
            if not any({"node_id": row.get("node_id"), "attempt": row.get("attempt")} == participant["broker"]
                       for row in ledger_rows):
                raise ValueError("receipt belongs to another worker than the participant's broker")
            path = broker.locate(rundir, pin["path"])
            if broker.sha(path) != pin["sha256"]:
                raise ValueError("receipt changed after registration")
            receipt = read_json(path)
            isolation = receipt["isolation"]
            if receipt["attestation"] != "transport_attested" or not receipt["session_id"]:
                raise ValueError("session is not transport attested")
            if receipt["session_id"] != participant["session_id"]:
                raise ValueError("receipt session differs from the participant's charter session")
            if (isolation["user_configuration_loaded"] is not False
                    or isolation.get("evidence", {}).get("confirmed") is not True):
                raise ValueError("read denial of the run tree and peers is not probe-confirmed")
            sessions.append(receipt["session_id"])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            reason = str(exc)[:200]
        rows.append({"actor_id": participant["actor_id"], "attested": reason is None, "reason": reason})
    sealed = len(rows) >= 2 and all(row["attested"] for row in rows)
    result = {"status": "sealed", "participants": rows}
    if sealed and len(set(sessions)) != len(sessions):
        sealed, result["reason"] = False, "participant sessions are not distinct"
    if not sealed:
        result["status"] = "unsealed"
        result.setdefault("reason", "a participant lacks an attested isolated session")
    else:
        result["independence"] = "attested_distinct_sessions"
    return result


# ---- channels and reducers (section 3.2) ------------------------------------------------------

def charter_reducer(left, right):
    if left and right and left != right:
        raise ValueError("the season charter is written once")
    return deepcopy(right or left or {})


def commits_reducer(left, right):
    result = dict(left or {})
    for actor, value in (right or {}).items():
        board._sha(value, "sealed commit")
        if actor in result and result[actor] != value:
            raise ValueError("sealed submission changed after commit")
        result[actor] = value
    return result


def sealed_reducer(left, right):
    """Write-once pins of sealed payloads; the reveal clears it with an overwrite."""
    result = dict(left or {})
    for actor, pin in (right or {}).items():
        if actor in result and result[actor] != pin:
            raise ValueError("a sealed payload pin cannot change")
        result[actor] = deepcopy(pin)
    return result


def views_reducer(left, right):
    return {**(left or {}), **deepcopy(right or {})}


def _envelope_digest(item):
    return board._digest({key: value for key, value in item.items() if key not in {"sha256", "duplicate_of"}})


def posts_reducer(left, right):
    """Append posts on their hash chain; refuse undeclared kinds; mark duplicate prediction vectors.

    The channel value is ``{charter_sha256, limits, entries}``: the chain starts at the
    journal charter digest and the charter's record and byte bounds cap the channel.
    """
    if not right:
        return deepcopy(left or {})
    board._object(right, {"charter_sha256", "limits", "entries"}, "posts channel write")
    if left and (left["charter_sha256"], left["limits"]) != (right["charter_sha256"], right["limits"]):
        raise ValueError("posts channel write belongs to another charter")
    limits = right["limits"]
    entries = deepcopy((left or {}).get("entries") or [])
    known = {entry["sha256"]: entry for entry in entries}
    previous = entries[-1]["sha256"] if entries else right["charter_sha256"]
    signatures = {}
    for entry in entries:
        if entry["kind"] == "hypothesis" and "duplicate_of" not in entry:
            signatures[board._digest(entry["fields"]["predictions"])] = entry["sha256"]
    for item in right["entries"]:
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind in ABSENT_BY_DESIGN:
            raise ValueError(f"post kind {kind!r} is absent by design")
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("undeclared board post kind")
        if item.get("sha256") in known:
            if _envelope_digest(known[item["sha256"]]) != _envelope_digest(item):
                raise ValueError("a retained post cannot change")
            continue  # an equal re-merge after a resume
        if _envelope_digest(item) != item.get("sha256"):
            raise ValueError("post envelope digest does not match its content")
        if item.get("previous_sha256") != previous:
            raise ValueError("post hash chain broken")
        if len(entries) >= limits["max_records"]:
            raise ValueError("posts exceed the charter record bound")
        body = {key: value for key, value in item.items() if key not in {"sha256", "duplicate_of"}}
        if len(board._bytes(body)) > limits["max_payload_bytes"]:
            raise ValueError("post exceeds the charter byte bound")
        entry = deepcopy(body) | {"sha256": item["sha256"]}
        if kind == "hypothesis":
            signature = board._digest(entry["fields"]["predictions"])
            if signature in signatures:
                entry["duplicate_of"] = signatures[signature]  # no diversity credit
            else:
                signatures[signature] = entry["sha256"]
        entries.append(entry)
        known[entry["sha256"]] = entry
        previous = entry["sha256"]
    return {"charter_sha256": right["charter_sha256"], "limits": deepcopy(limits), "entries": entries}


def posts_from(view, after=None):
    """Channel envelopes for the journal's revealed submissions and posts, chained from ``after``."""
    previous = after or view["charter_sha256"]
    envelopes = []

    def add(kind, actor, entry, identifier, fields, body):
        nonlocal previous
        item = {"id": identifier, "kind": kind, "actor": actor, "season": view["charter"]["season"],
                "sequence": entry["sequence"], "previous_sha256": previous, "entry_sha256": entry["sha256"],
                "body_pin": board._digest(body), "fields": fields}
        item["sha256"] = _envelope_digest(item)
        envelopes.append(item)
        previous = item["sha256"]
    for entry in view["entries"]:
        if entry["event"] in {"reveal", "append"}:
            for row in entry["payload"]["hypotheses"]:
                add("hypothesis", entry["actor_id"], entry, board.hypothesis_ref(entry["actor_id"], row),
                    {"predictions": row["predictions"]}, row)
        elif entry["event"] == "post":
            add(entry["payload"]["kind"], entry["actor_id"], entry, entry["sha256"],
                entry["payload"]["fields"], entry["payload"])
    return {"charter_sha256": view["charter_sha256"], "limits": view["charter"]["limits"], "entries": envelopes}


def season_snapshot(view, charter, seal, no_commit):
    """Code-written snapshot for the coordinator: no prose, no ranking, no vote."""
    snapshot = view["snapshot"]
    keep = ("phase", "prediction_groups", "known_conflicts", "counts", "open_requests", "register_states")
    result = {"season": charter["season"], "head_sha256": view["head"]["sha256"],
              **{key: deepcopy(snapshot.get(key)) for key in keep},
              "coverage": {"participants": len(charter["participants"]),
                           "committed": len(view["charter"]["participants"])},
              "no_commit": sorted(no_commit), "unsealed": seal["status"] != "sealed", "sealing": seal,
              "authority": "computed; not a vote, approval or scientific validity"}
    return result


# ---- reveal, sync and the Store index (sections 3.3, 3.5, 3.6) --------------------------------

def reveal_season(rundir, charter, commits, sealed, receipts, no_commit):
    """Third phase: create the journal for the committed population, then commit and reveal in order.

    Idempotent: journal entries are keyed ``(season, actor, kind)``, so a resumed reveal
    appends only the missing entries.
    """
    # The barrier is checked here too: no caller reveals before every participant
    # commits or reports no_commit after its timeout.
    check_reveal(charter, commits, no_commit=no_commit, now=_utc())
    if season_record(rundir, charter["season"]) != {"schema_version": 1, "kind": "board-season-record",
                                                     "charter": charter}:
        raise ValueError("reveal needs the season's frozen record for this charter")
    auth = code_auth(rundir, charter["season"])
    actors = sorted(commits)
    jcharter = journal_charter(charter, actors)
    root = journal_root(rundir, charter["season"])
    if root.exists():
        if board.snapshot(root)["charter_sha256"] != board._digest(jcharter):
            raise ValueError("the season journal belongs to another charter")
    else:
        root.parent.mkdir(parents=True, exist_ok=True)
        board.create(root, jcharter)
    payloads = {}
    for actor in actors:
        raw = (Path(rundir) / sealed[actor]["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sealed[actor]["sha256"]:
            raise ValueError("a sealed payload changed after its commit")
        payload = json.loads(raw)
        if board._digest(payload) != commits[actor]:
            raise ValueError("a sealed payload does not match its commit")
        payloads[actor] = payload
    for actor in actors:
        board.commit(root, actor, board.submission_digest(jcharter, payloads[actor]), auth=auth, rundir=rundir)
    for actor in actors:
        board.reveal(root, payloads[actor], auth=auth, rundir=rundir)
    view = season(root, rundir=rundir)
    seal = sealing(rundir, [p for p in charter["participants"] if p["actor_id"] in commits], receipts)
    snapshot = season_snapshot(view, charter, seal, no_commit)
    reveals = [entry["sha256"] for entry in view["entries"] if entry["event"] == "reveal"]
    _write_once(_record_path(rundir, charter["season"]).with_name(charter["season"] + ".reveal.json"), {
        "schema_version": 1, "kind": "board-season-reveal", "season": charter["season"],
        "charter_sha256": charter["charter_sha256"], "journal_charter_sha256": view["charter_sha256"],
        "reveal_head_sha256": reveals[-1], "no_commit": sorted(no_commit), "sealing": seal,
        "receipts": {actor: deepcopy(receipts.get(actor)) for actor in actors}})
    index_season(rundir, root)
    return {"head": view["head"]["sha256"], "posts": posts_from(view), "snapshot": snapshot,
            "views": {profile: project(card, view) for profile, card in PROFILE_CARDS.items()}}


def sync_update(rundir, season_id, channel_head):
    """``board_sync``: replay a verified journal extension into the channels, or hold on divergence."""
    from .graph_nodes import RecoveryHold
    result = verify_extension(channel_head, journal_root(rundir, season_id), rundir=rundir)
    if result["status"] == "divergence":
        raise RecoveryHold("board_divergence", result["reason"])
    if result["status"] == "current":
        return {}
    # The posts reducer skips retained envelopes and appends the extension on its chain.
    view = season(journal_root(rundir, season_id), rundir=rundir)
    return {"board_posts": posts_from(view), "board_head": result["journal_head"]}


def _run_id(rundir):
    return board._digest(str(Path(rundir).absolute()))[:16]


def _store(rundir):
    import sqlite3
    from langgraph.store.sqlite import SqliteStore
    path = Path(rundir) / STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    store = SqliteStore(connection)
    store.setup()
    return store, connection


def _text_of(value):
    found = []
    def walk(item):
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            for key in sorted(item):
                walk(item[key])
        elif isinstance(item, list):
            for element in item:
                walk(element)
    walk(value)
    return " ".join(found)


def _index_rows(view):
    """Searchable rows per profile, each already inside that profile's projection."""
    season_id = view["charter"]["season"]
    rows = []
    for entry in project(PROFILE_CARDS["workspace"], view)["entries"]:
        kind = entry["payload"]["kind"] if entry["event"] == "post" else entry["event"]
        rows.append({"profile": "workspace", "season": season_id, "kind": kind, "ref": entry["sha256"], "row": entry})
    critic = project(PROFILE_CARDS["spec-denied"], view)
    for group, kind in (("hypotheses", "hypothesis"), ("predictions", "prediction"),
                        ("receipts", None), ("open_requests", "evidence_request")):
        for row in critic[group]:
            rows.append({"profile": "spec-denied", "season": season_id, "kind": kind or row["kind"],
                         "ref": row["ref"], "row": row})
    return sorted(rows, key=lambda row: (row["profile"], row["ref"]))


def index_season(rundir, root):
    """Rebuild the advisory Store index of one revealed season from its journal (section 3.5)."""
    view = season(root, rundir=rundir)
    if view["snapshot"]["phase"] != "followups_open":
        return {"season": view["charter"]["season"], "rows": 0, "sha256": board._digest([])}
    rows = _index_rows(view)
    store, connection = _store(rundir)
    try:
        for profile in ("workspace", "spec-denied"):
            namespace = ("board", _run_id(rundir), view["charter"]["season"], profile)
            for item in store.search(namespace, limit=100000):
                store.delete(namespace, item.key)
        for row in rows:
            namespace = ("board", _run_id(rundir), row["season"], row["profile"])
            store.put(namespace, row["ref"], {**row, "text": _text_of(row["row"]).lower()}, index=False)
    finally:
        connection.close()
    return {"season": view["charter"]["season"], "rows": len(rows), "sha256": board._digest(rows)}


def find(rundir, root, card, query, kind=None):
    """``board.find``: the caller's own season in its projection, earlier seasons as the critic projection."""
    profile, _ = _profile(card)
    if profile not in {"workspace", "spec-denied"}:
        raise BoardAccessRefused("board_profile_refused", f"profile {profile!r} reads the snapshot only")
    own = Path(root).name
    index_season(rundir, root)
    terms = [term for term in str(query).lower().split() if term]
    store, connection = _store(rundir)
    try:
        items = store.search(("board", _run_id(rundir)), limit=100000)
    finally:
        connection.close()
    rows = []
    for item in items:
        value = item.value
        wanted = profile if value["season"] == own else "spec-denied"
        if value["profile"] != wanted or (kind is not None and value["kind"] != kind):
            continue
        if all(term in value["text"] for term in terms):
            rows.append({key: value[key] for key in ("profile", "season", "kind", "ref", "row")})
    rows.sort(key=lambda row: (row["season"], row["ref"]))
    return {"profile": profile, "query": str(query), "rows": rows[:FIND_LIMIT], "truncated": len(rows) > FIND_LIMIT,
            "authority": "advisory index rebuilt from the journal"}


# ---- broker action rows: board post | read | find (section 3.4) -------------------------------

def _phase(root):
    """``revealed`` once every initial submission is in the journal; ``sealed`` before."""
    try:
        return "revealed" if board.snapshot(root)["phase"] == "followups_open" else "sealed"
    except ValueError:
        return "sealed"  # the journal is written at the reveal boundary


def register_tools(broker, root, card):
    """Register the three board actions on a worker broker, each answering in the card's projection.

    Blind roles are refused all three (``board_prose_forbidden``); only ``workspace`` roles
    post (critics and verifiers never do); any read or find in the sealed phase is denied
    and logged in the ``peer-denials`` custody ledger. Refusals are receipted by the broker.
    """
    from .broker import Refusal, append_ledger, digest
    profile, forbidden = _profile(card)
    blind = profile == "blind" or "board_prose" in forbidden
    root = Path(root)

    def refuse(code, message):
        def handler(args):
            raise Refusal(code, message)
        return handler

    def sealed_denial(args):
        append_ledger(broker.rundir, "peer-denials", {
            "node_id": broker.node_id, "attempt": broker.attempt, "actor_id": broker.actor_id,
            "season": root.name, "args_sha256": digest(args), "utc": _utc(), "code": "peer_read_denied"})
        raise Refusal("peer_read_denied", "sealed phase denies all peer visibility")

    def read(args):
        if args not in ({}, {"actor_id": broker.actor_id}):
            raise Refusal("invalid_args", "board read takes no arguments or the caller's own actor_id")
        if _phase(root) == "sealed":
            sealed_denial(args)
        try:
            return {"stdout": json.dumps(project(card, season(root, rundir=broker.rundir)), sort_keys=True)}
        except BoardAccessRefused as exc:
            raise Refusal(exc.code, str(exc)) from None

    def search(args):
        if not isinstance(args, dict) or not {"query"} <= set(args) <= {"query", "kind"}:
            raise Refusal("invalid_args", "board find takes query and optional kind")
        if not isinstance(args["query"], str) or len(args["query"]) > 512:
            raise Refusal("invalid_args", "board find query must be bounded text")
        if _phase(root) == "sealed":
            sealed_denial(args)
        try:
            found = find(broker.rundir, root, card, args["query"], args.get("kind"))
        except BoardAccessRefused as exc:
            raise Refusal(exc.code, str(exc)) from None
        return {"stdout": json.dumps(found, sort_keys=True)}

    if blind:
        rows = {name: refuse("board_prose_forbidden", "blind roles read and post nothing on the board")
                for name in TOOL_ROWS}
    else:
        rows = {"board post": post_action(broker, root) if profile == "workspace" else
                refuse("board_post_refused", "only workspace roles post; critics and verifiers never post"),
                "board read": read, "board find": search}
    for name, row in TOOL_ROWS.items():
        broker.register(name, rows[name], read_only=row["read_only"])
    return sorted(rows)


TOOL_ROWS = {"board post": {"read_only": False, "phase": "revealed", "profiles": ["workspace"]},
             "board read": {"read_only": True, "phase": "revealed", "profiles": ["workspace", "spec-denied", "full"]},
             "board find": {"read_only": True, "phase": "revealed", "profiles": ["workspace", "spec-denied"]}}


# ---- graphs: board.producer and board.season --------------------------------------------------

def producer_packet(state, participant):
    """The producer's own projected packet: its participant row and the charter's public terms.

    No peer identity, commit, sealed pin or post crosses into a producer (section 3.3).
    """
    charter = state["board_charter"]
    producer = ((state.get("meta") or {}).get("instance") or {}).get("producer")
    return {"actor": deepcopy(participant),
            "packet": {"season": charter["season"], "mode": charter["mode"], "producer": producer,
                       "prediction_keys": list(charter["prediction_keys"]), "limits": dict(charter["limits"]),
                       "artifact_pins": deepcopy(charter["artifact_pins"]),
                       "max_wall_seconds": charter["max_wall_seconds"], "charter_sha256": charter["charter_sha256"]}}


def producer_identity(state):
    packet = state["packet"]
    return {"season": packet["season"], "actor": state["actor"]["actor_id"],
            "charter_sha256": packet["charter_sha256"]}


def _produce(state, identity):
    from .state_io import atomic_json
    actor, packet = state["actor"], state["packet"]
    function = PRODUCERS.get(packet["producer"])
    if function is None:
        raise ValueError(f"producer {packet['producer']!r} is not registered")
    try:
        out = function({"actor": deepcopy(actor), **deepcopy(packet)})
    except NoCommit as exc:
        return {"actor": actor["actor_id"], "no_commit": True, "reason": str(exc)[:200], "observed_utc": _utc()}
    if not isinstance(out, dict) or set(out) != {"submission", "receipt"}:
        raise ValueError("a producer returns its submission and its worker receipt pin (or null)")
    payload = json.loads(board._bytes(out["submission"]))
    if payload.get("actor_id") != actor["actor_id"] or payload.get("session_id") != actor["session_id"]:
        raise ValueError("a producer submits only as its own charter participant")
    path = _sealed_path(state["meta"]["scope_root"], packet["season"], actor["actor_id"])
    atomic_json(path, payload)
    raw = path.read_bytes()
    pin = {"path": path.relative_to(Path(state["meta"]["scope_root"])).as_posix(),
           "sha256": hashlib.sha256(raw).hexdigest()}
    return {"actor": actor["actor_id"], "no_commit": False, "commit_sha256": board._digest(payload),
            "pin": pin, "receipt": deepcopy(out["receipt"])}


def _standard(builder, add, subsystem):
    from . import graph_nodes
    add("decision_turn", graph_nodes.decision_turn(subsystem))
    add("reconcile", graph_nodes.reconcile_node())
    add("hold", graph_nodes.hold(subsystem.replace(".", "_") + "_hold"))


def producer_graph(ctx):
    """``board.producer``: one sealed producer. Its input view is its own packet only."""
    from typing import Annotated, TypedDict
    from langgraph.graph import END, START, StateGraph
    from . import graph_nodes

    class ProducerView(TypedDict, total=False):
        meta: dict
        actor: dict
        packet: dict

    state = TypedDict("ProducerState", {**graph_nodes.BaseState.__annotations__, "actor": dict, "packet": dict},
                      total=False)
    builder = StateGraph(state, input_schema=ProducerView)
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    add("seal", graph_nodes.effect(
        "board.produce", kind="model", run=_produce, segment=lambda s: {"seal": s["actor"]["actor_id"]},
        identity=lambda s: producer_identity(s), to_state=lambda s, r: {"results": {"seal": r}}))
    _standard(builder, add, "board.producer")
    builder.add_edge(START, "seal")
    builder.add_edge("seal", END)
    return builder


def _collect(state):
    commits, sealed, receipts, no_commit = {}, {}, {}, {}
    results = state.get("results") or {}
    for participant in state["board_charter"]["participants"]:
        actor = participant["actor_id"]
        item = results.get(actor) or {}
        seal = (item.get("results") or {}).get("seal") if item.get("outcome") == "ok" else None
        if seal is None:
            continue  # a failed or held producer neither commits nor times out: the reveal refuses
        if seal["no_commit"]:
            no_commit[actor] = {"reason": seal["reason"], "observed_utc": seal["observed_utc"]}
        else:
            commits[actor], sealed[actor], receipts[actor] = seal["commit_sha256"], seal["pin"], seal["receipt"]
    return {"board_commits": commits, "board_sealed": sealed, "board_receipts": receipts,
            "board_no_commit": no_commit}


def _ready(state):
    try:
        check_reveal(state["board_charter"], state.get("board_commits") or {},
                     no_commit=state.get("board_no_commit") or {}, now=_utc())
    except RevealRefused:
        return "escalate"
    return "go"


def _reveal(state, identity):
    charter = state["board_charter"]
    return reveal_season(state["meta"]["scope_root"], charter, state["board_commits"], state["board_sealed"],
                         state.get("board_receipts") or {}, state.get("board_no_commit") or {})


def _revealed(state, result):
    snapshot = result["snapshot"]
    return {"board_posts": result["posts"], "board_head": result["head"],
            "board_sealed": {"__overwrite__": {}},  # LangGraph's JSON-safe Overwrite form
            "board_snapshot": snapshot, "board_views": result["views"],
            "results": {"season": {"season": snapshot["season"], "board_head": result["head"],
                                   "snapshot_sha256": board._digest(snapshot), "unsealed": snapshot["unsealed"],
                                   "no_commit": snapshot["no_commit"]}}}


def _charter(state, identity):
    charter = freeze_charter(state["charter"])
    if charter["season"] != state["meta"]["instance"]["season"]:
        raise ValueError("the charter names another season than the graph instance")
    open_season(state["meta"]["scope_root"], charter)
    return charter


def season_graph(ctx):
    """``board.season``: charter -> sealed producers (Send) -> collect -> reveal barrier -> reveal."""
    from typing import Annotated, TypedDict
    from langgraph.graph import END, START, StateGraph
    from . import graph_nodes, graph_registry, graph_substrate

    state = TypedDict("SeasonState", {
        **graph_nodes.BaseState.__annotations__, "charter": dict,
        "board_charter": Annotated[dict, charter_reducer], "board_commits": Annotated[dict, commits_reducer],
        "board_sealed": Annotated[dict, sealed_reducer], "board_posts": Annotated[dict, posts_reducer],
        "board_head": Annotated[str, graph_nodes.last_value], "board_snapshot": Annotated[dict, graph_nodes.last_value],
        "board_views": Annotated[dict, views_reducer], "board_receipts": Annotated[dict, graph_nodes.write_once],
        "board_no_commit": Annotated[dict, graph_nodes.write_once]}, total=False)
    builder = StateGraph(state)
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    child = graph_substrate.BuildContext(scope_root=ctx.scope_root, graph_id=PRODUCER_GRAPH,
                                         version=graph_registry.get(PRODUCER_GRAPH)["version"],
                                         instance=deepcopy(ctx.instance))
    edge, producers = graph_nodes.map_node(
        lambda s: s["board_charter"]["participants"], lambda p: p["actor_id"],
        graph_substrate.build(PRODUCER_GRAPH, child), producer_packet, name="producers")
    add("charter", graph_nodes.effect(
        "board.charter", kind="journal", run=_charter, segment=lambda s: {"board": "charter"},
        identity=lambda s: {"season": ctx.instance["season"], "request_sha256": board._digest(s["charter"])},
        to_state=lambda s, r: {"board_charter": r}))
    add("producers", producers)
    add("collect", graph_nodes.Node("board", _collect))
    add("ready", graph_nodes.guard(_ready, routes={"go": "reveal", "escalate": "refused"}))
    add("reveal", graph_nodes.effect(
        "board.reveal", kind="journal", run=_reveal, segment=lambda s: {"board": "reveal"},
        identity=lambda s: {"season": ctx.instance["season"], "charter_sha256": s["board_charter"]["charter_sha256"],
                            "commits": s.get("board_commits") or {},
                            "no_commit": sorted(s.get("board_no_commit") or {})},
        to_state=_revealed))
    add("refused", graph_nodes.hold("reveal_before_commits",
                                    "every participant commits, or records no_commit after max_wall_seconds"))
    _standard(builder, add, "board.season")
    builder.add_edge(START, "charter")
    graph_nodes.connect(builder, "charter", edge)
    builder.add_edge("producers", "collect")
    builder.add_edge("collect", "ready")
    builder.add_edge("reveal", END)
    return builder
