"""Thirteen installed controller route admission/adoption controls and real sink endings."""
from copy import deepcopy

import pytest

from nc_cases import CONTROLLER, case, controller_installed
from nc_route_entry import RouteHarness
from nc_mutations import CONTROLLER as REAL_MUTATION, PEER, Mutation, register, returns
from nc_route_peer import fixture, fake_probe, real_probe


def _observe(nc, clean, hostile, code, *, harness=None):
    harness = harness or RouteHarness(nc)
    refused = harness.run(hostile)
    compliant = harness.run(clean)
    assert compliant.errors == () and compliant.effects == 1, compliant.report
    assert compliant.producer == b'fictional route output\n'
    assert compliant.ending['scientific_claims_adopted'] == []
    assert refused.ending['scientific_claims_adopted'] == []
    assert not refused.receipt['accepted'] and not compliant.receipt['accepted']
    assert refused.errors == (code,), ('SOURCE-GAP', code, refused.report)
    assert refused.effects == 0 and refused.producer is None
    assert code.encode() in refused.sink


@case('R01', binding=CONTROLLER)
def test_R01_a_development_phrase_cannot_authorize_effects_before_the_scientific_route_pin(nc):
    clean = fixture('dispatch')
    hostile = dict(clean, route_pinned=False)
    _observe(nc, clean, hostile, 'route_not_pinned')


@case('R02', binding=CONTROLLER)
def test_R02_supplied_input_scope_cannot_drop_the_new_generation_deliverable(nc):
    clean = fixture('population')
    hostile = dict(clean, covered=['supplied-result'])
    _observe(nc, clean, hostile, 'missing_deliverable')


@case('R03', binding=CONTROLLER)
def test_R03_a_pdf_without_its_staged_build_custody_cannot_be_delivered(nc):
    clean = fixture('manuscript')
    hostile = dict(clean, build_custody=False)
    _observe(nc, clean, hostile, 'manuscript_unreceipted')


@case('R04', binding=CONTROLLER)
def test_R04_a_requested_amplitude_component_remains_in_the_parent_population(nc):
    clean = fixture('population')
    clean.update(deliverables=['amplitude-a', 'amplitude-b'], covered=['amplitude-a', 'amplitude-b'])
    hostile = dict(clean, covered=['amplitude-a'])
    _observe(nc, clean, hostile, 'missing_deliverable')


@case('R08', binding=CONTROLLER)
def test_R08_a_calculation_without_its_requested_units_is_not_adopted(nc):
    clean = fixture('quantity')
    harness = RouteHarness(nc)
    hostile = deepcopy(clean)
    hostile['actual'].pop('units')
    _observe(nc, clean, hostile, 'units_changed_or_missing', harness=harness)
    changed = deepcopy(clean)
    changed['actual']['units'] = 'MeV'
    # A complete descriptor reaches continuity validation independently of the
    # missing-field schema guard; both must preserve the requested units.
    _observe(nc, clean, changed, 'units_changed_or_missing', harness=harness)


@case('R09', binding=CONTROLLER)
def test_R09_a_scoped_child_cannot_erase_an_additional_requested_stage(nc):
    clean = fixture('stages')
    clean.update(requested_stages=['likelihood'], stages=['likelihood'])
    hostile = dict(clean, requested_stages=['likelihood', 'generate'])
    _observe(nc, clean, hostile, 'missing_stage')


@case('R12', binding=CONTROLLER)
def test_R12_an_inference_step_cannot_add_training_under_existing_authority(nc):
    clean = fixture('inference')
    hostile = dict(clean, training=True)
    _observe(nc, clean, hostile, 'training_not_admitted')


@case('E04', binding=CONTROLLER)
def test_E04_a_routine_selecting_another_final_state_cannot_claim_reproduction(nc):
    clean = fixture('routine')
    hostile = dict(clean, routine_final_state='three leptons')
    _observe(nc, clean, hostile, 'routine_final_state_mismatch')


@case('E05', binding=CONTROLLER)
def test_E05_axes_from_memory_have_no_read_source_evidence(nc):
    clean = fixture('figure')
    hostile = deepcopy(clean)
    hostile['panels'][0].pop('source')
    _observe(nc, clean, hostile, 'figure_source_missing')


@case('E09', binding=CONTROLLER)
def test_E09_generation_waits_for_retained_external_recipe_bytes(nc):
    clean = fixture('recipe')
    hostile = deepcopy(clean)
    hostile['recipe']['retained'] = False
    _observe(nc, clean, hostile, 'external_recipe_missing')


@case('E21', binding=CONTROLLER)
def test_E21_full_compute_must_depend_on_the_early_smoke_waypoint(nc):
    clean = fixture('ladder')
    hostile = deepcopy(clean)
    hostile['steps'][1]['depends_on'] = []
    _observe(nc, clean, hostile, 'rung_ladder_skipped')


@case('E22', binding=CONTROLLER)
def test_E22_a_watcher_cannot_depend_on_a_transient_scratch_script(nc):
    clean = fixture('watcher')
    hostile = deepcopy(clean)
    hostile['watcher']['durable'] = False
    _observe(nc, clean, hostile, 'watcher_target_not_durable')


@case('E23', binding=CONTROLLER)
def test_E23_a_three_argument_call_cannot_arm_a_five_argument_watcher(nc):
    clean = fixture('watcher')
    hostile = deepcopy(clean)
    hostile['watcher']['arguments'] = ['a', 'b', 'c']
    _observe(nc, clean, hostile, 'watcher_preflight_failed')


for mechanism, rows in (
    ('M01', ('R01', 'R03', 'R12', 'E09', 'E21')),
    ('M02', ('R02', 'R04', 'R08', 'R09')),
    ('M14', ('E04', 'E05')),
    ('M18', ('E22', 'E23')),
    ('M27', ('R02', 'R04', 'R09')),
):
    register(Mutation(mechanism, 'nc_route_peer:guard',
                      lambda original: lambda payload: {'errors': [], 'notices': [], 'disclosures': []},
                      rows, binding=PEER, why='remove the route component admission in the explicit peer fake'))


for mechanism, target, replacement, rows in (
    ('M01', 'ravel.controller.graph:_admitted',
     lambda original: lambda state, store, plan, ready, steps: (list(ready), {}, {}), ('R01',)),
    ('M02', ('ravel.controller.routes.study.contracts:scope', 'ravel.controller.routes.study:scope'), returns(lambda: []), ('R02', 'R04', 'R09')),
    ('M01', 'ravel.controller.routes.manuscript:delivery_errors', returns(lambda: []), ('R03',)),
    ('M11', ('ravel.controller.routes.study.contracts:quantity_errors', 'ravel.controller.routes.study.evidence:quantity_errors'), returns(lambda: []), ('R08',)),
    ('M04', 'ravel.controller.routes.ml.training:inference_errors', returns(lambda: []), ('R12',)),
    ('M14', 'ravel.controller.routes.analysis.evidence:ADAPTERS',
     lambda original: {**original, 'inputs.route': lambda *a, **k: []}, ('E04',)),
    ('M15', 'ravel.controller.routes.analysis.evidence:ADAPTERS',
     lambda original: {**original, 'inputs.figures': lambda *a, **k: []}, ('E05',)),
    ('M09', 'ravel.controller.routes.study.evidence:check',
     lambda original: lambda *a, **k: [r for r in original(*a, **k) if r.get('row') != 'E09'], ('E09',)),
    ('M17', 'ravel.controller.routes.analysis.guard:ladder_errors', returns(lambda: []), ('E21',)),
    ('M10', 'ravel.workflow.preflight_watcher:probe_fire_command', returns(lambda: ('pass', [])), ('E23',)),
):
    register(Mutation(mechanism, target, replacement, rows, binding=REAL_MUTATION,
                      why='disable the installed admission reached by the required real component probe'))
