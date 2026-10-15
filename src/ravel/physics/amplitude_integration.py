"""Science mode ``amplitude-integration``: weighted integration through an amplitude program into a Gram store.

The separate program (for example the MCFM amplitude overlay) is located through
the declared component path (``ravel.addons``) and runs only through the execution
backend: every warm-up, block and point evaluation is one backend stage with a
pinned plan. RAVEL writes each stage's control file and a copy of the declared
input card whose ``seed`` line in ``[integration]`` is set to the stage seed; every
other card line is copied unchanged.

Input document (``kind: amplitude-integration``)::

    {"schema_version": 1, "kind": "amplitude-integration", "addon": "mcfm-amplitudes",
     "operation": "blocks",                    # or "point-oracle"
     "store": "store",                         # persistent; a later run resumes it
     "backend": {"kind": "oci-local", "program": "/opt/mcfm/ravel_mcfm_amplitudes",
                 "workdir": "/work", "resources": {"cpus": 1, "memory_mib": 4096},
                 "image": {...}, "readonly_trees": [...], "env": {...}},
     "cohorts": [{"id": "mixed", "channel": 1, "card": {"path": "mixed.ini", "sha256": "..."},
                  "warmup": {"draws": 100000, "seed": 11, "max_seconds": 3600}}],
     "schedule": {"schema_version": 1, "max_operation_seconds": 36000,
                  "blocks": [{"id": "mixed-1", "cohort": "mixed", "seed": 21, "draws": 50000, "max_seconds": 3600}, ...]},
     "spin0": {"members": [...], "constants": {...},
               "closure": {"members": ["top-even", "bottom-even"], "program_members": ["scalar_bottom", "scalar_top"], "rtol": 1e-6}},
     "audit_points": 8, "oracle_rtol": 1e-10,
     "oracle": {"cohort": "mixed", "points": {"path": "points.json", "sha256": "..."}, "seed": 5, "max_seconds": 600}}

Every block's points are checked against the program's own squared amplitudes
before the block is stored. With ``spin0`` the declared spin-0 members join the
basis after a per-helicity closure fit reproduces the program's CP-even
amplitudes at the block's own points.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np

from ravel import addons
from . import amplitude_basis as ab
from . import amplitude_records as records_
from . import amplitude_store as store
from . import backend_driver

MODE = 'amplitude-integration'
SCOPE = 'amplitude_basis_weighted_integration'


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pinned(pin, root, label):
    ab.require(type(pin) is dict and set(pin) == {'path', 'sha256'}, f'{label} needs path and sha256')
    path = Path(pin['path'])
    path = (path if path.is_absolute() else Path(root) / path).absolute()
    ab.require(path.is_file() and not path.is_symlink(), f'{label} {path} must be a regular file')
    ab.require(_sha256(path) == pin['sha256'], f'{label} {path} differs from its declared sha256')
    return path


def card_with_seed(text, seed):
    """Copy of an INI card with the [integration] seed set; every other line unchanged."""
    lines, section, hits = text.splitlines(), None, []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1].strip().lower()
        elif section == 'integration' and re.match(r'^\s*seed\s*=', line):
            hits.append(i)
    ab.require(len(hits) == 1, 'the card needs exactly one seed line in its [integration] section')
    lines[hits[0]] = re.sub(r'=.*$', f'= {seed}', lines[hits[0]])
    return '\n'.join(lines) + '\n'


def validate(task):
    ab.require(type(task) is dict and set(task) == {'input'} and isinstance(task['input'], str) and task['input'],
               'task needs exactly input (the document path)')
    return task


def installation_defaults(backend, addon):
    """Use prefix-local installation fields only where the document omits them."""
    from ravel.paths import native_build_root
    if backend.get('kind') not in ('oci-local', 'native') or addon != 'mcfm-amplitudes':
        return backend, None
    native = backend['kind'] == 'native'
    if native and 'program' in backend or {'image', 'program', 'readonly_trees'} <= set(backend):
        return backend, None
    path = native_build_root() / 'installations' / 'mcfm-amplitudes.json'
    if not path.is_file():
        ab.require('program' in backend, 'installed amplitude program missing; run bash scripts/setup/install.sh --only mcfm-amplitudes --jobs 4 --accept-licenses')
        return backend, None
    record = json.loads(path.read_text())
    ab.require(record.get('schema_version') == 1 and record.get('kind') == 'ravel-amplitude-installation'
               and record.get('group') == addon, 'invalid amplitude installation record')
    launcher = record.get('launcher')  # an oci-local record names its launcher file
    built_native = type(launcher) is dict and launcher.get('kind') == 'native'
    ab.require(native == built_native, 'the installed amplitude program was built for the '
               + ('native' if built_native else 'oci-local') + ' backend')
    for key in (() if native else ('image',)) + ('program', 'readonly_trees', 'build_receipt', 'build_receipt_sha256', 'program_sha256'):
        ab.require(key in record, 'installation record missing ' + key)
    receipt, program = Path(record['build_receipt']), Path(record['program'])
    ab.require(receipt.is_file() and _sha256(receipt) == record['build_receipt_sha256'], 'installed build receipt changed')
    ab.require(program.is_file() and _sha256(program) == record['program_sha256'], 'installed amplitude program changed')
    ab.require(type(record['readonly_trees']) is list and all(type(p) is dict and isinstance(p.get('path'), str)
                                                          for p in record['readonly_trees']),
               'installation readonly_trees must be paths')
    filled = dict(backend)
    if native:
        # A host program reads its trees in place; only its path and runtime environment are filled.
        for key in ('program', 'env'):
            if key not in filled and key in record:
                filled[key] = record[key]
        return filled, {'path': str(path.absolute()), 'sha256': _sha256(path)}
    for key in ('image', 'program', 'readonly_trees', 'site', 'env'):
        if key not in filled and key in record:
            filled[key] = record[key]
    filled.setdefault('workdir', '/work')
    if 'readonly_trees' not in backend:
        filled['readonly_trees'] = [dict(p, mount=p.get('mount', p['path'])) for p in filled['readonly_trees']]
    return filled, {'path': str(path.absolute()), 'sha256': _sha256(path)}


def load(task, base):
    validate(task)
    path = Path(task['input'])
    path = (path if path.is_absolute() else Path(base) / path).absolute()
    doc = json.loads(path.read_text())
    root = path.parent
    required = {'schema_version', 'kind', 'addon', 'operation', 'store', 'backend', 'cohorts'}
    optional = {'schedule', 'spin0', 'audit_points', 'oracle_rtol', 'oracle', 'description', 'retain_pairings'}
    ab.require(type(doc) is dict and required <= set(doc) <= required | optional,
               'document needs ' + ', '.join(sorted(required)))
    ab.require(doc['schema_version'] == 1 and doc['kind'] == MODE, f'schema_version 1 and kind {MODE} required')
    ab.require(type(doc.get('retain_pairings', False)) is bool, 'retain_pairings must be Boolean')
    ab.require(doc['operation'] in ('blocks', 'point-oracle'), 'operation must be blocks or point-oracle')
    addon = addons.resolve(doc['addon'])
    protocol = records_.validate_protocol(addon.manifest.get('protocol'))
    ab.require(type(doc['backend']) is dict, 'backend must be an object')
    be, installation = installation_defaults(doc['backend'], doc['addon'])
    doc['backend'] = be
    ab.require(type(be) is dict and {'kind', 'program', 'resources'} <= set(be)
               <= {'kind', 'program', 'resources', 'image', 'readonly_trees', 'env', 'workdir', 'site'},
               'backend needs kind, program and resources (optional image, readonly_trees, env, workdir, site)')
    ab.require(type(be['resources']) is dict and 'wall_seconds' not in be['resources'],
               'stage wall time comes from each warm-up, block or oracle max_seconds')
    cohorts = {}
    for c in doc['cohorts']:
        ab.require(type(c) is dict and set(c) == {'id', 'channel', 'card', 'warmup'}, 'cohort needs id, channel, card and warmup')
        ab.require(str(c['channel']) in protocol['channels'], f'channel {c["channel"]} is not declared by the program')
        ab.require(c['id'] not in cohorts, 'cohort ids must be unique')
        card = _pinned(c['card'], root, f'cohort {c["id"]} card')
        card_with_seed(card.read_text(), 1)
        w = c['warmup']
        ab.require(type(w) is dict and set(w) == {'draws', 'seed', 'max_seconds'}, 'warmup needs draws, seed and max_seconds')
        cohorts[c['id']] = {**c, 'card_path': card}
    spin0 = doc.get('spin0')
    if spin0 is not None:
        from . import spin0_amplitudes as sp
        ab.require(type(spin0) is dict and set(spin0) == {'members', 'constants', 'closure'}, 'spin0 needs members, constants and closure')
        sp.validate_constants(spin0['constants'])
        for m in spin0['members']:
            sp.validate_member(m)
        cl = spin0['closure']
        ab.require(type(cl) is dict and set(cl) == {'members', 'program_members', 'rtol'}, 'closure needs members, program_members and rtol')
        ab.require(set(cl['program_members']) <= set(protocol['members']), 'closure program_members must be program members')
        ab.require(set(cl['members']) <= {m['id'] for m in spin0['members']}, 'closure members must be spin0 members')
    ctx = {'path': path, 'root': root, 'doc': doc, 'addon': addon, 'protocol': protocol, 'cohorts': cohorts,
           'store': (root / doc['store']).absolute(), 'spin0': spin0, 'installation': installation}
    if doc['operation'] == 'blocks':
        schedule = store.validate_schedule(doc['schedule'])
        for b in schedule['blocks']:
            ab.require(b['cohort'] in cohorts, f'block {b["id"]} names an undeclared cohort')
        seeds = [b['seed'] for b in schedule['blocks']] + [c['warmup']['seed'] for c in cohorts.values()]
        ab.require(len(set(seeds)) == len(seeds), 'warm-up and block seeds must all differ')
    else:
        o = doc.get('oracle')
        ab.require(type(o) is dict and set(o) == {'cohort', 'points', 'seed', 'max_seconds'} and o['cohort'] in cohorts,
                   'point-oracle needs oracle with cohort, points, seed and max_seconds')
        ctx['points'] = _pinned(o['points'], root, 'oracle points')
    return ctx


def inputs(task, base):
    ctx = load(task, base)
    files = [ctx['path'], *[c['card_path'] for c in ctx['cohorts'].values()], ctx['addon'].root / addons.MANIFEST,
             *ctx['addon'].members().values()]
    if 'points' in ctx:
        files.append(ctx['points'])
    if ctx['installation']:
        files.append(Path(ctx['installation']['path']))
        files += [Path(row['path']) for row in runtime_files(ctx)]
    return files


def runtime_files(ctx):
    """The program's own runtime files that the installation pins; each stage receives copies."""
    if not ctx['installation']:
        return []
    record = json.loads(Path(ctx['installation']['path']).read_text())
    rows = record.get('runtime_files', [])
    for row in rows:
        ab.require(type(row) is dict and set(row) == {'path', 'sha256'}, 'installation runtime_files need path and sha256')
        ab.require(Path(row['path']).is_file() and _sha256(row['path']) == row['sha256'],
                   f'installed runtime file {row["path"]} changed')
    return rows


def execution_seconds(task, base):
    ctx = load(task, base)
    doc = ctx['doc']
    if doc['operation'] == 'point-oracle':
        return int(doc['oracle']['max_seconds']) + 60
    warm = sum(c['warmup']['max_seconds'] for c in ctx['cohorts'].values())
    longest = max(b['max_seconds'] for b in doc['schedule']['blocks'])
    return int(warm + doc['schedule']['max_operation_seconds'] + longest + 60)


# ---------------------------------------------------------------- stages
def _stage_spec(ctx, name, stage_dir, files, outputs, seconds):
    be = ctx['doc']['backend']
    workdir = be.get('workdir')
    card = ctx['protocol'].get('card_file', 'input.ini')
    # The program reads its other inputs next to the card: mounted in the working directory, or in place.
    spec = {'schema_version': 1, 'backend': be['kind'], 'stage': name,
            'argv': [be['program'], card if workdir else str(stage_dir / card)],
            'inputs': [{'path': str(stage_dir / f), **({'mount': f'{workdir}/{f}'} if workdir else {})} for f in files],
            'outputs': [{'name': o, 'destination': str((stage_dir / o).relative_to(ctx['store']))} for o in outputs],
            'resources': {**be['resources'], 'wall_seconds': int(seconds)},
            'description': f'{ctx["doc"]["addon"]} {name}'}
    for key in ('image', 'readonly_trees', 'env', 'workdir', 'site'):
        if key in be:
            spec[key] = be[key]
    if ctx['installation']:
        pin = ctx['installation']
        ab.require(_sha256(Path(pin['path'])) == pin['sha256'], 'amplitude installation record changed after preparation')
        spec['inputs'].append(dict(pin, mount='/ravel/installation.json'))
    return spec


def _prepare_stage(ctx, name, cohort, operation, draws, seed, extra=None):
    stage_dir = ctx['store'] / 'stages' / name
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    p = ctx['protocol']
    (stage_dir / p.get('card_file', 'input.ini')).write_text(card_with_seed(cohort['card_path'].read_text(), seed))
    (stage_dir / p.get('control_file', 'ravel-control.dat')).write_text(f'{operation} {draws} {seed} {cohort["channel"]}\n')
    files = [p.get('card_file', 'input.ini'), p.get('control_file', 'ravel-control.dat')]
    for target, source in (extra or {}).items():
        (stage_dir / target).write_bytes(source)
        files.append(target)
    for row in runtime_files(ctx):
        name = Path(row['path']).name
        ab.require(name not in files, f'runtime file {name} collides with a stage file')
        shutil.copyfile(row['path'], stage_dir / name)
        files.append(name)
    return stage_dir, files


def _attempt(ctx, name):
    root = ctx['store'] / 'backend' / name
    root.mkdir(parents=True, exist_ok=True)
    return root / f'attempt-{len(list(root.iterdir())) + 1}'


def run_stage(ctx, name, cohort, operation, draws, seed, seconds, *, extra=None, outputs=None, backend=None):
    p = ctx['protocol']
    out_file = p.get('output_file', 'amplitudes.dat')
    stage_dir, files = _prepare_stage(ctx, name, cohort, operation, draws, seed, extra)
    spec = _stage_spec(ctx, name, stage_dir, files, outputs or [out_file], seconds)
    # The native path launches as a supervised backend stage of the store; an
    # injected backend (a test double) is driven in process.
    receipt = (backend_driver.drive_stage(spec, ctx['store']) if backend is None
               else backend_driver.drive(spec, _attempt(ctx, name), ctx['store'], backend=backend))
    raw = (stage_dir / out_file).read_bytes()
    parsed = records_.parse(raw, operation=operation, draws=draws, seed=seed, channel=int(cohort['channel']), protocol=p)
    return parsed, stage_dir, {'stage': name, 'plan_sha256': receipt['plan_sha256'],
                               'output_sha256': hashlib.sha256(raw).hexdigest()}


def warmups(ctx, backend=None):
    """One frozen proposal grid per cohort, reused on resume."""
    grids, receipts = {}, []
    grid_file = ctx['protocol'].get('grid_file', 'proposal-grid.bin')
    for cid, c in ctx['cohorts'].items():
        record = ctx['store'] / f'warmup-{cid}.json'
        if record.is_file():
            saved = json.loads(record.read_text())
            grid = (ctx['store'] / saved['grid']).read_bytes()
            ab.require(hashlib.sha256(grid).hexdigest() == saved['sha256'], f'warm-up grid of {cid} changed')
            ab.require(saved['card_sha256'] == c['card']['sha256'] and saved['seed'] == c['warmup']['seed'],
                       f'warm-up of {cid} was made with a different card or seed')
        else:
            w = c['warmup']
            parsed, stage_dir, receipt = run_stage(ctx, f'warmup-{cid}', c, ctx['protocol']['operations']['warmup'],
                                                   w['draws'], w['seed'], w['max_seconds'],
                                                   outputs=[ctx['protocol'].get('output_file', 'amplitudes.dat'), grid_file],
                                                   backend=backend)
            grid = (stage_dir / grid_file).read_bytes()
            saved = {'grid': str((stage_dir / grid_file).relative_to(ctx['store'])), 'sha256': hashlib.sha256(grid).hexdigest(),
                     'card_sha256': c['card']['sha256'], 'seed': w['seed'], 'summary': parsed['summary'], **receipt}
            record.write_text(json.dumps(saved, indent=2) + '\n')
        grids[cid] = grid
        receipts.append({'cohort': cid, **saved})
    return grids, receipts


def header(ctx, receipts):
    names = records_.member_names(ctx['protocol'])
    if ctx['spin0'] is not None:
        names += [m['id'] for m in ctx['spin0']['members']]
    first = next(iter(ctx['cohorts'].values()))
    return {'basis': names, 'observables': list(records_.OBSERVABLES),
            'particles': {'pdg': ctx['protocol']['channels'][str(first['channel'])]['pdg'], 'status': [-1, -1, 1, 1, 1, 1]},
            'factor_unit': ctx['protocol']['factor_unit'], 'audit_points': int(ctx['doc'].get('audit_points', 0)),
            'addon': {k: v for k, v in ctx['addon'].identity().items() if k != 'root'}, 'spin0': ctx['spin0'],
            'cohorts': {cid: {'channel': c['channel'], 'card_sha256': c['card']['sha256']} for cid, c in ctx['cohorts'].items()},
            'proposals': {r['cohort']: r['sha256'] for r in receipts},
            **({'pairing': {'exchange': records_.EXCHANGE.tolist()}} if ctx['doc'].get('retain_pairings') else {})}


def run(task, base, output, *, backend=None):
    ctx = load(task, base)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    ctx['store'].mkdir(parents=True, exist_ok=True)
    rtol = float(ctx['doc'].get('oracle_rtol', 1e-10))
    if ctx['doc']['operation'] == 'point-oracle':
        return _point_oracle(ctx, out, rtol, backend)
    grids, receipts = warmups(ctx, backend)
    p = ctx['protocol']
    closures, stages = [], []

    def produce(block, writer):
        cohort = ctx['cohorts'][block['cohort']]
        parsed, _, receipt = run_stage(ctx, block['id'], cohort, p['operations']['block'], block['draws'], block['seed'],
                                       block['max_seconds'], extra={p.get('grid_file', 'proposal-grid.bin'): grids[block['cohort']]},
                                       backend=backend)
        stages.append(receipt)
        if len(parsed['meta']):
            check = records_.oracle_check(parsed, p, rtol=rtol)
            ab.require(check['passed'], f'block {block["id"]} differs from the program\'s own squared amplitudes: {check["max_relative_residual"]}')
            values, _, closure = records_.to_block(parsed, p, spin0=ctx['spin0'])
            if closure is not None:
                closures.append({'block': block['id'], **closure})
            amplitudes = values.pop('amplitudes')
            if ctx['doc'].get('retain_pairings'):
                values['pairing'] = {'amplitudes': amplitudes, 'identical': parsed['identical'],
                                     'selected_direct': parsed['selected_direct'], 'normalization': parsed['meta'][:, 5]}
            writer.append(**values, amplitudes=amplitudes)
        s = parsed['summary']
        return {k: s[k] for k in ('attempted', 'accepted', 'rejected', 'failed')}

    def block_header(block):
        channel = ctx['cohorts'][block['cohort']]['channel']
        return {'particles': {'pdg': p['channels'][str(channel)]['pdg'], 'status': [-1, -1, 1, 1, 1, 1]}}

    manifest = store.run_schedule(ctx['store'], ctx['doc']['schedule'], produce, header=header(ctx, receipts),
                                  block_header=block_header)
    result = {'schema_version': 1, 'mode': MODE, 'status': 'passed', 'status_scope': SCOPE, 'physics_validated': False,
              'store': str(ctx['store']), 'store_status': manifest['status'], 'remaining': manifest['remaining'],
              'blocks': manifest['blocks'], 'warmups': receipts, 'stages': stages, 'closures': closures,
              'summary': [f'{len(manifest["blocks"])} of {len(ctx["doc"]["schedule"]["blocks"])} blocks complete; store {manifest["status"]}.'],
              'limitations': ['The oracle check confirms the stored amplitudes reproduce the program\'s own squares; '
                              'it does not establish their physical accuracy.']}
    (out / 'integration.json').write_text(json.dumps(result, indent=2, default=_plain) + '\n')
    return result


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def _point_oracle(ctx, out, rtol, backend):
    o = ctx['doc']['oracle']
    cohort = ctx['cohorts'][o['cohort']]
    points = json.loads(ctx['points'].read_text())
    ab.require(type(points) is dict and set(points) == {'convention', 'points'}
               and points['convention'] == 'all-outgoing (px, py, pz, E) in GeV', 'points need the all-outgoing convention')
    lines = []
    for row in points['points']:
        ab.require(type(row) is dict and set(row) == {'momenta', 'direct_pairing'} and len(row['momenta']) == 6,
                   'each point needs six momenta and direct_pairing')
        lines += [' '.join(format(float(v), '.17g') for v in p) for p in row['momenta']]
        lines.append('1' if row['direct_pairing'] else '0')
    pfile = ctx['protocol'].get('points_file', 'ravel-points.dat')
    parsed, _, receipt = run_stage(ctx, f'oracle-{o["cohort"]}', cohort, ctx['protocol']['operations']['points'],
                                   len(points['points']), o['seed'], o['max_seconds'],
                                   extra={pfile: ('\n'.join(lines) + '\n').encode()}, backend=backend)
    check = records_.oracle_check(parsed, ctx['protocol'], rtol=rtol)
    result = {'schema_version': 1, 'mode': MODE, 'status': 'passed' if check['passed'] else 'failed', 'status_scope': SCOPE,
              'physics_validated': False, 'oracle': check, 'stage': receipt, 'points': len(parsed['meta']),
              'summary': [f'point oracle {"passed" if check["passed"] else "failed"} at {len(parsed["meta"])} points.']}
    (out / 'point-oracle.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
