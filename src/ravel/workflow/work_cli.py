"""``ravel work``: the worker commands of ``agent_worker`` plus ``mcp``, the broker's MCP face.

``ravel work mcp --workspace W [--toolbelt T] [--socket S]`` serves the toolbelt over stdio
(``broker_mcp``). Every other subcommand (supervise, dispatch, status, call, reconcile,
stop) is passed unchanged to ``agent_worker.main``.
"""
from __future__ import annotations


def main(argv=None):
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ['mcp']:
        from .broker_mcp import main as mcp
        return mcp(arguments[1:])
    from .agent_worker import main as worker
    return worker(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
