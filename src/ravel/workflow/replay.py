"""Governed replay of a completed ordinary science run and a determinism-aware comparison.

`prepare` rebuilds the recorded plan of a completed run (or of a packaged `run/`) in a fresh
run directory. Inputs stay where they are and are checked by digest; nothing large is copied.
It refuses unless the new stage fingerprint (command shape, input digests, outputs and mode)
equals the original apart from the run-directory, base-directory and package locations, and it
writes `replay-of.json`. The original's method decision is copied byte for byte and its sha256 is
recorded; an original without one is refused. The fresh run still needs its own ordinary approval: CHECK-IN 1 shows
the replay line, the original approval receipt binds a different plan and is never reused, and
a spent attempt is never reopened. `compare` compares declared quantities, never bytes, and its
receipt is not a physics validation.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

from . import execution, method_selection, science
from .state_io import atomic_json, read_json

RECORD = 'replay-of.json'
COMPARISON = 'replay-comparison.json'
SECTION = 'replay'
DEFAULT_RELATIVE = 1e-9
TOLERANCE_KEYS = ('schema_version', 'default_relative', 'ignore', 'statistical')
STATISTICAL_KEYS = ('document', 'pointer', 'seed_pointer', 'absolute', 'relative', 'n_sigma', 'uncertainty_pointer')
# Documented top-level bookkeeping, only when the value is a string or null.
# Numeric durations and process identifiers require a declared ignore pointer.
IGNORED_KEYS = frozenset({'attempt_id'})
IGNORED_SUFFIXES = ('_utc', '_at', '_timestamp', '_uuid', '_pid')
FIGURE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.webp',
                             '.svg', '.eps', '.pdf'})
UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?')
DIGEST = re.compile(r'[0-9a-f]{64}')
# Disclosed differences that are locations; a replay always has a new run directory.
LOCATIONS = frozenset({'base_dir', 'rundir'})
# Preparing plans have no replay section until their fingerprints agree.
_PENDING = {}


def _pin(path):
    path = Path(path)
    return {'path': str(path), 'sha256': execution.file_hash(path), 'size': path.stat().st_size}


def _write_new(path, value):
    data = json.dumps(value, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(data)
    return _pin(path)


# ---------------------------------------------------------------- sources

def _source(value):
    """(kind, run records directory, package root or None) of a completed run dir or a package."""
    path = Path(value).expanduser().absolute()
    if (path / 'submission.json').is_file() and (path / 'run' / science.PLAN).is_file():
        return 'package', path / 'run', path
    if path.name == 'run' and (path.parent / 'submission.json').is_file() and (path / science.PLAN).is_file():
        return 'package', path, path.parent
    if (path / science.PLAN).is_file():
        return 'rundir', science.root(path), None
    raise ValueError(f'{path} is neither a completed run directory nor a submission package with run/{science.PLAN}')


def _selected_stage(records):
    """The completed science stage record of a run (or of a package's copied run records)."""
    ledger = execution.load_execution(records)
    record = ledger['stages'].get('science')
    if not isinstance(record, dict) or record.get('status') != 'succeeded':
        status = None if not isinstance(record, dict) else record.get('status')
        raise ValueError(f'replay needs a completed original; its science stage status is {status!r}')
    if type(record.get('outputs')) is not list or not record['outputs']:
        raise ValueError('the completed science stage records no outputs')
    return record


def _original(source):
    kind, records, package = _source(source)
    plan, spec = read_json(records / science.PLAN), read_json(records / science.SPEC)
    if not isinstance(plan, dict) or plan.get('schema_version') != 2 or 'stage_binding' not in plan:
        raise ValueError('replay needs a reviewed (schema 2) science plan with a recorded stage binding')
    if 'research_binding' in plan:
        raise ValueError('a research-bound experiment replays only through its research cycle, which owns its '
                         'budget, dispatch journal and adjudication; add a new cycle experiment instead '
                         '(handoff: research-cycle owner)')
    if len(plan['stages']) != 1:
        raise ValueError('replay supports the one-stage ordinary science plan')
    return {'kind': kind, 'records': records, 'package': package, 'plan': plan, 'spec': spec,
            'rundir': Path(plan['stage_binding']['cwd'])}


def _refuse_partition_child(spec, base):
    """A partition child is claimed in its master's journal; a second run needs a new reservation."""
    if spec['mode'] != 'root-stream':
        return
    from ravel.physics import root_stream_core as core, root_stream_partitions as partitions
    if partitions.dispatch_identity(spec['task'], base, core.Capture()) is not None:
        raise ValueError('a root-stream partition child is claimed in its master journal; running it again needs '
                         'a new master reservation (handoff: root-stream partitions owner), not a replay')


# ---------------------------------------------------------------- fingerprint

def _ravel_root(binding):
    """The package directory whose modules the plan bound, read from its own input list."""
    for key in binding['input_snapshot']:
        path = Path(key)
        if path.name == 'execution.py' and path.parent.name == 'workflow' and path.parent.parent.name == 'ravel':
            return str(path.parent.parent)
    return None


def _interpreter(binding):
    """The command's interpreter as written and as resolved (the plan binds the resolved file)."""
    first = binding['command'][0]
    return (first, str(Path(first).resolve())) if Path(first).is_absolute() else ()


class _Locations:
    """Replace the run, base and package locations of one plan with stable tokens."""

    def __init__(self, rundir, base, ravel, interpreter):
        pairs = []
        for value, token in ((rundir, '<RUNDIR>'), (base, '<BASE>'), (ravel, '<RAVEL>')):
            if value:
                for form in {str(Path(value)), str(Path(value).resolve())}:
                    pairs.append((form, token))
        self.pairs = sorted(pairs, key=lambda pair: -len(pair[0]))
        self.interpreter = interpreter
        self.rundir = {str(Path(rundir)), str(Path(rundir).resolve())}

    def path(self, value):
        if value in self.interpreter:
            return '<PYTHON>'
        for prefix, token in self.pairs:
            if value == prefix or value.startswith(prefix + '/'):
                return token + value[len(prefix):]
        return value

    def text(self, value):
        for prefix, token in self.pairs:
            value = value.replace(prefix, token)
        return value

    def tree(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.tree(v) for v in value]
        if isinstance(value, dict):
            return {self.text(k): self.tree(v) for k, v in value.items()}
        return value

    def internal(self, value):
        return self.relative(value) is not None

    def relative(self, value):
        for root in sorted(self.rundir, key=len, reverse=True):
            if value == root or value.startswith(root + '/'):
                return value[len(root) + 1:]
        return None

    def content(self, raw):
        for prefix, token in self.pairs:
            raw = raw.replace(prefix.encode(), token.encode())
        return hashlib.sha256(raw).hexdigest()


def _inputs(binding, locations, records):
    """Normalised input inventory: run-internal files by location-independent content digest."""
    rows = {}
    for key, entry in binding['input_snapshot'].items():
        name = locations.path(key)
        if name == '<PYTHON>':
            rows[name] = 'interpreter: compared by runtime python version'
            continue
        files = []
        for row in entry['files']:
            relative = locations.relative(key)
            if relative is not None:
                target = Path(records) / relative
                if row['name'] != '.':
                    target = target / row['name']
                raw = target.read_bytes() if target.is_file() else None
                if raw is None or (hashlib.sha256(raw).hexdigest() != row['sha256']):
                    raise ValueError(f'run-internal input {name}/{row["name"]} differs from its plan record')
                files.append([row['name'], locations.content(raw)])
            else:
                files.append([row['name'], row['size'], row['sha256']])
        rows[name] = {'kind': entry['kind'], 'files': files}
    return rows


def _fingerprint(plan, records, base):
    binding = plan['stage_binding']
    interpreter = _interpreter(binding)
    locations = _Locations(binding['cwd'], base, _ravel_root(binding), interpreter)
    stage = plan['stages'][0]
    value = {
        'mode': plan['mode'],
        'command': [locations.path(token) for token in binding['command']],
        'cwd': locations.path(binding['cwd']),
        'inputs': _inputs(binding, locations, records),
        'outputs': list(binding['outputs']),
        'parents': binding['parents'],
        'log': stage.get('log'),
        'stage_fields': locations.tree({k: binding[k] for k in ('output_policy', 'helper_declaration', 'operation_resources')
                                        if k in binding}),
        'execution_task': locations.tree(plan['execution_task']),
        'mutable_inputs': locations.tree(plan['mutable_inputs']),
        'mutable_paths': plan['mutable_paths'],
        'limits': {k: plan[k] for k in ('max_seconds', 'max_attempts', 'approval_mode')},
        'python': binding['runtime']['python'],
    }
    disclosed = {'runtime': {k: binding['runtime'][k] for k in sorted(binding['runtime']) if k != 'python'},
                 'interpreter': None if not interpreter else {
                     'path': interpreter[1], 'sha256': binding['input_snapshot'].get(interpreter[1], {}).get('files', [{}])[0].get('sha256')},
                 'base_dir': plan['base_dir'], 'rundir': binding['cwd']}
    return value, disclosed


def _differences(original, replay):
    rows = []
    for key in original:
        if key == 'inputs':
            continue
        if original[key] != replay[key]:
            rows.append(f'{key} differs')
    a, b = original['inputs'], replay['inputs']
    rows += [f'input removed: {k}' for k in sorted(set(a) - set(b))]
    rows += [f'input added: {k}' for k in sorted(set(b) - set(a))]
    rows += [f'input changed: {k}' for k in sorted(set(a) & set(b)) if a[k] != b[k]]
    return rows


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _current(path):
    if path.is_file():
        return [['.', path.stat().st_size, execution.file_hash(path)]]
    if path.is_dir():
        return [[p.relative_to(path).as_posix(), p.stat().st_size, execution.file_hash(p)]
                for p in sorted(path.rglob('*')) if p.is_file()]
    return None


def _check_inputs(original, base):
    """Refuse before any write when a recorded external input is absent or has another digest."""
    binding = original['plan']['stage_binding']
    old_base, old_ravel = original['plan']['base_dir'], _ravel_root(binding)
    new_ravel = str(Path(execution.__file__).resolve().parents[1])
    locations = _Locations(binding['cwd'], old_base, old_ravel, _interpreter(binding))
    changed = []
    for key, entry in binding['input_snapshot'].items():
        name = locations.path(key)
        if name == '<PYTHON>' or locations.internal(key):
            continue
        actual = Path(name.replace('<BASE>', str(base), 1) if name.startswith('<BASE>') else
                      name.replace('<RAVEL>', new_ravel, 1) if name.startswith('<RAVEL>') else name)
        recorded = [[row['name'], row['size'], row['sha256']] for row in entry['files']]
        now = _current(actual)
        if now is None:
            changed.append(f'{name} is missing at {actual}')
        elif now != recorded:
            digest = now[0][2] if len(now) == 1 else _digest(now)
            was = recorded[0][2] if len(recorded) == 1 else _digest(recorded)
            changed.append(f'{name} at {actual}: recorded sha256 {was}, now {digest}')
    if changed:
        raise ValueError('replay refused: recorded inputs differ from the ones now present: ' + '; '.join(changed))


# ---------------------------------------------------------------- prepare

def _section(record):
    original = record['original']
    differences = record['disclosed_differences']
    environment, locations = sorted(set(differences) - LOCATIONS), sorted(set(differences) & LOCATIONS)
    disclosure = ('environment differs: ' + ', '.join(environment) if environment
                  else 'no environment difference recorded')
    if locations:
        disclosure += '; locations differ: ' + ', '.join(locations)
    return {'statement': f"replay of {original['source']}: identical plan; {disclosure}",
            'original': original['source'], 'original_plan_sha256': original['plan_sha256'],
            'stage_fingerprint_sha256': record['stage_fingerprint_sha256'],
            # The whole record, so an edit to a part no line names also changes the approved CHECK-IN.
            'record_sha256': _digest(record),
            'disclosed_differences': deepcopy(differences),
            'original_approval_reused': False,
            'approval': 'Approve this run dir with `ravel approve`; the original approval binds a different plan.'}


def checkin_section(context):
    """Registered CHECK-IN 1 provider: the replay line of a prepared replay, otherwise nothing."""
    stage = context.get('stage') or {}
    if not isinstance(stage, dict) or not isinstance(stage.get('cwd'), str):
        return None
    rundir = stage['cwd']
    if rundir in _PENDING:
        return deepcopy(_PENDING[rundir])
    path = Path(rundir) / RECORD
    if not path.is_file():
        return None
    return _section(read_json(path))


def _pins(paths):
    return [_pin(p) for p in sorted(paths) if p.is_file() and not p.is_symlink()]


def _result_pins(original):
    if original['kind'] == 'package':
        return _pins((original['package'] / 'results').rglob('*'))
    return _pins(p for out in original['stage']['outputs'] for p in (original['records'] / out).rglob('*'))


def prepare(source, into, *, inputs_root=None):
    """Plan a fresh replay of a completed run; never approve or run it."""
    original = _original(source)
    plan, spec = original['plan'], original['spec']
    base = Path(inputs_root).expanduser().absolute() if inputs_root is not None else Path(plan['base_dir'])
    if not base.is_dir():
        raise ValueError(f'recorded base directory {base} is absent; pass --inputs-root with the fetched inputs')
    _refuse_partition_child(spec, base)
    original['stage'] = _selected_stage(original['records'])
    into = Path(into).expanduser().absolute()
    if into.exists():
        raise ValueError(f'replay run directory {into} must be new')
    decision = original['records'] / method_selection.DECISION_PATH
    if not decision.is_file() or decision.is_symlink():
        raise ValueError(f'replay needs the method decision of the original at {decision}; a replay launches the '
                         'same governed stage, and its method decision is carried, never written anew')
    _check_inputs(original, base)
    original_fp, original_disclosed = _fingerprint(plan, original['records'], plan['base_dir'])
    fp_sha = _digest(original_fp)
    record = {'schema_version': 1, 'kind': 'ravel-replay-of',
              'original': {'source': str(Path(source).expanduser().absolute()), 'kind': original['kind'],
                           'rundir': str(original['rundir']),
                           'plan_sha256': execution.file_hash(original['records'] / science.PLAN),
                           'spec_sha256': execution.file_hash(original['records'] / science.SPEC),
                           'stage_binding_fingerprint': plan['stage_binding']['fingerprint'],
                           'approval': _pin(original['records'] / science.APPROVAL)
                           if (original['records'] / science.APPROVAL).is_file() else None,
                           'result_pins': _result_pins(original),
                           'attempt_journal_pins': _pins((original['records'] / 'logs/science-attempts').glob('*.json'))},
              'stage_fingerprint_sha256': fp_sha,
              'method_decision': {'path': method_selection.DECISION_PATH, 'sha256': execution.file_hash(decision),
                                  'original': str(decision)}}
    key = str(into.resolve())
    _PENDING[key] = None
    rd = None
    try:
        # science.plan reads a spec file and takes its parent as the base; a replay must not
        # write into the original base, so it uses the same planner with the recorded base.
        science._plan(into, None, base / Path(science.SPEC).name, deepcopy(spec))
        rd = science.root(into)
        from .research_admission import admission
        errors = admission(into, 'plan', bind=True)
        if errors:
            raise ValueError('; '.join(errors))
        replay_plan = read_json(rd / science.PLAN)
        replay_fp, replay_disclosed = _fingerprint(replay_plan, rd, str(base))
        differences = _differences(original_fp, replay_fp)
        if differences:
            raise ValueError(f'replay refused: the new plan in {rd} differs from the original apart from '
                             'locations; no replay plan retained: ' + '; '.join(differences))
        shutil.copyfile(decision, rd / method_selection.DECISION_PATH)
        if execution.file_hash(rd / method_selection.DECISION_PATH) != record['method_decision']['sha256']:
            raise ValueError(f'the method decision {decision} changed while it was copied')
        record['replay'] = {'rundir': str(rd), 'plan_sha256': execution.file_hash(rd / science.PLAN),
                            'stage_binding_fingerprint': replay_plan['stage_binding']['fingerprint']}
        record['disclosed_differences'] = {
            name: {'original': original_disclosed[name], 'replay': replay_disclosed[name]}
            for name in original_disclosed if original_disclosed[name] != replay_disclosed[name]}
        record['goal_binding_registered'] = False if 'goal_binding' in spec else None
        record.update(original_approval_reused=False, execution_authorized=False, physics_validated=False)
        pin = _write_new(rd / RECORD, record)
        _PENDING.pop(key, None)
        atomic_json(rd / 'inputs/checkin1.json', science.make_checkin(
            spec, execution.file_hash(rd / science.PLAN), replay_plan['stages'][0], base=base))
        with (rd / 'CHECKIN1.md').open('a', encoding='utf-8') as stream:
            statement = _section(record)['statement']
            stream.write(f"\nReplay of {statement[len('replay of '):]} "
                         f"(stage fingerprint {fp_sha[:12]}). Approve this run dir with `ravel approve`; "
                         'the original approval is never reused.\n')
            for name, values in sorted(record['disclosed_differences'].items()):
                stream.write(f"- {name}: original {json.dumps(values['original'], sort_keys=True)}; "
                             f"replay {json.dumps(values['replay'], sort_keys=True)}\n")
        method_selection.refresh_checkin(rd)
    except (ValueError, OSError):
        # Only a directory successfully planned by this invocation is removed.
        # A pre-existing target or a refused claim never assigns rd.
        if rd is not None:
            shutil.rmtree(rd)
        raise
    finally:
        _PENDING.pop(key, None)
    science.verify_plan(rd)
    science.packet(rd, write=True)
    return {'rundir': str(rd), 'replay_of': pin, 'identical_plan': True,
            'disclosed_differences': sorted(record['disclosed_differences']),
            'execution_authorized': False, 'next': f'ravel approve --rundir {rd}'}


def verify_record(rundir):
    """The replay record of a prepared run dir, bound to its current plan."""
    rd = science.root(rundir)
    if not (rd / RECORD).is_file():
        raise ValueError(f'{rd} is not a prepared replay (no {RECORD})')
    record = read_json(rd / RECORD)
    if (not isinstance(record, dict) or record.get('kind') != 'ravel-replay-of'
            or record.get('replay', {}).get('plan_sha256') != execution.file_hash(rd / science.PLAN)):
        raise ValueError(f'{RECORD} does not bind the current plan of {rd}')
    return record


def approval_gate(rundir):
    """Pass only when the replay run dir holds a fresh approval of its own plan."""
    rd = Path(rundir).expanduser().absolute()
    try:
        record = verify_record(rd)
        science.verify_plan(rd, approved=True)
    except (ValueError, OSError, KeyError) as exc:
        raise ValueError(f'replay run dir {rd} has no fresh approval of its own plan ({exc}); record it with '
                         f'`ravel approve --rundir {rd}`; Snakemake never approves') from exc
    approval = read_json(rd / science.APPROVAL)
    return {'rundir': str(rd), 'approved': True, 'approval': _pin(rd / science.APPROVAL),
            'approval_mode': approval['approval_mode'], 'expert_review': approval['expert_review'],
            'original_approval_reused': (record['original']['approval'] or {}).get('sha256') == execution.file_hash(rd / science.APPROVAL)}


def _wms():
    from importlib import import_module
    try:
        return import_module(__package__ + '.wms_launch')
    except ModuleNotFoundError as exc:
        if exc.name != __package__ + '.wms_launch':
            raise
        return None


def launch(rundir, *, project=None, task=None):
    """Run an approved replay: through the workflow-manager route with a project, else the ordinary run."""
    gate = approval_gate(rundir)
    rd = Path(gate['rundir'])
    if project is not None:
        wms = _wms()
        if wms is None:
            raise ValueError('the workflow-manager route needs `ravel wms` (ravel.workflow.wms_launch), '
                             'which this installation lacks; run without --project for the ordinary run')
        entry = wms.add(project, rd, task=task)
        receipt = wms.launch(project, entry['id'])
        route, code = 'workflow-manager', receipt['exit_code']
    else:
        receipt, route, code = None, 'ordinary-run', science.run(rd)
    return {'rundir': str(rd), 'route': route, 'exit_code': code, 'wms_receipt': receipt,
            'replay_of': _pin(rd / RECORD), 'physics_validated': False}


# ---------------------------------------------------------------- compare

def read_tolerances(path):
    if path is None:
        return {'schema_version': 1, 'default_relative': DEFAULT_RELATIVE, 'ignore': [], 'statistical': []}, None
    value = read_json(path)
    if not isinstance(value, dict) or set(value) - set(TOLERANCE_KEYS) or value.get('schema_version') != 1:
        raise ValueError(f'tolerances need schema_version 1 and only {", ".join(TOLERANCE_KEYS)}')
    relative = value.setdefault('default_relative', DEFAULT_RELATIVE)
    if type(relative) not in (int, float) or not 0 <= relative < 1:
        raise ValueError('default_relative must be a number in [0, 1)')
    for row in value.setdefault('ignore', []):
        if (not isinstance(row, dict) or set(row) - {'document', 'pointer', 'reason'}
                or not _pointer_ok(row.get('pointer')) or row['pointer'] == ''):
            raise ValueError('each ignore row needs a non-empty JSON pointer and may name a document and a reason')
    for row in value.setdefault('statistical', []):
        if (not isinstance(row, dict) or set(row) - set(STATISTICAL_KEYS) or not isinstance(row.get('document'), str)
                or not _pointer_ok(row.get('pointer')) or not _pointer_ok(row.get('seed_pointer'))):
            raise ValueError('each statistical row needs a document, a pointer and a seed_pointer')
        bounds = [k for k in ('absolute', 'relative', 'n_sigma') if k in row]
        if len(bounds) != 1 or type(row[bounds[0]]) not in (int, float) or row[bounds[0]] <= 0:
            raise ValueError('each statistical row declares exactly one positive absolute, relative or n_sigma bound')
        if ('n_sigma' in row) != ('uncertainty_pointer' in row) or ('uncertainty_pointer' in row and not _pointer_ok(row['uncertainty_pointer'])):
            raise ValueError('an n_sigma bound needs an uncertainty_pointer, and only it')
    # A seed is skipped, not compared: one that covers a sampled quantity would hide that quantity.
    for row in value['statistical']:
        if any(other['document'] == row['document'] and _under(other['pointer'], row['seed_pointer'])
               for other in value['statistical']):
            raise ValueError(f"seed_pointer {row['seed_pointer']!r} covers a sampled quantity of {row['document']}; "
                             'it must name the recorded seed only')
    return value, _pin(path)


def _pointer_ok(value):
    return isinstance(value, str) and (value == '' or value.startswith('/'))


def _resolve(document, pointer):
    value = document
    for part in pointer.split('/')[1:] if pointer else []:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _under(pointer, prefix):
    return pointer == prefix or prefix == '' or pointer.startswith(prefix + '/')


def _seed_ok(value):
    """A recorded seed is one integer or one string; anything else is compared as a quantity."""
    return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, str) and value != '')


def _undeclared(row, documents):
    """Why a statistical row's seed is not skipped in this document pair, or None when it is."""
    absent = [side for side, document in zip(('the original', 'the replay'), documents)
              if _resolve(document, row['pointer']) is None]
    if absent:
        return row['pointer'], ('not comparable: declared sampled quantity absent from '
                                + ('both runs' if len(absent) == 2 else absent[0]))
    seeds = [_resolve(document, row['seed_pointer']) for document in documents]
    if any(seed is not None and not _seed_ok(seed) for seed in seeds):
        return row['seed_pointer'], 'not comparable: seed pointer does not name a recorded integer or string seed'
    return None


def _recorded_rundir(records):
    """Run directory a package's copied plan was bound in; its results name paths below it."""
    plan = read_json(records / science.PLAN)
    binding = plan.get('stage_binding') if isinstance(plan, dict) else None
    cwd = binding.get('cwd') if isinstance(binding, dict) else None
    return [cwd] if isinstance(cwd, str) and Path(cwd).is_absolute() and len(Path(cwd).parts) > 1 else []


def _documents(path):
    """(kind, rundir or None, {relative name: path}, run-directory spellings) of a run's or package's delivered documents."""
    kind, records, package = _source(path)
    if kind == 'package':
        folder = package / 'results'
        return (kind, None, {p.relative_to(folder).as_posix(): p for p in sorted(folder.rglob('*')) if p.is_file()},
                _recorded_rundir(records))
    stage = _selected_stage(records)
    files = {}
    for out in stage['outputs']:
        folder = records / out
        for p in sorted(folder.rglob('*') if folder.is_dir() else [folder]):
            if p.is_file():
                files[p.relative_to(folder).as_posix() if folder.is_dir() else p.name] = p
    return kind, records, files, sorted({str(records), str(Path(records).resolve())}, key=len, reverse=True)


def _pair(original, replay):
    """Match documents by relative path; a package's results match by unique file name."""
    if original[0] == 'package':
        names = {}
        for name, path in replay[2].items():
            names.setdefault(Path(name).name, []).append((name, path))
        pairs, missing, matched = {}, [], set()
        for name, path in original[2].items():
            hits = names.get(Path(name).name, [])
            if len(hits) == 1:
                pairs[name] = (path, hits[0][1])
                matched.add(hits[0][0])
            else:
                missing.append(name)
        return pairs, missing, sorted(set(replay[2]) - matched)
    a, b = original[2], replay[2]
    return ({k: (a[k], b[k]) for k in sorted(set(a) & set(b))}, sorted(set(a) - set(b)), sorted(set(b) - set(a)))


class _Walk:
    def __init__(self, document, rules, ignore, seeds, roots, sides):
        self.document, self.rules, self.ignore, self.seeds, self.roots, self.sides = document, rules, ignore, seeds, roots, sides
        self.mismatches, self.not_comparable, self.ignored, self.provenance = [], [], [], []
        self.leaves = 0
        self.declared_suppressed_leaves = 0

    def _declared(self, pointer):
        return (any(_under(pointer, row['pointer']) for row in self.ignore)
                or any(_under(pointer, seed) for seed in self.seeds))

    def _skip(self, pointer, key, a, b):
        for row in self.ignore:
            if _under(pointer, row['pointer']):
                return row.get('reason', 'declared ignore')
        if key is not None:
            if (pointer.count('/') == 1 and key in IGNORED_KEYS
                    and all(v is None or isinstance(v, str) for v in (a, b))):
                return 'record metadata'
            if key.endswith(IGNORED_SUFFIXES) and all(isinstance(v, str) for v in (a, b)):
                return 'record metadata'
        for seed in self.seeds:
            if _under(pointer, seed):
                return 'recorded seed of a sampled quantity'
        return None

    def _location(self, value, side):
        if isinstance(value, str):
            for root in self.roots[side]:
                if value == root or value.startswith(root + '/'):
                    return '<RUNDIR>' + value[len(root):]
        return value

    def walk(self, a, b, pointer='', key=None):
        reason = self._skip(pointer, key, a, b)
        if reason is not None:
            if self._declared(pointer):
                self.declared_suppressed_leaves += max(_leaf_count(a), _leaf_count(b))
            self.ignored.append({'pointer': pointer, 'reason': reason})
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                child = pointer + '/' + k.replace('~', '~0').replace('/', '~1')
                if k not in a or k not in b:
                    reason = self._skip(child, k, a.get(k), b.get(k))
                    if reason is None:
                        self._mismatch(child, a.get(k), b.get(k), 'present in only one run')
                    else:
                        if self._declared(child):
                            self.declared_suppressed_leaves += _leaf_count(a[k] if k in a else b[k])
                        self.ignored.append({'pointer': child, 'reason': reason})
                    continue
                self.walk(a[k], b[k], child, k)
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                self._mismatch(pointer, len(a), len(b), 'length differs')
                return
            for i, (x, y) in enumerate(zip(a, b)):
                self.walk(x, y, f'{pointer}/{i}', None)
            return
        self.leaves += 1
        rule = next((r for r in self.rules if _under(pointer, r['pointer'])), None)
        if rule is not None:
            return self._statistical(a, b, pointer, rule)
        if isinstance(a, bool) or isinstance(b, bool):
            if type(a) is not type(b):
                self._mismatch(pointer, a, b, 'type differs')
            elif a != b:
                self._mismatch(pointer, a, b, 'value differs')
            return
        if a is None or b is None:
            if a is not b and a != b:
                self._mismatch(pointer, a, b, 'value differs')
            return
        if isinstance(a, int) and isinstance(b, int):
            if a != b:
                self._mismatch(pointer, a, b, 'integer count differs (exact)')
            return
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if isinstance(a, int) != isinstance(b, int):
                self._mismatch(pointer, a, b, 'integer in one run, floating-point in the other')
            elif not _close(a, b, self.sides['relative']):
                self._mismatch(pointer, a, b, f"relative difference above {self.sides['relative']:g}")
            return
        if isinstance(a, str) and isinstance(b, str):
            a, b = self._location(a, 'original'), self._location(b, 'replay')
            if (UUID.fullmatch(a) and UUID.fullmatch(b)) or (TIMESTAMP.fullmatch(a) and TIMESTAMP.fullmatch(b)):
                self.leaves -= 1
                self.ignored.append({'pointer': pointer, 'reason': 'embedded identifier or timestamp'})
            elif DIGEST.fullmatch(a) and DIGEST.fullmatch(b):
                self.leaves -= 1
                if a != b:
                    self.provenance.append({'pointer': pointer, 'original': a, 'replay': b})
            elif a == b and a.startswith('<RUNDIR>'):
                self.leaves -= 1
                self.ignored.append({'pointer': pointer, 'reason': 'normalised run-directory path'})
            elif a != b:
                self._mismatch(pointer, a, b, 'value differs')
            return
        self._mismatch(pointer, a, b, 'type differs')

    def _statistical(self, a, b, pointer, rule):
        seeds = [_resolve(doc, rule['seed_pointer']) for doc in self.sides['documents']]
        if any(seed is None for seed in seeds):
            self.not_comparable.append({'document': self.document, 'pointer': pointer,
                                        'reason': 'not comparable: seed not recorded'})
            return
        if not all(_seed_ok(seed) for seed in seeds):
            self.not_comparable.append({'document': self.document, 'pointer': pointer,
                                        'reason': 'not comparable: recorded seed is not an integer or string'})
            return
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)):
            self._mismatch(pointer, a, b, 'sampled quantity is not numeric')
            return
        if isinstance(a, int) != isinstance(b, int):
            self._mismatch(pointer, a, b, 'integer in one run, floating-point in the other')
            return
        if isinstance(a, int):
            if a != b:
                self._mismatch(pointer, a, b, 'integer count differs (exact)')
            return
        if seeds[0] == seeds[1]:
            if not _close(a, b, self.sides['relative']):
                self._mismatch(pointer, a, b, f"relative difference above {self.sides['relative']:g}")
            return
        if 'absolute' in rule:
            bound = rule['absolute']
        elif 'relative' in rule:
            bound = rule['relative'] * max(abs(a), abs(b))
        else:
            suffix = pointer[len(rule['pointer']):]
            errors = [_resolve(doc, rule['uncertainty_pointer'] + suffix) for doc in self.sides['documents']]
            if not all(isinstance(e, (int, float)) and not isinstance(e, bool) and e >= 0 for e in errors):
                self.not_comparable.append({'document': self.document, 'pointer': pointer,
                                            'reason': 'not comparable: uncertainty not recorded'})
                return
            bound = rule['n_sigma'] * math.hypot(*errors)
        if not abs(a - b) <= bound:
            self._mismatch(pointer, a, b, f'outside the declared statistical tolerance {bound:g}')

    def _mismatch(self, pointer, a, b, reason):
        self.mismatches.append({'document': self.document, 'pointer': pointer, 'original': a, 'replay': b,
                                'reason': reason})


def _close(a, b, relative):
    if a == b:
        return True
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= relative * max(abs(a), abs(b))


def _leaf_count(value):
    if isinstance(value, dict):
        return sum(_leaf_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(_leaf_count(v) for v in value)
    return 1


def compare(original, replay, tolerances=None):
    """Compare the declared quantities of two completed runs; never a physics validation."""
    rules, tolerance_pin = read_tolerances(tolerances)
    first, second = _documents(original), _documents(replay)
    pairs, missing, extra = _pair(first, second)
    roots = {'original': first[3], 'replay': second[3]}
    mismatches = [{'document': name, 'pointer': '', 'reason': 'document absent from the replay'} for name in missing]
    mismatches += [{'document': name, 'pointer': '', 'reason': 'document absent from the original'} for name in extra]
    not_comparable, ignored, provenance, not_compared, compared, leaves = [], [], [], [], [], 0
    for name, (a_path, b_path) in sorted(pairs.items()):
        if a_path.suffix.lower() != '.json':
            not_compared.append({'document': name, 'reason': 'no declared-quantity reader for this file type; bytes are not compared'})
            continue
        a, b = read_json(a_path), read_json(b_path)
        statistical = [r for r in rules['statistical'] if r['document'] == name]
        # A seed is skipped only for a quantity both runs hold; otherwise it is compared like any value.
        refused = [(row, _undeclared(row, (a, b))) for row in statistical]
        walk = _Walk(name, statistical, [r for r in rules['ignore'] if r.get('document') in (None, name)],
                     [row['seed_pointer'] for row, reason in refused if reason is None], roots,
                     {'relative': rules['default_relative'], 'documents': (a, b)})
        walk.not_comparable += [{'document': name, 'pointer': reason[0], 'reason': reason[1]}
                                for _, reason in refused if reason is not None]
        walk.walk(a, b)
        if walk.leaves == 0 and walk.declared_suppressed_leaves:
            walk.not_comparable.append({'document': name, 'pointer': '',
                                        'reason': 'all document leaves suppressed by declared ignore rows or seed pointers'})
        mismatches += walk.mismatches
        not_comparable += walk.not_comparable
        ignored += [{'document': name, **row} for row in walk.ignored]
        provenance += [{'document': name, **row} for row in walk.provenance]
        compared.append({'document': name, 'original': _pin(a_path), 'replay': _pin(b_path), 'leaves': walk.leaves})
        leaves += walk.leaves
    link = None
    if second[1] is not None and (Path(second[1]) / RECORD).is_file():
        link = read_json(Path(second[1]) / RECORD)['original']['source'] == str(Path(original).expanduser().absolute())
    unread_quantities = any(Path(row['document']).suffix.lower() not in FIGURE_SUFFIXES for row in not_compared)
    verdict = ('mismatch' if mismatches else 'not_comparable' if not_comparable or leaves == 0
               else 'equal_json_only' if unread_quantities else 'equal')
    return {'schema_version': 1, 'kind': 'ravel-replay-comparison',
            'original': str(Path(original).expanduser().absolute()), 'replay': str(Path(replay).expanduser().absolute()),
            'replay_record_names_original': link, 'tolerances': tolerance_pin,
            'default_relative': rules['default_relative'], 'verdict': verdict, 'equal': verdict == 'equal',
            'compared': compared, 'leaves_compared': leaves, 'mismatches': mismatches,
            'not_comparable': not_comparable, 'ignored': ignored, 'provenance_differences': provenance,
            'not_compared': not_compared, 'physics_validated': False, 'scientific_acceptance_inferred': False,
            'statement': 'Declared quantities compared under stated tolerances; timestamps, identifiers and attempt '
                         'metadata ignored. Agreement shows reproducibility of this run, not physics validity.'}


# ---------------------------------------------------------------- template

TEMPLATE = '''# RAVEL governed replay. Ordinary RAVEL keeps all authority: Snakemake never approves.
# Config: original=<completed run dir or package>, replay=<new run dir>, optional tolerances=<file>,
# optional ravel=<command>, default "ravel". Usage:
#   snakemake -s replay.smk --cores 1 --config original=PATH replay=PATH
# replay_approval_gate fails until `ravel approve --rundir <replay>` records a fresh approval.

RAVEL = config.get("ravel", "ravel")
TOLERANCES = config.get("tolerances")


rule all:
    input: "replay-comparison.json"


rule replay_prepare:
    output: "replay-prepared.json"
    params: original=config["original"], replay=config["replay"], ravel=RAVEL
    threads: 1
    retries: 0
    shell: "{params.ravel} replay prepare --from {params.original:q} --into {params.replay:q} > {output:q}"


rule replay_approval_gate:
    input: "replay-prepared.json"
    output: "replay-approved.json"
    params: replay=config["replay"], ravel=RAVEL
    threads: 1
    retries: 0
    shell: "{params.ravel} replay approval-gate --rundir {params.replay:q} > {output:q}"


rule replay_run:
    input: "replay-approved.json"
    output: "replay-run.json"
    params: replay=config["replay"], ravel=RAVEL
    threads: 1
    retries: 0
    shell: "{params.ravel} replay run --rundir {params.replay:q} > {output:q}"


rule replay_compare:
    input: "replay-run.json"
    output: "replay-comparison.json"
    params: original=config["original"], replay=config["replay"], ravel=RAVEL,
            tolerances=["--tolerances", TOLERANCES] if TOLERANCES else [],
            receipt=config["replay"] + "/replay-comparison.json"
    threads: 1
    retries: 0
    shell: "{params.ravel} replay compare --original {params.original:q} --replay {params.replay:q} {params.tolerances:q} --out {params.receipt:q} > {output:q}"
'''


def template_text():
    """The replay rule set shipped by the procedure export as templates/replay.smk."""
    return TEMPLATE


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel replay', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='operation', required=True)
    p = sub.add_parser('prepare', help='plan a fresh replay of a completed run; no approval, no compute')
    p.add_argument('--from', dest='source', type=Path, required=True, help='completed run dir or submission package')
    p.add_argument('--into', type=Path, required=True, help='new replay run dir')
    p.add_argument('--inputs-root', type=Path, help='directory holding the fetched inputs when the recorded base is absent')
    g = sub.add_parser('approval-gate', help='pass only when the replay run dir has a fresh approval of its own plan')
    g.add_argument('--rundir', type=Path, required=True)
    r = sub.add_parser('run', help='run an approved replay (workflow-manager route with --project)')
    r.add_argument('--rundir', type=Path, required=True)
    r.add_argument('--project', type=Path, help='project whose `ravel wms` workflow runs the replay')
    r.add_argument('--task', help='task id in the project workflow')
    c = sub.add_parser('compare', help='compare declared quantities of an original and its replay')
    c.add_argument('--original', type=Path, required=True)
    c.add_argument('--replay', type=Path, required=True)
    c.add_argument('--tolerances', type=Path)
    c.add_argument('--out', type=Path, help=f'new receipt file (default <replay>/{COMPARISON})')
    c.add_argument('--exit-zero', action='store_true', help='exit 0 once the receipt is written, whatever the verdict')
    sub.add_parser('template', help='print the replay Snakemake rule set')
    args = ap.parse_args(argv)
    if args.operation == 'template':
        sys.stdout.write(template_text())
        return 0
    if args.operation == 'prepare':
        value = prepare(args.source, args.into, inputs_root=args.inputs_root)
    elif args.operation == 'approval-gate':
        value = approval_gate(args.rundir)
    elif args.operation == 'run':
        value = launch(args.rundir, project=args.project, task=args.task)
    else:
        value = compare(args.original, args.replay, args.tolerances)
        out = args.out
        if out is None:
            kind, records, _ = _source(args.replay)
            if kind != 'rundir':
                raise ValueError('pass --out when the replay is not a run directory')
            out = records / COMPARISON
        value['receipt'] = str(_write_new(out, value)['path'])
    print(json.dumps(value, indent=2, allow_nan=False))
    if args.operation == 'compare':
        return 0 if value['equal'] or args.exit_zero else 1
    if args.operation == 'run':
        return 0 if value['exit_code'] == 0 else 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f'ravel replay: {exc}', file=sys.stderr)
        raise SystemExit(2)
