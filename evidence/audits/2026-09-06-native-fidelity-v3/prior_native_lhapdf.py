"""Preserve an activated macOS Fortran link environment's LHAPDF C++ runtime.

This preparation helper does not edit a toolchain, choose a PDF or run MadGraph.
The caller must invoke it inside the exact conda environment used by MadGraph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess


def probe(command):
    return subprocess.run(list(map(str, command)), check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=30).stdout.strip()


def pin(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def cxx_runtime(dependencies):
    """Use the linked library's actual dependency, never the machine name alone."""
    found = set()
    for line in dependencies.splitlines()[1:]:
        path = line.strip().split(' (compatibility version ', 1)[0]
        name = Path(path).name
        if re.fullmatch(r'libc\+\+(?:\.\d+)*\.dylib', name):
            found.add('c++')
        elif re.fullmatch(r'libstdc\+\+(?:\.\d+)*\.dylib', name):
            found.add('stdc++')
    if len(found) != 1:
        raise ValueError('LHAPDF must identify exactly one supported C++ runtime dependency')
    return next(iter(found))


def linker_arguments(flags):
    """Expand GCC forwarding into one ordered stream, without rewriting flags.

    -Xlinker forwards exactly one following token; -Wl, forwards comma-separated
    tokens. Argument pairing therefore takes place after expansion, including
    pairs split between different forwarding forms. Opaque/unknown linker syntax
    is rejected below; this is deliberately not a general compiler driver.
    """
    if not isinstance(flags, str) or any(c in flags for c in '\x00\r\n'):
        raise ValueError('LDFLAGS must be one valid environment string')
    tokens = shlex.split(flags)
    arguments, compiler_runtimes = [], set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token:
            raise ValueError('Empty linker argument is unsupported')
        if token == '-Xlinker':
            index += 1
            if index == len(tokens) or not tokens[index]:
                raise ValueError('Missing -Xlinker argument')
            arguments.append(tokens[index])
        elif token.startswith('-Wl,'):
            pieces = token[4:].split(',')
            if not all(pieces):
                raise ValueError('Empty -Wl argument is unsupported')
            arguments.extend(pieces)
        elif token in ('-l', '-L', '-F'):
            # A driver option consumes its own immediate operand, not a later
            # operand recovered by stripping a forwarding wrapper.
            index += 1
            if index == len(tokens) or not tokens[index] or tokens[index].startswith('-'):
                raise ValueError('Missing direct compiler option argument')
            arguments.extend((token, tokens[index]))
        elif token in ('-stdlib=libc++', '-stdlib=libstdc++'):
            compiler_runtimes.add(token.removeprefix('-stdlib=lib'))
        else:
            arguments.append(token)
        index += 1
    return arguments, compiler_runtimes


def runtime_selection(flags):
    """Validate the supported link grammar and classify explicit runtime links."""
    arguments, compiler_runtimes = linker_arguments(flags)
    explicit = set()
    switches = {'-headerpad_max_install_names', '-dead_strip_dylibs', '-dead_strip',
                '-search_paths_first', '-search_dylibs_first', '-no_compact_unwind',
                '-fatal_warnings', '-no_warn_duplicate_libraries'}
    one_operand = {'-L', '-F', '-rpath', '-syslibroot', '-framework', '-weak_framework'}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token.startswith(('-lazy_', '-load_', '-lto_')):
            raise ValueError('Unsupported linker loading directive: ' + token)
        if token in one_operand or token == '-l':
            index += 1
            if index == len(arguments) or not arguments[index] or arguments[index].startswith(('-', '@')):
                raise ValueError('Missing or unsupported linker option argument')
            operand = arguments[index]
            if token == '-l':
                if not re.fullmatch(r'[A-Za-z0-9_+.-]+', operand):
                    raise ValueError('Unsupported library-name syntax')
                match = re.fullmatch(r'(c\+\+|stdc\+\+)(?:\.\d+)*', operand)
                if match:
                    explicit.add(match[1])
        elif token.startswith('-l') and re.fullmatch(r'-l[A-Za-z0-9_+.-]+', token):
            match = re.fullmatch(r'-l(c\+\+|stdc\+\+)(?:\.\d+)*', token)
            if match:
                explicit.add(match[1])
        elif token in switches or token.startswith(('-L', '-F')) and len(token) > 2:
            pass
        elif not token.startswith(('-', '@')) and Path(token).suffix in ('.dylib', '.a'):
            match = re.fullmatch(r'lib(c\+\+|stdc\+\+)(?:\.\d+)*\.(?:dylib|a)', Path(token).name)
            if match:
                explicit.add(match[1])
        else:
            raise ValueError('Unsupported or opaque linker argument: ' + token)
        index += 1
    return {'linker_arguments': arguments, 'compiler_runtimes': sorted(compiler_runtimes),
            'explicit_runtimes': sorted(explicit)}


def existing_runtimes(flags):
    parsed = runtime_selection(flags)
    return set(parsed['compiler_runtimes']) | set(parsed['explicit_runtimes'])


def linker_environment(prefix, *, environment=None, system=None, architecture=None, run=probe):
    """Return a copied environment and a source-bound preparation record.

    Only Darwin with an explicitly defined LDFLAGS receives a possible addition.
    With LDFLAGS absent, MadGraph's own default remains responsible for its
    STDLIB and MACFLAG choices. Other operating systems remain outside this fix.
    """
    original = dict(os.environ if environment is None else environment)
    result = dict(original)
    system = platform.system() if system is None else system
    record = {'schema_version': 1, 'system': system, 'changed': False,
              'original_ldflags': original.get('LDFLAGS'),
              'effective_ldflags': original.get('LDFLAGS'), 'added_tokens': [],
              'reader': pin(__file__),
              'scope': 'Link preparation only; no generation or physics certification.'}
    if system != 'Darwin':
        record['status'] = 'outside_darwin_fix'
        return result, record
    prefix = Path(prefix).resolve(strict=True)
    active = original.get('CONDA_PREFIX')
    if not active or Path(active).resolve(strict=True) != prefix:
        raise ValueError('Run LHAPDF link preparation inside the exact selected conda prefix')
    architecture = platform.machine() if architecture is None else architecture
    if architecture not in ('arm64', 'x86_64'):
        raise ValueError('Unsupported macOS architecture')
    if architecture == 'x86_64':
        translated = run(['sysctl', '-in', 'sysctl.proc_translated'])
        silicon = run(['sysctl', '-in', 'hw.optional.arm64'])
        if translated not in ('', '0') or silicon not in ('', '0'):
            raise ValueError('Translated macOS execution cannot establish a native toolchain')
    config = prefix / 'bin/lhapdf-config'
    if not config.resolve(strict=True).is_relative_to(prefix):
        raise ValueError('lhapdf-config resolves outside the selected prefix')
    if Path(run([config, '--prefix'])).resolve(strict=True) != prefix:
        raise ValueError('lhapdf-config belongs to another prefix')
    libdir = Path(run([config, '--libdir'])).resolve(strict=True)
    if not libdir.is_relative_to(prefix):
        raise ValueError('LHAPDF library directory is outside the selected prefix')
    library = (libdir / 'libLHAPDF.dylib').resolve(strict=True)
    if not library.is_relative_to(prefix):
        raise ValueError('LHAPDF library resolves outside the selected prefix')
    architectures = run(['lipo', '-archs', library]).split()
    if architecture not in architectures:
        raise ValueError('LHAPDF architecture differs from the native process')
    runtime = cxx_runtime(run(['otool', '-L', library]))
    record.update(prefix=str(prefix), architecture=architecture,
                  library_architectures=architectures, runtime=runtime,
                  sources=[pin(config), pin(library)])
    if 'LDFLAGS' not in original:
        record['status'] = 'madgraph_default_ldflags_preserved'
        return result, record
    flags = original['LDFLAGS']
    if not isinstance(flags, str) or any(character in flags for character in '\x00\r\n'):
        raise ValueError('LDFLAGS must be one valid environment string')
    parsed = runtime_selection(flags)
    record['parsed_linker_flags'] = parsed
    found = set(parsed['compiler_runtimes']) | set(parsed['explicit_runtimes'])
    if found - {runtime}:
        raise ValueError('LDFLAGS selects a conflicting C++ runtime')
    # An explicit -stdlib option is not a Fortran linker -l argument. Append the
    # required library unless a recognized explicit runtime link already exists.
    if runtime not in parsed['explicit_runtimes']:
        token = '-l' + runtime
        result['LDFLAGS'] = flags + (' ' if flags else '') + token
        record.update(changed=True, effective_ldflags=result['LDFLAGS'], added_tokens=[token])
    record['status'] = 'explicit_runtime_link_preserved_or_added'
    return result, record


# The activated-generation contract below is deliberately restricted to the
# local Darwin NNPDF30 central-member workflow. It performs metadata I/O only.
GENERATION_POLICY = 'preserve-activated-v1'
PDF_SET = 'NNPDF30_nlo_as_0118'
PDF_ID = 260000
CONTEXT_KEYS = ('PATH', 'HOME', 'CONDA_PREFIX', 'LDFLAGS', 'LDFLAGS_LD', 'SDKROOT',
                'CONDA_BUILD_SYSROOT', 'CC', 'CXX', 'CPP', 'FC', 'F77', 'F90',
                'F95', 'AR', 'RANLIB', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS',
                'FFLAGS', 'FORTRANFLAGS', 'MACOSX_DEPLOYMENT_TARGET',
                'LHAPDF_DATA_PATH', 'PYTHONDONTWRITEBYTECODE',
                'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH')
FORBIDDEN_ENV = ('MAKEFLAGS', 'MFLAGS', 'GNUMAKEFLAGS', 'BASH_ENV', 'ENV',
                 'LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'CPATH',
                 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH',
                 'LIBRARY_PATH', 'PYTHONPATH', 'MADGRAPH_BASE', 'MG5DIR', 'MG5AMC',
                 'GFORTRAN_UNBUFFERED_ALL', 'COMPILER_PATH', 'GCC_EXEC_PREFIX')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def read_decision(path):
    from ravel.workflow.state_io import read_json
    result = read_json(path)
    if not isinstance(result, dict):
        raise ValueError('LHAPDF decision must be an object')
    return result


def _required_file(path, owner=None):
    original = Path(path)
    if not original.is_absolute():
        raise ValueError('Source path must be absolute')
    path = original.resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('Required source is missing or empty: ' + str(path))
    if owner is not None and not path.is_relative_to(Path(owner).resolve(strict=True)):
        raise ValueError('Source resolves outside its declared owner: ' + str(path))
    return path


def _absolute_link_paths(parsed):
    args = parsed['linker_arguments']; index = 0
    path_options = {'-L', '-F', '-rpath', '-syslibroot'}
    while index < len(args):
        token = args[index]
        value = None
        if token in path_options:
            index += 1; value = args[index]
        elif token.startswith(('-L', '-F')) and len(token) > 2:
            value = token[2:]
        elif token in ('-l', '-framework', '-weak_framework'):
            index += 1
        elif not token.startswith('-') and Path(token).suffix in ('.dylib', '.a'):
            value = token
        if value is not None and not Path(value).is_absolute():
            raise ValueError('Relative link path changes meaning in a fresh MG attempt')
        index += 1


def _metadata_pairs(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if ':' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.split(':', 1); key = key.strip()
        if key in result:
            raise ValueError('Duplicate PDF metadata field: ' + key)
        result[key] = value.strip().strip('"\'')
    return result


def generation_decision(prefix, *, environment=None, run=probe, system=None,
                        architecture=None, python_executable=None):
    """Inspect an already activated environment; never import or launch MG."""
    import shutil
    import sys
    env = dict(os.environ if environment is None else environment)
    if env.get('PYTHONDONTWRITEBYTECODE') != '1':
        raise ValueError('Activated decision requires inherited bytecode suppression')
    if any(env.get(k) not in (None, '') for k in FORBIDDEN_ENV):
        raise ValueError('Unsupported build/import environment override')
    for name, value in env.items():
        if (value not in (None, '') and name.startswith(('DYLD_', 'LD_', 'GCC_', 'GFORTRAN_', 'PYTHON', '_PYTHON'))
                and name not in CONTEXT_KEYS):
            raise ValueError('Unknown build/import environment variable: ' + name)
    if env.get('LD_LIBRARY_PATH') or env.get('DYLD_LIBRARY_PATH'):
        raise ValueError('Dynamic-library search overrides are outside this pinned local workflow')
    if env.get('CONDA_BUILD') not in (None, '', '0'):
        raise ValueError('Conda-build activation is outside this local workflow')
    if any(env.get(k) is not None and (type(env[k]) is not str or any(x in env[k] for x in '\x00\r\n')) for k in CONTEXT_KEYS):
        raise ValueError('Invalid activated environment operand')
    path_entries = env.get('PATH', '').split(os.pathsep)
    if not path_entries or any(not p or not Path(p).is_absolute() for p in path_entries):
        raise ValueError('Activated PATH must contain only explicit absolute entries')
    prefix = Path(prefix).resolve(strict=True)
    effective, link = linker_environment(prefix, environment=env, system=system,
                                        architecture=architecture, run=run)
    if link['system'] != 'Darwin' or link.get('status') not in (
            'madgraph_default_ldflags_preserved', 'explicit_runtime_link_preserved_or_added'):
        raise ValueError('This generation policy requires the reviewed local Darwin workflow')
    if 'parsed_linker_flags' in link:
        _absolute_link_paths(link['parsed_linker_flags'])
    if env.get('LDFLAGS_LD'):
        other = runtime_selection(env['LDFLAGS_LD'])
        _absolute_link_paths(other)
        if (set(other['compiler_runtimes']) | set(other['explicit_runtimes'])) - {link['runtime']}:
            raise ValueError('LDFLAGS_LD selects a conflicting C++ runtime')
    executable = _required_file(python_executable or sys.executable, prefix)
    if executable != _required_file(prefix/'bin/python', prefix):
        raise ValueError('Activated interpreter differs from selected MG interpreter')
    config = _required_file(prefix/'bin/lhapdf-config', prefix)
    default_datadir = Path(run([config, '--datadir'])).resolve(strict=True)
    if not default_datadir.is_dir() or not default_datadir.is_relative_to(prefix):
        raise ValueError('LHAPDF default data directory is outside the selected prefix')
    lookup = env.get('LHAPDF_DATA_PATH')
    if lookup:
        # MG prefers this variable and scans colon-separated paths. Restrict
        # this first workflow to one explicit owned directory, not a fallback.
        if os.pathsep in lookup or not Path(lookup).is_absolute():
            raise ValueError('Ambiguous or relative LHAPDF_DATA_PATH is unsupported')
        datadir = Path(lookup).resolve(strict=True)
    else:
        datadir = default_datadir
    if not datadir.is_dir() or not datadir.is_relative_to(prefix):
        raise ValueError('Selected PDF directory must belong to the MG prefix')
    index = _required_file(datadir/'pdfsets.index', prefix)
    matches = []
    for line in index.read_text().splitlines():
        words = line.split('#', 1)[0].split()
        if words and words[0] == str(PDF_ID):
            matches.append(words)
    if len(matches) != 1 or len(matches[0]) != 3 or matches[0][1] != PDF_SET:
        raise ValueError('PDF index does not uniquely bind NNPDF260000')
    setdir = datadir/PDF_SET
    info = _required_file(setdir/(PDF_SET+'.info'), prefix)
    meta = _metadata_pairs(info)
    if (meta.get('SetIndex') != str(PDF_ID) or meta.get('Format') != 'lhagrid1'
            or meta.get('NumMembers') != '101' or meta.get('DataVersion') != matches[0][2]):
        raise ValueError('PDF set metadata differs from the declared reference set')
    sources = {'helper': pin(__file__), 'python': pin(executable),
               'pdf_index': pin(index), 'pdf_info': pin(info),
               'lhapdf_defaults': pin(_required_file(datadir/'lhapdf.conf', prefix))}
    for i, item in enumerate(link['sources']):
        sources['link_'+str(i)] = item
    # MG copies the set directory. Require the entire advertised local set so
    # absent members cannot trigger a download; only member zero is selected.
    expected = {PDF_SET+'.info', *(f'{PDF_SET}_{i:04d}.dat' for i in range(101))}
    actual = {p.name for p in setdir.iterdir() if p.is_file()}
    if actual != expected or any(p.is_dir() for p in setdir.iterdir()):
        raise ValueError('PDF set inventory is incomplete or contains unknown files')
    for name in sorted(expected - {PDF_SET+'.info'}):
        sources['pdf_member_'+name[-8:-4]] = pin(_required_file(setdir/name, prefix))
    hooks = prefix/'etc/conda/activate.d'
    hook_paths = sorted(hooks.iterdir()) if hooks.is_dir() else []
    if not hook_paths or any(not p.is_file() or p.suffix != '.sh' for p in hook_paths):
        raise ValueError('Compiler activation hook inventory is unsupported')
    for i, path in enumerate(hook_paths):
        sources['activation_'+str(i)] = pin(_required_file(path, prefix))
    sdk = env.get('SDKROOT')
    if not sdk or not Path(sdk).is_absolute() or not Path(sdk).is_dir():
        raise ValueError('Activated SDKROOT must identify an existing absolute SDK')
    sources['sdk_settings'] = pin(_required_file(Path(sdk)/'SDKSettings.json'))
    compiler_names = {'default_fortran': 'gfortran', 'default_cpp': 'clang',
                      'make': 'make', 'archive': 'ar'}
    for key in ('CC', 'CXX', 'CPP', 'FC', 'F77', 'F90', 'F95', 'AR', 'RANLIB'):
        if env.get(key):
            compiler_names[key] = env[key]
    compiler_paths = {}
    for key, value in sorted(compiler_names.items()):
        tokens = shlex.split(value)
        if len(tokens) != 1:
            raise ValueError('Compiler commands with extra arguments are unsupported')
        found = shutil.which(tokens[0], path=env['PATH'])
        if not found:
            raise ValueError('Activated compiler/tool is unavailable: ' + key)
        path = _required_file(found)
        if not os.access(path, os.X_OK):
            raise ValueError('Compiler/tool is not executable')
        compiler_paths[key] = str(path); sources['compiler_'+key] = pin(path)
    mg = _required_file(prefix.parents[2]/'mg5amcnlo/bin/mg5_aMC')
    mg_config = _required_file(mg.parent.parent/'input/mg5_configuration.txt')
    sources['madgraph'] = pin(mg); sources['madgraph_config'] = pin(mg_config)
    home = env.get('HOME')
    if not home or not Path(home).is_absolute() or not Path(home).is_dir():
        raise ValueError('MG HOME must be an explicit existing absolute directory')
    user_config = Path(home)/'.mg5/mg5_configuration.txt'
    configs = []
    if user_config.exists():
        sources['madgraph_user_config'] = pin(_required_file(user_config))
        configs.append(user_config)
    configs.append(mg_config)
    options = {}
    for item in configs:
        seen = {}
        for raw in item.read_text().splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line: continue
            if line.count('=') != 1:
                raise ValueError('Unsupported MG configuration line')
            key, value = (part.strip() for part in line.split('=', 1))
            if not key or (key in seen and seen[key] != value):
                raise ValueError('Conflicting or malformed MG configuration assignment')
            # Repeated identical assignments have one effective value. The full
            # configuration bytes remain pinned; contradictory duplicates fail.
            seen[key] = value; options[key] = value
    if (options.get('lhapdf_py3') != str(config)
            or options.get('auto_update') != '0' or options.get('run_mode') != '0'
            or options.get('fortran_compiler', 'gfortran') not in ('gfortran', 'None', '')
            or options.get('cpp_compiler', 'None') not in ('clang', 'None', '')):
        raise ValueError('MG configuration does not select the pinned local LHAPDF/compiler policy')
    # Extra compiler flags are preserved and pinned, but cannot independently
    # select a link runtime through a second unparsed option surface.
    for name in ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'FFLAGS', 'FORTRANFLAGS'):
        for token in shlex.split(env.get(name) or ''):
            if token.startswith(('-Wl,', '-Xlinker', '-l', '-stdlib=', '@')) or token.endswith(('.a', '.dylib')):
                raise ValueError('Link directives outside LDFLAGS are unsupported: ' + name)
    mg_selection = {'configuration_order': [str(x) for x in configs],
                    'user_configuration': str(user_config),
                    'user_configuration_present': user_config.exists(),
                    'effective_options': options}

    result = {'schema_version': 1, 'policy': GENERATION_POLICY,
              'scope': 'Local Darwin LHAPDF260000 central member; metadata preparation only',
              'prefix': str(prefix), 'python': str(executable),
              'link': link, 'environment': {k: env.get(k) for k in CONTEXT_KEYS},
              'pdf': {'lhaid': PDF_ID, 'set': PDF_SET, 'datadir': str(datadir),
                      'default_datadir': str(default_datadir), 'version': matches[0][2],
                      'used_members': [0], 'available_members': 101},
              'compiler_paths': compiler_paths, 'madgraph_selection': mg_selection, 'sources': sources}
    # Rehash after all probes/reads, closing an ordinary source-drift window.
    for item in sources.values():
        if pin(item['path']) != item:
            raise ValueError('Generation decision source changed during inspection')
    return effective, result


def _validate_generation_decision(record, prefix):
    """Validate a prospective captured decision without activating or probing."""
    fields = {'schema_version', 'policy', 'scope', 'prefix', 'python', 'link',
              'environment', 'pdf', 'compiler_paths', 'madgraph_selection', 'sources'}
    if type(record) is not dict or set(record) != fields or type(record['schema_version']) is not int or record['schema_version'] != 1 or record['policy'] != GENERATION_POLICY:
        raise ValueError('Unsupported generation decision schema/policy')
    if any(type(record[k]) is not dict for k in ('environment', 'pdf', 'link', 'sources', 'compiler_paths', 'madgraph_selection')):
        raise ValueError('Malformed generation decision sections')
    if set(record['environment']) != set(CONTEXT_KEYS):
        raise ValueError('Unknown or incomplete generation environment fields')
    if (record['prefix'] != str(Path(prefix).resolve(strict=True))
            or record['pdf'].get('lhaid') != PDF_ID or type(record['pdf'].get('lhaid')) is not int
            or record['pdf'].get('set') != PDF_SET or canonical(record['pdf'].get('used_members')) != '[0]'):
        raise ValueError('Generation decision prefix or PDF scope differs')
    # Feed only already captured metadata outputs into the same deterministic
    # inspector. This checks structure/selection/arithmetic against real bytes
    # without invoking any tool during planning.
    link = record['link']; pdf = record['pdf']
    if not {'sources', 'library_architectures', 'runtime', 'architecture'} <= set(link) or 'default_datadir' not in pdf:
        raise ValueError('Incomplete link/PDF metadata')
    if type(link['sources']) is not list or len(link['sources']) != 2:
        raise ValueError('Malformed linker source inventory')
    def retained_probe(command):
        command = list(map(str, command))
        if command[0].endswith('lhapdf-config'):
            if command[-1] == '--prefix': return record['prefix']
            if command[-1] == '--libdir': return str(Path(link['sources'][1]['path']).parent)
            if command[-1] == '--datadir': return pdf['default_datadir']
        if command[0] == 'lipo': return ' '.join(link['library_architectures'])
        if command[0] == 'otool': return 'library:\n\t@rpath/lib'+link['runtime']+'.1.dylib (compatibility version 1.0.0)'
        if command[0] == 'sysctl': return '0'
        raise ValueError('Unsupported retained metadata probe')
    _, expected = generation_decision(prefix, environment=record['environment'],
                                      run=retained_probe, system='Darwin',
                                      architecture=link['architecture'],
                                      python_executable=record['python'])
    if canonical(record) != canonical(expected):
        raise ValueError('Generation decision contradicts its source metadata')
    return record


def validate_generation_decision(record, prefix):
    """Normalize malformed record failures before any generator can be reached."""
    try:
        return _validate_generation_decision(record, prefix)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('Malformed generation decision record') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--generation', action='store_true', help='Capture the opt-in native-generation decision, metadata only')
    parser.add_argument('--out', type=Path, required=True,
                        help='New JSON preparation record; no environment or toolchain is changed')
    args = parser.parse_args(argv)
    _, record = generation_decision(args.prefix) if args.generation else linker_environment(args.prefix)
    with args.out.open('x') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write('\n')
    view = record['link'] if args.generation else record
    print(json.dumps({'status': view['status'], 'changed': view['changed'],
                      'added_tokens': view['added_tokens']}))


if __name__ == '__main__':
    main()
