"""Internal validation callers record bounded machine choices before assent."""
import importlib.util
from pathlib import Path
import sys
import pytest
from ravel.workflow import method_selection, science
from ravel.workflow.state_io import atomic_json, read_json


@pytest.mark.parametrize('script', ['run_science_controls', 'run_rivet_controls'])
def test_internal_controls_record_machine_method_before_approval(tmp_path, monkeypatch, script):
    path = Path(__file__).parents[2] / 'scripts/validation' / (script + '.py')
    module_spec = importlib.util.spec_from_file_location(script, path)
    module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
    spec = tmp_path / 'spec.json'
    atomic_json(spec, {'schema_version': 1, 'mode': 'quantities', 'source': 'Synthetic validation output',
        'assumptions': ['Inert test'], 'approval_mode': 'scripted_yes', 'max_seconds': 45, 'task': {}})
    case = {'name': 'fictional-control', 'spec': str(spec), 'expected': 'passed'}
    if script == 'run_science_controls':
        monkeypatch.setattr(module, 'prepare', lambda out: [case])
    else:
        atomic_json(tmp_path / 'cases.json', {'schema_version': 1, 'cases': [{'name': 'fictional-control', 'energy': 1,
            'kind': 'dy', 'observable': 'synthetic', 'unit': 'pb/GeV', 'normalized': False, 'grouped': False,
            'expected': 'passed'}]})
        monkeypatch.setattr(module, 'events', lambda *a: 'inert event bytes')
    def plan(rd, source):
        atomic_json(rd / science.SPEC, read_json(source))
        atomic_json(rd / 'inputs/checkin1.json', {'schema_version': 1, 'kind': 'checkin1', 'sections': {}})
    def approve(rd, quote, *, scripted):
        assert scripted and quote == 'Explicit synthetic assent'
        record = read_json(rd / method_selection.DECISION_PATH)
        assert record['provenance']['authority'] == 'scripted_experiment'
        assert method_selection.escalation_allowed(record)[0]
        assert record['cost_forecast']['bounded_pilot']['max_wall_hours'] == (45 if script == 'run_science_controls' else 120) / 3600
        assert 'method_decision' in read_json(rd / 'inputs/checkin1.json')['sections']
    monkeypatch.setattr(module.science, 'plan', plan)
    monkeypatch.setattr(module.science, 'approve', approve)
    monkeypatch.setattr(module.science, 'run', lambda rd: 0)
    monkeypatch.setattr(module.science, 'packet', lambda rd: {'lifecycle_verdict': 'PASS'})
    runtime = tmp_path / 'runtime.json'; atomic_json(runtime, {})
    argv = [script, '--out', str(tmp_path / 'controls'), '--execute', '--assent', 'Explicit synthetic assent']
    if script == 'run_rivet_controls':
        argv += ['--runtime', str(runtime), '--source', str(tmp_path), '--cases', str(tmp_path / 'cases.json')]
    monkeypatch.setattr(sys, 'argv', argv)
    assert module.main() == 0
