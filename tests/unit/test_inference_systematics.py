"""Declared systematic-uncertainty registry: provenance, correlation model, template application."""
import numpy as np
import pytest

from ravel.physics.inference import systematics


def registry(**extra):
    doc = {'schema_version': 1, 'sources': [
        {'name': 'luminosity', 'kind': 'normsys', 'relative': 0.017,
         'applies_to': {'samples': 'all', 'regions': 'all'}, 'correlation': 'correlated',
         'origin': 'cited', 'citation': 'Luminosity determination note, table 3'},
        {'name': 'xsec_top', 'kind': 'normsys', 'up': 1.06, 'down': 0.95,
         'applies_to': {'samples': ['top'], 'regions': 'all'}, 'correlation': 'per-region',
         'origin': 'requester-assumption', 'statement': 'assume +6/-5 percent on the top cross section'},
        {'name': 'top_generator', 'kind': 'histosys', 'construction': 'one-sided-symmetrised',
         'applies_to': {'samples': ['top'], 'regions': ['SR', 'CR']}, 'correlation': 'correlated',
         'alternative': {'SR': [12.0, 6.0], 'CR': [110.0]},
         'origin': 'cited', 'citation': 'alternative generator sample, same selection'},
    ], 'absent': [{'component': 'jet energy scale', 'reason': 'nominal-only samples'}]}
    doc.update(extra)
    return systematics.Registry(doc)


def test_uncited_or_unstated_values_are_refused():
    doc = registry().document
    bad = {**doc, 'sources': [{**doc['sources'][0], 'citation': ''}]}
    with pytest.raises(ValueError, match='citation'):
        systematics.Registry(bad)
    bad = {**doc, 'sources': [{**doc['sources'][1], 'statement': None}]}
    with pytest.raises(ValueError, match='statement'):
        systematics.Registry(bad)
    with pytest.raises(ValueError, match='absent'):
        systematics.Registry({k: v for k, v in doc.items() if k != 'absent'})
    with pytest.raises(ValueError):
        systematics.Registry({**doc, 'sources': [{**doc['sources'][0], 'relative': -0.1}]})


def test_histosys_from_an_alternative_sample():
    reg = registry()
    variations = reg.variations('top', 'SR', np.array([10.0, 5.0]))
    up, down = variations['top_generator']
    assert np.allclose(up, [12.0, 6.0]) and np.allclose(down, [8.0, 4.0])
    lumi_up, lumi_down = variations['luminosity']
    assert np.allclose(lumi_up, [10.17, 5.085]) and np.allclose(lumi_down, [9.83, 4.915])
    assert 'xsec_top_SR' in variations  # per-region correlation gives a region-specific name
    comparison = reg.alternative_comparison('top', {'SR': np.array([10.0, 5.0]), 'CR': np.array([100.0])})
    assert comparison['top_generator']['CR']['relative_difference'] == pytest.approx([0.1])


def test_mirrored_variation_below_zero_is_refused_not_clipped():
    reg = registry()
    with pytest.raises(ValueError, match='negative'):
        reg.variations('top', 'SR', np.array([5.0, 2.0]))


def test_pyhf_modifiers_follow_the_correlation_model():
    reg = registry()
    mods = reg.modifiers('top', 'CR', np.array([100.0]))
    kinds = {(m['name'], m['type']) for m in mods}
    assert ('luminosity', 'normsys') in kinds and ('xsec_top_CR', 'normsys') in kinds
    assert ('top_generator', 'histosys') in kinds
    histo = next(m for m in mods if m['type'] == 'histosys')
    assert histo['data'] == {'hi_data': [110.0], 'lo_data': [90.0]}
    other = reg.modifiers('wjets', 'VR', np.array([3.0]))
    assert [m['name'] for m in other] == ['luminosity']
    assert reg.summary()['absent'] == [{'component': 'jet energy scale', 'reason': 'nominal-only samples'}]
