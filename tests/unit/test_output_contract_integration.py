"""Declared output contracts through intake, plan drafting and the final whole-task check.

Failure class: a request names where its deliverables go and what they may hold, yet the
whole task could be accepted while the declared file was missing or surrounded by undeclared
files. These controls need the output-contract integration (census, routing, plan coverage,
`require_final` and `ravel initiate`). Fictional requests only; nothing is generated, executed
or sent to a model.
"""
from copy import deepcopy
import json

import pytest

from ravel import cli
from ravel.validation import validate_request_plan
from ravel.validation.validate_task_contract import validate
from ravel.workflow import output_contract as oc, request_plan, route_prompt, task_completion as tc
from test_scientific_judgment import observed_role_boundary  # noqa: F401 - fixture
from test_scientific_report import fixture as report_fixture
from test_task_completion import request, resolved, review_final_artifacts, review_run, write
from ravel.workflow.state_io import read_json

DECLARED = ('Construct a summary plot of the supplied fictional search results for a heavy resonance below 500 GeV. '
            'Write the plot to `deliverables/summary.pdf`; do not create any other files.')
CALCULATION = 'Calculate the lifetime from the supplied width in GeV.'


def declared_goal(base, workspace):
    contract = route_prompt.route(DECLARED)
    requirements = tc.initial_requirements(DECLARED)
    requirements['obligations'] += oc.census_rows(DECLARED, room=63, workspace=workspace)
    coverage = [{'obligation_id': r['id'], 'criteria': deepcopy(r['criteria'])} for r in requirements['obligations']]
    requirements['assignments'] = [{'id': 'summary-child', 'purpose': 'A bounded child preserving the parent goal.',
                                    'coverage': coverage}]
    contract['task_requirements'] = requirements
    assert validate(contract) == []
    return contract, write(base / 'parent/inputs/task_contract.json', contract)


def test_final_delivery_observes_the_declared_deliverables(tmp_path, monkeypatch, observed_role_boundary):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    _, cp = declared_goal(tmp_path, workspace)
    out = resolved(tmp_path, cp, monkeypatch)
    recipe = report_fixture(tmp_path)
    recipe_pin = write(tmp_path / 'report-recipe.json', recipe)
    parent = tmp_path / 'final-review'
    rp = request(tmp_path, cp, [out], report=recipe_pin)
    ready = tc.evaluate(rp, base_dir=tmp_path)
    assert [v['code'] for v in ready['output_contract']['violations']] == ['missing']
    final_doc = read_json(rp['path'])
    final_doc['parent_review'] = {'rundir': str(parent), 'claim_scope': 'original_task_completion'}
    rp = write(tmp_path / 'completion.json', final_doc)
    review_run(parent, [rp['path'], *[p['path'] for p in ready['input_pins'] if p['path'] != rp['path']]],
               monkeypatch, scope='original_task_completion')
    review_final_artifacts(parent, rp, recipe, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='declared output contract violated before delivery.*does not exist'):
        tc.require_final(rp, base_dir=tmp_path)
    (workspace / 'deliverables').mkdir()
    (workspace / 'deliverables/summary.pdf').write_bytes(b'%PDF-1.7 fictional')
    (workspace / 'deliverables/summary.pdf.sidecar.json').write_text('{}')
    with pytest.raises(ValueError, match='undeclared entries: summary.pdf.sidecar.json'):
        tc.require_final(rp, base_dir=tmp_path)
    (workspace / 'deliverables/summary.pdf.sidecar.json').unlink()
    final = tc.require_final(rp, base_dir=tmp_path)
    assert final['parent_task_accepted'] and final['output_contract']['satisfied']
    assert final['output_contract']['semantic_content_verified'] is False


def test_intake_census_binds_declared_outputs_and_the_draft_plan_covers_them(tmp_path):
    prompt = CALCULATION + ' Write the result to `out/lifetime.json` with keys `value` and `unit`.'
    contract, reading, _ = route_prompt.route_records(prompt, output_workspace=tmp_path)
    assert validate(contract) == []
    rows = oc.rows(contract)
    assert [r['id'] for r in rows] == ['output-contract-F1']
    declared = rows[0]['criteria'][oc.CRITERIA_KEY]
    assert declared['workspace'] == str(tmp_path) and declared['keys']['names'] == ['value', 'unit']
    plan = request_plan.draft(reading, contract)
    errors = validate_request_plan.check(reading, plan, obligations=contract['task_requirements']['obligations'])
    assert not [e for e in errors if e['error_class'] == 'obligation_uncovered']
    coverage = {row['obligation_id']: row['by'] for row in plan['coverage']}
    assert coverage['output-contract-F1'] == coverage['original-request']
    plain = route_prompt.route(CALCULATION)
    assert oc.rows(plain) == [] and plain['task_requirements']['obligations'] == \
        route_prompt.route_records(CALCULATION, output_workspace=tmp_path)[0]['task_requirements']['obligations']


def test_initiate_binds_the_workspace_and_refuses_a_conflicting_run_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.subprocess, 'call', lambda *a, **k: pytest.fail('intake launched compute'))
    workspace = tmp_path / 'workspace'
    (workspace / 'supplied').mkdir(parents=True)
    monkeypatch.chdir(workspace)
    prompt = CALCULATION + ' Write the result to result.json; do not create any other files.'
    inside = workspace / 'run'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(inside)]) == 1
    assert not inside.exists()
    outside = tmp_path / 'runs/run'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(outside)]) == 0
    contract = json.loads((outside / 'inputs/task_contract.json').read_text())
    rows = oc.rows(contract)
    assert [r['id'] for r in rows] == ['output-contract-F1', 'output-contract-L2']
    assert rows[1]['criteria'][oc.CRITERIA_KEY]['workspace'] == str(workspace.resolve())
    assert rows[1]['criteria'][oc.CRITERIA_KEY]['baseline'] == {'names': ['supplied']}
    handoff = json.loads((outside / 'inputs/intake_handoff.json').read_text())
    assert handoff['obligations'] == contract['task_requirements']['obligations']


def test_read_only_command_checks_a_run(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli.subprocess, 'call', lambda *a, **k: pytest.fail('intake launched compute'))
    run = tmp_path / 'runs/run'
    assert cli.main(['initiate', '--prompt', CALCULATION + ' Write the result to result.json.', '--out', str(run)]) == 0
    capsys.readouterr()
    assert cli.main(['output-contract', 'check', '--rundir', str(run)]) == 1
    assert json.loads(capsys.readouterr().out)['violations'][0]['code'] == 'missing'
    (workspace / 'result.json').write_text('{"value": 1}')
    assert cli.main(['output-contract', 'check', '--rundir', str(run)]) == 0
