"""P03 acknowledgement, reviewer items and the acknowledging output schemas producer.v2 and findings.v3."""
from copy import deepcopy
import hashlib
import json

from test_p03_observed import observed, scope, reviewed_catalogue

import pytest

from ravel.controller import instructions as ins
from ravel.controller.instructions import ack
from ravel.workflow import role_registry

OUTPUT = 'outputs/result.json'


@pytest.fixture(scope='module')
def produced():
    card = role_registry.load('generator')
    step = {'id': 's07', 'kind': 'operate', 'instruction_sources': ['docs/workflow/steps/03-generate.md'],
            'stage': 'analysis'}
    manifest = ins.manifest(step, card)
    return card, step, manifest


@pytest.fixture
def check_ack(produced, tmp_path):
    card, step, original_manifest = produced
    count = 0

    def check(manifest, record, outputs):
        nonlocal count
        count += 1
        if not isinstance(record, dict) or manifest.get('sha256') is None:
            return ins.check_ack(manifest, record, outputs)
        store, session, completion, _, _, _, path = observed(
            tmp_path / str(count), card=card, step=step, manifest=original_manifest, record=record)
        path.write_text(json.dumps({'outputs': [{'kind': 'events'}]}))
        store.records['worker-completion'][completion]['artifacts'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with scope(store, session, completion):
            return ins.check_ack(manifest, record, outputs)
    return check


def complete(manifest, *, schema_version=2):
    rows = [{'unit': e['id'], 'status': 'done', 'evidence': OUTPUT + '#/outputs/0', 'note': None}
            for e in manifest['units'] if e['kind'] == 'duty']
    return {'schema_version': schema_version, 'kind': 'producer-result',
            'outputs': [{'path': OUTPUT, 'kind': 'events'}], 'decisions': [], 'knowledge_used': [], 'handoff': None,
            'instruction_ack': {'manifest_sha256': manifest['sha256']}, 'checklist': rows, 'escalation': []}


def duty(manifest, n=0):
    return [e['id'] for e in manifest['units'] if e['kind'] == 'duty'][n]


def test_a_complete_acknowledgement_is_accepted(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    assert check_ack(manifest, record, [OUTPUT]) == []
    assert ins.validate_record('producer.v2', record) == []


def test_a_missing_row_fails_the_step(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    gone = record['checklist'].pop(4)['unit']
    assert check_ack(manifest, record, [OUTPUT]) == [f'missing: {gone}: no checklist row for a duty unit']


def test_a_dangling_evidence_pointer_fails(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    record['checklist'][0]['evidence'] = 'outputs/from-an-earlier-attempt.json#/x'
    errors = check_ack(manifest, record, [OUTPUT])
    assert errors == [f'evidence: {duty(manifest)}: \'outputs/from-an-earlier-attempt.json#/x\' names no output '
                      'written in this attempt']
    record['checklist'][0]['evidence'] = None
    assert check_ack(manifest, record, [OUTPUT]) == [f'evidence: {duty(manifest)}: done without an evidence pointer']


def test_final_record_pointers_resolve_inside_the_record(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    record['checklist'][0]['evidence'] = 'final_record#/outputs/0/kind'
    assert check_ack(manifest, record, [OUTPUT]) == []
    record['checklist'][0]['evidence'] = 'final_record#/decisions/3'
    assert check_ack(manifest, record, [OUTPUT])[0].startswith(f'evidence: {duty(manifest)}:')
    record['checklist'][0]['evidence'] = './outputs/result.json'
    assert check_ack(manifest, record, [OUTPUT]) == []


def test_evidence_never_points_into_the_acknowledgement_itself(produced, check_ack):
    """A row cannot cite the checklist or the acknowledgement as its own evidence; other fields of the
    final record remain citable (positive control)."""
    _, _, manifest = produced
    for pointer in ('final_record#/checklist', 'final_record#/checklist/0/status', 'final_record#/instruction_ack',
                    'final_record#/instruction_ack/manifest_sha256'):
        record = complete(manifest)
        record['checklist'][0]['evidence'] = pointer
        errors = check_ack(manifest, record, [OUTPUT])
        assert errors == [f'evidence: {duty(manifest)}: {pointer!r} points into the acknowledgement, not to evidence']
    record = complete(manifest)
    record['checklist'][0]['evidence'] = 'final_record#/outputs/0'
    assert check_ack(manifest, record, [OUTPUT]) == []


def test_a_manifest_without_a_digest_is_never_acknowledged(produced, check_ack):
    _, _, manifest = produced
    unsealed = {k: v for k, v in manifest.items() if k != 'sha256'}
    record = complete(manifest)
    del record['instruction_ack']['manifest_sha256']
    errors = check_ack(unsealed, record, [OUTPUT])
    assert errors == ['manifest: instruction_ack.manifest_sha256 is not the delivered manifest digest']


def test_not_applicable_needs_a_note(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    record['checklist'][1].update(status='not_applicable', evidence=None, note='  ')
    assert check_ack(manifest, record, [OUTPUT]) == [f'note: {duty(manifest, 1)}: not_applicable without a note']
    record['checklist'][1]['note'] = 'No published figure exists for this operation.'
    assert check_ack(manifest, record, [OUTPUT]) == []


def test_blocked_holds_the_step_with_its_reason(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    record['checklist'][2].update(status='blocked', evidence=None, note='The input card is withheld.')
    errors = check_ack(manifest, record, [OUTPUT])
    assert errors == [f'blocked: {duty(manifest, 2)}: The input card is withheld.']
    assert ins.holds(errors) == errors


def test_wrong_manifest_duplicates_unknown_units_and_bad_rows_fail(produced, check_ack):
    _, _, manifest = produced
    record = complete(manifest)
    record['instruction_ack']['manifest_sha256'] = '0' * 64
    record['checklist'].append(dict(record['checklist'][0]))
    record['checklist'].append({'unit': 'docs/workflow/start.md#invented/9', 'status': 'done', 'evidence': OUTPUT,
                                'note': None})
    record['checklist'][3]['status'] = 'skipped'
    record['checklist'][5]['sha256'] = 'f' * 64
    errors = check_ack(manifest, record, [OUTPUT])
    assert errors[0].startswith('manifest: ')
    assert f'duplicate: {duty(manifest)}: more than one checklist row' in errors
    assert 'unknown: docs/workflow/start.md#invented/9: not a unit of the delivered manifest' in errors
    assert f"status: {duty(manifest, 3)}: 'skipped' is not done, not_applicable or blocked" in errors
    assert f'digest: {duty(manifest, 5)}: the row names a different unit digest' in errors
    assert check_ack(manifest, 'not a record', []) == ['manifest: the final record is not an object']


def test_context_rows_are_optional(tmp_path, monkeypatch):
    card = role_registry.load('generator')
    step = {'id': 'context-test'}
    base = ins.manifest(step, card)
    uid = base['units'][0]['id']
    reviewed_catalogue(monkeypatch, [uid])
    manifest = ins.manifest(step, card)
    record = complete(manifest)
    record['checklist'].append({'unit': uid, 'status': 'done', 'evidence': OUTPUT, 'note': None})
    store, session, completion, _, _, _, path = observed(tmp_path, card=card, step=step, manifest=manifest, record=record)
    path.write_text(json.dumps({'outputs': [{'kind': 'events'}]}))
    store.records['worker-completion'][completion]['artifacts'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, [OUTPUT]) == []
    record['checklist'].pop()
    store.records['worker-completion'][completion]['final_record'] = deepcopy(record)
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, [OUTPUT]) == []


def test_the_governing_skill_is_owed_at_its_stage(produced, check_ack):
    """E29 behaviour: a stage cannot close without acknowledging its governing skill's duty units."""
    _, _, manifest = produced
    skill = [e for e in manifest['units'] if e['via'] == 'skill']
    assert skill and all(e['id'].startswith('.claude/skills/certify/') for e in skill)
    record = complete(manifest)
    record['checklist'] = [r for r in record['checklist'] if not r['unit'].startswith('.claude/skills/certify/')]
    errors = check_ack(manifest, record, [OUTPUT])
    assert errors and all(e.startswith('missing: .claude/skills/certify/') for e in errors)


def test_output_schema_is_pinned_to_the_manifest_and_card(produced, check_ack):
    card, _, manifest = produced
    schema_id, schema = ins.output_schema(card, manifest)
    assert schema_id == 'producer.v2'
    props = schema['properties']
    duties = [e['id'] for e in manifest['units'] if e['kind'] == 'duty']
    assert props['instruction_ack']['properties']['manifest_sha256'] == {'const': manifest['sha256']}
    assert props['checklist']['minItems'] == props['checklist']['maxItems'] == len(duties)
    assert props['checklist']['items']['properties']['unit'] == {'enum': duties}
    assert props['escalation']['items']['properties']['kind'] == {'enum': card['escalation']}
    from jsonschema import Draft202012Validator
    assert not list(Draft202012Validator(schema).iter_errors(complete(manifest)))
    wrong = complete(manifest)
    wrong['instruction_ack']['manifest_sha256'] = 'a' * 64
    assert list(Draft202012Validator(schema).iter_errors(wrong))


def finding(version):
    item = {'id': 'F1', 'severity': 'B', 'location': {'path': OUTPUT, 'pointer': '/outputs/0', 'line': None},
            'code': 'missing-anchor', 'statement': 'The anchor is not recorded.', 'evidence': [OUTPUT],
            'closes': [], 'evidence_class': 'code_check'}
    if version == 2:
        item['classification'] = {'kind': 'defect', 'artifact_sha256': 'c' * 64, 'target': 's07',
                                  'rework_evidence': 'Recording the anchor changes the comparison.'}
    return item


@pytest.mark.parametrize('role,version', [('physics-critic', 2), ('consult-higgs', 1)])
def test_findings_v3_follows_the_card_finding_version(role, version, tmp_path):
    card = role_registry.load(role)
    assert card['output']['schema'] == f'findings.v{version}'
    step = {'id': 'r1', 'kind': 'review'}
    manifest = ins.manifest(step, card)
    schema_id, schema = ins.output_schema(card, manifest)
    assert schema_id == 'findings.v3'
    rows = [{'unit': e['id'], 'status': 'done', 'evidence': 'final_record#/items/0', 'note': None}
            for e in manifest['units'] if e['kind'] == 'duty']
    record = {'schema_version': 3, 'kind': 'findings', 'items': [finding(version)], 'handoff': None,
              'instruction_ack': {'manifest_sha256': manifest['sha256']}, 'checklist': rows, 'escalation': [],
              'item_verdicts': []}
    from jsonschema import Draft202012Validator
    assert not list(Draft202012Validator(schema).iter_errors(record))
    assert ins.validate_record('findings.v3', record) == []
    store, session, completion, _, _, _, _ = observed(tmp_path, card=card, step=step, manifest=manifest, record=record)
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, []) == []
    other = deepcopy(record)
    other['items'] = [finding(1 if version == 2 else 2)]
    assert list(Draft202012Validator(schema).iter_errors(other))


def test_findings_v3_items_pass_the_classification_rules():
    record = {'schema_version': 3, 'kind': 'findings', 'items': [finding(2)], 'handoff': None,
              'instruction_ack': {'manifest_sha256': 'a' * 64}, 'checklist': [], 'escalation': [], 'item_verdicts': []}
    record['items'][0]['classification'] = {'kind': 'limitation', 'artifact_sha256': 'c' * 64,
                                            'claims': [{'claim_id': 'C1', 'effect': 'bounds', 'bound': '10%'},
                                                       {'claim_id': 'C1', 'effect': 'invalidates', 'bound': 'all'}]}
    assert any('one limitation effect' in e for e in ins.validate_record('findings.v3', record))


def test_escalation_records_are_typed():
    record = {'schema_version': 3, 'kind': 'findings', 'items': [], 'handoff': None,
              'instruction_ack': {'manifest_sha256': 'a' * 64}, 'checklist': [], 'item_verdicts': [],
              'escalation': [{'kind': 'decision_block', 'statement': 'Two bases disagree.', 'evidence': [OUTPUT]}]}
    assert ins.validate_record('findings.v3', record) == []
    record['escalation'][0]['kind'] = 'ignore'
    assert ins.validate_record('findings.v3', record)


def test_reviewer_items_carry_must_check_and_review_required_units(produced, check_ack):
    _, _, manifest = produced
    reviewer = role_registry.load('physics-critic')
    items = ins.reviewer_items(manifest, reviewer)
    checks = [i for i in items if i['kind'] == 'must_check']
    assert [i['check'] for i in checks] == reviewer['must_check']
    assert checks[0]['unit'] == '.ravel/roles/ravel-physics-critic.json#must_check/0'
    flagged = [e['id'] for e in manifest['units'] if e.get('review_required')]
    assert flagged and [i['unit'] for i in items if i['kind'] == 'review_required'] == flagged
    cat = ins.installed()
    for item in items[len(checks):]:
        assert item['text'] == cat.units[item['unit']]['text'] and item['sha256'] == cat.units[item['unit']]['sha256']


def test_protocol_sentences_that_name_an_output_are_review_required():
    cat = ins.installed()
    flagged = [u for u in cat.units.values() if u.get('field') == 'protocol' and u.get('review_required')]
    assert 80 <= len(flagged) <= 140
    assert all(ack.compiler.names_output(u['text'], role_registry.load(u['source'][len('.ravel/roles/ravel-'):-5]))
               for u in flagged[:20])


def test_item_verdicts_need_one_verdict_with_evidence_per_item(produced, check_ack):
    _, _, manifest = produced
    items = ins.reviewer_items(manifest, role_registry.load('physics-critic'))
    rows = [{'item': i['id'], 'verdict': 'pass', 'evidence': [OUTPUT], 'note': None} for i in items]
    assert ins.check_item_verdicts(items, {'item_verdicts': rows}) == []
    rows[0] = {'item': items[0]['id'], 'verdict': 'fail', 'evidence': [], 'note': None}
    rows[1] = {'item': items[1]['id'], 'verdict': 'unresolved', 'evidence': [], 'note': None}
    rows.pop()
    errors = ins.check_item_verdicts(items, {'item_verdicts': rows})
    assert errors == [f'evidence: {items[0]["id"]}: a fail verdict needs evidence',
                      f'note: {items[1]["id"]}: an unresolved verdict needs a note',
                      f'missing: {items[-1]["id"]}: no verdict']
    assert ins.check_item_verdicts(items, {}) == ['item_verdicts[] is missing']


def test_generic_schemas_are_installed_and_valid():
    from jsonschema import Draft202012Validator
    for name in ('producer.v2', 'findings.v3'):
        schema = ack.generic_schema(name)
        Draft202012Validator.check_schema(schema)
        assert {'instruction_ack', 'checklist', 'escalation'} <= set(schema['required'])
        assert role_registry.validate_output(name, {}) != ['unresolved output schema: ' + name]
