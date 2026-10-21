"""Seat rows the governed step closes from the records of the actions that enforce them.

A seat (a worker, a review step or a child review seat) materialises its seat-stage and
review-stage rows before its worker starts. The step graph's nodes record each row from the record
their enforcing action wrote; nothing is satisfied without such a record, and a row whose condition
is absent is recorded not applicable with a typed reason and the record that shows it absent.

Which record closes which row:

- reservation (``budget.reserve``): A07, C02 and C13 are not applicable when the step declares no
  rung or is not a top-rung operation (no pilot calibration is used); SW24 is not applicable to a
  worker seat, which submits no remote job and exports no procedure.
- dispatch record (``step-dispatch``, the transport selection): SW21 (an installed declaration),
  XF02, CF14 and XF01 (the family is recorded as a label, never a constraint); SW09 from the
  operator-run qualification record in the run's store that the selection counted.
- consult triggers (a ``step-fact``): CF04 is not applicable when the card declares no consult or
  none of its triggers fired.
- observation (``step-observation``): CT05 from the confinement inventory probe; SW40 is the
  labelled residual worker exposure; E30 is not applicable when the start was not ambiguous.
- observed session (``review-session``, recorded from the verified receipt): SW06 (an admitted
  transport, a controller-observed session), CF10 and the role's ``independence`` row (the card's
  ``fresh_session`` and ``distinct_actor_from`` over the run's whole session census) and XF08
  (separate-session independence, the family only a label).
- instruction manifest: E29 is not applicable when no skill unit was delivered.
- credit decision (``step-credit``, read only from the controller store) for a review: C35, G09,
  SW07, V02, V03, XF05, I06, V06 and CF12 (the reviewer items it judged), CT06 and XF03 with the
  family label; the role projection (manifest) for CF09, G03, V04 and the role's ``sees`` row.
- P05 is not applicable to a review seat, which hands off no theory, measurement, likelihood or
  event quantity.
"""
from __future__ import annotations

from copy import deepcopy

FAMILY_LABEL = 'no cross-family requirement: the model family is recorded as a label only'


def _row(status, **evidence):
    return {'status': status, 'evidence': deepcopy(evidence)}


def na(reason, **evidence):
    return _row('not_applicable', reason='not_applicable:' + reason, **evidence)


def reserve_rows(acting, branch, reservation_id, *, top_rungs, operation_kinds):
    """Rows the reservation shows absent: no rung, no top-rung operation, no remote job or procedure export."""
    rows = {}
    rung, kind = acting.get('rung'), acting.get('kind')
    if rung is None:
        rows['A07'] = na('step_declares_no_rung', record=reservation_id)
    if not (rung in top_rungs and kind in operation_kinds):
        rows['C02'] = na('not_a_top_rung_operation', record=reservation_id, rung=rung, kind=kind)
        rows['C13'] = na('no_pilot_calibration_used', record=reservation_id, rung=rung, kind=kind)
    if branch == 'worker':
        rows['SW24'] = na('worker_seat_submits_no_remote_job_and_exports_no_procedure', record=reservation_id)
    return rows


def selection_rows(selection, dispatch_id, qualification_id):
    """Rows the transport selection decides, from the dispatch record and the store qualification it counted."""
    rows = {'XF02': _row('satisfied', record=dispatch_id, family=selection.get('family')),
            'CF14': _row('satisfied', record=dispatch_id, family=selection.get('family'), label=FAMILY_LABEL),
            'XF01': _row('satisfied', record=dispatch_id, family=selection.get('family'), label=FAMILY_LABEL)}
    if selection.get('declaration_origin') == 'builtin':
        rows['SW21'] = _row('satisfied', record=dispatch_id, sha256=selection.get('declaration_sha256'))
    else:
        rows['SW21'] = _row('violated', record=dispatch_id,
                            reason=f"declaration_origin:{selection.get('declaration_origin')}")
    if qualification_id is not None:
        rows['SW09'] = _row('satisfied', record=qualification_id, mechanism='transport_registry.store_qualifications')
    return rows


def consult_rows(card, fired, fact):
    """CF04 when no consult is owed: the card declares none, or none of its triggers fired."""
    if fired:
        return {}
    declared = ((card or {}).get('knowledge') or {}).get('consult') or []
    reason = 'card_declares_no_consult' if not declared else 'no_consult_trigger_fired'
    return {'CF04': na(reason, **fact)}


def observation_rows(observation_id, inventory, settlement):
    """CT05 from the inventory probe, SW40 as the labelled residual exposure, E30 for an unambiguous start."""
    rows = {}
    if type(inventory) is dict and inventory.get('kind') == 'worker':
        if inventory.get('equal') is True and not inventory.get('differences'):
            rows['CT05'] = _row('satisfied', record=observation_id, probe=inventory.get('backend'))
        else:
            rows['CT05'] = _row('violated', record=observation_id, reason='inventory_probe_mismatch')
        label = 'worker sandbox: CLI home read-write; RAVEL package readable; ' + str(inventory.get('egress_label'))
        rows['SW40'] = _row('violated', record=observation_id, label=label,
                            reason='residual worker exposure, labelled for the receipt')
    if settlement in ('settled', 'released'):
        rows['E30'] = na('no_ambiguous_start', record=observation_id, settlement=settlement)
    return rows


def session_rows(card, session, sessions, *, session_record, transport_kind, admitted_kinds, label):
    """Rows the observed session decides: an admitted, controller-observed, fresh, distinct seat session.

    ``session`` is the controller's ``review-session`` record of this seat (``session_record`` its store id) and
    ``sessions`` every session the controller observed in the run.
    """
    from ravel.workflow.review_independence import seat_refusal
    if session is None or session_record is None:
        return {}
    rows = {}
    if transport_kind in admitted_kinds:
        rows['SW06'] = _row('satisfied', record=session_record, transport=session.get('transport_id'))
    else:
        rows['SW06'] = _row('violated', record=session_record, reason=f'transport_kind:{transport_kind}')
    refusal = seat_refusal(card, session, sessions)
    independence = (_row('satisfied', record=session_record, fresh=session.get('fresh'))
                    if refusal is None else _row('violated', record=session_record, reason=refusal))
    rows['CF10'] = independence
    rows[f"ROLE-{card['id']}-independence"] = deepcopy(independence)
    if refusal is None:
        rows['XF08'] = _row('satisfied', record=session_record, label=label)
    return rows


def packet_rows(manifest):
    """E29 when the delivered manifest holds no skill unit (with skill units the acknowledgement discharges it)."""
    units = (manifest or {}).get('units') or []
    if any(u.get('via') == 'skill' for u in units):
        return {}
    return {'E29': na('no_skill_unit_delivered', sha256=(manifest or {}).get('sha256'))}


def validate_rows(acting, seat, validation_id):
    """P05 is not applicable to a review seat: it hands off no theory, measurement, likelihood or event quantity."""
    if (seat or {}).get('purpose') == 'review' or acting.get('kind') == 'review':
        return {'P05': na('review_seat_hands_off_no_chain_quantity', validator=validation_id)}
    return {}


def review_rows(card, decision, *, credit_id, review_output_id, manifest, projection_sha256, qualification_id,
                isolation_confirmed, item_problems, validation_id):
    """Rows a review's credit decision and its role projection close."""
    rows = {}
    credited = bool((decision or {}).get('independent'))
    label = (decision or {}).get('label')
    if credited:
        common = {'credit': credit_id, 'record': review_output_id,
                  'evidence_boundary': decision.get('evidence_boundary')}
        for row in ('C35', 'G09', 'SW07', 'V02', 'V03', 'XF05', 'I06', 'V06'):
            rows[row] = _row('satisfied', **common)
        rows['CT06'] = _row('satisfied', **common, label=label)
        rows['XF03'] = _row('satisfied', **common, label=label)
        if not item_problems:
            rows['CF12'] = _row('satisfied', credit=credit_id, validator=validation_id)
    elif decision is not None:
        reason = 'review_uncredited:' + str(decision.get('advisory'))
        for row in ('C35', 'G09', 'SW07', 'V02', 'V03', 'XF05', 'I06', 'V06'):
            rows[row] = _row('violated', credit=credit_id, reason=reason)
    if manifest is not None:
        profile_ok = (manifest.get('profile') == card['sees']['profile']
                      and sorted(manifest.get('forbidden_inputs') or []) == sorted(card['sees'].get('forbidden_inputs') or []))
        projected = {'sha256': projection_sha256}
        rows['CF09'] = (_row('satisfied', **projected) if profile_ok else
                        _row('violated', reason='projection_sees_differs_from_card', **projected))
        rows[f"ROLE-{card['id']}-sees"] = deepcopy(rows['CF09'])
        if qualification_id is not None and profile_ok:
            rows['G03'] = _row('satisfied', sha256=projection_sha256, record=qualification_id)
        if isolation_confirmed and profile_ok:
            rows['V04'] = _row('satisfied', sha256=projection_sha256, probe='read_denied')
    return rows
