"""What a worker's final record must satisfy before anything it produced is adopted.

- the final record validates against the packet's closed output schema and against the card's
  own output schema in controller form (``toolbelt.validate_final``; M11, CF06);
- the instruction acknowledgement and one checklist row per duty unit check against the
  delivered manifest (``instructions.check_ack``; M13);
- the ``escalation`` field is present and its value is one the card's role may raise (CF01);
- the session is fresh and transport-attested, and the model and effort that ran are the ones
  the card asked for (I05, I08);
- the controller itself runs every runnable ``must_check`` validator of the card and the
  producer's owed reviewer self-checks before an adopted artifact is accepted (M10, I09); a
  check that needs an input the step does not name is inconclusive, which never passes.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .services import StepHold, digest

ESCALATIONS = ('stop', 'checkin_flag', 'decision_block', 'new_experiment_required')
SEVERITY = ('stop', 'decision_block', 'new_experiment_required', 'checkin_flag')
NONE = (None, 'none')


def schema_document(packet, card=None):
    """The closed output schema the packet carries: inline, or a registered output schema id."""
    from ravel.workflow import toolbelt
    schema = (packet or {}).get('schema')
    if type(schema) is dict:
        return deepcopy(schema)
    if type(schema) is str and card is not None:
        try:
            return toolbelt.output_schema({**card, 'output': {**card['output'], 'schema': schema}})
        except (OSError, ValueError, toolbelt.ToolbeltError) as exc:
            raise StepHold('output_schema_unavailable', f'{schema}: {exc}') from None
    raise StepHold('output_schema_unavailable', 'the packet carries no closed output schema')


def schema_errors(record, schema):
    from jsonschema import Draft202012Validator
    return [('/'.join(str(p) for p in e.absolute_path) or '$') + ': ' + e.message
            for e in Draft202012Validator(schema).iter_errors(record)]


def card_schema_errors(card, record, controller_schema):
    """``toolbelt.validate_final`` against the card's output schema in its controller form."""
    from ravel.workflow import toolbelt
    effective = {**card, 'output': {**card['output'], 'schema': controller_schema}}
    try:
        _, errors = toolbelt.validate_final(effective, record)
    except (OSError, ValueError, toolbelt.ToolbeltError) as exc:
        raise StepHold('output_schema_unavailable', f'{controller_schema}: {exc}') from None
    return errors


def escalation(record, card):
    """``(escalations, errors)``: the field is required; each raised value is one the card declares.

    The acknowledging schemas carry a list of ``{kind, statement, evidence, options}``; an empty
    list raises nothing. A bare value or object is read the same way.
    """
    if type(record) is not dict or 'escalation' not in record:
        return [], [{'code': 'escalation_field_missing'}]
    value = record['escalation']
    rows = value if type(value) is list else [value]
    found, errors = [], []
    for item in rows:
        if item in NONE:
            continue
        if type(item) is str:
            item = {'kind': item}
        if type(item) is not dict:
            errors.append({'code': 'escalation_invalid'})
            continue
        kind = item.get('kind', item.get('value', item.get('type')))
        if kind in NONE:
            continue
        if kind not in ESCALATIONS:
            errors.append({'code': 'escalation_invalid', 'value': kind})
        elif kind not in card['escalation']:
            errors.append({'code': 'escalation_not_declared', 'value': kind, 'declared': list(card['escalation'])})
        else:
            statement = item.get('statement', item.get('reason', item.get('detail')))
            found.append({'kind': kind, 'statement': statement if type(statement) is str else None,
                          'evidence': [e for e in item.get('evidence') or () if type(e) is str],
                          'options': [o for o in item.get('options') or () if type(o) is str],
                          'record_sha256': digest(item)})
    return found, errors


def primary(escalations):
    """The escalation the step outcome reports: the most consequential one raised."""
    kinds = {row['kind'] for row in escalations}
    return next((kind for kind in SEVERITY if kind in kinds), None)


def ack_errors(manifest, record, outputs, *, store, session, completion_id=None):
    """``instructions.check_ack`` errors for the delivered manifest (empty when complete)."""
    from .services import module
    instructions = module('instructions')
    if not session or not completion_id:
        return ['manifest: no controller-observed completion']
    with instructions.observed_completion(store, session=session, completion_id=completion_id):
        errors = instructions.check_ack(manifest, record, list(outputs))
    if type(errors) is not list:
        raise StepHold('instruction_ack_unchecked', 'the instruction check returned no error list')
    return [str(e) for e in errors]


def split_ack(errors):
    """``(holding, failing)``: blocked duty rows hold the step; every other fault fails it."""
    holding = [e for e in errors if e.startswith('blocked:')]
    return holding, [e for e in errors if not e.startswith('blocked:')]


# ---- controller-run validators -----------------------------------------------------------

def validator_ids(card):
    """``(runnable must_check ids, reviewer-only ids)`` of the card, owed producer self-checks included."""
    from ravel.workflow import role_registry, review_projection_checks, run_validator_checks
    ids = set(role_registry.resolve_self_checks(card['must_check']))
    if card['independence']['kind'] == 'producer' or card['family'] == 'production':
        ids |= set(role_registry.self_checks(card['id']))
    # A reviewer item has a registered check that computes nothing; it is owed as a reviewer verdict.
    computes = getattr(review_projection_checks, 'computes', None)
    if callable(computes):
        runnable = sorted(i for i in ids if computes(i))
    else:
        runnable = sorted(i for i in ids if i in run_validator_checks.ADAPTERS or i in review_projection_checks.CHECKS)
    return runnable, sorted(ids - set(runnable))


def run_validators(card, step, *, run_dir, scratch, subjects=None, exempt=None, owed=()):
    """Run each runnable validator; ``inconclusive`` and ``failed`` never pass.

    ``subjects`` is given for a reviewer's own step: ``{check id: [{"step", "parameters"}, ...]}``, the inputs the
    approved plan declares for each check on the steps whose results exist (``review_subjects``). A check the step
    does not parameterize itself runs once on each subject. A reviewer's check with no subject in its step, the
    approved plan or the run tree (the validator cannot execute and nothing declares its inputs) is ``inconclusive``
    with the reason ``no_subject`` and what was missing: whatever the review policy makes applicable needs its
    subject. It is ``not_applicable`` only when ``exempt`` names it (``{check id: evidence}``): the review policy
    classified it as not applying to this run, and the evidence cites that stored classification record. Neither is
    ever a pass of a check that ran.

    ``owed`` names the checks a producer's own step runs for its review seats (the union the step graph adds to the
    producer card). Each is decided as its seat decides it: without its own declared inputs it is ``not_applicable``
    only where ``exempt`` cites the review policy's classification, else ``inconclusive`` (``no_subject``).
    """
    runnable, reviewer_only = validator_ids(card)
    # The controller supplies the approved parameters bound to this attempt's adopted bytes (``check_inputs``);
    # without that binding the step's declared ``parameters.check_inputs`` are checked as the plan states them.
    parameters = deepcopy(step['check_inputs'] if 'check_inputs' in step
                          else (step.get('parameters') or {}).get('check_inputs') or {})
    results = []
    reviewed = set(runnable) if subjects is not None else set(owed or ()) & set(runnable)
    for check_id in runnable:
        cited = (exempt or {}).get(check_id)
        if check_id in reviewed and cited and cited.get('reason') and cited.get('evidence'):
            # A fact-derived disposition precedes resolving inapplicable input
            # placeholders. It records no execution and never manufactures a ledger.
            results.append({'check_id': check_id, 'status': 'not_applicable',
                            'reason': 'policy_not_applicable', 'classification': deepcopy(cited)})
            continue
        planned = [] if check_id in parameters or subjects is None else list(subjects.get(check_id) or ())
        for subject in planned or [None]:
            values = parameters if subject is None else {check_id: deepcopy(subject['parameters'])}
            result, executed = _run_check(check_id, values, run_dir=run_dir, scratch=scratch,
                                          step=subject.get('spec', step) if subject is not None else step)
            if subject is not None:
                result['subject'] = subject['step']
            elif check_id in reviewed and not executed and check_id not in parameters:
                missing = result.get('diagnostics') or result.get('reason')
                cited = (exempt or {}).get(check_id)
                result = ({'check_id': check_id, 'status': 'not_applicable', 'reason': 'policy_not_applicable',
                           'classification': deepcopy(cited), 'missing': missing} if cited else
                          {**result, 'status': 'inconclusive', 'reason': 'no_subject', 'missing': missing})
            results.append(result)
    return {'results': results, 'reviewer_items': reviewer_only,
            'passed': all(r['status'] == 'passed' or (r['status'] == 'not_applicable' and r['check_id'] in reviewed)
                          for r in results)}


def _run_input(check_id, parameters, run_dir, scratch):
    """The ordinary adapter input, with a declared sweep's custody path supplied to its facts.

    The original state validator, level, contract and acceptance criteria are unchanged.
    Legacy plans without a declared sweep retain the adapter's canonical-path lookup.
    """
    from ravel.workflow import run_validator_checks as checks

    class BoundInput(checks.RunCheckInput):
        def call(self, function, *args, **kwargs):
            from ravel.validation import validate_run_state
            sweep = parameters.get(check_id, {}).get('sweep')
            if check_id == checks.TRAP_CHECK and sweep is not None and function is validate_run_state.check_trap_sweep:
                args = (*args[:2], {**args[2], 'trap_sweep_path': sweep}, *args[3:])
            census = parameters.get(check_id, {}).get('census')
            if (check_id == checks.CENSUS_CHECK and census is not None
                    and function is validate_run_state.check_resource_census):
                args = (*args[:2], {**args[2], 'resource_census_path': census}, *args[3:])
            target = parameters.get(check_id, {}).get('target')
            if (check_id == checks.FIGURE_CONTRACT_CHECK and target is not None
                    and function is validate_run_state.check_figure_contract):
                self.path(target)
                args = (*args[:2], {**args[2], 'figure_target_path': target}, *args[3:])
            return super().call(function, *args, **kwargs)

    return BoundInput(Path(run_dir), {'check_inputs': parameters}, Path(scratch))



def _run_check(check_id, parameters, *, run_dir, scratch, step=None):
    """``(result row, validator executed)`` of one validator on ``parameters``."""
    from ravel.workflow import review_projection_checks, run_validator_checks
    from ravel.controller.routes.validator_inputs import resolve_inputs
    from ravel.workflow.review_independence import controller_store
    has_sources = any(type(fields) is dict and any(type(value) is dict and 'source' in value
                      for value in fields.values()) for fields in parameters.values())
    try:
        source_store = controller_store(run_dir) if has_sources else None
    except (OSError, ValueError, LookupError):
        source_store = None
    parameters, binding_errors = resolve_inputs(parameters, step or {}, run_dir=run_dir, store=source_store)
    if check_id in binding_errors:
        return {'check_id': check_id, 'status': 'inconclusive', **binding_errors[check_id]}, False
    if check_id in review_projection_checks.ML_RESULT_CHECKS:
        from ravel.workflow.review_independence import controller_store
        value = review_projection_checks.observed_ml_result(
            controller_store(run_dir), parameters.get(check_id), check_id=check_id)
        return {'check_id': check_id, 'status': value['status'], 'result_sha256': digest(value),
                'diagnostics': _short(value.get('diagnostics'))}, True
    if check_id in run_validator_checks.ADAPTERS:
        Path(scratch).mkdir(parents=True, exist_ok=True)
        value = run_validator_checks.run(check_id, _run_input(check_id, parameters, run_dir, scratch))
        executed = bool(value.get('validator_executed'))
        return {'check_id': check_id, 'status': value['status'] if executed else 'inconclusive',
                'result_sha256': digest(value), 'diagnostics': _short(value.get('diagnostics'))}, executed
    named = (parameters.get(check_id) or {}).get('document')
    expected = None
    if type(named) is dict and set(named) == {'path', 'sha256'}:
        expected, named = named['sha256'], named['path']
        if type(expected) is not str:
            return {'check_id': check_id, 'status': 'inconclusive', 'reason': 'validator_input_invalid'}, False
    if type(named) is not str:
        return {'check_id': check_id, 'status': 'inconclusive', 'reason': 'validator_input_missing'}, False
    target = Path(run_dir) / named
    if expected is not None:
        try:
            from ravel.workflow.world_digest import read_bound
            raw, actual = read_bound(run_dir, named)
            if actual != expected:
                raise ValueError('the bound validator document differs from its accepted output')
        except (OSError, ValueError) as exc:
            return {'check_id': check_id, 'status': 'inconclusive', 'reason': 'validator_input_changed',
                    'detail': str(exc)}, False
    try:
        document = json.loads(raw if expected is not None else target.read_bytes())
        value = review_projection_checks.run_check(check_id, document)
        status = value['status']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        value, status = {'error': type(exc).__name__}, 'failed'
    return {'check_id': check_id, 'status': status, 'result_sha256': digest(value), 'document': named}, True


def reviewer(card):
    """Whether ``card`` is a reviewer: its own step's validators apply its constraints to subjects others produced."""
    return card['independence']['kind'] != 'producer' and card['family'] != 'production'


def _short(value):
    text = json.dumps(value, sort_keys=True, default=str) if value is not None else None
    return text[:2000] if text else None
