"""Literal evidence-card checks; a source assertion is not physics certification.

Readers must supply authenticated bytes. The literature service reads through
the knowledge broker before calling this pure validator. Numeric spelling is preserved:
rounding, unit conversion and condition inference are not extraction.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

MAX_CARDS = 512
DISPLAY_CARDS = 5
MAX_SOURCE_BYTES = 64 * 1024 * 1024
SHA = re.compile(r'[a-f0-9]{64}\Z')
NUMBER = re.compile(r'(?<![\d.])[+−-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+−-]?\d+)?(?:%?)(?![\d.])')
KINDS = {'measurement', 'prediction', 'source_assertion', 'speculation'}
FIELDS = {'schema_version', 'id', 'claim', 'assertion_kind', 'quantity', 'value',
          'uncertainty', 'conditions', 'scope_not_covered', 'locator', 'hepdata',
          'superseded_by', 'extractor'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _text(value, name, maximum=8192):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError('bounded nonempty ' + name + ' required')
    return value


def _keys(value, fields, name):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError('closed ' + name + ' fields required')


def _range(value, size):
    if (type(value) is not list or len(value) != 2 or any(type(n) is not int for n in value)
            or not 0 <= value[0] < value[1] <= size):
        raise ValueError('nonempty original byte range required')
    return value


def source_pin(card):
    """Validate the locator shape before any source is opened."""
    _keys(card, FIELDS, 'evidence card')
    if type(card['schema_version']) is not int or card['schema_version'] != 1:
        raise ValueError('evidence card/v1 required')
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{0,95}', _text(card['id'], 'card ID')):
        raise ValueError('bounded card ID required')
    _keys(card['locator'], {'doc', 'unit', 'byte_range', 'excerpt_sha256'}, 'locator')
    pin = card['locator']['doc']
    _keys(pin, {'path', 'sha256'}, 'source pin')
    _text(pin['path'], 'source path', 4096)
    for sha in (pin['sha256'], card['locator']['excerpt_sha256']):
        if type(sha) is not str or not SHA.fullmatch(sha):
            raise ValueError('exact source and excerpt SHA256 required')
    _text(card['locator']['unit'], 'located source unit', 512)
    return deepcopy(pin)


def validate(card, *, source):
    pin = source_pin(card)
    if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise ValueError('bounded authenticated original bytes required')
    if hashlib.sha256(source).hexdigest() != pin['sha256']:
        raise ValueError('source hash differs from original bytes')
    start, end = _range(card['locator']['byte_range'], len(source))
    excerpt_raw = source[start:end]
    if hashlib.sha256(excerpt_raw).hexdigest() != card['locator']['excerpt_sha256']:
        raise ValueError('excerpt hash differs from original bytes')
    try:
        excerpt = excerpt_raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('UTF-8 excerpt boundaries required; extract PDF text first') from exc
    if card['assertion_kind'] not in KINDS:
        raise ValueError('explicit evidence assertion_kind required')
    _text(card['claim'], 'claim')
    if card['claim'] not in excerpt:
        raise ValueError('claim, including every unit, must occur verbatim in excerpt')
    _keys(card['quantity'], {'name', 'unit'}, 'quantity')
    _text(card['quantity']['name'], 'quantity name', 256)
    unit = _text(card['quantity']['unit'], 'quantity unit', 128)
    if not re.search(r'(?<!\w)' + re.escape(unit) + r'(?!\w)', excerpt):
        raise ValueError('quantity unit must occur verbatim in excerpt')
    _text(card['value'], 'literal value', 256)
    _text(card['uncertainty'], 'literal uncertainty or not_stated', 256)
    if card['value'] not in excerpt:
        raise ValueError('value must occur verbatim in excerpt')
    if card['uncertainty'] != 'not_stated' and card['uncertainty'] not in excerpt:
        raise ValueError('uncertainty and units must occur verbatim in excerpt')
    conditions = card['conditions']
    if type(conditions) is not dict or 'observed_or_expected' not in conditions or len(conditions) > 32:
        raise ValueError('located conditions including observed_or_expected required')
    condition_values = []
    for name, row in conditions.items():
        _text(name, 'condition name', 128)
        if row == 'not_stated':
            continue
        _keys(row, {'value', 'byte_range'}, 'condition')
        a, b = _range(row['byte_range'], len(source))
        if not start <= a < b <= end or source[a:b].decode('utf-8') != _text(row['value'], 'condition'):
            raise ValueError('condition must occur verbatim at its located excerpt range')
        condition_values.append(row['value'])
    if type(card['scope_not_covered']) is not list or len(card['scope_not_covered']) > 32:
        raise ValueError('explicit uncovered scope list required')
    for scope in card['scope_not_covered']:
        _text(scope, 'uncovered scope')
    if type(card['superseded_by']) is not list or not all(type(x) is str and x for x in card['superseded_by']):
        raise ValueError('explicit superseding source IDs required')
    if card['hepdata'] is not None:
        _text(card['hepdata'], 'optional source identifier', 512)
    _text(card['extractor'], 'extractor provenance', 512)
    # Metadata (IDs, hashes, byte offsets, extractor versions) is not a scientific value.
    scientific = [card['claim'], card['quantity']['name'], card['value'], card['uncertainty'],
                  *conditions.keys(), *condition_values, *card['scope_not_covered']]
    original_numbers = set(NUMBER.findall(excerpt))
    for text in scientific:
        for number in NUMBER.findall(text):
            if number not in original_numbers:
                raise ValueError('every scientific number must occur verbatim in excerpt: ' + number)
    return {'id': card['id'], 'card_sha256': digest(card),
            'excerpt_sha256': card['locator']['excerpt_sha256'],
            'eligible_for_anchor': card['assertion_kind'] != 'speculation' and not card['superseded_by'],
            'scope': 'Literal source wording only; no scientific validity inferred'}


def rdj_anchor(card, *, source):
    """Return a source anchor compatible with decision_case, never speculation."""
    checked = validate(card, source=source)
    if card['assertion_kind'] == 'speculation':
        raise ValueError('speculation cannot anchor an RDJ edge')
    if not checked['eligible_for_anchor']:
        raise ValueError('superseded evidence cannot anchor a current decision')
    # RDJ's text anchor binds the entire original; the card retains the finer range.
    return {'kind': 'external_source', 'artifact': deepcopy(card['locator']['doc']),
            'format': 'text', 'location': '', 'value': source.decode('utf-8')}


def recipe_row(card, *, source):
    """Evidence handoff; unknown and speculative inputs remain DATA work."""
    checked = validate(card, source=source)
    if card['assertion_kind'] == 'speculation':
        raise ValueError('speculation cannot establish a recipe census entry')
    if not checked['eligible_for_anchor']:
        raise ValueError('superseded evidence cannot establish a current recipe row')
    return {'id': card['id'], 'quantity': deepcopy(card['quantity']), 'value': card['value'],
            'uncertainty': card['uncertainty'], 'conditions': deepcopy(card['conditions']),
            'locator': deepcopy(card['locator']), 'card_sha256': checked['card_sha256'],
            'scope_not_covered': deepcopy(card['scope_not_covered'])}


def check_rdj_anchor(anchor):
    """RDJ consumer seam: speculative card values cannot become source anchors."""
    def visit(value):
        if isinstance(value, dict):
            if value.get('assertion_kind') == 'speculation' and 'locator' in value:
                raise ValueError('speculation evidence cards cannot anchor an RDJ edge')
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(anchor.get('value'))
