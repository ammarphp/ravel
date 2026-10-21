"""Confinement rows: a hostile authored script on a governed launch achieves nothing outside it.

Every case launches ``tests/fixtures/enforcement/scripts/hostile.py`` through ``confine.popen``
for a controller-owned run, with counters the script cannot reach: sentinel trees (the run's
store, protected copies, another workspace), a loopback listener, a stand-in model CLI that would
leave a call file, and canary values. The positive control is the script's declared output,
adopted by ``confine.finish``. Write targets are never real files of the installation: a
disabled sandbox must not be able to damage the tree it tests.
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest

from nc_cases import CONTROLLER, case
from nc_controller import HostileLaunch
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _without_linux_wrapper(original):
    """Drop only the hostile launch's OS argv wrapper; preserve its real confined Plan.

    Qualification probes keep their wrapper and the issuer's independent checks
    still execute. This is a Linux-wrapper mutation, never an unconfined grant.
    """
    def linux_argv(plan, env):
        if plan.record.get('label') == 'nc-hostile':
            return list(plan.argv)
        return original(plan, env)
    return linux_argv


def _adopted(launch, finished):
    assert launch.returncode == 0, launch.stderr
    assert finished['adopted'] == [] or str(launch.report) in finished['adopted']
    assert launch.report.is_file(), 'positive control: the declared output is written and kept'
    return launch.observed()


@case('SW34', binding=CONTROLLER)
def test_SW34_a_hostile_authored_script_cannot_write_custody_connect_read_credentials_or_start_a_model(nc):
    launch = HostileLaunch(nc)
    store = nc.effects.sentinels('store-view', {})
    journal_before = (launch.store.root / 'journal.jsonl').read_bytes()
    secret = nc.effects.canary('credential')
    credentials = nc.path('account', '.aws', 'credentials')
    credentials.write_text(f'[default]\naws_secret_access_key = {secret.value}\n')
    other = nc.effects.sentinels('other-workspace', {'outputs/result.json': '{"fictional": 1}'})
    cli = launch.fake_model_cli()
    launch_error, finished = None, None
    try:
        finished = launch.run([
            {'op': 'write', 'path': str(launch.store.root / 'journal.jsonl'), 'text': '{"forged": true}\n'},
            {'op': 'write', 'path': str(launch.store.root / 'authority-forged.json'), 'text': '{"approve": true}'},
            {'op': 'write', 'path': str(other.root / 'outputs/result.json'), 'text': '{"fictional": 2}'},
            {'op': 'read', 'path': str(credentials)},
            {'op': 'connect', 'port': nc.effects.listener.port},
            {'op': 'exec', 'argv': [str(cli), '-p', 'fictional request']},
        ])
    except Exception as exc:
        launch_error = exc
    # Read independent effects before touching the possibly attacked store or
    # re-raising a launch/finish failure. No exception is converted to an oracle.
    assert (launch.store.root / 'journal.jsonl').read_bytes().startswith(journal_before)
    assert not (launch.store.root / 'authority-forged.json').exists()
    assert other.changes() == [] and store.changes() == []
    assert nc.effects.listener.accepted == 0
    assert list(launch.calls.iterdir()) == []
    assert secret.found_in(launch.run_dir, launch.store.root) == []
    if launch_error is not None:
        raise launch_error
    observed = _adopted(launch, finished)
    assert [r['record']['event'] for r in launch.store.scan('confinement-launch')] == ['admitted', 'finished']
    assert launch.store.verify() == []
    assert [a['op'] for a in observed] == ['write', 'write', 'write', 'read', 'connect', 'exec']


register(Mutation('M08', 'ravel.controller.confine.launcher:linux_argv', _without_linux_wrapper, ('SW34', 'T04', 'CT03'),
                  binding=MUTATION_CONTROLLER, why='governed launches run without the OS sandbox'),
         Mutation('SW34', 'ravel.controller.confine.launcher:linux_argv', _without_linux_wrapper, ('SW34',),
                  binding=MUTATION_CONTROLLER, why='governed launches run without the OS sandbox'))


@case('T04', binding=CONTROLLER)
def test_T04_protected_cards_policy_and_inputs_cannot_be_rewritten_directly_or_through_a_link(nc):
    launch = HostileLaunch(nc)
    protected = nc.effects.sentinels('protected', {
        'roles/cards/fictional-role.json': json.dumps({'id': 'fictional-role', 'purpose': 'fictional'}),
        'agent_surface/execution_guard.json': json.dumps({'execution_guard': 'strict'}),
        'gates/providers.json': json.dumps({'providers': []})})
    approved = launch.inputs / 'approved-input.json'
    approved.write_text(json.dumps({'fictional': 'approved'}))
    approved_digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    finished = launch.run([
        {'op': 'write', 'path': str(protected.root / 'roles/cards/fictional-role.json'), 'text': '{"id": "x"}'},
        {'op': 'append', 'path': str(protected.root / 'agent_surface/execution_guard.json'), 'text': 'off'},
        {'op': 'write', 'path': str(approved), 'text': '{"fictional": "changed"}'},
        {'op': 'symlink_write', 'target': str(protected.root / 'gates/providers.json'),
         'link': str(launch.outputs / 'alias.json'), 'text': '{"providers": ["forged"]}'},
    ], reads=[protected.root], digests={str(approved): approved_digest})
    _adopted(launch, finished)
    assert protected.changes() == []
    assert hashlib.sha256(approved.read_bytes()).hexdigest() == approved_digest
    assert not (launch.outputs / 'alias.json').exists() or str(launch.outputs / 'alias.json') in finished['quarantined']


@case('CT03', binding=CONTROLLER)
def test_CT03_the_controller_store_is_outside_every_launch(nc):
    launch = HostileLaunch(nc)
    before = sorted(p.relative_to(launch.store.root).as_posix() for p in launch.store.root.rglob('*'))
    head = launch.store.head()
    finished = launch.run([
        {'op': 'listdir', 'path': str(launch.store.root)},
        {'op': 'read', 'path': str(launch.store.root / 'journal.jsonl')},
        {'op': 'write', 'path': str(launch.store.root / 'stop.json'), 'text': '{"cleared": true}'},
    ])
    observed = _adopted(launch, finished)
    assert sorted(p.relative_to(launch.store.root).as_posix() for p in launch.store.root.rglob('*')) == before
    assert launch.store.head()['seq'] == head['seq'] + 2 and launch.store.verify() == []
    assert [r['record']['event'] for r in launch.store.scan('confinement-launch')] == ['admitted', 'finished']
    assert not (launch.store.root / 'stop.json').exists()
    journal = (launch.store.root / 'journal.jsonl').read_text()
    assert [a for a in observed if a['op'] == 'read' and a['ok'] and journal[:64] in str(a['result'])] == []


@case('SW37', binding=CONTROLLER)
def test_SW37_credential_variables_of_the_controller_never_reach_a_launched_stage(nc):
    launch = HostileLaunch(nc)
    secret = nc.effects.canary('environment')
    nc.patch.setenv('AWS_SECRET_ACCESS_KEY', secret.value)
    nc.patch.setenv('ANTHROPIC_API_KEY', secret.value)
    nc.patch.setenv('NC_FICTIONAL_TOKEN', secret.value)
    finished = launch.run([{'op': 'env'}], env={'AWS_SECRET_ACCESS_KEY': secret.value,
                                                'GITHUB_TOKEN': secret.value})
    _adopted(launch, finished)
    assert secret.found_in(launch.run_dir) == []
    names = set(launch.record['environment_names'])
    assert not {'AWS_SECRET_ACCESS_KEY', 'GITHUB_TOKEN', 'ANTHROPIC_API_KEY', 'NC_FICTIONAL_TOKEN'} & names


CLOCKS = {'WORKFLOW_STATE_UTC': '2001-01-01T00:00:00Z', 'GATE_TIMESTAMP': '2001-01-01T00:00:00Z',
          'NC_FICTIONAL_UTC': '2001-01-01T00:00:00Z'}


@case('SW16', binding=CONTROLLER)
def test_SW16_clock_variables_neither_stamp_the_journal_nor_reach_a_launch(nc):
    for name, value in CLOCKS.items():
        nc.patch.setenv(name, value)
    launch = HostileLaunch(nc)
    before = time.time_ns()
    record_id = launch.store.append('nc-probe', {'fictional': True})
    stamped = launch.store.read('nc-probe', record_id)['time_ns']
    assert before <= stamped <= time.time_ns(), 'the journal uses the controller clock'
    finished = launch.run([{'op': 'env'}], env=dict(CLOCKS))
    observed = _adopted(launch, finished)
    seen = next(a['result'] for a in observed if a['op'] == 'env')
    assert not set(CLOCKS) & set(seen), sorted(set(CLOCKS) & set(seen))
    assert not set(CLOCKS) & set(launch.record['environment_names'])


@case('C24', binding=CONTROLLER)
def test_C24_a_withheld_or_undeclared_source_is_unreadable_from_any_module(nc):
    launch = HostileLaunch(nc)
    withheld_canary = nc.effects.canary('withheld')
    withheld = nc.path('sources', 'withheld', 'reference.json')
    withheld.write_text(json.dumps({'value': withheld_canary.value}))
    undeclared_canary = nc.effects.canary('undeclared')
    undeclared = nc.path('sources', 'undeclared.json')
    undeclared.write_text(json.dumps({'value': undeclared_canary.value}))
    finished = launch.run([{'op': 'read', 'path': str(withheld)}, {'op': 'read', 'path': str(undeclared)},
                           {'op': 'exec', 'argv': ['/bin/cat', str(withheld)]}],
                          withheld=[withheld.parent])
    _adopted(launch, finished)
    assert withheld_canary.found_in(launch.run_dir) == []
    assert undeclared_canary.found_in(launch.run_dir) == []


@case('C18', binding=CONTROLLER)
def test_C18_an_operation_reads_only_its_committed_inputs(nc):
    launch = HostileLaunch(nc)
    helper_canary = nc.effects.canary('helper')
    helper = nc.path('helpers', 'unlisted_helper.py')
    helper.write_text(f'VALUE = {helper_canary.value!r}\n')
    finished = launch.run([{'op': 'read', 'path': str(helper)},
                           {'op': 'exec', 'argv': ['/bin/cat', str(helper)]}])
    _adopted(launch, finished)
    assert helper_canary.found_in(launch.run_dir) == []
    # A committed input changed after approval refuses the launch before anything starts.
    committed = launch.inputs / 'helper.py'
    committed.write_text('VALUE = 1\n')
    digest = hashlib.sha256(committed.read_bytes()).hexdigest()
    committed.write_text('VALUE = 2\n')
    report = launch.report
    report.unlink()
    with pytest.raises(launch.confine.ConfinementRefused, match='changed after approval'):
        launch.run([{'op': 'read', 'path': str(committed)}], digests={str(committed): digest})
    assert not report.exists()


@case('T05', binding=CONTROLLER)
def test_T05_a_launch_cannot_open_a_socket_to_any_host(nc):
    launch = HostileLaunch(nc)
    finished = launch.run([{'op': 'connect', 'port': nc.effects.listener.port},
                           {'op': 'connect', 'host': '127.0.0.1', 'port': nc.effects.listener.port}])
    _adopted(launch, finished)
    assert nc.effects.listener.accepted == 0


@case('E16', binding=CONTROLLER)
def test_E16_offline_acquisition_cannot_fall_back_to_a_network_fetch(nc):
    launch = HostileLaunch(nc)
    cli = launch.fake_model_cli()  # any remote client: its start would leave a call file and connect
    finished = launch.run([{'op': 'exec', 'argv': [str(cli), 'fetch', 'fictional-member']},
                           {'op': 'connect', 'port': nc.effects.listener.port}])
    _adopted(launch, finished)
    assert nc.effects.listener.accepted == 0 and list(launch.calls.iterdir()) == []


register(Mutation('M24', 'ravel.controller.confine.launcher:linux_argv', _without_linux_wrapper, ('T05', 'E16'),
                  binding=MUTATION_CONTROLLER, why='a launch reaches the network'))


def _scrub_keeps_case_variables(original):
    """The scrub keeps every variable of a capsule carrying this suite's canaries or past clocks.

    Only the case's own launch is affected: the launcher's qualification probe keeps its scrub.
    """
    def scrub(capsule):
        env, removed = original(capsule)
        values = [str(v) for v in (capsule or {}).values()] if isinstance(capsule, dict) else []
        if any(v.startswith('nc-canary-') or v == '2001-01-01T00:00:00Z' for v in values):
            return {**env, **{k: v for k, v in capsule.items() if k not in env}}, []
        return env, removed
    return scrub


register(Mutation('SW37', 'ravel.controller.confine.environment:scrub', _scrub_keeps_case_variables, ('SW37',),
                  binding=MUTATION_CONTROLLER, why='credential variables pass the environment scrub'),
         Mutation('SW16', 'ravel.controller.confine.environment:scrub', _scrub_keeps_case_variables, ('SW16',),
                  binding=MUTATION_CONTROLLER, why='clock variables pass the environment scrub'))
