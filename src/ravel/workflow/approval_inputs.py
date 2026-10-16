"""Operation-derived approval inputs and prospective full-text replacement seam.

Execution plans declare reads in stages[].inputs and native sources; execution adds
each stage's executable, argument scripts and registered helpers, which are bound too.
Produced intermediates are not pre-execution inputs: a read beneath a stage output is
excluded only when its producer runs first by declared dependency or plan order. Rendered cards are committed by the
plan before preparation. Superseded materializations require their prior approved
writer receipt, and cease to be accepted when that writer runs again.
No extension or operation-identity allowlist decides what enters the binding.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import provenance
from .execution import digest, file_hash, log_path
from .state_io import file_lock, read_json

APPROVAL = 'inputs/checkin1_approval.json'
# Receipts are consequences of approval, never inputs to their own approval.
RECEIPTS = (APPROVAL, 'inputs/checkin2_go.json')


def absolute(root, path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('operation input path must be a nonblank string')
    return Path(os.path.abspath(Path(root) / path))


def identity(root, path):
    return os.path.relpath(path, root)


def _pins(value):
    """Source pins have the same meaning at every depth of a request plan."""
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and 'sha256' in value:
            yield value['path']
        else:
            for item in value.values():
                yield from _pins(item)
    elif isinstance(value, list):
        for item in value:
            yield from _pins(item)


def _leaves(path):
    if path.is_symlink():
        raise ValueError(f'approved input must not be a symlink: {path}')
    if path.is_dir():
        children = sorted(path.rglob('*'))
        if any(p.is_symlink() for p in children):
            raise ValueError(f'approved input directory contains a symlink: {path}')
        return [p for p in children if p.is_file()]
    if path.exists() and not path.is_file():
        raise ValueError(f'planned operation input is not a regular file: {path}')
    return [path]


def _producers(root, stages, native, *, native_log_directory='logs'):
    """(output path, producing stage name) for every declared stage output and log."""
    rows = []
    for stage in stages:
        name = stage.get('stage')
        rows += [(absolute(root, p), name) for p in stage.get('outputs', [])]
        if 'log' in stage:
            rows.append((absolute(root, stage['log']), name))
        if native:
            # Native dispatch supplies these per-operation supervisor log paths.
            rows.append((log_path(root, Path(native_log_directory) / (name + '.log')), name))
    return rows


def _ancestors(stage, by_name):
    pending, found = list(stage.get('depends_on', [])), set()
    while pending:
        name = pending.pop()
        if name in found or name not in by_name:
            continue
        found.add(name)
        pending.extend(by_name[name].get('depends_on', []))
    return found


class _Order:
    """Producer-order lookups for one plan, cached by path and stage."""

    def __init__(self, stages, produced):
        self.stages = {s.get('stage'): s for s in stages}
        self.position = {s.get('stage'): i for i, s in enumerate(stages)}
        self.produced = [(str(out), str(out).rstrip(os.sep) + os.sep, producer) for out, producer in produced]
        self._matches, self._ancestors = {}, {}

    def producers(self, source):
        key = str(source)
        if key not in self._matches:
            self._matches[key] = [p for out, prefix, p in self.produced if key == out or key.startswith(prefix)]
        return self._matches[key]

    def ancestors(self, name):
        if name not in self._ancestors:
            self._ancestors[name] = _ancestors(self.stages[name], self.stages)
        return self._ancestors[name]


def _produced_before(source, stage, order):
    """A read beneath a stage output is a produced intermediate only when its producer runs first.

    With declared dependencies the producer must be a (transitive) dependency of the
    reading stage; without them it must precede the reader in plan order. Plan-level
    reads (``stage is None``) happen before every stage and are always bound.
    """
    if stage is None:
        return False
    name = stage.get('stage')
    for producer in order.producers(source):
        if producer == name:
            continue
        if 'depends_on' in stage:
            if producer in order.ancestors(name):
                return True
        elif producer in order.position and order.position[producer] < order.position.get(name, -1):
            return True
    return False


# Interpreter inputs bound wherever they live; any other file is bound when it lies in the run.
_SCRIPT_SUFFIXES = ('.py', '.sh', '.bash', '.zsh', '.R', '.r', '.jl', '.pl', '.rb', '.lua', '.mac', '.C', '.cmnd',
                    '.tcl', '.m', '.wl', '.wls')


def _command_files(args):
    """Candidate file tokens of a stage command: plain arguments, ``--opt=value`` values,
    ``-m module`` as its module file, and the words of a ``-c`` shell string."""
    import shlex
    tokens, previous = [], None
    for arg in args:
        if previous == '-m':
            tokens.append(arg.replace('.', '/') + '.py')
        elif previous == '-c':
            try:
                tokens.extend(w for w in shlex.split(arg) if not w.startswith('-'))
            except ValueError:
                pass
        elif arg.startswith('-'):
            if '=' in arg:
                tokens.append(arg.split('=', 1)[1])
        else:
            tokens.append(arg)
        previous = arg
    return tokens


def _execution_reads(root, stage):
    """Reads execution adds to a stage: its executable, argument scripts and registered helpers."""
    import shutil
    command = stage.get('command')
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        return []
    cwd = Path(stage.get('cwd') or root)
    if not cwd.is_absolute():
        cwd = Path(root) / cwd
    reads = []
    first = command[0]
    executable = first if Path(first).is_absolute() else (
        str(cwd / first) if '/' in first else shutil.which(first))
    if executable and Path(executable).is_file():
        reads.append(str(Path(executable).resolve()))
    run = Path(root).resolve()
    own = [(Path(o) if Path(o).is_absolute() else run / o).resolve()
           for o in stage.get('outputs', []) if isinstance(o, str) and o]
    for token in _command_files(command[1:]):
        candidate = (Path(token) if Path(token).is_absolute() else cwd / token)
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if any(resolved == o or resolved.is_relative_to(o) for o in own):
            continue  # the stage writes it
        if resolved.is_relative_to(run) or resolved.suffix in _SCRIPT_SUFFIXES:
            reads.append(str(resolved))
    declaration = stage.get('helper_declaration')
    if isinstance(declaration, dict):
        pins = [declaration.get('registration_source')]
        for row in declaration.get('helpers', []) if isinstance(declaration.get('helpers'), list) else []:
            if isinstance(row, dict):
                pins += [row.get('helper_source'), row.get('interpreter_binary')]
        reads += [pin['path'] for pin in pins if isinstance(pin, dict) and isinstance(pin.get('path'), str)]
    return reads


def operation_inputs(rundir, contract):
    """Return read leaves and rendered bytes from the current declared operations.

    The executable plan is authoritative for adapter reads, including future file
    classes. Request-plan source/template pins cover planning inputs. A new read
    joins automatically when its operation declares it; no suffix list changes.
    """
    root = Path(rundir).absolute()
    files, rendered = [], {}
    receipt_paths = {absolute(root, p) for p in RECEIPTS}
    pin = contract.get('execution_plan')
    if pin:
        path = absolute(root, pin['path'])
        plan = read_json(path)
        if file_hash(path) != pin['sha256']:
            raise ValueError(f'planned operation input differs from approved bytes: {pin["path"]}; re-pin the amended plan before approval')
        files.append(path)
        stages = plan.get('stages', [])
        if not isinstance(stages, list):
            raise ValueError(f'{path}: stages must be a list')
        native = 'capability' in plan and 'rundir' in plan
        produced = _producers(root, stages, native, native_log_directory=plan.get('log_directory', 'logs'))
        # Plan-level reads happen at preparation, before any stage writes.
        reads = [(None, p['path']) for p in plan.get('sources', [])]
        # Native plans also name source cards/templates used by preparation.
        declared = plan.get('inputs', {})
        reads += [(None, p) for p in (declared.values() if isinstance(declared, dict) else declared)]
        if 'config' in plan:
            reads.append((None, plan['config']))
        for stage in stages:
            reads += [(stage, p) for p in stage.get('inputs', [])]
            reads += [(stage, p) for p in _execution_reads(root, stage)]
        order, seen, checked = _Order(stages, produced), set(), set()
        for stage, value in reads:
            source = absolute(root, value)
            if source == path or source in receipt_paths or source in seen:
                continue
            key = (None if stage is None else stage.get('stage'), source)
            if key in checked:
                continue
            checked.add(key)
            if _produced_before(source, stage, order):
                continue
            seen.add(source)
            files.extend(_leaves(source))
        card_directory = 'output'
        if native and 'rendered' in plan:
            from ravel.physics.native_effective_config import expected_cards
            from ravel.physics.native_pipeline import output_root
            texts = expected_cards(plan)
            card_directory = output_root(plan)
        else:
            texts = plan.get('rendered', {})
        for name, text in texts.items():
            if not isinstance(text, str) or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('rendered cards require relative names and literal text')
            rendered[absolute(root, str(Path(card_directory) / name))] = text.encode('utf-8')
    request_pin = contract.get('request_plan')
    if request_pin:
        plan_path = absolute(root, request_pin['path'])
        plan = read_json(plan_path)
        for value in _pins(plan):
            source = absolute(root, value)
            if source not in receipt_paths:
                files.extend(_leaves(source))
    # Delphes source directives read more bytes than the top-level card. Reuse
    # its existing read-only parser, including its refusal of unresolved sources.
    for source in list(dict.fromkeys(files)):
        if source.suffix.lower() == '.tcl':
            from ravel.physics.detector_card import Card, _read_commands
            card = Card(source)
            _read_commands(card, card.text, 1, None, None, 0)
            files.extend(Path(p['path']) for p in card.sources)
    return list(dict.fromkeys(str(p) for p in files)), rendered


def capture(rundir, paths, rendered=None):
    """Keep path identity and a digest for diagnostics as well as the fingerprint."""
    rows = []
    for value in paths:
        path = absolute(rundir, value)
        if path.is_symlink():
            raise ValueError(f'approved input must not be a symlink: {path}')
        state = 'file' if path.is_file() else 'absent'
        rows.append({'path': identity(rundir, path), 'sha256': provenance.sha256_file(path), 'state': state})
    for path, raw in sorted((rendered or {}).items()):
        rows.append({'path': identity(rundir, path), 'sha256': hashlib.sha256(raw).hexdigest(), 'state': 'rendered-present' if path.exists() else 'rendered'})
    return rows


def _snapshot_sha(snapshot, target):
    """Read one byte commitment from an execution file/directory snapshot."""
    target = target.resolve()
    for name, value in snapshot.items():
        parent = Path(name)
        for entry in value['files']:
            path = parent if entry['name'] == '.' else parent / entry['name']
            if path == target:
                return entry['sha256']
    return None


def _rendering_receipt(rundir, path):
    """Inspect the declared writer's receipt without requiring stale inputs live.

    An amendment intentionally invalidates the old execution specification. Its
    retained receipt still proves which bytes that writer produced, and which
    approval it read. Do not treat it as reusable scientific execution evidence.
    """
    from . import execution
    root = Path(rundir).absolute()
    from ravel.validation.validate_run_state import find_first_existing
    contract_path = find_first_existing(str(root), 'inputs/task_contract.json', 'task_contract.json')
    contract = read_json(root / contract_path)
    pin = contract.get('execution_plan')
    if not pin:
        return None
    plan = read_json(absolute(root, pin['path']))
    target = absolute(root, path)
    writers = [s for s in plan['stages'] if any(
        target == absolute(root, out) or target.is_relative_to(absolute(root, out))
        for out in s.get('outputs', []))]
    if len(writers) != 1:
        return None
    stage = writers[0]['stage']
    record = execution.load_execution(root)['stages'].get(stage)
    if not record or record.get('stage') != stage:
        return None
    attempt = absolute(root, record['attempt_record'])
    expected = root / 'logs/execution' / stage / record['attempt_id'] / 'record.json'
    if attempt != expected or attempt.is_symlink() or read_json(attempt) != record:
        return None
    committed = {k: record[k] for k in
                 ('command', 'cwd', 'inputs', 'outputs', 'input_snapshot', 'parents', 'runtime')}
    committed.update(execution.stage_metadata_fields(record))
    if execution.digest(committed) != record.get('fingerprint'):
        return None
    if not any(target == absolute(root, out) or target.is_relative_to(absolute(root, out))
               for out in record['outputs']):
        return None
    if record['status'] == 'succeeded' and execution.receipt_digest(record) != record.get('receipt_sha256'):
        return None
    return record if execution.load_execution(root)['stages'].get(stage) == record else None


def _rendered_transition(rundir, path, actual_sha, approval):
    """Receipt-bound allowance ends when the writer starts a new attempt.

    Superseded output bytes need BOTH the prior approved rendering and the
    successful writer receipt that read that exact approval. History alone
    cannot authorize a hand revert after preparation. A current running writer
    may have archived its output before its launch authorization is captured.
    """
    if not approval:
        return False
    try:
        receipt = _rendering_receipt(rundir, path)
    except (OSError, ValueError, KeyError, TypeError):
        # Missing/malformed custody is never an allowance; keep the card path
        # in the ordinary changed-input diagnostic.
        return False
    if not receipt:
        return False
    approval_sha = _snapshot_sha(receipt['input_snapshot'], absolute(rundir, APPROVAL))
    current_sha = hashlib.sha256((json.dumps(approval, indent=2, allow_nan=False) + '\n').encode()).hexdigest()
    approval_path = absolute(rundir, APPROVAL)
    if approval_path.is_file() and read_json(approval_path) == approval:
        current_sha = file_hash(approval_path)
    if actual_sha is None:
        return receipt['status'] == 'running' and approval_sha == current_sha
    if receipt['status'] != 'succeeded' or approval_sha == current_sha:
        return False
    if _snapshot_sha(receipt['output_snapshot'], absolute(rundir, path)) != actual_sha:
        return False
    return any(row.get('path') == path
               and (row.get('before') or {}).get('state', '').startswith('rendered')
               and row['before']['sha256'] == actual_sha
               and row.get('prior_approval_sha256') == approval_sha
               for row in approval.get('input_changes', []))


def changes(rundir, approved, current, *, approval_record=None):
    """Path-qualified byte changes, including deletion/addition and rendered edits."""
    if not isinstance(approved, list):
        raise ValueError('approval approved_inputs must be a list')
    old = {}
    for row in approved:
        if (not isinstance(row, dict) or set(row) != {'path', 'sha256', 'state'}
                or not isinstance(row['path'], str) or not isinstance(row['sha256'], str)
                or len(row['sha256']) != 64 or row['state'] not in ('file', 'absent', 'rendered', 'rendered-present')):
            raise ValueError('invalid approval input commitment')
        if row['path'] in old:
            raise ValueError('duplicate approval input commitment')
        old[row['path']] = row
    new = {r['path']: r for r in current}
    result = []
    for path in sorted(old.keys() | new.keys()):
        before, after = old.get(path), new.get(path)
        materialization = (before is not None and after is not None
                           and before['state'] == 'rendered' and after['state'] == 'rendered-present'
                           and before['sha256'] == after['sha256'])
        preparation_archive = (before is not None and after is not None
                               and before['state'] == 'rendered-present' and after['state'] == 'rendered'
                               and before['sha256'] == after['sha256']
                               and _rendered_transition(rundir, path, None, approval_record))
        if before != after and not materialization and not preparation_archive:
            result.append({'path': path, 'before': before, 'after': after})
        elif after['state'].startswith('rendered'):
            actual = absolute(rundir, path)
            if actual.exists() and (not actual.is_file() or actual.is_symlink()
                                    or file_hash(actual) != after['sha256']):
                if (actual.is_file() and not actual.is_symlink()
                        and _rendered_transition(rundir, path, file_hash(actual), approval_record)):
                    continue
                result.append({'path': path, 'before': before,
                               'after': {'path': path, 'state': 'file', 'sha256': provenance.sha256_file(actual)}})
    return result


def record_deviations(rundir, rows, *, quote=None):
    """Idempotent disclosure; a deviation row never grants execution authority."""
    if not rows:
        return
    root = Path(rundir)
    path = root / 'DEVIATIONS.md'
    with file_lock(root / 'logs/approval-inputs.lock'):
        if path.is_symlink():
            raise ValueError('DEVIATIONS.md must not be a symlink')
        text = path.read_text() if path.exists() else '# Deviations\n\n'
        if '## Approved input changes' not in text:
            text += '\n## Approved input changes\n\n| Event | Path | Byte commitment or approval | Disposition |\n|---|---|---|---|\n'
        for row in rows:
            token = digest(row)
            marker = f'<!-- approval-input-change:{token} -->'
            if marker not in text:
                before = (row['before'] or {}).get('sha256', 'unbound')
                after = (row['after'] or {}).get('sha256', 'removed')
                name = row['path'].replace('|', '\\|').replace('\n', ' ')
                text += (f'\n{marker}\n| Approved input change | `{name}` | `{before}` → `{after}` | '
                         'Requires amendment and CHECK-IN 1 re-approval; observed byte change. |\n')
            if quote:
                approval_marker = f'<!-- approval-input-reapproval:{token}:{provenance.sha256_bytes(quote.encode())} -->'
                if approval_marker not in text:
                    reason = quote.replace('|', '\\|').replace('\n', ' ')
                    text += f'\n{approval_marker}\n| Amendment re-approved | `{row["path"]}` | {reason} | Re-approved at CHECK-IN 1. |\n'
        if path.is_symlink():
            raise ValueError('DEVIATIONS.md must not be a symlink')
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix='.deviations-', dir=root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def classify_replacement(rundir, path, text):
    """Redo-loop seam: call once for each proposed full-text replacement, before writing.

    A bounded repair admission cannot substitute for amendment re-approval of an
    approved input. This call classifies only; the caller owns applying/refusing
    the replacement and obtaining the amendment. It never writes card bytes.
    """
    if not isinstance(text, str):
        raise ValueError('replacement text must be a string')
    root = Path(rundir)
    record = read_json(root / APPROVAL)
    target = absolute(root, path)
    row = next((r for r in record.get('approved_inputs', [])
                if absolute(root, r['path']) == target), None)
    if row is None:
        # Legacy receipts have no per-path snapshot; classify against the live
        # declared reads, but never manufacture permission from a missing row.
        from .workflow_state import approval_input_paths
        bound = target in {absolute(root, p) for p in approval_input_paths(str(root))}
        old_sha = provenance.sha256_file(target) if bound else None
    else:
        bound, old_sha = True, row['sha256']
    changed = bound and provenance.sha256_bytes(text.encode()) != old_sha
    return {'path': identity(root, target),
            'classification': 'approved-input-change' if changed else 'unchanged-approved-input' if bound else 'unbound-input',
            'requires_reapproval': changed, 'before_sha256': old_sha,
            'replacement_sha256': provenance.sha256_bytes(text.encode())}


def authorization_pins(paths, pin):
    """Retain readable documents and binary byte digests without decoding tools."""
    result = []
    for path in paths:
        try:
            result.append(pin(path, document=True))
        except UnicodeDecodeError:
            result.append(pin(path))
    return result


def observed_changes(rundir, record):
    """Diagnose saved bytes even when an edited plan/card no longer parses."""
    old = record.get('approved_inputs', [])
    current = []
    for row in old:
        path = absolute(rundir, row['path'])
        if row['state'].startswith('rendered'):
            current.append({**row, 'state': 'rendered-present' if path.exists() else 'rendered'})
        else:
            current += capture(rundir, [str(path)])
    return changes(rundir, old, current, approval_record=record)
