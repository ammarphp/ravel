"""An adopted child scope selects the compute rung before its own plan review."""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.controller.routes import study
from ravel.controller.step import operations
from test_p10_contracts import _adopt
from test_study_input_roles import prepared  # noqa: F401


def rebind(prepared, proposal):
    context = prepared[0]
    coverage, _ = study.adopted_json(context, study.SCOPE_ARTIFACT)
    coverage['compute'] = proposal
    _adopt(context['store'], Path(context['run_dir']), study.SCOPE_ARTIFACT, coverage)
    context['store'].rows[-1]['record']['kind'] = 'document'
    context['plan'] = study.bind(context['plan'], context)
    return context, next(s for s in context['plan']['steps'] if s['id'] == 'operate')


@pytest.mark.parametrize('rung', ['smoke', 'full', 'scan'])
def test_child_scope_selects_its_explicit_rung_before_approval(prepared, rung):
    proposal = {'rung': rung, 'reason': 'This allocation covers the specified child computation.'}
    context, step = rebind(prepared, proposal)
    assert step['rung'] == rung
    assert step['parameters']['study_binding']['compute'] == proposal
    assert context['plan']['parameters']['study_binding']['compute'] == proposal
    assert context['store'].scan('authority') == []
    custody = list({row['record']['artifact']: deepcopy(row['record'])
                    for row in context['store'].rows}.values())
    assert operations.admission_errors(step, approved=step, inputs_custody=custody, context=context) == []


@pytest.mark.parametrize('proposal', [None, {}, {'rung': 'full'},
    {'rung': 'full', 'reason': ''}, {'rung': 'full', 'reason': '   '},
    {'rung': 'pilot', 'reason': 'One allocation.'},
    {'rung': ['smoke', 'full'], 'reason': 'One allocation.'},
    {'rung': 'full', 'reason': 'One allocation.', 'approved': True}])
def test_child_selection_requires_one_explicit_rung_and_reason(prepared, proposal):
    with pytest.raises(ValueError, match='compute selection'):
        rebind(prepared, proposal)


def test_existing_scope_preserves_an_unselected_rung(prepared):
    assert prepared[1]['rung'] is None
    assert 'compute' not in prepared[0]['plan']['parameters']['study_binding']


def test_revised_scope_releases_its_previous_compute_selection(prepared):
    context, step = rebind(prepared, {'rung': 'full', 'reason': 'Complete the declared calculation.'})
    assert step['rung'] == 'full'
    coverage, _ = study.adopted_json(context, study.SCOPE_ARTIFACT)
    coverage.pop('compute')
    _adopt(context['store'], Path(context['run_dir']), study.SCOPE_ARTIFACT, coverage)
    context['store'].rows[-1]['record']['kind'] = 'document'
    revised = study.bind(context['plan'], context)
    operate = next(s for s in revised['steps'] if s['id'] == 'operate')
    assert operate['rung'] is None
    assert 'compute' not in operate['parameters']['study_binding']
    assert revised['sha256'] != context['plan']['sha256']


def test_selected_rung_is_rechecked_at_operation_admission(prepared):
    context, step = rebind(prepared, {'rung': 'smoke', 'reason': 'The diagnostic uses a finite first allocation.'})
    changed = deepcopy(step)
    changed['rung'] = 'full'
    context['plan']['steps'] = [changed if s['id'] == changed['id'] else s for s in context['plan']['steps']]
    custody = list({row['record']['artifact']: deepcopy(row['record'])
                    for row in context['store'].rows}.values())
    errors = operations.admission_errors(changed, approved=changed, inputs_custody=custody, context=context)
    assert any(e['code'] == 'operation_input_binding_invalid' and 'compute selection' in e['message']
               for e in errors), errors
