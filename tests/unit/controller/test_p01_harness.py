"""The harness arm: a closed operator configuration, a retained session record and sink-only results.

Failure class: a harness-driven run whose executable, model or effort differs from the pinned
session, or whose session record is missing or stale, still started; or a harness results file
filled from a terminal message or a qualified receipt. Fictional, inert executable and requests
only: nothing is executed, no model is called.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

import p07_support as support  # noqa: F401  (the sink fixture's stand-ins)
from p07_support import VALUE, Run

from ravel.controller import entry, store as store_module
from ravel.controller.sink import common

REQUEST = b'Estimate the yield of a fictional widget process in a toy model and report the value with its uncertainty.'


def _session(tmp_path, *, model='fictional-model', effort='low', **changes):
    executable = tmp_path / 'harness' / 'inert-harness'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('#!/bin/sh\nexit 0\n')
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    record = {'schema_version': 1, 'kind': 'harness-session', 'session_id': 'fictional-session-1',
              'executable': str(executable), 'executable_sha256': digest, 'model': model, 'effort': effort}
    record.update(changes)
    session = tmp_path / 'harness' / 'session.json'
    session.write_text(json.dumps(record))
    results = tmp_path / 'trusted' / 'results.json'
    results.parent.mkdir(parents=True, exist_ok=True)
    return {'executable': str(executable), 'executable_sha256': digest, 'model': 'fictional-model', 'effort': 'low',
            'session_record': str(session), 'results_file': str(results)}


def _cli(tmp_path, monkeypatch, harness):
    """``ravel drive --unattended`` with the operator's harness configuration; the graph is stood in."""
    config = {'harness': harness, 'store_root': str(tmp_path / 'controller-store')}
    monkeypatch.setattr(entry, '_operator_config', lambda: deepcopy(config))
    monkeypatch.setattr(store_module, '_operator_config', lambda: deepcopy(config))
    confine = support.FakeConfine()
    monkeypatch.setattr(entry, '_identity_check', lambda: confine.require_governed_install)
    started = []
    monkeypatch.setattr(entry, 'drive', lambda store, **kw: started.append(store) or
                        {'thread_id': None, 'next': None, 'terminal': None, 'interrupts': []})
    request = tmp_path / 'request.txt'
    request.write_bytes(REQUEST)
    monkeypatch.chdir(tmp_path)
    code = entry.drive_main(['--unattended', '--request-file', str(request), '--rundir', str(tmp_path / 'runs' / 'h1')])
    return code, started


def test_a_bound_session_starts_the_harness_channel_with_its_results_target(tmp_path, monkeypatch, capsys):
    harness = _session(tmp_path)
    code, started = _cli(tmp_path, monkeypatch, harness)
    assert code == 0 and len(started) == 1
    store = started[0]
    assert store.latest('request')['record']['channel'] == 'harness'
    bound = store.latest('harness-session')['record']
    assert {k: bound[k] for k in ('executable', 'executable_sha256', 'model', 'effort')} == {
        k: harness[k] for k in ('executable', 'executable_sha256', 'model', 'effort')}
    assert bound['session_id'] == 'fictional-session-1' and entry.verify_harness_binding(bound) is None
    assert store.latest(common.DELIVERY_TARGET)['record'] == {'path': harness['results_file']}


CASES = {
    'open key': (lambda tmp, h: h.update(channel='trusted'), 'harness_config'),
    'relative executable': (lambda tmp, h: h.update(executable='inert-harness'), 'harness_config'),
    'missing session': (lambda tmp, h: Path(h['session_record']).unlink(), 'harness_session_missing'),
    'stale session': (lambda tmp, h: Path(h['session_record']).write_text('{"kind": "harness-session"}'),
                      'harness_session_stale'),
    'wrong executable': (lambda tmp, h: Path(h['executable']).write_text('#!/bin/sh\nexit 1\n'),
                         'harness_executable'),
    'wrong model': (lambda tmp, h: h.update(model='another-model'), 'harness_model'),
    'wrong effort': (lambda tmp, h: h.update(effort='high'), 'harness_effort'),
}


@pytest.mark.parametrize('case', CASES)
def test_a_missing_stale_or_mismatched_session_refuses_before_any_run(tmp_path, monkeypatch, capsys, case):
    harness = _session(tmp_path)
    mutate, code_name = CASES[case]
    mutate(tmp_path, harness)
    with pytest.raises(entry.EntryError) as refused:
        entry.harness_binding(harness)
    assert refused.value.code == code_name
    code, started = _cli(tmp_path, monkeypatch, harness)
    assert code == 2 and started == [] and not (tmp_path / 'runs' / 'h1').exists()
    with pytest.raises(entry.EntryError):
        entry.start(REQUEST, channel='harness', rundir=tmp_path / 'runs' / 'h2', root=tmp_path / 'other-store')


def _sink(tmp_path, monkeypatch, *, damage=None, review=None):
    harness = _session(tmp_path)
    binding = entry.harness_binding(harness)
    run = Run(tmp_path / 'sink', monkeypatch)
    request = run.store.latest('request')['record']
    run.store.append('request', {**request, 'channel': 'harness'})
    run.store.append('harness-session', binding)
    run.store.append(common.DELIVERY_TARGET, {'path': harness['results_file'], 'deliverable': 'd-value'})
    run.complete()
    if review:
        run.review_round('final', review)
    if damage:
        damage(harness)
    return run, Path(harness['results_file'])


def test_a_valid_bounded_accepted_run_writes_only_its_authorized_results(tmp_path, monkeypatch):
    run, results = _sink(tmp_path, monkeypatch)
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['delivery']['results_file']['status'] == 'written'
    assert json.loads(results.read_text()) == VALUE
    assert sorted(p.name for p in results.parent.iterdir()) == ['results.json']


SINK_CASES = {
    'qualified receipt': ({'review': {'physics-critic': (True, 'accept'), 'skeptical-verifier': (False, 'accept'),
                                      'physics-decider': (True, 'accept')}}, 'untouched'),
    'changed session': ({'damage': lambda h: Path(h['session_record']).write_text('{}')}, 'refused'),
    'changed executable': ({'damage': lambda h: Path(h['executable']).write_text('#!/bin/sh\nexit 2\n')}, 'refused'),
}


@pytest.mark.parametrize('case', SINK_CASES)
def test_results_stay_empty_without_an_accepted_current_receipt_and_session(tmp_path, monkeypatch, case):
    options, status = SINK_CASES[case]
    run, results = _sink(tmp_path, monkeypatch, **options)
    receipt = run.deliver()
    assert receipt['delivery']['results_file']['status'] == status
    assert not results.exists()


def test_a_terminal_message_never_fills_the_results(tmp_path, monkeypatch):
    run, results = _sink(tmp_path, monkeypatch)
    run.store.append('terminal', {'message': json.dumps(VALUE), 'status': 'completed'})
    from ravel.controller import sink
    ending = sink.bounded_end(run.store, 'fictional bound reached')
    assert ending['accepted'] is False and not results.exists()


def test_the_mcp_listing_equals_the_admitted_toolbelt(tmp_path):
    from ravel.workflow import broker_mcp, role_registry, toolbelt
    belt = toolbelt.build(role_registry.load('literature-scout'), max_tools=64)
    executing = [t for t in belt['tools'] if t['executes_through']['action'] is not None]
    listing = broker_mcp.Server(belt['tools'], lambda request: {}).listing()
    assert [row['name'] for row in listing] == [t['name'] for t in executing]
    assert [row['inputSchema'] for row in listing] == [t['args_schema'] for t in executing]
    assert toolbelt.allowed_actions(belt['tools']) == sorted({t['executes_through']['action'] for t in executing})
