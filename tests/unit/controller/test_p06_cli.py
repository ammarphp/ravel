"""P06: ``ravel operator`` writes and shows the operator ledger and answers escalations by code."""
from __future__ import annotations

import json
import re

from test_p06_support import frozen_store, operator_home, view  # noqa: F401
from ravel.controller.authority import OPERATOR_COMMAND, cli, common, request


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if code == 0 else captured.err)


def test_init_show_set_through_the_cli(operator_home, capsys, tmp_path):
    code, written = run(capsys, 'init', '--mode', 'autonomous', '--budget', 'events=2000', '--budget', 'cost_usd=null',
                        '--rungs', 'dry,smoke,full', '--r3-policy', 'conservative_default', '--wait-bound', '120',
                        '--notify-command', '["/usr/bin/true"]', '--store-root', str(tmp_path / 'runs'))
    assert code == 0 and written['source'] == 'operator_ledger'
    assert written['budgets']['events'] == 2000 and written['budgets']['cost_usd'] is None
    assert written['bounds']['rungs'] == ['dry', 'smoke', 'full'] and written['wait_bound_seconds'] == 120
    assert written['notify_command'] == ['/usr/bin/true'] and written['store_root'] == str(tmp_path / 'runs')
    code, shown = run(capsys, 'show')
    assert code == 0 and shown == written
    code, changed = run(capsys, 'set', '--allow-request-delegation', 'true', '--budget', 'tokens=7')
    assert code == 0 and changed['allow_request_delegation'] is True and changed['budgets']['tokens'] == 7
    assert run(capsys, 'init', '--mode', 'autonomous')[0] == 2
    assert run(capsys, 'set', '--budget', 'events')[0] == 2
    assert run(capsys, 'set', '--notify-command', 'not json')[0] == 2


def test_answer_through_the_cli_quotes_the_request_code(operator_home, capsys, tmp_path, monkeypatch):
    assert cli.main(['init', '--mode', 'autonomous']) == 0
    capsys.readouterr()
    store = frozen_store(tmp_path)
    monkeypatch.setattr(common, 'open_store', lambda identifier: store)
    held = request(store, 'escalation', {'view': view(store, 'escalation', question_sha256='5' * 64)}, {})
    line = capsys.readouterr().err
    assert 'WAITING FOR A HUMAN since' in line
    code = re.search(r'--code (\S+)', line).group(1)
    request_id = held['pending']['request']
    # The operator reads what is asked in the status, never in the notification.
    ok, status = run(capsys, 'status', '--run', store.run_id)
    shown = status['pending'][0]
    assert ok == 0 and shown['request'] == request_id and shown['answerable'] is True
    assert 'ESCALATION' in shown['text'] and 'Which binning should be used?' in shown['text']
    assert [o['id'] for o in shown['options']] == ['hold', 'proceed'] and status['deviations'] == []
    failed, message = run(capsys, 'answer', '--run', store.run_id, '--request', request_id, '--code', 'NOPE-NOPE',
                          '--decision', 'hold')
    assert failed == 2 and 'does not quote the code' in message
    ok, result = run(capsys, 'answer', '--run', store.run_id, '--request', request_id, '--code', code.lower(),
                     '--decision', 'hold', '--text', 'Use the coarse binning.')
    assert ok == 0 and result['label'] == OPERATOR_COMMAND and result['option'] == 'hold'
    assert request(store, 'escalation', {'view': view(store, 'escalation', question_sha256='5' * 64)}, {})['id'] == result['record']


def test_open_store_passes_the_configured_store_root_to_the_binding_store(operator_home, tmp_path, monkeypatch):
    """P01's ``RunStore(run_id, root=...)`` takes the store root and keeps the run at ``root/run_id``.

    Passing the run's own directory would open an empty nested store: an operator stop or
    answer would then be recorded where the run never reads it.
    """
    import sys
    import types
    from pathlib import Path
    from ravel.controller.authority import operator

    class BindingStore:
        def __init__(self, run_id, *, root=None):
            self.run_id, self.root = run_id, Path(root) / run_id

    module = types.ModuleType('ravel.controller.store')
    module.RunStore = BindingStore
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', module)
    root = tmp_path / 'runs'
    (root / 'run-0001').mkdir(parents=True)
    operator.init(mode='autonomous', store_root=str(root))
    assert common.open_store('run-0001').root == root / 'run-0001'


def test_run_controls_refuse_cleanly_for_an_unknown_run(operator_home, capsys):
    assert cli.main(['init', '--mode', 'physicist-in-the-loop']) == 0
    capsys.readouterr()
    code = cli.main(['stop', '--run', 'no-such-run', '--reason', 'operator stop'])
    assert code == 2 and 'no controller run' in capsys.readouterr().err
    code = cli.main(['stop', '--run', '../escape', '--reason', 'operator stop'])
    assert code == 2 and 'plain name' in capsys.readouterr().err


def test_cli_round_trips_consumer_settings(operator_home, capsys):
    code, config = run(capsys, 'init', '--mode', 'autonomous')
    assert code == 0
    expected = {'harness': None, 'engagement': {'minimum_tier': None}, 'restricted_sources': None,
                'remote_job_ceiling': 0, 'procedure_byte_ceiling': 1048576,
                'agent_preferences': None, 'site_resource_ceilings': None}
    assert {k: config[k] for k in expected} == expected
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': ['toy-worker']}
    code, changed = run(capsys, 'set', '--harness', '{"channel":"trusted"}',
                        '--engagement', '{"minimum_tier":"full"}', '--restricted-sources', '/operator/policy.json',
                        '--remote-job-ceiling', '2', '--procedure-byte-ceiling', '2048',
                        '--agent-preferences', json.dumps(preferences), '--site-resource-ceilings', '{"cpus":2}')
    assert code == 0 and changed['remote_job_ceiling'] == 2 and changed['procedure_byte_ceiling'] == 2048
    assert changed['harness'] == {'channel': 'trusted'} and changed['restricted_sources'] == '/operator/policy.json'
    assert changed['engagement'] == {'minimum_tier': 'full'} and changed['agent_preferences'] == preferences
    assert changed['site_resource_ceilings'] == {'cpus': 2}
    assert run(capsys, 'show') == (0, changed)
    assert run(capsys, 'set', '--harness', 'null')[1]['harness'] is None
