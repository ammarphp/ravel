"""Prospective software controls: AUTHOR HAS NOT IMPORTED OR RUN THESE.

The real Graph external-delivery/author verifier and ordinary plan consumer run
on disclosed synthetic text/runtime bytes. Inherited report/campaign fixture
hooks are synthetic; no provider, TeX, native worker or scientific vote occurs.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest
from ravel.physics import manuscript_build as mb, reinterpret_db
from ravel.workflow import execution as e, manuscript_production as mp
from ravel.workflow import publication_runtime as pr, science, route_prompt, task_completion as tc
from test_external_writer_accounting import author
from test_publication_runtime_v2 import request, LIMITS, put, pin
from test_physics_review import policy


@pytest.mark.parametrize('contract_directory', ['parent', 'parent/inputs'])
def test_child_registration_creates_ledger_in_bound_parent(tmp_path, contract_directory):
    """A supplied parent contract may precede the ordinary inputs directory."""
    prompt = 'Calculate the supplied quantity.'
    contract = route_prompt.route(prompt)
    requirements = tc.initial_requirements(prompt)
    requirements['assignments'] = [{'id': 'quantity', 'purpose': 'Calculate the quantity.',
        'coverage': [{'obligation_id': row['id'], 'criteria': deepcopy(row['criteria'])}
                     for row in requirements['obligations']]}]
    contract['task_requirements'] = requirements
    parent_pin = put(tmp_path / contract_directory / 'task_contract.json', contract)
    binding = {'contract': parent_pin, 'assignment_id': 'quantity'}
    child = tmp_path / 'child'
    put(child / science.SPEC, {'goal_binding': binding})
    entry = tc.register_child(child, binding, run_kind='science')
    assert tc.register_child(child, binding, run_kind='science') == entry
    ledger = tmp_path / 'parent/inputs/children.jsonl'
    assert [json.loads(line) for line in ledger.read_text().splitlines()] == [entry]
    assert not (tmp_path / 'inputs/children.jsonl').exists()


def prepared(root,monkeypatch):
    req,state,binding,value,response=author(root/'authorship',monkeypatch)
    collected=mp.collect(binding,root/'manuscript')
    request_pin,out,source,_=request(root/'runtime-source')
    snapshot=pr.materialize(request_pin,out)
    runtime={'schema_version':2,'engine':'pdflatex','purpose':'qualification','max_ram_mib':512,
        **{k:snapshot[k] for k in ('compiler','pdfinfo','svg_converter','asset_trees','closure_manifest',
                                 'environment','platform','snapshot_root')}}
    # A real task contract is distinct from synthetic campaign/report hooks.
    prompt=Path(req['original_task']['path']).read_text()
    contract=route_prompt.route(prompt);requirements=tc.initial_requirements(prompt)
    requirements['assignments']=[{'id':'publication-build','purpose':'Bound the full synthetic engineering PDF preparation.',
        'coverage':[{'obligation_id':r['id'],'criteria':deepcopy(r['criteria'])} for r in requirements['obligations']]}]
    contract['task_requirements']=requirements
    goal={'contract':put(root/'parent/task_contract.json',contract),'assignment_id':'publication-build'}
    p=policy();p.update(max_redos=0,allowed_changed_paths=[],allowed_stages=['science'])
    p['claim_scopes']={mb.SCOPE:{'checks':['integrity'],'actions':['delivery']}}
    review={'schema_version':1,'policy':p,'correction_contract':{'task_fields':[],'input_slots':[]}}
    def forbidden(*a,**k):raise AssertionError('Software control may not run a native/science effect')
    monkeypatch.setattr(reinterpret_db,'execute_native',forbidden)
    monkeypatch.setattr(mb,'run',forbidden)
    monkeypatch.setattr(science,'run',forbidden)
    result=mp.prepare_build(collected['package_pin'],root/'build',base_dir=out,runtime=runtime,
        review_policy=review,goal_binding=goal,max_seconds=30,custody_limits=LIMITS,approval_mode='scripted_yes')
    spec=json.loads(Path(result['specification']['path']).read_text());rd=root/'build/ordinary'
    return {'root':root,'rd':rd,'task':spec['task'],'spec':spec,'base':out,'runtime':runtime,
        'response':response,'binding':binding,'state':state,'package':collected['package'],'result':result}


def session(f):return e._validation_session(f['rd'])


def runtime_proofs(s):
    return [v for k,v in s.proofs.items() if type(k) is tuple and k and k[0]=='publication-unqualified-runtime-proof/v1']


def test_key_keeps_bool_integer_and_container_types_distinct():
    assert pr._typed_proof_key(True)!=pr._typed_proof_key(1)
    with pytest.raises(TypeError):pr._typed_proof_key(('not-a-list',))
