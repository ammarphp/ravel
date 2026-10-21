"""P01: an answer typed at the controller's terminal never ends a run by itself (physicist-in-the-loop mode).

The authority service records a typed answer as unattested terminal evidence
(``terminal_operator_unattested``): it proves no identity and authorizes nothing. An authorizing
answer of that kind leaves the authority point pending: the run keeps waiting, its pause names the
operator-answer step (``ravel operator answer``), and only the operator's authenticated answer
(``operator_command``) lets CHECK-IN 1's gate pass. No record labelled as a physicist or a human
arises from terminal input (``physicist_terminal_response`` is unreachable on this platform).

The exchange at the terminal is real: as in the authority's own terminal tests, a helper process
opens a pseudo-terminal pair with ``pty.fork``; the child, whose controlling terminal is the
pseudo-terminal, asks the production authority service for the run's CHECK-IN 1 on the subject the
controller pinned, and the parent types the answer on the master side. The controller run itself is
driven by the test process, which has no controlling terminal.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest

import fakes
from ravel import cli
from ravel.controller import entry, graph

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals are POSIX")

HELPER = textwrap.dedent(r'''
    import json, os, pty, re, signal, sys, time
    config = json.load(open(sys.argv[1]))
    pid, master = pty.fork()
    if pid == 0:
        try:
            sys.path[:0] = config["paths"]
            from pathlib import Path
            from ravel.controller.authority import issuer, operator, service
            issuer.home = lambda: Path(config["issuer"])
            operator.controller_home = lambda: Path(config["operator"])
            from ravel.controller.store import RunStore
            store = RunStore(config["run_id"], root=config["store_root"])
            answer = service.request(store, "approve_plan", config["subject"], config["bounds"])
            pending = answer.get("pending") if type(answer.get("pending")) is dict else {}
            print("RESULT " + json.dumps({"id": answer.get("id"), "label": answer.get("label"),
                                          "decision": answer.get("decision"), "request": pending.get("request"),
                                          "unattested_record": answer.get("unattested_record")}), flush=True)
        except Exception as exc:
            print("RESULT " + json.dumps({"error": type(exc).__name__, "message": str(exc)}), flush=True)
        os._exit(0)
    seen = b""
    def read_until(pattern, limit=60.0):
        global seen
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            match = re.search(pattern, seen)
            if match:
                return match
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            seen += chunk
        return re.search(pattern, seen)
    prompt = read_until(rb"Reply on one line: (\S+) <decision>")
    code = prompt.group(1).decode() if prompt else None
    if code:
        os.write(master, (code + " " + config["typed"] + "\n").encode())
    else:  # never asked: stop the child instead of waiting on it
        os.kill(pid, signal.SIGKILL)
    match = read_until(rb"RESULT (\{.*\})\r?\n", 90)
    while True:  # drain the terminal until the child has written everything and exited
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        seen += chunk
    os.waitpid(pid, 0)
    print(json.dumps({"prompted": code is not None, "result": json.loads(match.group(1)) if match else None,
                      "transcript": seen.decode("utf-8", "replace")}))
''')
ANSWER_LINE = re.compile(r"--request (\S+) --code (\S+)")


@pytest.fixture
def interactive(tmp_path, monkeypatch):
    """A physicist-in-the-loop operator configuration in the test's lock domain; the test process itself has no
    controlling terminal (as a batch job or a worker), so a question it asks waits."""
    root = fakes.isolate(tmp_path, monkeypatch)
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator, terminal
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")

    def no_terminal(*args, **kwargs):
        raise terminal.TerminalUnavailable("the test process has no controlling terminal; nothing was asked")
    monkeypatch.setattr(terminal, "ask", no_terminal)
    operator.init(mode="physicist-in-the-loop", store_root=str(root))
    # This unit harness substitutes the governed step graph and decision gates;
    # it issues no RDJ credit. The real final seat is covered by test_composition_wave_a.
    from ravel.controller import authority
    monkeypatch.setattr(authority, "review_final_task", lambda *args: None)
    monkeypatch.setattr(authority, "review_deviation", lambda *args: None)  # the same RDJ seat seam
    with fakes.stand_in_graphs():
        yield {"tmp": tmp_path, "root": root}


def _authority():
    from ravel.controller import authority
    from ravel.controller.authority import retained
    from test_p01_graph import _CanonicalItems
    return authority if hasattr(retained, "view_items") else _CanonicalItems(authority)


def _terminal_answer(env, store, typed):
    """Ask the run's CHECK-IN 1 at a real pseudo-terminal and type ``typed``; the authority's answer."""
    import ravel
    from ravel.controller.authority import issuer, operator
    values = fakes.final_state(store)
    subject, _, _ = graph.authority_material("checkin1", values, store)
    config = {"paths": [str(Path(ravel.__file__).parents[1]), str(Path(__file__).parent)],
              "issuer": str(issuer.home()), "operator": str(operator.controller_home()), "run_id": store.run_id,
              "store_root": str(store.store_root), "subject": subject,
              "bounds": graph.authority_bounds("checkin1", values, store), "typed": typed}
    (env["tmp"] / "terminal.json").write_text(json.dumps(config))
    helper = env["tmp"] / "tty_helper.py"
    helper.write_text(HELPER)
    done = subprocess.run([sys.executable, str(helper), str(env["tmp"] / "terminal.json")], capture_output=True,
                          text=True, timeout=180, stdin=subprocess.DEVNULL, start_new_session=True,
                          env=os.environ.copy())
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["prompted"], out["transcript"][-2000:]
    return out


def test_an_approval_typed_at_the_terminal_waits_for_the_operators_answer(interactive, capsys):
    from ravel.controller import authority
    from ravel.controller.authority import issuer
    fakes.PLANS.append(fakes.judgment_plan(deliverables=[{"id": "D1", "status": "mapped", "step": "j1",
                                                           "output": "outputs/answer.json"}]))
    with fakes.installed(authority=_authority()):
        store, observation = fakes.drive_request(interactive["tmp"])
        # Without a terminal the check-in waits; the authority printed the operator-answer line with its code.
        assert [i["payload"]["authority_kind"] for i in observation["interrupts"]] == ["approve_plan"]
        codes = dict(ANSWER_LINE.findall(capsys.readouterr().err))
        # The physicist types "approve" at the controller's terminal.
        typed = _terminal_answer(interactive, store, "approve")
        codes.update(ANSWER_LINE.findall(typed["transcript"]))
        records = [r for r in authority.records(store) if r["kind"] == "approve_plan"]
        assert [r["label"] for r in records] == ["terminal_operator_unattested"]
        assert records[0]["decision"] == "approve" and records[0]["authorizes_effects"] is False
        # The resumed run does not take the typed answer as authority, and it does not end: it keeps waiting.
        observation = entry.drive(store, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
        assert observation["terminal"] is None, observation["terminal"]
        assert not store.scan("ending") and "j1" not in [s for s, _ in fakes.DISPATCHED]
        assert not [r for r in store.scan("gate") if r["record"]["gate"] == "approve_plan"]
        [paused] = observation["interrupts"]
        payload = paused["payload"]
        assert payload["authority_kind"] == "approve_plan" and payload["approval_from_resume"] is False
        assert payload["pending"]["unattested_record"] == records[0]["id"]
        hint = payload["operator_answer"]
        assert hint["terminal_identity_attested"] is False and "ravel operator" in hint["command"]
        assert hint["decision"] == "approve" and hint["unattested_record"] == records[0]["id"]
        request = hint["request"] if hint["request"] in codes else next(iter(codes))
        if hint["request"]:
            assert f"--request {hint['request']}" in hint["command"]
        # The operator answers the pending request with its code: an authenticated operator command.
        capsys.readouterr()
        assert cli.main(["operator", "answer", "--run", store.run_id, "--request", request, "--code", codes[request],
                         "--decision", "approve"]) == 0, capsys.readouterr().err
        observation = entry.drive(store, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    records = [r for r in authority.records(store) if r["kind"] == "approve_plan"]
    assert [r["label"] for r in records] == ["terminal_operator_unattested", "operator_command"]
    gate = [r["record"] for r in store.scan("gate") if r["record"]["gate"] == "approve_plan"]
    assert gate and gate[-1]["passed"] is True and "j1" in [s for s, _ in fakes.DISPATCHED]
    assert fakes.final_state(store)["authority"]["approve_plan"][-1] == records[-1]["id"]
    # No record claims a physicist's or a human's identity; the authority's account says the terminal is unattested.
    every = [r for r in authority.records(store)]
    assert not [r for r in every if r["label"] in ("physicist_terminal_response", "human_operator")]
    assert all(r["record"].get("human_identity_authenticated") is False for r in store.scan("authority"))
    assert issuer.receipt()["terminal_identity_attested"] is False
    sink = graph.service("sink")
    if getattr(sink, "installed", True) is not False and hasattr(sink, "receipt"):
        assert sink.receipt(store).get("terminal_identity_attested") is False
    # The run continued to its next check-in, where it waits again; it never ended on the typed answer.
    assert observation["terminal"] is None and [i["payload"]["authority_kind"] for i in observation["interrupts"]] == [
        "final"]


def test_a_refusal_typed_at_the_terminal_is_taken_as_it_restricts(interactive):
    from ravel.controller import authority
    fakes.PLANS.append(fakes.judgment_plan(deliverables=[{"id": "D1", "status": "mapped", "step": "j1",
                                                           "output": "outputs/answer.json"}]))
    with fakes.installed(authority=_authority()):
        store, observation = fakes.drive_request(interactive["tmp"])
        _terminal_answer(interactive, store, "reject")
        observation = entry.drive(store, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    records = [r for r in authority.records(store) if r["kind"] == "approve_plan"]
    assert [(r["label"], r["decision"]) for r in records] == [("terminal_operator_unattested", "reject")]
    # Unattested input may restrict: CHECK-IN 1 is not approved and nothing executes.
    assert "j1" not in [s for s, _ in fakes.DISPATCHED] and observation["terminal"]["status"] == "qualified"
