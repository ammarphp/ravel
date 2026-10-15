"""Release CLI intake with synthetic requests and isolated machine state."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROMPTS = [
    'Implement the search in the attached paper and predict the binned signal yield of observable X '
    'for a 700 GeV chargino with a 150 GeV LSP at 60 fb^-1; fill the attached template.json; '
    'do not take values from the published tables.',
    'Generate events for a 700 GeV chargino with a 150 GeV LSP and implement the attached search; '
    'predict the binned signal yield of observable X at 60 fb^-1 and fill the attached template.',
]
MODES = ['model-events', 'event-production', 'columnar-analysis', 'cross-section',
         'normalization-ledger', 'fill-template']


def host_reading(prompt):
    def span(text):
        start = prompt.index(text)
        return {'start': start, 'end': start + len(text), 'text': text}
    facts = []
    for index, mass in enumerate((700, 150)):
        text = f'{mass} GeV'
        facts.append({'id': f'F{100 + index}', 'type': 'mass',
                      'value': {'text': text, 'value': float(mass), 'unit': 'GeV', 'gev': float(mass)},
                      'evidence': [span(text)], 'authority': 'user_quoted', 'witness': None,
                      'physics_critical': True})
    return {'schema_version': 1, 'kind': 'request-reading-additions',
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'author': {'actor': 'host-agent', 'host': 'synthetic-host', 'model': None,
                       'invocation_id': None, 'fresh_context': True, 'record': None},
            'facts': facts, 'deliverables': [], 'ambiguities': [],
            # Host interpretation of the detector work implicit in implementing a search.
            # This located host judgment is recorded; it is no detector qualification.
            'constraints': [{'id': 'K100', 'type': 'requested_stage', 'value': {'stage': 'detector'},
                             'evidence': [span('search')]}]}


@pytest.mark.parametrize('prompt', PROMPTS)
@pytest.mark.parametrize('interpreted', [False, True])
def test_release_initiate_writes_whole_prediction_chain(tmp_path, prompt, interpreted):
    output = tmp_path / 'run'
    args = [sys.executable, '-m', 'ravel', 'initiate', '--prompt', prompt, '--out', str(output)]
    if interpreted:
        path = tmp_path / 'interpretation.json'
        path.write_text(json.dumps(host_reading(prompt)))
        args += ['--interpretation', str(path)]
    # A Python CLI subprocess only; no native engine, source retrieval or scientific stage.
    env = dict(os.environ)
    env.update(HOME=str(tmp_path / 'home'), MPLCONFIGDIR=str(tmp_path / 'mpl'),
               RAVEL_STATE_DIR=str(tmp_path / 'state'))
    for name in ('home', 'mpl', 'state'): (tmp_path / name).mkdir()
    completed = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    recovery = json.loads((output / 'inputs/capability_recovery.json').read_text())
    contract = json.loads((output / 'inputs/task_contract.json').read_text())
    reading = json.loads((output / 'inputs/reading.json').read_text())
    chain = [c for c in recovery['candidates'] if c['selection'] == 'declared_chain_requires_host_review']
    assert [c['mode'] for c in chain] == MODES
    assert chain[2]['required_task_fields'] == ['analysis_spec']
    assert recovery['original_request'] == prompt and (output / 'request.txt').read_text() == prompt
    assert contract['targets']['masses_gev'] == [700., 150.]
    assert contract['targets']['lumi_fb'] == 60.
    assert any(o['criteria'].get('claim_kind') == 'prediction' for o in contract['task_requirements']['obligations'])
    if interpreted:
        assert any(c['id'] == 'K100' and c['value']['stage'] == 'detector' for c in reading['constraints'])
        assert any(f['id'] == 'F100' and f['value']['gev'] == 700. for f in reading['facts'])
    assert not recovery['compute_authorized'] and not recovery['physics_validated']
    assert not (output / 'inputs/checkin1_approval.json').exists()
    if 'do not take values' in prompt:
        assert all('hepdata_fetch' not in a['tool'] and 'fetch_figures' not in a['tool']
                   for a in recovery['next_actions'])
