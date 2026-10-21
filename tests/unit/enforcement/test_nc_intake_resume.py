"""Intake and resume rows: run state lives in the controller store; a legacy layout never receives new science.

The adversary deletes the run directory's counter files and resumes, resumes a copy of the run
directory, and points the controller at an epoch-one layout (a run-root contract and no ``inputs``
copy) to start new work there. Oracles are the store's own records after a fresh open, the resume
check's refusal, the legacy route's admission answer, the entry's refusal to create a run there and
an unchanged legacy tree; positive controls resume the original directory, inspect the legacy run
read-only and start a governed run in a new directory.
"""
from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import DEFAULT_PROMPT, operator, store_root
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

REQUEST = DEFAULT_PROMPT.encode()


def _tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def _started(nc, name):
    entry = require_controller('entry')
    op = operator(nc)
    if not op.initialized:
        op.init()
    run_dir = nc.root / 'runs' / name
    return entry.start(REQUEST, channel='nc-harness', rundir=run_dir, root=store_root(nc)), run_dir


@case('R11', binding=CONTROLLER)
def test_R11_deleted_run_tree_counters_reset_nothing_and_a_copied_directory_cannot_resume(nc):
    entry = require_controller('entry')
    budget = require_controller('step.budget')
    custody = require_controller('step.custody')
    from test_nc_budget import CEILINGS, amounts
    store, run_dir = _started(nc, 'nc-run-resume')
    first = budget.reserve(store, step_id='s01', attempt=1, amounts=amounts(wall_seconds=40), ceilings=CEILINGS)
    budget.settle(store, first['key'], status='ambiguous', evidence={'reason': 'fictional crash before a receipt'})
    custody.record_outcome(store, {'id': 's00'}, 1, 'failed', reason='fictional failure')
    # Counter files a legacy lifecycle would keep in the run tree, then deleted by the adversary.
    (run_dir / 'current_state.json').write_text(json.dumps({'attempts': {'s01': 0}, 'budget_used': 0}))
    (run_dir / 'budget-ledger.json').write_text(json.dumps({'wall_seconds': 0}))
    head = store.head()
    for path in sorted(run_dir.rglob('*'), reverse=True):
        if path.is_file() and path.name != 'controller-run.json':
            path.unlink()
    resumed = entry.open_for_resume(store.run_id, rundir=run_dir, root=store_root(nc))  # positive control
    assert resumed.head() == head
    assert budget.totals(resumed, CEILINGS)['wall_seconds']['charged'] == 40
    assert [r['key'] for r in budget.unsettled_prior(resumed, 's01', 2)] == [first['key']], 'nothing was reset'
    assert custody.outcomes(resumed)['s00']['status'] == 'failed'
    # A copy of the run directory is not the run.
    copy = nc.root / 'runs' / 'nc-run-resume-copy'
    shutil.copytree(run_dir, copy)
    with pytest.raises(entry.EntryError, match='cannot be resumed'):
        entry.open_for_resume(store.run_id, rundir=copy, root=store_root(nc))


register(Mutation('M02', 'ravel.controller.store:RunStore.check_binding',
                  lambda original: lambda self, run_dir=None: [], ('R11',), binding=MUTATION_CONTROLLER,
                  why='a resumed run is not checked against the directory it was bound to'))


@case('L01', binding=CONTROLLER)
def test_L01_an_epoch_one_layout_is_inspectable_and_never_receives_new_governed_science(nc):
    entry = require_controller('entry')
    legacy = require_controller('routes.legacy')
    old = nc.root / 'legacy' / 'epoch-one-run'
    old.mkdir(parents=True)
    (old / 'task_contract.json').write_text(json.dumps({'schema_version': 1, 'task_mode': 'reproduce'}))
    (old / 'RESULT.md').write_text('Fictional legacy result.\n')
    before = _tree(old)
    assert legacy.check(old)['layout'] == 'epoch-one'
    refusal = legacy.admit_new_run(old)
    assert refusal and 'new science is refused in a legacy layout' in refusal, refusal
    op = operator(nc)
    op.init()
    with pytest.raises(Exception) as refused:
        entry.start(REQUEST, channel='nc-harness', rundir=old, root=store_root(nc))
    assert 'must be new' in str(refused.value) or 'legacy' in str(refused.value), refused.value
    # Inspection is allowed and writes nothing.
    view = legacy.inspect(old)
    assert view['layout']['layout'] == 'epoch-one' and view['label'] == legacy.NOT_GOVERNED, view
    assert sorted(e['name'] for e in view['entries']) == ['RESULT.md', 'task_contract.json'], view['entries']
    assert _tree(old) == before, 'inspection or the refused start changed the legacy run'
    # Positive control: new work starts in a new directory as a governed run.
    store, run_dir = _started(nc, 'nc-run-new')
    assert legacy.check(run_dir)['layout'] == 'controller' and legacy.admit_new_run(nc.root / 'runs' / 'absent') is None


register(Mutation('M22', 'ravel.controller.routes.legacy:admit_new_run', lambda original: lambda *a, **k: None,
                  ('L01',), binding=MUTATION_CONTROLLER, why='new science is admitted into a legacy layout'))
