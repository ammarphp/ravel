"""Supplied, byte-bound cross sections and explicitly selected correction policies.

No calculation runs here. A selected table is an input, with named dimensions,
conventions and provenance. Relative uncertainties are interpolated linearly;
unknown uncertainties remain unknown. Extrapolation is refused.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path


class MissingInput(ValueError):
    def __init__(self, message, reason_code='missing_cross_section_input'):
        super().__init__(message)
        self.reason_code = reason_code


def require(document, keys, label, reason='missing_cross_section_input'):
    if not isinstance(document, dict):
        raise MissingInput(f'{label} must be a supplied object', reason)
    missing = [k for k in keys if k not in document]
    if missing:
        raise MissingInput(f'{label} needs {", ".join(missing)}', reason)


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonempty string')
    return value


def number(value, label, *, zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{label} must be a {"nonnegative" if zero else "positive"} finite number')
    return float(value)


def pin(value, base):
    require(value, ('path', 'sha256'), 'source pin')
    path = Path(text(value['path'], 'pin.path'))
    path = path if path.is_absolute() else Path(base) / path
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != value['sha256']:
        raise ValueError(f'supplied source sha256 differs: {path}')
    return path.resolve(), raw


def _read(request, base):
    require(request, ('schema_version', 'basis', 'sqrt_s_GeV', 'masses', 'convention',
                      'state_count', 'charge', 'table'), 'supplied cross-section request')
    if request['schema_version'] != 1:
        raise ValueError('supplied cross-section schema_version must be 1')
    text(request['basis'], 'basis')
    number(request['sqrt_s_GeV'], 'sqrt_s_GeV')
    count = request['state_count']
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError('state_count must be a positive integer or null')
    if request['charge'] is not None:
        text(request['charge'], 'charge')
    require(request['convention'], ('order', 'pdf', 'scale'), 'convention')
    from ravel.physics.cross_sections import ORDERS
    if request['convention']['order'] not in ORDERS:
        raise ValueError('convention.order must name a supported perturbative order')
    for field in ('pdf', 'scale'):
        text(request['convention'][field], 'convention.' + field)
        if request['convention'][field] == 'as-published':
            raise MissingInput('supplied tables need the actual convention.' + field)
    table = request['table']
    require(table, ('path', 'sha256', 'parameters', 'interpolation', 'provenance'), 'supplied table')
    names = table['parameters']
    if not isinstance(names, list) or not names or any(not isinstance(n,str) or not n.strip() for n in names) or len(set(names)) != len(names):
        raise ValueError('table.parameters must be distinct named dimensions in nesting order')
    if not isinstance(request['masses'], dict) or set(request['masses']) != set(names):
        raise ValueError('masses must specify exactly the declared table dimensions')
    for name in names:
        number(request['masses'][name], name)
    policy = table['interpolation']
    if policy not in ('exact', 'linear', 'loglog'):
        raise ValueError('table.interpolation must be exact, linear or loglog')
    provenance = table['provenance']
    require(provenance, ('kind', 'reference', 'justification'), 'table provenance')
    for field in ('kind', 'reference', 'justification'):
        text(provenance[field], 'provenance.' + field)
    path, raw = pin(table, base)
    data = json.loads(raw)
    require(data, ('data',), 'table bytes')
    nodes = {}
    def visit(d, level, coordinate):
        if not isinstance(d, dict) or not d:
            raise ValueError('empty or malformed supplied grid')
        if level == len(names):
            require(d, ('xsec_pb',), 'cross-section node')
            number(d['xsec_pb'], 'xsec_pb')
            for k,v in d.items():
                if k.startswith('unc_') and k.endswith('_pb'):
                    number(v, k, zero=True)
            if coordinate in nodes:
                raise ValueError('duplicate numerical grid coordinate')
            nodes[coordinate] = d
            return
        for key, value in d.items():
            numeric = number(float(key), 'grid coordinate')
            visit(value, level + 1, coordinate + (numeric,))
    visit(data['data'], 0, ())
    return names, nodes, path


def _weights(nodes, values, policy):
    if tuple(values) in nodes:
        return [(tuple(values), 1.)], 'exact node'
    if policy == 'exact':
        raise ValueError('requested coordinate is not an exact node')
    axes = []
    for index,value in enumerate(values):
        candidates = sorted({p[index] for p in nodes})
        if value < candidates[0] or value > candidates[-1]:
            raise ValueError('request outside supplied grid; no extrapolation')
        if value in candidates:
            axes.append([(value,1.)])
            continue
        lo = max(v for v in candidates if v < value)
        hi = min(v for v in candidates if v > value)
        f = ((math.log(value)-math.log(lo))/(math.log(hi)-math.log(lo))
             if policy == 'loglog' else (value-lo)/(hi-lo))
        axes.append([(lo,1-f),(hi,f)])
    result = []
    for corner in itertools.product(*axes):
        position = tuple(c[0] for c in corner)
        if position not in nodes:
            raise ValueError('missing interpolation corner; no interpolation across a hole')
        result.append((position, math.prod(c[1] for c in corner)))
    return result, policy


def supplied_lookup(request, base='.'):
    names, nodes, path = _read(request, base)
    weights, how = _weights(nodes, [request['masses'][n] for n in names], request['table']['interpolation'])
    sigma = (math.exp(sum(w*math.log(nodes[p]['xsec_pb']) for p,w in weights))
             if how == 'loglog' else sum(w*nodes[p]['xsec_pb'] for p,w in weights))
    from ravel.physics.cross_sections import _uncertainty
    uncertainties = [(_uncertainty(nodes[p]), w) for p,w in weights]
    keys = set().union(*(u for u,_ in uncertainties))
    relative = {k: None if any(u.get(k) is None for u,_ in uncertainties)
                else sum(w*u[k] for u,w in uncertainties) for k in keys}
    return {'schema_version': 1, **{k:request[k] for k in ('basis','sqrt_s_GeV','masses','convention','charge','state_count')},
            'sigma_pb': sigma, 'interpolation': how,
            'uncertainty': {'up_pb': None if relative.get('relative_up') is None else sigma*relative['relative_up'],
                            'down_pb': None if relative.get('relative_down') is None else sigma*relative['relative_down'],
                            **relative},
            'source': {'kind':'supplied-table','path':str(path),'sha256':request['table']['sha256'],
                       'provenance':request['table']['provenance']}}


def batch_header(contract, kind):
    require(contract, ('schema_version','kind','study_id','datasets','output_format','points'), 'contract')
    if contract['schema_version'] != 1 or contract['kind'] != kind:
        raise ValueError(f'version-1 {kind} contract required')
    text(contract['study_id'], 'study_id')
    if not isinstance(contract['datasets'],list) or not contract['datasets'] or any(not isinstance(d,str) or not d.strip() for d in contract['datasets']):
        raise ValueError('datasets must be an explicit nonempty population of identifiers')
    if contract['output_format'] not in ('json','jsonl'):
        raise ValueError('output_format must be json or jsonl')
    if not isinstance(contract['points'],list) or not contract['points']:
        raise MissingInput('contract needs supplied points')
    tags = []
    for p in contract['points']:
        require(p, ('tag',), 'point')
        tags.append(text(p['tag'], 'point.tag'))
    if len(set(tags)) != len(tags):
        raise ValueError('duplicate point tag')
    return {k:contract[k] for k in ('schema_version','kind','study_id','datasets','output_format')}


def lookup(request, base='.'):
    if request.get('kind') != 'cross-section-batch':
        return supplied_lookup(request, base)
    header = batch_header(request, 'cross-section-batch')
    points = []
    from ravel.physics import cross_sections
    for p in request['points']:
        require(p, ('request',), 'point')
        # Batch calculations are explicitly supplied, rather than falling back to a registry default.
        require(p['request'], ('table',), 'supplied point cross section')
        result = cross_sections.lookup(p['request'], base=base)
        points.append({'tag':p['tag'],'cross_section':result})
    return {**header, 'points':points}


def correction(contract, base='.'):
    require(contract, ('numerator','denominator','interpolation','justification'), 'correction')
    text(contract['justification'], 'correction.justification')
    from ravel.physics import cross_sections
    numerator = cross_sections.lookup(contract['numerator'], base=base)
    denominator = cross_sections.lookup(contract['denominator'], base=base)
    result = cross_sections.k_factor(numerator, denominator)
    policy = contract['interpolation']
    if policy == 'ratio-linear':
        # Ratios on common nodes are an explicitly justified policy, never a fallback.
        names, ns, _ = _read(contract['numerator'],base)
        other_names, ds, _ = _read(contract['denominator'],base)
        if names != other_names:
            raise ValueError('ratio interpolation requires identical named dimensions')
        common = {p:ns[p]['xsec_pb']/ds[p]['xsec_pb'] for p in ns.keys() & ds.keys()}
        if not common:
            raise ValueError('ratio interpolation requires common supplied nodes')
        weights, how = _weights(common, [numerator['masses'][n] for n in names], 'linear')
        result['k_factor'] = sum(w*common[p] for p,w in weights)
        result['numerator']['sigma_pb'] = result['k_factor'] * denominator['sigma_pb']
        result['interpolation_nodes'] = [{'parameters':dict(zip(names,p)), 'weight':w} for p,w in weights]
    elif policy != 'ratio-of-lookups':
        raise ValueError('correction.interpolation must be ratio-linear or ratio-of-lookups')
    result.update(interpolation=policy, justification=contract['justification'],
                  source_records={'numerator':numerator,'denominator':denominator})
    return result


def inputs(request, base='.'):
    """All supplied source bytes for prospective approval binding."""
    if request.get('kind') == 'cross-section-batch':
        lookup(request,base)
        return sorted(set(path for p in request['points'] for path in inputs(p['request'],base)))
    _,_,path = _read(request,base)
    return [path,Path(__file__).resolve()]


def emit(result, out=None):
    if result.get('output_format') == 'jsonl':
        metadata = {k:v for k,v in result.items() if k != 'points'}
        rendered = ''.join(json.dumps({**metadata,**p},allow_nan=False)+'\n' for p in result['points'])
    else:
        rendered = json.dumps(result,indent=2,allow_nan=False)+'\n'
    if out is None:
        print(rendered,end='')
    else:
        Path(out).write_text(rendered)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel xsec')
    parser.add_argument('operation', choices=['supplied','correct'])
    parser.add_argument('--request',required=True,type=Path)
    parser.add_argument('--out',type=Path)
    args = parser.parse_args(argv)
    contract = json.loads(args.request.read_text())
    result = lookup(contract,args.request.parent) if args.operation == 'supplied' else correction(contract,args.request.parent)
    return emit(result,args.out)


def deliver_batch(output, payload):
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ('cross-section.' + payload['output_format'])
    if target.exists():
        raise FileExistsError(target)
    emit(payload, target)
    return payload


def register_cli(subparsers):
    for name, description in [('supplied', 'look up selected provenance-bound calculation tables'),
                              ('correct', 'compute a correction from supplied like-for-like conventions')]:
        parser = subparsers.add_parser(name, help=description)
        parser.add_argument('--request', required=True, type=Path)
        parser.add_argument('--out', type=Path)
