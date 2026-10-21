"""Capability needs and their best available tool: registry, arising, the plan check and the planning view.

Every availability below is injected; nothing probes this host. Plans are minimal synthetic step lists.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import tool_selection as ts

ROOT = Path(__file__).resolve().parents[2]
AGENTRIVET = 'census-agentrivet-e4d12ecc'
SFITTER = 'census-sfitteragents-sfitter-6072a79e-pytorch-2-14-0'
FEYNRULES = 'census-feynrules-2-3-49'
FLEXIBLESUSY = 'census-flexiblesusy-2-9-0-cmssm-lowmssm-nmssm'
SYMPY = 'component-sympy'


def status_of(available=(), reasons=None):
    """A ``status(census_id)`` stand-in: the listed ids are available, every other tool has ``reasons``."""
    reasons = reasons or {}

    def status(census_id):
        if census_id in available:
            return {'available': True, 'reason': None}
        return {'available': False, 'reason': reasons.get(census_id, 'not_installed')}
    return status


@pytest.fixture(scope='module')
def needs():
    return ts.registry()


def named_registry(names):
    """The packaged registry with ``names`` ({census id: request names}) set on those rows."""
    census = json.loads((ROOT / 'src/ravel/data/backends/census.json').read_text())
    for row in census['tools']:
        if row['id'] in names:
            row['request_names'] = list(names[row['id']])
    return ts.registry(census)


def test_the_packaged_registry_names_registered_operations_and_roles(needs):
    operations = set(json.loads((ROOT / 'src/ravel/data/operation_signatures.json').read_text())['operations'])
    roles = {json.loads(p.read_text())['card']['id'] for p in (ROOT / '.ravel/roles').glob('ravel-*.json')}
    assert ts.registry_errors(needs, operations=operations, roles=roles) == []
    for row in needs.values():
        preferences = [c['preference'] for c in row['candidates']]
        assert preferences == sorted(preferences) and len(set(preferences)) == len(preferences)


@pytest.mark.parametrize('mutation, message', [
    (lambda c: c['tools'][0].setdefault('serves', []).append({'need': 'no-such-need', 'preference': 9,
                                                               'operations': ['x']}), 'unknown need'),
    (lambda c: c['needs']['global-fit']['methods'][0].update(preference=1), 'distinct positive preference'),
    (lambda c: c['needs']['global-fit']['methods'][0].update(operations=[], roles=[]), 'no operation or role'),
    (lambda c: c['needs']['global-fit']['methods'][0].update(available='sometimes'), 'malformed method'),
    (lambda c: c['needs']['global-fit']['triggers'].update(terms=['re:(']), 'invalid term'),
])
def test_malformed_declarations_are_refused(mutation, message):
    census = json.loads((ROOT / 'src/ravel/data/backends/census.json').read_text())
    mutation(census)
    with pytest.raises(ts.RegistryError, match=message):
        ts.registry(census)


def test_needs_arise_from_their_declared_sources():
    needs = named_registry({'census-snakemake-9-27-0': ['Snakemake']})
    arisen = ts.arising(needs, label={'task_mode': 'no_routine'}, request_text='Perform a global SMEFT fit.',
                        reading={'constraints': [{'id': 'K1', 'type': 'requested_tool', 'value': {'tool': 'Snakemake'}}]},
                        steps=[{'id': 'm', 'kind': 'operate', 'operation': 'model-authoring'},
                               {'id': 'd', 'kind': 'author', 'needs': ['global-fit']}])
    assert [s['from'] for s in arisen['routine-construction']] == ['derived_label']
    assert {s['from'] for s in arisen['global-fit']} == {'request_term', 'step_declares'}
    assert arisen['external-workflow-execution'][0] == {'from': 'requested_tool', 'constraint': 'K1',
                                                       'tool': 'Snakemake', 'candidate': 'census-snakemake-9-27-0'}
    assert arisen['symbolic-model-building'][0]['from'] == 'implied'
    assert ts.arising(needs, label={'task_mode': 'reproduce'}, request_text='Reproduce the published limit.') == {}


def _check(needs, steps, *, available=(), reasons=None, label=None, text=None, reading=None, plan_extra=None,
           supplied=()):
    plan = {'steps': steps, **(plan_extra or {})}
    return ts.check(plan, profile={}, supplied=supplied, label=label, reading=reading, request_text=text,
                    needs=needs, status=status_of(available, reasons), profile_record='environment-profile-000001')


def test_the_best_available_tool_serves_the_need(needs):
    record, problems = _check(needs, [{'id': 'construct', 'kind': 'author', 'role': 'routine-constructor'}],
                              available={AGENTRIVET}, label={'task_mode': 'no_routine'})
    assert problems == [] and record['passed'] is True
    row = record['needs'][0]
    assert row['need'] == 'routine-construction' and row['best'] == AGENTRIVET and row['status'] == 'served'
    assert ts.bound(record, 'construct')[0][1]['id'] == AGENTRIVET


def test_a_lower_preference_candidate_needs_a_typed_reason(needs):
    steps = [{'id': 'impl', 'kind': 'operate', 'operation': 'authored-analysis'}]
    record, problems = _check(needs, steps, available={AGENTRIVET}, label={'task_mode': 'no_routine'})
    assert len(problems) == 1 and 'AgentRivet' in problems[0] and 'role routine-constructor' in problems[0]
    assert record['needs'][0]['status'] == 'unserved' and record['passed'] is False


def test_the_fallback_serves_when_the_preferred_tool_is_missing(needs):
    steps = [{'id': 'impl', 'kind': 'operate', 'operation': 'authored-analysis'}]
    record, problems = _check(needs, steps, label={'task_mode': 'no_routine'})
    assert problems == []
    row = record['needs'][0]
    assert row['best'] == 'hand-written-analysis' and row['status'] == 'served'
    skipped = {c['id']: c['reason'] for c in row['candidates'] if c['state'] == 'unavailable'}
    assert skipped == {AGENTRIVET: 'not_installed'}


def test_an_unavailable_candidate_is_refused_while_another_is_available(needs):
    steps = [{'id': 'construct', 'kind': 'author', 'role': 'routine-constructor'}]
    record, problems = _check(needs, steps, label={'task_mode': 'no_routine'})
    assert len(problems) == 1 and 'unavailable here (not_installed)' in problems[0] and 'authored-analysis' in problems[0]


def test_no_available_alternative_is_a_derived_reason(needs):
    steps = [{'id': 'fit', 'kind': 'operate', 'operation': 'sfitter-native-fit'}]
    record, problems = _check(needs, steps, reasons={SFITTER: 'unsupported_platform'})
    # the Gaussian measurement fit is a method that is always available: it is the best available candidate
    assert problems and 'unavailable here (unsupported_platform)' in problems[0]
    steps = [{'id': 'wf', 'kind': 'operate', 'operation': 'external-workflow'}]
    record, problems = _check(needs, steps, reasons={'census-snakemake-9-27-0': 'remote_only'})
    assert problems == []
    entry = record['needs'][0]['served_by'][0]
    assert entry['reason']['code'] == 'no_available_alternative'
    assert record['needs'][0]['status'] == 'no_available_candidate'


def test_an_unobserved_tool_is_eligible_not_unavailable(needs):
    steps = [{'id': 'construct', 'kind': 'author', 'role': 'routine-constructor'}]
    record, problems = _check(needs, steps, reasons={AGENTRIVET: 'unobserved'}, label={'task_mode': 'no_routine'})
    assert problems == [] and record['needs'][0]['candidates'][0]['state'] == 'unknown'


def test_a_requested_tool_comes_first_and_is_its_own_reason():
    smelli = 'census-wcxf-wilson-2-5-2-flavio-2-7-1-smelli-2-4-3'
    needs = named_registry({smelli: ['smelli', 'flavio']})
    reading = {'constraints': [{'id': 'K2', 'type': 'requested_tool', 'value': {'tool': 'smelli'}}]}
    steps = [{'id': 'fit', 'kind': 'operate', 'operation': 'eft-toolchain'}]
    record, problems = _check(needs, steps, available={SFITTER, smelli}, text='a global fit of the couplings',
                              reading=reading)
    assert problems == [] and record['needs'][0]['best'] == smelli
    # the same plan without the request is served by a lower-preference tool and needs a reason
    record, problems = _check(needs, steps, available={SFITTER, smelli}, text='a global fit of the couplings')
    assert problems and 'SFitter' in problems[0]
    # a requested tool that is unavailable does not displace the best available one
    record, problems = _check(needs, steps, available={SFITTER}, text='a global fit of the couplings', reading=reading)
    assert record['needs'][0]['best'] == SFITTER and problems


def test_a_typed_reason_needs_a_statement_and_resolvable_evidence(needs):
    reason = {'code': 'not_applicable', 'statement': 'only two measurements; the request asks for their combination',
              'evidence': ['step:why']}
    steps = [{'id': 'fit', 'kind': 'operate', 'operation': 'measurement', 'tool_reasons': {'global-fit': reason}},
             {'id': 'why', 'kind': 'decide'}]
    record, problems = _check(needs, steps, available={SFITTER}, text='Perform a global fit of the measurements.')
    assert problems == [] and record['needs'][0]['status'] == 'served_with_reason'
    bad = deepcopy(steps)
    bad[0]['tool_reasons']['global-fit']['evidence'] = ['step:fit', 'reading:nothing']
    record, problems = _check(needs, bad, available={SFITTER}, text='Perform a global fit of the measurements.')
    assert any('names no decide or ask step' in p for p in problems)
    assert any('names no item of the reading' in p for p in problems)
    bad[0]['tool_reasons']['global-fit'] = {'code': 'preferred', 'statement': 'x', 'evidence': []}
    record, problems = _check(needs, bad, available={SFITTER}, text='Perform a global fit of the measurements.')
    assert any('needs code not_applicable' in p for p in problems)


def test_an_arisen_need_no_step_serves_needs_a_step_or_a_plan_reason(needs):
    record, problems = _check(needs, [{'id': 's', 'kind': 'synthesize'}], available={FEYNRULES},
                              text='Derive the Feynman rules of this Lagrangian.')
    assert len(problems) == 1 and 'no step serves it' in problems[0] and 'model-authoring' in problems[0]
    reading = {'facts': [{'id': 'F4', 'type': 'model'}]}
    plan_reason = {'tool_reasons': {'symbolic-model-building': {
        'code': 'not_applicable', 'statement': 'the request supplies the derived rules; nothing is derived',
        'evidence': ['reading:F4']}}}
    record, problems = _check(needs, [{'id': 's', 'kind': 'synthesize'}], available={FEYNRULES},
                              text='Derive the Feynman rules of this Lagrangian.', reading=reading, plan_extra=plan_reason)
    assert problems == [] and record['needs'][0]['status'] == 'reasoned'


def test_a_supplied_input_makes_its_method_available(needs):
    steps = [{'id': 'ufo', 'kind': 'operate', 'operation': 'model-tool-bridge'}]
    text = 'Build a UFO from this Lagrangian.'
    record, problems = _check(needs, steps, reasons={FEYNRULES: 'unlicensed'}, text=text)
    assert problems == [] and record['needs'][0]['status'] == 'no_available_candidate'
    record, problems = _check(needs, steps, reasons={FEYNRULES: 'unlicensed'}, text=text,
                              supplied=[{'kind': 'model', 'path': '/fictional/model.ufo'}])
    assert problems == [] and record['needs'][0]['best'] == 'supplied-ufo'
    assert record['needs'][0]['candidates'][0]['reason'] == 'unlicensed'


def test_symbolic_model_building_falls_back_to_a_supplied_model_then_a_sympy_derivation(needs):
    order = [c['id'] for c in needs['symbolic-model-building']['candidates']]
    assert order == [FEYNRULES, 'supplied-ufo', FLEXIBLESUSY, SYMPY]
    text = 'Derive the Feynman rules of the fictional scalar extension.'
    derive = [{'id': 'derive', 'kind': 'operate', 'operation': 'authored-analysis'}]
    # Without the Mathematica packages, a supplied model or a spectrum generator, SymPy written as authored code serves.
    record, problems = _check(needs, derive, available={SYMPY}, text=text)
    assert problems == [] and record['needs'][0]['best'] == SYMPY and record['needs'][0]['status'] == 'served'
    # A supplied model ranks above it: the SymPy derivation then needs a typed reason.
    record, problems = _check(needs, derive, available={SYMPY}, text=text, supplied=[{'kind': 'model'}])
    assert record['needs'][0]['best'] == 'supplied-ufo' and len(problems) == 1 and 'model-tool-bridge' in problems[0]
    # With FeynRules installed it is the best candidate, unless the request names SymPy.
    record, problems = _check(needs, derive, available={FEYNRULES, SYMPY}, text=text)
    assert record['needs'][0]['best'] == FEYNRULES and problems
    reading = {'constraints': [{'id': 'K3', 'type': 'requested_tool', 'value': {'tool': 'SymPy'}}]}
    record, problems = _check(needs, derive, available={FEYNRULES, SYMPY}, text=text, reading=reading)
    assert problems == [] and record['needs'][0]['best'] == SYMPY


def test_unknown_needs_named_by_a_plan_are_refused(needs):
    record, problems = _check(needs, [{'id': 'x', 'kind': 'author', 'needs': ['no-such-need']}])
    assert problems and 'unknown capability need' in problems[0]


def test_controller_steps_carry_needs_and_reasons_under_parameters(needs):
    step = {'id': 'fit', 'kind': 'operate', 'operation': 'measurement',
            'parameters': {'needs': ['global-fit'], 'tool_reasons': {'global-fit': {
                'code': 'not_applicable', 'statement': 'a combination of two measurements is requested',
                'evidence': ['step:why']}}}}
    record, problems = _check(needs, [step, {'id': 'why', 'kind': 'decide'}], available={SFITTER})
    assert problems == [] and record['needs'][0]['status'] == 'served_with_reason'


def test_the_planning_view_lists_every_need_with_its_ranked_candidates(needs):
    view = ts.planning_view(profile={}, label={'task_mode': 'no_routine'}, needs=needs,
                            status=status_of({AGENTRIVET}))
    by_need = {row['need']: row for row in view['needs']}
    assert set(by_need) == set(needs)
    assert by_need['routine-construction']['arises'] and by_need['routine-construction']['best'] == AGENTRIVET
    assert not by_need['global-fit']['arises']
    assert 'tool_reasons' in view['rule']


def test_alternatives_exclude_the_lost_candidate(needs):
    record, _ = _check(needs, [{'id': 'construct', 'kind': 'author', 'role': 'routine-constructor'}],
                       available={AGENTRIVET}, label={'task_mode': 'no_routine'})
    found = ts.alternatives(record, 'routine-construction', exclude=[AGENTRIVET])
    assert [c['id'] for c in found] == ['hand-written-analysis']
