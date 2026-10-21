"""Conservative aggregate delegation reservations; failed attempts stay charged.

A controller-owned run keeps its reservations in its run store (``ravel.controller.step.budget``);
this run-tree ledger refuses it.
"""
from pathlib import Path
from . import state_io

FIELDS = {'max_seconds', 'max_events', 'max_children'}


def validate_limits(limits):
    if (type(limits) is not dict or set(limits) != FIELDS
            or any(type(v) is not int or v < 0 for v in limits.values())):
        raise ValueError('finite aggregate delegation ceilings required')
    return limits


def reserve(root, child, requested, limits):
    validate_limits(limits)
    if (type(child) is not str or not child or type(requested) is not dict
            or set(requested) != {'max_seconds', 'max_events'}
            or any(type(v) is not int or v < 0 for v in requested.values())):
        raise ValueError('explicit bounded child reservation required')
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('ordinary aggregate authority root required')
    from .agent_worker import controller_run
    if controller_run(root):
        raise ValueError('a controller-owned run reserves its budget in the run store, through its governed step')
    path = root / 'inputs/delegation_reservations.json'
    with state_io.file_lock(root / 'logs/completion-budget.lock'):
        record = state_io.read_json(path) if path.exists() else {'schema_version': 1, 'limits': limits, 'children': []}
        if record.get('limits') != limits or record.get('schema_version') != 1:
            raise ValueError('aggregate ceilings cannot change after reservation')
        rows = record['children']
        entry = {'child': child, **requested}
        if entry in rows:
            return record
        if any(r['child'] == child for r in rows):
            raise ValueError('changed child requires a new aggregate reservation identity')
        if (len(rows) + 1 > limits['max_children']
                or any(sum(r[k] for r in rows) + requested[k] > limits[k] for k in requested)):
            raise ValueError('aggregate delegated ceiling exceeded')
        record['children'].append(entry)
        state_io.atomic_json(path, record)
        return record


def reserve_delegated(document, declaration, base, *, check_only=False):
    """Called only after declaration authority is checked by scientific_autonomy."""
    limits = declaration['value']['bounds'].get('aggregate')
    if limits is None:
        return
    base = Path(base).absolute()
    # Scoped CHECK-IN 1 approval is over the contract; its exact frozen spec
    # supplies the parent binding and the one-attempt resource ceiling.
    scoped_path = base / 'inputs/scoped.json'
    bounded = state_io.read_json(scoped_path) if scoped_path.exists() else document
    binding = bounded.get('goal_binding') or document.get('goal_binding')
    if not binding:
        raise ValueError('aggregate delegated child requires original parent binding')
    from .task_completion import binding_projection
    binding_projection(binding, base_dir=base)
    root = Path(binding['contract']['path']).parent.parent
    # Ceilings are obtained from the authority-bound parent document, never a
    # child-written larger limit or a mutable accounting ledger.
    from . import scientific_autonomy
    parent = state_io.read_json(binding['contract']['path'])
    authority = scientific_autonomy.declaration(parent, root)
    if authority is None or authority['value']['bounds'].get('aggregate') != limits:
        raise ValueError('aggregate ceiling differs from retained parent delegation')
    budget = bounded.get('resource_budget', {})
    seconds = bounded.get('max_seconds', budget.get('max_wall_seconds'))
    attempts = bounded.get('max_attempts', 1)
    if type(attempts) is not int or attempts < 1: raise ValueError('finite aggregate attempt ceiling required')
    if seconds is not None: seconds *= attempts
    generation = bounded.get('generation', {})
    events = generation.get('events', budget.get('max_generated_events', 0))
    if 'parameter_points' in generation: events *= len(generation['parameter_points'])
    if bounded.get('mode') == 'model-events':
        from . import science
        events = science.adapter(bounded).event_ceiling(bounded['task'], base)
    events *= attempts
    entry = {'child': str(base), 'max_seconds': seconds, 'max_events': events}
    if check_only:
        record = state_io.read_json(root / 'inputs/delegation_reservations.json')
        if (record.get('limits') != limits or entry not in record.get('children', [])
                or len(record['children']) > limits['max_children']
                or any(sum(r[k] for r in record['children']) > limits[k] for k in ('max_seconds', 'max_events'))):
            raise ValueError('aggregate reservation is missing, changed or exceeds authority')
    else:
        reserve(root, str(base), {'max_seconds': seconds, 'max_events': events}, limits)
