"""Closed mean consumer for the original native count/Gaussian experiment.

No ROOT import, integrand replacement, optimizer or sampling controller. The
existing admitted native worker supplies authenticated helpers/workspace and
the original regional loop. Native scalar-based algebra is not an independent
numerical reference for an arbitrary original function or joint integral.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import hashlib,json,math,os,time

KIND='source-graph-full-auxiliary-calibration/v1'
GRAPH_KIND='native-source-graph/v1'
SAMPLER='hybrid-original-knuth-root622-poissond/v1'
RNG='Python/random.Random MT19937 Knuth/Gaussian plus explicit local ROOT6.22 TRandom3/PoissonD large-count stream'
MAX_STATE_BYTES=256*1024**2
MAX_ONE_STATE_BYTES=65536

def require(ok,message):
    if not ok:raise ValueError(message)

def keys(value,fields,label):
    require(type(value)is dict and set(value)==set(fields),'closed '+label+' required')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def finite(value,label):
    require(type(value)in(int,float)and math.isfinite(value),'finite '+label+' required');return float(value)

def validate_rng_bytes(raw):
    require(0<len(raw)<=MAX_ONE_STATE_BYTES,'bounded native whole RNG serialization required')
    obj=json.loads(raw)
    require(obj.get('_typename')=='TRandom3'and type(obj.get('fMt'))is list and len(obj['fMt'])==624 and all(type(v)is int and 0<=v<2**32 for v in obj['fMt'])and type(obj.get('fCount624'))is int and 0<=obj['fCount624']<=624,'complete native TRandom3 words/position required')
    return obj

def validate_rng_states(result,buffers):
    """Consume authenticated exact buffers; no native replay or seed-only proof."""
    names=[]
    for row in result['rows']:
        previous=None
        for draw in row.get('native_sampler',{}).get('draws',[]):
            states={}
            for phase in ('before','after'):
                record=draw.get(phase,{})
                if record.get('status')=='written':
                    name=record['basename'];names.append(name);raw=buffers[name]
                    require(len(raw)==record['bytes']and hashlib.sha256(raw).hexdigest()==record['sha256'],'exact consumed native state subject differs')
                    obj=validate_rng_bytes(raw);states[phase]={'fMt':obj['fMt'],'fCount624':obj['fCount624']}
            if previous is not None and 'before'in states:require(states['before']==previous,'ordered native stream state continuity differs')
            previous=states.get('after')
    require(len(names)==len(set(names))and set(names)==set(buffers),'complete unique written native state census differs')
    return True

def original_state(response):
    d=response['document']
    state={p['name']:{'value':float(Fraction(p['initial'])),'minimum':float(Fraction(p['bounds'][0])),'maximum':float(Fraction(p['bounds'][1])),'constant':p['fixed']}for p in d['parameters']}
    state.update({'ravel_aux_'+str(i):{'value':0.,'minimum':float(Fraction(b[0])),'maximum':float(Fraction(b[1])),'constant':False}for i,b in enumerate(d['auxiliary']['eta_bounds'])})
    return state

def audit_point(point,response):
    keys(point,response['coordinates'],'full graph point')
    for name,p in original_state(response).items():
        value=finite(float(Fraction(point[name])),'graph coordinate')
        require(p['minimum']<=value<=p['maximum']and(not p['constant']or value==p['value']),'graph coordinate outside original fixed domain')
    return point

def cell(response):
    require(type(response)is dict and response.get('kind')==GRAPH_KIND,'authenticated native source graph required')
    return next(c for c in response['recipe']['cells']if c['id']==response['cell'])

def integral_count(response):
    c=cell(response);return len(c['components'])*len(c['law']['bins'])+sum(t['normalization']=='full_domain'for t in c['components'])

def native_seed(request,truth_id,ordinal,regional):
    return 1+regional.seed_for(request,truth_id,ordinal,'root-large-count-stream')%(2**32-1)

def seed_population(request,regional):
    rows=[{'truth_id':t['id'],'ordinal':j,'seed':native_seed(request,t['id'],j,regional)}for t in request['truths']for j in range(request['trials_per_truth'])]
    require(len({r['seed']for r in rows})==len(rows),'complete scheduled native seed collision; no reseeding')
    return rows

def validate(request,response,regional=None):
    if regional is None:
        from ravel.physics import regional_calibration as regional
    c=cell(response);d=response['document']
    require('expected_data'not in c and 'derivatives'not in c,'full auxiliary graph calibration uses supplied observed counts')
    extra={'native_readback_budget','count_sampler'}
    core={k:deepcopy(v)for k,v in request.items()if k not in extra}
    require(core.get('kind')==KIND,'explicit graph native-model calibration kind required')
    core['kind']=regional.KIND
    regional.validate(core,d,_native_graph=True)
    keys(request['native_readback_budget'],{'max_snapshots','max_integral_reads'},'native readback budget')
    b=request['native_readback_budget']
    require(all(type(v)is int and 0<=v<=100000000 for v in b.values()),'finite declared native readback limits required')
    keys(request['count_sampler'],{'kind','max_state_bytes'},'graph count sampler')
    require(request['count_sampler']['kind']==SAMPLER and type(request['count_sampler']['max_state_bytes'])is int and 0<=request['count_sampler']['max_state_bytes']<=MAX_STATE_BYTES,'explicit original/hybrid sampler and state byte bound required')
    seed_population(request,regional)
    return request

def prospective(request,response,regional=None):
    validate(request,response,regional)
    n=len(request['truths'])*request['trials_per_truth'];i=integral_count(response);b=len(response['document']['bins']);c=len(cell(response)['components'])
    return {'kind':KIND,'scheduled_toys':n,'maximum_top_level_profile_requests':2*n,
            'prospective_mean_snapshots':len(request['truths'])+3*n,'integral_scalars_per_snapshot':i,
            'maximum_explicit_integral_scalar_reads':i*(len(request['truths'])+3*n),
            'maximum_explicit_all_scalar_reads':(i+c*b+2*b)*(len(request['truths'])+3*n),
            'maximum_possible_rng_state_bytes':2*MAX_ONE_STATE_BYTES*b*n,
            'explicit_contribution_base_total_reads_per_snapshot':c*b+2*b,
            'truth_means':{'status':'pending_admitted_native_TOTAL_readback','reference':None},
            'requested_readback_budget':deepcopy(request['native_readback_budget']),
            'count_sampler':deepcopy(request['count_sampler']),
            'sampler_mean_scope':{'original_knuth':'0 < mean <= 1000','native_poissond_rejection':'1000 < mean < 1e9','gaussian_approximation_admitted':False},
            'native_internal_integral_evaluations':'unknown','native_internal_poisson_proposals':'unknown',
            'numerical_equivalence_qualified':False,'independent_source_reference_available':False,'coverage_qualified':False}

def audit_snapshot(snapshot,response):
    c=cell(response);d=response['document'];bins=d['bins'];names={b['id']for b in bins}
    require(snapshot.get('status')=='returned' and snapshot.get('source_graph_cell')==response['cell'] and snapshot.get('source_graph_recipe_sha256')==digest(response['recipe']),'complete exact native graph snapshot required')
    audit_point(snapshot['point'],response)
    rows=snapshot['integrals'];lookup={r['name']:r for r in rows}
    require(len(rows)==integral_count(response)and len(lookup)==len(rows),'full native numerator/denominator census required')
    keys(snapshot['base_means'],names,'native base means');keys(snapshot['totals'],names,'native TOTAL means')
    keys(snapshot['contributions'],{t['id']for t in c['components']},'all native contributions')
    aux=d['auxiliary'];point={n:Fraction(v)for n,v in snapshot['point'].items()}
    physical={n:Fraction(aux['observed'][i])+sum((Fraction(v)*point['ravel_aux_'+str(j)]for j,v in enumerate(aux['factor'][i])),Fraction())for i,n in enumerate(aux['names'])}
    reconstructed={b['id']:finite(snapshot['base_means'][b['id']],'base mean')for b in bins}
    for j,t in enumerate(c['components']):
        keys(snapshot['contributions'][t['id']],names,'every original bin contribution')
        den=finite(lookup['ravel_graph_den_'+str(j)]['value'],'full-domain denominator')if t['normalization']=='full_domain'else 1.
        require(den>0,'positive full-domain density denominator required')
        coefficient=math.prod(point[n]**power for n,power in t['powers'].items())
        for k,b in enumerate(bins):
            row=lookup['ravel_graph_int_'+str(j)+'_'+str(k)]
            require(row['component']==t['id']and row['status']is None and row['error']is None and row['relative_error']is None and row['evaluations']is None and row['numerical_equivalence_qualified']is False,'original integral identity/unknown numerical status required')
            exponent=sum((Fraction(v)*physical[n]for v,n in zip(t['log_response'][k],aux['names'])),Fraction())
            value=float(Fraction(t['coefficients'][k])*coefficient)*math.exp(float(exponent))*finite(row['value'],'raw bin integral')/den
            native=finite(snapshot['contributions'][t['id']][b['id']],'signed native contribution')
            require(abs(value-native)<=1e-10*(1+abs(value)),'native integral/coefficient/power/log-response contribution algebra differs')
            reconstructed[b['id']]+=native
    for name,value in reconstructed.items():
        native=finite(snapshot['totals'][name],'TOTAL mean')
        require(native>0 and abs(value-native)<=1e-10*(1+abs(value)),'complete signed native TOTAL algebra differs')
    require(snapshot['native_state_before']==snapshot['native_state_after'],'native mean readback changed complete workspace state')
    actual_reads={r['name']:r for r in snapshot['scalar_reads']}
    scalar_values={r['name']:r['value']for r in rows}
    for j,t in enumerate(c['components']):
        scalar_values.update({'ravel_graph_term_'+str(j)+'_'+str(i):snapshot['contributions'][t['id']][b['id']]for i,b in enumerate(bins)})
    for i,b in enumerate(bins):
        scalar_values['ravel_base_mean_'+str(i)]=snapshot['base_means'][b['id']];scalar_values['ravel_mean_'+str(i)]=snapshot['totals'][b['id']]
    require(set(actual_reads)==set(scalar_values)and len(actual_reads)==len(snapshot['scalar_reads'])and all(actual_reads[n]['status']=='returned'and actual_reads[n]['value']==v for n,v in scalar_values.items()),'retained raw scalar returns and complete graph values differ')
    actual={p['name']:p for p in snapshot['native_state_before']['parameters']}
    require(len(actual)==len(snapshot['native_state_before']['parameters']),'unique complete native state required')
    for name,value in snapshot['point'].items():
        p=actual[name];original=original_state(response)[name]
        require(p['kind']=='continuous'and p['value']==float(Fraction(value))and p['bounds']=={'min':original['minimum'],'max':original['maximum']}and(not original['constant']or p['constant']is True),'native readback is not at complete retained source point')
    require(snapshot['numerical_equivalence_qualified']is False and snapshot['independent_source_reference_available']is False,'native scalar audit cannot inherit independent numerical authority')
    return deepcopy(snapshot['totals'])

def mean_nll(point,observation,means,auxiliary_count):
    keys(observation['counts'],means,'same-toy complete counts')
    values=[]
    for name,mu in means.items():
        n=observation['counts'][name];require(type(n)is int and n>=0,'integer complete observations required')
        values.append(mu-n*math.log(mu)+math.lgamma(n+1))
    values.extend(.5*(float(Fraction(point['ravel_aux_'+str(i)]))-observation['globals']['ravel_aux_'+str(i)+'_In'])**2 for i in range(auxiliary_count))
    return finite(math.fsum(values),'native-mean NLL algebra')

class GraphLaw:
    """Worker-only closed strategy for the original loop, never caller supplied."""
    rng_name=RNG
    def __init__(self,ROOT,w,mc,response,request,expected,regional,state):
        validate(request,response,regional)
        self.ROOT=ROOT;self.w=w;self.mc=mc;self.response=response;self.request=request;self.expected=expected;self.regional=regional;self.state=state
        self.remaining_snapshots=0;self.remaining_integrals=0;self.active_sampler=None

    def start(self,result,save,out,deadline,initial):
        self.result=result;self.save=save;self.out=Path(out);self.deadline=deadline;self.initial=initial
        self.original_native_state=self.state.capture(self.w,self.mc)
        result.update(kind=KIND,source_graph_cell=self.response['cell'],source_graph_recipe_sha256=digest(self.response['recipe']),
                      initial_native_state=deepcopy(self.original_native_state),
                      native_truth_admission=[],native_seed_population=seed_population(self.request,self.regional),
                      native_readback_cost={'reserved_snapshots':0,'attempted_snapshots':0,'returned_snapshots':0,'reserved_integral_reads':0,'reserved_mean_scalar_reads':0,'snapshots':[]},
                      native_sampler_state_bytes=0,numerical_equivalence_qualified=False,independent_source_reference_available=False)
        self.save()

    def reserve(self,n):
        cost=self.result['native_readback_cost'];b=self.request['native_readback_budget'];i=integral_count(self.response)
        if cost['reserved_snapshots']+n>b['max_snapshots'] or cost['reserved_integral_reads']+n*i>b['max_integral_reads']:return False
        cost['reserved_snapshots']+=n;cost['reserved_integral_reads']+=n*i;cost['reserved_mean_scalar_reads']+=n*(len(cell(self.response)['components'])+2)*len(self.response['document']['bins']);self.remaining_snapshots+=n;self.remaining_integrals+=n*i;self.save();return True

    def snapshot(self,point,label):
        require(time.monotonic()<self.deadline and self.remaining_snapshots>0,'native graph snapshot reservation unavailable')
        self.remaining_snapshots-=1;self.remaining_integrals-=integral_count(self.response);cost=self.result['native_readback_cost']
        s={'sequence':len(cost['snapshots']),'label':label,'point':deepcopy(point),'status':'pending','source_graph_cell':self.response['cell'],'source_graph_recipe_sha256':digest(self.response['recipe']),
           'scalar_reads':[],'integrals':[],'base_means':{},'contributions':{},'totals':{},'numerical_equivalence_qualified':False,'independent_source_reference_available':False}
        cost['snapshots'].append(s);cost['attempted_snapshots']+=1;self.save()
        before=self.state.capture(self.w,self.mc);s['native_state_before']=before;self.save()
        try:
            self.current_snapshot=s
            s['integrals']=self.expected.source_graph_integrals(self.w,self.response,recorder=self);self.save()
            c=cell(self.response);bins=self.response['document']['bins']
            def read(name,target,key):
                fn=self.w.function(name);require(bool(fn),'original native mean/contribution absent')
                self.begin_scalar(name)
                v=float(fn.getVal());self.returned_scalar(v);target[key]=v if math.isfinite(v)else {'nonfinite_native_float':v.hex()};self.save();return finite(v,'native mean/contribution')
            for j,t in enumerate(c['components']):
                s['contributions'][t['id']]={}
                for i,b in enumerate(bins):read('ravel_graph_term_'+str(j)+'_'+str(i),s['contributions'][t['id']],b['id'])
            for i,b in enumerate(bins):
                read('ravel_base_mean_'+str(i),s['base_means'],b['id']);read('ravel_mean_'+str(i),s['totals'],b['id'])
            s['native_state_after']=self.state.capture(self.w,self.mc);s['status']='returned';self.save()
            audit_snapshot(s,self.response);cost['returned_snapshots']+=1;self.save();return s
        except BaseException as exc:
            s.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});self.save();raise
        finally:self.state.restore(self.w,self.mc,before)

    def begin_scalar(self,name):
        require(time.monotonic()<self.deadline,'aggregate wall exhausted before reserved native scalar')
        self.current_snapshot['scalar_reads'].append({'name':name,'status':'pending'});self.save()

    def returned_scalar(self,value):
        self.current_snapshot['scalar_reads'][-1].update(status='returned',value=value if math.isfinite(value)else {'nonfinite_native_float':value.hex()});self.save()

    def returned_integrals(self,rows):
        self.current_snapshot['integrals']=deepcopy(rows);self.save()

    def admit(self):
        require(self.reserve(len(self.request['truths'])),'complete native truth admission reservation unavailable')
        for truth in self.request['truths']:
            row={'truth_id':truth['id'],'status':'pending'};self.result['native_truth_admission'].append(row);self.save()
            self.state.restore(self.w,self.mc,self.original_native_state)
            for name,value in truth['point'].items():self.w.var(name).setVal(float(Fraction(value)))
            s=self.snapshot(truth['point'],'admission:'+truth['id']);row.update(snapshot=s)
            require(all(0<v<1e9 for v in s['totals'].values()),'graph mean outside original/hybrid Poisson scope; no Gaussian substitute')
            row['status']='admitted'
            self.save()
        self.state.restore(self.w,self.mc,self.original_native_state)

    def reserve_toy(self,row):
        large=[b['id']for b in self.response['document']['bins']if self.truth_means(row['truth_id'])[b['id']]>1000 and not(b['role']=='mc_auxiliary'and self.request['auxiliary_mode']=='conditional')]
        if self.result['native_sampler_state_bytes']+2*MAX_ONE_STATE_BYTES*len(large)>self.request['count_sampler']['max_state_bytes']:return False
        if not self.reserve(3):return False
        row['native_reservation']={'snapshots':3,'integral_reads':3*integral_count(self.response),'maximum_rng_state_bytes':2*MAX_ONE_STATE_BYTES*len(large),'large_count_channels':large};self.save();return True

    def truth_means(self,truth_id):
        return next(x['snapshot']['totals']for x in self.result['native_truth_admission']if x['truth_id']==truth_id and x['status']=='admitted')

    def begin_toy(self,row,truth):
        self.current_row=row;self.state.restore(self.w,self.mc,self.original_native_state)
        for name,value in truth['point'].items():self.w.var(name).setVal(float(Fraction(value)))
        row['source_graph_truth_readback']=self.snapshot(truth['point'],'toy:'+row['truth_id']+':'+str(row['ordinal'])+':truth')
        sampler={'kind':SAMPLER,'seed':native_seed(self.request,row['truth_id'],row['ordinal'],self.regional),'draws':[],
                 'internal_proposals':None,'original_count_seeds_unused_for_large_counts':[]}
        row['native_sampler']=sampler;self.save();self.active_sampler=None
        return row['source_graph_truth_readback']['totals']

    def serialize_rng(self,rng,draw,phase):
        name='ravel_calibration_rng_'+str(self.current_row['truth_id'])+'_'+str(self.current_row['ordinal'])+'_'+str(draw['ordinal'])+'_'+phase+'.json'
        record={'basename':name,'status':'pending_write'};draw[phase]=record;self.save()
        raw=str(self.ROOT.TBufferJSON.ConvertToJSON(rng,0)).encode()
        require(0<len(raw)<=MAX_ONE_STATE_BYTES,'bounded native whole RNG serialization required')
        validate_rng_bytes(raw)
        require(self.result['native_sampler_state_bytes']+len(raw)<=self.request['count_sampler']['max_state_bytes'],'native RNG state byte budget exhausted')
        path=self.out.parent/name
        require(not any(p.is_symlink()for p in (path,*path.parents)),'native state output traverses symlink')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(descriptor,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
        record.update(status='written',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw));self.result['native_sampler_state_bytes']+=len(raw);self.save()

    def poisson(self,mean,rng,channel):
        if mean<=1000:
            value=self.regional.poisson(mean,rng)
            self.check_count_domain(channel,value)
            return value
        require(1000<mean<1e9,'native rejection Poisson scope required; no Gaussian approximation')
        sampler=self.current_row['native_sampler']
        if self.active_sampler is None:self.active_sampler=self.ROOT.TRandom3(sampler['seed'])
        draw={'ordinal':len(sampler['draws']),'channel':channel,'mean':mean,'status':'pending','internal_proposals':None}
        sampler['draws'].append(draw);sampler['original_count_seeds_unused_for_large_counts'].append('count:'+channel);self.save()
        self.serialize_rng(self.active_sampler,draw,'before')
        require(time.monotonic()<self.deadline,'aggregate native deadline before large-count draw')
        value=float(self.active_sampler.PoissonD(mean));draw['return']=value if math.isfinite(value)else {'nonfinite_native_float':value.hex()};draw['status']='returned';self.save()
        self.serialize_rng(self.active_sampler,draw,'after')
        require(math.isfinite(value)and 0<=value<=2**53-1 and int(value)==value,'finite exactly representable native Poisson integer required')
        self.check_count_domain(channel,value)
        draw['status']='checked';self.save();return int(value)

    def check_count_domain(self,channel,value):
        var=self.w.var('n_obs_bin'+channel)
        require(bool(var)and float(var.getMin())<=value<=float(var.getMax()),'sampled count outside original native observable domain; no clipping/expansion')

    def fitted(self,state,label):return self.snapshot({n:s['value']for n,s in state.items()},label)

    def reset_profile(self,observation):
        same_toy=deepcopy(self.original_native_state)
        values={'n_obs_bin'+n:v for n,v in observation['counts'].items()}
        values.update(observation['globals'])
        for p in same_toy['parameters']:
            if p['name']in values:p['value']=float(values[p['name']])
        self.state.restore(self.w,self.mc,same_toy)

    def classify(self,row,initial):
        return classify(self.request,self.response,row,initial,self.expected,self.regional)

    def finish(self):
        require(self.state.capture(self.w,self.mc)==self.original_native_state,'ending complete source graph workspace state differs')
        self.result['final_native_state']=self.state.capture(self.w,self.mc);self.save()

def classify(request,response,row,initial,expected,regional):
    d=response['document'];truth=next(t for t in request['truths']if t['id']==row['truth_id'])
    native_truth=audit_snapshot(row['source_graph_truth_readback'],response)
    regional._check_observation(request,d,row,_native_truth_means=native_truth,_native_rng=RNG)
    regional._check_means(row['native_truth_means'],native_truth,'complete native generating means')
    poi=next(p['name']for p in d['parameters']if p['role']=='poi');mu=float(Fraction(truth['point'][poi]));values={}
    for role in ('free','fixed'):
        r=row[role];regional._check_fit(r,initial,poi,None if role=='free'else mu,expected)
        require(r['counts']==row['observation']['counts']and r['globals']==row['observation']['globals'],'profile changed same-toy complete observations')
        require(r['source_graph_readback']['point']=={n:s['value']for n,s in r['state'].items()},'native mean snapshot is not at retained fitted state')
        means=audit_snapshot(r['source_graph_readback'],response);regional._check_means(r['native_means'],means,'native fitted TOTAL means')
        values[role]=mean_nll(r['source_graph_readback']['point'],row['observation'],means,len(d['auxiliary']['names']))
    native_delta=finite(row['fixed']['nll'],'fixed NLL')-finite(row['free']['nll'],'free NLL');algebra_delta=values['fixed']-values['free'];q=2*native_delta
    row.update(raw_q=q,native_mean_nll=values,native_mean_q=2*algebra_delta,native_mean_contrast_discrepancy=native_delta-algebra_delta,
               numerical_equivalence_qualified=False,independent_source_reference_available=False)
    band=float(Fraction(request['nll_absolute_tolerance']))+float(Fraction(request['nll_relative_tolerance']))*max(abs(native_delta),abs(algebra_delta))
    require(abs(native_delta-algebra_delta)<=band,'native-mean count/Gaussian NLL factorization contrast disagrees')
    require(q>=0,'negative raw q; free minimum/globality unresolved')
    cutoff=float(Fraction(request['critical_q']));require(abs(q-cutoff)>float(Fraction(request['numerical_margin'])),'cutoff inclusion within numerical ambiguity margin')
    row['status']='included'if q<=cutoff else 'excluded';return row

def validate_delivery(result,response,request,expected,regional):
    """Authenticate complete native-model receipts, never replay native draws."""
    validate(request,response,regional)
    require(result.get('kind')==KIND and result.get('status')=='delivered'and result.get('request')==request and result.get('source_graph_cell')==response['cell']and result.get('source_graph_recipe_sha256')==digest(response['recipe']),'complete current original graph calibration delivery required')
    require(result['coverage_qualified']is False and result['optimizer_globality_qualified']is False and result['numerical_equivalence_qualified']is False and result['independent_source_reference_available']is False,'native model delivery cannot inherit independent numerical/physics authority')
    require(result['profile_policy']==expected.PROFILE_POLICY and result['native_seed_population']==seed_population(request,regional),'original profile/complete seed policy changed')
    d=response['document'];initial=original_state(response)
    require(result['initial_state']==initial and result['original_counts']=={b['id']:float(b['observed'])for b in d['bins']}and result['original_globals']=={'ravel_aux_'+str(i)+'_In':{'value':0.,'constant':True,'has_min':False,'has_max':False}for i in range(len(d['auxiliary']['names']))},'original source state/data/global law changed')
    require(result['final_state']==result['initial_state']and result['final_counts']==result['original_counts']and result['final_globals']==result['original_globals']and result['final_native_state']==result['initial_native_state'],'ending original full workspace state/data changed')
    # Readbacks are consumed in one reserved sequence. Failed prefixes retain
    # their original returns/errors; only COMPLETE returned snapshots can audit
    # a resolved trial. No omitted call is invented from a successful scalar.
    cost=result['native_readback_cost'];keys(cost,{'reserved_snapshots','attempted_snapshots','returned_snapshots','reserved_integral_reads','reserved_mean_scalar_reads','snapshots'},'native readback cost')
    snapshots=cost['snapshots'];require(type(snapshots)is list and all(s.get('sequence')==i and s.get('status')in('returned','failed')for i,s in enumerate(snapshots)),'complete ordered native readback attempts required')
    require(len({s['label']for s in snapshots})==len(snapshots),'duplicate readback operation')
    integral_names=[];c_=cell(response)
    for j,term in enumerate(c_['components']):
        if term['normalization']=='full_domain':integral_names.append('ravel_graph_den_'+str(j))
        integral_names += ['ravel_graph_int_'+str(j)+'_'+str(i)for i in range(len(d['bins']))]
    scalar_names=integral_names+['ravel_graph_term_'+str(j)+'_'+str(i)for j in range(len(c_['components']))for i in range(len(d['bins']))]+[name+str(i)for i in range(len(d['bins']))for name in ('ravel_base_mean_','ravel_mean_')]
    for snapshot in snapshots:
        reads=snapshot['scalar_reads'];require([r['name']for r in reads]==scalar_names[:len(reads)]and all(r['status']=='returned'for r in reads[:-1])and all(r['status']in('pending','returned')for r in reads),'complete ordered reserved scalar prefix differs')
        if snapshot['status']=='returned':
            require(len(reads)==len(scalar_names)and all(r['status']=='returned'for r in reads),'successful snapshot omitted actual scalar calls')
            audit_snapshot(snapshot,response)
        else:require(type(snapshot.get('error'))is dict,'failed original snapshot error absent')
    require(all(type(cost[n])is int and cost[n]>=0 for n in ('attempted_snapshots','returned_snapshots','reserved_snapshots','reserved_integral_reads','reserved_mean_scalar_reads'))and cost['attempted_snapshots']==len(snapshots)and cost['returned_snapshots']==sum(s['status']=='returned'for s in snapshots)and cost['returned_snapshots']<=cost['attempted_snapshots']<=cost['reserved_snapshots']<=request['native_readback_budget']['max_snapshots']and cost['reserved_mean_scalar_reads']==cost['reserved_snapshots']*(len(cell(response)['components'])+2)*len(d['bins'])and cost['reserved_integral_reads']==cost['reserved_snapshots']*integral_count(response)<=request['native_readback_budget']['max_integral_reads'],'complete explicit native mean cost census differs')
    admissions=result['native_truth_admission'];require([r['truth_id']for r in admissions]==[t['id']for t in request['truths']]and all(r['status']=='admitted'for r in admissions),'all original native generating truths required')
    labels=[];lookup={s['label']:s for s in snapshots}
    for admission,truth in zip(admissions,request['truths']):
        label='admission:'+truth['id'];labels.append(label)
        require(admission['snapshot']==lookup[label]and admission['snapshot']['point']==truth['point']and all(0<v<1e9 for v in audit_snapshot(admission['snapshot'],response).values()),'complete ordered admitted native truth differs')
    requests=sum(role in row for row in result['rows']for role in ('free','fixed'));require(result['top_level_profile_requests']==requests and requests<=2*len(result['rows']),'full profile request census differs')
    state_bytes=0;reserved_toys=0
    for row in result['rows']:
        truth=next(t for t in request['truths']if t['id']==row['truth_id']);prefix='toy:'+row['truth_id']+':'+str(row['ordinal'])+':'
        large=[b['id']for b in d['bins']if next(a['snapshot']['totals'][b['id']]for a in admissions if a['truth_id']==row['truth_id'])>1000 and not(b['role']=='mc_auxiliary'and request['auxiliary_mode']=='conditional')]
        if row['status']=='unissued':
            require('native_reservation'not in row and not any(label.startswith(prefix)for label in lookup),'unissued slot consumed native readback work')
            continue
        reserved_toys+=1
        require(row['native_reservation']=={'snapshots':3,'integral_reads':3*integral_count(response),'maximum_rng_state_bytes':2*MAX_ONE_STATE_BYTES*len(large),'large_count_channels':large},'whole-toy native reservation differs')
        ordered=[prefix+role for role in ('truth','free','fixed')];actual=[label for label in lookup if label.startswith(prefix)]
        require(actual==ordered[:len(actual)],'same-toy native readback stage/order differs');labels+=actual
        if 'source_graph_truth_readback'in row:
            require(row['source_graph_truth_readback']==lookup[prefix+'truth']and row['source_graph_truth_readback']['point']==truth['point'],'same-toy truth readback differs')
        for role in ('free','fixed'):
            if 'source_graph_readback'in row.get(role,{}):require(row[role]['source_graph_readback']==lookup[prefix+role],'fitted native readback identity differs')
        sampler=row.get('native_sampler')
        if sampler is not None:
            keys(sampler,{'kind','seed','draws','internal_proposals','original_count_seeds_unused_for_large_counts'},'native sampler receipt')
            require(sampler['kind']==SAMPLER and sampler['seed']==native_seed(request,row['truth_id'],row['ordinal'],regional)and sampler['internal_proposals']is None,'original native stream seed/proposal semantics differ')
            draws=sampler['draws'];require(len(draws)<=len(large)and [v['channel']for v in draws]==large[:len(draws)]and sampler['original_count_seeds_unused_for_large_counts']==['count:'+v['channel']for v in draws],'complete ordered large-count stream census differs')
            for i,draw in enumerate(draws):
                keys(draw,{'ordinal','channel','mean','status','internal_proposals'}|({'before'}if 'before'in draw else set())|({'after'}if 'after'in draw else set())|({'return'}if 'return'in draw else set()),'native draw receipt')
                require(draw['ordinal']==i and draw['internal_proposals']is None and draw['status']in('pending','returned','checked')and draw['mean']==row['source_graph_truth_readback']['totals'][draw['channel']],'retained draw identity/mean differs')
                for phase in ('before','after'):
                    record=draw.get(phase)
                    if record is not None:
                        require(record['basename']=='ravel_calibration_rng_'+row['truth_id']+'_'+str(row['ordinal'])+'_'+str(i)+'_'+phase+'.json'and record['status']in('pending_write','written'),'native state write identity differs')
                        if record['status']=='written':
                            keys(record,{'basename','status','sha256','bytes'},'native RNG state file receipt')
                            require(type(record['bytes'])is int and 0<record['bytes']<=MAX_ONE_STATE_BYTES and type(record['sha256'])is str and len(record['sha256'])==64,'bounded whole native state receipt required');state_bytes+=record['bytes']
                if draw['status']=='checked':
                    require(all(draw.get(phase,{}).get('status')=='written'for phase in ('before','after')),'checked draw lacks complete native state custody')
                    value=finite(draw['return'],'native Poisson return');require(0<=value<=2**53-1 and int(value)==value,'native Poisson return erased or noninteger')
                    if 'observation'in row:require(row['observation']['counts'][draw['channel']]==int(value),'native draw and complete observation differ')
        if 'observation'in row:
            truth_means=audit_snapshot(row['source_graph_truth_readback'],response);regional._check_observation(request,d,row,_native_truth_means=truth_means,_native_rng=RNG)
            require(sampler is not None and len(sampler['draws'])==len(large)and all(v['status']=='checked'for v in sampler['draws']),'complete observation omitted native draws')
        if row['status']in('included','excluded'):
            require(actual==ordered,'resolved slot omitted native readbacks')
            copied=deepcopy(row);classify(request,response,copied,result['initial_state'],expected,regional)
            diagnostics={'native_mean_nll','native_mean_q','native_mean_contrast_discrepancy'}
            require({k:v for k,v in copied.items()if k not in diagnostics}=={k:v for k,v in row.items()if k not in diagnostics},'persisted raw q/disposition differs')
            keys(row['native_mean_nll'],('free','fixed'),'retained native-mean NLL')
            native_delta=row['fixed']['nll']-row['free']['nll'];saved_delta=row['native_mean_nll']['fixed']-row['native_mean_nll']['free'];current_delta=copied['native_mean_nll']['fixed']-copied['native_mean_nll']['free']
            band=float(Fraction(request['nll_absolute_tolerance']))+float(Fraction(request['nll_relative_tolerance']))*max(abs(native_delta),abs(saved_delta),abs(current_delta))
            require(all(abs(finite(row['native_mean_nll'][role],'retained NLL')-copied['native_mean_nll'][role])<=band for role in ('free','fixed'))and row['native_mean_q']==2*saved_delta and row['native_mean_contrast_discrepancy']==native_delta-saved_delta and abs(native_delta-saved_delta)<=band,'retained native-mean algebra diagnostics differ')
    require(labels==[s['label']for s in snapshots]and cost['reserved_snapshots']==len(request['truths'])+3*reserved_toys,'full actual native operation/reservation census differs')
    require(result['native_sampler_state_bytes']==state_bytes<=request['count_sampler']['max_state_bytes'],'full native state byte census differs')
    require(result['summary']==regional.summarize(request,result['rows']),'full failure-inclusive scheduled denominator differs')
    return result
