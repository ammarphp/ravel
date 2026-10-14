"""Source identity of generated packet entries and bound inputs in the follow-up presentation check."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from ravel.physics import root_stream
from ravel.workflow import agent_graph as g, review_context as rc
from ravel.workflow import scientific_context_followup as followup, sfitter_source_context as source_context
from test_sfitter_conductor import proposal, SuppliedHost
from test_sfitter_source_context import references, setup


def test_every_packet_entry_carries_a_source_identity_the_host_can_classify(tmp_path):
    _, _, _, packet, _, _ = setup(tmp_path)
    index = rc._PacketIndex(Path(packet['path']), packet['manifest_sha256'])
    originals = {row['artifact_id'] for row in index.manifest['inputs']}
    generated = set(index.entries) - originals
    assert {'public_case', 'source_catalogue'} <= generated
    for identity, entry in index.entries.items():
        assert set(entry) >= {'source_path', 'source_sha256'}
        # The Host classifies every artifact by its source identity before presentation.
        root_stream.model_artifact_source(entry['source_path'], entry['source_sha256'])
        if identity in generated:
            # Generated material names its own packet copy, never an original source.
            assert entry['source_path'] == str(index.root / entry['path'])
            assert entry['source_sha256'] == entry['sha256'] == hashlib.sha256(index.read(entry)).hexdigest()
            assert entry['projection'] != 'exact bytes'
        else:
            pin = next(row['pin'] for row in index.manifest['inputs'] if row['artifact_id'] == identity)
            assert (entry['source_path'], entry['source_sha256']) == (pin['path'], pin['sha256'])
            assert entry['projection'] == 'exact bytes'
    index.finish()


@pytest.mark.parametrize('field', ['source_path', 'source_sha256', 'absent'])
def test_changed_or_absent_generated_source_identity_is_refused_by_the_index(tmp_path, field):
    _, _, _, packet, _, _ = setup(tmp_path)
    path = Path(packet['path']) / 'manifest.json'
    manifest = json.loads(path.read_bytes())
    entry = next(e for e in manifest['artifacts'] if e['id'] == 'public_case')
    if field == 'absent':
        del entry['source_path'], entry['source_sha256']
    elif field == 'source_path':
        entry['source_path'] = str(tmp_path / 'elsewhere.txt')
    else:
        entry['source_sha256'] = '0' * 64
    manifest.pop('sha256'); manifest['sha256'] = rc.execution.digest(manifest)
    path.write_bytes(source_context._raw(manifest))
    with pytest.raises(ValueError):
        rc._PacketIndex(Path(packet['path']), manifest['sha256'])


def test_followup_presentation_admits_bound_inputs_and_refuses_foreign_digests(tmp_path):
    wf, docs, _, packet, spec, root = setup(tmp_path)
    manifest = rc.verify_packet(packet['path'], expected_manifest_sha256=packet['manifest_sha256'])
    value = proposal(wf, 'extraction', 'request_context'); value['documentation_markdown'] = ''
    value['context_pages'] = references(docs, manifest)
    assert g.execute(root, SuppliedHost(value), workers=1)['complete']
    saved = json.loads((root / g.status(root)['nodes']['sfitter_lead']['result']['path']).read_bytes())
    isolation = saved['result']['isolation']
    index = rc._PacketIndex(Path(packet['path']), packet['manifest_sha256'])
    core = index.entries['public_case']['sha256']
    bound = {pin['sha256'] for pin in spec['nodes'][0]['inputs']}
    presented = set(isolation['evidence_presentation']['presented_subject_sha256s'])
    # The Host records the node's own bound input beside the packet's inline core.
    assert bound and bound <= presented and core in presented
    assert not bound & ({e['sha256'] for e in index.entries.values()} | {e['source_sha256'] for e in index.entries.values()})
    assert followup._explicit_presentation(isolation, index, {core}, bound) == presented
    # Without the bound-input declaration the same observation names a digest outside the packet.
    with pytest.raises(ValueError, match='must actually be presented'):
        followup._explicit_presentation(isolation, index, {core})
    foreign = copy.deepcopy(isolation)
    foreign['evidence_presentation']['presented_subject_sha256s'].append('f' * 64)
    with pytest.raises(ValueError, match='must actually be presented'):
        followup._explicit_presentation(foreign, index, {core}, bound)
    missing = copy.deepcopy(isolation)
    missing['evidence_presentation']['presented_subject_sha256s'].remove(core)
    with pytest.raises(ValueError, match='must actually be presented'):
        followup._explicit_presentation(missing, index, {core}, bound)
    index.finish()
