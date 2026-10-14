"""Synthetic method contracts and inert scientific dispatch refusals."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ravel.workflow import method_selection as ms
from ravel.workflow import approval_authority as aa
from ravel.workflow.state_io import atomic_json

FIXTURES = Path(__file__).parents[1] / 'fixtures/method_decisions'


def record(name='parameter_scan'):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def write_record(root, value=None):
    atomic_json(root / ms.DECISION_PATH, record() if value is None else value)


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('*.json')), ids=lambda p: p.name)
def test_synthetic_population(path):
    errors = ms.validate_method_decision(json.loads(path.read_text()))
    assert bool(errors) == ('.invalid.' in path.name)


def test_contract_ladders():
    ladders = ms.load_ladders()
    assert len(ladders) == 8
    assert ladders['reinterpretation'][-1] == 'full_detector_simulation'
    assert not any('remote' in m or 'hpc' in m for ladder in ladders.values() for m in ladder)


@pytest.mark.parametrize('change', ['missing', 'unchecked', 'false_quote', 'missing_evidence', 'wrong_rung', 'duplicate'])
def test_lower_methods_are_not_silently_skipped(change):
    r = record(); r['explicit_request'] = {'requested': False, 'quote': None}
    if change == 'missing': r['alternatives'].pop(0)
    if change == 'unchecked': r['alternatives'][0]['status'] = 'not_checked'
    if change == 'false_quote': r['explicit_request'] = {'requested': True, 'quote': None}
    if change == 'missing_evidence': r['alternatives'][0]['evidence'] = []
    if change == 'wrong_rung': r['selected']['rung'] = 0
    if change == 'duplicate': r['alternatives'].append(copy.deepcopy(r['alternatives'][0]))
    assert ms.validate_method_decision(r)
    assert ms.escalation_allowed(r)[0] is False


def test_explicit_quoted_request_allows_unchecked_lower_method():
    r = record('new_events'); r['alternatives'][0]['status'] = 'not_checked'
    assert ms.validate_method_decision(r) == []
    assert ms.escalation_allowed(r)[0]


@pytest.mark.parametrize('status', ['unknown', 'uncalibrated'])
def test_uncertain_top_cost_requires_typed_evidence(status):
    r = record(); r['cost_forecast'].update(status=status, wall_hours=None, cpu_hours=None)
    assert ms.validate_method_decision(r) == []
    assert not ms.escalation_allowed(r)[0]
    assert 'unknown' in ms.render_checkin_section(r)
    r['cost_forecast']['basis'] = 'A pilot or sign-off exists.'
    assert not ms.escalation_allowed(r)[0]
    r['cost_forecast']['bounded_pilot'] = {'max_wall_hours': .1, 'evidence': ['inputs/pilot-plan.json']}
    assert ms.escalation_allowed(r)[0]


def test_signoff_is_not_machine_review():
    r = record(); r['cost_forecast']['status'] = 'unknown'
    r['cost_forecast']['physicist_signoff'] = {'authority': 'delegated_machine', 'quote': 'yes', 'evidence': ['inputs/assent.txt']}
    assert ms.validate_method_decision(r)
    r['cost_forecast']['physicist_signoff']['authority'] = 'human_relayed'
    assert ms.escalation_allowed(r)[0]


@pytest.mark.parametrize('value', [-1, True, float('nan'), float('inf')])
def test_invalid_cost_values(value):
    r = record(); r['cost_forecast']['wall_hours'] = value
    assert ms.validate_method_decision(r)


@pytest.mark.parametrize('kind', ['relative_uncertainty', 'absolute_uncertainty'])
def test_no_invented_precision(kind):
    r = record(); r['sufficiency'].update(kind=kind, value=.01, source_text=None)
    assert ms.validate_method_decision(r)
    r['sufficiency']['source_text'] = 'Compute with uncertainty at most 0.01.'
    assert ms.validate_method_decision(r) == []


@pytest.mark.parametrize('plan', ['full', 'scan'])
@pytest.mark.parametrize('state', ['missing', 'invalid', 'denied'])
@pytest.mark.parametrize('nested', [False, True])
def test_supervisor_refuses_before_inert_launcher(tmp_path, monkeypatch, plan, state, nested):
    from ravel.workflow import stage_supervisor as ss, execution_backend as eb
    calls = []
    monkeypatch.setattr(ss.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    if state != 'missing':
        r = record()
        if state == 'invalid': r['alternatives'].pop(0)
        else: r['cost_forecast']['status'] = 'unknown'
        write_record(tmp_path, r)
    parent = tmp_path / 'parent'; parent.mkdir()
    if nested:
        monkeypatch.setattr(eb, 'require_approved_stage', lambda *a: {'rundir': str(tmp_path), 'required_plan': plan})
    with pytest.raises(ValueError, match='method-decision.json'):
        ss.supervise('synthetic', tmp_path, 2000, 'logs/inert.log', ['inert'], required_plan=plan,
                     nested_under=(parent, 'parent') if nested else None, kill_secs=1)
    assert calls == []


def test_unchecked_scientific_dispatch_cannot_use_popen(tmp_path, monkeypatch):
    from ravel.workflow import stage_supervisor as ss
    calls = []; monkeypatch.setattr(ss.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match='engineering'):
        ss.supervise('synthetic', tmp_path, 0, 'logs/inert.log', ['inert'], kill_secs=1)
    assert not calls


@pytest.mark.parametrize('plan', ['full', 'scan'])
@pytest.mark.parametrize('state', ['missing', 'invalid', 'denied'])
def test_remote_dispatch_refuses_before_fake_submit(tmp_path, monkeypatch, plan, state):
    from ravel.workflow import execution_backend as eb, machine_lease
    calls = []
    fake = SimpleNamespace(kind='inert', submit=lambda *a: calls.append(a))
    if state != 'missing':
        r = record()
        if state == 'invalid': r['alternatives'].pop(0)
        else: r['cost_forecast']['status'] = 'unknown'
        write_record(tmp_path, r)
    atomic_json(tmp_path / 'inputs/task_contract.json', {'compute_plan': plan})
    monkeypatch.setattr(eb, 'check_plan', lambda p: p)
    monkeypatch.setattr(eb, 'is_local', lambda p: False)
    monkeypatch.setattr(machine_lease, 'working', lambda: None)
    monkeypatch.setattr(machine_lease, 'inherited', lambda: None)
    monkeypatch.setattr(eb, 'require_approved_stage', lambda *a: {'rundir': str(tmp_path), 'stage': 'synthetic', 'attempt_id': 'a', 'required_plan': plan})
    with pytest.raises(ValueError, match='method-decision.json'):
        eb.submit({'spec': {'backend': 'inert'}}, tmp_path / 'attempt', authority=(tmp_path, 'synthetic'), backend=fake)
    assert not calls
    assert not (tmp_path / 'attempt').exists()


def test_light_paths_do_not_require_record(tmp_path):
    for plan in ('none', 'dry', 'smoke'):
        assert ms.launch_errors(tmp_path, plan) == []


def test_approval_fingerprint_contains_decision(tmp_path):
    from ravel.workflow import workflow_state as ws
    write_record(tmp_path)
    assert str(tmp_path / ms.DECISION_PATH) in ws.approval_input_paths(tmp_path)


def test_checkin_registry_displays_method_and_ceiling(tmp_path):
    from ravel.validation.validate_checkin import with_registered_sections, registered_section_errors
    write_record(tmp_path)
    atomic_json(tmp_path / 'inputs/task_contract.json', {'operation_resources': {'max_seconds': 3600}})
    c = with_registered_sections({'kind': 'checkin1', 'sections': {}}, tmp_path)
    section = c['sections']['method_decision']
    assert 'justified_scan' in section and 'insufficient' in section
    assert 'ceiling' in section and 'within' in section
    assert registered_section_errors(c, tmp_path) == []
    r = record(); r['cost_forecast']['wall_hours'] = 2; write_record(tmp_path, r)
    assert registered_section_errors(c, tmp_path)


@pytest.mark.parametrize('kwargs, expected', [
    ({'scripted': True, 'quote': 'yes'}, 'scripted_experiment'),
    ({'delegated': True, 'scripted': True}, 'delegated_machine'),
    ({'agent_session': True, 'quote': 'Approve this exact plan.'}, 'human_relayed'),
    ({'agent_session': False, 'interactive': True}, 'human_operator'),
    ({'agent_session': True, 'interactive': True}, 'unknown'),
    ({}, 'unknown')])
def test_authority_from_evidence(kwargs, expected):
    assert aa.classify(**kwargs) == expected


@pytest.mark.parametrize('receipt, expected', [({}, 'unknown'), ({'quote':'yes'}, 'unknown'),
    ({'approval_mode':'scripted_yes'}, 'scripted_experiment'),
    ({'authority':'machine_under_user_delegation'}, 'delegated_machine')])
def test_old_authority_is_not_invented(receipt, expected):
    assert aa.authority(receipt) == expected


@pytest.mark.parametrize('alias', ['steer', 'respond'])
def test_top_level_aliases_dispatch_existing_subcommands(monkeypatch, alias):
    from ravel import cli
    from ravel.workflow import gate_wiring
    calls = []
    monkeypatch.setattr(gate_wiring, 'main', lambda argv: calls.append(argv) or 0)
    assert cli.main([alias, '--rundir', 'fictional', '--text', 'Continue within the ceiling.']) == 0
    assert calls == [[alias, '--rundir', 'fictional', '--text', 'Continue within the ceiling.']]


def test_native_scripted_assent_receipt_and_changed_decision_stale(tmp_path, monkeypatch):
    from test_approval_chain import _rundir
    from ravel.workflow import workflow_state as ws
    from ravel.validation.validate_checkin import with_registered_sections
    rd = _rundir(tmp_path)
    write_record(rd)
    c = json.loads((rd / 'inputs/checkin1.json').read_text())
    atomic_json(rd / 'inputs/checkin1.json', with_registered_sections(c, rd))
    args = SimpleNamespace(rundir=str(rd), plan='smoke', quote='Synthetic scripted assent', scripted=True)
    assert ws.cmd_approve(args) == 0
    approval = json.loads((rd / 'inputs/checkin1_approval.json').read_text())
    assert approval['authority'] == 'scripted_experiment'
    assert ws.verify_approval(rd) == []
    r = record(); r['cost_forecast']['basis'] = 'A different retained observation.'; write_record(rd, r)
    assert any('stale' in e for e in ws.verify_approval(rd))


@pytest.mark.parametrize('plan', ['full', 'scan'])
def test_native_full_approval_verification_requires_record(tmp_path, plan):
    from ravel.workflow import workflow_state as ws
    assert 'method-decision.json' in '; '.join(ws.verify_approval(tmp_path, required_plan=plan))


@pytest.mark.parametrize('schema_version', [1, 2])
def test_science_scripted_approval_authority_and_method_binding(tmp_path, monkeypatch, schema_version):
    from ravel.workflow import science, execution
    from test_science_review_envelope import specification
    from test_science_workflow import fixture
    if schema_version == 1:
        rd, source = fixture(tmp_path)
    else:
        source = tmp_path / 'spec.json'; atomic_json(source, specification(tmp_path))
        rd = tmp_path / 'run'
    def small_binding(rd, stage, command, inputs, outputs, parents, cwd, **kw):
        import sys
        inputs = list(inputs) + [str(Path(sys.executable).resolve())]
        result = {'command': list(command), 'cwd': str(Path(cwd).resolve()), 'inputs': inputs,
                  'outputs': outputs, 'parents': {}, 'runtime': execution.runtime_context(),
                  'input_snapshot': execution.snapshot(rd, inputs)}
        result['fingerprint'] = execution.digest(result)
        return result
    monkeypatch.setattr(execution, 'plan_stage', small_binding)
    science.plan(rd, source)
    write_record(rd, record('rough_estimate'))
    ms.refresh_checkin(rd)
    assert science.approve(rd, 'Synthetic scripted assent', scripted=True) == 0
    approval = json.loads((rd / science.APPROVAL).read_text())
    assert approval['authority'] == 'scripted_experiment'
    assert 'input_fingerprint' in approval
    assert str(rd / ms.DECISION_PATH) in science.approval_input_paths(rd)
    if schema_version == 1:
        r=record('rough_estimate');r['provenance']['author_role']='alternate-coordinator';write_record(rd,r)
        with pytest.raises(ValueError,match='stale'):
            science.verify_plan(rd,approved=True)
    if schema_version == 2:
        assert 'analytic_estimate' in (rd / 'CHECKIN1.md').read_text()
        assert str(rd / ms.DECISION_PATH) in science.approval_input_paths(rd)
        r = record('rough_estimate'); r['stopping_criterion'] = 'A different endpoint.'; write_record(rd, r)
        with pytest.raises(ValueError, match='stale'):
            science._verify_v2_approval(rd, json.loads((rd / science.SPEC).read_text()))


def test_science_full_verification_refuses_missing_method(tmp_path):
    from ravel.workflow import science
    with pytest.raises(ValueError, match='method-decision.json'):
        science._verify_v2_approval(tmp_path, {'schema_version': 2, 'mode': 'domain'})


def test_native_cli_forwards_scripted_switch(tmp_path, monkeypatch):
    from ravel import cli
    from ravel.workflow import workflow_state
    calls=[]; monkeypatch.setattr(workflow_state, 'main', lambda args: calls.append(args) or 0)
    assert cli._native_approve(SimpleNamespace(rundir=tmp_path, plan='smoke', quote='Synthetic assent', scripted=True)) == 0
    assert calls[0][-1] == '--scripted'


def test_engineering_path_is_unreachable_from_agent_session(tmp_path, monkeypatch):
    from ravel.workflow import stage_supervisor as ss
    calls=[]; monkeypatch.setattr(ss.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    monkeypatch.setenv('RAVEL_SESSION_ID', 'inert-session')
    with pytest.raises(ValueError, match='engineering-only'):
        ss.supervise('engineering', tmp_path, 0, 'logs/inert.log', ['inert'], _engineering_only=True, kill_secs=1)
    assert not calls


def test_unknown_forecast_does_not_report_within_ceiling(tmp_path):
    r = record('rough_estimate'); r['cost_forecast'].update(status='unknown', wall_hours=0)
    text = ms.checkin_section({'method_decision': r, 'document': {'sections': {}}, 'approved_ceiling': {'wall_hours':1}})
    assert 'approved ceiling 1; status unknown' in text


def test_refresh_is_idempotent_and_stales_prior_approval(tmp_path):
    write_record(tmp_path)
    atomic_json(tmp_path / 'inputs/checkin1.json', {'kind':'checkin1', 'sections':{}})
    ms.refresh_checkin(tmp_path); original = (tmp_path / 'CHECKIN1.md').read_text()
    ms.refresh_checkin(tmp_path)
    assert (tmp_path / 'CHECKIN1.md').read_text() == original
    r=record(); r['required_output']='A revised fictional output.'; write_record(tmp_path, r)
    ms.refresh_checkin(tmp_path)
    assert (tmp_path / 'CHECKIN1.md').read_text().count('### Method decision') == 1


def test_science_cannot_borrow_zero_compute_parent_to_skip_gate(tmp_path):
    atomic_json(tmp_path / 'inputs/task_contract.json', {'compute_plan':'none'})
    with pytest.raises(ValueError, match='method-decision.json'):
        ms.require_launch(tmp_path, spec={'schema_version':2, 'mode':'domain'})


@pytest.mark.parametrize('route', ['native', 'scoped', 'science', 'science_legacy'])
@pytest.mark.parametrize('state', ['missing', 'invalid', 'denied'])
def test_scientific_supervisor_branches_gate_before_launcher(tmp_path, monkeypatch, route, state):
    from ravel.workflow import stage_supervisor as ss
    calls=[]; monkeypatch.setattr(ss.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    kwargs={}
    if route == 'native': kwargs['authorization_plan']={'compute_plan':'full'}
    elif route == 'scoped': atomic_json(tmp_path/'inputs/scoped-plan.json', {'mode':'likelihood'})
    else: atomic_json(tmp_path/'inputs/science.json', {'schema_version':1 if route == 'science_legacy' else 2, 'mode':'domain'})
    if state != 'missing':
        r=record()
        if state == 'invalid': r['alternatives'].pop(0)
        else: r['cost_forecast']['status']='unknown'
        write_record(tmp_path,r)
    with pytest.raises(ValueError, match='method-decision.json'):
        ss.supervise('synthetic',tmp_path,0,'logs/inert.log',['inert'],kill_secs=1,**kwargs)
    assert not calls


def test_nested_checks_parent_even_when_child_decision_valid(tmp_path,monkeypatch):
    from ravel.workflow import stage_supervisor as ss
    child=tmp_path/'child';child.mkdir();write_record(child)
    parent=tmp_path/'parent';parent.mkdir();atomic_json(parent/'inputs/task_contract.json',{'compute_plan':'scan'})
    calls=[];monkeypatch.setattr(ss.subprocess,'Popen',lambda *a,**k:calls.append(a))
    with pytest.raises(ValueError,match='parent/inputs/method-decision.json'):
        ss.supervise('synthetic',child,2000,'logs/inert.log',['inert'],required_plan='full',nested_under=(parent,'parent'),kill_secs=1)
    assert not calls


def test_remote_inherited_lease_cannot_skip_method_gate(tmp_path,monkeypatch):
    from ravel.workflow import execution_backend as eb,machine_lease
    atomic_json(tmp_path/'inputs/task_contract.json',{'compute_plan':'full'})
    monkeypatch.setattr(machine_lease,'working',lambda:SimpleNamespace(rundir=str(tmp_path)))
    calls=[];monkeypatch.setattr(eb,'_bind_plan',lambda *a:calls.append(a))
    with pytest.raises(ValueError,match='method-decision.json'):
        eb.dispatch_authority({'spec':{'backend':'inert'}})
    assert not calls


@pytest.mark.parametrize('plan', ['full','scan'])
def test_correction_envelope_cannot_bypass_method_gate(tmp_path,monkeypatch,plan):
    from ravel.workflow import workflow_state as ws
    monkeypatch.setattr(ws,'verify_approval',lambda *a,**k:[])
    atomic_json(tmp_path/'inputs/checkin1_approval.json',{'approved_plan':'scan','generated_utc':'2026-10-12T10:00:00Z'})
    assert 'method-decision.json' in '; '.join(ws.verify_approval_envelope(tmp_path,plan))


def test_retained_method_context_never_reads_current_source_directory(tmp_path):
    write_record(tmp_path)
    # An explicitly absent record belongs to the retained observation, even if
    # today's source directory carries a different decision.
    assert ms.checkin_section({'base_dir':tmp_path,'method_decision':None,'document':{'sections':{}}}) is None


@pytest.mark.parametrize('family', ['explanation','estimate_theory','model_spectrum','supplied_events','reinterpretation','fit_measurement','open_research','documents_figures'])
def test_uncalibrated_top_rung_requires_pilot_for_every_family(family):
    r=record();ladder=ms.load_ladders()[family];r['family']=family
    r['selected']={'method':ladder[-1],'rung':len(ladder)-1,'operation':None}
    r['alternatives']=[{'method':m,'rung':i,'status':'unavailable','reason':'The fictional inventory has no matching source.','evidence':['inputs/fictional-inventory.json']} for i,m in enumerate(ladder[:-1])]
    r['cost_forecast']['status']='uncalibrated'
    assert not ms.escalation_allowed(r)[0]
    r['cost_forecast']['bounded_pilot']={'max_wall_hours':.01,'evidence':['inputs/fictional-pilot.json']}
    assert ms.escalation_allowed(r)[0]


def test_science_missing_method_refuses_before_writing_approval(tmp_path,monkeypatch):
    import sys
    from ravel.workflow import science,execution
    from test_science_review_envelope import specification
    source=tmp_path/'spec.json';atomic_json(source,specification(tmp_path));rd=tmp_path/'run'
    def small_binding(rd,stage,command,inputs,outputs,parents,cwd,**kwargs):
        inputs=list(inputs)+[str(Path(sys.executable).resolve())]
        binding={'command':list(command),'cwd':str(Path(cwd).resolve()),'inputs':inputs,
                 'outputs':outputs,'parents':{},'runtime':execution.runtime_context(),'input_snapshot':execution.snapshot(rd,inputs)}
        binding['fingerprint']=execution.digest(binding);return binding
    monkeypatch.setattr(execution,'plan_stage',small_binding)
    science.plan(rd,source)
    with pytest.raises(ValueError,match='method-decision.json'):
        science.approve(rd,'Synthetic assent',scripted=True)
    assert not (rd/science.APPROVAL).exists()


@pytest.mark.parametrize('field', ['schema_version','selected','alternative'])
def test_integral_float_is_not_a_schema_version_or_ladder_index(field):
    r=record()
    if field == 'schema_version':r['schema_version']=1.0
    elif field == 'selected':r['selected']['rung']=float(r['selected']['rung'])
    else:r['alternatives'][0]['rung']=0.0
    assert ms.validate_method_decision(r)
    assert not ms.escalation_allowed(r)[0]


@pytest.mark.parametrize('declared', ['human_operator', 'human_relayed'])
def test_checkin_never_prints_unevidenced_human_decision_authority(declared):
    r = record(); r['provenance']['authority'] = declared
    text = ms.render_checkin_section(r)
    assert 'human' not in text.lower()
    assert 'unverified' in text and 'approval receipt' in text


def test_checkin_prints_machine_decision_authority():
    r = record(); r['provenance']['authority'] = 'delegated_machine'
    assert 'Decision authority: delegated_machine.' in ms.render_checkin_section(r)


def test_version_two_approval_shape_accepts_only_evidenced_authority_labels():
    from ravel.workflow import science
    base = dict.fromkeys(('schema_version', 'generated_by', 'quote', 'approval_mode', 'expert_review',
                          'plan_sha256', 'checkin_sha256', 'utc', 'input_fingerprint'), 'x')
    science._v2_approval_keys(base, 'prior')
    science._v2_approval_keys({**base, 'authority': 'scripted_experiment'}, 'prior')
    with pytest.raises(ValueError, match='invalid authority'):
        science._v2_approval_keys({**base, 'authority': 'human'}, 'prior')
    with pytest.raises(ValueError, match='requires exactly'):
        science._v2_approval_keys({**base, 'extra': 1}, 'prior')
