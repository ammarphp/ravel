"""Inert statistics and uncertainty records for synthetic result documents in tests.

The analysis route's step-07 check requires every limit to carry the engine's statistics record and an
uncertainty statement. Fixture documents that stand in for an engine's output use these: a statistics
record of one synthetic large-count region in which no statistics situation is detected (so its validity is
``valid`` and it recomputes under ``situations.audit``), and an uncertainty statement whose components are stated as not
evaluated, each with its reason. Neither claims any number the fixture does not carry.
"""
from ravel.physics.inference import situations, uncertainty


def inert_statistics(deliverables=("exclusion",)) -> dict:
    """Facts of one synthetic large-count region: no situation is detected, so the record is valid."""
    facts = situations.make_facts(deliverables=list(deliverables),
                                  bins=[{"channel": "SR", "bin": 0, "observed": 100.0, "background": 100.0}])
    return situations.record(facts, {})


def inert_uncertainty(observed=0.8, *, document=None) -> dict:
    reason = "an inert fixture result: no engine evaluated this component"
    components = [uncertainty.component("expected-band", "statistical", status="not-evaluated",
                                        meaning="spread of the expected limit", reason=reason),
                  uncertainty.component("systematic-impact", "systematic", status="not-evaluated",
                                        meaning="impact of the nuisance parameters", reason=reason),
                  uncertainty.component("root-precision", "method", status="not-evaluated",
                                        meaning="numerical precision of the limit", reason=reason)]
    if document is None:
        document = {"obs_limit": observed, "exp_limits": [0.5, 0.7, 0.9, 1.2, 1.6],
                    "limit_status": {"observed": "resolved", "expected": ["resolved"] * 5}}
    values = uncertainty.for_limits(document)["values"]
    return uncertainty.statement("95% CLs upper limit on the signal strength", values, components,
                                 [], [{"component": "every uncertainty", "reason": reason}])


def with_statistics(document, *, observed=0.8) -> dict:
    """The document with the inert statistics record and uncertainty statement added."""
    return {**document, "statistics": inert_statistics(),
            "uncertainty": inert_uncertainty(observed, document=document)}
