"""Theory chain: model source -> UFO -> amplitudes -> loops -> widths and branching ratios.

Synthetic requests, synthetic UFO trees and doctor reports only. Every stage tool is a mock runner;
MadGraph is a recorded-output runner. Nothing native starts: subprocess is patched to fail.
"""
import json
import subprocess
import types
from pathlib import Path

import pytest

from ravel.validation import validate_request_plan as rp
from ravel.workflow import theory_chain as tc

TEMPLATE_VALUES = {'model_name': 'SyntheticVector', 'name': 'Vx', 'pdg': 9000101, 'mass_GeV': 1800.0, 'width_GeV': 20.0, 'block': 'VXCOUP',
                   'gV_u': 0.1, 'gA_u': 0.0, 'gV_d': 0.1, 'gA_d': 0.0, 'gV_l': 0.05, 'gA_l': 0.0, 'gL_v': 0.0}


def request(**extra):
    base = {'id': 'synthetic-vector', 'model': {'route': 'feynrules-template', 'template': 'neutral-vector',
                                                 'values': TEMPLATE_VALUES},
            'process': 'p p > vx > e+ e-',
            'amplitudes': {'process': 'u u~ > e+ e-', 'loops': 1},
            'loops': {'integrals': 'one-loop scalar triangles and boxes of the amplitude'},
            'widths': {'particle': 'vx', 'order': 'tree', 'channels': ['u u~', 'd d~', 'e+ e-']}}
    base.update(extra)
    return base


def doctor(missing=(), absent_groups=()):
    """A ravel-doctor-report: every theory check ready unless named in ``missing`` (check id -> fix)."""
    groups = []
    for gid, checks in tc.MANIFEST_CHECKS.items():
        if gid in absent_groups:
            continue
        rows = [{'id': c, 'status': 'missing' if c in dict(missing) else 'ready',
                 **({'fix': dict(missing)[c]} if c in dict(missing) else {})} for c in checks]
        status = 'missing' if any(r['status'] == 'missing' for r in rows) else 'ready'
        groups.append({'group': gid, 'status': status, 'checks': rows})
    return {'schema_version': 1, 'kind': 'ravel-doctor-report', 'groups': groups,
            'refusal_classes': [{'id': 'SP-03', 'title': 'Loop decays of a generated spectrum',
                                 'refused': 'Decay widths need loop functions from Collier or LoopTools.',
                                 'why': 'no installer entry builds them',
                                 'would_make_it_possible': 'An installer entry that builds Collier and a doctor check.'}]}


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f'a native process was started: {a!r}')
    monkeypatch.setattr(subprocess, 'run', refuse)
    monkeypatch.setattr(subprocess, 'Popen', refuse)


# ------------------------------------------------------------------ a synthetic UFO
PARTICLES = (
    "from object_library import Particle\nimport parameters as Param\n"
    "e__minus__ = Particle(pdg_code=11, name='e-', antiname='e+', spin=2, color=1, mass=Param.ZERO, width=Param.ZERO,"
    " charge=-1, LeptonNumber=1, GhostNumber=0)\n"
    "e__plus__ = e__minus__.anti()\n"
    "u = Particle(pdg_code=2, name='u', antiname='u~', spin=2, color=3, mass=Param.ZERO, width=Param.ZERO,"
    " charge=2/3, LeptonNumber=0, GhostNumber=0)\n"
    "u__tilde__ = u.anti()\n"
    "d = Particle(pdg_code=1, name='d', antiname='d~', spin=2, color=3, mass=Param.ZERO, width=Param.ZERO,"
    " charge=-1/3, LeptonNumber=0, GhostNumber=0)\n"
    "d__tilde__ = d.anti()\n"
    "vx = Particle(pdg_code=9000101, name='vx', antiname='vx', spin=3, color=1, mass=Param.MVX, width=Param.WVX,"
    " charge=0, LeptonNumber=0, GhostNumber=0)\n")
PARAMETERS = (
    "from object_library import Parameter\n"
    "ZERO = Parameter(name='ZERO', nature='internal', type='real', value='0.0', texname='0')\n"
    "MVX = Parameter(name='MVX', nature='external', type='real', value=1800., texname='M', lhablock='MASS', lhacode=[9000101])\n"
    "WVX = Parameter(name='WVX', nature='external', type='real', value=20., texname='W', lhablock='DECAY', lhacode=[9000101])\n"
    + ''.join(f"{s} = Parameter(name='{s}', nature='external', type='real', value=0.1, texname='g', lhablock='VXCOUP',"
              f" lhacode=[{i + 1}])\n" for i, s in enumerate(('gVuVx', 'gAuVx', 'gVdVx', 'gAdVx', 'gVlVx', 'gAlVx', 'gLvVx'))))


def vertex(name, *particles, coupling='GC_1'):
    return (f"{name} = Vertex(name='{name}', particles=[{', '.join('P.' + p for p in particles)}], color=['1'], "
            f"lorentz=[L.FFV1], couplings={{(0,0):C.{coupling}}})\n")


VERTICES = ("from object_library import Vertex\nimport particles as P\nimport couplings as C\nimport lorentz as L\n"
            + vertex('V_1', 'e__plus__', 'e__minus__', 'vx') + vertex('V_2', 'u__tilde__', 'u', 'vx', coupling='GC_2')
            + vertex('V_3', 'd__tilde__', 'd', 'vx', coupling='GC_3'))
UFO_FILES = {'__init__.py': 'import particles\n', 'object_library.py': 'class Particle: pass\n',
             'parameters.py': PARAMETERS, 'particles.py': PARTICLES,
             'couplings.py': ("from object_library import Coupling\n"
                              "GC_1 = Coupling(name='GC_1', value='complex(0,1)*gVlVx', order={'NP':1})\n"
                              "GC_2 = Coupling(name='GC_2', value='complex(0,1)*gVuVx', order={'NP':1})\n"
                              "GC_3 = Coupling(name='GC_3', value='complex(0,1)*gVdVx', order={'NP':1})\n"),
             'lorentz.py': ("from object_library import Lorentz\n"
                            "FFV1 = Lorentz(name='FFV1', spins=[2,2,3], structure='Gamma(3,2,1)')\n"),
             'vertices.py': VERTICES}
# A charge-violating vertex: e+ u vx sums to +5/3.
BAD_VERTICES = VERTICES + vertex('V_4', 'e__plus__', 'u', 'vx')


def write_ufo(root, vertices=VERTICES):
    root.mkdir(parents=True)
    for name, text in {**UFO_FILES, 'vertices.py': vertices}.items():
        (root / name).write_text(text)
    return root


def mg5_runner(seen):
    def run(cmd):
        script = Path(cmd[-1]).read_text().splitlines()
        seen.append(script[-1])
        return types.SimpleNamespace(stdout='Summary: 1/1 passed, 0/1 failed\n', stderr='', returncode=0)
    return run


def runners(calls, vertices=VERTICES, lint_passed=True):
    """Mock stage runners: each records its call and returns synthetic outputs."""
    def model_source(stage, inputs, workdir):
        calls.append(stage['stage'])
        return {'spec': inputs['spec'], 'lint_passed': lint_passed, 'census_passed': True}

    def ufo(stage, inputs, workdir):
        calls.append(stage['stage'])
        return {'ufo': str(write_ufo(Path(workdir) / 'ufo', vertices)),
                'native_checks': {'gauge_checks': {
                    name: {'CheckHermiticity': {'holds': True, 'message_free': True}} for name in ('feynman', 'unitary')}}}

    def amplitudes(stage, inputs, workdir):
        calls.append(stage['stage'])
        return {'amplitude': 'synthetic amplitude', 'checks': {'diagram-census-complete': True}}

    def loops(stage, inputs, workdir):
        calls.append(stage['stage'])
        return {'values': [1.0], 'checks': {'known-answer-integrals': True}}

    def widths(stage, inputs, workdir):
        calls.append(stage['stage'])
        return {'widths': {'u u~': 0.6, 'd d~': 0.8, 'e+ e-': 0.2}}
    return {'model-source': model_source, 'ufo': ufo, 'amplitudes': amplitudes, 'loops': loops, 'widths': widths}


# ------------------------------------------------------------------ acceptance 1: the chain in order
def test_synthetic_request_drafts_every_stage_in_order_with_operation_and_admission_check():
    chain = tc.draft(request(), doctor=doctor())
    assert [s['stage'] for s in chain['stages']] == ['model-source', 'ufo', 'amplitudes', 'loops', 'widths']
    ops = {s['stage']: s['operation'] for s in chain['stages']}
    assert ops == {'model-source': 'model-authoring', 'ufo': 'model-derivation-bridge',
                   'amplitudes': 'feynarts-amplitude', 'loops': 'finite-integrals', 'widths': 'resonance-width'}
    for stage in chain['stages']:
        assert stage['admission_check']['checks'], stage['stage']
        assert stage['signature']['sha256'] and stage['signature']['source'] in ('registry', 'seam')
        assert stage['status'] == 'ready'
    assert {s['stage']: s['depends_on'] for s in chain['stages']} == {
        'model-source': None, 'ufo': 'model-source', 'amplitudes': 'ufo', 'loops': 'amplitudes', 'widths': 'ufo'}
    ufo = chain['stages'][1]
    assert ufo['admission_check']['role'] == 'postcondition'
    assert ufo['admission_check']['operation'] == 'model-admission'
    assert set(ufo['admission_check']['checks']) >= {'ufo-static', 'vertex-quantum-numbers', 'conjugate-vertices',
                                                       'mg5-check-gauge', 'mg5-check-lorentz', 'mg5-check-permutation'}
    for later in chain['stages'][2:]:
        assert 'model-admitted' in later['admission_check']['preconditions']


def test_supplied_ufo_route_starts_at_admission_and_sarah_route_uses_model_sources():
    chain = tc.draft(request(model={'route': 'supplied-ufo', 'ufo': 'model/ufo'}), doctor=doctor())
    first = chain['stages'][0]
    assert first['stage'] == 'model-source' and first['operation'] is None and first['status'] == 'supplied'
    assert chain['stages'][1]['operation'] is None and chain['stages'][1]['admission_check']['operation'] == 'model-admission'
    sarah = tc.draft(request(model={'route': 'sarah', 'sarah': {}}), doctor=doctor())
    assert sarah['stages'][0]['operation'] == 'model-sources' and sarah['stages'][1]['operation'] == 'model-sources'
    # Missing SARAH inputs hold the stage; they never refuse it.
    assert sarah['stages'][0]['status'] == 'held' and sarah['stages'][0]['hold']['would_make_possible']


def test_requested_stages_only_and_general_widths_route_to_diagrammatica():
    chain = tc.draft(request(amplitudes=None, loops=None, widths={'particle': 'vx', 'order': 'tree'}), doctor=doctor())
    assert [s['stage'] for s in chain['stages']] == ['model-source', 'ufo', 'widths']
    assert chain['stages'][-1]['operation'] == 'diagrammatica-code'
    assert chain['stages'][-1]['depends_on'] == 'ufo'


# ------------------------------------------------------------------ seam rows
def test_seam_rows_are_valid_signatures_and_the_registry_wins():
    document = json.loads(tc.SEAM_PATH.read_text())
    assert rp._schema_errors(document, rp.SIGNATURES_SCHEMA, 'seam') == []
    registry = rp.registry()
    for name in document['operations']:
        assert name in registry, f'{name} is not a registered mode'
    signed = {name: row for name, row in registry.items() if row}
    for name in document['operations']:
        if name in signed:
            assert tc.signature(name)['source'] == 'registry'
        else:
            assert tc.signature(name)['source'] == 'seam'
    assert tc.signature('model-authoring')['source'] == 'registry'


def test_seam_rows_cover_every_unsigned_chain_operation():
    registry = rp.registry()
    for operation in tc.CHAIN_OPERATIONS:
        assert registry.get(operation) or operation in tc.seam_rows(), operation


# ------------------------------------------------------------------ acceptance 2: holds, not refusals
def test_absent_tools_hold_their_stages_with_would_make_possible():
    report = doctor(missing={'feyncalc': 'run the installer for the wolfram group',
                             'integral-python': 'install the integrals environment'})
    chain = tc.draft(request(), doctor=report)
    by = {s['stage']: s for s in chain['stages']}
    for name in ('amplitudes', 'loops'):
        assert by[name]['status'] == 'held'
        assert by[name]['hold']['held_by'] == 'tool-absent'
        assert by[name]['hold']['would_make_possible']
        assert by[name]['hold']['missing']
    assert 'feyncalc' in [m['check'] for m in by['amplitudes']['hold']['missing']]
    assert 'install the integrals environment' in by['loops']['hold']['would_make_possible']
    assert by['model-source']['status'] == 'ready' and by['widths']['status'] == 'ready'
    assert all(s['status'] not in ('refused', 'failed', 'error') for s in chain['stages'])


def test_without_a_doctor_report_native_stages_hold_as_unverified():
    chain = tc.draft(request())
    by = {s['stage']: s for s in chain['stages']}
    for name in ('model-source', 'ufo', 'amplitudes', 'loops'):
        assert by[name]['status'] == 'held' and by[name]['hold']['held_by'] == 'tool-unverified'
        assert 'ravel doctor --group' in by[name]['hold']['would_make_possible']
    assert by['widths']['status'] == 'ready'  # the analytic tree route needs only the host Python


def test_loop_widths_hold_under_the_loop_decay_refusal_class():
    chain = tc.draft(request(widths={'particle': 'vx', 'order': 'loop'}), doctor=doctor())
    widths = chain['stages'][-1]
    assert widths['status'] == 'held' and widths['hold']['held_by'] == 'refusal-class:SP-03'
    assert widths['hold']['would_make_possible'] == 'An installer entry that builds Collier and a doctor check.'
    fallback = tc.draft(request(widths={'particle': 'vx', 'order': 'loop'}), doctor={'groups': doctor()['groups']})
    assert 'Collier' in fallback['stages'][-1]['hold']['would_make_possible']


def test_mg5_absent_keeps_admission_reachable_but_names_what_completes_it():
    chain = tc.draft(request(), doctor=doctor(absent_groups=('madgraph',)))
    ufo = chain['stages'][1]
    assert ufo['status'] == 'ready'
    pending = ufo['admission_check']['pending']
    assert pending and 'madgraph' in pending['would_make_possible']


def test_held_stage_holds_its_dependants_with_the_upstream_reason(tmp_path):
    chain = tc.draft(request(), doctor=doctor(missing={'feyncalc': 'install FeynCalc'}))
    calls = []
    result = tc.run(chain, tmp_path / 'run', runners=runners(calls), mg5='mg5_aMC', mg5_runner=mg5_runner([]))
    by = {s['stage']: s for s in result['stages']}
    assert by['amplitudes']['status'] == 'held'
    assert by['loops']['status'] == 'held' and by['loops']['hold']['held_by'] == 'upstream:amplitudes'
    assert 'install FeynCalc' in by['loops']['hold']['would_make_possible']
    assert 'amplitudes' not in calls and 'loops' not in calls
    assert by['widths']['status'] == 'done'  # widths depend on the admitted model, not on the amplitudes


# ------------------------------------------------------------------ acceptance 3: admission postcondition
def test_admission_runs_as_the_postcondition_of_model_authoring_on_the_chain(tmp_path):
    chain = tc.draft(request(), doctor=doctor())
    calls, seen = [], []
    result = tc.run(chain, tmp_path / 'run', runners=runners(calls), mg5='mg5_aMC', mg5_runner=mg5_runner(seen))
    assert calls == ['model-source', 'ufo', 'amplitudes', 'loops', 'widths']
    ufo = next(s for s in result['stages'] if s['stage'] == 'ufo')
    admission = ufo['admission']
    assert admission['decision'] == 'admitted', admission
    assert Path(admission['record']['path']).is_file()
    assert sorted(line.split()[1] for line in seen) == ['gauge', 'lorentz', 'permutation']
    assert all(line.endswith('p p > vx > e+ e-') for line in seen)
    assert result['events'].index('ufo:admission:admitted') < result['events'].index('amplitudes:start')
    widths = next(s for s in result['stages'] if s['stage'] == 'widths')
    rows = {r['id']: r for r in widths['postcondition']}
    assert rows['br-closure']['status'] == 'pass'
    assert rows['width-witness']['status'] == 'not_evaluated'
    assert widths['outputs']['branching_ratios']['d d~'] == pytest.approx(0.5)
    assert result['status'] == 'complete'


def test_refused_admission_stops_every_downstream_stage(tmp_path):
    chain = tc.draft(request(), doctor=doctor())
    calls = []
    result = tc.run(chain, tmp_path / 'run', runners=runners(calls, vertices=BAD_VERTICES), mg5='mg5_aMC',
                    mg5_runner=mg5_runner([]))
    ufo = next(s for s in result['stages'] if s['stage'] == 'ufo')
    assert ufo['status'] == 'admission_refused' and ufo['admission']['refusals']
    assert calls == ['model-source', 'ufo']
    by = {s['stage']: s for s in result['stages']}
    expected = {'amplitudes': 'upstream:ufo', 'loops': 'upstream:amplitudes', 'widths': 'upstream:ufo'}
    for name, held_by in expected.items():
        assert by[name]['status'] == 'held' and by[name]['hold']['held_by'] == held_by
        assert 'model admission' in by[name]['hold']['would_make_possible']
        assert 'vertex-quantum-numbers' in by[name]['hold']['would_make_possible']


def test_incomplete_admission_without_madgraph_holds_downstream(tmp_path):
    chain = tc.draft(request(), doctor=doctor(absent_groups=('madgraph',)))
    calls = []
    result = tc.run(chain, tmp_path / 'run', runners=runners(calls))
    ufo = next(s for s in result['stages'] if s['stage'] == 'ufo')
    assert ufo['status'] == 'admission_incomplete' and ufo['admission']['decision'] == 'incomplete'
    assert ufo['hold']['would_make_possible']
    assert calls == ['model-source', 'ufo']


def test_failed_authoring_lint_never_reaches_the_ufo(tmp_path):
    chain = tc.draft(request(), doctor=doctor())
    calls = []
    result = tc.run(chain, tmp_path / 'run', runners=runners(calls, lint_passed=False), mg5='mg5_aMC',
                    mg5_runner=mg5_runner([]))
    assert calls == ['model-source']
    assert result['stages'][0]['status'] == 'postcondition_failed'
    assert result['stages'][1]['hold']['held_by'] == 'upstream:model-source'


# ------------------------------------------------------------------ acceptance 4: native queue, nothing native runs
def test_without_runners_every_ready_native_stage_is_queued_not_run(tmp_path):
    chain = tc.draft(request(), doctor=doctor())
    result = tc.run(chain, tmp_path / 'run')
    by = {s['stage']: s for s in result['stages']}
    request_row = by['model-source']['native_request']
    assert by['model-source']['status'] == 'queued' and request_row['commands'][0]['argv'][:3] == ['ravel', 'model', 'author']
    assert by['ufo']['status'] == 'held' and by['ufo']['hold']['held_by'] == 'upstream:model-source'
    for stage in result['stages']:
        assert stage['status'] in ('queued', 'held')
    assert result['native_queue'] and all(r['runs_now'] is False for r in result['native_queue'])


def test_completion_record_carries_n3_n4a_n4b_with_exact_commands(tmp_path):
    chain = tc.draft(request(), doctor=doctor())
    result = tc.run(chain, tmp_path / 'run')
    record = tc.completion_record(chain, result)
    ids = [r['id'] for r in record['native_queue']]
    assert ids[:3] == ['N3', 'N4a', 'N4b']
    n3, n4a, n4b = record['native_queue'][:3]
    steps = {c['step']: c['argv'] for c in n3['commands']}
    assert steps['doctor'][-5:] == ['ravel', 'doctor', '--group', 'wolfram', '--json']
    assert steps['host-config-before'][:3] == ['shasum', '-a', '256'] and 'host-config-after' in steps
    assert 'AgentTools' in n3['never']
    plan = next(c['argv'] for c in n4a['commands'] if c['step'] == 'plan')
    assert plan[plan.index('--model-file') + 1] == 'SM.fr' and plan[plan.index('--lagrangian') + 1] == 'LSM'
    assert '--pinned-provider' not in plan
    plan_b = next(c['argv'] for c in n4b['commands'] if c['step'] == 'plan')
    assert '--pinned-provider' in plan_b and plan_b[plan_b.index('--ufo-python-compatibility') + 1] == \
        'feynrules-2.3.49-literal-UFOError-raise-v1'
    for row in (n4a, n4b):
        admit = next(c['argv'] for c in row['commands'] if c['step'] == 'admit')
        assert admit[admit.index('ravel'):admit.index('ravel') + 3] == ['ravel', 'model', 'admit']
        assert '--mg5' in admit and '--process' in admit
        assert [c['step'] for c in row['commands']] == ['worktree', 'plan', 'approve', 'run', 'admit']
        assert next(c for c in row['commands'] if c['step'] == 'approve')['by'] == 'root'
        assert row['expected_minutes'] and row['disk_mb'] and row['depends_on']
    assert n4a['source_commit'] != n4b['source_commit']
    assert all(r['runs_now'] is False for r in record['native_queue'])
    assert record['stages'] and record['kind'] == 'theory-chain-completion'
    json.dumps(record)


def test_bindings_resolve_command_variables_and_unresolved_ones_are_named():
    queue = tc.native_queue_requests({'RAVEL_REPO': '/repo', 'N_RUN_ROOT': '/runs'})
    n4a = queue[1]
    assert any('/runs/n4a-sm-derivation' in ' '.join(c['argv']) for c in n4a['commands'])
    assert 'FEYNRULES_ROOT' in n4a['unresolved']
    assert 'RAVEL_REPO' not in n4a['unresolved']


# ------------------------------------------------------------------ input checks and the R-10 firewall
def test_request_errors_are_typed():
    with pytest.raises(ValueError):
        tc.draft({'id': 'x'})
    with pytest.raises(ValueError):
        tc.draft(request(model={'route': 'unknown'}))
    with pytest.raises(ValueError):
        tc.draft(request(process='p p > vx\nlaunch'))


def test_chain_record_is_deterministic_and_carries_no_identity_fields():
    a = tc.draft(request(), doctor=doctor())
    b = tc.draft(request(), doctor=doctor())
    assert a == b and a['digest'] == b['digest']
    text = json.dumps(a).lower()
    for word in ('benchmark', 'challenge', 'arxiv'):
        assert word not in text
