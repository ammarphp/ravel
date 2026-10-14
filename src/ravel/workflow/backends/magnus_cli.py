"""Magnus backend: drive a user-installed ``magnus`` CLI as a separate process.

Magnus is AGPL-3.0. RAVEL never imports, vendors or copies it; this module only
runs the ``magnus`` executable that the user installed and configured. The CLI
reads its own credentials (``magnus login`` / its config file); RAVEL neither
sets, reads nor records a token, and redacts token-shaped text from every
client output it keeps.

Safety rules that differ from Magnus's own client defaults:

- Jobs are referenced by their absolute id only. Negative indices are refused.
- Each observation is checked against the handle (blueprint and RAVEL tag), so a
  job of another user or agent in a shared list is never adopted.
- Any action text a job returns is data. Only the exact line
  ``magnus receive magnus-secret:<id> --output <relative path>`` is honoured, and
  RAVEL runs that receive itself into a fresh staging path. Nothing else runs.
- Magnus local mode does not enforce CPU or memory limits. A plan for a local
  station must say so explicitly (``site.unenforced_limits_accepted``).

CLI verbs follow the documented Magnus SDK commands. A site whose CLI differs
can override them in ``site.verbs``; the override is part of the plan digest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

from ravel.workflow import execution_backend as eb

DEFAULT_VERBS = {
    'version': ['--version'],
    'config': ['config'],
    'submit': ['submit', '{blueprint}', '--'],
    'status': ['status', '{job}'],
    'logs': ['logs', '{job}'],
    'result': ['job', 'result', '{job}'],
    'kill': ['kill', '{job}'],
    'jobs': ['jobs'],
    'receive': ['receive', '{secret}', '--output', '{target}'],
}
_JOB_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{3,127}$')
_SUBMITTED = re.compile(r'(?im)^\s*(?:\[magnus\]\s*)?job\s+(?:submitted|id)\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9_-]{3,127})\s*$')
_RECEIVE = re.compile(r'^magnus receive (magnus-secret:[A-Za-z0-9_-]{3,128}) --output (\S+)$')
STATE_MAP = {
    'queued': 'pending', 'pending': 'pending', 'waiting': 'pending', 'preparing': 'pending', 'paused': 'pending',
    'running': 'running', 'executing': 'running',
    'completed': 'succeeded', 'success': 'succeeded', 'succeeded': 'succeeded', 'done': 'succeeded', 'finished': 'succeeded',
    'failed': 'failed', 'error': 'failed', 'terminated': 'cancelled', 'killed': 'cancelled', 'cancelled': 'cancelled',
    'canceled': 'cancelled',
}


def resolve_cli(path=None):
    resolved = path or shutil.which('magnus')
    if not resolved or not Path(resolved).is_file():
        raise ValueError('magnus CLI not found; install magnus-sdk in its own environment and pass site.cli')
    resolved = Path(resolved).resolve()
    return {'path': str(resolved), 'sha256': eb.file_sha256(resolved)}


def parse_action(text):
    """Return (receives, ignored_lines) from job action text, treated as data."""
    receives, ignored = [], []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = _RECEIVE.fullmatch(line)
        if match:
            target = match.group(2)
            try:
                eb._relative(target, 'receive output')
            except ValueError:
                ignored.append(line)
                continue
            receives.append({'secret': match.group(1), 'output': target})
        else:
            ignored.append(line)
    return receives, [eb.redact(line) for line in ignored]


def job_id(value):
    if not isinstance(value, str) or not _JOB_ID.fullmatch(value) or value.lstrip('-').isdigit() and value.startswith('-'):
        raise ValueError(f'magnus job reference {value!r} is not an absolute job id')
    return value


def _verb(plan, name, **values):
    verbs = {**DEFAULT_VERBS, **plan['spec'].get('site', {}).get('verbs', {})}
    return [part.format(**values) for part in verbs[name]]


class MagnusBackend(eb.Backend):
    kind = 'magnus'
    local = False

    def validate(self, spec):
        site = spec.get('site')
        if not isinstance(site, dict):
            raise ValueError('magnus backend needs a site block with the blueprint id')
        eb._keys(site, ('blueprint',), ('cli', 'station', 'mode', 'arguments', 'file_arguments', 'tag_argument',
                                        'verbs', 'unenforced_limits_accepted'), 'magnus site')
        if not isinstance(site['blueprint'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', site['blueprint']):
            raise ValueError('magnus blueprint id must be a plain identifier')
        mode = site.get('mode', 'remote')
        if mode not in ('remote', 'local'):
            raise ValueError('magnus site mode must be remote or local')
        if mode == 'local' and site.get('unenforced_limits_accepted') is not True:
            raise ValueError('Magnus local mode does not enforce CPU or memory limits; set '
                             'site.unenforced_limits_accepted true to accept that, or use oci-local')
        arguments = site.get('arguments', {})
        if not isinstance(arguments, dict) or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', k) or not isinstance(v, (str, int, float, bool))
                                                  for k, v in arguments.items()):
            raise ValueError('magnus blueprint arguments must be simple named scalars')
        for name in site.get('file_arguments', {}):
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name):
                raise ValueError('magnus file argument names must be plain identifiers')
        if any(isinstance(v, str) and re.search(r'(?i)latest|:HEAD\b|^HEAD$', v) for v in arguments.values()):
            raise ValueError('magnus arguments must not request mutable images or HEAD commits')
        if 'verbs' in site:
            if not isinstance(site['verbs'], dict) or set(site['verbs']) - set(DEFAULT_VERBS):
                raise ValueError('unknown magnus verb override')
        tag_argument = site.get('tag_argument', 'ravel_tag')
        if tag_argument is not None and not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', tag_argument):
            raise ValueError('magnus tag_argument must be a plain identifier or null')
        return spec

    def is_local(self, spec):
        return (spec.get('site') or {}).get('mode', 'remote') == 'local'

    def describe(self, spec):
        site = spec['site']
        cli = resolve_cli(site.get('cli'))
        version = subprocess.run([cli['path'], *DEFAULT_VERBS['version']], capture_output=True, text=True, timeout=60)
        return {'kind': self.kind, 'local': site.get('mode', 'remote') == 'local', 'cli': cli,
                'cli_version': eb.redact(version.stdout.strip())[:200], 'station': site.get('station'),
                'blueprint': site['blueprint'], 'mode': site.get('mode', 'remote'),
                'limits_enforced': site.get('mode', 'remote') == 'remote'}

    def doctor(self):
        try:
            cli = resolve_cli()
        except ValueError as exc:
            return {'backend': self.kind, 'ready': False, 'checks': [{'name': 'cli', 'ok': False, 'detail': str(exc)}]}
        checks = [{'name': 'cli', 'ok': True, 'detail': cli['path']}]
        version = subprocess.run([cli['path'], '--version'], capture_output=True, text=True, timeout=60)
        checks.append({'name': 'version', 'ok': version.returncode == 0, 'detail': eb.redact(version.stdout.strip())})
        config = subprocess.run([cli['path'], 'config'], capture_output=True, text=True, timeout=60)
        checks.append({'name': 'configured site', 'ok': config.returncode == 0,
                       'detail': eb.redact(config.stdout.strip())[:400] or 'run `magnus login` to configure a site'})
        configured = Path.home() / '.magnus/config.json'
        checks.append({'name': 'credential file', 'ok': configured.is_file() or bool(os.environ.get('MAGNUS_ADDRESS')),
                       'detail': ('present (not read)' if configured.is_file() else 'absent; run `magnus login`')})
        return {'backend': self.kind, 'ready': all(c['ok'] for c in checks), 'checks': checks}

    # -- client
    def _call(self, plan, handle, arguments, *, check=True, timeout=300):
        cli = plan['backend']['cli']
        if eb.file_sha256(cli['path']) != cli['sha256']:
            raise ValueError('magnus CLI bytes changed since the plan was prepared')
        argv = [cli['path'], *arguments]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        row = {'argv': [eb.redact(a) for a in argv], 'returncode': proc.returncode, 'utc': eb.utc_now(),
               'stdout': eb.redact(proc.stdout)[-20000:], 'stderr': eb.redact(proc.stderr)[-20000:]}
        journal = Path(handle['attempt_dir']) / 'magnus-client.jsonl'
        with journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
        if check and proc.returncode:
            raise ValueError(f'magnus {arguments[0]} failed with exit {proc.returncode}: {row["stderr"][-300:]}')
        return proc

    def submit_arguments(self, plan, handle):
        spec, site = plan['spec'], plan['spec']['site']
        arguments = _verb(plan, 'submit', blueprint=site['blueprint'])
        params = dict(site.get('arguments', {}))
        if site.get('tag_argument', 'ravel_tag'):
            params[site.get('tag_argument', 'ravel_tag')] = handle['tag']
        for name, path in site.get('file_arguments', {}).items():
            fact = next((f for f in plan['inputs'] if f['path'] == str(Path(path).resolve())), None)
            if fact is None:
                raise ValueError(f'magnus file argument {name} must be a declared, pinned input')
            params[name] = fact['path']
        for name, value in sorted(params.items()):
            arguments += [f'--{name}', str(value).lower() if isinstance(value, bool) else str(value)]
        return arguments

    def submit(self, plan, handle):
        Path(handle['job_dir']).mkdir(parents=True, exist_ok=True)
        proc = self._call(plan, handle, self.submit_arguments(plan, handle))
        identifier = None
        try:
            document = json.loads(proc.stdout)
            identifier = document.get('job_id') or document.get('id') if isinstance(document, dict) else None
        except json.JSONDecodeError:
            match = _SUBMITTED.search(proc.stdout)
            identifier = match.group(1) if match else None
        if identifier is None:
            raise ValueError('magnus submit did not report a job id')
        return {'job_id': job_id(identifier), 'blueprint': plan['spec']['site']['blueprint']}

    def _status_document(self, plan, handle, identifier):
        proc = self._call(plan, handle, _verb(plan, 'status', job=job_id(identifier)), check=False)
        if proc.returncode:
            return None
        try:
            document = json.loads(proc.stdout)
        except json.JSONDecodeError:
            text = proc.stdout.strip().lower()
            word = next((w for w in STATE_MAP if re.search(rf'\b{w}\b', text)), None)
            return {'status': word, 'raw': eb.redact(proc.stdout.strip())[:400]}
        return document if isinstance(document, dict) else None

    def _verify_owner(self, plan, handle, document):
        site = plan['spec']['site']
        blueprint = document.get('blueprint') or document.get('blueprint_id')
        if blueprint is not None and blueprint != site['blueprint']:
            raise ValueError('observed magnus job runs a different blueprint; refusing to adopt it')
        tag_argument = site.get('tag_argument', 'ravel_tag')
        names = ' '.join(str(document.get(k, '')) for k in ('task_name', 'description', 'name', 'args', 'arguments'))
        if tag_argument and any(document.get(k) for k in ('task_name', 'description', 'name', 'args', 'arguments')) \
                and handle['tag'] not in names:
            raise ValueError('observed magnus job does not carry this handle tag; refusing to adopt it')

    def observe(self, plan, handle):
        identifier = handle['remote']['job_id']
        document = self._status_document(plan, handle, identifier)
        if document is None:
            return {'state': 'unknown', 'exit_code': None, 'detail': 'status unavailable (station unreachable?)'}
        self._verify_owner(plan, handle, document)
        raw = str(document.get('status') or document.get('state') or '').lower()
        state = STATE_MAP.get(raw, 'unknown')
        if state == 'succeeded':
            result = self._result(plan, handle)
            if result.get('success') is not True:
                return {'state': 'failed', 'exit_code': None,
                        'detail': 'job completed but its result reports success=false: ' + str(result.get('message', ''))[:300]}
        if state == 'cancelled' and not handle.get('cancel_requested'):
            state = 'failed'
        return {'state': state, 'exit_code': 0 if state == 'succeeded' else None, 'detail': raw}

    def _result(self, plan, handle):
        proc = self._call(plan, handle, _verb(plan, 'result', job=job_id(handle['remote']['job_id'])))
        try:
            document = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError('magnus job result is not JSON') from exc
        if not isinstance(document, dict):
            raise ValueError('magnus job result must be a JSON object')
        return document

    def logs(self, plan, handle):
        return self._call(plan, handle, _verb(plan, 'logs', job=job_id(handle['remote']['job_id'])), check=False).stdout

    def cancel(self, plan, handle):
        self._call(plan, handle, _verb(plan, 'kill', job=job_id(handle['remote']['job_id'])))

    def find(self, plan, handle):
        site = plan['spec']['site']
        if not site.get('tag_argument', 'ravel_tag'):
            return None
        proc = self._call(plan, handle, _verb(plan, 'jobs'), check=False)
        try:
            rows = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise ValueError('magnus jobs listing is not JSON; recover this job manually by its id')
        matches = [r for r in rows if isinstance(r, dict) and handle['tag'] in json.dumps(r)
                   and (r.get('blueprint') in (None, site['blueprint']))]
        if len(matches) > 1:
            raise ValueError('more than one magnus job carries this tag; refusing to choose')
        if not matches:
            return None
        return {'job_id': job_id(str(matches[0].get('id') or matches[0].get('job_id'))), 'blueprint': site['blueprint']}

    def retrieve(self, plan, handle, staging):
        result = self._result(plan, handle)
        receives, ignored = parse_action(result.get('action') or result.get('magnus_action') or '')
        record = {'receives': receives, 'ignored_action_lines': ignored, 'message': eb.redact(str(result.get('message', '')))[:2000]}
        eb.atomic_json(Path(handle['attempt_dir']) / 'magnus-result.json', record)
        for item in receives:
            target = staging / item['output']
            if target.exists():
                raise ValueError(f"receive target {item['output']} already exists in staging")
            target.parent.mkdir(parents=True, exist_ok=True)
            self._call(plan, handle, _verb(plan, 'receive', secret=item['secret'], target=str(target)), timeout=6 * 3600)
        # Declared outputs are named relative to the staging root; a single
        # receive directory may also hold them directly.
        if len(receives) == 1:
            root = staging / receives[0]['output']
            for row in plan['spec']['outputs']:
                if 'destination' in row and not (staging / row['name']).exists() and (root / row['name']).exists():
                    (staging / row['name']).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(root / row['name']), str(staging / row['name']))


def blueprint_yaml(plan):
    """Generic RAVEL stage blueprint for a Magnus operator to register (data only).

    The blueprint runs the plan's pinned image and argv; it installs nothing at
    run time and takes the RAVEL tag so jobs can be recovered by tag.
    """
    spec = plan['spec']
    if 'image' not in spec or 'reference' not in spec['image']:
        raise ValueError('a Magnus blueprint needs an image pinned by registry digest')
    source = spec.get('source')
    argv = json.dumps(spec['argv'])
    lines = [
        f"id: ravel-stage-{plan['plan_sha256'][:12]}",
        f"title: RAVEL stage {spec['stage']}",
        'description: Runs one pinned RAVEL stage plan (image digest, commit and argv fixed by the plan).',
        'code: |',
        '  Tag = Annotated[str, {"description": "RAVEL handle tag used for recovery"}]',
        '',
        '  def blueprint(ravel_tag: Tag):',
        '      import json, shlex',
        f'      argv = json.loads({argv!r})',
        '      submit_job(',
        '          task_name="[ravel] " + ravel_tag,',
        f'          description="RAVEL plan {plan["plan_sha256"]}",',
    ]
    if source:
        lines += [f'          repo_name={source["repository"]!r},', f'          commit_sha={source["commit"]!r},']
    lines += [
        '          entry_command=" ".join(shlex.quote(a) for a in argv),',
        f'          container_image={("docker://" + spec["image"]["reference"])!r},',
        f'          cpu_count={spec["resources"]["cpus"]},',
        f'          memory_demand="{spec["resources"]["memory_mib"]}M",',
        '      )',
        '',
    ]
    return '\n'.join(lines)
