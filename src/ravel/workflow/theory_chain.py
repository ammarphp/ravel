"""Theory chain: model source -> UFO -> amplitudes -> loops -> widths and branching ratios.

``draft(request, doctor=None)`` composes the chain a theory request needs. Each stage names its
registered operation, the signature it runs under (the registry first, else the seam rows in
``data/theory_chain/operation_rows.json``), the tools it needs and its admission check. The UFO
stage carries model admission (``model_admission.admit``) as its postcondition; every later stage
has the admitted model as a precondition.

A stage is never refused for a missing tool. It is held, and the hold names what would make it
possible: the doctor's fix for an absent check, the doctor command that would verify an unreported
one, or the manifest refusal class (SP-03 for loop-level decays). Tool status comes only from a
supplied ``ravel doctor --json`` report; this module never probes or starts a tool.

``run(chain, out_dir, runners=...)`` walks the stages with injected runners (mocks in tests). A ready
stage without a runner is queued: its exact commands go to the native queue and nothing native
starts here. ``completion_record`` adds the standing native requests N3 (fresh-kernel provider load)
and N4a/N4b (Standard Model export and admission before and after the export fix).

A drafted chain is a plan, not a result: the admission checks state what they cannot detect, and
widths carry no witness until a native width comparison runs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re

SCHEMA = 1
KIND = 'theory-chain'
SEAM = 'data/theory_chain/operation_rows.json'
SEAM_PATH = Path(str(files('ravel').joinpath(SEAM)))
STAGES = ('model-source', 'ufo', 'amplitudes', 'loops', 'widths')
ROUTES = ('feynrules-template', 'feynrules-spec', 'supplied-ufo', 'sarah')
OK_STATUSES = ('ready', 'remote_route')
DONE = ('done', 'supplied')

# Manifest checks per group that the chain reads from a doctor report.
MANIFEST_CHECKS = {'wolfram': ('wolfram-kernel', 'feynrules', 'sarah', 'feyncalc', 'feynarts-patched'),
                   'madgraph': ('mg-python', 'mg5'),
                   'finite-integrals': ('integral-python', 'integrals-make', 'form'),
                   'diagram-consumers': ('heptapod-nda', 'heptapod-eda')}
# Operation -> (group, checks) it needs beyond the host Python.
OPERATION_TOOLS = {'model-authoring': (('wolfram', ('wolfram-kernel', 'feynrules')),),
                   'model-derivation-bridge': (('wolfram', ('wolfram-kernel', 'feynrules')),),
                   'model-sources': (('wolfram', ('wolfram-kernel', 'sarah')),),
                   'feynarts-amplitude': (('wolfram', ('wolfram-kernel', 'feyncalc', 'feynarts-patched')),),
                   'finite-integrals': (('finite-integrals', ('integral-python', 'integrals-make', 'form')),),
                   'diagrammatica-code': (('diagram-consumers', ('heptapod-nda', 'heptapod-eda')),),
                   'resonance-width': ()}
CHAIN_OPERATIONS = tuple(OPERATION_TOOLS)
ADMISSION_TOOLS = (('madgraph', ('mg-python', 'mg5')),)
SARAH_FIELDS = ('model', 'model-name', 'eigenstate', 'ufo-options', 'particle-conventions',
                'provider-readiness-receipt', 'provider-readiness-run', 'point-policy')
LOOP_DECAYS = 'SP-03'
LOOP_DECAYS_FALLBACK = ('An installer entry in the spectrum group that builds Collier or LoopTools at a pinned source, '
                        'a doctor check for its libraries, and a width route that binds them.')

LINT_CHECKS = ('fr-lint', 'spec-census')
STAGE_CHECKS = {'amplitudes': ('diagram-census-complete',), 'loops': ('known-answer-integrals',),
                'widths': ('br-closure', 'width-witness')}
CANNOT_DETECT = {
    'model-source': ['physics errors the ModelSpec states consistently (a wrong but anomaly-free charge assignment)'],
    'amplitudes': ['loop-level gauge invariance and renormalisation; the census counts diagrams, not their values'],
    'loops': ['integrals outside the known-answer controls; precision beyond the reported numerical error'],
    'widths': ['channels the request does not declare; branching ratios close over the declared channels only',
               'higher-order corrections; tree-level widths carry no QCD or electroweak correction'],
}
STAGE_MINUTES = {'model-source': (1, 5), 'ufo': (15, 300), 'amplitudes': (30, 200), 'loops': (60, 2000),
                 'widths': (10, 50)}

ROOT_ASSENT = '$ROOT_ASSENT'
SM_SOURCE = ('Pinned public FeynRules 2.3.49 Standard Model SM.fr with explicit DiagonalCKM.rst, named LSM; fresh '
             'source-to-UFO derivation and admission. No widths, generator, amplitudes or detector qualification.')
N4_PROCESS = 'p p > e+ e-'
N4A_COMMIT = 'ee77697'   # model admission is the authoring postcondition; the export fix is not yet applied
N4B_COMMIT = '4a0ffc2'   # the export fix: adjudicated SM diagnostics and the pinned provider digest
UFO_POLICY = 'feynrules-2.3.49-literal-UFOError-raise-v1'


# --------------------------------------------------------------------------- signatures
def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def seam_rows():
    """Signature rows this package supplies for registered modes the registry does not sign yet."""
    return json.loads(SEAM_PATH.read_text(encoding='utf-8'))['operations']


def signature(operation):
    """{source, sha256, entry}: the registry entry when it exists, else the seam row."""
    from ravel.validation import validate_request_plan as rp
    entry = rp.registry().get(operation)
    source = 'registry'
    if not entry:
        entry, source = seam_rows().get(operation), 'seam'
    if not entry:
        raise ValueError(f'operation {operation!r} has no signature in the registry or the theory-chain seam')
    return {'source': source, 'sha256': hashlib.sha256(_canonical(entry)).hexdigest(), 'entry': entry}


# --------------------------------------------------------------------------- tool status
def _check_status(doctor, group, check):
    """(status, fix) of one manifest check in a doctor report; ``unverified`` without a report."""
    if doctor is None:
        return 'unverified', None
    row = next((g for g in doctor.get('groups') or () if g.get('group') == group), None)
    if row is None:
        return 'not-reported', None
    found = next((c for c in row.get('checks') or () if c.get('id') == check), None)
    if found is None:
        return row.get('status', 'not-reported'), row.get('fix')
    return found.get('status'), found.get('fix')


def _missing(doctor, tools):
    rows = []
    for group, checks in tools:
        for check in checks:
            status, fix = _check_status(doctor, group, check)
            if status not in OK_STATUSES:
                rows.append({'group': group, 'check': check, 'status': status, 'fix': fix})
    return rows


def _tool_hold(missing):
    """A hold for missing or unverified checks, with what would make the stage possible."""
    absent = [m for m in missing if m['status'] not in ('unverified', 'not-reported')]
    parts = []
    for group in dict.fromkeys(m['group'] for m in missing):
        rows = [m for m in missing if m['group'] == group]
        fixes = list(dict.fromkeys(m['fix'] for m in rows if m['fix']))
        checks = ', '.join(m['check'] for m in rows)
        install = '; '.join(fixes) if fixes else (
            f'`python scripts/setup/install.py --only {group}`' if any(m in absent for m in rows) else None)
        verify = f'`ravel doctor --group {group} --json` reporting {checks} ready'
        parts.append(f'{install}, then {verify}' if install else verify)
    return {'held_by': 'tool-absent' if absent else 'tool-unverified', 'missing': missing,
            'would_make_possible': '; '.join(parts)}


def _refusal_class(doctor, class_id):
    for row in (doctor or {}).get('refusal_classes') or ():
        if row.get('id') == class_id and row.get('would_make_it_possible'):
            return row['would_make_it_possible']
    return LOOP_DECAYS_FALLBACK


# --------------------------------------------------------------------------- request
def _process(text, name):
    if type(text) is not str or not text.strip() or '\n' in text or '\r' in text or ';' in text:
        raise ValueError(f'{name} must be one MadGraph process line')
    return text.strip()


def _model_source(model):
    """(task, spec) for the model source; the spec is checked here, nothing native runs."""
    from ravel.physics import model_authoring as ma
    if type(model) is not dict or model.get('route') not in ROUTES:
        raise ValueError(f'request.model.route must be one of {", ".join(ROUTES)}')
    route = model['route']
    if route == 'feynrules-template':
        spec = ma.instantiate(model.get('template'), model.get('values') or {})
        return {'route': route, 'template': model['template']}, spec
    if route == 'feynrules-spec':
        spec = deepcopy(model.get('spec'))
        ma.validate_spec(spec)
        return {'route': route}, spec
    if route == 'supplied-ufo':
        if type(model.get('ufo')) is not str or not model['ufo'].strip():
            raise ValueError('a supplied-ufo route needs request.model.ufo, the UFO directory')
        return {'route': route, 'ufo': model['ufo']}, None
    sarah = model.get('sarah')
    if type(sarah) is not dict:
        raise ValueError('a sarah route needs request.model.sarah with the derivation inputs')
    return {'route': route, 'sarah': deepcopy(sarah)}, None


def _validate(request):
    if type(request) is not dict or type(request.get('id')) is not str or not request['id'].strip():
        raise ValueError('a theory request needs an id')
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', request['id']) is None:
        raise ValueError('request.id must be a short identifier')
    if 'model' not in request:
        raise ValueError('a theory request needs a model')
    _process(request.get('process'), 'request.process')
    amplitudes = request.get('amplitudes')
    if amplitudes is not None:
        if type(amplitudes) is not dict:
            raise ValueError('request.amplitudes must be an object')
        _process(amplitudes.get('process'), 'request.amplitudes.process')
        loops = amplitudes.get('loops', 0)
        if type(loops) is not int or not 0 <= loops <= 3:
            raise ValueError('request.amplitudes.loops must be an integer from 0 to 3')
    if request.get('loops') is not None and not (amplitudes or {}).get('loops'):
        raise ValueError('request.loops needs a loop-level amplitude (request.amplitudes.loops >= 1)')
    widths = request.get('widths')
    if widths is not None:
        if type(widths) is not dict or type(widths.get('particle')) is not str:
            raise ValueError('request.widths needs the decaying particle')
        if widths.get('order', 'tree') not in ('tree', 'loop'):
            raise ValueError('request.widths.order must be tree or loop')
        channels = widths.get('channels')
        if channels is not None and (type(channels) is not list or not channels
                                     or any(type(c) is not str or not c.strip() for c in channels)):
            raise ValueError('request.widths.channels must be a list of declared channels')


# --------------------------------------------------------------------------- draft
def _stage(name, operation, depends_on, task, check, doctor, hold=None):
    stage = {'stage': name, 'operation': operation, 'depends_on': depends_on, 'task': task,
             'signature': None, 'tools': [], 'admission_check': check, 'status': 'ready', 'hold': None}
    if operation:
        sig = signature(operation)
        stage['signature'] = {'source': sig['source'], 'sha256': sig['sha256']}
        tools = OPERATION_TOOLS.get(operation, ())
        stage['tools'] = [{'group': g, 'checks': list(c)} for g, c in tools]
        missing = _missing(doctor, tools)
        if missing and hold is None:
            hold = _tool_hold(missing)
    if hold is not None:
        stage.update(status='held', hold=hold)
    return stage


def _admission_check(doctor):
    from ravel.physics import model_admission as adm
    check = {'role': 'postcondition', 'operation': 'model-admission', 'function': 'ravel.physics.model_admission.admit',
             'checks': [*adm.REQUIRED, 'spec-charge-census', 'hermiticity-feynrules', 'ward-identity'],
             'required': list(adm.REQUIRED), 'preconditions': ['model-source-postcondition'],
             'scope': adm.SCOPE, 'pending': None}
    missing = _missing(doctor, ADMISSION_TOOLS)
    if missing:
        pending = _tool_hold(missing)
        check['pending'] = {'checks': [f'mg5-check-{k}' for k in adm.MG5_CHECKS], 'missing': missing,
                            'would_make_possible': pending['would_make_possible']}
    return check


def draft(request, *, doctor=None):
    """The theory chain for ``request`` under the tool status of ``doctor`` (a ravel-doctor-report)."""
    _validate(request)
    source_task, spec = _model_source(request['model'])
    route = source_task['route']
    process = _process(request['process'], 'request.process')
    stages = []

    # model source
    lint = {'role': 'postcondition', 'operation': 'model-authoring-lint', 'checks': list(LINT_CHECKS),
            'preconditions': [], 'cannot_detect': CANNOT_DETECT['model-source']}
    if route == 'supplied-ufo':
        source = _stage('model-source', None, None, source_task,
                        {'role': 'precondition', 'operation': None, 'checks': ['supplied-ufo-path'], 'preconditions': []},
                        doctor)
        source['status'] = 'supplied'
    elif route == 'sarah':
        absent = [f for f in SARAH_FIELDS if not source_task['sarah'].get(f)]
        hold = None if not absent else {
            'held_by': 'input-absent', 'missing': [{'input': f} for f in absent],
            'would_make_possible': 'the SARAH derivation inputs ' + ', '.join(absent)
                                   + ' in request.model.sarah (see `ravel model-derivation-bridge plan-sarah --help`)'}
        source = _stage('model-source', 'model-sources', None, source_task,
                        {'role': 'postcondition', 'operation': 'sarah-checkmodel', 'checks': ['sarah-checkmodel'],
                         'preconditions': [], 'cannot_detect': ['CheckModel output is diagnostic, not a certificate']},
                        doctor, hold=hold)
    else:
        source = _stage('model-source', 'model-authoring', None, {**source_task, 'spec': spec}, lint, doctor)
    stages.append(source)

    # UFO, with model admission as its postcondition
    ufo_operation = {'supplied-ufo': None, 'sarah': 'model-sources'}.get(route, 'model-derivation-bridge')
    ufo = _stage('ufo', ufo_operation, 'model-source', {'process': process}, _admission_check(doctor), doctor)
    if route == 'supplied-ufo':
        ufo.update(status='supplied')
        ufo['task']['ufo'] = source_task['ufo']
    stages.append(ufo)

    amplitudes = request.get('amplitudes')
    if amplitudes:
        stages.append(_stage('amplitudes', 'feynarts-amplitude', 'ufo', deepcopy(amplitudes), {
            'role': 'postcondition', 'operation': 'amplitude-census', 'checks': list(STAGE_CHECKS['amplitudes']),
            'preconditions': ['model-admitted'], 'cannot_detect': CANNOT_DETECT['amplitudes']}, doctor))
        if amplitudes.get('loops', 0) >= 1:
            stages.append(_stage('loops', 'finite-integrals', 'amplitudes', deepcopy(request.get('loops') or {}), {
                'role': 'postcondition', 'operation': 'integral-controls', 'checks': list(STAGE_CHECKS['loops']),
                'preconditions': ['model-admitted', 'amplitudes-delivered'], 'cannot_detect': CANNOT_DETECT['loops']},
                doctor))

    widths = request.get('widths')
    if widths:
        check = {'role': 'postcondition', 'operation': 'width-checks', 'checks': list(STAGE_CHECKS['widths']),
                 'preconditions': ['model-admitted'], 'cannot_detect': CANNOT_DETECT['widths']}
        if widths.get('order', 'tree') == 'loop':
            hold = {'held_by': f'refusal-class:{LOOP_DECAYS}', 'missing': [{'library': 'Collier or LoopTools'}],
                    'would_make_possible': _refusal_class(doctor, LOOP_DECAYS)}
            stages.append(_stage('widths', None, 'ufo', deepcopy(widths), check, doctor, hold=hold))
        else:
            operation = 'resonance-width' if widths.get('channels') else 'diagrammatica-code'
            stages.append(_stage('widths', operation, 'ufo', deepcopy(widths), check, doctor))

    chain = {'schema_version': SCHEMA, 'kind': KIND, 'request_id': request['id'], 'route': route,
             'process': process, 'stages': stages,
             'doctor': None if doctor is None else {'kind': doctor.get('kind'), 'status': doctor.get('status')},
             'scope': ('A drafted chain: the operations, tools and admission checks a theory request needs, with '
                       'every unavailable stage held. It establishes no physics result.')}
    chain['digest'] = hashlib.sha256(_canonical(chain)).hexdigest()
    return chain


# --------------------------------------------------------------------------- native requests
_VAR = re.compile(r'\$([A-Z][A-Z0-9_]*)')


def _bind(argv, bindings):
    def one(text):
        return _VAR.sub(lambda m: str(bindings[m.group(1)]) if m.group(1) in bindings else m.group(0), text)
    return [one(a) for a in argv]


def _unresolved(commands):
    names = []
    for command in commands:
        for arg in command['argv']:
            names += [m for m in _VAR.findall(arg) if m not in names]
    return names


def _request(row, bindings):
    used = _unresolved(row['commands'])
    row['commands'] = [{**c, 'argv': _bind(c['argv'], bindings)} for c in row['commands']]
    row['bindings'] = {k: bindings[k] for k in used if k in bindings}
    row['unresolved'] = _unresolved(row['commands'])
    row['runs_now'] = False
    return row


def _python(source, *argv):
    return ['env', f'PYTHONPATH={source}/src', '$PYTHON', '-m', 'ravel', *argv]


def _sm_derivation(row_id, commit, run, extra, admit_ufo, expected):
    source = f'$N_RUN_ROOT/{row_id.lower()}-source'
    plan = ['env', f'PYTHONPATH={source}/src', '$PYTHON', '-m', 'ravel.physics.model_derivation_bridge', 'plan',
            '--kernel', '$WOLFRAM_KERNEL', '--application-metadata', '$WOLFRAM_METADATA',
            '--feynrules', '$FEYNRULES_ROOT', '--model', '$FEYNRULES_ROOT/Models/SM', '--model-file', 'SM.fr',
            '--restriction', 'DiagonalCKM.rst', '--lagrangian', 'LSM',
            '--provider-readiness-receipt', '$PROVIDER_RECEIPT', '--provider-readiness-run', '$PROVIDER_RUN',
            '--source', SM_SOURCE, '--rundir', run, '--review-policy', '$REVIEW_POLICY',
            '--trust-provider-source', '--trust-model-source', '--max-seconds', '900', '--max-ram-mib', '8192', *extra]
    return [
        {'step': 'worktree', 'by': 'root', 'argv': ['/usr/bin/git', '-C', '$RAVEL_REPO', 'worktree', 'add', '--detach',
                                                    source, commit]},
        {'step': 'plan', 'by': 'root', 'argv': plan},
        {'step': 'approve', 'by': 'root', 'argv': _python(source, 'approve', '--rundir', run, '--quote', ROOT_ASSENT),
         'note': 'root records machine assent; this is never a physicist review'},
        {'step': 'run', 'by': 'root', 'argv': _python(source, 'run', '--rundir', run),
         'note': 'the one native job; Wolfram kernel bounded by --max-seconds and --max-ram-mib'},
        {'step': 'admit', 'by': 'root', 'argv': _python(source, 'model', 'admit', '--ufo', admit_ufo, '--mg5', '$MG5',
                                                        '--process', N4_PROCESS, '--workdir', f'{run}/admission-mg5',
                                                        '--out', f'{run}/admission.json'),
         'expected': expected},
    ]


def native_queue_requests(bindings=None):
    """The standing native requests N3, N4a and N4b with exact commands; ``$NAME`` tokens bind from ``bindings``."""
    bindings = dict(bindings or {})
    n3_out = '$N_RUN_ROOT/n3-wolfram-load'
    host = ['$HOME/.codex/config.toml', '$HOME/.claude/settings.json']
    n3 = {'id': 'N3', 'title': 'Fresh Wolfram kernel loads FeynRules 2.3.49, SARAH 4.15.4, FeynCalc and FeynArts 3.12 '
                               '(patched); host configuration digests unchanged',
          'native': True, 'source_commit': None, 'depends_on': [], 'expected_minutes': 10, 'disk_mb': 5,
          'never': 'Never run Wolfram AgentTools deploy (it rewrites host agent configuration).',
          'commands': [
              {'step': 'outdir', 'by': 'root', 'argv': ['mkdir', n3_out]},
              {'step': 'host-config-before', 'by': 'root', 'argv': ['shasum', '-a', '256', *host],
               'stdout': f'{n3_out}/host-config-before.sha256'},
              {'step': 'doctor', 'by': 'root', 'argv': _python('$RAVEL_REPO', 'doctor', '--group', 'wolfram', '--json'),
               'stdout': f'{n3_out}/doctor-wolfram.json',
               'note': 'the wolfram-kernel check loads each package in a fresh kernel (manifest load list)'},
              {'step': 'host-config-after', 'by': 'root', 'argv': ['shasum', '-a', '256', *host],
               'stdout': f'{n3_out}/host-config-after.sha256'},
              {'step': 'compare', 'by': 'root', 'argv': ['diff', f'{n3_out}/host-config-before.sha256',
                                                         f'{n3_out}/host-config-after.sha256'],
               'expected': 'no output: the digests are unchanged'}]}
    n4a_run = '$N_RUN_ROOT/n4a-sm-derivation'
    n4a = {'id': 'N4a', 'title': 'FeynRules SM -> UFO -> MadGraph check, baseline before the export fix',
           'native': True, 'source_commit': N4A_COMMIT, 'depends_on': ['N3'], 'expected_minutes': 60, 'disk_mb': 300,
           'commands': _sm_derivation('N4a', N4A_COMMIT, n4a_run, [], f'{n4a_run}/outputs/attempt-1/exported-ufo',
                                      'baseline: the export reproduces the Python-2 and kinetic/mass diagnostics, '
                                      'and admission refuses at ufo-static')}
    n4b_run = '$N_RUN_ROOT/n4b-sm-derivation'
    n4b = {'id': 'N4b', 'title': 'N4a rerun on the export-fix commit; SY-03 acceptance reads this record',
           'native': True, 'source_commit': N4B_COMMIT, 'depends_on': ['N3', 'N4a'], 'expected_minutes': 60,
           'disk_mb': 300,
           'commands': _sm_derivation('N4b', N4B_COMMIT, n4b_run, ['--pinned-provider', '--ufo-python-compatibility',
                                                                   UFO_POLICY],
                                      f'{n4b_run}/outputs/attempt-1/exported-ufo-python3',
                                      'the export passes its adjudicated diagnostics and static admission; '
                                      'MadGraph gauge, Lorentz and permutation checks pass on the process')}
    return [_request(row, bindings) for row in (n3, n4a, n4b)]


def _stage_request(chain, stage, workdir, bindings):
    """Exact commands that would run one ready stage; written for the queue, never executed here."""
    work = str(workdir)
    task = Path(workdir) / 'task.json'
    task.write_text(json.dumps(stage['task'], indent=2, sort_keys=True, default=str) + '\n')
    name, operation = stage['stage'], stage['operation']
    spec = Path(workdir) / 'model-spec.json'
    if stage['task'].get('spec') is not None:
        spec.write_text(json.dumps(stage['task']['spec'], indent=2) + '\n')
    native = bool(operation and 'executes_native' in signature(operation)['entry']['effects'])
    if name == 'model-source' and operation == 'model-authoring':
        commands = [{'step': 'author', 'by': 'executor', 'argv': ['ravel', 'model', 'author', '--spec', str(spec),
                                                                  '--out', f'{work}/authoring',
                                                                  '--feynrules', '$FEYNRULES_ROOT']}]
        native = False  # authoring writes the model tree; FeynRules runs at the UFO stage
    elif name == 'ufo' and operation == 'model-derivation-bridge':
        commands = [{'step': 'derive-and-admit', 'by': 'root',
                     'argv': ['ravel', 'model', 'author', '--spec', str(spec), '--out', f'{work}/derivation',
                              '--feynrules', '$FEYNRULES_ROOT', '--run', '--wolframscript', '$WOLFRAMSCRIPT',
                              '--mg5', '$MG5', '--process', chain['process']],
                     'note': 'run_native makes model admission the postcondition of authoring'}]
    elif operation == 'model-sources':
        sarah = stage['task'].get('sarah') or {}
        argv = ['ravel', 'model-derivation-bridge', 'plan-sarah', '--kernel', '$WOLFRAM_KERNEL',
                '--application-metadata', '$WOLFRAM_METADATA', '--sarah', '$SARAH_ROOT',
                '--source', f'SARAH model source for {chain["request_id"]}', '--rundir', f'{work}/run',
                '--review-policy', '$REVIEW_POLICY', '--trust-provider-source', '--trust-model-source']
        for field in SARAH_FIELDS:
            argv += [f'--{field}', str(sarah[field])]
        commands = [{'step': 'plan', 'by': 'root', 'argv': argv},
                    {'step': 'approve', 'by': 'root', 'argv': ['ravel', 'approve', '--rundir', f'{work}/run',
                                                               '--quote', ROOT_ASSENT]},
                    {'step': 'run', 'by': 'root', 'argv': ['ravel', 'run', '--rundir', f'{work}/run']}]
    else:
        commands = [{'step': 'plan', 'by': 'executor', 'argv': ['ravel', 'plan', '--rundir', f'{work}/run', '--spec',
                                                                f'{work}/spec.json'],
                     'note': f'the {operation} study specification is completed from task.json before CHECK-IN 1'},
                    {'step': 'approve', 'by': 'root', 'argv': ['ravel', 'approve', '--rundir', f'{work}/run',
                                                               '--quote', ROOT_ASSENT]},
                    {'step': 'run', 'by': 'root', 'argv': ['ravel', 'run', '--rundir', f'{work}/run']}]
    minutes, disk = STAGE_MINUTES[name]
    row = {'id': f'{chain["request_id"]}:{name}', 'title': f'{name} stage ({operation}) of {chain["request_id"]}',
           'stage': name, 'operation': operation, 'native': native, 'source_commit': None,
           'depends_on': [stage['depends_on']] if stage['depends_on'] else [], 'expected_minutes': minutes,
           'disk_mb': disk, 'commands': commands}
    return _request(row, bindings)


# --------------------------------------------------------------------------- run
def _row(check_id, status, **detail):
    return {'id': check_id, 'status': status, **detail}


def _declared(checks, outputs):
    declared = (outputs or {}).get('checks') or {}
    rows = []
    for name in checks:
        value = declared.get(name)
        rows.append(_row(name, 'pass' if value is True else 'fail' if value is False else 'not_evaluated'))
    return rows


def _width_rows(outputs):
    widths = (outputs or {}).get('widths')
    rows = []
    if isinstance(widths, dict) and widths and all(isinstance(v, (int, float)) and v >= 0 for v in widths.values()) \
            and sum(widths.values()) > 0:
        total = float(sum(widths.values()))
        ratios = {k: v / total for k, v in widths.items()}
        outputs['total_width'] = total
        outputs['branching_ratios'] = ratios
        closure = abs(sum(ratios.values()) - 1.0)
        rows.append(_row('br-closure', 'pass' if closure < 1e-12 else 'fail', total_width=total,
                         closure=closure, over='declared channels'))
    elif widths is None:
        rows.append(_row('br-closure', 'not_evaluated', reason='the stage returned no partial widths'))
    else:
        rows.append(_row('br-closure', 'fail', reason='partial widths must be nonnegative numbers with a positive sum'))
    witness = ((outputs or {}).get('checks') or {}).get('width-witness')
    rows.append(_row('width-witness', 'pass' if witness is True else 'fail' if witness is False else 'not_evaluated',
                     **({} if witness is not None else
                        {'reason': 'no independent width (FeynRules ComputeWidths or MadGraph auto-width) was compared'})))
    return rows


def _write_new(path, value):
    text = json.dumps(value, indent=2, sort_keys=True, default=str) + '\n'
    with Path(path).open('x') as handle:
        handle.write(text)
    return {'path': str(path), 'sha256': hashlib.sha256(text.encode()).hexdigest()}


def _upstream_hold(stage, upstream):
    if upstream['status'] == 'queued':
        reason = f'the queued request {upstream["native_request"]["id"]} completing'
    elif upstream['status'] == 'admission_refused':
        reason = ('a UFO that passes model admission (refused: '
                  + '; '.join(r.get('reason', r['id']) if isinstance(r, dict) else str(r)
                              for r in upstream['admission']['refusals'])[:400] + ')')
    elif upstream.get('hold'):
        reason = upstream['hold']['would_make_possible']
    else:
        failed = [r['id'] for r in upstream.get('postcondition') or () if r['status'] != 'pass']
        reason = f'the {upstream["stage"]} postcondition passing ({", ".join(failed)})'
    return {'held_by': f'upstream:{upstream["stage"]}',
            'would_make_possible': f'the {upstream["stage"]} stage completing: {reason}'}


def _admit(stage, outputs, spec, process, workdir, mg5, mg5_runner, events):
    from ravel.physics import model_admission as adm
    ufo = outputs.get('ufo') or stage['task'].get('ufo')
    record = adm.admit(ufo, spec=spec, native=outputs.get('native_checks'), mg5=mg5, process=process if mg5 else None,
                       workdir=Path(workdir) / 'admission-mg5' if mg5 else None, mg5_runner=mg5_runner)
    pin = _write_new(Path(workdir) / 'admission.json', record)
    decision = record['decision']
    events.append(f'ufo:admission:{decision}')
    stage['admission'] = {'decision': decision, 'refusals': record['refusals'], 'not_evaluated': record['not_evaluated'],
                          'record': pin}
    if decision == 'admitted':
        stage['status'] = 'done'
    elif decision == 'refused':
        stage['status'] = 'admission_refused'
    else:
        pending = (stage['admission_check'].get('pending') or {}).get('would_make_possible')
        names = ', '.join(r['id'] if isinstance(r, dict) else str(r) for r in record['not_evaluated'])
        stage['status'] = 'admission_incomplete'
        stage['hold'] = {'held_by': 'admission-incomplete',
                         'would_make_possible': f'verdicts for the required admission checks ({names})'
                                                + (f': {pending}' if pending else
                                                   '; pass --mg5 with the requested process')}


def run(chain, out_dir, *, runners=None, mg5=None, mg5_runner=None, bindings=None):
    """Walk the drafted chain; injected ``runners`` stand in for the stage tools. Returns the run record.

    ``runners`` maps a stage name to ``runner(stage, inputs, workdir) -> outputs``. A ready stage
    without a runner is queued with its exact commands; nothing native starts here. Model
    admission runs after the UFO stage and gates every later stage.
    """
    out = Path(out_dir)
    out.mkdir(parents=True)
    runners, bindings = runners or {}, dict(bindings or {})
    stages, events, queue = [deepcopy(s) for s in chain['stages']], [], []
    by = {s['stage']: s for s in stages}
    spec = by['model-source']['task'].get('spec')
    for stage in stages:
        name = stage['stage']
        workdir = out / name
        workdir.mkdir()
        upstream = by.get(stage['depends_on']) if stage['depends_on'] else None
        if upstream is not None and upstream['status'] not in DONE:
            stage.update(status='held', hold=_upstream_hold(stage, upstream))
            continue
        if stage['status'] == 'held':
            continue
        if stage['status'] == 'supplied':
            if name == 'ufo':
                _admit(stage, {}, spec, chain['process'], workdir, mg5, mg5_runner, events)
            continue
        runner = runners.get(name)
        if runner is None:
            stage['native_request'] = _stage_request(chain, stage, workdir, bindings)
            stage['status'] = 'queued'
            queue.append(stage['native_request'])
            continue
        inputs = {**deepcopy(stage['task']), 'spec': spec,
                  'upstream': {s['stage']: s.get('outputs') for s in stages if s.get('outputs') is not None}}
        if 'ufo' in by and by['ufo'].get('outputs'):
            inputs['ufo'] = by['ufo']['outputs'].get('ufo')
        events.append(f'{name}:start')
        outputs = runner(stage, inputs, workdir) or {}
        stage['outputs'] = outputs
        if name == 'model-source':
            rows = [_row('fr-lint', 'pass' if outputs.get('lint_passed') is True else
                         'fail' if outputs.get('lint_passed') is False else 'not_evaluated'),
                    _row('spec-census', 'pass' if outputs.get('census_passed') is True else
                         'fail' if outputs.get('census_passed') is False else 'not_evaluated')]
            if stage['operation'] == 'model-sources':
                rows = _declared(stage['admission_check']['checks'], outputs)
            stage['postcondition'] = rows
            stage['status'] = 'done' if all(r['status'] == 'pass' for r in rows) else 'postcondition_failed'
        elif name == 'ufo':
            _admit(stage, outputs, spec, chain['process'], workdir, mg5, mg5_runner, events)
        else:
            rows = _width_rows(outputs) if name == 'widths' else _declared(STAGE_CHECKS[name], outputs)
            stage['postcondition'] = rows
            stage['status'] = 'postcondition_failed' if any(r['status'] == 'fail' for r in rows) else 'done'
        events.append(f'{name}:{stage["status"]}')
    status = 'complete' if all(s['status'] in DONE for s in stages) else 'partial'
    result = {'schema_version': SCHEMA, 'kind': 'theory-chain-run', 'chain_digest': chain['digest'],
              'request_id': chain['request_id'], 'status': status, 'stages': stages, 'events': events,
              'native_queue': queue}
    _write_new(out / 'theory-chain-run.json', result)
    return result


def completion_record(chain, result, *, bindings=None):
    """The chain's completion record: stage outcomes, holds, and every native request with exact commands."""
    stages = [{'stage': s['stage'], 'operation': s['operation'], 'status': s['status'],
               'signature': s['signature'], 'admission_check': s['admission_check'], 'hold': s.get('hold'),
               'admission': s.get('admission'), 'postcondition': s.get('postcondition')} for s in result['stages']]
    return {'schema_version': SCHEMA, 'kind': 'theory-chain-completion', 'request_id': chain['request_id'],
            'chain_digest': chain['digest'], 'status': result['status'], 'stages': stages,
            'native_queue': native_queue_requests(bindings) + deepcopy(result['native_queue']),
            'note': ('Native requests are for root to queue; one native scientific job at a time. Approval '
                     'steps record machine assent, never physicist review.')}


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    d = sub.add_parser('draft', help='draft the theory chain for a request JSON; never runs a tool')
    d.add_argument('--request', required=True, type=Path)
    d.add_argument('--doctor', type=Path, help='a saved `ravel doctor --json` report')
    q = sub.add_parser('queue', help='print the standing native requests N3, N4a and N4b')
    q.add_argument('--bindings', type=Path, help='JSON object binding $NAME tokens in the commands')
    args = parser.parse_args(argv)
    if args.command == 'draft':
        doctor = json.loads(args.doctor.read_text()) if args.doctor else None
        print(json.dumps(draft(json.loads(args.request.read_text()), doctor=doctor), indent=2, default=str))
    else:
        bindings = json.loads(args.bindings.read_text()) if args.bindings else None
        print(json.dumps(native_queue_requests(bindings), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
