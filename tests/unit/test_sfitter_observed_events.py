"""Pure full-format returned-record controls; no native/SDK/model execution."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import numpy as np
import pytest

from ravel.physics import sfitter_observed_events as o, model_event_weights as mw, analysis_ir
from ravel.physics import sfitter_scan_extraction as extract
from ravel.physics import group_arithmetic
from ravel.workflow import science, agent_graph, agent_host
from ravel.cli import main as cli_main
from test_sfitter_scan_extraction import fixture as scan_fixture
from test_sfitter_adapter import save, pin


def fixture(tmp, law='fixed_N_IID_groups', random=False, grouped=False, tiny=False):
    base, old, _, wf, docs, config, rates, coef, _=scan_fixture(tmp)
    source=base/'source.txt';source.write_text('Artificial observed group law, exact supplied original-object identity, fixed scale and point-independent response. No physical/native qualification.')
    sp=pin(source);points=rates['points'];names=['nominal',*[p['id'] for p in points]]
    for p in points: p['selected_weight']=p['id'];p['weight_population']=[]
    definition=json.loads(Path(old['scan_definition']['path']).read_bytes())
    for p in definition['points']:p['selected_weight']=p['id'];p['weight_ids']=names
    dp=save(base/'scan-definition.json',definition)
    old['scan_definition']=dp;old.pop('rates');template=save(base/'extractor-template.json',old)
    bins=rates['bins'];bp=save(base/'bins.json',bins)
    groups=[{'name':'scan','combine':'none','ids':names[1:]}]
    header='<LesHouchesEvents version="3.0"><header><initrwgt><weightgroup name="scan" combine="none">'+''.join('<weight id="'+name+'">'+name+'</weight>' for name in names[1:])+'</weightgroup></initrwgt></header><init>\n2212 2212 6500 6500 0 0 0 0 -4 1\n1 0 1 1\n</init>\n'
    population=[];lhe=base/'returned.lhe'
    for i,nominal in enumerate(('1e-400' if tiny else '1','1.5','1','1.5','-0')):
        # Nonzero event-level residual variation, cancelling exactly in each bin total.
        values=[repr(p['rates'][i%2]/2 + (1 if i<2 else -1)*2.*math.sin(j+1)) if i<4 else '-0' for j,p in enumerate(points)]
        body='<event>\n1 1 '+nominal+' 91 0.007 0.118\n22 1 0 0 0 0 0 0 10 10 0 0 9\n<rwgt>'+''.join('<wgt id="'+name+'">'+value+'</wgt>' for name,value in zip(names[1:],values))+'</rwgt>\n</event>\n'
        population.append(body)
    lhe.write_text(header+''.join(population)+'</LesHouchesEvents>\n');lp=pin(lhe)
    with tempfile.TemporaryDirectory() as td:
        journal=Path(td)/'events.jsonl';mw.scan(lhe,expected_events=5,expected_groups=groups,maximum_bytes=1024**2,journal_path=journal)
        original=[json.loads(line) for line in journal.read_bytes().splitlines()]
    # Run the actual existing IR producer with real typed source and event objects.
    nodes=[{'id':'met','op':'met'},{'id':'pt','op':'field','args':['met'],'field':'pt'},
      {'id':'one','op':'const','value':1,'unit':'GeV'},{'id':'fifteen','op':'const','value':15,'unit':'GeV'},
      {'id':'sixteen','op':'const','value':16,'unit':'GeV'},
      {'id':'positive','op':'compare','args':['pt','one'],'comparison':'ge'},
      {'id':'low','op':'compare','args':['pt','fifteen'],'comparison':'le'},
      {'id':'high','op':'compare','args':['pt','sixteen'],'comparison':'ge'}]
    program={'schema_version':1,'name':'source_only_control','nodes':nodes,'regions':[{'name':'left','cuts':['positive','low']},{'name':'right','cuts':['high']}]}
    contract={'schema_version':1,'level':'reconstructed','source':'explicit artificial engineering fixture','energy_unit':'GeV',
        'flags':{'electron':{},'muon':{},'jet':{}},'response_evidence':[str(source)],'weight_names':['nominal']}
    events=[{'event_id':'e'+str(i),'group_id':'g0' if grouped and i<2 else 'g'+str(i), 'weights':{'nominal':float(row['nominal'])},
        'objects':{'electron':[],'muon':[],'jet':[]},'met':{'pt':10 if i in (0,2) else 20 if i in (1,3) else 0,'phi':0}} for i,row in enumerate(original)]
    pp=save(base/'program.json',program);cp=save(base/'contract.json',contract);ep=save(base/'objects.json',events)
    join={'schema_version':1,'lhe_sha256':lp['sha256'],'records':[{'event_id':e['event_id'],'ordinal':i,'canonical_event_sha256':r['canonical_event_sha256'],'reconstructed_event_sha256':agent_graph.digest(e)} for i,(e,r) in enumerate(zip(events,original))],'sources':[sp]}
    jp=save(base/'original-object-join.json',join)
    irconfig={'schema_version':1,'generator':{'lhe':lp,'events':5,'weight_groups':groups,'maximum_decoded_bytes':1024**2},
              'original_join':jp,'bins':bp,'region_bins':['left','right'],'sources':[sp],
              'response_weight_policy':{'kind':'weight_invariant_same_objects','source':sp,'description':'Explicit fixture premise; the same source IR masks apply to all original reweights'}}
    ip=save(base/'ir-observation.json',irconfig)
    task={'backend':'analysis-ir','program':pp['path'],'contract':cp['path'],'events':ep['path'],'sfitter_observation':ip['path']}
    producer=tmp/'producer';result=analysis_ir.run(task,base,producer)
    produced=result['sfitter_observation'];receipt=pin(producer/'sfitter-observation-producer.json')
    gp=save(base/'groups.json',{'schema_version':1,'lhe_sha256':lp['sha256'],'group_ids':[e['group_id'] for e in events],
          'description':'Explicit fixture correlation groups; independent between listed groups','sources':[sp]})
    cohort={'id':'shared','point_ids':[p['id'] for p in points],'generator':{**irconfig['generator'],'sources':[sp]},
            'analysis':{'trace':produced['trace'],'source':pp,'execution_evidence':receipt,'bin_definition':bp,'producer_kind':'analysis_ir_complete_decisions'},'grouping':gp,
            'sampling':{'law':law,'description':'Explicit artificial '+law+' law','source':sp}}
    request={'schema_version':1,'id':'observed_control','extractor_template':template,'cohorts':[cohort],
      'relationships':{'kind':'one_shared_reweight_cohort','description':'All original reweights and heldout are on the same complete source events','source':sp},
      'normalization':[{'point_id':p['id'],'scale':[2.,2.],'scale_uncertainty':'conditional_fixed',
        'denominator':{'kind':'observed_weight_sum' if random else 'fixed_external','values':None if random else [5.,5.],
                       'weight_id':'nominal' if random else None}, 'description':'Explicit fixed cross-section/luminosity coefficients; shared nominal denominator, never each reweight sum','source':sp} for p in points]}
    rp=save(base/'bridge-request.json',request)
    return base,request,rp,coef,events,original,task,result


@pytest.mark.parametrize('law',['fixed_N_IID_groups','poissonized_independent_groups'])
@pytest.mark.parametrize('random',[False,True])
def test_actual_analysis_to_complete_signed_scan_extractor(tmp_path,law,random):
    base,r,rp,coef,*_=fixture(tmp_path,law,random)
    receipt=o.materialize(rp,base,tmp_path/'delivery')
    request=json.loads(Path(receipt['extraction_request']['path']).read_bytes())
    result=extract.extract(request,Path(receipt['extraction_request']['path']).parent)
    assert result['status']=='passed' and result['design']['rank']==46
    assert np.allclose(result['coefficients'],coef,rtol=1e-12,atol=1e-12)
    report=json.loads(Path(receipt['diagnostics']['path']).read_bytes())
    deck=report['rate_deck'];q=len(deck['points'])*2
    assert len(deck['joint_covariance']['matrix'])==q*(2 if random else 1)
    assert all(p['weight_population'][0]['events']==5 for p in deck['points'])
    assert deck['points'][-1]['role']=='held_out' and not deck['points'][-1]['independence']['declared']
    rows=np.array(report['cohorts'][0]['group_vectors']);centered=rows-rows.mean(axis=0)
    C=centered.T@centered*5/4 if law=='fixed_N_IID_groups' else rows.T@rows
    assert np.allclose(deck['joint_covariance']['matrix'],C if random else C[:q,:q],rtol=1e-12,atol=1e-12)
    if random:
        assert deck['points'][1]['normalization']['denominator']==[5.,5.]
        assert C[0,q+2]==C[0,q] # same singular denominator repeated for each point/bin
    assert report['native_calls']==0 and report['physics_validated'] is False


def test_subevents_aggregate_before_all_products(tmp_path):
    base,r,*_=fixture(tmp_path,'poissonized_independent_groups',grouped=True)
    result=o.acquire(r,base)[0];rows=result['cohorts'][0]['group_vectors']
    assert len(rows)==4 and rows[0][0]!=0 and rows[0][1]!=0
    C=result['rate_deck']['joint_covariance']['matrix']
    assert C[0][1]==pytest.approx(rows[0][0]*rows[0][1])


@pytest.mark.parametrize('kind',['missing_event','original_hash','weight','missing_weight','extra_weight','veto_fill','unknown_bin','missing_point','missing_group','group_reappears','unknown_law','unknown_relationship','wrong_bins','wrong_eft','uncertain_scale','selected_denominator_missing','zero_denominator','corrupt_source'])
def test_material_observation_adversaries(tmp_path,kind):
    base,r,*_=fixture(tmp_path)
    cohort=r['cohorts'][0];trace=Path(cohort['analysis']['trace']['path']);rows=[json.loads(x) for x in trace.read_bytes().splitlines()]
    if kind=='missing_event':rows.pop()
    elif kind=='original_hash':rows[1]['canonical_event_sha256']='0'*64
    elif kind=='weight':rows[1]['weights'][0]['value']='999'
    elif kind=='missing_weight':rows[1]['weights'].pop()
    elif kind=='extra_weight':rows[1]['weights'].append({'id':'fake','value':'0'})
    elif kind=='veto_fill':rows[1]['vetoed']=True
    elif kind=='unknown_bin':rows[1]['fills'][0]['bin_index']=99
    elif kind=='missing_point':cohort['point_ids'].pop()
    elif kind in ('missing_group','group_reappears'):
        path=Path(cohort['grouping']['path']);doc=json.loads(path.read_bytes())
        doc['group_ids']=['g0','g1','g0'] if kind=='group_reappears' else ['g0']
        cohort['grouping']=save(path,doc)
    elif kind=='unknown_law':cohort['sampling']['law']='inferred_from_count'
    elif kind=='unknown_relationship':r['relationships']['kind']='independent_because_heldout'
    elif kind=='wrong_bins':rows[0]['bins'][0]['unit']='fb'
    elif kind=='wrong_eft':
        tp=Path(r['extractor_template']['path']);doc=json.loads(tp.read_bytes());wp=Path(doc['workflow']['path']);wf=json.loads(wp.read_bytes());wf['target']['eft']['target_scale_gev']=999.
        doc['workflow']=save(wp,wf);r['extractor_template']=save(tp,doc)
    elif kind=='uncertain_scale':r['normalization'][0]['scale_uncertainty']='use_header_error'
    elif kind=='selected_denominator_missing':r['normalization'][0]['denominator']={'kind':'observed_weight_sum','values':None,'weight_id':'fake'}
    elif kind=='zero_denominator':r['normalization'][0]['denominator']['values']=[0.,5.]
    elif kind=='corrupt_source':Path(cohort['analysis']['source']['path']).write_text('changed source')
    if kind in ('missing_event','original_hash','weight','missing_weight','extra_weight','veto_fill','unknown_bin','wrong_bins'):
        trace.write_text(''.join(json.dumps(row)+'\n' for row in rows));cohort['analysis']['trace']=pin(trace)
    with pytest.raises((ValueError,KeyError,StopIteration)):o.acquire(r,base)


def test_end_generated_bytes_refuse_without_recapture(tmp_path,monkeypatch):
    base,r,rp,*_=fixture(tmp_path)
    real=o._write
    def corrupt(path,doc,cap):
        value=real(path,doc,cap)
        if path.name=='event-rate-receipt.json':
            p=path.parent/'observed-scan-rates.json';raw=json.loads(p.read_bytes());raw['points'][0]['rates'][0]+=1;p.write_text(json.dumps(raw))
        return value
    monkeypatch.setattr(o,'_write',corrupt)
    with pytest.raises(ValueError):o.materialize(rp,base,tmp_path/'bad')


def test_writer_late_output_corruption_refuses(tmp_path):
    w=o.ObservationWriter(tmp_path/'trace.jsonl',{'header':'source'})
    w.record({'ordinal':0});w.path.write_text('changed\n')
    with pytest.raises(ValueError):w.finish(1)


def test_original_ir_join_missing_or_changed_refuses_without_new_trace(tmp_path):
    base,r,_,_,events,_,task,_=fixture(tmp_path)
    p=Path(task['sfitter_observation']);c=json.loads(p.read_bytes());jpath=Path(c['original_join']['path']);j=json.loads(jpath.read_bytes());j['records'][0]['reconstructed_event_sha256']='0'*64
    c['original_join']=save(jpath,j);save(p,c)
    with pytest.raises(ValueError,match='join'):analysis_ir.run(task,base,tmp_path/'bad-ir')


def test_whole_graph_host_and_public_cli(tmp_path):
    base,r,rp,*_=fixture(tmp_path)
    graph=o.graph(r,base,rp);host=agent_host.AgentHost(api_key='not-used')
    # Actual ordinary Graph scheduling/tool route, no provider or synthetic provider reply.
    agent_graph.create(tmp_path/'graph',graph);assert agent_graph.execute(tmp_path/'graph',host,workers=1)['complete']
    assert cli_main(['sfitter-observed-events','--request',rp['path'],'--output',str(tmp_path/'cli')])==0
    assert (tmp_path/'cli'/'scan-extraction-request.json').is_file()


def test_source_mode_scope_and_no_unapproved_run(tmp_path):
    base,r,rp,*_=fixture(tmp_path)
    task={'request':rp['path']};assert science.adapter({'mode':'sfitter-observed-events','task':task}) is o
    with pytest.raises(ValueError,match='approved'):o.run(task,base,tmp_path/'unapproved')


def test_real_ordinary_unapproved_plan_and_complete_input_population(tmp_path):
    from test_sfitter_adapter import specification
    base,r,rp,*_=fixture(tmp_path)
    spec=specification({'request':rp['path']});spec['mode']='sfitter-observed-events'
    spec['review_policy']['policy']['claim_scopes']={o.SCOPE:{'checks':['integrity'],'actions':['delivery']}}
    science.validate(spec);sp=save(base/'science.json',spec)
    rd=tmp_path/'ordinary';plan=science.plan(rd,sp['path'])
    assert science.verify_plan(rd,approved=False)==plan
    assert Path(r['cohorts'][0]['generator']['lhe']['path']) in science.task_inputs(spec,base)
    assert not (rd/'inputs/science-approval.json').exists()


def supplier_trace(base, request):
    """Test only the explicitly weaker supplier branch; never label this replay."""
    request=deepcopy(request)
    request['cohorts'][0]['analysis']['producer_kind']='supplied_observations'
    return request


@pytest.mark.parametrize('weight_index',[0,1,-1])
def test_original_signed_zero_mismatch_and_decimal_population(tmp_path,weight_index):
    base,r,*_=fixture(tmp_path)
    report=o.acquire(r,base)[0]
    nominal=report['rate_deck']['points'][0]['weight_population'][0]
    assert nominal=={'id':'nominal','events':5,'positive':4,'negative':0,'zero':1,'sumw':'5.0','sumw2':'6.50'}
    r=supplier_trace(base,r);a=r['cohorts'][0]['analysis'];p=Path(a['trace']['path'])
    rows=[json.loads(line) for line in p.read_bytes().splitlines()]
    assert rows[-1]['weights'][weight_index]['value']=='-0'
    rows[-1]['weights'][weight_index]['value']='+0.0'
    p.write_text(''.join(json.dumps(row)+'\n' for row in rows));a['trace']=pin(p)
    with pytest.raises(ValueError,match='signed event weight'):o.acquire(r,base)


def test_nonzero_decimal_underflow_refuses_before_population_relabel(tmp_path):
    with pytest.raises(ValueError,match='nonzero decimal underflow'):fixture(tmp_path,tiny=True)
    with tempfile.TemporaryDirectory() as td:
        p=next(tmp_path.rglob('returned.lhe'));jp=Path(td)/'full.jsonl'
        # The original literal parser still recognizes the positive tiny weight.
        groups=[{'name':'scan','combine':'none','ids':[x['id'] for x in json.loads((p.parent/'scan-definition.json').read_bytes())['points']]}]
        census=mw.scan(p,expected_events=5,expected_groups=groups,maximum_bytes=1024**2,journal_path=jp)
        assert census['signed_nominal_counts']=={'positive':4,'negative':0,'zero':1}
        assert json.loads(jp.read_bytes().splitlines()[0])['nominal']=='1E-400'


def test_join_nested_dependency_is_captured_before_optional_producer(tmp_path):
    base,r,_,_,_,_,task,_=fixture(tmp_path)
    cp=Path(task['sfitter_observation']);config=json.loads(cp.read_bytes());jp=Path(config['original_join']['path'])
    unique=base/'nested-only-evidence.txt';unique.write_text('Nested original-object lineage evidence; source-only control')
    join=json.loads(jp.read_bytes());join['sources'].append(pin(unique));config['original_join']=save(jp,join);save(cp,config)
    assert unique in analysis_ir.inputs(task,base)
    analysis_ir.run(task,base,tmp_path/'second-ir')


@pytest.mark.parametrize('kind',['order','member','bytes'])
def test_actual_producer_bundle_order_membership_and_ending_bytes(tmp_path,monkeypatch,kind):
    base,r,*_=fixture(tmp_path)
    a=r['cohorts'][0]['analysis'];p=Path(a['execution_evidence']['path']);doc=json.loads(p.read_bytes())
    root=Path(doc['analysis_witness']['manifest']['path']).parent
    if kind=='order':
        doc['analysis_consumed_weights']=['fake','nominal'];a['execution_evidence']=save(p,doc)
        with pytest.raises(ValueError,match='stream order'):o.acquire(r,base)
    else:
        real=group_arithmetic.gram;r['cohorts'][0]['sampling']['law']='poissonized_independent_groups'
        late_calls=[]
        def late(*args,**kwargs):
            result=real(*args,**kwargs)
            late_calls.append((result['groups'],result['coordinates']))
            if kind=='member':(root/'unindexed-scientific.json').write_text('{"new":1}')
            else:(root/'verification.json').write_text('{"passed":true,"fabricated":true}')
            return result
        monkeypatch.setattr(group_arithmetic,'gram',late)
        with pytest.raises(ValueError,match='ending|identity changed'):o.acquire(r,base)
        # The active acquire() local import must reach this same kernel exactly
        # once with all five original groups and both rate/denominator vectors.
        assert late_calls==[(5,4*len(r['cohorts'][0]['point_ids']))]
        changed=root/('unindexed-scientific.json' if kind=='member' else 'verification.json')
        expected=b'{"new":1}' if kind=='member' else b'{"passed":true,"fabricated":true}'
        assert changed.read_bytes()==expected
        (tmp_path/'late-mutation-observation.json').write_text(json.dumps({
            'kind':kind,'late_calls':late_calls,'producer_root':str(root),
            'mutated_file':str(changed),'mutation_sha256':hashlib.sha256(expected).hexdigest(),
            'ending_refusal_reached':True},sort_keys=True)+'\n')


def test_expected_bytes_must_match_before_first_generated_capture(tmp_path,monkeypatch):
    base,r,rp,*_=fixture(tmp_path)
    real=o.Capture.read
    def changed(self,value,base,expected=None):
        p=Path(value)
        if p.name=='observed-scan-rates.json' and expected is not None:
            doc=json.loads(p.read_bytes());doc['points'][0]['rates'][0]+=2;p.write_text(json.dumps(doc))
        return real(self,value,base,expected)
    monkeypatch.setattr(o.Capture,'read',changed)
    with pytest.raises(ValueError,match='bytes changed'):o.materialize(rp,base,tmp_path/'immediate')


def test_supplied_observation_branch_has_no_execution_or_replay_authority(tmp_path):
    base,r,*_=fixture(tmp_path);r=supplier_trace(base,r)
    report=o.acquire(r,base)[0];acquisition=report['cohorts'][0]['acquisition']
    assert acquisition=={'producer_kind':'supplied_observations','analysis_decisions_replayed':False,
                         'ordinary_execution_verified':False,'native_transport_qualified':False}


def test_complete_independent_point_runs_have_no_invented_crosspoint_covariance(tmp_path):
    base,r,_,coef,events,_,task,_=fixture(tmp_path)
    old=r['cohorts'][0];configuration=json.loads(Path(task['sfitter_observation']).read_bytes())
    cohorts=[]
    for index,point_id in enumerate(old['point_ids']):
        arm=base/('point-run-'+str(index));arm.mkdir()
        # Distinct supplied event content. Independence remains a declaration,
        # not a consequence of this engineered file or distinct event hash.
        raw=Path(old['generator']['lhe']['path']).read_text().replace('0 0 10 10 0 0 9','0 0 '+str(20+index)+' '+str(20+index)+' 0 0 9')
        lp=arm/'original.lhe';lp.write_text(raw);lp=pin(lp)
        with tempfile.TemporaryDirectory() as td:
            jp=Path(td)/'journal.jsonl';mw.scan(lp['path'],expected_events=5,expected_groups=old['generator']['weight_groups'],maximum_bytes=1024**2,journal_path=jp)
            originals=[json.loads(line) for line in jp.read_bytes().splitlines()]
        config=deepcopy(configuration);config['generator']['lhe']=lp
        join={'schema_version':1,'lhe_sha256':lp['sha256'],'records':[{'event_id':e['event_id'],'ordinal':i,'canonical_event_sha256':row['canonical_event_sha256'],'reconstructed_event_sha256':agent_graph.digest(e)} for i,(e,row) in enumerate(zip(events,originals))],'sources':configuration['sources']}
        config['original_join']=save(arm/'join.json',join);ip=save(arm/'observation.json',config)
        local={**task,'sfitter_observation':ip['path']};out=tmp_path/('point-producer-'+str(index))
        produced=analysis_ir.run(local,base,out)['sfitter_observation'];cohort=deepcopy(old)
        cohort.update(id='run-'+str(index),point_ids=[point_id]);cohort['generator']['lhe']=lp
        cohort['analysis']['trace']=produced['trace'];cohort['analysis']['execution_evidence']=pin(out/'sfitter-observation-producer.json')
        grouping=json.loads(Path(old['grouping']['path']).read_bytes());grouping['lhe_sha256']=lp['sha256'];cohort['grouping']=save(arm/'groups.json',grouping)
        cohorts.append(cohort)
    r['cohorts']=cohorts;r['relationships']['kind']='declared_independent_cohorts'
    r['relationships']['description']='Explicit artificial independent-run premise; content identity is not evidence of sampling independence'
    rp=save(base/'independent-request.json',r);receipt=o.materialize(rp,base,tmp_path/'independent-delivery')
    request=json.loads(Path(receipt['extraction_request']['path']).read_bytes());result=extract.extract(request,Path(receipt['extraction_request']['path']).parent)
    assert result['status']=='passed' and np.allclose(result['coefficients'],coef,rtol=1e-12,atol=1e-12)
    report=json.loads(Path(receipt['diagnostics']['path']).read_bytes());C=np.array(report['rate_deck']['joint_covariance']['matrix'])
    assert len(report['cohorts'])==48 and all(point['independence']['declared'] for point in report['rate_deck']['points'])
    assert not report['independence_proven'] and not report['sampling_law_validated']
    for i in range(48):
        for j in range(48):
            if i!=j:assert not np.any(C[2*i:2*i+2,2*j:2*j+2])
    assert len(report['source_population'])>512
    with pytest.raises(ValueError,match='Graph population exceeds'):o.graph(r,base,rp)


def test_unconsumed_original_reweight_underflow_refuses_full_bridge(tmp_path):
    base,r,*_=fixture(tmp_path);r=supplier_trace(base,r);cohort=r['cohorts'][0]
    p=Path(cohort['generator']['lhe']['path']);text=p.read_text();name=cohort['generator']['weight_groups'][0]['ids'][0]
    start=text.index('<wgt id="'+name+'">')+len('<wgt id="'+name+'">');end=text.index('</wgt>',start)
    p.write_text(text[:start]+'1e-400'+text[end:]);cohort['generator']['lhe']=pin(p)
    with tempfile.TemporaryDirectory() as td:
        jp=Path(td)/'events.jsonl';mw.scan(p,expected_events=5,expected_groups=cohort['generator']['weight_groups'],maximum_bytes=1024**2,journal_path=jp)
        originals=[json.loads(line) for line in jp.read_bytes().splitlines()]
    trace=Path(cohort['analysis']['trace']['path']);rows=[json.loads(line) for line in trace.read_bytes().splitlines()]
    rows[0]['lhe_sha256']=cohort['generator']['lhe']['sha256']
    for row,original in zip(rows[1:],originals):
        row['canonical_event_sha256']=original['canonical_event_sha256'];row['weights']=[{'id':'nominal','value':original['nominal']},*original['weights']]
    trace.write_text(''.join(json.dumps(row)+'\n' for row in rows));cohort['analysis']['trace']=pin(trace)
    gp=Path(cohort['grouping']['path']);doc=json.loads(gp.read_bytes());doc['lhe_sha256']=cohort['generator']['lhe']['sha256'];cohort['grouping']=save(gp,doc)
    with pytest.raises(ValueError,match='nonzero decimal underflow'):o.acquire(r,base)


def test_covariance_law_falsifiers_are_not_marginal_weight_shortcuts():
    # Sub-events are summed inside their original group before any products.
    grouped=[[2.-1.,2*(2.-1.)]]
    C=group_arithmetic.gram(list(map(list,zip(*grouped))),maximum_pair_products=100)['matrix']
    assert C==[[1.,2.],[2.,4.]] and C[0][0]!=2.**2+(-1.)**2
    assert C[1][1]+4*C[0][0]-4*C[0][1]==0 # H=2Y has zero residual variance.
    # A shared random denominator identical to its numerator has J S=0.
    C=o.marked_response.empirical_group_mean([[1.,1.],[3.,3.]])['covariance']
    J=[.5,-.5];assert math.fsum(J[i]*C[i][j]*J[j] for i in range(2) for j in range(2))==0
    # Denominator choice is independent of the selected reweight: common
    # nominal D preserves a doubled rate; point-wise own sums erase it.
    assert 2*4/2==2*(2*2/2) and 2*4/4==2*2/2
