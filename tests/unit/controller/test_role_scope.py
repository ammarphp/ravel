"""Installed role guidance follows the seat and its contracted route."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller import instructions as ins
from ravel.controller.instructions import catalogue, delivery
from ravel.paths import repository_root
from ravel.workflow import role_registry


def test_every_role_preamble_preserves_the_requested_quantity_and_method_choice():
    cat = catalogue.installed()
    for card in role_registry.all_cards():
        step = {'id': 'advisory', 'kind': 'derive', 'role': card['id']}
        manifest = ins.manifest(step, card)
        text = '\n'.join(cat.units[e['id']]['text'] for e in manifest['units'] if e['via'] == 'preamble')
        text = ' '.join(text.split())
        assert 'the **step-8 mass-plane scan' not in text, card['id']
        assert 'pyhf' not in text.lower() and 'mass-plane' not in text.lower(), card['id']
        assert 'no external paper or reference is required' not in text, card['id']
        assert 'macOS / Apple Silicon' not in text, card['id']
        assert 'requested quantities, units, domain and uncertainty conventions' in text, card['id']
        assert 'Select methods from the task contract and source evidence' in text, card['id']


@pytest.mark.parametrize('route', ['research', 'calculation', 'measurement', 'manuscript'])
def test_scope_is_derived_from_the_effective_card_and_route_and_checked_on_dispatch(route):
    card = role_registry.load('consult-theory')
    step = {'id': 'advisory', 'kind': 'derive', 'role': card['id'], 'route': route,
            'stage': 'planning', 'outputs': []}
    scope = delivery.seat_scope(step, card)
    assert scope['role'] == card['id'] and scope['purpose'] == card['purpose']
    assert scope['route'] == route and scope['stage'] == 'planning'
    manifest = ins.manifest(step, card)
    assert scope['response_schema'] == ins.output_schema(card, manifest)[0]
    packet = ins.packet(manifest, card, step, [])
    assert '== Seat scope ==' in packet['text']
    assert ins.check_packet(packet, manifest, card, step, []) == []
    assert ins.check_packet(packet, manifest, card, {**step, 'route': 'changed'}, [])
    changed = deepcopy(card)
    changed['purpose'] = 'Changed advisory duty'
    assert delivery.seat_scope(step, changed)['purpose'] != scope['purpose']


@pytest.mark.parametrize(('role', 'reading'), [
    ('consult-cosmology', 'doc:docs/workflow/steps/cosmology-solvers.md'),
    ('consult-latex', 'doc:docs/reference/staged-manuscript-authoring.md'),
    ('consult-onnx', 'doc:docs/reference/classifier-inputs.md'),
    ('consult-symbolic', 'doc:docs/reference/symbolic-evaluation.md'),
    ('consult-theory', 'proto:P2'),
])
def test_advisory_cards_deliver_domain_guidance_and_a_concrete_handoff(role, reading):
    card = role_registry.load(role)
    assert reading in card['knowledge']['must_read']
    manifest = ins.manifest({'id': 'advisory', 'kind': 'derive', 'role': role}, card)
    expected = catalogue.installed().resolve('knowledge:' + reading)
    assert expected and set(expected) <= {e['id'] for e in manifest['units'] if e['via'] == 'must_read'}
    assert any('advisory handoff' in line for line in card['protocol'])


def test_stage_response_cards_explain_the_final_record_and_artifact_mapping():
    cards = [card for card in role_registry.all_cards()
             if any('subject_sha256' in line and 'attributed_claim_ids' in line for line in card['protocol'])]
    assert cards
    for card in cards:
        text = ' '.join(card['protocol'])
        assert 'packet\'s Output contract' in text, card['id']
        assert 'declared output artifact' in text, card['id']
        assert 'stage response schema' in text, card['id']


@pytest.mark.parametrize('role', ['baseline-producer', 'comparative-reviewer'])
def test_stage_artifact_and_final_record_keep_their_own_contracts_in_protected_custody(tmp_path, role):
    from jsonschema import Draft202012Validator
    from ravel.controller.store import RunStore
    card = role_registry.load(role)
    assert any("packet's Output contract" in line for line in card['protocol'])
    output = 'outputs/stage-response.json'
    step = {'id': 'stage-response', 'kind': 'derive', 'role': role,
            'outputs': [{'path': output, 'kind': 'research-stage-response', 'required': True}]}
    manifest = ins.manifest(step, card)
    packet = ins.packet(manifest, card, step, [])
    schema_id, schema = ins.output_schema(card, manifest)
    domain = {'stage': 'method-review', 'role_id': role, 'subject_sha256': 'b' * 64,
              'verdict': 'accept', 'findings': [], 'attributed_claim_ids': []}
    acknowledgement = {'instruction_ack': {'manifest_sha256': manifest['sha256']},
                       'checklist': [{'unit': e['id'], 'status': 'done',
                                      'evidence': output + '#/subject_sha256', 'note': None}
                                     for e in manifest['units'] if e['kind'] == 'duty'],
                       'handoff': None, 'escalation': []}
    if schema_id == 'producer.v2':
        final = {'schema_version': 2, 'kind': 'producer-result',
                 'outputs': [{'path': output, 'kind': 'research-stage-response'}],
                 'decisions': [], 'knowledge_used': [], **acknowledgement}
    else:
        final = {'schema_version': 3, 'kind': 'findings', 'items': [], 'item_verdicts': [], **acknowledgement}
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(final))
    assert list(validator.iter_errors({**final, **domain}))
    store = RunStore('stage-custody', root=tmp_path / 'store')
    try:
        binding = {'run_id': store.run_id, 'step': step['id'], 'attempt': 1,
                   'manifest_sha256': manifest['sha256'], 'packet_sha256': packet['sha256']}
        session = store.append('worker-session', {**binding, 'packet': packet, 'step_spec': step,
                                                 'card': card, 'inputs': []})
        store.append('step-attempt', {**binding, 'session': session})
        target = store.path('instruction-artifacts', session, *Path(output).parts)
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(domain))
        completion = store.append('worker-completion', {**binding, 'session': session, 'final_record': final,
            'artifacts': [{'path': output, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}]})
        with ins.observed_completion(store, session=session, completion_id=completion):
            assert ins.check_ack(manifest, final, [output]) == []
        assert json.loads(target.read_text()) == domain
        assert store.read('worker-completion', completion)['record']['final_record'] == final
        target.write_text(json.dumps({**domain, 'subject_sha256': 'c' * 64}))
        with ins.observed_completion(store, session=session, completion_id=completion):
            assert ins.check_ack(manifest, final, [output])
    finally:
        store.close()


def test_cost_guidance_retains_the_original_requested_domain():
    text = (Path(repository_root()) / '.claude/skills/cost-preflight/SKILL.md').read_text()
    assert 'shrink the grid to the published' not in text
    assert 'Retain every originally requested point' in text
    assert 'approved scope change' in text
