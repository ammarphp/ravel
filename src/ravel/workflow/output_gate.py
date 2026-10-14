"""The toolchain execution gate: a stage is accepted only when its outputs meet their contracts.

An exit code of zero is not success. ``evaluate`` accepts a stage when the process exited
0, every declared output contract passes (``ravel.validation.output_postconditions``) and
the log carries no hard-error marker for the stage's toolchain. Marker lists are data
(``src/ravel/data/output_markers.json``). Otherwise the stage is refused with one failure
class:

* ``environment_blocked``: an environment marker (a missing library, a missing module);
* ``tool_failed``: a nonzero exit;
* ``hard_error_marker``: exit 0 but a hard-error marker in the log;
* ``contract_failed``: exit 0 but an output contract failed (empty tree, all-zero
  weights, stale output, near copy of a reference, missing branch).

``record`` writes the verdict as ``<gate_dir>/<stage>.json``; ``require_accepted`` is called
by the next stage before it reads anything, and refuses unless every named upstream
stage has an accepted verdict whose output digests still match the files on disk.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from ravel.paths import package_data_path
from ravel.validation import output_postconditions as postconditions

FAILURE_CLASSES = ('environment_blocked', 'tool_failed', 'hard_error_marker', 'contract_failed')


def markers(toolchain=None):
    document = json.loads(package_data_path('output_markers.json').read_text())
    if toolchain is None:
        return document['toolchains']
    if toolchain not in document['toolchains']:
        raise ValueError(f'no output markers for toolchain {toolchain!r}')
    return document['toolchains'][toolchain]


def scan_log(text, toolchains):
    """The first line matching each marker pattern, grouped by marker kind."""
    found = {'hard_errors': [], 'warnings': [], 'environment': []}
    lines = (text or '').splitlines()
    for name in toolchains:
        table = markers(name)
        for key in found:
            for pattern in table.get(key, []):
                regex = re.compile(pattern)
                line = next((l for l in lines if regex.search(l)), None)
                if line is not None:
                    found[key].append({'toolchain': name, 'pattern': pattern, 'line': line.strip()[:300]})
    return found


def evaluate(stage, *, returncode, log_text='', contracts=(), toolchains=(), base=None, snapshot_before=None):
    """The verdict for one finished stage. Contracts are checked even after a failure, for diagnosis."""
    found = scan_log(log_text, toolchains)
    checked = postconditions.check_all(list(contracts), base, snapshot_before=snapshot_before)
    failure = None
    if found['environment']:
        failure = 'environment_blocked'
    elif returncode != 0:
        failure = 'tool_failed'
    elif found['hard_errors']:
        failure = 'hard_error_marker'
    elif not checked['passed']:
        failure = 'contract_failed'
    return {'schema_version': 1, 'kind': 'ravel-output-gate', 'stage': stage, 'returncode': returncode,
            'verdict': 'accepted' if failure is None else 'refused', 'failure_class': failure,
            'markers': found, 'contracts': checked['contracts'],
            'outputs': {r['path']: r['observed'].get('sha256') for r in checked['contracts']}}


def record(gate_dir, verdict):
    gate_dir = Path(gate_dir)
    gate_dir.mkdir(parents=True, exist_ok=True)
    path = gate_dir / f'{verdict["stage"]}.json'
    if path.exists():
        raise ValueError(f'gate verdict for {verdict["stage"]} already recorded')
    path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + '\n')
    return path


def require_accepted(gate_dir, stages):
    """Refuse unless each upstream stage was accepted and its outputs are unchanged."""
    verdicts = []
    for stage in stages:
        path = Path(gate_dir) / f'{stage}.json'
        if not path.is_file():
            raise ValueError(f'upstream stage {stage} has no gate verdict; it must pass its output contracts first')
        verdict = json.loads(path.read_text())
        if verdict.get('verdict') != 'accepted':
            raise ValueError(f'upstream stage {stage} was refused ({verdict.get("failure_class")}); downstream stages do not run')
        for output, digest in verdict.get('outputs', {}).items():
            if digest is None or not Path(output).is_file() or postconditions._identity(output)['sha256'] != digest:
                raise ValueError(f'output {output} of stage {stage} changed after its gate verdict')
        verdicts.append(verdict)
    return verdicts


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel output-gate', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check', help='evaluate output contracts and a log for one finished stage')
    check.add_argument('--stage', required=True)
    check.add_argument('--contracts', required=True, help='JSON list of output contracts')
    check.add_argument('--returncode', type=int, required=True)
    check.add_argument('--log')
    check.add_argument('--toolchain', action='append', default=[])
    check.add_argument('--base')
    sub.add_parser('markers', help='print the marker lists')
    args = parser.parse_args(argv)
    try:
        if args.command == 'markers':
            print(json.dumps(markers(), indent=2))
            return 0
        contracts = json.loads(Path(args.contracts).read_text())
        text = Path(args.log).read_text(errors='replace') if args.log else ''
        verdict = evaluate(args.stage, returncode=args.returncode, log_text=text, contracts=contracts,
                           toolchains=args.toolchain, base=args.base)
        print(json.dumps(verdict, indent=2))
        return 0 if verdict['verdict'] == 'accepted' else 1
    except (OSError, ValueError) as exc:
        print(f'output-gate: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
