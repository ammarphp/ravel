"""Pure real Graph debit/outcome boundaries, with no provider or model calls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import agent_graph as graph, research_cycle as cycle
from ravel.workflow import research_outcome_metrics as metrics, state_io
from test_research_outcome_metrics import fixture, connect_graph
from test_agent_graph import Host, spec, node


class AmbiguousFixture(RuntimeError):
    ambiguous=True


class NotDispatchedFixture(ValueError):
    # A definite failure is typed; an untyped raise after dispatch stays ambiguous.
    not_dispatched=True


class FailedBeforeProviderHost:
    identity={'test_fixture':'inert-host-error-before-provider-v1'}
    def __init__(self):self.entered=[];self.provider_dispatched=[]
    def execute(self,item,request,control):
        def before_provider():
            self.entered.append(item['id'])
            raise NotDispatchedFixture('inert validation failed before any provider dispatch')
        return control.call('fixture',item['kind'],request,before_provider,output_tokens=64)


def run(root,gr,host,nodes=None):
    plan=spec(nodes or [node('outcome',kind='model',role='proposer')],calls=3,tokens=256)
    plan['budget']['max_wall_seconds']=60
    cycle.execute_graph(root,gr,plan,host)
    return cycle.outcome_metrics(root)


def test_failed_host_outcome_does_not_observe_provider_dispatch(tmp_path):
    root=fixture(tmp_path);host=FailedBeforeProviderHost()
    result=run(root,tmp_path/'graph',host);use=result['resource_use'];calls=use['calls']
    assert host.entered==['outcome'] and host.provider_dispatched==[]
    assert calls['debited_count']==calls['resolved_count']==calls['failed_count']==1
    assert calls['observed_count']==calls['complete_count']==1
    assert calls['started_count']==calls['ambiguous_count']==calls['completed_count']==0
    assert calls['provider_invocation_count'] is None
    assert use['call_receipts'][0]['provider_invocations'] is None
    assert use['call_receipts'][0]['observation_state']=='resolved_outcome_receipt'
    assert use['model_tokens']['total_tokens']['total'] is None
    text=metrics.markdown(result)
    assert 'Resolved outcome receipts observed: 1;' in text
    assert 'Actual provider invocation count: unknown.' in text
    assert 'Actual calls with receipts:' not in text


def test_ambiguous_receipt_retains_full_debit_and_incomplete_totals(tmp_path):
    root=fixture(tmp_path)
    def ambiguous(*args):raise AmbiguousFixture('inert ambiguous operation; no provider exists')
    host=Host(ambiguous);result=run(root,tmp_path/'graph',host)
    use=result['resource_use'];calls=use['calls']
    assert host.dispatched==['outcome']
    assert calls['debited_count']==calls['receipt_count']==calls['ambiguous_count']==1
    assert calls['observed_count']==calls['resolved_count']==0
    assert calls['complete_count'] is None and calls['unresolved_count']==1
    row=use['call_receipts'][0]
    assert row['observation_state']=='ambiguous_outcome_receipt' and row['elapsed_seconds'] is not None
    assert use['call_seconds']['observed_subtotal']==row['elapsed_seconds']
    assert use['call_seconds']['total'] is None and use['call_seconds']['unresolved_call_records']==1
    assert calls['provider_invocation_count'] is None


def test_partial_ambiguous_token_reports_stay_scoped_with_unknown_total(tmp_path):
    root=fixture(tmp_path);gr=tmp_path/'graph'
    def ambiguous(*args):raise AmbiguousFixture('inert ambiguous fixture')
    run(root,gr,Host(ambiguous))
    checkpoint=state_io.read_json(gr/graph.STATE);identity=next(iter(checkpoint['calls']))
    path=gr/'calls'/(identity+'.json');receipt=state_io.read_json(path)
    # Explicit synthetic receipt reports, never actual provider evidence.
    receipt['result']={'kind':'model_result','usage':{'input_tokens':5,'output_tokens':3,'total_tokens':8}}
    receipt['elapsed_seconds']=1.25
    checkpoint['calls'][identity]['receipt_sha256']=graph.digest(receipt)
    state_io.atomic_json(path,receipt);state_io.atomic_json(gr/graph.STATE,checkpoint)
    use=cycle.outcome_metrics(root)['resource_use']
    assert use['call_receipts'][0]['input_tokens']==5
    assert use['model_tokens']['total_tokens']['observed_subtotal']==8
    assert use['model_tokens']['total_tokens']['total'] is None
    assert use['model_tokens']['total_tokens']['unresolved_call_records']==1
    assert use['call_seconds']['observed_subtotal']==1.25 and use['call_seconds']['total'] is None
    assert use['calls']['complete_count'] is None and use['calls']['provider_invocation_count'] is None


def test_completed_mock_outcome_and_reuse_keep_resolved_census(tmp_path):
    root=fixture(tmp_path);gr,host=connect_graph(tmp_path,root)
    first=cycle.outcome_metrics(root);graph.execute(gr,host,workers=1);second=cycle.outcome_metrics(root)
    for result in (first,second):
        use=result['resource_use'];calls=use['calls']
        assert calls['observed_count']==calls['complete_count']==calls['resolved_count']==calls['completed_count']==1
        assert calls['debited_count']==calls['receipt_count']==calls['debited_complete_count']==1
        assert calls['unresolved_count']==calls['failed_count']==0
        assert calls['provider_invocation_count'] is None
        assert use['model_tokens']['total_tokens']['total']==18
        assert use['charged_ceiling']['calls']==2
    assert len(host.dispatched)==1
    assert first['resource_use']['calls']==second['resource_use']['calls']


def test_mixed_resolved_and_ambiguous_denominator(tmp_path):
    root=fixture(tmp_path)
    def outcome(item,*args):
        if item['id']=='ambiguous':raise AmbiguousFixture('inert ambiguous fixture')
        if item['id']=='failed':raise NotDispatchedFixture('inert definite failure')
        return {'kind':'model_result','usage':{'input_tokens':2,'output_tokens':1,'total_tokens':3}}
    nodes=[node(name,kind='model',role='proposer') for name in ('completed','failed','ambiguous')]
    result=run(root,tmp_path/'graph',Host(outcome),nodes);use=result['resource_use'];calls=use['calls']
    assert calls['debited_count']==calls['receipt_count']==3
    assert calls['observed_count']==calls['resolved_count']==2
    assert calls['completed_count']==calls['failed_count']==calls['ambiguous_count']==1
    assert calls['complete_count'] is None and calls['unresolved_count']==1
    assert len(use['call_receipts'])==3 and use['model_tokens']['total_tokens']['observed_subtotal']==3
    assert use['model_tokens']['total_tokens']['total'] is None and use['call_seconds']['total'] is None
    assert calls['provider_invocation_count'] is None


def test_untyped_host_raise_after_dispatch_stays_ambiguous_not_failed(tmp_path):
    root=fixture(tmp_path)
    def untyped(*args):raise ValueError('inert untyped raise; the effect may have committed')
    result=run(root,tmp_path/'graph',Host(untyped));use=result['resource_use'];calls=use['calls']
    assert calls['debited_count']==calls['receipt_count']==calls['ambiguous_count']==calls['unresolved_count']==1
    assert calls['failed_count']==calls['resolved_count']==calls['observed_count']==0
    assert calls['complete_count'] is None and use['call_receipts'][0]['observation_state']=='ambiguous_outcome_receipt'
    assert use['call_receipts'][0]['status']=='ambiguous'


@pytest.mark.parametrize('receipt_written',[False,True])
def test_started_boundary_public_status_report_and_custody(tmp_path,monkeypatch,receipt_written):
    root=fixture(tmp_path,parent=True);gr=tmp_path/'graph';host=Host();write=graph.atomic_json
    def stop(path,value):
        if Path(path).parent==gr/'calls' and value.get('status')=='started':
            if receipt_written:write(path,value)
            raise OSError('inert interruption before Host invocation')
        return write(path,value)
    with monkeypatch.context() as patch:
        patch.setattr(graph,'atomic_json',stop)
        try:run(root,gr,host)
        except OSError:pass
    assert host.dispatched==[]
    result=cycle.status(root)['outcome_metrics'];use=result['resource_use'];calls=use['calls']
    assert calls['debited_count']==calls['started_count']==calls['unresolved_count']==1
    assert calls['receipt_count']==int(receipt_written)
    assert calls['observed_count']==0 and calls['complete_count'] is None
    assert calls['provider_invocation_count'] is None
    assert use['model_tokens']['total_tokens']['total'] is None and use['call_seconds']['total'] is None
    assert result['original_task']['original_obligation_denominator']==4
    expected='started_receipt_only' if receipt_written else 'debited_without_receipt'
    assert use['call_receipts'][0]['observation_state']==expected
    descriptor=metrics.write_report(root,tmp_path/'report')
    saved=json.loads(Path(descriptor['files'][0]).read_bytes())
    assert saved['resource_use']['calls']==calls
    text=Path(descriptor['files'][1]).read_text()
    assert 'complete resolved-outcome count: unknown.' in text
    assert 'Actual calls with receipts:' not in text


def test_reconciled_not_dispatched_is_attestation_not_provider_count(tmp_path,monkeypatch):
    root=fixture(tmp_path);gr=tmp_path/'graph';write=graph.atomic_json
    def stop(path,value):
        if Path(path).parent==gr/'calls' and value.get('status')=='started':
            write(path,value);raise OSError('inert predispatch stop')
        return write(path,value)
    with monkeypatch.context() as patch:
        patch.setattr(graph,'atomic_json',stop)
        try:run(root,gr,Host())
        except OSError:pass
    _,state=graph._load(gr);identity=next(iter(state['calls']))
    evidence=tmp_path/'no-provider-fixture.json';evidence.write_text('{"inert_fixture_only":true}\n')
    import hashlib
    graph.reconcile(gr,identity,outcome='not_dispatched',evidence=[{'id':'fixture','path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}],reason='Explicit inert software witness, not provider authentication')
    use=cycle.outcome_metrics(root)['resource_use'];calls=use['calls']
    assert calls['observed_count']==calls['failed_count']==1 and calls['unresolved_count']==0
    assert use['call_receipts'][0]['reconciliation']['outcome']=='not_dispatched'
    assert use['call_receipts'][0]['reconciliation']['truth_authenticated'] is False
    assert calls['provider_invocation_count'] is None
