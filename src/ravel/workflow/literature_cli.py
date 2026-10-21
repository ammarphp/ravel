"""Route literature commands while preserving the legacy command parser."""
from __future__ import annotations

import sys


_SERVING_COMMANDS = frozenset({
    'search', 'get-paper', 'list-papers', 'compare-measurements', 'replay', 'audit',
})


def main(argv=None, *, serving=None):
    """Forward arguments to their owner; only serving commands receive trust."""
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == 'locate':
        argv = ['get-paper', *argv[1:]]
    if argv and argv[0] == 'benchmark':
        from . import literature_benchmark

        return literature_benchmark.main(argv[1:])
    if argv and argv[0] == 'models':
        from . import literature_models

        return literature_models.main(argv[1:])
    if argv and argv[0] in _SERVING_COMMANDS:
        from . import literature_serving

        return literature_serving.main(argv, serving=serving)
    from . import literature

    return literature.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
