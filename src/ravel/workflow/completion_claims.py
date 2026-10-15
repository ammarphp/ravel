"""CHECK-IN 3 claim records retain trials, selected confirmation and evidence."""
from copy import deepcopy
from pathlib import Path
import math
import re
from . import evidence_status


def selection_record(selection_pin, *, base_dir, _inputs=None, regime=None):
    from .task_completion import _Inputs
    observed = _inputs or _Inputs(base_dir); own = _inputs is None
    try:
        selection = observed.document(selection_pin)
        n = selection.get('n_trials')
        trials = selection.get('trials')
        if (type(n) is not int or n < 0 or type(trials) is not list or n != len(trials)
                or n > 10000): raise ValueError('trials_unreported: exact N and retained trial census required')
        ids = set()
        for row in trials:
            if (type(row) is not dict or type(row.get('id')) is not str or not row['id']
                    or row['id'] in ids or type(row.get('candidate')) is not str
                    or type(row.get('select')) not in (int, float) or not math.isfinite(row['select'])
                    or row.get('confirm') is not None and (type(row['confirm']) not in (int, float) or not math.isfinite(row['confirm']))):
                raise ValueError('distinct finite retained trial values required')
            ids.add(row['id'])
        if type(selection.get('rule')) is not str or not selection['rule'].strip():
            raise ValueError('selection rule required')
        objective = selection.get('objective')
        if objective not in ('maximize', 'minimize'): raise ValueError('selection objective required')
        selected = selection.get('selected_candidate')
        selected_rows = [r for r in trials if r['candidate'] == selected]
        confirmation = selection.get('selected_result_on_confirm')
        best = selection.get('best_of_n_select')
        if selected is None:
            if confirmation is not None:
                raise ValueError('null funnel cannot claim a selected result')
        else:
            if len(selected_rows) != 1 or confirmation is None or confirmation != selected_rows[0].get('confirm'):
                raise ValueError('selected confirmation differs from retained selected trial')
            if regime == 'closed_scored':
                row = selected_rows[0]
                if (type(row.get('seed')) is not int or type(row.get('confirm_seed')) is not int
                        or row['seed'] == row['confirm_seed']):
                    raise ValueError('fresh confirmation seeds required in closed_scored')
        extreme = (max if objective == 'maximize' else min)(r['select'] for r in trials) if trials else None
        if best != extreme: raise ValueError('optimistic best-of-N differs from retained selection trials')
        confirmed = [r['confirm'] for r in trials if r.get('confirm') is not None]
        oracle = None if confirmation is None or not confirmed else (max if objective == 'maximize' else min)(confirmed) - confirmation
        if oracle is not None and objective == 'minimize': oracle = -oracle
        result = {'n_trials': n, 'selected_candidate': selected, 'selected_result_on_confirm': confirmation,
                  'best_of_n_select': {'value': best, 'label': 'optimistic'}, 'oracle_gap': oracle,
                  'rule': selection['rule'], 'selection': observed.canonical(selection_pin)}
        if own: observed.finish()
        return result
    finally:
        if own: observed.close()


_LEVELS = ('executed', 'checked', 'validated')


def claimed_level(claim):
    """Evidence level a claim's free text asserts; text can only lower, never raise, it."""
    if claim.get('certified') is True: return 'validated'
    text = claim.get('fidelity')
    if type(text) is not str: return None
    text = text.strip().lower()
    if re.search(r'(?:\bun|\bnot\s+|\bnon-?)certif', text) or text.startswith(
            ('uncertified', 'blinded-prediction', 'conditional')): return None
    text = text.rstrip('.')
    if 'certif' in text or text == 'validated': return 'validated'
    if text == 'checked': return 'checked'
    return None


def _claim_paths(root, claim):
    """Every local artifact path a claim pins (its quantity and receipts)."""
    pins = [claim.get('quantity'), *(p for key in ('execution_receipts', 'validator_receipts')
                                     if isinstance(claim.get(key), list) for p in claim[key])]
    paths = []
    for pin in pins:
        value = pin.get('path') if isinstance(pin, dict) else pin if isinstance(pin, str) else None
        if isinstance(value, str) and value:
            paths.append(Path(value) if Path(value).is_absolute() else Path(root) / value)
    return paths


def claim_record(root, claim, *, _inputs=None, regime=None, require_trials=True):
    if type(claim) is not dict or type(claim.get('id')) is not str or not claim['id']:
        raise ValueError('named delivered claim required')
    # A deadline-labelled provisional fill never feeds a claim or a CHECK-IN 3 record.
    from .result_templates import provisional_errors
    refused = provisional_errors(_claim_paths(Path(claim.get('rundir', root)).absolute() if _inputs is None else _inputs.base, claim))
    if refused: raise ValueError('provisional_not_reviewed: ' + refused[0])
    if require_trials and (type(claim.get('n_trials')) is not int or claim['n_trials'] < 0):
        raise ValueError('trials_unreported: every delivered claim must report N trials')
    claimed = claimed_level(claim)
    wants_certified = claimed == 'validated'
    quantity_root = Path(claim.get('rundir', root)).absolute()
    try:
        status = evidence_status.derive(quantity_root, quantity=claim['quantity'],
                    execution_receipts=claim['execution_receipts'], validator_receipts=claim['validator_receipts'], _inputs=_inputs)
    except (KeyError, ValueError, OSError, TypeError) as exc:
        if wants_certified: raise ValueError('certified_requires_validated: ' + str(exc)) from exc
        raise
    if wants_certified and not evidence_status.certified(status):
        raise ValueError('certified_requires_validated: execution or a check cannot certify a delivered quantity')
    if claimed is not None and _LEVELS.index(claimed) > _LEVELS.index(status['state']):
        raise ValueError('checked_requires_validator: fidelity text exceeds the derived evidence status')
    certified = evidence_status.certified(status)
    result = {**deepcopy(claim), 'evidence_status': status, 'certified': certified,
              'fidelity': 'certified' if certified else status['state']}
    if 'fidelity' in claim: result['declared_fidelity'] = claim['fidelity']
    if require_trials:
        if 'selection' not in claim: raise ValueError('trials_unreported: claim requires its selection record')
        selection = selection_record(claim['selection'], base_dir=root, _inputs=_inputs, regime=regime)
        if 'n_trials' not in claim or type(claim['n_trials']) is not int or claim['n_trials'] != selection['n_trials']:
            raise ValueError('trials_unreported: claim must state the retained N trials')
        result.update(selection)
        if selection['selected_candidate'] is not None:
            from .task_completion import _Inputs
            source = _inputs or _Inputs(root)
            try:
                value = evidence_status._number(source.document(claim['quantity']), claim.get('quantity_pointer', '/value'))
                if value != selection['selected_result_on_confirm']:
                    raise ValueError('selected_confirmation_required: delivered quantity differs from selected confirmation')
                if _inputs is None: source.finish()
            finally:
                if _inputs is None: source.close()
        if 'result' in claim and claim['result'] != selection['selected_result_on_confirm']:
            raise ValueError('selected_confirmation_required: primary claim result differs from selected confirmation')
    return result


def checkin_errors(sections, root, *, kind):
    claims = sections.get('claims', [])
    if type(claims) is dict: claims = claims.get('rows', [])
    if type(claims) is not list: return ['claims must be a named quantity census']
    errors = []
    if root is not None and kind == 'deck':
        from .recipe_ledger import checkin3_errors
        errors.extend(checkin3_errors(sections, root))
        from ravel.validation.residual_decomposition import delivery_errors
        errors.extend(delivery_errors(root))
    must_report = False
    if root is not None and kind == 'deck':
        from .completion_lifecycle import required
        from .state_io import read_json
        path = Path(root) / 'inputs/task_contract.json'
        must_report = required(read_json(path)) if path.exists() else False
    for row in claims:
        if type(row) is not dict: continue
        if must_report or 'quantity' in row or claimed_level(row) is not None:
            if root is None:
                errors.append('certified_requires_validated: local receipt evidence required')
            else:
                try: claim_record(root, row, require_trials=kind == 'deck')
                except (ValueError, OSError, KeyError, TypeError) as exc: errors.append(str(exc))
    if root is not None and kind == 'deck':
        from .completion_disclosure import required
        if required(root):
            try: validate_delivery(root, {'claims': claims, 'disclosure': sections.get('disclosure')})
            except (ValueError, OSError, KeyError, TypeError) as exc: errors.append(str(exc))
    return errors


def validate_delivery(root, document, *, _inputs=None):
    from .task_completion import _Inputs
    from . import completion_disclosure
    observed = _inputs or _Inputs(root); own = _inputs is None
    try:
        claims = document.get('claims')
        if type(claims) is not list or len(claims) > 128: raise ValueError('delivered claim census required')
        block = None
        if completion_disclosure.required(root):
            if document.get('disclosure') is None: raise ValueError('funnel_disclosure_missing: computed research disclosure required')
            block = completion_disclosure.build(root, _inputs=observed)
            if block != document['disclosure']: raise ValueError('disclosure_differs: delivered disclosure differs from current records')
        ids = [r.get('id') for r in claims if type(r) is dict]
        if len(ids) != len(claims) or len(set(ids)) != len(ids): raise ValueError('distinct delivered claims required')
        from .completion_children import ledger
        registered = {str(Path(root).absolute()), *[r['rundir'] for r in ledger(root, observed)]}
        for claim in claims:
            if str(Path(claim.get('rundir', root)).absolute()) not in registered:
                raise ValueError('delivered child quantity must belong to registered parent population')
        records = [claim_record(root, claim, _inputs=observed, regime=(block or {}).get('regime')) for claim in claims]
        result = {'schema_version': 1, 'kind': 'completion-claim-records', 'claims': records, 'disclosure': block,
                  **({'omitted_claims': deepcopy(document['omitted_claims'])} if 'omitted_claims' in document else {})}
        if own: observed.finish()
        return result
    finally:
        if own: observed.close()


def reconcile(root, records, contract, inputs):
    """Current pinned plan declares the claims; a caller cannot invent that side."""
    if 'request_plan' not in contract:
        return
    from .completion_disclosure import _bound
    plan = inputs.document(_bound(contract['request_plan'], inputs, root))
    declared = {row['id']: row for row in plan['claims']}
    delivered = {row['id']: row for row in records['claims']}
    for ident, claim in delivered.items():
        if ident not in declared: raise ValueError('new_checkin1_required: new delivered claim')
        original = declared[ident]
        for field in ('kind', 'level', 'statistic', 'comparison', 'basis_declared'):
            if field in claim and claim[field] != original[field]:
                # A subset of the original basis is weaker, with a located
                # deviation and current parent review. Adding a basis is new.
                if field == 'basis_declared' and set(claim[field]) < set(original[field]):
                    if not claim.get('deviation'): raise ValueError('claim_deviation_required: narrower delivered basis')
                    _, path = inputs.file(claim['deviation'])
                    if path.name != 'DEVIATIONS.md': raise ValueError('claim_deviation_required: recorded DEVIATIONS.md')
                else:
                    raise ValueError('new_checkin1_required: delivered ' + field + ' differs from approved plan')
    if set(declared) - set(delivered):
        omitted = records.get('omitted_claims')
        if type(omitted) is not list or {row.get('id') for row in omitted} != set(declared) - set(delivered):
            raise ValueError('claim_deviation_required: omitted declared claims require a located boundary')
        for row in omitted:
            boundary = inputs.document(row['boundary'])
            if boundary.get('kind') not in ('task-boundary', 'held-node') or boundary.get('claim_id') != row['id'] or not boundary.get('reason'):
                raise ValueError('claim_deviation_required: exact omitted-claim boundary required')
            _, path = inputs.file(boundary['deviation'])
            if path.name != 'DEVIATIONS.md': raise ValueError('claim_deviation_required: recorded DEVIATIONS.md')


def render(records):
    """The report renderer includes the exact computed records, without a vote."""
    import json
    if records is None: return ''
    text = '\nDelivered claim evidence\n\n| Claim | N trials | Selected confirmation | Optimistic select | Evidence |\n| --- | --- | --- | --- | --- |\n'
    for row in records['claims']:
        values = (row['id'], row['n_trials'], row['selected_result_on_confirm'],
                  row['best_of_n_select']['value'], row['evidence_status']['state'])
        text += '| ' + ' | '.join(str(v).replace('|', '\\|') for v in values) + ' |\n'
    if records.get('disclosure') is not None:
        text += '\nResearch disclosure\n\n```json\n' + json.dumps(records['disclosure'], sort_keys=True, indent=2, allow_nan=False) + '\n```\n'
    return text


def require_manuscript_disclosure(root, reviewed):
    from . import completion_disclosure
    if not completion_disclosure.required(root): return
    block = completion_disclosure.build(root)
    quantitative = reviewed.get('quantitative_report')
    records = ((quantitative or {}).get('task_completion') or {}).get('claim_records')
    if records is None or records.get('disclosure') != block:
        raise ValueError('funnel_disclosure_missing: manuscript must carry the current computed quantitative disclosure')
    rendered = render(records)
    if rendered not in reviewed['report_text']:
        raise ValueError('funnel_disclosure_missing: manuscript text omits computed funnel and claim evidence')
