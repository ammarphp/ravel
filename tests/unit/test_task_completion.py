"""Whole task/child acceptance controls; no native worker or scientific calls.

The review journals use ordinary APIs with synthetic receipts and mocked compute
approval, as test_physics_review does. They test state/custody, not physics truth.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from test_scientific_judgment import observed_role_boundary

from ravel.workflow import task_completion as tc, route_prompt, scientific_report as sr
from ravel.workflow import execution, science, physics_review as pr, workflow_state, review_context, agent_graph, agent_host
from ravel.workflow.state_io import atomic_json, read_json
from ravel.validation.validate_task_contract import validate
from test_physics_review import policy, make_attempt, check_packet, accept
from test_scientific_report import fixture as report_fixture

PROMPT = "Consider a model (say HVT) with a Z'->WW. Construct a summary plot of ATLAS+CMS searches sensitive to Z'->WW for m(Z') < 500 GeV."


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); atomic_json(path, value); return pin(path)


def goal(base, *, clipped=False):
    c = route_prompt.route(PROMPT); req = tc.initial_requirements(PROMPT)
    req['obligations'] += [{'id': oid, 'kind': kind, 'statement': statement, 'criteria': criteria,
        'evidence': [{'start': 0, 'end': len(PROMPT), 'text': PROMPT}]} for oid, kind, statement, criteria in (
        ('atlas', 'coverage', 'ATLAS eligibility/coverage', {'experiment': 'ATLAS', 'census': 'requested searches'}),
        ('cms', 'coverage', 'CMS eligibility/coverage, including legitimate negative source evidence', {'experiment': 'CMS', 'census': 'requested searches'}),
        ('domain', 'domain', 'No invented lower mass bound', {'lower_gev': None, 'upper_gev': 500, 'upper_inclusive': False}))]
    coverage = [{'obligation_id': r['id'], 'criteria': deepcopy(r['criteria'])} for r in req['obligations']]
    if clipped:
        coverage[-1]['criteria']['lower_gev'] = 150
        coverage[0]['criteria'] = {'request_subset': 'Historical supplied census,150<=m<500'}
    req['assignments'] = [{'id': 'summary-child', 'purpose': 'A bounded supplied-census child, preserving the parent goal.', 'coverage': coverage}]
    c['task_requirements'] = req
    assert validate(c) == []
    return c, write(base / 'parent/inputs/task_contract.json', c)


def child(base, contract, *, state='partial'):
    rd = base / 'child'; binding = {'contract': contract, 'assignment_id': 'summary-child'}
    write(rd / science.SPEC, {'goal_binding': binding, 'source': 'Synthetic child scope, not actual HVT.'})
    c = read_json(contract['path']); coverage = c['task_requirements']['assignments'][0]['coverage']
    return {'assignment_id': 'summary-child', 'rundir': str(rd), 'claim_scope': 'diagnostic',
        'coverage': [{**deepcopy(row), 'state': state, 'evidence': [], 'explanation': 'Synthetic scope contribution; physical inputs remain explicit.'} for row in coverage]}


def request(base, contract, outcomes=(), *, parent_review=None, report=None):
    return write(base / 'completion.json', {'schema_version': 1, 'contract': contract, 'outcomes': list(outcomes),
        'parent_review': parent_review, 'report': report})


def review_run(root, extra_inputs, monkeypatch, *, scope="diagnostic"):
    p = policy(); p["claim_scopes"]["original_task_completion"] = {"checks": ["integrity", "agreement"], "actions": ["delivery", "reuse"]}
    (root / 'inputs').mkdir(parents=True, exist_ok=True)
    atomic_json(root / pr.POLICY, p)
    atomic_json(root / 'inputs/checkin1_approval.json', {'fixture': 'mocked compute approval only'})
    monkeypatch.setattr(pr, '_science_run', lambda root: False)
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'synthetic no-child hardware description')
    monkeypatch.setattr(workflow_state, 'approval_input_paths', lambda rd: [str(Path(rd) / pr.POLICY)])
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    (root / 'inputs/settings.cfg').write_text('synthetic=1\n')
    (root / 'inputs/held-fixed.txt').write_text('fixed\n')
    atomic_json(root / 'inputs/reference.json', {'reference': 1})
    record = make_attempt(root, extra_inputs=extra_inputs)
    check_packet(root, record)
    pr.open_cycle(root, effective_settings=['inputs/settings.cfg'], stage_receipts=[record['attempt_record']], check_results='inputs/checks.json')
    accept(root, scope=scope)
    return root


def resolved(base, contract, monkeypatch, *, clipped=False):
    out = child(base, contract, state='satisfied'); rd = Path(out['rundir'])
    evidence = write(rd / 'inputs/coverage.json', {'observed': 'Synthetic coverage evidence, including source-negative CMS eligibility.'})
    for row in out['coverage']: row['evidence'] = [evidence]
    out['coverage'][2]['state'] = 'negative'
    review_run(rd, [contract['path'], str(rd / science.SPEC), evidence['path']], monkeypatch)
    return out


def test_original_request_and_unobserved_obligations_remain_active(tmp_path):
    c, cp = goal(tmp_path); result = tc.evaluate(request(tmp_path, cp), base_dir=tmp_path)
    assert result['original_request'] == PROMPT and set(result['unmet_obligation_ids']) == {'original-request', 'atlas', 'cms', 'domain'}
    assert result['unobserved_assignment_ids'] == ['summary-child']
    assert not result['ready_for_parent_review'] and not result['parent_task_accepted']


@pytest.mark.parametrize('state', ['partial', 'unknown', 'blocked'])
def test_partial_or_refused_child_keeps_constructive_parent_work_open(tmp_path, state):
    _, cp = goal(tmp_path); out = child(tmp_path, cp, state=state)
    rp = request(tmp_path, cp, [out]); before = read_json(cp['path'])
    result = tc.evaluate(rp, base_dir=tmp_path)
    assert set(result['unmet_obligation_ids']) == {'original-request', 'atlas', 'cms', 'domain'}
    assert result['obligation_census'][0]['contributions'][0]['state'] == state
    assert read_json(cp['path']) == before
    with pytest.raises(ValueError, match='parent task remains open'): tc.require_final(rp, base_dir=tmp_path)


def test_successful_clipped_child_does_not_close_unbounded_parent_domain(tmp_path, monkeypatch):
    _, cp = goal(tmp_path, clipped=True); out = resolved(tmp_path, cp, monkeypatch)
    result = tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)
    assert result['unmet_obligation_ids'] == ['original-request', 'domain']
    assert result['obligation_census'][2]['contributions'][0]['state'] == 'negative'
    assert not result['parent_task_accepted']


def test_exact_positive_and_negative_source_coverage_only_ready_for_parent_review(tmp_path, monkeypatch):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch)
    result = tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)
    assert result['ready_for_parent_review'] and result['unmet_obligation_ids'] == []
    assert not result['parent_task_accepted'] and not result['semantic_entailment_verified']


def test_partial_progress_report_exposes_original_goal_and_open_coverage(tmp_path):
    _, cp = goal(tmp_path); rp = request(tmp_path, cp, [child(tmp_path, cp)])
    recipe = report_fixture(tmp_path); recipe.update(task_completion=rp, delivery='progress')
    result = sr.compose(recipe, base_dir=tmp_path)
    assert result['declared_fact_census_complete'] and not result['task_completion']['parent_task_accepted']
    assert PROMPT in result['report_text'] and '| cms |' in result['report_text'] and '| open |' in result['report_text']
    draft = {'slots': result['expected_slots'], 'interpretation': ['An honest scoped diagnostic, not parent completion.']}
    assert PROMPT in sr.revise(recipe, draft, base_dir=tmp_path)['report_text']
    recipe['delivery'] = 'final'
    with pytest.raises(ValueError): sr.compose(recipe, base_dir=tmp_path)


def test_agent_authored_narrowing_note_does_not_discharge_original_obligation(tmp_path):
    c, cp = goal(tmp_path)
    original = c['task_requirements']['obligations'][2]
    amendment = {'schema_version': 1, 'kind': 'task-scope-instruction', 'authority': 'direct-user-instruction',
        'prompt_sha256': c['task_requirements']['prompt_sha256'], 'instruction': 'Only ATLAS is now required.',
        'changes': [{'obligation_id': 'cms', 'before_sha256': tc.ce.digest(original), 'disposition': 'withdraw',
                     'statement': 'CMS withdrawn by proposed instruction', 'criteria': None}]}
    c['task_requirements']['amendments'] = [write(tmp_path / 'agent-note.json', amendment)]
    cp = write(Path(cp['path']), c)
    result = tc.evaluate(request(tmp_path, cp), base_dir=tmp_path)
    assert 'cms' in result['unmet_obligation_ids']
    assert not result['scope_changes'][0]['effective_authorization']
    assert result['obligation_census'][2]['effective'] == original


def test_recovery_after_refusal_keeps_original_contract_and_all_unknowns(tmp_path, monkeypatch):
    _, cp = goal(tmp_path); blocked = request(tmp_path, cp, [child(tmp_path, cp, state='blocked')])
    before = tc.evaluate(blocked, base_dir=tmp_path)
    retained = write(tmp_path / 'failed-completion.json', read_json(blocked['path']))
    out = resolved(tmp_path, cp, monkeypatch)
    after = tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)
    assert after['ready_for_parent_review'] and not before['ready_for_parent_review']
    assert tc.evaluate(retained, base_dir=tmp_path)['unmet_obligation_ids'] == before['unmet_obligation_ids']


@pytest.mark.parametrize('mutation', ['contract', 'evidence', 'hold'])
def test_cached_child_acceptance_does_not_override_live_drift_or_hold(tmp_path, monkeypatch, mutation):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch); rp = request(tmp_path, cp, [out])
    assert tc.evaluate(rp, base_dir=tmp_path)['ready_for_parent_review']
    if mutation == 'contract': Path(cp['path']).write_text('{}\n')
    elif mutation == 'evidence': Path(out['coverage'][0]['evidence'][0]['path']).write_text('{}\n')
    else: monkeypatch.setattr(pr, 'gate_errors', lambda *a, **kw: ['synthetic actual hold'])
    with pytest.raises(ValueError): tc.evaluate(rp, base_dir=tmp_path)


def review_final_artifacts(parent, completion, base_recipe, base, monkeypatch):
    """Actual current CI3 graphs with inert model replies, never a pass-bit mock."""
    from test_autonomy_final_results import package, pin as artifact_pin
    from test_scientific_judgment import FakeHost
    from ravel.workflow import scientific_judgment as judgment, final_results_review
    recipe = {**deepcopy(base_recipe), 'task_completion': completion, 'delivery': 'final'}
    draft = sr.prepare_final(recipe, base_dir=base)
    prior = pr._view(*pr._read(parent))['cycle']
    manifest, value = package(parent, prior)
    atomic_json(parent / 'final-draft/report.json', draft)
    atomic_json(parent / 'final-draft/recipe.json', recipe)
    for row in value['artifacts']:
        row.update(artifact_pin(Path(row['path'])))
    for row in value['changes_since_checkin2']:
        row['current_sha256'] = artifact_pin(Path(row['path']))['sha256']
    atomic_json(Path(manifest['path']), value)
    manifest = artifact_pin(Path(manifest['path']))
    judgment.open_final_cycle(parent, manifest=manifest, check_results='inputs/checks-final.json')
    reviewed = judgment.advance(parent, parent / 'current-final-roles', host=FakeHost(), model='control',
        reasoning_effort='high', max_output_tokens=1024, max_wall_seconds=30,
        claim_scope='original_task_completion', allow_control=True)
    assert reviewed['phase'] == 'final_results_reviewed'
    observed = final_results_review.gate(parent, manifest, report=draft['report_text'], recipe=recipe)
    assert not observed['unblinding_authorized']
    return recipe


def test_parent_review_and_exact_report_recipe_needed_for_final_acceptance(tmp_path, monkeypatch, observed_role_boundary):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch)
    recipe = report_fixture(tmp_path); recipe_pin = write(tmp_path / 'report-recipe.json', recipe)
    parent = tmp_path / 'final-review'; prq = {'rundir': str(parent), 'claim_scope': 'original_task_completion'}
    rp = request(tmp_path, cp, [out], report=recipe_pin)
    ready = tc.evaluate(rp, base_dir=tmp_path)
    final_doc = read_json(rp['path']); final_doc['parent_review'] = prq; rp = write(Path(rp['path']), final_doc)
    # Exact prospective completion record plus all sources, child evidence and
    # journal anchors are input to this separate parent review.
    review_run(parent, [rp['path'], *[p['path'] for p in ready['input_pins'] if p['path'] != rp['path']]], monkeypatch, scope='original_task_completion')
    with pytest.raises(ValueError, match='CHECK-IN 3'):
        tc.require_final(rp, base_dir=tmp_path)
    review_final_artifacts(parent, rp, recipe, tmp_path, monkeypatch)
    final = tc.require_final(rp, base_dir=tmp_path)
    assert final['parent_task_accepted'] and final['ready_for_parent_review']
    recipe.update(task_completion=rp, delivery='final')
    with pytest.raises(ValueError, match='exact parent CHECK-IN 3 binding'):
        sr.compose(recipe, base_dir=tmp_path)
    accepted_review = final['final_results_review']
    recipe['final_results_review'] = {
        'rundir': accepted_review['rundir'],
        'manifest': accepted_review['manifest'],
    }
    assert sr.compose(recipe, base_dir=tmp_path)['task_completion']['parent_task_accepted']
    recipe['title'] = 'A changed final delivery recipe'
    with pytest.raises(ValueError, match='delivery recipe'): sr.compose(recipe, base_dir=tmp_path)


def test_ordinary_final_gate_binds_completion_to_this_parent_review(tmp_path, monkeypatch, observed_role_boundary):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch)
    parent = tmp_path / 'final-review'
    parent.mkdir()
    recipe_pin = write(parent / 'report-recipe.json', report_fixture(parent))
    rp = request(parent, cp, [out], report=recipe_pin)
    ready = tc.evaluate(rp, base_dir=parent)
    doc = read_json(rp['path']); doc['parent_review'] = {'rundir': str(parent), 'claim_scope': 'original_task_completion'}
    final_pin = write(parent / 'inputs/task_completion.json', doc)
    review_run(parent, [final_pin['path'], *[p['path'] for p in ready['input_pins'] if p['path'] != rp['path']]], monkeypatch, scope='original_task_completion')
    assert pr.gate_errors(parent, 'final_task')
    review_final_artifacts(parent, final_pin, read_json(recipe_pin['path']), parent, monkeypatch)
    assert pr.gate_errors(parent, 'final_task') == []
    assert tc.final_gate(parent)['parent_task_accepted']
    from ravel.validation import verify_pack
    assert verify_pack.main(['verify_pack.py', str(parent), '--whole-task']) == 0
    doc['parent_review']['rundir'] = str(tmp_path / 'other-final-review')
    write(parent / 'inputs/task_completion.json', doc)
    assert pr.gate_errors(parent, 'final_task')


def test_scoped_delivery_and_mechanical_pack_do_not_close_original_goal(tmp_path, monkeypatch, capsys):
    _, cp = goal(tmp_path, clipped=True); out = resolved(tmp_path, cp, monkeypatch)
    assert pr.gate_errors(out['rundir'], 'delivery') == []
    assert pr.gate_errors(out['rundir'], 'final_task')
    from ravel.validation import verify_pack
    assert verify_pack.main(['verify_pack.py', out['rundir']]) == 0
    assert 'parent-task completion not assessed' in capsys.readouterr().out
    assert verify_pack.main(['verify_pack.py', out['rundir'], '--whole-task']) == 1


def test_published_schema_matches_closed_task_requirement_shape(tmp_path):
    from ravel.validation import validate_task_contract as validator
    c, _ = goal(tmp_path)
    c['task_requirements']['unreviewed_extension'] = 'not part of the task contract'
    assert validator._schema_errors(c, validator.SCHEMA, 'contract')
    del c['task_requirements']['unreviewed_extension']
    c['task_requirements']['assignments'][0]['coverage'][0]['extra'] = 1
    assert validator._schema_errors(c, validator.SCHEMA, 'contract')


def test_contract_cannot_choose_existing_child_scope_as_parent_decision(tmp_path):
    c, _ = goal(tmp_path)
    c['task_requirements']['parent_acceptance_scope'] = 'source_bound_published_summary_delivery'
    assert validate(c)
    with pytest.raises(ValueError, match='reserved original_task_completion'):
        tc.validate_requirements(c)


def test_unrelated_old_parent_cycle_cannot_close_new_completion(tmp_path, monkeypatch):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch)
    parent = tmp_path / 'old-parent'; review_run(parent, [], monkeypatch, scope='original_task_completion')
    recipe_pin = write(tmp_path / 'recipe.json', report_fixture(tmp_path))
    rp = request(tmp_path, cp, [out], report=recipe_pin, parent_review={'rundir': str(parent), 'claim_scope': 'original_task_completion'})
    with pytest.raises(ValueError, match='capture completion'): tc.require_final(rp, base_dir=tmp_path)


def test_missing_or_duplicate_coverage_cannot_hide_an_assigned_obligation(tmp_path):
    _, cp = goal(tmp_path); out = child(tmp_path, cp); out['coverage'].pop()
    with pytest.raises(ValueError, match='complete assignment'): tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)


def test_original_prompt_span_and_assignment_identity_are_checked(tmp_path):
    c, cp = goal(tmp_path); c['task_requirements']['obligations'][0]['evidence'][0]['text'] = 'invented user request'
    assert validate(c)
    binding = {'contract': cp, 'assignment_id': 'nonexistent'}
    with pytest.raises(ValueError): tc.binding_projection(binding, base_dir=tmp_path)


def test_registered_parent_approval_makes_exact_instruction_effective(tmp_path):
    from types import SimpleNamespace
    c, cp = goal(tmp_path); original = c['task_requirements']['obligations'][2]
    instruction = 'Only ATLAS is now required; retain the original CMS request as superseded.'
    amendment = {'schema_version': 1, 'kind': 'task-scope-instruction', 'authority': 'direct-user-instruction',
        'prompt_sha256': c['task_requirements']['prompt_sha256'], 'instruction': instruction,
        'changes': [{'obligation_id': 'cms', 'before_sha256': tc.ce.digest(original), 'disposition': 'withdraw',
                     'statement': 'CMS explicitly withdrawn', 'criteria': None}]}
    ap = write(tmp_path / 'instruction.json', amendment); c['task_requirements']['amendments'] = [ap]
    cp = write(Path(cp['path']), c); parent = Path(cp['path']).parent.parent
    checkin = {'schema_version': 1, 'kind': 'checkin1', 'sections': {
        'i': 'synthetic original request control', 'i-b': 'exact census', 'ii': 'scoped summary',
        'iii': {'plan': 'none', 'waypoint': 'source-only'}, 'iv': 'no compute',
        'v': [{'id': 'F1', 'text': 'synthetic control, no authenticated human vote'}], 'vi': ['answer', 'ask', 'propose']}}
    write(parent / 'inputs/checkin1.json', checkin)
    write(parent / 'inputs/cost_preflight.json', {'schema_version': 1, 'generated_by': 'cost_preflight.py', 'mode': 'none', 'walltime_h': [0, 0]})
    assert workflow_state.cmd_approve(SimpleNamespace(rundir=str(parent), plan='none', quote=instruction)) == 0
    result = tc.evaluate(request(tmp_path, cp), base_dir=tmp_path)
    assert result['scope_changes'][0]['effective_authorization']
    assert result['obligation_census'][2]['state'] == 'withdrawn_by_instruction'
    assert result['obligation_census'][2]['original'] == original
    assert not result['parent_task_accepted'] and not result['authority_origin_authenticated']
    # Approval is bound to actual source bytes, not just an actor field.
    Path(ap['path']).write_text('{}\n')
    assert workflow_state.verify_approval(str(parent))
    with pytest.raises(ValueError): tc.evaluate(request(tmp_path, cp), base_dir=tmp_path)


def test_graph_binding_and_host_context_keep_full_goal_and_refuse_drift(tmp_path):
    _, cp = goal(tmp_path); binding = {'contract': cp, 'assignment_id': 'summary-child'}
    node = {'id': 'propose', 'kind': 'model', 'role': 'proposer', 'depends_on': [], 'inputs': [],
        'packet': None, 'action': 'responses', 'parameters': {}, 'max_attempts': 1}
    spec = {'schema_version': 1, 'graph_id': 'parent-aware', 'goal_binding': binding,
        'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 20, 'max_wall_seconds': 30, 'max_reworks': 0}, 'nodes': [node]}
    root = tmp_path / 'graph'; state = agent_graph.create(root, spec)
    assert state['parent_task']['original_request'] == PROMPT and not state['parent_task']['parent_task_complete']
    req = agent_graph._request(spec, state, node, '0' * 64)
    context = agent_host.AgentHost()._context(node, req, {})
    assert context['parent_task']['original_request'] == PROMPT
    assert len(context['parent_task']['original_obligations']) == 4
    Path(cp['path']).write_text('{}\n')
    with pytest.raises(ValueError): agent_graph.status(root)


def test_genuine_child_role_context_includes_original_parent_census(tmp_path, monkeypatch):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch)
    manifest = review_context.create(out['rundir'], 'critic', tmp_path / 'critic-context')
    assert manifest['parent_task']['original_request'] == PROMPT
    assert [r['id'] for r in manifest['parent_task']['original_obligations']] == ['original-request', 'atlas', 'cms', 'domain']


def test_actual_ordinary_plan_captures_parent_contract_without_worker(tmp_path, monkeypatch):
    from test_science_review_envelope import specification
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'source-only no-child hardware description')
    _, cp = goal(tmp_path); spec = specification(tmp_path)
    spec['goal_binding'] = {'contract': cp, 'assignment_id': 'summary-child'}
    source = tmp_path / 'study.json'; atomic_json(source, spec)
    rd = tmp_path / 'planned-study'; proposal = science.plan(rd, source)
    assert cp['path'] in proposal['stages'][0]['inputs']
    assert science.verify_plan(rd)['stage_binding'] == proposal['stage_binding']
    status = science.packet(rd)
    assert status['parent_task']['original_request'] == PROMPT
    assert not status['parent_task']['parent_task_complete']
    assert not (rd / 'execution_attempt.json').exists()
    Path(cp['path']).write_text('{}\n')
    with pytest.raises(ValueError): science.verify_plan(rd)


def test_successful_facts_alone_do_not_name_parent_acceptance(tmp_path):
    result = sr.compose(report_fixture(tmp_path), base_dir=tmp_path)
    assert result['declared_fact_census_complete'] and result['task_completion'] is None
    assert result['scientific_acceptance'] is False


def test_finer_census_cannot_drop_whole_original_request(tmp_path):
    c, _ = goal(tmp_path)
    c['task_requirements']['obligations'] = [c['task_requirements']['obligations'][1]]
    c['task_requirements']['assignments'] = []
    assert validate(c)


def test_narrow_parent_scope_cannot_become_whole_goal_by_snapshotting_all_inputs(tmp_path, monkeypatch):
    _, cp = goal(tmp_path); out = resolved(tmp_path, cp, monkeypatch)
    recipe_pin = write(tmp_path / 'recipe.json', report_fixture(tmp_path))
    rp = request(tmp_path, cp, [out], report=recipe_pin)
    ready = tc.evaluate(rp, base_dir=tmp_path)
    parent = tmp_path / 'narrow-parent'
    doc = read_json(rp['path']); doc['parent_review'] = {'rundir': str(parent), 'claim_scope': 'diagnostic'}
    rp = write(Path(rp['path']), doc)
    review_run(parent, [rp['path'], *[p['path'] for p in ready['input_pins'] if p['path'] != rp['path']]], monkeypatch)
    with pytest.raises(ValueError, match='whole-goal acceptance scope'): tc.require_final(rp, base_dir=tmp_path)


@pytest.mark.parametrize('prompt', ['Generate 10 parton events from a supplied process card.',
                                  'Evaluate CLs using a supplied likelihood.',
                                  'Invent a new anomaly detection method.',
                                  'Measure a novel supplied covariance ratio.'])
def test_every_route_preserves_the_whole_original_request(prompt):
    contract = route_prompt.route(prompt)
    original = tc.initial_requirements(prompt)
    census = contract['task_requirements']
    assert census['completion_epoch'] == 1
    assert census['obligations'][0] == original['obligations'][0]
    assert {k: v for k, v in census.items() if k not in ('obligations', 'assignments', 'completion_epoch')} == {
        k: v for k, v in original.items() if k not in ('obligations', 'assignments')}
    assert contract['prompt'] == prompt


def test_actual_public_readonly_cli_reports_open_task_and_refuses_final(tmp_path, capsys):
    from ravel import cli
    _, cp = goal(tmp_path); rp = request(tmp_path, cp)
    assert cli.main(['task-completion', '--request', rp['path'], '--base', str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['unmet_obligation_ids'] == ['original-request', 'atlas', 'cms', 'domain']
    with pytest.raises(SystemExit) as exc:
        cli.main(['task-completion', '--request', rp['path'], '--base', str(tmp_path), '--require-final'])
    assert exc.value.code == 1
