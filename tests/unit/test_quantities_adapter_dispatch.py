"""Authored ordinary quantities dispatch controls; root alone executes them."""
from ravel.physics import quantities
from ravel.workflow import science, research_cycle as cycle
from ravel.workflow.state_io import read_json
from test_research_cycle import contract, propose, experiment, run_one


def test_quantities_optional_owner_hook_resolves_actual_implementation():
    implementation = science.adapter({'mode': 'quantities', 'task': {'contract': 'contract.json', 'records': 'records.jsonl'}})
    assert implementation is quantities
    assert getattr(implementation, 'owner_limits', None) is None


def test_quantities_real_ordinary_worker_preserves_approval_and_grouped_law(tmp_path):
    root = tmp_path / 'cycle'
    cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    propose(tmp_path, root)
    declared = experiment(tmp_path, 'paired', grouped=True)
    spec = read_json(declared['study']['path'])
    assert science.adapter(spec) is quantities
    # run_one uses actual plan, refuses before approval, then explicitly admits
    # the inert supplied arithmetic and runs the real supervised worker.
    rd = run_one(tmp_path, root, declared)
    observed = cycle._load(root)[1]['experiments'][0]['observation']
    assert observed['execution_status'] == 'succeeded'
    result = read_json(rd / 'outputs/attempt-1/result.json')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert result['quantities']['values']['nominal'] == [1.0]
    assert result['quantities']['covariance'] == [[1.0]]
    assert (rd / 'logs/science-worker-1.log').is_file()
    assert not (rd / 'logs/science.failure.json').exists()
