"""Handbook recipe and partition examples on synthetic local ROOT data."""
import copy

import numpy as np
import pytest
import uproot

from ravel.physics.columnar import engine, expressions, formats

SKILL = 'columnar-analysis'


def descriptor():
    return {'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic',
            'source': 'synthetic event schema, energy in GeV', 'format': 'root', 'tree': 'events',
            'collections': {}, 'met': {'magnitude': 'met', 'phi': 'phi'},
            'event': {'weight': 'weight'}, 'variations': {}}


def recipe():
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'Synthetic missing momentum',
            'weights': {'generator': 'weight', 'factors': []}, 'objects': [],
            'observables': [{'name': 'missing', 'op': 'met'}],
            'regions': [{'name': 'inclusive', 'cuts': [{'name': 'Finite momentum', 'expr': 'missing >= 0'}]}],
            'histograms': [{'name': 'momentum', 'region': 'inclusive', 'observable': 'missing',
                            'edges': [0, 10, 20], 'unit': 'GeV', 'label': 'Missing transverse momentum',
                            'normalization': 'raw', 'underflow': 'separate', 'overflow': 'separate'}]}


def test_record_lists_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ['compile-columnar-recipe', 'merge-columnar-partitions']


def test_compile_refuses_unknown_weight_and_histogram_edges(handbook, tmp_path):
    compile_checked = handbook.load(SKILL, 'compile-columnar-recipe')['compile_checked']
    assert compile_checked(recipe(), descriptor(), tmp_path).event_fields == ['weight']
    bad = recipe(); bad['weights']['generator'] = 'missing_weight'
    with pytest.raises(ValueError, match='not an event field'):
        compile_checked(bad, descriptor(), tmp_path)
    bad = recipe(); bad['histograms'][0]['edges'] = [0, 20, 10]
    with pytest.raises(ValueError):
        compile_checked(bad, descriptor(), tmp_path)


def test_partition_merge_preserves_signed_moments_and_refuses_overlap(handbook, tmp_path):
    compile_checked = handbook.load(SKILL, 'compile-columnar-recipe')['compile_checked']
    merge_checked = handbook.load(SKILL, 'merge-columnar-partitions')['merge_checked']
    path = tmp_path / 'sample.root'
    with uproot.recreate(path) as f:
        f['events'] = {'met': np.array([5., 15., 25.]), 'phi': np.zeros(3),
                       'weight': np.array([2., -1., 3.])}
    plan = compile_checked(recipe(), descriptor(), tmp_path)
    def part(a, b):
        return engine.analyse({'inputs': [{'path': str(path), 'file_index': 0,
                                         'entry_start': a, 'entry_stop': b}], 'chunk_size': 2}, plan)
    first, second = part(0, 1), part(1, 3)
    assert merge_checked([first, second])['variations'] == part(0, 3)['variations']
    with pytest.raises(ValueError, match='overlap'):
        merge_checked([first, copy.deepcopy(first)])
    changed = copy.deepcopy(second); changed['plan_identity'] = 'other-plan'
    with pytest.raises(ValueError, match='different recipes'):
        merge_checked([first, changed])


def test_undefined_value_fails_a_negated_cut():
    cut = expressions.compile_expression('not (x > 1)', allowed={'x'})
    assert cut.evaluate_cut({'x': np.array([0., np.nan, 2.])}).tolist() == [True, False, False]


def test_missing_branch_is_refused(tmp_path):
    path = tmp_path / 'missing.root'
    with uproot.recreate(path) as f:
        f['events'] = {'met': np.array([1.]), 'phi': np.zeros(1)}
    desc = formats.load_descriptor(descriptor())
    with pytest.raises(ValueError, match='weight'):
        desc.check_file(path, collections=[], event_fields=['weight'])
