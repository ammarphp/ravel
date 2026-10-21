"""Packet projection from the card's sees: what each reviewer profile can and cannot read."""
import json
from pathlib import Path

import pytest

from planted_fixtures import HEADLINE, run_tree


@pytest.fixture
def run(tmp_path):
    return run_tree(tmp_path.resolve() / 'run')


def projection():
    from ravel.workflow import review_projection
    return review_projection


def _sources(manifest):
    return {a['source_path'] for a in manifest['artifacts']}


def _omitted(manifest):
    return {o['source_path']: o['class'] for o in manifest['omissions']}


def _bytes(packet):
    root = Path(packet['path'])
    return b''.join(p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file())


def test_blind_reviewer_never_receives_the_headline_numbers_or_withheld_sources(run):
    rp = projection()
    packet = rp.project(run, 'normalization-auditor', key='k-blind')
    manifest, contents = rp.load(packet)
    assert manifest['profile'] == 'blind' and manifest['role'] == 'normalization-auditor'
    assert HEADLINE.encode() not in _bytes(packet)
    assert 'inputs/spec.json' in _sources(manifest)
    omitted = _omitted(manifest)
    assert omitted['inputs/checkin2.json'] == 'producer_headline'
    assert omitted['inputs/withheld/reference.json'] == 'withheld_sources'
    # Blind profiles read inside inputs/ only: no producer outputs, narrative, lessons or graph state.
    assert not any(s.startswith(('outputs/', 'lessons/', 'framework/', 'review/', 'research/')) or s == 'RESULT.md'
                   for s in _sources(manifest))
    xsec = next(a for a in manifest['artifacts'] if a['source_path'] == 'inputs/xsec.json')
    assert xsec['projection'] == 'fields withheld: headline'
    assert json.loads(contents['inputs/xsec.json']) == {'cross_section_pb': 0.02, 'k_factor': 1.25}


def test_full_profile_reads_the_record_but_not_board_lessons_or_graph_state(run):
    rp = projection()
    manifest, _ = rp.load(rp.project(run, 'integrity-auditor', key='k-full'))
    assert manifest['profile'] == 'full'
    assert 'research/protocol.json' in _sources(manifest)
    assert not any(s.startswith(('research/board/', 'lessons/', 'framework/', 'review/packets/'))
                   for s in _sources(manifest))


def test_spec_denied_plan_critic_sees_plan_and_contract_only_without_reasoning(run):
    rp = projection()
    manifest, contents = rp.load(rp.project(run, 'plan-critic', key='k-plan'))
    assert manifest['profile'] == 'spec-denied'
    from ravel.workflow.capability_catalogue import for_seat, shards, assemble
    context = for_seat('plan-critic')
    capability_sources = {f"ravel:capability-catalogue/{context['catalogue_sha256']}/{part['part']}"
                          for part in shards(context)}
    assert _sources(manifest) == {'inputs/request_plan.json', 'inputs/task_contract.json'} | capability_sources
    assert assemble([json.loads(contents[name]) for name in sorted(capability_sources)]) == context
    assert 'rationale' not in json.loads(contents['inputs/request_plan.json'])


def test_producer_profile_and_unknown_classes_are_refused(run):
    rp = projection()
    with pytest.raises(rp.ProjectionRefused) as refused:
        rp.project(run, 'analysis-author', key='k-producer')
    assert refused.value.code == 'producer_profile'
    assert rp.packet_for(run, {'role': 'analysis-author', 'key': 'k'}) is None
    from ravel.workflow import role_registry
    card = role_registry.load('normalization-auditor')
    card['sees']['forbidden_inputs'] = ['lessons', 'something_new']
    with pytest.raises(rp.ProjectionRefused) as unknown:
        rp.project(run, card, key='k-unknown')
    assert unknown.value.code == 'forbidden_class_unknown'


def test_packet_is_outside_the_run_immutable_and_reused_by_key(run):
    rp = projection()
    item = {'point_id': 'P1', 'subject_sha256': 'a' * 64}
    first = rp.project(run, 'trap-auditor', key='k-same', item=item)
    assert not Path(first['path']).resolve().is_relative_to(run)
    assert rp.project(run, 'trap-auditor', key='k-same', item=item) == first
    # Changed run bytes give a new packet under the same key, never the stale one.
    (run / 'inputs/spec.json').write_text('{"observable": "changed"}')
    second = rp.project(run, 'trap-auditor', key='k-same', item=item)
    assert second['path'] != first['path'] and second['manifest_sha256'] != first['manifest_sha256']
    manifest, contents = rp.load(first)
    assert manifest['subject_sha256'] == 'a' * 64 and manifest['review_point_id'] == 'P1'
    assert 'ravel:data/review/routine_checklist.json' in contents       # routine reviewers get the checklist
    from ravel.workflow import review_context
    artifact = next(Path(first['path']).glob('artifacts/a*'))
    artifact.chmod(0o600)
    artifact.write_text('tampered')
    with pytest.raises(ValueError):
        review_context.verify_packet(first['path'], expected_manifest_sha256=first['manifest_sha256'])


def test_manuscript_only_arm_holds_the_subject_and_nothing_else(run):
    rp = projection()
    (run / 'delivery').mkdir()
    (run / 'delivery/paper.json').write_text('{"title": "synthetic"}')
    manifest, contents = rp.load(rp.project(run, 'integrity-auditor', key='k-arm', subjects=['delivery/paper.json'],
                                            arm='manuscript-only'))
    assert set(contents) == {'delivery/paper.json'} and manifest['arm'] == 'manuscript-only'
