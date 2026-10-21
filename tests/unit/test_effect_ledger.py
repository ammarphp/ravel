"""Effect ledger: domain paths, identity versus provisioning, attempts, write-ahead charges,
typed reconciliation and the re-entrant scope lock. Synthetic data only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from ravel.workflow import agent_graph, effect_ledger as ledger

INSTANCE = {"case": "synthetic"}
SEGMENT = {"stage": "ideas", "round": 1, "role": "proposer-a", "item": "s1"}
PATH = ledger.path("test.graph", INSTANCE, None, SEGMENT)
CARD = {"id": "card-a", "version": 1, "card_sha256": "c" * 64}


def counted(value):
    calls = []
    def function():
        calls.append(1)
        return value
    return calls, function


def call(root, function, *, identity=None, provisioning=None, version=1, path=PATH, kind="model", **kwargs):
    return ledger.call(root, graph={"id": "test.graph", "version": version}, path=path, kind=kind,
                       identity={"card": CARD, "instruction_sha256": "i" * 64} if identity is None else identity,
                       provisioning={"transport_id": "stub"} if provisioning is None else provisioning,
                       function=function, **kwargs)


class Crash(BaseException):
    """A process death at a chosen boundary: nothing below it runs."""


# ---- paths and ids ----------------------------------------------------------------------------

def test_path_is_graph_instance_parent_and_segment_without_version_or_task_id():
    digest = ledger.digest(INSTANCE)
    assert PATH == f"test.graph[{digest}]/stage:ideas/round:1/role:proposer-a/item:s1"
    child = ledger.path("rdj.case", {"case": "c"}, PATH, {"role": "critic"})
    assert child.startswith(PATH + "/rdj.case[") and child.endswith("/role:critic")
    assert ledger.extend(PATH, {"turn": 3, "tool": 1}) == PATH + "/turn:3/tool:1"
    with pytest.raises(agent_graph.GraphError):
        ledger.path("test.graph", INSTANCE, None, {"item": "a/b"})


def test_call_id_is_the_digest_of_scope_path_and_attempt():
    scope = "a" * 64
    expected = hashlib.sha256(json.dumps({"scope_id": scope, "path": PATH, "attempt": 2}, sort_keys=True,
                                         separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert ledger.call_id(scope, PATH, 2) == expected
    assert ledger.call_id(scope, PATH, 1) != expected
    with pytest.raises(agent_graph.GraphError):
        ledger.call_id(scope, PATH, 0)


def test_legacy_call_id_reproduces_control_call_identity():
    assert ledger.legacy_call_id("attempt-1", "model") == agent_graph.digest({"attempt_id": "attempt-1", "label": "model"})


def test_receipt_records_graph_path_attempt_identity_provisioning_epoch_and_framework_step(tmp_path):
    calls, function = counted({"answer": 42})
    assert call(tmp_path, function) == {"answer": 42}
    receipt = ledger.latest(tmp_path, PATH)
    assert receipt["graph"] == {"id": "test.graph", "version": 1} and receipt["path"] == PATH
    assert receipt["attempt"] == 1 and receipt["status"] == "completed"
    assert receipt["call_id"] == ledger.call_id(ledger.scope_id(tmp_path), PATH, 1)
    assert receipt["identity_sha256"] == receipt["request_sha256"]
    assert receipt["provisioning"] == {"transport_id": "stub"}
    assert receipt["epoch"] == {"runner": 0, "cancellation": 0}
    assert set(receipt["framework_step"]) == {"thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "node_attempt",
                                              "kernel_module_sha256"}
    assert receipt["framework_step"]["kernel_module_sha256"]["effect_ledger.py"]
    assert receipt["supersedes"] is None and receipt["superseded_by"] is None and receipt["downstream"] is None


# ---- ledger rules (acceptance 9) --------------------------------------------------------------

def test_completed_effect_replays_and_provisioning_drift_is_recorded_not_compared(tmp_path):
    calls, function = counted({"answer": 42})
    call(tmp_path, function)
    drift = []
    assert call(tmp_path, function, provisioning={"transport_id": "stub", "atlas_sha256": "new"}, drift=drift) \
        == {"answer": 42}
    assert len(calls) == 1
    assert drift == [{"call_id": ledger.latest(tmp_path, PATH)["call_id"], "path": PATH, "keys": ["atlas_sha256"]}]
    assert ledger.latest(tmp_path, PATH)["reuses"][-1]["provisioning_drift"] == ["atlas_sha256"]


def test_version_bump_keeps_call_ids_and_reuses_equal_identity_at_zero_dispatch(tmp_path):
    calls, function = counted({"answer": 1})
    call(tmp_path, function, version=1)
    before = ledger.latest(tmp_path, PATH)["call_id"]
    assert call(tmp_path, function, version=2) == {"answer": 1}
    assert len(calls) == 1 and ledger.latest(tmp_path, PATH)["call_id"] == before
    assert [r["attempt"] for r in ledger.attempts(tmp_path, PATH)] == [1]


def test_started_effect_from_an_old_version_is_ambiguous_and_never_redispatched(tmp_path):
    def crash():
        raise Crash()
    with pytest.raises(Crash):
        call(tmp_path, crash, version=1)
    calls, function = counted({"x": 1})
    for version in (1, 2, 3):
        with pytest.raises(ledger.Ambiguous):
            call(tmp_path, function, version=version)
        with pytest.raises(ledger.Ambiguous):
            call(tmp_path, function, version=version, identity={"card": {**CARD, "version": 9}})
    assert calls == [] and [r["status"] for r in ledger.attempts(tmp_path, PATH)] == ["started"]


def test_identity_change_with_declared_version_change_supersedes_the_old_attempt(tmp_path):
    calls, function = counted({"v": "old"})
    call(tmp_path, function, version=1)
    old = ledger.latest(tmp_path, PATH)
    _, newer = counted({"v": "new"})
    assert call(tmp_path, newer, version=2, identity={"card": CARD, "instruction_sha256": "j" * 64}) == {"v": "new"}
    first, second = ledger.attempts(tmp_path, PATH)
    assert first["status"] == "superseded" and first["superseded_by"] == second["call_id"]
    assert second["attempt"] == 2 and second["supersedes"] == old["call_id"]
    # A card version change is a declared change too.
    _, third = counted({"v": "card"})
    call(tmp_path, third, version=2, identity={"card": {**CARD, "version": 2}, "instruction_sha256": "j" * 64})
    assert [r["status"] for r in ledger.attempts(tmp_path, PATH)] == ["superseded", "superseded", "completed"]


def test_identity_change_without_declared_change_is_nondeterministic_for_model_work(tmp_path):
    calls, function = counted({"v": 1})
    call(tmp_path, function)
    with pytest.raises(ledger.NondeterministicRequest):
        call(tmp_path, function, identity={"card": CARD, "instruction_sha256": "k" * 64})
    assert len(calls) == 1


def test_deterministic_checks_rerun_under_a_new_implementation_and_require_its_digest(tmp_path):
    with pytest.raises(agent_graph.GraphError, match="implementation_sha256"):
        call(tmp_path, lambda: 1, kind="check", identity={"input": "a"})
    calls, function = counted({"ok": True})
    call(tmp_path, function, kind="check", identity={"input": "a", "implementation_sha256": "1" * 64})
    call(tmp_path, function, kind="check", identity={"input": "a", "implementation_sha256": "2" * 64})
    assert len(calls) == 2
    assert [r["status"] for r in ledger.attempts(tmp_path, PATH)] == ["superseded", "completed"]


# ---- attempts from the ledger (acceptance 10) ------------------------------------------------

def test_attempt_numbers_come_from_the_ledger_and_the_retry_bound_holds(tmp_path):
    def fail():
        raise ledger.NotDispatched("synthetic refusal before sending")
    with pytest.raises(ledger.NotDispatched):
        call(tmp_path, fail, max_attempts=2)
    with pytest.raises(ledger.NotDispatched):
        call(tmp_path, fail, max_attempts=2)
    assert [(r["attempt"], r["status"]) for r in ledger.attempts(tmp_path, PATH)] == [(1, "failed"), (2, "failed")]
    with pytest.raises(ledger.CallFailed):
        call(tmp_path, fail, max_attempts=2)
    calls, function = counted({"third": True})
    assert call(tmp_path, function, max_attempts=3) == {"third": True}
    assert ledger.latest(tmp_path, PATH)["attempt"] == 3


# ---- write-ahead charging (acceptance 12) ----------------------------------------------------

class FakeLedger:
    def __init__(self):
        self.applied = []
        self.crash_on = None

    def present(self, root, identity):
        return identity in self.applied

    def apply(self, root, identity, amount):
        if self.crash_on == "before_apply":
            raise Crash()
        self.applied.append(identity)
        if self.crash_on == "after_apply":
            raise Crash()


@pytest.mark.parametrize("boundary", ["before_apply", "after_apply", "before_started", "inside_function"])
def test_write_ahead_charging_survives_a_crash_at_each_boundary(tmp_path, monkeypatch, boundary):
    fake = FakeLedger()
    charges = [{"ledger": "campaign", "amount": 1}]
    calls = []

    def function():
        calls.append(1)
        if boundary == "inside_function":
            raise Crash()
        return {"done": True}

    with ledger.registrations(charge_ledgers={"campaign": (fake.present, fake.apply)}):
        fake.crash_on = boundary if boundary in {"before_apply", "after_apply"} else None
        if boundary == "before_started":
            real = ledger._write
            def write(root, record):
                if record["status"] == "started":
                    raise Crash()
                return real(root, record)
            monkeypatch.setattr(ledger, "_write", write)
        with pytest.raises(Crash):
            call(tmp_path, function, charges=charges)
        monkeypatch.undo()
        fake.crash_on = None
        recovered = ledger.recover(tmp_path)
        if boundary == "inside_function":
            assert recovered["ambiguous"] and len(fake.applied) == 1
            with pytest.raises(ledger.Ambiguous):
                call(tmp_path, function, charges=charges)
            assert len(calls) == 1
        else:
            assert recovered["reserving_recovered"]
            assert call(tmp_path, function, charges=charges) == {"done": True}
            assert len(calls) == 1
        assert len(fake.applied) == 1
        assert all(c["applied"] for c in ledger.latest(tmp_path, PATH)["charges"])
        assert ledger.usage(tmp_path, PATH)["charged"] == {"campaign": 1}


def test_an_unbound_charge_ledger_is_refused_before_any_dispatch(tmp_path):
    calls, function = counted(1)
    with pytest.raises(agent_graph.GraphError, match="not bound"):
        call(tmp_path, function, charges=[{"ledger": "run_ceilings", "amount": 1}])
    assert calls == [] and ledger.attempts(tmp_path, PATH) == []


# ---- reconciliation through typed validators (acceptance 2) --------------------------------

def _started(tmp_path, downstream="worker/out.json"):
    def crash():
        raise Crash()
    with pytest.raises(Crash):
        call(tmp_path, crash, downstream={"kind": "worker_receipt", "path": downstream})
    return ledger.latest(tmp_path, PATH)


def _write_downstream(tmp_path, saved, **overrides):
    document = {"status": "completed", "identity_sha256": saved["identity_sha256"],
                "epoch": {"cancellation": saved["epoch"]["cancellation"]}, "result": {"from": "worker"}, **overrides}
    target = tmp_path / "worker" / "out.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(document))


def accept(root, receipt, document):
    return {"status": document["status"], "result": document["result"]}


def test_auto_reconcile_closes_only_through_the_registered_typed_validator(tmp_path):
    saved = _started(tmp_path)
    _write_downstream(tmp_path, saved)
    assert ledger.auto_reconcile(tmp_path, saved["call_id"]) is None  # no validator registered
    with ledger.registrations(validators={"worker_receipt": accept}):
        closed = ledger.auto_reconcile(tmp_path, saved["call_id"])
        assert closed["status"] == "completed" and closed["reconciliation"]["auto"] is True
        calls, function = counted({"never": True})
        assert call(tmp_path, function, downstream={"kind": "worker_receipt", "path": "worker/out.json"}) \
            == {"from": "worker"}
    assert calls == []


@pytest.mark.parametrize("defect", ["identity", "epoch", "live_group", "live_child", "validator_refuses"])
def test_auto_reconcile_refuses_a_mismatched_stale_or_live_downstream_receipt(tmp_path, defect):
    saved = _started(tmp_path)
    if defect == "epoch":
        # Written under a cancellation epoch older than the reservation's: stale.
        _write_downstream(tmp_path, saved, epoch={"cancellation": saved["epoch"]["cancellation"] - 1})
    elif defect == "identity":
        _write_downstream(tmp_path, saved, identity_sha256="f" * 64)
    elif defect == "live_group":
        _write_downstream(tmp_path, saved, pgid=os.getpgid(0))
    elif defect == "live_child":
        _write_downstream(tmp_path, saved, pgid=2 ** 30, child_pgid=os.getpgid(0))
    else:
        _write_downstream(tmp_path, saved)
    validator = (lambda root, receipt, document: (_ for _ in ()).throw(ValueError("refused"))) \
        if defect == "validator_refuses" else accept
    with ledger.registrations(validators={"worker_receipt": validator}):
        assert ledger.auto_reconcile(tmp_path, saved["call_id"]) is None
    assert ledger.read(tmp_path, saved["call_id"])["status"] == "started"


def test_reconcile_requires_matching_evidence_pins_and_not_dispatched_allows_a_new_attempt(tmp_path):
    saved = _started(tmp_path)
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"observed": "synthetic"}')
    pin = {"path": "evidence.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
    with pytest.raises(agent_graph.GraphError):
        ledger.reconcile(tmp_path, saved["call_id"], outcome="completed", evidence=[{**pin, "sha256": "0" * 64}],
                         reason="x", result={})
    record = ledger.reconcile(tmp_path, saved["call_id"], outcome="not_dispatched", evidence=[pin],
                              reason="synthetic: the worker never started")
    assert record["status"] == "reconciled" and record["reconciliation"]["truth_authenticated"] is False
    calls, function = counted({"second": True})
    assert call(tmp_path, function, max_attempts=2) == {"second": True}
    assert [r["attempt"] for r in ledger.attempts(tmp_path, PATH)] == [1, 2]


def test_downstream_must_be_scope_relative_and_a_tampered_result_is_refused(tmp_path):
    with pytest.raises(agent_graph.GraphError):
        call(tmp_path, lambda: 1, downstream={"kind": "worker_receipt", "path": "/etc/passwd"})
    calls, function = counted({"v": 1})
    call(tmp_path, function)
    saved = ledger.latest(tmp_path, PATH)
    target = tmp_path / "calls" / (saved["call_id"] + ".json")
    target.write_text(json.dumps({**saved, "result": {"v": 2}}))
    with pytest.raises(agent_graph.GraphError, match="result changed"):
        call(tmp_path, function)


def test_revalidate_callback_and_output_pins_run_on_reuse(tmp_path):
    output = tmp_path / "out.txt"
    output.write_text("a")
    pin = {"path": "out.txt", "sha256": hashlib.sha256(b"a").hexdigest()}
    seen = []
    call(tmp_path, lambda: {"pins": [pin]}, revalidate=seen.append)
    call(tmp_path, lambda: {"pins": [pin]}, revalidate=seen.append)
    assert len(seen) == 1
    output.write_text("b")
    with pytest.raises(agent_graph.GraphError, match="pin changed"):
        call(tmp_path, lambda: {"pins": [pin]})


def test_usage_counts_receipts_under_a_prefix(tmp_path):
    for item in ("a", "b"):
        call(tmp_path, lambda: 1, path=ledger.path("test.graph", INSTANCE, None, {"stage": "s", "item": item}))
    call(tmp_path, lambda: 1, path=ledger.path("test.graph", INSTANCE, None, {"stage": "t", "item": "a"}))
    prefix = ledger.path("test.graph", INSTANCE, None, {"stage": "s"})
    assert ledger.usage(tmp_path, prefix)["status"]["completed"] == 2


# ---- re-entrant scope lock -------------------------------------------------------------------

def test_reentrant_lock_admits_nested_and_sibling_threads_and_refuses_another_process(tmp_path):
    lock = tmp_path / "operation.lock"
    order = []

    def sibling():
        with ledger.reentrant_lock(lock):
            order.append("thread")

    code = ("import sys; sys.path.insert(0, sys.argv[2])\n"
            "from ravel.workflow import effect_ledger as l\n"
            "try:\n    l.reentrant_lock(sys.argv[1], admission=True).__enter__(); print('acquired')\n"
            "except Exception as e:\n    print('refused', e)")
    with ledger.reentrant_lock(lock):
        with ledger.reentrant_lock(lock):
            order.append("nested")
        worker = threading.Thread(target=sibling)
        worker.start()
        done = subprocess.run([sys.executable, "-c", code, str(lock), str(Path(ledger.__file__).parents[2])],
                              capture_output=True, text=True, timeout=60)
        assert done.stdout.startswith("refused") and "another process owns" in done.stdout
        order.append("released")
    worker.join(10)
    assert order == ["nested", "released", "thread"]


# ---- exactly once under supersession and exceptions ------------------------------------

def _card(version, marker):
    return {"card": {**CARD, "version": version}, "instruction_sha256": marker * 64}


def test_a_crash_inside_supersession_never_reuses_a_call_id_or_loses_a_charge(tmp_path, monkeypatch):
    fake = FakeLedger()
    charges = [{"ledger": "campaign", "amount": 1}]
    runs = []

    def make(tag):
        def function():
            runs.append(tag)
            return {"version": tag}
        return function

    with ledger.registrations(charge_ledgers={"campaign": (fake.present, fake.apply)}):
        call(tmp_path, make(1), identity=_card(1, "a"), version=1, charges=charges)
        real = ledger._write

        def write(root, record):
            if record["status"] == "superseded":
                raise Crash()
            return real(root, record)
        monkeypatch.setattr(ledger, "_write", write)
        with pytest.raises(Crash):
            call(tmp_path, make(2), identity=_card(2, "b"), version=2, charges=charges)
        monkeypatch.undo()
        ledger.recover(tmp_path)
        assert call(tmp_path, make(2), identity=_card(2, "b"), version=2, charges=charges) == {"version": 2}
        assert call(tmp_path, make(3), identity=_card(3, "c"), version=3, charges=charges) == {"version": 3}
    history = ledger.attempts(tmp_path, PATH)
    assert [(r["attempt"], r["status"]) for r in history] == [(1, "superseded"), (2, "superseded"), (3, "completed")]
    assert len({r["call_id"] for r in history}) == 3
    assert history[1]["result"] == {"version": 2} and history[1]["superseded_by"] == history[2]["call_id"]
    assert runs == [1, 2, 3] and len(fake.applied) == 3


@pytest.mark.parametrize("kind", ["model", "worker", "external", "journal", "native"])
def test_an_exception_from_a_dispatched_effect_is_ambiguous_and_never_dispatched_again(tmp_path, kind):
    runs = []

    def act():
        runs.append(1)
        raise ValueError("synthetic: the response was lost after sending")
    with pytest.raises(ledger.Ambiguous):
        call(tmp_path, act, kind=kind, max_attempts=3)
    with pytest.raises(ledger.Ambiguous):
        call(tmp_path, act, kind=kind, max_attempts=3)
    assert runs == [1] and ledger.latest(tmp_path, PATH)["status"] == "ambiguous"


def test_a_result_that_cannot_be_receipted_after_the_action_is_ambiguous(tmp_path):
    runs = []

    def act():
        runs.append(1)
        return {"value": float("nan")}
    with pytest.raises(ledger.Ambiguous):
        call(tmp_path, act, max_attempts=2)
    with pytest.raises(ledger.Ambiguous):
        call(tmp_path, act, max_attempts=2)
    assert runs == [1]


def test_only_a_typed_not_dispatched_failure_or_a_deterministic_kind_may_retry(tmp_path):
    def refuse():
        raise ledger.NotDispatched("synthetic: refused before sending")
    with pytest.raises(ledger.NotDispatched):
        call(tmp_path, refuse, max_attempts=2)
    assert ledger.latest(tmp_path, PATH)["status"] == "failed"
    calls, function = counted({"second": True})
    assert call(tmp_path, function, max_attempts=2) == {"second": True}
    check = ledger.path("test.graph", INSTANCE, None, {"stage": "check"})
    identity = {"implementation_sha256": "d" * 64}
    with pytest.raises(KeyError):
        call(tmp_path, lambda: {}["missing"], kind="check", identity=identity, path=check, max_attempts=2)
    assert ledger.latest(tmp_path, check)["status"] == "failed"
    assert call(tmp_path, lambda: {"ok": True}, kind="check", identity=identity, path=check,
                max_attempts=2) == {"ok": True}


# ---- downstream receipts: validator required, current cancellation epoch ---------------

def test_reuse_refuses_a_declared_downstream_without_its_registered_validator(tmp_path):
    downstream = {"kind": "worker_receipt", "path": "worker/out.json"}

    def act():
        _write_downstream(tmp_path, ledger.latest(tmp_path, PATH))
        return {"from": "worker"}
    with ledger.registrations(validators={"worker_receipt": accept}):
        assert call(tmp_path, act, downstream=downstream) == {"from": "worker"}
        assert call(tmp_path, act, downstream=downstream) == {"from": "worker"}
    # agent_worker registers this kind at import; unregister it here so the
    # refusal does not depend on which test modules ran first.
    with ledger.registrations():
        ledger._VALIDATORS.pop("worker_receipt", None)
        with pytest.raises(agent_graph.GraphError, match="validator"):
            call(tmp_path, act, downstream=downstream)


def test_a_downstream_receipt_from_before_the_current_cancellation_is_historical_not_a_close(tmp_path):
    saved = _started(tmp_path)
    _write_downstream(tmp_path, saved)
    ledger.bump_epoch(tmp_path, "cancellation")
    with ledger.registrations(validators={"worker_receipt": accept}):
        assert ledger.auto_reconcile(tmp_path, saved["call_id"]) is None
        record = ledger.read(tmp_path, saved["call_id"])
        assert record["status"] == "started"
        assert record["historical_downstream"][0]["epoch"]["cancellation"] == saved["epoch"]["cancellation"]
        _write_downstream(tmp_path, saved, epoch={"cancellation": ledger.epoch(tmp_path)["cancellation"]})
        assert ledger.auto_reconcile(tmp_path, saved["call_id"])["status"] == "completed"


# ---- reconciliation never closes a live effect ----------------------------------------

def _pin(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"observed": "synthetic"}')
    return {"path": "evidence.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}


def test_reconcile_refuses_an_effect_that_is_still_executing(tmp_path):
    pin = _pin(tmp_path)
    refused = []

    def act():
        saved = ledger.latest(tmp_path, PATH)
        try:
            ledger.reconcile(tmp_path, saved["call_id"], outcome="not_dispatched", evidence=[pin], reason="x")
        except agent_graph.GraphError as exc:
            refused.append(str(exc))
        return {"done": True}
    assert call(tmp_path, act) == {"done": True}
    assert refused and "in flight" in refused[0]
    assert ledger.latest(tmp_path, PATH)["status"] == "completed"


def test_an_outcome_never_overwrites_a_reconciliation_written_while_the_effect_ran(tmp_path):
    def act():
        saved = ledger.latest(tmp_path, PATH)
        # Another process closed the record while this effect ran.
        ledger._write(tmp_path, {**saved, "status": "reconciled", "reconciliation": {"outcome": "not_dispatched"}})
        return {"late": True}
    with pytest.raises(ledger.Ambiguous):
        call(tmp_path, act)
    record = ledger.latest(tmp_path, PATH)
    assert record["status"] == "reconciled"
    assert record["late_outcomes"][0]["status"] == "completed"
    assert record["late_outcomes"][0]["result_sha256"] == ledger.digest({"late": True})


def test_reconcile_refuses_while_another_process_holds_the_scope(tmp_path):
    saved = _started(tmp_path)
    pin = _pin(tmp_path)
    code = ("import sys, time; sys.path.insert(0, sys.argv[2])\n"
            "from ravel.workflow.state_io import file_lock\n"
            "with file_lock(sys.argv[1], blocking=False):\n"
            "    print('held', flush=True); time.sleep(60)")
    holder = subprocess.Popen([sys.executable, "-c", code, str(tmp_path / ledger.SCOPE_LOCK),
                               str(Path(ledger.__file__).parents[2])], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(agent_graph.GraphError, match="runner holds the scope"):
            ledger.reconcile(tmp_path, saved["call_id"], outcome="not_dispatched", evidence=[pin], reason="x")
    finally:
        holder.terminate()
        holder.wait(30)
    assert ledger.reconcile(tmp_path, saved["call_id"], outcome="not_dispatched", evidence=[pin],
                            reason="x")["status"] == "reconciled"


# ---- the worker-delegation API ------------------------------------------------------------------

def test_delegated_calls_key_on_the_legacy_call_id_and_replay_their_verified_result(tmp_path):
    where = ledger.delegated_path("graph-1", "attempt-1", "ask a model / step 1")
    assert where == ledger.delegated_path("graph-1", "attempt-1", "ask a model / step 1")
    assert ledger.legacy_call_id("attempt-1", "ask a model / step 1") in where
    calls, function = counted({"answer": 1})
    arguments = dict(graph_id="graph-1", attempt_id="attempt-1", label="ask a model / step 1", kind="model",
                     request={"question": 1})
    assert ledger.delegate(tmp_path, function=function, **arguments) == {"answer": 1}
    assert ledger.delegate(tmp_path, function=function, **arguments) == {"answer": 1}
    assert calls == [1]
    record = ledger.delegated(tmp_path, "graph-1", "attempt-1", "ask a model / step 1")
    assert record["identity"] == {"legacy_call_id": ledger.legacy_call_id("attempt-1", "ask a model / step 1"),
                                  "request_sha256": agent_graph.digest({"question": 1})}
    assert ledger.verified_result(tmp_path, record["call_id"]) == {"answer": 1}
    with pytest.raises(ledger.NondeterministicRequest):
        ledger.delegate(tmp_path, function=function, **{**arguments, "request": {"question": 2}})
    with pytest.raises(agent_graph.GraphError, match="kind"):
        ledger.delegate(tmp_path, function=function, **{**arguments, "label": "x", "kind": "shell"})
    assert ledger.LEGACY_KINDS == {"model": "model", "tool": "external", "worker": "worker"}


def test_deliver_external_closes_only_the_correlated_paused_effect(tmp_path):
    class AwaitingExternal(Exception):
        ambiguous = True
    arguments = dict(graph_id="graph-1", attempt_id="attempt-1", label="fetch", kind="tool", request={"url": "u"})

    def pause():
        raise AwaitingExternal("synthetic: delivered later")
    with pytest.raises(ledger.Ambiguous):
        ledger.delegate(tmp_path, function=pause, **arguments)
    record = ledger.delegated(tmp_path, "graph-1", "attempt-1", "fetch")
    assert record["kind"] == "external" and record["status"] == "ambiguous"
    with pytest.raises(agent_graph.GraphError, match="not completed"):
        ledger.verified_result(tmp_path, record["call_id"])
    receipt = {"call_id": ledger.legacy_call_id("attempt-1", "fetch"),
               "request_sha256": agent_graph.digest({"url": "u"}), "status": "completed", "result": {"fetched": 1}}
    with pytest.raises(agent_graph.GraphError, match="correlate"):
        ledger.deliver_external(tmp_path, record["call_id"], receipt={**receipt, "request_sha256": "0" * 64},
                                reason="synthetic delivery")
    closed = ledger.deliver_external(tmp_path, record["call_id"], receipt=receipt, reason="synthetic delivery")
    assert closed["status"] == "completed" and closed["reconciliation"]["evidence"][0]["path"].startswith("calls/")
    assert ledger.delegate(tmp_path, function=pause, **arguments) == {"fetched": 1}
    assert ledger.verified_result(tmp_path, record["call_id"]) == {"fetched": 1}


def test_a_refused_campaign_reservation_is_a_definite_failure_never_an_ambiguous_effect(tmp_path):
    """A research campaign's reservation boundary refuses before dispatch; the loop ends on it, bounded."""
    from ravel.workflow import research_cycle

    def reserve():
        raise research_cycle.CampaignBudgetExhausted('cumulative research resource ceiling exhausted: calls')
    with pytest.raises(research_cycle.CampaignBudgetExhausted):
        call(tmp_path, reserve)
    assert [(r["attempt"], r["status"], r["error_type"]) for r in ledger.attempts(tmp_path, PATH)] == \
        [(1, "failed", "CampaignBudgetExhausted")]

    def dispatched_then_ambiguous():
        raise RuntimeError("synthetic: the action may have been sent")
    with pytest.raises(ledger.Ambiguous):
        call(tmp_path / "other", dispatched_then_ambiguous)
