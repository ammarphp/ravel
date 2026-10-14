"""Ordinary complete marked-template shape and profiling consumers.

No new optimizer or MC likelihood: compose the bound source/auxiliary blocks,
absolute response provider and existing analytic profiler. Numerical delivery
never establishes detector calibration, a global minimum, intervals or CLs.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

from ravel.physics import finite_mc_model as fm, marked_response as marks
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock, _read, compact
from ravel.physics.published_background import BackgroundAuxBlock, inspect_workspace
from ravel.physics.marked_response_provider import MarkedResponseProvider
from ravel.physics.joint_analytic import AnalyticPublishedJoint, AnalyticJointProfiler
from ravel.physics.joint_profile import WorkBudget
from ravel.physics.quantities import _keys, _number, _text
from ravel.workflow.state_io import atomic_json

FAMILY = 'complete_marked_categories'


def validate(task):
    _keys(task, ('input', 'response_family'), label='marked joint analysis task')
    _text(task['input'], 'input')
    if task['response_family'] != FAMILY:
        raise ValueError('unknown marked joint response family')
    return deepcopy(task)


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label+' outside explicit resource envelope')
    return value


def _strengths(values, upper):
    if not isinstance(values, list) or not 1 <= len(values) <= 32:
        raise ValueError('one to 32 declared strengths required')
    result = [_number(v, 'profile strength') for v in values]
    if len(set(result)) != len(result) or any(not 0 <= v <= upper for v in result):
        raise ValueError('unique strengths in declared search domain required')
    return result


def prepare(document):
    _keys(document, ('schema_version', 'model_id', 'assumptions', 'limits', 'cases'), label='marked analysis')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('unsupported marked analysis schema')
    _text(document['model_id'], 'model id')
    if not isinstance(document['assumptions'], list) or len(document['assumptions']) < 2:
        raise ValueError('explicit new response-law and independence assumptions required')
    for value in document['assumptions']: _text(value, 'assumption')
    limits = document['limits']
    _keys(limits, ('execution_seconds', 'fit_budget', 'maximum_free_coordinates', 'capture_bytes', 'result_bytes', 'journal_bytes'), label='analysis limits')
    _integer(limits['execution_seconds'], 1, 21600, 'stage wall seconds')
    _integer(limits['maximum_free_coordinates'], 1, 256, 'free coordinates')
    for key, ceiling in [('capture_bytes',32*1024**2),('result_bytes',64*1024**2),('journal_bytes',64*1024**2)]:
        _integer(limits[key], 1024, ceiling, key)
    WorkBudget(limits['fit_budget'], maximum_wall_seconds=300)
    if not isinstance(document['cases'], list) or not 1 <= len(document['cases']) <= 16:
        raise ValueError('one to 16 explicit source cases required')
    cases = []; fits = shape_calls = covariances = 0
    for case in document['cases']:
        _keys(case, ('id', 'workspace', 'measurement', 'background_policy', 'background_source', 'MC', 'response', 'configuration', 'signal_samples', 'source_bin_map', 'mu_domain', 'source_bound_semantics', 'data', 'requests'), label='complete analysis case')
        _text(case['id'], 'case id'); cases.append(case['id']); _text(case['measurement'], 'measurement')
        if case['background_policy'] not in ('separable_signal_mc', 'rebuild_background_mc_from_source'):
            raise ValueError('explicit source auxiliary policy required')
        if (case['background_source'] is None) != (case['background_policy'] == 'separable_signal_mc'):
            raise ValueError('background rebuild requires its exact source, separable policy has no replacement')
        _keys(case['mu_domain'], ('initial','upper'), label='mu domain')
        mu = case['mu_domain']
        if not 0 < _number(mu['initial'],'initial strength') < _number(mu['upper'],'strength search cap') <= 1000:
            raise ValueError('physical zero lower bound and explicit finite numerical strength cap required')
        if not isinstance(case['source_bound_semantics'],dict): raise ValueError('explicit source bound semantics required')
        for name, row in case['source_bound_semantics'].items():
            _text(name,'source coordinate'); _keys(row,('lower','upper'),label='source bound semantics')
            if any(v not in ('physical','numerical') for v in row.values()): raise ValueError('physical/numerical bound meaning required')
        if case['data'] is not None:
            _keys(case['data'],('main','source_auxiliary','MC_auxiliary'),label='complete repeated data')
        requests = case['requests']; names = []
        if not isinstance(requests,list) or not 1 <= len(requests) <= 16: raise ValueError('bounded explicit analysis requests required')
        for req in requests:
            _text(req.get('id'),'request id'); names.append(req['id'])
            kind = req.get('kind')
            if kind == 'shape':
                _keys(req, ('id','kind','mu','latent','source_points'), label='shape request')
                if not 0 <= _number(req['mu'],'shape strength') <= mu['upper']: raise ValueError('shape strength outside declared domain')
                if not isinstance(req['source_points'],list) or not 1 <= len(req['source_points']) <= 32: raise ValueError('bounded complete shape points required')
                shape_calls += len(req['source_points']); covariances += 1
            elif kind in ('profile','finite_mc_comparison'):
                _keys(req, ('id','kind','strengths','fixed_source','fixed_latent'), label='profile request')
                _strengths(req['strengths'],mu['upper'])
                if not isinstance(req['fixed_source'],dict): raise ValueError('explicit conditional source map required')
                if kind == 'finite_mc_comparison' and not isinstance(req['fixed_latent'],dict): raise ValueError('comparison needs complete explicit fixed-latent reference')
                fits += (1+len(req['strengths']))*(2 if kind == 'finite_mc_comparison' else 1)
            else: raise ValueError('unknown marked analysis operation')
        if len(set(names)) != len(names): raise ValueError('duplicate request id')
    if len(set(cases)) != len(cases): raise ValueError('duplicate case id')
    if fits > 64 or shape_calls > 256: raise ValueError('declared aggregate mathematical population too large')
    if fits and limits['execution_seconds'] < fits*limits['fit_budget']['wall_seconds']:
        raise ValueError('stage envelope must contain every declared per-fit ceiling plus caller-chosen setup margin')
    return deepcopy(document), {'fit_calls':fits,'shape_density_calls':shape_calls,'shared_covariance_calls':covariances}


def _capture(task, base):
    validate(task); path = fm._regular(task['input'],base); raw = _read(path)
    document, counts = prepare(fm._load_bytes(raw)); captured = {str(path):raw}; bound = []
    def pin(value, *, decode=True):
        _keys(value,('path','sha256'),label='source pin')
        child = fm._regular(value['path'],path.parent); data = _read(child)
        if hashlib.sha256(data).hexdigest() != value['sha256']: raise ValueError('changed marked analysis input')
        if str(child) in captured and captured[str(child)] != data: raise ValueError('input changed during capture')
        captured[str(child)] = data
        if sum(map(len,captured.values())) > document['limits']['capture_bytes']: raise ValueError('aggregate input ceiling')
        return child, fm._load_bytes(data) if decode else data
    for case in document['cases']:
        workspace_path, workspace = pin(case['workspace']); inspect_workspace(workspace,case['signal_samples'])
        mc_path, _ = pin(case['MC']); mc = MCAuxiliaryBlock({'input':str(mc_path)},path.parent)
        for source in mc.contract()['inputs']: pin({'path':source['path'],'sha256':source['sha256']},decode=False)
        if mc.document()['mc_design']['kind'] != 'fixed_n_categories': raise ValueError('complete marked provider requires fixed-N categories')
        response_path, response = pin(case['response']); response = marks.prepare(response)
        if any(r['kind']=='shape' and len(r['source_points'])*len(response['destination_ids']) > 512 for r in case['requests']):
            raise ValueError('shared template covariance exceeds 512 complete coordinates')
        background_source = None if case['background_source'] is None else pin(case['background_source'])[1]
        bound.append((case, workspace, mc, response_path, background_source))
    if sum(map(len,captured.values())) > document['limits']['capture_bytes']: raise ValueError('aggregate input ceiling')
    for name, data in captured.items():
        if _read(fm._regular(name,path.parent)) != data: raise ValueError('source changed during capture')
    return document, counts, captured, bound


def inputs(task, base_dir, *, _session=None):
    return [Path(p) for p in _capture(task,base_dir)[2]]


def resource_bounds(task, base_dir):
    document, counts, _, _ = _capture(task,base_dir)
    limits = document['limits']; fits = counts['fit_calls']; budget = limits['fit_budget']
    return {'processes':2,'mathematical_workers':1,'native_children':0,'threads':1,'generated_events':0,'calibration_trials':0,
            'model_compilations':len(document['cases']), **counts, 'maximum_optimizer_attempts':3*fits,
            **{'maximum_'+key:fits*budget[key] for key in ('objective_calls','gradient_calls','feasibility_lp_calls','stationarity_lp_calls')},
            'maximum_free_coordinates':limits['maximum_free_coordinates'],'execution_seconds':limits['execution_seconds'],
            'per_fit_wall_seconds':budget['wall_seconds'],'capture_bytes':limits['capture_bytes'],'result_bytes':limits['result_bytes'],'journal_bytes':limits['journal_bytes'],
            'enforcement':'Charged existing fit budget plus ordinary external stage supervisor; no hard active native-thread/RSS guarantee.'}


def execution_seconds(task, base_dir):
    return _capture(task,base_dir)[0]['limits']['execution_seconds']


def validate_requests(case, source, mc_document):
    """Pure compiled-contract validation, before any requested numerical call."""
    domains = source['active_parameter_domains']; names = source['active_parameter_names']
    _keys(case['source_bound_semantics'],names,label='complete source bound semantics')
    classes = mc_document['classes']; ids = [c['id'] for c in classes]
    def source_point(point, complete):
        if not isinstance(point,dict) or (set(point) != set(names) if complete else not set(point) <= set(names)):
            raise ValueError('complete source point or named conditional subset required')
        for name,value in point.items():
            v = _number(value,'source coordinate'); row = domains[name]
            if not row['bounds'][0] <= v <= row['bounds'][1] or row['fixed'] and v != row['initial']:
                raise ValueError('source bounds or genuine fixed flags violated')
    def probabilities(point):
        _keys(point,ids,label='complete fixed category probabilities')
        p = [_number(point[n],'probability') for n in ids]
        if any(v<0 or v>1 for v in p) or abs(math.fsum(p)-1)>1e-12:
            raise ValueError('literal complete probability simplex required; never renormalized')
    for req in case['requests']:
        if req['kind']=='shape':
            probabilities(req['latent'])
            for point in req['source_points']: source_point(point,True)
        else:
            source_point(req['fixed_source'],False)
            if req['fixed_latent'] is not None: probabilities(req['fixed_latent'])


def construct(document, case, workspace, mc, response_path, background_source):
    background = BackgroundAuxBlock(workspace,case['signal_samples'],measurement=case['measurement'],policy=case['background_policy'],
                                    model_id=document['model_id']+'/'+case['id']+'/background',background_source=background_source)
    validate_requests(case,background.contract(),mc.document())
    provider = MarkedResponseProvider(path=response_path,sha256=case['response']['sha256'],configuration=case['configuration'])
    joint = AnalyticPublishedJoint(background,mc,source_workspace=workspace,signal_samples=case['signal_samples'],source_bin_map=case['source_bin_map'],
                                  model_id=document['model_id']+'/'+case['id'],response_assumptions=document['assumptions'],response_provider=provider)
    if case['data'] is not None: joint.validate_data(case['data'])
    profiler = AnalyticJointProfiler(joint,background,mc,mu_domain=case['mu_domain'],source_bound_semantics=case['source_bound_semantics'],rate_caps={},
                                    max_free_dimension=document['limits']['maximum_free_coordinates'],fit_wall_seconds_limit=300)
    return joint,provider,profiler


def profile_contrast(free, conditional):
    """Raw NLLs remain intact. Nesting is a separate diagnostic, never a clamp."""
    result = {'raw_twice_delta_nll':None,'twice_delta_nll':None,'passed':False,'global_optimum_certified':False}
    if free.get('verified') is not True or conditional.get('verified') is not True: return result
    values = [free.get('nll'),conditional.get('nll')]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values): return result
    delta = 2*(values[1]-values[0]); result['raw_twice_delta_nll'] = delta
    result['passed'] = delta >= -1e-5
    if result['passed']: result['twice_delta_nll'] = max(0.,delta)
    return result


def run(task, base_dir, output_dir):
    started = time.monotonic(); document, counts, captured, bound = _capture(task,base_dir)
    candidate = Path(output_dir).absolute()
    if any(Path(p).is_relative_to(candidate) for p in captured): raise ValueError('output overlaps captured source')
    out = fm._admit_output(candidate); limits = document['limits']; deadline = started+limits['execution_seconds']
    report = {'schema_version':1,'kind':'complete_marked_joint_analysis','status':'failed','physics_validated':False,
              'global_optimum_certified':False,'coverage_qualified':False,'calibration_trials':0,'generated_events':0,
              'planned_counts':counts,'calls':{'compilations':0,'fits':0,'shape_densities':0,'covariances':0},
              'assumptions':document['assumptions'],'cases':[], 'scope':'Supplied complete marked law: shape propagation and bounded stationary profile diagnostics; no detector, globality, interval or CLs qualification.'}
    for case,*_ in bound:
        report['cases'].append({'id':case['id'],'status':'pending','requests':[{'id':r['id'],'kind':r['kind'],'status':'pending','fits':[]} for r in case['requests']]})
    sequence = 0; previous = None; size = 0; journal = out/'marked-analysis.jsonl'
    def save():
        if len(compact(report)) > limits['result_bytes']: raise ValueError('analysis result ceiling')
        atomic_json(out/'marked-analysis.json',report)
    def record(state, identity, payload):
        nonlocal sequence,previous,size
        row = {'sequence':sequence,'previous_sha256':previous,'state':state,'identity':identity,'payload':payload}
        raw = compact(row)
        if size+len(raw)+1 > limits['journal_bytes']: raise ValueError('analysis journal ceiling')
        with journal.open('ab') as stream: stream.write(raw+b'\n'); stream.flush()
        size += len(raw)+1; sequence += 1; previous = hashlib.sha256(raw).hexdigest()
    def check():
        if time.monotonic() >= deadline: raise TimeoutError('marked analysis stage budget exhausted')
    def call(kind, identity, fn, serialize=lambda x:x):
        check(); report['calls'][kind] += 1; record('running',identity,{'kind':kind}); save()
        try: result = fn()
        except Exception as error:
            record('failed',identity,{'type':type(error).__name__,'message':str(error)}); raise
        # Save the literal oracle/fit return before wall, nesting, covariance or other derived checks.
        record('returned',identity,serialize(result)); check(); return result
    save()
    try:
        for (case,workspace,mc,path,bgsource), row in zip(bound,report['cases']):
            identity = case['id']; row['status']='running'; save()
            joint,provider,profiler = call('compilations',identity+'/compile',lambda:construct(document,case,workspace,mc,path,bgsource),lambda x:x[0].contract())
            row['joint_contract']=joint.contract(); save()
            supplied = {} if case['data'] is None else {'main_observations':case['data']['main'],'source_auxiliary_observations':case['data']['source_auxiliary'],'mc_observations':case['data']['MC_auxiliary']}
            for req,result_row in zip(case['requests'],row['requests']):
                request_id=identity+'/'+req['id'];result_row['status']='running';save()
                if req['kind']=='shape':
                    result_row['points']=[]
                    for i,point in enumerate(req['source_points']):
                        value=call('shape_densities',request_id+'/'+str(i),lambda:joint.evaluate_with_gradient(point,req['latent'],mu=req['mu'],**supplied))
                        result_row['points'].append({'source':deepcopy(point),'latent':deepcopy(req['latent']),'mu':req['mu'],'raw':value});save()
                    covariance=call('covariances',request_id+'/shared-template-covariance',lambda:provider.shared_template_covariance(req['source_points'],req['latent']))
                    result_row['template_covariance_mu1']=covariance
                    result_row['covariance_note']='MC estimator covariance at fixed supplied probabilities/source points only; no nuisance posterior, detector uncertainty, or added likelihood factor.'
                    result_row['status']='passed' if all(v['raw'].get('finite') is True for v in result_row['points']) else 'failed'
                else:
                    lanes=[('profile',req['fixed_latent'])] if req['kind']=='profile' else [('fixed_latent',req['fixed_latent']),('finite_mc',None)]
                    for lane,latent in lanes:
                        free=None
                        for mu in [None,*req['strengths']]:
                            fitrow={'lane':lane,'fixed_mu':mu,'fixed_source':deepcopy(req['fixed_source']),'fixed_latent':deepcopy(latent),'status':'running','result':None,'contrast':None}
                            result_row['fits'].append(fitrow);save()
                            value=call('fits',request_id+'/'+lane+'/'+str(mu),lambda:profiler.fit(fixed_mu=mu,data=case['data'],budget=limits['fit_budget'],fixed_source=req['fixed_source'],fixed_latent=latent,wall_hook=lambda:time.monotonic()>=deadline))
                            fitrow.update(status='returned',result=value);save()
                            if mu is None: free=value
                            else: fitrow['contrast']=profile_contrast(free,value)
                            save()
                    result_row['status']='passed' if all(r['result'].get('verified') is True and (r['contrast'] is None or r['contrast']['passed']) for r in result_row['fits']) else 'failed'
                    result_row['comparison_note']='Each lane retains its full normalized NLL and its own free-strength baseline. No ordering of recentered curves, confidence limits, or globality is inferred.'
                save()
            row['status']='passed' if all(r['status']=='passed' for r in row['requests']) else 'failed';save()
        check()
        for name,raw in captured.items():
            if _read(fm._regular(name,base_dir)) != raw: raise ValueError('analysis input changed before completion')
        report['status']='passed' if all(r['status']=='passed' for r in report['cases']) else 'failed'
    except Exception as error:
        report['error']={'type':type(error).__name__,'message':str(error)}
    report['elapsed_seconds']=time.monotonic()-started
    report['journal']={'records':sequence,'bytes':size,'head_sha256':previous}
    save();return report
