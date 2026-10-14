"""Proposed root-only controls for the three exact independent V1 findings."""
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from sfitter_complete_fixture import source,card,pin,workflow_request
from ravel.physics import sfitter_profiles as profiles,sfitter_compat as compat
from ravel.physics import sfitter_complete_worker as child,sfitter_complete_native as native

@pytest.mark.parametrize('phase',['run','fit','plot'])
def test_actual_documenter_lexical_path_binds_owned_run(tmp_path,phase):
    package=tmp_path/'sfitter';(package/'sfitter/util').mkdir(parents=True)
    name='20261009_120000_software';owned=package/'output'/name;owned.mkdir(parents=True)
    state=owned/'params.yaml';state.write_text('retained_'+phase)
    lexical=package/'sfitter/util/../../output'/name
    assert child.saved_directory(lexical,package)==owned
    assert child.saved_directory(owned,package)==owned
    assert state.read_text()=='retained_'+phase
    foreign=tmp_path/'foreign/output'/name;foreign.mkdir(parents=True)
    with pytest.raises(ValueError,match='escaped'):child.saved_directory(foreign,package)
    state.unlink();owned.rmdir();owned.symlink_to(foreign,target_is_directory=True)
    with pytest.raises(ValueError,match='alias'):child.saved_directory(lexical,package)

@pytest.mark.parametrize('algorithm',['smc','craft'])
@pytest.mark.parametrize('strategy',['histogram','annealing'])
@pytest.mark.parametrize('count',[1,2])
def test_exact_released_profile_branch_preserves_1d_and_complete_pair_population(tmp_path,algorithm,strategy,count):
    # CRAFT inherits this exact released SMC method. Extract only the reviewed
    # source definition; use recording facades, never import a native engine.
    root=source(tmp_path);raw=(root/compat.RELATIVE).read_bytes()
    derived=compat.projected_source(raw,hashlib.sha256(raw).hexdigest())
    tree=ast.parse(derived);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SMCFitter')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='profile')
    calls=[]
    # The exact extracted method evaluates list[np.ndarray] at definition.
    # object supplies its annotation namespace only; it is not a NumPy engine.
    np=SimpleNamespace(ndarray=object,linspace=lambda lo,hi,n,axis:(calls.append(('geometry',lo,hi,n,axis)) or [['native_edges']]))
    namespace={'np':np,'time':lambda:0,'timedelta':lambda **kw:'zero'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'source_bound_profile','exec'),namespace)
    facade=SimpleNamespace(likelihood=SimpleNamespace(dims_parameter=count),lower_bounds=[-1.]*count,upper_bounds=[1.]*count,
        profile_1d_params={'strategy':strategy},profile_2d_params={'strategy':strategy,'n_points':4},print=lambda message:None)
    for dimension in (1,2):
        for s in ('histogram','annealing'):
            setattr(facade,'profile_'+str(dimension)+'d_'+s,lambda d=dimension,s=s:(calls.append((d,s)) or ([d],[['native_'+str(d)+'_edges']])))
    one,bins_one,pairs,bins_pair=namespace['profile'](facade)
    assert one==[1] and bins_one==[['native_1_edges']] and calls[0]==(1,strategy)
    if count==1:
        assert pairs==[] and bins_pair==[['native_edges']]
        assert calls==[(1,strategy),('geometry',[-1.],[1.],5,1)]
    else:assert pairs==[2] and bins_pair==[['native_2_edges']] and calls==[(1,strategy),(2,strategy)]
    assert derived.replace(compat.AFTER.encode(),compat.BEFORE.encode()).replace(compat.PAIR_AFTER.encode(),compat.PAIR_BEFORE.encode())==raw
    assert (root/compat.RELATIVE).read_bytes()==raw

@pytest.mark.parametrize('profile',['top','higgs'])
@pytest.mark.parametrize('algorithm',['flow','smc','craft'])
def test_singleton_card_admission_keeps_declared_coordinate_settings(tmp_path,profile,algorithm):
    root=source(tmp_path);basis=profiles.basis(root,profile);selected=[basis[-1]]
    cp,rp,params,doc=card(tmp_path,root,profile,selected,algorithm)
    bound=profiles.compile_card(root,cp,rp,profile,selected,algorithm)
    assert bound['selection']['indices']==[len(basis)-1] and bound['params']==params
    assert bound['selection']['fixed_zero']==basis[:-1]
    if profile=='higgs' and algorithm=='flow':assert params['prescale']['std_init']==[.1]


def test_higgs_flow_start_scale_projection_retains_full_length_refusal(tmp_path):
    import yaml
    root=source(tmp_path);basis=profiles.basis(root,'higgs');selected=[basis[-1],basis[0]]
    cp,rp,params,doc=card(tmp_path,root,'higgs',selected)
    original=profiles.yaml_document((root/'sfitter/params/higgs_fit.yaml').read_text())
    assert params['prescale']['std_init']==[original['prescale']['std_init'][-1],original['prescale']['std_init'][0]]==[.1,10]
    params['prescale']['std_init']=original['prescale']['std_init'];rp.write_text(yaml.safe_dump(params))
    with pytest.raises(ValueError,match='coordinate'):profiles.compile_card(root,cp,rp,'higgs',selected,'flow')


def _large_settings(tmp_path,config):
    # Genuine complete tiny-file metadata, not duplicate or missing runtime leaves.
    # Long legal paths make >8MiB JSON without constructing native/model code.
    site=tmp_path/'large-site';site.mkdir();leaf=site
    for i in range(7):leaf/=str(i)+'x'*75;leaf.mkdir()
    assets=[]
    for i in range(12000):
        member=leaf/(str(i).zfill(5)+'y'*75+'.txt');member.write_bytes(b'not executable\n');assets.append(pin(member))
    value={key:copy.deepcopy(config[key]) for key in ('source','trusted_upstream_python','runtime','max_seconds','max_ram_mib','max_export_bytes')}
    value.update(schema_version=1);value['runtime'].update(site_roots=[str(site)],assets=assets)
    path=tmp_path/'settings.json';path.write_text(json.dumps(value,indent=2)+'\n')
    assert 8*1024**2<path.stat().st_size<64*1024**2 and len(assets)<64000
    return path,assets


def test_actual_schema2_materializer_retains_complete_transport_above_generic_8mib(tmp_path):
    from ravel.workflow import sfitter_workflow as w
    root=source(tmp_path);request,config=workflow_request(tmp_path,root,'higgs')
    settings,assets=_large_settings(tmp_path,config)
    request_path=tmp_path/'workflow.json';request_path.write_text(json.dumps(request)+'\n')
    result=w.materialize_datacard(request,tmp_path,tmp_path/'assembled',native_settings=pin(settings),request_pin=pin(request_path))
    path=Path(result['native_config']['path']);delivered=native._read(path,result['native_config']['sha256'])
    assert 8*1024**2<path.stat().st_size<=64*1024**2
    assert delivered['runtime']['assets']==assets and delivered['schema_version']==2
    assert result['native_calls_observed']==0 and result['execution_authorized'] is False
    from ravel.physics.ma5_saf import Capture
    with pytest.raises(ValueError):Capture().read(path,path.parent)

@pytest.mark.parametrize('mutation',['bytes','alias','replace'])
def test_schema2_generated_transport_ending_retains_original_custody(tmp_path,mutation):
    path=tmp_path/'transport.json';path.write_bytes(b'{"value":"'+b'a'*(8*1024**2)+b'"}')
    cap=native.transport_capture();cap.read(path,tmp_path)
    if mutation=='bytes':path.write_bytes(b'{"value":"changed"}')
    elif mutation=='alias':
        target=tmp_path/'foreign.json';target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
    else:
        saved=path.read_bytes();path.unlink();path.write_bytes(saved)
    with pytest.raises((ValueError,OSError)):cap.finish()


def test_schema2_transport_refuses_more_than_declared64mib(tmp_path):
    path=tmp_path/'too-large.json'
    with path.open('wb') as stream:stream.truncate(64*1024**2+1)
    with pytest.raises(ValueError,match='bounded'):native.transport_capture().read(path,tmp_path)
