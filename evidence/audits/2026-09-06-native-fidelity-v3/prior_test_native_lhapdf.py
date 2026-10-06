"""Inert metadata, activation and MG fixtures; no external tool is executed."""
import copy
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import native_lhapdf as link
from ravel.physics import native_pipeline as p
from test_native_dispatch import configuration, approve_fixture


def file(path, content='inert fixture\n', executable=False):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
    if executable:path.chmod(0o755)
    return path


@pytest.fixture
def fixture(tmp_path):
    build=tmp_path/'build';prefix=build/'tools/miniforge3/envs/mg5'
    for name in ('python','lhapdf-config','gfortran','clang','make','ar'):file(prefix/'bin'/name,executable=True)
    file(prefix/'lib/libLHAPDF.dylib');file(prefix/'etc/conda/activate.d/compiler.sh')
    sdk=tmp_path/'SDK';file(sdk/'SDKSettings.json','{"version":"fixture"}')
    data=prefix/'share/LHAPDF';pdf=data/link.PDF_SET
    file(data/'pdfsets.index','260000 NNPDF30_nlo_as_0118 2\n');file(data/'lhapdf.conf','Verbosity: 1\n')
    file(pdf/(link.PDF_SET+'.info'),'SetIndex: 260000\nFormat: lhagrid1\nNumMembers: 101\nDataVersion: 2\n')
    for i in range(101):file(pdf/f'{link.PDF_SET}_{i:04d}.dat',f'PDF member {i}\n')
    mg=file(build/'tools/mg5amcnlo/bin/mg5_aMC',executable=True)
    file(mg.parent.parent/'input/mg5_configuration.txt',f'lhapdf_py3 = {prefix}/bin/lhapdf-config\nauto_update = 0\nrun_mode = 0\nfortran_compiler = gfortran\n')
    home=tmp_path/'home';home.mkdir()
    env={'PATH':str(prefix/'bin'),'HOME':str(home),'CONDA_PREFIX':str(prefix),'LDFLAGS':f'-Wl,-rpath,{prefix}/lib -L{prefix}/lib','SDKROOT':str(sdk),'PYTHONDONTWRITEBYTECODE':'1'}
    obs={'--prefix':str(prefix),'--libdir':str(prefix/'lib'),'--datadir':str(data),'lipo':'arm64 x86_64','otool':'library:\n\t@rpath/libc++.1.dylib (compatibility version 1)','sysctl':'0'}
    calls=[]
    def probe(cmd):
        cmd=list(map(str,cmd));calls.append(cmd)
        return obs[cmd[-1] if cmd[0].endswith('lhapdf-config') else cmd[0]]
    def capture():return link.generation_decision(prefix,environment=env,run=probe,system='Darwin',architecture='arm64',python_executable=prefix/'bin/python')
    return SimpleNamespace(build=build,prefix=prefix,env=env,obs=obs,probe=probe,capture=capture,calls=calls,pdf=pdf,data=data,mg=mg)


def test_exact_capture_and_planner_revalidation_without_probes(fixture):
    effective,d=fixture.capture()
    assert effective==dict(fixture.env,LDFLAGS=fixture.env['LDFLAGS']+' -lc++')
    assert d['pdf']['lhaid']==260000 and d['pdf']['used_members']==[0]
    assert len([x for x in d['sources'] if x.startswith('pdf_member_')])==101
    before=list(fixture.calls);assert link.validate_generation_decision(d,fixture.prefix)==d
    assert before==fixture.calls
    assert all(c[0] in ('lipo','otool','sysctl') or c[0].endswith('lhapdf-config') for c in before)


def test_repeated_identical_configuration_has_one_pinned_effective_value(fixture):
    path = fixture.mg.parent.parent/'input/mg5_configuration.txt'
    line = 'mg5_path = '+str(fixture.mg.parent.parent)+'\n'
    path.write_text(path.read_text()+line*3)
    _, decision = fixture.capture()
    assert decision['madgraph_selection']['effective_options']['mg5_path'] == str(fixture.mg.parent.parent)
    assert link.validate_generation_decision(decision, fixture.prefix) == decision
    path.write_text(path.read_text()+line)
    with pytest.raises(ValueError):
        link.validate_generation_decision(decision, fixture.prefix)


@pytest.mark.parametrize('key', ['mg5_path', 'lhapdf_py3', 'auto_update', 'run_mode'])
def test_conflicting_repeated_configuration_still_fails(fixture, key):
    path = fixture.mg.parent.parent/'input/mg5_configuration.txt'
    path.write_text(path.read_text()+f'{key} = first\n{key} = second\n')
    with pytest.raises(ValueError, match='Conflicting'):
        fixture.capture()


@pytest.mark.parametrize('case',['missing_member','extra_member','wrong_index','duplicate_index','wrong_info','duplicate_info','wrong_lookup','multiple_lookup','relative_lookup','missing_hook','foreign_python','relative_flags','wrong_config','auto_update','cluster','unknown_env','bytecode','compiler_command','missing_compiler','compiler_link','home','default_outside'])
def test_invalid_source_or_context_rejected(fixture,tmp_path,case):
    f=fixture
    if case=='missing_member':(f.pdf/(link.PDF_SET+'_0050.dat')).unlink()
    elif case=='extra_member':file(f.pdf/'unknown.dat')
    elif case=='wrong_index':file(f.data/'pdfsets.index','260000 OTHER 2\n')
    elif case=='duplicate_index':file(f.data/'pdfsets.index','260000 NNPDF30_nlo_as_0118 2\n'*2)
    elif case=='wrong_info':file(f.pdf/(link.PDF_SET+'.info'),'Format: unknown\n')
    elif case=='duplicate_info':
        path=f.pdf/(link.PDF_SET+'.info');path.write_text(path.read_text()+'DataVersion: 2\n')
    elif case=='wrong_lookup':f.env['LHAPDF_DATA_PATH']=str(tmp_path)
    elif case=='multiple_lookup':f.env['LHAPDF_DATA_PATH']=str(f.data)+':'+str(tmp_path)
    elif case=='relative_lookup':f.env['LHAPDF_DATA_PATH']='relative'
    elif case=='missing_hook':(f.prefix/'etc/conda/activate.d/compiler.sh').unlink()
    elif case=='foreign_python':
        target=file(tmp_path/'external-python',executable=True);(f.prefix/'bin/python').unlink();(f.prefix/'bin/python').symlink_to(target)
    elif case=='relative_flags':f.env['LDFLAGS']='-Lrelative'
    elif case=='wrong_config':file(f.mg.parent.parent/'input/mg5_configuration.txt','lhapdf_py3 = wrong\n')
    elif case in ('auto_update','cluster'):
        path=f.mg.parent.parent/'input/mg5_configuration.txt';old,new=('auto_update = 0','auto_update = 7') if case=='auto_update' else ('run_mode = 0','run_mode = 1');path.write_text(path.read_text().replace(old,new))
    elif case=='unknown_env':f.env['MADGRAPH_BASE']=str(tmp_path)
    elif case=='bytecode':f.env.pop('PYTHONDONTWRITEBYTECODE')
    elif case=='compiler_command':f.env['FC']='gfortran -custom'
    elif case=='missing_compiler':(f.prefix/'bin/gfortran').unlink()
    elif case=='compiler_link':f.env['FFLAGS']='-lstdc++'
    elif case=='home':f.env['HOME']='relative'
    elif case=='default_outside':f.obs['--datadir']=str(tmp_path);f.env['LHAPDF_DATA_PATH']=str(f.data)
    with pytest.raises((ValueError,OSError)):f.capture()


@pytest.mark.parametrize('case',['hook','user_config','pdf'])
def test_existing_decision_detects_later_source_addition_or_drift(fixture,case):
    _,d=fixture.capture()
    if case=='hook':file(fixture.prefix/'etc/conda/activate.d/compiler.sh','changed')
    elif case=='user_config':file(Path(fixture.env['HOME'])/'.mg5/mg5_configuration.txt','cpp_compiler = clang\n')
    else:file(fixture.pdf/(link.PDF_SET+'_0000.dat'),'changed PDF')
    with pytest.raises(ValueError):link.validate_generation_decision(d,fixture.prefix)


@pytest.mark.parametrize('field',['pdf','sources','environment','link','compiler_paths','madgraph_selection'])
def test_malformed_sections_rejected(fixture,field):
    _,d=fixture.capture();d[field]=None
    with pytest.raises(ValueError):link.validate_generation_decision(d,fixture.prefix)


@pytest.mark.parametrize('case',['unknown_top','bool_version','bool_member','missing_env','unknown_env','omit_source','swap_compiler','link_runtime'])
def test_record_contradictions_rejected(fixture,case):
    _,d=fixture.capture()
    if case=='unknown_top':d['override']=True
    elif case=='bool_version':d['schema_version']=True
    elif case=='bool_member':d['pdf']['used_members']=[False]
    elif case=='missing_env':del d['environment']['HOME']
    elif case=='unknown_env':d['environment']['ARBITRARY']='x'
    elif case=='omit_source':del d['sources']['pdf_member_0010']
    elif case=='swap_compiler':d['compiler_paths']['default_cpp']=str(fixture.prefix/'bin/gfortran')
    elif case=='link_runtime':d['link']['runtime']='stdc++'
    with pytest.raises(ValueError):link.validate_generation_decision(d,fixture.prefix)


def planned(tmp_path,monkeypatch,f,*,opt=True):
    root=tmp_path/'run';root.mkdir();config=configuration(root)
    monkeypatch.setattr(p,'native_build_root',lambda:f.build)
    if opt:
        _,decision=f.capture();(root/'decision.json').write_text(json.dumps(decision))
        config.write_text(config.read_text().replace('[ravel.native.inputs]','lhapdf_linker = "preserve-activated-v1"\n[ravel.native.inputs]\nlhapdf_link_decision = "decision.json"'))
        card=root/'cards/run.dat';card.write_text(card.read_text().replace("'cteq6l1'","'lhapdf'")+'260000 = lhaid\n')
    return p.build_execution_plan(root,config),root,config


def test_opt_in_commands_outputs_dependencies(tmp_path,monkeypatch,fixture):
    plan,root,_=planned(tmp_path,monkeypatch,fixture);c=plan['generation_linker'];cmd=plan['generator_command']
    assert cmd[:6]==[str(fixture.build/'tools/miniforge3/bin/conda'),'run','--live-stream','-p',str(fixture.prefix),str(fixture.prefix/'bin/python')]
    assert cmd[6]=='-B' and cmd[-3:]==['generate-activated','--plan',str(root/'inputs/native_execution_plan.json')]
    assert c['payload_command']==[str(fixture.prefix/'bin/python'),'-O','-B',str(fixture.mg),'-s',str(root/'output/run.mg5')]
    stage=next(s for s in plan['stages'] if s['stage']=='madgraph')
    assert len(stage['outputs'])==2 and c['execution_record'] in stage['outputs']
    for item in link.read_decision(root/'decision.json')['sources'].values():assert item['path'] in stage['inputs']
    assert p.checked_linker(plan)[0]==c and not (root/'output').exists()


def test_default_generator_literal_unchanged(tmp_path,monkeypatch,fixture):
    plan,root,_=planned(tmp_path,monkeypatch,fixture,opt=False)
    assert 'generation_linker' not in plan
    assert plan['generator_command']==[str(fixture.build/'tools/miniforge3/bin/conda'),'run','--live-stream','-p',str(fixture.prefix),str(fixture.mg),str(root/'output/run.mg5')]
    assert len(next(s for s in plan['stages'] if s['stage']=='madgraph')['outputs'])==1


@pytest.mark.parametrize('case',['missing_decision','missing_policy','wrong_policy','wrong_pdf','wrong_id','process_override'])
def test_no_implicit_policy_or_card_rewrite(tmp_path,monkeypatch,fixture,case):
    plan,root,cfg=planned(tmp_path,monkeypatch,fixture)
    if case=='missing_decision':cfg.write_text(cfg.read_text().replace('lhapdf_link_decision = "decision.json"',''))
    elif case=='missing_policy':cfg.write_text(cfg.read_text().replace('lhapdf_linker = "preserve-activated-v1"',''))
    elif case=='wrong_policy':cfg.write_text(cfg.read_text().replace('preserve-activated-v1','automatic'))
    elif case in ('wrong_pdf','wrong_id'):
        card=root/'cards/run.dat';card.write_text(card.read_text().replace("'lhapdf'","'cteq6l1'") if case=='wrong_pdf' else card.read_text().replace('260000','260001'))
    else:
        card=root/'cards/process.dat';card.write_text('set lhapdf whatever\n'+card.read_text())
    with pytest.raises(ValueError):p.build_execution_plan(root,cfg)
    assert not (root/'output').exists()


def inert_execution(plan,root,f,monkeypatch,mutation=None):
    """Real plan/approval/record functions; fake activation calls actual inner entry."""
    original=link.generation_decision;original_approval=p.verify_execution_approval
    calls=[];approvals=[]
    monkeypatch.setenv('PYTHONDONTWRITEBYTECODE','1')
    def approve(plan):approvals.append(plan['plan_sha256']);return original_approval(plan)
    monkeypatch.setattr(p,'verify_execution_approval',approve)
    def capture(prefix,**kw):
        if 'environment' in kw:return original(prefix,**kw)
        return original(prefix,environment=dict(os.environ),run=f.probe,system='Darwin',architecture='arm64',python_executable=f.prefix/'bin/python')
    monkeypatch.setattr(link,'generation_decision',capture)
    def run(command,**kw):
        command=list(map(str,command));calls.append((command,kw))
        if command==plan['generator_command']:
            previous=Path.cwd();env=dict(os.environ);os.chdir(kw['cwd']);os.environ.clear();os.environ.update(f.env)
            if mutation=='env_drift':os.environ['LDFLAGS']+=' -dead_strip'
            if mutation=='unknown_env':os.environ['MADGRAPH_BASE']=str(root)
            if mutation=='no_bytecode':os.environ.pop('PYTHONDONTWRITEBYTECODE')
            try:
                if mutation=='forged_success':return SimpleNamespace(returncode=0)
                rc=p.generate_activated(p.load_plan(plan['plan_path']))
            finally:os.chdir(previous);os.environ.clear();os.environ.update(env)
            return SimpleNamespace(returncode=rc)
        assert command==plan['generation_linker']['payload_command']
        assert kw['env']['LDFLAGS']==f.env['LDFLAGS']+' -lc++'
        assert kw['env']['PYTHONDONTWRITEBYTECODE']=='1' and kw['cwd'].parent==root/'work/madgraph'
        if mutation=='mg_failure':return SimpleNamespace(returncode=9)
        target=kw['cwd']/'PROC_madgraph/Events/run_01/unweighted_events.lhe.gz'
        target.parent.mkdir(parents=True);target.write_bytes(gzip.compress(b'inert LHE fixture, no events'))
        if mutation=='post_drift':file(f.prefix/'lib/libLHAPDF.dylib','changed during MG')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(p.subprocess,'run',run)
    return calls,approvals


def test_real_approval_record_publish_chain_inert_activation_and_mg(tmp_path,monkeypatch,fixture):
    plan,root,_=planned(tmp_path,monkeypatch,fixture);approve_fixture(plan);p.prepare(plan)
    calls,approvals=inert_execution(plan,root,fixture,monkeypatch)
    assert p.generate(plan)==0 and len(calls)==2 and len(approvals)>=4
    rec=link.read_decision(root/'output/madgraph/linker_execution.json')
    assert rec['status']=='madgraph_subprocess_completed' and rec['physics_certified'] is False
    assert rec['retained_lhe']['sha256']==p.fingerprint(root/'output/madgraph/unweighted_events.lhe.gz')['sha256']
    assert rec['actual_decision']==link.read_decision(root/'decision.json')
    assert (Path(rec['cwd'])/'linker_preflight.json').is_file()


@pytest.mark.parametrize('mutation',['env_drift','unknown_env','no_bytecode','forged_success','mg_failure','post_drift'])
def test_inner_failure_cannot_publish(tmp_path,monkeypatch,fixture,mutation):
    plan,root,_=planned(tmp_path,monkeypatch,fixture);approve_fixture(plan);p.prepare(plan)
    calls,_=inert_execution(plan,root,fixture,monkeypatch,mutation)
    if mutation=='mg_failure':assert p.generate(plan)==9
    else:
        with pytest.raises((ValueError,OSError)):p.generate(plan)
    assert not (root/'output/madgraph/unweighted_events.lhe.gz').exists()
    assert not (root/'output/madgraph/linker_execution.json').exists()
    if mutation in ('env_drift','unknown_env','no_bytecode'):assert len(calls)==1
    if mutation!='forged_success':assert len(list((root/'work/madgraph').glob('attempt-*/linker_failure.json')))==1


def test_unapproved_direct_inner_rejects_before_probe(tmp_path,monkeypatch,fixture):
    plan,root,_=planned(tmp_path,monkeypatch,fixture);p.write_plan(plan)
    monkeypatch.setattr(link,'generation_decision',lambda *a,**k:pytest.fail('probe before approval'))
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:pytest.fail('launch before approval'))
    with pytest.raises(ValueError,match='approval'):p.generate_activated(plan)
    assert not (root/'work').exists()


def test_approved_pdf_drift_stops_before_outer_activation(tmp_path,monkeypatch,fixture):
    plan,root,_=planned(tmp_path,monkeypatch,fixture);approve_fixture(plan);p.prepare(plan)
    file(fixture.pdf/(link.PDF_SET+'_0000.dat'),'changed PDF')
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:pytest.fail('activation after drift'))
    with pytest.raises(ValueError):p.generate(plan)
    assert not (root/'work').exists()


def test_actual_execution_receipt_expansion_and_transitive_drift(tmp_path,monkeypatch,fixture):
    from ravel.workflow import execution as e
    plan,root,_=planned(tmp_path,monkeypatch,fixture);approve_fixture(plan)
    stages={s['stage']:s for s in plan['stages']}
    def start(name):
        s=stages[name]
        spec=e.plan_stage(root,name,s['command'],s['inputs'],s['outputs'],s['depends_on'],str(root))
        return e.begin_attempt(root,name,spec,'logs/'+name+'.log')
    prepare=start('prepare');p.prepare(plan);assert e.finish_attempt(root,prepare,0)==0
    mg=start('madgraph')
    candidate=Path(p.__file__).parents[1]
    assert str(candidate/'physics/native_lhapdf.py') in mg['input_snapshot']
    assert all(str(x) in mg['input_snapshot'] for x in candidate.rglob('*.py'))
    assert mg['parents']=={'prepare':prepare['receipt_sha256']}
    calls,_=inert_execution(plan,root,fixture,monkeypatch)
    assert p.generate(plan)==0
    assert e.finish_attempt(root,mg,0)==0 and e.stage_errors(root,'madgraph')==[]
    receipt=e.load_execution(root)['stages']['madgraph']
    assert str(root/'output/madgraph/linker_execution.json') in receipt['output_snapshot']
    file(fixture.pdf/(link.PDF_SET+'_0000.dat'),'later changed selected PDF')
    assert any('inputs changed' in x for x in e.stage_errors(root,'madgraph'))


def test_bootstrap_rejects_unapproved_inner(tmp_path,monkeypatch,fixture):
    import subprocess
    import sys
    plan,root,_=planned(tmp_path,monkeypatch,fixture);p.write_plan(plan)
    python=Path(sys.executable)
    env=dict(os.environ);env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
    result=subprocess.run([str(python),'-B',str(Path(p.__file__).parents[1]/'_bootstrap.py'),
                           'ravel.physics.native_pipeline','generate-activated','--plan',plan['plan_path']],
                          cwd=tmp_path,env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==2 and 'approval' in result.stderr
    assert not (root/'work').exists()


@pytest.mark.parametrize('case',['command','payload','record_path','omitted_pdf_source'])
def test_bound_runtime_contract_cannot_be_narrowed(tmp_path,monkeypatch,fixture,case):
    plan,root,_=planned(tmp_path,monkeypatch,fixture)
    if case=='command':plan['generator_command']=['/usr/bin/true']
    elif case=='payload':plan['generation_linker']['payload_command']=['/usr/bin/true']
    elif case=='record_path':plan['generation_linker']['execution_record']=str(root/'wrong.json')
    else:plan['sources']=[x for x in plan['sources'] if not x['path'].endswith('_0000.dat')]
    plan['plan_sha256']=p.plan_hash(plan)
    with pytest.raises(ValueError):p.checked_linker(plan)


@pytest.mark.parametrize('key,value',[('DYLD_FRAMEWORK_PATH','/tmp'),('DYLD_LIBRARY_PATH','/tmp'),
    ('LD_LIBRARY_PATH','/tmp'),('GCC_NEW_CONTROL','unknown'),('PYTHONHOME','/tmp'),
    ('LDFLAGS_LD','-Xlinker -l -Wl,stdc++'),('LDFLAGS_LD','-Lrelative')])
def test_secondary_link_or_import_surfaces_fail_closed(fixture,key,value):
    fixture.env[key]=value
    with pytest.raises(ValueError):fixture.capture()


def test_secondary_matching_runtime_and_unrelated_values_are_preserved(fixture):
    fixture.env['LDFLAGS_LD']='-Wl,-l,c++'
    fixture.env['UNRELATED_PRIVATE_VALUE']='TEST-SENTINEL-NOT-RECORDED'
    env,d=fixture.capture()
    assert env['LDFLAGS_LD']==fixture.env['LDFLAGS_LD']
    assert env['UNRELATED_PRIVATE_VALUE']=='TEST-SENTINEL-NOT-RECORDED'
    assert 'TEST-SENTINEL-NOT-RECORDED' not in json.dumps(d)
    assert link.validate_generation_decision(d,fixture.prefix)==d


@pytest.mark.parametrize('case',['missing_link_arch','malformed_link_sources','none_prefix','missing_source_key'])
def test_nested_malformed_records_raise_valueerror(fixture,case):
    _,d=fixture.capture();prefix=fixture.prefix
    if case=='missing_link_arch':del d['link']['architecture']
    elif case=='malformed_link_sources':d['link']['sources']=[None,None]
    elif case=='none_prefix':prefix=None
    else:del d['link']['sources'][1]['path']
    with pytest.raises(ValueError):link.validate_generation_decision(d,prefix)
