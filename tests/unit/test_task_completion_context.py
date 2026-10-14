"""Whole-parent readiness producer controls; synthetic ordinary review evidence only.

No native science/model/network work is performed. Journal setup follows the
existing public task_completion controls. The new producer never creates a vote.
"""
from copy import deepcopy
from pathlib import Path
import pytest
import subprocess
import socket


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError("pure control attempted external/native/model execution")
    for name in ("Popen","run","check_output","call","check_call"):
        monkeypatch.setattr(subprocess,name,deny)
    monkeypatch.setattr(socket,"create_connection",deny)

from ravel.physics import task_completion_context as context
from ravel.workflow import task_completion as tc, scientific_report as sr
from ravel.workflow import scientific_judgment as judgment, physics_review as review
from ravel.workflow.state_io import read_json, atomic_json
from test_task_completion import goal, resolved, review_run, write
from test_scientific_report import fixture as report_fixture
from test_autonomy_final_results import package
from test_scientific_judgment import observed_role_boundary
from test_scientific_judgment import FakeHost


def prepared(base, monkeypatch):
    _,contract=goal(base)
    outcome=resolved(base,contract,monkeypatch)
    (base/'producer').mkdir()
    recipe=write(base/'producer/report-recipe.json',report_fixture(base/'producer'))
    ready={'schema_version':1,'contract':contract,'outcomes':[outcome], 'parent_review':None,'report':recipe}
    ready_pin=write(base/'producer/ready.json',ready)
    parent=base/'whole-parent'
    final={**deepcopy(ready),'parent_review':{'rundir':str(parent),'claim_scope':'original_task_completion'}}
    final_pin=write(base/'producer/final.json',final)
    task={'schema_version':1,'ready_request':ready_pin,'final_request':final_pin,'parent_review_root':str(parent),'completion_base':str(base/'producer')}
    return task, ready, final


def test_real_readiness_producer_keeps_parent_unaccepted_and_full_census(tmp_path,monkeypatch):
    task,ready,final=prepared(tmp_path,monkeypatch)
    before=tc.evaluate(task['ready_request'],base_dir=tmp_path/'producer')
    assert before['ready_for_parent_review'] and not before['parent_task_accepted']
    # The actual ordinary input base differs from the future review root.
    parent=Path(task['parent_review_root']);parent.mkdir()
    out=parent/'outputs/attempt-1/task-completion-context'
    value=context.run(task,tmp_path/'producer',out)
    assert value['parent_task_accepted'] is False and value['original_task_complete'] is False
    assert value['original_request']==before['original_request']
    assert value['obligation_census']==before['obligation_census']
    assert {p['path'] for p in value['input_pins']} >= {task['ready_request']['path'],task['final_request']['path'],ready['contract']['path'],ready['report']['path']}
    assert not (parent/'physics_review.json').exists()
    assert read_json(task['ready_request']['path'])==ready and read_json(task['final_request']['path'])==final
    with pytest.raises(ValueError,match='parent task remains open'):
        tc.require_final(task['ready_request'],base_dir=tmp_path/'producer')


@pytest.mark.parametrize('change',['contract','report','outcome','scope','root'])
def test_final_request_cannot_change_any_original_ready_field(tmp_path,monkeypatch,change):
    task,_,final=prepared(tmp_path,monkeypatch)
    if change=='contract':final['contract']={**final['contract'],'sha256':'0'*64}
    elif change=='report':final['report']=write(tmp_path/'foreign.json',{})
    elif change=='outcome':final['outcomes'][0]['coverage'][0]['explanation']='different'
    elif change=='scope':final['parent_review']['claim_scope']='diagnostic'
    else:final['parent_review']['rundir']=str(tmp_path/'foreign')
    task['final_request']=write(Path(task['final_request']['path']),final)
    with pytest.raises(ValueError,match='may add only'):
        context.inputs(task,tmp_path/'producer')


def test_contributing_child_cannot_be_reused_as_the_whole_parent_review(tmp_path,monkeypatch):
    task,ready,final=prepared(tmp_path,monkeypatch)
    root=ready['outcomes'][0]['rundir'];task['parent_review_root']=root
    final['parent_review']['rundir']=root;task['final_request']=write(Path(task['final_request']['path']),final)
    with pytest.raises(ValueError,match='contributor child review'):
        context.inputs(task,tmp_path/'producer')


@pytest.mark.parametrize('change',['missing','changed','open'])
def test_ready_context_requires_current_complete_input_sources(tmp_path,monkeypatch,change):
    task,ready,_=prepared(tmp_path,monkeypatch)
    source=Path(ready['outcomes'][0]['coverage'][0]['evidence'][0]['path'])
    if change=='missing':source.unlink()
    elif change=='changed':source.write_text('{}\n')
    else:
        ready['outcomes'][0]['coverage'][0]['state']='unknown'
        task['ready_request']=write(Path(task['ready_request']['path']),ready)
        final={**deepcopy(ready),'parent_review':{'rundir':task['parent_review_root'],'claim_scope':'original_task_completion'}}
        task['final_request']=write(Path(task['final_request']['path']),final)
    with pytest.raises((ValueError,OSError)):
        context.inputs(task,tmp_path/'producer')


def test_wrong_attempt_destination_cannot_publish_a_parent_context(tmp_path,monkeypatch):
    task,_,_=prepared(tmp_path,monkeypatch)
    out=tmp_path/'foreign/outputs/attempt-1/task-completion-context'
    with pytest.raises(ValueError,match='exact prospective'):
        context.run(task,tmp_path/'producer',out)
    assert not out.exists()


def test_output_mutation_during_ending_input_check_is_refused(tmp_path,monkeypatch):
    task,_,_=prepared(tmp_path,monkeypatch)
    parent=Path(task['parent_review_root']);parent.mkdir()
    out=parent/'outputs/attempt-1/task-completion-context'
    original=tc._Inputs.finish
    def ending(observed):
        target=out/'task-completion-context.json'
        if target.is_file():target.write_text('{}\n')
        return original(observed)
    monkeypatch.setattr(tc._Inputs,'finish',ending)
    with pytest.raises(ValueError):context.run(task,tmp_path/'producer',out)


def test_ready_context_to_actual_parent_review_ci3_and_public_final_consumer(tmp_path,monkeypatch, observed_role_boundary):
    task,ready,_=prepared(tmp_path,monkeypatch)
    parent=Path(task['parent_review_root']);parent.mkdir()
    out=parent/'outputs/attempt-1/task-completion-context'
    produced=context.run(task,tmp_path/'producer',out)
    context_pin=write(tmp_path/'context-record.json',produced)
    # Existing ordinary journals capture the exact prospective request and all
    # authenticated readiness inputs. Synthetic role evidence is not physics.
    # final_request is already in the full producer census. Preserve all
    # distinct paths, rather than declaring one ordinary input twice.
    review_run(parent,list(dict.fromkeys([task['final_request']['path'],context_pin['path'], *[p['path'] for p in produced['input_pins']]])),monkeypatch,scope='original_task_completion')
    with pytest.raises(ValueError,match='CHECK-IN 3'):
        tc.require_final(task['final_request'],base_dir=tmp_path/'producer')
    recipe=read_json(ready['report']['path']);recipe.update(task_completion=task['final_request'],delivery='final')
    draft=sr.prepare_final(recipe,base_dir=tmp_path/'producer')
    _,events=review._read(parent)
    manifest,value=package(parent,events[0])
    artifact_root=parent/'final-draft'
    write(artifact_root/'report.json',draft);write(artifact_root/'recipe.json',recipe)
    for row in value['artifacts']:
        current=write(Path(row['path']),read_json(row['path']))
        row.update({k:v for k,v in current.items() if k!='size'})
    for change,row in zip(value['changes_since_checkin2'],value['artifacts']):change['current_sha256']=row['sha256']
    manifest={k:v for k,v in write(Path(manifest['path']),value).items() if k!='size'}
    judgment.open_final_cycle(parent,manifest=manifest,check_results='inputs/checks-final.json')
    result=judgment.advance(parent,tmp_path/'final-roles',host=FakeHost(),model='control',reasoning_effort='high',
        max_output_tokens=1024,max_wall_seconds=20,claim_scope='original_task_completion',allow_control=True)
    assert result['phase']=='final_results_reviewed'
    accepted=tc.require_final(task['final_request'],base_dir=tmp_path/'producer')
    assert accepted['parent_task_accepted'] and accepted['original_request']==produced['original_request']
    assert accepted['final_results_review']['manifest']['sha256']==manifest['sha256']
    assert review._path(parent,accepted['final_results_review']['manifest']['path'])==Path(manifest['path'])
    assert not accepted['semantic_entailment_verified']
