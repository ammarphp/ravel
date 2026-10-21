"""Comparison rows: agreement, residual diagnosis and attribution rest on declared bases and receipted evidence.

The adversary swaps the expected for the observed reference or adds an undeclared second comparator,
feeds a decomposition with replicas no launch produced, and promotes a feature to a cause without a
measured contribution. Oracles are the judgment record's protocol checks (P2, P5), the consequence
class and reviewer items the controller derives, and the step's custody check; positive controls pass
the same checks with matching manifests, receipted replicas and a quantified cause.
"""
from __future__ import annotations

from copy import deepcopy

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _p2(column_left='observed', column_right='observed', *, extra=None):
    from test_nc_judgment_protocols import P2_MANIFEST
    manifests = [dict(P2_MANIFEST, side='ours', column=column_left), dict(P2_MANIFEST, side='reference', column=column_right)]
    if extra is not None:
        manifests.append(dict(P2_MANIFEST, side=extra))
    return {'manifests': manifests, 'transformation': {'applied_to': None, 'description': 'none', 'result': None},
            'identity_check': {'kind': 'closure', 'expected': 1.0, 'measured': 1.0, 'tolerance': 0.01}}


@case('C28', binding=CONTROLLER)
def test_C28_an_agreement_claim_on_swapped_or_undeclared_comparators_is_refused(nc):
    judgment = require_controller('judgment')
    from test_nc_judgment_protocols import _record
    swapped = judgment.check_record(_record(triggers=['compare'], evidence={'P2': _p2('observed', 'expected')}))
    assert any('manifests still differ' in e and 'column' in e for e in swapped), swapped
    second = judgment.check_record(_record(triggers=['compare'], evidence={'P2': _p2(extra='second reference')}))
    assert second, 'an undeclared second comparator is admitted into one agreement claim'
    assert judgment.check_record(_record(triggers=['compare'], evidence={'P2': _p2()})) == []  # positive control


register(Mutation('M11', 'ravel.controller.judgment.protocols:SEMANTIC',
                  lambda original: {**original, 'P2': lambda value: []}, ('C28',),
                  binding=MUTATION_CONTROLLER, why='the basis manifests of a comparison are never compared'))


@case('C29', binding=CONTROLLER)
def test_C29_a_residual_decomposition_from_unregistered_replicas_or_models_is_refused(nc):
    custody = require_controller('step.custody')
    from test_nc_step import _adopted
    from test_nc_step_flow import _step
    store, run_dir = controller_run(nc)
    # Replica outputs with fabricated seed labels, written into the run tree by hand, and an unregistered model.
    (run_dir / 'steps' / 's11' / 'outputs').mkdir(parents=True)
    (run_dir / 'steps' / 's11' / 'outputs' / 'replica-seed-7.json').write_text('{"value": 1.1}')
    decomposition = _step('s20', 'compare', depends_on=['s11'],
                          inputs=[{'artifact': 's11:outputs/replica-seed-7.json'},
                                  {'artifact': 'inputs/residual-model.json'}])
    codes = sorted(e['code'] for e in custody.input_errors(store, decomposition, run_dir)[0])
    assert codes == ['predecessor_unreceipted', 'run_input_missing'], codes
    # Positive control: replicas adopted from their governed launch are consumed.
    replica = _adopted(nc, store, run_dir, _step('s12'), {'outputs/replica.json': '{"value": 1.0}'})
    receipted = _step('s21', 'compare', depends_on=['s12'], inputs=[{'artifact': replica[0]['artifact']}])
    assert custody.input_errors(store, receipted, run_dir)[0] == []


def _inputs_trusted(original):
    def input_errors(store, step, run_dir, *, ancestors=()):
        errors, found, run_inputs = original(store, step, run_dir, ancestors=ancestors)
        return [e for e in errors if e['code'] not in ('predecessor_unreceipted', 'run_input_missing')], found, run_inputs
    return input_errors


register(Mutation('M09', 'ravel.controller.step.custody:input_errors', _inputs_trusted, ('C29',),
                  binding=MUTATION_CONTROLLER, why='a decomposition consumes replicas and models no launch produced'))


@case('C30', binding=CONTROLLER)
def test_C30_a_residual_attribution_needs_a_measured_contribution_and_a_reviewer_seat(nc):
    # The installed route consumer owns C30. P5 alone is a planning protocol and
    # does not establish a scientific attribution above the retained noise model.
    from nc_route_entry import RouteHarness
    harness = RouteHarness(nc)
    clean = {'kind': 'comparison', 'noise_model': 'approved fictional replica-spread model', 'above_noise': True}
    control = harness.run(clean)
    hostile = harness.run(dict(clean, noise_model='', above_noise=False))
    assert control.errors == () and control.effects == 1, control.report
    assert hostile.errors == ('attribution_below_noise',) and hostile.effects == 0, hostile.report
    assert b'attribution_below_noise' in hostile.sink
    assert control.ending['scientific_claims_adopted'] == hostile.ending['scientific_claims_adopted'] == []
    assert not control.receipt['accepted'] and not hostile.receipt['accepted']


register(Mutation('M11', 'ravel.controller.routes.analysis.evidence:ADAPTERS',
                  lambda original: {**original, 'compare': lambda *a, **k: [
                      e for e in original['compare'](*a, **k) if e.get('row') != 'C30']}, ('C30',),
                  binding=MUTATION_CONTROLLER, why='the route comparison does not reject attribution below noise'))
