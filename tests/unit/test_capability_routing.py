"""Portable source/ordinary-tool controls; no engine/provider/model execution."""
import synthetic_identifiers as syn
from copy import deepcopy
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess

import pytest

from ravel import cli
from ravel.workflow import capability_routing as cr, intake, route_prompt, agent_graph, agent_host
from ravel.workflow.execution import digest
from ravel.validation.validate_task_contract import validate
from shipped_catalogue import shipped_operations


@pytest.fixture(autouse=True)
def no_external_launch(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('source controls launched a process'))
    # Metadata-only CLI status invokes Python's processor helper (uname -p).
    # Keep that field explicitly unqualified in these no-process source controls.
    monkeypatch.setattr(platform, 'platform', lambda: 'unqualified-source-control-platform')


def span(prompt):
    return {'start': 0, 'end': len(prompt), 'text': prompt}


def intent(prompt, mode, scope='component'):
    return {'mode': mode, 'basis': span(prompt), 'scope': scope}


def pin(path):
    return {'path': str(path.absolute()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False) + '\n')
    return pin(path)


def test_catalogue_reads_all_actual_current_dispatches_including_new_modes():
    catalog = cr.catalogue()
    from ravel.workflow.science import MODES
    assert [r['mode'] for r in catalog['operations']] == list(MODES)
    assert all(r['status'] == 'source_present_not_admitted' for r in catalog['operations'])
    assert set(shipped_operations(('checkmate-events', 'published-summary', 'ratio-measurement', 'native-likelihood',
                                   'continuous-fit'))) <= set(MODES)
    analyze = next(r for r in catalog['operations'] if r['mode'] == 'analyze')
    assert {'native-construction', 'routine-build', 'analysis-ir'} <= analyze['variants'].keys()
    assert not catalog['compute_authorized'] and not catalog['physics_validated']


@pytest.mark.parametrize('mode', ['analysis-response-features', 'classifier-inputs'])
def test_finite_mode_derived_catalogue_matches_real_ordinary_adapter(mode):
    from ravel.workflow import science
    row = next(row for row in cr.catalogue()['operations'] if row['mode'] == mode)
    implementation = science.adapter({'mode':mode})
    assert row['module'] == implementation.__name__
    assert row['source'] == pin(Path(implementation.__file__))
    assert row['entrypoints'] == ['inputs', 'run', 'validate']
    assert row['execution_evidence'] == 'not_inferred_from_source'


def test_catalogue_does_not_evaluate_opaque_dispatch_expression(tmp_path, monkeypatch):
    import importlib
    root = tmp_path/'source'; source = Path(cr.__file__).resolve().parents[3]
    shutil.copytree(source/'src', root/'src')
    dispatcher = root/'src/ravel/workflow/science.py'
    original = dispatcher.read_text()
    expression = "'ravel.physics.'+spec['mode'].replace('-','_')"
    assert expression in original
    dispatcher.write_text(original.replace(expression, "'ravel.physics.'+must_not_execute(spec['mode'])"))
    def deny(*args, **kwargs):
        raise AssertionError('source discovery imported a dispatch module')
    monkeypatch.setattr(importlib, 'import_module', deny)
    rows = {row['mode']:row for row in cr.catalogue(root)['operations']}
    for mode in ('analysis-response-features', 'classifier-inputs'):
        assert rows[mode]['status'] == 'source_dispatch_unresolved'
    assert rows['ratio-measurement']['status'] == 'source_present_not_admitted'


@pytest.mark.parametrize('prompt,modes', [
    ('From supplied numerator and denominator histograms and joint covariance, compute the ratio and propagated covariance.', {'ratio-measurement', 'derived-quantities'}),
    ('Construct an unfamiliar Rivet analysis for this paper, compile it and validate every published observable.', {'analyze'}),
    ('Normalize the event groups, rebin and compose the full covariance, then build the SR/CR Poisson model.', {'group-normalization', 'group-composition', 'statistical-model'}),
    ('Reproduce the multichannel unbinned template fit with the supplied workspace without new events.', {'native-likelihood', 'published-model', 'hs3-likelihood'}),
    ("Construct a summary plot of ATLAS+CMS HVT Z'->WW searches below 500 GeV.", {'published-summary'}),
    ('Assess toponium as a heavy Higgs using other searches and published limits.', {'published-summary'}),
    ('Check fixed-vector likelihood parity and verify the retained conditional-profile candidates of my fit.', {'likelihood-parity'}),
])
def test_unfamiliar_positive_questions_find_current_source_without_shrinking(prompt, modes):
    result = cr.plan(prompt)
    assert result['original_request'] == prompt and result['original_request_sha256'] == intake.prompt_hash(prompt)
    assert modes <= {c['mode'] for c in result['candidates']}
    assert not result['parent_goal_replaced'] and result['parent_goal_acceptance'] == 'not_assessed'
    assert not result['compute_authorized']
    assert all(c['scope'] == 'component' for c in result['candidates'])
    assert {'discover', 'retrieve', 'resolve', 'reuse-or-adapt', 'qualify'} <= {a['stage'] for a in result['next_actions']}


@pytest.mark.parametrize('prompt,bound', [
    ('Expand semi-visible-jet expected limits across dark pion/dark rho masses and assess a hypothetical tagger.', 'svj-recipe'),
    ('Check fixed-vector likelihood parity and verify the retained conditional-profile candidates of my fit.', 'likelihood-candidate-check'),
])
def test_source_bound_adapters_are_offered_only_when_selected(prompt, bound):
    assert bound not in {c['mode'] for c in cr.plan(prompt)['candidates']}
    selected = prompt + f' Use the {bound} operation.'
    candidate = next(c for c in cr.plan(selected)['candidates'] if c['mode'] == bound)
    assert candidate['applicability']['scope'] == 'source-bound' and 'not a general operation' in candidate['reason']


def test_fallback_unknown_is_an_open_parent_not_a_refusal(tmp_path, capsys):
    # A request with a scientific object that no rule recognises is an open research parent
    # (rule D5): exit 0, no compute, every stage and tool kept as an obligation.
    prompt = 'Construct an unfamiliar Rivet analysis and validate all its source observables.'
    result = cr.plan(prompt)
    assert result['legacy_draft']['task_mode'] == 'research'
    assert result['legacy_draft']['compute_plan'] == 'none' and result['legacy_draft']['blocking'] == []
    assert result['classification_status'] == 'open_parent'
    output = tmp_path / 'not-an-authorized-run'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(output)]) == 0
    captured = capsys.readouterr()
    assert 'next_route=open' in captured.out and 'analyze' in captured.out and 'rule=D5' in captured.out
    recovery = json.loads((output / 'inputs/capability_recovery.json').read_text())
    assert recovery['classification_status'] == 'open_parent'
    assert any(c['mode'] == 'analyze' for c in recovery['candidates'])
    handoff = json.loads((output / 'inputs/intake_handoff.json').read_text())
    assert handoff['route'] == 'open' and handoff['compute_authorized'] is False
    contract = json.loads((output / 'inputs/task_contract.json').read_text())
    assert any(o['criteria'].get('tool') == 'Rivet' for o in contract['task_requirements']['obligations'])
    assert not (output / 'inputs/checkin1_approval.json').exists()


def test_genuine_hold_is_recovery_not_asserted_impossibility(tmp_path, capsys):
    prompt = 'Context label: particle-level\nConstruct an unfamiliar Rivet analysis and validate its observables.'
    result = cr.plan(prompt)
    assert result['legacy_draft']['task_mode'] == 'unsupported'
    assert result['classification_status'] == 'needs_intent_resolution'
    assert 'grounded --interpretation' in result['legacy_draft']['blocking'][0]
    output = tmp_path / 'held-run'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(output)]) == 1
    captured = capsys.readouterr()
    assert 'needs_intent_resolution' in captured.out and 'would make it possible' in captured.out
    assert json.loads((output / 'inputs/capability_recovery.json').read_text())['classification_status'] == \
        'needs_intent_resolution'
    assert not (output / 'inputs/checkin1_approval.json').exists()


def test_supported_actual_cli_persists_exact_recovery_without_approval(tmp_path):
    prompt = "Consider HVT. Construct a summary plot of ATLAS+CMS searches for Z'->WW below 500 GeV."
    output = tmp_path / 'new-intake'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(output)]) == 0
    recovery = json.loads((output / 'inputs/capability_recovery.json').read_text())
    assert recovery['original_request'] == prompt
    assert (output / 'request.txt').read_text() == prompt
    assert not (output / 'inputs/checkin1_approval.json').exists()


@pytest.mark.parametrize('prompt', [
    'Calculate expected 5 sigma discovery sensitivity of the supplied likelihood; no discovery occurred.',
    'Using the supplied likelihood, calculate expected luminosity needed for 5 sigma discovery sensitivity; do not claim discovery occurred.',
    'Prepare prospective significance of this signal under explicit background scenarios.',
])
def test_prospective_significance_preserves_metric_without_exclusion_rewrite(prompt):
    result = cr.plan(prompt)
    assert result['prospective_significance']
    assert result['legacy_draft']['task_mode'] != 'unsupported'
    assert result['legacy_draft']['compute_plan'] == 'none'
    assert result['legacy_draft']['intake']['kind'] == 'method_study'
    assert 'expected CLs is not a replacement' in ' '.join(result['legacy_draft']['required_user_inputs'])
    assert validate(result['legacy_draft']) == []


@pytest.mark.parametrize('prompt,claim', [
    # An outcome-neutral request to discover something is a research question; the same
    # request phrased as a demand to claim the discovery presupposes the outcome and is held.
    pytest.param('Discover a new particle at 5 sigma.', 'Claim discovery of a new particle at 5 sigma.',
                 id='Discover a new particle at 5 sigma.'),
    pytest.param('Claim discovery of a new resonance using my expected sensitivity.', None,
                 id='Claim discovery of a new resonance using my expected sensitivity.'),
    pytest.param('Calculate the significance of the excess in private ATLAS data.', None,
                 id='Calculate the significance of the excess in private ATLAS data.'),
])
def test_actual_unavailable_discovery_claim_remains_held(prompt, claim):
    result = cr.plan(prompt)
    if claim is not None:
        assert not intake.requests_discovery(prompt) and intake.research_request(prompt)
        assert result['classification_status'] == 'draft_route_requires_admission'
        assert result['legacy_draft']['task_mode'] == 'research'
        assert result['legacy_draft']['intake']['kind'] == 'research'
        assert result['legacy_draft']['compute_plan'] == 'none' and result['legacy_draft']['blocking'] == []
        assert result['legacy_draft']['approval_required'] is True
        assert not result['compute_authorized'] and not result['physics_validated']
        assert not result['parent_goal_replaced'] and result['original_request'] == prompt
        assert validate(result['legacy_draft']) == []
        assert intake.requests_discovery(claim)
        result = cr.plan(claim)
    assert result['classification_status'] == 'claim_boundary'
    assert result['legacy_draft']['task_mode'] == 'unsupported'
    assert not result['compute_authorized']
    assert 'do not replace' in result['legacy_draft']['blocking'][0]


def test_svj_same_luminosity_does_not_invent_luminosity_input():
    prompt = 'Expand the Run 2 semi-visible-jet expected limits across masses and assess a hypothetical tagger.'
    contract = route_prompt.route(prompt)
    assert contract['task_mode'] == 'projection'
    assert not any('target luminosity' in x for x in contract['required_user_inputs'])
    future = route_prompt.route(('Project expected limits to future luminosity for ' + syn.analysis(1) + '.'))
    assert any('target luminosity' in x for x in future['required_user_inputs'])


def test_generation_shower_reinterpretation_is_not_replaced_by_supplied_component():
    prompt = ('Generate new events for this model, shower them, and reinterpret ' + syn.analysis(1) + '.')
    result = cr.plan(prompt, intents=[intent(prompt, 'analyze')])
    assert result['legacy_draft']['task_mode'] == 'reinterpret'
    assert result['original_request'] == prompt and result['candidates'][0]['scope'] == 'component'
    assert 'does not replace generation' in ' '.join(a['purpose'] for a in result['next_actions'])


def test_supplied_template_reproduction_does_not_infer_new_hard_events():
    prompt = ('Reproduce the template fit of ' + syn.analysis(28) + ' with the supplied workspace without new events.')
    contract = route_prompt.route(prompt)
    assert contract['task_mode'] == 'reproduce' and contract['stat_mode'] == 'shape-fit'
    assert contract['compute_plan'] == 'none' and validate(contract) == []


@pytest.mark.parametrize('kind', sorted(cr.FINDINGS))
def test_recovery_findings_remain_distinct_actions_and_original_obligations(kind):
    result = cr.plan('Compute the requested conditional model result.', findings=[{'kind': kind, 'detail': 'Explicit held/source finding.', 'evidence': []}])
    assert result['findings'][0]['kind'] == kind and not result['parent_goal_replaced']
    assert not result['compute_authorized']
    last = result['next_actions'][-1]['purpose']
    if kind == 'private-unavailable-input': assert 'cannot' in last and 'unmet' in last
    if kind == 'off-grid': assert 'Keep exact requested coordinates' in last
    if kind == 'optional-figure': assert 'stay unmet' in last


@pytest.mark.parametrize('fault', ['wrong-span', 'wrong-request', 'absent-mode', 'scope', 'unknown-finding', 'changed-fact', 'boolean-span'])
def test_unbound_or_invented_recovery_inputs_refuse(tmp_path, fault):
    prompt = 'Compute the supplied ratio.'; i = intent(prompt, 'ratio-measurement'); kwargs = {'intents': [i]}
    if fault == 'wrong-span': i['basis']['text'] = 'invented'
    elif fault == 'boolean-span': i['basis']['start'] = False
    elif fault == 'wrong-request': kwargs = {'contract': route_prompt.route('Survey another model.')}
    elif fault == 'absent-mode': i['mode'] = 'invented-full-discovery'
    elif fault == 'scope': i['scope'] = 'accepted'
    elif fault == 'unknown-finding': kwargs = {'findings': [{'kind': 'invented-physics', 'detail': 'no', 'evidence': []}]}
    else:
        p = tmp_path / 'fact.txt'; p.write_text('initial'); binding = pin(p); p.write_text('changed')
        kwargs = {'findings': [{'kind': 'off-grid', 'detail': 'source-bound map scope', 'evidence': [binding]}]}
    with pytest.raises(ValueError): cr.plan(prompt, **kwargs)


def test_actual_adapter_validation_and_inputs_recover_supplied_ratio(tmp_path):
    prompt = 'From supplied histograms and joint covariance, compute the ratio.'
    document = tmp_path / 'ratio.json'
    component = lambda value: {'bin_ids': ['a'], 'values': [value], 'units': ['fb']}
    data = {'schema_version': 1, 'analysis_id': 'synthetic-one-bin-ratio',
            'basis': [{'id': 'a', 'observable': 'pt', 'axis': {'name': 'pt', 'unit': 'GeV'}, 'low': [10.], 'high': [20.]}],
            'data': {'bin_ids': ['a'], 'values': [2.], 'unit': '1'},
            'experimental_covariance': {'bin_ids': ['a'], 'matrix': [[1.]], 'unit': '(1)^2'},
            'prediction': {'kind': 'numerator_denominator', 'sm_numerator': component(4.), 'sm_denominator': component(2.),
                           'bsm_numerator': component(1.), 'bsm_denominator': component(1.), 'coefficient_convention': 'positive_additive',
                           'signal_strength_domain': [0., 2.], 'baseline_convention': 'literal_num_den',
                           'published_sm_ratio': {'bin_ids': ['a'], 'values': [2.], 'unit': '1'}},
            'applicability': {'scope': 'conditional_fixed_prediction_diagnostic', 'prompt_lepton_met_control_contamination': 'unresolved synthetic',
                              'dilepton_efficiency_assumption': 'requires review', 'theory_covariance': 'not supplied'},
            'sources': {'measurement': 'synthetic', 'covariance': 'supplied synthetic', 'prediction': 'synthetic', 'approximation': 'fixed Gaussian'}}
    write(document, data)
    spec = {'schema_version': 1, 'mode': 'ratio-measurement', 'source': 'synthetic source-only input preparation',
            'assumptions': ['No numerical inference, applicability or covariance calibration is claimed.'],
            'max_seconds': 1, 'approval_mode': 'physicist',
            'task': {'schema_version': 1, 'input': str(document), 'signal_strength': 1}}
    result = cr.assess_candidate(prompt, intent(prompt, spec['mode']), spec, base_dir=tmp_path)
    assert result['status'] == 'specification_and_inputs_checked' and result['inputs'] == [pin(document)]
    from ravel.physics import ratio_measurement
    prepared = ratio_measurement.prepare(data, spec['task'])
    assert list(prepared['prediction']) == pytest.approx([5 / 3])
    assert not result['compute_authorized'] and result['parent_goal_acceptance'] == 'not_assessed'
    spec['task']['signal_strength'] = True
    held = cr.assess_candidate(prompt, intent(prompt, spec['mode']), spec, base_dir=tmp_path)
    assert held['status'] == 'needs_input_or_adapter_repair'


class Control:
    def __init__(self): self.calls = []
    def cancelled(self): return False
    def check_cancelled(self): pass
    def call(self, label, kind, request, function, output_tokens=0): self.calls.append(label); return function()


def host_node(path, role='proposer'):
    inputs = [{'id': 'request', **pin(path)}]
    node = {'id': 'route', 'kind': 'tool', 'role': role, 'depends_on': [], 'inputs': inputs, 'packet': None,
            'action': 'capability-routing', 'parameters': {'request_input': 'request'}, 'max_attempts': 1}
    request = {'schema_version': 1, 'graph_id': 'route-control', 'graph_revision': 'a' * 64, 'node_id': 'route',
               'generation': 1, 'node_sha256': digest(node), 'request_id': 'b' * 64, 'input_artifacts': inputs, 'packet': None, 'dependencies': []}
    return node, request


def test_ordinary_graph_accounts_recovery_reuses_and_rejects_source_drift(tmp_path, monkeypatch):
    path = tmp_path / 'request.json'; write(path, {'prompt': 'Compute the supplied ratio and covariance.', 'intents': [], 'findings': []})
    node, _ = host_node(path)
    spec = {'schema_version': 1, 'graph_id': 'route-control', 'budget': {'max_nodes': 1, 'max_calls': 1,
            'max_output_tokens': 0, 'max_wall_seconds': 30, 'max_reworks': 0}, 'nodes': [node]}
    graph = tmp_path / 'graph'; agent_graph.create(graph, spec); host = agent_host.AgentHost()
    result = agent_graph.execute(graph, host, workers=1)
    assert result['complete'] and result['usage']['calls'] == 1
    assert agent_graph.execute(graph, host, workers=1)['usage']['calls'] == 1
    changed = tmp_path / 'source-copy'
    shutil.copytree(Path(cr.__file__).resolve().parents[3] / 'src', changed / 'src')
    source = changed / 'src/ravel/physics/ratio_measurement.py'; source.write_text(source.read_text() + '\n# changed actual source control\n')
    original = cr.catalogue
    monkeypatch.setattr(cr, 'catalogue', lambda source_root=None: original(changed))
    retained = agent_graph.status(graph)
    with pytest.raises(agent_graph.GraphError, match='^completed generation source/request/host differs; explicit rework required$'): agent_graph.execute(graph, host, workers=1)
    # The refusal precedes any reservation: no call is charged and the completed generation is untouched.
    assert agent_graph.status(graph) == retained and retained['usage']['calls'] == 1


@pytest.mark.parametrize('role', ['critic', 'verifier'])
def test_blinded_reviews_cannot_receive_router_constructor_context(tmp_path, role):
    path = tmp_path / 'request.json'; write(path, {'prompt': 'Compute ratio.', 'intents': [], 'findings': []})
    node, request = host_node(path, role)
    with pytest.raises(agent_host.HostFailure): agent_host.AgentHost().execute(node, request, Control())


def test_host_does_not_read_unpresented_finding_evidence(tmp_path):
    source = tmp_path / 'private-source.txt'; source.write_text('held source')
    path = tmp_path / 'request.json'; write(path, {'prompt': 'Compute ratio.', 'intents': [],
        'findings': [{'kind': 'private-unavailable-input', 'detail': 'held physical input', 'evidence': [pin(source)]}]})
    node, request = host_node(path); control = Control()
    with pytest.raises(agent_host.HostFailure, match='explicit graph input'):
        agent_host.AgentHost().execute(node, request, control)
    assert not control.calls
