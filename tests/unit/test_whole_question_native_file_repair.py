"""Actual stage substitutions with inert declared model assets; no native calls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.physics.ma5_pad import InputCapture
from ravel.workflow import stage_correspondence as correspondence, resonance_study as rs, science
from test_whole_question_stage_correspondence import generation_recipe, write, pin, no_execution
from test_native_likelihood import fixture as native_fixture


def native_case(base, monkeypatch, changed=False):
    path, recipe = generation_recipe(base/'source')
    root = base/'native'; root.mkdir()
    cp, doc, _, _, _ = native_fixture(root)
    shape = root/'shape-original.root'; shape.write_bytes(b'Inert complete declared template identity A\n')
    doc['model']['files'].append({**pin(shape), 'staged_path':'source/shapes.root'})
    write(cp, doc)
    old = next(s for s in recipe['stages'] if s['role']=='constraint' and s['hypothesis']=='H0')
    spec=json.loads(Path(old['study']['path']).read_text())
    spec.update(mode='native-likelihood', task={'input':str(cp)}, max_seconds=doc['max_seconds']+60)
    stage=deepcopy(old); stage['study']=write(root/'study.json',spec)
    stage['documents']=[{'id':'native_config','task_key':'input','source':pin(cp)}]
    generation=next(s for s in recipe['stages'] if s['id']=='generate_H0')
    generation['exports']['template']='shape.root'
    stage['links']=[{'document':'native_config','pointer':'/model/files/1',
                    'from_stage':generation['id'],'export':'template'}]
    h=next(h for h in recipe['hypotheses'] if h['id']=='H0'); search=recipe['searches'][0]
    stage['target_mapping']=write(root/'mapping.json',{'schema_version':2,'original_study':stage['study'],
        'hypothesis_sha256':rs._digest(h),'search_sha256':rs._digest(search),
        'projected_target':correspondence.project(spec,root,InputCapture()),
        'bindings':[],'sources':[h['model']],'limitations':[]})
    recipe['stages'][recipe['stages'].index(old)]=stage; write(path,recipe)
    out=base/'inert-predecessor/outputs'; out.mkdir(parents=True)
    moved=out/'shape.root'; moved.write_bytes(b'Inert complete declared template identity B\n' if changed else shape.read_bytes())
    header=write(out.parent/'handoff.json',{'request':pin(path)})
    monkeypatch.setattr(rs,'_accepted',lambda *a:(out.parent,{'resonance_handoff':header['path']},
        {'template':pin(moved)},{'explicit_inert_review_boundary':True},out,{moved},False))
    monkeypatch.setattr(rs,'_finish_accepted',lambda rows,c:c.finish())
    return path,stage,spec,doc,moved,out.parent


@pytest.mark.parametrize('changed',[False,True])
def test_real_stage_spec_compares_noncard_template_identity(tmp_path,monkeypatch,changed):
    path,stage,spec,doc,moved,rd=native_case(tmp_path,monkeypatch,changed)
    if changed:
        with pytest.raises(ValueError,match='operative stage target/source population'):
            rs.prepare_stage(path,stage['id'],{'generate_H0':str(rd)},tmp_path/'refused')
        assert not (tmp_path/'refused/science.json').exists()
    else:
        prepared=rs.prepare_stage(path,stage['id'],{'generate_H0':str(rd)},tmp_path/'prepared')
        effective=json.loads(Path(prepared['specification']['path']).read_text())
        config=json.loads(Path(effective['task']['input']).read_text())
        assert config['model']['files'][1]=={**pin(moved),'staged_path':'source/shapes.root'}
        science.plan(tmp_path/'ordinary',prepared['specification']['path'])
        science.verify_plan(tmp_path/'ordinary',approved=False)
        assert not (tmp_path/'ordinary'/science.APPROVAL).exists()


@pytest.mark.parametrize('fault',['digest','staged_name','order','removed','added'])
def test_ordered_full_model_identity_refuses_all_population_changes(tmp_path,monkeypatch,fault):
    path,stage,spec,doc,moved,rd=native_case(tmp_path,monkeypatch)
    original=correspondence.project(spec,Path(spec['task']['input']).parent,InputCapture())
    assert original['facts']['model_files']==[{k:r[k] for k in ('sha256','staged_path')} for r in doc['model']['files']]
    changed=deepcopy(original); files=changed['facts']['model_files']
    if fault=='digest':files[1]['sha256']='f'*64
    elif fault=='staged_name':files[1]['staged_path']='source/other.root'
    elif fault=='order':files.reverse()
    elif fault=='removed':files.pop()
    else:files.append({'sha256':'a'*64,'staged_path':'source/added.root'})
    with pytest.raises(ValueError,match='operative stage target/source population'):
        correspondence.same_target(original,changed)
    relocated=deepcopy(original)
    for row in relocated['transport']['model_files']:row['path']='/authenticated/relocated/'+row['staged_path']
    correspondence.same_target(original,relocated)
