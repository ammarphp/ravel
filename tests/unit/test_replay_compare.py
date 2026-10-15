"""Replay comparison of declared quantities on synthetic completed run directories.

Only the execution ledger and the selected outputs are read; no plan, approval or worker
is involved. Numbers are synthetic.
"""
import json
from pathlib import Path
import uuid

import pytest

from ravel.workflow import replay
from ravel.workflow.state_io import atomic_json, read_json


def result(**changes):
    value = {'status': 'passed', 'physics_validated': False,
             'generated_utc': '2026-01-01T00:00:00+00:00', 'job': str(uuid.uuid4()), 'attempt_id': 'a-1',
             'histogram': {'edges': [0.0, 1.0, 2.0, 3.0], 'sumw': [1.5, 2.25, 0.75],
                           'sumw2': [0.5, 1.125, 0.3125], 'counts': [3, 4, 2]},
             'cutflow': [{'cut': 'all', 'events': 100}, {'cut': 'selected', 'events': 9}],
             'fit': {'mu_hat': 0.4123456789, 'mu95': 1.7320508075688772, 'converged': True}}
    for pointer, new in changes.items():
        target = value
        parts = pointer.split('/')[1:]
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        last = parts[-1]
        if isinstance(target, list):
            target[int(last)] = new
        else:
            target[last] = new
    return value


def run(path, document, *, extra=None):
    out = path / 'outputs/attempt-1'
    out.mkdir(parents=True)
    atomic_json(out / 'result.json', document)
    for name, value in (extra or {}).items():
        atomic_json(out / name, value)
    atomic_json(path / 'inputs/science-plan.json', {'schema_version': 2})
    atomic_json(path / 'execution_state.json', {'schema_version': 1, 'revision': 1, 'stages': {
        'science': {'status': 'succeeded', 'outputs': ['outputs/attempt-1'], 'attempt_id': str(uuid.uuid4())}}})
    return path


def test_one_bin_sumw2_relative_difference_is_named(tmp_path):
    a = run(tmp_path / 'a', result())
    b = run(tmp_path / 'b', result(**{'/histogram/sumw2/1': 1.125 * (1 + 1e-6)}))
    comparison = replay.compare(a, b)
    assert comparison['verdict'] == 'mismatch' and comparison['equal'] is False
    assert [(m['document'], m['pointer']) for m in comparison['mismatches']] == [('result.json', '/histogram/sumw2/1')]
    assert 'relative difference' in comparison['mismatches'][0]['reason']
    assert comparison['physics_validated'] is False


def test_timestamps_attempt_ids_and_uuids_are_ignored(tmp_path):
    a = run(tmp_path / 'a', result())
    b = run(tmp_path / 'b', result(**{'/generated_utc': '2026-03-04T05:06:07+00:00', '/attempt_id': 'a-2'}))
    comparison = replay.compare(a, b)
    assert read_json(a / 'outputs/attempt-1/result.json')['job'] != read_json(b / 'outputs/attempt-1/result.json')['job']
    assert comparison['verdict'] == 'equal', comparison['mismatches']
    reasons = {r['pointer']: r['reason'] for r in comparison['ignored']}
    assert reasons['/generated_utc'] == reasons['/attempt_id'] == 'record metadata'
    assert reasons['/job'] == 'embedded identifier or timestamp'


def test_integer_counts_are_exact_and_floats_use_the_stated_tolerance(tmp_path):
    a = run(tmp_path / 'a', result())
    b = run(tmp_path / 'b', result(**{'/cutflow/1/events': 10, '/fit/mu95': 1.7320508075688772 * (1 + 1e-12)}))
    comparison = replay.compare(a, b)
    assert [m['pointer'] for m in comparison['mismatches']] == ['/cutflow/1/events']
    assert comparison['mismatches'][0]['reason'] == 'integer count differs (exact)'
    tolerances = tmp_path / 'tolerances.json'
    atomic_json(tolerances, {'schema_version': 1, 'default_relative': 1e-5})
    c = run(tmp_path / 'c', result(**{'/histogram/sumw2/1': 1.125 * (1 + 1e-6)}))
    assert replay.compare(a, c, tolerances)['verdict'] == 'equal'


def test_missing_document_bool_and_string_differences_are_mismatches(tmp_path):
    a = run(tmp_path / 'a', result(), extra={'summary.json': {'regions': ['SR1', 'SR2']}})
    b = run(tmp_path / 'b', result(**{'/fit/converged': False}))
    comparison = replay.compare(a, b)
    assert {(m['document'], m['pointer']) for m in comparison['mismatches']} == {
        ('summary.json', ''), ('result.json', '/fit/converged')}


def test_run_dir_paths_and_byte_digests_are_not_quantities(tmp_path):
    a = run(tmp_path / 'a', result(**{'/histogram/source': str(tmp_path / 'a/work/h.yoda'), '/result_sha256': 'a' * 64}))
    b = run(tmp_path / 'b', result(**{'/histogram/source': str(tmp_path / 'b/work/h.yoda'), '/result_sha256': 'b' * 64}))
    comparison = replay.compare(a, b)
    assert comparison['verdict'] == 'equal', comparison['mismatches']
    assert comparison['provenance_differences'][0]['pointer'] == '/result_sha256'


def test_non_json_outputs_are_listed_not_compared(tmp_path):
    a = run(tmp_path / 'a', result())
    b = run(tmp_path / 'b', result())
    for rd, text in ((a, 'one'), (b, 'two')):
        (rd / 'outputs/attempt-1/figure.png').write_text(text)
    comparison = replay.compare(a, b)
    assert comparison['verdict'] == 'equal'
    assert comparison['not_compared'] == [{'document': 'figure.png',
                                           'reason': 'no declared-quantity reader for this file type; bytes are not compared'}]


@pytest.mark.parametrize('seeds', [('/sampled/seed', 11, 12), None])
def test_statistical_tolerance_requires_both_seeds(tmp_path, seeds):
    sampled = {'mean': [10.02, 9.97], 'error': [0.05, 0.05]}
    other = {'mean': [9.95, 10.04], 'error': [0.05, 0.05]}
    if seeds:
        sampled['seed'], other['seed'] = seeds[1], seeds[2]
    a = run(tmp_path / 'a', result(**{'/sampled': sampled}))
    b = run(tmp_path / 'b', result(**{'/sampled': other}))
    tolerances = tmp_path / 'tolerances.json'
    atomic_json(tolerances, {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': '/sampled/mean', 'seed_pointer': '/sampled/seed',
         'n_sigma': 3, 'uncertainty_pointer': '/sampled/error'}]})
    comparison = replay.compare(a, b, tolerances)
    if seeds:
        assert comparison['verdict'] == 'equal', comparison['mismatches']
    else:
        assert comparison['verdict'] == 'not_comparable' and comparison['equal'] is False
        assert {r['reason'] for r in comparison['not_comparable']} == {'not comparable: seed not recorded'}
        assert [r['pointer'] for r in comparison['not_comparable']] == ['/sampled/mean/0', '/sampled/mean/1']


def test_statistical_tolerance_still_reports_a_real_shift(tmp_path):
    a = run(tmp_path / 'a', result(**{'/sampled': {'mean': 10.0, 'seed': 1}}))
    b = run(tmp_path / 'b', result(**{'/sampled': {'mean': 10.5, 'seed': 2}}))
    tolerances = tmp_path / 'tolerances.json'
    atomic_json(tolerances, {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': '/sampled/mean', 'seed_pointer': '/sampled/seed', 'absolute': 0.1}]})
    comparison = replay.compare(a, b, tolerances)
    assert [m['pointer'] for m in comparison['mismatches']] == ['/sampled/mean']


@pytest.mark.parametrize('document', [
    {'schema_version': 2},
    {'schema_version': 1, 'unknown': True},
    {'schema_version': 1, 'default_relative': 2},
    {'schema_version': 1, 'statistical': [{'document': 'result.json', 'pointer': '/x', 'seed_pointer': '/s'}]},
    {'schema_version': 1, 'statistical': [{'document': 'result.json', 'pointer': '/x', 'seed_pointer': '/s', 'n_sigma': 2}]},
    {'schema_version': 1, 'statistical': [{'document': 'result.json', 'pointer': 'x', 'seed_pointer': '/s', 'absolute': 1}]},
])
def test_malformed_tolerances_are_refused(tmp_path, document):
    atomic_json(tmp_path / 't.json', document)
    with pytest.raises(ValueError):
        replay.read_tolerances(tmp_path / 't.json')


def test_schema_file_matches_the_reader():
    schema = json.loads((Path(replay.__file__).resolve().parents[1] / 'data/governed_replay/tolerances.schema.json').read_text())
    assert set(schema['properties']) == set(replay.TOLERANCE_KEYS)
    assert set(schema['$defs']['statistical']['properties']) == set(replay.STATISTICAL_KEYS)
    assert schema['properties']['default_relative']['default'] == replay.DEFAULT_RELATIVE


def test_incomplete_runs_are_not_compared(tmp_path):
    a = run(tmp_path / 'a', result())
    b = run(tmp_path / 'b', result())
    state = read_json(b / 'execution_state.json')
    state['stages']['science']['status'] = 'failed'
    atomic_json(b / 'execution_state.json', state)
    with pytest.raises(ValueError, match='completed original'):
        replay.compare(a, b)


@pytest.mark.parametrize('key,left,right', [('generated', 50000, 49000), ('pid', 11, 13),
                                           ('log', -12.5, -99.0), ('duration_seconds', 1.0, 2.0),
                                           ('value_at', 1, 2), ('worker_pid', 11, 13),
                                           ('attempt_id', 1, 2)])
@pytest.mark.parametrize('depth', [0, 3])
def test_numeric_metadata_names_are_quantities(tmp_path, key, left, right, depth):
    a_doc, b_doc = {key: left}, {key: right}
    for _ in range(depth):
        a_doc, b_doc = {'nested': a_doc}, {'nested': b_doc}
    comparison = replay.compare(run(tmp_path / 'a', a_doc), run(tmp_path / 'b', b_doc))
    assert comparison['verdict'] == 'mismatch'
    assert comparison['mismatches'][0]['pointer'] == '/nested' * depth + '/' + key
    if type(left) is int:
        assert comparison['mismatches'][0]['reason'] == 'integer count differs (exact)'
    assert comparison['ignored'] == []


@pytest.mark.parametrize('left,right', [(True, False), ([1], [2]), ({'value': 1}, {'value': 2})])
def test_nested_metadata_names_never_suppress_containers_or_booleans(tmp_path, left, right):
    comparison = replay.compare(run(tmp_path / 'a', {'nested': {'attempt_id': left}}),
                                run(tmp_path / 'b', {'nested': {'attempt_id': right}}))
    assert comparison['verdict'] == 'mismatch'


def test_duration_is_ignored_only_by_declared_pointer(tmp_path):
    a = run(tmp_path / 'a', {'value': 1.73, 'diagnostics': {'duration_seconds': 1.0}})
    b = run(tmp_path / 'b', {'value': 1.73, 'diagnostics': {'duration_seconds': 2.0}})
    assert replay.compare(a, b)['verdict'] == 'mismatch'
    rules = tmp_path / 'rules.json'
    atomic_json(rules, {'schema_version': 1, 'ignore': [
        {'pointer': '/diagnostics/duration_seconds', 'reason': 'recorded execution duration'}]})
    comparison = replay.compare(a, b, rules)
    assert comparison['verdict'] == 'equal'
    assert comparison['ignored'] == [{'document': 'result.json', 'pointer': '/diagnostics/duration_seconds',
                                      'reason': 'recorded execution duration'}]


def test_root_ignore_is_refused_by_reader_and_schema(tmp_path):
    import jsonschema
    rules = {'schema_version': 1, 'ignore': [{'pointer': ''}]}
    path = tmp_path / 'rules.json'
    atomic_json(path, rules)
    schema = read_json(Path(replay.__file__).resolve().parents[1] / 'data/governed_replay/tolerances.schema.json')
    with pytest.raises(ValueError, match='non-empty'):
        replay.read_tolerances(path)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rules, schema)


@pytest.mark.parametrize('pointer,seed_pointer', [('/value', ''), ('', ''), ('/histogram/sumw', '/histogram'),
                                                  ('/sampled/mean', '/sampled/mean')])
def test_seed_pointer_covering_its_quantity_is_refused(tmp_path, pointer, seed_pointer):
    import jsonschema
    rules = {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': pointer, 'seed_pointer': seed_pointer, 'absolute': 1}]}
    atomic_json(tmp_path / 'rules.json', rules)
    with pytest.raises(ValueError, match='seed_pointer'):
        replay.read_tolerances(tmp_path / 'rules.json')
    if seed_pointer == '':
        schema = read_json(Path(replay.__file__).resolve().parents[1] / 'data/governed_replay/tolerances.schema.json')
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(rules, schema)


def test_seed_pointer_of_one_row_cannot_cover_the_quantity_of_another(tmp_path):
    row = {'document': 'result.json', 'absolute': 1}
    rules = {'schema_version': 1, 'statistical': [{**row, 'pointer': '/sampled/mean', 'seed_pointer': '/sampled/seed'},
                                                  {**row, 'pointer': '/other', 'seed_pointer': '/sampled'}]}
    atomic_json(tmp_path / 'rules.json', rules)
    with pytest.raises(ValueError, match='seed_pointer'):
        replay.read_tolerances(tmp_path / 'rules.json')
    # The same pointers in two different documents do not interact.
    rules['statistical'][1]['document'] = 'other.json'
    atomic_json(tmp_path / 'separate.json', rules)
    assert len(replay.read_tolerances(tmp_path / 'separate.json')[0]['statistical']) == 2


def test_document_suppressed_by_a_seed_pointer_is_not_comparable(tmp_path):
    a = run(tmp_path / 'a', {'histogram': {'sumw': 1.73}}, extra={'visible.json': {'quantity': 2}})
    b = run(tmp_path / 'b', {'histogram': {'sumw': 99.0}}, extra={'visible.json': {'quantity': 2}})
    rules = tmp_path / 'rules.json'
    atomic_json(rules, {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': '/absent', 'seed_pointer': '/histogram', 'absolute': 1}]})
    comparison = replay.compare(a, b, rules)
    # The row names no quantity of this document, so its seed pointer hides nothing: the difference is reported.
    assert comparison['verdict'] == 'mismatch' and comparison['equal'] is False
    assert [(m['document'], m['pointer']) for m in comparison['mismatches']] == [('result.json', '/histogram/sumw')]
    assert comparison['not_comparable'] == [{'document': 'result.json', 'pointer': '/absent',
                                            'reason': 'not comparable: declared sampled quantity absent from both runs'}]
    # A document whose only leaf is the seed of a present, empty quantity still has nothing compared.
    for rd, seed in ((a, 7), (b, 8)):
        atomic_json(rd / 'outputs/attempt-1/result.json', {'sampled': {}, 'seed': seed})
    atomic_json(tmp_path / 'seeded.json', {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': '/sampled', 'seed_pointer': '/seed', 'absolute': 1}]})
    comparison = replay.compare(a, b, tmp_path / 'seeded.json')
    assert comparison['verdict'] == 'not_comparable' and comparison['equal'] is False
    assert comparison['not_comparable'] == [{'document': 'result.json', 'pointer': '',
                                            'reason': 'all document leaves suppressed by declared ignore rows or seed pointers'}]


@pytest.mark.parametrize('document', [{}, [], {'generated_utc': '2026-01-01T00:00:00Z'}])
def test_zero_quantity_leaves_is_not_comparable(tmp_path, document):
    comparison = replay.compare(run(tmp_path / 'a', document), run(tmp_path / 'b', document))
    assert comparison['verdict'] == 'not_comparable'
    assert comparison['leaves_compared'] == 0
    assert comparison['equal'] is False


def test_all_declared_ignored_leaves_name_the_document(tmp_path):
    a = run(tmp_path / 'a', {'value': 1.73}, extra={'visible.json': {'quantity': 2}})
    b = run(tmp_path / 'b', {'value': 99.0}, extra={'visible.json': {'quantity': 2}})
    rules = tmp_path / 'rules.json'
    atomic_json(rules, {'schema_version': 1, 'ignore': [{'document': 'result.json', 'pointer': '/value'}]})
    comparison = replay.compare(a, b, rules)
    assert comparison['verdict'] == 'not_comparable'
    assert comparison['not_comparable'] == [{'document': 'result.json', 'pointer': '',
                                            'reason': 'all document leaves suppressed by declared ignore rows or seed pointers'}]
    # A visible leaf in the suppressed document restores comparability.
    for rd in (a, b):
        atomic_json(rd / 'outputs/attempt-1/result.json', {'value': 1.73, 'quantity': 2})
    assert replay.compare(a, b, rules)['verdict'] == 'equal'


def test_non_figure_output_prevents_equal_and_cli_success(tmp_path, capsys):
    a, b = run(tmp_path / 'a', {'quantity': 1.73}), run(tmp_path / 'b', {'quantity': 1.73})
    for rd, value in ((a, '1.73'), (b, '99.0')):
        (rd / 'outputs/attempt-1/histogram.txt').write_text(value)
    comparison = replay.compare(a, b)
    assert comparison['verdict'] == 'equal_json_only' and comparison['equal'] is False
    assert comparison['not_compared'][0]['document'] == 'histogram.txt'
    out = tmp_path / 'receipt.json'
    assert replay.main(['compare', '--original', str(a), '--replay', str(b), '--out', str(out)]) == 1
    assert read_json(out)['verdict'] == 'equal_json_only'
    assert replay.main(['compare', '--original', str(a), '--replay', str(b), '--out', str(tmp_path / 'receipt-zero.json'),
                        '--exit-zero']) == 0
    assert json.loads(capsys.readouterr().out.split('\n{')[0])['equal'] is False


@pytest.mark.parametrize('left,right,seed_a,seed_b,verdict', [
    (10.0, 10.09, 7, 7, 'mismatch'), (10.0, 10.09, 7, 8, 'equal'),
    (10.0, 10.0 * (1 + 1e-12), 7, 7, 'equal'), (10, 11, 7, 7, 'mismatch'),
    (10, 11, 7, 8, 'mismatch')])
def test_sampled_quantity_uses_deterministic_rule_for_same_seed(tmp_path, left, right, seed_a, seed_b, verdict):
    a = run(tmp_path / 'a', {'sampled': {'value': left, 'seed': seed_a}})
    b = run(tmp_path / 'b', {'sampled': {'value': right, 'seed': seed_b}})
    rules = tmp_path / 'rules.json'
    atomic_json(rules, {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': '/sampled/value', 'seed_pointer': '/sampled/seed', 'absolute': 2}]})
    comparison = replay.compare(a, b, rules)
    assert comparison['verdict'] == verdict
    if type(left) is int:
        assert comparison['mismatches'][0]['reason'] == 'integer count differs (exact)'


def test_replay_package_extra_document_is_reported(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    for package in (a, b):
        atomic_json(package / 'submission.json', {})
        atomic_json(package / 'run/inputs/science-plan.json', {})
        atomic_json(package / 'results/result.json', {'quantity': 1.73})
    atomic_json(b / 'results/extra.json', {'quantity': 99.0})
    comparison = replay.compare(a, b)
    assert comparison['verdict'] == 'mismatch'
    assert comparison['mismatches'] == [{'document': 'extra.json', 'pointer': '',
                                         'reason': 'document absent from the original'}]


@pytest.mark.parametrize('left,right', [(True, 1), (False, 0), (1, True), (0, False)])
def test_boolean_and_number_are_a_type_mismatch(tmp_path, left, right):
    comparison = replay.compare(run(tmp_path / 'a', {'quantity': left}), run(tmp_path / 'b', {'quantity': right}))
    assert comparison['verdict'] == 'mismatch'
    assert comparison['mismatches'][0]['reason'] == 'type differs'


def test_statistical_boolean_does_not_bypass_seed_requirement(tmp_path):
    a, b = run(tmp_path / 'a', {'sampled': True}), run(tmp_path / 'b', {'sampled': True})
    rules = tmp_path / 'rules.json'
    atomic_json(rules, {'schema_version': 1, 'statistical': [
        {'document': 'result.json', 'pointer': '/sampled', 'seed_pointer': '/seed', 'absolute': 1}]})
    comparison = replay.compare(a, b, rules)
    assert comparison['verdict'] == 'not_comparable'
    assert comparison['not_comparable'][0]['reason'] == 'not comparable: seed not recorded'


def package(path, document, *, cwd=None):
    """A submission package whose copied plan records the original run directory."""
    atomic_json(path / 'submission.json', {})
    atomic_json(path / 'run/inputs/science-plan.json', {} if cwd is None else {'stage_binding': {'cwd': cwd}})
    atomic_json(path / 'results/result.json', document)
    return path


def test_packaged_original_run_directory_paths_are_normalised(tmp_path):
    old = '/synthetic/original-run'
    a = package(tmp_path / 'a', {'quantity': 1.73, 'histogram_file': old + '/work/h.root'}, cwd=old)
    b = run(tmp_path / 'b', {'quantity': 1.73, 'histogram_file': str(tmp_path / 'b/work/h.root')})
    comparison = replay.compare(a, b)
    assert comparison['verdict'] == 'equal', comparison['mismatches']
    assert {'document': 'result.json', 'pointer': '/histogram_file',
            'reason': 'normalised run-directory path'} in comparison['ignored']
    # A different file below the run directory is still a difference.
    c = run(tmp_path / 'c', {'quantity': 1.73, 'histogram_file': str(tmp_path / 'c/work/other.root')})
    assert [m['pointer'] for m in replay.compare(a, c)['mismatches']] == ['/histogram_file']
    # Two packages recorded in two run directories compare the same way.
    d = package(tmp_path / 'd', {'quantity': 1.73, 'histogram_file': '/synthetic/replay-run/work/h.root'},
                cwd='/synthetic/replay-run')
    assert replay.compare(a, d)['verdict'] == 'equal'


def test_package_without_a_recorded_run_directory_keeps_its_paths_literal(tmp_path):
    a = package(tmp_path / 'a', {'quantity': 1.73, 'histogram_file': '/synthetic/original-run/work/h.root'})
    b = run(tmp_path / 'b', {'quantity': 1.73, 'histogram_file': str(tmp_path / 'b/work/h.root')})
    assert [m['pointer'] for m in replay.compare(a, b)['mismatches']] == ['/histogram_file']


def statistical(tmp_path, **row):
    rules = tmp_path / 'rules.json'
    atomic_json(rules, {'schema_version': 1, 'statistical': [{'document': 'result.json', 'absolute': 1, **row}]})
    return rules


def test_unused_statistical_row_does_not_hide_its_seed_pointer(tmp_path):
    a = run(tmp_path / 'a', {'status': 'passed', 'generated': 50000})
    b = run(tmp_path / 'b', {'status': 'passed', 'generated': 49000})
    comparison = replay.compare(a, b, statistical(tmp_path, pointer='/absent', seed_pointer='/generated'))
    assert comparison['verdict'] == 'mismatch' and comparison['equal'] is False
    assert [(m['pointer'], m['reason']) for m in comparison['mismatches']] == [
        ('/generated', 'integer count differs (exact)')]
    assert comparison['ignored'] == []
    assert comparison['not_comparable'] == [{'document': 'result.json', 'pointer': '/absent',
                                            'reason': 'not comparable: declared sampled quantity absent from both runs'}]
    # With nothing hidden and nothing different, the unused declaration still cannot yield equal.
    c = run(tmp_path / 'c', {'status': 'passed', 'generated': 50000})
    assert replay.compare(a, c, statistical(tmp_path / 'c', pointer='/absent', seed_pointer='/generated'))['verdict'] == 'not_comparable'


@pytest.mark.parametrize('present', ['original', 'replay'])
def test_sampled_quantity_absent_from_one_run_does_not_install_its_seed(tmp_path, present):
    with_quantity, without = {'value': 1.5, 'generated': 50000}, {'generated': 49000}
    a = run(tmp_path / 'a', with_quantity if present == 'original' else without)
    b = run(tmp_path / 'b', without if present == 'original' else with_quantity)
    comparison = replay.compare(a, b, statistical(tmp_path, pointer='/value', seed_pointer='/generated'))
    assert comparison['verdict'] == 'mismatch'
    assert {m['pointer'] for m in comparison['mismatches']} == {'/value', '/generated'}
    absent = 'the replay' if present == 'original' else 'the original'
    assert {'document': 'result.json', 'pointer': '/value',
            'reason': 'not comparable: declared sampled quantity absent from ' + absent} in comparison['not_comparable']


@pytest.mark.parametrize('left,right', [({'events': 50000}, {'events': 49000}), ([50000], [49000]),
                                        (True, False), (1.5, 2.5)])
def test_seed_pointer_must_name_a_scalar_seed(tmp_path, left, right):
    a = run(tmp_path / 'a', {'sampled': 10.0, 'counts': left})
    b = run(tmp_path / 'b', {'sampled': 10.0, 'counts': right})
    comparison = replay.compare(a, b, statistical(tmp_path, pointer='/sampled', seed_pointer='/counts'))
    assert comparison['verdict'] == 'mismatch'
    assert comparison['mismatches'][0]['pointer'].startswith('/counts')
    assert not any(row['reason'] == 'recorded seed of a sampled quantity' for row in comparison['ignored'])
    assert {'document': 'result.json', 'pointer': '/counts',
            'reason': 'not comparable: seed pointer does not name a recorded integer or string seed'} in comparison['not_comparable']
    assert {'document': 'result.json', 'pointer': '/sampled',
            'reason': 'not comparable: recorded seed is not an integer or string'} in comparison['not_comparable']


@pytest.mark.parametrize('seed_a,seed_b', [(7, 8), ('a1b2', 'c3d4')])
def test_scalar_seeds_of_a_present_quantity_are_still_skipped(tmp_path, seed_a, seed_b):
    a = run(tmp_path / 'a', {'sampled': 10.0, 'seed': seed_a})
    b = run(tmp_path / 'b', {'sampled': 10.5, 'seed': seed_b})
    comparison = replay.compare(a, b, statistical(tmp_path, pointer='/sampled', seed_pointer='/seed'))
    assert comparison['verdict'] == 'equal', comparison
    assert comparison['ignored'] == [{'document': 'result.json', 'pointer': '/seed',
                                      'reason': 'recorded seed of a sampled quantity'}]


def test_figure_suffix_exemption_covers_report_files_and_the_guide_says_so(tmp_path):
    a, b = run(tmp_path / 'a', {'status': 'passed', 'quantity': 1.73}), run(tmp_path / 'b', {'status': 'passed', 'quantity': 1.73})
    for rd, text in ((a, 'synthetic table: 1.73'), (b, 'synthetic table: 99.0')):
        (rd / 'outputs/attempt-1/report.pdf').write_text(text)
    comparison = replay.compare(a, b)
    # The suffix alone decides: the file is listed as unread and the verdict stays equal.
    assert comparison['verdict'] == 'equal'
    assert [row['document'] for row in comparison['not_compared']] == ['report.pdf']
    guide = ' '.join((Path(__file__).resolve().parents[2] / 'docs/guides/replay.md').read_text().split())
    assert 'file that holds a report or a table of numbers is exempt in the same way' in guide
    assert 'Deliver every number that the comparison must cover in a JSON document' in guide
