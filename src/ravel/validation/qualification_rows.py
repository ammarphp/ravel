"""Cited published comparator rows with offline extracted-text verification."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import argparse
import math
from pathlib import Path
import re

from jsonschema import Draft202012Validator

DIRECTORY = Path(__file__).resolve().parents[1] / 'data/knowledge/qualification'


class QualificationError(ValueError):
    """The row lacks a supported source extraction or is still pending."""


def _read(path):
    from ravel.setup.manifest import read_json
    return read_json(path)


def validate_row(row, *, text=None, schema=None):
    schema = schema or _read(DIRECTORY / 'schema.json')['$defs']['row']
    errors = sorted(e.message for e in Draft202012Validator(schema).iter_errors(row))
    if errors:
        raise QualificationError('; '.join(errors))
    if row['id'] != 'qual:' + row['tool'] + ':' + row['quantity']:
        raise QualificationError('row id must match tool and quantity')
    if row['status'] == 'pending':
        return
    if text is None:
        raise QualificationError('filled row requires fetched document extracted text')
    if not isinstance(text, str):
        raise QualificationError('extracted text must be a string')
    evidence = row['evidence']
    if sha256(text.encode('utf-8')).hexdigest() != evidence['text_sha256']:
        raise QualificationError('extracted text checksum mismatch')
    quote = evidence['quote']
    if quote not in text:
        raise QualificationError('quoted extraction is absent from extracted text')
    locator = row['locator']
    start = text.find(locator)
    if start < 0:
        raise QualificationError('table/figure locator absent from extracted text')
    # Quote must be in the locator's section, before another table/figure header.
    section = text[start + len(locator):]
    boundary = re.search(r'(?im)^\s*(?:Table|Fig(?:ure)?\.?|Equation|Section)\s+\S+', section)
    if boundary:
        section = section[:boundary.start()]
    if quote not in section and quote not in locator:
        raise QualificationError('quote is outside the cited locator section')
    literal = evidence['value_literal']
    if not re.search(r'(?<![\w.])' + re.escape(literal) + r'(?![\w.])', quote):
        raise QualificationError('value literal is absent from quoted extraction')
    value = row['value']
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise QualificationError('value must be finite')
        try:
            equal = Decimal(literal.replace('−', '-').replace('D', 'E')) == Decimal(str(value))
        except InvalidOperation:
            equal = False
        if not equal:
            raise QualificationError('value does not match the quoted value literal')
    elif value != literal:
        raise QualificationError('expression value differs from quoted literal')
    for key in ('minus', 'plus'):
        uncertainty = row['uncertainty'][key]
        if uncertainty is not None and not math.isfinite(uncertainty):
            raise QualificationError('uncertainty must be finite')


def load_rows(directory=None):
    directory = Path(directory or DIRECTORY)
    document = _read(directory / 'rows.json')
    schema = _read(directory / 'schema.json')
    errors = sorted(e.message for e in Draft202012Validator(schema).iter_errors(document))
    if errors:
        raise QualificationError('; '.join(errors))
    ids = [row['id'] for row in document['rows']]
    if len(ids) != len(set(ids)):
        raise QualificationError('duplicate reference row id')
    referenced = {i for ids in document['comparators'].values() for i in ids}
    if referenced != set(ids):
        raise QualificationError('comparator rows must resolve exactly once in the row catalogue')
    return document


def _text(row, source_cache):
    name = (row.get('evidence') or {}).get('text_file')
    if source_cache is None or not name:
        return None
    path = Path(source_cache) / name
    if Path(name).name != name or name in ('.', '..') or path.is_symlink() or not path.is_file():
        raise QualificationError('extracted text must be an ordinary cache file')
    return path.read_text(encoding='utf-8')


def resolve(identity, *, directory=None, require_filled=True, text=None, source_cache=None):
    document = load_rows(directory)
    row = next((r for r in document['rows'] if r['id'] == identity), None)
    if row is None:
        raise QualificationError('unknown comparator row: ' + identity)
    if require_filled and row['status'] != 'filled':
        raise QualificationError('comparator value pending source fetch: ' + identity)
    validate_row(row, text=text if text is not None else _text(row, source_cache))
    return row


def check_directory(directory=None, *, source_cache=None):
    directory = Path(directory or DIRECTORY)
    try:
        document = load_rows(directory)
    except (OSError, ValueError) as exc:
        return ['qualification rows: ' + str(exc)]
    errors = []
    schema = _read(directory / 'schema.json')['$defs']['row']
    for row in document['rows']:
        try:
            validate_row(row, text=_text(row, source_cache), schema=schema)
        except (OSError, ValueError) as exc:
            errors.append(row['id'] + ': ' + str(exc))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DIRECTORY)
    parser.add_argument('--source-cache', type=Path)
    args = parser.parse_args(argv)
    errors = check_directory(args.directory, source_cache=args.source_cache)
    print('\n'.join(errors) if errors else 'Comparator rows OK; null values remain source-fetch holds')
    return int(bool(errors))


def register_qualification_reference(add, package):
    """Register the held reference table through the atlas's existing tool seam."""
    directory = package / 'data/knowledge/qualification'
    if not directory.is_dir():
        return
    document = load_rows(directory)
    pending = sum(row['status'] == 'pending' for row in document['rows'])
    add('check', 'published-comparator-schema', 'Published comparator schema',
        'Source, locator, units, extraction and quoted-value contract', directory / 'schema.json',
        check={'catches': 'Missing source extraction, wrong quoted value and malformed comparator rows'})
    return add('tool', 'published-comparator-rows', 'Published comparator rows',
               'Cited source reference values; each pending row is a source-fetch hold',
               directory / 'rows.json', qualification_status='not_installed' if pending else 'built_but_unqualified',
               qualification_scope='Reference registration only; no native or scientific qualification inferred.',
               pending_rows=pending, links={'checks': ['check:published-comparator-schema']})


if __name__ == '__main__':
    raise SystemExit(main())
