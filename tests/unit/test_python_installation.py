"""Installation contract/transport only. No pip/native installs or scientific calls."""
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile

import pytest
from packaging.requirements import Requirement
from ravel import python_installation as p

ROOT = Path(__file__).resolve().parents[2]


def clone(tmp_path):
    target=tmp_path/'source';target.mkdir()
    for rel in ['pyproject.toml']+p.setup_files(ROOT):
        q=target/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((ROOT/rel).read_bytes())
    return target


def test_canonical_full_host_and_required_conflicts():
    m=p.declarations(ROOT)
    assert m['requires_python']=='>=3.11,<3.13'
    assert len(m['dependencies'])>=38
    names={Requirement(d).name.lower() for d in m['dependencies']}
    assert {'jax','hepdata-cli','servicex','hist','awkward','wilson','flavio','smelli','emcee','dynesty','camb','classy','cobaya','pysecdec'}<=names
    assert {'smodels','torch','root','rivet','madgraph','sfitter'}.isdisjoint(names)
    assert [q['name'] for q in m['isolated_required']]==['smodels','sfitter']
    assert 'smodels==3.2.1' in (ROOT/m['isolated_required'][0]['requirements']).read_text()
    assert 'numpy==2.5.3' in (ROOT/m['isolated_required'][1]['requirements']).read_text()
    assert m['isolated_required'][1]['python']=='==3.12.*'
    plan=p.plan(ROOT)
    assert plan['host_command'][-1]==str(ROOT/'requirements-full.txt')
    assert plan['physics_validated'] is plan['compute_authorized'] is False


@pytest.mark.parametrize('change',['host','manifest','engine','replay','symlink','extra-alias'])
def test_inconsistent_install_assets_refuse(tmp_path,change):
    c=clone(tmp_path)
    if change=='host':
        q=c/'requirements-full.txt';q.write_text(q.read_text().replace('numpy==1.26.4','numpy==2.5.3'))
    elif change=='manifest':
        q=c/p.MANIFEST;d=json.loads(q.read_text());d['dependencies'][0]='pyhf==0.6.1';q.write_text(json.dumps(d))
    elif change=='engine':
        q=c/'environment/python/requirements-smodels.txt';q.write_text(q.read_text().replace('3.2.1','3.1.1'))
    elif change=='replay':
        q=c/'environment/python/sfitter-replay.lock';q.write_bytes(q.read_bytes()+b'\nmutated\n')
    elif change=='symlink':
        q=c/'requirements-full.txt';q.unlink();q.symlink_to(ROOT/'requirements-full.txt')
    else:
        q=c/'pyproject.toml';q.write_text(q.read_text().replace('symbolic = [','unadmitted = ["unknown-python-provider==1"]\nsymbolic = ['))
    with pytest.raises(ValueError):
        (p.validate_aliases(c) if change=='extra-alias' else p.declarations(c))


def test_complete_setup_plan_from_foreign_cwd(tmp_path,monkeypatch,capsys):
    monkeypatch.chdir(tmp_path)
    assert p.main(['--plan'],source_root=ROOT)==0
    out=json.loads(capsys.readouterr().out)
    assert out['source_root']==str(ROOT) and len(out['isolated_required'])==2
    assert out['host_command_cwd']==str(ROOT)


def test_installed_resource_projection(tmp_path,monkeypatch):
    installed=tmp_path/'site/ravel';installed.mkdir(parents=True)
    for rel in p.setup_files(ROOT):
        q=installed/'data/installation'/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((ROOT/rel).read_bytes())
    monkeypatch.setattr(p,'__file__',str(installed/'python_installation.py'))
    assert p.declarations()['dependencies']==p.declarations(ROOT)['dependencies']
    assert p.plan()['host_directory'] is None
    with pytest.raises(SystemExit):p.main([])


def test_complete_helper_creates_only_local_environments_and_installs_once(tmp_path,monkeypatch):
    c=clone(tmp_path);calls=[];made=[]
    monkeypatch.setattr(sys,'version_info',(3,12,0))
    class Builder:
        def __init__(self,with_pip):assert with_pip is True
        def create(self,target):
            made.append(target);target.mkdir();(target/'pyvenv.cfg').write_text('fixture')
    monkeypatch.setattr(p.venv,'EnvBuilder',Builder)
    def output(argv,**kwargs):
        target=Path(argv[0]).parent.parent
        return json.dumps([str(target),[3,12]])
    monkeypatch.setattr(subprocess,'check_output',output)
    sealed={'runtime_id':'0'*16,'runtime_dir':'/fixture/runtime/'+'0'*16,'launcher':'/fixture/runtime/'+'0'*16+'/bin/ravel','reused':False}
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        return subprocess.CompletedProcess(argv,0,stdout=json.dumps(sealed),stderr='')
    monkeypatch.setattr(subprocess,'run',run)
    value=p.install(c)
    assert made==[c/'.venv',c/'.venv-smodels',c/'.venv-sfitter']
    pip=[(a,k) for a,k in calls if a[1:5]==['-m','pip','install','-r']]
    assert len(pip)==3 and all(k['cwd']==c and k['check'] is True for _,k in pip)
    # The installation ends by sealing the host environment's RAVEL with that environment's interpreter.
    assert len(calls)==4 and calls[-1][0]==[str(c/'.venv/bin/python'),'-I','-m','ravel','governed-runtime','seal']
    assert calls[-1][1]['cwd']==c
    assert value['governed_runtime']=={**{k:sealed[k] for k in ('runtime_id','runtime_dir','launcher','reused')},'sealed':True}
    assert value['complete_python_profile'] is True and value['native_admitted'] is False


def test_existing_global_or_wrong_interpreter_cannot_be_used(tmp_path,monkeypatch):
    c=clone(tmp_path);(c/'.venv').mkdir();(c/'.venv/pyvenv.cfg').write_text('fixture')
    monkeypatch.setattr(sys,'version_info',(3,12,0))
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:json.dumps(['/usr/global',[3,12]]))
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('global pip attempt'))
    with pytest.raises(ValueError,match='project-local'):p.install(c)


def test_wrong_python_refuses_before_create(tmp_path,monkeypatch):
    monkeypatch.setattr(sys,'version_info',(3,11,0))
    monkeypatch.setattr(p.venv,'EnvBuilder',lambda **k:pytest.fail('wrong interpreter venv'))
    with pytest.raises(ValueError,match='python3.12'):p.install(ROOT)


def test_pip_failure_stops_before_other_environments(tmp_path,monkeypatch):
    c=clone(tmp_path);seen=[];monkeypatch.setattr(sys,'version_info',(3,12,0))
    monkeypatch.setattr(p,'_environment',lambda root,logical:seen.append(logical) or root/logical/'bin/python')
    def fail(*a,**k):raise subprocess.CalledProcessError(3,a[0])
    monkeypatch.setattr(subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError):p.install(c)
    assert seen==['.venv']


def test_setup_population_and_native_script_export():
    names=p.setup_files(ROOT)
    assert names==sorted(set(names))
    assert {'requirements-full.txt',p.MANIFEST,'scripts/setup/python_installation.py','native/scripts/paths.sh'}<=set(names)
    assert any(v.startswith('environment/scripts/') for v in names)
    registry=json.loads((ROOT/'distribution.json').read_text())['distribution']
    assert 'requirements-full.txt' in registry['files'] and 'native/setup' in registry['trees']


def test_host_aliases_remain_compatible():
    project=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']
    assert set(project['optional-dependencies'])=={'source-tables','replay','test','cosmology','measurement','classifier','science','figures','source-validation','symbolic'}
    assert p.validate_aliases(ROOT) is True


def test_full_profile_keeps_optional_and_build_requirements():
    manifest=p.declarations(ROOT)
    canonical=tomllib.loads((ROOT/'pyproject.toml').read_text())
    assert manifest['runtime_dependencies']==canonical['project']['dependencies']
    assert manifest['build_requirements']==canonical['build-system']['requires']
    assert manifest['build_requirements']==['hatchling==1.27.0']
    assert manifest['selected_extras']['test']==['pytest>=8.3.5,<9']
    for group in [manifest['build_requirements'], *manifest['selected_extras'].values()]:
        assert set(group)<=set(manifest['dependencies'])


@pytest.mark.parametrize('group', ['runtime_dependencies', 'build_requirements', 'test', 'cosmology'])
def test_full_profile_omission_refuses(tmp_path, group):
    root=clone(tmp_path)
    path=root/p.MANIFEST
    manifest=json.loads(path.read_text())
    values=(manifest['selected_extras'][group] if group in {'test','cosmology'} else manifest[group])
    values.pop()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        p.declarations(root)


def test_wheel_sdist_installed_dependency_and_asset_contract(tmp_path):
    from hatchling.builders.wheel import WheelBuilder
    from hatchling.builders.sdist import SdistBuilder
    out=tmp_path/'dist';out.mkdir()
    wheel=Path(next(WheelBuilder(str(ROOT)).build(directory=str(out))))
    sdist=Path(next(SdistBuilder(str(ROOT)).build(directory=str(out))))
    with zipfile.ZipFile(wheel) as z:
        names=z.namelist();metadata=z.read(next(n for n in names if n.endswith('.dist-info/METADATA'))).decode()
        from email import message_from_string
        msg=message_from_string(metadata)
        from packaging.specifiers import SpecifierSet
        assert SpecifierSet(msg['Requires-Python'])==SpecifierSet('>=3.11,<3.13')
        from packaging.utils import canonicalize_name
        def signature(value):
            r=Requirement(value)
            return (canonicalize_name(r.name),tuple(sorted(r.extras)),str(r.specifier),str(r.marker) if r.marker else None,r.url)
        installed={signature(d) for d in msg.get_all('Requires-Dist') if 'extra ==' not in d}
        manifest=p.declarations(ROOT)
        assert installed=={signature(d) for d in manifest['runtime_dependencies']}
        assert {'pytest','hatchling','camb','classy','cobaya'}.isdisjoint(
            Requirement(d).name.lower() for d in manifest['runtime_dependencies'])
        for extra, requirements in manifest['selected_extras'].items():
            selected={signature(d.split(';')[0].strip()) for d in msg.get_all('Requires-Dist')
                      if Requirement(d).marker is not None
                      and Requirement(d).marker.evaluate({'extra':extra})}
            assert selected=={signature(d) for d in requirements}
        for logical in p.setup_files(ROOT):
            assert z.read('ravel/data/installation/'+logical)==(ROOT/logical).read_bytes()
        assert z.read('ravel/python_installation.py')==(ROOT/'src/ravel/python_installation.py').read_bytes()
    import tarfile
    with tarfile.open(sdist) as t:
        base=t.getnames()[0].split('/')[0]
        for logical in p.setup_files(ROOT):
            assert t.extractfile(base+'/'+logical).read()==(ROOT/logical).read_bytes()


def test_direct_import_inventory_is_accounted():
    manifest=p.declarations(ROOT)
    roots=set()
    for path in (ROOT/'src/ravel').rglob('*.py'):
        if '/data/' in path.as_posix():continue
        tree=ast.parse(path.read_text())
        trees=[tree]
        for n in ast.walk(tree):
            if isinstance(n,ast.Constant) and type(n.value)is str and ('import ' in n.value or 'from ' in n.value):
                try:trees.append(ast.parse(n.value))
                except SyntaxError:pass
        for tree in trees:
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):roots.update(a.name.split('.')[0] for a in n.names)
                elif isinstance(n,ast.ImportFrom) and n.level==0 and n.module:roots.add(n.module.split('.')[0])
    third=roots-set(sys.stdlib_module_names)-{'ravel','__future__'}
    assert third<=set(manifest['import_roots']),sorted(third-set(manifest['import_roots']))
    assert manifest['import_roots']['ROOT']['environment']=='native'
    assert manifest['import_roots']['torch']['environment']=='sfitter'


def test_fresh_stdlib_only_wrapper_from_foreign_cwd(tmp_path):
    # Actual -S interpreter invocations are the only allowed external software
    # calls in this batch. They inspect declarations, never install or run science.
    python=Path(sys.executable)
    # The historical full-helper failure is retained in the source proposal's
    # evidence. This tiny fixture isolates its third-party bootstrap prerequisite
    # without depending on an author-local predecessor directory.
    old=tmp_path/'bootstrap_requires_packaging.py'
    old.write_text('from packaging.requirements import Requirement\n')
    before=subprocess.run([str(python),'-S','-B',str(old),'--plan'],cwd=tmp_path,text=True,capture_output=True,timeout=10)
    assert before.returncode!=0 and "No module named 'packaging'" in before.stderr
    current=subprocess.run([str(python),'-S','-B',str(ROOT/'scripts/setup/python_installation.py'),'--plan'],cwd=tmp_path,text=True,capture_output=True,timeout=10)
    assert current.returncode==0,current.stderr
    result=json.loads(current.stdout)
    assert result['source_root']==str(ROOT) and len(result['isolated_required'])==2
    assert result['compute_authorized'] is result['physics_validated'] is False
    assert not (ROOT/'.venv').exists() and not (ROOT/'.venv-smodels').exists()
    (tmp_path/'bootstrap-observation.json').write_text(json.dumps({'negative_fixture':'isolated third-party bootstrap prerequisite, not historical helper replay','old_argv':before.args,'old_code':before.returncode,'old_stderr':before.stderr,'current_argv':current.args,'current_code':current.returncode,'current_plan':result,'site_packages_enabled':False,'installs':0},indent=2)+'\n')


def test_required_particle_table_compatibility_is_canonical():
    m=p.declarations(ROOT)
    assert len(m['dependencies'])==52
    assert m['dependencies'].count('particle==0.26.2')==1
    for requirement in ('flavio==2.7.1','smelli==2.4.3','wilson==2.5.2'):
        assert requirement in m['dependencies']
    assert m['import_roots']['particle']['environment']=='host'
    assert p.validate_aliases(ROOT) is True


def test_particle_major_update_cannot_leave_stale_projection(tmp_path):
    c=clone(tmp_path)
    q=c/'pyproject.toml';q.write_text(q.read_text().replace('particle==0.26.2','particle==1.0.1'))
    with pytest.raises(ValueError,match='canonical pyproject'):p.declarations(c)


def test_required_site_profile_assets_and_entry_points():
    declared = p.plan(ROOT)['required_site_profiles']
    assert declared['required_for'] == ['root-stream', 'site-workflow']
    assert declared['execution_os'] == 'Linux' and declared['python'] == '3.12'
    assert declared['profiles']['site-analysis']['requirements'] == ['requirements-full.txt', 'requirements-site.txt']
    assert declared['profiles']['site-wms']['requirements'] == ['requirements-site-wms.txt']
    assert declared['profiles']['site-wms']['installs_ravel'] is False
    assert declared['linux_install_argv'] == ['python3.12', str(ROOT/'scripts/setup/site_installation.py'), '--install']
    assert declared['runtime_or_site_data_qualified'] is False
    assert set(p.SITE_REQUIREMENTS) <= set(p.setup_files(ROOT))
    exported = json.loads((ROOT/'distribution.json').read_text())['distribution']['files']
    assert set(p.SITE_REQUIREMENTS) <= set(exported)


@pytest.mark.parametrize('mutation', ['missing-requirements', 'wrong-profile', 'symlink'])
def test_incomplete_site_installation_cannot_be_packaged(tmp_path, mutation):
    root = clone(tmp_path)
    if mutation == 'missing-requirements':
        (root/'requirements-site-wms.txt').unlink()
    elif mutation == 'wrong-profile':
        target = root/p.SITE_MANIFEST
        value = json.loads(target.read_text())
        value['profiles']['site-wms']['installs_ravel'] = True
        target.write_text(json.dumps(value))
    else:
        target = root/'requirements-site.txt'
        target.unlink()
        target.symlink_to(ROOT/'requirements-site.txt')
    with pytest.raises((ValueError, FileNotFoundError)):
        p.setup_files(root)


def test_visual_review_renderer_is_required_in_complete_host():
    manifest=p.declarations(ROOT)
    assert manifest['dependencies'].count('pypdfium2==5.14.0')==1
    assert manifest['import_roots']['pypdfium2']['environment']=='host'
    assert p.validate_aliases(ROOT) is True


def test_original_role_pydantic_v2_is_a_direct_required_host_dependency():
    m=p.declarations(ROOT)
    assert m['dependencies'].count('pydantic==2.14.0')==1
    assert m['import_roots']['pydantic']['environment']=='host'
    assert 'pydantic==2.14.0' in (ROOT/'requirements-full.txt').read_text().splitlines()
    assert p.validate_aliases(ROOT) is True


def test_tokenizer_closure_is_pinned_after_onnxruntime_in_every_declaration():
    m=p.declarations(ROOT)
    closure=['onnxruntime==1.30.0','tokenizers==0.22.1','huggingface-hub==1.33.0','hf-xet==1.7.0']
    canonical=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['dependencies']
    rows=[l.strip() for l in (ROOT/'requirements-full.txt').read_text().splitlines()
          if l.strip() and not l.startswith('#')]
    for values in (m['dependencies'],m['runtime_dependencies'],canonical,rows):
        start=values.index(closure[0])
        assert values[start:start+len(closure)]==closure
        assert all(values.count(v)==1 for v in closure)
    assert m['import_roots']['tokenizers']=={'environment':'host','provider':'tokenizers'}
    assert {'huggingface_hub','hf_xet'}.isdisjoint(m['import_roots'])
