"""Exact native-action identity and read-only replay of its protected admission."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from . import custody, operations, spec
from .services import StepHold, digest

RUNG_KINDS = {None: 'dry_run', 'none': 'dry_run', 'dry': 'dry_run',
              'smoke': 'smoke_launch', 'pilot': 'single_point_launch',
              'full': 'bulk_launch', 'scan': 'scan_launch'}
ACTION_FIELDS = {'kind', 'step', 'node_id', 'rung', 'floor', 'view_pins', 'digest', 'budget'}
PIN_FIELDS = {'plan_sha256', 'step_sha256', 'launch_sha256', 'attempt', 'native_preflight'}


def _sha(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def selected(rundir, value):
    """Recognize native identity from markers or the protected current step, never caller kind."""
    from ravel.controller import store as stores
    from ravel.workflow import rdj_approval
    try:
        if type(value) is not dict:
            return False
        pins = value.get('view_pins')
        if 'step' in value or type(pins) is dict and 'native_preflight' in pins:
            return True
        root = Path(rundir)
        if not stores.controller_owned(root):
            return False
        store, scientific = rdj_approval.controller_plan(root)
        if store.check_binding(root) or store.verify():
            raise ValueError('native selection requires the bound verified controller journal')
        plan = operations.current_plan(store, {'plan_sha256': scientific['sha256']})
        steps = [step for step in plan.get('steps') or ()
                 if type(step) is dict and step.get('id') == value.get('node_id')]
        if len(steps) > 1:
            raise ValueError('native selection found an ambiguous protected plan step')
        return bool(steps and (steps[0].get('kind') in ('operate', 'acquire') or spec.launch(steps[0]) is not None))
    except (OSError, KeyError, TypeError, AttributeError, StepHold) as exc:
        raise ValueError('native action selection unavailable: ' + str(exc)) from None


def consequence_action(step):
    """The policy inputs shared by wave selection and the eventual exact native action."""
    rung, floor = step.get('rung'), step.get('consequence_class', 'R0')
    if type(floor) is not str or floor not in ('R0', 'R1', 'R2', 'R3'):
        raise ValueError('native action consequence class must be one of R0-R3')
    if rung not in RUNG_KINDS:
        raise ValueError('native action requires the actual rung, attempt, budget and complete identity')
    return {'kind': RUNG_KINDS[rung], 'rung': rung, 'floor': floor}


def action(step, context, prepared, preflight_record):
    """Construct launch kind and pins from the actual step, reservation and preflight."""
    try:
        consequence = consequence_action(step)
        attempt = context.get('attempt')
        if (type(attempt) is not int or attempt < 1
                or type(step.get('id')) is not str or not step['id']
                or not _sha(context.get('plan_sha256')) or not _sha(prepared.get('launch_sha256'))
                or type(preflight_record) is not str or not preflight_record
                or type(prepared.get('budget')) is not dict):
            raise ValueError('native action requires the actual rung, attempt, budget and complete identity')
        pins = {'plan_sha256': context['plan_sha256'], 'step_sha256': spec.step_sha256(step),
                'launch_sha256': prepared['launch_sha256'], 'attempt': str(attempt),
                'native_preflight': preflight_record}
        return {**consequence, 'step': step['id'], 'node_id': step['id'],
                'view_pins': pins, 'digest': digest(pins), 'budget': deepcopy(prepared['budget'])}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('native action identity is malformed: ' + str(exc)) from None


STUDY_ADAPTER = 'ravel.controller.routes.study.runtime'


def study_preparation_implementation(step):
    """The installed ordinary-study preparation: the adapter's own prepare command, confined, no network.

    It plans the ordinary child from the adopted specification; for a supplied workflow it also adopts
    the workflow by a static scan and writes its site profile. Nothing is parsed, run or approved.
    """
    params = spec.parameters(step)
    if (step.get('kind') != 'operate' or step.get('operation') != 'ordinary-study-prepare'
            or params.get('phase') != 'prepare' or params.get('action') != 'prepare'):
        return None
    signature = operations.signatures().get(step.get('operation')) or {}
    events = (step.get('budget') or {}).get('events')
    if (step.get('rung') not in (None, 'none', 'dry') or params.get('adapter') != STUDY_ADAPTER
            or spec.launch(step) != {'adapter': STUDY_ADAPTER} or signature.get('effects') != []
            or (signature.get('cost') or {}).get('unit') != 'seconds' or type(events) is not int or events != 0):
        raise ValueError('study preparation requires its zero-event, zero-effect adapter signature at a dry rung')
    import sys
    from ravel.controller.routes.study import runtime
    from ravel.workflow import wms_adopt
    from ravel.workflow.execution import file_hash as file_sha256
    return {'entrypoint': STUDY_ADAPTER + ':preparation', 'interpreter': sys.executable,
            'argv_prefix': [sys.executable, '-m', STUDY_ADAPTER, 'prepare'], 'bounded_read_only': True,
            'kind': 'ordinary-study-preparation',
            'code': {str(Path(path).resolve()): file_sha256(Path(path).resolve())
                     for path in (runtime.__file__, wms_adopt.__file__)}}


def preparation_implementation(step):
    """The installed bounded source-reader or study-preparation capability, never a generic phase exemption."""
    from ravel.controller.routes.analysis.execution import acquisition_implementation
    params = spec.parameters(step)
    study = study_preparation_implementation(step)
    if study is not None:
        return study
    if params.get('phase') != 'prepare' or step.get('kind') != 'acquire':
        return None
    signature = operations.signatures().get(step.get('operation')) or {}
    maximum = (params.get('task') or {}).get('max_bytes')
    events = (step.get('budget') or {}).get('events')
    if (step.get('rung') not in (None, 'none', 'dry')
            or signature.get('effects') != ['acquires_published']
            or (signature.get('cost') or {}).get('unit') != 'bytes'
            or type(maximum) is not int or maximum <= 0 or type(events) is not int or events != 0):
        raise ValueError('preparation requires a bounded zero-event source-acquisition signature')
    implementation = acquisition_implementation(step)
    argv = (spec.launch(step) or {}).get('argv')
    prefix = (implementation or {}).get('argv_prefix')
    if (type(implementation) is not dict or implementation.get('bounded_read_only') is not True
            or type(prefix) is not list or not prefix or not all(type(word) is str and word for word in prefix)
            or type(argv) is not list or argv[:len(prefix)] != prefix
            or type(implementation.get('code')) is not dict or not implementation['code']
            or any(not Path(path).is_absolute() or not _sha(value)
                   for path, value in implementation['code'].items())):
        raise ValueError('preparation requires its current installed bounded source-reader implementation')
    return implementation


def load(rundir, value):
    """Return ``(store, applied plan, exact step, preflight proof)`` after fresh checks.

    This interface establishes launch admission only. It supplies no approval,
    review credit, execution receipt or host waiver.
    """
    from ravel.controller import store as stores
    from ravel.controller.confine import commitments
    try:
        if type(value) is not dict or set(value) != ACTION_FIELDS:
            raise ValueError('native action fields differ from the closed controller interface')
        pins = value.get('view_pins')
        if type(pins) is not dict or set(pins) != PIN_FIELDS or value.get('digest') != digest(pins):
            raise ValueError('native action does not bind its exact view pins')
        if not all(_sha(pins.get(key)) for key in ('plan_sha256', 'step_sha256', 'launch_sha256')):
            raise ValueError('native action source digests are malformed')
        attempt = pins.get('attempt')
        if type(attempt) is not str or not attempt.isascii() or not attempt.isdecimal() or str(int(attempt)) != attempt or int(attempt) < 1:
            raise ValueError('native action has no canonical positive attempt')
        if type(pins.get('native_preflight')) is not str or not pins['native_preflight']:
            raise ValueError('native action has no protected preflight record')
        root = Path(rundir)
        owner = stores.controller_owned(root)
        if not owner:
            raise ValueError('native action requires a controller-owned run')
        store = stores.RunStore(owner)
        if store.check_binding(root) or store.verify():
            raise ValueError('native action run binding or protected journal does not verify')
        context = {'plan_sha256': pins['plan_sha256'], 'attempt': int(attempt)}
        plan = operations.current_plan(store, context)
        if plan.get('sha256') != pins['plan_sha256']:
            raise ValueError('native action names another protected plan')
        steps = [row for row in plan.get('steps') or () if type(row) is dict and row.get('id') == value['step']]
        if len(steps) != 1:
            raise ValueError('native action has no unique approved step')
        step = steps[0]
        if pins['step_sha256'] != spec.step_sha256(step):
            raise ValueError('native action step differs from the protected applied step')
        proof = store.read('step-fact', pins['native_preflight'])['record']
        if (proof.get('mechanism') != 'native-launch-preflight' or proof.get('passed') is not True
                or proof.get('step_id') != step['id'] or type(proof.get('attempt')) is not int
                or proof['attempt'] != int(attempt)
                or any(proof.get(key) != pins[key] for key in ('plan_sha256', 'step_sha256', 'launch_sha256'))):
            raise ValueError('native action has no matching passed protected preflight')
        expected = action(step, context, {'launch_sha256': proof['launch_sha256'],
                                         'budget': proof.get('budget')}, pins['native_preflight'])
        if digest(expected) != digest(value):
            raise ValueError('native action differs from actual step, attempt or protected reservation')
        implementation = preparation_implementation(step)
        if implementation is not None or 'preparation_implementation' in proof:
            if (implementation is None or proof.get('preparation_implementation') != implementation
                    or type((proof.get('budget') or {}).get('events')) is not int or proof['budget']['events'] != 0):
                raise ValueError('preparation source implementation or zero-event reservation changed')
        else:
            commitments.verify(store, plan, step, root)
        problems, found, _ = custody.input_errors(store, step, root)
        problems += custody.parent_errors(store, step)
        problems += operations.executor_errors(step)
        problems += operations.admission_errors(step, inputs_custody=found, approved=step,
            context={'store': store, 'run_dir': root, 'plan': plan})
        if problems:
            raise ValueError('native launch admission refused: ' + str(problems)[:1200])
        return store, plan, deepcopy(step), deepcopy(proof)
    except (OSError, KeyError, TypeError, AttributeError, StepHold) as exc:
        raise ValueError('native launch admission unavailable: ' + str(exc)) from None


def _ordered(rows):
    previous = 0
    for row in rows:
        seq = row.get('seq')
        if type(seq) is not int or seq <= previous:
            raise ValueError('native review admission requires ordered protected journal sequences')
        previous = seq
    return rows


def _corrections_started(store, plan, step, review):
    """Count executed prior rounds globally; a producer never repeats after this review."""
    facts = _ordered(store.scan('step-fact'))
    indexed = {row['id']: row for row in facts}
    if len(indexed) != len(facts):
        raise ValueError('native preflight facts have duplicate protected identities')
    done = set()
    for launch in _ordered(store.scan('step-launch')):
        body = launch['record']
        if body.get('phase') != 'started':
            continue
        fact = indexed.get(body.get('native_preflight'))
        if fact is None:
            raise ValueError('a started native effect has no exact protected preflight link')
        proof = fact['record']
        if (fact['seq'] >= launch['seq'] or proof.get('mechanism') != 'native-launch-preflight'
                or proof.get('passed') is not True
                or any(body.get(key) != proof.get(key) or body.get(key) is None
                       for key in ('step_id', 'attempt', 'launch_sha256'))):
            raise ValueError('a started native effect differs from its linked preflight')
        correction = proof.get('correction') or {}
        if proof.get('plan_sha256') != plan['sha256'] or correction.get('purpose') != 'waypoint':
            continue
        number = correction.get('round')
        if type(number) is not int or number < 1:
            raise ValueError('a started waypoint correction has no positive round')
        if launch['seq'] < review['seq']:
            done.add(number)
        elif proof['step_id'] == step['id']:
            raise ValueError('this producer already started a correction after the latest waypoint review')
    return len(done)


def _scientific_review(store, plan, step, proof):
    from ravel.controller import graph
    from ravel.controller.authority import mode
    from ravel.workflow import physics_review, review_enforcement
    rounds = _ordered([row for row in store.scan('review')
                       if row['record'].get('purpose') == 'waypoint'
                       and row['record'].get('plan_sha256') == plan['sha256']])
    result = {'mechanism': 'controller.native-review-admission', 'plan_sha256': plan['sha256'],
              'step_id': step['id'], 'waypoint_review': rounds[-1]['id'] if rounds else None}
    if rounds and not graph._accepted(rounds[-1]['record'].get('seats') or {}):
        row = rounds[-1]
        record = row['record']
        if step['id'] not in (plan.get('waypoints') or []) or type(proof.get('correction')) is not dict:
            raise ValueError('the latest waypoint review blocks this native action')
        if (type(record.get('attempt')) is not int or record['attempt'] < 1
                or type(record.get('subject')) is not dict or not record['subject']
                or record.get('subject_sha256') != digest(record['subject'])):
            raise ValueError('the protected waypoint review subject is malformed')
        done = _corrections_started(store, plan, step, row)
        bound = graph.correction_rounds({'mode': mode.frozen(store)})
        correction, problem = graph.review_correction(store, purpose='waypoint',
            verdicts=record['seats'], subject_sha256=record['subject_sha256'],
            attempt=record['attempt'], done=done, bound=bound)
        if problem is not None or digest(correction) != digest(proof['correction']):
            raise ValueError('native correction does not replay the protected review and frozen bound: ' + str(problem))
        result['correction'] = deepcopy(correction)
    if physics_review.registered(store.run_dir):
        capsule = proof.get('capsule')
        if (type(capsule) is not dict or not all(key in capsule for key in ('argv', 'reads', 'writes', 'cwd'))
                or not proof.get('stage') or not proof.get('log')
                or proof.get('depends_on') != step.get('depends_on')):
            raise ValueError('legacy scientific review requires the actual protected launch capsule and paths')
        correction_id = review_enforcement.before_stage(store.run_dir, proof['stage'], capsule['argv'],
            capsule['reads'], capsule['writes'], step['depends_on'], capsule['cwd'], proof['log'])
        if correction_id is not None:
            raise ValueError('a legacy correction requires its owning adapter and full lifecycle')
        result['legacy_review'] = 'checked'
    return result


def _preparation_authority(store, plan, step, proof, preflight):
    """Replay a later exact effect against today's real frozen and narrowed authority."""
    from ravel.controller.authority.operator import BUDGET_KEYS, _number, budget_integer
    from ravel.controller.authority.service import authorize_effect
    fact = store.read('step-fact', preflight)
    seq = fact.get('seq')
    if type(seq) is not int or seq < 1:
        raise ValueError('preparation needs its ordered protected preflight')
    matching = [row for row in _ordered(store.scan('step-authority'))
                if row['record'].get('step_id') == step['id']
                and type(row['record'].get('attempt')) is int
                and row['record']['attempt'] == proof['attempt']
                and row['record'].get('plan_sha256') == plan['sha256']]
    if not matching or matching[-1]['seq'] <= seq or not matching[-1].get('id'):
        raise ValueError('preparation needs a later exact current authority effect')
    row = matching[-1]
    effect = row['record'].get('effect') or {}
    stage = proof.get('stage') or (spec.launch(step) or {}).get('stage') or step.get('operation') or step['kind']
    rung = step.get('rung') or 'none'
    dimensions = {key: key for key in BUDGET_KEYS}
    dimensions.update(broker_calls='model_calls', attempts=None)
    requested = {}
    for source in (step.get('budget') or {}, proof['budget']):
        mapped = {}
        for key, value in source.items():
            if key not in dimensions:
                raise ValueError('preparation has an unknown authority budget dimension')
            dimension = dimensions[key]
            if dimension is None:
                continue
            if not _number(value, integer=budget_integer(dimension)):
                raise ValueError('preparation authority budget is not finite and nonnegative')
            mapped[dimension] = mapped.get(dimension, 0) + value
        requested.update(mapped)
    if (effect.get('id') != step['id'] or effect.get('pins') != {'plan_sha256': plan['sha256']}
            or effect.get('rung') != rung or effect.get('plan') != rung or effect.get('stage') != stage
            or type(effect.get('started_ns')) is not int or effect['started_ns'] <= 0
            or effect.get('budget') != requested):
        raise ValueError('preparation authority does not cover the exact effect and reservation')
    fresh = authorize_effect(store, deepcopy(effect))
    if (row['record'].get('authority') != fresh or not fresh.get('mode_record')
            or fresh.get('approve_plan') is not None or fresh.get('go') is not None):
        raise ValueError('preparation authority or frozen mode changed')
    return row['id'], fresh['mode_record']


def approval(rundir, value):
    """Map a native action to actual approval, scientific review and exact R3 authority."""
    from ravel.controller.authority import rdj, retained
    from ravel.workflow import rdj_approval, rdj_loop
    try:
        store, plan, step, proof = load(rundir, value)
        required, _ = rdj_loop.compute_class(rundir, 'launch', value)
        implementation = preparation_implementation(step)
        if implementation is not None:
            if required not in ('R0', 'R1'):
                raise ValueError('bounded preparation mapping is limited to at-most-R1 actions')
            authority_id, mode_id = _preparation_authority(store, plan, step, proof,
                                                          value['view_pins']['native_preflight'])
            reviewed = _scientific_review(store, plan, step, proof)
            return [], {'schema_version': 1, 'mechanism': 'controller.native_preparation.mapping',
                        'action_digest': value['digest'], 'native_preflight': value['view_pins']['native_preflight'],
                        'view_pins': deepcopy(value['view_pins']), 'preparation_authority': authority_id,
                        'mode_record': mode_id, 'preparation_implementation': deepcopy(implementation),
                        'scientific_review': reviewed}
        native_case = None
        if required == 'R3':
            from . import native_authority
            if not native_authority.active(rundir, value):
                raise ValueError('native R3 action requires its exact authenticated retained action context')
            missing, native_case = native_authority.evaluate(rundir, value)
            if missing:
                return list(missing), None
        approved = retained.current(store, 'approve_plan')
        pins = approved['view']['pins']
        if pins.get('plan_sha256') != plan['sha256'] or approved['plan'].get('sha256') != plan['sha256']:
            raise ValueError('the retained approval covers another current plan')
        missing, mapped = rdj_approval.evaluate(store.run_dir, rdj.approval_action(pins))
        if missing:
            return list(missing), None
        reviewed = _scientific_review(store, plan, step, proof)
        return [], {'schema_version': 1, 'mechanism': 'controller.native_launch.mapping',
                    'action_digest': value['digest'], 'native_preflight': value['view_pins']['native_preflight'],
                    'view_pins': deepcopy(value['view_pins']), 'approval_context': approved['id'],
                    'approval': mapped, 'scientific_review': reviewed,
                    **({'native_case': native_case, 'operator_authority': native_case['authority']}
                       if native_case is not None else {})}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration, StepHold) as exc:
        return [str(exc)[:1500]], None
