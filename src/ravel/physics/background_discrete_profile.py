"""Serial native fixed-candidate scans and an explicit supplied discrete envelope.

Uses the existing full regional Combine adapter. No Python optimizer, candidate
pruning, nuisance removal, additional asymptotics or auto-selected complexity
penalty. This is not an automatic RooMultiPdf implementation: native grid fits
are compared using the documented absolute-NLL recipe, with an explicit common
law and supplied candidate-dependent NLL correction.
"""
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import struct
import time

from ravel.physics import background_construction as builder
from ravel.physics import native_likelihood as native
from ravel.physics import statistical_construction as regional
from ravel.workflow.state_io import atomic_json, read_json


def validate(task):
    regional._keys(task, {'input'}, 'discrete background task')
    regional._text(task['input'],'discrete background input')


def _configuration(task, base, *, _session=None):
    from ravel.workflow.science import regular
    validate(task)
    cp=regular(task['input'],base,_session=_session)
    read=lambda p: _session.read_document(p) if _session is not None else read_json(p)
    cfg=read(cp)
    regional._keys(cfg, {'schema_version','construction','candidates','overhead_seconds','max_seconds'}, 'discrete background input')
    if type(cfg['schema_version']) is not int or cfg['schema_version'] != 1: raise ValueError('discrete schema 1 required')
    sp=native._pin(cfg['construction'],cp.parent,_session=_session); spec=read(sp)
    population=builder.construct(spec)
    if type(cfg['candidates']) is not list or len(cfg['candidates']) != len(population): raise ValueError('complete ordered candidate population required')
    all_inputs=[cp,sp]; entries=[]; common=None
    for declaration,expected in zip(cfg['candidates'],population):
        regional._keys(declaration,{'id','input'},'native candidate binding')
        if declaration['id'] != expected['id']: raise ValueError('candidate order or identity changed')
        p=native._pin(declaration['input'],cp.parent,_session=_session)
        child={'input':str(p)}
        original=native._configuration(child,p.parent,_session=_session)
        config=original[0]
        native._validate_absolute_scan(config)
        construction=native._pin(config['model']['construction'],p.parent,_session=_session)
        if read(construction) != expected['document']: raise ValueError('native candidate changed the complete lowered likelihood')
        # Equal observations, auxiliary law, baseline terms and POI are already
        # guaranteed by exact lowering; runtime and grid must also be identical.
        signature={'runtime':config['runtime'],'fit':config['fit']}
        if common is None: common=signature
        if signature != common: raise ValueError('native runtime, minimizer or full grid differs across candidates')
        all_inputs += native.inputs(child,p.parent,_session=_session)
        entries.append({'id':expected['id'],'task':child,'base':p.parent,'config':config,'penalty_nll':expected['penalty_nll']})
    overhead=cfg['overhead_seconds']; total=cfg['max_seconds']
    if type(overhead) is not int or not 1 <= overhead <= 3600 or type(total) is not int or total != overhead+sum(e['config']['max_seconds'] for e in entries) or total > 86400:
        raise ValueError('whole population plus explicit custody budget required')
    all_inputs += [regular(p,base,_session=_session) for p in (__file__,builder.__file__)]
    return cfg,spec,entries,list(dict.fromkeys(all_inputs))


def inputs(task, base, *, _session=None):
    return _configuration(task,base,_session=_session)[3]


def execution_seconds(task, base, *, _session=None):
    return _configuration(task,base,_session=_session)[0]['max_seconds']


def _validation_inputs(task, base, session):
    return inputs(task,base,_session=session)


def _validation_execution_seconds(task, base, session):
    return execution_seconds(task,base,_session=session)


def resource_bounds(task, base, *, _session=None):
    cfg,_,entries,_=_configuration(task,base,_session=_session)
    return {'processes':3,'maximum_mathematical_workers':1,'native_commands_serial':True,
            'candidate_fits':len(entries),'profile_grid_points_per_candidate':entries[0]['config']['fit']['points'],
            'generated_events':0,'max_seconds':cfg['max_seconds'],
            'candidate_seconds':[e['config']['max_seconds'] for e in entries]}


def _float32_cell(value):
    """Closed IEEE round-to-nearest cell of a literal finite Float_t value.

    Closure conservatively includes midpoint ties. It is a compatibility
    enclosure, not reconstruction of the original double or a precision bound
    for the native function. Native Float_t conversion semantics still require
    source/runtime qualification. No arbitrary coordinate tolerance is used.
    """
    import math
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('finite native Float_t observation required')
    try:
        packed=struct.pack('>f',value); represented=struct.unpack('>f',packed)[0]
    except (OverflowError,struct.error):
        raise ValueError('native observation is not representable as finite Float_t')
    if represented != value:
        raise ValueError('native parameter/mean branch is not a literal Float_t observation')
    if value == 0:
        half=F(1,2**150);return -half,half
    sign=-1 if value < 0 else 1
    bits=struct.unpack('>I',struct.pack('>f',abs(value)))[0]
    q=F(abs(value)); previous=F(struct.unpack('>f',struct.pack('>I',bits-1))[0])
    # At max finite, use the next mathematical grid value rather than infinity.
    following=q+(q-previous) if bits==0x7f7fffff else F(struct.unpack('>f',struct.pack('>I',bits+1))[0])
    lo,hi=(previous+q)/2,(q+following)/2
    return (lo,hi) if sign==1 else (-hi,-lo)


def native_state_admission(document, rows):
    """Admit native saved state/means, without calling rounded state exact."""
    coordinates={p['name']:p['bounds'] for p in document['parameters'] if not p['fixed']}
    coordinates.update({'ravel_aux_'+str(i):bounds for i,bounds in enumerate(document['auxiliary']['eta_bounds'])})
    mean_names=['ravel_mean_'+str(i) for i in range(len(document['bins']))]
    for i,row in enumerate(rows):
        if (set(coordinates)|set(mean_names))-set(row):
            raise ValueError('native full state or full-mean branches missing at row '+str(i))
        for name,bounds in coordinates.items():
            lo,hi=_float32_cell(row[name])
            # The existing bridge writes binary64 bounds with .17g. Preserve
            # source tokens; test compatibility with that actual native box.
            lower,upper=[F(float(regional._q(v))) for v in bounds]
            if hi < lower or lo > upper:
                raise ValueError('native Float_t coordinate incompatible with declared domain: '+name+' at row '+str(i))
        for name in mean_names:
            _float32_cell(row[name])
            if row[name] <= 0:
                raise ValueError('native full total mean is not strictly positive: '+name+' at row '+str(i))
    return {'rows':len(rows),'coordinate_bounds':coordinates,'positive_total_mean_branches':mean_names,
            'domain_rule':'Literal Float_t closed nearest-rounding cell intersects original native binary64 domain; no clipping',
            'total_mean_rule':'Saved source-defined native full-mean functions are strictly positive at every returned point',
            'rounded_coordinates_are_exact_native_state':False,
            'independent_full_native_density_parity_qualified':False}


def envelope(spec, results, fit):
    """Compare literal complete native rows. Missing/failed candidates refuse.

    The reference is the smallest RETAINED corrected NLL, including returned
    native best-fit rows. This is a finite-result envelope, not a proof of a
    continuous global minimum or an interval/coverage determination.
    """
    population=builder.construct(spec)
    if type(results) is not list or len(results) != len(population): raise ValueError('complete candidate results required')
    curves=[]; all_values=[]; common_grid=None
    for expected,record in zip(population,results):
        regional._keys(record,{'id','result'},'candidate return')
        result=record['result']
        if record['id'] != expected['id'] or result.get('status') != 'passed' or result.get('physics_validated') is not False or result.get('fit') != fit:
            raise ValueError('failed, changed, or missing candidate result blocks the envelope')
        raw=result['inference']['rows']; checked=native.extract_rows(raw,fit)
        # Accept the native object or its exact persisted JSON representation.
        # Do not canonicalize caller data: that could conceal mixed-key changes.
        checked_json=json.loads(json.dumps(checked,allow_nan=False))
        if not checked['passed'] or result['inference'] not in (checked,checked_json) or 'absolute_nll_rows' not in checked:
            raise ValueError('native raw rows and checked inference must agree exactly')
        document=expected['document']
        nuisance_names=[p['name'] for p in document['parameters'] if p['role'] != 'poi' and not p['fixed']]
        nuisance_names += ['ravel_aux_'+str(i) for i in range(len(document['auxiliary']['names']))]
        if any(set(nuisance_names)-set(row) for row in raw):
            raise ValueError('complete floating nuisance branches are required at every native grid/best point')
        state_admission=native_state_admission(document,raw)
        penalty=F(expected['penalty_nll']); grid=[]; best=[]
        for row,absolute in zip(raw,checked['absolute_nll_rows']):
            value=F(absolute['returned_sum_rational'])+penalty; all_values.append(value)
            item={'coordinate':row[fit['poi']],'row_index':absolute['row_index'],
                  'native_sum_rational':absolute['returned_sum_rational'],'penalty_nll':str(penalty),'corrected_nll_rational':str(value)}
            (best if abs(row['quantileExpected']+1) <= 1e-5 else grid).append(item)
        grid.sort(key=lambda r:r['coordinate'])
        coordinates=[r['coordinate'] for r in grid]
        if common_grid is None: common_grid=coordinates
        if coordinates != common_grid: raise ValueError('actual native binary64 grid coordinates differ across candidates')
        curves.append({'id':expected['id'],'grid':grid,'native_best':best,
                       'floating_background_coefficients':expected['floating_background_coefficients'],
                       'floating_nuisance_branches':nuisance_names,
                       'native_state_admission':state_admission,
                       'fixed_source_coordinates':{p['name']:p['initial'] for p in document['parameters'] if p['fixed']}})
    reference=min(all_values); points=[]
    for i,x in enumerate(common_grid):
        values=[F(c['grid'][i]['corrected_nll_rational']) for c in curves]; value=min(values)
        points.append({'coordinate':x,'corrected_nll_rational':str(value),
            'selected_candidates':[c['id'] for c,v in zip(curves,values) if v==value],
            'twice_delta_from_retained_minimum_rational':str(2*(value-reference))})
    return {'curves':curves,'points':points,'retained_minimum_nll_rational':str(reference),
        'all_candidates_included':True,'global_minimum_qualified':False,'coverage_qualified':False,
        'automatic_roo_multipdf_traversal':False,'penalty':spec['penalty'],
        'scope':'Finite native fixed-candidate grid envelope, conditional on the entire supplied likelihood/census/penalty; numerical precision and calibration require independent qualification.'}


def _hashes(paths):
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def write_report(result, out):
    """Ordinary Check-In 2 links all candidates, including unexecuted/failed."""
    out=Path(out)
    report={'status':result['status'],'physics_validated':False,
            'population':result['population'],'returns':result['returns'],
            'envelope':result['envelope'],'limitations':result['limitations'],
            'error':result.get('error')}
    atomic_json(out/'background-model-comparison.json',report)
    lines=['# Supplied background candidate comparison','',
           'Delivery: '+result['status']+'. Native optimizer and statistical calibration require independent review.','',
           '| Candidate | Execution |','|---|---|']
    for row in result['population']:
        lines.append('| '+row['id']+' | '+row['status']+' |')
    lines += ['', 'All raw native returns, full grid branches, explicit correction and selected ties are in background-model-comparison.json.',
              'A failed or missing candidate prevents an envelope. No candidate is discarded, no confidence interval is inferred, and no historical result is replaced.','']
    (out/'background-model-comparison.md').write_text('\n'.join(lines))
    return [{'stem':'background-model-comparison','files':['background-model-comparison.json','background-model-comparison.md'],
             'normalization':'Absolute returned native NLL plus explicitly supplied candidate correction; same full observation/auxiliary law'}]


def run(task, base, out):
    """One serial native job per declared candidate; no retry or hidden pruning."""
    out=Path(out).absolute(); started=time.monotonic()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('fresh nonsymlink discrete output required')
    cfg,spec,entries,paths=_configuration(task,base)
    before=_hashes(paths); population=builder.construct(spec); out.mkdir(parents=True)
    report={'status':'failed','physics_validated':False,'scope':'Full supplied binned background candidate population with native profiling',
        'population':[{'id':e['id'],'status':'not_executed'} for e in entries],
        'returns':[],'envelope':None,'original_inputs':before,'ending_inputs':None,
        'limitations':['No optimizer, covariance, globality, coverage or physical background-family qualification is implied.',
                       'Absolute NLL comparison uses one unchanged normalized observation/auxiliary law; its native fidelity requires execution witnesses.',
                       'Supplied complexity correction is explicit; an information criterion is not a coverage theorem.',
                       'Native deltaNLL leaves have finite precision. Rational reduction preserves only the returned values.']}
    save=lambda: atomic_json(out/'background-discrete-profile.json',report)
    save()
    try:
        for i,e in enumerate(entries):
            # Reserve the entire declared child allowance and remaining shared
            # custody overhead; a late start refuses rather than silently shrinking
            # native budgets or exceeding the admitted whole-worker ceiling.
            elapsed=time.monotonic()-started
            remaining=sum(x['config']['max_seconds'] for x in entries[i:])
            if elapsed+remaining >= cfg['max_seconds']: raise ValueError('whole-population budget cannot cover remaining declared candidate ceilings')
            report['population'][i]['status']='running'; save()
            result=native.run(e['task'],e['base'],out/e['id'])
            # Retain every returned object BEFORE dependent validation/comparison.
            report['returns'].append({'id':e['id'],'result':result})
            report['population'][i]['status']='returned'; save()
            if result.get('status') != 'passed': raise ValueError('native candidate failed: '+e['id'])
            native_state_admission(population[i]['document'],result['inference']['rows'])
            report['population'][i]['status']='passed'; save()
        report['envelope']=envelope(spec,report['returns'],entries[0]['config']['fit']); save()
        after=_hashes(paths); report['ending_inputs']=after
        if after != before: raise ValueError('background/native input bytes changed')
        if time.monotonic()-started > cfg['max_seconds']: raise ValueError('whole-population deadline exceeded')
        report['status']='passed'; save()
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        report['error']={'type':type(exc).__name__,'message':str(exc)}
        report['elapsed_seconds']=time.monotonic()-started; save()
    return report
