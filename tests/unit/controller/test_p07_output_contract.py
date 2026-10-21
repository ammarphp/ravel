"""Declared output contracts from controller intake to the sole sink. Fictional requests only.

Failure class: a request names where its deliverables go, which keys they hold and that a location
must hold nothing else, yet a controller run could be accepted while the declared file was missing,
linked, malformed or surrounded by undeclared files, or a later reading could adopt entries created
after the request was received. Intake binds the declarations to the directory the request came
from; the sink observes the real bytes immediately before acceptance. No model, job or network runs.
"""
from __future__ import annotations

import contextlib
import io
import json
import os

import pytest

import fakes
import p07_support as support
from p07_support import Run

from ravel.controller import entry, graph
from ravel.controller.sink.checks import OUTPUT_CONTRACT_LABEL
from ravel.workflow import output_contract as oc

PROMPT = ('Calculate the lifetime of a fictional state from the supplied width in GeV. Write the result as JSON to '
          '`deliverables/result.json` with exactly the keys `value` and `unit`; do not create any other files.')
VALID = b'{"value": 1.25, "unit": "s"}'


def _intake(tmp_path, monkeypatch):
    """The real entry and intake node under the controller's service stand-ins."""
    workspace = tmp_path / 'workspace'
    (workspace / 'deliverables').mkdir(parents=True)
    (workspace / 'deliverables' / 'supplied-note.txt').write_text('present when the request was received')
    monkeypatch.chdir(workspace)
    root = tmp_path / 'controller-store'
    with fakes.installed():
        store = entry.start(PROMPT.encode(), channel='terminal', rundir=tmp_path / 'runs' / 'r1', root=root)
        state = {'run': {'run_id': store.run_id, 'store_root': str(root), 'run_dir': str(store.run_dir)}}
        update = graph.intake(state)
    contract = json.loads(store.get_blob(update['request']['contract_sha256']))
    return workspace, store, state, update, contract


def _deliver(tmp_path, monkeypatch, contract):
    """The sink over a fictional governed run whose pinned contract carries the intake rows."""
    pinned = {**support.CONTRACT, 'task_requirements': {'obligations': oc.rows(contract)}}
    monkeypatch.setattr(support, 'CONTRACT', pinned)
    run = Run(tmp_path / 'sink', monkeypatch)
    run.complete()
    return run, run.deliver()


def _codes(receipt):
    return sorted({r['code'] for r in receipt['work']['current_refusals'] if r['code'].startswith('output_contract_')})


@pytest.fixture
def declared(tmp_path, monkeypatch):
    return _intake(tmp_path, monkeypatch)


def test_intake_binds_the_declarations_to_the_receiving_workspace(declared):
    workspace, store, _, update, contract = declared
    assert store.latest('request')['record']['workspace'] == os.path.realpath(workspace)
    rows = oc.rows(contract)
    assert [r['id'] for r in rows] == ['output-contract-F1', 'output-contract-L2']
    declared_file, location = (r['criteria'][oc.CRITERIA_KEY] for r in rows)
    assert declared_file['workspace'] == os.path.realpath(workspace)
    assert declared_file['keys'] == {'names': ['value', 'unit'], 'closed': True, 'container': 'keys'}
    assert location['baseline'] == {'names': ['supplied-note.txt']}
    retained = update['request']['output_contract']
    assert retained['rows'] == ['output-contract-F1', 'output-contract-L2']
    assert retained['workspaces'] == [os.path.realpath(workspace)]


def test_valid_bytes_are_accepted(declared, tmp_path, monkeypatch):
    workspace, _, _, _, contract = declared
    (workspace / 'deliverables' / 'result.json').write_bytes(VALID)
    _, receipt = _deliver(tmp_path, monkeypatch, contract)
    assert receipt['label'] == 'accepted' and receipt['accepted'] is True and _codes(receipt) == []
    assert OUTPUT_CONTRACT_LABEL not in receipt['labels']


def _symlink(workspace):
    real = workspace.parent / 'elsewhere.json'
    real.write_bytes(VALID)
    (workspace / 'deliverables' / 'result.json').symlink_to(real)


VIOLATIONS = {
    'missing': (lambda ws: None, ['output_contract_missing']),
    'symlink': (_symlink, ['output_contract_special_entry', 'output_contract_symbolic_link']),
    'extra sidecar': (lambda ws: ((ws / 'deliverables' / 'result.json').write_bytes(VALID),
                                  (ws / 'deliverables' / 'result.json.sidecar.json').write_text('{}')),
                      ['output_contract_extra_entry']),
    'changed baseline': (lambda ws: ((ws / 'deliverables' / 'result.json').write_bytes(VALID),
                                     (ws / 'deliverables' / 'later-note.txt').write_text('written after intake')),
                         ['output_contract_extra_entry']),
    'wrong format': (lambda ws: (ws / 'deliverables' / 'result.json').write_text('value = 1.25'),
                     ['output_contract_format']),
    'extra key': (lambda ws: (ws / 'deliverables' / 'result.json').write_text(
        '{"value": 1.25, "unit": "s", "note": "x"}'), ['output_contract_extra_keys']),
}


@pytest.mark.parametrize('case', VIOLATIONS)
def test_every_violation_is_named_and_withholds_acceptance(declared, tmp_path, monkeypatch, case):
    workspace, _, _, _, contract = declared
    damage, expected = VIOLATIONS[case]
    damage(workspace)
    run, receipt = _deliver(tmp_path, monkeypatch, contract)
    assert receipt['accepted'] is False and receipt['label'] != 'accepted'
    assert _codes(receipt) == expected
    assert OUTPUT_CONTRACT_LABEL in receipt['labels']
    # A qualified ending reports the same observation, labelled, and grants no acceptance.
    from ravel.controller import sink
    ending = sink.bounded_end(run.store, 'fictional bound reached')
    assert ending['accepted'] is False and OUTPUT_CONTRACT_LABEL in ending['labels']


def test_re_entered_and_resolved_intake_adopt_no_new_baseline_entries(declared):
    workspace, store, state, update, contract = declared
    (workspace / 'deliverables' / 'later-note.txt').write_text('written after intake')
    with fakes.installed():
        again = graph.intake(state)
    assert again['request'] == update['request']
    rows = oc.rows(contract)
    resolved = oc.census_rows(PROMPT, room=62, workspace=os.path.realpath(workspace), retained=rows)
    assert resolved == rows
    assert resolved[1]['criteria'][oc.CRITERIA_KEY]['baseline'] == {'names': ['supplied-note.txt']}
    fresh = oc.census_rows(PROMPT, room=62, workspace=os.path.realpath(workspace))
    assert fresh[1]['criteria'][oc.CRITERIA_KEY]['baseline'] == {'names': ['later-note.txt', 'supplied-note.txt']}


def test_a_run_directory_inside_the_nothing_else_location_is_refused_before_creation(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    (workspace / 'deliverables').mkdir(parents=True)
    monkeypatch.chdir(workspace)
    inside = workspace / 'deliverables' / 'run'
    with fakes.installed(), pytest.raises(entry.EntryError) as refused:
        entry.start(PROMPT.encode(), channel='terminal', rundir=inside, root=tmp_path / 'controller-store')
    assert refused.value.code == 'output_contract_placement' and not inside.exists()


OVERFULL = ('Calculate the lifetime of a fictional state from the supplied width in GeV. '
            + ' '.join(f'Write table {n} to `tables/part{n}.csv`.' for n in range(40)))


def test_an_overfull_declaration_keeps_the_routing_reminder_and_initiate_still_refuses(tmp_path, monkeypatch):
    from ravel import cli
    from ravel.workflow import host_guards, route_prompt
    with pytest.raises(ValueError):
        route_prompt.route(OVERFULL)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        host_guards.route({'prompt': OVERFULL}, str(tmp_path / 'project'), 'claude')
    payload = json.loads(out.getvalue())
    assert payload['hookSpecificOutput']['additionalContext'].startswith('ROUTING (G1)')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.subprocess, 'call', lambda *a, **k: pytest.fail('intake launched compute'))
    with contextlib.redirect_stderr(io.StringIO()):
        assert cli.main(['initiate', '--prompt', OVERFULL, '--out', str(tmp_path / 'runs' / 'over')]) != 0
    assert not (tmp_path / 'runs' / 'over' / 'inputs' / 'task_contract.json').exists()
