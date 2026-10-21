"""The sink against the real run store, obligation ledger and authority service (skipped until they are installed).

The package tests use fakes that keep the peers' published rules; this file checks the same calls against
the real packages: every row status and evidence the sink records passes the ledger's own checks, the
delivery decisions come back as structured gate errors, the bounded ending discharges its rows and lists
public pending obligations and complete summary counts. A delivery here is not expected to be accepted: no
controller graph ran, so other nodes' obligations stay pending, and the sink must say so.
"""
from __future__ import annotations

import json
import sys

import pytest

ledger = pytest.importorskip('ravel.controller.ledger')
store_module = pytest.importorskip('ravel.controller.store')
authority = pytest.importorskip('ravel.controller.authority')
if not hasattr(ledger, 'load_catalogue') or not hasattr(store_module, 'RunStore'):
    pytest.skip('the controller ledger and store are not the integrated packages', allow_module_level=True)

from ravel.controller import sink  # noqa: E402
from p07_support import PROMPT, READING, REPORT, VALUE, FakeConfine, module_of, sha  # noqa: E402

RUN_ID = 'run-p07-peer-' + __import__('secrets').token_hex(4)


class RealRun:
    """A fictional run on the real store and ledger, with the records the controller's nodes write."""

    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, 'ravel.controller.confine', module_of(
            'ravel.controller.confine', FakeConfine(), ('code_identity', 'require_governed_install')))
        for absent in ('ravel.controller.step.budget', 'ravel.controller.routes.analysis.fidelity',
                       'ravel.controller.routes.manuscript'):
            monkeypatch.setitem(sys.modules, absent, None)
        # The operator-configured store root (the test's own lock domain): the root production resolves.
        self.store = store_module.RunStore.create(tmp_path / 'runs' / RUN_ID, run_id=RUN_ID)
        self.dir = self.store.run_dir
        request = self.store.put_blob(PROMPT.encode())
        self.store.append('request', {'sha256': request, 'channel': 'terminal', 'bytes': len(PROMPT),
                                      'unattended': False})
        contract = {'task_mode': 'calculation', 'prompt': PROMPT}
        self.store.append('intake', {'request_sha256': request, 'channel': 'terminal',
                                     'contract_blob': self.store.put_blob(json.dumps(contract).encode()),
                                     'reading_blob': self.store.put_blob(json.dumps(READING).encode())})
        self.store.append('mode', {'schema': 'operating-mode.v1', 'schema_version': 1, 'uid': 'mode-1',
                                   'run_id': RUN_ID, 'mode': 'autonomous', 'delegation': 'operator_configured',
                                   'operator_source': 'operator_ledger', 'allow_unconfined': False,
                                   'budgets': {}, 'bounds': {}, 'notify_command': None})
        ledger.materialise(self.store, 'intake', {'run_id': RUN_ID, 'task_mode': 'calculation', 'route': 'judgment',
                                                  'deliverables': [d['id'] for d in READING['deliverables']]})
        steps = [self.step('s1', ['outputs/value.json'], ['d-value']),
                 self.step('s2', ['outputs/report.md'], ['d-report'], depends=['s1'])]
        plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
                'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'parameters': {}, 'steps': steps,
                'deliverables': [{'id': 'd-value', 'status': 'mapped', 'step': 's1', 'output': 'outputs/value.json'},
                                 {'id': 'd-report', 'status': 'mapped', 'step': 's2', 'output': 'outputs/report.md'}],
                'waypoints': [], 'checkins': [], 'obligations': [], 'open_obligations': [], 'instruction_sources': []}
        plan['sha256'] = sha(json.dumps(plan, sort_keys=True).encode())
        blob = self.store.put_blob(json.dumps(plan, sort_keys=True).encode())
        self.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'source': 'compile', 'revision': 0,
                                   'route': 'judgment'})
        ledger.materialise(self.store, 'plan', {'plan': plan, 'route': 'judgment', 'task_mode': 'calculation'})
        self.plan = plan

    @staticmethod
    def step(step_id, outputs, deliverables, depends=()):
        return {'id': step_id, 'kind': 'operate', 'inputs': [], 'depends_on': list(depends),
                'outputs': [{'path': p, 'kind': 'artifact', 'required': True} for p in outputs], 'waypoint': False,
                'rung': None, 'budget': {}, 'protocols': [], 'review': [], 'instruction_sources': [],
                'obligations': [], 'deliverables': list(deliverables)}

    def adopt(self, step_id, path, raw):
        destination = f'steps/{step_id}/{path}'
        target = self.dir / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        started = self.store.append('step-launch', {'schema_version': 1, 'phase': 'started', 'step_id': step_id,
                                                    'attempt': 1, 'launch_sha256': 'a' * 64})
        self.store.append('step-launch', {'schema_version': 1, 'phase': 'finished', 'started': started,
                                          'step_id': step_id, 'attempt': 1, 'exit_status': 0, 'backend': 'linux',
                                          'confinement': {'errors': []}, 'plan': {'backend': 'linux'}})
        record = {'schema_version': 1, 'artifact': f'{step_id}:{path}', 'step_id': step_id, 'attempt': 1,
                  'path': path, 'destination': destination, 'sha256': sha(raw), 'kind': 'artifact',
                  'producer': {'kind': 'launch', 'journal_id': started, 'exit_status': 0}, 'inputs': [],
                  'status': 'staged'}
        self.store.append('custody', record)
        self.store.append('custody', {**record, 'status': 'accepted'})
        self.store.append('step-outcome', {'schema_version': 1, 'step_id': step_id, 'attempt': 1,
                                           'status': 'completed'})

    def instances(self):
        from ravel.controller.ledger import state
        folded = state.load(self.store, full=True)
        return {k: folded.instances[k] for k in folded.current_keys()}


def test_every_status_the_sink_records_passes_the_real_ledger(tmp_path, monkeypatch):
    run = RealRun(tmp_path, monkeypatch)
    run.adopt('s1', 'outputs/value.json', json.dumps(VALUE).encode())
    run.adopt('s2', 'outputs/report.md', REPORT.encode())
    receipt = sink.deliver(run.store, run.plan)
    codes = {r['code'] for r in receipt['work']['current_refusals']}
    assert not codes & {'ledger_record', 'ledger_materialise', 'ledger_absent'}, receipt['work']['current_refusals']
    assert receipt['label'] != 'accepted' and receipt['architecture_complete'] is False
    deliver_rows = {(i.id, i.scope.get('artifact')): i for i in run.instances().values() if i.stage == 'deliver'}
    assert deliver_rows, 'the deliver stage was materialised'
    recorded = [(row, scope) for (row, scope), i in deliver_rows.items() if i.status != 'pending']
    assert len(recorded) >= len(deliver_rows) - 6, sorted(k for k, i in deliver_rows.items() if i.status == 'pending')
    for gate in ('delivery', 'final_task', 'report_integrity'):
        for error in receipt['ledger']['decisions'][gate]['errors']:
            assert set(error) == {'code', 'provider', 'message'}
    assert receipt['ledger']['unmet'] and all('consequence' in row for row in receipt['ledger']['unmet'])
    assert receipt['ledger']['chain_verified'] is True and receipt['ledger']['by_status']


def test_the_bounded_ending_discharges_its_rows_in_the_real_ledger(tmp_path, monkeypatch):
    run = RealRun(tmp_path, monkeypatch)
    run.adopt('s1', 'outputs/value.json', json.dumps(VALUE).encode())
    receipt = sink.bounded_end(run.store, 'budget exhausted: fictional tokens')
    assert receipt['qualified'] and not receipt['accepted'] and receipt['id']
    rows = {i.id: i.status for i in run.instances().values() if i.id in ('B03', 'JR10')}
    assert rows == {'B03': 'satisfied', 'JR10': 'satisfied'}
    ending = json.loads((run.dir / 'delivery' / 'qualified-delivery.json').read_text())
    assert ending['ledger_listing_error'] is None
    assert sorted(row['key'] for row in ending['ledger_obligations'] if row['status'] == 'pending') == \
        sorted(ledger.pending(run.store))
    assert ending['ledger_counts'] == ledger.summary(run.store)['by_status']
    assert {o['id']: o['state'] for o in ending['obligations']} == {'d-value': 'satisfied', 'd-report': 'blocked'}


def test_legacy_writers_refuse_a_real_controller_run(tmp_path, monkeypatch):
    run = RealRun(tmp_path, monkeypatch)
    assert sink.owner(run.dir) == RUN_ID and sink.owner(run.dir / 'steps') == RUN_ID
    from ravel.workflow import architecture_receipt
    with pytest.raises(sink.SinkRefused):
        architecture_receipt.label_delivery(run.dir, [])
    observed = architecture_receipt.build_receipt(run.dir)
    assert observed['run_id'] == RUN_ID and observed['delivery']['status'] == 'not delivered'
