"""Normalize supplied JSON populations to the general point-list representation."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from .ma5_saf import Capture, _json, _keys
from . import supplied_contracts as contracts


def select(document, path):
    if type(path) is not list or not path or any(type(p) is not str or not p for p in path):
        raise ValueError('explicit nonempty literal JSON key path required')
    for key in path:
        contracts.fields(document, (key,)); document = document[key]
    return document


def scalar(value):
    if type(value) not in (str, int, float): raise ValueError('literal finite coordinate required')
    try: result = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc: raise ValueError('finite rational coordinate required') from exc
    return result


def normalize(document, mapping):
    contracts.fields(mapping, ('records', 'identity', 'coordinates', 'relations'))
    _keys(mapping, ('records', 'identity', 'coordinates', 'relations'), 'supplied population mapping')
    records = select(document, mapping['records'])
    if type(records) is not list or not 1 <= len(records) <= 512: raise ValueError('bounded complete source population required')
    if type(mapping['coordinates']) is not list or not 1 <= len(mapping['coordinates']) <= 4: raise ValueError('explicit coordinate mapping required')
    if type(mapping['relations']) is not list: raise ValueError('explicit coordinate relation census required')
    points = []
    for record in records:
        identity = select(record, mapping['identity'])
        if type(identity) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,80}', identity): raise ValueError('literal source point identity required')
        values = [select(record, path) for path in mapping['coordinates']]
        for value in values: scalar(value)
        for relation in mapping['relations']:
            _keys(relation, ('terms', 'equals'), 'supplied coordinate relation')
            if type(relation['terms']) is not list or not relation['terms']: raise ValueError('nonempty supplied relation terms required')
            total = Fraction()
            for term in relation['terms']:
                _keys(term, ('path', 'factor'), 'linear coordinate term')
                total += scalar(select(record, term['path']))*scalar(term['factor'])
            if total != scalar(relation['equals']): raise ValueError('supplied coordinate relation differs')
        points.append({'id': identity, 'coordinate': [str(value) for value in values]})
    if len({p['id'] for p in points}) != len(points) or len({tuple(scalar(x) for x in p['coordinate']) for p in points}) != len(points):
        raise ValueError('distinct complete source identities and coordinates required')
    return {'schema_version': 1, 'points': points}


def run(contract, base, output):
    contracts.fields(contract, ('schema_version', 'source', 'mapping', 'output'))
    _keys(contract, ('schema_version', 'source', 'mapping', 'output'), 'population normalization contract')
    if type(contract['schema_version']) is not int or contract['schema_version'] != 1: raise ValueError('population normalization schema1 required')
    contracts.output_contract(contract['output'])
    c = Capture(); _, raw = c.pin(contract['source'], base)
    result = normalize(_json(raw), contract['mapping']); c.finish()
    out = Path(output).absolute()
    if out.exists() or '..' in out.parts or any(p.is_symlink() for p in (out, *out.parents)): raise ValueError('fresh population output directory required')
    if any(p.is_relative_to(out) for p in c.files): raise ValueError('population output cannot contain source')
    out.mkdir(parents=True); target = contracts.publish(out, result, contract['output'])
    try: c.finish()
    except Exception:
        target.rename(target.with_name('failed-'+target.name)); raise
    return {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True); parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(argv); c = Capture(); path, raw = c.read(args.contract, Path.cwd())
    contract = _json(raw); result = run(contract, path.parent, args.output_dir); c.finish()
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
