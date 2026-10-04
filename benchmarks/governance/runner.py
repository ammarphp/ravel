"""Assignment coordinator (slice design §3, §6, §10; WP07): build, run, seal and account.

``build_synthetic_campaign`` freezes a synthetic campaign from the task bank (``tasks.registry.build_bank``:
every registered family, schema_version 2 task definitions recording the campaign's per-run task budget,
one request per family): the v1 spec and registry and the §4.1 manifest (``campaign_manifest.write_campaign``),
plus the coordinator-private directory ``<campaign>/coordinator/`` (the bank build, campaign secret,
planted canary, environment manifest, run configuration, behavior plans, run lock). The whole
campaign is assembled in a temporary directory and renamed into place only after it loads, so a
failed build leaves nothing behind. ``run_campaign`` walks the registry in order and, per
assignment, copies the evaluator files to ``evaluator/<run_id>/``, materializes the §6 subject
workspace under an opaque handle, admits it, applies global budget admission, prepares and
starts the broker, admits the launch environment and prompt, launches the adapter under the
Seatbelt profile, stops the broker and seals ``runs/<run_id>/sealed/`` with its evidence
manifest. Every step is a line in the append-only ``runs/<run_id>/journal.jsonl``; the adapter's
raw streams and call record go to the coordinator-owned ``runs/<run_id>/host/`` first.
``write_outcomes`` and ``report`` turn the evaluator's judge reports into the v1 outcomes
document, the v1 summary and the analysis.

Sealed ``run.json`` and ``launch.json`` follow ``contracts.validate_run_record`` and
``validate_launch_record`` (slice design §10a). The launcher journals ``process_started`` ({pid,
pgid, marker, started_at, leader_start}, via ``isolation.launch(on_start=...)``) before it waits on
the subject. A lost launch (journaled ``launched`` without ``exited`` after a coordinator
interruption, or an adapter that raised after the launch began) is recorded as ``interrupted_crash``
after a census of exactly that launch (``isolation.census_launch`` on the journaled record: its
sandbox marker, or its process group while the recorded leader holds the group id; never a
command-line match), never relaunched and never given fresh budget (retry policy none).
It is sealed as ``status_hint: interrupted``, the one lost-launch representation: the cause
(``coordinator_interrupted`` or ``adapter_error``) is its validity flag and ``adapter_result.json``
is coordinator-authored (``details.authored_by`` ``coordinator``, cause, note and census; its own
status_hint is ``launch_error``, the nearest AdapterResult value), so the evaluator scores it v1
``crash`` with the coordinator's note. ``launch_error`` in run.json is only an adapter-reported
launch failure. A launch the adapter never recorded seals ``argv``/``env_names`` as ``[]`` with the
flag ``launch_unrecorded``. ``started_utc`` is the launch time (for a ``not_started`` run the time
it was closed, equal to ``ended_utc``); ``ended_utc`` is the exit, crash or not-started record time.
A sealed run is skipped on resume, and becomes a v1 row in ``write_outcomes``, only while its seal
reconciles (``seal_problem``: sealed tree, ``evidence_manifest.json`` and the evidence_sha256 journaled
at sealing); otherwise the coordinator stops with a coordinator-integrity error (red-team RT-01).

Binding (holistic review R0.0-R1.6). The coordinator freezes campaign.json's sha256 in
``coordinator/campaign.sha256`` and every run's ``materialized``/``launched`` records; any later
change refuses the load, write_outcomes and report. The frozen treatment texts are read once at
load, verified against every arm manifest and held; before each launch the run is re-verified
against the frozen campaign (code behind every common hash, texts, the prompt's instruction segment,
request, materialized workspace; journaled as ``admitted.verified``) and a drifted run is not
started, and a drift during the run is flagged ``code_drift_during_run``. The recording launcher
refuses a launch call that changes the coordinator's environment or carries evaluator material
(``LaunchRefused``); a real host must match the frozen host configuration and launch identically in
every run (``host_binding``; its spend ceiling equals ``usd_per_run``). A failure before the
launcher was called is not_started with no charge. Budget admission is exact (decimal). A clock
step back closes a run at its launch time (``clock_stepped_back``). Outcomes re-derive every
audit.py judge report from the sealed evidence; a run whose seal does not reconcile gets a v1 row
only through a recorded human incident decision (``record_incident_decision``: the evaluator's
null-judgment row). ``behavioral_check`` is the §12.3 behavioral treatment check as a product check.

Real hosts (smoke spec §9 step 5). ``_build_campaign`` is the one builder: ``build_synthetic_campaign``
calls it with the fake host (unchanged behaviour: the whole family, ``host_launch`` null) and
``live.build_live_campaign`` with a pinned Claude Code CLI, a task subset (in family-index order; the
family stays whole), the frozen approval, the single-use approval ledger and ``host_launch`` (the
real-host launch declaration in ``coordinator/config.json``, bound into the environment manifest with
the family index's sha256). A real host's binding is written once at build from the adapter the
runtime factory builds (``live.claude_adapter``); every launch is compared with it, including the exact
argv and environment the adapter passes (M6). Per assignment a real host gets a private host-state
directory (``<host_state_root>/<opaque>``), its own allowlist proxy on 127.0.0.1 that serves only the
launch's leader process (``allowlist_proxy``, attribution by socket ownership), the real-host profile
(the pinned binary, the per-run config and tmp directories, the proxy port, the credential directory,
the keychains and ``~/.claude.json`` denied, the keychain mach services removed) and the one
credential exception: the recording launcher reads the declared token file after every other check and
puts the value only into the environment it hands ``isolation.launch`` (``launch_call.json`` records
names only). After the run, before anything is sealed, the coordinator sweeps the campaign, the
workspace and the host state for the token and its encodings and redacts every hit
(``host/redactions.json``), checks the keychain for an item the host may have written, reads the task
client's environment-name reports, scans the host's transcripts and state for canaries and records
the proxy's decisions; each finding is a sealed validity flag or a journaled note. The kernel's stage
receipts are sealed and compared with the frozen kernel, interpreter and stage workers (M5). The
behavioral gate reads the latest record and re-derives it (M1); a failing post-run drift check never
loses a paid result (M2). ``run_campaign`` honours ``coordinator/stop.json`` (an automated stop rule or
a human ``cli.py stop``: every remaining assignment is closed not_started, charge 0), ``limit`` (a
pause) and, for a real host, preflight, the run-start credential validation (a pause: nothing
journaled) and a hard core-file limit of 0.

Standard library only. A campaign with a host other than the synthetic fake host runs only with
``RAVEL_EVAL_LIVE=1``.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import fcntl
import hashlib
import hmac
import importlib
import importlib.util
import json
import os
import platform
import re
import resource
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from . import (allowlist_proxy, analysis, campaign_manifest, canonical, contracts, credentials, guard, isolation,
               stages, treatment)
from .adapters import fake as fake_adapter
from .adapters.base import (AdapterResult, HostDriftError, assert_prompt_not_in_argv, ipc_residue_flagged,
                            profile_sha256)
from .broker import BUDGET_KEYS as BROKER_BUDGET, OPERATIONS as BROKER_OPERATIONS, STAGE_ENV_KEYS, TOKEN_HEADER, Broker
from .canonical import ContractError, require
from .contracts import (LAUNCH_FIELDS, LOST_CAUSES, RUN_FIELDS, RUN_STATUS_HINTS, validate_launch_record,  # noqa: F401
                        validate_run_record)
from .tasks import registry

experiment = contracts.experiment
GOVERNANCE = Path(__file__).resolve().parent
CHECKOUT = GOVERNANCE.parents[1]
PROTOCOL = CHECKOUT / "docs/development/evaluation-study/slice-design.md"
CLIENT = GOVERNANCE / "client" / "ravel_task.py"
TOOL_GUIDE = GOVERNANCE / "client" / "tools.md"
# The research packet named by the slice plan: research-planning/<PACKET_NAME> in the lab workspace that
# holds the checkout (a sibling of the checkout). It lies inside the lab tree and is forbidden explicitly as
# well (packet_dirs). Derived from the checkout, never a host-specific absolute path; PACKET_ENV, read from
# the coordinator's own environment (a subject's is built from scratch), adds one location, never replaces one.
PACKET_NAME = "2026-09-25-ravel-research-packet"
PACKET_ENV = "RAVEL_EVAL_PACKET_DIR"
PACKET_DIR = str(CHECKOUT.parent / "research-planning" / PACKET_NAME)
COORDINATOR = "coordinator"
STATES = ("materialized", "admitted", "admission_failed", "launched", "process_started", "exited", "sealed",
          "not_started", "interrupted_crash")
LOST_HINT = "interrupted"   # contracts.RUN_STATUS_HINTS: the one sealed representation of a lost launch
CONFIG_FIELDS = ("schema_version", "checkout", "stage_python", "stage_env", "subject_python", "subject_prefix",
                 "sandbox", "forbidden_roots", "subjects_root", "host_launch")
ASSIGNMENT_KEYS = ("adapter", "behavior", "behavior_plan_sha256")
INTERRUPTED = "coordinator interrupted; no retry under policy none"
LOST_NOTES = {"coordinator_interrupted": INTERRUPTED,
              "adapter_error": "adapter failed after the launch began; no retry under policy none"}
SUBJECT_ROOT = "$SUBJECT_ROOT"
DEFAULT_BUDGET = {"usd_per_run": 1.0, "seconds_per_run": 600, "max_broker_ops": 40, "max_fits": 4,
                  "max_stage_executions": 6}
SYNTHETIC_MODEL = "synthetic-fake-subject (no model)"
SYNTHETIC_AUTHORIZATION = {"kind": "synthetic_engineering", "reference_sha256": None,
                           "reference": "SYNTHETIC engineering campaign from runner.build_synthetic_campaign; "
                                        "fake host, no model call; not an approval"}
STAGE_ENV = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1", "LC_ALL": "C", "LANG": "C",
             **{name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                       "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")}}
RESOURCE_POLICY = ("Use only this workspace and bin/ravel-task; at most {ops} task-service operations, of which at "
                   "most {fits} fit operations and at most {stages} census and calc operations together; wall-clock "
                   "limit {seconds:g} s; no network access except the task service.")
# Content canaries, checked at every campaign load against every subject-visible byte: the family
# build's random canary (index["canary"], planted in every oracle record and task definition before
# hashing), fragments present in every oracle record / task definition however it is formatted (the
# oracle module each record names, by the definition's oracle_kind), and each task's value canaries,
# which its family index lists (tasks.builder.value_canaries: the distinctive printed oracle, fault and
# convention values; for likelihood_freshness exactly _value_canaries of its oracle record). The random
# campaign canary is the tripwire file coordinator/canary.txt.
ORACLE_CANARY = "governance.oracle.counting"
ORACLE_CANARIES = {"counting": ORACLE_CANARY, "lhe_census": "governance.oracle.lhe_census"}
DEFINITION_CANARY = "exposure_class"   # a key of every schema_version 2 task definition (never subject-visible)
FIXED_CANARIES = (*ORACLE_CANARIES.values(), DEFINITION_CANARY)
VALUE_FIELDS = ("obs_limit_events", "exp_limits_events", "sigma_vis_obs_fb", "sigma_vis_exp_fb")
SEAL_REMEDY = ("Remedy: a human compares runs/<run_id>/sealed/ with runs/<run_id>/evidence_manifest.json, "
               "the sealed evidence_sha256 in runs/<run_id>/journal.jsonl and runs/<run_id>/judge_report.json, "
               "records the incident and its decision for each run (a seal that does not reconcile: "
               "runner.record_incident_decision / cli.py incident-decision, which admits only the evaluator's "
               "null-judgment row for that run); never re-seal, re-audit or edit a digest, a judge report or the "
               "journal to make them agree.")
CUSTODY_INCIDENT = ("refusing to {action}: custody incident (human gate) in {count} run(s) {runs}: {what}. "
                    + SEAL_REMEDY + " Outcomes and reports are written only when every run's sealed tree, evidence "
                    "manifest and journaled seal agree and every launched run's judged evidence_sha256 equals that "
                    "seal.")
COORDINATOR_INTEGRITY = ("coordinator integrity: run {run_id}: {what}; the sealed evidence must equal the "
                         "evidence_sha256 the coordinator journaled when it sealed the run, so it is not skipped, "
                         "resumed or scored. " + SEAL_REMEDY)
PLACEHOLDER_HANDLE = "0" * 16   # build-time profile and prompt checks use a workspace of this name
CAMPAIGN_DIGEST = "campaign.sha256"   # coordinator/: sha256 of campaign.json's bytes, written when frozen
INCIDENTS = "incidents"               # coordinator/incidents/<run_id>.json: recorded human incident decisions
BEHAVIORAL = "behavioral"             # coordinator/behavioral/<n>/: behavioral treatment checks (brokers, result)
HOST_BINDING = "host_binding.json"    # coordinator/: a real host's launch identity, bound at its first launch
INCIDENT_DECISION = "admit_null_judgment_row"
INCIDENT_FIELDS = ("schema_version", "run_id", "decision", "decided_by", "decided_utc", "reason",
                   "journaled_evidence_sha256", "tree_sha256", "manifest_sha256", "problem")
CLOCK_FLAG = "clock_stepped_back"          # a closing journal time before the launch time: ended set to started
CODE_DRIFT_FLAG = "code_drift_during_run"  # treatment code verified before the launch differed after it
PROBE_REUSE = "recompute_convert"          # the behavioral check probes the task whose conversion alone is stale
STOP_FILE = "stop.json"                    # coordinator/stop.json: no further launch (live.STOP_RULES or cli.py stop)
STOP_FIELDS = ("schema_version", "time_utc", "run_id", "rule", "reason", "set_by")
STOPPED_REASON = "campaign stopped before this assignment ({rule}: {reason}); no launch under the stop"
HOST_ROOT_MODE = 0o700                     # a real host's subjects and host-state roots: private to this user
RECEIPTS = "ravel-runs"                    # broker/<run_id>/ravel-runs/<16 hex>/execution_state.json (M5)
PLACEHOLDER_PORTS = (1, 2)                 # build- and load-time profile checks: broker and proxy ports


class LaunchRefused(RuntimeError):
    """The recording launcher refused a launch call before anything started (never an OSError or
    ValueError, so an adapter's launch_host cannot turn it into a launch_error result)."""

    def __init__(self, message, code="launch_refused"):
        super().__init__(message)
        self.code = code


class CoordinatorInterrupted(BaseException):
    """SIGHUP or SIGTERM reached a live coordinator (cli.py run installs the handlers, M8). A BaseException, so no
    handler on the way turns it into a result: isolation.launch's finally kills the launch by census, the broker
    and proxy stop in _start's finally, and the resumed run is a lost launch (interrupted_crash)."""


# ---------------------------------------------------------------- small helpers

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _pretty(value) -> bytes:
    return json.dumps(value, indent=1, sort_keys=True, allow_nan=False).encode() + b"\n"


def _within(path: str, root: str) -> bool:
    for a, b in ((path, root), (path.casefold(), root.casefold())):
        if a == b or a.startswith(b.rstrip("/") + "/"):
            return True
    return False


def _record(journal, state, **details):
    require(state in STATES, f"journal: unknown state {state!r}")
    canonical.append_jsonl(journal, {"state": state, "time_utc": utc_now(), "details": details})


def read_journal(path) -> list:
    """The assignment journal; a torn or malformed line fails closed (repair by hand, never guess)."""
    records, error = canonical.read_jsonl(path)
    require(error is None, f"{path}: malformed journal ({error}); refusing to guess the run's state")
    for i, record in enumerate(records):
        require(isinstance(record, dict) and set(record) == {"state", "time_utc", "details"}
                and record["state"] in STATES and isinstance(record["details"], dict),
                f"{path}: line {i + 1} is not a journal record")
    return records


@contextlib.contextmanager
def campaign_lock(campaign_dir):
    """Exclusive, non-blocking coordinator/run.lock: one process runs, seals, audits or reports a
    campaign at a time. flock is released by the OS when its holder dies (a resume is not blocked)."""
    path = Path(campaign_dir) / COORDINATOR / "run.lock"
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"{path.parent}: no coordinator directory")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ContractError(f"another coordinator is using campaign {Path(campaign_dir).name}") from None
        yield
    finally:
        os.close(fd)


def audit_module():
    """The independent evaluator (governance.audit), or None when this checkout has no audit.py."""
    name = f"{__package__}.audit"
    return importlib.import_module(name) if importlib.util.find_spec(name) is not None else None


def unsealed_runs(campaign_dir) -> list:
    """Registry run ids (in order) whose journal has no ``sealed`` record."""
    registry = canonical.strict_load(Path(campaign_dir) / campaign_manifest.REGISTRY)
    return [r["run_id"] for r in registry["runs"]
            if not any(x["state"] == "sealed" for x in read_journal(Path(campaign_dir) / "runs" / r["run_id"]
                                                                   / "journal.jsonl"))]


def evidence_digest(run_dir) -> str:
    """canonical.digest of the sealed tree manifest; evidence_manifest.json must hold it exactly (its
    canonical bytes, not a value-equal rewrite such as ``"bytes": 123.0`` for 123, which a Python ``==``
    would accept while every digest of it differs). This alone cannot see a post-seal change that
    rewrote evidence_manifest.json consistently: callers that trust a seal use
    ``seal_problem``/``sealed_evidence``, which also check the journaled seal."""
    run_dir = Path(run_dir)
    entries = canonical.tree_manifest(run_dir / "sealed")
    require(canonical.canonical_bytes(canonical.strict_load(run_dir / "evidence_manifest.json"))
            == canonical.canonical_bytes(entries), f"{run_dir.name}: sealed tree differs from evidence_manifest.json")
    return canonical.digest(entries)


# The seal paths of one run as _seal writes them and campaign_manifest.verify reads them: (name under
# runs/<run_id>, "" for the run directory, None for runs/ itself; whether it is a directory)
SEAL_PATHS = ((None, True), ("", True), (campaign_manifest.JOURNAL, False), (campaign_manifest.SEALED, True),
              (campaign_manifest.EVIDENCE_MANIFEST, False))


def _seal_path_problem(run_dir):
    """None when runs/, runs/<run_id>, its journal.jsonl, sealed/ and evidence_manifest.json are each absent or a
    real directory / regular file (lstat: no symlink followed), else the problem. The coordinator never writes a
    symlink there; one would let a seal be read through bytes outside the run (campaign_manifest.verify reports
    the same paths)."""
    run_dir = Path(run_dir)
    for name, directory in SEAL_PATHS:
        path = run_dir.parent if name is None else run_dir / name if name else run_dir
        label = "runs" if name is None else f"runs/{run_dir.name}" + (f"/{name}" if name else "")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            return (f"{label} is a symlink or not a {'directory' if directory else 'regular file'} (the coordinator "
                    "never writes one there; a seal is never read through it)")
    return None


def seal_problem(run_dir) -> tuple:
    """(evidence digest, None) when the run's seal reconciles, else (digest or None, problem).

    Reconciles (red-team RT-01) three records of one seal: the sealed tree, its evidence_manifest.json
    and the evidence_sha256 of the run's one ``sealed`` journal record, written by the coordinator at
    sealing time. A tree edited after sealing with a consistently rewritten manifest agrees with the
    manifest but not with the journal. A symlink or an irregular entry on a seal path
    (``_seal_path_problem``) is a problem before anything is read through it."""
    run_dir = Path(run_dir)
    problem = _seal_path_problem(run_dir)
    if problem is not None:
        return None, problem
    seals = [r["details"].get("evidence_sha256") for r in read_journal(run_dir / "journal.jsonl")
             if r["state"] == "sealed"]
    if len(seals) != 1 or not canonical.is_sha256(seals[0]):
        return None, f"the journal holds {len(seals)} sealed record(s), not one with an evidence_sha256"
    try:
        digest = evidence_digest(run_dir)
    except (ContractError, OSError, ValueError) as exc:
        return None, f"the sealed tree does not match its evidence manifest ({exc})"
    if digest != seals[0]:
        return digest, (f"the sealed tree and evidence manifest digest {digest} differ from the evidence_sha256 "
                        f"{seals[0]} journaled when the run was sealed (changed after sealing)")
    return digest, None


def sealed_evidence(run_dir) -> str:
    """The reconciled evidence digest of a sealed run (``seal_problem``); ContractError (coordinator
    integrity, naming the run and the remedy) when the seal does not reconcile."""
    digest, problem = seal_problem(run_dir)
    require(problem is None, COORDINATOR_INTEGRITY.format(run_id=Path(run_dir).name, what=problem))
    return digest


def exact(value) -> Decimal:
    """A budget or charge number as the exact decimal it prints as (repr): sums and comparisons of
    USD and seconds never lose a cent to binary rounding (0.3 x 3 is 0.9, not 0.8999999999999999)."""
    require(canonical.finite_number(value), f"budget arithmetic: finite number required, got {value!r}")
    return Decimal(repr(value))


def _utc_seconds(stamp) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def campaign_digest_problem(campaign_dir, current=None):
    """None when campaign.json still has the bytes the coordinator froze, else the problem.

    campaign.json's budgets (global caps, broker operations, fits), host and arms are read on every
    load; only usd_per_run and seconds_per_run are also bound by the v1 spec. The coordinator writes
    the sha256 of campaign.json's bytes to ``coordinator/campaign.sha256`` when it freezes the
    campaign, and into every run's ``materialized`` and ``launched`` journal records; any recorded
    digest that differs from the current bytes is a change after the freeze. A campaign the
    coordinator built (coordinator/config.json present) must hold the frozen digest."""
    campaign_dir = Path(campaign_dir)
    current = current or canonical.sha256_file(campaign_dir / campaign_manifest.MANIFEST)
    record = campaign_dir / COORDINATOR / CAMPAIGN_DIGEST
    if record.is_file() and not record.is_symlink():
        frozen = record.read_text().strip()
        if frozen != current:
            return (f"campaign.json (sha256 {current}) differs from the bytes frozen at build (sha256 {frozen}): its "
                    "budgets, host, arms or storage changed after the freeze")
    elif os.path.lexists(record) or os.path.lexists(campaign_dir / COORDINATOR / "config.json"):
        return f"coordinator/{CAMPAIGN_DIGEST} is missing or not a regular file: the frozen campaign.json is unverifiable"
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    for run in registry["runs"]:
        path = campaign_dir / "runs" / run["run_id"] / "journal.jsonl"
        if not path.exists():
            continue
        for record in read_journal(path):
            recorded = record["details"].get("campaign_sha256")
            if recorded is not None and recorded != current:
                return (f"run {run['run_id']} journaled campaign.json sha256 {recorded} at {record['state']}, but "
                        f"campaign.json is now {current}: it changed after the freeze")
    return None


# ---------------------------------------------------------------- environment and checkout

def checkout_source(checkout=CHECKOUT) -> dict:
    """{git_commit, dirty} of the checkout: HEAD and whether tracked files differ from it."""
    git = shutil.which("git")
    require(git is not None, "git is not available to read the checkout commit")
    env = {"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~")}

    def run(*args):
        done = subprocess.run([git, *args], cwd=checkout, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=60, check=False)
        require(done.returncode == 0, f"git {' '.join(args)} failed: {done.stderr.strip()[-200:]}")
        return done.stdout
    return {"git_commit": run("rev-parse", "HEAD").strip(),
            "dirty": bool(run("status", "--porcelain", "--untracked-files=no").strip())}


def lab_root(checkout=CHECKOUT) -> str:
    """Outermost ancestor of the checkout holding .git, CLAUDE.md or AGENTS.md (the lab tree). Never the subject
    markers' .claude: the user's home holds ~/.claude and must not become the lab root."""
    checkout = Path(os.path.realpath(checkout))
    found = checkout
    for ancestor in (checkout, *checkout.parents):
        if any(os.path.lexists(ancestor / marker) for marker in isolation.ANCESTOR_MARKERS):
            found = ancestor
    require(str(found) not in ("/", os.path.realpath(os.path.expanduser("~"))),
            f"lab root {found} would forbid the whole home directory")
    return str(found)


def packet_dirs(lab=None, environ=None) -> list:
    """Every location the research packet is forbidden at: research-planning/<PACKET_NAME> beside the
    checkout (PACKET_DIR) and in the lab root, plus the absolute path PACKET_ENV names in the coordinator's
    environment, if set. Resolved; a relative PACKET_ENV fails closed (never silently ignored)."""
    lab = lab_root() if lab is None else lab
    dirs = {PACKET_DIR, os.path.join(lab, "research-planning", PACKET_NAME)}
    extra = (os.environ if environ is None else environ).get(PACKET_ENV)
    if extra:
        require(os.path.isabs(extra) and "\0" not in extra, f"{PACKET_ENV}: absolute path required, got {extra!r}")
        dirs.add(extra)
    return sorted(os.path.realpath(d) for d in dirs)


def forbidden_roots(store, extra=()) -> list:
    """Store, lab tree, checkout and packet: no subject root or sandbox root may overlap one."""
    lab = lab_root()
    roots = {os.path.realpath(store), lab, os.path.realpath(CHECKOUT), *packet_dirs(lab)}
    return sorted(roots | {os.path.realpath(r) for r in extra})


def check_subject_visible_root(path, forbidden, label) -> Path:
    """A root a subject can see (the subjects root, a real host's host-state root): absolute, outside and not
    containing any forbidden root, no ancestor holding an instruction or host-settings marker
    (isolation.SUBJECT_ANCESTOR_MARKERS) and no arm word in its realpath (smoke spec WI-6). Returns the realpath."""
    path = Path(path)
    require(path.is_absolute(), f"{label}: absolute path required, got {path}")
    real = os.path.realpath(path)
    for root in forbidden:
        require(not (_within(real, root) or _within(root, real)), f"{label} {real} overlaps forbidden root {root}")
    for ancestor in (Path(real), *Path(real).parents):
        for marker in isolation.SUBJECT_ANCESTOR_MARKERS:
            require(not os.path.lexists(ancestor / marker),
                    f"{label}: {ancestor} holds {marker} (hosts load parent-directory instructions)")
    terms = treatment.arm_identifying_terms(real)
    require(not terms, f"{label}: the path names {terms}; subject-visible paths may not identify an arm")
    return Path(real)


def check_subjects_root(subjects_root, forbidden) -> Path:
    """Absolute, outside every forbidden root, no instruction-bearing ancestor, no arm word in the path."""
    return check_subject_visible_root(subjects_root, forbidden, "subjects_root")


def host_root_problem(path):
    """None when a real host's root (subjects or host state) is a real directory owned by this user with mode
    0700 (lstat: never a symlink), else the problem (smoke spec R17)."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        return f"{path}: cannot be inspected ({exc.strerror})"
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return f"{path}: not a real directory (a symlink or another kind of file)"
    if info.st_uid != os.getuid():
        return f"{path}: owned by uid {info.st_uid}, not this user"
    if stat.S_IMODE(info.st_mode) != HOST_ROOT_MODE:
        return f"{path}: mode {stat.S_IMODE(info.st_mode):04o}, not {HOST_ROOT_MODE:04o}"
    return None


def prepare_host_root(path, label) -> bool:
    """Create a real host's root exclusively with mode 0700 (its parent must exist), or verify an existing one
    (host_root_problem). Returns True when this call created it (the builder removes it again on failure)."""
    try:
        os.mkdir(path, HOST_ROOT_MODE)
    except FileExistsError:
        problem = host_root_problem(path)
        require(problem is None, f"{label}: {problem}")
        return False
    except OSError as exc:
        raise ContractError(f"{label}: cannot create {path} ({exc.strerror}); its parent must exist") from None
    os.chmod(path, HOST_ROOT_MODE)   # the umask never widens it, but make the mode exact
    return True


def subject_interpreter() -> tuple:
    """(python, prefix): the resolved base interpreter (a venv inside the repository is unreadable
    under the profile) and its resolved prefix, which becomes a sandbox read root."""
    python = os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)
    prefix = os.path.realpath(sys.base_prefix)
    require(python.startswith(prefix + os.sep), f"subject interpreter {python} lies outside its prefix {prefix}")
    require(not any(c.isspace() for c in python), "subject interpreter path may not contain whitespace (shebang)")
    return python, prefix


def launch_policy(*, workspace, subject_prefix, forbidden, port, extra_ports=(), host_access=None) \
        -> isolation.SandboxPolicy:
    """The subject's sandbox policy: read the workspace and the subject interpreter prefix, write its
    output/, tmp/ and home/, reach only the broker port, and deny every forbidden root. Built at
    build time (placeholder workspace and port), at every campaign load and at every launch, in
    every sandbox mode, so a misconfiguration (an interpreter prefix inside a forbidden root, say)
    fails the build instead of burning assignments as not_started.

    A real host adds exactly its ``host_access`` (``host_access(host_launch, host_state_dir)``): the pinned
    binary (one read literal, or the copied ``.app`` as one read root), write roots for its per-run config/ and
    tmp/, the deny roots (the credential directory, ~/Library/Keychains, ~/.claude.json) and the removal of the
    keychain mach services; ``extra_ports`` adds its proxy port. Nothing else: no /private/tmp, ~/Library or
    ~/.local/share/claude, no new mach service, no pty or semaphore rule. Without ``host_access`` the policy is
    exactly the fake host's (same profile bytes)."""
    workspace = Path(workspace)
    access = host_access or {}
    try:
        return isolation.SandboxPolicy(
            read_roots=[workspace, subject_prefix, *access.get("read_roots", ())],
            write_roots=[workspace / "output", workspace / "tmp", workspace / "home", *access.get("write_roots", ())],
            read_literals=list(access.get("read_literals", ())), network="localhost",
            localhost_ports=[port, *extra_ports], deny_roots=list(access.get("deny_roots", ())),
            forbidden_roots=forbidden, mach_services_removed=list(access.get("mach_services_removed", ())))
    except ContractError as exc:
        raise ContractError(f"launch profile: {exc}") from None


def host_access(host_launch, host_state_dir) -> dict:
    """What a real host's launch policy adds (launch_policy): {read_literals, read_roots, write_roots, deny_roots,
    mach_services_removed}; the write roots are the run's host-state config/ and tmp/ (never the state root)."""
    state = Path(host_state_dir)
    return {"read_literals": list(host_launch["binary_access"]["read_literals"]),
            "read_roots": list(host_launch["binary_access"]["read_roots"]),
            "write_roots": [state / name for name in HOST_STATE_SUBDIRS],
            "deny_roots": list(host_launch["deny_roots"]),
            "mach_services_removed": list(host_launch["mach_services_removed"])}


HOST_STATE_SUBDIRS = ("config", "tmp")   # a real host's per-run CLAUDE_CONFIG_DIR and CLAUDE_CODE_TMPDIR


def stage_environment(checkout=CHECKOUT) -> dict:
    env = {**STAGE_ENV, "PYTHONPATH": str(Path(checkout) / "src")}
    require(set(env) <= STAGE_ENV_KEYS, "stage env outside the broker's allowlist")
    return env


def harness_manifest() -> list:
    """Sorted {path, sha256} of every benchmarks/governance/**/*.py: binds the coordinator, the
    evaluator, the adapters and the profile generator even while they are untracked (git status
    ignores untracked files, so source.dirty cannot)."""
    paths = sorted(p for p in GOVERNANCE.rglob("*.py") if "__pycache__" not in p.parts)
    for path in paths:
        require(path.is_file() and not path.is_symlink(), f"harness source {path} is not a regular file")
    return [{"path": p.relative_to(GOVERNANCE).as_posix(), "sha256": canonical.sha256_file(p)} for p in paths]


def materialized_client(subject_python) -> bytes:
    """bin/ravel-task as materialized: the client with its shebang pinned to the subject interpreter
    (identical in every arm; its sha256 is bound by the environment manifest)."""
    first, _, rest = CLIENT.read_bytes().partition(b"\n")
    require(first.startswith(b"#!"), "client: shebang line expected")
    return f"#!{subject_python} -I\n".encode() + rest


def environment_manifest(*, subject_python, stage_python, stage_env, sandbox, host_launch=None,
                         family_index_sha256=None) -> dict:
    """What the environment digest binds: both interpreters, the stage env, pyhf, platform, sandbox,
    the materialized client, the harness code, the real host's launch declaration (null for the fake
    host) and the sha256 of the frozen family index. Every field is re-derived at load."""
    probe = subprocess.run([stage_python, "-c", "import sys, pyhf; sys.stdout.write(pyhf.__version__)"], cwd="/",
                           env=stage_env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
                           check=False)
    require(probe.returncode == 0 and probe.stdout.strip(),
            f"stage interpreter cannot import pyhf: {probe.stderr.strip()[-300:]}")
    return {"schema_version": 1,
            "subject_interpreter": campaign_manifest.interpreter_record(subject_python),
            "stage_interpreter": campaign_manifest.interpreter_record(stage_python),
            "stage_env": dict(sorted(stage_env.items())), "pyhf_version": probe.stdout.strip(),
            "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                         "platform": platform.platform()},
            "sandbox": sandbox,
            "materialized_client_sha256": canonical.sha256_bytes(materialized_client(subject_python)),
            "harness_code": harness_manifest(), "host_launch": host_launch, "family_index_sha256": family_index_sha256}


def fake_host_version() -> str:
    return "fake_subject-sha256:" + canonical.sha256_file(fake_adapter.SUBJECT_SCRIPT)


def fake_host(subject_python, environment_sha256, sandbox) -> dict:
    """§4.2 host configuration of the synthetic fake host (no model, reasoning or sampling exist)."""
    return {"schema_version": 1, "adapter": "fake", "executable": subject_python,
            "executable_sha256": canonical.sha256_file(subject_python), "version": fake_host_version(),
            "model": None, "reasoning": None, "sampling": None,
            "context_policy": "fresh workspace, HOME and session per assignment", "memory_policy": "none",
            "subagent_policy": "none", "tool_allowlist": ["bin/ravel-task"], "network": "localhost",
            "sandbox": sandbox, "environment_manifest_sha256": environment_sha256, "cost_source": "none_synthetic",
            "unknown_fields": []}


# The task-bank registry decides guard and broker behaviour (the field registry, the dependency classes that choose the
# stale codes, key units, role acceptance, input formats and operations) and the operation vocabulary the contracts
# check, so it is part of the guard implementation, the broker and the operation schema (decision E-179).
REGISTRY_SOURCE = GOVERNANCE / "tasks" / "registry.py"
GUARD_SOURCES = (GOVERNANCE / "guard.py", REGISTRY_SOURCE)


def guard_implementation_sha256() -> str:
    """The guard implementation digest every arm manifest records: the canonical digest of the sorted
    [{path, sha256}] list of guard.py and the registry it reads (treatment.common_hashes' file-list rule)."""
    return canonical.digest(sorted(({"path": p.name, "sha256": canonical.sha256_file(p)} for p in GUARD_SOURCES),
                                   key=lambda entry: entry["path"]))


def common_sources(stage_python) -> dict:
    """Source files of the §4.3 common block (identical in every arm)."""
    g = GOVERNANCE
    return {"envelope": treatment.TREATMENTS_DIR / treatment.FROZEN_FILES["envelope"], "tool_guide": TOOL_GUIDE,
            "client": CLIENT, "broker": [g / "broker.py", g / "guard.py", REGISTRY_SOURCE],
            "stage_workers": [Path(stages.__file__)] + [stages.worker_path(s) for s in stages.WORKERS],
            "kernel_source": CHECKOUT / "src", "interpreter": stage_python,
            "operation_schema": [g / "contracts.py", REGISTRY_SOURCE] + [
                g / "schemas" / f"{n}.schema.json" for n in ("claim", "claim_v2", "submission", "decision_record")]}


def arm_manifests(stage_python) -> dict:
    common = treatment.common_hashes(common_sources(stage_python))
    arms = {arm: treatment.arm_manifest(arm, common=common, instructions_text=treatment.frozen_bytes("instructions"),
                                        guard_impl_sha256=guard_implementation_sha256()) for arm in contracts.ARMS}
    diff = treatment.treatment_diff(arms)
    require(diff["ok"], f"treatment diff failed: {diff['violations']}")
    return arms


def _budget(overrides, runs) -> dict:
    overrides = dict(overrides or {})
    unknown = sorted(set(overrides) - set(contracts.BUDGET_FIELDS))
    require(not unknown, f"budget: unknown fields {unknown}")
    budget = {name: overrides.get(name, value) for name, value in DEFAULT_BUDGET.items()}
    for cap, per_run in (("global_usd_cap", "usd_per_run"), ("global_seconds_cap", "seconds_per_run")):
        value = budget[per_run]   # runs x per-run cap, exactly (0.3 x 3 is 0.9, never 0.8999999999999999)
        default = runs * value if type(value) is int else float(exact(value) * runs)
        budget[cap] = overrides.get(cap, default)
    return budget


# ---------------------------------------------------------------- build

def build_synthetic_campaign(store, *, campaign_id, created_utc, seeds, schedule_seed, subjects_root, source=None,
                             budget=None, sandbox="seatbelt", extra_forbidden_roots=(), tasks=None) -> Path:
    """Freeze a synthetic fake-host campaign at <store>/synthetic/<campaign_id>/; return its directory.

    ``source`` defaults to the checkout's git HEAD and tracked-file dirtiness; an explicit
    {git_commit, dirty} must equal it when git can read the checkout. ``budget`` overrides
    DEFAULT_BUDGET fields (global caps default to runs x per-run caps). ``sandbox`` is
    ``seatbelt`` or ``none_test_only`` (recorded in the host config and every run.json). ``tasks``
    (default: every family task) selects the v1 tasks, kept in family-index order; the family stays
    whole. The campaign is assembled under a temporary directory in the namespace and renamed into
    place only after it loads (profile, separation and code checks included); on any failure nothing
    remains and the campaign id stays free.
    """
    return _build_campaign(store, campaign_id=campaign_id, created_utc=created_utc, seeds=seeds,
                           schedule_seed=schedule_seed, subjects_root=subjects_root, tasks=tasks, sandbox=sandbox,
                           budget=budget, make_host=fake_host, authorization=dict(SYNTHETIC_AUTHORIZATION),
                           approval_record=None, host_launch=None, source=source,
                           extra_forbidden_roots=extra_forbidden_roots)


def _select_tasks(index, tasks) -> list:
    """The requested task ids in bank-index order (every task of a runnable family when ``tasks`` is None: since WP12
    plan steps 8-9 the whole 12-task bank). A task of a family outside the bank's ``runnable_families`` (one with no
    evaluator profile or fake behaviours, registry.RUNNABLE_FAMILIES) is never scheduled; the frozen bank still
    holds it."""
    runnable = [t["task_id"] for t in index["tasks"] if t["family"] in index["runnable_families"]]
    if tasks is None:
        return runnable
    require(isinstance(tasks, (list, tuple)) and tasks and all(isinstance(t, str) for t in tasks),
            "tasks: a nonempty list of task ids")
    require(len(set(tasks)) == len(tasks), f"tasks: duplicate task ids in {list(tasks)}")
    ids = [t["task_id"] for t in index["tasks"]]
    unknown = sorted(set(tasks) - set(ids))
    require(not unknown, f"tasks: {unknown} are not tasks of the family index {ids}")
    held = sorted(set(tasks) - set(runnable))
    require(not held, f"tasks: {held} belong to families no campaign may run yet (runnable: "
                      f"{index['runnable_families']}; a family needs its evaluator profile and fake behaviours)")
    return [t for t in ids if t in set(tasks)]


def _pinned_binary_problems(pin, host_launch, forbidden) -> list:
    """The pinned binary as a real host's campaign must hold it (smoke spec WI-1 step 4, R2, R17): its resolved
    path, outside every forbidden root and naming no arm; a regular file (never a symlink) with the pinned sha256;
    read-only (no write bit) in a directory owned by this user without write bits (a harness-owned 0555 copy),
    or the inner binary of a copied, read-only .app bundle whose parent directory has no write bits either (so the
    bundle cannot be swapped by a rename: only the inner binary's sha256 is rechecked at each launch); the
    host_launch binary access naming exactly it."""
    executable, problems = pin.executable, []
    real = os.path.realpath(executable)
    if real != executable:
        return [f"pin: {executable} resolves to {real}; pin the resolved path of the harness-owned copy"]
    for root in forbidden:
        if _within(real, root) or _within(root, real):
            problems.append(f"pin: {real} overlaps forbidden root {root}")
    terms = treatment.arm_identifying_terms(real)
    if terms:
        problems.append(f"pin: the path names {terms}; a subject-visible path may not identify an arm")
    try:
        info = os.lstat(real)
    except OSError as exc:
        return problems + [f"pin: {real} cannot be inspected ({exc.strerror})"]
    if not stat.S_ISREG(info.st_mode):
        return problems + [f"pin: {real} is not a regular file"]
    if info.st_mode & 0o222:
        problems.append(f"pin: {real} is writable (mode {stat.S_IMODE(info.st_mode):04o}); make the copy read-only")
    access = host_launch["binary_access"]
    app = next(iter(access["read_roots"]), None)
    owned = [Path(real).parent] if app is None else [Path(app).parent, Path(app), Path(app) / "Contents",
                                                     Path(real).parent]
    for directory in owned:
        try:
            state = os.lstat(directory)
        except OSError as exc:
            problems.append(f"pin: {directory} cannot be inspected ({exc.strerror})")
            continue
        if stat.S_ISLNK(state.st_mode) or state.st_uid != os.getuid() or state.st_mode & 0o222:
            problems.append(f"pin: {directory} must be a real directory owned by this user without write bits "
                            f"(mode {stat.S_IMODE(state.st_mode):04o}): a harness-owned read-only copy")
    if app is None and access["read_literals"] != [real]:
        problems.append(f"host_launch.binary_access.read_literals {access['read_literals']} is not the pin {real}")
    if app is not None and not _within(real, app):
        problems.append(f"host_launch.binary_access.read_roots {access['read_roots']} does not hold the pin {real}")
    if not problems and canonical.sha256_file(real) != pin.executable_sha256:
        problems.append(f"pin: {real} does not have the pinned sha256 {pin.executable_sha256}")
    return problems


def _verify_pin(pin, host_launch) -> dict:
    """verify_host of the pin (sha256 and ``--version``, run with the adapter's isolation environment in a
    throwaway directory), then its code signature (hardened runtime and no get-task-allow: the profile's
    same-sandbox task-port allowance is safe only with a binary the kernel protects, E-90), then the byte check
    that the binary knows the model id (R2, necessary only)."""
    from . import live
    from .adapters import base as adapter_base, claude_cli
    pins = host_launch["claude"]["env_pins"]
    identity = adapter_base.verify_host(pin.executable, expected_version=pin.version,
                                        expected_sha256=pin.executable_sha256,
                                        version_pattern=claude_cli.VERSION_PATTERN,
                                        env_for=lambda tmp: {"PATH": "/usr/bin:/bin", "HOME": tmp,
                                                             "CLAUDE_CONFIG_DIR": tmp, **claude_cli.ISOLATION_ENV,
                                                             **pins})
    signature = live.code_signature(pin.executable)
    require(not signature["problems"], "pin: its code signature does not protect the host process: "
                                       + "; ".join(signature["problems"]))
    require(live.model_in_binary(pin.executable, pin.model),
            f"pin: the model id {pin.model!r} does not appear in the pinned binary; this pin cannot serve that model "
            "(smoke spec §1.1: choose the pin and the model together)")
    return identity


def _build_campaign(store, *, campaign_id, created_utc, seeds, schedule_seed, subjects_root, tasks, sandbox, budget,
                    make_host, authorization, approval_record, host_launch, source, extra_forbidden_roots,
                    pin=None, approval=None) -> Path:
    """The one campaign builder (smoke spec WI-1). ``make_host(subject_python, environment_sha256, sandbox)``
    returns the §4.2 host configuration. A real host (``host_launch``, ``pin`` and ``approval`` given) adds, in
    order: the credential directory to the forbidden roots; both subject-visible roots checked and created 0700
    exclusively or verified (R17); the pinned binary checked, verified and searched for the model id (R2); the
    real-host profile built with placeholder ports; the approval checked against the finished spec, caps and
    host (live.approval_problems); the host binding written once from the runtime adapter (R20); the self-check;
    the ledger claim, whose line is removed again if the rename fails (R9). Every failure leaves nothing behind:
    no campaign directory, no ledger line and no root this build created."""
    from . import live
    require(sandbox in contracts.SANDBOXES, f"sandbox: expected one of {list(contracts.SANDBOXES)}")
    require(isinstance(campaign_id, str) and contracts.SAFE_ID.fullmatch(campaign_id) is not None,
            f"campaign_id: must match {contracts.SAFE_ID.pattern}")
    store = Path(store)
    require(store.is_absolute(), f"store: absolute path required, got {store}")
    target = store / "synthetic" / campaign_id
    require(not os.path.lexists(target), f"refusing to overwrite existing campaign directory {target}")
    real = host_launch is not None
    require(real == (pin is not None) == (approval is not None),
            "a real host's campaign needs its host_launch, its pin and its approval together")
    require(not real or sandbox == "seatbelt", "a real host runs only under the Seatbelt sandbox")
    state_root = None
    if real:
        contracts.validate_host_launch(host_launch)
        credential_dir = os.path.dirname(host_launch["credential"]["file"])
        forbidden = forbidden_roots(store, [*extra_forbidden_roots, credential_dir])
    else:
        forbidden = forbidden_roots(store, extra_forbidden_roots)
    subjects = check_subjects_root(subjects_root, forbidden)
    if real:
        state_root = check_subject_visible_root(host_launch["host_state_root"], forbidden, "host_state_root")
        require(not (_within(str(state_root), str(subjects)) or _within(str(subjects), str(state_root))),
                f"host_state_root {state_root} and subjects_root {subjects} must be disjoint")
        problems = _pinned_binary_problems(pin, host_launch, forbidden)
        require(not problems, "; ".join(problems))
        _verify_pin(pin, host_launch)
    subject_python, subject_prefix = subject_interpreter()
    # Fail fast, before any family build or interpreter probe, and in every sandbox mode.
    isolation.seatbelt_profile(launch_policy(
        workspace=subjects / PLACEHOLDER_HANDLE, subject_prefix=subject_prefix, forbidden=forbidden,
        port=PLACEHOLDER_PORTS[0], extra_ports=PLACEHOLDER_PORTS[1:] if real else (),
        host_access=host_access(host_launch, state_root / PLACEHOLDER_HANDLE) if real else None))
    stage_python = os.path.abspath(sys.executable)
    stage_env = stage_environment()
    source = _source(source)
    arms = arm_manifests(stage_python)
    namespace = store / "synthetic"
    namespace.mkdir(parents=True, exist_ok=True)
    created = []
    build = Path(tempfile.mkdtemp(prefix=f".{campaign_id}.build-", dir=namespace))
    try:
        if real:
            for path, label in ((subjects, "subjects_root"), (state_root, "host_state_root")):
                if prepare_host_root(path, label):
                    created.append(path)
        # the task bank: every registered family under one canary, each definition recording this campaign's
        # per-run task budget and the operations the broker serves (checked again below)
        require(registry.CAMPAIGN_OPERATIONS == tuple(sorted(BROKER_OPERATIONS)),
                f"registry.CAMPAIGN_OPERATIONS {list(registry.CAMPAIGN_OPERATIONS)} are not the broker's operations "
                f"{sorted(BROKER_OPERATIONS)}")
        per_run = _budget(budget, 1)
        task_budget = {name: per_run[name] for name in registry.TASK_BUDGET_FIELDS}
        index = registry.build_bank(build / "family", budget=task_budget)
        definitions, v1_tasks = {}, {}   # every bank task, keyed by id, in bank index order
        require(len(index["tasks"]) == len(index["v1_tasks"]), "family index: tasks and v1_tasks differ in length")
        for entry, v1_task in zip(index["tasks"], index["v1_tasks"]):
            data = (build / "family" / entry["definition_path"]).read_bytes()
            require(canonical.sha256_bytes(data) == entry["definition_sha256"], f"{entry['task_id']}: definition hash")
            definition = canonical.strict_loads(data.decode())
            require(definition["schema_version"] == 2
                    and canonical.canonical_bytes(definition["budget"]) == canonical.canonical_bytes(task_budget)
                    and definition["allowed_operations"] == sorted(BROKER_OPERATIONS),
                    f"{entry['task_id']}: a bank definition records this campaign's task budget and the broker's "
                    "operations")
            task = {"id": definition["task_id"], "expected": definition["expected"],
                    "prompt_sha256": definition["prompt_sha256"], "oracle_sha256": definition["oracle_sha256"],
                    "fidelity_tolerance": definition["fidelity"]["tolerance"]}
            require(canonical.canonical_bytes(task) == canonical.canonical_bytes(v1_task),
                    f"{entry['task_id']}: family index v1 task differs from its definition")
            definitions[task["id"]], v1_tasks[task["id"]] = definition, task
        selected = _select_tasks(index, tasks)
        environment = environment_manifest(subject_python=subject_python, stage_python=stage_python,
                                           stage_env=stage_env, sandbox=sandbox, host_launch=host_launch,
                                           family_index_sha256=canonical.sha256_file(build / "family" / "index.json"))
        host = make_host(subject_python, canonical.digest(environment), sandbox)
        limits = _budget(budget, len(selected) * len(seeds) * len(contracts.ARMS))
        if real:
            model, runtime = campaign_manifest.spec_identity("synthetic", host)
        else:
            model = SYNTHETIC_MODEL
            runtime = f"{campaign_manifest.SYNTHETIC_LABEL} {campaign_manifest.runtime_label(host)}"
        spec = {"experiment_id": campaign_id, "protocol_sha256": canonical.sha256_file(PROTOCOL),
                "code_commit": source["git_commit"], "environment_sha256": host["environment_manifest_sha256"],
                "model": model, "runtime": runtime, "schedule_seed": schedule_seed, "seeds": list(seeds),
                "tasks": [v1_tasks[t] for t in selected],
                "budget": {"usd_per_run": limits["usd_per_run"], "seconds_per_run": limits["seconds_per_run"]}}
        if real:
            problems = live.approval_problems(approval, spec=spec, host=pin.fields(), budget=limits,
                                              arms=list(contracts.ARMS), ledger=live.read_approval_ledger(),
                                              host_launch=host_launch)
            require(not problems, "the approval does not authorize this campaign: " + "; ".join(problems))
        staged = campaign_manifest.write_campaign(   # <build>/synthetic/<campaign_id>: verify checks the names
            build, kind="synthetic", campaign_id=campaign_id, spec=spec, host=host, arms=arms,
            tasks=[definitions[t] for t in selected], budget=limits, authorization=authorization,
            created_utc=created_utc, source=source, interpreter=campaign_manifest.interpreter_record(stage_python),
            subjects_root=subjects_root, approval_record=approval_record)
        coordinator = staged / COORDINATOR
        coordinator.mkdir(mode=0o700)
        os.rename(build / "family", coordinator / "family")
        canonical.write_once(coordinator / "campaign_secret", secrets.token_hex(32).encode() + b"\n", mode=0o400)
        canonical.write_once(coordinator / "canary.txt", f"RAVEL-EVAL-CANARY-{secrets.token_hex(16)}\n".encode(),
                             mode=0o400)
        canonical.write_once(coordinator / "environment.json", _pretty(environment))
        config = {"schema_version": 1, "checkout": str(CHECKOUT), "stage_python": stage_python,
                  "stage_env": stage_env, "subject_python": subject_python, "subject_prefix": subject_prefix,
                  "sandbox": sandbox, "forbidden_roots": forbidden, "subjects_root": str(subjects),
                  "host_launch": host_launch}
        canonical.write_once(coordinator / "config.json", _pretty(config))
        canonical.write_once(coordinator / CAMPAIGN_DIGEST,
                             (canonical.sha256_file(staged / campaign_manifest.MANIFEST) + "\n").encode(), mode=0o400)
        if real:   # R20: the binding is the runtime adapter's, written once here; every launch only compares
            adapter = live.claude_adapter(host, host_launch, limits, state_root / PLACEHOLDER_HANDLE, launcher=None)
            binding, problems = host_binding(adapter, host, limits, "synthetic")
            require(not problems, "host binding: " + "; ".join(problems))
            canonical.write_once(coordinator / HOST_BINDING, _pretty(binding))
        _Campaign(staged, check_environment=False)   # fail closed now, not at the first launch
        require(not os.path.lexists(target), f"refusing to overwrite existing campaign directory {target}")
        if real:
            with live.claim_approval(approval_sha256=live.approval_digest(approval), campaign_id=campaign_id,
                                     created_utc=created_utc):
                require(not os.path.lexists(target), f"refusing to overwrite existing campaign directory {target}")
                os.rename(staged, target)
        else:
            os.rename(staged, target)
    except BaseException:
        for path in reversed(created):   # only a root this build created, and only while it is still empty
            try:
                os.rmdir(path)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(build, ignore_errors=True)
    return target


def _source(source) -> dict:
    try:
        observed = checkout_source()
    except (ContractError, OSError, subprocess.SubprocessError) as exc:
        require(source is not None, f"source: git cannot read the checkout ({exc}); pass source explicitly")
        return dict(source)
    require(source is None or source == observed, f"source {source} differs from the checkout {observed}")
    return observed


# ---------------------------------------------------------------- campaign context

class _Recorder:
    """The launcher handed to the adapter: checks the final call (``check(argv, env)``, problems or
    []: a refused call raises LaunchRefused before anything is written or started), writes the call
    (argv, environment NAMES, cwd, timeout) before delegating to isolation.launch, and journals
    ``process_started`` ({pid, pgid, marker, started_at, leader_start}) as soon as the subject
    starts, so an interrupted launch is on record and its census can find exactly its processes. No
    launch call on record and no process start on record together prove that nothing was started."""

    def __init__(self, path, journal, check=None, *, credential=None, admission=None, proxy=None,
                 remove_unattributed_ipc=True, fingerprint=None):
        """``credential`` (a real host: ``(env_name, file)``) is the one credential exception (smoke spec WI-5):
        after every other check the file is read (credentials.read_credential) and its value goes only into the
        environment handed to isolation.launch; ``admission(final_env, allowed_secret_names)`` must then pass
        (isolation.env_admission: codes only for the declared name). ``launch_call.json`` records names only. The
        value is kept in memory for the post-run sweep until ``release()``. ``proxy``: the launch's allowlist proxy,
        whose owner becomes the started leader and is cleared as soon as the launch returns (a later client is never
        the owner, whoever reuses the pid). ``remove_unattributed_ipc`` is passed to isolation.launch (False for a
        real host: M7). ``fingerprint(token bytes)``: the keyed fingerprint launch_call.json records (never a plain
        hash), so a resume can tell whether the file it re-reads still holds the token this launch used."""
        self.path, self.journal, self.check = Path(path), Path(journal), check
        self.credential, self.admission, self.proxy = credential, admission, proxy
        self.fingerprint = fingerprint
        self.remove_unattributed_ipc = remove_unattributed_ipc
        self._needle = None
        self.credential_failed = False

    @property
    def needle(self):
        """The credential bytes this launch used, for the post-run sweep only (None before a launch)."""
        return self._needle

    def release(self):
        self._needle = None

    def __call__(self, argv, *, cwd, env, profile, timeout_s, stdout_path, stderr_path, stdin_path=None):
        problems = self.check(list(argv), dict(env)) if self.check is not None else []
        if problems:
            raise LaunchRefused("the coordinator refused the launch call: " + "; ".join(problems))
        final_env, credential_names = dict(env), []
        if self.credential is not None:
            name, file = self.credential
            if name in env:
                raise LaunchRefused(f"the adapter set the credential variable {name} itself; only the coordinator "
                                    "injects it")
            try:
                value = credentials.read_credential(file)
            except credentials.CredentialError as exc:   # generic: never content, length or prefix
                self.credential_failed = True
                raise LaunchRefused(f"the host credential is unavailable: {exc}", code="credential_unavailable") \
                    from None
            final_env[name] = value
            credential_names = [name]
            if self.admission is not None:
                checked = self.admission(final_env, frozenset(credential_names))
                if not checked["ok"]:
                    codes = sorted({f"{v['code']} ({v['where']})" for v in checked["violations"]})
                    raise LaunchRefused("the launch environment failed admission: " + ", ".join(codes))
            self._needle = value.encode("ascii")
            del value
        call = {"argv": list(argv), "env_names": sorted(final_env), "cwd": str(cwd), "timeout_s": timeout_s,
                "profile_sha256": profile_sha256(profile)}
        if self.credential is not None:
            call["credential_env_names"] = credential_names
            if self.fingerprint is not None:
                call["credential_fingerprint"] = self.fingerprint(self._needle)
        canonical.write_once(self.path, _pretty(call))

        def on_start(started):
            if self.proxy is not None:
                self.proxy.owner_pid = started["pid"]
            _record(self.journal, "process_started", **started)
        try:
            return isolation.launch(argv, cwd=cwd, env=final_env, profile=profile, timeout_s=timeout_s,
                                    stdout_path=stdout_path, stderr_path=stderr_path, stdin_path=stdin_path,
                                    on_start=on_start, remove_unattributed_ipc=self.remove_unattributed_ipc)
        finally:
            if self.proxy is not None:
                self.proxy.owner_pid = None


def _value_canaries(oracle) -> list:
    """Each oracle limit and sigma_vis value as JSON prints it (distinctive decimals only)."""
    values = []
    for side in ("current", "prior"):
        for name in VALUE_FIELDS:
            value = oracle[side][name]
            values += value if isinstance(value, list) else [value]
    printed = [json.dumps(v) for v in values if canonical.finite_number(v) and type(v) is float]
    return sorted({p for p in printed if "." in p and "e" not in p and len(p) >= 8})


def fake_adapter_factory(assignment):
    """Adapter factory for the synthetic fake host: the planned behavior, the pinned subject
    interpreter and the coordinator's recording launcher."""
    return fake_adapter.FakeAdapter(assignment["behavior"], assignment["launcher"], python=assignment["python"])


def adapter_factory_for(campaign):
    """The campaign host's adapter factory: the fake subject's, or live.claude_factory for the Claude CLI (the
    adapter the build-time binding was written from, R20). Another host has no factory here."""
    if campaign.host["adapter"] == "fake":
        return fake_adapter_factory
    require(campaign.host["adapter"] == "claude_cli", f"no adapter factory for a {campaign.host['adapter']} host")
    from . import live
    return live.claude_factory(campaign)


PLACEHOLDER_SESSION = "00000000-0000-0000-0000-000000000000"   # a real host's per-run session id in its binding
HOST_IDENTITY = (("executable", "executable"), ("expected_sha256", "executable_sha256"),
                 ("expected_version", "version"), ("model", "model"))


def host_binding(adapter, host, budget, kind) -> tuple:
    """(binding, problems) of a real (non-fake) host adapter against the frozen campaign (§4.2).

    Every assignment of a campaign must launch the same host identically, whatever its arm: the
    adapter's pinned executable, its sha256, version and model must equal the campaign host
    configuration (a null campaign value cannot be bound and is refused); its executor id is
    ``<adapter>/<version>/<model>``; its outer sandbox is the campaign's; it starts a fresh session
    (a resumed session would carry context across assignments); its synthetic label is the
    campaign's; and the claude_cli spend ceiling it enforces (``--max-budget-usd``) equals the
    campaign's ``usd_per_run``, the amount an unknown-cost run is charged, so unknown cost is never
    undercharged. The binding (adapter, executor id, argv with the per-run session or workspace
    replaced by a placeholder, the environment values the adapter adds apart from its per-run
    directory, ceiling) is what the coordinator compares across runs. codex_cli enforces no USD
    ceiling (its cost is tokens only, charged at the cap)."""
    name, problems = host["adapter"], []
    require(name in ("claude_cli", "codex_cli"), f"host_binding: a real host adapter required, got {name!r}")
    for attribute, key in HOST_IDENTITY:
        value = getattr(adapter, attribute, None)
        if host[key] is None:
            problems.append(f"host.{key} is unknown in the campaign, so the adapter's {attribute} cannot be bound")
        elif value != host[key]:
            problems.append(f"adapter {attribute} {value!r} differs from the campaign's host.{key} {host[key]!r}")
    executor = f"{name}/{host['version']}/{host['model']}"
    if getattr(adapter, "executor_id", None) != executor:
        problems.append(f"adapter executor_id {getattr(adapter, 'executor_id', None)!r} is not {executor!r}")
    if getattr(adapter, "sandbox", None) != host["sandbox"]:
        problems.append(f"adapter sandbox {getattr(adapter, 'sandbox', None)!r} differs from the campaign's "
                        f"{host['sandbox']!r}")
    if getattr(adapter, "resume_session_id", None) is not None:
        problems.append("the adapter resumes a host session; every assignment starts a fresh one")
    if getattr(adapter, "synthetic", None) is not (kind == "synthetic"):
        problems.append(f"adapter synthetic label {getattr(adapter, 'synthetic', None)!r} differs from the "
                        f"{kind} campaign")
    ceiling, extra_env = None, {}
    if name == "claude_cli":   # smoke spec WI-2: a per-run CLAUDE_CODE_TMPDIR (the CLI's default is /tmp) and a
        for attribute, what in (("tmp_dir", "per-run temp directory"), ("effort", "pinned --effort")):
            if getattr(adapter, attribute, None) is None:   # pinned effort (R14) are part of every live launch
                problems.append(f"the claude_cli adapter has no {what} ({attribute} is None)")
    try:
        if name == "claude_cli":
            ceiling = getattr(adapter, "max_budget_usd", None)
            if not (canonical.finite_number(ceiling) and exact(ceiling) == exact(budget["usd_per_run"])):
                problems.append(f"the host-enforced spend ceiling max_budget_usd {ceiling!r} differs from the "
                                f"campaign's usd_per_run {budget['usd_per_run']!r}")
            argv = adapter.build_argv(session_id=PLACEHOLDER_SESSION)
            extra_env = dict(adapter.isolation_env())
        else:
            argv = adapter.build_argv(SUBJECT_ROOT)
    except (AttributeError, TypeError, ContractError) as exc:
        problems.append(f"the adapter's argv cannot be built for its binding: {type(exc).__name__}: {exc}")
        argv = None
    binding = {"schema_version": 1, "adapter": name, "executor_id": getattr(adapter, "executor_id", None),
               "argv": argv, "extra_env": extra_env, "usd_ceiling": ceiling}
    try:
        canonical.canonical_bytes(binding)
    except (TypeError, ValueError) as exc:
        problems.append(f"the host binding is not canonical JSON: {exc}")
    return binding, problems


def _subject_files(campaign, run) -> dict:
    """The §6 subject workspace as fresh bytes (no links, no .git, no evaluator material)."""
    files = {"request.md": campaign.requests[run["task_id"]], "tools.md": campaign.tool_guide,
             "bin/ravel-task": campaign.client,
             "output/": b"", "tmp/": b"", "home/": b""}
    for name, data in campaign.inputs(run["task_id"], "current").items():
        files[f"inputs/{name}"] = data
    return files


class _Campaign:
    """A verified campaign and its coordinator-private context."""

    def __init__(self, campaign_dir, *, check_environment=True):
        self.dir = Path(campaign_dir).resolve()
        verified = campaign_manifest.verify(self.dir)
        require(verified["ok"], f"campaign verification failed: {verified['errors']}")
        manifest_bytes = (self.dir / campaign_manifest.MANIFEST).read_bytes()
        self.campaign_sha256 = canonical.sha256_bytes(manifest_bytes)
        problem = campaign_digest_problem(self.dir, self.campaign_sha256)
        require(problem is None, f"campaign integrity: {problem}")
        self.manifest = canonical.strict_loads(manifest_bytes.decode("utf-8"))
        self.registry = canonical.strict_load(self.dir / campaign_manifest.REGISTRY)
        self.spec, self.host, self.budget = self.registry["spec"], self.manifest["host"], self.manifest["budget"]
        require(set(self.budget) == set(contracts.BUDGET_FIELDS),
                "campaign.budget has no max_stage_executions: a campaign frozen before WP12 is verified and audited by "
                "this checkout but run only from its own (E-24, E-151)")
        coordinator = self.dir / COORDINATOR
        self.config = canonical.strict_load(coordinator / "config.json")
        require(set(self.config) == set(CONFIG_FIELDS), f"coordinator config: fields must be {sorted(CONFIG_FIELDS)}")
        require(self.config["checkout"] == str(CHECKOUT),
                f"the campaign was frozen in {self.config['checkout']}; run it from that checkout, not {CHECKOUT}")
        require(self.config["sandbox"] == self.host["sandbox"], "coordinator config: sandbox differs from the host")
        require(self.host["adapter"] == "fake" or os.environ.get("RAVEL_EVAL_LIVE") == "1",
                "a non-fake host runs only with RAVEL_EVAL_LIVE=1 and an approved campaign")
        require(self.host["sandbox"] == "seatbelt" or self.manifest["kind"] == "synthetic",
                "sandbox none_test_only is for synthetic campaigns only")
        require(self.host["adapter"] == "fake" or self.host["sandbox"] == "seatbelt",
                "a real host runs only under the Seatbelt sandbox (none_test_only is for the fake host)")
        self.host_launch = self.config["host_launch"]
        self.real = self.host["adapter"] != "fake"
        require((self.host_launch is not None) == self.real,
                "coordinator config: host_launch is required for, and only for, a real host")
        if self.real:
            contracts.validate_host_launch(self.host_launch, "coordinator config host_launch")
        if self.host["sandbox"] == "seatbelt":
            require(isolation.sandbox_available() and isolation.census_available(),
                    "the campaign requires the Seatbelt sandbox and its census, unavailable here")
        self.environment = canonical.strict_load(coordinator / "environment.json")
        require(canonical.digest(self.environment) == self.host["environment_manifest_sha256"]
                == self.spec["environment_sha256"], "coordinator/environment.json differs from the frozen digest")
        self.family_dir = coordinator / "family"
        index_sha256 = canonical.sha256_file(self.family_dir / "index.json")
        require(canonical.canonical_bytes(self.environment.get("host_launch")) == canonical.canonical_bytes(
            self.host_launch) and self.environment.get("family_index_sha256") == index_sha256,
                "coordinator/environment.json does not bind this campaign's host_launch and family index (rebuild the "
                "campaign with the current builder)")
        self._check_code(check_environment)
        self.secret = (coordinator / "campaign_secret").read_bytes()
        self.canary = (coordinator / "canary.txt").read_text().strip()
        require(len(self.secret) >= 32 and self.canary.startswith("RAVEL-EVAL-CANARY-"), "coordinator secret/canary")
        self.index = canonical.strict_load(self.family_dir / "index.json")
        self.tasks = {t["task_id"]: t for t in self.index["tasks"]}
        spec_ids = [t["id"] for t in self.spec["tasks"]]
        require(spec_ids and [t for t in self.tasks if t in set(spec_ids)] == spec_ids,
                f"the spec's tasks {spec_ids} are not a subset of the family index {list(self.tasks)} in its order")
        self.requests = {}   # task id -> its family's request.md, as the bank index lists and hashes it
        for task_id, task in self.tasks.items():
            data = (self.family_dir / task["request_path"]).read_bytes()
            require(canonical.sha256_bytes(data) == task["prompt_sha256"], f"{task_id}: its request.md changed")
            self.requests[task_id] = data
        require(all(t["prompt_sha256"] == canonical.sha256_bytes(self.requests[t["id"]]) for t in self.spec["tasks"]),
                "request.md differs from the prompt_sha256 the v1 spec freezes for its tasks")
        self.tool_guide = TOOL_GUIDE.read_bytes()
        self.client = materialized_client(self.config["subject_python"])
        require(canonical.sha256_bytes(self.client) == self.environment["materialized_client_sha256"],
                "the materialized client differs from the one the environment manifest binds")
        self.forbidden_roots = sorted(set(self.config["forbidden_roots"])
                                      | set(forbidden_roots(self.dir.parent.parent)))
        self.subjects_root = check_subjects_root(self.manifest["storage"]["subjects_root"], self.forbidden_roots)
        require(str(self.subjects_root) == self.config["subjects_root"], "subjects_root differs from the config")
        self.host_state_root = None
        if self.real:
            credential_dir = os.path.realpath(os.path.dirname(self.host_launch["credential"]["file"]))
            require(credential_dir in self.forbidden_roots,
                    "the credential directory is not among the campaign's forbidden roots")
            self.host_state_root = check_subject_visible_root(self.host_launch["host_state_root"],
                                                              self.forbidden_roots, "host_state_root")
            require(not (_within(str(self.host_state_root), str(self.subjects_root))
                         or _within(str(self.subjects_root), str(self.host_state_root))),
                    "host_state_root and subjects_root must be disjoint")
        # the launch policy must be buildable (placeholder workspace, ports and host-state directory)
        self._profile(self.subjects_root / PLACEHOLDER_HANDLE, list(PLACEHOLDER_PORTS if self.real else [1]),
                      host_state_dir=self.host_state_dir_for(None))
        self.forbidden_sha256 = {canonical.sha256_file(self.family_dir / p)
                                 for p in self.index["path_roles"]["evaluator_private"]}
        self.forbidden_sha256 |= {canonical.sha256_file(coordinator / "canary.txt"),
                                  canonical.sha256_file(coordinator / "campaign_secret")}
        self.family_canary = self.index.get("canary")
        require(isinstance(self.family_canary, str) and contracts.CANARY.fullmatch(self.family_canary) is not None,
                "family index: no build canary (rebuild the campaign with the current family)")
        self.canaries = [self.canary, self.family_canary, *FIXED_CANARIES]
        for task_id, task in self.tasks.items():
            listed = task.get("value_canaries")
            require(isinstance(listed, list) and all(isinstance(c, str) and c for c in listed),
                    f"{task_id}: the bank index lists no value canaries (rebuild the campaign with the current builder)")
            self.canaries += [c for c in listed if c not in self.canaries]
        self._check_separation()

    def _check_code(self, check_environment):
        stage_python = self.config["stage_python"]
        problems = self._code_problems()
        require(not problems, "; ".join(problems))
        # The frozen texts are read ONCE, verified against every arm's manifest hashes and held: every
        # prompt this coordinator delivers or seals is rendered from these bytes, never re-read (R0.0).
        texts = {name: treatment.frozen_bytes(name) for name in treatment.FROZEN_FILES}
        problems = self._text_problems(texts)
        require(not problems, "frozen treatment texts: " + "; ".join(problems))
        self.texts = texts
        if check_environment:
            environment = environment_manifest(
                subject_python=self.config["subject_python"], stage_python=stage_python,
                stage_env=self.config["stage_env"], sandbox=self.config["sandbox"], host_launch=self.host_launch,
                family_index_sha256=canonical.sha256_file(self.family_dir / "index.json"))
            require(canonical.digest(environment) == self.host["environment_manifest_sha256"],
                    "the environment differs from the frozen environment manifest")

    def _code_problems(self) -> list:
        """What changed since the freeze: the four arm manifests rebuilt from disk (treatment texts,
        tool guide, client, broker and guard, stage workers, kernel source, interpreter, operation
        schemas), the fake subject, the harness code, and the treatment texts this coordinator holds."""
        problems = []
        try:
            arms = arm_manifests(self.config["stage_python"])
        except (ContractError, OSError) as exc:
            arms = None
            problems.append(f"the treatment manifests cannot be rebuilt: {exc}")
        if arms is not None and canonical.canonical_bytes(arms) != canonical.canonical_bytes(self.manifest["arms"]):
            problems.append("treatment code, kernel source or interpreter changed since the campaign was frozen")
        if self.host["adapter"] == "fake" and self.host["version"] != fake_host_version():
            problems.append("fake_subject.py changed since the campaign was frozen")
        try:
            now = {e["path"]: e["sha256"] for e in harness_manifest()}
        except (ContractError, OSError) as exc:
            now = None
            problems.append(f"the harness code cannot be read: {exc}")
        if now is not None:
            frozen = {e["path"]: e["sha256"] for e in self.environment["harness_code"]}
            changed = sorted(p for p in set(now) | set(frozen) if now.get(p) != frozen.get(p))
            if changed:
                problems.append(f"harness code changed since the campaign was frozen: {changed[:10]}")
        held = getattr(self, "texts", None)
        if held is not None:
            for name, data in held.items():
                try:
                    unchanged = treatment.frozen_bytes(name) == data
                except (ContractError, OSError):
                    unchanged = False
                if not unchanged:
                    problems.append(f"the frozen {name} text on disk differs from the bytes verified at load")
        return problems

    def _text_problems(self, texts) -> list:
        """The frozen envelope and instruction bytes against every arm manifest's hashes (§4.3)."""
        problems = []
        appended = treatment.SEPARATOR + texts["instructions"]
        for arm, manifest in self.manifest["arms"].items():
            included = manifest["instructions"]["included"]
            if canonical.sha256_bytes(texts["envelope"]) != manifest["common"]["envelope_sha256"]:
                problems.append(f"{arm}: the envelope does not hash to common.envelope_sha256")
            if included and canonical.sha256_bytes(appended) != manifest["instructions"]["text_sha256"]:
                problems.append(f"{arm}: the appended instructions do not hash to instructions.text_sha256")
            template = texts["envelope"] + (appended if included else b"")
            if canonical.sha256_bytes(template) != manifest["prompt_template_sha256"]:
                problems.append(f"{arm}: the prompt template does not hash to prompt_template_sha256")
        return problems

    def instructions_sha256(self) -> str:
        """The campaign's frozen appended-instruction hash (the text_sha256 of its instruction arms)."""
        hashes = {m["instructions"]["text_sha256"] for m in self.manifest["arms"].values()
                  if m["instructions"]["included"]}
        require(len(hashes) == 1, "campaign arms: exactly one frozen instruction text expected")
        return hashes.pop()

    def leaks(self, data: bytes) -> list:
        """Codes of evaluator material in subject-visible bytes: its hash or any canary."""
        codes = ["forbidden_content"] if canonical.sha256_bytes(data) in self.forbidden_sha256 else []
        return codes + (["canary"] if any(c.encode() in data for c in self.canaries) else [])

    def _check_separation(self):
        """Every fixed canary sits in its evaluator source; no subject-visible byte (workspace
        template, inputs, fake subject script, every arm's prompt) is evaluator-private or holds a
        canary."""
        visible = {"tools.md": self.tool_guide, "bin/ravel-task": self.client, "client source": CLIENT.read_bytes()}
        if self.host["adapter"] == "fake":
            visible["fake subject"] = fake_adapter.SUBJECT_SCRIPT.read_bytes()
        placeholder = self.subjects_root / PLACEHOLDER_HANDLE
        for task_id in self.tasks:
            visible[f"{task_id} request.md"] = self.requests[task_id]
            for name, data in self.inputs(task_id, "current").items():
                visible[f"{task_id} input {name}"] = data
            evaluator = self.evaluator_files(task_id)
            kind = canonical.strict_loads(evaluator["task_definition.json"].decode("utf-8"))["oracle_kind"]
            require(ORACLE_CANARIES[kind].encode() in evaluator["oracle.json"], f"{task_id}: oracle canary missing")
            require(DEFINITION_CANARY.encode() in evaluator["task_definition.json"], f"{task_id}: definition canary")
            for name, data in evaluator.items():
                require(self.family_canary.encode() in data, f"{task_id}: {name} lacks the family build canary")
        first = {}   # one task per distinct request: the prompt depends on the arm and the request only
        for task_id, data in self.requests.items():
            first.setdefault(data, task_id)
        for task_id in first.values():
            for arm in contracts.ARMS:
                visible[f"{task_id} {arm} prompt"] = self.prompt({"arm": arm, "task_id": task_id}, placeholder).encode()
        for label, data in visible.items():
            codes = self.leaks(data)
            require(not codes, f"subject-visible {label}: evaluator material ({', '.join(codes)})")

    # -- per-task material
    def inputs(self, task_id, side) -> dict:
        result = {}
        for name, entry in self.tasks[task_id]["inputs"][side].items():
            data = (self.family_dir / entry["path"]).read_bytes()
            require(canonical.sha256_bytes(data) == entry["sha256"], f"{task_id}: {side} input {name} changed")
            result[name] = data
        return result

    def definition(self, task_id) -> dict:
        """The task's frozen definition (verified against the index): the coordinator reads its input kinds and prior
        recipe to set up the broker; nothing of it reaches the subject but the prior artifacts the recipe makes."""
        return canonical.strict_loads(self.evaluator_files(task_id)["task_definition.json"].decode("utf-8"))

    def broker_inputs(self, task_id) -> dict:
        """{current, prior}: {registry input kind: bytes} of the task's inputs, named by kind as its definition lists
        them (input names may have subdirectories: sample/, archive/)."""
        definition = self.definition(task_id)
        by_side = {}
        for side, key in (("current", "inputs"), ("prior", "prior_inputs")):
            kinds = {item["name"]: item["kind"] for item in definition[key]}
            files = self.inputs(task_id, side)
            require(set(files) == set(kinds), f"{task_id}: {side} inputs differ from the definition's")
            by_side[side] = {kinds[name]: data for name, data in files.items()}
        return by_side

    def evaluator_files(self, task_id) -> dict:
        task = self.tasks[task_id]
        files = {}
        for name, key in (("oracle.json", "oracle"), ("task_definition.json", "definition")):
            data = (self.family_dir / task[f"{key}_path"]).read_bytes()
            require(canonical.sha256_bytes(data) == task[f"{key}_sha256"], f"{task_id}: {name} changed")
            files[name] = data
        return files

    def opaque(self, run_id) -> str:
        return hmac.new(self.secret, run_id.encode(), hashlib.sha256).hexdigest()[:16]

    def run_dir(self, run_id) -> Path:
        return self.dir / "runs" / run_id

    def prompt(self, run, ws) -> str:
        """The run's prompt, rendered from the frozen texts verified at load (never re-read from disk)."""
        policy = RESOURCE_POLICY.format(ops=self.budget["max_broker_ops"], fits=self.budget["max_fits"],
                                        stages=self.budget["max_stage_executions"],
                                        seconds=self.budget["seconds_per_run"])
        included = self.manifest["arms"][run["arm"]]["instructions"]["included"]
        return treatment.render_prompt(
            self.texts["envelope"], treatment.SEPARATOR + self.texts["instructions"] if included else None,
            request_text=self.requests[run["task_id"]].decode("utf-8").strip(), input_root=str(ws),
            output_root=str(ws / "output"),
            resource_policy=policy)

    def plan(self, behavior_plan):
        """(plan, sha256) for the fake host (default: reference everywhere); (None, None) otherwise."""
        if self.host["adapter"] != "fake":
            require(behavior_plan is None, "behavior_plan: synthetic fake host only")
            return None, None
        plan = {"default": "reference", "by_task_arm": {}} if behavior_plan is None else behavior_plan
        require(isinstance(plan, dict) and set(plan) == {"default", "by_task_arm"},
                "behavior_plan: fields must be default, by_task_arm")
        require(plan["default"] in fake_adapter.BEHAVIORS,
                f"behavior_plan.default: one of {list(fake_adapter.BEHAVIORS)}")
        require(isinstance(plan["by_task_arm"], dict), "behavior_plan.by_task_arm: object required")
        for key, behavior in plan["by_task_arm"].items():
            task_id, sep, arm = key.partition("|") if isinstance(key, str) else ("", "", "")
            require(sep and task_id in self.tasks and arm in contracts.ARMS, f"behavior_plan: bad key {key!r}")
            require(behavior in fake_adapter.BEHAVIORS, f"behavior_plan[{key!r}]: unknown behavior {behavior!r}")
        sha = canonical.digest(plan)
        path = self.dir / COORDINATOR / "behavior_plans" / f"{sha}.json"
        if not path.exists():
            canonical.write_once(path, _pretty(plan))
        return plan, sha

    # -- accounting
    def spent_exact(self) -> tuple:
        """(USD, seconds) as exact decimals: the charges journaled by every run (exited or interrupted);
        never reset, never minted."""
        usd = seconds = Decimal(0)
        for run in self.registry["runs"]:
            for record in read_journal(self.run_dir(run["run_id"]) / "journal.jsonl"):
                charge = record["details"].get("charge") if record["state"] in ("exited", "interrupted_crash") else None
                if charge:
                    usd, seconds = usd + exact(charge["usd"]), seconds + exact(charge["seconds"])
        return usd, seconds

    def spent(self) -> dict:
        usd, seconds = self.spent_exact()
        return {"usd": float(usd), "seconds": float(seconds)}

    def credential_fingerprint(self, token: bytes) -> str:
        """The keyed fingerprint of a credential (HMAC-SHA256 under coordinator/campaign_secret, which is never
        sealed): it tells a resume whether the file still holds the token a launch used, and is no check value for
        anyone without the campaign secret (never a plain hash of a retained secret)."""
        return credentials.keyed_digest(self.secret, token, credentials.FINGERPRINT_PURPOSE)

    def redaction_digest(self, data: bytes) -> str:
        """The keyed digest a redaction record keeps of the bytes before redaction (audit.py recomputes it with the
        campaign secret to find sealed pre-redaction bytes); never a plain hash of token-bearing bytes."""
        return credentials.keyed_digest(self.secret, data, credentials.REDACTION_PURPOSE)

    def open_launches(self, exclude=None) -> list:
        """The run ids whose journal records a launch (``launched``) without a closing record: lost launches not yet
        resumed. Global admission charges each at the per-run caps until its resume charges it (E-79)."""
        found = []
        for run in self.registry["runs"]:
            if run["run_id"] == exclude:
                continue
            states = {r["state"] for r in read_journal(self.run_dir(run["run_id"]) / "journal.jsonl")}
            if "launched" in states and not states & {"exited", "interrupted_crash", "not_started"}:
                found.append(run["run_id"])
        return found

    def charge(self, usd, provenance, seconds) -> dict:
        """Unknown cost or time is charged at the per-run cap, never zero. Only a fake-host run costs 0
        (provenance none_synthetic); none_synthetic from any other host counts as unknown."""
        if provenance == "none_synthetic" and self.host["adapter"] == "fake":
            usd, usd_basis = 0.0, "none_synthetic"
        elif provenance != "none_synthetic" and canonical.finite_number(usd) and usd >= 0:
            usd, usd_basis = float(usd), "reported"
        else:
            usd, usd_basis = float(self.budget["usd_per_run"]), "per_run_cap_unknown"
        if canonical.finite_number(seconds) and seconds >= 0:
            seconds, seconds_basis = float(seconds), "measured"
        else:
            seconds, seconds_basis = float(self.budget["seconds_per_run"]), "per_run_cap_unknown"
        return {"usd": usd, "usd_basis": usd_basis, "seconds": seconds, "seconds_basis": seconds_basis}

    def host_state_dir_for(self, run_id):
        """A real host's per-run state directory ``<host_state_root>/<opaque handle>`` (run_id None: the placeholder
        the build- and load-time profile checks use); None for the fake host."""
        if not self.real:
            return None
        return self.host_state_root / (PLACEHOLDER_HANDLE if run_id is None else self.opaque(run_id))

    # -- one assignment
    def process(self, run, plan, plan_sha, factory) -> dict:
        rid = run["run_id"]
        journal = self.run_dir(rid) / "journal.jsonl"
        records = read_journal(journal)
        if any(r["state"] == "sealed" for r in records):   # skipped only while its seal reconciles (RT-01)
            return {"run_id": rid, "action": "skipped", "evidence_sha256": sealed_evidence(self.run_dir(rid))}
        self._copy_evaluator(run)
        if records:
            return self._resume(run, records)
        return self._start(run, plan, plan_sha, factory)

    def close_stopped(self, run, stop) -> dict:
        """Close one assignment under a stop (smoke spec §4): a sealed run is skipped, a run the journal already
        opened is resumed as usual (a lost launch stays a lost launch), and an untouched one is closed not_started
        with charge 0 after its evaluator files are copied, so every assignment keeps a v1 row. Never launches."""
        rid = run["run_id"]
        records = read_journal(self.run_dir(rid) / "journal.jsonl")
        if any(r["state"] == "sealed" for r in records):
            return {"run_id": rid, "action": "skipped", "evidence_sha256": sealed_evidence(self.run_dir(rid))}
        self._copy_evaluator(run)
        if records:
            return self._resume(run, records)
        return self._not_started(run, STOPPED_REASON.format(rule=stop["rule"], reason=stop["reason"]), code="stopped")

    def _copy_evaluator(self, run):
        target = self.dir / "evaluator" / run["run_id"]
        for name, data in self.evaluator_files(run["task_id"]).items():
            path = target / name
            if os.path.lexists(path):
                require(path.is_file() and not path.is_symlink() and path.read_bytes() == data,
                        f"evaluator/{run['run_id']}/{name} differs from the frozen family")
            else:
                canonical.write_once(path, data)

    def _start(self, run, plan, plan_sha, factory):
        rid = run["run_id"]
        journal = self.run_dir(rid) / "journal.jsonl"
        behavior = None if plan is None else plan["by_task_arm"].get(f"{run['task_id']}|{run['arm']}", plan["default"])
        assignment = {"adapter": self.host["adapter"], "behavior": behavior, "behavior_plan_sha256": plan_sha}
        opaque = self.opaque(rid)
        ws = self.subjects_root / opaque
        state = self.host_state_dir_for(rid)
        try:
            files = _subject_files(self, run)
            self.subjects_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.real:   # both roots were created 0700 at build; verified again before anything goes in
                for root, label in ((self.subjects_root, "subjects_root"), (self.host_state_root, "host_state_root")):
                    problem = host_root_problem(root)
                    require(problem is None, f"{label}: {problem}")
            isolation.materialize(files, ws)
            if state is not None:
                os.mkdir(state, 0o700)   # fresh: a leftover from an earlier attempt is refused, never reused
        except (ContractError, OSError) as exc:
            reason = f"subject workspace materialization failed: {exc}"
            _record(journal, "admission_failed", stage="materialization", reason=reason, **assignment)
            return self._not_started(run, reason, code="materialization")
        _record(journal, "materialized", opaque_handle=opaque, subject_root=str(ws),
                workspace_files={n: canonical.sha256_bytes(d) for n, d in sorted(files.items()) if not n.endswith("/")},
                evaluator_files={n: canonical.sha256_bytes(d) for n, d in self.evaluator_files(run["task_id"]).items()},
                campaign_sha256=self.campaign_sha256,
                **({"host_state_dir": str(state)} if state is not None else {}), **assignment)
        check = self._admit(ws, {})
        if not check["ok"]:
            reason = "admission check failed (workspace): " + ", ".join(
                sorted({v["code"] for v in check["violations"]}))
            _record(journal, "admission_failed", stage="workspace", reason=reason, violations=check["violations"])
            return self._not_started(run, reason, code="admission")
        # §10: global budget admission after the admission check, in exact decimals (a campaign sized to
        # N runs at the cap admits all N; float sums would refuse the last one). A real host's launch that is on
        # record but not closed (a lost launch not yet resumed) counts at the per-run caps (E-79).
        (usd, seconds), b = self.spent_exact(), self.budget
        if self.real:
            open_launches = self.open_launches(exclude=rid)
            usd += exact(b["usd_per_run"]) * len(open_launches)
            seconds += exact(b["seconds_per_run"]) * len(open_launches)
        remaining = {"usd": exact(b["global_usd_cap"]) - usd, "seconds": exact(b["global_seconds_cap"]) - seconds}
        if remaining["usd"] < exact(b["usd_per_run"]) or remaining["seconds"] < exact(b["seconds_per_run"]):
            reason = (f"global budget admission: remaining {remaining['usd']:f} USD / {remaining['seconds']:f} s is "
                      f"below the per-run cap {b['usd_per_run']:g} USD / {b['seconds_per_run']:g} s")
            _record(journal, "admission_failed", stage="global_budget", reason=reason,
                    spent={"usd": float(usd), "seconds": float(seconds)})
            return self._not_started(run, reason, code="global_budget")
        try:
            broker, handles = self._broker(run)
        except Exception as exc:   # kernel probe or prior stages: fail closed, the subject never runs
            reason = f"broker preparation failed: {type(exc).__name__}: {exc}"
            _record(journal, "admission_failed", stage="broker", reason=reason)
            return self._not_started(run, reason, code="broker_preparation")
        proxy = None
        if self.real:   # WI-4: one proxy per launch, in this process; it serves only the launch's leader
            from . import live
            proxy = allowlist_proxy.AllowlistProxy(self.host_launch["proxy"]["allow"],
                                                   log_path=self.run_dir(rid) / "host" / "proxy.jsonl")
            proxy.owner_check = lambda address: live.socket_owned_by(proxy.owner_pid, address[1], proxy.port)
            try:
                proxy.start()
            except OSError as exc:
                reason = f"proxy start failed: {type(exc).__name__}: {exc}"
                _record(journal, "admission_failed", stage="proxy", reason=reason)
                return self._not_started(run, reason, code="proxy_start_failed")
        stop_error, summary, box, broker_seconds = None, None, {}, None
        try:
            kind, value, code = self._serve(run, ws, broker, handles, behavior, assignment, factory, proxy=proxy,
                                            state=state, box=box)
        finally:
            if proxy is not None:   # first: the host is gone, so nothing may reach the proxy while the broker drains
                proxy.owner_pid = None
                proxy.stop()        # joins its handlers (bounded) before its log is summarized and sealed
                summary = proxy_summary(proxy.decisions, stop_error=proxy.stop_error,
                                        late=proxy.late_decisions)
            began = time.monotonic()
            try:
                broker.stop()       # may wait up to broker.STOP_SECONDS for a stage call in progress
            except RuntimeError as exc:
                stop_error = str(exc)
            broker_seconds = round(time.monotonic() - began, 3)
        recorder = box.get("recorder")
        try:
            extra = {"broker_stop_error": stop_error} if stop_error else {}
            if self.real:
                extra["broker_stop_seconds"] = broker_seconds
            if summary is not None:
                extra["proxy"] = summary
            if kind == "not_started":
                return self._not_started(run, value, code=code, **extra)
            data = None
            if kind == "exited":
                result = value.as_dict()
                data = _pretty(result)
            if self.real:   # before anything is written or sealed: redact, sweep, check (WI-5, WI-7b)
                needle = recorder.needle if recorder is not None else None
                post, data = self._post_run(run, ws, state, needle, data, summary)
                extra.update(post)
                if kind == "adapter_error" and needle is not None:
                    value = credentials.redact_value(value, needle)[0]
            if kind == "adapter_error":
                extra.update(self._post_run_drift())
                return self._crash(run, "adapter_error", error=value, **extra)
            canonical.write_once(self.run_dir(rid) / "host" / "adapter_result.json", data)   # M2: the paid result
            extra.update(self._post_run_drift())   # first, then the drift check (which never raises)
            charge = self.charge(result["cost"]["usd"], result["cost"]["provenance"], result["wall_seconds"])
            _record(journal, "exited", status_hint=result["status_hint"], exit_code=result["exit_code"],
                    wall_seconds=result["wall_seconds"], cost=result["cost"], validity=result["validity"],
                    charge=charge, **extra)
            return self._seal(run)
        finally:
            if recorder is not None:
                recorder.release()

    def _post_run_drift(self) -> dict:
        """M2: the post-run drift check, total: {"code_drift": problems} or {}; an exception is itself a drift
        entry, never a lost result."""
        try:
            drift = self._code_problems()
        except Exception as exc:   # noqa: BLE001 - the run already happened and was paid for
            drift = [f"post-run drift check failed: {type(exc).__name__}: {exc}"]
        return {"code_drift": drift} if drift else {}

    def _broker(self, run):
        guard = self.manifest["arms"][run["arm"]]["guard"]
        broker = Broker(self.dir / "broker" / run["run_id"], guard_mode=guard["mode"], feedback=guard["feedback"],
                        budgets={name: self.budget[name] for name in BROKER_BUDGET},
                        python=self.config["stage_python"], env=self.config["stage_env"],
                        secret=secrets.token_bytes(32))
        by_kind = self.broker_inputs(run["task_id"])
        current = broker.register_inputs(by_kind["current"])
        prior = broker.create_prior(by_kind["prior"], recipe=self.definition(run["task_id"])["prior_recipe"])
        return broker, {"current": current, "prior": prior}

    def _profile(self, ws, ports, host_state_dir=None):
        """The Seatbelt profile (None for none_test_only, whose policy inputs are still validated). ``ports``: the
        broker port, or [broker, proxy] for a real host, whose policy adds its host access (``host_state_dir``)."""
        ports = [ports] if isinstance(ports, int) else list(ports)
        access = host_access(self.host_launch, host_state_dir) if self.real else None
        policy = launch_policy(workspace=ws, subject_prefix=self.config["subject_prefix"],
                               forbidden=self.forbidden_roots, port=ports[0], extra_ports=ports[1:],
                               host_access=access)
        return isolation.seatbelt_profile(policy) if self.host["sandbox"] == "seatbelt" else None

    def _admit(self, ws, env):
        return isolation.admission_check(ws, forbidden_sha256=self.forbidden_sha256, canaries=self.canaries, env=env,
                                         forbidden_roots=self.forbidden_roots)

    def _serve(self, run, ws, broker, handles, behavior, assignment, factory, *, proxy=None, state=None, box=None):
        """Start the broker, admit the launch environment and prompt, re-verify what the run receives
        against the frozen campaign, bind the host, launch. Returns (kind, value, not_started code).

        A real host's environment adds the proxy variables (coordinator environment: never bound, never the
        adapter's to change) and puts the subject interpreter's directory first on PATH (E-49); its profile
        reaches the broker and its proxy and grants its host access; its recording launcher checks the exact
        call against the build-time binding (M6), injects the credential and hands the proxy its owner."""
        rid = run["run_id"]
        journal, host_dir = self.run_dir(rid) / "journal.jsonl", self.run_dir(rid) / "host"
        endpoint, token = broker.start()
        parts = urllib.parse.urlsplit(endpoint)
        require(parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.port,
                f"broker endpoint is not 127.0.0.1: {endpoint}")
        extra, path_dirs, ports = {"RAVEL_TASK_ENDPOINT": endpoint, "RAVEL_TASK_TOKEN": token}, \
            ["/usr/bin", "/bin", str(ws / "bin")], [parts.port]
        if self.real:
            url, no_proxy = f"http://127.0.0.1:{proxy.port}", self.host_launch["proxy"]["no_proxy"]
            extra.update({"HTTPS_PROXY": url, "https_proxy": url, "NO_PROXY": no_proxy, "no_proxy": no_proxy})
            path_dirs.insert(0, os.path.dirname(self.config["subject_python"]))
            ports.append(proxy.port)
        env = isolation.subject_env(workspace=ws, home=ws / "home", path_dirs=path_dirs, extra=extra)

        def refuse(stage, reason, code=None, **details):
            _record(journal, "admission_failed", stage=stage, reason=reason, **details)
            return "not_started", reason, code or stage

        try:
            profile = self._profile(ws, ports, host_state_dir=state)   # after start: exactly the broker/proxy ports
        except ContractError as exc:
            return refuse("profile", f"admission check failed (launch profile): {exc}")
        check = self._admit(ws, env)
        if not check["ok"]:
            return refuse("environment", "admission check failed (launch environment): " + ", ".join(
                sorted({v["code"] for v in check["violations"]})), violations=check["violations"])
        prompt = self.prompt(run, ws)
        leaks = self.leaks(prompt.encode())
        if leaks:
            return refuse("prompt", "admission check failed (prompt): " + ", ".join(leaks))
        verified, problems = self._verify_launch(run, ws, prompt)
        if problems:
            return refuse("treatment", "treatment verification failed before the launch (the run would not "
                                       "receive the frozen treatment): " + "; ".join(problems), problems=problems)
        _record(journal, "admitted", broker_port=parts.port, current_handles=handles["current"],
                prior_handles=handles["prior"], profile_sha256=profile_sha256(profile), verified=verified,
                **({"proxy_port": proxy.port} if proxy is not None else {}))
        expected = {}   # M6: filled with the bound call once the host binding is checked, before adapter.run
        credential = self.host_launch["credential"] if self.real else None
        recorder = _Recorder(
            host_dir / "launch_call.json", journal,
            check=lambda argv, final_env: self._launch_call_problems(argv, final_env, env, expected=expected.get("call"),
                                                                     require_expected=self.real),
            credential=(credential["env_name"], credential["file"]) if credential else None,
            admission=(lambda final_env, names: isolation.env_admission(
                final_env, canaries=self.canaries, forbidden_roots=self.forbidden_roots,
                allowed_secret_names=names)) if credential else None,
            proxy=proxy, remove_unattributed_ipc=not self.real,
            fingerprint=self.credential_fingerprint if credential else None)
        if box is not None:
            box["recorder"] = recorder
        # The arm is not passed: the runner resolves everything arm-dependent (the fake behavior plan),
        # so no factory can configure a host differently by arm (R0.5).
        request = {"run_id": rid, "task_id": run["task_id"], "seed": run["seed"], "behavior": behavior,
                   "python": self.config["subject_python"], "launcher": recorder}
        if state is not None:
            request["host_state_dir"] = str(state)
        adapter = factory(request)
        name = getattr(adapter, "name", None)
        require(name == self.host["adapter"], f"adapter factory returned a {name!r} adapter for a "
                                              f"{self.host['adapter']} host")
        executor = getattr(adapter, "executor_id", None)
        require(isinstance(executor, str) and executor.strip(), "adapter: executor_id required")
        if getattr(adapter, "launcher", None) is not recorder:
            return refuse("host", "the adapter does not launch through the coordinator's recording launcher, so its "
                                  "launch could not be journaled or censused")
        binding_sha256, gate = None, {}
        if self.real:
            binding, problems = self._bind_host(adapter)
            if problems:
                return refuse("host", "host configuration differs from the campaign: " + "; ".join(problems),
                              code="binding_mismatch", problems=problems)
            binding_sha256 = canonical.digest(binding)
            expected["call"] = {"binding": binding, "per_run_env": {
                "CLAUDE_CONFIG_DIR": str(state / HOST_STATE_SUBDIRS[0]),
                "CLAUDE_CODE_TMPDIR": str(state / HOST_STATE_SUBDIRS[1])}}
            gate = {"behavioral_record_sha256": getattr(self, "behavioral_sha256", None)}
        timeout = self.budget["seconds_per_run"]
        _record(journal, "launched", executor_id=executor, timeout_s=timeout, profile_sha256=profile_sha256(profile),
                prompt_sha256=canonical.sha256_bytes(prompt.encode()), campaign_sha256=self.campaign_sha256,
                host_binding_sha256=binding_sha256, **gate, **assignment)
        try:
            result = adapter.run(prompt=prompt, workspace=ws, env=env, profile=profile, timeout_s=timeout,
                                 out_dir=host_dir)
        except Exception as exc:  # never a retry: a lost launch if the launcher was called, else not started
            if self._launcher_called(rid):
                return "adapter_error", f"{type(exc).__name__}: {exc}", None
            if isinstance(exc, HostDriftError):
                what, code = "host drift; the host was not launched", "host_drift"
            elif isinstance(exc, LaunchRefused):
                what, code = "the launch call was refused before anything started", exc.code
            else:
                what, code = "the adapter failed before calling the launcher; no process was started", \
                    "adapter_before_launch"
            return "not_started", f"{what}: {type(exc).__name__}: {exc}", code
        return "exited", result, None

    def _launcher_called(self, run_id) -> bool:
        """Whether the recording launcher was ever called for this run: its launch call or a process
        start is on record. Without either, no subject process can have been started (the call record
        is written before isolation.launch is entered), so a failure is not_started, never a lost launch."""
        call = self.run_dir(run_id) / "host" / "launch_call.json"
        return os.path.lexists(call) or any(r["state"] == "process_started"
                                            for r in read_journal(self.run_dir(run_id) / "journal.jsonl"))

    def _verify_launch(self, run, ws, prompt) -> tuple:
        """(record, problems): what this run is about to receive, re-verified against the frozen campaign
        just before its launch (R0.0). campaign.json's bytes; every arm manifest rebuilt from the code on
        disk (common hashes: envelope, tool guide, client, broker and guard, stage workers, kernel source,
        interpreter, operation schemas; guard implementation) and the harness code; the frozen texts on
        disk against the bytes held since load; the prompt's instruction segment against this arm's
        manifest (treatment.check_prompt) and its template hash; request.md against the v1 prompt_sha256;
        and the materialized request.md, tools.md and client against the frozen bytes. The record is
        journaled in ``admitted``; any problem refuses the launch (not_started)."""
        arm = self.manifest["arms"][run["arm"]]
        problems = []
        current = canonical.sha256_file(self.dir / campaign_manifest.MANIFEST)
        if current != self.campaign_sha256:
            problems.append(f"campaign.json changed since this coordinator loaded it (now sha256 {current})")
        problems += self._code_problems()
        task = next(t for t in self.spec["tasks"] if t["id"] == run["task_id"])
        request = self.requests[run["task_id"]]
        request_sha256 = canonical.sha256_bytes(request)
        if request_sha256 != task["prompt_sha256"]:
            problems.append("request.md is not the prompt_sha256 the v1 spec freezes for this task")
        if canonical.sha256_bytes(self.tool_guide) != arm["common"]["tool_guide_sha256"]:
            problems.append("the tool guide is not the one the treatment manifest binds")
        if canonical.sha256_bytes(self.client) != self.environment["materialized_client_sha256"]:
            problems.append("the client is not the one the environment manifest binds")
        for name, data in (("request.md", request), ("tools.md", self.tool_guide), ("bin/ravel-task", self.client)):
            path = ws / name
            if not (path.is_file() and not path.is_symlink() and path.read_bytes() == data):
                problems.append(f"the materialized {name} differs from the frozen bytes")
        included = arm["instructions"]["included"]
        template = self.texts["envelope"] + (treatment.SEPARATOR + self.texts["instructions"] if included else b"")
        if canonical.sha256_bytes(template) != arm["prompt_template_sha256"]:
            problems.append("the prompt template is not the manifest's prompt_template_sha256")
        problems += treatment.check_prompt(prompt, arm, instructions_sha256=self.instructions_sha256())
        record = {"campaign_sha256": current, "treatment_manifest_sha256": canonical.digest(arm),
                  "common_sha256": canonical.digest(arm["common"]),
                  "guard_implementation_sha256": arm["guard"]["implementation_sha256"],
                  "harness_sha256": canonical.digest(self.environment["harness_code"]),
                  "instructions_sha256": arm["instructions"]["text_sha256"],
                  "prompt_template_sha256": canonical.sha256_bytes(template),
                  "prompt_sha256": canonical.sha256_bytes(prompt.encode()), "request_sha256": request_sha256}
        return record, problems

    def _launch_call_problems(self, argv, env, base_env, expected=None, require_expected=False) -> list:
        """The final launch call an adapter makes, checked by the recording launcher before anything
        starts: the coordinator's subject environment is passed on unchanged (an adapter may only add),
        neither an added environment value nor any argv element carries evaluator material, no added name
        looks like a credential (isolation.SECRET_NAME: the coordinator alone injects the declared one), and,
        for a real host, no added value names an arm (the per-run directories its factory chooses, R0.5; the
        fake host's arm-dependent behavior is the runner's own plan, and its synthetic test adapters
        pass probe paths such as the repository's audit.py, which the arm-term scan would name).

        M6 (a real host, ``expected`` = {binding, per_run_env}): exactly one ``--session-id`` with a canonical
        uuid, the argv equal to the binding's with that uuid replaced by the placeholder, the added names exactly
        the binding's plus the per-run directories, each bound value and each per-run path equal to the
        coordinator's, and none of the names that may never reach a real host anywhere in the final environment.
        ``require_expected``: a real host's call before its binding was checked is refused."""
        problems = []
        changed = sorted(n for n, v in base_env.items() if env.get(n) != v)
        if changed:
            problems.append(f"the adapter changed or dropped coordinator environment variables {changed}")
        added = sorted(set(env) - set(base_env))
        for name in added:
            value = env[name]
            if not isinstance(value, str):
                problems.append(f"environment variable {name} is not a string")
                continue
            terms = treatment.arm_identifying_terms(value) if self.host["adapter"] != "fake" else []
            if terms:
                problems.append(f"environment variable {name} names {terms}")
            if self.leaks(value.encode()):
                problems.append(f"environment variable {name} carries evaluator material")
        secret = [n for n in added if isolation.SECRET_NAME.search(n)]
        if secret:
            problems.append(f"the adapter added credential-like variables {secret}; only the coordinator injects the "
                            "declared credential")
        for i, element in enumerate(argv):
            if isinstance(element, str) and self.leaks(element.encode()):
                problems.append(f"argv[{i}] carries evaluator material")
        if require_expected and expected is None:
            problems.append("the launch call came before the host binding was checked")
        if expected is not None:
            problems += _bound_call_problems(list(argv), env, set(added), expected)
        return problems

    def _bind_host(self, adapter) -> tuple:
        """host_binding against the campaign, then against the binding written at build
        (coordinator/host_binding.json, R20): every run launches the host identically, and exactly as the
        builder bound it. A real host's campaign without that file is refused (never bound at a launch)."""
        binding, problems = host_binding(adapter, self.host, self.budget, self.manifest["kind"])
        if problems:
            return binding, problems
        path = self.dir / COORDINATOR / HOST_BINDING
        if not os.path.lexists(path):
            problems.append(f"no host binding was written at build (coordinator/{HOST_BINDING}); rebuild the campaign")
        elif canonical.canonical_bytes(canonical.strict_load(path)) != canonical.canonical_bytes(binding):
            problems.append(f"the host launch differs from the binding written at build (coordinator/{HOST_BINDING})")
        return binding, problems

    def _not_started(self, run, reason, code=None, **extra):
        if code is not None:
            extra["code"] = code
        _record(self.run_dir(run["run_id"]) / "journal.jsonl", "not_started", reason=reason,
                charge={"usd": 0.0, "usd_basis": "not_started", "seconds": 0.0, "seconds_basis": "not_started"},
                **extra)
        return self._seal(run)

    def _crash(self, run, cause, *, census=None, **extra):
        """A lost launch: census of exactly that launch, charge at the cap (unknown), journal, seal.
        Never relaunched."""
        require(cause in LOST_CAUSES, f"lost launch cause: one of {list(LOST_CAUSES)}")
        found = census if census is not None else self._lost_census(run["run_id"])
        provenance = "none_synthetic" if self.host["adapter"] == "fake" else None
        _record(self.run_dir(run["run_id"]) / "journal.jsonl", "interrupted_crash", cause=cause,
                note=LOST_NOTES[cause], census=found, charge=self.charge(None, provenance, None), **extra)
        return self._seal(run)

    def _lost_census(self, run_id) -> dict:
        """isolation.census_launch on the journaled process_started record. Without one, the launcher
        never started a subject (no launch call), or the coordinator died between the start and its
        record (a launch call exists): then the census is incomplete, survivors unknown."""
        started = [r["details"] for r in read_journal(self.run_dir(run_id) / "journal.jsonl")
                   if r["state"] == "process_started"]
        require(len(started) <= 1, f"{run_id}: more than one process_started record")
        if started:
            return isolation.census_launch(started[0])
        # E-212: the predicate _launcher_called uses, so a launch_call.json that is no regular file (a dangling link,
        # a directory) reads as called: incomplete, never a clean census
        called = os.path.lexists(self.run_dir(run_id) / "host" / "launch_call.json")
        return {"method": "no process_started record: nothing to census", "launch": None, "found": [], "killed": [],
                "survivors": [], "foreign": [], "complete": not called,
                "note": "the launcher was called but no process start was journaled; survivors unknown"
                if called else None}

    def _with_precensus(self, run_id, census) -> dict:
        """A lost launch's resume census with the censuses ``run`` took of it before preflight (E-206,
        runs/<run_id>/precensus-<k>.json): what they found and killed joins this census's ``found`` and ``killed``
        (so a subject killed before preflight still reads subject_outlived_coordinator), and they are kept whole
        under ``precensus``; survivors and completeness stay this census's (the latest look)."""
        from . import live
        earlier = live._precensuses(self.run_dir(run_id))
        if not earlier:
            return census
        found, killed = set(census.get("found") or []), set(census.get("killed") or [])
        incomplete = False
        for _, prior in earlier:
            prior = prior if isinstance(prior, dict) else {}
            found.update(p for p in prior.get("found") or [] if type(p) is int)
            killed.update(p for p in prior.get("killed") or [] if type(p) is int)
            incomplete = incomplete or prior.get("complete") is not True
        # E-212: an earlier census that could not search leaves that period unproven, even when the latest look is
        # complete (the processes it could not prove may have exited since): census_incomplete (_host_files)
        return {**census, "found": sorted(found), "killed": sorted(killed), "precensus_incomplete": incomplete,
                "precensus": [{"k": k, "census": prior} for k, prior in earlier]}

    def _resume(self, run, records):
        states = {r["state"]: r for r in records}
        if "not_started" in states or "exited" in states or "interrupted_crash" in states:
            return self._seal(run)
        if "launched" in states:
            if self._launcher_called(run["run_id"]):
                if not self.real:
                    return self._crash(run, "coordinator_interrupted")
                census = self._lost_census(run["run_id"])   # first: nothing of the launch may still be writing
                census = self._with_precensus(run["run_id"], census)
                return self._crash(run, "coordinator_interrupted", census=census, **self._resume_post_run(run))
            return self._not_started(run, "coordinator interrupted after the launch record and before the launcher "
                                          "was called (no launch call and no process start on record, so no process "
                                          "was started); no retry under policy none", code="interrupted_before_launch")
        if "admission_failed" in states:
            details = states["admission_failed"]["details"]
            return self._not_started(run, details.get("reason") or "admission failed",
                                     code=details.get("stage") if self.real else None)
        return self._not_started(run, f"coordinator interrupted before launch (last state {records[-1]['state']}); "
                                      "no retry under policy none", code="interrupted_before_launch")

    # -- a real host's post-run checks (WI-5, WI-7b, M9)
    def _resume_post_run(self, run) -> dict:
        """The post-run checks of a lost launch, on resume: the credential file is re-read only to sweep (R8), and
        only when its keyed fingerprint equals the one the launch recorded (launch_call.json); a file that cannot be
        re-read, or that now holds another token (re-minted after the launch), leaves the sweep incomplete
        (credential_sweep_incomplete, S2), while every other post-run check still runs. The host's raw streams of such
        a launch cannot be redacted, so they are moved out of the sealed set into ``runs/<id>/quarantine/`` (E-99:
        journaled ``quarantined_streams``; sealed as missing, raw_streams_missing), never sealed unredacted; the
        quarantine is deleted with the token when it is revoked. A launch whose call was never recorded never
        received the credential: nothing to sweep."""
        rid = run["run_id"]
        call_path, note, needle = self.run_dir(rid) / "host" / "launch_call.json", None, None
        call = canonical.strict_load(call_path) if call_path.is_file() and not call_path.is_symlink() else None
        if call is not None:
            try:
                needle = credentials.read_credential(self.host_launch["credential"]["file"]).encode("ascii")
            except credentials.CredentialError as exc:
                note = f"the credential could not be re-read to sweep: {exc}"
            else:
                recorded = call.get("credential_fingerprint")
                if not isinstance(recorded, str) or not hmac.compare_digest(recorded,
                                                                            self.credential_fingerprint(needle)):
                    needle, note = None, ("the credential file no longer holds the token this launch used (its "
                                          "keyed fingerprint differs from the recorded one): the sweep cannot search "
                                          "for the launch's token")
        post, _ = self._post_run(run, self.subjects_root / self.opaque(rid), self.host_state_dir_for(rid), needle,
                                 None, None)
        if note is not None:
            post["credential_sweep"] = {"clean": False, "hits": [], "incomplete": True, "redactions": 0, "note": note}
            post["coordinator_flags"] = sorted(set(post["coordinator_flags"]) | {"credential_sweep_incomplete"})
            post["quarantined_streams"] = self._quarantine_streams(rid)
        return post

    QUARANTINE = "quarantine"   # runs/<id>/quarantine/: unswept raw streams, outside the sealed set (E-99)

    def _quarantine_streams(self, rid) -> list:
        """Move a lost launch's raw host streams, which no sweep could search, out of runs/<id>/host/ (what the seal
        reads) into runs/<id>/quarantine/ (mode 0700, never sealed): [names moved]."""
        host_dir, target = self.run_dir(rid) / "host", self.run_dir(rid) / self.QUARANTINE
        moved = []
        for name in ("stdout.jsonl", "stderr.txt"):
            path = host_dir / name
            if path.is_file() and not path.is_symlink():
                target.mkdir(mode=0o700, exist_ok=True)
                require(not os.path.lexists(target / name), f"{rid}: quarantine/{name} already exists")
                os.rename(path, target / name)
                moved.append(name)
        return moved

    def _post_run(self, run, ws, state, needle, data, proxy) -> tuple:
        """(journal details, adapter-result bytes) of a real host's run, before anything is written or sealed.

        The serialized adapter result is redacted in memory first. Then, each step recorded whatever the others
        find: the sweep of the campaign directory, the workspace and the host state for the token and its
        encodings, every hit redacted (host/redactions.json, with the in-memory redaction); the keychain residue
        check (LC-21); the task client's environment-name reports (LC-11); the canary scan of the host's streams
        and state, and the host-state manifest (hang-safe capped reads, M9); the shell snapshot; the sandbox
        denial collector; the proxy's decisions. ``coordinator_flags`` are sealed as validity flags;
        ``info_flags`` are journaled only (outcomes, not stops)."""
        from . import live
        rid = run["run_id"]
        host_dir = self.run_dir(rid) / "host"
        flags, info, details, redactions = set(), set(), {}, []
        if data is not None and needle is not None:
            redacted, counts = credentials.redact_bytes(data, needle)
            if counts:
                redactions.append({"root": "coordinator_memory", "path": f"runs/{rid}/host/adapter_result.json",
                                   "pre_hmac_sha256": self.redaction_digest(data),
                                   "post_sha256": canonical.sha256_bytes(redacted), "counts_by_variant": counts})
                data = redacted
        try:
            if needle is None:
                details["credential_sweep"] = {"clean": True, "hits": [], "incomplete": False, "redactions": 0,
                                               "note": "no credential was read for this launch: nothing to sweep"}
            else:
                swept = credentials.sweep({"campaign": str(self.dir), "workspace": str(ws), "host_state": str(state)},
                                          needle, redact=True, pre_digest=self.redaction_digest)
                redactions += swept["redactions"]
                renames = [{"root": label, **r} for label, root in (("workspace", ws), ("host_state", state))
                           for r in credentials.redact_names(root, needle)]   # a name the sweep cannot rewrite
                redactions += renames
                if any(not r["renamed"] for r in renames):
                    swept["incomplete"] = True
                hits = swept["hits"] + [{"root": r["root"], "path": r["path"], "where": "content",
                                         "counts": r["counts_by_variant"]} for r in redactions
                                        if r["root"] == "coordinator_memory"]
                details["credential_sweep"] = {"clean": not hits and not swept["incomplete"], "hits": hits,
                                               "incomplete": swept["incomplete"], "redactions": len(redactions),
                                               "skipped": [s for s in swept["skipped"]
                                                           if s["kind"] not in ("missing", "special_file")][:50],
                                               "bytes_read": swept["bytes_read"]}
                if hits:
                    flags.add("credential_exposed")
                if swept["incomplete"]:
                    flags.add("credential_sweep_incomplete")
            if redactions:   # a resumed run keeps what an interrupted post-run check already recorded
                path = host_dir / REDACTIONS
                earlier = canonical.strict_load(path) if path.is_file() and not path.is_symlink() else []
                canonical.atomic_write_bytes(path, _pretty(earlier + redactions))
        except Exception as exc:   # noqa: BLE001 - a sweep that fails is incomplete, never silent
            details["credential_sweep"] = {"clean": False, "hits": [], "incomplete": True, "redactions": len(redactions),
                                           "note": f"the sweep failed: {type(exc).__name__}"}
            flags.add("credential_sweep_incomplete")
        steps = (("keychain", lambda: self._keychain_check(live, state)),
                 ("client_env", lambda: self._client_env_check(rid)),
                 ("canary_scan", lambda: self._canary_check(host_dir, state)),
                 ("sandbox_denials", lambda: self._denials_check(live, rid)),
                 ("host_config", lambda: self._host_config_check(state)))
        for name, step in steps:
            try:
                details[name], found, noted = step()
            except Exception as exc:   # noqa: BLE001 - recorded, and conservative
                details[name], found, noted = {"error": f"{type(exc).__name__}: {exc}"}, \
                    {"keychain": {"credential_persisted_keychain"}, "client_env": {"credential_visible_to_subject"},
                     "canary_scan": {"canary_in_transcript"},
                     "host_config": {"host_config_credential_shaped"}}.get(name, set()), \
                    {"sandbox_denials_unavailable"} if name == "sandbox_denials" else set()
            flags |= found
            info |= noted
        bash = (canonical.strict_loads(data.decode("utf-8")).get("details") or {}).get("bash") if data else None
        snapshots = details.get("canary_scan", {}).get("snapshots", 0)
        details["shell_snapshot"] = {"snapshots": snapshots, "bash_calls": (bash or {}).get("calls")}
        if (bash or {}).get("calls") and not snapshots:
            info.add("shell_snapshot_missing")
        if proxy is not None:
            sealed_flags, noted = proxy_flags(proxy)
            flags |= sealed_flags
            info |= noted
            if needle is not None:   # its request lines and targets came from the host: journaled redacted
                details["proxy"], counts = credentials.redact_value(proxy, needle)
                if counts:
                    flags.add("credential_exposed")
        details["coordinator_flags"] = sorted(flags)
        details["info_flags"] = sorted(info)
        return details, data

    def _host_config_check(self, state):
        """The key NAMES of the host's own config file (``<CLAUDE_CONFIG_DIR>/.claude.json``), read by the coordinator
        (O_NOFOLLOW, nonblocking, capped; values never recorded), with the credential-shaped names among them. The
        host's config directory is a write root of the one profile the host shares with the subject, so the subject
        could read that file during the run, and the host's first-party behaviour after authentication (profile
        fetches, config writes) is unobserved before paid run 1: any credential-shaped name is
        ``host_config_credential_shaped`` (S2, which prints the REVOKE action and ends the token's retention, E-50),
        in every run, and the S10a go/no-go reviews the rest (E-92). A file that cannot be read or parsed sets the same
        flag (_post_run's conservative map)."""
        path = state / HOST_STATE_SUBDIRS[0] / ".claude.json"
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except FileNotFoundError:
            return {"present": False, "keys": [], "credential_shaped": []}, set(), set()
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode), "not a regular file")
            data = os.read(fd, HOST_CONFIG_CAP + 1)
        finally:
            os.close(fd)
        require(len(data) <= HOST_CONFIG_CAP, f"larger than {HOST_CONFIG_CAP} bytes")
        value = json.loads(data.decode("utf-8"))
        keys = sorted(value) if isinstance(value, dict) else []
        nested = sorted(f"{k}.{n}" for k in keys if isinstance(value[k], dict) for n in value[k])
        names = keys + nested
        shaped = [n for n in names if CREDENTIAL_SHAPED.search(n)]
        return {"present": True, "keys": names[:500], "credential_shaped": shaped[:100]}, \
            {"host_config_credential_shaped"} if shaped else set(), set()

    def _keychain_check(self, live, state):
        """LC-21, outside the sandbox: no keychain item named for the run's config dir (as passed and resolved)."""
        found = live.keychain_residue(state / HOST_STATE_SUBDIRS[0])
        return found, {"credential_persisted_keychain"} if found["persisted"] else set(), set()

    def _client_env_check(self, rid):
        """LC-11 (best effort: the report comes from a process the subject controls): no environment-name report
        of the task client lists a credential variable."""
        reports, error = canonical.read_jsonl(self.dir / "broker" / rid / "client_env.jsonl")
        listed = sorted({n for r in reports if isinstance(r, dict) for n in (r.get("names") or [])
                         if n in CREDENTIAL_VISIBLE_NAMES})
        record = {"reports": len(reports), "credential_names": listed, "malformed": error,
                  "markers": sorted({str(r.get("marker")) for r in reports if isinstance(r, dict) and r.get("marker")})}
        return record, {"credential_visible_to_subject"} if listed else set(), set()

    def _canary_check(self, host_dir, state):
        """The canary scan of the host's raw streams and every host-state file, and the host-state manifest, from
        one hang-safe capped read (isolation.read_output_tree: no link followed, FIFOs and devices reported,
        never opened blocking; M9). Value canaries are left out: the host's transcript legitimately carries the
        numbers the task computes."""
        canaries = [self.canary, self.family_canary, *FIXED_CANARIES]
        needles = [c.encode(enc) for c in canaries for enc in isolation.CANARY_ENCODINGS]
        hits = []
        for name in ("stdout.jsonl", "stderr.txt"):
            path = host_dir / name
            if path.is_file() and not path.is_symlink():
                with open(path, "rb") as handle:
                    data = handle.read(HOST_STATE_CAP)
                if any(n in data for n in needles):
                    hits.append(f"host/{name}")
        files, violations = isolation.read_output_tree(state, max_bytes=HOST_STATE_CAP)
        hits += [f"host_state/{rel}" for rel, data in sorted(files.items()) if any(n in data for n in needles)]
        manifest = {"files": [{"path": rel, "bytes": len(data), "sha256": canonical.sha256_bytes(data)}
                              for rel, data in sorted(files.items())],
                    "violations": violations}
        canonical.atomic_write_bytes(host_dir / HOST_STATE_MANIFEST, _pretty(manifest))   # not sealed yet
        snapshots = sum(1 for rel in files if Path(rel).parent.as_posix() == f"{HOST_STATE_SUBDIRS[0]}/shell-snapshots"
                        and Path(rel).name.startswith("snapshot-"))
        record = {"hits": hits, "state_files": len(files), "state_violations": sorted({v["code"] for v in violations}),
                  "snapshots": snapshots}
        return record, {"canary_in_transcript"} if hits else set(), set()

    def _denials_check(self, live, rid):
        """Sandbox denials over the launch window (log show; a 60 s wall bound). Best effort (F14). The window is
        machine-wide, so the count is split by the launch's own pids (E-213): its journaled leader and any process a
        census of it found."""
        records = read_journal(self.run_dir(rid) / "journal.jsonl")
        launched = [r["time_utc"] for r in records if r["state"] == "launched"]
        pids = {r["details"].get("pid") for r in records if r["state"] == "process_started"}
        for r in records:
            if r["state"] == "interrupted_crash":
                pids.update((r["details"].get("census") or {}).get("found") or [])
        found = live.sandbox_denials(launched[-1] if launched else utc_now(), utc_now(),
                                     launch_pids=sorted(p for p in pids if type(p) is int))
        return found, set(), set() if found.get("available") else {"sandbox_denials_unavailable"}

    # -- sealing
    def _seal(self, run):
        rid = run["run_id"]
        rdir = self.run_dir(rid)
        journal = rdir / "journal.jsonl"
        records = read_journal(journal)
        last = {r["state"]: r for r in records}
        info = {}
        for record in records:
            info.update({k: v for k, v in record["details"].items()
                         if k in ASSIGNMENT_KEYS + ("executor_id", "profile_sha256")})
        ws = self.subjects_root / self.opaque(rid)
        arm_manifest = self.manifest["arms"][run["arm"]]
        prompt = self.prompt(run, ws).encode()
        flags = {"sandbox_none_test_only"} if self.host["sandbox"] == "none_test_only" else set()
        files = {"prompt.txt": prompt, "treatment_manifest.json": _pretty(arm_manifest)}
        reason, violations = None, []
        closing = last.get("not_started") or last.get("exited") or last.get("interrupted_crash")
        require(closing is not None, f"{rid}: sealing a run the journal never closed")
        if closing["details"].get("broker_stop_error"):
            flags.add("broker_stop_failed")
        if closing["details"].get("code_drift"):
            flags.add(CODE_DRIFT_FLAG)
        flags.update(closing["details"].get("coordinator_flags") or [])   # a real host's post-run checks
        ended = closing["time_utc"]
        if "not_started" in last:
            status, reason, started = "not_started", closing["details"]["reason"], ended
        else:
            launched = last["launched"]
            started = launched["time_utc"]
            if _utc_seconds(ended) < _utc_seconds(started):   # the wall clock stepped back during the run: the
                ended = started                                # journal order stands, the record stays sealable
                flags.add(CLOCK_FLAG)
            host_dir = rdir / "host"
            result_path = host_dir / "adapter_result.json"
            stored = canonical.strict_load(result_path) if result_path.is_file() else None
            census_record = None
            if "exited" in last:
                require(stored is not None, f"{rid}: exited without a recorded adapter result")
                result = stored
                if self.host["adapter"] == "fake" and result["host_version"] != self.host["version"]:
                    flags.add("host_version_mismatch")
            else:
                census_record = closing["details"]["census"]
                flags.add(closing["details"]["cause"])
                result = self._lost_result(closing["details"], stored)
            status = LOST_HINT if census_record is not None else result["status_hint"]
            files.update(self._host_files(host_dir, result, prompt, ws, launched, census_record, flags,
                                          started="process_started" in last))
            output, violations = self._output_files(ws, flags)
            files.update(output)
        if self.real:
            files.update(self._live_files(rdir / "host", launched=status != "not_started"))
        files.update(self._broker_files(rid, flags, arm_manifest))
        if status != "not_started" and "broker/custody.jsonl" not in files:
            flags.add("custody_missing")
        record = {"schema_version": 1, "run_id": rid, "campaign_id": self.manifest["campaign_id"],
                  "campaign_kind": self.manifest["kind"], "task_id": run["task_id"], "seed": run["seed"],
                  "arm": run["arm"], "opaque_handle": self.opaque(rid), "adapter": self.host["adapter"],
                  "synthetic": self.manifest["kind"] == "synthetic" or self.host["adapter"] == "fake",
                  "executor_id": None if status == "not_started" else info.get("executor_id"),
                  "behavior": info.get("behavior") if self.host["adapter"] == "fake" else None,
                  "behavior_plan_sha256": info.get("behavior_plan_sha256") if self.host["adapter"] == "fake" else None,
                  "started_utc": started, "ended_utc": ended, "status_hint": status, "not_started_reason": reason,
                  "treatment_manifest_sha256": canonical.digest(arm_manifest),
                  "prompt_sha256": canonical.sha256_bytes(prompt),
                  "profile_sha256": None if status == "not_started" else info.get("profile_sha256"),
                  "validity_flags": sorted(flags)}
        validate_run_record(record)
        files["run.json"] = _pretty(record)
        sealed, manifest_path = rdir / "sealed", rdir / "evidence_manifest.json"
        for path in (sealed, manifest_path):   # a seal the coordinator never journaled is set aside, not reused
            if os.path.lexists(path):
                _set_aside(path)
        for relative, data in sorted(files.items()):
            canonical.write_once(sealed / relative, data)
        entries = canonical.tree_manifest(sealed)
        digest = canonical.digest(entries)
        canonical.make_read_only(sealed)
        canonical.write_once(manifest_path, _pretty(entries))
        _record(journal, "sealed", evidence_sha256=digest, files=len(entries), output_violations=violations)
        return {"run_id": rid, "action": "sealed", "status_hint": status, "evidence_sha256": digest}

    def _lost_result(self, crash, stored) -> dict:
        """The coordinator-authored AdapterResult of a lost launch (run.json status_hint interrupted;
        AdapterResult has no such value, so its own status_hint is launch_error): nothing observed
        (null exit, time and cost unless synthetic), the cause, note and census in details. An
        adapter result written but never journaled ``exited`` is kept whole in details and its
        final text sealed (it still counts as delivered)."""
        census_record, fake = crash["census"], self.host["adapter"] == "fake"
        flags = ["survivors_after_kill"] if census_record["survivors"] else []
        if stored is not None:
            flags += [f for f in stored["validity"]["invalidating"] if f not in flags]
        result = AdapterResult(
            adapter=self.host["adapter"], status_hint="launch_error", exit_code=None, wall_seconds=None,
            raw_stdout="stdout.jsonl", raw_stderr="stderr.txt", events=[], parse_errors=[], session_ids=[],
            final_text=stored.get("final_text") if stored else None,
            cost={"usd": 0.0 if fake else None, "provenance": self.host["cost_source"], "semantics": "unknown"},
            usage=None, subagents=[], permission_denials=[], host_version=None,
            synthetic=self.manifest["kind"] == "synthetic" or fake,
            details={"authored_by": "coordinator", "cause": crash["cause"], "note": crash["note"],
                     "error": crash.get("error"), "census": census_record, "launch": {},
                     "unjournaled_adapter_result": stored, "flags": flags})
        return result.as_dict()

    def _host_files(self, host_dir, result, prompt, ws, launched, census_record, flags, *, started=False) -> dict:
        files = {"adapter_result.json": _pretty({**result, "raw_stdout": "stdout.jsonl", "raw_stderr": "stderr.txt"})}
        flags.update(result["validity"]["invalidating"])
        for name in ("stdout.jsonl", "stderr.txt"):
            path = host_dir / name
            if path.is_file() and not path.is_symlink():
                files[name] = path.read_bytes()
            else:
                files[name] = b""
                flags.add("raw_streams_missing")
        files["final_text.txt"] = (result.get("final_text") or "").encode()
        stdin = host_dir / "stdin.txt"
        if stdin.is_file() and stdin.read_bytes() != prompt:
            flags.add("stdin_mismatch")
        call_path = host_dir / "launch_call.json"
        call = canonical.strict_load(call_path) if call_path.is_file() else None
        if call is None:   # argv and env names unknown: sealed as [] (the layout's lists), never guessed
            flags.add("launch_unrecorded")
        else:
            try:
                assert_prompt_not_in_argv(call["argv"], prompt.decode())
            except ContractError:
                flags.add("prompt_in_argv")
        launch = result["details"].get("launch") or {}
        if census_record is None:
            survivors, killed = launch.get("survivors"), launch.get("killed")
        else:   # a lost launch: the census, not a launcher, looked for and killed subject processes
            survivors, killed = census_record["survivors"], bool(census_record["killed"])
            if census_record["found"]:   # the subject ran on after the coordinator lost it
                flags.add("subject_outlived_coordinator")
            if not census_record["complete"]:   # the census could not search: survivors are unknown
                flags.add("census_incomplete")
                survivors = None
            elif census_record.get("precensus_incomplete"):   # E-212: an earlier look could not search
                flags.add("census_incomplete")
        if survivors:
            flags.add("survivors_after_kill")
        if launch.get("census_complete") is False:   # the sandbox census became unusable mid-launch: an
            flags.add("census_incomplete")           # escapee outside the group was unseen, survivors unknown
            survivors = None
        # System V IPC residue (adapters.base docstring: an invalidating flag, which makes the audit's
        # unsupported_claim null): a subject that may have run under a profile needs its launcher's report of an
        # empty residue. Unknown for a lost launch (census_launch lists no IPC objects; a killed coordinator removed
        # none) and for a launch_error after the launch call, unless its error is one isolation.launch raises before
        # any child exists (the process start may have happened without its journal record: on_start can fail).
        if launched["details"].get("profile_sha256") is not None and (started or call is not None):
            if census_record is not None:
                flags.add("ipc_residue")
            elif result["status_hint"] == "launch_error" and not started:
                if not _before_start(launch.get("error")):
                    flags.add("ipc_residue")
            elif ipc_residue_flagged(launch):
                flags.add("ipc_residue")
        record = {"argv": call["argv"] if call else [], "env_names": call["env_names"] if call else [],
                  "cwd_opaque": _opaque_path(call["cwd"], ws) if call else None,
                  "timeout_s": call["timeout_s"] if call else launched["details"].get("timeout_s"),
                  "exit_code": result["exit_code"], "timed_out": launch.get("timed_out"), "killed": killed,
                  "survivors": survivors, "wall_seconds": result["wall_seconds"]}
        validate_launch_record(record)
        files["launch.json"] = _pretty(record)
        return files

    def _output_files(self, ws, flags):
        if not os.path.lexists(ws):
            return {}, []
        data, violations = isolation.read_output_tree(ws / "output")
        if violations:
            flags.add("subject_output_violations")
        return {f"subject_output/{Path(rel).as_posix()}": content for rel, content in data.items()}, violations

    def _broker_files(self, run_id, flags, arm_manifest=None) -> dict:
        """The broker's custody log and artifacts, the kernel's stage receipts (M5:
        ``broker/ravel-runs/<16 hex>/execution_state.json``, checked against the frozen kernel source, interpreter
        and stage workers) and, for a real host, the task client's environment-name reports (LC-11)."""
        root, files = self.dir / "broker" / run_id, {}
        custody = root / "custody.jsonl"
        if custody.is_file() and not custody.is_symlink():
            files["broker/custody.jsonl"] = custody.read_bytes()
            if canonical.read_jsonl(custody)[1] is not None:
                flags.add("custody_malformed")
        artifacts = root / "artifacts"
        if artifacts.is_dir() and not artifacts.is_symlink():
            for path in sorted(artifacts.iterdir()):
                require(stat.S_ISREG(path.lstat().st_mode), f"broker artifact {path.name} is not a regular file")
                files[f"broker/artifacts/{path.name}"] = path.read_bytes()
        runs = root / RECEIPTS
        if runs.is_dir() and not runs.is_symlink():
            for rundir in sorted(runs.iterdir()):
                receipt = rundir / "execution_state.json"
                if rundir.is_dir() and not rundir.is_symlink() and receipt.is_file() and not receipt.is_symlink():
                    files[f"broker/{RECEIPTS}/{rundir.name}/execution_state.json"] = receipt.read_bytes()
        if arm_manifest is not None:
            workers = {e["path"]: e["sha256"] for e in self.environment["harness_code"]
                       if e["path"].startswith("stages/")}
            flags.update(receipt_flags({k: v for k, v in files.items() if k.startswith(f"broker/{RECEIPTS}/")},
                                       arm_manifest["common"], workers))
        reports = root / "client_env.jsonl"
        if self.real and reports.is_file() and not reports.is_symlink():
            files["broker/client_env.jsonl"] = reports.read_bytes()
        return files

    def _live_files(self, host_dir, *, launched) -> dict:
        """A real host's coordinator records sealed with its run: the proxy log (empty when there were no requests,
        always for a launched run), the redaction manifest when anything was redacted, the host-state manifest."""
        files = {}
        for name, always in (("proxy.jsonl", launched), (REDACTIONS, False), (HOST_STATE_MANIFEST, False)):
            path = host_dir / name
            if path.is_file() and not path.is_symlink():
                files[name] = path.read_bytes()
            elif always:
                files[name] = b""
        return files


def receipt_findings(receipts: dict, common: dict, workers=None) -> list:
    """(flag, where) for every stage receipt that does not match the frozen treatment (M5): the kernel source
    digest over the receipt's ``src/ravel/**/*.py`` snapshot entries against ``common.kernel_source_sha256``
    (kernel_fingerprint_mismatch), the interpreter entry (the one absolute entry that is neither a Python source
    nor inside the RAVEL run directory) against ``common.interpreter_sha256`` (interpreter_mismatch) and, when
    ``workers`` ({"stages/<name>.py": sha256}) is given, each stage worker against it (stage_worker_mismatch).
    A receipt that does not parse is kernel_fingerprint_mismatch too. Shared rule: audit.py restates it."""
    found = []
    for name, data in sorted(receipts.items()):
        try:
            state = canonical.strict_loads(data.decode("utf-8"))
            stages_ = state["stages"]
            require(isinstance(stages_, dict), "stages: object required")
        except (UnicodeDecodeError, ValueError, KeyError, TypeError, ContractError):
            found.append(("kernel_fingerprint_mismatch", f"{name}: unreadable receipt"))
            continue
        for stage, record in sorted(stages_.items()):
            where = f"{name}#{stage}"
            snapshot = record.get("input_snapshot") if isinstance(record, dict) else None
            if not isinstance(snapshot, dict):
                found.append(("kernel_fingerprint_mismatch", f"{where}: no input snapshot"))
                continue

            def sha_of(entry):
                files_ = entry.get("files") if isinstance(entry, dict) else None
                return files_[0].get("sha256") if isinstance(files_, list) and len(files_) == 1 \
                    and isinstance(files_[0], dict) else None
            kernel = sorted(({"path": "src/ravel/" + key.rsplit("/src/ravel/", 1)[1], "sha256": sha_of(entry)}
                             for key, entry in snapshot.items() if "/src/ravel/" in key and key.endswith(".py")),
                            key=lambda e: e["path"])
            if not kernel or canonical.digest(kernel) != common["kernel_source_sha256"]:
                found.append(("kernel_fingerprint_mismatch", where))
            interpreters = [sha_of(entry) for key, entry in snapshot.items()
                            if not key.endswith(".py") and f"/{RECEIPTS}/" not in key]
            if interpreters != [common["interpreter_sha256"]]:
                found.append(("interpreter_mismatch", where))
            if workers is not None:
                for key, entry in snapshot.items():
                    tail = key.rsplit("/benchmarks/governance/", 1)[-1] if "/benchmarks/governance/stages/" in key \
                        else None
                    if tail is not None and workers.get(tail) != sha_of(entry):
                        found.append(("stage_worker_mismatch", f"{where}: {tail}"))
    return found


def receipt_flags(receipts, common, workers=None) -> set:
    return {flag for flag, _ in receipt_findings(receipts, common, workers)}


HOST_STATE_CAP = 64 << 20                 # bytes of a real host's streams and state one post-run scan reads (M9)
HOST_STATE_MANIFEST = "host_state.json"  # runs/<id>/host/: {files: [{path, bytes, sha256}], violations}, sealed
REDACTIONS = "redactions.json"           # runs/<id>/host/: the redaction manifest (WI-5), sealed when present
HOST_CONFIG_CAP = 4 << 20                # bytes of the host's .claude.json whose key names a post-run check lists
CREDENTIAL_SHAPED = re.compile(r"token|secret|oauth|credential|api_?key|password|bearer|auth", re.IGNORECASE)
# Credential variables no task-client report may list (LC-11): the host's token, its fd variant, the API credentials.
CREDENTIAL_VISIBLE_NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "ANTHROPIC_API_KEY",
                            "ANTHROPIC_AUTH_TOKEN")
PROXY_ATTRIBUTION_REASONS = ("subject_client", "owner_unknown")


def proxy_summary(decisions, *, stop_error=None, late=0) -> dict:
    """The journaled summary of one launch's proxy decisions (WI-4): requests, allowed {target: n}, denied
    [{target, reason, n}], the non-owner clients, the errors, the stop error and decisions after stop."""
    allowed, denied = {}, {}
    for d in decisions:
        if d["decision"] == "allow":
            allowed[d["target"]] = allowed.get(d["target"], 0) + 1
        elif d["decision"] == "deny":
            key = (d["target"], d["reason"])
            denied[key] = denied.get(key, 0) + 1
    return {"requests": len(decisions), "allowed": dict(sorted(allowed.items(), key=lambda kv: str(kv[0]))),
            "denied": [{"target": t, "reason": r, "n": n}
                       for (t, r), n in sorted(denied.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))],
            "subject_clients": sum(1 for d in decisions if d["reason"] == "subject_client"),
            "errors": [{"target": d["target"], "reason": d["reason"]} for d in decisions if d["decision"] == "error"],
            "stop_error": stop_error, "late_decisions": late}


def proxy_flags(summary) -> tuple:
    """(sealed flags, informational flags) of a proxy summary (WI-4): a deny of the host's own request
    (proxy_denied_connect) or of an unattributable client (proxy_owner_unknown) is S3; an upstream failure or a
    proxy that did not stop cleanly is S7; a non-owner client (subject_network_attempt) is an outcome."""
    flags, info = set(), set()
    reasons = [d["reason"] for d in summary["denied"]]
    if any(r not in PROXY_ATTRIBUTION_REASONS for r in reasons):
        flags.add("proxy_denied_connect")
    if "owner_unknown" in reasons:
        flags.add("proxy_owner_unknown")
    if summary["errors"]:
        flags.add("proxy_upstream_error")
    if summary["stop_error"] or summary["late_decisions"]:
        flags.add("proxy_stop_failed")
    if summary["subject_clients"]:
        info.add("subject_network_attempt")
    return flags, info


def _canonical_uuid(value) -> bool:
    try:
        return isinstance(value, str) and value == str(uuid.UUID(value))
    except ValueError:
        return False


def _bound_call_problems(argv, env, added, expected) -> list:
    """M6: a real host's launch call against its build-time binding (``_launch_call_problems``)."""
    from . import live
    binding, per_run, problems = expected["binding"], expected["per_run_env"], []
    at = [i for i, a in enumerate(argv) if a == "--session-id"]
    if len(at) != 1 or at[0] + 1 >= len(argv) or not _canonical_uuid(argv[at[0] + 1]):
        problems.append("the launch argv must carry exactly one --session-id followed by a canonical uuid")
    elif argv[:at[0] + 1] + [PLACEHOLDER_SESSION] + argv[at[0] + 2:] != binding["argv"]:
        problems.append("the launch argv differs from the host binding written at build")
    names = set(binding["extra_env"]) | set(per_run)
    if added != names:
        problems.append(f"the added variables differ from the binding: extra {sorted(added - names)}, missing "
                        f"{sorted(names - added)}")
    for name, value in binding["extra_env"].items():
        if name in env and env[name] != value:
            problems.append(f"{name} differs from its bound value")
    for name, value in per_run.items():
        if name in env and env[name] != value:
            problems.append(f"the per-run {name} is not the coordinator's {value}")
    never = live.never_present(env)
    if never:
        problems.append(f"the launch environment holds names that never reach a real host: {never}")
    return problems


def _opaque_path(path, ws) -> str:
    path, root = os.path.realpath(path), os.path.realpath(ws)
    return SUBJECT_ROOT + path[len(root):] if _within(path, root) else path


# launch_error causes that isolation.launch raises before any child exists (launch_host records them as "<type>:
# <message>"): the System V listing failed, the profile or its census was refused, or an argument check failed. Any
# other cause after the launch call (an on_start journal write that failed after the start, a stream-copy failure,
# an error this list does not name) leaves the subject's System V residue unknown.
BEFORE_START_ERRORS = ("IpcUnavailable: ",) + tuple(f"ContractError: {message}" for message in (
    "launch: profile must be a deny-default SBPL profile", "launch: sandbox-exec is unavailable",
    "launch: the sandbox process census (sandbox_check) is unavailable", "launch: profile rejected by sandbox-exec",
    "launch: profile does not deny reading a coordinator-private file", "launch: argv must be a nonempty list",
    "launch: argv[0] must be an absolute path to an executable file", "launch: env must be an explicit dict",
    "launch: cwd is not a directory", "launch: timeout_s must be a positive finite number",
    "launch: on_start must be callable or None", "launch: stdout_path and stderr_path must differ",
    "launch: output files must not exist", "launch: stdin_path is not a file", "cwd: ", "output path: ",
    "stdin_path: "))


def _before_start(error) -> bool:
    return isinstance(error, str) and error.startswith(BEFORE_START_ERRORS)


def _set_aside(path):
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    n = 1
    while os.path.lexists(path.with_name(f"{path.name}.incomplete-{n}")):
        n += 1
    os.rename(path, path.with_name(f"{path.name}.incomplete-{n}"))


# ---------------------------------------------------------------- run, outcomes, report

class CredentialPause(ContractError):
    """The run-start credential validation failed (smoke spec R8): the invocation pauses. Nothing is journaled for
    the assignment that was about to start and no stop is written; fix the credential file and run again."""


def core_limit_problem():
    """None when the hard core-file limit is 0 (a crashing host dumps no memory, token included: R12e)."""
    soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
    return None if hard == 0 else (f"the hard core-file limit is {hard} (soft {soft}), not 0: run under "
                                   "`ulimit -Hc 0` or through cli.py run, which sets it")


def read_stop(campaign_dir):
    """coordinator/stop.json (validated), or None. A malformed stop record fails closed (never ignored)."""
    path = Path(campaign_dir) / COORDINATOR / STOP_FILE
    if not os.path.lexists(path):
        return None
    require(path.is_file() and not path.is_symlink(), f"coordinator/{STOP_FILE}: not a regular file")
    record = canonical.strict_load(path)
    require(isinstance(record, dict) and set(record) == set(STOP_FIELDS) and record["schema_version"] == 1
            and isinstance(record["rule"], str) and isinstance(record["reason"], str)
            and isinstance(record["set_by"], str) and (record["run_id"] is None or canonical.is_sha256(record["run_id"])),
            f"coordinator/{STOP_FILE}: not a stop record ({sorted(STOP_FIELDS)}); a human must repair it")
    return record


def record_stop(campaign_dir, *, run_id, rule, reason, set_by) -> tuple:
    """(stop record, written): write coordinator/stop.json exactly once, atomically and exclusively (the record is
    written to a private temporary file and hard-linked into place, which fails if a stop is already there, so a human
    stop and an automated one can never overwrite each other); ``written`` is False when another stop was first, and
    the record returned is then that one. A campaign under a stop never launches again (a repaired configuration is a
    new campaign with its own approval)."""
    record = {"schema_version": 1, "time_utc": utc_now(), "run_id": run_id, "rule": rule, "reason": reason,
              "set_by": set_by}
    written = write_exclusive(Path(campaign_dir) / COORDINATOR / STOP_FILE, _pretty(record))
    return read_stop(campaign_dir), written


def write_exclusive(target, data: bytes) -> bool:
    """Write ``data`` to ``target`` once, atomically and exclusively: a private temporary file in the same directory,
    fsynced, made read-only (0444) and hard-linked into place, which fails when ``target`` exists. Returns whether this
    call wrote it (False: another writer was first, and nothing changed)."""
    target = Path(target)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o444)
        try:
            os.link(tmp, target)
            return True
        except FileExistsError:
            return False
    finally:
        os.unlink(tmp)


def write_stop(campaign_dir, *, run_id, rule, reason, set_by) -> dict:
    """record_stop that refuses when a stop is already in place (ContractError, nothing changed)."""
    stop, written = record_stop(campaign_dir, run_id=run_id, rule=rule, reason=reason, set_by=set_by)
    require(written, f"coordinator/{STOP_FILE}: refusing to overwrite the stop already in place ({stop['rule']})")
    return stop


def run_campaign(campaign_dir, *, adapter_factory=None, behavior_plan=None, only=None, limit=None) -> dict:
    """Process the registry's assignments in order (or the subset ``only``, still in registry order).

    ``adapter_factory(assignment)`` returns the Adapter for one run (default: the host's,
    ``adapter_factory_for``); ``assignment`` carries run_id, task_id, seed, behavior, python (the
    subject interpreter), launcher (the coordinator's recording launcher, which the adapter must
    use: a run whose adapter holds another launcher is not started) and, for a real host,
    host_state_dir. The arm is never passed: everything arm-dependent (the fake host's behavior) is
    resolved here, and a real host must launch identically in every run (``host_binding``, the
    binding written at build in ``coordinator/host_binding.json``). ``behavior_plan`` (fake host only)
    is {"default": behavior, "by_task_arm": {"<task_id>|<arm>": behavior}}.

    Before each launch the run's treatment is re-verified against the frozen campaign (the code
    behind every common hash, the frozen texts, the prompt's instruction segment, the request, the
    materialized workspace; ``admitted.verified`` in the journal) and a drifted run is not started;
    after it, a drift is flagged ``code_drift_during_run``. A failure before the recording launcher
    was called (no launch call and no process start on record) is not_started with no charge.

    ``limit`` processes at most that many unsealed assignments and leaves the rest untouched (a pause,
    never a stop). ``coordinator/stop.json`` (an automated stop rule or ``cli.py stop``) closes every
    remaining assignment not_started with charge 0 instead of launching it (``close_stopped``); a launch
    resumed there is still evaluated, so its triggers are recorded beside the stop in place (E-95). A real
    host also needs, before any assignment: every lost or unclean probe launch censused, and none left
    unclean (E-96), every lost run launch censused by its journaled start, and none left unclean (E-206: before
    preflight, so a preflight that fails never leaves one running), a passing preflight, the run-start
    credential validation (CredentialPause: nothing
    journaled, no stop), a hard core-file limit of 0 and the behavioral gate (the latest record,
    re-derived: M1); before each new assignment the S10a gate (``live.go_no_go_problem``: once run 1 was
    launched, no further run launches until its recorded go; a hold, reported as ``paused`` with
    ``held`` true: E-92) and the credential again (a pause); after each sealed run its live checks are
    written and the stop rules evaluated (``live.stop_reason``): the first trigger writes stop.json once.

    Stop evaluation is idempotent across invocations (E-78): before anything else a real host's campaign re-derives
    the stop rules of every sealed run (``live.derive_stops``), so a stop lost between a seal and its stop.json (a
    SIGHUP, Ctrl-C, a crash, an exception in the live checks) is written now and nothing launches; an evaluation that
    raises is an S7 stop (fail closed). A trigger that finds a stop already in place (a human stop written meanwhile)
    is recorded in ``triggers`` (and the run's live_checks.json), never lost and never an error. ``only`` is refused
    for a real host: it would skip an earlier lost launch, its census, charge and stop (E-79).
    """
    campaign = _Campaign(campaign_dir)
    require(limit is None or (type(limit) is int and limit > 0), "limit: a positive integer or None")
    require(only is None or not campaign.real, "only: refused for a real host (every run is processed in registry "
                                               "order, so an earlier lost launch is always resumed and charged first)")
    factory = adapter_factory if adapter_factory is not None else adapter_factory_for(campaign)
    runs = campaign.registry["runs"]
    if only is not None:
        wanted = set(only)
        unknown = sorted(wanted - {r["run_id"] for r in runs})
        require(not unknown, f"only: not assignments of this campaign: {unknown}")
        runs = [r for r in runs if r["run_id"] in wanted]
    live, triggers = None, []

    def apply(run_id, trigger, action=None):
        """Write the stop of one fired trigger, or record it beside the stop already in place."""
        stop, written = record_stop(campaign.dir, run_id=run_id, rule=trigger["rule"], reason=trigger["reason"],
                                    set_by="live.stop_reason")
        triggers.append({"run_id": run_id, "rule": trigger["rule"], "reason": trigger["reason"], "written": written,
                         **({"action": action} if action else {})})
        return stop

    # One coordinator per campaign: two would both find an empty journal and launch the same run.
    with campaign_lock(campaign.dir):
        if campaign.real:
            from . import live
            for derived in live.derive_stops(campaign.dir):   # before any launch or gate: never skip a lost stop
                if derived["stop"] is not None:
                    apply(derived["run_id"], derived["stop"], derived.get("action"))
        stop = read_stop(campaign.dir)
        if campaign.real and stop is None:   # a real subject never meets an unverified gate (§12.3, R0.1)
            unclean = live.census_problems(live.census_lost_probes(campaign.dir))
            require(not unclean, f"refusing to launch a real host: probe launches {unclean} left survivors or could "
                                 f"not be censused: {live.PROBE_CENSUS_REMEDY}")
            unclean = live.census_problems(live.census_lost_runs(campaign))   # E-206: before preflight can fail
            require(not unclean, f"refusing to launch a real host: lost run launches {unclean} left survivors or "
                                 f"could not be censused: {live.RUN_CENSUS_REMEDY}")
            checked = live.preflight(campaign.dir, campaign=campaign)
            failed = [f"{c['id']}: {c['detail']}" for c in checked["checks"] if not c["ok"]]
            require(checked["ok"], "refusing to launch a real host: preflight failed: " + "; ".join(failed))
            live.validate_credential(campaign.dir)
            problem = core_limit_problem()
            require(problem is None, f"refusing to launch a real host: {problem}")
            problem, campaign.behavioral_sha256 = behavioral_record(campaign.dir, campaign.campaign_sha256,
                                                                    campaign.manifest["arms"])
            require(problem is None, f"refusing to launch a real host: {problem}")
        plan, plan_sha = campaign.plan(behavior_plan)
        results, processed, paused, held = [], 0, None, False

        def evaluate(run_id):
            """The stop rules of one freshly sealed run: its live checks written, a trigger applied."""
            try:
                checks = live.live_checks(campaign.dir, run_id)
                trigger, action = checks["stop"], checks.get("action")
            except Exception as exc:   # noqa: BLE001 - an evaluation that cannot run stops the campaign (S7)
                trigger, action = live.evaluation_failed(run_id, exc), None
            return None if trigger is None else apply(run_id, trigger, action)

        for run in runs:
            stop = stop or read_stop(campaign.dir)
            if stop is not None:
                journal = read_journal(campaign.run_dir(run["run_id"]) / "journal.jsonl")
                outcome = campaign.close_stopped(run, stop)
                results.append(outcome)
                # E-95: a launch resumed under a stop (sealed interrupted by close_stopped) is evaluated like any
                # sealed run, so its credential findings are recorded beside the stop in place and print REVOKE
                if campaign.real and outcome["action"] == "sealed" and any(r["state"] == "launched" for r in journal):
                    evaluate(run["run_id"])
                continue
            journal = read_journal(campaign.run_dir(run["run_id"]) / "journal.jsonl")
            if not any(r["state"] == "sealed" for r in journal):
                if limit is not None and processed >= limit:
                    paused = f"limit {limit} reached; the remaining assignments are untouched"
                    break
                if campaign.real and not journal:
                    problem = live.go_no_go_problem(campaign.dir)   # E-92: run 1 is reviewed before run 2 launches
                    if problem is not None:
                        paused, held = problem, True
                        break
                    live.validate_credential(campaign.dir)   # before _start journals anything: a pause
            outcome = campaign.process(run, plan, plan_sha, factory)
            results.append(outcome)
            if outcome["action"] != "skipped":
                processed += 1
            if campaign.real and outcome["action"] == "sealed":
                stop = evaluate(run["run_id"]) or stop
    return {"campaign_dir": str(campaign.dir), "synthetic": campaign.manifest["kind"] == "synthetic",
            "behavior_plan_sha256": plan_sha, "runs": results, "spent": campaign.spent(), "stopped": stop,
            "paused": paused, "held": held, "triggers": triggers}


# ---------------------------------------------------------------- behavioral treatment check (§12.3)

def _probe_claim(claim_id, field, text, content, handle):
    key, index, role, quantile, unit, _ = guard.field_spec(field)
    value = content[key] if index is None else content[key][index]
    return {"schema_version": 1, "claim_id": claim_id, "status": "final", "text": text,
            "quantity": format(value, ".10g"), "unit": unit, "role": role, "expected_quantile": quantile,
            "artifact_field": field, "evidence_ids": [handle], "qualifiers": ["behavioral treatment probe"]}


def _probe_submission(conversion, handle) -> dict:
    """The observed and median expected sigma_vis of one conversion, cited to it (a probe, not a subject)."""
    claims = [_probe_claim("probe-observed", "sigma_vis_obs_fb", "Observed visible cross-section limit",
                           conversion, handle),
              _probe_claim("probe-median-expected", "sigma_vis_exp_fb[2]",
                           "Median expected visible cross-section limit", conversion, handle)]
    text = "\n".join(["Behavioral treatment probe."] + [f"{c['text']}: {c['quantity']} fb" for c in claims])
    return {"claims": claims, "report_text": text, "refusal": None, "final": True}


def _call(opener, endpoint, token, op, args) -> dict:
    """One broker operation over its HTTP protocol (§6), as the subject client makes it."""
    request = urllib.request.Request(endpoint, data=json.dumps({"op": op, "args": args}).encode(), method="POST",
                                     headers={TOKEN_HEADER: token, "Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=1200) as response:
            data = canonical.strict_loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        data = canonical.strict_loads(exc.read().decode("utf-8"))
    require(isinstance(data, dict) and data.get("ok") is True, f"behavioral probe: {op} failed: {data}")
    return data["result"]


def behavioral_check(campaign_dir) -> dict:
    """The behavior half of the §12.3 treatment identity check, as a product check (R0.1).

    One real broker per arm, run with that arm's frozen guard mode and feedback, the campaign's
    budgets, stage interpreter and environment and one shared secret, on the task whose conversion
    alone is stale (reuse_expectation recompute_convert: the luminosity changed). Each receives the
    SAME two submissions over its HTTP protocol: a stale probe citing the prior conversion and a
    clean probe citing a fresh conversion of the prior fit with the current luminosity. The custody
    records go through ``treatment.probe_from_custody`` and ``treatment.behavioral_diff`` (primary
    2x2): a no-op, detect-only or arm-dependent guard, a false block or subject-visible content
    beyond the declared feedback fails, which the manifest check (``treatment_diff``) cannot see.
    The brokers' custody and artifacts and ``result.json`` (observations, verdict, the campaign's
    sha256) are kept under ``coordinator/behavioral/<n>/``. Never calls a model; the kernel runs."""
    campaign_dir = Path(campaign_dir).resolve()
    with campaign_lock(campaign_dir):
        campaign = _Campaign(campaign_dir)
        task = next((t["task_id"] for t in campaign.index["tasks"] if t.get("reuse_expectation") == PROBE_REUSE), None)
        require(task is not None, f"behavioral check: the family has no {PROBE_REUSE} task to probe")
        parent = campaign.dir / COORDINATOR / BEHAVIORAL
        parent.mkdir(mode=0o700, exist_ok=True)
        n = 1
        while os.path.lexists(parent / str(n)):
            n += 1
        root = parent / str(n)
        root.mkdir(mode=0o700)
        by_kind, recipe = campaign.broker_inputs(task), campaign.definition(task)["prior_recipe"]
        secret, arms = secrets.token_bytes(32), list(contracts.ARMS)

        def prepare(arm):
            setting = campaign.manifest["arms"][arm]["guard"]
            broker = Broker(root / arm, guard_mode=setting["mode"], feedback=setting["feedback"],
                            budgets={name: campaign.budget[name] for name in BROKER_BUDGET},
                            python=campaign.config["stage_python"], env=campaign.config["stage_env"], secret=secret)
            broker.register_inputs(by_kind["current"])
            broker.create_prior(by_kind["prior"], recipe=recipe)
            return broker

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(arms)) as pool:
            futures = {arm: pool.submit(prepare, arm) for arm in arms}
        brokers = {arm: future.result() for arm, future in futures.items()}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 127.0.0.1 only, never a proxy
        observations = {}
        for arm in arms:
            endpoint, token = brokers[arm].start()
            try:
                listed = _call(opener, endpoint, token, "inputs", {})
                current = {e["kind"]: e["handle"] for e in listed["current"]}
                prior = {e["kind"]: e["handle"] for e in listed["prior"]}
                stale = _call(opener, endpoint, token, "show", {"handle": prior["conversion"]})["content"]
                fresh = _call(opener, endpoint, token, "convert", {"fit": prior["fit"],
                                                                   "luminosity": current["luminosity"]})
                for submission in (_probe_submission(stale, prior["conversion"]),
                                   _probe_submission(fresh, fresh["handle"])):
                    _call(opener, endpoint, token, "submit", submission)
            finally:
                brokers[arm].stop()
            submits = [line for line in canonical.read_jsonl(brokers[arm].custody_path())[0]
                       if line["op"] == "submit" and line["ok"]]
            require(len(submits) == 2, f"behavioral probe: {arm} custody holds {len(submits)} submit calls, not 2")
            observations[arm] = {"stale": treatment.probe_from_custody(submits[0]),
                                 "clean": treatment.probe_from_custody(submits[1])}
        verdict = treatment.behavioral_diff(observations)
        record = {"schema_version": 1, "campaign_id": campaign.manifest["campaign_id"],
                  "campaign_sha256": campaign.campaign_sha256, "task_id": task,
                  "arms": {arm: dict(campaign.manifest["arms"][arm]["guard"]) for arm in arms},
                  "observations": observations, "result": verdict}
        path = root / "result.json"
        canonical.write_once(path, _pretty(record))
    return {"ok": verdict["ok"], "violations": verdict["violations"], "differences": verdict["differences"],
            "task_id": task, "record": str(path)}


NO_BEHAVIORAL = "no behavioral treatment check was recorded (cli.py treatment-diff --behavioral)"


def _numbered(parent) -> list:
    """(n, path) of the numbered subdirectories of ``parent`` in numeric order ("10" after "2")."""
    if not parent.is_dir() or parent.is_symlink():
        return []
    return sorted((int(p.name), p) for p in parent.iterdir()
                  if p.name.isdigit() and p.name == str(int(p.name)) and p.is_dir() and not p.is_symlink())


def behavioral_record(campaign_dir, campaign_sha256, arms=None) -> tuple:
    """(problem, record sha256): the stricter treatment gate (H-11, E-48, M1). Only the LATEST behavioral check
    (``coordinator/behavioral/<n>/``, the largest n in numeric order) counts: its result.json must parse strictly,
    name this campaign.json's sha256, pass, record the arms' guards exactly as ``arms`` (the manifest's arms, when
    given) freeze them, and re-derive from its own custody: two successful submits per arm through
    ``treatment.probe_from_custody`` and ``treatment.behavioral_diff`` must give exactly its observations and
    verdict (a hand-written passing result fails). (None, sha256 of result.json) when it holds."""
    parent = Path(campaign_dir) / COORDINATOR / BEHAVIORAL
    numbered = _numbered(parent)
    if not numbered:
        return NO_BEHAVIORAL, None
    n, root = numbered[-1]
    label = f"coordinator/{BEHAVIORAL}/{n}"
    unpassed = (f"the latest behavioral treatment check ({label}) is not a passing behavioral treatment check of "
                "this campaign.json (cli.py treatment-diff --behavioral)")
    path = root / "result.json"
    try:
        require(path.is_file() and not path.is_symlink(), "result.json missing")
        record = canonical.strict_load(path)
        require(isinstance(record, dict) and isinstance(record.get("result"), dict), "not a behavioral record")
    except (ContractError, OSError, ValueError) as exc:
        return f"{unpassed}: unreadable ({exc})", None
    if record.get("campaign_sha256") != campaign_sha256 or record["result"].get("ok") is not True:
        return unpassed, None
    if arms is not None:
        expected = {arm: dict(arms[arm]["guard"]) for arm in contracts.ARMS}
        if canonical.canonical_bytes(record.get("arms")) != canonical.canonical_bytes(expected):
            return f"{unpassed}: its arms' guards differ from the campaign manifest's", None
    observations = {}
    try:
        for arm in contracts.ARMS:
            lines, error = canonical.read_jsonl(root / arm / "custody.jsonl")
            submits = [line for line in lines if isinstance(line, dict) and line.get("op") == "submit" and line.get("ok")]
            require(error is None and len(submits) == 2, f"{arm}: custody holds {len(submits)} successful submits, "
                                                         f"not 2 ({error or 'intact'})")
            observations[arm] = {"stale": treatment.probe_from_custody(submits[0]),
                                 "clean": treatment.probe_from_custody(submits[1])}
        verdict = treatment.behavioral_diff(observations)
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        return f"{unpassed}: it does not re-derive from its custody ({exc})", None
    if (canonical.canonical_bytes(observations) != canonical.canonical_bytes(record.get("observations"))
            or canonical.canonical_bytes(verdict) != canonical.canonical_bytes(record["result"])):
        return f"{unpassed}: its observations or verdict differ from their re-derivation from its custody", None
    if not verdict["ok"]:
        return f"{unpassed}: the re-derived verdict fails", None
    return None, canonical.sha256_file(path)


def behavioral_record_problem(campaign_dir, campaign_sha256, arms=None):
    """None when the latest behavioral check passes and re-derives (``behavioral_record``), else the problem. A
    real host's campaign is launched only after one (run_campaign, live.preflight): the manifest check alone
    cannot see a no-op or arm-dependent guard."""
    return behavioral_record(campaign_dir, campaign_sha256, arms)[0]


def scorer_ids_for(manifest, scorer_ids=None) -> set:
    """Scorers whose judge reports may become v1 outcomes: audit.py's SCORER_ID by default; any other
    (a labeled test stub) only when named explicitly and only for a synthetic campaign."""
    if scorer_ids is None:
        audit = audit_module()
        require(audit is not None, "governance.audit is not installed in this checkout (audit.py missing); "
                                   "outcomes are written only from the independent evaluator's judge reports")
        return {audit.SCORER_ID}
    require(manifest["kind"] == "synthetic", "scorer_ids: a scorer other than audit.py is for synthetic campaigns only")
    require(isinstance(scorer_ids, (set, frozenset, list, tuple)) and scorer_ids
            and all(isinstance(s, str) and s.strip() for s in scorer_ids), "scorer_ids: nonempty list of names")
    return set(scorer_ids)


def _judge_reports(campaign_dir, registry, manifest, scorer_ids, skip=()):
    """One validated judge report per registry run (except the runs in ``skip``, which are under a
    recorded incident decision), in registry order, each by an allowed scorer; refuse (naming the
    runs) if any is missing."""
    reports, missing = [], []
    for run in registry["runs"]:
        if run["run_id"] in skip:
            continue
        path = Path(campaign_dir) / "runs" / run["run_id"] / "judge_report.json"
        if not path.is_file() or path.is_symlink():
            missing.append(run["run_id"])
            continue
        label = f"runs/{run['run_id']}/judge_report.json"
        report = canonical.strict_load(path)
        contracts.validate_judge_report(report, label)
        require(report["run_id"] == run["run_id"], f"{label}: names another run")
        reports.append(report)
    require(not missing, f"refusing to write outcomes: no judge report for runs {missing}")
    allowed = scorer_ids_for(manifest, scorer_ids)
    for report in reports:
        label = f"runs/{report['run_id']}/judge_report.json"
        require(report["scorer_id"] in allowed, f"{label}: written by {report['scorer_id']!r}, not {sorted(allowed)}")
    return reports


# ---------------------------------------------------------------- incident decisions (human gate)

def incident_path(campaign_dir, run_id) -> Path:
    return Path(campaign_dir) / COORDINATOR / INCIDENTS / f"{run_id}.json"


def _journaled_seal(run_dir):
    """The evidence_sha256 of the run's one ``sealed`` journal record, or None."""
    seals = [r["details"].get("evidence_sha256") for r in read_journal(Path(run_dir) / "journal.jsonl")
             if r["state"] == "sealed"]
    return seals[0] if len(seals) == 1 and canonical.is_sha256(seals[0]) else None


def _seal_state(run_dir) -> dict:
    """The incident as observed: the journaled seal digest, the digest of the sealed tree as it is now
    (canonical.tree_manifest), the sha256 of evidence_manifest.json's bytes and seal_problem's reason.
    Any later change to the tree, its manifest or the journal changes this state."""
    run_dir = Path(run_dir)
    _, problem = seal_problem(run_dir)
    try:
        tree = canonical.digest(canonical.tree_manifest(run_dir / "sealed"))
    except (ContractError, OSError):
        tree = None
    manifest = run_dir / "evidence_manifest.json"
    return {"journaled_evidence_sha256": _journaled_seal(run_dir), "tree_sha256": tree,
            "manifest_sha256": canonical.sha256_file(manifest) if manifest.is_file() and not manifest.is_symlink()
            else None, "problem": problem}


def _check_decision(decision, label):
    require(isinstance(decision, dict) and set(decision) == set(INCIDENT_FIELDS),
            f"{label}: fields must be {sorted(INCIDENT_FIELDS)}")
    require(type(decision["schema_version"]) is int and decision["schema_version"] == 1, f"{label}: schema_version 1")
    require(canonical.is_sha256(decision["run_id"]), f"{label}.run_id: a v1 run id required")
    require(decision["decision"] == INCIDENT_DECISION, f"{label}.decision: only {INCIDENT_DECISION!r} is defined")
    for name in ("decided_by", "decided_utc", "reason", "problem"):
        require(isinstance(decision[name], str) and decision[name].strip(), f"{label}.{name}: nonblank string required")
    try:
        _utc_seconds(decision["decided_utc"])
    except ValueError:
        raise ContractError(f"{label}.decided_utc: ISO-8601 time required") from None
    for name in ("journaled_evidence_sha256", "tree_sha256", "manifest_sha256"):
        require(decision[name] is None or canonical.is_sha256(decision[name]), f"{label}.{name}: SHA-256 or null")


def record_incident_decision(campaign_dir, run_id, *, decided_by, reason, decided_utc=None) -> Path:
    """Record a HUMAN decision on one run's custody incident (a seal that does not reconcile, §10a).

    Without it write_outcomes and report refuse the whole campaign for one such run. The only
    decision is INCIDENT_DECISION: write_outcomes and report then admit for that run, instead of any
    judge report, the evaluator's null-judgment row (audit.py's own: status crash with every v1
    judgment null for a launched run, the not_started row for a run the journal closed not_started),
    never a scored one, so every assignment still ends with exactly one v1 row. The row's evidence
    digest is the one the coordinator journaled at sealing. The record binds the incident as observed
    now (journaled seal digest, the sealed tree's digest, the evidence manifest's bytes, the reason);
    if any of them changes afterwards the decision no longer applies and the incident refuses again. It is written
    once, never edited. The tool cannot verify who invoked it: ``decided_by`` names the person
    accountable for the decision, which belongs to a human reviewer, never to an agent."""
    campaign_dir = Path(campaign_dir).resolve()
    require(isinstance(decided_by, str) and decided_by.strip(), "decided_by: the accountable person's name required")
    require(isinstance(reason, str) and reason.strip(), "reason: the decision's reason required")
    with campaign_lock(campaign_dir):
        verified = campaign_manifest.verify(campaign_dir)
        require(verified["ok"], f"campaign verification failed: {verified['errors']}")
        registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
        require(run_id in {r["run_id"] for r in registry["runs"]}, f"{run_id!r} is not an assignment of this campaign")
        rdir = campaign_dir / "runs" / run_id
        require(any(r["state"] == "sealed" for r in read_journal(rdir / "journal.jsonl")),
                f"run {run_id} was never sealed: resume the campaign, there is no incident to decide")
        state = _seal_state(rdir)
        require(state["problem"] is not None, f"run {run_id}: its seal reconciles; there is no incident to decide")
        decision = {"schema_version": 1, "run_id": run_id, "decision": INCIDENT_DECISION,
                    "decided_by": decided_by.strip(), "decided_utc": decided_utc or utc_now(),
                    "reason": reason.strip(), **state}
        _check_decision(decision, "incident decision")
        path = incident_path(campaign_dir, run_id)
        canonical.write_once(path, _pretty(decision))
    return path


def _incident_decisions(campaign_dir, registry) -> dict:
    root = Path(campaign_dir) / COORDINATOR / INCIDENTS
    if not os.path.lexists(root):
        return {}
    require(root.is_dir() and not root.is_symlink(), f"coordinator/{INCIDENTS}: not a directory")
    ids, decisions = {r["run_id"] for r in registry["runs"]}, {}
    for path in sorted(root.iterdir()):
        label = f"coordinator/{INCIDENTS}/{path.name}"
        require(path.suffix == ".json" and path.stem in ids and path.is_file() and not path.is_symlink(),
                f"{label}: not an incident decision of an assignment of this campaign")
        decision = canonical.strict_load(path)
        _check_decision(decision, label)
        require(decision["run_id"] == path.stem, f"{label}: names another run")
        decisions[path.stem] = decision
    return decisions


def _incident_report(campaign_dir, run_id, decision) -> dict:
    """The evaluator's null-judgment report for a run under an incident decision (audit.py's own
    constructors: nothing is scored)."""
    audit = audit_module()
    require(audit is not None, "an incident row is the evaluator's null-judgment row: governance.audit is required")
    _, manifest, _, run, definition, _ = audit._campaign(campaign_dir, run_id)
    details = {r["state"]: r["details"] for r in read_journal(Path(campaign_dir) / "runs" / run_id / "journal.jsonl")}
    why = (f"coordinator integrity incident ({decision['problem']}); human decision {decision['decision']} by "
           f"{decision['decided_by']} at {decision['decided_utc']} (coordinator/{INCIDENTS}/{run_id}.json): "
           f"{decision['reason']}")
    if "not_started" in details:
        record = {"synthetic": manifest["kind"] == "synthetic",
                  "not_started_reason": f"{details['not_started'].get('reason')}; {why}"}
        report = audit._not_started(manifest, run, definition, record)
    else:
        executor = (details.get("launched") or {}).get("executor_id")
        evidence = decision["journaled_evidence_sha256"] or decision["tree_sha256"]
        require(isinstance(executor, str) and executor.strip() and evidence is not None,
                f"run {run_id}: the journal records no launch executor or seal digest, so no honest v1 row exists")
        report = audit._unscorable(manifest, run, definition, evidence, executor, "coordinator_integrity_incident", why)
    contracts.validate_judge_report(report, f"incident row of {run_id}")
    return report


def _sealed_identity_errors(run_id, record, planned, manifest) -> list:
    """A sealed run.json against the assignment it is read for (defence in depth beside campaign_manifest.verify,
    which checks the same fields): run_id, campaign_id, campaign_kind, synthetic, adapter, task_id, seed and arm,
    each of the registry's or manifest's JSON type and value."""
    if planned is None:
        return [f"{run_id}: not an assignment of this campaign's registry"]
    expected = {"run_id": run_id, "campaign_id": manifest["campaign_id"], "campaign_kind": manifest["kind"],
                "synthetic": manifest["kind"] == "synthetic", "adapter": manifest["host"]["adapter"],
                "task_id": planned["task_id"], "seed": planned["seed"], "arm": planned["arm"]}
    return [f"{run_id}: sealed run.json.{name} {record[name]!r} differs from this campaign's {value!r}"
            for name, value in expected.items() if type(record[name]) is not type(value) or record[name] != value]


def _bind_to_seals(campaign_dir, reports, action, decisions=None) -> dict:
    """Bind every judged run to its seal before anything sealed is trusted (red-team RT-01), bind every
    judge report to the evaluator (R1.0), and apply recorded incident decisions (R1.6).

    Each run's seal is reconciled first (``seal_problem``: sealed tree, evidence manifest and the
    journaled seal digest; not_started runs included). Only a run whose seal reconciles has its sealed
    run.json read, and the record read is the record checked: it must name this assignment, campaign,
    kind, synthetic label and adapter (``_sealed_identity_errors``, the fields campaign_manifest.verify
    checks), and it is then checked against its judgment: a run sealed never-launched must be judged
    not_started and a launched one not, a failed or lost launch (status_hint launch_error or
    interrupted) crash, a launched run's judged evidence_sha256 must equal its seal, and the report's
    campaign_kind, synthetic, adapter and (launched) executor_id must be the sealed run's. A report
    by audit.py's scorer is then re-derived with ``audit.build_report`` from the sealed evidence and
    must equal it exactly (a judge report edited after it was written is a custody incident). A run
    under an incident decision (``record_incident_decision``) is admitted with the evaluator's
    null-judgment row, only while the decision still describes its seal. Refuses with one custody
    incident (a human gate naming every affected run, why, and the remedy) when any seal does not
    reconcile without a matching decision, any judged digest differs from its seal or any report
    differs from its re-derivation; otherwise with every judgment error. Returns {run_id: incident
    report} for the runs admitted under a decision."""
    incidents, errors, admitted = [], [], {}
    audit = audit_module()
    evaluator = audit.SCORER_ID if audit is not None else None
    manifest = canonical.strict_load(Path(campaign_dir) / campaign_manifest.MANIFEST)
    planned = {r["run_id"]: r for r in canonical.strict_load(Path(campaign_dir) / campaign_manifest.REGISTRY)["runs"]}
    for rid, decision in sorted((decisions or {}).items()):
        state = _seal_state(Path(campaign_dir) / "runs" / rid)
        if state["problem"] is None or any(decision[k] != v for k, v in state.items()):
            incidents.append((rid, f"the recorded incident decision (coordinator/{INCIDENTS}/{rid}.json) no longer "
                                   f"describes the run's seal, which changed after the decision (now {state})"))
            continue
        try:
            admitted[rid] = _incident_report(campaign_dir, rid, decision)
        except ContractError as exc:
            incidents.append((rid, f"no null-judgment row under the incident decision: {exc}"))
    for report in reports:
        rid, rdir = report["run_id"], Path(campaign_dir) / "runs" / report["run_id"]
        digest, problem = seal_problem(rdir)
        if problem is not None:   # its run.json is not trusted: nothing sealed is read
            incidents.append((rid, f"coordinator integrity: {problem}"))
            continue
        require((rdir / "sealed" / "run.json").is_file(), f"{rid}: judge report without sealed evidence")
        run = canonical.strict_load(rdir / "sealed" / "run.json")
        validate_run_record(run, f"runs/{rid}/sealed/run.json")
        identity = _sealed_identity_errors(rid, run, planned.get(rid), manifest)
        if identity:
            errors += identity
            continue
        row, hint, found = report["v1_outcome"], run["status_hint"], []
        if hint == "not_started" and row["status"] != "not_started":
            found.append(f"{rid}: never launched, judged {row['status']!r}")
        elif hint != "not_started" and row["status"] == "not_started":
            found.append(f"{rid}: launched, judged not_started")
        elif hint in ("launch_error", LOST_HINT) and row["status"] != "crash":
            found.append(f"{rid}: sealed {hint} (a failed or lost launch), judged {row['status']!r}, not crash")
        elif hint != "not_started" and row["evidence_sha256"] != digest:
            incidents.append((rid, f"the judged evidence_sha256 {row['evidence_sha256']} differs from the sealed "
                                   f"evidence {digest}"))
            continue
        if not found:
            found += [f"{rid}: judged {name} {report[name]!r}, sealed {run[name]!r}"
                      for name in ("campaign_kind", "synthetic", "adapter") if report[name] != run[name]]
            if hint != "not_started" and row["executor_id"] != run["executor_id"]:
                found.append(f"{rid}: judged executor_id {row['executor_id']!r}, sealed {run['executor_id']!r}")
        if found:
            errors += found
            continue
        if evaluator is not None and report["scorer_id"] == evaluator:
            try:
                rebuilt = audit.build_report(campaign_dir, rid)
            except ContractError as exc:
                incidents.append((rid, f"the evaluator cannot re-derive this judge report from the sealed evidence "
                                       f"({exc})"))
                continue
            if canonical.canonical_bytes(rebuilt) != canonical.canonical_bytes(report):
                fields = sorted(k for k in set(rebuilt) | set(report)
                                if canonical.canonical_bytes(rebuilt.get(k)) != canonical.canonical_bytes(report.get(k)))
                incidents.append((rid, f"the judge report differs at {fields} from the evaluator's re-derivation from "
                                       "the sealed evidence and scorer (changed after it was written)"))
    require(not incidents, CUSTODY_INCIDENT.format(
        action=action, count=len(incidents), runs=[rid for rid, _ in incidents],
        what="; ".join(f"{rid}: {why}" for rid, why in incidents)))
    require(not errors, f"refusing to {action}: " + "; ".join(errors))
    return admitted


def _admitted_reports(campaign_dir, scorer_ids, action) -> tuple:
    """(registry, manifest, reports): the campaign verified and still the bytes frozen at build
    (R1.2), and exactly one report per registry run, in registry order: its judge report by an
    allowed scorer, provenance-checked, bound to its seal and (audit.py's) re-derived, or the
    evaluator's null-judgment row under a recorded incident decision."""
    verified = campaign_manifest.verify(campaign_dir)
    require(verified["ok"], f"campaign verification failed: {verified['errors']}")
    problem = campaign_digest_problem(campaign_dir)
    require(problem is None, f"refusing to {action}: campaign integrity: {problem}")
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    manifest = canonical.strict_load(campaign_dir / campaign_manifest.MANIFEST)
    decisions = _incident_decisions(campaign_dir, registry)
    reports = _judge_reports(campaign_dir, registry, manifest, scorer_ids, skip=set(decisions))
    provenance = campaign_manifest.verify_run_provenance(campaign_dir, reports)
    require(provenance["ok"], f"judge report provenance: {provenance['errors']}")
    by_run = {r["run_id"]: r for r in reports}
    by_run.update(_bind_to_seals(campaign_dir, reports, action, decisions))
    ordered = [by_run[r["run_id"]] for r in registry["runs"]]
    provenance = campaign_manifest.verify_run_provenance(campaign_dir, ordered)
    require(provenance["ok"], f"judge report provenance: {provenance['errors']}")
    return registry, manifest, ordered


def write_outcomes(campaign_dir, *, scorer_ids=None) -> Path:
    """Write outcomes.json: exactly one v1 row per registry run, each the v1_outcome of that run's
    judge report (by audit.py's scorer unless ``scorer_ids`` names a synthetic test scorer), bound to
    its sealed evidence; a run sealed never-launched must be judged not_started, a lost launch
    (status_hint interrupted) or launch error crash; a report by audit.py's scorer must equal its
    re-derivation from the sealed evidence. Refuses (naming the runs) if a report is missing, when
    campaign.json is not the frozen bytes, and as a custody incident (a human gate, naming every
    affected run, why, and the remedy) when any run's seal does not reconcile (``seal_problem``:
    sealed tree, evidence manifest and the journaled seal digest), a launched run's judged
    evidence_sha256 differs from its seal or a report differs from its re-derivation; seals are
    reconciled before any sealed run.json is trusted (``_bind_to_seals``). A run under a recorded
    human incident decision (``record_incident_decision``) gets the evaluator's null-judgment row."""
    campaign_dir = Path(campaign_dir).resolve()
    with campaign_lock(campaign_dir):
        registry, manifest, reports = _admitted_reports(campaign_dir, scorer_ids, "write outcomes")
        outcomes = {"schema_version": 1, "registry_sha256": registry["registry_sha256"],
                    "outcomes": [r["v1_outcome"] for r in reports]}
        try:
            experiment.score(registry, outcomes)
        except (ValueError, TypeError, KeyError) as exc:
            raise ContractError(f"v1 score rejects the outcomes: {exc}") from exc
        path = campaign_dir / "outcomes.json"
        canonical.atomic_write_bytes(path, (json.dumps(outcomes, indent=2, allow_nan=False) + "\n").encode())
    return path


def _task_definitions(campaign_dir, registry) -> list:
    """One §4.4 definition per task from the frozen family; every evaluator copy must equal it."""
    family_dir = Path(campaign_dir) / COORDINATOR / "family"
    index = canonical.strict_load(family_dir / "index.json")
    by_task = {t["task_id"]: (family_dir / t["definition_path"]).read_bytes() for t in index["tasks"]}
    for run in registry["runs"]:
        copy = Path(campaign_dir) / "evaluator" / run["run_id"] / "task_definition.json"
        require(not copy.exists() or copy.read_bytes() == by_task[run["task_id"]],
                f"evaluator/{run['run_id']}/task_definition.json differs from the frozen family")
    return [canonical.strict_loads(by_task[t["id"]].decode()) for t in registry["spec"]["tasks"]]


def report(campaign_dir, *, bootstrap_seed=0, n_bootstrap=2000, scorer_ids=None) -> dict:
    """v1 score -> summary.json and analysis.analyze -> analysis.json from outcomes.json, whose rows
    must be exactly the admitted reports' v1 rows. Every check of write_outcomes applies again (the
    scorer rule, judge-report provenance, campaign.json's frozen bytes, seal reconciliation, the
    re-derivation of audit.py's reports and incident decisions): a sealed tree or a judge report
    changed after outcomes were written never reaches summary.json or analysis.json."""
    campaign_dir = Path(campaign_dir).resolve()
    with campaign_lock(campaign_dir):
        registry, manifest, reports = _admitted_reports(campaign_dir, scorer_ids, "report")
        outcomes = canonical.strict_load(campaign_dir / "outcomes.json")
        try:
            summary = experiment.score(registry, outcomes)
        except (ValueError, TypeError, KeyError) as exc:
            raise ContractError(f"v1 score: {exc}") from exc
        require(canonical.canonical_bytes(outcomes["outcomes"])
                == canonical.canonical_bytes([r["v1_outcome"] for r in reports]),
                "outcomes.json differs from the judge reports' v1 rows; rewrite it with write_outcomes")
        result = analysis.analyze(registry, outcomes, reports, _task_definitions(campaign_dir, registry),
                                  bootstrap_seed=bootstrap_seed, n_bootstrap=n_bootstrap)
        entries = canonical.canonical_bytes(result["inputs"]["task_entries"])
        require(entries == canonical.canonical_bytes(manifest["tasks"]), "analysis task entries differ from campaign")
        paths = {"summary": campaign_dir / "summary.json", "analysis": campaign_dir / "analysis.json"}
        for name, value in (("summary", summary), ("analysis", result)):
            canonical.atomic_write_bytes(paths[name], (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())
    return {"summary": str(paths["summary"]), "analysis": str(paths["analysis"]), "synthetic": result["synthetic"]}


__all__ = ["build_synthetic_campaign", "run_campaign", "write_outcomes", "report", "fake_adapter_factory",
           "read_journal", "evidence_digest", "seal_problem", "sealed_evidence", "launch_policy", "checkout_source",
           "campaign_lock", "audit_module", "unsealed_runs", "scorer_ids_for", "harness_manifest", "behavioral_check",
           "record_incident_decision", "campaign_digest_problem", "host_binding", "exact",
           "behavioral_record_problem", "behavioral_record", "adapter_factory_for", "host_access",
           "check_subject_visible_root", "host_root_problem", "prepare_host_root", "read_stop", "write_stop",
           "core_limit_problem", "CredentialPause", "CoordinatorInterrupted", "proxy_summary", "proxy_flags",
           "receipt_findings"]
