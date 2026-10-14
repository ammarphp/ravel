"""Complete MC stream→source-typed expected SR/CR native construction.

Observed data are not prerequisites for nominal conditional forecasts. The
caller supplies the whole physical/auxiliary law, nuisance assumptions and
signal+background generating point. MC moments are retained, never converted
into invented Poisson counts or Gaussian constraints. No fit is launched here.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
from pathlib import Path
from ravel.physics import root_stream as stream, root_stream_core as c
from ravel.physics import native_statistical_construction as constructor
from ravel.physics import columnar_ntuple_recipe as h

SCOPE = 'mc_expected_source_construction'


def project(delivery, design):
    c.keys(design, ('schema_version', 'recipe', 'term_bindings', 'region_roles',
                   'validation_bins', 'mc_treatment', 'missing_validation', 'dependencies',
                   'native_component_treatment'), 'expected construction design')
    c.require(type(design['schema_version']) is int and design['schema_version'] == 1, 'expected design schema1 required')
    c.require(design['mc_treatment'] == 'conditional_on_supplied_MC_centrals_moments_retained_no_auxiliary_inferred',
              'an MC sampling/uncertainty law cannot be inferred from sumw/sumw2')
    c.require(type(design['missing_validation']) is list, 'data/physics validation obligations must remain explicit')
    c.require(design['native_component_treatment'] == 'additional_source_declared_means_require_fresh_joint_review',
              'native graph components are additional means, not an implicit replacement for MC terms')
    recipe = deepcopy(design['recipe'])
    c.require(type(recipe['cells']) is list and recipe['cells'], 'complete expected source cells required')
    roles = design['region_roles']; c.require(type(roles) is dict and roles, 'exact source region roster required')
    c.require(all(r in ('signal_region', 'control_region', 'validation_region') for r in roles.values()), 'source region roles required')
    c.require(type(design['validation_bins']) is list and len(set(design['validation_bins'])) == len(design['validation_bins']) and
              all(roles.get(x) == 'validation_region' for x in design['validation_bins']), 'held-out MC validation roster required')
    cells = {cell['id']: cell for cell in recipe['cells']}
    c.require(len(cells) == len(recipe['cells']), 'distinct original expected cells required')
    for cell in cells.values():
        expected = constructor.expected_request(cell)
        c.require(expected['conditioning'] == 'supplied_nominal' and all(b['observed'] is None for b in cell['law']['bins']),
                  'expected-only route preserves unobserved data; no zero or integer fabrication')
        poi = [p for p in cell['law']['parameters'] if p['role'] == 'poi']
        c.require(len(poi) == 1 and Fraction(expected['point'][poi[0]['name']]) > 0,
                  'discovery forecast must generate a declared nonzero signal strength')
        c.require(cell['fit']['method'] == 'MultiDimFit' and cell['fit']['data'] == 'source_asimov',
                  'nonzero signal Asimov profile is separate from background CLs')
        c.require(all(roles.get(b['id']) == b['role'] and b['role'] in ('signal_region', 'control_region')
                      for b in cell['law']['bins']), 'VR may not become a fitted SR/CR')
    bindings = design['term_bindings']; c.require(type(bindings) is list and bindings, 'complete source mean term bindings required')
    samples = {s['id']: s for s in delivery['samples']}; seen = set()
    for row in bindings:
        c.keys(row, ('cell', 'term', 'sample', 'quantity', 'bin_ids'), 'expected mean binding')
        c.require(row['cell'] in cells and (row['cell'], row['term']) not in seen, 'unique original mean term association required')
        seen.add((row['cell'], row['term'])); cell = cells[row['cell']]
        terms = [t for t in cell['law']['terms'] if t['id'] == row['term']]
        c.require(len(terms) == 1 and row['sample'] in samples, 'original mean term/sample required')
        term = terms[0]; sample = samples[row['sample']]
        c.require((term['basis'] == 'bsm' and sample['kind'] == 'signal_mc') or
                  (term['basis'] in ('sm', 'background') and sample['kind'] == 'background_mc'), 'MC signal/background basis differs')
        c.require('shape' not in term, 'bin-integrated MC means cannot be silently remorphed by an additional shape law')
        pars = {p['name']: p for p in cell['law']['parameters']}
        poi_name = next(p['name'] for p in pars.values() if p['role'] == 'poi')
        c.require((term['basis'] != 'bsm' or term['powers'].get(poi_name) == 1) and
                  (term['basis'] == 'bsm' or poi_name not in term['powers']), 'explicit linear signal strength and POI-independent background required')
        c.require(all(name == poi_name or Fraction(pars[name]['initial']) == 1
                      for name in term['powers']), 'MC means require unit nominal non-POI multiplicative coordinates')
        observed = cell['law']['auxiliary']['observed']
        c.require(all(sum((Fraction(a)*Fraction(b) for a,b in zip(response, observed)), Fraction()) == 0
                      for response in term['log_response']), 'MC coefficient is a nominal mean; nonzero auxiliary offsets need explicit transport')
        c.require(row['quantity'] in sample['quantities'], 'actual complete quantity required')
        q = sample['quantities'][row['quantity']]; bins = [b['id'] for b in q['contract']['bins']]
        c.require(q['contract']['representation'] == 'integrated' and q['contract']['normalization']['unit'] == 'events' and
                  q['contract']['weight_names'] == ['nominal'], 'actual nominal expected event integrals required')
        c.require(type(row['bin_ids']) is list and len(row['bin_ids']) == len(cell['law']['bins']) and
                  len(set(row['bin_ids'])) == len(row['bin_ids']) and set(row['bin_ids']) <= set(bins), 'all SR/CR means including control-region signal required')
        c.require(all(source == target['id'] and roles[source] == target['role']
                      for source, target in zip(row['bin_ids'], cell['law']['bins'])), 'literal source bin identity/role cannot be relabelled')
        # Fraction preserves each emitted binary64 central exactly. Negative
        # weighted contributions stay signed; the existing source constructor
        # must admit or refuse the complete resulting mean/domain law.
        term['coefficients'] = [str(Fraction(q['values']['nominal'][bins.index(b)])) for b in row['bin_ids']]
        term['source'] = 'mc_stream_delivery'
    c.require(seen == {(cell['id'], t['id']) for cell in cells.values() for t in cell['law']['terms']},
              'every original mean contribution requires an explicit complete mapping')
    return recipe


def dependency_pins(recipe):
    """Declared whole constructor dependencies, without authenticating old votes.

    Exact constructor.inputs performs the stronger complete review admission
    after the projected subject obtains new critic/verifier receipts.
    """
    capsule = recipe['source_capsule']; root = Path(capsule['root'])
    c.require(root.is_absolute(), 'absolute original source root required')
    facts = [{'path': str(root / row['path']), 'sha256': row['sha256']} for row in capsule['files']]
    for cell in recipe['cells']: facts.extend(cell['law']['sources'])
    runtime = recipe['runtime']; transport = runtime['transport']
    facts += (list(runtime['tools'].values()) + runtime['artifacts'] if transport['kind'] == 'local'
              else [transport[k] for k in ('executable', 'image_archive', 'image_manifest')])
    facts.append(runtime['version_proof']['source'])
    review = recipe['review']; c.require(Path(review['root']).is_absolute(), 'absolute prior review root required')
    facts.append(review['subject'])
    facts += [{**r, 'path': str(Path(review['root']) / r['path'])} for r in review['files']]
    pins = {}
    for fact in facts:
        path = Path(fact['path']); c.require(path.is_absolute() and '..' not in path.parts, 'absolute literal original dependency required')
        if path in pins: c.require(pins[path] == fact['sha256'], 'one path cannot bind different source bytes')
        pins[path] = fact['sha256']
    return pins


def validate(task):
    c.keys(task, ('request',), 'expected construction task'); c.pin(task['request']); return task


def fitted_kernel(recipe, config, design, cap, base, analysis):
    """Bind the actual executed kernel, not only a disjointness annotation."""
    recipe = h.validate_recipe(recipe)
    c.require('fitted_categories' in recipe, 'independent Poisson handoff requires guarded fitted categories')
    fitted = recipe['fitted_categories']
    if recipe['schema_version'] == 1: cap.read(fitted['source'], base)
    expected = fitted['bins']
    roles = {'signal': 'signal_region', 'control': 'control_region', 'validation': 'validation_region'}
    c.require(design['region_roles'] == {r['id']: roles[r['role']] for r in recipe['regions']},
              'all original selection region identities and roles must survive the handoff')
    for cell in design['recipe']['cells']:
        c.require([b['id'] for b in cell['law']['bins']] == expected,
                  'every fitted cell must retain the exact guarded SR/CR roster/order')
    bundle = config['bundle']
    if recipe['schema_version'] == 2:
        from ravel.physics import columnar_selection as selection
        recipe, _ = selection.verify_bundle(recipe, config, base, cap)
    else:
        c.require(bundle['entry'] == 'kernel.py' and bundle['blind_entry'] is None and
                  set(bundle['files']) == {'kernel.py'}, 'exact unblinded kernel bundle required')
        _, raw = cap.read(bundle['files']['kernel.py'], base)
        c.require(raw == h.kernel_bytes(recipe), 'executed kernel must contain the exact unweighted co-fill guard')
    c.require(analysis == h.analysis_document(recipe, analysis['branch_contract'],
              analysis['original_goal'], bundle['files']['kernel.py']),
              'executed original analysis must retain canonical nominal factors and complete region geometry')
    return fitted


def _load(task, base):
    validate(task); cap = c.Capture(); path, raw = cap.read(task['request'], base); d = c.strict(raw)
    c.keys(d, ('schema_version', 'stream_task', 'stream_result', 'stream_closure', 'design', 'goal_binding', 'original_goal'), 'MC expected handoff request')
    c.require(type(d['schema_version']) is int and d['schema_version'] == 1, 'handoff schema1 required')
    original_task = cap.document(d['stream_task'], path.parent)
    _, original_config, ds, analysis = stream._load(original_task, path.parent, cap)
    goal_path, _ = cap.read(d['original_goal'], path.parent)
    expected_goal_path, _ = cap.read(analysis['original_goal'], path.parent)
    c.require(goal_path == expected_goal_path and d['original_goal']['sha256'] == analysis['original_goal']['sha256'] and
              type(d['goal_binding']) is dict, 'whole original physics question must survive the statistical handoff')
    result_path, raw = cap.read(d['stream_result'], path.parent, max(8*1024**2, d['stream_result']['size']))
    c.require(result_path.name == 'root-stream-result.json', 'original whole stream result required')
    value = c.strict(raw); result = {**value, 'commitment': d['stream_closure']}; guard = stream.guard(result, result_path.parent)
    receipt = stream.ordinary_stream_delivery(result, result_path.parent, original_task)
    from ravel.workflow import science
    origin_paths = science.review_waypoint_paths(Path(receipt['rundir']))
    c.require(value['status'] == 'passed', 'failed/partial stream cannot become an expected template')
    native, original = stream.private_delivery(guard)
    c.require(original['dataset'] == ds and original['analysis'] == analysis and
              value['delivery'] == stream.public_delivery(native, ds, analysis), 'whole original source/data projection differs')
    c.require(all(s['kind'] != 'data' for s in ds['samples']), 'MC-only expected route never exposes restricted observed data')
    design = cap.document(d['design'], path.parent); recipe = project(native['delivery'], design)
    selection = cap.document(original_config['bundle']['review_source'], path.parent)
    fitted = fitted_kernel(selection, original_config, design, cap, path.parent, analysis)
    cap.expected_fitted_categories = deepcopy(fitted)
    dependencies = design['dependencies']; c.require(type(dependencies) is list and dependencies, 'whole prospective constructor dependency pins required')
    declared = {}
    for fact in dependencies:
        c.pin(fact); p, _ = cap.read(fact, path.parent, min(fact['size'], 64*1024**2))
        c.require(p not in declared, 'duplicate dependency declaration')
        declared[p] = fact['sha256']
    c.require(declared == dependency_pins(design['recipe']), 'missing/extra or relabelled whole constructor dependencies')
    # Source additions identify actual output/design, never a new statistical
    # law. All declared nuisance/auxiliary/source state remains unchanged.
    for cell in recipe['cells']:
        ids = {s['id'] for s in cell['law']['sources']}
        c.require(not ids & {'mc_stream_delivery', 'mc_expected_design'}, 'reserved exact source IDs collide')
        for key, declaration in (('mc_stream_delivery', d['stream_result']), ('mc_expected_design', d['design'])):
            p, _ = cap.read(declaration, path.parent, max(8*1024**2, declaration['size']))
            cell['law']['sources'].append({'id': key, 'path': str(p), 'sha256': declaration['sha256']})
    constructor.validate_document(recipe)
    # A changed mean changes subject(recipe). Old source review bytes are
    # retained as lineage only, never used to authenticate the new subject.
    cap.expected_origin_paths = [Path(p) for p in origin_paths]
    cap.expected_origin_paths.extend(result_path.parent / 'native' / name for name, fact in guard.native_outputs.items()
                                 if fact.get('kind') == 'file')
    closure_path, _ = cap.read(d['stream_closure'], result_path.parent)
    cap.expected_origin_paths.append(closure_path)
    cap.finish(); guard.finish(result)
    return path, d, design, recipe, value, result, guard, receipt, original_task, result_path, analysis, cap


def inputs(task, base):
    *_, cap = _load(task, base); cap.finish(); return sorted({*cap.rows, *cap.expected_origin_paths})


def execution_seconds(task, base):
    _load(task, base); return 60


def goal_inputs(spec, base):
    _, d, *_, cap = _load(spec['task'], base)
    c.require(spec.get('schema_version') == 2 and spec.get('goal_binding') == d['goal_binding'], 'expected stage must retain declared original goal binding')
    cap.finish()


def validate_scope(spec):
    p = spec.get('review_policy', {}).get('policy', {})
    c.require(spec.get('schema_version') == 2 and spec.get('max_attempts') == 1 and p.get('max_redos') == 0 and
              set(p.get('claim_scopes', {})) == {SCOPE} and p['claim_scopes'][SCOPE].get('actions') == ['delivery'], 'expected source preparation only')
    return spec


def run(task, base, output):
    out = Path(output).absolute()
    from ravel.workflow import science
    owner = next((rd for rd in (out, *out.parents) if (rd / science.PLAN).is_file()), None)
    c.require(owner is not None, 'ordinary approved expected-preparation worker required')
    plan = science.verify_worker(owner); spec = science.execution_spec(owner); validate_scope(spec)
    c.require(spec['mode'] == 'mc-expected-construction' and spec['task'] == task and
              out == (owner / plan['output_directory'] / 'mc-expected-construction').absolute(), 'actual expected-preparation destination differs')
    path, d, design, recipe, value, result, guard, receipt, original_task, result_path, analysis, cap = _load(task, base)
    c.require(not out.exists() and '..' not in out.parts and not any(p.is_symlink() for p in (out, *out.parents)), 'fresh expected construction required')
    c.require(not any(out == p or out.is_relative_to(p.parent) for p in cap.rows), 'output must not contaminate original scientific directories')
    c.require(not any(out.is_relative_to(p.parent) for p in cap.expected_origin_paths), 'output must be disjoint from original delivery evidence')
    out.mkdir(parents=True); emitted = []
    declaration = stream.write_new(out / 'expected-source-recipe.json', recipe); emitted.append(declaration)
    subject_value = {k:v for k,v in recipe.items() if k != 'review'}
    subject = stream.write_new(out / 'fresh-review-subject.json', subject_value); emitted.append(subject)
    c.require(subject['sha256'] == hashlib.sha256(constructor.subject(recipe)).hexdigest(), 'exact prospective source subject differs')
    next_action = {'mode': 'native-statistical-construction', 'task': {'input': declaration['path']},
        'goal_binding': d['goal_binding'],
        'subject': subject, 'required_roles': ['critic', 'verifier'],
        'existing_review_is_lineage_only': True, 'ready_to_plan': False,
        'missing': ['Fresh exact-subject Graph critic/verifier source review; replace recipe.review with its complete receipts.',
                    'Ordinary constructor inputs and planning must then authenticate all source/runtime/subject dependencies.',
                    'Fresh ordinary approval is required for each later native Asimov/profile job.']}
    emitted.append(stream.write_new(out / 'next-research-action.json', next_action))
    evidence = {'schema_version': 1, 'kind': 'mc-expected-construction', 'status': 'passed', 'status_scope': SCOPE,
        'recipe': declaration, 'next_ordinary_action': next_action, 'original_stream_result': d['stream_result'],
        'all_moments_retained': value['delivery']['samples'], 'mc_validation_bins': design['validation_bins'],
        'fitted_category_guard': cap.expected_fitted_categories,
        'mc_validation_computed': False, 'missing_data_validation': design['missing_validation'],
        'original_goal': analysis['original_goal'], 'fits': 0, 'native_calls': 0, 'sensitivity_computed': False,
        'original_task_complete': False, 'execution_authorized': False, 'physics_validated': False,
        'limitations': ['Expected signal+background Asimov generation/profile inputs only; actual q0/profile diagnostics and matched comparison with earlier results remain future.',
            'No observed CR/VR/SR data, CP variations or MC auxiliary sampling laws are invented.',
            'All signed MC means and moments stay literal. Structural constructor validation is not numerical/global mean-domain qualification.',
            'Changed MC coefficients need a fresh whole-source statistical judgment; old review receipts confer no derivative authority.',
            'The executed unweighted co-fill guard falsifies observed overlap, not physical exclusivity on unobserved support. Independent source-entry/group and Poisson laws remain source-review obligations.',
            'Held-out MC validation is distinct from unavailable data-dependent background closure.']}
    emitted.append(stream.write_new(out / 'mc-expected-construction-preparation.json', evidence))
    cap.finish(); guard.finish(result)
    c.require(stream.ordinary_stream_delivery(result, result_path.parent, original_task) == receipt,
              'ending original actual stream receipt differs')
    stream.custody.asset_check({p['path']: p for p in emitted})
    return evidence


def write_report(result, out):
    stream.write_new(Path(out) / 'mc-expected-construction-report.json', result)
    return [{'stem': 'mc-expected-construction-report', 'files': ['mc-expected-construction-report.json'],
             'scope': 'MC-only expected source preparation; new review/profile/validation and sensitivity remain pending.'}]
