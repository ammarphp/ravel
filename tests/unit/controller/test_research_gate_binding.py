"""A research loop scope in the run's protected store decides its gates through the controller's binding."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ravel.workflow import decision_gate

RUN = 'run-20261020-000000-0000abcd'


class Store:
    def __init__(self, root):
        self.root = root

    def path(self, *parts):
        return self.root.joinpath(*parts)


@pytest.fixture
def world(tmp_path, monkeypatch):
    import ravel.controller.store as store
    store_dir = tmp_path / 'store' / RUN
    scope = store_dir / 'research' / 'scope'
    scope.mkdir(parents=True)
    run_dir = tmp_path / 'runs' / 'run'
    (run_dir / 'campaign').mkdir(parents=True)
    monkeypatch.setattr(store, 'RunStore', lambda run_id: Store(tmp_path / 'store' / run_id))
    monkeypatch.setattr(store, 'controller_owned',
                        lambda path: RUN if Path(path).resolve().is_relative_to(run_dir.resolve()) else None)
    return scope, run_dir


def bind(scope, run, **change):
    value = {'schema_version': 1, 'kind': 'research-gate-binding', 'run_id': RUN, 'run_dir': str(run),
             'campaign': str(run / 'campaign'), **change}
    (scope / decision_gate.RESEARCH_GATE_BINDING).write_text(json.dumps(value))


def test_the_bound_scope_names_its_campaign_and_run(world):
    scope, run_dir = world
    assert decision_gate._research_scope(scope, RUN) is None, 'an unbound scope keeps the ordinary decision'
    bind(scope, run_dir)
    assert decision_gate._research_scope(scope, RUN) == (run_dir / 'campaign', run_dir)


@pytest.mark.parametrize('change', [{'run_id': 'run-20261020-000000-0000ffff'}, {'kind': 'other'},
                                    {'campaign': '/elsewhere/campaign'}, {'run_dir': '/elsewhere'}])
def test_a_binding_of_another_run_or_campaign_is_refused(world, change):
    scope, run_dir = world
    bind(scope, run_dir, **change)
    with pytest.raises(ValueError):
        decision_gate._research_scope(scope, RUN)


def test_a_binding_outside_the_run_s_store_or_through_a_link_is_refused(world, tmp_path):
    scope, run_dir = world
    outside = tmp_path / 'outside'
    outside.mkdir()
    bind(outside, run_dir)
    with pytest.raises(ValueError, match='protected store'):
        decision_gate._research_scope(outside, RUN)
    (scope / decision_gate.RESEARCH_GATE_BINDING).symlink_to(outside / decision_gate.RESEARCH_GATE_BINDING)
    with pytest.raises(ValueError, match='protected store'):
        decision_gate._research_scope(scope, RUN)


def test_a_bound_scope_decides_with_the_campaign_protocol_and_the_run_s_other_providers(world, monkeypatch):
    scope, run_dir = world
    bind(scope, run_dir)
    from ravel.workflow import research_protocol
    seen = []
    error = lambda provider: decision_gate.GateError('code', 'research_choice', provider, 'm', 'f', ())  # noqa: E731
    monkeypatch.setattr(research_protocol, 'gate_errors',
                        lambda root, gate, action: seen.append(('protocol', Path(root))) or [error('research_protocol')])
    original = decision_gate._controller_check

    def run_check(rundir, gate, action, run_id):
        if Path(rundir) == run_dir:
            seen.append(('run', Path(rundir)))
            return [error('research_protocol'), error('ledger')]
        return original(rundir, gate, action, run_id)
    monkeypatch.setattr(decision_gate, '_controller_check', run_check)
    errors = original(scope, 'research_choice', {}, RUN)
    assert seen == [('protocol', run_dir / 'campaign'), ('run', run_dir)]
    assert [e.provider for e in errors] == ['research_protocol', 'ledger']
    seen.clear()
    assert [e.provider for e in original(scope, 'other_gate', {}, RUN)] == ['ledger']
    assert seen == [('run', run_dir)]
