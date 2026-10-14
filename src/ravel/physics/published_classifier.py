"""Published source classifiers composed with ordinary event/quantity delivery.

Supplied scalar rows are not reconstructed objects. Source excerpts are supplied
traceable declarations, not scientific approval. Native Rivet remains the sole
executor for preserved C++ ONNX/TMVA routines; this adds no TMVA provider.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import stat

from . import classifier_inputs as ci, quantities, domain_adapters as domains
from ravel.workflow.state_io import atomic_json

LIMIT=8*1024*1024
MAX_EVENTS=4096
SCOPE='published_source_classifier_quantity_delivery'
LIMITATIONS=[
    'Source declarations, feature units, supplied eligibility and object reconstruction require applicability review; excerpts do not prove their interpretation.',
    'Source scalar arithmetic and runtime inference are delivered, not native bitwise equivalence, calibration, detector validation or a new trained model.',
    'Poissonized independent-group moments and all named weights retain shared-bin covariance; no missing systematic covariance or likelihood is inferred.',
    'Native Rivet preserves original output contracts. Per-event scores and full bin covariance are unavailable unless the native routine actually publishes them.',
]


def _keys(v, keys):
    if type(v) is not dict or set(v)!=set(keys):raise ValueError('closed published-classifier fields required: '+str(keys))


def _text(v):
    if type(v) is not str or not v.strip():raise ValueError('explicit nonempty literal required')
    return v


def _num(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('finite literal number required')
    return v


def _sig(p):
    s=p.stat(follow_symlinks=False)
    if not stat.S_ISREG(s.st_mode):raise ValueError('ordinary regular evidence required')
    return (s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


def _json(raw):
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate JSON field')
            d[k]=v
        return d
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


class _Custody:
    def __init__(self,base,limit=LIMIT):self.base=Path(base).absolute();self.facts={};self.limit=limit

    def read(self,pin):
        if type(pin) is not dict or not {'path','sha256'}<=set(pin)<= {'path','sha256','size'}:raise ValueError('closed ordinary evidence pin required')
        if not re.fullmatch('[0-9a-f]{64}',pin['sha256']):raise ValueError('exact evidence SHA256 required')
        p=self.base/Path(_text(pin['path']))
        before=_sig(p);raw=ci.bounded_read(p,self.limit)
        if _sig(p)!=before or hashlib.sha256(raw).hexdigest()!=pin['sha256'] or ('size' in pin and (type(pin['size']) is not int or pin['size']!=len(raw))):
            raise ValueError('evidence changed or digest mismatch')
        fact={'path':str(p),'sha256':pin['sha256'],'size':len(raw)}
        if p in self.facts and self.facts[p]!=(fact,before):raise ValueError('conflicting evidence commitment')
        self.facts[p]=(fact,before)
        return p,raw

    def finish(self):
        for p,(fact,before) in self.facts.items():
            raw=ci.bounded_read(p,self.limit)
            if _sig(p)!=before or len(raw)!=fact['size'] or hashlib.sha256(raw).hexdigest()!=fact['sha256']:
                raise ValueError('ending source/input evidence changed')

    def current(self):
        for p,(fact,before) in self.facts.items():
            if any(q.is_symlink() for q in (p,*p.parents)) or _sig(p)!=before:
                raise ValueError('ending evidence endpoint changed')

    def inventory(self):return [v[0] for p,v in sorted(self.facts.items())]


def _native_outputs(root):
    """Retain generated native bytes without altering their schema or contents."""
    root=Path(root);members=sorted(root.rglob('*'))
    if any(p.is_symlink() for p in members):raise ValueError('native output symlink is not ordinary custody')
    files=[p for p in members if p.is_file()]
    if not 1<=len(files)<=4096:raise ValueError('bounded complete native output census required')
    custody=_Custody(root,64*1024*1024);total=0
    for p in files:
        before=_sig(p);raw=ci.bounded_read(p,custody.limit);total+=len(raw)
        if _sig(p)!=before or total>512*1024*1024:raise ValueError('changed or oversized native output population')
        custody.facts[p]=({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)},before)
    return custody


def _native_current(root,custody):
    members=list(Path(root).rglob('*'))
    if any(p.is_symlink() for p in members) or {p for p in members if p.is_file()}!=set(custody.facts):
        raise ValueError('native output membership changed')
    custody.current()


def validate(task):
    _keys(task,('schema_version','input','input_sha256'))
    if type(task['schema_version']) is not int or task['schema_version']!=1:raise ValueError('published-classifier task/v1 required')
    _text(task['input'])
    if type(task['input_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',task['input_sha256']):raise ValueError('input hash required')


def _excerpt(contract,index):
    if type(index) is not int or not 0<=index<len(contract['source_excerpts']):raise ValueError('source excerpt index required')
    return contract['source_excerpts'][index]


def _source_model(model,custody):
    _keys(model,('id','contract','feature_units','score_unit','score_range','eligibility','controls'))
    _text(model['id']);c=deepcopy(model['contract'])
    for name in ('source','model'):
        p,raw=custody.read(c[name]);old=c[name];c[name]={'path':str(p),'sha256':old['sha256']}
        if name=='source':
            for e in c['source_excerpts']:
                if e['file']!=old:raise ValueError('source excerpt must bind exact source declaration')
                e['file']=deepcopy(c[name])
    if (c.get('event_reconstruction_qualified') is not False or c.get('native_runtime_qualified') is not False or
        c.get('source_arithmetic_not_native_bitwise_equivalence') is not True):
        raise ValueError('source declarations cannot acquire native/physics qualification')
    ci.admit(c,{},expected_contract_sha256=ci.digest(c),preprocess=False)
    names=[f['id'] for f in c['features']]
    if not 1<=len(names)<=512 or len(set(names))!=len(names):raise ValueError('bounded unique complete feature census required')
    _keys(model['feature_units'],names)
    for unit in model['feature_units'].values():_text(unit)
    _text(model['score_unit'])
    if type(model['score_range']) is not list or len(model['score_range'])!=2 or _num(model['score_range'][0])>=_num(model['score_range'][1]):raise ValueError('ordered declared source score range required')
    _keys(model['eligibility'],('source_expression','source_excerpt'))
    _text(model['eligibility']['source_expression']);_excerpt(c,model['eligibility']['source_excerpt'])
    static=c['model_static'];ins=static['inputs'];outs=static['outputs']
    if len(ins)!=1 or len(outs)!=1:raise ValueError('single full tensor input/output source route required')
    if outs[0].get('element_type') not in (1,11):raise ValueError('floating source output tensor required')
    _route(c,None,False)
    sample={n:1.0 for n in names}
    ci.admit(c,sample,expected_contract_sha256=ci.digest(c),preprocess=True)
    width=c['source_output_operation']['complete_model_output_width']
    if not 1<=width<=512:raise ValueError('bounded full output width required')
    if type(model['controls']) is not list or not 1<=len(model['controls'])<=256:raise ValueError('complete supplied reference controls required')
    ids=[]
    for row in model['controls']:
        _keys(row,('id','values','expected_outputs','atol','rtol'));ids.append(_text(row['id']))
        ci.prepare_features(c,row['values'])
        if type(row['expected_outputs']) is not list or len(row['expected_outputs'])!=width:raise ValueError('complete reference output tensor required')
        for x in row['expected_outputs']:_num(x)
        if _num(row['atol'])<0 or _num(row['rtol'])<0:raise ValueError('nonnegative fixed reference tolerances required')
    if len(ids)!=len(set(ids)):raise ValueError('unique reference row identities required')
    return c


def _route(contract,event_number,selected):
    routing=contract['routing']
    if routing is None:return selected
    if routing.get('kind')=='supplied_fixed_model':return selected
    if routing.get('kind')!='event_number_cxx_modulo':raise ValueError('unserved source model routing; use unchanged native route')
    _keys(routing,('kind','modulus','odd_only_remainder','otherwise','selected'))
    if routing['modulus']!=2 or routing['odd_only_remainder']!=1 or routing['otherwise']!='even' or routing['selected'] not in ('even','odd'):
        raise ValueError('unsupported literal parity model routing')
    if event_number is None and not selected:return False
    if type(event_number) is not int:raise ValueError('original signed C++ event number required')
    remainder=event_number%2 if event_number>=0 else -((-event_number)%2)
    branch='odd' if remainder==1 else 'even'
    return selected and branch==routing['selected']


def _events(document,models,q):
    _keys(document,('kind','event_ids','weight_names','feature_units','events'))
    if document['kind']!='published-classifier-events/v1' or document['weight_names']!=q['weight_names']:raise ValueError('complete original weight order required')
    ids=document['event_ids'];names=[m['id'] for m in models]
    if type(ids) is not list or not 1<=len(ids)<=MAX_EVENTS or any(type(i) is not str or not i for i in ids) or len(set(ids))!=len(ids):raise ValueError('complete bounded unique original event census required')
    if document['feature_units']!={m['id']:m['feature_units'] for m in models}:raise ValueError('supplied feature units differ from source declarations')
    rows=document['events']
    if type(rows) is not list or [r.get('event_id') for r in rows]!=ids:raise ValueError('exact complete event order/census required; missing events cannot disappear')
    groups={}
    for r in rows:
        _keys(r,('event_id','event_number','group_id','shard_id','weights','source_selected','eligible','features'))
        group,shard=_text(r['group_id']),_text(r['shard_id'])
        if group in groups and groups[group]!=shard:raise ValueError('correlated group split across shards')
        groups[group]=shard
        _keys(r['weights'],q['weight_names'])
        for w in r['weights'].values():_num(w)
        for key in ('source_selected','eligible','features'):_keys(r[key],names)
        for m in models:
            name=m['id'];eligible=r['eligible'][name]
            selected=r['source_selected'][name]
            if type(selected) is not bool or type(eligible) is not bool:raise ValueError('explicit source eligibility boolean required')
            if eligible is not _route(m['contract'],r['event_number'],selected):raise ValueError('source eligibility/model routing differs')
            if not eligible:
                if r['features'][name] is not None:raise ValueError('ineligible source row must explicitly carry null, not imputed features')
            else:ci.prepare_features(m['contract'],r['features'][name])
    return rows


def _bins(doc,models,q):
    bins=doc['score_bins'];names={m['id']:m for m in models}
    if type(bins) is not list or not 1<=len(bins)<=32:raise ValueError('bounded complete source category population required')
    expected=[];seen=[]
    for i,b in enumerate(bins):
        _keys(b,('id','model','conditions','source_expression','source_excerpt'))
        seen.append(_text(b['id']));m=names.get(b['model'])
        if m is None:raise ValueError('unknown score model')
        _text(b['source_expression']);_excerpt(m['contract'],b['source_excerpt'])
        if type(b['conditions']) is not list or not 1<=len(b['conditions'])<=2:raise ValueError('explicit bounded score interval conditions required')
        for c in b['conditions']:
            _keys(c,('op','value'))
            if c['op'] not in ('>','>=','<','<='):raise ValueError('literal native boundary operator required')
            _num(c['value'])
        expected.append({'id':b['id'],'low':[i],'high':[i+1]})
    if len(set(seen))!=len(seen) or set(b['model'] for b in bins)!=set(names):raise ValueError('unique bins and complete used model census required')
    if q['axes']!=[{'name':'source_category','unit':'1'}] or q['bins']!=expected or q['representation']!='integrated':raise ValueError('quantity basis must be exact ordered source categories')


def _load(task,base):
    validate(task);custody=_Custody(base)
    p,raw=custody.read({'path':task['input'],'sha256':task['input_sha256']});doc=_json(raw)
    if doc.get('kind')!='published-classifier-composition/v1':raise ValueError('closed composition kind required')
    if doc.get('route')=='supplied-onnx':
        _keys(doc,('kind','route','models','events','score_bins','quantities','source_semantics'))
        _text(doc['source_semantics'])
        if type(doc['models']) is not list or not 1<=len(doc['models'])<=8:raise ValueError('bounded complete model population required')
        models=deepcopy(doc['models']);names=[m['id'] for m in models]
        if len(set(names))!=len(names):raise ValueError('unique source model identities required')
        for m in models:m['contract']=_source_model(m,custody)
        q=quantities.validate(doc['quantities'])
        if not 1<=len(q['weight_names'])<=16:raise ValueError('bounded named weight basis required')
        _,raw=custody.read(doc['events']);rows=_events(_json(raw),models,q)
        resolved=deepcopy(doc);resolved['models']=models
        _bins(resolved,models,q)
        # Bound additive second moments and stored tensors before any inference.
        dimensions=len(q['weight_names'])*(len(q['bins'])+2)
        tensor_cells=sum((len(m['contract']['features'])+m['contract']['source_output_operation']['complete_model_output_width'])*
            (len(m['controls'])+sum(r['eligible'][m['id']] for r in rows)) for m in models)
        if dimensions>256 or tensor_cells>200000:raise ValueError('declared joint moment/tensor population exceeds bounded supplied route; use complete native delivery')
        custody.finish();return resolved,rows,custody
    if doc.get('route')=='native-rivet':
        _keys(doc,('kind','route','native_task','source_bindings','native_output_paths','native_per_event_scores','source_semantics'))
        _text(doc['source_semantics'])
        if doc['native_per_event_scores']!='not_published_by_this_handoff':raise ValueError('native per-event scores cannot be invented')
        from . import existing_events
        t=doc['native_task'];existing_events.validate(t)
        if t['backend']!='rivet-built' or t.get('native_weight_cap')!=0:raise ValueError('reviewed built routine and all native weights required')
        if doc['native_output_paths']!=[o['path'] for o in t['observables']]:raise ValueError('complete exact requested native output census required')
        files=existing_events.inputs(t,base);members={str(Path(f).absolute()) for f in files}
        if type(doc['source_bindings']) is not list or not 2<=len(doc['source_bindings'])<=256:raise ValueError('complete declared native source/model bindings required')
        roles=[]
        for binding in doc['source_bindings']:
            _keys(binding,('role','provider','pin','source_expression'))
            if binding['role'] not in ('source','model','preprocessing','configuration') or binding['provider'] not in ('ONNX','TMVA'):raise ValueError('explicit original source inference role required')
            _text(binding['source_expression']);path,_=custody.read(binding['pin'])
            if str(path.absolute()) not in members:raise ValueError('classifier source/model outside exact admitted native build closure')
            roles.append(binding['role'])
        if not {'source','model'}<=set(roles):raise ValueError('original source and actual model assets required')
        custody.finish();return doc,files,custody
    raise ValueError('unsupported published classifier execution route')


def inputs(task,base):
    doc,rows,custody=_load(task,base)
    paths=[Path(f['path']) for f in custody.inventory()]
    return list(dict.fromkeys(paths+(rows if doc['route']=='native-rivet' else [])))


def _score(op,row):
    if op['kind']=='difference':return _num(row[op['positive_index']]-row[op['negative_index']])
    return _num(row[op['index']])


def _matches(score,conditions):
    operators={'>':lambda a,b:a>b,'>=':lambda a,b:a>=b,'<':lambda a,b:a<b,'<=':lambda a,b:a<=b}
    return all(operators[c['op']](score,c['value']) for c in conditions)


def _infer(doc,rows,custody):
    outputs={r['event_id']:{} for r in rows};runtimes=[];checks=[]
    for m in doc['models']:
        name=m['id'];c=m['contract'];op=c['source_output_operation']
        dtype=c['features'][0]['cast'];width=op['complete_model_output_width']
        controls=m['controls'];active=[r for r in rows if r['eligible'][name]]
        ordered=[r['values'] for r in controls]+[r['features'][name] for r in active]
        vectors=[ci.prepare_features(c,v)['values'] for v in ordered]
        _,raw=custody.read(c['model'])
        inferred=domains.onnx_rows(raw,vectors,input_name=c['model_static']['inputs'][0]['name'],
            output_name=c['model_static']['outputs'][0]['name'],dtype=dtype,
            feature_count=len(c['features']),output_width=width)
        if len(inferred['outputs'])!=len(vectors):raise ValueError('model executor omitted declared rows')
        runtimes.append({'model':name,**{k:v for k,v in inferred.items() if k!='outputs'}})
        for ctrl,actual in zip(controls,inferred['outputs']):
            ok=all(math.isclose(_num(a),_num(e),abs_tol=ctrl['atol'],rel_tol=ctrl['rtol']) for a,e in zip(actual,ctrl['expected_outputs']))
            checks.append({'model':name,'id':ctrl['id'],'expected_outputs':ctrl['expected_outputs'],'actual_outputs':actual,'passed':ok,'atol':ctrl['atol'],'rtol':ctrl['rtol']})
        for r,vector,rawout in zip(active,vectors[len(controls):],inferred['outputs'][len(controls):]):
            score=_score(op,rawout)
            if not m['score_range'][0]<=score<=m['score_range'][1]:raise ValueError('score outside declared source range')
            outputs[r['event_id']][name]={'prepared_values':vector,'complete_outputs':rawout,'score':score,
                'source_output_operation':op,'threshold_selected':score>op['threshold'] if op['kind']=='strict_score_threshold' else None}
        for r in rows:
            if not r['eligible'][name]:outputs[r['event_id']][name]=None
    records=[];traces=[]
    for r in rows:
        fills=[];matched=[]
        for i,b in enumerate(doc['score_bins']):
            modelout=outputs[r['event_id']][b['model']]
            if modelout is not None and _matches(modelout['score'],b['conditions']):fills.append([i+0.5]);matched.append(b['id'])
        records.append({k:r[k] for k in ('event_id','group_id','shard_id','weights')}|{'fills':fills})
        traces.append({**r,'inference':outputs[r['event_id']],'matched_bins':matched})
    return traces,records,quantities.calculate(doc['quantities'],records),runtimes,checks


def run_in_worker(task,base,out,*,worker_started):
    doc,rows,custody=_load(task,base);out=Path(out).absolute()
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents):raise ValueError('fresh ordinary classifier output required')
    # Outputs never overlap consumed scientific evidence, even through aliases.
    resolved=out.resolve(strict=False)
    if any(p.resolve().is_relative_to(resolved) for p in custody.facts):raise ValueError('output root overlaps original inputs')
    out.mkdir(parents=True,exist_ok=False)
    result={'kind':'published-classifier-delivery','status_scope':SCOPE,'route':doc['route'],
        'physics_validated':False,'training_executed':False,'native_bitwise_equivalence':False,
        'calibration_qualified':False,'source_semantics':doc['source_semantics'],'limitations':list(LIMITATIONS)}
    native_custody=None
    if doc['route']=='native-rivet':
        from . import existing_events
        native=existing_events.run_in_worker(doc['native_task'],base,out/'native',worker_started=worker_started)
        if native.get('physics_validated') is not False or native.get('status') not in ('passed','failed'):raise ValueError('native result authority or status differs')
        native_custody=_native_outputs(out/'native')
        result.update(status=native['status'],native=native,native_outputs=native_custody.inventory(),per_event_scores=None,
            per_event_scores_status='not_published_by_this_handoff',inference_execution='original_native_routine')
    else:
        traces,records,q,runtimes,checks=_infer(doc,rows,custody)
        result.update(status='passed' if all(c['passed'] for c in checks) else 'failed',
            events=traces,quantity_records=records,quantities=q,models=doc['models'],
            score_bins=doc['score_bins'],runtime=runtimes,reference_checks=checks,
            inference_execution='supplied_source_rows',population={'events':len(rows),
                'groups':len({r['group_id'] for r in rows}), 'weight_names':doc['quantities']['weight_names'],
                'models':len(doc['models']),'bins':len(doc['score_bins']),'unselected_events':sum(not r['fills'] for r in records)})
    result['inputs']=custody.inventory();custody.finish()
    from .analysis_response_features import _Emitted
    emitted=_Emitted(out);emitted.json(out/'published-classifier.json',result)
    output_path=out/'published-classifier.json';output_identity=_sig(output_path)
    emitted.finish();custody.finish()
    if native_custody is not None:native_custody.finish()
    # Final identity census closes later reads without blessing rehashed changes.
    custody.current()
    if native_custody is not None:_native_current(out/'native',native_custody)
    if any(p.is_symlink() for p in (output_path,*output_path.parents)) or _sig(output_path)!=output_identity:
        raise ValueError('ending published classifier commitment changed')
    return result


def run(task,base,out):
    if _load(task,base)[0]['route']=='native-rivet':raise ValueError('native execution requires ordinary science worker clock')
    return run_in_worker(task,base,out,worker_started=None)


def write_report(result,out):
    if result.get('kind')!='published-classifier-delivery' or result.get('physics_validated') is not False:raise ValueError('literal classifier delivery required')
    from .analysis_response_features import _Emitted
    e=_Emitted(out);e.json(Path(out)/'published-classifier-report.json',result)
    text='# Published classifier delivery\n\nRoute: '+result['route']+'\n\nStatus: '+result['status']+'\n\n'+'\n'.join('- '+x for x in LIMITATIONS)+'\n'
    e.bytes(Path(out)/'published-classifier-report.md',text.encode());e.finish()
    return [{'stem':'published-classifier-report','files':['published-classifier-report.json','published-classifier-report.md'],'normalization':'Declared complete event/group multiweight quantities or unchanged original native normalization'}]


def helper_declaration(task,base_dir,output_dir,*,_session=None):
    """Retain original optional historical-helper registration at the new path."""
    doc,_,_=_load(task,base_dir)
    if doc['route']!='native-rivet' or 'improvement_lineage' not in doc['native_task']:return None
    from . import native_incumbent
    return native_incumbent.helper_declaration(doc['native_task']['improvement_lineage'],base_dir,
        Path(output_dir)/'published-classifier'/'native',_session=_session)
