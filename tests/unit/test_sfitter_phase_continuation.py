"""Real finite source-phase review gate with explicitly synthetic transport.

The original tiny review fixture mocks approval verification and supplies its
stdlib result. No scientific vote, fit, provider or native process is claimed.
"""
import json
from pathlib import Path
import pytest
from ravel.workflow import sfitter_phase_continuation as m
from ravel.workflow import sfitter_review_protocol as p, scientific_judgment as j
from ravel.workflow import physics_review as review, sfitter_workflow as w
from test_conductor_protocol_join import adopted, prepare
from test_sfitter_review_protocol import FakeHost, add, ref, criterion
from test_sfitter_adapter import save, pin
from test_physics_review import run, opened, accept
from test_scientific_judgment import observed_role_boundary


def whole_extraction(tmp,rp):
    request=json.loads(Path(rp['path']).read_bytes())
    wf=json.loads(Path(request['workflow']['path']).read_bytes())
    source=request['regime'];source=json.loads(Path(source['path']).read_bytes())['sources'][0]
    ob=wf['target']['observables'][0]
    add(tmp,request,'observable_semantics','regime_consistency',{'rows':[
        {**{k:ob[k] for k in ('ID','representation','normalization','unit')},
         'acceptance':'total','luminosity_included':False,'source':ref(source,'/acceptance')}]})
    values=save(tmp/'artificial-uncertainties.json',{'a':[3.],'b':[4.],'total':[5.]})
    add(tmp,request,'uncertainty_roundtrip','quadrature',
        {'components':[ref(values,'/a'),ref(values,'/b')],'total':ref(values,'/total'),
         'criterion':criterion(source),'independence':ref(source,'/independence')})
    request['required_concerns']=['traceability','uncertainty_roundtrip','observable_semantics']
    request['check_mapping']={k:['agreement'] for k in request['required_concerns']}
    return save(tmp/'full-protocol.json',request)


def accepted(run, tmp, *, roles=('critic','verifier','synthesizer'), whole=True):
    opened(run)
    root = run[0]
    source=tmp/"source";source.mkdir()
    ap, rp = adopted(source)
    if whole:rp=whole_extraction(source,rp)
    for role in roles:
        binding = prepare(root, tmp, ap, rp, role)
        j.execute_role(binding['judgment'], FakeHost())
        # Callers request observed_role_boundary: the unmodified control transport cannot vote.
        p.consume(root, binding, allow_control=True)
    return root, ap, rp


def test_actual_existing_review_join_advances_context_without_production(run, tmp_path,observed_role_boundary):
    root, ap, rp = accepted(run, tmp_path)
    assert not review.gate_errors(root, 'reuse')
    original = Path(json.loads(Path(ap['path']).read_bytes())['workflow_draft']['path']).read_bytes()
    result = m.advance(ap, rp, tmp_path, root, tmp_path/'continuation')
    assert result['completed_source_phase']=='extraction' and result['next_phase']=='sm_template'
    assert result['production_calls_dispatched']==0 and result['old_votes_carried']==[]
    assert not result['execution_authorized'] and not result['physics_validated']
    context = json.loads(Path(result['context']['path']).read_bytes())
    assert context['phase']=='sm_template' and context['completed_source_drafts']==['extraction']
    next_request = json.loads(Path(result['workflow']['path']).read_bytes())
    assert next_request['target']==context['target']
    assert all(pin in next_request['sources'] for pin in result['retained_journal_inputs'])
    assert Path(json.loads(Path(ap['path']).read_bytes())['workflow_draft']['path']).read_bytes()==original
    assert review.status(root)['state']=='accepted'


@pytest.mark.parametrize('roles',[(),('critic',),('critic','verifier')])
def test_unfinished_domain_review_refuses_before_outputs(run,tmp_path,roles,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path,roles=roles)
    with pytest.raises(ValueError):m.advance(ap,rp,tmp_path,root,tmp_path/'continuation')
    assert not (tmp_path/'continuation').exists()


def test_prior_acceptance_without_this_domain_request_is_not_phase_authority(run,tmp_path):
    opened(run);root=run[0];source=tmp_path/'source';source.mkdir();ap,rp=adopted(source);rp=whole_extraction(source,rp)
    accept(root)
    assert not review.gate_errors(root,'reuse')
    with pytest.raises(ValueError,match='exact domain request'):
        m.advance(ap,rp,tmp_path,root,tmp_path/'continuation')
    assert not (tmp_path/'continuation').exists()


def test_all_three_narrow_acceptances_do_not_approve_whole_phase(run,tmp_path,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path,whole=False)
    assert not review.gate_errors(root,'reuse')
    with pytest.raises(ValueError,match='incomplete owning phase'):
        m.advance(ap,rp,tmp_path,root,tmp_path/'continuation')
    assert not (tmp_path/'continuation').exists()


def test_declared_scope_cannot_borrow_acceptance_for_other_domain_request(run,tmp_path,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path)
    request=json.loads(Path(rp['path']).read_bytes());request['claim_scope']='diagnostic'
    other=save(tmp_path/'other-domain.json',request)
    with pytest.raises(ValueError,match='scope'):
        m.advance(ap,other,tmp_path,root,tmp_path/'continuation')


@pytest.mark.parametrize('mutation',['review_input','final_receipt','generated_context','extra_output'])
def test_ending_changes_never_return_continuation(run,tmp_path,monkeypatch,mutation,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path)
    old=m.atomic_json;called=[]
    def write(path,value):
        old(path,value)
        if Path(path).name!='continuation-receipt.json':return
        called.append(True)
        if mutation=='review_input':(root/'inputs/held-fixed.txt').write_text('changed\n')
        elif mutation=='final_receipt':
            old(path,{**value,'execution_authorized':True})
        elif mutation=='generated_context':
            (Path(path).parent/'next-phase-context/context.json').write_text('{"changed":true}\n')
        else:(Path(path).parent/'extra.json').write_text('{}\n')
    monkeypatch.setattr(m,'atomic_json',write)
    with pytest.raises(ValueError):m.advance(ap,rp,tmp_path,root,tmp_path/'continuation')
    assert called==[True]


def test_later_original_journal_change_invalidates_next_source_inputs(run,tmp_path,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path)
    result=m.advance(ap,rp,tmp_path,root,tmp_path/'continuation')
    request=json.loads(Path(result['workflow']['path']).read_bytes())
    head=root/review.HEAD
    head.write_bytes(head.read_bytes()+b'\n')
    with pytest.raises(ValueError):w.input_pins(request,Path(result['workflow']['path']).parent)


def test_relative_adoption_is_retained_as_canonical_same_captured_bytes(run,tmp_path,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path)
    relative={**ap,'path':str(Path(ap['path']).relative_to(tmp_path))}
    result=m.advance(relative,rp,tmp_path,root,tmp_path/'continuation')
    request=json.loads(Path(result['workflow']['path']).read_bytes())
    assert ap in request['sources'] and relative not in request['sources']


def test_actual_cli_operation_prepares_context_without_native_dispatch(run,tmp_path,monkeypatch,capsys,observed_role_boundary):
    root,ap,rp=accepted(run,tmp_path)
    monkeypatch.chdir(tmp_path)
    m.main(['--adoption',ap['path'],'--domain-request',rp['path'],'--rundir',str(root),
            '--output',str(tmp_path/'continuation')])
    result=json.loads(capsys.readouterr().out)
    assert Path(result['context']['path']).is_file() and result['production_calls_dispatched']==0
