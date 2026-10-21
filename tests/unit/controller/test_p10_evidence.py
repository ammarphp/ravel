"""Inert adopted-descriptor and instruction controls for ordinary child studies."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ravel.controller.routes.study import evidence


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir()
        self.run_id = 'fictional-evidence'
        self.rows = []

    def append(self, kind, record):
        value = json.loads(json.dumps(record, allow_nan=False))
        identifier = str(len(self.rows) + 1)
        self.rows.append({'id': identifier, 'kind': kind, 'record': value})
        return identifier

    def scan(self, kind):
        return deepcopy([row for row in self.rows if row['kind'] == kind])

    def read(self, kind, identifier):
        return next(row for row in self.scan(kind) if row['id'] == identifier)

    def path(self, *parts):
        return self.root.joinpath(*parts)


@pytest.fixture
def env(tmp_path):
    run = tmp_path / 'run'
    run.mkdir()
    store = Store(tmp_path / 'protected-custody')
    assert not store.root.is_relative_to(run)
    return store, {'run_dir': str(run), 'store': store}


def adopt(env, artifact, value):
    store, context = env
    destination = 'adopted/' + artifact.replace(':', '/')
    path = Path(context['run_dir']) / destination
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    store.append('custody', {'artifact': artifact, 'destination': destination,
                            'sha256': pin, 'status': 'accepted'})
    return pin, path


DESCRIPTORS = {
    'P05': {'basis': ['signed_a', 'signed_b'], 'units': 'fictional_unit',
            'sign_convention': 'signed contribution', 'covariance': [[2, -0.3], [-0.3, 3]],
            'population': ['left', 'right']},
    'E07': {'pdf_member': 3, 'generation_settings': {'scale': 17, 'cut': 2}},
    'E08': {'spectrum': {'state_a': 103, 'state_b': 7}, 'invisible_states': ['state_b']},
    'E10': {'beam_energy': [137, 137], 'seed': 31},
    'E13': {'weight_names': ['nominal'], 'reentrant': False},
    'E17': {'bin_ids': ['left', 'right']},
    'E18': {'perturbative_order': 'supplied_order', 'process_basis': ['positive', 'negative']},
    'R08': {'units': 'fictional_unit', 'statistic': 'supplied quadratic form'},
}


def rows(store, kind='study-evidence'):
    return [r['record'] for r in store.scan(kind)]


def continuity(env, row, monkeypatch=None):
    store, context = env
    expected = deepcopy(DESCRIPTORS[row])
    assert set(expected) == set(evidence.FIELDS[row])
    adopt(env, 'inputs:expected.json', expected)
    observed_sha, _ = adopt(env, 'outputs:observed.json', expected)
    binding = {'row': row, 'expected': 'inputs:expected.json', 'observed': 'outputs:observed.json',
               'validator': 'descriptor-continuity'}
    if row == 'E08':
        from ravel.workflow import review_independence
        binding['review'] = {'subject_sha256': observed_sha, 'reviewer': 'fictional reviewer'}
        monkeypatch.setattr(review_independence, 'decide',
            lambda query: {'independent': query.get('subject_sha256') == observed_sha})
    step = {'id': 'operate', 'operation': 'fictional-operation',
            'parameters': {'evidence_requirements': [binding]}}
    assert evidence.check(store, step, context, phase='review') == []
    positive = rows(store)[-1]
    assert positive['status'] == 'satisfied'
    assert positive['observed_sha256'] == observed_sha
    assert positive['expected_sha256']
    assert positive['binding_sha256']
    assert positive['labels'] == []
    for field in evidence.FIELDS[row]:
        for change in ('missing', 'mutated'):
            actual = deepcopy(expected)
            if change == 'missing':
                actual.pop(field)
            elif type(actual[field]) is bool:
                actual[field] = not actual[field]
            elif type(actual[field]) is int:
                actual[field] += 1
            elif type(actual[field]) is list:
                actual[field] = [*actual[field], 'changed component']
            elif type(actual[field]) is dict:
                actual[field]['changed component'] = 19
            else:
                actual[field] = 'changed descriptor'
            adopt(env, binding['observed'], actual)
            findings = evidence.check(store, step, context, phase='review')
            assert findings and findings[0]['row'] == row
            assert findings[0]['code'] == 'scientific_evidence_unresolved'
            assert rows(store)[-1]['status'] == 'violated'
            assert rows(store)[-1]['findings']
            assert store.read('study-evidence', findings[0]['record_id'])['record']['row'] == row
    # Artifact bytes changed without new accepted custody must also be rejected.
    _, observed_path = adopt(env, binding['observed'], expected)
    observed_path.write_text('{}')
    assert evidence.check(store, step, context, phase='review')
    assert rows(store)[-1]['status'] == 'violated'
    return step, observed_sha


def test_P05_adopted_basis_signed_covariance_and_population(env):
    continuity(env, 'P05')


def test_E07_adopted_member_and_generation_settings(env):
    continuity(env, 'E07')


def test_E08_exact_spectrum_requires_independent_observed_subject(env, monkeypatch):
    step, observed_sha = continuity(env, 'E08', monkeypatch)
    store, context = env
    adopt(env, 'outputs:observed.json', DESCRIPTORS['E08'])
    from ravel.workflow import review_independence
    monkeypatch.setattr(review_independence, 'decide', lambda query: {'independent': False})
    assert evidence.check(store, step, context, phase='review')
    assert 'independent review' in rows(store)[-1]['findings'][0]
    # A distinct subject is refused before independence credit is requested.
    step['parameters']['evidence_requirements'][0]['review']['subject_sha256'] = '0' * 64
    assert evidence.check(store, step, context, phase='review')
    assert 'exact executed evidence digest' in rows(store)[-1]['findings'][0]


def test_E09_external_recipe_and_actual_sources_precede_any_effect(env):
    store, context = env
    _, source_path = adopt(env, 'source:recipe-source.json', {'text': 'Fictional exact source instructions.'})
    recipe = {'kind': 'external-generation-recipe', 'schema_version': 1,
              'operation': 'fictional-generation', 'instructions': 'Apply the supplied finite settings.',
              'sources': ['source:recipe-source.json']}
    _, recipe_path = adopt(env, 'inputs:recipe.json', recipe)
    step = {'id': 'operate', 'operation': 'fictional-generation',
            'parameters': {'evidence_requirements': [{'row': 'E09', 'expected': 'inputs:recipe.json'}]}}
    effects = []
    def guarded_dispatch():
        errors = evidence.check(store, step, context, phase='dispatch')
        if not errors:
            effects.append('inert generation')
        return errors
    assert guarded_dispatch() == [] and len(effects) == 1
    assert rows(store)[-1]['status'] == 'satisfied'
    effects.clear()
    source_path.unlink()
    assert guarded_dispatch() and not effects
    assert rows(store)[-1]['status'] == 'violated'
    adopt(env, 'source:recipe-source.json', {'text': 'Fictional exact source instructions.'})
    recipe_path.unlink()
    assert guarded_dispatch() and not effects
    for changed in ({**recipe, 'operation': 'different-operation'}, {**recipe, 'sources': []},
                    {**recipe, 'instructions': ''}, {**recipe, 'sources': ['source:absent.json']}):
        adopt(env, 'inputs:recipe.json', changed)
        assert guarded_dispatch() and not effects
        assert rows(store)[-1]['status'] == 'violated'
        assert rows(store)[-1]['row'] == 'E09'


def test_E10_adopted_beam_energy_and_seed(env):
    continuity(env, 'E10')


def test_E13_adopted_weights_and_nonreentrant_merge(env):
    step, _ = continuity(env, 'E13')
    store, context = env
    adopt(env, 'outputs:observed.json', {**DESCRIPTORS['E13'], 'merged': True})
    assert evidence.check(store, step, context, phase='review')
    assert 'non-reentrant' in rows(store)[-1]['findings'][0]


def test_E17_adopted_bin_pairing(env):
    continuity(env, 'E17')


def test_E18_adopted_order_and_signed_process_basis(env):
    continuity(env, 'E18')


def test_R08_adopted_units_and_requested_statistic(env):
    continuity(env, 'R08')


def test_unknown_scientific_validator_remains_pending(env):
    store, context = env
    adopt(env, 'inputs:expected.json', DESCRIPTORS['R08'])
    adopt(env, 'outputs:observed.json', DESCRIPTORS['R08'])
    step = {'id': 'operate', 'parameters': {'evidence_requirements': [{
        'row': 'R08', 'expected': 'inputs:expected.json', 'observed': 'outputs:observed.json',
        'validator': 'unavailable-fictional-validator'}]}}
    findings = evidence.check(store, step, context, phase='review')
    assert findings and findings[0]['code'] == 'scientific_evidence_unresolved'
    record = rows(store)[-1]
    assert record['status'] == 'pending'
    assert record['labels'] == ['scientific_validator_unavailable']
    assert record['findings']


def test_self_comparison_binding_is_refused_before_any_evidence_record(env):
    store, context = env
    adopt(env, 'inputs:expected.json', DESCRIPTORS['R08'])
    step = {'id': 'operate', 'parameters': {'evidence_requirements': [{
        'row': 'R08', 'expected': 'inputs:expected.json', 'observed': 'inputs:expected.json',
        'validator': 'descriptor-continuity'}]}}
    with pytest.raises(ValueError, match='observed artifact'):
        evidence.check(store, step, context, phase='review')
    assert rows(store) == []


@pytest.mark.parametrize('row', ['STEP-cosmology-solvers', 'STEP-eft-conventions', 'STEP-sfitter'],
                         ids=lambda row: row)
def test_specialist_delivered_units_acknowledgement_and_receipt(env, monkeypatch, row):
    store, context = env
    fake = ModuleType('ravel.controller.instructions')
    unit_ids = [row + ':duty', row + ':escalation']
    manifest = {'sha256': 'd' * 64, 'units': [{'id': u, 'sha256': 'e' * 64} for u in unit_ids]}
    calls = []
    def make_manifest(step, card):
        calls.append('manifest')
        assert step['instruction_sources'] == ['docs/workflow/steps/' + row[5:] + '.md']
        return deepcopy(manifest)
    def make_packet(actual, card, step, inputs):
        calls.append('packet')
        assert actual == manifest
        return {'sha256': 'f' * 64, 'manifest': actual}
    def check_packet(packet):
        return [] if packet['manifest'] == manifest else ['altered packet']
    def check_ack(actual, final, outputs):
        calls.append('check_ack')
        failures = []
        if final.get('instruction_ack', {}).get('manifest_sha256') != actual['sha256']:
            failures.append('manifest mismatch')
        checklist = final.get('checklist', [])
        if [item.get('unit') for item in checklist] != unit_ids:
            failures.append('one complete checklist row per delivered unit required')
        if any(item.get('status') != 'done' or item.get('evidence') not in outputs for item in checklist):
            failures.append('checklist evidence required')
        if final.get('escalation') != 'none':
            failures.append('explicit escalation disposition required')
        return failures
    fake.manifest, fake.packet, fake.check_packet, fake.check_ack = make_manifest, make_packet, check_packet, check_ack
    import ravel.controller as controller
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(controller, 'instructions', fake, raising=False)
    step = {'id': 'operate', 'instruction_sources': ['docs/workflow/steps/' + row[5:] + '.md']}
    final = {'instruction_ack': {'manifest_sha256': manifest['sha256']},
             'checklist': [{'unit': u, 'status': 'done', 'evidence': 'outputs/result.json'} for u in unit_ids],
             'escalation': 'none'}
    assert evidence.instruction_errors(store, step, context, final, ['outputs/result.json']) == []
    assert rows(store, 'study-instructions')[-1]['errors'] == []
    assert set(calls) == {'manifest', 'packet', 'check_ack'}
    for field in ('instruction_ack', 'checklist', 'escalation'):
        changed = deepcopy(final)
        changed.pop(field)
        failures = evidence.instruction_errors(store, step, context, changed, ['outputs/result.json'])
        assert failures and all(f['code'] == 'instruction_ack_invalid' for f in failures)
        receipt = rows(store, 'study-instructions')[-1]
        assert receipt['errors'] and receipt['packet_sha256'] == 'f' * 64
        assert receipt['manifest'] == manifest
        assert receipt['final_sha256'] == evidence.digest(changed)


def staged_E08(env):
    store, context = env
    adopt(env, 'inputs:expected-spectrum', DESCRIPTORS['E08'])
    observed_sha, path = adopt(env, 'outputs:candidate-spectrum', DESCRIPTORS['E08'])
    custody = deepcopy(rows(store, 'custody')[-1])
    custody['status'] = 'staged'
    store.append('custody', custody)
    step = {'id': 'candidate', 'parameters': {'evidence_requirements': [{
        'row': 'E08', 'expected': 'inputs:expected-spectrum', 'observed': 'outputs:candidate-spectrum',
        'validator': 'descriptor-continuity', 'review': {'subject_sha256': observed_sha}}]}}
    return step, path, custody


def test_E08_staged_candidate_integrity_is_pending_until_actual_review(env, monkeypatch):
    from ravel.workflow import review_independence
    store, context = env
    step, _, custody = staged_E08(env)
    calls = []
    monkeypatch.setattr(review_independence, 'decide', lambda query: calls.append(query) or {'independent': False})
    assert evidence.check(store, step, {**context, 'allow_staged_evidence': True}, phase='adopt') == []
    candidate = rows(store)[-1]
    assert candidate['status'] == 'pending'
    assert 'operation_review_pending' in candidate['labels']
    assert 'credit' not in candidate and calls == []
    assert 'accepted' not in candidate['labels']
    store.append('custody', {**custody, 'status': 'accepted'})
    assert evidence.check(store, step, context, phase='review')
    assert rows(store)[-1]['status'] == 'violated'
    assert len(calls) == 1


def test_staged_observed_bytes_require_explicit_candidate_permission_and_unchanged_pin(env):
    store, context = env
    step, path, _ = staged_E08(env)
    assert evidence.check(store, step, context, phase='adopt')
    assert rows(store)[-1]['status'] == 'violated'
    path.write_text('{}')
    assert evidence.check(store, step, {**context, 'allow_staged_evidence': True}, phase='adopt')
    assert rows(store)[-1]['status'] == 'violated'
    assert 'digest' in rows(store)[-1]['findings'][0]


def test_pending_candidate_is_recorded_without_forbidden_pending_transition(tmp_path, monkeypatch):
    from ravel.controller import ledger
    from p02_support import FakeStore, fixture_catalogue, row, use_catalogue
    from ravel.workflow import review_independence
    store = FakeStore('pending-candidate', root=tmp_path / 'protected')
    use_catalogue(monkeypatch, fixture_catalogue([row('E08', 'study.evidence', 'intake', 'run')]))
    [key] = ledger.materialise(store, 'intake',
        {'run_id': store.run_id, 'task_mode': 'calculate', 'deliverables': []})
    root = tmp_path / 'run'
    root.mkdir()
    env = store, {'run_dir': str(root), 'store': store}
    step, _, custody = staged_E08(env)
    step['parameters']['evidence_requirements'][0]['entry_ids'] = [key]
    assert evidence.check(store, step, {**env[1], 'allow_staged_evidence': True}, phase='adopt') == []
    assert rows(store)[-1]['status'] == 'pending'
    assert ledger.current(store)[0]['status'] == 'pending'
    store.append('custody', {**custody, 'status': 'accepted'})
    monkeypatch.setattr(review_independence, 'decide', lambda query: {'independent': True})
    assert evidence.check(store, step, env[1], phase='review') == []
    assert ledger.current(store)[0]['status'] == 'satisfied'
