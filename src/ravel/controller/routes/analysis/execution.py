"""Analysis operation requests at the P04 step / P05 confinement boundary.

This module never starts a process. The step service owns authority, reservations,
confinement and adoption. It resolves only declared input tokens; a requested launch
cannot turn a run-relative path into an extra read grant.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from . import common, scan


def request(step, context):
    """JSON-safe operation context, preserving the approved task and singleton point."""
    plan = context.get('plan') or {}
    params = step.get('parameters') or {}
    point, coordinates = scan.point_of(step)
    declared = list(step.get('points') or [])
    if declared and (len(declared) != 1 or declared[0] != point):
        raise ValueError('the step point differs from its singleton approved population')
    if point is not None and context.get('point') not in (None, point):
        raise ValueError('the dispatch context belongs to another point')
    if context.get('plan_sha256') not in (None, plan.get('sha256')) and plan:
        raise ValueError('the dispatch context belongs to another plan')
    return {'schema_version': 1, 'kind': 'analysis-operation-request', 'step_id': step['id'],
            'operation': step.get('operation'), 'role': step.get('role'), 'rung': step.get('rung') or 'none',
            'plan_sha256': plan.get('sha256') or context.get('plan_sha256'),
            'point': point, 'coordinates': deepcopy(coordinates), 'grid_sha256': params.get('grid_sha256'),
            'task': deepcopy(params.get('task') or {}), 'inputs': deepcopy(step.get('inputs') or []),
            'launch': deepcopy(params.get('launch')),
            'acquisition': step.get('kind') == 'acquire'}


def resolve_launch(step, context, *, output_root, inputs):
    """Resolve ``@input:<artifact>`` argv tokens from P04's verified input census.

    ``inputs`` contains only P04-admitted ``artifact, path|destination, sha256`` rows.
    The run directory itself is never exposed as a read root. Output paths remain
    relative to the attempt output directory chosen by P04.
    """
    launch = deepcopy((step.get('parameters') or {}).get('launch') or {})
    argv = launch.get('argv')
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError('an approved launch needs a nonempty string argv')
    declared = {r['artifact'] for r in step.get('inputs') or []}
    root = Path(context['run_dir']).resolve()
    paths = {}
    for row in inputs:
        name = row.get('artifact')
        if name not in declared:
            continue
        relative = row.get('destination') or row.get('path')
        if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError('an admitted input has an unsafe destination')
        target = root / relative
        if any(p.is_symlink() for p in (target, *target.parents) if p != root and root in p.parents):
            raise ValueError('an admitted input has a symbolic link in its destination')
        if not target.is_file() or common.file_sha256(target) != row.get('sha256'):
            raise ValueError('an admitted input changed before launch')
        if name in paths:
            raise ValueError('an admitted input appears twice')
        paths[name] = str(target)
    resolved = []
    for word in argv:
        if word.startswith('@input:'):
            artifact = word[len('@input:'):]
            if artifact not in paths:
                raise ValueError('a launch token names an undeclared or unverified input: ' + artifact)
            resolved.append(paths[artifact])
        else:
            resolved.append(word)
    if launch.get('reads'):
        raise ValueError('analysis launches read only the verified input census')
    launch.update(argv=resolved, reads=sorted(paths.values()), cwd=str(Path(output_root).resolve()))
    return launch


def dispatch(store, step, context):
    """Delegate one admitted operation to the binding ``step.run`` interface.

    The graph normally calls P04 directly. This adapter is also usable by an operation
    caller and in isolated package tests, without a local reimplementation of P04/P05.
    """
    from . import admit
    errors = admit(step, context)
    if errors:
        return {'step_id': step['id'], 'attempt': context.get('attempt', 1), 'status': 'held',
                'outputs': [], 'receipts': [], 'reason': '; '.join(e['message'] for e in errors)}
    operation = request(step, context)
    from ravel.controller import step as service
    forwarded = {**deepcopy({k: v for k, v in context.items() if k != 'store'}), 'operation_request': operation,
                 'plan_sha256': operation['plan_sha256']}
    # RunStore is a service object, never part of the JSON-safe dispatch context.
    forwarded.pop('store', None)
    if operation['point'] is not None:
        forwarded['point'] = operation['point']
    return service.run(store, deepcopy(step), forwarded)


def acquire(step, context, *, output_root, inputs):
    """Trusted controller acquisition action; scientific processes still use P05.

    Called only by P04 after signature, authority and budget admission. This narrow
    action runs the registered acquisition module, with the current source policy,
    verified input paths and outputs rooted in the attempt directory. Domain launches
    keep their network disabled. Nonzero acquisition and oversize output are failures,
    never fabricated source absence or accepted adoption.
    """
    from ravel.workflow import resource_census, restriction_guard, acquisition_http
    if step.get('kind') != 'acquire' or step.get('operation') != 'acquire-published':
        raise ValueError('only the registered publication acquisition operation is admitted')
    from ravel.controller.confine.inputs import hash_copy
    from ravel.controller.step import member_manifest as transport
    params = step.get('parameters') or {}
    ceiling = (params.get('task') or {}).get('max_bytes')
    if type(ceiling) is not int or ceiling <= 0:
        raise ValueError('acquisition needs a positive output byte ceiling')
    launch = resolve_launch(step, context, output_root=output_root, inputs=inputs)
    argv = launch['argv']
    prefix = ['python', '-m', 'ravel.workflow.resource_census']
    if argv[:3] != prefix:
        raise ValueError('acquisition runs only its registered implementation')
    args = argv[3:]
    folder = Path(output_root).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    declared = {o['path'].removeprefix('outputs/') for o in step.get('outputs') or []}
    no_record = None
    # Only two source-backed command shapes belong to this route, each with its local-source form for a run whose
    # environment profile records no network egress (the controller's own record, never a worker's choice). No
    # worker-chosen module, executable, output root or flag is accepted by the trusted action.
    profile = context.get('environment_profile') or {}
    offline = (profile.get('network') or {}).get('egress') == 'none'
    mirror = (profile.get('sources') or {}).get('mirror') if offline else None
    if step['id'] == 'inputs.census':
        local = (['--offline'] + (['--mirror', mirror] if mirror else [])) if offline else []
        if len(args) != 4 + len(local) or args[0] != '--reading' or args[2] != '--controller-output' or args[4:] != local:
            raise ValueError('the census acquisition command differs from the approved action')
        if args[3] not in declared:
            raise ValueError('the census output is not declared')
        args[3] = str(folder / args[3])
        descriptor = {'classes': ['public-metadata'], 'quantities': ['text']}
    elif step['id'] == 'acquire.data':
        local = (['--offline'] + (['--offline-mirror', mirror] if mirror else [])) if offline else []
        if (len(args) != 7 + len(local) or args[0] != '--fetch-published-data'
                or args[1] not in ('--inspire', '--record-source') or args[3:5] != ['--out', 'hepdata']
                or args[5:7] != ['--download-likelihood', '--tables'] or args[7:] != local):
            raise ValueError('the data acquisition command differs from the approved action')
        if args[1] == '--record-source':
            # The record identifier is supplied by an approved producer artifact,
            # rather than rewriting this consumer's plan bytes after preparation.
            source = Path(args[2])
            admitted = {str(Path(context['run_dir']) / (row.get('destination') or row.get('path', '')))
                        for row in inputs if row.get('artifact') in {r['artifact'] for r in step['inputs']}}
            if str(source) not in admitted:
                raise ValueError('the record source is not a verified declared input')
            route = json.loads(source.read_text())
            if not isinstance(route, dict) or 'hepdata_record' not in route:
                raise ValueError('the record source needs an explicit hepdata_record field')
            record = route['hepdata_record']
            if record is None:
                no_record = _no_published_record(step, context, inputs)
            elif (not isinstance(record, str) or not record or record.startswith('-')
                    or any(c.isspace() for c in record)):
                raise ValueError('the record source needs a nonempty publication record identifier')
            else:
                args[1:3] = ['--inspire', record]
        if 'hepdata/hepdata_manifest.json' not in declared:
            raise ValueError('the data manifest is not declared')
        args[4] = str(folder / 'hepdata')
        descriptor = ({'classes': ['public-metadata'], 'quantities': ['text']} if no_record is not None else
                      {'identifiers': {'inspire': [args[2]]}, 'classes': ['hepdata'], 'quantities': ['values']})
    else:
        raise ValueError('unknown analysis acquisition action')
    wall_seconds = context.get('acquisition_wall_seconds', (step.get('budget') or {}).get('wall_seconds'))
    with acquisition_http.scope(context['run_dir'], str(folder), descriptor, ceiling, wall_seconds) as audit:
        restriction_guard.require('resource_census', descriptor, rundir=context['run_dir'], output=str(folder))
        if no_record is not None:
            # Nothing is fetched: the typed record of a request without a published record.
            (folder / 'hepdata').mkdir(parents=True, exist_ok=True)
            (folder / 'hepdata/hepdata_manifest.json').write_text(json.dumps(no_record, sort_keys=True) + '\n')
            code = 0
        else:
            try:
                code = resource_census.main(args)
            except SystemExit as exc:
                code = exc.code if type(exc.code) is int else 1
    audit['scope_completed'] = True
    if code not in (None, 0):
        return {'exit_status': int(code), 'bytes': 0, 'members': [], 'source_admission': audit}
    member_inventory = None
    if step['id'] == 'acquire.data' and no_record is None:
        manifest_path = folder / 'hepdata/hepdata_manifest.json'
        manifest = transport.load(manifest_path)
        inventory, raw_size = [], 0
        for path in transport.member_files(manifest_path.parent):
            if path == manifest_path:
                continue
            name = transport.logical_path(path.relative_to(manifest_path.parent).as_posix())
            size = path.stat().st_size
            raw_size += size
            if raw_size > ceiling:
                raise ValueError('acquisition output exceeds the approved byte ceiling')
            sha = hash_copy(path)[0]
            inventory.append({'path': name, 'sha256': sha, 'bytes': size, 'blob': name})
        if transport.KEY in manifest and transport.rows(manifest) != inventory:
            raise ValueError('acquisition member manifest differs from local inventory')
        manifest[transport.KEY] = {'schema_version': 1, 'members': inventory}
        encoded = (json.dumps(manifest, sort_keys=True) + '\n').encode()
        if len(encoded) > transport.MAX_MANIFEST_BYTES:
            raise ValueError('acquisition member manifest metadata exceeds its byte ceiling')
        from ravel.workflow import private_files
        private_files.write(manifest_path, encoded)
        member_inventory = transport.verify(manifest_path)
    members, size = [], 0
    for path in transport.member_files(folder):
        size += path.stat().st_size
        if size > ceiling:
            raise ValueError('acquisition output exceeds the approved byte ceiling')
        members.append({'path': path.relative_to(folder).as_posix(), 'sha256': hash_copy(path)[0]})
    result = {'exit_status': 0, 'bytes': size, 'members': members, 'source_admission': audit,
              'source_scope_completed': audit.get('scope_completed') is True,
              'quantity_transport': {'kind': 'uninterpreted_source_transfer',
                                     'representation': 'file_bytes' if member_inventory is not None else 'metadata',
                                     'members': deepcopy(members), 'inventory_sha256': common.digest(members),
                                     'source_fields_transformed': False,
                                     'source_quantities': deepcopy(descriptor['quantities'])}}
    if member_inventory is not None:
        result.update(member_inventory=member_inventory,
                      member_inventory_sha256=common.digest(member_inventory))
    return result


def _no_published_record(step, context, inputs):
    """The typed not-applicable manifest of a data acquisition with no published record to fetch.

    Admitted only when the route analysis states no record (``hepdata_record: null``) and this run's
    resource census, a verified declared input of the step, found no analysis to sweep (its typed
    ``reading/targets`` ABSENT rung and no record). Anything else stays a refusal.
    """
    census_artifact = next((r['artifact'] for r in step.get('inputs') or ()
                            if r['artifact'].endswith(':outputs/inputs/resource_census.json')), None)
    row = next((r for r in inputs if r.get('artifact') == census_artifact), None)
    if census_artifact is None or row is None:
        raise ValueError('the record source needs a nonempty publication record identifier: the census is not a '
                         'verified declared input')
    path = Path(context['run_dir']) / (row.get('destination') or row.get('path', ''))
    if not path.is_file() or common.file_sha256(path) != row.get('sha256'):
        raise ValueError('the census input changed before the acquisition')
    census = json.loads(path.read_text())
    rung = ((census.get('rungs') or {}).get('reading/targets') or {}) if isinstance(census, dict) else {}
    if not isinstance(census, dict) or census.get('records') != [] or rung.get('status') != 'ABSENT':
        raise ValueError('the record source needs a nonempty publication record identifier: the census found an '
                         'analysis to acquire')
    return {'schema_version': 1, 'status': 'not_applicable',
            'reason': 'the route analysis names no published record and the census of the pinned reading found '
                      'no analysis to acquire; nothing was fetched',
            'evidence': {'census': census_artifact, 'census_sha256': row['sha256'], 'rung': 'reading/targets'},
            'tables': [], 'likelihood': None}


def acquisition_implementation(step):
    """Identity of the installed controller action; no process executes its logical argv."""
    if step.get('kind') != 'acquire' or step.get('operation') != 'acquire-published':
        return None
    import sys
    from ravel.workflow import resource_census
    return {'entrypoint': __name__ + ':launch_acquisition', 'interpreter': sys.executable,
            'argv_prefix': ['python', '-m', 'ravel.workflow.resource_census'], 'bounded_read_only': True,
            'code': {str(Path(path).resolve()): common.file_sha256(Path(path).resolve())
                     for path in (__file__, resource_census.__file__)}}


def launch_acquisition(store, step, context, prepared, *, inventory):
    """Serialize retained-storage admission through this trusted bounded source action."""
    from ravel.controller.step.member_manifest import copy_lock
    with copy_lock(store):
        return _launch_acquisition_locked(store, step, context, prepared, inventory=inventory)


def _launch_acquisition_locked(store, step, context, prepared, *, inventory):
    """Run the bounded source reader after the step's fresh effect authorization.

    The caller retains admission and effect custody; no worker or native process
    receives network access. The result names only this attempt's observed files.
    """
    import time
    folder = Path(prepared['output_root'])
    expected = (Path(context['run_dir']) / 'steps' / step['id'] / 'attempts'
                / str(context.get('attempt', 1)) / 'outputs')
    if (folder != expected or not folder.is_absolute()
            or any(part.is_symlink() for part in (folder, *folder.parents))):
        raise ValueError('acquisition outputs belong to the exact governed attempt')
    capsule = prepared['capsule']
    from ravel.controller.step import host_operations
    # The declared host actor's admission binds this in-process launch; a refusal starts nothing.
    host_decision = host_operations.admit(store, step, context.get('attempt', 1), branch='launch')
    from ravel.controller.confine import resource_admission
    storage = resource_admission.admit_acquisition(
        store, step, context['run_dir'], input_paths=capsule.get('input_digests') or (),
        plan_sha256=context.get('plan_sha256'), attempt=context.get('attempt', 1), phase='start')
    folder.mkdir(parents=True, exist_ok=True)
    journal = store.append('step-launch', {'schema_version': 1, 'phase': 'started', 'host_decision': host_decision,
        'step_id': step['id'], 'attempt': context.get('attempt', 1), 'launch_sha256': prepared['launch_sha256'],
        'argv_sha256': common.digest(capsule['argv']), 'writes': capsule['writes'],
        'scope': deepcopy(prepared.get('scope') or {}),
        'native_preflight': prepared.get('native_preflight'), 'storage_admission': storage['record_id']})
    began = time.monotonic()
    try:
        profile = store.latest('environment-profile') if callable(getattr(store, 'latest', None)) else None
        acquired = acquire(step, {**context, 'acquisition_wall_seconds': capsule['limits']['wall_seconds'],
                                  'environment_profile': profile['record'] if profile else None},
                           output_root=folder, inputs=prepared['verified_inputs'])
        acquired['storage_admission'] = storage
    except Exception as exc:
        store.append('step-launch', {'schema_version': 1, 'phase': 'failed', 'started': journal,
            'step_id': step['id'], 'attempt': context.get('attempt', 1),
            'error': type(exc).__name__, 'reason': str(exc)[:1000]})
        raise
    wall = time.monotonic() - began
    timed_out = wall > capsule['limits']['wall_seconds']
    observed = inventory(folder)
    code = acquired['exit_status']
    finished = store.append('step-launch', {'schema_version': 1, 'phase': 'finished', 'started': journal,
        'step_id': step['id'], 'attempt': context.get('attempt', 1), 'exit_status': code,
        'timed_out': timed_out, 'wall_seconds': wall, 'inventory': observed,
        'backend': 'controller-acquisition', 'acquisition': acquired})
    return {'journal_id': journal, 'finished_id': finished, 'exit_status': code, 'timed_out': timed_out,
            'wall_seconds': wall, 'inventory': observed, 'output_root': str(folder),
            'launch_sha256': prepared['launch_sha256'], 'backend': 'controller-acquisition',
            'acquisition': acquired, 'label': None, 'confinement_errors': [], 'quarantined': []}


def review_errors(step, final):
    """Route-supplied must-checks of a principal check-in review, before its credit.

    P04 already enforces nested review-seat items. The controller's own plan review
    is a principal review step; its route items need the same explicit verdicts.
    """
    items = ((step.get('parameters') or {}).get('review_items') or [])
    if step.get('kind') != 'review' or not items:
        return []
    expected = {item['id'] for item in items}
    rows = final.get('item_verdicts') if isinstance(final, dict) else None
    if not isinstance(rows, list):
        return ['route must-check item_verdicts are missing']
    seen, errors = set(), []
    for row in rows:
        name = row.get('item') if isinstance(row, dict) else None
        if name not in expected or name in seen:
            errors.append('unknown or duplicate route must-check: ' + str(name))
            continue
        seen.add(name)
        if row.get('verdict') != 'pass' or not row.get('evidence'):
            errors.append('route must-check not passed with evidence: ' + str(name))
    errors += ['missing route must-check: ' + name for name in sorted(expected - seen)]
    return errors


def bind_launches(plan, source, supplied=()):
    """Bind source-backed native argv supplied by preparation, before CI1 approval.

    Exact expanded step IDs are required, including one identity per scan point.
    Nothing infers scientific commands or mutates preparation steps that already ran.
    Without supplied argv the operation retains its registered executor-role path.

    A prepared launch may read run inputs the operator supplied (``launch_inputs``: step id ->
    ``inputs/<name>`` artifacts). Each must be one of this run's staged supplied inputs
    (``supplied``: the intake's staged rows); it becomes a declared input of that step pinned to the
    staged digest, so custody refuses the launch if the approved bytes change.
    """
    launches = source.get('launches') or {}
    if not isinstance(launches, dict):
        raise ValueError('route-analysis launches is an object keyed by exact step id')
    reads = source.get('launch_inputs') or {}
    if not isinstance(reads, dict):
        raise ValueError('route-analysis launch_inputs is an object keyed by exact step id')
    staged = {row['artifact']: row for row in supplied or ()
              if isinstance(row, dict) and isinstance(row.get('artifact'), str) and isinstance(row.get('sha256'), str)}
    changed = deepcopy(plan)
    by_id = {s['id']: s for s in changed['steps']}
    for key, launch in launches.items():
        step = by_id.get(key)
        if step is None or common.phase_of(step) == 'prepare' or step.get('kind') != 'operate':
            raise ValueError('a native launch names an unplanned or preparation step: ' + str(key))
        if not isinstance(launch, dict) or not isinstance(launch.get('argv'), list) or not launch['argv'] \
                or not all(isinstance(a, str) and a for a in launch['argv']):
            raise ValueError('a prepared native launch needs explicit argv')
        if launch.get('reads'):
            raise ValueError('a prepared native launch reads only declared step inputs')
        step['parameters']['launch'] = deepcopy(launch)
    for key, artifacts in reads.items():
        step = by_id.get(key)
        if step is None or key not in launches:
            raise ValueError('launch inputs name a step without a prepared launch: ' + str(key))
        if not isinstance(artifacts, list) or not all(isinstance(a, str) for a in artifacts):
            raise ValueError('the launch inputs of a step are a list of run-input artifacts')
        for artifact in artifacts:
            row = staged.get(artifact)
            if row is None:
                raise ValueError('a launch input is not a staged supplied input of this run: ' + artifact)
            existing = [r for r in step['inputs'] if r.get('artifact') == artifact]
            if any(r.get('sha256') != row['sha256'] for r in existing):
                raise ValueError('a declared launch input must match its staged supplied digest: ' + artifact)
            if not existing:
                step['inputs'].append({'artifact': artifact, 'sha256': row['sha256'], 'kind': 'supplied',
                                       'required': True})
    effects = source.get('launch_effects', {})
    if type(effects) is not dict:
        raise ValueError('launch_effects is an object keyed by exact prepared launch step')
    from ravel.validation.validate_request_plan import signatures
    registered = signatures()
    for key, declared in effects.items():
        step = by_id.get(key)
        if step is None or key not in launches:
            raise ValueError('execution effects require an exact prepared native launch')
        signature = registered.get(step.get('operation'))
        if (signature is None or type(declared) is not list
                or any(type(effect) is not str for effect in declared)
                or len(set(declared)) != len(declared)
                or not set(declared) <= set(signature['effects'])):
            raise ValueError('execution effects must be distinct effects admitted by the operation signature')
        step['parameters']['execution_effects'] = deepcopy(declared)
        step['parameters']['execution_effects_evidence'] = {
            'source_sha256': common.digest(source), 'launch_sha256': common.digest(launches[key]),
            'inputs': deepcopy(step['inputs'])}
    changed['sha256'] = common.digest({k: v for k, v in changed.items() if k != 'sha256'})
    from . import scientific
    return scientific.bind(changed, source)
