"""Prepare the full upstream SimpleAnalysis source for an offline native job.

Only the two upstream external-source download clauses are replaced. Analysis,
object reconstruction, selections, model files and finalization remain byte
identical. Image qualification and governed routine-build execution are separate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

from ravel import analysis_sources as sources
from ravel.physics import simpleanalysis_container as container
from ravel.workflow.state_io import atomic_json


def offline_external_overlay(raw, name):
    """Replace a positively recognized upstream download clause, not arbitrary CMake."""
    text = raw.decode('utf-8')
    if name == 'HepMC3':
        old = '  GIT_REPOSITORY https://gitlab.cern.ch/hepmc/HepMC3.git\n  GIT_TAG 3.2.6\n'
    elif name == 'RestFrames':
        old = '   URL https://github.com/crogan/RestFrames/archive/v1.0.1.tar.gz\n   URL_MD5 668e3ca6f301172d7e67b5e85b1ab6d2\n'
    else:
        raise ValueError('only the two source-declared external projects are supported')
    if text.count(old) != 1:
        raise ValueError('source external download clause differs from reviewed upstream')
    replacement = '  SOURCE_DIR ${CMAKE_SOURCE_DIR}/../externals/' + name + '\n  DOWNLOAD_COMMAND ""\n  UPDATE_COMMAND ""\n'
    return text.replace(old, replacement).encode('utf-8')


def prepare_inputs(capsule, base, destination, *, external_sources, guest, observer_source=None, compiler_jobs=1, dependency_checkpoint=None):
    """Materialize reviewable source, offline dependencies and fixed guest commands.

    Called during preparation, before science.plan. This never probes a tool or
    compiles. The resulting input tree is independently bound by the normal
    scientific-study plan before container execution.
    """
    sources.validate_capsule(capsule)
    root, _ = sources.source_files(capsule, base)
    if capsule['framework'] != 'simpleanalysis' or not capsule['submodules']:
        raise ValueError('complete upstream SimpleAnalysis submodule capsule required')
    if not capsule['dependency_review']['complete'] or any(d['status'] != 'resolved' for d in capsule['dependencies']):
        raise ValueError('qualified native runtime and complete external/source obligations required')
    if set(external_sources) != {'HepMC3','RestFrames'}:
        raise ValueError('both independently acquired external source trees required')
    guest = json.loads(json.dumps(guest))
    if type(compiler_jobs) is not int or compiler_jobs not in (1, 2):
        raise ValueError('one or two explicit native compiler jobs required')
    if compiler_jobs == 2:
        guest['schema_version'] = 2
        guest['compiler_jobs'] = 2
    validate_guest(guest)
    if observer_source is None:
        from ravel.physics.simpleanalysis_observer import NATIVE_LOADER_OBSERVER
        observer_source=NATIVE_LOADER_OBSERVER.encode()
    if not isinstance(observer_source, bytes) or not observer_source:
        raise ValueError('qualified same-process native observer source required')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('preserve prior prepared guest input tree')
    destination.mkdir(parents=True)
    staged = destination/'work/source';staged.mkdir(parents=True)
    for fact in capsule['files']:
        target=staged/fact['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/fact['path'],target)
        if sources.digest(target)!=fact['sha256']:
            raise ValueError('source changed while staging native input')
    units=[f['path'] for f in capsule['files'] if f['role']=='compile']
    bindings=container.routine_bindings(capsule,base,units)
    changed=[]
    for name,path in {'HepMC3':'Ext_HEPMC/externals.cmake','RestFrames':'Ext_RestFrames/externals.cmake'}.items():
        target=staged/path;before=target.read_bytes();after=offline_external_overlay(before,name);target.write_bytes(after)
        changed.append({'path':path,'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest(),
                        'scope':'Only exact upstream acquisition clause replaced by bound offline SOURCE_DIR; source build/settings retained'})
    for name,entry in external_sources.items():
        if set(entry)!= {'root','files','archive_sha256','source_commit'}:
            raise ValueError('external source must retain acquired archive and extracted byte closure')
        sources._hash(entry['archive_sha256'])
        if not re.fullmatch('[0-9a-f]{40}',entry['source_commit']):
            raise ValueError('external source exact commit required')
        if container.tree_facts(entry['root'])!=entry['files']:
            raise ValueError('acquired external source changed')
        shutil.copytree(entry['root'],destination/'work/externals'/name)
    contract = {'source_inventory':sources.inventory(capsule,base),'routine_bindings':bindings,
        'compile_units':units,'offline_external_overlays':changed,'external_sources':external_sources,'guest':guest,
        'observer_source_sha256':hashlib.sha256(observer_source).hexdigest(),'physics_validated':False}
    if dependency_checkpoint is not None:
        from ravel.physics import simpleanalysis_checkpoint as checkpoint
        contract['dependency_checkpoint'] = checkpoint.materialize(dependency_checkpoint, destination, contract)
    atomic_json(destination/'source-contract.json', contract)
    (destination/'native-observer.c').write_bytes(observer_source)
    for name,content in guest_programs(guest, contract.get('dependency_checkpoint')).items():
        (destination/name).write_text(content)
    (destination/'compiler-launcher.py').chmod(0o755)
    return {'input_directory':str(destination.resolve()),'input_files':container.tree_facts(destination),
        'routine_bindings':bindings,'compile_units':units,'offline_external_overlays':changed,'physics_validated':False}


def guest_programs(guest, dependency_checkpoint=None):
    """Derive the only admitted compiler/guest programs without filesystem IO."""
    validate_guest(guest)
    tools=guest['tools']
    launcher = '''import base64,hashlib,json,os,sys,time
target=sys.argv[1];facts=[]
for arg in sys.argv[2:]:
 if arg.endswith(('.cc','.cxx','.cpp','.c')) and os.path.isfile(arg):
  raw=open(arg,'rb').read();facts.append({'path':os.path.abspath(arg),'sha256':hashlib.sha256(raw).hexdigest(),'content_base64':base64.b64encode(raw).decode('ascii')})
record={'schema_version':1,'pid':os.getpid(),'cwd':os.getcwd(),'argv':sys.argv[1:],'environment':dict(os.environ),'driver_path':target,'driver_sha256':hashlib.sha256(open(target,'rb').read()).hexdigest(),'compile_inputs':facts,'timestamp_ns':int(time.time()*1e9)}
with open('/tmp/ravel-output/compiler-invocations.jsonl','a') as stream:
 stream.write(json.dumps(record,sort_keys=True)+'\\n');stream.flush();os.fsync(stream.fileno())
os.execv(target,sys.argv[1:])
'''
    if guest.get('compiler_jobs', 1) == 2:
        # Preserve a complete raw JSON record across two concurrent launchers.
        # Ownership cleanup is unaffected; no lock survives the driver exec.
        launcher = launcher.replace('import base64,', 'import fcntl,base64,', 1)
        lines = launcher.splitlines(True)
        launcher = ''.join((' fcntl.flock(stream.fileno(),fcntl.LOCK_EX)\n try:\n ' + line +
                            ' finally:\n  fcntl.flock(stream.fileno(),fcntl.LOCK_UN)\n')
                           if line.startswith(' stream.write(') else line for line in lines)
    # The setup comes from the bound image; CMake and both compiler paths are
    # positively qualified rather than selected from the host shell's PATH.
    script='''#!/bin/bash
set -euo pipefail
mkdir -p /tmp/ravel-output
exec > /tmp/ravel-output/build.log 2>&1
set +u
set +o pipefail
source SETUP
set -euo pipefail
export LC_ALL=C LC_CTYPE=C OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MAKEFLAGS=-j1 CMAKE_BUILD_PARALLEL_LEVEL=1
export CXX=COMPILER_TOOL CC=C_COMPILER_TOOL
COMPILER_TOOL --version
sha256sum SETUP COMPILER_TOOL C_COMPILER_TOOL CMMAKE
cp -a /tmp/ravel-input/work /tmp/ravel-work
mkdir -p /tmp/ravel-work/build/.cmake/api/v1/query
touch /tmp/ravel-work/build/.cmake/api/v1/query/codemodel-v2
CMMAKE -S /tmp/ravel-work/source -B /tmp/ravel-work/build -DCMAKE_CXX_COMPILER=COMPILER_TOOL -DCMAKE_C_COMPILER=C_COMPILER_TOOL -DCMAKE_CXX_COMPILER_LAUNCHER=/tmp/ravel-input/compiler-launcher.py -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
CMMAKE --build /tmp/ravel-work/build --parallel 1 --target simpleAnalysis
test -x /tmp/ravel-work/build/BINARY
set +u
set +o pipefail
source /tmp/ravel-work/build/PLATFORM/setup.sh
set -euo pipefail
mkdir -p /tmp/ravel-output/probe
C_COMPILER_TOOL -O0 -fPIC -shared /tmp/ravel-input/native-observer.c -o /tmp/ravel-work/native-observer.so
RAVEL_NATIVE_BINARY=/tmp/ravel-work/build/BINARY RAVEL_NATIVE_OBSERVER_DIRECTORY=/tmp/ravel-output/probe LD_PRELOAD=/tmp/ravel-work/native-observer.so /tmp/ravel-work/build/BINARY -l > /tmp/ravel-output/listing.stdout 2> /tmp/ravel-output/listing.stderr
cp /tmp/ravel-work/build/compile_commands.json /tmp/ravel-output/compile_commands.json
cp -a /tmp/ravel-work/build/.cmake/api/v1/reply /tmp/ravel-output/cmake-reply
mkdir -p /tmp/ravel-output/runtime/work/build
cp -aL /tmp/ravel-work/build/PLATFORM /tmp/ravel-output/runtime/work/build/PLATFORM
cp -a /tmp/ravel-work/source /tmp/ravel-output/runtime/work/source
cp /tmp/ravel-work/native-observer.so /tmp/ravel-output/runtime/work/native-observer.so
cp /tmp/ravel-input/source-contract.json /tmp/ravel-output/source-contract.json
printf '%s\\n' SOURCE_BUILT_SIMPLEANALYSIS_COMPLETED
'''
    if guest.get('compiler_jobs', 1) == 2:
        script = script.replace('MAKEFLAGS=-j1 CMAKE_BUILD_PARALLEL_LEVEL=1', 'MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2').replace('--parallel 1 --target', '--parallel 2 --target')
    if dependency_checkpoint is not None:
        script = script.replace('cp -a /tmp/ravel-input/work /tmp/ravel-work\n', 'cp -a /tmp/ravel-input/work /tmp/ravel-work\ncp -a /tmp/ravel-input/dependency-checkpoint/work/. /tmp/ravel-work/\n')
    replacements={'SETUP':guest['setup']['path'],'CMMAKE':tools['cmake']['path'],'COMPILER_TOOL':tools['compiler']['path'],
        'C_COMPILER_TOOL':tools['c_compiler']['path'],'BINARY':guest['binary_relative'],'PLATFORM':str(Path(guest['binary_relative']).parts[0])}
    # Tokens are delimited, preventing a path containing a token from being
    # transformed by a later replacement pass.
    script=re.sub(r'\b(?:SETUP|CMMAKE|COMPILER_TOOL|C_COMPILER_TOOL|BINARY|PLATFORM)\b',lambda m:replacements[m[0]],script)
    return {'compiler-launcher.py':'#!'+tools['python']['path']+'\n'+launcher,'run.sh':script}


def validate_guest(guest):
    """Validate closed guest paths/identities before interpolating a shell job."""
    expected = {'schema_version','setup','tools','binary_relative','qualification_sha256'} | ({'compiler_jobs'} if guest.get('schema_version') == 2 else set())
    if set(guest) != expected or guest.get('schema_version') not in (1, 2) or (guest.get('schema_version') == 2 and (type(guest['compiler_jobs']) is not int or guest['compiler_jobs'] != 2)):
        raise ValueError('qualified guest setup/tool/layout contract required')
    sources._hash(guest['qualification_sha256'])
    sources.relative_path(guest['binary_relative'])
    if Path(guest['binary_relative']).name != 'simpleAnalysis':
        raise ValueError('the full upstream simpleAnalysis executable is required')
    if set(guest['tools']) != {'compiler','c_compiler','cmake','python'}:
        raise ValueError('qualified native C/CXX/CMake/observer interpreter required')
    for fact in [guest['setup'], *guest['tools'].values()]:
        if set(fact) != {'path','sha256'} or not isinstance(fact['path'],str) or not re.fullmatch(r'/[A-Za-z0-9_./+\-]+',fact['path']):
            raise ValueError('closed absolute guest tool path required')
        sources._hash(fact['sha256'])
    return guest
