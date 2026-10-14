"""Source-bound lepton associations, complete populations and shared-event moments."""
import copy
import gzip
import json
import math

import pytest

from ravel.physics import truth_reco_response as response
from response_fixture import contract,join_contract
from ravel.physics import compressed_validation


def analyze(event,*,expect_four_state=True,**kwargs):
    policy=contract()
    if not expect_four_state:policy['topology']=[]
    return response.analyze_event(event,contract=policy,**kwargs)

def run(*args,**kwargs):return response.run(*args,contract=contract(),**kwargs)
def join(*args,**kwargs):return response.validate_native_join(*args,join_contract=join_contract(),**kwargs)

def particle(pid, uid, mother=-1, *, status=1, pt=6., eta=.2, m2=-1):
    return dict(pid=pid, uid=uid, m1=mother, m2=m2, status=status, pt=pt, eta=eta, phi=.1, energy=pt*math.cosh(eta))


def event(*, entry=0, number=41, matched=True, weight=1.):
    # Non-consecutive UIDs deliberately differ from Particle array indices.
    particles = [particle(1000011, 900, status=22), particle(-1000011, 200, status=22),
                 particle(11, 37, 0), particle(-11, 89, 1),
                 particle(1000022, 56, 0), particle(1000022, 99, 1)]
    reco = [dict(index=i, flavour='electron', ref=p['uid'], pt=7., eta=.3, phi=.1)
            for i, p in enumerate(particles[2:4])] if matched else []
    return dict(source_entry=entry, event_number=number, weight=weight, particles=particles, reco=reco)


def test_refs_not_indices_and_all_unmatched_denominators():
    row = analyze(event(matched=False))
    assert row['delphes_event_number'] == 41 and row['source_entry'] == 0
    assert row['native_event_id'] is None and len(row['direct_particles']) == 2
    assert all(p['matched_reco'] is None for p in row['direct_particles'])
    row = analyze(event())
    assert [p['particle_uid'] for p in row['direct_particles']] == [37, 89]
    assert [p['matched_reco']['particle_index'] for p in row['direct_particles']] == [2, 3]


def test_same_signed_pdg_copy_chain_is_direct():
    source = event()
    source['particles'][2]['status'] = 2
    source['particles'].append(particle(11, 142, 2))
    source['reco'][0]['ref'] = 142
    row = analyze(source)
    child = next(p for p in row['direct_particles'] if p['pid'] == 11)
    assert child['copy_chain_indices'] == [6, 2, 0]
    assert child['matched_reco']['particle_uid'] == 142


def test_secondary_tau_and_conversion_origins_are_retained():
    source = event(matched=False)
    source['particles'].extend([particle(15, 110, 0, status=2), particle(11, 111, 6),
                                particle(22, 120, 1, status=2), particle(-11, 121, 8),
                                particle(13, 130)])
    for index, (ref, flavour) in enumerate([(111,'electron'),(121,'electron'),(130,'muon')]):
        source['reco'].append(dict(index=index, flavour=flavour, ref=ref, pt=6., eta=.1, phi=.3))
    row = analyze(source)
    assert len(row['direct_particles']) == 2
    assert [p['origin'] for p in row['reco_particles']] == ['tau_ancestor','other_parent_descendant','other_origin']


def test_stau_population_is_measured_and_flagged_not_discarded():
    source = event(matched=False)
    source['particles'].extend([particle(1000015, 400, status=22), particle(15, 401, 6, status=2), particle(11, 402, 7)])
    summary = response.ResponseSummary(contract())
    summary.add(analyze(source))
    result = summary.result()
    assert result['input_events'] == 1
    assert result['topology_population_status'] == 'FAIL'
    assert result['root_parent_counts_both_charges']['1000015'] == 1
    assert result['physics_certified'] is False


@pytest.mark.parametrize('mutation', ['no_sleptons','same_sign','missing_bino','missing_lepton'])
def test_declared_topology_failures_remain_in_input_denominator(mutation):
    source = event(matched=False)
    if mutation == 'no_sleptons':
        source['particles'][0]['pid'] = source['particles'][1]['pid'] = 22
    elif mutation == 'same_sign':
        source['particles'][1]['pid'] *= -1
        source['particles'][3]['pid'] *= -1
    elif mutation == 'missing_bino': source['particles'][4]['status'] = 2
    else: source['particles'][2]['status'] = 2
    summary = response.ResponseSummary(contract())
    summary.add(analyze(source))
    assert summary.result()['input_events'] == 1
    assert summary.result()['topology_population_status'] == 'FAIL'


def test_population_policy_can_be_explicitly_not_requested():
    source = event(matched=False)
    source['particles'][0]['pid'] = source['particles'][1]['pid'] = 22
    policy=contract();policy['topology']=[]
    summary = response.ResponseSummary(policy)
    summary.add(analyze(source,expect_four_state=False))
    assert summary.result()['topology_population_status'] == 'not_requested'
    assert summary.result()['input_events'] == 1


@pytest.mark.parametrize('mutation,match', [
    ('mother_high','out-of-range'), ('mother_low','out-of-range'), ('self_cycle','cycle'),
    ('two_cycle','cycle'), ('duplicate_uid','UID'), ('null_uid','UID'),
    ('missing_ref','TRef'), ('duplicate_ref','duplicate reco'), ('wrong_flavour','flavour'),
    ('unstable_ref','stable'), ('wrong_parent','flavour/sign'), ('wrong_sign','flavour/sign'),
    ('ambiguous','ambiguous'), ('nan_weight','finite'), ('nan_pt','finite')])
def test_malformed_population_is_rejected(mutation, match):
    source = event()
    if mutation == 'mother_high': source['particles'][4]['m1'] = 100
    elif mutation == 'mother_low': source['particles'][4]['m1'] = -2
    elif mutation == 'self_cycle': source['particles'][4]['m1'] = 4
    elif mutation == 'two_cycle': source['particles'][4]['m1'] = 5; source['particles'][5]['m1'] = 4
    elif mutation == 'duplicate_uid': source['particles'][4]['uid'] = 37
    elif mutation == 'null_uid': source['particles'][4]['uid'] = 0
    elif mutation == 'missing_ref': source['reco'][0]['ref'] = 999
    elif mutation == 'duplicate_ref': source['reco'].append(copy.deepcopy(source['reco'][0]))
    elif mutation == 'wrong_flavour': source['reco'][0]['flavour'] = 'muon'
    elif mutation == 'unstable_ref': source['particles'][2]['status'] = 2
    elif mutation == 'wrong_parent': source['particles'][0]['pid'] = 1000013
    elif mutation == 'wrong_sign': source['particles'][0]['pid'] = -1000011
    elif mutation == 'ambiguous': source['particles'][2]['m2'] = 1
    elif mutation == 'nan_weight': source['weight'] = math.nan
    elif mutation == 'nan_pt': source['particles'][2]['pt'] = math.nan
    with pytest.raises(ValueError, match=match): analyze(source)


def test_shared_event_pair_uncertainty_not_independent_leptons():
    summary = response.ResponseSummary(contract())
    summary.add(analyze(event()))
    summary.add(analyze(event(entry=1, number=99, matched=False)))
    result = summary.result()['total_response']['electron']
    assert result['raw_truth'] == 4 and result['raw_matched'] == 2
    assert result['ratio'] == .5
    assert result['event_truth_sumw2'] == 8
    assert result['standard_error'] == pytest.approx(math.sqrt(.125))
    assert result['standard_error'] != .25  # Invalid independent-object approximation.


def test_migration_moments_cluster_same_bin_leptons():
    summary = response.ResponseSummary(contract())
    summary.add(analyze(event(weight=2.)))
    rows = summary.result()['matched_migrations']
    assert len(rows) == 2  # pT and eta, each both leptons in the same cell.
    assert all(p['count'] == 2 and p['sumw'] == 4 and p['event_sumw2'] == 16 for p in rows)


@pytest.mark.parametrize('matched', [False, True])
def test_boundary_bins_do_not_claim_zero_mc_uncertainty(matched):
    summary = response.ResponseSummary(contract())
    summary.add(analyze(event(matched=matched)))
    result = summary.result()
    assert result['total_response']['electron']['standard_error'] is None
    assert result['total_response']['electron']['precision_status'] == 'boundary_count_precision_unresolved'
    assert result['total_response']['muon']['ratio'] is None
    assert result['total_response']['muon']['precision_status'] == 'zero_denominator_unresolved'


def test_signed_weights_retained_with_unresolved_zero_denominator():
    summary = response.ResponseSummary(contract())
    summary.add(analyze(event()))
    summary.add(analyze(event(entry=1, number=42, weight=-1, matched=False)))
    result = summary.result()
    assert result['signed_weight_caution'] and result['raw_weights']['negative_events'] == 1
    assert result['total_response']['electron']['ratio'] is None
    assert result['input_events'] == 2


def test_one_shared_event_or_identical_pair_outcomes_do_not_claim_zero_error():
    moment = response.RatioMoments()
    moment.add(2, 1, 1.)
    assert moment.result()['ratio'] == .5
    assert moment.result()['standard_error'] is None
    assert moment.result()['precision_status'] == 'insufficient_event_clusters_unresolved'
    moment.add(2, 1, 1.)
    assert moment.result()['standard_error'] is None
    assert moment.result()['precision_status'] == 'zero_empirical_variance_precision_unresolved'


@pytest.mark.parametrize('entry,number', [(1,42),(0,41)])
def test_missing_or_duplicate_population_rejected(entry, number):
    summary = response.ResponseSummary(contract())
    if entry == 0: summary.add(analyze(event()))
    with pytest.raises(ValueError): summary.add(analyze(event(entry=entry,number=number)))


def test_duplicate_event_ids_even_at_next_entry_rejected():
    summary = response.ResponseSummary(contract())
    summary.add(analyze(event()))
    with pytest.raises(ValueError, match='duplicate Delphes'):
        summary.add(analyze(event(entry=1)))


def test_run_preserves_all_events_and_refuses_existing_outputs(tmp_path, monkeypatch):
    source, card, output = tmp_path/'input.root', tmp_path/'card.tcl', tmp_path/'out'
    source.write_bytes(b'ROOT placeholder'); card.write_text('detector card')
    monkeypatch.setattr(response, 'delphes_events', lambda _,**kwargs: iter([event(),event(entry=1,number=42,matched=False)]))
    result = run(source,output,detector_card=card)
    assert result['input_events'] == 2 and result['native_join_status'] == 'not_requested'
    assert result['definitions']['contract']==contract()
    with gzip.open(output/'truth_reco_response.jsonl.gz','rt') as stream:
        records = [json.loads(x) for x in stream]
    assert len(records) == 3 and records[-1]['source_entry'] == 1
    with pytest.raises(FileExistsError): run(source,output,detector_card=card)


@pytest.mark.parametrize('failure', ['source_drift','duplicate_event','empty'])
def test_failed_run_publishes_no_summary_or_event_artifact(tmp_path, monkeypatch, failure):
    source, card, output = tmp_path/'input.root', tmp_path/'card.tcl', tmp_path/'out'
    source.write_bytes(b'ROOT placeholder'); card.write_text('detector card')
    def events(_,**kwargs):
        if failure == 'empty': return
        yield event()
        if failure == 'source_drift': source.write_bytes(b'changed')
        else: yield event(entry=1)
    monkeypatch.setattr(response,'delphes_events',events)
    with pytest.raises(ValueError): run(source,output,detector_card=card)
    assert not list(output.glob('truth_reco_response*'))


@pytest.mark.parametrize('classnames', [{}, {'Delphes;1':'TTree'},
    {'ProcessID0;1':'TProcessID','ProcessID1;1':'TProcessID','Delphes;1':'TTree'}])
def test_missing_or_multiple_process_namespaces_rejected(classnames):
    with pytest.raises(ValueError,match='TProcessID'): response.require_single_process_id(classnames)


def test_single_process_namespace_positive_control():
    assert response.require_single_process_id({'ProcessID0;1':'TProcessID','Delphes;1':'TTree'}) == 'ProcessID0;1'


def test_failed_second_publication_removes_only_own_event_artifact(tmp_path, monkeypatch):
    source, card, output = tmp_path/'input.root', tmp_path/'card.tcl', tmp_path/'out'
    source.write_bytes(b'ROOT placeholder'); card.write_text('detector card')
    monkeypatch.setattr(response,'delphes_events',lambda _,**kwargs: iter([event()]))
    original_link = type(source).hardlink_to
    def link(path, target):
        if path.name == 'truth_reco_response.json': raise OSError('injected summary publication failure')
        original_link(path,target)
    monkeypatch.setattr(type(source),'hardlink_to',link)
    with pytest.raises(OSError): run(source,output,detector_card=card)
    assert not list(output.glob('truth_reco_response*'))

def test_two_supplied_response_contracts_change_binning_population_and_format(tmp_path,monkeypatch):
    artifacts=[]
    for ident,points,count,edges,eta_edges,fmt in [('ANA-0001',[1],2,[0,7,None],[0,1,None],'jsonl.gz'),('ANA-0002',[2,4,8],3,[0,3,6,9,None],[0,.1,.5,2,None],'json')]:
        policy=contract();policy.update(study_id=ident,parameter_grid=[{'coordinate':p} for p in points],datasets=['DATA-'+str(i) for i in range(count)],pt_edges=edges,abs_eta_edges=eta_edges,output_format=fmt)
        source=tmp_path/(ident+'.root');source.write_bytes(b'Fictional input');card=tmp_path/(ident+'.tcl');card.write_text('Fictional detector card')
        monkeypatch.setattr(response,'delphes_events',lambda _,**kwargs:iter([event(entry=i,number=i+10,matched=i%2==0) for i in range(count)]))
        out=tmp_path/(ident+'-out');result=response.run(source,out,detector_card=card,contract=policy)
        assert result['contract']==policy and result['input_events']==count
        assert len(result['response_bins'])==2*(len(edges)-1)*(len(eta_edges)-1)
        artifact=out/result['event_artifact']['path']
        if fmt=='json':rows=json.loads(artifact.read_text())
        else:
            with gzip.open(artifact,'rt') as stream:rows=[json.loads(line) for line in stream]
        assert len(rows)==count+1 and rows[0]['definitions']['contract']==policy;artifacts.append(result)
    assert artifacts[0]!=artifacts[1]
    with pytest.raises(response.ResponseInputError) as caught:response.run(source,tmp_path/'missing',detector_card=card)
    assert caught.value.reason=='missing_input' and not (tmp_path/'missing').exists()
