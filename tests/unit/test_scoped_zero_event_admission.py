"""Exact scoped numerical launch admission; no generator or numerical fit runs."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

from ravel import cli
from ravel.workflow import execution, scoped, stage_supervisor
from ravel.workflow.state_io import atomic_json, read_json


@pytest.fixture
def declared(tmp_path, monkeypatch):
    # Keep the pure binding controls independent of other agents' concurrent
    # source edits. Actual acceptance below retains the entire real package.
    frozen_source = tmp_path / 'pure-source/ravel/workflow/execution.py'
    frozen_source.parent.mkdir(parents=True)
    frozen_source.write_bytes(Path(execution.__file__).read_bytes())
    monkeypatch.setattr(execution, '__file__', str(frozen_source))
    rd = tmp_path / 'run'
    (rd / 'inputs').mkdir(parents=True)
    atomic_json(rd / scoped.PLAN, {'synthetic': 'pure admission fixture'})
    atomic_json(rd / 'inputs/value.json', {'value': 3})
    command = [sys.executable, '-c', "print('never executed by pure controls')"]
    stage = {'stage': 'likelihood', 'command': command, 'inputs': ['inputs/value.json'],
             'outputs': ['outputs'], 'depends_on': [], 'cwd': str(rd)}
    binding = execution.plan_stage(rd, stage['stage'], command, stage['inputs'], stage['outputs'], [], rd)
    proposal = {'mode': 'likelihood', 'max_seconds': 30, 'stages': [stage], 'stage_binding': binding}
    approvals = []
    def approved(root, *, require_approval=False):
        approvals.append(require_approval)
        return deepcopy(proposal)
    monkeypatch.setattr(scoped, 'verify_plan', approved)
    atomic_json(rd / 'execution_attempt.json', {'attempt': 1,
                'plan_sha256': execution.file_hash(rd / scoped.PLAN), 'budget_seconds': 30})
    arguments = dict(rundir=rd, stage='likelihood', command=command, inputs=stage['inputs'],
                     outputs=stage['outputs'], depends_on=[], cwd=str(rd),
                     log='logs/scoped-worker.log', kill_secs=30, events=0)
    return rd, proposal, arguments, approvals


def test_zero_events_require_actual_full_approval_and_exact_binding(declared):
    rd, proposal, arguments, approvals = declared
    assert scoped.verify_supervised_stage(**arguments) == proposal
    assert approvals == [True]
    assert not (rd / 'execution_state.json').exists()


def test_authorization_capture_can_normalize_relative_input_output_paths(declared):
    rd, proposal, arguments, _approvals = declared
    arguments['inputs'] = sorted(str(execution.resolve_path(rd, path))
                                for path in proposal['stage_binding']['inputs'])
    arguments['outputs'] = [str(rd / 'outputs')]
    assert scoped.verify_supervised_stage(**arguments) == proposal


@pytest.mark.parametrize('field,value', [
    ('events', True), ('events', False), ('events', 1), ('events', 0.0),
    ('stage', 'statistics'), ('kill_secs', True), ('kill_secs', 31),
    ('log', 'logs/unapproved.log'), ('inputs', []), ('outputs', ['other-output']),
    ('depends_on', ['undeclared-parent']), ('command', [sys.executable, '-c', "print('broader job')"]),
])
def test_zero_event_seam_refuses_changed_scope_before_attempt(declared, field, value):
    rd, _proposal, arguments, _approvals = declared
    arguments[field] = value
    with pytest.raises(ValueError):
        scoped.verify_supervised_stage(**arguments)
    assert not (rd / 'execution_state.json').exists()


def test_zero_event_seam_refuses_generation_and_other_cwd(declared, tmp_path):
    rd, proposal, arguments, _approvals = declared
    proposal['mode'] = 'generate'
    with pytest.raises(ValueError, match='likelihood-only'):
        scoped.verify_supervised_stage(**arguments)
    proposal['mode'] = 'likelihood'
    arguments['cwd'] = str(tmp_path)
    with pytest.raises(ValueError, match='approved plan'):
        scoped.verify_supervised_stage(**arguments)
    assert not (rd / 'execution_state.json').exists()


@pytest.mark.parametrize('field,value', [('attempt', 2), ('attempt', True),
                                         ('budget_seconds', 31), ('plan_sha256', '0' * 64)])
def test_zero_event_seam_requires_bound_original_budget(declared, field, value):
    rd, _proposal, arguments, _approvals = declared
    receipt = read_json(rd / 'execution_attempt.json')
    receipt[field] = value
    atomic_json(rd / 'execution_attempt.json', receipt)
    with pytest.raises(ValueError, match='one-attempt budget'):
        scoped.verify_supervised_stage(**arguments)


@pytest.mark.parametrize('status', ['failed', 'succeeded', 'interrupted'])
def test_spent_original_attempt_does_not_admit_a_second_launch(declared, status):
    rd, _proposal, arguments, _approvals = declared
    atomic_json(rd / 'execution_state.json', {'schema_version': 1, 'revision': 1,
                'stages': {'likelihood': {'status': status}}})
    with pytest.raises(ValueError, match='already spent'):
        scoped.verify_supervised_stage(**arguments)


def test_actual_zero_event_legacy_tinyworker_keeps_real_ci1_and_one_attempt(tmp_path, monkeypatch):
    """A tiny terminal program replaces only the physics worker for this control.

    Plan verification, actual CHECK-IN 1 assent, authorization capture, process
    supervision and receipts all remain real. The intentionally incomplete
    scientific delivery must still fail its existing lifecycle postconditions.
    Run against a stable package source or a coherent frozen private copy.
    """
    rd = tmp_path / 'actual-run'
    assert cli.main(['initiate', '--prompt', 'Compute a likelihood-only control for a supplied model.',
                     '--out', str(rd)]) == 0
    command = [sys.executable, '-c',
               "from pathlib import Path; import json; p=Path('outputs'); p.mkdir(); "
               "(p/'tiny.json').write_text(json.dumps({'control':'no fit or events'})); print('tiny complete')"]
    monkeypatch.setattr(scoped, 'module_command', lambda *_: command)
    specification = {'schema_version': 1, 'mode': 'likelihood',
        'source': 'Explicit synthetic launch control, no numerical inference',
        'assumptions': ['The terminal program produces only an engineering marker'],
        'max_seconds': 30, 'approval_mode': 'scripted_yes',
        'likelihood': {'counting': {'observed': 1, 'background': 2, 'background_uncertainty': 1, 'signal': 1},
                       'poi_cap': 32, 'normalization': {'kind': 'signal_events', 'luminosity_fb': 1}}}
    atomic_json(tmp_path / 'spec.json', specification)
    scoped.plan(rd, tmp_path / 'spec.json')
    from method_decision_fixture import admit_method
    admit_method(rd)
    scoped.approve(rd, 'Actual assent to this bounded synthetic terminal-program control', scripted=True)
    stage = read_json(rd / scoped.PLAN)['stages'][0]
    for changes in ({'required_plan': 'smoke'}, {'events': 1}, {'logrel': 'logs/broader.log'},
                    {'cmd': [*command, 'unapproved-argument']}, {'kill_secs': 31}):
        arguments = dict(stage='likelihood', rundir=str(rd), events=0, logrel='logs/scoped-worker.log',
                         cmd=command, kill_secs=30, inputs=stage['inputs'], outputs=stage['outputs'],
                         depends_on=[], cwd=str(rd))
        arguments.update(changes)
        with pytest.raises(ValueError):
            stage_supervisor.supervise(**arguments)
        assert not (rd / 'execution_state.json').exists()
        assert not (rd / 'execution_attempt.json').exists()
        assert not (rd / 'logs/authorization').exists()
    assert scoped.run(rd) == 3  # Process succeeded; scientific delivery is intentionally absent.
    record = execution.load_execution(rd)['stages']['likelihood']
    assert record['status'] == 'succeeded'
    assert record['authorization_receipt']
    journal = sorted((rd / 'logs/authorization').glob('*.json'))
    assert [read_json(p)['event'] for p in journal] == ['authorized', 'launched']
    assert read_json(journal[0])['authorization']['required_plan'] == 'full'
    assert read_json(rd / 'execution_attempt.json')['attempt'] == 1
    with pytest.raises(ValueError, match='already spent'):
        scoped.run(rd)
    assert scoped.run(rd, resume=True) == 1
    assert execution.load_execution(rd)['stages']['likelihood']['attempt_id'] == record['attempt_id']
    with pytest.raises(ValueError, match='already spent'):
        stage_supervisor.supervise('likelihood', str(rd), 0, 'logs/scoped-worker.log', command,
            kill_secs=30, inputs=stage['inputs'], outputs=stage['outputs'], depends_on=[], cwd=str(rd))
    assert len(list((rd / 'logs/authorization').glob('*.json'))) == 2
