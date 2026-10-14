"""The scientific critic's review obligations follow the requested quantity and the plan's contracts."""
import json
import re

from ravel.workflow import critic_obligations as co
from ravel.workflow import role_registry

SIGNATURES = {
    'op-generate': {'stages': ['generation', 'shower'], 'effects': ['generates_events']},
    'op-statistic': {'stages': ['statistic'], 'effects': []},
    'op-fit': {'stages': ['statistic', 'figure'], 'effects': []},
}
ARTIFACT_NAME = re.compile(r'\b[\w.-]+\.(?:json|csv|root|ya?ml|lhe(?:\.gz)?|hepmc|txt|npz|parquet)\b|RESULT\.md')


def _plan(kind, definition, operations):
    return {'claims': [{'id': 'C1', 'kind': kind, 'statistic': {'source': 'policy_default', 'definition': definition}}],
            'nodes': [{'id': f'N{i}', 'operation': op} for i, op in enumerate(operations, 1)]}


EXCLUSION = _plan('exclusion', '95% CLs', ['op-generate', 'op-statistic'])
MEASUREMENT = _plan('estimate', 'profile-likelihood interval', ['op-fit'])


def test_obligations_differ_between_an_exclusion_and_a_measurement():
    excl = {row['id'] for row in co.obligations(EXCLUSION, signatures=SIGNATURES)}
    meas = {row['id'] for row in co.obligations(MEASUREMENT, signatures=SIGNATURES)}
    assert excl != meas
    assert 'exclusion:root-resolved' in excl and 'exclusion:root-resolved' not in meas
    assert 'estimate:fit-quality' in meas and 'estimate:fit-quality' not in excl
    # Stage contracts come from the planned operations, not from the claim kind.
    assert 'normalization-basis' in excl and 'normalization-basis' not in meas
    assert 'figure-criteria' in meas and 'figure-criteria' not in excl
    assert {'provenance', 'scope', 'units-and-conventions'} <= excl & meas


def test_obligations_cite_no_fixed_artifact_name():
    for plan in (EXCLUSION, MEASUREMENT):
        text = json.dumps(co.obligations(plan, signatures=SIGNATURES))
        assert not ARTIFACT_NAME.search(text), ARTIFACT_NAME.search(text).group(0)


def test_declared_statistic_is_carried_into_the_obligation():
    rows = co.obligations(_plan('exclusion', 'S/sqrt(B + dB^2) >= 2', ['op-statistic']), signatures=SIGNATURES)
    check = next(r['check'] for r in rows if r['id'] == 'exclusion:statistic-as-declared')
    assert 'S/sqrt(B + dB^2) >= 2' in check


def test_unknown_claim_kind_is_refused():
    try:
        co.obligations(_plan('unheard-of', None, []), signatures=SIGNATURES)
    except ValueError as exc:
        assert 'unheard-of' in str(exc)
    else:
        raise AssertionError('unknown claim kind accepted')


def test_every_plan_claim_kind_has_obligations():
    from ravel.validation import validate_request_plan as rp
    from ravel.workflow.request_plan import STATEMENTS
    assert set(STATEMENTS) | set(rp.STATISTIC_KINDS) | set(rp.NO_STATISTIC_KINDS) <= set(co.BY_CLAIM)


def test_critic_card_builds_checks_from_supplied_obligations():
    text = json.dumps(role_registry.load('physics-critic'))
    assert 'critic_obligations' in text
    for fixed in ('sr_yields', 'cutflow_cert', 'validate_cutflow.py'):
        assert fixed not in text
