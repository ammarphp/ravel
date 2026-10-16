# SPDX-License-Identifier: Apache-2.0
"""Numerical qualification of an installed MCFM amplitude program.

Runs the installed program in fresh directories exactly as an amplitude-integration
stage does (the card copy with the stage seed, the control file and the operation's
extra file) and applies the product's own checks to its output:

Each stage runs as the native backend runs it: the card's absolute path as the argument, an empty
working directory and RAVEL_OUTPUT_DIR for the outputs.

1. warm-up: a proposal grid, a complete draw census and the declared safety cuts applied at sampling;
2. weighted block on that grid: the declared safety cuts recomputed from every stored point and
   excluded draw, the block accepted as amplitude-integration accepts it (point oracle, Gram
   block and a store block whose census counts the excluded draws in the exposure), and the
   per-helicity spin-0 phase closure against the program's CP-even amplitudes when ``--spin0`` is given;
3. the same block again: identical records (fixed seed, one thread);
4. point evaluation of points taken from the block: the point oracle again, and the
   program's own squared amplitudes equal to the block's values at the same momenta;
5. point evaluation of the block's excluded draws: the program excludes every one of them again
   by the same cut, and its own squared amplitudes there equal the block's per unit coupling
   normalization where they are measured.

The excluded share of the draws, of the integration factor and of the program's own weight is
measured for the warm-up and the block and reported under ``safety``.

This is a consistency qualification of the installed program. It certifies neither
the physical accuracy of the amplitudes nor a study result.

Usage:
  python scripts/validation/qualify_mcfm_amplitudes.py --installation <prefix>/installations/mcfm-amplitudes.json \
      --card card.ini --work <new-dir> --output report.json [--spin0 spin0.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from ravel import addons  # noqa: E402
from ravel.physics import amplitude_integration as ai  # noqa: E402
from ravel.physics import amplitude_records as records_  # noqa: E402
from ravel.physics import amplitude_store as store  # noqa: E402

# META columns: the point's integration factor, and the program's full, signal-plus-interference and
# continuum squared amplitudes, each multiplied by that factor.
NORM, FULL, SUBTRACTION, CONTINUUM = 5, 6, 7, 8


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def installed_program(installation):
    record = json.loads(Path(installation).read_text())
    if record.get('kind') != 'ravel-amplitude-installation' or record.get('group') != 'mcfm-amplitudes':
        raise ValueError('not an MCFM amplitude installation record')
    program, receipt = Path(record['program']), Path(record['build_receipt'])
    if sha256(program) != record['program_sha256'] or sha256(receipt) != record['build_receipt_sha256']:
        raise ValueError('installed program or build receipt differs from the installation record')
    return record, program


def run_operation(program, env, protocol, card_text, directory, *, operation, draws, seed, channel, extra=None,
                  runtime=(), timeout=3600):
    """One stage as the native backend runs it: inputs in place, an empty working directory, outputs collected."""
    stage, cwd, output = directory / 'stage', directory / 'cwd', directory / 'output'
    for path in (stage, cwd, output):
        path.mkdir(parents=True)
    card = stage / protocol.get('card_file', 'input.ini')
    card.write_text(ai.card_with_seed(card_text, seed))
    (stage / protocol.get('control_file', 'ravel-control.dat')).write_text(f'{operation} {draws} {seed} {channel}\n')
    for name, data in (extra or {}).items():
        (stage / name).write_bytes(data)
    for row in runtime:
        if sha256(row['path']) != row['sha256']:
            raise ValueError(f'installed runtime file {row["path"]} changed')
        shutil.copyfile(row['path'], stage / Path(row['path']).name)
    start = time.monotonic()
    with (directory / 'program.log').open('wb') as log:
        proc = subprocess.run([str(program), str(card)], cwd=cwd, env={**env, 'RAVEL_OUTPUT_DIR': str(output)},
                              stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    seconds = time.monotonic() - start
    if proc.returncode != 0:
        raise RuntimeError(f'{directory.name}: program exited with status {proc.returncode}; see {directory / "program.log"}')
    raw = (output / protocol.get('output_file', 'amplitudes.dat')).read_bytes()
    parsed = records_.parse(raw, operation=operation, draws=draws, seed=seed, channel=channel, protocol=protocol)
    return parsed, raw, round(seconds, 1)


def accepted_block(parsed, protocol, spin0, directory, channel):
    """The block as amplitude-integration stores it: oracle, Gram block and a finished store block."""
    oracle = records_.oracle_check(parsed, protocol)
    if not oracle['passed']:
        return False, {'reason': 'point oracle', 'oracle': oracle['max_relative_residual']}, None
    values, _, closure = records_.to_block(parsed, protocol, spin0=spin0)
    names = records_.member_names(protocol) + ([m['id'] for m in spin0['members']] if spin0 else [])
    header = {'basis': names, 'observables': list(records_.OBSERVABLES), 'factor_unit': protocol['factor_unit'],
              'particles': {'pdg': protocol['channels'][str(channel)]['pdg'], 'status': [-1, -1, 1, 1, 1, 1]},
              'safety_cuts': protocol.get('safety_cuts', [])}
    values.pop('amplitudes')
    s = parsed['summary']
    with store.BlockWriter(Path(directory) / 'block.ravg', header) as writer:
        writer.append(**values)
        marker = writer.finish({k: s[k] for k in ('attempted', 'accepted', 'rejected', 'failed', 'excluded')})
    return True, {'points': marker['points'], 'summary': marker['summary']}, closure


def points_document(parsed, count):
    rows = [{'momenta': parsed['momenta'][i].tolist(), 'direct_pairing': bool(parsed['selected_direct'][i])}
            for i in range(min(count, len(parsed['meta'])))]
    return {'convention': 'all-outgoing (px, py, pz, E) in GeV', 'points': rows}


def points_file(document):
    lines = []
    for row in document['points']:
        lines += [' '.join(format(float(v), '.17g') for v in p) for p in row['momenta']]
        lines.append('1' if row['direct_pairing'] else '0')
    return ('\n'.join(lines) + '\n').encode()


def max_relative(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1e-300))) if a.size else 0.0


def qualify(args):
    record, program = installed_program(args.installation)
    addon_root = Path(args.addon) if args.addon else Path(args.installation).resolve().parents[1] / 'addons/mcfm-amplitudes'
    component = addons.load(addon_root)
    protocol = component.manifest['protocol']
    card = Path(args.card).read_text()
    spin0 = json.loads(Path(args.spin0).read_text()) if args.spin0 else None
    env = dict(os.environ)
    env.update(record.get('env', {}))
    env['OMP_NUM_THREADS'] = '1'
    work = Path(args.work).absolute()
    if work.exists() and any(work.iterdir()):
        raise ValueError(f'work directory {work} must be new or empty')
    checks, stages = [], {}
    channel = args.channel
    runtime = record.get('runtime_files', [])

    def check(name, passed, **detail):
        checks.append({'name': name, 'passed': bool(passed), **detail})

    warm, _, seconds = run_operation(program, env, protocol, card, work / 'warmup', operation=protocol['operations']['warmup'],
                                     draws=args.warmup_draws, seed=args.warmup_seed, channel=channel, runtime=runtime)
    grid_name = protocol.get('grid_file', 'proposal-grid.bin')
    grid = (work / 'warmup' / 'output' / grid_name).read_bytes()
    stages['warmup'] = {'seconds': seconds, 'summary': warm['summary'], 'grid_sha256': hashlib.sha256(grid).hexdigest()}
    check('warmup-census', warm['summary']['failed'] == 0 and warm['summary']['attempted'] == args.warmup_draws,
          summary=warm['summary'])
    safety = records_.check_safety(warm, protocol)
    check('warmup-safety-cut-applied-at-sampling', safety['passed'], cuts=safety['cuts'], undeclared_exclusions=safety['undeclared_exclusions'])
    measured = {'cuts': protocol.get('safety_cuts', []), 'warmup': records_.safety_census(warm, protocol)}

    block_args = dict(operation=protocol['operations']['block'], draws=args.block_draws, seed=args.block_seed,
                      channel=channel, extra={grid_name: grid}, runtime=runtime)
    block, block_raw, seconds = run_operation(program, env, protocol, card, work / 'block', **block_args)
    stages['block'] = {'seconds': seconds, 'summary': block['summary'], 'points': len(block['meta'])}
    check('block-census', block['summary']['failed'] == 0 and len(block['meta']) > 0, summary=block['summary'])
    safety = records_.check_safety(block, protocol)
    check('block-safety-cut-applied-at-sampling', safety['passed'], cuts=safety['cuts'], undeclared_exclusions=safety['undeclared_exclusions'])
    measured['block'] = records_.safety_census(block, protocol)
    kept = block
    oracle = records_.oracle_check(kept, protocol, rtol=args.rtol)
    check('block-point-oracle', oracle['passed'], points=len(kept['meta']), max_relative_residual=oracle['max_relative_residual'],
          rtol=args.rtol, excluded_draws=block['summary']['excluded'])
    try:
        accepted, detail, closure = accepted_block(block, protocol, spin0, work / 'store-check', channel)
    except ValueError as exc:
        accepted, detail, closure = False, {'reason': str(exc)}, None
    check('block-accepted-by-amplitude-integration', accepted, **detail,
          note='point oracle, safety cuts, Gram block and a store block whose census counts excluded draws')
    if spin0 is not None:
        check('spin0-phase-closure', bool(closure and closure.get('passed')), closure=closure)

    repeat, repeat_raw, seconds = run_operation(program, env, protocol, card, work / 'block-repeat', **block_args)
    stages['block-repeat'] = {'seconds': seconds}
    same = (len(repeat['meta']) == len(block['meta']) and np.array_equal(repeat['amplitudes'], block['amplitudes'])
            and np.array_equal(repeat['meta'], block['meta']) and np.array_equal(repeat['momenta'], block['momenta']))
    check('block-repeat-identical', same, note='every record except the CPU time on the COMPLETE line')

    document = points_document(kept, args.oracle_points)
    points, _, seconds = run_operation(program, env, protocol, card, work / 'points', operation=protocol['operations']['points'],
                                       draws=len(document['points']), seed=args.oracle_seed, channel=channel,
                                       extra={protocol.get('points_file', 'ravel-points.dat'): points_file(document)},
                                       runtime=runtime)
    stages['points'] = {'seconds': seconds, 'points': len(points['meta'])}
    oracle = records_.oracle_check(points, protocol, rtol=args.rtol)
    check('point-evaluation-oracle', oracle['passed'], points=len(points['meta']),
          max_relative_residual=oracle['max_relative_residual'], rtol=args.rtol)
    n = len(points['meta'])
    # Point evaluation carries unit weights, so compare the squares per unit integration factor. The
    # signal-plus-interference square is a subtraction of two sums and is reported, not compared.
    per_factor = lambda meta, cols: meta[:, cols] / meta[:, NORM:NORM + 1]
    compared = [FULL, CONTINUUM]
    agreement = (max_relative(per_factor(points['meta'], compared), per_factor(kept['meta'][:n], compared))
                 if n else float('inf'))
    subtraction = (max_relative(per_factor(points['meta'], [SUBTRACTION]), per_factor(kept['meta'][:n], [SUBTRACTION]))
                   if n else float('inf'))
    check('point-evaluation-reproduces-block-squares', n == len(document['points']) and agreement <= args.value_rtol,
          max_relative_difference=agreement, rtol=args.value_rtol, compared=['full', 'continuum'],
          signal_plus_interference_max_relative_difference=subtraction)

    ex = block['excluded']
    m = min(len(ex['draw']), args.oracle_points)
    if m:
        document = {'convention': 'all-outgoing (px, py, pz, E) in GeV',
                    'points': [{'momenta': ex['momenta'][i].tolist(), 'direct_pairing': True} for i in range(m)]}
        again, _, seconds = run_operation(program, env, protocol, card, work / 'excluded-points',
                                          operation=protocol['operations']['points'], draws=m, seed=args.oracle_seed + 1,
                                          channel=channel, runtime=runtime,
                                          extra={protocol.get('points_file', 'ravel-points.dat'): points_file(document)})
        stages['excluded-points'] = {'seconds': seconds, 'points': m}
        redo = again['excluded']
        same_cuts = again['summary']['excluded'] == m and np.array_equal(redo['cut'], ex['cut'][:m])
        weighed = ex['measured'][:m]
        # Per unit coupling normalization, as for stored points: a sampled draw carries the couplings at its
        # own scale, a supplied point the fixed ones.
        per_norm = lambda e, n: e['reference'][:n][weighed] / e['normalization'][:n][weighed]
        same = max_relative(per_norm(redo, m), per_norm(ex, m)) if same_cuts else float('inf')
        check('point-evaluation-applies-safety-cut', same_cuts and again['summary']['accepted'] == 0
              and same <= args.value_rtol, points=m, excluded=again['summary']['excluded'],
              measured_references=int(weighed.sum()), reference_max_relative_difference=same, rtol=args.value_rtol)

    report = {'schema_version': 1, 'kind': 'ravel-mcfm-amplitudes-qualification',
              'status': 'passed' if all(c['passed'] for c in checks) else 'failed',
              'scope': "consistency of the installed program with its own squared amplitudes, its spin-0 phase "
                       "convention and its reproducibility; not a physics accuracy certificate",
              'host': {'system': platform.system(), 'machine': platform.machine(), 'node': platform.node()},
              'installation': {'path': str(Path(args.installation).resolve()), 'sha256': sha256(args.installation),
                               'program_sha256': record['program_sha256'],
                               'build_receipt_sha256': record['build_receipt_sha256']},
              'addon': {k: v for k, v in component.identity().items() if k != 'root'},
              'card': {'path': str(Path(args.card).resolve()), 'sha256': sha256(args.card)},
              'spin0': spin0, 'channel': channel, 'stages': stages, 'safety': measured, 'checks': checks}
    Path(args.output).write_text(json.dumps(report, indent=2, default=lambda v: v.item() if hasattr(v, 'item') else str(v)) + '\n')
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--installation', required=True)
    ap.add_argument('--card', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--addon')
    ap.add_argument('--spin0')
    ap.add_argument('--channel', type=int, default=1)
    ap.add_argument('--warmup-draws', type=int, default=20000)
    ap.add_argument('--warmup-seed', type=int, default=11)
    ap.add_argument('--block-draws', type=int, default=5000)
    ap.add_argument('--block-seed', type=int, default=21)
    ap.add_argument('--oracle-points', type=int, default=64)
    ap.add_argument('--oracle-seed', type=int, default=5)
    ap.add_argument('--rtol', type=float, default=1e-10)
    ap.add_argument('--value-rtol', type=float, default=1e-11)
    args = ap.parse_args(argv)
    report = qualify(args)
    for row in report['checks']:
        print(('PASS ' if row['passed'] else 'FAIL ') + row['name'])
    print('RESULT ' + report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
