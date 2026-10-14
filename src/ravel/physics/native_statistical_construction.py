"""Reviewed original RooFit graphs -> complete ordinary native fit bundles.

Preparation transports scientific input; it does not prove a native integral,
factory, template morph, fit, or calibration numerically equivalent to its source.
No native import, compiler, optimizer, model call, or subprocess runs here.
"""
from __future__ import annotations

import ast
import copy
from fractions import Fraction
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import tempfile

from ravel import analysis_sources
from ravel.physics import statistical_construction as regional
from ravel.workflow.state_io import atomic_json, read_json

KIND = 'native-source-graph/v1'
CARD = 'source/ravel_graph_model.txt'
AXES = ('mass', 'width', 'hypothesis', 'candidate')
SHA = re.compile(r'[a-f0-9]{64}')
ID = re.compile(r'[A-Za-z][A-Za-z0-9_]*')


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact ' + label + ' fields required')


def _id(value):
    if type(value) is not str or not ID.fullmatch(value) or value in {'MH','ModelConfig','ModelConfig_bonly','model_s','model_b','data_obs','w'} or value.startswith(('ravel_','CMS_','n_exp_','n_obs_')):
        raise ValueError('owned, nonreserved identifier required')
    return value


def _native_float(value, label):
    """Preserve source zero/sign; refuse erased or nonfinite native scalars."""
    try:
        native = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(label + ' has no finite native representation') from exc
    if not math.isfinite(native) or value != 0 and native == 0:
        raise ValueError(label + ' requires a finite nonzero native representation')
    return native


def _interval(values):
    if type(values) is not list or len(values) != 2:
        raise ValueError('complete interval endpoints required')
    lo, hi = map(_q, values)
    native_lo, native_hi = float(lo), float(hi)
    native_width = native_hi - native_lo
    if not lo < hi or not native_lo < native_hi or not math.isfinite(native_width):
        raise ValueError('finite distinct interval endpoints required')
    _native_float(hi-lo, 'source interval width')
    return lo, hi


def _template_native_geometry(template):
    """Checked native edges/heights, with source integrals left unchanged."""
    edges = [float(_q(v)) for v in template['edges']]
    heights = []
    for a, b, value in zip(template['edges'], template['edges'][1:], template['values']):
        lo, hi = _interval([a,b]); integral = _q(value)
        height = _native_float(integral/(hi-lo), 'source template density height')
        represented = height * (float(hi)-float(lo))
        if not math.isfinite(represented) or integral != 0 and represented == 0:
            raise ValueError('native template geometry erases or overflows a source bin integral')
        heights.append(height)
    return edges, heights


def _text(value):
    if type(value) is not str or not value.strip() or '\x00' in value:
        raise ValueError('explicit source statement required')


def _q(value):
    return regional._q(value)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def subject(document):
    """The full recipe, including every cell and runtime, before review receipts."""
    return encoded({k: v for k, v in document.items() if k != 'review'})


def _dag(rows, roots, *, label):
    names = {row['id']: row for row in rows}
    if len(names) != len(rows):
        raise ValueError('duplicate ' + label)
    visiting, used, order = set(), set(), []
    def visit(name):
        if name in visiting or name not in names or len(visiting) >= 128:
            raise ValueError('cyclic/missing ' + label)
        if name in used:
            return
        visiting.add(name)
        deps = names[name]['depends_on']
        if type(deps) is not list or len(set(deps)) != len(deps):
            raise ValueError('unique explicit dependencies required')
        for dep in deps:
            visit(dep)
        visiting.remove(name); used.add(name); order.append(name)
    for root in roots:
        visit(root)
    if used != set(names):
        raise ValueError('unused ' + label)
    return order


def validate_document(document):
    _keys(document, {'schema_version', 'kind', 'question', 'scope', 'population', 'cells',
                     'source_capsule', 'members', 'review', 'runtime', 'max_seconds', 'assumptions'}, 'native constructor')
    if type(document['schema_version']) is not int or document['schema_version'] not in (1, 2) or document['kind'] != KIND:
        raise ValueError('native source graph schema 1 or 2 required')
    if len(encoded(document)) > 8 * 1024**2:
        raise ValueError('bounded 8 MiB recipe required')
    _text(document['question']); _text(document['scope'])
    if type(document['assumptions']) is not list or not document['assumptions']:
        raise ValueError('explicit source assumptions required')
    for value in document['assumptions']: _text(value)
    if type(document['max_seconds']) is not int or not 1 <= document['max_seconds'] <= 86400:
        raise ValueError('bounded original execution budget required')
    capsule = analysis_sources.validate_capsule(document['source_capsule'])
    if capsule['framework'] != 'cpp' or not capsule['dependency_review']['complete']:
        raise ValueError('complete original C++ source/dependency capsule required')
    paths = {r['path'] for r in capsule['files']}
    if 'ravel_graph_model.txt' in paths:
        raise ValueError('original source file collides with generated native card')
    members = document['members']
    if type(members) is not list or not 1 <= len(members) <= 2048:
        raise ValueError('bounded original function/class/member census required')
    for row in members:
        _keys(row, {'id', 'path', 'first_line', 'last_line', 'sha256', 'depends_on'}, 'source member')
        _id(row['id'])
        if row['path'] not in paths or type(row['first_line']) is not int or type(row['last_line']) is not int or not 1 <= row['first_line'] <= row['last_line'] or not SHA.fullmatch(str(row['sha256'])):
            raise ValueError('bound exact whole-source member span required')
    if len({r['id'] for r in members}) != len(members):
        raise ValueError('duplicate original member')
    _keys(document['population'], AXES, 'Cartesian population')
    for axis in AXES:
        values = document['population'][axis]
        if type(values) is not list or not values or len(values) != len(set(values)) or any(type(v) is not str or not v.strip() for v in values):
            raise ValueError('ordered literal source-declared axes required, including explicit singleton axes')
    if math.prod(len(document['population'][a]) for a in AXES) > 512:
        raise ValueError('bounded complete population required; never truncate a Cartesian product')
    expected = list(itertools.product(*(document['population'][a] for a in AXES)))
    cells = document['cells']
    if type(cells) is not list or not 1 <= len(cells) <= 512 or len(cells) != len(expected):
        raise ValueError('every original Cartesian cell requires an actual construction')
    identities, member_roots = set(), []
    for position, cell in enumerate(cells):
        _keys(cell, {'id', 'coordinates', 'law', 'parameters', 'observables', 'nodes', 'components', 'integration', 'fit'} | ({'expected_data'} if 'expected_data' in cell else set()) | ({'derivatives'} if 'derivatives' in cell else set()) | ({'calibration'} if 'calibration' in cell else set()) | ({'discovery_diagnostic'} if 'discovery_diagnostic' in cell else set()), 'cell')
        _id(cell['id']); _keys(cell['coordinates'], AXES, 'cell coordinates')
        if cell['id'] in identities or tuple(cell['coordinates'][a] for a in AXES) != expected[position]:
            raise ValueError('duplicate/reordered/omitted original cell')
        identities.add(cell['id'])
        law = regional.validate(_scaffold_law(cell))
        if type(cell['fit']) is not dict or 'expected_data' in cell['law'] or cell['fit'].get('method') != 'MultiDimFit' or cell['fit'].get('data') != ('source_asimov' if 'expected_data' in cell else 'observed'):
            raise ValueError('source graph requires explicit observed or source_asimov MultiDimFit; generic CLs is not admitted')
        poi = next(p for p in law['parameters'] if p['role'] == 'poi')
        if cell['fit'].get('poi') != poi['name'] or cell['fit'].get('domain') != poi['bounds']:
            raise ValueError('full source POI domain must be preserved')
        _keys(cell['integration'], {'eps_abs', 'eps_rel', 'max_steps', 'policy'} | ({'max_eval_2d','max_eval_3d','max_eval_nd','max_warn','max_template_cells'} if document['schema_version']==2 else set()), 'native integral settings')
        if cell['integration']['policy'] != ('ROOT6.22-joint-original-source-relative-policy' if document['schema_version']==2 else 'ROOT6.22-RooIntegrator1D-original-default-zero-policy') or type(cell['integration']['max_steps']) is not int or not 8 <= cell['integration']['max_steps'] <= 20:
            raise ValueError('supported bounded ROOT6.22 integrator policy required')
        for name in ('eps_abs', 'eps_rel'):
            if not Fraction('1e-12') <= _q(cell['integration'][name]) <= Fraction('1e-4'):
                raise ValueError('explicit integration settings outside supported envelope')
        if document['schema_version']==2:
            for key in ('max_eval_2d','max_eval_3d','max_eval_nd'):
                if type(cell['integration'][key]) is not int or not 1 <= cell['integration'][key] <= 10000000: raise ValueError('bounded explicit native evaluation cap required')
            if type(cell['integration']['max_warn']) is not int or not 1 <= cell['integration']['max_warn'] <= 1000 or type(cell['integration']['max_template_cells']) is not int or not 1 <= cell['integration']['max_template_cells'] <= 65536: raise ValueError('finite explicit diagnostic/template resources required')
        owned = {p['name'] for p in law['parameters']}
        owned.update('ravel_aux_' + str(i) for i in range(len(law['auxiliary']['names'])))
        extras = cell['parameters']
        if type(extras) is not list or len(extras) > 128:
            raise ValueError('bounded graph coordinate population required')
        extra_names = set()
        for p in extras:
            _keys(p, {'name', 'initial', 'bounds', 'fixed', 'unit', 'member'}, 'graph parameter')
            _id(p['name']); regional._bounds(p['bounds'], p['initial']); _text(p['unit'])
            if type(p['fixed']) is not bool or p['name'] in owned:
                raise ValueError('graph parameter ownership collision')
            owned.add(p['name']); extra_names.add(p['name']); member_roots.append(p['member'])
        point_coordinates = set(owned)
        observables = cell['observables']
        if type(observables) is not list or not 1 <= len(observables) <= 32:
            raise ValueError('complete integration variable/domain/unit population required')
        obs = {}
        for o in observables:
            _keys(o, {'name', 'bounds', 'unit', 'member'}, 'integration observable')
            _id(o['name']); lo,hi = _interval(o['bounds']); _text(o['unit'])
            _native_float((lo+hi)/2, 'integration observable midpoint')
            if o['name'] in owned: raise ValueError('observable/coordinate ownership collision')
            obs[o['name']] = o; owned.add(o['name']); member_roots.append(o['member'])
        nodes = cell['nodes']
        if type(nodes) is not list or not 1 <= len(nodes) <= 512:
            raise ValueError('bounded complete original native object graph required')
        node_names = set(); graph_rows = []; used_coordinates = set()
        for node in nodes:
            kind = node.get('kind') if type(node) is dict else None
            _keys(node, {'name', 'kind', 'depends_on', 'members', 'class'} | ({'factory'} if kind == 'factory' else {'template'} if kind == 'template' else set()), 'native node')
            if kind not in ('factory', 'template'): raise ValueError('reviewed factory or closed original histogram template required')
            _id(node['name'])
            if type(node['class']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:::[A-Za-z][A-Za-z0-9_]*)*',node['class']):
                raise ValueError('exact original native class identity required')
            if node['name'] in owned or node['name'] in node_names:
                raise ValueError('native node ownership collision')
            node_names.add(node['name'])
            if type(node['members']) is not list or not node['members']: raise ValueError('original factory/member mapping required')
            member_roots += node['members']
            if type(node['depends_on']) is not list or len(set(node['depends_on'])) != len(node['depends_on']):
                raise ValueError('unique original native server mapping required')
            used_coordinates.update(set(node['depends_on']) & owned)
            if kind == 'factory':
                literal = node['factory']; _text(literal)
                if len(literal) > 20000 or not re.match(r'(?:[A-Za-z][A-Za-z0-9_]*::)+' + re.escape(node['name']) + r'\(', literal) or not literal.endswith(')') or '\n' in literal:
                    raise ValueError('exact reviewed single RooFactory member mapping required')
            else:
                t = node['template']
                if document['schema_version']==2:
                    _validate_joint_template(t, node, obs, paths, cell['integration']['max_template_cells'])
                else:
                    _keys(t, {'source_path', 'observable', 'edges', 'values', 'semantics'}, 'template')
                    if node['class'] != 'RooHistFunc' or t['source_path'] not in paths or t['observable'] not in obs or node['depends_on'] != [t['observable']] or t['semantics'] != 'absolute_bin_integrals_piecewise_constant':
                        raise ValueError('complete original template source/measure required')
                    edges, values = t['edges'], t['values']
                    if type(edges) is not list or type(values) is not list or not 1 <= len(values) <= 2048 or len(edges) != len(values) + 1 or any(_q(a) >= _q(b) for a, b in zip(edges, edges[1:])):
                        raise ValueError('complete finite ordered template bins required')
                    if [edges[0], edges[-1]] != obs[t['observable']]['bounds']:
                        raise ValueError('template must cover the full declared observable domain')
                    for value in values: _q(value)
                    _template_native_geometry(t)
        for node in nodes:
            if set(node['depends_on']) - owned - node_names: raise ValueError('missing native node/coordinate dependency')
            graph_rows.append({'id': node['name'], 'depends_on': [x for x in node['depends_on'] if x in node_names]})
        components = cell['components']
        if type(components) is not list or not 1 <= len(components) <= 128:
            raise ValueError('complete nonempty native contribution population required')
        component_ids = set()
        for t in components:
            _keys(t, {'id', 'node', 'normalization', 'measure', 'role', 'bin_windows', 'coefficients', 'powers', 'log_response', 'meaning'} | ({'observables'} if document['schema_version']==2 else {'observable'}), 'native contribution')
            _id(t['id']); _text(t['meaning'])
            tuple_names = _component_observables(t)
            if t['id'] in component_ids or t['node'] not in node_names or not tuple_names or len(tuple_names)!=len(set(tuple_names)) or any(name not in obs for name in tuple_names):
                raise ValueError('duplicate contribution or missing original shape')
            component_ids.add(t['id'])
            if t['normalization'] not in ('full_domain', 'absolute_integral') or t['measure'] not in ('density', 'signed_density') or t['role'] not in ('signal', 'background', 'interference'):
                raise ValueError('explicit density/yield or signed absolute measure required')
            if (t['role'] == 'interference' or t['measure'] == 'signed_density') and t['normalization'] != 'absolute_integral':
                raise ValueError('signed interference must remain an absolute contribution to TOTAL means')
            if len(t['bin_windows']) != len(law['bins']) or len(t['coefficients']) != len(law['bins']) or len(t['log_response']) != len(law['bins']):
                raise ValueError('every SR/CR/auxiliary bin requires an explicit contribution window/transfer')
            for index, (bounds, value, logrow) in enumerate(zip(t['bin_windows'], t['coefficients'], t['log_response'])):
                rectangle = _component_rectangle(t,bounds)
                for name in tuple_names:
                    lo,hi=map(_q,obs[name]['bounds']); a,b=_interval(rectangle[name])
                    if not lo <= a < b <= hi: raise ValueError('complete joint bin integral outside original full domain')
                if t['measure'] == 'density' and _q(value) < 0: raise ValueError('positive density requires nonnegative yield/transfer')
                _q(value)
                if law['bins'][index]['role']=='mc_auxiliary' and _q(value)!=0:
                    raise ValueError('source graph contribution cannot replace the original exposure times latent MC count law')
                if type(logrow) is not list or len(logrow) != len(law['auxiliary']['names']): raise ValueError('single common auxiliary response law required')
                for v in logrow: _q(v)
            if type(t['powers']) is not dict or set(t['powers']) - point_coordinates or any(type(v) is not int or not 0 <= v <= 8 for v in t['powers'].values()):
                raise ValueError('bound physical/whitened coordinate powers required')
            used_coordinates.update(t['powers'])
        _dag(graph_rows, [t['node'] for t in components], label='native graph node')
        for t in components:
            names=set(_component_observables(t)); pending=[t['node']]; seen=set(); actual=set()
            while pending:
                name=pending.pop()
                if name in seen: continue
                seen.add(name)
                for dep in next(n for n in nodes if n['name']==name)['depends_on']:
                    if dep in obs: actual.add(dep)
                    elif dep in node_names: pending.append(dep)
            if names!=actual: raise ValueError('complete original integration-observable dependency census required')
            if document['schema_version']==2:
                # Native hybrid partition is rechecked before numerical evaluation; all possible residual dimensions must fit this admitted backend/cap.
                for dim in range(2,min(len(names),15)+1):
                    key='max_eval_2d' if dim==2 else 'max_eval_3d' if dim==3 else 'max_eval_nd'
                    if cell['integration'][key]<2**dim+2*dim*(dim+1)+1: raise ValueError('declared native evaluation cap below actual rule minimum')
        if 'expected_data' in cell: expected_request(cell)
        if 'discovery_diagnostic' in cell:
            from ravel.physics import discovery_heldout, regional_expected
            discovery_heldout.validate(cell['discovery_diagnostic'],cell,regional_expected.PROFILE_POLICY)
        if 'calibration' in cell:
            from ravel.physics import source_graph_calibration as graph_calibration
            if 'derivatives' in cell or 'expected_data' in cell or 'saved_fit' not in cell['fit']:
                raise ValueError('graph full auxiliary calibration requires its distinct observed saved-fit route')
            native_law=copy.deepcopy(law)
            native_law['parameters'] += [dict(name=p['name'],role='coefficient',initial=p['initial'],bounds=p['bounds'],fixed=p['fixed'],meaning='Original graph coordinate',source=law['sources'][0]['id']) for p in cell['parameters']]
            graph_calibration.validate(cell['calibration'],{'kind':KIND,'recipe':document,'cell':cell['id'],'document':native_law,'coordinates':[p['name']for p in law['parameters']]+['ravel_aux_'+str(i)for i in range(len(law['auxiliary']['names']))]+[p['name']for p in cell['parameters']]})
        if 'derivatives' in cell:
            from ravel.physics.combine_derivatives import validate_selection
            validate_selection(cell['derivatives'])
            fit = cell['fit']
            if ('saved_fit' in fit or fit.get('points') is not None or fit.get('minimizer') is not None
                or fit.get('reference_quantiles') is not None or fit.get('fixed_witness_points') != []):
                raise ValueError('source graph diagnostics use the existing fixed NLL, without grid/fit/reference or extra witnesses')
            declared = {p['name']:p for p in [*law['parameters'], *cell['parameters']]}
            for i, bounds in enumerate(law['auxiliary']['eta_bounds']):
                declared['ravel_aux_'+str(i)] = {'fixed':False,'initial':'0','bounds':bounds}
            for name, value in cell['derivatives']['anchor'].items():
                p = declared.get(name)
                if p is None or p['fixed'] or not _q(p['bounds'][0]) <= Fraction.from_float(float(value)) <= _q(p['bounds'][1]):
                    raise ValueError('diagnostic anchor changes undeclared/fixed/out-of-domain source coordinate')
            for axis in cell['derivatives']['axes']:
                p = declared.get(axis['name'])
                if p is None or p['fixed']:
                    raise ValueError('diagnostic axis must be an original floating graph coordinate')
        if extra_names - used_coordinates or set(obs) - used_coordinates:
            raise ValueError('unused extra parameter/integration observable')
    _dag(members, member_roots, label='source member')
    return copy.deepcopy(document)


def _pin(value, base, session=None):
    from ravel.workflow.science import regular
    _keys(value, {'path', 'sha256'}, 'source pin')
    if not SHA.fullmatch(str(value['sha256'])): raise ValueError('exact source digest required')
    p = regular(value['path'], base, _session=session)
    before = session.observe(p) if session is not None else None
    raw = p.read_bytes()
    if session is not None and (session.observe(p) != before or session.hash_file(p) != hashlib.sha256(raw).hexdigest()):
        raise ValueError('source changed while consuming authenticated bytes')
    if hashlib.sha256(raw).hexdigest() != value['sha256']: raise ValueError('source pin changed')
    return p, raw


def source_inputs(document, base, *, _session=None):
    """Authenticate complete source, template buffers, and existing Graph reviews."""
    from ravel.workflow import agent_graph
    from ravel.workflow.science import regular
    d = validate_document(document); capsule = d['source_capsule']
    root = Path(base) / capsule['root']
    files, raw_by_path = [], {}
    for fact in capsule['files']:
        p, raw = _pin({'path': str(root / fact['path']), 'sha256': fact['sha256']}, base, _session)
        files.append(p); raw_by_path[fact['path']] = raw
    for row in d['members']:
        lines = raw_by_path[row['path']].splitlines(keepends=True)
        if row['last_line'] > len(lines) or hashlib.sha256(b''.join(lines[row['first_line']-1:row['last_line']])).hexdigest() != row['sha256']:
            raise ValueError('original member span changed')
    for cell in d['cells']:
        files += regional.source_inputs(_scaffold_law(cell), base, _session=_session)
        for node in cell['nodes']:
            if node['kind'] == 'template':
                t = node['template']; raw = raw_by_path[t['source_path']]
                if raw != encoded({k:t[k] for k in (('axes','values','semantics') if 'axes' in t else ('edges','values','semantics'))}):
                    raise ValueError('consumed template differs from authenticated complete source buffer')
    review = d['review']
    _keys(review, {'root', 'files', 'subject', 'critic', 'verifier'}, 'existing source review')
    subject_path, raw = _pin(review['subject'], base, _session)
    if raw != subject(d): raise ValueError('Graph review subject omits/changes recipe, runtime or cell population')
    files.append(subject_path)
    graph_root = Path(base) / review['root']
    if not graph_root.is_dir() or any(p.is_symlink() for p in (graph_root, *graph_root.parents)):
        raise ValueError('existing nonsymlink Graph root required')
    declared = set()
    if type(review['files']) is not list or not review['files'] or len(review['files']) > 4096:
        raise ValueError('complete existing review dependency inventory required')
    for fact in review['files']:
        _keys(fact, {'path', 'sha256'}, 'Graph dependency')
        analysis_sources.relative_path(fact['path'])
        if fact['path'] in declared: raise ValueError('duplicate Graph dependency')
        declared.add(fact['path'])
        p, _ = _pin({'path': str(graph_root / fact['path']), 'sha256': fact['sha256']}, base, _session)
        files.append(p)
    actual = {p.relative_to(graph_root).as_posix() for p in graph_root.rglob('*') if p.is_file()}
    if actual != declared or 'state.lock' not in declared:
        raise ValueError('review snapshot has missing/extra dependencies or lock absent')
    if review['critic']['node'] == review['verifier']['node']:
        raise ValueError('distinct existing critic and verifier nodes required')
    for role in ('critic', 'verifier'):
        row = review[role]; _keys(row, {'node', 'packet_sha256'}, 'source review role')
        receipt = agent_graph.model_receipt(graph_root, row['node'], expected_subject_sha256=review['subject']['sha256'], expected_packet_sha256=row['packet_sha256'], require_exact_subject=True)
        value = receipt['public_value']
        if receipt['role'] != role or type(value) is not dict or value.get('kind') != 'native-source-graph-review/v1' or value.get('decision') != 'source_clear' or value.get('subject_sha256') != review['subject']['sha256'] or value.get('members') != [r['id'] for r in d['members']] or value.get('unresolved') != [] or value.get('physics_validated') is not False or value.get('numerical_equivalence_qualified') is not False:
            raise ValueError('current complete critic/verifier source review required; numerical qualification cannot be inherited')
    def final_review_census():
        if {p.relative_to(graph_root).as_posix() for p in graph_root.rglob('*') if p.is_file()} != declared:
            raise ValueError('review dependency census changed during observation')
        for fact in review['files']:
            _pin({'path': str(graph_root / fact['path']), 'sha256': fact['sha256']}, base, _session)
    final_review_census()
    if _session is not None:
        _session.retain_final_check(final_review_census)
    # Bind native implementation and all original capsule/runtime input bytes in
    # the ordinary parent validation session; no receipt is a scientific label.
    files += [regular(Path(p), base, _session=_session) for p in (__file__, regional.__file__, regional.parametric_shapes.__file__, analysis_sources.__file__, agent_graph.__file__)]
    return list(dict.fromkeys(files))


def response(document, cell_id):
    d = validate_document(document); cell = next((c for c in d['cells'] if c['id'] == cell_id), None)
    if cell is None: raise ValueError('unknown original cell')
    base = regional.response(_scaffold_law(cell))
    witness_law = copy.deepcopy(base['document'])
    witness_law['parameters'] += [dict(name=p['name'], role='coefficient', initial=p['initial'], bounds=p['bounds'], fixed=p['fixed'], meaning='Original native graph coordinate; structural witness only', source=witness_law['sources'][0]['id']) for p in cell['parameters']]
    return {**base, 'kind': KIND, 'document': witness_law, 'base': base, 'recipe': d, 'cell': cell_id,
            **({'expected_data':expected_request(cell),'original_law':copy.deepcopy(cell['law']),'source_observations':{b['id']:b['observed'] for b in cell['law']['bins']},'build_observation_semantics':'unobserved_expected_scaffold' if cell['expected_data']['conditioning']=='supplied_nominal' else 'actual_observed_conditioning_input'} if 'expected_data' in cell else {}),
            'coordinates': base['coordinates'] + [p['name'] for p in cell['parameters']],
            'law': {**base['law'], 'native_graph': 'original reviewed factory/member graph, raw bin integrals, full-domain denominator only for densities; signed TOTAL means without clipping',
                    'numerical_equivalence_qualified': False, 'expected_data_qualified': False, 'calibration_qualified': False}}


def datacard(document, cell_id):
    d = validate_document(document); cell = next(c for c in d['cells'] if c['id'] == cell_id)
    return regional.datacard(_scaffold_law(cell)) + ''.join(p['name'] + ' flatParam\n' for p in cell['parameters'] if not p['fixed']).encode()


def template_integral(template, window):
    """Independent exact piecewise-constant source reference; no native claim."""
    lo, hi = map(_q, window)
    return sum((_q(v) * max(Fraction(), min(hi, _q(b)) - max(lo, _q(a))) / (_q(b)-_q(a))
                for a, b, v in zip(template['edges'], template['edges'][1:], template['values'])), Fraction())


def native_bridge_source(compiled):
    if compiled != response(compiled['recipe'], compiled['cell']): raise ValueError('source graph lowering changed')
    cell = next(c for c in compiled['recipe']['cells'] if c['id'] == compiled['cell'])
    tree = ast.parse(regional.native_bridge_source(compiled['base']))
    # Only the generated base mean names are changed. Original regional source,
    # auxiliaries and original user function/class source bodies are untouched.
    class Rename(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value.startswith('sum::ravel_mean_'):
                node.value = node.value.replace('sum::ravel_mean_', 'sum::ravel_base_mean_', 1)
            return node
    tree = Rename().visit(tree)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'doParametersOfInterest')
    lines = ['import ROOT', 'from array import array', 'w = self.modelBuilder.out', 'self._ravel_graph_objects = []']
    for pin in compiled['recipe']['runtime']['artifacts']:
        if Path(pin['path']).suffix in ('.so','.dylib'):
            lines.append('if ROOT.gSystem.Load('+repr(pin['path'])+') < 0: raise ValueError("original prepared native library failed to load")')
    for p in cell['parameters']:
        literal = p['name']+'['+','.join(regional._native_number(v) for v in [p['initial'], *p['bounds']])+']'
        lines += ['self.modelBuilder.doVar('+repr(literal)+')', 'w.var('+repr(p['name'])+').setConstant('+repr(p['fixed'])+')', 'w.var('+repr(p['name'])+').setUnit('+repr(p['unit'])+')']
        if not p['fixed']: lines += ['self.modelBuilder.extraNuisances.append(w.var('+repr(p['name'])+'))']
    for o in cell['observables']:
        source_lo, source_hi = _interval(o['bounds'])
        lo, hi = float(source_lo), float(source_hi)
        midpoint = _native_float((source_lo+source_hi)/2, 'integration observable midpoint')
        if not lo <= midpoint <= hi: raise ValueError('native midpoint outside original observable domain')
        literal = o['name']+'['+','.join(map(str, [midpoint, lo, hi]))+']'
        lines += ['self.modelBuilder.doVar('+repr(literal)+')', 'w.var('+repr(o['name'])+').setConstant(True)', 'w.var('+repr(o['name'])+').setUnit('+repr(o['unit'])+')']
    rows = [{'id': n['name'], 'depends_on': [v for v in n['depends_on'] if v in {r['name'] for r in cell['nodes']}]} for n in cell['nodes']]
    for name in _dag(rows, [t['node'] for t in cell['components']], label='native node'):
        n = next(n for n in cell['nodes'] if n['name'] == name)
        if n['kind'] == 'factory':
            lines += ['self.modelBuilder.factory_('+repr(n['factory'])+')']
        else:
            t = n['template']
            if 'axes' in t:
                geometry=_joint_template_geometry(t); names=[a['observable'] for a in t['axes']]
                for axis in t['axes']:
                    edges=[float(_q(v)) for v in axis['edges']]
                    lines += ['w.var('+repr(axis['observable'])+').setBinning(ROOT.RooBinning('+str(len(edges)-1)+', array("d", '+repr(edges)+')))']
                lines += ['variables = ROOT.RooArgSet(*[w.var(n) for n in '+repr(names)+'])',
                          'data = ROOT.RooDataHist('+repr(name+'_data')+', '+repr(name)+', variables)']
                for row in geometry:
                    for observable,value in zip(names,row['midpoints']): lines += ['w.var('+repr(observable)+').setVal('+repr(value)+')']
                    lines += ['data.set(variables, '+repr(row['height'])+', 0.0)']
                lines += ['fn = ROOT.RooHistFunc('+repr(name)+', '+repr(name)+', variables, data, 0)',
                          'getattr(w,"import")(fn)', 'self._ravel_graph_objects.extend([data,fn])']
            else:
                edges, values = _template_native_geometry(t)
                lines += ['h = ROOT.TH1D('+repr(name+'_hist')+', '+repr(name)+', '+str(len(values))+', array("d", '+repr(edges)+'))', 'h.SetDirectory(0)',
                          'for i,v in enumerate('+repr(values)+',1): h.SetBinContent(i,v)',
                          'data = ROOT.RooDataHist('+repr(name+'_data')+', '+repr(name)+', ROOT.RooArgList(w.var('+repr(t['observable'])+')), h)',
                          'fn = ROOT.RooHistFunc('+repr(name)+', '+repr(name)+', ROOT.RooArgSet(w.var('+repr(t['observable'])+')), data, 0)',
                          'getattr(w,"import")(fn)', 'self._ravel_graph_objects.extend([h,data,fn])']
    settings = cell['integration']
    lines += ['cfg = ROOT.RooNumIntConfig(ROOT.RooAbsReal.defaultIntegratorConfig())',
              'cfg.setEpsAbs('+repr(float(_q(settings['eps_abs'])))+')', 'cfg.setEpsRel('+repr(float(_q(settings['eps_rel'])))+')',
              'cfg.method1D().setLabel("RooIntegrator1D")', 'cfg.getConfigSection("RooIntegrator1D").setRealValue("maxSteps", '+str(settings['max_steps'])+')',
              'cfg.getConfigSection("RooIntegrator1D").setRealValue("minSteps", 999)',
              'cfg.getConfigSection("RooIntegrator1D").setRealValue("fixSteps", 0)',
              'cfg.getConfigSection("RooIntegrator1D").setCatLabel("sumRule", "Trapezoid")',
              'cfg.getConfigSection("RooIntegrator1D").setCatLabel("extrapolation", "Wynn-Epsilon")']
    if compiled['recipe']['schema_version']==2:
        lines += ['cfg.method2D().setLabel("RooAdaptiveIntegratorND")','cfg.methodND().setLabel("RooAdaptiveIntegratorND")']
        for key,native in [('max_eval_2d','maxEval2D'),('max_eval_3d','maxEval3D'),('max_eval_nd','maxEvalND'),('max_warn','maxWarn')]:
            lines += ['cfg.getConfigSection("RooAdaptiveIntegratorND").setRealValue('+repr(native)+', '+repr(settings[key])+')']
    # Released RooRealIntegral retains/copies a borrowed config pointer.
    lines += ['self._ravel_graph_objects.append(cfg)']
    by_bin = [[] for b in cell['law']['bins']]
    all_coordinates = compiled['coordinates']; aux = cell['law']['auxiliary']
    for j, t in enumerate(cell['components']):
        names=_component_observables(t);observables={o['name']:o for o in cell['observables']}
        lines += ['fn = w.function('+repr(t['node'])+') or w.pdf('+repr(t['node'])+')',
                  'observers = [w.var(n) for n in '+repr(names)+']', 'obsset = ROOT.RooArgSet(*observers)', 'fn.setIntegratorConfig(cfg)',
                  'if set(v.GetName() for v in fn.getObservables(ROOT.RooArgSet(*[w.var(n) for n in '+repr([o['name']for o in cell['observables']])+']))) != set('+repr(names)+'): raise ValueError("original integrand observable identity changed")']
        denominator = 'ravel_graph_den_'+str(j)
        if t['normalization'] == 'full_domain':
            lines += ['integral = fn.createIntegral(obsset, cfg)',
                      'if len(integral.numIntRealVars()) > 15: raise ValueError("unsupported residual numeric dimension; retain native source/card fallback")',
                      'integral.SetName('+repr(denominator)+')', 'getattr(w,"import")(integral,ROOT.RooFit.RecycleConflictNodes())', 'self._ravel_graph_objects.append(integral)',
                      'if not math.isfinite(w.function('+repr(denominator)+').getVal()) or w.function('+repr(denominator)+').getVal() <= 0: raise ValueError("full-domain density normalization is not positive finite")']
        for b, window in enumerate(t['bin_windows']):
            numerator = 'ravel_graph_int_'+str(j)+'_'+str(b); term = 'ravel_graph_term_'+str(j)+'_'+str(b)
            rectangle=_component_rectangle(t,window)
            for name in names: lines += ['w.var('+repr(name)+').setRange('+repr(numerator)+', '+','.join(repr(float(_q(v)))for v in rectangle[name])+')']
            lines += ['integral = fn.createIntegral(obsset, cfg, '+repr(numerator)+')',
                      'if len(integral.numIntRealVars()) > 15: raise ValueError("unsupported residual numeric dimension; retain native source/card fallback")',
                      'integral.SetName('+repr(numerator)+')', 'getattr(w,"import")(integral,ROOT.RooFit.RecycleConflictNodes())', 'self._ravel_graph_objects.append(integral)']
            args = [numerator] + ([denominator] if t['normalization'] == 'full_domain' else [])
            expr = regional._formula_number(t['coefficients'][b])+'*@0'+('/@1' if len(args)==2 else '')
            for p, power in t['powers'].items():
                args.append(p); expr += '*pow(@'+str(len(args)-1)+','+str(power)+')'
            r = list(map(_q, t['log_response'][b])); offset = sum((r[i]*_q(aux['observed'][i]) for i in range(len(r))), Fraction())
            slopes = [sum((r[i]*_q(aux['factor'][i][a]) for i in range(len(r))), Fraction()) for a in range(len(r))]
            if offset or any(slopes):
                exp = regional._formula_number(str(offset))
                for a, slope in enumerate(slopes):
                    if slope:
                        args.append('ravel_aux_'+str(a)); exp += '+('+regional._formula_number(str(slope))+')*@'+str(len(args)-1)
                expr += '*exp('+exp+')'
            literal = 'expr::'+term+'("'+expr+'",'+','.join(args)+')'
            lines += ['self.modelBuilder.factory_('+repr(literal)+')']; by_bin[b].append(term)
    for b, terms in enumerate(by_bin):
        lines += ['self.modelBuilder.factory_('+repr('sum::ravel_mean_'+str(b)+'(ravel_base_mean_'+str(b)+','+','.join(terms)+')')+')',
                  'if not math.isfinite(w.function('+repr('ravel_mean_'+str(b))+').getVal()) or w.function('+repr('ravel_mean_'+str(b))+').getVal() <= 0: raise ValueError("TOTAL expected mean must be positive finite; no clipping")']
    extra = ast.parse('import math\n'+'\n'.join(lines)).body
    method.body += extra
    return ast.unparse(ast.fix_missing_locations(tree))+'\n'


def structural_witness(probe, config, compiled, expected_preparation=None):
    """Native custody/graph linkage only; never manufacture numerical parity."""
    from ravel.physics.native_likelihood import _check_regional_linkage, _finite
    _check_regional_linkage(probe, config, compiled)
    cell = next(c for c in compiled['recipe']['cells'] if c['id'] == compiled['cell'])
    expected = {n['name']: {'class': n['class'], 'servers': sorted(n['depends_on'])} for n in cell['nodes']}
    if probe.get('source_graph_nodes') != expected: raise ValueError('original native object/class/server census differs')
    expected_observables = {o['name']: {'bounds': list(map(float,map(_q,o['bounds']))), 'unit':o['unit'], 'constant':True} for o in cell['observables']}
    if probe.get('source_graph_observables') != expected_observables:
        raise ValueError('original native integration ranges/units/constant ownership differ')
    observations = {'counts': {b['id']: b['observed'] for b in compiled['document']['bins']}, 'dataset_weight': 1.0,
                    'auxiliary': {'ravel_aux_'+str(i)+'_In': {'value': 0.0, 'constant': True} for i in range(len(compiled['document']['auxiliary']['names']))}}
    if expected_preparation is not None:
        observations=validate_expected_delivery(expected_preparation,compiled)
        if probe.get('construction_count_domains')!=expected_preparation.get('count_domains'):raise ValueError('serialized generated count domains changed')
    if probe.get('construction_observations') != observations: raise ValueError('complete original/generated observations changed')
    if compiled['recipe']['schema_version']==2 or 'expected_data' in cell:
        integration_witness(probe.get('source_graph_integrals'),compiled)
        _template_readback(probe.get('source_graph_templates'),compiled)
        for witness in probe['fixed_witnesses']: integration_witness(witness.get('source_graph_integrals'),compiled)
    rows = []
    for witness in probe['fixed_witnesses']:
        _finite(witness['raw_nll_at_source_nuisance_values'], 'source graph raw NLL')
        state = witness.get('construction_state', {})
        if set(state) != set(compiled['coordinates']): raise ValueError('complete source graph coordinate state required')
        for name, value in state.items():
            p = next((p for p in compiled['document']['parameters'] if p['name']==name), None)
            bounds = p['bounds'] if p else compiled['document']['auxiliary']['eta_bounds'][int(name.rsplit('_',1)[1])]
            fixed = p['fixed'] if p else False
            if [value['minimum'],value['maximum']] != list(map(float,map(_q,bounds))) or value['constant'] != fixed or not float(_q(bounds[0])) <= _finite(value['value'],'coordinate') <= float(_q(bounds[1])):
                raise ValueError('source graph coordinate domain/fixed state changed')
            if p and fixed and value['value'] != float(_q(p['initial'])): raise ValueError('fixed source graph coordinate changed')
        if state[config['fit']['poi']]['value'] != float(_q(witness['point'])) or set(witness['scales']) != set(compiled['functions']):
            raise ValueError('source graph fixed-point/function census changed')
        for name, value in witness['scales'].items():
            if _finite(value,'TOTAL mean') <= 0: raise ValueError('invalid signed TOTAL mean')
            rows.append({'point':witness['point'],'function':name,'actual':value,'reference_kind':'structural custody only; no numerical reference',
                         'numerical_equivalence_qualified':False,'expected_data_qualified':False,'calibration_qualified':False})
    return rows


def validate_task(task):
    _keys(task, {'input'}, 'constructor task')


validate = validate_task


def _load(task, base, session=None):
    from ravel.workflow.science import regular
    validate_task(task); p = regular(task['input'], base, _session=session)
    d = session.read_document(p) if session is not None else read_json(p)
    validate_document(d)
    return p, d


def inputs(task, base, *, _session=None):
    p, d = _load(task,base,_session)
    files = source_inputs(d,p.parent,_session=_session)
    # Runtime pins are subsequently checked by each ordinary native task. Bind
    # them here too, so a source-only preparation plan cannot omit host/image ABI.
    runtime = d['runtime']; transport = runtime['transport']
    pins = (list(runtime['tools'].values())+runtime['artifacts']) if transport['kind']=='local' else [transport[k] for k in ('executable','image_archive','image_manifest')]
    pins += [runtime['version_proof']['source']]
    for value in pins:
        if not Path(value['path']).is_absolute():
            raise ValueError('absolute original runtime pins required for per-cell relocation')
        path,_ = _pin(value,p.parent,_session); files.append(path)
    return list(dict.fromkeys([p,*files]))


def execution_seconds(task, base, *, _session=None):
    return _load(task,base,_session)[1]['max_seconds']


def _validation_inputs(task, base, session):
    return inputs(task,base,_session=session)


def _validation_execution_seconds(task, base, session):
    return execution_seconds(task,base,_session=session)


def run(task, base, out):
    """Emit every native bundle and task; never build or fit a workspace here."""
    from ravel.physics import native_likelihood
    p, d = _load(task,base); inputs(task,base)
    output = Path(out)
    if output.exists() or any(q.is_symlink() for q in (output,*output.parents)):
        raise ValueError('fresh nonsymlink constructor output required')
    # Absolute input paths keep the original review and source subject stable.
    if not Path(d['source_capsule']['root']).is_absolute() or not Path(d['review']['root']).is_absolute() or not Path(d['review']['subject']['path']).is_absolute() or any(not Path(s['path']).is_absolute() for c in d['cells'] for s in c['law']['sources']):
        raise ValueError('ordinary construction requires absolute original source/review/law pins')
    output.parent.mkdir(parents=True,exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.native-statistical-construction-',dir=output.parent))
    intended = {}

    def verify(path, root=staging):
        relative = path.relative_to(root)
        if relative not in intended or any(q.is_symlink() for q in (path,*path.parents)) or not path.is_file():
            raise ValueError('intended constructor artifact missing/aliased')
        before = path.stat(); raw = path.read_bytes(); after = path.stat()
        if ((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
                != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
                or (len(raw),hashlib.sha256(raw).hexdigest()) != intended[relative]):
            raise ValueError('intended constructor artifact changed')

    def commit(path, raw, value=None):
        relative = path.relative_to(staging)
        # A declared relocation may replace only the exact previous commitment.
        # The new commitment derives from intended bytes before serialization.
        if relative in intended:
            verify(path)
        elif path.exists() or path.is_symlink():
            raise ValueError('fresh intended constructor artifact required')
        intended[relative] = (len(raw),hashlib.sha256(raw).hexdigest())
        if value is None:
            path.write_bytes(raw)
        else:
            atomic_json(path,value)
        verify(path)

    def commit_json(path, value):
        # Exact original atomic_json encoding, including insertion order.
        raw = (json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')
        commit(path,raw,value)

    def verify_population(root):
        if any(q.is_symlink() for q in (root,*root.parents)) or not root.is_dir():
            raise ValueError('ordinary constructor artifact tree required')
        files, directories = set(), set()
        for path in root.rglob('*'):
            if path.is_symlink():
                raise ValueError('constructor artifact alias refused')
            relative = path.relative_to(root)
            if path.is_dir():
                directories.add(relative)
            elif path.is_file():
                files.add(relative); verify(path,root)
            else:
                raise ValueError('nonordinary constructor artifact refused')
        expected_directories = {parent for relative in intended for parent in relative.parents if parent != Path('.')}
        if files != set(intended) or directories != expected_directories:
            raise ValueError('complete intended constructor artifact census changed')

    rows, configurations = [], {}
    recipe_raw = encoded(d)
    for cell in d['cells']:
        destination = staging / cell['id']; destination.mkdir()
        commit(destination/'recipe.json',recipe_raw)
        commit(destination/'model.txt',datacard(d,cell['id']))
        compiled = response(d,cell['id'])
        commit(destination/'source_response.py',native_bridge_source(compiled).encode('utf-8'))
        pin = lambda name: {'path':str((destination/name).resolve()),'sha256':intended[(destination/name).relative_to(staging)][1]}
        source_files = []
        for fact in d['source_capsule']['files']:
            target = destination/'source'/fact['path']; target.parent.mkdir(parents=True,exist_ok=True)
            original,raw = _pin({'path':str(Path(d['source_capsule']['root'])/fact['path']),'sha256':fact['sha256']},p.parent)
            commit(target,raw)
            source_files.append({'path':str(target.resolve()),'sha256':fact['sha256'],'staged_path':'source/'+fact['path']})
        config = {'schema_version':3 if 'derivatives' in cell else 2 if 'saved_fit' in cell['fit'] else 1, 'source':d['question'],
                  **({'expected_data':copy.deepcopy(cell['expected_data'])} if 'expected_data' in cell else {}),
                  **({'derivatives':copy.deepcopy(cell['derivatives'])} if 'derivatives' in cell else {}),
                  **({'calibration':copy.deepcopy(cell['calibration'])} if 'calibration' in cell else {}),
                  **({'discovery_diagnostic':copy.deepcopy(cell['discovery_diagnostic'])} if 'discovery_diagnostic' in cell else {}),
                  'model':{'files':[{**pin('model.txt'),'staged_path':CARD},*source_files], 'card':CARD,
                           'regions':[{'channel':b['id'],'role':b['role']} for b in cell['law']['bins']], 'physics_model':None, 'signal_replacement':None,
                           'source_graph':{'recipe':pin('recipe.json'),'cell':cell['id']}},
                  'runtime':copy.deepcopy(d['runtime']), 'fit':copy.deepcopy(cell['fit']), 'max_seconds':d['max_seconds']}
        configurations[cell['id']] = copy.deepcopy(config)
        commit_json(destination/'native.json',config)
        native_task = {'input':str((destination/'native.json').resolve())}
        # This is the real ordinary admission route, including runtime/config
        # validation; it does not invoke native commands or confer approval.
        native_likelihood.inputs(native_task,destination)
        row = {'id':cell['id'],'coordinates':cell['coordinates'],'task':native_task,'mode':'asimov-sensitivity' if 'discovery_diagnostic' in cell else 'full-auxiliary-calibration' if 'calibration' in cell else 'native-likelihood','parent_scope':d['scope'],
               'max_seconds':d['max_seconds'],'card':pin('model.txt'),'bridge':pin('source_response.py'),
               'numerical_equivalence_qualified':False,'calibration_qualified':False,'physics_validated':False}
        commit_json(destination/'task.json',row); rows.append(row)
    result = {'status':'passed','physics_validated':False,'scope':d['scope'],'kind':KIND,'population':d['population'],'cells':rows,
              'source_subject_sha256':hashlib.sha256(subject(d)).hexdigest(),'native_calls':0,'fit_calls':0,
              'limitations':['Existing Graph receipts bind a structural source judgment, not numerical or scientific truth.',
                             'Native integrals, template morphs, optimizer domain behavior and complete inference/calibration require later ordinary qualification.']}
    # Every cell has passed ordinary native admission before public output exists.
    # Failed staging evidence stays private; no partial cell population is served.
    verify_population(staging)
    for row in rows:
        old = staging/row['id']; final = output/row['id']
        # Never recapture arbitrary emitted JSON as the intended configuration.
        cfg = copy.deepcopy(configurations[row['id']])
        for fact in cfg['model']['files']:
            fact['path'] = str(final/Path(fact['path']).relative_to(old))
        cfg['model']['source_graph']['recipe']['path'] = str(final/'recipe.json')
        commit_json(old/'native.json',cfg)
        row['task']['input'] = str(final/'native.json')
        row['card']['path'] = str(final/'model.txt'); row['bridge']['path'] = str(final/'source_response.py')
        commit_json(old/'task.json',row)
    commit_json(staging/'construction.json',result)
    # Recheck complete intended membership and phase-specific commitments after
    # original input custody, immediately before the single publication rename.
    inputs(task,base)
    if output.exists() or any(q.is_symlink() for q in (output,*output.parents)):
        raise ValueError('constructor output appeared/changed before publication')
    verify_population(staging)
    staging.rename(output)
    verify_population(output)
    return result

def _scaffold_law(cell):
    law=copy.deepcopy(cell['law'])
    if 'expected_data' not in cell: return law
    if 'expected_data' in law: raise ValueError('source graph expected request belongs to the original cell, not regional CLs')
    request=cell['expected_data']
    if type(request)is not dict or request.get('kind')!='source-graph-asimov/v1': raise ValueError('explicit source graph generating law required')
    nominal=request.get('conditioning')=='supplied_nominal'
    for b in law['bins']:
        if b['observed'] is None:
            if not nominal: raise ValueError('actual complete observations required for conditioning')
            b['observed']=0
    return law


def expected_request(cell):
    r=cell['expected_data']; _keys(r,{'kind','conditioning','point','source','statement','fit'},'source graph expected declaration')
    if r['kind']!='source-graph-asimov/v1' or r['conditioning'] not in ('supplied_nominal','fit_observed_at_fixed_poi'): raise ValueError('closed source graph nominal/conditioning mode required')
    _text(r['statement'])
    if r['source'] not in {s['id'] for s in cell['law']['sources']}: raise ValueError('source-bound generating point required')
    pars=cell['law']['parameters']+cell['parameters']; aux=cell['law']['auxiliary']
    _keys(r['point'], {p['name']for p in pars}|{'ravel_aux_'+str(i)for i in range(len(aux['names']))},'full original generating point')
    for p in pars:
        q=_q(r['point'][p['name']]); _native_float(q,'source expected coordinate')
        if not _q(p['bounds'][0])<=q<=_q(p['bounds'][1]) or p['fixed'] and q!=_q(p['initial']): raise ValueError('source point changes fixed value or original domain')
    for i,bounds in enumerate(aux['eta_bounds']):
        q=_q(r['point']['ravel_aux_'+str(i)]); _native_float(q,'source expected eta')
        if not _q(bounds[0])<=q<=_q(bounds[1]): raise ValueError('source point outside auxiliary domain')
    if r['conditioning']=='supplied_nominal':
        if r['fit'] is not None: raise ValueError('nominal data generation carries no hidden conditioning fit')
    else:
        if any(type(b['observed'])is not int or b['observed']<0 for b in cell['law']['bins']): raise ValueError('conditioning requires original integer observations')
        f=r['fit']; _keys(f,{'strategy','tolerance','max_calls','max_iterations','max_edm'},'source conditioning fit')
        if type(f['strategy'])is not int or f['strategy']not in (0,1,2): raise ValueError('bounded native strategy required')
        for key in ('max_calls','max_iterations'):
            if type(f[key])is not int or not 1<=f[key]<=100000: raise ValueError('bounded native conditioning work required')
        if _q(f['tolerance'])<=0 or _q(f['max_edm'])<=0: raise ValueError('positive native fit tolerance/EDM required')
    return copy.deepcopy(r)


def _component_observables(component):
    names=component.get('observables',[component['observable']] if 'observable'in component else None)
    if type(names)is not list or not names or any(type(n)is not str for n in names): raise ValueError('full original observable tuple required')
    return names


def _component_rectangle(component,window):
    names=_component_observables(component)
    if 'observables'in component:
        _keys(window,set(names),'full original bin hyperrectangle')
        return window
    return {names[0]:window}


def _joint_template_geometry(template):
    axes=template['axes']; values=template['values']; rows=[]
    for row in values:
        widths=[];midpoints=[];native_volume=1.;volume=Fraction(1)
        for axis,index in zip(axes,row['indices']):
            lo,hi=_interval(axis['edges'][index:index+2]); width=hi-lo
            midpoint=_native_float((lo+hi)/2,'joint template midpoint')
            if not float(lo)<midpoint<float(hi): raise ValueError('joint bin has no representable interior midpoint')
            native_center=0.5*(float(lo)+float(hi))
            if not math.isfinite(native_center) or not float(lo)<native_center<float(hi): raise ValueError('original RooBinning binCenter has no finite interior native representation')
            volume*=width;native_volume*=float(hi)-float(lo)
            if not math.isfinite(native_volume) or native_volume==0: raise ValueError('joint native bin volume overflow/underflow')
            widths.append(width);midpoints.append(midpoint)
        _native_float(volume,'joint bin volume');value=_q(row['integral']);height=_native_float(value/volume,'joint deterministic height')
        reconstructed=height*native_volume
        if not math.isfinite(reconstructed) or value!=0 and reconstructed==0: raise ValueError('joint native geometry erases original bin integral')
        rows.append({'indices':row['indices'],'midpoints':midpoints,'height':height,'source_integral':row['integral'],'source_volume':str(volume),'native_volume':native_volume})
    return rows


def _validate_joint_template(t,node,obs,paths,maximum):
    _keys(t,{'source_path','axes','values','semantics'},'joint template')
    if node['class']!='RooHistFunc' or t['source_path']not in paths or t['semantics']!='absolute_bin_integrals_piecewise_constant': raise ValueError('original joint deterministic measure/source required')
    axes=t['axes']
    if type(axes)is not list or not 1<=len(axes)<=32: raise ValueError('bounded complete joint axes required')
    for axis in axes:
        _keys(axis,{'observable','edges'},'joint axis')
        if axis['observable']not in obs or type(axis['edges'])is not list or len(axis['edges'])<2: raise ValueError('source-bound ordered full edges required')
        for lo,hi in zip(axis['edges'],axis['edges'][1:]): _interval([lo,hi])
        if [axis['edges'][0],axis['edges'][-1]]!=obs[axis['observable']]['bounds']: raise ValueError('joint axes must span original full domains')
    names=[a['observable']for a in axes]
    if len(names)!=len(set(names))or node['depends_on']!=names: raise ValueError('joint axis identity/server census differs')
    count=math.prod(len(a['edges'])-1 for a in axes)
    if count>maximum or type(t['values'])is not list or len(t['values'])!=count: raise ValueError('complete joint table exceeds declared finite resource or omits bins')
    expected=itertools.product(*(range(len(a['edges'])-1)for a in axes))
    for row,index in zip(t['values'],expected):
        _keys(row,{'indices','integral'},'joint original cell')
        if type(row['indices'])is not list or any(type(i)is not int for i in row['indices'])or tuple(row['indices'])!=index: raise ValueError('original Cartesian rows missing/duplicated/reordered')
        _q(row['integral'])
    _joint_template_geometry(t)


def joint_template_integral(template,rectangle):
    names=[a['observable']for a in template['axes']];_keys(rectangle,set(names),'joint reference rectangle')
    result=Fraction()
    for row in template['values']:
        portion=Fraction(1)
        for axis,index in zip(template['axes'],row['indices']):
            lo,hi=map(_q,axis['edges'][index:index+2]);a,b=_interval(rectangle[axis['observable']])
            portion*=max(Fraction(),min(hi,b)-max(lo,a))/(hi-lo)
        result+=_q(row['integral'])*portion
    return result


def integration_witness(rows,compiled):
    """Check complete actual joint metadata/scalars; convergence remains unknown."""
    cell=next(c for c in compiled['recipe']['cells']if c['id']==compiled['cell']);obs={o['name']:o for o in cell['observables']}; expected={}
    for j,t in enumerate(cell['components']):
        names=_component_observables(t)
        if t['normalization']=='full_domain':expected['ravel_graph_den_'+str(j)]=(t,None,{n:obs[n]['bounds']for n in names})
        for i,window in enumerate(t['bin_windows']):
            name='ravel_graph_int_'+str(j)+'_'+str(i);expected[name]=(t,name,_component_rectangle(t,window))
    if type(rows)is not list or len(rows)!=len(expected)or len({r.get('name')for r in rows if type(r)is dict})!=len(rows):raise ValueError('complete original joint integral census required')
    for r in rows:
        _keys(r,{'name','component','observables','range_name','ranges','integrand','value','intVars','numIntRealVars','anaIntVars','numIntCatVars','factoredVars','engine_variables','numerical_dimension','requested','effective','status','error','relative_error','evaluations','numerical_equivalence_qualified'},'native joint integral readback')
        if r['name']not in expected:raise ValueError('foreign integral')
        t,range_name,rectangle=expected[r['name']];names=_component_observables(t);dim=r['numerical_dimension']
        if type(dim)is not int or not 0<=dim<=15 or r['requested']!=cell['integration']or r['component']!=t['id']or r['observables']!=names or r['range_name']!=range_name or r['integrand']!=t['node']:raise ValueError('original joint integral identity/policy changed')
        if r['ranges']!={n:list(map(float,map(_q,rectangle[n])))for n in names}:raise ValueError('original joint integral full/range endpoints changed')
        partitions=[r[k]for k in ('numIntRealVars','anaIntVars','factoredVars')]
        native_names=r['intVars']
        if type(native_names)is not list or native_names!=sorted(set(native_names))or r['numIntCatVars']!=[]or any(type(v)is not list or v!=sorted(set(v))for v in partitions)or len(partitions[0])!=dim or set().union(*map(set,partitions))!=set(native_names)or sum(map(len,partitions))!=len(native_names):raise ValueError('native analytic/numeric/factored tuple partition differs')
        mappings=r['engine_variables'];nodes={node['name']:node for node in cell['nodes']}
        if type(mappings)is not list or [v.get('name')for v in mappings]!=native_names:raise ValueError('complete actual engine variable mapping required')
        closure=set()
        for mapping in mappings:
            _keys(mapping,{'name','class','original_observables'},'actual engine variable');name=mapping['name']
            if name in names:expected_class='RooRealVar';originals={name}
            elif name in nodes:
                expected_class=nodes[name]['class'];pending=[name];visited=set();originals=set()
                while pending:
                    node=pending.pop()
                    if node in visited:continue
                    visited.add(node)
                    for dependency in nodes[node]['depends_on']:
                        if dependency in names:originals.add(dependency)
                        elif dependency in nodes:pending.append(dependency)
            else:raise ValueError('undeclared transformed native variable; retain original supplied-card fallback')
            if mapping['class']!=expected_class or mapping['original_observables']!=sorted(originals)or not originals:raise ValueError('transformed engine variable original source closure/class differs')
            closure.update(originals)
        if closure!=set(names):raise ValueError('actual engine variables omit original joint coordinates')
        effective={'eps_abs':0.0 if dim>=2 else float(_q(cell['integration']['eps_abs'])),'eps_rel':float(_q(cell['integration']['eps_rel'])),'max_warn':0 if dim>=2 else None,'method':'RooAdaptiveIntegratorND'if dim>=2 else 'RooIntegrator1D'if dim==1 else 'source_analytical'}
        if r['effective']!=effective or any(r[k]is not None for k in ('status','error','relative_error','evaluations'))or r['numerical_equivalence_qualified']is not False:raise ValueError('unknown native convergence or effective settings misrepresented')
        if type(r['value'])not in(int,float)or not math.isfinite(r['value'])or range_name is None and r['value']<=0:raise ValueError('invalid raw joint value/denominator')
    return copy.deepcopy(rows)


def _template_readback(rows,compiled):
    cell=next(c for c in compiled['recipe']['cells']if c['id']==compiled['cell']);expected={n['name']:n for n in cell['nodes']if n['kind']=='template'}
    if type(rows)is not dict or set(rows)!=set(expected):raise ValueError('complete native template readback required')
    for name,node in expected.items():
        t=node['template'];r=rows[name];_keys(r,{'axes','cells','interpolation_order'},'native deterministic table')
        if 'axes'in t:
            axes=t['axes'];geometry=_joint_template_geometry(t)
        else:
            axes=[{'observable':t['observable'],'edges':t['edges']}];edges,heights=_template_native_geometry(t)
            geometry=[{'indices':[i],'height':h}for i,h in enumerate(heights)]
        if r['axes']!=[{'observable':a['observable'],'edges':list(map(float,map(_q,a['edges'])))}for a in axes]or r['interpolation_order']!=0:raise ValueError('native original template edges/order changed')
        if type(r['cells'])is not list or len(r['cells'])!=len(geometry):raise ValueError('native full joint table missing/extra')
        actual={tuple(c['indices']):c for c in r['cells']}
        if len(actual)!=len(geometry):raise ValueError('duplicate native template cell')
        for g in geometry:
            c=actual.get(tuple(g['indices']));_keys(c,{'indices','height','sumw2'},'native cell')
            if c['height']!=g['height']or ('axes'in t and c['sumw2']!=0):raise ValueError('native deterministic original heights/errors changed')


def validate_expected_delivery(result,compiled):
    cell=next(c for c in compiled['recipe']['cells']if c['id']==compiled['cell']);r=expected_request(cell)
    if type(result)is not dict or result.get('kind')!='source-graph-asimov/v1' or result.get('status')!='passed' or result.get('request')!=r or result.get('generating_request')!=r or result.get('source_graph_cell')!=cell['id']:raise ValueError('exact original complete source expected preparation required')
    if result.get('dataset_name')!='data_obs' or result.get('observed_endpoint')is not None or result.get('conditioning')!=r['conditioning']:raise ValueError('expected dataset/endpoint/conditioning identity changed')
    if result.get('data_semantics')!='generated_source_graph_Asimov_not_observed' or result.get('original_counts')!=compiled['source_observations']or result.get('build_observation_semantics')!=compiled['build_observation_semantics']:raise ValueError('original observed/null/scaffold identity changed')
    flags=('expected_data_qualified','numerical_equivalence_qualified','coverage_qualified','optimizer_globality_qualified')
    if any(result.get(f)is not False for f in flags):raise ValueError('source structural data readback cannot imply qualification')
    state=result.get('generating_state'); final=result.get('final_state');pars={p['name']:p for p in compiled['document']['parameters']};aux=compiled['document']['auxiliary']
    initial_counts={b['id']:b['observed']for b in compiled['document']['bins']}
    if result.get('initial_dataset_counts')!=initial_counts:raise ValueError('original native scaffold/observed count population changed')
    initial_globals={'ravel_aux_'+str(i)+'_In':{'value':0.0,'constant':True,'has_min':False,'has_max':False}for i in range(len(aux['names']))}
    if result.get('original_globals')!=initial_globals:raise ValueError('original native Gaussian observations changed')
    original=result.get('original_state')
    expected_initial={p['name']:float(_q(p['initial']))for p in pars.values()}
    expected_initial.update({'ravel_aux_'+str(i):0.0 for i in range(len(aux['names']))})
    if type(original)is not dict or set(original)!=set(compiled['coordinates']):raise ValueError('complete original native coordinate census required')
    for name,row in original.items():
        _keys(row,{'value','minimum','maximum','constant'},'original native coordinate');p=pars.get(name);bounds=p['bounds']if p else aux['eta_bounds'][int(name.rsplit('_',1)[1])]
        if row!={'value':expected_initial[name],'minimum':float(_q(bounds[0])),'maximum':float(_q(bounds[1])),'constant':p['fixed']if p else False}:raise ValueError('original native coordinate state differs')
    if type(state)is not dict or set(state)!=set(compiled['coordinates'])or final!=state:raise ValueError('complete unchanged generating state required')
    for name,row in state.items():
        _keys(row,{'value','minimum','maximum','constant'},'native generating coordinate');p=pars.get(name);bounds=p['bounds']if p else aux['eta_bounds'][int(name.rsplit('_',1)[1])];fixed=p['fixed']if p else False
        if [row['minimum'],row['maximum']]!=list(map(float,map(_q,bounds)))or row['constant']!=fixed or type(row['value'])not in(int,float)or not math.isfinite(row['value'])or not row['minimum']<=row['value']<=row['maximum']:raise ValueError('generating native coordinate/fixed domain differs')
        if (r['conditioning']=='supplied_nominal' or fixed or p and p['role']=='poi')and row['value']!=float(_q(r['point'][name])):raise ValueError('generating exact declared/fixed coordinate differs')
    counts=result.get('generated_counts');domains=result.get('count_domains')
    raw=result.get('native_mean_returns')
    if type(raw)is not dict or raw!=counts or any(type(v)not in(int,float)or not math.isfinite(v)for v in raw.values()):raise ValueError('complete literal native mean returns must equal generated/dataset counts')
    ids={b['id']for b in cell['law']['bins']}
    if type(counts)is not dict or set(counts)!=ids or result.get('dataset_counts')!=counts or result.get('dataset_weight')!=1.0 or type(domains)is not dict or set(domains)!=ids:raise ValueError('full generated count/domain/dataset population differs')
    for name,value in counts.items():
        d=domains[name];_keys(d,{'has_min','has_max','minimum','maximum'},'original native count domain')
        if type(value)not in(int,float)or not math.isfinite(value)or value<=0 or type(d['has_min'])is not bool or type(d['has_max'])is not bool:raise ValueError('invalid generated source mean/domain')
        for exists,key,ok in [(d['has_min'],'minimum',lambda v:value>=v),(d['has_max'],'maximum',lambda v:value<=v)]:
            if exists and (type(d[key])not in(int,float)or not math.isfinite(d[key])or not ok(d[key]))or not exists and d[key]is not None:raise ValueError('generated count exceeded original domain')
    globals_={'ravel_aux_'+str(i)+'_In':{'value':state['ravel_aux_'+str(i)]['value'],'constant':True,'has_min':False,'has_max':False}for i in range(len(aux['names']))}
    if result.get('generated_globals')!=globals_:raise ValueError('full generating Gaussian globals changed')
    from ravel.physics import regional_expected
    checked=copy.deepcopy(r)
    if checked['conditioning']=='fit_observed_at_fixed_poi':checked['conditioning']='fit_observed_background'
    regional_expected.conditioning_check(result.get('conditioning_fit'),checked)
    if r['conditioning']!='supplied_nominal' and (result.get('conditioning_counts')!=result.get('initial_dataset_counts')or result.get('conditioning_globals')!=result.get('original_globals')):raise ValueError('conditioning changed original count/global observations')
    if r['conditioning']!='supplied_nominal':
        conditioned=copy.deepcopy(state);conditioned[next(p['name']for p in pars.values()if p['role']=='poi')]['constant']=True
        if result.get('conditioned_state')!=conditioned:raise ValueError('conditioning full coordinate state changed')
        fit=result['conditioning_fit'];free={n for n,v in conditioned.items()if not v['constant']};floats=fit.get('floating_parameters',[]);const=fit.get('constant_parameters',[])
        if type(floats)is not list or len(floats)!=len(free)or {x['name']for x in floats}!=free or type(const)is not list or len({x['name']for x in const})!=len(const):raise ValueError('conditioning full parameter population differs')
        for x in floats:
            if x['value']!=state[x['name']]['value']or type(x['error'])not in(int,float)or not math.isfinite(x['error'])or x['error']<0:raise ValueError('conditioning parameter/error differs')
        if any(next((x['value']for x in const if x['name']==n),None)!=v['value']for n,v in conditioned.items()if v['constant']):raise ValueError('conditioning fixed parameter census differs')
        covariance=fit.get('covariance',[])
        if type(covariance)is not list or len(covariance)!=len(floats)or any(type(x)is not list or len(x)!=len(floats)for x in covariance):raise ValueError('conditioning covariance geometry differs')
        for i,row in enumerate(covariance):
            for j,v in enumerate(row):
                if type(v)not in(int,float)or not math.isfinite(v)or v!=covariance[j][i]:raise ValueError('conditioning covariance differs')
    integration_witness(result.get('integration_readback'),compiled)
    return {'counts':copy.deepcopy(counts),'dataset_weight':1.0,'auxiliary':{k:{'value':v['value'],'constant':True}for k,v in globals_.items()}}
