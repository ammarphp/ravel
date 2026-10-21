"""Governed-step rows: custody, card fields, escalation and the controller's own validators.

The adversary feeds an unreceipted or altered predecessor into a step, dispatches before a parent
completed, sets a quantity its role does not own, drops a declared output, returns an undeclared
or missing escalation, satisfies a hard-coded schema instead of its card's, or skips a reviewer's
self-check. Oracles are the step graph's own checks over the controller store; positive controls
pass the same checks with the governed values.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _card(role):
    from ravel.workflow import role_registry
    return role_registry.load(role)


def _step(step_id, *, depends_on=(), inputs=(), outputs=(('outputs/result.json', 'result'),), quantities=None,
          kind='derive'):
    step = {'id': step_id, 'kind': kind, 'depends_on': list(depends_on),
            'inputs': [dict(row) for row in inputs],
            'outputs': [{'path': path, 'kind': k, 'required': True} for path, k in outputs],
            'parameters': {'quantities': dict(quantities or {})}}
    return step


def _adopted(nc, store, run_dir, step, files, *, card_role='calculation'):
    """The controller's adoption of a confined launch's declared outputs, then its acceptance."""
    custody = require_controller('step.custody')
    root = nc.root / 'launch-output' / step['id']
    inventory = []
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        inventory.append({'path': path, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    rows = [{'plan_path': p, 'path': p, 'kind': 'result', 'required': True} for p in files]
    staged = custody.launch_adoption(store, run_dir=run_dir, step=step, attempt=1, card=_card(card_role),
                                     launch={'output_root': str(root), 'inventory': inventory, 'journal_id': 'nc-j1',
                                             'exit_status': 0, 'launch_sha256': 'f' * 64, 'backend': 'fictional'},
                                     outputs=rows, inputs_custody=[])
    return custody.accept(store, staged, 'accepted', evidence={'validators': 'fictional pass'})


@case('T07', binding=CONTROLLER)
def test_T07_an_unreceipted_or_altered_predecessor_is_never_laundered_through_a_governed_step(nc):
    custody = require_controller('step.custody')
    store, run_dir = controller_run(nc)
    producer = _step('s01')
    accepted = _adopted(nc, store, run_dir, producer, {'outputs/result.json': '{"value": 1}'})
    artifact = accepted[0]['artifact']
    consumer = _step('s02', depends_on=['s01'], inputs=[{'artifact': artifact}])
    errors, found, _ = custody.input_errors(store, consumer, run_dir)
    assert errors == [] and [r['artifact'] for r in found] == [artifact]  # positive control
    # A file copied into the run by hand, under a name no step produced.
    (run_dir / 'steps' / 's01' / 'outputs').mkdir(parents=True, exist_ok=True)
    (run_dir / 'steps' / 's01' / 'outputs' / 'unreceipted.json').write_text('{"value": 2}')
    laundered = _step('s02', depends_on=['s01'], inputs=[{'artifact': 's01:outputs/unreceipted.json'}])
    codes = [e['code'] for e in custody.input_errors(store, laundered, run_dir)[0]]
    assert codes == ['predecessor_unreceipted'], codes
    # The adopted bytes changed after custody recorded them.
    target = run_dir / accepted[0]['destination']
    target.write_text('{"value": 999}')
    codes = [e['code'] for e in custody.input_errors(store, consumer, run_dir)[0]]
    assert codes == ['predecessor_bytes_changed'], codes
    target.write_text('{"value": 1}')
    # A producer that is not a dependency of the consuming step.
    stranger = _step('s03', inputs=[{'artifact': artifact}])
    codes = [e['code'] for e in custody.input_errors(store, stranger, run_dir)[0]]
    assert codes == ['input_without_dependency'], codes


register(Mutation('M09', 'ravel.controller.step.custody:_verify', lambda original: lambda *a, **k: [], ('T07',),
                  binding=MUTATION_CONTROLLER, why='consumed artifacts are not verified against custody'))


@case('SW39', binding=CONTROLLER)
def test_SW39_a_step_is_not_dispatched_before_every_parent_completed_in_the_store(nc):
    custody = require_controller('step.custody')
    store, _ = controller_run(nc)
    child = _step('s02', depends_on=['s01'])
    assert [e['code'] for e in custody.parent_errors(store, child)] == ['parent_incomplete']
    custody.record_outcome(store, _step('s01'), 1, 'failed', reason='fictional failure')
    assert [e['code'] for e in custody.parent_errors(store, child)] == ['parent_incomplete']
    (store.run_dir / 'steps' / 's01').mkdir(parents=True, exist_ok=True)
    (store.run_dir / 'steps' / 's01' / 'outcome.json').write_text('{"status": "completed"}')  # a run-tree claim
    assert [e['code'] for e in custody.parent_errors(store, child)] == ['parent_incomplete']
    custody.record_outcome(store, _step('s01'), 2, 'completed')
    assert custody.parent_errors(store, child) == []  # positive control


register(Mutation('SW39', 'ravel.controller.step.custody:parent_errors', lambda original: lambda *a, **k: [],
                  ('SW39',), binding=MUTATION_CONTROLLER, why='dispatch does not check parent completion'))


@case('CF07', binding=CONTROLLER)
def test_CF07_a_role_cannot_set_a_quantity_it_does_not_own(nc):
    cards = require_controller('step.cards')
    from ravel.workflow import role_registry
    owners = [c for c in role_registry.all_cards() if c['ownership']['owns']]
    assert owners, 'the registry declares owned quantities'
    owner = owners[0]
    quantity = owner['ownership']['owns'][0]
    outsider = next(c for c in role_registry.all_cards() if quantity not in c['ownership']['owns'])
    step = _step('s04', quantities={'outputs/result.json': quantity})
    errors = cards.ownership_errors(outsider, step)
    assert [e['code'] for e in errors] == ['ownership_not_owner'] and errors[0]['quantity'] == quantity
    assert cards.ownership_errors(owner, step) == []  # positive control


@case('CF05', binding=CONTROLLER)
def test_CF05_a_missing_required_declared_output_refuses_adoption_before_any_copy(nc):
    custody = require_controller('step.custody')
    store, run_dir = controller_run(nc)
    step = _step('s05', outputs=(('outputs/a.json', 'result'), ('outputs/b.json', 'result')))
    root = nc.root / 'launch-output' / 's05'
    (root / 'outputs').mkdir(parents=True)
    (root / 'outputs' / 'a.json').write_text('{"a": 1}')
    inventory = [{'path': 'outputs/a.json', 'sha256': hashlib.sha256(b'{"a": 1}').hexdigest()}]
    rows = [{'plan_path': p, 'path': p, 'kind': 'result', 'required': True} for p in ('outputs/a.json', 'outputs/b.json')]
    with pytest.raises(Exception) as refused:
        custody.launch_adoption(store, run_dir=run_dir, step=step, attempt=1, card=_card('calculation'),
                                launch={'output_root': str(root), 'inventory': inventory}, outputs=rows,
                                inputs_custody=[])
    assert getattr(refused.value, 'reason', '') == 'declared_output_missing', refused.value
    assert not (run_dir / 'steps' / 's05').exists() and store.scan('custody') == []
    rows[1]['required'] = False  # positive control: an optional output may be absent
    adopted = custody.launch_adoption(store, run_dir=run_dir, step=step, attempt=1, card=_card('calculation'),
                                      launch={'output_root': str(root), 'inventory': inventory}, outputs=rows,
                                      inputs_custody=[])
    assert [r['path'] for r in adopted] == ['outputs/a.json']


@case('CF01', binding=CONTROLLER)
def test_CF01_every_escalation_value_is_handled_and_a_missing_field_fails_the_step(nc):
    validate = require_controller('step.validate')
    escalation = require_controller('step.escalation')
    store, _ = controller_run(nc)
    card = _card('ablation-critic')
    assert validate.escalation({'completed': True}, card)[1] == [{'code': 'escalation_field_missing'}]
    assert validate.escalation({'escalation': 'fictional_escalation'}, card)[1][0]['code'] == 'escalation_invalid'
    narrow = next(c for c in __import__('ravel.workflow.role_registry', fromlist=['all_cards']).all_cards()
                  if set(validate.ESCALATIONS) - set(c['escalation']))
    missing_kind = sorted(set(validate.ESCALATIONS) - set(narrow['escalation']))[0]
    assert validate.escalation({'escalation': missing_kind}, narrow)[1][0]['code'] == 'escalation_not_declared'
    step = _step('s06')
    actions = {}
    for kind in card['escalation']:
        found, errors = validate.escalation({'escalation': [{'kind': kind, 'statement': f'fictional {kind}'}]}, card)
        assert errors == [] and [f['kind'] for f in found] == [kind]
        outcome = escalation.handle(store, step=step, attempt=1, seat=f'seat-{kind}', escalations=found)
        actions[kind] = outcome
    assert actions['stop']['halts'] and actions['decision_block']['halts']
    assert actions['new_experiment_required']['replan'] is not None
    assert actions['checkin_flag']['flags'] and not actions['checkin_flag']['halts']
    assert store.scan('rdj-request') and store.scan('replan-request') and store.scan('checkin-flag')
    assert validate.escalation({'escalation': 'none'}, card) == ([], [])  # positive control: nothing raised


@case('CF06', binding=CONTROLLER)
def test_CF06_a_final_record_must_satisfy_the_card_schema_not_a_hard_coded_one(nc):
    validate = require_controller('step.validate')
    cards = require_controller('step.cards')
    card = _card('analysis-author')
    schema = cards.controller_schema(card)
    legacy_only = {'completed': True, 'summary': 'fictional result written'}  # the hard-coded producer.v1 record
    assert validate.card_schema_errors(card, legacy_only, schema), 'producer.v1 alone is not the card contract'


@case('I09', binding=CONTROLLER)
def test_I09_the_controller_runs_the_validators_a_producer_owes_before_adoption(nc):
    validate = require_controller('step.validate')
    from ravel.validation import validate_run_state
    card = _card('baseline-producer')
    runnable, _ = validate.validator_ids(card)
    assert runnable == ['check:validation.validate_task_contract.validate'], runnable
    broken = nc.root / 'broken-run'
    (broken / 'inputs').mkdir(parents=True)
    (broken / 'inputs' / 'task_contract.json').write_text(json.dumps({'task_mode': 'fictional-mode'}))
    result = validate.run_validators(card, {}, run_dir=broken, scratch=nc.root / 'scratch-broken')
    assert result['passed'] is False and result['results'][0]['status'] != 'passed', result
    good = nc.root / 'good-run'
    (good / 'inputs').mkdir(parents=True)
    contract = validate_run_state._base_contract(task_mode='reproduce', compute_plan='smoke')
    (good / 'inputs' / 'task_contract.json').write_text(json.dumps(contract))
    result = validate.run_validators(card, {}, run_dir=good, scratch=nc.root / 'scratch-good')
    assert result['passed'] is True, result  # positive control


register(Mutation('M10', 'ravel.controller.step.validate:run_validators',
                  lambda original: lambda card, step, **kw: {'results': [], 'reviewer_items': [], 'passed': True},
                  ('I09',), binding=MUTATION_CONTROLLER, why='the controller trusts the producer instead of running checks'),
         Mutation('M11', 'ravel.controller.step.validate:card_schema_errors', lambda original: lambda *a, **k: [],
                  ('CF06',), binding=MUTATION_CONTROLLER, why='the card output schema is not enforced'))


@case('CF02', binding=CONTROLLER)
def test_CF02_the_card_stop_limits_bound_the_worker_whatever_the_executor_default(nc):
    cards = require_controller('step.cards')
    import json as _json
    from ravel.paths import package_data_path
    executor_default = _json.loads(package_data_path('roles', 'executors.json').read_text())['budgets']
    card = deepcopy(_card('analysis-author'))
    card['stop'] = dict(card['stop'], max_wall_seconds=120, max_broker_calls=7, max_turns=3)
    budgets, applied = cards.worker_budgets(card, {'budget': {'wall_seconds': 10 ** 6, 'broker_calls': 10 ** 6}})
    assert budgets['max_wall_seconds'] == 120 and budgets['max_broker_calls'] == 7 and budgets['max_turns'] == 3
    assert applied['card_stop']['max_wall_seconds'] == 120
    narrower, _ = cards.worker_budgets(card, {'budget': {'wall_seconds': 30}})
    assert narrower['max_wall_seconds'] == 30  # a step share narrows the card, never widens it
    assert executor_default, 'the executor table still carries its defaults; the card wins over them'
