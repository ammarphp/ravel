"""Authored pure controls. No diagram engine, SymPy, licensed kernel or CAS call."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from ravel.physics import feyn_graph as fg, feyn_graph_worker as worker
from ravel.physics import diagram_analysis as da, feynarts_amplitude as fa, symbolic_evaluation as se
from ravel.workflow import science


def process():
    field=lambda n,a:{'type':'F','index':2,'indices':[n],'antiparticle':a}
    return {'id':'electron_scattering','incoming':[field(1,False),field(1,True)],'outgoing':[field(2,False),field(2,True)],'loops':0,'incoming_momenta':['p1','p2'],'outgoing_momenta':['p3','p4'],'loop_momenta':[],'adjacencies':[3,4],'max_diagrams':16,'render_pdf':True}


def cfg():
    return {'schema_version':1,'source':'Inert API fixture','original_task':{'path':'goal.json','sha256':'0'*64},'trusted_native_sources':True,'engine_commit':fg.COMMIT,'engine_source':{'root':'engine','manifest':{'path':'tree.json','sha256':'0'*64}},'runtime':{'python':{'path':'python','sha256':'0'*64},'trees':[{}],'site_roots':['runtime'],'engine_module':'feyngraph'},'model':{'kind':'ufo','tree':{},'entry':'.','gauge':'Feynman','source_vertex_names':['V_1']},'processes':[{'id':'decay','incoming':['X'],'outgoing':['s','t'],'loops':0,'momentum_labels':['p1','p2','p3'],'selectors':[]}],'conventions':'Structural diagrams only','render':{'formats':['svg','tikz'],'max_visualize':1},'max_diagrams':10,'max_seconds':10,'max_ram_mib':512,'max_output_bytes':100000}


def test_explicit_model_passed_and_full_census(tmp_path,monkeypatch):
    selected=[];marker=object()
    class Model:
        def particles(self):return []
        def vertices(self):return [SimpleNamespace(name=lambda:'V_1',coupling_orders=lambda:{})]
        def splitting(self,n):return None
    class Container:
        def __len__(self):return 2
        def __getitem__(self,i):return SimpleNamespace(draw_svg=lambda p:Path(p).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>'),draw_tikz=lambda p:Path(p).write_text('\\begin{tikzpicture}\\end{tikzpicture}'))
    class Generator:
        def __init__(self,inc,out,loops,model,selector):selected.append((inc,out,loops,model,selector))
        def set_momentum_labels(self,labels):selected.append(labels)
        def generate(self):return Container()
    engine=SimpleNamespace(DiagramGenerator=Generator,DiagramSelector=lambda:marker,set_threads=lambda n:selected.append(n))
    monkeypatch.setattr(worker,'row',lambda d,i,l:{'id':i,'incoming':[],'outgoing':[]})
    model=Model();writes=[];r=worker.enumerate_processes(cfg(),engine,model,tmp_path,lambda x:writes.append(deepcopy(x)))
    assert selected[1][3] is model and selected[1][4] is marker and selected[0]==1
    assert selected[2]==['p1','p2','p3'] and r['complete'] is True
    assert [d['id'] for d in r['processes'][0]['diagrams']]==[0,1]
    assert len(r['processes'][0]['renders'])==2 and writes[0]['complete'] is False


def test_population_cap_preserves_failed_whole_count(tmp_path):
    c=cfg();c['max_diagrams']=1;writes=[]
    model=SimpleNamespace(particles=lambda:[],vertices=lambda:[SimpleNamespace(name=lambda:'V_1',coupling_orders=lambda:{})],splitting=lambda n:None)
    class G:
        def __init__(self,*args):pass
        def set_momentum_labels(self,v):pass
        def generate(self):return [object(),object()]
    engine=SimpleNamespace(DiagramGenerator=G,DiagramSelector=lambda:object(),set_threads=lambda n:None)
    with pytest.raises(ValueError,match='no truncation'):worker.enumerate_processes(c,engine,model,tmp_path,lambda x:writes.append(deepcopy(x)))
    assert writes[-1]['complete'] is False and writes[-1]['processes'][0]['count']==2


@pytest.mark.parametrize('key,value',[('engine_commit','other'),('trusted_native_sources',False),('max_diagrams',True)])
def test_declared_enumeration_mismatch(key,value):
    c=cfg();c[key]=value
    with pytest.raises(ValueError):fg.config(c)


def test_supplied_model_cannot_be_implicit_builtin():
    c=cfg();c['model']['kind']='builtin-sm-feynman'
    with pytest.raises(ValueError,match='explicit selection'):fg.config(c)


def test_modes_reach_real_adapters():
    for mode,module in [('feyn-graph',fg),('diagram-analysis',da),('feynarts-amplitude',fa)]:assert mode in science.MODES and science.adapter({'mode':mode,'task':{}}) is module


def test_typed_amplitude_keeps_full_list_spinors_and_native_export():
    s=fa.script(process())
    for x in ('CreateTopologies[0,2->2','Model->ravelClassesModel','GenericModel->ravelGenericModel','InsertionLevel->{Particles}','Truncated->False','FCFAConvert[','List->True','DropSumOver->False','ravelAmplitude=Total[ravelConverted]','"converted_amplitudes"','Export[ravelDiagramPDF,Paint['):assert x in s
    assert 'NIntegrate' not in s and 'mathematica_to_callable' not in s


@pytest.mark.parametrize('key,value',[('loops',True),('incoming_momenta',['p1','p1']),('loop_momenta',['k1']),('adjacencies',[]),('render_pdf',1)])
def test_full_amplitude_process_fields(key,value):
    p=process();p[key]=value
    with pytest.raises(ValueError):fa.script(p)


def test_explicit_model_file_names():
    a={'version':'3.12','tree':{},'entry':'FeynArts.m','model_tree':{},'classes_model':'SM','generic_model':'Lorentz','patched_source_receipt':{}}
    assert fa.addon(a)==a
    a['classes_model']='unsupplied/model'
    with pytest.raises(ValueError):fa.addon(a)


def test_split_vertex_is_explicitly_unsupported():
    d={'vertices':[{'interaction':{'name':'V_1a'}}],'propagators':[],'loops':[]}
    with pytest.raises(ValueError,match='split Lorentz/color'):da.source_vertex(d,[{'name':'V_1','splitting':{'V_1a':[[0,0]]}}])
    assert da.source_vertex(d,[])=='V_1a'


def test_nda_never_discards_complex_phase():
    with pytest.raises(ValueError,match='complex phases'):da.nda_diagram({'diagram':{}},{'coefficient_coordinates':{'g':{'real':1,'imag':2}}})
    assert da.nda_diagram({'diagram':{}},{'coefficient_coordinates':{'g':{'real':-2,'imag':0}}})['couplings']=={'g':-2}


def test_scalar_converter_existing_exact_signature():
    converter=SimpleNamespace(mathematica_to_sympy=lambda f:SimpleNamespace(free_symbols=set()),mathematica_to_python_source=lambda *a,**k:'def result_width():\n    return 2.0\n')
    declaration={'id':'width','variables':[],'units':'GeV','dimension_GeV':1,'conventions':'Exact supplied scalar','assumptions':[],'points':[]}
    r=se.convert_result({'id':'width','symbol':'width','formula':'2.0'},declaration,converter)
    assert r['status']=='delivered' and r['numerical_status']=='not_requested' and r['physics_validated'] is False


def test_original_marker_population():
    assert se.marker_census('SYMBOLIC_RESULT[x]: 1\nLATEX_RESULT[x]: 1\nSTATUS: complete\n',{'symbolic':['x'],'numerical':[],'latex':['x'],'status':'complete'})['valid']


def test_native_count_boolean_is_not_integer(tmp_path):
    c=cfg();d={'schema_version':1,'engine_commit':fg.COMMIT,'model':c['model'],'model_particles':[],'model_vertices':[{'name':'V_1','coupling_orders':{}}],'source_vertex_splittings':[{'name':'V_1','splitting':None}],'processes':[{'request':c['processes'][0],'count':True,'diagrams':[{'id':0,'incoming':[{'particle':{'name':'X'}}],'outgoing':[{'particle':{'name':'s'}},{'particle':{'name':'t'}}]}],'renders':[],'complete':True}],'complete':True,'imports':[]}
    with pytest.raises(ValueError,match='full native diagram census'):fg.check_delivery(c,d,tmp_path)


def test_common_report_preserves_original_structured_result(tmp_path):
    out=tmp_path/'feyn-graph';out.mkdir();r={'status':'passed','delivery':None,'errors':[],'physics_validated':False,'original_task_complete':False}
    d=fg.finish({},tmp_path,out,r,{}, {},100000,input_loader=lambda *a:[])
    table=fg.write_report(out,d);(tmp_path/'result.json').write_text(json.dumps(r))
    assert table[0]['stem']=='diagram-report' and 'diagram-result.json' in table[0]['files']
    fg.finalize(d,out,common=tmp_path)
    (out/'diagram-report.md').write_text('changed report')
    with pytest.raises(ValueError,match='original artifacts'):fg.finalize(d,out,common=tmp_path)


@pytest.mark.parametrize('mode', ['feyn-graph','diagram-analysis'])
def test_real_common_worker_report_tail_with_inert_adapter(tmp_path,monkeypatch,mode):
    """Exercises real ordinary serialization/report/finalize, no diagram runtime."""
    from ravel.physics import science_worker as common
    rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    (rd/'inputs/science-plan.json').write_text('{}\n')
    task={'input':'inert-unused-request','input_sha256':'0'*64}
    spec={'schema_version':2,'mode':mode,'task':task,'source':'Explicit inert adapter delivery fixture','assumptions':['No native, model or CAS call.']}
    selected={'max_seconds':45,'output_directory':'outputs/attempt-1','base_dir':str(tmp_path),'stage_binding':{'input_snapshot':[]}}
    for module in (science,common):
        monkeypatch.setattr(module,'verify_worker',lambda *a:selected)
        monkeypatch.setattr(module,'execution_spec',lambda *a:spec)
    implementation=fg if mode=='feyn-graph' else da
    def inert(task,base,out):
        out=Path(out);out.mkdir(parents=True)
        result={'schema_version':1,'status':'passed','status_scope':implementation.SCOPE,'physics_validated':False,'original_task_complete':False,'delivery':None,'errors':[]}
        if mode=='diagram-analysis':result.update(requested_diagram_count=2,rows=[{'id':'process-d0','status':'constructed'},{'id':'process-d1','status':'constructed'}])
        return fg.finish(task,base,out,result,{}, {},100000,input_loader=lambda *a:[])
    monkeypatch.setattr(implementation,'run',inert)
    assert common.main([str(rd)])==0
    out=rd/'outputs/attempt-1';value=json.loads((out/'result.json').read_text())
    assert value['physics_validated'] is False and value['original_task_complete'] is False
    tables=json.loads((out/'figures.json').read_text())['tables']
    assert mode+'/diagram-result.json' in tables[0]['files']
    assert mode+'/diagram-report.md' in (out/'RESULT.md').read_text()
    assert json.loads((out/mode/'diagram-result.json').read_text())==value


def test_model_bound_wrapper_uses_admitted_addon_and_model_path():
    c={'schema_version':2,'provider_entry':'FeynCalc/FeynCalc.m','provider_version_symbol':'FeynCalc`$FeynCalcVersion','feynarts':{'classes_model':'SelectedModel','generic_model':'Lorentz'}}
    s={'id':'script','results':[{'id':'amplitude','symbol':'ravelAmplitude'}]}
    value=se.wrapper_script(c,s,Path('/owned/provider'),Path('/owned/process.wl'),Path('/owned/out/sidecar.json'),Path('/owned/feynarts'),Path('/owned/models'))
    for literal in ('$FAPatch=False','FeynCalc`$FeynArtsDirectory="/owned/feynarts"','FeynArts`$ModelPath={"/owned/models"}','ravelFADirectoryBefore=FeynArts`$FeynArtsDir','"directory"->FeynArts`$FeynArtsDir','"records"->ravelFARecords','FeynCalc`$FeynCalcVersion'):
        assert literal in value
    assert 'AutoInstallFeynArts' not in value and 'UserBaseDirectory=' not in value
    assert '\n$FeynArtsDirectory=' not in value and 'Global`$FeynArtsDirectory' not in value



def test_actual_unapproved_science_plan_and_input_preservation(tmp_path,monkeypatch):
    import hashlib
    def save(path,value):
        path.write_text(json.dumps(value)+'\n' if type(value) is not str else value)
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    def tree(name,files):
        root=tmp_path/name;root.mkdir()
        for rel,raw in files.items():
            path=root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(raw)
        return {'root':str(root),'manifest':save(tmp_path/(name+'.json'),fg.custody.source_tree(root))}
    c=cfg();c['original_task']=save(tmp_path/'goal.json',{'requested_quantities':['complete diagrams'],'independent_physics_correctness':None})
    c['engine_source']=tree('engine',{'api.txt':'Inert primary API fixture'})
    api=tmp_path/'api.json';save(api,{'feyngraph':{'required_sources':{'api.txt':hashlib.sha256(b'Inert primary API fixture').hexdigest()}}});monkeypatch.setattr(fg,'API',api)
    c['model']['tree']=tree('model',{'vertices.py':"V_1=Vertex(name='V_1')\n"})
    rt=tree('runtime',{'feyngraph.py':'# Inert namespace; never imported or executed\n','python':'# Inert executable fixture\n'})
    executable=Path(rt['root'])/'python';executable.chmod(0o700)
    c['runtime']={'python':{'path':str(executable),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()},'trees':[rt],'site_roots':[rt['root']],'engine_module':'feyngraph'}
    config=tmp_path/'enumeration.json';task={'input':str(config),'input_sha256':save(config,c)['sha256']}
    policy={'schema_version':1,'actors':{'proposer':'inert-proposer','executor':'inert-executor','physics_critic':'inert-critic','skeptical_verifier':'inert-verifier','physics_decider':'inert-decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'custody','kind':'integrity'}],'claim_scopes':{fg.SCOPE:{'checks':['custody'],'actions':['delivery']}}}
    spec={'schema_version':2,'mode':'feyn-graph','source':'Inert source/runtime planning control','assumptions':['No engine, subprocess, model or CAS call.'],'max_seconds':45,'approval_mode':'scripted_yes','max_attempts':1,'task':task,'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    path=tmp_path/'spec.json';save(path,spec);rd=tmp_path/'run'
    science.plan(rd,path);science.verify_plan(rd,approved=False)
    assert not (rd/'inputs/science-approval.json').exists()
    (Path(c['model']['tree']['root'])/'vertices.py').write_text("V_1=Vertex(name='other')\n")
    with pytest.raises(ValueError):science.verify_plan(rd,approved=False)


@pytest.mark.parametrize('case',['complete','omitted_counterterm','reordered','duplicate_declared','duplicate_source'])
def test_complete_ufo_regular_and_counterterm_source_roster(tmp_path,monkeypatch,case):
    """Real source-census API over literal inert files; no UFO/native import."""
    import hashlib
    def save(path,value):
        path.write_text(json.dumps(value)+'\n' if type(value) is not str else value)
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    def tree(name,files):
        root=tmp_path/name;root.mkdir()
        for relative,value in files.items():(root/relative).write_text(value)
        return {'root':str(root),'manifest':save(tmp_path/(name+'.json'),fg.custody.source_tree(root))}
    c=cfg();c['original_task']=save(tmp_path/'goal.json',{'requested_quantities':['complete regular and counterterm diagrams']})
    c['engine_source']=tree('engine',{'api.txt':'Inert primary API fixture'})
    api=tmp_path/'api.json';save(api,{'feyngraph':{'required_sources':{'api.txt':hashlib.sha256(b'Inert primary API fixture').hexdigest()}}});monkeypatch.setattr(fg,'API',api)
    ct="VCT_1=CTVertex(name='VCT_1')\n"
    if case=='duplicate_source':ct+="VCT_2=CTVertex(name='VCT_1')\n"
    c['model']['tree']=tree('model',{'vertices.py':"V_1=Vertex(name='V_1')\n",'CT_vertices.py':ct})
    c['model']['source_vertex_names']=['V_1','VCT_1']
    if case=='omitted_counterterm':c['model']['source_vertex_names']=['V_1']
    if case=='reordered':c['model']['source_vertex_names']=['VCT_1','V_1']
    if case=='duplicate_declared':c['model']['source_vertex_names']=['V_1','VCT_1','VCT_1']
    rt=tree('runtime',{'feyngraph.py':'# Inert source; never imported\n','python':'# Inert executable; never launched\n'})
    executable=Path(rt['root'])/'python';executable.chmod(0o700)
    c['runtime']={'python':{'path':str(executable),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()},'trees':[rt],'site_roots':[rt['root']],'engine_module':'feyngraph'}
    path=tmp_path/'enumeration.json';task={'input':str(path),'input_sha256':save(path,c)['sha256']}
    original=fg.custody.source_tree(Path(c['model']['tree']['root']))
    if case=='complete':
        admitted=fg.inputs(task,tmp_path)
        assert Path(c['model']['tree']['root'])/'vertices.py' in admitted
        assert Path(c['model']['tree']['root'])/'CT_vertices.py' in admitted
    else:
        with pytest.raises(ValueError):fg.inputs(task,tmp_path)
    assert fg.custody.source_tree(Path(c['model']['tree']['root']))==original


@pytest.mark.parametrize('case',['complete','omitted_counterterm','reordered','duplicate'])
def test_native_split_roster_retains_every_regular_and_counterterm(tmp_path,case):
    c=cfg();c['model']['source_vertex_names']=['V_1','VCT_1'];seen=[]
    def splitting(name):seen.append(name);return {'native_'+name:[[0,0]]}
    model=SimpleNamespace(particles=lambda:[],vertices=lambda:[SimpleNamespace(name=lambda n=n:'native_'+n,coupling_orders=lambda:{}) for n in c['model']['source_vertex_names']],splitting=splitting)
    class Generator:
        def __init__(self,*args):assert args[3] is model
        def set_momentum_labels(self,labels):assert labels==c['processes'][0]['momentum_labels']
        def generate(self):return []
    engine=SimpleNamespace(DiagramGenerator=Generator,DiagramSelector=lambda:object(),set_threads=lambda n:None)
    result=worker.enumerate_processes(c,engine,model,tmp_path,lambda value:None)
    assert seen==['V_1','VCT_1'] and result['complete'] is True
    if case=='omitted_counterterm':result['source_vertex_splittings'].pop()
    if case=='reordered':result['source_vertex_splittings'].reverse()
    if case=='duplicate':result['source_vertex_splittings'].append(deepcopy(result['source_vertex_splittings'][1]))
    if case=='complete':assert fg.check_delivery(c,result,tmp_path) is result
    else:
        with pytest.raises(ValueError,match='splitting roster'):fg.check_delivery(c,result,tmp_path)


def amplitude_sidecar_fixture():
    provider=Path('/owned/provider')
    c={'schema_version':2,'provider_entry':'FeynCalc/FeynCalc.m','expected_kernel_version':13.3,'expected_provider_version':'10.1.0'}
    script={'id':'script','results':[{'id':'amplitude','symbol':'ravelAmplitude'}],'feynarts_process':{'max_diagrams':16}}
    receipt={'schema_version':1,'script_id':'script','kernel_version':13.3,'kernel_version_string':'Inert Wolfram fixture',
             'process_id':31,'provider_loaded':True,'provider_before':'/owned/provider/FeynCalc/FeynCalc.m',
             'provider_after':'/owned/provider/FeynCalc/FeynCalc.m','provider_version':'10.1.0','script_ok':True,
             'parallel_kernel_count':0,'results':[{'id':'amplitude','symbol':'ravelAmplitude','defined':True,'formula':'Gamma[p]'}],
             'feynarts':{'version':'FeynArts 3.12 (27 Mar 2025)','configured_directory':'/owned/feynarts',
             'directory_before':'/owned/feynarts','directory':'/owned/feynarts','model_path':['/owned/models'],
             'records':{'diagram_count':1,'topologies':'topology','insertions':'insertion','original_amplitudes':'amplitude','converted_amplitudes':['converted']}}}
    return c,script,receipt,provider


@pytest.mark.parametrize('case',['complete','trailing_separator','foreign_before','foreign_after','foreign_loader','missing_before','boolean_directory'])
def test_actual_loaded_addon_directory_readback_is_required(case):
    c,script,receipt,provider=amplitude_sidecar_fixture()
    if case=='trailing_separator':receipt['feynarts']['directory_before']+='/';receipt['feynarts']['directory']+='/'
    if case=='foreign_before':receipt['feynarts']['directory_before']='/foreign/feynarts'
    if case=='foreign_after':receipt['feynarts']['directory']='/foreign/feynarts'
    if case=='foreign_loader':receipt['feynarts']['configured_directory']='/foreign/feynarts'
    if case=='missing_before':receipt['feynarts'].pop('directory_before')
    if case=='boolean_directory':receipt['feynarts']['directory']=True
    if case in ('complete','trailing_separator'):
        assert se.validate_sidecar(receipt,c,script,provider,31)==receipt['results']
    else:
        with pytest.raises(ValueError):se.validate_sidecar(receipt,c,script,provider,31)


def test_legacy_schema1_addon_free_wrapper_and_sidecar_stay_valid():
    c,script,receipt,provider=amplitude_sidecar_fixture();c.update(schema_version=1,provider_version_symbol='FeynCalc`$FeynCalcVersion')
    receipt.pop('feynarts');script.pop('feynarts_process')
    assert se.validate_sidecar(receipt,c,script,provider,31)==receipt['results']
    value=se.wrapper_script(c,script,provider,Path('/owned/process.wl'),Path('/owned/sidecar.json'))
    assert '$LoadAddOns={};' in value and '$FeynArtsDirectory' not in value and '$FeynArtsDir' not in value
