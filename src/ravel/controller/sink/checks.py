"""The sink's checks: every delivery obligation evaluated from controller evidence and the actual bytes.

Each check yields a ledger status with evidence for one obligation row (per delivered artifact or
per run), the labels the sink renders, and refusals. A refusal withholds the accepted label; its
consequence (``diagnostic`` for a row nobody may waive, ``qualified`` for a waivable one) decides
which label the delivery carries instead. Nothing a worker wrote decides a check: worker lists,
receipts, verdict claims and notices inside artifacts are ignored or compared against the store.
"""
from __future__ import annotations

from pathlib import Path
import json
import re

from . import common, numbers
from .common import (ENGAGEMENT_UNKNOWN, GOVERNANCE_UNKNOWN, HOST_FINDINGS, NOT_GOVERNED, REVIEW_INCOMPLETE, UNCONFINED,
                     REVIEW_UNSANDBOXED,
                     UNVERIFIED, USAGE_UNKNOWN)

RESULT_KINDS = ('exclusion', 'limit', 'estimate', 'measurement', 'fit', 'calculation', 'value', 'prediction',
                'scan', 'contour', 'significance', 'interval', 'cross_section', 'yield')
CERTIFIED = ('certified', 'pass', 'passed', 'accepted', 'ok')
UNCERTIFIED_MODES = ('delphes-custom-uncertified', 'particle-level', 'parton-level', 'custom', 'uncertified', 'proxy',
                     'custom-fast-response')
BOUND_STATUSES = ('bound', 'upper_bound', 'lower_bound', 'uncrossed', 'endpoint', 'unresolved', 'at_cap', 'cap',
                  'not_crossed', 'bracket_endpoint')
RESOLVED_STATUSES = ('resolved', 'crossing', 'crossed', 'converged', 'root', 'ok')
CLEAN_VERDICTS = ('accept', 'accepted', 'pass', 'passed', 'clean', 'ok', 'approved')
OPEN_DEFECT = ('open', 'unresolved', 'pending')
UNCERTIFIED_FIELDS = ('fidelity', 'explanation', 'certifiable_route', 'flag')
STATISTIC_KEYS = ('statistic', 'test_statistic')
WAIVER_LABELS = ('physicist_terminal_response', 'operator_command')
FINAL = 'final_review'


class Findings:
    """Row statuses, labels and refusals of one sink evaluation."""

    def __init__(self):
        self.rows = {}
        self.labels = []
        self.refusals = []
        self.notes = []
        self.documents = {}
        self.defaults = []
        self.credits = []
        self.rounds = {}
        self.statistic = None
        self.claims = []
        self.review_findings = []

    def _put(self, row, target, status, evidence):
        evidence = {k: v for k, v in evidence.items() if v is not None}
        self.rows[(row, target)] = {'row': row, 'artifact': target, 'status': status, 'evidence': evidence}

    def satisfied(self, row, target=None, *, mechanism, **evidence):
        self._put(row, target, 'satisfied', {'mechanism': mechanism, **evidence})

    def violated(self, row, target, reason, *, label=None, refuse=None, **evidence):
        self._put(row, target, 'violated', {'reason': reason[:2000], 'label': label, **evidence})
        if label:
            self.label(label, row=row, artifact=target, text=reason)
        if refuse:
            self.refuse(refuse, row=row, artifact=target, message=reason)

    def waived(self, row, target, authority, reason):
        self._put(row, target, 'waived', {'authority': authority, 'reason': reason[:2000]})
        self.label(f'WAIVED {row}', row=row, artifact=target, text=f'{reason} (authority {authority})')

    def not_applicable(self, row, target, reason, **evidence):
        self._put(row, target, 'not_applicable', {'reason': reason, **evidence})

    def label(self, label, *, row=None, artifact=None, text=None):
        entry = {'label': label, 'row': row, 'artifact': artifact, 'text': (text or '')[:1000]}
        if entry not in self.labels:
            self.labels.append(entry)

    def refuse(self, consequence, *, code=None, row=None, artifact=None, message='', typed=None):
        entry = {'code': code or (row or 'sink').lower(), 'row': row, 'artifact': artifact,
                 'consequence': consequence, 'message': message[:2000]}
        if typed is not None:
            entry['typed'] = typed  # a peer's typed problem row, kept whole beside its rendered message
        if entry not in self.refusals:
            self.refusals.append(entry)


# ---- helpers ------------------------------------------------------------------------------------

def _suffix(path):
    name = str(path).lower()
    for compound in ('.tar.gz', '.tar.bz2', '.tar.xz'):
        if name.endswith(compound):
            return compound
    return Path(name).suffix


def kind_of(path):
    suffix = _suffix(path)
    if suffix in numbers.DOCUMENTS:
        return 'document'
    if suffix in numbers.FIGURES:
        return 'figure'
    return 'machine'


def _objects(value, depth=0):
    """Every JSON object inside ``value`` (depth-bounded)."""
    if depth > 64:
        return
    if type(value) is dict:
        yield value
        for item in value.values():
            yield from _objects(item, depth + 1)
    elif type(value) is list:
        for item in value:
            yield from _objects(item, depth + 1)


def _load_json(path):
    try:
        if Path(path).stat().st_size > common.TEXT_LIMIT:
            return None
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError, UnicodeDecodeError):
        return None


QUALIFIER_WORDS = re.compile(r'\b(?:upper|limits?|exclusion|observed|expected|asymptotic)\b')


def _norm(text):
    text = str(text).lower().replace('\u03c7', 'chi').replace('\u221a', 'sqrt').replace('\u00b2', '2')
    return re.sub(r'[^a-z0-9]+', '', QUALIFIER_WORDS.sub(' ', text))


def statistic_matches(pinned, delivered, *, level_optional=False):
    """Whether ``delivered`` states the pinned statistic: equal after normalisation, never by containment.

    Qualifier words (upper, limit, observed, expected, ...) name no statistic and are ignored. A
    statistic that contains or is contained in the pinned one differs from it (CLs+b is not CLs;
    S/sqrt(B) is not S/sqrt(B + dB^2)). With ``level_optional`` (the exclusion default, not a
    prescribed statistic) a delivered statistic that states no level matches the pinned one.
    """
    a, b = _norm(pinned), _norm(delivered)
    if not a or not b:
        return False
    if a == b:
        return True
    return level_optional and not re.search(r'\d', b) and re.sub(r'^\d+', '', a) == b


def pinned_statistic(reading):
    """``(statistic, prescribed)`` from the pinned reading: a prescribed statistic, else the exclusion default."""
    reading = reading if type(reading) is dict else {}
    for row in reading.get('constraints') or ():
        if type(row) is dict and row.get('type') == 'prescribed_statistic':
            value = (row.get('value') or {}).get('statistic')
            if type(value) is str and value.strip():
                return value.strip(), True
    claims = {d.get('claim_kind') for d in reading.get('deliverables') or () if type(d) is dict}
    if 'exclusion' in claims:
        return '95% CLs', False
    return None, False


def review_rounds(ev, plan_sha):
    """The latest review round per purpose for the current plan (``review`` records the graph wrote)."""
    found = {}
    for row in common.records(ev['store'], 'review'):
        if row.get('plan_sha256') == plan_sha and type(row.get('seats')) is dict:
            found[row.get('purpose')] = row
    return found


def credit_rows(ev):
    """Seat credits of the governed steps: ``(seats, decisions)``.

    ``seats`` are the review seats a producing step derived (latest attempt of each step, seat
    and role); a review step's own decision (``own``) is a ``decisions`` row: it labels the seat's
    model-family relation and evidence boundary, while the controller's review rounds say which
    plan, final and attack seats were credited.
    """
    seats, decisions = {}, []
    for record in ev['credits']:
        own = record.get('own') if type(record.get('own')) is dict else None
        if own is not None:
            decision = own.get('decision') if type(own.get('decision')) is dict else {}
            decisions.append({'record_id': record.get('_id'), 'step_id': record.get('step_id'),
                              'attempt': record.get('attempt'), 'seat': 'own', 'role': None,
                              'credited': bool(own.get('credited')), 'verdict': own.get('verdict'),
                              # The decision holds the observed relation; the step's own field may only say unknown.
                              'family_relation': decision.get('family_relation') or own.get('family_relation'),
                              'label': decision.get('label'), 'boundary': decision.get('evidence_boundary'),
                              'reasons': []})
        for seat in record.get('seats') or ():
            if type(seat) is not dict:
                continue
            decision = seat.get('decision') if type(seat.get('decision')) is dict else {}
            row = {'record_id': record.get('_id'), 'step_id': record.get('step_id'), 'attempt': record.get('attempt'),
                   'seat': seat.get('seat'), 'role': seat.get('role'), 'credited': bool(seat.get('credited')),
                   'verdict': seat.get('verdict'),
                   'family_relation': decision.get('family_relation') or seat.get('family_relation'),
                   'label': decision.get('label'), 'boundary': decision.get('evidence_boundary'),
                   'reasons': list(seat.get('reasons') or [])}
            key = (row['step_id'], row['seat'], row['role'])
            if key not in seats or (row['attempt'] or 0) >= (seats[key]['attempt'] or 0):
                seats[key] = row
    return list(seats.values()), decisions


def family_text(relation, label):
    if type(label) is str and label.strip():
        return label
    independence = common.module('independence')
    if independence is not None and hasattr(independence, 'family_label'):
        return independence.family_label(relation)
    return {'same': 'separate session, same model family', 'different': 'separate session, different model family'
            }.get(relation, 'separate session, model family unknown')


def _waiver(ev, row, key):
    """An authority record that may waive ``row``: a physicist or operator answer naming it."""
    for record in common.records(ev['store'], 'authority'):
        subject = record.get('subject') if type(record.get('subject')) is dict else {}
        named = list(subject.get('obligations') or []) if type(subject.get('obligations')) is list else []
        if row not in named and key not in named:
            continue
        if record.get('label') in WAIVER_LABELS and record.get('authorizes_effects') is not False \
                and record.get('kind') not in ('revoke', 'stop', 'pause', 'resume', 'final'):
            return record.get('uid') or record.get('_id')
    return None


# ---- the evaluation -------------------------------------------------------------------------------

def references(ev, classification, run_dir, hashes, plan):
    refs = numbers.References()
    seen = set()

    def machine(artifact):
        if artifact in seen:
            return
        seen.add(artifact)
        record = ev['custody'].get(artifact)
        if record is None or record.get('status') != 'accepted' or type(record.get('destination')) is not str:
            return
        destination = record['destination']
        if hashes.of(destination) != record.get('sha256'):
            return
        if kind_of(destination) == 'machine' and numbers.add_machine(run_dir / destination, refs, common.TEXT_LIMIT * 4):
            refs.sources += 1
        for parent in record.get('inputs') or ():
            machine(parent)

    for row in classification['declared']:
        if row['status'] == 'accepted':
            machine(row['artifact'])
    intake = ev['intake']
    numbers.add_text_numbers(intake.get('prompt'), refs)
    for document in (intake.get('reading'), intake.get('contract'), (plan or {}).get('parameters')):
        numbers._walk_json(document, refs)
    return refs.freeze()


def _producer_journal(ev, record):
    """The store journal of the dispatch or launch that produced an artifact, or the reason it is absent."""
    producer = record.get('producer') if type(record.get('producer')) is dict else {}
    kind = producer.get('kind')
    if kind == 'worker':
        dispatched = [d for d in ev['dispatches'] if d.get('node_id') == producer.get('node_id')
                      and d.get('attempt') == producer.get('attempt')]
        observed = [o for o in ev['observations'] if o.get('receipt_sha256') == producer.get('receipt_sha256')]
        if dispatched and observed:
            return {'dispatch': dispatched[-1].get('_id'), 'observation': observed[-1].get('_id')}, None
        return None, 'the producing worker session has no dispatch and observation in the controller store'
    if kind == 'launch':
        found = [l for l in ev['launches'] if l['id'] == producer.get('journal_id') and l['finished'] is not None]
        if found and found[-1]['exit_status'] == 0:
            return {'launch': found[-1]['id']}, None
        return None, 'the producing launch has no finished, successful journal in the controller store'
    return None, f'the producer {kind!r} is neither a governed worker nor a governed launch'


def evaluate(store, ev, plan, classification, hashes, *, relative_rounding=None):
    """Run every check; returns ``Findings``."""
    ev.setdefault('store', store)
    findings = Findings()
    run_dir = Path(ev['run_dir'])
    rows = classification['declared']
    delivered = [r for r in rows if r['status'] == 'accepted']
    refs = references(ev, classification, run_dir, hashes, plan)
    findings.notes.append({'reference_values': len(refs.values), 'reference_sources': refs.sources,
                           'truncated': refs.truncated})
    plan_sha = (plan or {}).get('sha256')
    rounds = review_rounds(ev, plan_sha)
    seat_credits, decisions = credit_rows(ev)
    credits = seat_credits + decisions
    final_round = rounds.get('final')
    final_seats = (final_round or {}).get('seats') or {}
    final_open = [s for s, v in final_seats.items() if type(v) is dict and v.get('verdict') not in CLEAN_VERDICTS]
    final_credit = next((c['record_id'] for c in decisions if c['step_id'] == FINAL and c['credited']), None) \
        if final_seats and all((v or {}).get('credited') for v in final_seats.values()) else None
    statistic, prescribed = pinned_statistic(ev['intake'].get('reading'))
    fidelity = fidelity_context(ev, plan)
    defaults = adopted_defaults(ev)

    # ---- run-level non-row refusals ----
    for problem in ev['plan']['problems']:
        findings.refuse('diagnostic', code='plan_integrity', message=problem)
    for problem in ev['binding'] or ([] if ev['binding'] is not None else ['the run binding is unknown']):
        findings.refuse('diagnostic', code='run_binding', message=problem)
    for problem in ev['store_problems'] or ([] if ev['store_problems'] is not None else ['the store chain is unknown']):
        findings.refuse('diagnostic', code='store_chain', message=problem)
    if ev['request'] is None:
        findings.refuse('diagnostic', code='request_missing',
                        message='the controller store holds no request record: the run did not pass controller intake')
    identity = ev['identity']
    if identity.get('governed') is not True:
        text = '; '.join(identity.get('problems') or ['the controller code identity is not governed'])
        findings.label(NOT_GOVERNED, text=text)
        findings.refuse('diagnostic', code='not_governed', message=text)
    _governance(findings, ev)
    _output_contract(findings, ev)
    for row in ev.get('review_fallbacks') or ():
        # The operator's fallback ran a review seat without the OS worker sandbox: labelled, and the delivery stays
        # qualified; it is machine review whose confinement was the CLI's own policy, never human review.
        findings.label(REVIEW_UNSANDBOXED, text=f"review seat {row.get('seat')} of step {row.get('step_id')} ran "
                       'without the OS worker sandbox under the operator\'s configured fallback')
        findings.refuse('diagnostic', code='review_unsandboxed',
                        message=f"step {row.get('step_id')}: review without the OS worker sandbox (operator fallback; "
                                f"not enforced: {', '.join(row.get('not_enforced') or [])})")
    for launch in ev['launches']:
        if launch['kind'] == 'unconfined':
            findings.label(UNCONFINED, text=f"launch {launch['id']} of step {launch['step_id']} ran without a sandbox")
            findings.refuse('diagnostic', code='unconfined', message=f"step {launch['step_id']} ran unconfined")
        elif launch['kind'] == 'unknown' and launch['finished'] is not None:
            findings.refuse('diagnostic', code='confinement_unknown',
                            message=f"launch {launch['id']} records no confinement backend")
        elif launch['kind'] == 'unqualified':
            findings.refuse('diagnostic', code='confinement_unqualified',
                            message=f"launch {launch['id']} of step {launch['step_id']} names the backend "
                                    f"{launch['backend']} without its confirmed denial-probe qualification")
        if launch['errors']:
            findings.refuse('diagnostic', code='confinement_finish',
                            message=f"launch {launch['id']}: " + '; '.join(map(str, launch['errors'][:5])))
    for observation in ev['observations']:
        if observation.get('status') == 'ok' and not observation.get('tool_inventory'):
            findings.refuse('diagnostic', code='worker_inventory_missing',
                            message=f"worker session of step {observation.get('step_id')} has no observed tool inventory")
    if not ev['authority'].get('mode'):
        findings.refuse('diagnostic', code='authority_missing',
                        message='no frozen operating mode record is in the store')
    records_ = ev['authority'].get('records')
    if records_ is not None:
        if not (ev['authority'].get('current') or {}).get('approve_plan'):
            findings.refuse('diagnostic', code='authority_missing',
                            message='no CHECK-IN 1 authority record that authorizes the plan is in the store')
        if not (ev['authority'].get('current') or {}).get('final'):
            findings.refuse('diagnostic', code='authority_missing',
                            message='no CHECK-IN 3 acceptance (final authority record) is in the store')
    else:
        findings.refuse('diagnostic', code='authority_unknown', message='the authority records cannot be read')
    _engagement(findings, ev)
    from .receipts import unacknowledged, undelivered_sessions
    for row in unacknowledged(ev):
        findings.refuse('diagnostic', code='instructions_unacknowledged',
                        message=f"step {row['step_id']} (seat {row['seat'] or 'producer'}, attempt {row['attempt']}) "
                                'did not acknowledge every delivered instruction unit')
    for row in undelivered_sessions(ev):
        findings.refuse('diagnostic', code='instructions_undelivered',
                        message=f"the worker session of step {row['step_id']} (seat {row['seat'] or 'producer'}, "
                                f"attempt {row['attempt']}) has no instruction delivery receipt")
    for submission in ev['wms']:
        findings.label('remote confinement: facility policy',
                       text=f"facility job of launch {submission.get('launch_id')} runs under the facility's policy")
    # Review: every seat the governed steps derived is credited; the final round exists and is clean.
    missing = [c for c in seat_credits if not c['credited']]
    same_user = [c for c in credits if c['boundary'] == 'same_user_state']
    for purpose, row in sorted(rounds.items()):
        for seat, verdict in sorted((row.get('seats') or {}).items()):
            if not (verdict or {}).get('credited'):
                missing.append({'step_id': f'{purpose} review', 'seat': seat, 'role': seat,
                                'reasons': [f"{(verdict or {}).get('status') or 'not credited'}"]})
    if final_round is None:
        missing.append({'step_id': FINAL, 'seat': None, 'role': None, 'reasons': ['no final review round']})
    elif not final_seats:
        missing.append({'step_id': FINAL, 'seat': None, 'role': None, 'reasons': ['the final round has no seats']})
    if missing:
        text = '; '.join(f"{m['step_id']}/{m.get('role') or m.get('seat') or '-'}: "
                         + (', '.join(m.get('reasons') or []) or 'not credited') for m in missing[:10])
        findings.label(REVIEW_INCOMPLETE, text=text)
        findings.refuse('diagnostic', code='review_incomplete', message=text)
    if same_user:
        findings.label(NOT_GOVERNED, text='review evidence lies in same-user state outside the controller store')
        findings.refuse('diagnostic', code='review_evidence_boundary',
                        message='a review credit rests on same-user state, not on the controller store')
    relations = {}
    for c in credits:
        if c['credited'] and (c['seat'] != 'own' or c['family_relation'] or c['label']):
            text = family_text(c['family_relation'], c['label'])
            relations[text] = relations.get(text, 0) + 1
    for text, count in sorted(relations.items()):
        findings.label(f'REVIEW: {text}', text=f'{count} credited seat(s)')
    unknown = sorted(d for d, v in ev['budget']['dimensions'].items() if v['unknown_attempts'])
    if unknown:
        findings.label(USAGE_UNKNOWN, text='not measured for every attempt: ' + ', '.join(unknown))

    # ---- the route packages' delivery checks (manuscript build, staged ML) ----
    route_checks(findings, ev, plan)

    # ---- per-artifact rows ----
    documents = {}
    for row in rows:
        artifact = row['artifact']
        path = run_dir / row['destination']
        kind = kind_of(row['destination'])
        ok = row['status'] == 'accepted'
        reason = '; '.join(row['reasons']) or row['status']
        # C27: exact declared outputs (population equality); D07: the sink's own inventory.
        if ok:
            findings.satisfied('C27', artifact, mechanism='sink.population', artifact=artifact, sha256=row['sha256'])
        else:
            findings.violated('C27', artifact, f'declared output not deliverable: {reason}', refuse='diagnostic')
        findings.satisfied('D07', artifact, mechanism='sink.inventory', sha256=row['sha256'],
                           record={'status': row['status']})
        # D08: diagnostic promotion by copy, rename or nesting; a diagnostic ancestor.
        if row['status'] == 'diagnostic_promotion' or (row['status'] == 'lineage'
                                                        and any('diagnostic' in r for r in row['reasons'])):
            findings.violated('D08', artifact, reason, refuse='diagnostic')
        else:
            findings.satisfied('D08', artifact, mechanism='sink.custody_lineage', artifact=artifact)
        # D06: the sink recomputes the receipt and renders every notice; a worker-written receipt or sink
        # notice inside a delivered artifact is refused rather than delivered beside the real one.
        forged = _forged_notice(path, kind) if ok else None
        if forged:
            findings.violated('D06', artifact, forged, refuse='diagnostic')
        else:
            findings.satisfied('D06', artifact, mechanism='sink.receipt', artifact=artifact)
        # D05: completion is derived from the ledger's conservation entries, never from prose.
        findings.satisfied('D05', artifact, mechanism='sink.completion_from_ledger', artifact=artifact)
        # C22: adopted delegated defaults are rendered from the store.
        findings.satisfied('C22', artifact, mechanism='sink.render.defaults', record={'defaults': len(defaults)})
        document = _load_json(path) if ok and _suffix(path) == '.json' else None
        # D01 / E20: numbers trace to accepted artifacts.
        if not ok:
            for row_id in ('D01', 'E20', 'D02'):
                findings.not_applicable(row_id, artifact, f'not delivered: {reason}')
        elif kind == 'document':
            try:
                text = path.read_text(encoding='utf-8', errors='replace') if path.stat().st_size <= common.TEXT_LIMIT \
                    else None
            except OSError:
                text = None
            if text is None:
                findings.violated('D01', artifact, 'the document is too large or unreadable for number tracing',
                                  label='NUMBERS NOT TRACED', refuse='diagnostic')
                findings.violated('E20', artifact, 'the document is too large or unreadable for number tracing',
                                  label='NUMBERS NOT TRACED', refuse='diagnostic')
            else:
                traced = numbers.trace(text, _suffix(path), refs, relative_rounding)
                documents[artifact] = traced
                if traced['untraced_table_count']:
                    shown = ', '.join(f"{n['text']} (line {n['line']})" for n in traced['untraced_table'][:5])
                    message = (f"{traced['untraced_table_count']} table number(s) do not trace to an accepted "
                               f'artifact: {shown}')
                    findings.violated('D01', artifact, message, label='REFUSED: UNTRACED TABLE NUMBER',
                                      refuse='diagnostic', record=traced['untraced_table'][:20])
                    findings.violated('E20', artifact, message, label='REFUSED: UNTRACED TABLE NUMBER',
                                      refuse='diagnostic')
                else:
                    findings.satisfied('E20', artifact, mechanism='sink.numbers.tables',
                                       record={'table_numbers': traced['table_numbers']})
                    if traced['unmatched_prose_count']:
                        shown = ', '.join(f"{n['text']} (line {n['line']})" for n in traced['unmatched_prose'][:8])
                        findings.violated('D01', artifact,
                                          f"{traced['unmatched_prose_count']} number(s) in prose match no accepted "
                                          f'artifact within their rounding: {shown}', label=UNVERIFIED,
                                          record=traced['unmatched_prose'][:50])
                    else:
                        findings.satisfied('D01', artifact, mechanism='sink.numbers',
                                           record={'table_numbers': traced['table_numbers'],
                                                   'prose_numbers': traced['prose_numbers']})
        elif kind == 'figure':
            step = next((s for s in (plan or {}).get('steps') or () if s.get('id') == row['step']), {})
            traced = bool((row['custody'] or {}).get('inputs')) or bool(step.get('inputs'))
            if traced:
                findings.satisfied('D01', artifact, mechanism='sink.figure_lineage',
                                   record={'inputs': (row['custody'] or {}).get('inputs') or step.get('inputs')})
                findings.satisfied('E20', artifact, mechanism='sink.figure_lineage')
            else:
                message = 'the figure was rendered from no accepted artifact or pinned input'
                findings.violated('D01', artifact, message, label='REFUSED: FIGURE VALUES UNTRACED', refuse='diagnostic')
                findings.violated('E20', artifact, message, label='REFUSED: FIGURE VALUES UNTRACED', refuse='diagnostic')
        else:
            findings.satisfied('D01', artifact, mechanism='sink.numbers.source', artifact=artifact)
            findings.satisfied('E20', artifact, mechanism='sink.numbers.source', artifact=artifact)
        # D02: statistic and fidelity equal the intake pins; discovery language is labelled.
        if ok:
            _statistic(findings, ev, row, document, statistic, prescribed, fidelity, documents.get(artifact))
            _statistics_validity(findings, artifact, document)
        # D03: figure panels and fidelity are reviewed (an R row: satisfied only with a credit).
        figure_credit = next((c['record_id'] for c in seat_credits if c['step_id'] == row['step'] and c['credited']
                              and 'figure' in str(c.get('role') or '')), None) or final_credit
        if kind == 'figure' and ok:
            panels = _panel_holes(ev, plan, row, run_dir, hashes)
            if panels:
                findings.violated('D03', artifact, 'requested figure panels are missing: ' + ', '.join(panels),
                                  refuse='diagnostic')
            elif figure_credit:
                findings.satisfied('D03', artifact, mechanism='sink.figure_review', credit=figure_credit)
            else:
                findings.refuse('diagnostic', code='figure_review_missing', row='D03', artifact=artifact,
                                message='no credited review seat covers this figure')
        elif final_credit:
            findings.not_applicable('D03', artifact, 'not a delivered figure', credit=final_credit)
        else:
            findings.refuse('diagnostic', code='review_credit_missing', row='D03', artifact=artifact,
                            message='no credited final review covers the delivered population')
        # E25: open defect notes; E26: presented verdicts equal the recorded ones.
        defects = _open_defects(document)
        if final_open:
            findings.violated('E25', artifact, 'the final review left open findings: ' + ', '.join(final_open),
                              refuse='diagnostic')
        elif defects:
            findings.violated('E25', artifact, 'the artifact carries open defect notes: ' + ', '.join(defects[:5]),
                              refuse='diagnostic')
        else:
            findings.satisfied('E25', artifact, mechanism='sink.defects', artifact=artifact)
        claimed = _claimed_verdict(document)
        recorded = sorted({str((v or {}).get('verdict')) for v in final_seats.values()}) if final_seats else []
        if claimed is not None and claimed.lower() in CLEAN_VERDICTS and (final_open or not final_seats):
            findings.violated('E26', artifact, f'the artifact presents the verdict {claimed!r}; the recorded final '
                              f'verdicts are {recorded or "absent"}', refuse='diagnostic')
        else:
            findings.satisfied('E26', artifact, mechanism='sink.render.verdicts', record={'recorded': recorded})

    # ---- run-level rows ----
    refused_attempts = {(r.get('step_id'), r.get('attempt')) for r in ev['refusals']}
    fallback = [r['artifact'] for r in delivered
                if (r['step'], (r['custody'] or {}).get('attempt')) in refused_attempts]
    if fallback:
        findings.violated('A12', None, 'results of a refused attempt are offered for delivery: ' + ', '.join(fallback),
                          refuse='diagnostic')
    else:
        findings.satisfied('A12', None, mechanism='sink.custody', record={'refusals': len(ev['refusals'])})
    unjournaled = []
    journals = {}
    for row in delivered:
        record = ev['custody'].get(row['artifact']) or {}
        journal, problem = _producer_journal(ev, record)
        if problem:
            unjournaled.append(f"{row['artifact']}: {problem}")
        else:
            journals[row['artifact']] = journal
    if unjournaled:
        findings.violated('T10', None, '; '.join(unjournaled[:10]), refuse='diagnostic')
    else:
        findings.satisfied('T10', None, mechanism='sink.custody_origin', record=journals)
    findings.satisfied('B04', None, mechanism='sink.costs', record={'unknown': unknown})
    _scan_run_rows(findings, ev, delivered, run_dir)
    if ('E27', None) not in findings.rows:
        findings.satisfied('E27', None, mechanism='sink.environment',
                           record={'launches': len(ev['launches']), 'identity': (identity.get('live') or {}).get('digest')})
    findings.documents = documents
    findings.defaults = defaults
    findings.credits = credits
    findings.rounds = rounds
    findings.statistic = {'pinned': statistic, 'prescribed': prescribed, 'fidelity': {
        'requested': fidelity['wanted'], 'planned': fidelity['planned'], 'checked': fidelity['available']}}
    return findings


OUTPUT_CONTRACT_LABEL = 'OUTPUT CONTRACT NOT MET'


def _output_contract(findings, ev):
    """Observe the deliverables the request declared, from their real bytes, immediately before acceptance.

    The rows (paths, formats, keys, exclusive locations and their intake baselines) come from the
    contract intake pinned in the store; nothing a worker wrote widens them. Every violation is
    named and withholds acceptance; a qualified ending carries the same labelled observation.
    Conformance is mechanical, never a judgment of scientific content.
    """
    from ...workflow import output_contract
    contract = (ev.get('intake') or {}).get('contract')
    rows = output_contract.rows(contract) if type(contract) is dict else []
    if not rows:
        return
    report = output_contract.check(rows)
    findings.notes.append({'output_contract': {
        'declared': report['declared'], 'satisfied': report['satisfied'], 'items': report['items'],
        'violations': report['violations'], 'semantic_content_verified': report['semantic_content_verified']}})
    for violation in report['violations']:
        text = f"{violation['obligation_id']}: {violation['message']}"
        findings.label(OUTPUT_CONTRACT_LABEL, artifact=violation['path'], text=text)
        findings.refuse('qualified', code='output_contract_' + violation['code'], artifact=violation['path'],
                        message=text)


PROBLEM_SCOPE = ('step', 'stage', 'deliverable')
PROBLEM_TEXT = ('message', 'detail')


def _problem_text(problem):
    """One line for a route check's problem row (``{code, step, stage, deliverable, message, detail, ...}``).

    Nothing a route reported is dropped: the code, the scope fields, every other field as
    ``name value``, then the message and the detail.
    """
    if type(problem) is not dict:
        return str(problem)[:1000]
    parts = [str(problem.get('code') or 'refused')]
    parts += [f'{key} {problem[key]}' for key in PROBLEM_SCOPE if problem.get(key)]
    parts += [f'{key} {problem[key]}' for key in sorted(problem, key=str)
              if key not in ('code', *PROBLEM_SCOPE, *PROBLEM_TEXT) and problem[key] not in (None, '', [], {})]
    parts += [str(problem[key]) for key in PROBLEM_TEXT if problem.get(key)]
    return (': '.join([parts[0], ', '.join(parts[1:])]) if len(parts) > 1 else parts[0])[:1000]


def route_checks(findings, ev, plan):
    """Every installed route package's delivery check over the store; each problem withholds acceptance.

    The checks are universal (a manuscript document or a typed training stage may sit in any
    plan), so each installed one runs on every delivery. A plan of a route whose check is not
    installed is refused: the absent check is not a pass.
    """
    if type(plan) is not dict:
        return  # the plan problems already refuse
    route = plan.get('route')
    route_id = route.get('id') if type(route) is dict else route
    for name, interface, routes in common.ROUTE_CHECKS:
        module = common.module(interface)
        check = getattr(module, 'delivery_errors_from_store', None) if module is not None else None
        if not callable(check):
            if route_id in routes:
                findings.refuse('diagnostic', code=name, message=f'the {route_id} route check is not installed; '
                                                                 'its deliverables cannot be checked')
            continue
        try:
            problems = check(ev['store'], plan)
            if type(problems) not in (list, tuple):
                raise TypeError(f'the check returned {type(problems).__name__}, not a list of problems')
            for problem in problems:
                findings.refuse('diagnostic', code=name, message=_problem_text(problem),
                                typed=common.plain(problem) if type(problem) is dict else None)
        except Exception as exc:  # a failing route check is a refusal, never a pass
            findings.refuse('diagnostic', code=name, message=f'{name} check failed: {type(exc).__name__}: {exc}')


def _governance(findings, ev):
    """The host governance label of the run directory, rendered with its reasons in every notice.

    ``NOT GOVERNED`` (the controller does not own the directory, or another run does) and an
    unknown governance label withhold acceptance; a controller-owned run's host findings and
    recorded host events are rendered as notices, since the controller boundary, not the host, holds.
    """
    governance = ev['governance']
    reasons = '; '.join(governance['reasons'])
    if not governance['available']:
        findings.label(GOVERNANCE_UNKNOWN, text=governance['error'] or 'host governance is unknown')
        findings.refuse('diagnostic', code='host_governance_unknown', message=governance['error'] or '')
    elif governance['label']:
        findings.label(governance['label'], text=reasons or 'host governance labels this run')
        findings.refuse('diagnostic', code='not_governed',
                        message=f"{governance['label']}: {reasons or 'host governance labels this run'}")
    elif governance['controller_run'] != ev['run_id']:
        text = (f"host governance finds the run directory owned by {governance['controller_run']!r}, "
                f"not by this run {ev['run_id']!r}")
        findings.label(NOT_GOVERNED, text=text)
        findings.refuse('diagnostic', code='not_governed', message=text)
    elif reasons:
        findings.label(HOST_FINDINGS, text=reasons)


def _engagement(findings, ev):
    """The engagement policy's labels, and its verdict on accepted delivery (EG08: no verdict, no acceptance)."""
    engagement = ev['engagement']
    declaration = (((ev.get('plan') or {}).get('plan') or {}).get('engagement') or {}).get('seat_plan', {}).get('scan_review')
    for population in (declaration or {}).get('populations', []):
        findings.label('SCAN REVIEW POPULATION', text=f"{population['id']}: "
                       f"{len(population['review_point_ids'])} of {len(population['point_ids'])} points; "
                       f"reviewed: {', '.join(population['review_point_ids'])}; "
                       f"population: {', '.join(population['point_ids'])}")
    if not engagement['available']:
        findings.label(ENGAGEMENT_UNKNOWN, text=engagement['error'] or 'the engagement policy is unknown')
        findings.refuse('diagnostic', code='engagement_unknown', message=engagement['error'] or '')
        return
    for label in engagement['labels']:
        findings.label(label, text=f"engagement envelope {engagement['envelope_status']}")
    for reason in engagement.get('refusal_reasons') or ():
        findings.refuse('diagnostic', code=reason['code'], message=reason['message'])
    if not engagement['accepted_allowed']:
        findings.refuse('diagnostic', code='engagement',
                        message=f"the engagement envelope ({engagement['envelope_status']}) allows no accepted "
                                'delivery: ' + (', '.join(engagement['labels']) or 'no current delivery check'))
    _engagement_rows(findings, engagement)


def _engagement_rows(findings, engagement):
    """EG08-EG11 from the engagement section this receipt renders. EG11: the receipt carries the section, read from
    the store (never from a worker). EG08 and EG10: the delivery-stage envelope check ran its floors and ceiling on the
    run's usage census (a breach or overspend is labelled above, and acceptance is refused). EG09: the broker
    reconciliation where an independent count exists; without one it does not apply, and acceptance still needs it.
    Without a delivery check EG08-EG10 stay pending."""
    if not engagement['available']:
        findings.violated('EG11', None, engagement['error'] or 'the engagement section is unknown',
                          label=ENGAGEMENT_UNKNOWN)
        return
    findings.satisfied('EG11', None, mechanism='sink.render.engagement',
                       record={'decision_id': engagement.get('decision_id'), 'tier': engagement.get('tier')})
    checks = [c for c in engagement.get('envelope_checks') or () if type(c) is dict]
    delivered = [c for c in checks if c.get('stage') == 'deliver']
    if not delivered:
        return
    last = delivered[-1]
    evidence = {'record': last.get('record_id'), 'status': last.get('status'),
                'wave_checks': sum(c.get('stage') == 'wave' for c in checks)}
    findings.satisfied('EG08', None, mechanism='engagement.envelope.floors', **evidence)
    findings.satisfied('EG10', None, mechanism='engagement.envelope.ceiling',
                       flags=[f.get('status') for f in last.get('flags') or () if type(f) is dict], **evidence)
    broker = last.get('broker') or {}
    if broker.get('available') is not True:
        findings.not_applicable('EG09', None, 'not_applicable:no_independent_broker_count', **evidence)
    elif ((last.get('floors') or {}).get('H5') or {}).get('status') == 'ok':
        findings.satisfied('EG09', None, mechanism='engagement.envelope.broker', **evidence)
    else:
        findings.violated('EG09', None, 'model requests the independent broker counted are not all attributed to '
                          'controller sessions', label='ENGAGEMENT BELOW FLOOR', **evidence)


def fidelity_frontier(ev, artifact, planned, depth=0, seen=None):
    """The detector fidelity levels that feed ``artifact``: its producing step's planned level, else the
    nearest planned levels up each branch of its custody lineage (a combining step inherits its inputs')."""
    seen = set() if seen is None else seen
    if artifact in seen or depth > 64:
        return set()
    seen.add(artifact)
    record = ev['custody'].get(artifact) or {}
    step = record.get('step_id') or str(artifact).split(':', 1)[0]
    if planned.get(step) is not None:
        return {planned[step]}
    levels = set()
    for parent in record.get('inputs') or ():
        levels |= fidelity_frontier(ev, parent, planned, depth + 1, seen)
    return levels


def fidelity_context(ev, plan):
    """The detector fidelity the pinned request demands and each plan step supplies (the analysis route's rules).

    Both come from controller-pinned records (the reading, the contract and the approved plan),
    never from a field a worker wrote into a result. Without the analysis route installed the
    check is reported as not available.
    """
    module = common.module('fidelity')
    found = {'module': module, 'wanted': None, 'planned': {}, 'available': False}
    if module is None or not all(hasattr(module, name) for name in ('requested', 'planned', 'below')):
        return found
    try:
        found['wanted'] = module.requested(ev['intake'].get('reading'), ev['intake'].get('contract')).get('level')
        found['planned'] = dict(module.planned(plan) or {})
        found['available'] = True
    except Exception as exc:  # a fidelity fault is reported, never a pass
        found['error'] = f'{type(exc).__name__}: {exc}'[:500]
    return found


def _statistic(findings, ev, row, document, statistic, prescribed, fidelity, traced):
    artifact = row['artifact']
    problems = []
    stated = None
    if type(document) is dict:
        for key in STATISTIC_KEYS:
            value = document.get(key)
            if type(value) is str and value.strip():
                stated = value.strip()
                break
    is_result = (row.get('claim_kind') in RESULT_KINDS) and type(document) is dict
    if stated is not None and statistic is not None and \
            not statistic_matches(statistic, stated, level_optional=not prescribed):
        problems.append(f'the delivered statistic {stated!r} differs from the pinned {statistic!r}')
    elif stated is None and prescribed and is_result:
        problems.append(f'the delivered result does not state the prescribed statistic {statistic!r}')
    if fidelity.get('error') and is_result:
        problems.append(f"the fidelity check failed: {fidelity['error']}")
    elif fidelity['available'] and fidelity['wanted'] is not None and is_result:
        levels = fidelity_frontier(ev, artifact, fidelity['planned'])
        below = sorted(str(level) for level in levels if fidelity['module'].below(level, fidelity['wanted']))
        if not levels:
            problems.append(f"no step in the result's lineage supplies detector fidelity; the pinned request "
                            f"demands {fidelity['wanted']}")
        elif below:
            problems.append(f"the result was produced from {', '.join(below)} detector fidelity; the pinned "
                            f"request demands {fidelity['wanted']}")
    discovery = (traced or {}).get('discovery_language') or []
    if problems:
        ledger = common.module('ledger')
        key = None
        if ledger is not None and hasattr(ledger, 'instance_key') and ev.get('run_id'):
            key = ledger.instance_key('D02', ev['run_id'], {'artifact': artifact})
        authority = _waiver(ev, 'D02', key)
        if authority:
            findings.waived('D02', artifact, authority, '; '.join(problems))
        else:
            findings.violated('D02', artifact, '; '.join(problems), label='REFUSED: STATISTIC OR FIDELITY DIFFERS',
                              refuse='qualified')
    elif discovery and statistic is not None:
        findings.violated('D02', artifact, 'discovery language in an exclusion result: '
                          + ', '.join(f"{d['text']!r} (line {d['line']})" for d in discovery[:5]),
                          label='DISCOVERY LANGUAGE IN AN EXCLUSION RESULT')
    else:
        findings.satisfied('D02', artifact, mechanism='sink.statistic',
                           record={'pinned': statistic, 'stated': stated})


STATISTICS_QUALIFIED = 'QUALIFIED: STATISTICAL VALIDITY'


def _statistics_validity(findings, artifact, document):
    """A delivered result's statistics record decides its qualification; the sink recomputes it, never reads it.

    A record that does not recompute, or a held outcome, withholds the delivery (diagnostic); a
    qualified outcome makes it qualified and renders every qualification label on the artifact.
    """
    if type(document) is not dict:
        return
    # A scan document carries one record per assembled point; each is recomputed like a single result's.
    blocks = [('', document)] if document.get('statistics') is not None else []
    points = document.get('points') if type(document.get('points')) is list else []
    blocks += [(f"{row.get('tag')}: ", row) for row in points
               if type(row) is dict and row.get('statistics') is not None]
    if not blocks:
        return
    try:
        from ravel.physics.inference import situations, uncertainty
    except ImportError as exc:  # the catalogue is part of the package; its absence is a refusal, never a pass
        findings.refuse('diagnostic', code='statistics_catalogue_missing', artifact=artifact, message=str(exc))
        return
    qualified = []
    for prefix, result in blocks:
        block = result['statistics']
        problems = situations.audit(block) or situations.result_document_errors(block, result)
        uncertainty_problems = uncertainty.document_errors(result)
        if uncertainty_problems:
            findings.refuse('diagnostic', code='uncertainty_unstated', artifact=artifact,
                            message=prefix + '; '.join(uncertainty_problems))
        if problems:
            findings.refuse('diagnostic', code='statistics_record_invalid', artifact=artifact,
                            message=prefix + 'the statistics record does not recompute: ' + '; '.join(problems))
            continue
        outcome, labels = block['validity']['outcome'], situations.labels(block)
        if outcome == 'held':
            findings.refuse('diagnostic', code='statistics_held', artifact=artifact,
                            message=prefix + 'the statistics outcome is held: ' + '; '.join(labels))
        elif outcome == 'qualified':
            qualified += [prefix + text for text in labels]
    if qualified:
        for text in qualified:
            findings.label(STATISTICS_QUALIFIED, artifact=artifact, text=text)
        findings.refuse('qualified', code='statistics_qualified', artifact=artifact,
                        message='the statistics outcome is qualified: ' + '; '.join(qualified))


NOTICE_MARKERS = ('RAVEL SINK NOTICE', 'RAVEL delivery label:')


def _forged_notice(path, kind):
    """Why a delivered artifact carries a worker-written receipt or sink notice, or None."""
    try:
        if Path(path).stat().st_size > common.TEXT_LIMIT:
            return None
        raw = Path(path).read_bytes()
    except OSError:
        return None
    text = raw.decode('utf-8', errors='replace')
    if any(marker in text for marker in NOTICE_MARKERS):
        return 'the artifact carries a sink notice written by a worker; only the sink renders notices'
    if _suffix(path) == '.json':
        try:
            document = json.loads(raw)
        except ValueError:
            return None
        for item in _objects(document):
            if item.get('kind') == common.RECEIPT_KIND or 'architecture_complete' in item:
                return 'the artifact carries a worker-supplied architecture receipt; the sink computes the only receipt'
    return None


def _panel_holes(ev, plan, row, run_dir, hashes):
    """Requested panels the figure's adopted panel census lacks (the step names ``parameters.panels``)."""
    step = next((s for s in (plan or {}).get('steps') or () if s.get('id') == row['step']), {})
    wanted = (step.get('parameters') or {}).get('panels')
    if type(wanted) is not list or not wanted:
        return []
    destination = str(Path(row['destination']).with_suffix('')) + '.panels.json'
    record = next((r for r in ev['custody'].values() if r.get('destination') == destination), None)
    if record is None or record.get('status') != 'accepted' or hashes.of(destination) != record.get('sha256'):
        return [f'{p} (no accepted panel census at {destination})' for p in wanted]
    found = _load_json(run_dir / destination)
    present = [p.get('id') if type(p) is dict else p for p in (found or {}).get('panels') or ()] \
        if type(found) is dict else []
    return [str(p) for p in wanted if p not in present]


def _open_defects(document):
    found = []
    for item in _objects(document):
        classification = item.get('classification') if type(item.get('classification')) is dict else {}
        kind = item.get('kind') if type(item.get('kind')) is str else classification.get('kind')
        status = str(item.get('status') or item.get('disposition') or '').lower()
        if kind == 'defect' and (status in OPEN_DEFECT or not status):
            found.append(str(item.get('id') or item.get('summary') or 'defect')[:80])
    return found


def _claimed_verdict(document):
    if type(document) is dict and type(document.get('verdict')) is str and any(
            k in document for k in ('findings', 'items', 'panel', 'seats', 'dispositions')):
        return document['verdict']
    return None


def _runtime_problem(ev, row, item):
    """Compare runtime claims to the producing launch's controller record, never to each other.

    A launch without a recorded runtime supports no version pin. Explicit nulls disclose
    unknown versions; they do not assert a pin or permit an exporter to supply one.
    """
    fields = [key for key in ('runtime', 'exported_runtime') if key in item]
    if fields == ['runtime'] and type(item['runtime']) is not dict:
        return None  # scalar elapsed runtime is not an environment claim
    if not fields:
        return None
    custody = (ev.get('custody') or {}).get(row['artifact']) or {}
    producer = custody.get('producer') if type(custody.get('producer')) is dict else {}
    launch = next((entry for entry in ev.get('launches') or ()
                   if producer.get('kind') == 'launch' and entry.get('id') == producer.get('journal_id')
                   and entry.get('step_id') == custody.get('step_id')
                   and entry.get('attempt') == custody.get('attempt')), None)
    finished = (launch or {}).get('finished') or {}
    recorded = None
    if (finished.get('exit_status') == 0 and finished.get('step_id') == custody.get('step_id')
            and finished.get('attempt') == custody.get('attempt')):
        recorded = finished.get('runtime')
    for field in fields:
        claimed = item[field]
        if type(claimed) is not dict:
            return f"{row['artifact']}: {field} is not a runtime mapping"
        if type(recorded) is dict:
            try:
                matches = common.canonical(claimed) == common.canonical(recorded)
            except (TypeError, ValueError):
                return f"{row['artifact']}: {field} or the recorded runtime is not finite JSON"
            if not matches:
                return f"{row['artifact']}: {field} differs from the producing launch's recorded runtime"
        elif any(value is not None for value in claimed.values()):
            return f"{row['artifact']}: {field} pins versions without a controller-recorded runtime"
    return None


def _scan_run_rows(findings, ev, delivered, run_dir):
    """C06, C33, E11, E15, E19 and E27 over the delivered JSON documents."""
    uncertified, certificates, tails, fidelity, caps, bounds = [], [], [], [], [], []
    runtimes = []
    for row in delivered:
        path = run_dir / row['destination']
        if _suffix(path) != '.json':
            continue
        document = _load_json(path)
        if document is None:
            continue
        for item in _objects(document):
            historical = item.get('runtime')
            exported = item.get('exported_runtime')
            if type(historical) is dict and type(exported) is dict:
                changed = [name for name, version in historical.items()
                           if exported.get(name) != version]
                if changed:
                    findings.violated('E27', None,
                                      'unsupported historical runtime substitution: ' + ', '.join(changed),
                                      refuse='diagnostic')
            runtime_problem = _runtime_problem(ev, row, item)
            if runtime_problem:
                runtimes.append(runtime_problem)
            for key in ('certification', 'certificate'):
                cert = item.get(key)
                if type(cert) is dict:
                    status = str(cert.get('status') or cert.get('verdict') or '').lower()
                    if status not in CERTIFIED:
                        absent = [f for f in UNCERTIFIED_FIELDS if not cert.get(f) and not item.get(f)]
                        if absent:
                            uncertified.append(f"{row['artifact']}: {', '.join(absent)}")
            kind = str(item.get('kind') or '')
            if 'certif' in kind or 'certificate' in item or 'r5_certificate' in item:
                named = item.get('rundir') or item.get('run_dir')
                if type(named) is str and named and not common.inside(run_dir, named):
                    certificates.append(f"{row['artifact']}: names the run {named}")
            tier = str(item.get('tier') or '').lower()
            status = str(item.get('status') or item.get('verdict') or '').lower()
            if tier in ('tail', 'report-only', 'report_only') and (item.get('certified') is True or status in CERTIFIED):
                tails.append(f"{row['artifact']}: {item.get('name') or item.get('region') or tier}")
            declared = item.get('fidelity')
            declared = declared.get('mode') or declared.get('level') if type(declared) is dict else declared
            mode = str(declared or '').lower()
            if mode in UNCERTIFIED_MODES and (item.get('exclusion_of_record') is True or item.get('certified') is True):
                fidelity.append(f"{row['artifact']}: {mode}")
            capped = item.get('median_at_cap') is True or item.get('at_poi_cap') is True or status in BOUND_STATUSES
            if capped:
                if item.get('resolved') is True or status in RESOLVED_STATUSES and status not in BOUND_STATUSES:
                    caps.append(f"{row['artifact']}: {item.get('name') or item.get('id') or 'limit'}")
                else:
                    bounds.append(row['artifact'])
    _labelled(findings, 'C06', uncertified, 'UNCERTIFIED CLAIM WITHOUT ITS LIMITATION FIELDS',
              'uncertified claims lack fidelity, explanation, certifiable route or flag')
    if certificates:
        findings.violated('C33', None, 'a certificate from outside this run is offered: ' + '; '.join(certificates[:5]),
                          refuse='diagnostic')
    else:
        findings.satisfied('C33', None, mechanism='sink.custody_lineage')
    _labelled(findings, 'E11', tails, 'LOW-STATISTICS REGION IS REPORT-ONLY',
              'a low-statistics region is presented as certified')
    _labelled(findings, 'E15', fidelity, 'UNCERTIFIED FIDELITY: NO EXCLUSION OF RECORD',
              'an uncertified custom analysis claims an exclusion of record')
    _labelled(findings, 'E19', caps, 'SCAN CAP IS A BOUND, NOT A RESOLVED CROSSING',
              'a scan cap is presented as a resolved crossing')
    if bounds:
        findings.label('LIMIT IS A BOUND AT THE SCAN CAP', text=', '.join(sorted(set(bounds))[:10]))
    if runtimes:
        message = '; '.join(runtimes[:10])
        # A substitution already found above keeps its own reason; this check adds its refusal either way.
        if (findings.rows.get(('E27', None)) or {}).get('status') == 'violated':
            findings.label('REFUSED: UNSUPPORTED RUNTIME PIN', row='E27', text=message)
        else:
            findings.violated('E27', None, message, label='REFUSED: UNSUPPORTED RUNTIME PIN')
        findings.refuse('diagnostic', code='unsupported_runtime_pin', row='E27', message=message)


def _labelled(findings, row, hits, label, what):
    if hits:
        findings.violated(row, None, f'{what}: ' + '; '.join(hits[:10]), label=label)
    else:
        findings.satisfied(row, None, mechanism='sink.scan')


def ledger_chain(findings, ledger):
    """A ledger whose own record chain does not verify decides nothing: the delivery is diagnostic."""
    if not (ledger or {}).get('available'):
        return  # an absent ledger is refused where the delivery decisions are taken
    chain = ((ledger or {}).get('summary') or {}).get('chain') or {}
    if chain.get('verified') is not True:
        findings.refuse('diagnostic', code='ledger_chain', message='the obligation ledger chain does not verify: '
                        + str(chain.get('error') or (ledger or {}).get('error') or 'no verified chain in its summary'))


def ledger_labels(findings, ledger):
    """Render every labelled (L-class) violation the ledger holds, whichever node recorded it.

    The label text is the one the recording node stored with the violation; a violation stored
    without one is rendered by its row id, so no labelled violation can go unshown.
    """
    summary = (ledger or {}).get('summary') or {}
    for violation in summary.get('violations') or ():
        if type(violation) is not dict or violation.get('class') != 'L':
            continue
        label = violation.get('label') or f"{violation.get('id')} VIOLATED"
        text = f"{violation.get('id')}: {violation.get('reason') or 'labelled violation'}" + \
            (' (superseded attempt)' if violation.get('superseded') else '')
        findings.label(str(label), row=violation.get('id'), text=text)


def adopted_defaults(ev):
    """Every adopted delegated default with its justification: judgment records and authority defaults (C22)."""
    out = []
    for record in ev['judgments']:
        chosen, default = record.get('chosen'), record.get('default_option')
        if default is not None and chosen == default:
            option = next((o for o in record.get('options') or () if type(o) is dict and o.get('id') == chosen), {})
            out.append({'source': 'judgment', 'id': record.get('_id'), 'step': record.get('step'),
                        'question': record.get('question'), 'chosen': chosen,
                        'rationale': record.get('rationale'), 'default': record.get('default'),
                        'class': record.get('class'),
                        'option': option.get('description') or option.get('summary') or option.get('text'),
                        'predicted': option.get('predicted_consequences')})
    for record in ev['authority'].get('defaults') or ():
        out.append({'source': 'authority', 'id': record.get('id'), 'kind': record.get('kind'),
                    'chosen': record.get('option'), 'label': record.get('label'),
                    'rationale': record.get('comment') or 'conservative default recorded at the wait bound'})
    return out
