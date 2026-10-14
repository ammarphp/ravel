"""Released Contur companion operations through the ordinary scientific lifecycle.

This module prepares and supervises native calls. It does not implement a
likelihood, generate events, initialize Contur, or approve scientific results.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat

from ravel.physics import contur_yoda as custody
from ravel.workflow import science
from ravel.workflow.state_io import read_json

VERSION, COMMIT = custody.VERSION, custody.COMMIT
SCOPE = 'released_contur_companion_delivery'
ENTRIES = {'sm-test': ('contur-smtest', 'smtest'),
           'herwig-xs-br': ('contur-extract-xs-bf', 'extract_xs_bf'),
           'map-plots': ('contur-plot', 'plot'),
           'rivet-plots': ('contur-rivetplots', 'mkhtml')}
MAX_MEMBERS, MAX_MEMBER, MAX_PAYLOAD = 20000, 128*1024*1024, 512*1024*1024
XS_FLAGS = {'fold_br': '--br', 'fold_bsm_br': '--bsm-br',
            'split_leptons': '--sl', 'merge_bosons': '--mb',
            'split_incoming_partons': '--sp', 'split_antiparticles': '--sa',
            'split_b': '--sb', 'split_light_quarks': '--sq',
            'merge_by_mediator': '--mBm'}
OPTION_KEYS = {
    'sm-test': ('offline', 'use_spey', 'only_analyses', 'veto_analyses', 'prediction', 'graphics'),
    'herwig-xs-br': ('offline', 'seed', 'tag', 'tolerance', *XS_FLAGS),
    'map-plots': ('offline', 'variables', 'levels', 'slice', 'save_plots', 'databg',
                 'no_exp', 'pools', 'format', 'ilevel', 'iorder', 'isigma', 'style'),
    'rivet-plots': ('offline', 'only_analyses', 'veto_analyses', 'databg', 'no_exp',
                   'runpoint', 'include_none', 'cls'),
}


def _keys(value, keys, label):
    custody._keys(value, keys, label)


def _text(value, label, *, empty=False):
    if (not isinstance(value, str) or (not empty and not value.strip())
            or any(c in value for c in ('\x00', '\n', '\r'))):
        raise ValueError(label + ' requires single-line text')


def _number(value, label, low=0, high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or high is not None and value > high:
        raise ValueError('invalid finite ' + label)


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid bounded integer ' + label)


def options(operation, value):
    _keys(value, OPTION_KEYS[operation], 'native companion options')
    bools = {'offline', 'use_spey', 'graphics', 'save_plots', 'databg', 'no_exp',
             'pools', 'include_none', *XS_FLAGS}
    for key in set(value) & bools:
        if type(value[key]) is not bool:
            raise ValueError('explicit boolean required: ' + key)
    for key in ('only_analyses', 'veto_analyses'):
        if key in value:
            patterns = value[key]
            if not isinstance(patterns, list) or len(patterns) > 100 or len(set(patterns)) != len(patterns):
                raise ValueError('distinct finite native selectors required')
            for pattern in patterns:
                _text(pattern, key); re.compile(pattern)
    if operation == 'sm-test':
        _text(value['prediction'], 'native SM prediction selector')
    elif operation == 'herwig-xs-br':
        _integer(value['seed'], 'Herwig file selector', 0, 2147483647)
        if not isinstance(value['tag'], str) or not re.fullmatch('[A-Za-z0-9_-]+', value['tag']):
            raise ValueError('literal Herwig file tag required')
        _number(value['tolerance'], 'native printed percentage cutoff option', 0, 1)
    elif operation == 'map-plots':
        if (not isinstance(value['variables'], list) or len(value['variables']) != 2
                or len(set(value['variables'])) != 2):
            raise ValueError('exactly two distinct native parameter names required')
        for name in value['variables']:
            if not isinstance(name, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name):
                raise ValueError('literal parameter name required')
        levels = value['levels']
        if not isinstance(levels, list) or not 1 <= len(levels) <= 3:
            raise ValueError('one to three native contour levels required')
        for level in levels:
            _number(level, 'native contour level')
        if len(set(levels)) != len(levels):
            raise ValueError('native contour levels must be distinct')
        if not isinstance(value['slice'], dict):
            raise ValueError('explicit native slice parameter map required')
        for name, number in value['slice'].items():
            if not isinstance(name, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name) or name in value['variables']:
                raise ValueError('invalid native slice parameter identity')
            _number(number, 'slice value', low=-math.inf)
        if value['format'] not in ('pdf', 'png', 'svg') or value['style'] not in ('DRAFT', 'FINAL'):
            raise ValueError('unsupported noninteractive native plot format/style')
        _integer(value['ilevel'], 'native zoom level', 1, 4)
        _integer(value['iorder'], 'native spline order', 1, 5)
        _number(value['isigma'], 'native mesh smoothing radius', 0, 5)
    else:
        _number(value['cls'], 'native histogram selection', 0, 1)
        if value['runpoint'] is not None and (not isinstance(value['runpoint'], str) or
                not re.fullmatch('[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', value['runpoint'])):
            raise ValueError('explicit native beam/runpoint selector required')
    return deepcopy(value)


def validate(task):
    _keys(task, ('input',), 'contur-companion task')
    _text(task['input'], 'input document')
    return deepcopy(task)


def _load(task, base):
    path = science.regular(validate(task)['input'], base)
    if path.stat().st_size > 2*1024*1024:
        raise ValueError('companion request exceeds two MiB')
    doc = read_json(path)
    _keys(doc, ('schema_version', 'source', 'operation', 'runtime', 'assets', 'entry',
                'inputs', 'options', 'max_seconds', 'max_ram_mib', 'renderer_cores'), 'companion request')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or doc['operation'] not in ENTRIES:
        raise ValueError('closed companion operation/schema required')
    _text(doc['source'], 'scientific attribution')
    _keys(doc['runtime'], ('python', 'manifest'), 'native runtime')
    _keys(doc['assets'], ('source', 'data', 'user'), 'complete Contur asset manifests')
    _integer(doc['max_seconds'], 'native seconds', 1, 900)
    _integer(doc['max_ram_mib'], 'native RAM MiB', 512, 8192)
    _integer(doc['renderer_cores'], 'prospective renderer cores', 1, 4)
    options(doc['operation'], doc['options'])
    _keys(doc['inputs'], ('config',) if doc['operation'] == 'sm-test' else
          ('payload',) if doc['operation'] == 'herwig-xs-br' else ('payload', 'database'), 'operation inputs')
    if 'database' in doc['inputs'] and (not isinstance(doc['inputs']['database'], str) or
            not re.fullmatch(r'[A-Za-z0-9_.-]+\.db', doc['inputs']['database'])):
        raise ValueError('native database basename required')
    return path, doc


def _payload(pin, base):
    path = custody._pin(pin, base)
    if path.stat().st_size > 16*1024*1024:
        raise ValueError('complete operation manifest exceeds sixteen MiB')
    doc = read_json(path)
    _keys(doc, ('schema_version', 'kind', 'root', 'files', 'source'), 'operation payload manifest')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or doc['kind'] != 'contur-companion-input':
        raise ValueError('ordinary complete companion input manifest required')
    _text(doc['source'], 'native output/log source association')
    root = Path(doc['root']).expanduser().absolute()
    actual = bounded_inventory(root)
    if (not isinstance(doc['files'], dict) or not doc['files'] or len(doc['files']) > MAX_MEMBERS
            or actual != doc['files']):
        raise ValueError('complete native payload membership/bytes differ')
    total = 0
    for rel in doc['files']:
        p = Path(rel)
        if p.is_absolute() or '..' in p.parts or p.as_posix() != rel:
            raise ValueError('canonical relative native payload path required')
        size = (root/p).stat().st_size
        if size > MAX_MEMBER:
            raise ValueError('native payload member exceeds declared bound')
        total += size
    if total > MAX_PAYLOAD:
        raise ValueError('native operation payload exceeds declared bound')
    return doc, root, [path, *(root/r for r in doc['files'])]


def bounded_inventory(root):
    """Apply finite operation payload bounds before hashing its regular files."""
    root=Path(root).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):
        raise ValueError('native payload root must be an ordinary directory')
    paths=[];total=0
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('native payload has alias or special member')
        if path.is_file():
            size=path.stat().st_size;total+=size;paths.append(path)
            if size>MAX_MEMBER or total>MAX_PAYLOAD or len(paths)>MAX_MEMBERS:
                raise ValueError('native operation payload exceeds prospective file/aggregate bounds')
    return {p.relative_to(root).as_posix():custody._sha(p) for p in paths}


def herwig_profile(root, doc):
    root = Path(root)
    if not re.fullmatch('[A-Za-z0-9_-]+', root.name):
        raise ValueError('literal native runpoint directory name required')
    stem = f"herwig-S{doc['options']['seed']}-{doc['options']['tag']}_{root.name}"
    paths = [root/'params.dat', root/(stem+'.log'), root/(stem+'.out')]
    for path in paths:
        science.regular(path, root)
    custody.parameter_values(paths[0])
    with paths[-1].open('rb') as stream:
        header = stream.read(16384).decode('utf-8', errors='strict')
    if not re.search(r'Cross-section(?:[^\n]*\n[^\n]*)?\s*\(nb\)', header):
        raise ValueError('original Herwig nb source-format declaration required')
    return {'stem': stem, 'native_total_unit': 'nb', 'printed_unit': 'fb',
            'printed_conversion_source': 'native percentage * total_nb * 0.01 * 1e6',
            'reported_uncertainty': 'unavailable: native parser discards parenthesized errors'}


def admission(task, base):
    path, doc = _load(task, base)
    python = custody._pin(doc['runtime']['python'], path.parent)
    if not os.access(python, os.X_OK):
        raise ValueError('native interpreter is not executable')
    runtime_path = custody._pin(doc['runtime']['manifest'], path.parent)
    runtime = read_json(runtime_path)
    _keys(runtime, ('schema_version', 'kind', 'python_sha256', 'installed_distribution_version',
                    'files', 'environment', 'scope'), 'declared native runtime')
    if (type(runtime['schema_version']) is not int or runtime['schema_version'] != 1
            or runtime['kind'] != 'contur-declared-runtime'
            or runtime['python_sha256'] != doc['runtime']['python']['sha256']):
        raise ValueError('runtime/interpreter binding differs')
    _text(runtime['installed_distribution_version'], 'distribution label')
    _text(runtime['scope'], 'runtime scope')
    _keys(runtime['environment'], custody.ENV_KEYS, 'native startup environment')
    if any(v is not None and (not isinstance(v, str) or '\x00' in v) for v in runtime['environment'].values()):
        raise ValueError('invalid nonsecret native environment')
    if not isinstance(runtime['files'], list) or not runtime['files']:
        raise ValueError('complete declared dependency file pins required')
    files = [path, python, runtime_path, *[custody._pin(p, runtime_path.parent) for p in runtime['files']]]
    bundles = {}
    for kind in ('source', 'data', 'user'):
        md, root, members = custody._manifest(doc['assets'][kind], path.parent, 'contur-' + kind)
        bundles[kind] = {'manifest': md, 'root': root}; files += members
    entry = custody._pin(doc['entry'], path.parent)
    if entry != bundles['source']['root']/'bin'/ENTRIES[doc['operation']][0]:
        raise ValueError('native companion entry differs from declared released source/operation')
    files.append(entry)
    if doc['operation'] == 'sm-test':
        if doc['inputs']['config'] is not None:
            files.append(custody._pin(doc['inputs']['config'], path.parent))
    else:
        md, root, members = _payload(doc['inputs']['payload'], path.parent)
        bundles['payload'] = {'manifest': md, 'root': root}; files += members
        if doc['operation'] == 'herwig-xs-br':
            herwig_profile(root, doc)
        else:
            database = root/doc['inputs']['database']
            with database.open('rb') as stream: header=stream.read(16)
            if doc['inputs']['database'] not in md['files'] or header != b'SQLite format 3\x00':
                raise ValueError('genuine source-associated native SQLite payload required')
            if doc['operation'] == 'rivet-plots' and not any(r.startswith('scripts/') and r.endswith('.py') for r in md['files']):
                raise ValueError('complete associated native scripts are required')
    files += list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return path, doc, runtime, bundles, sorted(set(files))


def inputs(task, base):
    return admission(task, base)[-1]


def execution_seconds(task, base):
    return _load(task, base)[1]['max_seconds'] + 60


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def write_new(path, value):
    """Commit intended serialized bytes, never adopt a first foreign reread."""
    path = Path(path); raw = _json_bytes(value)
    with path.open('xb') as stream:
        stream.write(raw)
    pin = {'path': str(path.absolute()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    verify_emitted([pin])
    return pin


def verify_emitted_value(pin,value):
    raw=_json_bytes(value)
    if len(raw)!=pin['size'] or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise ValueError('intended companion returned value differs')
    verify_emitted([pin])


def supplied_mode(path):
    mode=stat.S_IMODE(science.regular(path,Path.cwd()).stat().st_mode)
    if mode & (stat.S_ISUID|stat.S_ISGID|stat.S_ISVTX):
        raise ValueError('privilege bits are not admitted for supplied native copies')
    return mode


def verify_emitted(pins):
    for pin in pins:
        path = science.regular(pin['path'], Path.cwd())
        if path.stat().st_size != pin['size'] or custody._sha(path) != pin['sha256']:
            raise ValueError('intended companion artifact changed: '+str(path))


def resolved_document(doc, base):
    doc = deepcopy(doc)
    def resolve(pin):
        pin['path'] = str(custody._pin(pin, base))
    for pin in [doc['entry'], *doc['runtime'].values(), *doc['assets'].values()]:
        resolve(pin)
    for pin in doc['inputs'].values():
        if isinstance(pin, dict): resolve(pin)
    return doc


def scientific_modes(doc,bundles):
    if doc['operation']=='sm-test':
        return {} if doc['inputs']['config'] is None else {
            'config.dat':supplied_mode(doc['inputs']['config']['path'])}
    prefix=bundles['payload']['root'].name
    return {prefix+'/'+rel:supplied_mode(bundles['payload']['root']/rel)
            for rel in bundles['payload']['manifest']['files']}


def prepared_modes(work,commitment=None):
    """Retain the declared preparation snapshot, not a fresh permission baseline."""
    path=science.regular(Path(work)/'preparation.json',Path.cwd())
    if commitment is None:
        commitment={'path':str(path),'sha256':custody._sha(path),'size':path.stat().st_size}
    if Path(commitment['path'])!=path:
        raise ValueError('foreign native preparation mode commitment')
    preparation=read_json(path)
    verify_emitted_value(commitment,preparation)
    if (preparation.get('kind')!=SCOPE or preparation.get('source_version')!=VERSION
            or preparation.get('source_commit')!=COMMIT
            or preparation.get('execution_authorized') is not False):
        raise ValueError('native preparation mode scope differs')
    return deepcopy(preparation['staged_inputs']['scientific_modes']),commitment


def staged_inputs(doc, bundles, work, *, initial_user=False, generated_products=(),mode_baseline=None):
    work = Path(work)
    expected = {}
    if doc['operation'] == 'sm-test':
        if doc['inputs']['config'] is not None:
            expected['config.dat'] = doc['inputs']['config']['sha256']
    else:
        prefix = bundles['payload']['root'].name
        expected = {prefix+'/'+rel: sha for rel, sha in bundles['payload']['manifest']['files'].items()}
    current_modes=scientific_modes(doc,bundles)
    if mode_baseline is None and (work/'preparation.json').exists():
        mode_baseline,_=prepared_modes(work)
    if mode_baseline is None:
        mode_baseline=current_modes
    if (not isinstance(mode_baseline,dict) or set(mode_baseline)!=set(expected)
            or any(type(m) is not int or not 0<=m<=0o777 for m in mode_baseline.values())
            or current_modes!=mode_baseline):
        raise ValueError('original native scientific input mode differs from preparation')
    expected_modes=deepcopy(mode_baseline)
    generated={}
    for pin in generated_products:
        target=science.regular(pin['path'],work)
        if not target.is_relative_to(work/'input'):
            raise ValueError('generated input product outside exact staged input root')
        rel=target.relative_to(work/'input').as_posix()
        verify_emitted([pin])
        if rel in expected:
            if pin['sha256']!=expected[rel]:raise ValueError('native figure overwrote an original scientific input')
            continue
        if rel in generated:raise ValueError('duplicate generated input product')
        generated[rel]=pin['sha256']
    if custody._workspace_inventory(work/'input') != {**expected,**generated}:
        raise ValueError('staged native scientific input membership/bytes differ')
    if any(stat.S_IMODE((work/'input'/rel).stat().st_mode)!=mode for rel,mode in expected_modes.items()):
        raise ValueError('staged native scientific input mode differs')
    user = custody._workspace_inventory(work/'user'); original = bundles['user']['manifest']['files']
    if initial_user and user != original:
        raise ValueError('initial native user copy differs')
    changes = {r: {'original': original.get(r), 'ending': user.get(r)}
               for r in sorted(set(original)|set(user)) if original.get(r) != user.get(r)}
    return {'scientific_files': expected, 'scientific_modes':expected_modes,
            'generated_input_products':list(generated_products), 'user_files': user, 'user_changes': changes,
            'scope': 'finite current checkpoints, not continuous native read tracing'}


def generated_input_products(observed, bundles, work):
    """Exact observed savefig products; original input commitments stay separate.

    Reconcile the renderer census before calling this helper. Every contributing
    script must be one of the original copied scientific inputs with exact bytes.
    No directory, suffix or marker-wide exception is introduced.
    """
    work=Path(work);products={}
    if observed.get('operation')!='rivet-plots':return []
    original={bundles['payload']['root'].name+'/'+rel:sha
              for rel,sha in bundles['payload']['manifest']['files'].items()}
    calls={(r['script'],r['sha256']):r for r in observed.get('renderer_calls',[])}
    for receipt in observed.get('render_receipts',[]):
        script=science.regular(receipt['script'],work)
        if not script.is_relative_to(work/'input'):
            raise ValueError('native input-root product requires original copied script')
        rel=script.relative_to(work/'input').as_posix()
        if (original.get(rel)!=receipt['script_sha256'] or custody._sha(script)!=original[rel]
                or (str(script),receipt['script_sha256']) not in calls or receipt.get('status')!='returned'):
            raise ValueError('native input-root product script/source differs')
        if receipt.get('native_multiprocess') is not True and any(
                Path(save['path']).is_relative_to(work/'input') for save in receipt['saves']):
            from ravel.physics.contur_companion_worker import serial_products
            directory=receipt.get('plot_dir',calls[(str(script),receipt['script_sha256'])]['directory'])
            native_targets=serial_products(script,directory,work)
            fields=lambda row:(row['path'],row['sha256'],row['size'])
            if sorted(map(fields,native_targets))!=sorted(map(fields,receipt['saves'])):
                raise ValueError('native serial product population differs from source declarations')
        for save in receipt['saves']:
            target=science.regular(save['path'],work)
            if not target.is_relative_to(work/'input'):continue
            if save.get('status')!='written':raise ValueError('native input-root figure failed')
            verify_emitted([save])
            if str(target) in products and products[str(target)]!=save:
                raise ValueError('native input-root product has contradictory commitments')
            products[str(target)]=save
    return [products[key] for key in sorted(products)]


def materialize(task, base, work):
    path, doc, runtime, bundles, files = admission(task, base)
    work = Path(work).absolute()
    for bundle in bundles.values():
        original = bundle['root'].resolve()
        if work.resolve().is_relative_to(original) or original.is_relative_to(work.resolve()):
            raise ValueError('native workspace must be disjoint from original committed roots')
    if any(p.is_symlink() for p in (work, *work.parents)):
        raise ValueError('ordinary native workspace cannot traverse aliases')
    copied=[bundles['user']['root']/rel for rel in bundles['user']['manifest']['files']]
    if doc['operation']=='sm-test':
        if doc['inputs']['config'] is not None:copied.append(custody._pin(doc['inputs']['config'],path.parent))
    else:copied.extend(bundles['payload']['root']/rel for rel in bundles['payload']['manifest']['files'])
    for supplied in copied:supplied_mode(supplied)
    mode_baseline=scientific_modes(doc,bundles)
    work.mkdir(parents=True, exist_ok=False); (work/'input').mkdir(); (work/'user').mkdir()
    for rel in bundles['user']['manifest']['files']:
        target = work/'user'/rel; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundles['user']['root']/rel, target)
    if doc['operation'] == 'sm-test':
        if doc['inputs']['config'] is not None:
            shutil.copy2(custody._pin(doc['inputs']['config'], path.parent), work/'input/config.dat')
    else:
        payload = bundles['payload']
        for rel in payload['manifest']['files']:
            target = work/'input'/payload['root'].name/rel; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(payload['root']/rel, target)
    resolved = resolved_document(doc, path.parent)
    emitted = [write_new(work/'native-input.json', resolved)]
    emitted.append(write_new(work/'preparation.json', {'kind': SCOPE, 'inputs': {str(p): custody._sha(p) for p in files},
        'source_version': VERSION, 'source_commit': COMMIT, 'arguments': arguments(resolved, bundles, work),
        'installed_distribution_version': runtime['installed_distribution_version'],
        'staged_inputs': staged_inputs(resolved, bundles, work, initial_user=True,mode_baseline=mode_baseline), 'execution_authorized': False}))
    verify_emitted(emitted)
    verify_emitted_value(emitted[0],resolved)
    staged_inputs(resolved,bundles,work,initial_user=True,mode_baseline=mode_baseline)
    verify_emitted(emitted)
    return resolved, emitted


def arguments(doc, bundles, work):
    o = doc['options']; work = Path(work)
    args = ['--outputdir', str(work/'native-output'), '--log', str(work/'contur.log')]
    if o['offline']: args.append('--offline')
    for key, flag in [('only_analyses','--ana-match'), ('veto_analyses','--ana-unmatch')]:
        for pattern in o.get(key, []): args += [flag, pattern]
    if doc['operation'] == 'sm-test':
        args += ['--sm-prediction', o['prediction']]
        if o['graphics']: args.append('--graphics')
        if o['use_spey']: args.append('--spey')
        if doc['inputs']['config'] is not None: args += ['--config', str(work/'input/config.dat')]
    elif doc['operation'] == 'herwig-xs-br':
        args += [str(work/'input'/bundles['payload']['root'].name), '--mceg', 'herwig', '--seed', str(o['seed']), '--tag', o['tag'], '--tolerance', str(o['tolerance'])]
        args += [flag for key,flag in XS_FLAGS.items() if o[key]]
    elif doc['operation'] == 'map-plots':
        args += [str(work/'input'/bundles['payload']['root'].name/doc['inputs']['database']), *o['variables'],
                 '--levels', *map(str,o['levels']), '--format', o['format'], '--ilevel', str(o['ilevel']),
                 '--iorder', str(o['iorder']), '--isigma', str(o['isigma']), '--style', o['style']]
        if o['slice']: args += ['--slice', ' '.join(str(v) for pair in o['slice'].items() for v in pair)]
        for key,flag in [('save_plots','--save-plots'),('databg','--databg'),('no_exp','--no-exp'),('pools','--pools')]:
            if o[key]: args.append(flag)
    else:
        args += ['--indir',str(work/'input'/bundles['payload']['root'].name), '--resultsfile', doc['inputs']['database'],
                 '--cores',str(doc['renderer_cores']), '--cls',str(o['cls'])]
        if o['runpoint'] is not None: args += ['--runpoint',o['runpoint']]
        for key,flag in [('databg','--databg'),('no_exp','--no-exp'),('include_none','--includenone')]:
            if o[key]: args.append(flag)
    return args


def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd/science.PLAN).is_file():
            selected = science.verify_worker(rd); spec = science.execution_spec(rd)
            if spec['mode'] != 'contur-companion' or spec['task'] != task or Path(output).resolve() != (rd/selected['output_directory']).resolve():
                raise ValueError('companion differs from exact approved ordinary worker')
            return rd, selected
    raise ValueError('companion native dispatch requires approved supervised ordinary worker')


def run(task, base, output):
    rd, selected = _approved(task, output)
    if execution_seconds(task, base) > selected['max_seconds']:
        raise ValueError('native plus readback budget exceeds approved stage')
    original = {str(p): custody._sha(p) for p in inputs(task, base)}
    out = Path(output).absolute(); out.mkdir(parents=True, exist_ok=True)
    resolved, emitted = materialize(task, base, out/'contur-companion-work')
    work = out/'contur-companion-work'
    mode_baseline,preparation_pin=prepared_modes(work,emitted[1])
    from ravel.physics.reinterpret_db import execute_native
    worker = Path(__file__).with_name('contur_companion_worker.py')
    command = [resolved['runtime']['python']['path'], '-B', '-X', 'pycache_prefix='+str(work/'bytecode-cache'),
               str(worker), '--input', str(work/'native-input.json'), '--work', str(work), '--rundir', str(rd)]
    native = execute_native(command, out, resolved)
    from ravel.physics.contur_companion_worker import reconcile
    observation = read_json(work/'native-observation.json')
    reconcile(resolved, observation, work)
    _, _, _, bundles, _ = admission(task, base)
    ending = staged_inputs(resolved, bundles, work,
                           generated_products=generated_input_products(observation,bundles,work),mode_baseline=mode_baseline)
    result = {'kind':'native-contur-companion', 'status':'passed', 'status_scope':SCOPE,
        'physics_validated':False, 'calibration_qualified':False, 'original_task_complete':False,
        'operation':resolved['operation'], 'source':resolved['source'], 'native_execution':native,
        'observation':observation, 'staged_after_readback':ending,
        'limitations':['Original native quantities and plotted results only; no calibration, reproduction or comparative superiority.',
            'Input/runtime checkpoints and loaded Python-module observation do not establish every native read or a hermetic OS/ABI.',
            'Native map interpolation is not fresh evaluation; opaque pickle is not unpickled by RAVEL.',
            'Herwig parser uncertainty is unavailable; native SM theory covariance remains diagonal.']}
    emitted.append(write_new(out/'contur-companion-results.json', result))
    if original != {str(p): custody._sha(p) for p in inputs(task, base)}:
        raise ValueError('original companion input/source/runtime changed')
    verify_emitted(emitted)
    if read_json(work/'native-observation.json') != observation:
        raise ValueError('native observation changed before public delivery')
    reconcile(resolved, observation, work)
    staged_inputs(resolved,bundles,work,generated_products=generated_input_products(observation,bundles,work),mode_baseline=mode_baseline)
    verify_emitted_value(emitted[-1],result)
    return result


def prepare(input_file, review_policy, output, *, approval_mode='physicist'):
    path = Path(input_file).absolute(); task = {'input':str(path)}
    _, doc, _, _, files = admission(task, path.parent)
    original = {str(p):custody._sha(p) for p in files}
    spec = {'schema_version':2, 'mode':'contur-companion', 'source':doc['source'],
        'assumptions':[SCOPE, 'Released native companion calculations and plots, not a replacement likelihood.',
            'Complete source/reference/runtime/input populations bound; scientific applicability and uncertainty qualification remain separate.',
            'No generation, contur-init, training, automatic retry, or cross-engine statistical combination.'],
        'max_seconds':execution_seconds(task,path.parent), 'approval_mode':approval_mode, 'task':task,
        'max_attempts':1, 'review_policy':read_json(science.regular(review_policy,path.parent))}
    science.validate(spec)
    if spec['review_policy']['policy']['max_redos'] != 0:
        raise ValueError('companion permits no automatic redo')
    emitted = write_new(output,spec)
    if original != {str(p):custody._sha(p) for p in inputs(task,path.parent)}:
        raise ValueError('companion input changed during preparation')
    verify_emitted_value(emitted,spec)
    return spec


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True); parser.add_argument('--review-policy',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    prepare(args.input,args.review_policy,args.out)
    return 0


if __name__ == '__main__':
    main()
