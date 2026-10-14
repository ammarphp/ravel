"""SFitterAgents domain review, composed with ordinary scientific judgment.

Domain protocol adapted from MIT-licensed SFitterAgents 6072a79e. Upstream
instructions are source material, not operational authority. This module has
no runner, approval, vote store, or retry ledger; it uses the existing ones.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct

from . import decision_case, scientific_judgment as judgment, sfitter_workflow as workflow
from . import execution
from .validation_io import identity

CONCERNS = {
    'traceability': ('extraction', 'Locate every extracted bin in its primary source'),
    'uncertainty_roundtrip': ('extraction', 'Recompute the declared uncertainty decomposition'),
    'observable_semantics': ('extraction', 'Recheck integrated/differential, fiducial/total and normalization meanings'),
    'sm_baseline': ('sm_template', 'Compare independent SM baseline and declared perturbative order'),
    'coupling_contamination': ('parameterization', 'Inspect actual generated coupling references and model-specific zeroing'),
    'coefficient_baseline': ('parameterization', 'Recompute signed polynomial scan predictions and the independent SM point'),
    'theory_doublecount': ('sm_template', 'Audit physical uncertainty sources across experimental and theory channels'),
    'datacard_roundtrip': ('datacard', 'Check whole-population composition; native parser roundtrip needs executed evidence'),
    'documentation': ('datacard', 'Retain inputs, source scripts, conventions and unresolved limitations'),
}
SOURCES = ('sfitteragents/.claude/skills/sf-deep-verify/SKILL.md',
           'sfitteragents/.claude/skills/sf-reinterpret/SKILL.md',
           'sfitteragents/.claude/skills/sf-parameterize/SKILL.md',
           'sfitteragents/prompts/sf-discipline.md',
           'sfitteragents/.claude/agents/sf-reviewer.md')
METHODS = {'traceability':{'traceability'}, 'uncertainty_roundtrip':{'quadrature'},
    'observable_semantics':{'regime_consistency'}, 'sm_baseline':{'vector_agreement'},
    'coupling_contamination':{'coupling_census'}, 'coefficient_baseline':{'polynomial','vector_agreement'},
    'theory_doublecount':{'uncertainty_inventory'}, 'datacard_roundtrip':{'datacard_composition','native_parser_roundtrip'},
    'documentation':{'document_inventory'}}
LIMITS = [workflow.BOUNDARY,
    'A prescribed check is not an executed result; blindspot triage is not verification.',
    'Criteria and independence premises require scientific review. No universal R-squared, interference or Taylor criterion is imposed.',
    'Distinct native score -Q and exp(-Q), RFit, correlations, truncation and exact normalized polynomial semantics remain unchanged.',
    'Warnings remain in every report. An owning-phase draft or adequate test design is not executed repair closure.']


def _keys(value, fields, name): judgment._keys(value, set(fields), name)
def _text(value, name): workflow.sfitter_native._text(value, name)
def _version(value):
    if type(value) is not int or value != 1: raise ValueError('integer schema_version 1 required')
def _pin(pin, base):
    _keys(pin, ('path','sha256'), 'source pin')
    return {'path': str(workflow.custody._pin(pin, base)), 'sha256': pin['sha256']}
def _read(pin, base): return judgment._read_pin(_pin(pin, base))
def _bytes(pin, base):
    """Same bounded authenticated-buffer pattern as judgment, for text sources."""
    pin = _pin(pin, base); path = judgment._path(pin['path']); before = identity(path.stat())
    if not 0 < before[3] <= 16*1024**2: raise ValueError('bounded text source required')
    with path.open('rb') as stream:
        if identity(os.fstat(stream.fileno())) != before: raise ValueError('source changed before read')
        raw = stream.read(before[3]+1)
        if identity(os.fstat(stream.fileno())) != before: raise ValueError('source changed during read')
    if (identity(path.stat()) != before or len(raw) != before[3]
            or hashlib.sha256(raw).hexdigest() != pin['sha256']): raise ValueError('consumed text source changed')
    return raw
def _ref(ref, base, pins):
    _keys(ref, ('artifact','location'), 'located source')
    pin = _pin(ref['artifact'], base); pins[pin['path']] = pin
    return decision_case.pointer(_read(pin, base), ref['location'])
def _vector(value, n=None):
    if type(value) is not list or not value or (n is not None and len(value) != n): raise ValueError('complete vector required')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in value): raise ValueError('finite real vector required')
    return value
def _criterion(value, base, pins):
    _keys(value, ('absolute','relative','justification'), 'declared comparison criterion')
    for key in ('absolute','relative'):
        if type(value[key]) not in (int,float) or not math.isfinite(value[key]) or value[key] < 0: raise ValueError('nonnegative finite tolerance required')
    if not _ref(value['justification'], base, pins): raise ValueError('located criterion justification required')
    return value
def _agreement(actual, expected, criterion):
    actual=_vector(actual); expected=_vector(expected,len(actual))
    residual=_vector([a-b for a,b in zip(actual,expected)],len(actual))
    bands=_vector([criterion['absolute']+criterion['relative']*abs(e) for e in expected],len(actual))
    return residual, all(abs(r) <= band for r,band in zip(residual,bands))


def _zeroing(record, target, allowed, base, pins):
    """Compare a full DIM6 card census at an explicit preparation/runtime stage."""
    from ravel.physics import scoped
    parameter_recipe=scoped.parameter_recipe
    sp=judgment._pin(scoped.__file__);pins[sp['path']]=sp
    _keys(record, ('model_source','stage','provenance','parameter_card','execution','dim6_parameters','parameter_locations','parameter_operators','active_values'), 'version-specific parameter observation')
    _text(record['model_source'],'model version')
    if record['model_source']!=target['model_source'] or record['stage'] not in ('pre_activation','final_scan') or record['provenance'] not in ('constructed_input','returned_parameter_card'): raise ValueError('explicit model/stage/provenance required')
    names=record['dim6_parameters']
    if type(names) is not list or not names or len(set(names))!=len(names): raise ValueError('complete declared DIM6 census required')
    _keys(record['parameter_locations'],names,'DIM6 parameter locations'); _keys(record['parameter_operators'],names,'version-specific parameter/operator map')
    active=record['active_values']
    if type(active) is not dict or not set(active)<=set(names) or record['stage']=='pre_activation' and active: raise ValueError('pre-activation zeroing has no active scan parameters')
    for name,value in active.items():
        operators=record['parameter_operators'][name]
        if type(value) not in (int,float) or not math.isfinite(value) or type(operators) is not list or not operators or not set(operators)<=set(allowed): raise ValueError('active parameter must map only to the declared scanned coordinates with finite exact value')
    locations={}
    for name,row in record['parameter_locations'].items():
        _keys(row, ('block','indices'), 'DIM6 card address')
        if type(row['block']) is not str or not row['block'].lower().startswith('dim6') or type(row['indices']) is not list or not row['indices'] or any(type(i) is not int for i in row['indices']): raise ValueError('exact DIM6 block/index address required')
        address=(row['block'].lower(),tuple(row['indices']))
        if address in locations: raise ValueError('aliased DIM6 parameter address')
        locations[address]=name
        operators=record['parameter_operators'][name]
        if type(operators) is not list or len(set(operators))!=len(operators) or not set(operators)<=set(target['eft']['basis']): raise ValueError('declared full-basis parameter mapping required')
    pin=_pin(record['parameter_card'],base); pins[pin['path']]=pin
    rows=parameter_recipe(_bytes(pin,base).decode('utf8')); block=None; observed={}
    for row in rows:
        if row[0]=='block':
            if len(row)<2 or type(row[1]) is not str: raise ValueError('malformed parameter block')
            block=row[1];continue
        if row[0]=='decay':block=None;continue
        if block is None or not block.startswith('dim6'):continue
        if len(row)<2 or any(type(x) not in (int,float) or not math.isfinite(x) or int(x)!=x for x in row[:-1]) or type(row[-1]) not in (int,float) or not math.isfinite(row[-1]): raise ValueError('unparsed finite DIM6 row')
        address=(block,tuple(int(x) for x in row[:-1]))
        if address in observed: raise ValueError('duplicate DIM6 card address')
        observed[address]=row[-1]
    if set(observed)!=set(locations): raise ValueError('observed complete DIM6 card census differs from declared model map')
    values={locations[a]:value for a,value in observed.items()}
    mismatches=[name for name,value in values.items() if value!=active.get(name,0.)]
    observed_return=False
    if record['provenance']=='constructed_input':
        if record['execution'] is not None: raise ValueError('constructed input cannot borrow native observation')
    else:
        declaration=record['execution']; _keys(declaration, ('rundir','stage','attempt_record'), 'actual returned parameter-card execution')
        root=judgment.review._root(declaration['rundir']); stage=declaration['stage']; _text(stage,'native stage')
        if execution.stage_errors(root,stage): raise ValueError('returned parameter card requires current successful stage custody')
        actual=execution.load_execution(root)['stages'][stage]; rp=_pin(declaration['attempt_record'],base)
        if Path(rp['path'])!=judgment._path(root/actual['attempt_record']) or _read(rp,base)!=actual: raise ValueError('returned card needs this exact immutable native attempt')
        outputs=[execution.resolve_path(root,path,output=True) for path in actual['outputs']]
        if not any(Path(pin['path'])==o or o.is_dir() and Path(pin['path']).is_relative_to(o) for o in outputs): raise ValueError('parameter card is not a returned ordinary output')
        pins[rp['path']]=rp; observed_return=True
        if execution.stage_errors(root,stage): raise ValueError('native parameter observation changed during read')
    return {'stage':record['stage'],'provenance':record['provenance'],'values':values,'expected_active_values':active,
            'unexpected_parameter_values':mismatches,'native_observed':observed_return,
            'execution':record['execution'],
            'scope':'card values and declared version-specific operator map; no compiled coupling or model-validity certification'}


def _workflow(pin, base, pins):
    """Consume authenticated handoff documents, rather than parsing a second read."""
    pin = _pin(pin, base); pins[pin['path']] = pin; request = _read(pin, base); base = Path(pin['path']).parent
    workflow.validate(request)
    manifest=_read(request['upstream_tree']['manifest'],base)
    _keys(manifest, ('schema_version','files'), 'exact upstream census'); _version(manifest['schema_version'])
    if manifest['files']!=workflow._known(): raise ValueError('authenticated upstream census differs')
    root, paths = workflow._knowledge(request, base, 'datacard')
    for path in paths:
        p = workflow._pin(path); pins[p['path']] = p
    known = workflow._known()
    for rel in SOURCES:
        p = {'path': str(root/rel), 'sha256': known[rel]}; _bytes(p, base); pins[p['path']] = p
    docs = {}; next_phase = None
    for phase in workflow.PHASES:
        if phase not in request['handoffs']: next_phase = phase; break
        p = _pin(request['handoffs'][phase], base); pins[p['path']] = p
        doc = _read(p, base)
        workflow._handoff(request, doc, Path(p['path']).parent, phase)
        if phase=='conventions' and 'transport_result' in doc['payload']:
            rp=_pin(doc['payload']['transport_request'],Path(p['path']).parent)
            workflow.eft_conventions.verify_result({'request':rp['path']},Path(rp['path']).parent,
                _read(doc['payload']['transport_result'],Path(p['path']).parent))
        docs[phase] = doc
        for nested in workflow._refs(doc):
            q = _pin(nested, Path(p['path']).parent); pins[q['path']] = q
    if set(request['handoffs']) != set(docs): raise ValueError('ordered genuine handoffs required')
    for p in request['sources']:
        q = _pin(p, base); pins[q['path']] = q
    return request, docs, next_phase, base


def _compute(method, data, target, observables, base, pins):
    n = sum(len(o['bins']) for o in target['observables'] if o['ID'] in observables)
    if method == 'prescribed':
        _keys(data, ('description','evidence'), 'unexecuted prescribed check'); _text(data['description'],'check description')
        if type(data['evidence']) is not list: raise ValueError('explicit evidence list required')
        evidence = [_ref(r,base,pins) for r in data['evidence']]
        return 'inconclusive', {'description':data['description'],'available_evidence':evidence,'executed':False}
    if method == 'traceability':
        _keys(data, ('rows',), 'bin traceability'); wanted={(o['ID'],b) for o in target['observables'] if o['ID'] in observables for b in o['bins']}
        if type(data['rows']) is not list: raise ValueError('traceability rows required')
        seen=set(); outputs=[]
        for row in data['rows']:
            _keys(row, ('observable','bin','source','confidence'), 'located extraction row')
            key=(row['observable'],row['bin'])
            if key not in wanted or key in seen or row['confidence'] not in ('strong','medium','weak','unknown'): raise ValueError('traceability census differs')
            seen.add(key); value=_ref(row['source'],base,pins)
            outputs.append({**row,'located_value':value})
        return ('pass' if seen==wanted and all(r['located_value'] is not None and r['confidence']!='unknown' for r in outputs) else 'inconclusive'), {'rows':outputs,'missing':sorted(wanted-seen),'confidence_is_declared':True}
    if method == 'regime_consistency':
        _keys(data, ('rows',), 'observable semantics'); rows=data['rows']; wanted=[o for o in target['observables'] if o['ID'] in observables]
        if type(rows) is not list or len(rows)!=len(wanted): raise ValueError('whole semantic population required')
        status='pass'
        for row,ob in zip(rows,wanted):
            _keys(row, ('ID','representation','normalization','unit','acceptance','luminosity_included','source'), 'observable meaning')
            if row['ID']!=ob['ID'] or row['acceptance'] not in ('fiducial','total','unknown') or type(row['luminosity_included']) is not bool: raise ValueError('semantic identities invalid')
            if not _ref(row['source'],base,pins): raise ValueError('located semantic source required')
            if any(row[k]!=ob[k] for k in ('representation','normalization','unit')) or row['normalization']=='normalized' and row['luminosity_included']: status='fail'
            elif row['acceptance']=='unknown' and status!='fail': status='inconclusive'
        return status, {'rows':rows,'normalization_rule':'native normalized multi-bin groups; absolute singleton','luminosity_cancellation':'prescribed only for declared normalized observable'}
    if method == 'document_inventory':
        _keys(data, ('rows',), 'documentation coverage'); rows=data['rows']; wanted=set(observables); seen=set()
        if type(rows) is not list: raise ValueError('documented population required')
        for row in rows:
            _keys(row, ('observable','measurement','model','method','uncertainties','limitations'), 'scientific documentation')
            if row['observable'] not in wanted or row['observable'] in seen: raise ValueError('documentation identity differs')
            seen.add(row['observable'])
            for key in ('measurement','model','method','uncertainties','limitations'):
                if _ref(row[key],base,pins) is None: raise ValueError('located documentation field required')
        return ('pass' if seen==wanted else 'inconclusive'), {'rows':rows,'missing_observables':sorted(wanted-seen),'documentation_is_not_physics_verification':True}
    if method == 'quadrature':
        _keys(data, ('components','total','criterion','independence'), 'uncertainty roundtrip')
        if not _ref(data['independence'],base,pins): raise ValueError('independence premise must be located')
        total=_vector(_ref(data['total'],base,pins),n)
        if type(data['components']) is not list or not data['components']: raise ValueError('declared components required')
        components=[_vector(_ref(p,base,pins),n) for p in data['components']]
        if any(x<0 for row in [total,*components] for x in row): raise ValueError('uncertainties must be nonnegative')
        computed=[math.sqrt(sum(row[i]**2 for row in components)) for i in range(n)]
        residual,okay=_agreement(computed,total,_criterion(data['criterion'],base,pins))
        return ('pass' if okay else 'fail'), {'computed':computed,'reported':total,'residual':residual,'independence_is_a_source_premise':True}
    if method == 'vector_agreement':
        _keys(data, ('actual','reference','criterion'), 'independent baseline comparison')
        a,b=data['actual'],data['reference']
        if _pin(a['artifact'],base)['path']==_pin(b['artifact'],base)['path']: raise ValueError('baseline requires a separate reference artifact')
        actual=_vector(_ref(a,base,pins),n); expected=_vector(_ref(b,base,pins),n)
        residual,okay=_agreement(actual,expected,_criterion(data['criterion'],base,pins))
        return ('pass' if okay else 'fail'), {'actual':actual,'independent_reference':expected,'residual':residual}
    if method == 'polynomial':
        _keys(data, ('observable','offset','linear','square','mixed','points','bin_widths','criterion'), 'signed scan check')
        matches=[o for o in target['observables'] if o['ID']==data['observable']]
        if len(matches)!=1 or observables!=[data['observable']]: raise ValueError('one complete native group per polynomial check required')
        ob=matches[0]; n=len(ob['bins']); basis=target['eft']['basis']; eft=target['eft']
        offset=_vector(data['offset'],n); widths=_vector(data['bin_widths'],n)
        if any(w<=0 for w in widths): raise ValueError('positive bin widths required')
        _keys(data['linear'],basis,'complete linear coefficients')
        _keys(data['square'],basis if eft['quadratic'] else (),'declared square coefficients')
        expected={'x'.join(p) for p in eft['mixed_pairs']}; _keys(data['mixed'],expected,'declared signed mixed coefficients')
        for coefficients in (data['linear'],data['square'],data['mixed']):
            for row in coefficients.values(): _vector(row,n)
        criterion=_criterion(data['criterion'],base,pins); rows=[]
        if type(data['points']) is not list or not data['points'] or len(data['points'])>4096: raise ValueError('bounded actual scan points required')
        for point in data['points']:
            _keys(point, {'coefficients','observed'} | ({'mc_errors'} if 'mc_errors' in point else set()), 'actual scan point'); x=_vector(point['coefficients'],len(basis)); obs=_vector(point['observed'],n); values=dict(zip(basis,x))
            errors=_vector(point['mc_errors'],n) if 'mc_errors' in point else None
            if errors is not None and any(e<0 for e in errors): raise ValueError('nonnegative actual Monte Carlo errors required')
            pred=[offset[i]+sum(values[k]*v[i] for k,v in data['linear'].items())+sum(values[k]**2*v[i] for k,v in data['square'].items())+
                  sum(values[a]*values[b]*data['mixed']['x'.join((a,b))][i] for a,b in eft['mixed_pairs']) for i in range(n)]
            _vector(pred,n)
            norm=sum(p*w for p,w in zip(pred,widths)) if ob['normalization']=='normalized' else 1.
            if not math.isfinite(norm) or norm<=0: rows.append({'coefficients':x,'status':'fail','reason':'nonpositive or nonfinite native normalization','raw_prediction':pred}); continue
            pred=[p/norm for p in pred]; residual,okay=_agreement(pred,obs,criterion)
            rows.append({'coefficients':x,'status':'pass' if okay else 'fail','prediction':pred,'observed':obs,'residual':residual,'normalization':norm,
                'mc_errors':errors,'statistical_precision':'source-supplied; criterion adequacy requires review' if errors is not None else 'not_supplied'})
        return ('pass' if all(r['status']=='pass' for r in rows) else 'fail'), {'points':rows,'domain':'only supplied points; no globality or interpolation-power claim','normalization':'exact native polynomial ratio; no Taylor expansion'}
    if method == 'coupling_census':
        _keys(data, ('matrix_sources','coupling_map','allowed_operators','zeroing_record'), 'generated coupling check')
        if type(data['matrix_sources']) is not list or not data['matrix_sources']: raise ValueError('actual generated matrix sources required')
        mapping=_ref(data['coupling_map'],base,pins); allowed=data['allowed_operators']
        if type(allowed) is not list or not set(allowed)<=set(target['eft']['basis']) or len(set(allowed))!=len(allowed): raise ValueError('declared allowed operator scope required')
        used=set()
        for p in data['matrix_sources']:
            q=_pin(p,base); pins[q['path']]=q; lines=_bytes(q,base).decode('utf8').splitlines()
            body='\n'.join(line.split('!')[0] for line in lines if not line.startswith(('C','c','*')))
            used.update(re.findall(r'\bGC_\d+\b',body,re.I))
        used={x.upper() for x in used}; unexpected=[]; unknown=[]
        if type(mapping) is not dict: raise ValueError('model-specific coupling map required')
        for name in sorted(used):
            if name not in mapping: unknown.append(name); continue
            row=mapping[name]; _keys(row, ('kind','operators'), 'coupling meaning')
            if (row['kind'] not in ('qcd','eft','other') or type(row['operators']) is not list
                    or not set(row['operators'])<=set(target['eft']['basis']) or row['kind']=='qcd' and row['operators']
                    or row['kind']=='eft' and not row['operators']): raise ValueError('explicit coupling meaning required')
            if row['kind']=='other' or not set(row['operators'])<=set(allowed): unexpected.append(name)
        zeroing=_zeroing(_ref(data['zeroing_record'],base,pins),target,allowed,base,pins)
        if zeroing['native_observed']:
            declaration=zeroing['execution'];root=judgment.review._root(declaration['rundir'])
            record=execution.load_execution(root)['stages'][declaration['stage']]
            outputs=[execution.resolve_path(root,path,output=True) for path in record['outputs']]
            for source in data['matrix_sources']:
                path=Path(_pin(source,base)['path'])
                if not any(path==o or o.is_dir() and path.is_relative_to(o) for o in outputs): raise ValueError('coupling matrix must be an actual output of the observed native attempt')
            if execution.stage_errors(root,declaration['stage']): raise ValueError('generated coupling evidence changed')
        status='fail' if unexpected or zeroing['unexpected_parameter_values'] else 'inconclusive' if unknown or not used or not zeroing['native_observed'] else 'pass'
        return status, {'couplings':sorted(used),'unexpected':unexpected,'unmapped':unknown,'parameter_card_check':zeroing,
            'mapping_and_parameter_completeness':'source premises; not compiled-model certification'}
    if method == 'uncertainty_inventory':
        _keys(data, ('rows',), 'physical uncertainty inventory'); seen={}; overlaps=[]
        if type(data['rows']) is not list or not data['rows']: raise ValueError('source inventory required')
        for row in data['rows']:
            _keys(row, ('physical_source','channel','name','observables','source','included_independently'), 'uncertainty source')
            for key in ('physical_source','name'): _text(row[key],key)
            if row['channel'] not in ('experimental','theory') or type(row['included_independently']) is not bool or type(row['observables']) is not list or not set(row['observables'])<=set(observables): raise ValueError('uncertainty population/channel invalid')
            if not _ref(row['source'],base,pins): raise ValueError('physical source provenance required')
            for ob in row['observables']:
                key=(row['physical_source'],ob); prior=seen.setdefault(key,[])
                if prior and row['included_independently'] and any(r['included_independently'] for r in prior): overlaps.append({'source':row['physical_source'],'observable':ob,'names':[r['name'] for r in prior]+[row['name']]})
                prior.append(row)
        covered={o for row in data['rows'] for o in row['observables']}
        return ('fail' if overlaps else 'pass' if covered==set(observables) else 'inconclusive'), {'independently_double_counted':overlaps,'missing_observables':sorted(set(observables)-covered),'physical_source_identity_is_declared':True,'no_name_based_independence_inference':True}
    raise ValueError('unsupported domain recomputation method')


def _native_roundtrip(data, wf, base, pins):
    """Read actual ordinary native outputs; never import upstream/Torch or score."""
    from . import science
    _keys(data, ('rundir','initialized_state','native_request','runtime'), 'executed native parser witness')
    root=judgment.review._root(data['rundir']); plan=science.verify_plan(root); spec=science.execution_spec(root)
    if spec['mode']!='sfitter-native-fit' or execution.stage_errors(root,'science'): raise ValueError('current successful ordinary SFitter attempt required')
    config_path,config=workflow.sfitter_native._load(spec['task'],root)
    wanted=_pin(wf['handoffs']['datacard'],base); card_handoff=_read(wanted,base)['payload']
    if _pin(config['datacard'],config_path.parent)!=_pin(card_handoff['datacard'],Path(wanted['path']).parent): raise ValueError('native parser witness belongs to another card')
    out=root/plan['output_directory']; documents={}
    for name in ('initialized_state','native_request','runtime'):
        pin=_pin(data[name],base)
        expected={'initialized_state':'initialized-state.json','native_request':'request.json','runtime':'runtime.json'}[name]
        if Path(pin['path'])!=judgment._path(out/'native'/expected): raise ValueError('parser witness is not this ordinary output')
        pins[pin['path']]=pin; documents[name]=_read(pin,base)
    request=documents['native_request']; initialized=documents['initialized_state']; runtime=documents['runtime']
    workflow.sfitter_native.validate_runtime(runtime,request)
    origin=next(({'path':p,'sha256':h} for p,h in request['source_files'].items() if p.endswith('/likelihood/full_likelihood.py')),None)
    if origin is None: raise ValueError('initialized native source origin unavailable')
    card=_read(card_handoff['datacard'],Path(wanted['path']).parent); basis=wf['target']['eft']['basis']; bins=sum(len(o['Meas']['data']) for o in card['observations'])
    exporter=workflow.sfitter_native.sfitter_results
    exporter.validate_initialized_state(initialized,basis,origin,bin_count=bins,group_count=len(card['observations']))
    def vector(key):
        record=initialized['native_tensors'][key]
        if record['dtype']!='<f8': raise ValueError('observed float64 native scalar population required')
        raw=exporter.validate_array(record); return list(struct.unpack('<'+'d'*(len(raw)//8),raw))
    # Native singleton normalization stores zero width; other groups use supplied widths.
    expected_meas=[m for ob in card['observations'] for m in ob['Meas']['data']]
    expected_sm=[x for p in card['predictions'] for x in p['data']]
    expected_widths=[x if len(ob['bin_widths'])>1 else 0. for ob in card['observations'] for x in ob['bin_widths']]
    expected_coefficients=[]
    for prediction in card['predictions']:
        for i in range(len(prediction['data'])):
            matrix=[[0.]*(len(basis)+1) for _ in basis]
            for term in prediction['modifiers']:
                parts=term['name'].split('x'); a=basis.index(parts[0]); b=basis.index(parts[1]) if len(parts)==2 else len(basis)
                matrix[a][b]=term['data'][i]
            expected_coefficients.extend(x for row in matrix for x in row)
    comparisons={key:{'expected':value,'observed':vector(key)} for key,value in
        (('measurements',expected_meas),('smeft_offset',expected_sm),('bin_widths',expected_widths),('smeft_coeffs',expected_coefficients))}
    okay=all(row['observed']==row['expected'] and all(math.isfinite(x) for x in row['observed']) for row in comparisons.values())
    if execution.stage_errors(root,'science'): raise ValueError('native evidence changed during parser recomputation')
    # Retain ordinary immutable record and original native configuration pins too.
    state=execution.load_execution(root); record=state['stages']['science']
    for path in (root/record['attempt_record'],root/'inputs/science-plan.json',config_path):
        p=judgment._pin(path); pins[p['path']]=p
    return ('pass' if okay else 'fail'), {'comparisons':comparisons,'attempt_id':record['attempt_id'],
        'native_state':initialized,'scope':'observed measurement/SM/coefficient/width parser roundtrip; no Q/calibration/convergence validation'}


def context(request, base_dir):
    """Recompute the finite review population, preserving missing work and warnings."""
    _keys(request, ('schema_version','id','workflow','stage','regime','checks','required_concerns','check_mapping','claim_scope'), 'SFitter review request')
    _version(request['schema_version']); _text(request['id'],'review id'); _text(request['claim_scope'],'prospective claim scope')
    if request['stage'] not in (*workflow.PHASES,'native_result'): raise ValueError('known owning phase required')
    base=Path(base_dir); pins={}; wf,docs,next_phase,wbase=_workflow(request['workflow'],base,pins)
    if request['stage'] in workflow.PHASES and request['stage'] not in docs: raise ValueError('review requires the actual returned phase handoff')
    if request['stage']=='native_result' and next_phase is not None: raise ValueError('native result requires full prior handoffs')
    rp=_pin(request['regime'],base); pins[rp['path']]=rp; regime=_read(rp,base)
    _keys(regime, ('schema_version','observables','sources'), 'scientific regime'); _version(regime['schema_version'])
    if type(regime['observables']) is not list or len(regime['observables'])!=len(wf['target']['observables']): raise ValueError('complete scientific regime census required')
    for row,ob in zip(regime['observables'],wf['target']['observables']):
        _keys(row, ('ID','acceptance','source'), 'observable regime')
        if row['ID']!=ob['ID'] or row['acceptance'] not in ('fiducial','total','unknown'): raise ValueError('regime identity differs')
        _ref(row['source'],base,pins)
    if type(regime['sources']) is not list or not regime['sources']: raise ValueError('regime needs primary source pins')
    for p in regime['sources']:
        q=_pin(p,base); pins[q['path']]=q
    active=list(CONCERNS); required=request['required_concerns']; mapping=request['check_mapping']
    if type(required) is not list or not required or len(set(required))!=len(required) or not set(required)<=set(active): raise ValueError('explicit unique material concern scope required')
    if type(mapping) is not dict or set(mapping)!=set(required): raise ValueError('every material concern needs original check mapping')
    for ids in mapping.values():
        if type(ids) is not list or not ids or len(set(ids))!=len(ids): raise ValueError('original unique check IDs required')
        for name in ids: _text(name,'check ID')
    if type(request['checks']) is not list or len(request['checks'])>256: raise ValueError('bounded check population required')
    all_ids=[o['ID'] for o in wf['target']['observables']]; results=[]; names=set()
    for check in request['checks']:
        _keys(check, ('id','concern','observables','method','data'), 'domain check')
        _text(check['id'],'check id')
        if check['id'] in names or check['concern'] not in CONCERNS: raise ValueError('duplicate or unknown check')
        names.add(check['id']); obs=check['observables']
        if type(obs) is not list or not obs or len(set(obs))!=len(obs) or not set(obs)<=set(all_ids): raise ValueError('known unique observable coverage required')
        data=_ref(check['data'],base,pins)
        if check['method'] not in METHODS[check['concern']] | {'prescribed'}: raise ValueError('method does not recompute this concern')
        if check['method'] in ('polynomial','vector_agreement'):
            if 'sm_template' not in docs: raise ValueError('actual returned SM template required')
            sm=[r for r in docs['sm_template']['payload']['rows'] if r['ID'] in obs]
            if check['method']=='vector_agreement':
                if _ref(data['actual'],base,pins)!=[x for r in sm for x in r['data']]: raise ValueError('baseline check is not the actual handed-off SM population')
            else:
                if 'parameterization' not in docs or 'extraction' not in docs: raise ValueError('actual signed coefficients and measurement geometry required')
                if len(sm)!=1 or data['offset']!=sm[0]['data']: raise ValueError('scan check uses a different SM baseline')
                prm=next(r for r in docs['parameterization']['payload']['rows'] if r['ID']==data['observable'])
                extr=next(r for r in docs['extraction']['payload']['rows'] if r['ID']==data['observable'])
                coefficients={m['name']:m['data'] for m in prm['modifiers']}
                supplied={**data['linear'],**{k+'x'+k:v for k,v in data['square'].items()},**data['mixed']}
                if supplied!=coefficients or data['bin_widths']!=extr['bin_widths']: raise ValueError('scan check is not the actual handed-off coefficient/geometry population')
        if check['method']=='datacard_composition':
            _keys(data, (), 'deterministic whole-card comparison')
            ready=workflow.ready_native(wf,wbase)
            handoff=docs['datacard']['payload']; parent=Path(_pin(wf['handoffs']['datacard'],wbase)['path']).parent
            card=_read(handoff['datacard'],parent); sem=_read(handoff['semantic_manifest'],parent)
            workflow.sfitter_native.semantic(sem,card,wf['target']['eft']['basis'])
            expected={'observations':[],'predictions':[]}
            for extracted,sm,terms in zip(docs['extraction']['payload']['rows'],docs['sm_template']['payload']['rows'],docs['parameterization']['payload']['rows']):
                ob=deepcopy(extracted); ob['modifiers']=sm['theory_modifiers']; expected['observations'].append(ob)
                expected['predictions'].append({'ID':sm['ID'],'name':sm['name'],'data':sm['data'],'modifiers':terms['modifiers']})
            if card!=expected: raise ValueError('authenticated card is not exact returned handoff composition')
            status,result='pass', {'structural_composition':'pass','native_parser_roundtrip':'not_executed_by_source_preflight','native_input':ready}
        elif check['method']=='native_parser_roundtrip': status,result=_native_roundtrip(data,wf,wbase,pins)
        else: status,result=_compute(check['method'],data,wf['target'],obs,base,pins)
        if check['method']=='regime_consistency':
            acceptance={r['ID']:r['acceptance'] for r in regime['observables']}
            mismatches=[r['ID'] for r in data['rows'] if r['acceptance']!='unknown' and acceptance[r['ID']]!='unknown' and r['acceptance']!=acceptance[r['ID']]]
            if mismatches: status='fail'; result['regime_mismatch']=mismatches
        results.append({**check,'status':status,'recomputation':result})
    concerns=[]
    for name,(owner,description) in CONCERNS.items():
        rows=[r for r in results if r['concern']==name]; covered=set(o for r in rows for o in r['observables']); missing=[o for o in all_ids if o not in covered]
        methods={r['method'] for r in rows}
        method_missing={m:[o for o in all_ids if not any(o in r['observables'] and r['method']==m for r in rows)] for m in sorted(METHODS[name])}
        status='fail' if any(r['status']=='fail' for r in rows) else 'inconclusive' if missing or any(r['status']!='pass' for r in rows) or any(method_missing.values()) else 'pass'
        if name=='observable_semantics' and any(r['acceptance']=='unknown' for r in regime['observables']): status='inconclusive' if status!='fail' else status
        concerns.append({'id':name,'owner_phase':owner,'description':description,'material':name in required,'status':status,
                         'missing_observables':missing,'missing_method_observables':method_missing,'checks':rows,'original_check_ids':mapping.get(name,[])})
    warnings=[{'concern':c['id'],'owner_phase':c['owner_phase'],'status':c['status'],'missing_observables':c['missing_observables']} for c in concerns if c['status']!='pass']
    if any(r['acceptance']=='unknown' for r in regime['observables']): warnings.append({'concern':'observable_semantics','owner_phase':'extraction','status':'inconclusive','reason':'fiducial/total regime unresolved'})
    pins[str(Path(__file__).resolve())]=judgment._pin(__file__)
    for p in list(pins.values()): _pin(p,base) # Fresh final source census; no cross-operation cache.
    triggers=[]
    for ob,r in zip(wf['target']['observables'],regime['observables']):
        triggers.append({'observable':ob['ID'],'acceptance':r['acceptance'],'normalization':ob['normalization'],
            'prescribed_probes':(['width_weighted_exact_polynomial_ratio','luminosity_cancellation'] if ob['normalization']=='normalized' else ['absolute_unit_and_luminosity_convention'])+
                (['same_fiducial_selection_SM_baseline'] if r['acceptance']=='fiducial' else ['total_rate_SM_baseline_no_efficiency_inference'] if r['acceptance']=='total' else ['locate_primary_acceptance_definition'])})
    eft=wf['target']['eft']
    triggers.append({'eft_truncation':'linear_and_declared_square_mixed' if eft['quadratic'] else 'linear_only',
        'mixed_pairs':eft['mixed_pairs'],'prescribed_probes':['model_version_DIM6_zeroing','generated_coupling_inventory','signed_SM_D6_interference','independent_SM_point']+
            (['signed_D6_square_and_mixed_terms'] if eft['quadratic'] else []),'scale_policy':'same_declared_scale; no implicit RGE'})
    return {'schema_version':1,'kind':'sfitter_domain_review','request_sha256':execution.digest(request),'workflow_sha256':execution.digest(wf),
            'stage':request['stage'],'claim_scope':request['claim_scope'],'target':wf['target'],'regime':regime,'phase_handoffs':docs,
            'regime_triggers':triggers,
            'concerns':concerns,'warnings':warnings,'blindspot_triage_only':True,'inputs':sorted(pins.values(),key=lambda p:p['path']),
            'upstream_commit':workflow.sfitter_native.COMMIT,'upstream_license':'MIT; retained original notices',
            'execution_authorized':False,'physics_validated':False,'old_votes_carried':[],'limits':LIMITS}


def _case(report, pin, author):
    pending={'reviewer_id':'unassigned-domain-reviewer','decision':'unresolved','reason':'Fresh independent role must inspect actual artifacts and criterion premises'}
    action='Review only the declared scope '+report['claim_scope']+' for SFitter stage '+report['stage']
    nodes=[{'id':'action','author_id':author,'assertion':action,'rationale':'Raw delivery, test adequacy and scientific result closure are separate actions',
            'material':True,'assumptions':[],'unknowns':[],'anchors':[{'kind':'user_requirement','artifact':pin,'format':'json','location':'/claim_scope','value':report['claim_scope']}],'review':deepcopy(pending)}]; edges=[]
    for i,c in enumerate(report['concerns']):
        if not c['material']: continue # Retained warnings are not premises for a narrower action.
        node='concern'+str(i)
        nodes.append({'id':node,'author_id':author,'assertion':c['description'],'rationale':'Recompute artifacts and independently assess source, regime and criterion; a status is not physics proof',
            'material':c['material'],'assumptions':[{'statement':'Criteria, source identity and independence premises are scientifically adequate for this scope','disposition':'unresolved','reason':'This requires actual role judgment'}],
            'unknowns':[] if c['status']=='pass' else [{'question':'Concern remains '+c['status'],'request':{'kind':'evidence','description':'Owning phase '+c['owner_phase']+' must supply the missing/revised evidence and a fresh review'}}],
            'anchors':[{'kind':'measurement','artifact':pin,'format':'json','location':'/concerns/'+str(i),'value':c}], 'review':deepcopy(pending)})
        edges.append({'parent':'action','child':node,'author_id':author,'rationale':'Material only within the prospective original check/claim scope; preserve other warnings',
                      'review':deepcopy(pending),'request':{'kind':'evidence','description':'Recheck '+c['id']+' in '+c['owner_phase']}})
    nodes[0]['anchors'].append({'kind':'measurement','artifact':pin,'format':'json','location':'','value':report})
    return decision_case.validate_case({'schema_version':1,'action':action,'root':'action','triggers':[{'kind':'high_consequence','reason':'EFT conventions and uncertainty sources change fit interpretation'}],
        'budget':{'max_nodes':len(nodes),'max_depth':1},'nodes':nodes,'edges':edges})


def prepare_role(rundir, request_pin, out, **options):
    """Prepare existing bounded role Graph with complete domain evidence; no dispatch."""
    request_pin=_pin(request_pin,Path(request_pin['path']).parent); request=_read(request_pin,Path(request_pin['path']).parent)
    report=context(request,Path(request_pin['path']).parent)
    root,reg,_,_=judgment._live(rundir)
    for c in report['concerns']:
        for check in c['checks']:
            if check['method']=='native_parser_roundtrip':
                data=_ref(check['data'],Path(request_pin['path']).parent,{})
                if judgment.review._root(data['rundir'])!=root: raise ValueError('native parser evidence must be this exact reviewed run')
    if request['claim_scope'] not in reg['policy']['claim_scopes']: raise ValueError('claim scope not prospectively registered')
    scientific={c['id'] for c in reg['policy']['required_checks'] if c['kind']=='scientific'}
    if not set(x for ids in request['check_mapping'].values() for x in ids)<=scientific: raise ValueError('domain concerns must map to original scientific checks')
    if options.get('claim_scope',request['claim_scope'])!=request['claim_scope'] or 'case_pin' in options: raise ValueError('domain scope/case cannot be replaced')
    out=judgment._path(out)
    if out==root or out.is_relative_to(root): raise ValueError('domain preparation must preserve the existing scientific run')
    out.mkdir(parents=True,exist_ok=False)
    rp=judgment._new(out/'domain-report.json',report)
    case=_case(report,rp,reg['policy']['actors']['proposer'])
    # The exact original inputs, not just their report labels, are public anchors.
    for i,p in enumerate(report['inputs']):
        if Path(p['path']).stat().st_size>2_000_000: continue # Explicit pin remains; no unbounded model context.
        raw=_bytes(p,Path(p['path']).parent)
        try: value=judgment.review_context._strict_json_bytes(raw); format_='json'
        except (ValueError,UnicodeError):
            try: value=raw.decode('utf8'); format_='text'
            except UnicodeError: continue
        if format_=='text' and (not value.strip() or value!=value.strip()):
            # JSON wrapper retains exact text without changing the original evidence bytes.
            wrapped=judgment._new(out/('source-'+str(i)+'.json'),{'source':p,'text':value}); value={'source':p,'text':value}; p=wrapped; format_='json'
        case['nodes'][0]['anchors'].append({'kind':'external_source','artifact':p,'format':format_,'location':'','value':value})
    cp=judgment._new(out/'domain-case.json',decision_case.validate_case(case))
    bound=judgment.prepare_role(root,out/'role',case_pin=cp,claim_scope=request['claim_scope'],**{k:v for k,v in options.items() if k!='claim_scope'})
    result={'schema_version':1,'kind':'sfitter_domain_binding','request':request_pin,'report':rp,'case':cp,'judgment':bound,
            'execution_authorized':False,'physics_validated':False}
    judgment._new(out/'protocol-binding.json',result)
    return result


def verify_binding(binding, *, allow_control=False):
    _keys(binding, ('schema_version','kind','request','report','case','judgment','execution_authorized','physics_validated'), 'domain binding')
    _version(binding['schema_version'])
    if binding['kind']!='sfitter_domain_binding' or binding['execution_authorized'] is not False or binding['physics_validated'] is not False: raise ValueError('domain binding has no execution or physics authority')
    base=Path(binding['request']['path']).parent; request=_read(binding['request'],base); current=context(request,base); report=_read(binding['report'],base)
    if current!=report: raise ValueError('domain evidence or recomputation changed; prepare a fresh review')
    verified=judgment.verify_binding(binding['judgment'],allow_control=allow_control)
    if verified['contract']['case_pin']!=binding['case'] or verified['contract']['claim_scope']!=request['claim_scope']: raise ValueError('role did not review this exact domain case/scope')
    case=_read(binding['case'],base)
    _,reg,_,_=judgment._live(verified['contract']['rundir'])
    expected=_case(report,binding['report'],reg['policy']['actors']['proposer'])
    observed=deepcopy(case); observed['nodes'][0]['anchors']=observed['nodes'][0]['anchors'][:len(expected['nodes'][0]['anchors'])]
    if observed!=expected: raise ValueError('role did not review the complete declared domain case')
    return request,current,verified


def consume(rundir, binding, *, allow_control=False):
    """Use the original journal, with no acceptance of unresolved material checks."""
    request,report,verified=verify_binding(binding,allow_control=allow_control)
    if verified['value']['verdict']=='accept' and any(c['material'] and c['status']!='pass' for c in report['concerns']):
        raise ValueError('required domain concern unresolved/failed; send back or request evidence')
    if verified['value']['verdict']=='send_back':
        mapped={x for ids in request['check_mapping'].values() for x in ids}
        if any(not set(f['check_ids'])&mapped for f in verified['value']['findings']): raise ValueError('domain findings need located original scientific check IDs')
    contract,value=verified['contract'],verified['value']
    if str(judgment.review._root(rundir))!=contract['rundir']: raise ValueError('role belongs to another run')
    if contract['phase']!='result_review': return verified
    if value['claim_scope'] is not None and value['claim_scope']!=contract['claim_scope']: raise ValueError('role changed requested scope')
    # The ordinary journal retains original domain sources as well as role/context
    # evidence, so later delivery/reuse also refuses source drift.
    support=verified['supporting_artifacts']+[binding['request'],binding['report'],*report['inputs']]
    return judgment.review.submit_review(rundir,role=judgment.ROLE[contract['role']],actor_id=contract['actor_id'],
        verdict=value['verdict'],summary=value['summary'],findings=value['findings'],closes=value['closes'],claim_scope=value['claim_scope'],
        supporting_artifacts=list({p['path']:p for p in support}.values()))


def rework(rundir, binding, out, *, allow_control=False):
    """Actual send-back -> new owning-phase draft, never old vote/status mutation."""
    request,report,verified=verify_binding(binding,allow_control=allow_control)
    root,_,_,view=judgment._live(rundir)
    if str(root)!=verified['contract']['rundir'] or verified['value']['verdict']!='send_back' or view['state']!='send_back': raise ValueError('current actual send-back for this run required')
    matching=[r for r in view['reviews'] if r['actor_id']==verified['contract']['actor_id'] and r['verdict']=='send_back' and binding['judgment']['request'] in r.get('supporting_artifacts',[])]
    if len(matching)!=1: raise ValueError('send-back must already be recorded in the existing review journal')
    checks={x for f in verified['value']['findings'] for x in f['check_ids']}
    concerns=[c for c in report['concerns'] if checks&set(c['original_check_ids'])]
    if not concerns: raise ValueError('located finding has no owning-phase mapping')
    owner=min((c['owner_phase'] for c in concerns),key=workflow.PHASES.index)
    base=Path(request['workflow']['path']).parent; wf=_read(request['workflow'],base)
    # Preserve current handoff identities but discard the owning suffix in a new request.
    wf=deepcopy(wf); cutoff=workflow.PHASES.index(owner)
    wf['handoffs']={p:_pin(pin,base) for p,pin in wf['handoffs'].items() if workflow.PHASES.index(p)<cutoff}
    wf['sources']=[_pin(p,base) for p in wf['sources']]+[binding['request'],binding['report'],binding['judgment']['request']]
    wf['upstream_tree']={'root':str(workflow.custody._regular(wf['upstream_tree']['root'],base,directory=True)),'manifest':_pin(wf['upstream_tree']['manifest'],base)}
    wf['id']=wf['id'][:35]+'-rework-'+binding['judgment']['subject_sha256'][:8]
    out=judgment._path(out)
    if out==root or out.is_relative_to(root): raise ValueError('rework must preserve original scientific run/history')
    out.mkdir(parents=True,exist_ok=False); wp=judgment._new(out/'workflow.json',wf)
    graph=judgment._inherit_goal(workflow.phase_graph(wf,out,wp),verified['contract'].get('campaign')); gp=judgment._new(out/'phase-graph.json',graph)
    receipt={'schema_version':1,'kind':'sfitter_owning_phase_rework','owner_phase':owner,'affected_concerns':[c['id'] for c in concerns],
        'workflow':wp,'phase_graph':gp,'invalidated_handoffs':list(workflow.PHASES[cutoff:]),'retained_handoffs':list(wf['handoffs']),
        'parent_request':binding['request'],'actual_sendback_request':binding['judgment']['request'],
        'campaign':verified['contract'].get('campaign'),
        'admission_route':'existing_bounded_correction_if_scope_allows' if view['redos_remaining']>0 else 'fresh_study_required_original_redo_bound_exhausted',
        'old_votes_carried':[],'execution_authorized':False,'physics_validated':False,
        'next':'Run the bounded owning-phase Graph through existing campaign accounting; supply revised artifacts, then prepare fresh domain roles. Ordinary correction/new-study admission remains required.'}
    judgment._new(out/'rework-receipt.json',receipt)
    return receipt


def host_tool(parameters, pins):
    """No nested dispatch; all domain dependencies must be explicit Graph inputs."""
    _keys(parameters, ('request_input',), 'SFitter review tool parameters'); key=parameters['request_input']
    if key not in pins: raise ValueError('explicit protocol operation input required')
    path,sha=pins[key]; operation=_read({'path':str(path),'sha256':sha},Path(path).parent)
    _keys(operation, ('operation','rundir','request','arguments'), 'protocol operation')
    request=_read(operation['request'],Path(path).parent); report=context(request,Path(operation['request']['path']).parent)
    presented={str(judgment._path(p)):h for p,h in pins.values()}
    for p in [operation['request'],*report['inputs']]:
        if presented.get(str(judgment._path(p['path'])))!=p['sha256']: raise ValueError('domain source must be explicitly presented to caller Graph')
    args=operation['arguments']; op=operation['operation']
    if op=='context': _keys(args, (), 'context arguments'); return report
    if op=='prepare-role':
        _keys(args, ('out','role','actor_id','model','reasoning_effort','max_output_tokens','max_wall_seconds','campaign','experiment'), 'role preparation arguments')
        return prepare_role(operation['rundir'],operation['request'],**args)
    if op in ('consume','rework'):
        fields=('binding',) if op=='consume' else ('binding','out'); _keys(args,fields,'consumer arguments')
        p=_pin(args['binding'],Path(path).parent)
        if presented.get(p['path'])!=p['sha256']: raise ValueError('actual binding must be presented')
        b=_read(p,Path(path).parent)
        if b['request']!=_pin(operation['request'],Path(path).parent): raise ValueError('operation request differs from actual domain binding')
        return globals()[op](operation['rundir'],b,**({'out':args['out']} if op=='rework' else {}))
    raise ValueError('unsupported protocol operation; no approval or native/model dispatch')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('operation',choices=('context','prepare-role','consume','rework'))
    parser.add_argument('--request',required=True,type=Path); parser.add_argument('--rundir',type=Path); parser.add_argument('--arguments',type=Path); parser.add_argument('--out',type=Path)
    args=parser.parse_args(argv); pin=judgment._pin(args.request); request=_read(pin,args.request.parent)
    if args.operation=='context': result=context(request,args.request.parent)
    else:
        if args.rundir is None or args.arguments is None: parser.error('--rundir and exact --arguments JSON required')
        values=_read(judgment._pin(args.arguments),args.arguments.parent)
        if args.operation=='prepare-role': result=prepare_role(args.rundir,pin,**values)
        else:
            _keys(values, ('binding',) if args.operation=='consume' else ('binding','out'),'operation arguments')
            b=_read(values['binding'],args.arguments.parent)
            if b['request']!=pin: raise ValueError('binding request differs')
            result=globals()[args.operation](args.rundir,b,**({'out':values['out']} if args.operation=='rework' else {}))
    if args.out: judgment._new(args.out,result)
    else: print(json.dumps(result,indent=2,allow_nan=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
