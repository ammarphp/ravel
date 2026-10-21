"""Shared CLI and worker joins proposed by the role-dispatch integration fragment."""
import json

import pytest

from ravel.workflow import agent_worker, broker, production_executor
from ravel.workflow.transports import generic_delegate, host_subagent
from test_cli_worker_adapter import cli, ready, real_sandbox_or_skip, spec as cli_spec  # noqa: F401
from test_role_dispatch import run, response, spec, tool


@pytest.mark.parametrize('entry', [production_executor.main, agent_worker.main])
def test_public_work_role_alias_uses_common_binding_parser(run, capsys, entry):
    s = spec()
    spec_path, subject_path = run / 'spec.json', run / 'subject.json'
    spec_path.write_text(json.dumps(s))
    subject_path.write_text(json.dumps(host_subagent.subject_for(s)))
    code = entry(['dispatch', '--rundir', str(run), '--node', s['node_id'], '--role', s['role']['id'],
                  '--spec', str(spec_path), '--subject', str(subject_path)])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result['status'] == 'refused'
    assert result['missing'] == ['delegate:unavailable']
    assert not result['required_role_satisfied']


def test_worker_dispatch_host_adapter_uses_common_interface_without_worker_credit(run):
    seen = []
    def invoke(arguments):
        seen.append(arguments)
        return response(arguments['request'])
    adapter = generic_delegate.DelegateAdapter(tool(), invoke)
    s = spec()
    result = agent_worker.dispatch(run, s, host_adapter=adapter, dispatch_mode='advisory',
                                   parent_session_id='fictional-parent')
    assert result['kind'] == 'role-dispatch-result' and result['status'] == 'advisory'
    assert len(seen) == 1 and not result['required_role_satisfied']
    assert result['worker_receipt'] is None
    with pytest.raises(ValueError, match='no receipt'):
        agent_worker.load_receipt(run, s['node_id'], s['attempt'])


def test_advisory_host_attempt_is_never_credited_by_a_later_cli_launch(cli):
    real_sandbox_or_skip(cli)
    ready(cli)
    run = cli / 'run'
    s = cli_spec(cli)
    s['transport_preference'] = ['claude-cli-worker', 'host-subagent-claude']
    def invoke(arguments):
        request = arguments['request']
        # The advisory child writes the declared output through its gated broker.
        reply = broker.socket_call(request['brief']['broker_socket'], {
            'call_id': 'advisory-write', 'action': 'write',
            'args': {'path': 'outputs/conformance.txt', 'content': 'n-0123456789'}})
        assert reply['status'] == 'ok', reply
        return response(request)
    adapter = generic_delegate.DelegateAdapter(tool(), invoke)
    advisory = agent_worker.dispatch(run, s, host_adapter=adapter, dispatch_mode='advisory',
                                     parent_session_id='fictional-parent')
    assert advisory['status'] == 'advisory'
    # A governed worker that writes nothing on the same attempt must not inherit that output.
    (cli / 'bin/mode.txt').write_text('skip_write')
    receipt = agent_worker.dispatch(run, s)
    assert receipt['status'] == 'refused' and receipt['credited_outputs'] == []
    assert receipt['failure']['missing'] == ['fresh_attempt']
    assert not (agent_worker.workspace(run, s['node_id'], s['attempt']) / 'scratch/seen.json').exists()


def test_host_window_attempt_never_starts_a_governed_worker(run, monkeypatch):
    from ravel.workflow import sandbox
    from ravel.workflow.transports import cli_worker
    monkeypatch.setattr(sandbox, 'available', lambda: 'fictional')
    monkeypatch.setattr(cli_worker, 'prepare_launch', lambda *a, **k: pytest.fail('launched on a host attempt'))
    s = spec()
    s['transport_preference'] = ['claude-cli-worker', 'host-subagent-claude']
    packet = host_subagent.brief(run, s, agent_worker.materialize(run, s), transport_id='host-subagent-claude')
    with host_subagent.serve_broker(run, s, packet):
        pass
    receipt = agent_worker.dispatch(run, s)
    assert receipt['status'] == 'refused' and receipt['failure']['code'] == 'host_attempt'
    assert receipt['credited_outputs'] == []
    # The host's own completion of that attempt keeps the refusal.
    assert host_subagent.complete(run, s, packet, final=response({})['final']) == receipt


def test_required_worker_host_seat_remains_held(run):
    adapter = generic_delegate.DelegateAdapter(tool(), lambda _: pytest.fail('called'))
    result = agent_worker.dispatch(run, spec(), host_adapter=adapter)
    assert result['status'] == 'refused' and not result['required_role_satisfied']
    assert 'independence:unproven' in result['missing']


def test_integrated_agent_surface_is_coherent():
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    checked = subprocess.run([sys.executable, str(root / 'scripts/run.py'),
                              'ravel.validation.check_agent_surface'], cwd=root,
                             capture_output=True, text=True, timeout=120)
    assert checked.returncode == 0, checked.stdout + checked.stderr
