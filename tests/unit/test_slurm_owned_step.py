from copy import deepcopy
import json,os,time
import pytest
from cosmic_evolution_fixture import schema,FakeController,LIMITS
from ravel.workflow.slurm_owned_step import OwnedStep,record

def setup():
    alloc={'cluster':'fixture','job_id':17,'uid':os.getuid(),'submit':1,'start':2,'restarts':0,'nodes':['n0','n1']}
    c=FakeController({'allocation':alloc},None,None,None,None);c.start=100;c.step=3
    s=OwnedStep(alloc,schema(),c.observe,clock=lambda:100)
    payload={'path':'native','sha256':'0'*64,'size':1}
    rows=[{'nonce':'fresh','job_id':17,'step_id':3,'uid':os.getuid(),'rank':i,'node':'n'+str(i),'payload':deepcopy(payload)} for i in range(2)]
    s.begin(os.getuid(),'17',payload);return s,c,rows,payload

def test_two_ranks_exact_incarnation_then_complete():
    s,c,rows,p=setup();ack=s.bind(rows,2,'fresh',p);assert ack['step_id']==3
    c.state='COMPLETED';r=s.finish([{'rank':i,'job_id':17,'step_id':3,'exit_code':0} for i in range(2)])
    assert r['accounting_complete'] is False and r['distributed_memory_peak'] is None
    assert not any(x['kind']=='cancel' for x in c.calls)

@pytest.mark.parametrize('attack',['rank-tail','duplicate','payload','nonce','uid','job','node','step','stale-start','restart','bool'])
def test_pre_payload_population_and_incarnation_refuse(attack):
    s,c,rows,p=setup()
    if attack=='rank-tail':rows.pop()
    elif attack=='duplicate':rows[1]['rank']=0
    elif attack in ('payload','nonce'):rows[1][attack]={} if attack=='payload' else 'old'
    elif attack in ('uid','job','node','step'):rows[1][{'job':'job_id','step':'step_id'}.get(attack,attack)]=999 if attack!='node' else 'foreign'
    elif attack=='stale-start':c.start=99
    elif attack=='restart':c.runtime['allocation']['restarts']=1
    elif attack=='bool':rows[1]['rank']=True
    with pytest.raises(ValueError):s.bind(rows,2,'fresh',p)
    assert s.owned is None and not any(x['kind']=='cancel' for x in c.calls)

def test_unknown_ownership_never_guesses_cancellation():
    s,c,rows,p=setup()
    with pytest.raises(ValueError,match='never observed'):s.cancel()
    assert not any(x['kind']=='cancel' for x in c.calls)

def test_cleanup_uses_only_owned_job_dot_step():
    s,c,rows,p=setup();s.bind(rows,2,'fresh',p);r=s.cancel()
    assert r['allocation_cancelled'] is False
    assert [(x['job'],x['step']) for x in c.calls if x['kind']=='cancel']==[(17,3)]

def test_reused_step_cannot_authorize_cleanup():
    s,c,rows,p=setup();s.bind(rows,2,'fresh',p);c.start=101
    with pytest.raises(ValueError,match='incarnation changed'):s.cancel()
    assert not any(x['kind']=='cancel' for x in c.calls)

@pytest.mark.parametrize('attack',['nonzero','missing','duplicate'])
def test_native_complete_rank_exit_is_required(attack):
    s,c,rows,p=setup();s.bind(rows,2,'fresh',p);c.state='COMPLETED';exits=[{'rank':i,'job_id':17,'step_id':3,'exit_code':0} for i in range(2)]
    if attack=='nonzero':exits[1]['exit_code']=1
    elif attack=='missing':exits.pop()
    else:exits[1]['rank']=0
    with pytest.raises(ValueError):s.finish(exits)

def test_compact_native_hostlist_is_expanded_not_guessed():
    r={'jobs':[{'job_id':17,'uid':os.getuid(),'submit':1,'start':2,'restarts':0,'state':'RUNNING','nodes':'n[0-1]'}]}
    assert record(json.dumps(r).encode(),schema()['job'],'job',expand_nodes=lambda v:['n0','n1'])['nodes']==['n0','n1']
    with pytest.raises(ValueError):record(json.dumps(r).encode(),schema()['job'],'job')

@pytest.mark.parametrize('ranks,nodes',[(32,1),(8,2)])
def test_original_cpu32_and_gpu8_complete_rank_populations(ranks,nodes):
    s,c,rows,p=setup();population=['n'+str(i) for i in range(nodes)]
    s.expected['nodes']=population;c.runtime['allocation']['nodes']=population
    old=c.observe
    def observe(kind,job,step):
        raw=old(kind,job,step)
        if kind=='step':v=json.loads(raw);v['steps'][0]['nodes']=population;return json.dumps(v).encode()
        return raw
    s.observe=observe
    rows=[{'nonce':'fresh','job_id':17,'step_id':3,'uid':os.getuid(),'rank':i,'node':population[i%nodes],'payload':deepcopy(p)} for i in range(ranks)]
    s.bind(rows,ranks,'fresh',p);c.state='COMPLETED'
    out=s.finish([{'rank':i,'job_id':17,'step_id':3,'exit_code':0} for i in range(ranks)])
    assert len(out['rank_exits'])==ranks
