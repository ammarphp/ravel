"""A new search on supplied simulated samples is a research parent with analysis and statistics candidates.

In-process intake only: the reading, the contract and the draft plan. No tool or model runs.
Every request is synthetic.
"""
import pytest

from ravel.workflow import intake, request_plan, route_prompt
from ravel.workflow.request_reading import supplied_sample_search

NEW_SEARCHES = [
    'Design a new search on these supplied simulated samples and show the discovery sensitivity against the '
    'previous analysis.',
    'We have reconstructed Monte Carlo samples for signal and background. Develop a dedicated search for a heavy '
    'resonance decaying to two leptons on the supplied samples, and compare its expected discovery significance '
    'with the previous analysis at the same luminosity.',
    'Here are our simulated signal and background samples. Carry out a new blinded search with the simulated '
    'samples we supply, define signal, control and validation regions, and show the expected discovery '
    'sensitivity against the previous analysis on the same signal points.',
]


def routed(prompt):
    contract, reading, _ = route_prompt.route_records(prompt, interpretation=None, additions=None)
    plan = request_plan.draft(reading, contract)
    return contract, reading, [node['operation'] for node in plan['nodes']]


@pytest.mark.parametrize('prompt', NEW_SEARCHES)
def test_a_new_search_on_supplied_samples_is_a_research_parent_with_both_candidates(prompt):
    assert supplied_sample_search(prompt)
    contract, reading, operations = routed(prompt)
    assert contract['task_mode'] == 'research' and contract['intake']['kind'] == 'research'
    assert intake.handoff_route(contract, reading) == 'research'
    assert {'columnar-analysis', 'search-statistics'} <= set(operations)
    assert contract['blocking'] == [] and contract['compute_plan'] == 'none'


@pytest.mark.parametrize('prompt', [
    'Design a new search using the simulated samples we supply.',
    'Build a new analysis on the samples provided and report its sensitivity.',
    'Carry out a dedicated search on our simulated signal and background samples.',
    'Optimise a new search on the attached ntuples.',
])
def test_supplied_samples_are_read_before_and_after_the_noun(prompt):
    assert supplied_sample_search(prompt)
    assert routed(prompt)[0]['task_mode'] == 'research'


@pytest.mark.parametrize('prompt', [
    'Reinterpret the previous analysis with the supplied simulated samples and show the expected significance.',
    'Design a new search for a heavy resonance and generate the signal events needed for it.',
    'Compute the expected discovery significance of the previous analysis at twice the luminosity.',
])
def test_other_requests_are_not_read_as_a_new_search_on_supplied_samples(prompt):
    assert not supplied_sample_search(prompt)


def test_a_significance_study_without_a_new_search_keeps_its_route():
    prompt = 'Estimate the expected discovery significance for a counting experiment with the supplied yields.'
    assert not supplied_sample_search(prompt)
    assert intake.proposal(prompt)['kind'] == 'method_study'
