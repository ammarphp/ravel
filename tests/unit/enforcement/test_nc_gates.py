"""Gate rows against the installed decision gate: every required provider is required, wherever a registry is written.

The rows are the gates of the installed decision gate (``nc_cases.dimension_rows('GATE')``). For each gate the
adversary removes one required provider at a time, as a host without that module would, while the run tree
carries registries of its own that require nothing. The oracle is the installed registry's requirement list,
read from the package data and not through the gate's own accessor, and the refusal the gate must give for each
provider it names.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from nc_cases import INSTALLED, dimension_case, dimension_rows
from nc_mutations import Mutation, register

ACTION = {'digest': 'a' * 64, 'node_id': 'N1'}
# Registries a run author could leave in the run tree; the gate reads the installed one only.
RUN_TREE_REGISTRIES = ('gates/providers.json', '.ravel/providers.json', 'inputs/providers.json')


def _epoch_two_run(root):
    plan = {'agent_layer_epoch': 2, 'delegated': True, 'nodes': [], 'claims': [], 'edges': []}
    path = root / 'inputs' / 'plan.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan))
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (root / 'inputs' / 'task_contract.json').write_text(json.dumps(
        {'agent_layer_epoch': 2, 'delegated': True, 'request_plan': pin}))
    return root


@dimension_case('GATE', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('GATE'), ids=str)
def test_gate_requires_every_installed_provider(nc, row):
    from importlib import util
    from ravel.paths import package_data_path
    from ravel.workflow import decision_gate
    gate = row.split('-', 1)[1]
    # The requirement list is read from the installed data, not through the gate's accessor: a gate that stopped
    # requiring its providers would otherwise take the oracle with it.
    installed = json.loads(package_data_path('gates', 'providers.json').read_text())
    modules = {p['id']: p['module'] for p in installed['providers']}
    named = installed['required_providers']
    required = list(dict.fromkeys([*named.get('*', []), *named.get(gate, [])]))
    assert required and set(required) <= set(modules), f'gate {gate} names providers {required} the registry lacks'
    run = _epoch_two_run(nc.root / 'run')
    # Positive control: with every provider module available, no required provider is reported inactive.
    errors = decision_gate.check(run, gate, ACTION)
    assert [e for e in errors if e.code == 'provider_inactive' and e.provider in required] == []
    for provider in required:
        # The run tree carries registries that drop this provider and require nothing; they are not read.
        hostile = {'schema_version': 1, 'providers': [p for p in installed['providers'] if p['id'] != provider],
                   'required_providers': {}, 'required_scopes': []}
        for relative in RUN_TREE_REGISTRIES:
            nc.write_json(f'run/{relative}', hostile)
        with pytest.MonkeyPatch.context() as patch:
            real = util.find_spec
            patch.setattr(util, 'find_spec',
                          lambda name, *a, _real=real, _module=modules[provider]: None if name == _module
                          else _real(name, *a))
            errors = decision_gate.check(run, gate, ACTION)
        inactive = [(e.gate, e.provider, e.pins, e.message) for e in errors if e.code == 'provider_inactive']
        assert inactive == [(gate, provider, ('provider:' + provider,), 'provider module is not installed')], (
            gate, provider, [(e.code, e.provider) for e in errors])
        assert errors, 'a missing required provider must refuse, never pass as an empty check'


def _registry_without_requirements(original):
    def registry():
        document = original()
        document['required_providers'] = {}
        document['required_scopes'] = []
        return document
    return registry


register(Mutation('G02', 'ravel.workflow.decision_gate:_registry', _registry_without_requirements,
                  ('test_gate_requires_every_installed_provider[GATE-launch]',),
                  why='the gate requires no provider, so a missing provider module passes as an empty check'))
