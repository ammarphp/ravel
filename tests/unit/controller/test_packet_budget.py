"""Instruction packet budgets from declared model windows, delivery by reference and typed refusal.

Fictional models and steps only; the instruction catalogue, role cards and capability catalogue are
the installed ones. No model, provider, network or native tool runs.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.controller import instructions as ins
from ravel.controller.instructions import budget as packet_budget, delivery
from ravel.workflow import role_registry

ROLE = 'trap-auditor'
INPUTS = [{'artifact': 's05:outputs/run_card.json', 'sha256': 'b' * 64}]


def catalogue(*rows):
    return {'models': [{'tiers': ['agent', 'judgment', 'cheap'], 'status': 'current', **row} for row in rows]}


def preferences(models):
    return {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': list(models),
            'tier_models': {tier: dict(models) for tier in ('agent', 'judgment', 'cheap')}}


def step(**parameters):
    return {'id': 's07', 'kind': 'review', 'role': ROLE, 'inputs': INPUTS, 'outputs': [], 'depends_on': ['s05'],
            'protocols': [], 'review': [], 'instruction_sources': [], 'obligations': [], 'parameters': parameters}


def build(current, budget=None):
    card = role_registry.load(ROLE)
    manifest = ins.manifest(current, card)
    return card, manifest, ins.packet(manifest, card, current, INPUTS, budget=budget)


def fixed_budget(tokens):
    return {'schema_version': 1, 'kind': 'instruction-packet-budget', 'packet_tokens': tokens, 'basis': 'fixture',
            'binding_model': 'fixture-model', 'tiers': ['agent'], 'candidates': []}


def test_the_budget_is_the_smallest_declared_input_window_of_the_seat_candidates():
    models = catalogue({'id': 'wide-model', 'context_tokens': 900_000, 'max_output_tokens': 100_000},
                       {'id': 'narrow-model', 'context_tokens': 300_000, 'max_output_tokens': 50_000})
    card = role_registry.load(ROLE)
    budget = packet_budget.seat_budget(card, preferences({'t1': 'wide-model', 't2': 'narrow-model'}),
                                       catalogue=models)
    assert budget['packet_tokens'] == 250_000 and budget['binding_model'] == 'narrow-model'
    assert budget['basis'] == 'frozen_preferences'
    assert {c['model'] for c in budget['candidates']} == {'wide-model', 'narrow-model'}
    # Another provider's window changes the budget: nothing is a fixed number.
    wider = packet_budget.seat_budget(card, preferences({'t1': 'wide-model'}), catalogue=models)
    assert wider['packet_tokens'] == 800_000


def test_an_undeclared_window_is_budgeted_at_the_smallest_declared_catalogue_window_and_says_so():
    models = catalogue({'id': 'listed-without-window'},
                       {'id': 'small-declared', 'context_tokens': 120_000, 'max_output_tokens': 20_000},
                       {'id': 'large-declared', 'context_tokens': 1_000_000, 'max_output_tokens': 100_000})
    card = role_registry.load(ROLE)
    budget = packet_budget.seat_budget(card, preferences({'t1': 'listed-without-window'}), catalogue=models)
    assert budget['packet_tokens'] == 100_000
    [candidate] = budget['candidates']
    assert candidate['basis'] == 'undeclared_window_catalogue_floor' and candidate['floor_model'] == 'small-declared'


def test_without_frozen_preferences_the_projection_uses_current_models_for_the_card_tiers():
    models = catalogue({'id': 'current-a', 'context_tokens': 500_000, 'max_output_tokens': 50_000},
                       {'id': 'legacy-b', 'context_tokens': 100_000, 'max_output_tokens': 10_000,
                        'status': 'legacy'})
    budget = packet_budget.seat_budget(role_registry.load(ROLE), None, catalogue=models)
    assert budget['basis'] == 'catalogue_projection' and budget['packet_tokens'] == 450_000


def test_no_declared_window_anywhere_is_a_typed_refusal_with_its_remedy():
    with pytest.raises(packet_budget.BudgetUnavailable) as refused:
        packet_budget.seat_budget(role_registry.load(ROLE), None, catalogue=catalogue({'id': 'opaque'}))
    assert 'context_tokens' in refused.value.remedy


def test_the_capability_catalogue_is_a_compact_index_with_the_complete_data_attached():
    card, manifest, built = build(step())
    context = built['capability_context']
    for row in context['catalogue']['entries']:
        assert row['id'] + ' | cost=' + str(row['cost_class']) in built['text']
    assert context['catalogue_sha256'] in built['text'] and 'capabilities-*.json input shards' in built['text']
    assert built['budget']['packet_tokens'] > 0 and built['references'] == []


def test_large_step_values_move_by_reference_and_every_mandatory_part_stays_inline():
    bulky = ['evidence row %05d ' % i + 'x' * 120 for i in range(4000)]
    current = step(review_items=[{'id': 'r1', 'note': 'kept'}], evidence=bulky)
    card, manifest, whole = build(current)
    assert whole['references'] == []  # the declared window holds it: nothing moves
    budget = fixed_budget(whole['tokens'] - 20_000)
    card, manifest, built = build(current, budget)
    assert built['tokens'] <= budget['packet_tokens']
    [reference] = built['references']
    assert reference['pointer'] == '#/parameters/evidence' and reference['value'] == bulky
    raw = delivery.reference_bytes(reference)
    assert reference['sha256'] == hashlib.sha256(raw).hexdigest() and reference['bytes'] == len(raw)
    assert f'"$packet_reference":"{reference["name"]}"' in built['text']
    spec = json.loads(next(line for line in built['text'].splitlines() if line.startswith('{"')))
    placeholder = spec['parameters']['evidence']
    assert placeholder == {'$packet_reference': reference['name'], 'sha256': reference['sha256'],
                           'bytes': reference['bytes'], 'excerpt': raw.decode()[:delivery.EXCERPT_CHARS]}
    assert '"note":"kept"' in built['text']
    # The card, every duty unit and the output contract stay inline; nothing is deferred that must not be.
    assert json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False) in built['text']
    duties = [e for e in manifest['units'] if e['kind'] == 'duty']
    assert duties and not set(built['deferred']) & {e['id'] for e in duties}
    for entry in duties:
        assert f'--- [duty] {entry["id"]} ' in built['text']
    # The dispatch check rebuilds the same packet under the same budget and refuses any altered reference.
    assert ins.check_packet(built, manifest, card, current, INPUTS, budget=budget) == []
    altered = deepcopy(built)
    altered['references'][0]['value'] = bulky[:-1]
    assert ins.check_packet(altered, manifest, card, current, INPUTS, budget=budget)


def test_a_core_beyond_the_budget_is_refused_with_its_remedy_never_truncated():
    card, manifest, whole = build(step())
    with pytest.raises(delivery.PacketBudgetExceeded) as refused:
        build(step(), fixed_budget(whole['tokens'] // 3))
    assert refused.value.code == 'packet_budget_exceeded'
    assert 'larger' in refused.value.remedy and 'not truncated' in str(refused.value)


def test_the_selected_model_must_hold_the_packet():
    models = catalogue({'id': 'roomy', 'context_tokens': 400_000, 'max_output_tokens': 40_000},
                       {'id': 'tight', 'context_tokens': 60_000, 'max_output_tokens': 10_000})
    assert packet_budget.selected_problem({'model': 'roomy'}, 100_000, catalogue=models) is None
    problem = packet_budget.selected_problem({'model': 'tight'}, 100_000, catalogue=models)
    assert problem and "'tight'" in problem and 'larger declared context window' in problem


def test_every_installed_route_projection_packet_fits_its_declared_budget():
    """The installed envelopes compile every route's sessions at every tier; each packet fits its seat budget."""
    from ravel.controller.engagement.records import data
    envelopes = data('envelopes.json')
    assert envelopes['status'] == 'ready'
    checked = 0
    for route, tiers in envelopes['packets'].items():
        for tier, sessions in tiers.items():
            for session in sessions:
                role = session['key'].rsplit(':', 1)[-1]
                try:
                    card = role_registry.load(role)
                except (KeyError, ValueError, OSError):
                    card = None
                limit = packet_budget.seat_budget(card)['packet_tokens']
                assert 0 < session['packet_tokens'] <= limit, (route, tier, session['key'])
                checked += 1
    assert checked > 100
