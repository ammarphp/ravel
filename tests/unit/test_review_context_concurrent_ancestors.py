"""Unrelated entry churn is separate from committed packet/path replacement."""
import os
from pathlib import Path
import pytest
from ravel.workflow import review_context as context, agent_host
from test_binary_role_evidence import packet, node, request


def index(tmp_path):
    owned = tmp_path / 'workspace' / 'owned'
    owned.mkdir(parents=True)
    p = packet(owned / 'packet', {'first': b'first', 'second': b'second'})
    value = context._PacketIndex(p['path'], p['manifest_sha256'])
    value.read(value.entries['first'])
    return owned, p, value


@pytest.mark.parametrize('checkpoint', ['read', 'finish'])
@pytest.mark.parametrize('churn', ['mkdir', 'file', 'remove'])
def test_unrelated_sibling_entry_churn_does_not_change_committed_packet(tmp_path, checkpoint, churn):
    owned, p, value = index(tmp_path)
    sibling = owned / 'other-task'
    if churn == 'mkdir': sibling.mkdir()
    elif churn == 'file': sibling.write_text('unrelated metadata')
    else:
        sibling.mkdir(); sibling.rmdir()
    if checkpoint == 'read': assert value.read(value.entries['second']) == b'second'
    value.finish()
    assert context.verify_packet(p['path'], expected_manifest_sha256=p['manifest_sha256'])['sha256'] == p['manifest_sha256']


@pytest.mark.parametrize('checkpoint', ['read', 'finish'])
@pytest.mark.parametrize('change', ['replacement', 'symlink', 'permissions'])
def test_exact_ancestor_identity_and_mode_still_refuse(tmp_path, checkpoint, change):
    owned, p, value = index(tmp_path)
    if change == 'permissions': owned.chmod(0o700 if owned.stat().st_mode & 0o777 != 0o700 else 0o755)
    else:
        saved = owned.with_name('saved'); owned.rename(saved)
        if change == 'symlink': owned.symlink_to(saved, target_is_directory=True)
        else:
            (owned / 'packet/artifacts').mkdir(parents=True)
            for rel in ['manifest.json', 'artifacts/first.dat', 'artifacts/second.dat']:
                os.link(saved / 'packet' / rel, owned / 'packet' / rel)
    with pytest.raises((ValueError, OSError)):
        value.read(value.entries['second']) if checkpoint == 'read' else value.finish()


@pytest.mark.parametrize('change', ['owned_packet_entry', 'artifact_entry', 'leaf_bytes', 'leaf_aba', 'manifest_bytes'])
def test_owned_namespace_and_exact_leaf_observations_remain_strict(tmp_path, change):
    owned, p, value = index(tmp_path)
    root = Path(p['path']); first = root / 'artifacts/first.dat'
    if change == 'owned_packet_entry': (root / 'unexpected').write_bytes(b'unindexed')
    elif change == 'artifact_entry': (root / 'artifacts/unindexed.dat').write_bytes(b'unindexed')
    elif change in {'leaf_bytes', 'leaf_aba'}:
        raw = first.read_bytes(); first.write_bytes(b'changed')
        if change == 'leaf_aba': first.write_bytes(raw)
    else: (root / 'manifest.json').write_bytes((root / 'manifest.json').read_bytes() + b' ')
    with pytest.raises((ValueError, OSError)): value.finish()


def test_public_host_authenticates_all_copies_during_unrelated_sibling_churn(tmp_path, monkeypatch):
    (tmp_path / 'workspace').mkdir()
    p = packet(tmp_path / 'workspace/packet', {'first': b'first', 'second': b'second'})
    before = context._PacketIndex.read
    writes = []
    def churn(self, entry):
        raw = before(self, entry)
        if not writes:
            (self.root.parent / 'parallel-metadata').mkdir(); writes.append(entry['id'])
        return raw
    monkeypatch.setattr(context._PacketIndex, 'read', churn)
    value = agent_host.AgentHost().prepare_model_context(node(p), request(node(p)))
    assert writes and value['context']['review_packet']['manifest_sha256'] == p['manifest_sha256']
