"""Authored pure controls. NOT EXECUTED by the implementation author.

All manuscript/source/stage fixtures are deliberately synthetic engineering
examples. No provider, science process or scientific correctness is inferred.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest
from ravel.workflow import report_integrity as ri, scientific_report, scientific_judgment as sj
from ravel.workflow import execution, agent_graph, agent_host, state_io


def pin(path):
    raw = path.read_bytes()
    return {"path":str(path), "sha256":hashlib.sha256(raw).hexdigest(), "size":len(raw)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if type(value) is str else json.dumps(value, allow_nan=False)+"\n")
    return pin(path)


def span(text, start=0):
    return {"start":start, "end":start+len(text), "text":text}


def located(path, text):
    return {"artifact":pin(path), "format":"text", "location":span(text), "value":text}


def fixture(base):
    code = "def score(x):\n    return x*x\n"
    write(base/"score.py", code)
    primary = "Example Author (2020). Squared scores. Example DOI. This toy method squares x.\n"
    write(base/"primary.txt", primary)
    parts = [("claim", "A", "The supplied score is four [1].\n"),
             ("method", "B", "We square the supplied x [1]; no optimization is claimed.\n"),
             ("reference", "C", "[1] Example Author. Squared scores. 2020. Example DOI.\n")]
    text = "".join(p[2] for p in parts); units = []; cursor=0
    for kind, identity, value in parts:
        units.append({"id":identity, "kind":kind, "span":span(value,cursor)}); cursor+=len(value)
    manuscript = write(base/"manuscript.md", text)
    result = write(base/"result.json", {"score":4})
    occurrences=[]
    for unit in units[:2]:
        start=text.index("[1]",unit["span"]["start"])
        occurrences.append({"unit_id":unit["id"], "span":span("[1]",start)})
    return {"schema_version":1, "document_type":"manuscript", "applicability":"Synthetic manuscript audit; no scientific or provider execution.",
        "author_id":"writer", "manuscript":manuscript, "units":units,
        "claims":[{"id":"score", "unit_ids":["A"], "statement":"The supplied score is four, without a physics claim.",
            "evidence":[{"artifact":result,"format":"json","location":"/score","value":4}],
            "citation_ids":["reference"], "method_ids":["square"], "uncertainties":["Synthetic source only."]}],
        "methods":[{"id":"square", "unit_ids":["B"], "description":"Square supplied x, no fit.",
            "operations":[{"id":"evaluate", "description":"Invoke score(x).", "code":[located(base/"score.py",code)],
                "execution":None, "results":[{"artifact":result,"format":"json","location":"/score","value":4}],
                "differences":["No native execution has occurred in this fixture."]}],
            "citation_ids":["reference"], "uncertainties":[]}],
        "citations":[{"id":"reference", "reference_unit":"C", "bibliography":{"title":"Squared scores", "authors":["Example Author"],
            "year":"2020", "identifiers":["Example DOI"]}, "identity_evidence":[{"source_role":"primary-paper", "source_url":"https://example.invalid/primary",
            "located":located(base/"primary.txt",primary)}], "occurrences":occurrences, "uncertainties":["Fabricated engineering source, not a real paper."]}],
        "quantitative_report":None}


def test_whole_character_claim_method_reference_census_and_actual_content(tmp_path):
    r=fixture(tmp_path); p=ri.prepare(r,base_dir=tmp_path)
    assert {i['id'] for i in p['items']}=={'claim.score','method.square','operation.square.evaluate','citation.reference'}
    assert p['items'][1]['presented_code'][0]['value']=='def score(x):\n    return x*x\n'
    assert p['items'][1]['execution']['state']=='execution_evidence_missing'
    assert not any(p[k] for k in ('semantic_census_verified','bibliography_verified','method_equivalence_verified','scientific_acceptance','execution_authorized'))


@pytest.mark.parametrize('change', ['gap','overlap','truncated','missing-claim','missing-method','missing-reference','duplicate-owner'])
def test_full_population_cannot_be_silently_narrowed(tmp_path,change):
    r=fixture(tmp_path)
    if change=='gap':r['units'][1]['span']['start']+=1
    elif change=='overlap':r['units'][1]['span']['start']-=1
    elif change=='truncated':r['units'].pop()
    elif change=='missing-claim':r['claims']=[]
    elif change=='missing-method':r['methods']=[]
    elif change=='missing-reference':r['citations']=[]
    else:r['claims'].append({**deepcopy(r['claims'][0]),'id':'second'})
    with pytest.raises(ValueError):ri.prepare(r,base_dir=tmp_path)


@pytest.mark.parametrize('change',['foreign-method','foreign-citation','wrong-source-value','outside-occurrence','duplicate-id','private-source','symlink'])
def test_located_applicability_and_missing_source_adversaries(tmp_path,change):
    r=fixture(tmp_path)
    if change=='foreign-method':r['claims'][0]['method_ids']=['unknown']
    elif change=='foreign-citation':r['methods'][0]['citation_ids']=['unknown']
    elif change=='wrong-source-value':r['claims'][0]['evidence'][0]['value']=5
    elif change=='outside-occurrence':r['citations'][0]['occurrences'][0]['unit_id']='B'
    elif change=='duplicate-id':r['citations'].append(deepcopy(r['citations'][0]))
    elif change=='private-source':(tmp_path/'primary.txt').unlink()
    else:
        (tmp_path/'primary.txt').rename(tmp_path/'original.txt');(tmp_path/'primary.txt').symlink_to(tmp_path/'original.txt')
    with pytest.raises((ValueError,FileNotFoundError)):ri.prepare(r,base_dir=tmp_path)


def test_matching_metadata_and_wrong_declared_method_do_not_prove_truth(tmp_path):
    r=fixture(tmp_path);r['methods'][0]['description']='We optimize a global likelihood.'
    r['citations'][0]['bibliography']['title']='A different title'
    p=ri.prepare(r,base_dir=tmp_path)
    # Content reaches the reviewer unchanged; no keyword/hash truth gate.
    assert p['items'][2]['declared']['description']=='We optimize a global likelihood.'
    assert p['items'][3]['declared']['bibliography']['title']=='A different title'
    assert not p['method_equivalence_verified'] and not p['bibliography_verified']


def test_other_classification_is_presented_for_fresh_semantic_census_audit(tmp_path):
    r=fixture(tmp_path);r['units'][0]['kind']='other';r['claims']=[]
    p=ri.prepare(r,base_dir=tmp_path)
    assert p['units'][0]['span']['text']=='The supplied score is four [1].\n'
    assert p['semantic_census_verified'] is False
    assert 'complete census/classification' in p['review_instructions']


def test_all_original_sources_rechecked_after_preparation(tmp_path,monkeypatch):
    r=fixture(tmp_path);real=ri.execution.file_hash
    def late(path):
        result=real(path);(tmp_path/'primary.txt').write_text('late mutation');return result
    monkeypatch.setattr(ri.execution,'file_hash',late)
    with pytest.raises(ValueError,match='changed'):ri.prepare(r,base_dir=tmp_path)


def test_generated_audit_cannot_recapture_late_writer_mutation(tmp_path,monkeypatch):
    r=fixture(tmp_path);real=ri.state_io.atomic_json
    def late(path,value):
        real(path,value)
        if Path(path).name=='presentation.json':
            value['bibliography_verified']=True;real(path,value)
    monkeypatch.setattr(ri.state_io,'atomic_json',late)
    with pytest.raises(ValueError,match='changed|differs'):ri.materialize(r,tmp_path/'audit',base_dir=tmp_path)


def test_full_case_and_unreviewed_public_anchors_use_existing_schema(tmp_path):
    r=fixture(tmp_path);out=ri.materialize(r,tmp_path/'audit',base_dir=tmp_path)
    case=json.loads(Path(out['case']['path']).read_text())
    assert len(case['nodes'])==5 and len(case['edges'])==4
    assert all(n['material'] and n['review']['decision']=='unresolved' for n in case['nodes'])
    ri.decision_case.validate_case(case)
    unreviewed=sj._unreviewed(case)
    assert all('review' not in n for n in unreviewed['nodes'])
    assert unreviewed['nodes'][0]['anchors'][0]['value']['bibliography_verified'] is False


def stage(base, request):
    """Actual durable execution API, inert process identity; no process started."""
    op=request['methods'][0]['operations'][0]
    source=base/'score.py'; output=base/'returned.json'
    specification=execution.plan_stage(base,'arithmetic',[sys.executable,'-c','pass'],[str(source)],[str(output)],[],str(base))
    record=execution.begin_attempt(base,'arithmetic',specification,'logs/supervisor.log')
    output.write_text('{"score":4}\n');(base/'logs/supervisor.log').write_text('Synthetic inert returned value.\n')
    execution.finish_attempt(base,record,0)
    record=execution.load_execution(base)['stages']['arithmetic']
    op['results']=[{'artifact':pin(output),'format':'json','location':'/score','value':4}]
    op['execution']={'rundir':str(base),'receipt':pin(execution.resolve_path(base,record['attempt_record']))}
    return record


def test_current_same_stage_source_result_custody_not_runtime_or_equivalence(tmp_path):
    r=fixture(tmp_path);record=stage(tmp_path,r)
    p=ri.prepare(r,base_dir=tmp_path);op=p['items'][1]
    assert op['execution']['attempt_id']==record['attempt_id']
    assert op['execution']['declared_stage_input_join_checked']
    assert not op['execution']['runtime_consumption_verified'] and not p['method_equivalence_verified']


def test_source_outside_actual_execution_inputs_cannot_be_claimed_consumed(tmp_path):
    r=fixture(tmp_path);stage(tmp_path,r)
    raw='def score(x):\n    return x*x\n';write(tmp_path/'other.py',raw)
    r['methods'][0]['operations'][0]['code']=[located(tmp_path/'other.py',raw)]
    with pytest.raises(ValueError,match='same stage'):ri.prepare(r,base_dir=tmp_path)


def test_changed_executed_source_or_current_stage_refuses(tmp_path):
    r=fixture(tmp_path);stage(tmp_path,r);(tmp_path/'score.py').write_text('changed')
    with pytest.raises(ValueError):ri.prepare(r,base_dir=tmp_path)


def test_failed_receipt_is_presented_as_diagnostic_not_success(tmp_path):
    r=fixture(tmp_path)
    source=tmp_path/'score.py';spec=execution.plan_stage(tmp_path,'arithmetic',[sys.executable,'-c','pass'],[str(source)],[str(tmp_path/'never.json')],[],str(tmp_path))
    record=execution.begin_attempt(tmp_path,'arithmetic',spec,'logs/supervisor.log');(tmp_path/'logs/supervisor.log').write_text('Synthetic retained failure.\n')
    execution.finish_attempt(tmp_path,record,2)
    record=execution.load_execution(tmp_path)['stages']['arithmetic']
    r['methods'][0]['operations'][0]['execution']={'rundir':str(tmp_path),'receipt':pin(execution.resolve_path(tmp_path,record['attempt_record']))}
    p=ri.prepare(r,base_dir=tmp_path)
    assert p['items'][1]['execution']['state']=='failed_or_incomplete_retained_stage'
    assert not p['scientific_acceptance']


def test_draft_has_complete_pending_census_and_final_cannot_borrow_hashes(tmp_path):
    r=fixture(tmp_path);out=scientific_report.manuscript(r,base_dir=tmp_path)
    assert out['delivery']=='draft' and len(out['integrity']['item_census'])==4
    assert not out['integrity']['complete_actual_independent_roles']
    with pytest.raises(ValueError,match='actual ordinary'):scientific_report.manuscript(r,base_dir=tmp_path,final=True)


def test_arithmetic_task_is_not_given_universal_manuscript_roles(tmp_path):
    r=fixture(tmp_path);r['document_type']='arithmetic'
    with pytest.raises(ValueError,match='arithmetic reports keep'):ri.prepare(r,base_dir=tmp_path)
    assert 'manuscript_integrity' not in scientific_report.compose.__code__.co_varnames


def graph_node(base, request):
    path=base/'request.json';write(path,request)
    pins=[pin(path),*ri.input_pins(request,base_dir=base)]
    inputs=[{'id':'request' if i==0 else 'basis'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(pins)]
    return {'id':'prepare','kind':'tool','role':'proposer','depends_on':[],'inputs':inputs,'packet':None,
        'action':'manuscript-integrity','parameters':{'request_input':'request'},'max_attempts':1}


def test_actual_ordinary_graph_host_tool_is_connected_and_charged(tmp_path):
    request=fixture(tmp_path);n=graph_node(tmp_path,request)
    spec={'schema_version':1,'graph_id':'manuscript','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1024,'max_wall_seconds':20,'max_reworks':0},'nodes':[n]}
    root=tmp_path/'graph';agent_graph.create(root,spec)
    result=agent_graph.execute(root,agent_host.AgentHost(api_key='unused-synthetic-key'))
    attempts=list((root/'attempts').glob('*.json'))
    assert len(attempts)==1
    assert result['complete'] is True
    assert result['nodes']['prepare']['status']=='completed'
    assert not list((root/'calls').glob('*.json'))==[]
    raw=json.loads(attempts[0].read_text());assert raw['result']['value']['kind']=='manuscript_integrity_preparation'


@pytest.mark.parametrize('role',['critic','verifier'])
def test_host_preparation_does_not_impersonate_blinded_reviewer(tmp_path,role):
    r=fixture(tmp_path);n=graph_node(tmp_path,r);n['role']=role
    class C:
        def check_cancelled(self):pass
        def cancelled(self):return False
        def call(self,*args,**kwargs):return args[3]()
    req={'request_id':'a'*64,'input_artifacts':n['inputs'],'packet':None}
    with pytest.raises(agent_host.HostFailure):agent_host.AgentHost(api_key='unused').execute(n,req,C())


def test_all_source_inputs_must_reach_actual_host(tmp_path):
    r=fixture(tmp_path);n=graph_node(tmp_path,r);n['inputs']=[n['inputs'][0]]
    class C:
        def check_cancelled(self):pass
        def cancelled(self):return False
        def call(self,*args,**kwargs):return args[3]()
    req={'request_id':'a'*64,'input_artifacts':n['inputs'],'packet':None}
    with pytest.raises(agent_host.HostFailure,match='missing/changed'):agent_host.AgentHost(api_key='unused').execute(n,req,C())


def test_case_sources_current_dependency_requirement_is_not_optional(tmp_path,monkeypatch):
    r=fixture(tmp_path);p=ri.materialize(r,tmp_path/'audit',base_dir=tmp_path)
    case=json.loads(Path(p['case']['path']).read_text())
    verified={'contract':{'case_pin':{k:p['case'][k] for k in ('path','sha256')},'actor_id':'critic','source_pins':[]}}
    monkeypatch.setattr(sj,'verify_binding',lambda b:verified)
    with pytest.raises(ValueError,match='every original case'):ri._verified(r,{},tmp_path)


@pytest.mark.parametrize('change',['omitted','context-only','false-assertion','changed-edge'])
def test_fresh_case_cannot_silently_replace_full_population(tmp_path,monkeypatch,change):
    r=fixture(tmp_path);p=ri.materialize(r,tmp_path/'audit',base_dir=tmp_path)
    case=json.loads(Path(p['case']['path']).read_text())
    if change=='omitted':case['nodes'].pop();case['edges'].pop()
    elif change=='context-only':case['nodes'][1]['material']=False
    elif change=='false-assertion':case['nodes'][1]['assertion']='This is proven true.'
    else:case['edges'][0]['rationale']='Invented causal equivalence.'
    case_pin=write(tmp_path/'altered-case.json',case)
    verified={'contract':{'case_pin':{k:case_pin[k] for k in ('path','sha256')},'actor_id':'critic','source_pins':[]}}
    monkeypatch.setattr(sj,'verify_binding',lambda b:verified)
    with pytest.raises(ValueError,match='omit/downgrade/reinterpret'):ri._verified(r,{},tmp_path)


def test_nonvoting_missing_evidence_and_sendback_use_existing_consumer(tmp_path,monkeypatch):
    r=fixture(tmp_path);calls=[]
    monkeypatch.setattr(ri,'_verified',lambda *a:({}, {'contract':{'rundir':str(tmp_path)}}))
    monkeypatch.setattr(sj,'consume',lambda root,binding:calls.append((root,binding)) or {'kind':'scientific_evidence_request'})
    value=ri.consume_role(r,{'same':'binding'},base_dir=tmp_path)
    assert value['kind']=='scientific_evidence_request' and calls==[(str(tmp_path),{'same':'binding'})]
    # This is a disclosed delegate join, not a fresh actual role or live vote.
