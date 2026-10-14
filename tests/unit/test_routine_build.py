"""Observed tiny C++ builds and adverse custody controls, not physics tests."""
import base64
import copy
import shutil
from pathlib import Path
import os
import json
import subprocess
import sys

import pytest

from ravel import analysis_sources as sources, cli
from ravel.physics import routine_build as build
from ravel.workflow import execution, physics_review, science
from ravel.workflow.state_io import atomic_json, read_json
from method_decision_fixture import admit_method


def fixture(tmp_path, compiler=None):
    compiler = compiler or shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('actual C++ compiler unavailable; no observed build evidence')
    compiler = Path(compiler).absolute()
    root = tmp_path / 'source'
    (root / 'include/local').mkdir(parents=True)
    (root / 'assets/a').mkdir(parents=True)
    (root / 'assets/b').mkdir(parents=True)
    (root / 'include/local/value.hh').write_text('#define VALUE 42\n')
    (root / 'assets/a/model.dat').write_text('left model')
    (root / 'assets/b/model.dat').write_text('right model')
    (root / 'main.cc').write_text('#include <cstdio>\n#include "local/value.hh"\nint main() { std::printf("previously_unknown:%d\\n", VALUE); return 0; }\n')
    facts = [{'path': p, 'sha256': sources.digest(root / p), 'role': role} for p, role in
             [('main.cc', 'compile'), ('include/local/value.hh', 'header'), ('assets/a/model.dat', 'model'), ('assets/b/model.dat', 'model')]]
    capsule = {'schema_version': 1, 'kind': 'analysis-source-capsule', 'framework': 'cpp',
               'routine': 'PreviouslyUnknown', 'source': {'repository': 'supplied', 'revision': None,
                   'description': 'Tiny compiled source/layout receipt control, no physics'}, 'root': 'source',
               'files': facts, 'layout': {'include_dirs': ['include'], 'asset_dirs': ['assets/a', 'assets/b']},
               'dependencies': [{'name': 'local helper', 'kind': 'source', 'status': 'resolved',
                   'files': ['include/local/value.hh'], 'reason': 'Explicit included helper bytes'},
                   {'name': 'model assets', 'kind': 'asset', 'status': 'resolved',
                    'files': ['assets/a/model.dat', 'assets/b/model.dat'], 'reason': 'Two distinct assets'}],
               'dependency_review': {'complete': True, 'description': 'Bounded test fixture with all supplied inputs'},
               'submodules': []}
    atomic_json(tmp_path / 'capsule.json', capsule)
    config = {'schema_version': 1, 'source_capsule': 'capsule.json',
              'recipe': {'name': 'cpp-executable', 'compile_units': ['main.cc'], 'output': 'probe', 'flags': ['-std=c++17', '-O0']},
              'runtime': {'tools': {'compiler': {'path': str(compiler), 'sha256': sources.digest(compiler)}},
                          'artifacts': [], 'environment': {}},
              'probe': {'executable': '$BUILD_OUTPUT', 'arguments': [], 'expected_exit_code': 0,
                        'stdout_contains': ['previously_unknown:42']}}
    atomic_json(tmp_path / 'build.json', config)
    return {'backend': 'routine-build', 'input': 'build.json'}, config, capsule


def test_planning_is_read_only_even_with_executable_runtime(tmp_path, monkeypatch):
    task, _, _ = fixture(tmp_path)
    monkeypatch.setattr(build.subprocess, 'run', lambda *a, **k: pytest.fail('planning executed code'))
    plan = build.build_plan(task, tmp_path, tmp_path / 'output')
    assert len(build.inputs(task, tmp_path)) == 7
    assert plan['base_dir'] == str(tmp_path.resolve())
    assert plan['compute_authorized'] is False and plan['physics_validated'] is False
    assert not (tmp_path / 'output').exists()


def test_actual_compiler_probe_receipt_rebinds_complete_source_layout(tmp_path):
    task, _, _ = fixture(tmp_path)
    out = tmp_path / 'output'
    receipt = build.run(task, tmp_path, out)
    plan = read_json(out / 'build-plan.json')
    assert receipt['observed']['build_exit_code'] == receipt['observed']['probe_exit_code'] == 0
    assert receipt['physics_validated'] is False
    assert 'clang' in receipt['observed']['compiler_version'].lower() or 'gcc' in receipt['observed']['compiler_version'].lower() or 'g++' in receipt['observed']['compiler_version'].lower()
    assert (out / 'work/source/assets/a/model.dat').read_text() == 'left model'
    assert (out / 'work/source/assets/b/model.dat').read_text() == 'right model'
    assert build.verify_receipt(receipt, plan, tmp_path, out)['status'] == 'passed'
    assert receipt['schema_version'] == 2
    staged = read_json(out / 'staged-source.json')
    assert staged['before'] == staged['after']
    assert staged['before']['files'][0]['path'] == 'main.cc'


@pytest.mark.parametrize('defect', ['binary', 'staged_source', 'original_source', 'log', 'stdout_digest', 'command'])
def test_observed_receipt_rejects_changed_evidence(tmp_path, defect):
    task, _, _ = fixture(tmp_path); out = tmp_path / 'output'
    receipt = build.run(task, tmp_path, out); plan = read_json(out / 'build-plan.json')
    if defect == 'binary':
        (out / receipt['binary']['path']).write_bytes(b'tampered executable')
    elif defect == 'staged_source':
        (out / 'work/source/assets/a/model.dat').write_text('tampered model')
    elif defect == 'original_source':
        (tmp_path / 'source/include/local/value.hh').write_text('#define VALUE 43\n')
    elif defect == 'log':
        (out / 'probe.log').write_text('missing process observation')
    elif defect == 'stdout_digest':
        receipt['observed']['probe_stdout_sha256'] = '0' * 64
    elif defect == 'command':
        receipt['commands'][0][0] = '/wrong/compiler'
    with pytest.raises(ValueError):
        build.verify_receipt(receipt, plan, tmp_path, out)


def test_rehashed_but_wrong_probe_observation_does_not_pass(tmp_path):
    task, _, _ = fixture(tmp_path); out = tmp_path / 'output'
    receipt = build.run(task, tmp_path, out); plan = read_json(out / 'build-plan.json')
    log = read_json(out / 'probe.log'); log['stdout_base64'] = base64.b64encode(b'wrong routine').decode()
    atomic_json(out / 'probe.log', log)
    receipt['logs']['probe.log']['sha256'] = sources.digest(out / 'probe.log')
    with pytest.raises(ValueError, match='probe observation'):
        build.verify_receipt(receipt, plan, tmp_path, out)


def test_failed_actual_compile_has_log_and_preserves_prior_output(tmp_path):
    task, _, capsule = fixture(tmp_path)
    p = tmp_path / 'source/main.cc'; p.write_text('#include "missing_dependency.hh"\n')
    capsule['files'][0]['sha256'] = sources.digest(p); atomic_json(tmp_path / 'capsule.json', capsule)
    previous = tmp_path / 'prior-working-binary'; previous.write_bytes(b'old output preserved')
    with pytest.raises(ValueError, match='build/probe failed'):
        build.run(task, tmp_path, tmp_path / 'output')
    assert previous.read_bytes() == b'old output preserved'
    assert read_json(tmp_path / 'output/build-0.log')['returncode'] != 0
    assert not (tmp_path / 'output/build-receipt.json').exists()


def test_unresolved_or_unbound_onnx_refuses_before_compiler(tmp_path, monkeypatch):
    task, _, capsule = fixture(tmp_path)
    monkeypatch.setattr(build.subprocess, 'run', lambda *a, **k: pytest.fail('compiler ran despite unresolved dependency'))
    capsule['dependency_review']['complete'] = False
    capsule['dependencies'][1]['status'] = 'unresolved'
    atomic_json(tmp_path / 'capsule.json', capsule)
    with pytest.raises(ValueError, match='transitive dependency'):
        build.inputs(task, tmp_path)
    capsule['dependency_review']['complete'] = True; capsule['dependencies'][1]['status'] = 'resolved'
    p = tmp_path / 'source/main.cc'; p.write_text('auto p = getONNX(name(), "res.odd");\n')
    capsule['files'][0]['sha256'] = sources.digest(p)
    capsule['files'] = [f for f in capsule['files'] if f['role'] != 'model']
    capsule['layout']['asset_dirs'] = []; capsule['dependencies'] = capsule['dependencies'][:1]
    atomic_json(tmp_path / 'capsule.json', capsule)
    with pytest.raises(ValueError, match='ONNX helper'):
        build.inputs(task, tmp_path)


@pytest.mark.parametrize('flag', ['@response.txt', '-fplugin=malicious.so', '-Wl,-rpath,/unbound', '-include/unknown.hh'])
def test_unbound_recipe_flags_refused_before_execution(tmp_path, flag):
    task, config, _ = fixture(tmp_path); config['recipe']['flags'].append(flag)
    atomic_json(tmp_path / 'build.json', config)
    with pytest.raises(ValueError, match='unsupported compiler flag'):
        build.inputs(task, tmp_path)


def test_simpleanalysis_does_not_claim_portable_build_from_handport_environment(tmp_path):
    task, config, capsule = fixture(tmp_path)
    config['recipe']['name'] = 'simpleanalysis-analysisbase'; config['recipe']['flags'] = []
    capsule['framework'] = 'simpleanalysis'
    atomic_json(tmp_path / 'build.json', config); atomic_json(tmp_path / 'capsule.json', capsule)
    with pytest.raises(ValueError, match='AnalysisBase'):
        build.inputs(task, tmp_path)


def test_alias_spelling_and_link_chain_are_bound_even_with_identical_target_bytes(tmp_path):
    driver = tmp_path / 'clang-19'; driver.write_text('compiler bytes'); driver.chmod(0o755)
    alias = tmp_path / 'clang++'; alias.symlink_to('clang-19')
    first = build.executable_identity(alias)
    second = tmp_path / 'same-bytes'; second.write_bytes(driver.read_bytes()); second.chmod(0o755)
    alias.unlink(); alias.symlink_to('same-bytes')
    changed = build.executable_identity(alias)
    assert first['sha256'] == changed['sha256']
    assert first != changed
    assert first['path'] == str(alias) and first['links'] == [{'path': str(alias), 'target': 'clang-19'}]


def test_prospective_sealed_config_rejects_alias_retargeting_before_build_even_with_same_bytes(tmp_path, monkeypatch):
    task, config, _ = fixture(tmp_path)
    target = Path(config['runtime']['tools']['compiler']['path'])
    alias = tmp_path / target.name; alias.symlink_to(target)
    config['runtime']['tools']['compiler']['path'] = str(alias)
    atomic_json(tmp_path / 'build.json', config)
    sealed = build.seal_configuration(task, tmp_path)
    atomic_json(tmp_path / 'build.json', sealed)
    monkeypatch.setattr(build.subprocess, 'run', lambda *a, **k: pytest.fail('prospective alias check launched a process'))
    assert build.build_plan(task, tmp_path, tmp_path / 'out')['custody']['prospectively_sealed'] is True
    # Different symlink bytes resolve to the exact same executable target/hash.
    alias.unlink(); alias.symlink_to(os.path.relpath(target, alias.parent))
    assert sources.digest(alias) == sealed['runtime']['tools']['compiler']['sha256']
    with pytest.raises(ValueError, match='prospectively sealed'):
        build.inputs(task, tmp_path)


def test_rivet_effective_compiler_selection_binds_configured_alias_and_rejects_other_driver(tmp_path):
    task, config, _ = fixture(tmp_path)
    compiler = Path(config['runtime']['tools']['compiler']['path'])
    alias = tmp_path / 'configured-clang++'; alias.symlink_to(compiler)
    builder = tmp_path / 'rivet-build'
    builder.write_text('''rivetcxx=$(which $(echo "configured-clang++" | awk '{print $1}') 2> /dev/null)
if [[ -x "$rivetcxx" ]]; then
mycxx="configured-clang++ -std=c++17"
elif [[ -x "$abscxx" ]]; then
mycxx="$CXX"
fi
''')
    selection = build._rivet_compiler(builder, compiler, {'PATH': str(tmp_path)})
    assert selection['selection'] == 'configured'
    assert selection['executable']['links'][0]['target'] == str(compiler)
    other = tmp_path / 'other-driver'; other.write_text('wrong driver'); other.chmod(0o755)
    alias.unlink(); alias.symlink_to(other)
    with pytest.raises(ValueError, match='different compiler'):
        build._rivet_compiler(builder, compiler, {'PATH': str(tmp_path)})


def test_real_compiler_alias_observer_executes_target_and_records_actual_source_argv(tmp_path):
    task, config, _ = fixture(tmp_path)
    out = tmp_path / 'out'; (out / 'work/source').mkdir(parents=True); (out / 'work/build').mkdir()
    selected = Path(config['runtime']['tools']['compiler']['path'])
    alias = tmp_path / selected.name; alias.symlink_to(selected)
    source = out / 'work/source/main.cc'; source.write_text('int main(){return 0;}')
    observer_dir = out / 'work/compiler-observer'; observer_dir.mkdir()
    observer = observer_dir / alias.name
    observer.write_text('#!' + sys.executable + '\n' + build.COMPILER_OBSERVER); observer.chmod(0o755)
    env = dict(os.environ, RAVEL_COMPILER_TARGET=str(alias), RAVEL_COMPILER_JOURNAL=str(out / 'compiler-invocations.jsonl'))
    completed = subprocess.run([str(observer), str(source), '-o', str(out / 'work/build/probe')],
                               cwd=out / 'work/build', env=env, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode()
    plan = {'custody': {'compiler_selection': {'executable': build.executable_identity(alias)}},
            'recipe': {'compile_units': ['main.cc']},
            'source_inventory': {'files': [{'path': 'main.cc', 'sha256': sources.digest(source)}]}}
    facts = build.verify_compiler_invocations(out / 'compiler-invocations.jsonl', plan, out)
    assert facts[0]['argv'][0] == str(alias) and str(source) in facts[0]['argv']
    source.write_text('changed after compiler')
    facts[0]['target'] = '/wrong/compiler'
    (out / 'compiler-invocations.jsonl').write_text(__import__('json').dumps(facts[0]) + '\n')
    with pytest.raises(ValueError, match='bound effective compiler'):
        build.verify_compiler_invocations(out / 'compiler-invocations.jsonl', plan, out)


def compiler_concatenation_fixture(tmp_path):
    out = tmp_path / 'out'
    source_dir = out / 'work/source'; source_dir.mkdir(parents=True)
    (out / 'work/build').mkdir()
    first = source_dir / 'one.cc'; first.write_bytes(b'int helper(){return 42;}')
    second = source_dir / 'two.cc'; second.write_bytes(b'int main(){return helper()-42;}\n')
    _, config, _ = fixture(tmp_path)
    selected = Path(config['runtime']['tools']['compiler']['path'])
    alias = tmp_path / selected.name; alias.symlink_to(selected)
    generated = out / 'work/build/tmp.abcdefgh.cc'
    raw = b''.join(b'\n#line 1 "' + os.fsencode(p) + b'"\n' + p.read_bytes() for p in (first, second))
    selection = {'executable': build.executable_identity(alias), 'selection': 'configured',
                 'configured_command': alias.name + ' -std=c++17'}
    plan = {'custody': {'compiler_selection': selection},
            'recipe': {'compile_units': ['one.cc', 'two.cc']},
            'source_inventory': {'files': [{'path': p.name, 'sha256': sources.digest(p)} for p in (first, second)]}}
    fact = {'schema_version': 2, 'pid': 123, 'timestamp_ns': 456,
            'cwd': str(generated.parent), 'argv': [str(alias), '-std=c++17', '-c', generated.name],
            'invoked_alias': str(out / 'work/compiler-observer' / alias.name),
            'target': selection['executable']['resolved_path'], 'sha256': selection['executable']['sha256'],
            'compile_inputs': [{'path': str(generated), 'sha256': __import__('hashlib').sha256(raw).hexdigest(),
                                'content_base64': base64.b64encode(raw).decode()}]}
    return out, plan, generated, raw, fact, alias


def test_real_compiler_observer_retains_transient_rivet_concatenation_and_linker_probe(tmp_path):
    out, plan, generated, raw, _, alias = compiler_concatenation_fixture(tmp_path)
    observer_dir = out / 'work/compiler-observer'; observer_dir.mkdir()
    observer = observer_dir / alias.name
    observer.write_text('#!' + sys.executable + '\n' + build.COMPILER_OBSERVER); observer.chmod(0o755)
    journal = out / 'compiler-invocations.jsonl'
    env = dict(os.environ, RAVEL_COMPILER_TARGET=str(alias), RAVEL_COMPILER_JOURNAL=str(journal))
    probe_name = '713' + str(os.getpid())
    probe = Path('/tmp').resolve() / (probe_name + '.cc')
    probe_binary = probe.with_suffix('')
    assert not probe.exists() and not probe_binary.exists()
    probe.write_bytes(b'int main() { return 0; }\n')
    try:
        # The upstream feature test may fail on Darwin, which is intentional.
        subprocess.run([str(observer), '-std=c++17', '-Wl,--no-as-needed', probe.name, '-o', probe_name],
                       cwd=probe.parent, env=env, capture_output=True)
        generated.write_bytes(raw)
        completed = subprocess.run([str(observer), '-std=c++17', generated.name, '-o', 'probe'],
                                   cwd=generated.parent, env=env, capture_output=True)
        assert completed.returncode == 0, completed.stderr.decode()
        assert subprocess.run([str(generated.parent / 'probe')]).returncode == 0
        generated.unlink()  # Normal upstream cleanup does not lose the bytes.
        facts = build.verify_compiler_invocations(journal, plan, out)
        assert len(facts) == 2
        assert base64.b64decode(facts[1]['compile_inputs'][0]['content_base64']) == raw
        assert [str(out / 'work/source' / p) for p in plan['recipe']['compile_units']] != facts[1]['argv'][1:]
    finally:
        probe.unlink(missing_ok=True); probe_binary.unlink(missing_ok=True)


@pytest.mark.parametrize('defect', ['changed_body', 'omitted_unit', 'duplicate_unit', 'reordered_units',
                                  'relabel_marker', 'unbound_filename', 'outside_build', 'missing_bytes', 'wrong_digest'])
def test_generated_compiler_source_requires_exact_staged_unit_bytes_and_order(tmp_path, defect):
    out, plan, generated, raw, fact, _ = compiler_concatenation_fixture(tmp_path)
    content = fact['compile_inputs'][0]
    if defect == 'changed_body': raw = raw.replace(b'return 42', b'return 41')
    elif defect == 'omitted_unit': raw = raw.split(b'\n#line 1 ')[1]; raw = b'\n#line 1 ' + raw
    elif defect == 'duplicate_unit': raw += raw
    elif defect == 'reordered_units':
        parts = raw.split(b'\n#line 1 ')[1:]; raw = b''.join(b'\n#line 1 ' + p for p in reversed(parts))
    elif defect == 'relabel_marker': raw = raw.replace(b'one.cc"', b'other.cc"')
    elif defect == 'unbound_filename':
        content['path'] = str(generated.with_name('unbound.cc')); fact['argv'][-1] = 'unbound.cc'
    elif defect == 'outside_build': fact['cwd'] = str(tmp_path)
    elif defect == 'missing_bytes': content.pop('content_base64')
    if defect != 'missing_bytes':
        content['content_base64'] = base64.b64encode(raw).decode()
        content['sha256'] = '0' * 64 if defect == 'wrong_digest' else __import__('hashlib').sha256(raw).hexdigest()
    journal = out / 'compiler-invocations.jsonl'; journal.write_text(__import__('json').dumps(fact) + '\n')
    with pytest.raises(ValueError): build.verify_compiler_invocations(journal, plan, out)


@pytest.mark.parametrize('defect', [None, 'other_program', 'other_arguments', 'other_directory'])
def test_outside_work_compiler_source_only_admits_exact_upstream_linker_probe(tmp_path, defect):
    out, plan, generated, raw, fact, alias = compiler_concatenation_fixture(tmp_path)
    probe = dict(fact, cwd=str(Path('/tmp').resolve()),
                 argv=[str(alias), '-std=c++17', '-Wl,--no-as-needed', '123.cc', '-o', '123'])
    probe_raw = b'int main() { return 0; }\n' if defect != 'other_program' else b'int unbound(){return 1;}\n'
    probe['compile_inputs'] = [{'path': str(Path(probe['cwd']) / '123.cc'),
                               'sha256': __import__('hashlib').sha256(probe_raw).hexdigest(),
                               'content_base64': base64.b64encode(probe_raw).decode()}]
    if defect == 'other_arguments': probe['argv'][2] = '-shared'
    elif defect == 'other_directory': probe['cwd'] = str(tmp_path)
    journal = out / 'compiler-invocations.jsonl'
    journal.write_text('\n'.join(__import__('json').dumps(x) for x in [probe, fact]) + '\n')
    if defect:
        with pytest.raises(ValueError): build.verify_compiler_invocations(journal, plan, out)
    else:
        assert len(build.verify_compiler_invocations(journal, plan, out)) == 2


def loaded_observation(tmp_path):
    binary = tmp_path / 'RivetUnknown.so'; binary.write_bytes(b'plugin identity fixture')
    identity = {'path': str(binary), 'sha256': sources.digest(binary)}
    env = {'RIVET_ANALYSIS_PLUGINS': str(binary)}
    observation = {'schema_version': 1, 'kind': 'rivet-loader-observation', 'pid': 123, 'cwd': str(tmp_path),
        'environment': env, 'python': {'path': sys.executable, 'sha256': sources.digest(sys.executable)},
        'plugin_before': identity, 'plugin_after': identity, 'images_before': [], 'images_after_import': [],
        'images_after_load': [str(binary)], 'selected_plugins': [str(binary)], 'registered_names': ['Unknown'],
        'canonical_routine': 'Unknown', 'runtime_version': '4.1.3', 'physics_validated': False}
    trace = ("Trying to load plugin analyses from file " + str(binary) + "\nRegistering a plugin analysis called 'Unknown'\n").encode()
    return binary, observation, env, trace


@pytest.mark.parametrize('defect', ['metadata_only', 'attempt_only', 'duplicate', 'preloaded', 'wrong_same_name', 'hash', 'environment'])
def test_loader_custody_refuses_metadata_or_candidate_only_and_competing_same_name(tmp_path, defect):
    binary, observation, env, trace = loaded_observation(tmp_path)
    if defect == 'metadata_only': trace = b'Unknown'
    elif defect == 'attempt_only': trace = ('Trying to load plugin analyses from file ' + str(binary) + '\nUnknown').encode()
    elif defect == 'duplicate': trace += b"Ignoring duplicate plugin analysis called 'Unknown'\n"
    elif defect == 'preloaded': observation['images_after_import'] = [str(binary)]
    elif defect == 'wrong_same_name': observation['images_after_load'] = [str(tmp_path / 'RivetOther.so')]
    elif defect == 'hash': observation['plugin_after'] = dict(observation['plugin_after'], sha256='0' * 64)
    else: observation['environment'] = dict(env, RIVET_ANALYSIS_PATH='/ambient')
    with pytest.raises(ValueError):
        build.verify_loader_observation(observation, binary, 'Unknown', env, tmp_path, trace, '')


def test_loader_custody_accepts_exact_mapped_image_and_successful_canonical_registration(tmp_path):
    binary, observation, env, trace = loaded_observation(tmp_path)
    assert build.verify_loader_observation(observation, binary, 'Unknown', env, tmp_path, trace, '')['status'] == 'passed'


def test_multi_routine_receipt_requires_each_source_bound_canonical_registration(tmp_path):
    binary,observation,env,trace=loaded_observation(tmp_path)
    observation['registered_names'].append('Secondary')
    with pytest.raises(ValueError, match='registration trace'):
        build.verify_loader_observation(observation,binary,'Unknown',env,tmp_path,trace,'',registered_routines=['Unknown','Secondary'])
    trace += b"Registering a plugin analysis called 'Secondary'\n"
    assert build.verify_loader_observation(observation,binary,'Unknown',env,tmp_path,trace,'',registered_routines=['Unknown','Secondary'])['status']=='passed'


@pytest.mark.parametrize('defect', [None, 'name_only', 'uncompiled_source', 'no_registration', 'legacy'])
def test_secondary_entry_requires_bound_compiled_source_and_actual_registration(tmp_path, defect):
    source_fact={'path':'Secondary.cc','sha256':'1'*64,'role':'compile'}
    supporting={'path':'Secondary.info','sha256':'2'*64,'role':'configuration'}
    binding={'registration':'literal-RIVET_DECLARE_PLUGIN','source_files':[source_fact],'supporting_files':[supporting]}
    plan={'schema_version':2,'routine':'Primary','routine_bindings':{'Secondary':binding},
          'recipe':{'compile_units':['Primary.cc','Secondary.cc']}}
    receipt={'schema_version':2,'custody':{'loader':{'path':'loader-observation.json'}}}
    atomic_json(tmp_path/'loader-observation.json',{'registered_names':['Primary','Secondary']})
    if defect=='name_only': plan['routine_bindings']={}
    elif defect=='uncompiled_source': plan['recipe']['compile_units']=['Primary.cc']
    elif defect=='no_registration': atomic_json(tmp_path/'loader-observation.json',{'registered_names':['Primary']})
    elif defect=='legacy': plan['schema_version']=receipt['schema_version']=1
    if defect:
        with pytest.raises(ValueError): build.bound_routine(receipt,plan,tmp_path,'Secondary')
    else:
        assert build.bound_routine(receipt,plan,tmp_path,'Secondary')==binding


@pytest.mark.parametrize('wrong_plugin', [False, True])
def test_fresh_process_observer_measures_real_native_image_not_same_name_metadata(tmp_path, wrong_plugin):
    """A real tiny library + stub Rivet API exercises OS loading, not physics."""
    _, config, _ = fixture(tmp_path)
    source = tmp_path / 'library.cc'; source.write_text('extern "C" int fixture_value(){return 42;}')
    plugin = tmp_path / 'RivetUnknown.so'
    command = [config['runtime']['tools']['compiler']['path'], '-shared', '-fPIC', str(source), '-o', str(plugin)]
    result = subprocess.run(command, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    other = tmp_path / 'RivetSameName.so'; shutil.copyfile(plugin, other)
    (tmp_path / 'rivet.py').write_text('''import ctypes,os
_plugins=[]
_library=None
def setLogLevel(*args): pass
def setAnalysisPlugins(paths):
    global _plugins
    _plugins=paths
def analysisPlugins(): return _plugins
def version(): return '4.1.3'
class Analysis:
    def name(self): return 'Unknown'
class AnalysisLoader:
    @staticmethod
    def analysisNames():
        global _library
        actual=os.environ.get('STUB_WRONG_PLUGIN') or _plugins[0]
        print('Trying to load plugin analyses from file '+actual)
        _library=ctypes.CDLL(actual)
        assert _library.fixture_value()==42
        print("Registering a plugin analysis called 'Unknown'")
        return ['Unknown']
    @staticmethod
    def getAnalysis(name): return Analysis()
''')
    env = build.isolated_process_environment(tmp_path / 'home', tmp_path / 'tmp')
    env.update(PYTHONPATH=str(tmp_path), PYTHONDONTWRITEBYTECODE='1')
    if wrong_plugin: env['STUB_WRONG_PLUGIN'] = str(other)
    observation = tmp_path / 'image-observation.json'
    command = build.rivet_loader_command(sys.executable, plugin, 'Unknown', observation)
    if wrong_plugin:
        with pytest.raises(ValueError, match='build/probe failed'):
            build._process(command, tmp_path, env, tmp_path / 'observer.log')
        assert not observation.exists()
        assert b'actual loaded analysis plugin differs' in base64.b64decode(read_json(tmp_path / 'observer.log')['stderr_base64'])
    else:
        _, stdout = build._process(command, tmp_path, env, tmp_path / 'observer.log')
        value = read_json(observation)
        assert str(plugin) in value['images_after_load']
        assert build.verify_loader_observation(value, plugin, 'Unknown', env, tmp_path,
            stdout, read_json(tmp_path / 'observer.log')['stderr_base64'])['status'] == 'passed'


def test_locale_less_native_python_launch_retains_exact_environment(tmp_path):
    # Mirrors the closed native launch, rather than inheriting pytest's locale.
    env = build.isolated_process_environment(tmp_path / 'home', tmp_path / 'tmp')
    assert env['LC_ALL'] == env['LC_CTYPE'] == 'C'
    assert env['PYTHONCOERCECLOCALE'] == '0' and env['PYTHONUTF8'] == '1'
    result = subprocess.run([sys.executable, '-c',
        'import json,os,sys; print(json.dumps({"environment":dict(os.environ),"utf8":sys.flags.utf8_mode}))'],
        cwd=tmp_path, env=env, capture_output=True, check=True)
    observed = json.loads(result.stdout)
    assert observed['environment'] == env
    assert observed['utf8'] == 1


def test_rehashed_staged_observation_cannot_relabel_actual_compiler_input(tmp_path):
    task, _, _ = fixture(tmp_path); out = tmp_path / 'output'
    receipt = build.run(task, tmp_path, out); plan = read_json(out / 'build-plan.json')
    staged = read_json(out / 'staged-source.json'); staged['before']['files'][0]['path'] = 'different/main.cc'
    atomic_json(out / 'staged-source.json', staged)
    receipt['custody']['staged_source']['sha256'] = sources.digest(out / 'staged-source.json')
    with pytest.raises(ValueError, match='staged compilation'):
        build.verify_receipt(receipt, plan, tmp_path, out)


def test_legacy_receipt_retains_qualified_integrity_without_acquiring_new_observations(tmp_path):
    task, _, _ = fixture(tmp_path); out = tmp_path / 'output'
    receipt = build.run(task, tmp_path, out)
    plan = build.build_plan(task, tmp_path, out, _legacy=True); atomic_json(out / 'build-plan.json', plan)
    receipt.update(schema_version=1, runtime_identity=plan['runtime_identity'], build_plan_sha256=sources.digest(out / 'build-plan.json'))
    receipt.pop('custody')
    for name, fact in receipt['logs'].items():
        log = read_json(out / name)
        for key in ('cwd', 'environment', 'started_at', 'finished_at'): log.pop(key)
        log['schema_version'] = 1; atomic_json(out / name, log); fact['sha256'] = sources.digest(out / name)
    assert build.verify_receipt(receipt, plan, tmp_path, out)['custody'] == 'legacy-declared-evidence-only'


# Real public lifecycle with a tiny OS-loaded plugin and explicit API stand-in.
# Synthetic review votes here are test controls, not external actor reviews.
def lifecycle_fixture(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        pytest.skip('real C++ compiler required')
    compiler = Path(compiler).absolute()
    root = tmp_path / 'source'; root.mkdir()
    source = root / 'control.cc'
    source.write_text('#define RIVET_DECLARE_PLUGIN(...)\nRIVET_DECLARE_PLUGIN(Control)\n'
                      'extern "C" int fixture_value(){return 42;}\n')
    tools = tmp_path / 'tools'; tools.mkdir()
    alias = tools / compiler.name; alias.symlink_to(compiler)
    builder = tools / 'rivet-build'
    builder.write_text('#!/bin/bash\n'
        'rivetcxx=$(which $(echo "' + alias.name + '" | awk \'{print $1}\') 2> /dev/null)\n'
        'if [[ -x "$rivetcxx" ]]; then\nmycxx="' + alias.name + ' -std=c++17"\n'
        'elif [[ -x "$abscxx" ]]; then\nmycxx="$CXX"\nfi\n'
        'output="$3"\nshift 3\n$mycxx -shared -fPIC "$@" -o "$output"\n')
    builder.chmod(0o755)
    probe = tools / 'metadata.py'; probe.write_text('print("Control")\n'); probe.chmod(0o755)
    stub = tools / 'rivet.py'
    stub.write_text('''import ctypes
_plugins=[]
_library=None
def setLogLevel(*args): pass
def setAnalysisPlugins(paths):
    global _plugins
    _plugins=paths
def analysisPlugins(): return _plugins
def version(): return 'explicit-api-stand-in'
class Analysis:
    def name(self): return 'Control'
class AnalysisLoader:
    @staticmethod
    def analysisNames():
        global _library
        print('Trying to load plugin analyses from file '+_plugins[0])
        _library=ctypes.CDLL(_plugins[0])
        assert _library.fixture_value()==42
        print("Registering a plugin analysis called 'Control'")
        return ['Control']
    @staticmethod
    def getAnalysis(name): return Analysis()
''')
    capsule = {'schema_version': 1, 'kind': 'analysis-source-capsule', 'framework': 'rivet',
        'routine': 'Control', 'source': {'repository': 'supplied', 'revision': None,
            'description': 'Real tiny OS-loaded library; explicit Rivet API stand-in, no physics'},
        'root': 'source', 'files': [{'path': 'control.cc', 'sha256': sources.digest(source), 'role': 'compile'}],
        'layout': {'include_dirs': [], 'asset_dirs': []}, 'dependencies': [],
        'dependency_review': {'complete': True, 'description': 'Explicit fixture runtime and one tiny unit'},
        'submodules': []}
    atomic_json(tmp_path / 'capsule.json', capsule)
    config = {'schema_version': 1, 'source_capsule': 'capsule.json',
        'recipe': {'name': 'rivet-plugin', 'compile_units': ['control.cc'],
                   'output': 'RivetControl.so', 'flags': []},
        'runtime': {'tools': {k: {'path': str(p), 'sha256': sources.digest(p)} for k, p in
            [('compiler', alias), ('build', builder), ('probe', probe), ('python', Path(sys.executable))]},
            'artifacts': [{'path': str(stub), 'sha256': sources.digest(stub)}],
            'environment': {'PATH': str(tools)+':/usr/bin:/bin', 'PYTHONPATH': str(tools)}},
        'probe': {'executable': 'probe', 'arguments': [], 'expected_exit_code': 0,
                  'stdout_contains': ['Control']}}
    atomic_json(tmp_path / 'build.json', config)
    task = {'backend': 'routine-build', 'input': 'build.json'}
    atomic_json(tmp_path / 'build.json', build.seal_configuration(task, tmp_path))
    policy = {'schema_version': 1, 'policy': {'schema_version': 1,
        'actors': {'proposer': 'synthetic-producer', 'executor': 'synthetic-executor',
            'physics_critic': 'synthetic-critic', 'skeptical_verifier': 'synthetic-skeptic',
            'physics_decider': 'synthetic-decider'}, 'max_redos': 0,
        'allowed_changed_paths': [], 'allowed_stages': ['science'],
        'required_checks': [{'id': 'integrity', 'kind': 'integrity'}],
        'claim_scopes': {'engineering': {'checks': ['integrity'], 'actions': ['delivery', 'reuse']}}},
        'correction_contract': {'task_fields': [], 'input_slots': []}}
    spec = {'schema_version': 2, 'mode': 'analyze', 'source': 'Synthetic public lifecycle control',
        'assumptions': ['Actual compiler/OS loading; API and review actors explicitly synthetic'],
        'max_seconds': 45, 'max_attempts': 1, 'approval_mode': 'scripted_yes',
        'task': task, 'review_policy': policy}
    atomic_json(tmp_path / 'spec.json', spec)
    return tmp_path / 'run', tmp_path / 'spec.json'


def test_public_plan_approve_run_source_build_custody_review_and_reuse(tmp_path):
    rd, spec = lifecycle_fixture(tmp_path)
    assert cli.main(['plan', '--rundir', str(rd), '--spec', str(spec)]) == 0
    with pytest.raises((OSError, ValueError)):
        science.run(rd)
    quote = 'Actual authorization for this synthetic tiny compiler lifecycle control'
    # A full launch is refused until the run records its method decision.
    assert cli.main(['approve', '--rundir', str(rd), '--scripted', '--quote', quote]) == 2
    assert not (rd / science.APPROVAL).exists()
    admit_method(rd)
    assert cli.main(['approve', '--rundir', str(rd), '--scripted', '--quote', quote]) == 0
    assert cli.main(['run', '--rundir', str(rd)]) == 0
    record = execution.load_execution(rd)['stages']['science']
    assert record['status'] == 'succeeded' and record['exit_code'] == 0
    actual_record = read_json(execution.resolve_path(rd, record['attempt_record']))
    assert not subprocess.run(['ps', '-p', str(actual_record['child_pid']), '-o', 'pid='],
                              capture_output=True, text=True).stdout.strip()
    out = rd / 'outputs/attempt-1'
    receipt, plan = read_json(out / 'build-receipt.json'), read_json(out / 'build-plan.json')
    assert build.verify_receipt(receipt, plan, tmp_path, out)['status'] == 'passed'
    log, observation = read_json(out / 'probe.log'), read_json(out / 'loader-observation.json')
    assert observation['environment'] == log['environment']
    assert observation['environment']['LC_ALL'] == observation['environment']['LC_CTYPE'] == 'C'
    assert observation['environment']['PYTHONCOERCECLOCALE'] == '0'
    assert receipt['physics_validated'] is False
    assert b"Registering a plugin analysis called 'Control'" in base64.b64decode(log['stdout_base64'])
    assert science.packet(rd)['lifecycle_verdict'] == 'PENDING'
    with pytest.raises(ValueError):
        science.run(rd, resume=True)
    checks = rd / 'logs/control-checks.json'
    atomic_json(checks, {'schema_version': 1, 'checks': [{'id': 'integrity', 'status': 'pass',
        'attempt_ids': [record['attempt_id']], 'evidence': [{'path': str(out / 'build-receipt.json'),
            'location': '/custody; explicit synthetic control, no scientific review claim'}]}]})
    physics_review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
        stage_receipts=[record['attempt_record']], check_results=str(checks))
    for role, actor in [('physics_critic', 'synthetic-critic'),
                         ('skeptical_verifier', 'synthetic-skeptic'),
                         ('physics_decider', 'synthetic-decider')]:
        physics_review.submit_review(rd, role=role, actor_id=actor, verdict='accept',
            summary='Synthetic test vote, not a real scientific review', claim_scope='engineering')
    assert science.packet(rd)['lifecycle_verdict'] == 'PASS'
    assert cli.main(['run', '--rundir', str(rd), '--resume']) == 0
    assert execution.load_execution(rd)['stages']['science']['attempt_id'] == record['attempt_id']
    # Successful reuse must still refuse changed retained process evidence.
    observation['environment']['UNDECLARED_NATIVE_FLAG'] = '1'
    atomic_json(out / 'loader-observation.json', observation)
    with pytest.raises(ValueError):
        science.run(rd, resume=True)

@pytest.mark.parametrize('defect',[None,'missing','duplicate','wrong','collision','extra'])
def test_aliased_source_requires_exact_same_process_canonical_and_alias_trace(tmp_path,defect):
    binary,observation,env,trace=loaded_observation(tmp_path)
    bindings={'Unknown':{'registration':'literal-RIVET_DECLARE_ALIASED_PLUGIN','aliases':['OldUnknown']}}
    trace+=b"Registering a plugin analysis via alias 'OldUnknown'\n"
    if defect=='missing':trace=trace.replace(b"Registering a plugin analysis via alias 'OldUnknown'\n",b'')
    elif defect=='duplicate':trace+=b"Registering a plugin analysis via alias 'OldUnknown'\n"
    elif defect=='wrong':trace=trace.replace(b'OldUnknown',b'UnboundAlias')
    elif defect=='collision':bindings['Unknown']['aliases']=['Unknown'];trace+=b"Registering a plugin analysis via alias 'Unknown'\n"
    elif defect=='extra':trace+=b"Registering a plugin analysis via alias 'UnboundAlias'\n"
    if defect is None:
        build.verify_loader_observation(observation,binary,'Unknown',env,tmp_path,trace,'',registered_routines=bindings)
    else:
        with pytest.raises(ValueError,match='source-bound alias'):
            build.verify_loader_observation(observation,binary,'Unknown',env,tmp_path,trace,'',registered_routines=bindings)
