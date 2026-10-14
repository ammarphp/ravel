"""Read-only decision gate. Providers inspect evidence; they never acquire it."""
from __future__ import annotations
from dataclasses import dataclass
from importlib import import_module, util
from importlib.resources import files
from pathlib import Path
import json

GATES = ('approve_plan', 'launch', 'failed_stage_feedback', 'checkin2_accept', 'correction', 'deviation',
         'research_choice', 'delivery', 'final_task', 'report_integrity', 'export', 'unblind', 'spend_above_ceiling')
EPOCH_TWO_ONLY = frozenset({'unblind', 'spend_above_ceiling'})


@dataclass(frozen=True)
class GateError:
    code: str
    gate: str
    provider: str
    message: str
    fix: str
    pins: tuple[str, ...] = ()


def _registry():
    return json.loads(files('ravel').joinpath('data/gates/providers.json').read_text())


def providers(gate: str) -> list[dict]:
    if gate not in GATES:
        raise ValueError('unknown decision gate: ' + gate)
    result = []
    for row in _registry()['providers']:
        if '*' not in row['gates'] and gate not in row['gates']:
            continue
        active = row['active']
        reason = None if active else 'disabled by provider registry'
        if active and util.find_spec(row['module']) is None:
            active, reason = False, 'provider module is not installed'
        missing_function = False
        if active:
            try:
                module = import_module(row['module'])
            except ImportError:
                module = None  # check() reports the import failure as invalid provider evidence.
            if module is not None and not callable(getattr(module, row['function'], None)):
                active, reason, missing_function = False, f"provider module lacks its registered function {row['module']}.{row['function']}", True
        result.append({**row, 'active': active, 'reason': reason, 'missing_function': missing_function})
    return result


def _facts(rundir: Path) -> dict:
    """The run's typed facts.

    A run that keeps its contract at the run root, the layout before ``inputs/``, predates
    the agent layer: such a contract is epoch one and keeps its existing gate decisions.
    """
    from .review_points import _facts as typed_facts
    legacy = rundir / 'task_contract.json'
    if (rundir / 'inputs/task_contract.json').exists() or not legacy.is_file():
        return typed_facts(rundir)
    contract = json.loads(legacy.read_bytes())
    if not isinstance(contract, dict):
        raise ValueError('task contract must be an object')
    if type(contract.get('agent_layer_epoch', 1)) is not int or contract.get('agent_layer_epoch', 1) != 1:
        raise ValueError('a contract at the run root cannot declare agent_layer_epoch two; use inputs/task_contract.json')
    return {'agent_layer_epoch': 1}


def check(rundir: Path, gate: str, action: dict) -> list[GateError]:
    """Concatenate active provider errors in registry order, without side effects.

    A missing required provider is a refusal, not a successful empty check.
    Epoch-one contracts retain their existing gate decisions.
    """
    rows = providers(gate)
    if not isinstance(action, dict):
        raise ValueError('gate action must be an object')
    try:
        facts = _facts(Path(rundir))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = [GateError('gate_inputs_invalid', gate, 'review_points', str(exc),
                            'Restore the pinned contract and plan.', ('inputs:contract-plan',))]
        try:
            from .review_points import invalid_input_diagnostics
            errors.extend(invalid_input_diagnostics(rundir, gate, action))
        except Exception:
            pass  # Diagnostics must never replace or suppress the primary refusal.
        return errors
    if facts.get('agent_layer_epoch') != 2:
        # These gates have no epoch-one decision to preserve; an empty list would approve them.
        if gate in EPOCH_TWO_ONLY:
            return [GateError('epoch_gate_unsupported', gate, 'decision_gate',
                              'This gate has no epoch-one decision; an older contract cannot pass it.',
                              'Obtain the decision through the run\'s human approval route.', ('contract:agent_layer_epoch',))]
        return []
    registry = _registry()
    required = set(registry['required_providers'].get('*', []))
    required.update(registry['required_providers'].get(gate, []))
    for scope in registry.get('required_scopes', []):
        if action.get('scope') == scope['scope'] and gate in scope['gates']:
            required.update(scope['providers'])
    result = []
    if gate == 'checkin2_accept':
        try:
            from .review_points import derive
            from .rdj_loop import compute_class
            # Comparison/certificate production is an R2/R3 wiring prerequisite.
            if any(p.get('comparison_required') or p.get('requires_certificate') for p in derive(facts)):
                if compute_class(Path(rundir), gate, action)[0] in {'R2', 'R3'}:
                    required.add('comparison')
        except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
            result.append(GateError('provider_evidence_invalid', gate, 'comparison', str(exc),
                                    'Restore the typed plan and RDJ action.', ('comparison:class-inputs',)))
    seen = set()
    for row in rows:
        name = row['id']; seen.add(name)
        if not row['active']:
            # A registered provider without its function refuses whether or not it is required.
            if name in required or row['missing_function']:
                result.append(GateError('provider_inactive', gate, name, row['reason'],
                    'Install and enable the required provider.', ('provider:' + name,)))
            continue
        try:
            provider = import_module(row['module'])
            errors = getattr(provider, row['function'])(Path(rundir), gate, action)
            for error in errors:
                # Older provider seams predate evidence IDs. Preserve the error and
                # name the exact requested receipt rather than inventing evidence.
                pins = tuple(error.pins) or (f'{name}:{gate}:{action.get("digest", "action")}',)
                result.append(GateError(error.code, error.gate, error.provider, error.message, error.fix, pins))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            result.append(GateError('provider_evidence_invalid', gate, name, str(exc),
                'Repair the named provider evidence.', (f'{name}:{gate}:{action.get("digest", "action")}',)))
    for name in sorted(required - seen):
        result.append(GateError('provider_inactive', gate, name, 'required provider is not registered for this gate',
                               'Register the provider for this gate.', ('provider:' + name,)))
    return result
