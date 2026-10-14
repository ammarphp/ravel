"""Parent-bound child registration and run-kind adapters, without launch authority."""
import json
from copy import deepcopy
from pathlib import Path
from . import state_io

KINDS = {'science', 'scoped', 'route-a', 'research', 'calculation'}
LEDGER = 'inputs/children.jsonl'


def specification(root, inputs):
    root = Path(root)
    for kind, path in [('science', 'inputs/science.json'), ('scoped', 'inputs/scoped.json'),
                       ('route-a', 'inputs/task_contract.json')]:
        if (root / path).exists():
            pin = inputs.capture(root / path)
            doc = inputs.document(pin)
            if kind == 'route-a' and doc.get('task_mode') in ('research', 'calculation'):
                kind = doc['task_mode']
            return kind, pin, doc
    raise ValueError('child requires a bound science, scoped or task specification')


def checkin_projection(binding, base):
    from .task_completion import binding_projection
    value = binding_projection(binding, base_dir=base)
    return {'goal_binding': deepcopy(binding),
            'parent_obligations': deepcopy(value['assignment']['coverage'])}


def ledger(root, inputs):
    path = Path(root) / LEDGER
    if not path.exists():
        inputs.absent(path); rows = []
    else:
        raw, _ = inputs.file(inputs.capture(path))
        rows = [json.loads(line, object_pairs_hook=state_io._unique) for line in raw.decode().splitlines()]
    for row in _source_children(root, inputs):
        if row not in rows: rows.append(row)
    if len(rows) > 128:
        raise ValueError('child ledger exceeds128')
    seen = set()
    for row in rows:
        if (type(row) is not dict or set(row) != {'assignment_id', 'rundir', 'run_kind'}
                or row['run_kind'] not in KINDS or type(row['rundir']) is not str
                or not Path(row['rundir']).is_absolute()):
            raise ValueError('typed ordinary child registration required')
        key = (row['assignment_id'], row['rundir'])
        if key in seen:
            raise ValueError('duplicate child ledger registration')
        seen.add(key)
    return rows


def _source_children(root, inputs):
    """Reuse existing collectors for denominator discovery, never acceptance."""
    from .completion_disclosure import _bound
    from . import candidate_experiments as ce
    path = Path(root) / 'inputs/completion_sources.json'
    if not path.exists():
        inputs.absent(path); return []
    sources = inputs.document(inputs.capture(path))
    if (sources.get('schema_version') != 1 or set(sources) - {'schema_version', 'resonance', 'research_cycles'}):
        raise ValueError('typed existing completion source ledger required')
    discovered = []
    def observe(reader):
        value = reader(); digest = ce.digest(value)
        def ending():
            if ce.digest(reader()) != digest:
                raise ValueError('completion source ledger changed during evaluation')
        inputs.ending_checks.append(ending)
        return value
    if sources.get('resonance') is not None:
        from . import resonance_study
        source = sources['resonance']
        recipe = _bound(source['request'], inputs, root)
        if inputs.document(recipe).get('parent_contract') != inputs.capture(Path(root) / 'inputs/task_contract.json'):
            raise ValueError('collection must bind this exact original parent')
        runs = deepcopy(source['runs'])
        if type(runs) is not dict or len(runs) > 128: raise ValueError('bounded existing result map required')
        view = observe(lambda: resonance_study.collect(recipe['path'], runs, None))
        discovered.extend(row['rundir'] for row in view['stages'] if row.get('rundir'))
    cycles = sources.get('research_cycles', [])
    if type(cycles) is not list or len(cycles) > 128: raise ValueError('bounded research cycle census required')
    for pin in cycles:
        from . import research_cycle
        head = _bound(pin, inputs, root); cycle_root = Path(head['path']).parent
        if Path(head['path']).name != 'head.json': raise ValueError('current research head required')
        def read_cycle(cycle_root=cycle_root):
            _, state = research_cycle._load(cycle_root)
            return {'state': state, 'status': research_cycle.status(cycle_root)}
        view = observe(read_cycle)
        discovered.extend(row['rundir'] for row in view['state']['experiments'] if row.get('rundir'))
    rows = []
    parent = inputs.capture(Path(root) / 'inputs/task_contract.json')
    for rundir in dict.fromkeys(discovered):
        rd = Path(rundir).absolute(); kind, _, spec = specification(rd, inputs)
        binding = spec.get('goal_binding')
        if type(binding) is not dict or binding.get('contract') != parent:
            raise ValueError('collected child must bind exact original parent')
        rows.append({'assignment_id': binding['assignment_id'], 'rundir': str(rd), 'run_kind': kind})
    return rows


def register_child(child, binding, *, run_kind):
    from .task_completion import _Inputs, binding_projection
    if run_kind not in KINDS:
        raise ValueError('known child run kind required')
    child = Path(child).absolute()
    binding_projection(binding, base_dir=child)
    contract_path = Path(binding['contract']['path'])
    parent = contract_path.parent.parent if contract_path.parent.name == 'inputs' else contract_path.parent
    observed = _Inputs(parent)
    try:
        observed.file(binding['contract'])
        kind, _, spec = specification(child, observed)
        if spec.get('goal_binding') != binding or kind != run_kind:
            raise ValueError('registration must bind actual child kind and parent assignment')
        with state_io.file_lock(parent / 'logs/completion-children.lock'):
            rows = ledger(parent, observed)
            entry = {'assignment_id': binding['assignment_id'], 'rundir': str(child), 'run_kind': run_kind}
            if entry in rows:
                observed.finish()
                return entry
            if any(r['rundir'] == str(child) for r in rows):
                raise ValueError('child already registered to another assignment')
            observed.finish()
            # Atomic replacement keeps readers from seeing a partial JSONL line.
            import os, tempfile
            (parent / 'inputs').mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=parent / 'inputs', prefix='.children-')
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(''.join(json.dumps(r, sort_keys=True) + '\n' for r in [*rows, entry]))
                    stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, parent / LEDGER)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            return entry
    finally:
        observed.close()
