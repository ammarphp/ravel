"""Controlled clocks with real public Graph/campaign/engine-free Host tools."""
from copy import deepcopy
import pytest
from ravel.workflow import research_cycle as cycle, agent_graph as graph, agent_host
from test_research_cycle import contract


def setup(tmp_path, monkeypatch, *, wall=480, parent=600, first_delay=0):
    now=[1000.0]
    monkeypatch.setattr(cycle.time, 'time', lambda: now[0])
    c=contract(tmp_path);c['budget']['wall_seconds']=parent
    root=tmp_path/'campaign';cycle.create(root,c,base_dir=tmp_path, evaluation_harness=True)
    pins=[{'id':i,**{k:cycle._pin(tmp_path/f)[k] for k in ('path','sha256')}} for i,f in [('request','context-request.json'),('api','math.py')]]
    spec={'schema_version':1,'graph_id':'remaining-clock','budget':{'max_nodes':1,'max_calls':2,'max_output_tokens':0,'max_wall_seconds':wall,'max_reworks':1},'nodes':[{'id':'context','kind':'tool','role':'proposer','depends_on':[],'inputs':pins,'packet':None,'action':'scientific-context','parameters':{'request_input':'request'},'max_attempts':1}]}
    class Host(agent_host.AgentHost):
        executions=0
        def execute(self,*a,**k):
            self.executions+=1
            if self.executions==1:now[0]+=first_delay
            return super().execute(*a,**k)
    return root,tmp_path/'graph',spec,Host(),now


def retained(root,gr):
    s=cycle._load(root)[1];_,g=graph._load(gr)
    return deepcopy((s['timing'],s['resource_ledger'],cycle._usage(s),g['started_epoch']))


def started(tmp_path,monkeypatch,**kw):
    root,gr,spec,host,now=setup(tmp_path,monkeypatch,**kw)
    r=cycle.execute_graph(root,gr,spec,host);assert r['complete'] and r['usage']['calls']==1
    graph.rework(gr,['context'],reason='Supplied software rerun; original clocks and reservation retained.')
    return root,gr,spec,host,now


def test_actual_resumed_original_allowance_no_second_charge(tmp_path,monkeypatch):
    root,gr,spec,host,now=started(tmp_path,monkeypatch)
    old=retained(root,gr);now[0]=1240
    result=cycle.execute_graph(root,gr,spec,host)
    assert result['complete'] and result['usage']['calls']==2 and host.executions==2
    assert retained(root,gr)==old
    assert old[0]['deadline_epoch']==1600 and old[3]==1000


def test_fixed_deadline_equality_is_allowed(tmp_path,monkeypatch):
    root,gr,spec,host,now=started(tmp_path,monkeypatch,first_delay=120)
    old=retained(root,gr);assert old[3]+480==old[0]['deadline_epoch']==1600
    now[0]=1240
    assert cycle.execute_graph(root,gr,spec,host)['complete']
    assert retained(root,gr)==old


def test_independent_child_expiry_with_parent_live(tmp_path,monkeypatch):
    root,gr,spec,host,now=started(tmp_path,monkeypatch)
    old=retained(root,gr);now[0]=1480
    with pytest.raises(graph.GraphError,match='wall-time budget exhausted'):cycle.execute_graph(root,gr,spec,host)
    assert host.executions==1 and retained(root,gr)==old
    assert now[0]<old[0]['deadline_epoch']


def test_independent_parent_expiry_with_child_live(tmp_path,monkeypatch):
    # Real Host preparation can occur after initial fit and before first call.
    root,gr,spec,host,now=started(tmp_path,monkeypatch,first_delay=121)
    old=retained(root,gr);now[0]=1600
    assert old[3]+480==1601
    with pytest.raises(cycle.OperationalBoundaryError):cycle.execute_graph(root,gr,spec,host)
    assert host.executions==1 and retained(root,gr)==old
    boundary=cycle._load(root)[1]['operational_boundaries'][-1]
    assert boundary['remaining_seconds']==0 and boundary['required_ceiling_seconds']==1


@pytest.mark.parametrize('when,passes',[(1100,True),(1240,False),(1600,False)])
def test_reserved_pristine_unstarted_requires_full_original_fit(tmp_path,monkeypatch,when,passes):
    root,gr,spec,host,now=setup(tmp_path,monkeypatch)
    graph.create(gr,spec);original=graph.execute
    def before_call(*a,**k):raise RuntimeError('supplied pre-call interruption')
    monkeypatch.setattr(graph,'execute',before_call)
    with pytest.raises(RuntimeError,match='pre-call interruption'):cycle.execute_graph(root,gr,spec,host,prepared=True)
    old=retained(root,gr);assert old[3] is None and host.executions==0
    monkeypatch.setattr(graph,'execute',original);now[0]=when
    if passes:
        assert cycle.execute_graph(root,gr,spec,host,prepared=True)['complete']
        fresh=retained(root,gr);assert fresh[:3]==old[:3] and fresh[3]==when
    else:
        with pytest.raises(cycle.OperationalBoundaryError):cycle.execute_graph(root,gr,spec,host,prepared=True)
        assert retained(root,gr)==old and host.executions==0


def test_first_reservation_still_requires_full_fit(tmp_path,monkeypatch):
    root,gr,spec,host,now=setup(tmp_path,monkeypatch,parent=300)
    with pytest.raises(cycle.OperationalBoundaryError):cycle.execute_graph(root,gr,spec,host)
    s=cycle._load(root)[1]
    assert not gr.exists() and s['resource_ledger']==[] and host.executions==0
    assert s['timing']['deadline_epoch']==1300


@pytest.mark.parametrize('end',[1480,1600])
def test_validation_elapsed_time_is_checked_after_authentication(tmp_path,monkeypatch,end):
    root,gr,spec,host,now=started(tmp_path,monkeypatch)
    old=retained(root,gr);now[0]=1240;original=cycle.validate_graph_reservation
    def delayed(*a,**k):
        result=original(*a,**k);now[0]=end;return result
    monkeypatch.setattr(cycle,'validate_graph_reservation',delayed)
    with pytest.raises((graph.GraphError,cycle.OperationalBoundaryError)):cycle.execute_graph(root,gr,spec,host)
    assert retained(root,gr)==old and host.executions==1


def test_missing_original_parent_timer_is_not_initialized(tmp_path,monkeypatch):
    root,gr,spec,host,now=started(tmp_path,monkeypatch)
    s=cycle._load(root)[1];s['timing'].update(started_epoch=None,deadline_epoch=None)
    cycle._commit(root,s,'supplied_bad_timer_fixture')
    old=retained(root,gr)
    with pytest.raises(ValueError,match='original campaign timer'):cycle.execute_graph(root,gr,spec,host)
    assert retained(root,gr)==old and host.executions==1


def test_changed_reserved_ceiling_refuses_before_clock_or_host(tmp_path,monkeypatch):
    root,gr,spec,host,now=started(tmp_path,monkeypatch)
    old=retained(root,gr);changed=deepcopy(spec);changed['budget']['max_wall_seconds']=481;now[0]=1240
    with pytest.raises(ValueError):cycle.execute_graph(root,gr,changed,host)
    assert retained(root,gr)==old and host.executions==1
