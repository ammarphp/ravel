"""P01 records the intake rows of the obligation ledger from the records their enforcing actions wrote.

The intake transition (``intake->route_select``) requires every current row at node
``controller.intake``; ``route_select->plan`` adds ``controller.route_select``. Nobody may satisfy
these rows by fiat: the controller's recorder map (``graph.RECORDERS``) asks each row's provider
for the record its enforcing action wrote (P01's request, intake, binding and command-policy
records, P06's authenticated mode record, P05's admission record, P12's layout check and P14's
host observation) and records a pointer that ``store.read`` resolves. A row whose provider shows
no evidence stays pending and the transition holds.

These tests run the real ledger, the real authority service and the real confinement admission.
Two stand-ins remain, each for something a test process cannot provide: the installed-code
identity (a test runs from a checkout) and the operator's restricted-source policy, which the
closed operator configuration cannot carry yet.
"""
from __future__ import annotations

import json
import re

import pytest

import fakes
from ravel.controller import entry, graph, ledger
from ravel.controller.ledger import state as ledger_state

INTAKE = "intake->route_select"
REQUEST = fakes.REQUEST
# The identity of an installed, read-only RAVEL (a test process runs from a checkout).
INSTALLED = {"kind": "installed", "package_dir": "/read-only/site-packages/ravel", "version": "0", "checkout": None,
             "writable_by_controller_user": False, "symlinks": [], "selectors": {}, "digest": "tree:" + "0" * 64}


@pytest.fixture
def real(tmp_path, monkeypatch):
    """An inert controller run on the real ledger, authority and confinement admission."""
    fakes.isolate(tmp_path, monkeypatch)
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])  # a controller declaration lasts for its process
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    operator.init(mode="autonomous")
    # This unit harness substitutes the governed step graph and decision gates;
    # it issues no RDJ credit. The real final seat is covered by test_composition_wave_a.
    from ravel.controller import authority
    monkeypatch.setattr(authority, "review_final_task", lambda *args: None)
    monkeypatch.setattr(authority, "review_deviation", lambda *args: None)  # the same RDJ seat seam
    sources = tmp_path / "operator" / "restricted-sources.json"
    sources.parent.mkdir()
    sources.write_text(json.dumps({"kind": "restricted-sources", "fingerprints": ["fictional private example"]}))
    from ravel.controller.confine import policy
    settings = policy.runs.operator_settings
    monkeypatch.setattr(policy.runs, "operator_settings", lambda: {**settings(), "restricted_sources": str(sources)})
    monkeypatch.setattr(policy.identity, "code_identity", lambda **_: dict(INSTALLED))
    stores = []
    with fakes.stand_in_graphs():
        yield {"tmp": tmp_path, "stores": stores}
    for store in stores:
        ledger_state.forget(store)


def _drive(real, name="r1", **overrides):
    """Start and drive a run on the real services (``overrides`` replaces named services)."""
    store = entry.start(REQUEST, channel="terminal", rundir=real["tmp"] / "runs" / name)
    real["stores"].append(store)
    with graph.services(**overrides):
        observation = entry.drive(store, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
    return store, observation


def _instances(store):
    return ledger_state.load(store, full=True).instances


def _resolve(store, record_id):
    """The store record a ``record`` pointer names (the kind is the id's prefix)."""
    kind = record_id.rsplit("-", 2)[0]
    return store.read(kind, record_id)


def _pointers(evidence):
    return [value for key, value in evidence.items() if key == "record" or key.endswith("_record")]


def _unmet(store, transition):
    return sorted(row["id"] or row["entry"] for row in ledger.gate(store, transition))


class _Omitting:
    """The real authority service whose intake mode freeze writes nothing (the record is omitted)."""

    def __init__(self, tamper=None):
        from ravel.controller import authority
        self._authority, self._tamper = authority, tamper

    def __getattr__(self, name):
        return getattr(self._authority, name)

    def freeze_mode(self, store, contract, *, run_dir=None):
        if self._tamper is None:
            return {"installed": True, "record_id": None}
        frozen = self._authority.freeze_mode(store, contract, run_dir=run_dir)
        self._tamper(store, frozen)
        return frozen


def _forge(store, frozen):
    """A worker appends a mode record of its own to the store, outside the issuer's custody."""
    store.append("mode", {**{k: v for k, v in frozen.items() if k not in ("id", "issuer")}, "mode": "autonomous",
                          "uid": "f" * 32, "delegation": "operator_configured"})


# P01's rows and the providers whose records discharge the intake rows (the recorder map).
P01_ROWS = ("CT01", "R01", "C25", "C41", "CT03", "SW20", "SW13", "R11")
P06_ROWS = ("A04", "CT04", "SW25")
P05_ROWS = ("SW23", "SW29", "SW16")
HOOK_ROWS = ("L01", "SW26", "SW15")  # the P12 layout check and the P14 host observation


def test_intake_gate_passes_with_real_evidence_only(real):
    store, observation = _drive(real)
    instances = _instances(store)
    recorded = {key.split("@", 1)[0]: instance for key, instance in instances.items()
                if instance.stage == "intake" and instance.status != "pending"}
    for row in P01_ROWS + P06_ROWS + P05_ROWS + HOOK_ROWS + ("R02",):
        assert row in recorded, (row, _unmet(store, INTAKE), store.latest("ledger-evidence"))
        instance = recorded[row]
        assert instance.status == "satisfied", (row, instance.status)
        pointers = _pointers(instance.evidence)
        assert pointers, (row, instance.evidence)
        for pointer in pointers:
            assert _resolve(store, pointer)["id"] == pointer
    assert recorded["A04"].evidence["record"] == store.latest("mode")["id"]
    assert recorded["CT01"].evidence["record"] == store.latest("intake")["id"]
    assert recorded["C25"].evidence["record"] == store.scan("run")[0]["id"]
    assert recorded["SW23"].evidence["record"] == store.latest("code-identity")["id"]
    assert recorded["R02"].evidence["record"] == store.scan("route")[0]["id"]
    assert ledger.gate(store, INTAKE) == [] and ledger.gate(store, "route_select->plan") == []
    # Rows whose enforcing action never happened in this run stay pending (no blanket satisfaction): no stop,
    # steering, unblinding or terminal answer occurred.
    untouched = [key for key, instance in instances.items()
                 if key.split("@", 1)[0] in ("B05", "C37", "A11", "CT07") and instance.status != "pending"]
    assert untouched == []

    # Negative controls: the mode record omitted before the rows are recorded, or forged by a worker.
    for name, tamper in (("omitted", None), ("forged", _forge)):
        held, observation = _drive(real, name, authority=_Omitting(tamper))
        rows = {key.split("@", 1)[0]: instance for key, instance in _instances(held).items()}
        assert rows["A04"].status in ("pending", "violated"), name
        assert rows["CT04"].status in ("pending", "violated") and rows["SW25"].status in ("pending", "violated")
        assert rows["CT01"].status == "satisfied"  # the other providers' evidence is unaffected
        assert {"A04", "CT04", "SW25"} <= set(_unmet(held, INTAKE)), name
        assert observation["terminal"]["status"] == "qualified" and held.latest("route") is None


def test_L01_SW26_SW15_are_recorded_from_the_legacy_check_and_the_host_observation(real):
    store, _ = _drive(real)
    rows = {key.split("@", 1)[0]: instance for key, instance in _instances(store).items()}
    layout = _resolve(store, rows["SW26"].evidence["record"])
    assert layout["kind"] == "legacy-layout" and layout["record"]["view"]["layout"] == "controller"
    assert layout["record"]["view"]["controller_run"] == store.run_id
    assert rows["L01"].evidence["record"] == layout["id"]
    admission = _resolve(store, rows["L01"].evidence["admission_record"])
    assert admission["kind"] == "legacy-admission" and admission["record"]["layout"] == "absent"
    host = _resolve(store, rows["SW15"].evidence["record"])
    assert host["kind"] == "host-observation" and host["record"]["tripwire"]["mode"] == "block"
    assert host["record"]["tripwire"]["declared"] == store.run_id
    # A process the operator already runs with the tripwire on (``1``) blocks the same way.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("RAVEL_AGENT_TRIPWIRE", "1")
        enabled, _ = _drive(real, "enabled")
    rows_enabled = {key.split("@", 1)[0]: instance for key, instance in _instances(enabled).items()}
    assert rows_enabled["SW15"].status == "satisfied"
    assert _resolve(enabled, rows_enabled["SW15"].evidence["record"])["record"]["tripwire"]["mode"] == "1"

    # Negative controls. An epoch-one contract at the run root before the intake: the run's layout is
    # downgraded, so L01 and SW26 stay pending and the intake holds.
    downgraded = entry.start(REQUEST, channel="terminal", rundir=real["tmp"] / "runs" / "downgraded")
    real["stores"].append(downgraded)
    (downgraded.run_dir / "task_contract.json").write_text(json.dumps({"task_mode": "reproduce"}))
    observation = entry.drive(downgraded, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
    rows = {key.split("@", 1)[0]: instance for key, instance in _instances(downgraded).items()}
    assert rows["L01"].status == "pending" and rows["SW26"].status == "pending"
    assert {"L01", "SW26"} <= set(_unmet(downgraded, INTAKE))
    assert observation["terminal"]["status"] == "qualified" and downgraded.latest("route") is None
    # A graph started outside the controller entry: no process declaration and no admission, so SW15
    # and the admission rows stay pending.
    from ravel.workflow import graph_substrate as gs
    outside = entry.start(REQUEST, channel="terminal", rundir=real["tmp"] / "runs" / "outside")
    real["stores"].append(outside)
    gs.run(outside.graph_scope(), graph.GRAPH_ID, {"run_id": outside.run_id},
           input=entry._run_input(outside, unattended=False, workers=1),
           gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
    rows = {key.split("@", 1)[0]: instance for key, instance in _instances(outside).items()}
    assert all(rows[row].status == "pending" for row in ("SW15", "SW23", "SW29", "SW16"))
    assert {"SW15", "SW23", "SW29"} <= set(_unmet(outside, INTAKE)) and outside.latest("route") is None


def test_SW23_SW29_an_unadmitted_install_or_source_policy_starts_no_graph(real, monkeypatch):
    from ravel.controller.confine import policy
    checkout = {**INSTALLED, "kind": "checkout", "checkout": "/work", "writable_by_controller_user": True,
                "selectors": {"RAVEL_ROOT": "/work"}}
    monkeypatch.setattr(policy.identity, "code_identity", lambda **_: dict(checkout))
    store = entry.start(REQUEST, channel="terminal", rundir=real["tmp"] / "runs" / "checkout")
    real["stores"].append(store)
    with pytest.raises(entry.EntryError, match="not admitted"):
        entry.drive(store, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
    assert store.latest("intake") is None and store.scan("code-identity") == []
    # Installed code without the operator's restricted-source policy is refused as well.
    monkeypatch.setattr(policy.identity, "code_identity", lambda **_: dict(INSTALLED))
    settings = policy.runs.operator_settings
    monkeypatch.setattr(policy.runs, "operator_settings",
                        lambda: {k: v for k, v in settings().items() if k != "restricted_sources"})
    unpinned = entry.start(REQUEST, channel="terminal", rundir=real["tmp"] / "runs" / "unpinned")
    real["stores"].append(unpinned)
    with pytest.raises(entry.EntryError, match="not admitted: operator restricted_sources"):
        entry.drive(unpinned, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
    assert unpinned.latest("intake") is None and unpinned.scan(policy.SOURCE_KIND) == []
    from ravel.controller.confine import ledger_evidence
    assert ledger_evidence.ledger_evidence(unpinned) == {}  # an identity without its source pin proves nothing


def test_a_refused_evidence_object_leaves_only_its_row_pending(real, monkeypatch):
    from ravel.controller.ledger import chain
    oversized = {"padding": "x" * (chain.MAX_EVIDENCE_BYTES + 1)}
    monkeypatch.setitem(graph.INTAKE_RECORDERS, "CT01",
                        ("P01", lambda store, context: {"record": context["intake"]["id"], **oversized}))
    store, observation = _drive(real)
    rows = {key.split("@", 1)[0]: instance for key, instance in _instances(store).items()}
    assert rows["CT01"].status == "pending" and rows["R01"].status == "satisfied"
    noted = [r["record"] for r in store.scan("ledger-evidence") if r["record"]["point"] == "controller.intake"][-1]
    assert "CT01" not in noted["recorded"] and "the ledger refused its evidence" in noted["pending"]["CT01"]
    assert _unmet(store, INTAKE) == ["CT01"] and store.latest("route") is None
    assert observation["terminal"]["status"] == "qualified"


# ---- the check-in rows: recorded from the verified authority record before the gate checks them ------------------

CHECKIN1 = "checkin1->execute"
# The authority's rows at CHECK-IN 1, recorded by the controller once the authority verifies the approval.
P06_CI1 = ("CHECKIN-1", "A01", "C05", "C07", "C15")
# The nodes whose rows the judgment graph and the governed step graph record when they plan and seat the steps.
PEER_NODES = ("judgment.frame", "judgment.decompose", "judgment.classify", "step.seat_derivation", "step.plan_bind")


def _mapped_plan():
    # The controller records the plan-bind rows when it binds the plan, so the step names its registered role.
    step = fakes.make_step("j1", kind="derive", outputs=["outputs/answer.json"], role="calculation")
    return fakes.judgment_plan(steps=[step], deliverables=[{"id": "D1", "status": "mapped", "step": "j1",
                                                            "output": "outputs/answer.json"}])


def _authority():
    """The real authority service; while it lacks its owner's canonical items, disposition and mechanism evidence,
    with the lane's stand-ins for exactly those helpers (``test_p01_graph._CanonicalItems``)."""
    from ravel.controller import authority
    from ravel.controller.authority import retained
    from test_p01_graph import _CanonicalItems
    return authority if hasattr(retained, "view_items") else _CanonicalItems(authority)


class _PeerRows:
    """Stand-ins for the peers this lane does not compose: the real judgment and governed step graphs, the route's
    check-in content rows and the confinement's input commitment. When the plan-review seat runs, it records what
    those peers record for an inert run (the plan-node rows, the seat's own attempt and the rows at CHECK-IN 1 owned
    by other packages), each citing a stand-in record of its own. It never records an authority (P06) row."""

    def __init__(self, monkeypatch):
        self.recorded = []
        real_step = fakes.step_run

        def step_run(store, step, context):
            if step["id"] == "plan_review" and not self.recorded:
                self.record(store, step)
            return real_step(store, step, context)
        monkeypatch.setattr(fakes, "step_run", step_run)

    def record(self, store, step):
        rows = ledger.load_catalogue().rows
        cite = store.append("peer-stand-in", {"purpose": "rows the composed peers record for an inert run"})
        evidence = {"record": cite, "credit": cite, "ack": cite, "mechanism": "test stand-in for an absent peer"}
        keys = list(ledger.materialise(store, "review", {
            "step": step["id"], "seat": step["role"], "role": step["role"], "attempt": 1, "seat_kind": "review",
            "review_kind": step["parameters"]["review_kind"], "step_kind": "review"}))
        for node in PEER_NODES:
            keys += ledger.pending(store, node=node)
        keys += [k for k in ledger.pending(store, node="authority.ci1") if rows[k.split("@", 1)[0]]["package"] != "P06"]
        assert not [k for k in keys if rows[k.split("@", 1)[0]]["package"] == "P06"]
        ledger.record_many(store, [(key, "satisfied", dict(evidence)) for key in dict.fromkeys(keys)])
        self.recorded = keys


class _Revoking:
    """The authority service; the operator revokes machine authority right after CHECK-IN 1 is decided."""

    def __init__(self, authority):
        self._authority = authority

    def __getattr__(self, name):
        return getattr(self._authority, name)

    def request(self, store, kind, subject, bounds):
        answer = self._authority.request(store, kind, subject, bounds)
        if kind == "approve_plan" and "pending" not in answer:
            import os
            from ravel.controller.authority import common, stop
            stop.record_control(store, "revoke", label=common.OPERATOR_COMMAND, source="operator_cli",
                                evidence={"operator_uid": os.getuid()}, reason="the operator withdraws delegation")
        return answer


class _Undisposed:
    """The authority service whose authenticated disposition refuses the final record (a raw body would pass)."""

    def __init__(self, authority):
        self._authority = authority

    def __getattr__(self, name):
        return getattr(self._authority, name)

    def disposition(self, store, record_id, *, kind, subject):
        from ravel.controller.authority import common
        raise common.AuthorityRefused(f"{kind} record {record_id} is not a current disposition (fixture)")


def test_checkin1_execute_gate_passes_after_a_verified_approval(real, monkeypatch, capfd):
    from ravel.controller import authority
    peers = _PeerRows(monkeypatch)
    fakes.PLANS.append(_mapped_plan())
    store, observation = _drive(real, authority=_authority())
    assert peers.recorded, "the run never reached its plan-review seat"
    assert ledger.gate(store, CHECKIN1) == []
    approval = [r for r in authority.records(store) if r["kind"] == "approve_plan"][-1]
    assert approval["decision"] == "approve" and approval["label"] == "operator_configured_machine"
    rows = {key.split("@", 1)[0]: instance for key, instance in _instances(store).items()}
    for row in P06_CI1:
        assert rows[row].status == "satisfied", (row, rows[row].status)
        assert rows[row].evidence["authority"] == approval["id"] and rows[row].evidence["provider"] == "P06"
        assert rows[row].evidence["mechanism"] == "authority.verify"
    # Recorded at the authority point, before the gate checked the transition, and the gate passed: its decision
    # gate, ledger transition and authority record. (The acting node's ``ledger.decide`` re-check composes the
    # decision gate's own providers; the wave-A gate proves that join.)
    noted = [r for r in store.scan("ledger-evidence") if r["record"]["point"] == "authority.ci1"]
    gate = [r for r in store.scan("gate") if r["record"]["gate"] == "approve_plan"][0]
    assert noted and noted[0]["seq"] < gate["seq"] and sorted(noted[0]["record"]["recorded"]) == sorted(P06_CI1)
    assert gate["record"]["passed"] is True and gate["record"]["errors"] == []
    # The authority's mechanism rows from its own evidence: the frozen mode record.
    for row in ("A02", "A03", "C09", "SW01", "SW02"):
        assert rows[row].status == "satisfied" and rows[row].evidence["authority"] == store.latest("mode")["id"]
    assert rows["CT07"].status == "pending"  # no terminal answer was given in this run

    # A revoked approval is not verified: CHECK-IN 1's rows stay unsatisfied and nothing executes.
    fakes.reset()
    peers.recorded = []
    fakes.PLANS.append(_mapped_plan())
    revoked, observation = _drive(real, "revoked", authority=_Revoking(_authority()))
    assert peers.recorded
    rows = {key.split("@", 1)[0]: instance for key, instance in _instances(revoked).items()}
    assert all(rows[row].status == "pending" for row in P06_CI1)
    assert set(P06_CI1) <= set(_unmet(revoked, CHECKIN1))
    revocation = [r for r in authority.records(revoked) if r["kind"] == "revoke"][-1]
    noted = [r["record"] for r in revoked.scan("ledger-evidence") if r["record"]["point"] == "authority.ci1"][0]
    assert noted["recorded"] == [] and "AuthorityRefused" in noted["pending"]["CHECKIN-1"]
    assert revocation["id"] in noted["pending"]["CHECKIN-1"]  # refused because of the operator's revocation
    gate = [r["record"] for r in revoked.scan("gate") if r["record"]["gate"] == "approve_plan"][0]
    assert gate["passed"] is False and {"obligation_unmet", "authority_refused"} <= {e["code"] for e in gate["errors"]}
    assert "j1" not in [step for step, _ in fakes.DISPATCHED] and observation["terminal"]["status"] == "qualified"

    # The final gate reads the final record through the authenticated disposition, never its raw body.
    fakes.reset()
    fakes.PLANS.append(_mapped_plan())
    final_store, observation = _drive(real, "final", ledger=fakes.FakeLedger(), sink=fakes.FakeSink(),
                                       authority=_authority())
    [pending] = entry._pending(observation)
    assert pending["payload"]["authority_kind"] == "final"
    code = re.findall(r"--code (\S+)", capfd.readouterr().err)[-1]
    renewed = authority.answer(final_store, pending["payload"]["pending"]["request"], code, "accept")
    assert renewed["label"] == "operator_command"  # R3 final authority is distinct from plan approval
    with graph.services(ledger=fakes.FakeLedger(), sink=fakes.FakeSink(), authority=_authority()):
        observation = entry.drive(final_store, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    assert observation["terminal"] is None  # delivered after an accepted, authenticated final disposition
    final = [r for r in authority.records(final_store) if r["kind"] == "final"][-1]
    values = fakes.final_state(final_store)
    with graph.services(ledger=fakes.FakeLedger(), authority=_authority()):
        pins = graph.checkin_view("checkin3", values, final_store)["pins"]
        helper = _authority()
        assert helper.disposition(final_store, final["id"], kind="final", subject=pins)["decision"] == "accept"
        changed = {**pins, "steps_sha256": "0" * 64}
        with pytest.raises(ValueError, match="stale"):
            helper.disposition(final_store, final["id"], kind="final", subject=changed)
        assert graph._authority_errors(final_store, values, "checkin3_gate", pins) == []
        assert [e["code"] for e in graph._authority_errors(final_store, values, "checkin3_gate", changed)] == [
            "authority_refused"]
    fakes.reset()
    fakes.PLANS.append(_mapped_plan())
    refused, observation = _drive(real, "undisposed", ledger=fakes.FakeLedger(), sink=fakes.FakeSink(),
                                  authority=_Undisposed(_authority()))
    [pending] = entry._pending(observation)
    code = re.findall(r"--code (\S+)", capfd.readouterr().err)[-1]
    authority.answer(refused, pending["payload"]["pending"]["request"], code, "accept")
    with graph.services(ledger=fakes.FakeLedger(), sink=fakes.FakeSink(), authority=_Undisposed(_authority())):
        observation = entry.drive(refused, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    assert observation["terminal"]["status"] == "qualified"
    final_gate = [r["record"] for r in refused.scan("gate") if r["record"]["gate"] == "final_task"][-1]
    assert final_gate["passed"] is False and final_gate["errors"][-1]["code"] == "authority_refused"
