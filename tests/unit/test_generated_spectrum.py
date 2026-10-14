"""Portable generated-spectrum controls; no compiler/solver/model/provider calls."""
import hashlib
import os
from pathlib import Path
import stat
import pytest
from ravel.physics import generated_spectrum as bridge
from ravel.physics import model_sources, model_tool_bridge as custody

def pin(p):return {'path':str(p),'sha256':custody._hash(p)}

def bundle(root,kind,files,modes=None):
    root.mkdir();original=root/'original';original.mkdir();paths={}
    for name,raw in files.items():
        p=original/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);paths[name]=p
    modes={name:(modes or {}).get(name,0o644) for name in files}
    archive=root/'source-assets.zip';model_sources._write_bundle(archive,paths,modes)
    doc={'schema_version':2,'source_contract_sha256':'a'*64,'source_configuration_sha256':'b'*64,
        'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},'modes':modes,
        'bundle':{'format':model_sources.BUNDLE_FORMAT,'path':archive.name,'sha256':custody._hash(archive),'bytes':archive.stat().st_size},
        'baseline_kind':kind,'provider_status':{'configured':False},
        'scope':'Synthetic portable fixture; no scientific source/runtime qualification.'}
    manifest=root/'source-capsule.json';custody._write(manifest,doc);return pin(manifest)

@pytest.fixture
def config(tmp_path):
    source={'cmssm/configure':b'#!/bin/sh\nFLEXIBLESUSY_MAJOR=2\nFLEXIBLESUSY_MINOR=9\nFLEXIBLESUSY_PATCH=0\n',
        'cmssm/models/CMSSM/LesHouches.in.CMSSM':b'Block MINPAR\n1 125\n2 500\n',
        'cmssm/models/CMSSM/module.mk':b'Synthetic module\n',
        'cmssm/models/CMSSM/CMSSM_two_scale_spectrum_generator.cpp':b'Synthetic generated source\n',
        'cmssm/doc/observables/lepton_physics.rst':b''}
    boost={'include/boost/version.hpp':b'#define BOOST_VERSION 108500\n'}
    eigen={'include/eigen3/Eigen/Core':b'Synthetic core\n',
        'include/eigen3/Eigen/src/Core/util/Macros.h':b'#define EIGEN_WORLD_VERSION 3\n#define EIGEN_MAJOR_VERSION 4\n#define EIGEN_MINOR_VERSION 0\n',
        'include/eigen3/unsupported/Eigen/MatrixFunctions':b'Synthetic math\n',
        'include/eigen3/unsupported/Eigen/CXX11/Tensor':b'Synthetic tensor\n'}
    tools={}
    for role,name in [('cc','clang-22'),('cxx','clang-22'),('fc','gfortran'),('make','make'),('gsl_config','gsl-config')]:
        p=tmp_path/name
        if not p.exists():p.write_bytes(b'Synthetic tool; never executed\n');p.chmod(0o700)
        tools[role]=pin(p)
    runtime=tmp_path/'runtime-support';runtime.write_bytes(b'Synthetic support\n')
    c={'schema_version':1,'operation':'flexiblesusy-2.9.0-generated-CMSSM','source':'Synthetic fixture',
        'trusted_generated_source':True,
        'source_capsule':bundle(tmp_path/'source','pregenerated-spectrum',source,{'cmssm/configure':0o755}),
        'boost_capsule':bundle(tmp_path/'boost','supplied-build-headers',boost),
        'eigen_capsule':bundle(tmp_path/'eigen','supplied-build-headers',eigen),
        'tools':tools,'runtime_inputs':[pin(runtime)],'max_ram_mib':4096}
    path=tmp_path/'config.json';custody._write(path,c);return c,path

@pytest.mark.parametrize('field,value',[
    ('schema_version',True),('operation','SARAH'),('trusted_generated_source',False),('source',''),
    ('runtime_inputs',[]),('max_ram_mib',True),('max_ram_mib',1023),('max_ram_mib',4097)])
def test_contract_refuses_unbounded_or_untrusted(config,field,value):
    c,_=config;c[field]=value
    with pytest.raises(ValueError):bridge.validate_config(c)

def test_archive_and_tool_bytes_are_inputs(config):
    c,path=config;rows=bridge.inputs({'config':str(path)},path.parent)
    assert path in rows
    for key in ('source_capsule','boost_capsule','eigen_capsule'):
        manifest=Path(c[key]['path']);assert manifest in rows and manifest.parent/'source-assets.zip' in rows
    assert Path(c['runtime_inputs'][0]['path']) in rows

@pytest.mark.parametrize('key,member,raw',[
    ('source_capsule','cmssm/configure',b'FLEXIBLESUSY_MAJOR=3\nFLEXIBLESUSY_MINOR=9\nFLEXIBLESUSY_PATCH=0\n'),
    ('boost_capsule','include/boost/version.hpp',b'#define BOOST_VERSION 108400\n'),
    ('eigen_capsule','include/eigen3/Eigen/src/Core/util/Macros.h',b'#define EIGEN_WORLD_VERSION 3\n#define EIGEN_MAJOR_VERSION 3\n#define EIGEN_MINOR_VERSION 0\n')])
def test_labels_cannot_replace_actual_version_tokens(config,tmp_path,key,member,raw):
    c,path=config;manifest=Path(c[key]['path']);doc=custody._read(manifest)
    files={name:(manifest.parent/'original'/name).read_bytes() for name in doc['files']};files[member]=raw
    c[key]=bundle(tmp_path/'changed',doc['baseline_kind'],files,doc['modes']);custody._write(path,c)
    with pytest.raises(ValueError):bridge.inputs({'config':str(path)},path.parent)

@pytest.mark.parametrize('name',['cmssm/libold.a','cmssm/old.o','cmssm/models/CMSSM/run_CMSSM.x','cmssm/Makefile','cmssm/config.status'])
def test_prebuilt_or_partial_main_state_refused(config,tmp_path,name):
    c,path=config;manifest=Path(c['source_capsule']['path']);doc=custody._read(manifest)
    files={n:(manifest.parent/'original'/n).read_bytes() for n in doc['files']};files[name]=b'prebuilt fixture'
    c['source_capsule']=bundle(tmp_path/'partial',doc['baseline_kind'],files,doc['modes']);custody._write(path,c)
    with pytest.raises(ValueError,match='prebuilt/partial/configured'):bridge.inputs({'config':str(path)},path.parent)

def test_complete_source_restore_preserves_empty_member_and_mode(config,tmp_path):
    c,_=config;out=tmp_path/'restored';result=model_sources.restore_source_bundle(c['source_capsule'],tmp_path,out)
    assert (out/'cmssm/doc/observables/lepton_physics.rst').read_bytes()==b''
    assert result['empty_members']==['cmssm/doc/observables/lepton_physics.rst']
    assert stat.S_IMODE((out/'cmssm/configure').stat().st_mode)==0o755
    assert result['native_calls']==0 and result['approval_inherited'] is False

def test_fixed_commands_original_input_and_one_job(config,tmp_path):
    c,path=config;commands,_=bridge.commands(c,path.parent,tmp_path/'work',tmp_path/'out')
    assert '--with-cxx='+str(tmp_path/'work/cxx-driver') in commands['configure']
    assert all(flag in commands['configure'] for flag in ('--disable-meta','--disable-librarylink','--disable-threads'))
    assert commands['compile']==[c['tools']['make']['path'],'-j1',bridge.TARGET]
    assert commands['solver'][1]=='--slha-input-file='+str(tmp_path/'work/source/cmssm'/bridge.INPUT)
    assert not any('force' in token for command in commands.values() for token in command)

def test_cxx_driver_exact_argv0_without_alias_lookup(config,monkeypatch):
    c,_=config;calls=[]
    monkeypatch.setattr(os,'execv',lambda exe,argv:calls.append((exe,argv)))
    monkeypatch.setattr(bridge.sys,'argv',['wrapper','-O2','file with space.cc'])
    exec(bridge.cxx_driver(Path(c['tools']['cxx']['path'])),{})
    expected=str(Path(c['tools']['cxx']['path']).with_name('clang++-22'))
    assert calls==[(c['tools']['cxx']['path'],[expected,'-O2','file with space.cc'])]

def test_launcher_refuses_ambient_compiler_override(monkeypatch,tmp_path):
    calls=[];monkeypatch.setattr(os,'execv',lambda exe,argv:calls.append((exe,argv)))
    monkeypatch.setattr(os,'chdir',lambda cwd:None)
    for key in bridge.BUILD_ENVIRONMENT:monkeypatch.setenv(key,'unadmitted injection')
    command=['/bound/executable','space and quote" literal']
    exec(bridge.launcher(command,tmp_path,'/bound/cc'),{})
    assert calls==[(command[0],command)] and os.environ['CC']=='/bound/cc'
    assert all(key not in os.environ for key in bridge.BUILD_ENVIRONMENT if key!='CC')
    assert os.environ['OMP_NUM_THREADS']=='1' and os.environ['LC_ALL']=='C'

SLHA=b'Block SPINFO\n 3 retained warning\n 4 retained error\nBlock MASS\n 1000022 -100.0\nDECAY 1000022 1.0e-12\n 0.2 2 22 12\nBlock DCINFO\n 3 omitted below cutoff\n'

def test_signed_mass_info_flags_and_unknown_channels_are_not_validity():
    diagnosis=bridge.diagnose_slha(SLHA,'literal solver fixture')
    assert diagnosis['source_sha256']==hashlib.sha256(SLHA).hexdigest()
    assert diagnosis['physics_validated'] is False and diagnosis['channel_completeness_declared'] is False
    assert len(diagnosis['all_info_rows'])==3
    assert diagnosis['static_inventory']['masses'][0]['sign_interpretation']=='preserved_uninterpreted'
    assert diagnosis['static_inventory']['decays'][0]['channel_completeness'].startswith('unresolved')

@pytest.mark.parametrize('raw',[b'Block MASS\n1000022 nan\n',b'\xffraw failure bytes'])
def test_malformed_output_is_retained_as_static_refusal(raw):
    result=bridge.diagnose_slha(raw,'solver fixture')
    assert result['static_disposition']=='static_parser_refusal' and result['static_inventory'] is None
    assert result['source_sha256']==hashlib.sha256(raw).hexdigest() and result['physics_validated'] is False

def test_no_approval_refuses_before_config_or_native(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db,'execute_native',lambda *a,**k:pytest.fail('unapproved scientific call'))
    out=tmp_path/'out'
    with pytest.raises(ValueError,match='approved supervised worker'):bridge.run({'config':'absent'},tmp_path,out)
    assert not out.exists()

def test_synthetic_transport_real_restoration_and_strict_output_snapshot(config,tmp_path,monkeypatch):
    """Actual ZIP/output admission; explicitly synthetic compiler and solver return."""
    from ravel.physics import reinterpret_db
    from ravel.workflow import execution
    c,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *a:root);calls=[]
    def fake(command,phase_out,resources):
        phase=phase_out.name;calls.append((phase,resources))
        if phase=='compile':
            binary=root/'work/generated-spectrum/attempt-1/source/cmssm'/bridge.TARGET
            binary.parent.mkdir(parents=True,exist_ok=True);binary.write_bytes(b'synthetic target, never executed');binary.chmod(0o700)
        if phase=='solver':(out/'CMSSM.slha').write_bytes(SLHA)
        custody._write(phase_out/'native-execution.json',{'synthetic':True,'returncode':0})
        return {'synthetic':True,'returncode':0,'resource_violation':None}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    before={str(p):custody._hash(p) for p in bridge.inputs({'config':str(path)},path.parent)}
    result=bridge.run({'config':str(path)},path.parent,out)
    assert [p for p,_ in calls]==['configure','compile','solver']
    assert [r['max_seconds'] for _,r in calls]==[120,1200,60]
    assert before=={str(p):custody._hash(p) for p in bridge.inputs({'config':str(path)},path.parent)}
    assert result['compiler_jobs']==1 and result['physics_validated'] is False
    assert result['generated_slha']['sha256']==hashlib.sha256(SLHA).hexdigest()
    retained=out/'run_CMSSM.x'
    assert result['compiled_target']['path']==str(retained)
    assert result['compiled_target']['sha256']==hashlib.sha256(retained.read_bytes()).hexdigest()
    assert result['compiled_target_stable_after_solver'] is True
    session=execution._validation_session(root)
    snapshot=session.snapshot([str(out)],outputs=True);session.finish()
    assert snapshot[str(out)]['kind']=='directory'
    assert any(row['name']=='run_CMSSM.x' for row in snapshot[str(out)]['files'])
    assert not any(row['size']==0 for row in snapshot[str(out)]['files'])

@pytest.mark.parametrize('when',['configure','compile','solver'])
def test_phase_failure_never_claims_delivered(config,tmp_path,monkeypatch,when):
    from ravel.physics import reinterpret_db
    c,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *a:root);calls=[]
    def fake(command,phase_out,resources):
        calls.append(phase_out.name)
        if phase_out.name==when:raise RuntimeError('retained synthetic native failure')
        if phase_out.name=='compile':
            p=root/'work/generated-spectrum/attempt-1/source/cmssm'/bridge.TARGET
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic target');p.chmod(0o700)
        return {'synthetic':True,'returncode':0}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    with pytest.raises(RuntimeError,match='retained synthetic'):bridge.run({'config':str(path)},path.parent,out)
    assert calls[-1]==when and not (out/'generated-spectrum.json').exists()

def test_import_origin_private():
    assert Path(bridge.__file__).resolve().parent == Path(custody.__file__).resolve().parent
    assert Path(bridge.__file__).resolve().parent == Path(model_sources.__file__).resolve().parent

def test_exhausted_stage_budget_refuses_before_first_native_phase(config,tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    c,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *a:root)
    clock=iter((0,bridge.STAGE_SECONDS+1));monkeypatch.setattr(bridge.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(reinterpret_db,'execute_native',lambda *a,**k:pytest.fail('native phase after exhausted budget'))
    with pytest.raises(ValueError,match='budget exhausted before configure'):
        bridge.run({'config':str(path)},path.parent,out)
    assert not (out/'generated-spectrum.json').exists()

def test_changed_declared_runtime_refuses_completed_handoff(config,tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    c,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *a:root)
    def fake(command,phase_out,resources):
        if phase_out.name=='compile':
            p=root/'work/generated-spectrum/attempt-1/source/cmssm'/bridge.TARGET
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic target');p.chmod(0o700)
        if phase_out.name=='solver':
            (out/'CMSSM.slha').write_bytes(SLHA)
            Path(c['runtime_inputs'][0]['path']).write_bytes(b'changed runtime bytes')
        return {'synthetic':True,'returncode':0}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    with pytest.raises(ValueError,match='source pin changed'):
        bridge.run({'config':str(path)},path.parent,out)
    assert not (out/'generated-spectrum.json').exists()

@pytest.mark.parametrize('change',['original_source','header_addition','retained_target','target_mode'])
def test_phase_custody_refuses_consumption_or_stale_executable(config,tmp_path,monkeypatch,change):
    from ravel.physics import reinterpret_db
    c,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *a:root);calls=[]
    work=root/'work/generated-spectrum/attempt-1'
    def fake(command,phase_out,resources):
        phase=phase_out.name;calls.append(phase)
        if phase=='configure' and change=='original_source':
            (work/'source/cmssm/configure').write_bytes(b'changed original source')
        if phase=='configure' and change=='header_addition':
            (work/'boost/include/boost/new.hpp').write_bytes(b'undeclared header')
        if phase=='compile':
            p=work/'source/cmssm'/bridge.TARGET
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic target');p.chmod(0o700)
        if phase=='solver':
            (out/'CMSSM.slha').write_bytes(SLHA)
            if change=='retained_target':(out/'run_CMSSM.x').write_bytes(b'changed retained executable')
            if change=='target_mode':(work/'source/cmssm'/bridge.TARGET).chmod(0o755)
        return {'synthetic':True,'returncode':0,'resource_violation':None}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    with pytest.raises(ValueError):bridge.run({'config':str(path)},path.parent,out)
    assert calls==(['configure'] if change in ('original_source','header_addition') else ['configure','compile','solver'])
    assert not (out/'generated-spectrum.json').exists()

def test_common_worker_accepts_transport_postconditions_and_strict_output(config,tmp_path,monkeypatch):
    """Common worker/snapshot API with explicitly synthetic admission/native phases."""
    from ravel.physics import science_worker, reinterpret_db
    from ravel.workflow import execution
    from ravel.plotting import science_figures
    c,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    task={'config':str(path)}
    spec={'schema_version':2,'mode':'generated-spectrum','task':task,'assumptions':['Synthetic portable fixture, no scientific approval or qualification.']}
    proposal={'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}}
    monkeypatch.setattr(science_worker,'verify_worker',lambda *a:proposal)
    monkeypatch.setattr(science_worker,'execution_spec',lambda *a:spec)
    monkeypatch.setattr(bridge,'_approved',lambda *a:root)
    monkeypatch.setattr(science_figures,'render',lambda *a:{'status':'not_applicable','figures':[],'tables':[]})
    def fake(command,phase_out,resources):
        if phase_out.name=='compile':
            p=root/'work/generated-spectrum/attempt-1/source/cmssm'/bridge.TARGET
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic target');p.chmod(0o700)
        if phase_out.name=='solver':(out/'CMSSM.slha').write_bytes(SLHA)
        return {'synthetic':True,'returncode':0,'resource_violation':None}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    assert science_worker.main([str(root)])==0
    result=custody._read(out/'result.json');verification=custody._read(out/'verification.json')
    assert result['status']=='passed' and result['physics_validated'] is False
    assert verification['passed'] is True and verification['result_sha256']==custody._hash(out/'result.json')
    session=execution._validation_session(root)
    snapshot=session.snapshot([str(out)],outputs=True);session.finish()
    assert snapshot[str(out)]['kind']=='directory'


@pytest.mark.parametrize('damage',['mode','symlink','delete','directory'])
def test_fixed_generated_driver_damage_refused_before_compile(config,tmp_path,monkeypatch,damage):
    from ravel.physics import reinterpret_db
    _,path=config;root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *args:root)
    calls=[]
    def synthetic_native(command,phase_out,resources):
        calls.append(phase_out.name)
        driver=root/'work/generated-spectrum/attempt-1/cxx-driver'
        if phase_out.name=='configure':
            if damage=='mode':driver.chmod(0o755)
            elif damage=='symlink':
                ordinary=driver.with_name('changed-driver-alias-target');ordinary.write_bytes(driver.read_bytes());ordinary.chmod(0o700)
                driver.unlink();driver.symlink_to(ordinary)
            elif damage=='delete':driver.unlink()
            elif damage=='directory':driver.unlink();driver.mkdir()
        return {'synthetic':True,'returncode':0,'resource_violation':None}
    monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_native)
    with pytest.raises(ValueError):bridge.run({'config':str(path)},path.parent,out)
    assert calls==['configure']
    assert not (out/'generated-spectrum.json').exists()
