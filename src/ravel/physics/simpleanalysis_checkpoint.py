"""Prospective reuse of two completed native dependencies, never main objects.

A failed build remains failed. A new governed plan may admit locally preserved
dependency bytes as explicit inputs after checking two independent copies,
upstream sources, the original guest recipe and its completed build stamps.
This is local byte custody, not authenticated process or physics attestation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from ravel import analysis_sources as sources
from ravel.physics import simpleanalysis_container as container
from ravel.workflow.state_io import atomic_json, read_json


def _fact(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('ordinary absolute checkpoint evidence required')
    return {'path': str(path), 'sha256': sources.digest(path), 'size': path.stat().st_size}


def _census(root):
    """Normalize only internal file links, retaining their exact spelling."""
    root = Path(root)
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('ordinary checkpoint directory required')
    files, links, total = {}, {}, 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError('checkpoint directory aliases are refused')
        for name in names:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            sources.relative_path(relative)
            if path.is_symlink():
                target = os.readlink(path)
                if os.path.isabs(target) or not path.resolve().is_relative_to(root) or not path.resolve().is_file():
                    raise ValueError('checkpoint link escapes its owned source tree')
                links[relative] = target
            elif not path.is_file():
                raise ValueError('checkpoint special file refused')
            size = path.stat().st_size
            if size > 128 * 1024**2:
                raise ValueError('checkpoint member exceeds declared bound')
            total += size
            if total > 2 * 1024**3 or len(files) >= 10000:
                raise ValueError('checkpoint tree exceeds declared bound')
            files[relative] = {'sha256': sources.digest(path), 'size': size}
    return files, links


def _select(relative, original_restframes, platform):
    """Closed dependency/cache paths; a main-target object never qualifies."""
    if relative.startswith('externals/RestFrames/'):
        return relative[len('externals/RestFrames/'):] not in original_restframes
    prefixes = ('build/myHepMC/', 'build/CMakeFiles/RestFramesBuild/',
                'build/src/RestFrames-stamp/')
    if relative.startswith(prefixes):
        return True
    if relative == 'build/CMakeFiles/RestFrames-complete':
        return True
    if relative.startswith('build/tmp/RestFrames-'):
        return True
    prefix = 'build/' + platform + '/'
    if relative.startswith(prefix):
        child = relative[len(prefix):]
        return (child.startswith(('include/HepMC3/', 'include/RestFrames/', 'share/HepMC3/'))
                or child == 'bin/HepMC3-config'
                or bool(re.fullmatch(r'lib(?:64)?/lib(?:HepMC3|RestFrames)\.(?:so(?:\.[0-9.]+)?|a|la)', child)))
    return False


def derive(request, current_contract):
    required = {'schema_version', 'snapshots', 'previous_prepared', 'previous_job',
                'previous_build_plan', 'failed_stage', 'qualification', 'container_cleanup'}
    if not isinstance(request, dict) or set(request) != required or request['schema_version'] != 1 or len(request['snapshots']) != 2:
        raise ValueError('two-copy completed-dependency checkpoint request required')
    paths = [Path(p) for p in request['snapshots']]
    for root in paths:
        if (not root.is_absolute() or root != root.resolve()
                or any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir()):
            raise ValueError('canonical ordinary snapshot roots required')
    if paths[0].samefile(paths[1]):
        raise ValueError('physically distinct owned copies required')
    evidence = [_fact(request[key]) for key in ('previous_job', 'previous_build_plan', 'failed_stage', 'qualification', 'container_cleanup')]
    stage = read_json(request['failed_stage'])
    if stage.get('status') != 'failed' or stage.get('error') != 'wall-clock' or stage.get('cleanup', {}).get('requires_recovery') is not False:
        raise ValueError('preserved failed and host-fenced source attempt required')
    previous = Path(request['previous_prepared'])
    evidence.append(_fact(previous / 'source-contract.json'))
    old = read_json(previous / 'source-contract.json')
    for key in ('source_inventory', 'routine_bindings', 'compile_units', 'offline_external_overlays', 'external_sources', 'observer_source_sha256'):
        if current_contract[key] != old[key]:
            raise ValueError('checkpoint source/dependency recipe differs')
    expected_guest = dict(current_contract['guest'])
    expected_guest.pop('compiler_jobs', None)
    expected_guest['schema_version'] = 1
    if old['guest'] != expected_guest or expected_guest['qualification_sha256'] != sources.digest(request['qualification']):
        raise ValueError('checkpoint compiler/image qualification differs')
    job = read_json(request['previous_job'])
    if job['input_directory'] != str(previous) or job['transport']['qualification']['sha256'] != expected_guest['qualification_sha256']:
        raise ValueError('checkpoint original container job differs')
    plan = read_json(request['previous_build_plan'])
    if plan.get('container_job') != job or plan.get('source_inventory') != old['source_inventory']:
        raise ValueError('checkpoint original source build plan differs')
    if job['input_files'] != container.tree_facts(previous):
        raise ValueError('checkpoint original approved inputs changed')
    cleanup = read_json(request['container_cleanup'])
    expected_name = 'ravel-sa-' + hashlib.sha256((container.plan_hash(job) + plan['output_root']).encode()).hexdigest()[:24]
    if cleanup.get('plan_sha256') != container.plan_hash(job) or cleanup.get('job_name') != expected_name or cleanup.get('state') != 'stopped' or cleanup.get('requires_recovery') is not False or cleanup.get('errors') != []:
        raise ValueError('actual closed owned dependency container required')
    cid = cleanup['after']['Id']
    for phase in ('before','after'):
        container._owned(cleanup[phase],job,expected_name,cid)
    if cleanup['after']['State']['Running'] or cleanup['after']['State'].get('Pid') != 0:
        raise ValueError('actual checkpoint container is not quiescent')
    censuses = []
    for snapshot in paths:
        capture = read_json(snapshot.parent / 'record.json')
        evidence.append(_fact(snapshot.parent / 'record.json'))
        if capture.get('status') != 'copied-live-incomplete' or capture.get('container_id') != cid:
            raise ValueError('checkpoint copy is not the retained owned container')
        calls = capture.get('calls', [])
        prefix = [job['transport']['client']['path'], '--connection', job['transport']['connection']]
        raw_inspect = _fact(snapshot.parent / 'inspect-before.stdout')
        evidence.append(raw_inspect)
        if not calls or calls[0].get('argv') != prefix + ['container','inspect',cid] or calls[0].get('returncode') != 0 or calls[0].get('stdout_sha256') != raw_inspect['sha256']:
            raise ValueError('actual raw owned copy-time observation required')
        observed = read_json(raw_inspect['path'])
        if not isinstance(observed,list) or len(observed) != 1:
            raise ValueError('one raw copy-time container observation required')
        container._owned(observed[0],job,expected_name,cid)
        if not any(c.get('returncode') == 0 and c.get('argv') == prefix + ['cp',capture['container_id'] + ':/tmp/ravel-work', str(snapshot)] for c in calls):
            raise ValueError('actual successful owned work-copy command required')
        facts, links = _census(snapshot)
        censuses.append((facts, links))
        for relative, fact in job['input_files'].items():
            if relative.startswith('work/') and censuses[-1][0].get(relative[len('work/'):]) != fact:
                raise ValueError('preserved upstream or external source differs')
    original_rest = set(container.tree_facts(previous / 'work/externals/RestFrames'))
    platform = Path(old['guest']['binary_relative']).parts[0]
    selected = {p: f for p, f in censuses[1][0].items() if _select(p, original_rest, platform)}
    if not selected or any(censuses[0][0].get(p) != fact for p, fact in selected.items()):
        raise ValueError('dependency bytes are incomplete or changed across owned copies')
    selected_links = {p: t for p, t in censuses[1][1].items() if p in selected}
    if any(censuses[0][1].get(p) != t for p, t in selected_links.items()):
        raise ValueError('dependency link identity changed across owned copies')
    required_paths = ['build/myHepMC/src/proj_HEPMC-stamp/proj_HEPMC-done',
                      'build/src/RestFrames-stamp/RestFrames-done',
                      'build/CMakeFiles/RestFramesBuild/lib/libRestFrames.so.1.0.0',
                      'build/myHepMC/src/proj_HEPMC-build/outputs/lib64/libHepMC3.so.3']
    if any(p not in selected for p in required_paths) or any(selected[p]['size'] == 0 for p in required_paths[2:]):
        raise ValueError('both completed dependency stamps and actual libraries required')
    cache = (paths[1] / 'build/myHepMC/src/proj_HEPMC-build/CMakeCache.txt').read_text()
    if ('CMAKE_CXX_COMPILER:FILEPATH=' + expected_guest['tools']['compiler']['path'] + '\n' not in cache
            or 'HEPMC3_BUILD_STATIC_LIBS:BOOL=ON\n' not in cache):
        raise ValueError('completed dependency compiler/build options differ')
    # No main objects, dictionary, executable or target graph are imported.
    return {'schema_version': 1, 'kind': 'simpleanalysis-completed-dependency-checkpoint',
            'request': request, 'evidence': evidence, 'cache_files': selected,
            'normalized_internal_links': selected_links, 'image': job['transport']['image'],
            'compiler_jobs': current_contract['guest'].get('compiler_jobs', 1),
            'main_target_reuse': False, 'physics_validated': False}


def materialize(request, prepared, current_contract):
    result = derive(request, current_contract)
    destination = Path(prepared) / 'dependency-checkpoint/work'
    if destination.exists():
        raise ValueError('preserve previous dependency checkpoint')
    source = Path(request['snapshots'][1])
    for relative in result['cache_files']:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target, follow_symlinks=True)
    if container.tree_facts(destination) != result['cache_files']:
        raise ValueError('materialized dependency checkpoint bytes differ')
    return result


def verify(result, prepared, current_contract):
    expected = derive(result['request'], current_contract)
    if expected != result or container.tree_facts(Path(prepared) / 'dependency-checkpoint/work') != result['cache_files']:
        raise ValueError('approved dependency checkpoint or source custody differs')
    # The ordinary science input snapshot binds the actual cache and all source
    # witnesses. The two snapshots are enumerated rather than hidden in a root.
    inputs = [Path(f['path']) for f in result['evidence']]
    previous_job = read_json(result['request']['previous_job'])
    inputs.extend(Path(result['request']['previous_prepared']) / relative for relative in previous_job['input_files'])
    for root in map(Path, result['request']['snapshots']):
        facts, _ = _census(root)
        inputs.extend(p for relative in facts if not (p := root / relative).is_symlink())
    return inputs
