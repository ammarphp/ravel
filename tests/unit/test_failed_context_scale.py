"""Bounded presentation/Graph controls, synthetic transport only."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import pytest
import sys
from ravel.workflow import execution, failed_stage_review as f, review_context as r, scientific_judgment as j, agent_host as h, agent_graph as g
from ravel.workflow.state_io import atomic_json
from test_failed_stage_review import case, pin


@pytest.fixture
def unreviewed_case(tmp_path):
    """A failed ordinary stage whose run holds neither a review policy nor a science plan.

    The packet reader presents located evidence only from a run that is outside every retained
    scientific producer namespace. A run that keeps a review policy without its science plan is
    such a namespace and is refused; `case` has that layout and covers the refusal below.
    """
    root = tmp_path / "unreviewed" / "run"
    (root / "inputs").mkdir(parents=True)
    (root / "outputs").mkdir()
    source = root / "inputs/source.py"
    source.write_text("# harmless fixture, never executed\nvalue = 1\n")
    inputs = ["inputs/source.py"]
    spec = {"command": [sys.executable, "inputs/source.py"], "cwd": str(root), "inputs": inputs,
            "outputs": ["outputs"], "parents": {},
            "input_snapshot": execution.snapshot(root, inputs), "runtime": execution.runtime_context()}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "science", spec, "logs/worker.log")
    atomic_json(root / "outputs/result.json", {"status": "unresolved", "physics_validated": False,
        "fatal": None, "custody_refusal": None, "returned": 4, "machine_passed": 3})
    atomic_json(root / "outputs/raw.json", {"score": 0.004, "failure": "bounded line search"})
    (root / "logs/worker.log").write_text("engineering fixture retained failure\n")
    assert execution.finish_attempt(root, record, 2, "exit-2") == 2
    request = {"schema_version": 1, "stage_receipt": pin(root / record["attempt_record"]),
        "failure_kind": "scientific_unresolved", "result": pin(root / "outputs/result.json"),
        "evidence": [{**pin(root / "outputs/result.json"), "location": "$.returned"},
                     {**pin(root / "outputs/raw.json"), "location": "$.failure"}],
        "required_returned_outputs": ["outputs/result.json", "outputs/raw.json"]}
    return root, record, request


def expanded(case, monkeypatch):
    root, _, request = case
    doc = f.intake(request, base_dir=root)
    # Projection-only synthetic census; this explicitly does not establish live custody.
    for n in range(9000):
        doc['source_inputs'][str(root/'unexecuted-synthetic-source-population'/f'{n:06d}.py')] = {
            'kind':'file','files':[{'name':'.','size':1,'sha256':'0'*64}]}
    doc['sha256'] = execution.digest({k:v for k,v in doc.items() if k!='sha256'})
    monkeypatch.setattr(f, 'verify', lambda value, **kw: deepcopy(value))
    return root, doc


def test_small_default_preserves_complete_premise_and_legacy_layout(case, tmp_path):
    root, _, request = case; doc=f.intake(request,base_dir=root)
    m=f.create_context(doc,'critic',tmp_path/'packet',base_dir=root)
    assert json.loads(r.read_artifact(tmp_path/'packet','premise',expected_manifest_sha256=m['sha256']))==doc
    assert [a['id'] for a in m['artifacts']]==['premise','e0000','e0001']
    assert all('presentation' not in a for a in m['artifacts'])


def test_review_policy_without_science_plan_is_refused_by_the_packet_reader(case,unreviewed_case,tmp_path):
    from ravel.workflow import physics_review, science
    refused=h.HostFailure
    for name,(root,_,request),held in (('reviewed',case,True),('unreviewed',unreviewed_case,False)):
        assert (root/physics_review.POLICY).exists() is held and not (root/science.PLAN).exists()
        out=tmp_path/('packet-'+name);m=f.create_context(f.intake(request,base_dir=root),'critic',out,base_dir=root)
        node={'role':'critic','packet':{'path':str(out),'manifest_sha256':m['sha256']}}
        if held:
            with pytest.raises(refused,match='^Restricted or unauthenticated site artifacts cannot enter a review packet$'):
                h.AgentHost()._packet(node)
        else:
            assert [a['id'] for a in h.AgentHost()._packet(node)['artifacts']]==['premise','e0000','e0001']


def test_large_census_is_retained_with_bounded_unknown_failure_view(unreviewed_case,tmp_path,monkeypatch):
    root,doc=expanded(unreviewed_case,monkeypatch);out=tmp_path/'packet'
    m=f.create_context(doc,'critic',out,base_dir=root)
    public=h.AgentHost()._packet({'role':'critic','packet':{'path':str(out),'manifest_sha256':m['sha256']}})
    summary=json.loads(next(a for a in public['artifacts'] if a['id']=='premise')['content'])
    assert summary['source_inputs']['root_count']==len(doc['source_inputs'])
    assert summary['source_inputs']['sha256']==execution.digest(doc['source_inputs'])
    assert summary['stage_status']=='failed' and summary['result_status']=='unresolved'
    assert summary['missing_output_roots']==doc['missing_output_roots']
    assert summary['scientific_acceptance'] is False and summary['automatic_redo'] is False
    index=r.read_index_page(out,expected_manifest_sha256=m['sha256'],query='full_premise')
    full=next(a for a in index['entries'] if a['id']=='full_premise')
    assert full['presentation']=='on_demand' and 'content' not in full and full['bytes']>2_000_000
    assert index['artifact_content_presented'] is False and full['content_presented'] is False
    assert all(a['id']!='full_premise' for a in public['artifacts'])
    assert public['presentation']['all_content_read_by_model'] is False
    assert len(json.dumps(public))<65536
    assert json.loads(r.read_artifact(out,'full_premise',expected_manifest_sha256=m['sha256']))==doc


@pytest.mark.parametrize('bad',[{'offset':-1,'max_bytes':1},{'offset':True,'max_bytes':1},{'offset':0,'max_bytes':65537},{'offset':0,'max_bytes':False}])
def test_page_bounds_are_not_inflated(bad):
    with pytest.raises(ValueError):r._artifact_page(b'bytes','fixture',**bad)


def test_split_utf8_and_binary_pages_are_explicit_base64():
    raw='α'.encode()+b'\xff';page=r._artifact_page(raw,'fixture',offset=1,max_bytes=2)
    assert page['content_encoding']=='base64' and base64.b64decode(page['content'])==raw[1:3]
    assert page['page_sha256']==hashlib.sha256(raw[1:3]).hexdigest()
    assert page['complete'] and page['artifact_sha256']==hashlib.sha256(raw).hexdigest()


def test_fresh_role_page_selection_preserves_source_projection(case,tmp_path):
    root,_,request=case;doc=f.intake(request,base_dir=root)
    rows=sorted(f._files(doc['returned_outputs']),key=lambda row:row['path'])
    n=next(i for i,row in enumerate(rows) if row['path'].endswith('result.json'))
    artifact=f'returned{n:06d}'
    m=f.create_context(doc,'critic',tmp_path/'packet',base_dir=root,evidence_pages=[{'artifact_id':artifact,'offset':0,'max_bytes':65536}])
    raw=r.read_artifact(tmp_path/'packet',artifact,expected_manifest_sha256=m['sha256'])
    assert 'status' not in json.loads(raw) and json.loads(raw)['machine_passed']==3
    entry=next(a for a in m['artifacts'] if a['id']==artifact)
    assert entry['source_path']==rows[n]['path'] and entry['source_sha256']==rows[n]['sha256']
    page=json.loads(r.read_artifact(tmp_path/'packet','p0000',expected_manifest_sha256=m['sha256']))
    assert json.loads(page['content'])==json.loads(raw)


@pytest.mark.parametrize('identity',['/arbitrary/path','input999999','full_premise/../../secret'])
def test_selected_source_access_is_allowlisted(case,tmp_path,identity):
    root,_,request=case;doc=f.intake(request,base_dir=root)
    with pytest.raises(ValueError):f.create_context(doc,'critic',tmp_path/'packet',base_dir=root,
        evidence_pages=[{'artifact_id':identity,'offset':0,'max_bytes':10}])
    assert not (tmp_path/'packet').exists()


def test_selected_input_assumptions_are_initially_material_and_source_bound(case,tmp_path):
    root,_,request=case;doc=f.intake(request,base_dir=root)
    spec=root/'inputs/science.json';spec.write_text(json.dumps({'schema_version':1,'mode':'fixture','task':{'observable':'Q'},'assumptions':['fixed nuisance']}))
    row={'name':'.','size':spec.stat().st_size,'sha256':execution.file_hash(spec)}
    doc['source_inputs'][str(spec)]={'kind':'file','files':[row]}
    # Only test the typed source projection here, not an invented receipt admission.
    presented=f._bounded_premise(doc)
    assert presented['scientific_contract']['content']['assumptions']==['fixed nuisance']
    spec.write_text('{}')
    with pytest.raises(ValueError,match='contract changed'):f._bounded_premise(doc)


def test_page_read_authenticates_whole_deferred_blob_each_time(case,tmp_path,monkeypatch):
    root,doc=expanded(case,monkeypatch);out=tmp_path/'packet';m=f.create_context(doc,'critic',out,base_dir=root)
    page=r.read_artifact_page(out,'full_premise',expected_manifest_sha256=m['sha256'],offset=0,max_bytes=17)
    assert page['bytes']==17 and not page['complete']
    entry=next(a for a in m['artifacts'] if a['id']=='full_premise')
    path=out/entry['path'];raw=path.read_bytes();path.write_bytes(raw[:-1]+b'X')
    with pytest.raises(ValueError):r.read_artifact_page(out,'full_premise',expected_manifest_sha256=m['sha256'],offset=0,max_bytes=17)
    with pytest.raises(ValueError):g._artifact_checks({'inputs':[],'role':'critic','packet':{'path':str(out),'manifest_sha256':m['sha256']}})


def test_oversized_located_evidence_remains_page_selectable(case,tmp_path,monkeypatch):
    root,doc=expanded(case,monkeypatch)
    ref=doc['evidence'][1];path=Path(ref['path'])
    path.write_text(json.dumps({'status':'failed','physics_validated':False,'raw':'x'*2_100_000}))
    ref.update(sha256=execution.file_hash(path),size=path.stat().st_size)
    m=f.create_context(doc,'critic',tmp_path/'packet',base_dir=root,
        evidence_pages=[{'artifact_id':'e0001','offset':0,'max_bytes':128}])
    entry=next(a for a in m['artifacts'] if a['id']=='e0001')
    assert entry['presentation']=='on_demand' and entry['source_path']==str(path)
    raw=r.read_artifact(tmp_path/'packet','e0001',expected_manifest_sha256=m['sha256'])
    assert 'status' not in json.loads(raw)
    page=json.loads(r.read_artifact(tmp_path/'packet','p0000',expected_manifest_sha256=m['sha256']))
    assert page['content']==raw[:128].decode() and page['total_bytes']>2_000_000


def test_selected_page_continuation_and_receipt_never_claim_full_inline(case,tmp_path):
    root,_,request=case
    # A run without a contract is refused by the gate; this pre-release run keeps its old decision.
    (root/'inputs').mkdir(exist_ok=True);(root/'inputs/task_contract.json').write_text(json.dumps({'prompt':'pre-release failed stage'}))
    doc=f.intake(request,base_dir=root);intake=j._new(tmp_path/'intake.json',doc)
    bindings=[]
    class InertHost:
        identity={'fixture':'no actual model transport'}
        def execute(self,node,request,control):
            result={'kind':'model_result','value':{'kind':'failed_scientific_stage_critique','summary':'control only','observations':[],
                'mechanisms':[],'unknowns':[]},'transport':{'request_id':request['request_id'],'execution_mode':'responses_http_loopback_control'},
                'isolation':{'fresh_request':True,'parent_transcript_supplied':False}}
            return control.call('control','model',{'id':request['request_id']},lambda:result,output_tokens=16)
    for role in ('critic','verifier'):
        binding=j.prepare_failed_role(root,intake,tmp_path/role,role=role,model='control',reasoning_effort='high',max_output_tokens=512,max_wall_seconds=20,
            evidence_pages=[{'artifact_id':'full_premise','offset':0,'max_bytes':31}])
        g.execute(binding['graph_root'],InertHost(),workers=1);bindings.append(binding)
        spec,_=g._load(Path(binding['graph_root']));packet=Path(spec['nodes'][0]['packet']['path'])
        raw=r.read_artifact(packet,'full_premise',expected_manifest_sha256=binding['context_manifest_sha256']);sha=hashlib.sha256(raw).hexdigest()
        receipt=g.model_receipt(binding['graph_root'],role,expected_subject_sha256=sha,require_exact_subject=False)
        assert not receipt['exact_subject_presented'] and sha not in receipt['presented_subject_sha256s']
        with pytest.raises(ValueError,match='present the exact'):
            g.model_receipt(binding['graph_root'],role,expected_subject_sha256=sha,require_exact_subject=True)
    feedback=j.failed_feedback(root,intake,*bindings,allow_control=True)
    assert feedback['scientific_acceptance'] is False and feedback['control_only']
    assert all(row['presentation']['automatic_page_read'] is False for row in feedback['reviews'])
    with pytest.raises(ValueError):j.failed_feedback(root,intake,*bindings)


def test_oversized_scientific_contract_is_disclosed_before_read(case,monkeypatch):
    root,_,request=case;doc=f.intake(request,base_dir=root);source=root/'inputs/science.json'
    doc['source_inputs'][str(source)]={'kind':'file','files':[{'name':'.','sha256':'0'*64,'size':1_000_000_000}]}
    original=Path.open
    def guard(path,*args,**kw):
        if path==source:raise AssertionError('oversized contract must not be opened for summary')
        return original(path,*args,**kw)
    monkeypatch.setattr(Path,'open',guard)
    summary=f._bounded_premise(doc)
    assert summary['scientific_contract']['content'] is None and 'exceeds' in summary['scientific_contract']['limitation']


def test_summary_hidden_as_deferred_cannot_be_feedback(case,tmp_path,monkeypatch):
    root,_,request=case;doc=f.intake(request,base_dir=root);bindings=[];nodes=[]
    for role,actor in [('critic','critic'),('verifier','skeptic')]:
        out=tmp_path/role
        manifest=f.create_context(doc,role,out,base_dir=root,evidence_pages=[{'artifact_id':'full_premise','offset':0,'max_bytes':1}])
        if role=='critic':
            next(a for a in manifest['artifacts'] if a['id']=='premise')['presentation']='on_demand'
            manifest['sha256']=execution.digest({k:v for k,v in manifest.items() if k!='sha256'})
            (out/'manifest.json').write_text(json.dumps(manifest))
        bindings.append({'graph_root':str(tmp_path),'node_id':role,'context_manifest_sha256':manifest['sha256'],'actor_id':actor})
        nodes.append({'id':role,'packet':{'path':str(out)}})
    def receipt(root,node_id,**kw):
        b=next(b for b in bindings if b['node_id']==node_id)
        return {'role':node_id,'request_id':node_id,'context_manifest_sha256':b['context_manifest_sha256'],
            'execution_observation':'control_only','context_transport_separated':True}
    monkeypatch.setattr(g,'model_receipt',receipt);monkeypatch.setattr(g,'_load',lambda root:({'nodes':nodes},{}))
    with pytest.raises(ValueError,match='summary must be presented inline'):
        f.graph_feedback(doc,*bindings,base_dir=root,allow_control=True)
