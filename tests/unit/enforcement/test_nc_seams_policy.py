"""In-process seams and frozen policy: nothing outside the installed controller changes a run's decisions.

The adversary installs a gate override in the controller process (a plugin setting the gate
context variables), enables the test seams from ordinary code, or rewrites the project's provider
policy after intake. Oracles are the gate check's refusal, the seam guard and the frozen mode
record; positive controls use the seams where the harness allows them and start a later run.
"""
from __future__ import annotations

import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _always_pass(scope_root, gate_name, action):
    return []


@case('SW30', binding=CONTROLLER)
def test_SW30_a_gate_override_or_a_self_enabled_seam_is_refused_in_a_controller_run(nc):
    testing = require_controller('testing')
    from ravel.workflow import graph_nodes
    store, run_dir = controller_run(nc)
    with testing.seams(False, controller=True):
        with graph_nodes.gate_checker(_always_pass, providers=lambda gate: []):
            errors = graph_nodes.check_gate(run_dir, 'approve_plan', {'digest': 'a' * 64})
        assert any(e.get('code') == 'seam_refused' for e in errors), errors
        with pytest.raises(testing.SeamRefused):
            testing.enable_seams()  # only the harness's conftest may enable the seams
        with pytest.raises(testing.SeamRefused):
            testing.refuse('a plugin-installed controller service')
    # Positive control: the harness's seam still works on a run the controller does not own.
    legacy = nc.root / 'legacy-scope'
    legacy.mkdir()
    with testing.seams(True, controller=False):
        with graph_nodes.gate_checker(_always_pass, providers=lambda gate: []):
            assert graph_nodes.check_gate(legacy, 'approve_plan', {'digest': 'a' * 64}) == []


register(Mutation('SW30', 'ravel.controller.testing:refuse_for_controller', lambda original: lambda *a, **k: None,
                  ('SW30',), binding=MUTATION_CONTROLLER, why='a controller run takes gate decisions from an override'))


@case('SW25', binding=CONTROLLER)
def test_SW25_a_provider_policy_rewritten_after_intake_does_not_change_the_run(nc):
    authority = require_controller('authority')
    project_config = nc.root / '.ravel' / 'data_classification.json'
    project_config.parent.mkdir(parents=True)
    restricted = {'level': 'restricted',
                  'allowed_providers': [{'transport_id': 'claude-cli-worker', 'account_class': 'subscription'}]}
    project_config.write_text(json.dumps(restricted))
    store, _ = controller_run(nc)
    frozen = authority.frozen(store)['provider_policy']
    project_config.write_text(json.dumps({'level': 'public', 'allowed_providers': []}))
    assert authority.frozen(store)['provider_policy'] == frozen, 'the policy frozen at intake stays the run policy'
    later, _ = controller_run(nc, 'nc-run-after-policy-change')
    assert authority.frozen(later)['provider_policy']['policy_sha256'] != frozen['policy_sha256']  # positive


def _live_provider_policy(original):
    def frozen(store, *, required=True):
        record = original(store, required=required)
        if record is None:
            return None
        from ravel.controller.authority import mode
        return dict(record, provider_policy=mode._provider_policy(None, store.run_record()['run_dir'].rsplit('/runs/', 1)[0]))
    return frozen


register(Mutation('SW25', ('ravel.controller.authority.mode:frozen', 'ravel.controller.authority:frozen'),
                  _live_provider_policy, ('SW25',), binding=MUTATION_CONTROLLER,
                  why='the run reads the project provider policy as it is now'))
