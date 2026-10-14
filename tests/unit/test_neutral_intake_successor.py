"""Two source findings: actual ordinary API controls, authored not executed."""
import synthetic_identifiers as syn
from copy import deepcopy
import json

import pytest

from ravel import cli
from ravel.validation.validate_task_contract import validate
from ravel.workflow import current_state, intake, route_prompt
from ravel.workflow import research_orchestrator as orchestration, research_coordinator_decisions as decisions
from test_benchmark_neutral_intake import LABELS, open_settings


@pytest.mark.parametrize('qualifier', [
    'particle-level', 'truth-level', 'generator-level', 'no detector',
    'parton-level', 'likelihood-only', 'detector simulation', 'fiducial',
    'unbinned', 'signed', 'blinded', 'precision', 'covariance', 'without shower',
])
def test_claimed_identifier_cannot_erase_scientific_qualifiers(qualifier):
    prompt='Context label: '+qualifier+('\nReproduce ' + syn.analysis(1) + '.')
    assert intake.routing_text(prompt)==prompt and intake.routing_context_unresolved(prompt)
    result=route_prompt.route(prompt)
    assert result['task_mode']=='unsupported' and result['compute_plan']=='none'
    assert result['prompt']==prompt and result['approval_required'] is True
    assert result['task_requirements']['obligations'][0]['statement']==prompt
    assert any('grounded --interpretation' in row for row in result['blocking'])


@pytest.mark.parametrize('key', ['Benchmark label', 'Suite name', 'Task ID', 'Source label', 'Provenance name'])
def test_scientific_qualifier_preservation_is_not_conditioned_on_metadata_key(key):
    prompt=key+(': particle-level\nReproduce ' + syn.analysis(1) + '.')
    assert intake.routing_text(prompt)==prompt
    assert intake.routing_context_unresolved(prompt)
    assert route_prompt.route(prompt)['task_mode']=='unsupported'


@pytest.mark.parametrize('qualifier', ['particle-level', 'truth-level', 'generator-level', 'no detector'])
def test_grounded_qualifier_recovery_preserves_actual_detector_mode_and_whole_task(tmp_path, qualifier):
    prompt='Context label: '+qualifier+('\nReproduce ' + syn.analysis(1) + '.')
    interpretation={'schema_version':1,'prompt_sha256':intake.prompt_hash(prompt),'kind':'reproduce',
        'objective':prompt,'requested_outputs':['Complete original reproduction and validation with the declared approximation'],
        'evidence':[{'start':0,'end':len(prompt),'text':prompt}],
        'unresolved':['Actual particle-level input, approximation validation and full original requested outputs']}
    interpreted=tmp_path/'interpretation.json';interpreted.write_text(json.dumps(interpretation)+'\n')
    root=tmp_path/'parent'
    assert cli.main(['initiate','--prompt',prompt,'--interpretation',str(interpreted),'--out',str(root)])==0
    path=root/'inputs/task_contract.json';contract=json.loads(path.read_text())
    assert contract['task_mode']=='reproduce' and contract['detector_mode']=='particle-level'
    assert contract['intake']['source']=='host-agent' and contract['prompt']==prompt
    handoff=current_state.build_packet(root)['intake_handoff']
    assert handoff['task_mode']==handoff['task_kind']=='reproduce'
    assert handoff['original_request']==prompt and handoff['compute_authorized'] is False
    settings=tmp_path/'settings.json';settings.write_text(json.dumps(open_settings())+'\n')
    assert cli.main(['research-orchestrate','prepare','--parent-contract',str(path),
                    '--settings',str(settings),'--out',str(tmp_path/'prepared')])==0
    request=decisions.request(orchestration._pin(tmp_path/'prepared/request.json'))
    assert request['handoff']==handoff and request['campaign']==open_settings()['campaign']
    wrong=deepcopy(interpretation);wrong['prompt_sha256']='0'*64
    with pytest.raises(ValueError):route_prompt.route(prompt,wrong)
    assert not (root/'inputs/checkin1_approval.json').exists()


@pytest.mark.parametrize('head', [
    'Survey', 'Please survey', 'I want to survey', 'I would like you to survey',
    'Could you survey', 'Would you please survey',
])
@pytest.mark.parametrize('label', [None, *LABELS])
def test_explicit_survey_action_precedes_incidental_constraint_language(head, label):
    question=head+' which analyses constrain the supplied physics scenario.'
    prompt=question if label is None else 'Suite name: '+label+'\n'+question
    result=route_prompt.route(prompt)
    assert result['task_mode']=='survey' and result['compute_plan']=='none'
    assert result['prompt']==prompt and result['approval_required'] is True
    assert result['task_requirements']['obligations'][0]['statement']==prompt
    assert validate(result)==[]


@pytest.mark.parametrize('question,expected', [
    ('Survey the entire mass and coupling domain, including all constraints.', 'survey'),
    ('Survey constraints on the supplied model.', 'survey'),
    ('Use survey results to constrain the supplied model.', 'reinterpret'),
    ('Reinterpret the supplied limits on the model.', 'reinterpret'),
    ('Reproduce the published survey and validate all constraints.', 'reproduce'),
    ('Do not survey constraints; reinterpret the supplied limits on the model.', 'reinterpret'),
    ('Do not survey the scenario.', 'unsupported'),
    ('Scan masses over 200 to 500 GeV and retain all requested constraints.', 'scan'),
])
def test_action_and_noun_counterfactuals_preserve_original_operation(question, expected):
    result=route_prompt.route(question)
    assert result['task_mode']==expected and result['prompt']==question
    assert result['approval_required'] is True


@pytest.mark.parametrize('label', [None, *LABELS])
def test_original_survey_witness_reaches_actual_cli_handoff_and_prepare_without_approval(tmp_path,label):
    question='Survey which analyses constrain the supplied physics scenario.'
    prompt=question if label is None else 'Benchmark label: '+label+'\n'+question
    root=tmp_path/'parent'
    assert cli.main(['initiate','--prompt',prompt,'--out',str(root)])==0
    path=root/'inputs/task_contract.json';contract=json.loads(path.read_text())
    handoff=current_state.build_packet(root)['intake_handoff']
    assert contract['task_mode']==handoff['task_kind']==handoff['task_mode']=='survey'
    assert handoff['original_request']==prompt
    settings=tmp_path/'settings.json';settings.write_text(json.dumps(open_settings())+'\n')
    assert cli.main(['research-orchestrate','prepare','--parent-contract',str(path),
                    '--settings',str(settings),'--out',str(tmp_path/'prepared')])==0
    request=decisions.request(orchestration._pin(tmp_path/'prepared/request.json'))
    assert request['handoff']==handoff
    assert json.loads(path.read_text())==contract
    assert handoff['compute_authorized'] is handoff['parent_task_accepted'] is False
    assert not (root/'inputs/checkin1_approval.json').exists()


def test_explicit_survey_word_in_claimed_identifier_requires_grounded_intent():
    prompt='Source label: survey constraints\nCalculate 2+2.'
    assert intake.routing_text(prompt)==prompt and intake.routing_context_unresolved(prompt)
    result=route_prompt.route(prompt)
    assert result['task_mode']=='unsupported' and result['prompt']==prompt


@pytest.mark.parametrize('name', LABELS)
def test_opaque_identifiers_and_scoped_operations_stay_unchanged(name):
    for question,mode in [('Calculate 2+2.','calculation'),
                          ('Generate a parton-level generation-only sample.','generate'),
                          ('Evaluate the supplied likelihood-only workspace.','likelihood')]:
        prompt='Context label: '+name+'\n'+question
        assert intake.routing_text(prompt).strip()==question
        result=route_prompt.route(prompt)
        assert result['task_mode']==mode and result['prompt']==prompt
        assert result['compute_plan']=='none' and result['approval_required'] is True
