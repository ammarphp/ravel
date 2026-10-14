"""``ravel inference``: examples, checks and study specifications without computation."""
import json

import pytest

from ravel import cli
from ravel.physics.inference import MODES, cli as inference_cli
from ravel.workflow import science


def test_focused_command_is_registered():
    assert cli.FOCUSED_COMMANDS['inference'][0] == 'physics.inference.cli'


@pytest.mark.parametrize('mode', MODES)
def test_every_example_checks_and_runs(mode, tmp_path, capsys):
    assert cli.main(['inference', 'example', '--mode', mode]) == 0
    doc = json.loads(capsys.readouterr().out)
    path = tmp_path / f'{mode}.json'
    path.write_text(json.dumps(doc))
    assert cli.main(['inference', 'check', '--mode', mode, '--input', str(path)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked['compute_authorized'] is False and checked['inputs'][0]['path'] == str(path)
    module = science.adapter({'mode': mode, 'task': {}})
    result = module.run({'input': str(path)}, tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed', result


def test_spec_writes_a_plannable_schema_two_specification(tmp_path, capsys):
    path = tmp_path / 'formula.json'
    path.write_text(json.dumps(inference_cli.example('formula-grid')))
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps({'schema_version': 1, 'policy': {
        'schema_version': 1, 'actors': {'proposer': 'p', 'executor': 'e', 'physics_critic': 'c',
                                        'skeptical_verifier': 'v', 'physics_decider': 'd'},
        'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
        'required_checks': [{'id': 'integrity', 'kind': 'integrity'}, {'id': 'values', 'kind': 'scientific'}],
        'claim_scopes': {'formula_delivery': {'checks': ['integrity', 'values'], 'actions': ['delivery']}}},
        'correction_contract': {'task_fields': [], 'input_slots': []}}))
    out = tmp_path / 'spec.json'
    assert cli.main(['inference', 'spec', '--mode', 'formula-grid', '--input', str(path), '--policy', str(policy),
                     '--source', 'Synthetic example', '--assumption', 'Synthetic values only',
                     '--max-seconds', '60', '--approval-mode', 'scripted_yes', '--out', str(out)]) == 0
    spec = json.loads(out.read_text())
    science.validate(spec)
    science.plan(tmp_path / 'study', out)
    assert (tmp_path / 'study/inputs/science-plan.json').is_file()
    assert not (tmp_path / 'study/inputs/science-approval.json').exists()


def test_modes_listing(capsys):
    assert cli.main(['inference', 'modes']) == 0
    assert [row['mode'] for row in json.loads(capsys.readouterr().out)] == list(MODES)
