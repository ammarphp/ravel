"""The v2 shadow derivation runs on the whole battery beside v1 and changes no v1 record.

For every case the v1 records (reading, contract, plan, plan-check errors, flags and label)
are computed, the shadow derivation runs on them, and the v1 records are compared byte for
byte with themselves and with a fresh v1 computation after the shadow ran.
"""
import copy

import pytest

import intake_records as ir
from ravel.workflow import intake_v2_shadow as shadow

CASES = ir.case_params()


@pytest.mark.parametrize('case', CASES)
def test_shadow_beside_v1_changes_no_v1_record(case):
    prompt = case['prompt']
    records = shadow.v1_records(prompt)
    before = shadow.canonical(records)
    result = shadow.shadow(prompt, records)
    assert shadow.canonical(records) == before
    assert shadow.canonical(shadow.v1_records(prompt)) == before
    governance = result['governance']
    assert governance['status'] == 'shadow' and governance['kind'] == 'governance-shadow'
    assert set(governance['lineage']) == {c['id'] for c in records['plan']['claims']}
    assert governance['label'] == records['plan']['label']
    assert all(row['direction'] in ('tightened', 'dropped') for row in result['diff']['rows'])


def test_shadow_refuses_a_derivation_that_changes_a_v1_record(monkeypatch):
    prompt = ir.load_cases('generic.json')[0]['prompt']
    records = shadow.v1_records(prompt)

    def mutating(reading, plan, registry=None, observed=None):
        plan['status'] = 'proposed'
        return {'stages': {}, 'launch': {'checkin1_required': False}}

    monkeypatch.setattr(shadow, 'derive', mutating)
    with pytest.raises(RuntimeError, match='changed a v1 record'):
        shadow.shadow(prompt, copy.deepcopy(records))
