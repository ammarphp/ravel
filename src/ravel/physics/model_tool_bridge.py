"""Supervised source-bound UFO parameter and tree process validation through MG5.

Full UFO Python is executable trusted source. Native checks and independently
observed cards/kinematics establish a scoped numerical witness, not UV validity.
No event generation, CLI process interpolation, implicit restrictions or widths.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ravel.validation import model_tool_witness as witness

EXCLUDED = {'.git', '__pycache__', '.DS_Store'}
SCOPE = 'Source-bound full-UFO effective parameters and deterministic native tree 2-to-2 process consistency'


def _keys(obj, names, label):
    if not isinstance(obj, dict) or set(obj) != set(names):
        raise ValueError(label + ' requires exactly ' + ', '.join(sorted(names)))


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def _regular(name, base, directory=False):
    p = Path(name).expanduser()
    p = p if p.is_absolute() else Path(base)/p
    if any(x.is_symlink() for x in (p, *p.parents)) or not (p.is_dir() if directory else p.is_file()):
        raise ValueError('requires a regular non-symlink ' + str(p))
    return p.resolve()


def _pin(pin, base):
    _keys(pin, ('path', 'sha256'), 'file pin')
    if not isinstance(pin['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256']):
        raise ValueError('invalid source hash')
    p = _regular(pin['path'], base)
    if _hash(p) != pin['sha256']:
        raise ValueError('source pin changed: ' + str(p))
    return p


def _read(path):
    from ravel.workflow.state_io import read_json
    return read_json(path)


def _write(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')


def source_tree(root):
    """Finite source bytes; internal file aliases become regular snapshot files."""
    root = Path(root).resolve()
    rows = {}
    for p in sorted(root.rglob('*')):
        relative = p.relative_to(root)
        if any(x in EXCLUDED for x in relative.parts) or p.suffix in ('.pyc', '.pyo', '.pkl'):
            continue
        if p.is_symlink() and (p.is_dir() or not p.resolve().is_relative_to(root) or not p.is_file()):
            raise ValueError('source alias is not an internal regular file: ' + str(p))
        if p.is_file():
            rows[relative.as_posix()] = _hash(p)
    if not rows or len(rows) > 20000:
        raise ValueError('source tree must contain 1..20000 bounded files')
    return {'schema_version': 1, 'files': rows}


def _tree(spec, base):
    _keys(spec, ('root', 'manifest'), 'source tree')
    root = _regular(spec['root'], base, directory=True)
    manifest = _pin(spec['manifest'], base)
    doc = _read(manifest)
    _keys(doc, ('schema_version', 'files'), 'tree manifest')
    if doc['schema_version'] != 1 or doc != source_tree(root):
        raise ValueError('source tree differs from the declared complete source census')
    return root, manifest, [root/name for name in doc['files']]


def validate(task):
    _keys(task, ('config',), 'model-tool-bridge task')
    if not isinstance(task['config'], str) or not task['config'].strip():
        raise ValueError('source-bound bridge config path required')
    return dict(task)


def validate_config(c):
    _keys(c, ('schema_version', 'source', 'runtime', 'model_tree', 'trusted_ufo_python',
              'parameter_card', 'processes', 'seeds', 'energy_gev', 'max_seconds', 'max_ram_mib', *(['spectrum_origin'] if 'spectrum_origin' in c else [])), 'bridge config')
    if type(c['schema_version']) is not int or c['schema_version'] != 1 or c['trusted_ufo_python'] is not True:
        raise ValueError('explicit trusted UFO Python source and schema1 required')
    if not isinstance(c['source'], str) or not c['source'].strip():
        raise ValueError('source attribution is required')
    _keys(c['runtime'], ('madgraph_tree', 'python', 'python_manifest'), 'runtime')
    if not isinstance(c['processes'], list) or not 1 <= len(c['processes']) <= 4:
        raise ValueError('supply 1..4 tree processes')
    ids = set()
    for p in c['processes']:
        _keys(p, ('id', 'initial_pdgs', 'final_pdgs', 'orders', 'forbidden_pdgs'), 'process')
        if not isinstance(p['id'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', p['id']) or p['id'] in ids:
            raise ValueError('unique simple process identity required')
        ids.add(p['id'])
        for field in ('initial_pdgs', 'final_pdgs'):
            if not isinstance(p[field], list) or len(p[field]) != 2 or any(type(x) is not int or not 0 < abs(x) < 1000000000 for x in p[field]):
                raise ValueError('explicit nonzero PDGs for a two-to-two tree process required')
        if (not isinstance(p['forbidden_pdgs'], list) or len(set(p['forbidden_pdgs'])) != len(p['forbidden_pdgs'])
                or any(type(x) is not int or not 0 < x < 1000000000 for x in p['forbidden_pdgs'])):
            raise ValueError('invalid forbidden PDGs')
        if (not isinstance(p['orders'], dict) or not p['orders'] or len(p['orders']) > 8
                or any(not isinstance(k, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,15}', k)
                       or type(v) is not int or not 0 <= v <= 8 for k, v in p['orders'].items())):
            raise ValueError('explicit bounded coupling orders required')
    if (not isinstance(c['seeds'], list) or not 2 <= len(c['seeds']) <= 8 or len(set(c['seeds'])) != len(c['seeds'])
            or any(type(x) is not int or not 0 <= x <= 2147483647 for x in c['seeds'])):
        raise ValueError('2..8 unique deterministic integer seeds required')
    if not 0 < witness.finite(c['energy_gev'], 'energy') <= 100000:
        raise ValueError('invalid finite GeV energy')
    if type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 900:
        raise ValueError('native time ceiling must be1..900seconds')
    if type(c['max_ram_mib']) is not int or not 512 <= c['max_ram_mib'] <= 8192:
        raise ValueError('native sampled RAM ceiling must be512..8192MiB')
    return c


def _load(task, base):
    validate(task)
    p = _regular(task['config'], base)
    return p, validate_config(_read(p))


def inputs(task, base):
    p, c = _load(task, base)
    mg, mg_manifest, mgfiles = _tree(c['runtime']['madgraph_tree'], p.parent)
    model, model_manifest, modelfiles = _tree(c['model_tree'], p.parent)
    if not re.search(r'^version\s*=\s*2\.9\.27\s*$', (mg/'VERSION').read_text(), re.M):
        raise ValueError('qualified native API is MG5 2.9.27')
    for name in ('parameters.py', 'particles.py', 'vertices.py', 'couplings.py', 'object_library.py', 'lorentz.py', '__init__.py'):
        if not (model/name).is_file():
            raise ValueError('missing full source UFO file ' + name)
    python = _pin(c['runtime']['python'], p.parent)
    if not os.access(python, os.X_OK):
        raise ValueError('native Python is not executable')
    support = _pin(c['runtime']['python_manifest'], p.parent)
    runtime = _read(support)
    if runtime['python_sha256'] != c['runtime']['python']['sha256'] or not runtime['files']:
        raise ValueError('Python support manifest differs from executable')
    deps = [_pin(v, p.parent) for v in runtime['files']]
    card = _pin(c['parameter_card'], p.parent)
    witness.card_values(card.read_text())
    if 'spectrum_origin' in c:
        from .model_specific_spectrum import origin_inputs
        deps += origin_inputs(c['spectrum_origin'],p.parent,c['parameter_card'],c['model_tree'])
    package_sources = list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return sorted(set([p, mg_manifest, model_manifest, python, support, card,
                       *(x.resolve() for x in package_sources+mgfiles+modelfiles), *deps]))


def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected = science.verify_worker(rd)
            spec = science.execution_spec(rd)
            if spec['mode'] != 'model-tool-bridge' or spec['task'] != task or Path(output).resolve() != (rd/selected['output_directory']).resolve():
                raise ValueError('dynamic tool bridge differs from its exact approved worker task/output')
            return rd, selected
    raise ValueError('dynamic UFO execution requires its approved supervised worker')


def _copy(spec, base, destination):
    root, _, _ = _tree(spec, base)
    manifest = source_tree(root)
    destination.mkdir()
    for name in manifest['files']:
        q = destination/name
        q.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, q)
    if source_tree(destination) != manifest:
        raise ValueError('private runtime/model copy differs from original source')


def imported_sources(rows, allowed):
    """Require a nonempty unique census of actual imports within approved bytes."""
    if not isinstance(rows, list) or not rows:
        raise ValueError('native imported-source census is empty')
    seen = set()
    for row in rows:
        _keys(row, ('path', 'sha256'), 'imported source row')
        if (not isinstance(row['path'], str) or row['path'] in seen
                or allowed.get(row['path']) != row['sha256']):
            raise ValueError('native imported an unbound, duplicate or changed source/dependency file')
        seen.add(row['path'])
    return len(seen)


def run(task, base, output):
    rd, selected = _approved(task, output)
    path, c = _load(task, base)
    if c['max_seconds'] > selected['max_seconds']:
        raise ValueError('native bridge exceeds approved supervisor time')
    files = inputs(task, base)
    before = {str(p): _hash(p) for p in files}
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = rd/'work/model-tool-bridge'/out.name
    if work.exists() or any(x.is_symlink() for x in (work, *work.parents)):
        raise ValueError('fresh regular selected-attempt workspace required')
    work.mkdir(parents=True)
    _copy(c['runtime']['madgraph_tree'], path.parent, work/'madgraph')
    _copy(c['model_tree'], path.parent, work/'model_source')
    card = _pin(c['parameter_card'], path.parent)
    shutil.copyfile(card, work/'param_card.dat')
    request = {'config': c, 'madgraph': str(work/'madgraph'), 'model': str(work/'model_source'),
               'card': str(work/'param_card.dat'), 'source_sha256': before[str(path)]}
    _write(out/'native-input.json', request)
    from ravel.physics.reinterpret_db import execute_native
    receipt = execute_native([str(_pin(c['runtime']['python'], path.parent)), '-I', '-B', str(Path(__file__).resolve()),
                              '--native-worker', str(out/'native-input.json'), '--out', str(out)], out, c)
    native = _read(out/'native-model-checks.json')
    if native['source_sha256'] != before[str(path)] or native['card_sha256'] != c['parameter_card']['sha256']:
        raise ValueError('native receipt is not bound to the supplied config/card')
    allowed = dict(before)
    for spec, copied in ((c['runtime']['madgraph_tree'], work/'madgraph'), (c['model_tree'], work/'model_source')):
        root, _, _ = _tree(spec, path.parent)
        allowed.update({str(copied/name): digest for name, digest in source_tree(root)['files'].items()})
    imported_sources(native['imported_source_files'], allowed)
    checks = witness.adjudicate(native, c, card.read_text())
    if before != {str(p): _hash(p) for p in inputs(task, base)}:
        raise ValueError('original scientific input/runtime changed during native execution')
    result = {'status': 'passed' if checks['passed'] else 'failed', 'physics_validated': False, 'scope': SCOPE,
              'source': c['source'], 'checks': checks, 'native_execution': receipt,
              'native_artifacts': ['native-model-checks.json', 'native-input.json', 'native-execution.json'],
              'generated_events': 0, 'limitations': ['Tree2-to-2 numerical consistency only; no loops, generator integration, shower or detector validation.',
                  'Supplied full UFO and explicit card; no FeynRules derivation, UV-model validity or independent amplitude reference.',
                  'Native Python source/dependencies are bound; host OS/system libraries remain outside this finite capsule.',
                  'Massless/zero amplitudes cannot establish nonvacuous process checks; unsupported inputs remain failed evidence.']}
    _write(out/'model-tool-bridge.json', result)
    return result


def _complex(value):
    value = complex(value)
    if not math.isfinite(value.real) or not math.isfinite(value.imag):
        raise ValueError('native model emitted nonfinite parameter/coupling')
    return {'real': value.real, 'imag': value.imag}


def _snapshot(model):
    params = model.get('parameter_dict')
    return {'external_parameters': [{'name': p.name, 'block': p.lhablock.lower(), 'codes': list(p.lhacode),
                'observed_value': _complex(params[p.name])} for p in model.get('parameters')[('external',)]],
            'parameters': {k: _complex(v) for k, v in sorted(params.items())},
            'couplings': {k: _complex(v) for k, v in sorted(model.get('coupling_dict').items())}}


def _diagnostic_value(value, depth=0):
    """Retain raw return types without turning missing/nonfinite data into success."""
    if depth > 20:
        raise ValueError('native diagnostic nesting exceeds retained bound')
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {'nonfinite_float': repr(value)}
    if type(value) is complex:
        return {'real': _diagnostic_value(value.real,depth+1),
                'imag': _diagnostic_value(value.imag,depth+1)}
    if isinstance(value, (list, tuple)):
        if len(value) > 10000:
            raise ValueError('native diagnostic population exceeds retained bound')
        return [_diagnostic_value(item,depth+1) for item in value]
    if isinstance(value, dict):
        if len(value) > 10000:
            raise ValueError('native diagnostic mapping exceeds retained bound')
        return {str(key): (item.nice_string() if key == 'process' and hasattr(item,'nice_string')
                else _diagnostic_value(item,depth+1)) for key,item in value.items()}
    return {'unsupported_type': type(value).__name__, 'representation': repr(value)[:4096]}


def native_worker(request, out):
    """Runs only in the owned native process after approval and source copies."""
    import random
    os.environ.pop('HOME', None)
    sys.path.insert(0, request['madgraph'])
    from models import import_ufo
    from madgraph.core import base_objects
    from madgraph.various import process_checks
    from models.model_reader import ModelReader
    c = validate_config(request['config'])
    model = import_ufo.import_model(request['model'], restrict=False, complex_mass_scheme=False)
    required = model.get('parameters')[('external',)]
    supplied = witness.card_values(Path(request['card']).read_text())
    if any((p.lhablock.lower(), tuple(p.lhacode)) not in supplied for p in required):
        raise ValueError('supplied card misses UFO external parameters; native defaults are forbidden')
    reader = ModelReader(model)
    reader.set_parameters_and_couplings(request['card'], complex_mass_scheme=False)
    snapshot = _snapshot(reader)
    witness.effective_card(snapshot, supplied)
    original = process_checks.MatrixElementEvaluator
    snapshots, evaluations = [], []
    class ObservedEvaluator(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            snapshots.append(_snapshot(self.full_model))
        def evaluate_matrix_element(self, matrix_element, *args, **kwargs):
            result = super().evaluate_matrix_element(matrix_element, *args, **kwargs)
            p = kwargs.get('p')
            if result is not None and p is not None:
                proc = matrix_element.get('processes')[0]
                pdgs = [l.get('id') for l in sorted(proc.get('legs'), key=lambda l: l.get('number'))]
                m2 = result['m2'] if isinstance(result, dict) else result[0]
                evaluations.append({'ordered_leg_pdgs': pdgs, 'momenta_gev': [list(x) for x in p],
                    'ordered_leg_states': [l.get('state') for l in sorted(proc.get('legs'), key=lambda l: l.get('number'))],
                    'effective_orders': dict(proc.get('orders')),
                    'effective_forbidden_pdgs': list(proc.get('forbidden_particles')),
                    'effective_perturbation_couplings': list(proc.get('perturbation_couplings')),
                    'effective_masses_gev': {str(pdg): self.full_model.get_mass(pdg) for pdg in pdgs}, 'm2': float(m2)})
            return result
    process_checks.MatrixElementEvaluator = ObservedEvaluator
    checks = []
    observations = {'schema_version':1,'source_sha256':request['source_sha256'],
        'card_sha256':_hash(request['card']),'completed':False,'cases':[],
        'scope':'Partial native return/traces; no successful comparison, amplitude or model conclusion is inferred.'}
    diagnostic_path = Path(out)/'native-case-observations.json'
    _write(diagnostic_path,observations)
    for spec in c['processes']:
        if not set(spec['orders']) <= set(model.get('order_hierarchy')):
            raise ValueError('coupling order is absent from the source UFO')
        for pdg in spec['initial_pdgs']+spec['final_pdgs']+spec['forbidden_pdgs']:
            if model.get_particle(pdg) is None:
                raise ValueError('PDG is absent from the source UFO')
        for seed in c['seeds']:
            snapshots.clear(); evaluations.clear()
            legs = base_objects.LegList([base_objects.Leg({'id': p, 'state': i >= 2})
                        for i, p in enumerate(spec['initial_pdgs']+spec['final_pdgs'])])
            proc = base_objects.Process({'legs': legs, 'model': model, 'orders': spec['orders'],
                                        'forbidden_particles': spec['forbidden_pdgs']})
            options = {'energy': c['energy_gev'], 'events': None, 'skip_evt': 0}
            process_checks.clean_added_globals(process_checks.ADDED_GLOBAL)
            random.seed(seed)
            permutation = process_checks.check_processes(proc, param_card=request['card'], quick=False, options=options)[0]
            observed = {'process_id':spec['id'],'seed':seed,'native_process':proc.nice_string(),
                'phase':'permutation_completed','permutation_return_type':type(permutation).__name__,
                'permutation':_diagnostic_value(permutation),
                'evaluator_snapshots':_diagnostic_value(snapshots),'evaluations':_diagnostic_value(evaluations)}
            observations['cases'].append(observed)
            _write(diagnostic_path,observations)
            process_checks.clean_added_globals(process_checks.ADDED_GLOBAL)
            random.seed(seed)
            lorentz = process_checks.check_lorentz(proc, param_card=request['card'], options=options)
            observed.update(phase='lorentz_completed',lorentz_return_type=type(lorentz).__name__,
                lorentz=_diagnostic_value(lorentz),evaluator_snapshots=_diagnostic_value(snapshots),
                evaluations=_diagnostic_value(evaluations))
            _write(diagnostic_path,observations)
            if len(permutation) != 1 or len(lorentz) != 1 or not isinstance(lorentz[0]['results'], list):
                raise ValueError('native process has no nonvacuous permutation/Lorentz result')
            checks.append({'process_id': spec['id'], 'seed': seed, 'native_process': proc.nice_string(),
                'permutation': {'momenta_gev': permutation[0]['momenta'], 'values': permutation[0]['values'],
                                'native_difference': permutation[0]['difference'], 'native_passed': permutation[0]['passed']},
                'lorentz': {'m2_values': [r['m2'] for r in lorentz[0]['results']],
                            'native_evaluation_count': len(lorentz[0]['results'])},
                'evaluator_snapshots': list(snapshots), 'evaluations': list(evaluations)})
    imported = {}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            p = Path(filename).resolve()
            if p.is_file():
                imported[str(p)] = _hash(p)
    payload = {'schema_version': 1, 'source_sha256': request['source_sha256'], 'card_sha256': _hash(request['card']),
               'restriction_applied': False, 'model_point': snapshot, 'checks': checks,
               'imported_source_files': [{'path': p, 'sha256': digest} for p, digest in sorted(imported.items())],
               'native_python_version': sys.version, 'generated_events': 0}
    _write(Path(out)/'native-model-checks.json', payload)
    observations['completed'] = True
    _write(diagnostic_path,observations)


def runtime_inventory(out):
    """Metadata/file enumeration only; no UFO, generator or scientific import."""
    import importlib.metadata as metadata
    import sysconfig
    files, versions = set(), {}
    for dist in metadata.distributions():
        name = dist.metadata.get('Name', 'unknown')
        versions[name] = dist.version
        for row in dist.files or ():
            p = Path(dist.locate_file(row)).resolve()
            if p.is_file() and p.suffix not in ('.pyc', '.pyo'):
                files.add(p)
    for p in Path(sysconfig.get_path('stdlib')).rglob('*'):
        if 'site-packages' in p.parts or '__pycache__' in p.parts:
            continue
        if p.is_file() and p.suffix in ('.py', '.so', '.dylib'):
            files.add(p.resolve())
    _write(out, {'schema_version': 1, 'python_sha256': _hash(Path(sys.executable).resolve()),
        'python_version': sys.version, 'distributions': versions,
        'files': [{'path': str(p), 'sha256': _hash(p)} for p in sorted(files)],
        'scope': 'Finite installed Python sources and distribution files; OS libraries are outside this capsule.'})


def prepare(args):
    """Draft an immutable, source-bound general UFO request without model execution."""
    if not args.trust_ufo_python:
        raise ValueError('executing supplied UFO Python requires explicit --trust-ufo-python')
    rd = Path(args.rundir).expanduser().absolute()
    proposal = rd.with_name(rd.name+'-proposal')
    if rd.exists() or proposal.exists():
        raise ValueError('fresh study and proposal required; never reinitialize an existing run')
    mg = _regular(args.madgraph, Path.cwd(), directory=True)
    model = _regular(args.ufo, Path.cwd(), directory=True)
    python = _regular(args.python, Path.cwd())
    card = _regular(args.parameter_card, Path.cwd())
    witness.card_values(card.read_text())
    protocol = _read(_regular(args.processes, Path.cwd()))
    _keys(protocol, ('processes', 'seeds', 'energy_gev'), 'typed process protocol')
    proposal.mkdir(parents=True)
    def pin(p):
        return {'path': str(p), 'sha256': _hash(p)}
    def tree(root, name):
        manifest = proposal/name
        _write(manifest, source_tree(root))
        return {'root': str(root), 'manifest': pin(manifest)}
    support = proposal/'python-support.json'
    subprocess.run([str(python), '-I', '-B', str(Path(__file__).resolve()), '--runtime-inventory', str(support)],
                   check=True, timeout=120)
    c = {'schema_version': 1, 'source': args.source,
         'runtime': {'madgraph_tree': tree(mg, 'madgraph-source.json'), 'python': pin(python), 'python_manifest': pin(support)},
         'model_tree': tree(model, 'ufo-source.json'), 'trusted_ufo_python': True,
         'parameter_card': pin(card), **protocol, 'max_seconds': args.max_seconds, 'max_ram_mib': args.max_ram_mib}
    validate_config(c)
    document = proposal/'model-tool-bridge.json'
    _write(document, c)
    task = {'config': str(document)}
    inputs(task, proposal)
    policy = _read(_regular(args.review_policy, Path.cwd()))
    specification = {'schema_version': 2, 'mode': 'model-tool-bridge', 'source': args.source,
         'assumptions': ['The attributed supplied full UFO is trusted executable Python; the explicit card is the requested point, with no restriction or default substitution.',
             'Native seeded tree process checks and observed effective cards/kinematics establish only the sampled numerical consistency.',
             'UV model validity, independently calculated amplitudes/widths, generator integration and detector response remain separate requirements.'],
         'max_seconds': args.max_seconds+240, 'max_attempts': 1+policy['policy']['max_redos'],
         'approval_mode': args.approval_mode, 'review_policy': policy, 'task': task}
    spec = proposal/'science.json'
    _write(spec, specification)
    from ravel.workflow.science import plan
    plan(rd, spec)
    print('Prepared dynamic source-bound model bridge; review '+str(rd/'CHECKIN1.md')+'. No model calculation or events generated.')
    return 0


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == 'plan':
        parser = argparse.ArgumentParser(prog='ravel model-tool-bridge plan', description=__doc__)
        parser.add_argument('--madgraph', required=True); parser.add_argument('--python', required=True)
        parser.add_argument('--ufo', required=True); parser.add_argument('--parameter-card', required=True)
        parser.add_argument('--source', required=True); parser.add_argument('--processes', required=True,
            help='typed JSON with processes, deterministic seeds and energy_gev; no free-form CLI process string')
        parser.add_argument('--trust-ufo-python', action='store_true')
        parser.add_argument('--rundir', required=True); parser.add_argument('--review-policy', required=True)
        parser.add_argument('--max-seconds', type=int, default=300); parser.add_argument('--max-ram-mib', type=int, default=4096)
        parser.add_argument('--approval-mode', choices=('physicist', 'scripted_yes'), default='physicist')
        return prepare(parser.parse_args(arguments[1:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-worker'); parser.add_argument('--out'); parser.add_argument('--runtime-inventory')
    args = parser.parse_args(arguments)
    if args.runtime_inventory:
        runtime_inventory(args.runtime_inventory)
    elif args.native_worker and args.out:
        native_worker(_read(args.native_worker), args.out)
    else:
        parser.error('only the supervised private worker or metadata inventory entrypoint is supported')


if __name__ == '__main__':
    main()
