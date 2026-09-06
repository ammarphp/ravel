from pathlib import Path
import copy
import importlib.util
import pytest

from ravel.physics import native_lhapdf as m


@pytest.fixture
def fixture(tmp_path):
    prefix = tmp_path / 'env with spaces'
    (prefix / 'bin').mkdir(parents=True)
    (prefix / 'lib').mkdir()
    (prefix / 'bin/lhapdf-config').write_text('test config')
    (prefix / 'lib/libLHAPDF.dylib').write_text('test library')
    observations = {
        '--prefix': str(prefix), '--libdir': str(prefix / 'lib'),
        'lipo': 'arm64 x86_64',
        'otool': f'{prefix}/lib/libLHAPDF.dylib:\n\t@rpath/libc++.1.dylib (compatibility version 1.0.0, current version 1.0.0)',
        'sysctl.proc_translated': '0', 'hw.optional.arm64': '0',
    }
    calls = []
    def run(command):
        command = list(map(str, command)); calls.append(command)
        return observations[command[-1] if command[0] == 'sysctl' else command[-1] if command[0].endswith('lhapdf-config') else command[0]]
    env = {'CONDA_PREFIX': str(prefix), 'LDFLAGS': f'-Wl,-dead_strip_dylibs -L"{prefix}/lib"',
           'PATH': 'deliberately unchanged', 'SECRET_NOT_TO_BE_RECORDED': 'TEST-ENV-SENTINEL-8df4'}
    return prefix, env, observations, calls, run


def call(fixture, **kwargs):
    prefix, env, _, _, run = fixture
    return m.linker_environment(prefix, environment=env, system='Darwin', run=run, **kwargs)


def test_preserves_exact_flags_and_unrelated_environment(fixture):
    prefix, env, _, calls, _ = fixture
    before = copy.deepcopy(env)
    result, record = call(fixture, architecture='arm64')
    assert env == before
    assert result == dict(before, LDFLAGS=before['LDFLAGS'] + ' -lc++')
    assert record['added_tokens'] == ['-lc++']
    assert 'TEST-ENV-SENTINEL-8df4' not in str(record)
    assert all(command[0] not in ('make', 'gfortran', 'mg5_aMC') for command in calls)
    assert record['sources'] == [m.pin(prefix / 'bin/lhapdf-config'), m.pin(prefix / 'lib/libLHAPDF.dylib')]


@pytest.mark.parametrize('flags', ['-lc++', '-l c++', '-Wl,-lc++', '-Wl,-l,c++', '"/some path/libc++.1.dylib"'])
def test_existing_runtime_is_not_added_twice(fixture, flags):
    fixture[1]['LDFLAGS'] = flags
    result, record = call(fixture, architecture='arm64')
    assert result == fixture[1] and not record['changed'] and record['added_tokens'] == []


@pytest.mark.parametrize('flags', ['-lstdc++', '-l stdc++', '-Wl,-lstdc++', '-Wl,-l,stdc++', '-stdlib=libstdc++', '/x/libstdc++.6.dylib', '-lc++ -lstdc++'])
def test_conflicting_runtime_rejected(fixture, flags):
    fixture[1]['LDFLAGS'] = flags
    with pytest.raises(ValueError, match='conflicting'):
        call(fixture, architecture='arm64')


def test_compiler_stdlib_option_does_not_substitute_for_fortran_link(fixture):
    fixture[1]['LDFLAGS'] = '-stdlib=libc++'
    result, record = call(fixture, architecture='arm64')
    assert result['LDFLAGS'] == '-stdlib=libc++ -lc++'


def test_undefined_and_empty_ldflags_are_distinct(fixture):
    del fixture[1]['LDFLAGS']
    result, record = call(fixture, architecture='arm64')
    assert 'LDFLAGS' not in result and record['status'] == 'madgraph_default_ldflags_preserved'
    fixture[1]['LDFLAGS'] = ''
    result, record = call(fixture, architecture='arm64')
    assert result['LDFLAGS'] == '-lc++' and record['changed']


def test_non_darwin_scope_does_not_probe_or_mutate(fixture):
    prefix, env, _, calls, run = fixture
    result, record = m.linker_environment(prefix, environment=env, system='Linux', run=run)
    assert result == env and result is not env and calls == []
    assert record['status'] == 'outside_darwin_fix'


@pytest.mark.parametrize('mutation', ['unactivated', 'wrong_prefix', 'outside_libdir', 'missing_arch', 'translated', 'silicon_x86', 'unknown_runtime', 'two_runtimes', 'malformed_flags'])
def test_ambiguous_runtime_and_ownership_hold(fixture, mutation, tmp_path):
    _, env, obs, _, _ = fixture
    arch = 'arm64'
    if mutation == 'unactivated': env.pop('CONDA_PREFIX')
    elif mutation == 'wrong_prefix': obs['--prefix'] = str(tmp_path)
    elif mutation == 'outside_libdir': obs['--libdir'] = str(tmp_path)
    elif mutation == 'missing_arch': obs['lipo'] = 'x86_64'
    elif mutation == 'translated': arch = 'x86_64'; obs['sysctl.proc_translated'] = '1'
    elif mutation == 'silicon_x86': arch = 'x86_64'; obs['hw.optional.arm64'] = '1'
    elif mutation == 'unknown_runtime': obs['otool'] = 'library:\n\tlibSystem.dylib'
    elif mutation == 'two_runtimes': obs['otool'] += '\n\tlibstdc++.6.dylib (compatibility version 1.0.0)'
    else: env['LDFLAGS'] = '-L"unterminated'
    with pytest.raises(ValueError): call(fixture, architecture=arch)


def test_native_intel_uses_same_actual_runtime_rule(fixture):
    result, record = call(fixture, architecture='x86_64')
    assert record['architecture'] == 'x86_64' and result['LDFLAGS'].endswith(' -lc++')


def test_external_config_symlink_rejected(fixture, tmp_path):
    config = fixture[0] / 'bin/lhapdf-config'; config.unlink()
    external = tmp_path / 'external-config'; external.write_text('test')
    config.symlink_to(external)
    with pytest.raises(ValueError, match='config resolves outside'):
        call(fixture, architecture='arm64')


def test_library_runtime_not_guessed_from_arm(fixture):
    fixture[2]['otool'] = 'library:\n\t@rpath/libstdc++.6.dylib (compatibility version 7.0.0)'
    result, record = call(fixture, architecture='arm64')
    assert result['LDFLAGS'].endswith(' -lstdc++') and record['runtime'] == 'stdc++'


FORWARDED = [
    '-Xlinker -l -Xlinker {runtime}',
    '-Xlinker -l{runtime}',
    '-Wl,-l -Wl,{runtime}',
    '-Xlinker -l -Wl,{runtime}',
    '-Wl,-l -Xlinker {runtime}',
    '-Wl,-headerpad_max_install_names,-l -Xlinker {runtime}',
    '-Xlinker -l -Wl,{runtime},-dead_strip_dylibs',
    '-Wl,-l -stdlib=lib{runtime} -Xlinker {runtime}',
    '-Xlinker "/some path/lib{runtime}.1.dylib"',
    '-Wl,"/some path/lib{runtime}.1.dylib"',
    '-Wl,-l{runtime}.1',
]


@pytest.mark.parametrize('template', FORWARDED)
@pytest.mark.parametrize('runtime', ['c++', 'stdc++'])
def test_forwarded_matching_and_conflicting_links(fixture, template, runtime):
    flags = template.format(runtime=runtime)
    fixture[1]['LDFLAGS'] = flags
    before = copy.deepcopy(fixture[1])
    if runtime == 'stdc++':
        with pytest.raises(ValueError, match='conflicting'):
            call(fixture, architecture='arm64')
    else:
        result, record = call(fixture, architecture='arm64')
        assert result == before
        assert not record['changed'] and record['added_tokens'] == []
        assert record['parsed_linker_flags']['explicit_runtimes'] == ['c++']
    assert fixture[1] == before


@pytest.mark.parametrize('flags', [
    '-Xlinker -l -Xlinker c++ -Wl,-l -Xlinker stdc++',
    '-Wl,-l -Xlinker stdc++ -Xlinker -l -Wl,c++',
    '-l c++ -Xlinker -l -Wl,stdc++',
    '-Xlinker -l -Xlinker stdc++ -lc++',
    '-stdlib=libc++ -Wl,-l -Xlinker stdc++',
])
def test_mixed_two_runtime_orders_reject(fixture, flags):
    fixture[1]['LDFLAGS'] = flags
    assert m.existing_runtimes(flags) == {'c++', 'stdc++'}
    with pytest.raises(ValueError, match='conflicting'):
        call(fixture, architecture='arm64')


def test_forwarded_order_and_operand_roles_are_preserved(fixture):
    flags = '-Wl,-rpath -Xlinker "/a path/libstdc++.1.dylib" -Wl,-l -Xlinker c++'
    assert m.runtime_selection(flags) == {
        'linker_arguments': ['-rpath', '/a path/libstdc++.1.dylib', '-l', 'c++'],
        'compiler_runtimes': [], 'explicit_runtimes': ['c++']}
    fixture[1]['LDFLAGS'] = flags
    result, _ = call(fixture, architecture='arm64')
    assert result['LDFLAGS'] == flags


def test_search_path_named_like_runtime_is_not_a_link(fixture):
    flags = '-Wl,-L -Xlinker "/a path/libstdc++.1.dylib"'
    fixture[1]['LDFLAGS'] = flags
    result, record = call(fixture, architecture='arm64')
    assert result['LDFLAGS'] == flags + ' -lc++'
    assert record['parsed_linker_flags']['explicit_runtimes'] == []


@pytest.mark.parametrize('flags', [
    '-Xlinker', '-Xlinker ""', '-Wl,', '-Wl,,', '-Wl,-l,',
    '-Wl,-l', '-Xlinker -l', '-l', '-L', '-l -Xlinker c++',
    '-Wl,-l -Wl,-dead_strip_dylibs', '-Xlinker "-l stdc++"',
    '-Wl,-rpath -Xlinker -lc++', '-Xlinker -Wl,-lc++',
    '@runtime-flags', '-Xlinker @runtime-flags', '-Wl,@runtime-flags',
    '-Wl,-filelist,/tmp/libraries.txt', '-specs=/tmp/specs',
    '-Wl,--library=stdc++', '-Wl,-l,:libstdc++.dylib',
    '-static-libstdc++', '-Wl,-lto_library,/x/libc++.dylib',
])
def test_malformed_or_opaque_syntax_fails_closed(fixture, flags):
    fixture[1]['LDFLAGS'] = flags
    before = copy.deepcopy(fixture[1])
    with pytest.raises(ValueError):
        call(fixture, architecture='arm64')
    assert fixture[1] == before


