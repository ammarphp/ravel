"""Ordinary supplied instrumentation and retained event-response consumption.

Native production is composed through existing routine-build/rivet-built. This
adapter never compiles, launches Rivet, loads ORT or creates detector responses.
"""
import hashlib
import json
import math
import os
from pathlib import Path
from . import classifier_inputs as ci, hhh_native_trace as native, hhh_response as response
from ravel.workflow.state_io import atomic_json

MAX_EMITTED_BYTES = 320*1024*1024


def _json_bytes(value):
    # Lossless compact full-cohort representation; committed before writer.
    # Original scientific input/native log bounds remain separately 64 MiB.
    return (json.dumps(value,separators=(',', ':'),allow_nan=False)+'\n').encode('utf-8')


class _Emitted:
    """Bind intended bytes before writes; never establish truth from a reread.

    This is output integrity under the ordinary stable-descriptor reader, not an
    adversarial filesystem sandbox. The caller still owns its full attempt.
    """
    def __init__(self,root):
        self.root=Path(root).absolute();self.expected={}

    def _commit(self,path,raw):
        path=Path(path).absolute()
        response.require(path.is_relative_to(self.root) and path!=self.root and '..' not in path.parts,'emitted path outside owned output')
        response.require(type(raw) is bytes and len(raw)<=MAX_EMITTED_BYTES,'bounded exact emitted bytes required')
        response.require(path not in self.expected and not path.exists() and not path.is_symlink(),'fresh single-write emitted member required')
        response.require(not any(p.is_symlink() for p in path.parents),'emitted ancestor symlink')
        fact={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        self.expected[path]=fact
        return path,fact

    def _check(self,path):
        fact=self.expected[path];raw=ci.bounded_read(path,MAX_EMITTED_BYTES)
        response.require(len(raw)==fact['bytes'] and hashlib.sha256(raw).hexdigest()==fact['sha256'],'generated output differs from committed bytes: '+str(path))

    def bytes(self,path,raw):
        path,fact=self._commit(path,raw);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);self._check(path)
        return dict(fact)

    def json(self,path,value):
        return self.bytes(path,_json_bytes(value))

    def inventory(self):
        return [dict(self.expected[p]) for p in sorted(self.expected)]

    def finish(self,*,exact_tree=False):
        for path in self.expected:self._check(path)
        if exact_tree:
            members=list(self.root.rglob('*'))
            response.require(not any(p.is_symlink() for p in members),'generated tree contains an uncommitted link')
            response.require({p for p in members if p.is_file()}==set(self.expected),'generated tree contains uncommitted or missing files')


def _verify_delivery(result):
    """Recheck a completed source/trace population before and after reporting."""
    response.require(ci.bounded_read(Path(result['delivery_path']),MAX_EMITTED_BYTES)==_json_bytes(result),'persisted delivery differs from returned result')
    for fact in result['generated_outputs']:
        response.keys(fact,('path','sha256','bytes'))
        raw=ci.bounded_read(Path(fact['path']),MAX_EMITTED_BYTES)
        response.require(len(raw)==fact['bytes'] and hashlib.sha256(raw).hexdigest()==fact['sha256'],'changed completed generated member')


def validate(task):
    response.keys(task,('schema_version','operation','input','input_sha256'))
    response.require(type(task['schema_version']) is int and task['schema_version']==1 and task['operation'] in ('prepare-source','consume-traces'),'closed analysis-response task')
    response.require(type(task['input']) is str and task['input'],'input path required')
    response.require(type(task['input_sha256']) is str and len(task['input_sha256'])==64 and all(x in '0123456789abcdef' for x in task['input_sha256']),'input SHA256 required')
    return task

def _pin(pin,base,limit=64*1024*1024):
    response.keys(pin,('path','sha256'));p=Path(pin['path']);p=p if p.is_absolute() else Path(base)/p
    raw=ci.bounded_read(p,limit);response.require(hashlib.sha256(raw).hexdigest()==pin['sha256'],'changed input bytes: '+str(p))
    return p.resolve(),raw

def supplied_descriptor(d,base):
    if 'instrumentation' not in d:raise response.ResponseInputError('supplied instrumentation package required','missing_input')
    descriptor=response.decode(_pin(d['instrumentation'],base,4*1024*1024)[1])
    response.keys(descriptor,('schema_version','routine','instrumented_routine','instrumentation','trace','models','final_histograms','build','runtime_version','analysis_options','normalization_scale','beam_pdg','beam_energy_gev','limitations','coordinate_fields','study'))
    response.require(type(descriptor['schema_version']) is int and descriptor['schema_version']==1,'instrumentation package/v1 required')
    import re
    for k in ('routine','instrumented_routine'):
        response.require(isinstance(descriptor[k],str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',descriptor[k]),'explicit source/instrumented routine identity required')
    response.manifest(descriptor['trace'])
    response.require(descriptor['trace']['header']=={'schema':1,'analysis':descriptor['routine'],'source_sha256':descriptor['instrumentation']['source_sha256']},'trace header must bind original source identity')
    response.require(isinstance(descriptor['models'],dict),'complete supplied model asset population required')
    for row in descriptor['models'].values():
        response.keys(row,('filename','contract'));response.require(isinstance(row['filename'],str) and Path(row['filename']).name==row['filename'] and row['filename'] not in ('.','..') and row['filename'].endswith('.onnx'),'safe supplied model asset basename required')
    response.require(isinstance(descriptor['final_histograms'],list) and descriptor['final_histograms'] and len(set(descriptor['final_histograms']))==len(descriptor['final_histograms']) and all(isinstance(v,str) and v.startswith('/'+descriptor['instrumented_routine']+'/') for v in descriptor['final_histograms']),'complete supplied final native output census required')
    from .truth_reco_response import study_contract
    study_contract(descriptor['study'])
    response.keys(descriptor['build'],('compile_unit','output','flags'))
    for key in ('compile_unit','output'):
        response.require(isinstance(descriptor['build'][key],str) and Path(descriptor['build'][key]).name==descriptor['build'][key] and descriptor['build'][key] not in ('.','..'),'safe supplied build member required')
    response.require(isinstance(descriptor['runtime_version'],str) and descriptor['runtime_version'] and isinstance(descriptor['analysis_options'],dict),'explicit native runtime/options required')
    response.finite(descriptor['normalization_scale']);response.require(descriptor['normalization_scale']>0,'positive supplied source normalization scale required')
    response.require(isinstance(descriptor['coordinate_fields'],dict) and all(isinstance(v,list) and v for v in descriptor['coordinate_fields'].values()),'explicit producer coordinate field paths required')
    response.require(isinstance(descriptor['limitations'],list) and all(isinstance(v,str) for v in descriptor['limitations']),'supplied source interpretation limits required')
    return descriptor


def document(task,base):
    validate(task);p,raw=_pin({'path':task['input'],'sha256':task['input_sha256']},base,4*1024*1024);d=response.decode(raw);paths={p:raw}
    def walk(x):
        if isinstance(x,dict):
            if set(x)=={'path','sha256'}:
                q,b=_pin(x,p.parent);paths[q]=b
            else:
                for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(d)
    required=('schema_version','instrumentation','source','info','reference','models','contracts','dependencies') if task['operation']=='prepare-source' else ('schema_version','instrumentation','prepared','events','metadata','contracts','anchors','axes','reference_point','nominal_weight','normalization_tolerance')
    if 'instrumentation' not in d:raise response.ResponseInputError('supplied instrumentation package required','missing_input')
    response.keys(d,required);response.require(type(d['schema_version']) is int and d['schema_version']==1,'source/trace document schema')
    descriptor=supplied_descriptor(d,p.parent)
    contracts=response.decode(_pin(d['contracts'],p.parent,4*1024*1024)[1]);response.source_contracts(contracts,descriptor['trace'])
    for c in contracts.values():
        for k in ('source','model'):
            q,b=_pin(c[k],p.parent);paths[q]=b
        response.require(c['routine']==descriptor['routine'] and c['source']['sha256']==descriptor['instrumentation']['source_sha256'],'classifier source differs from selected instrumentation')
    if task['operation']=='prepare-source':
        response.require(set(d['models'])==set(descriptor['models']),'complete supplied native model assets required')
        response.require(d['source']['sha256']==descriptor['instrumentation']['source_sha256'],'supplied original source required')
        for name,row in descriptor['models'].items():response.require(d['models'][name]['sha256']==contracts[row['contract']]['model']['sha256'],'native model differs from classifier contract')
        response.require(type(d['dependencies']) is list,'explicit source dependency census required')
    else:
        from . import existing_events
        prepared=response.decode(_pin(d['prepared'],p.parent)[1]);walk(prepared)
        response.require(prepared['descriptor']==descriptor,'prepared instrumentation differs from selected package')
        capsule=response.decode(_pin(prepared['capsule'],p.parent)[1]);walk(capsule)
        for fact in capsule['files']:
            q,b=_pin({'path':str(Path(capsule['root'])/fact['path']),'sha256':fact['sha256']},p.parent);paths[q]=b
        for a in d['anchors']:
            response.keys(a,('point','trace','producer_task','build_reuse','loader'))
            q,b=_pin(a['producer_task'],p.parent);producer=response.decode(b);reuse_root=_pin(a['build_reuse'],p.parent)[0].parent
            for name in ('native-dispatch.json','runtime-version.json','requested-observables.json','event-census.json','selected-routine-source.json','observables.json','histograms.yoda'):
                extra=reuse_root/name;paths[extra.resolve()]=ci.bounded_read(extra,64*1024*1024)
            for extra in existing_events.inputs(producer,q.parent):paths.setdefault(Path(extra).resolve(),None)
    return p,d,contracts,paths


def inputs(task,base):return list(document(task,base)[3])
def execution_seconds(task,base):validate(task);return 60

def resource_bounds(task,base):
    return {'processes':2,'mathematical_workers':1,'native_children':0,'max_seconds':60,'max_trace_bytes':64*1024*1024,'max_events':20000,'new_model_calls':0,'new_native_calls':0,'maximum_response_coordinates':512}


def final_histograms(descriptor):return descriptor['final_histograms']


def native_build_draft(prepared,runtime):
    """Actual existing build schema1 draft; seal with routine_build.seal_configuration
    after supplying genuine runtime paths. Never manufactures execution_identity.
    """
    response.require(prepared['kind']=='analysis-response-source','prepared source required')
    response.keys(runtime,('tools','artifacts','environment'));descriptor=prepared['descriptor'];routine=descriptor['instrumented_routine']
    return {'schema_version':1,'source_capsule':prepared['capsule']['path'],
            'recipe':{'name':'rivet-plugin','compile_units':[descriptor['build']['compile_unit']],'output':descriptor['build']['output'],'flags':descriptor['build']['flags']},
            'runtime':runtime,'probe':{'executable':'probe','arguments':['--show-analysis',routine],'expected_exit_code':0,'stdout_contains':[routine]}}

def observable_population(observables,original_names,descriptor):
    requested=[]
    for o in observables:
        response.require(o.get('quantity_kind')=='native_categorical','complete supplied native categorical objects per original weight required')
        c=o['native_categorical'];suffix=c['native_weight']['suffix'];path=o['path'][:-len(suffix)] if suffix else o['path']
        response.require(not suffix or o['path'].endswith(suffix),'declared native suffix differs')
        requested.append((path,c['native_weight']['native']))
    response.require(len(requested)==len(set(requested)) and set(requested)=={(p,w) for p in final_histograms(descriptor) for w in response.native_weight_names(original_names)},'complete supplied object/weight native output population required')
    return requested

def native_event_task(*,build_receipt,build_plan,events,metadata,python,observables,seed,descriptor):
    routine=descriptor["instrumented_routine"]
    """Compose existing rivet-built task with caller-supplied full source-native
    observable contracts. No invented runtime, RAW object schema or execution.
    """
    from . import existing_events
    meta=response.decode(ci.bounded_read(Path(metadata)))
    task={'backend':'rivet-built','routine':routine,'build_receipt':str(build_receipt),'build_plan':str(build_plan),'events':str(events),'metadata':str(metadata),'runtime':{'python':str(python),'version':descriptor['runtime_version']},'observables':observables,'options':descriptor['analysis_options'],'seed':seed,'native_weight_cap':0}
    existing_events.validate(task);observable_population(observables,meta['weight_names'],descriptor)
    return task

def prepare(d,base,out,contracts,*,_emitted=None):
    descriptor=supplied_descriptor(d,base);routine=descriptor['instrumented_routine'];original=descriptor['routine']
    response.source_contracts(contracts,descriptor['trace']);emitted=_Emitted(out) if _emitted is None else _emitted
    source=_pin(d['source'],base)[1];generated,edits=native.instrument(source,descriptor['instrumentation'])
    root=Path(out)/'source';root.mkdir();cc=root/descriptor['build']['compile_unit'];emitted.bytes(cc,generated)
    info=_pin(d['info'],base)[1].decode();response.require(info.startswith('Name: '+original+'\n'),'supplied original metadata identity')
    info=info.replace('Name: '+original+'\n','Name: '+routine+'\n',1).replace('Status: VALIDATED','Status: UNVALIDATED')
    emitted.bytes(root/(routine+'.info'),info.encode('utf-8'))
    reference_name=Path(d['reference']['path']).name;emitted.bytes(root/reference_name,_pin(d['reference'],base)[1])
    for name,pin in d['models'].items():emitted.bytes(root/descriptor['models'][name]['filename'],_pin(pin,base)[1])
    files=[{'path':Path(f['path']).name,'sha256':f['sha256'],'role':'compile' if Path(f['path']).name==cc.name else 'model' if f['path'].endswith('.onnx') else 'reference' if Path(f['path']).name==reference_name else 'configuration'} for f in emitted.inventory()]
    capsule={'schema_version':1,'kind':'analysis-source-capsule','framework':'rivet','routine':routine,'source':{'repository':'supplied','revision':None,'description':'Supplied source with reversible observation edits; native qualification pending'},'root':str(root.resolve()),'files':files,'layout':{'include_dirs':['.'],'asset_dirs':['.']},'dependencies':[{'name':'source-models','kind':'asset','status':'resolved','files':[f['path'] for f in files if f['role']=='model'],'reason':'All explicitly supplied model bytes preserved; runtime unqualified.'}] if d['models'] else [],'dependency_review':{'complete':True,'description':'Supplied assets complete; ordinary routine-build requires actual native library/runtime closure.'},'submodules':[]}
    from ravel.analysis_sources import validate_capsule
    validate_capsule(capsule);capsule_fact=emitted.json(Path(out)/'source-capsule.json',capsule)
    result={'kind':'analysis-response-source','status':'passed','routine':routine,'original_routine':original,'source_sha256':descriptor['instrumentation']['source_sha256'],'instrumented_sha256':hashlib.sha256(generated).hexdigest(),'edits':edits,'capsule':{k:capsule_fact[k] for k in ('path','sha256')},'models':d['models'],'classifier_contracts':d['contracts'],'dependencies':d['dependencies'],'descriptor':descriptor,'source_approximations':response.LIMITATIONS+descriptor['limitations'],'future_execution':'ordinary analyze/routine-build followed by analyze/rivet-built with uncapped complete weights, original event metadata and all supplied outputs; then consume-traces','required_final_histograms':final_histograms(descriptor),'new_native_calls':0,'physics_validated':False,'native_noninterference_qualified':False}
    result['generated_outputs']=emitted.inventory();result['delivery_path']=str((Path(out)/'prepared.json').absolute())
    emitted.json(Path(out)/'prepared.json',result);emitted.finish();return result


def original_census(path,metadata):
    """Use existing complete particle/beam census, then retain every serialized E/W identity."""
    from .event_census import census
    response.require(Path(path).suffix!='.gz','bounded plain ASCII HepMC required for this current full trace join')
    raw=ci.bounded_read(path,64*1024*1024);exposure=census(path,metadata)
    version=exposure['format'];current=None;rows=[]
    for line in raw.decode().splitlines():
        f=line.split()
        if not f:continue
        if f[0]=='E':
            if current is not None:rows.append(current)
            current={'number':int(f[1]),'weights':[]}
            if version=='HepMC2':
                start=12+int(f[11]);n=int(f[start]);current['weights']=[float(v) for v in f[start+1:]];response.require(len(current['weights'])==n,'complete HepMC2 weights')
        elif f[0]=='W' and current is not None and version=='HepMC3':current['weights']=[float(v) for v in f[1:]]
        elif 'END_EVENT_LISTING' in line:
            if current is not None:rows.append(current);current=None
    response.require(len(rows)==exposure['events'],'complete event identity join')
    names=metadata['weight_names'];out=[]
    for i,e in enumerate(rows):
        identity={'event_number':e['number'],'raw_weight_names':names,'raw_weights':e['weights'],'selected_weight_names':response.native_weight_names(names),'selected_weights':e['weights']}
        out.append({'event_id':str(i),'group_id':str(e['number']) if metadata['groups']=='correlated_event_number' else str(i),'weights':dict(zip(names,e['weights'])),'native_identity':identity})
    return out,exposure

def _producer(a,base,prepared,events,metadata):
    """Read-only existing build/loader custody. No reconstruction or numerical call."""
    from . import existing_events, routine_build
    response.keys(a,('point','trace','producer_task','build_reuse','loader'))
    descriptor=prepared['descriptor'];routine=descriptor['instrumented_routine']
    task=response.decode(_pin(a['producer_task'],base)[1]);existing_events.validate(task)
    response.require(task['backend']=='rivet-built' and task['routine']==routine and task.get('native_weight_cap')==0 and task['options']==descriptor['analysis_options'] and task['runtime']['version']==descriptor['runtime_version'],'exact existing observer runner with uncapped weights required')
    meta_doc=response.decode(metadata.read_bytes());observable_population(task['observables'],meta_doc['weight_names'],descriptor)
    task_base=Path(_pin(a['producer_task'],base)[0]).parent
    response.require(existing_events.regular(task['events'],task_base)==events and existing_events.regular(task['metadata'],task_base)==metadata,'producer uses a different original event population')
    rp,pp,receipt,plan,py,exe,binary=existing_events._built_evidence(task,task_base)
    response.require(plan['source_capsule']==prepared['capsule'] and plan['recipe']['compile_units']==[descriptor['build']['compile_unit']],'complete prepared source capsule/build translation-unit identity differs')
    runtime_shas={v['sha256'] for v in plan['runtime_identity']['artifacts']}
    response.require({v['sha256'] for v in prepared['dependencies']}<=runtime_shas,'actual build runtime must bind all observed projection/calibration implementation source dependencies')
    declared=[v for v in plan['source_inventory']['files'] if v['path'].endswith(descriptor['build']['compile_unit'])]
    response.require(len(declared)==1 and declared[0]['sha256']==prepared['instrumented_sha256'],'observed plugin built from different observer source')
    reuse=response.decode(_pin(a['build_reuse'],base)[1]);log=_pin(a['trace'],base)[1];loader=response.decode(_pin(a['loader'],base)[1])
    reuse_path=_pin(a['build_reuse'],base)[0]
    response.require(_pin(a['trace'],base)[0]==reuse_path.parent/'rivet.log' and _pin(a['loader'],base)[0]==reuse_path.parent/'loader-event-observation.json','same original native output directory required')
    response.require(loader['environment'].get('RIVET_RANDOM_SEED')==str(task['seed']),'actual selected native seed differs')
    response.require(reuse['plugin_sha256']==receipt['binary']['sha256'] and reuse['events_sha256']==hashlib.sha256(events.read_bytes()).hexdigest() and reuse['metadata_sha256']==hashlib.sha256(metadata.read_bytes()).hexdigest(),'native reuse/census custody mismatch')
    response.require(reuse['loader_observation']['sha256']==a['loader']['sha256'] and reuse['native_weight_cap']==0,'same native execution witness required')
    root=reuse_path.parent;work=root/'work'
    response.require(reuse.get('rebuild') is False and reuse.get('physics_validated') is False and reuse['build_receipt']==str(rp) and reuse['build_plan']==str(pp) and reuse['build_receipt_sha256']==hashlib.sha256(rp.read_bytes()).hexdigest() and reuse['build_plan_sha256']==hashlib.sha256(pp.read_bytes()).hexdigest(),'same observed native build receipt/plan required')
    env=routine_build.isolated_process_environment(work/'home',work/'tmp');env.update(RIVET_RANDOM_SEED=str(task['seed']),PYTHONDONTWRITEBYTECODE='1');env.update(plan['runtime_identity']['environment'])
    source=rp.parent/'work/source';assets=os.pathsep.join(str(source/v) for v in plan['source_inventory']['layout']['asset_dirs']) or str(source)
    env.update(RIVET_ANALYSIS_PLUGINS=str(binary),RIVET_ANALYSIS_PATH=str(source),RIVET_REF_PATH=assets,RIVET_INFO_PATH=assets,RIVET_DATA_PATH=assets)
    cli=[str(py),str(exe),'-a',routine,'-o',str(root/'histograms.yoda'),'-x',str(meta_doc['cross_section_pb']),'--weight-nominal',meta_doc['weight_names'][0],'--weight-cap','0',str(events)]
    cli[3]=routine+''.join(':'+key+'='+str(value) for key,value in sorted(task['options'].items()))
    command=routine_build.rivet_loader_command(py,binary,routine,root/'loader-event-observation.json',exe,*cli[2:])
    response.require(reuse['command']==command and reuse['declared_analysis_options']==descriptor['analysis_options'],'literal native CLI differs from full source task')
    dp=root/'native-dispatch.json';dispatch=response.decode(ci.bounded_read(dp))
    response.require(reuse['native_dispatch']=={'path':dp.name,'sha256':hashlib.sha256(dp.read_bytes()).hexdigest()} and dispatch['native_cli_command']==cli and dispatch['launched_command']==command and dispatch['native_weight_cap']==0 and dispatch['routine']==routine and dispatch['declared_analysis_options']==descriptor['analysis_options'] and dispatch['nominal_weight']==meta_doc['weight_names'][0] and dispatch['events_sha256']==hashlib.sha256(events.read_bytes()).hexdigest(),'retained command declaration mismatch')
    response.require(loader['runtime_version']==descriptor['runtime_version'] and loader['python']=={'path':str(py.resolve()),'sha256':hashlib.sha256(py.read_bytes()).hexdigest()},'source-matched native runtime/interpreter required')
    version=response.decode(ci.bounded_read(root/'runtime-version.json'))
    response.require(version['returncode']==0 and version['stdout'].strip()=='rivet v'+descriptor['runtime_version'],'recorded native version refusal')
    response.require(response.decode(ci.bounded_read(root/'requested-observables.json'))==task['observables'],'actual requested complete native output population differs')
    quantities=response.decode(ci.bounded_read(root/'observables.json',64*1024*1024))
    response.require(set(quantities['observables'])=={o['path'] for o in task['observables']},'missing retained native categorical output')
    for o in task['observables']:response.require(quantities['observables'][o['path']]['contract']==o,'retained native observable contract differs')
    routine_build.verify_loader_observation(loader,binary,routine,env,work,log,'')
    return log

def consume(d,base,out,contracts,*,_emitted=None):
    emitted=_Emitted(out) if _emitted is None else _emitted
    descriptor=supplied_descriptor(d,base);routine=descriptor['instrumented_routine']
    prepared=response.decode(_pin(d['prepared'],base)[1]);response.require(prepared['kind']=='analysis-response-source' and prepared['descriptor']==descriptor,'prepared supplied observer source required')
    # Recreate source identity; a label in prepared.json cannot substitute for the code.
    original=ci.bounded_read(_pin(next(iter(contracts.values()))['source'],base)[0]);generated,_=native.instrument(original,descriptor["instrumentation"])
    response.require(prepared['instrumented_sha256']==hashlib.sha256(generated).hexdigest(),'prepared native source projection changed')
    events=_pin(d['events'],base)[0];metadata_path,metadata_raw=_pin(d['metadata'],base);metadata=response.decode(metadata_raw)
    census,exposure=original_census(events,metadata);response.require(metadata['beam_pdg']==descriptor['beam_pdg'] and metadata['beam_energy_gev']==descriptor['beam_energy_gev'],'supplied source beam domain')
    response.require(d['nominal_weight']==metadata['weight_names'][0],'original native nominal weight required')
    tol=d['normalization_tolerance'];response.keys(tol,('atol','rtol'))
    for x in tol.values():response.finite(x);response.require(x>=0,'nonnegative declared normalization arithmetic tolerance')
    response.require(type(d['anchors']) is list and d['anchors'],'complete supplied response anchors required')
    response.require(type(d['axes']) is list and d['axes'] and all(set(axis)=={'name','knots'} and axis['name'] in descriptor['coordinate_fields'] for axis in d['axes']),'supplied axes must bind actual producer configuration fields')
    points=[a['point'] for a in d['anchors']]
    for a in d['anchors']:
        response.require(isinstance(a['point'],list) and len(a['point'])==len(d['axes']),'complete anchor coordinate dimensions required')
        producer=response.decode(_pin(a['producer_task'],base)[1])
        for axis,coordinate in zip(d['axes'],a['point']):
            actual=response.evaluate({'path':['producer',*descriptor['coordinate_fields'][axis['name']]]},{'producer':producer})
            response.require(actual==coordinate and coordinate in axis['knots'],'anchor coordinate differs from actual source producer configuration')
    contract_map=response.source_contracts(contracts,descriptor["trace"]);observed=[]
    for i,a in enumerate(d['anchors']):
        raw=_producer(a,base,prepared,events,metadata)
        # Preserve native returns before comparison/derivation can fail.
        emitted.bytes(Path(out)/('anchor-'+str(i)+'.native.log'),raw)
        result=response.consume(raw,census,contract_map,descriptor["trace"]);emitted.json(Path(out)/('anchor-'+str(i)+'.json'),result);observed.append(result)
    first=observed[0]['source_normalization'];expected=exposure['sumw'];xs=metadata['cross_section_pb']
    for r in observed:
        response.require(r['source_normalization']==first,'same-source anchor normalization changed')
        for i,n in enumerate(r['source_normalization']):
            reference_xs=xs*(expected[i]/expected[0]) # exact source setCrossSection user-xs convention
            for value,reference in ((n['sumW'],expected[i]),(n['cross_section_pb'],reference_xs),(n['scale_factor'],descriptor["normalization_scale"]*reference_xs/expected[i])):
                response.require(math.isclose(value,reference,rel_tol=tol['rtol'],abs_tol=tol['atol']),'source per-weight native normalization differs from complete original census')
    from .detector_response import summarize
    # Constant source-native nominal factor is conditional, never a fitted denominator law.
    config={'axes':d['axes'],'anchors':[{'point':p} for p in points],'reference_point':d['reference_point'],'weight_name':d['nominal_weight'],'normalization':{'scale':1.,'denominator':'fixed','fixed_denominator':1.}}
    rows=[[{k:e[k] for k in ('event_id','group_id','weights','allocation')} for e in r['rows']] for r in observed]
    moments=summarize(config,response.destinations(descriptor["trace"]),rows)
    factors={w:n['scale_factor'] for w,n in zip(metadata['weight_names'],first)}
    ordered_factors=[factors[x['weight']] for x in moments['joint_weight_anchor_basis']]
    raw_values=[v for w in moments['weights'].values() for v in w['numerators']]
    finalized={'basis':moments['joint_weight_anchor_basis'],'values':[a*b for a,b in zip(raw_values,ordered_factors)],'covariance':[[a*b*c for b,c in zip(ordered_factors,row)] for a,row in zip(ordered_factors,moments['joint_weight_anchor_covariance'])],'factors':ordered_factors,'scope':'Exact supplied linear scaling of conditional group Gram by recorded native factors, conditioned on their values; not native YODA errors or sampling-law calibration'}
    response.require(all(math.isfinite(x) for x in finalized['values']) and all(math.isfinite(x) for row in finalized['covariance'] for x in row),'finalized moment overflow')
    result={'kind':'analysis-response-feature-delivery','status':'passed','routine':descriptor['routine'],'physics_validated':False,'new_native_calls':0,'new_model_calls':0,'events':len(census),'original_census':exposure,'source_normalization':first,'weight_identity_mapping':[{'original':w,'native':n} for w,n in zip(metadata['weight_names'],response.native_weight_names(metadata['weight_names']))],'normalization_convention':'Complete recorded native per-weight factors; conditional fixed-factor moments with full cross-weight covariance','source_finalized':finalized,'anchors':observed,'response':moments,'study':descriptor['study'],'source_approximations':response.LIMITATIONS+descriptor['limitations'],'native_noninterference_qualified':False,'calibration_qualified':False,'likelihood_inferred':False}
    result['generated_outputs']=emitted.inventory();result['delivery_path']=str((Path(out)/'analysis-response-features.json').absolute())
    emitted.json(Path(out)/'analysis-response-features.json',result);emitted.finish();return result

def run(task,base,out):
    p,d,contracts,paths=document(task,base);out=Path(out)
    response.require(not out.exists() and not any(q.is_symlink() for q in (out,*out.parents)),'fresh unlinked consumer output required');out.mkdir(parents=True)
    emitted=_Emitted(out)
    try:
        result=(prepare if task['operation']=='prepare-source' else consume)(d,p.parent,out,contracts,_emitted=emitted)
        for q,b in paths.items():
            if b is not None:response.require(ci.bounded_read(q,64*1024*1024)==b,'ending source/input bytes changed')
        if task['operation']=='consume-traces':document(task,base) # Fresh existing build/runtime checks; common worker also rechecks its full input snapshot.
        emitted.finish(exact_tree=True)
        return result
    except BaseException as e:
        emitted.json(out/'failure.json',{'kind':type(e).__name__,'message':str(e),'status':'failed','physics_validated':False});raise

def write_report(result,out):
    response.require(result.get('status')=='passed' and result.get('physics_validated') is False,'scoped successful source/trace result required')
    _verify_delivery(result)
    from .truth_reco_response import study_contract
    study=result['descriptor']['study'] if result['kind']=='analysis-response-source' else result['study'];report=study_contract(study)['output'];stem=report['stem']
    out=Path(out);emitted=_Emitted(out);files=[]
    if 'json' in report['formats']:emitted.json(out/(stem+'.json'),result);files.append(stem+'.json')
    if 'markdown' in report['formats']:
        emitted.bytes(out/(stem+'.md'),('# Source analysis response\n\n'+result['kind']+'\n\n'+'\n'.join('- '+s for s in result['source_approximations'])+'\n').encode('utf-8'));files.append(stem+'.md')
    _verify_delivery(result);emitted.finish()
    return [{'stem':stem,'files':files,'normalization':'Explicit recorded source normalization; complete original events and weights'}]
