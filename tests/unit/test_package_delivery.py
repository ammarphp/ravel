from workflow_instruction_inventory_fixture import FINAL_INVENTORY, assert_inventory
"""Software transport only; no scientific execution or runtime qualification."""
import builtins
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import types

import pytest
from ravel.workflow.campaign_budget import tomllib

REPO=Path(__file__).resolve().parents[2]

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_catalogue_uses_imported_installed_package_and_complete_modes(tmp_path):
    package=tmp_path/'site-packages/ravel'
    shutil.copytree(REPO/'src/ravel',package)
    module=load(package/'workflow/capability_routing.py','installed_catalogue_control')
    result=module.catalogue()
    from ravel.workflow.science import MODES
    assert [r['mode'] for r in result['operations']]==list(MODES)
    assert result['source_root']==str(package.parent)
    assert all(Path(p['path']).is_relative_to(package) for p in result['source_pins'])
    assert result['compute_authorized'] is result['physics_validated'] is False
    assert not (package.parent/'src/ravel').exists()

def test_explicit_checkout_remains_selected_and_missing_root_cannot_fall_back(tmp_path):
    from ravel.workflow import capability_routing as c
    result=c.catalogue(REPO)
    assert result['source_root']==str(REPO)
    assert all(Path(p['path']).is_relative_to(REPO/'src/ravel') for p in result['source_pins'])
    with pytest.raises(ValueError,match='regular file'):
        c.catalogue(tmp_path/'missing-selected-checkout')

def test_explicit_symlink_source_still_refuses(tmp_path):
    from ravel.workflow import capability_routing as c
    (tmp_path/'linked').symlink_to(REPO,target_is_directory=True)
    with pytest.raises(ValueError,match='regular file'):
        c.catalogue(tmp_path/'linked')

def test_unrelated_directory_intake_keeps_original_request_and_host_identity(tmp_path,monkeypatch,capsys):
    import platform
    # This pure control explicitly does not observe the optional uname CPU probe.
    monkeypatch.setattr(platform,'platform',lambda:'unobserved-under-pure-control')
    from ravel import cli
    from ravel.workflow.agent_host import AgentHost
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:cli.main(['--help'])
    assert e.value.code==0
    prompt='Survey published collider searches.'
    assert cli.main(['initiate','--prompt',prompt,'--out',str(tmp_path/'draft')])==0
    contract=json.loads((tmp_path/'draft/inputs/task_contract.json').read_text())
    recovery=json.loads((tmp_path/'draft/inputs/capability_recovery.json').read_text())
    assert contract['prompt']==recovery['original_request']==prompt
    assert recovery['parent_goal_acceptance']=='not_assessed' and recovery['compute_authorized'] is False
    packet=json.loads((tmp_path/'draft/current_state.json').read_text())
    # Survey intakes make the census optional (required_stages); the basis manifest is next.
    assert packet['next_required']['what']=='basis_manifest'
    assert packet['next_instruction']['logical_path']=='docs/workflow/steps/02-inputs.md'
    assert [r['logical_path'] for r in packet['instruction_resources']]==packet['instructions']
    import hashlib
    assert all(Path(r['path']).is_file() and hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'] for r in packet['instruction_resources'])
    identity=AgentHost().identity
    assert identity and any('capability-source:' in k for k in identity['sources'])

def test_toml_host_reader_uses_explicit_backport_only_if_stdlib_absent(monkeypatch,tmp_path):
    fake=types.ModuleType('tomli');fake.load=tomllib.load;fake.loads=tomllib.loads
    monkeypatch.setitem(sys.modules,'tomli',fake)
    original=builtins.__import__
    def absent(name,*args,**kwargs):
        if name=='tomllib':raise ModuleNotFoundError('test absent stdlib TOML',name='tomllib')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',absent)
    module=load(REPO/'src/ravel/workflow/campaign_budget.py','ravel.workflow._campaign_toml_control')
    p=tmp_path/'settings.toml';p.write_text('[generation]\nevents = 19\n')
    with p.open('rb') as f:assert module.tomllib.load(f)=={'generation':{'events':19}}
    with pytest.raises(tomllib.TOMLDecodeError):module.tomllib.loads('x = [')

def test_toml_fallback_does_not_hide_unrelated_module_failure(monkeypatch):
    original=builtins.__import__
    def absent(name,*args,**kwargs):
        if name=='tomllib':raise ModuleNotFoundError('other missing dependency',name='unrelated_dependency')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',absent)
    with pytest.raises(ModuleNotFoundError,match='other missing dependency'):
        load(REPO/'src/ravel/workflow/campaign_budget.py','ravel.workflow._campaign_other_control')

def test_build_hook_is_bound_to_own_helpers_and_preserves_caller_modules(monkeypatch):
    pytest.importorskip('hatchling')
    module=load(REPO/'hatch_build.py','pinned_hatch_control')
    from ravel.python_installation import setup_files
    expected=len(FINAL_INVENTORY)+len(setup_files(REPO))
    stale=types.ModuleType('ravel.python_installation');stale.setup_files=lambda root:['pyproject.toml']
    monkeypatch.setitem(sys.modules,'ravel.python_installation',stale)
    path_before=list(sys.path);prefix_before={n for n in sys.modules if n.startswith('_ravel_build_payload_')}
    hook=module.CustomBuildHook(str(REPO),{},None,None,str(REPO/'ignored-build'),'wheel')
    data={'force_include':{}};hook.initialize('standard',data)
    assert len(data['force_include'])==expected
    assert all('pyproject.toml' not in p for p in data['force_include'].values())
    assert sys.modules['ravel.python_installation'] is stale and sys.path==path_before
    assert {n for n in sys.modules if n.startswith('_ravel_build_payload_')}==prefix_before

def test_python_profiles_preserve_runtime_boundary():
    project=tomllib.loads((REPO/'pyproject.toml').read_text())['project']
    assert project['requires-python']=='>=3.11,<3.13'
    from ravel.python_installation import declarations
    profile=declarations(REPO)
    assert project['dependencies']==profile['runtime_dependencies']
    assert set(project['dependencies'])<=set(profile['dependencies'])
    assert 'numpy==1.26.4' in project['dependencies']
    assert 'onnxruntime==1.30.0' in project['dependencies']
    assert not any(dep.startswith(('smodels=', 'torch=', 'ROOT=', 'rivet=')) for dep in project['dependencies'])
    extras=project['optional-dependencies']
    assert extras['figures']==['Pillow>=10,<13','pypdf>=5,<7']
    assert extras['source-validation']==['jsonschema>=4.23,<5']
    import re
    assert not any(re.split(r'[<=>;\[]',dep,1)[0].strip().lower() in {'root','rivet','wilson','smelli'} for deps in extras.values() for dep in deps)

def test_source_byte_reader_needs_no_yaml_but_table_parser_requires_it(tmp_path,monkeypatch):
    import hashlib
    original=builtins.__import__
    def absent(name,*args,**kwargs):
        if name=='yaml':raise ModuleNotFoundError('source-tables extra is absent',name='yaml')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',absent)
    module=load(REPO/'src/ravel/physics/source_tables.py','no_optional_yaml_control')
    raw=b'independent_variables: []\ndependent_variables: []\n';p=tmp_path/'table.yaml';p.write_bytes(raw)
    assert module.bounded_read(p)==raw
    with pytest.raises(ValueError,match=r'ravel-hep\[source-tables\]'):
        module.read_table_snapshot(raw,{'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()})

def test_optional_yaml_parse_keeps_literal_numbers_and_duplicate_refusal(tmp_path):
    pytest.importorskip('yaml')
    import hashlib
    from ravel.physics import source_tables as s
    raw=b'independent_variables:\n- header: {name: x}\n  values: [{low: 0, high: 1}]\ndependent_variables:\n- header: {name: y}\n  values: [{value: 1.00}]\n'
    pin={'path':str(tmp_path/'table.yaml'),'sha256':hashlib.sha256(raw).hexdigest()}
    result=s.read_table_snapshot(raw,pin)
    assert result['rows']==1 and result['payload']['dependent_variables'][0]['values'][0]['value']=={'literal':'1.00','decimal':'1.00'}
    bad=raw.replace(b'{name: y}',b'{name: y, name: z}')
    with pytest.raises(ValueError,match='unique literal string'):
        s.read_table_snapshot(bad,{**pin,'sha256':hashlib.sha256(bad).hexdigest()})


def test_installed_instruction_closure_and_strict_source_override(tmp_path,monkeypatch):
    from ravel import paths
    # Stand in for an installed module's location, retaining real bundled bytes.
    monkeypatch.setattr(paths,'__file__',str(tmp_path/'site-packages/ravel/paths.py'))
    monkeypatch.setattr(paths,'package_data_path',lambda *p:REPO.joinpath('src/ravel/data',*p))
    assert_inventory(paths.WORKFLOW_INSTRUCTIONS)
    for logical in paths.WORKFLOW_INSTRUCTIONS:
        row=paths.workflow_instruction(logical)
        assert row['logical_path']==logical and row['size']>0
        assert Path(row['path']).is_relative_to(REPO/'src/ravel/data/workflow')
    with pytest.raises(FileNotFoundError):paths.workflow_instruction_path('docs/workflow/start.md',source_root=tmp_path/'missing')
    with pytest.raises(ValueError):paths.workflow_instruction_path('../private.md')
    root=tmp_path/'selected';p=root/'docs/workflow/start.md';p.parent.mkdir(parents=True);p.write_text('selected source instruction')
    assert paths.workflow_instruction('docs/workflow/start.md',source_root=root)['path']==str(p)


def test_instruction_reader_refuses_oversize_and_symlink(tmp_path):
    from ravel.paths import workflow_instruction
    p=tmp_path/'docs/workflow/start.md';p.parent.mkdir(parents=True);p.write_bytes(b'x'*(256*1024+1))
    with pytest.raises(ValueError,match='bounded regular'):workflow_instruction('docs/workflow/start.md',source_root=tmp_path)
    p.unlink();p.symlink_to(REPO/'src/ravel/data/workflow/docs/workflow/start.md')
    with pytest.raises(FileNotFoundError):workflow_instruction('docs/workflow/start.md',source_root=tmp_path)


def test_every_original_stage_has_a_finite_instruction():
    from ravel.workflow.current_state import BLOCKER_INSTRUCTIONS
    from ravel.validation.validate_run_state import STAGE_ORDER
    from ravel.paths import WORKFLOW_INSTRUCTIONS
    assert set(BLOCKER_INSTRUCTIONS)==set(STAGE_ORDER)
    assert set(BLOCKER_INSTRUCTIONS.values())<=set(WORKFLOW_INSTRUCTIONS)


def _instruction_build_source(tmp_path):
    from ravel.paths import WORKFLOW_INSTRUCTIONS
    target=tmp_path/'build-source'
    shutil.copytree(REPO/'src/ravel',target/'src/ravel')
    for logical in WORKFLOW_INSTRUCTIONS:
        p=target/logical;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((REPO/logical).read_bytes())
    from ravel.python_installation import setup_files
    for logical in ['pyproject.toml']+setup_files(REPO):
        p=target/logical;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((REPO/logical).read_bytes())
    return target


def _instruction_hook(target,kind):
    pytest.importorskip('hatchling')
    module=load(REPO/'hatch_build.py','instruction_hatch_control')
    hook=module.CustomBuildHook(str(target),{},None,None,str(target/'ignored-build'),kind)
    data={'force_include':{}};hook.initialize('standard',data)
    return data['force_include']


@pytest.mark.parametrize('kind',['wheel','sdist'])
def test_instruction_build_retains_complete_canonical_authority(kind):
    from ravel.paths import WORKFLOW_INSTRUCTIONS
    project=tomllib.loads((REPO/'pyproject.toml').read_text())
    assert project['tool']['hatch']['build']['targets']['wheel']['exclude']==['src/ravel/data/workflow']
    included=_instruction_hook(REPO,kind)
    for logical in WORKFLOW_INSTRUCTIONS:
        source=str(REPO/logical)
        assert included[source]==('ravel/data/workflow/'+logical if kind=='wheel' else logical)
        if kind=='sdist':
            assert included[str(REPO/'src/ravel/data/workflow'/logical)]=='src/ravel/data/workflow/'+logical
    assert not [v for v in included.values() if '/data/replay/' in v]


@pytest.mark.parametrize('kind',['wheel','sdist'])
def test_instruction_build_refuses_stale_canonical_document(tmp_path,kind):
    target=_instruction_build_source(tmp_path)
    p=target/'docs/workflow/start.md';p.write_bytes(p.read_bytes()+b'\nchanged canonical instruction\n')
    with pytest.raises(ValueError,match='differs from canonical source'):_instruction_hook(target,kind)


@pytest.mark.parametrize('change',['missing-canonical','missing-bundle','extra-bundle','linked-canonical'])
def test_instruction_build_refuses_incomplete_or_aliased_population(tmp_path,change):
    target=_instruction_build_source(tmp_path)
    source=target/'docs/workflow/start.md';bundle=target/'src/ravel/data/workflow/docs/workflow/start.md'
    if change=='missing-canonical':source.unlink()
    elif change=='missing-bundle':bundle.unlink()
    elif change=='extra-bundle':(bundle.parent/'private.md').write_text('not declared')
    else:source.unlink();source.symlink_to(bundle)
    with pytest.raises((ValueError,FileNotFoundError)):_instruction_hook(target,'wheel')


def test_instruction_build_admits_explicit_synchronized_source_edit(tmp_path):
    target=_instruction_build_source(tmp_path);logical='docs/workflow/start.md'
    source=target/logical;bundle=target/'src/ravel/data/workflow'/logical
    raw=source.read_bytes()+b'\nsynchronized source edit\n';source.write_bytes(raw);bundle.write_bytes(raw)
    included=_instruction_hook(target,'wheel')
    assert included[str(source)]=='ravel/data/workflow/'+logical and source.read_bytes()==bundle.read_bytes()
