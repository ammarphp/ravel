"""Mutation adequacy: each mechanism, inner guard and switch closure, disabled, fails a case.

For every required id the registered mutations are applied one at a time in a fresh case
environment, and the named catching cases are run. At least one must fail on its oracle (an
assertion or a failed ``pytest.raises``). The oracle is the case's own expectation and is never
patched; only the mechanism is.
"""
from __future__ import annotations

import importlib
from contextlib import nullcontext
from pathlib import Path

import pytest

import nc_cases
import nc_mutations
from nc_env import Env

REQUIRED = ([f'M{n:02d}' for n in range(1, 30)] + [f'G{n:02d}' for n in range(1, 15)]
            + [f'SW{n:02d}' for n in range(1, 42)])
ORACLE_FAILURES = (AssertionError, pytest.fail.Exception)


def _load_cases():
    for path in sorted(Path(__file__).resolve().parent.glob('test_nc_*.py')):
        if path.stem not in ('test_nc_bindings', 'test_nc_mutation_adequacy'):
            importlib.import_module(path.stem)


_load_cases()


def _case(identifier):
    """``(case, row)``: a bespoke case by row id or name, or a parameterized one as ``name[row]``."""
    name, _, row = identifier.partition('[')
    row = row.rstrip(']') or None
    entry = nc_cases.CASES.get(name) if row is None else None
    if entry is None:
        matches = {id(c): c for c in nc_cases.CASES.values() if c.name == name}
        entry = next(iter(matches.values())) if len(matches) == 1 else None
    if entry is None:
        raise LookupError(f'no registered case {identifier!r}')
    if (row is None) != (entry.dimension is None):
        raise LookupError(f'{identifier!r}: a parameterized case is named with its row, a bespoke case without')
    return entry, row


def _run(case, mutation, tmp_path_factory, row=None):
    """Run the control or a disabled variant; unrelated errors never count as detection."""
    patch = pytest.MonkeyPatch()
    label = mutation.mechanism if mutation else 'control'
    env = Env(tmp_path_factory.mktemp(f'mut-{label}-{case.name[:40]}'), patch)
    try:
        env.enter_domain()
        with mutation.applied(patch) if mutation else nullcontext():
            case.func(env) if row is None else case.func(env, row=row)
    except ORACLE_FAILURES:
        return 'caught'
    except pytest.skip.Exception as exc:
        return f'skipped: {exc}'
    except Exception as exc:  # an error is not an oracle failure
        return f'error: {type(exc).__name__}: {exc}'
    finally:
        try:
            env.close()
        finally:
            patch.undo()
    return 'passed'


def test_every_required_mechanism_has_a_registered_mutation():
    missing = [identifier for identifier in REQUIRED if identifier not in nc_mutations.MUTATIONS]
    assert not missing, f'mechanisms, guards or switches without a mutation: {missing}'


def test_a_peer_fake_variant_never_establishes_mechanism_adequacy():
    peer = nc_mutations.Mutation('M99', 'nc_contract:FakeLedger.gate', lambda original: original, ('R01',),
                                 binding=nc_mutations.PEER)
    installed = nc_mutations.Mutation('M99', 'nc_contract:FakeLedger.gate', lambda original: original, ('R01',))
    real = nc_mutations.Mutation('M99', 'ravel.controller.ledger:gate', lambda original: original, ('R01',),
                                 binding=nc_mutations.CONTROLLER)
    for integrated in (False, True):
        assert _adequacy_variants([peer], integrated=integrated) == []
    assert _adequacy_variants([peer, installed, real], integrated=False) == [installed]
    assert _adequacy_variants([peer, installed, real], integrated=True) == [installed, real]


def _adequacy_variants(mutations, *, integrated):
    """The variants that can establish a mechanism's adequacy: installed ones, and controller ones once
    the controller is installed. A peer-fake variant disables a test double, never the mechanism."""
    return [m for m in mutations if m.binding == nc_mutations.INSTALLED
            or m.binding == nc_mutations.CONTROLLER and integrated]


def _require_detection(mutation, tmp_path_factory):
    """All named controls pass before any disabled variant can establish detection."""
    assert mutation.cases, f'{mutation!r}: no catching cases are registered'
    outcomes = {}
    runnable = []
    for identifier_case in mutation.cases:
        case, row = _case(identifier_case)
        if row in nc_cases.withheld_rows():
            continue  # a release withholds this case's operation; its other named cases catch the mutation
        control = _run(case, None, tmp_path_factory, row)
        if control.startswith('skipped: ' + nc_cases.SANDBOX_BLOCKED):
            outcomes[identifier_case] = control
            continue
        assert control == 'passed', f'{mutation!r}: unmodified case {identifier_case} is not passing: {control}'
        runnable.append((identifier_case, case, row))
    for identifier_case, case, row in runnable:
        outcomes[identifier_case] = _run(case, mutation, tmp_path_factory, row)
        if outcomes[identifier_case] == 'caught':
            break
    if not any(value == 'caught' for value in outcomes.values()):
        if all(value.startswith('skipped: ' + nc_cases.SANDBOX_BLOCKED) for value in outcomes.values()):
            pytest.skip(f'{nc_cases.SANDBOX_BLOCKED} every catching case of {mutation!r} needs OS confinement')
        pytest.fail(f'{mutation!r} disabled {mutation.mechanism} and no case failed on its oracle: {outcomes}')


@pytest.mark.parametrize('identifier', REQUIRED)
def test_disabling_the_mechanism_fails_at_least_one_case(identifier, tmp_path_factory):
    mutations = nc_mutations.MUTATIONS.get(identifier)
    if not mutations:
        pytest.fail(f'{identifier} has no registered mutation')
    runnable = _adequacy_variants(mutations, integrated=nc_cases.controller_installed())
    if not runnable:
        pytest.skip(f'{nc_cases.PENDING_INTEGRATION} no installed variant of {identifier}; '
                    'its controller variants run once the controller is installed')
    for mutation in runnable:
        _require_detection(mutation, tmp_path_factory)


PEER_MUTATIONS = [m for mutations in nc_mutations.MUTATIONS.values() for m in mutations
                  if m.binding == nc_mutations.PEER]


@pytest.mark.parametrize('mutation', PEER_MUTATIONS,
                         ids=[f'{m.mechanism}-{m.targets[0]}-{"-".join(m.cases)}' for m in PEER_MUTATIONS])
def test_a_disabled_peer_fake_is_caught_and_its_mechanism_keeps_a_controller_variant(mutation, tmp_path_factory):
    """Harness self-check of the explicit peer fakes, reported apart from mechanism adequacy.

    Before integration the peer cases must notice their disabled fake, else their refusals are
    vacuous. The mechanism a fake stands in for keeps a controller variant, which
    ``test_disabling_the_mechanism_fails_at_least_one_case`` requires once the controller is
    installed; from then on the fakes are no longer reached.
    """
    assert any(m.binding == nc_mutations.CONTROLLER for m in nc_mutations.MUTATIONS[mutation.mechanism]), (
        f'{mutation!r}: a peer fake stands in for {mutation.mechanism}, which has no controller variant')
    if nc_cases.controller_installed():
        return
    _require_detection(mutation, tmp_path_factory)
