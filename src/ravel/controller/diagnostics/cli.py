"""Local-only ``ravel diagnostics report --run ID`` command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from .records import DiagnosticsRefused
from .report import markdown, report


def policy_refusal(argv):
    """The controller command policy for this command, as for every other entry point."""
    from ravel.controller import command_policy
    return command_policy.check(argv)


def open_store(run_id):
    from ravel.controller.authority import operator_config
    from ravel.controller.store import RunStore
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,63}', run_id):
        raise DiagnosticsRefused('invalid run id')
    root = Path(operator_config()['store_root']).expanduser()
    if not (root / run_id).is_dir():
        raise DiagnosticsRefused('run store does not exist')
    return RunStore(run_id, root=root)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel diagnostics', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('report', help='compare pinned expectations with the run records')
    command.add_argument('--run', required=True, help='controller run id')
    command.add_argument('--json', action='store_true', help='print JSON rather than the readable report')
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    store = None
    try:
        refusal = policy_refusal(['diagnostics', *arguments])
        if refusal:
            raise DiagnosticsRefused('refused: ' + refusal)
        store = open_store(args.run)
        value = report(store)
        print(json.dumps(value, indent=2, sort_keys=True) if args.json else markdown(value), end='\n')
        if not args.json:
            print('JSON: ' + value['artifacts']['json'])
            print('Report: ' + value['artifacts']['markdown'])
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print('ravel diagnostics: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        if store is not None and hasattr(store, 'close'):
            store.close()
