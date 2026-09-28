"""Coordinator-owned operation broker for one evaluation assignment (slice design §6).

The subject reaches the RAVEL kernel only through this broker: an HTTP service on
127.0.0.1 guarded by a per-assignment token. Calls are serialized; every subject call
(authenticated or not) is one canonical line in the append-only ``custody.jsonl`` and
every artifact is an immutable ``artifacts/<handle>.json`` record. A request other than
POST /op is authenticated, recorded and answered ``not_found`` without counting as an
operation; malformed HTTP (``bad_request``) and a connection that makes no progress for
REQUEST_SECONDS on one read or write (``request_timeout``) are recorded with op null.
A handle is ``art-`` plus 12 hex of an HMAC (broker secret) over the artifact's kind,
origin, content and derived_from, so identical results of one origin share a handle.
Kernel work runs as RAVEL supervised stages (resume) with one fixed interpreter string and
one fixed environment (``stages``): the likelihood DAG fit -> convert -> report in one RAVEL
run directory per workspace digest (``ravel-runs/<first 16 hex of its sha256>/``), and the
standalone stages census, calc and the coordinator-only figure each in a run directory keyed
by the stage, its input digests and its parameters (``stages.run_key``). The stage environment
is an allowlist (STAGE_ENV_KEYS, never a copy of os.environ) and must pin the kernel
source with PYTHONPATH; the broker verifies once that the interpreter imports ``ravel``
from there. RAVEL's ``execution_state.json`` stays the stage authority; custody records
what the subject asked for and received.

Inputs are the task-bank registry's kinds (``registry.INPUT_KINDS``): JSON records, the title
text, and gzip event files, which the broker stores as bytes and never parses (their artifact
content is their size). The runner materializes a task's input names, subdirectories included
(``sample/``, ``archive/``), and hands the broker their bytes by kind.

Coordinator-owned layout under ``root``: custody.jsonl, artifacts/, blobs/<sha256>
(exact input bytes for re-establishing stages), ravel-runs/, stage-home/, stage-tmp/, and
client_env.jsonl once a call carries the client's environment-name report (the
X-Ravel-Client-Env header, names only: one {seq, names, marker} line per such call, seq
naming the call's custody line; custody itself is unchanged). The report comes from a process
the subject controls, so it is evidence of what reached the subject's shell, never proof.
Coordinator calls are recorded with the ops ``register_inputs`` (one line) and
``create_prior`` (one line per step: inputs, then each step of the task's prior recipe, by
default fit, convert, report); every other op is a subject call, and no subject op runs a
coordinator-only step (``figure``). Standard library only.
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import importlib
import importlib.util
import os
import re
import secrets
import socket
import socketserver
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import guard, stages
from .allowlist_proxy import TWIN_ATTEMPTS, PortTaken, reserve_ipv6_twin
from .canonical import (ContractError, append_jsonl, atomic_write_bytes, canonical_bytes, digest, finite_number,
                        require, sha256_bytes, sha256_file, strict_load, strict_loads, write_once)
from .stages import calc as calc_stage
from .tasks import registry

INPUT_KINDS = tuple(registry.INPUT_KINDS)      # workspace, luminosity, title first: the v1 listing order
MODES = {("audit", "silent"), ("audit", "diagnostic"), ("block", "diagnostic")}
BUDGET_KEYS = {"max_broker_ops", "max_fits", "max_stage_executions"}
TREATMENT_WORDS = frozenset({"mode", "arm", "guard", "enforcement", "feedback"})
# subject-defined objects: their keys are not scanned (a note's requested budget, a calc's binding names)
FREE_FORM = {"note": ("requested_budget",), "calc": ("bind",)}
# The prior recipe of a task that names none: the likelihood_freshness recipe (slice design §5).
DEFAULT_RECIPE = ({"op": "fit", "params": {}}, {"op": "convert", "params": {}}, {"op": "report", "params": {}})
# Each stage's operands: argument name -> the artifact kinds it accepts (inputs or computed artifacts).
OPERANDS = {"fit": {"workspace": ("workspace",)}, "convert": {"fit": ("fit",), "luminosity": ("luminosity",)},
            "report": {"conversion": ("conversion",), "title": ("title",)},
            "census": {"events": ("events", "archive_events"), "manifest": ("manifest",),
                       "selection": ("selection",)},
            "figure": {"fit": ("fit",)}}
LIMIT_STATUS = {"obs_limit_events": "observed", "sigma_vis_obs_fb": "observed",
                "exp_limits_events": "expected", "sigma_vis_exp_fb": "expected"}
CALC_ARGS = {"expr", "bind", "unit"}
CALC_OPTIONAL = {"label"}
CENSUS_SUMMARY = ("complete_events", "header_nevents", "gzip_complete", "document_complete", "sha256_matches_record",
                  "physics_status", "cross_section_pb", "selected_events")
STAGE_ENV_KEYS = frozenset({"PATH", "PYTHONPATH", "PYTHONHASHSEED", "PYTHONNOUSERSITE", "PYTHONUTF8", "LANG", "LC_ALL",
                            "LC_CTYPE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                            "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
                            "CONDA_PREFIX"})
KERNEL_PROBE = "import importlib.util as u; s = u.find_spec('ravel'); print(s.origin if s and s.origin else '')"
TOKEN_HEADER = "X-Ravel-Task-Token"
CLIENT_ENV_HEADER = "X-Ravel-Client-Env"   # the client's environment NAMES (smoke spec WI-5, LC-11)
CLIENT_ENV_LIMIT = 8192
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
OPERATIONS = {"inputs": (), "show": ("handle",), "fit": ("workspace",), "convert": ("fit", "luminosity"),
              "report": ("conversion", "title"), "census": ("events", "manifest", "selection"), "calc": None,
              "submit": None, "note": None, "status": ()}
HANDLE = re.compile(r"art-[0-9a-f]{12}")
ACCEPTED = "Submission accepted."
NOT_ACCEPTED = "Submission not accepted."
MAX_BODY = 1 << 20
STAGE_KILL_SECONDS = 900.0
STAGE_POLL_SECONDS = 0.2
REQUEST_SECONDS = 30.0                               # socket timeout of one read or write on a connection
STOP_SECONDS = STAGE_KILL_SECONDS + 300.0            # longest legitimate call in progress at stop()
CLAIM_KEYS = {"schema_version", "claim_id", "status", "text", "quantity", "unit", "role",
              "expected_quantile", "artifact_field", "evidence_ids", "qualifiers"}
# Claim schema version 2 (WP12 design §1.5): the unit pb, a relation (eq, gt, ge, lt, le) and a categorical value on
# any registered artifact field. Accepted since the evaluator's task-bank profiles score it (plan step 8, E-131).
CLAIM_KEYS_V2 = CLAIM_KEYS | {"relation", "value"}
CLAIM_UNITS = {1: ("events", "fb", None), 2: ("events", "fb", "pb", None)}
DECISION_KEYS = {"schema_version", "run_id", "decision_id", "evidence_ids", "question", "action",
                 "brief_rationale", "falsification_test", "requested_budget", "timestamp_utc"}


class OpError(Exception):
    """An operation rejected with a subject-visible code and message."""

    def __init__(self, code, message, status=200):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class StageFailure(OpError):
    def __init__(self, message, detail):
        super().__init__("stage_failed", message)
        self.detail = detail


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _keys(value, expected, label):
    require(isinstance(value, dict), f"{label}: expected object")
    require(set(value) == set(expected), f"{label}: fields must be {sorted(expected)}")


def _strings(value, label):
    require(isinstance(value, list) and all(isinstance(v, str) for v in value), f"{label}: list of strings required")


def check_submission(submission):
    """Minimal structural check of a submission (§4.5-4.6); contracts.validate_submission may add more."""
    _keys(submission, {"claims", "report_text", "refusal", "final"}, "submission")
    require(isinstance(submission["claims"], list), "claims: list required")
    ids = set()
    for claim in submission["claims"]:
        version = claim.get("schema_version") if isinstance(claim, dict) else None
        require(type(version) is int and version in CLAIM_UNITS, "claim schema_version: expected 1 or 2")
        _keys(claim, CLAIM_KEYS if version == 1 else CLAIM_KEYS_V2, "claim")
        require(isinstance(claim["claim_id"], str) and claim["claim_id"].strip(), "claim_id: nonblank string required")
        require(claim["claim_id"] not in ids, f"duplicate claim_id: {claim['claim_id']}")
        ids.add(claim["claim_id"])
        require(claim["status"] in ("provisional", "retracted", "final"), "claim status: invalid")
        require(isinstance(claim["text"], str), "claim text: string required")
        quantity = claim["quantity"]
        require(quantity is None or guard.decimal_value(quantity) is not None,
                f"claim quantity: decimal string within 1e+-{guard.MAX_EXPONENT}, or null")
        require(claim["unit"] in CLAIM_UNITS[version],
                "claim unit: events, fb or null" + (" (version 2: or pb)" if version == 2 else ""))
        require(claim["role"] in ("observed", "expected", "diagnostic", "not_applicable"), "claim role: invalid")
        require(claim["expected_quantile"] in (*guard.QUANTILES, None), "claim expected_quantile: invalid")
        require((claim["role"] == "expected") == (claim["expected_quantile"] is not None),
                "claim expected_quantile: required exactly when role is expected")
        valued = quantity is not None or (version == 2 and claim["value"] is not None)
        require(valued == (claim["artifact_field"] is not None),
                "claim artifact_field: required exactly when quantity" + (" or value" if version == 2 else "")
                + " is present")
        if claim["artifact_field"] is not None:   # version 1: the v1 fields; version 2: every registry field
            fields = guard.V1_FIELDS if version == 1 else registry.ARTIFACT_FIELDS
            require(claim["artifact_field"] in fields, f"unknown artifact_field: {claim['artifact_field']!r}")
        _strings(claim["evidence_ids"], "claim evidence_ids")
        _strings(claim["qualifiers"], "claim qualifiers")
    require(isinstance(submission["report_text"], str), "report_text: string required")
    refusal = submission["refusal"]
    require(refusal is None or (isinstance(refusal, dict) and set(refusal) == {"text"}
                                and isinstance(refusal["text"], str)), "refusal: null or {text}")
    require(type(submission["final"]) is bool, "final: boolean required")


def check_decision_record(record):
    """Minimal structural check of a decision record (§4.7, packet schema)."""
    _keys(record, DECISION_KEYS, "decision record")
    require(type(record["schema_version"]) is int and record["schema_version"] == 1, "schema_version: expected 1")
    for name in ("run_id", "decision_id", "question", "action", "brief_rationale", "timestamp_utc"):
        require(isinstance(record[name], str), f"{name}: string required")
    require(record["decision_id"].strip(), "decision_id: nonblank string required")
    _strings(record["evidence_ids"], "evidence_ids")
    require(record["falsification_test"] is None or isinstance(record["falsification_test"], str),
            "falsification_test: string or null")
    require(isinstance(record["requested_budget"], dict), "requested_budget: object required")


def _contracts():
    """The shared contracts module when present (it is built separately), else None."""
    name = f"{__package__}.contracts" if __package__ else "contracts"
    try:
        found = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        found = None
    return importlib.import_module(name) if found else None


def _input_content(kind, data):
    """An input's artifact content by its registry format: the JSON object, the title text, or for gzip event
    files (never parsed here) their size."""
    require(kind in registry.INPUT_FORMATS, f"{kind}: not a registry input kind")
    require(isinstance(data, bytes), f"{kind}: input bytes required")
    if registry.INPUT_FORMATS[kind] == "gzip":
        require(data, f"{kind}: empty input")
        return {"file_bytes": len(data)}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{kind}: input is not UTF-8") from exc
    if registry.INPUT_FORMATS[kind] == "text":
        require(text.strip(), f"{kind}: blank input")
        return text
    content = strict_loads(text)
    require(isinstance(content, dict), f"{kind}: JSON object required")
    return content


def _recipe_needs(name, params):
    """The operand kinds one prior-recipe step needs (``Broker.create_prior``); ContractError for parameters its
    stage does not take."""
    if name in ("fit", "convert", "report"):
        require(params == {}, f"prior recipe {name}: takes no parameters")
        return {kinds[0] for kinds in OPERANDS[name].values()}
    if name == "census":
        events = params.get("events", "events")
        require(set(params) <= {"events"} and isinstance(events, str) and events in OPERANDS["census"]["events"],
                "prior recipe census: parameters {events?: events | archive_events}")
        return {events, "manifest", "selection"}
    if name == "figure":
        require(set(params) == {"legend"}, "prior recipe figure: parameters {legend}")
        return {"fit"}
    bindings = params.get("bindings")
    require(set(params) == {"expression", "bindings", "unit", "label"} and isinstance(bindings, list) and bindings
            and all(isinstance(b, dict) and set(b) == {"name", "source", "field"} and isinstance(b["source"], str)
                    and isinstance(b["name"], str) for b in bindings)
            and len({b["name"] for b in bindings}) == len(bindings),
            "prior recipe calc: parameters {expression, bindings: [{name, source, field}] with unique names, unit, "
            "label}")
    return {b["source"] for b in bindings}


def _check_recipe(recipe, available):
    """A prior recipe's steps are stages with the parameters they take, each operand is a prior input kind or an
    earlier step's artifact kind, and each artifact kind is made once; ContractError otherwise."""
    require(isinstance(recipe, list), "prior recipe: a list of steps required")
    available, made = set(available), set()
    for i, step in enumerate(recipe):
        require(isinstance(step, dict) and set(step) == {"op", "params"} and step["op"] in stages.WORKERS
                and isinstance(step["params"], dict), f"prior recipe[{i}]: {{op, params}} over the stages "
                                                      f"{list(stages.WORKERS)}")
        canonical_bytes(step["params"])            # strict JSON: the parameters go into custody
        missing = sorted(_recipe_needs(step["op"], step["params"]) - available)
        require(not missing, f"prior recipe[{i}] {step['op']}: needs {missing}, which neither a prior input nor an "
                             "earlier step provides")
        kind = stages.STAGES[step["op"]]["kind"]
        require(kind not in made, f"prior recipe[{i}]: a second {kind} artifact")
        made.add(kind)
        available.add(kind)


def _treatment_like(name):
    """True when an identifier has a treatment word among its snake, kebab or camelCase words."""
    if not isinstance(name, str):
        return False
    words = re.split(r"[^a-z]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower())
    return bool(set(words) & TREATMENT_WORDS)


def _switch_attempt(request):
    """Treatment-like names in one parsed request: the op, extra top-level keys, keys inside args.

    Keys inside the free-form objects of FREE_FORM (a note's requested_budget) are not scanned.
    """
    op, args = request.get("op"), request.get("args")
    found = {k for k in request if k not in ("op", "args") and _treatment_like(k)}
    if _treatment_like(op):
        found.add(op)
    stack = [(args, FREE_FORM.get(op, ()) if isinstance(op, str) else ())]
    while stack:                                     # iterative: no depth limit to hide behind
        value, skip = stack.pop()
        if isinstance(value, dict):
            found |= {k for k in value if _treatment_like(k)}
            stack += [(v, ()) for k, v in value.items() if k not in skip]
        elif isinstance(value, list):
            stack += [(v, ()) for v in value]
    return found


def _within(path, root):
    return path == root or root in path.parents


def parse_client_env(value) -> tuple:
    """(names, marker) of an X-Ravel-Client-Env header: the sorted unique variable names and marker None; the
    names and "invalid_names" when the client left out names that are not plain identifiers (its trailing
    "!invalid"); (None, "overflow") for the client's "!overflow"; (None, "malformed") for anything else (too long,
    unsorted, duplicated or not names). Never a value: the client sends names only."""
    if not isinstance(value, str) or len(value) > CLIENT_ENV_LIMIT:
        return None, "malformed"
    if value == "!overflow":
        return None, "overflow"
    parts = value.split(",") if value else []
    marker = None
    if parts and parts[-1] == "!invalid":
        parts, marker = parts[:-1], "invalid_names"
    if not all(ENV_NAME.fullmatch(p) for p in parts) or parts != sorted(set(parts)):
        return None, "malformed"
    return parts, marker


class _Server(http.server.HTTPServer):
    def server_bind(self):
        # Skip HTTPServer's reverse DNS lookup (getfqdn): loopback only, no name service.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ravel-task"
    sys_version = ""

    @property
    def timeout(self):
        """Socket timeout set at setup(): a stalled or half-open connection cannot hold the service."""
        return REQUEST_SECONDS

    def log_message(self, *args):
        pass

    def log_error(self, format, *args):
        # BaseHTTPRequestHandler reports a timed-out read or write here, then drops the connection.
        if any(isinstance(a, (TimeoutError, socket.timeout)) for a in args):
            self.server.broker._record("request_timeout", {"detail": f"no progress for {REQUEST_SECONDS:g} s"})

    def send_error(self, code, message=None, explain=None):
        """Malformed HTTP (request line, headers, sizes): recorded, answered with a JSON error, closed."""
        self.close_connection = True
        try:
            self.server.broker._record("bad_request", {"http_status": int(code), "detail": str(message or "")[:200]})
        finally:
            self._send(int(code), {"ok": False, "error": {"code": "bad_request", "message": "malformed HTTP request"}})

    def parse_request(self):
        if not super().parse_request():
            return False
        if self.command == "POST" and self.path == "/op":
            return True
        # Any other method or path: authenticated and recorded like a call, never counted, then closed.
        self.close_connection = True
        self._send(*self.server.broker._request(self.headers.get(TOKEN_HEADER), None, route=(self.command, self.path),
                                                client_env=self.headers.get(CLIENT_ENV_HEADER)))
        return False

    def _send(self, status, response):
        body = canonical_bytes(response) + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        body = None
        if 0 <= length <= MAX_BODY:
            body = self.rfile.read(length)        # a stalled body times out: recorded by log_error
            if len(body) != length:               # the client closed before sending the whole body
                body = None
        if body is None:
            self.close_connection = True
        try:
            status, response = self.server.broker._request(self.headers.get(TOKEN_HEADER), body,
                                                           client_env=self.headers.get(CLIENT_ENV_HEADER))
        except Exception:  # custody could not be written: fail closed, never hang the client
            status, response = 500, {"ok": False, "error": {"code": "internal_error", "message": "internal error"}}
        self._send(status, response)


class Broker:
    """One assignment's operation broker (§6, §13)."""

    def __init__(self, root, *, guard_mode, feedback, budgets: dict, python: str, env: dict, secret: bytes):
        require((guard_mode, feedback) in MODES, f"unsupported guard mode/feedback: {guard_mode}/{feedback}")
        require(isinstance(budgets, dict) and set(budgets) == BUDGET_KEYS
                and all(type(v) is int and v > 0 for v in budgets.values()),
                f"budgets must be positive integers {sorted(BUDGET_KEYS)}")
        require(isinstance(python, str) and os.path.isabs(python) and os.path.isfile(python)
                and os.access(python, os.X_OK), "python: absolute path to an executable interpreter required")
        require(isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()),
                "env: mapping of strings required")
        unexpected = sorted(set(env) - STAGE_ENV_KEYS)     # names only: a value may be a secret
        require(not unexpected, f"stage env: {unexpected} outside the fixed minimal environment "
                                f"{sorted(STAGE_ENV_KEYS)} (HOME, TMPDIR and PYTHONDONTWRITEBYTECODE are the broker's)")
        require(env.get("PYTHONPATH"), "stage env: PYTHONPATH must pin the RAVEL kernel source")
        require(isinstance(secret, bytes) and len(secret) >= 16, "secret: at least 16 bytes required")
        root = Path(root)
        require(not root.exists() or (root.is_dir() and not any(root.iterdir())), "broker root must be new or empty")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        for name in ("artifacts", "blobs", "ravel-runs", "stage-home", "stage-tmp"):
            (self.root / name).mkdir()
        self.guard_mode, self.feedback, self.budgets = guard_mode, feedback, dict(budgets)
        self._python, self._secret = python, secret
        # Containment variables live in the broker root; none of them is part of a RAVEL receipt.
        self._stage_env = {**env, "HOME": str(self.root / "stage-home"), "TMPDIR": str(self.root / "stage-tmp"),
                           "PYTHONDONTWRITEBYTECODE": "1"}
        self._kernel_package = self._probe_kernel(env["PYTHONPATH"])
        self._artifacts, self._current, self._prior, self._prior_attempted = {}, None, None, False
        self._seq = self._ops = self._fits = self._stage_runs = 0
        self._submissions = []
        self._lock = threading.Lock()
        self._server = self._thread = self._token = None
        self._started = False

    # -- coordinator interface -------------------------------------------------------------
    def custody_path(self) -> Path:
        return self.root / "custody.jsonl"

    def client_env_path(self) -> Path:
        return self.root / "client_env.jsonl"

    def register_inputs(self, current: dict) -> dict:
        """Register the subject's current inputs ({registry input kind: bytes}); returns kind -> handle."""
        with self._lock:
            require(self._current is None and not self._started, "current inputs are registered once, before start")
            require(isinstance(current, dict) and current and set(current) <= set(INPUT_KINDS),
                    f"current inputs: a nonempty mapping of registry input kinds {list(INPUT_KINDS)}")
            for kind, data in current.items():
                _input_content(kind, data)
            seq = self._reserve()
            entry = self._entry("register_inputs", {k: sha256_bytes(current[k]) for k in INPUT_KINDS if k in current})
            try:
                registered = {}
                for kind in INPUT_KINDS:
                    if kind in current:
                        handle, record = self._store_input(kind, current[kind], "current_input", seq)
                        registered[kind] = {"handle": handle, "sha256": record["content_sha256"],
                                            "content": record["content"]}
                self._current = registered
                handles = {kind: item["handle"] for kind, item in registered.items()}
                entry.update(ok=True, result=handles)
                return dict(handles)
            except Exception as exc:
                entry.update(error_code="internal_error", incident={"kind": "internal_error", "detail": repr(exc)})
                raise
            finally:
                self._write(seq, entry)

    def create_prior(self, prior: dict, recipe=None) -> dict:
        """Store the prior inputs ({registry input kind: bytes}) and run the task's prior recipe on them; return
        artifact kind -> handle of every step's artifact, in recipe order.

        ``recipe`` is the task definition's ``prior_recipe`` (default ``DEFAULT_RECIPE``: fit, convert,
        report): steps ``{op, params}`` over every stage, the coordinator-only ``figure`` included. A step's
        operands are resolved by kind (``OPERANDS``): a prior input, or the artifact an earlier step made
        (each artifact kind at most once). Parameters: none for fit, convert and report; census
        ``{events?: events | archive_events}``; figure ``{legend}`` (stages/figure.py); calc ``{expression,
        bindings: [{name, source, field}], unit, label}`` with each ``source`` a prior input kind or an earlier
        step's artifact kind. Custody gets one ``create_prior`` line for the inputs and one per step (its
        derived_from digests, and its parameters when it has any). An empty recipe with no prior inputs records
        the inputs line only. A failed step is terminal for this broker."""
        recipe = [dict(step) for step in DEFAULT_RECIPE] if recipe is None else recipe
        with self._lock:
            require(not self._prior_attempted and not self._started, "prior artifacts are created once, before start")
            require(isinstance(prior, dict) and set(prior) <= set(INPUT_KINDS),
                    f"prior inputs: a mapping of registry input kinds {list(INPUT_KINDS)}")
            for kind, data in prior.items():
                _input_content(kind, data)
            _check_recipe(recipe, set(prior))
            self._prior_attempted = True   # a failed prior is terminal for this broker, never retried
            seq = self._reserve()
            entry = self._entry("create_prior", {"step": "inputs",
                                                 **{k: sha256_bytes(prior[k]) for k in INPUT_KINDS if k in prior}})
            try:
                inputs = {kind: self._store_input(kind, prior[kind], "prior", seq)[0]
                          for kind in INPUT_KINDS if kind in prior}
                entry.update(ok=True, result=inputs)
            except Exception as exc:
                entry.update(error_code="internal_error", incident={"kind": "internal_error", "detail": repr(exc)})
                raise
            finally:
                self._write(seq, entry)
            made = {}
            for step in recipe:
                name, params = step["op"], step["params"]
                seq = self._reserve()
                entry = self._entry("create_prior", {"step": name})
                trace = {}
                try:
                    derived, run = self._prior_plan(name, params, {**inputs, **made})
                    entry["args"] = {"step": name, **derived, **({"params": params} if params else {})}
                    content = run(trace)
                    handle, _ = self._store(stages.STAGES[name]["kind"], "prior", content, digest(content), derived,
                                            seq)
                    made[stages.STAGES[name]["kind"]] = handle
                    entry.update(ok=True, result={"handle": handle, "upstream_stages": trace["upstream"]})
                except OpError as exc:
                    entry.update(error_code=exc.code, result={"detail": getattr(exc, "detail", exc.message)})
                    raise RuntimeError(f"prior {name} stage failed: {exc.message}") from exc
                except Exception as exc:
                    entry.update(error_code="internal_error", incident={"kind": "internal_error", "detail": repr(exc)})
                    raise
                finally:
                    entry["stage"] = trace.get("stage")
                    self._write(seq, entry)
            self._prior = made
            return dict(made)

    def start(self) -> tuple[str, str]:
        """Serve on an ephemeral 127.0.0.1 port; returns (endpoint URL, per-assignment token)."""
        with self._lock:
            require(self._current is not None, "register current inputs before start")
            require(not self._started, "a broker serves one assignment once")
            require(not self._prior_attempted or self._prior is not None, "prior artifact creation failed")
            self._started = True
            self._token = secrets.token_hex(32)
            for _ in range(TWIN_ATTEMPTS):   # the port's [::1] twin is held too (E-82): a subject's profile admits it
                server = _Server(("127.0.0.1", 0), _Handler)
                try:
                    server.twin = reserve_ipv6_twin(server.server_address[1])
                except PortTaken:
                    server.server_close()
                    continue
                except BaseException:
                    server.server_close()
                    raise
                break
            else:
                raise OSError(f"no 127.0.0.1 port whose [::1] twin is free after {TWIN_ATTEMPTS} tries")
            server.broker = self
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1},
                                            name="ravel-task-broker", daemon=True)
            self._thread.start()
            return f"http://127.0.0.1:{server.server_address[1]}/op", self._token

    def stop(self) -> None:
        """Stop serving once the call in progress, if any, is answered and recorded (bounded wait)."""
        server, thread = self._server, self._thread
        if server is None:
            return
        stopper = threading.Thread(target=server.shutdown, name="ravel-task-broker-stop", daemon=True)
        stopper.start()
        stopper.join(STOP_SECONDS)
        if stopper.is_alive():
            server.socket.close()                   # no new connections; the call in progress is still recorded
            raise RuntimeError(f"broker did not stop within {STOP_SECONDS:g} s: a call is still in progress")
        server.server_close()
        if getattr(server, "twin", None) is not None:
            server.twin.close()
        thread.join(timeout=30)
        self._server = self._thread = None

    def _probe_kernel(self, pythonpath):
        """The ravel package directory the stage interpreter imports; it must lie under the pinned PYTHONPATH."""
        done = subprocess.run([self._python, "-c", KERNEL_PROBE], cwd=self.root / "stage-home", env=self._stage_env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        origin = done.stdout.strip() if done.returncode == 0 else ""
        require(origin, f"stage interpreter cannot import ravel: {done.stderr.strip()[-300:]}")
        package = Path(origin).resolve().parent
        roots = [Path(entry).resolve() for entry in pythonpath.split(os.pathsep) if entry]
        require(any(_within(package, root) for root in roots),
                f"stages would import ravel from {package}, outside the pinned PYTHONPATH")
        return package

    # -- custody and artifacts ---------------------------------------------------------------
    def _reserve(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def _entry(op, args):
        return {"op": op, "args": args, "ok": False, "error_code": None, "result": None, "stage": None,
                "guard": None, "feedback_shown": "none", "incident": None}

    def _write(self, seq, entry):
        append_jsonl(self.custody_path(), {"seq": seq, "time_utc": utc_now(), **entry})

    def _record(self, error_code, result):
        """One custody line for a transport event that never reached an operation (op null, not counted)."""
        with self._lock:
            seq = self._reserve()
            entry = self._entry(None, None)
            entry.update(error_code=error_code, result=result)
            self._write(seq, entry)

    def _handle(self, kind, origin, content, derived_from):
        material = canonical_bytes({"kind": kind, "origin": origin, "content": content, "derived_from": derived_from})
        return "art-" + hmac.new(self._secret, material, hashlib.sha256).hexdigest()[:12]

    def _store(self, kind, origin, content, content_sha256, derived_from, seq):
        """Record an artifact immutably; an identical artifact keeps its first record and handle."""
        handle = self._handle(kind, origin, content, derived_from)
        existing = self._artifacts.get(handle)
        if existing is not None:
            require(existing["kind"] == kind and existing["content"] == content
                    and existing["derived_from"] == derived_from, f"artifact handle collision: {handle}")
            return handle, existing
        record = {"handle": handle, "kind": kind, "content": content, "content_sha256": content_sha256,
                  "derived_from": derived_from, "produced_by_seq": seq, "origin": origin}
        write_once(self.root / "artifacts" / f"{handle}.json", canonical_bytes(record) + b"\n")
        self._artifacts[handle] = record
        return handle, record

    def _store_input(self, kind, data, origin, seq):
        sha = sha256_bytes(data)
        blob = self.root / "blobs" / sha
        if not blob.exists():
            write_once(blob, data)
        return self._store(kind, origin, _input_content(kind, data), sha, {kind: sha}, seq)

    def _blob(self, sha):
        data = (self.root / "blobs" / sha).read_bytes()
        require(sha256_bytes(data) == sha, f"input blob {sha} changed")
        return data

    # -- RAVEL stages -------------------------------------------------------------------------
    def _place(self, path, sha):
        if not (path.is_file() and sha256_file(path) == sha):
            atomic_write_bytes(path, self._blob(sha))

    def _attempt(self, rundir, name):
        path = rundir / "execution_state.json"
        record = strict_load(path)["stages"].get(name) if path.exists() else None
        return None if record is None else (record.get("attempt_id"), record.get("status"))

    def _supervise(self, rundir, name):
        before = self._attempt(rundir, name)
        argv = stages.supervisor_argv(self._python, name, rundir, kill_secs=STAGE_KILL_SECONDS,
                                      poll=STAGE_POLL_SECONDS)
        proc = subprocess.run(argv, cwd=rundir, env=self._stage_env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, close_fds=True, timeout=STAGE_KILL_SECONDS + 120)
        after = self._attempt(rundir, name)
        detail = {"exit_code": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        if proc.returncode != 0:
            failure = rundir / "outputs" / name / "failure.json"
            message = f"{name} stage failed (exit {proc.returncode})"
            if after != before and failure.is_file():
                record = strict_load(failure)
                message = f"{name} stage failed: {record.get('type')}: {record.get('error')}"
            raise StageFailure(message, detail)
        require(after is not None and after[1] == "succeeded", f"{name} stage has no succeeded receipt")
        return "reused" if after == before else "executed"

    def _run_dag(self, derived, target, trace, expect):
        """Run the stages up to ``target`` with resume in the run dir of ``derived['workspace']``.

        The run dir's luminosity/title inputs are set to the cited ones first. An upstream
        stage whose output is listed in ``expect`` must reproduce it exactly (determinism
        check); RAVEL decides by its receipts which stages are reused and which rerun.
        """
        rundir = self.root / "ravel-runs" / derived["workspace"][:16]
        trace.update(stage={"name": target, "status": "not_run",
                            "ravel_run": f"ravel-runs/{derived['workspace'][:16]}"}, upstream=[])
        (rundir / "inputs").mkdir(parents=True, exist_ok=True)
        workspace = rundir / "inputs" / "workspace.json"
        if workspace.exists():
            require(sha256_file(workspace) == derived["workspace"], "RAVEL run directory workspace mismatch")
        else:
            atomic_write_bytes(workspace, self._blob(derived["workspace"]))
        if "luminosity" in derived:
            self._place(rundir / "inputs" / "luminosity.json", derived["luminosity"])
        if "title" in derived:
            self._place(rundir / "inputs" / "title.txt", derived["title"])
        for name in stages.ORDER[: stages.ORDER.index(target) + 1]:
            try:
                status = self._supervise(rundir, name)
            except StageFailure:
                if name == target:
                    trace["stage"]["status"] = "failed"
                else:
                    trace["upstream"].append({"name": name, "status": "failed"})
                raise
            content = strict_load(rundir / stages.STAGES[name]["artifact"])
            if name == target:
                trace["stage"]["status"] = status
            else:
                trace["upstream"].append({"name": name, "status": status})
            if name in expect and content != expect[name]:
                raise RuntimeError(f"determinism check failed: {status} {name} output differs from the cited artifact")
        return content

    def _run_standalone(self, name, files, trace):
        """Run a standalone stage (census, calc, figure) with resume in its keyed run dir (``stages.run_key``):
        the input files ({relative path: bytes}) are written once and a run dir's inputs never change."""
        key = stages.run_key(name, files)
        rundir = self.root / "ravel-runs" / key
        trace.update(stage={"name": name, "status": "not_run", "ravel_run": f"ravel-runs/{key}"}, upstream=[])
        for relative, data in files.items():
            path = rundir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                require(sha256_file(path) == sha256_bytes(data), "RAVEL run directory input mismatch")
            else:
                atomic_write_bytes(path, data)
        try:
            status = self._supervise(rundir, name)
        except StageFailure:
            trace["stage"]["status"] = "failed"
            raise
        content = strict_load(rundir / stages.STAGES[name]["artifact"])
        trace["stage"]["status"] = status
        return content

    def _plan(self, name, operands, params=None):
        """(derived_from, run) of one stage over resolved operand records ({argument: artifact record}); ``run(trace)``
        returns the stage's artifact content. calc is planned by ``_calc_request``."""
        if name == "fit":
            derived = {"workspace": operands["workspace"]["derived_from"]["workspace"]}
            return derived, lambda trace: self._run_dag(derived, "fit", trace, {})
        if name == "convert":
            fit = operands["fit"]
            derived = {"workspace": fit["derived_from"]["workspace"],
                       "luminosity": operands["luminosity"]["derived_from"]["luminosity"]}
            return derived, lambda trace: self._run_dag(derived, "convert", trace, {"fit": fit["content"]})
        if name == "report":
            conversion = operands["conversion"]
            derived = {**conversion["derived_from"], "title": operands["title"]["derived_from"]["title"]}
            fits = [r["content"] for r in self._artifacts.values()
                    if r["kind"] == "fit" and r["derived_from"] == {"workspace": derived["workspace"]}]
            expect = {"convert": conversion["content"], **({"fit": fits[0]} if fits else {})}
            return derived, lambda trace: self._run_dag(derived, "report", trace, expect)
        if name == "census":
            events = operands["events"]
            derived = {events["kind"]: events["derived_from"][events["kind"]],
                       "manifest": operands["manifest"]["derived_from"]["manifest"],
                       "selection": operands["selection"]["derived_from"]["selection"]}
            files = {"inputs/events.lhe.gz": self._blob(derived[events["kind"]]),
                     "inputs/manifest.json": self._blob(derived["manifest"]),
                     "inputs/selection.json": self._blob(derived["selection"])}
            return derived, lambda trace: self._run_standalone("census", files, trace)
        if name == "figure":
            fit = operands["fit"]
            files = {"inputs/fit.json": canonical_bytes(fit["content"]), stages.PARAMS: stages.params_bytes(params)}
            return dict(fit["derived_from"]), lambda trace: self._run_standalone("figure", files, trace)
        raise ContractError(f"no plan for stage {name!r}")

    def _prior_plan(self, name, params, available):
        """``_plan`` of one prior-recipe step whose operands are resolved by kind in ``available`` ({kind: handle}
        of the prior inputs and of the earlier steps' artifacts)."""
        if name == "calc":
            bind = {b["name"]: {"handle": available[b["source"]], "field": b["field"]} for b in params["bindings"]}
            return self._calc_request(params["expression"], bind, params["unit"], params["label"])
        operands = {}
        for argument, kinds in OPERANDS[name].items():
            kind = params.get("events", "events") if (name, argument) == ("census", "events") else kinds[0]
            operands[argument] = self._artifacts[available[kind]]
        return self._plan(name, operands, params if name == "figure" else None)

    def _bound_value(self, name, record, field):
        """The finite, resolved value of one calc binding (``stages/calc.py``); OpError otherwise."""
        def refuse(why):
            return OpError("invalid_arguments", f"calc: binding {name}: {why}")
        try:
            key, index = calc_stage.field_path(field)
        except calc_stage.CalcError as exc:
            raise refuse(str(exc)) from None
        content = record["content"]
        value = content.get(key) if isinstance(content, dict) else None
        if not isinstance(content, dict) or key not in content or (
                index is not None and not (isinstance(value, list) and index < len(value))):
            raise refuse(f"{record['handle']} has no field {field}")
        if index is not None:
            value = value[index]
        if value is None:
            raise refuse(f"{field} is null (not a resolved value); a calc binds only resolved values")
        if not finite_number(value):
            raise refuse(f"{field} is not a finite number")
        curve = LIMIT_STATUS.get(key)
        status = content.get("limit_status")
        if curve is not None and isinstance(status, dict):
            state = status.get("observed") if curve == "observed" else (
                status.get("expected")[index] if index is not None and isinstance(status.get("expected"), list)
                and index < len(status["expected"]) else None)
            if state != "resolved":
                raise refuse(f"{field} is a numerical bound (limit status {state}), not a resolved limit")
        return value

    def _calc_request(self, expression, bind, unit, label):
        """(derived_from, run) of a calc: the checked request (grammar, bindings, unit, label) and the union of the
        bound artifacts' derived_from, which must name one digest per input kind; OpError invalid_arguments
        otherwise."""
        try:
            calc_stage.parse(expression)
        except calc_stage.CalcError as exc:
            raise OpError("invalid_arguments", f"calc: {exc}") from None
        if not (isinstance(bind, dict) and bind and all(isinstance(ref, dict) and set(ref) == {"handle", "field"}
                                                        for ref in bind.values())):
            raise OpError("invalid_arguments", "calc: bind is a nonempty object {name: {handle, field}}")
        bindings, derived = [], {}
        for name in sorted(bind):
            record = self._artifact(bind[name]["handle"])
            value = self._bound_value(name, record, bind[name]["field"])
            bindings.append({"name": name, "handle": record["handle"], "field": bind[name]["field"], "value": value})
            for kind, sha in record["derived_from"].items():
                if derived.setdefault(kind, sha) != sha:
                    raise OpError("invalid_arguments", f"calc: the bound artifacts derive from different {kind} "
                                                       "inputs; a calc combines values of one set of inputs")
        request = {"expression": expression, "bindings": bindings, "unit": unit, "label": label}
        try:
            calc_stage.check_request(request)
        except calc_stage.CalcError as exc:
            raise OpError("invalid_arguments", f"calc: {exc}") from None
        files = {stages.PARAMS: stages.params_bytes(request)}
        return derived, lambda trace: self._run_standalone("calc", files, trace)

    # -- subject protocol ---------------------------------------------------------------------
    def _request(self, token, body, route=None, client_env=None):
        """Authenticate, account, dispatch and record one call; returns (HTTP status, response).

        ``route`` is the (method, path) of a request other than POST /op: it is authenticated
        and recorded like a call, answered not_found and never counted as an operation.
        ``client_env`` is the X-Ravel-Client-Env header, when present: recorded in
        client_env.jsonl under this call's seq (``parse_client_env``), whatever the call's outcome.
        """
        with self._lock:
            seq = self._reserve()
            if client_env is not None:
                names, marker = parse_client_env(client_env)
                append_jsonl(self.client_env_path(), {"seq": seq, "names": names, "marker": marker})
            entry = self._entry(None, None)
            status = 200
            try:
                if route is not None:
                    entry["result"] = {"method": route[0][:32], "path": route[1][:256]}
                if not (isinstance(token, str) and self._token
                        and hmac.compare_digest(token.encode(), self._token.encode())):
                    entry["incident"] = {"kind": "unauthorized_request", "detail": "missing or invalid token"}
                    raise OpError("unauthorized", "missing or invalid task token", 401)
                if route is not None:
                    raise OpError("not_found", "the service answers POST /op only", 404)
                request, problem, switch = None, "request body missing, incomplete or too large", set()
                if body is not None:
                    try:
                        request = strict_loads(body.decode("utf-8"))
                        problem = None if isinstance(request, dict) else "request must be a JSON object"
                    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                        problem = f"request is not valid JSON: {type(exc).__name__}"
                if problem is None:
                    if isinstance(request.get("op"), str):
                        entry["op"] = request["op"]
                    if isinstance(request.get("args"), dict):
                        entry["args"] = request["args"]
                    # Inspected before the budget: an attempt is an incident even past the budget.
                    switch = _switch_attempt(request)
                    if switch:
                        entry["incident"] = {"kind": "treatment_switch_attempt", "detail": sorted(switch)}
                # Every authenticated call counts, whatever its outcome; calls past the budget do not.
                if self._ops >= self.budgets["max_broker_ops"]:
                    raise OpError("budget_exhausted", "the operation budget is exhausted")
                self._ops += 1
                if problem is not None:
                    raise OpError("bad_request", problem, 400)
                result = self._dispatch(request, seq, entry, switch)
                entry["ok"] = True
                response = {"ok": True, "result": result}
            except OpError as exc:
                entry["error_code"], status = exc.code, exc.status
                if isinstance(exc, StageFailure):
                    entry["result"] = {**(entry["result"] or {}), "detail": exc.detail}
                response = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
            except Exception as exc:  # recorded, never raised into the service loop
                entry["error_code"] = "internal_error"
                entry["incident"] = {"kind": "internal_error", "detail": f"{type(exc).__name__}: {exc}"}
                response = {"ok": False, "error": {"code": "internal_error",
                                                   "message": "internal error; the call was recorded"}}
            finally:
                self._write(seq, entry)
            return status, response

    def _dispatch(self, request, seq, entry, switch):
        op, args = request.get("op"), request.get("args")
        extra = sorted(set(request) - {"op", "args"})
        if not isinstance(op, str) or op not in OPERATIONS:
            raise OpError("unknown_operation", f"unknown operation: {op!r}")
        if extra or not isinstance(args, dict):
            raise OpError("invalid_arguments", "a request is {\"op\": <name>, \"args\": {...}}")
        if switch:
            raise OpError("invalid_arguments", "unknown argument(s): " + ", ".join(sorted(switch)))
        names = OPERATIONS[op]
        if names is not None and set(args) != set(names):
            raise OpError("invalid_arguments", f"{op} takes exactly: {', '.join(names) or 'no arguments'}")
        return getattr(self, f"_op_{op}")(args, seq, entry)

    def _artifact(self, handle, kind=None):
        """The record of a handle; ``kind`` (one kind or a tuple of kinds) is what the argument accepts."""
        if not (isinstance(handle, str) and HANDLE.fullmatch(handle)):
            raise OpError("invalid_arguments", "a handle is 'art-' followed by 12 lowercase hex characters")
        record = self._artifacts.get(handle)
        if record is None:
            raise OpError("unknown_handle", f"unknown handle: {handle}")
        kinds = (kind,) if isinstance(kind, str) else kind
        if kinds is not None and record["kind"] not in kinds:
            raise OpError("invalid_arguments", f"{handle} is not a {' or '.join(kinds)} artifact")
        return record

    def _op_inputs(self, args, seq, entry):
        prior = [] if self._prior is None else [
            {"handle": h, "kind": self._artifacts[h]["kind"], "derived_from": self._artifacts[h]["derived_from"]}
            for h in self._prior.values()]
        result = {"current": [{"handle": self._current[k]["handle"], "kind": k, "sha256": self._current[k]["sha256"]}
                              for k in INPUT_KINDS if k in self._current], "prior": prior}
        entry["result"] = result
        return result

    def _op_show(self, args, seq, entry):
        record = self._artifact(args["handle"])
        entry["result"] = {k: record[k] for k in ("handle", "kind", "content_sha256", "derived_from")}
        return {k: record[k] for k in ("handle", "kind", "content", "derived_from")}

    def _run_stage_op(self, target, derived, run, seq, entry, summary):
        trace = {}
        try:
            content = run(trace)
        finally:
            entry["stage"] = trace.get("stage")
            entry["result"] = {"upstream_stages": trace.get("upstream", [])}
        kind = stages.STAGES[target]["kind"]
        handle, _ = self._store(kind, "subject_request", content, digest(content), derived, seq)
        result = {"handle": handle, "stage_status": trace["stage"]["status"],
                  **{k: content[k] for k in summary}, "derived_from": derived}
        entry["result"] = {**result, "upstream_stages": trace["upstream"]}
        return result

    def _stage_budget(self):
        """Count one census or calc request against max_stage_executions (like fits: executed or reused)."""
        if self._stage_runs >= self.budgets["max_stage_executions"]:
            raise OpError("budget_exhausted", "the census and calc budget is exhausted")
        self._stage_runs += 1

    def _op_fit(self, args, seq, entry):
        workspace = self._artifact(args["workspace"], "workspace")
        if self._fits >= self.budgets["max_fits"]:
            raise OpError("budget_exhausted", "the fit budget is exhausted")
        self._fits += 1
        derived, run = self._plan("fit", {"workspace": workspace})
        return self._run_stage_op("fit", derived, run, seq, entry,
                                  ("obs_limit_events", "exp_limits_events", "limit_status"))

    def _op_convert(self, args, seq, entry):
        operands = {"fit": self._artifact(args["fit"], "fit"),
                    "luminosity": self._artifact(args["luminosity"], "luminosity")}
        derived, run = self._plan("convert", operands)
        return self._run_stage_op("convert", derived, run, seq, entry,
                                  ("sigma_vis_obs_fb", "sigma_vis_exp_fb", "luminosity_fb"))

    def _op_report(self, args, seq, entry):
        operands = {"conversion": self._artifact(args["conversion"], "conversion"),
                    "title": self._artifact(args["title"], "title")}
        derived, run = self._plan("report", operands)
        return self._run_stage_op("report", derived, run, seq, entry, ("text",))

    def _op_census(self, args, seq, entry):
        operands = {name: self._artifact(args[name], kinds) for name, kinds in OPERANDS["census"].items()}
        self._stage_budget()
        derived, run = self._plan("census", operands)
        return self._run_stage_op("census", derived, run, seq, entry, CENSUS_SUMMARY)

    def _op_calc(self, args, seq, entry):
        if not CALC_ARGS <= set(args) <= CALC_ARGS | CALC_OPTIONAL:
            raise OpError("invalid_arguments", "calc takes exactly: expr, bind, unit, and optionally label")
        derived, run = self._calc_request(args["expr"], args["bind"], args["unit"], args.get("label"))
        self._stage_budget()
        return self._run_stage_op("calc", derived, run, seq, entry, ("result", "declared_unit"))

    def _op_submit(self, args, seq, entry):
        try:
            check_submission(args)
            contracts = _contracts()
            if contracts is not None and hasattr(contracts, "validate_submission"):
                contracts.validate_submission(args)
        except (ValueError, TypeError, KeyError) as exc:
            raise OpError("invalid_arguments", f"invalid submission: {exc}") from exc
        verdict = guard.evaluate(args, self._current, self._artifacts)
        diagnostics = verdict["diagnostics"]
        accepted = not (self.guard_mode == "block" and verdict["blocking"])
        submission_id = f"sub-{len(self._submissions) + 1:03d}"
        self._submissions.append({"submission_id": submission_id, "accepted": accepted})
        result = {"submission_id": submission_id, "accepted": accepted}
        if self.feedback == "diagnostic":
            text = guard.feedback_text(diagnostics)
            result["message"] = (ACCEPTED if accepted else NOT_ACCEPTED) + (f"\n{text}" if text else "")
            result["diagnostics"] = guard.subject_diagnostics(diagnostics)
            entry["feedback_shown"] = "diagnostic" if diagnostics else "silent_ack"
        else:
            result["message"] = ACCEPTED if accepted else NOT_ACCEPTED
            entry["feedback_shown"] = "silent_ack"
        entry["guard"] = {"mode": self.guard_mode, "feedback": self.feedback, "accepted": accepted,
                          "diagnostics": diagnostics}
        entry["result"] = result
        return result

    def _op_note(self, args, seq, entry):
        try:
            check_decision_record(args)
            contracts = _contracts()
            if contracts is not None and hasattr(contracts, "validate_decision_record"):
                contracts.validate_decision_record(args)
        except (ValueError, TypeError, KeyError) as exc:
            raise OpError("invalid_arguments", f"invalid decision record: {exc}") from exc
        entry["result"] = {"decision_id": args["decision_id"]}
        return {"decision_id": args["decision_id"]}

    def _op_status(self, args, seq, entry):
        result = {"ops_used": self._ops, "ops_remaining": self.budgets["max_broker_ops"] - self._ops,
                  "fits_used": self._fits, "fits_remaining": self.budgets["max_fits"] - self._fits,
                  "stage_executions_used": self._stage_runs,
                  "stage_executions_remaining": self.budgets["max_stage_executions"] - self._stage_runs,
                  "submissions": [dict(s) for s in self._submissions]}
        entry["result"] = result
        return result
