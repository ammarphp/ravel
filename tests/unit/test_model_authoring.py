"""Model-authoring kit: ModelSpec checks, .fr rendering and lint, two-gauge verdicts, UFO checks.

No FeynRules, Wolfram or MadGraph process runs here; native runs are replaced by
recorded or synthetic receipts.
"""
import copy
import json
import types
from pathlib import Path

import pytest

from ravel.physics import fr_lint, model_authoring as ma, ufo_check

ZERO = [[0.0] * 3 for _ in range(3)]


def one(i, j, value):
    m = copy.deepcopy(ZERO)
    m[i][j] = value
    return m


def zprime():
    return ma.instantiate('neutral-vector', dict(mass_GeV=2000., width_GeV=60., gV_u=0.1, gA_u=0.1, gV_d=0.1,
                                                 gA_d=0.0, gV_l=0.05, gA_l=0.05, gL_v=0.02, kinetic_mixing=0.01))


def scalar_lq(**over):
    values = dict(mass_GeV=1500., width_GeV=10., quark='uq', lepton='l', fermion_number=2, charge='-1/3',
                  coupling_L=one(2, 2, 1.0), coupling_R=one(0, 1, 0.5))
    values.update(over)
    return ma.instantiate('scalar-leptoquark', values)


def all_templates():
    return {
        'neutral-vector': zprime(),
        'scalar-leptoquark': scalar_lq(),
        'vector-leptoquark': ma.instantiate('vector-leptoquark', dict(
            mass_GeV=2000., width_GeV=20., quark='dq', lepton='l', fermion_number=0, charge='2/3',
            coupling_L=one(2, 2, 1.0), coupling_R=ZERO, kappa=1.0)),
        'axion-like-particle': ma.instantiate('axion-like-particle', dict(
            mass_GeV=500., width_GeV=1., g_GG=1e-3, g_WW=1e-3, g_BB=2e-3)),
    }


@pytest.mark.parametrize('name', ['neutral-vector', 'scalar-leptoquark', 'vector-leptoquark', 'axion-like-particle'])
def test_every_template_renders_lint_clean_with_neutral_hermitian_canonical_terms(name):
    spec = all_templates()[name]
    text = ma.render_fr(spec)
    report = fr_lint.lint(text, spec=spec)
    assert report['passed'], report['errors']
    assert report['warnings'] == []
    assert ma.charge_census(spec)['passed']
    assert ma.hermiticity_census(spec)['passed']
    assert ma.quadratic_census(spec)['passed']
    assert 'LFull := LSM + LNew;' in text and f'M$ModelName = "{spec["name"]}"' in text
    for p in spec['parameters']:
        assert f'{p["symbol"]} == {{' in text


def test_physics_values_have_no_defaults():
    with pytest.raises(ValueError, match='needs mass_GeV'):
        ma.instantiate('neutral-vector', dict(width_GeV=1., gV_u=0, gA_u=0, gV_d=0, gA_d=0, gV_l=0, gA_l=0, gL_v=0))
    with pytest.raises(ValueError, match='needs coupling_L'):
        ma.instantiate('scalar-leptoquark', dict(mass_GeV=1., width_GeV=1., quark='uq', lepton='l',
                                                 fermion_number=0, charge='5/3', coupling_R=ZERO))


def test_leptoquark_charge_is_checked_against_the_coupling():
    with pytest.raises(ValueError, match='differs from the charge -1/3'):
        scalar_lq(charge='1/3')
    assert scalar_lq(fermion_number=0, charge='5/3')['fields'][0]['hypercharge'] == '5/3'
    with pytest.raises(ValueError, match='no right-handed neutrinos'):
        scalar_lq(lepton='vl', fermion_number=0, charge='2/3')


def test_lepton_number_is_assigned_so_every_coupling_conserves_it():
    for f2 in (0, 2):
        spec = scalar_lq(fermion_number=f2, charge='5/3' if f2 == 0 else '-1/3')
        assert spec['fields'][0]['quantum_numbers'] == {'LeptonNumber': 1 if f2 else -1}
        assert ma.charge_census(spec)['passed']
    spec = scalar_lq()
    spec['fields'][0]['quantum_numbers'] = {'LeptonNumber': -1}
    rows = ma.charge_census(spec)['terms']
    assert any('LeptonNumber sums to' in p for r in rows for p in r['problems'])


def test_rendered_bosons_carry_explicit_colour_and_explicit_hypercharge_connection():
    text = ma.render_fr(scalar_lq())
    assert 'DC[LQsbar[cc1],mu] + I g1 (-1/3) B[mu] LQsbar[cc1]' in text
    assert 'QuantumNumbers   -> {Q -> -1/3, LeptonNumber -> 1}' in text
    assert 'Y ->' not in text
    zp = ma.render_fr(zprime())
    assert 'QuantumNumbers' not in zp.split('M$Parameters')[0]  # real fields carry no quantum numbers


def test_missing_hc_is_caught():
    spec = scalar_lq()
    spec['lagrangian_terms'][0]['hc'] = False
    census = ma.hermiticity_census(spec)
    assert not census['passed'] and 'missing h.c.' in census['terms'][0]['reason']


def test_off_diagonal_mass_term_is_caught():
    spec = zprime()
    spec['fields'].append({**copy.deepcopy(spec['fields'][0]), 'name': 'Zpp', 'pdg': 9000016,
                           'mass': {'symbol': 'MZpp', 'value': 3000.}, 'width': {'symbol': 'WZpp', 'value': 1.}})
    spec['parameters'].append({'symbol': 'mmix', 'nature': 'external', 'block': 'MIXING', 'index': [1], 'value': 10.})
    spec['lagrangian_terms'].append({'id': 'mix', 'kind': 'mass', 'hc': False, 'couplings': ['mmix'],
                                     'operator': 'mmix^2 Zp[mu] Zpp[mu]',
                                     'fields': [{'field': 'Zp'}, {'field': 'Zpp'}]})
    census = ma.quadratic_census(spec)
    assert not census['passed'] and 'off-diagonal mass term' in census['problems'][0]


def test_non_canonical_kinetic_term_is_caught():
    spec = zprime()
    spec['fields'][0]['kinetic'] = 'declared'
    spec['parameters'].append({'symbol': 'kn', 'nature': 'external', 'block': 'KIN', 'index': [1], 'value': 1.})
    spec['lagrangian_terms'].append({'id': 'kin', 'kind': 'kinetic', 'hc': False, 'couplings': [], 'normalization': 0.5,
                                     'operator': '-1/2 del[Zp[nu],mu] del[Zp[nu],mu]', 'fields': [{'field': 'Zp'}]})
    census = ma.quadratic_census(spec)
    assert not census['passed'] and 'not canonical (0.25)' in census['problems'][0]
    spec2 = zprime()
    spec2['lagrangian_terms'].append({'id': 'kin2', 'kind': 'kinetic', 'hc': False, 'couplings': [],
                                      'operator': '-1/4 del[Zp[nu],mu] del[Zp[nu],mu]', 'fields': [{'field': 'Zp'}]})
    assert 'makes it non-canonical' in ma.quadratic_census(spec2)['problems'][0]


def test_non_neutral_monomial_is_caught():
    spec = scalar_lq()
    spec['lagrangian_terms'][0]['fields'][1] = {'field': 'vl'}
    rows = ma.charge_census(spec)['terms']
    assert not rows[0]['passed'] and 'electric charge sums to' in rows[0]['problems'][0]


def test_unsupported_features_are_refused_for_routing_elsewhere():
    spec = zprime()
    spec['fields'][0]['su2'] = 2
    with pytest.raises(ma.UnsupportedModel, match='SU\\(2\\) multiplet'):
        ma.validate_spec(spec)
    spec = zprime()
    spec['fields'][0]['su3'] = '3bar'
    with pytest.raises(ma.UnsupportedModel, match='conjugate triplet'):
        ma.validate_spec(spec)
    spec = zprime()
    spec['unsupported_features'] = ['new U(1) gauge group']
    with pytest.raises(ma.UnsupportedModel):
        ma.validate_spec(spec)


def test_spec_refuses_decimal_charges_sm_clashes_and_short_names():
    spec = zprime()
    spec['fields'][0]['hypercharge'] = '0.333'
    with pytest.raises(ValueError, match='exact rational'):
        ma.validate_spec(spec)
    spec = zprime()
    spec['fields'][0]['pdg'] = 23
    with pytest.raises(ValueError, match='PDG code'):
        ma.validate_spec(spec)
    spec = zprime()
    spec['fields'][0]['name'] = 'a'
    with pytest.raises(ValueError, match='too short'):
        ma.validate_spec(spec)


FR_HEADER = 'M$ModelName = "Toy";\nM$ClassesDescription = {\n'


def toy_fr(classname='Xx', pdg=9000100, body='', index=101):
    return (FR_HEADER + f'  S[{index}] == {{ ClassName -> {classname}, SelfConjugate -> True, '
            f'Mass -> {{MX, 10.}}, Width -> {{WX, 1.}}, PDG -> {pdg}, ParticleName -> "xx" }}\n}};\n' + body)


def test_lint_one_character_classname_and_sm_collisions():
    errors = fr_lint.lint(toy_fr('a'))['errors']
    assert any('one-character ClassName' in e for e in errors)
    errors = fr_lint.lint(toy_fr('Xx', pdg=23, index=1))['errors']
    assert any('PDG 23' in e for e in errors) and any('S[1]' in e for e in errors)
    assert fr_lint.lint(toy_fr())['passed']


@pytest.mark.parametrize('body,needle', [
    ('Get["evil.m"];', 'Get is not allowed'),
    ('<< "evil.m";', 'file operator'),
    ('x = Import["data.csv"];', 'Import is not allowed'),
    ('y = Run["ls"];', 'Run is not allowed'),
    ('z = Global`q;', 'context-qualified'),
])
def test_lint_refuses_file_and_process_access(body, needle):
    report = fr_lint.lint(toy_fr(body=body))
    assert not report['passed'] and any(needle in e for e in report['errors'])


def test_lint_unbalanced_and_unterminated():
    assert any('unclosed' in e for e in fr_lint.lint(toy_fr(body='L := Block[{mu}, x['))['errors'])
    assert 'unterminated comment' in fr_lint.lint('(* open')['errors'][0]


def test_lint_cross_checks_spec_census_and_required_coupling():
    spec = scalar_lq()
    text = ma.render_fr(spec)
    bad = copy.deepcopy(spec)
    bad['lagrangian_terms'][0]['fields'] = bad['lagrangian_terms'][0]['fields'][:2]
    assert any('not in the field census' in e for e in fr_lint.lint(text, spec=bad)['errors'])
    bad = copy.deepcopy(spec)
    bad['parameters'].append({'symbol': 'unused', 'nature': 'external', 'block': 'XB', 'index': [1], 'value': 1.})
    bad['required_couplings'].append('unused')
    errors = fr_lint.lint(text, spec=bad)['errors']
    assert any('unused is not declared' in e for e in errors)
    assert any('required coupling unused appears in no Lagrangian term' in e for e in errors)


def test_lint_refuses_redeclared_gauge_groups_in_an_extension():
    spec = zprime()
    text = ma.render_fr(spec) + '\nM$GaugeGroups = {U1X == {Abelian -> True}};\n'
    assert any('must not redeclare M$GaugeGroups' in e for e in fr_lint.lint(text, spec=spec)['errors'])


def test_lint_against_installed_sm_inventory_when_available():
    import os
    root = Path(os.environ.get('RAVEL_NATIVE_BUILD', '/nonexistent'))
    sm = root / 'tools/feynrules-extract/feynrules-current/Models/SM/SM.fr'
    if not sm.is_file():
        pytest.skip('FeynRules SM.fr is not installed here')
    inv = fr_lint.sm_inventory(sm.read_text())
    assert {'uq', 'dq', 'Phi'} <= inv['class_names'] and {22, 23, 25} <= inv['pdgs']
    spec = zprime()
    assert fr_lint.lint(ma.render_fr(spec), spec=spec, sm_text=sm.read_text())['passed']


# ------------------------------------------------------------ gauge verdicts

def row(holds, printed=''):
    return {'holds': holds, 'message_free': True, 'returned': str(holds), 'printed': printed}


def gauge_record(*, feynman_quad=True, unitary_quad=True, pairs=(), printed='', feynman_herm=True):
    def gauge(quad, herm, p):
        return {'CheckHermiticity': row(herm), 'CheckDiagonalQuadraticTerms': row(quad, printed if not quad else ''),
                'CheckDiagonalMassTerms': row(True), 'CheckKineticTermNormalisation': row(True),
                'offdiagonal_quadratic_pairs': [list(x) for x in p]}
    return {'feynman': gauge(feynman_quad, feynman_herm, pairs), 'unitary': gauge(unitary_quad, True, ()),
            'goldstones': ['G0', 'GP']}


def test_benign_goldstone_mixing_in_feynman_gauge_is_waived():
    native = gauge_record(feynman_quad=False, pairs=[('GPbar', 'W'), ('GP', 'Wbar'), ('G0', 'Z')],
                          printed='Non diagonal quadratic term found: ee vev del[GPbar, mu] W[mu]')
    verdict = ma.adjudicate_gauge_checks(native)
    assert verdict['passed']
    assert verdict['verdicts']['feynman']['CheckDiagonalQuadraticTerms'] == 'waived-goldstone-mixing'
    assert verdict['waived'][0]['pairs'] == [['G0', 'Z'], ['GP', 'W']]


def test_goldstone_waiver_needs_the_reported_warning_and_goldstone_pairs():
    silent = gauge_record(feynman_quad=False, pairs=[('G0', 'Z')], printed='')
    assert not ma.adjudicate_gauge_checks(silent)['passed']
    new_mixing = gauge_record(feynman_quad=False, pairs=[('G0', 'Z'), ('Zp', 'Z')], printed='Non diagonal')
    assert not ma.adjudicate_gauge_checks(new_mixing)['passed']
    unitary_fail = gauge_record(feynman_quad=False, unitary_quad=False, pairs=[('G0', 'Z')], printed='Non diagonal')
    assert not ma.adjudicate_gauge_checks(unitary_fail)['passed']


def test_other_feynman_gauge_failures_are_never_waived():
    verdict = ma.adjudicate_gauge_checks(gauge_record(feynman_herm=False))
    assert not verdict['passed'] and verdict['failures'] == ['feynman gauge: CheckHermiticity fails']


def test_run_script_loads_sm_and_model_and_checks_both_gauges(tmp_path):
    spec = zprime()
    text = ma.run_script(spec, feynrules_root=tmp_path / 'fr', model_dir=tmp_path / 'm', ufo_dir=tmp_path / 'u',
                         receipt=tmp_path / 'r.json')
    assert f'LoadModel["{tmp_path}/m/SM.fr", "{tmp_path}/m/{spec["name"]}.fr"]' in text
    assert 'ravelGauge[True]' in text and 'ravelGauge[False]' in text
    assert 'CheckKineticTermNormalisation[lagNew' in text and 'CheckDiagonalMassTerms[lagFull]' in text
    assert 'WriteUFO[Global`LFull' in text


# ----------------------------------------------------------------- UFO checks

UFO_FILES = {
    '__init__.py': 'import particles\n',
    'object_library.py': 'class Particle: pass\n',
    'parameters.py': (
        "from object_library import Parameter\n"
        "ZERO = Parameter(name='ZERO', nature='internal', type='real', value='0.0', texname='0')\n"
        "MZp = Parameter(name='MZp', nature='external', type='real', value=2000., texname='M', lhablock='MASS', lhacode=[9000006])\n"
        "WZp = Parameter(name='WZp', nature='external', type='real', value=60., texname='W', lhablock='DECAY', lhacode=[9000006])\n"
        "gVuZp = Parameter(name='gVuZp', nature='external', type='real', value=0.1, texname='g', lhablock='ZPCOUP', lhacode=[1])\n"
        "gAuZp = Parameter(name='gAuZp', nature='external', type='real', value=0.1, texname='g', lhablock='ZPCOUP', lhacode=[2])\n"),
    'particles.py': (
        "from object_library import Particle\nimport parameters as Param\n"
        "u = Particle(pdg_code=2, name='u', antiname='u~', spin=2, color=3, mass=Param.ZERO, width=Param.ZERO, charge=2/3)\n"
        "u__tilde__ = u.anti()\n"
        "Zp = Particle(pdg_code=9000006, name='zp', antiname='zp', spin=3, color=1, mass=Param.MZp, width=Param.WZp, charge=0)\n"),
    'couplings.py': (
        "from object_library import Coupling\n"
        "GC_1 = Coupling(name='GC_1', value='complex(0,1)*gVuZp', order={'NP':1})\n"
        "GC_2 = Coupling(name='GC_2', value='complex(0,1)*gAuZp', order={'NP':1})\n"),
    'lorentz.py': "from object_library import Lorentz\nFFV1 = Lorentz(name='FFV1', spins=[2,2,3], structure='Gamma(3,2,1)')\n",
    'vertices.py': (
        "from object_library import Vertex\nimport particles as P\nimport couplings as C\nimport lorentz as L\n"
        "V_1 = Vertex(name='V_1', particles=[P.u__tilde__, P.u, P.Zp], color=['Identity(1,2)'], lorentz=[L.FFV1], "
        "couplings={(0,0):C.GC_1})\n"),
}


def write_ufo(root, **overrides):
    root.mkdir()
    for name, text in {**UFO_FILES, **overrides}.items():
        (root / name).write_text(text)
    return root


def ufo_spec():
    spec = zprime()
    keep = {'gVuZp', 'gAuZp'}
    spec['parameters'] = [p for p in spec['parameters'] if p['symbol'] in keep]
    spec['lagrangian_terms'] = [t for t in spec['lagrangian_terms'] if set(t['couplings']) <= keep]
    spec['required_couplings'] = ['gVuZp']
    spec['optional_couplings'] = []
    return spec


def test_static_ufo_check_passes_and_records_coupling_survival(tmp_path):
    report = ufo_check.check(write_ufo(tmp_path / 'ufo'), spec=ufo_spec())
    assert report['passed'], report['errors']
    assert report['required_coupling_survival'] == {'gVuZp': True}
    assert report['counts']['vertices'] == 1


def test_python2_raise_is_refused(tmp_path):
    ufo = write_ufo(tmp_path / 'ufo', **{'function_library.py': 'def f():\n    raise UFOError, "bad"\n'})
    report = ufo_check.check(ufo)
    assert not report['passed'] and 'does not parse as Python 3' in report['errors'][0]


def test_required_coupling_present_but_in_no_vertex_is_refused(tmp_path):
    spec = ufo_spec()
    spec['required_couplings'] = ['gVuZp', 'gAuZp']
    report = ufo_check.check(write_ufo(tmp_path / 'ufo'), spec=spec)
    assert not report['passed']
    assert report['errors'] == ['required coupling gAuZp appears in no coupling used by a vertex']


def test_mathematica_leftovers_duplicate_pdg_and_massless_width_are_refused(tmp_path):
    particles = UFO_FILES['particles.py'] + (
        "Zq = Particle(pdg_code=9000006, name='zq', antiname='zq', spin=3, color=1, mass=Param.ZERO, width=Param.WZp, charge=0)\n")
    couplings = UFO_FILES['couplings.py'] + "GC_3 = Coupling(name='GC_3', value='Global`x', order={'NP':1})\n"
    report = ufo_check.check(write_ufo(tmp_path / 'ufo', **{'particles.py': particles, 'couplings.py': couplings}))
    assert any('Mathematica leftover' in e for e in report['errors'])
    report = ufo_check.check(write_ufo(tmp_path / 'ufo2', **{'particles.py': particles}))
    assert any('PDG 9000006 declared by Zp and Zq' in e for e in report['errors'])
    assert any('massless with a nonzero width' in e for e in report['errors'])


def test_spec_ufo_consistency_charge_and_missing_field(tmp_path):
    spec = ufo_spec()
    spec['fields'][0]['pdg'] = 9000099
    report = ufo_check.check(write_ufo(tmp_path / 'ufo'), spec=spec)
    assert any('is not in the UFO' in e for e in report['errors'])


def fake_mg5(output, returncode=0):
    return lambda cmd: types.SimpleNamespace(stdout=output, stderr='', returncode=returncode)


def test_madgraph_import_and_generate_requires_a_diagram(tmp_path):
    ufo = write_ufo(tmp_path / 'ufo')
    ok = ufo_check.madgraph_generate(ufo, 'p p > zp', mg5='mg5_aMC', workdir=tmp_path / 'a',
                                     runner=fake_mg5('INFO: Process has 2 diagrams\nTotal: 2 processes with 4 diagrams\n'))
    assert ok['passed'] and ok['diagrams'] == 4
    assert (tmp_path / 'a' / 'check.mg5').read_text().splitlines()[-1] == 'generate p p > zp'
    none = ufo_check.madgraph_generate(ufo, 'p p > zp', mg5='mg5_aMC', workdir=tmp_path / 'b',
                                       runner=fake_mg5('NoDiagramException : No amplitudes generated\n'))
    assert not none['passed'] and 'no diagrams' in none['errors'][0]
    broken = ufo_check.madgraph_generate(ufo, 'p p > zp', mg5=['python', 'mg5_aMC'], workdir=tmp_path / 'c',
                                         runner=fake_mg5('ERROR: model import failed\nTotal: 1 processes with 1 diagrams'))
    assert not broken['passed'] and 'did not import' in broken['errors'][0]
    with pytest.raises(ValueError):
        ufo_check.madgraph_generate(ufo, 'p p > zp\nshell rm', mg5='x', workdir=tmp_path / 'd')


# ----------------------------------------------------- authoring end to end

def fake_feynrules(tmp_path):
    root = tmp_path / 'feynrules'
    (root / 'Models/SM').mkdir(parents=True)
    (root / 'Models/SM/SM.fr').write_text('M$ModelName = "Standard Model";\n')
    return root


def test_author_writes_pinned_model_tree_and_bridge_request(tmp_path):
    spec = zprime()
    record = ma.author(spec, tmp_path / 'out', feynrules=fake_feynrules(tmp_path))
    assert record['status'] == 'authored' and record['label'] == 'generated_contract_checked'
    out = tmp_path / 'out'
    assert (out / 'model/SM.fr').is_file() and (out / f'model/{spec["name"]}.fr').is_file()
    request = json.loads((out / 'derivation-request.json').read_text())
    assert request['model_files'] == ['SM.fr', f'{spec["name"]}.fr']
    assert request['two_gauge_checks'] == {'new_terms_symbol': 'LNew'}
    with pytest.raises(ValueError, match='exists'):
        ma.author(spec, out, feynrules=fake_feynrules(tmp_path / 'again'))


def test_run_native_adjudicates_converts_checks_and_writes_card(tmp_path):
    spec = ufo_spec()
    out = tmp_path / 'out'
    ma.author(spec, out, feynrules=fake_feynrules(tmp_path))
    native = {'status': 'completed', 'kernel_version': 15.0, 'provider_version': '2.3.49', 'new_vertex_count': 4,
              'vertex_messages': [], 'ufo_messages': [], 'ufo_written': True,
              'gauge_checks': gauge_record(feynman_quad=False, pairs=[('G0', 'Z')], printed='Non diagonal')}

    def runner(command, native_dir, limits):
        assert command[-1].endswith('run.wl') and limits['max_seconds'] == 60
        (out / 'native-checks.json').write_text(json.dumps(native))
        write_ufo(out / 'ufo', **{'object_library.py': 'class UFOError(Exception):\n    pass\n\n\n'
                                                         'def f():\n    raise UFOError, "bad"\n'})
        return {'returncode': 0}
    sessions = []
    result = ma.run_native(out, wolframscript='wolframscript', max_seconds=60, runner=runner, mg5='mg5_aMC',
                           process='u u~ > zp > u u~', mg5_runner=mg5_session(sessions))
    assert result['passed'] and result['status'] == 'checked', result
    assert result['python_compatibility']['journal']  # Python-2 raise rewritten before the static check
    assert result['admission']['decision'] == 'admitted'
    assert sorted(s[-1].split()[:2][1] for s in sessions if s[-1].startswith('check')) == ['gauge', 'lorentz',
                                                                                           'permutation']
    admission = json.loads((out / 'admission.json').read_text())
    assert admission['kind'] == 'model-admission' and admission['ufo'] == result['ufo']
    assert {r['id']: r['status'] for r in admission['checks']}['hermiticity-feynrules'] == 'pass'
    card = (out / 'model-card.md').read_text()
    assert 'generated_contract_checked' in card and 'waived-goldstone-mixing' in card
    assert 'Model admission: admitted' in card
    assert json.loads((out / 'model-card.json').read_text())['native']['ufo_check_passed'] is True


def mg5_session(seen, failing=()):
    def run(cmd):
        script = Path(cmd[-1]).read_text().splitlines()
        seen.append(script)
        kind = script[-1].split()[1] if script[-1].startswith('check') else None
        out = ('Summary: 0/1 passed, 1/1 failed\n' if kind in failing else 'Summary: 1/1 passed, 0/1 failed\n')
        return types.SimpleNamespace(stdout='Total: 1 processes with 2 diagrams\n' + out, stderr='', returncode=0)
    return run


def native_run(out, native, ufo_overrides=None):
    def runner(command, native_dir, limits):
        (out / 'native-checks.json').write_text(json.dumps(native))
        write_ufo(out / 'ufo', **(ufo_overrides or {}))
        return {'returncode': 0}
    return runner


def completed_native():
    return {'status': 'completed', 'new_vertex_count': 4, 'vertex_messages': [], 'ufo_messages': [],
            'ufo_written': True, 'gauge_checks': gauge_record()}


def test_admission_is_a_postcondition_without_mg5_the_model_is_not_checked(tmp_path):
    out = tmp_path / 'out'
    ma.author(ufo_spec(), out, feynrules=fake_feynrules(tmp_path))
    result = ma.run_native(out, runner=native_run(out, completed_native()))
    assert not result['passed'] and result['status'] == 'admission_incomplete'
    assert {'mg5-check-gauge', 'mg5-check-lorentz', 'mg5-check-permutation'} <= set(result['admission']['not_evaluated'])


def test_admission_refuses_a_failing_mg5_check(tmp_path):
    out = tmp_path / 'out'
    ma.author(ufo_spec(), out, feynrules=fake_feynrules(tmp_path))
    result = ma.run_native(out, runner=native_run(out, completed_native()), mg5='mg5_aMC', process='u u~ > zp',
                           mg5_runner=mg5_session([], failing=('lorentz',)))
    assert not result['passed'] and result['status'] == 'failed'
    assert result['admission']['decision'] == 'refused'
    assert result['admission']['refusals'][0].startswith('mg5-check-lorentz')


def test_admission_refuses_a_charge_violating_vertex(tmp_path):
    out = tmp_path / 'out'
    ma.author(ufo_spec(), out, feynrules=fake_feynrules(tmp_path))
    bad = UFO_FILES['vertices.py'] + ("V_2 = Vertex(name='V_2', particles=[P.u, P.u, P.Zp], color=['1'], "
                                      "lorentz=[L.FFV1], couplings={(0,0):C.GC_2})\n")
    result = ma.run_native(out, runner=native_run(out, completed_native(), {'vertices.py': bad}), mg5='mg5_aMC',
                           process='u u~ > zp', mg5_runner=mg5_session([]))
    assert result['admission']['decision'] == 'refused' and not result['passed']
    assert any('V_2 charge sums to 4/3' in r for r in result['admission']['refusals'])


def test_run_native_fails_on_feynrules_messages(tmp_path):
    spec = ufo_spec()
    out = tmp_path / 'out'
    ma.author(spec, out, feynrules=fake_feynrules(tmp_path))
    native = {'status': 'completed', 'new_vertex_count': 4, 'vertex_messages': ['HoldForm[QN::NonConserv]'],
              'ufo_messages': [], 'ufo_written': True, 'gauge_checks': gauge_record()}

    def runner(command, native_dir, limits):
        (out / 'native-checks.json').write_text(json.dumps(native))
        write_ufo(out / 'ufo')
        return {'returncode': 0}
    result = ma.run_native(out, runner=runner)
    assert not result['passed'] and 'QN::NonConserv' in result['gauge_checks']['failures'][-1]


def test_run_native_refuses_changed_sources(tmp_path):
    spec = zprime()
    out = tmp_path / 'out'
    ma.author(spec, out, feynrules=fake_feynrules(tmp_path))
    (out / f'model/{spec["name"]}.fr').write_text('changed')
    with pytest.raises(ValueError, match='changed after authoring'):
        ma.run_native(out, runner=lambda *a: pytest.fail('ran'))


# ------------------------------------------------------- interference stages

def test_interference_stage_lines_and_closure():
    stages = ma.interference_processes(final='e+ e-', order_in_amplitude=2, model='NeutralVector')
    lines = {s['id']: s['mg5_process'] for s in stages['stages']}
    assert lines == {'sm': 'p p > e+ e- NP^2==0', 'interference': 'p p > e+ e- NP^2==2',
                     'pure': 'p p > e+ e- NP^2==4', 'full': 'p p > e+ e- NP^2<=4'}
    parts = {'sm': {'sigma_pb': 1.0, 'error_pb': 0.001}, 'interference': {'sigma_pb': -0.05, 'error_pb': 0.001},
             'pure': {'sigma_pb': 0.2, 'error_pb': 0.001}, 'full': {'sigma_pb': 1.151, 'error_pb': 0.001}}
    assert ma.interference_closure(parts, rel_tol=1e-3)['passed']
    parts['full']['sigma_pb'] = 1.3
    assert not ma.interference_closure(parts, rel_tol=1e-3)['passed']


def test_derivation_bridge_accepts_and_scripts_two_gauge_checks():
    from ravel.physics import model_derivation_bridge as bridge
    c = {'two_gauge_checks': {'new_terms_symbol': 'LNew'}, 'lagrangian_symbol': 'LFull'}
    snippet = ma.gauge_check_script(c['lagrangian_symbol'], c['two_gauge_checks']['new_terms_symbol'])
    assert 'Global`LNew' in snippet and 'Global`LFull' in snippet
    source = Path(bridge.__file__).read_text()
    assert "'two_gauge_checks'" in source and 'adjudicate_gauge_checks' in source


def test_science_modes_are_registered_with_descriptors(tmp_path, monkeypatch):
    from ravel.paths import package_data_path
    from ravel.workflow import science
    descriptors = json.loads(package_data_path('mode_descriptors.json').read_text())['modes']
    for mode in ('model-authoring', 'cross-section', 'simplified-spectrum', 'resonance-lineshape'):
        assert mode in science.MODES and mode in descriptors
        module = science.adapter({'mode': mode, 'task': {'request': 'r.json'}})
        assert all(callable(getattr(module, name)) for name in ('validate', 'inputs', 'run', 'main'))
    monkeypatch.setenv('FEYNRULES_ROOT', str(fake_feynrules(tmp_path)))
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'schema_version': 1, 'template': 'axion-like-particle', 'values': dict(
        mass_GeV=500., width_GeV=1., g_GG=1e-3, g_WW=0.0, g_BB=0.0)}))
    task = ma.validate({'request': str(request)})
    assert any(p.name == 'SM.fr' for p in ma.inputs(task, tmp_path))
    record = ma.run(task, tmp_path, tmp_path / 'output')
    assert record['status'] == 'authored' and record['native_run_performed'] is False
    card = (tmp_path / 'output/model-authoring/model-card.md').read_text()
    assert 'FeynRules has not been run for this card.' in card and 'gGGax' in card
