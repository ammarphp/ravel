"""An unavailable full detector simulation is held, preserving the requested fidelity."""
import pytest

from ravel.workflow import request_reading, request_plan
from ravel.validation import validate_task_contract as vtc


def test_full_simulation_request_is_held_and_never_downgraded():
    prompt = 'Predict binned signal yields using full simulation of the detector.'
    reading = request_reading.document(prompt)
    assert any('full simulation' in row['statement'].lower() for row in reading['boundaries'])
    plan = request_plan.draft(reading, {'prompt': prompt})
    assert plan['nodes'] and all(n['status'] == 'held' and n['rung'] == 'none' for n in plan['nodes'])


def test_negated_or_quoted_full_simulation_does_not_hold_fast_response():
    prompt = 'Predict binned signal yields with fast response; do not use full simulation.'
    reading = request_reading.document(prompt)
    assert not any('full simulation' in row['statement'].lower() for row in reading['boundaries'])


def test_contract_cannot_silently_execute_a_full_simulation_request():
    from ravel.workflow import route_prompt
    contract = route_prompt.route('Generate a signal sample using full simulation of the detector.')
    contract.update(compute_plan='full', cost_estimate={'mode': 'full', 'points': 1,
                    'walltime_h': [1, 2]}, detector_mode='parton-level')
    assert any('full simulation' in e.lower() for e in vtc.validate(contract))


def test_reference_to_full_simulation_or_a_named_tool_is_not_a_hold():
    for prompt in ('Compare the fast response with the published full-simulation efficiencies.',
                   'Simulate a new forward calorimeter in GEANT4 and estimate its energy resolution.'):
        reading = request_reading.document(prompt)
        assert not any('full simulation' in row['statement'].lower() for row in reading['boundaries'])


DEMANDS = (
    'Predict binned signal yields of a toy model using full detector simulation.',
    'Predict binned signal yields of a toy model with Geant4 full simulation of the signal.',
    'Predict binned signal yields of a toy model using fullsim.',
    'Predict binned signal yields of a toy model; the detector response must be full simulation, not fast simulation.',
    'Predict binned signal yields of a toy model using a full Geant4-based simulation of the detector.',
    'Predict binned signal yields of a toy model at full-simulation level.',
    'Predict binned signal yields of a toy model with full sim.',
)
DESCRIPTIONS = (
    'Using full simulation, the published analysis derived its efficiencies; reproduce the expected '
    'exclusion contour of a toy model with the fast detector response.',
    'Reproduce the expected exclusion contour of a toy model. The reference signal samples were produced '
    'with full simulation.',
    'Reproduce the expected exclusion contour of a toy model using full simulation efficiencies from the '
    'supplied table.',
)


def _held(prompt):
    return any('full simulation' in row['statement'].lower() for row in request_reading.document(prompt)['boundaries'])


@pytest.mark.parametrize('prompt', DEMANDS)
def test_natural_full_simulation_demands_are_held(prompt):
    assert _held(prompt)


@pytest.mark.parametrize('prompt', DESCRIPTIONS)
def test_descriptions_of_the_reference_are_not_held(prompt):
    assert not _held(prompt)
    plan = request_plan.draft(request_reading.document(prompt), {'prompt': prompt})
    assert not all(n['status'] == 'held' for n in plan['nodes'])


def test_legacy_archive_audit_does_not_reread_boundaries():
    from ravel.workflow import route_prompt
    contract = route_prompt.route('Generate a signal sample using full simulation of the detector.')
    contract.update(compute_plan='full', cost_estimate={'mode': 'full', 'points': 1,
                    'walltime_h': [1, 2]}, detector_mode='parton-level')
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        assert not any('full simulation' in e.lower() for e in vtc.validate(contract, legacy=True))


# The request names a published, reference, official or original result and, in the same
# sentence, asks this run to simulate the detector in full: the run is the simulating agent.
REFERENCE_DEMANDS = (
    'Reproduce the published exclusion contour of a toy model using full simulation of the detector.',
    'Reproduce the published exclusion contour of a toy model using full detector simulation.',
    'Reproduce the official analysis of a toy model; use full simulation, as the collaboration did.',
    'Run full simulation for the signal, then compare with the published figure.',
    'Reproduce the published expected limit using full detector simulation.',
    'Reproduce the reference yields of a toy model with full simulation of the detector.',
    'Reproduce the original cut flow of a toy model; the signal samples must be produced with full simulation.',
)
# The mention says how the reference was produced, or names products this run consumes.
REFERENCE_DESCRIPTIONS = (
    'Reproduce the published limit, which was obtained with full simulation, using the fast detector response.',
    'Predict binned signal yields of a toy model using efficiencies obtained from full simulation.',
    'Reproduce the expected contour of a toy model; the collaboration used full simulation for its signal samples.',
)


@pytest.mark.parametrize('prompt', REFERENCE_DEMANDS)
def test_full_simulation_demands_next_to_a_reference_are_held(prompt):
    assert _held(prompt)


@pytest.mark.parametrize('prompt', REFERENCE_DESCRIPTIONS)
def test_reference_production_and_consumed_products_are_not_held(prompt):
    assert not _held(prompt)
