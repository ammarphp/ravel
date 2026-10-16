"""Finite prepared-study grids over the ordinary allocation launcher.

No model, generator, analysis, statistic or scheduler policy is selected here.
The manifest and append-only attempt population are bound in a locked ledger.
An ambiguous submit is reserved before the remote call and never silently retried.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

from . import allocation_study as allocation
from .state_io import atomic_json, file_lock, read_json

SCHEMA = 1
LEDGER = 'ledger.json'
TERMINAL = {'completed', 'failed', 'cancelled', 'timed-out'}
OBSERVED = TERMINAL | {'pending', 'running', 'unknown', 'missing'}


def _keys(row, required, optional=()):
    if not isinstance(row, dict) or set(row) - set(required) - set(optional) or set(required) - set(row):
        raise ValueError(f'expected fields {sorted(required)}, optional {sorted(optional)}')


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('expected a nonempty string')
    return value


def _positive(value):
    if type(value) is not int or value < 1:
        raise ValueError('expected a positive integer')
    return value


def _deadline(value):
    try:
        stamp = datetime.fromisoformat(_text(value).replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('expiry must be an ISO timestamp with timezone') from None
    if stamp.tzinfo is None:
        raise ValueError('expiry must include a timezone')
    return stamp


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _path(base, name):
    return (base / _text(name)).resolve()


def _relative(name):
    path = Path(_text(name))
    if path.is_absolute() or '..' in path.parts or str(path) == '.':
        raise ValueError('artifact source must be a relative file within its study')
    return str(path)


@dataclass(frozen=True)
class Axis:
    name: str
    values: tuple


@dataclass(frozen=True)
class GridCell:
    id: str
    axes: dict
    scenario: str
    study_spec: str
    rundir: str
    agent: tuple[str, ...]


@dataclass(frozen=True)
class GridManifest:
    schema_version: int
    axes: tuple[Axis, ...]
    scenarios: tuple[str, ...]
    cells: tuple[GridCell, ...]
    approval: dict
    budget: dict
    allocation: dict
    concurrency: int
    quantities: tuple[dict, ...]
    artifacts: tuple[str, ...]

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        doc, base = read_json(path), path.parent
        _keys(doc, ('schema_version', 'axes', 'scenarios', 'cells', 'approval', 'budget',
                    'allocation', 'concurrency', 'quantities'), ('artifacts',))
        if type(doc['schema_version']) is not int or doc['schema_version'] != SCHEMA:
            raise ValueError('unsupported study-grid schema')
        axes = []
        if not isinstance(doc['axes'], list) or not doc['axes']:
            raise ValueError('declare nonempty axes')
        for row in doc['axes']:
            _keys(row, ('name', 'values'))
            values = row['values']
            if not isinstance(values, list) or not values or any(
                type(v) not in (str, int, float) or (type(v) is float and not math.isfinite(v)) for v in values
            ) or len(set(values)) != len(values):
                raise ValueError('axis values must be distinct finite numbers or strings')
            axes.append(Axis(_text(row['name']), tuple(values)))
        names = [a.name for a in axes]
        if len(set(names)) != len(names):
            raise ValueError('axis names must be distinct')
        scenarios = doc['scenarios']
        if not isinstance(scenarios, list) or not scenarios or any(not isinstance(s, str) or not s for s in scenarios):
            raise ValueError('declare nonempty scenario names')
        if len(set(scenarios)) != len(scenarios):
            raise ValueError('scenario names must be distinct')
        cells, ids, coordinates, rundirs = [], set(), set(), set()
        if not isinstance(doc['cells'], list):
            raise ValueError('cells must be a list')
        for row in doc['cells']:
            _keys(row, ('id', 'axes', 'scenario', 'study_spec', 'rundir', 'agent'))
            cid = _text(row['id'])
            if not isinstance(row['axes'], dict) or set(row['axes']) != set(names):
                raise ValueError('cell must supply every declared axis')
            for a in axes:
                value = row['axes'][a.name]
                if type(value) not in (int, float, str) or value not in a.values:
                    raise ValueError('cell coordinate is outside declared axes')
            scenario = _text(row['scenario'])
            coordinate = tuple(row['axes'][n] for n in names) + (scenario,)
            rd = str(_path(base, row['rundir']))
            if cid in ids or coordinate in coordinates or rd in rundirs or scenario not in scenarios:
                raise ValueError('duplicate cell, coordinate, run directory or undeclared scenario')
            argv = row['agent']
            if not isinstance(argv, list) or not argv or any(not isinstance(s, str) or not s for s in argv):
                raise ValueError('cell agent must be a nonempty argv list')
            ids.add(cid)
            coordinates.add(coordinate)
            rundirs.add(rd)
            cells.append(GridCell(cid, row['axes'], scenario, str(_path(base, row['study_spec'])), rd, tuple(argv)))
        expected = math.prod(len(a.values) for a in axes) * len(scenarios)
        if len(cells) != expected:
            raise ValueError('supply exactly one prepared cell for every axes/scenario combination')
        _keys(doc['approval'], ('rundir', 'route', 'rung', 'approval_files', 'expires_utc'))
        approval = dict(doc['approval'])
        approval['rundir'] = str(_path(base, approval['rundir']))
        if approval['route'] not in allocation.ROUTES or approval['rung'] not in allocation.RUNGS:
            raise ValueError('unknown delegated approval route or rung')
        if not isinstance(approval['approval_files'], dict):
            raise ValueError('approval_files must contain approval path/digest pairs')
        _deadline(approval['expires_utc'])
        budget = doc['budget']
        _keys(budget, ('max_submissions', 'max_cpu_minutes', 'expires_utc'))
        _positive(budget['max_submissions'])
        _positive(budget['max_cpu_minutes'])
        _deadline(budget['expires_utc'])
        if not isinstance(doc['allocation'], dict):
            raise ValueError('allocation must be an object')
        profile = dict(doc['allocation'])
        _keys(profile, ('account', 'partition', 'cpus', 'minutes'),
              ('checkout', 'venv', 'prefix', 'modules', 'env', 'claude_config_dir', 'collect_to', 'job_name'))
        for key in ('modules', 'env'):
            if key in profile and (not isinstance(profile[key], list) or any(not isinstance(v, str) for v in profile[key])):
                raise ValueError(f'allocation {key} must be a list of strings')
        _positive(profile['cpus'])
        _positive(profile['minutes'])
        for key in ('checkout', 'venv', 'prefix', 'claude_config_dir', 'collect_to'):
            if key in profile:
                profile[key] = str(_path(base, profile[key]))
        quantities, qnames = [], set()
        if not isinstance(doc['quantities'], list):
            raise ValueError('quantities must be a list')
        for q in doc['quantities']:
            _keys(q, ('name', 'source', 'field'))
            name = _text(q['name'])
            if name in qnames:
                raise ValueError('quantity names must be distinct')
            qnames.add(name)
            quantities.append(dict(name=name, source=_relative(q['source']), field=_text(q['field'])))
        artifacts = doc.get('artifacts', [])
        if not isinstance(artifacts, list):
            raise ValueError('artifacts must be a list of relative file paths')
        artifacts = tuple(_relative(a) for a in artifacts)
        if len(set(artifacts)) != len(artifacts) or set(artifacts) & qnames:
            raise ValueError('artifact paths and quantity names must be distinct')
        return cls(SCHEMA, tuple(axes), tuple(scenarios), tuple(cells), approval, budget, profile,
                   _positive(doc['concurrency']), tuple(quantities), artifacts)


@dataclass(frozen=True)
class Artifact:
    path: str
    sha256: str
    field: str | None


@dataclass(frozen=True)
class HarvestCell:
    id: str
    axes: dict
    scenario: str
    status: str
    job_id: str | None
    artifacts: dict[str, Artifact]
    values: dict
    detail: str | None
    attempts: list
    overridden: bool
    regime: str
    override: dict | None
    receipt_sha256: str | None


@dataclass(frozen=True)
class GridHarvest:
    schema_version: int
    kind: str
    manifest_sha256: str
    axes: tuple[Axis, ...]
    scenarios: tuple[str, ...]
    quantities: tuple[dict, ...]
    cells: tuple[HarvestCell, ...]


def _load(manifest, directory, *, create=False):
    grid = GridManifest.load(manifest)
    identity = _digest(asdict(grid))
    path = directory / LEDGER
    if path.exists():
        ledger = read_json(path)
        if ledger.get('manifest_sha256') != identity:
            raise ValueError('grid manifest changed; use a new grid directory')
        if set(ledger.get('cells', {})) != {c.id for c in grid.cells}:
            raise ValueError('grid ledger population changed; cells cannot be silently dropped')
    elif create:
        ledger = {'schema_version': SCHEMA, 'manifest_sha256': identity, 'cells': {
            c.id: {'study_spec_sha256': allocation._sha(c.study_spec), 'attempts': []} for c in grid.cells}}
        atomic_json(path, ledger)
    else:
        raise ValueError('grid has no ledger; submit it first')
    return grid, ledger


def override_context(grid):
    return _digest({**{k: asdict(grid)[k] for k in ('axes', 'scenarios', 'cells', 'quantities')},
                    'base_inputs': {c.id: allocation._sha(c.study_spec) for c in grid.cells}})


def record_override(manifest, directory, cell_id, request):
    """Record an explicit cell repair without changing the immutable grid manifest."""
    from . import point_overrides as overrides
    directory = Path(directory).resolve()
    with file_lock(directory / '.lock'):
        grid, ledger = _load(manifest, directory, create=True)
        _refresh(ledger)
        population = {c.id: {**asdict(c), 'override': ledger['cells'][c.id].get('override')} for c in grid.cells}
        if cell_id not in population:
            raise ValueError('override names an unknown cell')
        entry = ledger['cells'][cell_id]
        if entry['attempts'] and entry['status'] not in TERMINAL | {'missing'}:
            raise ValueError('cannot override a live or ambiguous cell')
        cell = population[cell_id]
        if allocation._sha(cell['study_spec']) != entry['study_spec_sha256']:
            raise ValueError('prepared study specification changed')
        settings = read_json(Path(cell['study_spec']))
        def successful_neighbour(c):
            other = ledger['cells'][c['id']]
            if other['status'] != 'completed' or not other['attempts']:
                return []
            root = Path(other['attempts'][-1]['result_root'])
            return [overrides.pin(root / q['source']) for q in grid.quantities if (root / q['source']).is_file()]
        record, effective = overrides.admit(cell_id, request, settings, point=cell,
            population=population, axes=[asdict(a) for a in grid.axes],
            successful=successful_neighbour,
            context_sha256=override_context(grid),
            evidence_directory=Path(cell['rundir']) / 'inputs/point-overrides/evidence')
        # A generic agent must explicitly consume the effective specification.
        if cell['study_spec'] not in cell['agent'] and '{study_spec}' not in cell['agent']:
            raise ValueError('cell agent argv must bind the study_spec path or {study_spec}')
        path = Path(cell['study_spec']).parent / ('override-' + record['receipt_sha256'] + '.json')
        atomic_json(path, effective)
        if entry.get('override') and entry['override'] != record:
            entry.setdefault('override_history', []).append({'override': entry['override'],
                'effective_study_spec': entry['effective_study_spec']})
        entry.update(override=record, effective_study_spec=str(path))
        atomic_json(directory / LEDGER, ledger)
        return record


def _refresh(ledger):
    for cell in ledger['cells'].values():
        for attempt in cell['attempts']:
            if attempt['status'] in TERMINAL:
                continue
            directory = Path(attempt['request_dir'])
            if not (directory / 'request.json').is_file():
                attempt.update(status='missing', error='allocation request artifact missing')
            elif (directory / 'submission.json').is_file() or attempt.get('job_id'):
                attempt.update(allocation.collect(directory, job_id=attempt.get('job_id')))
            else:
                attempt['status'] = 'unknown'
            if attempt['status'] not in OBSERVED:
                raise ValueError('unrecognized allocation status')
        cell['status'] = cell['attempts'][-1]['status'] if cell['attempts'] else 'not-submitted'


def _recheck(grid, ledger, cell):
    now = datetime.now(timezone.utc)
    if now >= _deadline(grid.approval['expires_utc']):
        raise ValueError('delegated approval expired')
    if now >= _deadline(grid.budget['expires_utc']):
        raise ValueError('grid budget expired')
    _, digests = allocation._approval(Path(grid.approval['rundir']), grid.approval['route'], grid.approval['rung'])
    if digests != grid.approval['approval_files']:
        raise ValueError('delegated approval changed')
    count = sum(len(c['attempts']) for c in ledger['cells'].values())
    cost = sum(a['cpu_minutes'] for c in ledger['cells'].values() for a in c['attempts'])
    if count + 1 > grid.budget['max_submissions'] or cost + grid.allocation['cpus'] * grid.allocation['minutes'] > grid.budget['max_cpu_minutes']:
        raise ValueError('grid submission budget exhausted')
    entry = ledger['cells'][cell.id]
    if entry.get('override'):
        from .point_overrides import verify
        verify(entry['override'], entry['effective_study_spec'])
    if allocation._sha(cell.study_spec) != entry['study_spec_sha256']:
        raise ValueError('prepared study specification changed')


def submit(manifest, directory, *, resume=False, supersede=(), sbatch='sbatch'):
    """Submit one bounded wave. Resume submits untouched cells; supersede names terminal attempts."""
    directory = Path(directory).resolve()
    with file_lock(directory / '.lock'):
        grid, ledger = _load(manifest, directory, create=True)
        _refresh(ledger)
        context_sha256 = override_context(grid)
        atomic_json(directory / LEDGER, ledger)
        selected = set(supersede)
        if selected - set(ledger['cells']):
            raise ValueError('supersede names an unknown cell')
        if not resume and not selected and any(c['attempts'] for c in ledger['cells'].values()):
            raise ValueError('duplicate submission refused; use resume or explicitly supersede a cell')
        for cid in selected:
            attempts = ledger['cells'][cid]['attempts']
            if not attempts or attempts[-1]['status'] not in TERMINAL | {'missing'}:
                raise ValueError('only terminal or explicitly missing submissions can be superseded')
        for cell in grid.cells:
            entry = ledger['cells'][cell.id]
            if entry['attempts'] and cell.id not in selected:
                continue
            live = sum(a['status'] not in TERMINAL for c in ledger['cells'].values() for a in c['attempts']
                       if not a.get('superseded') and not (cell.id in selected and c is entry and a is entry['attempts'][-1]))
            if live >= grid.concurrency:
                break
            _recheck(grid, ledger, cell)
            spec = entry.get('effective_study_spec', cell.study_spec)
            agent = [spec if a in (cell.study_spec, '{study_spec}') else a for a in cell.agent]
            request_dir = allocation.prepare(cell.rundir, agent, **grid.allocation,
                                             rung=grid.approval['rung'], route=grid.approval['route'],
                                             **({'point_override': {'record': entry['override'], 'settings': spec}}
                                                if entry.get('override') else {}))
            # Recheck after preparation, immediately before durable reservation and dispatch.
            _recheck(grid, ledger, cell)
            if entry['attempts']:
                entry['attempts'][-1]['superseded'] = True
            attempt = {'request_dir': str(request_dir), 'request_id': read_json(request_dir / 'request.json')['request_id'],
                       'job_id': None, 'status': 'unknown',
                       'override': entry.get('override'), 'study_spec_sha256': allocation._sha(spec),
                       'receipt_sha256': entry['override']['receipt_sha256'] if entry.get('override') else
                           _digest({'cell_id': cell.id, 'context_sha256': context_sha256,
                                    'study_spec_sha256': allocation._sha(spec)}),
                       'cpu_minutes': grid.allocation['cpus'] * grid.allocation['minutes']}
            entry['attempts'].append(attempt)
            entry['status'] = 'unknown'
            atomic_json(directory / LEDGER, ledger)
            try:
                attempt.update(job_id=allocation.submit(request_dir, sbatch=sbatch), status='pending')
                entry['status'] = 'pending'
            except Exception as exc:
                attempt['error'] = str(exc)
                if isinstance(exc, allocation.NotSubmitted):
                    # Refused before any job existed: terminal and explicit, not an ambiguous reply.
                    attempt['status'] = entry['status'] = 'failed'
                atomic_json(directory / LEDGER, ledger)
                raise
            atomic_json(directory / LEDGER, ledger)
        return ledger


def status(manifest, directory):
    directory = Path(directory).resolve()
    with file_lock(directory / '.lock'):
        _, ledger = _load(manifest, directory)
        _refresh(ledger)
        atomic_json(directory / LEDGER, ledger)
        return ledger


def harvest(manifest, directory, output=None):
    directory = Path(directory).resolve()
    with file_lock(directory / '.lock'):
        grid, ledger = _load(manifest, directory)
        _refresh(ledger)
        atomic_json(directory / LEDGER, ledger)
        cells = []
        for cell in grid.cells:
            attempts = ledger['cells'][cell.id]['attempts']
            attempt = attempts[-1] if attempts else {}
            state, artifacts, values, detail = attempt.get('status', 'not-submitted'), {}, {}, None
            if state == 'completed':
                root = Path(attempt['result_root']).resolve()
                requested = list(grid.quantities) + [dict(name=p, source=p, field=None) for p in grid.artifacts]
                for q in requested:
                    try:
                        path = (root / q['source']).resolve()
                        if not path.is_relative_to(root):
                            raise ValueError('result artifact escapes study directory')
                        before = allocation._sha(path)
                        doc = read_json(path) if q['field'] is not None else None
                        if attempt.get('override'):
                            expected_receipt = attempt['override']['receipt_sha256']
                            direct = isinstance(doc, dict) and doc.get('point_receipt_sha256') == expected_receipt
                            if not direct:
                                witness = root / 'outputs/point-override-result.json'
                                sidecar = read_json(witness) if witness.is_file() else {}
                                if (not isinstance(sidecar, dict) or
                                        sidecar.get('point_receipt_sha256') != expected_receipt or
                                        not isinstance(sidecar.get('artifacts'), dict) or
                                        sidecar['artifacts'].get(q['source']) != before):
                                    raise ValueError('result lacks the effective point override receipt')
                                artifacts['point_override_result'] = Artifact(str(witness), allocation._sha(witness), None)
                        if q['field'] is None:
                            artifacts[q['name']] = Artifact(str(path), before, None)
                            continue
                        value = doc
                        for key in q['field'].split('.'):
                            value = value[key]
                        if type(value) not in (int, float) or not math.isfinite(value):
                            raise ValueError('harvested quantity must be a finite number')
                        if before != allocation._sha(path):
                            raise ValueError('result artifact changed during harvest')
                        artifacts[q['name']] = Artifact(str(path), before, q['field'])
                        values[q['name']] = value
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        state, detail = 'missing', str(exc)
                        values = {}
                        break
            record = attempt.get('override')
            if record:
                from .point_overrides import verify
                try:
                    request = read_json(Path(attempt['request_dir']) / 'request.json')
                    if (request.get('point_override', {}).get('record') != record or
                            attempt.get('receipt_sha256') != record['receipt_sha256']):
                        raise ValueError('override differs from the submitted point identity')
                    verify(record, request['point_override']['settings'], authority=False)
                except (OSError, ValueError) as exc:
                    state, values, detail = 'missing', {}, str(exc)
            # A proposed, unexecuted repair cannot relabel old successful data.
            if entry_record := ledger['cells'][cell.id].get('override'):
                if record != entry_record:
                    state, values, detail = 'missing', {}, 'override not yet executed'
                    record = entry_record
            cells.append(HarvestCell(cell.id, cell.axes, cell.scenario, state, attempt.get('job_id'),
                                     artifacts, values, detail, attempts, bool(record),
                                     record['reason'] if record else 'default', record,
                                     record['receipt_sha256'] if record else attempt.get('receipt_sha256')))
        result = GridHarvest(SCHEMA, 'study-grid-harvest', ledger['manifest_sha256'], grid.axes,
                             grid.scenarios, grid.quantities, tuple(cells))
        atomic_json(Path(output) if output else directory / 'harvest.json', asdict(result))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    verbs = parser.add_subparsers(dest='verb', required=True)
    for verb in ('submit', 'status', 'resume', 'harvest', 'override'):
        sub = verbs.add_parser(verb)
        sub.add_argument('--manifest', required=True, type=Path)
        sub.add_argument('--grid-dir', required=True, type=Path)
        if verb in ('submit', 'resume'):
            sub.add_argument('--supersede', action='append', default=[])
        if verb == 'override':
            sub.add_argument('--cell', required=True)
            sub.add_argument('--record', required=True, type=Path)
        if verb == 'harvest':
            sub.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verb in ('submit', 'resume'):
            result = submit(args.manifest, args.grid_dir, resume=args.verb == 'resume', supersede=args.supersede)
        elif args.verb == 'override':
            result = record_override(args.manifest, args.grid_dir, args.cell, read_json(args.record))
        elif args.verb == 'status':
            result = status(args.manifest, args.grid_dir)
        else:
            result = asdict(harvest(args.manifest, args.grid_dir, args.output))
        print(json.dumps(result, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f'ravel study-grid: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
