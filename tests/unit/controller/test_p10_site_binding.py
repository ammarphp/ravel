"""Multi-jobscript site bindings, the launch capability channel and batch-site workflow commands.

Inert: no scheduler, sandbox or workflow manager runs. The confined launcher is only planned.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from ravel.controller.routes import study
from ravel.controller.routes.study import contracts, runtime, site
from ravel.workflow import wms_adopt, wms_policy

DATA = Path(study.__file__).resolve().parents[3] / 'data'
TOKEN = 'rwc1.run.launch.' + 'x' * 32


class Store:
    """Local binding-interface fake of the controller store."""
    def __init__(self, run_id='fictional', *, root=None):
        self.run_id = run_id
        self.root = Path(root or '.')
        self.rows = []

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        record_id = str(len(self.rows) + 1)
        self.rows.append({'id': record_id, 'kind': kind, 'record': deepcopy(record)})
        return record_id

    def read(self, kind, record_id):
        return next(deepcopy(row) for row in self.rows if row['kind'] == kind and row['id'] == record_id)

    def scan(self, kind):
        return [deepcopy(row) for row in self.rows if row['kind'] == kind]

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def checkpointer(self):
        raise NotImplementedError('no graph execution in this inert fake')


def reading():
    return {'deliverables': [{'id': 'quantity'}, {'id': 'new_sample'}], 'constraints': []}


def _adopt(store, root, artifact, value):
    relative = 'steps/' + artifact.replace(':', '/')
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    store.append('custody', {'artifact': artifact, 'destination': relative,
                             'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'accepted'})


def _prepared_context(root, monkeypatch):
    from ravel.workflow import science
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root=root / 'protected-store')
    spec = {'schema_version': 2, 'mode': 'fictional-study', 'max_seconds': 10,
            'max_attempts': 2, 'task': {'finite': True}}
    source = json.loads((DATA / 'controller/routes/study.json').read_text())
    prepared_plan = {'route': {'id': 'study.site'}, 'parameters': {}, 'steps': deepcopy(source['steps']),
                     'deliverables': deepcopy(reading()['deliverables']), 'open_obligations': []}
    context = {'store': store, 'run_dir': str(root), 'plan': prepared_plan, 'reading': reading(),
               'contract': {'task_mode': 'supplied_events'}}
    _adopt(store, root, study.SPEC_ARTIFACT, spec)
    child = root / 'children/study'

    def pin_file(name, value):
        path = child / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    ordinary = {'kind': 'science', 'child_rundir': 'children/study',
                'plan_sha256': pin_file(science.PLAN, {'mode': spec['mode'], 'max_seconds': 10}),
                'specification_sha256': pin_file(science.SPEC, spec)}
    _adopt(store, root, 'prepare-child:outputs/preparation.json',
           {'kind': 'ordinary-study-preparation', 'ordinary': ordinary})
    monkeypatch.setattr(study, 'mode_admission', lambda spec: {'operation': 'fictional-study',
        'role': 'calculation', 'signature': {'stages': [], 'produces': [{'kind': 'document'}]}})
    return context


def _scripts(root, count):
    pins = []
    for index in range(count):
        script = root / f'prepared-script-{index}'
        script.write_bytes(f'inert scheduler payload {index}\n'.encode())
        pins.append({'path': script.name, 'sha256': hashlib.sha256(script.read_bytes()).hexdigest()})
    return pins


def _scope(root, site_binding):
    return {'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity', 'new_sample'],
            'stages': [], 'child_rundir': 'children/study', 'site': site_binding}


def _operate(plan):
    return next(row for row in plan['steps'] if row['id'] == 'operate')


# ----------------------------------------------------------------- binding
def test_multi_jobscript_site_binds_exact_pins_and_detects_changed_bytes(tmp_path, monkeypatch):
    context = _prepared_context(tmp_path / 'multi', monkeypatch)
    root = Path(context['run_dir'])
    pins = _scripts(root, 3)
    wms_scope = {'workflow_dir': str(root), 'max_jobs': 3}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, _scope(root, {'jobscripts': pins, 'wms_scope': wms_scope}))
    context['plan'] = study.bind(context['plan'], context)
    operate = _operate(context['plan'])
    assert operate['parameters']['launch']['jobscripts'] == pins
    assert 'jobscript' not in operate['parameters']['launch']
    assert operate['parameters']['wms_scope'] == wms_scope
    assert study.gate('checkin1', context) == []
    assert not context['store'].scan('authority')
    (root / pins[1]['path']).write_bytes(b'changed prepared bytes\n')
    assert any(row['code'] == 'study_binding_invalid' for row in study.gate('checkin1', context))


@pytest.mark.parametrize('max_jobs', [2, 4, None, '3', 3.0])
def test_multi_jobscript_site_requires_max_jobs_equal_to_its_pin_count(tmp_path, monkeypatch, max_jobs):
    context = _prepared_context(tmp_path / 'count', monkeypatch)
    root = Path(context['run_dir'])
    pins = _scripts(root, 3)
    wms_scope = {'workflow_dir': str(root)} if max_jobs is None else {'workflow_dir': str(root), 'max_jobs': max_jobs}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, _scope(root, {'jobscripts': pins, 'wms_scope': wms_scope}))
    with pytest.raises(ValueError, match='max_jobs must equal its pinned jobscript count'):
        study.bind(context['plan'], context)
    # The same refusal reaches the gate when an adopted scope changes after a valid binding.
    context = _prepared_context(tmp_path / 'rebound', monkeypatch)
    root = Path(context['run_dir'])
    pins = _scripts(root, 3)
    _adopt(context['store'], root, study.SCOPE_ARTIFACT,
           _scope(root, {'jobscripts': pins, 'wms_scope': {'workflow_dir': str(root), 'max_jobs': 3}}))
    context['plan'] = study.bind(context['plan'], context)
    assert study.gate('checkin1', context) == []
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, _scope(root, {'jobscripts': pins, 'wms_scope': wms_scope}))
    assert any(row['code'] == 'study_binding_invalid' and 'max_jobs' in row['message']
               for row in study.gate('checkin1', context))
    assert not context['store'].scan('authority')


def test_multi_jobscript_site_refuses_duplicate_malformed_and_mixed_pins(tmp_path, monkeypatch):
    context = _prepared_context(tmp_path / 'refused', monkeypatch)
    root = Path(context['run_dir'])
    pins = _scripts(root, 2)
    twin = root / 'prepared-twin'
    twin.write_bytes((root / pins[0]['path']).read_bytes())
    cases = [
        ({'jobscripts': [pins[0], pins[0]]}, 'must be distinct'),
        ({'jobscripts': [pins[0], {'path': twin.name, 'sha256': pins[0]['sha256']}]}, 'must be distinct'),
        ({'jobscripts': []}, 'exact prepared jobscript pins'),
        ({'jobscripts': pins[0]}, 'exact prepared jobscript pins'),
        ({'jobscripts': [pins[0], {'path': pins[1]['path'], 'sha256': None}]}, 'exact prepared jobscript pins'),
        ({'jobscripts': [pins[0], {**pins[1], 'kind': 'script'}]}, 'exact prepared jobscript pins'),
        ({'jobscripts': pins, 'jobscript': pins[0]}, 'exact site scope'),
    ]
    for binding, message in cases:
        max_jobs = len(binding['jobscripts']) if type(binding['jobscripts']) is list else 1
        _adopt(context['store'], root, study.SCOPE_ARTIFACT, _scope(root, {
            **binding, 'wms_scope': {'workflow_dir': str(root), 'max_jobs': max_jobs}}))
        with pytest.raises(ValueError, match=message):
            study.bind(context['plan'], context)
    assert not context['store'].scan('authority')


def test_single_jobscript_site_binds_exactly_as_before(tmp_path, monkeypatch):
    context = _prepared_context(tmp_path / 'site', monkeypatch)
    root = Path(context['run_dir'])
    script = root / 'prepared-script'
    script.write_bytes(b'inert scheduler payload\n')
    pin = {'path': script.name, 'sha256': hashlib.sha256(script.read_bytes()).hexdigest()}
    scope = _scope(root, {'jobscript': pin, 'wms_scope': {'workflow_dir': str(root), 'max_jobs': 1}})
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, scope)
    context['plan'] = study.bind(context['plan'], context)
    operate = _operate(context['plan'])
    assert operate['parameters']['launch']['jobscript'] == pin
    assert 'jobscripts' not in operate['parameters']['launch']
    assert operate['parameters']['wms_scope'] == scope['site']['wms_scope']
    assert study.gate('checkin1', context) == []
    assert not context['store'].scan('authority')
    script.write_bytes(b'changed prepared bytes\n')
    assert any(row['code'] == 'study_binding_invalid' for row in study.gate('checkin1', context))
    (root / 'prepared-directory').mkdir()
    unpinned = deepcopy(scope)
    unpinned['site']['jobscript'] = {'path': 'prepared-directory', 'sha256': None}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, unpinned)
    assert any(row['code'] == 'study_binding_invalid' and 'jobscript pin' in row['message']
               for row in study.gate('checkin1', context))


# ----------------------------------------------------------------- dispatch pass-through
class Process:
    pid = None
    returncode = None

    def communicate(self, timeout):
        self.returncode = 0
        return '', ''


@pytest.fixture
def inert_dispatch(tmp_path, monkeypatch):
    from ravel.controller import authority, confine
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV, raising=False)
    launches = []
    capsule = {'argv': [sys.executable, '-m', runtime.ADAPTER, 'run'], 'env': {'PATH': '/usr/bin'},
               'reads': [], 'writes': [], 'limits': {'wall_seconds': 5}, 'backend': 'auto'}

    def preflight(store, step, context):
        return {'capsule': capsule, 'launch_sha256': contracts.digest(capsule),
                'output_root': str(tmp_path / store.run_id / 'outputs'), 'inventory': {'equal': True}}

    def popen(spec, **kwargs):
        launches.append(deepcopy(spec))
        return Process()
    monkeypatch.setattr(runtime, 'preflight', preflight)
    monkeypatch.setattr(authority, 'stop_state', lambda store: 'running')
    monkeypatch.setattr(confine, 'popen', popen)
    monkeypatch.setattr(confine, 'finish', lambda process: None, raising=False)

    def run(run_id):
        store = Store(run_id, root=tmp_path / run_id / 'store')
        step = {'id': 'operate', 'budget': {'wall_seconds': 5}}
        return store, runtime.dispatch(store, step, {'attempt': 1})
    return {'run': run, 'launches': launches, 'capsule': capsule}


def test_dispatch_outside_a_trusted_launch_passes_no_capability(inert_dispatch):
    store, outcome = inert_dispatch['run']('local')
    assert outcome['exit_status'] == 0
    assert inert_dispatch['launches'][0]['env'] == {'PATH': '/usr/bin'}
    assert not store.scan('study-operation-capability')


def test_dispatch_inside_a_trusted_launch_passes_the_capability_by_name_only(inert_dispatch):
    capsule = inert_dispatch['capsule']
    binding = Store('trusted')  # the same controller run as the dispatching store
    scope = {'jobscripts': [], 'capability': {'workflow_dir': '/fictional', 'max_jobs': 1}}
    with site.trusted_launch(binding, 'operate', TOKEN, scope):
        store, outcome = inert_dispatch['run']('trusted')
    assert outcome['exit_status'] == 0
    launched = inert_dispatch['launches'][0]
    assert launched['env'] == {'PATH': '/usr/bin', wms_policy.CAPABILITY_ENV: TOKEN}
    assert {k: v for k, v in launched.items() if k != 'env'} == {k: v for k, v in capsule.items() if k != 'env'}
    assert capsule['env'] == {'PATH': '/usr/bin'}, 'the admitted capsule is never mutated'
    token_free = contracts.digest(capsule)
    assert [row['record'] for row in store.scan('study-operation-capability')] == [
        {'key': 'operate:1', 'launch_sha256': token_free, 'passed': [wms_policy.CAPABILITY_ENV]}]
    assert {row['record']['launch_sha256'] for row in store.scan('study-operation')} == {token_free}
    assert outcome['launch_sha256'] == token_free
    assert TOKEN not in json.dumps(store.rows), 'the store records variable names, never the bearer token'


def test_dispatch_inside_another_runs_launch_passes_no_capability(inert_dispatch):
    other = Store('another-run')
    with site.trusted_launch(other, 'operate', TOKEN, {'jobscripts': [], 'capability': {}}):
        store, _ = inert_dispatch['run']('trusted')
    assert wms_policy.CAPABILITY_ENV not in inert_dispatch['launches'][0]['env']
    assert not store.scan('study-operation-capability')


# ----------------------------------------------------------------- launcher channel
@pytest.fixture
def planning_only(tmp_path, monkeypatch):
    """Plan a confined launch without starting the backend or any process."""
    from ravel.controller.confine import launcher
    from ravel.workflow import sandbox
    scratch = tmp_path / 'scratch-parent'
    scratch.mkdir()
    monkeypatch.setenv('TMPDIR', str(scratch.resolve()))
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True, 'checks': {}})
    run = (tmp_path / 'run').resolve()
    (run / 'inputs').mkdir(parents=True)
    (run / 'outputs').mkdir()
    yield run
    assert list(scratch.iterdir()) == [], 'planning creates no scratch directory'


def test_the_launch_capability_reaches_a_planned_confined_launch_and_other_overrides_do_not(planning_only):
    from ravel.controller.confine import environment, launcher
    run = planning_only
    capsule = {'PATH': '/usr/bin', wms_policy.CAPABILITY_ENV: TOKEN, 'RAVEL_ROOT': '/elsewhere',
               'RAVEL_SNAKEMAKE': '/elsewhere/snakemake'}
    plan = launcher.prepare({'argv': [sys.executable, '-c', 'pass'], 'run_dir': str(run), 'stage': 'stage',
                             'cwd': str(run), 'reads': [str(run)], 'writes': [str(run / 'outputs')], 'env': capsule})
    assert plan.env[wms_policy.CAPABILITY_ENV] == TOKEN
    assert 'RAVEL_ROOT' not in plan.env and 'RAVEL_SNAKEMAKE' not in plan.env
    assert set(plan.record['removed_environment_names']) == {'RAVEL_ROOT', 'RAVEL_SNAKEMAKE'}
    assert wms_policy.CAPABILITY_ENV in plan.record['environment_names']
    assert TOKEN not in json.dumps(plan.record, default=str)
    assert wms_policy.CAPABILITY_ENV in environment.passed_channels()
    assert wms_policy.CAPABILITY_ENV not in environment.channels()
    assert environment.launch_environment({}, None, {wms_policy.CAPABILITY_ENV: TOKEN})[0] == {
        wms_policy.CAPABILITY_ENV: TOKEN}


def test_capsule_from_never_harvests_the_launch_capability_from_an_environment():
    # Only a trusted launcher names the secret in a capsule; an ambient environment (a native
    # payload, a supervised stage, a controller process inside a launch authorization) cannot leak it.
    from ravel.controller.confine import environment
    source = {'PATH': '/usr/bin', 'RAVEL_ROOT': '/elsewhere', 'GH_TOKEN': 'x'}
    assert environment.capsule_from(source) == {'PATH': '/usr/bin'}
    assert environment.capsule_from({**source, wms_policy.CAPABILITY_ENV: TOKEN}) == {'PATH': '/usr/bin'}
    env, removed = environment.scrub({'PATH': '/usr/bin', wms_policy.CAPABILITY_ENV: TOKEN, 'RAVEL_ROOT': '/x'})
    assert env == {'PATH': '/usr/bin', wms_policy.CAPABILITY_ENV: TOKEN} and removed == ['RAVEL_ROOT']


# ----------------------------------------------------------------- batch-site workflow commands
LOCAL_RUN = ['/opt/bin/snakemake', '--snakefile', '/w/wf/Snakefile', '--directory', '/w/work',
             '--profile', 'none', '--workflow-profile', 'none', '--cores', '1', '--', 'all']


def _record(site_profile=None):
    record = {'snakemake': ['/opt/bin/snakemake'], 'snakefile': {'path': '/w/wf/Snakefile'},
              'workdir': '/w/work', 'cores': 1, 'targets': ['all']}
    if site_profile is not None:
        record['site'] = {'scheduler': 'htcondor', 'jobs': 4, 'profile': site_profile}
    return record


def test_run_command_uses_the_pinned_site_profile_only_for_the_run():
    local = _record()
    assert wms_adopt.run_command(local) == LOCAL_RUN
    batch = _record({'path': '/w/profiles/htcondor', 'sha256': 'a' * 64, 'files': []})
    assert wms_adopt.run_command(batch) == [
        '/opt/bin/snakemake', '--snakefile', '/w/wf/Snakefile', '--directory', '/w/work',
        '--profile', '/w/profiles/htcondor', '--workflow-profile', 'none', '--cores', '1', '--jobs', '4', '--', 'all']
    # The inspection's dry runs stay local parses: they never carry the site profile.
    assert wms_adopt.inspection_commands(batch) == wms_adopt.inspection_commands(local)
    for argv in wms_adopt.inspection_commands(batch).values():
        assert argv[argv.index('--profile') + 1] == 'none' and '/w/profiles/htcondor' not in argv
        assert '--dry-run' in argv and '--jobs' not in argv


def _review_contract():
    return {'schema_version': 1, 'policy': {
        'schema_version': 1,
        'actors': {'proposer': 'producer', 'executor': 'executor', 'physics_critic': 'critic',
                   'skeptical_verifier': 'skeptic', 'physics_decider': 'decider'},
        'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
        'required_checks': [{'id': 'integrity', 'kind': 'integrity'},
                            {'id': 'scientific', 'kind': 'scientific'}],
        'claim_scopes': {'diagnostic': {'checks': ['integrity'], 'actions': ['delivery', 'reuse']}},
    }, 'correction_contract': {'task_fields': [], 'input_slots': []}}


@pytest.fixture
def adoptable(tmp_path):
    base = tmp_path.resolve()
    (base / 'wf').mkdir()
    (base / 'work').mkdir()
    (base / 'wf/Snakefile').write_text('rule all:\n    output: "final.txt"\n    shell: "echo done > {output}"\n')
    executable = base / 'bin/workflow-manager'
    executable.parent.mkdir()
    executable.write_text(f'#!{sys.executable}\nraise SystemExit("never started by adoption")\n')
    executable.chmod(0o755)
    study_document = {'source': 'Explicit synthetic external workflow control',
                      'assumptions': ['The one-rule workflow is a synthetic engineering control'],
                      'max_seconds': 300, 'approval_mode': 'scripted_yes', 'review_policy': _review_contract()}

    def adopt(name, **options):
        return wms_adopt.adopt(base / 'wf/Snakefile', base / 'work', base / name, study_document,
                               snakemake=str(executable), **options)
    return {'base': base, 'adopt': adopt}


def test_adopt_records_the_pinned_site_profile_and_refuses_an_unsupported_site(adoptable):
    from ravel.workflow import wms_site
    from ravel.workflow.site_profiles import write_profile
    base = adoptable['base']
    profile = Path(write_profile(base / 'profiles', 'htcondor', jobs=4,
                                 options={'workflow_dir': str(base / 'work')})['path'])
    adoptable['adopt']('batch', site={'scheduler': 'htcondor', 'profile_dir': str(profile), 'jobs': 4})
    record = json.loads((base / 'batch' / wms_adopt.RECORD).read_text())
    assert record['site'] == {'scheduler': 'htcondor', 'jobs': 4, 'profile': wms_site.profile_pin(profile)}
    assert wms_adopt.run_command(record)[5:9] == ['--profile', str(profile), '--workflow-profile', 'none']
    # The inspection study shows only local dry runs.
    shown = json.loads((base / 'batch/inspect.science.json').read_text())['task']['commands']
    assert shown == wms_adopt.inspection_commands(record)
    assert all(argv[argv.index('--profile') + 1] == 'none' for argv in shown.values())
    # A local adoption keeps exactly its former record: no site key.
    adoptable['adopt']('local')
    assert 'site' not in json.loads((base / 'local' / wms_adopt.RECORD).read_text())
    for name, site_document, message in (
            ('slurm', {'scheduler': 'slurm', 'profile_dir': str(profile), 'jobs': 4}, 'not supported'),
            ('zero', {'scheduler': 'htcondor', 'profile_dir': str(profile), 'jobs': 0}, 'positive integer'),
            ('flag', {'scheduler': 'htcondor', 'profile_dir': str(profile), 'jobs': True}, 'positive integer'),
            ('relative', {'scheduler': 'htcondor', 'profile_dir': 'profiles/htcondor', 'jobs': 4}, 'absolute'),
            ('missing', {'scheduler': 'htcondor', 'profile_dir': str(base / 'absent'), 'jobs': 4}, 'profile'),
            ('extra', {'scheduler': 'htcondor', 'profile_dir': str(profile), 'jobs': 4, 'cores': 2}, 'exactly')):
        with pytest.raises(ValueError, match=message):
            adoptable['adopt'](name, site=site_document)
        assert not (base / name).exists(), 'a refused adoption leaves no folder behind'


def test_a_batch_site_run_starts_only_with_its_pinned_profile_under_a_launch_capability(tmp_path, monkeypatch):
    from ravel.workflow import wms_site
    from ravel.workflow.site_profiles import write_profile
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV, raising=False)
    profile = Path(write_profile(tmp_path / 'profiles', 'htcondor', jobs=4,
                                 options={'workflow_dir': str(tmp_path)})['path'])
    record = _record(wms_site.profile_pin(profile))
    wms_adopt._site_admission(_record())  # a local site needs no launch capability
    with pytest.raises(ValueError, match='only under its controller launch capability; nothing was started'):
        wms_adopt._site_admission(record)
    store = Store('batch-run')
    with site.trusted_launch(store, 'operate', TOKEN, {'jobscripts': [], 'capability': {}}):
        wms_adopt._site_admission(record)
        (profile / 'config.yaml').write_text((profile / 'config.yaml').read_text() + '# edited\n')
        with pytest.raises(ValueError, match='pinned site profile changed; restore its original bytes'):
            wms_adopt._site_admission(record)


def test_the_adopt_command_takes_the_three_site_arguments_together(adoptable, capsys):
    base = adoptable['base']
    with pytest.raises(SystemExit):
        wms_adopt.main(['adopt', '--snakefile', str(base / 'wf/Snakefile'), '--workdir', str(base / 'work'),
                        '--rundir', str(base / 'partial'), '--study', str(base / 'study.json'),
                        '--site-scheduler', 'htcondor', '--site-jobs', '4'])
    assert 'together' in capsys.readouterr().err
    assert not (base / 'partial').exists()


@pytest.mark.parametrize('rung', ['smoke', 'full', 'scan'])
def test_adopted_scope_selects_the_ordinary_child_compute_rung(tmp_path, monkeypatch, rung):
    context = _prepared_context(tmp_path / 'selected', monkeypatch)
    root = Path(context['run_dir'])
    coverage = {'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity', 'new_sample'],
                'stages': [], 'child_rundir': 'children/study',
                'compute': {'rung': rung, 'reason': 'the declared workflow fits this explicit allocation'}}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, coverage)
    bound = study.bind(context['plan'], context)
    assert _operate(bound)['rung'] == rung
    assert context['plan']['steps'] != bound['steps']
    assert study.gate('checkin1', {**context, 'plan': bound}) == []
    assert not context['store'].scan('authority')
    coverage['compute'] = {'rung': 'scan' if rung != 'scan' else 'full', 'reason': 'a changed selection'}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, coverage)
    assert any(row['code'] == 'study_binding_changed'
               for row in study.gate('checkin1', {**context, 'plan': bound}))


@pytest.mark.parametrize('rung', [None, 'dry', 'pilot', 'science', '', 1, {}, []])
def test_scope_compute_rung_requires_an_explicit_execution_selection(tmp_path, monkeypatch, rung):
    context = _prepared_context(tmp_path / 'invalid', monkeypatch)
    root = Path(context['run_dir'])
    coverage = {'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity', 'new_sample'],
                'stages': [], 'child_rundir': 'children/study',
                'compute': {'rung': rung, 'reason': 'an invalid rung must refuse regardless of its reason'}}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, coverage)
    with pytest.raises(ValueError, match='compute selection requires one smoke, full or scan rung'):
        study.bind(context['plan'], context)
    assert not context['store'].scan('authority')
