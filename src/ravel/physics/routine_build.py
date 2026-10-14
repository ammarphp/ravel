"""Observed bounded routine builds and probes, separate from physics admission.

The standard scientific-study wrapper supplies approval and supervision. Planning
only reads declared files; it never probes an executable or runs a build script.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import json
import sys
import time
from datetime import datetime, timezone

from ravel import analysis_sources as sources
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, read_json

ENVIRONMENT = {'PATH', 'SDKROOT', 'LIBRARY_PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH',
               'PYTHONPATH', 'PKG_CONFIG_PATH', 'CMAKE_PREFIX_PATH'}
RECIPES = {'cpp-executable', 'rivet-plugin', 'simpleanalysis-analysisbase'}

# The observer execs the original alias pathname, preserving clang++ driver
# semantics. A completed successful build is separate evidence that exec worked.
COMPILER_OBSERVER = r'''import base64,hashlib,json,os,sys,time
from pathlib import Path
target, journal = os.environ['RAVEL_COMPILER_TARGET'], os.environ['RAVEL_COMPILER_JOURNAL']
p=Path(target)
inputs=[]
for arg in sys.argv[1:]:
    candidate=Path(arg)
    if candidate.suffix in ('.cc','.cxx','.cpp','.c') and candidate.is_file():
        raw=candidate.read_bytes()
        inputs.append({'path':str(candidate.absolute()),'sha256':hashlib.sha256(raw).hexdigest(),
                       'content_base64':base64.b64encode(raw).decode()})
fact={'schema_version':2,'pid':os.getpid(),'cwd':os.getcwd(),'argv':[target,*sys.argv[1:]],
      'invoked_alias':str(Path(sys.argv[0]).absolute()),'target':str(p.resolve()),
      'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'timestamp_ns':time.time_ns(),
      'compile_inputs':inputs}
with open(journal,'a') as f:
    f.write(json.dumps(fact,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
os.execv(target,[target,*sys.argv[1:]])
'''

# Run in a fresh bound interpreter. The operating-system image inventory is an
# independent observation of loading, combined with Rivet's successful canonical
# registration trace; neither a candidate path nor a metadata name alone passes.
RIVET_LOADER_OBSERVER = r'''import ctypes,hashlib,json,os,sys
from pathlib import Path
def images():
    if sys.platform == 'darwin':
        lib=ctypes.CDLL(None)
        lib._dyld_image_count.restype=ctypes.c_uint32
        lib._dyld_get_image_name.argtypes=[ctypes.c_uint32]
        lib._dyld_get_image_name.restype=ctypes.c_char_p
        return sorted({os.fsdecode(lib._dyld_get_image_name(i)) for i in range(lib._dyld_image_count())})
    if sys.platform.startswith('linux'):
        return sorted({line.split(None,5)[5].strip() for line in Path('/proc/self/maps').read_text().splitlines()
                       if len(line.split(None,5))==6 and line.split(None,5)[5].startswith('/')})
    raise RuntimeError('loaded-image observation unsupported on this platform')
def fact(path):
    p=Path(path)
    return {'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
plugin,routine,output,cli,*arguments=sys.argv[1:]
plugin=str(Path(plugin).resolve())
before=images()
if any(Path(p).name.startswith('Rivet') and p.endswith('.so') for p in before):
    raise RuntimeError('analysis plugin preloaded before Rivet import')
identity=fact(plugin)
import rivet
imported=images()
if any(Path(p).name.startswith('Rivet') and p.endswith('.so') for p in imported):
    raise RuntimeError('analysis plugin preloaded during Rivet import')
rivet.setLogLevel('Rivet.AnalysisLoader',0)
rivet.setAnalysisPlugins([plugin])
names=rivet.AnalysisLoader.analysisNames()
analysis=rivet.AnalysisLoader.getAnalysis(routine) if cli == '-' else None
loaded=images()
if routine not in names or (cli == '-' and (analysis is None or analysis.name()!=routine)):
    raise RuntimeError('exact canonical analysis not registered')
paths=[str(Path(p).resolve()) for p in loaded if Path(p).name.startswith('Rivet') and p.endswith('.so')]
if paths != [plugin] or fact(plugin)!=identity:
    raise RuntimeError('actual loaded analysis plugin differs from expected binary')
observation={'schema_version':1,'kind':'rivet-loader-observation','pid':os.getpid(),
    'cwd':os.getcwd(),'environment':dict(os.environ),'python':fact(sys.executable),
    'plugin_before':identity,'plugin_after':fact(plugin),'images_before':before,
    'images_after_import':imported,'images_after_load':loaded,'selected_plugins':rivet.analysisPlugins(),
    'registered_names':names,'canonical_routine':routine,'runtime_version':rivet.version(),
    'physics_validated':False}
Path(output).write_text(json.dumps(observation,sort_keys=True,indent=2)+'\n')
# Optional CLI execution occurs in this same process after custody observations.
if cli != '-':
    import runpy
    sys.argv=[cli,*arguments]
    runpy.run_path(cli,run_name='__main__')
else:
    print(routine)
'''


def executable_identity(path):
    """Read-only invocation path, every alias link and final executable bytes."""
    p = Path(path).absolute()
    links = []
    current = p
    for _ in range(64):
        # Resolve directory aliases too, without losing their spelling.
        alias = next((q for q in reversed((current, *current.parents)) if q.is_symlink()), None)
        if alias is None:
            break
        target = os.readlink(alias)
        links.append({'path': str(alias), 'target': target})
        current = (alias.parent / target if not Path(target).is_absolute() else Path(target)) / current.relative_to(alias)
        current = Path(os.path.abspath(current))
    else:
        raise ValueError('executable alias cycle or excessive link chain')
    if not current.is_file() or not os.access(p, os.X_OK):
        raise ValueError('missing or nonexecutable runtime alias: ' + str(p))
    return {'path': str(p), 'resolved_path': str(current), 'sha256': sources.digest(current), 'links': links}


def _rivet_compiler(build, declared, environment):
    """Recognize the pinned upstream selection protocol without executing it."""
    code = Path(build).read_text(errors='replace')
    match = re.search(r'rivetcxx=\$\(which \$\(echo "([^"\n]+)" \| awk', code)
    branch = re.search(r'if \[\[ -x "\$rivetcxx" \]\]; then\s*mycxx="([^"\n]+)"\s*elif \[\[ -x "\$abscxx" \]\]; then\s*mycxx="\$CXX"', code)
    if not match or not branch or not re.fullmatch(r'[A-Za-z0-9_.+\-]+(?: -std=c\+\+(?:11|14|17|20|23))?', branch[1]):
        raise ValueError('unsupported Rivet compiler selection protocol; bind a supported builder')
    name = match[1].split()[0]
    if branch[1].split()[0] != name:
        raise ValueError('Rivet configured compiler probe and command disagree')
    found = shutil.which(name, path=environment.get('PATH', '/usr/bin:/bin'))
    selected = Path(found).absolute() if found else declared
    identity = executable_identity(selected)
    if identity['sha256'] != sources.digest(declared) or identity['resolved_path'] != str(declared.resolve()):
        raise ValueError('Rivet builder selects a different compiler than the bound compiler')
    return {'protocol': 'rivet-configured-alias-then-CXX', 'configured_name': name,
            'configured_command': branch[1], 'selection': 'configured' if found else 'CXX',
            'executable': identity, 'builder_sha256': sources.digest(build)}


def _rivet_python(tools, artifacts, environment):
    selected = tools.get('python')
    if selected is None:
        selected = shutil.which('python3', path=environment.get('PATH', '/usr/bin:/bin'))
    if selected is None:
        raise ValueError('Rivet loader custody requires a bound Python interpreter')
    selected = Path(selected).absolute()
    if selected.resolve() not in {p.resolve() for p in [*tools.values(), *artifacts]}:
        raise ValueError('Rivet loader Python must be an explicit runtime artifact or tool')
    return selected


def _execution_identity(recipe, tools, artifacts, environment):
    rivet = recipe['name'] == 'rivet-plugin'
    return {'tools': {k: executable_identity(p) for k, p in tools.items()},
            'compiler_selection': _rivet_compiler(tools['build'], tools['compiler'], environment) if rivet else None,
            'loader_python': executable_identity(_rivet_python(tools, artifacts, environment)) if rivet else None}


def seal_configuration(task, base):
    """Return a prospective config binding invocation aliases as actual inputs.

    The caller saves this new document before science planning/CHECK-IN 1; this
    function never modifies an input, launches a process or grants approval.
    """
    if _ma5_sfs_task(task, base):
        from ravel.physics import ma5_sfs_materialization
        return ma5_sfs_materialization.configuration(task, base)
    if _checkmate_task(task, base):
        from ravel.physics import checkmate_fritz_build
        return checkmate_fritz_build.configuration(task, base)[0]
    if _autotools_task(task, base):
        from ravel.physics import autotools_library_build
        return autotools_library_build.configuration(task, base)[0]
    if _native_container_task(task, base):
        from ravel.physics import simpleanalysis_build
        return json.loads(json.dumps(simpleanalysis_build._configuration(task, base)[0]))
    config, _, _, _, _, _, tools, artifacts = _configuration(task, base)
    sealed = json.loads(json.dumps(config))
    sealed['schema_version'] = 2
    sealed['execution_identity'] = _execution_identity(config['recipe'], tools, artifacts,
                                                       config['runtime']['environment'])
    return sealed


def rivet_loader_command(python, binary, routine, observation, executable='-', *arguments):
    """Wrap metadata or event CLI in one process with exact-plugin observation."""
    return [str(python), '-c', RIVET_LOADER_OBSERVER, str(binary), routine,
            str(observation), str(executable), *arguments]


def verify_loader_observation(observation, binary, routine, environment, directory, stdout, stderr_base64, *, registered_routines=None):
    """Require mapped image plus successful unambiguous canonical registration."""
    expected = {'path': str(Path(binary).resolve()), 'sha256': sources.digest(binary)}
    required = {'schema_version', 'kind', 'pid', 'cwd', 'environment', 'python', 'plugin_before',
                'plugin_after', 'images_before', 'images_after_import', 'images_after_load',
                'selected_plugins', 'registered_names', 'canonical_routine', 'runtime_version', 'physics_validated'}
    if not isinstance(observation, dict) or set(observation) != required or type(observation['schema_version']) is not int or observation['schema_version'] != 1 or observation['kind'] != 'rivet-loader-observation' or observation['physics_validated'] is not False:
        raise ValueError('invalid loaded-plugin observation')
    if type(observation['pid']) is not int or observation['pid'] <= 0 or observation['cwd'] != str(Path(directory).resolve()) or observation['environment'] != environment:
        raise ValueError('loaded-plugin process/environment binding differs')
    if observation['plugin_before'] != expected or observation['plugin_after'] != expected or observation['selected_plugins'] != [expected['path']]:
        raise ValueError('loaded-plugin identity differs from expected binary')
    for key in ('images_before', 'images_after_import', 'images_after_load', 'registered_names'):
        if not isinstance(observation[key], list) or any(not isinstance(p, str) for p in observation[key]):
            raise ValueError('loaded-plugin image/name inventory required')
    def plugins(paths):
        return [str(Path(p).resolve()) for p in paths if Path(p).name.startswith('Rivet') and p.endswith('.so')]
    if plugins(observation['images_before']) or plugins(observation['images_after_import']) or plugins(observation['images_after_load']) != [expected['path']]:
        raise ValueError('loaded-plugin image inventory is preloaded, ambiguous or wrong')
    if observation['canonical_routine'] != routine or routine not in observation['registered_names'] or not isinstance(observation['runtime_version'], str) or not observation['runtime_version']:
        raise ValueError('exact canonical routine registration required')
    if not isinstance(observation['python'], dict) or set(observation['python']) != {'path', 'sha256'}:
        raise ValueError('loaded-plugin interpreter identity required')
    _bound(observation['python'], '/', executable=True)
    text = stdout.decode('utf-8', errors='replace') + base64.b64decode(stderr_base64, validate=True).decode('utf-8', errors='replace')
    registered = re.findall(r"Registering a plugin analysis called '([^']+)'", text)
    attempted = re.findall(r'Trying to load plugin analyses from file ([^\r\n]+)', text)
    required_names = set(registered_routines or [routine])
    if routine not in required_names or not required_names <= set(observation['registered_names']) or any(registered.count(name) != 1 for name in required_names) or attempted != [expected['path']] or 'Ignoring duplicate plugin analysis' in text or 'Cannot open ' in text:
        raise ValueError('missing or ambiguous successful loader registration trace')
    if isinstance(registered_routines, dict):
        aliases = [alias for binding in registered_routines.values() for alias in binding.get('aliases', [])]
        observed_aliases = re.findall(r"Registering a plugin analysis via alias '([^']+)'", text)
        if len(aliases) != len(set(aliases)) or any(alias in required_names or observed_aliases.count(alias) != 1 for alias in aliases) or aliases and set(observed_aliases) != set(aliases):
            raise ValueError('missing or ambiguous source-bound alias registration trace')
    return {'status': 'passed', 'plugin': expected, 'routine': routine, 'pid': observation['pid'],
            'physics_validated': False, 'scope': 'Fresh-process mapped plugin and canonical registration; no detector or physics validation.'}


def verify_compiler_invocations(journal, plan, out):
    selection = plan['custody']['compiler_selection']
    identity = selection['executable']
    try:
        facts = [json.loads(line) for line in Path(journal).read_text().splitlines()]
    except (OSError, ValueError) as exc:
        raise ValueError('actual selected compiler invocation observation required') from exc
    if not facts:
        raise ValueError('selected compiler was not observed during build')
    expected_alias = str(Path(out) / 'work/compiler-observer' / Path(identity['path']).name)
    ordered_units = [str(Path(out) / 'work/source' / p) for p in plan['recipe']['compile_units']]
    units = set(ordered_units)
    expected_inputs = {str(Path(out) / 'work/source' / f['path']): f['sha256']
                       for f in plan['source_inventory']['files'] if f['path'] in plan['recipe']['compile_units']}
    seen = set()
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {'schema_version', 'pid', 'cwd', 'argv', 'invoked_alias', 'target', 'sha256', 'timestamp_ns', 'compile_inputs'} or type(fact['schema_version']) is not int or fact['schema_version'] != 2 or type(fact['pid']) is not int or fact['pid'] <= 0 or type(fact['timestamp_ns']) is not int or fact['timestamp_ns'] <= 0:
            raise ValueError('invalid selected compiler invocation')
        if fact['invoked_alias'] != expected_alias or fact['target'] != identity['resolved_path'] or fact['sha256'] != identity['sha256'] or not isinstance(fact['cwd'], str) or not isinstance(fact['argv'], list) or not fact['argv'] or any(not isinstance(arg, str) for arg in fact['argv']) or fact['argv'][0] != identity['path']:
            raise ValueError('invoked compiler differs from the bound effective compiler')
        inputs = fact['compile_inputs']
        argv_sources = [str((Path(fact['cwd']) / arg).absolute()) for arg in fact['argv'][1:]
                        if Path(arg).suffix in ('.cc', '.cxx', '.cpp', '.c')]
        if not isinstance(inputs, list) or any(not isinstance(f, dict) or set(f) != {'path', 'sha256', 'content_base64'} for f in inputs) or [f['path'] for f in inputs] != argv_sources or len(set(argv_sources)) != len(argv_sources):
            raise ValueError('invocation-time staged compiler inputs differ from source capsule')
        decoded = []
        for source in inputs:
            try:
                raw = base64.b64decode(source['content_base64'], validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError('invocation-time compiler source bytes required') from exc
            if hashlib.sha256(raw).hexdigest() != source['sha256']:
                raise ValueError('invocation-time compiler source digest differs')
            decoded.append(raw)
        if fact['cwd'] != str(Path(out) / 'work/build'):
            # Upstream rivet-build has one fixed linker feature test in /tmp.
            # Its harmless source and exact argument form are recognized; an
            # arbitrary out-of-work compiler input is never treated as a unit.
            flags = selection.get('configured_command', '').split()[1:] if selection.get('selection') == 'configured' else []
            probe_args = fact['argv'][1:]
            name = Path(inputs[0]['path']).name if len(inputs) == 1 else ''
            if (fact['cwd'] != str(Path('/tmp').resolve()) or not re.fullmatch(r'[0-9]+\.cc', name)
                    or probe_args != [*flags, '-Wl,--no-as-needed', name, '-o', name[:-3]]
                    or decoded != [b'int main() { return 0; }\n']):
                raise ValueError('compiler invocation outside bound build is not the upstream linker probe')
            continue
        for source, raw in zip(inputs, decoded):
            if source['path'] in units:
                if source['sha256'] != expected_inputs[source['path']]:
                    raise ValueError('invocation-time staged compiler inputs differ from source capsule')
                seen.add(source['path'])
            else:
                # With -j1 upstream compiles one generated concatenation, with
                # exact #line markers followed by the unchanged staged bytes.
                # Retain actual transient bytes, since upstream deletes them.
                generated = Path(source['path'])
                if generated.parent != Path(out) / 'work/build' or not re.fullmatch(r'tmp\.[A-Za-z0-9]+\.cc', generated.name):
                    raise ValueError('unbound generated compiler source')
                expected = b''
                for unit in ordered_units:
                    content = Path(unit).read_bytes()
                    if hashlib.sha256(content).hexdigest() != expected_inputs[unit]:
                        raise ValueError('staged source bytes differ from declared compiler input')
                    expected += b'\n#line 1 "' + os.fsencode(unit) + b'"\n' + content
                if raw != expected:
                    raise ValueError('generated compiler source differs from exact staged-unit concatenation')
                seen.update(units)
    if seen != units:
        raise ValueError('compiler observations omit a declared compile unit')
    return facts


def bound_routine(receipt, plan, out, routine):
    """Select a source-bound registered entry after receipt integrity rebind.

    Legacy receipts serve only their original primary. A secondary entry needs
    a literal declaration in an actual compiled unit and observed registration;
    matching an analysis name or installed catalogue entry alone is insufficient.
    """
    if plan.get('schema_version') == 3:
        from ravel.physics import simpleanalysis_build
        return simpleanalysis_build.bound_routine(receipt, plan, out, routine)
    if plan.get('schema_version', 1) == 1 and routine == plan['routine']:
        return {'registration': 'legacy-declared-primary',
                'source_files': plan['source_inventory']['files'], 'supporting_files': []}
    binding = plan.get('routine_bindings', {}).get(routine)
    if plan.get('schema_version') != 2 or receipt.get('schema_version') != 2 or not isinstance(binding, dict):
        raise ValueError('selected routine lacks source-bound observed build registration')
    if routine != plan['routine'] and (binding['registration'] not in ('literal-RIVET_DECLARE_PLUGIN', 'literal-RIVET_DECLARE_ALIASED_PLUGIN') or
            not binding['source_files'] or any(f['role'] != 'compile' or f['path'] not in plan['recipe']['compile_units'] for f in binding['source_files'])):
        raise ValueError('secondary routine needs a literal registration in its bound compiled source')
    observed = read_json(Path(out) / receipt['custody']['loader']['path'])
    if routine not in observed['registered_names']:
        raise ValueError('selected source-bound routine was not actually registered')
    return binding


def validate(task):
    if not isinstance(task, dict) or set(task) != {'backend', 'input'} or task['backend'] != 'routine-build' or not isinstance(task['input'], str) or not task['input']:
        raise ValueError('routine-build task needs exactly backend and input')


def _ma5_sfs_task(task, base):
    from ravel.physics import ma5_sfs_materialization
    return ma5_sfs_materialization.accepts(task, base)


def _checkmate_task(task, base):
    validate(task)
    config = read_json(regular(task['input'], base))
    return isinstance(config, dict) and config.get('schema_version') == 5 and config.get('kind') == 'checkmate252-supplied-fritz-build'


def _autotools_task(task, base):
    validate(task)
    config = read_json(regular(task['input'], base))
    return isinstance(config, dict) and config.get('schema_version') == 4


def _native_container_task(task, base):
    validate(task)
    config = read_json(regular(task['input'], base))
    return isinstance(config, dict) and config.get('schema_version') == 3


def _bound(fact, base, *, executable=False):
    if not isinstance(fact, dict) or set(fact) != {'path', 'sha256'} or not isinstance(fact['path'], str) or not fact['path']:
        raise ValueError('runtime fact needs exact path and SHA256')
    sources._hash(fact['sha256'])
    candidate = Path(base) / fact['path']
    # System executable aliases are resolved; the actual target is fingerprinted.
    path = candidate.absolute() if executable else regular(fact['path'], base)
    if not path.is_file() or sources.digest(path) != fact['sha256']:
        raise ValueError('runtime bytes differ from the declared identity: ' + fact['path'])
    if executable and not os.access(path, os.X_OK):
        raise ValueError('runtime tool is not executable: ' + fact['path'])
    return path


def _configuration(task, base):
    validate(task)
    config_path = regular(task['input'], base)
    config = read_json(config_path)
    version = config.get('schema_version') if isinstance(config, dict) else None
    fields = {'schema_version', 'source_capsule', 'recipe', 'runtime', 'probe'}
    if version == 2:
        fields.add('execution_identity')
    if isinstance(config,dict) and 'improvement_lineage' in config:
        fields.add('improvement_lineage')
    if not isinstance(config, dict) or set(config) != fields or type(version) is not int or version not in (1, 2):
        raise ValueError('invalid routine-build configuration version or fields')
    if not isinstance(config['source_capsule'], str) or not config['source_capsule']:
        raise ValueError('source capsule path required')
    capsule_path = regular(config['source_capsule'], base)
    capsule = sources.load_capsule(capsule_path)
    source_root, files = sources.source_files(capsule, base)
    marked=any(f['path']=='provenance/improvement-lineage.json' for f in capsule['files'])
    if marked != ('improvement_lineage' in config):
        raise ValueError('challenger source lineage cannot be omitted or added to unrelated source')
    if 'improvement_lineage' in config:
        from ravel.physics import native_incumbent
        native_incumbent.source_binding(config['improvement_lineage'],capsule,capsule_path.parent)
    if not capsule['dependency_review']['complete'] or any(d['status'] != 'resolved' for d in capsule['dependencies']):
        raise ValueError('unresolved declared transitive dependency obligations prevent building')
    if sources.dependency_cues(capsule, base)['onnx_model']:
        model_paths = {f['path'] for f in capsule['files'] if f['role'] == 'model'}
        asset_paths = {p for d in capsule['dependencies'] if d['kind'] == 'asset' for p in d['files']}
        if not model_paths or not model_paths <= asset_paths:
            raise ValueError('ONNX helper cue requires explicit bound model asset obligations')
    recipe = config['recipe']
    if not isinstance(recipe, dict) or set(recipe) != {'name', 'compile_units', 'output', 'flags'} or recipe['name'] not in RECIPES:
        raise ValueError('invalid closed build recipe')
    framework = {'cpp-executable': 'cpp', 'rivet-plugin': 'rivet', 'simpleanalysis-analysisbase': 'simpleanalysis'}[recipe['name']]
    if capsule['framework'] != framework:
        raise ValueError('build recipe differs from capsule framework')
    roles = {f['path']: f['role'] for f in capsule['files']}
    units = recipe['compile_units']
    if not isinstance(units, list) or not units or len(set(units)) != len(units) or any(roles.get(p) != 'compile' for p in units):
        raise ValueError('compile units must be unique declared compile files')
    sources.relative_path(recipe['output'])
    if not all(re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]*', part) for part in Path(recipe['output']).parts) or (recipe['name'] != 'simpleanalysis-analysisbase' and '/' in recipe['output']):
        raise ValueError('build output must be a safe basename or declared SimpleAnalysis build-relative path')
    if recipe['name'] == 'rivet-plugin' and not re.fullmatch('Rivet[A-Za-z0-9_]+\\.so', recipe['output']):
        raise ValueError('Rivet plugin output must be RivetNAME.so')
    if not isinstance(recipe['flags'], list) or len(set(recipe['flags'])) != len(recipe['flags']) or any(not isinstance(f, str) or not re.fullmatch(r'-std=c\+\+(?:11|14|17|20|23)|-O[0123]|-g|-Wall|-Wextra|-D[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_.+\-]+)?', f) for f in recipe['flags']):
        raise ValueError('unsupported compiler flag; use bound dependency configuration')
    runtime = config['runtime']
    if not isinstance(runtime, dict) or set(runtime) != {'tools', 'artifacts', 'environment'} or not isinstance(runtime['tools'], dict) or 'compiler' not in runtime['tools']:
        raise ValueError('runtime needs compiler, tools, artifacts and environment')
    allowed_tools = {'compiler', 'build', 'cmake', 'probe', 'python'}
    if set(runtime['tools']) - allowed_tools:
        raise ValueError('unknown build runtime tool')
    tools = {k: _bound(v, base, executable=True) for k, v in runtime['tools'].items()}
    if recipe['name'] == 'rivet-plugin' and 'build' not in tools:
        raise ValueError('Rivet recipe requires a bound build tool')
    if not isinstance(runtime['artifacts'], list):
        raise ValueError('explicit runtime artifact list required')
    artifacts = [_bound(f, base) for f in runtime['artifacts']]
    if len(set(artifacts)) != len(artifacts):
        raise ValueError('duplicate runtime artifact')
    environment = runtime['environment']
    if not isinstance(environment, dict) or set(environment) - ENVIRONMENT or any(not isinstance(v, str) or '\x00' in v for v in environment.values()):
        raise ValueError('unsupported build environment')
    if recipe['name'] == 'simpleanalysis-analysisbase':
        if 'cmake' not in tools or not any(p.name == 'AnalysisBaseConfig.cmake' for p in artifacts) or 'CMAKE_PREFIX_PATH' not in environment:
            raise ValueError('SimpleAnalysis requires pinned AnalysisBaseConfig.cmake, CMake and explicit CMAKE_PREFIX_PATH; portable hand-port tools are insufficient')
        if roles.get('CMakeLists.txt') != 'build' or not capsule['submodules']:
            raise ValueError('SimpleAnalysis requires declared root CMake and submodule content')
        if set(units) != {p for p, role in roles.items() if role == 'compile'}:
            raise ValueError('CMake recipe must declare all compile units in its staged source graph')
        if recipe['flags']:
            raise ValueError('SimpleAnalysis flags must come from the bound package configuration')
    probe = config['probe']
    if not isinstance(probe, dict) or set(probe) != {'executable', 'arguments', 'expected_exit_code', 'stdout_contains'} or probe['executable'] not in ({'$BUILD_OUTPUT'} | set(tools)):
        raise ValueError('probe executable must be built output or a bound runtime tool')
    if probe['executable'] == '$BUILD_OUTPUT' and recipe['name'] == 'rivet-plugin':
        raise ValueError('shared Rivet plugin must be probed through a bound runtime executable')
    if recipe['name'] == 'cpp-executable' and probe['executable'] != '$BUILD_OUTPUT':
        raise ValueError('executable build must probe the actual produced executable')
    if type(probe['expected_exit_code']) is not int or probe['expected_exit_code'] != 0:
        raise ValueError('build admission requires a successful runtime probe')
    for key in ('arguments', 'stdout_contains'):
        if not isinstance(probe[key], list) or any(not isinstance(v, str) or '\x00' in v for v in probe[key]):
            raise ValueError('probe arguments and expected text must be strings')
    if not probe['stdout_contains'] or any(not v for v in probe['stdout_contains']):
        raise ValueError('probe needs a nonempty declared output denominator')
    if recipe['name'] == 'rivet-plugin' and (probe['executable'] != 'probe' or capsule['routine'] not in probe['stdout_contains']):
        raise ValueError('Rivet probe requires a bound probe tool and exact declared routine output')
    if version == 2 and config['execution_identity'] != _execution_identity(recipe, tools, artifacts, environment):
        raise ValueError('prospectively sealed compiler/tool alias identity changed')
    return config, capsule, config_path, capsule_path, source_root, files, tools, artifacts


def inputs(task, base):
    if _ma5_sfs_task(task, base):
        from ravel.physics import ma5_sfs_materialization
        return ma5_sfs_materialization.inputs(task, base)
    if _checkmate_task(task, base):
        from ravel.physics import checkmate_fritz_build
        return checkmate_fritz_build.inputs(task, base)
    if _autotools_task(task, base):
        from ravel.physics import autotools_library_build
        return autotools_library_build.inputs(task, base)
    if _native_container_task(task, base):
        from ravel.physics import simpleanalysis_build
        return simpleanalysis_build.inputs(task, base)
    config, _, config_path, capsule_path, _, files, tools, artifacts = _configuration(task, base)
    selected = []
    if config['recipe']['name'] == 'rivet-plugin':
        selected = [Path(_rivet_compiler(tools['build'], tools['compiler'], config['runtime']['environment'])['executable']['resolved_path']),
                    _rivet_python(tools, artifacts, config['runtime']['environment']).resolve()]
    if 'improvement_lineage' in config:
        from ravel.physics import native_incumbent
        selected += native_incumbent.source_binding(config['improvement_lineage'],
            sources.load_capsule(capsule_path),capsule_path.parent)[1]
    return list(dict.fromkeys([config_path, capsule_path, *files, *[p.resolve() for p in tools.values()], *artifacts, *selected]))


def build_plan(task, base, out, *, _legacy=False):
    if _ma5_sfs_task(task, base):
        from ravel.physics import ma5_sfs_materialization
        if _legacy: raise ValueError('MA5 SFS source needs prospective materialization custody')
        return ma5_sfs_materialization.build_plan(task, base, out)
    if _checkmate_task(task, base):
        from ravel.physics import checkmate_fritz_build
        return checkmate_fritz_build.build_plan(task, base, out)
    if _autotools_task(task, base):
        if _legacy: raise ValueError('autotools bundle requires prospective custody')
        from ravel.physics import autotools_library_build
        return autotools_library_build.build_plan(task, base, out)
    if _native_container_task(task, base):
        if _legacy:
            raise ValueError('native container build cannot use legacy declaration-only admission')
        from ravel.physics import simpleanalysis_build
        return simpleanalysis_build.build_plan(task, base, out)
    config, capsule, cp, sp, source_root, files, tools, artifacts = _configuration(task, base)
    out = Path(out).resolve()
    work, build = out / 'work/source', out / 'work/build'
    output = build / config['recipe']['output']
    recipe = config['recipe']
    include_flags = ['-I' + str(work / d) for d in capsule['layout']['include_dirs']]
    compile_files = [str(work / p) for p in recipe['compile_units']]
    if recipe['name'] == 'cpp-executable':
        commands = [[str(tools['compiler']), *recipe['flags'], *include_flags, *compile_files, '-o', str(output)]]
    elif recipe['name'] == 'rivet-plugin':
        if any(c.isspace() for p in [str(out), *compile_files] for c in p):
            raise ValueError('upstream Rivet build protocol requires paths without whitespace')
        commands = [[str(tools['build']), '-j', '1', str(output), *compile_files, *include_flags, *recipe['flags']]]
    else:
        commands = [[str(tools['cmake']), '-S', str(work), '-B', str(build), '-DCMAKE_CXX_COMPILER=' + str(tools['compiler'])],
                    [str(tools['cmake']), '--build', str(build), '--parallel', '1', '--target', Path(recipe['output']).name]]
    probe = config['probe']
    executable = output if probe['executable'] == '$BUILD_OUTPUT' else tools[probe['executable']]
    probe_command = [str(executable), *probe['arguments']]
    runtime_identity = {'tools': {k: {'path': str(p), 'sha256': sources.digest(p)} for k, p in tools.items()},
                        'artifacts': [{'path': str(p), 'sha256': sources.digest(p)} for p in artifacts],
                        'environment': config['runtime']['environment']}
    result = {'schema_version': 1 if _legacy else 2, 'kind': 'routine-build-plan', 'recipe': recipe,
            'routine': capsule['routine'], 'framework': capsule['framework'],
            'base_dir': str(Path(base).resolve()), 'input': {'path': str(cp), 'sha256': sources.digest(cp)},
            'source_capsule': {'path': str(sp), 'sha256': sources.digest(sp)},
            'source_inventory': sources.inventory(capsule, base),
            'source_root': str(source_root), 'output_root': str(out),
            'binary': str(output.relative_to(out)), 'commands': commands,
            'probe_command': probe_command, 'probe_expectation': probe,
            'runtime_identity': runtime_identity, 'compute_authorized': False,
            'physics_validated': False,
            'scope': 'Declared dependency/layout build plan; source-booked routines need no reference YODA file.'}
    if not _legacy:
        result['routine_bindings'] = sources.routine_bindings(capsule, base, recipe['compile_units']) if capsule['framework'] == 'rivet' else {}
        result['runtime_identity']['tool_resolution'] = {k: executable_identity(p) for k, p in tools.items()}
        result['custody'] = {'staged_source': str(work), 'compiler_selection': None, 'loader': None,
                             'prospectively_sealed': config['schema_version'] == 2}
        if recipe['name'] == 'rivet-plugin':
            result['custody']['compiler_selection'] = _rivet_compiler(tools['build'], tools['compiler'], config['runtime']['environment'])
            result['custody']['compiler_observer_sha256'] = hashlib.sha256(COMPILER_OBSERVER.encode()).hexdigest()
            python = _rivet_python(tools, artifacts, config['runtime']['environment'])
            result['custody']['observer_python'] = executable_identity(python)
            result['custody']['loader'] = {'python': executable_identity(python),
                'observer_sha256': hashlib.sha256(RIVET_LOADER_OBSERVER.encode()).hexdigest(),
                'observation': 'loader-observation.json'}
            result['probe_command'] = rivet_loader_command(python, output, capsule['routine'],
                out / 'loader-observation.json', *probe_command)
    if 'improvement_lineage' in config:
        result['improvement_lineage']=config['improvement_lineage']
        result['prior_reviews_carried']=[]
    return result


def _process(command, directory, environment, log, *, work_deadline=None, max_seconds=120):
    started = datetime.now(timezone.utc).isoformat()
    if type(max_seconds) is not int or not 1 <= max_seconds <= 86400:
        raise ValueError('bounded native command ceiling required')
    timeout=max_seconds if work_deadline is None else min(max_seconds,work_deadline-time.monotonic())
    if timeout<=0:raise TimeoutError('native challenger build work deadline exhausted')
    try:
        result = subprocess.run(command, cwd=directory, env=environment, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as problem:
        # The failed operation must retain its partial raw observation before
        # propagation. No native exit code or guest/process quiescence is known.
        def captured(value):
            if value is None:
                return b'', 'unavailable'
            if type(value) is bytes:
                return value, 'bytes'
            if type(value) is str:
                return value.encode('utf-8', errors='surrogatepass'), 'text_utf8_surrogatepass'
            raise TypeError('unexpected TimeoutExpired output representation')
        stdout, stdout_kind = captured(problem.output)
        stderr, stderr_kind = captured(problem.stderr)
        atomic_json(log, {'schema_version': 2, 'command': command, 'returncode': None,
                          'cwd': str(Path(directory).resolve()), 'environment': dict(environment),
                          'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
                          'stdout_base64': base64.b64encode(stdout).decode('ascii'),
                          'stderr_base64': base64.b64encode(stderr).decode('ascii'),
                          'timed_out': True, 'timeout_seconds': timeout,
                          'stdout_capture_kind': stdout_kind, 'stderr_capture_kind': stderr_kind,
                          'native_process_quiescence_established': False})
        raise
    stdout = result.stdout
    atomic_json(log, {'schema_version': 2, 'command': command, 'returncode': result.returncode,
                      'cwd': str(Path(directory).resolve()), 'environment': dict(environment),
                      'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
                      'stdout_base64': base64.b64encode(stdout).decode('ascii'),
                      'stderr_base64': base64.b64encode(result.stderr).decode('ascii')})
    if result.returncode:
        raise ValueError('routine build/probe failed; inspect ' + Path(log).name)
    return result.returncode, stdout


def isolated_process_environment(home, temporary):
    """Closed launch defaults, including Python's otherwise implicit locale.

    Python may coerce an absent or C LC_CTYPE to C.UTF-8 at startup. Declare
    the portable C locale and UTF-8 Python mode before exec, retaining exact
    launch/observed environment equality instead of accepting added variables.
    """
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(temporary),
            'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
            'LC_ALL': 'C', 'LC_CTYPE': 'C', 'PYTHONCOERCECLOCALE': '0', 'PYTHONUTF8': '1'}
    if sys.platform == 'darwin':
        # Framework Python initializes CoreFoundation, which otherwise adds
        # this user/text-encoding setting even to a closed launch environment.
        environment['__CF_USER_TEXT_ENCODING'] = f'0x{os.getuid():X}:0x0:0x0'
    return environment


def execution_environment(plan, out, phase):
    """Complete deterministic environment retained by each actual subprocess."""
    out = Path(out).resolve()
    work = out / 'work/source'
    env = isolated_process_environment(out / 'work/home', out / 'work/tmp')
    env.update(plan['runtime_identity']['environment'])
    env['CXX'] = plan['runtime_identity']['tools']['compiler']['path']
    if phase != 'compiler' and plan['framework'] == 'rivet':
        selection = plan['custody']['compiler_selection']
        observer_dir = out / 'work/compiler-observer'
        env.update(PATH=str(observer_dir) + os.pathsep + env['PATH'],
                   RAVEL_COMPILER_TARGET=selection['executable']['path'],
                   RAVEL_COMPILER_JOURNAL=str(out / 'compiler-invocations.jsonl'))
        if selection['selection'] == 'CXX':
            env['CXX'] = str(observer_dir / Path(selection['executable']['path']).name)
    if phase == 'probe' and plan['framework'] == 'rivet':
        assets = os.pathsep.join(str(work / d) for d in plan['source_inventory']['layout']['asset_dirs']) or str(work)
        env.update(RIVET_ANALYSIS_PLUGINS=str(out / plan['binary']), RIVET_ANALYSIS_PATH=str(work),
                   RIVET_INFO_PATH=assets, RIVET_REF_PATH=assets, RIVET_DATA_PATH=assets)
    return env


def execution_seconds(task,base):
    if _ma5_sfs_task(task, base):
        from ravel.physics import ma5_sfs_materialization
        return ma5_sfs_materialization.execution_seconds(task, base)
    if _checkmate_task(task, base):
        from ravel.physics import checkmate_fritz_build
        return checkmate_fritz_build.execution_seconds(task, base)
    if _autotools_task(task, base):
        from ravel.physics import autotools_library_build
        return autotools_library_build.execution_seconds(task, base)
    if _native_container_task(task,base):return 1
    config,*_=_configuration(task,base)
    if 'improvement_lineage' not in config:return 1
    from ravel.physics import native_incumbent
    commands=2 if config['recipe']['name']=='cmake-target' else 1
    return native_incumbent.execution_seconds(config['improvement_lineage'],base,120*(commands+2))


def run(task, base, out, *, worker_started=None):
    if _ma5_sfs_task(task, base):
        from ravel.physics import ma5_sfs_materialization
        return ma5_sfs_materialization.run(task, base, out, worker_started=worker_started)
    if _checkmate_task(task, base):
        from ravel.physics import checkmate_fritz_build
        return checkmate_fritz_build.run(task, base, out, worker_started=worker_started)
    if _autotools_task(task, base):
        from ravel.physics import autotools_library_build
        return autotools_library_build.run(task, base, out, worker_started=worker_started)
    if _native_container_task(task, base):
        from ravel.physics import simpleanalysis_build
        return simpleanalysis_build.run(task, base, out)
    from ravel.physics import native_incumbent
    started=native_incumbent.worker_start(worker_started)
    plan = build_plan(task, base, out)
    boundary=None
    if 'improvement_lineage' in plan:
        from ravel.physics import native_incumbent
        boundary=native_incumbent.WorkerBoundary(plan['improvement_lineage'],base,out,
            work_seconds=120*(len(plan['commands'])+2),worker_started=started)
    deadline=None if boundary is None else boundary.work_deadline
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work, build = out / 'work/source', out / 'work/build'
    work.mkdir(parents=True, exist_ok=False)
    build.mkdir(exist_ok=False)
    for fact in plan['source_inventory']['files']:
        src = Path(plan['source_root']) / fact['path']
        target = work / fact['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        if sources.digest(target) != fact['sha256']:
            raise ValueError('source changed while staging')
    atomic_json(out / 'source-inventory.json', plan['source_inventory'])
    atomic_json(out / 'build-plan.json', plan)
    staged_before = sources.staged_inventory(plan['source_inventory'], work)
    # Avoid inherited credentials and ambient compiler/runtime flags. This is not
    # an OS sandbox: arbitrary supplied C++/CMake still needs a trusted worker.
    env = isolated_process_environment(out / 'work/home', out / 'work/tmp')
    Path(env['HOME']).mkdir(); Path(env['TMPDIR']).mkdir()
    env.update(plan['runtime_identity']['environment'])
    env['CXX'] = plan['runtime_identity']['tools']['compiler']['path']
    _, compiler_version = _process([env['CXX'], '--version'], build, env, out / 'compiler.log',**({} if deadline is None else {'work_deadline':deadline}))
    if plan['framework'] == 'rivet':
        selection = plan['custody']['compiler_selection']
        alias = Path(selection['executable']['path']).name
        observer_dir = out / 'work/compiler-observer'
        observer_dir.mkdir()
        observer = observer_dir / alias
        observer.write_text('#!' + plan['custody']['observer_python']['path'] + '\n' + COMPILER_OBSERVER)
        observer.chmod(0o755)
        env['PATH'] = str(observer_dir) + os.pathsep + env['PATH']
        env['RAVEL_COMPILER_TARGET'] = selection['executable']['path']
        env['RAVEL_COMPILER_JOURNAL'] = str(out / 'compiler-invocations.jsonl')
        if selection['selection'] == 'CXX':
            env['CXX'] = str(observer)
    for i, command in enumerate(plan['commands']):
        _process(command, build, env, out / f'build-{i}.log',**({} if deadline is None else {'work_deadline':deadline}))
    binary = out / plan['binary']
    if binary.is_symlink() or not binary.is_file() or binary.stat().st_size == 0:
        raise ValueError('build did not produce the declared ordinary output binary')
    probe_env = dict(env)
    if plan['framework'] == 'rivet':
        probe_env.update(RIVET_ANALYSIS_PLUGINS=str(binary), RIVET_ANALYSIS_PATH=str(work),
                         RIVET_INFO_PATH=os.pathsep.join(str(work / d) for d in plan['source_inventory']['layout']['asset_dirs']) or str(work),
                         RIVET_REF_PATH=os.pathsep.join(str(work / d) for d in plan['source_inventory']['layout']['asset_dirs']) or str(work),
                         RIVET_DATA_PATH=os.pathsep.join(str(work / d) for d in plan['source_inventory']['layout']['asset_dirs']) or str(work))
    # The requested metadata probe and the loaded-image observation share one
    # fresh process. This also prevents inherited first-registration state.
    code, stdout = _process(plan['probe_command'], build, probe_env, out / 'probe.log',**({} if deadline is None else {'work_deadline':deadline}))
    if any(s not in stdout.decode('utf-8', errors='replace') for s in plan['probe_expectation']['stdout_contains']):
        raise ValueError('runtime probe omitted declared expected output')
    # Re-read and rebind inputs after subprocesses, not only before planning.
    current = build_plan(task, base, out)
    if current != plan:
        raise ValueError('source or runtime changed during build/probe')
    for fact in plan['source_inventory']['files']:
        _bound({'path': str(work / fact['path']), 'sha256': fact['sha256']}, out)
    staged_after = sources.staged_inventory(plan['source_inventory'], work)
    if staged_before != staged_after:
        raise ValueError('actual staged compilation inputs changed during execution')
    atomic_json(out / 'staged-source.json', {'schema_version': 1, 'before': staged_before,
                'after': staged_after, 'source_inventory_sha256': sources.digest(out / 'source-inventory.json')})
    log_names = ['compiler.log', *[f'build-{i}.log' for i in range(len(plan['commands']))], 'probe.log']
    custody = {'staged_source': {'path': 'staged-source.json', 'sha256': sources.digest(out / 'staged-source.json')}}
    if plan['framework'] == 'rivet':
        verify_compiler_invocations(out / 'compiler-invocations.jsonl', plan, out)
        verify_loader_observation(read_json(out / 'loader-observation.json'), binary, plan['routine'],
                                  probe_env, build, stdout, read_json(out / 'probe.log')['stderr_base64'],
                                  registered_routines=plan['routine_bindings'])
        custody.update(compiler_invocations={'path': 'compiler-invocations.jsonl', 'sha256': sources.digest(out / 'compiler-invocations.jsonl')},
                       loader={'path': 'loader-observation.json', 'sha256': sources.digest(out / 'loader-observation.json')})
    receipt = {'schema_version': 2, 'kind': 'routine-build-receipt', 'status': 'passed',
               'routine': plan['routine'], 'framework': plan['framework'], 'recipe': plan['recipe']['name'],
               'source_capsule_sha256': plan['source_capsule']['sha256'],
               'source_inventory_sha256': sources.digest(out / 'source-inventory.json'),
               'build_plan_sha256': sources.digest(out / 'build-plan.json'),
               'binary': {'path': plan['binary'], 'sha256': sources.digest(binary)},
               'commands': plan['commands'], 'probe_command': plan['probe_command'],
               'logs': {name: {'path': name, 'sha256': sources.digest(out / name)} for name in log_names},
               'observed': {'build_exit_code': 0, 'probe_exit_code': code,
                            'probe_stdout_sha256': hashlib.sha256(stdout).hexdigest(),
                            'compiler_version': compiler_version.decode('utf-8', errors='replace')},
               'runtime_identity': plan['runtime_identity'], 'custody': custody, 'physics_validated': False,
               'limitations': ['Declared file/dependency closure only; dynamic/transitive completeness is a supplied review.',
                               'Receipt records local process observation, not authenticated external execution or a hermetic OS image.',
                               'An executable/listing probe is not event execution, detector calibration, reference agreement or inference admission.']}
    if 'improvement_lineage' in plan:
        receipt['improvement_lineage']=plan['improvement_lineage']
        receipt['prior_reviews_carried']=[]
    if boundary is not None:
        proof=boundary.finish()
        if proof is not None:receipt['historical_qualification']=proof
    atomic_json(out / 'build-receipt.json', receipt)
    return receipt


def verify_receipt(receipt, plan, base, outroot):
    """Read-only rebind of delivered build evidence; never run compiler or probe.

    This establishes retained evidence integrity, not authenticity of an arbitrary
    caller's supplied process-observation assertions. Lifecycle custody is separate.
    """
    if isinstance(receipt, dict) and receipt.get('schema_version') == 6:
        from ravel.physics import ma5_sfs_materialization
        return ma5_sfs_materialization.verify_receipt(receipt, plan, base, outroot)
    if isinstance(receipt, dict) and receipt.get('schema_version') == 5:
        from ravel.physics import checkmate_fritz_build
        return checkmate_fritz_build.verify_receipt(receipt, plan, base, outroot)
    if isinstance(receipt, dict) and receipt.get('schema_version') == 4:
        from ravel.physics import autotools_library_build
        return autotools_library_build.verify_receipt(receipt, plan, base, outroot)
    if isinstance(receipt, dict) and receipt.get('schema_version') == 3:
        from ravel.physics import simpleanalysis_build
        return simpleanalysis_build.verify_receipt(receipt, plan, base, outroot)
    out = Path(outroot).resolve()
    required = {'schema_version', 'kind', 'status', 'routine', 'framework', 'recipe',
                'source_capsule_sha256', 'source_inventory_sha256', 'build_plan_sha256',
                'binary', 'commands', 'probe_command', 'logs', 'observed',
                'runtime_identity', 'physics_validated', 'limitations'}
    version = receipt.get('schema_version') if isinstance(receipt, dict) else None
    if version == 2:
        required.add('custody')
    if 'improvement_lineage' in plan:
        required |= {'improvement_lineage','prior_reviews_carried'}
        from ravel.physics import native_incumbent
        parent=native_incumbent.validate_lineage(plan['improvement_lineage'],base)
        if parent['parent_qualification'] is not None:
            required.add('historical_qualification')
            native_incumbent.verify_worker_boundaries(plan['improvement_lineage'],
                receipt.get('historical_qualification'),base,out)
            if receipt['historical_qualification']['selected_work_seconds_ceiling']!=120*(len(plan['commands'])+2):
                raise ValueError('observed challenger build selected branch budget differs')
        if receipt.get('improvement_lineage')!=plan['improvement_lineage'] or receipt.get('prior_reviews_carried')!=[]:
            raise ValueError('challenger build must retain lineage without old votes')
    if not isinstance(receipt, dict) or set(receipt) != required or type(version) is not int or version not in (1, 2) or receipt['kind'] != 'routine-build-receipt' or receipt['status'] != 'passed' or receipt['physics_validated'] is not False or plan.get('schema_version') != version:
        raise ValueError('invalid observed routine-build receipt')
    if sources.digest(out / 'build-plan.json') != receipt['build_plan_sha256'] or read_json(out / 'build-plan.json') != plan:
        raise ValueError('build plan differs from receipt')
    task = {'backend': 'routine-build', 'input': plan['input']['path']}
    if build_plan(task, base, out, _legacy=version == 1) != plan:
        raise ValueError('source/runtime inputs differ from observed build plan')
    if sources.digest(out / 'source-inventory.json') != receipt['source_inventory_sha256'] or read_json(out / 'source-inventory.json') != plan['source_inventory']:
        raise ValueError('source inventory differs from receipt')
    checks = {'routine': plan['routine'], 'framework': plan['framework'], 'recipe': plan['recipe']['name'],
              'source_capsule_sha256': plan['source_capsule']['sha256'], 'commands': plan['commands'],
              'probe_command': plan['probe_command'], 'runtime_identity': plan['runtime_identity']}
    if any(receipt[k] != v for k, v in checks.items()):
        raise ValueError('receipt identity/commands differ from build plan')
    if not isinstance(receipt['binary'], dict) or set(receipt['binary']) != {'path', 'sha256'} or receipt['binary']['path'] != plan['binary']:
        raise ValueError('binary output differs from plan')
    _bound(receipt['binary'], out)
    expected_logs = {'compiler.log', *{f'build-{i}.log' for i in range(len(plan['commands']))}, 'probe.log'}
    if not isinstance(receipt['logs'], dict) or set(receipt['logs']) != expected_logs:
        raise ValueError('complete observed build/probe logs required')
    for name, fact in receipt['logs'].items():
        if fact['path'] != name:
            raise ValueError('log identity differs from receipt')
        _bound(fact, out)
    observed = receipt['observed']
    if not isinstance(observed, dict) or set(observed) != {'build_exit_code', 'probe_exit_code', 'probe_stdout_sha256', 'compiler_version'} or type(observed['build_exit_code']) is not int or type(observed['probe_exit_code']) is not int or observed['build_exit_code'] != 0 or observed['probe_exit_code'] != 0:
        raise ValueError('successful observed build/probe return codes required')
    sources._hash(observed['probe_stdout_sha256'])
    if not isinstance(observed['compiler_version'], str) or not observed['compiler_version'].strip():
        raise ValueError('actual compiler observation required')
    commands = {'compiler.log': [plan['runtime_identity']['tools']['compiler']['path'], '--version'],
                **{f'build-{i}.log': command for i, command in enumerate(plan['commands'])},
                'probe.log': plan['probe_command']}
    for name, command in commands.items():
        log = read_json(out / name)
        fields = {'schema_version', 'command', 'returncode', 'stdout_base64', 'stderr_base64'}
        if version == 2:
            fields |= {'cwd', 'environment', 'started_at', 'finished_at'}
        if not isinstance(log, dict) or set(log) != fields or log['schema_version'] != version or log['command'] != command or type(log['returncode']) is not int or log['returncode'] != 0:
            raise ValueError('observed process log differs from the declared successful command')
        if version == 2:
            expected_env = execution_environment(plan, out, 'compiler' if name == 'compiler.log' else 'probe' if name == 'probe.log' else 'build')
            if log['cwd'] != str(out / 'work/build') or log['environment'] != expected_env:
                raise ValueError('observed process cwd/environment differs from build custody')
            try:
                started, finished = [datetime.fromisoformat(log[k]) for k in ('started_at', 'finished_at')]
                if started.tzinfo is None or finished.tzinfo is None or finished < started:
                    raise ValueError('invalid time order')
            except (ValueError, TypeError) as exc:
                raise ValueError('process observation timestamps required') from exc
        try:
            stdout = base64.b64decode(log['stdout_base64'], validate=True)
            base64.b64decode(log['stderr_base64'], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid raw process observation') from exc
        if name == 'compiler.log' and stdout.decode('utf-8', errors='replace') != observed['compiler_version']:
            raise ValueError('compiler observation differs from receipt')
        if name == 'probe.log' and (hashlib.sha256(stdout).hexdigest() != observed['probe_stdout_sha256'] or any(s not in stdout.decode('utf-8', errors='replace') for s in plan['probe_expectation']['stdout_contains'])):
            raise ValueError('probe observation differs from receipt or expected output')
    for fact in plan['source_inventory']['files']:
        _bound({'path': str(out / 'work/source' / fact['path']), 'sha256': fact['sha256']}, out)
    if version == 2:
        custody = receipt['custody']
        keys = {'staged_source'} | ({'compiler_invocations', 'loader'} if plan['framework'] == 'rivet' else set())
        if not isinstance(custody, dict) or set(custody) != keys:
            raise ValueError('complete routine-build custody observations required')
        names = {'staged_source': 'staged-source.json', 'compiler_invocations': 'compiler-invocations.jsonl', 'loader': 'loader-observation.json'}
        for key, fact in custody.items():
            if fact.get('path') != names[key]:
                raise ValueError('custody observation path differs')
            _bound(fact, out)
        staged = read_json(out / 'staged-source.json')
        expected = sources.staged_inventory(plan['source_inventory'], out / 'work/source')
        if staged != {'schema_version': 1, 'before': expected, 'after': expected, 'source_inventory_sha256': receipt['source_inventory_sha256']}:
            raise ValueError('staged compilation input observations differ')
        if plan['framework'] == 'rivet':
            observer = out / 'work/compiler-observer' / Path(plan['custody']['compiler_selection']['executable']['path']).name
            expected_source = '#!' + plan['custody']['observer_python']['path'] + '\n' + COMPILER_OBSERVER
            if observer.is_symlink() or not observer.is_file() or observer.read_text() != expected_source:
                raise ValueError('compiler observer source differs from the bound implementation')
            verify_compiler_invocations(out / 'compiler-invocations.jsonl', plan, out)
            log = read_json(out / 'probe.log')
            observation = read_json(out / 'loader-observation.json')
            python = plan['custody']['loader']['python']
            if observation['python'] != {'path': python['resolved_path'], 'sha256': python['sha256']}:
                raise ValueError('loader interpreter differs from bound runtime')
            verify_loader_observation(observation, out / plan['binary'], plan['routine'],
                log['environment'], log['cwd'], base64.b64decode(log['stdout_base64'], validate=True), log['stderr_base64'],
                registered_routines=plan['routine_bindings'])
    return {'status': 'passed', 'routine': plan['routine'], 'binary_sha256': receipt['binary']['sha256'],
            'custody': 'observed-selected-compiler-staged-source-and-loader' if version == 2 and plan['framework'] == 'rivet' else 'observed-staged-source' if version == 2 else 'legacy-declared-evidence-only',
            'prospectively_sealed': bool(version == 2 and plan['custody']['prospectively_sealed']),
            'physics_validated': False, 'scope': 'Retained source/runtime/build/probe evidence integrity; process authenticity and physics admission are separate.'}


def run_in_worker(task,base,out,*,worker_started):
    """The ordinary science worker supplies its common pre-admission clock."""
    return run(task,base,out,worker_started=worker_started)
