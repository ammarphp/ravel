"""Custody of what a step consumes and adopts (mechanism M09).

A step consumes only artifacts the controller adopted earlier: each input names its producing
step and digest, that producer is a real prior dependency of the step, its custody record is
in the run store, the adopted bytes still have that digest, and its own inputs verify in turn,
so an unreceipted file is never laundered through a later governed step (T06, T07, C19). A
step is dispatched or launched only after every parent completed in the store, not on the
caller's word (SW39).

Adoption copies the declared outputs a governed worker or launch produced, by digest, into
``steps/<step>/`` of the run directory and appends one custody record per artifact. It refuses
before copying a byte when a required declared output is missing, when an output's bytes differ
from what the dispatcher credited, when the dispatcher's sealed spec differs from the one the
step dispatched, when an output sets a quantity its role does not own, or when the destination
already holds other bytes (CF05, CF07, G08). Host-authored waivers and other run-tree files
grant nothing here (I10).
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath

from .services import StepHold, digest, records

CUSTODY = 'custody'
OUTCOME = 'step-outcome'
MAX_DEPTH = 64


def _sha(path):
    from ..confine.inputs import hash_copy
    return hash_copy(path)[0]


def destination(step_id, path):
    return f'steps/{step_id}/{path}'


def attempt_step_id(step_id, attempt):
    """The deterministic immutable adoption namespace of one logical step attempt."""
    if type(attempt) is not int or attempt < 1:
        raise ValueError('an adoption attempt is a positive integer')
    return step_id if attempt == 1 else step_id[:80] + '.attempt-' + str(attempt) + '.' + digest(step_id)[:12]


def attempt_destination(step_id, path, attempt):
    return destination(attempt_step_id(step_id, attempt), path)


def custody_index(store):
    """``artifact -> latest custody record`` over the run store."""
    found = {}
    for row in records(store, CUSTODY):
        found[row['artifact']] = row
    return found


def outcomes(store):
    """``step id -> latest outcome record``."""
    found = {}
    for row in records(store, OUTCOME):
        found[row['step_id']] = row
    return found


def parent_errors(store, step):
    """Every dependency completed in the store (the dispatch-time parent check)."""
    done = outcomes(store)
    errors = []
    for parent in step['depends_on']:
        record = done.get(parent)
        if record is None or record.get('status') != 'completed':
            errors.append({'code': 'parent_incomplete', 'parent': parent,
                           'status': None if record is None else record.get('status')})
    return errors


def _verify(index, artifact, run_dir, seen, depth, store):
    if depth > MAX_DEPTH:
        return [{'code': 'custody_chain_too_deep', 'artifact': artifact}]
    if artifact in seen:
        return []
    seen.add(artifact)
    record = index.get(artifact)
    if record is None:
        return [{'code': 'predecessor_unreceipted', 'artifact': artifact}]
    if record.get('status') != 'accepted':
        return [{'code': 'predecessor_not_accepted', 'artifact': artifact}]
    target = Path(run_dir) / record['destination']
    try:
        if target.is_symlink() or not target.is_file() or _sha(target) != record['sha256']:
            raise ValueError('predecessor changed')
        verified_attachments(record, run_dir)
    except (OSError, ValueError, KeyError, TypeError, StepHold):
        return [{'code': 'predecessor_bytes_changed', 'artifact': artifact}]
    from . import host_operations
    errors = host_operations.custody_errors(store, record)
    for parent in record.get('inputs') or ():
        errors += _verify(index, parent, run_dir, seen, depth + 1, store)
    return errors


def verified_attachments(record, run_dir):
    """Return only the exact manifest-bound attachments of an adopted artifact."""
    from . import member_manifest
    producer = record.get('producer') or {}
    trusted = (producer.get('kind') == 'launch' and producer.get('backend') == 'controller-acquisition'
               and producer.get('operation') == 'acquire-published')
    run = Path(run_dir)
    target = run / record.get('destination', '')
    if 'attachments' not in record:
        if trusted and target.name == 'hepdata_manifest.json' and member_manifest.KEY in member_manifest.load(target):
            raise StepHold('input_changed', 'acquisition member attachments are missing')
        return []
    if not trusted:
        raise StepHold('input_changed', 'compound attachments require a trusted acquisition receipt')
    if _sha(target) != record['sha256']:
        raise StepHold('input_changed', 'acquisition manifest changed after verification')
    try:
        member_manifest.verify(target, attachments=[
            {**row, 'destination': (run / row['destination']).as_posix()} for row in record['attachments']])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StepHold('input_changed', str(exc)) from None
    return deepcopy(record['attachments'])


def input_errors(store, step, run_dir, *, ancestors=()):
    """``(errors, custody records, run inputs)`` for the step's inputs, verified transitively.

    An artifact another step produced is consumed only from an accepted custody record of a real
    prior dependency (its digest, when the plan pins one, must match). A file under ``inputs/`` of
    the run directory is a run input the controller wrote; it is pinned by digest at dispatch.
    """
    index = custody_index(store)
    allowed = set(step['depends_on']) | set(ancestors)
    errors, found, run_inputs = [], [], []
    run = Path(run_dir)
    for row in step['inputs']:
        artifact, wanted = row['artifact'], row.get('sha256')
        record = index.get(artifact)
        if record is not None:
            if record['step_id'] not in allowed:
                errors.append({'code': 'input_without_dependency', 'artifact': artifact, 'producer': record['step_id']})
            elif record.get('status') != 'accepted':
                errors.append({'code': 'predecessor_not_accepted', 'artifact': artifact, 'status': record.get('status')})
            elif wanted is not None and record['sha256'] != wanted:
                errors.append({'code': 'predecessor_digest_differs', 'artifact': artifact})
            else:
                problems = _verify(index, artifact, run, set(), 0, store)
                errors += problems
                if not problems:
                    found.append(deepcopy(record))
            continue
        if Path(artifact).parts[:1] == ('inputs',):
            target = run / artifact
            linked = any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(run) and p != run)
            if linked or not target.is_file():
                if row.get('required', True):
                    errors.append({'code': 'run_input_missing', 'artifact': artifact})
                continue
            sha = _sha(target)
            if wanted is not None and sha != wanted:
                errors.append({'code': 'run_input_changed', 'artifact': artifact})
                continue
            run_inputs.append({'artifact': artifact, 'path': artifact, 'sha256': sha})
            continue
        if row.get('required', True):
            errors.append({'code': 'predecessor_unreceipted', 'artifact': artifact})
    return errors, found, run_inputs


def accept(store, adopted, status, *, evidence=None):
    """Append the validators' verdict for each staged artifact: ``accepted`` or ``rejected``."""
    if status not in ('accepted', 'rejected'):
        raise ValueError('a custody verdict is accepted or rejected')
    rows = []
    for record in adopted:
        row = {**{k: v for k, v in record.items() if k != 'record_id'}, 'status': status,
               'verdict_of': record.get('record_id'), 'evidence': deepcopy(evidence)}
        row['record_id'] = store.append(CUSTODY, row)
        rows.append(row)
    return rows


def _owned(card, quantities):
    owned = set(((card or {}).get('ownership') or {}).get('owns') or ())
    for path, quantity in quantities.items():
        if quantity is not None and quantity not in owned:
            raise StepHold('ownership_not_owner', f"{(card or {}).get('id')} does not own quantity {quantity} ({path})")


def worker_adoption(store, *, run_dir, step, attempt, card, receipt, workspace, sealed_spec_sha256,
                    recorded_spec, outputs, inputs_custody, final_path=None, sidecar=False,
                    sidecar_path='final-record.json'):
    """Adopt a worker's credited outputs; refuse before any copy when a condition fails.

    ``outputs`` are the declared rows (worker ``path`` under ``outputs/`` and the ``plan_path`` it
    adopts to); a card with a sidecar also adopts its final record, at ``sidecar_path``.
    """
    from . import host_operations
    host_operations.admit(store, step, attempt, branch='worker')
    from .spec import quantities as declared_quantities
    if digest(recorded_spec) != sealed_spec_sha256:
        raise StepHold('work_order_fidelity', 'the dispatcher custody spec differs from the spec the step sealed')
    credited = {row['path']: row for row in receipt.get('credited_outputs') or ()}
    missing = [row['plan_path'] for row in outputs if row['required'] and row['path'] not in credited]
    if missing:
        raise StepHold('declared_output_missing', 'required declared outputs were not credited: ' + ', '.join(missing),
                       evidence={'missing': missing})
    quantities = declared_quantities(step)
    _owned(card, quantities)
    rows = []
    for row in outputs:
        found = credited.get(row['path'])
        if found is None:
            continue
        source = Path(workspace) / row['path']
        if source.is_symlink() or not source.is_file() or _sha(source) != found['sha256']:
            raise StepHold('adoption_bytes_changed', f"{row['plan_path']} differs from the bytes the dispatcher credited")
        rows.append((row['plan_path'], source, found['sha256'], row['kind']))
    if sidecar and final_path is not None:
        final = Path(final_path)
        if final.is_file() and not final.is_symlink():
            rows.append((sidecar_path, final, _sha(final), 'final-record'))
    return _copy(store, run_dir=run_dir, step=step, attempt=attempt, rows=rows, card=card,
                 producer={'kind': 'worker', 'node_id': receipt['node_id'], 'attempt': receipt['attempt'],
                           'receipt_sha256': digest(receipt), 'session_id': receipt.get('session_id'),
                           'role': (receipt.get('role') or {}).get('id')},
                 quantities=quantities, inputs_custody=inputs_custody)


def launch_adoption(store, *, run_dir, step, attempt, card, launch, outputs, inputs_custody,
                    output_prefix='outputs/', host_store=None, host_step=None):
    """Adopt declared outputs from the launch inventory's own source layout.

    A launch whose output root is itself the ``output_prefix`` directory (native launches
    run inside ``outputs/``) wrote each declared plan path with that one prefix removed;
    the full plan path there is an extra directory, not the declared output. Any other
    root (a subgraph passes an empty prefix; a bespoke root has no layout prefix) holds
    the plan paths as written. The chosen relative source path is recorded per custody
    record; artifact identities and adoption destinations always retain the plan paths.
    A host operation's protected receipt is bound from ``host_store``/``host_step`` (the
    acting step's own store and identity) when the adoption scope differs from them.
    """
    from .spec import quantities as declared_quantities
    from . import host_operations
    host_receipt = host_operations.receipt(host_store if host_store is not None else store,
                                           host_step if host_step is not None else step, attempt, launch)
    root = Path(launch['output_root'])
    inventory = launch.get('inventory') or []
    observed = {row['path']: row['sha256'] for row in inventory}
    if len(observed) != len(inventory):
        raise StepHold('adoption_bytes_changed', 'launch inventory contains duplicate paths')
    compound = (bool(host_receipt) and launch.get('backend') == host_operations.ACQUISITION_BACKEND
                and step.get('kind') == 'acquire' and step.get('operation') == 'acquire-published')
    attachments = {}
    if compound:
        from . import member_manifest
        # Trusted acquisition authorizes exactly its complete observed output tree.
        actual = []
        try:
            for item in member_manifest.member_files(root):
                actual.append({'path': item.relative_to(root).as_posix(), 'sha256': _sha(item),
                               'bytes': item.stat().st_size})
        except (ValueError, OSError) as exc:
            raise StepHold('adoption_bytes_changed', str(exc)) from None
        if actual != inventory:
            raise StepHold('adoption_bytes_changed', 'acquisition launch inventory differs from actual tree')


    strip = bool(output_prefix) and root.name == PurePosixPath(output_prefix).name

    def located(plan_path):
        source_path = plan_path.removeprefix(output_prefix) if strip else plan_path
        return source_path if source_path in observed else None

    missing = [row['plan_path'] for row in outputs if row['required'] and located(row['plan_path']) is None]
    if missing:
        raise StepHold('declared_output_missing', 'required declared outputs were not written: ' + ', '.join(missing),
                       evidence={'missing': missing})
    quantities = declared_quantities(step)
    _owned(card, quantities)
    rows = []
    for row in outputs:
        source_path = located(row['plan_path'])
        if source_path is None:
            continue
        source = root / source_path
        linked = any(part.is_symlink() for part in (source, *source.parents)
                     if part.is_relative_to(root))
        if (not source.resolve().is_relative_to(root.resolve()) or linked
                or not source.is_file() or _sha(source) != observed[source_path]):
            raise StepHold('adoption_bytes_changed', f"{row['plan_path']} differs from the launch inventory")
        if compound and source.name == 'hepdata_manifest.json':
            try:
                document = member_manifest.load(source)
                if member_manifest.KEY in document:
                    members = member_manifest.verify(source)
                    attachments[row['plan_path']] = members
                    permitted = {source_path, *(str(PurePosixPath(source_path).parent / r['blob']) for r in members)}
                    if set(observed) != permitted:
                        raise ValueError('acquisition inventory has undeclared members')
            except (ValueError, OSError) as exc:
                raise StepHold('adoption_bytes_changed', str(exc)) from None
        rows.append((row['plan_path'], source, observed[source_path], row['kind'], source_path))
    return _copy(store, run_dir=run_dir, step=step, attempt=attempt, rows=rows, card=card,
                 producer={'kind': 'launch', 'journal_id': launch.get('journal_id'), 'exit_status': launch.get('exit_status'),
                           'launch_sha256': launch.get('launch_sha256'), 'backend': launch.get('backend'),
                           **(host_receipt or {})},
                 quantities=quantities, inputs_custody=inputs_custody, attachments=attachments)


def subgraph_adoption(store, *, run_dir, step, attempt, card, child, inputs_custody, source_step_id=None):
    """Stage the research adapter's exact pinned outputs through the ordinary custody and checks path.

    The adapter writes each declared output at ``steps/<source step>/<path>`` (``source_step_id``, the logical
    step, defaults to ``step``) and pins its bytes and size; every pin must be one declared output and every
    required declared output must be pinned exactly once. A controller-written progress record is operational
    evidence: this adoption makes no statement that its scientific result or the parent task was accepted.
    """
    from .spec import quantities as declared_quantities
    if child.get('outcome') != 'ok' or child.get('graph_id') != 'research.loop':
        raise StepHold('subgraph_incomplete', 'only a completed research adapter stages its declared outputs')
    quantities = declared_quantities(step)
    _owned(card, quantities)
    supplied = child.get('outputs') or []
    rows = []
    run = Path(run_dir).resolve(strict=True)
    for declared in step['outputs']:
        source = run / destination(source_step_id or step['id'], declared['path'])
        matching = [pin for pin in supplied if type(pin) is dict and Path(pin.get('path', '')) == source]
        if len(matching) != 1:
            if declared.get('required', True):
                raise StepHold('declared_output_missing', 'research adapter must pin exactly one ' + declared['path'])
            continue
        pin = matching[0]
        if (any(part.is_symlink() for part in (source, *source.parents)) or not source.is_file()
                or _sha(source) != pin.get('sha256') or source.stat().st_size != pin.get('size')):
            raise StepHold('adoption_bytes_changed', 'research progress differs from its adapter pin')
        rows.append((declared['path'], source, pin['sha256'], declared['kind']))
    if len(rows) != len(supplied):
        raise StepHold('subgraph_output_population', 'every research adapter output must be declared exactly once')
    return _copy(store, run_dir=run, step=step, attempt=attempt, rows=rows, card=card,
                 producer={'kind': 'subgraph', 'graph_id': child['graph_id'],
                           'results_sha256': child['results_sha256']},
                 quantities=quantities, inputs_custody=inputs_custody)


def _copy(store, *, run_dir, step, attempt, rows, card, producer, quantities, inputs_custody, attachments=None):
    from .member_manifest import copy_lock
    with copy_lock(store):
        return _copy_locked(store, run_dir=run_dir, step=step, attempt=attempt, rows=rows, card=card,
                            producer=producer, quantities=quantities, inputs_custody=inputs_custody,
                            attachments=attachments)


def _copy_locked(store, *, run_dir, step, attempt, rows, card, producer, quantities, inputs_custody, attachments=None):
    run = Path(run_dir)
    targets = []
    for path, source, sha, kind, *located in rows:
        relative = destination(step['id'], path)
        target = run / relative
        for part in (target, *target.parents):
            if part == run:
                break
            if part.is_symlink():
                raise StepHold('adoption_destination_invalid', relative)
        if target.exists() and (not target.is_file() or _sha(target) != sha):
            raise StepHold('adoption_destination_occupied', f'{relative} already holds other bytes')
        targets.append((path, source, sha, kind, relative, target, located[0] if located else None))
    # Include all blobs in the pre-copy destination and source checks. They remain attachments
    # of their manifest, never independently authored artifacts.
    attached_targets = {}
    for path, source, sha, kind, relative, target, source_path in targets:
        members = (attachments or {}).get(path, [])
        attached_targets[path] = []
        for row in members:
            blob_source, blob_target = Path(source).parent / row['blob'], target.parent / row['blob']
            if _sha(blob_source) != row['sha256'] or blob_source.stat().st_size != row['bytes']:
                raise StepHold('adoption_bytes_changed', 'acquisition attachment changed')
            if any(p.is_symlink() for p in (blob_target, *blob_target.parents)):
                raise StepHold('adoption_destination_invalid', str(blob_target))
            if blob_target.exists() and (not blob_target.is_file() or _sha(blob_target) != row['sha256']):
                raise StepHold('adoption_destination_occupied', str(blob_target))
            attached_targets[path].append((row, blob_source, blob_target))
    from .member_manifest import admit_copies, copy_checked, verify as verify_members
    from ravel.workflow import private_files
    all_copies = [(source, target, sha) for path, source, sha, kind, relative, target, source_path in targets]
    all_copies += [(src, dst, row['sha256']) for members in attached_targets.values() for row, src, dst in members]
    admit_copies(run, all_copies, store=store)
    created = []
    try:
        for path, source, sha, kind, relative, target, source_path in targets:
            copies = [(source, target, sha)] + [(src, dst, row['sha256'])
                      for row, src, dst in attached_targets[path]]
            for src, dst, expected in copies:
                if dst.exists():
                    continue
                private_files.mkdir(dst.parent)
                actual, mode = copy_checked(src, dst)
                created.append(dst)
                dst.chmod(mode & 0o600)
                if actual != expected:
                    raise StepHold('adoption_bytes_changed', f'{path} changed during adoption')
        for path, source, sha, kind, relative, target, source_path in targets:
            if path in (attachments or {}):
                try:
                    verify_members(target, attachments=[{**row, 'destination': dst.as_posix()}
                                   for row, src, dst in attached_targets[path]])
                except (ValueError, OSError) as exc:
                    raise StepHold('adoption_bytes_changed', str(exc)) from None
    except BaseException:
        for dst in reversed(created):
            dst.unlink(missing_ok=True)
        raise
    adopted = []
    parents = sorted(record['artifact'] for record in inputs_custody)
    for path, source, sha, kind, relative, target, source_path in targets:
        record = {'schema_version': 1, 'artifact': f"{step['id']}:{path}", 'step_id': step['id'],
                  'attempt': attempt, 'path': path, 'destination': relative, 'sha256': sha, 'kind': kind,
                  'quantity': quantities.get(path), 'owner_role': producer.get('host_role') or (card or {}).get('id'), 'producer': deepcopy(producer),
                  'inputs': parents, 'rung': step.get('rung'), 'status': 'staged'}
        if path in (attachments or {}):
            record['attachments'] = [{**row, 'destination': dst.relative_to(run).as_posix()}
                                     for row, src, dst in attached_targets[path]]
        if source_path is not None:
            record['source_path'] = source_path
        record['record_id'] = store.append(CUSTODY, record)
        adopted.append(record)
    return adopted


def record_outcome(store, step, attempt, status, **fields):
    return store.append(OUTCOME, {'schema_version': 1, 'step_id': step['id'], 'attempt': attempt, 'status': status,
                                  **deepcopy(fields)})
