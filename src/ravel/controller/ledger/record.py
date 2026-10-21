"""Status changes of ledger instances (CONTROLLER-SPEC 7.3).

Allowed changes: ``pending`` to any other status; ``satisfied`` to ``satisfied`` (further evidence, such as an
outside attempt the mechanism refused) or ``violated`` (the evidence was invalidated); ``waived`` and
``not_applicable`` to ``violated``. ``violated`` is final for the instance: a retry is a new seat attempt, so a new
instance, and the violated one stays in the record and the receipt. Nothing returns to ``pending``.

Evidence: ``satisfied`` names a receipt id, artifact digest, validator result, credit id, authority record id,
instruction receipt, acknowledgement, mechanism or gate; R rows need a ``credit``; I rows an ``ack``; a
deliverable-conservation row the plan steps that cover it (``covered_by``), each closed. ``violated`` and
``not_applicable`` need a ``reason`` (``not_applicable`` on an R row also a ``credit`` for the reviewed reason); a
violated L row also its ``label``; a conserved original obligation is never ``not_applicable``: only a covering
step or a waiver closes it.
``waived`` needs an authority record id (the authority service's ``uid`` or the store's record id), read by the
authenticated reader explicitly installed at composition: the record must belong to the run, be labelled a
physicist terminal response or an operator command, grant its subject, and name the row (its catalogue id or
instance key) in ``subject.obligations`` or, for a deviation, in ``subject.change.touches``. Only rows whose waivability is
``authority`` can be waived.
"""
from __future__ import annotations

from . import chain
from .catalogue import Catalogue
from .chain import LedgerError
from .state import ALLOWED, State
EVIDENCE_KEYS = ('receipt', 'artifact', 'sha256', 'validator', 'credit', 'authority', 'instruction_receipt', 'ack',
                 'mechanism', 'covered_by', 'gate', 'probe', 'record')
AUTHORITY_KIND = 'authority'
AUTHORITY_SCHEMA = 'authority-record.v1'
# Who may waive (CONTROLLER-SPEC 7.3): the physicist at the controller's terminal or the operator's own answer. A
# subject that names obligations never resolves by machine, so neither a configured machine decision, a
# request-stated delegation, a worker nor a legacy unattested approval waives anything.
WAIVER_LABELS = ('physicist_terminal_response', 'operator_command')
NON_WAIVER_KINDS = ('revoke', 'stop', 'pause', 'resume', 'final')
POSITIVE_DECISIONS = ('approve', 'go', 'answer')
_authority_reader = None


def register_authority_reader(fn) -> None:
    global _authority_reader
    if not callable(fn):
        raise TypeError('an authenticated authority reader must be callable')
    if _authority_reader is not None and _authority_reader is not fn:
        raise ValueError('an authenticated authority reader is already registered')
    _authority_reader = fn


def _text(evidence: dict, key: str) -> bool:
    value = evidence.get(key)
    return isinstance(value, str) and bool(value.strip())


def _present(value) -> bool:
    return value not in (None, '', [], {}, False)


def _authority_record(store, record_id: str) -> dict:
    """Return the authenticated body supplied by the composed authority service; never scan raw records."""
    if _authority_reader is None:
        raise LedgerError('authority_unverified', 'no authenticated authority reader is registered')
    try:
        body = _authority_reader(store, record_id)
    except KeyError:
        raise LedgerError('authority_missing', f'authority record {record_id} is not in the run store') from None
    except Exception as exc:
        raise LedgerError('authority_unverified', f'authority record {record_id} could not be authenticated') from exc
    if not isinstance(body, dict):
        raise LedgerError('authority_unverified', 'the authenticated authority reader did not return a record body')
    return body


def _named(record: dict) -> list:
    """The obligations an authority record's scope names: ``subject.obligations`` or a deviation's ``touches``."""
    subject = record.get('subject') if isinstance(record.get('subject'), dict) else {}
    names = list(subject.get('obligations') or []) if isinstance(subject.get('obligations'), list) else []
    change = subject.get('change') if isinstance(subject.get('change'), dict) else {}
    if isinstance(change.get('touches'), list):
        names.extend(change['touches'])
    return [n for n in names if isinstance(n, str)]


def _authority(store, state: State, record_id: str, row_id: str, key: str) -> dict:
    record = _authority_record(store, record_id)
    if record.get('schema') not in (None, AUTHORITY_SCHEMA):
        raise LedgerError('authority_invalid', f'record {record_id} is not an {AUTHORITY_SCHEMA}')
    if record.get('run_id') != state.run_id:
        raise LedgerError('authority_invalid', f'authority record {record_id} does not belong to this run')
    if record.get('label') not in WAIVER_LABELS:
        raise LedgerError('waiver_refused', f'authority record {record_id} is labelled {record.get("label")!r}; '
                          'only a physicist terminal response or the operator can waive')
    if record.get('kind') in NON_WAIVER_KINDS:
        raise LedgerError('waiver_refused', f'an authority record of kind {record.get("kind")} waives nothing')
    if record.get('authorizes_effects') is False or ('authorizes_effects' not in record
                                                      and record.get('decision') not in POSITIVE_DECISIONS):
        raise LedgerError('waiver_refused', f'authority record {record_id} does not grant its subject')
    named = _named(record)
    if row_id not in named and key not in named:
        raise LedgerError('waiver_refused', f'authority record {record_id} does not name {row_id} in its scope')
    return record


def check(catalogue: Catalogue, state: State, store, key: str, status: str, evidence) -> dict:
    """The evidence to record, or LedgerError naming the refusal. Never writes."""
    from .gates import step_unmet  # gates read state only; imported here to keep the modules independent

    instance = state.instances.get(key)
    if instance is None:
        raise LedgerError('entry_unknown', f'ledger entry {key} was never materialised')
    row = catalogue.row(instance.id)
    if status not in ALLOWED:
        raise LedgerError('status_unknown', f'unknown ledger status {status!r}')
    if status not in ALLOWED[instance.status]:
        raise LedgerError('transition_refused', f'{key} cannot go from {instance.status} to {status}')
    if not isinstance(evidence, dict):
        raise LedgerError('evidence_invalid', 'evidence must be an object')
    chain.json_safe(evidence, '$evidence')
    if len(chain.canonical(evidence)) > chain.MAX_EVIDENCE_BYTES:
        raise LedgerError('evidence_invalid', 'evidence is larger than the ledger accepts; record pointers')
    cls = row['class']
    if status == 'satisfied':
        if not any(_present(evidence.get(k)) for k in EVIDENCE_KEYS):
            raise LedgerError('evidence_missing', f'{key}: satisfied needs one of {", ".join(EVIDENCE_KEYS)}')
        if cls == 'R' and not _present(evidence.get('credit')):
            raise LedgerError('credit_missing', f'{key}: a review-gated row is satisfied only by a credit id')
        if cls == 'I' and not _present(evidence.get('ack')):
            raise LedgerError('ack_missing', f'{key}: an instructed row is satisfied only by an acknowledgement')
        if 'deliverable' in instance.scope:
            covered = evidence.get('covered_by')
            covered = [covered] if isinstance(covered, str) else covered
            if not isinstance(covered, list) or not covered or not all(isinstance(s, str) for s in covered):
                raise LedgerError('cover_missing', f'{key}: a conserved obligation is satisfied only by covering steps')
            mapping = {d['id']: d['steps'] for d in (state.plan or {}).get('deliverables') or []}
            mapped = mapping.get(instance.scope['deliverable'], [])
            stray = [s for s in covered if s not in mapped]
            if stray:
                raise LedgerError('cover_refused', f'{key}: steps {stray} do not produce deliverable '
                                  f'{instance.scope["deliverable"]} in the current plan')
            open_steps = [s for s in covered if step_unmet(catalogue, state, s)]
            if open_steps:
                raise LedgerError('cover_refused', f'{key}: covering steps {open_steps} are not closed')
    elif status == 'violated':
        if not _text(evidence, 'reason'):
            raise LedgerError('reason_missing', f'{key}: a violation needs a reason')
        if cls == 'L' and not _text(evidence, 'label'):
            raise LedgerError('label_missing', f'{key}: a labelled row records its violation with the label the sink '
                              'renders')
    elif status == 'not_applicable':
        if 'deliverable' in instance.scope:
            raise LedgerError('conservation_refused', f'{key}: an original obligation is closed only by a covering '
                              'step or an authorized boundary (a waiver), never as not applicable')
        if not _text(evidence, 'reason'):
            raise LedgerError('reason_missing', f'{key}: not applicable needs a recorded reason')
        if cls == 'R' and not _present(evidence.get('credit')):
            raise LedgerError('credit_missing', f'{key}: the reason a review-gated row does not apply is reviewed')
    elif status == 'waived':
        if row['waivability'] != 'authority':
            raise LedgerError('waiver_refused', f'{row["id"]} is a {row["waivability"]} row: nobody may waive it')
        if not _text(evidence, 'authority'):
            raise LedgerError('authority_missing', f'{key}: a waiver needs an authority record id')
        _authority(store, state, evidence['authority'], row['id'], key)
    return evidence
