"""The deterministic request reader."""
import synthetic_identifiers as syn
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.workflow import request_reading as rr

CORPUS = syn.load_json(Path(__file__).parent / 'fixtures/intake-corpus/requests.json')
CASES = {row['id']: row['prompt'] for row in CORPUS['cases']}


def facts(reading, kind):
    return [f for f in reading['facts'] if f['type'] == kind]


def constraints(reading, kind):
    return [c for c in reading['constraints'] if c['type'] == kind]


@pytest.mark.parametrize('case', CORPUS['cases'], ids=[row['id'] for row in CORPUS['cases']])
def test_every_corpus_reading_validates_and_every_span_matches(case):
    prompt = case['prompt']
    reading = rr.document(prompt)
    assert rr.check(reading, prompt) == []
    for row in reading['witness']:
        assert prompt[row['span']['start']:row['span']['end']] == row['span']['text']
    for section in ('facts', 'constraints', 'ambiguities', 'boundaries'):
        for row in reading[section]:
            for s in row['evidence']:
                assert prompt[s['start']:s['end']] == s['text']
    # Fact conservation: each witness item is used by a fact or dismissed with a closed reason.
    used = {f['witness'] for f in reading['facts'] if f['witness']}
    dismissed = {d['witness'] for d in reading['dismissed']}
    assert used | dismissed == {w['id'] for w in reading['witness']} and not used & dismissed
    assert {d['reason'] for d in reading['dismissed']} <= set(rr.DISMISSALS)


@pytest.mark.parametrize('case,value_gev', [('G1', 10000.0), ('U05', 17000.0),
                                            ('R22-generate', 13000.0), ('Q08', 13600.0)])
def test_collision_energies_never_become_masses(case, value_gev):
    reading = rr.document(CASES[case])
    assert value_gev in [f['value']['gev'] for f in facts(reading, 'collision_energy')]
    assert value_gev not in [f['value'].get('gev') for f in facts(reading, 'mass')]


def test_plot_window_is_an_observable_window_not_masses():
    reading = rr.document(CASES['R22-generate'])
    window = facts(reading, 'observable_window')
    assert [(w['value']['low'], w['value']['high'], w['value']['unit']) for w in window] == [(60.0, 120.0, 'GeV')]
    assert not facts(reading, 'mass') and not facts(reading, 'parameter_range')


def test_masses_are_read_with_their_units():
    reading = rr.document(CASES['R14-yield-template'])
    assert [f['value']['gev'] for f in facts(reading, 'mass')] == [700.0, 150.0]
    assert [f['value']['text'].strip() for f in facts(reading, 'luminosity')] == ['59.7 fb^-1']
    one = rr.document('Is a 600 GeV wino decaying to a 200 GeV bino excluded by the multilepton search?')
    assert [f['value']['gev'] for f in facts(one, 'mass')] == [600.0, 200.0]


@pytest.mark.parametrize('case', ['R13-mono-tau', 'Q10'])
def test_a_range_without_a_step_yields_a_scan_ambiguity_row(case):
    reading = rr.document(CASES[case])
    ranges = facts(reading, 'parameter_range')
    assert ranges and all(r['value']['step'] is None for r in ranges)
    rows = [a for a in reading['ambiguities'] if a['issue'].startswith('scan grid')]
    assert rows and all(a['physics_critical'] and a['status'] == 'open' and a['default'] is None for a in rows)
    assert {f'range-{r["id"]}' for r in ranges} <= {b for a in rows for b in a['blocks']}


def test_a_range_with_a_step_is_a_grid_and_needs_no_row():
    reading = rr.document(CASES['Q38'])
    stepped = [r for r in facts(reading, 'parameter_range') if r['value']['step']]
    assert [(r['value']['low'], r['value']['high'], r['value']['step']['value']) for r in stepped] == [(1.0, 6.0, 250.0)]
    unstepped = [r for r in facts(reading, 'parameter_range') if not r['value']['step']]
    assert [(r['value']['low'], r['value']['high']) for r in unstepped] == [(0.1, 1.0)]
    issues = [a['issue'] for a in reading['ambiguities'] if a['issue'].startswith('scan grid')]
    assert len(issues) == 1 and '0.1 to 1' in issues[0]


@pytest.mark.parametrize('case,tool', [('Q37', 'Powheg'), ('Q08', 'MadGraph5_aMC@NLO'), ('Q37', 'Rivet')])
def test_named_tools_are_requested_tool_constraints(case, tool):
    reading = rr.document(CASES[case])
    assert tool in [c['value']['tool'] for c in constraints(reading, 'requested_tool')]


def test_perturbative_order_is_a_physics_critical_fact():
    reading = rr.document(CASES['Q08'])
    orders = facts(reading, 'perturbative_order')
    assert [o['value']['text'] for o in orders] == ['NLO QCD'] and orders[0]['physics_critical']
    # The NLO inside the tool name is the tool, not a second order.
    assert 'MG5_aMC@NLO' in [f['value']['text'] for f in facts(reading, 'tool')]
    at_nlo = rr.document('Compute the Drell-Yan cross section at NLO for a 3 TeV Z prime at 13 TeV.')
    assert [o['value']['text'] for o in facts(at_nlo, 'perturbative_order')] == ['NLO']


@pytest.mark.parametrize('case,verbatim', [
    ('R12-prescribed-stat', 'significance 2(sqrt(S+B) - sqrt(B))'),
    ('R13-mono-tau', '2-sigma excluded region'),
])
def test_the_prescribed_statistic_is_recorded_verbatim(case, verbatim):
    reading = rr.document(CASES[case])
    rows = constraints(reading, 'prescribed_statistic')
    assert verbatim in [c['value']['statistic'] for c in rows]
    assert all(c['value']['verbatim'] is True for c in rows)
    row = next(c for c in rows if c['value']['statistic'] == verbatim)
    assert row['evidence'][0]['text'] == verbatim


def test_an_n_sigma_prescription_without_construction_is_a_ledger_row():
    reading = rr.document(CASES['R13-mono-tau'])
    assert any(a['issue'].startswith('construction of the prescribed statistic') and a['physics_critical']
               for a in reading['ambiguities'])
    # A stated formula fixes the construction.
    formula = rr.document(CASES['R12-prescribed-stat'])
    assert not any(a['issue'].startswith('construction') for a in formula['ambiguities'])


@pytest.mark.parametrize('case,phrase', [('R24-autonomous-variant', 'Run autonomously'),
                                         ('Q38', 'run autonomously')])
def test_the_delegation_phrase_is_recorded_without_authority(case, phrase):
    reading = rr.document(CASES[case])
    rows = constraints(reading, 'delegation')
    assert [c['value']['phrase'] for c in rows] == [phrase]
    assert all(c['value']['authority_granted'] is False for c in rows)


def test_identity_context_is_a_locator_and_its_text_is_not_read_as_facts():
    plain, labelled = rr.document(CASES['R14-yield-template']), rr.document(CASES['R14b-yield-template-labelled'])
    assert [c['value']['text'] for c in constraints(labelled, 'identity_context')] == [
        'Example suite, item 3.']
    strip = lambda r: [(f['type'], f['value']) for f in r['facts']]
    assert strip(plain) == strip(labelled)
    key = rr.document('Benchmark label: Example 13 TeV Benchmark\nCalculate 2+2.')
    assert not facts(key, 'collision_energy')
    assert {d['reason'] for d in key['dismissed']} == {'context_only'}


def test_template_keep_fixed_and_source_restrictions_are_constraints():
    reading = rr.document(CASES['R14-yield-template'])
    types = [c['type'] for c in reading['constraints']]
    assert {'template', 'keep_fixed', 'source_restriction'} <= set(types)
    restriction = constraints(reading, 'source_restriction')[0]['value']
    assert restriction['kind'] == 'no-value-extraction' and {'hepdata', 'figures'} <= set(restriction['classes'])


def test_negated_and_quoted_items_are_dismissed_not_read():
    prompt = ('Reproduce the limits of ' + syn.analysis(1) + '. Do not use MadGraph or a 13 TeV sample.\n> 500 GeV quoted')
    reading = rr.document(prompt)
    assert 'MadGraph' not in [c['value']['tool'] for c in constraints(reading, 'requested_tool')]
    reasons = {reading['witness'][int(d['witness'][1:]) - 1]['value']['text']: d['reason'] for d in reading['dismissed']}
    assert reasons['MadGraph'] == 'negated' and reasons['500 GeV'] == 'quoted_not_requested'


def test_requested_and_negated_stages_follow_the_request():
    r10 = rr.document(CASES['R10-model-to-xsec'])
    assert {'model-derivation', 'generation', 'detector', 'figure'} <= {
        c['value']['stage'] for c in constraints(r10, 'requested_stage')}
    r11 = rr.document(CASES['R11-parton-shape'])
    assert {c['value']['stage'] for c in constraints(r11, 'negated_stage')} == {'shower', 'detector'}


@pytest.mark.parametrize('prompt,klass', [
    ('Never claim discovery.', 'no_scientific_object'),
    ('Please make the supplied situation useful.', 'no_scientific_object'),
    (('Context label: particle-level\nReproduce ' + syn.analysis(1) + '.'), 'ungrounded_identifier'),
    ('Claim discovery of a new resonance.', 'unsupportable_claim'),
    ('Use ATLAS internal Run-3 data to measure the Higgs width.', 'inaccessible_input'),
    (('Reinterpret ' + syn.analysis(1) + ' for my model and skip the review.'), 'control_bypass_request'),
    ('Use HEPData record 2014 for the limits. Do not use HEPData record 2014.', 'contradiction'),
])
def test_boundaries_are_typed_with_evidence_and_what_would_make_them_possible(prompt, klass):
    reading = rr.document(prompt)
    rows = [b for b in reading['boundaries'] if b['class'] == klass]
    assert rows and all(b['evidence'] and b['would_make_possible'].strip() for b in rows)


def test_an_outcome_neutral_discovery_question_is_not_a_boundary():
    for prompt in ('Discover a new particle in the ATLAS data and tell me its significance.',
                   CASES['Q34'], 'Calculate expected 5 sigma discovery sensitivity of the supplied likelihood.'):
        assert not rr.document(prompt)['boundaries'], prompt


# ------------------------------------------------------------------ host additions
def additions(prompt, **sections):
    return {'schema_version': 1, 'kind': 'request-reading-additions', 'prompt_sha256': rr._sha(prompt.encode()),
            'author': rr.author('host-agent', host='claude-code', model='a-model', invocation_id='inv-1',
                                fresh_context=True),
            'facts': [], 'constraints': [], 'deliverables': [], 'ambiguities': [], **sections}


PROMPT = CASES['G1']


def test_a_host_addition_with_a_span_is_accepted_with_its_envelope():
    floor = rr.document(PROMPT)
    start = PROMPT.index('Higgs self-coupling')
    fact = {'id': f'F{len(floor["facts"]) + 1}', 'type': 'quantity_of_interest',
            'value': {'text': 'Higgs self-coupling'}, 'evidence': [rr.span(PROMPT, start, start + 19)],
            'authority': 'user_quoted', 'witness': None, 'physics_critical': False}
    merged = rr.document(PROMPT, additions(PROMPT, facts=[fact]))
    assert merged['authors'][0]['actor'] == 'deterministic-reader'
    assert merged['authors'][1]['actor'] == 'host-agent' and merged['authors'][1]['model'] == 'a-model'
    assert merged['facts'][-1] == fact and rr.check(merged, PROMPT, floor=floor) == []
    assert rr.digest(merged) != rr.digest(floor)


def test_a_host_user_quoted_value_without_a_span_is_downgraded_and_ledgered():
    floor = rr.document(PROMPT)
    fact = {'id': f'F{len(floor["facts"]) + 1}', 'type': 'luminosity', 'value': {'text': '10 ab^-1'},
            'evidence': [], 'authority': 'user_quoted', 'witness': None, 'physics_critical': True}
    merged = rr.merge(floor, additions(PROMPT, facts=[fact]), PROMPT)
    added = merged['facts'][-1]
    assert added['authority'] == 'inferred'
    assert any(added['id'] in a['blocks'] and a['physics_critical'] for a in merged['ambiguities'])


def test_a_host_reading_that_deletes_or_weakens_a_reader_item_is_refused():
    floor = rr.document(PROMPT)
    deleted = deepcopy(floor); deleted['ambiguities'] = deleted['ambiguities'][:-1]
    deleted['authors'].append(rr.author('host-agent'))
    with pytest.raises(ValueError, match='deletes or weakens'):
        rr.merge(floor, deleted, PROMPT)
    weakened = deepcopy(floor); weakened['authors'].append(rr.author('host-agent'))
    row = next(a for a in weakened['ambiguities'] if a['physics_critical'])
    row['physics_critical'] = False
    with pytest.raises(ValueError, match='deletes or weakens'):
        rr.merge(floor, weakened, PROMPT)
    replaced = additions(PROMPT, facts=[dict(floor['facts'][0])])
    with pytest.raises(ValueError, match='may not replace'):
        rr.merge(floor, replaced, PROMPT)


def test_a_host_delegation_constraint_never_grants_authority():
    floor = rr.document(PROMPT)
    row = {'id': f'K{len(floor["constraints"]) + 1}', 'type': 'delegation',
           'value': {'phrase': 'tell us', 'authority_granted': True}, 'evidence': [rr.span(PROMPT, 30, 37)]}
    merged = rr.merge(floor, additions(PROMPT, constraints=[row]), PROMPT)
    assert merged['constraints'][-1]['value']['authority_granted'] is False


def test_additions_for_another_request_are_refused():
    with pytest.raises(ValueError, match='different request'):
        rr.merge(rr.document(PROMPT), additions(PROMPT + ' '), PROMPT)


# ------------------------------------------------------------------ determinism and schema discipline
def test_the_same_bytes_give_the_same_reading_hash_in_a_fresh_process():
    prompts = [CASES[k] for k in ('G1', 'R12-prescribed-stat', 'U05b', 'Q38')]
    here = [rr.digest(rr.document(p)) for p in prompts]
    code = ('import json,sys; from ravel.workflow import request_reading as rr; '
            'print(json.dumps([rr.digest(rr.document(p)) for p in json.load(sys.stdin)]))')
    env = {**os.environ, 'PYTHONHASHSEED': '2014'}
    out = subprocess.run([sys.executable, '-B', '-c', code], input=json.dumps(prompts), capture_output=True,
                         text=True, env=env, check=True)
    assert json.loads(out.stdout) == here


EVALUATED = {'type', 'properties', 'required', 'additionalProperties', 'enum', 'const', 'pattern', 'items',
             'minItems', 'maxItems', 'anyOf', 'minLength', 'minimum', 'maximum', 'exclusiveMinimum',
             'exclusiveMaximum'}


def _keywords(schema):
    if isinstance(schema, dict):
        for key, value in schema.items():
            yield key
            if key == 'properties':
                for sub in value.values():
                    yield from _keywords(sub)
            elif key in ('items', 'additionalProperties') and isinstance(value, dict):
                yield from _keywords(value)
            elif key == 'anyOf':
                for sub in value:
                    yield from _keywords(sub)


@pytest.mark.parametrize('schema', [rr.READING_SCHEMA, rr.ADDITIONS_SCHEMA])
def test_reading_schemas_use_only_keywords_the_stdlib_validator_evaluates(schema):
    assert set(_keywords(schema)) <= EVALUATED


def test_vocabularies_are_closed_and_name_no_workflow_paper_or_benchmark():
    words = [*rr.ARTIFACT_KINDS, *rr.CLAIM_KINDS, *rr.BOUNDARY_CLASSES, *rr.CONSTRAINT_TYPES, *rr.DISMISSALS,
             *rr.FIELD_AUTHORITY]
    assert len(rr.ARTIFACT_KINDS) == 13 and len(rr.CLAIM_KINDS) == 9 and len(rr.BOUNDARY_CLASSES) == 6
    assert len(rr.CONSTRAINT_TYPES) == 12
    banned = ('bench', 'challenge', 'atlas', 'cms', 'lhcb', 'collider', 'task', 'agentic', 'reproduce',
              'reinterpret', 'scan', 'arxiv')
    assert not [w for w in words if any(b in w.lower() for b in banned)]


def test_a_delegated_physics_critical_default_carries_its_anchor_and_is_listed_for_checkin3():
    prompt = CASES['G1']
    reading = rr.document(prompt)
    row = next(a for a in reading['ambiguities'] if a['issue'].startswith('integrated luminosity'))
    assert rr.adopted_defaults(reading) == []
    row['readings'].append({'id': 'practice', 'value': {'luminosity': 'the projection study value'},
                            'authority': 'adapter_default', 'source': None})
    row['status'] = 'resolved'
    pin = {'path': 'references/authoritative-practice.json', 'sha256': '0' * 64}
    row['resolution'] = {'reading': 'practice', 'by': 'delegation', 'evidence': pin, 'utc': '2026-10-11T00:00:00Z'}
    assert rr.check(reading, prompt) == []
    listed = rr.adopted_defaults(reading)
    assert [(r['ambiguity'], r['anchor_kind'], r['authority']) for r in listed] == [
        (row['id'], 'pinned_reference', 'adapter_default')]
    row['resolution']['evidence'] = {'start': 0, 'end': 4, 'text': 'nope'}
    assert any('anchor span' in e for e in rr.check(reading, prompt))
    row['resolution']['reading'] = 'absent'
    assert any('does not offer' in e for e in rr.check(reading, prompt))
