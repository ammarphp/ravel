"""Specific LLP generator target and intended-output regression controls."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
import test_llp_plane_recipe as f
from ravel.physics import llp_plane_recipe as op


def set_config(base,d,cfg,target):
    c=d['points'][1]['components'][0]
    old=f.read(c['generation']);cp=f.emit(base/'generator/config.json',cfg)
    old['config']={k:cp[k] for k in ('path','sha256')}
    c['generation']=f.emit(base/'generation-request.json',old)
    c['generation_target']=f.emit(base/'generation-target.json',target)


@pytest.mark.parametrize('change',['coordinate','mass','component','point','process','model','decay','unit','initial-state'])
def test_typed_generator_target_refusals(tmp_path,change):
    d=f.fixture(tmp_path);cfg,target=f.generation(tmp_path,d)
    if change=='coordinate':target['coordinate_parameters'][0]['parameter']['indices']=[6]
    if change=='mass':target['mass_parameters'][0]['parameter']['indices']=[6]
    if change=='component':target['component_id']='other'
    if change=='point':target['point_identity_sha256']=d['points'][0]['identity']['sha256']
    if change=='process':target['process_card']=target['parameter_card']
    if change=='model':target['model_manifest']=target['parameter_card']
    if change=='decay':target['decay']={**target['decay'],'mode':'MADSPIN'}
    if change=='unit':target['coordinate_parameters'][0]['unit']='TeV'
    if change=='initial-state':target['beam_pdg']=[11,-11]
    set_config(tmp_path,d,cfg,target)
    with pytest.raises(ValueError):f.run(tmp_path,d)
    assert not (tmp_path/'output').exists()


def test_rehashed_coherent_wrong_mass_card_still_refuses_linked_point(tmp_path):
    d=f.fixture(tmp_path);cfg,target=f.generation(tmp_path,d)
    from svj_fixtures import write
    cfg['cards']['parameter']=write(tmp_path/'generator/param.dat','BLOCK MASS\n 1000024 601\nDECAY 1000024 0\n')
    target['parameter_card']=op.gen._generated_pin(cfg['cards']['parameter']['path'])
    set_config(tmp_path,d,cfg,target)
    with pytest.raises(ValueError,match='coordinate value'):f.run(tmp_path,d)


@pytest.mark.parametrize('unsupported',[None,'asymmetric','electron'])
def test_unknown_correspondence_or_beams_remain_complete_source_need(tmp_path,unsupported):
    d=f.fixture(tmp_path);cfg,target=f.generation(tmp_path,d)
    if unsupported is None:d['points'][1]['components'][0].pop('generation_target')
    else:
        from svj_fixtures import write
        if unsupported=='asymmetric':cfg['generation']['energy_gev']=[6000,7000]
        else:cfg['generation'].update(beam_type=[0,0],beam_pdg=[11,-11])
        run=Path(cfg['cards']['run']['path']).read_text()
        if unsupported=='asymmetric':run=run.replace('6500 = ebeam1','6000 = ebeam1').replace('6500 = ebeam2','7000 = ebeam2')
        else:run=run.replace('1 = lpp1','0 = lpp1').replace('1 = lpp2','0 = lpp2')
        cfg['cards']['run']=write(tmp_path/'generator/run.dat',run)
        for k in ('beam_type','beam_pdg','energy_gev'):target[k]=deepcopy(cfg['generation'][k])
        set_config(tmp_path,d,cfg,target)
    result=f.run(tmp_path,d)
    assert len(result['cells'])==8 and result['points'][1]['components'][0]['generation'] is None
    assert 'correspondence' in ' '.join(result['points'][1]['obligations'])
    assert not (tmp_path/'output/points/p1/associated/generation').exists()


@pytest.mark.parametrize('filename',['lifetime-trace.json','projected-workspace.json','template.json','workspace.json','contract.json','signal-template-input.json','inference-science.json'])
def test_all_new_owned_template_json_commits_before_emission(tmp_path,monkeypatch,filename):
    d=f.fixture(tmp_path,design='independent_Poisson_groups')
    pub,t=f.published(tmp_path/'published',[.25]*4);template=f.read(t)
    for ch in template['channels']:
        for sample in ch['samples']:sample['mc_stat']['sumw2']=[.0625]*2
    t=f.emit(tmp_path/'matching-template.json',template)
    d['cells'][0].update(published_model=pub,template=t,mc_interpretation='supplied_Poissonized_groups_and_source_MC_constraints')
    writer=op.atomic_json;seen=[]
    def changed(path,document):
        writer(path,document)
        if Path(path).name==filename:
            Path(path).write_text('{"foreign": true}\n');seen.append(str(path))
    monkeypatch.setattr(op,'atomic_json',changed)
    with pytest.raises(ValueError,match='generated recipe changed'):f.run(tmp_path,d)
    assert seen and not (tmp_path/'output/llp-plane-recipe.json').exists()


@pytest.mark.parametrize('filename',['science.json','preparation.json'])
def test_inherited_generation_commitment_not_recaptured_on_return(tmp_path,monkeypatch,filename):
    from ravel.workflow import model_event_plan
    d=f.fixture(tmp_path);f.generation(tmp_path,d);prepare=model_event_plan.prepare
    def changed(*args,**kwargs):
        result=prepare(*args,**kwargs)
        Path(kwargs['output_dir'],filename).write_text('{"foreign": true}\n')
        return result
    monkeypatch.setattr(model_event_plan,'prepare',changed)
    with pytest.raises(ValueError,match='generated recipe changed'):f.run(tmp_path,d)
    assert not (tmp_path/'output/llp-plane-recipe.json').exists()


def test_returned_receipt_and_every_persisted_commitment_match(tmp_path):
    d=f.fixture(tmp_path);f.generation(tmp_path,d)
    result=f.run(tmp_path,d)
    path=tmp_path/'output/llp-plane-recipe.json'
    assert path.read_bytes()==(json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
    for expected in result['output_inventory']:
        raw=Path(expected['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==expected['sha256'] and len(raw)==expected['size']
    assert len(result['cells'])==8 and result['execution_authorized'] is result['physics_validated'] is False
