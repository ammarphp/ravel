"""A source-bound operation is offered only when the request matches its applicability predicate.

Every registered operation declares its applicability as data. A general operation is
suggested by its vocabulary alone; a source-bound operation additionally requires its
predicate (groups of terms, all groups matched) to match the request.
"""
import json
from pathlib import Path

import pytest

from ravel.workflow import capability_routing as cr
from ravel.workflow import intake, science

ROOT = Path(__file__).resolve().parents[2]
WEIGHTS = {'tools': 3, 'inputs': 2, 'observables': 2, 'outputs': 2, 'context': 1}


def _row(summary, applicability):
    return {'summary': summary, 'operations': ['analysis'], 'tools': ['Widgetscope'],
            'inputs': ['widget ntuple'], 'observables': [], 'outputs': [], 'context': [],
            'applicability': applicability}


def _document():
    return {'schema_version': 1, 'weights': dict(WEIGHTS), 'threshold': 2, 'modes': {
        'general-widget-analysis': _row('Analyse supplied widget ntuples.', {'scope': 'general'}),
        'bound-widget-release': _row('Reproduce one released widget study.', {
            'scope': 'source-bound',
            'bound_to': 'the stored question population of one synthetic release',
            'select_when': [['ANA-0001', 'bound-widget-release']],
            'general_operation': 'general-widget-analysis'}),
    }}


def _by_mode(document=None):
    document = document or _document()
    rows = cr._descriptors(document, set(document['modes']))
    return {mode: {'mode': mode, 'descriptor': row} for mode, row in rows.items()}


def _modes(prompt, by_mode):
    return [row['mode'] for row in cr.suggest(prompt, by_mode)]


def test_unmatched_request_is_never_offered_the_source_bound_operation():
    by_mode = _by_mode()
    for prompt in ('Analyse my widget ntuples with Widgetscope.',
                   'Run Widgetscope over the widget ntuple I supplied and report the yields.'):
        modes = _modes(prompt, by_mode)
        assert 'general-widget-analysis' in modes
        assert 'bound-widget-release' not in modes


def test_matching_request_is_offered_the_source_bound_operation_with_its_scope():
    by_mode = _by_mode()
    rows = cr.suggest('Reproduce ANA-0001 with Widgetscope on its widget ntuple.', by_mode)
    bound = next(row for row in rows if row['mode'] == 'bound-widget-release')
    assert bound['applicability']['scope'] == 'source-bound'
    assert bound['applicability']['general_operation'] == 'general-widget-analysis'
    # Naming the registered operation also selects it, even inside a code span.
    assert 'bound-widget-release' in _modes('Use `bound-widget-release` with Widgetscope.', by_mode)


def test_every_predicate_group_must_match():
    document = _document()
    document['modes']['bound-widget-release']['applicability']['select_when'] = [['ANA-0001'], ['question population']]
    by_mode = _by_mode(document)
    assert 'bound-widget-release' not in _modes('Reproduce ANA-0001 with Widgetscope.', by_mode)
    assert 'bound-widget-release' in _modes(
        'Reproduce ANA-0001 with Widgetscope over its stored question population.', by_mode)


@pytest.mark.parametrize('applicability', [
    None, {}, {'scope': 'narrow'}, {'scope': 'general', 'select_when': [['x']]},
    {'scope': 'source-bound', 'bound_to': 'x', 'general_operation': None},
    {'scope': 'source-bound', 'bound_to': 'x', 'select_when': [], 'general_operation': None},
    {'scope': 'source-bound', 'bound_to': 'x', 'select_when': [[]], 'general_operation': None},
    {'scope': 'source-bound', 'bound_to': ' ', 'select_when': [['x']], 'general_operation': None},
    {'scope': 'source-bound', 'bound_to': 'x', 'select_when': [['x']], 'general_operation': 'absent-mode'},
])
def test_descriptor_requires_a_well_formed_applicability_predicate(applicability):
    document = _document()
    row = document['modes']['bound-widget-release']
    if applicability is None:
        row.pop('applicability')
    else:
        row['applicability'] = applicability
    with pytest.raises(ValueError):
        cr._descriptors(document, set(document['modes']))


def test_host_intent_for_an_unmatched_source_bound_operation_is_withheld():
    by_mode = _by_mode()
    prompt = 'Analyse my widget ntuples with Widgetscope.'
    intent = {'mode': 'bound-widget-release', 'scope': 'component',
              'basis': {'start': 0, 'end': len(prompt), 'text': prompt}}
    offered, withheld = cr.screen_intents(prompt, [intent], by_mode)
    assert offered == [] and withheld[0]['mode'] == 'bound-widget-release'
    assert withheld[0]['general_operation'] == 'general-widget-analysis'
    prompt = 'Reproduce ANA-0001 with Widgetscope.'
    intent['basis'] = {'start': 0, 'end': len(prompt), 'text': prompt}
    offered, withheld = cr.screen_intents(prompt, [intent], by_mode)
    assert [i['mode'] for i in offered] == ['bound-widget-release'] and withheld == []


def test_packaged_registry_declares_applicability_for_every_operation():
    document = json.loads((ROOT / 'src/ravel/data/mode_descriptors.json').read_text())
    rows = cr._descriptors(document, set(document['modes']))
    assert all(row['applicability']['scope'] in ('general', 'source-bound') for row in rows.values())
    bound = {mode for mode, row in rows.items() if row['applicability']['scope'] == 'source-bound'}
    assert bound and set(science.MODES) >= bound
    # A source-bound operation never serves a named general operation.
    for mode in bound:
        assert rows[mode]['operations'] == []
        for operation in {op for row in rows.values() for op in row['operations']}:
            assert mode not in intake.operation_modes(operation)


def test_packaged_source_bound_operations_need_explicit_selection():
    by_mode = cr.declared_descriptors()
    bound = {mode for mode, row in by_mode.items() if row['descriptor']['applicability']['scope'] == 'source-bound'}
    generic = ('Run a columnar analysis with ServiceX and coffea over PHYSLITE.',
               'Convert my ROOT file ntuple into raw arrays.',
               'Construct mass and width inputs for a large width resonance search.',
               'Make a parameter grid for a semi-visible jet dark shower model.',
               'Sample the parameter space with MultiNest.')
    for prompt in generic:
        assert not bound & set(_modes(prompt, by_mode)), prompt
    for mode in bound:
        assert mode in _modes(f'Use the {mode} operation.', by_mode), mode


def test_science_dispatch_reports_registered_applicability():
    assert science.applicability('literal-calculation') == {'scope': 'general'}
    # Every source-bound operation the registry ships names what it is bound to.
    bound = [science.applicability(mode) for mode in science.MODES
             if science.applicability(mode)['scope'] != 'general']
    assert bound and all(row['scope'] == 'source-bound' and row['bound_to'].strip() for row in bound)
    with pytest.raises(ValueError):
        science.applicability('absent-mode')
