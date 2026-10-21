"""Native absence helpers close only named rows with enforcing-record evidence."""
from copy import deepcopy

import pytest
from ravel.controller.confine.resource_mechanisms import ResourceMechanism

from ravel.controller.step import native_rows


PACKET = {'CF03', 'CF13', 'CT02', 'I01', 'I02', 'E29', 'ROLE-analysis-author-purpose',
          'ROLE-analysis-author-knowledge', 'ROLE-analysis-author-protocol-0'}
FOREIGN = {'P05', 'E01', 'E30', 'CF06', 'CF030', 'XCF03', 'ROLE-analysis-author-tools',
           'ROLE-analysis-author-sees', 'ROLE-analysis-author-dispatch', 'ROLE-analysis-author-stop',
           'ROLE-analysis-author-output', 'ROLE-analysis-author-model', 'ROLE-analysis-author-independence',
           'ROLE-analysis-author-guard-0', 'ROLE-analysis-author-protocol-0-extra',
           'XROLE-analysis-author-purpose'}
SCOPE = '@run-id/step=s1/seat=main/attempt=1'


@pytest.mark.parametrize('branch', ['launch', 'subgraph'])
def test_packet_exact_materialised_rows(branch):
    entries = [row + SCOPE for row in PACKET | FOREIGN]
    rows = native_rows.packet_rows(branch, entries, 'preflight-record')
    assert set(rows) == PACKET
    for value in rows.values():
        assert value == {'status': 'not_applicable', 'evidence': {
            'reason': f'not_applicable:{branch}_receives_no_agent_instruction_packet',
            'record': 'preflight-record'}}


def test_packet_does_not_invent_rows_or_close_worker_branch():
    assert native_rows.packet_rows('launch', [], 'record') == {}
    assert native_rows.packet_rows('launch', ['CF03' + SCOPE], 'record').keys() == {'CF03'}
    assert native_rows.packet_rows('worker', [row + SCOPE for row in PACKET], 'record') == {}


@pytest.mark.parametrize('record', [None, ''])
def test_missing_records_cannot_close_rows(record):
    assert native_rows.packet_rows('launch', list(PACKET), record) == {}
    assert native_rows.observation_rows({'journal_id': record}, {'kind': 'launch', 'equal': True},
                                        'settled', role='analysis-author') == {}
    assert native_rows.observation_rows(None, None, 'settled') == {}


def test_native_observation_exact_set_and_record():
    rows = native_rows.observation_rows({'journal_id': 'launch-record'},
                                        {'kind': 'launch', 'equal': True, 'differences': [], 'backend': 'sandbox'},
                                        'settled', role='analysis-author')
    assert set(rows) == {'CF06', 'I07', 'G13', 'E30', 'CT05', 'ROLE-analysis-author-model',
                         'ROLE-analysis-author-independence', 'ROLE-analysis-author-output'}
    assert all(value['evidence']['record'] == 'launch-record' for value in rows.values())
    assert rows['CT05']['status'] == 'satisfied'
    assert rows['CF06']['evidence']['reason'] == 'not_applicable:native_action_returns_no_worker_final_record'
    assert rows['I07'] == rows['CF06'] == rows['ROLE-analysis-author-output']
    assert rows['G13']['evidence']['reason'] == 'not_applicable:native_action_makes_no_broker_calls'
    assert rows['ROLE-analysis-author-model']['evidence']['reason'] == \
        'not_applicable:native_action_starts_no_model_session'
    assert rows['ROLE-analysis-author-model'] == rows['ROLE-analysis-author-independence']


@pytest.mark.parametrize('probe', [None, {}, {'kind': 'worker', 'equal': True}])
def test_missing_or_foreign_probe_leaves_inventory_pending(probe):
    rows = native_rows.observation_rows({'journal_id': 'record'}, probe, 'settled')
    assert 'CT05' not in rows
    assert not any(row.startswith('ROLE-') for row in rows)


@pytest.mark.parametrize('probe', [{'kind': 'launch', 'equal': False},
                                  {'kind': 'launch'},
                                  {'kind': 'launch', 'equal': 1},
                                  {'kind': 'launch', 'equal': True, 'differences': ['extra-tool']}])
def test_mismatched_probe_fails_closed(probe):
    rows = native_rows.observation_rows({'journal_id': 'record'}, probe, 'settled')
    assert rows['CT05'] == {'status': 'violated', 'evidence': {
        'record': 'record', 'reason': 'inventory_probe_mismatch'}}


def test_controller_acquisition_starts_no_child():
    rows = native_rows.observation_rows({'journal_id': 'record', 'backend': 'controller-acquisition'},
                                        None, 'released', role={'id': 'analysis-author'})
    assert rows['CT05'] == {'status': 'not_applicable', 'evidence': {
        'record': 'record', 'reason': 'not_applicable:trusted_controller_acquisition_starts_no_child'}}
    assert rows['E30']['evidence']['settlement'] == 'released'
    assert 'ROLE-analysis-author-output' in rows


@pytest.mark.parametrize('settlement', [None, 'ambiguous', 'failed', 'pending'])
def test_ambiguous_or_unknown_settlement_stays_pending(settlement):
    rows = native_rows.observation_rows({'journal_id': 'record'}, None, settlement)
    assert 'E30' not in rows
    assert set(rows) == {'CF06', 'I07', 'G13'}


def test_native_packet_preflight_replay_reuses_scoped_record(monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace
    graph = import_module('ravel.controller.step.graph')
    entry = 'CF03' + SCOPE
    current, calls = [], []
    def record(store, key, status, evidence):
        calls.append((key, status, evidence))
        current.append({'entry': key, 'status': status, 'evidence': evidence})
    ledger = SimpleNamespace(materialise=lambda *_: [entry], current=lambda *_: current, record=record)
    monkeypatch.setattr(graph, 'module', lambda name: ledger)
    monkeypatch.setattr(graph, '_store', lambda _: object())
    monkeypatch.setattr(graph, '_ledger_binding', lambda _: ('dispatch', {}, {}, {}))
    monkeypatch.setattr(graph, '_fact', lambda *_, **__: {'record': 'original-fact' if not calls else 'replay-fact'})
    monkeypatch.setattr(graph.spec, 'step_sha256', lambda _: 'step-sha')
    state = {'branch': 'launch', 'acting': {}, 'reservation': {'record_id': 'reservation'}}
    first = graph._native_instruction_absence(state)
    second = graph._native_instruction_absence(state)
    assert first == second and len(calls) == 1
    assert second[1]['CF03']['evidence']['record'] == 'original-fact'
    current[0]['status'] = 'violated'
    with pytest.raises(graph.StepHold, match='native_packet_absence_conflict'):
        graph._native_instruction_absence(state)


@pytest.fixture
def native_role_worker_subject():
    card = {'id': 'analysis-author', 'requires': {'packages': ['toy']},
            'tools': {'allow': ['read']}, 'stop': {'max_turns': 4},
            'operations': [{'id': 'toy-operation'}, {'id': 'toy-operation'}]}
    launch = {'journal_id': 'observed-launch-record', 'backend': 'native-test-backend',
              'exit_status': 0, 'timed_out': False}
    return card, launch


@pytest.mark.parametrize('operations', [[], [{'id': 'one'}], [{'id': 'same'}] * 3])
@pytest.mark.parametrize(('exit_status', 'timed_out'), [(0, False), (1, False), (-9, True)])
def test_role_worker_absence_exact_rows_preserve_effective_card_and_observed_launch(
        native_role_worker_subject, operations, exit_status, timed_out):
    card, launch = native_role_worker_subject
    card['operations'] = operations
    launch.update(exit_status=exit_status, timed_out=timed_out)
    before = deepcopy((card, launch))
    card_sha = 'aB' * 32
    rows = native_rows.role_worker_absence(card, launch, card_sha256=card_sha)
    expected = {'ROLE-analysis-author-' + field for field in ('dispatch', 'requires', 'tools', 'stop')}
    expected |= {'ROLE-analysis-author-operations-' + str(index) for index in range(len(operations))}
    expected.add('XF08')
    assert set(rows) == expected
    for row in rows.values():
        assert row == {'status': 'not_applicable', 'evidence': {
            'reason': 'not_applicable:native_action_starts_no_registered_role_worker',
            'record': launch['journal_id'], 'card_sha256': card_sha}}
    assert (card, launch) == before
    assert not (set(rows) & {'CF03', 'CF06', 'CT05', 'E01', 'E29', 'E30', 'G05', 'G13', 'P05',
                             'ROLE-analysis-author-model', 'ROLE-analysis-author-independence',
                             'ROLE-analysis-author-output', 'ROLE-analysis-author-purpose',
                             'check:validation.validate_cutflow', 'check:validation.certificates.validate_certificate'})


@pytest.mark.parametrize('field', ['id', 'requires', 'tools', 'stop', 'operations'])
def test_role_worker_absence_requires_every_effective_card_field(native_role_worker_subject, field):
    card, launch = native_role_worker_subject
    del card[field]
    assert native_rows.role_worker_absence(card, launch, card_sha256='a' * 64) == {}


@pytest.mark.parametrize(('field', 'value'), [
    ('id', ''), ('id', '  '), ('id', 1), ('id', None),
    ('requires', []), ('requires', None), ('tools', []), ('tools', None),
    ('stop', []), ('stop', None), ('operations', {}), ('operations', None), ('operations', ())])
def test_role_worker_absence_refuses_malformed_effective_card(native_role_worker_subject, field, value):
    card, launch = native_role_worker_subject
    card[field] = value
    assert native_rows.role_worker_absence(card, launch, card_sha256='a' * 64) == {}


@pytest.mark.parametrize('field', ['journal_id', 'backend', 'exit_status', 'timed_out'])
def test_role_worker_absence_needs_finished_observed_launch_fields(native_role_worker_subject, field):
    card, launch = native_role_worker_subject
    del launch[field]
    assert native_rows.role_worker_absence(card, launch, card_sha256='a' * 64) == {}


@pytest.mark.parametrize(('field', 'value'), [
    ('journal_id', ''), ('journal_id', '  '), ('journal_id', 1), ('journal_id', None),
    ('backend', ''), ('backend', '  '), ('backend', 1), ('backend', None),
    ('exit_status', None), ('exit_status', '0'), ('exit_status', 0.0), ('exit_status', True),
    ('timed_out', None), ('timed_out', 0), ('timed_out', 1), ('timed_out', 'false')])
def test_role_worker_absence_refuses_malformed_launch_source(native_role_worker_subject, field, value):
    card, launch = native_role_worker_subject
    launch[field] = value
    assert native_rows.role_worker_absence(card, launch, card_sha256='a' * 64) == {}


@pytest.mark.parametrize('digest', [None, '', 'a' * 63, 'a' * 65, 'g' * 64, 'a' * 63 + '\n', 1, True, {}])
def test_role_worker_absence_requires_actual_card_digest(native_role_worker_subject, digest):
    card, launch = native_role_worker_subject
    assert native_rows.role_worker_absence(card, launch, card_sha256=digest) == {}


@pytest.mark.parametrize('card', [None, 'analysis-author', [], True])
def test_role_worker_absence_refuses_absent_or_nondocument_card(native_role_worker_subject, card):
    _, launch = native_role_worker_subject
    assert native_rows.role_worker_absence(card, launch, card_sha256='a' * 64) == {}


@pytest.mark.parametrize('launch', [None, 'launch-record', [], True])
def test_role_worker_absence_refuses_absent_or_nondocument_launch(native_role_worker_subject, launch):
    card, _ = native_role_worker_subject
    assert native_rows.role_worker_absence(card, launch, card_sha256='a' * 64) == {}


@pytest.fixture
def confined_path_subject():
    return {'finished_id': 'finished-native-record', 'journal_id': 'started-native-record',
            'backend': 'bwrap', 'exit_status': 0, 'timed_out': False,
            'plan': {'kind': 'confined', 'network': 'none', 'backend': 'bwrap',
                     'limits': {'wall_seconds': 30, 'cpus': 1},
                     'limits_enforced': {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value, 'cpus': ResourceMechanism.LINUX_CPU_AFFINITY.value},
                     'custody_sha256': 'b' * 64}, 'confinement': {'errors': []}}


@pytest.mark.parametrize('cpu_enforcement', [ResourceMechanism.LINUX_CPU_AFFINITY.value, ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT.value])
@pytest.mark.parametrize('custody_pin', [True, False])
@pytest.mark.parametrize(('exit_status', 'timed_out'), [(0, False), (1, False), (-9, True)])
def test_path_absence_only_explicit_parser_alternate_entrypoint_and_remote_export_rows(
        confined_path_subject, cpu_enforcement, custody_pin, exit_status, timed_out):
    launch = confined_path_subject
    launch.update(exit_status=exit_status, timed_out=timed_out)
    launch['plan']['limits_enforced']['cpus'] = cpu_enforcement
    backend = 'sandbox-exec' if cpu_enforcement == ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT.value else 'bwrap'
    launch['backend'] = launch['plan']['backend'] = backend
    if not custody_pin:
        del launch['plan']['custody_sha256']
    before = deepcopy(launch)
    rows = native_rows.path_absence(launch)
    groups = {
        'native_capsule_invokes_no_host_shell_hook_parser': {'G10', 'G14', 'SW27'},
        'native_capsule_uses_no_alternate_unconfined_or_supervisor_entrypoint': {
            'SW17', 'SW34', 'SW35', 'SW36', 'SW37', 'SW38'},
        'local_capsule_submits_no_remote_job_or_procedure_export': {'SW24'}}
    assert set(rows) == set().union(*groups.values())
    evidence = {'record': launch['finished_id'], 'started': launch['journal_id'], 'backend': launch['backend']}
    if custody_pin:
        evidence['custody_sha256'] = launch['plan']['custody_sha256']
    for reason, identifiers in groups.items():
        for identifier in identifiers:
            assert rows[identifier] == {'status': 'not_applicable', 'evidence': {
                **evidence, 'reason': 'not_applicable:' + reason}}
    assert launch == before
    assert not (set(rows) & {'G04', 'SW08', 'G05', 'C24', 'T04', 'T09', 'CT05', 'E30',
                             'check:validation.validate_cutflow', 'check:validation.certificates.validate_certificate'})


@pytest.mark.parametrize('field', ['finished_id', 'journal_id', 'backend', 'exit_status', 'timed_out',
                                   'plan', 'confinement'])
def test_path_absence_needs_every_finished_launch_field(confined_path_subject, field):
    del confined_path_subject[field]
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize(('field', 'value'), [
    ('finished_id', ''), ('finished_id', ' '), ('finished_id', None), ('finished_id', 1),
    ('journal_id', ''), ('journal_id', ' '), ('journal_id', None), ('journal_id', 1),
    ('backend', ''), ('backend', ' '), ('backend', None), ('backend', 1), ('backend', 'different-backend'),
    ('exit_status', None), ('exit_status', '0'), ('exit_status', False), ('exit_status', 0.),
    ('timed_out', None), ('timed_out', 'false'), ('timed_out', 0),
    ('plan', None), ('plan', []), ('plan', True),
    ('confinement', None), ('confinement', []), ('confinement', True)])
def test_path_absence_refuses_malformed_finished_launch(confined_path_subject, field, value):
    confined_path_subject[field] = value
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize('field', ['kind', 'network', 'backend', 'limits', 'limits_enforced'])
def test_path_absence_needs_every_actual_confined_plan_field(confined_path_subject, field):
    del confined_path_subject['plan'][field]
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize(('field', 'value'), [
    ('kind', None), ('kind', 'unconfined'), ('kind', 'worker'),
    ('network', None), ('network', 'all'), ('network', {'tcp_ports': [443]}),
    ('backend', ''), ('backend', ' '), ('backend', None), ('backend', 1), ('backend', 'different-backend'),
    ('limits', None), ('limits', []), ('limits', {}),
    ('limits_enforced', None), ('limits_enforced', []), ('limits_enforced', {}), ('limits_enforced', True),
    ('limits_enforced', {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value}),
    ('limits_enforced', {'cpus': ResourceMechanism.LINUX_CPU_AFFINITY.value}),
    ('limits_enforced', {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value, 'cpus': False}),
    ('limits_enforced', {'wall_seconds': True, 'cpus': ResourceMechanism.LINUX_CPU_AFFINITY.value}),
    ('limits_enforced', {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value, 'cpus': ''}),
    ('limits_enforced', {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value, 'cpus': 'unverified'}),
    ('limits_enforced', {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value, 'cpus': ResourceMechanism.LINUX_CPU_AFFINITY.value, 'extra': 'claimed'})])
def test_path_absence_refuses_wrong_plan_or_enforcement_mapping(confined_path_subject, field, value):
    confined_path_subject['plan'][field] = value
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize('field', ['wall_seconds', 'cpus'])
def test_path_absence_refuses_enforcement_without_corresponding_limit(confined_path_subject, field):
    del confined_path_subject['plan']['limits'][field]
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize('errors', [None, '', False, {}, ['surviving process'], ['unexpected output']])
def test_path_absence_requires_explicit_empty_confinement_errors(confined_path_subject, errors):
    confined_path_subject['confinement']['errors'] = errors
    assert native_rows.path_absence(confined_path_subject) == {}


def test_path_absence_refuses_missing_confinement_error_observation(confined_path_subject):
    del confined_path_subject['confinement']['errors']
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize('pin', [None, '', 'a' * 63, 'a' * 65, 'g' * 64, True])
def test_path_absence_refuses_malformed_optional_custody_pin(confined_path_subject, pin):
    confined_path_subject['plan']['custody_sha256'] = pin
    assert native_rows.path_absence(confined_path_subject) == {}


@pytest.mark.parametrize('launch', [None, [], True, 'launch-record'])
def test_path_absence_requires_actual_launch_document(launch):
    assert native_rows.path_absence(launch) == {}


def test_path_absence_allows_actual_memory_enforcement_but_refuses_unenforced_extra_limits(confined_path_subject):
    plan = confined_path_subject['plan']
    plan['limits']['memory_mib'] = 128
    plan['limits_enforced']['memory_mib'] = ResourceMechanism.LINUX_RLIMIT_AS.value
    assert len(native_rows.path_absence(confined_path_subject)) == 10
    plan['limits']['processes'] = 4
    plan['limits_enforced']['processes'] = False
    assert native_rows.path_absence(confined_path_subject) == {}
    plan['limits_enforced']['processes'] = 'invented enforcement'
    assert native_rows.path_absence(confined_path_subject) == {}


def test_native_role_absence_covers_materialised_effective_projection_instances(native_role_worker_subject):
    card,launch=native_role_worker_subject
    entries=['ROLE-analysis-author-operations-31@scope', 'ROLE-analysis-author-operations-31@scope',
             'ROLE-analysis-author-operations-extra@scope', 'ROLE-other-operations-31@scope',
             'ROLE-analysis-author-must_check-31@scope', 'GATE-launch@scope']
    rows=native_rows.role_worker_absence(card,launch,card_sha256='a'*64,entries=entries)
    assert 'ROLE-analysis-author-operations-31' in rows
    assert rows['ROLE-analysis-author-operations-31']['evidence']['record']==launch['journal_id']
    assert set(rows)-{'ROLE-analysis-author-operations-31'}==set(
        native_rows.role_worker_absence(card,launch,card_sha256='a'*64))
