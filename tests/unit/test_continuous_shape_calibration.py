"""Artificial source laws/recording facades only; no ROOT or calibration trials."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import math
import shutil
import sys
import pytest
from ravel.physics import regional_calibration as c, statistical_construction as r
from ravel.physics import full_auxiliary_calibration as a, native_likelihood as n
from test_full_auxiliary_calibration import fixture as base_fixture, configuration as base_configuration, fake
from test_regional_expected import e


def fixture(tmp_path, *, fixed=False, response=True):
    d,q=base_fixture(tmp_path)
    d['parameters'].append({'name':'slope','role':'coefficient','initial':'0','bounds':['-1/2','1/2'],'fixed':fixed,'meaning':'Artificial inverse-unit continuous density slope','source':'s'})
    shape={'kind':'normalized_exponential','domain':['0','4'],'bin_windows':[['0','1'],['2','4'],None],'slope_parameter':'slope','slope_log_response':['1/10' if response else '0']}
    d['terms'][0].update(coefficients=['50','50','0'],shape=shape)
    d['terms'].append({'id':'signed','basis':'interference','coefficients':['-1/2','-1/2','0'],'powers':{'mu':1},'log_response':[['0'],['0'],['0']],'source':'s'})
    # Existing BSM term keeps the TOTAL positive; the negative term is retained.
    q['truths'][0]['point']['slope']='0'
    r.validate(d);c.validate(q,d)
    return d,q


def configuration(tmp_path):
    cp,cfg,_,_=base_configuration(tmp_path)
    d,q=fixture(tmp_path)
    source=tmp_path/'shape-construction.json';source.write_text(json.dumps(d))
    card=tmp_path/'shape-card.txt';card.write_bytes(r.datacard(d))
    pin=lambda p:{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    cfg['model']['construction']=pin(source)
    cfg['model']['files']=[{**pin(card),'staged_path':cfg['model']['card']}]
    cfg['calibration']=q;cp.write_text(json.dumps(cfg))
    return cp,cfg,d,q


def bundle(tmp_path,d):
    root=tmp_path/'work';root.mkdir()
    files={}
    for name,source in zip(c.SHAPE_SOURCE_MEMBERS,c.shape_source_paths(d)):
        target=root/'ravel_calibration_source'/'ravel'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        files[name]={'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':source.stat().st_size}
    return root,{'kind':c.SHAPE_SOURCE_KIND,'files':files}


def test_zero_slope_independent_area_and_full_unobserved_mass(tmp_path):
    d,q=fixture(tmp_path,response=False);point=q['truths'][0]['point']
    got=c.means(d,point)
    theta=F('5/4');beta=1.;mu=1.
    assert got['SR']==pytest.approx(50*beta*math.exp(float(theta/10))*.25+1.5*mu)
    assert got['CR']==pytest.approx(50*beta*math.exp(-float(theta/10))*.5+2.5*mu)
    assert got['MC']==3.
    fractions,_=r.parametric_shapes.fractions(d['terms'][0]['shape'],F(0))
    assert fractions==[.25,.5,0.] and sum(fractions)==.75
    assert list(got.values())==pytest.approx(r.mean_jet(d,point)['means'])


@pytest.mark.parametrize('slope',['-25/2','-1/1000','0','1/1000','25/2'])
def test_nonzero_slope_independent_integral_anchor(tmp_path,slope):
    d,q=fixture(tmp_path,response=False)
    d['parameters'][-1]['bounds']=['-25/2','25/2'];point=q['truths'][0]['point'];point['slope']=slope
    got=c.means(d,point);v=float(F(slope));theta=1.25
    def integral(lo,hi):
        if not v:return (hi-lo)/4
        return (math.exp(v*hi)-math.exp(v*lo))/math.expm1(4*v)
    assert got['SR']==pytest.approx(50*math.exp(theta/10)*integral(0,1)+1.5,rel=2e-12)
    assert got['CR']==pytest.approx(50*math.exp(-theta/10)*integral(2,4)+2.5,rel=2e-12)
    assert got['MC']==3


def test_correlated_shape_truth_and_full_source_nll(tmp_path):
    d,q=fixture(tmp_path);point=q['truths'][0]['point'];original=deepcopy(d)
    t=c.toy(q,d,q['truths'][0],0);got=c.means(d,point)
    assert list(got.values())==pytest.approx(r.mean_jet(d,point)['means'])
    assert set(t['counts'])=={'SR','CR','MC'} and set(t['globals'])=={'ravel_aux_0_In'}
    direct=sum(v-t['counts'][b]*math.log(v)+math.lgamma(t['counts'][b]+1) for b,v in got.items())+.5*(.5-t['globals']['ravel_aux_0_In'])**2
    assert c.source_nll(d,point,t)==pytest.approx(direct) and d==original
    q['auxiliary_mode']='conditional';u=c.toy(q,d,q['truths'][0],0)
    assert u['counts']['MC']==3 and u['globals']=={'ravel_aux_0_In':0.}
    assert c.seed_for(q,'truth1',0,'count:SR')==c.seed_for({**q,'auxiliary_mode':'unconditional'},'truth1',0,'count:SR')


@pytest.mark.parametrize('change',[lambda d,q:d['terms'][0]['shape'].update(kind='unknown_pdf'),lambda d,q:d['terms'][0]['shape']['bin_windows'].__setitem__(2,['0','1']),lambda d,q:q['truths'][0]['point'].update(slope='2'),lambda d,q:d['terms'][0]['shape'].update(slope_log_response=['20']),lambda d,q:d['parameters'][-1].update(fixed=True) or q['truths'][0]['point'].update(slope='1/10')])
def test_explicit_shape_domain_and_fixed_truth_refusals(tmp_path,change):
    d,q=fixture(tmp_path);change(d,q)
    with pytest.raises(ValueError):c.validate(q,d)


def test_no_shape_seed_means_and_observation_bytes_preserved(tmp_path):
    d,q=base_fixture(tmp_path)
    def legacy(point):
        theta=F('1/4')+2*F(point['ravel_aux_0'])
        return {'SR':float(F('41/4')*F(point['beta']))*math.exp(float(theta/10))+2*float(F(point['mu'])),
                'CR':float(F('41/2')*F(point['beta']))*math.exp(float(-theta/10))+3*float(F(point['mu'])),
                'MC':3*float(F(point['beta']))}
    assert c.shape_source_paths(d)==[] and c.shape_description(d) is None
    assert c.means(d,q['truths'][0]['point'])==legacy(q['truths'][0]['point'])
    observation=c.toy(q,d,q['truths'][0],0)
    assert observation==c.toy(q,d,q['truths'][0],0)
    assert set(observation)=={'counts','globals','physical_gaussian_measurement','means_at_fixed_truth','component_seeds','rng','auxiliary_mode','sha256'}
    assert observation['means_at_fixed_truth']==legacy(q['truths'][0]['point'])



def test_bound_native_source_package_is_standalone(tmp_path):
    d,q=fixture(tmp_path);root,binding=bundle(tmp_path,d);before=list(sys.path)
    saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')}
    for name in saved:sys.modules.pop(name)
    try:
        c.bind_shape_sources(root,binding)
        staged=sys.modules['ravel.physics.parametric_shapes']
        assert Path(staged.__file__).is_relative_to(root)
        assert list(c.means(d,q['truths'][0]['point']).values())==pytest.approx(r.mean_jet(d,q['truths'][0]['point'])['means'])
        c.check_shape_sources(root,binding)
        assert not list(root.rglob('*.pyc'))
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved);sys.path[:]=before


def test_bound_source_members_are_named_first_and_never_loaded_by_path(tmp_path,monkeypatch):
    import importlib.machinery as machinery
    d,_=fixture(tmp_path);root,binding=bundle(tmp_path,d);read=[];original=machinery.SourceFileLoader.get_data
    def recorded(loader,path):
        read.append(str(path));return original(loader,path)
    saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')}
    for name in saved:sys.modules.pop(name)
    monkeypatch.setattr(machinery.SourceFileLoader,'get_data',recorded)
    try:
        c.bind_shape_sources(root,binding)
        # The initializer's registry probe and every member import resolve inside the bound census.
        assert [p for p in read if p.startswith(str(root))]==[]
        assert sorted(n for n in sys.modules if n=='ravel' or n.startswith('ravel.'))==sorted(
            ['ravel','ravel.physics','ravel.workflow','ravel.workflow.state_io','ravel.physics.eft_functions',
             'ravel.physics.parametric_shapes','ravel.physics.continuous_dijet_shapes','ravel.physics.statistical_construction'])
        assert all(Path(sys.modules[n].__file__).is_relative_to(root) for n in sys.modules if n=='ravel' or n.startswith('ravel.'))
        assert not hasattr(sys.modules['ravel.workflow'],'role_registry') and not hasattr(sys.modules['ravel.workflow'],'host_governance')
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved)


def test_bound_source_refuses_a_member_import_outside_the_census(tmp_path):
    d,_=fixture(tmp_path);root,binding=bundle(tmp_path,d)
    path=root/'ravel_calibration_source/ravel/physics/__init__.py'
    path.write_text(path.read_text()+'\nfrom ravel.workflow import role_registry\n')
    binding['files']['physics/__init__.py']={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')}
    for name in saved:sys.modules.pop(name)
    try:
        with pytest.raises(ImportError,match='role_registry'):c.bind_shape_sources(root,binding)
        assert not [n for n in sys.modules if n=='ravel' or n.startswith('ravel.')]
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved)


@pytest.mark.parametrize('damage',['missing','extra','changed','symlink','wrong_size','foreign_import'])
def test_native_shape_source_refuses_unbound_members(tmp_path,damage):
    d,_=fixture(tmp_path);root,binding=bundle(tmp_path,d);path=root/'ravel_calibration_source/ravel/physics/parametric_shapes.py'
    if damage=='missing':binding['files'].pop('physics/parametric_shapes.py')
    elif damage=='extra':binding['files']['physics/arbitrary.py']=binding['files']['physics/parametric_shapes.py']
    elif damage=='changed':path.write_text(path.read_text()+'\n# source drift\n')
    elif damage=='symlink':saved=root/'original.py';path.rename(saved);path.symlink_to(saved)
    elif damage=='wrong_size':binding['files']['physics/parametric_shapes.py']['bytes']+=1
    with pytest.raises(ValueError):
        if damage=='foreign_import':c.bind_shape_sources(root,binding)
        else:c.check_shape_sources(root,binding,imported=False)


def test_ordinary_context_and_input_census_expose_shared_dependency(tmp_path):
    cp,cfg,d,q=configuration(tmp_path);task={'input':str(cp)}
    context=a.context(task,tmp_path)
    assert context['continuous_shapes']['terms']==c.shape_description(d)['terms']
    assert context['toys_generated']==context['fits_performed']==0 and not context['execution_authorized']
    assert all(p in a.inputs(task,tmp_path) for p in c.shape_source_paths(d))
    assert n.execution_seconds(task,tmp_path)==120
    assert 'not independent native' in context['continuous_shapes']['reference_dependency']


def test_serialized_worker_branch_is_explicit_bound_and_ending_checked():
    tree=ast.parse(n.NATIVE_PROBE)
    source=ast.unparse(tree)
    assert "bind_shape_sources(root, cfg['calibration_shape_sources'])" in source
    assert "check_shape_sources(root, cfg['calibration_shape_sources'])" in source
    assert "has_shapes != ('calibration_shape_sources' in cfg)" in source
    assert c.execute.__code__.co_names.count('_profile_fit')==1


def test_ordinary_native_body_stages_all_shape_sources_and_keeps_raw_rows(tmp_path,monkeypatch):
    from test_native_likelihood import VERSION_LOG
    cp,cfg,d,q=configuration(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0';cfg['calibration']=q;cp.write_text(json.dumps(cfg))
    out=tmp_path/'ordinary-native-attempt';commands=[]
    monkeypatch.setattr(n,'_check_probe',lambda *args:None);monkeypatch.setattr(n,'_check_workspace',lambda *args:[])
    def supplied(command,cwd,env,log,deadline,**kwargs):
        commands.append(list(command));log.parent.mkdir(parents=True,exist_ok=True)
        if '--help' in command:value='Explicit supplied help'
        elif len(command)==1:value=VERSION_LOG
        elif '-o' in command:Path(command[command.index('-o')+1]).write_bytes(b'FAKE workspace');value='Explicit supplied build'
        elif '--calibrate' in command:
            root=Path(command[2]).parent;staged=json.loads(Path(command[2]).read_bytes())
            c.check_shape_sources(root,staged['calibration_shape_sources'],imported=False)
            assert set(staged['calibration_shape_sources']['files'])==set(c.SHAPE_SOURCE_MEMBERS)
            facade,w,mc,data,_=fake(root,d)
            delivery=c.execute(facade,w,mc,data,r.response(d),staged['calibration'],e,root/'ravel_calibration_journal.json',float(command[-1]))
            assert delivery['continuous_shapes']==c.shape_description(d)
            value='RAVEL_NATIVE_PROBE='+json.dumps({'calibration':delivery})
        else:value='RAVEL_NATIVE_PROBE='+json.dumps({'identity':'explicit fake'})
        log.write_text(value+'\n');return value
    monkeypatch.setattr(n,'_process',supplied)
    result=a.run({'input':str(cp)},tmp_path,out)
    assert result['status']=='passed' and result['inference']['delivery']['top_level_profile_requests']==4
    assert len(commands)==6 and sum('--calibrate' in x for x in commands)==1
    assert result['inference']['delivery']['coverage_qualified'] is False
    assert all(row['observation']['counts'].keys()=={'SR','CR','MC'} for row in result['inference']['delivery']['rows'])
    assert (out/'native-calibration.json').exists()


def test_complete_correlated_shape_response_and_gaussian_truth(tmp_path):
    d,q=fixture(tmp_path)
    d['auxiliary'].update(names=['theta','other'],observed=['1/4','2'],factor=[['2','0'],['1','3']],eta_bounds=[['-3','3'],['-5','5']])
    for t in d['terms']:t['log_response']=[v+['0'] for v in t['log_response']]
    d['terms'][0]['shape']['slope_log_response']=['1/10','1/20']
    d['parameters'][-1]['bounds']=['-1/4','1/4']
    q['truths'][0]['point']['ravel_aux_1']='-1'
    r.validate(d);c.validate(q,d)
    point=q['truths'][0]['point'];means=c.means(d,point)
    effective=F('1/10')*F('5/4')+F('1/20')*F('-1/2')
    f=(math.exp(float(effective))-1)/math.expm1(4*float(effective))
    assert means['SR']==pytest.approx(50*math.exp(.125)*f+1.5)
    t=c.toy(q,d,q['truths'][0],0)
    assert set(t['globals'])=={'ravel_aux_0_In','ravel_aux_1_In'}
    assert t['physical_gaussian_measurement']['other']==pytest.approx(2+t['globals']['ravel_aux_0_In']+3*t['globals']['ravel_aux_1_In'])
    assert means['MC']==3


def test_shape_sampling_retains_existing_component_admission(tmp_path):
    d,q=fixture(tmp_path)
    d['terms'][-1]['shape']=deepcopy(d['terms'][0]['shape'])
    with pytest.raises(ValueError,match='nonnegative background'):c.validate(q,d)
    d,q=fixture(tmp_path);d['terms'][0]['coefficients'][0]='-1'
    with pytest.raises(ValueError,match='nonnegative background'):c.validate(q,d)


def test_unbound_loader_payload_is_refused_before_import(tmp_path):
    d,_=fixture(tmp_path);root,binding=bundle(tmp_path,d)
    package=root/'ravel_calibration_source/ravel/physics'
    (package/'parametric_shapes.so').write_bytes(b'Not a native library; never imported')
    with pytest.raises(ValueError,match='unbound shape source package member'):
        c.check_shape_sources(root,binding,imported=False)


def test_real_graph_host_and_public_unapproved_shape_plan(tmp_path):
    from ravel.workflow import agent_graph as g, science
    from ravel.workflow.agent_host import AgentHost
    from ravel import cli
    from test_science_capability_integration import specification
    cp,cfg,d,q=configuration(tmp_path);task={'input':str(cp)}
    tp=tmp_path/'task.json';tp.write_text(json.dumps(task));pin={'path':str(tp),'sha256':hashlib.sha256(tp.read_bytes()).hexdigest()}
    gs=a.graph(task,tmp_path,pin);rd=tmp_path/'context-graph';g.create(rd,gs)
    assert g.execute(rd,AgentHost(api_key='not-used'),workers=1)['complete']
    _,state=g._load(rd);value=g._result(rd,state['nodes']['context']['result'])['result']['value']
    assert value['continuous_shapes']['terms']==c.shape_description(d)['terms']
    assert not value['execution_authorized'] and value['fits_performed']==value['toys_generated']==0
    spec=specification('full-auxiliary-calibration',task);spec['max_seconds']=120
    sp=tmp_path/'study.json';sp.write_text(json.dumps(spec));study=tmp_path/'ordinary-study'
    assert cli.main(['plan','--rundir',str(study),'--spec',str(sp)])==0
    science.verify_plan(study,approved=False)
    assert not (study/science.APPROVAL).exists()
    plan=json.loads((study/science.PLAN).read_bytes())
    assert plan['max_seconds']==120


def test_ending_staged_source_drift_retains_all_failed_slots(tmp_path,monkeypatch):
    from test_native_likelihood import VERSION_LOG
    cp,cfg,d,q=configuration(tmp_path);out=tmp_path/'failed-ending-attempt'
    monkeypatch.setattr(n,'_check_probe',lambda *args:None);monkeypatch.setattr(n,'_check_workspace',lambda *args:[])
    def supplied(command,cwd,env,log,deadline,**kwargs):
        log.parent.mkdir(parents=True,exist_ok=True)
        if '--help' in command:value='Supplied help'
        elif len(command)==1:value=VERSION_LOG
        elif '-o' in command:Path(command[command.index('-o')+1]).write_bytes(b'FAKE workspace');value='Supplied build'
        elif '--calibrate' in command:
            root=Path(command[2]).parent;staged=json.loads(Path(command[2]).read_bytes())
            facade,w,mc,data,_=fake(root,d)
            delivery=c.execute(facade,w,mc,data,r.response(d),staged['calibration'],e,root/'ravel_calibration_journal.json',float(command[-1]))
            path=root/'ravel_calibration_source/ravel/physics/parametric_shapes.py';path.write_text(path.read_text()+'\n# supplied ending drift\n')
            value='RAVEL_NATIVE_PROBE='+json.dumps({'calibration':delivery})
        else:value='RAVEL_NATIVE_PROBE='+json.dumps({'identity':'explicit fake'})
        log.write_text(value+'\n');return value
    monkeypatch.setattr(n,'_process',supplied)
    result=a.run({'input':str(cp)},tmp_path,out)
    assert result['status']=='failed'
    audit=result['calibration_failure_audit']
    assert len(audit['rows'])==2 and all(row['status']=='unresolved' for row in audit['rows'])
    assert audit['scientific_reuse_authorized'] is False
    assert (out/'native-work/ravel_calibration_journal.json').exists()


def power_fixture(tmp_path, exponent='0', *, response=False):
    d,q=fixture(tmp_path,response=False)
    d['parameters'][-1].update(bounds=['-3','2'],initial='0',meaning='Artificial dimensionless power-law exponent')
    d['terms'][0]['shape']={'kind':'normalized_power','domain':['1','4'],'bin_windows':[['1','2'],['3','4'],None],'exponent_parameter':'slope','exponent_response':['1/10' if response else '0']}
    q['truths'][0]['point']['slope']=exponent
    r.validate(d);c.validate(q,d)
    return d,q


@pytest.mark.parametrize('exponent',['-1','0','1','-3','2'])
def test_power_source_mean_independent_physical_x_integral(tmp_path,exponent):
    d,q=power_fixture(tmp_path,exponent);p=float(F(exponent))
    def fraction(lo,hi):
        if p==-1:return math.log(hi/lo)/math.log(4)
        return (hi**(p+1)-lo**(p+1))/(4**(p+1)-1)
    got=c.means(d,q['truths'][0]['point'])
    assert got['SR']==pytest.approx(50*math.exp(.125)*fraction(1,2)+1.5,rel=2e-12)
    assert got['CR']==pytest.approx(50*math.exp(-.125)*fraction(3,4)+2.5,rel=2e-12)
    assert got['MC']==3
    assert fraction(1,2)+fraction(3,4)<1
    assert list(got.values())==pytest.approx(r.mean_jet(d,q['truths'][0]['point'])['means'])


def test_power_correlated_exponent_complete_truth_nll(tmp_path):
    d,q=power_fixture(tmp_path,'-1',response=True)
    point=q['truths'][0]['point'];got=c.means(d,point)
    effective=-1+.125
    frac=(2**(effective+1)-1)/(4**(effective+1)-1)
    assert got['SR']==pytest.approx(50*math.exp(.125)*frac+1.5)
    o=c.toy(q,d,q['truths'][0],0)
    direct=sum(v-o['counts'][b]*math.log(v)+math.lgamma(o['counts'][b]+1) for b,v in got.items())+.5*(.5-o['globals']['ravel_aux_0_In'])**2
    assert c.source_nll(d,point,o)==pytest.approx(direct)
    assert c.shape_description(d)['terms'][0]['shape']['kind']=='normalized_power'


@pytest.mark.parametrize('damage',[lambda d:d['terms'][0]['shape'].update(domain=['0','4']),lambda d:d['terms'][0]['shape'].update(exponent_response=['100']),lambda d:d['terms'][0]['shape'].update(kind='normalized_dijet')])
def test_power_bad_domain_and_unadmitted_family_refuse(tmp_path,damage):
    d,q=power_fixture(tmp_path);damage(d)
    with pytest.raises(ValueError):c.validate(q,d)


def test_loaded_source_uses_authenticated_buffer_not_second_path_read(tmp_path,monkeypatch):
    import builtins
    d,_=fixture(tmp_path);root,binding=bundle(tmp_path,d);saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')}
    path=root/'ravel_calibration_source/ravel/physics/parametric_shapes.py';original=path.read_bytes();old_compile=builtins.compile;observed=[]
    def hooked(raw,filename,mode,*args,**kwargs):
        if str(filename)==str(path) and mode=='exec':
            observed.append(hashlib.sha256(raw).hexdigest())
            path.write_bytes(b'raise RuntimeError("unadmitted transient source")\n')
            try:return old_compile(raw,filename,mode,*args,**kwargs)
            finally:path.write_bytes(original)
        return old_compile(raw,filename,mode,*args,**kwargs)
    for name in saved:sys.modules.pop(name)
    monkeypatch.setattr(builtins,'compile',hooked)
    try:
        c.bind_shape_sources(root,binding)
        assert observed==[binding['files']['physics/parametric_shapes.py']['sha256']]
        assert sys.modules['ravel.physics.parametric_shapes'].MAX_DIMENSIONLESS_SLOPE==50
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved)


def test_actual_serialized_calibration_branch_uses_staged_source_package(tmp_path,monkeypatch):
    d,q=power_fixture(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0'
    root,binding=bundle(tmp_path,d)
    for module,name,key in [(e,'ravel_regional_expected.py','calibration_optimizer_sha256'),(c,'ravel_regional_calibration.py','calibration_implementation_sha256')]:shutil.copyfile(module.__file__,root/name)
    cfg={'calibration':q,'max_seconds':120,'calibration_shape_sources':binding,'calibration_optimizer_sha256':hashlib.sha256((root/'ravel_regional_expected.py').read_bytes()).hexdigest(),'calibration_implementation_sha256':hashlib.sha256((root/'ravel_regional_calibration.py').read_bytes()).hexdigest()}
    facade,w,mc,data,calls=fake(root,d);result={}
    branch=next(node for node in ast.walk(ast.parse(n.NATIVE_PROBE)) if isinstance(node,ast.If) and "sys.argv[4] == '--calibrate'" in ast.unparse(node.test))
    tree=ast.fix_missing_locations(ast.Module(body=[branch],type_ignores=[]))
    namespace={'sys':sys,'__file__':str(root/'ravel_native_probe.py'),'cfg':cfg,'response':r.response(d),'ROOT':facade,'w':w,'mc':mc,'data':data,'result':result,'file_hash':lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()}
    saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')};old_argv=sys.argv
    for name in saved:sys.modules.pop(name)
    sys.argv=[namespace['__file__'],'workspace','configuration','response','--calibrate','10']
    try:
        exec(compile(tree,'actual-serialized-native-calibration-branch','exec'),namespace)
        assert result['calibration']['top_level_profile_requests']==4
        assert all(row['status']=='included' for row in result['calibration']['rows'])
        assert Path(sys.modules['ravel.physics.parametric_shapes'].__file__).is_relative_to(root)
        assert result['calibration']['coverage_qualified'] is False
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved);sys.argv=old_argv
    c.validate_delivery(result['calibration'],r.response(d),q,e)


def _inert_source_delivery(tmp_path, monkeypatch, *, after_worker=None, before_process=None):
    """Actual adapter with disclosed inert process/approval and ROOT facades.

    The three interface obligations were independently located by Measurement's
    V1 review (485a2fee); its original tests and failing results remain separate.
    """
    from test_native_likelihood import VERSION_LOG
    cp, cfg, d, q = configuration(tmp_path)
    q['truths'][0]['point']['ravel_aux_0'] = '0'
    cfg['calibration'] = q; cp.write_text(json.dumps(cfg))
    expected = n._configuration({'input':str(cp)}, tmp_path)[9]
    calls = []
    monkeypatch.setattr(n, '_check_probe', lambda *args: None)
    monkeypatch.setattr(n, '_check_workspace', lambda *args: [])
    def supplied(command, cwd, env, log, deadline, **kwargs):
        calls.append(list(command))
        if before_process: before_process()
        log.parent.mkdir(parents=True, exist_ok=True)
        if '--help' in command: value = 'Explicit inert supplied help'
        elif len(command) == 1: value = VERSION_LOG
        elif '-o' in command:
            Path(command[command.index('-o')+1]).write_bytes(b'Inert supplied workspace'); value = 'Inert build'
        elif '--calibrate' in command:
            root = Path(command[2]).parent; staged = json.loads(Path(command[2]).read_bytes())
            facade, w, mc, data, _ = fake(root, d)
            delivery = c.execute(facade, w, mc, data, r.response(d), staged['calibration'], e,
                root/'ravel_calibration_journal.json', float(command[-1]))
            c.check_shape_sources(root, staged['calibration_shape_sources'], imported=False)
            if after_worker: after_worker(root)
            value = 'RAVEL_NATIVE_PROBE='+json.dumps({'calibration':delivery})
        else: value = 'RAVEL_NATIVE_PROBE='+json.dumps({'identity':'explicit inert'})
        log.write_text(value+'\n'); return value
    monkeypatch.setattr(n, '_process', supplied)
    out = tmp_path/'inert-source-attempt'
    result = a.run({'input':str(cp)}, tmp_path, out)
    return result, expected, out, calls


def test_source_staging_retains_regional_identity_and_admitted_pins(tmp_path, monkeypatch):
    result, expected, out, calls = _inert_source_delivery(tmp_path, monkeypatch)
    assert result['status'] == 'passed' and result['response_binding'] == expected
    assert expected['kind'] == 'regional-poisson-construction/v1'
    work = out/'native-work'
    binding = json.loads((work/'ravel_native_configuration.json').read_bytes())['calibration_shape_sources']
    for name, source in zip(c.SHAPE_SOURCE_MEMBERS, c.shape_source_paths({'terms':[{'shape':{}}]})):
        original = source.read_bytes(); staged = (work/'ravel_calibration_source/ravel'/name).read_bytes()
        assert staged == original
        assert binding['files'][name] == {'sha256':result['original_input_hashes'][str(source)], 'bytes':len(original)}
    assert len(calls) == 6


@pytest.mark.parametrize('member', ['physics/unbound.py','workflow/unbound.sh','foreign'])
def test_host_closed_delivery_refuses_late_members_and_preserves_raw_journal(tmp_path, monkeypatch, member):
    active = []
    def add(root):
        target = root/'ravel_calibration_source/ravel'/member
        target.mkdir() if member == 'foreign' else target.write_text('# unbound late member\n')
        active.append(str(target))
    result, _, out, _ = _inert_source_delivery(tmp_path, monkeypatch, after_worker=add)
    assert active and result['status'] == 'failed'
    assert 'unbound shape source package member' in result['error']['message']
    assert not result['calibration_failure_audit']['scientific_reuse_authorized']
    assert (out/'native-work/ravel_calibration_journal.json').exists()


def _copied_shape_sources(tmp_path, monkeypatch):
    originals = c.shape_source_paths({'terms':[{'shape':{}}]})
    copies = []
    for name, source in zip(c.SHAPE_SOURCE_MEMBERS, originals):
        target = tmp_path/'source-copies'/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes()); copies.append(target)
    monkeypatch.setattr(c, 'shape_source_paths', lambda d: copies if any('shape' in t for t in d['terms']) else [])
    return copies


def test_removed_pathname_copy_hook_does_not_stage_unapproved_bytes(tmp_path, monkeypatch):
    copies = _copied_shape_sources(tmp_path, monkeypatch); target_source = copies[c.SHAPE_SOURCE_MEMBERS.index('physics/parametric_shapes.py')]
    original = shutil.copyfile; activated = []
    def old_hook(src, target, *args, **kwargs):
        if Path(src) == target_source:
            activated.append(str(src)); target_source.write_bytes(b'unapproved source')
        return original(src, target, *args, **kwargs)
    monkeypatch.setattr(shutil, 'copyfile', old_hook)
    result, _, out, _ = _inert_source_delivery(tmp_path, monkeypatch)
    assert not activated  # A removed hook is not counted as an active refusal.
    assert result['status'] == 'passed'
    staged = out/'native-work/ravel_calibration_source/ravel/physics/parametric_shapes.py'
    assert staged.read_bytes() == target_source.read_bytes()
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == result['original_input_hashes'][str(target_source)]


@pytest.mark.parametrize('damage', ['substituted_buffer','read_exception','nonregular_descriptor'])
def test_actual_admitted_capture_refuses_and_closes_descriptor(tmp_path, monkeypatch, damage):
    import os
    copies = _copied_shape_sources(tmp_path, monkeypatch); source = copies[c.SHAPE_SOURCE_MEMBERS.index('physics/parametric_shapes.py')]
    old_open, old_read, old_close = os.open, os.read, os.close
    observed = []; opened = []; closed = []; live = set()
    def opening(path, flags, *args, **kwargs):
        if Path(path) == source and flags & os.O_NONBLOCK:
            fd = old_open('/dev/null' if damage == 'nonregular_descriptor' else path, flags, *args, **kwargs)
            opened.append(fd); live.add(fd); observed.append(damage); return fd
        return old_open(path, flags, *args, **kwargs)
    def reading(fd, size):
        if fd in live:
            if damage == 'read_exception': raise OSError('injected capture read failure')
            if damage == 'substituted_buffer': return b'unapproved captured source buffer'
        return old_read(fd, size)
    def closing(fd):
        is_capture = fd in live
        result = old_close(fd)
        if is_capture:
            live.remove(fd); closed.append(fd)
            with pytest.raises(OSError): os.fstat(fd)
        return result
    monkeypatch.setattr(os, 'open', opening); monkeypatch.setattr(os, 'read', reading); monkeypatch.setattr(os, 'close', closing)
    result, _, _, calls = _inert_source_delivery(tmp_path, monkeypatch)
    assert observed and result['status'] == 'failed' and not calls
    assert closed == opened and not live and not result['calibration_failure_audit']['scientific_reuse_authorized']


def test_staged_write_substitution_refuses_original_commitment(tmp_path, monkeypatch):
    copies = _copied_shape_sources(tmp_path, monkeypatch); original = Path.write_bytes; active = []
    def changed(path, raw):
        if path.name == 'parametric_shapes.py' and 'ravel_calibration_source' in path.parts:
            active.append(hashlib.sha256(raw).hexdigest()); raw += b'\n# unapproved staged source\n'
        return original(path, raw)
    monkeypatch.setattr(Path, 'write_bytes', changed)
    result, _, out, calls = _inert_source_delivery(tmp_path, monkeypatch)
    assert active and result['status'] == 'failed' and not calls
    original_bytes = copies[c.SHAPE_SOURCE_MEMBERS.index('physics/parametric_shapes.py')].read_bytes()
    assert active == [hashlib.sha256(original_bytes).hexdigest()]
    assert (out/'native-work/ravel_calibration_source/ravel/physics/parametric_shapes.py').read_bytes() != original_bytes
    assert 'shape source is not its declared regular file' in result['error']['message']


def test_final_delivery_check_catches_member_added_during_retained_census(tmp_path, monkeypatch):
    original = n._hash; active = []
    def ending(path):
        path = Path(path)
        if path.name == 'native-calibration.json' and not active:
            package = path.parent/'native-work/ravel_calibration_source/ravel'
            if package.exists():
                target = package/'workflow/late.sh'; target.write_text('# late census addition\n'); active.append(str(target))
        return original(path)
    monkeypatch.setattr(n, '_hash', ending)
    result, _, out, _ = _inert_source_delivery(tmp_path, monkeypatch)
    assert active and result['status'] == 'failed'
    assert (out/'native-work/ravel_calibration_journal.json').exists()
    assert not result['calibration_failure_audit']['scientific_reuse_authorized']


@pytest.mark.parametrize('damage', ['added_file','added_directory','added_symlink','earlier_leaf','missing_leaf'])
def test_ending_namespace_after_last_descriptor_read(tmp_path, monkeypatch, damage):
    """Measurement's V2 late-read witness, plus adjacent ending census cases.

    The exact original independent witness stays outside this adapted matrix.
    All mutations are confined to fresh inert copied source packages.
    """
    import os
    check = c.check_shape_sources
    old_open, old_read, old_close = os.open, os.read, os.close
    phase = {'calls':0, 'final':False}; live = set(); active = []
    def checking(*args, **kwargs):
        phase['calls'] += 1; phase['final'] = phase['calls'] == 3
        try: return check(*args, **kwargs)
        finally: phase['final'] = False
    def opening(path, flags, *args, **kwargs):
        fd = old_open(path, flags, *args, **kwargs)
        if phase['final'] and Path(path).name == 'statistical_construction.py': live.add(fd)
        return fd
    def reading(fd, count):
        raw = old_read(fd, count)
        if fd in live and raw and not active:
            package = tmp_path/'inert-source-attempt/native-work/ravel_calibration_source/ravel'
            target = package/'physics/last-read-addition'
            if damage == 'added_file': target.with_suffix('.py').write_text('# late unbound file\n')
            elif damage == 'added_directory': target.mkdir()
            elif damage == 'added_symlink': target.symlink_to(package/'__init__.py')
            elif damage == 'earlier_leaf':
                earlier = package/'__init__.py'; earlier.write_bytes(earlier.read_bytes()+b'\n# late known-leaf drift\n')
            else: (package/'workflow/state_io.py').unlink()
            active.append(damage)
        return raw
    def closing(fd):
        live.discard(fd); return old_close(fd)
    monkeypatch.setattr(c,'check_shape_sources',checking)
    monkeypatch.setattr(os,'open',opening); monkeypatch.setattr(os,'read',reading); monkeypatch.setattr(os,'close',closing)
    result, _, out, _ = _inert_source_delivery(tmp_path, monkeypatch)
    assert active == [damage] and not live and phase['calls'] == 3
    assert result['status'] == 'failed'
    assert not result['calibration_failure_audit']['scientific_reuse_authorized']
    assert len(result['calibration_failure_audit']['rows']) == 2
    assert (out/'native-work/ravel_calibration_journal.json').exists()
