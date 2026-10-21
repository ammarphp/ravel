"""Mutation-harness control ordering; these checks confer no mechanism adequacy."""
from types import SimpleNamespace

import pytest

import test_nc_mutation_adequacy as adequacy


def test_every_named_positive_control_runs_before_a_caught_mutant_can_end_the_search(monkeypatch):
    mutation = SimpleNamespace(cases=('first', 'second'))
    monkeypatch.setattr(adequacy, '_case', lambda name: (name, None))

    def run(case, variant, factory, row):
        return 'caught' if variant is not None or case == 'second' else 'passed'

    monkeypatch.setattr(adequacy, '_run', run)
    with pytest.raises(AssertionError, match='unmodified case second is not passing'):
        adequacy._require_detection(mutation, None)


def test_all_clean_controls_precede_the_first_disabled_variant(monkeypatch):
    mutation = SimpleNamespace(cases=('first', 'second'))
    monkeypatch.setattr(adequacy, '_case', lambda name: (name, None))
    observed = []

    def run(case, variant, factory, row):
        observed.append((case, variant is not None))
        return 'caught' if variant is not None else 'passed'

    monkeypatch.setattr(adequacy, '_run', run)
    adequacy._require_detection(mutation, None)
    assert observed == [('first', False), ('second', False), ('first', True)]
