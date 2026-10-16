"""Real canonical custody over harmless large files; no scientific dispatch."""
from copy import deepcopy
import json,sys
from pathlib import Path
from types import SimpleNamespace
import time
import pytest
from ravel.workflow import execution, failed_stage_review as failed, research_cycle as cycle, research_protocol as proto, research_presentation as material, physics_review, agent_host, state_io
from test_research_protocol import make,no_process
from test_research_cycle import write
from ravel.workflow import agent_graph


def native_failure(base,n=8974):
    root=base/'retained-native';(root/'inputs').mkdir(parents=True);(root/'outputs').mkdir()
    for i in range(n):(root/'inputs'/(str(i).zfill(6)+'x'*194+'.dat')).write_bytes(b'native source control\n')
    policy={'schema_version':1,'actors':{'proposer':'author','executor':'worker','physics_critic':'critic','skeptical_verifier':'verifier','physics_decider':'decider'},
        'allowed_changed_paths':[],'allowed_stages':['science'],'max_redos':0,'required_checks':[{'id':'custody','kind':'integrity'}],
        'claim_scopes':{'diagnostic':{'checks':['custody'],'actions':['delivery','reuse']}}}
    state_io.atomic_json(root/physics_review.POLICY,policy)
    inputs=['inputs',physics_review.POLICY]
    spec={'command':[sys.executable,'never-dispatched.py'],'cwd':str(root),'inputs':inputs,'outputs':['outputs'],'parents':{},
        'input_snapshot':execution.snapshot(root,inputs),'runtime':execution.runtime_context(),
        'operation_resources':{'schema_version':1,'kind':'solver','generated_events':0,'solver_evaluations':1,'max_seconds':30}}
    spec['fingerprint']=execution.digest(spec)
    record=execution.begin_attempt(root,'science',spec,'logs/worker.log')
    (root/'logs/worker.log').write_text('Explicit synthetic retained execution failure; no command dispatched.\n')
    assert execution.finish_attempt(root,record,3,'explicit inert infrastructure error')==3
    request={'schema_version':1,'stage_receipt':{k:cycle._pin(root/record['attempt_record'])[k] for k in ('path','sha256')},
        'failure_kind':'infrastructure_failure','result':None,'evidence':[{**{k:cycle._pin(root/'logs/worker.log')[k] for k in ('path','sha256')},'location':'complete inert failure log'}],
        'required_returned_outputs':['outputs/never-returned-result.json','outputs/never-returned-quantity.json']}
    doc=failed.intake(request,base_dir=root);pin=write(base/'intake.json',doc)
    return root,pin,doc


def test_real_large_canonical_import_current_custody_and_bounded_protocol_host(tmp_path,monkeypatch):
    # This checks large-file custody, not elapsed time. Scope a fixed wall clock
    # to the campaign and Graph modules; keep real monotonic receipt durations.
    clock = SimpleNamespace(time=lambda: 1000.0, monotonic=time.monotonic)
    monkeypatch.setattr(cycle, 'time', clock)
    monkeypatch.setattr(agent_graph, 'time', clock)
    root,p=make(tmp_path,monkeypatch)
    original=monkeypatch.undo
    # make's synthetic successful-evidence seam must not cover this canonical failure.
    from test_research_protocol import cycle as same_cycle
    source=Path(cycle.__file__).read_text()
    import ast
    module=ast.parse(source);node=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='_current_evidence')
    ns=vars(cycle).copy();exec(compile(ast.Module(body=[node],type_ignores=[]),str(cycle.__file__),'exec'),ns)
    monkeypatch.setattr(cycle,'_current_evidence',ns['_current_evidence'])
    prior,intake,doc=native_failure(tmp_path)
    assert intake['size']>2_000_000 and len({r['path'] for r in failed._files(doc['source_inputs'])})==8975
    with pytest.raises(ValueError):cycle._read(intake,tmp_path)
    imported=cycle.import_failed_stage(root,'failed-native',intake,premise_ids=['pairing'],predictions={'loss':None},
        historical_cost={'calls':0,'output_tokens':0,'wall_seconds':30,'native_attempts':1})
    e=imported['experiments'][0]
    assert e['input_pins']==[intake] and cycle._pin(root/'history'/f"{imported['revision']:04d}.json")['size']<2_000_000
    cycle._current_evidence(imported,e)
    with pytest.raises(ValueError,match='never grants'):cycle._current_evidence(imported,e,accepted=True)
    graph=tmp_path/'status-graph'
    prepared=proto.prepare_host_request(root,'status',{},graph,tmp_path/'host',presentation='indexed')
    assert len(prepared['inputs'])==3
    commitment=material.document(prepared['inputs'][2],tmp_path,material.MAX_INVENTORY_BYTES)
    inventory=material.document(commitment['inventory'],tmp_path,material.MAX_INVENTORY_BYTES)
    assert inventory['file_count']>8975 and len(inventory['missing_output_obligations'])==2
    assert imported['resource_ledger'][-1]['ceiling']['native_attempts']==1
    raw=state_io.read_json(prepared['inputs'][1]['path'])
    assert raw['actual_feedback'][0]['failed_material']['result'] is None
    assert raw['actual_feedback'][0]['failed_material']['returned_output_obligations'][0]['status']=='missing'
    inputs=[{'id':'p'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(prepared['inputs'])]
    spec={'schema_version':1,'graph_id':'whole-native-status','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},
        'nodes':[{'id':'status','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,'action':'research-protocol','parameters':{'request_input':'p0'},'max_attempts':1}]}
    result=cycle.execute_graph(root,graph,spec,agent_host.AgentHost())
    assert result['complete'],result
    manifest=proto.prepare_meta_review(root,tmp_path/'meta',role='critic',model='inert',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10,presentation='indexed')
    assert len(state_io.read_json(manifest['graph_spec']['path'])['nodes'][0]['inputs'])==0
    # Fresh Host consumption refuses a self-rebound external inventory even
    # when its small normal input commitments are all recomputed consistently.
    request=state_io.read_json(prepared['request']['path'])
    altered=deepcopy(inventory);altered['files'][0]['origins']=['forged origin']
    foreign=write(tmp_path/'rebound-inventory.json',altered)
    foreign_commit=write(tmp_path/'rebound-commitment.json',{'schema_version':1,'kind':'protocol_inventory_commitment',
        'inventory':foreign,'content_read_by_reviewer':False})
    request['inventory']=foreign;request['inventory_commitment']=foreign_commit
    with pytest.raises(ValueError,match='whole current evidence'):
        proto.host_prepare(request,presented_pins=[prepared['inputs'][1],foreign_commit],base_dir=tmp_path)
    first=Path(failed._files(doc['source_inputs'])[0]['path']);original_bytes=first.read_bytes();first.unlink()
    with pytest.raises(ValueError):cycle._current_evidence(imported,e)
    first.write_bytes(original_bytes)
    first.write_bytes(b'changed original source')
    with pytest.raises(ValueError):cycle._current_evidence(imported,e)


@pytest.mark.parametrize('change',['noncanonical','foreign','oversized'])
def test_large_typed_failure_does_not_authorize_foreign_or_noncanonical(tmp_path,monkeypatch,change):
    value={'schema_version':1,'kind':'failed_stage_diagnostic_intake','run_dir':str(tmp_path), 'padding':'x'*2_000_001}
    if change=='oversized':value['padding']='x'*(16*1024**2)
    if change=='foreign':value['kind']='other_large_json'
    pin=write(tmp_path/'foreign.json',value)
    if change in {'foreign','oversized'}:
        with pytest.raises(ValueError):cycle._read_failed_intake(pin,tmp_path)
    else:
        from ravel.workflow import failed_stage_review
        with pytest.raises(ValueError):failed_stage_review.verify(cycle._read_failed_intake(pin,tmp_path),base_dir=tmp_path)
