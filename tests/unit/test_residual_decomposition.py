"""Residual diagnosis: decomposition, noise model, attribution check and trigger seam.

Every fixture is a synthetic binned model: two signal-region bins and one control-region bin
per node, a background normalisation profiled from the control region, and a limit quantity
computed with the median expected asymptotic CLs on the background-only Asimov dataset.
"""
import json
import math

import numpy as np
import pytest
from scipy.optimize import brentq, minimize_scalar

from ravel.validation import noise_model, residual_decomposition as rd

Z95 = 1.959963984540054


def _nll(n, lam):
    lam = np.maximum(lam, 1e-12)
    return float(np.sum(lam - n * np.log(lam)))


def full_mu95(sr_signal, sr_bkg, cr_signal, cr_bkg):
    """Expected mu95 with a free background normalisation constrained by the control region."""
    sr_signal, sr_bkg = np.asarray(sr_signal, float), np.asarray(sr_bkg, float)
    n = np.append(sr_bkg, cr_bkg)

    def nll(mu, k):
        return _nll(n, np.append(k * sr_bkg + mu * sr_signal, k * cr_bkg + mu * cr_signal))

    floor = nll(0.0, 1.0)

    def q(mu):
        best = minimize_scalar(lambda k: nll(mu, k), bounds=(1e-3, 10.0), method='bounded',
                               options={'xatol': 1e-10})
        return 2.0 * (best.fun - floor) - Z95 ** 2

    return brentq(q, 1e-6, 1e4, xtol=1e-12)


def _node(index, sr_ref, sr_ours, sr_bkg, cr_ref, cr_ours, cr_bkg, result, reference, mc=0.01,
          flavour='ee', extra=None, ref_mc=None):
    ref_mc = mc if ref_mc is None else ref_mc
    regions = [
        {'name': 'SR', 'role': 'signal', 'flavour': flavour, 'background': list(sr_bkg),
         'ours': {'yield': list(sr_ours), 'sumw2': [(mc * y) ** 2 for y in sr_ours]},
         'reference': {'yield': list(sr_ref), 'staterror': [ref_mc * y for y in sr_ref]}},
        {'name': 'CR', 'role': 'control', 'flavour': flavour, 'background': [cr_bkg],
         'ours': {'yield': [cr_ours], 'sumw2': [(mc * cr_ours) ** 2]},
         'reference': {'yield': [cr_ref], 'staterror': [ref_mc * cr_ref]}},
    ]
    node = {'id': f'n{index}', 'coordinates': [100.0 + 10 * index, 20.0], 'result': result,
            'reference': reference, 'regions': regions}
    if extra:
        node['fingerprints'] = extra
    return node


def replicas(value, spread=0.001, seeds=(11, 12, 13)):
    """Producer-recorded replicas of our result, one per distinct seed."""
    return [{'value': value * (1.0 + spread * k), 'seed': s} for k, s in zip((-1, 0, 1), seeds)]


SR_BKG = [40.0, 15.0]
CR_BKG = 400.0


def _shape(i):
    return np.array([6.0 + 0.5 * i, 4.0 + 0.3 * i])


def cr_omission_model(n=10):
    """Ours omits the control-region signal that the reference likelihood carries."""
    nodes, planted = [], []
    for i in range(n):
        sr = _shape(i)
        cr = (0.05 + 0.12 * i) * sr.sum()
        reference = full_mu95(sr, SR_BKG, cr, CR_BKG)
        ours = full_mu95(sr, SR_BKG, 0.0, CR_BKG)
        nodes.append(_node(i, sr, sr, SR_BKG, cr, cr, CR_BKG, ours, reference, mc=0.005))
        nodes[-1]['replicas'] = replicas(ours)
        planted.append(cr / (cr + sr.sum()))
    return {'schema_version': 1, 'kind': 'residual-model', 'response': 'inverse', 'nodes': nodes}, planted


def rate_deficit_model(n=10, scale=0.8):
    nodes = []
    for i in range(n):
        sr, cr = _shape(i), 0.3 * _shape(i).sum()
        reference = full_mu95(sr, SR_BKG, cr, CR_BKG)
        ours = full_mu95(scale * sr, SR_BKG, scale * cr, CR_BKG)
        nodes.append(_node(i, sr, scale * sr, SR_BKG, cr, scale * cr, CR_BKG, ours, reference, mc=0.005))
    return {'schema_version': 1, 'kind': 'residual-model', 'response': 'inverse', 'nodes': nodes}


def noise_only_model(n=12, mc=0.06, seed=7):
    rng = np.random.default_rng(seed)
    nodes = []
    for i in range(n):
        sr, cr = _shape(i), 0.3 * _shape(i).sum()
        noisy_sr = sr * (1.0 + mc * rng.standard_normal(2))
        noisy_cr = cr * (1.0 + mc * rng.standard_normal())
        reference = full_mu95(sr, SR_BKG, cr, CR_BKG)
        ours = full_mu95(noisy_sr, SR_BKG, noisy_cr, CR_BKG)
        # The reference is exact here, so it declares no statistical error.
        nodes.append(_node(i, sr, noisy_sr, SR_BKG, cr, noisy_cr, CR_BKG, ours, reference, mc=mc, ref_mc=0.0))
    return {'schema_version': 1, 'kind': 'residual-model', 'response': 'inverse', 'nodes': nodes}


def _rule(threshold=0.02, aggregation='median_abs'):
    return {'metric': 'relative difference of the limit', 'threshold': threshold,
            'aggregation': aggregation, 'definition': 'synthetic'}


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, rundir, trigger):
        self.calls.append(trigger)
        return {'status': 'opened', 'id': f'x{len(self.calls)}'}


# --- the decomposition -----------------------------------------------------------------

def test_terms_close_on_the_total_residual():
    model, _ = cr_omission_model(4)
    record = rd.decompose(model)
    for node in record['nodes']:
        terms = node['terms']
        assert terms['rate'] + terms['shape'] + terms['likelihood'] == pytest.approx(terms['total'], abs=1e-12)


def test_planted_control_region_omission_is_assigned_to_the_likelihood_term():
    model, planted = cr_omission_model()
    record = rd.decompose(model)
    attribution = record['attribution']['all']
    assert attribution['assigned'] == 'likelihood'
    assert attribution['terms']['likelihood']['above_noise'] is True
    assert attribution['terms']['rate']['above_noise'] is False
    assert attribution['terms']['shape']['above_noise'] is False
    corr = record['fingerprints']['likelihood']['reference_cr_signal_fraction']
    assert corr['supported'] is True
    assert abs(corr['spearman']) > 0.9 and abs(corr['pearson']) > 0.9
    fractions = [n['fingerprints']['reference_cr_signal_fraction'] for n in record['nodes']]
    assert fractions == pytest.approx(planted, rel=1e-12)


def test_planted_rate_deficit_is_assigned_to_the_rate_term():
    record = rd.decompose(rate_deficit_model())
    attribution = record['attribution']['all']
    assert attribution['assigned'] == 'rate'
    assert attribution['terms']['likelihood']['above_noise'] is False
    for node in record['nodes']:
        assert node['regions']['SR']['rate_ratio'] == pytest.approx(0.8, rel=1e-9)
        assert node['terms']['rate'] == pytest.approx(-math.log(0.8), rel=1e-9)


def test_flavour_and_region_breakdowns_are_separate_scopes():
    model = rate_deficit_model(6)
    for node in model['nodes'][::2]:
        for region in node['regions']:
            region['flavour'] = 'mm'
    record = rd.decompose(model)
    assert set(record['attribution']) == {'all', 'flavour:ee', 'flavour:mm', 'region:SR'}
    assert record['attribution']['flavour:mm']['n_nodes'] == 3
    assert record['attribution']['flavour:mm']['assigned'] == 'rate'
    assert record['attribution']['region:SR']['n_nodes'] == 6
    assert 'likelihood' not in record['attribution']['flavour:mm']['terms']


def test_declared_fingerprint_is_correlated_and_an_undeclared_one_is_refused():
    model, planted = cr_omission_model(6)
    for node, value in zip(model['nodes'], planted):
        node['fingerprints'] = {'declared_knob': 2.0 * value}
    record = rd.decompose(model)
    assert record['fingerprints']['likelihood']['declared_knob']['supported'] is True
    model['nodes'][0]['fingerprints'] = {}
    with pytest.raises(ValueError, match='declared_knob'):
        rd.decompose(model)


def test_malformed_models_are_refused():
    model, _ = cr_omission_model(3)
    model['response'] = 'direct'
    with pytest.raises(ValueError, match='response'):
        rd.decompose(model)
    model, _ = cr_omission_model(3)
    model['nodes'][1]['regions'][0]['ours']['sumw2'] = [1.0]
    with pytest.raises(ValueError, match='bins'):
        rd.decompose(model)
    model, _ = cr_omission_model(3)
    model['nodes'][1]['result'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        rd.decompose(model)
    model, _ = cr_omission_model(3)
    for region in model['nodes'][2]['regions']:
        region['role'] = 'control'
    with pytest.raises(ValueError, match='signal region'):
        rd.decompose(model)


# --- the noise model -------------------------------------------------------------------

def test_noise_thresholds_scale_with_declared_statistics():
    small = noise_model.build(noise_only_model(mc=0.01), rd.node_terms)
    large = noise_model.build(noise_only_model(mc=0.06), rd.node_terms)
    assert large['scopes']['all']['median_threshold']['rate'] > 4 * small['scopes']['all']['median_threshold']['rate']
    node = large['nodes'][0]
    assert node['threshold']['total'] == pytest.approx(node['k_node'] * node['sigma']['total'])
    # A family-wise false-alarm rate: more nodes, a larger per-node multiplier.
    assert noise_model.node_multiplier(100, 0.05) > noise_model.node_multiplier(10, 0.05) > Z95


def test_replica_scatter_enters_the_noise():
    model = noise_only_model(n=4)
    base = noise_model.build(model, rd.node_terms)
    for node in model['nodes']:
        node['replicas'] = [{'value': node['result'] * f, 'seed': s} for f, s in ((0.7, 1), (1.0, 2), (1.3, 3))]
    wide = noise_model.build(model, rd.node_terms)
    assert wide['nodes'][0]['sigma']['total'] > 3 * base['nodes'][0]['sigma']['total']
    assert wide['nodes'][0]['sigma_sources']['replicas'] == 3


# --- trigger: agreement residual above tolerance and beyond noise -----------------------

def test_pure_noise_opens_no_ticket(tmp_path):
    model = noise_only_model()
    rca, board = Recorder(), Recorder()
    record = rd.decompose(model, tolerance_rule=_rule(0.01, 'median_abs'))
    # The residual exceeds the tolerance but not the noise: no feature, no ticket, no epoch.
    assert record['exceedance']['above_tolerance'] is True
    assert record['exceedance']['beyond_noise'] is False
    result = rd.open_triggers(tmp_path, record, claim_id='C2', rca=rca, board=board)
    assert result['status'] == 'no_trigger'
    assert rca.calls == [] and board.calls == []
    for aggregation in ('per_node', 'max_abs', 'fraction_within'):
        record = rd.decompose(model, tolerance_rule=_rule(0.01, aggregation))
        assert rd.open_triggers(tmp_path, record, claim_id='C2', rca=rca, board=board)['status'] == 'no_trigger'
    assert rca.calls == [] and board.calls == []


def test_noise_alone_triggers_at_about_the_false_alarm_rate():
    fired = sum(rd.decompose(noise_only_model(n=8, seed=seed), tolerance_rule=_rule(0.01))['exceedance']['beyond_noise']
                for seed in range(100, 160))
    # alpha = 0.05 over 60 lattices: about 3 expected; 8 or more has binomial probability below 0.01.
    assert fired < 8


def test_residual_beyond_noise_opens_a_ticket_and_a_board_epoch(tmp_path):
    model, _ = cr_omission_model()
    rca, board = Recorder(), Recorder()
    record = rd.decompose(model, tolerance_rule=_rule(0.02))
    assert record['exceedance']['beyond_noise'] is True
    result = rd.open_triggers(tmp_path, record, claim_id='C2', rca=rca, board=board)
    assert result['status'] == 'opened'
    assert len(rca.calls) == 1 and len(board.calls) == 1
    trigger = rca.calls[0]
    assert trigger == board.calls[0]
    assert trigger['claim_id'] == 'C2'
    assert trigger['symptom']['trigger_id'] == record['sha256']
    assert {row['term'] for row in trigger['seeds'] if row['kind'] == 'term'} == {'likelihood'}
    assert any(row['kind'] == 'fingerprint' and row['variable'] == 'reference_cr_signal_fraction'
               for row in trigger['seeds'])
    assert trigger['min_hypotheses'] == 2


def test_residual_within_tolerance_opens_no_ticket(tmp_path):
    model, _ = cr_omission_model()
    rca = Recorder()
    record = rd.decompose(model, tolerance_rule=_rule(0.9))
    assert record['exceedance']['above_tolerance'] is False
    assert rd.open_triggers(tmp_path, record, claim_id='C2', rca=rca, board=rca)['status'] == 'no_trigger'
    assert rca.calls == []


def test_absent_rca_and_board_modules_record_a_pending_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, '_resolve', lambda module, name: None)
    model, _ = cr_omission_model(6)
    record = rd.decompose(model, tolerance_rule=_rule(0.02))
    result = rd.open_triggers(tmp_path, record, claim_id='C2')
    assert result['status'] == 'pending'
    pending = json.loads((tmp_path / 'claims' / 'rca_triggers.json').read_text())
    assert [row['trigger_id'] for row in pending['triggers']] == [record['sha256']]
    # The same decomposition does not queue a second trigger.
    rd.open_triggers(tmp_path, record, claim_id='C2')
    pending = json.loads((tmp_path / 'claims' / 'rca_triggers.json').read_text())
    assert len(pending['triggers']) == 1


def test_a_record_without_a_tolerance_rule_cannot_trigger(tmp_path):
    model, _ = cr_omission_model(4)
    record = rd.decompose(model)
    with pytest.raises(ValueError, match='tolerance'):
        rd.open_triggers(tmp_path, record, claim_id='C2', rca=Recorder(), board=Recorder())


# --- check:attribution_above_noise -----------------------------------------------------

def test_attribution_claim_below_threshold_is_refused():
    model, _ = cr_omission_model()
    record = rd.decompose(model)
    result = rd.check_attribution_above_noise(record, [{'term': 'rate', 'scope': 'all'}])
    assert result['kind'] == 'ravel-check-result'
    assert result['check_id'] == 'attribution_above_noise'
    assert result['status'] == 'failed'
    assert 'below its noise threshold' in result['refusals'][0]['reason']


def test_attribution_claim_on_a_node_below_threshold_is_refused():
    record = rd.decompose(noise_only_model())
    node = record['nodes'][0]['id']
    result = rd.check_attribution_above_noise(record, [{'term': 'shape', 'scope': f'node:{node}'}])
    assert result['status'] == 'failed'


def test_unsupported_fingerprint_attribution_is_refused():
    record = rd.decompose(rate_deficit_model())
    result = rd.check_attribution_above_noise(
        record, [{'term': 'rate', 'scope': 'all', 'fingerprint': 'reference_cr_signal_fraction'}])
    assert result['status'] == 'failed'
    assert 'fingerprint' in result['refusals'][0]['reason']


def test_attribution_claim_above_threshold_passes():
    model, _ = cr_omission_model()
    record = rd.decompose(model)
    result = rd.check_attribution_above_noise(
        record, [{'term': 'likelihood', 'scope': 'all', 'fingerprint': 'reference_cr_signal_fraction'}])
    assert result['status'] == 'passed', result['refusals']
    assert result['refusals'] == []


def test_unknown_scope_or_term_is_refused_not_ignored():
    record = rd.decompose(rate_deficit_model(4))
    for claim in ({'term': 'rate', 'scope': 'flavour:tt'}, {'term': 'pdf', 'scope': 'all'},
                  {'term': 'rate', 'scope': 'node:missing'}):
        assert rd.check_attribution_above_noise(record, [claim])['status'] == 'failed'
    assert rd.check_attribution_above_noise(record, [])['status'] == 'failed'


# --- run-level binding: approved target, producer custody ------------------------------

def bound_run(tmp_path, monkeypatch, model, *, rule=None, approved=True, compared=None, alpha=None,
              reference_noise=None):
    """A run whose CHECK-IN 1 approved the agreement target and its pinned reference noise, and
    whose residual model is the output of a registered stage receipt from a RAVEL tool module."""
    from rdj_fixtures import Run
    from ravel.workflow import workflow_state
    run = Run(tmp_path / 'run')
    noise = reference_noise or {'schema_version': 1, 'kind': 'residual-reference-noise', 'nodes': [
        {'coordinates': n['coordinates'], 'reference': n['reference'],
         'regions': {r['name']: {'staterror': r['reference']['staterror']} for r in n['regions']}}
        for n in model['nodes']]}
    if alpha is not None:
        noise['alpha'] = alpha
    pin = run.put('inputs/reference_noise.json', noise)
    coordinates = [n['coordinates'] for n in model['nodes']] if compared is None else compared
    target = {'claim_id': 'C2', 'tolerance_rule': rule or _rule(0.02),
              'noise_model': {'definition': 'synthetic', 'pin': {'locator': pin['path'], 'sha256': pin['sha256']}},
              'nodes': {'coordinates': ['m1', 'm2'], 'reference_lattice': coordinates, 'compared': coordinates}}
    record = run.put('inputs/agreement_targets.json', {'targets': [target]})
    run.put('inputs/checkin1.json', {'kind': 'checkin1', 'sections': {'agreement_targets': {
        'record_sha256': record['sha256'], 'claims': [{'claim_id': 'C2', 'status': 'valid', 'target': target}]}}})
    monkeypatch.setattr(workflow_state, 'verify_approval',
                        lambda *a, **k: [] if approved else ['stale or unbound approval: synthetic'])
    anchor = run.stage('residual-model', 'claims/residual_model.json', model)
    return run, anchor['binding']['receipt_id']


def test_diagnose_writes_records_and_pins_the_check(tmp_path, monkeypatch):
    model, _ = cr_omission_model(6)
    run, receipt = bound_run(tmp_path, monkeypatch, model)
    rca, board = Recorder(), Recorder()
    out = rd.diagnose(run.root, 'C2', model_receipt=receipt, rca=rca, board=board,
                      attributions=[{'term': 'likelihood', 'scope': 'all'}])
    paths = rd.paths('C2')
    for key in ('decomposition', 'noise', 'check'):
        assert (run.root / paths[key]).is_file()
    check = json.loads((run.root / paths['check']).read_text())
    assert check['status'] == 'passed'
    assert {pin['path'] for pin in check['pins']} == {paths['decomposition'], paths['noise']}
    assert out['trigger']['status'] == 'opened' and len(rca.calls) == 1
    record = json.loads((run.root / paths['decomposition']).read_text())
    assert record['inputs']['model']['receipt_id'] == receipt
    assert rd.delivery_errors(run.root) == []


def test_diagnose_without_a_valid_agreement_target_is_refused(tmp_path, monkeypatch):
    model, _ = cr_omission_model(3)
    run, receipt = bound_run(tmp_path, monkeypatch, model)
    with pytest.raises(ValueError, match='agreement-target'):
        rd.diagnose(run.root, 'C9', model_receipt=receipt)


def test_unapproved_target_is_refused(tmp_path, monkeypatch):
    model, _ = cr_omission_model(3)
    run, receipt = bound_run(tmp_path, monkeypatch, model, approved=False)
    with pytest.raises(ValueError, match='approval'):
        rd.diagnose(run.root, 'C2', model_receipt=receipt)


def test_target_changed_after_approval_is_refused(tmp_path, monkeypatch):
    model, _ = cr_omission_model(3)
    run, receipt = bound_run(tmp_path, monkeypatch, model)
    run.put('inputs/agreement_targets.json', {'targets': [], 'edited': True})
    with pytest.raises(ValueError, match='changed after'):
        rd.diagnose(run.root, 'C2', model_receipt=receipt)


def test_agent_written_residual_model_is_refused(tmp_path, monkeypatch):
    model = rate_deficit_model()
    run, receipt = bound_run(tmp_path, monkeypatch, model)
    for node in model['nodes']:
        for region in node['regions']:
            region['ours']['sumw2'] = [w * 1e4 for w in region['ours']['sumw2']]
    run.put('claims/residual_model.json', model)
    with pytest.raises(ValueError, match='stage receipt'):
        rd.diagnose(run.root, 'C2', model_receipt=receipt, rca=Recorder(), board=Recorder())


def test_inflated_noise_cannot_hide_a_real_residual(tmp_path, monkeypatch):
    """Gaming: a real 20% rate deficit, with the reference noise inflated in the producer's model."""
    honest = rate_deficit_model()
    rca = Recorder()
    run, receipt = bound_run(tmp_path, monkeypatch, honest, rule=_rule(0.05))
    assert rd.diagnose(run.root, 'C2', model_receipt=receipt, rca=rca, board=rca)['trigger']['status'] == 'opened'
    inflated = rate_deficit_model()
    approved_noise = json.loads((run.root / 'inputs/reference_noise.json').read_text())
    for node in inflated['nodes']:
        for region in node['regions']:
            region['reference']['staterror'] = [e * 100.0 for e in region['reference']['staterror']]
    assert rd.decompose(inflated, tolerance_rule=_rule(0.05))['exceedance']['beyond_noise'] is False
    run2, receipt2 = bound_run(tmp_path / 'second', monkeypatch, inflated, rule=_rule(0.05),
                               reference_noise=approved_noise)
    with pytest.raises(ValueError, match='approved noise model'):
        rd.diagnose(run2.root, 'C2', model_receipt=receipt2, rca=rca, board=rca)
    with pytest.raises(TypeError):
        rd.diagnose(run.root, 'C2', model_receipt=receipt, alpha=0.999)


def test_alpha_comes_from_the_approved_noise_model(tmp_path, monkeypatch):
    model = noise_only_model(n=8)
    run, receipt = bound_run(tmp_path, monkeypatch, model, alpha=0.2, rule=_rule(0.01))
    rd.diagnose(run.root, 'C2', model_receipt=receipt, rca=Recorder(), board=Recorder())
    assert json.loads((run.root / rd.paths('C2')['decomposition']).read_text())['alpha'] == 0.2


def test_cherry_picked_nodes_are_refused(tmp_path, monkeypatch):
    model = rate_deficit_model(10)
    compared = [n['coordinates'] for n in model['nodes']]
    model['nodes'] = model['nodes'][:1]
    run, receipt = bound_run(tmp_path, monkeypatch, model, compared=compared)
    with pytest.raises(ValueError, match='compared nodes'):
        rd.diagnose(run.root, 'C2', model_receipt=receipt)


def test_delivery_refuses_a_missing_or_rehashed_decomposition(tmp_path, monkeypatch):
    model = rate_deficit_model(6)
    run, receipt = bound_run(tmp_path, monkeypatch, model)
    assert any('residual decomposition' in e for e in rd.delivery_errors(run.root))
    rd.diagnose(run.root, 'C2', model_receipt=receipt, rca=Recorder(), board=Recorder(),
                attributions=[{'term': 'likelihood', 'scope': 'all'}])
    path = run.root / rd.paths('C2')['decomposition']
    record = json.loads(path.read_text())
    record['attribution']['all']['terms']['likelihood'].update(above_noise=True, threshold=1e-9)
    record['sha256'] = rd._digest({k: v for k, v in record.items() if k != 'sha256'})
    path.write_text(json.dumps(record))
    assert any('recomputed' in e for e in rd.delivery_errors(run.root))
    from ravel.workflow import decision_gate
    assert any(p['id'] == 'residual_diagnosis' and 'delivery' in p['gates'] for p in decision_gate.providers('delivery'))
    assert rd.gate_errors(run.root, 'delivery', {})


def test_rehashed_above_noise_flag_alone_is_refused():
    record = rd.decompose(rate_deficit_model())
    record['attribution']['all']['terms']['shape']['above_noise'] = True
    record['sha256'] = rd._digest({k: v for k, v in record.items() if k != 'sha256'})
    assert rd.check_attribution_above_noise(record, [{'term': 'shape', 'scope': 'all'}])['status'] == 'failed'


# --- noise and statistics hardening ----------------------------------------------------

def test_many_random_fingerprints_support_nothing():
    model, _ = cr_omission_model()
    rng = np.random.default_rng(3)
    for node in model['nodes']:
        node['fingerprints'] = {f'v{i}': float(rng.standard_normal()) for i in range(100)}
    record = rd.decompose(model)
    supported = [v for term in record['fingerprints'].values() for v, row in term.items()
                 if row['supported'] and v.startswith('v')]
    assert supported == []
    assert record['fingerprints']['likelihood']['reference_cr_signal_fraction']['supported'] is True


def test_degenerate_replicas_are_refused_and_floored():
    model = noise_only_model(n=6)
    for node in model['nodes']:
        node['replicas'] = [{'value': node['result'], 'seed': 1}, {'value': node['result'] * (1 + 1e-9), 'seed': 1}]
    with pytest.raises(ValueError, match='replicas'):
        rd.decompose(model)
    base = noise_model.build(noise_only_model(n=6), rd.node_terms)
    for node in model['nodes']:
        node['replicas'] = [{'value': node['result'] * (1 + 1e-12 * k), 'seed': k} for k in range(3)]
    floored = noise_model.build(model, rd.node_terms)
    assert floored['nodes'][0]['sigma']['total'] >= base['nodes'][0]['sigma']['total'] * 0.999


def test_likelihood_without_result_noise_is_not_attributable():
    model, _ = cr_omission_model()
    for node in model['nodes']:
        del node['replicas']
    record = rd.decompose(model)
    assert record['attribution']['all']['terms']['likelihood']['threshold'] is None
    result = rd.check_attribution_above_noise(record, [{'term': 'likelihood', 'scope': 'all'}])
    assert result['status'] == 'failed' and 'replicas' in result['refusals'][0]['reason']


def test_zero_sumw2_with_a_yield_is_a_refusal_not_a_crash():
    model, _ = cr_omission_model(4)
    model['nodes'][0]['regions'][0]['ours']['sumw2'] = [0.0, 0.0]
    with pytest.raises(ValueError, match='sumw2'):
        rd.decompose(model, tolerance_rule=_rule(0.02))


def test_all_zero_signal_region_and_zero_background_bin_are_valid():
    model = rate_deficit_model(5)
    for node in model['nodes']:
        node['regions'].append({'name': 'empty', 'role': 'signal', 'flavour': 'ee', 'background': [3.0],
                                'ours': {'yield': [0.0], 'sumw2': [0.0]},
                                'reference': {'yield': [0.0], 'staterror': [0.0]}})
        node['regions'][0]['background'][1] = 0.0
    record = rd.decompose(model)
    assert record['attribution']['region:empty']['assigned'] is None
    assert record['attribution']['all']['assigned'] == 'rate'


def test_decomposition_is_deterministic():
    model, _ = cr_omission_model(5)
    assert rd.decompose(model)['sha256'] == rd.decompose(json.loads(json.dumps(model)))['sha256']
