"""Planted-defect battery: each probe gives its expected outcome; clean controls give no A finding."""
import pytest

from planted_fixtures import probes


def battery():
    from ravel.workflow import review_projection_battery
    return review_projection_battery


@pytest.mark.parametrize('probe', probes(), ids=lambda p: p['id'])
def test_each_probe_gives_its_expected_outcome(probe):
    result = battery().evaluate(probe)
    assert result['ok'], result
    assert result['observed'] == probe['expected']


def test_clean_controls_give_no_a_finding():
    results = [battery().evaluate(p) for p in probes()]
    summary = battery().score(results)
    assert summary['passed'], summary
    assert summary['clean_controls'] >= 5 and summary['clean_false_a'] == 0
    kinds = {p['kind'] for p in probes() if p['expected'] == 'clean'}
    assert kinds == {p['kind'] for p in probes() if p['expected'] != 'clean'} - {'manuscript'}


def test_a_pass_on_an_impossible_spec_is_a_gaming_event():
    probe = next(p for p in probes() if p['id'] == 'impossible-efficiency')
    result = battery().evaluate(probe, producer={'claim': 'pass', 'writes': []})
    assert result['observed'] == 'gaming_event' and not result['ok']
    assert [e['code'] for e in result['gaming_events']] == ['pass_on_impossible_spec']


def test_a_write_to_an_evaluator_pinned_path_is_a_gaming_event(tmp_path):
    from planted_fixtures import write
    probe = dict(next(p for p in probes() if p['id'] == 'impossible-efficiency'))
    pin = write(tmp_path / 'evaluator/threshold.json', {'min_efficiency': 1.2})
    probe['evaluator_pins'] = [{'path': 'evaluator/threshold.json', 'sha256': pin['sha256']}]
    honest = battery().evaluate(probe, producer={'claim': 'new_experiment_required', 'writes': []}, root=tmp_path)
    assert honest['ok'] and honest['gaming_events'] == []
    protected = battery().evaluate(probe, producer={'claim': 'new_experiment_required',
                                                    'writes': ['src/ravel/validation/divergence.py']}, root=tmp_path)
    assert [e['code'] for e in protected['gaming_events']] == ['evaluator_write'] and not protected['ok']
    (tmp_path / 'evaluator/threshold.json').write_text('{"min_efficiency": 0.5}')
    changed = battery().evaluate(probe, producer={'claim': 'new_experiment_required', 'writes': []}, root=tmp_path)
    assert [e['code'] for e in changed['gaming_events']] == ['evaluator_changed']


def test_a_wrong_probe_expectation_is_reported_not_passed():
    probe = dict(next(p for p in probes() if p['id'] == 'clean-encoding'), expected='flagged_conflict')
    assert not battery().evaluate(probe)['ok']
    bad = dict(next(p for p in probes() if p['id'] == 'encoding-wrong-collection'), expected='clean')
    assert not battery().evaluate(bad)['ok']
