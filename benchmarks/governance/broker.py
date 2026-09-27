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
Kernel work runs as RAVEL supervised stages (fit -> convert -> report, resume) with one
fixed interpreter string and one fixed environment, in one RAVEL run directory per
workspace digest (``ravel-runs/<first 16 hex of its sha256>/``). The stage environment
is an allowlist (STAGE_ENV_KEYS, never a copy of os.environ) and must pin the kernel
source with PYTHONPATH; the broker verifies once that the interpreter imports ``ravel``
from there. RAVEL's ``execution_state.json`` stays the stage authority; custody records
what the subject asked for and received.

Coordinator-owned layout under ``root``: custody.jsonl, artifacts/, blobs/<sha256>
(exact input bytes for re-establishing stages), ravel-runs/, stage-home/, stage-tmp/.
Coordinator calls are recorded with the ops ``register_inputs`` (one line) and
``create_prior`` (one line per step: inputs, fit, convert, report); every other op is a
subject call. Standard library only.
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
from .canonical import (ContractError, append_jsonl, atomic_write_bytes, canonical_bytes, digest,
                        require, sha256_bytes, sha256_file, strict_load, strict_loads, write_once)

INPUT_KINDS = ("workspace", "luminosity", "title")
PRIOR_KINDS = ("fit", "conversion", "report")
MODES = {("audit", "silent"), ("audit", "diagnostic"), ("block", "diagnostic")}
BUDGET_KEYS = {"max_broker_ops", "max_fits"}
TREATMENT_WORDS = frozenset({"mode", "arm", "guard", "enforcement", "feedback"})
FREE_FORM = {"note": ("requested_budget",)}      # subject-defined objects: their keys are not scanned
STAGE_ENV_KEYS = frozenset({"PATH", "PYTHONPATH", "PYTHONHASHSEED", "PYTHONNOUSERSITE", "PYTHONUTF8", "LANG", "LC_ALL",
                            "LC_CTYPE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                            "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
                            "CONDA_PREFIX"})
KERNEL_PROBE = "import importlib.util as u; s = u.find_spec('ravel'); print(s.origin if s and s.origin else '')"
TOKEN_HEADER = "X-Ravel-Task-Token"
OPERATIONS = {"inputs": (), "show": ("handle",), "fit": ("workspace",), "convert": ("fit", "luminosity"),
              "report": ("conversion", "title"), "submit": None, "note": None, "status": ()}
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
        _keys(claim, CLAIM_KEYS, "claim")
        require(type(claim["schema_version"]) is int and claim["schema_version"] == 1, "claim schema_version: expected 1")
        require(isinstance(claim["claim_id"], str) and claim["claim_id"].strip(), "claim_id: nonblank string required")
        require(claim["claim_id"] not in ids, f"duplicate claim_id: {claim['claim_id']}")
        ids.add(claim["claim_id"])
        require(claim["status"] in ("provisional", "retracted", "final"), "claim status: invalid")
        require(isinstance(claim["text"], str), "claim text: string required")
        quantity = claim["quantity"]
        require(quantity is None or guard.decimal_value(quantity) is not None,
                f"claim quantity: decimal string within 1e+-{guard.MAX_EXPONENT}, or null")
        require(claim["unit"] in ("events", "fb", None), "claim unit: events, fb or null")
        require(claim["role"] in ("observed", "expected", "diagnostic", "not_applicable"), "claim role: invalid")
        require(claim["expected_quantile"] in (*guard.QUANTILES, None), "claim expected_quantile: invalid")
        require((claim["role"] == "expected") == (claim["expected_quantile"] is not None),
                "claim expected_quantile: required exactly when role is expected")
        require((quantity is None) == (claim["artifact_field"] is None),
                "claim artifact_field: required exactly when quantity is present")
        if claim["artifact_field"] is not None:
            guard.field_spec(claim["artifact_field"])
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
    require(isinstance(data, bytes), f"{kind}: input bytes required")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{kind}: input is not UTF-8") from exc
    if kind == "title":
        require(text.strip(), "title: blank input")
        return text
    content = strict_loads(text)
    require(isinstance(content, dict), f"{kind}: JSON object required")
    return content


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
        self._send(*self.server.broker._request(self.headers.get(TOKEN_HEADER), None, route=(self.command, self.path)))
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
            status, response = self.server.broker._request(self.headers.get(TOKEN_HEADER), body)
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
        self._seq = self._ops = self._fits = 0
        self._submissions = []
        self._lock = threading.Lock()
        self._server = self._thread = self._token = None
        self._started = False

    # -- coordinator interface -------------------------------------------------------------
    def custody_path(self) -> Path:
        return self.root / "custody.jsonl"

    def register_inputs(self, current: dict) -> dict:
        """Register the subject's current inputs; returns kind -> handle."""
        with self._lock:
            require(self._current is None and not self._started, "current inputs are registered once, before start")
            require(isinstance(current, dict) and set(current) <= set(INPUT_KINDS)
                    and {"workspace", "title"} <= set(current), "current inputs: workspace, title, optional luminosity")
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

    def create_prior(self, prior: dict) -> dict:
        """Run fit -> convert -> report on the prior inputs; returns kind -> handle for fit/conversion/report."""
        with self._lock:
            require(not self._prior_attempted and not self._started, "prior artifacts are created once, before start")
            require(isinstance(prior, dict) and set(prior) == set(INPUT_KINDS),
                    "prior inputs require workspace, luminosity and title")
            for kind, data in prior.items():
                _input_content(kind, data)
            self._prior_attempted = True   # a failed prior is terminal for this broker, never retried
            seq = self._reserve()
            entry = self._entry("create_prior", {"step": "inputs", **{k: sha256_bytes(prior[k]) for k in INPUT_KINDS}})
            try:
                handles = {kind: self._store_input(kind, prior[kind], "prior", seq)[0] for kind in INPUT_KINDS}
                entry.update(ok=True, result=handles)
            except Exception as exc:
                entry.update(error_code="internal_error", incident={"kind": "internal_error", "detail": repr(exc)})
                raise
            finally:
                self._write(seq, entry)
            shas = {kind: sha256_bytes(prior[kind]) for kind in INPUT_KINDS}
            made, expect = {}, {}
            for name in stages.ORDER:
                kind = stages.STAGES[name]["kind"]
                # fit <- workspace; convert <- workspace, luminosity; report <- all three inputs.
                derived = {k: shas[k] for k in INPUT_KINDS[: stages.ORDER.index(name) + 1]}
                seq = self._reserve()
                entry = self._entry("create_prior", {"step": name, **derived})
                trace = {}
                try:
                    content = self._run_dag(derived, name, trace, expect)
                    handle, _ = self._store(kind, "prior", content, digest(content), derived, seq)
                    made[kind], expect[name] = handle, content
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
            server = _Server(("127.0.0.1", 0), _Handler)
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

    # -- subject protocol ---------------------------------------------------------------------
    def _request(self, token, body, route=None):
        """Authenticate, account, dispatch and record one call; returns (HTTP status, response).

        ``route`` is the (method, path) of a request other than POST /op: it is authenticated
        and recorded like a call, answered not_found and never counted as an operation.
        """
        with self._lock:
            seq = self._reserve()
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
        if not (isinstance(handle, str) and HANDLE.fullmatch(handle)):
            raise OpError("invalid_arguments", "a handle is 'art-' followed by 12 lowercase hex characters")
        record = self._artifacts.get(handle)
        if record is None:
            raise OpError("unknown_handle", f"unknown handle: {handle}")
        if kind is not None and record["kind"] != kind:
            raise OpError("invalid_arguments", f"{handle} is not a {kind} artifact")
        return record

    def _op_inputs(self, args, seq, entry):
        prior = [] if self._prior is None else [
            {"handle": h, "kind": self._artifacts[h]["kind"], "derived_from": self._artifacts[h]["derived_from"]}
            for h in (self._prior[k] for k in PRIOR_KINDS)]
        result = {"current": [{"handle": self._current[k]["handle"], "kind": k, "sha256": self._current[k]["sha256"]}
                              for k in INPUT_KINDS if k in self._current], "prior": prior}
        entry["result"] = result
        return result

    def _op_show(self, args, seq, entry):
        record = self._artifact(args["handle"])
        entry["result"] = {k: record[k] for k in ("handle", "kind", "content_sha256", "derived_from")}
        return {k: record[k] for k in ("handle", "kind", "content", "derived_from")}

    def _run_stage_op(self, target, derived, expect, seq, entry, summary):
        trace = {}
        try:
            content = self._run_dag(derived, target, trace, expect)
        finally:
            entry["stage"] = trace.get("stage")
            entry["result"] = {"upstream_stages": trace.get("upstream", [])}
        kind = stages.STAGES[target]["kind"]
        handle, _ = self._store(kind, "subject_request", content, digest(content), derived, seq)
        result = {"handle": handle, "stage_status": trace["stage"]["status"],
                  **{k: content[k] for k in summary}, "derived_from": derived}
        entry["result"] = {**result, "upstream_stages": trace["upstream"]}
        return result

    def _op_fit(self, args, seq, entry):
        workspace = self._artifact(args["workspace"], "workspace")
        if self._fits >= self.budgets["max_fits"]:
            raise OpError("budget_exhausted", "the fit budget is exhausted")
        self._fits += 1
        derived = {"workspace": workspace["derived_from"]["workspace"]}
        return self._run_stage_op("fit", derived, {}, seq, entry,
                                  ("obs_limit_events", "exp_limits_events", "limit_status"))

    def _op_convert(self, args, seq, entry):
        fit = self._artifact(args["fit"], "fit")
        luminosity = self._artifact(args["luminosity"], "luminosity")
        derived = {"workspace": fit["derived_from"]["workspace"],
                   "luminosity": luminosity["derived_from"]["luminosity"]}
        return self._run_stage_op("convert", derived, {"fit": fit["content"]}, seq, entry,
                                  ("sigma_vis_obs_fb", "sigma_vis_exp_fb", "luminosity_fb"))

    def _op_report(self, args, seq, entry):
        conversion = self._artifact(args["conversion"], "conversion")
        title = self._artifact(args["title"], "title")
        derived = {**conversion["derived_from"], "title": title["derived_from"]["title"]}
        fits = [r["content"] for r in self._artifacts.values()
                if r["kind"] == "fit" and r["derived_from"] == {"workspace": derived["workspace"]}]
        expect = {"convert": conversion["content"], **({"fit": fits[0]} if fits else {})}
        return self._run_stage_op("report", derived, expect, seq, entry, ("text",))

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
                  "submissions": [dict(s) for s in self._submissions]}
        entry["result"] = result
        return result
