"""Capability-need row (CT09): every need a plan has is served by its best available tool, or a typed reason.

The adversary plans the hand-written analysis for a request whose analysis routine must be constructed while the
preferred construction tool is available on the host, and records no reason. The oracle reads the ledger's CT09
instance and the controller's ``tool-selection`` record; the positive controls plan the preferred tool, and plan the
hand-written analysis on a host whose profile shows the preferred tool missing.
"""
from __future__ import annotations

import json

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

PROMPT = b'Construct the particle-level analysis of the fictional search, which has no routine, and report its yields.'
PREFERRED = 'census-agentrivet-e4d12ecc'


def _profile(available):
    rows = {PREFERRED: {'readiness': 'ready' if available else 'missing', 'status': 'built_but_unqualified',
                        'version': None, 'licence': 'not_applicable', 'platform_qualification': ''}}
    return {'schema': 'ravel-environment-profile.v1', 'network': {'egress': 'unknown', 'source': 'not-probed',
                                                                 'checks': []},
            'tools': {'observed': True, 'source': 'doctor-census', 'prefix': None, 'reason': None, 'rows': rows},
            'sources': {'mirror': None}, 'site_profile': None, 'probe_errors': []}


def _step(step_id, **fields):
    return {'id': step_id, 'kind': 'author', 'inputs': [], 'depends_on': [],
            'outputs': [{'path': 'outputs/' + step_id + '.json', 'kind': 'document', 'required': True}],
            'parameters': {}, 'waypoint': False, 'rung': None, 'budget': {}, 'protocols': [], 'review': [],
            'instruction_sources': [], 'obligations': [], 'deliverables': ['yields'], **fields}


def _selected(nc, name, *, available, step):
    graph, ledger, routes = require_controller('graph', 'ledger', 'routes')
    store, root = controller_run(nc, name)
    request = store.put_blob(PROMPT)
    store.append('request', {'sha256': request, 'channel': 'terminal', 'bytes': len(PROMPT), 'unattended': False})
    reading = {'deliverables': [{'id': 'yields', 'claim_kind': None}], 'constraints': [], 'facts': []}
    contract = {'task_mode': 'no_routine', 'prompt': PROMPT.decode()}
    intake = store.append('intake', {'request_sha256': request, 'channel': 'terminal',
                                     'contract_blob': store.put_blob(json.dumps(contract).encode()),
                                     'reading_blob': store.put_blob(json.dumps(reading).encode()),
                                     'label': {'task_mode': 'no_routine', 'rule': 'D3'}})
    store.append('environment-profile', _profile(available))
    ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': 'no_routine', 'route': 'judgment',
                                       'deliverables': ['yields']})
    plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
            'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'parameters': {}, 'steps': [step],
            'deliverables': [{'id': 'yields', 'status': 'mapped', 'step': step['id'],
                              'output': step['outputs'][0]['path'], 'claim_kind': None}],
            'waypoints': [], 'checkins': [], 'obligations': [], 'open_obligations': [], 'instruction_sources': []}
    plan['sha256'] = routes.plan_sha256(plan)
    ledger.materialise(store, 'plan', {'plan': plan, 'route': 'judgment', 'task_mode': 'no_routine'})
    state = {'run': {'run_id': store.run_id, 'run_dir': str(root), 'store_root': str(store.store_root)},
             'request': {'sha256': request, 'intake_record_id': intake}}
    record_id = graph.record_tool_selection(state, store, plan)
    row = next(r for r in ledger.current(store, node='controller.plan') if r['id'] == 'CT09')
    return row, store.read('tool-selection', record_id)['record']


@case('CT09', binding=CONTROLLER)
def test_CT09_a_need_served_below_its_best_available_tool_without_a_reason_is_never_satisfied(nc):
    hand_written = _step('impl', kind='operate', operation='authored-analysis', role='analysis-author')
    row, record = _selected(nc, 'need-unserved', available=True, step=hand_written)
    assert row['status'] == 'violated', row
    assert record['passed'] is False and record['needs'][0]['best'] == PREFERRED
    assert 'AgentRivet' in row['evidence']['reason']
    # Positive control: the preferred construction tool serves the need.
    row, record = _selected(nc, 'need-best', available=True, step=_step('construct', role='routine-constructor'))
    assert row['status'] == 'satisfied' and record['passed'] is True
    assert row['evidence']['record'].startswith('tool-selection-')
    # Positive control: with the preferred tool missing, the hand-written analysis is the best available.
    row, record = _selected(nc, 'need-fallback', available=False, step=hand_written)
    assert row['status'] == 'satisfied', row
    skipped = {c['id']: c['reason'] for c in record['needs'][0]['candidates'] if c['state'] == 'unavailable'}
    assert skipped == {PREFERRED: 'not_installed'}


def _every_plan_passes(original):
    """The capability-need check accepts every plan."""
    def check(plan, **kwargs):
        record, _ = original(plan, **kwargs)
        for row in record['needs']:
            row['problems'] = []
        return {**record, 'problems': [], 'passed': True}, []
    return check


register(Mutation('M27', 'ravel.workflow.tool_selection:check', _every_plan_passes, ('CT09',),
                  binding=MUTATION_CONTROLLER, why='a plan that serves a need below its best available tool passes'))
