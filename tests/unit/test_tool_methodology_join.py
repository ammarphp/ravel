"""Independent actual tool closure -> full meta packet/Graph, synthetic transport only."""
from pathlib import Path
import json
import pytest
from test_research_tools import compile_and_admit,no_external_calls
from test_research_protocol import make
from ravel.workflow import research_tools as tools,research_protocol as protocol,research_cycle as cycle,agent_host
from ravel.workflow.state_io import read_json
from test_research_cycle import write


def test_complete_canonical_tool_closure_reaches_actual_meta_model_content(tmp_path,monkeypatch):
 # Declare three synthetic Graph calls at fresh creation: materialize, admit, meta.
 # The two earlier ceiling refusals remain retained; no live budget is altered.
 import test_research_blueprint as blueprint_fixture
 original_contract=blueprint_fixture.contract
 def declared_source_contract(base):
  contract=original_contract(base)
  contract['budget']={**contract['budget'],'calls':3,'output_tokens':128}
  return contract
 monkeypatch.setattr(blueprint_fixture,'contract',declared_source_contract)
 root,bundle,result,api=compile_and_admit(tmp_path/'actual-tool',monkeypatch)
 old_evidence=cycle._current_evidence
 from ravel.workflow import research_followup
 old_feedback=research_followup._feedback_content
 fixture,definition=make(tmp_path/'prospective-protocol',monkeypatch)
 monkeypatch.setattr(cycle,'_current_evidence',old_evidence);monkeypatch.setattr(research_followup,'_feedback_content',old_feedback)
 # Bind a smaller prospectively declared source protocol inside the unchanged
 # six-experiment ceiling, retaining the existing required `paired` denominator.
 # No attempt or original policy is changed by this isolated packet fixture.
 definition['candidates']=[c for c in definition['candidates'] if c['id'] in {'original','changed'}]
 definition['cells']=[c for c in definition['cells'] if c['id'] in {'full-a','full-b'}]
 definition['stages']=[s for s in definition['stages'] if s['id'] in {'base-full','incumbent-full','new-full'}]
 for stage in definition['stages']:
  stage['requires']=[];stage['requires_stages']=[]
  for row in stage['cells']:row['experiment_id']='paired' if stage['candidate']=='changed' else 'repeat'
 definition['comparisons']=[c for c in definition['comparisons'] if c['id']=='full-contrast']
 definition['claims'][0]['stage_ids']=['incumbent-full','new-full'];definition['claims'][0]['comparison_ids']=['full-contrast']
 definition['required_stage_ids']=['incumbent-full','new-full'];definition['required_comparison_ids']=['full-contrast']
 definition['not_applicable']=[{'purpose':'screen','reason':'This pure packet presentation fixture has no scientific stage execution.'},{'purpose':'ablation','reason':'No methodological effectiveness or ablation evidence is inferred by this source packet test.'}]
 protocol.bind(root,write(tmp_path/'bound-protocol.json',definition))
 closure=tools.input_pins(bundle,tmp_path)
 experiments=cycle._load(root)[1]['experiments']
 assert all(all(p in e['input_pins'] for p in closure) for e in experiments)
 before=cycle._usage(cycle._load(root)[1]);prepared=protocol.prepare_meta_review(root,tmp_path/'meta-presentation',role='critic',model='explicit-synthetic-source-control',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10)
 spec=read_json(prepared['graph_spec']['path']);packet=Path(spec['nodes'][0]['packet']['path']);manifest=read_json(packet/'manifest.json')
 rows={row['source_path']:row for row in manifest['artifacts']};b=read_json(bundle['path']);required=[bundle,b['api_request'],b['api_context'],*b['source_inputs']]
 assert all(p in closure for p in required)
 for p in closure:
  row=rows[p['path']];assert row['projection']=='full_authenticated_source_or_evidence'
  assert (packet/row['path']).read_bytes()==Path(p['path']).read_bytes()
 observed=[];host=agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses')
 def response(data,parameters,message,control):
  payload=json.loads(data)['input'];serial=json.dumps(payload);observed.append(serial)
  assert 'def measure(records)' in serial
  for p in required:assert p['sha256'] in serial
  value={'kind':'research_meta_review','subject_sha256':prepared['context']['sha256'],'actor_id':prepared['actor_id'],'action':'report_only','affected_claim_ids':['complete-method'],'affected_stage_ids':[],'objections':[],'required_experiment_ids':[],'premise_revision':None,'resolves_meta_revisions':[],'replacement_stage_ids':[],'replacement_comparison_ids':[],'replacement_claim_ids':[]}
  return host._result(value,parameters,message,response_id='synthetic-meta-context-only',observed_model='explicit-synthetic-source-control',usage={'input_tokens':10,'output_tokens':10})
 monkeypatch.setattr(host,'_responses',response)
 outcome=cycle.execute_graph(root,prepared['graph_root'],spec,host);assert outcome['complete'] and observed
 after=cycle._usage(cycle._load(root)[1]);assert after['calls']==before['calls']+1
 assert not cycle.status(root)['parent_task_accepted']
 # A fresh packet cannot present an API that changed after its original context.
 Path(api['path']).write_text('def measure(records):\n return {"changed":True}\n')
 with pytest.raises(ValueError):protocol.prepare_meta_review(root,tmp_path/'stale-meta',role='verifier',model='explicit-synthetic-source-control',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10)
 assert cycle._usage(cycle._load(root)[1])==after
