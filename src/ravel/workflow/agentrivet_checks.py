"""Bounded construction checks of each generated Rivet draft: compile, registration, small sample.

The construction request declares the checks (tools, environment, ceilings and an
optional small event sample). Before any launch the declaration is approved once
(`approve`), its whole ceiling is reserved against the original campaign budget,
and every process start is recorded in the construction's launch journal
(``logs/authorization``). Each draft is checked at most once, in a fresh
directory with a closed environment:

1. ``rivet-build`` compiles the draft; compiler text and parsed diagnostics are kept.
2. When a Python interpreter with the Rivet bindings is declared, RAVEL's
   loader observer confirms that the built plugin registers ``routine_name``.
3. When a sample is declared, the routine runs on at most ``max_events`` events and
   ``rivet_sample_checks`` turns the output into typed findings.

Results are construction feedback for the routine's author and reviewers. They
never replace the sealed ``routine-build`` study, the full event run or the
independent review, and they carry no physics validation.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from ravel.physics import hepdata_table_map, rivet_sample_checks, routine_build, yoda_text
from . import launch_authorization, research_cycle, state_io

MAX_PROBES = 12
REGISTRATION_SECONDS = 120
OUTPUT_LIMIT = 32_000
ENVIRONMENT = set(routine_build.ENVIRONMENT) | {'CXX'}
DIAGNOSTIC = re.compile(r'^(?P<file>[^\s:][^:\n]*):(?P<line>\d+):(?:(?P<column>\d+):)?\s*'
                        r'(?P<severity>fatal error|error|warning|note):\s*(?P<message>.+)$', re.M)
APPROVAL = 'checks-approval.json'
SCOPE = ('Bounded compile, plugin-registration and small-sample construction checks of generated drafts. '
         'Not a sealed build, a full event run, scientific acceptance or physics review.')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f'{label} needs exactly {sorted(keys)}')


def _int(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer in [{low}, {high}]')
    return value


def _tool(path, base, label):
    if path is None:
        return None
    if type(path) is not str or not path.strip():
        raise ValueError(f'{label} must be an executable path or null')
    p = Path(path) if Path(path).is_absolute() else Path(base) / path
    identity = routine_build.executable_identity(p)
    return {'path': str(Path(p).absolute()), 'identity': identity}


def normalize(declaration, *, base, rounds):
    """Validate a checks declaration and capture tool identities and sample bytes."""
    _keys(declaration, {'schema_version', 'runtime', 'compile', 'sample'}, 'construction checks')
    if declaration['schema_version'] != 1 or type(declaration['schema_version']) is not int:
        raise ValueError('construction checks version 1 required')
    runtime = declaration['runtime']
    _keys(runtime, {'rivet_build', 'rivet', 'python', 'environment'}, 'checks runtime')
    environment = runtime['environment']
    if type(environment) is not dict or any(type(k) is not str or type(v) is not str for k, v in environment.items()):
        raise ValueError('checks environment maps names to strings')
    if set(environment) - ENVIRONMENT:
        raise ValueError(f'checks environment names must be among {sorted(ENVIRONMENT)}')
    tools = {k: _tool(runtime[k], base, k) for k in ('rivet_build', 'rivet', 'python')}
    if tools['rivet_build'] is None:
        raise ValueError('the compile check needs rivet_build')
    compile_ = declaration['compile']
    _keys(compile_, {'max_probes', 'timeout_seconds'}, 'compile checks')
    probes = _int(compile_['max_probes'], rounds, MAX_PROBES, 'compile max_probes (at least one per coder call)')
    compile_seconds = _int(compile_['timeout_seconds'], 10, 900, 'compile timeout_seconds')
    sample = declaration['sample']
    sample_seconds = 0
    if sample is not None:
        _keys(sample, {'events', 'max_events', 'timeout_seconds', 'tolerance'}, 'sample checks')
        if tools['rivet'] is None:
            raise ValueError('the sample check needs the rivet executable')
        _keys(sample['events'], {'path', 'sha256'}, 'sample events pin')
        events = Path(sample['events']['path'])
        events = events if events.is_absolute() else Path(base) / events
        if not events.is_file() or events.is_symlink() or _file_sha(events) != sample['events']['sha256']:
            raise ValueError('sample events differ from their pin')
        _int(sample['max_events'], 1, 100_000, 'sample max_events')
        sample_seconds = _int(sample['timeout_seconds'], 10, 3600, 'sample timeout_seconds')
        tolerance = sample['tolerance']
        if type(tolerance) not in (int, float) or isinstance(tolerance, bool) or not 0 < tolerance <= 0.5:
            raise ValueError('sample tolerance must be in (0, 0.5]')
        sample = {'events': {'path': str(events.absolute()), 'sha256': sample['events']['sha256']},
                  'max_events': sample['max_events'], 'timeout_seconds': sample_seconds, 'tolerance': float(tolerance)}
    per_probe = compile_seconds + (REGISTRATION_SECONDS if tools['python'] else 0) + sample_seconds
    return {'schema_version': 1, 'runtime': {**tools, 'environment': dict(sorted(environment.items()))},
            'compile': {'max_probes': probes, 'timeout_seconds': compile_seconds}, 'sample': sample,
            'reservation': {'calls': 0, 'output_tokens': 0, 'native_attempts': probes, 'wall_seconds': probes * per_probe}}


def _file_sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def approve(request_pin, *, base_dir, quote, scripted=False):
    """Record the one approval of a request's declared checks; returns the receipt pin."""
    from . import agentrivet_construction as construction
    from .launch_authorization import operational_utc
    path, request = construction._load(request_pin, base_dir)
    checks = (request.get('construction') or {}).get('checks')
    if checks is None:
        raise ValueError('this construction request declares no checks to approve')
    if type(quote) is not str or not quote.strip():
        raise ValueError('actual assent text required')
    if type(scripted) is not bool or scripted != (request['approval_mode'] == 'scripted_yes'):
        raise ValueError('approval mode must match the request; scripted assent is not human approval')
    target = path.parent / APPROVAL
    if target.exists():
        raise ValueError('checks approval already recorded; preserve the original receipt')
    receipt = {'schema_version': 1, 'kind': 'agentrivet-construction-checks-approval',
               'construction_request': {'path': str(path), 'sha256': request_pin['sha256']},
               'checks_sha256': _digest(checks), 'reservation': deepcopy(checks['reservation']),
               'approval_mode': request['approval_mode'], 'quote': quote, 'utc': operational_utc(),
               'scope': SCOPE, 'expert_review': False, 'physics_validated': False}
    return construction._emit(target, receipt)


def _approval(path, request_pin, checks):
    if not path.is_file():
        raise ValueError('declared construction checks need their recorded approval before any launch')
    raw = path.read_bytes()
    receipt = json.loads(raw)
    if (receipt.get('kind') != 'agentrivet-construction-checks-approval'
            or receipt.get('construction_request', {}).get('sha256') != request_pin['sha256']
            or receipt.get('checks_sha256') != _digest(checks) or receipt.get('expert_review') is not False
            or type(receipt.get('quote')) is not str or not receipt['quote'].strip()):
        raise ValueError('construction checks approval does not bind this request and declaration')
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def diagnostics(text):
    """Compiler diagnostics as ``{file, line, column, severity, message}`` rows (at most 64)."""
    rows = []
    for match in DIAGNOSTIC.finditer(text or ''):
        rows.append({'file': Path(match['file']).name, 'line': int(match['line']),
                     'column': int(match['column']) if match['column'] else None,
                     'severity': match['severity'], 'message': match['message'].strip()[:500]})
        if len(rows) == 64:
            break
    return rows


def bounded(text, limit=OUTPUT_LIMIT):
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f'\n[... {len(text) - limit} characters omitted ...]\n' + text[-half:]


class Session:
    """One construction's checks: approval, one reservation, journaled launches, cached records."""

    def __init__(self, request, request_pin, construction_dir, routine, *, table_map=None, contract=(),
                 histograms=None, reference=None):
        self.request, self.request_pin = request, request_pin
        self.root = Path(construction_dir).absolute()
        self.checks = request['construction']['checks']
        self.routine = routine
        self.table_map, self.contract = table_map, list(contract)
        self.histograms = histograms or (lambda: [])
        self.reference = reference
        self.directory = self.root / 'checks'
        self.approval = None
        self.reservation = None
        self.records = {}

    # ---------------------------------------------------------- governance
    def start(self):
        self.approval = _approval(self.root / APPROVAL, self.request_pin, self.checks)
        identity = 'operation:agentrivet-construction-checks:' + str(self.root)
        evidence = {'approval': self.approval, 'checks_sha256': _digest(self.checks)}
        research_cycle.reserve_operation(self.request['campaign'], identity, self.checks['reservation'], evidence)
        self.reservation = identity
        self.directory.mkdir(exist_ok=True)
        (self.root / launch_authorization.JOURNAL).mkdir(parents=True, exist_ok=True)
        self.records = retained(self.root)
        return self

    def _verify_tools(self):
        for key in ('rivet_build', 'rivet', 'python'):
            tool = self.checks['runtime'][key]
            if tool is not None and routine_build.executable_identity(tool['path']) != tool['identity']:
                raise ValueError(f'declared {key} changed after approval')
        sample = self.checks['sample']
        if sample is not None and _file_sha(sample['events']['path']) != sample['events']['sha256']:
            raise ValueError('sample events changed after approval')

    def _launch(self, command, workdir, environment, timeout, label, probe):
        context = {'kind': 'agentrivet-construction-check', 'label': label, 'probe': probe, 'cwd': str(workdir),
                   'routine': self.routine}
        authorization = {'approval': self.approval, 'reservation': self.reservation,
                         'checks_sha256': _digest(self.checks), 'machine_approval_is_not_human_review': True}
        confined = self._confinement(command, workdir, environment)
        event = launch_authorization._append(self.root, {'event': 'authorized', 'command': command,
                                                         'context': context, 'authorization': authorization})
        started = time.monotonic()
        if confined is None:
            process = subprocess.Popen(command, cwd=workdir, env=environment, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
        else:
            from ravel.controller.confine import start
            process = start(confined, subprocess.Popen, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
        launched = launch_authorization._append(self.root, {
            'event': 'launched', 'authorization_sequence': event['sequence'],
            'authorization_sha256': event['sha256'], 'pid': process.pid,
            **({'confinement': confined.record} if confined is not None else {})})
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)   # this launch's own new session only
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        result = {'returncode': None if timed_out else process.returncode, 'timed_out': timed_out,
                  'stdout': stdout, 'stderr': stderr, 'seconds': round(time.monotonic() - started, 3),
                  'journal': [event['sequence'], launched['sequence']]}
        if confined is not None:
            from ravel.controller.confine import finish
            result['confinement'] = {'launch': confined.record, 'finish': finish(process)}
        return result

    def _confinement(self, command, workdir, environment):
        """For a construction directory of a controller-owned run: the confined launch plan, else None.

        The check reads the construction directory, its declared tools and sample, and writes only
        its own work directory; planning refuses or holds before the journal is written.
        """
        from ravel.controller.confine import prepare, runs
        owner = runs.owner_of(self.root)
        if owner is None:
            return None
        reads = [str(self.root)]
        for tool in self.checks['runtime'].values():
            if isinstance(tool, dict) and isinstance(tool.get('path'), str) and os.path.exists(tool['path']):
                located = Path(tool['path']).resolve()
                reads.append(str(located))
        sample = self.checks.get('sample')
        if sample is not None and os.path.exists(sample['events']['path']):
            reads.append(str(Path(sample['events']['path']).resolve()))
        return prepare({'argv': [str(part) for part in command], 'env': dict(environment), 'reads': reads,
                        'writes': [str(Path(workdir).resolve())], 'cwd': str(Path(workdir).resolve()),
                        'controller': {'run_id': owner[0]}, 'label': 'agentrivet-construction-check'})

    def _environment(self, workdir, extra=None):
        environment = routine_build.isolated_process_environment(workdir / 'home', workdir / 'tmp')
        (workdir / 'home').mkdir(exist_ok=True)
        (workdir / 'tmp').mkdir(exist_ok=True)
        environment.update(self.checks['runtime']['environment'])
        environment.update(extra or {})
        return environment

    # ---------------------------------------------------------- checks
    def record_for(self, code):
        return self.records.get(hashlib.sha256(code.encode('utf-8')).hexdigest())

    @staticmethod
    def compiled(record):
        """True when the compile passed and, where probed, the plugin registered the routine."""
        if record is None or record['compile']['status'] != 'passed':
            return False
        return record['registration'] is None or record['registration']['status'] == 'passed'

    def build_result(self, code):
        """(returncode, text) in the upstream BuildResult convention for an observed draft."""
        return result_of(self.observe(code))

    def observe(self, code):
        if self.approval is None:
            raise ValueError('construction checks were not started')
        if type(code) is not str or not code.strip():
            raise ValueError('nonempty draft required')
        existing = self.record_for(code)
        if existing is not None:
            return existing
        probe = len(self.records) + 1
        if probe > self.checks['compile']['max_probes']:
            raise ValueError('approved construction check budget exhausted; no further launch')
        self._verify_tools()
        workdir = self.directory / f'probe-{probe:02d}'
        workdir.mkdir()
        raw = code.encode('utf-8')
        source = workdir / f'{self.routine}.cc'
        source.write_bytes(raw)
        if self.reference is not None:
            (workdir / f'{self.routine}.yoda').write_text(self.reference)
        plugin = workdir / f'Rivet{self.routine}.so'
        environment = self._environment(workdir)
        compiled = self._launch([self.checks['runtime']['rivet_build']['path'], plugin.name, source.name], workdir,
                                environment, self.checks['compile']['timeout_seconds'], 'compile', probe)
        text = (compiled['stdout'] + compiled['stderr']).decode('utf-8', errors='replace')
        status = 'timed_out' if compiled['timed_out'] else ('passed' if compiled['returncode'] == 0 and plugin.is_file() else 'failed')
        if status == 'failed' and compiled['returncode'] == 0:
            text += f'\nrivet-build exited 0 but wrote no {plugin.name}'
        log = workdir / 'compile-log.json'
        state_io.atomic_json(log, {'command': [self.checks['runtime']['rivet_build']['path'], plugin.name, source.name],
                                   'returncode': compiled['returncode'], 'timed_out': compiled['timed_out'],
                                   'stdout_base64': base64.b64encode(compiled['stdout']).decode(),
                                   'stderr_base64': base64.b64encode(compiled['stderr']).decode()})
        record = {'schema_version': 1, 'kind': 'agentrivet-construction-check', 'probe': probe, 'routine': self.routine,
                  'source': {'path': str(source), 'sha256': hashlib.sha256(raw).hexdigest()},
                  'compile': {'status': status, 'returncode': compiled['returncode'], 'seconds': compiled['seconds'],
                              'output': bounded(text), 'diagnostics': diagnostics(text),
                              'log': {'path': str(log), 'sha256': _file_sha(log)}},
                  'registration': None, 'sample': None, 'journal': list(compiled['journal']),
                  'approval': self.approval, 'reservation': self.reservation,
                  'bookings': self._bookings(code), 'physics_validated': False, 'scientific_acceptance': False}
        if status == 'passed' and self.checks['runtime']['python'] is not None:
            record['registration'] = self._registration(workdir, plugin, environment, probe, record)
        if self.compiled(record) and self.checks['sample'] is not None:
            record['sample'] = self._sample(workdir, plugin, probe, record)
        target = workdir / 'record.json'
        state_io.atomic_json(target, record)
        self.records[record['source']['sha256']] = record
        return record

    def _bookings(self, code):
        booked = hepdata_table_map.bookings(code)
        found = hepdata_table_map.verify_bookings(self.table_map, booked, self.histograms())
        return {'booked': booked, 'findings': found}

    def _registration(self, workdir, plugin, environment, probe, record):
        observation = workdir / 'loader-observation.json'
        command = routine_build.rivet_loader_command(self.checks['runtime']['python']['path'], plugin, self.routine, observation)
        ran = self._launch(command, workdir, environment, REGISTRATION_SECONDS, 'registration', probe)
        record['journal'] += ran['journal']
        names = None
        try:
            if ran['timed_out'] or ran['returncode'] != 0 or not observation.is_file():
                raise ValueError(bounded((ran['stdout'] + ran['stderr']).decode('utf-8', errors='replace'), 4000)
                                 or 'loader observation absent')
            document = json.loads(observation.read_text())
            names = document.get('registered_names')
            routine_build.verify_loader_observation(document, plugin, self.routine, environment, workdir, ran['stdout'],
                                                    base64.b64encode(ran['stderr']).decode())
            return {'status': 'passed', 'registered_names': names, 'message': 'the plugin registers the routine'}
        except (ValueError, OSError, KeyError, TypeError) as problem:
            if names is None and observation.is_file():
                try:
                    names = json.loads(observation.read_text()).get('registered_names')
                except (ValueError, OSError):
                    names = None
            return {'status': 'failed', 'registered_names': names, 'message': str(problem)[:4000]}

    def _sample(self, workdir, plugin, probe, record):
        sample, runtime = self.checks['sample'], self.checks['runtime']
        output = workdir / 'sample.yoda'
        arguments = ['-a', self.routine, '-n', str(sample['max_events']), '-o', output.name, sample['events']['path']]
        extra = {'RIVET_ANALYSIS_PATH': str(workdir), 'RIVET_REF_PATH': str(workdir),
                 'RIVET_INFO_PATH': str(workdir), 'RIVET_DATA_PATH': str(workdir)}
        if runtime['python'] is not None:
            environment = self._environment(workdir, extra)
            command = routine_build.rivet_loader_command(runtime['python']['path'], plugin, self.routine,
                                                         workdir / 'sample-loader-observation.json',
                                                         runtime['rivet']['path'], *arguments)
        else:
            environment = self._environment(workdir, extra)
            command = [runtime['rivet']['path'], *arguments]
        ran = self._launch(command, workdir, environment, sample['timeout_seconds'], 'sample', probe)
        record['journal'] += ran['journal']
        text = (ran['stdout'] + ran['stderr']).decode('utf-8', errors='replace')
        if ran['timed_out'] or ran['returncode'] != 0 or not output.is_file():
            return {'status': 'timed_out' if ran['timed_out'] else 'failed', 'returncode': ran['returncode'],
                    'output': bounded(text, 8000), 'yoda': None,
                    'findings': [{'check': 'sample_run', 'severity': 'error', 'object': self.routine,
                                  'message': 'the routine did not complete on the sample: ' + bounded(text, 2000)}]}
        try:
            objects = yoda_text.parse(output.read_text())
            found = rivet_sample_checks.findings(objects, self.routine, table_map=self.table_map, contract=self.contract,
                                                 booked=record['bookings']['booked'], tolerance=sample['tolerance'])
        except (ValueError, OSError) as problem:
            found = [{'check': 'sample_output', 'severity': 'error', 'object': str(output),
                      'message': f'unreadable sample output: {problem}'}]
        return {'status': 'completed', 'returncode': 0, 'output': bounded(text, 4000),
                'yoda': {'path': str(output), 'sha256': _file_sha(output)}, 'findings': found}


def result_of(record):
    """(returncode, text) of a check record in the upstream BuildResult convention."""
    text = record['compile']['output']
    if record['compile']['status'] != 'passed':
        return (record['compile']['returncode'] if record['compile']['returncode'] else 1), text
    registration = record['registration']
    if registration is not None and registration['status'] != 'passed':
        names = ', '.join(registration.get('registered_names') or []) or 'none'
        return 1, (text + f"\nrivet-build succeeded, but the built plugin does not register the routine "
                          f"'{record['routine']}' (registered: {names}). {registration['message']}")
    return 0, text


def retained(construction_dir):
    """Retained check records of a construction, keyed by draft SHA-256 (read only)."""
    records = {}
    for path in sorted((Path(construction_dir) / 'checks').glob('probe-*/record.json')):
        record = json.loads(path.read_text())
        if record.get('kind') != 'agentrivet-construction-check':
            raise ValueError('retained construction check record is malformed')
        source = Path(record['source']['path'])
        if not source.is_file() or _file_sha(source) != record['source']['sha256']:
            raise ValueError('retained construction check source changed')
        records[record['source']['sha256']] = record
    return records


def summary(record):
    """Compact text-bearing view of a check record for a role brief or a repair prompt."""
    if record is None:
        return None
    view = {'probe': record['probe'], 'source_sha256': record['source']['sha256'],
            'compile': {k: record['compile'][k] for k in ('status', 'returncode', 'diagnostics', 'output')},
            'booking_findings': record['bookings']['findings']}
    if record['registration'] is not None:
        view['registration'] = record['registration']
    if record['sample'] is not None:
        view['sample'] = {k: record['sample'][k] for k in ('status', 'findings')}
    return view


def failure_text(record):
    """Plain text of what a check found wrong with a draft, or '' when nothing failed."""
    if record is None:
        return ''
    lines = []
    if record['compile']['status'] != 'passed':
        lines.append(f"rivet-build {record['compile']['status']} (exit {record['compile']['returncode']}):")
        lines.append(record['compile']['output'])
    elif record['registration'] is not None and record['registration']['status'] != 'passed':
        lines.append(f"The plugin compiled but does not register '{record['routine']}': {record['registration']['message']}")
    for finding in record['bookings']['findings']:
        lines.append(f"[{finding['severity']}] {finding['check']}: {finding['message']}")
    if record['sample'] is not None:
        for finding in record['sample']['findings']:
            if finding['severity'] in ('error', 'warning'):
                lines.append(f"[{finding['severity']}] {finding['check']}: {finding['message']}")
    return '\n'.join(lines)
