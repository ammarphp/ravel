"""Synthetic excerpts and negative evidence-card acceptance controls."""
from copy import deepcopy
import hashlib

import pytest


def card(kind='measurement'):
    raw = b'Observed yield is 12.4 fb with uncertainty 0.6 fb at 13 TeV. Expected yield is 9 fb.'
    value = {'schema_version': 1, 'id': 'card-a', 'claim': 'Observed yield is 12.4 fb',
             'assertion_kind': kind, 'quantity': {'name': 'yield', 'unit': 'fb'},
             'value': '12.4', 'uncertainty': '0.6 fb',
             'conditions': {'observed_or_expected': {'value': 'Observed', 'byte_range': [0, 8]},
                            'energy': {'value': '13 TeV', 'byte_range': [49, 55]},
                            'selection': 'not_stated'},
             'scope_not_covered': ['Other selections'],
             'locator': {'doc': {'path': 'inputs/paper.txt', 'sha256': hashlib.sha256(raw).hexdigest()},
                         'unit': 'paragraph', 'byte_range': [0, len(raw)],
                         'excerpt_sha256': hashlib.sha256(raw).hexdigest()},
             'hepdata': None, 'superseded_by': [], 'extractor': 'literal-extract'}
    # Locate conditions from exact bytes, without assumed offsets.
    start = raw.index(b'13 TeV'); value['conditions']['energy']['byte_range'] = [start, start + 6]
    return raw, value


def test_invented_number_is_refused():
    from ravel.validation import evidence_card
    raw, value = card(); value['value'] = '99.3'
    with pytest.raises(ValueError, match='verbatim'):
        evidence_card.validate(value, source=raw)


def test_speculation_never_anchors_rdj_or_census():
    from ravel.validation import evidence_card
    raw, value = card('speculation')
    with pytest.raises(ValueError, match='speculation'):
        evidence_card.rdj_anchor(value, source=raw)
    with pytest.raises(ValueError, match='speculation'):
        evidence_card.recipe_row(value, source=raw)


def test_restricted_source_is_refused_through_broker_with_receipt(tmp_path, monkeypatch):
    from ravel.workflow import literature
    from test_knowledge_broker import setup, row
    _, broker, _ = setup(tmp_path, monkeypatch, [row(paths=['paper.txt'])])
    raw, value = card()
    (broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    result = literature.check_cards([value], broker=broker)
    assert result['census'][0]['status'] == 'refused'
    assert result['census'][0]['receipt_id']
    assert broker.verify_ledger()[-1]['status'] == 'refused'
    assert '12.4' not in str(result)


def test_valid_card_has_literal_number_unit_and_located_conditions():
    from ravel.validation import evidence_card
    raw, value = card()
    result = evidence_card.validate(value, source=raw)
    assert result['eligible_for_anchor'] and result['id'] == 'card-a'
    anchor = evidence_card.rdj_anchor(value, source=raw)
    from ravel.workflow import decision_case
    decision_case._anchor(anchor)
    assert evidence_card.recipe_row(value, source=raw)['conditions'] == value['conditions']


@pytest.mark.parametrize('mutation', ['source', 'excerpt', 'unit', 'condition', 'unlocated', 'claim-number', 'scope-number', 'rounding'])
def test_card_refuses_source_and_scientific_field_mutations(mutation):
    from ravel.validation import evidence_card
    raw, value = card()
    if mutation == 'source': raw += b' changed'
    elif mutation == 'excerpt': value['locator']['excerpt_sha256'] = '0' * 64
    elif mutation == 'unit': value['quantity']['unit'] = 'pb'
    elif mutation == 'condition': value['conditions']['energy']['value'] = '14 TeV'
    elif mutation == 'unlocated': value['conditions']['energy'] = '13 TeV'
    elif mutation == 'claim-number': value['claim'] = 'Yield is 4 fb'
    elif mutation == 'scope-number': value['scope_not_covered'] = ['Above 17 TeV']
    else: value['value'] = '12.40'
    with pytest.raises(ValueError):
        evidence_card.validate(value, source=raw)


def test_superseded_card_cannot_establish_current_recipe():
    from ravel.validation import evidence_card
    raw, value = card(); value['superseded_by'] = ['successor']
    assert not evidence_card.validate(value, source=raw)['eligible_for_anchor']
    with pytest.raises(ValueError, match='superseded'):
        evidence_card.recipe_row(value, source=raw)


def test_five_cards_only_in_display_complete_census_remains(tmp_path, monkeypatch):
    from ravel.workflow import literature
    from test_knowledge_broker import setup
    _, broker, _ = setup(tmp_path, monkeypatch)
    raw, value = card(); (broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    cards = [{**deepcopy(value), 'id': 'card-' + str(i)} for i in range(7)]
    report = literature.check_cards(cards, broker=broker)
    assert len(report['cards']) == 5 and len(report['census']) == 7
    assert report['remaining_ids'] == ['card-5', 'card-6']
    assert len(report['anchor_ids']) == len(report['recipe_ids']) == 7


def test_census_is_rederived_and_receipts_must_match(tmp_path, monkeypatch):
    from ravel.workflow import literature
    from test_knowledge_broker import setup
    _, broker, _ = setup(tmp_path, monkeypatch)
    raw, value = card(); (broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    report = literature.check_cards([value], broker=broker)
    assert literature.consume_cards(report, [value], broker=broker)['population'] == 1
    changed = deepcopy(report); changed['anchor_ids'] = []
    with pytest.raises(ValueError, match='derivation'):
        literature.consume_cards(changed, [value], broker=broker)
    (broker.workspace / 'inputs/paper.txt').write_bytes(raw + b'changed')
    with pytest.raises(ValueError, match='derivation'):
        literature.consume_cards(report, [value], broker=broker)


def test_judgment_scout_card_is_retained():
    from ravel.workflow import literature
    assert literature.scout_tier()['tier'] == 'judgment'


def test_rdj_consumer_refuses_speculative_evidence_card_value():
    from ravel.workflow import decision_case
    raw, value = card('speculation')
    anchor = {'kind': 'external_source', 'artifact': value['locator']['doc'], 'format': 'json', 'location': '', 'value': value}
    with pytest.raises(ValueError, match='speculation'):
        decision_case._anchor(anchor)


def test_cheap_scout_is_refused(monkeypatch):
    from ravel.workflow import literature
    monkeypatch.setattr(literature.role_registry, 'load', lambda role: {'model': {'tier': 'cheap'}})
    with pytest.raises(ValueError, match='judgment'):
        literature.scout_tier()


def test_source_identifier_restriction_is_refused_before_read(tmp_path, monkeypatch):
    from ravel.workflow import literature
    from test_knowledge_broker import setup, row
    _, broker, _ = setup(tmp_path, monkeypatch, [row(paths=[], identifiers={'hepdata': ['42']})])
    raw, value = card(); value['hepdata'] = '42'
    (broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    report = literature.check_cards([value], broker=broker)
    assert report['census'][0]['reason'] == 'forbidden_source'
    assert broker.verify_ledger()[-1]['input_pins'] == []


def test_rdj_consumer_keeps_value_error_for_malformed_anchor():
    from ravel.workflow import decision_case
    for anchor in ('not-an-anchor', ['list'], None):
        with pytest.raises(ValueError):
            decision_case._anchor(anchor)
