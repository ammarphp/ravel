"""Explicit output-policy controls, with no stage launch or ledger upgrade."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import execution as candidate


def policy(path='out/combine_logger.out', role='incidental_log'):
    return {'schema_version': 1, 'allow_empty_directory_members': [{'path': path, 'role': role}]}


def fixture(root):
    (root / 'out').mkdir()
    (root / 'out/result.json').write_text('{"status":"passed","required_values":[1,2,3]}')
    (root / 'out/combine_logger.out').write_bytes(b'')


@pytest.fixture(params=['cold', 'cached'])
def reader(request, tmp_path):
    if request.param == 'cold':
        yield lambda paths, **kw: candidate.snapshot(tmp_path, paths, **kw)
    else:
        session = candidate._validation_session(tmp_path)
        yield lambda paths, **kw: session.snapshot(paths, **kw)
        session.close()


def test_strict_default_is_unchanged(reader, tmp_path):
    fixture(tmp_path)
    with pytest.raises(ValueError, match='empty output'):
        reader(['out'], outputs=True)


def test_exact_incidental_log_retains_zero_hash_and_complete_population(reader, tmp_path):
    fixture(tmp_path)
    result = reader(['out'], outputs=True, output_policy=policy())
    rows = next(iter(result.values()))['files']
    assert [row['name'] for row in rows] == ['combine_logger.out', 'result.json']
    assert rows[0] == {'name': 'combine_logger.out', 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}
    assert rows[1]['sha256'] == hashlib.sha256((tmp_path / 'out/result.json').read_bytes()).hexdigest()


def test_exact_python_marker_is_allowed_and_retained(reader, tmp_path):
    fixture(tmp_path)
    (tmp_path / 'out/combine_logger.out').write_text('nonempty')
    (tmp_path / 'out/__init__.py').write_bytes(b'')
    result = reader(['out'], outputs=True, output_policy=policy('out/__init__.py', 'python_package_marker'))
    assert any(row['name'] == '__init__.py' and row['size'] == 0 for row in next(iter(result.values()))['files'])


@pytest.mark.parametrize('contents', ['', '{', '{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'])
def test_all_invalid_JSON_remains_refused_even_with_incidental_policy(reader, tmp_path, contents):
    fixture(tmp_path)
    (tmp_path / 'out/result.json').write_text(contents)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        reader(['out'], outputs=True, output_policy=policy())


def test_directly_declared_empty_file_still_fails(reader, tmp_path):
    fixture(tmp_path)
    with pytest.raises(ValueError):
        reader(['out/combine_logger.out'], outputs=True, output_policy=policy())


def test_empty_directory_still_fails(reader, tmp_path):
    (tmp_path / 'out').mkdir()
    with pytest.raises(ValueError):
        reader(['out'], outputs=True)


def test_all_zero_directory_still_fails(reader, tmp_path):
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out/combine_logger.out').write_bytes(b'')
    with pytest.raises(ValueError, match='empty output directory'):
        reader(['out'], outputs=True, output_policy=policy())


def test_unlisted_empty_member_still_fails(reader, tmp_path):
    fixture(tmp_path)
    (tmp_path / 'out/unknown.out').write_bytes(b'')
    with pytest.raises(ValueError, match='empty output'):
        reader(['out'], outputs=True, output_policy=policy())


@pytest.mark.parametrize('name', ['critical.root', 'critical.ROOT', 'critical.json', 'required.dat', 'arbitrary.py'])
def test_incidental_role_cannot_allow_empty_scientific_formats(reader, tmp_path, name):
    fixture(tmp_path)
    (tmp_path / 'out/combine_logger.out').write_text('nonempty')
    (tmp_path / 'out' / name).write_bytes(b'')
    with pytest.raises(ValueError):
        reader(['out'], outputs=True, output_policy=policy('out/' + name))


@pytest.mark.parametrize('mutator', [
    lambda p: p.update(schema_version=True),
    lambda p: p.update(schema_version=2),
    lambda p: p.update(unknown=True),
    lambda p: p.update(allow_empty_directory_members='out/combine_logger.out'),
    lambda p: p['allow_empty_directory_members'][0].update(path='../outside.log'),
    lambda p: p['allow_empty_directory_members'][0].update(path='/absolute.log'),
    lambda p: p['allow_empty_directory_members'][0].update(path='out//combine_logger.out'),
    lambda p: p['allow_empty_directory_members'][0].update(path='out/./combine_logger.out'),
    lambda p: p['allow_empty_directory_members'][0].update(path='out\\combine_logger.out'),
    lambda p: p['allow_empty_directory_members'][0].update(path='out/missing.log'),
    lambda p: p['allow_empty_directory_members'][0].update(role='unknown'),
    lambda p: p['allow_empty_directory_members'][0].update(role='python_package_marker'),
    lambda p: p['allow_empty_directory_members'].append(copy.deepcopy(p['allow_empty_directory_members'][0])),
])
def test_invalid_or_unmatched_policy_refuses(reader, tmp_path, mutator):
    fixture(tmp_path)
    declared = policy(); mutator(declared)
    with pytest.raises(ValueError):
        reader(['out'], outputs=True, output_policy=declared)


def test_input_snapshots_remain_unmodified_and_refuse_output_policy(reader, tmp_path):
    fixture(tmp_path)
    result = reader(['out'])
    assert next(iter(result.values()))['files'][0]['size'] == 0
    with pytest.raises(ValueError, match='cannot alter input'):
        reader(['out'], output_policy=policy())


def test_member_and_directory_aliases_still_refuse(reader, tmp_path):
    fixture(tmp_path)
    (tmp_path / 'out/combine_logger.out').unlink()
    (tmp_path / 'outside.log').write_bytes(b'')
    (tmp_path / 'out/combine_logger.out').symlink_to(tmp_path / 'outside.log')
    with pytest.raises(ValueError, match='symlink'):
        reader(['out'], outputs=True, output_policy=policy())


def test_cached_allowance_cannot_leak_into_strict_validation(tmp_path):
    fixture(tmp_path)
    session = candidate._validation_session(tmp_path)
    session.snapshot(['out'], outputs=True, output_policy=policy())
    with pytest.raises(ValueError, match='empty output'):
        session.snapshot(['out'], outputs=True)
    session.close()


def test_incidental_empty_file_is_still_a_mutation_guarded_member(tmp_path):
    fixture(tmp_path)
    session = candidate._validation_session(tmp_path)
    session.snapshot(['out'], outputs=True, output_policy=policy())
    (tmp_path / 'out/combine_logger.out').write_text('changed')
    assert session.finish(), 'Allowed empty members retain original identity and content custody'


def test_cold_and_cached_identical_snapshot_with_policy(tmp_path):
    fixture(tmp_path)
    session = candidate._validation_session(tmp_path)
    cold = candidate.snapshot(tmp_path, ['out'], outputs=True, output_policy=policy())
    cached = session.snapshot(['out'], outputs=True, output_policy=policy())
    assert cold == cached
    assert session.finish() == []
