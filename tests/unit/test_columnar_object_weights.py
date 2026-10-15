"""Synthetic controls for declared object weights, periods and missing momentum."""
import math

import awkward as ak
import numpy as np
import pytest
import uproot

from ravel.physics.columnar import engine, formats
from ravel.physics.columnar.recipe import compile_recipe


def descriptor():
    return formats.load_descriptor({
        'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic arrays',
        'source': 'fabricated values', 'format': 'root', 'tree': 'events',
        'collections': {'candidates': {'fields': {
            'pt': 'pt', 'eta': 'eta', 'phi': 'phi',
            'mass': {'fixed': 0, 'source': 'synthetic massless objects'},
            'sf': 'sf', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'}}},
        'met': {'px': 'mx', 'py': 'my'},
        'event': {k: k for k in ('generator', 'era', 'first', 'second', 'correction', 'alternate')},
        'variations': {'shift': {'branches': {'correction': 'correction_shift'}}}})


def recipe(factors=()):
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic selection',
            'weights': {'generator': 'generator', 'factors': list(factors)},
            'objects': [{'name': 'selected', 'from': 'candidates', 'select': 'pt > 10'}],
            'observables': [{'name': 'n', 'op': 'count', 'collection': 'selected'}],
            'regions': [{'name': 'inclusive', 'cuts': []}], 'histograms': [],
            'event_record': {'max_events': 100, 'observables': ['n']}}


def write_events(path, *, pts=None, sf=None, data=None, mc=None, era=None, correction=True, phis=None):
    pts = [[20.], [30., 5.], [], [40., 25., 15.]] if pts is None else pts
    n = len(pts)
    def jagged(values):
        return ak.unflatten(np.asarray([x for row in values for x in row], float), [len(x) for x in values])
    zeros = [[0.] * len(x) for x in pts]
    columns = {'pt': jagged(pts), 'eta': jagged(zeros), 'phi': jagged(zeros if phis is None else phis),
               'sf': jagged(sf if sf is not None else [[2.] * len(x) for x in pts]),
               'data_eff': jagged(data if data is not None else [[.8] * len(x) for x in pts]),
               'mc_eff': jagged(mc if mc is not None else [[.5] * len(x) for x in pts]),
               'mx': np.full(n, 3.), 'my': np.full(n, 4.), 'generator': np.ones(n),
               'era': np.asarray(era if era is not None else [1] * n, dtype=np.int32),
               'first': np.asarray(([1, 0, 1, 0] * n)[:n], dtype=np.bool_),
               'second': np.asarray(([0, 1, 0, 1] * n)[:n], dtype=np.bool_),
               'alternate': np.full(n, 7.)}
    if correction:
        columns['correction'] = np.full(n, 3.)
        columns['correction_shift'] = np.full(n, 5.)
    with uproot.recreate(path) as stream:
        stream.mktree('events', {k: ('var * float64' if isinstance(v, ak.Array) else v.dtype)
                                 for k, v in columns.items()})
        stream['events'].extend(columns)
    return path


def run(base, doc, paths=None, chunk=2):
    paths = [write_events(base / 'events.root')] if paths is None else paths
    plan = compile_recipe(doc, descriptor(), base)
    result = engine.analyse({'inputs': [{'path': str(p), 'file_index': i} for i, p in enumerate(paths)],
                             'chunk_size': chunk}, plan)
    return plan, result


def weights(result):
    return [r['weight'] for r in result['event_record']]


def test_object_product_matches_selected_loop(tmp_path):
    doc = recipe([{'object_product': {'objects': 'selected', 'field': 'sf'}}] * 2)
    _, result = run(tmp_path, doc)
    expected = [math.prod([2. for p in row if p > 10]) ** 2 for row in [[20.], [30., 5.], [], [40., 25., 15.]]]
    np.testing.assert_allclose(weights(result), expected, rtol=1e-12)


def test_optional_factor_across_files(tmp_path):
    doc = recipe([{'field': 'correction', 'optional_in_files': True,
                   'applies_when': {'field': 'era', 'in': [1]}}])
    paths = [write_events(tmp_path / 'a.root', era=[1, 2, 1, 2]),
             write_events(tmp_path / 'b.root', correction=False)]
    plan, result = run(tmp_path, doc, paths)
    assert weights(result) == [3., 1., 3., 1., 1., 1., 1., 1.]
    assert [r['optional_weights_missing'] for r in result['inputs']] == [[], ['correction']]
    assert plan.descriptor.check_file(paths[1], collections=plan.source_collections,
                                      event_fields=plan.event_fields)['optional_weights_missing'] == ['correction']


def test_named_met_override_is_used_by_angles_and_mass(tmp_path):
    doc = recipe()
    doc['observables'] += [
        {'name': 'hidden', 'op': 'met_override', 'base': 'met', 'add_invisible': ['selected']},
        {'name': 'hidden_phi', 'op': 'met_phi', 'met': 'hidden'},
        {'name': 'mass', 'op': 'mt', 'object': 'selected[0]', 'met': 'hidden'},
        {'name': 'angle', 'op': 'delta_phi', 'a': 'selected[0]', 'b': 'hidden'},
        {'name': 'minimum', 'op': 'min_delta_phi_met', 'collection': 'selected', 'met': 'hidden'}]
    doc['event_record']['observables'] += ['hidden', 'hidden_phi', 'mass', 'angle', 'minimum']
    path = write_events(tmp_path / 'met.root', pts=[[20., 30.]])
    _, result = run(tmp_path, doc, [path])
    row = result['event_record'][0]
    mag, phi = math.hypot(53., 4.), math.atan2(4., 53.)
    assert row['hidden'] == pytest.approx(mag)
    assert row['hidden_phi'] == pytest.approx(phi)
    assert row['angle'] == pytest.approx(phi)
    assert row['minimum'] == pytest.approx(phi)
    assert row['mass'] == pytest.approx(math.sqrt(2 * 30 * mag * (1 - math.cos(phi))))


def test_trigger_ratio_matches_one_two_and_three_object_law(tmp_path):
    pts = [[20.], [30., 20.], [40., 30., 20.]]
    data, mc = [[.8], [.9, .7], [.5, .6, .7]], [[.4], [.5, .6], [.2, .3, .4]]
    path = write_events(tmp_path / 'trigger.root', pts=pts, data=data, mc=mc)
    doc = recipe([{'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'}}])
    _, result = run(tmp_path, doc, [path])
    expected = [(1 - math.prod(1 - x for x in a)) / (1 - math.prod(1 - x for x in b))
                for a, b in zip(data, mc)]
    np.testing.assert_allclose(weights(result), expected, rtol=1e-12)


@pytest.mark.parametrize('empty', [False, True])
def test_zero_trigger_denominator_refuses_with_original_entry_index(tmp_path, empty):
    pts = [[20.], [20.], [20.], [] if empty else [20.]]
    path = write_events(tmp_path / 'zero.root', pts=pts, mc=[[.5], [.5], [.5], [] if empty else [0.]])
    doc = recipe([{'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'}}])
    with pytest.raises(ValueError, match='zero MC denominator at event index 3'):
        run(tmp_path, doc, [path])


@pytest.mark.parametrize('value', [-.01, 1.01, float('nan'), float('inf')])
def test_trigger_efficiencies_must_be_probabilities(tmp_path, value):
    path = write_events(tmp_path / 'invalid.root', pts=[[20.]], data=[[value]])
    doc = recipe([{'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'}}])
    with pytest.raises(ValueError, match=r'must be in \[0, 1\].*event index 0'):
        run(tmp_path, doc, [path])


def test_tiny_nonzero_efficiencies_are_not_rounded_to_zero(tmp_path):
    path = write_events(tmp_path / 'tiny.root', pts=[[20.]], data=[[2e-25]], mc=[[1e-25]])
    doc = recipe([{'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'}}])
    _, result = run(tmp_path, doc, [path])
    assert weights(result) == pytest.approx([2.])


def period_cut():
    return {'name': 'trigger selection', 'any_of_by_period': {
        'period_field': 'era', 'table': {'1': ['first'], '2': ['second']}}}


def test_period_cut_uses_exactly_the_fields_for_that_period(tmp_path):
    path = write_events(tmp_path / 'periods.root', era=[1, 1, 2, 2])
    doc = recipe()
    doc['regions'][0]['cuts'] = [period_cut()]
    _, result = run(tmp_path, doc, [path])
    assert [bool(r['regions']) for r in result['event_record']] == [True, False, False, True]
    assert result['variations']['nominal']['cutflows']['inclusive'][-1] == [2, 2., 2.]


def test_period_cut_unknown_period_refuses_even_after_a_failed_cut(tmp_path):
    path = write_events(tmp_path / 'unknown.root', era=[1, 9, 2, 2])
    doc = recipe()
    doc['regions'][0]['cuts'] = [{'name': 'empty selection', 'expr': 'n < 0'}, period_cut()]
    with pytest.raises(ValueError, match='unknown period .*9'):
        run(tmp_path, doc, [path])


def test_period_cut_rejects_nonboolean_fields(tmp_path):
    doc = recipe()
    cut = period_cut()
    cut['any_of_by_period']['table']['1'] = ['correction']
    doc['regions'][0]['cuts'] = [cut]
    with pytest.raises(ValueError, match='boolean values'):
        run(tmp_path, doc)


def test_multiple_chains_and_inherited_period_cut(tmp_path):
    doc = recipe()
    cut = period_cut()
    cut['any_of_by_period']['table']['1'] = ['first', 'second']
    doc['regions'][0]['cuts'] = [cut]
    doc['regions'].append({'name': 'derived', 'base': 'inclusive', 'cuts': [{'name': 'one object', 'expr': 'n == 1'}]})
    _, result = run(tmp_path, doc)
    assert result['variations']['nominal']['cutflows']['inclusive'][-1][0] == 4
    assert result['variations']['nominal']['cutflows']['derived'][-1][0] == 2


def test_missing_factor_still_refuses_without_optional_declaration(tmp_path):
    paths = [write_events(tmp_path / 'present.root'), write_events(tmp_path / 'absent.root', correction=False)]
    with pytest.raises(ValueError, match="branch 'correction'.*not in tree"):
        run(tmp_path, recipe(['correction']), paths)


def test_optional_read_summary_survives_merge_and_finalization(tmp_path):
    doc = recipe([{'field': 'correction', 'optional_in_files': True}])
    paths = [write_events(tmp_path / 'a.root'), write_events(tmp_path / 'b.root', correction=False)]
    plan = compile_recipe(doc, descriptor(), tmp_path)
    parts = [engine.analyse({'inputs': [{'path': str(p), 'file_index': i}]}, plan) for i, p in enumerate(paths)]
    merged = engine.merge(parts)
    result = engine.finalize(merged, plan, {'mode': 'none'}, out_dir=tmp_path / 'out')
    assert [r['optional_weights_missing'] for r in result['provenance']['inputs']] == [[], ['correction']]


def test_optional_present_malformed_branch_refuses(tmp_path):
    path = write_events(tmp_path / 'malformed.root')
    # This field is present but violates the scalar descriptor; optionality cannot hide it.
    with uproot.recreate(tmp_path / 'bad.root') as stream:
        with uproot.open(path) as source:
            arrays = source['events'].arrays(library='ak', how=dict)
        arrays['correction'] = ak.Array([[1.]] * 4)
        stream['events'] = arrays
    with pytest.raises(ValueError, match='jagged'):
        run(tmp_path, recipe([{'field': 'correction', 'optional_in_files': True}]), [tmp_path / 'bad.root'])


@pytest.mark.parametrize('other_use', ['generator', 'condition', 'cut', 'mandatory_factor'])
def test_optional_field_is_required_when_used_by_another_operation(tmp_path, other_use):
    doc = recipe([{'field': 'correction', 'optional_in_files': True}])
    if other_use == 'generator':
        doc['weights']['generator'] = 'correction'
    elif other_use == 'condition':
        doc['weights']['factors'][0]['applies_when'] = {'field': 'correction', 'in': [1]}
    elif other_use == 'cut':
        doc['regions'][0]['cuts'] = [{'name': 'required period', 'any_of_by_period': {
            'period_field': 'correction', 'table': {'1': ['first']}}}]
    else:
        doc['weights']['factors'].append('correction')
    path = write_events(tmp_path / 'absent.root', correction=False)
    with pytest.raises(ValueError, match="branch 'correction'.*not in tree"):
        run(tmp_path, doc, [path])


def test_scoped_factors_and_weight_systematics_keep_their_conditions(tmp_path):
    path = write_events(tmp_path / 'scoped.root', era=[1, 2, 1, 2])
    doc = recipe([{'field': 'correction', 'applies_when': {'field': 'era', 'in': [1]}},
                  {'object_product': {'objects': 'selected', 'field': 'sf'},
                   'applies_when': {'field': 'era', 'in': [2]}}])
    doc['systematics'] = [{'name': 'up', 'kind': 'weight-factor', 'replace': {'correction': 'alternate'}}]
    _, result = run(tmp_path, doc, [path])
    assert weights(result) == [3., 2., 3., 8.]
    assert result['variations']['up']['cutflows']['inclusive'][0][1] == 24.


def test_optional_factor_branch_variation_and_replacement(tmp_path):
    doc = recipe([{'field': 'correction', 'optional_in_files': True}])
    doc['systematics'] = [{'name': 'shifted', 'kind': 'branch-variation', 'variation': 'shift'},
                          {'name': 'replacement', 'kind': 'weight-factor', 'replace': {'correction': 'alternate'}}]
    paths = [write_events(tmp_path / 'a.root'), write_events(tmp_path / 'b.root', correction=False)]
    _, result = run(tmp_path, doc, paths)
    assert result['variations']['nominal']['cutflows']['inclusive'][0][1] == 16.
    assert result['variations']['shifted']['cutflows']['inclusive'][0][1] == 24.
    assert result['variations']['replacement']['cutflows']['inclusive'][0][1] == 56.


def test_object_weights_are_applied_to_enumerated_subsets(tmp_path):
    doc = recipe([{'object_product': {'objects': 'selected', 'field': 'sf'}}])
    doc['efficiency_maps'] = {'retention': {
        'source': {'format': 'json-grid', 'path': 'map.json'},
        'axes': [{'name': 'transverse momentum', 'unit': 'GeV'}],
        'out_of_range': 'refuse', 'citation': 'synthetic probabilities', 'semantics': 'absolute'}}
    (tmp_path / 'map.json').write_text('{"axes":[{"name":"transverse momentum","unit":"GeV","edges":[0,100]}],"values":[0.5]}')
    doc['objects'].append({'efficiency': {'name': 'retention', 'object': 'selected', 'map': 'retention',
                           'coordinates': ['pt'], 'application': 'enumerate', 'card_efficiency': 'synthetic input'}})
    path = write_events(tmp_path / 'enumeration.root', pts=[[20., 30.]])
    _, result = run(tmp_path, doc, [path])
    row = result['variations']['nominal']['cutflows']['inclusive'][0]
    assert row[1] == pytest.approx(.25 * (1 + 2 + 2 + 4))
    assert row[2] == pytest.approx(row[1] ** 2)


def test_object_product_random_selected_values_matches_loop(tmp_path):
    rng = np.random.default_rng(17)
    pts = [rng.uniform(0, 50, int(n)).tolist() for n in rng.integers(0, 8, 65)]
    sf = [rng.uniform(.7, 1.3, len(row)).tolist() for row in pts]
    # Rejected objects may contain unusable weights; they cannot enter the product.
    for p, s in zip(pts, sf):
        for i in range(len(p)):
            if p[i] <= 10:
                s[i] = float('nan')
    path = write_events(tmp_path / 'random.root', pts=pts, sf=sf)
    doc = recipe([{'object_product': {'objects': 'selected', 'field': 'sf'}}])
    plan, result = run(tmp_path, doc, [path], chunk=7)
    expected = [math.prod(s for p, s in zip(p_row, s_row) if p > 10) for p_row, s_row in zip(pts, sf)]
    np.testing.assert_allclose(weights(result), expected, rtol=1e-12)
    parts = [engine.analyse({'inputs': [{'path': str(path), 'entry_start': a, 'entry_stop': b}], 'chunk_size': 3}, plan)
             for a, b in [(0, 23), (23, 65)]]
    merged = engine.merge(parts)
    assert weights(merged) == weights(result)
    np.testing.assert_allclose(merged['variations']['nominal']['cutflows']['inclusive'],
                               result['variations']['nominal']['cutflows']['inclusive'], rtol=1e-12)


@pytest.mark.parametrize('factor', [
    {}, {'field': 'unknown'}, {'object_product': {'objects': 'unknown', 'field': 'sf'}},
    {'object_product': {'objects': 'selected', 'field': 'unknown'}},
    {'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff'}},
    {'field': 'correction', 'object_product': {'objects': 'selected', 'field': 'sf'}},
    {'field': 'correction', 'optional_in_files': 1},
    {'field': 'correction', 'applies_when': {'field': 'era', 'in': []}},
    {'field': 'correction', 'applies_when': {'field': 'era', 'in': ['first']}},
    {'field': 'correction', 'applies_when': {'field': 'unknown', 'in': [1]}},
    {'object_product': {'objects': 'selected', 'field': 'sf'}, 'optional_in_files': True}])
def test_invalid_typed_factors_refuse_during_compilation(tmp_path, factor):
    with pytest.raises(ValueError):
        compile_recipe(recipe([factor]), descriptor(), tmp_path)


@pytest.mark.parametrize('table', [{}, {'1': []}, {'one': ['first']}, {'1': ['unknown']},
                                 {'1': ['first'], '1.0': ['second']}, {'nan': ['first']}])
def test_invalid_period_tables_refuse_during_compilation(tmp_path, table):
    doc = recipe()
    cut = period_cut()
    cut['any_of_by_period']['table'] = table
    doc['regions'][0]['cuts'] = [cut]
    with pytest.raises(ValueError):
        compile_recipe(doc, descriptor(), tmp_path)


def test_met_override_components_chaining_and_conditional_consumers(tmp_path):
    path = write_events(tmp_path / 'vectors.root', pts=[[20., 30., 5.], []], phis=[[0., math.pi / 2, math.pi], []])
    doc = recipe()
    doc['observables'] += [
        {'name': 'hidden', 'op': 'met_override', 'base': 'met', 'add_invisible': ['selected'], 'only_if': 'n > 0'},
        {'name': 'same', 'op': 'met', 'met': 'hidden'},
        {'name': 'mass', 'op': 'mt', 'object': 'selected[0]', 'met': 'hidden', 'only_if': 'n > 0'},
        {'name': 'angle', 'op': 'delta_phi', 'a': 'hidden', 'b': 'selected[0]', 'only_if': 'n > 0'},
        {'name': 'double', 'op': 'met_override', 'base': 'hidden', 'add_invisible': ['selected']},
        {'name': 'original', 'op': 'met'}]
    doc['event_record']['observables'] += ['hidden', 'same', 'mass', 'angle', 'double', 'original']
    _, result = run(tmp_path, doc, [path])
    row, empty = result['event_record']
    mag = math.hypot(23., 34.)
    angle = math.pi / 2 - math.atan2(34., 23.)
    assert row['hidden'] == pytest.approx(mag)
    assert row['same'] == pytest.approx(mag)
    assert row['double'] == pytest.approx(math.hypot(43., 64.))
    assert row['angle'] == pytest.approx(angle)
    assert row['mass'] == pytest.approx(math.sqrt(2 * 30 * mag * (1 - math.cos(angle))))
    assert row['original'] == pytest.approx(5.)
    assert all(empty[key] is None for key in ['hidden', 'same', 'mass', 'angle', 'double'])
    assert empty['original'] == pytest.approx(5.)


def test_empty_override_keeps_input_vector_and_undefined_angles(tmp_path):
    path = write_events(tmp_path / 'empty.root', pts=[[]])
    doc = recipe()
    doc['observables'] += [
        {'name': 'hidden', 'op': 'met_override', 'base': 'met', 'add_invisible': ['selected']},
        {'name': 'direction', 'op': 'met_phi', 'met': 'hidden'},
        {'name': 'angle', 'op': 'min_delta_phi_met', 'collection': 'selected', 'met': 'hidden'}]
    doc['event_record']['observables'] += ['hidden', 'direction', 'angle']
    _, result = run(tmp_path, doc, [path])
    row = result['event_record'][0]
    assert row['hidden'] == pytest.approx(5.)
    assert row['direction'] == pytest.approx(math.atan2(4., 3.))
    assert row['angle'] is None


@pytest.mark.parametrize('observable', [
    {'name': 'bad', 'op': 'met_override', 'base': 'n', 'add_invisible': ['selected']},
    {'name': 'met', 'op': 'met_override', 'base': 'met', 'add_invisible': ['selected']},
    {'name': 'bad', 'op': 'met_override', 'base': 'met', 'add_invisible': []},
    {'name': 'bad', 'op': 'met_override', 'base': 'met', 'add_invisible': ['selected', 'selected']},
    {'name': 'bad', 'op': 'met_override', 'base': 'met', 'add_invisible': ['unknown']},
    {'name': 'bad', 'op': 'mt', 'object': 'selected[0]', 'met': 'n'},
    {'name': 'bad', 'op': 'min_delta_phi_met', 'collection': 'selected', 'met': 'later'},
    {'name': 'bad', 'op': 'delta_phi', 'a': 'selected[0]', 'b': 'n'}])
def test_invalid_vector_names_and_override_definitions_refuse(tmp_path, observable):
    doc = recipe()
    doc['observables'].append(observable)
    with pytest.raises(ValueError):
        compile_recipe(doc, descriptor(), tmp_path)


def test_inactive_trigger_factor_does_not_require_a_nonzero_acceptance(tmp_path):
    doc = recipe([{'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'},
                   'applies_when': {'field': 'era', 'in': [2]}}])
    path = write_events(tmp_path / 'inactive.root', pts=[[], [20.]], era=[1, 2])
    _, result = run(tmp_path, doc, [path])
    assert weights(result) == pytest.approx([1., 1.6])


@pytest.mark.parametrize('value', [float('nan'), float('inf')])
def test_invalid_selected_object_weight_refuses(tmp_path, value):
    path = write_events(tmp_path / 'invalid.root', pts=[[20.]], sf=[[value]])
    with pytest.raises(ValueError, match='object_product: invalid weight at event index 0'):
        run(tmp_path, recipe([{'object_product': {'objects': 'selected', 'field': 'sf'}}]), [path])


def test_zero_and_signed_object_weights_are_preserved(tmp_path):
    path = write_events(tmp_path / 'signed.root', pts=[[20.], [20.]], sf=[[-2.], [0.]])
    _, result = run(tmp_path, recipe([{'object_product': {'objects': 'selected', 'field': 'sf'}}]), [path])
    assert weights(result) == [-2., 0.]
    assert result['variations']['nominal']['cutflows']['inclusive'][0] == [2, -2., 4.]


def test_optional_policy_does_not_mutate_shared_descriptor(tmp_path):
    shared = descriptor()
    path = write_events(tmp_path / 'absent.root', correction=False)
    optional = compile_recipe(recipe([{'field': 'correction', 'optional_in_files': True}]), shared, tmp_path)
    required = compile_recipe(recipe(['correction']), shared, tmp_path)
    assert optional.descriptor.check_file(path, collections=optional.source_collections,
                                         event_fields=optional.event_fields)['optional_weights_missing'] == ['correction']
    with pytest.raises(ValueError, match="branch 'correction'"):
        required.descriptor.check_file(path, collections=required.source_collections, event_fields=required.event_fields)


def test_recompiling_a_plan_descriptor_does_not_inherit_optionality(tmp_path):
    optional = compile_recipe(recipe([{'field': 'correction', 'optional_in_files': True}]), descriptor(), tmp_path)
    required = compile_recipe(recipe(['correction']), optional.descriptor, tmp_path)
    path = write_events(tmp_path / 'absent.root', correction=False)
    with pytest.raises(ValueError, match="branch 'correction'"):
        required.descriptor.check_file(path, collections=required.source_collections, event_fields=required.event_fields)


def test_joined_recipe_delivers_weighted_histogram_cutflow_and_input_records(tmp_path):
    paths = [write_events(tmp_path / 'present.root', era=[1, 2, 2, 1]),
             write_events(tmp_path / 'absent.root', era=[1, 2, 2, 1], correction=False)]
    doc = recipe([
        {'object_product': {'objects': 'selected', 'field': 'sf'}},
        {'trigger_or_sf': {'objects': 'selected', 'data_eff': 'data_eff', 'mc_eff': 'mc_eff'},
         'applies_when': {'field': 'era', 'in': [1]}},
        {'field': 'correction', 'optional_in_files': True, 'applies_when': {'field': 'era', 'in': [1]}}])
    cut = period_cut()
    cut['any_of_by_period']['table'] = {'1': ['first', 'second'], '2': ['second']}
    doc['regions'][0]['cuts'] = [cut]
    doc['observables'].append({'name': 'hidden', 'op': 'met_override', 'base': 'met', 'add_invisible': ['selected']})
    doc['histograms'] = [{'name': 'missing momentum', 'region': 'inclusive', 'observable': 'hidden',
                          'edges': [0, 100], 'unit': 'GeV', 'label': 'Missing momentum', 'normalization': 'raw'}]
    plan, partial = run(tmp_path, doc, paths)
    result = engine.finalize(partial, plan, {'mode': 'none'}, out_dir=tmp_path / 'joined')
    expected = 0.
    for has_correction in [True, False]:
        for i, count in enumerate([1, 1, 0, 3]):
            if i == 2:  # period two requires only the second trigger field
                continue
            w = 2. ** count
            if i in [0, 3]:
                w *= (1 - .2 ** count) / (1 - .5 ** count)
                if has_correction:
                    w *= 3.
            expected += w
    assert result['histograms']['missing momentum']['nominal']['sumw'] == pytest.approx([expected])
    assert result['cutflows']['nominal'][0]['cuts'][-1]['sumw'] == pytest.approx(expected)
    assert [r['optional_weights_missing'] for r in result['provenance']['inputs']] == [[], ['correction']]
    assert result['event_accounting']['passed'] is True
