"""Pure synthetic controls; optional pySecDec and every native operation are mocked."""
import ast
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS, ModuleType
import pytest
from ravel.physics import finite_integrals as a, finite_integrals_core as k
from ravel.validation import numerical_reference as nr


def pin(p):
    raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
def save(p,d):
    p.write_text(json.dumps(d,indent=2)+'\n');return pin(p)
def cfg(n=3,complex_mass=False):
    mass={'real':'4','imag':'-3' if complex_mass else '0'}
    p={'id':'p0','invariants_gev2':{'s'+str(i)+str(j):'0' for i,j in k.pairs(n)},'masses_squared_gev2':[deepcopy(mass) for _ in range(n)],'scale_squared_gev2':'2','mu_gev':'1'}
    q=deepcopy(p);q['id']='p1';q['mu_gev']='2'
    return {'schema_version':1,'kind':'pysecdec-finite-one-loop','source':'Synthetic independent Feynman-parameter identity',
        'evidence':[{'path':'pending','sha256':'0'*64,'size':1}],
        'runtime':{'python':{},'make':{},'cxx':{},'trees':[{}],'site_roots':['/synthetic'],'contrib_root':'/synthetic/contrib','path':['/usr/bin'],'version':k.VERSION},
        'propagators':n,'regime':'causal_complex_masses' if complex_mass else 'euclidean_positive_masses',
        'prescription':k.PRESCRIPTION,'normalization':k.NORMALIZATION,'axes':['mu'],'points':[p,q],
        'precision':{'epsrel':'1/1000','epsabs':'1/1000000','maxeval':1000,'minn':100,'seed':19},
        'max_seconds':30,'max_ram_mib':512,'max_output_bytes':1024**2,
        'operation_resources':{'schema_version':1,'kind':'solver','generated_events':0,'solver_evaluations':2,'max_seconds':30}}

def cmul(x,y):return (x[0]*y[0]-x[1]*y[1],x[0]*y[1]+x[1]*y[0])
def cinv(x):return (x[0]/(x[0]**2+x[1]**2),-x[1]/(x[0]**2+x[1]**2))
def independent_zero_momentum(c,p):
    # Simplex volume 1/(N-1)!, Gamma(N-2) and Wick-rotation sign.
    m=(F(p['masses_squared_gev2'][0]['real']),F(p['masses_squared_gev2'][0]['imag']))
    x=cinv(m)
    if c['propagators']==3:return tuple(-v/2 for v in x)
    return tuple(v/6 for v in cmul(x,x))
def literal(re,im,er='0',ei='0'):
    return ' + (('+str(float(re))+','+str(float(im))+') +/- ('+str(er)+','+str(ei)+')) + O(eps)'
def delivery(c):
    rows=[]
    for p in c['points']:
        truth=independent_zero_momentum(c,p);factor=F(k.numerical_arguments(c,p)['dimensionful_factor'])
        raw=['literal integral before prefactor','literal gamma prefactor',literal(truth[0]/factor,truth[1]/factor)]
        rows.append({'id':p['id'],'point':p,'status':'returned','raw':raw,'derived':k.derived(c,p,raw)})
    return {'status':'returned','version':k.VERSION,'generator_spec':k.generator_spec(c),'calls_started':len(rows),'calls_returned':len(rows),
        'rows':rows,'phases':[{'name':'generate','status':'returned'},{'name':'build','status':'returned','returncode':0}],
        'operation_resources':c['operation_resources']}

@pytest.mark.parametrize('n,causal',[(3,False),(4,False),(3,True),(4,True)])
def test_independent_complex_gamma_simplex_sign_and_scale(n,causal):
    c=k.config(cfg(n,causal));d=delivery(c)
    assert k.delivery_check(c,json.loads(json.dumps(d)))
    for p,row in zip(c['points'],d['rows']):
        for key,value in zip(('real','imag'),independent_zero_momentum(c,p)):
            assert abs(F(row['derived']['values'][key])-value)<F(1,10**15)
    if causal and n==3:assert F(d['rows'][0]['derived']['values']['imag'])<0
    original=deepcopy(c)
    for p in c['points']:p['scale_squared_gev2']='8'
    new=delivery(c)
    assert all(abs(F(new['rows'][0]['derived']['values'][key])-F(d['rows'][0]['derived']['values'][key]))<F(1,10**15) for key in ('real','imag'))
    assert new['rows'][0]['derived']['native_arguments']!=d['rows'][0]['derived']['native_arguments']
    assert k.generator_spec(c)['replacement_rules']==k.generator_spec(original)['replacement_rules']

@pytest.mark.parametrize('fault',['massless','positive_imag','missing_imag','timelike','omitted_axis','duplicate','normalization','units','budget','extra','tiny'])
def test_closed_domains_refuse(fault):
    c=cfg(complex_mass=fault in ('positive_imag','missing_imag'))
    if fault=='massless':c['points'][0]['masses_squared_gev2'][0]['real']='0'
    if fault=='positive_imag':c['points'][0]['masses_squared_gev2'][0]['imag']='3'
    if fault=='missing_imag':c['points'][0]['masses_squared_gev2'][0]['imag']='0'
    if fault=='timelike':c['points'][0]['invariants_gev2']['s01']='1'
    if fault=='omitted_axis':c['points'][1]['scale_squared_gev2']='4'
    if fault=='duplicate':c['points'][1]['mu_gev']='1'
    if fault=='normalization':c['normalization']='16*pi^2 convention'
    if fault=='units':c['points'][0]['scale_squared_gev2']='-1'
    if fault=='budget':c['operation_resources']['solver_evaluations']=1
    if fault=='extra':c['precision']['arbitrary_digits']=100
    if fault=='tiny':c['points'][0]['invariants_gev2']['s01']='-1e-30'
    with pytest.raises(ValueError):k.config(c)

@pytest.mark.parametrize('raw',[' + ((1,2) +/- (-1,0))',' + ((nan,0) +/- (0,0))',' + ((1,2) +/- (0,0))*eps^-1 + O(eps)',' + ((1,0) +/- (0,0)) + ((2,0) +/- (0,0))*eps','__import__("os")','((1,0) +/- (0,0)) + O(eps^2)'])
def test_literal_parser_refuses_poles_extra_terms_nonfinite(raw):
    with pytest.raises(ValueError):k.parse_finite(raw)

@pytest.mark.parametrize('fault',['raw','id','point','count','phase','precision','resources'])
def test_complete_raw_population_and_phase_binding(fault):
    c=cfg();d=delivery(c)
    if fault=='raw':d['rows'][0]['raw'][2]=literal(99,0)
    if fault=='id':d['rows'][0]['id']='other'
    if fault=='point':d['rows'][0]['point']=deepcopy(d['rows'][0]['point']);d['rows'][0]['point']['mu_gev']='9'
    if fault=='count':d['calls_started']=1
    if fault=='phase':d['phases'][1]['returncode']=3
    if fault=='precision':d['rows'][0]['derived']['estimated_precision_met']=False
    if fault=='resources':d['operation_resources']={}
    with pytest.raises(ValueError):k.delivery_check(c,d)

def test_error_estimate_over_target_retained_not_enclosure():
    c=cfg();d=delivery(c);row=d['rows'][0];row['raw'][2]=literal(-.25,0,'1','2');row['derived']=k.derived(c,c['points'][0],row['raw'])
    assert not k.delivery_check(c,d)
    assert row['derived']['qualified_enclosure'] is False and F(row['derived']['values']['error_imag'])==1

def fixture(tmp,mp):
    tmp=tmp.resolve();c=cfg();e=tmp/'evidence.txt';e.write_text('Exact synthetic conventions, no executed integral.');c['evidence']=[{key:value for key,value in pin(e).items() if key!='size'}]
    config=tmp/'config.json';save(config,c);task={'config':str(config)}
    tool=tmp/'tool';tool.write_text('synthetic executable placeholder');tool.chmod(0o700)
    mp.setattr(a,'runtime',lambda c,b:([tool],[],tmp,{'python':tool,'make':tool,'cxx':tool},[tmp]))
    return task,c

def fake_execution(command,out,c):
    d=delivery(c);lib=out/'synthetic.so';lib.write_bytes(b'not a shared library; synthetic control only')
    d['generated_library']={'path':str(lib),'sha256':pin(lib)['sha256'],'bytes':lib.stat().st_size};d['imports_before']=[{'path':command[0],'sha256':pin(Path(command[0]))['sha256']}];d['imports_after']=deepcopy(d['imports_before'])
    k.write(out/'native-integrals.json',d)
    return {'returncode':0,'resource_violation':None,'new_events_generated':0}

@pytest.mark.parametrize('fault',['none','partial','input','native_output','completion','cap'])
def test_adapter_native_mock_full_custody_partial_and_cap(tmp_path,monkeypatch,fault):
    task,c=fixture(tmp_path,monkeypatch);out=tmp_path/'output'
    monkeypatch.setattr(a,'approved',lambda *args:{'max_seconds':30})
    from ravel.physics import reinterpret_db
    def execute(command,native,config):
        value=fake_execution(command,native,config)
        if fault=='partial':raise ValueError('synthetic native failure after full returned bytes')
        if fault=='input':(tmp_path/'evidence.txt').write_text('changed')
        if fault=='cap':(native/'large.bin').write_bytes(b'0'*(1024**2-100))
        return value
    monkeypatch.setattr(reinterpret_db,'execute_native',execute)
    orig=k.write
    def write(path,value):
        sha=orig(path,value)
        if path.name=='finite-integrals.json' and value['status']=='passed':
            if fault=='completion':path.write_text('{}')
            if fault=='native_output':(out/'native/native-integrals.json').write_text('{}')
        return sha
    monkeypatch.setattr(k,'write',write)
    r=a.run(task,tmp_path,out)
    assert r['status']==('passed' if fault=='none' else 'failed')
    assert (out/'raw-census.json').exists() and (out/'native/native-integrals.json').exists()
    if fault=='none':assert core_read(out/'finite-integrals.json')['status']=='passed' and (out/'reported-values.json').exists()
    if fault=='completion':assert core_read(out/'finite-integrals.json')=={} and (out/'delivery-failure.json').exists()
    if fault=='cap':assert core_read(out/'finite-integrals.json')['status']=='failed'

def core_read(p):return json.loads(p.read_text())

def test_approval_absence_prevents_output(tmp_path,monkeypatch):
    task,c=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='approved'):a.run(task,tmp_path,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def reference_fixture(tmp):
    c=cfg();config=save(tmp/'integral-config.json',c);d=delivery(c);doc=k.reference_document(c,d)
    deck=k.comparison_deck(c,heldout_ids=['p1'],atol='1e-14',rtol='0')
    e=tmp/'evidence.txt';e.write_text('Synthetic independent Feynman-parameter exact identity')
    p=c['points'][1];re,im=independent_zero_momentum(c,p)
    ref={'schema_version':1,'kind':'numerical-point-values','context':deck['context'],'axes':deck['axes'],
        'components':[{key:row[key] for key in ('id','unit','convention')} for row in deck['components']],
        'rows':[{'id':p['id'],'coordinates':k.numerical_arguments(c,p)['coordinates'],'values':{'real':{'mid':str(re),'radius':'0'},'imag':{'mid':str(im),'radius':'0'}}}]}
    comp={'schema_version':1,'kind':'heldout-numerical-reference-check','deck':save(tmp/'deck.json',deck),
        'candidate':{'id':'candidate','format':'finite-integral-reported/v1','file':save(tmp/'candidate.json',doc),'evidence':[pin(e)],'projection':{'configuration':config,'component_map':{'real':'real','imag':'imag'}}},
        'references':[{'id':'reference','file':save(tmp/'reference.json',ref),'evidence':[pin(e)]}], 'duplicate_reference_policy':'report'}
    save(tmp/'comparison.json',comp);return {'input':'comparison.json'},comp,doc,deck,ref

@pytest.mark.parametrize('fault',['none','raw','context','mapping','population','band','estimated_error'])
def test_real_existing_reference_consumer_reported_center_semantics(tmp_path,fault):
    task,c,doc,deck,ref=reference_fixture(tmp_path)
    if fault=='raw':doc['rows'][0]['raw'][2]=literal(2,0)
    if fault=='context':deck['context']['domain']='opposite imaginary prescription'
    if fault=='mapping':c['candidate']['projection']['component_map']['imag']='real'
    if fault=='population':doc['rows'].pop()
    if fault=='band':ref['rows'][0]['values']['real']['mid']='7'
    if fault=='estimated_error':
        row=doc['rows'][1];row['raw'][2]=literal(-.25,0,1,1);row['derived']=k.derived(doc['configuration'],row['point'],row['raw'])
    c['candidate']['file']=save(tmp_path/'candidate.json',doc);c['deck']=save(tmp_path/'deck.json',deck);c['references'][0]['file']=save(tmp_path/'reference.json',ref);save(tmp_path/'comparison.json',c)
    if fault in ('raw','context','mapping','population'):
        with pytest.raises(ValueError):nr.compare(task,tmp_path)
    else:
        r,_=nr.compare(task,tmp_path)
        assert r['status']==('failed' if fault=='band' else 'passed')
        assert not r['reported_center_metadata']['qualified_enclosure'] and not r['reported_center_metadata']['statistical_error_used_as_radius']
        assert not r['physics_validated'] and not r['withholding_chronology_verified']
        if fault=='estimated_error':assert not r['reported_center_metadata']['rows'][1]['estimated_precision_met']

def specification(task):
    return {'schema_version':2,'mode':'finite-integrals','source':'Pure constructed integral control','assumptions':['Synthetic optional runtime; native dispatch not called'],
        'max_seconds':30,'max_attempts':1,'approval_mode':'scripted_yes','task':task,
        'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'delivery','kind':'scientific'}],
        'claim_scopes':{k.SCOPE:{'checks':['integrity','delivery'],'actions':['delivery']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}}

def test_actual_plan_and_host_context_without_runtime_calls(tmp_path,monkeypatch):
    task,c=fixture(tmp_path,monkeypatch)
    from ravel.workflow import science
    spec=specification(task);save(tmp_path/'spec.json',spec)
    science.plan(tmp_path/'planned',tmp_path/'spec.json')
    assert science.adapter(spec) is a and not (tmp_path/'planned/inputs/science-approval.json').exists()
    plan=core_read(tmp_path/'planned/inputs/science-plan.json')
    assert {str(p) for p in a.inputs(task,tmp_path)}<=set(plan['stage_binding']['input_snapshot'])
    from ravel.workflow.agent_host import AgentHost,HostFailure
    rp=save(tmp_path/'task.json',task)
    pins=[{'id':'task',**rp},*[{'id':'p'+str(i),**pin(p)} for i,p in enumerate(a.context_inputs(task,tmp_path))]]
    node={'id':'context','kind':'tool','role':'designer','depends_on':[],'inputs':pins,'packet':None,'action':'finite-integrals-context','parameters':{'request_input':'task'},'max_attempts':1}
    pins=[{key:value for key,value in row.items() if key!='size'} for row in pins]
    node['inputs']=pins
    host=AgentHost(api_key='not-used',bound_roots=[str(tmp_path),str(a.API.parent)])
    control=NS(cancelled=lambda:False,call=lambda action,kind,request,operation:operation())
    value=host.execute(node,{'request_id':'pure','packet':None,'input_artifacts':pins},control)
    assert value['value']['mode']=='finite-integrals' and value['value']['execution_authorized'] is False
    node['inputs']=pins[:-1]
    with pytest.raises(HostFailure):host.execute(node,{'request_id':'pure','packet':None,'input_artifacts':pins[:-1]},control)

@pytest.mark.parametrize('fail',['none','second_return','build','unbound_import'])
def test_actual_worker_source_against_fake_optional_api(tmp_path,monkeypatch,fail):
    from ravel.physics import finite_integrals_worker as w
    c=cfg();out=tmp_path/'native';out.mkdir();site=tmp_path/'site';site.mkdir();src=site/'synthetic.py';src.write_text('# inert fixture')
    psd=ModuleType('pySecDec');psd.__file__=str(src);psd.__version__=k.VERSION
    interface=ModuleType('pySecDec.integral_interface');interface.__file__=str(src)
    contrib=ModuleType('pySecDecContrib');contrib.__file__=str(src);contrib.dirname=str(tmp_path)
    monkeypatch.setitem(sys.modules,'pySecDecContrib',contrib)
    monkeypatch.setenv('MAKEFLAGS','-j99');monkeypatch.setenv('SECDEC_WITH_CUDA','80')
    observed={};returns=delivery(c)['rows']
    def make_integral(**kw):observed['integral']=kw;return 'synthetic integral'
    def generate(**kw):observed['package']=kw;(out/'finite_integral').mkdir()
    class Fake:
        info={'name':'finite_integral','number_of_complex_parameters':'3','number_of_real_parameters':'3'}
        def __init__(self,path):self.i=0
        def use_Qmc(self,**kw):observed.setdefault('qmc',[]).append(kw)
        def __call__(self,**kw):
            observed.setdefault('calls',[]).append(kw);i=self.i;self.i+=1
            return returns[i]['raw'] if not(fail=='second_return' and i==1) else ['one','two','not a finite integral']
    psd.LoopIntegralFromPropagators=make_integral;psd.loop_package=generate;interface.IntegralLibrary=Fake
    monkeypatch.setitem(sys.modules,'pySecDec',psd);monkeypatch.setitem(sys.modules,'pySecDec.integral_interface',interface)
    def build(*args,**kwargs):
        assert args[0][1]=='-j1' and kwargs['timeout']>0
        (out/'finite_integral/finite_integral_pylink.so').write_bytes(b'synthetic not loaded')
        return NS(returncode=2 if fail=='build' else 0)
    monkeypatch.setattr(w.subprocess,'run',build)
    request={'config':c,'output':str(out),'ravel_source_root':str(Path(k.__file__).parents[2]),'sites':[str(site)],'contrib_root':str(tmp_path),'path':'/usr/bin','make':'/synthetic/make','cxx':'/synthetic/cxx','runtime_assets':{str(src):pin(src)['sha256']}}
    # Controlled script frame for the new exact copied-entry source contract.
    driver=out/'driver.py';driver.write_bytes(Path(w.__file__).read_bytes())
    request['driver']={key:value for key,value in pin(driver).items() if key!='size'}
    request['runtime_assets'][str(driver)]=request['driver']['sha256']
    main_module=ModuleType('__main__');main_module.__file__=str(driver)
    monkeypatch.setattr(w,'__file__',str(driver))
    monkeypatch.setitem(sys.modules,'__main__',main_module)
    monkeypatch.setitem(sys.modules,'__mp_main__',main_module)
    for name,module in list(sys.modules.items()):
        if name.split('.')[0] in {'yaml','numpy','sympy','mpmath'} and getattr(module,'__file__',None):
            f=Path(module.__file__).resolve();request['runtime_assets'][str(f)]=pin(f)['sha256']
    if fail=='unbound_import':request['runtime_assets'].pop(str(src))
    save(tmp_path/'request.json',request)
    oldenv=dict(w.os.environ);oldpath=sys.path[:]
    try:
        if fail=='none':w.main(tmp_path/'request.json')
        else:
            with pytest.raises(ValueError):w.main(tmp_path/'request.json')
    finally:w.os.environ.clear();w.os.environ.update(oldenv);sys.path[:]=oldpath
    d=core_read(out/'native-integrals.json')
    if fail=='none':
        assert k.delivery_check(c,d)
        assert observed['package']['contour_deformation'] is False and observed['package']['processes']==1
        assert 'MAKEFLAGS' in d['cleared_build_environment_keys'] and 'SECDEC_WITH_CUDA' in d['cleared_build_environment_keys']
        assert all(x['cputhreads']==1 and x['devices']==[] for x in observed['qmc'])
        assert all(x['number_of_threads']==1 for x in observed['calls'])
    else:
        assert d['status']=='failed'
        if fail=='second_return':
            assert d['calls_returned']==2 and d['rows'][1]['raw'][2]=='not a finite integral' and d['rows'][0]['derived']
            assert core_read(out/'p1.native-return.json')['raw'][2]=='not a finite integral'
        if fail=='build':assert d['calls_started']==0


@pytest.mark.parametrize('fail',[False,True])
def test_actual_common_worker_full_lifecycle(tmp_path,monkeypatch,fail):
    from ravel.workflow import science
    from ravel.physics import science_worker, reinterpret_db
    task,c=fixture(tmp_path,monkeypatch);spec=specification(task);rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    proposal={'schema_version':2,'base_dir':str(tmp_path.resolve()),'attempt':1,'output_directory':'outputs/attempt-1','max_seconds':30,'stage_binding':{'input_snapshot':{}}}
    save(rd/'inputs/science-plan.json',proposal);save(rd/'inputs/science.json',spec)
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal);monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    monkeypatch.setattr(science,'verify_worker',lambda _:proposal);monkeypatch.setattr(science,'execution_spec',lambda _:spec)
    def native(command,out,c):
        r=fake_execution(command,out,c)
        if fail:raise ValueError('synthetic failure, raw returns retained')
        return r
    monkeypatch.setattr(reinterpret_db,'execute_native',native)
    assert science_worker.main([str(rd),'--attempt','1'])==(3 if fail else 0)
    out=rd/'outputs/attempt-1';r=core_read(out/'result.json')
    assert r==core_read(out/'finite-integrals/finite-integrals.json')
    assert core_read(out/'verification.json')['passed'] is (not fail)
    assert core_read(out/'figures.json')['figures']==[]
    assert (out/'RESULT.md').is_file() and not r['qualified_enclosure']
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])

@pytest.mark.parametrize('fault',['none','extra_data','changed_source','alias','executable'])
def test_complete_runtime_census_and_release_source_binding(tmp_path,monkeypatch,fault):
    root=tmp_path/'runtime';package=root/'site/pySecDec';package.mkdir(parents=True);contrib=root/'contrib';contrib.mkdir()
    src=package/'__init__.py';src.write_text('# source fixture, never imported')
    data=root/'weights.pkl';data.write_bytes(b'not a pickle; source census fixture')
    doc={'schema_version':1,'files':{str(p.relative_to(root)):pin(p)['sha256'] for p in (src,data)}}
    manifest=save(tmp_path/'manifest.json',doc);manifest.pop('size')
    api=tmp_path/'api.json';save(api,{'required_package_files':{'__init__.py':pin(src)['sha256']}});monkeypatch.setattr(a,'API',api)
    tool=tmp_path/'tool';tool.write_text('# no execution');tool.chmod(0o700);toolpin=pin(tool);toolpin.pop('size')
    c=cfg();c['runtime']={'python':toolpin,'make':toolpin,'cxx':toolpin,'trees':[{'root':str(root),'manifest':manifest}],'site_roots':[str(root/'site')],'contrib_root':str(contrib),'path':[str(tmp_path)],'version':k.VERSION}
    if fault=='extra_data':(root/'new.pkl').write_bytes(b'extra')
    if fault=='changed_source':src.write_text('different')
    if fault=='alias':(root/'alias').symlink_to(src)
    if fault=='executable':tool.chmod(0o600)
    if fault=='none':assert data in a.runtime(c,tmp_path)[0]
    else:
        with pytest.raises(ValueError):a.runtime(c,tmp_path)


def test_nonfinite_overflow_and_optimized_native_refuse_before_input(monkeypatch):
    with pytest.raises(ValueError):k.number('1e999')
    from ravel.physics import finite_integrals_worker as w
    monkeypatch.setattr(w.sys,'flags',NS(optimize=1))
    with pytest.raises(ValueError,match='optimized'):w.main('/never-read')
