"""Review paths outside the controller: declared-actor submissions and missing registrations.

The adversary submits a verdict through the legacy review journal command naming a policy actor,
or deletes the run's review registration files to switch review gating off before the first
smoke. Oracles are the journal command's refusal and the review state the controller derives from
its store; positive controls run the same paths on a run the controller does not own.
"""
from __future__ import annotations

import contextlib
import io
import json

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

REFUSAL = 'under a caller-declared actor is refused for a controller-owned run'


def _journal(run_dir, action, request):
    from ravel.workflow import physics_review
    path = run_dir.parent / f'{run_dir.name}-{action}-request.json'
    path.write_text(json.dumps(request))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = physics_review.main(['--rundir', str(run_dir), action, '--request', str(path)])
        except SystemExit as exc:
            status = exc.code
    return status, out.getvalue() + err.getvalue()


@case('SW07', binding=CONTROLLER)
def test_SW07_a_review_verdict_naming_a_policy_actor_is_never_recorded_for_a_controller_run(nc):
    require_controller()
    store, run_dir = controller_run(nc)
    before = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob('*'))
    head = store.head()
    verdict = {'role': 'physics-critic', 'actor_id': 'fictional-policy-actor', 'decision': 'accept',
               'findings': [], 'subject_sha256': 'a' * 64}
    for action in ('review', 'open', 'reclassify'):
        status, text = _journal(run_dir, action, verdict)
        assert status != 0 and REFUSAL in text, (action, status, text[-400:])
    assert sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob('*')) == before
    assert store.head() == head
    # Positive control: on a run the controller does not own, the controller does not refuse the command.
    legacy = nc.root / 'legacy-run'
    (legacy / 'inputs').mkdir(parents=True)
    status, text = _journal(legacy, 'review', verdict)
    assert REFUSAL not in text


register(Mutation('SW07', 'ravel.workflow.physics_review:_controller_refusal', lambda original: lambda *a, **k: None,
                  ('SW07',), binding=MUTATION_CONTROLLER, why='declared-actor review commands reach a controller run'))


@case('SW08', binding=CONTROLLER)
def test_SW08_deleting_the_review_registration_files_does_not_switch_review_off(nc):
    require_controller()
    from ravel.workflow import physics_review
    store, run_dir = controller_run(nc)
    store.append(physics_review.REGISTRATION_KIND, {'registration_sha256': 'b' * 64, 'run_id': store.run_id})
    for name in (physics_review.REGISTRATION, physics_review.HEAD):
        path = run_dir / name
        if path.exists():
            path.unlink()
    assert not physics_review.registered(run_dir), 'the run tree holds no registration file any more'
    assert physics_review.active(run_dir) is True, 'the controller store keeps the review active'
    # Positive control: outside the controller, no registration still permits the initial smoke.
    legacy = nc.root / 'legacy-run'
    (legacy / 'inputs').mkdir(parents=True)
    assert physics_review.active(legacy) is False


register(Mutation('SW08', 'ravel.workflow.physics_review:_controller_registered', lambda original: lambda *a, **k: False,
                  ('SW08',), binding=MUTATION_CONTROLLER, why='an absent registration file switches review off'))
