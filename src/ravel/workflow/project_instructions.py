"""One declared project instruction document for every session a run starts.

A project can require that one named instruction file reaches every agent on every
prompt. A run declares that file once, when it starts::

    ravel project-instructions pin --rundir <run> --path <document>

The pin (``inputs/project_instructions.json``: path, sha256, bytes) is bound into the
run's custody ledger, outside the run tree. From then on every worker launch and every
one-shot reviewer or answer call RAVEL starts for the run receives the document's text
verbatim, ahead of RAVEL's own instructions, and its receipt records the document
sha256, the byte count and the delivery mechanism.

Delivery. ``deliver`` picks the strongest mechanism the route's probe confirms:

- ``system_prompt_append_flag``: the route's argv template carries the placeholder
  ``{project_instructions_file}`` behind a flag, and the probe confirmed that flag. The
  text is written to a read-only file and the flag names it.
- ``prompt_first_block``: the text is the first block of the prompt, before the RAVEL
  instructions. This is the mechanism for every route whose template has no such flag.

A worker the host itself starts (a host subagent) gets no prompt from RAVEL. ``for_packet``
puts the text in its work packet instead, as ``work_packet``. That record shows delivery only
when the host reports, with the final record, the sha256 of the document its subagent read.

The document is the only project configuration RAVEL supplies. User settings, memory,
skills, hooks and plugins stay excluded exactly as before.

Kept text. Each pin copies the document's bytes into the run's custody folder, named by
their sha256 (``retained_path``). A later re-pin or an edited file does not remove an
earlier text: ``retained_text`` returns the text any session of the run was given.

A fixed document. The text may not change during a run. When the file's sha256 differs
from the pin, the next launch is refused and names the command that re-pins it. A re-pin
needs an explicit approval (who approved it and why) and is appended to the custody
ledger; editing the pin file by hand does not re-pin anything.

Ancestor files. A worker workspace under the project that holds the declared file is
accepted when every instruction file above it is either the declared document itself,
with the pinned sha256, or a companion file whose whole content is one import of it
(for example a ``CLAUDE.md`` holding ``@AGENTS.md``). ``classify`` answers that question
for one file.

Which run. A session belongs to the run named with ``--rundir``. Without that name,
``owning_run`` finds the run from the session's graph or request file: the nearest
directory above it that holds an ``inputs`` folder (``nearest_run``). The search stops at
that directory. A named run must be that nearest run, and naming it settles a run that
pins nothing under a tree that pins a document.

Credit. ``receipt_problem`` names why a worker receipt or a one-shot session receipt does
not show delivery of the pinned document. A run that declares a document credits no
session whose receipt lacks the record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex

from . import broker
from .state_io import atomic_json, read_json

PIN_FILE = 'inputs/project_instructions.json'
PIN_KIND = 'project-instructions-pin'
LEDGER = 'project-instructions'
MAX_BYTES = 256 * 1024
# The argv-template placeholder a route uses to carry the document behind a system-prompt flag.
CARRIER = 'project_instructions_file'
CARRIER_NAME = 'project-instructions.md'
MECHANISMS = ('system_prompt_append_flag', 'prompt_first_block', 'work_packet')
POSITION = 'before_ravel_instructions'
PIN_FIELDS = {'schema_version', 'kind', 'path', 'sha256', 'bytes', 'sequence', 'pinned_utc', 'approval'}
APPROVAL_FIELDS = {'approved_by', 'statement', 'utc', 'replaces_sha256'}
RECORD_FIELDS = {'schema_version', 'path', 'sha256', 'bytes', 'mechanism', 'flag', 'position', 'ambient'}
AMBIENT_FIELDS = {'ancestor_files', 'cli_reported_loaded'}
# A work-packet record also says which document the host reported its subagent read (None: no report).
ACKNOWLEDGEMENT = 'host_acknowledged_sha256'
RELATIONS = ('declared', 'import')
BLOCK_OPEN = '===== PROJECT INSTRUCTIONS ====='
BLOCK_CLOSE = '===== END OF PROJECT INSTRUCTIONS ====='


class ProjectInstructionsError(ValueError):
    """The declared document cannot be delivered; ``missing`` names each item. Nothing is launched."""

    def __init__(self, message, missing):
        super().__init__(message)
        self.missing = list(missing)


def _refuse(item, detail):
    raise ProjectInstructionsError(f'project instructions refused: {item} ({detail})', [item])


def _hex(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _read(path):
    """(bytes, text) of a regular, non-linked UTF-8 document within the size bound."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _refuse('project_instructions:document', f'{path} is not a regular file')
    raw = path.read_bytes()
    if not raw.strip() or len(raw) > MAX_BYTES:
        _refuse('project_instructions:document', f'{path} must hold 1 to {MAX_BYTES} bytes of text')
    try:
        return raw, raw.decode('utf-8')
    except UnicodeDecodeError:
        _refuse('project_instructions:document', f'{path} is not UTF-8 text')


def pin(path):
    """``{path, sha256, bytes}`` for a document: its real absolute path and the digest of its bytes."""
    source = Path(path).expanduser()
    if source.is_symlink():
        _refuse('project_instructions:document', f'{source} is a symbolic link')
    resolved = Path(os.path.realpath(source))
    raw, _ = _read(resolved)
    return {'path': str(resolved), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _run(rundir):
    return Path(os.path.realpath(rundir))


def _ledger_file(run):
    """Where the custody ledger file is, found without creating or checking any custody directory.

    A run that pins nothing must cost one ``exists`` call and never fail here.
    """
    state = os.path.realpath(os.environ.get('RAVEL_STATE_DIR') or Path.home() / '.local/state/ravel')
    return Path(state) / 'workers' / broker.digest(str(run)) / (LEDGER + '.jsonl')


def _rows(run):
    try:
        return broker.ledger(run, LEDGER)
    except ValueError as exc:
        _refuse('project_instructions:custody', str(exc))


def repin_command(rundir, path=None):
    """The exact command that re-pins the document by an explicit approval."""
    words = ['ravel', 'project-instructions', 'repin', '--rundir', str(rundir)]
    if path is not None:
        words += ['--path', str(path)]
    return ' '.join(shlex.quote(w) for w in words) + ' --approved-by <who approves> --statement "<why the text changed>"'


def _shape(record):
    if (type(record) is not dict or set(record) != PIN_FIELDS or record['kind'] != PIN_KIND
            or record['schema_version'] != 1 or type(record['path']) is not str or not Path(record['path']).is_absolute()
            or not _hex(record['sha256']) or type(record['bytes']) is not int or not 0 < record['bytes'] <= MAX_BYTES
            or type(record['sequence']) is not int or record['sequence'] < 1):
        return False
    approval = record['approval']
    if record['sequence'] == 1:
        return approval is None
    return (type(approval) is dict and set(approval) == APPROVAL_FIELDS and _hex(approval['replaces_sha256'])
            and all(type(approval[k]) is str and approval[k].strip() for k in ('approved_by', 'statement', 'utc')))


def declared(rundir):
    """The run's pin record, or None when the run declares no document.

    The record in the run tree counts only when it is the latest entry of the custody
    ledger. A pin file that was edited, added or removed by hand is refused.
    """
    run = _run(rundir)
    path, ledger = run / PIN_FILE, _ledger_file(run)
    if not path.exists() and not path.is_symlink() and not ledger.exists():
        return None
    if not ledger.exists():
        _refuse('project_instructions:pin-not-in-custody',
                f'{path} has no entry in this run\'s custody under RAVEL_STATE_DIR; remove it or pin the document with '
                '`ravel project-instructions pin`')
    rows = _rows(run)
    if path.is_symlink() or not path.is_file():
        _refuse('project_instructions:pin-removed',
                f'this run pinned a document and {path} is gone; restore it or run: {repin_command(run, rows[-1]["record"]["path"])}')
    try:
        record = read_json(path)
    except (OSError, ValueError):
        record = None
    if not _shape(record) or not rows or broker.digest(record) != rows[-1]['record']['record_sha256']:
        _refuse('project_instructions:pin-changed',
                f'{path} differs from the pin in custody; a new pin needs an approval: {repin_command(run)}')
    return record


def retained_path(rundir, sha256):
    """Where custody keeps the bytes of a document this run pinned: beside the ledger, named by the sha256."""
    return _ledger_file(_run(rundir)).parent / f'{LEDGER}.{sha256}.md'


def retained_text(rundir, sha256):
    """The text of a document this run pinned at any time, read from the custody copy, or None.

    The copy counts only while it still holds the pinned bytes.
    """
    if not _hex(sha256):
        return None
    path = retained_path(rundir, sha256)
    if path.is_symlink() or not path.is_file():
        return None
    raw = path.read_bytes()
    return raw.decode('utf-8') if hashlib.sha256(raw).hexdigest() == sha256 else None


def _retain(run, document):
    """Copy the pinned bytes into custody before the pin is recorded, so every recorded pin has its text."""
    if retained_text(run, document['sha256']) is not None:
        return
    raw, _ = _read(document['path'])
    if hashlib.sha256(raw).hexdigest() != document['sha256']:
        _refuse('project_instructions:changed', f'{document["path"]} changed while it was being pinned')
    try:
        folder = broker.custody(run)
    except ValueError as exc:
        _refuse('project_instructions:custody', str(exc))
    target = retained_path(run, document['sha256'])
    assert target.parent == folder
    scratch = target.with_name(target.name + '.' + os.urandom(8).hex())
    scratch.write_bytes(raw)
    scratch.chmod(0o400)
    os.replace(scratch, target)


def _write(run, document, approval):
    rows = _rows(run)
    record = {'schema_version': 1, 'kind': PIN_KIND, **document, 'sequence': len(rows) + 1,
              'pinned_utc': broker.utc(), 'approval': approval}
    assert _shape(record)
    _retain(run, document)
    broker.append_ledger(run, LEDGER, {'record_sha256': broker.digest(record), 'path': record['path'],
                                       'sha256': record['sha256'], 'bytes': record['bytes'],
                                       'sequence': record['sequence'], 'approval': approval})
    atomic_json(run / PIN_FILE, record)
    return record


def declare(rundir, path):
    """Pin the document for a run that has none yet. A second pin goes through ``repin``."""
    run = _run(rundir)
    if not run.is_dir():
        _refuse('project_instructions:rundir', f'{run} is not a directory')
    if declared(run) is not None:
        _refuse('project_instructions:already-pinned',
                f'this run already pins a document; changing it needs an approval: {repin_command(run, path)}')
    return _write(run, pin(path), None)


def repin(rundir, *, approved_by, statement, path=None):
    """Replace the run's pin by an explicit approval; the approval is kept in the pin and in custody."""
    run = _run(rundir)
    from .approval_authority import AGENT_MARKERS
    present = [name for name in AGENT_MARKERS if name in os.environ]
    if present:
        # A changed document waits for the operator; an agent never re-pins it (its own session is refused).
        _refuse('project_instructions:agent-session', f'a re-pin is the operator\'s action; an agent session '
                f'({present[0]}) is refused')
    for name, value in (('approved_by', approved_by), ('statement', statement)):
        if type(value) is not str or not value.strip():
            _refuse('project_instructions:approval', f'a re-pin records {name}')
    current = declared(run)
    if current is None:
        _refuse('project_instructions:not-pinned', 'this run pins no document yet; use `ravel project-instructions pin`')
    document = pin(path if path is not None else current['path'])
    if document == {k: current[k] for k in ('path', 'sha256', 'bytes')}:
        _refuse('project_instructions:unchanged', 'the document equals the current pin')
    approval = {'approved_by': approved_by.strip(), 'statement': statement.strip(), 'utc': broker.utc(),
                'replaces_sha256': current['sha256']}
    return _write(run, document, approval)


def text_of(pinned):
    """The pinned document's text, read now and checked against the pin."""
    source = Path(pinned['path'])
    raw = source.read_bytes() if source.is_file() and not source.is_symlink() else None
    if raw is None or hashlib.sha256(raw).hexdigest() != pinned['sha256']:
        item = 'project_instructions:changed'
        raise ProjectInstructionsError(
            f'project instructions refused: {item} ({source} no longer has the pinned sha256 {pinned["sha256"]}. '
            'The document may not change during a run. Restore the pinned text, or approve the new text with: '
            f'{repin_command(pinned.get("rundir") or "<run>")})', [item])
    return raw.decode('utf-8')


def for_run(rundir):
    """The run's pin with its run directory attached (for refusal messages), or None."""
    record = declared(rundir)
    if record is None:
        return None
    return {**{k: record[k] for k in ('path', 'sha256', 'bytes')}, 'rundir': str(_run(rundir))}


def nearest_run(start):
    """The nearest directory at or above ``start`` that holds an ``inputs`` folder, or None."""
    here = Path(os.path.realpath(start))
    return next((folder for folder in (here, *here.parents) if (folder / 'inputs').is_dir()), None)


def owning_run(start, named=None):
    """The run directory that owns ``start``, or None when no run holds it.

    A run is the nearest directory at or above ``start`` that holds an ``inputs`` folder, and
    the search stops there. When that run pins nothing and a directory further up does, the
    path lies in a run nested under another run's tree: the outer pin is not this run's
    declaration, so the caller is refused until it names the run itself.

    ``named`` is the run the caller named. It must be the nearest run when one holds ``start``,
    and it is then the owner whatever a directory further up pins.
    """
    folder = nearest_run(start)
    if named is not None:
        named = _run(named)
        if folder is not None and folder != named:
            _refuse('project_instructions:run-mismatch', f'{start} belongs to run {folder}, not to the named run {named}')
        return named
    if folder is None:
        return None
    pin_file = folder / PIN_FILE
    if not pin_file.exists() and not pin_file.is_symlink():
        outer = next((above for above in folder.parents if (above / PIN_FILE).is_file()), None)
        if outer is not None:
            _refuse('project_instructions:run-ambiguous',
                    f'{folder} pins no document and {outer} above it pins one; name the run that owns this '
                    'session with --rundir')
    return folder


def unsettled(exc):
    """True when a refusal says only that the nearest run must be named (``run-ambiguous``)."""
    return isinstance(exc, ProjectInstructionsError) and exc.missing == ['project_instructions:run-ambiguous']


def for_path(start, named=None):
    """The pin of the run that owns ``start`` (``owning_run``), or None when no run owns it or it pins nothing."""
    run = owning_run(start, named)
    return None if run is None else for_run(run)


def block(text, pinned):
    """The prompt's first block: one header line, the document verbatim, one closing line."""
    header = (f'{BLOCK_OPEN}\nThe project that owns this run declares the document below for every session. It is '
              f'reproduced verbatim (sha256 {pinned["sha256"]}, {pinned["bytes"]} bytes). Follow it together with '
              'the RAVEL instructions that come after it.\n\n')
    return header + text + ('' if text.endswith('\n') else '\n') + BLOCK_CLOSE + '\n\n'


def _carrier_flag(declaration, probe):
    """The confirmed template flag that carries the document, or None."""
    if type(declaration) is not dict or type(probe) is not dict or type(probe.get('flags')) is not dict:
        return None
    template = declaration.get('argv_template') or []
    for index, token in enumerate(template):
        if '{' + CARRIER + '}' in token:
            flag = token.split('=', 1)[0] if token.startswith('-') else (template[index - 1] if index else '')
            return flag if flag.startswith('-') and probe['flags'].get(flag) == 'confirmed' else None
    return None


def deliver(pinned, agent, probe, *, declaration=None, carrier=None, ancestor_files=()):
    """``(argv_additions, prompt_prefix, receipt_fields)`` for one session of ``agent``.

    ``argv_additions`` are template values for the route's argv rendering: the document
    file behind the route's confirmed flag, or None so the flag is dropped. ``prompt_prefix``
    goes before RAVEL's own prompt and is empty when the flag carries the text.
    ``receipt_fields`` is the record the session's receipt stores. With no pin all three
    are empty. ``carrier`` is where the flag mechanism writes the text (read-only).
    """
    if pinned is None:
        return {CARRIER: None}, '', None
    if type(agent) is not str or not agent:
        raise ValueError('deliver needs the agent name')
    text = text_of(pinned)
    flag = _carrier_flag(declaration, probe) if carrier is not None else None
    record = {'schema_version': 1, 'path': pinned['path'], 'sha256': pinned['sha256'], 'bytes': pinned['bytes'],
              'mechanism': 'system_prompt_append_flag' if flag else 'prompt_first_block', 'flag': flag,
              'position': POSITION,
              'ambient': {'ancestor_files': [dict(row) for row in ancestor_files], 'cli_reported_loaded': None}}
    if flag is None:
        return {CARRIER: None}, block(text, pinned), record
    target, raw = Path(carrier), text.encode('utf-8')
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.read_bytes() != raw:
            _refuse('project_instructions:carrier-changed', str(target))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o400)
    return {CARRIER: str(target)}, '', record


def for_packet(pinned):
    """``{text, record}`` for a work packet a host-started worker follows, or None with no pin.

    RAVEL writes no prompt for such a worker; the packet carries the text and tells the worker
    to read it first. The record's mechanism is ``work_packet``. Writing the packet is not
    delivery: RAVEL starts no process and sees no prompt. The record therefore shows delivery
    only once the host reports the sha256 of the document its subagent read (``acknowledged``)
    and that sha256 is the pinned one.
    """
    if pinned is None:
        return None
    return {'read_first': 'Read this project instruction document before anything else in this packet. When the '
                          'work is done, report the sha256 printed in this record with the final record, so the '
                          'receipt can show which document was read.',
            'text': text_of(pinned),
            'record': {'schema_version': 1, 'path': pinned['path'], 'sha256': pinned['sha256'],
                       'bytes': pinned['bytes'], 'mechanism': 'work_packet', 'flag': None, 'position': POSITION,
                       'ambient': {'ancestor_files': [], 'cli_reported_loaded': None}, ACKNOWLEDGEMENT: None}}


def acknowledged(record, reported):
    """A work-packet record with the sha256 the host reported for the document its subagent read."""
    value = json.loads(json.dumps(record))
    value[ACKNOWLEDGEMENT] = reported if _hex(reported) else None
    return value


def classify(path, pinned):
    """How an instruction file relates to the pin: ``declared``, ``import`` or None (not accepted).

    ``declared`` is the pinned file itself with the pinned bytes. ``import`` is a regular
    file whose whole content is one ``@<path>`` line that resolves to the pinned file.
    """
    path = Path(path)
    if pinned is None or path.is_symlink() or not path.is_file():
        return None
    target = Path(pinned['path'])
    if Path(os.path.realpath(path)) == target:
        raw = path.read_bytes()
        return 'declared' if hashlib.sha256(raw).hexdigest() == pinned['sha256'] else None
    try:
        content = path.read_text(encoding='utf-8').strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.startswith('@') or len(content.split()) != 1 or len(content) < 2:
        return None
    named = Path(content[1:]).expanduser()
    resolved = Path(os.path.realpath(named if named.is_absolute() else path.parent / named))
    if resolved != target or classify(target, pinned) != 'declared':
        return None
    return 'import'


def ancestor_row(path, pinned):
    """The receipt row for an accepted ancestor file."""
    path = Path(path)
    return {'path': str(path), 'relation': classify(path, pinned),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def with_cli_report(record, reported):
    """The record with the CLI's own report of loading an ancestor file: True, False or None (no report)."""
    if record is None:
        return None
    value = json.loads(json.dumps(record))
    value['ambient']['cli_reported_loaded'] = reported if type(reported) is bool else None
    return value


def record_of(receipt):
    """The delivery record a worker receipt or a one-shot session receipt carries, or None."""
    if type(receipt) is not dict:
        return None
    section = receipt.get('transport') if receipt.get('kind') == 'agent-worker-receipt' else receipt.get('configuration')
    return section.get('project_instructions') if type(section) is dict else None


def record_problem(record, pinned):
    """Why a delivery record does not show the pinned document (None when it does)."""
    if type(record) is not dict:
        return 'project_instructions:not-recorded'
    ambient = record.get('ambient')
    packet = record.get('mechanism') == 'work_packet'
    if (set(record) != RECORD_FIELDS | ({ACKNOWLEDGEMENT} if packet else set())
            or record['schema_version'] != 1 or record['mechanism'] not in MECHANISMS
            or record['position'] != POSITION or type(ambient) is not dict or set(ambient) != AMBIENT_FIELDS
            or type(ambient['ancestor_files']) is not list or ambient['cli_reported_loaded'] not in (True, False, None)
            or (record['mechanism'] == 'system_prompt_append_flag') != (type(record['flag']) is str)):
        return 'project_instructions:record-shape'
    if record['sha256'] != pinned['sha256'] or record['bytes'] != pinned['bytes']:
        return 'project_instructions:other-document'
    if packet and record[ACKNOWLEDGEMENT] != pinned['sha256']:
        # RAVEL prepared the text and observed no session; only the host's report says what was read.
        return 'project_instructions:unobserved'
    return None


def receipt_problem(receipt, pinned):
    """Why a session receipt earns no credit under this pin (None when it shows delivery, or with no pin)."""
    if pinned is None:
        return None
    return record_problem(record_of(receipt), pinned)


def supplied_problem(supplied, pinned):
    """Why an isolation block's ``project_instructions`` entry (sha256, bytes, mechanism) does not show the pin."""
    if pinned is None:
        return None
    if type(supplied) is not dict:
        return 'project_instructions:not-recorded'
    if set(supplied) != {'sha256', 'bytes', 'mechanism'} or supplied['mechanism'] not in MECHANISMS:
        return 'project_instructions:record-shape'
    if supplied['sha256'] != pinned['sha256'] or supplied['bytes'] != pinned['bytes']:
        return 'project_instructions:other-document'
    return None


def statement(record):
    """One clause for an isolation basis: the supplied document is declared, not leaked user configuration."""
    return 'RAVEL supplied one declared project instruction document; it is not user configuration'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel project-instructions', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, text in (('pin', 'pin the document for a run that has none yet'),
                       ('repin', 'replace the pin by an explicit approval'),
                       ('show', 'print the run\'s pin and whether the document still matches it')):
        sub = commands.add_parser(name, help=text)
        sub.add_argument('--rundir', type=Path, required=True)
        if name != 'show':
            sub.add_argument('--path', type=Path, required=name == 'pin', help='the instruction document')
        if name == 'repin':
            sub.add_argument('--approved-by', required=True, help='who approves the new text')
            sub.add_argument('--statement', required=True, help='why the text changed')
    args = parser.parse_args(argv)
    try:
        if args.command == 'pin':
            result = declare(args.rundir, args.path)
        elif args.command == 'repin':
            result = repin(args.rundir, approved_by=args.approved_by, statement=args.statement, path=args.path)
        else:
            record = for_run(args.rundir)
            result = {'declared': record is not None, 'pin': declared(args.rundir), 'document_matches': None}
            if record is not None:
                try:
                    text_of(record)
                    result['document_matches'] = True
                except ProjectInstructionsError as exc:
                    result.update(document_matches=False, refusal=str(exc))
    except ProjectInstructionsError as exc:
        print(json.dumps({'status': 'refused', 'missing': exc.missing, 'detail': str(exc)}, indent=2))
        return 3
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if args.command != 'show' or result['document_matches'] is not False else 3


if __name__ == '__main__':
    raise SystemExit(main())
