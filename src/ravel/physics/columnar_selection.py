"""Changed columnar working points, dedicated source delta-R OR and joint response.

No reader or fit engine. MeV vectors remain aligned by source index. The source
declares ordered directed simultaneous removals, recoil association and detector
response; software does not infer ATLAS calibration or METMaker equivalence.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import os
from ravel.physics import root_stream_core as c, columnar_response as response


def _identity(value):
    if type(value) is dict:
        if set(value) == {'path', 'sha256', 'size'}:
            return {k: value[k] for k in ('sha256', 'size')}
        return {k: _identity(v) for k, v in value.items()}
    if type(value) is list: return [_identity(v) for v in value]
    return value


def selection_law(recipe):
    return _identity({k: recipe[k] for k in ('objects', 'overlap_removal', 'met',
                                            'trigger_by_year', 'scalar_scale_factors')})


def signature(recipe):
    return c.digest({'law': selection_law(recipe), 'source_identity': _identity(recipe['selection_source'])})


def _known_branch_role(recipe, name):
    """Known source roles precede every proposed use or unit label.

    Roles come from the recipe's supplied ``branch_roles`` descriptor, then from
    what the recipe itself declares it consumes. No format table is built in.
    Additional producer branches remain unknown here; their complete recoil
    association is still required, and a declaration cannot retype known fields.
    """
    from ravel.physics.columnar_ntuple_recipe import descriptor_role
    supplied = descriptor_role(recipe['branch_roles'], name)
    if supplied is not None: return supplied
    if name in ('year', 'mcChannelNumber'): return ('event_identifier', 'scalar', '1')
    if name == 'weight_mc_NOSYS': return ('generator_weight', 'scalar', '1')
    if name in recipe['scalar_scale_factors']: return ('scale_weight', 'scalar', '1')
    if any(name in bs for bs in recipe['trigger_by_year'].values()): return ('trigger_decision', 'scalar', '1')
    for obj in recipe['objects']:
        prefix = obj['prefix']
        if name == prefix + '_pt_NOSYS': return ('object_pt', 'jagged', 'MeV')
        if name == prefix + '_eta': return ('object_eta', 'jagged', '1')
        if name == prefix + '_phi': return ('object_phi', 'jagged', 'rad')
    return None


def _source_branch_role(recipe, name, coordinates=None):
    """One admission boundary for fixed native and actual declared consumers."""
    known = _known_branch_role(recipe, name)
    if known is not None: return known
    for obj in recipe['objects']:
        if any(name == g['branch'] for wp in obj['working_points'].values() for g in wp['gates']):
            return ('object_predicate', 'jagged', '1')
        if obj['tagger'] and name in obj['tagger'].values(): return ('object_tagger', 'jagged', '1')
    if any(name == g['gate']['branch'] for r in recipe['overlap_removal']['rules'] for g in r['gates']):
        return ('object_predicate', 'jagged', '1')
    axes = recipe['response']['coordinates'] if coordinates is None else coordinates
    if any(type(a) is dict and a.get('kind') == 'scalar' and a.get('branch') == name for a in axes):
        return ('response_coordinate', 'scalar', '1')
    return None


def _changed_predicate(recipe, branch):
    role = _known_branch_role(recipe, branch)
    c.require(role is None or role[0] != 'baseline_or',
              'stored baseline OR flags cannot define any changed object predicate or tagger field')


def _gate(recipe, gate, prefix):
    c.keys(gate, ('branch', 'kind', 'low', 'high'), 'source WP/pair gate')
    c.require(type(gate['branch']) is str and gate['branch'].isidentifier() and
              gate['branch'].startswith(prefix + '_'), 'same-container gate branch required')
    _changed_predicate(recipe, gate['branch'])
    c.require(gate['kind'] in ('bit', 'range'), 'literal flag or half-open range gate required')
    if gate['kind'] == 'bit':
        c.require(gate['low'] is None and gate['high'] is None, 'bit gate has no numerical interval')
    else:
        c.scalar(gate['low'])
        c.require(gate['high'] is None or c.scalar(gate['high']) > gate['low'], 'finite half-open score range required')


def recoil_law(met):
    """Association source cannot contain its own commitment recursively."""
    return _identity({k: v for k, v in met.items() if k != 'association_source'})


def validate_recoil(met, names):
    if met['kind'] == 'unused':
        c.keys(met, ('kind', 'components', 'objects'), 'unused changed MET')
        c.require(met['components'] == [] and met['objects'] == [], 'unused MET has no recoil terms')
        return
    c.keys(met, ('kind', 'components', 'objects', 'association', 'association_source'), 'changed recoil')
    c.require(met['kind'] == 'source_recoil' and type(met['components']) is list and
              1 <= len(met['components']) <= 32 and type(met['objects']) is list and
              len(met['objects']) <= len(names), 'bounded typed Cartesian recoil terms required')
    seen, term_ids, used = set(), set(), []
    for term in met['components']:
        c.keys(term, ('id', 'x', 'y', 'unit', 'sign', 'groups'), 'signed source recoil component')
        c.text(term['id']); c.require(term['id'] not in term_ids, 'distinct recoil component IDs required'); term_ids.add(term['id'])
        for key in ('x', 'y'):
            b = term[key]
            c.require(type(b) is str and b.isidentifier() and b not in seen and
                      not b.startswith(('metBaseline_', 'metSignal_')),
                      'distinct Cartesian branches required; stored MET magnitude/phi/sumET refused')
            seen.add(b)
        c.require(term['unit'] == 'MeV' and type(term['sign']) is int and term['sign'] in (-1, 1),
                  'explicit signed MeV Cartesian component required')
        c.require(type(term['groups']) is list and term['groups'] and len(term['groups']) <= 256 and
                  all(type(g) is str and g for g in term['groups']) and len(set(term['groups'])) == len(term['groups']),
                  'complete explicit component group association required')
        used.extend(term['groups'])
    object_names = set()
    for term in met['objects']:
        c.keys(term, ('object', 'sign', 'groups'), 'signed selected-object recoil term')
        c.require(term['object'] in names and term['object'] not in object_names and
                  type(term['sign']) is int and term['sign'] in (-1, 1),
                  'distinct declared selected-object term and explicit sign required')
        object_names.add(term['object'])
        c.require(type(term['groups']) is list and term['groups'] and len(term['groups']) <= 256 and
                  all(type(g) is str and g for g in term['groups']) and len(set(term['groups'])) == len(term['groups']),
                  'complete explicit selected-object group association required')
        used.extend(term['groups'])
    c.require(len(used) == len(set(used)), 'recoil groups may contribute exactly once; double counting refused')
    association = met['association']
    if association is None:
        c.require(met['association_source'] is None, 'missing association has no resolved producer source')
        return  # Source preparation hold; never an executable active-MET kernel.
    c.keys(association, ('convention', 'selection_objects', 'object_associations', 'population', 'groups'), 'complete recoil association')
    c.require(association['convention'] == 'signed_cartesian_sum_for_missing_transverse_momentum' and
              association['selection_objects'] == list(names), 'exact full changed-object roster and vector convention required')
    population = association['population']
    c.require(type(population) is list and 1 <= len(population) <= 2048 and
              all(type(x) is str and x for x in population) and len(population) == len(set(population)),
              'complete distinct primitive source-population census required')
    groups = association['groups']
    c.require(type(groups) is list and 1 <= len(groups) <= 256, 'complete bounded association groups required')
    by_group, members = {}, []
    for group in groups:
        c.keys(group, ('id', 'role', 'object', 'members'), 'source recoil association group')
        c.text(group['id']); c.require(group['id'] not in by_group, 'distinct association group IDs required')
        c.require(group['role'] in ('soft', 'unselected_hard', 'selected_objects', 'complete_changed_vector'), 'typed hard/soft/selected/complete-vector source role required')
        c.require((group['role'] == 'selected_objects' and group['object'] in names) or
                  (group['role'] != 'selected_objects' and group['object'] is None), 'source role and selected-object identity differ')
        c.require(type(group['members']) is list and group['members'] and
                  len(group['members']) <= 2048 and all(type(x) is str and x for x in group['members']),
                  'explicit primitive membership required')
        by_group[group['id']] = group; members.extend(group['members'])
    c.require(len(members) == len(set(members)) and set(members) == set(population),
              'source association must completely and disjointly partition its original population')
    c.require(set(used) == set(by_group), 'every source association group must contribute exactly once; omission refused')
    for term in met['components']:
        c.require(all(by_group[g]['role'] in ('soft', 'unselected_hard', 'complete_changed_vector') for g in term['groups']),
                  'Cartesian components cannot also contain separately selected-object groups')
    for term in met['objects']:
        c.require(all(by_group[g]['role'] == 'selected_objects' and by_group[g]['object'] == term['object'] for g in term['groups']),
                  'selected-object association differs from the actual post-WP/OR population')
    complete = [g for g in groups if g['role'] == 'complete_changed_vector']
    if complete:
        c.require(len(groups) == len(complete) == len(met['components']) == 1 and met['objects'] == [],
                  'complete changed-selection producer vector is a sole term, never combined twice')
    roster = association['object_associations']
    c.require(type(roster) is list and [r['object'] for r in roster] == list(names),
              'each changed object collection requires an explicit source MET association or exclusion')
    for row in roster:
        c.keys(row, ('object', 'treatment', 'groups', 'statement'), 'complete object recoil association')
        c.text(row['statement'])
        expected = [g['id'] for g in groups if g['role'] == 'selected_objects' and g['object'] == row['object']]
        if complete:
            c.require(row['treatment'] == 'complete_vector' and row['groups'] == [complete[0]['id']],
                      'complete producer vector must explicitly cover every changed object collection')
        elif expected:
            c.require(row['treatment'] == 'selected_term' and row['groups'] == expected,
                      'actual selected-object terms differ from complete source association')
        else:
            c.require(row['treatment'] == 'excluded' and row['groups'] == [],
                      'unused object collections require explicit source exclusion, never implicit omission')
    if met['association_source'] is not None: c.pin(met['association_source'])


def validate_recipe(recipe):
    from ravel.physics import columnar_ntuple_recipe as h
    fields = ('schema_version', 'objects', 'overlap_removal', 'met', 'trigger_by_year',
              'scalar_scale_factors', 'sf_applicability', 'regions', 'uncertainty_policy',
              'selection_source', 'response', 'branch_roles')
    c.require(type(recipe) is dict and 'branch_roles' in recipe,
              'changed recipe needs a supplied branch_roles format descriptor; no branch roles are built in')
    c.keys(recipe, (*fields, 'fitted_categories') if 'fitted_categories' in recipe else fields, 'changed columnar recipe')
    c.require(type(recipe['schema_version']) is int and recipe['schema_version'] == 2, 'changed recipe schema2 required')
    c.pin(recipe['selection_source'])
    shadow = deepcopy(recipe)
    for k in ('selection_source', 'response'): del shadow[k]
    shadow['schema_version'] = 1; shadow['met'] = 'Baseline'; shadow['overlap_removal'] = 'none'
    roles = h.branch_roles(shadow['branch_roles'])
    for obj in shadow['objects']:
        del obj['working_points']
        rule = h.container_rule(roles, obj['prefix'])
        obj['selection'] = 'stored' if rule is None else rule['selections'][0]
    # Reuse the original region, scalar-weight, year, role descriptor and full fitted law checks.
    recipe = {**recipe, 'branch_roles': h.validate_recipe(shadow)['branch_roles']}
    names = {o['name']: o for o in recipe['objects']}
    years = set(recipe['trigger_by_year'])
    for obj in recipe['objects']:
        c.keys(obj, ('name', 'prefix', 'selection', 'pt_min_GeV', 'abs_eta_max',
                     'scale_factors', 'tagger', 'working_points'), 'changed object')
        c.require(obj['selection'] == 'source_defined' and obj['scale_factors'] == [],
                  'changed object corrections use one joint selected-object ratio, not extra SF products')
        c.require(type(obj['working_points']) is dict and set(obj['working_points']) == years,
                  'every declared year requires an explicit object WP')
        if obj['tagger']:
            for branch in obj['tagger'].values():
                if branch is not None: _changed_predicate(recipe, branch)
        for wp in obj['working_points'].values():
            c.keys(wp, ('id', 'isolation', 'gates'), 'source working point')
            c.text(wp['id']); c.require(wp['isolation'] is None or type(wp['isolation']) is str and wp['isolation'], 'explicit isolation identity or source absence required')
            c.require(type(wp['gates']) is list and len(wp['gates']) <= 32 and
                      len({g['branch'] for g in wp['gates']}) == len(wp['gates']), 'distinct bounded complete WP gates required')
            for g in wp['gates']: _gate(recipe, g, obj['prefix'])
    overlap = recipe['overlap_removal']
    c.keys(overlap, ('semantics', 'rules', 'max_pair_checks_per_event'), 'recomputed overlap')
    c.integer(overlap['max_pair_checks_per_event'], 1, 10**7, 'prospective source pair-work ceiling')
    c.require(overlap['semantics'] == 'ordered_directed_simultaneous_deltaR' and
              type(overlap['rules']) is list and len(overlap['rules']) <= 64 and
              len({r['id'] for r in overlap['rules']}) == len(overlap['rules']), 'explicit bounded ordered removal rules required')
    for rule in overlap['rules']:
        c.keys(rule, ('id', 'target', 'against', 'radius', 'gates'), 'directed removal rule')
        c.text(rule['id']); c.require(rule['target'] in names and rule['against'] in names, 'declared target/partner object populations required')
        rad = rule['radius']; c.keys(rad, ('kind', 'constant', 'offset', 'scale_GeV', 'cap'), 'delta-R radius')
        if rad['kind'] == 'constant':
            c.require(0 < c.scalar(rad['constant']) <= math.pi and all(rad[k] is None for k in ('offset', 'scale_GeV', 'cap')), 'positive finite source constant radius required')
        else:
            c.require(rad['kind'] == 'target_inverse_pt' and rad['constant'] is None and
                      c.scalar(rad['offset']) >= 0 and c.scalar(rad['scale_GeV']) >= 0 and
                      0 < c.scalar(rad['cap']) <= math.pi, 'source min(cap,offset+scale/pT_target) radius required')
        c.require(type(rule['gates']) is list and len(rule['gates']) <= 32, 'bounded pair gates required')
        for pair in rule['gates']:
            c.keys(pair, ('side', 'gate'), 'pair gate'); c.require(pair['side'] in ('target', 'against'), 'explicit pair side required')
            _gate(recipe, pair['gate'], names[rule[pair['side']]]['prefix'])
    met = recipe['met']; validate_recoil(met, names)
    if met['kind'] == 'unused':
        c.require(met['components'] == [] and met['objects'] == [] and
                  all(r['met_GeV'] == [0, None] for r in recipe['regions']), 'unused MET requires all MET cuts inactive')
    c.keys(recipe['response'], ('request', 'payload', 'coordinates'), 'joint response binding')
    c.require(type(recipe['response']['coordinates']) is list, 'source-declared response coordinates required')
    c.pin(recipe['response']['request'])
    if recipe['response']['payload'] is not None: c.pin(recipe['response']['payload'])
    for term in met['components']:
        for branch in (term['x'], term['y']):
            c.require(_source_branch_role(recipe, branch) is None,
                      'known source branch roles cannot be retyped as Cartesian MeV recoil components')
    for axis in recipe['response']['coordinates']:
        c.require(type(axis) is dict, 'typed response coordinate required')
        if axis.get('kind') == 'scalar':
            branch = axis.get('branch')
            c.require(type(branch) is str and branch.isidentifier(), 'literal scalar response branch required')
            role = _source_branch_role(recipe, branch)
            c.require(role is not None and role[1:] == ('scalar', '1') and
                      not branch.startswith(('metBaseline_', 'metSignal_')) and
                      branch not in {b for t in met['components'] for b in (t['x'], t['y'])},
                      'scalar response coordinate must preserve its known dimensionless scalar source role')
    return deepcopy(recipe)


def _read(declaration, base, cap):
    path, raw = cap.read(declaration, base, 8 * 1024**2)
    return path, c.strict(raw)


def bind(recipe, base, cap):
    """Every dependency consumed through its own actual document base."""
    recipe = validate_recipe(recipe)
    def bound(pin, parent):
        path, _ = cap.read(pin, parent, 8 * 1024**2)
        return {**pin, 'path': str(path)}
    recipe['selection_source'] = bound(recipe['selection_source'], base)
    declaration = cap.document(recipe['selection_source'], base)
    c.keys(declaration, ('schema_version', 'kind', 'law', 'statement'), 'selection source declaration')
    c.require(type(declaration['schema_version']) is int and declaration['schema_version'] == 1 and
              declaration['kind'] == 'source_declared_changed_columnar_selection' and
              declaration['law'] == selection_law(recipe), 'exact source WP/OR/recoil/trigger law differs')
    c.text(declaration['statement'])
    recoil = recipe['met']; recoil_ready = True; recoil_evidence = None
    if recoil['kind'] == 'source_recoil':
        recoil_ready = recoil['association'] is not None and recoil['association_source'] is not None
        if recoil_ready:
            recoil['association_source'] = bound(recoil['association_source'], base)
            evidence = cap.document(recoil['association_source'], base)
            c.keys(evidence, ('schema_version', 'kind', 'selection', 'law', 'statement'), 'recoil producer association source')
            c.require(type(evidence['schema_version']) is int and evidence['schema_version'] == 1 and
                      evidence['kind'] == 'source_declared_complete_disjoint_changed_recoil' and
                      evidence['selection'] == _identity({k: recipe[k] for k in ('objects', 'overlap_removal')}) and
                      evidence['law'] == recoil_law(recoil), 'actual source recoil population/selection/sign association differs')
            c.text(evidence['statement']); recoil_evidence = recoil['association_source']
    rb = recipe['response']; rp, request = _read(rb['request'], base, cap)
    rb['request'] = {**rb['request'], 'path': str(rp)}
    response.validate_request(request, signature(recipe), recipe['trigger_by_year'])
    c.require(request['coordinates'] == recipe['response']['coordinates'], 'recipe response axes differ from actual calibration request')
    bound(request['source'], rp.parent); bound(request['acquisition']['configuration_source'], rp.parent)
    payload = None
    if rb['payload'] is not None:
        pp, payload = _read(rb['payload'], base, cap); rb['payload'] = {**rb['payload'], 'path': str(pp)}
        bound(payload['source'], pp.parent)
        for pin in payload['inputs']: bound(pin, pp.parent)
    compiled = response.prepare(request, rb['request'], payload, signature(recipe), recipe['trigger_by_year'])
    compiled['recoil_association'] = {'ready': recoil_ready, 'source': recoil_evidence,
        'scope': 'Source-declared association algebra; detector completeness and METMaker equivalence remain unqualified.'}
    if not recoil_ready:
        compiled['ready'] = False
        compiled.setdefault('missing', []).append('complete_source_bound_changed_selection_recoil_association')
        compiled['recoil_acquisition'] = {'kind': 'source_recoil_association_acquisition',
            'required': ['actual primitive detector-source population census',
                         'complete disjoint hard/soft or complete-vector producer association',
                         'explicit Cartesian signs and units for the exact changed WP/ordered OR'],
            'requested_law': recoil_law(recoil),
            'selection': _identity({k: recipe[k] for k in ('objects', 'overlap_removal')}),
            'selection_source': recipe['selection_source'], 'selection_sha256': signature(recipe),
            'next_action': 'Obtain the actual producer association record; bind its exact bytes and rebuild the joint calibration for this selection identity.',
            'execution_authorized': False, 'physics_validated': False}
    object_names = {o['name'] for o in recipe['objects']}
    object_branches = {b for o in recipe['objects'] for b in
        (o['prefix']+'_pt_NOSYS', o['prefix']+'_eta', o['prefix']+'_phi')}
    object_branches.update(g['branch'] for o in recipe['objects'] for wp in o['working_points'].values() for g in wp['gates'])
    object_branches.update(g['gate']['branch'] for r in recipe['overlap_removal']['rules'] for g in r['gates'])
    object_branches.update(b for o in recipe['objects'] if o['tagger'] for b in o['tagger'].values() if b is not None)
    c.require(not object_branches.intersection(b for t in recoil['components'] for b in (t['x'], t['y'])),
              'object-vector branches cannot masquerade as scalar recoil components')
    for a in request['coordinates']:
        c.require(a['object'] is None or a['object'] in object_names, 'response axis must use actual selected population')
        c.require(a['kind'] != 'met' or recipe['met']['kind'] != 'unused', 'unused MET cannot condition response')
        if a['kind'] == 'scalar':
            role = _source_branch_role(recipe, a['branch'], request['coordinates'])
            c.require(role is not None and role[1:] == ('scalar', '1'),
                      'scalar response coordinate must preserve its known dimensionless scalar source role')
            c.require(not a['branch'].startswith(('metBaseline_', 'metSignal_')) and
                      a['branch'] not in object_branches and
                      a['branch'] not in {b for t in recipe['met']['components'] for b in (t['x'],t['y'])},
                      'scalar response axes cannot disguise object vectors or stored/object-dependent MET')
    for row in recipe['sf_applicability']: row['source'] = bound(row['source'], base)
    if 'fitted_categories' in recipe: recipe['fitted_categories']['source'] = bound(recipe['fitted_categories']['source'], base)
    c.require(len(cap.rows) <= 128 and sum(p['size'] for p in cap.rows.values()) <= 32*1024**2,
              'complete prospective source bundle bound exceeded')
    return recipe, compiled


def required_branches(recipe, request=None):
    recipe = validate_recipe(recipe)
    branches = {'year', 'mcChannelNumber', 'weight_mc_NOSYS', *recipe['scalar_scale_factors']}
    branches.update(b for bs in recipe['trigger_by_year'].values() for b in bs)
    for o in recipe['objects']:
        p = o['prefix']; branches.update((p+'_pt_NOSYS', p+'_eta', p+'_phi'))
        for wp in o['working_points'].values(): branches.update(g['branch'] for g in wp['gates'])
        if o['tagger']: branches.update(b for b in o['tagger'].values() if b is not None)
    for rule in recipe['overlap_removal']['rules']: branches.update(g['gate']['branch'] for g in rule['gates'])
    for term in recipe['met']['components']: branches.update((term['x'], term['y']))
    branches.update(a['branch'] for a in recipe['response']['coordinates'] if a['kind'] == 'scalar')
    return sorted(branches)


def bit_branches(recipe):
    """Every changed-selection branch read as a literal 0/1 flag: bit gates, triggers and tagger flags."""
    recipe = validate_recipe(recipe)
    flags = {g['branch'] for o in recipe['objects'] for wp in o['working_points'].values() for g in wp['gates'] if g['kind'] == 'bit'}
    flags.update(g['gate']['branch'] for r in recipe['overlap_removal']['rules'] for g in r['gates'] if g['gate']['kind'] == 'bit')
    flags.update(b for bs in recipe['trigger_by_year'].values() for b in bs)
    flags.update(o['tagger'][k] for o in recipe['objects'] if o['tagger'] for k in ('tagged', 'valid', 'mass') if o['tagger'][k] is not None)
    return flags


def branch_description(recipe, request, name):
    role = _source_branch_role(recipe, name, request['coordinates'])
    if role is not None: return role[1:]
    if any(name in (t['x'], t['y']) for t in recipe['met']['components']): return ('scalar', 'MeV')
    return ('jagged', 'MeV' if name.endswith('_pt_NOSYS') else 'rad' if name.endswith('_phi') else '1')


def _passed(event, gate, i):
    from ravel.physics.columnar_ntuple_recipe import bit, number
    x = event[gate['branch']][i]
    if gate['kind'] == 'bit': return bit(x)
    x = number(x)
    c.require(x != -666, 'did-not-run sentinel cannot be a calibrated score')
    return gate['low'] <= x and (gate['high'] is None or x < gate['high'])


def _coordinates(event, selected, met, axes):
    result=[]
    for a in axes:
        if a['kind']=='scalar': value=c.scalar(event[a['branch']])
        elif a['kind']=='met': value=met
        else:
            obj=selected[a['object']]
            if a['kind']=='count': value=len(obj['indices'])
            elif a['kind']=='sum_pt': value=math.fsum(obj['pt_GeV'])
            else:
                if a['rank'] >= len(obj['indices']):
                    c.require(a['missing'] is not None, 'declared response rank missing; no invented coordinate')
                    value=a['missing']
                else: value=obj['pt_GeV' if a['kind']=='pt' else 'abs_eta'][a['rank']]
        result.append(c.scalar(value))
    return result


def selection_view(event, recipe, axes):
    from ravel.physics.columnar_ntuple_recipe import bit, number
    year=event['year']; c.require(type(year) is int and str(year) in recipe['trigger_by_year'], 'source year has no declared WP/trigger strategy')
    passed=any([bit(event[b]) for b in recipe['trigger_by_year'][str(year)]])
    selected={}; byname={o['name']:o for o in recipe['objects']}
    for o in recipe['objects']:
        p=o['prefix']; wp=o['working_points'][str(year)]; pts=event[p+'_pt_NOSYS']; fields={p+'_pt_NOSYS',p+'_eta',p+'_phi',*(g['branch'] for g in wp['gates'])}
        if o['tagger']: fields.update(b for b in o['tagger'].values() if b is not None)
        for r in recipe['overlap_removal']['rules']:
            for g in r['gates']:
                if r[g['side']]==o['name']: fields.add(g['gate']['branch'])
        c.require(type(pts) is list and all(type(event[b]) is list and len(event[b])==len(pts) for b in fields), 'complete aligned source object vectors required')
        indices=[]
        for i,pt in enumerate(pts):
            c.require(number(pt)>=0, 'nonnegative source pT required'); eta=number(event[p+'_eta'][i]); number(event[p+'_phi'][i])
            ok=all([_passed(event,g,i) for g in wp['gates']]); tag=o['tagger']
            if tag:
                tagged,valid=bit(event[tag['tagged']][i]),bit(event[tag['valid']][i])
                score=None if tag['score'] is None else number(event[tag['score']][i])
                c.require(not(valid and score==-666),'valid tagger may not carry did-not-run sentinel')
                ok=ok and tagged and valid and score!=-666 and (tag['mass'] is None or bit(event[tag['mass']][i]))
            if ok and pt/1000 >= o['pt_min_GeV'] and abs(eta)<o['abs_eta_max']: indices.append(i)
        selected[o['name']]=indices
    pair_checks=0
    for rule in recipe['overlap_removal']['rules']:
        target,against=rule['target'],rule['against'];tp,ap=byname[target]['prefix'],byname[against]['prefix']; removed=set()
        for i in selected[target]:
            rad=rule['radius']
            pt=event[tp+'_pt_NOSYS'][i]/1000
            if rad['kind']=='constant': radius=rad['constant']
            else:
                c.require(pt>0,'shrinking source radius requires positive target pT')
                radius=min(rad['cap'],rad['offset']+rad['scale_GeV']/pt)
            for j in selected[against]:
                pair_checks+=1
                c.require(pair_checks<=recipe['overlap_removal']['max_pair_checks_per_event'], 'source pair-work ceiling exhausted; no truncated selection')
                if target==against and i==j: continue
                if not all([_passed(event,g['gate'],i if g['side']=='target' else j) for g in rule['gates']]): continue
                dphi=math.remainder(math.remainder(event[tp+'_phi'][i],2*math.pi)-math.remainder(event[ap+'_phi'][j],2*math.pi),2*math.pi)
                dr=math.hypot(event[tp+'_eta'][i]-event[ap+'_eta'][j],dphi)
                c.require(math.isfinite(dr),'delta-R exceeds finite representation')
                if dr<radius: removed.add(i); break
        selected[target]=[i for i in selected[target] if i not in removed]
    objects={}
    for name,ids in selected.items():
        p=byname[name]['prefix']; ids.sort(key=lambda i:-event[p+'_pt_NOSYS'][i])
        objects[name]={'indices':ids,'pt_GeV':[event[p+'_pt_NOSYS'][i]/1000 for i in ids],
                       'abs_eta':[abs(event[p+'_eta'][i]) for i in ids]}
    met=0.0
    if recipe['met']['kind']=='source_recoil':
        c.require(recipe['met']['association'] is not None, 'missing source recoil association cannot be evaluated')
        xs=[t['sign']*c.scalar(event[t['x']])/1000 for t in recipe['met']['components']]
        ys=[t['sign']*c.scalar(event[t['y']])/1000 for t in recipe['met']['components']]
        for term in recipe['met']['objects']:
            name=term['object']
            p=byname[name]['prefix']
            for i in selected[name]:
                pt=event[p+'_pt_NOSYS'][i]/1000; phi=event[p+'_phi'][i]
                xs.append(term['sign']*pt*math.cos(phi));ys.append(term['sign']*pt*math.sin(phi))
        met=c.scalar(math.hypot(math.fsum(xs),math.fsum(ys)))
    coordinates=_coordinates(event,objects,met,axes)
    return {'trigger_passed':passed,'objects':objects,'met_GeV':met,'response_coordinates':coordinates}


def event_view(event, recipe, compiled):
    c.require(compiled['ready'] and compiled['request']['selection_sha256']==signature(recipe) and
              compiled['request_pin']==recipe['response']['request'] and
              compiled['request']['coordinates']==recipe['response']['coordinates'],
              'complete current selection/request/response correspondence required')
    view=selection_view(event,recipe,compiled['request']['coordinates'])
    c.require(type(event['mcChannelNumber']) is int,'literal actual MC DSID required')
    factor=response.factor(compiled,str(event['year']),event['mcChannelNumber'],view['response_coordinates'],view['trigger_passed'])
    return {**view,'object_factor':factor,'response_applied':view['trigger_passed']}


def records(events, entries, sample, recipe, compiled):
    # Reuse the exact existing region/co-fill/complete-entry logic. No source
    # monkeypatch: pass fixed computed views to the shared records helper.
    from ravel.physics.columnar_ntuple_recipe import records_from_views
    c.require(len(events)==len(entries), 'all original source entries required')
    c.require(all(type(e['mcChannelNumber']) is int and e['mcChannelNumber']==sample['dsid'] for e in events), 'original MC sample identity differs')
    return records_from_views([event_view(e,recipe,compiled) for e in events],entries,recipe)


def kernel_bytes(recipe, compiled):
    checked=validate_recipe(recipe); c.require(compiled['ready'],'missing response cannot produce an executable kernel')
    encoded=json.dumps(checked,sort_keys=True,allow_nan=False); table=json.dumps(compiled,sort_keys=True,allow_nan=False)
    raw = ('import json\nfrom ravel.physics import columnar_selection as s\nRECIPE=s.validate_recipe(json.loads('+repr(encoded)+'))\nRESPONSE=json.loads('+repr(table)+')\n'
            'def event_factors(table, entries, sample):\n    import awkward as ak\n    rows=ak.to_list(table)\n    if len(rows)!=len(entries): raise ValueError("complete source entries required")\n    if any(e["mcChannelNumber"]!=sample["dsid"] for e in rows): raise ValueError("original sample differs")\n    return [s.event_view(e,RECIPE,RESPONSE)["object_factor"] for e in rows]\n'
            'def analyze(table, entries, sample):\n    import awkward as ak\n    return s.records(ak.to_list(table),entries,sample,RECIPE,RESPONSE)\n').encode()
    c.require(len(raw)<=8*1024**2,'complete generated kernel exceeds existing ROOT document budget')
    return raw


class SourceTracker:
    """Finite observation wrapper retaining actual source/base and bytes."""
    def __init__(self, capture):
        self.capture = capture; self.rows = {}; self.raw = {}

    def read(self, declaration, base, limit=8*1024**2):
        declared=Path(declaration['path']);declared=(declared if declared.is_absolute() else Path(base)/declared).absolute()
        # A dependency is named from its own document base and may step to a sibling
        # directory. Without a linked component the lexical path is the path the system
        # resolves, so exactly that one path is budgeted, consumed and retained.
        c.require(not any(p.is_symlink() for p in (declared,*declared.parents)),
                  'ordinary unlinked scientific dependency path required')
        lexical=Path(os.path.normpath(str(declared)))
        if lexical not in self.rows:
            c.require(len(self.rows)<128 and sum(p['size'] for p in self.rows.values())+declaration['size']<=32*1024**2,
                      'reserve complete scientific dependency bytes before consumption')
        path, raw = self.capture.read({**declaration,'path':str(lexical)}, base, limit)
        self.rows[path] = {**declaration, 'path': str(path)}; self.raw[path] = raw
        return path, raw

    def document(self, declaration, base):
        return c.strict(self.read(declaration, base)[1])


def rebase_recipe(recipe, base, capture):
    tracker = SourceTracker(capture)
    checked, compiled = bind(recipe, base, tracker)
    return checked, compiled, tracker


def input_pins(recipe, base, capture):
    _, _, tracker = rebase_recipe(recipe, base, capture)
    return list(tracker.rows.values())


def publish_dependencies(tracker, out, emitted):
    """Copy exact original scientific input bytes, never rewrite nested pins."""
    from ravel.physics import root_stream as stream
    out = Path(out); (out/'selection-dependencies').mkdir()
    files={}; rows=[]
    for i,(path,pin) in enumerate(tracker.rows.items()):
        member='selection-dependencies/source_%04d'%i; raw=tracker.raw[path]
        c.require(hashlib.sha256(raw).hexdigest()==pin['sha256'] and len(raw)==pin['size'], 'intended dependency bytes differ')
        with (out/member).open('xb') as handle: handle.write(raw)
        transported={**pin,'path':str(out/member)}; emitted.append(transported); files[member]=transported
        stream.custody.asset_check({transported['path']:transported})
        rows.append({'original':pin,'member':member})
    manifest=stream.write_new(out/'selection-dependencies.json',{'schema_version':1,'files':rows})
    emitted.append(manifest);files['selection-dependencies.json']=manifest
    return files


class BundleCapture:
    """Explicit original pin -> exact copied bytes; not hash-equality fiction.

    Returned original paths are recorded document bases for resolving nested
    references. Actual observation and ending custody belong to copied files.
    """
    def __init__(self, rows, files, base, cap):
        self.by_original={}; self.rows={};self.files=files;self.base=base;self.cap=cap;self.used=set()
        c.require(sum(r['original']['size'] for r in rows)<=32*1024**2,'complete copied dependency budget exceeded')
        for row in rows:
            c.keys(row,('original','member'),'scientific dependency transport');c.pin(row['original'])
            c.require(Path(row['original']['path']).is_absolute() and row['member'] in files,
                      'canonical original base and actual bundle member required')
            path=Path(row['original']['path']);c.require(path not in self.by_original,'duplicate original transport refused')
            transport=files[row['member']]; c.pin(transport)
            c.require((transport['sha256'],transport['size'])==(row['original']['sha256'],row['original']['size']), 'scientific dependency must be exact bytes')
            self.by_original[path]=row

    def read(self, declaration, base, limit=8*1024**2):
        c.pin(declaration); path=Path(declaration['path'])
        if not path.is_absolute(): path=Path(base)/path
        path=Path(os.path.normpath(path))
        c.require(path in self.by_original and self.by_original[path]['original']=={**declaration,'path':str(path)}, 'undeclared or changed original dependency refused')
        row=self.by_original[path]; _,raw=self.cap.read(self.files[row['member']],self.base,limit)
        self.rows[path]=row['original'];self.used.add(row['member'])
        return path,raw

    def document(self, declaration, base): return c.strict(self.read(declaration,base)[1])


def verify_bundle(recipe, config, base, cap, *, extra_members=()):
    files=config['bundle']['files']
    c.require(config['bundle']['entry']=='kernel.py' and config['bundle']['blind_entry'] is None and
              'selection-dependencies.json' in files, 'exact changed-selection dependency bundle required')
    manifest=cap.document(files['selection-dependencies.json'],base)
    c.keys(manifest,('schema_version','files'),'selection dependency transport')
    c.require(type(manifest['schema_version']) is int and manifest['schema_version']==1 and
              type(manifest['files']) is list and 1<=len(manifest['files'])<=125,
              'complete bounded scientific input transport required')
    transport=BundleCapture(manifest['files'],files,base,cap)
    checked,compiled=bind(recipe,base,transport)
    c.require(transport.used=={r['member'] for r in manifest['files']} and
              set(files)=={'kernel.py','selection-dependencies.json',*transport.used,*extra_members},
              'missing, unused or extra scientific/kernel bundle members refused')
    _,raw=cap.read(files['kernel.py'],base)
    c.require(raw==kernel_bytes(checked,compiled), 'actual executed selection and joint response kernel differs')
    return checked,compiled


def compiled_recipe(recipe, base="."):
    cap=c.Capture(); checked,compiled=bind(recipe,base,cap);cap.finish()
    return checked,compiled


def canonical_references(recipe, base):
    """Record original document bases without pretending copied files are originals."""
    result=validate_recipe(recipe)
    pins=[result["selection_source"],result["response"]["request"],*(r["source"] for r in result["sf_applicability"])]
    if result['met']['kind'] == 'source_recoil' and result['met']['association_source'] is not None:
        pins.append(result['met']['association_source'])
    if result["response"]["payload"] is not None: pins.append(result["response"]["payload"])
    if "fitted_categories" in result: pins.append(result["fitted_categories"]["source"])
    for pin in pins:
        p=Path(pin["path"]);p=p if p.is_absolute() else Path(base)/p
        pin["path"]=os.path.normpath(str(p.absolute()))
    return result
