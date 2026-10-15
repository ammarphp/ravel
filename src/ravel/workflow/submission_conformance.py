"""Offline, read-only conformance checks selected by a requester-supplied rule pack.

No policy population ships here. Supplied records establish documentary
conformance, not the authenticity or completeness of the producing systems.
Only fixed git inspection commands and pdfinfo can be executed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlsplit

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

GIT = '/usr/bin/git' if Path('/usr/bin/git').is_file() else 'git'
SHA256 = re.compile(r'[0-9a-f]{64}')
# Required and allowed parameters; schema generation and validation share this contract.
PARAMETERS = {
    'instruction_hash': ({'path', 'sha256'}, {'path': 'text', 'sha256': 'digest'}),
    'session_instructions': ({'path', 'sha256'}, {'path': 'text', 'sha256': 'digest', 'receipt_field': 'text'}),
    'prompt_log': ({'path'}, {'path': 'text'}),
    'workflow_launches': ({'stages', 'receipts', 'guard_log', 'policy_sha256', 'manager'},
        {'stages': 'text', 'receipts': 'text', 'guard_log': 'text', 'policy_sha256': 'digest', 'manager': 'text'}),
    'tracked_clean': ({'paths'}, {'paths': 'paths'}),
    'environment': ({'stages', 'runtime_directory', 'requirements', 'installability'},
        {'stages': 'text', 'runtime_directory': 'text', 'requirements': 'text', 'installability': 'text',
         'vendored_ravel': 'text'}),
    'skill_coverage': ({'invoked', 'coverage'}, {'invoked': 'text', 'coverage': 'text'}),
    'rerun_comparison': ({'workflow', 'tolerances'}, {'workflow': 'text', 'tolerances': 'text'}),
    'size_budget': ({'max_file_bytes'}, {'max_file_bytes': 'positive', 'max_total_bytes': 'positive',
                                      'intermediates': 'text'}),
    'note_limits': ({'pdf', 'aux', 'segments', 'max_main_pages'},
        {'pdf': 'text', 'aux': 'text', 'segments': 'text', 'max_main_pages': 'positive'}),
    'submission_tag': ({'tag'}, {'tag': 'text'}),
}
FIX_HINTS = {
    'instruction_hash': 'Restore the declared instruction bytes or supply the correct reviewed upstream hash.',
    'session_instructions': 'Supply the declared document-hash receipt for every prompt row.',
    'prompt_log': 'Rebuild the complete prompt audit with full text, exact model builds, timestamps and token counts.',
    'workflow_launches': 'Supply complete stage-attempt, manager-launch and policy-bound guard records; resolve unauthorized launches.',
    'tracked_clean': 'Track the referenced files at HEAD and reconcile their index, bytes and executable modes.',
    'environment': 'Supply matching executed-stage runtime records, exact requirements and pinned public or vendored distribution evidence.',
    'skill_coverage': 'Supply the complete invoked-software census and a clean, tracked skill for each item.',
    'rerun_comparison': 'Declare the final quantity-comparison rule and its nonempty tolerances file.',
    'size_budget': 'Move oversized intermediates to declared storage with checksums or revise the supplied byte budget.',
    'note_limits': 'Provide the built PDF, physical section boundaries and pdfinfo; keep main text within the declared limit.',
    'submission_tag': 'Have the repository owner supply the declared tag pointing at the reviewed HEAD.',
}


def _text(value):
    return type(value) is str and bool(value.strip()) and '\x00' not in value


def _digest(value):
    return type(value) is str and SHA256.fullmatch(value) is not None


def rule_pack_schema():
    """Return the portable schema, containing check definitions and no rule pack."""
    types = {
        'text': {'type': 'string', 'minLength': 1, 'pattern': r'^(?=[\s\S]*\S)[^\u0000]*$'},
        'digest': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        'positive': {'type': 'integer', 'minimum': 1},
        'paths': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                  'items': {'type': 'string', 'minLength': 1, 'pattern': r'^(?=[\s\S]*\S)[^\u0000]*$'}},
    }
    variants = []
    for check_name, (required, fields) in PARAMETERS.items():
        variants.append({'type': 'object', 'additionalProperties': False,
            'required': ['id', 'check', 'params'], 'properties': {
                'id': types['text'], 'check': {'const': check_name}, 'enabled': {'type': 'boolean'},
                'scope': {'enum': ['repo', 'runs']},
                'params': {'type': 'object', 'additionalProperties': False,
                           'required': sorted(required),
                           'properties': {k: types[t] for k, t in fields.items()}}}})
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
        'title': 'Requester-supplied conformance rule pack', 'type': 'object', 'additionalProperties': False,
        'required': ['schema_version', 'kind', 'rules'], 'properties': {
            'schema_version': {'const': 1}, 'kind': {'const': 'conformance-rule-pack'},
            'rundirs': {'type': 'array', 'uniqueItems': True, 'items': types['text']},
            'rules': {'type': 'array', 'minItems': 1, 'items': {'oneOf': variants}}},
        '$comment': 'Rule IDs must be unique; the runtime validator enforces this cross-row constraint.'}


def _strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON field: ' + key)
            value[key] = item
        return value
    def constant(_):
        raise ValueError('non-finite JSON value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def validate_rules(value):
    """Validate without importing a schema runtime or executing supplied code."""
    if (type(value) is not dict or set(value) - {'schema_version', 'kind', 'rules', 'rundirs'}
            or type(value.get('schema_version')) is not int or value['schema_version'] != 1
            or value.get('kind') != 'conformance-rule-pack'
            or type(value.get('rules')) is not list or not value['rules']):
        raise ValueError('version-one conformance rule pack with a nonempty rules list required')
    checks = {'text': _text, 'digest': _digest,
              'positive': lambda v: type(v) is int and v > 0,
              'paths': lambda v: type(v) is list and bool(v) and all(_text(x) for x in v)
                                and len(set(v)) == len(v)}
    if 'rundirs' in value:
        dirs = value['rundirs']
        if type(dirs) is not list or not all(_text(p) for p in dirs) or len(set(dirs)) != len(dirs):
            raise ValueError('distinct declared run directories required')
    seen = set()
    for row in value['rules']:
        if (type(row) is not dict or set(row) - {'id', 'check', 'params', 'enabled', 'scope'}
                or not _text(row.get('id')) or row['id'] in seen
                or type(row.get('check')) is not str or row['check'] not in PARAMETERS
                or type(row.get('enabled', True)) is not bool or row.get('scope', 'repo') not in ('repo', 'runs')):
            raise ValueError('distinct rule ID, known check, Boolean enabled and repo/runs scope required')
        seen.add(row['id'])
        required, fields = PARAMETERS[row['check']]
        params = row.get('params')
        if (type(params) is not dict or set(params) - set(fields) or not required <= set(params)
                or any(not checks[fields[k]](v) for k, v in params.items())):
            raise ValueError('invalid parameters for rule ' + row['id'])
    return value


def _git(root, *args, missing=False, stdin=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_LAZY_FETCH='1', GIT_ALLOW_PROTOCOL='', GIT_TERMINAL_PROMPT='0',
               GIT_NO_REPLACE_OBJECTS='1')
    done = subprocess.run([GIT, '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull,
                           '-C', str(root), *args], env=env, input=stdin, capture_output=True, timeout=30)
    if done.returncode:
        if missing:
            return None
        raise ValueError('git inspection failed: ' + done.stderr.decode('utf-8', 'replace').strip())
    return done.stdout


def _safe(root, relative):
    raw = Path(relative)
    if (not _text(relative) or raw.is_absolute() or '..' in raw.parts
            or not raw.parts or '.git' in raw.parts):
        raise ValueError('ordinary relative evidence path inside its declared scope required')
    path = root / raw
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('evidence must not traverse a symlink')
    if not path.resolve().is_relative_to(root):
        raise ValueError('evidence escaped its declared scope')
    return path


class _Result:
    def __init__(self):
        self.evidence = []
        self.failures = []
        self.missing = []

    def fail(self, detail, **facts):
        self.failures.append(detail)
        self.evidence.append({'detail': detail, **facts})

    def unavailable(self, detail, **facts):
        self.missing.append(detail)
        self.evidence.append({'detail': detail, **facts})

    @property
    def status(self):
        return 'FAIL' if self.failures else 'NOT-CHECKABLE' if self.missing else 'PASS'


class _Context:
    def __init__(self, repo):
        self.repo = Path(repo).resolve()
        top = _git(self.repo, 'rev-parse', '--show-toplevel').decode().strip()
        if Path(top).resolve() != self.repo:
            raise ValueError('--repo must name the git working-tree root')
        self.head = _git(self.repo, 'rev-parse', '--verify', 'HEAD').decode().strip()
        self.algorithm = _git(self.repo, 'rev-parse', '--show-object-format').decode().strip()
        self.files = {}
        for entry in _git(self.repo, 'ls-tree', '-rz', '--full-tree', self.head).split(b'\0'):
            if entry:
                header, name = entry.split(b'\t', 1)
                mode, kind, identity = header.decode().split()
                self.files[os.fsdecode(name)] = (mode, kind, identity)
        self.staged = set(map(os.fsdecode, filter(None, _git(self.repo, 'diff', '--cached',
                                      '--no-ext-diff', '--name-only', '-z', self.head, '--').split(b'\0'))))
        self.index = _git(self.repo, 'ls-files', '--stage', '-z')
        self.index_entries = []
        for entry in self.index.split(b'\0'):
            if entry:
                header, name = entry.split(b'\t', 1)
                mode, identity, stage = header.decode().split()
                self.index_entries.append((os.fsdecode(name), mode, identity, stage))
        self.references = set()
        self.pins = {}
        self.pin_roots = {}
        self.size_observations = {}

    def read(self, root, relative, result):
        try:
            path = _safe(root, relative)
            self.references.add(path)
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError('ordinary evidence file required')
            with path.open('rb') as stream:
                raw = stream.read()
            digest = hashlib.sha256(raw).hexdigest()
            if path in self.pins and self.pins[path] != digest:
                raise ValueError('evidence changed during inspection')
            self.pins[path] = digest
            self.pin_roots[path] = root
            result.evidence.append({'path': str(path), 'sha256': digest, 'bytes': len(raw)})
            return raw
        except FileNotFoundError:
            result.unavailable('missing evidence source', path=str(root / relative))
        except (OSError, ValueError) as exc:
            result.fail(str(exc), path=str(root / relative))
        return None

    def document(self, root, relative, result):
        raw = self.read(root, relative, result)
        if raw is None:
            return None
        try:
            return _strict_json(raw)
        except (ValueError, UnicodeError) as exc:
            result.fail('invalid JSON evidence: ' + str(exc), path=str(root / relative))
            return None

    def tracked(self, path, result):
        if not path.is_relative_to(self.repo):
            result.fail('referenced file is outside the git working tree', path=str(path))
            return
        relative = path.relative_to(self.repo).as_posix()
        entry = self.files.get(relative)
        if not entry or entry[0] not in ('100644', '100755') or entry[1] != 'blob':
            result.fail('ordinary file is not tracked at HEAD', path=relative)
            return
        raw = self.read(self.repo, relative, result)
        if raw is None:
            result.fail('tracked file is absent or unreadable', path=relative)
            return
        blob = hashlib.new(self.algorithm, b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        executable = bool(path.stat().st_mode & stat.S_IXUSR)
        if blob != entry[2] or relative in self.staged or executable != (entry[0] == '100755'):
            result.fail('referenced file differs from HEAD or the index is staged', path=relative)


def _rows(value, key, result, *, allow_empty=False):
    rows = value.get(key) if type(value) is dict else None
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        result.fail('evidence requires an object list', field=key)
        return None
    if not rows and not allow_empty:
        result.unavailable('evidence population is empty', field=key)
        return None
    return rows


def _stages(context, root, params, result):
    value = context.document(root, params['stages'], result)
    if value is None:
        return None
    if type(value) is dict and type(value.get('stages')) is dict:
        value = _ledger_stages(context, root, params['stages'], value, result)
        if value is None:
            return None
    rows = _rows(value, 'stages', result)
    if rows is None:
        return None
    seen, executed = set(), []
    for index, row in enumerate(rows, 1):
        key = (row.get('id'), row.get('attempt'))
        if (not all(_text(v) for v in key) or type(row.get('executed')) is not bool
                or key in seen):
            result.fail('distinct stage/attempt and explicit execution Boolean required', row=index)
            continue
        seen.add(key)
        if row['executed']:
            executed.append(key)
    if not executed:
        result.unavailable('no executed stage/attempt evidence')
    return executed


def _ledger_stages(context, root, path, ledger, result):
    """Inspect retained RAVEL attempts, including failed and superseded attempts."""
    if (type(ledger.get('schema_version')) is not int or ledger['schema_version'] != 1
            or type(ledger.get('revision')) is not int or ledger['revision'] < 0):
        result.fail('invalid version-one execution ledger')
        return None
    run = _safe(root, path).parent
    current = {}
    for name, record in ledger['stages'].items():
        if type(record) is not dict or record.get('stage') != name or not _text(record.get('attempt_id')):
            result.fail('execution ledger stage/attempt identity is invalid')
            continue
        current[(name, record['attempt_id'])] = record
    history = _safe(run, 'logs/execution')
    if not history.is_dir():
        result.unavailable('retained execution attempt directory is missing', path=str(history))
        return None
    attempts = {}
    for source in sorted(history.glob('*/*/record.json')):
        record = context.document(run, source.relative_to(run).as_posix(), result)
        if record is None:
            continue
        if type(record) is not dict:
            result.fail('retained execution attempt must be an object', path=str(source))
            continue
        key = (record.get('stage'), record.get('attempt_id'))
        if (not all(_text(v) for v in key) or key in attempts
                or key != (source.parent.parent.name, source.parent.name)
                or record.get('attempt_record') != source.relative_to(run).as_posix()
                or record.get('status') not in ('running', 'succeeded', 'failed', 'interrupted')):
            result.fail('retained execution attempt identity or status is invalid', path=str(source))
            continue
        attempts[key] = record
    for key, record in current.items():
        if key not in attempts:
            result.unavailable('current stage has no retained attempt record', stage=key[0], attempt=key[1])
        elif attempts[key] != record:
            result.fail('execution ledger differs from retained current attempt', stage=key[0], attempt=key[1])
    return {'stages': [{'id': stage, 'attempt': attempt, 'executed': True}
                       for stage, attempt in sorted(attempts)]}


def _instruction_hash(context, root, params, result):
    raw = context.read(root, params['path'], result)
    if raw is not None and hashlib.sha256(raw).hexdigest() != params['sha256']:
        result.fail('instruction document differs from supplied upstream hash', expected_sha256=params['sha256'])


def _session_instructions(context, root, params, result):
    value = context.document(root, params['path'], result)
    if value is None:
        return
    rows = _rows(value, 'records', result)
    if rows is not None:
        field = params.get('receipt_field', 'instruction_sha256')
        for index, row in enumerate(rows, 1):
            if row.get(field) != params['sha256']:
                result.fail('prompt row lacks the declared instruction receipt', row=index, field=field)


def _prompt_log(context, root, params, result):
    value = context.document(root, params['path'], result)
    if value is None:
        return
    rows = _rows(value, 'records', result)
    if type(value) is dict and 'gaps' not in value:
        result.unavailable('missing prompt-log build gap census', field='gaps')
    elif type(value) is dict and (type(value['gaps']) is not list or value['gaps']):
        result.fail('prompt-log build has gaps or an invalid gap census')
    if rows is None:
        return
    keys = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens', 'output_tokens', 'total_tokens')
    for index, row in enumerate(rows, 1):
        for field in ('prompt', 'model', 'timestamp'):
            if not _text(row.get(field)):
                result.fail('prompt row lacks required full text or metadata', row=index, field=field)
        if _text(row.get('timestamp')):
            try:
                stamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                if stamp.utcoffset() is None:
                    raise ValueError('timezone required')
            except ValueError:
                result.fail('prompt timestamp is not a timezone-qualified ISO timestamp', row=index)
        if row.get('model_build_exact') is not True:
            result.unavailable('exact model-build evidence missing or inexact', row=index, field='model_build_exact')
        usage = row.get('usage')
        if (row.get('usage_reported') is not True or type(usage) is not dict
                or any(type(usage.get(k)) is not int or usage[k] < 0 for k in keys)):
            result.fail('prompt row lacks complete nonnegative token accounting', row=index)
        elif (usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']
              or usage['cached_input_tokens'] + usage['cache_creation_input_tokens'] > usage['input_tokens']):
            result.fail('prompt token accounting is inconsistent', row=index)


def _workflow_launches(context, root, params, result):
    stages = _stages(context, root, params, result)
    value = context.document(root, params['receipts'], result)
    receipts = _rows(value, 'receipts', result, allow_empty=True) if value is not None else None
    guard = context.document(root, params['guard_log'], result)
    if receipts is not None:
        keys = []
        for index, receipt in enumerate(receipts, 1):
            key = (receipt.get('stage'), receipt.get('attempt'))
            if not all(_text(v) for v in key):
                result.fail('launch receipt lacks stage/attempt identity', row=index)
                continue
            keys.append(key)
            if receipt.get('manager') != params['manager']:
                result.fail('direct or undeclared-manager launch receipt present', row=index)
            if receipt.get('policy_sha256') != params['policy_sha256']:
                result.fail('launch receipt lacks the declared policy commitment', row=index)
        if len(keys) != len(set(keys)):
            result.fail('duplicate stage/attempt launch receipts')
        if stages is not None:
            for stage, attempt in sorted(set(stages) - set(keys)):
                result.fail('executed stage has no workflow-manager launch receipt', stage=stage, attempt=attempt)
            for stage, attempt in sorted(set(keys) - set(stages)):
                result.fail('launch receipt is outside the declared executed population', stage=stage, attempt=attempt)
    if guard is not None:
        if type(guard) is not dict:
            result.fail('guard record must be an object')
            return
        if guard.get('complete') is not True:
            result.unavailable('guard command census is not declared complete')
        if guard.get('policy_sha256') != params['policy_sha256']:
            result.fail('guard log policy differs from declared policy')
        commands = _rows(guard, 'commands', result)
        if commands is not None:
            for index, row in enumerate(commands, 1):
                if type(row.get('allowed')) is not bool or type(row.get('within_policy')) is not bool:
                    result.fail('guard command lacks explicit policy decision', row=index)
                elif row['allowed'] and not row['within_policy']:
                    result.fail('guard allowed a command outside policy', row=index)


def _tracked_clean(context, root, params, result):
    paths = set(context.references)
    for value in params['paths']:
        try:
            paths.add(_safe(root, value))
        except ValueError as exc:
            result.fail(str(exc), path=value)
    for path in sorted(paths):
        context.tracked(path, result)


def _public_url(value):
    if not _text(value):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and bool(url.hostname) and '.' in url.hostname
                and url.hostname not in ('localhost', '127.0.0.1') and not url.username and not url.password)
    except ValueError:
        return False


def _environment(context, root, params, result):
    stages = _stages(context, root, params, result)
    runtimes = {}
    try:
        folder = _safe(root, params['runtime_directory'])
        if not folder.is_dir():
            result.unavailable('runtime environment directory is missing', path=str(folder))
        else:
            for path in sorted(folder.glob('*.json')):
                value = context.document(root, path.relative_to(root).as_posix(), result)
                if value is None:
                    continue
                try:
                    from .env_snapshot import snapshot_id
                    if type(value) is not dict or value.get('snapshot_id') != snapshot_id(value):
                        raise ValueError('runtime snapshot content identity differs')
                    key = (value.get('stage'), value.get('attempt'))
                    if not all(_text(v) for v in key) or key in runtimes:
                        raise ValueError('distinct runtime stage/attempt identity required')
                    if path.name != f'{key[0]}-{key[1]}.json':
                        raise ValueError('runtime filename differs from stage/attempt')
                    if not all(type(value.get(k)) is dict and value[k] for k in ('python', 'platform')):
                        raise ValueError('runtime Python and platform records required')
                    runtimes[key] = value
                except (ValueError, KeyError, TypeError) as exc:
                    result.fail('invalid runtime environment: ' + str(exc), path=str(path))
            if stages is not None:
                for stage, attempt in sorted(set(stages) - set(runtimes)):
                    result.unavailable('executed stage runtime record is missing', stage=stage, attempt=attempt,
                                       path=str(folder / f'{stage}-{attempt}.json'))
    except (OSError, ValueError) as exc:
        result.fail(str(exc), path=params['runtime_directory'])
    raw = context.read(root, params['requirements'], result)
    availability = context.document(root, params['installability'], result)
    rows = _rows(availability, 'distributions', result, allow_empty=True) if availability is not None else None
    sources = {}
    if rows is not None:
        for index, row in enumerate(rows, 1):
            if not _text(row.get('name')) or not _text(row.get('version')):
                result.fail('installability row lacks distribution/version', row=index)
                continue
            key = (canonicalize_name(row['name']), row['version'])
            if key in sources:
                result.fail('duplicate installability evidence', row=index)
            sources[key] = row
    pins = set()
    if raw is not None:
        try:
            text = raw.decode('utf-8').replace('\\\n', ' ')
            for number, line in enumerate(text.splitlines(), 1):
                line = line.split(' #', 1)[0].strip()
                if not line or line.startswith('#'):
                    continue
                line = re.sub(r'\s+--hash=sha256:[0-9a-f]{64}', '', line)
                try:
                    requirement = Requirement(line)
                    specs = list(requirement.specifier)
                    if len(specs) != 1 or specs[0].operator != '==' or '*' in specs[0].version or requirement.url:
                        raise ValueError('one exact distribution version required')
                except ValueError:
                    result.fail('requirements line is not an exact named distribution pin', line=number)
                    continue
                key = (canonicalize_name(requirement.name), specs[0].version)
                pins.add(key)
                row = sources.get(key)
                if row is None:
                    result.unavailable('public installability evidence missing for pinned distribution',
                                       distribution=key[0], version=key[1])
                elif row.get('public') is True and _public_url(row.get('url')) and _digest(row.get('sha256')):
                    pass  # Documentary evidence supplied at run time; no live network claim.
                elif 'vendored' in row:
                    vendor = context.read(root, row['vendored'], result) if _text(row['vendored']) else None
                    if vendor is None or not _digest(row.get('sha256')) or hashlib.sha256(vendor).hexdigest() != row['sha256']:
                        result.fail('vendored distribution copy is absent or differs from checksum', distribution=key[0])
                    if key[0] in ('ravel', 'ravel-hep') and 'vendored_ravel' not in params:
                        result.fail('vendored RAVEL requires a LICENSE and NOTICE directory declaration')
                elif (type(row.get('public_tag')) is dict and _public_url(row['public_tag'].get('url'))
                      and _text(row['public_tag'].get('tag')) and _digest(row['public_tag'].get('sha256'))):
                    pass
                elif row.get('public') is False:
                    result.fail('pinned distribution is not publicly installable and has no pinned replacement',
                                distribution=key[0], version=key[1])
                else:
                    result.unavailable('installability record lacks a pinned public source', distribution=key[0], version=key[1])
            if not pins:
                result.unavailable('requirements contain no exact distribution pins')
        except UnicodeError:
            result.fail('requirements must be UTF-8 text')
    for stage, attempt in stages or []:
        if (stage, attempt) not in runtimes:
            continue
        for package in runtimes[(stage, attempt)]['packages']:
            key = (canonicalize_name(package['name']), package['version'])
            if key[0] not in ('ravel', 'ravel-hep') and key not in pins:
                result.fail('executed runtime distribution is not pinned in requirements',
                            stage=stage, attempt=attempt, distribution=key[0], version=key[1])
    if 'vendored_ravel' in params:
        for name in ('LICENSE', 'NOTICE'):
            raw = context.read(root, str(Path(params['vendored_ravel']) / name), result)
            if raw is None or not raw.strip():
                result.fail('vendored RAVEL requires nonempty LICENSE and NOTICE', file=name)


def _skill_coverage(context, root, params, result):
    invoked = context.document(root, params['invoked'], result)
    coverage = context.document(root, params['coverage'], result)
    rows = _rows(coverage, 'skills', result, allow_empty=True) if coverage is not None else None
    population = set()
    if invoked is not None:
        for field, kind in (('executables', 'executable'), ('distributions', 'distribution')):
            names = invoked.get(field) if type(invoked) is dict else None
            if type(names) is not list or not all(_text(name) for name in names):
                result.fail('invoked software census requires name lists', field=field)
                continue
            population.update((kind, canonicalize_name(name) if kind == 'distribution' else name) for name in names)
        if not population:
            result.unavailable('invoked software census is empty')
    covered = {}
    for index, row in enumerate(rows or [], 1):
        if row.get('kind') not in ('executable', 'distribution') or not _text(row.get('name')) or not _text(row.get('path')):
            result.fail('skill mapping requires kind, software name and tracked path', row=index)
            continue
        name = canonicalize_name(row['name']) if row['kind'] == 'distribution' else row['name']
        key = (row['kind'], name)
        if key in covered:
            result.fail('duplicate software skill mapping', row=index)
        covered[key] = row['path']
    if rows is not None:
        for key in sorted(population):
            if key not in covered:
                result.fail('invoked software has no declared skill', kind=key[0], software=key[1])
                continue
            raw = context.read(root, covered[key], result)
            if raw is not None:
                if not raw.strip():
                    result.fail('software skill is empty', software=key[1])
            context.tracked(_safe(root, covered[key]), result)


def _rerun_comparison(context, root, params, result):
    value = context.document(root, params['workflow'], result)
    tolerance = context.document(root, params['tolerances'], result)
    if value is not None:
        rows = _rows(value, 'rules', result, allow_empty=True)
        if rows is not None and (not rows or rows[-1].get('kind') != 'quantity-comparison'
                                or rows[-1].get('tolerances') != params['tolerances']):
            result.fail('last declared workflow rule is not a quantity comparison with the supplied tolerances')
    if tolerance is not None and (type(tolerance) is not dict or not tolerance):
        result.fail('nonempty declared tolerances object required')


def _size_budget(context, root, params, result):
    totals = defaultdict(int)
    versions = defaultdict(list)
    modes = defaultdict(set)
    for relative, (mode, _, identity) in context.files.items():
        versions[relative].append(identity)
        modes[relative].add(mode)
    for relative, mode, identity, stage in context.index_entries:
        versions[relative].append(identity)
        modes[relative].add(mode)
        if stage != '0':
            result.fail('index has unmerged tracked content', path=relative)
    # Submodule commits live in another repository; their identities are not local blobs.
    identities = sorted({identity for relative, values in versions.items() if modes[relative] != {'160000'}
                         for identity in values})
    raw = _git(context.repo, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
               stdin=''.join(identity + '\n' for identity in identities).encode())
    sizes = {}
    for line in raw.decode().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == 'blob':
            sizes[fields[0]] = int(fields[2])
    for relative, identities in sorted(versions.items()):
        try:
            if modes[relative] <= {'120000', '160000'}:
                # Links and submodules are measured from recorded objects and never followed.
                path = context.repo / relative
                if '/' in relative:
                    _safe(context.repo, Path(relative).parent.as_posix())
                if '120000' in modes[relative] and not path.is_symlink():
                    result.fail('tracked symbolic link differs from its recorded type', path=relative)
                    continue
                size = max((sizes[i] for i in identities if i in sizes), default=0)
                totals[relative.split('/')[0] if '/' in relative else '.'] += size
                if size > params['max_file_bytes']:
                    result.fail('tracked file exceeds declared byte ceiling', path=relative, bytes=size,
                                max_file_bytes=params['max_file_bytes'])
                continue
            path = _safe(context.repo, relative)
            if any(identity not in sizes for identity in identities) or not path.is_file():
                result.fail('tracked file is absent or not an ordinary blob', path=relative)
                continue
            observed = path.stat()
            context.size_observations[path] = (observed.st_size, observed.st_mtime_ns, observed.st_mode, observed.st_ino)
            size = max(observed.st_size, *(sizes[identity] for identity in identities))
            totals[relative.split('/')[0] if '/' in relative else '.'] += size
            if size > params['max_file_bytes']:
                result.fail('tracked file exceeds declared byte ceiling', path=relative, bytes=size,
                            max_file_bytes=params['max_file_bytes'])
        except (OSError, ValueError) as exc:
            result.fail(str(exc), path=relative)
    result.evidence.append({'folder_bytes': dict(sorted(totals.items())), 'total_bytes': sum(totals.values()),
                            'basis': 'maximum file bytes across HEAD, index and working tree'})
    if 'max_total_bytes' in params and sum(totals.values()) > params['max_total_bytes']:
        result.fail('tracked working-tree total exceeds declared byte ceiling', max_total_bytes=params['max_total_bytes'])
    if 'intermediates' in params:
        value = context.document(root, params['intermediates'], result)
        if value is not None:
            rows = _rows(value, 'artifacts', result, allow_empty=True)
            for index, row in enumerate(rows or [], 1):
                if not _digest(row.get('sha256')) or not _text(row.get('storage_path')):
                    result.fail('intermediate requires checksum and storage path', row=index)
                if 'path' in row and row['path'] in context.files:
                    result.fail('referenced intermediate is committed', row=index, path=row['path'])


def _note_limits(context, root, params, result):
    pdf = context.read(root, params['pdf'], result)
    aux = context.read(root, params['aux'], result)
    segments = context.document(root, params['segments'], result)
    executable = shutil.which('pdfinfo')
    if executable is None:
        result.unavailable('pdfinfo executable is missing', source='pdfinfo')
    if pdf is None or aux is None or segments is None or executable is None:
        return
    try:
        done = subprocess.run([executable, '-isodates', str(_safe(root, params['pdf']))],
                              capture_output=True, text=True, timeout=30)
        if done.returncode:
            result.fail('pdfinfo failed to read the built PDF', exit_code=done.returncode)
            return
        from ravel.physics.manuscript_build import page_census
        census = page_census(done.stdout, aux.decode('utf-8'), max_main_pages=params['max_main_pages'], segments=segments)
        result.evidence.append({'page_census': census})
    except (OSError, subprocess.SubprocessError) as exc:
        result.unavailable('pdfinfo could not inspect the built PDF: ' + str(exc), source='pdfinfo')
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        result.fail('invalid or over-limit main-text page census: ' + str(exc))


def _submission_tag(context, root, params, result):
    ref = 'refs/tags/' + params['tag']
    if _git(context.repo, 'check-ref-format', ref, missing=True) is None:
        result.fail('invalid declared tag name')
        return
    target = _git(context.repo, 'rev-parse', '--verify', ref + '^{commit}', missing=True)
    if target is None or target.decode().strip() != context.head:
        result.fail('declared submission tag does not point at HEAD', tag=params['tag'], head=context.head)
    else:
        result.evidence.append({'tag': params['tag'], 'commit': context.head})


CHECKS = {name: globals()['_' + name] for name in PARAMETERS}


def _run_dirs(context, rules, rundirs):
    values = [*rules.get('rundirs', []), *rundirs]
    roots = []
    for value in values:
        raw = Path(value)
        path = raw if raw.is_absolute() else _safe(context.repo, str(value))
        # Explicitly named run roots may be outside the repository; no discovery follows links.
        if any(p.is_symlink() for p in (path, *path.parents) if str(p) not in ('/tmp', '/var')):
            raise ValueError('run directory must not traverse a symlink')
        path = path.resolve()
        if path not in roots:
            roots.append(path)
    return roots


def check(repo, rules, rundirs=()):
    """Return one ordered {id, status, evidence, fix_hint} row per supplied rule.

    `rules` is a mapping or a JSON file path. Record paths are relative to the
    repository, or to each explicitly declared run for scope='runs'. Missing
    sources never pass. The checker writes no state, cache or evidence files.
    """
    rules = validate_rules(_strict_json(Path(rules).read_bytes()) if isinstance(rules, (str, Path)) else rules)
    packed = json.dumps(rules, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    rules = _strict_json(packed)
    context = _Context(repo)
    roots = _run_dirs(context, rules, rundirs)
    results = {}
    # Tracking is evaluated last so it includes every referenced evidence file.
    ordered = sorted(enumerate(rules['rules']), key=lambda pair: pair[1]['check'] == 'tracked_clean')
    for index, row in ordered:
        result = _Result()
        results[index] = result
        if not row.get('enabled', True):
            result.unavailable('rule is disabled by supplied policy')
            continue
        scopes = [context.repo] if row.get('scope', 'repo') == 'repo' else roots
        if not scopes:
            result.unavailable('no run directories supplied for run-scoped rule')
        for root in scopes:
            if not root.is_dir():
                result.unavailable('declared run directory is missing', path=str(root))
                continue
            try:
                CHECKS[row['check']](context, root, row['params'], result)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                result.fail('malformed conformance evidence: ' + str(exc), scope=str(root))
    # A concurrent rewrite cannot leave an earlier PASS with stale byte evidence.
    changed = []
    for path, digest in context.pins.items():
        try:
            root = context.pin_roots[path]
            _safe(root, path.relative_to(root).as_posix())
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                changed.append(str(path))
        except (OSError, ValueError):
            changed.append(str(path))
    for path, before in context.size_observations.items():
        try:
            _safe(context.repo, path.relative_to(context.repo).as_posix())
            after = path.stat()
            if before != (after.st_size, after.st_mtime_ns, after.st_mode, after.st_ino):
                changed.append(str(path))
        except (OSError, ValueError):
            changed.append(str(path))
    if _git(context.repo, 'rev-parse', '--verify', 'HEAD').decode().strip() != context.head:
        changed.append('HEAD')
    if _git(context.repo, 'ls-files', '--stage', '-z') != context.index:
        changed.append('git index')
    if changed:
        for result in results.values():
            result.fail('inspection inputs changed during check', sources=changed)
    report_rows = []
    for index, rule in enumerate(rules['rules']):
        result = results[index]
        if not result.evidence:
            result.evidence.append({'detail': 'declared check completed against supplied evidence'})
        hints = result.failures or result.missing
        report_rows.append({'id': rule['id'], 'check': rule['check'], 'status': result.status,
                            'params': rule['params'], 'enabled': rule.get('enabled', True),
                            'scope': rule.get('scope', 'repo'),
                            'evidence': result.evidence,
                            'fix_hint': (FIX_HINTS[rule['check']] + ' ' + '; '.join(dict.fromkeys(hints))) if hints else ''})
    counts = Counter(row['status'] for row in report_rows)
    return {'schema_version': 1, 'kind': 'conformance-report', 'repo': str(context.repo), 'head': context.head,
            'rule_pack_sha256': hashlib.sha256(packed).hexdigest(),
            'rules': report_rows, 'counts': {k: counts[k] for k in ('PASS', 'FAIL', 'NOT-CHECKABLE')},
            'passed': all(row['status'] == 'PASS' for row in report_rows),
            'scope': 'Offline documentary checks of supplied records; public availability and producer completeness are supplied evidence, not live verification.'}


def render_markdown(report):
    """Render the complete per-rule evidence without dropping missing sources."""
    lines = ['# Conformance report', '', f"Repository: `{report['repo']}`", f"Commit: `{report['head']}`",
             f"Rule pack (canonical JSON SHA256): `{report['rule_pack_sha256']}`", '', report['scope'], '']
    for row in report['rules']:
        identity = row['id'].replace('\n', ' ').replace('\r', ' ')
        lines += [f"## {identity}: {row['status']}", '', 'Parameters:', '', '```json',
                  json.dumps({'check': row['check'], 'params': row['params'], 'scope': row['scope'],
                              'enabled': row['enabled']}, indent=2, sort_keys=True).replace('```', '` ` `'),
                  '```', '', 'Evidence:', '', '```json',
                  json.dumps(row['evidence'], indent=2, sort_keys=True).replace('```', '` ` `'), '```', '']
        if row['fix_hint']:
            lines += ['Fix: ' + row['fix_hint'], '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel conformance')
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('check', help='read-only checks against a requester-supplied rule pack')
    command.add_argument('--repo', type=Path, required=True)
    command.add_argument('--rules', type=Path, required=True)
    command.add_argument('--rundir', type=Path, action='append', default=[])
    command.add_argument('--out', type=Path, required=True)
    command.add_argument('--format', choices=('json', 'markdown'))
    args = parser.parse_args(argv)
    try:
        rules = validate_rules(_strict_json(args.rules.read_bytes()))
        repo = args.repo.resolve()
        # Validate the output before any inspection or directory creation.
        # Command-line run directories are relative to the caller, not the repository.
        rundirs = [path.absolute() for path in args.rundir]
        roots = _run_dirs(_Context(repo), rules, rundirs)
        out = args.out.absolute()
        if any(p.is_symlink() for p in (out, *out.parents) if str(p) not in ('/tmp', '/var')):
            raise ValueError('report output must not traverse a symlink')
        resolved = out.resolve()
        if any(resolved.is_relative_to(root) for root in [repo, *roots]):
            raise ValueError('--out must be outside the inspected repository and run directories')
        if out.exists():
            raise ValueError('report output already exists')
        report = check(repo, rules, rundirs)
        fmt = args.format or ('markdown' if out.suffix.lower() == '.md' else 'json')
        text = render_markdown(report) if fmt == 'markdown' else json.dumps(report, indent=2, sort_keys=True) + '\n'
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x', encoding='utf-8') as stream:
            stream.write(text)
        return 1 if report['counts']['FAIL'] else 3 if report['counts']['NOT-CHECKABLE'] else 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('conformance: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
