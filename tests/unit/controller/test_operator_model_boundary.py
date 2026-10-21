"""The operator boundary refuses agent preferences that name a model the model catalogue does not admit.

``ravel operator init|set --agent-preferences`` checks every ``tier_models`` model against the model
catalogue before writing and prints one remedy per flagged model. A run's frozen preferences are only
labelled (``catalogue_problems``); ``operator.validate`` stays catalogue-free for synthetic fixtures.
The catalogue module is a stand-in here, so the tests hold whether or not the build ships one.
"""
from __future__ import annotations

import json
import sys
import types

from test_p06_support import operator_home  # noqa: F401
from ravel.controller.authority import cli, operator

KNOWN = 'catalogued-model-a'
UNKNOWN = 'uncatalogued-model-b'


def _catalogue(monkeypatch, known=(KNOWN,)):
    module = types.ModuleType('ravel.workflow.model_catalogue')
    module.problem = lambda model_id: None if model_id in known else 'model:uncatalogued'
    module.remedy = lambda model_id: (f'model {model_id!r} is not in the model catalogue: add a row for it '
                                      'to the catalogue overlay or adopt it with ravel models detect --adopt')
    module.lookup = lambda model_id: {'id': model_id} if model_id in known else None
    monkeypatch.setitem(sys.modules, 'ravel.workflow.model_catalogue', module)
    return module


def _preferences(*models):
    return {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': ['toy-worker'],
            'tier_models': {tier: {'toy-worker': model} for tier, model in zip(('judgment', 'agent', 'cheap'), models)}}


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_init_refuses_an_uncatalogued_model_with_its_remedy_before_writing(operator_home, capsys, monkeypatch):
    catalogue = _catalogue(monkeypatch)
    code, out, err = run(capsys, 'init', '--mode', 'autonomous',
                         '--agent-preferences', json.dumps(_preferences(KNOWN, UNKNOWN)))
    assert code == 2 and out == ''
    assert err.splitlines() == ['ravel operator: ' + catalogue.remedy(UNKNOWN)]
    assert not operator.ledger_path().exists()


def test_set_refuses_an_uncatalogued_model_and_keeps_the_prior_configuration(operator_home, capsys, monkeypatch):
    catalogue = _catalogue(monkeypatch)
    assert run(capsys, 'init', '--mode', 'autonomous')[0] == 0
    before = operator.ledger_path().read_bytes()
    code, _, err = run(capsys, 'set', '--agent-preferences', json.dumps(_preferences(UNKNOWN, 'other-unknown')))
    assert code == 2
    # One line per flagged model, in tier-name order (agent before judgment).
    assert err.splitlines() == ['ravel operator: ' + catalogue.remedy('other-unknown'),
                                'ravel operator: ' + catalogue.remedy(UNKNOWN)]
    assert operator.ledger_path().read_bytes() == before


def test_catalogued_models_are_accepted_and_written(operator_home, capsys, monkeypatch):
    _catalogue(monkeypatch)
    preferences = _preferences(KNOWN, KNOWN, KNOWN)
    code, out, err = run(capsys, 'init', '--mode', 'autonomous', '--agent-preferences', json.dumps(preferences))
    assert code == 0 and err == ''
    assert json.loads(out)['agent_preferences'] == preferences


def test_problems_are_empty_without_a_catalogue_and_validate_never_consults_it(operator_home, monkeypatch):
    monkeypatch.setitem(sys.modules, 'ravel.workflow.model_catalogue', None)
    assert operator.agent_preference_problems(_preferences(UNKNOWN)) == []
    _catalogue(monkeypatch)
    assert operator.agent_preference_problems(_preferences(UNKNOWN, UNKNOWN)) == [
        sys.modules['ravel.workflow.model_catalogue'].remedy(UNKNOWN)]
    assert operator.agent_preference_problems(None) == []
    # Synthetic fixture ids still reach the ledger through the library entry point.
    written = operator.init(mode='autonomous', agent_preferences=_preferences(UNKNOWN))
    assert written['agent_preferences']['tier_models']['judgment'] == {'toy-worker': UNKNOWN}


def test_frozen_preferences_carry_a_catalogue_label_that_the_validator_does_not_admit(operator_home, monkeypatch):
    from ravel.controller.step import seats
    _catalogue(monkeypatch)
    frozen = {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': ['claude-cli-worker'],
              'tier_models': {'agent': {'claude-cli-worker': UNKNOWN}}}
    prefs, kept, _ = seats.preferences({'agent_preferences': frozen}, {'family': 'production'})
    assert kept == ['claude-cli-worker']
    assert prefs['catalogue_problems'] == [sys.modules['ravel.workflow.model_catalogue'].remedy(UNKNOWN)]
    frozen['tier_models'] = {'agent': {'claude-cli-worker': KNOWN}}
    assert 'catalogue_problems' not in seats.preferences({'agent_preferences': frozen}, {'family': 'production'})[0]
    labelled = {**frozen, 'catalogue_problems': ['x']}
    try:
        operator.set_values({'agent_preferences': labelled}) if operator._ledger_rows() else \
            operator.init(mode='autonomous', agent_preferences=labelled)
    except ValueError as exc:
        assert 'agent_preferences' in str(exc)
    else:
        raise AssertionError('operator.validate admitted the run-internal catalogue label')
