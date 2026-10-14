"""Atomic limit transformations from supplied cross sections and component responses.

A response_ratio is a component's target yield per unit total cross section
divided by its source yield per unit total cross section. Source yield fractions sum
to one. No component is silently dropped and every approximation is justified.
The multiplicative transformation requires unchanged accepted shapes.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ravel.limits import read_limits, rescale_artifact
from ravel.physics import cross_sections
from ravel.physics.xsec_conventions import MissingInput, batch_header, correction, number, require, text, emit

REASON = 'missing_production_transformation'


def load_contract(value, base='.'):
    if isinstance(value, dict):
        return copy.deepcopy(value), Path(base), None
    if not value:
        raise MissingInput('a supplied production transformation contract is required', REASON)
    path = Path(value)
    path = path if path.is_absolute() else Path(base)/path
    if not path.is_file():
        raise MissingInput('the selected normalization input must be an existing contract file', REASON)
    raw = path.read_bytes()
    return json.loads(raw), path.resolve().parent, {'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest()}


def _population(rows, contract, kind):
    header = batch_header(contract, kind)
    tags = [r.get('tag') for r in rows]
    if len(set(tags)) != len(tags) or set(tags) != {p['tag'] for p in contract['points']}:
        raise ValueError('contract point population must match the supplied rows exactly')
    return header, {p['tag']:p for p in contract['points']}


def _parameters(point, record):
    require(point, ('parameters',), 'transformation point', REASON)
    if not isinstance(point['parameters'],dict) or not point['parameters']:
        raise ValueError('parameters must name the supplied grid coordinate')
    # Table dimensions can be a projection of a larger scan; every selected
    # cross-section dimension must still match the actual point.
    if any(point['parameters'].get(k) != v for k,v in record['masses'].items()):
        raise ValueError('cross-section dimensions differ from the transformation coordinate')
    for k,v in point['parameters'].items():
        text(k, 'parameter name')
        if type(v) not in (int,float):
            raise ValueError('parameters must have numeric coordinates')
        # Named scan axes can be signed or zero, unlike mass-table dimensions.
        import math
        if not math.isfinite(v):
            raise ValueError('parameter coordinate must be finite')


def _row_coordinate(row, point):
    coordinates = row.get('parameters', row)
    bindings = point.get('coordinate_bindings', {})
    if not isinstance(bindings, dict) or set(bindings) - set(point['parameters']):
        raise ValueError('coordinate_bindings must map declared parameters to source coordinate keys')
    for key,value in point['parameters'].items():
        source_key = text(bindings.get(key,key), 'coordinate binding')
        if source_key not in coordinates:
            raise MissingInput(f'source row needs coordinate {source_key}', REASON)
        if coordinates[source_key] != value:
            raise ValueError('transformation coordinate differs from the source row')


def _components(point, source, target):
    require(point, ('components','shape_justification'), 'production transformation', REASON)
    text(point['shape_justification'], 'shape_justification')
    parts = point['components']
    if not isinstance(parts,list) or not parts:
        raise MissingInput('production transformation needs component accounting', REASON)
    fraction, response = 0., 0.
    source_states, target_states, ids = [], [], []
    for part in parts:
        require(part, ('id','source_states','target_states','source_yield_fraction','response_ratio','justification'),
                'component', REASON)
        ids.append(text(part['id'],'component.id'))
        text(part['justification'], 'component.justification')
        for key, states in (('source_states',source_states),('target_states',target_states)):
            if not isinstance(part[key],list) or any(not isinstance(s,str) or not s.strip() for s in part[key]):
                raise ValueError('component states must be supplied identifier lists')
            states.extend(part[key])
        if not part['source_states'] and not part['target_states']:
            raise ValueError('a component must account for source or target states')
        weight = number(part['source_yield_fraction'], 'source_yield_fraction', zero=True)
        ratio = number(part['response_ratio'], 'response_ratio', zero=True)
        if (not part['source_states'] and weight != 0) or (weight == 0 and ratio != 0):
            raise ValueError('a zero source contribution cannot establish a nonzero target response')
        if weight > 1:
            raise ValueError('source_yield_fraction exceeds one')
        if not part['target_states'] and ratio != 0:
            raise ValueError('an omitted target component must have zero response_ratio')
        fraction += weight
        response += weight*ratio
    import math
    if not math.isclose(fraction,1,rel_tol=0,abs_tol=1e-12):
        raise ValueError('component source yield fractions must sum to one')
    number(response,'total response ratio')
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate component id')
    for states, record in ((source_states,source),(target_states,target)):
        if len(set(states)) != len(states):
            raise ValueError('component state populations overlap')
        if record['state_count'] is not None and len(states) != record['state_count']:
            raise ValueError('component population differs from cross-section state_count')
    return response


def transform(rows, selected, base='.'):
    contract, base, commitment = load_contract(selected,base)
    header, by_tag = _population(rows,contract,'production-transformation')
    updated = copy.deepcopy(rows)
    for r in updated:
        if r.get('production_transformation'):
            raise ValueError('row already carries a production transformation; start from its source artifact')
        p = by_tag[r['tag']]
        require(p, ('source','target'), 'point cross sections', REASON)
        source = cross_sections.lookup(p['source'],base=base)
        target = cross_sections.lookup(p['target'],base=base)
        _parameters(p,source); _parameters(p,target)
        _row_coordinate(r, p)
        if source['sqrt_s_GeV'] != target['sqrt_s_GeV']:
            raise ValueError('production transformation cannot change collision energy')
        import math
        require(r, ('sigma_ref_fb',), 'source normalization', REASON)
        current = number(r['sigma_ref_fb'],'row.sigma_ref_fb')
        if not math.isclose(current,source['sigma_pb']*1000,rel_tol=1e-12):
            raise ValueError('source cross section differs from the row normalization')
        response = _components(p,source,target)
        factor = source['sigma_pb'] / (target['sigma_pb'] * response)
        before = copy.deepcopy(r)
        rescale_artifact(r,factor)
        r['sigma_ref_fb'] = target['sigma_pb']*1000
        r['excluded_obs'] = read_limits(r).observed.exclusion()
        r['production_transformation'] = {'parameters':p['parameters'],'source':source,'target':target,
            'components':p['components'],'shape_justification':p['shape_justification'],
            'response_ratio':response,'mu_scale':factor,'source_artifact':before}
    # Commit only after every point is valid, including bounded quantiles.
    rows[:] = updated
    return {**header,'contract':commitment,'points':[{'tag':r['tag'],**r['production_transformation']} for r in rows]}


def renormalize(rows, selected, manifest, kfactor_reader, base='.'):
    contract, base, commitment = load_contract(selected,base)
    header, by_tag = _population(rows,contract,'cross-section-renormalization')
    manifest_points = {p['tag']:p for p in manifest['points']}
    updated = copy.deepcopy(rows)
    for r in updated:
        if r.get('normalization_change'):
            raise ValueError('row already carries a normalization change')
        p = by_tag[r['tag']]
        require(p, ('correction','replaced_kfactor','application_justification'), 'normalization point')
        text(p['application_justification'], 'application_justification')
        flat = number(p['replaced_kfactor'],'replaced_kfactor')
        import math
        actual = kfactor_reader(manifest_points[r['tag']])
        if actual is None or not math.isclose(flat,actual,rel_tol=1e-12):
            raise ValueError('replaced_kfactor differs from the source normalization')
        value = correction(p['correction'],base)
        _parameters(p,value['source_records']['numerator'])
        _row_coordinate(r, p)
        factor = flat/value['k_factor']
        before = copy.deepcopy(r)
        require(r, ('sigma_ref_fb',), 'source normalization', REASON)
        current = number(r['sigma_ref_fb'],'row.sigma_ref_fb')
        rescale_artifact(r,factor)
        r['sigma_ref_fb'] = current/factor
        r['excluded_obs'] = read_limits(r).observed.exclusion()
        r['normalization_change'] = {'parameters':p['parameters'],'correction':value,
            'replaced_kfactor':flat,'application_justification':p['application_justification'],
            'mu_scale':factor,'source_artifact':before}
    rows[:] = updated
    return {**header,'contract':commitment,'points':[{'tag':r['tag'],**r['normalization_change']} for r in rows]}


def write_scan(scan, out, metadata):
    """Serialize the requested JSON object or JSONL population without discarding scan metadata."""
    result = dict(scan)
    result.update({k:metadata[k] for k in ('study_id','datasets','output_format')})
    return emit(result,out)
