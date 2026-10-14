"""Pure full-population accumulator controls; these are not calibration data."""
from copy import deepcopy
from fractions import Fraction as F
import math
import random
import json
import struct
import time
import pytest
from ravel.physics import detector_response as dr


def contract(shared=True):
    return {'anchors': [{'point': [0]}, {'point': [1]}],
            'axes': [{'name': 'x', 'knots': [0, 1]}], 'reference_point': {'x': 0},
            'weight_name': 'nominal', 'normalization': {'scale': 7.,
            'denominator': 'sum_original_weights' if shared else 'fixed',
            'fixed_denominator': None if shared else 13., 'meaning': 'artificial control'}}


def dense_oracle(d, destinations, anchors):
    """Independent dense contraction, not a low-rank/Gram implementation.

    The reference uses original rounded float products/fsums for marks and
    then exact arithmetic for their linear residuals, as the new contract says.
    """
    weights=list(anchors[0][0]['weights']); groups=list(dict.fromkeys(r['group_id'] for r in anchors[0]))
    k=len(anchors)*len(destinations); marks={}; raw={}; all_residuals=[]
    for w in weights:
        rows=[]
        for g in groups:
            selected=[i for i,r in enumerate(anchors[0]) if r['group_id']==g]
            v=[math.fsum(anchors[a][i]['weights'][w]*anchors[a][i]['allocation'][b]
                         for i in selected) for a in range(len(anchors)) for b in range(len(destinations))]
            v.append(math.fsum(anchors[0][i]['weights'][w] for i in selected)); rows.append(v)
        marks[w]=dict(zip(groups,rows))
        raw[w]=[[math.fsum(v[i]*v[j] for v in rows) for j in range(k+1)] for i in range(k+1)]
        n=[math.fsum(v[i] for v in rows) for i in range(k)]
        den=math.fsum(v[-1] for v in rows) if d['normalization']['denominator']=='sum_original_weights' else d['normalization']['fixed_denominator']
        factor=F(d['normalization']['scale']/den)
        ratios=[F(x/den) if d['normalization']['denominator']=='sum_original_weights' else F(0) for x in n]
        all_residuals.extend([[factor*(F(v[i])-ratios[i]*F(v[-1])) for v in rows] for i in range(k)])
    cov=[[float(sum((x*y for x,y in zip(a,b)),F(0))) for b in all_residuals] for a in all_residuals]
    return marks,raw,cov


@pytest.mark.parametrize('shared',[False,True])
def test_dense_equivalence_signed_groups_all_weights_and_anchors(shared):
    rng=random.Random(27641); rows=[]
    for a in range(2):
        row=[]
        for i in range(31):
            weight=(-1. if i%7==0 else 1.)*(1.+i%3)/4
            # Correlated subevents, exact cancellations, signed alternative weights.
            row.append({'event_id':str(i),'group_id':str(i//3),
                'weights':{'nominal':weight,'alternative':weight*(1.5 if i%2 else -.5)},
                'allocation':[rng.choice([0.,0.,.25,1.]) for _ in range(4)]})
        rows.append(row)
    d=contract(shared); expected=dense_oracle(d,list('abcd'),rows)
    result=dr.summarize(d,list('abcd'),rows)
    assert result['group_marks']==expected[0]
    for w in expected[1]: assert result['weights'][w]['full_numerator_denominator_Gram']==expected[1][w]
    assert result['joint_weight_anchor_covariance']==expected[2]
    assert result['group_ids']==list(map(str,range(11)))
    assert not result['sampling_law_established'] and not result['likelihood_inferred']


def test_large_common_mark_cancellation_retains_small_exact_residual():
    # The expanded float Gram would catastrophically cancel O(1e30) terms.
    rows=[]
    for a in range(2):
        rows.append([{'event_id':str(i),'group_id':str(i),'weights':{'nominal':1.},
                     'allocation':[1e15+(-1 if i==0 else 1),0.]} for i in range(2)])
    d=contract(); expected=dense_oracle(d,['signal','zero'],rows)
    result=dr.summarize(d,['signal','zero'],rows)
    assert result['joint_weight_anchor_covariance']==expected[2]
    assert result['joint_weight_anchor_covariance'][0][0]==24.5
    assert result['joint_weight_anchor_covariance'][1]==[0.]*4


def test_exact_zero_support_count_is_after_group_cancellation():
    rows=[[{'event_id':'a','group_id':'g','weights':{'nominal':1.},'allocation':[1.,0.]},
           {'event_id':'b','group_id':'g','weights':{'nominal':-1.},'allocation':[1.,0.]},
           {'event_id':'c','group_id':'h','weights':{'nominal':2.},'allocation':[0.,0.]}] for _ in range(2)]
    r=dr.summarize(contract(False),['signal','explicit_zero'],rows)
    assert r['group_marks']['nominal']['g']==[0.]*5
    assert r['group_marks']['nominal']['h']==[0.,0.,0.,0.,2.]
    work=r['moment_work']; assert work['products']=={'event_mark':4,'normalized_mean':4,'raw_float_Gram':1,'raw_exact_Gram':1,'normalization_projection':0}
    assert work['nonzero_group_support_entries']==1
    assert r['joint_weight_anchor_covariance']==[[0.]*4 for _ in range(4)]


@pytest.mark.parametrize('mutation',['missing-event','missing-anchor','missing-zero','nonfinite-zero','weight','group'])
def test_missingness_and_nonfinite_refuse_before_support_admission(monkeypatch,mutation):
    rows=[[{'event_id':'a','group_id':'g','weights':{'nominal':1.},'allocation':[1.,0.]}] for _ in range(2)]
    if mutation=='missing-event': rows[1]=[]
    if mutation=='missing-anchor': rows.pop()
    if mutation=='missing-zero': rows[1][0]['allocation'].pop()
    if mutation=='nonfinite-zero': rows[1][0]['allocation'][1]=float('nan')
    if mutation=='weight': rows[1][0]['weights']['nominal']=2.
    if mutation=='group': rows[1][0]['group_id']='other'
    monkeypatch.setattr(dr,'MAX_MOMENT_PRODUCTS',0)
    with pytest.raises(ValueError) as error: dr.summarize(contract(False),['signal','zero'],rows)
    assert 'two million' not in str(error.value)


def test_dense_product_budget_still_refuses_full_population():
    rows=[[{'event_id':str(i),'group_id':str(i),'weights':{'nominal':1.},'allocation':[1.]*90} for i in range(1000)] for _ in range(2)]
    with pytest.raises(ValueError,match='two million actual products'):
        dr.summarize(contract(False),list(map(str,range(90))),rows)


def test_full_twenty_thousand_sparse_groups_182_coordinates(record_property):
    size=20000; dests=[f'b{i}' for i in range(90)]+['__rejected__']; rows=[]
    for a in range(2):
        row=[]
        for i in range(size):
            allocation=[0.]*91; allocation[(i+17*a)%91]=1.
            row.append({'event_id':str(i),'group_id':str(i),'weights':{'nominal':1.},'allocation':allocation})
        rows.append(row)
    start=time.perf_counter(); result=dr.summarize(contract(),dests,rows)
    elapsed=time.perf_counter()-start; record_property('twenty_thousand_seconds',elapsed)
    assert result['events']==size and len(result['group_ids'])==size and len(result['basis'])==182
    assert len(result['anchor_records'])==2 and all(len(x)==size for x in result['anchor_records'])
    assert all(len(x)==183 for x in result['group_marks']['nominal'].values())
    assert result['weights']['nominal']['sum_original_weights']==size
    assert result['moment_work']['products']['event_mark']==40000
    assert result['moment_work']['products']['raw_float_Gram']==120000
    assert result['moment_work']['products']['raw_exact_Gram']==120000
    assert result['moment_work']['total_products']<500000
    assert result['moment_work']['dense_legacy_group_product_estimate']==size*183**2
    cov=result['joint_weight_anchor_covariance']; assert len(cov)==182 and all(len(x)==182 for x in cov)
    # Each anchor partitions the identical original population. Its sum is
    # exactly constant in exact arithmetic; per-entry output rounding remains.
    counts=[sum(1 for e in rows[0] if e['allocation'][b]) for b in range(91)]
    factor=F(7./size); ratios=[F(n/size) for n in counts]
    for i in range(91):
        exact=[factor*factor*(F(counts[i] if i==j else 0)-ratios[j]*counts[i]
                  -ratios[i]*counts[j]+ratios[i]*ratios[j]*size) for j in range(91)]
        assert cov[i][:91]==list(map(float,exact))
        # Ratio division is binary64 and each final covariance entry rounds;
        # derive the error budget from these entries, not a tuned epsilon.
        error=abs(F(math.fsum(cov[i][:91]))-sum(exact,F(0)))
        bound=sum((F(math.ulp(x))/2 for x in cov[i][:91]),F(0))+F(math.ulp(math.fsum(cov[i][:91])))/2
        assert error<=bound
    assert math.fsum(result['weights']['nominal']['normalized_values'][:91])==pytest.approx(7.)
    record_property('moment_work',result['moment_work'])


def test_large_full_signed_cohort_and_joint_coordinates(record_property):
    # This is a complete artificial cohort of supplied shared-group marks in the
    # consumer, without native events, native classifier returns or physics data.
    dests=[f'family{f}/{b}b/score{s}' for f in range(3) for b in (4,5,6) for s in range(19)]+[f'rejected/{v}' for v in range(11)]; assert len(dests)==182
    rows=[]; shares=[struct.unpack('f',struct.pack('f',x))[0] for x in (1.,81.7/126.,44.3/126.)]
    families=[sorted({x.split('/')[0] for x in dests if not x.startswith('rejected/')})][0]
    for a in range(2):
        anchor=[]
        for i in range(20000):
            value=[0.]*182; weight=0. if i%31==0 else (-1. if i%17==0 else 1.)
            if i%11==0: value[177+i%5]=1.
            else:
                b=4+i%3
                for f in families:
                    indices=[j for j,x in enumerate(dests) if x.startswith(f'{f}/{b}b/')]
                    value[indices[(i+3*a)%len(indices)]]=shares[i%3]
            anchor.append({'event_id':str(i),'group_id':str(i),'weights':{'nominal':weight},'allocation':value})
        rows.append(anchor)
    start=time.perf_counter(); result=dr.summarize(contract(),dests,rows)
    record_property('six_b_shaped_twenty_thousand_seconds',time.perf_counter()-start)
    assert len(result['basis'])==364 and len(result['group_ids'])==20000
    assert all(len(v)==365 for v in result['group_marks']['nominal'].values())
    assert result['moment_work']['total_products']<=dr.MAX_MOMENT_PRODUCTS
    assert result['anchor_records']==rows
    assert any(v[-1]<0 for v in result['group_marks']['nominal'].values())
    assert any(v==[0.]*365 for v in result['group_marks']['nominal'].values())
    assert all(math.isfinite(v) for row in result['joint_weight_anchor_covariance'] for v in row)
    record_property('six_b_shaped_moment_work',result['moment_work'])
    encoder=json.JSONEncoder(sort_keys=True,separators=(',', ':'),allow_nan=False)
    size=sum(len(x.encode('utf-8')) for x in encoder.iterencode(result))+1
    record_property('six_b_shaped_compact_response_bytes',size)
    assert size<256*1024**2


def test_proportional_signed_groups_exactly_zero_delta_and_mixed_weight_denominators():
    rows=[[{'event_id':str(i),'group_id':str(i),'weights':{'nominal':d,'alternative':2*d},
            'allocation':[1.,-2.]} for i,d in enumerate((1.,2.,-1.))] for _ in range(2)]
    result=dr.summarize(contract(),['a','b'],rows)
    assert result['group_marks']['nominal']['2'][-1]==-1.
    assert result['joint_weight_anchor_covariance']==[[0.]*8 for _ in range(8)]
    assert result['joint_weight_anchor_covariance']==dense_oracle(contract(),['a','b'],rows)[2]


def test_full_twenty_thousand_ordinary_generic_response_selection_and_delivery(tmp_path,record_property):
    from test_detector_response import fixed, empty_event, refresh, execute
    d=fixed(tmp_path)
    objects=json.loads(open(d['object_contract']['path']).read());objects['weight_names']=['nominal'];refresh(d['object_contract'],objects)
    selection=json.loads(open(d['selection']['path']).read())
    selection['regions']=[{'name':f'b{i}','cuts':[{'var':'MET','op':'>=','val':i},{'var':'MET','op':'<','val':i+1}]} for i in range(90)]
    refresh(d['selection'],selection);d['normalization']={'scale':7.,'denominator':'sum_original_weights','fixed_denominator':None,'meaning':'complete artificial cohort only'}
    for a,pin in enumerate(d['anchors']):
        events=[empty_event(str(i),str(i),met=(i+17*a)%91+.5) for i in range(20000)]
        for e in events: e['weights']={'nominal':1.}
        refresh(pin['events'],events)
        assert __import__('pathlib').Path(pin['events']['path']).stat().st_size<dr.MAX_BYTES
    start=time.perf_counter(); result,out=execute(tmp_path,d)
    record_property('full_ordinary_twenty_thousand_seconds',time.perf_counter()-start)
    assert result['events']==20000 and len(result['basis'])==182
    assert len(result['group_ids'])==20000
    assert result['weights']['nominal']['sum_original_weights']==20000
    assert all(r['covariance'] is None and r['covariance_status'].startswith('deferred_to_complete') for r in result['selection_results'])
    for path in (out/'complete-response.json',tmp_path/'out/domain-result.json'):
        assert path.stat().st_size<=dr.MAX_OUTPUT_BYTES
    output_bytes=sum(p.stat().st_size for p in (tmp_path/'out').rglob('*') if p.is_file())
    assert output_bytes<=512*1024**2
    record_property('ordinary_output_bytes',output_bytes)


def test_selector_default_covariance_preserved_and_mapping_cannot_use_deferred(tmp_path):
    from test_detector_response import fixed
    from ravel.physics.reconstructed_events import run
    d=fixed(tmp_path); task={'events':d['anchors'][0]['events']['path'],
             'object_contract':d['object_contract']['path'],'selection':d['selection']['path']}
    result=run(task,tmp_path,tmp_path/'normal')
    assert result['covariance']=={'nominal':[[1.]],'twice':[[4.]]}
    assert 'covariance_status' not in result
    with pytest.raises(ValueError,match='mapping requires'):
        run({**task,'mapping':'unread'},tmp_path,tmp_path/'mapping',defer_covariance_to_response=True)
    assert not (tmp_path/'mapping').exists()
    with pytest.raises(ValueError,match='literal'):
        run(task,tmp_path,tmp_path/'badflag',defer_covariance_to_response='true')


def test_output_byte_bound_retains_partial_without_returned_acceptance(tmp_path,monkeypatch):
    monkeypatch.setattr(dr,'MAX_OUTPUT_BYTES',24)
    target=tmp_path/'partial.json'
    with pytest.raises(ValueError,match='complete response result exceeds'):
        dr.write_complete_json({'all_rows':[1.]*100},target)
    assert 0<target.stat().st_size<=24
    with pytest.raises(json.JSONDecodeError): json.loads(target.read_bytes())


def test_common_worker_generic_response_uses_bounded_result_writer(tmp_path,monkeypatch):
    from ravel.physics import science_worker as worker
    from ravel.plotting import science_figures
    spec={'schema_version':2,'mode':'domain','task':{'domain':'detector-response','config':{}},
          'assumptions':['Source-only writer control; admission and adapter injected']}
    result={'status':'passed','physics_validated':False,'details':{'all_coordinates':[0.]*20}}
    class Injected:
        @staticmethod
        def run(*args):return result
    monkeypatch.setattr(worker,'verify_worker',lambda root:{'base_dir':str(tmp_path),
        'output_directory':'outputs','stage_binding':{'input_snapshot':[]}})
    monkeypatch.setattr(worker,'execution_spec',lambda root:spec)
    monkeypatch.setattr(worker,'adapter',lambda spec:Injected)
    monkeypatch.setattr(science_figures,'render',lambda *args:{'figures':[],'tables':[]})
    monkeypatch.setattr(dr,'MAX_OUTPUT_BYTES',8)
    with pytest.raises(ValueError,match='complete response result exceeds'):
        worker.main([str(tmp_path/'ordinary')])
    assert (tmp_path/'ordinary/outputs/result.json').exists()
    assert not (tmp_path/'ordinary/outputs/verification.json').exists()
    assert not (tmp_path/'ordinary/outputs/checkin2.json').exists()
