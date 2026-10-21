"""Strict outcomes for the non-compliance suite and the ``nc`` case environment.

A case either passes or fails. A skip is accepted only with a declared reason:
``sandbox-blocked:`` (this host offers no OS confinement for the case) or
``pending-integration:`` (a CONTROLLER case while ``ravel.controller`` is not installed).
Once the controller package is installed, ``pending-integration:`` is a failure. Any other skip,
and every xfail, is turned into a failure. The ending audit reports blocked cases separately;
declared skips never count as completed coverage.
"""
from __future__ import annotations

from collections import Counter

import pytest

import nc_cases
from nc_audit import collection_errors
from nc_env import Env

_results = {}
_planned = set()
_peer_nodes = {}


def pytest_configure(config):
    _results.clear()
    _planned.clear()
    _peer_nodes.clear()
    config.addinivalue_line('markers', 'nc_case(rows=(), binding=..., dimension=None, fields=()): '
                                       'non-compliance case bound to coverage rows')
    config.addinivalue_line('markers', 'nc_peer_case: explicit peer fake before integration; '
                                     'mandatory real component adapter after installation')


def pytest_collection_modifyitems(config, items):
    selected = [item for item in items if str(item.path.parent) == str(nc_cases.ROOT / 'tests' / 'unit' / 'enforcement')]
    if not selected:
        return
    partial = bool(config.option.keyword or config.option.markexpr or any('::' in arg for arg in config.args))
    errors = collection_errors(selected, nc_cases.collection_bindings(), installed_rows=nc_cases.installed_population(),
                               complete_files=not partial)
    if errors:
        raise pytest.UsageError('non-compliance collection refused:\n' + '\n'.join(errors))
    _planned.update(item.nodeid for item in selected)
    for item in selected:
        if item.get_closest_marker('nc_peer_case'):
            _peer_nodes[item.nodeid] = 'real-component' if nc_cases.controller_installed() else 'peer-fake'


def _allowed_skip(reason):
    if reason.startswith(nc_cases.SANDBOX_BLOCKED):
        return True
    return reason.startswith(nc_cases.PENDING_INTEGRATION) and not nc_cases.controller_installed()


def _skip_reason(report):
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).removeprefix('Skipped: ')
    return str(longrepr)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if hasattr(report, 'wasxfail'):
        report.outcome = 'failed'
        report.longrepr = f'non-compliance cases never xfail ({report.wasxfail!r})'
        del report.wasxfail
        return
    if report.skipped:
        reason = _skip_reason(report)
        if not _allowed_skip(reason) or (item.get_closest_marker('nc_peer_case')
                                        and reason.startswith(nc_cases.PENDING_INTEGRATION)):
            report.outcome = 'failed'
            report.longrepr = f'unexpected skip in the non-compliance suite: {reason}'


def pytest_runtest_logreport(report):
    if report.nodeid not in _planned:
        return
    previous = _results.get(report.nodeid)
    if report.failed:
        _results[report.nodeid] = 'failed'
    elif report.skipped and previous != 'failed':
        _results[report.nodeid] = 'blocked'
    elif report.when == 'call' and report.passed and previous not in ('failed', 'blocked'):
        _results[report.nodeid] = 'passed'


def pytest_terminal_summary(terminalreporter):
    if not _planned:
        return
    counts = Counter(_results.values())
    completed = counts['passed'] + counts['failed']
    terminalreporter.write_line(f'NC AUDIT: collected={len(_planned)} completed={completed} '
                              f'passed={counts["passed"]} failed={counts["failed"]} '
                              f'blocked={counts["blocked"]} unfinished={len(_planned - _results.keys())}')
    if _peer_nodes:
        modes = Counter(_peer_nodes.values())
        terminalreporter.write_line(f'NC PEER CASES: peer-fake={modes["peer-fake"]} '
                                   f'real-component={modes["real-component"]}')


@pytest.fixture
def nc(tmp_path, monkeypatch):
    env = Env(tmp_path, monkeypatch)
    yield env
    env.close()
