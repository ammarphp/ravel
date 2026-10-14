"""Governed authored analysis step: pinned attempts of agent-written Python in a sandbox.

Use this only when no declarative recipe (``columnar-analysis``) or quantity tool can
express a step. The study is planned and approved like any other science mode
(``authored-analysis``); CHECK-IN 1 shows the purpose, the specification, the
input/output contract, the attempt budget, the sandbox and the lint of the first attempt.

The task::

    {"purpose": "why no declarative recipe expresses this step",
     "specification": "spec.md",
     "code": "attempt.py",
     "io_contract": {"inputs": [{"name": "events", "path": "events.root"}],
                     "outputs": [{"path": "yields.json", "kind": "json",
                                  "postconditions": [{"pointer": "/signal_region/yield", "check": "positive"}]}]},
     "parameters": [{"name": "met_threshold", "value": 200, "expected_sensitivity": "yield falls as it rises"}],
     "budget": 3, "timeout_seconds": 600, "reference_paths": ["published/"]}

The code runs as ``python -B -s code.py`` in a fresh working directory that holds
``step-inputs.json`` (input names to absolute paths, and the parameters). It writes its
declared outputs relative to that directory and may import ``ravel.toolkit``. On macOS the
process runs under ``sandbox-exec`` with no network, writes only inside the working
directory and no read access to the reference paths; on Linux it runs under ``bwrap`` with
the same rules. Without a sandbox the step refuses to run.

Each attempt is pinned in a ledger (``attempts/NNN/code.py`` written once, never
overwritten) with its observation: exit code, the tail of stderr, the postcondition
results, the lint findings and a failure class:

- ``coding``: an exception, a missing or malformed output, a failed postcondition, all-zero
  or non-finite weights, or a lint error that stops execution;
- ``infrastructure``: a timeout, a signal, memory or disk exhaustion;
- ``scientific_unresolved``: a postcondition declared as scientific failed, or the code
  wrote ``unresolved.json`` stating a scientific question it cannot settle.

Coding and infrastructure failures may be repaired while the budget lasts; a scientific
failure or an exhausted budget goes to failed-stage review. The designer packet for the
next attempt holds exactly the specification pin, the input/output contract, the
previous code pin, its diff from the attempt before it and the typed observation. It
never holds output values or comparisons with reference results.
"""
import argparse
import ast
import difflib
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

SCOPE = 'governed_authored_analysis_step'
OUTPUT = 'authored-analysis'
TASK_KEYS = {'purpose', 'specification', 'code', 'io_contract'}
OPTIONAL = {'parameters', 'budget', 'timeout_seconds', 'reference_paths', 'loop_warning_threshold'}
CHECKS = ('exists', 'finite', 'positive', 'nonzero', 'range', 'all_finite', 'not_all_zero')
CLASSES = ('coding', 'infrastructure', 'scientific_unresolved')
INFRASTRUCTURE_ERRORS = ('MemoryError', 'No space left on device', 'Killed', 'Resource temporarily unavailable')
FORBIDDEN_MODULES = ('subprocess', 'socket', 'urllib', 'requests', 'http', 'ftplib', 'multiprocessing', 'ctypes')
FORBIDDEN_CALLS = ('os.system', 'os.popen', 'os.exec', 'os.spawn', 'os.fork', 'eval', 'exec', '__import__')
STDERR_TAIL = 4000
MAX_BUDGET = 10
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')


# ---------------------------------------------------------------- helpers
def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'regular file required: {path}')
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': _sha(raw), 'size': len(raw)}


def _canonical(document):
    return json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _resolve(base, value):
    path = Path(value)
    return path if path.is_absolute() else Path(base) / path


def _write_new(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(text)


def _write_json(path, document):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(document, indent=2, allow_nan=False) + '\n')
    os.replace(tmp, path)


# ---------------------------------------------------------------- task
def validate(task):
    """Structural check of an authored-step task (no files read)."""
    if not isinstance(task, dict) or not TASK_KEYS <= set(task) or set(task) - TASK_KEYS - OPTIONAL:
        raise ValueError(f'authored-analysis task needs {sorted(TASK_KEYS)} and may add {sorted(OPTIONAL)}')
    for key in ('purpose', 'specification', 'code'):
        if not isinstance(task[key], str) or not task[key].strip():
            raise ValueError(f'{key} must be nonempty text')
    if len(task['purpose'].split()) < 5:
        raise ValueError('purpose must say why no declarative recipe or quantity tool expresses this step')
    contract = task['io_contract']
    if not isinstance(contract, dict) or set(contract) != {'inputs', 'outputs'}:
        raise ValueError('io_contract has inputs and outputs')
    names = set()
    for item in contract['inputs']:
        if not isinstance(item, dict) or set(item) != {'name', 'path'} or not NAME.match(str(item['name'])) \
                or not isinstance(item['path'], str) or item['name'] in names:
            raise ValueError('each input has a distinct identifier name and a path')
        names.add(item['name'])
    if not isinstance(contract['outputs'], list) or not contract['outputs']:
        raise ValueError('io_contract declares at least one output')
    paths = set()
    for out in contract['outputs']:
        if not isinstance(out, dict) or set(out) - {'path', 'kind', 'postconditions', 'description'} \
                or out.get('kind') not in ('json', 'file') or not isinstance(out.get('path'), str):
            raise ValueError('each output has path, kind json or file, and optional postconditions')
        rel = Path(out['path'])
        if rel.is_absolute() or '..' in rel.parts or out['path'] in paths:
            raise ValueError(f'output path {out["path"]!r} must be relative, inside the working directory and distinct')
        paths.add(out['path'])
        for cond in out.get('postconditions', []):
            if not isinstance(cond, dict) or cond.get('check') not in CHECKS \
                    or set(cond) - {'pointer', 'check', 'low', 'high', 'class', 'description'}:
                raise ValueError(f'a postcondition has a check from {CHECKS}, an optional pointer, and optional class')
            if cond.get('class', 'coding') not in ('coding', 'scientific_unresolved'):
                raise ValueError('a postcondition class is coding or scientific_unresolved')
            if cond['check'] != 'exists' and out['kind'] != 'json':
                raise ValueError('value checks apply to json outputs')
            if cond['check'] == 'range' and not all(type(cond.get(k)) in (int, float) for k in ('low', 'high')):
                raise ValueError('a range postcondition needs numeric low and high')
    params = task.get('parameters', [])
    if not isinstance(params, list):
        raise ValueError('parameters is a list')
    seen = set()
    for p in params:
        if not isinstance(p, dict) or set(p) != {'name', 'value', 'expected_sensitivity'} or not NAME.match(str(p['name'])) \
                or p['name'] in seen or not isinstance(p['expected_sensitivity'], str) or not p['expected_sensitivity'].strip():
            raise ValueError('each parameter has a distinct name, a value and its expected sensitivity')
        seen.add(p['name'])
    budget = task.get('budget', 3)
    if type(budget) is not int or not 1 <= budget <= MAX_BUDGET:
        raise ValueError(f'budget must be an integer from 1 to {MAX_BUDGET}')
    timeout = task.get('timeout_seconds', 600)
    if type(timeout) not in (int, float) or not 1 <= timeout <= 86_400:
        raise ValueError('timeout_seconds must be from 1 to 86400')
    refs = task.get('reference_paths', [])
    if not isinstance(refs, list) or any(not isinstance(r, str) or not r.strip() for r in refs):
        raise ValueError('reference_paths is a list of paths the code must not read')
    threshold = task.get('loop_warning_threshold', 0)
    if type(threshold) is not int or threshold < 0:
        raise ValueError('loop_warning_threshold is a non-negative integer')


def inputs(task, base):
    """Every file the study reads, after the lint of the first attempt passes."""
    validate(task)
    files = [_resolve(base, task['specification']), _resolve(base, task['code'])]
    files += [_resolve(base, i['path']) for i in task['io_contract']['inputs']]
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'regular file required: {path}')
    findings = lint(files[1].read_text(), task)
    errors = [f for f in findings if f['severity'] == 'error']
    if errors:
        raise ValueError('the first attempt fails its lint: ' + '; '.join(f['message'] for f in errors))
    sandbox_command(Path(tempfile.gettempdir()), [], probe=True)
    return files


# ---------------------------------------------------------------- lint
def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return '.'.join(reversed(parts))
    return None


def _per_entry_iteration(node):
    """True for range(len(x)), range(x.shape[0]), range(x.size), range(len(...)) and .tolist() loops."""
    it = node.iter
    if isinstance(it, ast.Call) and _dotted(it.func) == 'range' and it.args:
        arg = it.args[-1] if len(it.args) > 1 else it.args[0]
        if isinstance(arg, ast.Call) and _dotted(arg.func) in ('len', 'ak.num', 'awkward.num', 'np.size', 'numpy.size'):
            return True
        if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Attribute) and arg.value.attr == 'shape':
            return True
        if isinstance(arg, ast.Attribute) and arg.attr in ('size', 'num_entries'):
            return True
    if isinstance(it, ast.Call):
        name = _dotted(it.func) or ''
        if name.endswith('.tolist') or name.endswith('to_list') or name.endswith('.iterrows'):
            return True
    return False


def lint(source, task=None):
    """Findings for authored code: forbidden calls, unused parameters, per-entry loops,
    reimplemented toolkit functions. Errors stop execution; warnings are recorded."""
    from ravel.toolkit import FUNCTIONS
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{'rule': 'syntax', 'severity': 'error', 'line': exc.lineno, 'message': f'syntax error: {exc.msg}'}]
    names, strings = set(), set()
    loops = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            for module in modules:
                if module.split('.')[0] in FORBIDDEN_MODULES:
                    findings.append({'rule': 'forbidden-module', 'severity': 'error', 'line': node.lineno,
                                     'message': f'module {module!r} is not available to an authored step'})
        elif isinstance(node, ast.Call):
            name = _dotted(node.func) or ''
            if any(name == f or name.startswith(f) and f.endswith(('exec', 'spawn')) for f in FORBIDDEN_CALLS):
                findings.append({'rule': 'forbidden-call', 'severity': 'error', 'line': node.lineno,
                                 'message': f'call {name!r} is not available to an authored step'})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS:
            findings.append({'rule': 'toolkit-reimplementation', 'severity': 'warning', 'line': node.lineno,
                             'message': f'function {node.name!r} reimplements ravel.toolkit.{node.name}; import it instead'})
        elif isinstance(node, (ast.For, ast.comprehension)) and _per_entry_iteration(node):
            loops += 1
            findings.append({'rule': 'per-entry-loop', 'severity': 'warning', 'line': getattr(node, 'lineno', getattr(node.iter, 'lineno', 0)),
                             'message': 'a Python loop over every entry or object; use array operations'})
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value)
    if task is not None:
        threshold = task.get('loop_warning_threshold', 0)
        if loops > threshold:
            for f in findings:
                if f['rule'] == 'per-entry-loop':
                    f['above_threshold'] = True
        for p in task.get('parameters', []):
            if p['name'] not in strings and p['name'] not in names:
                findings.append({'rule': 'unused-parameter', 'severity': 'error', 'line': None,
                                 'message': f'declared parameter {p["name"]!r} is never read by the code'})
    return findings


# ---------------------------------------------------------------- sandbox
def _profile(workdir, references):
    def q(p):
        return '"' + str(p).replace('\\', '\\\\').replace('"', '\\"') + '"'
    lines = ['(version 1)', '(allow default)', '(deny network*)', '(deny file-write* (subpath "/"))',
             f'(allow file-write* (subpath {q(workdir)}) (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))']
    for ref in references:
        lines.append(f'(deny file-read* (subpath {q(ref)}))')
    return '\n'.join(lines) + '\n'


def sandbox_command(workdir, references, *, probe=False):
    """The command prefix that confines a process; refuses when no sandbox is available."""
    workdir = Path(workdir).resolve()
    references = [Path(r).resolve() for r in references]
    system = platform.system()
    if system == 'Darwin' and Path('/usr/bin/sandbox-exec').is_file():
        if probe:
            return ['sandbox-exec']
        return ['/usr/bin/sandbox-exec', '-p', _profile(workdir, references)]
    bwrap = shutil.which('bwrap')
    if system == 'Linux' and bwrap:
        if probe:
            return ['bwrap']
        command = [bwrap, '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc', '--unshare-net',
                   '--die-with-parent', '--bind', str(workdir), str(workdir)]
        for ref in references:
            command += ['--tmpfs', str(ref)] if ref.is_dir() else ['--ro-bind', '/dev/null', str(ref)]
        return command
    raise ValueError('no sandbox is available (sandbox-exec on macOS or bwrap on Linux); an authored step does not run unconfined')


def _environment(workdir):
    import ravel
    package_parent = Path(ravel.__file__).resolve().parents[1]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(workdir / '.home'), 'TMPDIR': str(workdir / '.tmp'),
           'MPLCONFIGDIR': str(workdir / '.tmp'), 'MPLBACKEND': 'Agg', 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTHONNOUSERSITE': '1', 'LANG': 'C.UTF-8'}
    if package_parent.name == 'src':
        env['PYTHONPATH'] = str(package_parent)
    return env


def execute(code_path, workdir, task, base, *, python=None):
    """Run one attempt in the sandbox; returns the raw observation (no classification)."""
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    (workdir / '.home').mkdir(); (workdir / '.tmp').mkdir()
    step_inputs = {'inputs': {i['name']: str(_resolve(base, i['path']).resolve()) for i in task['io_contract']['inputs']},
                   'parameters': {p['name']: p['value'] for p in task.get('parameters', [])},
                   'outputs': [o['path'] for o in task['io_contract']['outputs']]}
    (workdir / 'step-inputs.json').write_text(json.dumps(step_inputs, indent=2) + '\n')
    shutil.copyfile(code_path, workdir / 'code.py')
    references = [_resolve(base, r) for r in task.get('reference_paths', [])]
    command = sandbox_command(workdir, references) + [python or sys.executable, '-B', '-s', 'code.py']
    timeout = task.get('timeout_seconds', 600)
    try:
        proc = subprocess.Popen(command, cwd=workdir, env=_environment(workdir), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        return {'exit_code': None, 'timed_out': False, 'stderr_tail': f'could not start: {exc}', 'started': False}
    try:
        _, err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        # Signal only the process group this call created.
        os.killpg(proc.pid, signal.SIGKILL)
        _, err = proc.communicate()
        timed_out = True
    text = err.decode('utf8', errors='replace')
    return {'exit_code': proc.returncode, 'timed_out': timed_out, 'stderr_tail': text[-STDERR_TAIL:], 'started': True}


# ---------------------------------------------------------------- postconditions and classes
def _pointer(document, pointer):
    value = document
    for part in [p.replace('~1', '/').replace('~0', '~') for p in pointer.lstrip('/').split('/') if p != '']:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _numbers(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return [float(v) for v in value]
    return None


def check_outputs(workdir, task):
    """Postcondition results (pass/fail with a value-free message) for every declared output."""
    results = []
    for out in task['io_contract']['outputs']:
        path = Path(workdir) / out['path']
        present = path.is_file() and not path.is_symlink() and path.stat().st_size > 0
        results.append({'output': out['path'], 'check': 'exists', 'passed': present, 'class': 'coding',
                        'message': 'present' if present else 'missing or empty'})
        if not present:
            continue
        document = None
        if out['kind'] == 'json':
            try:
                document = json.loads(path.read_text(), parse_constant=lambda c: float('nan'))
            except (ValueError, UnicodeDecodeError):
                results.append({'output': out['path'], 'check': 'json', 'passed': False, 'class': 'coding',
                                'message': 'not valid JSON'})
                continue
        for cond in out.get('postconditions', []):
            if cond['check'] == 'exists':
                continue
            row = {'output': out['path'], 'check': cond['check'], 'pointer': cond.get('pointer', ''),
                   'class': cond.get('class', 'coding')}
            try:
                values = _numbers(_pointer(document, cond.get('pointer', '')))
            except (KeyError, IndexError, ValueError, TypeError):
                results.append({**row, 'passed': False, 'message': 'pointer does not resolve'})
                continue
            if values is None:
                results.append({**row, 'passed': False, 'message': 'value is not a number or list of numbers'})
                continue
            finite = all(math.isfinite(v) for v in values)
            passed = {'finite': finite, 'all_finite': finite,
                      'positive': finite and all(v > 0 for v in values),
                      'nonzero': finite and all(v != 0 for v in values),
                      'not_all_zero': finite and any(v != 0 for v in values),
                      'range': finite and all(cond.get('low', -math.inf) <= v <= cond.get('high', math.inf) for v in values)
                      }[cond['check']]
            results.append({**row, 'passed': passed, 'message': 'satisfied' if passed else f'{cond["check"]} not satisfied'})
    return results


def classify(raw, postconditions, unresolved):
    """The failure class of an observation, or None when the attempt passed."""
    if not raw['started']:
        return 'infrastructure'
    if raw['timed_out'] or (raw['exit_code'] is not None and raw['exit_code'] < 0):
        return 'infrastructure'
    if raw['exit_code'] != 0:
        tail = raw['stderr_tail']
        if any(marker in tail for marker in INFRASTRUCTURE_ERRORS):
            return 'infrastructure'
        return 'coding'
    if unresolved:
        return 'scientific_unresolved'
    failed = [p for p in postconditions if not p['passed']]
    if any(p['class'] == 'coding' for p in failed):
        return 'coding'
    if failed:
        return 'scientific_unresolved'
    return None


# ---------------------------------------------------------------- ledger
class Ledger:
    """Append-only attempts of one authored step in a directory."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.path = self.dir / 'ledger.json'
        if not self.path.is_file():
            raise ValueError(f'no authored-step ledger in {self.dir}')
        self.doc = json.loads(self.path.read_text())
        self._verify()

    @classmethod
    def create(cls, directory, task, base, *, approval=None):
        validate(task)
        directory = Path(directory)
        if directory.exists() and any(directory.iterdir()):
            raise ValueError(f'ledger directory {directory} is not empty')
        directory.mkdir(parents=True, exist_ok=True)
        task_text = _canonical(task)
        _write_new(directory / 'task.json', task_text + '\n')
        doc = {'schema_version': 1, 'kind': 'authored-step-ledger', 'task_sha256': _sha(task_text.encode()),
               'base': str(Path(base).resolve()), 'specification': _pin(_resolve(base, task['specification'])),
               'budget': task.get('budget', 3), 'approval': approval, 'attempts': [], 'status': 'open'}
        _write_json(directory / 'ledger.json', doc)
        return cls(directory)

    @classmethod
    def continue_from(cls, source, directory, task, *, approval):
        """Copy a ledger (its pins verified) to a new directory bound to an approval."""
        old = cls(source)
        if _canonical(old.task) != _canonical(task):
            raise ValueError('the source ledger is for a different task')
        directory = Path(directory)
        if directory.exists():
            raise ValueError(f'{directory} already exists')
        shutil.copytree(old.dir, directory, symlinks=False)
        new = cls(directory)
        new.doc['approval'] = approval
        new.doc['continued_from'] = {'ledger': str(old.path.resolve()), 'sha256': _sha(old.path.read_bytes())}
        if new.doc['status'] == 'open' and len(new.doc['attempts']) >= new.doc['budget']:
            new.doc['status'] = 'failed_stage_review'
        new._save()
        return new

    @property
    def task(self):
        return json.loads((self.dir / 'task.json').read_text())

    def _verify(self):
        if _sha((self.dir / 'task.json').read_text().rstrip('\n').encode()) != self.doc['task_sha256']:
            raise ValueError('the ledger task changed after the ledger was created')
        for attempt in self.doc['attempts']:
            for key in ('code', 'observation'):
                pin = attempt.get(key)
                if pin and _sha((self.dir / pin['path']).read_bytes()) != pin['sha256']:
                    raise ValueError(f'attempt {attempt["number"]} {key} changed after it was pinned')

    def _save(self):
        _write_json(self.path, self.doc)

    def submit(self, code_path):
        """Pin a new attempt's code; refused after acceptance, review or budget exhaustion."""
        if self.doc['status'] != 'open':
            raise ValueError(f'the step is {self.doc["status"]}; no further attempts')
        attempts = self.doc['attempts']
        if attempts and 'observation' not in attempts[-1]:
            raise ValueError(f'attempt {attempts[-1]["number"]} has not been run')
        if len(attempts) >= self.doc['budget']:
            raise ValueError('the attempt budget is spent')
        number = len(attempts) + 1
        raw = Path(code_path).read_bytes()
        rel = f'attempts/{number:03d}/code.py'
        _write_new(self.dir / rel, raw.decode('utf8'))
        lint_findings = lint(raw.decode('utf8'), self.task)
        attempts.append({'number': number, 'code': {'path': rel, 'sha256': _sha(raw)},
                         'parent': attempts[-1]['number'] if attempts else None, 'lint': lint_findings})
        self._save()
        return attempts[-1]

    def run(self, *, python=None):
        """Execute the latest unexecuted attempt and record its typed observation."""
        attempts = self.doc['attempts']
        if not attempts or 'observation' in attempts[-1]:
            raise ValueError('no attempt is waiting to run; submit one first')
        attempt = attempts[-1]
        task, base = self.task, Path(self.doc['base'])
        workdir = self.dir / f'attempts/{attempt["number"]:03d}/work'
        errors = [f for f in attempt['lint'] if f['severity'] == 'error']
        if errors:
            raw = {'exit_code': None, 'timed_out': False, 'started': False,
                   'stderr_tail': 'not run: ' + '; '.join(f['message'] for f in errors)}
            post, unresolved, failure = [], None, 'coding'
        else:
            raw = execute(self.dir / attempt['code']['path'], workdir, task, base, python=python)
            post = check_outputs(workdir, task) if raw['started'] else []
            unresolved_path = workdir / 'unresolved.json'
            unresolved = unresolved_path.read_text()[:2000] if unresolved_path.is_file() else None
            failure = classify(raw, post, unresolved)
        observation = {'exit_code': raw['exit_code'], 'timed_out': raw['timed_out'], 'stderr_tail': raw['stderr_tail'],
                       'postconditions': post, 'lint': attempt['lint'], 'failure_class': failure,
                       'unresolved_statement': unresolved}
        rel = f'attempts/{attempt["number"]:03d}/observation.json'
        text = json.dumps(observation, indent=2, allow_nan=False) + '\n'
        _write_new(self.dir / rel, text)
        attempt['observation'] = {'path': rel, 'sha256': _sha(text.encode())}
        if failure is None:
            outputs = [_pin(workdir / o['path']) for o in task['io_contract']['outputs']]
            attempt['outputs'] = [{**p, 'path': str(Path(p['path']).relative_to(self.dir.resolve()))} for p in outputs]
            self.doc['status'] = 'accepted'
        elif failure == 'scientific_unresolved':
            self.doc['status'] = 'failed_stage_review'
        elif len(attempts) >= self.doc['budget']:
            self.doc['status'] = 'failed_stage_review'
        else:
            self.doc['status'] = 'open'
        attempt['failure_class'] = failure
        attempt['decision'] = {'accepted': 'accepted', 'failed_stage_review': 'failed_stage_review',
                               'open': 'repair'}[self.doc['status']]
        self._save()
        return attempt

    def packet(self):
        """The designer packet for the next attempt (exactly the declared fields)."""
        attempts = self.doc['attempts']
        if not attempts or 'observation' not in attempts[-1]:
            raise ValueError('the packet follows an executed attempt')
        last = attempts[-1]
        previous = (self.dir / last['code']['path']).read_text()
        diff = None
        if last['parent'] is not None:
            parent = next(a for a in attempts if a['number'] == last['parent'])
            before = (self.dir / parent['code']['path']).read_text()
            diff = ''.join(difflib.unified_diff(before.splitlines(True), previous.splitlines(True),
                                                f'attempt-{parent["number"]}', f'attempt-{last["number"]}'))
        observation = json.loads((self.dir / last['observation']['path']).read_text())
        return {'spec_pin': self.doc['specification'], 'io_contract': self.task['io_contract'],
                'previous_code_pin': {**last['code'], 'attempt': last['number']}, 'previous_diff': diff,
                'observation': {k: observation[k] for k in ('exit_code', 'timed_out', 'stderr_tail', 'postconditions',
                                                            'failure_class', 'lint')}}


def approval_binding(rundir, task):
    """The approved science plan that authorises attempts of this task."""
    rd = Path(rundir)
    spec_path, approval_path = rd / 'inputs/science.json', rd / 'inputs/science-approval.json'
    if not spec_path.is_file() or not approval_path.is_file():
        raise ValueError(f'{rd} has no approved science plan')
    spec = json.loads(spec_path.read_text())
    if spec.get('mode') != 'authored-analysis' or _canonical(spec.get('task')) != _canonical(task):
        raise ValueError('the approved science plan is not this authored-analysis task')
    return {'rundir': str(rd.resolve()), 'specification': _pin(spec_path), 'approval': _pin(approval_path)}


# ---------------------------------------------------------------- science mode
def run(task, base, destination):
    """Worker: pin and run the first attempt; later attempts use the command line."""
    validate(task)
    ledger = Ledger.create(Path(destination) / OUTPUT, task, base, approval={'kind': 'science-worker'})
    ledger.submit(_resolve(base, task['code']))
    attempt = ledger.run()
    packet_hint = f'ravel authored-analysis packet --ledger {ledger.dir}'
    if attempt['failure_class'] is not None:
        raise ValueError(f'authored attempt 1 ended as {attempt["failure_class"]} ({attempt["decision"]}); '
                         f'read the designer packet with: {packet_hint}')
    return {'status': 'passed', 'kind': 'authored-analysis', 'status_scope': SCOPE, 'physics_validated': False,
            'ledger': f'{OUTPUT}/ledger.json', 'attempt': attempt['number'],
            'outputs': [{**o, 'path': f'{OUTPUT}/{o["path"]}'} for o in attempt['outputs']],
            'lint_warnings': [f for f in attempt['lint'] if f['severity'] == 'warning'],
            'limitations': ['The outputs satisfy the declared postconditions only.',
                            'Authored code is checked by its contract and lint, not by an independent implementation.']}


# ---------------------------------------------------------------- command line
def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel authored-analysis', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('lint', help='lint authored code against a task')
    p.add_argument('--code', required=True, type=Path)
    p.add_argument('--task', type=Path)
    p = sub.add_parser('new', help='create the attempt ledger of an approved authored-analysis study')
    p.add_argument('--rundir', required=True, type=Path, help='run whose approved science plan is this task')
    p.add_argument('--ledger', required=True, type=Path)
    p.add_argument('--base', type=Path, default=Path.cwd())
    p.add_argument('--from', dest='source', type=Path, help='continue the attempts of an existing ledger (for example the worker\'s)')
    p = sub.add_parser('submit', help='pin the code of the next attempt')
    p.add_argument('--ledger', required=True, type=Path)
    p.add_argument('--code', required=True, type=Path)
    p = sub.add_parser('run', help='run the latest attempt in the sandbox and record its observation')
    p.add_argument('--ledger', required=True, type=Path)
    p.add_argument('--rundir', type=Path, help='approved run (checked again before execution)')
    p = sub.add_parser('packet', help='print the designer packet for the next attempt')
    p.add_argument('--ledger', required=True, type=Path)
    p = sub.add_parser('status', help='print the ledger')
    p.add_argument('--ledger', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'lint':
            task = json.loads(args.task.read_text()) if args.task else None
            out = lint(args.code.read_text(), task)
        elif args.command == 'new':
            task = json.loads((args.rundir / 'inputs/science.json').read_text())['task']
            binding = approval_binding(args.rundir, task)
            if args.source is not None:
                out = Ledger.continue_from(args.source, args.ledger, task, approval=binding).doc
            else:
                out = Ledger.create(args.ledger, task, args.base, approval=binding).doc
        elif args.command == 'submit':
            out = Ledger(args.ledger).submit(args.code)
        elif args.command == 'run':
            ledger = Ledger(args.ledger)
            approval = ledger.doc['approval'] or {}
            rundir = args.rundir or (Path(approval['rundir']) if approval.get('rundir') else None)
            if rundir is None:
                raise ValueError('name the approved run with --rundir')
            approval_binding(rundir, ledger.task)
            out = ledger.run()
        elif args.command == 'packet':
            out = Ledger(args.ledger).packet()
        else:
            out = Ledger(args.ledger).doc
        print(json.dumps(out, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'authored-analysis refused: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
