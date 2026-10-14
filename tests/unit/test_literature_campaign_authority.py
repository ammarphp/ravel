"""Authored/UNRUN ordinary authority and Graph regressions.

Original campaigns, knowledge/custody readers, Graph/Host calls and receipts are
real software APIs. HTTP transport and race/dependency callbacks are explicitly
in-process test fixtures; no remote publication/model or scientific acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel.workflow import literature_context as lc, research_cycle as cycle
from ravel.workflow import research_tools as tools, physics_knowledge as pk
from ravel.workflow import agent_graph, agent_host
from test_research_cycle import contract, write
from test_task_completion import goal, PROMPT
from test_literature_context import (document, request, pin, scripted_transport,
    acquisition_request, refuse_real_network)


def campaign(base, *, parent=False):
    original=contract(base)
    if parent:
        _, parent_pin=goal(base)
        original['goal_binding']={'contract':parent_pin,'assignment_id':'summary-child'}
    root=base/'campaign';cycle.create(root,original,base_dir=base, evaluation_harness=True)
    return root,original


def bind_source(base, root, identity='paper'):
    source=base/identity;source.mkdir()
    doc=document(source,identity,'Original μ convention retained as a source assertion.\n','text')
    req=request(source,[doc],root=root)
    result=tools.prepare_literature_context(root,req,root/('located-'+identity),
        premise_map={identity+'.u0.n0':'premise-'+identity},reason='Bind full original source, not a vote.')
    return doc,req,result


def scope_for(root, original):
    return {'root':str(root),'contract_sha256':cycle.ce.digest(original)}


def test_real_same_campaign_multiple_knowledge_additions_keep_original_custody(tmp_path):
    base=tmp_path.resolve();root,original=campaign(base)
    doc,req,first=bind_source(base,root)
    original_custody_path=Path(first['product']['path']).parent/'original-custody.json'
    original_custody=original_custody_path.read_bytes()
    _,_,second=bind_source(base,root,'second')
    _,state=cycle._load(root)
    assert state['contract']==original and len(state['knowledge_bindings'])==2
    assert lc.consume(first['product'],base_dir=base)==first
    assert lc.consume(second['product'],base_dir=base)==second
    for result in (first,second):
        knowledge=json.loads(Path(result['knowledge_request']['path']).read_text())
        assert pk.retrieve(knowledge,base)['kind']=='physics-knowledge-context'
        assert not any(result['context']['claims'].values())
        assert not any('/history/' in p['path'] or p['path'].endswith('/head.json')
                       for p in result['context']['input_pins'])
    assert original_custody_path.read_bytes()==original_custody
    assert lc._SCOPE_VERIFICATION.get()==()


@pytest.mark.parametrize('fault',['source','head','history','contract'])
def test_real_bound_source_and_journal_tamper_refuse_without_cached_authority(tmp_path,fault):
    base=tmp_path.resolve();root,original=campaign(base)
    doc,req,result=bind_source(base,root)
    assert lc.consume(result['product'],base_dir=base)==result
    if fault=='source':
        Path(doc['pin']['path']).write_text('Different source.\n')
    elif fault=='head':
        (root/'head.json').write_text('{}\n')
    elif fault=='history':
        (root/'history/0000.json').write_text('{}\n')
    else:
        state=cycle._load(root)[1];state['contract']['question']='Altered original question.'
        state=cycle._seal({k:v for k,v in state.items() if k!='sha256'})
        current=root/'history'/f"{state['revision']:04d}.json"
        write(current,state);write(root/'head.json',cycle._pin(current))
    with pytest.raises((ValueError,KeyError)):
        lc._scope(scope_for(root,original),lc._Reader(base))
    assert lc._SCOPE_VERIFICATION.get()==()


@pytest.mark.parametrize('fault',['head','earlier-history'])
def test_last_backedge_read_cannot_hide_earlier_authority_mutation(tmp_path,monkeypatch,fault):
    base=tmp_path.resolve();root,original=campaign(base)
    bind_source(base,root)
    old=lc._Reader.read;changed=[]
    def reading(self,pin_value,maximum=lc.MAX_INPUT_BYTES):
        answer=old(self,pin_value,maximum)
        stack=lc._SCOPE_VERIFICATION.get()
        if stack and stack[-1]['phase']=='knowledge' and not changed:
            target=Path(stack[-1]['current_pin']['path'])
            if Path(pin_value['path'])==target:
                victim=root/'head.json' if fault=='head' else root/'history/0000.json'
                victim.write_bytes(victim.read_bytes()+b' ');changed.append(str(victim))
        return answer
    monkeypatch.setattr(lc._Reader,'read',reading)
    with pytest.raises(ValueError):lc._scope(scope_for(root,original),lc._Reader(base))
    assert len(changed)==1 and lc._SCOPE_VERIFICATION.get()==()


def test_current_parent_change_during_actual_backedge_refuses(tmp_path,monkeypatch):
    base=tmp_path.resolve();root,original=campaign(base,parent=True)
    bind_source(base,root)
    before=lc._Reader.read;changed=[]
    def reading(self,pin_value,maximum=lc.MAX_INPUT_BYTES):
        answer=before(self,pin_value,maximum)
        stack=lc._SCOPE_VERIFICATION.get()
        if stack and stack[-1]['phase']=='knowledge' and not changed:
            if Path(pin_value['path'])==Path(stack[-1]['current_pin']['path']):
                parent=Path(original['goal_binding']['contract']['path'])
                parent.write_bytes(parent.read_bytes()+b' ');changed.append(True)
        return answer
    monkeypatch.setattr(lc._Reader,'read',reading)
    with pytest.raises(ValueError):lc._scope(scope_for(root,original),lc._Reader(base))
    assert changed==[True] and lc._SCOPE_VERIFICATION.get()==()


def test_parent_input_change_during_final_authority_reads_refuses(tmp_path,monkeypatch):
    base=tmp_path.resolve();root,original=campaign(base,parent=True)
    bind_source(base,root)
    before_read=lc._Reader.read;before_finish=lc._Reader.finish;closing=[];changed=[]
    def finishing(self,**kwargs):
        stack=lc._SCOPE_VERIFICATION.get()
        if stack and self is stack[-1]['authority']:
            closing.append(self)
        return before_finish(self,**kwargs)
    def reading(self,pin_value,maximum=lc.MAX_INPUT_BYTES):
        answer=before_read(self,pin_value,maximum)
        if closing and self is closing[-1] and not changed:
            if '/history/' in pin_value['path']:
                parent=Path(original['goal_binding']['contract']['path'])
                parent.write_bytes(parent.read_bytes()+b' ');changed.append(True)
        return answer
    monkeypatch.setattr(lc._Reader,'read',reading);monkeypatch.setattr(lc._Reader,'finish',finishing)
    with pytest.raises(ValueError):lc._scope(scope_for(root,original),lc._Reader(base))
    assert changed==[True] and lc._SCOPE_VERIFICATION.get()==()


@pytest.mark.parametrize('edge',['same-parent','backedge-parent','cross-campaign'])
def test_actual_journal_dependency_cycles_refuse_and_exception_frame_resets(tmp_path,monkeypatch,edge):
    # These callbacks inject malformed dependency edges; they do not fabricate
    # accepted journals or claim a real physical parent/citation cycle exists.
    base=tmp_path.resolve();root,original=campaign(base)
    other=base/'other';other.mkdir();second,second_original=campaign(other)
    real_parent=cycle._parent_goal;real_load=cycle._load
    if edge=='backedge-parent':bind_source(base,root)
    parent_calls=[]
    if edge in ('same-parent','backedge-parent'):
        def parent(state):
            if state['base_dir']==str(base):
                parent_calls.append(True)
                if edge=='same-parent' or len(parent_calls)>1:
                    return lc._scope(scope_for(root,original),lc._Reader(base))
            return real_parent(state)
        monkeypatch.setattr(cycle,'_parent_goal',parent)
    else:
        def loading(path,**kwargs):
            stack=lc._SCOPE_VERIFICATION.get()
            if Path(path)==root and stack:
                lc._scope(scope_for(second,second_original),lc._Reader(other))
            elif Path(path)==second and stack:
                lc._scope(scope_for(root,original),lc._Reader(base))
            return real_load(path,**kwargs)
        monkeypatch.setattr(cycle,'_load',loading)
    with pytest.raises(ValueError,match='cyclic'):
        lc._scope(scope_for(root,original),lc._Reader(base))
    assert lc._SCOPE_VERIFICATION.get()==()
    monkeypatch.setattr(cycle,'_parent_goal',real_parent);monkeypatch.setattr(cycle,'_load',real_load)
    assert lc._scope(scope_for(root,original),lc._Reader(base))['question']==original['question']


def test_acyclic_nested_campaign_reference_has_independent_full_validation(tmp_path,monkeypatch):
    base=tmp_path.resolve();root,original=campaign(base)
    other=base/'other';other.mkdir();second,second_original=campaign(other)
    real_load=cycle._load;seen=[]
    def loading(path,**kwargs):
        if Path(path)==root and lc._SCOPE_VERIFICATION.get():
            seen.append(lc._scope(scope_for(second,second_original),lc._Reader(other)))
        return real_load(path,**kwargs)
    monkeypatch.setattr(cycle,'_load',loading)
    assert lc._scope(scope_for(root,original),lc._Reader(base))['scope']==original['scope']
    assert len(seen)==1 and seen[0]['root']==str(second)
    assert lc._SCOPE_VERIFICATION.get()==()


@pytest.mark.parametrize('status',[200,503])
def test_real_parent_bound_public_acquisition_graph_and_current_string_root_consumer(tmp_path,monkeypatch,status):
    base=tmp_path.resolve();root,original=campaign(base,parent=True)
    body=b'Actual scripted entity; source assertions only.\n'
    calls=scripted_transport(monkeypatch,body,status=status)
    result=tools.acquire_literature(root,acquisition_request(base),root/'acquisition',
        agent_host.AgentHost(timeout_seconds=30,literature_origins=['https://papers.example.org']),max_wall_seconds=30)
    actual=lc.consume_acquisition(result['binding'],base_dir=base)
    binding=json.loads(Path(result['binding']['path']).read_text())
    graph=cycle._ordinary(binding['graph']);spec,_=agent_graph._load(graph)
    origin=cycle._graph_result(graph,binding['node'])
    _,state=cycle._load(root)
    assert spec['goal_binding']==original['goal_binding'] and len(state['graphs'])==1
    assert state['graphs'][0]['usage']['calls']==1 and cycle._usage(state)['calls']==1
    assert origin==binding['origin'] and len(calls)==1
    assert agent_graph.status(graph)['complete']
    assert state['parent_task']['original_request']==PROMPT
    assert [r['id'] for r in state['parent_task']['original_obligations']]==['original-request','atlas','cms','domain']
    assert actual['status']==('acquired' if status==200 else 'failed')
    assert (actual['source_artifact'] is not None)==(status==200)
    assert not state['physics_validated'] and not any(result['claims'].values())
    Path(result['binding']['path']).write_text('{}\n')
    with pytest.raises(ValueError):lc.consume_acquisition(result['binding'],base_dir=base)
