"""One fail-closed independence decision, separate from transport and human authority.

For a run the controller owns, the evidence is read only from that run's protected store,
where the controller alone records the sessions it started and the review outputs it observed
(``review_dispatch.store_lookup``); an installed resolver, a run file or a same-user state
record supplies none. For any other run the evidence comes from a controller resolver. By
default it is ``review_dispatch.lookup``: what RAVEL's own dispatchers recorded while they
dispatched the role (a supervised worker launch, a graph runner's completed model call),
outside the run tree and every worker sandbox. Those records are written by processes of the
same OS user (``same_user_state``), and the decision says so. A host controller with a stronger
boundary installs its own resolver with ``authority_session``, which replaces the default for
that scope. Only a controller-owned process may install one. Never install a resolver from a
run file, environment setting, model response or tool argument. A declared reviewer name, a
host or relay report and a control transport supply no evidence anywhere.

Independence rests on a separate observed session, a distinct actor and an artifact-only
RAVEL packet. Model families are never required: ``family_relation`` only labels a credited
seat (``separate session, same model family`` when that is what happened).

Existing consumers still verify their ordinary receipts, subjects and artifacts.
This module adds a necessary condition; it never substitutes for those checks.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

_AUTHORITY = ContextVar('review_dispatch_authority', default=None)
_SHA = re.compile(r'[0-9a-f]{64}')
_BUILDERS = frozenset({'ravel.workflow.review_projection', 'ravel.workflow.scientific_judgment',
                       'ravel.workflow.research_protocol', 'ravel.workflow.rdj_loop'})
_EXPOSURES = frozenset({'author_identity', 'author_rationale', 'reference_values', 'peer_verdicts'})
# Where the evidence behind a decision lies. The controller alone writes its run store; a resolver a
# controller-owned process installed reports ``controller_only``; the dispatcher records of a run the
# controller does not own are same-user state, credited as before and labelled by this boundary.
CONTROLLER_STORE, INSTALLED_RESOLVER, SAME_USER_STATE = 'controller_store', 'controller_only', 'same_user_state'
FAMILY_LABELS = {'same': 'separate session, same model family',
                 'different': 'separate session, different model family',
                 'unknown': 'separate session, model family unknown'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@contextmanager
def authority_session(resolver):
    """Controller composition seam, never an agent-facing registration operation.

    ``resolver(query)`` returns authenticated evidence or None; it replaces the
    default dispatcher-record resolver inside this scope. The resolver is
    responsible for an immutable invocation binding and live, complete context
    census across all phases/graphs in this run. Tests that model a controller
    use an inert one. This scope grants no authority to persisted decision
    dictionaries.
    """
    if not callable(resolver):
        raise TypeError('controller resolver must be callable')
    token = _AUTHORITY.set(resolver)
    try:
        yield
    finally:
        _AUTHORITY.reset(token)


def advisory(reason):
    return {'independent': False, 'advisory': reason, 'dispatch_id': None,
            'context_id': None, 'exposure': None}


def _names(value, *, nonempty=False):
    return (type(value) is list and (bool(value) or not nonempty)
            and all(type(x) is str and bool(x.strip()) for x in value)
            and len(set(value)) == len(value))


def controller_run(run):
    """The controller's run id when it owns the run directory ``run``, else None.

    Raises when ownership cannot be determined, so an unreadable store never reads as ungoverned.
    """
    try:
        from ravel.controller.store import controller_owned
    except ModuleNotFoundError as exc:
        if exc.name in {'ravel.controller', 'ravel.controller.store'}:
            return None  # No controller is installed: no run can be controller-owned.
        raise  # A broken controller dependency must not turn enforcement off.
    return controller_owned(Path(run))


def controller_store(run):
    """The run's protected store when the controller owns ``run``; None for a run it does not own."""
    run_id = controller_run(run)
    if run_id is None:
        return None
    from ravel.controller.store import RunStore
    return RunStore(run_id)


def decide(query):
    """Authenticate exact bytes and context separation; unknown evidence is advice.

    The caller supplies only the expected binding, never purported proof. All
    proof comes from the controller resolver: for a controller-owned run the
    controller's own records in its run store, never an installed resolver.
    Exposure is explicit by dimension; this decision does not claim semantic or
    double blinding of allowed evidence. A credited decision names where its
    evidence lies (``evidence_boundary``) and labels how the reviewer's model
    family relates to the authors' (``family_relation``, ``label``); the family
    never decides credit.
    """
    required = {'run', 'role', 'subject_sha256', 'receipt_sha256', 'output_sha256', 'packet_sha256'}
    if type(query) is not dict or set(query) != required:
        return advisory('review_binding_invalid')
    if any(type(query[k]) is not str or not query[k].strip() for k in ('run', 'role')):
        return advisory('review_binding_invalid')
    if any(type(query[k]) is not str or not _SHA.fullmatch(query[k])
           for k in ('subject_sha256', 'receipt_sha256', 'output_sha256')):
        return advisory('review_binding_invalid')
    if query['packet_sha256'] is not None and (type(query['packet_sha256']) is not str
                                             or not _SHA.fullmatch(query['packet_sha256'])):
        return advisory('review_binding_invalid')
    try:
        store = controller_store(query['run'])
    except Exception:
        return advisory('controller_ownership_unknown')
    if store is not None:
        from .review_dispatch import store_lookup

        def resolver(q):
            return store_lookup(q, store)
        accepted = {CONTROLLER_STORE}
    else:
        resolver = _AUTHORITY.get()
        if resolver is None:
            from .review_dispatch import lookup as resolver
        accepted = {INSTALLED_RESOLVER, SAME_USER_STATE}
    try:
        proof = deepcopy(resolver(deepcopy(query)))
    except Exception:
        return advisory('trusted_dispatch_unavailable')
    if type(proof) is not dict or proof.get('binding') != query:
        return advisory('trusted_dispatch_missing_or_changed')
    if proof.get('authority_boundary') not in accepted:
        return advisory('dispatch_authority_unprotected')
    context = proof.get('context_id')
    if type(context) is not str or not context.strip() or type(proof.get('dispatch_id')) is not str or not proof['dispatch_id'].strip():
        return advisory('context_unknown')
    authors = proof.get('author_context_ids')
    if proof.get('author_census_complete') is not True or not _names(authors, nonempty=True):
        return advisory('author_context_unknown')
    if context in authors:
        return advisory('author_context_review')
    prior = proof.get('other_review_context_ids')
    if proof.get('review_census_complete') is not True or not _names(prior):
        return advisory('review_context_unknown')
    if context in prior:
        return advisory('review_context_reused')
    if proof.get('parent_transcript_supplied') is not False:
        return advisory('inherited_or_unknown_transcript')
    packet = proof.get('packet')
    if type(packet) is not dict or type(packet.get('builder')) is not str or packet['builder'] not in _BUILDERS \
            or packet.get('projection_verified') is not True or packet.get('author_summary') is not False:
        return advisory('packet_not_ravel_projection')
    packet_sha = packet.get('sha256')
    if type(packet_sha) is not str or not _SHA.fullmatch(packet_sha) \
            or query['packet_sha256'] not in (None, packet_sha) \
            or packet.get('subject_sha256') != query['subject_sha256']:
        return advisory('projected_packet_changed')
    if proof.get('read_boundary') not in ('packet_only', 'tools_disabled') \
            or proof.get('read_boundary_verified') is not True:
        return advisory('packet_only_access_unverified')
    exposure = proof.get('exposure')
    if type(exposure) is not dict or set(exposure) != _EXPOSURES \
            or any(v not in ('withheld', 'permitted') for v in exposure.values()) \
            or proof.get('exposure_verified') is not True:
        return advisory('permitted_exposure_unverified')
    if proof.get('output_unmodified') is not True:
        return advisory('review_output_changed')
    relation = family_relation(proof.get('models'))
    return {'independent': True, 'advisory': None, 'dispatch_id': proof['dispatch_id'],
            'context_id': context, 'exposure': exposure, 'evidence_boundary': proof['authority_boundary'],
            'family_relation': relation, 'label': family_label(relation)}


def _family(value):
    """A model's vendor family from a model id, or from ``{'family': ..., 'model': ...}``; None if unknown."""
    from .transport_registry import FAMILY_PATTERNS, model_family
    if type(value) is dict:
        family = value.get('family')
        if type(family) is str and family.strip() and family not in ('any', 'unknown'):
            return family
        value = value.get('model')
    if type(value) is not str or not value.strip():
        return None
    if value in {name for name, _ in FAMILY_PATTERNS}:
        return value
    family = model_family(value)
    return None if family == 'unknown' else family


def family_relation(models):
    """Label only: how the reviewer's model family relates to the others'. Never a requirement.

    ``models`` maps seat or role names to the model each was observed on: a model identifier, or
    ``{'model': ..., 'family': ...}`` where a registered family wins. The ``reviewer`` entry (the
    first entry when none is named so) is compared with every other entry: ``same`` when another
    shares its family, ``different`` when every family is known and none is shared, otherwise
    ``unknown``. Two sessions of one family are independent sessions; this only says which.
    """
    if type(models) is not dict or len(models) < 2:
        return 'unknown'
    subject = 'reviewer' if 'reviewer' in models else next(iter(models))
    mine = _family(models[subject])
    others = [_family(v) for k, v in models.items() if k != subject]
    if mine is not None and mine in others:
        return 'same'
    if mine is None or None in others:
        return 'unknown'
    return 'different'


def family_label(relation):
    """The receipt text for a credited seat: ``separate session, same model family`` and so on."""
    return FAMILY_LABELS[relation if relation in FAMILY_LABELS else 'unknown']


def seat_refusal(card, session, sessions):
    """Why ``session`` cannot hold a seat of ``card`` (its ``independence`` fields), or None.

    ``session`` and every entry of ``sessions`` (all sessions the controller started in the run)
    are ``{'session_id', 'role', 'actor_id', 'fresh'}`` records. The dispatcher asks before a start
    and the credit decision asks again: a card that needs a fresh session refuses a resumed or
    unobserved one, a session already holding another seat is reused, and an actor of a role the
    card names in ``distinct_actor_from`` is refused. Model families are not compared.
    """
    from .role_registry import same_card
    independence = (card or {}).get('independence') or {}
    if type(session) is not dict or type(session.get('session_id')) is not str or not session['session_id']:
        return 'session_unobserved'
    if independence.get('fresh_session') is True and session.get('fresh') is not True:
        return 'session_not_fresh'
    others = [o for o in sessions if type(o) is dict and o is not session and o != session]
    if any(o.get('session_id') == session['session_id'] for o in others):
        return 'session_reused'
    actor = session.get('actor_id')
    for role in independence.get('distinct_actor_from') or []:
        if actor is None or any(same_card(o.get('role'), role) and o.get('actor_id') == actor for o in others):
            return 'actor_not_distinct:' + role
    return None


def worker_query(root, receipt, receipt_sha256, *, subject_sha256):
    return {'run': str(Path(root).resolve()), 'role': (receipt.get('role') or {}).get('id'),
            'subject_sha256': subject_sha256, 'receipt_sha256': receipt_sha256,
            'output_sha256': (receipt.get('final_record') or {}).get('sha256'),
            'packet_sha256': None}


def graph_query(root, receipt):
    return {'run': str(Path(root).resolve()), 'role': receipt.get('role'),
            'subject_sha256': receipt.get('subject_sha256'), 'receipt_sha256': receipt.get('receipt_sha256'),
            'output_sha256': digest(receipt.get('public_value')),
            'packet_sha256': receipt.get('context_manifest_sha256')}


def graph_decision(root, receipt):
    return decide(graph_query(root, receipt))


def require(decision):
    if not decision['independent']:
        raise ValueError('review is advisory; no independent credit: ' + decision['advisory'])
    return decision


def retain_advice(root, value, decision):
    """Retain uncredited responses outside the acceptance/objection journal."""
    from . import broker
    root = broker.ordinary(root)
    record = {'schema_version': 1, 'kind': 'review_advice', 'independent': False,
              'advisory': decision['advisory'], 'value': deepcopy(value), 'execution_authorized': False}
    directory = broker.confined(root, 'review-advice')
    directory.mkdir(exist_ok=True)
    path = broker.confined(root, 'review-advice/' + digest(record) + '.json')
    raw = (json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    try:
        with path.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('retained review advice changed') from None
    return {**record, 'path': str(path)}


def journal_decision(root, event):
    """Reauthenticate a scientific journal vote without trusting saved credit flags."""
    evidence = event.get('independence_evidence')
    if type(evidence) is not dict or set(evidence) != {'query', 'response', 'request'}:
        return advisory('declared_name_advice')
    query, value = evidence['query'], evidence['response']
    roles = {'critic': 'physics_critic', 'verifier': 'skeptical_verifier', 'synthesizer': 'physics_decider'}
    if type(query) is not dict or type(value) is not dict:
        return advisory('review_binding_invalid')
    if query.get('run') != str(Path(root).resolve()) or roles.get(query.get('role')) != event.get('role') \
            or digest(value) != query.get('output_sha256') \
            or value.get('subject_sha256') != query.get('subject_sha256') \
            or any(value.get(k) != event.get(k) for k in
                   ('verdict', 'summary', 'findings', 'closes', 'claim_scope')):
        return advisory('review_output_changed')
    try:
        from .scientific_judgment import _read_pin
        if evidence['request'].get('sha256') != query.get('subject_sha256'):
            return advisory('review_binding_invalid')
        contract = _read_pin(evidence['request'])
        from .role_registry import same_card
        if (contract.get('rundir') != query['run'] or not same_card(contract.get('role'), query['role'])
                or contract.get('cycle_id') != event.get('cycle_id')
                or contract.get('phase') != 'result_review'):
            return advisory('review_subject_changed')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return advisory('review_subject_changed')
    return decide(query)


def meta_decision(event):
    """Historical meta resolutions need the same live authority as new intake."""
    query = event.get('independence_query')
    receipt = event.get('role_receipt')
    if type(query) is not dict or type(receipt) is not dict:
        return advisory('unauthenticated_meta_advice')
    if type(query.get('run')) is not str or graph_query(query['run'], receipt) != query:
        return advisory('review_binding_invalid')
    value = receipt.get('public_value')
    fields = ('action', 'affected_claim_ids', 'affected_stage_ids', 'objections', 'required_experiment_ids',
              'resolves_meta_revisions', 'replacement_stage_ids', 'replacement_comparison_ids', 'replacement_claim_ids')
    if type(value) is not dict or any(event.get(k) != value.get(k) for k in fields):
        return advisory('review_output_changed')
    return decide(query)
