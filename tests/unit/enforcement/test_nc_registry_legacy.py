"""Pinned registry and legacy layouts: data changed after intake, and old layouts, decide nothing new.

The adversary drops a role registration fragment (a new role, a repointed alias) after the run
pinned its registry, or writes a run-root contract to make a controller run look like an epoch-one
legacy run. Oracles are card resolution against the pin and the legacy route's admission and
resume checks; positive controls resolve under the pinned registry and resume the intact run.
No file of the installed package is written: the changed registry is presented in process.
"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _changed_registry(nc, change):
    """The installed registry document as the dropped fragment would make it (in process only)."""
    from ravel.workflow import role_registry
    original = role_registry.registry_document

    def document(*, roles_root=None):
        value = deepcopy(original(roles_root=roles_root))
        change(value)
        return value
    nc.patch.setattr(role_registry, 'registry_document', document)


@case('SW28', binding=CONTROLLER)
def test_SW28_a_registration_dropped_after_intake_changes_nothing_for_the_run(nc):
    cards = require_controller('step.cards')
    from ravel.workflow import role_registry
    pinned = role_registry.registry_sha256()
    card, _, registry = cards.resolve('analysis-author', {'registry_sha256': pinned})  # positive control
    assert registry == pinned and card['id'] == 'analysis-author'

    def repoint(document):
        # A fragment that repoints an existing alias (or adds one) to another registered role.
        alias = next(iter(document['aliases']), 'fictional-alias')
        target = 'physics-critic' if document['aliases'].get(alias) != 'physics-critic' else 'analysis-author'
        document['aliases'][alias] = target
    _changed_registry(nc, repoint)
    with pytest.raises(Exception) as held:
        cards.resolve('analysis-author', {'registry_sha256': pinned})
    assert getattr(held.value, 'reason', '') == 'role_registry_changed', held.value
    with pytest.raises(Exception) as unpinned:
        cards.resolve('analysis-author', {})
    assert getattr(unpinned.value, 'reason', '') == 'role_registry_unpinned'


def _pin_ignored(original):
    def resolve(role, context):
        from ravel.workflow import role_registry
        return original(role, dict(context or {}, registry_sha256=role_registry.registry_sha256()))
    return resolve


register(Mutation('SW28', 'ravel.controller.step.cards:resolve', _pin_ignored, ('SW28',),
                  binding=MUTATION_CONTROLLER, why='cards resolve under whatever registry is installed now'))


@case('SW26', binding=CONTROLLER)
def test_SW26_an_epoch_one_layout_never_receives_new_governed_science(nc):
    legacy = require_controller('routes.legacy')
    old = nc.root / 'old-run'
    old.mkdir()
    (old / 'task_contract.json').write_text(json.dumps({'schema_version': 1, 'task_mode': 'reproduce'}))
    refusal = legacy.admit_new_run(old)
    assert refusal and 'new science is refused in a legacy layout' in refusal, refusal
    # A controller run downgraded from outside to look like epoch one cannot be resumed.
    store, run_dir = controller_run(nc)
    assert legacy.resume_errors(run_dir, store.run_id) == []  # positive control: the intact run resumes
    (run_dir / 'task_contract.json').write_text(json.dumps({'schema_version': 1, 'task_mode': 'reproduce'}))
    errors = legacy.resume_errors(run_dir, store.run_id)
    assert errors and any('SW26' in e or 'legacy layout' in e for e in errors), errors
    assert legacy.admit_new_run(nc.root / 'new-run') is None  # positive control: a new directory is admitted


register(Mutation('SW26', 'ravel.controller.routes.legacy:resume_errors', lambda original: lambda *a, **k: [],
                  ('SW26',), binding=MUTATION_CONTROLLER, why='a downgraded layout resumes as governed'))
