"""Synthetic supplied-response controls; no native detector execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def acquired(root, name, value):
    """An input the operator path fetched, registered in custody as RAVEL's acquisition path does."""
    from ravel.workflow import rdj_custody
    pin = put(root, 'inputs/' + name, value)
    rdj_custody.register_acquisition(root, 'inputs/' + name, source='acquisition')
    return pin


def parity(root, status='passed', missing=(), producer='ravel.validation.claim_checks', register=True,
           name='checks/parity.json'):
    """A signal-model completeness result written by a recognized check and registered by the check runner."""
    from ravel.workflow import rdj_custody
    pin = put(root, name, {'schema_version': 1, 'kind': 'ravel-check-result',
                           'check_id': 'signal_model_complete_before_calibration', 'producer': producer,
                           'status': status, 'missing_components': list(missing), 'pins': []})
    if register:
        rdj_custody.register_check_result(root, name)
    return pin


def node(root, i, *, tag='', seed=None, base=None, coeff=None):
    base = base or [10. + i, 20. + i]
    coeff = coeff or [[2., 0.], [0., 3.]]
    seed = i if seed is None else seed
    samples = {stage: acquired(root, f'cal{tag}/{stage}{i}.json', {'node': f'n{i}', 'stage': stage, 'tag': tag})
               for stage in ('generated', 'showered')}
    return {'id': f'n{i}', 'seed': seed, 'sample_ids': [f's{tag}{i}'], 'samples': samples,
            'response': acquired(root, f'cal{tag}/r{i}.json', {'node': f'n{i}', 'seed': seed,
                'sample_ids': [f's{tag}{i}'], 'samples': samples, 'base': base, 'coefficients': coeff}),
            'observable': acquired(root, f'cal{tag}/o{i}.json', {'node': f'n{i}', 'quantity': 'signal_yields',
                'values': [base[0] + .4, base[1] - .6], 'tag': tag})}


@pytest.fixture
def spec(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    monkeypatch.setenv('RAVEL_STATE_DIR', str(state))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(state))
    anchor = acquired(tmp_path, 'band.json', {'low': 0.5, 'high': 1.5})
    claim = put(tmp_path, 'claim.json', {'value': 3})
    nodes = [node(tmp_path, i) for i in range(12)]
    return {'schema_version': 1, 'kind': 'cal:spec',
            'study_id': hashlib.sha256(b'synthetic preregistration').hexdigest(),
            'agreement_target': {'reference': {'pins': [{'locator': claim['path'], 'sha256': claim['sha256']}]}},
            'knobs': [{'module': 'jet_energy_scale', 'parameter': k, 'bins': [i], 'nominal': 1.,
                       'values': [.8, 1., 1.2], 'bounds': [.5, 1.5],
                       'anchor': {'kind': 'retrieved_document', 'pin': anchor,
                                  'low_pointer': '/low', 'high_pointer': '/high'}} for i,k in enumerate(['a','b'])],
            'calibration_nodes': nodes[:4], 'held_out_nodes': nodes[4:],
            'loss': 'squared_error', 'stop': {'max_trials': 9, 'loss_at_most': 0.},
            'budget': {'max_trials': 9}, 'signal_model': {'patch_parity': parity(tmp_path)},
            'imported_calibration': None}


def modules():
    from ravel.physics import detector_calibration as dc
    from ravel.validation import calibration_checks as cc
    return dc, cc


def allow_authorities(monkeypatch):
    dc, _ = modules()
    monkeypatch.setattr(dc, 'approval_binding', lambda *a, **k: {'input_fingerprint': 'f' * 64})
    monkeypatch.setattr(dc, 'calibration_authorization', lambda *a, **k: {'receipt_sha256': 'e' * 64})


def test_target_pin_is_refused(spec, tmp_path):
    _, cc = modules()
    spec['calibration_nodes'][0]['observable'] = {'path': spec['agreement_target']['reference']['pins'][0]['locator'],
                                                'sha256': spec['agreement_target']['reference']['pins'][0]['sha256']}
    with pytest.raises(ValueError, match='calibration_target_disjoint'):
        cc.validate_spec(spec, tmp_path)


def test_claim_quantity_is_refused(spec, tmp_path):
    _, cc = modules()
    spec['calibration_nodes'][0]['observable'] = acquired(tmp_path, 'bad.json', {'node':'n0','quantity':'mu95','values':[1,2]})
    with pytest.raises(ValueError, match='intermediate'):
        cc.validate_spec(spec, tmp_path)


def test_heldout_node_observable_is_refused(spec, tmp_path):
    _, cc = modules()
    spec['calibration_nodes'][0]['observable'] = deepcopy(spec['held_out_nodes'][0]['observable'])
    with pytest.raises(ValueError, match='calibration_target_disjoint'):
        cc.validate_spec(spec, tmp_path)


@pytest.mark.parametrize('field', ['seed', 'sample_ids'])
def test_heldout_lineage_overlap_is_refused(spec, tmp_path, field):
    _, cc = modules()
    spec['held_out_nodes'][0][field] = deepcopy(spec['calibration_nodes'][0][field])
    with pytest.raises(ValueError, match='confirmation_separation'):
        cc.validate_spec(spec, tmp_path)


def test_unanchored_bounds_are_refused(spec, tmp_path):
    _, cc = modules()
    spec['knobs'][0]['bounds'] = [0.,2.]
    with pytest.raises(ValueError, match='anchored band'):
        cc.validate_spec(spec, tmp_path)


def test_outside_band_requires_r3_human(spec, tmp_path):
    dc, _ = modules()
    spec['knobs'][0]['values'] = [2.]
    with pytest.raises(ValueError, match='R3.*human'):
        dc.fit(tmp_path, spec, tmp_path/'cal')


def test_loose_human_receipt_does_not_authorize(spec, tmp_path):
    dc, _ = modules()
    spec['knobs'][0]['values'] = [2.]
    spec['human_approval'] = {'class':'R3','approved':True}
    with pytest.raises(ValueError):
        dc.fit(tmp_path, spec, tmp_path/'cal')


def test_global_scalar_is_refused(spec, tmp_path):
    _, cc = modules()
    spec['signal_scale'] = 1.1
    with pytest.raises(ValueError, match='global.*scalar'):
        cc.validate_spec(spec, tmp_path)


def test_calibration_before_model_completeness_is_refused(spec, tmp_path):
    _, cc = modules()
    spec['signal_model']['patch_parity'] = parity(tmp_path, status='failed', missing=['control'],
                                                  name='checks/bad-parity.json')
    with pytest.raises(ValueError, match='signal_model_complete_before_calibration'):
        cc.validate_spec(spec, tmp_path)


def test_imported_calibration_cannot_be_validated(spec, tmp_path, monkeypatch):
    dc, cc = modules(); allow_authorities(monkeypatch)
    spec['imported_calibration'] = {'source': acquired(tmp_path, 'imported-source.json', {'source': 'synthetic'}),
                                  'fitted_on':['n0'],
                                  'response': acquired(tmp_path,'imported.json',{'parameters':[1.2,.8]})}
    result = dc.fit(tmp_path, spec, tmp_path/'cal')
    assert result['imported_calibration']['fitted_on'] == ['n0']
    with pytest.raises(ValueError, match='imported_calibration'):
        cc.delivery_check(result, evidence_status='validated')


def test_confirmation_requires_approval_pin(spec, tmp_path, monkeypatch):
    dc, _ = modules(); allow_authorities(monkeypatch)
    frozen = dc.fit(tmp_path, spec, tmp_path/'cal')
    monkeypatch.undo()
    state = tmp_path/'state'; monkeypatch.setenv('RAVEL_STATE_DIR',str(state));monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE',str(state))
    with pytest.raises(ValueError, match='approval'):
        dc.confirm(tmp_path, frozen['freeze'])


def test_two_knobs_twelve_nodes_four_fit_eight_once(spec, tmp_path, monkeypatch):
    dc, cc = modules(); allow_authorities(monkeypatch)
    held_paths = {Path(p['path']) for n in spec['held_out_nodes'] for p in [n['response'],n['observable'],*n['samples'].values()]}
    original = Path.read_bytes; reads=[]
    def spy(path):
        if path in held_paths: reads.append(path)
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',spy)
    frozen = dc.fit(tmp_path, spec, tmp_path/'cal')
    assert not reads
    assert frozen['parameters'] == pytest.approx([1.2,.8])
    assert frozen['n_trials'] == len(frozen['trials']) == 7
    assert frozen['stop_reason'] == 'loss_at_most'
    assert original(Path(frozen['response']['path']))
    assert hashlib.sha256(original(Path(frozen['response']['path']))).hexdigest() == frozen['response']['sha256']
    result = dc.confirm(tmp_path, frozen['freeze'])
    assert len(result['held_out_scores']) == 8
    assert len(reads) == 32 and len(set(reads)) == 32
    assert result['after']['loss'] < result['before']['loss']
    assert cc.delivery_check(result) == []
    with pytest.raises(ValueError, match='already.*read|spent'):
        dc.confirm(tmp_path, frozen['freeze'])


def test_changed_response_refuses_confirm(spec, tmp_path, monkeypatch):
    dc, _ = modules(); allow_authorities(monkeypatch)
    frozen=dc.fit(tmp_path,spec,tmp_path/'cal')
    Path(frozen['response']['path']).write_text('{}')
    with pytest.raises(ValueError, match='pin changed'):
        dc.confirm(tmp_path,frozen['freeze'])


def test_trials_persist_across_run_directories(spec, tmp_path, monkeypatch):
    dc, _ = modules(); allow_authorities(monkeypatch)
    first=dc.fit(tmp_path,spec,tmp_path/'cal')
    second=dc.fit(tmp_path,spec,tmp_path/'other')
    assert second['study_trials'] == first['study_trials'] + second['n_trials']


def test_before_and_after_required(spec, tmp_path, monkeypatch):
    dc, cc=modules();allow_authorities(monkeypatch)
    result=dc.confirm(tmp_path,dc.fit(tmp_path,spec,tmp_path/'cal')['freeze'])
    del result['before']
    with pytest.raises(ValueError,match='before.and.after'):
        cc.delivery_check(result)


def test_heldout_cannot_hide_in_anchor(spec, tmp_path):
    _,cc=modules()
    spec['knobs'][0]['anchor']['pin']=deepcopy(spec['held_out_nodes'][0]['observable'])
    with pytest.raises(ValueError,match='calibration_target_disjoint'):cc.validate_spec(spec,tmp_path)


def test_approval_boolean_cannot_bind_freeze(spec, tmp_path):
    dc,_=modules()
    put(tmp_path,'inputs/checkin1_approval.json',{'approved':True,'input_fingerprint':'f'*64})
    with pytest.raises(ValueError,match='approval'):dc.approval_binding(tmp_path,spec=spec)


def test_authorization_replays_r3_and_human(spec, tmp_path, monkeypatch):
    dc,_=modules()
    from ravel.workflow import rdj_loop
    calls=[]
    accepted={'case':{'decision_point':{'tuning':{'class':'calibration'}}},
              'receipt':{'attestation_summary':{'human_approver':{'approval_id':'synthetic'}}},
              'receipt_sha256':'e'*64,'case_sha256':'d'*64}
    def authorize(root,gate,action):
        calls.append((gate,action));return deepcopy(accepted)
    monkeypatch.setattr(rdj_loop,'authorizing_receipt',authorize)
    dc.calibration_authorization(tmp_path,spec,floor='R3',human=True)
    assert calls[0][0]=='checkin2_accept' and calls[0][1]['floor']=='R3'
    accepted['receipt']['attestation_summary']={}
    with pytest.raises(ValueError,match='R3 human'):dc.calibration_authorization(tmp_path,spec,floor='R3',human=True)


def test_m15_check_seam_refuses_same_target(spec, tmp_path):
    _,cc=modules()
    spec['calibration_nodes'][0]['observable']={'path':spec['agreement_target']['reference']['pins'][0]['locator'],
                                               'sha256':spec['agreement_target']['reference']['pins'][0]['sha256']}
    errors=cc.gate_errors(tmp_path,'checkin2_accept',{'calibration_spec':put(tmp_path,'spec.json',spec)})
    assert errors and errors[0].pins==('check:calibration_target_disjoint',)


def test_changed_delivery_is_refused(spec,tmp_path,monkeypatch):
    dc,_=modules();allow_authorities(monkeypatch)
    result=dc.confirm(tmp_path,dc.fit(tmp_path,spec,tmp_path/'cal')['freeze'])
    dc.verify_delivery(tmp_path,tmp_path/'cal/confirmation.json',allow_test_namespace=True)
    result['after']['loss']=1000
    (tmp_path/'cal/confirmation.json').write_text(json.dumps(result))
    with pytest.raises(ValueError,match='delivery.*changed'):
        dc.verify_delivery(tmp_path,tmp_path/'cal/confirmation.json',allow_test_namespace=True)


def test_local_ledger_head_mutation_is_refused(spec,tmp_path,monkeypatch):
    dc,_=modules();allow_authorities(monkeypatch)
    dc.confirm(tmp_path,dc.fit(tmp_path,spec,tmp_path/'cal')['freeze'])
    (tmp_path/'research/calibration'/(spec['study_id']+'.jsonl')).write_text('')
    with pytest.raises(ValueError,match='ledger'):
        dc.verify_delivery(tmp_path,tmp_path/'cal/confirmation.json',allow_test_namespace=True)


def test_refit_after_confirm_is_refused(spec,tmp_path,monkeypatch):
    dc,_=modules();allow_authorities(monkeypatch)
    dc.confirm(tmp_path,dc.fit(tmp_path,spec,tmp_path/'cal')['freeze'])
    with pytest.raises(ValueError,match='spent'):dc.fit(tmp_path,spec,tmp_path/'later')


def test_undeclared_bin_response_is_refused(spec,tmp_path,monkeypatch):
    dc,_=modules();allow_authorities(monkeypatch)
    node=spec['calibration_nodes'][0]
    node['response']=acquired(tmp_path,'scalar.json',{'node':node['id'],'seed':node['seed'],'sample_ids':node['sample_ids'],'samples':node['samples'],
                                               'base':[10.,20.],'coefficients':[[1.,1.],[1.,1.]]})
    with pytest.raises(ValueError,match='global signal scalar'):dc.fit(tmp_path,spec,tmp_path/'cal')


def test_registered_card_and_signature_match_outputs(spec,tmp_path,monkeypatch):
    dc,cc=modules();allow_authorities(monkeypatch)
    from ravel.workflow import role_registry
    from ravel.validation import signature_conformance
    card=role_registry.load('detector-calibrator')
    assert role_registry.validate_card(card)==[]
    assert card['model']['tier']=='agent'
    assert 'held_out_artifacts' in card['sees']['forbidden_inputs']
    project=Path(__file__).resolve().parents[2]
    entries=json.loads((project/'src/ravel/data/calibration/operation_signature.json').read_text())
    assert signature_conformance.entry_errors('detector-calibration',entries['detector-calibration'])==[]
    receipt=dc.fit(tmp_path,spec,tmp_path/'cal')
    outputs={'response':json.loads(Path(receipt['response']['path']).read_bytes()),'report':receipt}
    assert signature_conformance.output_errors('detector-calibration',outputs,entries)==[]


def test_approximation_requires_its_own_authorization(spec,tmp_path,monkeypatch):
    dc,_=modules();allow_authorities(monkeypatch)
    spec['signal_model']={'approximation_action':{'kind':'approximation','digest':'d'*64}}
    with pytest.raises(ValueError,match='approximation'):dc.fit(tmp_path,spec,tmp_path/'cal')


def test_changed_frozen_sample_is_refused(spec,tmp_path,monkeypatch):
    dc,_=modules();allow_authorities(monkeypatch)
    Path(spec['calibration_nodes'][0]['samples']['generated']['path']).write_text('changed')
    with pytest.raises(ValueError,match='sample pin changed|registered acquisition'):dc.fit(tmp_path,spec,tmp_path/'cal')


def test_claim_reference_cannot_be_substituted(spec,tmp_path,monkeypatch):
    dc,_=modules()
    from ravel.validation import agreement_target
    monkeypatch.setattr(agreement_target,'targets',lambda *a,**k: {'claim':{'reference':{'pins':[{'locator':'other.json','sha256':'b'*64}]}}})
    with pytest.raises(ValueError,match='current agreement target'):dc.target_binding(tmp_path,spec)


def test_matching_current_target_is_consumed(spec,tmp_path,monkeypatch):
    dc,_=modules()
    from ravel.validation import agreement_target
    monkeypatch.setattr(agreement_target,'targets',lambda *a,**k: {'claim':spec['agreement_target']})
    assert dc.target_binding(tmp_path,spec)['claim_ids']==['claim']


# ---- custody-registered calibration inputs, target-scoped exposure and wiring

def test_relabelled_heldout_copy_is_refused(spec, tmp_path):
    _, cc = modules()
    held = json.loads(Path(spec['held_out_nodes'][0]['observable']['path']).read_text())
    spec['calibration_nodes'][0]['observable'] = put(tmp_path, 'scratch/copy.json', {**held, 'node': 'n0'})
    with pytest.raises(ValueError, match='registered'):
        cc.validate_spec(spec, tmp_path)


def test_claim_numbers_cannot_calibrate(spec, tmp_path):
    _, cc = modules()
    claim = put(tmp_path, 'claim-cutflow.json', {'cutflow': [3, 3]})
    spec['agreement_target']['reference']['pins'] = [{'locator': claim['path'], 'sha256': claim['sha256']}]
    spec['calibration_nodes'][0]['observable'] = acquired(tmp_path, 'copied.json',
                                                         {'node': 'n0', 'quantity': 'cutflow', 'values': [3, 3]})
    with pytest.raises(ValueError, match='reference'):
        cc.validate_spec(spec, tmp_path)


@pytest.mark.parametrize('register,producer', [(False, 'ravel.validation.claim_checks'), (True, 'agent-notes')])
def test_self_authored_parity_is_refused(spec, tmp_path, register, producer):
    _, cc = modules()
    spec['signal_model']['patch_parity'] = parity(tmp_path, register=register, producer=producer,
                                                  name='checks/self.json')
    with pytest.raises(ValueError, match='signal_model_complete_before_calibration'):
        cc.validate_spec(spec, tmp_path)


def test_self_authored_band_is_refused(spec, tmp_path):
    _, cc = modules()
    spec['knobs'][0]['anchor']['pin'] = put(tmp_path, 'mine/band.json', {'low': 0, 'high': 100})
    spec['knobs'][0]['bounds'] = [0, 100]
    spec['knobs'][0]['values'] = [1, 5, 20]
    with pytest.raises(ValueError, match='acquisition'):
        cc.validate_spec(spec, tmp_path)


def test_anchor_in_the_reference_record_is_admitted(spec, tmp_path):
    _, cc = modules()
    record = acquired(tmp_path, 'reference-record.json', {'value': 3, 'low': 0.5, 'high': 1.5})
    spec['agreement_target']['reference']['pins'] = [{'locator': record['path'], 'sha256': record['sha256']}]
    spec['knobs'][0]['anchor']['pin'] = record
    assert cc.validate_spec(spec, tmp_path)['outside_band'] is False


def test_signal_normalisation_knob_is_refused(spec, tmp_path, monkeypatch):
    dc, cc = modules()
    spec['knobs'][0]['module'] = 'signal'
    with pytest.raises(ValueError, match='detector-response module'):
        cc.validate_spec(spec, tmp_path)
    spec['knobs'][0]['module'] = 'jet_energy_scale'
    allow_authorities(monkeypatch)
    spec['knobs'] = spec['knobs'][:1]
    spec['knobs'][0]['bins'] = [0, 1]
    for i, n in enumerate(spec['calibration_nodes']):
        base = [10. + i, 20. + i]
        spec['calibration_nodes'][i] = node(tmp_path, i, tag='scalar', base=base, coeff=[[b] for b in base])
    with pytest.raises(ValueError, match='global signal scalar'):
        dc.fit(tmp_path, spec, tmp_path / 'cal')


def test_calibration_nodes_may_share_a_seed(spec, tmp_path):
    _, cc = modules()
    for n in spec['calibration_nodes']:
        n['seed'] = 0
    assert cc.validate_spec(spec, tmp_path)


def test_imported_calibration_needs_registered_source_and_disjoint_training(spec, tmp_path):
    _, cc = modules()
    response = acquired(tmp_path, 'imported.json', {'parameters': [1.2, .8]})
    spec['imported_calibration'] = {'source': put(tmp_path, 'missing-source.json', {}), 'fitted_on': ['external'],
                                    'response': response}
    with pytest.raises(ValueError, match='acquisition'):
        cc.validate_spec(spec, tmp_path)
    spec['imported_calibration']['source'] = acquired(tmp_path, 'source.json', {'source': 'synthetic'})
    spec['imported_calibration']['fitted_on'] = [spec['held_out_nodes'][0]['id']]
    with pytest.raises(ValueError, match='held-out'):
        cc.validate_spec(spec, tmp_path)


def test_imported_label_is_refused_only_for_the_same_target(spec, tmp_path, monkeypatch):
    dc, cc = modules(); allow_authorities(monkeypatch)
    spec['imported_calibration'] = {'source': acquired(tmp_path, 'source.json', {'source': 'synthetic'}),
                                    'fitted_on': ['external-node'],
                                    'response': acquired(tmp_path, 'imported.json', {'parameters': [1.2, .8]})}
    result = dc.confirm(tmp_path, dc.fit(tmp_path, spec, tmp_path / 'cal')['freeze'])
    assert result['imported_in_sample'] is False
    assert cc.delivery_check(result, evidence_status='validated') == []


def test_second_study_in_the_same_run_is_admitted(spec, tmp_path, monkeypatch):
    dc, _ = modules(); allow_authorities(monkeypatch)
    dc.confirm(tmp_path, dc.fit(tmp_path, spec, tmp_path / 'cal')['freeze'])
    second = deepcopy(spec)
    second['study_id'] = hashlib.sha256(b'second preregistration').hexdigest()
    nodes = [node(tmp_path, i, tag='b', base=[30. + i, 50. + i]) for i in range(12)]
    second['calibration_nodes'], second['held_out_nodes'] = nodes[:4], nodes[4:]
    result = dc.confirm(tmp_path, dc.fit(tmp_path, second, tmp_path / 'cal-b')['freeze'])
    assert len(result['held_out_scores']) == 8
    assert result['target_trials'] > result['study_trials']


def test_reserialized_heldout_in_a_new_study_is_refused_and_trials_accumulate(spec, tmp_path, monkeypatch):
    dc, _ = modules(); allow_authorities(monkeypatch)
    first = dc.confirm(tmp_path, dc.fit(tmp_path, spec, tmp_path / 'cal')['freeze'])
    other = tmp_path / 'other-run'
    second = deepcopy(spec)
    second['study_id'] = hashlib.sha256(b'copied study').hexdigest()
    for group in ('calibration_nodes', 'held_out_nodes'):
        for n in second[group]:
            n['sample_ids'] = ['copy-' + s for s in n['sample_ids']]
            for key in ('generated', 'showered'):
                n['samples'][key] = acquired(other, f'copy/{key}{n["id"]}.json',
                                             {**json.loads(Path(n['samples'][key]['path']).read_text()), 'copy': 1})
            response = json.loads(Path(n['response']['path']).read_text())
            n['response'] = acquired(other, f'copy/r{n["id"]}.json', {**response, 'sample_ids': n['sample_ids'],
                                                                     'samples': n['samples'], 'copy': 1})
            n['observable'] = acquired(other, f'copy/o{n["id"]}.json',
                                       {**json.loads(Path(n['observable']['path']).read_text()), 'copy': 1})
    second['signal_model']['patch_parity'] = parity(other)
    second['knobs'] = deepcopy(second['knobs'])
    for knob in second['knobs']:
        knob['anchor']['pin'] = acquired(other, 'band.json', {'low': 0.5, 'high': 1.5})
    claim = put(other, 'claim.json', {'value': 3})
    second['agreement_target']['reference']['pins'] = [{'locator': claim['path'], 'sha256': claim['sha256']}]
    frozen = dc.fit(other, second, other / 'cal')
    assert frozen['target_trials'] == first['target_trials'] + frozen['n_trials']
    with pytest.raises(ValueError, match='already scored'):
        dc.confirm(other, frozen['freeze'])


def test_detector_calibration_action_without_spec_is_refused(tmp_path):
    _, cc = modules()
    from ravel.workflow import decision_gate
    assert any(p['id'] == 'calibration' for p in decision_gate.providers('checkin2_accept'))
    assert cc.gate_errors(tmp_path, 'checkin2_accept', {'kind': 'detector-calibration'})
    assert cc.gate_errors(tmp_path, 'delivery', {'kind': 'detector-calibration'})
    assert cc.gate_errors(tmp_path, 'checkin2_accept', {'kind': 'other'}) == []


def test_test_namespace_delivery_is_refused_by_default(spec, tmp_path, monkeypatch):
    dc, _ = modules(); allow_authorities(monkeypatch)
    result = dc.confirm(tmp_path, dc.fit(tmp_path, spec, tmp_path / 'cal')['freeze'])
    assert result['test_namespace'] is True and result['sealing'].startswith('evaluator-convention')
    with pytest.raises(ValueError, match='test namespace'):
        dc.verify_delivery(tmp_path, tmp_path / 'cal/confirmation.json')
