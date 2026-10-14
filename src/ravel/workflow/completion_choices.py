"""Computed CHECK-IN 3 census of retained RDJ choices and adapter defaults."""
from copy import deepcopy
from pathlib import Path
from . import candidate_experiments as ce


def _references(value):
    if type(value) is dict:
        if 'rdj_receipt' in value:
            yield value
        for key, item in value.items():
            if key != 'rdj_receipt': yield from _references(item)
    elif type(value) is list:
        for item in value: yield from _references(item)


def census(roots, inputs):
    result = []; seen = set()
    for root in roots:
        root = Path(root)
        for folder in ('inputs', 'research'):
            paths = inputs.population(root / folder, '*.json')
            if len(paths) > 128: raise ValueError('choice census exceeds128 documents per root')
            for path in paths:
                document = inputs.document(inputs.capture(path))
                for row in _references(document):
                    pin = row['rdj_receipt']
                    # Optional not-yet-decided stages are not adopted choices.
                    if pin is None: continue
                    from .completion_disclosure import _bound
                    pin = _bound(pin, inputs, root)
                    receipt = inputs.document(pin)
                    if (receipt.get('kind') != 'rdj-receipt' or receipt.get('schema_version') != 1
                            or receipt.get('outcome') != 'authorize' or receipt.get('class') not in {'R0', 'R1', 'R2', 'R3'}
                            or receipt.get('open_a_findings') != 0 or receipt.get('unresolved_branches') != 0):
                        raise ValueError('current closed RDJ authorization required for CI3 choice')
                    action = {k: v for k, v in row.items() if k != 'rdj_receipt'}
                    if receipt.get('action_digest') != ce.digest(action):
                        raise ValueError('RDJ choice differs from its authorized action')
                    case = inputs.document(_bound(receipt['case'], inputs, root))
                    if case.get('schema_version') != 2 or receipt.get('case_sha256') != receipt['case']['sha256']:
                        raise ValueError('RDJ choice requires its pinned v2 case')
                    canonical = inputs.canonical(pin)
                    key = (canonical['path'], canonical['sha256'])
                    if key not in seen:
                        seen.add(key)
                        result.append({'choice': deepcopy(action), 'rdj_receipt': canonical,
                                       'kind': 'physics_critical_choice'})
        from ravel.validation.intake_records import load_delegated_defaults, DELEGATED_DEFAULTS_PATH
        path = root / DELEGATED_DEFAULTS_PATH
        if path.exists():
            inputs.capture(path)
            contract_path = root / 'inputs/task_contract.json'
            contract = inputs.document(inputs.capture(contract_path)) if contract_path.exists() else None
            record, errors = load_delegated_defaults(root, contract)
            if errors: raise ValueError('invalid adopted defaults: ' + '; '.join(errors))
            for row in (record or {}).get('entries', []):
                result.append({'choice': deepcopy(row), 'rdj_receipt': None, 'kind': 'adopted_adapter_default'})
    return result


def checkin_errors(sections, root):
    from .task_completion import _Inputs
    from .completion_children import ledger
    inputs = _Inputs(root)
    try:
        children = ledger(root, inputs)
        roots = [Path(root), *[Path(r['rundir']) for r in children]]
        wanted = census(list(dict.fromkeys(roots)), inputs)
        # Retained contracts already have an exact, validated adopted_defaults
        # census. New parents use the unified interface; RDJ choices always do.
        from .completion_lifecycle import required
        contract_path = Path(root) / 'inputs/task_contract.json'
        epoch = required(inputs.document(inputs.capture(contract_path))) if contract_path.exists() else False
        legacy_defaults = (not epoch and sections.get('ci3_list') is None
                          and all(row['kind'] == 'adopted_adapter_default' for row in wanted))
        inputs.finish()
        if wanted and not legacy_defaults and sections.get('ci3_list') != wanted:
            return ['CHECK-IN 3 must list every RDJ-justified choice and adopted adapter default in ci3_list']
        return []
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return ['CHECK-IN 3 choice census: ' + str(exc)]
    finally: inputs.close()
