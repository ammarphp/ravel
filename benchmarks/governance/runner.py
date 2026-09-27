"""Assignment coordinator (slice design §3, §6, §10; WP07): build, run, seal and account.

``build_synthetic_campaign`` freezes a synthetic campaign from the development family: the v1
spec and registry and the §4.1 manifest (``campaign_manifest.write_campaign``), plus the
coordinator-private directory ``<campaign>/coordinator/`` (family build, campaign secret,
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

Standard library only. The only host this module builds a campaign for is the synthetic fake
host; a campaign with any other host runs only with ``RAVEL_EVAL_LIVE=1``.
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
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from . import analysis, campaign_manifest, canonical, contracts, guard, isolation, stages, treatment
from .adapters import fake as fake_adapter
from .adapters.base import (AdapterResult, HostDriftError, assert_prompt_not_in_argv, ipc_residue_flagged,
                            profile_sha256)
from .broker import STAGE_ENV_KEYS, TOKEN_HEADER, Broker
from .canonical import ContractError, require
from .contracts import (LAUNCH_FIELDS, LOST_CAUSES, RUN_FIELDS, RUN_STATUS_HINTS, validate_launch_record,  # noqa: F401
                        validate_run_record)
from .oracle.counting import INPUT_KINDS
from .tasks.development.likelihood_freshness import family

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
                 "sandbox", "forbidden_roots", "subjects_root")
ASSIGNMENT_KEYS = ("adapter", "behavior", "behavior_plan_sha256")
INTERRUPTED = "coordinator interrupted; no retry under policy none"
LOST_NOTES = {"coordinator_interrupted": INTERRUPTED,
              "adapter_error": "adapter failed after the launch began; no retry under policy none"}
SUBJECT_ROOT = "$SUBJECT_ROOT"
DEFAULT_BUDGET = {"usd_per_run": 1.0, "seconds_per_run": 600, "max_broker_ops": 40, "max_fits": 4}
SYNTHETIC_MODEL = "synthetic-fake-subject (no model)"
SYNTHETIC_AUTHORIZATION = {"kind": "synthetic_engineering", "reference_sha256": None,
                           "reference": "SYNTHETIC engineering campaign from runner.build_synthetic_campaign; "
                                        "fake host, no model call; not an approval"}
STAGE_ENV = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1", "LC_ALL": "C", "LANG": "C",
             **{name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                       "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")}}
RESOURCE_POLICY = ("Use only this workspace and bin/ravel-task; at most {ops} task-service operations, of which at "
                   "most {fits} fit operations; wall-clock limit {seconds:g} s; no network access except the task "
                   "service.")
# Content canaries, checked at every campaign load against every subject-visible byte: the family
# build's random canary (index["canary"], planted in every oracle record and task definition before
# hashing), fragments present in every oracle record / task definition however it is formatted, and
# each oracle limit and sigma_vis value as printed (10 significant digits). The random campaign
# canary is the tripwire file coordinator/canary.txt.
ORACLE_CANARY = "governance.oracle.counting"
DEFINITION_CANARY = "reuse_expectation"
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


class LaunchRefused(RuntimeError):
    """The recording launcher refused a launch call before anything started (never an OSError or
    ValueError, so an adapter's launch_host cannot turn it into a launch_error result)."""


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
    """Outermost ancestor of the checkout holding .git, CLAUDE.md or AGENTS.md (the lab tree)."""
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


def check_subjects_root(subjects_root, forbidden) -> Path:
    """Absolute, outside every forbidden root, no instruction-bearing ancestor, no arm word in the path."""
    path = Path(subjects_root)
    require(path.is_absolute(), f"subjects_root: absolute path required, got {path}")
    real = os.path.realpath(path)
    for root in forbidden:
        require(not (_within(real, root) or _within(root, real)),
                f"subjects_root {real} overlaps forbidden root {root}")
    for ancestor in (Path(real), *Path(real).parents):
        for marker in isolation.ANCESTOR_MARKERS:
            require(not os.path.lexists(ancestor / marker),
                    f"subjects_root: {ancestor} holds {marker} (hosts load parent-directory instructions)")
    terms = treatment.arm_identifying_terms(real)
    require(not terms, f"subjects_root: the path names {terms}; subject-visible paths may not identify an arm")
    return Path(real)


def subject_interpreter() -> tuple:
    """(python, prefix): the resolved base interpreter (a venv inside the repository is unreadable
    under the profile) and its resolved prefix, which becomes a sandbox read root."""
    python = os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)
    prefix = os.path.realpath(sys.base_prefix)
    require(python.startswith(prefix + os.sep), f"subject interpreter {python} lies outside its prefix {prefix}")
    require(not any(c.isspace() for c in python), "subject interpreter path may not contain whitespace (shebang)")
    return python, prefix


def launch_policy(*, workspace, subject_prefix, forbidden, port) -> isolation.SandboxPolicy:
    """The subject's sandbox policy: read the workspace and the subject interpreter prefix, write its
    output/, tmp/ and home/, reach only the broker port, and deny every forbidden root. Built at
    build time (placeholder workspace and port), at every campaign load and at every launch, in
    every sandbox mode, so a misconfiguration (an interpreter prefix inside a forbidden root, say)
    fails the build instead of burning assignments as not_started."""
    workspace = Path(workspace)
    try:
        return isolation.SandboxPolicy(read_roots=[workspace, subject_prefix],
                                       write_roots=[workspace / "output", workspace / "tmp", workspace / "home"],
                                       network="localhost", localhost_ports=[port], forbidden_roots=forbidden)
    except ContractError as exc:
        raise ContractError(f"launch profile: {exc}") from None


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


def environment_manifest(*, subject_python, stage_python, stage_env, sandbox) -> dict:
    """What the environment digest binds: both interpreters, the stage env, pyhf, platform, sandbox,
    the materialized client and the harness code."""
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
            "harness_code": harness_manifest()}


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


def common_sources(stage_python) -> dict:
    """Source files of the §4.3 common block (identical in every arm)."""
    g = GOVERNANCE
    return {"envelope": treatment.TREATMENTS_DIR / treatment.FROZEN_FILES["envelope"], "tool_guide": TOOL_GUIDE,
            "client": CLIENT, "broker": [g / "broker.py", g / "guard.py"],
            "stage_workers": [Path(stages.__file__)] + [stages.worker_path(s) for s in stages.ORDER],
            "kernel_source": CHECKOUT / "src", "interpreter": stage_python,
            "operation_schema": [g / "contracts.py"] + [g / "schemas" / f"{n}.schema.json"
                                                       for n in ("claim", "submission", "decision_record")]}


def arm_manifests(stage_python) -> dict:
    common = treatment.common_hashes(common_sources(stage_python))
    guard_sha = canonical.sha256_file(GOVERNANCE / "guard.py")
    arms = {arm: treatment.arm_manifest(arm, common=common, instructions_text=treatment.frozen_bytes("instructions"),
                                        guard_impl_sha256=guard_sha) for arm in contracts.ARMS}
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
                             budget=None, sandbox="seatbelt", extra_forbidden_roots=()) -> Path:
    """Freeze a synthetic fake-host campaign at <store>/synthetic/<campaign_id>/; return its directory.

    ``source`` defaults to the checkout's git HEAD and tracked-file dirtiness; an explicit
    {git_commit, dirty} must equal it when git can read the checkout. ``budget`` overrides
    DEFAULT_BUDGET fields (global caps default to runs x per-run caps). ``sandbox`` is
    ``seatbelt`` or ``none_test_only`` (recorded in the host config and every run.json). The
    campaign is assembled under a temporary directory in the namespace and renamed into place
    only after it loads (profile, separation and code checks included); on any failure nothing
    remains and the campaign id stays free.
    """
    require(sandbox in contracts.SANDBOXES, f"sandbox: expected one of {list(contracts.SANDBOXES)}")
    require(isinstance(campaign_id, str) and contracts.SAFE_ID.fullmatch(campaign_id) is not None,
            f"campaign_id: must match {contracts.SAFE_ID.pattern}")
    store = Path(store)
    require(store.is_absolute(), f"store: absolute path required, got {store}")
    target = store / "synthetic" / campaign_id
    require(not os.path.lexists(target), f"refusing to overwrite existing campaign directory {target}")
    forbidden = forbidden_roots(store, extra_forbidden_roots)
    subjects = check_subjects_root(subjects_root, forbidden)
    subject_python, subject_prefix = subject_interpreter()
    # Fail fast, before any family build or interpreter probe, and in every sandbox mode.
    isolation.seatbelt_profile(launch_policy(workspace=subjects / PLACEHOLDER_HANDLE, subject_prefix=subject_prefix,
                                             forbidden=forbidden, port=1))
    stage_python = os.path.abspath(sys.executable)
    stage_env = stage_environment()
    environment = environment_manifest(subject_python=subject_python, stage_python=stage_python,
                                       stage_env=stage_env, sandbox=sandbox)
    host = fake_host(subject_python, canonical.digest(environment), sandbox)
    source = _source(source)
    arms = arm_manifests(stage_python)
    namespace = store / "synthetic"
    namespace.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix=f".{campaign_id}.build-", dir=namespace))
    try:
        index = family.build_family(build / "family")
        definitions, tasks = [], []   # v1 tasks in family index order, tolerance from each definition
        require(len(index["tasks"]) == len(index["v1_tasks"]), "family index: tasks and v1_tasks differ in length")
        for entry, v1_task in zip(index["tasks"], index["v1_tasks"]):
            data = (build / "family" / entry["definition_path"]).read_bytes()
            require(canonical.sha256_bytes(data) == entry["definition_sha256"], f"{entry['task_id']}: definition hash")
            definition = canonical.strict_loads(data.decode())
            task = {"id": definition["task_id"], "expected": definition["expected"],
                    "prompt_sha256": definition["prompt_sha256"], "oracle_sha256": definition["oracle_sha256"],
                    "fidelity_tolerance": definition["fidelity"]["tolerance"]}
            require(canonical.canonical_bytes(task) == canonical.canonical_bytes(v1_task),
                    f"{entry['task_id']}: family index v1 task differs from its definition")
            definitions.append(definition)
            tasks.append(task)
        limits = _budget(budget, len(tasks) * len(seeds) * len(contracts.ARMS))
        spec = {"experiment_id": campaign_id, "protocol_sha256": canonical.sha256_file(PROTOCOL),
                "code_commit": source["git_commit"], "environment_sha256": host["environment_manifest_sha256"],
                "model": SYNTHETIC_MODEL,
                "runtime": f"{campaign_manifest.SYNTHETIC_LABEL} {campaign_manifest.runtime_label(host)}",
                "schedule_seed": schedule_seed, "seeds": list(seeds), "tasks": tasks,
                "budget": {"usd_per_run": limits["usd_per_run"], "seconds_per_run": limits["seconds_per_run"]}}
        staged = campaign_manifest.write_campaign(   # <build>/synthetic/<campaign_id>: verify checks the names
            build, kind="synthetic", campaign_id=campaign_id, spec=spec, host=host, arms=arms, tasks=definitions,
            budget=limits, authorization=dict(SYNTHETIC_AUTHORIZATION), created_utc=created_utc, source=source,
            interpreter=campaign_manifest.interpreter_record(stage_python), subjects_root=subjects_root)
        coordinator = staged / COORDINATOR
        coordinator.mkdir(mode=0o700)
        os.rename(build / "family", coordinator / "family")
        canonical.write_once(coordinator / "campaign_secret", secrets.token_hex(32).encode() + b"\n", mode=0o400)
        canonical.write_once(coordinator / "canary.txt", f"RAVEL-EVAL-CANARY-{secrets.token_hex(16)}\n".encode(),
                             mode=0o400)
        canonical.write_once(coordinator / "environment.json", _pretty(environment))
        config = {"schema_version": 1, "checkout": str(CHECKOUT), "stage_python": stage_python,
                  "stage_env": stage_env, "subject_python": subject_python, "subject_prefix": subject_prefix,
                  "sandbox": sandbox, "forbidden_roots": forbidden, "subjects_root": str(subjects)}
        canonical.write_once(coordinator / "config.json", _pretty(config))
        canonical.write_once(coordinator / CAMPAIGN_DIGEST,
                             (canonical.sha256_file(staged / campaign_manifest.MANIFEST) + "\n").encode(), mode=0o400)
        _Campaign(staged, check_environment=False)   # fail closed now, not at the first launch
        require(not os.path.lexists(target), f"refusing to overwrite existing campaign directory {target}")
        os.rename(staged, target)
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

    def __init__(self, path, journal, check=None):
        self.path, self.journal, self.check = Path(path), Path(journal), check

    def __call__(self, argv, *, cwd, env, profile, timeout_s, stdout_path, stderr_path, stdin_path=None):
        problems = self.check(list(argv), dict(env)) if self.check is not None else []
        if problems:
            raise LaunchRefused("the coordinator refused the launch call: " + "; ".join(problems))
        canonical.write_once(self.path, _pretty({"argv": list(argv), "env_names": sorted(env), "cwd": str(cwd),
                                                 "timeout_s": timeout_s, "profile_sha256": profile_sha256(profile)}))
        return isolation.launch(argv, cwd=cwd, env=env, profile=profile, timeout_s=timeout_s, stdout_path=stdout_path,
                                stderr_path=stderr_path, stdin_path=stdin_path,
                                on_start=lambda started: _record(self.journal, "process_started", **started))


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
    files = {"request.md": campaign.request, "tools.md": campaign.tool_guide, "bin/ravel-task": campaign.client,
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
        if self.host["sandbox"] == "seatbelt":
            require(isolation.sandbox_available() and isolation.census_available(),
                    "the campaign requires the Seatbelt sandbox and its census, unavailable here")
        self.environment = canonical.strict_load(coordinator / "environment.json")
        require(canonical.digest(self.environment) == self.host["environment_manifest_sha256"]
                == self.spec["environment_sha256"], "coordinator/environment.json differs from the frozen digest")
        self._check_code(check_environment)
        self.secret = (coordinator / "campaign_secret").read_bytes()
        self.canary = (coordinator / "canary.txt").read_text().strip()
        require(len(self.secret) >= 32 and self.canary.startswith("RAVEL-EVAL-CANARY-"), "coordinator secret/canary")
        self.family_dir = coordinator / "family"
        self.index = canonical.strict_load(self.family_dir / "index.json")
        self.tasks = {t["task_id"]: t for t in self.index["tasks"]}
        require(list(self.tasks) == [t["id"] for t in self.spec["tasks"]], "family index tasks differ from the spec")
        self.request = (self.family_dir / "request.md").read_bytes()
        require(all(t["prompt_sha256"] == canonical.sha256_bytes(self.request) for t in self.spec["tasks"]),
                "request.md differs from the prompt_sha256 the v1 spec freezes for its tasks")
        self.tool_guide = TOOL_GUIDE.read_bytes()
        self.client = materialized_client(self.config["subject_python"])
        require(canonical.sha256_bytes(self.client) == self.environment["materialized_client_sha256"],
                "the materialized client differs from the one the environment manifest binds")
        self.forbidden_roots = sorted(set(self.config["forbidden_roots"])
                                      | set(forbidden_roots(self.dir.parent.parent)))
        self.subjects_root = check_subjects_root(self.manifest["storage"]["subjects_root"], self.forbidden_roots)
        require(str(self.subjects_root) == self.config["subjects_root"], "subjects_root differs from the config")
        self._profile(self.subjects_root / PLACEHOLDER_HANDLE, 1)   # the launch policy must be buildable
        self.forbidden_sha256 = {canonical.sha256_file(self.family_dir / p)
                                 for p in self.index["path_roles"]["evaluator_private"]}
        self.forbidden_sha256 |= {canonical.sha256_file(coordinator / "canary.txt"),
                                  canonical.sha256_file(coordinator / "campaign_secret")}
        self.family_canary = self.index.get("canary")
        require(isinstance(self.family_canary, str) and contracts.CANARY.fullmatch(self.family_canary) is not None,
                "family index: no build canary (rebuild the campaign with the current family)")
        self.canaries = [self.canary, self.family_canary, ORACLE_CANARY, DEFINITION_CANARY]
        for task_id in self.tasks:
            oracle = canonical.strict_loads(self.evaluator_files(task_id)["oracle.json"].decode())
            self.canaries += [c for c in _value_canaries(oracle) if c not in self.canaries]
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
            environment = environment_manifest(subject_python=self.config["subject_python"], stage_python=stage_python,
                                               stage_env=self.config["stage_env"], sandbox=self.config["sandbox"])
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
        now = {e["path"]: e["sha256"] for e in harness_manifest()}
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
        visible = {"request.md": self.request, "tools.md": self.tool_guide, "bin/ravel-task": self.client,
                   "client source": CLIENT.read_bytes()}
        if self.host["adapter"] == "fake":
            visible["fake subject"] = fake_adapter.SUBJECT_SCRIPT.read_bytes()
        placeholder = self.subjects_root / PLACEHOLDER_HANDLE
        for task_id in self.tasks:
            for name, data in self.inputs(task_id, "current").items():
                visible[f"{task_id} input {name}"] = data
            evaluator = self.evaluator_files(task_id)
            require(ORACLE_CANARY.encode() in evaluator["oracle.json"], f"{task_id}: oracle canary missing")
            require(DEFINITION_CANARY.encode() in evaluator["task_definition.json"], f"{task_id}: definition canary")
            for name, data in evaluator.items():
                require(self.family_canary.encode() in data, f"{task_id}: {name} lacks the family build canary")
        for arm in contracts.ARMS:
            visible[f"{arm} prompt"] = self.prompt({"arm": arm}, placeholder).encode()
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
                                        seconds=self.budget["seconds_per_run"])
        included = self.manifest["arms"][run["arm"]]["instructions"]["included"]
        return treatment.render_prompt(
            self.texts["envelope"], treatment.SEPARATOR + self.texts["instructions"] if included else None,
            request_text=self.request.decode("utf-8").strip(), input_root=str(ws), output_root=str(ws / "output"),
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
        try:
            files = _subject_files(self, run)
            self.subjects_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            isolation.materialize(files, ws)
        except (ContractError, OSError) as exc:
            reason = f"subject workspace materialization failed: {exc}"
            _record(journal, "admission_failed", stage="materialization", reason=reason, **assignment)
            return self._not_started(run, reason)
        _record(journal, "materialized", opaque_handle=opaque, subject_root=str(ws),
                workspace_files={n: canonical.sha256_bytes(d) for n, d in sorted(files.items()) if not n.endswith("/")},
                evaluator_files={n: canonical.sha256_bytes(d) for n, d in self.evaluator_files(run["task_id"]).items()},
                campaign_sha256=self.campaign_sha256, **assignment)
        check = self._admit(ws, {})
        if not check["ok"]:
            reason = "admission check failed (workspace): " + ", ".join(
                sorted({v["code"] for v in check["violations"]}))
            _record(journal, "admission_failed", stage="workspace", reason=reason, violations=check["violations"])
            return self._not_started(run, reason)
        # §10: global budget admission after the admission check, in exact decimals (a campaign sized to
        # N runs at the cap admits all N; float sums would refuse the last one).
        (usd, seconds), b = self.spent_exact(), self.budget
        remaining = {"usd": exact(b["global_usd_cap"]) - usd, "seconds": exact(b["global_seconds_cap"]) - seconds}
        if remaining["usd"] < exact(b["usd_per_run"]) or remaining["seconds"] < exact(b["seconds_per_run"]):
            reason = (f"global budget admission: remaining {remaining['usd']:f} USD / {remaining['seconds']:f} s is "
                      f"below the per-run cap {b['usd_per_run']:g} USD / {b['seconds_per_run']:g} s")
            _record(journal, "admission_failed", stage="global_budget", reason=reason,
                    spent={"usd": float(usd), "seconds": float(seconds)})
            return self._not_started(run, reason)
        try:
            broker, handles = self._broker(run)
        except Exception as exc:   # kernel probe or prior stages: fail closed, the subject never runs
            reason = f"broker preparation failed: {type(exc).__name__}: {exc}"
            _record(journal, "admission_failed", stage="broker", reason=reason)
            return self._not_started(run, reason)
        stop_error = None
        try:
            kind, value = self._serve(run, ws, broker, handles, behavior, assignment, factory)
        finally:
            try:
                broker.stop()
            except RuntimeError as exc:
                stop_error = str(exc)
        extra = {"broker_stop_error": stop_error} if stop_error else {}
        if kind == "not_started":
            return self._not_started(run, value, **extra)
        drift = self._code_problems()   # verified before the launch: the same code must be there after it
        if drift:
            extra["code_drift"] = drift
        if kind == "adapter_error":
            return self._crash(run, "adapter_error", error=value, **extra)
        result = value.as_dict()
        canonical.write_once(self.run_dir(rid) / "host" / "adapter_result.json", _pretty(result))
        charge = self.charge(result["cost"]["usd"], result["cost"]["provenance"], result["wall_seconds"])
        _record(journal, "exited", status_hint=result["status_hint"], exit_code=result["exit_code"],
                wall_seconds=result["wall_seconds"], cost=result["cost"], validity=result["validity"], charge=charge,
                **extra)
        return self._seal(run)

    def _broker(self, run):
        guard = self.manifest["arms"][run["arm"]]["guard"]
        broker = Broker(self.dir / "broker" / run["run_id"], guard_mode=guard["mode"], feedback=guard["feedback"],
                        budgets={"max_broker_ops": self.budget["max_broker_ops"], "max_fits": self.budget["max_fits"]},
                        python=self.config["stage_python"], env=self.config["stage_env"],
                        secret=secrets.token_bytes(32))
        by_kind = {side: {INPUT_KINDS[n]: d for n, d in self.inputs(run["task_id"], side).items()}
                   for side in ("current", "prior")}
        current = broker.register_inputs(by_kind["current"])
        prior = broker.create_prior(by_kind["prior"])
        return broker, {"current": current, "prior": prior}

    def _profile(self, ws, port):
        """The Seatbelt profile (None for none_test_only, whose policy inputs are still validated)."""
        policy = launch_policy(workspace=ws, subject_prefix=self.config["subject_prefix"],
                               forbidden=self.forbidden_roots, port=port)
        return isolation.seatbelt_profile(policy) if self.host["sandbox"] == "seatbelt" else None

    def _admit(self, ws, env):
        return isolation.admission_check(ws, forbidden_sha256=self.forbidden_sha256, canaries=self.canaries, env=env,
                                         forbidden_roots=self.forbidden_roots)

    def _serve(self, run, ws, broker, handles, behavior, assignment, factory):
        """Start the broker, admit the launch environment and prompt, re-verify what the run receives
        against the frozen campaign, bind the host, launch. Returns (kind, value)."""
        rid = run["run_id"]
        journal, host_dir = self.run_dir(rid) / "journal.jsonl", self.run_dir(rid) / "host"
        endpoint, token = broker.start()
        parts = urllib.parse.urlsplit(endpoint)
        require(parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.port,
                f"broker endpoint is not 127.0.0.1: {endpoint}")
        env = isolation.subject_env(workspace=ws, home=ws / "home", path_dirs=["/usr/bin", "/bin", str(ws / "bin")],
                                    extra={"RAVEL_TASK_ENDPOINT": endpoint, "RAVEL_TASK_TOKEN": token})

        def refuse(stage, reason, **details):
            _record(journal, "admission_failed", stage=stage, reason=reason, **details)
            return "not_started", reason

        try:
            profile = self._profile(ws, parts.port)   # after start: localhost is exactly the broker port
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
                prior_handles=handles["prior"], profile_sha256=profile_sha256(profile), verified=verified)
        recorder = _Recorder(host_dir / "launch_call.json", journal,
                             check=lambda argv, final_env: self._launch_call_problems(argv, final_env, env))
        # The arm is not passed: the runner resolves everything arm-dependent (the fake behavior plan),
        # so no factory can configure a host differently by arm (R0.5).
        adapter = factory({"run_id": rid, "task_id": run["task_id"], "seed": run["seed"], "behavior": behavior,
                           "python": self.config["subject_python"], "launcher": recorder})
        name = getattr(adapter, "name", None)
        require(name == self.host["adapter"], f"adapter factory returned a {name!r} adapter for a "
                                              f"{self.host['adapter']} host")
        executor = getattr(adapter, "executor_id", None)
        require(isinstance(executor, str) and executor.strip(), "adapter: executor_id required")
        if getattr(adapter, "launcher", None) is not recorder:
            return refuse("host", "the adapter does not launch through the coordinator's recording launcher, so its "
                                  "launch could not be journaled or censused")
        binding_sha256 = None
        if self.host["adapter"] != "fake":
            binding, problems = self._bind_host(adapter)
            if problems:
                return refuse("host", "host configuration differs from the campaign: " + "; ".join(problems),
                              problems=problems)
            binding_sha256 = canonical.digest(binding)
        timeout = self.budget["seconds_per_run"]
        _record(journal, "launched", executor_id=executor, timeout_s=timeout, profile_sha256=profile_sha256(profile),
                prompt_sha256=canonical.sha256_bytes(prompt.encode()), campaign_sha256=self.campaign_sha256,
                host_binding_sha256=binding_sha256, **assignment)
        try:
            result = adapter.run(prompt=prompt, workspace=ws, env=env, profile=profile, timeout_s=timeout,
                                 out_dir=host_dir)
        except Exception as exc:  # never a retry: a lost launch if the launcher was called, else not started
            if self._launcher_called(rid):
                return "adapter_error", f"{type(exc).__name__}: {exc}"
            if isinstance(exc, HostDriftError):
                what = "host drift; the host was not launched"
            elif isinstance(exc, LaunchRefused):
                what = "the launch call was refused before anything started"
            else:
                what = "the adapter failed before calling the launcher; no process was started"
            return "not_started", f"{what}: {type(exc).__name__}: {exc}"
        return "exited", result

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
        request_sha256 = canonical.sha256_bytes(self.request)
        if request_sha256 != task["prompt_sha256"]:
            problems.append("request.md is not the prompt_sha256 the v1 spec freezes for this task")
        if canonical.sha256_bytes(self.tool_guide) != arm["common"]["tool_guide_sha256"]:
            problems.append("the tool guide is not the one the treatment manifest binds")
        if canonical.sha256_bytes(self.client) != self.environment["materialized_client_sha256"]:
            problems.append("the client is not the one the environment manifest binds")
        for name, data in (("request.md", self.request), ("tools.md", self.tool_guide), ("bin/ravel-task", self.client)):
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

    def _launch_call_problems(self, argv, env, base_env) -> list:
        """The final launch call an adapter makes, checked by the recording launcher before anything
        starts: the coordinator's subject environment is passed on unchanged (an adapter may only add),
        neither an added environment value nor any argv element carries evaluator material, and, for a
        real host, no added value names an arm (the per-run directories its factory chooses, R0.5; the
        fake host's arm-dependent behavior is the runner's own plan, and its synthetic test adapters
        pass probe paths such as the repository's audit.py, which the arm-term scan would name)."""
        problems = []
        changed = sorted(n for n, v in base_env.items() if env.get(n) != v)
        if changed:
            problems.append(f"the adapter changed or dropped coordinator environment variables {changed}")
        for name in sorted(set(env) - set(base_env)):
            value = env[name]
            if not isinstance(value, str):
                problems.append(f"environment variable {name} is not a string")
                continue
            terms = treatment.arm_identifying_terms(value) if self.host["adapter"] != "fake" else []
            if terms:
                problems.append(f"environment variable {name} names {terms}")
            if self.leaks(value.encode()):
                problems.append(f"environment variable {name} carries evaluator material")
        for i, element in enumerate(argv):
            if isinstance(element, str) and self.leaks(element.encode()):
                problems.append(f"argv[{i}] carries evaluator material")
        return problems

    def _bind_host(self, adapter) -> tuple:
        """host_binding against the campaign, then against the binding of the campaign's first launch
        (coordinator/host_binding.json, written once): every run launches the host identically."""
        binding, problems = host_binding(adapter, self.host, self.budget, self.manifest["kind"])
        if problems:
            return binding, problems
        path = self.dir / COORDINATOR / HOST_BINDING
        if os.path.lexists(path):
            if canonical.canonical_bytes(canonical.strict_load(path)) != canonical.canonical_bytes(binding):
                problems.append(f"the host launch differs from the campaign's first launch (coordinator/{HOST_BINDING})")
        else:
            canonical.write_once(path, _pretty(binding))
        return binding, problems

    def _not_started(self, run, reason, **extra):
        _record(self.run_dir(run["run_id"]) / "journal.jsonl", "not_started", reason=reason,
                charge={"usd": 0.0, "usd_basis": "not_started", "seconds": 0.0, "seconds_basis": "not_started"},
                **extra)
        return self._seal(run)

    def _crash(self, run, cause, **extra):
        """A lost launch: census of exactly that launch, charge at the cap (unknown), journal, seal.
        Never relaunched."""
        require(cause in LOST_CAUSES, f"lost launch cause: one of {list(LOST_CAUSES)}")
        found = self._lost_census(run["run_id"])
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
        called = (self.run_dir(run_id) / "host" / "launch_call.json").is_file()
        return {"method": "no process_started record: nothing to census", "launch": None, "found": [], "killed": [],
                "survivors": [], "foreign": [], "complete": not called,
                "note": "the launcher was called but no process start was journaled; survivors unknown"
                if called else None}

    def _resume(self, run, records):
        states = {r["state"]: r for r in records}
        if "not_started" in states or "exited" in states or "interrupted_crash" in states:
            return self._seal(run)
        if "launched" in states:
            if self._launcher_called(run["run_id"]):
                return self._crash(run, "coordinator_interrupted")
            return self._not_started(run, "coordinator interrupted after the launch record and before the launcher "
                                          "was called (no launch call and no process start on record, so no process "
                                          "was started); no retry under policy none")
        if "admission_failed" in states:
            return self._not_started(run, states["admission_failed"]["details"].get("reason") or "admission failed")
        return self._not_started(run, f"coordinator interrupted before launch (last state {records[-1]['state']}); "
                                      "no retry under policy none")

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
        files.update(self._broker_files(rid, flags))
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

    def _broker_files(self, run_id, flags) -> dict:
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
        return files


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

def run_campaign(campaign_dir, *, adapter_factory, behavior_plan=None, only=None) -> dict:
    """Process the registry's assignments in order (or the subset ``only``, still in registry order).

    ``adapter_factory(assignment)`` returns the Adapter for one run; ``assignment`` carries
    run_id, task_id, seed, behavior, python (the subject interpreter) and launcher (the
    coordinator's recording launcher, which the adapter must use: a run whose adapter holds another
    launcher is not started). The arm is never passed: everything arm-dependent (the fake host's
    behavior) is resolved here, and a real host must launch identically in every run
    (``host_binding``, the campaign's first launch in ``coordinator/host_binding.json``).
    ``behavior_plan`` (fake host only) is {"default": behavior, "by_task_arm": {"<task_id>|<arm>":
    behavior}}.

    Before each launch the run's treatment is re-verified against the frozen campaign (the code
    behind every common hash, the frozen texts, the prompt's instruction segment, the request, the
    materialized workspace; ``admitted.verified`` in the journal) and a drifted run is not started;
    after it, a drift is flagged ``code_drift_during_run``. A failure before the recording launcher
    was called (no launch call and no process start on record) is not_started with no charge.
    """
    campaign = _Campaign(campaign_dir)
    if campaign.host["adapter"] != "fake":   # a real subject never meets an unverified gate (§12.3, R0.1)
        problem = behavioral_record_problem(campaign.dir, campaign.campaign_sha256)
        require(problem is None, f"refusing to launch a real host: {problem}")
    plan, plan_sha = campaign.plan(behavior_plan)
    runs = campaign.registry["runs"]
    if only is not None:
        wanted = set(only)
        unknown = sorted(wanted - {r["run_id"] for r in runs})
        require(not unknown, f"only: not assignments of this campaign: {unknown}")
        runs = [r for r in runs if r["run_id"] in wanted]
    # One coordinator per campaign: two would both find an empty journal and launch the same run.
    with campaign_lock(campaign.dir):
        results = [campaign.process(run, plan, plan_sha, adapter_factory) for run in runs]
    return {"campaign_dir": str(campaign.dir), "synthetic": campaign.manifest["kind"] == "synthetic",
            "behavior_plan_sha256": plan_sha, "runs": results, "spent": campaign.spent()}


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
        by_kind = {side: {INPUT_KINDS[name]: data for name, data in campaign.inputs(task, side).items()}
                   for side in ("current", "prior")}
        secret, arms = secrets.token_bytes(32), list(contracts.ARMS)

        def prepare(arm):
            setting = campaign.manifest["arms"][arm]["guard"]
            broker = Broker(root / arm, guard_mode=setting["mode"], feedback=setting["feedback"],
                            budgets={"max_broker_ops": campaign.budget["max_broker_ops"],
                                     "max_fits": campaign.budget["max_fits"]},
                            python=campaign.config["stage_python"], env=campaign.config["stage_env"], secret=secret)
            broker.register_inputs(by_kind["current"])
            broker.create_prior(by_kind["prior"])
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


def behavioral_record_problem(campaign_dir, campaign_sha256):
    """None when ``coordinator/behavioral/<n>/result.json`` holds a passing behavioral check of this
    campaign's frozen campaign.json (its sha256), else the problem. A real host's campaign is launched
    only after one (run_campaign): the manifest check alone cannot see a no-op or arm-dependent guard."""
    parent = Path(campaign_dir) / COORDINATOR / BEHAVIORAL
    if not parent.is_dir() or parent.is_symlink():
        return "no behavioral treatment check was recorded (cli.py treatment-diff --behavioral)"
    for path in sorted(parent.glob("*/result.json")):
        try:
            record = canonical.strict_load(path)
        except (ContractError, OSError, ValueError):
            continue
        if (isinstance(record, dict) and record.get("campaign_sha256") == campaign_sha256
                and isinstance(record.get("result"), dict) and record["result"].get("ok") is True):
            return None
    return "no passing behavioral treatment check of this campaign.json was recorded (cli.py treatment-diff --behavioral)"


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
           "behavioral_record_problem"]
