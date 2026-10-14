"""Nominal columnar ntuple selection recipe; no reader, calibration or inference engine.

The supplied ntuple format defines MeV units, aligned unsorted objects,
baseline-only stored OR and best-effort SFs. A recipe is a declared analysis,
not task closure. No container, period or branch table is built in: which
branches exist and what they mean come from the supplied branch schema and an
optional supplied ``branch_roles`` descriptor (see :func:`branch_roles`).
"""
from copy import deepcopy
import math
import re

SELECTIONS = ('baseline', 'signal', 'stored')
ROLE_KEYS = ('schema_version', 'kind', 'name', 'source', 'branches', 'families', 'periods', 'period_scoped_weights')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys(value, names, label):
    require(type(value) is dict and set(value) == set(names), 'closed ' + label + ' required')


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), 'finite numeric source required')
    return value


def bit(value):
    require(type(value) in (int, bool) and value in (0, 1), 'literal 8-bit 0/1 flag required')
    return bool(value)


def interval(value):
    require(type(value) is list and len(value) == 2 and number(value[0]) >= 0 and
            (value[1] is None or number(value[1]) > value[0]), 'half-open nonnegative interval required')


def branch_roles(doc):
    """Validate a supplied branch-role descriptor; the format's roles are data, never code.

    ``{"schema_version": 1, "kind": "columnar-branch-roles", "name", "source",
    "branches": [{"name", "role", "shape", "unit"}], "families": [{"pattern", "role", "shape", "unit"}],
    "periods": [...], "period_scoped_weights": {"<scalar weight>": [<periods>]}}``. ``unit`` null
    means the format fixes no absolute unit and the bound branch schema must state one.
    ``periods`` and ``period_scoped_weights`` are optional.
    """
    require(type(doc) is dict and doc.get('schema_version') == 1 and doc.get('kind') == 'columnar-branch-roles' and
            set(doc) <= set(ROLE_KEYS) and {'name', 'source', 'branches', 'families'} <= set(doc),
            'supplied columnar-branch-roles descriptor (schema 1) required')
    require(all(type(doc[k]) is str and doc[k].strip() for k in ('name', 'source')), 'descriptor name and source required')
    def row(r, key):
        keys(r, (key, 'role', 'shape', 'unit'), 'branch-role row')
        require(type(r['role']) is str and re.fullmatch('[a-z][a-z_]{0,63}', r['role']) and
                r['shape'] in ('scalar', 'jagged') and (r['unit'] is None or type(r['unit']) is str and r['unit'].strip()),
                'typed branch role, shape and unit (or null) required')
    require(type(doc['branches']) is list and len(doc['branches']) <= 4096 and
            type(doc['families']) is list and len(doc['families']) <= 256, 'bounded branch and family roles required')
    for r in doc['branches']:
        row(r, 'name'); require(type(r['name']) is str and r['name'].isidentifier(), 'literal branch name required')
    require(len({r['name'] for r in doc['branches']}) == len(doc['branches']), 'distinct branch roles required')
    for r in doc['families']:
        row(r, 'pattern')
        require(type(r['pattern']) is str and 0 < len(r['pattern']) <= 256, 'bounded family pattern required')
        try: re.compile(r['pattern'])
        except re.error: require(False, 'family pattern must be a regular expression')
    if 'periods' in doc:
        require(type(doc['periods']) is list and doc['periods'] and len(set(doc['periods'])) == len(doc['periods']) and
                all(type(p) is str and re.fullmatch('[0-9]{4}', p) for p in doc['periods']), 'distinct declared period keys required')
    if 'period_scoped_weights' in doc:
        scoped = doc['period_scoped_weights']
        require(type(scoped) is dict and all(type(w) is str and w.isidentifier() and type(ps) is list and ps and
                all(type(p) is str and re.fullmatch('[0-9]{4}', p) for p in ps) for w, ps in scoped.items()),
                'period-scoped weights map literal weights to declared periods')
    return deepcopy(doc)


def descriptor_role(roles, name):
    """(role, shape, unit) from a supplied descriptor, exact names before families; None when unknown."""
    if roles is None: return None
    for r in roles['branches']:
        if r['name'] == name: return (r['role'], r['shape'], r['unit'])
    for r in roles['families']:
        if re.fullmatch(r['pattern'], name): return (r['role'], r['shape'], r['unit'])
    return None


def validate_recipe(recipe):
    if type(recipe) is dict and recipe.get("schema_version") == 2:
        from ravel.physics import columnar_selection as s
        return s.validate_recipe(recipe)
    fields = ('schema_version', 'objects', 'overlap_removal', 'met', 'trigger_by_year',
              'scalar_scale_factors', 'sf_applicability', 'regions', 'uncertainty_policy')
    optional = tuple(k for k in ('fitted_categories', 'branch_roles') if type(recipe) is dict and k in recipe)
    keys(recipe, (*fields, *optional), 'columnar ntuple recipe')
    roles = branch_roles(recipe['branch_roles']) if 'branch_roles' in recipe else None
    require(type(recipe['schema_version']) is int and recipe['schema_version'] == 1, 'recipe schema1 required')
    require(recipe['overlap_removal'] in ('none', 'standard', 'largeR'), 'explicit stored OR choice required')
    require(recipe['met'] in ('Baseline', 'Signal'), 'explicit native MET flavour required')
    require(recipe['uncertainty_policy'] == 'nominal_only_missing_variations_explicit', 'no invented variations')
    require(type(recipe['objects']) is list and recipe['objects'], 'complete selected object declarations required')
    names = set(); prefixes = set()
    for obj in recipe['objects']:
        keys(obj, ('name', 'prefix', 'selection', 'pt_min_GeV', 'abs_eta_max', 'scale_factors', 'tagger'), 'object')
        require(type(obj['name']) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', obj['name']) and
                obj['name'] not in names and type(obj['prefix']) is str and
                re.fullmatch('[A-Za-z][A-Za-z0-9]*', obj['prefix']), 'distinct declared object name/prefix required')
        names.add(obj['name'])
        require(obj['prefix'] not in prefixes, 'one SF/selection population per native container required')
        prefixes.add(obj['prefix'])
        require(number(obj['pt_min_GeV']) >= 0 and number(obj['abs_eta_max']) > 0, 'explicit object kinematic cuts required')
        # Whether a container stores these flags is a fact of the supplied branch schema.
        require(obj['selection'] in SELECTIONS, 'unsupported stored object selection')
        if recipe['overlap_removal'] != 'none':
            require(obj['selection'] != 'signal', 'stored overlap removal is baseline-only')
        require(type(obj['scale_factors']) is list and len(set(obj['scale_factors'])) == len(obj['scale_factors']), 'distinct object factors required')
        for sf in obj['scale_factors']:
            require(type(sf) is str and sf.startswith(obj['prefix'] + '_') and
                    re.fullmatch('[A-Za-z0-9_]+', sf), 'literal same-container SF branch required')
        tag = obj['tagger']
        if tag is not None:
            keys(tag, ('tagged', 'valid', 'score', 'mass'), 'tagger')
            for field, branch in tag.items():
                require((field in ('score', 'mass') and branch is None) or
                        (type(branch) is str and branch.startswith(obj['prefix'] + '_') and
                         re.fullmatch('[A-Za-z0-9_]+', branch)), 'literal same-container tagger source branch required')
            # The calibrated-range flag is mandatory; its name comes from the supplied format.
            require(tag['valid'] not in (tag['tagged'], tag['score'], tag['mass']), 'explicit calibrated-range flag required')
    if recipe['overlap_removal'] != 'none':
        require(recipe['met'] == 'Baseline', 'stored baseline OR cannot assert signal MET consistency')
    require(type(recipe['trigger_by_year']) is dict and recipe['trigger_by_year'], 'source-defined year/trigger map required')
    periods = roles.get('periods') if roles else None
    for year, branches in recipe['trigger_by_year'].items():
        require(type(year) is str and re.fullmatch('[0-9]{4}', year) and (periods is None or year in periods) and
                type(branches) is list and branches and
                len(set(branches)) == len(branches), 'distinct year-specific trigger OR required')
        for branch in branches:
            require(type(branch) is str and re.fullmatch('trigPassed_[A-Za-z0-9_]+', branch), 'literal trigger decision branch required')
    require(type(recipe['scalar_scale_factors']) is list and
            len(set(recipe['scalar_scale_factors'])) == len(recipe['scalar_scale_factors']) and
            all(type(w) is str and w.isidentifier() and w != 'weight_mc_NOSYS' for w in recipe['scalar_scale_factors']),
            'explicit available nominal scalar weights required')
    for weight in recipe['scalar_scale_factors']:
        role = descriptor_role(roles, weight)
        require(role is None or role == ('scale_weight', 'scalar', '1'), 'scalar weight must keep its supplied scale-weight role')
        scope = (roles or {}).get('period_scoped_weights', {}).get(weight)
        require(scope is None or set(recipe['trigger_by_year']) <= set(scope),
                weight + ' is supplied only for periods ' + ','.join(scope or ()) + '; separate campaign recipes required')
    # Electron/muon trigger OR SF formula and WP-dependent efficiencies are not
    # approximated by a product of single-lepton scale factors.
    for obj in recipe['objects']:
        require(not any('trig' in sf.lower() for sf in obj['scale_factors']), 'lepton trigger OR efficiency/SF needs a separately reviewed event law')
    applicable = recipe['sf_applicability']
    require(type(applicable) is list and applicable, 'explicit SF/trigger/OR applicability record required')
    for row in applicable:
        keys(row, ('subject', 'source', 'treatment', 'limitations'), 'applicability')
        from ravel.physics.root_stream_core import pin
        pin(row['source'])
        require(type(row['subject']) is str and row['subject'] and
                row['treatment'] == 'declared_conditional_not_calibration_qualification' and
                type(row['limitations']) is list and row['limitations'], 'applicability may not assert calibration')
    require(type(recipe['regions']) is list and 1 <= len(recipe['regions']) <= 32, 'bounded complete regional population required')
    seen = set()
    for region in recipe['regions']:
        keys(region, ('id', 'role', 'counts', 'ht', 'met_GeV'), 'region')
        require(type(region['id']) is str and region['id'] and region['id'] not in seen and
                region['role'] in ('signal', 'control', 'validation'), 'distinct region/role required')
        seen.add(region['id']); interval(region['met_GeV'])
        require(type(region['counts']) is dict and set(region['counts']) <= names, 'declared object counts only')
        for bounds in region['counts'].values():
            require(type(bounds) is list and len(bounds) == 2 and type(bounds[0]) is int and bounds[0] >= 0 and
                    (bounds[1] is None or type(bounds[1]) is int and bounds[1] >= bounds[0]), 'inclusive integer count bounds required')
        if region['ht'] is not None:
            keys(region['ht'], ('object', 'range_GeV'), 'HT')
            require(region['ht']['object'] in names, 'HT selected-object identity required'); interval(region['ht']['range_GeV'])
    if 'fitted_categories' in recipe:
        fitted = recipe['fitted_categories']
        keys(fitted, ('bins', 'source', 'semantics', 'independent_unit'), 'fitted categories')
        from ravel.physics.root_stream_core import pin
        pin(fitted['source'])
        require(fitted['semantics'] == 'source_declared_disjoint_independent_poisson' and
                fitted['independent_unit'] == 'source_entry_declared_independent_physical_event_group',
                'source-disjoint fitted law and independent physical group declaration required')
        require(type(fitted['bins']) is list and fitted['bins'] and
                all(type(b) is str for b in fitted['bins']) and
                len(set(fitted['bins'])) == len(fitted['bins']) and
                fitted['bins'] == [r['id'] for r in recipe['regions'] if r['role'] != 'validation'],
                'complete ordered original SR/CR fitted categories required; VR stays outside the fit')
    return deepcopy(recipe)


def required_branches(recipe):
    if type(recipe) is dict and recipe.get("schema_version") == 2:
        from ravel.physics import columnar_selection as s
        return s.required_branches(recipe)
    recipe = validate_recipe(recipe)
    branches = {'year', 'mcChannelNumber', 'weight_mc_NOSYS', 'met' + recipe['met'] + '_met_NOSYS', *recipe['scalar_scale_factors']}
    branches.update(b for values in recipe['trigger_by_year'].values() for b in values)
    for obj in recipe['objects']:
        prefix = obj['prefix']; branches.update((prefix + '_pt_NOSYS', prefix + '_eta'))
        if obj['selection'] != 'stored': branches.add(prefix + '_select_' + obj['selection'] + '_NOSYS')
        if recipe['overlap_removal'] != 'none':
            branches.add(prefix + '_select_passesOR' + ('LargeR' if recipe['overlap_removal'] == 'largeR' else '') + '_NOSYS')
        branches.update(obj['scale_factors'])
        if obj['tagger']: branches.update(b for b in obj['tagger'].values() if b is not None)
    return sorted(branches)


def branch_description(recipe, name):
    """(shape, unit) a schema-1 branch must carry: the supplied role, else the recipe's own consumption."""
    recipe = validate_recipe(recipe)
    role = descriptor_role(recipe.get('branch_roles'), name)
    if role is not None: return role[1:]
    met = 'met' + recipe['met'] + '_met_NOSYS'
    scalars = {'year', 'mcChannelNumber', 'weight_mc_NOSYS', met, *recipe['scalar_scale_factors']}
    scalars.update(b for values in recipe['trigger_by_year'].values() for b in values)
    return ('scalar' if name in scalars else 'jagged',
            'MeV' if name == met or name.endswith('_pt_NOSYS') else '1')


def bit_branches(recipe):
    """Every schema-1 branch the selection reads as a literal 0/1 flag."""
    recipe = validate_recipe(recipe)
    flags = set()
    for obj in recipe['objects']:
        prefix = obj['prefix']
        if obj['selection'] != 'stored': flags.add(prefix + '_select_' + obj['selection'] + '_NOSYS')
        if recipe['overlap_removal'] != 'none':
            flags.add(prefix + '_select_passesOR' + ('LargeR' if recipe['overlap_removal'] == 'largeR' else '') + '_NOSYS')
        if obj['tagger']: flags.update(obj['tagger'][k] for k in ('tagged', 'valid', 'mass') if obj['tagger'][k] is not None)
    return flags


def analysis_document(recipe, branches, original_goal, kernel):
    """One canonical quantity/weight mapping for producer and consumer."""
    recipe = validate_recipe(recipe)
    require(type(branches) is list and len({b['name'] for b in branches}) == len(branches) and
            {b['name'] for b in branches} == set(required_branches(recipe)),
            'exact complete source branch roster required')
    q = {'schema_version': 1, 'axes': [{'name': 'region_index', 'unit': '1'}],
         'bins': [{'id': r['id'], 'low': [i], 'high': [i+1]} for i,r in enumerate(recipe['regions'])],
         'weight_names': ['nominal'], 'input_weight_unit': '1', 'representation': 'integrated',
         'normalization': {'kind': 'absolute', 'scale': 1.0, 'unit': 'events'}}
    return {'schema_version': 1, 'original_goal': deepcopy(original_goal), 'branch_contract': deepcopy(branches),
        'weight_contract': {'raw_mc_weight': 'weight_mc_NOSYS',
            'scale_factors': deepcopy(recipe['scalar_scale_factors']), 'variations': [],
            'derived_factor': {'entry': 'kernel.py', 'source': deepcopy(kernel),
                               'semantics': 'source_declared_nominal_event_sf'}},
        'quantities': [{'id': 'regions', 'contract': q}], 'blinding': None}


def event_view(event, recipe):
    """Keep source indices; apply flags then cuts; stable descending pT sort."""
    if type(recipe) is dict and recipe.get("schema_version") == 2:
        from ravel.physics import columnar_selection as s
        checked, compiled = s.compiled_recipe(recipe)
        return s.event_view(event, checked, compiled)
    year = event['year']
    require(type(year) is int and str(year) in recipe['trigger_by_year'], 'source year has no declared trigger strategy')
    passed = any([bit(event[b]) for b in recipe['trigger_by_year'][str(year)]])
    selected = {}; factor = 1.0
    for obj in recipe['objects']:
        prefix = obj['prefix']; pts = event[prefix + '_pt_NOSYS']; etas = event[prefix + '_eta']
        fields = [prefix + '_pt_NOSYS', prefix + '_eta', *obj['scale_factors']]
        flags = []
        if obj['selection'] != 'stored': flags.append(prefix + '_select_' + obj['selection'] + '_NOSYS')
        if recipe['overlap_removal'] != 'none': flags.append(prefix + '_select_passesOR' + ('LargeR' if recipe['overlap_removal'] == 'largeR' else '') + '_NOSYS')
        fields.extend(flags)
        if obj['tagger']: fields.extend(b for b in obj['tagger'].values() if b is not None)
        require(type(pts) is list and all(type(event[b]) is list and len(event[b]) == len(pts) for b in fields), 'all selected-container vectors must be index-aligned')
        indices = []
        for i, pt in enumerate(pts):
            require(number(pt) >= 0, 'physical transverse momentum required'); eta = number(etas[i])
            valid = all([bit(event[b][i]) for b in flags])
            tag = obj['tagger']
            if tag is not None:
                tagged, in_range = bit(event[tag['tagged']][i]), bit(event[tag['valid']][i])
                mass_passed = True if tag['mass'] is None else bit(event[tag['mass']][i])
                score = None if tag['score'] is None else number(event[tag['score']][i])
                require(not (in_range and score == -666), 'valid tagger cannot carry did-not-run sentinel')
                valid = valid and tagged and in_range and mass_passed and score != -666
            if valid and pt / 1000.0 >= obj['pt_min_GeV'] and abs(eta) < obj['abs_eta_max']:
                indices.append(i)
        indices.sort(key=lambda i: -pts[i])
        selected[obj['name']] = {'indices': indices, 'pt_GeV': [number(pts[i] / 1000.0) for i in indices]}
        for i in indices:
            for sf in obj['scale_factors']:
                value = number(event[sf][i]); require(value >= 0, 'nonnegative declared SF required')
                factor = number(factor * value)
    met = number(event['met' + recipe['met'] + '_met_NOSYS'])
    require(met >= 0, 'nonnegative physical MET required')
    return {'trigger_passed': passed, 'objects': selected,
            'met_GeV': met / 1000.0,
            'object_factor': factor}


def records(events, entries, sample, recipe):
    require(len(events) == len(entries), 'all source events including rejected events required')
    answer = []
    for event, entry in zip(events, entries):
        require(type(event['mcChannelNumber']) is int and event['mcChannelNumber'] == sample['dsid'], 'event DSID differs from declared original sample')
        view = event_view(event, recipe); fills = []
        if view['trigger_passed']:
            for i, region in enumerate(recipe['regions']):
                ok = region['met_GeV'][0] <= view['met_GeV'] and (region['met_GeV'][1] is None or view['met_GeV'] < region['met_GeV'][1])
                for name, bounds in region['counts'].items():
                    count = len(view['objects'][name]['indices']); ok = ok and bounds[0] <= count and (bounds[1] is None or count <= bounds[1])
                if region['ht'] is not None:
                    ht = math.fsum(view['objects'][region['ht']['object']]['pt_GeV']); lo, hi = region['ht']['range_GeV']
                    ok = ok and lo <= ht and (hi is None or ht < hi)
                if ok: fills.append([i + .5])
        if 'fitted_categories' in recipe:
            fitted = set(recipe['fitted_categories']['bins'])
            matching = [recipe['regions'][int(fill[0])]['id'] for fill in fills
                        if recipe['regions'][int(fill[0])]['id'] in fitted]
            # This is an unweighted check: zero weights and underflow cannot
            # conceal an observed co-fill. It falsifies overlap on the processed
            # cohort, but never proves physical exclusivity over unobserved data.
            require(len(matching) <= 1, 'unweighted fitted-category co-fill refused')
        answer.append({'source_entry': int(entry), 'fills': {'regions': fills}})
    return answer


def kernel_bytes(recipe):
    if type(recipe) is dict and recipe.get("schema_version") == 2:
        from ravel.physics import columnar_selection as s
        checked, compiled = s.compiled_recipe(recipe)
        return s.kernel_bytes(checked, compiled)
    import json
    checked = validate_recipe(recipe)
    # The JSON representation is embedded as a literal, not executable source.
    encoded = json.dumps(checked, sort_keys=True, allow_nan=False)
    return ('import json\nfrom ravel.physics import columnar_ntuple_recipe as h\nRECIPE = h.validate_recipe(json.loads(' + repr(encoded) + '))\n'
            'def event_factors(table, entries, sample):\n'
            '    import awkward as ak\n'
            '    return [h.event_view(e, RECIPE)["object_factor"] for e in ak.to_list(table)]\n'
            'def analyze(table, entries, sample):\n'
            '    import awkward as ak\n'
            '    return h.records(ak.to_list(table), entries, sample, RECIPE)\n').encode()


def records_from_views(views, entries, recipe):
    """Same complete region/co-fill law for precomputed changed selections."""
    require(len(views) == len(entries), "complete source views/entries required")
    answer = []
    for view, entry in zip(views, entries):
        fills = []
        if view['trigger_passed']:
            for i, region in enumerate(recipe['regions']):
                ok = region['met_GeV'][0] <= view['met_GeV'] and (region['met_GeV'][1] is None or view['met_GeV'] < region['met_GeV'][1])
                for name, bounds in region['counts'].items():
                    count = len(view['objects'][name]['indices']); ok = ok and bounds[0] <= count and (bounds[1] is None or count <= bounds[1])
                if region['ht'] is not None:
                    ht = math.fsum(view['objects'][region['ht']['object']]['pt_GeV']); lo, hi = region['ht']['range_GeV']
                    ok = ok and lo <= ht and (hi is None or ht < hi)
                if ok: fills.append([i + .5])
        if 'fitted_categories' in recipe:
            fitted = set(recipe['fitted_categories']['bins'])
            matching = [recipe['regions'][int(fill[0])]['id'] for fill in fills
                        if recipe['regions'][int(fill[0])]['id'] in fitted]
            # This is an unweighted check: zero weights and underflow cannot
            # conceal an observed co-fill. It falsifies overlap on the processed
            # cohort, but never proves physical exclusivity over unobserved data.
            require(len(matching) <= 1, 'unweighted fitted-category co-fill refused')
        answer.append({'source_entry': int(entry), 'fills': {'regions': fills}})
    return answer
