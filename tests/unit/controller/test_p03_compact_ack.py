"""Indexed acknowledgements retain complete duty coverage and observed evidence custody."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from ravel.controller import instructions as ins
from ravel.controller.instructions import ack, compiler
from test_p03_observed import observed, reviewed_catalogue, scope


def compact(manifest, record):
    result = deepcopy(record)
    indices = {entry['id']: index for index, entry in enumerate(manifest['units'])}
    groups = []
    for row in record['checklist']:
        fields = {key: row[key] for key in ('status', 'evidence', 'note')}
        group = next((group for group in groups if all(group[key] == value for key, value in fields.items())), None)
        if group is None:
            group = {'indices': [], **fields}
            groups.append(group)
        group['indices'].append(indices[row['unit']])
    result['checklist'] = {'schema_version': 1, 'groups': groups}
    return result


@pytest.fixture
def delivered(tmp_path):
    return observed(tmp_path)


def check(delivered, record):
    store, session, completion, manifest, _, _, _ = delivered
    store.records['worker-completion'][completion]['final_record'] = deepcopy(record)
    with scope(store, session, completion):
        return ins.check_ack(manifest, record, ['outputs/result.json'])


@pytest.mark.parametrize('status', ['done', 'not_applicable', 'blocked'])
def test_both_encodings_expand_to_identical_duties_and_verdicts(delivered, status):
    _, _, _, manifest, _, expanded, _ = delivered
    expanded = deepcopy(expanded)
    if status != 'done':
        expanded['checklist'][0].update(status=status, evidence=None, note='The required input is absent.')
    encoded = compact(manifest, expanded)
    assert check(delivered, expanded) == check(delivered, encoded)
    rows, errors = ack.normalise_checklist(manifest, encoded['checklist'])
    assert errors == []
    assert rows == expanded['checklist']
    assert len(rows) == sum(unit['kind'] == 'duty' for unit in manifest['units'])


@pytest.mark.parametrize('damage', ['omitted', 'duplicate', 'conflicting', 'wrong-manifest', 'dangling', 'no-note'])
def test_both_encodings_refuse_the_same_faults(delivered, damage):
    _, _, _, manifest, _, expanded, _ = delivered
    expanded = deepcopy(expanded)
    if damage == 'omitted':
        expanded['checklist'].pop(0)
    elif damage in ('duplicate', 'conflicting'):
        row = deepcopy(expanded['checklist'][0])
        if damage == 'conflicting':
            row.update(status='blocked', evidence=None, note='An input is missing.')
        expanded['checklist'].append(row)
    elif damage == 'wrong-manifest':
        expanded['instruction_ack']['manifest_sha256'] = '0' * 64
    elif damage == 'dangling':
        expanded['checklist'][0]['evidence'] = 'outputs/result.json#/missing/field'
    else:
        expanded['checklist'][0].update(status='not_applicable', evidence=None, note=' ')
    expected = check(delivered, expanded)
    assert expected
    assert check(delivered, compact(manifest, expanded)) == expected


@pytest.mark.parametrize('index', [-1, 10**6, True, '0', 0.5])
def test_invalid_indices_refuse_credit(delivered, index):
    manifest, expanded = delivered[3], delivered[5]
    encoded = compact(manifest, expanded)
    encoded['checklist']['groups'][0]['indices'].append(index)
    assert any(error.startswith('manifest:') for error in check(delivered, encoded))


@pytest.mark.parametrize('damage', ['version', 'empty-group', 'missing-status', 'extra-field', 'mixed'])
def test_malformed_compact_groups_refuse_credit(delivered, damage):
    manifest, expanded = delivered[3], delivered[5]
    encoded = compact(manifest, expanded)
    checklist = encoded['checklist']
    if damage == 'version':
        checklist['schema_version'] = 2
    elif damage == 'empty-group':
        checklist['groups'].append({'indices': [], 'status': 'done', 'evidence': 'outputs/result.json', 'note': None})
    elif damage == 'missing-status':
        del checklist['groups'][0]['status']
    elif damage == 'extra-field':
        checklist['groups'][0]['all_remaining'] = True
    else:
        checklist['rows'] = expanded['checklist']
    assert any(error.startswith('manifest:') for error in check(delivered, encoded))


@pytest.mark.parametrize('schema_id', ['producer.v2', 'findings.v3'])
def test_generic_and_pinned_schemas_accept_both_encodings(delivered, schema_id):
    manifest, expanded = delivered[3], deepcopy(delivered[5])
    if schema_id == 'findings.v3':
        expanded = {key: expanded[key] for key in ('instruction_ack', 'checklist', 'escalation', 'handoff')}
        expanded.update(schema_version=3, kind='findings', items=[], item_verdicts=[])
    schema = ack.pin_schema(ack.generic_schema(schema_id), manifest, None)
    for record in (expanded, compact(manifest, expanded)):
        assert ins.validate_record(schema_id, record) == []
        assert list(Draft202012Validator(schema).iter_errors(record)) == []
        record['instruction_ack']['manifest_sha256'] = '0' * 64
        assert list(Draft202012Validator(schema).iter_errors(record))


@pytest.mark.parametrize('encoding', ['expanded', 'compact'])
@pytest.mark.parametrize('damage', ['artifact', 'stale-attempt', 'receipt'])
def test_custody_remains_bound_to_observed_bytes(delivered, encoding, damage):
    store, session, completion, manifest, packet, expanded, path = delivered
    record = compact(manifest, expanded) if encoding == 'compact' else deepcopy(expanded)
    assert check(delivered, record) == []
    receipt = ins.record_delivery(store, manifest, packet, session=session)
    if damage == 'artifact':
        path.write_text('{"value": 8}')
    elif damage == 'stale-attempt':
        active = store.scan('step-attempt')[-1]
        store.append('step-attempt', {**active, 'attempt': 2, 'session': 'later'})
    else:
        store.records['instruction-delivery'][receipt]['packet_sha256'] = '0' * 64
    if damage != 'receipt':
        with scope(store, session, completion):
            assert ins.check_ack(manifest, record, ['outputs/result.json'])
    assert ins.discharge(store, {'I02': 'entry'}, manifest, receipt_id=receipt,
                         record=lambda *args: None) == {'I02': 'violated'}


def test_semantic_equivalence_cannot_replace_observed_record(delivered):
    store, session, completion, manifest, packet, expanded, _ = delivered
    encoded = compact(manifest, expanded)
    assert check(delivered, encoded) == []
    receipt = ins.record_delivery(store, manifest, packet, session=session)
    with scope(store, session, completion):
        assert ins.check_ack(manifest, expanded, ['outputs/result.json']) == [
            'manifest: controller completion custody failed: final record differs from the controller-observed completion']
    assert store.records['worker-completion'][completion]['final_record'] == encoded
    assert ins.discharge(store, {'I02': 'entry'}, manifest, receipt_id=receipt,
                         record=lambda *args: None) == {'I02': 'satisfied'}


def test_indices_follow_full_manifest_including_context(tmp_path, monkeypatch):
    step = {'id': 'step-one', 'kind': 'operate'}
    original = ins.manifest(step, None)
    reviewed_catalogue(monkeypatch, [original['units'][0]['id']])
    delivered = observed(tmp_path, step=step)
    manifest, expanded = delivered[3], delivered[5]
    encoded = compact(manifest, expanded)
    assert manifest['units'][0]['kind'] == 'context'
    assert encoded['checklist']['groups'][0]['indices'][0] == 1
    assert check(delivered, encoded) == []
    schema = delivered[4]['schema']
    assert list(Draft202012Validator(schema).iter_errors(encoded)) == []
    encoded['checklist']['groups'][0]['indices'][0] = 0
    assert any(error.startswith('missing:') for error in check(delivered, encoded))
    assert list(Draft202012Validator(schema).iter_errors(encoded))


@pytest.mark.parametrize('encoding', ['expanded', 'compact'])
def test_evidence_cannot_point_into_either_acknowledgement(delivered, encoding):
    manifest, expanded = delivered[3], deepcopy(delivered[5])
    expanded['checklist'][0]['evidence'] = 'final_record#/%63hecklist'
    record = compact(manifest, expanded) if encoding == 'compact' else expanded
    assert any('points into the acknowledgement' in error for error in check(delivered, record))
    expanded['checklist'][0]['evidence'] = 'final_record#/outputs/0'
    record = compact(manifest, expanded) if encoding == 'compact' else expanded
    assert check(delivered, record) == []


def test_review_required_items_remain_required_for_both_encodings(tmp_path):
    from ravel.workflow import role_registry
    card = role_registry.load('generator')
    delivered = observed(tmp_path, card=card)
    manifest, expanded = delivered[3], delivered[5]
    items = ins.reviewer_items(manifest, card)
    expected = {f'unit:{entry["id"]}' for entry in manifest['units'] if entry.get('review_required')}
    assert expected and expected <= {item['id'] for item in items}
    verdicts = {'item_verdicts': [{'item': item['id'], 'verdict': 'pass',
                                  'evidence': ['outputs/result.json#/value']} for item in items]}
    for record in (expanded, compact(manifest, expanded)):
        assert check(delivered, record) == []
        assert ins.check_item_verdicts(items, verdicts) == []
        assert ins.check_item_verdicts(items, {'item_verdicts': verdicts['item_verdicts'][1:]}) == [
            f'missing: {items[0]["id"]}: no verdict']


@pytest.mark.parametrize('status,expected', [('done', 'satisfied'), ('not_applicable', 'satisfied'), ('blocked', 'pending')])
def test_both_encodings_have_identical_delivery_credit(delivered, status, expected):
    store, session, _, manifest, packet, expanded, _ = delivered
    expanded = deepcopy(expanded)
    if status != 'done':
        expanded['checklist'][0].update(status=status, evidence=None, note='The input is absent.')
    receipt = ins.record_delivery(store, manifest, packet, session=session)
    for record in (expanded, compact(manifest, expanded)):
        check(delivered, record)
        assert ins.discharge(store, {'I02': 'entry'}, manifest, receipt_id=receipt,
                             record=lambda *args: None) == {'I02': expected}


def test_packet_saving_keeps_every_unit_text_and_pin(delivered, record_property):
    _, session, _, manifest, packet, expanded, _ = delivered
    encoded = compact(manifest, expanded)
    expanded_bytes = len(json.dumps(expanded, separators=(',', ':')).encode())
    compact_bytes = len(json.dumps(encoded, separators=(',', ':')).encode())
    record_property('packet_text_bytes', len(packet['text'].encode()))
    record_property('expanded_ack_bytes', expanded_bytes)
    record_property('compact_ack_bytes', compact_bytes)
    record_property('manifest_sha256', manifest['sha256'])
    record_property('manifest_units', len(manifest['units']))
    record_property('duty_units', sum(entry['kind'] == 'duty' for entry in manifest['units']))
    assert compact_bytes < expanded_bytes
    from ravel.controller.instructions import catalogue
    cat = catalogue.installed()
    for index, entry in enumerate(manifest['units']):
        assert cat.units[entry['id']]['text'] in packet['text']
        assert f'--- [{entry["kind"]}] {entry["id"]} index:{index}\n' in packet['text']
        assert f'sha256:{entry["sha256"]}' not in packet['text']
    assert packet['text'].index('== Acknowledgement ==') < packet['text'].index('step:')
    assert ins.check_packet(packet, manifest, None, {'id': 'step-one', 'kind': 'operate'}, []) == []
    receipt = ins.receipt(manifest, packet, session=session)
    assert receipt['manifest_sha256'] == manifest['sha256']
    assert receipt['packet_sha256'] == packet['sha256']
    assert receipt['units'] == [entry['id'] for entry in manifest['units']]
    assert all(len(entry['sha256']) == 64 for entry in manifest['units'])
    assert compiler.digest_value({key: value for key, value in manifest.items() if key != 'sha256'}) == manifest['sha256']
