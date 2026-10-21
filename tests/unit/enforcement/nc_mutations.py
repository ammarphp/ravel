"""Mutation adequacy: disabling a mechanism must make at least one of its cases fail.

``MUTATIONS`` maps each mechanism (M01-M28), inner guard (G01-G14) and switch closure (SW01-SW41)
to the code it disables. A mutation replaces one attribute (``module:attribute``) with a disabled
variant built from the original (``replacement(original) -> object``); it never touches a case's
oracle. ``test_nc_mutation_adequacy`` runs the named catching cases in fresh environments under the
mutation and requires an oracle failure (an ``AssertionError`` or a failed ``pytest.raises``) from
at least one of them; an unrelated error does not count as detection.

A mutation on ``ravel.controller`` (or on a module a controller package changes) is a CONTROLLER
mutation: before integration it ends with the declared ``pending-integration:`` skip, after
integration it must run.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib

INSTALLED = 'installed'
CONTROLLER = 'controller'
PEER = 'peer-fake'


class Mutation:
    def __init__(self, mechanism, target, replacement, cases, *, binding=INSTALLED, why=''):
        self.mechanism = mechanism
        self.target = target
        self.replacement = replacement
        self.cases = tuple(cases)
        self.binding = binding
        self.why = why

    def __repr__(self):
        return f'Mutation({self.mechanism} -> {", ".join(self.targets)})'

    @property
    def targets(self):
        """Every name the mechanism is reached by: a function re-exported by a package is patched twice."""
        return (self.target,) if isinstance(self.target, str) else tuple(self.target)

    @staticmethod
    def resolve(target):
        module_name, _, attribute = target.partition(':')
        owner = importlib.import_module(module_name)
        *path, name = attribute.split('.')
        for part in path:
            owner = getattr(owner, part)
        return owner, name

    @contextmanager
    def applied(self, patch):
        resolved = [self.resolve(target) for target in self.targets]
        originals = [getattr(owner, name) for owner, name in resolved]
        replacement = self.replacement(originals[0])
        for owner, name in resolved:
            patch.setattr(owner, name, replacement)
        try:
            yield
        finally:
            for (owner, name), original in zip(resolved, originals):
                patch.setattr(owner, name, original)


def returns(value):
    """A disabled check that answers ``value`` whatever it is asked."""
    def build(original):
        def disabled(*args, **kwargs):
            return value() if callable(value) else value
        disabled.__wrapped__ = original
        return disabled
    return build


def passes_through(transform):
    """A variant that calls the original and transforms its answer (for example, drops refusals)."""
    def build(original):
        def disabled(*args, **kwargs):
            return transform(original(*args, **kwargs), *args, **kwargs)
        disabled.__wrapped__ = original
        return disabled
    return build


def constant(value):
    """Replace a module-level constant (a policy table, a frozen set) with ``value``."""
    return lambda original: value


MUTATIONS: dict[str, list[Mutation]] = {}


def register(*mutations):
    for mutation in mutations:
        MUTATIONS.setdefault(mutation.mechanism, []).append(mutation)
    return mutations
