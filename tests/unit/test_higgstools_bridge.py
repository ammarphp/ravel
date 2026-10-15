"""Synthetic file-protocol and interpretation controls; no native tool runs."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/higgs/higgstools'


def bridge():
    return importlib.import_module('ravel.physics.higgstools_bridge')


def sample():
    return json.loads((FIXTURES / 'sector.json').read_text())


def doctor():
    return json.loads((FIXTURES / 'doctor.json').read_text())


def test_import_never_loads_higgs_with_poisoned_package(tmp_path):
    poison = tmp_path / 'Higgs'
    poison.mkdir()
    (poison / '__init__.py').write_text("raise RuntimeError('forbidden host import')\n")
    code = ('import sys; sys.path.insert(0, '+repr(str(tmp_path))+'); '
            'import ravel.physics.higgstools_bridge; assert "Higgs" not in sys.modules')
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('fault', ['commit', 'cp', 'assignment'])
def test_input_refuses_commit_cp_and_ambiguous_assignment(fault):
    b = bridge(); sector = sample()
    if fault == 'commit': sector['datasets']['hbdataset']['commit'] = 'c' * 40
    if fault == 'cp': del sector['neutral_scalars'][0]['cp']
    if fault == 'assignment':
        sector['neutral_scalars'][1]['mass_gev'] = sector['neutral_scalars'][0]['mass_gev'] + .1
        sector['mass_assignment']['choices'] = []
    with pytest.raises(ValueError): b.validate_bundle(sector, doctor())


def test_fake_worker_roundtrips_complete_particle_population(tmp_path):
    b = bridge(); sector = sample()
    result = b.exchange(sector, 'higgs-bounds', doctor(), tmp_path / 'child',
                        [sys.executable, '-B', str(FIXTURES / 'fake_worker.py')])
    assert len(result['particles']) == 4
    assert result['datasets'] == {k:v['commit'] for k,v in sector['datasets'].items()}
    for row in result['particles']:
        assert {'allowed', 'obsratio', 'expected_ratio', 'selected_limit_id'} <= row.keys()
    assert result['physics_validated'] is False


def test_nonselected_channel_cannot_exclude(tmp_path):
    b = bridge()
    result = b.exchange(sample(), 'higgs-bounds', doctor(), tmp_path / 'child',
                        [sys.executable, '-B', str(FIXTURES / 'fake_worker.py')])
    claims = [{'particle_id':'s1', 'limit_id':'other-limit', 'excluded':True}]
    with pytest.raises(ValueError, match='selected'): b.check_hb_selection(result, claims)
    row = result['particles'][0]
    assert b.check_hb_selection(result, [{'particle_id':row['id'],
        'limit_id':row['selected_limit_id'], 'excluded':not row['allowed']}])['check'] == 'check:higgs.hb_selection'


def test_signals_requires_dof_for_pvalue_and_uses_total_chi2(tmp_path):
    b = bridge(); sector = sample()
    run = lambda s,p: b.exchange(s, 'higgs-signals', doctor(), p,
        [sys.executable, '-B', str(FIXTURES / 'fake_worker.py')])
    result = run(sector, tmp_path / 'no-dof')
    assert 'p_value' not in result
    sector['degrees_of_freedom'] = {'value':3, 'statistic':'chi2_total', 'basis':'Declared fixed-point goodness of fit'}
    result = run(sector, tmp_path / 'dof')
    from scipy.stats import chi2
    assert result['p_value'] == pytest.approx(chi2.sf(result['chi2_total'], 3), rel=0, abs=1e-12)
    assert result['delta_chi2'] == result['chi2_total'] - result['sm_reference']['chi2_total']
    assert len(result['measurements']) == result['n_obs'] == 3


@pytest.mark.parametrize('setting', [7, 8])
def test_spectrum_refusal_points_to_operations_and_keeps_settings_off(setting):
    from ravel.physics import model_specific_spectrum as named
    blocks = {}
    for row in named.profile()['input_map']:
        blocks.setdefault(row['block'], []).append(' '+' '.join(map(str,row['codes']))+' '+('1' if row['parameter']=='SignvS' else '10'))
    raw = '\n'.join('BLOCK '+k+'\n'+'\n'.join(v) for k,v in blocks.items())+'\nBLOCK FlexibleSUSY\n 12 0\n 31 0\nBLOCK FlexibleDecay\n'+'\n'.join(f' {n} {1 if n==setting else 0}' for n in range(10))+'\n'
    with pytest.raises(ValueError, match='higgs-bounds.*higgs-signals'):
        named.input_witness(raw.encode(), False, 'none')
    clean = raw.replace(f' {setting} 1', f' {setting} 0')
    assert named.input_witness(clean.encode(), False, 'none')['explicit_decay_settings'][setting] == '0'


@pytest.mark.xfail(reason='awaits H-16', strict=True)
def test_live_worker_qualification():
    pytest.fail('Dedicated runtime and pinned upstream API qualification are pending')


@pytest.mark.parametrize('field,value', [('schema_version', True), ('request_sha256','wrong'),
    ('datasets', {}), ('particles', []), ('p_value', .5)])
def test_bounds_response_cannot_change_protocol_pin_population_or_pvalue(tmp_path, field, value):
    b = bridge()
    result = b.exchange(sample(), 'higgs-bounds', doctor(), tmp_path/'child',
        [sys.executable, '-B', str(FIXTURES/'fake_worker.py')])
    result.pop('status');result.pop('scope');result.pop('limitations');result.pop('physics_validated')
    expected = result['request_sha256']
    result[field] = value
    with pytest.raises(ValueError): b.finalize_result(result, sample(), 'higgs-bounds', expected)


@pytest.mark.parametrize('dof', [{'value':0,'statistic':'chi2_total','basis':'Synthetic'},
    {'value':True,'statistic':'chi2_total','basis':'Synthetic'},
    {'value':2,'statistic':'delta_chi2','basis':'Synthetic'},
    {'value':2,'statistic':'chi2_total'}])
def test_dof_requires_positive_integer_named_statistic_and_basis(dof):
    s=sample();s['degrees_of_freedom']=dof
    with pytest.raises(ValueError): bridge().validate_bundle(s, doctor())


@pytest.mark.parametrize('fault', ['negative-mass','nonfinite','duplicate','br-total','factorization','unknown-cp'])
def test_no_silent_scalar_or_rate_input_repairs(fault):
    s=sample()
    if fault=='negative-mass':s['neutral_scalars'][0]['mass_gev']=-10
    if fault=='nonfinite':s['neutral_scalars'][0]['couplings']['cWW']=float('nan')
    if fault=='duplicate':s['charged_scalars'][0]['id']='s1'
    if fault=='br-total':s['neutral_scalars'][0]['branching_ratios']['gg']=.8
    if fault=='factorization':s['charged_scalars'][0]['rates'][0]['sigma_br_pb']=.2
    if fault=='unknown-cp':s['neutral_scalars'][0]['cp']='unknown'
    with pytest.raises(ValueError):bridge().validate_bundle(s, doctor())


def test_input_builders_preserve_explicit_choices_and_signed_couplings():
    b=bridge();s=sample();meta={k:s[k] for k in ('datasets','mass_assignment','provenance')}
    s['neutral_scalars'][1]['mass_gev']=125
    with pytest.raises(ValueError):b.build_effective_couplings(s['neutral_scalars'],s['charged_scalars'],**meta)
    meta['mass_assignment']['choices']=[{'particle_ids':['s1','s2'],'choice':'native','basis':'Explicit synthetic overlap decision'}]
    s['neutral_scalars'][0]['couplings']['cWW']=-1.
    result=b.build_effective_couplings(s['neutral_scalars'],s['charged_scalars'],**meta)
    assert result['neutral_scalars'][0]['couplings']['cWW']==-1
    for row in s['neutral_scalars']:
        row['couplings']={}
        row['rates']=[{'collider':'LHC13','production':'ggH','decay':'bb','sigma_br_pb':.05,'production_pb':.1}]
    assert b.build_direct_rates(s['neutral_scalars'],s['charged_scalars'],**meta)['input_kind']=='direct-rates'


@pytest.mark.parametrize('producer', ['FlexibleSUSY','SPheno','2HDMC','extended-scalar-point'])
def test_slha_builder_requires_declared_cp_and_transports_source_rows(producer):
    b=bridge();s=sample();meta={k:s[k] for k in ('datasets','mass_assignment','provenance')}
    raw=b'BLOCK MASS\n 35 220\nBLOCK COUPLINGS Q= 1000\n 1 -.5\nDECAY 35 .01\n .2 2 5 -5\n'
    rows=[{'id':'s1','pdg':35,'charge':'neutral','cp':'even',
           'coupling_selectors':{'cZZ':{'block':'COUPLINGS','codes':[1],'scale':'1000'}},
           'decay_channels':{'bb':[5,-5]}}]
    result=b.build_slha(raw,producer,rows,**meta)
    assert result['neutral_scalars'][0]['couplings']['cZZ']==-.5
    assert result['neutral_scalars'][0]['branching_ratios']=={'bb':.2}
    del rows[0]['cp']
    with pytest.raises(ValueError,match='CP'):b.build_slha(raw,producer,rows,**meta)


def test_native_launch_without_ordinary_worker_is_refused(tmp_path):
    with pytest.raises(ValueError,match='ordinary science worker'):
        bridge()._approved({'input':'sector.json'},tmp_path,'higgs-bounds')


def test_worker_without_delegation_never_imports_poisoned_higgs(tmp_path):
    poison=tmp_path/'Higgs';poison.mkdir();(poison/'__init__.py').write_text("raise RuntimeError('forbidden import')\n")
    request=tmp_path/'request.json';request.write_text(json.dumps({'delegation':None}))
    worker=bridge().WORKER
    code='import sys,runpy;sys.path.insert(0,'+repr(str(tmp_path))+');sys.argv=['+repr(str(worker))+','+repr(str(request))+','+repr(str(tmp_path/'response.json'))+'];runpy.run_path('+repr(str(worker))+',run_name="__main__")'
    result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
    assert result.returncode!=0
    assert 'delegation required' in result.stderr and 'forbidden import' not in result.stderr


def native_document(tmp_path, operation='higgs-bounds'):
    """Inert interpreter marker and local synthetic trees, never executed."""
    import hashlib
    import shutil
    b=bridge();s=sample()
    for key in ('hbdataset','hsdataset'):
        shutil.copytree(FIXTURES/key,tmp_path/key)
        s['datasets'][key]['path']=str(tmp_path/key)
    sm=json.loads((FIXTURES/'sm-sector.json').read_text())
    sm['datasets']=deepcopy(s['datasets'])
    sm_path=tmp_path/'sm.json';sm_path.write_text(json.dumps(sm))
    s['sm_reference']={'path':str(sm_path),'sha256':hashlib.sha256(sm_path.read_bytes()).hexdigest()}
    report=tmp_path/'doctor.json';report.write_text(json.dumps(doctor()))
    executable=tmp_path/'.venv-higgstools/bin/python';executable.parent.mkdir(parents=True)
    executable.write_text('Inert executable marker; do not run\n');executable.chmod(0o700)
    doc={'schema_version':1,'operation':operation,'bundle':s,
         'doctor_report':{'path':str(report),'sha256':hashlib.sha256(report.read_bytes()).hexdigest()},
         'runtime':{'python':{'path':str(executable),'sha256':hashlib.sha256(executable.read_bytes()).hexdigest()},'version':'synthetic-version'},
         'max_seconds':30,'max_ram_mib':128}
    path=tmp_path/'input.json';path.write_text(json.dumps(doc))
    return {'input':str(path)},doc,path


@pytest.mark.parametrize('fault',['wrong-venv','python-pin','dataset-pin','dataset-extra','doctor-pin','sm-pin','sm-settings','dataset-link'])
def test_native_input_inventory_refuses_runtime_data_or_reference_drift(tmp_path,fault):
    b=bridge();task,d,path=native_document(tmp_path)
    if fault=='wrong-venv':d['runtime']['python']['path']=str(tmp_path/'bin/python')
    if fault=='python-pin':d['runtime']['python']['sha256']='e'*64
    if fault=='dataset-pin':(tmp_path/'hbdataset/synthetic.json').write_text('{}')
    if fault=='dataset-extra':(tmp_path/'hbdataset/extra.json').write_text('{}')
    if fault=='doctor-pin':d['doctor_report']['sha256']='e'*64
    if fault=='sm-pin':d['bundle']['sm_reference']['sha256']='e'*64
    if fault=='sm-settings':
        import hashlib
        sm=tmp_path/'sm.json';value=json.loads(sm.read_text());value['mass_assignment']['window_gev']=4
        sm.write_text(json.dumps(value));d['bundle']['sm_reference']['sha256']=hashlib.sha256(sm.read_bytes()).hexdigest()
    if fault=='dataset-link':(tmp_path/'hbdataset/link.json').symlink_to(tmp_path/'hbdataset/synthetic.json')
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError):b.inputs(task,tmp_path)


def test_native_input_inventory_and_ordinary_gate_are_reused(tmp_path,monkeypatch):
    b=bridge();task,doc,path=native_document(tmp_path)
    files=b.inputs(task,tmp_path)
    assert path in files and b.WORKER in files and b.SCHEMA in files
    assert b.execution_seconds(task,tmp_path)==35
    observed=[]
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db,'execute_native',lambda *a,**k:observed.append(a))
    with pytest.raises(ValueError,match='ordinary science worker'):b.run(task,tmp_path,tmp_path/'out')
    assert observed==[]


def test_worker_evaluates_both_operations_and_same_call_sm_with_synthetic_api(tmp_path):
    from types import SimpleNamespace
    worker=importlib.import_module('ravel.physics.higgstools_worker')
    task,doc,path=native_document(tmp_path)
    calls=[]
    class Particle:
        def __init__(self,identity):self.id=identity
        def setMass(self,x):calls.append(('mass',self.id,x))
        def setTotalWidth(self,x):calls.append(('width',self.id,x))
        def setBr(self,*x):calls.append(('br',self.id,x))
        def setCxn(self,*x):calls.append(('cxn',self.id,x))
    class Predictions:
        def __init__(self):self.ids=[]
        def addParticle(self,identity,charge,cp):
            self.ids.append(identity);calls.append(('particle',identity,charge,cp));return Particle(identity)
    hp=SimpleNamespace(Predictions=Predictions,effectiveCouplingInput=lambda p,**kw:calls.append(('couplings',p.id,kw)))
    class Bounds:
        def __init__(self,path):self.path=path
        def __call__(self,pred):return SimpleNamespace(particleResults={identity:SimpleNamespace(allowed=True,obsratio=.5,expratio=.7,limit=SimpleNamespace(id='selected-limit')) for identity in pred.ids})
    class Signals:
        nObservables=3
        def __init__(self,path):self.calls=[];calls.append(('signals-engine',self))
        def __call__(self,pred):self.calls.append(pred);return 9. if len(pred.ids)>1 else 3.
        def chisqMeasurements(self,pred):return {'m1':2.,'m2':3.,'m3':4.}
    modules={'hp':hp,'hb':SimpleNamespace(Bounds=Bounds),'hs':SimpleNamespace(Signals=Signals)}
    request={'operation':'higgs-bounds','bundle':doc['bundle']}
    result=worker.evaluate(request,'d'*64,**modules)
    assert len(result['particles'])==4 and result['particles'][0]['selected_limit_id']=='selected-limit'
    request['operation']='higgs-signals'
    result=worker.evaluate(request,'d'*64,**modules)
    assert result['delta_chi2']==6 and result['sm_reference']['same_call'] is True
    engines=[row[1] for row in calls if row[0]=='signals-engine']
    assert len(engines)==1 and len(engines[0].calls)==2
    assert [r[3] for r in calls if r[0]=='particle'][:4]==['even','odd','mixed','undefined']
    first_width=next(i for i,r in enumerate(calls) if r[0]=='width')
    first_coupling=next(i for i,r in enumerate(calls) if r[0]=='couplings')
    assert first_width>first_coupling


def test_direct_rates_never_invent_a_production_factorization():
    from types import SimpleNamespace
    worker=importlib.import_module('ravel.physics.higgstools_worker');s=sample()
    del s['charged_scalars'][0]['rates'][0]['production_pb']
    class Particle:
        def setMass(self,x):pass
        def setTotalWidth(self,x):pass
        def setBr(self,*x):pass
    class Predictions:
        def addParticle(self,*a):return Particle()
    hp=SimpleNamespace(Predictions=Predictions,effectiveCouplingInput=lambda *a,**k:None)
    with pytest.raises(ValueError,match='factorization'):worker.predictions(hp,s)
    calls=[]
    Particle.setChannelRate=lambda self,*args:calls.append(args)
    worker.predictions(hp,s)
    assert calls==[('LHC13','pp','tb',.08)]


def test_signals_refuses_wrong_reference_or_worker_pvalue(tmp_path):
    b=bridge();s=sample()
    result=b.exchange(s,'higgs-signals',doctor(),tmp_path/'child',
        [sys.executable,'-B',str(FIXTURES/'fake_worker.py')])
    for fault in ('same-call','reference','pvalue','delta'):
        raw=deepcopy(result)
        if fault=='same-call':raw['sm_reference']['same_call']=False
        if fault=='reference':raw['sm_reference']['input_sha256']='e'*64
        if fault=='pvalue':raw['p_value']=.5
        if fault=='delta':raw['delta_chi2']=10
        with pytest.raises(ValueError):b.finalize_result(raw,s,'higgs-signals',raw['request_sha256'])


@pytest.mark.parametrize('fault', ['missing','duplicate','not-ready','mismatch'])
def test_doctor_record_must_contain_unique_ready_dataset_pins(fault):
    report=doctor();rows=report['groups'][0]['checks']
    if fault=='missing':rows.pop()
    if fault=='duplicate':rows.append(deepcopy(rows[1]))
    if fault=='not-ready':rows[1]['status']='version_mismatch'
    if fault=='mismatch':rows[1]['found']='e'*40
    with pytest.raises(ValueError):bridge().validate_bundle(sample(),report)


def test_worker_is_rejected_under_host_interpreter_before_external_import():
    worker=importlib.import_module('ravel.physics.higgstools_worker')
    with pytest.raises(ValueError,match='dedicated HiggsTools interpreter'):
        worker._delegated_parent({'delegation':{}},Path('response.json'))


def test_registration_fragments_publish_operation_and_check_seams():
    b=bridge();root=b.SCHEMA.parent.parent/'registration'
    for operation in b.OPERATIONS:
        fragment=json.loads((root/(operation+'.json')).read_text())
        assert fragment[operation]['implementation']['module']=='ravel.physics.higgstools_bridge'
        assert fragment['_integration']['task_fields']==['input']
        assert fragment['_integration']['runtime']=='{REPO}/.venv-higgstools/bin/python'
    assert fragment['_integration']['doctor_checks']==['higgstools-python','hbdataset','hsdataset']
    bounds=json.loads((root/'higgs-bounds.json').read_text())
    assert bounds['_integration']['claim_checks']['check:higgs.hb_selection'].endswith(':check_hb_selection')


def test_effective_coupling_defaults_require_explicit_parameter_names_and_basis():
    from types import SimpleNamespace
    worker=importlib.import_module('ravel.physics.higgstools_worker');s=sample()
    class Particle:
        def setMass(self,x):pass
        def setTotalWidth(self,x):pass
        def setBr(self,*x):pass
        def setCxn(self,*x):pass
    class Predictions:
        def addParticle(self,*a):return Particle()
    calls=[]
    def coupling(particle,cWW=1.,cZZ=1.,cbb=1.):calls.append(cbb)
    hp=SimpleNamespace(Predictions=Predictions,effectiveCouplingInput=coupling)
    with pytest.raises(ValueError,match='undeclared native'):worker.predictions(hp,s)
    s['provenance']['native_coupling_defaults']={'parameters':['cbb'],'basis':'Explicit synthetic default-law choice'}
    worker.predictions(hp,s)
    assert calls==[1.,1.,1.]


def test_ordinary_worker_seam_uses_shared_launcher_and_dedicated_command(tmp_path,monkeypatch):
    import os
    from ravel.workflow import science,execution
    from ravel.physics import reinterpret_db
    b=bridge();task,doc,path=native_document(tmp_path)
    rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    (rd/science.PLAN).write_text('{}')
    out=rd/'outputs';out.mkdir()
    plan={'output_directory':'outputs','max_seconds':35}
    state={'status':'running','child_pid':os.getpid(),'child_identity':'synthetic-identity','fingerprint':'synthetic-fingerprint'}
    monkeypatch.setattr(science,'verify_worker',lambda r:plan)
    monkeypatch.setattr(science,'execution_spec',lambda r:{'mode':'higgs-bounds','task':task})
    monkeypatch.setattr(execution,'load_execution',lambda r:{'stages':{'science':state}})
    monkeypatch.setattr(execution,'process_identity',lambda p:'synthetic-identity')
    observed=[]
    def inert_launcher(command,output,resources):
        observed.append(command)
        assert resources['max_seconds']==30
        subprocess.run([sys.executable,'-B',str(FIXTURES/'fake_worker.py'),*command[-2:]],check=True)
    monkeypatch.setattr(reinterpret_db,'execute_native',inert_launcher)
    result=b.run(task,tmp_path,out)
    assert result['status']=='passed'
    assert len(observed)==1
    assert observed[0][:3]==[doc['runtime']['python']['path'],'-B',str(b.WORKER)]
    state['child_pid']=-1
    with pytest.raises(ValueError,match='live ordinary'):b._approved(task,out,'higgs-bounds')


def test_child_parent_witness_requires_current_approval_and_input_bytes(tmp_path,monkeypatch):
    import hashlib
    from ravel.workflow import science,execution
    worker=importlib.import_module('ravel.physics.higgstools_worker')
    rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    plan=rd/science.PLAN;plan.write_text(json.dumps({'stage_binding':{'fingerprint':'synthetic-fingerprint'}}))
    approval=rd/science.APPROVAL;approval.write_text(json.dumps({'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest()}))
    asset=tmp_path/'asset.json';asset.write_text('{}')
    delegation={'rundir':str(rd),'parent_pid':1234,'parent_identity':'synthetic-identity',
        'fingerprint':'synthetic-fingerprint','output':str(rd/'outputs'),
        'input_hashes':{str(asset):hashlib.sha256(asset.read_bytes()).hexdigest()}}
    state={'status':'running','child_pid':1234,'child_identity':'synthetic-identity',
           'fingerprint':'synthetic-fingerprint','outputs':['outputs']}
    monkeypatch.setattr(worker.sys,'executable',str(tmp_path/'.venv-higgstools/bin/python'))
    monkeypatch.setattr(worker.sys,'prefix',str(tmp_path/'.venv-higgstools'))
    monkeypatch.setattr(worker.os,'getppid',lambda:1234)
    monkeypatch.setattr(science,'execution_spec',lambda r:{'mode':'higgs-bounds'})
    monkeypatch.setattr(execution,'load_execution',lambda r:{'stages':{'science':state}})
    monkeypatch.setattr(execution,'process_identity',lambda p:'synthetic-identity')
    request={'delegation':delegation,'operation':'higgs-bounds'};response=rd/'outputs/higgstools/response.json'
    assert worker._delegated_parent(request,response)==delegation
    state['status']='completed'
    with pytest.raises(ValueError,match='live exact'):worker._delegated_parent(request,response)
    state['status']='running';asset.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='input pin changed'):worker._delegated_parent(request,response)
