"""Source-coordinate rebin and same-original-event normalization composition.

No event projection, native runner or inference. All original acquisitions and
the complete coordinate traces are supplied and remain independently unqualified.
The module never manufactures a target-geometry native acquisition record.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from ravel.physics import group_normalization as n

class CompositionError(ValueError): pass

def need(value, message):
    if not value: raise CompositionError(message)

def keys(obj, required, optional=()):
    need(isinstance(obj, dict) and set(required)<=set(obj)<=set(required)|set(optional), 'closed object keys required')

def text(value):
    need(isinstance(value,str) and value.strip(), 'nonempty identity required'); return value

def number(value):
    return n._number(value)

def pins(sources, base):
    from ravel.workflow.science import regular
    raw=n._sources(sources, base)
    for pin in sources: regular(pin['path'], base)
    return raw

def read_origin(pin, base):
    raw=pins([pin], base)[pin['id']]
    return n._decode(raw), raw

def native_arm(pin, base):
    contract, _=read_origin(pin, base)
    path=Path(pin['path']);path=path if path.is_absolute() else Path(base)/path
    base=path.parent
    raw=pins(contract['sources'], Path(base))
    acquired=n._decode(raw[contract['acquisition_source']])
    result=n.normalize(contract, acquired, base_dir=base)
    original=n._decode(raw[contract['acquisition_contract_source']])
    return {'contract':contract, 'acquired':acquired, 'original':original,
            'result':result, 'hist_basis':acquired['basis'],
            'hist_groups':acquired['uncertainty']['groups'],
            'components':contract['components'], 'origin_kind':'original_native_supplied',
            'origins':[pin,*contract['sources']], 'base':base, 'source_snapshot':raw}

def cell(x, bins):
    if x < bins[0]['low']: return 'underflow'
    for b in bins:
        if x < b['high']: return b['id']
    return 'overflow'

def geometry(q):
    keys(q, ('axis','bins','unit','representation'))
    keys(q['axis'], ('name','unit')); text(q['axis']['name']);text(q['axis']['unit']);text(q['unit'])
    need(q['representation']=='integrated', 'rebin integrated quantities only')
    need(isinstance(q['bins'],list) and 1<=len(q['bins'])<=128,'bounded finite geometry required')
    seen=set(); last=None
    for b in q['bins']:
        keys(b, ('id','low','high')); ident=text(b['id']);low=number(b['low']);high=number(b['high'])
        need(ident not in seen and ident not in ('underflow','overflow') and low<high and
             (last is None or low==last),'exact contiguous target geometry required')
        seen.add(ident);last=high

def rebin_schema(contract):
    keys(contract, ('schema_version','kind','sources','original_normalization','target_geometry_source',
                    'targets','sites','fill_semantics','boundary_rule'), ('arithmetic_policy',))
    n.arithmetic_policy(contract)
    need(type(contract['schema_version']) is int and contract['schema_version']==1 and
         contract['kind']=='source-coordinate-rebin-contract','unsupported rebin contract')
    need(contract['fill_semantics']=='native_default_event_weight_fraction1' and
         contract['boundary_rule']=='half_open_finite_underflow_overflow','explicit source fill/boundary semantics required')
    need(isinstance(contract['targets'],list) and bool(contract['targets']), 'complete target geometry required')
    outputs=[]
    for row in contract['targets']:
        keys(row,('output','quantity'));outputs.append(text(row['output']));geometry(row['quantity'])
    need(len(set(outputs))==len(outputs), 'unique target outputs required')
    need(isinstance(contract['sites'],list) and len(contract['sites'])==len(outputs), 'complete source site census required')
    sites=[];mapped=[]
    for row in contract['sites']:
        keys(row,('site','output','definition'));keys(row['definition'],('source','first_line','last_line','text'))
        need(type(row['site']) is int and row['site']>=0, 'integer source site required')
        sites.append(row['site']);mapped.append(row['output'])
    need(len(set(sites))==len(sites) and set(mapped)==set(outputs), 'unique complete source site/output census required')


def rebin(contract, *, base_dir='.'):
    """Reconcile original group fills, then construct distinct target groups."""
    rebin_schema(contract)
    raw=pins(contract['sources'],base_dir)
    need(contract['original_normalization'] in raw and contract['target_geometry_source'] in raw,
         'original normalization and target source pins required')
    origin=next(p for p in contract['sources'] if p['id']==contract['original_normalization'])
    arm=native_arm(origin,base_dir)
    source_target=n._decode(raw[contract['target_geometry_source']])
    need(source_target==contract['targets'],'target geometry is not exactly source bound')
    acq, original=arm['acquired'],arm['original']; components=arm['components']
    names=[w['id'] for w in arm['contract']['weights']]
    outputs=[c['output'] for c in components]
    need(isinstance(contract['targets'],list) and len(contract['targets'])==len(components), 'complete target output census required')
    targets={}
    for target in contract['targets']:
        keys(target, ('output','quantity'));o=text(target['output']);geometry(target['quantity'])
        need(o in outputs and o not in targets,'unique complete target outputs required')
        source=next(c for c in components if c['output']==o)['quantity'];q=target['quantity']
        need(q['axis']==source['axis'] and q['unit']==source['unit'], 'target axis/units differ from source')
        targets[o]=q
    need(isinstance(contract['sites'],list) and len(contract['sites'])==len(outputs),'complete fill site/output census required')
    sites={}
    for row in contract['sites']:
        keys(row,('site','output','definition'))
        need(type(row['site']) is int and row['site']>=0 and row['site'] not in sites and row['output'] in outputs,
             'unique source fill site required')
        n._definition(row['definition'],raw);sites[row['site']]=row['output']
    need(set(sites.values())==set(outputs),'one source site per output required')
    trace_raw=pins(arm['contract']['sources'],arm['base'])[arm['contract']['native_trace_source']]
    trace=[n._decode(line) for line in trace_raw.decode('utf-8').splitlines()]
    groups=arm['hist_groups']; events=original['events']
    need(len(trace)==len(groups),'complete coordinate trace/event census required')
    original_positions={(b['weight'],b['output'],b['bin']):i for i,b in enumerate(arm['hist_basis'])}
    target_basis=[]
    for w in names:
        for component in components:
            o=component['output'];q=targets[o]; bs=q['bins']
            for b,lo,hi in [('underflow',None,bs[0]['low']),*[(b['id'],b['low'],b['high']) for b in bs],('overflow',bs[-1]['high'],None)]:
                target_basis.append({'weight':w,'output':o,'bin':b,'unit':'1','axis_unit':q['axis']['unit'],'low':lo,'high':hi,
                                     'native_path':next(r['native_path'] for r in arm['hist_basis'] if r['output']==o)})
    
    if n.arithmetic_policy(contract)['method']=='legacy_compensated':
        need(len(target_basis)+len(names)<=768 and (len(target_basis)+len(names))**2*len(groups)<=25_000_000, 'rebin union arithmetic budget exceeded')
    else: n.arithmetic_budget(contract, len(target_basis)+len(names), len(groups))
    target_positions={(b['weight'],b['output'],b['bin']):i for i,b in enumerate(target_basis)}
    target_groups=[]; fill_count=0
    for ordinal,(record,group,event) in enumerate(zip(trace,groups,events)):
        keys(record,('schema','routine','original_source_sha256','ordinal','event_number','pid','unwinding','native_weight_names','weights','fills'))
        need(record['schema']=='ravel-native-fills/v1' and record['routine']==acq['logical_source_routine'] and
             record['original_source_sha256']==acq['uninstrumented_source_sha256'] and
             type(record['ordinal']) is int and record['ordinal']==ordinal and
             type(record['event_number']) is int and record['event_number']==event['event_number'] and
             type(record['pid']) is int and record['pid']==acq['same_process_pid'] and type(record['unwinding']) is bool,
             'coordinate trace source/process/encounter differs')
        need(record['native_weight_names']==[w['native'] for w in original['weight_mapping']] and
             isinstance(record['weights'],list) and len(record['weights'])==len(names) and
             all(type(w) in (int,float) and math.isfinite(w) for w in record['weights']) and
             record['weights']==event['selected_weights'], 'coordinate effective weight mapping differs')
        need(isinstance(record['fills'],list) and len(record['fills'])<=65536,'bounded fills required')
        fill_count+=len(record['fills']);need(fill_count<=max(65536,4*n.arithmetic_policy(contract)['maximum_groups']), 'total coordinate fill budget exceeded')
        old_terms=[[] for _ in arm['hist_basis']];new_terms=[[] for _ in target_basis]
        for fill in record['fills']:
            keys(fill,('site','coordinates'));need(type(fill['site']) is int and fill['site'] in sites,'unbound source site')
            need(isinstance(fill['coordinates'],list) and len(fill['coordinates'])==1,'one observed source coordinate required')
            x=number(fill['coordinates'][0]);output=sites[fill['site']]
            old=next(c['quantity']['bins'] for c in components if c['output']==output)
            for w,weight in zip(names,record['weights']):
                value=number(weight)
                old_terms[original_positions[(w,output,cell(x,old))]].append(value)
                new_terms[target_positions[(w,output,cell(x,targets[output]['bins']))]].append(value)
        need([math.fsum(v) for v in old_terms]==group['values'],
             'coordinate trace fails original complete native group reconciliation')
        target_groups.append({'id':group['id'],'values':[math.fsum(v) for v in new_terms]})
    changed=copy.deepcopy(components)
    for component in changed:component['quantity']=targets[component['output']]
    need(pins(contract['sources'],base_dir)==raw,'source changed during rebin')
    arm.update(hist_basis=target_basis,hist_groups=target_groups,components=changed,
               origin_kind='source_coordinate_rebin',rebin_contract=contract,
               origins=[*arm['origins'],*contract['sources']])
    return arm

def composition_schema(contract):
    keys(contract, ('schema_version','kind','sources','arms','group_join','counter_policy'), ('arithmetic_policy',))
    n.arithmetic_policy(contract)
    need(type(contract['schema_version']) is int and contract['schema_version']==1 and
         contract['kind']=='same-event-group-composition-contract','unsupported composition contract')
    need(contract['group_join']=='exact_ordered_source_sha256_encounter' and
         contract['counter_policy']=='share_one_counter_per_weight','explicit same-event counter law required')
    need(isinstance(contract['arms'],list) and 2<=len(contract['arms'])<=8,'bounded multiple arms required')
    ids=[]
    for row in contract['arms']:
        keys(row,('id','kind','source'));ident=text(row['id']);
        need(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}',ident), 'bounded unambiguous arm namespace required')
        ids.append(ident);text(row['source'])
        need(row['kind'] in ('original_native_supplied','source_coordinate_rebin'), 'unknown distinct arm origin kind')
    need(len(set(ids))==len(ids),'unique bound arm required')


def compose(contract, *, base_dir='.'):
    """Join source-bound original/rebin arms with one shared event counter."""
    composition_schema(contract)
    raw=pins(contract['sources'],base_dir); arms=[];ids=set()
    need(isinstance(contract['arms'],list) and 2<=len(contract['arms'])<=8,'bounded multiple arms required')
    for declaration in contract['arms']:
        keys(declaration, ('id','kind','source'));ident=text(declaration['id'])
        need(ident not in ids and declaration['source'] in raw,'unique bound arm required');ids.add(ident)
        pin=next(p for p in contract['sources'] if p['id']==declaration['source'])
        if declaration['kind']=='original_native_supplied':arm=native_arm(pin,base_dir)
        elif declaration['kind']=='source_coordinate_rebin':
            path=Path(pin['path']);path=path if path.is_absolute() else Path(base_dir)/path
            arm=rebin(n._decode(raw[declaration['source']]),base_dir=path.parent)
        else:raise CompositionError('unknown distinct arm origin kind')
        arm['id']=ident;arms.append(arm)
    first=arms[0];names=[w['id'] for w in first['contract']['weights']]
    for arm in arms[1:]:
        need(arm['contract']['weights']==first['contract']['weights'] and
             arm['original']['weight_mapping']==first['original']['weight_mapping'], 'cross-mode native weight/counter mapping differs')
        need(arm['original']['events']==first['original']['events'] and
             arm['acquired']['normalization_event_weights']==first['acquired']['normalization_event_weights'],
             'cross-mode complete original encounter/weight population differs')
        need(arm['acquired']['normalization_counter_by_weight']==first['acquired']['normalization_counter_by_weight'],
             'cross-mode whole-event counters differ')
        need([g['id'] for g in arm['hist_groups']]==[g['id'] for g in first['hist_groups']], 'cross-mode exact group order differs')
    hist_basis=[];components=[];rows=[];coordinates=[]
    for arm in arms:
        for component in arm['components']:
            q=copy.deepcopy(component);q['id']=arm['id']+'/'+q['id'];q['output']=arm['id']+'/'+q['output'];components.append(q)
        component_map={c['output']:c for c in arm['components']}
        for b in arm['hist_basis']:
            hist_basis.append({**b,'arm':arm['id'],'kind':'histogram'})
            coordinates.append((b['weight'],arm['id']+'/'+component_map[b['output']]['id'],b['bin']))
    count=len(hist_basis); m=len(first['hist_groups'])
    policy=n.arithmetic_policy(contract)
    if policy['method']=='legacy_compensated':
        need(count+len(names)<=768 and m<=4096 and (count+len(names))**2*m<=25_000_000, 'complete union covariance budget exceeded')
    else: n.arithmetic_budget(contract,count+len(names),m)
    for i,event in enumerate(first['acquired']['normalization_event_weights']):
        rows.append([v for arm in arms for v in arm['hist_groups'][i]['values']]+[event['weights'][w] for w in names])
    central=[math.fsum(r[i] for r in rows) for i in range(count+len(names))]
    input_arithmetic=None
    if policy['method']=='legacy_compensated': input_cov=n._gram(list(map(list,zip(*rows))))
    else:
        from . import group_arithmetic
        input_arithmetic=group_arithmetic.gram(list(map(list,zip(*rows))),maximum_pair_products=policy['maximum_pair_group_products'])
        input_cov=input_arithmetic['matrix']
    values=[];J=[];phi=[];err=[]; factors=[]
    lookup={c['id']:c for c in components}
    for i,(w,c,b) in enumerate(coordinates):
        W=central[count+names.index(w)];N=central[i];component=lookup[c]
        need(W>0 if component['denominator_policy']=='positive' else W!=0,'inadmissible shared normalization denominator')
        k=number(component['fixed_coefficients'][w]['value']);alpha=k/W;value=alpha*N;beta=-value/W
        need(all(math.isfinite(v) for v in (alpha,value,beta)) and alpha!=0 and (N==0 or value!=0) and (value==0 or beta!=0),
             'shared normalization central/derivative unrepresentable')
        row=[0.]*(count+len(names));row[i]=alpha;row[count+names.index(w)]=beta;J.append(row);values.append(value)
        dots=[n._dot([(alpha,r[i]),(beta,r[count+names.index(w)])]) for r in rows]
        phi.append([v[0] for v in dots]);err.append([v[1] for v in dots])
        factors.append({'weight':w,'component':c,'bin':b,'fixed_coefficient':k,'counter':W,'counter_coordinate':count+names.index(w)})
    output_arithmetic=None
    if policy['method']!='legacy_compensated':
        output_arithmetic=group_arithmetic.gram(phi,error=err,maximum_pair_products=policy['maximum_pair_group_products'])
        C=output_arithmetic['matrix'];maximum=output_arithmetic['maximum_entry_forward_error_bound']
    else:
        C=[[0.]*count for _ in range(count)];maximum=0.
        for i in range(count):
            for j in range(i,count):
                value,error=n._dot(zip(phi[i],phi[j]))
                propagated=n._positive_sum(n._positive_sum([n._up(abs(a)*eb),n._up(abs(b)*ea),n._up(ea*eb)])
                             for a,b,ea,eb in zip(phi[i],phi[j],err[i],err[j]))
                C[i][j]=C[j][i]=value;maximum=max(maximum,n._positive_sum([error,propagated]))
    need(pins(contract['sources'],base_dir)==raw,'source changed during composition')
    for arm in arms:
        need(pins(arm['contract']['sources'],arm['base'])==arm['source_snapshot'], 'original arm source changed during composition')
    return copy.deepcopy({'schema_version':1,'kind':'composed-group-normalization-result','contract':contract,
        'components':components,'input_basis':hist_basis+[{'kind':'normalization_counter','weight':w,'counter':first['contract']['weights'][i]['counter_id'],'unit':'1'} for i,w in enumerate(names)],
        'input_values':central,'input_covariance':input_cov,'input_groups':[{'id':g['id'],'vector':row} for g,row in zip(first['hist_groups'],rows)],
        'output_basis':[{'weight':w,'component':c,'bin':b} for w,c,b in coordinates], 'values':values,'jacobian':J,'output_covariance':C,
        'normalization_factors':factors,'linearized_group_vectors':[{'id':g['id'],'vector':[p[i] for p in phi]} for i,g in enumerate(first['hist_groups'])],
        'covariance_maximum_entry_forward_error_bound':maximum,'forward_error_scope':first['result']['forward_error_scope'],
        'counter_diagnostics':{w:{**d,'scalar_coordinate':count+names.index(w)} for w,d in first['result']['counter_diagnostics'].items()},
        'arm_origins':[{'id':a['id'],'kind':a['origin_kind'],'original_native':a['result'],'base_dir':str(a['base']), 'rebin_contract':a.get('rebin_contract'),'target_groups':a['hist_groups'] if a['origin_kind']=='source_coordinate_rebin' else None,'sources':a['origins']} for a in arms],
        'uncertainty_scope':first['result']['uncertainty_scope'],'linearized_groups_are_central_contributions':False,
        'representability_policy':first['result']['representability_policy'],'requires_separate_execution_custody_review':True,
        'experimental_independence':None,'native_acquisition_qualified':False,'inference':None,'physics_validated':False,
        **({'arithmetic_admission':{'policy':policy,'input_entry_forward_error_bounds':input_arithmetic['entry_forward_error_bounds'],
        'output_entry_forward_error_bounds':output_arithmetic['entry_forward_error_bounds'],'method':output_arithmetic['algorithm'],
        'scope':output_arithmetic['scope']}} if output_arithmetic else {})})

def derived_joint(result):
    need(result.get('kind')=='composed-group-normalization-result','composed quantity result required')
    return copy.deepcopy({'schema_version':1,'basis':result['output_basis'],'values':result['values'],
        'uncertainty':{'kind':'supplied_covariance','matrix':result['output_covariance'],'semantics':result['uncertainty_scope']}})

def finite_slice(result,basis,*,representation='integrated'):
    """Reuse the numerical slice over the identical normalized quantity schema.

    Only the quantity kind is mapped for this in-memory numerical utility. No
    native input, acquisition record, geometry or original provenance is changed.
    The returned origin explicitly distinguishes the composed operation.
    """
    need(result.get('kind')=='composed-group-normalization-result','composed quantity result required')
    numerical={**result,'kind':'group-normalization-result','sources':result['contract']['sources'],
               'acquisition_source':'multiple-source-bound-arms'}
    out=n.finite_slice(numerical,basis,representation=representation)
    out['origin_kind']='same-event-source-bound-composed-normalization'
    out['arm_origins']=result['arm_origins']
    return out

def measurement_slice(result,measurement_basis,mapping,unit_join):
    """Exact source-basis numerator/denominator density slice, full cross C.

    Supplies BSM components to the existing ratio-measurement seam. No SM or
    experimental covariance is created, and no independence is inferred.
    Unit notation joins require caller-declared identical numerical scales.
    """
    keys(mapping,('numerator','denominator'))
    need(isinstance(measurement_basis,list) and 1<=len(measurement_basis)<=128,'explicit measurement basis required')
    count=len(measurement_basis)
    need(all(isinstance(mapping[k],list) and len(mapping[k])==count for k in mapping),'complete two-sided mapping required')
    selected=mapping['numerator']+mapping['denominator'];out=finite_slice(result,selected,representation='differential')
    need(isinstance(unit_join,list) and len(unit_join)==count,'explicit complete source unit notation join required')
    components={r['id']:r for r in result['components']};ids=[]
    for i,b in enumerate(measurement_basis):
        keys(b,('id','observable','axis','low','high'));ident=text(b['id']);text(b['observable'])
        need(ident not in ids and isinstance(b['low'],list) and isinstance(b['high'],list) and len(b['low'])==len(b['high'])==1,
             'unique continuous measurement basis required');ids.append(ident)
        for side in mapping:
            row=mapping[side][i];component=components[row['component']];q=component['quantity']
            cell=next(v for v in q['bins'] if v['id']==row['bin'])
            need(q['axis']==b['axis'] and [cell['low']]==b['low'] and [cell['high']]==b['high'],
                 'exact source measurement geometry join required')
        keys(unit_join[i],('from','to','scale'))
        need(type(unit_join[i]['scale']) in (int,float) and unit_join[i]['scale']==1 and
             unit_join[i]['from']==out['units'][i]==out['units'][count+i], 'identity-only unit notation join required')
        text(unit_join[i]['to'])
    return copy.deepcopy({'schema_version':1,'kind':'source-bound-measurement-component-slice','basis':measurement_basis,
        'bsm_numerator':{'bin_ids':ids,'values':out['values'][:count],'units':[r['to'] for r in unit_join]},
        'bsm_denominator':{'bin_ids':ids,'values':out['values'][count:],'units':[r['to'] for r in unit_join]},
        'joint_prediction_covariance':out['covariance'],'coordinate_ids':[side+'/'+i for side in ('bsm_numerator','bsm_denominator') for i in ids],
        'mapping':mapping,'unit_join':unit_join,'quantity_origin':out,
        'experimental_independence':None,'inference':None,'physics_validated':False})

def component_schema(contract):
    keys(contract,('schema_version','kind','sources','composition_source','measurement_basis_source','mapping','unit_join'))
    need(type(contract['schema_version']) is int and contract['schema_version']==1 and
         contract['kind']=='source-bound-measurement-components-contract', 'unsupported component-slice contract')
    text(contract['composition_source']);text(contract['measurement_basis_source'])
    keys(contract['mapping'],('numerator','denominator'))
    need(all(isinstance(contract['mapping'][side],list) and bool(contract['mapping'][side]) for side in contract['mapping']),
         'complete numerator/denominator mapping required')
    need(len(contract['mapping']['numerator'])==len(contract['mapping']['denominator'])<=128, 'bounded complete two-sided mapping required')
    for side in contract['mapping']:
        for row in contract['mapping'][side]:
            keys(row,('weight','component','bin'))
            for value in row.values():text(value)
    need(isinstance(contract['unit_join'],list) and len(contract['unit_join'])==len(contract['mapping']['numerator']),
         'complete source unit notation join required')
    for row in contract['unit_join']:
        keys(row,('from','to','scale'));text(row['from']);text(row['to'])
        need(number(row['scale'])==1, 'identity-only unit notation join required')


def component_slice(contract, *, base_dir='.'):
    """Compose supplied same-event arms and join a source-pinned exact basis."""
    component_schema(contract);raw=pins(contract['sources'],base_dir)
    need(contract['composition_source'] in raw and contract['measurement_basis_source'] in raw,
         'composition and measurement basis pins required')
    pin=next(p for p in contract['sources'] if p['id']==contract['composition_source'])
    path=Path(pin['path']);path=path if path.is_absolute() else Path(base_dir)/path
    composition=compose(n._decode(raw[contract['composition_source']]),base_dir=path.parent)
    basis=n._decode(raw[contract['measurement_basis_source']])
    sliced=measurement_slice(composition,basis,contract['mapping'],contract['unit_join'])
    sliced.update(contract=contract,sources=contract['sources'],native_acquisition_qualified=False)
    need(pins(contract['sources'],base_dir)==raw,'component origin source changed during operation')
    return composition,sliced


def validate(task):
    keys(task,('schema_version','operation','input','contract_sha256'))
    need(type(task['schema_version']) is int and task['schema_version']==1 and task['operation'] in
         ('coordinate-rebin','same-event-compose','measurement-components'), 'closed operation task required')
    n.validate({'schema_version':1,'input':task['input'],'contract_sha256':task['contract_sha256']})
    return copy.deepcopy(task)


KINDS={'coordinate-rebin':'source-coordinate-rebin-contract',
       'same-event-compose':'same-event-group-composition-contract',
       'measurement-components':'source-bound-measurement-components-contract'}


def inputs(task,base):
    """Closed complete nested graph; no numerical evaluation or native imports."""
    from ravel.workflow.science import regular
    task=validate(task);root=regular(task['input'],base)
    need(root.stat().st_size<=1_000_000 and hashlib.sha256(root.read_bytes()).hexdigest()==task['contract_sha256'],'outer contract digest/size differs')
    files=[root];visiting=set();visited=set()
    def visit(path, expected):
        path=regular(path,base)
        need(path not in visiting,'cyclic contract graph')
        need(len(visiting)<5 and path.stat().st_size<=1_000_000,'bounded contract graph depth/size required')
        doc=n._decode(path.read_bytes())
        need(isinstance(doc,dict) and doc.get('kind')==expected,'declared operation/arm contract kind differs')
        if path in visited:return
        visiting.add(path)
        if expected=='group-normalization-contract':
            supplied=n.inputs({'schema_version':1,'input':str(path),'contract_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},path.parent)
            for source in supplied:
                if source not in files:files.append(source)
        else:
            checker={'source-coordinate-rebin-contract':rebin_schema,
                     'same-event-group-composition-contract':composition_schema,
                     'source-bound-measurement-components-contract':component_schema}[expected]
            checker(doc);raw=pins(doc['sources'],path.parent)
            for pin in doc['sources']:
                source=regular(pin['path'],path.parent)
                if source not in files:files.append(source)
            if expected=='source-coordinate-rebin-contract':
                children=[(doc['original_normalization'],'group-normalization-contract')]
                need(doc['target_geometry_source'] in raw,'target geometry source pin required')
                need(n._decode(raw[doc['target_geometry_source']])==doc['targets'],'target geometry is not exactly source bound')
                for row in doc['sites']:n._definition(row['definition'],raw)
            elif expected=='same-event-group-composition-contract':
                children=[(a['source'],'group-normalization-contract' if a['kind']=='original_native_supplied' else 'source-coordinate-rebin-contract') for a in doc['arms']]
            else:
                children=[(doc['composition_source'],'same-event-group-composition-contract')]
                need(doc['measurement_basis_source'] in raw,'measurement basis source pin required')
                from ravel.physics.ratio_measurement import _basis
                basis=n._decode(raw[doc['measurement_basis_source']]);_basis(basis)
                need(len(basis)==len(doc['mapping']['numerator']), 'measurement slice mapping population differs')
            for ident,kind in children:
                need(ident in raw,'declared nested contract source pin missing')
                pin=next(p for p in doc['sources'] if p['id']==ident)
                visit(regular(pin['path'],path.parent),kind)
        need(len(files)<=512 and sum(p.stat().st_size for p in files)<=128_000_000,'bounded complete input graph required')
        visiting.remove(path);visited.add(path)
    visit(root,KINDS[task['operation']])
    return files


def run(task,base,out):
    from ravel.workflow.state_io import atomic_json
    task=validate(task);files=inputs(task,base);path=files[0]
    snapshot={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    contract=n._decode(path.read_bytes());sliced=None
    if task['operation']=='coordinate-rebin':
        arm=rebin(contract,base_dir=path.parent)
        result={'schema_version':1,'kind':'source-coordinate-rebin-result','contract':contract,
                'original_native':arm['result'],'target_basis':arm['hist_basis'],'target_groups':arm['hist_groups'],
                'components':arm['components'],'sources':arm['origins'],'native_acquisition_qualified':False,
                'physics_validated':False,'inference':None}
    elif task['operation']=='measurement-components':
        result,sliced=component_slice(contract,base_dir=path.parent)
        result['measurement_components']=sliced
    else:result=compose(contract,base_dir=path.parent)
    need(inputs(task,base)==files and {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}==snapshot,
         'complete input graph changed during operation')
    result.update(status='passed',status_scope='Source-bound supplied coordinate/group quantity transform only',
                  input={'path':str(path),'sha256':task['contract_sha256']},task=task)
    out=Path(out);need(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),
                      'fresh operation output without symlink ancestry required');out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/'group-composition.json',result)
    if task['operation']!='coordinate-rebin':atomic_json(out/'normalized-joint.json',derived_joint(result))
    if sliced is not None:atomic_json(out/'measurement-components.json',sliced)
    return result
