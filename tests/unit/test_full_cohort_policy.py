import copy
from fractions import Fraction
import hashlib,json,math
import pytest
from ravel.physics import group_normalization as g
from ravel.physics import group_composition as c
import test_group_normalization as f
import test_group_composition as cf
from pathlib import Path

POLICY={'method':'vectorized_products_compensated_sum_v1',
        'maximum_groups':20000,'maximum_pair_group_products':100_000_000}


def test_policy_small_population_exact_values_and_matrix(tmp_path):
    contract,acquired=f.fixture(tmp_path)
    old=g.normalize(contract,acquired)
    contract['arithmetic_policy']=POLICY
    new=g.normalize(contract,acquired)
    for field in ['input_values','input_covariance','values','jacobian','output_covariance',
                  'input_groups','linearized_group_vectors','counter_diagnostics']:
        assert new[field]==old[field]
    assert 'arithmetic_admission' not in old
    assert new['arithmetic_admission']['policy']==POLICY


def test_whole_20000_normalization_and_legacy_refusal(tmp_path):
    contract,acquired=f.fixture(tmp_path)
    groups=acquired['uncertainty']['groups']; events=acquired['normalization_event_weights']
    acquired['uncertainty']['groups']=[{**groups[i%5],'id':'a'*64+':'+str(i)} for i in range(20000)]
    acquired['normalization_event_weights']=[{**events[i%5],'id':'a'*64+':'+str(i)} for i in range(20000)]
    acquired['values']=[x*4000 for x in acquired['values']]
    acquired['source_file_encounter_groups']=20000
    for row in acquired['normalization_counter_by_weight'].values():
        row['sumw']*=4000;row['sumw2']*=4000;row['entries']=20000
        row['raw_tokens']=[str(row['sumw']),str(row['sumw2']),'20000']
    f.save_original(contract,acquired,tmp_path);f.save_acquired(contract,acquired,tmp_path)
    with pytest.raises(ValueError,match='group/counter census'):g.normalize(contract,acquired)
    contract['arithmetic_policy']=POLICY
    result=g.normalize(contract,acquired)
    assert len(result['input_groups'])==20000
    assert result['counter_diagnostics']['nominal']['sumw']==16000
    assert result['counter_diagnostics']['nominal']['sumw2']==30000
    assert result['counter_diagnostics']['nominal']['entries']==20000
    # Full emitted-J/group Gram, independent exact rational contraction of the
    # five repeated vectors. This includes the shared counter/cross-weight law.
    J=result['jacobian']; V=[r['vector'] for r in result['input_groups'][:5]]
    phi=[[sum((Fraction(j)*Fraction(v) for j,v in zip(row,group)),Fraction(0)) for group in V] for row in J]
    bounds=result['arithmetic_admission']['output_entry_forward_error_bounds']
    for i in range(len(J)):
        for j in range(len(J)):
            exact=4000*sum((a*b for a,b in zip(phi[i],phi[j])),Fraction(0))
            assert abs(Fraction(result['output_covariance'][i][j])-exact)<=Fraction(bounds[i][j])


@pytest.mark.parametrize('bad',[None,{}, {'method':'BLAS'},
    {**POLICY,'maximum_groups':True},{**POLICY,'maximum_groups':20001},
    {**POLICY,'maximum_pair_group_products':100_000_001}, {**POLICY,'extra':1}])
def test_policy_refuses_before_public_worker(tmp_path,bad):
    contract,acquired=f.fixture(tmp_path);contract['arithmetic_policy']=bad
    path=tmp_path/'contract.json';path.write_text(json.dumps(contract))
    task={'schema_version':1,'input':str(path),'contract_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    with pytest.raises(ValueError):g.inputs(task,tmp_path)


def test_composition_and_rebin_schema_bind_budget():
    # Missing future source files are irrelevant to pure policy/schema admission.
    contract={'schema_version':1,'kind':'same-event-group-composition-contract','sources':[],
              'arms':[{'id':'NU','kind':'original_native_supplied','source':'NU'},
                      {'id':'EL','kind':'original_native_supplied','source':'EL'}],
              'group_join':'exact_ordered_source_sha256_encounter',
              'counter_policy':'share_one_counter_per_weight','arithmetic_policy':POLICY}
    c.composition_schema(contract)
    assert g.arithmetic_budget(contract,65,20000)==POLICY
    with pytest.raises(ValueError):g.arithmetic_budget(contract,71,20000)
    contract['arithmetic_policy']={**POLICY,'maximum_groups':19999}
    with pytest.raises(ValueError):g.arithmetic_budget(contract,65,20000)


def test_full_20000_same_event_coordinate_route_to_48_components(tmp_path):
    # Every supplied group is retained, including signed, zero and no-fill
    # events. These are fabricated source traces, not acquired native events.
    pattern_weights=[[2.],[-.5],[0.],[1.],[1.]]
    nu=[[(0,225.),(1,225.),(2,300.),(3,math.pi)],[],
        [(0,100.)],[(0,1500.),(3,2.094395)],[(0,325.),(3,2.617994)]]
    el=[[(0,225.),(3,math.pi)],[(0,275.),(3,2.094396)],
        [],[(1,275.),(2,700.)],[(0,325.),(3,2.617993)]]
    arms=[]
    for name,coordinates in [('NU',nu),('EL',el)]:
        _,normal,acquired,rebin=cf.native(tmp_path/name,name,
            coordinates*4000,['nominal'],pattern_weights*4000)
        acquired['source_file_encounter_groups']=20000
        acquired['normalization_counter_by_weight']['nominal']['entries']=20000
        acquired['normalization_counter_by_weight']['nominal']['raw_tokens'][-1]='20000'
        acquired_path=Path(next(p['path'] for p in normal['sources'] if p['id']=='acquired'))
        ap=cf.save(acquired_path,acquired,'acquired')
        normal['sources']=[ap if p['id']=='acquired' else p for p in normal['sources']]
        normal['arithmetic_policy']=POLICY
        np=cf.save(acquired_path.parent/'normalization.json',normal,'normalization')
        rebin['sources']=[np if p['id']=='normalization' else p for p in rebin['sources']]
        rebin['arithmetic_policy']=POLICY
        arms.append((cf.save(acquired_path.parent/'rebin.json',rebin,name),normal,acquired,rebin))
    contract={'schema_version':1,'kind':'same-event-group-composition-contract',
              'sources':[a[0] for a in arms],
              'arms':[{'id':'numerator','kind':'source_coordinate_rebin','source':'NU'},
                      {'id':'denominator','kind':'source_coordinate_rebin','source':'EL'}],
              'group_join':'exact_ordered_source_sha256_encounter',
              'counter_policy':'share_one_counter_per_weight','arithmetic_policy':POLICY}
    task,_,basis=cf.measurement_contract((contract,*arms),tmp_path)
    assert len(c.inputs(task,tmp_path))==19
    result=c.run(task,tmp_path,tmp_path/'full-output')
    assert len(result['input_groups'])==20000 and len(result['input_basis'])==65
    assert len(result['values'])==64
    assert result['input_values'][-1]==14000.
    assert result['input_covariance'][-1][-1]==25000.
    assert sum(row['kind']=='normalization_counter' for row in result['input_basis'])==1
    assert any(v!=0 for row in result['output_covariance'][:32] for v in row[32:])
    J=result['jacobian'];V=[row['vector'] for row in result['input_groups'][:5]]
    phi=[[sum((Fraction(j)*Fraction(v) for j,v in zip(row,group)),Fraction()) for group in V] for row in J]
    bounds=result['arithmetic_admission']['output_entry_forward_error_bounds']
    for i in range(64):
        for j in range(64):
            exact=4000*sum((a*b for a,b in zip(phi[i],phi[j])),Fraction())
            assert abs(Fraction(result['output_covariance'][i][j])-exact)<=Fraction(bounds[i][j])
    sliced=result['measurement_components']
    assert sliced['basis']==basis and len(sliced['joint_prediction_covariance'])==48
    assert any(v!=0 for row in sliced['joint_prediction_covariance'][:24] for v in row[24:])
    assert not sliced['native_acquisition_qualified']
    assert sliced['experimental_independence'] is None
    assert (tmp_path/'full-output/group-composition.json').is_file()
    assert (tmp_path/'full-output/normalized-joint.json').is_file()
    assert (tmp_path/'full-output/measurement-components.json').is_file()
