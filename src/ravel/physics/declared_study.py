"""Shared plumbing for single-request declarative science modes.

A task is ``{"request": <path>}``. The request JSON is the complete scientific
input; additional files it names are pinned by path and sha256. Outputs are
written once into a fresh directory. Planning goes through the ordinary
``science.plan`` lifecycle, so approval and execution stay with RAVEL.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ravel.physics import model_tool_bridge as custody


def sha256(path):
    return custody._hash(path)


def validate_task(task):
    custody._keys(task, ('request',), 'declared study task')
    if not isinstance(task['request'], str) or not task['request'].strip():
        raise ValueError('an explicit request path is required')
    return dict(task)


def load_request(task, base):
    validate_task(task)
    path = custody._regular(task['request'], base)
    from ravel.workflow.state_io import read_json
    return path, read_json(path)


def pinned(pin, base):
    """Resolve a {path, sha256} pin relative to the request directory."""
    return custody._pin(pin, base)


def inputs(path, extra=()):
    files = [Path(path).resolve(), Path(__file__).resolve(), *(Path(p).resolve() for p in extra)]
    return sorted(set(files))


def deliver(output, filename, result):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    target = out / filename
    with target.open('x') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write('\n')
    return result


def emit(result, out=None):
    text = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if out is None:
        print(text, end='')
    else:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x') as handle:
            handle.write(text)
        print(f'wrote {out}')
    return 0


def plan_arguments(parser):
    parser.add_argument('--request', required=True, help='request JSON')
    parser.add_argument('--rundir', required=True, help='new run directory')
    parser.add_argument('--review-policy', required=True, help='physics review policy JSON')
    parser.add_argument('--source', required=True, help='scientific source or synthetic-control description')
    parser.add_argument('--assumption', action='append', default=[], help='additional numbered assumption')
    parser.add_argument('--max-seconds', type=int, default=300)
    parser.add_argument('--approval-mode', choices=('physicist', 'scripted_yes'), default='physicist')
    return parser


def prepare(args, *, mode, assumptions):
    """Write science.json beside a fresh proposal directory and run science.plan (no compute)."""
    request = custody._regular(args.request, Path.cwd())
    root = Path(args.rundir).expanduser().absolute()
    proposal = root.with_name(root.name + '-proposal')
    if root.exists() or proposal.exists():
        raise ValueError('fresh run directory and proposal directory required')
    from ravel.workflow.state_io import read_json
    policy = read_json(custody._regular(args.review_policy, Path.cwd()))
    spec = {'schema_version': 2, 'mode': mode, 'source': args.source,
            'assumptions': [*assumptions, *args.assumption], 'max_seconds': args.max_seconds,
            'max_attempts': 1 + policy['policy']['max_redos'], 'approval_mode': args.approval_mode,
            'review_policy': policy, 'task': {'request': str(request)}}
    proposal.mkdir(parents=True)
    spec_path = proposal / 'science.json'
    custody._write(spec_path, spec)
    from ravel.workflow import science
    science.plan(root, spec_path)
    print(f'Prepared {mode} study at {root}; review CHECK-IN 1 and approve before running.')
    return 0


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
