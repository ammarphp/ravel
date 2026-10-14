"""Deliver a declared literature census and published-limit overlay.

This operation reuses summary_audit and summary_overlay. It neither searches the
literature nor derives limits. Source pins authenticate supplied bytes, not the
scientific correctness or completeness of a caller's hypothesis/census.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from ravel.physics.source_tables import bounded_read

MAX_DOCUMENT = 1024 * 1024
MAX_SOURCE = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    _require(type(value) is str and len(value) == 64 and
             all(c in '0123456789abcdef' for c in value), 'literal SHA256 required')
    return value


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('nonfinite JSON token: ' + value)
    try:
        doc = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    except RecursionError as exc:
        raise ValueError('bounded JSON nesting required') from exc
    nodes = [0]
    def check(value, depth=0):
        nodes[0] += 1
        _require(depth <= 24 and nodes[0] <= 100000, 'bounded JSON structure required')
        if type(value) is float:
            _require(math.isfinite(value), 'finite JSON numbers required')
        if type(value) is dict:
            for item in value.values(): check(item, depth+1)
        elif type(value) is list:
            for item in value: check(item, depth+1)
    check(doc)
    return doc


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value), 'finite numeric scalar required')
    return value


def validate(task):
    _require(type(task) is dict and set(task) == {'schema_version', 'input', 'input_sha256'}
             and type(task['schema_version']) is int and task['schema_version'] in (1,2),
             'closed published-summary task/v1 or v2 required')
    _require(type(task['input']) is str and task['input'], 'literal input path required')
    _sha(task['input_sha256'])
    return dict(task)


def _in_window(mass, window):
    return window['lo_gev'] <= mass and (mass <= window['hi_gev'] if
           window['upper_inclusive'] else mass < window['hi_gev'])


def inspect(survey, manifest, contract):
    """Validate supplied meaning/census and build a value-preserving window view."""
    from ravel.validation.summary_audit import audit
    _require(type(survey) is dict and type(manifest) is dict and
             type(survey.get('schema_version')) is type(manifest.get('schema_version')) is int and
             survey.get('schema_version') == manifest.get('schema_version') == 1,
             'existing census and basis manifest/v1 required')
    window = contract['window']
    _require(type(window) is dict and set(window) == {'lo_gev', 'hi_gev', 'upper_inclusive'}
             and type(window['upper_inclusive']) is bool, 'closed mass window required')
    lo, hi = _number(window['lo_gev']), _number(window['hi_gev'])
    _require(0 <= lo < hi and manifest.get('window_gev') == [lo, hi],
             'manifest and requested window must agree')
    target = manifest.get('target_basis')
    _require(type(target) is dict and all(type(target.get(k)) is str and target[k].strip()
             for k in ('quantity', 'model', 'sqrt_s')), 'explicit target quantity/model/energy required')
    energy = _number(contract['energy_tev'])
    _require(energy > 0 and target['sqrt_s'] == f'{energy:g} TeV',
             'declared energy and target label must agree')
    candidates = survey.get('candidates')
    _require(type(candidates) is list and 1 <= len(candidates) <= 64,
             'bounded nonempty complete supplied candidate census required')
    ids = [c.get('id') for c in candidates if type(c) is dict]
    _require(len(ids) == len(candidates) and all(type(i) is str and i for i in ids)
             and len(set(ids)) == len(ids), 'unique complete candidate identities required')
    evidence = contract['candidate_sources']
    _require(type(evidence) is list and len(evidence) == len(ids)
             and all(type(r) is dict for r in evidence)
             and {r.get('survey_id') for r in evidence} == set(ids),
             'exact source evidence for every supplied candidate required')
    for row in evidence:
        _require(type(row) is dict and set(row) == {'survey_id', 'mass_range_gev', 'source_ids', 'energy_tev'}
                 and _number(row['energy_tev']) == energy
                 and type(row['source_ids']) is list and row['source_ids']
                 and len(set(row['source_ids'])) == len(row['source_ids'])
                 and set(row['source_ids']) <= set(contract['source_assets']),
                 'closed candidate source/range declarations required')
    index = {c['id']: c for c in candidates}
    for row in evidence:
        candidate = index[row['survey_id']]
        limits = row['mass_range_gev']
        _require(type(limits) is list and len(limits) == 2 and
                 0 < _number(limits[0]) < _number(limits[1]) and
                 candidate.get('mass_range_gev') == limits,
                 'candidate range differs from declared source interpretation')
        disposition = candidate.get('disposition', {})
        if disposition.get('state') == 'excluded' and disposition.get('reason_class') == 'out-of-range':
            _require(limits[1] < lo or limits[0] > hi or
                     limits[0] == hi and not window['upper_inclusive'],
                     'out-of-range exclusion overlaps requested mass window')
    curves = manifest.get('curves')
    _require(type(curves) is list and 1 <= len(curves) <= 32,
             'bounded nonempty curve population required')
    curve_ids = [c.get('survey_id') for c in curves if type(c) is dict]
    _require(len(curve_ids) == len(curves) and len(set(curve_ids)) == len(curve_ids)
             and set(curve_ids) <= set(ids), 'exact unique curve to candidate joins required')
    series_pins = contract['resolved_series_sha256']
    _require(type(series_pins) is dict and set(series_pins) == set(curve_ids),
             'exact complete resolved series identity census required')
    view = deepcopy(manifest)
    view['window_upper_inclusive'] = window['upper_inclusive']
    view['annotations'] = [contract['census_scope'], contract['precision_scope'],
        'Lines connect retained samples; sample endpoints are not search-reach boundaries.']
    view['excluded_boundary_anchors'] = []
    rows, known_intervals, point_count = [], [], 0
    for source, viewed in zip(curves, view['curves']):
        sid = source['survey_id']
        resolved = source.get('resolved')
        _require(type(resolved) is dict and set(resolved) <=
                 {'mass_gev', 'obs', 'exp', 'theory', 'theory_label', 'style'}
                 and 'mass_gev' in resolved, 'closed resolved mass/limit series required')
        _require(digest(resolved) == _sha(series_pins[sid]), 'resolved values changed against source declaration')
        masses = resolved['mass_gev']
        point_count += len(masses) if type(masses) is list else 0
        _require(type(masses) is list and 2 <= len(masses) <= 10000 and
                 point_count <= 10000 and
                 all(_number(x) > 0 for x in masses) and
                 all(a < b for a, b in zip(masses, masses[1:])),
                 'positive strictly ordered complete mass coordinates required')
        _require(index[sid]['mass_range_gev'] == [masses[0], masses[-1]],
                 'census reach must match actual retained curve endpoints')
        _require(type(source.get('draw')) is str and source['draw'] in
                 ('primary', 'crosscheck', 'none'), 'explicit primary/crosscheck/dropped styling required')
        state = index[sid]['disposition']['state']
        _require((state != 'excluded' or source['draw'] == 'none') and
                 (state != 'plotted' or source['draw'] != 'none'),
                 'drawn curve and candidate disposition must agree')
        _require(type(source.get('source')) is str and source['source'] and
                 type(source.get('lumi_fb')) in (int, float) and
                 _number(source['lumi_fb']) > 0, 'explicit curve label and luminosity required')
        _require('obs' in resolved or 'exp' in resolved, 'published limit series required')
        selected = [i for i, mass in enumerate(masses) if _in_window(mass, window)]
        # A literal upper-bound sample can anchor the clipped display segment;
        # it remains outside the half-open scientific reporting window. Never
        # interpolate a new sample or borrow a value from beyond that boundary.
        anchors = [i for i, mass in enumerate(masses) if mass == hi] if (
            selected and not window['upper_inclusive']) else []
        displayed = sorted(selected + anchors)
        if anchors:
            view['excluded_boundary_anchors'].append({'survey_id': sid,
                'source_index': anchors[0], 'mass_gev': masses[anchors[0]],
                'in_requested_window': False, 'purpose': 'literal sample for display clipping only'})
        view_resolved = deepcopy(resolved)
        view_resolved['mass_gev'] = [masses[i] for i in displayed]
        for kind in ('obs', 'exp', 'theory'):
            if kind not in resolved:
                continue
            values = resolved[kind]
            _require(type(values) is list and len(values) == len(masses) and
                     all(v is None or _number(v) > 0 for v in values),
                     'full finite positive or explicitly unavailable limit series required')
            view_resolved[kind] = [values[i] for i in displayed]
            rows.extend({'survey_id': sid, 'kind': kind, 'mass_gev': mass,
                         'value': value, 'in_requested_window': _in_window(mass, window),
                         'provenance': source.get('provenance'), 'draw': source['draw']}
                        for mass, value in zip(masses, values))
        _require(all(any(resolved[k][i] is not None for k in ('obs', 'exp') if k in resolved)
                     for i in (0, len(masses)-1)),
                 'curve endpoints require actual retained published limit values')
        viewed['resolved'] = view_resolved
        if source['draw'] != 'none':
            known_intervals.append((max(lo, masses[0]), min(hi, masses[-1])))
    if view['excluded_boundary_anchors']:
        view['annotations'].append(f'Literal {hi:g} GeV samples anchor clipping only; excluded from the reported half-open window.')
    # The gap is a fact about this declared supplied census, not all experiments.
    cursor, gaps = lo, []
    for left, right in sorted((a, b) for a, b in known_intervals if a < b):
        if left > cursor:
            gaps.append([cursor, left])
        cursor = max(cursor, right)
    if cursor < hi:
        gaps.append([cursor, hi])
    declared_gaps = manifest.get('coverage_gaps')
    _require(type(declared_gaps) is list and all(type(g) is dict and
             set(g) == {'lo_gev', 'hi_gev', 'note'} and type(g['note']) is str and g['note']
             for g in declared_gaps) and
             [[g['lo_gev'], g['hi_gev']] for g in declared_gaps] == gaps,
             'coverage gap differs from complete retained curve reach')
    checks = audit(survey, manifest)
    _require(checks['verdict'] == 'PASS', 'existing summary audit refused source census/basis')
    return {'audit': checks, 'render_manifest': view, 'complete_series_rows': rows,
            'coverage_interpretation': 'Intervals without a retained curve in the supplied census; not an exhaustive current-search absence claim.',
            'window': deepcopy(window)}


def _load(task, base):
    from ravel.workflow.science import regular
    task = validate(task)
    if task['schema_version']==2:
        return _load_requested(task,base)
    input_path = regular(task['input'], base)
    raw = bounded_read(input_path, limit=MAX_DOCUMENT)
    _require(hashlib.sha256(raw).hexdigest() == task['input_sha256'], 'summary contract digest mismatch')
    contract = _json(raw)
    required = {'schema_version', 'kind', 'survey', 'manifest', 'source_assets',
                'candidate_sources', 'resolved_series_sha256', 'window', 'energy_tev', 'census_scope', 'precision_scope'}
    _require(type(contract) is dict and set(contract) == required and
             type(contract['schema_version']) is int and contract['schema_version'] == 1 and
             contract['kind'] == 'published-limit-summary/v1', 'closed summary contract/v1 required')
    _require(all(type(contract[k]) is str and contract[k].strip() and len(contract[k]) <= 160 for k in
                 ('census_scope', 'precision_scope')), 'explicit census and precision scope required')
    sources = contract['source_assets']
    _require(type(sources) is dict and 1 <= len(sources) <= 64 and
             all(type(k) is str and k for k in sources), 'bounded explicit source asset population required')
    pins, byte_total = {}, len(raw)
    def read(pin, limit):
        nonlocal byte_total
        _require(type(pin) is dict and set(pin) == {'path', 'sha256'} and
                 type(pin['path']) is str, 'closed exact resource pin required')
        path = regular(pin['path'], input_path.parent)
        data = bounded_read(path, limit=limit)
        _require(hashlib.sha256(data).hexdigest() == _sha(pin['sha256']), 'source resource digest mismatch')
        _require(path != input_path, 'contract cannot cite itself as source evidence')
        if path not in pins:
            byte_total += len(data)
            pins[path] = {'path': str(path), 'sha256': pin['sha256'], 'size': len(data)}
        else:
            _require(pins[path]['sha256'] == pin['sha256'], 'conflicting source alias')
        _require(byte_total <= MAX_TOTAL, 'bounded total supplied summary source bytes required')
        return data
    survey = _json(read(contract['survey'], MAX_DOCUMENT))
    manifest = _json(read(contract['manifest'], MAX_DOCUMENT))
    for pin in sources.values():
        read(pin, MAX_SOURCE)
    result = inspect(survey, manifest, contract)
    pins[input_path] = {'path': str(input_path), 'sha256': task['input_sha256'], 'size': len(raw)}
    result.update(contract=contract, survey=survey, manifest=manifest,
                  input_snapshot=list(pins.values()), input_source=str(input_path))
    return result


def inputs(task, base):
    return [Path(pin['path']) for pin in _load(task, base)['input_snapshot']]


def _header(loaded):
    """Experiment and luminosity the drawn curves of the supplied census declare for one header."""
    drawn = [c for c in loaded['manifest']['curves'] if c['draw'] != 'none']
    index = {c['id']: c for c in loaded['survey']['candidates']}
    experiments = {index[c['survey_id']].get('experiment') for c in drawn}
    _require(len(experiments) == 1 and all(type(e) is str and e.strip() for e in experiments),
             'one declared experiment across the drawn curves required for the single-experiment summary header; '
             f'the supplied census declares {sorted(map(repr, experiments))}')
    luminosities = {c['lumi_fb'] for c in drawn}
    _require(len(luminosities) == 1,
             'one declared luminosity across the drawn curves required for the summary header; '
             f'the supplied curves declare {sorted(luminosities)} fb^-1')
    return experiments.pop(), luminosities.pop()


def run(task, base, out):
    from ravel.workflow.state_io import atomic_json
    from ravel.plotting.summary_overlay import render_manifest
    if task['schema_version']==2:
        return _run_requested(task,base,out)
    loaded = _load(task, base)
    out = Path(out)
    _require(not out.exists() and not out.is_symlink() and not any(p.is_symlink() for p in out.parents),
             'fresh unlinked published-summary output required')
    experiment, luminosity = _header(loaded)
    out.mkdir(parents=True, exist_ok=False)
    # Retain exact supplied meaning and full arrays separately from the window view.
    atomic_json(out / 'survey.json', loaded['survey'])
    atomic_json(out / 'basis-manifest.json', loaded['manifest'])
    atomic_json(out / 'render-manifest.json', loaded['render_manifest'])
    atomic_json(out / 'summary-audit.json', loaded['audit'])
    plotted = render_manifest(loaded['render_manifest'], str(out / 'summary'), experiment=experiment,
                              com=loaded['contract']['energy_tev'], lumi=luminosity)
    _require(all((out / name).is_file() and (out / name).stat().st_size > 0
                 for name in ('summary.png', 'summary.pdf')), 'required PNG/PDF summary delivery missing')
    for pin in loaded['input_snapshot']:
        _require(hashlib.sha256(bounded_read(Path(pin['path']), limit=MAX_SOURCE)).hexdigest()
                 == pin['sha256'], 'summary source changed during rendering')
    result = {k: loaded[k] for k in ('audit', 'survey', 'manifest', 'render_manifest',
                                   'complete_series_rows', 'coverage_interpretation', 'window', 'input_snapshot')}
    result.update(kind='published-limit-summary', status='passed', physics_validated=False,
        claim_scope='source_bound_published_summary_delivery', original_task_fulfilled=False, publication_contract_satisfied=False, census_scope=loaded['contract']['census_scope'],
        precision_scope=loaded['contract']['precision_scope'], plotted=plotted,
        native_calls=0, generated_events=0, new_limits_derived=False,
        model_exclusion_inferred=False, independent_physics_review=False,
        limits=['The supplied census and production/spin/width hypotheses require independent review.',
                'Digitized values retain their declared approximate precision; null series are unavailable.',
                'Connecting retained plotted points does not add a numerical mass/limit sample; sample ends are not search reach.',
                'Any literal upper-bound display clipping anchors remain excluded from the half-open scientific reporting window.',
                'No statistical combination, acceptance conversion, new limit or low-mass theory extrapolation.'])
    atomic_json(out / 'published-summary.json', result)
    def esc(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    rows = ['| Candidate | Disposition | Range GeV | Reason |', '|---|---|---|---|']
    for candidate in loaded['survey']['candidates']:
        rows.append('| ' + ' | '.join(esc(v) for v in (candidate['id'], candidate['disposition']['state'],
                    candidate['mass_range_gev'], candidate['disposition'].get('reason', ''))) + ' |')
    (out / 'SUMMARY.md').write_text('# Published-limit summary\n\n' + result['census_scope'] + '\n\n' +
        result['precision_scope'] + '\n\n![Published limits](summary.png)\n\n' + '\n'.join(rows) +
        '\n\nAll full source series, including unavailable values and out-of-window points, are in published-summary.json. '
        'The coverage shading means no retained curve in this supplied census. Literal upper-bound clipping anchors, '
        'listed in render_manifest.excluded_boundary_anchors, remain outside a half-open reporting window. '
        'Line endpoints show retained sample support, not the end of search sensitivity. No new limit or model exclusion is derived.\n')
    return result


def _load_requested(task,base):
    """Normal input graph for the original requested summary, not a supplied-curve surrogate."""
    from ravel.workflow.science import regular
    path=regular(task['input'],base)
    raw=bounded_read(path,limit=MAX_DOCUMENT)
    _require(hashlib.sha256(raw).hexdigest()==task['input_sha256'],'requested summary input changed')
    contract=_json(raw)
    fields={'schema_version','kind','parent_task','figure_target','search_census','panels','source_assets','runtime_resources'}
    _require(type(contract) is dict and set(contract)==fields and contract['schema_version']==2 and
             type(contract['schema_version']) is int and contract['kind']=='requested-published-summary/v2',
             'original-task published summary contract/v2 required')
    pins={path:{'path':str(path),'sha256':task['input_sha256'],'size':len(raw)}}
    total=len(raw)
    def read(pin,limit):
        nonlocal total
        _require(type(pin) is dict and set(pin)=={'path','sha256'} and type(pin['path']) is str,'exact summary resource pin required')
        p=regular(pin['path'],path.parent);data=bounded_read(p,limit=limit)
        _require(hashlib.sha256(data).hexdigest()==_sha(pin['sha256']),'requested summary source digest changed')
        if p not in pins:total+=len(data);pins[p]={'path':str(p),'sha256':pin['sha256'],'size':len(data)}
        else:_require(pins[p]['sha256']==pin['sha256'],'conflicting source alias')
        _require(total<=200*1024*1024,'summary source closure exceeds declared 200 MiB')
        return data
    parent=_json(read(contract['parent_task'],MAX_DOCUMENT))
    target=_json(read(contract['figure_target'],MAX_DOCUMENT))
    census=_json(read(contract['search_census'],MAX_DOCUMENT))
    sources=contract['source_assets']
    _require(type(sources) is dict and 1<=len(sources)<=96 and all(type(k) is str and k for k in sources),'explicit original-task source resource census required')
    for pin in sources.values():read(pin,16*1024*1024)
    runtime=contract['runtime_resources']
    _require(type(runtime) is dict and set(runtime)=={'mplhep_source_id','font_source_ids'} and
             type(runtime['mplhep_source_id']) is str and runtime['mplhep_source_id'] in sources and
             type(runtime['font_source_ids']) is list and runtime['font_source_ids'] and
             len(set(runtime['font_source_ids']))==len(runtime['font_source_ids']) and
             set(runtime['font_source_ids'])<=sources.keys(),'prospective exact mplhep/font runtime resource pins required')
    _require(type(contract['panels']) is list and 1<=len(contract['panels'])<=4,'bounded panel contracts required')
    panels={}
    for row in contract['panels']:
        _require(type(row) is dict and set(row)=={'id','summary'} and type(row['id']) is str and
                 row['id'] not in panels,'unique panel source contract required')
        _require(type(row['summary']) is dict and set(row['summary'])=={'path','sha256'},'closed panel resource pin required')
        panel_path=regular(row['summary']['path'],path.parent)
        loaded=_load({'schema_version':1,'input':str(panel_path),'input_sha256':row['summary']['sha256']},path.parent)
        panels[row['id']]=loaded
        for pin in loaded['input_snapshot']:
            p=Path(pin['path'])
            if p not in pins:total+=pin['size'];pins[p]=pin
            else:_require(pins[p]==pin,'conflicting panel/source input pin')
        _require(total<=200*1024*1024,'combined summary source closure exceeds declared bound')
    declaration=validate_requested_summary(target,parent,census,panels,set(sources),contract['parent_task']['sha256'])
    return {'contract':contract,'parent':parent,'figure_contract':target,'search_census':census,
            'panels':panels,'declaration':declaration,'input_snapshot':list(pins.values()),'input_source':str(path)}


def _run_requested(task,base,out):
    from ravel.workflow.state_io import atomic_json
    from ravel.plotting.summary_overlay import render_summary_panels
    from ravel.plotting.figure_target import attach_summary_delivery,verify_summary_delivery
    loaded=_load_requested(validate(task),base)
    out=Path(out)
    _require(not out.exists() and not out.is_symlink() and not any(p.is_symlink() for p in out.parents), 'fresh requested-summary output required')
    out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/'search-census.json',loaded['search_census'])
    atomic_json(out/'source-references.json',loaded['figure_contract']['references'])
    atomic_json(out/'original-request.json',loaded['parent'])
    for identity,panel in loaded['panels'].items():
        # IDs are labels only, not filesystem names supplied by the caller.
        number=list(loaded['panels']).index(identity)+1
        atomic_json(out/f'panel-{number}.json',{k:panel[k] for k in ['audit','survey','manifest','render_manifest','complete_series_rows','coverage_interpretation','window','input_snapshot']})
    plotted=render_summary_panels(loaded['panels'],loaded['figure_contract'],str(out/'summary'))
    evidence=plotted['publication_evidence']
    source_assets=loaded['contract']['source_assets'];runtime=loaded['contract']['runtime_resources']
    from ravel.workflow.science import regular
    def runtime_pin(identity):
        declared=source_assets[identity]
        return {'path':str(regular(declared['path'],Path(loaded['input_source']).parent)),
                'sha256':declared['sha256']}
    expected_mpl=runtime_pin(runtime['mplhep_source_id'])
    observed_mpl=evidence.get('mplhep_module')
    _require(observed_mpl and all(observed_mpl[k]==expected_mpl[k] for k in ['path','sha256']), 'actual mplhep module differs from approved resource')
    fonts=[runtime_pin(i) for i in runtime['font_source_ids']]
    _require(evidence.get('fonts') and all(any(all(f[k]==expected[k] for k in ['path','sha256']) for expected in fonts) for f in evidence['fonts']), 'actual font resources differ from approved inputs')
    def stable_inputs():
        for pin in loaded['input_snapshot']:
            raw=bounded_read(Path(pin['path']),limit=16*1024*1024)
            _require(len(raw)==pin['size'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'source/runtime changed during requested-summary delivery')
    stable_inputs()
    # Existing figure_target declaration/attachment/text-reference composition
    # retains a single primary synthesis target and every contributing reference.
    expected_outputs=plotted.get('output_pins')
    _require(type(expected_outputs) is list and {p.get('path') for p in expected_outputs}=={str(out/'summary.png'),str(out/'summary.pdf')},'renderer image/PDF byte pins required')
    def stable_outputs():
        for pin in expected_outputs:
            raw=bounded_read(Path(pin['path']),limit=16*1024*1024)
            _require(len(raw)==pin['size'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'rendered image bytes changed before delivery')
    stable_outputs()
    figure=attach_summary_delivery(out,loaded['figure_contract'])
    stable_outputs()
    experiments=' and '.join(loaded['figure_contract']['request']['experiments'])
    gallery=['# Contributing published references','', 'This is a description-only synthesis target of published '+experiments+' results; no official combined figure is claimed.','']
    for candidate in loaded['figure_contract']['candidates']:
        gallery.append('## '+candidate['experiment']+' '+candidate['id'])
        gallery.append(candidate['disposition']+': '+candidate['reason'])
        for rid in candidate['reference_ids']:
            ref=next(r for r in loaded['figure_contract']['references'] if r['id']==rid)
            origin=loaded['contract']['source_assets'][ref['source_id']]
            gallery.append(ref['paper']+' '+ref['version']+' '+ref['figure_or_table']+' — '+ref['caption']+'; source '+origin['path']+' SHA256 '+origin['sha256'])
        gallery.append('')
    (out/'SOURCE-GALLERY.md').write_text('\n'.join(gallery)+'\n')
    attachments=[]
    for name in ['summary.png','summary.pdf','figure_target.json','search-census.json','source-references.json','summary-reference-composite.png','SOURCE-GALLERY.md']:
        raw=bounded_read(out/name,limit=16*1024*1024)
        _require(raw,'required requested-summary delivery is empty')
        attachments.append({'name':name,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
    fulfillment={'status':'delivered_pending_review','parent_task_sha256':loaded['contract']['parent_task']['sha256'],
        'request':loaded['figure_contract']['request'],'candidate_ids':loaded['declaration']['candidate_ids'],
        'attachments':attachments,'publication_evidence':evidence,'scientific_task_accepted':False,
        'source_census_completeness':'An explicit reviewed discovery census is retained; scientific exhaustiveness/applicability require the independent role decision, not a producer flag.'}
    result={'kind':'published-limit-summary','status':'passed','physics_validated':False,
        'claim_scope':'source_bound_requested_summary_delivery','new_limits_derived':False,
        'model_exclusion_inferred':False,'native_calls':0,'generated_events':0,
        'figure_contract':loaded['figure_contract'],'figure_target_lifecycle':figure,
        'panels':plotted['panels'],'task_fulfillment':fulfillment,'input_snapshot':loaded['input_snapshot'],
        'limits':['No acceptance conversion, statistical combination or newly derived exclusion.',
                  'Different model/production/width/branching conventions remain separate panels.',
                  'Source review and literal graph checks cannot certify a complete literature census or hypothesis applicability.']}
    stable_inputs()
    stable_outputs()
    verify_summary_delivery(result,out)
    atomic_json(out/'task-fulfillment.json',fulfillment)
    atomic_json(out/'published-summary.json',result)
    (out/'SUMMARY.md').write_text('# Requested published-search summary\n\n'+loaded['parent']['prompt']+'\n\n![Summary](summary.png)\n\n'
        'Published 95% CL source limits only. Model/production panels retain their independent conventions. '
        'The original request, every candidate disposition, source reference and literal full series are retained. '
        'Delivery is pending independent task/physics review; no new limit, statistical combination or automatic current-census claim.\n')
    return result


# Collaboration names checked in a parent prompt. A request may name any other
# experiment, but it must keep every one of these that the original prompt names.
KNOWN_EXPERIMENTS = ('ATLAS', 'CMS', 'LHCb', 'ALICE', 'Belle II', 'BaBar', 'BESIII', 'CDF', 'D0',
                     'NA62', 'NA64', 'FASER', 'MoEDAL', 'ALEPH', 'DELPHI', 'OPAL', 'ZEUS')
REQUEST_FIELDS = {'model', 'resonance', 'decay', 'experiments', 'window'}
BASIS_FIELDS = ['model', 'resonance', 'spin', 'decay', 'production', 'width', 'quantity', 'unit',
                'energy_tev', 'branching_convention']


def _mentions(text, phrase):
    import re
    return re.search(r'(?<![\w])' + re.escape(phrase) + r'(?![\w])', text, re.I) is not None


def _process_named(prompt, resonance, decay):
    """The prompt states resonance -> decay, in arrow or 'decaying to' wording."""
    import re
    text = prompt.replace('′', "'").replace('→', '->').replace('⇒', '=>')
    forms = {resonance, resonance.replace("'", 'prime'), re.sub(r'prime$', "'", resonance)}
    names = '|'.join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    channel = r'\s*'.join(re.escape(ch) for ch in decay if not ch.isspace())
    link = r'(?:->|=>|\bdecay(?:s|ing)?\s+(?:in)?to\b|\bto\b)'
    return re.search(r'(?<![\w])(?:' + names + r')\s*' + link + r'\s*' + channel + r'(?![\w])', text, re.I) is not None


def validate_requested_summary(target, parent, census, panels, source_ids, parent_sha256):
    """Bind a supplied census and panels to the original summary question.

    The request declares a model, a process (resonance and decay, with an optional
    spin), an experiment set and a mass window. Each panel declares its basis. The
    original prompt and parent targets bound these declarations: nothing is narrowed
    or replaced. No truth or census authority transfers to the caller's declaration.
    """
    from ravel.plotting.figure_manifest import summary_recipe
    def keys(row, expected):
        _require(type(row) is dict and set(row) == set(expected), 'closed search-summary declaration required')
    def text(x):
        _require(type(x) is str and 0 < len(x.strip()) <= 4000, 'explicit bounded summary fact required')
    def number(x):
        _require(type(x) in (int, float) and math.isfinite(x), 'finite summary fact required')
        return x
    keys(target, ['schema_version', 'figure_class', 'parent_task_sha256', 'request', 'panels', 'candidates',
                  'references', 'census_as_of'])
    _require(type(target['schema_version']) is int and target['schema_version'] == 2,
             'multisource figure target/v2 required')
    recipe = summary_recipe(target['figure_class'])
    _require(target['parent_task_sha256'] == parent_sha256 and parent.get('task_mode') == 'summary_plot',
             'exact original summary task must be bound')
    prompt = parent.get('prompt'); text(prompt)
    req = target['request']
    _require(type(req) is dict and REQUEST_FIELDS <= set(req) <= REQUEST_FIELDS | {'spin'},
             'closed search-summary declaration required')
    for k in ('model', 'resonance', 'decay'):
        text(req[k])
    spin = req.get('spin')
    _require(spin is None and 'spin' not in req or type(spin) is int and spin >= 0,
             'declared requested spin must be a nonnegative integer')
    _require(_process_named(prompt, req['resonance'], req['decay']),
             'original requested process must be named in the parent prompt')
    parent_targets = parent.get('targets') or {}
    parent_model = parent_targets.get('model')
    if isinstance(parent_model, list):
        model_bound = req['model'] in parent_model
    elif parent_model is not None:
        model_bound = parent_model == req['model']
    else:
        model_bound = _mentions(prompt, req['model'])
    _require(model_bound, 'requested model cannot be narrowed/replaced by the curve manifest')
    experiments = req['experiments']
    _require(type(experiments) is list and experiments and all(type(e) is str and e.strip() for e in experiments)
             and experiments == sorted(set(experiments)), 'sorted unique requested experiment set required')
    named = {e for e in KNOWN_EXPERIMENTS if _mentions(prompt, e)}
    _require(all(_mentions(prompt, e) for e in experiments) and named <= set(experiments),
             'original experiment scope must be preserved')
    window = req['window']; keys(window, ['lo_gev', 'hi_gev', 'upper_inclusive'])
    lo, hi = number(window['lo_gev']), number(window['hi_gev'])
    bounds = [float(b) for b in (lo, hi) if b > 0]
    masses = parent_targets.get('masses_gev')
    _require(0 <= lo < hi and type(window['upper_inclusive']) is bool and type(masses) is list and
             sorted(float(number(m)) for m in masses) == bounds,
             'original requested mass window must be preserved')
    keys(census, ['schema_version', 'kind', 'as_of', 'experiments', 'candidate_ids', 'searches', 'source_review_ids'])
    _require(census['schema_version'] == 1 and type(census['schema_version']) is int and
             census['kind'] == 'official-search-census' and census['as_of'] == target['census_as_of'] and
             census['experiments'] == experiments, 'current supplied discovery census must match requested experiments/date')
    _require(type(census['searches']) is list and len(experiments) <= len(census['searches']) <= 64,
             'explicit discovery operations for every requested experiment required')
    discovered, searched = set(), set()
    for search in census['searches']:
        keys(search, ['experiment', 'source_id', 'locator', 'query', 'candidate_ids'])
        _require(search['experiment'] in experiments and search['source_id'] in source_ids,
                 'official discovery source must be in the declared input closure')
        text(search['locator']); text(search['query'])
        _require(type(search['candidate_ids']) is list and all(type(i) is str for i in search['candidate_ids']),
                 'literal discovered candidate identities required')
        discovered.update(search['candidate_ids']); searched.add(search['experiment'])
    _require(searched == set(experiments) and type(census['source_review_ids']) is list and
             census['source_review_ids'] and set(census['source_review_ids']) <= source_ids,
             'every requested discovery route and independent source-interpretation input required')
    def requested_process(basis):
        return (basis['resonance'] == req['resonance'] and basis['decay'] == req['decay'] and
                (spin is None or basis['spin'] == spin))
    declared_panels = target['panels']
    _require(type(declared_panels) is list and 1 <= len(declared_panels) <= 4,
             'one to four explicit model/production panels required')
    pindex = {}
    for p in declared_panels:
        keys(p, ['id', 'role', 'model_basis', 'axes', 'caption', 'relation_to_request'])
        text(p['id']); text(p['caption']); text(p['relation_to_request'])
        _require(p['id'] not in pindex and p['role'] in ['requested_model', 'alternative_model'],
                 'unique typed summary panels required')
        basis = p['model_basis']; keys(basis, BASIS_FIELDS)
        for k in ['model', 'production', 'width', 'quantity', 'unit', 'branching_convention']:
            text(basis[k])
        _require(type(basis['spin']) is int and basis['spin'] >= 0 and requested_process(basis) and
                 number(basis['energy_tev']) > 0, 'explicit requested-process panel basis/units required')
        if p['role'] == 'requested_model':
            _require(basis['model'] == req['model'], 'requested-model panel changed model')
        keys(p['axes'], ['x', 'y', 'x_label', 'y_label'])
        _require(p['axes']['x'] == 'linear' and p['axes']['y'] in ['linear', 'log'] and
                 'GeV' in p['axes']['x_label'] and '[' + basis['unit'] + ']' in p['axes']['y_label'],
                 'explicit mass/limit axes and units required')
        loaded = panels.get(p['id'])
        _require(loaded is not None and loaded['window'] == window, 'panel and original mass window differ')
        mt = loaded['manifest']['target_basis']
        _require(mt['model'] == basis['model'] and mt['quantity'] == basis['quantity'] and
                 mt['sqrt_s'] == f"{basis['energy_tev']:g} TeV",
                 'actual rendered panel quantity/model/energy must match declaration')
        pindex[p['id']] = p
    _require(set(pindex) == set(panels) and any(p['role'] == 'requested_model' for p in pindex.values()),
             'all actual panels and the requested-model panel required')
    references = target['references']
    _require(type(references) is list and 1 <= len(references) <= 128, 'multisource reference census required')
    refs = {}
    for ref in references:
        keys(ref, ['id', 'source_id', 'paper', 'version', 'figure_or_table', 'caption'])
        for k in ['id', 'paper', 'version', 'figure_or_table', 'caption']:
            text(ref[k])
        _require(ref['id'] not in refs and ref['source_id'] in source_ids, 'unique pinned primary references required')
        refs[ref['id']] = ref
    rows = target['candidates']
    _require(type(rows) is list and 1 <= len(rows) <= 64, 'complete supplied candidate census required')
    ids = [r.get('id') for r in rows if type(r) is dict]
    _require(len(ids) == len(rows) and len(set(ids)) == len(ids) and set(ids) == set(census['candidate_ids']) == discovered,
             'no discovery candidate may disappear between census and figure declaration')
    joins = set()
    for row in rows:
        keys(row, ['id', 'experiment', 'reference_ids', 'mass_range_gev', 'model_basis', 'disposition', 'reason',
                   'panel_id', 'curve_id'])
        text(row['id']); text(row['reason'])
        _require(row['experiment'] in experiments and type(row['reference_ids']) is list and
                 row['reference_ids'] and set(row['reference_ids']) <= refs.keys(),
                 'located primary evidence for every disposition required')
        span = row['mass_range_gev']
        _require(type(span) is list and len(span) == 2 and 0 < number(span[0]) < number(span[1]),
                 'source-bound published search reach required')
        basis = row['model_basis']; keys(basis, BASIS_FIELDS)
        for k in ['model', 'resonance', 'decay', 'production', 'width', 'quantity', 'unit', 'branching_convention']:
            text(basis[k])
        _require(type(basis['spin']) is int and basis['spin'] >= 0 and number(basis['energy_tev']) > 0,
                 'source spin/energy required')
        overlap = span[1] >= lo and (span[0] < hi or window['upper_inclusive'] and span[0] == hi)
        eligible = requested_process(basis) and overlap
        state = row['disposition']
        _require(state in ['plotted', 'crosscheck', 'alternative_panel', 'out_of_range', 'incompatible'],
                 'unresolved/partial candidate cannot qualify requested summary delivery')
        if state == 'out_of_range':
            _require(not overlap, 'out-of-range disposition actually overlaps request')
        if state == 'incompatible':
            _require(not eligible, 'eligible requested-process candidate needs its own compatible panel; '
                                   'no silent model conversion or global exclusion')
        if state in ['plotted', 'crosscheck', 'alternative_panel']:
            p = pindex.get(row['panel_id'])
            _require(p is not None and basis == p['model_basis'], 'incompatible production/model/width/BR cannot share one panel')
            _require(state != 'alternative_panel' or p['role'] == 'alternative_model', 'alternative interpretation must be labelled separately')
            loaded = panels[row['panel_id']]
            curve = next((c for c in loaded['manifest']['curves'] if c['survey_id'] == row['curve_id']), None)
            _require(curve is not None and curve['draw'] != 'none', 'declared published quantity has no actual plotted source series')
            _require((curve['draw'] == 'crosscheck') == (state == 'crosscheck'), 'superseded crosscheck must stay visibly distinct')
            candidate = next((c for c in loaded['survey']['candidates'] if c['id'] == row['curve_id']), None)
            _require(candidate is not None and candidate['experiment'] == row['experiment'] and candidate['mass_range_gev'] == span,
                     'figure candidate and actual supplied panel census must agree')
            join = (row['panel_id'], row['curve_id'])
            _require(join not in joins, 'duplicate candidate-to-curve join'); joins.add(join)
        else:
            _require(row['panel_id'] is None and row['curve_id'] is None, 'excluded candidate cannot carry a hidden plotted join')
    actual = {(pid, c['survey_id']) for pid, l in panels.items() for c in l['manifest']['curves'] if c['draw'] != 'none'}
    _require(joins == actual, 'complete actual drawn population must map to requested figure/census')
    return {'recipe': recipe, 'request': deepcopy(req), 'candidate_ids': ids, 'panel_ids': list(pindex),
            'reference_ids': list(refs), 'task_contract_complete': True, 'scientific_task_accepted': False,
            'qualification': 'Complete supplied discovery/quantity/panel contract; independent current-census/model '
                             'interpretation and actual delivery review remain required.'}
