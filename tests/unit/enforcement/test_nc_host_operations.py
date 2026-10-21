"""Installed host actors and confined receipts, using inert preparation bytes only.

Only the child payload is fictional. Admission, confinement qualification, launch
observations, custody, ledger materialisation and final publication are installed APIs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import subprocess
import sys

import pytest

from nc_cases import CONTROLLER, dimension_case, dimension_rows, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register, returns

RAW = b'{"kind":"host-preparation","fixture_marker":"fictional-preparation-output"}'
PATH = 'preparation.json'
ARTIFACT = 'host:' + PATH


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _setup(nc, operation, scenario):
    host, custody, ledger, sink, services, confine = require_controller(
        'step.host_operations', 'step.custody', 'ledger', 'sink', 'step.services', 'confine')
    store, root = controller_run(nc, 'host-' + operation + '-' + scenario)
    actor = host.declaration(operation)['role']
    step = {'id': 'host', 'kind': 'operate', 'operation': operation, 'role': actor,
            'inputs': [], 'depends_on': [], 'outputs': [{'path': PATH, 'kind': 'artifact', 'required': True}],
            'parameters': {}, 'waypoint': False, 'rung': None, 'budget': {}, 'protocols': [],
            'review': [], 'instruction_sources': [], 'obligations': [], 'deliverables': ['preparation']}
    reading = {'deliverables': [{'id': 'preparation', 'claim_kind': None}], 'constraints': []}
    prompt = b'Produce fictional preparation bytes; this fixture makes no scientific claim.'
    request = store.put_blob(prompt)
    store.append('request', {'sha256': request, 'channel': 'terminal', 'bytes': len(prompt), 'unattended': False})
    store.append('intake', {'request_sha256': request, 'channel': 'terminal',
                           'contract_blob': store.put_blob(json.dumps({'task_mode': 'calculation',
                                                                    'prompt': prompt.decode()}).encode()),
                           'reading_blob': store.put_blob(json.dumps(reading).encode())})
    ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': 'calculation',
                                       'route': 'judgment', 'deliverables': ['preparation']})
    plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
            'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'parameters': {}, 'steps': [step],
            'deliverables': [{'id': 'preparation', 'status': 'mapped', 'step': 'host',
                              'output': PATH, 'claim_kind': None}],
            'waypoints': [], 'checkins': [], 'obligations': [], 'open_obligations': [], 'instruction_sources': []}
    plan['sha256'] = _sha(json.dumps(plan, sort_keys=True).encode())
    store.append('plan', {'plan_sha256': plan['sha256'],
                         'blob': store.put_blob(json.dumps(plan, sort_keys=True).encode()),
                         'source': 'compile', 'revision': 0, 'route': 'judgment'})
    ledger.materialise(store, 'plan', {'plan': plan, 'route': 'judgment', 'task_mode': 'calculation'})
    return {'store': store, 'root': root, 'step': step, 'plan': plan, 'host': host, 'custody': custody,
            'sink': sink, 'services': services, 'confine': confine,
            'counter': {'starts': 0, 'adopted': 0, 'published': 0}}


def _launch(h, *, completion=True, branch='launch', attempt=1):
    store, root, step = h['store'], h['root'], h['step']
    decision = h['host'].admit(store, step, attempt, branch=branch)
    output = root / 'outputs' / 'host'
    output.mkdir(parents=True)
    target = output / PATH
    script = 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))'
    spec = {'argv': [sys.executable, '-I', '-B', '-c', script, str(target), RAW.hex()],
            'env': {'PATH': '/usr/bin:/bin', 'LANG': 'C'}, 'reads': [], 'writes': [str(target)],
            'run_dir': str(root), 'stage': 'host', 'limits': {'wall_seconds': 120}, 'label': 'nc-host-preparation'}
    launch_sha = h['services'].digest(spec)
    started = store.append('step-launch', {'schema_version': 1, 'phase': 'started',
                                         'host_decision': decision, 'step_id': step['id'],
                                         'attempt': attempt, 'launch_sha256': launch_sha})
    process = h['confine'].popen(spec, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    h['counter']['starts'] += 1
    _, stderr = process.communicate(timeout=180)
    report = h['confine'].finish(process)
    assert process.returncode == 0, stderr
    assert target.read_bytes() == RAW
    actual_plan = deepcopy(process.ravel_confinement.record)
    backend = getattr(process, 'ravel_backend', None) or actual_plan.get('backend')
    inventory = [{'path': PATH, 'sha256': _sha(target.read_bytes()), 'bytes': target.stat().st_size}]
    if completion:
        store.append('step-launch', {'schema_version': 1, 'phase': 'finished', 'started': started,
                                    'step_id': step['id'], 'attempt': attempt, 'exit_status': process.returncode,
                                    'timed_out': False, 'inventory': inventory, 'backend': backend,
                                    'confinement': report, 'plan': actual_plan})
    return {'journal_id': started, 'launch_sha256': launch_sha, 'output_root': str(output),
            'inventory': inventory, 'exit_status': process.returncode, 'backend': backend}


def _adopt(h, launch):
    rows = h['custody'].launch_adoption(h['store'], run_dir=h['root'], step=h['step'], attempt=1,
        card={'id': h['step']['role'], 'ownership': {'owns': []}}, launch=launch,
        outputs=[{'path': PATH, 'plan_path': PATH, 'kind': 'artifact', 'required': True}], inputs_custody=[])
    h['counter']['adopted'] += len(rows)
    return rows


def _complete(h, rows):
    accepted = h['custody'].accept(h['store'], rows, 'accepted')
    assert len(accepted) == 1 and accepted[0]['status'] == 'accepted'
    h['custody'].record_outcome(h['store'], h['step'], 1, 'completed')
    assert h['custody'].outcomes(h['store'])['host']['status'] == 'completed'
    return accepted[0]


def _deliver(h):
    receipt = h['sink'].deliver(h['store'], h['plan'])
    assert receipt.get('id') and 'error' not in receipt, receipt
    directory = h['root'] / 'delivery'
    disk = json.loads((directory / 'RECEIPT.json').read_bytes())
    assert disk['sha256'] == receipt['sha256']
    assert (directory / 'DELIVERY.md').read_text()
    published = {row['artifact']: (directory / row['path']).read_bytes()
                 for row in receipt['delivery']['artifacts']}
    for row in receipt['delivery']['artifacts']:
        assert _sha(published[row['artifact']]) == row['sha256']
    h['counter']['published'] = len(published)
    return published


@dimension_case('HOST', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('HOST'))
def test_declared_host_actor_and_confined_receipt_control_custody_and_delivery(nc, row):
    operation = row.removeprefix('HOST-')
    # All forbidden actors/paths are checked before any process starts.
    for role, kind, branch, reason in (
            ('analysis-author', 'operate', 'launch', 'host_operation_role_mismatch'),
            ('physics-critic', 'operate', 'launch', 'host_operation_role_mismatch'),
            ('coordinator', 'derive', 'worker', 'host_operation_path_mismatch')):
        h = _setup(nc, operation, role + '-' + branch)
        h['step'].update(role=role, kind=kind)
        with pytest.raises(h['services'].StepHold) as held:
            _launch(h, branch=branch)
        assert held.value.reason == reason
        assert h['counter'] == {'starts': 0, 'adopted': 0, 'published': 0}

    # A real emitted output alone confers no custody without protected completion.
    h = _setup(nc, operation, 'missing-completion')
    launch = _launch(h, completion=False)
    with pytest.raises(h['services'].StepHold) as held:
        _adopt(h, launch)
    assert held.value.reason == 'host_operation_receipt_missing'
    assert not (h['root'] / 'steps' / 'host' / PATH).exists()
    assert ARTIFACT not in _deliver(h)
    assert h['counter'] == {'starts': 1, 'adopted': 0, 'published': 0}

    h = _setup(nc, operation, 'altered-observation')
    launch = _launch(h)
    launch['inventory'] = [dict(launch['inventory'][0], bytes=len(RAW) + 1)]
    with pytest.raises(h['services'].StepHold) as held:
        _adopt(h, launch)
    assert held.value.reason == 'host_operation_receipt_changed'
    assert not (h['root'] / 'steps' / 'host' / PATH).exists()
    assert ARTIFACT not in _deliver(h)
    assert h['counter'] == {'starts': 1, 'adopted': 0, 'published': 0}

    intact = _setup(nc, operation, 'intact')
    intact_record = _complete(intact, _adopt(intact, _launch(intact)))
    assert intact['host'].custody_errors(intact['store'], intact_record) == []
    assert _deliver(intact)[ARTIFACT] == RAW
    assert intact['counter'] == {'starts': 1, 'adopted': 1, 'published': 1}

    for damage in ('stripped', 'foreign', 'owner', 'no-current-step', 'no-current-blob'):
        h = _setup(nc, operation, damage)
        record = _complete(h, _adopt(h, _launch(h)))
        producer = deepcopy(record['producer'])
        if damage in ('stripped', 'no-current-step', 'no-current-blob'):
            producer = {}
        elif damage == 'foreign':
            producer.update(host_receipt=intact_record['producer']['host_receipt'],
                host_receipt_sha256=intact_record['producer']['host_receipt_sha256'])
        if damage == 'no-current-step':
            revised = dict(h['plan'], steps=[], revision=1)
            h['store'].append('plan', {'source': 'compile', 'plan_sha256': h['services'].digest(revised),
                'blob': h['store'].put_blob(json.dumps(revised).encode())})
        if damage == 'no-current-blob':
            h['store'].append('plan', {'source': 'compile', 'plan_sha256': 'f' * 64})
        changed = {k: deepcopy(v) for k, v in record.items() if k not in ('record_id', '_record_id')}
        changed['producer'] = producer
        if damage == 'owner':
            changed['owner_role'] = 'analysis-author'
        h['store'].append('custody', changed)
        # The pinned plan detects even a producer stripped of operation and receipt.
        consumer = {'id': 'consumer', 'depends_on': ['host'], 'inputs': [{'artifact': ARTIFACT}]}
        errors, found, _ = h['custody'].input_errors(h['store'], consumer, h['root'])
        assert errors and not found
        assert all(error['code'].startswith('host_operation_receipt_') for error in errors)
        assert ARTIFACT not in _deliver(h)
        assert h['counter'] == {'starts': 1, 'adopted': 1, 'published': 0}


_CATCH = ('test_declared_host_actor_and_confined_receipt_control_custody_and_delivery'
          '[HOST-ordinary-study-prepare]')
register(
    Mutation('M06', 'ravel.controller.step.host_operations:admission_errors', returns([]), (_CATCH,),
             binding=MUTATION_CONTROLLER, why='host operation actor and path checks are disabled'),
    Mutation('M09', 'ravel.controller.step.host_operations:receipt', returns(None), (_CATCH,),
             binding=MUTATION_CONTROLLER, why='host adoption accepts output without a protected receipt'),
    Mutation('M09', 'ravel.controller.step.host_operations:custody_errors', returns([]), (_CATCH,),
             binding=MUTATION_CONTROLLER, why='host receipts are not rechecked for consumption or delivery'))


@pytest.mark.parametrize('attempt', [1, 2])
def test_host_receipt_follows_the_logical_step_through_attempt_adoption(nc, attempt):
    graph = require_controller('step.graph')
    h = _setup(nc, 'ordinary-study-prepare', 'graph-attempt-' + str(attempt))
    launch = _launch(h, attempt=attempt)
    state = {'context': {'run_id': h['store'].run_id, 'run_dir': str(h['root']), 'attempt': attempt},
             'step': h['step'], 'acting': h['step'], 'branch': 'launch', 'launch': launch,
             'preflight': {'outputs': [{'path': PATH, 'plan_path': PATH, 'kind': 'artifact', 'required': True}]}}
    with h['services'].bound(h['store']):
        result = graph.adopt(state)
    assert result['adoption']['refused'] is None, result
    row, = result['adoption']['adopted']
    assert row['step_id'] == 'host' and row['attempt'] == attempt
    assert row['producer']['host_receipt'] == result['evaluations']['HOST-ordinary-study-prepare']['evidence']['record']
    assert (h['root'] / row['destination']).read_bytes() == RAW
    accepted, = h['custody'].accept(h['store'], [row], 'accepted')
    assert h['host'].custody_errors(h['store'], accepted) == []
    host_row = 'HOST-ordinary-study-prepare'
    with h['services'].bound(h['store']):
        graph.ledger_update(dict(state, evaluations={host_row: result['evaluations'][host_row]}))
    ledger = require_controller('ledger')
    discharged = [r for r in ledger.current(h['store'], step='host') if r['id'] == host_row]
    assert discharged and all(r['status'] == 'satisfied' for r in discharged), discharged


def test_omitted_actor_still_has_the_registered_host_identity_in_custody(nc):
    h = _setup(nc, 'ordinary-study-prepare', 'implicit-declared-actor')
    h['step']['role'] = None
    h['plan']['sha256'] = h['services'].digest(h['plan'])
    h['store'].append('plan', {'source': 'compile', 'plan_sha256': h['plan']['sha256'],
        'blob': h['store'].put_blob(json.dumps(h['plan']).encode())})
    record = _complete(h, _adopt(h, _launch(h)))
    assert record['owner_role'] == h['host'].declaration('ordinary-study-prepare')['role']
    assert record['producer']['host_role'] == record['owner_role']
    assert h['host'].custody_errors(h['store'], record) == []
