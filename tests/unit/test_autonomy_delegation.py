"""Fictional request -> frozen mode -> CI1 -> inert supervised authorization."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
from ravel.workflow import scientific_autonomy as autonomy, operating_mode as mode
from ravel.workflow import workflow_state as ws, launch_authorization as launch, gate_wiring
from ravel.workflow.state_io import atomic_json, read_json
import intake_sidecar_fixtures as fx
from test_operating_mode import operator, set_operator_mode, authorize_run, initialize_trusted
from inert_dispatch import inert_dispatch  # noqa: F401


@pytest.mark.parametrize('message', [
    'Run autonomously.', 'Run this task autonomously.', 'I grant you full autonomy.',
    'I authorize autonomous operation.', 'Proceed without further approval.', 'Please operate autonomously.', 'Proceed autonomously within the task limits.',
    'Work autonomously.', 'You may run autonomously.', 'I authorize you to operate autonomously.',
    'I delegate autonomous operation to you.', 'Use autonomous mode.', 'Enable autonomous mode.',
    'Complete this task autonomously.', 'Perform the task without further confirmation.',
    'Calculate the polynomial and proceed autonomously.',
])
def test_varied_explicit_delegations_are_exact_source_spans(message):
    span = autonomy.delegation_intent(message)
    assert span is not None
    assert message[span['start']:span['end']] == span['text']
    assert mode.request_mode(message)[0] == 'autonomous'


@pytest.mark.parametrize('message', [
    'Do not operate autonomously.', 'Never proceed autonomously.', 'If ready, work autonomously.',
    'The example says "Operate autonomously."', 'Example:\nProceed autonomously.',
    '> Use autonomous mode.', '```\nEnable autonomous mode.\n```', 'You may run autonomously?',
    'Run autonomously. Wait for my approval at every check-in.',
    'I might authorize you to operate autonomously.', 'Please inspect the polynomial.',
])
def test_missing_conditional_quoted_or_negated_authority_refuses(message):
    assert autonomy.delegation_intent(message) is None


def planned(root, prompt='Inspect the fictional polynomial.', *, epoch=2, authorize=True):
    from ravel.workflow.request_plan import provisional_label
    nodes=[fx.node(operation='literal-calculation', covers=['original-request'])]
    claims=[fx.claim(kind='calculation', statement='value of the fictional polynomial',
        basis_declared=['generated_prediction'], comparison={'target':'none','locator':None,'metric':None,'tolerance':None})]
    draft=fx.plan({'path':'inputs/reading.json','sha256':'0'*64}, prompt, nodes=nodes, claims=claims)
    label=provisional_label(fx.reading(prompt), draft)
    contract, reading, plan = fx.pinned_run(root, prompt=prompt,
        plan_overrides={'claims':claims, 'nodes':nodes, 'label':label},
        contract_overrides={'task_mode':label['task_mode']})
    if authorize:
        authorize_run(root, contract)
    ws.new_state(str(root), contract, str(root / 'inputs/task_contract.json'), 'fixture')
    gate_wiring.record_run_init(root)
    checkin=fx.checkin1(plan, reading)
    checkin['variant']=label['task_mode']
    checkin['sections'].update(formula='f(x)=x*x', conventions='dimensionless', inputs={'x':2},
                               precision='exact', check_value='f(0)=0')
    atomic_json(root / 'inputs/checkin1.json', checkin)
    atomic_json(root / 'inputs/cost_preflight.json', {'schema_version':1, 'generated_by':'cost_preflight.py',
                                                   'mode':'none', 'walltime_h':[0,0]})
    return contract


def test_default_human_mode_refuses_machine_approval(operator):
    root = operator / 'run'; planned(root)
    with pytest.raises(ValueError, match='delegation required'):
        ws.record_delegated_approval(root, 'none')
    assert not (root / 'inputs/checkin1_approval.json').exists()


def test_mode_does_not_skip_independent_plan_gate(operator):
    set_operator_mode('autonomous')
    root = operator / 'run'; planned(root)
    with pytest.raises(ValueError):
        ws.record_delegated_approval(root, 'none')
    assert not (root / 'inputs/checkin1_approval.json').exists()
    assert mode.bind_plan(root)
    assert autonomy.plan_authority(root, required_plan='none')['value']['origin'] == 'operating_mode'


def test_intake_to_ci1_preserves_contract_and_refuses_untyped_launch(operator, monkeypatch, inert_dispatch):
    # Real epoch-two plan and launch gates; only transport and process are inert.
    set_operator_mode('autonomous')
    root = operator / 'run'; planned(root, epoch=None)
    admit_plan(root, monkeypatch)
    before = {p: (root / p).read_bytes() for p in ('inputs/task_contract.json', 'inputs/plan.json', 'inputs/checkin1.json')}
    monkeypatch.chdir(operator)
    assert ws.main(['approve', '--rundir', 'run', '--plan', 'none', '--quote', 'Proceed']) == 0
    receipt = read_json(root / 'inputs/checkin1_approval.json')
    assert receipt['authority'] == 'delegated_machine'
    assert receipt['operating_mode']['source'] == 'project'
    assert not ws.verify_approval('run', required_plan='none')
    assert all((root / p).read_bytes() == data for p, data in before.items())
    with pytest.raises(ValueError, match='plan-derived resource contract'):
        launch.authorized_popen('run', 'none', ['fictional-worker'],
            context={'stage':'science', 'events':0, 'max_seconds':10})
    assert launch._events(root) == []


@pytest.mark.parametrize('change', ['plan', 'checkin', 'mode', 'revoked', 'scope'])
def test_bound_authority_refuses_scope_snapshot_and_revocation_changes(operator, monkeypatch, change, inert_dispatch):
    set_operator_mode('autonomous')
    root=operator/'run'; planned(root, epoch=None)
    admit_plan(root, monkeypatch)
    ws.record_delegated_approval(root, 'none')
    if change == 'scope':
        assert ws.verify_approval(str(root), required_plan='smoke')
        return
    if change == 'revoked':
        atomic_json(root / autonomy.REVOCATION, {'revoked':True})
    else:
        path=root / {'plan':'inputs/plan.json', 'checkin':'inputs/checkin1.json', 'mode':mode.RUN_RECORD}[change]
        value=read_json(path);value['changed']=True;atomic_json(path,value)
    assert ws.verify_approval(str(root), required_plan='none')
    with pytest.raises(ValueError):
        launch.authorized_popen(root, 'none', ['fictional-worker'], context={'stage':'science', 'events':0, 'max_seconds':1})


def test_ceiling_refusal_leaves_no_transition(operator):
    bounds=deepcopy(mode.DEFAULT_BOUNDS);bounds['max_seconds']=5
    set_operator_mode('autonomous', bounds=bounds)
    root=operator/'run';planned(root)
    with pytest.raises(ValueError, match='budget'):
        mode.bind_plan(root)
    assert not (root / autonomy.TRANSITION).exists()


def test_explicit_request_is_primary_source(operator, monkeypatch, inert_dispatch):
    set_operator_mode('physicist-in-the-loop')
    root=operator/'run';planned(root, 'Please operate autonomously. Inspect the fictional polynomial.', epoch=None)
    admit_plan(root, monkeypatch)
    receipt=ws.record_delegated_approval(root,'none')
    assert receipt['operating_mode']['source']=='explicit_request'
    assert receipt['quote']=='Please operate autonomously.'


def test_existing_ci1_request_plan_transition_needs_no_native_plan(operator):
    root=operator/'run';planned(root, epoch=None)
    text=operator/'response.txt';text.write_text('Proceed autonomously.')
    autonomy.record_checkin1_delegation(root,
        user_text={'path':str(text),'sha256':hashlib.sha256(text.read_bytes()).hexdigest()},
        quote=text.read_text(),delegate_actor='fixture-coordinator',actions=['approve_plan'],
        bounds={'compute_plans':['none'],'allowed_changed_paths':[],'allowed_stages':[],'max_redos':0},
        task_class='research_analysis')
    assert autonomy.plan_authority(root,required_plan='none')
    assert mode.receipt(root)['source']=='explicit_request'
    assert mode.receipt(root)['mode']=='autonomous'


def admit_plan(root, monkeypatch):
    """Fake transport only: real RDJ plan case, custody and gate decision."""
    from rdj_fixtures import Run, prepare_case
    from ravel.workflow import transport_registry, rdj_loop
    mode.bind_plan(root)
    run=Run.__new__(Run);run.root=root
    prompt=read_json(root/'inputs/task_contract.json')['prompt']
    run.prompt_span=lambda text: {'kind':'user_requirement', 'binding':{
        'source':'prompt','sha256':hashlib.sha256(prompt.encode()).hexdigest(),
        'start':0,'end':len(prompt),'text':prompt}}
    monkeypatch.setattr(transport_registry,'select',lambda card,*a,**kw: {'role':card['id'],'transport':'fictional'})
    action=gate_wiring.plan_action(root,'none',write=True)
    case=prepare_case(run,'approve_plan','plan_approval','R2',action=action)
    assert rdj_loop.authorize(root,case)['outcome']=='authorize'
    from test_review_points import credit_pending
    credit_pending(root, gate='approve_plan')
