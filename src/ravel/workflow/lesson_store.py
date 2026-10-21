"""Lesson store, do-not-learn gate, promotion lifecycle and serving gate.

``knowledge_lessons`` judges one record. This module decides what may be written (candidates
only, through the do-not-learn gate), how a lesson moves ``candidate -> trial -> promoted`` or to
``revoked``/``dormant``, and which reader may see it. Candidates reach only RCA investigators and
the tool's consult; a trial lesson appears only inside the "with" side of a paired arm; at most
three promoted lessons are served per node; reviewers never receive lessons.

Every lesson carries ``evidence.origin`` (request digest and run id). A benchmark arm loads the
local store ``frozen`` from a snapshot or ``disabled``, and the run records the mode and the digest
of every lesson it serves, shipped lessons included. When an evaluator-supplied excluded-origin set
is configured, the withheld screen is mandatory: a lesson from an excluded run or request, or one
quoting an excluded document, pin or path, is refused at write and withheld at load.
The store is empty until real runs produce tickets.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re

from .knowledge_atlas import digest, encode
from .knowledge_lessons import lesson_errors, trigger_fires

SHIPPED = Path(__file__).resolve().parents[1] / 'data/knowledge/lessons'
LOCAL = Path('.ravel/knowledge/lessons')
MODES = ('live', 'frozen', 'disabled')
MAX_PROMOTED_PER_NODE = 3
GENERALITY_LIMIT = 0.30
RECEIPT_KINDS = ('check_result', 'stage_log', 'test_result', 'repair_diff', 'artifact',
                 'reviewer_verdict', 'model_prose')
OPINION_KINDS = frozenset(('reviewer_verdict', 'model_prose'))
DIRECTIONS = ('higher', 'lower')
LIFECYCLE_FIELDS = ('status', 'lifecycle', 'impact')
REVIEWER_KINDS = ('voting', 'specialist')
# Independence kinds that may read lessons; any other or missing kind is served as a reviewer.
READER_KINDS = ('producer', 'advisory', 'investigation')
_HEX = re.compile(r'[0-9a-f]{64}')
_NUMBER = re.compile(r'(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])')


def _receipt_ok(receipt):
    return isinstance(receipt, dict) and bool(receipt.get('path')) and bool(_HEX.fullmatch(str(receipt.get('sha256', ''))))


def origin_errors(origin) -> list[str]:
    """Delta-Wa3: a learned record names the request digest and run that produced it."""
    if not isinstance(origin, dict) or not _HEX.fullmatch(str(origin.get('request_digest', ''))) \
            or not isinstance(origin.get('run_id'), str) or not origin['run_id'].strip():
        return ['origin needs a sha256 request_digest and a run_id']
    return []


def _do_not_learn():
    """The protected-path do-not-learn rule, or None when it is not installed."""
    try:
        from ravel.validation.check_protected_paths import suppression_rule
    except ImportError:
        return None
    return suppression_rule


def _numbers(text):
    values = []
    for token in _NUMBER.findall(text):
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def withheld_errors(lesson, withheld) -> list[str]:
    """A lesson may not carry a withheld identifier or a number from a withheld source (R-10/R-11).

    ``withheld`` is supplied by the harness: ``{"ids": [...], "numbers": [...]}``; none is kept here.
    """
    if not withheld:
        return []
    text = json.dumps({k: lesson.get(k) for k in ('id', 'title', 'trigger', 'body')}, sort_keys=True)
    folded = text.casefold()
    errors = ['carries a withheld identifier' for i in withheld.get('ids', ()) if str(i).casefold() in folded][:1]
    present = _numbers(json.dumps(lesson.get('body', '')) + ' ' + json.dumps(lesson.get('trigger')))
    for number in withheld.get('numbers', ()):
        if any(math.isclose(float(number), v, rel_tol=1e-9, abs_tol=1e-12) for v in present):
            errors.append('carries a number from a withheld source'); break
    return errors


def _origins(excluded_origins):
    from .literature_index import normalize_excluded_origins
    if excluded_origins is None:
        from .literature_settings import configured_excluded_origins
        return configured_excluded_origins()
    return normalize_excluded_origins(excluded_origins)


def origin_match_errors(lesson, excluded_origins) -> list[str]:
    """A lesson descending from or quoting an excluded origin (its run, request, document, pin or path)."""
    origins = _origins(excluded_origins)
    if not origins or not isinstance(lesson, dict):
        return []
    evidence = lesson.get('evidence') if isinstance(lesson.get('evidence'), dict) else {}
    origin = evidence.get('origin') if isinstance(evidence.get('origin'), dict) else {}
    receipts = [r for r in evidence.get('receipts', ()) if isinstance(r, dict)] \
        if isinstance(evidence.get('receipts'), list) else []
    folded = json.dumps(lesson, sort_keys=True, default=str).casefold()
    for kind, value in origins:
        if kind == 'run' and value in (origin.get('run_id'), origin.get('request_digest')):
            return ['descends from an excluded run']
        if kind == 'pin' and any(r.get('sha256') == value for r in receipts):
            return ['rests on an excluded pin']
        if kind == 'path' and any(str(r.get('path', '')) == value or str(r.get('path', '')).startswith(value + '/')
                                  for r in receipts):
            return ['rests on an excluded path']
        if value.casefold() in folded:
            return ['quotes an excluded origin']
    return []


def gate_errors(lesson, *, retained_facts, withheld=None, check_ids=None, do_not_learn=None,
                excluded_origins=None) -> list[str]:
    """Reasons the writer refuses a lesson (KM section 2.5 do-not-learn gate); empty means accepted.

    ``retained_facts`` are the run facts of retained runs; a trigger firing on more than 30% of
    them is too generic. ``do_not_learn`` defaults to the protected-path rule; without it every
    lesson is refused (fail closed).
    """
    errors = list(lesson_errors(lesson, check_ids=check_ids))
    if not isinstance(lesson, dict):
        return errors
    name = str(lesson.get('id', '?')) + ': '
    evidence = lesson.get('evidence') if isinstance(lesson.get('evidence'), dict) else {}
    own = origin_errors(evidence.get('origin'))
    receipts = evidence.get('receipts') if isinstance(evidence.get('receipts'), list) else []
    kinds = [r.get('kind') for r in receipts if isinstance(r, dict)]
    if any(k not in RECEIPT_KINDS for k in kinds):
        own.append('every receipt needs a kind in ' + '|'.join(RECEIPT_KINDS))
    elif kinds and set(kinds) <= OPINION_KINDS:
        own.append('rests on a reviewer verdict or model prose alone')
    if _origins(excluded_origins) and not isinstance(withheld, dict):
        own.append('the withheld screen is required while an excluded-origin set is configured')
    own += withheld_errors(lesson, withheld)
    own += origin_match_errors(lesson, excluded_origins)
    if not isinstance(retained_facts, (list, tuple)):
        own.append('retained run facts are required to measure trigger generality')
    elif retained_facts:
        try:
            fired = sum(1 for facts in retained_facts if trigger_fires(lesson['trigger'], facts))
        except (KeyError, TypeError, AttributeError):
            fired = 0  # a malformed trigger is already refused by lesson_errors
        if fired / len(retained_facts) > GENERALITY_LIMIT:
            own.append(f'trigger fires on {fired} of {len(retained_facts)} retained runs (limit 30%)')
    rule = do_not_learn or _do_not_learn()
    if rule is None:
        own.append('do-not-learn rule unavailable: the protected-path manifest is not installed')
    else:
        text = ' \n'.join(str(lesson.get(k) or '') for k in ('title', 'body'))
        own += ['do-not-learn: weakens a check, trap, gate or threshold: ' + s
                for s in rule(text, known_ids=sorted(check_ids or ()))]
    errors += [name + e for e in own]
    return list(dict.fromkeys(errors))


# ----------------------------------------------------------------------------- store

def _file(lesson_id):
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(lesson_id)) + '.json'


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, indent=2, sort_keys=True) + '\n'
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(raw)
    os.replace(temporary, path)
    return path


def write_candidate(root, lesson, *, retained_facts, withheld=None, check_ids=None, do_not_learn=None,
                    excluded_origins=None) -> Path:
    """Record a candidate lesson in the project's local store after the do-not-learn gate.

    The writer records candidates only; promotion goes through ``to_trial`` and ``promote``. A
    run-time procedure from an ``engineer`` verdict enters here as a candidate too.
    """
    if not isinstance(lesson, dict) or lesson.get('status') != 'candidate' or lesson.get('impact') is not None \
            or lesson.get('lifecycle'):
        raise ValueError('the writer records new candidates only')
    errors = gate_errors(lesson, retained_facts=retained_facts, withheld=withheld, check_ids=check_ids,
                         do_not_learn=do_not_learn, excluded_origins=excluded_origins)
    if errors:
        raise ValueError('lesson refused: ' + '; '.join(errors))
    path = Path(root) / LOCAL / _file(lesson['id'])
    if path.exists() and json.loads(path.read_text()) != lesson:
        raise ValueError('a different lesson already holds this id: ' + str(lesson['id']))
    return _write(path, lesson)


def update_lesson(root, lesson, *, excluded_origins=None) -> Path:
    """Replace a stored local lesson with its next lifecycle state (from ``to_trial``/``promote``/...)."""
    if origin_match_errors(lesson, excluded_origins):
        raise ValueError('lesson update refused: excluded origin')
    path = Path(root) / LOCAL / _file(lesson['id'])
    if not path.is_file():
        raise ValueError('no stored lesson with id ' + str(lesson['id']))
    stored = json.loads(path.read_text())
    if stored.get('lifecycle', []) != lesson.get('lifecycle', [])[:len(stored.get('lifecycle', []))]:
        raise ValueError('lifecycle history cannot be rewritten')
    # Only the transition fields may change; the content passed the do-not-learn gate at write time.
    changed = sorted(k for k in set(stored) | set(lesson) if k not in LIFECYCLE_FIELDS and stored.get(k) != lesson.get(k))
    if changed:
        raise ValueError('a lifecycle update changes gated lesson content: ' + ', '.join(changed))
    errors = lesson_errors(lesson) + promotion_errors(lesson)
    if errors:
        raise ValueError('lesson refused: ' + '; '.join(errors))
    return _write(path, lesson)


def _read_dir(directory):
    rows = []
    for path in sorted(Path(directory).glob('*.json')) if Path(directory).is_dir() else []:
        rows.append(json.loads(path.read_text()))
    return rows


def load_lessons(root, *, mode='live', snapshot=None, shipped=None, excluded_origins=None) -> dict:
    """Shipped lessons plus the local store in the declared mode, with the digest a run records.

    ``frozen`` reads the local lessons of a snapshot from ``export_snapshot`` (checked against its
    digest), ``disabled`` reads none; shipped, developer-reviewed lessons are read in every mode.
    ``snapshot_sha256`` hashes every served lesson, shipped ones included, in every mode; a frozen
    load also reports the snapshot's own digest as ``local_snapshot_sha256``. With an
    excluded-origin set, lessons that descend from or quote one, or carry no origin, are withheld.
    """
    excluded_origins = _origins(excluded_origins)
    if mode not in MODES:
        raise ValueError('mode must be one of ' + '|'.join(MODES))
    lessons = _read_dir(SHIPPED if shipped is None else shipped)
    if mode == 'live':
        local = _read_dir(Path(root) / LOCAL)
    elif mode == 'frozen':
        if not isinstance(snapshot, dict) or snapshot_errors(snapshot):
            raise ValueError('frozen mode needs a valid store snapshot')
        local = snapshot['lessons']
    else:
        local = []
    lessons = lessons + local
    withheld = []
    if _origins(excluded_origins):
        withheld = sorted(str(r.get('id')) for r in lessons
                          if origin_match_errors(r, excluded_origins)
                          or origin_errors(((r.get('evidence') or {}) if isinstance(r, dict) else {}).get('origin')))
        lessons = [r for r in lessons if str(r.get('id')) not in withheld]
    loaded = {'mode': mode, 'lessons': lessons, 'lesson_ids': sorted(str(r.get('id')) for r in lessons),
              'snapshot_sha256': digest(encode(lessons))}
    if mode == 'frozen':
        loaded['local_snapshot_sha256'] = snapshot['snapshot_sha256']
    if withheld:
        loaded['withheld_lesson_ids'] = withheld
    return loaded


def _excluded(row, tokens):
    origin = (row.get('evidence') or {}).get('origin') if 'evidence' in row else row.get('run')
    origin = origin if isinstance(origin, dict) else {}
    keys = {row.get('id'), origin.get('run_id'), origin.get('id'), origin.get('request_digest')}
    return bool(keys & tokens)


def export_snapshot(root, *, exclusions=()) -> dict:
    """Delta-Wa3: export the local lessons and outcomes, leaving out every record the harness names.

    ``exclusions`` lists record ids, run ids or request digests; the export records its digest.
    """
    from .lesson_store_outcomes import LOCAL as OUTCOMES
    tokens = {str(t) for t in exclusions}
    lessons = _read_dir(Path(root) / LOCAL)
    outcomes = _read_dir(Path(root) / OUTCOMES)
    excluded = sorted(str(r.get('id')) for r in lessons + outcomes if _excluded(r, tokens))
    value = {'schema_version': 1, 'kind': 'lesson-store-snapshot',
             'lessons': [r for r in lessons if not _excluded(r, tokens)],
             'outcomes': [r for r in outcomes if not _excluded(r, tokens)],
             'excluded': excluded, 'exclusion_list_sha256': digest(encode(sorted(tokens)))}
    value['snapshot_sha256'] = digest(encode(value))
    return value


def snapshot_errors(snapshot) -> list[str]:
    body = {k: v for k, v in snapshot.items() if k != 'snapshot_sha256'}
    if snapshot.get('kind') != 'lesson-store-snapshot' or snapshot.get('snapshot_sha256') != digest(encode(body)):
        return ['snapshot digest does not match its contents']
    return []


def record_store_state(rundir, loaded) -> Path:
    """Write the store mode and snapshot digest a run used to ``<rundir>/knowledge/lesson_store.json``."""
    state = {'schema_version': 1, 'kind': 'lesson-store-state', 'mode': loaded['mode'],
             'snapshot_sha256': loaded['snapshot_sha256'], 'lesson_ids': loaded['lesson_ids']}
    if 'local_snapshot_sha256' in loaded:
        state['local_snapshot_sha256'] = loaded['local_snapshot_sha256']
    return _write(Path(rundir) / 'knowledge/lesson_store.json', state)


# ----------------------------------------------------------------------------- lifecycle

def _runs_firing(lesson, tickets):
    runs = set()
    for ticket in [lesson['evidence']['ticket'] | {'origin': lesson['evidence'].get('origin')}, *tickets]:
        origin = ticket.get('origin') if isinstance(ticket, dict) else None
        if isinstance(ticket.get('facts'), dict) and not origin_errors(origin) \
                and trigger_fires(lesson['trigger'], ticket['facts']):
            runs.add(origin['run_id'])
    return sorted(runs)


def to_trial(lesson, *, tickets=(), review=None) -> dict:
    """``candidate -> trial`` at recurrence in two or more runs, or on a reviewed RCA ticket."""
    if lesson.get('status') != 'candidate':
        raise ValueError('only a candidate moves to trial')
    runs = _runs_firing(lesson, tickets)
    if len(runs) >= 2:
        row = {'to': 'trial', 'basis': 'recurrence', 'runs': runs}
    elif isinstance(review, dict) and review.get('ticket_id') == lesson['evidence']['ticket']['id'] \
            and review.get('verdict') == 'reviewed' and str(review.get('reviewer', '')).strip() \
            and _receipt_ok(review.get('receipt')):
        row = {'to': 'trial', 'basis': 'reviewed_ticket', 'review': review}
    else:
        raise ValueError('trial needs recurrence in two runs or a reviewed RCA ticket with a receipt')
    return {**lesson, 'status': 'trial', 'lifecycle': [*lesson.get('lifecycle', []), row]}


def impact_errors(impact, *, trial_runs=()) -> list[str]:
    """A held-out paired replay: two arms scored on the same declared metrics over tasks disjoint
    from the runs the lesson was learned or trialled on."""
    if not isinstance(impact, dict):
        return ['impact record required']
    errors = []
    metrics = impact.get('metric')
    if not isinstance(metrics, dict) or not metrics or any(d not in DIRECTIONS for d in metrics.values()):
        errors.append('impact.metric declares each metric with direction higher|lower')
        metrics = {}
    arms = [impact.get('arm_with'), impact.get('arm_without')]
    if not all(isinstance(a, dict) and a.get('id') and isinstance(a.get('scores'), dict) for a in arms):
        return errors + ['impact needs arm_with and arm_without with id and scores']
    if arms[0]['id'] == arms[1]['id'] or arms[0].get('snapshot_sha256') == arms[1].get('snapshot_sha256'):
        errors.append('the paired arms must differ in id and store snapshot')
    for arm in arms:
        if set(arm['scores']) != set(metrics) or not all(
                type(v) in (int, float) and math.isfinite(v) for v in arm['scores'].values()):
            errors.append('each arm scores exactly the declared metrics with finite numbers')
    tasks = impact.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        errors.append('impact needs the replayed tasks')
    elif set(map(str, tasks)) & set(trial_runs):
        errors.append('impact tasks are not held out from the runs the lesson came from')
    if impact.get('held_out') is not True or impact.get('paired') is not True:
        errors.append('impact must be a held-out paired replay')
    if not isinstance(impact.get('receipts'), list) or not impact['receipts'] or not all(map(_receipt_ok, impact['receipts'])):
        errors.append('impact needs receipts')
    return errors


def impact_verdict(impact) -> str:
    """``gain`` (better on one metric, worse on none), ``harm`` (worse on any) or ``neutral``."""
    better = worse = False
    for name, direction in impact['metric'].items():
        delta = impact['arm_with']['scores'][name] - impact['arm_without']['scores'][name]
        delta = delta if direction == 'higher' else -delta
        better, worse = better or delta > 0, worse or delta < 0
    return 'harm' if worse else 'gain' if better else 'neutral'


def reproduction_errors(lesson) -> list[str]:
    """P14: the confirming check failed before the fix, passed after it, and a clean control passed."""
    reproduction = (lesson.get('evidence') or {}).get('reproduction')
    if not isinstance(reproduction, dict):
        return ['promotion needs evidence.reproduction (pre-fix failure, post-fix pass, clean control)']
    errors = []
    for key, status in (('pre_fix', 'fail'), ('post_fix', 'pass'), ('control', 'pass')):
        step = reproduction.get(key)
        if not isinstance(step, dict) or step.get('status') != status or not _receipt_ok(step.get('receipt')) \
                or step.get('check') != lesson.get('confirming_check'):
            errors.append(f'reproduction.{key} must record the confirming check with status {status} and a receipt')
    return errors


def _trial_runs(lesson):
    runs = {r for row in lesson.get('lifecycle', []) for r in row.get('runs', [])}
    origin = (lesson.get('evidence') or {}).get('origin')
    return runs | ({origin['run_id']} if not origin_errors(origin) else set())


def promotion_errors(lesson) -> list[str]:
    """Lifecycle evidence a stored lesson's status requires (P14); used by check_knowledge."""
    if not isinstance(lesson, dict):
        return []
    status, history = lesson.get('status'), lesson.get('lifecycle', [])
    states = [row.get('to') for row in history] if isinstance(history, list) else []
    name = str(lesson.get('id', '?')) + ': '
    errors = []
    if status in ('trial', 'promoted') and 'trial' not in states:
        errors.append(f'{status} lesson has no trial record')
    if status == 'promoted':
        if 'promoted' not in states or 'trial' in states and states.index('trial') > states.index('promoted'):
            errors.append('promoted lesson has no promotion record after its trial')
        problems = impact_errors(lesson.get('impact'), trial_runs=_trial_runs(lesson))
        errors += problems or ([] if impact_verdict(lesson['impact']) == 'gain'
                               else ['promoted lesson impact shows no gain or shows harm'])
        errors += reproduction_errors(lesson)
    return [name + e for e in errors]


def promote(lesson, impact, *, excluded_origins=None) -> dict:
    """``trial -> promoted`` on a held-out paired gain with no harm; harm revokes instead."""
    if origin_match_errors(lesson, excluded_origins):
        raise ValueError('lesson promotion refused: excluded origin')
    if lesson.get('status') != 'trial':
        raise ValueError('only a trial lesson can be promoted')
    errors = impact_errors(impact, trial_runs=_trial_runs(lesson))
    if errors:
        raise ValueError('impact refused: ' + '; '.join(errors))
    verdict = impact_verdict(impact)
    if verdict == 'harm':
        return revoke(lesson, impact)
    if verdict != 'gain':
        raise ValueError('no gain on any declared metric; the lesson stays in trial')
    errors = reproduction_errors(lesson)
    if errors:
        raise ValueError('promotion refused: ' + '; '.join(errors))
    return {**lesson, 'status': 'promoted', 'impact': impact,
            'lifecycle': [*lesson.get('lifecycle', []), {'to': 'promoted', 'impact_sha256': digest(encode(impact))}]}


def revoke(lesson, impact) -> dict:
    """Negative measured impact revokes a trial or promoted lesson."""
    if impact_errors(impact, trial_runs=_trial_runs(lesson)) or impact_verdict(impact) != 'harm':
        raise ValueError('revocation needs a valid impact record showing harm')
    return {**lesson, 'status': 'revoked', 'impact': impact,
            'lifecycle': [*lesson.get('lifecycle', []), {'to': 'revoked', 'impact_sha256': digest(encode(impact))}]}


def in_scope(lesson, versions) -> bool:
    """True unless supplied current versions differ from the lesson's pinned scope."""
    if not versions:
        return True
    scope = lesson.get('scope') or {}
    tool_version = (versions.get('tools') or {}).get(scope.get('tool'))
    return (tool_version in (None, scope.get('tool_version'))
            and versions.get('ravel_version') in (None, scope.get('ravel_version')))


def apply_versions(lesson, versions) -> dict:
    """A lesson whose pinned versions are no longer current goes dormant."""
    if lesson.get('status') in ('revoked', 'dormant') or in_scope(lesson, versions):
        return lesson
    return {**lesson, 'status': 'dormant', 'lifecycle': [*lesson.get('lifecycle', []), {'to': 'dormant', 'versions': versions}]}


# ----------------------------------------------------------------------------- serving gate

def reader_class(card) -> str:
    """``reviewer``, ``investigator``, ``consult`` or ``producer`` from a role card.

    Fails closed: a card whose independence kind is missing or not a known reader kind is a reviewer.
    """
    knowledge, sees = card.get('knowledge') or {}, card.get('sees') or {}
    kind = (card.get('independence') or {}).get('kind')
    if kind in REVIEWER_KINDS or kind not in READER_KINDS or 'lessons' in knowledge.get('forbidden', []) \
            or 'lessons' in sees.get('forbidden_inputs', []):
        return 'reviewer'
    if kind == 'producer':
        return 'producer'  # a producer never reads candidates, whatever its family
    return {'investigation': 'investigator', 'consult': 'consult'}.get(card.get('family'), 'producer')


def served_lessons(lessons, *, card, facts, arm=None, versions=None) -> dict:
    """The lessons a card may receive at a node whose run facts are ``facts``, and the omissions.

    ``arm`` is ``{"side": "with"|"without", "paired_with": <arm id>}`` inside a paired replay.
    """
    reader = reader_class(card)
    paired = isinstance(arm, dict) and arm.get('side') == 'with' and bool(arm.get('paired_with'))
    origins = _origins(None)
    lessons = [r for r in lessons if not origin_match_errors(r, origins)]
    served, promoted, omitted = [], [], []
    for lesson in sorted(lessons, key=lambda r: str(r.get('id'))):
        if not isinstance(lesson, dict) or lesson_errors(lesson) or promotion_errors(lesson):
            omitted.append({'id': str(lesson.get('id') if isinstance(lesson, dict) else '?'), 'reason': 'withheld'}); continue
        if not trigger_fires(lesson['trigger'], facts):
            continue
        status = lesson['status']
        if reader == 'reviewer':
            reason = 'forbidden'
        elif status in ('revoked', 'dormant') or not in_scope(lesson, versions):
            reason = 'withheld'
        elif status == 'candidate':
            consult = reader == 'consult' and card.get('id') == 'consult-' + str(lesson['scope']['tool'])
            reason = None if reader == 'investigator' or consult else 'withheld'
        elif status == 'trial':
            reason = None if paired else 'withheld'
        else:
            promoted.append(lesson); continue
        if reason:
            omitted.append({'id': lesson['id'], 'reason': reason})
        else:
            served.append(lesson)
    served += promoted[:MAX_PROMOTED_PER_NODE]
    omitted += [{'id': r['id'], 'reason': 'procedural_cap'} for r in promoted[MAX_PROMOTED_PER_NODE:]]
    return {'reader': reader, 'served': served, 'omitted': omitted}


def bundle_items(lessons, *, card, facts, arm=None, versions=None) -> dict:
    """Bundle-index ``items`` and ``omitted`` rows for the lessons a card may read at a node.

    The bundle materializer (knowledge binding) writes ``records[path]`` at each item's ``path``.
    """
    gate = served_lessons(lessons, card=card, facts=facts, arm=arm, versions=versions)
    items = [{'id': r['id'], 'kind': 'lesson', 'path': 'lessons/' + _file(r['id']),
              'sha256': digest(encode(r)), 'reason': 'derive:lessons_for_failure',
              'tokens': max(1, len(encode(r)) // 4)} for r in gate['served']]
    return {'items': items, 'omitted': gate['omitted'],
            'records': {item['path']: r for item, r in zip(items, gate['served'])}}
