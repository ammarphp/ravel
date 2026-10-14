"""Cheapest sufficient scientific method: records, disclosure and launch admission."""
from __future__ import annotations

from importlib.resources import files
import json
import math
from pathlib import Path

from .state_io import read_json

DECISION_PATH = 'inputs/method-decision.json'
RESOURCE_FIELDS = ('wall_hours', 'cpu_hours', 'disk_gb', 'events', 'model_calls')


def load_ladders() -> dict:
    return json.loads(files('ravel').joinpath('data/methods/ladders.json').read_text())


def validate_method_decision(record: dict, *, ladders=None) -> list[str]:
    """Return structural and scientific-choice errors; never infer missing evidence."""
    from jsonschema import Draft202012Validator  # only when a decision is validated; intake runs without it
    schema = json.loads(files('ravel').joinpath('data/methods/method-decision.schema.json').read_text())
    errors = [f"{'.'.join(map(str, e.absolute_path)) or 'record'}: {e.message}"
              for e in Draft202012Validator(schema).iter_errors(record)]
    if errors:
        return errors
    indexes = [('schema_version', record['schema_version']), ('selected.rung', record['selected']['rung'])]
    indexes += [(f'alternatives.{i}.rung', row['rung']) for i, row in enumerate(record['alternatives'])]
    errors += [f'{name} must be an exact integer' for name, value in indexes if type(value) is not int]
    if errors:
        return errors
    for section, fields in ((record['cost_forecast'], RESOURCE_FIELDS),
                            (record['sufficiency'], ('value',))):
        for field in fields:
            value = section[field]
            if value is not None:
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    errors.append(f'{field} must be finite or null')
    pilot = record['cost_forecast'].get('bounded_pilot')
    if pilot is not None:
        try:
            finite = math.isfinite(pilot['max_wall_hours'])
        except OverflowError:
            finite = False
        if not finite:
            errors.append('bounded_pilot.max_wall_hours must be finite')
    family = record['family']
    ladder = (load_ladders() if ladders is None else ladders).get(family)
    if not isinstance(ladder, list) or not ladder:
        return errors + [f'no method ladder for {family}']
    selected = record['selected']
    if selected['rung'] >= len(ladder) or ladder[selected['rung']] != selected['method']:
        errors.append('selected method must match its family ladder rung')
    explicit = record['explicit_request']
    if explicit['requested'] and not explicit['quote']:
        errors.append('explicit request requires the verbatim user quote')
    rows = {}
    for alternative in record['alternatives']:
        rung = alternative['rung']
        if rung in rows:
            errors.append(f'duplicate alternative rung {rung}')
        rows[rung] = alternative
        if rung >= len(ladder) or ladder[rung] != alternative['method']:
            errors.append(f'alternative rung {rung} must match its family ladder method')
        if alternative['status'] == 'selected' and rung != selected['rung']:
            errors.append('only the selected rung may have selected status')
        if alternative['status'] in ('insufficient', 'unavailable') and not alternative['evidence']:
            errors.append(f'alternative rung {rung} requires evidence for {alternative["status"]}')
    for rung in range(min(selected['rung'], len(ladder))):
        if rung not in rows:
            errors.append(f'missing lower rung {rung} ({ladder[rung]}) in alternatives')
        elif rows[rung]['status'] == 'selected':
            errors.append(f'lower rung {rung} cannot be selected')
        elif rows[rung]['status'] == 'not_checked' and not (explicit['requested'] and explicit['quote']):
            errors.append(f'lower rung {rung} is not_checked; escalation requires an explicit user request with quote')
    sufficiency = record['sufficiency']
    if sufficiency['kind'] in ('relative_uncertainty', 'absolute_uncertainty'):
        if sufficiency['value'] is None or sufficiency['value'] <= 0:
            errors.append('numerical uncertainty requires a positive value')
        if sufficiency['source_text'] is None:
            errors.append('numerical uncertainty requires source_text; do not invent precision')
    return errors


def escalation_allowed(record: dict) -> tuple[bool, str]:
    errors = validate_method_decision(record)
    if errors:
        return False, '; '.join(errors)
    cost = record['cost_forecast']
    ladder = load_ladders()[record['family']]
    if (cost['status'] in ('unknown', 'uncalibrated') and record['selected']['rung'] >= len(ladder) - 2
            and not (cost.get('bounded_pilot') or cost.get('physicist_signoff'))):
        return False, 'Top-two-rung cost is unknown or uncalibrated; record a bounded pilot or physicist sign-off.'
    return True, 'The method meets the recorded requirement and every cheaper method is accounted for.'


def render_checkin_section(record: dict) -> str:
    """Plain-language Markdown, with unknown resource costs kept explicit."""
    errors = validate_method_decision(record)
    if errors:
        raise ValueError('; '.join(errors))
    selected = record['selected']
    cost = record['cost_forecast']
    lines = ['### Method decision', f'Required output: {record["required_output"]}',
             f'Chosen method: {selected["method"].replace("_", " ")} (`{selected["method"]}`, rung {selected["rung"]}).',
             f'Sufficiency: {record["sufficiency"]["kind"].replace("_", " ")}; domain: {record["validity_domain"]}.']
    if record['sufficiency']['value'] is not None:
        lines.append(f'Required precision: {record["sufficiency"]["value"]} {record["sufficiency"]["unit"] or ""}.')
    for row in sorted(record['alternatives'], key=lambda r: r['rung']):
        if row['rung'] < selected['rung']:
            lines.append(f'Cheaper method {row["method"].replace("_", " ")} (`{row["method"]}`): {row["status"]}. {row["reason"]} '
                         + ('Evidence: ' + ', '.join(row['evidence']) + '.' if row['evidence'] else ''))
    if record['explicit_request']['requested']:
        lines.append(f'Explicit user request: {record["explicit_request"]["quote"]}')
    lines += [f'Cost forecast status: {cost["status"]}. Basis: {cost["basis"]}',
              'Forecast: ' + '; '.join(f'{field.replace("_", " ")}: {cost[field] if cost[field] is not None else "unknown"}'
                                      for field in RESOURCE_FIELDS) + '.',
              f'Stop when: {record["stopping_criterion"]}',
              _decision_authority(record['provenance']['authority'])]
    allowed, reason = escalation_allowed(record)
    lines.append(f'Escalation {"allowed" if allowed else "refused"}: {reason}')
    return '\n\n'.join(lines)


def _decision_authority(declared):
    # The record's author declares this label; nothing here evidences a person.
    if declared in ('human_operator', 'human_relayed'):
        return ('Decision authority: declared by the record author, unverified; '
                'the CHECK-IN 1 approval receipt records the evidenced authority.')
    return f'Decision authority: {declared}.'


def launch_errors(rundir, required_plan) -> list[str]:
    """Fail closed for full/scan; light routes remain outside this gate."""
    if required_plan not in ('full', 'scan'):
        return []
    path = Path(rundir) / DECISION_PATH
    try:
        allowed, reason = escalation_allowed(read_json(path))
        if allowed:
            return []
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        reason = str(exc)
    return [f'Scientific {required_plan} launch refused: {reason} Write a schema_version 1 method decision to {path}: '
            'state the requested output and precision in the user\'s words, select the cheapest sufficient family rung, '
            'record every cheaper rung with its reason and evidence, cost forecast and stopping criterion; '
            'for unknown or uncalibrated top-two-rung cost record bounded_pilot or physicist_signoff. '
            f'Run `ravel method-decision --rundir {Path(rundir)}` to render CHECK-IN 1, then approve the current inputs before launch. Nothing was started.']


def scientific_plan(rundir, required_plan=None, *, spec=None):
    """Read volume from the approved route, never from a backend location."""
    if required_plan is not None and required_plan != 'science':
        return required_plan
    # Engineering test-domain leases have no scientific directory. The backend
    # still verifies their lease binding; no full/scan requirement is downgraded.
    if rundir is None and spec is None:
        if required_plan == 'science':
            raise ValueError('a scientific launch requirement needs its run directory; nothing was started')
        return None
    root = Path(rundir)
    if spec is None and (root / 'inputs/science.json').exists():
        spec = read_json(root / 'inputs/science.json')
    if spec is not None:
        if spec.get('mode') in ('literal-calculation', 'published-summary', 'source-tables', 'manuscript-build',
                               'task-completion-context', 'ntuple-inventory', 'scientific-delivery'):
            return 'none'
        # A scientific adapter computation is a full operation, including the
        # legacy route. A zero-compute parent or placement cannot downgrade it.
        return 'full'
    for relative in ('inputs/task_contract.json', 'inputs/native_execution_plan.json', 'inputs/checkin1_approval.json'):
        path = root / relative
        if path.exists():
            document = read_json(path)
            plan = document.get('compute_plan', document.get('approved_plan'))
            if plan in ('none', 'dry', 'smoke', 'full', 'scan'):
                return plan
    return required_plan


def require_launch(rundir, required_plan=None, *, spec=None):
    errors = launch_errors(rundir, scientific_plan(rundir, required_plan, spec=spec))
    if errors:
        raise ValueError('; '.join(errors))


def checkin_section(context):
    """CHECK-IN registry seam; the input file is the canonical decision."""
    base = context.get('rundir') or context.get('base_dir')
    record = context.get('method_decision')
    if (context.get('rundir') is not None or 'method_decision' not in context) and base is not None and (Path(base) / DECISION_PATH).exists():
        record = read_json(Path(base) / DECISION_PATH)
    if record is None:
        return None
    text = render_checkin_section(record)
    contract = context.get('contract') or {}
    spec = context.get('spec') or {}
    ceiling = context.get('approved_ceiling')
    if ceiling is None:
        seconds = (contract.get('operation_resources') or {}).get('max_seconds', spec.get('max_seconds'))
        ceiling = {'wall_hours': seconds / 3600} if seconds is not None else {}
    lines = []
    for field in RESOURCE_FIELDS:
        maximum = ceiling.get(field)
        forecast = record['cost_forecast'][field]
        status = ('unknown' if maximum is None or forecast is None or record['cost_forecast']['status'] in ('unknown', 'uncalibrated')
                  else 'within' if forecast <= maximum else 'exceeds')
        lines.append(f'{field.replace("_", " ")}: forecast {forecast if forecast is not None else "unknown"}; '
                     f'approved ceiling {maximum if maximum is not None else "not recorded"}; status {status}.')
    return text + '\n\nForecast against the approved ceiling (before approval, the proposed ceiling):\n\n' + '\n\n'.join(lines)


def refresh_checkin(rundir):
    """Materialize the current decision before approval; retain the existing plan."""
    from .state_io import atomic_json
    from ravel.validation.validate_checkin import with_registered_sections
    root = Path(rundir).resolve()
    record = read_json(root / DECISION_PATH)
    errors = validate_method_decision(record)
    if errors:
        raise ValueError('; '.join(errors))
    document = read_json(root / 'inputs/checkin1.json')
    if document.get('kind') != 'checkin1':
        raise ValueError('method disclosure requires an existing CHECK-IN 1')
    document['sections'].pop('method_decision', None)
    spec = read_json(root / 'inputs/science.json') if (root / 'inputs/science.json').exists() else None
    result = with_registered_sections(document, root, context={'spec': spec, 'rundir': root})
    atomic_json(root / 'inputs/checkin1.json', result)
    companion = root / 'CHECKIN1.md'
    text = companion.read_text() if companion.exists() else '# CHECK-IN 1\n'
    marker = '\n<!-- method-decision -->\n'
    text = text.split(marker)[0]
    companion.write_text(text.rstrip() + '\n' + marker + result['sections']['method_decision'] + '\n')
    return result


def record_machine_decision(rundir, record, *, authority, refresh=True):
    """Record an explicit, admitted machine choice without inventing a method.

    Callers supply the complete scientific decision and cost evidence. Existing
    different decisions are preserved for review rather than overwritten.
    """
    from copy import deepcopy
    from .state_io import atomic_json
    if authority not in ('scripted_experiment', 'delegated_machine'):
        raise ValueError('method recording requires an explicit machine authority')
    value = deepcopy(record)
    if isinstance(value, dict) and isinstance(value.get('provenance'), dict):
        value['provenance']['authority'] = authority
    allowed, reason = escalation_allowed(value)
    if not allowed:
        raise ValueError(reason)
    root = Path(rundir)
    path = root / DECISION_PATH
    if path.exists() or path.is_symlink():
        if read_json(path) != value:
            raise FileExistsError(f'preserve the existing method decision: {path}')
    else:
        atomic_json(path, value)
    if refresh and (root / 'inputs/checkin1.json').is_file():
        refresh_checkin(root)
    return path


def record_validation_decision(rundir, *, required_output, max_seconds, evidence, operation, authority):
    """Choose a bounded prospective operation for an internal validation request.

    This choice covers observing current execution behavior. It is not a method
    selector for a physics request, and it grants no execution approval.
    """
    import hashlib
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('bounded validation needs a positive finite time ceiling')
    record = {
        'schema_version': 1,
        'request_digest': hashlib.sha256(required_output.encode('utf8')).hexdigest(),
        'obligation_ids': ['validation-output'], 'required_output': required_output,
        'sufficiency': {'kind': 'qualitative', 'value': None, 'unit': None, 'source_text': required_output},
        'validity_domain': 'The supplied bounded validation specification and current operation',
        'allowed_approximations': [], 'family': 'open_research',
        'selected': {'method': 'small_prospective_experiment', 'rung': 2, 'operation': operation},
        'alternatives': [
            {'method': 'source_assessment', 'rung': 0, 'status': 'insufficient',
             'reason': 'Source reading cannot establish the executed operation behavior.', 'evidence': list(evidence)},
            {'method': 'analytic_discriminator_or_reuse', 'rung': 1, 'status': 'insufficient',
             'reason': 'An analytic calculation or retained result does not execute the requested current operation.',
             'evidence': list(evidence)}],
        'explicit_request': {'requested': False, 'quote': None},
        'cost_forecast': {'status': 'uncalibrated', **{field: None for field in RESOURCE_FIELDS},
            'basis': 'A declared time ceiling bounds one validation attempt; actual cost is uncalibrated.',
            'bounded_pilot': {'max_wall_hours': max_seconds / 3600, 'evidence': list(evidence)}},
        'stopping_criterion': 'Stop after the one bounded attempt and retain its success or failure.',
        'provenance': {'author_role': 'coordinator', 'transport': 'internal',
            'authority': authority, 'reviewed_by': []}}
    return record_machine_decision(rundir, record, authority=authority)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Validate and render the method decision into CHECK-IN 1 before approval.')
    parser.add_argument('--rundir', required=True)
    args = parser.parse_args(argv)
    refresh_checkin(args.rundir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
