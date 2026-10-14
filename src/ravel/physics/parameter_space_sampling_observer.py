"""Recording-only wrappers around the exact released EasyScan interfaces.

No replacement sampler/likelihood/engine. All original functions are forwarded
once; raw records are written before dependent validation or the next call.
"""
import functools
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import stat
from ravel.physics import parameter_space_sampling_core as core
from ravel.physics import dataset_query_quantities as integrity
from ravel.workflow.state_io import atomic_json


def value(v):
    if v is None or type(v) in (str,bool,int):return v
    if isinstance(v,float):return float(v) if math.isfinite(v) else {'native_nonfinite':repr(float(v))}
    if type(v) is dict:return {str(k):value(x) for k,x in v.items()}
    if type(v) in (list,tuple):return [value(x) for x in v]
    if hasattr(v,'tolist'):return value(v.tolist())
    if hasattr(v,'item'):return value(v.item())
    return {'native_type':type(v).__name__}


def check_workspace(request):
    """Ending finite membership and immutable-byte checks for owned work copies.

    Native cards/outputs/backups and declared program logs are mutable. Native
    parallel copies share the same source census and are separately checked.
    """
    work=Path(request['work']);info=request['info'];c=request['config']
    allowed={q for p in c['programmes'] for q in [*p['inputs'],*p['outputs'],*p['intermediates'],*p['mutable_paths']]}
    allowed.update(q+'.ESbackup' for q in list(allowed));allowed.add('EASYSCAN.LOG')
    prefix=info['result_folder']+'/'
    workers=[('p'+str(i)+'_',info['parallel_folder']) for i in range(info['workers'])] if info['workers']>1 else []
    initial=request['initial_workspace']
    def scan():
        members={}
        for q in work.rglob('*'):
            if q.is_symlink() or not (q.is_file() or q.is_dir()):raise ValueError('nonordinary native work member')
            if q.is_file():members[q.relative_to(work).as_posix()]=q
        return members
    before=scan();immutable={}
    for rel,q in before.items():
        if rel.startswith(prefix) or rel in allowed:continue
        original=rel
        for worker,folder in workers:
            if rel.startswith(worker+folder+'/'):original=rel[len(worker):];break
        if original in allowed:continue
        if original not in initial:raise ValueError('unadmitted native work member: '+rel)
        if 'initial_modes' in request and q.stat().st_mode&0o777!=request['initial_modes'][original]:raise ValueError('immutable native work permission differs')
        immutable[str(q)]={'path':str(q),**initial[original]}
    # An immutable source disappearance is distinct from a native output miss.
    expected=set(initial)-allowed
    if not expected.issubset(before):raise ValueError('immutable native work member missing')
    if info['workers']>1:
        for worker,folder in workers:
            want={worker+r for r in expected if r.startswith(folder+'/')}
            if not want.issubset(before):raise ValueError('isolated native worker source member missing')
    integrity.asset_check(immutable)
    if set(scan())!=set(before):raise ValueError('native work namespace changed during ending reads')


class Observer:
    def __init__(self,request, *, counters=None):
        self.request=request;self.out=Path(request['output']);self.work=Path(request['work']);self.records=self.out/'records'
        self.records.mkdir(exist_ok=False)
        if counters is None:
            import multiprocessing
            counters={k:multiprocessing.get_context('fork').Value('q',0) for k in ('evaluations','programme_calls','proposals','raw_bytes','raw_members','failed')}
        self.counters=counters;self.sequence={};self.current={};self.current_worker={};self.method={};self.proposal={};self.samplers={};self.optimizer=None;self.workers=[];self.originals=[]
        import multiprocessing
        # Same existing fork-shared finite member reservation, with 72 bytes
        # per slot (path digest, intended content digest, size). No new process,
        # controller or unbounded cross-worker dictionary: ceiling100k/7.2MB.
        self.emission_rows=multiprocessing.get_context('fork').Array('B',72*request['config']['resources']['max_output_members'],lock=True)
        self.emitted=core.Emitted(self.out);self.emcee_export=False;self.emcee_physical=[]

    def _register(self,index,fact):
        rel=Path(fact['path']).relative_to(self.out).as_posix().encode('utf-8')
        raw=hashlib.sha256(rel).digest()+bytes.fromhex(fact['sha256'])+fact['size'].to_bytes(8,'big')
        with self.emission_rows.get_lock():self.emission_rows[(index-1)*72:index*72]=raw

    def _finish_emitted(self):
        # All workers publish the intended commitment before their write, using
        # the original shared raw-member counter. First rereads never establish
        # the parent baseline, including after a child has exited.
        n=self.counters['raw_members'].value
        with self.emission_rows.get_lock():raw=bytes(self.emission_rows[:n*72])
        expected={raw[i:i+32]:(raw[i+32:i+64].hex(),int.from_bytes(raw[i+64:i+72],'big')) for i in range(0,len(raw),72)}
        if len(expected)!=n or any(sha=='0'*64 for sha,size in expected.values()):raise ValueError('incomplete intended recorder commitments')
        def members():
            rows={}
            for root in (self.records,self.out/'raw-calls'):
                if not root.exists():continue
                for p in root.rglob('*'):
                    if p.is_symlink() or not (p.is_file() or p.is_dir()):raise ValueError('nonordinary emitted recorder member')
                    if p.is_file():rows[hashlib.sha256(p.relative_to(self.out).as_posix().encode('utf-8')).digest()]=p
            return rows
        found=members()
        if set(found)!=set(expected):raise ValueError('recorder emitted population differs')
        from ravel.workflow.research_cycle import _bounded_source_snapshot
        for key,p in found.items():
            _,data=_bounded_source_snapshot(p,64*1024**2);sha,size=expected[key]
            if len(data)!=size or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('ending recorder differs from intended bytes')
        if members()!=found:raise ValueError('recorder namespace changed during ending reads')
        self.emitted.finish()

    def reserve(self,key,limit):
        if self.counters['failed'].value:raise RuntimeError('prior observer recording failed; further native calls forbidden')
        cell=self.counters[key]
        with cell.get_lock():
            if cell.value>=limit:raise RuntimeError('declared native '+key+' ceiling reached')
            cell.value+=1;return cell.value

    def record(self,kind,data):
        pid=os.getpid();seq=self.sequence.get(pid,0)+1;self.sequence[pid]=seq
        q=self.records/(str(pid)+'-'+str(seq).zfill(8)+'-'+kind+'.json')
        try:
            payload={'schema_version':1,'pid':pid,'sequence':seq,'kind':kind,'current_evaluation':self.current.get(pid),**value(data)}
            raw=core.emission_bytes(payload)
            index=self.reserve('raw_members',self.request['config']['resources']['max_output_members'])
            cell=self.counters['raw_bytes']
            with cell.get_lock():
                if cell.value+len(raw)>self.request['config']['resources']['max_output_bytes']:raise RuntimeError('raw recording byte ceiling')
                cell.value+=len(raw)
            if q.exists():raise RuntimeError('observer record collision')
            self.emitted.json(q,payload,atomic_json,register=lambda fact:self._register(index,fact))
        except BaseException:
            self.counters['failed'].value=1;raise
        return q

    def capture(self,paths,tag):
        try:return self._capture(paths,tag)
        except BaseException:
            self.counters['failed'].value=1;raise

    def _capture(self,paths,tag):
        result=[];pid=os.getpid()
        for rel in paths:
            core.relative(rel);p=self.work/rel
            if not p.exists():result.append({'path':rel,'status':'missing'});continue
            if p.is_symlink() or not p.is_file() or p.stat().st_size>64*1024**2:raise ValueError('programme raw member unavailable/nonordinary/over64MiB')
            from ravel.workflow.research_cycle import _bounded_source_snapshot
            _,raw=_bounded_source_snapshot(p,64*1024**2)
            directory=self.out/'raw-calls'/str(pid)/(str(self.sequence.get(pid,0)+1).zfill(8)+'-'+tag)
            q=directory/rel;q.parent.mkdir(parents=True,exist_ok=True)
            index=self.reserve('raw_members',self.request['config']['resources']['max_output_members'])
            cell=self.counters['raw_bytes']
            with cell.get_lock():
                if cell.value+len(raw)>self.request['config']['resources']['max_output_bytes']:raise RuntimeError('raw recording byte ceiling')
                cell.value+=len(raw)
            self.emitted.bytes(q,raw,register=lambda fact:self._register(index,fact))
            s=p.stat();result.append({'path':rel,'status':'retained','sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),
                'retained_path':str(q.relative_to(self.out)),'identity':[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]})
        return result

    def bind(self,obj,name,wrapper):
        old=getattr(obj,name);self.originals.append((obj,name,old));setattr(obj,name,wrapper(old))

    def likelihood(self,fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            n=self.reserve('evaluations',self.request['config']['resources']['max_evaluations']);pid=os.getpid();self.current[pid]=n
            self.record('evaluation-begin',{'arguments':args,'keywords':kwargs})
            try:result=fn(*args,**kwargs)
            except BaseException as exc:self.record('evaluation-exception',{'exception':type(exc).__name__,'message':str(exc),'arguments_after':args});raise
            self.record('evaluation-return',{'return':result,'arguments_after':args});return result
        return wrapped

    def install_scanner(self,scanner):
        for name in ('onepointrun','onepointbatchrun','gridrun','randomrun','bestfitrun','mcmcrun','emceerun','dynestyrun','postprocessrun'):
            if not hasattr(scanner,name):continue
            def factory(fn):
                @functools.wraps(fn)
                def wrapped(*args,**kwargs):
                    bound=inspect.signature(fn).bind(*args,**kwargs);pid=os.getpid();self.method[pid]=fn.__name__
                    if fn.__name__=='emceerun':
                        self.emcee_export=False;self.emcee_physical=[]
                        native_prior=bound.arguments['Prior']
                        @functools.wraps(native_prior)
                        def observed_prior(cube,ndim,nparams):
                            unit=value(cube[:ndim]);result=native_prior(cube,ndim,nparams)
                            if self.emcee_export:
                                row={'unit_coordinates':unit,'physical_coordinates':value(cube[:ndim])}
                                self.record('emcee-export-prior',row);self.emcee_physical.append(row)
                            return result
                        bound.arguments['Prior']=observed_prior
                    self.record('scanner-begin',{'method':fn.__name__,'arguments':{k:v for k,v in bound.arguments.items() if k not in ('LnLike','Prior')}})
                    bound.arguments['LnLike']=self.likelihood(bound.arguments['LnLike'])
                    try:result=fn(*bound.args,**bound.kwargs)
                    except BaseException as exc:self.record('scanner-exception',{'method':fn.__name__,'exception':type(exc).__name__,'message':str(exc)});raise
                    if fn.__name__=='emceerun' and 'EMCEE' in self.samplers:
                        self.samplers['EMCEE']['physical_chain_rows']=self.emcee_physical;self.emcee_export=False
                    self.record('scanner-return',{'method':fn.__name__,'return':result});return result
                return wrapped
            self.bind(scanner,name,factory)
        def process_factory(fn):
            @functools.wraps(fn)
            def wrapped(processes):
                self.record('workers-before',{'count':len(processes)})
                try:return fn(processes)
                finally:
                    rows=[{'pid':p.pid,'exitcode':p.exitcode,'name':p.name} for p in processes]
                    self.workers.extend(rows);self.record('workers-after',{'workers':rows})
            return wrapped
        self.bind(scanner,'run_processes',process_factory)
        def save_factory(fn):
            @functools.wraps(fn)
            def wrapped(*args,**kwargs):
                b=inspect.signature(fn).bind(*args,**kwargs);self.record('save-begin',{'values':b.arguments['cube'],'table':str(getattr(b.arguments['data_file'],'name','')),'native_number':b.arguments['num'],'save_file':b.arguments['save_file']})
                result=fn(*args,**kwargs);self.record('save-return',{'return':result});return result
            return wrapped
        self.bind(scanner,'saveCube',save_factory)
        # Observe complete MCMC proposals, including draws outside the prior,
        # without changing/repeating a random draw or the source acceptance law.
        def gauss_factory(fn):
            @functools.wraps(fn)
            def wrapped(*args,**kwargs):
                result=fn(*args,**kwargs);pid=os.getpid()
                if self.method.get(pid,'mcmcrun' if self.request['info']['method']=='MCMC' else None)=='mcmcrun':
                    draws=self.proposal.setdefault(pid,[]);draws.append(value(result));n=self.request['info']['sampled_parameters']
                    if len(draws)==n:
                        self.reserve('proposals',self.request['config']['resources']['max_evaluations'])
                        self.record('mcmc-proposal',{'unit_coordinates':draws,'inside_prior':all(isinstance(v,(int,float)) and 0<=v<=1 for v in draws)});self.proposal[pid]=[]
                return result
            return wrapped
        self.bind(scanner,'gauss',gauss_factory)

    def install_program(self,cls):
        contracts=self.request['config']['programmes']
        def mapping(instance):
            name=instance.getProgName()
            selected=[p for p in contracts if self.request['info']['projection'][p['section']]['Program name']==name]
            if len(selected)!=1:raise ValueError('native programme does not bind unique declared section')
            return selected[0]
        def factory(method):
            def wrap(fn):
                @functools.wraps(fn)
                def wrapped(instance,*args,**kwargs):
                    p=mapping(instance);b=inspect.signature(fn).bind(instance,*args,**kwargs);prefix=b.arguments.get('i_process',b.arguments.get('ParallelAdd',self.current_worker.get(os.getpid(),'')));self.current_worker[os.getpid()]=prefix
                    if prefix and prefix not in ['p'+str(i)+'_' for i in range(self.request['info']['workers'])]:raise ValueError('unknown native worker prefix')
                    paths=[prefix+q for q in [*p['inputs'],*p['outputs'],*p['intermediates'],*p['mutable_paths']]]
                    if method=='RunProgram':
                        if not instance._executor:raise ValueError('detached native executor refused before programme call')
                        self.reserve('programme_calls',self.request['config']['resources']['max_programme_calls'])
                    before=self.capture(paths,p['section']+'-'+method+'-before')
                    self.record('programme-begin',{'section':p['section'],'method':method,'worker':prefix,'files':before})
                    try:result=fn(instance,*args,**kwargs)
                    except BaseException as exc:
                        after=self.capture(paths,p['section']+'-'+method+'-exception');self.record('programme-exception',{'section':p['section'],'method':method,'exception':type(exc).__name__,'message':str(exc),'files':after});raise
                    after=self.capture(paths,p['section']+'-'+method+'-after')
                    self.record('programme-return',{'section':p['section'],'method':method,'return':result,'files':after,'parameters_after':b.arguments.get('par')})
                    if method=='RunProgram' and result:
                        bm={r['path']:r for r in before};am={r['path']:r for r in after}
                        for rel in [prefix+q for q in [*p['outputs'],*p['intermediates']]]:
                            row=am[rel]
                            if row['status']=='missing' or row.get('identity')==bm[rel].get('identity'):raise ValueError('missing or stale current programme output: '+rel)
                        if p['status']=='phasetracer-xsm-a68b':
                            for rel in [prefix+q for q in p['outputs']]:self.record('phasetracer-status',core.phase_status((self.work/rel).read_bytes()))
                    return result
                return wrapped
            return wrap
        for name in ('WriteInputFile','RunProgram','ReadOutputFile','ReadBound','Recover'):
            self.bind(cls,name,factory(name))

    def install_sampler(self,module,attribute,method):
        def factory(fn):
            @functools.wraps(fn)
            def wrapped(*args,**kwargs):
                # Return the actual native object; only its invoked run method
                # is decorated. No proxy changes isinstance/identity semantics.
                obj=fn(*args,**kwargs);native=getattr(obj,method)
                @functools.wraps(native)
                def run(*aa,**kk):
                    self.record('sampler-begin',{'kind':attribute,'arguments':aa,'keywords':kk})
                    try:result=native(*aa,**kk)
                    except BaseException as exc:self.record('sampler-exception',{'kind':attribute,'exception':type(exc).__name__,'message':str(exc)});raise
                    if attribute=='EnsembleSampler':data={'chain_unit_coordinates':value(obj.get_chain()),'log_probability':value(obj.get_log_prob()),'acceptance_fraction':value(obj.acceptance_fraction)};key='EMCEE'
                    else:
                        rr=obj.results;data={k:value(getattr(rr,k,None)) for k in ('samples','logl','logwt','logz','logzerr','ncall','eff')};key='DYNESTY'
                    self.samplers[key]=data;self.record('sampler-return',{'method':method,'return':result,'complete_arrays':data})
                    if key=='EMCEE':self.emcee_export=True
                    return result
                setattr(obj,method,run);return obj
            return wrapped
        self.bind(module,attribute,factory)

    def restore(self):
        for obj,name,fn in reversed(self.originals):setattr(obj,name,fn)
        self.originals=[]

    def final(self,status,exception=None):
        self._finish_emitted()
        result={'schema_version':1,'status':status,'exception':exception,'counts':{k:c.value for k,c in self.counters.items()},'workers':self.workers,'samplers':self.samplers,'optimizer':self.optimizer,
            'recording_failed':bool(self.counters['failed'].value),'original_functions_forwarded_once':True,'algorithm_qualified':False,'rng_checkpoint_restored':False}
        self.emitted.json(self.out/'observation.json',result,atomic_json,replace=(self.out/'observation.json') in self.emitted.expected);self.emitted.finish();return result
