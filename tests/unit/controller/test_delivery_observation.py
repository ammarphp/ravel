"""One observed delivery audit through the complete inert controller run."""
from test_composition_wave_a import (run, _assert_milestones, _assert_derived_and_verified,
                                    _assert_final_review)  # noqa: F401
from ravel.controller import graph


def test_current_delivery_audit_is_observed_and_credited(run):
    store, summary = run
    found = graph.delivery_assumption_evidence(store.run_dir)
    assert found['status'] == 'satisfied', (found['reason'], found['evidence'])
    _assert_milestones(store, summary)
    _assert_derived_and_verified(store)
    _assert_final_review(store, summary)
