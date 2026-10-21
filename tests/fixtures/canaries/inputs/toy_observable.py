"""Inert toy analysis for the canaries: N(g) = 100 g^2 with uncertainty 1 + g (fictional model).

Usage: toy_observable.py <output.json> <g> [<g> ...]. Writes one JSON table and nothing else.
Each execution carries a fresh execution id so the canary can count executions from outside.
Standard library only; no network, no environment reads.
"""
import json
import sys
import uuid


def main(argv):
    output, points = argv[0], [float(v) for v in argv[1:]]
    rows = [{'coupling': g, 'observable': round(100.0 * g * g, 6), 'uncertainty': round(1.0 + g, 6)} for g in points]
    with open(output, 'w') as stream:
        json.dump({'schema_version': 1, 'kind': 'toy-observable-table', 'model': 'fictional toy model',
                   'toy_observable_execution': uuid.uuid4().hex, 'rows': rows}, stream, indent=1, sort_keys=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
