"""P-8 (surface drift on every host surface) and P-15 (RDJ anchors on every transport label)."""
from pathlib import Path

import pytest

from ravel.workflow import rdj_custody, rdj_loop as rdj, role_registry
from rdj_fixtures import Roles, Run, critic, reviewer, two_level_r2, verifier
from parity_support import declarations
from test_receipt_schema import label_for


@pytest.mark.parametrize('surface', role_registry.SURFACES)
def test_a_hand_edit_to_any_generated_host_file_is_detected(tmp_path, surface):
    expected = role_registry.render(surface)
    for relative, text in expected.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    assert role_registry.check_rendered(tmp_path, surfaces=(surface,)) == []
    profiles = role_registry.PROFILE_DIRS[surface]
    inside = [r for r in sorted(expected) if r.startswith(profiles + '/ravel-')]
    outside = [r for r in sorted(expected) if r not in inside]        # entry files, config, gate shims
    for victim in outside + inside[:2]:
        (tmp_path / victim).write_text(expected[victim] + '\n# hand edit\n')
        assert role_registry.check_rendered(tmp_path, surfaces=(surface,)) == ['generated surface drift: ' + victim]
        (tmp_path / victim).write_text(expected[victim])
    (tmp_path / profiles / 'ravel-unregistered-role.txt').write_text('orphan')
    assert any('orphan' in e for e in role_registry.check_rendered(tmp_path, surfaces=(surface,)))


def test_every_voting_role_has_a_profile_on_every_host_surface():
    voting = {c['id'] for c in role_registry.all_cards() if c['independence']['kind'] == 'voting'}
    assert voting
    for surface in role_registry.SURFACES:
        paths = role_registry.profile_paths(surface)
        assert voting <= set(paths), surface
        assert all(paths[r] in role_registry.render(surface) for r in voting)


KIND_REPRESENTATIVES = ('cli-worker', 'ravel-loop', 'http-model', 'external-relay', 'host-subagent')


@pytest.mark.parametrize('kind', KIND_REPRESENTATIVES)
def test_a_self_grounded_chain_is_refused_on_every_transport_label(parity_env, kind):
    """P-15: a chain that ends in a generated claim (no externally verified anchor) cannot authorize, whoever reviewed."""
    document = declarations(kind)[0]
    kw = {'attestation': label_for(document)}
    roles = Roles(edge_reviewer=reviewer(**kw), critic=critic(**kw), verifier=verifier(**kw))
    run = Run(parity_env / 'run')
    case_id = prepare_unanchored(run, roles)
    with pytest.raises(Exception) as refused:
        rdj.authorize(run.root, case_id)
    assert 'self-grounded' in str(refused.value) and 'externally verified anchor' in str(refused.value)


def prepare_unanchored(run, roles):
    from rdj_fixtures import PROPOSER, add, node
    case_id = rdj.open_case(run.root, 'launch', run.action(), PROPOSER)
    add(run, case_id, 'action', node('A', 'The synthetic chain is ready'))
    rdj.run_roles(run.root, case_id, roles)
    return case_id


@pytest.mark.parametrize('kind', KIND_REPRESENTATIVES)
def test_a_transcript_only_tool_output_anchors_nothing_until_it_is_pinned(parity_env, kind):
    document = declarations(kind)[0]
    kw = {'attestation': label_for(document)}
    roles = Roles(edge_reviewer=reviewer(**kw), critic=critic(**kw), verifier=verifier(**kw))
    run = Run(parity_env / 'run')
    anchor = run.stage('smoke', 'outputs/smoke.json', {'events': 100}, register=False)
    case_id = two_level_r2(run, leaf_anchor=anchor, roles=roles)
    rdj.run_roles(run.root, case_id, roles)
    with pytest.raises(Exception) as unpinned:
        rdj.authorize(run.root, case_id)
    assert 'self-grounded' in str(unpinned.value)
    attempt = anchor['binding']['receipt_id'].split(':', 2)[2]
    rdj_custody.register_stage_receipt(run.root, 'smoke', attempt)           # pinning it into custody
    rdj.run_roles(run.root, case_id, roles)
    try:
        rdj.authorize(run.root, case_id)
    except Exception as still_open:                                          # noqa: BLE001
        assert 'self-grounded' not in str(still_open)
