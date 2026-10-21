"""Controller services hook and lifecycle checks for the short-note build.

Source and rendering are ordinary confined plan operations. The assembly graph consumes their
accepted custody and computed integrity items; it carries no authority to publish. Only the outer
controller calls the sole sink, including the typed source-only ending when TeX is unavailable.

PDF admission (``pdf_admission``): a PDF stage that names a TeX engine is admitted only under this
host's manuscript-build qualification or the run's explicit reference-host build record; a site
profile that is ready without TeX, or a ``pdflatex`` on the path, establishes neither.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from ..ml import staged as artifacts
from . import CLAIM_MAP_KIND, is_authoring, note

_ACTIVE = ContextVar('controller_note_services', default=None)
ASSEMBLY = 'manuscript-assembly'
STAGE = 'manuscript-stage'
# The owner's explicit record of a separate reference host that builds the PDF.
REFERENCE_BUILD = 'inputs/manuscript-reference-host.json'


@dataclass(frozen=True)
class Binding:
    store: object
    run_dir: Path
    plan: dict
    step_id: str
    output_root: Path | None = None


@contextmanager
def services(binding):
    if not isinstance(binding, Binding):
        raise TypeError('a controller-owned note Binding is required')
    token = _ACTIVE.set(binding)
    try:
        yield binding
    finally:
        _ACTIVE.reset(token)


def active():
    return _ACTIVE.get()


def qualified_engine(environ=None):
    """The TeX engine this host's manuscript-build qualification covers, or None.

    The toolchain manifest's ``tex`` group must be qualified, with a ready doctor result, for this
    host's platform; the engine is the qualified prefix's ``bin/pdflatex`` wrapper. A site profile
    that is ready without TeX, or any other ``pdflatex`` on the path, establishes nothing.
    """
    from ravel.setup import manifest as mf
    from ravel.setup.installer import resolve_prefix
    try:
        repo = mf.repo_root()
        document, _ = mf.load(repo)
        group = next(g for g in document['groups'] if g.get('id') == 'tex')
        qualification = group.get('qualification') or {}
        record = qualification.get('record') or {}
        if (qualification.get('status') != 'qualified' or record.get('doctor_result') != 'ready'
                or record.get('platform') != mf.detect_platform()
                or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('evidence_sha256', '')))):
            return None
        engine = Path(resolve_prefix(repo, None, environ)) / 'bin' / 'pdflatex'
    except (mf.ManifestError, StopIteration, OSError, ValueError, KeyError, TypeError):
        return None
    return engine if engine.is_file() and os.access(engine, os.X_OK) else None


def _host_identity():
    """This host exactly: node name, kernel and machine."""
    u = os.uname()
    return {'nodename': u.nodename, 'sysname': u.sysname, 'release': u.release, 'version': u.version,
            'machine': u.machine}


def pdf_admission(step, run_dir):
    """``(basis, errors)`` for a PDF stage launch: what admits its TeX engine on this host.

    A launch without an engine runs to the typed source-only ending and claims no PDF. A launch with
    one needs this host's manuscript-build qualification (``qualified_engine``) or the run's explicit
    reference-host build record (``REFERENCE_BUILD``) naming this exact host, that engine path and its
    current bytes, and a ready ``ravel doctor --mode manuscript-build`` report digest.
    """
    argv = ((step.get('parameters') or {}).get('launch') or {}).get('argv') or []
    # ``--tex=<engine>`` keeps an absent engine a nonempty argv token; the two-token form is read alike.
    engines = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '--tex']
    engines += [arg[len('--tex='):] for arg in argv if type(arg) is str and arg.startswith('--tex=')]
    if len(engines) != 1:
        return None, [{'code': 'manuscript_pdf_engine_ambiguous', 'step': step['id'],
                       'message': 'the PDF launch names its TeX engine exactly once'}]
    if not engines[0]:
        return 'source-only', []
    engine = Path(engines[0])
    qualified = qualified_engine()
    if qualified is not None and engine == qualified:
        return 'manuscript-build-qualification', []
    record_path = Path(run_dir) / REFERENCE_BUILD
    try:
        if record_path.is_symlink() or not record_path.is_file():
            raise ValueError('no reference-host build record')
        record = json.loads(record_path.read_text())
        doctor = record.get('doctor') or {}
        if (record.get('schema_version') != 1 or record.get('kind') != 'manuscript-reference-host-build'
                or record.get('host_identity') != _host_identity()
                or record.get('engine') != {'path': str(engine), 'sha256': hashlib.sha256(engine.read_bytes()).hexdigest()}
                or doctor.get('mode') != 'manuscript-build' or doctor.get('result') != 'ready'
                or not re.fullmatch(r'[0-9a-f]{64}', str(doctor.get('report_sha256', '')))):
            raise ValueError('the reference-host build record names another host, engine or doctor result')
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return None, [{'code': 'manuscript_pdf_unqualified', 'step': step['id'],
                       'message': f'the PDF stage holds: the TeX engine {engine} is not covered by this host\'s '
                                  'manuscript-build qualification, and the run records no reference-host build for '
                                  f'this exact host and engine ({str(exc)[:200]}). Qualify the host with ravel doctor '
                                  f'--mode manuscript-build, or record the reference-host build in {REFERENCE_BUILD}'}]
    return 'reference-host-build', []


def parameters(spec, reading, contract, supplied):
    rows = [row for row in supplied if row.get('kind') == 'file' and str(row.get('path', '')).endswith('.json')
            and len(str(row.get('sha256', ''))) == 64]
    # The plan names a TeX engine only where the manuscript-build qualification covers it; a pdflatex on
    # the path proves nothing, and without an engine the PDF stage ends with the qualified source bundle.
    qualified = qualified_engine()
    found = {'python': sys.executable, 'tex': str(qualified) if qualified else ''}
    if len(rows) == 1:
        found.update(result_path=rows[0]['path'], result_sha256=rows[0]['sha256'])
    return found


def signatures():
    return {operation: {'summary': 'Source-bound short note ' + stage,
                       'implementation': {'kind': 'command', 'module': note.__name__},
                       # The note stages read the authoring step's trap sweep, which their validators require.
                       'consumes': [{'slot': 'claims', 'kind': CLAIM_MAP_KIND}, {'slot': 'documents', 'kind': 'document'},
                                    {'slot': 'results', 'kind': 'table'},
                                    {'slot': 'trap_sweep', 'kind': 'validation:trap-sweep'}],
                       'produces': [{'slot': f'artifact_{i}', 'kind': kind}
                                    for i, (_, kind) in enumerate(note.OUTPUTS[stage])],
                       'effects': [], 'cost': {'unit': 'task', 'forecast': None, 'ceiling_pointer': None},
                       'critical_fields': [], 'basis': {'adds': [], 'passes': ['documents']}, 'tools': [],
                       'stages': [], 'review': {'checks': ['io_contract']}, 'fidelity_rank': 1}
            for stage, operation in note.OPERATIONS.items()}


def executors():
    return {operation: 'analysis-author' for operation in note.OPERATIONS.values()}


def stage_of(step):
    return next((stage for stage, operation in note.OPERATIONS.items() if operation == step.get('operation')), None)


def structure_errors(step, plan):
    from . import is_authoring, is_build_graph, _ancestors, _steps
    errors = []
    stage = stage_of(step)
    above = [_steps(plan)[ident] for ident in _ancestors(plan, step['id']) if ident in _steps(plan)]
    if not any(is_authoring(row) for row in above):
        errors.append({'code': 'manuscript_claim_map_missing', 'step': step['id']})
    if stage == 'pdf' and not any(is_build_graph(row) for row in above):
        errors.append({'code': 'manuscript_staging_missing', 'step': step['id']})
    if stage == 'pdf' and not any(stage_of(row) == 'sources' for row in above):
        errors.append({'code': 'manuscript_sources_missing', 'step': step['id']})
    launch = (step.get('parameters') or {}).get('launch') or {}
    argv = launch.get('argv') or []
    if step.get('kind') != 'operate' or len(argv) < 5 or argv[1:5] != ['-I', '-m', note.__name__, stage]:
        errors.append({'code': 'manuscript_launch_mismatch', 'step': step['id']})
    if not any(o['path'] == note.RECEIPT and o.get('required') for o in step.get('outputs') or ()):
        errors.append({'code': 'manuscript_receipt_undeclared', 'step': step['id']})
    return errors


def bind(plan, context):
    """Import supplied result bytes before CHECK-IN 1 pins the source-stage reads."""
    from ravel.controller import result_import
    from ravel.controller.sink import common
    from ravel.controller.routes.compiler import plan_sha256
    store, run = context['store'], Path(context['run_dir'])
    if common.run_dir(store) != run:
        raise result_import.ImportRefused('result_import_run_invalid', 'the route must bind its own run directory')
    bound = deepcopy(plan)
    for step in bound.get('steps', []):
        if stage_of(step) != 'sources':
            continue
        launch = step['parameters']['launch']
        argv = launch['argv']
        for i, arg in enumerate(argv[:-1]):
            if arg != '--result':
                continue
            name, sep, declaration = argv[i + 1].partition('=')
            source, at, sha = declaration.rpartition('@')
            if not name or not sep or not at:
                raise result_import.ImportRefused('result_import_declaration_invalid', 'result needs name=path@sha256')
            # Already adopted inputs (including a resumed import) retain their ordinary custody.
            found = None
            for row in artifacts.custody_index(store).values():
                if (row.get('status') != 'accepted' or row.get('sha256') != sha
                        or str(run / row.get('destination', '')) != source):
                    continue
                _, target, checked = artifacts.adopted(store, run, row['step_id'], row['path'])
                if str(target) == source:
                    found = checked
                    break
            if found is None:
                found = result_import.import_result(store, source, sha)
            target = str(run / found['destination'])
            argv[i + 1] = name + '=' + target + '@' + sha
            launch['reads'] = [target if value == source else value for value in launch.get('reads', [])]
            parameters = bound.get('parameters', {})
            if parameters.get('result_path') == source:
                parameters['result_path'] = target
    bound['sha256'] = plan_sha256(bound)
    return bound


def admit(step, context):
    if stage_of(step) is None:
        return []
    errors = structure_errors(step, context['plan'])
    if stage_of(step) == 'pdf':
        errors += pdf_admission(step, context['run_dir'])[1]
    from ..ml.modes import ancestors, unresolved_placeholders
    if step not in context['plan'].get('steps', []):
        errors.append({'code': 'mode_step_not_in_plan', 'step': step['id']})
    if unresolved_placeholders(step):
        errors.append({'code': 'mode_unresolved_placeholder', 'step': step['id']})
    above = ancestors(context['plan'], step['id'])
    for item in step.get('inputs') or ():
        try:
            source, path = item['artifact'].split(':', 1)
            if source not in above:
                raise ValueError('the input is not a predecessor')
            artifacts.adopted(context['store'], context['run_dir'], source, path)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append({'code': 'manuscript_input_custody_missing', 'message': str(exc)[:400]})
    for prior in context['plan'].get('steps') or ():
        stage = stage_of(prior)
        if stage is None or prior['id'] not in above:
            continue
        try:
            receipt, _, _ = artifacts.adopted_json(context['store'], context['run_dir'], prior['id'], note.RECEIPT)
            if (receipt.get('kind') != 'manuscript-stage-receipt' or receipt.get('stage') != stage
                    or receipt.get('status') != 'completed' or receipt.get('placeholders')):
                raise ValueError('the predecessor did not complete its staged contract')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append({'code': 'manuscript_stage_prerequisite_incomplete', 'message': str(exc)[:400]})
    # A supplied digest is provenance, not accepted delivery custody. The importer must establish
    # the latter in the controller store; a worker cannot set a boolean in its claim map to do so.
    if stage_of(step) == 'sources':
        launch = (step.get('parameters') or {}).get('launch') or {}
        reads = set(launch.get('reads') or ())
        argv = launch.get('argv') or []
        declarations = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '--result']
        matched = set()
        accepted = set()
        consumed = []
        for row in artifacts.custody_index(context['store']).values():
            if row.get('status') != 'accepted' or not row.get('destination'):
                continue
            try:
                _, target, custody = artifacts.adopted(context['store'], context['run_dir'], row['step_id'], row['path'])
                matches = {value for value in declarations
                           if value.partition('=')[1] and value.partition('=')[0]
                           and value.partition('=')[2] == str(target) + '@' + custody['sha256']}
                if matches:
                    matched.update(matches)
                    accepted.add(str(target))
                    consumed.append(custody)
            except (ValueError, OSError, KeyError):
                continue
        if (not declarations or len(declarations) != len(set(declarations))
                or set(declarations) != matched or reads - accepted):
            errors.append({'code': 'manuscript_result_custody_missing',
                           'message': 'import supplied delivered results through accepted controller custody first'})
        if not errors:
            from ravel.controller import result_import
            result_import.record_use(context['store'], step, consumed)
    return errors


def step(step, outcome, context):
    stage = stage_of(step)
    if stage is None:
        return []
    problems = []
    try:
        receipt, _, custody = artifacts.adopted_json(context['store'], context['run_dir'], step['id'], note.RECEIPT)
        if receipt.get('kind') != 'manuscript-stage-receipt' or receipt.get('stage') != stage:
            problems.append('manuscript_receipt_invalid')
        elif receipt.get('status') != 'completed':
            problems += receipt.get('codes') or ['manuscript_stage_incomplete']
        elif receipt.get('placeholders'):
            problems.append('manuscript_stage_placeholders')
        for path, digest in (receipt.get('outputs') or {}).items():
            _, _, row = artifacts.adopted(context['store'], context['run_dir'], step['id'], path)
            if digest != row['sha256']:
                problems.append('manuscript_output_changed')
        if stage == 'pdf' and not problems:
            raw, _, _ = artifacts.adopted(context['store'], context['run_dir'], step['id'], 'outputs/manuscript.pdf')
            if not raw.startswith(b'%PDF-'):
                problems.append('manuscript_pdf_invalid')
    except (artifacts.AdoptionMissing, OSError, ValueError, KeyError) as exc:
        receipt, custody = {}, {}
        problems.append('manuscript_receipt_missing: ' + str(exc)[:300])
    if stage == 'sources' and not problems:
        from ravel.controller import result_import
        result_import.retain_inputs(context['store'], step)
    context['store'].append(STAGE, {'schema_version': 1, 'step_id': step['id'], 'stage': stage,
                                    'status': receipt.get('status'), 'codes': receipt.get('codes') or [],
                                    'receipt_sha256': custody.get('sha256'), 'problems': problems})
    return problems


def assemble(binding, *, publish=True):
    """Recompute graph assembly from accepted sources and authoring, never from callback verdicts."""
    from . import _ancestors, _steps, is_authoring
    store, run, plan = binding.store, binding.run_dir, binding.plan
    above = [_steps(plan)[ident] for ident in _ancestors(plan, binding.step_id) if ident in _steps(plan)]
    source = [row for row in above if stage_of(row) == 'sources']
    authors = [row for row in above if is_authoring(row)]
    if len(source) != 1 or len(authors) != 1:
        raise ValueError('the note assembly names one staged author and one source build')
    outcomes = {r['step_id']: r for r in artifacts.records(store, 'step-outcome') if r.get('step_id')}
    if any(outcomes.get(row['id'], {}).get('status') != 'completed' for row in source + authors):
        raise ValueError('the note prerequisites need completed controller step outcomes')
    author, source = authors[0], source[0]
    claim_map, _, _ = artifacts.adopted_json(store, run, author['id'], 'outputs/claim_map.json')
    raw, _, _ = artifacts.adopted(store, run, author['id'], 'outputs/note.md')
    bundle, _, bundle_custody = artifacts.adopted_json(store, run, source['id'], 'outputs/bundle.json')
    integrity, _, integrity_custody = artifacts.adopted_json(store, run, source['id'], 'outputs/integrity.json')
    source_receipt, _, _ = artifacts.adopted_json(store, run, source['id'], note.RECEIPT)
    if (source_receipt.get('status') != 'completed' or bundle.get('status') != 'completed'
            or integrity.get('passed') is not True or integrity.get('failing')
            or {row['id'] for row in integrity.get('items', [])} != set(note.ITEMS)
            or any(row.get('verdict') != 'pass' for row in integrity['items'])
            or hashlib.sha256(raw).hexdigest() != bundle.get('note_sha256')):
        raise ValueError('the source build has unresolved integrity items or changed text')
    note.validate_claim_map(claim_map)
    _, _, claims_custody = artifacts.adopted(store, run, author['id'], 'outputs/claim_map.json')
    if bundle.get('claim_map_sha256') != claims_custody['sha256']:
        raise ValueError('the source build binds a different claim map')
    record = {'schema_version': 1, 'step_id': binding.step_id, 'source_step': source['id'],
              'plan_sha256': plan['sha256'], 'status': 'completed',
              'bundle_sha256': bundle_custody['sha256'], 'integrity_sha256': integrity_custody['sha256'],
              'claim_map_sha256': claims_custody['sha256'], 'scientific_acceptance': False}
    if publish:
        if binding.output_root is None:
            raise ValueError('the controller supplies the graph attempt output root for adoption')
        output_root = Path(binding.output_root)
        attempts = Path(binding.run_dir).resolve() / 'steps' / binding.step_id / 'attempts'
        if (not output_root.resolve().is_relative_to(attempts) or output_root.name != 'outputs'
                or any(p.is_symlink() for p in (output_root, *output_root.parents))):
            raise ValueError('the assembly output root must be this graph step attempt directory')
        destination = output_root / 'outputs/assembly.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, sort_keys=True, allow_nan=False).encode()
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != encoded:
                raise ValueError('assembly output changed')
        else:
            with destination.open('xb') as stream:
                stream.write(encoded)
        store.append(ASSEMBLY, record)
    return deepcopy(record)


def qualified_artifacts(store, plan, run_dir):
    """A source-only ending selects only reviewed, assembled source artifacts for the sole sink to deliver."""
    rows = artifacts.records(store, STAGE)
    if not any(row.get('stage') == 'pdf' and row.get('status') == 'qualified'
               and row.get('codes') == ['manuscript_tex_unavailable'] for row in rows):
        return []
    assemblies = [row for row in artifacts.records(store, ASSEMBLY)
                  if row.get('status') == 'completed' and row.get('plan_sha256') == plan['sha256']]
    found = []
    for assembly in assemblies:
        checked = assemble(Binding(store, Path(run_dir), plan, assembly['step_id']), publish=False)
        if checked['bundle_sha256'] != assembly['bundle_sha256']:
            raise ValueError('source bundle changed after the assembly')
        for path in ('outputs/sources.tar', 'outputs/sources/main.tex', 'outputs/bundle.json', 'outputs/integrity.json'):
            _, _, custody = artifacts.adopted(store, run_dir, assembly['source_step'], path)
            found.append(custody)
    return found


def checkin(kind, context):
    """CHECK-IN 1's own rows from the route's evidence: the plan review's credit and the staged authoring's
    accepted claim map, the reviewable content this approval binds (A06, C03). The route declares no check-in
    variant (C04 not applicable). Without both, nothing is recorded and the ledger keeps CHECK-IN 1 shut."""
    store, plan = context.get('store'), context.get('plan') or {}
    if kind not in ('approve_plan', 'checkin1') or store is None:
        return {}
    from ..analysis import discharge
    evidence = {'validator': 'route.manuscript.authoring+plan_review', 'sha256': plan.get('sha256'),
                'mechanism': 'route.manuscript'}
    authoring = [row for row in plan.get('steps') or () if is_authoring(row)]
    wanted = [(row['id'], output['path']) for row in authoring for output in row.get('outputs') or ()
              if output.get('kind') == CLAIM_MAP_KIND]
    try:
        claim_maps = [artifacts.adopted(store, context['run_dir'], step_id, path)[2]['sha256'] for step_id, path in wanted]
    except artifacts.AdoptionMissing:
        claim_maps = []
    credit = discharge.checkin1_content(store, context, evidence, claim_maps)
    if credit is None:
        return {}
    # Result-sensitive assumptions (C14): the authoring's accepted trap sweep states every trap it hit.
    stated = []
    for row in authoring:
        for output in row.get('outputs') or ():
            if output.get('kind') == 'validation:trap-sweep':
                try:
                    value, _, custody = artifacts.adopted_json(store, context['run_dir'], row['id'], output['path'])
                except (artifacts.AdoptionMissing, ValueError):
                    return {}
                if type(value) is not dict or value.get('none_hit') is not True:
                    return {}
                stated += list(value.get('traps_hit') or ())
                evidence = {**evidence, 'trap_sweeps': [*evidence.get('trap_sweeps', []), custody['sha256']]}
    if 'trap_sweeps' in evidence:
        discharge.checkin1_assumptions(store, context, evidence, credit, stated)
    return {}


def ending(reason, context):
    found = qualified_artifacts(context['store'], context['plan'], context['run_dir'])
    record = {'reason': str(reason), 'artifacts': [r['artifact'] for r in found],
              'qualified': bool(found), 'qualification': 'manuscript_tex_unavailable' if found else 'incomplete'}
    context['store'].append('manuscript-ending', record)
    return record


@contextmanager
def bind_step(store, step, context, output_root):
    """Bind the approved assembly to this controller step's exact output attempt."""
    run = Path(context['run_dir'])
    plan = context['plan']
    attempt = context.get('attempt', 1)
    expected = run / 'steps' / step['id'] / 'attempts' / str(attempt) / 'outputs'
    root = Path(output_root)
    protected = Path(store.path()).resolve()
    matches = [row for row in plan.get('steps', []) if row.get('id') == step['id']]
    if (type(attempt) is not int or attempt < 1 or context.get('plan_sha256') != plan.get('sha256')
            or matches != [step] or (step.get('graph') or {}).get('id') != 'manuscript.build'
            or not run.is_absolute() or root != expected or not root.resolve().is_relative_to(run.resolve())
            or root.resolve().is_relative_to(protected) or protected.is_relative_to(root.resolve())
            or any(part.is_symlink() for part in (root, *root.parents))):
        raise ValueError('the assembly binding requires the approved step and its exact current attempt output root')
    with services(Binding(store, run, deepcopy(plan), step['id'], root)) as binding:
        yield binding
