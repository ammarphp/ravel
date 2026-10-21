"""Credential metadata at the scheduler submission boundary, with inert helper and scheduler clients."""
import json
import os
from pathlib import Path

import pytest

from test_p06_support import autonomous, operator_home  # noqa: F401
from test_autonomy_needs import _store_with_dir
from ravel.controller.authority import AuthorityRefused, OPERATOR_COMMAND, autonomy, stop
from ravel.controller.routes.study import site
from ravel.workflow.site_profiles import htcondor


@pytest.fixture
def boundary(operator_home, tmp_path, monkeypatch):
    autonomous()
    store = _store_with_dir(tmp_path)
    workflow = Path(store.run_dir) / 'workflow'
    workflow.mkdir()
    script = workflow / 'job.sh'
    script.write_text('#!/bin/sh\n# properties = {"rule":"fictional","threads":1}\nexit 0\n')
    secret = tmp_path / 'private-proxy'
    secret.write_text('private-credential-sentinel')
    lifetime = tmp_path / 'lifetime'
    lifetime.write_text('0')
    tools = tmp_path / 'bin'
    tools.mkdir()
    helper = tools / 'voms-proxy-info'
    helper.write_text('#!/bin/sh\ncat "$TASK_PROXY_LIFETIME"\nexit "${TASK_PROXY_EXIT:-0}"\n')
    helper.chmod(0o700)
    monkeypatch.setenv('PATH', str(tools) + ':' + os.environ['PATH'])
    monkeypatch.setenv('TASK_PROXY_LIFETIME', str(lifetime))
    monkeypatch.setenv('TASK_PROXY_PATH', str(secret))
    calls = []
    monkeypatch.setattr(htcondor, '_submit_invoke', lambda *args: calls.append(args) or '31.0')
    profile = {'options': {'workflow_dir': str(workflow), 'x509userproxy_env': 'TASK_PROXY_PATH'}}

    def submit():
        with site.trusted_launch(store, 'operate', 'fictional-capability', {}):
            return htcondor.submit(script, profile=profile)
    return store, lifetime, calls, submit


def test_expiry_waits_once_and_requires_observed_renewal_and_operator_acknowledgment(boundary, monkeypatch):
    store, lifetime, calls, submit = boundary
    notifications = []
    from ravel.controller.authority import service
    monkeypatch.setattr(service, '_notify', lambda *args: notifications.append(args) or {'ok': True})
    for _ in range(2):
        with pytest.raises(AuthorityRefused, match='proxy_expired'):
            submit()
        assert autonomy.guard(store)[0] == 'wait'
    assert calls == [] and len(notifications) == 1
    stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={},
                        reason='credential checked')
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    assert autonomy.guard(store)[0] == 'wait' and len(notifications) == 1
    lifetime.write_text('3600')
    assert submit() == '31.0'
    assert len(calls) == 1 and autonomy.guard(store)[0] == 'go'
    records = store.scan(autonomy.CONDITION)
    assert [r['phase'] for r in records if r['code'] == 'proxy_expired'] == ['open', 'cleared']
    assert 'private-credential-sentinel' not in json.dumps(records)
    assert 'private-proxy' not in json.dumps(records)


def test_renewal_still_waits_for_operator_acknowledgment(boundary):
    store, lifetime, calls, submit = boundary
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    lifetime.write_text('3600')
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    assert calls == []
    stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={},
                        reason='credential renewed')
    assert submit() == '31.0' and len(calls) == 1


def test_expired_zero_metadata_survives_the_clients_failure_exit(boundary, monkeypatch):
    store, lifetime, calls, submit = boundary
    monkeypatch.setenv('TASK_PROXY_EXIT', '1')
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    assert calls == [] and autonomy.guard(store)[0] == 'wait'


def test_one_renewed_proxy_preserves_another_expired_condition(boundary, monkeypatch, tmp_path):
    store, lifetime, calls, submit = boundary
    first = os.environ['TASK_PROXY_PATH']
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    second = tmp_path / 'another-proxy'
    second.write_text('another-private-sentinel')
    monkeypatch.setenv('TASK_PROXY_PATH', str(second))
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={},
                        reason='credentials checked')
    lifetime.write_text('3600')
    monkeypatch.setenv('TASK_PROXY_PATH', first)
    with pytest.raises(AuthorityRefused, match='proxy_expired'):
        submit()
    assert calls == []
    remaining = autonomy.condition_findings(store)
    assert len(remaining) == 1 and remaining[0]['code'] == 'proxy_expired'


@pytest.mark.parametrize('text', ['unavailable', '', 'nan'])
def test_unknown_lifetime_refuses_with_a_distinct_status(boundary, text):
    store, lifetime, calls, submit = boundary
    lifetime.write_text(text)
    with pytest.raises(ValueError, match='credential_status_unknown'):
        submit()
    assert calls == [] and store.scan(autonomy.CONDITION) == []
