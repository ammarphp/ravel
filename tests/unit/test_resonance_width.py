"""Tree-level resonance widths and branching ratios over declared fermion channels."""

from method_decision_fixture import admit_method
import json
import math

import pytest

from ravel.physics import resonance_width as rw
from ravel.workflow import science

ALPHA, S2 = 1 / 128.0, 0.2312
SM = [('ee', 'e', 0.000511), ('mumu', 'mu', 0.1057), ('tautau', 'tau', 1.777),
      ('nn_e', 've', 0.), ('nn_m', 'vm', 0.), ('nn_t', 'vt', 0.),
      ('uu', 'u', 0.0022), ('cc', 'c', 1.27), ('tt', 't', 172.5),
      ('dd', 'd', 0.0047), ('ss', 's', 0.093), ('bb', 'b', 4.18)]


def sequential(mass=2500., scale=1.0):
    return {'schema_version': 1, 'source': 'Sequential pattern with declared electroweak inputs',
            'resonance': {'name': "Z'", 'spin': 1, 'mass_gev': mass},
            'couplings': {'scheme': 'sequential_sm', 'sin2_theta_w': S2, 'alpha_em': ALPHA, 'scale_factor': scale},
            'channels': [{'id': i, 'fermion': f, 'mass_gev': m} for i, f, m in SM],
            'groups': {'charged_leptons': ['ee', 'mumu', 'tautau']}}


def g_z():
    return math.sqrt(4 * math.pi * ALPHA / (S2 * (1 - S2)))


def test_sequential_vector_widths_match_the_massless_formula():
    value = rw.calculate(sequential())
    ee = next(c for c in value['channels'] if c['id'] == 'ee')
    gl, gr = g_z() * (-.5 + S2), g_z() * S2
    assert ee['gL']['Re'] == pytest.approx(gl) and ee['gR']['Re'] == pytest.approx(gr)
    assert ee['partial_width_gev'] == pytest.approx(2500. * (gl ** 2 + gr ** 2) / (24 * math.pi), rel=1e-6)
    uu = next(c for c in value['channels'] if c['id'] == 'uu')
    gl_u, gr_u = g_z() * (.5 - 2 / 3 * S2), -g_z() * 2 / 3 * S2
    assert uu['partial_width_gev'] == pytest.approx(3 * 2500. * (gl_u ** 2 + gr_u ** 2) / (24 * math.pi), rel=1e-6)
    assert value['total_width_gev'] == pytest.approx(sum(c['partial_width_gev'] for c in value['channels']))
    assert sum(c['branching_ratio'] for c in value['channels']) == pytest.approx(1.)
    group = value['groups']['charged_leptons']
    assert group['branching_ratio'] == pytest.approx(sum(c['branching_ratio'] for c in value['channels'] if c['id'] in ('ee', 'mumu', 'tautau')))
    assert 0.02 < value['width_over_mass'] < 0.05
    assert 'massless limit' in value['formula']


def test_widths_scale_with_mass_and_coupling_squared():
    a = rw.calculate(sequential(1000.))
    b = rw.calculate(sequential(1000., scale=2.))
    ee = lambda v: next(c for c in v['channels'] if c['id'] == 'ee')['partial_width_gev']
    assert ee(b) == pytest.approx(4 * ee(a))


def test_scalar_yukawa_width_has_beta_cubed_threshold():
    y, m, mt = 1.2, 750., 172.5
    d = {'schema_version': 1, 'source': 'declared scalar Yukawa', 'resonance': {'name': 'S', 'spin': 0, 'mass_gev': m},
         'couplings': {'scheme': 'declared'}, 'channels': [{'id': 'tt', 'fermion': 't', 'mass_gev': mt, 'gL': y, 'gR': y}]}
    beta = math.sqrt(1 - 4 * mt ** 2 / m ** 2)
    assert rw.calculate(d)['channels'][0]['partial_width_gev'] == pytest.approx(3 * y ** 2 * m * beta ** 3 / (8 * math.pi))


def test_vector_axial_declaration_and_closed_channel():
    d = {'schema_version': 1, 'source': 'declared vector couplings', 'resonance': {'name': 'V', 'spin': 1, 'mass_gev': 300.},
         'couplings': {'scheme': 'declared'},
         'channels': [{'id': 'chi', 'fermion': 'chi', 'mass_gev': 0., 'color': 1, 'gV': 1.0, 'gA': 0.},
                      {'id': 'heavy', 'fermion': 'Q', 'mass_gev': 200., 'color': 3, 'gL': .5, 'gR': .5}]}
    value = rw.calculate(d)
    chi, heavy = value['channels']
    assert chi['partial_width_gev'] == pytest.approx(300. * 2 / (24 * math.pi))
    assert heavy['open'] is False and heavy['partial_width_gev'] == 0 and chi['branching_ratio'] == 1


@pytest.mark.parametrize('change', ['spin', 'unknown_fermion', 'missing_coupling', 'group', 'scalar_sequential', 'duplicate'])
def test_invalid_declarations_refuse(change):
    d = sequential()
    if change == 'spin':
        d['resonance']['spin'] = 2
    elif change == 'unknown_fermion':
        d['channels'][0]['fermion'] = 'chi'
    elif change == 'missing_coupling':
        d['couplings'] = {'scheme': 'declared'}
    elif change == 'group':
        d['groups'] = {'x': ['not-a-channel']}
    elif change == 'scalar_sequential':
        d['resonance']['spin'] = 0
    else:
        d['channels'][1]['id'] = 'ee'
    with pytest.raises(ValueError):
        rw.calculate(d)


def test_registered_ordinary_mode_runs_and_writes_result(tmp_path):
    (tmp_path / 'width.json').write_text(json.dumps(sequential()))
    spec = {'mode': 'resonance-width', 'task': {'input': 'width.json'}}
    assert science.adapter(spec) is rw and science._new_capability(spec)
    assert rw.inputs(spec['task'], tmp_path) == [(tmp_path / 'width.json').resolve()]
    result = rw.run(spec['task'], tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert json.loads((tmp_path / 'out/resonance-width.json').read_text())['total_width_gev'] == result['total_width_gev']


def test_ordinary_lifecycle_plan_approve_run(tmp_path):
    work = tmp_path / 'request'
    work.mkdir()
    (work / 'width.json').write_text(json.dumps(sequential(3000.)))
    policy = {'schema_version': 1, 'policy': {'schema_version': 1,
              'actors': {'proposer': 'p', 'executor': 'e', 'physics_critic': 'c', 'skeptical_verifier': 'v', 'physics_decider': 'd'},
              'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
              'required_checks': [{'id': 'integrity', 'kind': 'integrity'}],
              'claim_scopes': {rw.SCOPE: {'checks': ['integrity'], 'actions': ['delivery']}}},
              'correction_contract': {'task_fields': [], 'input_slots': []}}
    spec = {'schema_version': 2, 'mode': 'resonance-width', 'source': 'declared sequential couplings',
            'assumptions': ['Tree level over the declared channels.'], 'max_seconds': 120, 'approval_mode': 'scripted_yes',
            'max_attempts': 1, 'task': {'input': 'width.json'}, 'review_policy': policy}
    (work / 'science.json').write_text(json.dumps(spec))
    rd = tmp_path / 'study'
    science.plan(rd, work / 'science.json'); admit_method(rd)
    science.approve(rd, 'Scripted engineering check.', scripted=True)
    assert science.run(rd) == 0
    result = json.loads(next(rd.rglob('resonance-width.json')).read_text())
    assert result['status'] == 'passed' and result['groups']['charged_leptons']['branching_ratio'] > 0.05
