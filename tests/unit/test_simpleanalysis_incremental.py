"""Small byte-custody/closed-resource controls, without native compilers or VMs."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ravel.physics import simpleanalysis_checkpoint as checkpoint
from ravel.physics import simpleanalysis_container as container
from ravel.physics.simpleanalysis_recipe import guest_programs, validate_guest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)


def fixture(tmp_path):
    previous = tmp_path / 'previous'
    for relative in ['source/analysis.cxx', 'externals/HepMC3/source.cc', 'externals/RestFrames/source.cc']:
        write(previous / 'work' / relative, 'original source\n')
    qualification = tmp_path / 'qualification.json'
    write(qualification, {'scope': 'synthetic qualification control only'})
    guest = {'schema_version': 1, 'setup': {'path': '/release_setup.sh', 'sha256': 'a' * 64},
             'tools': {k: {'path': '/qualified/' + k, 'sha256': 'b' * 64} for k in ('compiler', 'c_compiler', 'cmake', 'python')},
             'binary_relative': 'qualified-platform/bin/simpleAnalysis', 'qualification_sha256': checkpoint.sources.digest(qualification)}
    contract = {'source_inventory': {'source': 'synthetic'}, 'routine_bindings': {'Example': {}},
                'compile_units': ['analysis.cxx'], 'offline_external_overlays': [], 'external_sources': {},
                'guest': guest, 'observer_source_sha256': 'c' * 64, 'physics_validated': False}
    write(previous / 'source-contract.json', contract)
    job = {'input_directory': str(previous), 'input_files': container.tree_facts(previous),
           'transport': {'client': {'path': '/qualified/client'}, 'connection': 'qualified', 'qualification': {'sha256': guest['qualification_sha256']}, 'image': {'config_sha256': 'd' * 64}}}
    jobpath = tmp_path / 'job.json'; write(jobpath, job)
    plan = {'container_job': job, 'source_inventory': contract['source_inventory'], 'output_root': str(tmp_path / 'old-output')}
    planpath = tmp_path / 'build-plan.json'; write(planpath, plan)
    name = 'ravel-sa-' + hashlib.sha256((container.plan_hash(job) + plan['output_root']).encode()).hexdigest()[:24]
    observation = {'Id': 'e' * 64, 'Name': name, 'Image': 'd' * 64,
                   'Config': {'Labels': {'org.ravel.plan': container.plan_hash(job), 'org.ravel.job': name}},
                   'State': {'Running': False, 'Pid': 0}}
    cleanup = {'plan_sha256': container.plan_hash(job), 'job_name': name, 'state': 'stopped',
               'requires_recovery': False, 'errors': [], 'before': observation, 'after': observation}
    cleanpath = tmp_path / 'cleanup.json'; write(cleanpath, cleanup)
    stagepath = tmp_path / 'failed-stage.json'; write(stagepath, {'status': 'failed', 'error': 'wall-clock', 'cleanup': {'requires_recovery': False}})
    for index in (1, 2):
        root = tmp_path / str(index) / 'work'
        shutil.copytree(previous / 'work', root)
        for relative, raw in {
            'build/myHepMC/src/proj_HEPMC-stamp/proj_HEPMC-done': '',
            'build/src/RestFrames-stamp/RestFrames-done': '',
            'build/CMakeFiles/RestFramesBuild/lib/libRestFrames.so.1.0.0': 'completed library',
            'build/myHepMC/src/proj_HEPMC-build/outputs/lib64/libHepMC3.so.3': 'completed library',
            'build/myHepMC/src/proj_HEPMC-build/CMakeCache.txt': 'CMAKE_CXX_COMPILER:FILEPATH=/qualified/compiler\nHEPMC3_BUILD_STATIC_LIBS:BOOL=ON\n',
            'build/main.dir/analysis.cxx.o': 'INCOMPLETE MAIN OBJECT MUST NOT REUSE',
            'build/compile_commands.json': 'STALE MAIN GRAPH MUST NOT REUSE',
            'externals/RestFrames/src/generated.o': 'completed dependency object',
        }.items(): write(root / relative, raw)
        inspect = root.parent / 'inspect-before.stdout'
        inspect.write_text(json.dumps([observation]))
        write(root.parent / 'record.json', {'status': 'copied-live-incomplete', 'container_id': 'e' * 64,
              'calls': [{'returncode': 0, 'argv': ['/qualified/client','--connection','qualified','container','inspect','e'*64], 'stdout_sha256': checkpoint.sources.digest(inspect)},
                        {'returncode': 0, 'argv': ['/qualified/client','--connection','qualified', 'cp', 'e' * 64 + ':/tmp/ravel-work', str(root)]}]})
    request = {'schema_version': 1, 'snapshots': [str(tmp_path / str(i) / 'work') for i in (1, 2)],
               'previous_prepared': str(previous), 'previous_job': str(jobpath), 'previous_build_plan': str(planpath),
               'failed_stage': str(stagepath), 'qualification': str(qualification), 'container_cleanup': str(cleanpath)}
    current = copy.deepcopy(contract); current['guest'].update(schema_version=2, compiler_jobs=2)
    return request, current


def test_completed_dependencies_materialize_but_no_main_object_or_graph(tmp_path):
    request, current = fixture(tmp_path)
    result = checkpoint.materialize(request, tmp_path / 'prepared', current)
    assert result['main_target_reuse'] is False
    assert not any('main.dir' in p or p.endswith('compile_commands.json') for p in result['cache_files'])
    inputs = checkpoint.verify(result, tmp_path / 'prepared', current)
    assert len(inputs) > len(result['evidence'])
    assert Path(request['previous_prepared']) / 'work/source/analysis.cxx' in inputs
    script = guest_programs(current['guest'], result)['run.sh']
    assert 'dependency-checkpoint/work/.' in script and '--parallel 2 --target simpleAnalysis' in script
    assert 'MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2' in script


@pytest.mark.parametrize('case', ['one-copy', 'different-library', 'source-drift', 'missing-stamp',
    'empty-library', 'compiler-drift', 'static-option-drift', 'foreign-container', 'unfenced-stage',
    'failed-copy', 'guest-tool-drift', 'escape-link', 'directory-link', 'job-source-drift', 'wrong-copy-client', 'raw-inspect-drift'])
def test_real_checkpoint_refusals(tmp_path, case):
    request, current = fixture(tmp_path); root = Path(request['snapshots'][1])
    if case == 'one-copy': request['snapshots'][0] = request['snapshots'][1]
    elif case == 'different-library': write(root / 'build/CMakeFiles/RestFramesBuild/lib/libRestFrames.so.1.0.0', 'different')
    elif case == 'source-drift': write(root / 'source/analysis.cxx', 'changed source')
    elif case == 'missing-stamp': (root / 'build/src/RestFrames-stamp/RestFrames-done').unlink()
    elif case == 'empty-library':
        for value in request['snapshots']: write(Path(value) / 'build/CMakeFiles/RestFramesBuild/lib/libRestFrames.so.1.0.0', '')
    elif case in ('compiler-drift', 'static-option-drift'):
        for value in request['snapshots']:
            p = Path(value) / 'build/myHepMC/src/proj_HEPMC-build/CMakeCache.txt'
            p.write_text(p.read_text().replace('/qualified/compiler', '/different/compiler') if case == 'compiler-drift' else p.read_text().replace('=ON', '=OFF'))
    elif case == 'foreign-container':
        p = Path(request['container_cleanup']); value = json.loads(p.read_text()); value['after']['Config']['Labels']['org.ravel.job'] = 'foreign'; write(p, value)
    elif case == 'unfenced-stage': write(Path(request['failed_stage']), {'status': 'failed', 'error': 'wall-clock', 'cleanup': {'requires_recovery': True}})
    elif case == 'failed-copy':
        p = root.parent / 'record.json'; value = json.loads(p.read_text()); value['calls'][1]['returncode'] = 2; write(p, value)
    elif case == 'wrong-copy-client':
        p = root.parent / 'record.json'; value = json.loads(p.read_text()); value['calls'][1]['argv'][0] = '/foreign/client'; write(p,value)
    elif case == 'raw-inspect-drift': (root.parent / 'inspect-before.stdout').write_text('[]')
    elif case == 'guest-tool-drift': current['guest']['tools']['compiler']['sha256'] = 'f' * 64
    elif case == 'escape-link': (root / 'escape').symlink_to(tmp_path / 'qualification.json')
    elif case == 'directory-link': (root / 'directory-alias').symlink_to(root / 'source', target_is_directory=True)
    elif case == 'job-source-drift': write(Path(request['previous_prepared']) / 'work/source/analysis.cxx', 'producer rehash cannot establish old approval')
    with pytest.raises(ValueError): checkpoint.derive(request, current)


def test_rehashed_prepared_cache_cannot_replace_retained_copy(tmp_path):
    request, current = fixture(tmp_path)
    result = checkpoint.materialize(request, tmp_path / 'prepared', current)
    p = tmp_path / 'prepared/dependency-checkpoint/work/externals/RestFrames/src/generated.o'
    p.write_text('arbitrary producer replacement')
    result['cache_files']['externals/RestFrames/src/generated.o'] = {'sha256': checkpoint.sources.digest(p), 'size': p.stat().st_size}
    with pytest.raises(ValueError, match='checkpoint'): checkpoint.verify(result, tmp_path / 'prepared', current)


def test_internal_file_links_are_flattened_and_extra_main_cache_refused(tmp_path):
    request, current = fixture(tmp_path)
    for value in request['snapshots']:
        p = Path(value) / 'build/myHepMC/src/proj_HEPMC-build/outputs/lib64/libHepMC3.so'
        p.symlink_to('libHepMC3.so.3')
    result = checkpoint.materialize(request, tmp_path / 'prepared', current)
    target = tmp_path / 'prepared/dependency-checkpoint/work/build/myHepMC/src/proj_HEPMC-build/outputs/lib64/libHepMC3.so'
    assert target.is_file() and not target.is_symlink()
    write(tmp_path / 'prepared/dependency-checkpoint/work/build/forged.dir/main.o', 'not admitted')
    with pytest.raises(ValueError): checkpoint.verify(result, tmp_path / 'prepared', current)


def test_container_v1_unchanged_and_explicit_v2_resources(monkeypatch, tmp_path):
    monkeypatch.setattr(container, 'validate_transport', lambda value, **kwargs: value)
    write(tmp_path / 'run.sh', '#!/bin/bash\ntrue\n')
    transport = {'image': {'reference': 'immutable'}}
    old = container.make_plan(transport, tmp_path, max_seconds=120)
    assert old['schema_version'] == 1 and 'cpus' not in old['resources']
    new = container.make_plan(transport, tmp_path, max_seconds=7200, memory_mib=5120, cpus=2)
    assert new['schema_version'] == 2 and new['resources']['workers'] == 1
    args = container._create_arguments(new, tmp_path, 'owned')
    assert args[args.index('--cpus') + 1] == '2' and args[args.index('--memory') + 1] == '5120m'
    for cpus, memory in [(True, 5120), (3, 5120), (1, 5120), (2, 8193)]:
        with pytest.raises(ValueError): container.make_plan(transport, tmp_path, max_seconds=7200, memory_mib=memory, cpus=cpus)


def test_actual_v2_resource_observation_must_match():
    plan = {'schema_version': 2, 'resources': {'cpus': 2, 'memory_mib': 5120},
            'transport': {'image': {'config_sha256': 'a' * 64}}}
    observation = {'Id': 'b' * 64, 'Name': 'owned', 'Image': 'a' * 64,
                   'Config': {'Labels': {'org.ravel.plan': container.plan_hash(plan), 'org.ravel.job': 'owned'}},
                   'State': {'Running': False}, 'HostConfig': {'NanoCpus': 2 * 10**9, 'Memory': 5120 * 1024**2, 'PidsLimit': 256}}
    assert container._owned(observation, plan, 'owned') == 'b' * 64
    container._observed_resources(observation, plan)
    for key, bad in [('NanoCpus', 10**9), ('Memory', 3072 * 1024**2), ('PidsLimit', 257)]:
        changed = copy.deepcopy(observation); changed['HostConfig'][key] = bad
        with pytest.raises(ValueError, match='resources'): container._observed_resources(changed, plan)
        assert container._owned(changed,plan,'owned') == 'b'*64


def test_old_guest_program_bytes_and_positive_new_job_contract():
    guest = {'schema_version': 1, 'setup': {'path': '/release_setup.sh', 'sha256': 'a' * 64},
             'tools': {k: {'path': '/qualified/' + k, 'sha256': 'b' * 64} for k in ('compiler', 'c_compiler', 'cmake', 'python')},
             'binary_relative': 'platform/bin/simpleAnalysis', 'qualification_sha256': 'c' * 64}
    first = guest_programs(guest)
    assert '--parallel 1 --target simpleAnalysis' in first['run.sh'] and 'dependency-checkpoint' not in first['run.sh']
    changed = copy.deepcopy(guest); changed.update(schema_version=2, compiler_jobs=2)
    assert 'fcntl.flock' in guest_programs(changed)['compiler-launcher.py']
    assert 'fcntl.flock' not in first['compiler-launcher.py']
    for bad in (True, 3, 0):
        changed['compiler_jobs'] = bad
        with pytest.raises(ValueError): validate_guest(changed)


def test_real_two_concurrent_journal_invocations(tmp_path):
    import base64
    import subprocess
    import sys
    guest = {'schema_version': 2, 'compiler_jobs': 2, 'setup': {'path': '/release_setup.sh', 'sha256': 'a' * 64},
             'tools': {k: {'path': '/qualified/' + k, 'sha256': 'b' * 64} for k in ('compiler', 'c_compiler', 'cmake', 'python')},
             'binary_relative': 'platform/bin/simpleAnalysis', 'qualification_sha256': 'c' * 64}
    journal = tmp_path / 'journal.jsonl'
    launcher = tmp_path / 'launcher.py'
    launcher.write_text(guest_programs(guest)['compiler-launcher.py'].replace('/tmp/ravel-output/compiler-invocations.jsonl', str(journal)))
    sources = []
    for index in (1, 2):
        p = tmp_path / (str(index) + '.cxx'); p.write_text(('source-only development control ' + str(index) + '\n') * 20000); sources.append(p)
    processes = [subprocess.Popen([sys.executable, str(launcher), '/usr/bin/true', str(p)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for p in sources]
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert len(rows) == 2 and len({row['pid'] for row in rows}) == 2
    assert {row['compile_inputs'][0]['path'] for row in rows} == set(map(str, sources))
    for row in rows:
        fact = row['compile_inputs'][0]
        assert base64.b64decode(fact['content_base64']) == Path(fact['path']).read_bytes()
        assert fact['sha256'] == checkpoint.sources.digest(fact['path'])


def test_lexical_alias_of_one_copy_is_not_independent_custody(tmp_path):
    request, current = fixture(tmp_path)
    first = Path(request['snapshots'][0])
    # Preserve the reviewer's exact attack: two successful synthetic cp rows
    # can have distinct spellings while naming one existing physical tree.
    alias = str(first / '..' / 'work')
    record_path = first.parent / 'record.json'
    record = json.loads(record_path.read_text())
    record['calls'].append({**record['calls'][1], 'argv': [*record['calls'][1]['argv'][:-1], alias]})
    write(record_path, record)
    request['snapshots'][1] = alias
    assert first.samefile(alias) and first.resolve() == Path(alias).resolve()
    with pytest.raises(ValueError, match='canonical ordinary snapshot'):
        checkpoint.derive(request, current)


def test_snapshot_directory_symlink_is_not_a_second_owned_copy(tmp_path):
    request, current = fixture(tmp_path)
    alias = tmp_path / 'aliased-copy'
    alias.symlink_to(Path(request['snapshots'][0]), target_is_directory=True)
    request['snapshots'][1] = str(alias)
    assert alias.samefile(request['snapshots'][0])
    with pytest.raises(ValueError, match='canonical ordinary snapshot'):
        checkpoint.derive(request, current)
