"""``ravel inference``: inspect inference documents and prepare ordinary studies.

Subcommands (none of them computes a result):

- ``modes``: list the inference science modes;
- ``example --mode M``: print a small synthetic input document for a mode;
- ``check --mode M --input doc.json``: validate a document and list every input
  file with its sha256 and the declared statistic;
- ``spec --mode M --input doc.json --policy review.json --source TEXT
  --assumption TEXT [--assumption TEXT ...] --max-seconds N --out spec.json``:
  write the schema 2 study specification for ``ravel plan``.

Computation runs through ``ravel plan``, ``ravel approve`` and ``ravel run``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ravel.paths import package_data_path

from . import MODES

SUMMARIES = {
    'formula-grid': 'evaluate declared closed-form formulas (widths, branching ratios, bands) on a parameter grid',
    'coupling-morphing': 'fit a declared polynomial in couplings to N runs; condition number, closure, covariance',
    'prescribed-statistic': 'evaluate the statistic a request prescribes (closed form or binned profile) as the primary result, CLs alongside',
    'search-statistics': 'SR/CR/VR pyhf models: discovery significance, CLs, background-only fit diagnostics',
    'differential-likelihood': 'Gaussian likelihood for a measured spectrum with full covariance and signed signals',
}


def _module(mode):
    from importlib import import_module
    if mode not in MODES:
        raise ValueError('mode must be one of ' + ', '.join(MODES))
    return import_module('ravel.physics.inference.' + mode.replace('-', '_'))


def example(mode):
    if mode not in MODES:
        raise ValueError('mode must be one of ' + ', '.join(MODES))
    return json.loads(package_data_path('inference', 'examples', mode + '.json').read_text())


def check(mode, document):
    module = _module(mode)
    task = {'input': str(Path(document).absolute())}
    module.validate(task)
    paths = module.inputs(task, Path.cwd())
    doc = json.loads(Path(document).read_text())
    statistic = doc.get('statistic')
    return {'mode': mode, 'status': 'checked', 'compute_authorized': False,
            'statistic': statistic if isinstance(statistic, dict) else None,
            'inputs': [{'path': str(p), 'sha256': hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in paths],
            'next': 'ravel inference spec ... then ravel plan --rundir <new-dir> --spec <spec.json>'}


def specification(mode, document, *, policy, source, assumptions, max_seconds, approval_mode):
    check(mode, document)
    review = json.loads(Path(policy).read_text())
    if not assumptions:
        raise ValueError('state at least one assumption')
    return {'schema_version': 2, 'mode': mode, 'source': source, 'assumptions': list(assumptions),
            'max_seconds': max_seconds, 'max_attempts': 1, 'approval_mode': approval_mode,
            'task': {'input': str(Path(document).absolute())}, 'review_policy': review}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel inference', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('modes', help='list the inference science modes')
    ex = sub.add_parser('example', help='print a synthetic example document')
    ex.add_argument('--mode', required=True, choices=MODES)
    ck = sub.add_parser('check', help='validate a document and list its inputs; no computation')
    ck.add_argument('--mode', required=True, choices=MODES)
    ck.add_argument('--input', required=True, type=Path)
    sp = sub.add_parser('spec', help='write a schema 2 study specification for ravel plan')
    sp.add_argument('--mode', required=True, choices=MODES)
    sp.add_argument('--input', required=True, type=Path)
    sp.add_argument('--policy', required=True, type=Path, help='review policy JSON (see science-review.md)')
    sp.add_argument('--source', required=True, help='scientific source of the inputs')
    sp.add_argument('--assumption', action='append', default=[], help='one numbered assumption; repeat')
    sp.add_argument('--max-seconds', type=int, default=600)
    sp.add_argument('--approval-mode', choices=('physicist', 'scripted_yes'), default='physicist')
    sp.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'modes':
        print(json.dumps([{'mode': m, 'summary': SUMMARIES[m]} for m in MODES], indent=2))
    elif args.command == 'example':
        print(json.dumps(example(args.mode), indent=2))
    elif args.command == 'check':
        print(json.dumps(check(args.mode, args.input), indent=2))
    else:
        value = specification(args.mode, args.input, policy=args.policy, source=args.source,
                              assumptions=args.assumption, max_seconds=args.max_seconds,
                              approval_mode=args.approval_mode)
        with args.out.open('x') as stream:
            stream.write(json.dumps(value, indent=2) + '\n')
        print(f'wrote {args.out}; next: ravel plan --rundir <new-dir> --spec {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
