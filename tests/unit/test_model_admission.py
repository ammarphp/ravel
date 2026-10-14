"""Model admission: vertex quantum numbers, conjugate vertices, FeynRules Hermiticity, MG5 checks.

Synthetic UFO trees only; MadGraph is replaced by a recorded-output runner.
"""
import json
import types
from pathlib import Path

import pytest

from ravel.physics import model_admission as adm

PARTICLES = (
    "from object_library import Particle\nimport parameters as Param\n"
    "e__minus__ = Particle(pdg_code=11, name='e-', antiname='e+', spin=2, color=1, mass=Param.ZERO, width=Param.ZERO,"
    " charge=-1, LeptonNumber=1, GhostNumber=0)\n"
    "e__plus__ = e__minus__.anti()\n"
    "a = Particle(pdg_code=22, name='a', antiname='a', spin=3, color=1, mass=Param.ZERO, width=Param.ZERO, charge=0,"
    " LeptonNumber=0, GhostNumber=0)\n"
    "S1 = Particle(pdg_code=9000005, name='s1', antiname='s1~', spin=1, color=3, mass=Param.MS1, width=Param.WS1,"
    " charge=-2/3, LeptonNumber=1, GhostNumber=0)\n"
    "S1__tilde__ = S1.anti()\n"
    "d = Particle(pdg_code=1, name='d', antiname='d~', spin=2, color=3, mass=Param.ZERO, width=Param.ZERO,"
    " charge=-1/3, LeptonNumber=0, GhostNumber=0)\n"
    "d__tilde__ = d.anti()\n"
    "ghA = Particle(pdg_code=9000001, name='ghA', antiname='ghA~', spin=-1, color=1, mass=Param.ZERO, width=Param.ZERO,"
    " charge=0, LeptonNumber=0, GhostNumber=1)\n"
    "ghA__tilde__ = ghA.anti()\n")

PARAMETERS = (
    "from object_library import Parameter\n"
    "ZERO = Parameter(name='ZERO', nature='internal', type='real', value='0.0', texname='0')\n"
    "MS1 = Parameter(name='MS1', nature='external', type='real', value=1000., texname='M', lhablock='MASS', lhacode=[9000005])\n"
    "WS1 = Parameter(name='WS1', nature='external', type='real', value=1., texname='W', lhablock='DECAY', lhacode=[9000005])\n"
    "lam = Parameter(name='lam', nature='external', type='real', value=0.1, texname='l', lhablock='NPCOUP', lhacode=[1])\n")

VERTEX_HEAD = "from object_library import Vertex\nimport particles as P\nimport couplings as C\nimport lorentz as L\n"


def vertex(name, *particles, lorentz='FFV1', coupling='GC_1'):
    return (f"{name} = Vertex(name='{name}', particles=[{', '.join('P.' + p for p in particles)}], color=['1'], "
            f"lorentz=[L.{lorentz}], couplings={{(0,0):C.{coupling}}})\n")


GOOD_VERTICES = (vertex('V_1', 'e__plus__', 'e__minus__', 'a')
                 + vertex('V_2', 'd__tilde__', 'e__minus__', 'S1__tilde__', lorentz='FFS1', coupling='GC_2')
                 + vertex('V_3', 'e__plus__', 'd', 'S1', lorentz='FFS1', coupling='GC_3'))

FILES = {
    '__init__.py': 'import particles\n',
    'object_library.py': 'class Particle: pass\n',
    'parameters.py': PARAMETERS,
    'particles.py': PARTICLES,
    'couplings.py': ("from object_library import Coupling\n"
                     "GC_1 = Coupling(name='GC_1', value='-(ee*complex(0,1))', order={'QED':1})\n"
                     "GC_2 = Coupling(name='GC_2', value='complex(0,1)*lam', order={'NP':1})\n"
                     "GC_3 = Coupling(name='GC_3', value='complex(0,1)*lam', order={'NP':1})\n"),
    'lorentz.py': ("from object_library import Lorentz\n"
                   "FFV1 = Lorentz(name='FFV1', spins=[2,2,3], structure='Gamma(3,2,1)')\n"
                   "FFS1 = Lorentz(name='FFS1', spins=[2,2,1], structure='Identity(2,1)')\n"),
    'vertices.py': VERTEX_HEAD + GOOD_VERTICES,
}


def ufo(root, **overrides):
    root.mkdir()
    for name, text in {**FILES, **overrides}.items():
        (root / name).write_text(text)
    return root


SUMMARY = 'Summary: 1/1 passed, 0/1 failed\n'


def mg5_runner(outputs, seen=None):
    """Answer each MadGraph session with the recorded output for the check it runs."""
    def run(cmd):
        script = Path(cmd[-1]).read_text().splitlines()
        if seen is not None:
            seen.append(script)
        kind = script[-1].split()[1]
        return types.SimpleNamespace(stdout=outputs.get(kind, SUMMARY), stderr='', returncode=0)
    return run


def test_particle_table_reads_anti_particles_with_negated_quantum_numbers(tmp_path):
    table = adm.particle_table(ufo(tmp_path / 'u'))
    assert table['e__plus__']['pdg'] == -11 and table['e__plus__']['name'] == 'e+'
    assert table['e__plus__']['quantum_numbers'] == {'charge': 1, 'LeptonNumber': -1, 'GhostNumber': 0}
    assert table['a']['self_conjugate'] and table['a']['anti'] == 'a'
    assert table['S1']['anti'] == 'S1__tilde__' and table['S1__tilde__']['anti'] == 'S1'


def test_conserving_hermitian_ufo_passes_static_checks(tmp_path):
    record = adm.static_admission(ufo(tmp_path / 'u'))
    assert record['decision'] == 'passed', record
    rows = {r['id']: r for r in record['checks']}
    assert rows['vertex-quantum-numbers']['status'] == 'pass'
    assert set(rows['vertex-quantum-numbers']['quantum_numbers']) == {'charge', 'LeptonNumber', 'GhostNumber'}
    assert rows['conjugate-vertices']['status'] == 'pass'


def test_goldstone_flag_is_not_an_additive_quantum_number(tmp_path):
    # MadGraph's own sm UFO marks Goldstones with GoldstoneBoson = True; a flag, not a charge.
    particles = PARTICLES + (
        "G0 = Particle(pdg_code=250, name='G0', antiname='G0', spin=1, color=1, mass=Param.ZERO, width=Param.ZERO,"
        " charge=0, GoldstoneBoson=True, LeptonNumber=0, GhostNumber=0)\n"
        "H = Particle(pdg_code=25, name='H', antiname='H', spin=1, color=1, mass=Param.ZERO, width=Param.ZERO,"
        " charge=0, LeptonNumber=0, GhostNumber=0)\n")
    vertices = VERTEX_HEAD + GOOD_VERTICES + vertex('V_7', 'G0', 'G0', 'H', lorentz='SSS1')
    record = adm.static_admission(ufo(tmp_path / 'u', **{'particles.py': particles, 'vertices.py': vertices}))
    rows = {r['id']: r for r in record['checks']}
    assert rows['vertex-quantum-numbers']['status'] == 'pass', rows['vertex-quantum-numbers']
    assert 'GoldstoneBoson' not in rows['vertex-quantum-numbers']['quantum_numbers']


def test_vertex_violating_charge_is_refused(tmp_path):
    bad = VERTEX_HEAD + GOOD_VERTICES + vertex('V_9', 'e__minus__', 'e__minus__', 'a')
    record = adm.admit(ufo(tmp_path / 'u', **{'vertices.py': bad}))
    assert record['decision'] == 'refused'
    assert 'vertex-quantum-numbers' not in record['not_evaluated']  # it was evaluated and failed
    row = next(r for r in record['checks'] if r['id'] == 'vertex-quantum-numbers')
    assert row['status'] == 'fail'
    assert {'vertex': 'V_9', 'quantum_number': 'charge', 'sum': '-2'} in row['violations']
    assert any('V_9' in reason for reason in record['refusals'])


def test_vertex_violating_a_declared_additive_quantum_number_is_refused(tmp_path):
    bad = VERTEX_HEAD + GOOD_VERTICES.replace("'e__minus__', 'S1__tilde__'", "'e__plus__', 'S1__tilde__'")
    bad = bad.replace("P.d__tilde__, P.e__minus__", "P.d__tilde__, P.e__plus__")
    record = adm.static_admission(ufo(tmp_path / 'u', **{'vertices.py': bad}))
    row = next(r for r in record['checks'] if r['id'] == 'vertex-quantum-numbers')
    assert row['status'] == 'fail'
    assert {v['quantum_number'] for v in row['violations'] if v['vertex'] == 'V_2'} == {'charge', 'LeptonNumber'}


def test_vertex_without_its_conjugate_is_refused_as_non_hermitian(tmp_path):
    missing_hc = VERTEX_HEAD + vertex('V_1', 'e__plus__', 'e__minus__', 'a') + vertex(
        'V_2', 'd__tilde__', 'e__minus__', 'S1__tilde__', lorentz='FFS1', coupling='GC_2')
    record = adm.admit(ufo(tmp_path / 'u', **{'vertices.py': missing_hc}))
    assert record['decision'] == 'refused'
    row = next(r for r in record['checks'] if r['id'] == 'conjugate-vertices')
    assert row['status'] == 'fail' and row['missing'][0]['vertex'] == 'V_2'
    assert row['missing'][0]['conjugate_particles'] == ['d', 'e+', 's1']


def test_ghost_vertices_are_outside_the_conjugate_vertex_check(tmp_path):
    ghosts = VERTEX_HEAD + GOOD_VERTICES + vertex('V_4', 'ghA__tilde__', 'ghA', 'a', lorentz='FFV1')
    row = next(r for r in adm.static_admission(ufo(tmp_path / 'u', **{'vertices.py': ghosts}))['checks']
               if r['id'] == 'conjugate-vertices')
    assert row['status'] == 'pass' and row['ghost_vertices_skipped'] == 1


def test_undeclared_vertex_particle_is_refused(tmp_path):
    bad = VERTEX_HEAD + GOOD_VERTICES + vertex('V_5', 'mu__plus__', 'e__minus__', 'a')
    record = adm.static_admission(ufo(tmp_path / 'u', **{'vertices.py': bad}))
    assert record['decision'] == 'refused'
    assert any('mu__plus__' in reason for reason in record['refusals'])


def test_python2_ufo_is_refused_before_vertex_checks(tmp_path):
    record = adm.admit(ufo(tmp_path / 'u', **{'function_library.py': 'def f():\n    raise UFOError, "x"\n'}))
    assert record['decision'] == 'refused'
    rows = {r['id']: r for r in record['checks']}
    assert rows['ufo-static']['status'] == 'fail'
    assert rows['vertex-quantum-numbers']['status'] == 'not_evaluated'


def gauge_checks(hermitian=True):
    row = lambda holds=True: {'holds': holds, 'message_free': True, 'returned': '{}', 'printed': ''}
    gauge = lambda: {name: row(hermitian if name == 'CheckHermiticity' else True)
                     for name in ('CheckHermiticity', 'CheckDiagonalQuadraticTerms', 'CheckDiagonalMassTerms',
                                  'CheckKineticTermNormalisation')}
    return {'feynman': gauge(), 'unitary': gauge(), 'goldstones': []}


def test_feynrules_non_hermitian_verdict_is_refused(tmp_path):
    record = adm.admit(ufo(tmp_path / 'u'), native={'gauge_checks': gauge_checks(hermitian=False)})
    rows = {r['id']: r for r in record['checks']}
    assert rows['hermiticity-feynrules']['status'] == 'fail' and record['decision'] == 'refused'
    record = adm.admit(ufo(tmp_path / 'v'), native={'physical_checks': {'hermiticity': {
        'requested': True, 'message_free': True, 'returned_list': True, 'vertex_count': 2, 'expression': '{...}'}}})
    assert {r['id']: r for r in record['checks']}['hermiticity-feynrules']['status'] == 'fail'


def test_feynrules_hermiticity_absent_is_recorded_not_assumed(tmp_path):
    rows = {r['id']: r for r in adm.admit(ufo(tmp_path / 'u'))['checks']}
    assert rows['hermiticity-feynrules']['status'] == 'not_evaluated'
    assert rows['spec-charge-census']['status'] == 'not_evaluated'


def test_spec_hypercharge_census_feeds_admission():
    from ravel.physics import model_authoring as ma
    spec = ma.instantiate('scalar-leptoquark', dict(
        mass_GeV=1500., width_GeV=10., quark='uq', lepton='l', fermion_number=2, charge='-1/3',
        coupling_L=[[0.0] * 3 for _ in range(3)], coupling_R=[[0.0, 0.5, 0.0], [0.0] * 3, [0.0] * 3]))
    assert adm.hypercharge_check(spec)['status'] == 'pass'
    spec['fields'][0]['hypercharge'] = '2/3'
    row = adm.hypercharge_check(spec)
    assert row['status'] == 'fail'
    assert row['violations'] == [{'term': 'LQs-R', 'problems': ['electric charge sums to -1']}]


def test_all_three_mg5_checks_pass_and_admit(tmp_path):
    seen = []
    record = adm.admit(ufo(tmp_path / 'u'), mg5='mg5_aMC', process='e+ e- > a > e+ e-', workdir=tmp_path / 'w',
                       mg5_runner=mg5_runner({}, seen), native={'gauge_checks': gauge_checks()})
    assert record['decision'] == 'admitted', record['refusals'] + record['not_evaluated']
    assert sorted(s[-1].split()[1] for s in seen) == ['gauge', 'lorentz', 'permutation']
    assert all(s[-1].endswith('e+ e- > a > e+ e-') for s in seen)
    rows = {r['id']: r for r in record['checks']}
    assert rows['mg5-check-gauge']['passed_count'] == 1 and rows['ward-identity']['status'] == 'not_evaluated'
    assert all(r['cannot_detect'] for r in record['checks'])


@pytest.mark.parametrize('kind', ['gauge', 'lorentz', 'permutation'])
def test_a_failing_mg5_check_refuses(tmp_path, kind):
    failing = {kind: 'Summary: 0/1 passed, 1/1 failed\nFailed processes: e+ e- > e+ e-\n'}
    record = adm.admit(ufo(tmp_path / 'u'), mg5='mg5_aMC', process='e+ e- > e+ e-', workdir=tmp_path / 'w',
                       mg5_runner=mg5_runner(failing))
    assert record['decision'] == 'refused'
    assert {r['id']: r for r in record['checks']}[f'mg5-check-{kind}']['status'] == 'fail'


def test_mg5_check_without_a_verdict_is_not_a_pass(tmp_path):
    record = adm.admit(ufo(tmp_path / 'u'), mg5='mg5_aMC', process='e+ e- > e+ e-', workdir=tmp_path / 'w',
                       mg5_runner=mg5_runner({'lorentz': 'Command "check lorentz" interrupted\n'}),
                       native={'gauge_checks': gauge_checks()})
    assert record['decision'] == 'incomplete'
    assert {r['id']: r for r in record['checks']}['mg5-check-lorentz']['status'] == 'error'


def test_without_mg5_admission_is_incomplete_not_admitted(tmp_path):
    record = adm.admit(ufo(tmp_path / 'u'), native={'gauge_checks': gauge_checks()})
    assert record['decision'] == 'incomplete'
    assert set(record['not_evaluated']) >= {'mg5-check-gauge', 'mg5-check-lorentz', 'mg5-check-permutation'}


def test_mg5_process_line_is_one_line(tmp_path):
    with pytest.raises(ValueError):
        adm.admit(ufo(tmp_path / 'u'), mg5='mg5_aMC', process='e+ e- > e+ e-\nshell rm -rf x', workdir=tmp_path / 'w')


def test_record_shape_and_digest_follow_the_conventions(tmp_path):
    root = ufo(tmp_path / 'u')
    record = adm.admit(root)
    assert record['schema_version'] == 1 and record['kind'] == 'model-admission'
    assert record['ufo_digest'] == adm.tree_digest(root) and len(record['ufo_digest']) == 64
    json.dumps(record)


def test_cli_admit_writes_record_and_exit_code(tmp_path, capsys):
    from ravel.physics import model_authoring as ma
    root = ufo(tmp_path / 'u')
    out = tmp_path / 'admission.json'
    assert ma.main(['admit', '--ufo', str(root), '--out', str(out)]) == 1  # no MG5 checks: incomplete
    assert json.loads(out.read_text())['decision'] == 'incomplete'
    capsys.readouterr()
    bad = ufo(tmp_path / 'b', **{'vertices.py': VERTEX_HEAD + vertex('V_9', 'e__minus__', 'e__minus__', 'a')})
    assert ma.main(['admit', '--ufo', str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)['decision'] == 'refused'
