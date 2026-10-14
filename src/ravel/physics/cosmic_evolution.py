"""Ordinary source-bound CosmicIC/Nyx preparation, delivery and site-local steps.

Private writer/dirty-source prerequisites are explicit. Supplied source contracts
do not become physics certificates. No CAMB/CLASS substitution or remote job
submission is performed. Optional native commands run only in the live ordinary
worker; installed Ravel planning/Graph paths import no MPI/GPU library.
"""
from __future__ import annotations
from copy import deepcopy
import argparse
import hashlib
import math
from pathlib import Path
import shutil

from ravel.workflow import science, execution
from ravel.workflow.state_io import atomic_json
from . import cosmic_evolution_core as core

SCOPE = 'Complete declared source/card/IC/Nyx output custody; original whole-question scientific acceptance remains separate'
LIMITS = {'max_input_files', 'max_input_bytes', 'max_output_files', 'max_output_bytes',
          'max_seconds', 'cleanup_seconds', 'max_controller_bytes', 'max_controller_calls', 'handshake_seconds'}


def validate(task):
    core.keys(task, ('input',), 'cosmic-evolution task')
    if type(task['input']) is not str or not task['input']: raise ValueError('operation input path required')
    return deepcopy(task)


def validate_document(d):
    core.keys(d, ('schema_version', 'source', 'operation', 'original_requests', 'source_trees',
                  'writer_contract', 'cases', 'runtime', 'resources'), 'cosmic evolution')
    if type(d['schema_version']) is not int or d['schema_version'] != 1 or d['operation'] not in ('source-preparation', 'retained-delivery', 'site-local-execution'):
        raise ValueError('explicit schema1 source/prepared/retained/site-local operation required')
    if type(d['source']) is not str or not d['source'].strip(): raise ValueError('original source attribution required')
    core.keys(d['resources'], LIMITS, 'finite operation resources')
    for k, v in d['resources'].items(): core.integer(v, k)
    if d['resources']['max_seconds'] + d['resources']['cleanup_seconds'] > 86400:
        raise ValueError('ordinary86400s finite per-study ceiling')
    if d['resources']['handshake_seconds'] > d['resources']['max_seconds']:
        raise ValueError('declared handshake budget exceeds whole study')
    if type(d['original_requests']) is not list or not d['original_requests']:
        raise ValueError('whole original request/variant commitments required')
    if type(d['source_trees']) is not list: raise ValueError('explicit complete native source trees required')
    if type(d['cases']) is not list or not d['cases'] or len(d['cases']) > d['resources']['max_input_files']:
        raise ValueError('complete finite declared case population required')
    ids = []
    for case in d['cases']:
        core.keys(case, ('id', 'ic_card', 'nyx_card', 'transfer', 'ic', 'scope', 'outputs', 'retained_root', 'phases', 'data_files'), 'full original case')
        ids.append(core.name(case['id']))
        core.keys(case['scope'], ('ic_shape', 'nyx_shape', 'initial_redshift', 'final_redshift', 'fields', 'redshifts', 'analysis_redshifts', 'checkpoint', 'other_obligations'), 'case scope')
        for k in ('ic_shape', 'nyx_shape'):
            shape = case['scope'][k]
            if shape is not None and (type(shape) is not list or len(shape) != 3): raise ValueError('complete original3D geometry required')
            if shape is not None:
                for v in shape: core.integer(v, k)
        if case['scope']['ic_shape'] is None: raise ValueError('IC population remains explicit even for Nyx-only delivery')
        for k in ('initial_redshift', 'final_redshift'):
            if case['scope'][k] is not None and core.number(case['scope'][k], k) < 0: raise ValueError('nonnegative cosmological redshift required')
        for k in ('fields', 'redshifts', 'analysis_redshifts', 'other_obligations'):
            value = case['scope'][k]
            if type(value) is not list or len(value) != len(set(value)): raise ValueError('complete distinct source scope required')
        if any(type(v) is not str or not v for v in [*case['scope']['fields'], *case['scope']['other_obligations']]): raise ValueError('explicit output/remaining obligation identities required')
        for v in [*case['scope']['redshifts'], *case['scope']['analysis_redshifts']]: core.number(v, 'output redshift')
        if type(case['scope']['checkpoint']) is not bool: raise ValueError('explicit original checkpoint declaration required')
        if type(case['phases']) is not list: raise ValueError('explicit phase population required')
        if type(case['data_files']) is not list: raise ValueError('complete active physics-data file bindings required')
        for row in case['data_files']:
            core.keys(row, ('card', 'key', 'file'), 'native data binding')
            if row['card'] not in ('ic', 'nyx') or type(row['key']) is not str: raise ValueError('exact original card/data key required')
        core.keys(case['outputs'], ('required_files', 'text_markers', 'scope'), 'complete native output contract')
        if case['outputs']['scope'] != case['scope']: raise ValueError('native output denominator must equal whole case scope')
        if type(case['outputs']['required_files']) is not list or not case['outputs']['required_files']:
            raise ValueError('complete explicit native output files required')
        for f in case['outputs']['required_files']: core.relative(f)
        if type(case['outputs']['text_markers']) is not list: raise ValueError('full declared output text marker list required')
        seen = []
        for phase in case['phases']:
            core.keys(phase, ('id', 'kind', 'payload', 'argv', 'copies', 'ranks', 'nodes', 'gpus_per_node', 'max_seconds', 'ic_handoff'), 'source-defined phase')
            seen.append(core.name(phase['id']))
            if phase['kind'] not in ('build', 'cosmicic', 'nyx'): raise ValueError('original build/IC/Nyx phase required')
            if type(phase['payload']) is dict and set(phase['payload']) == {'build_phase', 'path'}:
                prior = [p for p in case['phases'][:len(seen)-1] if p['id'] == phase['payload']['build_phase'] and p['kind'] == 'build']
                if len(prior) != 1: raise ValueError('derived payload requires an earlier declared complete build phase')
                core.relative(phase['payload']['path'])
            else: core.keys(phase['payload'], ('path', 'sha256', 'size'), 'native payload commitment')
            for k in ('ranks', 'nodes', 'max_seconds'): core.integer(phase[k], k)
            core.integer(phase['gpus_per_node'], 'GPUs per node', 0)
            if phase['nodes'] > phase['ranks'] or phase['max_seconds'] > d['resources']['max_seconds']:
                raise ValueError('phase resource/allocation population differs')
            if type(phase['argv']) is not list or any(type(x) is not str or '\x00' in x for x in phase['argv']): raise ValueError('literal native argv required; no shell')
            if type(phase['copies']) is not list: raise ValueError('finite explicit scratch inputs required')
            targets = []
            for row in phase['copies']:
                core.keys(row, ('file', 'to'), 'source-bound scratch copy'); targets.append(core.relative(row['to']))
            if len(set(targets)) != len(targets): raise ValueError('scratch destination collision')
            if phase['ic_handoff'] is not None:
                core.keys(phase['ic_handoff'], ('file_list_to', 'chunks_to'), 'complete IC handoff')
                core.relative(phase['ic_handoff']['file_list_to'])
                if phase['kind'] != 'nyx' or type(phase['ic_handoff']['chunks_to']) is not list:
                    raise ValueError('only Nyx may consume the complete IC handoff')
                for target in phase['ic_handoff']['chunks_to']: core.relative(target)
                if len(set([phase['ic_handoff']['file_list_to'], *phase['ic_handoff']['chunks_to'], *targets])) != 1 + len(phase['ic_handoff']['chunks_to']) + len(targets):
                    raise ValueError('IC/source scratch destination collision')
        if len(set(seen)) != len(seen): raise ValueError('unique phase identities required')
        if case['ic'] is not None and 'generated_phase' in case['ic']:
            core.keys(case['ic'], ('generated_phase', 'file_list', 'shape'), 'fresh generated IC declaration')
            core.relative(case['ic']['file_list'])
            found = [p for p in case['phases'] if p['id'] == case['ic']['generated_phase'] and p['kind'] == 'cosmicic']
            if len(found) != 1 or any(p['kind'] == 'nyx' and i <= case['phases'].index(found[0]) for i, p in enumerate(case['phases'])):
                raise ValueError('fresh IC generation must precede every consuming Nyx phase')
            if d['operation'] == 'retained-delivery': raise ValueError('retained operation requires actual retained IC commitments')
    if len(set(ids)) != len(ids): raise ValueError('no duplicate/dropped original case identities')
    if sum(p['max_seconds'] for c in d['cases'] for p in c['phases']) > d['resources']['max_seconds']:
        raise ValueError('full phase wall-time denominator exceeds declared study budget')
    return deepcopy(d)


def _effective(rows):
    result = {}
    for row in rows:
        if row['key'] in result and result[row['key']] != row['value']:
            raise ValueError('conflicting native card values require actual source/revised prescription')
        result[row['key']] = row['value']
    return result


def _vector(values, key):
    if key not in values: raise ValueError('required native card field missing: ' + key)
    return [core.number(float(v), key) for v in values[key].split()]


def _capture(task, base):
    path = science.regular(validate(task)['input'], base)
    # The first bounded config buffer is the exact one validated/used below.
    from ravel.workflow.operation_resources import document_pin
    p = document_pin(path); d = validate_document(core.loads(p['text'].encode()))
    capture = core.Capture(path.parent, d['resources'])
    _, consumed = capture.read({'path': str(path), 'sha256': p['sha256'], 'size': len(p['text'].encode())}, text=True)
    if consumed != p['text'].encode(): raise ValueError('configuration consumption changed')
    for pin in d['original_requests']: capture.read(pin, text=True)
    for tree in d['source_trees']: capture.tree(tree)
    writer = capture.json(d['writer_contract']) if d['writer_contract'] is not None else None
    if writer is not None:
        for pin in writer.get('source_evidence', []): capture.read(pin, text=True)
        if not d['source_trees'] or not writer.get('source_evidence'):
            raise ValueError('writer profile needs actual complete native source and writer evidence')
        roots = [Path(r).absolute() for r in capture.trees]
        for pin in writer['source_evidence']:
            f, _ = capture.read(pin, text=True)
            if not any(f.is_relative_to(r) for r in roots): raise ValueError('writer evidence is not in complete supplied native source')
    observations = []; prerequisites = []
    for case in d['cases']:
        ic_path, raw = capture.read(case['ic_card'], text=True); ic_rows = core.card(raw); ic_values = _effective(ic_rows)
        if _vector(ic_values, 'np') != [case['scope']['ic_shape'][0]] or len(set(case['scope']['ic_shape'])) != 1:
            raise ValueError('original CosmicIC np/full cubic population differs')
        if _vector(ic_values, 'z_in') != [case['scope']['initial_redshift']]: raise ValueError('IC initial redshift differs')
        nyx_rows = None
        if case['nyx_card'] is not None:
            nyx_path, raw = capture.read(case['nyx_card'], text=True); nyx_rows = core.card(raw); vals = _effective(nyx_rows)
            if (_vector(vals, 'amr.n_cell') != case['scope']['nyx_shape'] or
                    _vector(vals, 'nyx.initial_z') != [case['scope']['initial_redshift']] or
                    _vector(vals, 'nyx.final_z') != [case['scope']['final_redshift']] or
                    _vector(vals, 'nyx.plot_z_values') != case['scope']['redshifts'] or
                    vals.get('amr.plot_vars', '').split() + vals.get('amr.derive_plot_vars', '').split() != case['scope']['fields'] or
                    _vector(vals, 'nyx.analysis_z_values') != case['scope']['analysis_redshifts'] or
                    vals.get('amr.checkpoint_files_output') != str(int(case['scope']['checkpoint']))):
                raise ValueError('full original Nyx grid/field/redshift/analysis/checkpoint population differs')
            if case['scope']['ic_shape'] != case['scope']['nyx_shape']:
                prerequisites.append(case['id'] + ': complete matching ICs required;64 cannot discharge1024')
            for key in ('nyx.uvb_rates_file', *(['nyx.inhomo_zhi_file'] if vals.get('nyx.inhomo_reion') == '1' else [])):
                if key in vals and not any(r['card'] == 'nyx' and r['key'] == key for r in case['data_files']):
                    prerequisites.append(case['id'] + ': actual active native physics-data input missing: ' + key)
        for row in case['data_files']:
            values = ic_values if row['card'] == 'ic' else _effective(nyx_rows or [])
            original_path = ic_path if row['card'] == 'ic' else nyx_path
            if row['key'] not in values: raise ValueError('native data key absent from original card')
            selected = Path(values[row['key']]); selected = selected if selected.is_absolute() else original_path.parent / selected
            actual, _ = capture.read(row['file'])
            if selected.absolute() != actual: raise ValueError('actual source-bound data file/card association differs')
        transfer = case['transfer']; _, raw = capture.read(transfer['file'], text=True)
        t = core.transfer(raw, transfer); capture.read(transfer['normalization'], text=True)
        if transfer['redshift'] != case['scope']['initial_redshift']: raise ValueError('transfer generation redshift differs')
        ic = None
        if case['ic'] is not None:
            if case['ic']['shape'] != case['scope']['ic_shape']: raise ValueError('full IC population/shape differs')
            if 'generated_phase' in case['ic']:
                ic = {'generated_phase': case['ic']['generated_phase'], 'shape': case['ic']['shape'], 'pending_actual_native_products': True}
            elif writer is not None: ic = core.binary_ic(capture, case['ic'], writer)
            else:
                capture.read(case['ic']['file_list'], text=True)
                for pin in case['ic']['chunks']: capture.read(pin)
        for phase in case['phases']:
            if 'build_phase' not in phase['payload']: capture.read(phase['payload'])
            for row in phase['copies']: capture.read(row['file'])
        if case['nyx_card'] is not None and case['ic'] is None:
            prerequisites.append(case['id'] + ': complete actual IC binary population is missing')
        if d['operation'] == 'retained-delivery':
            if type(case['retained_root']) is not str: raise ValueError('actual retained output root required')
            root = Path(case['retained_root']); root = root if root.is_absolute() else path.parent / root
            retained = core.output_inventory(root, d['resources'])
            capture.tree({'root': str(root), 'files': [{'path': str(root / row['path']), 'sha256': row['sha256'], 'size': row['size']} for row in retained]})
        observations.append({'id': case['id'], 'scope': case['scope'], 'original_ic_card_rows': ic_rows,
                             'original_nyx_card_rows': nyx_rows, 'transfer': t, 'ic': ic})
    if writer is None: prerequisites.append('Authentic CosmicIC generator/writer source/full closure missing; PrintFormat6 is unavailable')
    runtime = d['runtime']
    if runtime is not None:
        core.keys(runtime, ('python', 'slurm', 'schemas', 'version', 'allocation', 'environment', 'files'), 'site native runtime')
        capture.read(runtime['python']); schemas = capture.json(runtime['schemas'])
        core.keys(runtime['slurm'], ('srun', 'scontrol', 'scancel'), 'installed Slurm commands')
        for pin in [*runtime['slurm'].values(), *runtime['files']]: capture.read(pin)
        environment_keys = {'PATH', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'OMP_NUM_THREADS', 'OMP_PLACES', 'OMP_PROC_BIND',
                            'MPICH_GPU_SUPPORT_ENABLED', 'MPICH_GPU_IPC_ENABLED', 'CUDA_VISIBLE_DEVICES',
                            'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'}
        if type(runtime['environment']) is not dict or any(k not in environment_keys or type(v) is not str for k, v in runtime['environment'].items()): raise ValueError('explicit source-bound startup environment required; allocation identity cannot be overridden')
        if type(runtime['version']) is not str or not runtime['version']: raise ValueError('exact installed Slurm version required')
    else: schemas = None
    if d['operation'] == 'site-local-execution' and (prerequisites or runtime is None or any(not c['phases'] for c in d['cases'])):
        raise ValueError('site execution prerequisites unresolved: ' + '; '.join(prerequisites + (['site runtime/allocation/phase needed'] if runtime is None else [])))
    if d['operation'] == 'retained-delivery' and (prerequisites or any(c['retained_root'] is None for c in d['cases'])):
        raise ValueError('retained native delivery requires complete source/writer/IC/output prerequisites')
    capture.finish()
    return path, d, capture, observations, prerequisites, schemas


def inputs(task, base): return [Path(p['path']) for p in _capture(task, base)[2].pins()]
def execution_seconds(task, base):
    d = _capture(task, base)[1]
    return d['resources']['max_seconds'] + d['resources']['cleanup_seconds']


def context(task, base):
    path, d, capture, observations, prerequisites, _ = _capture(task, base)
    value = {'kind': 'cosmic-evolution-source-context', 'original_requests': d['original_requests'],
             'cases': observations, 'prerequisites': prerequisites, 'input_pins': capture.pins(),
             'operation': d['operation'], 'execution_authorized': False, 'physics_verified': False}
    capture.finish(); return value


def run(task, base, out):
    path, d, capture, observations, prerequisites, schemas = _capture(task, base)
    out = Path(out).absolute(); rd = out.parents[2]
    proposal = science.verify_worker(rd); spec = science.execution_spec(rd)
    if spec['mode'] != 'cosmic-evolution' or _capture(spec['task'], base)[0] != path or out != rd / proposal['output_directory'] / 'cosmic-evolution' or Path(proposal['base_dir']) != Path(base):
        raise ValueError('exact ordinary current cosmic-evolution worker/destination required')
    out.mkdir(parents=True, exist_ok=False)
    publications = core.Publications(d['resources'])
    native_results = []
    try:
        if d['operation'] == 'site-local-execution':
            from .cosmic_evolution_worker import execute
            native_results = execute(d, path, capture, schemas, out, rd)
        elif d['operation'] == 'retained-delivery':
            for case in d['cases']:
                root = Path(case['retained_root']); root = root if root.is_absolute() else path.parent / root
                native_results.append({'id': case['id'], 'delivery': core.check_outputs(root, case['outputs'], d['resources']), 'fresh_native_execution': False})
        capture.finish()
        result = {'status': 'passed', 'physics_validated': False, 'scope': SCOPE,
                  'operation': d['operation'], 'original_requests': d['original_requests'], 'cases': observations,
                  'native_results': native_results, 'prerequisites': prerequisites,
                  'input_pins': capture.pins(), 'whole_parent_accepted': False,
                  'limitations': ['Complete declared custody is not scientific/native-format applicability or numerical qualification.',
                    'Source preparation preserves missing writer/dirty source/full outputs as obligations; it is not evolution.',
                    'Supplied native binaries/Slurm/site runtime are trusted. Undeclared OS/native reads/writes are not sandboxed.',
                    'Local process/RSS receipts do not establish remote rank absence or distributed peak memory.']}
    except Exception as error:
        result = {'status': 'failed', 'physics_validated': False, 'scope': SCOPE, 'operation': d['operation'],
                  'original_requests': d['original_requests'], 'cases': observations, 'native_results': native_results,
                  'error': {'type': type(error).__name__, 'message': str(error)}, 'whole_parent_accepted': False,
                  'limitations': ['Partial/failed native and ownership artifacts are retained; no scientific acceptance.']}
        publications.json(out / 'cosmic-result.json', result)
        raise
    publications.json(out / 'cosmic-result.json', result)
    p = out / 'cosmic-result.json'
    published = capture.limits.copy()
    observed = core.Capture(out, published)
    row = next(r for r in core.output_inventory(out, d['resources']) if r['path'] == p.name)
    raw = observed.json({'path': str(p), 'sha256': row['sha256'], 'size': row['size']})
    if execution.digest(raw) != execution.digest(result): raise ValueError('persisted result differs from actual adapter return')
    capture.finish()
    for row in native_results:
        root = out / row['id'] if d['operation'] == 'site-local-execution' else Path(next(c['retained_root'] for c in d['cases'] if c['id'] == row['id']))
        if not root.is_absolute(): root = path.parent / root
        if core.output_inventory(root, d['resources']) != row['delivery']['inventory']: raise ValueError('native outputs changed before final adapter return')
    observed.finish()
    # Ending observation uses the pre-emission intended commitment too.
    core.output_inventory(out, d['resources'])
    publications.finish(); capture.finish()
    return result


def write_report(result, out):
    out = Path(out); path = out / 'cosmic-evolution-report.md'
    rows = ['CosmicIC/Nyx declared operation: ' + result['status'], '', SCOPE + '.', '',
            'Original cases and native product populations remain in cosmic-evolution/cosmic-result.json. '
            'Transfer normalization, private writer/source applicability and numerical science are not certified. '
            'Observed Slurm step completion is distinct from complete accounting or distributed memory measurement.', '']
    for case in result.get('cases', []):
        rows += [case['id'] + ': ' + str(case['scope']), '']
    rows += ['Remaining prerequisites: ' + '; '.join(result.get('prerequisites', [])), '']
    caps = {'max_output_files': 1, 'max_output_bytes': core.TEXT_BYTES}
    publications = core.Publications(caps); commitment = publications.text(path, '\n'.join(rows)); publications.finish()
    return [{'stem': 'cosmic-evolution-report', 'files': [path.name], 'normalization': 'Original native/source conventions retained; no new physical scaling',
             'intended_commitment': commitment}]


def finish_delivery(result, task, base, out):
    """Whole common-worker return rechecks the actual adapter contribution."""
    path, d, captured, _, _, _ = _capture(task, base)
    for row in result['native_results']:
        root = Path(out) / row['id'] if d['operation'] == 'site-local-execution' else Path(next(c['retained_root'] for c in d['cases'] if c['id'] == row['id']))
        if not root.is_absolute(): root = path.parent / root
        if core.output_inventory(root, d['resources']) != row['delivery']['inventory']:
            raise ValueError('native outputs changed during common result publication')
    raw = (core.json.dumps(result, indent=2, allow_nan=False) + '\n').encode('utf-8')
    captured.read({'path': str(Path(out) / 'cosmic-result.json'), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}, text=True)
    captured.finish()


def prepare(input_path, review_policy_path, output, *, goal_binding=None, approval_mode='physicist'):
    path = Path(input_path).absolute(); task = {'input': str(path)}
    _, d, _, _, _, _ = _capture(task, path.parent)
    from ravel.workflow.operation_resources import document
    spec = {'schema_version': 2, 'mode': 'cosmic-evolution', 'source': d['source'], 'task': task,
            'assumptions': [SCOPE, 'Original variants/full outputs retained; no inferred physical/source-profile validity.',
                            'Existing allocated site only; no remote submission or new allocation.'],
            'approval_mode': approval_mode, 'max_seconds': execution_seconds(task, path.parent),
            'max_attempts': 1, 'review_policy': document(science.regular(review_policy_path, path.parent))}
    if goal_binding is not None: spec['goal_binding'] = deepcopy(goal_binding)
    science.validate(spec)
    intended = (core.json.dumps(spec, indent=2, allow_nan=False) + '\n').encode('utf-8')
    publications = core.Publications(d['resources']); commitment = publications.json(output, core.loads(intended)); publications.finish()
    if commitment['sha256'] != hashlib.sha256(intended).hexdigest(): raise ValueError('prepared return differs from intended serialization')
    return core.loads(intended)


def prepare_context(input_path, output):
    path, d, captured, _, _, _ = _capture({'input':str(input_path)}, Path.cwd())
    rows = captured.pins(); configuration = next(p for p in rows if p['path'] == str(path))
    value = {'schema_version':1, 'configuration':configuration, 'inputs':rows}
    intended = (core.json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')
    published = core.Publications(d['resources']); commitment = published.json(output, core.loads(intended))
    captured.finish(); published.finish()
    if commitment['sha256'] != hashlib.sha256(intended).hexdigest(): raise ValueError('context return differs from intended serialization')
    return core.loads(intended)


def main(argv=None):
    import sys
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == '--context':
        p = argparse.ArgumentParser(); p.add_argument('input'); p.add_argument('output')
        a = p.parse_args(args[1:]); prepare_context(a.input, a.output); return 0
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('input'); p.add_argument('policy'); p.add_argument('output')
    a = p.parse_args(args); prepare(a.input, a.policy, a.output); return 0


if __name__ == "__main__": raise SystemExit(main())
