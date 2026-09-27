"""WP07 assignment coordinator and CLI (slice design §3, §6, §10).

Everything here is SYNTHETIC engineering evidence: the fake subject (no model), the development
family, the stub judge reports (labeled as such), the budgets and the simulated interruptions are
test fixtures, not agent results. The broker runs the real RAVEL kernel under the test
interpreter; launches use the Seatbelt sandbox where sandbox-exec and its census work and fall
back to sandbox ``none_test_only`` elsewhere, which every run.json then records. One campaign
always runs ``none_test_only`` so that flag is asserted on every platform.
"""
import copy
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("pyhf", reason="the broker's stage workers run the pyhf kernel under the test interpreter")

from governance import broker as broker_module  # noqa: E402
from governance import campaign_manifest, canonical, cli, contracts, isolation, runner, treatment  # noqa: E402
from governance import guard  # noqa: E402
from governance.adapters.base import HostDriftError  # noqa: E402
from governance.adapters.claude_cli import ClaudeCliAdapter  # noqa: E402
from governance.adapters.codex_cli import CodexCliAdapter  # noqa: E402
from governance.adapters.fake import FakeAdapter  # noqa: E402
from governance.canonical import ContractError  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "benchmarks" / "governance" / "cli.py"
PYTHON = os.path.realpath(getattr(sys, "_base_executable", sys.executable))
PREFIX = os.path.realpath(sys.base_prefix)
SANDBOX = ("seatbelt" if isolation.sandbox_available() and isolation.census_available()
           and PYTHON.startswith(PREFIX + "/") else "none_test_only")
CREATED = "2026-09-25T12:00:00Z"
STUB_SCORER = "synthetic-stub-judge (test fixture)"
SEALED_ALWAYS = {"run.json", "prompt.txt", "treatment_manifest.json"}
SEALED_LAUNCHED = SEALED_ALWAYS | {"adapter_result.json", "stdout.jsonl", "stderr.txt", "final_text.txt",
                                  "launch.json", "broker/custody.jsonl"}
LAUNCH_ENV = sorted(["HOME", "LANG", "PATH", "TMPDIR", "RAVEL_TASK_ENDPOINT", "RAVEL_TASK_TOKEN"])
SUBJECT_TEMPLATE = ("request.md", "tools.md", "bin/ravel-task")
ZERO_CHARGE = {"usd": 0.0, "usd_basis": "not_started", "seconds": 0.0, "seconds_basis": "not_started"}


def build(base, campaign_id="synthetic-runner-test", sandbox=SANDBOX, **budget):
    return runner.build_synthetic_campaign(base / "store", campaign_id=campaign_id, created_utc=CREATED, seeds=[11],
                                           schedule_seed=7, subjects_root=base / "subjects", sandbox=sandbox,
                                           budget=budget or None)


def registry(campaign):
    return canonical.strict_load(campaign / "registry.json")


def run_of(campaign, task_id, arm):
    return next(r for r in registry(campaign)["runs"] if (r["task_id"], r["arm"]) == (task_id, arm))


def journal(campaign, run_id):
    return runner.read_journal(campaign / "runs" / run_id / "journal.jsonl")


def states(campaign, run_id):
    return [r["state"] for r in journal(campaign, run_id)]


def last(campaign, run_id, state):
    return [r for r in journal(campaign, run_id) if r["state"] == state][-1]["details"]


def sealed(campaign, run_id):
    return campaign / "runs" / run_id / "sealed"


def sealed_names(campaign, run_id):
    root = sealed(campaign, run_id)
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def sealed_json(campaign, run_id, name):
    return canonical.strict_load(sealed(campaign, run_id) / name)


def run_record(campaign, run_id):
    return sealed_json(campaign, run_id, "run.json")


def opaque_of(campaign, run_id):
    """The documented rule: first 16 hex of HMAC(campaign secret, run_id)."""
    secret = (campaign / "coordinator" / "campaign_secret").read_bytes()
    return hmac.new(secret, run_id.encode(), hashlib.sha256).hexdigest()[:16]


def never(assignment):
    raise AssertionError(f"the adapter factory must not be called (run {assignment['run_id']})")


def files_under(root):
    return [p for p in Path(root).rglob("*") if p.is_file() and not p.is_symlink()]


def expected_flags(*extra, sandbox=SANDBOX):
    return sorted(set(extra) | ({"sandbox_none_test_only"} if sandbox == "none_test_only" else set()))


def plant(monkeypatch, data, skip=()):
    """SYNTHETIC leak: every workspace (except runs in ``skip``) gets ``data`` as inputs/notes.json."""
    original = runner._subject_files
    monkeypatch.setattr(runner, "_subject_files", lambda c, r: original(c, r) if r["run_id"] in skip
                        else {**original(c, r), "inputs/notes.json": data})


def simulate_launched(campaign, run_id, subject_root, started=None, called=False):
    """SYNTHETIC journal of a coordinator killed after the launch: materialized, launched, no exit;
    ``started`` adds the launcher's process_started record ({pid, pgid, marker, started_at, leader_start});
    ``called`` adds the recording launcher's host/launch_call.json (the launcher was entered, no process
    start journaled). Without either, the resume proves no process was started (not_started, R1.4)."""
    path = campaign / "runs" / run_id / "journal.jsonl"
    assignment = {"adapter": "fake", "behavior": "reference", "behavior_plan_sha256": None}
    runner._record(path, "materialized", opaque_handle=subject_root.name, subject_root=str(subject_root),
                   workspace_files={}, **assignment)
    runner._record(path, "launched", executor_id="synthetic-fake:reference", timeout_s=100, profile_sha256=None,
                   prompt_sha256="0" * 64, **assignment)
    if called:
        canonical.write_once(campaign / "runs" / run_id / "host" / "launch_call.json", runner._pretty(
            {"argv": [PYTHON, "-I", "-B", str(subject_root / "tmp" / "fake_subject.py"), "reference"],
             "env_names": LAUNCH_ENV, "cwd": str(subject_root), "timeout_s": 100, "profile_sha256": None}))
    if started is not None:
        runner._record(path, "process_started", **started)


def epoch(utc):
    return datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()


def sleeper(*extra):
    """A SYNTHETIC process this test starts and ends itself, leading its own group and session."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *map(str, extra)],
                            start_new_session=True, stdin=subprocess.DEVNULL)


class RaisingAdapter(FakeAdapter):
    """SYNTHETIC failure: the fake subject really runs, then the adapter raises (a bug or Ctrl-C)."""

    def __init__(self, error, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = error

    def run(self, **kwargs):
        super().run(**kwargs)
        raise self.error("SYNTHETIC failure after the launch")


@pytest.fixture
def base(tmp_path_factory):
    """A neutral directory name: subject-visible paths may not contain arm words."""
    return Path(os.path.realpath(tmp_path_factory.mktemp("lab")))


@pytest.fixture(scope="module")
def launched(tmp_path_factory):
    """Three SYNTHETIC assignments through the real broker and fake adapter (sandboxed when possible):
    V0 reference in baseline, V3 reference in full, V1 stale_copy in enforcement."""
    base = Path(os.path.realpath(tmp_path_factory.mktemp("lab")))
    campaign = build(base, seconds_per_run=120)
    picks = {"reuse": run_of(campaign, "lf-a", "baseline"), "refusal": run_of(campaign, "lf-d", "full"),
             "stale": run_of(campaign, "lf-b", "enforcement")}
    plan = {"default": "reference", "by_task_arm": {"lf-b|enforcement": "stale_copy"}}
    tokens, calls, original = [], [], broker_module.Broker.start

    def start(self):
        endpoint, token = original(self)
        tokens.append(token)
        return endpoint, token

    keys = []

    def factory(assignment):
        calls.append(assignment["run_id"])
        keys.append(sorted(assignment))
        return runner.fake_adapter_factory(assignment)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(broker_module.Broker, "start", start)
        result = runner.run_campaign(campaign, adapter_factory=factory, behavior_plan=plan,
                                     only=[r["run_id"] for r in picks.values()])
    return SimpleNamespace(base=base, campaign=campaign, picks=picks, plan=plan, tokens=tokens, calls=calls,
                           result=result, keys=keys)


@pytest.fixture(scope="module")
def lost(tmp_path_factory):
    """Every assignment of one SYNTHETIC campaign sealed, through the real broker and fake subject:
    adapter_error (the adapter raises after the subject ran), interrupted (Ctrl-C after the launch,
    then a resume), launch_error (no interpreter), seal_crash (sealing fails after the exit, then a
    resume), env_refused (a canary in the launch environment), broker_failed (prior stages fail);
    the other ten are refused at workspace admission."""
    base = Path(os.path.realpath(tmp_path_factory.mktemp("lab")))
    campaign = build(base, campaign_id="synthetic-runner-lost", seconds_per_run=120)
    names = {"adapter_error": ("lf-a", "baseline"), "interrupted": ("lf-a", "instructions"),
             "launch_error": ("lf-a", "enforcement"), "seal_crash": ("lf-a", "full"),
             "env_refused": ("lf-b", "baseline"), "broker_failed": ("lf-b", "instructions")}
    picks = {name: run_of(campaign, *key)["run_id"] for name, key in names.items()}
    role = {rid: name for name, rid in picks.items()}
    calls = Counter()

    def factory(a):
        calls[a["run_id"]] += 1
        name = role[a["run_id"]]
        if name in ("adapter_error", "interrupted"):
            error = RuntimeError if name == "adapter_error" else KeyboardInterrupt
            return RaisingAdapter(error, a["behavior"], a["launcher"], python=a["python"])
        if name == "launch_error":
            return FakeAdapter(a["behavior"], a["launcher"], python="/nonexistent/python")
        return runner.fake_adapter_factory(a)

    def go(name, **kwargs):
        return runner.run_campaign(campaign, adapter_factory=factory, only=[picks[name]], **kwargs)

    go("adapter_error")
    with pytest.raises(KeyboardInterrupt):
        go("interrupted")
    before_resume = states(campaign, picks["interrupted"])
    go("interrupted")
    go("launch_error")
    real, failures = canonical.make_read_only, []

    def fail_once(root):
        if not failures:
            failures.append(root)
            raise OSError("SYNTHETIC crash while sealing")
        return real(root)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(canonical, "make_read_only", fail_once)
        with pytest.raises(OSError, match="SYNTHETIC crash while sealing"):
            go("seal_crash")
    before_reseal = states(campaign, picks["seal_crash"])
    go("seal_crash")
    canary = (campaign / "coordinator" / "canary.txt").read_text().strip()
    with pytest.MonkeyPatch.context() as patch:
        subject_env = isolation.subject_env
        patch.setattr(isolation, "subject_env", lambda **kw: {**subject_env(**kw), "RAVEL_NOTE": canary})
        go("env_refused")

    def broken_prior(self, prior):
        raise RuntimeError("SYNTHETIC prior stage failure")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(broker_module.Broker, "create_prior", broken_prior)
        go("broker_failed")
    with pytest.MonkeyPatch.context() as patch:
        plant(patch, (campaign / "coordinator" / "family" / "index.json").read_bytes(), skip=set(picks.values()))
        rest = runner.run_campaign(campaign, adapter_factory=never)
    return SimpleNamespace(base=base, campaign=campaign, picks=picks, calls=calls, rest=rest,
                           before_resume=before_resume, before_reseal=before_reseal)


# ---------------------------------------------------------------- launched assignments

def test_launched_runs_are_journaled_in_registry_order(launched):
    order = [r["run_id"] for r in registry(launched.campaign)["runs"]
             if r["run_id"] in {p["run_id"] for p in launched.picks.values()}]
    assert launched.calls == order
    assert [r["run_id"] for r in launched.result["runs"]] == order
    assert {r["action"] for r in launched.result["runs"]} == {"sealed"}
    assert launched.result["synthetic"] is True
    for run in launched.picks.values():
        assert states(launched.campaign, run["run_id"]) == ["materialized", "admitted", "launched", "process_started",
                                                            "exited", "sealed"]
        started = last(launched.campaign, run["run_id"], "process_started")   # the census record of the launch
        assert isolation.check_launch_record(started) == started and started["pid"] == started["pgid"]
        assert (started["marker"] is None) == (SANDBOX != "seatbelt")
        times = {r["state"]: epoch(r["time_utc"]) for r in journal(launched.campaign, run["run_id"])}
        assert times["launched"] <= started["started_at"] <= times["process_started"] <= times["exited"]
        assert started["started_at"] - isolation.START_SLACK_S <= started["leader_start"] <= times["process_started"]
        exited = last(launched.campaign, run["run_id"], "exited")
        assert exited["status_hint"] == "exited" and exited["exit_code"] == 0
        assert exited["charge"]["usd"] == 0.0 and exited["charge"]["usd_basis"] == "none_synthetic"
        assert exited["charge"]["seconds_basis"] == "measured" and exited["charge"]["seconds"] > 0
    assert launched.result["spent"]["usd"] == 0.0


def test_sealed_layout_evidence_manifest_and_run_record(launched):
    campaign, manifest = launched.campaign, canonical.strict_load(launched.campaign / "campaign.json")
    instructions = treatment.frozen_bytes("instructions").decode()
    for run in launched.picks.values():
        rid, root = run["run_id"], sealed(launched.campaign, run["run_id"])
        names = sealed_names(campaign, rid)
        assert SEALED_LAUNCHED <= names
        assert any(n.startswith("broker/artifacts/art-") for n in names)
        assert "subject_output/submission-01.json" in names
        entries = canonical.tree_manifest(root)
        assert canonical.strict_load(root.parent / "evidence_manifest.json") == entries
        digest = runner.evidence_digest(root.parent)
        assert digest == last(campaign, rid, "sealed")["evidence_sha256"] == canonical.digest(entries)
        assert all(not (p.stat().st_mode & 0o222) for p in [root, *root.rglob("*")])
        record = run_record(campaign, rid)
        runner.validate_run_record(record)
        behavior = launched.plan["by_task_arm"].get(f"{run['task_id']}|{run['arm']}", "reference")
        assert (record["run_id"], record["task_id"], record["seed"], record["arm"]) == (rid, run["task_id"],
                                                                                      run["seed"], run["arm"])
        assert record["campaign_id"] == manifest["campaign_id"] and record["campaign_kind"] == "synthetic"
        assert record["synthetic"] is True and record["adapter"] == "fake"
        assert record["behavior"] == behavior and record["executor_id"] == f"synthetic-fake:{behavior}"
        assert record["behavior_plan_sha256"] == canonical.digest(launched.plan)
        assert record["status_hint"] == "exited" and record["not_started_reason"] is None
        times = {r["state"]: r["time_utc"] for r in journal(campaign, rid)}
        assert (record["started_utc"], record["ended_utc"]) == (times["launched"], times["exited"])
        assert record["started_utc"] < record["ended_utc"]
        assert (record["profile_sha256"] is not None) == (SANDBOX == "seatbelt")
        assert record["validity_flags"] == expected_flags()
        prompt = (root / "prompt.txt").read_bytes()
        assert record["prompt_sha256"] == canonical.sha256_bytes(prompt)
        assert (instructions in prompt.decode()) == contracts.ARMS[run["arm"]]["instructions"]
        assert record["treatment_manifest_sha256"] == canonical.digest(manifest["arms"][run["arm"]]) \
            == canonical.digest(canonical.strict_load(root / "treatment_manifest.json"))
        result = canonical.strict_load(root / "adapter_result.json")
        assert (result["raw_stdout"], result["raw_stderr"]) == ("stdout.jsonl", "stderr.txt")
        assert result["details"]["stdin_sha256"] == record["prompt_sha256"] and result["synthetic"] is True
        assert (root / "final_text.txt").read_text() == result["final_text"]
        launch = canonical.strict_load(root / "launch.json")
        assert set(launch) == set(runner.LAUNCH_FIELDS)
        assert launch["cwd_opaque"] == "$SUBJECT_ROOT" and launch["exit_code"] == 0 and launch["survivors"] == []
        assert launch["timeout_s"] == 120 and launch["timed_out"] is False
        evaluator = campaign / "evaluator" / rid          # exactly the layout's two evaluator files
        assert sorted(p.name for p in evaluator.iterdir()) == ["oracle.json", "task_definition.json"]
        assert canonical.sha256_file(evaluator / "oracle.json") == \
            next(t for t in registry(campaign)["spec"]["tasks"] if t["id"] == run["task_id"])["oracle_sha256"]
        materialized = last(campaign, rid, "materialized")["workspace_files"]["bin/ravel-task"]
        environment = canonical.strict_load(campaign / "coordinator" / "environment.json")
        assert materialized == environment["materialized_client_sha256"]
    assert campaign_manifest.verify(campaign) == {"ok": True, "errors": []}


def test_custody_records_the_real_broker_in_each_guard_setting(launched):
    def custody(run):
        return canonical.read_jsonl(sealed(launched.campaign, run["run_id"]) / "broker" / "custody.jsonl")[0]

    def submits(run):
        return [e for e in custody(run) if e["op"] == "submit" and e["ok"]]

    reuse, refusal, stale = launched.picks["reuse"], launched.picks["refusal"], launched.picks["stale"]
    assert not [e for e in custody(reuse) if e["op"] == "fit"]            # V0: the fit is reused, never executed
    assert [s["guard"]["accepted"] for s in submits(reuse)] == [True]
    assert submits(refusal)[0]["args"]["refusal"] is not None and submits(refusal)[0]["guard"]["accepted"] is True
    blocked = submits(stale)[0]["guard"]
    assert blocked["mode"] == "block" and blocked["accepted"] is False
    assert "stale_numerical_dependency" in {d["code"] for d in blocked["diagnostics"]}


def test_opaque_handles_and_subject_roots_hide_arms_and_evaluator_content(launched):
    campaign = launched.campaign
    evaluator = {canonical.sha256_file(p) for p in files_under(campaign / "evaluator")}
    family = campaign / "coordinator" / "family"
    evaluator |= {canonical.sha256_file(family / p)
                  for p in canonical.strict_load(family / "index.json")["path_roles"]["evaluator_private"]}
    evaluator.add(canonical.sha256_file(campaign / "coordinator" / "campaign_secret"))
    canary = (campaign / "coordinator" / "canary.txt").read_text().strip().encode()
    oracles = [canonical.strict_load(p) for p in (campaign / "evaluator").glob("*/oracle.json")]
    values = {v.encode() for o in oracles for v in runner._value_canaries(o)}
    assert values and all(b"." in v for v in values)
    subjects = launched.base / "subjects"
    for run in launched.picks.values():
        rid, opaque = run["run_id"], run_record(campaign, run["run_id"])["opaque_handle"]
        assert re.fullmatch(r"[0-9a-f]{16}", opaque) and opaque == opaque_of(campaign, rid)
        assert opaque not in rid and opaque != rid[:16]
        assert not [w for w in contracts.LEAKY_WORDS if w in opaque] and not treatment.arm_identifying_terms(opaque)
        root = subjects / opaque
        assert root.is_dir() and not treatment.arm_identifying_terms(str(root))
        template = [root / name for name in SUBJECT_TEMPLATE] + sorted((root / "inputs").iterdir())
        for path in template:
            assert not treatment.arm_identifying_terms(path.read_text()), path
            assert not treatment.arm_identifying_terms(path.relative_to(root).as_posix())
            assert not any(v in path.read_bytes() for v in values), path
        assert (root / "bin" / "ravel-task").read_bytes().startswith(f"#!{PYTHON} -I\n".encode())
    for path in files_under(subjects):
        data = path.read_bytes()
        assert canonical.sha256_bytes(data) not in evaluator, path
        assert canary not in data, path
    assert not runner._within(os.path.realpath(subjects), os.path.realpath(campaign.parent.parent))
    assert not runner._within(os.path.realpath(campaign / "evaluator"), os.path.realpath(subjects))


def test_launch_records_environment_names_never_values(launched):
    assert len(launched.tokens) == len(launched.picks)
    for run in launched.picks.values():
        launch = canonical.strict_load(sealed(launched.campaign, run["run_id"]) / "launch.json")
        assert launch["env_names"] == LAUNCH_ENV
        prompt = (sealed(launched.campaign, run["run_id"]) / "prompt.txt").read_text()
        assert all(prompt.strip() not in arg for arg in launch["argv"])
    tokens = [t.encode() for t in launched.tokens]
    for path in files_under(launched.campaign) + files_under(launched.base / "subjects"):
        data = path.read_bytes()
        assert not any(t in data for t in tokens), path


def test_resume_skips_sealed_runs_without_touching_them(launched):
    ids = [r["run_id"] for r in launched.picks.values()]
    paths = [launched.campaign / "runs" / rid / "journal.jsonl" for rid in ids]
    before = [p.read_bytes() for p in paths]
    result = runner.run_campaign(launched.campaign, adapter_factory=never, only=ids)
    assert {r["action"] for r in result["runs"]} == {"skipped"}
    assert [p.read_bytes() for p in paths] == before
    for rid in ids:
        assert runner.evidence_digest(launched.campaign / "runs" / rid) == last(launched.campaign, rid,
                                                                               "sealed")["evidence_sha256"]


# ---------------------------------------------------------------- lost launches, launch errors, failures

@pytest.mark.parametrize("name,cause", [("adapter_error", "adapter_error"), ("interrupted", "coordinator_interrupted")])
def test_lost_launch_is_sealed_interrupted_charged_at_the_cap_and_never_relaunched(lost, name, cause):
    campaign, rid = lost.campaign, lost.picks[name]
    assert lost.calls[rid] == 1                                   # never relaunched
    if name == "interrupted":                                     # the Ctrl-C left the launch open
        assert lost.before_resume == ["materialized", "admitted", "launched", "process_started"]
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "process_started", "interrupted_crash",
                                     "sealed"]
    crash = last(campaign, rid, "interrupted_crash")
    assert crash["cause"] == cause and crash["note"] == runner.LOST_NOTES[cause]
    assert crash["census"]["launch"] == last(campaign, rid, "process_started")   # exactly that launch's census
    assert crash["census"]["found"] == [] and crash["census"]["survivors"] == [] and crash["census"]["complete"]
    assert crash["charge"] == {"usd": 0.0, "usd_basis": "none_synthetic", "seconds": 120.0,
                               "seconds_basis": "per_run_cap_unknown"}    # unknown time: the cap, never zero
    record = run_record(campaign, rid)
    runner.validate_run_record(record)
    assert record["status_hint"] == "interrupted" and record["executor_id"] == "synthetic-fake:reference"
    # a lost sandboxed launch's System V IPC residue is unknown (its census lists none): flagged (invalidating)
    assert record["validity_flags"] == expected_flags(cause, *(["ipc_residue"] if SANDBOX == "seatbelt" else []))
    assert record["ended_utc"] == [r for r in journal(campaign, rid) if r["state"] == "interrupted_crash"][0][
        "time_utc"]
    assert SEALED_LAUNCHED <= sealed_names(campaign, rid) and "subject_output/submission-01.json" in \
        sealed_names(campaign, rid)
    result = sealed_json(campaign, rid, "adapter_result.json")
    assert result["status_hint"] == "launch_error" and result["exit_code"] is None and result["synthetic"] is True
    assert result["details"]["authored_by"] == "coordinator" and result["details"]["cause"] == cause
    assert result["details"]["census"] == crash["census"] and result["validity"] == {"ok": True, "invalidating": []}
    assert (sealed(campaign, rid) / "stdout.jsonl").read_bytes()   # the subject's real stream is kept
    launch = sealed_json(campaign, rid, "launch.json")
    assert launch["argv"][0] == PYTHON and launch["env_names"] == LAUNCH_ENV and launch["exit_code"] is None
    assert (launch["killed"], launch["survivors"], launch["timeout_s"]) == (False, [], 120)
    assert runner.evidence_digest(campaign / "runs" / rid) == last(campaign, rid, "sealed")["evidence_sha256"]


def test_launch_error_is_sealed_with_the_recorded_call(lost):
    campaign, rid = lost.campaign, lost.picks["launch_error"]
    assert lost.calls[rid] == 1
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "exited", "sealed"]   # never started
    exited = last(campaign, rid, "exited")
    assert exited["status_hint"] == "launch_error" and exited["exit_code"] is None
    assert exited["charge"]["seconds"] == 120.0 and exited["charge"]["seconds_basis"] == "per_run_cap_unknown"
    record = run_record(campaign, rid)
    assert record["status_hint"] == "launch_error" and record["validity_flags"] == expected_flags()
    launch = sealed_json(campaign, rid, "launch.json")
    assert launch["argv"][0] == "/nonexistent/python" and launch["env_names"] == LAUNCH_ENV
    assert launch["exit_code"] is None and launch["wall_seconds"] is None
    assert "launch_error:" in (sealed(campaign, rid) / "stderr.txt").read_text()
    assert "authored_by" not in sealed_json(campaign, rid, "adapter_result.json")["details"]


def test_crash_between_exit_and_seal_reseals_without_relaunching(lost):
    campaign, rid = lost.campaign, lost.picks["seal_crash"]
    assert lost.calls[rid] == 1
    assert lost.before_reseal == ["materialized", "admitted", "launched", "process_started", "exited"]
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "process_started", "exited", "sealed"]
    run_dir = campaign / "runs" / rid
    assert (run_dir / "sealed.incomplete-1").is_dir() and not (run_dir / "sealed.incomplete-2").exists()
    assert run_record(campaign, rid)["status_hint"] == "exited"
    assert runner.evidence_digest(run_dir) == last(campaign, rid, "sealed")["evidence_sha256"]


def test_environment_and_broker_failures_are_not_started_with_zero_resources(lost):
    campaign = lost.campaign
    for name, stage, text in (("env_refused", "environment", "env_canary"),
                              ("broker_failed", "broker", "SYNTHETIC prior stage failure")):
        rid = lost.picks[name]
        assert lost.calls[rid] == 0
        assert states(campaign, rid) == ["materialized", "admission_failed", "not_started", "sealed"]
        assert last(campaign, rid, "admission_failed")["stage"] == stage
        assert last(campaign, rid, "not_started")["charge"] == ZERO_CHARGE
        record = run_record(campaign, rid)
        runner.validate_run_record(record)
        assert record["status_hint"] == "not_started" and text in record["not_started_reason"]
        assert record["started_utc"] == record["ended_utc"] and record["executor_id"] is None
        assert SEALED_ALWAYS | {"broker/custody.jsonl"} <= sealed_names(campaign, rid)
        assert "launch.json" not in sealed_names(campaign, rid)
    assert {r["action"] for r in lost.rest["runs"]} == {"skipped", "sealed"}
    assert runner.unsealed_runs(campaign) == []


def test_interrupted_launch_census_kills_the_journaled_launch_and_seals_what_is_known(base):
    campaign = build(base, seconds_per_run=100, global_seconds_cap=1600)
    rid = registry(campaign)["runs"][0]["run_id"]
    root = base / "subjects" / opaque_of(campaign, rid)
    (root / "output").mkdir(parents=True)
    (root / "output" / "partial.json").write_text('{"synthetic": true}\n')
    started_at = time.time()
    survivor = sleeper()     # SYNTHETIC unsandboxed subject that outlived its coordinator (leads its own group)
    record = {"pid": survivor.pid, "pgid": survivor.pid, "marker": None, "started_at": started_at,
              "leader_start": isolation._start_time(survivor.pid)}   # as the launcher records its leader
    try:
        simulate_launched(campaign, rid, root, started=record)
        result = runner.run_campaign(campaign, adapter_factory=never, only=[rid])
        assert survivor.wait(timeout=10) == -signal.SIGKILL
    finally:
        survivor.kill()
        survivor.wait()
    assert states(campaign, rid) == ["materialized", "launched", "process_started", "interrupted_crash", "sealed"]
    crash = last(campaign, rid, "interrupted_crash")
    assert crash["cause"] == "coordinator_interrupted" and crash["note"] == runner.INTERRUPTED
    census = crash["census"]
    assert census["launch"] == record and census["method"].startswith("unsandboxed launch")
    assert (census["found"], census["killed"], census["survivors"], census["foreign"]) == (
        [survivor.pid], [survivor.pid], [], [])
    assert census["complete"] is True
    assert crash["charge"] == {"usd": 0.0, "usd_basis": "none_synthetic", "seconds": 100.0,
                               "seconds_basis": "per_run_cap_unknown"}
    record = run_record(campaign, rid)
    runner.validate_run_record(record)
    assert record["status_hint"] == "interrupted" and record["executor_id"] == "synthetic-fake:reference"
    assert record["validity_flags"] == expected_flags("coordinator_interrupted", "custody_missing",
                                                      "launch_unrecorded", "raw_streams_missing",
                                                      "subject_outlived_coordinator")
    launch = sealed_json(campaign, rid, "launch.json")
    assert (launch["argv"], launch["env_names"], launch["cwd_opaque"], launch["timeout_s"]) == ([], [], None, 100)
    assert (launch["exit_code"], launch["killed"], launch["survivors"]) == (None, True, [])
    assert sealed_names(campaign, rid) >= {"adapter_result.json", "final_text.txt", "subject_output/partial.json"}
    assert result["runs"][0]["status_hint"] == "interrupted" and result["spent"]["seconds"] == 100.0
    again = runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    assert again["runs"][0]["action"] == "skipped" and again["spent"] == result["spent"]   # no fresh budget


def test_resume_never_signals_by_command_line_or_a_group_it_did_not_start(base):
    """The lost launch's census is isolation.census_launch on its journaled record only: a process whose
    argv names the subject root (the retired command-line census killed it) and the recorded group id, now
    held by a process older than the launch or by a newer session leader (whose members all started after
    the launch: the start-time floor alone would have killed them), are never signalled."""
    assert not hasattr(runner, "census")                     # the command-line census is gone
    campaign = build(base, seconds_per_run=100)
    rid, newer_rid = (r["run_id"] for r in registry(campaign)["runs"][:2])
    root = base / "subjects" / opaque_of(campaign, rid)
    root.mkdir(parents=True)
    older = sleeper()                                         # SYNTHETIC: holds the first recorded group id
    procs = [older]
    try:
        time.sleep(0.3)                                       # the launch began after it started
        started_at = time.time()
        older_start = isolation._start_time(older.pid)
        # The recorded leaders' starts are never a whole number of seconds from the holders' starts as read
        # (unprovable on Linux, E-23): offsets with a fractional .37 s.
        leader_start = older_start + math.ceil(started_at - older_start) + 0.37   # after the launch began
        procs.append(sleeper(root))                           # SYNTHETIC: argv names the subject root
        simulate_launched(campaign, rid, root, started={"pid": older.pid, "pgid": older.pid, "marker": None,
                                                        "started_at": started_at, "leader_start": leader_start})
        procs.append(sleeper())                               # a newer session leader holds its id now;
        long_ago = isolation._start_time(procs[2].pid) - 60.37   # SYNTHETIC lost launch whose group has ended
        simulate_launched(campaign, newer_rid, base / "subjects" / opaque_of(campaign, newer_rid),
                          started={"pid": procs[2].pid, "pgid": procs[2].pid, "marker": None,
                                   "started_at": long_ago - 0.01, "leader_start": long_ago})
        runner.run_campaign(campaign, adapter_factory=never, only=[rid, newer_rid])
        time.sleep(0.2)
        assert [proc.poll() for proc in procs] == [None, None, None]
    finally:
        for proc in procs:
            proc.kill()
            proc.wait()
    for run_id, holder in ((rid, older), (newer_rid, procs[2])):
        census = last(campaign, run_id, "interrupted_crash")["census"]
        assert (census["found"], census["killed"], census["survivors"]) == ([], [], [])
        assert census["foreign"] == [holder.pid] and census["complete"] is True
        record = run_record(campaign, run_id)
        assert record["status_hint"] == "interrupted" and "subject_outlived_coordinator" not in record["validity_flags"]


def test_interruption_before_launch_is_not_started(base):
    campaign = build(base)
    rid = registry(campaign)["runs"][1]["run_id"]
    path = campaign / "runs" / rid / "journal.jsonl"
    runner._record(path, "materialized", opaque_handle="0" * 16, subject_root="/nonexistent", workspace_files={},
                   adapter="fake", behavior="reference", behavior_plan_sha256=None)   # SYNTHETIC journal
    runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    assert states(campaign, rid) == ["materialized", "not_started", "sealed"]
    assert "coordinator interrupted before launch" in run_record(campaign, rid)["not_started_reason"]


def test_a_torn_journal_is_refused(base):
    campaign = build(base)
    rid = registry(campaign)["runs"][0]["run_id"]
    path = campaign / "runs" / rid / "journal.jsonl"
    runner._record(path, "materialized", opaque_handle="0" * 16, subject_root="/nonexistent", workspace_files={})
    with open(path, "ab") as handle:
        handle.write(b'{"state": "launched", "time_')          # SYNTHETIC torn write
    with pytest.raises(ContractError, match="malformed journal"):
        runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    assert not (campaign / "runs" / rid / "sealed").exists()


def test_global_budget_admission_refuses_below_the_per_run_cap(base):
    campaign = build(base, seconds_per_run=100, global_seconds_cap=150)
    first, second = registry(campaign)["runs"][:2]
    simulate_launched(campaign, first["run_id"], base / "subjects" / opaque_of(campaign, first["run_id"]), called=True)
    result = runner.run_campaign(campaign, adapter_factory=never, only=[first["run_id"], second["run_id"]])
    assert [r["status_hint"] for r in result["runs"]] == ["interrupted", "not_started"]
    assert states(campaign, second["run_id"]) == ["materialized", "admission_failed", "not_started", "sealed"]
    failed = last(campaign, second["run_id"], "admission_failed")
    assert failed["stage"] == "global_budget" and failed["spent"] == {"usd": 0.0, "seconds": 100.0}
    assert "global budget" in run_record(campaign, second["run_id"])["not_started_reason"]
    assert not (campaign / "broker" / second["run_id"]).exists()
    assert result["spent"] == {"usd": 0.0, "seconds": 100.0}


def test_admission_failure_is_not_started_with_zero_resources(base, monkeypatch):
    campaign = build(base)
    run = run_of(campaign, "lf-c", "instructions")
    plant(monkeypatch, (campaign / "coordinator" / "family" / "tasks" / "lf-c" / "oracle.json").read_bytes())
    result = runner.run_campaign(campaign, adapter_factory=never, only=[run["run_id"]])
    rid = run["run_id"]
    assert states(campaign, rid) == ["materialized", "admission_failed", "not_started", "sealed"]
    failed = last(campaign, rid, "admission_failed")
    assert failed["stage"] == "workspace"
    assert {"forbidden_content", "canary"} <= {v["code"] for v in failed["violations"]}
    assert last(campaign, rid, "not_started")["charge"] == ZERO_CHARGE
    record = run_record(campaign, rid)
    runner.validate_run_record(record)
    assert record["status_hint"] == "not_started" and "forbidden_content" in record["not_started_reason"]
    assert record["executor_id"] is None and record["profile_sha256"] is None
    assert record["started_utc"] == record["ended_utc"] == [r for r in journal(campaign, rid)
                                                            if r["state"] == "not_started"][0]["time_utc"]
    assert sealed_names(campaign, rid) == SEALED_ALWAYS
    assert not (campaign / "broker" / rid).exists()           # no kernel work for a refused workspace
    assert runner.evidence_digest(campaign / "runs" / rid) == result["runs"][0]["evidence_sha256"]
    assert result["spent"] == {"usd": 0.0, "seconds": 0.0}


def test_a_reformatted_oracle_copy_is_caught_by_value_canaries(base, monkeypatch):
    campaign = build(base)
    rid = run_of(campaign, "lf-b", "full")["run_id"]
    oracle = canonical.strict_load(campaign / "coordinator" / "family" / "tasks" / "lf-b" / "oracle.json")
    # SYNTHETIC leak: the oracle's numbers only, reformatted (no fixed fragment, no matching hash).
    notes = json.dumps({"numbers": [oracle["current"]["sigma_vis_obs_fb"]]}, indent=4).encode()
    plant(monkeypatch, notes)
    runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    failed = last(campaign, rid, "admission_failed")
    assert failed["stage"] == "workspace" and {v["code"] for v in failed["violations"]} == {"canary"}


def test_the_family_build_canary_alone_fails_admission(base, monkeypatch):
    """Each family build plants a random canary in every oracle record and task definition; the
    coordinator scans subject-visible bytes for it (here a SYNTHETIC note quoting only the canary)."""
    campaign = build(base)
    canary = canonical.strict_load(campaign / "coordinator" / "family" / "index.json")["canary"]
    assert contracts.CANARY.fullmatch(canary)
    for task in ("lf-a", "lf-d"):
        for name in ("oracle.json", "task_definition.json"):
            assert canary.encode() in (campaign / "coordinator" / "family" / "tasks" / task / name).read_bytes()
    rid = run_of(campaign, "lf-a", "baseline")["run_id"]
    plant(monkeypatch, json.dumps({"note": canary}).encode())
    runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    failed = last(campaign, rid, "admission_failed")
    assert failed["stage"] == "workspace" and {v["code"] for v in failed["violations"]} == {"canary"}


def test_host_drift_is_not_started(base):
    class DriftingAdapter(FakeAdapter):
        def run(self, **kwargs):
            raise HostDriftError("SYNTHETIC drift: the pinned binary hash differs")

    campaign = build(base)
    rid = run_of(campaign, "lf-a", "full")["run_id"]
    runner.run_campaign(campaign, only=[rid],
                        adapter_factory=lambda a: DriftingAdapter(a["behavior"], a["launcher"], python=a["python"]))
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "not_started", "sealed"]
    record = run_record(campaign, rid)
    assert record["status_hint"] == "not_started" and "host drift" in record["not_started_reason"]
    assert record["executor_id"] is None and last(campaign, rid, "not_started")["charge"]["seconds"] == 0.0
    names = sealed_names(campaign, rid)
    assert SEALED_ALWAYS | {"broker/custody.jsonl"} <= names and "launch.json" not in names


def test_timeout_is_sealed_and_an_unsandboxed_campaign_is_flagged_everywhere(base):
    """Always one none_test_only launch (even where Seatbelt works): the flag must reach run.json."""
    campaign = build(base, campaign_id="synthetic-runner-unsandboxed", sandbox="none_test_only", seconds_per_run=3)
    rid = run_of(campaign, "lf-a", "baseline")["run_id"]
    plan = {"default": "reference", "by_task_arm": {"lf-a|baseline": "timeout"}}
    runner.run_campaign(campaign, adapter_factory=runner.fake_adapter_factory, behavior_plan=plan, only=[rid])
    record = run_record(campaign, rid)
    assert record["status_hint"] == "timeout" and record["behavior"] == "timeout"
    assert record["validity_flags"] == ["sandbox_none_test_only"] and record["profile_sha256"] is None
    launch = sealed_json(campaign, rid, "launch.json")
    assert launch["timed_out"] is True and launch["killed"] is True and launch["survivors"] == []
    assert launch["exit_code"] != 0 and launch["wall_seconds"] >= 3
    charge = last(campaign, rid, "exited")["charge"]
    assert charge["seconds_basis"] == "measured" and charge["seconds"] >= 3


# ---------------------------------------------------------------- code, separation and accounting guards

def test_code_or_prompt_drift_refuses_to_run(base, monkeypatch):
    campaign = build(base)
    rid = registry(campaign)["runs"][0]["run_id"]
    oracle = canonical.strict_load(campaign / "coordinator" / "family" / "tasks" / "lf-a" / "oracle.json")
    drifts = [
        ("fake_host_version", lambda: "fake_subject-sha256:" + "0" * 64, "fake_subject.py changed"),
        ("harness_manifest", lambda: [{"path": "runner.py", "sha256": "0" * 64}], "harness code changed"),
        ("arm_manifests", lambda python: {}, "treatment code, kernel source or interpreter changed"),
        ("RESOURCE_POLICY", runner.RESOURCE_POLICY + f" ({oracle['current']['obs_limit_events']})",
         "prompt: evaluator material"),
    ]
    for name, value, message in drifts:
        with monkeypatch.context() as patch:
            patch.setattr(runner, name, value)
            with pytest.raises(ContractError, match=re.escape(message)):
                runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    assert not (campaign / "runs" / rid).exists()


def test_charge_counts_unknown_cost_at_the_per_run_cap():
    charge = runner._Campaign.charge
    live = SimpleNamespace(host={"adapter": "claude_cli"}, budget={"usd_per_run": 2.5, "seconds_per_run": 90})
    cap = {"usd": 2.5, "usd_basis": "per_run_cap_unknown"}
    for usd, provenance in ((None, "host_reported"), (-1.0, "host_reported"), (float("nan"), "host_reported"),
                            (float("inf"), "host_reported"), (True, "host_reported"), (0.0, "none_synthetic"),
                            (0.4, "none_synthetic")):
        result = charge(live, usd, provenance, 12.5)
        assert {k: result[k] for k in cap} == cap, (usd, provenance)
    assert charge(live, 0.75, "host_reported", None) == {"usd": 0.75, "usd_basis": "reported", "seconds": 90.0,
                                                         "seconds_basis": "per_run_cap_unknown"}
    fake = SimpleNamespace(host={"adapter": "fake"}, budget=live.budget)
    assert charge(fake, None, "none_synthetic", 1.0) == {"usd": 0.0, "usd_basis": "none_synthetic", "seconds": 1.0,
                                                          "seconds_basis": "measured"}


# ---------------------------------------------------------------- build

def test_build_binds_checkout_environment_and_family(base):
    campaign = build(base)
    manifest, spec = canonical.strict_load(campaign / "campaign.json"), registry(campaign)["spec"]
    assert campaign == base / "store" / "synthetic" / "synthetic-runner-test"
    assert campaign_manifest.verify(campaign) == {"ok": True, "errors": []}
    assert spec["experiment_id"] == manifest["campaign_id"]
    assert spec["protocol_sha256"] == canonical.sha256_file(REPO / "docs/development/evaluation-study/slice-design.md")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert spec["code_commit"] == manifest["source"]["git_commit"] == head.strip()
    environment = canonical.strict_load(campaign / "coordinator" / "environment.json")
    assert spec["environment_sha256"] == manifest["host"]["environment_manifest_sha256"] \
        == canonical.digest(environment)
    assert environment["pyhf_version"] and environment["subject_interpreter"]["executable"] == PYTHON
    harness = {e["path"]: e["sha256"] for e in environment["harness_code"]}
    for name in ("runner.py", "cli.py", "isolation.py", "adapters/fake.py", "experiment.py"):
        assert harness[name] == canonical.sha256_file(REPO / "benchmarks" / "governance" / name)
    assert environment["materialized_client_sha256"] == canonical.sha256_bytes(runner.materialized_client(PYTHON))
    assert [t["id"] for t in spec["tasks"]] == ["lf-a", "lf-b", "lf-c", "lf-d"]
    assert [t["fidelity_tolerance"] for t in spec["tasks"]] == [0.005, 0.005, 0.005, None]
    assert spec["model"].startswith("synthetic") and spec["runtime"].startswith("synthetic fake ")
    assert manifest["host"]["sandbox"] == SANDBOX and manifest["authorization"]["kind"] == "synthetic_engineering"
    assert treatment.treatment_diff(manifest["arms"])["ok"] is True
    assert len(registry(campaign)["runs"]) == 16 and manifest["budget"]["global_seconds_cap"] == 16 * 600
    secret = campaign / "coordinator" / "campaign_secret"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o400
    assert sorted(p.name for p in (base / "store" / "synthetic").iterdir()) == ["synthetic-runner-test"]
    other = build(base, campaign_id="synthetic-runner-test-unsandboxed", sandbox="none_test_only")
    assert canonical.strict_load(other / "campaign.json")["host"]["sandbox"] == "none_test_only"


@pytest.mark.parametrize("case", ["repository", "instructions_ancestor", "arm_word", "store"])
def test_build_refuses_unsafe_subject_roots(base, case):
    if case == "repository":
        subjects = REPO / "local-subjects"
    elif case == "instructions_ancestor":
        (base / "marked").mkdir()
        (base / "marked" / "AGENTS.md").write_text("synthetic instructions\n")
        subjects = base / "marked" / "subjects"
    elif case == "arm_word":
        subjects = base / "full" / "subjects"
    else:
        subjects = base / "store" / "subjects"
    with pytest.raises(ContractError, match="subjects_root"):
        runner.build_synthetic_campaign(base / "store", campaign_id="synthetic-refused", created_utc=CREATED,
                                        seeds=[11], schedule_seed=7, subjects_root=subjects, sandbox=SANDBOX)
    assert not (base / "store" / "synthetic" / "synthetic-refused").exists()
    assert not subjects.exists()


def test_a_failed_build_leaves_nothing_and_the_id_stays_usable(base, monkeypatch):
    def refuse(self):
        raise ContractError("SYNTHETIC late build failure")

    with monkeypatch.context() as patch:
        patch.setattr(runner._Campaign, "_check_separation", refuse)
        with pytest.raises(ContractError, match="SYNTHETIC late build failure"):
            build(base)
    assert list((base / "store" / "synthetic").iterdir()) == []
    assert campaign_manifest.verify(build(base))["ok"] is True
    with pytest.raises(ContractError, match="refusing to overwrite"):
        build(base)


@pytest.mark.parametrize("sandbox", ["seatbelt", "none_test_only"])
def test_build_refuses_a_subject_interpreter_the_profile_cannot_grant(base, sandbox):
    """The launch policy inputs are validated at build time in every sandbox mode, before anything is
    built: an interpreter prefix inside a forbidden root fails the build, not every launch."""
    with pytest.raises(ContractError, match="launch profile: sandbox root .* overlaps forbidden root"):
        runner.build_synthetic_campaign(base / "store", campaign_id="synthetic-refused", created_utc=CREATED,
                                        seeds=[11], schedule_seed=7, subjects_root=base / "subjects",
                                        sandbox=sandbox, extra_forbidden_roots=[PREFIX])
    assert not (base / "store").exists() and not (base / "subjects").exists()   # failed fast: nothing written
    with pytest.raises(ContractError, match="launch profile: sandbox root"):
        runner.launch_policy(workspace=base / "subjects" / runner.PLACEHOLDER_HANDLE, subject_prefix=PREFIX,
                             forbidden=[PREFIX], port=1)


def test_the_packet_is_forbidden_where_the_checkout_places_it(base, monkeypatch):
    """The research packet's location derives from the checkout (research-planning/<packet> beside it and
    in the lab root), never from a host-specific absolute path, so a checkout anywhere forbids its own lab's
    packet. RAVEL_EVAL_PACKET_DIR, read from the coordinator's environment, adds a location and never
    replaces one; a relative value fails closed instead of being ignored."""
    monkeypatch.delenv(runner.PACKET_ENV, raising=False)
    assert runner.PACKET_DIR == str(REPO.parent / "research-planning" / runner.PACKET_NAME)
    lab = runner.lab_root()
    default = runner.forbidden_roots(base / "store")
    for packet in (runner.PACKET_DIR, os.path.join(lab, "research-planning", runner.PACKET_NAME)):
        assert os.path.realpath(packet) in default
    assert {lab, os.path.realpath(REPO), os.path.realpath(base / "store")} <= set(default)
    elsewhere = base / "packet-elsewhere"
    monkeypatch.setenv(runner.PACKET_ENV, str(elsewhere))
    widened = runner.forbidden_roots(base / "store")
    assert set(widened) == set(default) | {os.path.realpath(elsewhere)}
    with pytest.raises(ContractError, match="overlaps forbidden root"):
        runner.check_subjects_root(elsewhere / "subjects", widened)
    runner.check_subjects_root(base / "subjects", widened)       # a neutral root elsewhere stays allowed
    monkeypatch.setenv(runner.PACKET_ENV, "relative/packet")
    with pytest.raises(ContractError, match=runner.PACKET_ENV):
        runner.forbidden_roots(base / "store")


def test_behavior_plan_is_validated_and_fake_only(base):
    campaign = build(base)
    for plan in ({"default": "reference"}, {"default": "nonsense", "by_task_arm": {}},
                 {"default": "reference", "by_task_arm": {"lf-z|full": "reference"}},
                 {"default": "reference", "by_task_arm": {"lf-a|full": "nonsense"}}):
        with pytest.raises(ContractError, match="behavior_plan"):
            runner.run_campaign(campaign, adapter_factory=never, behavior_plan=plan, only=[])


def test_a_second_coordinator_or_another_checkout_is_refused(base):
    campaign = build(base)
    rid = registry(campaign)["runs"][0]["run_id"]
    holder = os.open(campaign / "coordinator" / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ContractError, match="another coordinator"):
            runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    finally:
        os.close(holder)
    assert not (campaign / "runs" / rid).exists()
    config = campaign / "coordinator" / "config.json"
    record = canonical.strict_load(config)
    config.chmod(0o644)
    config.write_text(json.dumps({**record, "checkout": "/nonexistent/other-checkout"}))
    with pytest.raises(ContractError, match="frozen in /nonexistent/other-checkout"):
        runner.run_campaign(campaign, adapter_factory=never, only=[rid])


# ---------------------------------------------------------------- outcomes, report and CLI

def stub_report(campaign, run_id, *, status="not_started", evidence=None, scorer=STUB_SCORER):
    """A SYNTHETIC stub judge report (test fixture standing in for audit.py; judges nothing)."""
    manifest = canonical.strict_load(campaign / "campaign.json")
    task = next(r["task_id"] for r in registry(campaign)["runs"] if r["run_id"] == run_id)
    oracle = next(t["oracle_sha256"] for t in registry(campaign)["spec"]["tasks"] if t["id"] == task)
    started = status != "not_started"
    row = {"run_id": run_id, "status": status, "unsupported_claim": None, "refusal_valid": None,
           "fidelity_error": None, "cost_usd": 0.0 if started else 0, "wall_seconds": None if started else 0,
           "interventions": 0, "executor_id": "synthetic-fake:reference" if started else None, "scorer_id": None,
           "evidence_sha256": evidence, "notes": "SYNTHETIC stub judge report (test fixture); nothing adjudicated"}
    return {"schema_version": 1, "run_id": run_id, "campaign_id": manifest["campaign_id"],
            "campaign_kind": "synthetic", "adapter": "fake", "synthetic": True, "evidence_sha256": evidence,
            "oracle_sha256": oracle, "scorer_id": scorer, "review_state": "mechanical_only", "status": status,
            "claim_findings": [], "gate_events": [],
            "quantities": {**{n: 0 for n in contracts.QUANTITY_COUNTS}, **{n: False for n in contracts.QUANTITY_FLAGS}},
            "deliverable": {"complete": status == "completed", "missing": [], "title_current": None},
            "refusal": {"present": False, "valid": None, "reason_matched": None}, "fidelity_error": None,
            "unresolved_items": [], "v1_outcome": row, "notes": "SYNTHETIC stub judge report (test fixture)"}


def write_report(campaign, report):
    path = campaign / "runs" / report["run_id"] / "judge_report.json"
    if path.exists():
        path.chmod(0o644)
    path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")


def honest_stub(campaign, run_id, **kwargs):
    """The stub a judge would have to write: not_started for never-launched runs, crash with the seal digest
    for every launched one."""
    if run_record(campaign, run_id)["status_hint"] == "not_started":
        return stub_report(campaign, run_id, **kwargs)
    return stub_report(campaign, run_id, status="crash", evidence=runner.evidence_digest(campaign / "runs" / run_id),
                       **kwargs)


def test_outcomes_bind_every_row_to_its_seal_and_to_the_scorer(lost):
    campaign, runs = lost.campaign, registry(lost.campaign)["runs"]
    stubs = {r["run_id"]: honest_stub(campaign, r["run_id"]) for r in runs}
    for rid, report in list(stubs.items())[:-1]:
        write_report(campaign, report)
    with pytest.raises(ContractError, match=runs[-1]["run_id"]):
        runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER])
    write_report(campaign, stubs[runs[-1]["run_id"]])
    error_rid = lost.picks["launch_error"]
    digest = runner.evidence_digest(campaign / "runs" / error_rid)
    bad = [(stub_report(campaign, error_rid, status="completed", evidence=digest), "not crash"),
           (stub_report(campaign, error_rid, status="crash", evidence="0" * 64), "differs from the seal"),
           (stub_report(campaign, lost.picks["env_refused"], status="crash", evidence="0" * 64), "never launched"),
           (stub_report(campaign, lost.picks["seal_crash"]), "judged not_started")]
    for report, message in bad:
        write_report(campaign, report)
        with pytest.raises(ContractError, match=message):
            runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER])
        write_report(campaign, stubs[report["run_id"]])
    assert not (campaign / "outcomes.json").exists()
    with pytest.raises(ContractError, match="audit.py missing" if runner.audit_module() is None else "written by"):
        runner.write_outcomes(campaign)                     # default: only audit.py's scorer counts
    with pytest.raises(ContractError, match="written by"):
        runner.write_outcomes(campaign, scorer_ids=["another-scorer"])
    with pytest.raises(ContractError, match="synthetic campaigns only"):
        runner.scorer_ids_for({"kind": "empirical"}, [STUB_SCORER])
    with runner.campaign_lock(campaign):
        with pytest.raises(ContractError, match="another coordinator"):
            runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER])
    outcomes = canonical.strict_load(runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER]))
    assert [row["run_id"] for row in outcomes["outcomes"]] == [r["run_id"] for r in runs]
    rows = {row["run_id"]: row for row in outcomes["outcomes"]}
    assert rows[error_rid]["status"] == "crash" and rows[error_rid]["evidence_sha256"] == digest
    paths = runner.report(campaign, n_bootstrap=50, scorer_ids=[STUB_SCORER])
    summary, result = canonical.strict_load(paths["summary"]), canonical.strict_load(paths["analysis"])
    counts = Counter()
    for arm in summary["arms"].values():
        counts.update(arm["status_counts"])
    assert (counts["crash"], counts["not_started"]) == (4, 12)
    assert result["synthetic"] is True and paths["synthetic"] is True
    assert result["inputs"]["task_entries"] == canonical.strict_load(campaign / "campaign.json")["tasks"]
    edited = {**outcomes, "outcomes": outcomes["outcomes"][::-1]}
    (campaign / "outcomes.json").write_text(json.dumps(edited, indent=2) + "\n")
    with pytest.raises(ContractError, match="differs from the judge reports"):
        runner.report(campaign, n_bootstrap=50, scorer_ids=[STUB_SCORER])


def test_lost_launches_are_judged_crash_by_the_evaluator(lost):
    """Cross-package: runner-sealed lost launches and launch errors through audit.build_report."""
    audit = pytest.importorskip("governance.audit", reason="audit.py (WP08) is not integrated in this checkout")
    campaign = lost.campaign
    for name in ("adapter_error", "interrupted", "launch_error"):
        rid = lost.picks[name]
        report = audit.build_report(campaign, rid)
        assert report["status"] == "crash" and report["v1_outcome"]["status"] == "crash", name
        assert report["evidence_sha256"] == runner.evidence_digest(campaign / "runs" / rid)
    for name in ("seal_crash", "env_refused", "broker_failed"):
        assert audit.build_report(campaign, lost.picks[name])["status"] != "crash", name


def tamper(campaign, run_id, name, data):
    """SYNTHETIC post-seal tamper (red-team RT-01): rewrite one sealed file and then, consistently,
    evidence_manifest.json, so the tree and its manifest agree again; returns the new digest."""
    rdir = campaign / "runs" / run_id
    path = rdir / "sealed" / name
    for directory in (rdir / "sealed", path.parent):
        directory.chmod(0o755)
    path.chmod(0o644)
    path.write_bytes(data)
    manifest = rdir / "evidence_manifest.json"
    manifest.chmod(0o644)
    manifest.write_bytes(runner._pretty(canonical.tree_manifest(rdir / "sealed")))
    return runner.evidence_digest(rdir)


def test_a_post_seal_tamper_with_a_rewritten_manifest_is_never_laundered(base, monkeypatch):
    """RT-01: every run's recomputed evidence digest must equal the one its coordinator journaled when it
    sealed the run. A consistent tree+manifest rewrite (judged afresh) is refused by write_outcomes and by
    the resume/skip path as a coordinator-integrity incident naming every run and the remedy."""
    campaign = build(base, seconds_per_run=100)
    runs = [r["run_id"] for r in registry(campaign)["runs"]]
    lost_rid, quiet_rid, other_rid = runs[0], runs[1], runs[2]
    for rid in (lost_rid, other_rid):                                      # two lost launches (no process)
        simulate_launched(campaign, rid, base / "subjects" / opaque_of(campaign, rid), called=True)
    with monkeypatch.context() as patch:   # every other assignment: not_started at workspace admission
        plant(patch, (campaign / "coordinator" / "family" / "index.json").read_bytes())
        runner.run_campaign(campaign, adapter_factory=never)
    for rid in runs:
        write_report(campaign, honest_stub(campaign, rid))
    before = runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER]).read_bytes()
    journaled = last(campaign, lost_rid, "sealed")["evidence_sha256"]
    assert runner.sealed_evidence(campaign / "runs" / lost_rid) == journaled
    # A delivered-looking number appears in the lost launch's final text after sealing; its judge report
    # is rewritten to the new digest (as a re-audit of the tampered tree would), and a not_started run's
    # reason is edited: each tree agrees with its rewritten manifest, not with its journaled seal.
    forged = tamper(campaign, lost_rid, "final_text.txt", b"SYNTHETIC: sigma_vis < 0.123 fb\n")
    assert forged != journaled and runner.evidence_digest(campaign / "runs" / lost_rid) == forged
    write_report(campaign, stub_report(campaign, lost_rid, status="crash", evidence=forged))
    quiet = {**run_record(campaign, quiet_rid), "not_started_reason": "SYNTHETIC edited reason"}
    tamper(campaign, quiet_rid, "run.json", runner._pretty(quiet))
    other = runner.evidence_digest(campaign / "runs" / other_rid)          # intact seal, misjudged evidence
    write_report(campaign, stub_report(campaign, other_rid, status="crash", evidence="0" * 64))
    with pytest.raises(ContractError) as refused:
        runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER])
    message = str(refused.value)
    assert message.startswith("refusing to write outcomes: custody incident (human gate) in 3 run(s)")
    for rid in (lost_rid, quiet_rid):
        assert f"{rid}: coordinator integrity: the sealed tree and evidence manifest digest" in message
    assert "journaled when the run was sealed (changed after sealing)" in message
    assert f"{other_rid}: the judged evidence_sha256 {'0' * 64} differs from the sealed evidence {other}" in message
    assert "Remedy: a human compares" in message
    assert (campaign / "outcomes.json").read_bytes() == before              # nothing rewritten
    for rid in (lost_rid, quiet_rid):                                       # the skip path fails closed too
        with pytest.raises(ContractError, match=f"coordinator integrity: run {rid}: .*changed after sealing"):
            runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    assert runner.seal_problem(campaign / "runs" / other_rid) == (other, None)
    assert runner.run_campaign(campaign, adapter_factory=never, only=[other_rid])["runs"][0]["action"] == "skipped"


def test_seals_are_reconciled_before_any_sealed_record_is_trusted_and_again_by_report(base, monkeypatch):
    """RT-01 follow-up: write_outcomes reconciles every seal before it reads a sealed run.json, so a post-seal
    edit that breaks run.json is the custody incident naming every affected run and the remedy, never a field
    error about the first; report() reconciles the seals again, so a tree changed after outcomes were written
    never reaches summary.json or analysis.json."""
    campaign = build(base, seconds_per_run=100)
    runs = [r["run_id"] for r in registry(campaign)["runs"]]
    lost_rid, quiet_rid = runs[0], runs[1]
    simulate_launched(campaign, lost_rid, base / "subjects" / opaque_of(campaign, lost_rid), called=True)   # no process
    with monkeypatch.context() as patch:   # every other assignment: not_started at workspace admission
        plant(patch, (campaign / "coordinator" / "family" / "index.json").read_bytes())
        runner.run_campaign(campaign, adapter_factory=never)
    for rid in runs:
        write_report(campaign, honest_stub(campaign, rid))
    runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER])
    paths = runner.report(campaign, n_bootstrap=50, scorer_ids=[STUB_SCORER])
    written = {name: Path(path).read_bytes() for name, path in paths.items() if name != "synthetic"}
    # SYNTHETIC post-seal tampers, each with a consistently rewritten manifest: a not_started run.json that
    # no longer validates, and a lost launch's final text.
    tamper(campaign, quiet_rid, "run.json", runner._pretty({**run_record(campaign, quiet_rid), "SYNTHETIC": 1}))
    tamper(campaign, lost_rid, "final_text.txt", b"SYNTHETIC: sigma_vis < 0.123 fb\n")
    for action, call in (("report", lambda: runner.report(campaign, n_bootstrap=50, scorer_ids=[STUB_SCORER])),
                         ("write outcomes", lambda: runner.write_outcomes(campaign, scorer_ids=[STUB_SCORER]))):
        with pytest.raises(ContractError) as refused:
            call()
        message = str(refused.value)
        assert message.startswith(f"refusing to {action}: custody incident (human gate) in 2 run(s)"), message
        for rid in (lost_rid, quiet_rid):
            assert f"{rid}: coordinator integrity: the sealed tree and evidence manifest digest" in message
        assert "Remedy: a human compares" in message
    assert {name: Path(paths[name]).read_bytes() for name in written} == written   # nothing rewritten


def cli_run(*args):
    done = subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=REPO, capture_output=True, text=True,
                          timeout=600, check=False)
    return done.returncode, json.loads(done.stdout)


def test_cli_builds_verifies_and_fails_closed(base):
    code, built = cli_run("build-synthetic", "--store", base / "store", "--campaign-id", "synthetic-cli-test",
                          "--created-utc", CREATED, "--seed", 11, "--schedule-seed", 3, "--subjects-root",
                          base / "subjects", "--sandbox", SANDBOX, "--seconds-per-run", 60)
    assert code == 0 and built["ok"] and built["runs"] == 16 and built["synthetic"] is True
    campaign = built["campaign_dir"]
    assert cli_run("verify", "--campaign", campaign) == (0, {"ok": True, "campaign": {"ok": True, "errors": []},
                                                             "provenance": {"ok": True, "errors": []},
                                                             "judge_reports": 0})
    code, diff = cli_run("treatment-diff", "--campaign", campaign)
    assert code == 0 and diff["ok"] and diff["violations"] == []
    plan = base / "plan.json"
    plan.write_text(json.dumps({"default": "over_refuse", "by_task_arm": {}}))   # SYNTHETIC behavior plan
    rid = run_of(Path(campaign), "lf-a", "baseline")["run_id"]
    code, ran = cli_run("run", "--campaign", campaign, "--behavior-plan", plan, "--only", rid)
    assert code == 0 and ran["ok"] and [r["action"] for r in ran["runs"]] == ["sealed"]
    assert run_record(Path(campaign), rid)["behavior"] == "over_refuse"
    assert ran["behavior_plan_sha256"] == canonical.digest(json.loads(plan.read_text()))
    code, refused = cli_run("report", "--campaign", campaign)
    assert code == 2 and refused["ok"] is False and "no judge report" in refused["error"]
    code, audited = cli_run("audit", "--campaign", campaign)       # 15 assignments are not sealed yet
    assert code == 2 and audited["ok"] is False and "not sealed yet" in audited["error"]
    assert not list(Path(campaign).glob("runs/*/judge_report.json"))
    code, usage = cli_run("run")
    assert code == 2 and usage["ok"] is False and usage["error"].startswith("ContractError: usage:")
    code, rebuilt = cli_run("build-synthetic", "--store", base / "store", "--campaign-id", "synthetic-cli-test",
                            "--created-utc", CREATED, "--seed", 11, "--schedule-seed", 3, "--subjects-root",
                            base / "subjects", "--sandbox", SANDBOX)
    assert code == 2 and "refusing to overwrite" in rebuilt["error"]


def test_cli_audit_reports_a_missing_evaluator_and_calls_a_present_one(lost, monkeypatch, capsys):
    campaign = str(lost.campaign)
    monkeypatch.setattr(runner, "audit_module", lambda: None)
    assert cli.main(["audit", "--campaign", campaign]) == 1
    missing = json.loads(capsys.readouterr().out)
    assert missing["ok"] is False and "audit.py missing" in missing["error"]
    seen = []
    stub = SimpleNamespace(SCORER_ID=STUB_SCORER, audit_campaign=lambda d: seen.append(d) or [   # SYNTHETIC stub
        {"status": "not_started", "synthetic": True}] * 16)
    monkeypatch.setattr(runner, "audit_module", lambda: stub)
    assert cli.main(["audit", "--campaign", campaign]) == 0
    done = json.loads(capsys.readouterr().out)
    assert done == {"ok": True, "scorer_id": STUB_SCORER, "judge_reports": 16, "status_counts": {"not_started": 16},
                    "synthetic": True}
    assert seen == [Path(campaign).resolve()]

    def boom(*args, **kwargs):
        raise RuntimeError("SYNTHETIC unexpected failure")

    monkeypatch.setattr(runner, "write_outcomes", boom)
    assert cli.main(["report", "--campaign", campaign]) == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "RuntimeError: SYNTHETIC unexpected failure"}



# ---------------------------------------------------------------- holistic-review fixes (R0.x, R1.x, R4.5)

def writable(path):
    path = Path(path)
    for item in (path, *path.parents):
        if item.name in ("sealed", "runs") or item == path:
            try:
                item.chmod(item.stat().st_mode | stat.S_IWUSR)
            except OSError:
                pass


def copy_campaign(source, tmp_path):
    """A copy of a finished SYNTHETIC campaign in another store (mutation tests never touch the fixture)."""
    target = tmp_path / "store" / "synthetic" / source.name
    shutil.copytree(source, target, symlinks=True)
    return target


def tampered_treatments(root):
    """A SYNTHETIC copy of the frozen treatment texts whose instruction text differs by one word."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name in treatment.FROZEN_FILES.values():
        shutil.copy(treatment.TREATMENTS_DIR / name, root / name)
    text = (root / treatment.FROZEN_FILES["instructions"]).read_text()
    (root / treatment.FROZEN_FILES["instructions"]).write_text(text.replace("the", "a", 1))
    return root


class PreLaunchFailure(FakeAdapter):
    """SYNTHETIC adapter bug before the launcher is called (a claude_cli fresh_dir or merge_env failure)."""

    def run(self, **kwargs):
        raise RuntimeError("SYNTHETIC adapter failure before the launch")


class LateDrift(FakeAdapter):
    """SYNTHETIC: the fake subject really ran, then the adapter raises HostDriftError."""

    def run(self, **kwargs):
        super().run(**kwargs)
        raise HostDriftError("SYNTHETIC drift noticed after the launch")


class ExtraEnv(FakeAdapter):
    """SYNTHETIC adapter that adds (or overrides) launch environment values."""

    def __init__(self, extra, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra = extra

    def run(self, **kwargs):
        return super().run(**{**kwargs, "env": {**kwargs["env"], **self.extra}})


class AfterRun(FakeAdapter):
    """SYNTHETIC: calls ``hook`` after the fake subject ran (a code edit during the run)."""

    def __init__(self, hook, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hook = hook

    def run(self, **kwargs):
        result = super().run(**kwargs)
        self.hook()
        return result


@pytest.fixture(scope="module")
def guarded(tmp_path_factory):
    """SYNTHETIC launch-boundary scenarios on one campaign (only ``late_drift`` and ``code_drift`` start a
    subject process, the fake subject, exactly as the other launched tests do)."""
    base = Path(os.path.realpath(tmp_path_factory.mktemp("lab")))
    campaign = build(base, campaign_id="synthetic-runner-guarded", seconds_per_run=120)
    tampered = tampered_treatments(base / "tampered-treatments")
    names = {"pre_launch": ("lf-a", "baseline"), "late_drift": ("lf-a", "instructions"),
             "leaky_env": ("lf-a", "enforcement"), "changed_env": ("lf-a", "full"), "foreign": ("lf-b", "baseline"),
             "drift_before": ("lf-b", "instructions"), "code_drift": ("lf-b", "enforcement"),
             "resume_uncalled": ("lf-b", "full")}
    picks = {name: run_of(campaign, *key)["run_id"] for name, key in names.items()}
    calls = Counter()

    def go(name, factory, **kwargs):
        def counted(a):
            calls[name] += 1
            return factory(a)
        return runner.run_campaign(campaign, adapter_factory=counted, only=[picks[name]], **kwargs)

    go("pre_launch", lambda a: PreLaunchFailure(a["behavior"], a["launcher"], python=a["python"]))
    go("late_drift", lambda a: LateDrift(a["behavior"], a["launcher"], python=a["python"]))
    canary = (campaign / "coordinator" / "canary.txt").read_text().strip()
    go("leaky_env", lambda a: ExtraEnv({"HOST_NOTE": canary}, a["behavior"], a["launcher"], python=a["python"]))
    go("changed_env", lambda a: ExtraEnv({"HOME": "/nonexistent/elsewhere"}, a["behavior"], a["launcher"],
                                         python=a["python"]))
    go("foreign", lambda a: FakeAdapter(a["behavior"], None, python=a["python"]))   # would bypass the recorder
    original = runner._Campaign._broker
    with pytest.MonkeyPatch.context() as patch:
        def drifting_broker(self, run):   # the instruction file changes after the load, before the launch
            prepared = original(self, run)
            patch.setattr(treatment, "TREATMENTS_DIR", tampered)
            return prepared
        patch.setattr(runner._Campaign, "_broker", drifting_broker)
        go("drift_before", never)
    with pytest.MonkeyPatch.context() as patch:
        go("code_drift", lambda a: AfterRun(lambda: patch.setattr(treatment, "TREATMENTS_DIR", tampered),
                                            a["behavior"], a["launcher"], python=a["python"]))
    simulate_launched(campaign, picks["resume_uncalled"], base / "subjects" / opaque_of(campaign, picks["resume_uncalled"]))
    go("resume_uncalled", never)
    return SimpleNamespace(base=base, campaign=campaign, picks=picks, calls=calls)


@pytest.mark.parametrize("name, text", [
    ("pre_launch", "the adapter failed before calling the launcher; no process was started: RuntimeError"),
    ("leaky_env", "the launch call was refused before anything started: LaunchRefused: the coordinator refused "
                  "the launch call: environment variable HOST_NOTE carries evaluator material"),
    ("changed_env", "the adapter changed or dropped coordinator environment variables ['HOME']")])
def test_a_failure_before_the_launcher_ran_is_not_started_with_no_charge(guarded, name, text):
    """R1.4: no launch call and no process start on record prove that nothing started: not_started, zero
    charge, never a lost-launch crash charged at the cap. (Before the fix _serve's except turned any
    non-HostDriftError adapter exception into _crash('adapter_error'): status interrupted, v1 crash, the
    per-run cap charged, although no launch call was ever written.)"""
    campaign, rid = guarded.campaign, guarded.picks[name]
    assert guarded.calls[name] == 1
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "not_started", "sealed"]
    assert last(campaign, rid, "not_started")["charge"] == ZERO_CHARGE
    assert text in last(campaign, rid, "not_started")["reason"]
    assert not (campaign / "runs" / rid / "host" / "launch_call.json").exists()
    record = run_record(campaign, rid)
    assert record["status_hint"] == "not_started" and record["executor_id"] is None
    assert "launch.json" not in sealed_names(campaign, rid)


def test_host_drift_after_the_launcher_ran_is_a_lost_launch(guarded):
    """R1.4 converse: a HostDriftError once the launcher was called (a launch call and a process start on
    record) is never not_started; it is the adapter_error lost launch, charged at the cap."""
    campaign, rid = guarded.campaign, guarded.picks["late_drift"]
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "process_started", "interrupted_crash",
                                     "sealed"]
    crash = last(campaign, rid, "interrupted_crash")
    assert crash["cause"] == "adapter_error" and "HostDriftError" in crash["error"]
    assert crash["charge"]["seconds"] == 120.0 and crash["charge"]["seconds_basis"] == "per_run_cap_unknown"
    assert run_record(campaign, rid)["status_hint"] == "interrupted"


def test_a_resumed_launch_record_without_a_launch_call_is_not_started(guarded):
    """R1.4 on resume: journaled launched, never called (no launch call, no process start): not_started,
    no charge, no census; with a launch call it stays a lost launch (test_global_budget_...)."""
    campaign, rid = guarded.campaign, guarded.picks["resume_uncalled"]
    assert guarded.calls["resume_uncalled"] == 0
    assert states(campaign, rid) == ["materialized", "launched", "not_started", "sealed"]
    assert last(campaign, rid, "not_started")["charge"] == ZERO_CHARGE
    assert "before the launcher was called" in run_record(campaign, rid)["not_started_reason"]


def test_an_adapter_that_bypasses_the_recording_launcher_is_not_started(guarded):
    campaign, rid = guarded.campaign, guarded.picks["foreign"]
    assert guarded.calls["foreign"] == 1
    assert states(campaign, rid) == ["materialized", "admitted", "admission_failed", "not_started", "sealed"]
    failed = last(campaign, rid, "admission_failed")
    assert failed["stage"] == "host" and "recording launcher" in failed["reason"]


def test_a_treatment_edit_after_the_load_refuses_the_launch(guarded):
    """R0.0: the instruction text changed between the campaign load and this launch. Before the fix the
    prompt was re-read from disk at launch, so the edited text was delivered and sealed with no flag."""
    campaign, rid = guarded.campaign, guarded.picks["drift_before"]
    assert guarded.calls["drift_before"] == 0
    assert states(campaign, rid) == ["materialized", "admission_failed", "not_started", "sealed"]
    failed = last(campaign, rid, "admission_failed")
    assert failed["stage"] == "treatment"
    assert "treatment code, kernel source or interpreter changed since the campaign was frozen" in failed["reason"]
    assert "the frozen instructions text on disk differs from the bytes verified at load" in failed["reason"]
    assert last(campaign, rid, "not_started")["charge"] == ZERO_CHARGE


def test_a_code_edit_during_the_run_is_flagged(guarded):
    """R0.0 after the launch: the code verified before the launch must still be there after it."""
    campaign, rid = guarded.campaign, guarded.picks["code_drift"]
    assert states(campaign, rid) == ["materialized", "admitted", "launched", "process_started", "exited", "sealed"]
    assert any("changed since the campaign was frozen" in d for d in last(campaign, rid, "exited")["code_drift"])
    record = run_record(campaign, rid)
    assert runner.CODE_DRIFT_FLAG in record["validity_flags"] and "stdin_mismatch" not in record["validity_flags"]
    held = (sealed(campaign, rid) / "prompt.txt").read_bytes()         # sealed from the bytes held since load:
    assert canonical.sha256_bytes(held) == last(campaign, rid, "launched")["prompt_sha256"]   # what was delivered


def test_every_launch_journals_what_it_verified(launched):
    """R0.0: admitted.verified binds the run to the frozen campaign; the factory never receives the arm (R0.5)."""
    campaign = launched.campaign
    manifest = canonical.strict_load(campaign / "campaign.json")
    digest = canonical.sha256_file(campaign / "campaign.json")
    assert (campaign / "coordinator" / runner.CAMPAIGN_DIGEST).read_text().strip() == digest
    for run in launched.picks.values():
        rid, arm = run["run_id"], manifest["arms"][run["arm"]]
        verified = last(campaign, rid, "admitted")["verified"]
        assert verified["campaign_sha256"] == digest == last(campaign, rid, "launched")["campaign_sha256"] \
            == last(campaign, rid, "materialized")["campaign_sha256"]
        assert verified["prompt_sha256"] == run_record(campaign, rid)["prompt_sha256"]
        assert verified["instructions_sha256"] == arm["instructions"]["text_sha256"]
        assert verified["prompt_template_sha256"] == arm["prompt_template_sha256"]
        assert verified["treatment_manifest_sha256"] == canonical.digest(arm)
        assert verified["common_sha256"] == canonical.digest(arm["common"])
        assert verified["request_sha256"] == next(t["prompt_sha256"] for t in registry(campaign)["spec"]["tasks"]
                                                  if t["id"] == run["task_id"])
        assert last(campaign, rid, "launched")["host_binding_sha256"] is None   # the fake host is not bound
    assert launched.keys and all("arm" not in keys for keys in launched.keys)


def test_global_budget_admits_every_run_the_campaign_was_sized_for(base, monkeypatch):
    """R1.3: 16 runs at 0.1 s each; after 15 are charged the cap, 0.1 s remains and the 16th is admitted.
    Float sums refuse it (1.6 - 15 x 0.1 = 0.0999...87 < 0.1), which is what the old admission did."""
    total = 0.0
    for _ in range(15):                                               # the old spent(): sequential float sums
        total += 0.1
    assert 1.6 - total < 0.1                                          # would refuse the 16th run
    assert runner._budget({"usd_per_run": 0.3}, 3)["global_usd_cap"] == 0.9 != 3 * 0.3
    campaign = build(base, seconds_per_run=0.1)
    runs = [r["run_id"] for r in registry(campaign)["runs"]]
    assert canonical.strict_load(campaign / "campaign.json")["budget"]["global_seconds_cap"] == 1.6
    for rid in runs[:15]:
        simulate_launched(campaign, rid, base / "subjects" / opaque_of(campaign, rid), called=True)

    def stop_after_admission(self, run):
        raise RuntimeError("SYNTHETIC stop after the global budget admission")

    monkeypatch.setattr(runner._Campaign, "_broker", stop_after_admission)
    result = runner.run_campaign(campaign, adapter_factory=never)
    assert [r["status_hint"] for r in result["runs"]] == ["interrupted"] * 15 + ["not_started"]
    assert result["spent"]["seconds"] == 1.5
    failed = last(campaign, runs[15], "admission_failed")
    assert failed["stage"] == "broker" and "SYNTHETIC stop" in failed["reason"]   # past the budget admission


def test_a_backward_clock_step_never_makes_a_run_unsealable(base, monkeypatch):
    """R1.6: the closing record's wall time before the launch record's. The unclamped record fails
    validate_run_record (the old _seal raised on every resume and run_campaign stopped at this run); now
    ended is set to started and the run carries clock_stepped_back."""
    campaign = build(base, seconds_per_run=100)
    rid = registry(campaign)["runs"][0]["run_id"]
    simulate_launched(campaign, rid, base / "subjects" / opaque_of(campaign, rid), called=True)
    monkeypatch.setattr(runner, "utc_now", lambda: "2000-01-01T00:00:00.000000Z")   # SYNTHETIC clock step
    runner.run_campaign(campaign, adapter_factory=never, only=[rid])
    record = run_record(campaign, rid)
    launched_at = last(campaign, rid, "launched")
    times = {r["state"]: r["time_utc"] for r in journal(campaign, rid)}
    assert times["interrupted_crash"] == "2000-01-01T00:00:00.000000Z" < times["launched"]
    assert record["started_utc"] == record["ended_utc"] == times["launched"]
    assert runner.CLOCK_FLAG in record["validity_flags"] and launched_at["executor_id"] == record["executor_id"]
    with pytest.raises(ContractError, match="started_utc after ended_utc"):
        runner.validate_run_record({**record, "ended_utc": times["interrupted_crash"]})


def test_an_incomplete_launch_census_seals_survivors_unknown(tmp_path):
    """R4.5: a launch whose sandbox census became unusable reports survivors [] once the group is empty;
    the sealed launch.json records them as null (unknown), as the lost-launch path does, never []."""
    host, ws = tmp_path / "host", tmp_path / "subject"
    host.mkdir()
    for name in ("stdout.jsonl", "stderr.txt"):
        (host / name).write_bytes(b"")
    result = {"validity": {"invalidating": ["census_incomplete"]}, "final_text": None, "exit_code": -9,
              "wall_seconds": 5.0, "details": {"launch": {"timed_out": True, "killed": True, "survivors": [],
                                                           "census_complete": False}}}   # SYNTHETIC launcher result
    flags = set()
    files = runner._Campaign._host_files(None, host, result, b"SYNTHETIC prompt", ws, {"details": {"timeout_s": 5}},
                                         None, flags)
    launch = json.loads(files["launch.json"])
    assert launch["survivors"] is None and "census_incomplete" in flags
    complete = copy.deepcopy(result)
    complete["details"]["launch"]["census_complete"] = True
    assert json.loads(runner._Campaign._host_files(None, host, complete, b"SYNTHETIC prompt", ws,
                                                   {"details": {"timeout_s": 5}}, None, set())["launch.json"]
                      )["survivors"] == []


def test_a_sandboxed_run_needs_an_empty_ipc_residue_on_record(tmp_path):
    """Hand-off from eval/fix-isolation (R4.2 follow-up): the runner flags ipc_residue (invalidating: the audit's
    unsupported_claim is null, as adapters.base records) for a run whose subject may have run under a profile unless
    the launcher reported an empty System V IPC residue: objects left (even removed) or unknown (a lost launch, whose
    census lists no IPC objects; a launch_error after the process start, or after the launch call when no start was
    journaled and the error is not one isolation.launch raises before any child exists). An unsandboxed launch, and
    a launch refused before its start, are never flagged. SYNTHETIC launcher results; nothing is launched."""
    host, ws = tmp_path / "host", tmp_path / "subject"
    host.mkdir()
    for name in ("stdout.jsonl", "stderr.txt"):
        (host / name).write_bytes(b"")
    sandboxed, unsandboxed = ({"details": {"timeout_s": 5, "profile_sha256": value}} for value in ("a" * 64, None))
    lost_census = {"survivors": [], "killed": [], "found": [], "complete": True}

    def flags_of(residue, launched=sandboxed, started=True, census=None, hint="exited", call=False, error=None):
        launch = {"timed_out": False, "killed": False, "survivors": [], "census_complete": True}
        if residue != "absent":
            launch["ipc_residue"] = residue
        if error is not None:   # launch_host's record of a launcher exception: the error only
            launch = {"error": error}
        result = {"validity": {"invalidating": []}, "final_text": None, "exit_code": 0, "wall_seconds": 1.0,
                  "status_hint": hint, "details": {"launch": {} if census else launch}}
        if call:
            canonical.write_once(host / "launch_call.json", runner._pretty(
                {"argv": ["/usr/bin/true"], "env_names": [], "cwd": str(ws), "timeout_s": 5, "profile_sha256": None}))
        try:
            flags = set()
            runner._Campaign._host_files(None, host, result, b"SYNTHETIC prompt", ws, launched, census, flags,
                                         started=started)
            return "ipc_residue" in flags
        finally:
            (host / "launch_call.json").unlink(missing_ok=True)

    residue = [{"kind": "sem", "id": 65536, "key": "0x0000abcd", "cleared": True, "note": "removed"}]
    assert not flags_of([])
    assert flags_of(residue) and flags_of(None) and flags_of("absent")
    assert flags_of("absent", hint="launch_error")                        # the subject started, then the launch failed
    assert not flags_of("absent", hint="launch_error", started=False)     # refused before its start (no process)
    assert flags_of("absent", census=lost_census)                         # a lost launch: unknown
    assert flags_of("absent", census=lost_census, started=False, call=True)   # a start may not have been journaled
    assert not flags_of("absent", census=lost_census, started=False)      # the launcher was never called
    assert not flags_of(residue, launched=unsandboxed) and not flags_of(None, launched=unsandboxed)
    # integration review: a launch_error after the launch call without a journaled process start. on_start (the
    # process_started journal write) raised after Popen, so isolation killed a subject that ran: residue unknown,
    # unless the error is one isolation.launch raises before any child exists (the listing or the profile refused)
    for error in ("OSError: [Errno 28] No space left on device", "ContractError: journal: unknown state 'x'",
                  "OSError: launch: copying the subject's streams failed: BrokenPipeError()"):
        assert not runner._before_start(error)
        assert flags_of("absent", hint="launch_error", started=False, call=True, error=error)
    assert flags_of("absent", hint="launch_error", started=False, call=True)          # no error on record: unknown
    assert not flags_of("absent", launched=unsandboxed, hint="launch_error", started=False, call=True,
                        error="OSError: [Errno 28] No space left on device")
    with pytest.raises(ContractError) as refused:          # a pure check: nothing is launched
        isolation._check_profile("(allow default)")
    ipc = isolation.IpcUnavailable("System V IPC listing failed: ipcs exited 1")
    for exc in (ipc, refused.value, ContractError("launch: profile rejected by sandbox-exec: syntax error"),
                ContractError("launch: argv[0] must be an absolute path to an executable file")):
        error = f"{type(exc).__name__}: {exc}"             # launch_host's record of a launcher exception
        assert runner._before_start(error)
        assert not flags_of("absent", hint="launch_error", started=False, call=True, error=error)


# -- R0.5 / R1.5: a real host's configuration is bound to the campaign (mocked adapters, never launched)

def claude_host(**overrides):
    host = {"adapter": "claude_cli", "executable": "/opt/synthetic/claude-2.1.233", "executable_sha256": "a" * 64,
            "version": "2.1.233", "model": "synthetic-model", "sandbox": "seatbelt"}
    return {**host, **overrides}


def claude(tmp_path, **overrides):
    args = {"executable": "/opt/synthetic/claude-2.1.233", "expected_version": "2.1.233",
            "expected_sha256": "a" * 64, "model": "synthetic-model", "max_turns": 30, "max_budget_usd": 1.5,
            "permission_mode": "dontAsk", "setting_sources": "project", "disallowed_tools": ["WebSearch", "WebFetch"],
            "config_dir": str(tmp_path / "claude-config"), "synthetic": True}
    return ClaudeCliAdapter(**{**args, **overrides})


def test_host_binding_requires_the_frozen_identity_and_the_per_run_ceiling(tmp_path):
    budget = {"usd_per_run": 1.5}
    binding, problems = runner.host_binding(claude(tmp_path), claude_host(), budget, "synthetic")
    assert problems == []
    assert binding["usd_ceiling"] == 1.5 and runner.PLACEHOLDER_SESSION in binding["argv"]
    assert binding["executor_id"] == "claude_cli/2.1.233/synthetic-model"
    cases = [(claude(tmp_path, max_budget_usd=5.0), claude_host(), "max_budget_usd 5.0 differs from the campaign's "
                                                                     "usd_per_run 1.5"),
             (claude(tmp_path, model="other-model"), claude_host(), "adapter model 'other-model' differs"),
             (claude(tmp_path, expected_version="2.1.281"), claude_host(), "adapter expected_version '2.1.281'"),
             (claude(tmp_path), claude_host(model=None), "host.model is unknown in the campaign"),
             (claude(tmp_path, resume_session_id="00000000-0000-4000-8000-000000000001"), claude_host(),
              "resumes a host session"),
             (claude(tmp_path, synthetic=False), claude_host(), "synthetic label False differs from the synthetic")]
    for adapter, host, message in cases:
        assert any(message in p for p in runner.host_binding(adapter, host, budget, "synthetic")[1]), message
    codex = CodexCliAdapter("/opt/synthetic/codex", "0.155.0", "b" * 64, "synthetic-model", tmp_path / "codex-home",
                            synthetic=True)
    host = {**claude_host(adapter="codex_cli", executable="/opt/synthetic/codex", executable_sha256="b" * 64,
                          version="0.155.0")}
    binding, problems = runner.host_binding(codex, host, budget, "synthetic")
    assert problems == [] and binding["usd_ceiling"] is None and runner.SUBJECT_ROOT in binding["argv"]


def test_a_real_hosts_added_environment_may_not_name_an_arm():
    """R0.5: the recording launcher scans a real host's added environment values (its per-run directories)
    for arm terms; the coordinator's own variables must pass unchanged."""
    def problems(adapter, env):
        campaign = SimpleNamespace(host={"adapter": adapter}, leaks=lambda data: [])
        return runner._Campaign._launch_call_problems(campaign, ["/opt/synthetic/host"], env, {"HOME": "/h"})
    arm_named = {"HOME": "/h", "CLAUDE_CONFIG_DIR": "/runs/full-arm/claude-config"}
    assert problems("claude_cli", arm_named) == ["environment variable CLAUDE_CONFIG_DIR names ['arm', 'full']"]
    assert problems("fake", arm_named) == []
    assert problems("claude_cli", {"HOME": "/elsewhere"}) == [
        "the adapter changed or dropped coordinator environment variables ['HOME']"]


def test_every_run_launches_a_real_host_identically(tmp_path):
    """R0.5: the first launch's binding is written once; a later run whose argv differs (per-arm max turns,
    here) is refused."""
    (tmp_path / "coordinator").mkdir()
    campaign = SimpleNamespace(host=claude_host(), budget={"usd_per_run": 1.5}, manifest={"kind": "synthetic"},
                               dir=tmp_path)
    first, problems = runner._Campaign._bind_host(campaign, claude(tmp_path))
    assert problems == [] and canonical.strict_load(tmp_path / "coordinator" / runner.HOST_BINDING) == first
    assert runner._Campaign._bind_host(campaign, claude(tmp_path))[1] == []
    assert runner._Campaign._bind_host(campaign, claude(tmp_path, max_turns=60))[1] == [
        "the host launch differs from the campaign's first launch (coordinator/host_binding.json)"]


# -- R1.0, R1.2, R1.6: outcomes bound to the frozen campaign, the evaluator and recorded human decisions

@pytest.fixture(scope="module")
def judged(tmp_path_factory):
    """A SYNTHETIC campaign judged by audit.py: lf-a/baseline really run (reference), lf-a/instructions a lost
    launch (launch call recorded, no process), every other assignment refused at workspace admission."""
    audit = pytest.importorskip("governance.audit", reason="audit.py (WP08) is not integrated in this checkout")
    base = Path(os.path.realpath(tmp_path_factory.mktemp("lab")))
    campaign = build(base, campaign_id="synthetic-runner-judged", seconds_per_run=120)
    real, lost = run_of(campaign, "lf-a", "baseline")["run_id"], run_of(campaign, "lf-a", "instructions")["run_id"]
    runner.run_campaign(campaign, adapter_factory=runner.fake_adapter_factory, only=[real])
    simulate_launched(campaign, lost, base / "subjects" / opaque_of(campaign, lost), called=True)
    with pytest.MonkeyPatch.context() as patch:
        plant(patch, (campaign / "coordinator" / "family" / "index.json").read_bytes(), skip={real, lost})
        runner.run_campaign(campaign, adapter_factory=never)
    audit.audit_campaign(campaign)
    outcomes = canonical.strict_load(runner.write_outcomes(campaign))
    quiet = next(r["run_id"] for r in registry(campaign)["runs"] if r["run_id"] not in (real, lost))
    return SimpleNamespace(campaign=campaign, real=real, lost=lost, quiet=quiet, outcomes=outcomes, audit=audit)


def rewrite(path, data):
    path = Path(path)
    for item in (path.parent, path):
        item.chmod(item.stat().st_mode | stat.S_IWUSR)
    path.write_bytes(data)


def test_a_judge_report_edited_after_the_audit_is_a_custody_incident(judged, tmp_path):
    """R1.0: one judge_report.json edited (the sealed tree, its manifest and the journal untouched) used to
    enter outcomes.json (and report) unchanged; every audit.py report is now re-derived with
    audit.build_report from the sealed evidence and must equal it."""
    c = copy_campaign(judged.campaign, tmp_path)
    path = c / "runs" / judged.real / "judge_report.json"
    honest = canonical.strict_load(path)
    assert honest == judged.audit.build_report(c, judged.real)            # the evaluator is deterministic
    assert honest["status"] == "completed" and honest["fidelity_error"] is not None
    forged = copy.deepcopy(honest)
    forged["fidelity_error"] = forged["v1_outcome"]["fidelity_error"] = 1e-7   # a better-looking v1 row
    contracts.validate_judge_report(forged)
    rewrite(path, canonical.canonical_bytes(forged) + b"\n")
    before = (c / "outcomes.json").read_bytes()
    assert runner.seal_problem(c / "runs" / judged.real)[1] is None      # every seal still reconciles
    for action, call in (("write outcomes", lambda: runner.write_outcomes(c)),
                         ("report", lambda: runner.report(c, n_bootstrap=50))):
        with pytest.raises(ContractError) as refused:
            call()
        message = str(refused.value)
        assert message.startswith(f"refusing to {action}: custody incident (human gate) in 1 run(s) "
                                  f"['{judged.real}']"), message
        assert "differs at ['fidelity_error', 'v1_outcome'] from the evaluator's re-derivation" in message
    assert (c / "outcomes.json").read_bytes() == before
    rewrite(path, canonical.canonical_bytes(honest) + b"\n")
    relabeled = {**canonical.strict_load(c / "runs" / judged.quiet / "judge_report.json"),
                 "campaign_id": "synthetic-another-campaign"}                 # passes the contract, not provenance
    rewrite(c / "runs" / judged.quiet / "judge_report.json", canonical.canonical_bytes(relabeled) + b"\n")
    with pytest.raises(ContractError, match="judge report provenance"):   # report() checks provenance too
        runner.report(c, n_bootstrap=50)


def test_campaign_json_changed_after_the_freeze_is_refused(judged, tmp_path):
    """R1.2: global caps, broker operations and fits live only in campaign.json; campaign_manifest.verify
    accepts a changed value (the gap), the coordinator's frozen digest does not."""
    c = copy_campaign(judged.campaign, tmp_path)
    frozen = (c / "campaign.json").read_bytes()
    manifest = canonical.strict_load(c / "campaign.json")
    manifest["budget"].update(global_usd_cap=1000.0, max_broker_ops=400, max_fits=40)   # SYNTHETIC edit
    rewrite(c / "campaign.json", campaign_manifest.manifest_bytes(manifest))
    assert campaign_manifest.verify(c) == {"ok": True, "errors": []}
    for call in (lambda: runner.write_outcomes(c), lambda: runner.report(c, n_bootstrap=50),
                 lambda: runner.run_campaign(c, adapter_factory=never, only=[])):
        with pytest.raises(ContractError, match=r"campaign integrity: campaign.json \(sha256 [0-9a-f]{64}\) differs "
                                                r"from the bytes frozen at build"):
            call()
    rewrite(c / "campaign.json", frozen)
    record = c / "coordinator" / runner.CAMPAIGN_DIGEST
    record.chmod(0o644)
    record.unlink()
    with pytest.raises(ContractError, match="campaign.sha256 is missing"):
        runner.write_outcomes(c)
    digest = canonical.sha256_bytes(frozen)
    assert last(judged.campaign, judged.real, "launched")["campaign_sha256"] == digest
    assert last(judged.campaign, judged.quiet, "materialized")["campaign_sha256"] == digest


def test_a_recorded_incident_decision_admits_only_the_evaluators_null_row(judged, tmp_path, capsys):
    """R1.6: one seal that does not reconcile used to block the campaign's outcomes for good. A recorded human
    decision (bound to the observed state) admits the evaluator's null-judgment row for that run only; every
    assignment ends with exactly one v1 row; a change after the decision refuses again."""
    c = copy_campaign(judged.campaign, tmp_path)
    final = c / "runs" / judged.lost / "sealed" / "final_text.txt"
    rewrite(final, final.read_bytes() + b"SYNTHETIC post-seal edit: sigma_vis < 0.1 fb\n")   # tree != manifest
    quiet = c / "runs" / judged.quiet
    reason = {**run_record(c, judged.quiet), "not_started_reason": "SYNTHETIC edited reason"}
    rewrite(quiet / "sealed" / "run.json", runner._pretty(reason))                  # consistent rewrite of a
    rewrite(quiet / "evidence_manifest.json", runner._pretty(canonical.tree_manifest(quiet / "sealed")))   # quiet run
    with pytest.raises(ContractError, match=r"custody incident \(human gate\) in 2 run\(s\)"):
        runner.write_outcomes(c)
    with pytest.raises(ContractError, match="its seal reconciles; there is no incident to decide"):
        runner.record_incident_decision(c, judged.real, decided_by="SYNTHETIC reviewer", reason="SYNTHETIC")
    with pytest.raises(ContractError, match="decided_by"):
        runner.record_incident_decision(c, judged.lost, decided_by=" ", reason="SYNTHETIC")
    path = runner.record_incident_decision(c, judged.lost, decided_by="SYNTHETIC reviewer (test fixture)",
                                           reason="SYNTHETIC: the final text was edited after sealing")
    decision = canonical.strict_load(path)
    assert decision["problem"].startswith("the sealed tree does not match its evidence manifest")
    assert decision["journaled_evidence_sha256"] == last(c, judged.lost, "sealed")["evidence_sha256"]
    with pytest.raises(ContractError, match=r"in 1 run\(s\) \['" + judged.quiet):
        runner.write_outcomes(c)                                      # the other incident still refuses
    assert cli.main(["incident-decision", "--campaign", str(c), "--run-id", judged.quiet, "--decided-by",
                     "SYNTHETIC reviewer (test fixture)", "--reason", "SYNTHETIC: reason edited after sealing"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"]["decision"] == runner.INCIDENT_DECISION
    outcomes = canonical.strict_load(runner.write_outcomes(c))
    assert [r["run_id"] for r in outcomes["outcomes"]] == [r["run_id"] for r in registry(c)["runs"]]
    rows = {r["run_id"]: r for r in outcomes["outcomes"]}
    lost = rows[judged.lost]
    assert (lost["status"], lost["unsupported_claim"], lost["refusal_valid"], lost["fidelity_error"]) == (
        "crash", None, None, None)
    assert lost["evidence_sha256"] == decision["journaled_evidence_sha256"] and "human decision" in lost["notes"]
    assert lost["executor_id"] == "synthetic-fake:reference" and lost["scorer_id"] == judged.audit.SCORER_ID
    assert rows[judged.quiet]["status"] == "not_started" and "SYNTHETIC reviewer" in rows[judged.quiet]["notes"]
    honest = {r["run_id"]: r for r in judged.outcomes["outcomes"]}
    assert all(rows[rid] == honest[rid] for rid in rows if rid not in (judged.lost, judged.quiet))
    runner.report(c, n_bootstrap=50)
    with pytest.raises(ContractError, match="refusing to overwrite"):
        runner.record_incident_decision(c, judged.lost, decided_by="SYNTHETIC reviewer", reason="SYNTHETIC again")
    rewrite(final, final.read_bytes() + b"SYNTHETIC second edit\n")      # changed after the decision
    with pytest.raises(ContractError, match="no longer describes the run's seal"):
        runner.write_outcomes(c)


# -- R0.1 / R0.3: the behavioral treatment check is a product check

def test_behavioral_check_passes_for_the_real_guard_and_fails_for_a_noop_guard(base, monkeypatch, capsys):
    """R0.1: the same stale and clean probe through a real broker per arm (cli.py treatment-diff --behavioral);
    a guard that never blocks passes the manifest check and fails this one."""
    campaign = build(base)
    assert cli.main(["treatment-diff", "--campaign", str(campaign), "--behavioral"]) == 0
    done = json.loads(capsys.readouterr().out)
    assert done["ok"] and done["manifest"]["ok"] and done["behavioral"]["ok"], done
    assert done["behavioral"]["task_id"] == "lf-c" and done["behavioral"]["violations"] == []
    record = canonical.strict_load(done["behavioral"]["record"])
    assert record["result"]["ok"] and record["campaign_sha256"] == canonical.sha256_file(campaign / "campaign.json")
    assert {d["code"] for d in record["observations"]["full"]["stale"]["diagnostics"]} == {
        "stale_conversion_dependency"}
    digest = canonical.sha256_file(campaign / "campaign.json")
    assert runner.behavioral_record_problem(campaign, digest) is None   # a real host could launch after it
    monkeypatch.setattr(guard, "evaluate", lambda submission, current_inputs, artifacts:
                        {"blocking": False, "diagnostics": []})      # SYNTHETIC no-op guard
    assert treatment.treatment_diff(canonical.strict_load(campaign / "campaign.json")["arms"])["ok"] is True
    noop = runner.behavioral_check(campaign)
    assert noop["ok"] is False
    assert "enforcement: accepted a submission with blocking diagnostics" in noop["violations"]
    assert "passing behavioral treatment check" in runner.behavioral_record_problem(campaign, "0" * 64)
    assert "no behavioral treatment check" in runner.behavioral_record_problem(base / "absent", digest)


def test_cli_refuses_the_mechanism_study_no_campaign_carries(base, capsys):
    """R0.3: the variant is library-level only; the CLI says so instead of checking an operator flag."""
    assert cli.main(["treatment-diff", "--campaign", str(base / "absent"), "--mechanism-study"]) == 2
    assert "library-level only in this slice" in json.loads(capsys.readouterr().out)["error"]
