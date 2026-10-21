"""Read-only decision gate. Providers inspect evidence; they never acquire it.

For a run the controller owns, the gate is stricter: the provider registry is read from the installed package
only and must equal the registry the obligation catalogue pins, so a removed, disabled or repointed provider
refuses every decision; an epoch-one layout never passes; and every decision also requires the obligation-ledger
transition it leads to (``ravel.controller.ledger``). Runs the controller does not own keep their existing decisions.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from importlib import import_module, util
from importlib.resources import files
from pathlib import Path
import json
import os

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


REGISTRY = 'data/gates/providers.json'


def _registry_bytes() -> bytes:
    """The installed provider registry: package data only, never a run tree, the working directory or a variable."""
    return files('ravel').joinpath(REGISTRY).read_bytes()


def _registry():
    return json.loads(_registry_bytes())


def registry_sha256() -> str:
    return hashlib.sha256(_registry_bytes()).hexdigest()


def providers(gate: str) -> list[dict]:
    return _rows(_registry(), gate)


def _rows(registry: dict, gate: str) -> list[dict]:
    if gate not in GATES:
        raise ValueError('unknown decision gate: ' + gate)
    result = []
    for row in registry['providers']:
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
    Epoch-one contracts retain their existing gate decisions, except in runs the controller owns.
    """
    rows = providers(gate)
    if not isinstance(action, dict):
        raise ValueError('gate action must be an object')
    owner = _controller_owner(Path(rundir), gate)
    if isinstance(owner, list):
        return owner
    if owner is not None:
        return _controller_check(Path(rundir), gate, action, owner)
    facts = _facts_or_errors(rundir, gate, action)
    if isinstance(facts, list):
        return facts
    if facts.get('agent_layer_epoch') != 2:
        # These gates have no epoch-one decision to preserve; an empty list would approve them.
        if gate in EPOCH_TWO_ONLY:
            return [GateError('epoch_gate_unsupported', gate, 'decision_gate',
                              'This gate has no epoch-one decision; an older contract cannot pass it.',
                              'Obtain the decision through the run\'s human approval route.', ('contract:agent_layer_epoch',))]
        return []
    return _provider_errors(Path(rundir), gate, action, facts, _registry(), rows)


def _facts_or_errors(rundir, gate: str, action: dict):
    try:
        return _facts(Path(rundir))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = [GateError('gate_inputs_invalid', gate, 'review_points', str(exc),
                            'Restore the pinned contract and plan.', ('inputs:contract-plan',))]
        try:
            from .review_points import invalid_input_diagnostics
            errors.extend(invalid_input_diagnostics(rundir, gate, action))
        except Exception:
            pass  # Diagnostics must never replace or suppress the primary refusal.
        return errors


def _controller_owner(rundir: Path, gate: str):
    """The owning controller run id, None for a run the controller does not own, or the refusal when unknown."""
    try:
        from ravel.controller.store import controller_owned
    except ModuleNotFoundError as exc:
        if exc.name in ('ravel.controller', 'ravel.controller.store'):
            return None  # an install without the controller core owns no run
        return [GateError('controller_ownership_unknown', gate, 'decision_gate', str(exc),
                          'Repair the controller installation before deciding.', ('controller:ownership',))]
    except ImportError as exc:  # a broken controller never makes its runs look legacy
        return [GateError('controller_ownership_unknown', gate, 'decision_gate', str(exc),
                          'Repair the controller installation before deciding.', ('controller:ownership',))]
    try:
        owner = controller_owned(rundir)
    except Exception as exc:  # an ownership question that cannot be answered never falls back to the weaker gate
        return [GateError('controller_ownership_unknown', gate, 'decision_gate', str(exc),
                          'Repair the controller store before deciding.', ('controller:ownership',))]
    if owner is not None and (not isinstance(owner, str) or not owner):
        return [GateError('controller_ownership_unknown', gate, 'decision_gate',
                          f'the controller reported an invalid owner {owner!r}', 'Repair the controller store.',
                          ('controller:ownership',))]
    return owner


RESEARCH_GATE_BINDING = 'research-gate-binding.json'


def _research_scope(rundir: Path, run_id: str):
    """``(campaign, run directory)`` of a research loop scope inside the run's protected store, else None.

    The research controller writes the binding into the loop's graph scope (``research_controller.invoke``); a
    binding outside that run's store, of another run, or naming a campaign outside the run directory is refused.
    """
    path = Path(rundir) / RESEARCH_GATE_BINDING
    if not path.exists() and not path.is_symlink():
        return None
    from ravel.controller.store import RunStore, controller_owned
    store_dir = Path(os.path.realpath(RunStore(run_id).path()))
    if path.is_symlink() or not path.is_file() or not Path(os.path.realpath(rundir)).is_relative_to(store_dir):
        raise ValueError('a research gate binding is read only from the run\'s own protected store')
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict or value.get('kind') != 'research-gate-binding' or value.get('run_id') != run_id:
        raise ValueError('the research gate binding names another run')
    run_dir, campaign = Path(value['run_dir']), Path(value['campaign'])
    if controller_owned(run_dir) != run_id or not Path(os.path.realpath(campaign)).is_relative_to(
            Path(os.path.realpath(run_dir))):
        raise ValueError('the research gate binding names a campaign outside its controller run')
    return campaign, run_dir


def _controller_check(rundir: Path, gate: str, action: dict, run_id: str) -> list[GateError]:
    """The decision for a controller-owned run: pinned installed providers, epoch two only, plus the ledger.

    A research loop scope decides as its campaign's gate does: the research protocol provider on the campaign,
    every other provider and the ledger on the run directory that owns the research request.
    """
    try:
        scope = _research_scope(Path(rundir), run_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [GateError('research_gate_binding_invalid', gate, 'decision_gate', str(exc),
                          'Run the research loop through the controller, which binds its scope.', ('controller:scope',))]
    if scope is not None:
        campaign, run_dir = scope
        from . import research_protocol
        errors = list(research_protocol.gate_errors(campaign, gate, action)) if gate == 'research_choice' else []
        return errors + [e for e in _controller_check(run_dir, gate, action, run_id) if e.provider != 'research_protocol']
    try:
        from ravel.controller import ledger
        catalogue = ledger.load_catalogue()
    except Exception as exc:
        return [GateError('obligation_catalogue_invalid', gate, 'ledger', str(exc),
                          'Reinstall RAVEL; the obligation catalogue is package data.', ('ledger:catalogue',))]
    data = _registry_bytes()
    pinned = catalogue.gate_registry['sha256']
    if hashlib.sha256(data).hexdigest() != pinned:
        return [GateError('provider_registry_unpinned', gate, 'decision_gate',
                          'the installed provider registry differs from the one the obligation catalogue pins; '
                          'a removed, disabled or repointed provider cannot decide a controller run',
                          'Reinstall RAVEL or rebuild the catalogue pins from a reviewed registry.',
                          ('provider:registry', 'ledger:catalogue'))]
    registry = json.loads(data)
    facts = _facts_or_errors(rundir, gate, action)
    if isinstance(facts, list):
        return facts
    if facts.get('agent_layer_epoch') != 2:
        return [GateError('epoch_one_controller_run', gate, 'decision_gate',
                          'a run the controller owns never takes an epoch-one decision',
                          'Keep the contract at inputs/task_contract.json with agent_layer_epoch two.',
                          ('contract:agent_layer_epoch',))]
    errors = _provider_errors(rundir, gate, action, facts, registry, _rows(registry, gate))
    return errors + _ledger_errors(run_id, gate, action)


def _ledger_errors(run_id: str, gate: str, action: dict) -> list[GateError]:
    try:
        from ravel.controller.ledger import gates as ledger_gates
        from ravel.controller.store import RunStore
        store = RunStore(run_id)
        transition, own = ledger_gates.transition_for(store, gate, action)
        unmet = ledger_gates.unmet(store, transition, exclude=own)
    except Exception as exc:
        return [GateError('ledger_unavailable', gate, 'ledger', str(exc),
                          'Restore the controller store; a decision without its ledger refuses.', ('ledger:store',))]
    errors = []
    for row in unmet:
        where = f' at {row["node"]}' if row.get('node') else ''
        errors.append(GateError('ledger_' + row['reason'], gate, 'ledger', row['message'],
                                f'Discharge {row["id"] or row["entry"]}{where} before {transition}.',
                                (f'ledger:{row["entry"]}',)))
    return errors


def _provider_errors(rundir: Path, gate: str, action: dict, facts: dict, registry: dict,
                     rows: list[dict]) -> list[GateError]:
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
