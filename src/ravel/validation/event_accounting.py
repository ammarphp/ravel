"""Count and signed-weight conservation under explicit processing laws.

The rejected population must be observed independently, not inferred by
subtracting the output. These moment checks do not prove event identity.
"""
import argparse
import json
import math
from pathlib import Path

FIELDS = ('count', 'sumw', 'sumw2', 'positive', 'negative', 'zero')


def moments(weights):
    weights = list(weights)
    if any(type(w) not in (int, float) or not math.isfinite(w) for w in weights):
        raise ValueError('finite signed event weights required')
    return {'count': len(weights), 'sumw': math.fsum(weights), 'sumw2': math.fsum(w*w for w in weights),
            'positive': sum(w > 0 for w in weights), 'negative': sum(w < 0 for w in weights),
            'zero': sum(w == 0 for w in weights)}


def _validate(row):
    if type(row) is not dict or set(row) != set(FIELDS):
        raise ValueError('event moments need count, sumw, sumw2, positive, negative and zero')
    for key in ('count', 'positive', 'negative', 'zero'):
        if type(row[key]) is not int or row[key] < 0:
            raise ValueError('nonnegative integer event/sign counts required')
    if row['count'] != row['positive'] + row['negative'] + row['zero']:
        raise ValueError('event sign counts do not sum to count')
    for key in ('sumw', 'sumw2'):
        if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
            raise ValueError('finite event moments required')
    if row['sumw2'] < 0 or row['sumw'] ** 2 > row['count'] * row['sumw2'] + 1e-12 * max(1, row['sumw'] ** 2):
        raise ValueError('inconsistent signed first/second moments')
    if row['count'] == row['zero'] and (row['sumw'] != 0 or row['sumw2'] != 0):
        raise ValueError('empty/zero-weight population has nonzero moments')


def check(document, *, rel_tol=1e-12, abs_tol=1e-12):
    if type(document) is not dict or set(document) != {'schema_version', 'input', 'output', 'transformation'} or document['schema_version'] != 1:
        raise ValueError('event accounting schema_version 1 with input/output/transformation required')
    source, output, law = document['input'], document['output'], document['transformation']
    _validate(source); _validate(output)
    if type(law) is not dict or law.get('kind') not in ('identity', 'scale', 'selection', 'selection-and-scale'):
        raise ValueError('declared identity, scale or selection transformation required')
    selected = law['kind'] in ('selection', 'selection-and-scale')
    scaled = law['kind'] in ('scale', 'selection-and-scale')
    if set(law) != {'kind'} | ({'rejected'} if selected else set()) | ({'weight_scale'} if scaled else set()):
        raise ValueError('transformation needs exactly its declared rejected population and/or weight_scale')
    rejected = law['rejected'] if selected else moments([])
    _validate(rejected)
    scale = law['weight_scale'] if scaled else 1.
    if type(scale) not in (int, float) or not math.isfinite(scale) or scale == 0:
        raise ValueError('finite nonzero declared weight_scale required')
    expected = {k: math.fsum([source[k], -rejected[k]]) if k in ('sumw', 'sumw2')
                else source[k] - rejected[k] for k in FIELDS}
    _validate(expected)
    expected['sumw'] *= scale; expected['sumw2'] *= scale * scale
    if scale < 0:
        expected['positive'], expected['negative'] = expected['negative'], expected['positive']
    rows = [{'field': k, 'expected': expected[k], 'observed': output[k],
             'status': 'pass' if (math.isclose(output[k], expected[k], rel_tol=rel_tol, abs_tol=abs_tol)
                 if k in ('sumw', 'sumw2') else output[k] == expected[k]) else 'fail'} for k in FIELDS]
    return {'schema_version': 1, 'check': 'event_accounting', 'computed': True,
            'passed': all(r['status'] == 'pass' for r in rows), 'rows': rows,
            'transformation': law, 'identity_verified': False,
            'scope': 'declared population counts and signed moments; no physical event association inferred'}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel check:event_accounting', description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    result = check(json.loads(args.spec.read_text()))
    raw = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(raw)
    else:
        print(raw, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
