"""Confined ordinary-operation adapter used below the governed step graph.

The controller retains its store and authority. The installed child entrypoint
receives only the prepared ordinary run and explicit receipt destination. All
ordinary approval, runtime, prospective review and correction checks still run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from ravel.workflow.state_io import file_lock, read_json

from .contracts import adopted_json, digest, pinned_json, records, relative
from . import evidence

ADAPTER = 'ravel.controller.routes.study.runtime'


class StudyHold(ValueError):
    """A concrete ordinary-operation obligation remains unmet; no launch occurs."""


def packet_context(context):
    """JSON-safe trusted graph context, excluding live services and credentials."""
    keys = ('run_id', 'run_dir', 'store_root', 'plan_sha256', 'attempt', 'phase',
            'plan', 'reading', 'contract', 'state', 'supplied', 'authority_subject', 'site_budget', 'review_queries')
    result = {key: deepcopy(context[key]) for key in keys if key in context}
    for key in ('run_dir', 'store_root'):
        if isinstance(result.get(key), Path):
            result[key] = str(result[key])
    json.dumps(result, allow_nan=False)
    return result


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


from contextlib import contextmanager


@contextmanager
def capsule_runtime(env=None):
    """The runtime view an ordinary child was planned and runs under: its confined launch's environment.

    A stage binding fingerprints the runtime keys of the process that planned it (a confined
    preparation carries none of the controller's); the controller verifies and evaluates the child
    under that same view, never under its own shell environment.
    """
    from ravel.workflow.execution import RUNTIME_ENVIRONMENT_KEYS
    saved = {key: os.environ.get(key) for key in RUNTIME_ENVIRONMENT_KEYS}
    try:
        for key in RUNTIME_ENVIRONMENT_KEYS:
            value = (env or {}).get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _ordinary(step, context, *, approved=True):
    ordinary = (step.get('parameters') or {}).get('ordinary')
    required = {'kind', 'child_rundir', 'plan_sha256', 'specification_sha256'}
    if type(ordinary) is not dict or not required <= set(ordinary) or ordinary['kind'] not in ('science', 'scoped'):
        raise StudyHold('the approved step needs its complete prepared ordinary child binding')
    root = Path(context['run_dir']).absolute()
    child = root / relative(ordinary['child_rundir'])
    if not child.is_relative_to(root / 'children') or any(p.is_symlink() for p in (child, *child.parents)):
        raise StudyHold('the ordinary child must remain inside its original children directory')
    from ravel.workflow import science, scoped
    module = science if ordinary['kind'] == 'science' else scoped
    plan_path, spec_path = child / module.PLAN, child / module.SPEC
    for path, sha in ((plan_path, ordinary['plan_sha256']), (spec_path, ordinary['specification_sha256'])):
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise StudyHold('ordinary plan or specification changed after controller approval')
    # Authority is checked by its actual owner and the existing child gate.
    with capsule_runtime():
        proposal = (module.verify_plan(child, approved=approved) if ordinary['kind'] == 'science'
                    else module.verify_plan(child, require_approval=approved))
    return ordinary, child, module, proposal


def approve_ordinary_child(store, step, child, ordinary, decision, context):
    """The ordinary child's own approval, recorded by its controller from the verified CHECK-IN 1 decision.

    The approved controller plan pins the child's plan and specification bytes (``ordinary``), and the
    authority service has just verified the ``approve_plan`` decision against the current check-in pins.
    Only then does the controller record the child's scripted assent, quoting that decision. A child
    whose approval mode is not scripted assent needs its own human approval and is held; an existing
    approval is verified as it stands and never rewritten. The receipt names machine authority as such.
    """
    from ravel.workflow import science
    if ordinary['kind'] != 'science':
        return None
    approval = child / science.APPROVAL
    if approval.exists() or approval.is_symlink():
        return None  # the child's own gate decides an existing approval; it is never rewritten
    spec = read_json(child / science.SPEC)
    if spec.get('approval_mode') != 'scripted_yes':
        raise StudyHold('the ordinary child needs its own approval: its approval mode is not scripted assent')
    if (type(decision.get('id')) is not str or decision.get('decision') != 'approve'
            or decision.get('authorizes_effects') is not True or not context.get('plan_sha256')):
        raise StudyHold('the ordinary child is approved only from a verified CHECK-IN 1 decision')
    quote = (f"Controller CHECK-IN 1 decision {decision['id']} approved plan {context['plan_sha256']}, "
             f"which pins this study's plan {ordinary['plan_sha256']}.")
    from . import child_contract
    try:
        compute = _compute_approval(store, step, ordinary, decision, context)
        contract_record = child_contract.prepare(store, child, ordinary, decision,
            {**context, 'step_id': step['id'], 'compute_approval': compute})
    except child_contract.ComputeRungUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StudyHold('ordinary child contract unavailable: ' + str(exc)) from None
    with capsule_runtime():
        science.approve(child, quote, scripted=True)
    return store.append('study-child-approval', {
        'step_id': step['id'], 'child_rundir': ordinary['child_rundir'], 'decision': decision['id'],
        'plan_sha256': context['plan_sha256'], 'child_plan_sha256': ordinary['plan_sha256'],
        'contract_record_id': contract_record,
        'approval_sha256': hashlib.sha256(approval.read_bytes()).hexdigest(), 'quote': quote,
        'authority': 'machine: scripted assent under the controller decision'})


def _compute_approval(store, step, ordinary, decision, context):
    """Retain the selected step rung only after the ordinary effect authority admits it."""
    from .child_contract import ComputeRungUnavailable
    rung = step.get('rung')
    if rung is None:
        return None  # review intake can exist; compute dispatch still refuses without its own binding
    if rung not in ('smoke', 'full', 'scan'):
        raise ComputeRungUnavailable('ordinary compute rung must be an explicit smoke, full or scan selection')
    from ..compiler import authority_budget
    from ravel.controller.step.operations import current_plan
    plan = current_plan(store, context)
    selected = [row for row in plan.get('steps', []) if row.get('id') == step['id']]
    if (len(selected) != 1
            or selected[0].get('rung') != rung
            or (selected[0].get('parameters') or {}).get('ordinary') != ordinary):
        raise ComputeRungUnavailable('ordinary compute rung differs from its approved step')
    order = ('none', 'dry', 'smoke', 'pilot', 'full', 'scan')
    ceiling = (decision.get('bounds') or {}).get('rung')
    if ceiling not in order or order.index(rung) > order.index(ceiling):
        raise ComputeRungUnavailable('ordinary compute rung exceeds its verified CHECK-IN 1 bounds')
    requires_go = context.get('requires_go', True)
    if type(requires_go) is not bool or not _finite((step.get('budget') or {}).get('wall_seconds')):
        raise ComputeRungUnavailable('ordinary compute rung needs explicit GO scope and a finite time ceiling')
    from ravel.controller import authority
    from ..compiler import AUTHORITY_BUDGET
    resources = authority_budget(step.get('budget') or {})
    reserved = (context.get('reservation') or {}).get('amounts', {})
    if (type(reserved) is not dict
            or any(key not in set(AUTHORITY_BUDGET.values()) for key in reserved)
            or any(value is not None and type(value) not in (int, float) for value in reserved.values())):
        raise ComputeRungUnavailable('ordinary compute needs its declared reservation dimensions')
    resources.update({key: value for key, value in reserved.items() if value is not None})
    effect = {'id': step['id'], 'rung': rung, 'plan': rung, 'pins': {'plan_sha256': context['plan_sha256']},
              'go_pins': deepcopy(context.get('go_pins') or {}), 'requires_go': requires_go,
              'stage': step.get('operation') or step['id'], 'budget': resources,
              'started_ns': time.time_ns()}
    try:
        authorized = authority.authorize_effect(store, effect)
    except ValueError as exc:
        raise ComputeRungUnavailable('ordinary compute rung authority refused: ' + str(exc)) from None
    if (type(authorized) is not dict or authorized.get('approve_plan') != decision['id']
            or (requires_go and rung in ('full', 'scan') and not authorized.get('go'))):
        raise ComputeRungUnavailable('ordinary compute rung lacks its current CHECK-IN 1/GO binding')
    return {'schema_version': 1, 'required_plan': rung, 'step_id': step['id'],
            'parent_plan_sha256': context['plan_sha256'], 'child_plan_sha256': ordinary['plan_sha256'],
            'child_specification_sha256': ordinary['specification_sha256'],
            'max_seconds': step['budget']['wall_seconds'], 'requires_go': requires_go, 'authority': deepcopy(authorized)}


def preflight(store, step, context):
    """Admit a typed operation, authority, evidence and exact confined capsule."""
    from ravel.controller import authority, ledger, confine
    if authority.stop_state(store) != 'running':
        raise StudyHold('the operator has paused or stopped this run')
    if (step.get('parameters') or {}).get('action') == 'prepare':
        return preparation(store, step, context)
    if scientific_checks(store, step, context, phase='dispatch'):
        raise StudyHold('required external generation recipe is unresolved')
    unmet = ledger.gate(store, 'launch[' + step['id'] + ']')
    if unmet:
        raise StudyHold('ordinary dispatch has unmet ledger obligations: ' + str(unmet))
    # An unapproved child's plan is checked without its approval, which follows the verified
    # controller decision below; an approved child is checked by its own gate as it stands.
    try:
        ordinary, child, module, proposal = _ordinary(step, context)
        child_approved = True
    except (ValueError, OSError):  # a refused or absent approval file (the plan itself is checked next)
        ordinary, child, module, proposal = _ordinary(step, context, approved=False)
        child_approved = False
    spec = read_json(child / module.SPEC)
    if ordinary['kind'] == 'science':
        from . import mode_admission
        admitted = mode_admission(spec)
        if step.get('operation') != admitted['operation'] or step.get('role') != admitted['role']:
            raise StudyHold('selected mode, operation and production role differ from the ordinary contract')
    else:
        from ravel.workflow.scoped_spec import require_valid
        require_valid(spec)
        if spec['mode'] != context['contract']['task_mode']:
            raise StudyHold('scoped child changed the original requested operation')
    cost = step.get('budget', {}).get('wall_seconds')
    if not _finite(cost) or cost > spec['max_seconds']:
        raise StudyHold('step duration must remain within its original ordinary ceiling')
    if not context.get('plan_sha256'):
        raise StudyHold('the launch must name its approved controller plan')
    subject = context.get('authority_subject')
    if type(subject) is not dict:
        raise StudyHold('the shared authority owner must receive the current ordinary check-in view')
    # The step's budget in the authority's dimensions: its retry limit is control metadata, never a resource.
    from ..compiler import CompileError, authority_budget
    try:
        budget = authority_budget(step.get('budget') or {}, step=step.get('id'))
    except CompileError as exc:
        raise StudyHold(str(exc)) from None
    bounds = {'budget': budget}
    if step.get('rung') in ('smoke', 'full', 'scan'):
        from ravel.controller.graph import plan_bounds
        from ravel.controller.step.operations import current_plan
        # Retain the complete approved parent scope when reusing its check-in.
        bounds = plan_bounds(current_plan(store, context))
    decision = authority.request(store, 'approve_plan', deepcopy(subject), bounds)
    if (not isinstance(decision, dict) or 'pending' in decision or not decision.get('id')
            or decision.get('decision') != 'approve' or decision.get('authorizes_effects') is not True):
        detail = decision.get('pending') if isinstance(decision, dict) else decision
        raise StudyHold('ordinary child authority is pending: ' + json.dumps(detail, default=str)[:900])
    # The authority compares pins: the check-in view's pins, not the view itself.
    decision = authority.verify(store, decision['id'], kind='approve_plan', subject=(subject.get('view') or {}).get('pins') or {})
    if not child_approved:
        approve_ordinary_child(store, step, child, ordinary, decision, context)
        ordinary, child, module, proposal = _ordinary(step, context)
    attempt = context.get('attempt', 1)
    if type(attempt) is not int or not 1 <= attempt <= spec.get('max_attempts', 1):
        raise StudyHold('original prospective attempt ceiling exhausted')
    output_root = Path(context.get('output_root') or
                       Path(context['run_dir']) / 'steps' / step['id'] / 'attempts' / str(attempt) / 'outputs')
    if not output_root.is_absolute() or not output_root.is_relative_to(Path(context['run_dir']).absolute()):
        raise StudyHold('declared step output root must lie inside the current run')
    if any(p.is_symlink() for p in (output_root, *output_root.parents)):
        raise StudyHold('declared output root cannot traverse links')
    receipt = output_root / 'result.json'
    argv = [sys.executable, '-m', ADAPTER, 'run', '--kind', ordinary['kind'], '--rundir', str(child),
            '--receipt', str(receipt)]
    if (step.get('parameters') or {}).get('action') == 'correct':
        if ordinary['kind'] != 'science' or attempt < 2:
            raise StudyHold('corrections require an ordinary prospective redo attempt')
        pin = (step.get('parameters') or {}).get('correction')
        correction = pinned_json(context['run_dir'], pin)
        keys = {'actor_id', 'changed_paths', 'recheck_checks', 'max_seconds', 'supporting_artifacts'}
        if (type(correction) is not dict or set(correction) != keys
                or not _finite(correction['max_seconds']) or correction['max_seconds'] > cost):
            raise StudyHold('correction must retain its prospective numerical and resource envelope')
        policy = (spec.get('review_policy') or {}).get('policy') or {}
        if (not set(correction['changed_paths']) <= set(policy.get('allowed_changed_paths', []))
                or not set(correction['recheck_checks']) <= set(policy.get('checks', correction['recheck_checks']))):
            raise StudyHold('correction changes paths outside the prospectively reviewed envelope')
        argv[3] = 'correct'
        argv.extend(['--correction', str(Path(context['run_dir']) / pin['path'])])
    # The ordinary child's own directory is the launch's writable root (its outputs, work, logs and
    # state files live there; the launcher observes directories, and the child creates the rest).
    writes = [str(output_root), str(child)]
    reads = [str(child / 'inputs')]
    env = {'RAVEL_LAUNCH_STATE': str(launch_state_root(Path(context['run_dir']).absolute(), relative(ordinary['child_rundir'])))}
    writes.append(env['RAVEL_LAUNCH_STATE'])
    workflow = (step.get('parameters') or {}).get('site_workflow')
    if workflow:
        # A supplied workflow runs in its adopted working directory beside the child and reads its
        # adoption record, site profile and the supplied workflow file the run directory holds.
        root = Path(workflow['workflow_root'])
        run_root = Path(context['run_dir']).absolute()
        if (not root.is_absolute() or not root.is_relative_to(run_root / 'children')
                or any(p.is_symlink() for p in (root, *root.parents)) or not (root / 'work').is_dir()):
            raise StudyHold('the adopted workflow root must be an ordinary directory under the run\'s children')
        writes.append(str(root / 'work'))
        reads.extend([str(root / 'adoption'), str(root / 'profiles'), str(run_root / 'inputs')])
        from ravel.workflow import wms_runtime
        manager = wms_runtime.snakemake_argv() or wms_runtime.declared_entry()
        if len(manager) != 1:
            raise StudyHold('the external-workflow run needs the installed workflow manager entry')
        reads.append(str(Path(manager[0]).resolve().parent))
        reads = [path for path in reads if Path(path).exists()]
    if (step.get('parameters') or {}).get('action') == 'correct':
        reads.append(str(Path(context['run_dir']) / step['parameters']['correction']['path']))
    _declare_roots([str(output_root), env['RAVEL_LAUNCH_STATE']])
    capsule = {'argv': argv, 'env': env, 'reads': reads, 'writes': writes,
               'limits': {'wall_seconds': cost}, 'backend': 'auto'}
    inventory = confine.probe('launch', {**capsule, 'admitted': {'writable': writes, 'network': 'none'}})
    if inventory.get('equal') is not True:
        raise StudyHold('actual launch confinement differs from its admitted inventory: '
                        + json.dumps(inventory.get('differences'), default=str)[:1200])
    body = {'step_id': step['id'], 'attempt': attempt, 'ordinary': deepcopy(ordinary),
            'plan_sha256': context['plan_sha256'], 'authority': decision['id'], 'capsule_sha256': digest(capsule)}
    admission = store.append('study-operation-admission', body)
    return {'capsule': capsule, 'launch_sha256': digest(capsule), 'output_root': str(output_root),
            'outputs': [{'path': row['path'], 'plan_path': row['path'], 'kind': row['kind'],
                         'required': row.get('required', True)} for row in step.get('outputs', [])],
            'ordinary': ordinary, 'admission_id': admission,
            'authority': decision, 'plan_sha256': context['plan_sha256'], 'inventory': inventory}


def _with_plan(store, context):
    """The step context with its plan: the controller's pinned current plan when the context names none."""
    if isinstance(context.get('plan'), dict):
        return context
    from ravel.controller.step import operations
    return {**context, 'plan': operations.current_plan(store, context)}


def preparation(store, step, context):
    """Prepare the ordinary plan as an explicit confined, noncomputing step."""
    from ravel.controller import confine, ledger
    context = _with_plan(store, context)
    if context.get('phase') != 'prepare' or step.get('rung') not in (None, 'none', 'dry'):
        raise StudyHold('ordinary preparation belongs to the declared pre-CI1 dry phase')
    if ledger.gate(store, 'plan->plan_review'):
        raise StudyHold('preparation has unmet input or instruction obligations')
    specification, spec_pin = adopted_json({**context, 'store': store}, 'specify:outputs/specification.json')
    coverage, _ = adopted_json({**context, 'store': store}, 'specify:outputs/scope.json')
    child_relative = relative(coverage['child_rundir'])
    if child_relative.parts[0] != 'children' or len(child_relative.parts) < 2:
        raise StudyHold('preparation child must occupy its declared children directory')
    route = context['plan']['route']
    route_id = route['id'] if isinstance(route, dict) else route
    kind = 'scoped' if route_id == 'scoped' else 'science'
    if kind == 'science':
        from . import mode_admission
        mode_admission(specification)
    else:
        from ravel.workflow.scoped_spec import require_valid
        require_valid(specification)
    root = Path(context['run_dir']).absolute()
    output_root = root / 'steps' / step['id'] / 'attempts' / str(context.get('attempt', 1)) / 'outputs'
    child = root / child_relative
    if any(p.is_symlink() for p in (child, *child.parents, output_root, *output_root.parents)):
        raise StudyHold('preparation output roots must not traverse links')
    cost = step.get('budget', {}).get('wall_seconds')
    if not _finite(cost):
        raise StudyHold('preparation needs an explicit finite wall-clock bound')
    argv = [sys.executable, '-m', ADAPTER, 'prepare', '--kind', kind, '--rundir', str(child),
            '--spec', str(root / spec_pin['destination']), '--child-relative', str(child_relative),
            '--receipt', str(output_root / 'preparation.json')]
    if kind == 'scoped':
        argv.extend(['--contract', str(root / 'inputs/task_contract.json')])
    reads = [str(root / spec_pin['destination']), str(root / 'inputs')]
    for pin in supplied_pins(context):
        rows = inspect_inputs(store, [pin], run_dir=root)
        reads.extend(str(root / row['path']) for row in rows)
    # The preparation creates the child (and a supplied workflow's root) inside the run's children
    # directory, which is the declared writable root: a planner refuses a pre-existing child.
    writes = [str(root / child_relative.parts[0]), str(output_root)]
    env = {'RAVEL_LAUNCH_STATE': str(launch_state_root(root, child_relative))}
    workflow_root = governed_workflow_root(specification, root, child_relative)
    if workflow_root is not None:
        # The supplied workflow's adoption record, working directory and site profile live beside the
        # child; the adoption binds the declared workflow manager entry of this environment (read only).
        from ravel.workflow import wms_runtime
        manager = wms_runtime.snakemake_argv() or wms_runtime.declared_entry()
        if len(manager) != 1:
            raise StudyHold('the external-workflow preparation needs the installed workflow manager entry')
        if any(p.is_symlink() for p in (workflow_root, *workflow_root.parents)):
            raise StudyHold('preparation output roots must not traverse links')
        argv.extend(['--workflow-root', str(workflow_root), '--snakemake', manager[0]])
        if workflow_root.parent != root / child_relative.parts[0]:
            raise StudyHold('the adopted workflow root belongs beside its child')
        reads.append(str(Path(manager[0]).resolve().parent))  # the manager entry and its interpreter link
    # The declared roots exist before the probe and the launch: the inventory observes directories,
    # and a root the child would otherwise create is bound as the exact admitted writable path.
    _declare_roots(writes)
    capsule = {'argv': argv, 'env': env, 'reads': reads, 'writes': writes,
               'limits': {'wall_seconds': cost}, 'backend': 'auto'}
    inventory = confine.probe('launch', {**capsule, 'admitted': {'writable': capsule['writes'], 'network': 'none'}})
    if inventory.get('equal') is not True:
        raise StudyHold('preparation confinement inventory differs from admission: '
                        + json.dumps(inventory.get('differences'), default=str)[:1200])
    return {'capsule': capsule, 'launch_sha256': digest(capsule), 'output_root': str(output_root),
            'outputs': [{'path': row['path'], 'plan_path': row['path'], 'kind': row['kind'],
                         'required': row.get('required', True)} for row in step.get('outputs', [])],
            'ordinary': {'kind': kind},
            'authority': None, 'plan_sha256': context['plan_sha256'], 'inventory': inventory}


def _launched_child(capsule):
    """The ordinary child directory a study capsule names (``--rundir``)."""
    argv = list(capsule.get('argv') or [])
    return Path(argv[argv.index('--rundir') + 1]) if '--rundir' in argv else None


def adopt_launch_journal(store, child, journal_id):
    """Copy a confined child's run-tree launch journal into the controller store after its launch.

    A confined launch cannot reach the store, so the original of each authorization event it
    writes stays in its run tree; the controller adopts those events (a verified hash chain) as
    the store's copy right after the launch it journalled (``journal_id``) finishes, extending
    the prefix it already holds. A journal that contradicts the stored prefix is refused and the
    discrepancy journalled, never overwritten.
    """
    from ravel.workflow import launch_authorization as journal
    if child is None or not (Path(child) / journal.JOURNAL).is_dir():
        return None
    try:
        events = journal._events(child)
    except ValueError as exc:
        store.append('study-launch-journal', {'child': str(child), 'launch': journal_id, 'refused': str(exc)[:500]})
        return {'refused': str(exc)[:500]}
    stored = [row.get('record', row).get('sha256') for row in store.scan(journal.STORE_KIND)]
    local = [event['sha256'] for event in events]
    if stored and local[:len(stored)] != stored:
        store.append('study-launch-journal', {'child': str(child), 'launch': journal_id,
                                              'refused': 'run-tree journal contradicts the stored events'})
        return {'refused': 'run-tree journal contradicts the stored events'}
    added = 0
    for event in events[len(stored):]:
        store.append(journal.STORE_KIND, event)
        added += 1
    record = store.append('study-launch-journal', {'child': str(child), 'launch': journal_id,
                                                   'events': len(events), 'adopted': added})
    return {'record': record, 'events': len(events), 'adopted': added}


def _declare_roots(writes):
    """Create each declared writable directory (empty) so the confined launch binds exactly it."""
    for value in writes:
        path = Path(value)
        if path.suffix == '.json':
            continue  # a declared file is created by the launch itself
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise StudyHold('a declared output root must not traverse links')
        path.mkdir(parents=True, exist_ok=True)


def launch_state_root(root, child_relative):
    """The persistent state root of a child's confined launches (its lease, custody and steering records)."""
    return Path(root) / child_relative.parent / (child_relative.name + '.state')


def governed_workflow_root(specification, root, child_relative):
    """The controller-declared directory of a supplied workflow's adoption, or None for other modes."""
    from ravel.workflow import wms_adopt
    if (type(specification) is not dict or specification.get('mode') != wms_adopt.MODE
            or not wms_adopt.is_request(specification.get('task'))):
        return None
    return Path(root) / child_relative.parent / (child_relative.name + '.workflow')


def _terminate(process):
    """Stop the session created for this launch and reap its launcher."""
    def kill(sig):
        pid = getattr(process, 'pid', None)
        try:
            if pid and os.getpgid(pid) == pid:
                os.killpg(pid, sig)
                return
        except ProcessLookupError:
            return
        (process.terminate if sig == signal.SIGTERM else process.kill)()
    kill(signal.SIGTERM)
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        kill(signal.SIGKILL)
        process.communicate(timeout=2)


def dispatch(store, step, context):
    """Launch through P05, preserving attempt/cost journals over interruption."""
    from ravel.controller import confine, authority
    prepared = preflight(store, step, context)
    attempt = context.get('attempt', 1)
    key = step['id'] + ':' + str(attempt)
    lock = store.path('locks', 'study-operation.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock):
        found = [r for r in records(store, 'study-operation') if r.get('key') == key]
        if found:
            if found[0]['launch_sha256'] != prepared['launch_sha256']:
                raise StudyHold('restart changed an existing ordinary launch')
            outcomes = [r for r in found if 'outcome' in r]
            if outcomes:
                return deepcopy(outcomes[-1]['outcome'])
            raise StudyHold('reconcile the original interrupted ordinary attempt; do not resubmit')
        store.append('study-operation', {'key': key, 'event': 'reserved',
            'launch_sha256': prepared['launch_sha256'], 'wall_seconds': step['budget']['wall_seconds']})
    if authority.stop_state(store) != 'running':
        raise StudyHold('operator stopped before the confined ordinary launch')
    capsule = prepared['capsule']
    output_root = Path(prepared['output_root'])
    output_root.mkdir(parents=True, exist_ok=True)
    # The protected launch journal every host receipt and adoption reads: the host-operation
    # admission (a declared host operation such as the study preparation) binds this exact launch.
    from ravel.controller.step import host_operations
    host_decision = host_operations.admit(store, step, attempt, branch='launch')
    journal = store.append('step-launch', {'schema_version': 1, 'phase': 'started', 'host_decision': host_decision,
                                           'step_id': step['id'], 'attempt': attempt,
                                           'launch_sha256': prepared['launch_sha256'],
                                           'argv_sha256': digest(capsule['argv']), 'writes': capsule['writes'],
                                           'scope': {}, 'native_preflight': context.get('launch_preflight', {}).get('native_preflight')
                                           if isinstance(context.get('launch_preflight'), dict) else None})
    started = time.monotonic()
    store.append('study-operation', {'key': key, 'event': 'dispatch_started',
                                     'launch_sha256': prepared['launch_sha256']})
    launched = capsule
    broker = None
    from . import site
    if site.active_launch(run_id=store.run_id):
        # The launch capability is a secret minted after preflight: the admission,
        # the operation journal and the stored capsule keep the token-free digest,
        # and the record names the passed channel variables, never their values.
        passed = site.submission_environment()
        channels = []
        brokered = (step.get('parameters') or {}).get('site_broker')
        if brokered is not None:
            # A confined child cannot verify a capability against the run store, so it
            # never holds one: it requests each submission through the controller broker.
            from ravel.workflow import wms_broker
            broker = wms_broker.from_parameters(store, brokered)
            broker.start()
            passed = broker.environment(capsule['argv'][0])
            channels = [broker.socket_path]
        launched = {**capsule, 'env': {**capsule['env'], **passed}}
        record = {'key': key, 'launch_sha256': prepared['launch_sha256'], 'passed': sorted(passed)}
        if channels:
            launched['channels'] = [*(capsule.get('channels') or []), *channels]
            record['channels'] = channels
        try:
            store.append('study-operation-capability', record)
        except BaseException:
            if broker is not None:
                broker.stop()
            raise
    timed_out = False
    try:
        process = confine.popen(launched, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, cwd=output_root)
        try:
            stdout, stderr = process.communicate(timeout=capsule['limits']['wall_seconds'])
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process)
            stdout, stderr = '', 'ordinary launch reached its declared wall-clock ceiling'
    finally:
        if broker is not None:
            broker.stop()
    finish = getattr(confine, 'finish', None)
    confinement = finish(process) if callable(finish) else None
    plan = getattr(getattr(process, 'ravel_confinement', None), 'record', None) or {}
    inventory = []
    for path in sorted(output_root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        raw = path.read_bytes()
        inventory.append({'path': path.relative_to(output_root).as_posix(),
                          'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    plain_plan = json.loads(json.dumps(plan, sort_keys=True, default=str)) if type(plan) is dict else None
    plain_confinement = (json.loads(json.dumps(confinement, sort_keys=True, default=str))
                         if type(confinement) is dict else None)
    wall = max(0, time.monotonic() - started)
    backend = getattr(process, 'ravel_backend', None) or (plan or {}).get('backend')
    finished = store.append('step-launch', {'schema_version': 1, 'phase': 'finished', 'started': journal,
                                            'step_id': step['id'], 'attempt': attempt, 'exit_status': process.returncode,
                                            'timed_out': timed_out, 'wall_seconds': wall, 'inventory': inventory,
                                            'backend': backend, 'confinement': plain_confinement, 'plan': plain_plan})
    outcome = {'exit_status': process.returncode, 'timed_out': timed_out,
        'wall_seconds': wall, 'output_root': str(output_root),
        'launch_sha256': prepared['launch_sha256'], 'inventory': inventory,
        'confinement_probe': deepcopy(prepared['inventory']),
        'backend': backend, 'journal_id': journal, 'finished_id': finished,
        'plan': plain_plan, 'confinement': plain_confinement,
        'label': plan.get('label_text') if plan.get('kind') == 'unconfined' else 'ordinary_operation_contract',
        'confinement_errors': list((confinement or {}).get('errors') or ()),
        'quarantined': list((confinement or {}).get('quarantined') or ())}
    # The attempt keeps the launch's streams beside its outputs (the preflight fact names this
    # log path); the journal records their digests.
    logs = output_root.parent / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    for name, text in (('stdout', stdout), ('stderr', stderr)):
        with (logs / name).open('a', encoding='utf-8') as stream:
            stream.write(text or '')
    outcome['journal_adoption'] = adopt_launch_journal(store, _launched_child(capsule), journal)
    outcome['log_id'] = store.append('study-operation-log', {'key': key,
        'launch_sha256': prepared['launch_sha256'],
        'stdout_sha256': hashlib.sha256((stdout or '').encode()).hexdigest(),
        'stderr_sha256': hashlib.sha256((stderr or '').encode()).hexdigest(),
        'logs': str(logs)})
    store.append('study-operation', {'key': key, 'event': 'outcome',
        'launch_sha256': prepared['launch_sha256'], 'outcome': deepcopy(outcome)})
    return outcome


def scientific_checks(store, step, context, *, phase):
    """Bind descriptor checks to the current attempt's materialised ledger rows.

    Authored entry ids cannot target another step or an earlier attempt. Missing
    materialisation keeps that obligation open while ordinary source checks run.
    """
    bound = deepcopy(step)
    requirements = evidence.requirements(step)
    scope = context.get('ledger_scope')
    if requirements and scope is not None:
        from ravel.controller import ledger
        from ravel.controller.ledger.state import instance_key
        present = {row['entry'] for row in ledger.current(store, step=scope['step'])}
        for requirement in requirements:
            key = instance_key(requirement['row'], store.run_id, scope)
            requirement['entry_ids'] = [key] if key in present else []
        bound.setdefault('parameters', {})['evidence_requirements'] = requirements
    return evidence.check(store, bound, context, phase=phase)


def validate_outcome(store, step, outcome, context):
    problems = scientific_checks(store, step, context, phase='adopt')
    if outcome.get('timed_out') or outcome.get('exit_status', 0) != 0:
        problems.append({'code': 'ordinary_operation_failed', 'message': 'confined operation did not finish successfully'})
    if context.get('instruction_manifest_required'):
        problems.extend(evidence.instruction_errors(store, step, context,
            context.get('final_record') or {}, [r['path'] for r in step.get('outputs', [])]))
    if (step.get('parameters') or {}).get('action') == 'prepare':
        return problems
    try:
        ordinary, child, module, _ = _ordinary(step, context)
        with capsule_runtime():
            packet = (module.packet(child) if ordinary['kind'] == 'science'
                      else module.evaluate(child, context['contract']))
        pending_review = (ordinary['kind'] == 'science' and packet.get('execution', {}).get('status') == 'awaiting_review'
                          and packet.get('errors') == [])
        if pending_review:
            store.append('study-review-pending', {'step_id': step['id'], 'packet_sha256': digest(packet),
                                                  'labels': ['operation_review_pending']})
        if packet.get('lifecycle_verdict', packet.get('verdict')) != 'PASS' and not pending_review:
            problems.append({'code': 'ordinary_evidence_incomplete', 'message': 'operation lifecycle or result review failed'})
    except (ValueError, OSError, KeyError, TypeError) as exc:
        problems.append({'code': 'ordinary_evidence_invalid', 'message': str(exc)})
    return problems


def review_rows(store, step, *, credit_id):
    """Execution-only conditions are absent in an authenticated nonexecuting review.

    Delivered generation instructions do not turn a review into a generation
    action. The protected credit and validation records establish that boundary;
    an operation or an explicit descriptor binding still owes its own checks.
    """
    if step.get('kind') != 'review' or step.get('operation'):
        return {}
    credits = [r.get('record', r) for r in store.scan('step-credit')
               if r.get('id') == credit_id]
    if len(credits) != 1:
        return {}
    credit = credits[0]
    if credit.get('step_id') != step['id'] or credit.get('credited') is not True:
        return {}
    own = credit.get('own') or {}
    if own.get('credited') is not True:
        return {}
    bound = {r['row'] for r in evidence.requirements(step)}
    record = {'credit': credit_id, 'step_sha256': digest(step),
              'reason': 'not_applicable:credited_review_executes_no_scientific_operation'}
    return {row: {'status': 'not_applicable', 'evidence': deepcopy(record)}
            for row in ('E02', 'E06', 'E07', 'E08', 'E10', 'E13', 'E14', 'E17', 'E18')
            if row not in bound}


def child_review_rows(store, parent, *, credit_id, seat_key):
    """Execution absence from a credited child's protected, observed session.

    The parent's operation can generate events; its review worker cannot. The
    session's actual step, receipt, seat and attempt must match the credit before
    any execution-only duty of that child can be disposed.
    """
    credits = [row.get('record', row) for row in store.scan('step-credit') if row.get('id') == credit_id]
    if len(credits) != 1:
        return {}
    credit = credits[0]
    if credit.get('step_id') != parent.get('id') or credit.get('credited') is not True:
        return {}
    seats = [row for row in credit.get('seats') or () if row.get('seat') == seat_key]
    if len(seats) != 1:
        return {}
    seat = seats[0]
    attempt = credit.get('attempt')
    if (seat.get('credited') is not True or seat.get('status') != 'completed'
            or type(attempt) is not int or attempt < 1 or seat.get('attempt') != attempt
            or not seat.get('session_id') or not seat.get('receipt_sha256')):
        return {}
    sessions = []
    for row in store.scan('worker-session'):
        session = row.get('record', row)
        if (session.get('run_id') == store.run_id and session.get('seat') == seat_key
                and session.get('attempt') == attempt and session.get('session_id') == seat['session_id']
                and session.get('receipt_sha256') == seat['receipt_sha256']):
            sessions.append((row.get('id'), session))
    if len(sessions) != 1 or not sessions[0][0]:
        return {}
    session_id, session = sessions[0]
    step = session.get('step_spec') or {}
    parameters = step.get('parameters') or {}
    if (step.get('kind') != 'review' or step.get('operation') or step.get('role') != seat.get('role')
            or session.get('step') != step.get('id') or parameters.get('seat_of') != parent.get('id')
            or parameters.get('purpose') != 'review'):
        return {}
    bound = {row['row'] for row in evidence.requirements(step)}
    source = {'credit': credit_id, 'session': session_id, 'step_sha256': digest(step),
              'reason': 'not_applicable:credited_review_executes_no_scientific_operation'}
    return {row: {'status': 'not_applicable', 'evidence': deepcopy(source)}
            for row in ('E02', 'E06', 'E07', 'E08', 'E10', 'E13', 'E14', 'E17', 'E18') if row not in bound}


def supplied_pins(context):
    """The original supplied pins: the compiled request first, else the trusted packet field."""
    request = ((context.get('plan') or {}).get('parameters') or {}).get('study_request') or {}
    return request['supplied'] if 'supplied' in request else context.get('supplied', [])


def inspect_inputs(store, supplied, *, run_dir):
    """Read supplied bytes by pin; inventory never manufactures missing data.

    Run-relative pins and the entry's absolute real paths are both read without
    following links. A directory recorded without a digest stays explicitly unpinned.
    """
    root = Path(run_dir).absolute()
    rows = []
    for pin in supplied:
        value = pin['path']
        if type(value) is str and Path(value).is_absolute():
            path = Path(value)
            if path.as_posix() != value or '..' in path.parts:
                raise StudyHold('supplied input path is not an ordinary absolute path')
        else:
            path = root / relative(value)
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise StudyHold('supplied input traverses a symbolic link')
        if pin['sha256'] is None:
            if not path.is_dir():
                raise StudyHold('an unpinned supplied input must be an existing directory')
            rows.append({'path': pin['path'], 'sha256': None, 'size': None, 'kind': pin.get('kind'),
                         'content_pinned': False})
            continue
        if not path.is_file():
            raise StudyHold('supplied input is absent or not an ordinary file')
        content = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                content.update(chunk)
        if content.hexdigest() != pin['sha256']:
            raise StudyHold('supplied input differs from its original pin')
        rows.append({'path': pin['path'], 'sha256': pin['sha256'], 'size': path.stat().st_size,
                     'kind': pin.get('kind'), 'content_pinned': True})
    store.append('study-input-inventory', {'inputs': rows})
    return rows


def _run_root(child, child_relative):
    """The run directory a child's run-relative path was resolved against."""
    child, parts = Path(child).absolute(), relative(child_relative).parts
    if child.parts[-len(parts):] != parts:
        raise StudyHold('the child directory does not end with its declared run-relative path')
    return Path(*child.parts[:-len(parts)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'prepare', 'correct'])
    parser.add_argument('--kind', choices=['science', 'scoped'], required=True)
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--child-relative')
    parser.add_argument('--correction', type=Path)
    parser.add_argument('--contract', type=Path)
    parser.add_argument('--workflow-root', type=Path, help='governed external-workflow adoption root')
    parser.add_argument('--snakemake', help='the workflow manager entry the adopted study runs')
    args = parser.parse_args(argv)
    from ravel.workflow import science, scoped
    module = science if args.kind == 'science' else scoped
    if args.action == 'prepare':
        if args.spec is None or args.child_relative is None:
            parser.error('prepare requires --spec and --child-relative')
        relative(args.child_relative)
        if args.kind == 'scoped':
            if args.contract is None:
                parser.error('scoped prepare requires the original --contract')
            args.rundir.mkdir(parents=True, exist_ok=False)
            (args.rundir / 'inputs').mkdir()
            with (args.rundir / 'inputs/task_contract.json').open('xb') as stream:
                stream.write(args.contract.read_bytes())
        extra = {}
        if args.workflow_root is not None:
            # A supplied workflow request: adopt (static scan and pins) and plan its governed study here;
            # nothing of the workflow is parsed, run or approved before CHECK-IN 1.
            from ravel.workflow import wms_adopt
            if args.kind != 'science' or args.snakemake is None:
                parser.error('a governed workflow preparation needs a science child and --snakemake')
            request = read_json(args.spec)
            if request.get('mode') != wms_adopt.MODE or not wms_adopt.is_request(request.get('task')):
                raise StudyHold('the governed workflow preparation needs an external-workflow request specification')
            study = {key: request[key] for key in wms_adopt.STUDY_KEYS}
            proposal = wms_adopt.prepare_governed(request['task'], study, base=_run_root(args.rundir, args.child_relative),
                                                  child=args.rundir, workflow_root=args.workflow_root,
                                                  snakemake=args.snakemake)
            extra = {'site_launch': proposal.get('site_launch'), 'workflow_root': proposal['workflow_root'],
                     'adoption': proposal['adoption']}
        else:
            proposal = module.plan(args.rundir, args.spec)
        ordinary = {'kind': args.kind, 'child_rundir': args.child_relative,
            'plan_sha256': hashlib.sha256((args.rundir / module.PLAN).read_bytes()).hexdigest(),
            'specification_sha256': hashlib.sha256((args.rundir / module.SPEC).read_bytes()).hexdigest()}
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with args.receipt.open('x') as stream:
            json.dump({'kind': 'ordinary-study-preparation', 'ordinary': ordinary, 'proposal': proposal, **extra},
                      stream, sort_keys=True, allow_nan=False, default=str)
        return 0
    if args.action == 'correct':
        if args.kind != 'science' or args.correction is None:
            parser.error('correct requires a science child and --correction')
        correction = read_json(args.correction)
        keys = {'actor_id', 'changed_paths', 'recheck_checks', 'max_seconds', 'supporting_artifacts'}
        if type(correction) is not dict or set(correction) != keys:
            raise StudyHold('exact prospectively bound correction arguments required')
        science.correct(args.rundir, **correction)
    code = module.run(args.rundir)
    # Serialize only source-owned result/verification facts. An exit code by
    # itself never creates a scientific delivery or an accepted label.
    if args.kind == 'science':
        packet = science.packet(args.rundir)
    else:
        packet = scoped.evaluate(args.rundir, read_json(args.rundir / 'inputs/task_contract.json'))
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    passed = not code and packet.get('lifecycle_verdict', packet.get('verdict')) == 'PASS'
    pending = (not code and args.kind == 'science' and packet.get('execution', {}).get('status') == 'awaiting_review'
               and packet.get('errors') == [])
    products = (module.controller_products(args.rundir, allow_pending_review=True) if pending
                else module.controller_products(args.rundir) if passed else {'packet': packet})
    with args.receipt.open('x') as stream:
        json.dump({'kind': 'ordinary-study-receipt', 'exit_status': code or (0 if passed or pending else 3),
                   **products}, stream, sort_keys=True, allow_nan=False)
    return code or (0 if passed or pending else 3)


if __name__ == '__main__':
    raise SystemExit(main())


def scientific_review_queries(store, step, *, attempt):
    """Discover a canonical latest credited E08 collection query without granting credit.

    The evidence validator separately verifies the actual reviewed member bytes,
    child session and current independence decision before accepting this query.
    """
    if type(attempt) is not int or attempt < 1 or not any(row['row'] == 'E08' for row in evidence.requirements(step)):
        return {}
    credits = [entry.get('record', entry) for entry in store.scan('step-credit')
               if entry.get('record', entry).get('step_id') == step.get('id')
               and entry.get('record', entry).get('attempt') == attempt]
    if not credits or credits[-1].get('credited') is not True:
        return {}
    seats = [seat for seat in credits[-1].get('seats') or ()
             if seat.get('credited') is True and seat.get('status') == 'completed' and seat.get('verdict') == 'accept']
    if not seats:
        return {}
    for seat in seats:
        query = seat.get('query')
        if (type(query) is not dict or seat.get('attempt') != attempt
                or any(type(query.get(key)) is not str or not query[key].strip()
                       for key in ('run', 'subject_sha256', 'role'))
                or type(seat.get('seat')) is not str or not seat['seat'].strip()
                or seat.get('role') != query['role'] or seat.get('subject_sha256') != query['subject_sha256']):
            return {}
    identities = {(seat['query']['run'], seat['query']['subject_sha256']) for seat in seats}
    if len(identities) != 1 or len({seat['seat'] for seat in seats}) != len(seats):
        return {}
    selected = min(seats, key=lambda seat: (seat['role'], seat['seat']))
    return {'E08': deepcopy(selected['query'])}
