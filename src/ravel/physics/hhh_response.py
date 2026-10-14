"""Supplied trace interpretation, classifier manifests and event-group marks.

The consumer checks retained native observations. It performs no reconstruction,
random draws or model inference, and establishes no sampling law or calibration.
"""
import bisect,json,math
from . import classifier_inputs as ci
from .truth_reco_response import ResponseInputError

LIMITATIONS=['Source-bound observations only; native noninterference and physics qualification remain separate.',
             'Shared-event marks retain signed weights; no independent channel or marginal-error covariance law is inferred.']

def require(ok,why):
    if not ok:raise ResponseInputError(why)

def finite(v):
    require(type(v) in (int,float) and math.isfinite(v),'finite native scalar required');return v

def keys(d,ks):require(type(d) is dict and set(d)==set(ks),'closed complete trace fields required')

def decode(raw):
    def pairs(xs):
        out={}
        for k,v in xs:require(k not in out,'duplicate JSON key');out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False,'nonfinite JSON literal'))

def manifest(value):
    required={'schema_version','prefix','header','event_paths','classifiers','destinations','normalization_phase','identity_phase'}
    if not isinstance(value,dict) or not required<=set(value):raise ResponseInputError('supplied trace/classifier manifest required','missing_input')
    keys(value,required);require(type(value['schema_version']) is int and value['schema_version']==1,'trace manifest/v1 required')
    require(isinstance(value['prefix'],str) and value['prefix'] and '\n' not in value['prefix'] and isinstance(value['header'],dict),'explicit trace prefix/header required')
    require(isinstance(value['identity_phase'],str) and value['identity_phase'],'supplied native identity phase required')
    dests=value['destinations'];require(isinstance(dests,list) and dests and all(isinstance(x,str) and x for x in dests) and len(set(dests))==len(dests),'complete unique supplied destinations required')
    paths=value['event_paths'];require(isinstance(paths,list) and paths and len(paths)<=256,'complete supplied event dispositions required')
    for row in paths:
        keys(row,('id','phases','checks','allocation'));require(isinstance(row['id'],str) and row['id'] and isinstance(row['phases'],list) and row['phases'] and isinstance(row['checks'],list) and isinstance(row['allocation'],list) and len(row['allocation'])==len(dests),'complete disposition/check/allocation required')
        for phase in row['phases']:
            keys(phase,('phase','min','max'));require(isinstance(phase['phase'],str) and phase['phase'] and type(phase['min']) is int and type(phase['max']) is int and 0<=phase['min']<=phase['max']<=65536,'bounded supplied phase cardinalities required')
    classifiers=value['classifiers'];require(isinstance(classifiers,list) and 1<=len(classifiers)<=256,'explicit classifier population required')
    for row in classifiers:
        keys(row,('id','contract','select','features_phase','input_phase','output_phase'));require(all(isinstance(row[k],str) and row[k] for k in ('id','contract','features_phase','input_phase','output_phase')),'supplied classifier phase/contract identity required')
    require(len({r['id'] for r in paths})==len(paths) and len({r['id'] for r in classifiers})==len(classifiers),'unique disposition/classifier identifiers required')
    require(isinstance(value['normalization_phase'],str) and value['normalization_phase'],'supplied normalization phase required')
    return value

def evaluate(expr,context,depth=0,_budget=None):
    """Bounded data expressions only: no code, imports, calls or process access."""
    if _budget is None:_budget=[65536]
    _budget[0]-=1
    require(depth<=64 and _budget[0]>=0,'bounded source interpretation expression required')
    if not isinstance(expr,dict):return expr
    if set(expr)=={'literal'}:return expr['literal']
    if set(expr)=={'path'}:
        value=context
        require(isinstance(expr['path'],list) and len(expr['path'])<=64,'bounded explicit data path required')
        for key in expr['path']:
            require(isinstance(value,(dict,list)) and type(key) in (str,int),'literal trace data path required')
            try:value=value[key]
            except (KeyError,IndexError,TypeError) as exc:raise ResponseInputError('missing declared trace field','missing_input') from exc
        return value
    keys(expr,('op','args'));require(isinstance(expr['args'],list) and len(expr['args'])<=1024,'bounded interpretation operands required')
    op=expr['op']
    if op in ('map','all_items','any_items','sum_items'):
        require(len(expr['args'])==2,'collection expression arity required')
        population=evaluate(expr['args'][0],context,depth+1,_budget)
        require(isinstance(population,list) and len(population)<=65536,'bounded complete object/check population required')
        results=[evaluate(expr['args'][1],dict(context,item=item),depth+1,_budget) for item in population]
        if op=='map':return results
        if op=='sum_items':return finite(math.fsum(finite(v) for v in results))
        require(all(type(v) is bool for v in results),'boolean per-object predicates required')
        return all(results) if op=='all_items' else any(results)
    if op=='if':
        require(len(expr['args'])==3,'conditional arity required')
        return evaluate(expr['args'][1] if evaluate(expr['args'][0],context,depth+1,_budget) else expr['args'][2],context,depth+1,_budget)
    args=[evaluate(x,context,depth+1,_budget) for x in expr['args']]
    if op in ('eq','ne','lt','le','gt','ge','div','mod','sub'):
        require(len(args)==2,'binary expression arity required');a,b=args
        if op=='eq':return a==b
        if op=='ne':return a!=b
        for v in args:finite(v)
        if op=='lt':return a<b
        if op=='le':return a<=b
        if op=='gt':return a>b
        if op=='ge':return a>=b
        if op=='sub':return finite(a-b)
        if op=='div':require(b!=0,'nonzero supplied divisor required');return finite(a/b)
        require(type(a) is int and type(b) is int and b!=0,'integer nonzero remainder operands required');return -(abs(a)%abs(b)) if a<0 else abs(a)%abs(b)
    if op in ('and','or'):require(all(type(v) is bool for v in args),'boolean source checks required');return all(args) if op=='and' else any(args)
    if op=='not':require(len(args)==1 and type(args[0]) is bool,'unary boolean required');return not args[0]
    if op in ('add','mul'):
        require(args,'nonempty arithmetic operands required');value=0 if op=='add' else 1
        for v in args:finite(v);value=value+v if op=='add' else value*v;finite(value)
        return value
    if op=='len':require(len(args)==1 and isinstance(args[0],(list,dict,str)),'length operand required');return len(args[0])
    if op=='float32':require(len(args)==1,'cast arity required');return ci.cast(finite(args[0]),'float32')
    if op=='bin_label':
        require(len(args)==5,'bin-label score, edges, labels, upper endpoint and overflow required');score,edges,labels,upper,overflow=args;finite(score)
        require(isinstance(edges,list) and edges and all(type(v) in (int,float) and math.isfinite(v) for v in edges) and all(a<b for a,b in zip(edges,edges[1:])) and len(labels)==len(edges),'ordered complete supplied score bins required')
        return overflow if score<edges[0] or score>upper else labels[bisect.bisect_right(edges,score)-1]
    raise ResponseInputError('unsupported supplied interpretation operation')

def native_weight_names(names):
    require(type(names) is list and names and all(type(n) is str and n for n in names) and len(set(names))==len(names),'explicit original named weights required')
    require(not any(n.upper().startswith('IRREG') for n in names[1:]),'source-filtered variations cannot enter complete-weight mode')
    return ['',*names[1:]]

def destinations(value=None):return manifest(value)['destinations']

def source_contracts(contracts,value=None):
    value=manifest(value)
    require(isinstance(contracts,dict) and set(contracts)=={r['contract'] for r in value['classifiers']},'all supplied source classifier contracts required')
    for c in contracts.values():
        ci.admit(c,{},expected_contract_sha256=ci.digest(c),preprocess=False)
        require(c['source_output_operation'] is not None and c['features'],'complete scalar feature/output interpretation required')
    return contracts

def read_trace(raw,value=None):
    value=manifest(value);require(type(raw) is bytes and len(raw)<=64*1024*1024,'bounded retained native log required');records=[]
    for line in raw.decode().splitlines():
        if value['prefix'] in line:
            require(line.startswith(value['prefix']),'interleaved native trace');require(len(line.encode())<=1024*1024,'trace record ceiling')
            d=decode(line[len(value['prefix']):]);keys(d,('seq','event','phase','data'))
            require(type(d['seq']) is int and d['seq']==len(records)+1 and type(d['event']) is int,'complete ordered trace sequence');records.append(d)
    require(records and records[0]=={'seq':1,'event':0,'phase':'header','data':value['header']},'supplied source trace header required')
    require(records[-1]['phase']==value['normalization_phase'],'native finalization missing; partial population cannot succeed')
    return records

def inspect_event(rows,source_event,contracts,value=None):
    value=manifest(value);matched=[]
    for path in value['event_paths']:
        cursor=0;valid=True
        for phase in path['phases']:
            count=0
            while cursor<len(rows) and rows[cursor]['phase']==phase['phase']:cursor+=1;count+=1
            valid &= phase['min']<=count<=phase['max']
        if valid and cursor==len(rows):matched.append(path)
    require(len(matched)==1,'one complete supplied event phase path required');path=matched[0]
    phases={}
    for row in rows:phases.setdefault(row['phase'],[]).append(row['data'])
    require(len(phases.get(value['identity_phase'],[]))==1 and phases[value['identity_phase']][0]==source_event['native_identity'],'native event/complete weight identity differs from original census')
    context={'phases':phases,'source_event':source_event,'outputs':{}}
    for check in path['checks']:require(evaluate(check,context) is True,'supplied source interpretation check failed')
    checks=[]
    for model in value['classifiers']:
        if evaluate(model['select'],context) is not True:continue
        c=contracts[model['contract']]
        require(all(len(phases.get(model[k],[]))==1 for k in ('features_phase','input_phase','output_phase')),'complete selected model phase population required')
        features=phases[model['features_phase']][0];prepared=ci.admit(c,features,expected_contract_sha256=ci.digest(c))
        actual=phases[model['input_phase']][0];require(actual==prepared['values'],'actual normalized tensor differs from supplied source arithmetic')
        output=phases[model['output_phase']][0];width=c['source_output_operation']['complete_model_output_width']
        require(type(output) is list and len(output)==width,'complete returned native model output required')
        element_type=c['model_static']['outputs'][0]['element_type'];require(element_type in (1,11),'supported floating native output tensor required')
        cast='float32' if element_type==1 else 'float64'
        for v in output:finite(v);require(ci.cast(v,cast)==v,'native output source scalar retention differs')
        context['outputs'][model['id']]=output;checks.append({'model':model['id'],'contract_sha256':ci.digest(c),'features':prepared,'actual_input':actual,'actual_output':output})
    allocation=[finite(evaluate(expr,context)) for expr in path['allocation']]
    return {'disposition':path['id'],'allocation':allocation,'native_rows':rows,'feature_checks':checks}

def consume(raw,census,contracts,value=None):
    value=manifest(value);source_contracts(contracts,value)
    require(type(census) is list and 1<=len(census)<=20000,'complete original event population required')
    require(len({v['event_id'] for v in census})==len(census),'unique original subevent identities required')
    for e in census:
        keys(e,('event_id','group_id','weights','native_identity'));require(all(type(e[k]) is str and e[k] for k in ('event_id','group_id')),'explicit original event/group identities')
        require(type(e['weights']) is dict and e['weights'],'all original weights required')
        for v in e['weights'].values():finite(v)
        n=e['native_identity'];require(n['raw_weight_names']==census[0]['native_identity']['raw_weight_names'],'source weight population changed between events');keys(n,('event_number','raw_weight_names','raw_weights','selected_weight_names','selected_weights'))
        require(list(e['weights'])==n['raw_weight_names'] and list(e['weights'].values())==n['raw_weights'],'complete ordered original weight map required')
        require(n['selected_weight_names']==native_weight_names(n['raw_weight_names']) and n['selected_weights']==n['raw_weights'],'complete uncapped native weight identities required')
    records=read_trace(raw,value);parts=[];offset=1
    for i,e in enumerate(census,1):
        rows=[]
        while offset<len(records) and records[offset]['event']==i and records[offset]['phase']!=value['normalization_phase']:rows.append(records[offset]);offset+=1
        require(rows,'missing original event in trace');parts.append(inspect_event(rows,e,contracts,value))
    footers=records[offset:];names=census[0]['native_identity']['selected_weight_names'];require(len(footers)==len(names),'complete per-weight finalization required');final=[]
    for i,(footer,name) in enumerate(zip(footers,names)):
        require(footer['phase']==value['normalization_phase'] and footer['event']==len(census),'extra events or misplaced finalization')
        f=footer['data'];keys(f,('events','weight_index','weight_name','sumW','cross_section_pb','scale_factor'))
        require(f['events']==len(census) and f['weight_index']==i and f['weight_name']==name,'complete ordered native finalization differs')
        for k in ('sumW','cross_section_pb','scale_factor'):finite(f[k])
        require(f['sumW']!=0,'zero native normalization denominator');final.append(f)
    return {'events':len(census),'rows':[{**e,'allocation':p['allocation']} for e,p in zip(census,parts)],'event_details':parts,'source_normalization':final,'destinations':destinations(value),'source_header':records[0],'source_approximations':LIMITATIONS,'physics_validated':False,'native_noninterference_qualified':False}
