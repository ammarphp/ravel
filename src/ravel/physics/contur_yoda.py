"""Fresh, source-bound single-point Contur inference from a supplied Rivet YODA.

The ordinary science worker owns approval, attempts and process supervision.
This adapter does not generate events, initialize Contur databases, combine
independent engines, or replace native pool/overlap/statistical calculations.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'

from ravel.workflow import science
from ravel.workflow.state_io import read_json, atomic_json
from ravel.physics import contur_import

VERSION = contur_import.VERSION
COMMIT = contur_import.COMMIT
SCOPE = 'fresh native single-point Contur confidence and complete pool results from supplied YODA and reference assets'
ENV_KEYS = ('PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'RIVET_ANALYSIS_PATH', 'RIVET_DATA_PATH', 'YODA_DATA_PATH')
BOOL_FLAGS = {
    'sig_plus_bg': '--spb', 'diag': '--diagonalise-cov', 'use_theory_corr': '--theorycorr',
    'look_elsewhere': '--look-elsewhere', 'exclude_hgg': '--nohiggsgamma',
    'exclude_met_ratio': '--nometratio', 'tracks_only': '--tracks-only',
}
INVERSE_FLAGS = {'exclude_hww': '--withhiggsww', 'exclude_b_veto': '--withbvetos',
                 'exclude_awz': '--atlas-wz', 'exclude_searches': '--use-searches',
                 'exclude_soft_physics': '--soft-physics'}
FIXED = {'stat_types': list(contur_import.MODES), 'multi_p': False, 'no_pools': False,
         'offline': True, 'exclude_superseded': True, 'npyscripts': -1, 'keep_unscaled_aos': True}
EFFECTIVE_KEYS = (*FIXED, *BOOL_FLAGS, *INVERSE_FLAGS, 'use_spey', 'min_num_sys', 'min_num_sys_sm',
                  'add_sqrt_evtcount_signal_error', 'flat_uncertainty', 'only_analyses', 'veto_analyses',
                  'weight', 'sorting_metric')
SOURCE_ROLES = {'database_reader': 'src/contur/data/data_access_db.py',
                'depot_export': 'src/contur/factories/depot.py',
                'point_results': 'src/contur/factories/contur_point.py',
                'confidence_semantics': 'src/contur/factories/likelihood.py'}


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(label + ' requires exactly ' + ', '.join(sorted(names)))


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(label + ' requires nonempty text')


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' requires a finite number, not a boolean')


def _pin(pin, base):
    _keys(pin, ('path', 'sha256'), 'file pin')
    if not isinstance(pin['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256']):
        raise ValueError('invalid SHA256')
    path = science.regular(pin['path'], base)
    if _sha(path) != pin['sha256']:
        raise ValueError('bound Contur input changed: ' + str(path))
    return path


def validate(task):
    _keys(task, ('input',), 'contur-yoda task')
    _text(task['input'], 'input document')
    return deepcopy(task)


def settings(value, *, schema_version=1):
    """Explicit requested effective state; no unsupported default substitution."""
    _keys(value, EFFECTIVE_KEYS, 'requested effective Contur settings')
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError('fresh Contur input schema1 or schema2 required')
    for key, expected in FIXED.items():
        if key == 'stat_types' and schema_version == 2:
            expected = list(contur_import.FULL_MODES)
        if type(value[key]) is not type(expected) or value[key] != expected:
            raise ValueError('first single-point route requires ' + key + '=' + str(expected))
    for key in (*BOOL_FLAGS, *INVERSE_FLAGS, 'use_spey', 'add_sqrt_evtcount_signal_error'):
        if type(value[key]) is not bool:
            raise ValueError('explicit boolean required: ' + key)
    for key in ('min_num_sys', 'min_num_sys_sm'):
        if type(value[key]) is not int or value[key] < 1:
            raise ValueError('positive integer required: ' + key)
    if value['flat_uncertainty'] is not None:
        _number(value['flat_uncertainty'], 'flat uncertainty')
        if value['flat_uncertainty'] < 0:
            raise ValueError('negative flat uncertainty')
    for key in ('only_analyses', 'veto_analyses'):
        if not isinstance(value[key], list) or len(set(value[key])) != len(value[key]):
            raise ValueError('distinct analysis regex list required')
        for pattern in value[key]:
            _text(pattern, 'analysis pattern')
            re.compile(pattern)
    if not value['only_analyses']:
        raise ValueError('first operation requires an explicit analysis selection')
    if not isinstance(value['weight'], str) or any(c in value['weight'] for c in ('\x00', '\n', '\r')):
        raise ValueError('explicit nominal empty-string or named weight required')
    if value['sorting_metric'] not in ('LLR', 'CLs'):
        raise ValueError('native sorting metric required')
    return deepcopy(value)


def parameter_values(path):
    """The released params.dat grammar, with duplicate/non-numeric refusal."""
    result = {}
    for line in Path(path).read_text().strip().split('\n'):
        if line.count(' = ') != 1:
            raise ValueError('params.dat requires exact name = value lines')
        name, value = line.split(' = ')
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name) or name in result:
            raise ValueError('duplicate or unsupported parameter identity')
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError('first route requires numeric parameters; SLHA/log augmentation is separate') from exc
        _number(number, 'parameter')
        result[name] = number
    if not result:
        raise ValueError('parameters are required; native unknown-parameter fallback is refused')
    return result


def _manifest(pin, base, kind):
    path = _pin(pin, base)
    doc = read_json(path)
    keys = ('schema_version', 'kind', 'root', 'files', 'scope')
    _keys(doc, (*keys, 'version', 'commit') if kind == 'contur-source' else keys, kind + ' manifest')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or doc['kind'] != kind:
        raise ValueError('explicit manifest kind/version differs')
    _text(doc['scope'], 'manifest scope')
    root = Path(doc['root']).expanduser().absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('manifest root must be an existing directory without symlinks')
    if not isinstance(doc['files'], dict) or not doc['files']:
        raise ValueError('complete nonempty declared asset inventory required')
    files = [path]
    for rel, sha in doc['files'].items():
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts or p.as_posix() != rel:
            raise ValueError('relative canonical manifest paths required')
        files.append(_pin({'path': str(root/p), 'sha256': sha}, base))
    if kind == 'contur-source':
        if doc['version'] != VERSION or doc['commit'] != COMMIT:
            raise ValueError('native first route requires explicit released Contur3.1.5 source')
        actual = {p.relative_to(root).as_posix() for p in (root/'src/contur').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        required = actual | {'bin/contur', 'pyproject.toml', 'COPYING'}
        if set(doc['files']) != required or not actual:
            raise ValueError('source inventory must cover the entire actual package and entry/license/metadata')
    else:
        area = root/'data' if kind == 'contur-data' else root
        actual = {p.relative_to(root).as_posix() for p in area.rglob('*') if p.is_file()}
        if set(doc['files']) != actual:
            raise ValueError('asset inventory is not complete for its declared directory')
        if kind == 'contur-user' and not {'analyses.db', 'models.db'} <= actual:
            raise ValueError('initialized analyses.db and models.db required; no automatic contur-init')
    return doc, root.resolve(), files


def _load(task, base):
    path = science.regular(validate(task)['input'], base)
    doc = read_json(path)
    if doc.get('schema_version') == 3:
        from ravel.physics import contur_population
        return contur_population.load(task, base)
    _keys(doc, ('schema_version', 'source', 'yoda', 'parameters', 'expected_events', 'config',
                'runtime', 'assets', 'settings', 'max_seconds', 'max_ram_mib'), 'fresh Contur document')
    if type(doc['schema_version']) is not int or doc['schema_version'] not in (1, 2):
        raise ValueError('fresh Contur schema1 required')
    _text(doc['source'], 'scientific YODA/normalization attribution')
    for key, low, high in (('max_seconds', 1, 900), ('max_ram_mib', 512, 8192), ('expected_events', 1, 10000000)):
        if type(doc[key]) is not int or not low <= doc[key] <= high:
            raise ValueError('invalid bounded integer ' + key)
    settings(doc['settings'], schema_version=doc['schema_version'])
    _keys(doc['assets'], ('source', 'data', 'user'), 'asset manifests')
    _keys(doc['runtime'], ('python', 'manifest'), 'native runtime')
    return path, doc


def _admission(task, base):
    path, doc = _load(task, base)
    if doc['schema_version'] == 3:
        from ravel.physics import contur_population
        return contur_population.admission(path, doc)
    yoda = _pin(doc['yoda'], path.parent)
    if not yoda.name.endswith(('.yoda', '.yoda.gz')):
        raise ValueError('supplied YODA or gzip YODA required')
    parameters = _pin(doc['parameters'], path.parent)
    parameter_values(parameters)
    config = _pin(doc['config'], path.parent)
    python = _pin(doc['runtime']['python'], path.parent)
    if not os.access(python, os.X_OK):
        raise ValueError('bound native Python must be executable')
    runtime_path = _pin(doc['runtime']['manifest'], path.parent)
    runtime = read_json(runtime_path)
    _keys(runtime, ('schema_version', 'kind', 'python_sha256', 'installed_distribution_version',
                    'files', 'environment', 'scope'), 'declared dependency runtime')
    if type(runtime['schema_version']) is not int or runtime['schema_version'] != 1 or runtime['kind'] != 'contur-declared-runtime' or runtime['python_sha256'] != doc['runtime']['python']['sha256']:
        raise ValueError('declared dependency runtime/interpreter mismatch')
    _text(runtime['installed_distribution_version'], 'installed distribution label')
    _text(runtime['scope'], 'declared runtime scope')
    _keys(runtime['environment'], ENV_KEYS, 'native startup environment')
    if any(v is not None and (not isinstance(v, str) or '\x00' in v) for v in runtime['environment'].values()):
        raise ValueError('nonsecret startup environment must be string or null')
    if not isinstance(runtime['files'], list) or not runtime['files']:
        raise ValueError('declared native dependency file pins required')
    files = [path, yoda, parameters, config, python, runtime_path]
    files += [_pin(p, runtime_path.parent) for p in runtime['files']]
    bundles = {}
    for kind in ('source', 'data', 'user'):
        md, root, ff = _manifest(doc['assets'][kind], path.parent, 'contur-' + kind)
        bundles[kind] = {'manifest': md, 'root': root}
        files += ff
    # Package sources define the actual observer, decoder and ordinary lifecycle.
    files += list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return path, doc, runtime, bundles, sorted(set(files))


def inputs(task, base):
    return _admission(task, base)[-1]


def execution_seconds(task, base):
    return _load(task, base)[1]['max_seconds'] + 30


def arguments(doc, work):
    """Compile only the released single-file options; no arbitrary CLI injection."""
    if doc.get('schema_version') == 3:
        from ravel.physics import contur_population
        return contur_population.arguments(doc, work)
    s = settings(doc['settings'], schema_version=doc.get('schema_version', 1)); work = Path(work)
    args = [str(work/'input'/Path(doc['yoda']['path']).name), '--nomultip', '--offline',
            '--outputdir', str(work/'native-output'), '--resultsfile', 'results.db',
            '--config', str(work/'input/config.dat'), '--log', str(work/'contur.log'),
            '--weight-name', s['weight'], '--min-num-sys', str(s['min_num_sys'])]
    for pattern in s['only_analyses']:
        args += ['--ana-match', pattern]
    for pattern in s['veto_analyses']:
        args += ['--ana-unmatch', pattern]
    for key, flag in BOOL_FLAGS.items():
        if s[key]: args.append(flag)
    for key, flag in INVERSE_FLAGS.items():
        if not s[key]: args.append(flag)
    if s['use_spey']: args.append('--spey')
    if doc.get('schema_version', 1) == 2: args.append('--databg')
    if s['sorting_metric'] == 'CLs': args.append('--sort-by-cls')
    return args


def effective_state(cfg, *, schema_version=1):
    state = {key: deepcopy(getattr(cfg, key)) for key in EFFECTIVE_KEYS}
    settings(state, schema_version=schema_version)
    return state


def check_effective(requested, effective, *, schema_version=1):
    settings(requested, schema_version=schema_version); settings(effective, schema_version=schema_version)
    differences = {k: {'requested': requested[k], 'effective': effective[k]} for k in EFFECTIVE_KEYS
                   if type(requested[k]) is not type(effective[k]) or requested[k] != effective[k]}
    if differences:
        raise ValueError('resolved Contur settings differ before inference: ' + str(differences))
    return {'requested': requested, 'effective': effective,
            'single_file_side_effects': ['all plot scripts are written by the released single-file policy',
                                       'unscaled analysis objects retained'],
            'runtime_consumption_scope': 'Observed Python configuration before native process_single, not all file or shared-library reads.'}


def confidence_witness(point, *, modes=contur_import.MODES):
    """Disallow upstream None→0 serialization from masquerading as confidence."""
    witness = {}
    modes = contur_import.mode_population(modes)
    if modes == contur_import.FULL_MODES and (
            set(point.full_likelihood_results) != set(modes) or
            set(point.sorted_blocks_results) != set(modes)):
        raise ValueError('full native confidence witness has missing or unknown modes')
    for mode in modes:
        combined = point.full_likelihood_results.get(mode)
        pools = point.sorted_blocks_results.get(mode)
        if not isinstance(combined, dict) or not isinstance(pools, dict) or not pools:
            raise ValueError('incomplete native confidence population')
        def confidence(value):
            if isinstance(value, bool) or value is None:
                raise ValueError('missing native confidence; released None-to-zero writer fallback refused')
            value = float(value)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('invalid native confidence')
            return value
        if any(not isinstance(k, str) or not k.strip() for k in pools):
            raise ValueError('native pool identity must be nonempty text')
        witness[mode] = {'combined': confidence(combined.get('CLs')),
                         'pools': {str(k): confidence(v.get('CLs')) for k, v in pools.items()}}
    return witness


def reconcile(points, doc, staged_yoda, witness):
    if doc.get('schema_version', 1) == 2:
        settings(doc['settings'], schema_version=2)
        if (set(witness) != set(contur_import.FULL_MODES) or len(points) != 1 or
            [r['raw']['stat_type'] for r in points[0]['runs']] != list(contur_import.FULL_MODES)):
            raise ValueError('full native database/raw witness mode population differs')
    if len(points) != 1 or points[0]['original_yoda_paths'] != [str(Path(staged_yoda))]:
        raise ValueError('fresh database must describe exactly the unchanged supplied YODA')
    if points[0]['parameters'] != doc['parameter_values']:
        raise ValueError('native parameter basis/values differ')
    for run in points[0]['runs']:
        mode = run['raw']['stat_type']; raw = witness[mode]
        if run['raw']['events_num'] != doc['expected_events']:
            raise ValueError('native YODA event count differs from declared supplied exposure')
        if run['native_exclusion_confidence'] != raw['combined'] or {p['pool_name']: p['exclusion'] for p in run['pools']} != raw['pools']:
            raise ValueError('serialized complete confidence/pool population differs from actual raw calculation')
    return points


def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd/science.PLAN).is_file():
            selected = science.verify_worker(rd); spec = science.execution_spec(rd)
            if spec['mode'] != 'contur-yoda' or spec['task'] != task or Path(output).resolve() != (rd/selected['output_directory']).resolve():
                raise ValueError('Contur task/output differs from exact approved worker')
            return rd, selected
    raise ValueError('fresh Contur requires approved supervised science worker')


def _workspace_inventory(root):
    """Hash regular staged files, refusing links and special files."""
    root = Path(root).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('staged directory must exist without symlinks: ' + str(root))
    inventory = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('staged inventory contains symlink or special file: ' + str(path))
        if path.is_file():
            inventory[path.relative_to(root).as_posix()] = _sha(science.regular(path, root))
    return inventory


def staged_inputs(doc, bundles, work, *, initial_user=False):
    """Bind actual scientific copies to admitted originals, not preparation prose.

    The full user inventory is exact at startup and immediately before inference.
    The user area is writable in released Contur; ending changes are disclosed,
    not silently described as unchanged. This is a checkpoint witness, not an
    open-file trace or proof of every native read during the call.
    """
    work = Path(work).absolute()
    expected = {Path(doc['yoda']['path']).name: doc['yoda']['sha256'],
                'params.dat': doc['parameters']['sha256'], 'config.dat': doc['config']['sha256']}
    scientific = _workspace_inventory(work/'input')
    if scientific != expected:
        raise ValueError('staged scientific input bytes/population differ from admitted originals')
    expected_user = bundles['user']['manifest']['files']
    user = _workspace_inventory(work/'user')
    if initial_user and user != expected_user:
        raise ValueError('staged initial user inventory differs from admitted originals')
    changes = {rel: {'initial_sha256': expected_user.get(rel), 'ending_sha256': user.get(rel),
                     'change': 'added' if rel not in expected_user else 'removed' if rel not in user else 'changed'}
               for rel in sorted(set(expected_user) | set(user)) if expected_user.get(rel) != user.get(rel)}
    return {'scientific_files': scientific, 'user_files': user, 'user_changes': changes,
            'initial_user_required': initial_user,
            'scope': 'Exact staged scientific bytes at this checkpoint; initial user bytes exact before SDK and inference; ending writable-user changes retained. Not continuous consumption tracing.'}


def materialize(task, base, work):
    """Source preparation only. Copies supplied bytes into a fresh owned workspace."""
    path, doc, runtime, bundles, files = _admission(task, base)
    if doc['schema_version'] == 3:
        from ravel.physics import contur_population
        return contur_population.materialize(path, doc, runtime, bundles, files, work)
    work = Path(work); work.mkdir(parents=True, exist_ok=False)
    (work/'input').mkdir(); (work/'user').mkdir()
    for key, name in (('yoda', Path(doc['yoda']['path']).name), ('parameters', 'params.dat'), ('config', 'config.dat')):
        shutil.copyfile(_pin(doc[key], path.parent), work/'input'/name)
    for rel in bundles['user']['manifest']['files']:
        target = work/'user'/rel; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundles['user']['root']/rel, target)
    # Resolve pins; native worker must not depend on a caller's relative cwd.
    resolved = deepcopy(doc)
    for key in ('yoda', 'parameters', 'config'):
        resolved[key]['path'] = str(_pin(doc[key], path.parent))
    for key in ('python', 'manifest'):
        resolved['runtime'][key]['path'] = str(_pin(doc['runtime'][key], path.parent))
    for key in resolved['assets']:
        resolved['assets'][key]['path'] = str(_pin(doc['assets'][key], path.parent))
    atomic_json(work/'native-input.json', resolved)
    atomic_json(work/'preparation.json', {'kind': 'contur-single-source-preparation',
        'input_hashes': {str(p): _sha(p) for p in files}, 'arguments': arguments(resolved, work),
        'source_version': VERSION, 'source_commit_label': COMMIT, 'runtime_consumption_verified': False,
        'installed_distribution_version': runtime['installed_distribution_version'], 'source_override': str(bundles['source']['root']/'src'),
        'initialized_user_assets_copied': True, 'events_generated': 0,
        'staged_inputs': staged_inputs(resolved, bundles, work, initial_user=True)})
    return work/'native-input.json'


def module_witness(source_root, declared, dependencies, *, modules=None):
    """Hash every loaded non-stdlib module file against admitted byte identities.

    The Python launcher uses a fresh pycache_prefix with -B. Existing cache
    bytecode cannot quietly replace inspected source. This is not a system
    shared-library/open-file tracing claim.
    """
    import sysconfig
    stdlib = Path(sysconfig.get_path('stdlib')).resolve()
    own = Path(__file__).resolve().parents[1]
    observed = {}
    for name, module in list((sys.modules if modules is None else modules).items()):
        f = getattr(module, '__file__', None)
        if not f or name == '__main__':
            continue
        path = Path(f).resolve()
        if path.suffix == '.pyc':
            raise ValueError('sourceless/cache bytecode is not admitted: ' + str(path))
        if name == 'ravel' or name.startswith('ravel.'):
            if not path.is_relative_to(own) or not path.is_file():
                raise ValueError('loaded Ravel module outside bound observer package')
            # Outer and native admission cover every actual package .py file.
            observed[name] = {'path': str(path), 'sha256': _sha(path)}
            continue
        if path.is_relative_to(stdlib) and not {'site-packages', 'dist-packages'} & set(path.parts):
            continue
        table = declared if name == 'contur' or name.startswith('contur.') else dependencies
        if str(path) not in table or _sha(path) != table[str(path)]:
            raise ValueError('loaded module absent or changed in declared source/runtime: ' + str(path))
        if (name == 'contur' or name.startswith('contur.')) and not path.is_relative_to(source_root):
            raise ValueError('loaded Contur source outside admitted source directory')
        observed[name] = {'path': str(path), 'sha256': table[str(path)]}
    return observed


def _delegated_parent(rundir, prepared, work):
    """Require the live ordinary science worker as this child's direct parent.

    Outer verify_worker performs full approval/runtime/source admission. This
    narrow child check prevents launching from mere materialization; it does
    not claim to repeat approval under a different native Python interpreter.
    """
    from ravel.workflow import execution
    rd = science.root(rundir)
    proposal = read_json(rd/science.PLAN)
    spec = science.execution_spec(rd)
    record = execution.load_execution(rd)['stages'].get('science', {})
    approval = read_json(rd/science.APPROVAL)
    if (spec['schema_version'] != 2 or spec['mode'] != 'contur-yoda' or spec['max_attempts'] != 1 or
        record.get('status') != 'running' or record.get('child_pid') != os.getppid() or
        record.get('child_identity') != execution.process_identity(os.getppid()) or
        record.get('fingerprint') != proposal['stage_binding']['fingerprint'] or
        approval.get('plan_sha256') != _sha(rd/science.PLAN) or
        Path(work) != rd/proposal['stages'][0]['outputs'][0]/'contur-work'):
        raise ValueError('native Contur requires delegation from its live exact ordinary worker')
    original_path, original = _load(spec['task'], proposal['base_dir'])
    if original['schema_version'] == 3:
        from ravel.physics import contur_population
        if prepared != contur_population.resolve(original, original_path.parent):
            raise ValueError('native prepared profile input differs from exact approved original')
        return
    resolved = deepcopy(original)
    for key in ('yoda', 'parameters', 'config'):
        resolved[key]['path'] = str(_pin(original[key], original_path.parent))
    for key in ('python', 'manifest'):
        resolved['runtime'][key]['path'] = str(_pin(original['runtime'][key], original_path.parent))
    for key in resolved['assets']:
        resolved['assets'][key]['path'] = str(_pin(original['assets'][key], original_path.parent))
    if prepared != resolved:
        raise ValueError('native prepared input differs from exact approved original')


def native_worker(input_path, work, rundir):
    """Private child entry. This executes the released API only after outer approval."""
    if sys.flags.optimize:
        raise ValueError('optimized runtime is not admitted')
    if read_json(input_path).get('schema_version') == 3:
        from ravel.physics import contur_population
        return contur_population.native_worker(input_path, work, rundir)
    work = Path(work).resolve(); path = Path(input_path).resolve()
    if path != work/'native-input.json':
        raise ValueError('native input must be the prepared exact workspace document')
    _, doc, runtime, bundles, _ = _admission({'input': str(path)}, path.parent)
    _delegated_parent(rundir, doc, work)
    staged_before_sdk = staged_inputs(doc, bundles, work, initial_user=True)
    for key, value in runtime['environment'].items():
        if os.environ.get(key) != value:
            raise ValueError('native startup environment differs: ' + key)
    os.environ['CONTUR_USER_DIR'] = str(work/'user')
    os.environ['CONTUR_DATA_PATH'] = str(bundles['data']['root'])
    sys.path.insert(0, str(bundles['source']['root']/'src'))
    import contur
    from contur.run import arg_utils, run_analysis
    from contur.config import config as cfg
    if contur.__version__ != VERSION:
        raise ValueError('actual loaded Contur version differs from pinned source')
    source = bundles['source']['manifest']; source_root = bundles['source']['root']
    declared = {str(source_root/rel): sha for rel, sha in source['files'].items()}
    dependency_pins = {str(_pin(p, Path(doc['runtime']['manifest']['path']).parent)): p['sha256'] for p in runtime['files']}
    def loaded_sources():
        return module_witness(source_root, declared, dependency_pins)
    observed = {'staged_before_sdk': staged_before_sdk}
    original_process, original_write = run_analysis.process_single, run_analysis.write_point
    def before_process(args, yodafile, csvfile=None):
        if Path(yodafile).absolute() != work/'input'/Path(doc['yoda']['path']).name:
            raise ValueError('native process_single YODA differs from exact staged scientific input')
        observed['staged_before_inference'] = staged_inputs(doc, bundles, work, initial_user=True)
        version = doc['schema_version']
        observed['effective_settings'] = check_effective(doc['settings'], effective_state(cfg, schema_version=version), schema_version=version)
        observed['loaded_before_inference'] = loaded_sources()
        atomic_json(work/'native-observation.json', observed)
        return original_process(args, yodafile, csvfile)
    def before_write(point, *args):
        observed['confidence_witness'] = (confidence_witness(point, modes=contur_import.FULL_MODES)
                                          if doc['schema_version'] == 2 else confidence_witness(point))
        atomic_json(work/'native-observation.json', observed)
        return original_write(point, *args)
    run_analysis.process_single, run_analysis.write_point = before_process, before_write
    try:
        run_analysis.main(arg_utils.get_args(arguments(doc, work), 'analysis'))
    finally:
        run_analysis.process_single, run_analysis.write_point = original_process, original_write
        observed['staged_after_inference'] = staged_inputs(doc, bundles, work)
        observed['loaded_after_inference'] = loaded_sources()
        observed['source_observer_intervention'] = 'two checked call wrappers: staged-input and resolved-state checks before process_single and raw confidence check before write_point; no native calculation modified'
        atomic_json(work/'native-observation.json', observed)
    if 'confidence_witness' not in observed:
        raise ValueError('native raw confidence witness absent')
    return observed


def run(task, base, output):
    rd, selected = _approved(task, output)
    if _load(task, base)[1]['schema_version'] == 3:
        from ravel.physics import contur_population
        return contur_population.run(task, base, output)
    if execution_seconds(task, base) > selected['max_seconds']:
        raise ValueError('native plus readback ceiling exceeds approved ordinary stage')
    files = inputs(task, base); before = {str(p): _sha(p) for p in files}
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=True)
    native_input = materialize(task, base, out/'contur-work')
    doc = read_json(native_input)
    from ravel.physics.reinterpret_db import execute_native
    command = [doc['runtime']['python']['path'], '-B', '-X', 'pycache_prefix='+str(out/'contur-work/bytecode-cache'), str(Path(__file__).resolve()), '--native-worker', '--input', str(native_input), '--out', str(out/'contur-work'), '--rundir', str(rd)]
    receipt = execute_native(command, out, doc)
    _, _, _, bundles, _ = _admission(task, base)
    observation = read_json(out/'contur-work/native-observation.json')
    check_effective(doc['settings'], observation['effective_settings']['effective'], schema_version=doc['schema_version'])
    database = out/'contur-work/native-output/results.db'
    full = doc['schema_version'] == 2
    points = (contur_import.decode_database(database, modes=contur_import.FULL_MODES)
              if full else contur_import.decode_database(database))
    doc['parameter_values'] = parameter_values(doc['parameters']['path'])
    reconcile(points, doc, out/'contur-work/input'/Path(doc['yoda']['path']).name, observation['confidence_witness'])
    staged_after_readback = staged_inputs(doc, bundles, out/'contur-work')
    if before != {str(p): _sha(p) for p in inputs(task, base)}:
        raise ValueError('bound source/YODA/reference/runtime inputs changed during execution')
    result = {'kind': 'native-contur-single-point', 'status': 'passed', 'physics_validated': False,
        'scope': SCOPE, 'points': points, 'fresh_inference': True, 'native_execution': receipt,
        'source': doc['source'], 'requested_effective_settings': observation['effective_settings'],
        'runtime_observation': observation, 'staged_after_readback': staged_after_readback,
        'database': {'path': str(database), 'sha256': _sha(database)},
        'events_generated': 0, 'detector_validated': False, 'event_weights_validated': False,
        'limitations': ['Input YODA normalization, event/group weights, generator and detector fidelity are supplied evidence, not established by inference.',
            'Native analysis selection, overlap protection, background modes and pooling are preserved; engine results must not be naively unioned with other families.',
            'Native CL/exclusion fields store confidence; 1-confidence is separately named, never a discovery significance.',
            'Module byte observation does not prove all runtime shared-library, reference-file or original event consumption.',
            'Staged scientific inputs are checked before SDK, before inference and at ending checkpoints; this is not continuous read tracing. Writable user changes are disclosed, not asserted immutable.',
            'All single-file native plot scripts are permitted inside the owned workspace; expected wall/RAM ceilings remain prospective.',
            'No catalogue-wide coverage, paper reproduction or fit calibration is inferred.']}
    if full:
        result['mode_population'] = list(contur_import.FULL_MODES)
        commitments = contur_import.full_mode_delivery(out, 'contur-results.json', result, points)
        if before != {str(p): _sha(p) for p in inputs(task, base)}:
            raise ValueError('bound full-mode Contur inputs changed before final return')
        contur_import.verify_full_mode_delivery(out, 'contur-results.json', result, commitments)
    else:
        atomic_json(out/'contur-results.json', result)
        (out/'native-columns.csv').write_text(contur_import.export_csv(points))
    return result


def prepare(input_file, review_policy, output, *, approval_mode='physicist'):
    path = Path(input_file).resolve(); task = {'input': str(path)}
    inputs(task, path.parent)
    _, doc = _load(task, path.parent)
    spec = {'schema_version': 2, 'mode': 'contur-yoda', 'source': doc['source'],
        'assumptions': [('fresh native declared ' + doc['operation'] + ' Contur population with exact source grouping and ordered per-input metadata' if doc['schema_version'] == 3 else SCOPE), 'Source/data/user/runtime are declared pinned inputs; installed version labels do not select the runtime.',
            'No generation, shower, detector simulation, contur-init or cross-engine combination.',
            'Native module/configuration witnesses have limited consumption scope; supplied original weights/normalization need separate admission.'],
        'max_seconds': execution_seconds(task, path.parent), 'approval_mode': approval_mode,
        'task': task, 'max_attempts': 1, 'review_policy': read_json(science.regular(review_policy, path.parent))}
    science.validate(spec)
    if spec['review_policy']['policy']['max_redos'] != 0:
        raise ValueError('first fresh Contur route permits one attempt and no automatic retry')
    if Path(output).exists():
        raise FileExistsError(output)
    atomic_json(output, spec)
    return spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--native-worker', action='store_true')
    parser.add_argument('--review-policy')
    parser.add_argument('--rundir')
    args = parser.parse_args(argv)
    if args.native_worker:
        if not args.rundir:
            raise ValueError('ordinary parent delegation required')
        native_worker(args.input, args.out, args.rundir)
    else:
        if not args.review_policy:
            raise ValueError('ordinary prospective review policy required')
        prepare(args.input, args.review_policy, args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
