"""Pure original-interface controls; fake native transport is explicit.

No EasyScan initialization, sampler, external physics programme or engine is
executed. Source-extracted tests independently bind the released interfaces.
"""
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import pytest
from ravel.physics import parameter_space_sampling_core as c,parameter_space_sampling as a,parameter_space_sampling_observer as ob


def pin(p):
    raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,allow_nan=False));return pin(p)


def manifest(root):
    return {'schema_version':1,'files':{p.relative_to(root).as_posix():{k:v for k,v in {**pin(p),'mode':p.stat().st_mode&0o777}.items() if k!='path'} for p in root.rglob('*') if p.is_file()}}


def fixture(tmp_path,monkeypatch, *, method='RANDOM',workers=1,count=4):
    fw=tmp_path/'framework';fw.mkdir();(fw/'cli.py').write_text('# Explicit inert synthetic source; never imported\n')
    work=tmp_path/'workspace';(work/'tools').mkdir(parents=True);(work/'tools/in.txt').write_text('1 2\n');(work/'tools/program.sh').write_text('exit 1 # never executed');(work/'tools/program.sh').chmod(0o755)
    rt=tmp_path/'runtime';rt.mkdir();(rt/'inert.txt').write_text('explicit inert runtime manifest')
    api=c.strict(c.API.read_bytes());api['files']={k:{x:v[x] for x in ('sha256','size')} for k,v in manifest(fw)['files'].items()}
    ap=tmp_path/'synthetic-api.json';write(ap,api);monkeypatch.setattr(a,'API',ap)
    mf=write(tmp_path/'framework.json',manifest(fw));mw=write(tmp_path/'workspace.json',manifest(work));mr=write(tmp_path/'runtime.json',manifest(rt))
    question=tmp_path/'question.json';write(question,{'source':'explicit synthetic software task, no physics'})
    ncols='x, flat, 0, 1, 1\ny, flat, 0, 1, 1' if method=='GRID' else 'x, flat, 0, 1, 10, 0.5\ny, flat, 0, 1, 10, 0.5' if method in ('MCMC','EMCEE') else 'x, flat, 0, 1\ny, flat, 0, 1'
    ini='[scan]\nResult folder name: result\nScan method: '+method+'\nInput parameters: '+ncols.replace('\n','\n  ')+'\nNumber of points: '+str(count)+'\nParallel threads: '+str(workers)+'\n'
    if workers>1:ini+='Parallel folder: tools\n'
    if method=='EMCEE':ini+='MCMC walkers: 8\n'
    ini+='\n[program1]\nProgram name: synthetic\nExecute command: ./program.sh\nCommand path: tools/\nInput file: 1, tools/in.txt\nInput variable: x, 1, Position, 1, 1\n  y, 1, Position, 1, 2\nOutput file: 1, tools/out.txt\nOutput variable: f, 1, Position, 1, 1\n[constraint]\nGaussian: f, 1, 0.2\n[plot]\nColor: x, y, f\n'
    ip=tmp_path/'scan.ini';ip.write_text(ini)
    doc={'schema_version':2,'operation':'run','study_id':'ANA-0001','question':pin(question),'ini':pin(ip),'framework':{'root':str(fw),'manifest':mf},'workspace':{'root':str(work),'manifest':mw},
        'programmes':[{'section':'program1','inputs':['tools/in.txt'],'outputs':['tools/out.txt'],'intermediates':[],'mutable_paths':[],'units':{'f':'1'},'status':'native'}],
        'runtime':{'python':pin(Path(sys.executable).resolve()),'trees':[{'root':str(rt),'manifest':mr}],'site_roots':[str(rt)],'versions':{'Python':'explicit synthetic metadata only'}},
        'report':{'format':'json','path':'selected.json','table':'result/ScanResult.txt'},'resources':{'max_seconds':20,'max_ram_mib':512,'max_evaluations':100,'max_programme_calls':100,'max_output_bytes':64*1024**2,'max_output_members':10000,'max_copy_bytes':64*1024**2},'continuation':None,'returned':None}
    task={'config':write(tmp_path/'task-config.json',doc)}
    return task,doc,ip


def observer_fixture(tmp_path, *, method='RANDOM',workers=1):
    work=tmp_path/'work';work.mkdir();(work/'tools').mkdir();(work/'tools/in.txt').write_text('1 2\n')
    doc={'programmes':[{'section':'program1','inputs':['tools/in.txt'],'outputs':['tools/out.txt'],'intermediates':['tools/inter.txt'],'mutable_paths':[],'units':{'f':'1'},'status':'native'}],
        'resources':{'max_evaluations':100,'max_programme_calls':100,'max_output_bytes':64*1024**2,'max_output_members':10000}}
    info={'method':method,'workers':workers,'parallel_folder':'tools','result_folder':'result','sampled_parameters':2,'projection':{'program1':{'Program name':'synthetic'}}}
    initial=a.census(work,64*1024**2,10000)
    return {'output':str(tmp_path),'work':str(work),'config':doc,'info':info,'initial_workspace':initial}


@pytest.mark.parametrize('method,count,workers',[('RANDOM',9,1),('GRID',3,1),('BESTFIT',7,1),('MCMC',11,1),('EMCEE',12,1),('DYNESTY',6,1),('RANDOM',9,2)])
def test_source_configuration_and_context_cold(tmp_path,monkeypatch,method,count,workers):
    task,doc,ip=fixture(tmp_path,monkeypatch,method=method,count=count,workers=workers)
    value=a.context(task,tmp_path);assert value['native_configuration']['method']==method
    assert not value['execution_authorized'] and not value['native_algorithms_reimplemented']
    assert not any(n in sys.modules for n in ('scanner','emcee','dynesty','easyscan_hep','program'))
    assert a.inputs(task,tmp_path)


def test_grid_endpoint_law_and_emcee_slots(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch,method='GRID');assert c.ini(p.read_bytes(),d)['grid_population']==4
    p.write_text(p.read_text().replace(', 1\n',', 4\n'));assert c.ini(p.read_bytes(),d)['grid_population']==25
    d['operation']='continue-native'
    with pytest.raises(ValueError,match='only native'):c.ini(p.read_bytes(),d)


@pytest.mark.parametrize('mutation',['Time limit in minute: 2','Command executor: subprocess.popen','Command executor: unknown'])
def test_detached_native_executor_refused_before_execution(tmp_path,monkeypatch,mutation):
    t,d,p=fixture(tmp_path,monkeypatch);raw=p.read_bytes()+b''
    raw=raw.replace(b'Input file:',mutation.encode()+b'\nInput file:')
    with pytest.raises(ValueError,match='executor'):c.ini(raw,d)


def test_raw_table_never_drops_malformed_or_nonfinite():
    p=c.table(b'x,y\n1,2\n3\nNaN,4\n\n');assert len(p['rows'])==4 and p['malformed_rows']==[2] and p['nonfinite_rows']==[3]
    assert p['rows'][3]['status']=='blank'


def test_dynesty_final_evidence_used_for_all_weights():
    result=c.dynesty_weights(c.table(b'log_likelihood,log_weight,log_evidence,x\n-1,-3,-5,1\n-2,-2,-1,2\n'))
    assert result['final_logz']==-1 and result['weights_using_final_logz']==pytest.approx([__import__('math').exp(-2),__import__('math').exp(-1)])
    assert sum(result['separate_normalized_weights'])==pytest.approx(1) and not result['absolute_evidence_qualified']


@pytest.mark.parametrize('code,label',[(-100,'numerical_ewsb_failure'),(-1,'numerical_phasefinder_failure'),(-2,'physical_no_transition'),(-3,'physical_no_qualifying_transition')])
def test_phase_status_preserves_nonmeasurement_zeroes(code,label):
    r=c.phase_status(('80 .1 .2 '+str(code)+' 0 0 0 0 0 173 1 2 0 1').encode());assert r['source_status']==label and r['Tc_and_VEVs'] is None and len(r['raw_fields'])==14


def test_observed_likelihood_forwards_once_return_and_exception(tmp_path):
    o=ob.Observer(observer_fixture(tmp_path));calls=[]
    def fn(*args,**kw):calls.append((args,kw));args[0][0]=42;return -3
    wrapped=o.likelihood(fn);cube=[1,2];assert wrapped(cube,2,3,'')==-3 and cube[0]==42 and len(calls)==1
    class Meaningful(Exception):pass
    def bad(*args,**kw):raise Meaningful('original')
    with pytest.raises(Meaningful,match='original'):o.likelihood(bad)([1],1,1,'')
    kinds=[json.loads(p.read_text())['kind'] for p in sorted(o.records.glob('*.json'))];assert kinds==['evaluation-begin','evaluation-return','evaluation-begin','evaluation-exception']


def test_recording_failure_stops_before_original_call(tmp_path,monkeypatch):
    o=ob.Observer(observer_fixture(tmp_path));calls=[]
    monkeypatch.setattr(ob,'atomic_json',lambda *a,**k:(_ for _ in ()).throw(OSError('record failure')))
    with pytest.raises(OSError):o.likelihood(lambda *aa:calls.append(aa))([1],1,1,'')
    with pytest.raises(RuntimeError,match='prior observer'):o.likelihood(lambda *aa:calls.append(aa))([1],1,1,'')
    assert calls==[]


def test_shared_evaluation_ceiling_before_dispatch(tmp_path):
    r=observer_fixture(tmp_path);r['config']['resources']['max_evaluations']=1;o=ob.Observer(r);calls=[]
    fn=o.likelihood(lambda *aa:calls.append(aa) or -1)
    fn([1],1,1,'')
    with pytest.raises(RuntimeError,match='ceiling'):fn([2],1,1,'')
    assert len(calls)==1 and o.counters['evaluations'].value==1


def test_worker_exit_census_does_not_trust_root_success(tmp_path):
    o=ob.Observer(observer_fixture(tmp_path,workers=2));calls=[]
    sc=SimpleNamespace(run_processes=lambda processes:calls.append(processes),saveCube=lambda cube,data_file,file_path,num,save_file:None,gauss=lambda *args:0)
    o.install_scanner(sc);ps=[SimpleNamespace(pid=101,exitcode=0,name='p0'),SimpleNamespace(pid=102,exitcode=2,name='p1')]
    assert sc.run_processes(ps) is None and len(calls)==1 and o.workers[1]['exitcode']==2
    o.restore()


def test_sampler_object_and_complete_native_arrays_preserved(tmp_path):
    o=ob.Observer(observer_fixture(tmp_path,method='EMCEE'));calls=[]
    class Sampler:
        acceptance_fraction=[.5,.75]
        def run_mcmc(self,*a,**k):calls.append((a,k));return ('native',)
        def get_chain(self):return [[[.1,.2],[.3,.4]]]
        def get_log_prob(self):return [[-1,float('-inf')]]
    real=Sampler();module=SimpleNamespace(EnsembleSampler=lambda *a,**k:real)
    o.install_sampler(module,'EnsembleSampler','run_mcmc');assert module.EnsembleSampler(2,2,None) is real
    assert real.run_mcmc([[0,0]],1,progress=False)==('native',) and len(calls)==1
    assert o.samplers['EMCEE']['log_probability'][0][1]=={'native_nonfinite':'-inf'}
    o.restore()


def test_mcmc_proposal_outside_prior_recorded_without_redraw(tmp_path):
    o=ob.Observer(observer_fixture(tmp_path,method='MCMC'));pid=__import__('os').getpid();o.method[pid]='mcmcrun';calls=[]
    def gauss(*args):calls.append(args);return [1.5,-.2][len(calls)-1]
    sc=SimpleNamespace(gauss=gauss,run_processes=lambda p:None,saveCube=lambda cube,data_file,file_path,num,save_file:None)
    o.install_scanner(sc);assert sc.gauss(0,1)==1.5 and sc.gauss(0,1)==-.2 and len(calls)==2
    record=next(p for p in o.records.glob('*mcmc-proposal.json'));assert not json.loads(record.read_text())['inside_prior'];o.restore()


def test_programme_raw_before_next_call_and_stale_intermediate_refusal(tmp_path):
    r=observer_fixture(tmp_path);o=ob.Observer(r);calls=[]
    class Program:
        _executor=True
        def getProgName(self):return 'synthetic'
        def RunProgram(self,i_process=''):
            calls.append(i_process);(Path(r['work'])/'tools/out.txt').write_text('1\n');(Path(r['work'])/'tools/inter.txt').write_text('2\n');return True
        def WriteInputFile(self,par,i_process):return True
        def ReadOutputFile(self,par,path,i_process):return True
        def ReadBound(self,par):return True
        def Recover(self,i_process):return None
    o.install_program(Program);p=Program();assert p.RunProgram() is True
    raw=list((tmp_path/'raw-calls').rglob('out.txt'));assert len(raw)==1 and raw[0].read_bytes()==b'1\n'
    original=Program.RunProgram.__wrapped__
    # New source callable deliberately leaves every output untouched; recorder
    # must stop before downstream ReadOutputFile treats an earlier result as new.
    def inert(self,i_process=''):return True
    o.restore();Program.RunProgram=inert;o.install_program(Program)
    with pytest.raises(ValueError,match='stale'):p.RunProgram()
    assert len(calls)==1;o.restore();Program.RunProgram=original


def test_closed_work_copy_preserves_cards_but_refuses_new_source(tmp_path):
    r=observer_fixture(tmp_path);(Path(r['work'])/'tools/in.txt').write_text('native card update')
    ob.check_workspace(r)
    (Path(r['work'])/'unbound.py').write_text('# unknown')
    with pytest.raises(ValueError,match='unadmitted'):ob.check_workspace(r)


def test_cold_runtime_missing_and_source_changes_refuse(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch);d['runtime']=None;t={'config':write(tmp_path/'no-runtime.json',d)}
    assert a.context(t,tmp_path)['missing_runtime']
    with pytest.raises(ValueError,match='runtime inputs'):a.inputs(t,tmp_path)
    (tmp_path/'workspace/unbound.py').write_text('# unexpected')
    with pytest.raises(ValueError,match='membership'):a.inputs(t,tmp_path)


def test_source_copy_consumes_one_admitted_buffer(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch);cap=c.Capture();target=tmp_path/'copy'
    a._copy_tree(d['workspace'],tmp_path,cap,target)
    assert manifest(target)==manifest(tmp_path/'workspace')
    (tmp_path/'workspace/tools/in.txt').write_text('drift')
    with pytest.raises(ValueError):cap.finish()


def test_real_ordinary_science_plan_no_native(tmp_path,monkeypatch):
    from ravel.workflow import science
    import platform
    monkeypatch.setattr(science.execution,'runtime_context',lambda:{'platform':'explicit inert software platform','python':'inert','environment_sha256':science.execution.digest(science.execution.runtime_environment()),'packages_sha256':'1'*64})
    task,d,ip=fixture(tmp_path,monkeypatch)
    actors=dict(zip(('proposer','executor','physics_critic','skeptical_verifier','physics_decider'),['synthetic:'+v for v in ('p','e','c','v','d')]))
    spec=a.specification(task,source='explicit synthetic software fixture',assumptions=['No actual native programme/sampler runs'],actors=actors,max_seconds=20,approval_mode='scripted_yes')
    assert science.adapter(spec) is a and science._new_capability(spec)
    f=tmp_path/'science.json';write(f,spec);rd=tmp_path/'ordinary';science.plan(rd,f)
    assert (rd/'inputs/science-plan.json').is_file() and not (rd/'inputs/science-approval.json').exists()
    assert science.verify_plan(rd)


def test_real_graph_host_context_and_stale_input(tmp_path,monkeypatch):
    from ravel.workflow import agent_graph as g,agent_host as h,execution
    t,d,p=fixture(tmp_path,monkeypatch);tp=tmp_path/'task.json';write(tp,t)
    dependencies=a.context_inputs(t,tmp_path)
    pins=[{'id':'task','path':str(tp),'sha256':pin(tp)['sha256']}]+[{'id':'d'+str(i),'path':str(p),'sha256':pin(p)['sha256']} for i,p in enumerate(dependencies)]
    node={'id':'context','kind':'tool','role':'executor','depends_on':[],'inputs':pins,'packet':None,'action':'parameter-space-sampling-context','parameters':{'request_input':'task'},'max_attempts':1}
    spec={'schema_version':1,'graph_id':'parameter-space-sampling-context','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':60,'max_reworks':0},'nodes':[node]}
    rd=tmp_path/'graph';g.create(rd,spec);result=g.execute(rd,h.AgentHost(),workers=1)
    assert result['complete'] and result['usage']['calls']==1 and result['execution_authorized'] is False
    Path(t['config']['path']).write_text('{}')
    with pytest.raises(g.GraphError):g.execute(rd,h.AgentHost(),workers=1)


def test_real_adapter_inert_native_boundary_complete_raw_and_report(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    from ravel.plotting import science_figures
    task,d,p=fixture(tmp_path,monkeypatch);rd=tmp_path/'run';rd.mkdir();out=rd/'outputs/attempt-1/parameter-space-sampling';out.parent.mkdir(parents=True)
    monkeypatch.setattr(a,'_approved',lambda task,out:(rd,{'max_seconds':20}))
    calls=[]
    def fake(command,native,resources):
        calls.append(command);req=c.strict((native/'request.json').read_bytes());work=Path(req['work']);res=work/'result';(res/'Figures').mkdir(parents=True)
        (res/'ScanResult.txt').write_text('x,y,f,Chi2\n0,0,1,0\n1,1,2,25\n')
        # Explicit non-native image bytes test retention only, not rendering.
        (res/'Figures/Color_x_y_f.png').write_bytes(b'INERT synthetic image stand-in')
        write(native/'observation.json',{'schema_version':1,'status':'completed','counts':{'evaluations':4},'workers':[],'samplers':{}})
        return {'returncode':0,'synthetic_transport':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    result=a.run(task,tmp_path,out);assert result['status']=='passed' and not result['physics_validated'] and len(calls)==1
    assert len(result['delivery']['tables']['result/ScanResult.txt']['rows'])==2 and result['programme_contracts']==d['programmes']
    summary=science_figures.render({'mode':'parameter-space-sampling','task':task},result,tmp_path,out.parent)
    assert summary['figures'] and 'Color_x_y_f.png' in (out.parent/'parameter-space-sampling-report.md').read_text()
    assert (out/'raw-census.json').is_file()
    with pytest.raises(ValueError,match='fresh'):a.run(task,tmp_path,out)


@pytest.mark.parametrize('failed',['native_exit','unknown_member','wrong_trials','missing_figure','worker_exit'])
def test_adapter_preserves_native_failure_and_full_raw(tmp_path,monkeypatch,failed):
    from ravel.physics import reinterpret_db
    task,d,p=fixture(tmp_path,monkeypatch,workers=2 if failed=='worker_exit' else 1);rd=tmp_path/'run';rd.mkdir();out=rd/'outputs/attempt-1/parameter-space-sampling';out.parent.mkdir(parents=True)
    monkeypatch.setattr(a,'_approved',lambda task,out:(rd,{'max_seconds':20}))
    def fake(cmd,native,resources):
        req=c.strict((native/'request.json').read_bytes());work=Path(req['work']);res=work/'result';(res/'Figures').mkdir(parents=True)
        (res/'ScanResult.txt').write_text('x,y,f\n1,2,3\n')
        if failed!='missing_figure':(res/'Figures/Color_x_y_f.png').write_bytes(b'inert')
        if failed=='unknown_member':(work/'unbound.py').write_text('# unknown source')
        if failed=='worker_exit':
            for i in range(2):shutil.copytree(work/'tools',work/('p'+str(i)+'_tools'))
        write(native/'observation.json',{'schema_version':1,'status':'completed','counts':{'evaluations':3 if failed=='wrong_trials' else 4},'workers':[],'samplers':{}})
        (native/'partial-raw.txt').write_text('retained negative witness')
        if failed=='native_exit':raise ValueError('explicit inert native error')
        return {'returncode':0,'synthetic_transport':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    result=a.run(task,tmp_path,out);assert result['status']=='failed' and result['physics_validated'] is False
    assert (out/'native/partial-raw.txt').read_text()=='retained negative witness' and (out/'raw-census.json').is_file()


def test_native_continuation_only_copies_exact_predecessor(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch,method='MCMC',count=4);info=c.ini(p.read_bytes(),d)
    pr=tmp_path/'predecessor';pr.mkdir();s=pr/'ScanResult.txt';s.write_text('x,y,f,dwell\n.5,.5,1,2\n')
    allp=pr/'All_ScanResult.txt';allp.write_text('x,y,f,dwell\n.5,.5,1,1\n')
    cont={'schema_version':1,'config_identity':a.identity(d,info),'runtime_identity':c.digest(d['runtime']),'method':'MCMC','root':str(pr),'files':{'ScanResult.txt':pin(s),'All_ScanResult.txt':pin(allp)}}
    d['operation']='continue-native';d['continuation']=write(tmp_path/'continuation.json',cont);t={'config':write(tmp_path/'continue.json',d)}
    before=s.read_bytes();a.inputs(t,tmp_path);assert s.read_bytes()==before
    cont['runtime_identity']='0'*64;d['continuation']=write(tmp_path/'bad-cont.json',cont);t={'config':write(tmp_path/'bad.json',d)}
    with pytest.raises(ValueError,match='runtime differs'):a.inputs(t,tmp_path)


def test_mutable_executable_laundering_refused(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch);d['programmes'][0]['mutable_paths']=['tools/program.sh'];t={'config':write(tmp_path/'bad-mutable.json',d)}
    with pytest.raises(ValueError,match='executable/source'):a.inputs(t,tmp_path)


def test_same_bytes_executable_permission_change_refuses(tmp_path):
    r=observer_fixture(tmp_path);q=Path(r['work'])/'immutable.sh';q.write_text('#source');q.chmod(0o755)
    r['initial_workspace']=a.census(r['work'],64*1024**2,10000);r['initial_modes']={p.relative_to(r['work']).as_posix():p.stat().st_mode&0o777 for p in Path(r['work']).rglob('*') if p.is_file()}
    q.chmod(0o644)
    with pytest.raises(ValueError,match='permission'):ob.check_workspace(r)


def test_supplied_gaussian_lexemes_and_initial_discrepancy(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch,method='MCMC',count=7)
    raw=p.read_bytes().replace(b'Gaussian: f, 1, 0.2',b'Gaussian: f, 1.0, 2e-1').replace(b'10, 0.5',b'10, 1.5')
    info=c.ini(raw,d)
    assert info['projection']['constraint']['Gaussian']=='f, 1.0, 2e-1'
    assert [v['parameter'] for v in info['discrepancies']]==['x','y']
    assert info['parameters'][0]['numeric'][-1]==1.5


def test_complete_returned_population_and_path_binding(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch);info=c.ini(p.read_bytes(),d);root=tmp_path/'returned';root.mkdir();(root/'complete.txt').write_text('whole native return')
    r={'schema_version':1,'root':str(root),'config_identity':a.identity(d,info),'runtime_identity':c.digest(d['runtime']),'files':{'complete.txt':pin(root/'complete.txt')},'observation':{'status':'completed','counts':{}}}
    d['operation']='read-returned';d['returned']=write(tmp_path/'returned.json',r);t={'config':write(tmp_path/'read-returned.json',d)}
    assert a.inputs(t,tmp_path)
    (root/'omitted.txt').write_text('not in supplied census')
    with pytest.raises(ValueError,match='complete returned'):a.inputs(t,tmp_path)


def test_complete_sampler_arrays_and_finite_chain_are_separate(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch,method='EMCEE',count=8);info=c.ini(p.read_bytes(),d);info['figures']=[]
    raw={'result/ScanResult.txt':b'x,y,f,dwell\n.5,.5,1,1\n','result/All_ScanResult.txt':b'x,y,f,dwell\n.5,.5,1,1\n','result/EMCEEChain.txt':b'log_probability,x,y\n'+b'-1,.5,.5\n'*8}
    files={k:{'size':len(v)} for k,v in raw.items()};data={'chain_unit_coordinates':[[[.5,.5]]*8],'log_probability':[[-1]*8],'acceptance_fraction':[.5]*8};obs={'status':'completed','counts':{},'workers':[],'samplers':{'EMCEE':data}}
    result=a.project(d,info,files,raw.__getitem__,obs);assert result['issues']==[] and result['sampler_population']['complete_slots']==8
    data['log_probability'][0][-1]={'native_nonfinite':'-inf'};raw['result/EMCEEChain.txt']=b'log_probability,x,y\n'+b'-1,.5,.5\n'*7
    result=a.project(d,info,files,raw.__getitem__,obs);assert result['sampler_population']['finite_slots']==7 and result['issues']==['requested_finite_emcee_chain_shortened']
    data['chain_unit_coordinates'][0].pop();assert 'complete_emcee_array_dimensions_or_values_differ' in a.project(d,info,files,raw.__getitem__,obs)['issues']


def test_dynesty_arrays_table_and_final_evidence_population(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch,method='DYNESTY');info=c.ini(p.read_bytes(),d);info['figures']=[]
    raw={'result/ScanResult.txt':b'x,y,f\n1,2,3\n','result/DynestySamples.txt':b'log_likelihood,log_weight,log_evidence,x,y\n-2,-3,-5,1,2\n-1,-2,-1,3,4\n'}
    files={k:{'size':len(v)} for k,v in raw.items()};data={'samples':[[1,2],[3,4]],'logl':[-2,-1],'logwt':[-3,-2],'logz':[-5,-1],'logzerr':[.1,.1],'ncall':[2,3],'eff':50};obs={'status':'completed','counts':{},'workers':[],'samplers':{'DYNESTY':data}}
    assert a.project(d,info,files,raw.__getitem__,obs)['issues']==[]
    data['samples'][1][0]=5
    assert 'native_dynesty_table_and_complete_arrays_differ' in a.project(d,info,files,raw.__getitem__,obs)['issues']
    zero=c.dynesty_weights(c.table(b'log_likelihood,log_weight,log_evidence,x\n-inf,-inf,-3,1\n-1,-2,-1,2\n'));assert zero['weights_using_final_logz'][0]==0


def test_real_common_worker_intake_checkin_and_report(tmp_path,monkeypatch):
    from ravel.physics import science_worker as sw,reinterpret_db
    t,d,p=fixture(tmp_path,monkeypatch);rd=tmp_path/'run';rd.mkdir()
    actors=dict(zip(('proposer','executor','physics_critic','skeptical_verifier','physics_decider'),['synthetic:'+v for v in ('p','e','c','v','d')]))
    spec=a.specification(t,source='synthetic software only',assumptions=['Inert native transport, no scientific result'],actors=actors,max_seconds=20)
    proposal={'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':'synthetic-source-binding'}}
    monkeypatch.setattr(sw,'verify_worker',lambda r:proposal);monkeypatch.setattr(sw,'execution_spec',lambda r:spec);monkeypatch.setattr(a,'_approved',lambda *aa:(rd,{'max_seconds':20}))
    def fake(cmd,native,resources):
        req=c.strict((native/'request.json').read_bytes());res=Path(req['work'])/'result';(res/'Figures').mkdir(parents=True)
        (res/'ScanResult.txt').write_text('x,y,f\n1,2,3\n');(res/'Figures/Color_x_y_f.png').write_bytes(b'explicit nonrendering image stand-in')
        write(native/'observation.json',{'status':'completed','counts':{'evaluations':4},'workers':[],'samplers':{}});return {'returncode':0,'inert_transport':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    assert sw.main([str(rd)])==0
    out=rd/'outputs/attempt-1';ci=c.strict((out/'checkin2.json').read_bytes());assert ci['sections']['waypoint']['status_scope']==a.SCOPE
    assert not c.strict((out/'verification.json').read_bytes())['expert_review'] and (out/'parameter-space-sampling-report.md').is_file()
    assert c.strict((out/'figures.json').read_bytes())['figures'][0]['style_qualified'] is False


def test_real_child_protocol_forwards_original_cli_once(tmp_path,monkeypatch):
    # The production protocol runs in a fresh interpreter. Collection of other
    # test files can import native libraries which are deliberately not in this
    # inert child's captured runtime, so exercise the same process boundary.
    import os, subprocess
    if os.environ.get('RAVEL_TEST_SAMPLING_CHILD') != '1':
        child = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q',
            f'{__file__}::test_real_child_protocol_forwards_original_cli_once'],
            env={**os.environ, 'RAVEL_TEST_SAMPLING_CHILD': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, timeout=120)
        assert child.returncode == 0, child.stdout + child.stderr
        return
    from ravel.physics import parameter_space_sampling_worker as worker
    import os,types
    request=observer_fixture(tmp_path);work=Path(request['work']);fw=tmp_path/'framework';fw.mkdir()
    source=Path(a.__file__).parents[1]
    files={str(q):pin(q) for q in a._members(source).values()}
    for name in ('easyscan_hep','easyscan_hep.cli','scanner','program'):
        f=fw/(name.replace('.','_')+'.py');f.write_text('# Explicit inert import boundary\n');files[str(f)]=pin(f)
        mod=types.ModuleType(name);mod.__file__=str(f);monkeypatch.setitem(sys.modules,name,mod)
    package=sys.modules['easyscan_hep'];package.__path__=[];cli=sys.modules['easyscan_hep.cli'];package.cli=cli;sc=sys.modules['scanner']
    def randomrun(LnLike):return LnLike([.5],1,1,'')
    sc.randomrun=randomrun;sc.run_processes=lambda processes:None;sc.saveCube=lambda cube,data_file,file_path,num,save_file:None;sc.gauss=lambda *a:0
    class Program:
        def getProgName(self):return 'synthetic'
        def WriteInputFile(self,par,i_process):return True
        def RunProgram(self,i_process=''):raise AssertionError('no native programme')
        def ReadOutputFile(self,par,path,i_process):return True
        def ReadBound(self,par):return True
        def Recover(self,ParallelAdd):return None
    sys.modules['program'].PROGRAM=Program;calls=[]
    cli.main=lambda:calls.append((tuple(sys.argv),Path.cwd())) or sc.randomrun(lambda *a:-1)
    request['config']['operation']='run';request.update(source_root=str(source),assets=files,closed_roots=[str(source),str(fw)],site_roots=[],framework=str(fw),ini=str(work/'ravel-native.ini'))
    q=tmp_path/'request.json';write(q,request);prior_cwd=Path.cwd();prior_path=list(sys.path);prior_argv=list(sys.argv)
    for key in ('EASYSCAN_ROOT','EASYSCAN_RESULT_EXISTS_ACTION','PYTHONDONTWRITEBYTECODE','MPLCONFIGDIR'):monkeypatch.setenv(key,os.environ.get(key,''))
    try:assert worker.main([str(q),pin(q)['sha256']])==0
    finally:os.chdir(prior_cwd);sys.path[:]=prior_path;sys.argv[:]=prior_argv
    assert len(calls)==1 and calls[0][1]==work and calls[0][0][0]=='easyscan'
    final=c.strict((tmp_path/'observation.json').read_bytes());assert final['counts']['evaluations']==1 and not final['algorithm_qualified']
    assert sc.randomrun is randomrun


def test_loaded_native_module_outside_runtime_refuses(tmp_path,monkeypatch):
    from ravel.physics.parameter_space_sampling_worker import loaded_native_assets
    import types
    m=types.ModuleType('dynesty');m.__file__=str(tmp_path/'unbound.py');monkeypatch.setitem(sys.modules,'dynesty',m)
    with pytest.raises(ValueError,match='outside captured'):loaded_native_assets({'assets':{}})


def test_cold_public_cli_and_complete_installed_document_pairs(capsys):
    from ravel import cli,paths
    root=Path(__file__).parents[2]
    with pytest.raises(SystemExit) as exc:cli.main(['parameter-space-sampling','population'])
    assert exc.value.code==2
    for logical in paths.WORKFLOW_INSTRUCTIONS:assert (root/logical).read_bytes()==(root/'src/ravel/data/workflow'/logical).read_bytes()
    assert 'docs/reference/parameter-space-sampling.md' in paths.WORKFLOW_INSTRUCTIONS


def test_native_bestfit_fields_retained_without_convergence_claim(tmp_path,monkeypatch):
    t,d,p=fixture(tmp_path,monkeypatch,method='BESTFIT',count=20);info=c.ini(p.read_bytes(),d);info['figures']=[]
    raw={'result/ScanResult.txt':b'x,y,f\n.1,.2,1\n'};files={k:{'size':len(v)} for k,v in raw.items()}
    obs={'status':'completed','counts':{'evaluations':79},'workers':[],'samplers':{},'optimizer':{'x':[.1,.2],'fun':0,'success':False,'message':'native maxiter reached','nit':20,'nfev':79}}
    result=a.project(d,info,files,raw.__getitem__,obs);assert result['issues']==[] and result['observation']['optimizer']['success'] is False and result['scientific_validity_unknown']
    obs.pop('optimizer');assert 'native_bestfit_complete_objective_result_missing' in a.project(d,info,files,raw.__getitem__,obs)['issues']
    d['resources']['max_evaluations']=3;p.write_text(p.read_text().replace('BESTFIT','RANDOM'))
    with pytest.raises(ValueError,match='complete original trial'):c.ini(p.read_bytes(),d)
