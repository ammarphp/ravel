"""Workflow-manager submission rows: a facility submit needs the live launch's capability and its pinned profile.

The adversary calls the submit console script directly, or edits the site profile after the launch's
approval minted its capability. Oracles are read outside the submission: the inert scheduler stub's
call log, the console script's exit status and message, and the store's submission records; the
positive control submits the approved job once through the same entry.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _site_profile(nc, workflow):
    """A complete fictional site-profile folder (the members its pin covers)."""
    from ravel.workflow.site_profiles import render
    folder = nc.path('site-profile', 'profile.json').parent
    profile = render('htcondor', project_id='project-a', options={'workflow_dir': str(workflow)})
    (folder / 'profile.json').write_text(json.dumps(profile))
    (folder / 'config.yaml').write_text('jobs: 1\n')
    for name in ('ravel-submit.sh', 'ravel-status.sh'):
        (folder / name).write_text('#!/bin/sh\nexit 0\n')
        (folder / name).chmod(0o755)
    return folder


@case('T08', binding=CONTROLLER)
def test_T08_a_direct_submit_or_a_site_profile_changed_after_approval_submits_nothing(nc):
    confine = require_controller('confine')
    from ravel.workflow import wms_policy, wms_site
    from ravel.workflow.site_profiles import htcondor
    from test_nc_switches_launch import CONSOLE_PROGRAM, _inert_scheduler, _job_script
    store, _ = controller_run(nc)
    scheduler = _inert_scheduler(nc)
    workflow = nc.path('workflow', 'run-keys.json').parent
    (workflow / 'run-keys.json').write_text(json.dumps({'alpha': '012abc'}))
    job = _job_script(workflow / 'job-alpha.sh', 'task_alpha')
    folder = _site_profile(nc, workflow)
    argv = ['--profile', str(folder / 'profile.json'), str(job)]

    def submit():
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                status = htcondor.submit_main(list(argv))
            except SystemExit as stop:
                status = stop.code
        return status, out.getvalue(), err.getvalue()

    # A direct call of the console script, in process and as a separate process, submits nothing.
    status, _, err = submit()
    assert status == 1 and 'no launch capability was presented' in err, (status, err)
    child = subprocess.run([sys.executable, '-c', CONSOLE_PROGRAM, *argv], capture_output=True, text=True,
                           timeout=120, env=dict(os.environ))
    assert child.returncode == 1 and 'no launch capability was presented' in child.stderr, child
    assert scheduler() == []
    # The approved launch mints a capability bound to the site profile it was approved with.
    pin = wms_site.profile_pin(folder)
    token = confine.mint_capability(store, 'launch-1', {'workflow_dir': str(workflow), 'tasks': ['alpha'],
                                                         'rules': ['task_alpha'], 'max_jobs': 2,
                                                         'profile_sha256': pin['sha256']})
    with wms_policy.launch_authorization(workflow, 'alpha', 2, {'alpha': 'a' * 64}, capability=token,
                                         controller_run=store.run_id):
        status, out, err = submit()
        assert status == 0 and len(scheduler()) == 1, (status, out, err)  # positive control
        # The site profile is edited after the approval: its digest no longer matches the capability.
        (folder / 'config.yaml').write_text('jobs: 1000\n')
        status, _, err = submit()
        assert status == 1 and 'site profile differs' in err, (status, err)
        assert len(scheduler()) == 1, 'the stub scheduler received no job after the profile changed'
    assert [row['record']['task'] for row in store.scan('wms-submission')] == ['alpha']


def _pinned_once(original):
    """The site profile is pinned once and never read again (a later edit goes unseen)."""
    cache = {}

    def profile_pin(folder):
        return cache.setdefault(str(folder), original(folder))
    return profile_pin


register(Mutation('M08', 'ravel.workflow.wms_site:profile_pin', _pinned_once, ('T08',), binding=MUTATION_CONTROLLER,
                  why='a site profile changed after approval keeps the approved digest'))
