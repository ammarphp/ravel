"""Worker executed only by the isolated easyscan interpreter.

The GPL Python binding belongs solely to this interpreter.  The execution
adapter that supplies likelihood callbacks is intentionally external to RAVEL;
this worker owns only request validation and evidence extraction.
"""
from __future__ import annotations

import json
import sys


def main(stream_in=sys.stdin, stream_out=sys.stdout):
    request = json.load(stream_in)
    if type(request) is not dict or request.get('schema_version') != 1 or set(request) != {'schema_version', 'settings'}:
        raise ValueError('worker request schema 1 required')
    # Deliberately local: the host process must never import this GPL binding.
    import pymultinest  # noqa: F401
    raise RuntimeError('a supplied likelihood callback and output path are required for native execution')


if __name__ == '__main__':
    raise SystemExit(main())
