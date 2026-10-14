"""Worker-local JSON-lines broker with supervisor-owned, chained custody.

Only trusted Python registrations create actions. Artifact bytes, board prose,
model findings and socket messages cannot register a handler or grant authority.
The custody store must be outside the worker's sandbox mounts.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import stat
import threading
import time
from datetime import datetime, timezone

from .state_io import atomic_json, file_lock, read_json

MAX_MESSAGE = 1024 * 1024
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
ENV_NAME = re.compile(r'[A-Z_][A-Z0-9_]{0,63}\Z')
DERIVATIONS = {'registered_validator', 'toolchain', 'authored_script', 'retrieval'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ordinary(path):
    path = Path(path).absolute()
    linked = next((p for p in (path, *path.parents) if p.is_symlink()), None)
    if linked is not None:
        # Name the real path so the caller can pass it instead (for example /private/tmp for /tmp).
        raise ValueError(f'paths cannot traverse symlinks: {linked} is a symlink; use the real path '
                         f'{os.path.realpath(path)}')
    return path.resolve()


def runtime_dir():
    """The resolved temporary directory for sockets (``ordinary`` refuses a symlinked TMPDIR)."""
    return Path(os.path.realpath(os.environ.get('TMPDIR') or '/private/tmp'))


def confined(root, rel):
    root = ordinary(root)
    if type(rel) is not str or not rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
        raise ValueError('path must be relative and confined')
    path = ordinary(root / rel)
    if not path.is_relative_to(root) or path == root:
        raise ValueError('path must be relative and confined')
    return path


def _private_dirs(folder):
    """Create each missing level with mode 0700, not with the umask."""
    missing = []
    while not folder.exists():
        missing.append(folder); folder = folder.parent
    for level in reversed(missing):
        level.mkdir(mode=0o700, exist_ok=True)


def _state_dir():
    return ordinary(os.environ.get('RAVEL_STATE_DIR', str(Path.home() / '.local/state/ravel')))


def custody(rundir):
    run = ordinary(rundir)
    state = _state_dir()
    if state.is_relative_to(run) or run.is_relative_to(state):
        raise ValueError('custody must be outside the run tree')
    folder = state / 'workers' / digest(str(run))
    _private_dirs(folder)
    return ordinary(folder)


WORK = 'agent-work'


def work_root(rundir):
    """Live worker workspaces: ``$RAVEL_WORK_ROOT/<run digest>``, outside the run tree and custody."""
    run = ordinary(rundir)
    base = ordinary(os.environ.get('RAVEL_WORK_ROOT') or str(_state_dir() / 'work'))
    if base.is_relative_to(run) or run.is_relative_to(base):
        raise ValueError('worker workspaces must be outside the run tree')
    state = _state_dir() / 'workers'
    if base.is_relative_to(state) or state.is_relative_to(base):
        raise ValueError('worker workspaces must be outside worker custody')
    folder = base / digest(str(run))
    _private_dirs(folder)
    return ordinary(folder)


def locate(rundir, rel):
    """Resolve a logical run path; ``agent-work/<node>/<attempt>/...`` names the live workspace."""
    parts = Path(rel).parts if type(rel) is str else ()
    if len(parts) >= 4 and parts[0] == WORK:
        return confined(work_root(rundir), str(Path(*parts[1:])))
    return confined(rundir, rel)


def logical(rundir, path):
    """The logical run path of a run file or a live workspace file."""
    path = ordinary(path); root = work_root(rundir)
    if path.is_relative_to(root):
        return (Path(WORK) / path.relative_to(root)).as_posix()
    return path.relative_to(ordinary(rundir)).as_posix()


def append_ledger(rundir, name, record):
    """Fsync an append-only hash chain; callers hold no model-provided authority."""
    root = custody(rundir)
    if not ID.fullmatch(name):
        raise ValueError('invalid ledger name')
    path = root / (name + '.jsonl')
    with file_lock(root / (name + '.lock')):
        rows = ledger(rundir, name)
        row = {'n': len(rows) + 1, 'previous_sha256': digest(rows[-1]) if rows else None,
               'record': deepcopy(record)}
        raw = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n'
        with ordinary(path).open('a', encoding='utf-8') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        return row


def ledger(rundir, name):
    path = ordinary(custody(rundir) / (name + '.jsonl'))
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if (set(row) != {'n', 'previous_sha256', 'record'} or row['n'] != len(rows) + 1
                or row['previous_sha256'] != (digest(rows[-1]) if rows else None)):
            raise ValueError('custody ledger chain changed')
        rows.append(row)
    return rows


def verify_broker_receipt(rundir, pin, *, verify_outputs=True):
    """Resolve public receipt bytes against the broker's inaccessible ledger."""
    run = ordinary(rundir)
    path = locate(run, pin['path'])
    if not path.is_file() or sha(path) != pin['sha256']:
        raise ValueError('broker receipt bytes differ from custody pin')
    known = [r['record'] for r in ledger(run, 'broker') if r['record']['path'] == pin['path']
             and r['record']['sha256'] == pin['sha256']]
    if len(known) != 1:
        raise ValueError('broker receipt not in custody')
    receipt = read_json(path)
    if digest(receipt) != known[0]['receipt_sha256']:
        raise ValueError('broker receipt differs from custody')
    for output in receipt['output_pins'] if verify_outputs else []:
        p = locate(run, output['path'])
        if not p.is_file() or sha(p) != output['sha256']:
            raise ValueError('broker output changed after custody')
    return receipt


def verify_acquisition_receipt(rundir, pin):
    receipt = verify_broker_receipt(rundir, pin)
    rows = [r['record'] for r in ledger(rundir, 'acquisition')
            if r['record']['receipt'] == pin]
    if (len(rows) != 1 or receipt['derivation'] != 'retrieval'
            or receipt['status'] != 'ok' or rows[0]['source'] != receipt.get('source')):
        raise ValueError('acquisition receipt not in custody')
    return receipt


def authority_inputs(reply):
    """Gate adapters may consume receipt references only, never stdout prose."""
    return {k: deepcopy(reply[k]) for k in ('receipt_id', 'status', 'outputs') if k in reply}


STOP_RECORD = WORK + '/stop.json'


def stop_mode(rundir):
    """``None`` without a worker stop record, ``drain`` for a drain record, ``cancel`` for any other.

    Under a drain an admitted attempt finishes its broker work; a cancellation, an older record
    without a mode and an unreadable record stop it.
    """
    path = Path(rundir) / STOP_RECORD
    if not path.exists() and not path.is_symlink():
        return None
    try:
        record = read_json(path) if path.is_file() and not path.is_symlink() else None
    except (OSError, ValueError):
        record = None
    return 'drain' if type(record) is dict and record.get('mode') == 'drain' else 'cancel'


class Refusal(ValueError):
    def __init__(self, code, message):
        super().__init__(message); self.code = code


class ValidatorRaised(Exception):
    """A registered-validator handler raises this when the selected validator was entered and
    raised: the failed receipt then keeps the validator's identity. Any other exception means the
    handler failed before the validator ran, and the receipt names no validator."""


class Broker:
    def __init__(self, rundir, workspace, *, node_id, attempt, allowed_actions, max_calls,
                 forbidden_sources=(), actor_id=None, season=None, lease=None, guards=()):
        self.rundir, self.workspace = ordinary(rundir), ordinary(workspace)
        if not self.workspace.is_relative_to(work_root(self.rundir)):
            raise ValueError('worker workspace outside the run work root')
        if not ID.fullmatch(node_id) or type(attempt) is not int or attempt < 1:
            raise ValueError('invalid worker identity')
        if type(max_calls) is not int or not 0 <= max_calls <= 100000:
            raise ValueError('finite broker call budget required')
        self.node_id, self.attempt, self.max_calls = node_id, attempt, max_calls
        self.allowed_actions = set(allowed_actions)
        self.forbidden_sources = tuple(forbidden_sources)
        self.actor_id, self.season, self.lease = actor_id, deepcopy(season), lease
        self.guards = list(guards)
        self.actions = {}
        self.socket_path = self.workspace / '.broker.sock'
        if len(os.fsencode(str(self.socket_path))) >= 100:
            self.socket_path = runtime_dir() / ('rv-broker-'+digest([str(self.workspace),node_id,attempt])[:16]+'.sock')
        self._lock = custody(rundir) / (digest([node_id, attempt]) + '.broker.lock')
        self._state = custody(rundir) / (digest([node_id, attempt]) + '.broker.json')
        self.register('read', self._read, read_only=True)
        self.register('write', self._write)

    def register(self, name, handler, *, derivation='authored_script', validator_id=None,
                 read_only=False, native=False, validator_ids=None):
        if (not callable(handler) or derivation not in DERIVATIONS or type(name) is not str
                or not name.strip() or name in self.actions):
            raise ValueError('invalid or duplicate trusted action registration')
        if derivation == 'registered_validator':
            path = Path(__file__).parents[1] / 'data/validators/allowlist.json'
            entries=read_json(path) if path.is_file() else []
            entries=entries.get('validators',[]) if type(entries) is dict else entries
            ids={r.get('id') if type(r) is dict else r for r in entries}
            declared = set(validator_ids) if validator_ids is not None else {validator_id}
            if not declared or not declared <= ids:
                raise ValueError('validator must be registered in the allowlist')
            if validator_ids is not None:
                validator_id = frozenset(declared)
        self.actions[name] = (handler, derivation, validator_id, read_only, native)

    def sealing_status(self):
        participants = (self.season or {}).get('participants', [])
        confirmed = len(participants)>=2
        sessions=[]
        for participant in participants:
            try:
                pin=participant['receipt']
                if not any(row['record']['pin']==pin for row in ledger(self.rundir,'worker-receipts')):
                    raise ValueError('unregistered participant')
                receipt=read_json(locate(self.rundir,pin['path']))
                if sha(locate(self.rundir,pin['path']))!=pin['sha256']:
                    raise ValueError('participant receipt changed')
                isolation=receipt['isolation']
                if (receipt['attestation']!='transport_attested' or not receipt['session_id']
                        or isolation['user_configuration_loaded'] is not False
                        or isolation.get('evidence',{}).get('confirmed') is not True):
                    raise ValueError('participant session not attested and isolated')
                sessions.append(receipt['session_id'])
            except (ValueError,OSError,KeyError,TypeError):
                confirmed=False
        confirmed=confirmed and len(set(sessions))==len(participants)
        result={'status':'sealed' if confirmed else 'unsealed',
                'phase':(self.season or {}).get('phase'),'participants':len(participants)}
        if confirmed:result['independence']='attested_distinct_sessions'
        return result

    def peer_denials(self):
        return [r['record'] for r in ledger(self.rundir, 'peer-denials')
                if r['record']['node_id'] == self.node_id and r['record']['attempt'] == self.attempt]

    def _canonical(self, rel, *, write=False):
        """Policy on the normalized relative path: escape, forbidden sources, granted roots."""
        code = 'write_outside_workspace' if write else 'forbidden_source'
        if type(rel) is not str or not rel or '\x00' in rel or rel.startswith('/'):
            raise Refusal(code, 'path must be relative and confined')
        parts = [part for part in rel.split('/') if part not in ('', '.')]
        if not parts or '..' in parts:
            raise Refusal(code, 'path escaped workspace')
        if any(fnmatchcase('/'.join(parts), pattern) for pattern in self.forbidden_sources):
            raise Refusal('forbidden_source', 'source excluded by the recorded policy')
        permitted = ('outputs', 'scratch') if write else ('inputs', 'outputs', 'scratch')
        if parts[0] not in permitted or len(parts) < 2:
            raise Refusal(code, 'path outside granted roots')
        return parts

    def _open(self, parts, *, write=False):
        """Open by descriptor from the workspace with no-follow at every component.

        A component replaced by a symlink after the policy check fails to open; the
        opened leaf must be a regular file with one link before it is truncated or read.
        """
        code = 'write_outside_workspace' if write else 'forbidden_source'
        directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.workspace, directory)
        try:
            for name in parts[:-1]:
                if write:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                following = os.open(name, directory, dir_fd=fd)
                os.close(fd); fd = following
            flags = (os.O_WRONLY | os.O_CREAT) if write else (os.O_RDONLY | os.O_NONBLOCK)
            leaf = os.open(parts[-1], flags | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        except OSError:
            raise Refusal(code, 'path is not an ordinary file inside the workspace') from None
        finally:
            os.close(fd)
        observed = os.fstat(leaf)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            os.close(leaf)
            raise Refusal(code, 'path is not an ordinary file inside the workspace')
        return leaf, observed

    def _digest(self, rel, *, write=False):
        """Logical pin of a workspace file, hashed through a verified descriptor."""
        parts = self._canonical(rel, write=write)
        leaf, _ = self._open(parts)
        with os.fdopen(leaf, 'rb') as stream:
            value = hashlib.sha256(stream.read()).hexdigest()
        return {'path': logical(self.rundir, self.workspace.joinpath(*parts)), 'sha256': value}

    def _read(self, args):
        if set(args) != {'path'}:
            raise Refusal('invalid_args', 'read requires path only')
        leaf, observed = self._open(self._canonical(args['path']))
        with os.fdopen(leaf, 'rb') as stream:
            if observed.st_size > MAX_MESSAGE // 2:
                raise Refusal('budget_exhausted', 'read exceeds byte bound')
            raw = stream.read(MAX_MESSAGE // 2 + 1)
        if len(raw) > MAX_MESSAGE // 2:
            raise Refusal('budget_exhausted', 'read exceeds byte bound')
        return {'stdout': raw.decode(), 'input_paths': [args['path']]}

    def _write(self, args):
        if set(args) != {'path', 'content'} or type(args['content']) is not str:
            raise Refusal('invalid_args', 'write requires path and text content only')
        parts = self._canonical(args['path'], write=True)
        raw = args['content'].encode()
        if len(raw) > MAX_MESSAGE // 2:
            raise Refusal('budget_exhausted', 'write exceeds byte bound')
        leaf, _ = self._open(parts, write=True)
        with os.fdopen(leaf, 'wb') as stream:
            stream.truncate(0); stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        return {'output_paths': [args['path']]}

    def _snapshot(self):
        """Digest of ``outputs/`` for repeat detection, walked by descriptor.

        Directories are traversed through ``fwalk`` without following links and each
        file is opened no-follow relative to its directory descriptor, so a component
        swapped for a symlink cannot redirect this privileged read. ``scratch/`` is
        excluded: touching a scratch file is not a state change.
        """
        result = []
        try:
            top = os.open(self.workspace / 'outputs', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            return digest(['outputs-unavailable'])
        try:
            for folder, dirs, files, fd in os.fwalk('.', dir_fd=top, follow_symlinks=False):
                dirs.sort()
                for name in sorted(files + [d for d in dirs if stat.S_ISLNK(os.lstat(d, dir_fd=fd).st_mode)]):
                    rel = os.path.normpath(os.path.join('outputs', folder, name))
                    try:
                        leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    except OSError:
                        result.append([rel, 'not-ordinary']); continue
                    with os.fdopen(leaf, 'rb') as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                            result.append([rel, 'not-ordinary']); continue
                        result.append([rel, hashlib.sha256(stream.read()).hexdigest()])
        finally:
            os.close(top)
        return digest(result)

    def _custody_pin(self, call_id, request_sha):
        """The custody pin of this call's receipt, matched through its reservation, or None."""
        reserved = {r['record']['receipt_id'] for r in ledger(self.rundir, 'broker-reservations')
                    if r['record']['node_id'] == self.node_id and r['record']['attempt'] == self.attempt
                    and r['record']['request_sha256'] == request_sha}
        for row in ledger(self.rundir, 'broker'):
            record = row['record']
            if record['node_id'] != self.node_id or record['attempt'] != self.attempt:
                continue
            pin = {'path': record['path'], 'sha256': record['sha256']}
            receipt = verify_broker_receipt(self.rundir, pin, verify_outputs=False)
            if receipt['receipt_id'] in reserved and receipt['reply'].get('call_id') == call_id:
                return pin
        return None

    def verify_ledger(self):
        return [verify_broker_receipt(self.rundir, {'path': r['record']['path'], 'sha256':r['record']['sha256']},verify_outputs=False)
                for r in ledger(self.rundir, 'broker')
                if r['record']['node_id'] == self.node_id and r['record']['attempt'] == self.attempt]

    def call(self, request):
        # Malformed and refused requests consume calls just like successful ones.
        digest(request)
        with file_lock(self._lock):
            state = read_json(self._state) if self._state.exists() else {'calls': {}, 'n': 0, 'repeats': {}, 'blocked': False}
            call_id = request.get('call_id') if type(request) is dict else None
            request_sha = digest(request)
            old = state['calls'].get(call_id) if type(call_id) is str else None
            if old and old['request_sha256'] == request_sha and not old.get('pin'):
                # A crash after the custody append and before this state pin: adopt the
                # receipted outcome from custody instead of leaving it ambiguous.
                pin = self._custody_pin(call_id, request_sha)
                if pin is not None:
                    old['pin'] = pin; atomic_json(self._state, state)
            if old and old['request_sha256'] == request_sha and old.get('pin'):
                known = verify_broker_receipt(self.rundir, old['pin'],verify_outputs=False)
                return known['reply']
            n = state['n'] + 1
            action = request.get('action') if type(request) is dict else None
            args = request.get('args') if type(request) is dict else None
            record = {'schema_version': 1, 'kind':'broker-receipt',
                'receipt_id':f'{self.node_id}/{self.attempt}/{n}', 'node_id':self.node_id,
                'attempt':self.attempt, 'n':n, 'action':action, 'args_sha256':digest(args),
                'argv':[], 'script_sha256':None, 'input_pins':[], 'output_pins':[],
                'exit_status':None, 'wall_seconds':0.0, 'stdout_sha256':hashlib.sha256(b'').hexdigest(),
                'stderr_sha256':hashlib.sha256(b'').hexdigest(), 'derivation':None, 'validator_id':None,
                'policy':{'allowlisted':False,'source_restriction_sha256':digest(self.forbidden_sources),'lease':None},
                'started_utc':utc(), 'finished_utc':None, 'source':None}
            began = time.monotonic(); outputs = []; stdout = ''; error = None
            try:
                if (type(request) is not dict or set(request) != {'call_id','action','args'}
                        or type(call_id) is not str or not ID.fullmatch(call_id)
                        or type(action) is not str or type(args) is not dict):
                    raise Refusal('invalid_call', 'call requires call_id, action and args only')
                if old:
                    if old['request_sha256'] == request_sha:
                        raise Refusal('ambiguous_call','started broker call has no receipt; reconcile instead of repeating')
                    raise Refusal('call_identity_changed', 'call ID reused with different request')
                if state['n'] >= self.max_calls:
                    raise Refusal('budget_exhausted', 'broker call budget exhausted')
                # A cancellation stops every call; under a drain this admitted attempt finishes its
                # work (outputs, self-checks) and only a call that starts native work is refused.
                stopping = stop_mode(self.rundir)
                if stopping == 'cancel':
                    raise Refusal('stop_requested', 'run worker stop requested')
                if state['blocked']:
                    raise Refusal('decision_block', 'repetition requires a decision turn')
                if action not in self.allowed_actions or action not in self.actions:
                    raise Refusal('not_allowlisted', 'action not in the role allowlist or registry')
                record['policy']['allowlisted'] = True
                if self.season and self.season.get('phase') == 'sealed' and action in {'board read','board find'}:
                    if type(self.actor_id) is not str or not self.actor_id or set(args) != {'actor_id'} or args.get('actor_id') != self.actor_id or action == 'board find':
                        append_ledger(self.rundir, 'peer-denials', {'node_id':self.node_id,'attempt':self.attempt,
                            'actor_id':self.actor_id,'args_sha256':digest(args),'utc':utc(),'code':'peer_read_denied'})
                        raise Refusal('peer_read_denied', 'sealed phase denies all peer visibility')
                for guard in self.guards:
                    refusal = guard(action, deepcopy(args), self.workspace)
                    if refusal:
                        raise Refusal(refusal['code'], refusal['message'])
                before = self._snapshot()
                key = digest([action, digest(args)])
                last = state['repeats'].get(key, {})
                count = last.get('count', 0) + 1 if last.get('state') == before else 1
                if state.get('last_state') != before:
                    state['repeats'] = {}
                    count = 1
                state['last_state'] = before
                state['repeats'][key] = {'state':before, 'count':count}
                if count >= 3:
                    state['blocked'] = True
                    raise Refusal('decision_block', 'third identical call without state change')
                handler, derivation, validator, readonly, native = self.actions[action]
                selected = args.get('check_id') if isinstance(validator, frozenset) else validator
                if isinstance(validator, frozenset) and selected not in validator:
                    raise Refusal('not_allowlisted', 'check is outside the registered validator set')
                # One rule for scalar and multi-id registrations: a receipt names a validator only
                # after its handler reports that the validator ran (or raised inside it).
                is_validator = derivation == 'registered_validator'
                record.update(derivation=derivation, validator_id=None)
                if native and stopping == 'drain':
                    raise Refusal('stop_requested', 'a drain admits no new native work')
                if native:
                    lease = self.lease(action, deepcopy(args)) if self.lease else None
                    if not lease:
                        raise Refusal('lease_busy', 'native action waits for its admitted lease')
                    record['policy']['lease'] = lease
                state['n'] = n
                state['calls'][call_id] = {'request_sha256':request_sha,'pin':None}
                atomic_json(self._state,state)
                broker_reservation = {**record,'status':'started','request_sha256':request_sha}
                append_ledger(self.rundir,'broker-reservations',broker_reservation)
                try:
                    value = handler(deepcopy(args))
                except ValidatorRaised:
                    if is_validator:
                        record.update(validator_id=selected, exit_status=1)
                    raise
                if type(value) is not dict:
                    raise ValueError('registered action must return a structured record')
                executed = is_validator and value.get('validator_executed') is True
                if executed:
                    record['validator_id'] = selected
                stdout = value.get('stdout', '')
                if type(stdout) is not str or len(stdout.encode()) > MAX_MESSAGE // 2:
                    raise ValueError('broker output exceeds byte bound')
                for key, writable in (('input_paths',False),('output_paths',True)):
                    for rel in value.get(key, []):
                        record['output_pins' if writable else 'input_pins'].append(self._digest(rel, write=writable))
                if derivation == 'retrieval':
                    source = value.get('source')
                    if type(source) is not dict or set(source) != {'uri','record_id'} or not all(type(x) is str and x for x in source.values()):
                        raise ValueError('retrieval requires producer source identity')
                    record['source'] = source
                outputs = record['output_pins']
                exit_status = value.get('exit_status', 0)
                if type(exit_status) is not int or exit_status < 0:
                    raise ValueError('action exit_status must be a nonnegative integer')
                if is_validator and (not executed or 'exit_status' not in value):
                    # Validator success is explicit: it ran, and it stated its outcome. A handler
                    # that returns without both has not passed a check.
                    exit_status = exit_status or 1
                record['exit_status'] = exit_status
                status = 'ok' if exit_status == 0 else 'failed'
            except Refusal as exc:
                status = 'refused'; error = {'code':exc.code,'message':str(exc)}
            except Exception:
                status = 'failed'; error = {'code':'action_failed','message':'registered broker action failed'}
            reply = {'call_id':call_id, 'receipt_id':record['receipt_id'], 'status':status,
                     'outputs':outputs, 'stdout_tail':stdout[-8192:], 'error':error}
            record.update(status=status, reply=reply, finished_utc=utc(), wall_seconds=time.monotonic()-began,
                          stdout_sha256=hashlib.sha256(stdout.encode()).hexdigest())
            path = confined(self.workspace, f'calls/{n}.json')
            atomic_json(path, record)
            pin = {'path':logical(self.rundir, path), 'sha256':sha(path)}
            append_ledger(self.rundir, 'broker', {**pin,'node_id':self.node_id,'attempt':self.attempt,'receipt_sha256':digest(record)})
            if status == 'ok' and record['derivation'] == 'retrieval':
                append_ledger(self.rundir,'acquisition',{'receipt':pin,'source':record['source']})
            after = self._snapshot()
            if state.get('last_state') != after:
                state['repeats'] = {}
            state['last_state'] = after
            state['n'] = n
            if type(call_id) is str and not old:
                state['calls'][call_id] = {'request_sha256':request_sha, 'pin':pin}
            atomic_json(self._state, state)
            return reply


@contextmanager
def serve(broker):
    """Transport adapters share this socket and the same receipting implementation."""
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            while True:
                raw = self.rfile.readline(MAX_MESSAGE + 1)
                if not raw:
                    return
                if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
                    return
                try:
                    request = json.loads(raw)
                    response = broker.call(request)
                except (ValueError, TypeError):
                    response = broker.call({'invalid_wire_sha256':hashlib.sha256(raw).hexdigest()})
                self.wfile.write((json.dumps(response, allow_nan=False)+'\n').encode()); self.wfile.flush()
    path = ordinary(broker.socket_path)
    if path.exists():
        raise ValueError('broker socket already owned; do not replace a running worker')
    server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    os.chmod(path, 0o600)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    try:
        yield server
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
        path.unlink(missing_ok=True)


def socket_call(path, request):
    raw = json.dumps(request, allow_nan=False).encode()+b'\n'
    if len(raw) > MAX_MESSAGE:
        raise ValueError('broker request exceeds byte bound')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10);client.connect(str(path));client.sendall(raw)
        with client.makefile('rb') as stream:
            response = stream.readline(MAX_MESSAGE + 1)
    if len(response) > MAX_MESSAGE or not response.endswith(b'\n'):
        raise ValueError('broker reply exceeds byte bound')
    return json.loads(response)
