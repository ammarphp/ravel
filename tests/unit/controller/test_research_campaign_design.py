"""The research route derives its campaign request from a worker's campaign design (trusted producer)."""
import json
from pathlib import Path
import sys

import pytest

from ravel.controller.routes import research
from ravel.workflow import research_coordinator_decisions as decisions, research_cycle as cycle, state_io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_langgraph_research_orchestration import open_fixture, parent  # noqa: E402

PREFERENCES = {'agent_preferences': {'transport_preference': ['inert-cli'],
                                     'tier_models': {'judgment': {'inert-cli': 'inert-judgment-model'}}}}


def design(**override):
    value = {'schema_version': 1, 'kind': research.DESIGN_KIND,
             'campaign': {'id': 'fictional-campaign', 'budget': {'calls': 3, 'output_tokens': 60000,
                                                                 'wall_seconds': 1800, 'native_attempts': 0},
                          'max_experiments': 1, 'exploration_every': 1, 'required_experiments': [], 'premises': []},
             'evidence': [{'input': 'table.csv', 'purpose': 'model_context'}], 'candidate_modes': None,
             'review': {'arguments': {}, 'allow_control': False}, 'max_decisions': 2,
             'max_output_tokens': 4096, 'max_wall_seconds': 600}
    value.update(override)
    return value


@pytest.fixture
def run(tmp_path, monkeypatch):
    from ravel.controller import authority
    monkeypatch.setattr(authority, 'frozen', lambda store, **kw: PREFERENCES)
    _, contract = parent(tmp_path)
    run_dir = tmp_path / 'parent'
    (run_dir / 'inputs' / 'table.csv').write_text('g,N\n0.5,25\n')
    return run_dir, contract


def adopt(run_dir, value):
    target = run_dir / 'steps' / 'prepare' / 'outputs' / 'campaign-request.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    state_io.atomic_json(target, value)
    return cycle._pin(target)


def test_a_campaign_design_is_derived_into_a_request_on_the_run_s_own_contract(run):
    run_dir, contract = run
    pin = adopt(run_dir, design())
    request = research.campaign_request(pin, {'run_dir': str(run_dir), 'store': object()})
    value = decisions.request(request)  # the real validation: handoff, runtime, evidence pins, planning context
    assert value['parent_contract'] == contract
    assert Path(request['path']).resolve().is_relative_to((run_dir / 'research-request').resolve())
    assert [row['pin']['path'] for row in value['evidence']] == [str((run_dir / 'inputs' / 'table.csv').resolve())]
    assert value['runtime']['model'] == 'inert-judgment-model' and value['runtime']['adapter'] == 'model'
    assert value['campaign'] == design()['campaign'] and value['max_decisions'] == 2
    again = research.campaign_request(pin, {'run_dir': str(run_dir), 'store': object()})
    assert again == request, 'a resumed bind adopts the same derived request'


@pytest.mark.parametrize('evidence', [[{'input': '../outside.csv', 'purpose': 'model_context'}],
                                      [{'input': 'task_contract.json/..', 'purpose': 'model_context'}],
                                      [{'input': 'absent.csv', 'purpose': 'model_context'}],
                                      [{'path': '/etc/hosts', 'purpose': 'model_context'}]])
def test_design_evidence_names_only_staged_run_inputs(run, evidence):
    run_dir, _ = run
    (run_dir / 'outside.csv').write_text('x\n')
    pin = adopt(run_dir, design(evidence=evidence))
    with pytest.raises(ValueError):
        research.campaign_request(pin, {'run_dir': str(run_dir), 'store': object()})


@pytest.mark.parametrize('change', [{'parent_contract': {'path': '/x', 'sha256': 'a' * 64}}, {'schema_version': 2}])
def test_a_design_with_custody_fields_or_another_version_is_refused(run, change):
    run_dir, _ = run
    pin = adopt(run_dir, design(**change))
    with pytest.raises(ValueError, match='research-campaign-design/v1'):
        research.campaign_request(pin, {'run_dir': str(run_dir), 'store': object()})


def test_the_request_is_derived_only_inside_the_controller(run):
    run_dir, _ = run
    pin = adopt(run_dir, design())
    with pytest.raises(ValueError, match='inside the controller'):
        research.campaign_request(pin, {'run_dir': str(run_dir)})


def test_a_complete_open_research_request_is_adopted_as_before(tmp_path):
    request, _, _, _ = open_fixture(tmp_path)
    assert research.campaign_request(request, {'run_dir': str(tmp_path)}) == request
