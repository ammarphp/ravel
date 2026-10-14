"""Narrow engineering controls for V1 reviewer findings; no science authority."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
import test_research_protocol as own
from ravel.workflow import research_cycle as cycle, research_protocol as proto
from ravel.workflow import agent_host, state_io
from ravel.physics import research_comparison as cmp

no_process = own.no_process


def extra_regime(tmp_path, monkeypatch, *, changed=1, original=4, comparator=True, other_rule=False):
    root,p = own.baseline_screen_full(tmp_path,monkeypatch,new_full=(1,2))
    cell = deepcopy(p['cells'][1]);cell.update(id='other-cell',regime='other-full-regime')
    cell['population'] = own.write(tmp_path/'other-population.json',{'ids':['c','d']})
    p['cells'].append(cell)
    for ident,candidate in [('original-other','original'),('changed-other','changed')]:
        p['stages'].append({'id':ident,'purpose':'full','candidate':candidate,
            'cells':[{'cell_id':cell['id'],'experiment_id':ident,'value_pointer':'/cells/0/operands/0/value',
                'interval_pointer':None,'quality_pointer':'/status'}],
            'requires':[],'requires_stages':[],'acceptance_scope':'supplied_method_diagnostic',
            'premise_ids':[],'ablation':None,'replaces':None})
        p['required_stage_ids'].append(ident)
    if comparator:
        row = deepcopy(next(c for c in p['comparisons'] if c['id']=='full-contrast'))
        row.update(id='other-contrast',left_stage='changed-other',right_stage='original-other',experiment_id='compare-other-contrast')
        if other_rule:
            rule = proto._json(row['rule'],tmp_path);rule['tolerance']=0.002
            row['rule'] = own.write(tmp_path/'other-rule.json',rule)
        p['comparisons'].append(row);p['required_comparison_ids'].append(row['id'])
    proto.bind(root,own.write(tmp_path/'all-full-regimes.json',p))
    for ident,values in [('original-other',[original]),('changed-other',[changed])]:
        own.design(tmp_path,root,p,ident,values);own.accepted_fixture(root,ident)
    if comparator:own.complete_comparator(tmp_path,root,'other-contrast')
    return root,p


@pytest.mark.parametrize('changed,original,comparator,other_rule,expected',[
    (100,0,False,False,{'changed','original'}),
    (100,0,True,False,{'changed','original'}),
    (1,4,True,False,{'changed'}),
    (2,2,True,False,{'changed'}),
    (1,4,True,True,{'changed','original'}),
])
def test_complete_pair_preference_never_discards_uncovered_conflicting_or_incompatible_regime(
        tmp_path,monkeypatch,changed,original,comparator,other_rule,expected):
    root,p = extra_regime(tmp_path,monkeypatch,changed=changed,original=original,comparator=comparator,other_rule=other_rule)
    view = proto.status(root)['incumbent_options']
    assert set(view['valid_full_candidate_ids']) == {'changed','original'}
    assert set(view['undominated_candidate_ids']) == expected
    assert len(view['reviewed_local_contrasts']) == (2 if comparator else 1)
    if expected == {'changed'}:
        pref = view['reviewed_dominance'][0]
        assert pref['comparison_ids'] == ['full-contrast','other-contrast']
        assert {c:{r['stage_id'] for r in rows} for c,rows in pref['complete_full_stage_cells'].items()} == {
            'changed':{'new-full','changed-other'},'original':{'incumbent-full','original-other'}}
    else:assert view['reviewed_dominance'] == []


def test_meta_receipt_cannot_reapply_but_fresh_round_is_charged(tmp_path,monkeypatch):
    root,p = own.baseline_screen_full(tmp_path,monkeypatch)
    state = own.meta(tmp_path,root,monkeypatch,'report_only');event=state['events'][-1]
    with pytest.raises(ValueError,match='already consumed'):
        proto.apply_meta_review(root,graph_root=state['graphs'][-1]['root'],node_id='meta',context_pin=event['context'],allow_control=True)
    assert cycle._load(root)[1] == state
    fresh = own.meta(tmp_path,root,monkeypatch,'report_only')
    assert cycle._usage(fresh)['calls'] == cycle._usage(state)['calls']+1
    assert sum(e['kind']=='protocol_meta_review_applied' for e in fresh['events']) == 2


def test_meta_complete_ordinary_input_inventory_and_actual_role_bytes(tmp_path,monkeypatch):
    root,p = own.make(tmp_path,monkeypatch)
    own.design(tmp_path,root,p,'base-full',[1,2]);own.accepted_fixture(root,'base-full')
    original = {pin['path']:pin for e in cycle._load(root)[1]['experiments'] for pin in e['input_pins']}
    prepared = proto.prepare_meta_review(root,tmp_path/'meta',role='verifier',model='inert',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10)
    subject = proto._json(prepared['context'],tmp_path)
    assert all(pin in subject['source_inputs'] for pin in original.values())
    spec=state_io.read_json(prepared['graph_spec']['path']);packet=agent_host.AgentHost()._packet(spec['nodes'][0])
    artifacts = {a['source_sha256']:a for a in packet['artifacts']}
    for pin in original.values():
        assert pin['sha256'] in artifacts
        assert artifacts[pin['sha256']]['content'] == Path(pin['path']).read_text()
    assert cycle._load(root)[1]['graphs'] == []


def test_meta_omitted_input_content_refuses_after_real_charged_graph(tmp_path,monkeypatch):
    root,p = own.make(tmp_path,monkeypatch)
    own.design(tmp_path,root,p,'base-full',[1,2]);own.accepted_fixture(root,'base-full')
    required = next(pin for e in cycle._load(root)[1]['experiments'] for pin in e['input_pins'] if pin['path'].endswith('supplied-values.json'))
    original = proto.prepare_meta_review
    def incomplete(*args,**kw):
        prepared=original(*args,**kw);spec=state_io.read_json(prepared['graph_spec']['path'])
        manifest_path=Path(spec['nodes'][0]['packet']['path'])/'manifest.json';manifest=state_io.read_json(manifest_path)
        manifest['artifacts']=[a for a in manifest['artifacts'] if a['source_path']!=required['path']]
        manifest.pop('sha256');manifest['sha256']=cycle.science.execution.digest(manifest)
        state_io.atomic_json(manifest_path,manifest);spec['nodes'][0]['packet']['manifest_sha256']=manifest['sha256']
        state_io.atomic_json(Path(prepared['graph_spec']['path']),spec)
        return prepared
    monkeypatch.setattr(proto,'prepare_meta_review',incomplete)
    before=cycle._load(root)[1]
    # Dispatch admission authenticates the complete packet index before the campaign
    # reservation, so the truncation is refused earlier than the charged Graph and the
    # later source-content check: nothing is reserved, charged or dispatched.
    with pytest.raises(ValueError,match='review context artifact membership differs from complete index'):
        own.meta(tmp_path,root,monkeypatch,'report_only')
    state=cycle._load(root)[1]
    assert state==before
    assert state['graphs']==[] and cycle._usage(state)['calls']==0
    assert not any(row['id'].startswith('graph:') for row in state['resource_ledger'])
    assert not any(e['kind'] in {'ordinary_graph_reserved','protocol_meta_review_applied'} for e in state['events'])
    assert not (tmp_path/'meta-0'/'graph'/'calls').exists()


def test_meta_other_ordinary_input_drift_refuses_without_preparation_or_debit(tmp_path,monkeypatch):
    root,p=own.make(tmp_path,monkeypatch);own.design(tmp_path,root,p,'base-full',[1,2])
    state=cycle._load(root)[1];Path(tmp_path/'base-full/supplied-values.json').write_text('{"value":[99,99],"quality":true}')
    with pytest.raises(ValueError,match='authenticated source bytes'):
        proto.prepare_meta_review(root,tmp_path/'meta',role='critic',model='inert',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10)
    assert not (tmp_path/'meta').exists() and cycle._load(root)[1]==state


def test_canonical_census_deduplicates_before_unique_limit_and_reads_once(tmp_path,monkeypatch):
    pin=own.write(tmp_path/'source.txt','source');alias={**pin,'path':str(tmp_path/'./source.txt')}
    calls=[];original=cmp._snapshot
    def observed(*a,**kw):calls.append(a[0]);return original(*a,**kw)
    monkeypatch.setattr(cmp,'_snapshot',observed)
    result=proto._pins([pin,alias]*200,tmp_path)
    assert result==[pin] and calls==[pin]


@pytest.mark.parametrize('kind',['unique','references','conflicting_alias'])
def test_census_limits_and_conflicting_aliases_refuse_before_payload_io(tmp_path,monkeypatch,kind):
    pin=own.write(tmp_path/'source.txt','source')
    if kind=='unique':pins=[{**pin,'path':str(tmp_path/('p'+str(i)))} for i in range(129)]
    elif kind=='references':pins=[pin]*8193
    else:pins=[pin,{**pin,'path':str(tmp_path/'./source.txt'),'sha256':'0'*64}]
    def forbidden(*a,**kw):raise AssertionError('payload IO before population admission')
    monkeypatch.setattr(cmp,'_snapshot',forbidden)
    with pytest.raises(ValueError):proto._pins(pins,tmp_path)
