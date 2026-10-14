"""Portable ordinary-route controls; synthetic custody, no optional SDK calls."""
import ast
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace as N, ModuleType
import sys

import pytest
from ravel import cli
from ravel.physics import contur_companion as api, contur_companion_worker as worker
from ravel.workflow import science, execution
from ravel.plotting import science_figures

S=None  # No optional upstream package or stored scientific artifacts used.


@pytest.fixture(autouse=True)
def inert(monkeypatch):
    import subprocess,platform
    def no(*a,**kw): raise AssertionError('external SDK/native calls forbidden in pure controls')
    for name in ('Popen','run','call','check_call','check_output'):
        monkeypatch.setattr(subprocess,name,no)
    monkeypatch.setattr(os,'system',no)
    monkeypatch.setattr(platform,'platform',lambda:'Explicit inert platform control')


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n');return path


def pin(path): return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def policy():
    return {'schema_version':1,'policy':{'schema_version':1,
        'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],
        'claim_scopes':{'diagnostic':{'checks':['integrity'],'actions':['delivery','reuse']}}},
        'correction_contract':{'task_fields':[],'input_slots':[]}}


def choices(operation):
    if operation=='sm-test':return dict(offline=False,use_spey=False,only_analyses=[],veto_analyses=[],prediction='A',graphics=False)
    if operation=='herwig-xs-br':return dict(offline=False,seed=101,tag='runpoint',tolerance=0.,**{k:False for k in api.XS_FLAGS})
    if operation=='map-plots':return dict(offline=False,variables=['mZp','cotH'],levels=[.5,1,1.5],slice={},save_plots=True,databg=False,no_exp=False,pools=False,format='pdf',ilevel=1,iorder=3,isigma=.25,style='DRAFT')
    return dict(offline=False,only_analyses=[],veto_analyses=[],databg=False,no_exp=False,runpoint=None,include_none=False,cls=0.)


def fixture(tmp,operation):
    tmp.mkdir(parents=True,exist_ok=True);assets={}
    for kind,names in {'source':['src/contur/__init__.py','bin/contur','pyproject.toml','COPYING'],
                       'data':['data/reference.yoda'],'user':['analyses.db','models.db']}.items():
        root=tmp/kind;root.mkdir();files={}
        for name in names:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('inert source '+name+'\n');files[name]=pin(p)['sha256']
        md=dict(schema_version=1,kind='contur-'+kind,root=str(root),files=files,scope='Synthetic custody, not installed runtime')
        if kind=='source':md.update(version=api.VERSION,commit=api.COMMIT)
        assets[kind]=pin(put(tmp/(kind+'-manifest.json'),md))
    entry=tmp/'source/bin'/api.ENTRIES[operation][0];entry.write_text('# inert bin entry\n')
    py=tmp/'python';py.write_text('not executable as interpreter');py.chmod(0o755)
    dep=tmp/'dependency.py';dep.write_text('# inert dependency')
    rt=dict(schema_version=1,kind='contur-declared-runtime',python_sha256=pin(py)['sha256'],installed_distribution_version='stand-in; not runtime proof',
            files=[pin(dep)],environment={k:os.environ.get(k) for k in api.custody.ENV_KEYS},scope='inert complete declared fixture')
    if operation=='sm-test':inputs={'config':None}
    else:
        root=tmp/'0003';root.mkdir()
        if operation=='herwig-xs-br':
            for name in ['params.dat','herwig-S101-runpoint_0003.log','herwig-S101-runpoint_0003.out']:
                (root/name).write_text('mZp = 1000\n' if name=='params.dat' else 'Synthetic native-format prerequisite; not Herwig evidence\nCross-section\nevents attempts (nb)\n')
        else:
            with sqlite3.connect(root/'results.db') as c:c.execute('CREATE TABLE inert_control(id INTEGER)')
            (root/'scripts').mkdir();(root/'scripts/d01.py').write_text('# inert script')
        md=dict(schema_version=1,kind='contur-companion-input',root=str(root),files=api.bounded_inventory(root),source='inert native output association; no native result')
        inputs={'payload':pin(put(tmp/'payload-manifest.json',md))}
        if operation!='herwig-xs-br':inputs['database']='results.db'
    doc=dict(schema_version=1,source='Synthetic pure custody control',operation=operation,runtime={'python':pin(py),'manifest':pin(put(tmp/'runtime.json',rt))},
        assets=assets,entry=pin(entry),inputs=inputs,options=choices(operation),max_seconds=20,max_ram_mib=512,renderer_cores=2)
    path=put(tmp/'request.json',doc)
    return {'input':str(path)},doc


@pytest.mark.parametrize('operation',list(api.ENTRIES))
def test_public_caller_materialization_and_unapproved_plan(tmp_path,operation):
    task,doc=fixture(tmp_path/'inputs',operation);review=put(tmp_path/'policy.json',policy());out=tmp_path/'science.json'
    assert cli.main(['contur-companion','--input',task['input'],'--review-policy',str(review),'--out',str(out)])==0
    spec=json.loads(out.read_text());assert spec['schema_version']==2 and spec['mode']=='contur-companion'
    assert science.adapter(spec) is api and science._new_capability(spec)
    rd=tmp_path/'run';science.plan(rd,out)
    assert not (rd/science.APPROVAL).exists()
    with pytest.raises(ValueError):api.run(task,tmp_path,tmp_path/'unapproved')
    original={str(p):api.custody._sha(p) for p in api.inputs(task,tmp_path)}
    resolved,emitted=api.materialize(task,tmp_path,tmp_path/'prepared')
    api.verify_emitted(emitted)
    assert resolved['operation']==operation
    assert original=={str(p):api.custody._sha(p) for p in api.inputs(task,tmp_path)}


@pytest.mark.parametrize('operation',list(api.ENTRIES))
def test_wrong_entry_and_unbound_members_refuse(tmp_path,operation):
    task,doc=fixture(tmp_path,operation)
    doc['entry']=pin(tmp_path/'source/bin/contur');put(Path(task['input']),doc)
    with pytest.raises(ValueError,match='entry'):api.inputs(task,tmp_path)


@pytest.mark.parametrize('field,value',[('max_seconds',True),('max_seconds',901),('renderer_cores',0),('renderer_cores',5),('max_ram_mib',511)])
def test_resources_no_boolean_or_unbounded_substitution(tmp_path,field,value):
    task,doc=fixture(tmp_path,'sm-test');doc[field]=value;put(Path(task['input']),doc)
    with pytest.raises(ValueError):api.inputs(task,tmp_path)


def test_original_pair_units_defaults_no_missing_log(tmp_path):
    task,doc=fixture(tmp_path,'herwig-xs-br');_,_,_,bundles,_=api.admission(task,tmp_path)
    p=api.herwig_profile(bundles['payload']['root'],doc)
    assert p['native_total_unit']=='nb' and p['stem']=='herwig-S101-runpoint_0003'
    original=bundles['payload']['root']/'herwig-S101-runpoint_0003.out'
    original.write_bytes(original.read_bytes().replace(b'(nb)',b'(pb)'))
    with pytest.raises(ValueError):api.inputs(task,tmp_path)
    with pytest.raises(ValueError,match='nb'):api.herwig_profile(bundles['payload']['root'],doc)


@pytest.mark.parametrize('operation',list(api.ENTRIES))
def test_original_root_cannot_be_written_by_materialize(tmp_path,operation):
    task,doc=fixture(tmp_path,operation);root=tmp_path/'source';before=api.custody._workspace_inventory(root)
    with pytest.raises(ValueError,match='disjoint'):api.materialize(task,tmp_path,root/'derived')
    assert before==api.custody._workspace_inventory(root) and not (root/'derived').exists()


def test_intended_emitted_bytes_not_first_foreign_reread(tmp_path,monkeypatch):
    original=api.verify_emitted
    def alter(pins):
        Path(pins[0]['path']).write_text('{"foreign":true}\n');return original(pins)
    monkeypatch.setattr(api,'verify_emitted',alter)
    with pytest.raises(ValueError,match='intended'):api.write_new(tmp_path/'record.json',{'intended':True})



@pytest.mark.parametrize('bits',[0o4000,0o2000,0o1000])
def test_privilege_mode_refuses_before_any_materialization(tmp_path,bits):
    task,doc=fixture(tmp_path/'original','rivet-plots');source=tmp_path/'original/0003/scripts/d01.py';source.chmod(0o755|bits)
    with pytest.raises(ValueError,match='privilege'):api.materialize(task,tmp_path,tmp_path/'work')
    assert not (tmp_path/'work').exists()

@pytest.mark.parametrize('change',['mode','bytes','alias','unlisted'])
def test_original_staged_protections_survive_precise_product_allowance(tmp_path,change):
    task,doc=fixture(tmp_path/'original','rivet-plots');resolved,_=api.materialize(task,tmp_path,tmp_path/'work')
    _,_,_,bundles,_=api.admission(task,tmp_path);work=tmp_path/'work';source=work/'input/0003/scripts/d01.py'
    product=work/'input/0003/scripts/profile.pdf';product.write_bytes(b'inert exact native product')
    product_pin={**pin(product),'size':product.stat().st_size}
    assert api.staged_inputs(resolved,bundles,work,generated_products=[product_pin])['scientific_files']=={'0003/'+key:val for key,val in bundles['payload']['manifest']['files'].items()}
    if change=='mode':source.chmod(0o755)
    elif change=='bytes':source.write_text('foreign')
    elif change=='alias':source.unlink();source.symlink_to(tmp_path/'original/0003/scripts/d01.py')
    else:(source.parent/'foreign.json').write_text('{}')
    with pytest.raises(ValueError):api.staged_inputs(resolved,bundles,work,generated_products=[product_pin])


def test_serial_unclaimed_products_cannot_be_laundered_by_fresh_hash(tmp_path):
    task,doc=fixture(tmp_path/'original','rivet-plots');_,_=api.materialize(task,tmp_path,tmp_path/'work');_,_,_,bundles,_=api.admission(task,tmp_path)
    work=tmp_path/'work';script=work/'input/0003/scripts/d01.py';product=script.parent/'foreign.pdf';product.write_bytes(b'not source declared')
    observation={'operation':'rivet-plots','renderer_calls':[dict(script=str(script),sha256=api.custody._sha(script),directory=str(work/'native-output'))],
                 'render_receipts':[dict(script=str(script),script_sha256=api.custody._sha(script),status='returned',saves=[dict(path=str(product),sha256=api.custody._sha(product),size=product.stat().st_size,status='written')])]}
    with pytest.raises(ValueError):api.generated_input_products(observation,bundles,work)


@pytest.mark.parametrize('mutate',[False,True])
def test_native_worker_intended_detached_return_matches_emitted_bytes(tmp_path,monkeypatch,mutate):
    task,doc=fixture(tmp_path/'original','sm-test');resolved,_=api.materialize(task,tmp_path,tmp_path/'work');work=tmp_path/'work'
    monkeypatch.setattr(worker,'delegated_parent',lambda *a:None)  # explicit no-lifecycle/native authority control
    monkeypatch.setattr(api.custody,'module_witness',lambda *a,**kw:{'scope':'inert origin boundary only; no SDK import/ABI'})
    imported={'contur':N(__version__=api.VERSION),'contur.run.run_smtest':N(), 'contur.config.config':N(),
        'contur.util.utils':N(),'contur.run.arg_utils':N()}
    original_import=worker.importlib.import_module
    monkeypatch.setattr(worker.importlib,'import_module',lambda name,*a,**kw:imported[name] if name in imported else original_import(name,*a,**kw))
    def no_sdk(document,bundles,directory,modules):
        out=directory/'native-output';out.mkdir();(out/'probs_ALL.pdf').write_bytes(b'explicit inert probability product')
        cfg=dict(stat_types=['SMBG'],use_spey=False,**{key:False for key in ('exclude_searches','exclude_met_ratio','exclude_hgg','exclude_hww','exclude_b_veto','exclude_awz','exclude_soft_physics','tracks_only')})
        return dict(operation='sm-test',phase='returned',outputs=api.bounded_inventory(out),analyses=[{'name':'inert'}],pvalues=[{'value':.4}],effective_configuration=cfg,renderer_calls=[],render_receipts=[])
    monkeypatch.setattr(worker,'execute_operation',no_sdk)
    active=api.write_new;reached=[]
    def returned(path,value):
        commitment=active(path,value)
        if Path(path).name=='native-observation.json':
            reached.append(commitment)
            if mutate:value['calibration_qualified']=True
        return commitment
    monkeypatch.setattr(api,'write_new',returned)
    previous_path=list(sys.path);previous_env={k:os.environ.get(k) for k in ('CONTUR_USER_DIR','CONTUR_DATA_PATH','RAVEL_CONTUR_RENDER_BINDING','RAVEL_CONTUR_RENDER_BINDING_SHA256')}
    try:
        if mutate:
            with pytest.raises(ValueError,match='returned value'):worker.native_worker(work/'native-input.json',work,tmp_path/'inert-rundir')
        else:
            observed=worker.native_worker(work/'native-input.json',work,tmp_path/'inert-rundir')
            assert observed==json.loads((work/'native-observation.json').read_text())
        assert reached
    finally:
        sys.path[:]=previous_path
        for key,value in previous_env.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


@pytest.mark.parametrize('change', ['none', 'missing', 'bytes', 'alias', 'outside'])
def test_ordinary_product_table_preserves_exact_profile_commitment(tmp_path, change):
    out = tmp_path/'output'; work = out/'contur-companion-work'
    native = work/'native-output/native-table.txt'
    native.parent.mkdir(parents=True); native.write_bytes(b'inert native table')
    profile = work/'input/0003/scripts/native-profile.pdf'
    profile.parent.mkdir(parents=True); profile.write_bytes(b'inert native profile')
    commitment = {**pin(profile), 'size': profile.stat().st_size}
    result = dict(status_scope=api.SCOPE, physics_validated=False,
        observation={'outputs': {'native-table.txt': pin(native)['sha256']}},
        staged_after_readback={'generated_input_products': [commitment]})
    if change == 'missing': profile.unlink()
    elif change == 'bytes': profile.write_bytes(b'foreign changed product')
    elif change == 'alias':
        other = tmp_path/'same.pdf'; other.write_bytes(profile.read_bytes())
        profile.unlink(); profile.symlink_to(other)
    elif change == 'outside':
        other = tmp_path/'outside.pdf'; other.write_bytes(b'unrelated')
        result['staged_after_readback']['generated_input_products'] = [{**pin(other), 'size': other.stat().st_size}]
    spec = {'mode': 'contur-companion', 'task': {}}
    if change != 'none':
        with pytest.raises(ValueError): science_figures.render(spec, result, tmp_path, out)
        return
    table = science_figures.render(spec, result, tmp_path, out)['tables'][0]
    assert table['files'] == ['contur-companion-results.json',
        'contur-companion-work/native-output/native-table.txt',
        'contur-companion-work/input/0003/scripts/native-profile.pdf']
    assert profile.read_bytes() == b'inert native profile'


def test_mode_change_during_copy_does_not_become_preparation_baseline(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path/'original', 'rivet-plots')
    source = tmp_path/'original/0003/scripts/d01.py'; source.chmod(0o640)
    copy = api.shutil.copy2; reached = []
    def late(source_path, target_path, *args, **kwargs):
        if Path(source_path) == source:
            source.chmod(0o600); reached.append(True)
        return copy(source_path, target_path, *args, **kwargs)
    monkeypatch.setattr(api.shutil, 'copy2', late)
    with pytest.raises(ValueError, match='mode differs from preparation'):
        api.materialize(task, tmp_path, tmp_path/'work')
    assert reached
    assert not (tmp_path/'work/preparation.json').exists()


def test_rebased_preparation_cannot_replace_intended_mode_commitment(tmp_path):
    task, _ = fixture(tmp_path/'original', 'rivet-plots')
    source = tmp_path/'original/0003/scripts/d01.py'; source.chmod(0o640)
    doc, emitted = api.materialize(task, tmp_path, tmp_path/'work')
    baseline, known = api.prepared_modes(tmp_path/'work', emitted[1])
    assert baseline['0003/scripts/d01.py'] == 0o640
    source.chmod(0o600); (tmp_path/'work/input/0003/scripts/d01.py').chmod(0o600)
    p = tmp_path/'work/preparation.json'; foreign = json.loads(p.read_text())
    foreign['staged_inputs']['scientific_modes']['0003/scripts/d01.py'] = 0o600
    p.write_bytes(api._json_bytes(foreign))
    with pytest.raises(ValueError, match='intended companion returned value differs'):
        api.prepared_modes(tmp_path/'work', known)


@pytest.mark.parametrize('change', ['none', 'source', 'copy', 'joint', 'preparation'])
def test_native_worker_retains_original_config_mode_baseline(tmp_path, monkeypatch, change):
    task, doc = fixture(tmp_path/'original', 'sm-test')
    source = tmp_path/'original/config.dat'; source.write_text('inert explicit config\n'); source.chmod(0o640)
    doc['inputs']['config'] = pin(source); put(Path(task['input']), doc)
    _, _ = api.materialize(task, tmp_path, tmp_path/'work'); work = tmp_path/'work'
    copied = work/'input/config.dat'
    monkeypatch.setattr(worker, 'delegated_parent', lambda *a: None)
    monkeypatch.setattr(api.custody, 'module_witness', lambda *a, **kw: {'scope': 'inert origin only, no ABI'})
    imports = {'contur': N(__version__=api.VERSION), 'contur.run.run_smtest': N(),
        'contur.config.config': N(), 'contur.util.utils': N(), 'contur.run.arg_utils': N()}
    original_import = worker.importlib.import_module
    monkeypatch.setattr(worker.importlib, 'import_module',
        lambda name, *a, **kw: imports[name] if name in imports else original_import(name, *a, **kw))
    reached = []
    def no_native(document, bundles, directory, modules):
        reached.append(True)
        if change in ('source', 'joint'): source.chmod(0o600)
        if change in ('copy', 'joint'): copied.chmod(0o600)
        if change == 'preparation':
            path = work/'preparation.json'; altered = json.loads(path.read_text())
            altered['uncommitted'] = True; path.write_bytes(api._json_bytes(altered))
        output = directory/'native-output'; output.mkdir(); (output/'probs_ALL.pdf').write_bytes(b'inert probability product')
        cfg = dict(stat_types=['SMBG'], use_spey=False, **{key: False for key in
            ('exclude_searches','exclude_met_ratio','exclude_hgg','exclude_hww','exclude_b_veto',
             'exclude_awz','exclude_soft_physics','tracks_only')})
        return dict(operation='sm-test', phase='returned', outputs=api.bounded_inventory(output),
            analyses=[{'name':'inert'}], pvalues=[{'value':.4}], effective_configuration=cfg,
            renderer_calls=[], render_receipts=[])
    monkeypatch.setattr(worker, 'execute_operation', no_native)
    saved_path = list(sys.path); keys = ('CONTUR_USER_DIR','CONTUR_DATA_PATH',
        'RAVEL_CONTUR_RENDER_BINDING','RAVEL_CONTUR_RENDER_BINDING_SHA256')
    saved_env = {key: os.environ.get(key) for key in keys}
    try:
        if change == 'none':
            observed = worker.native_worker(work/'native-input.json', work, tmp_path/'inert-parent')
            assert observed['staged_before']['scientific_modes'] == {'config.dat':0o640}
            assert observed['staged_after']['scientific_modes'] == {'config.dat':0o640}
            assert observed == json.loads((work/'native-observation.json').read_text())
        else:
            with pytest.raises(ValueError):
                worker.native_worker(work/'native-input.json', work, tmp_path/'inert-parent')
        assert reached
    finally:
        sys.path[:] = saved_path
        for key, value in saved_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
