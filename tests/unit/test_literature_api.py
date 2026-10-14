"""Synthetic local citations, code snapshots and explicit title choices."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.workflow import literature
from test_knowledge_broker import setup


def test_citation_and_code_following_uses_literal_links_and_producing_commit(tmp_path, monkeypatch):
    _, broker, _ = setup(tmp_path, monkeypatch)
    commit = 'a' * 40
    text = 'Read source: https://sources.invalid/secondary\nCode: https://code.invalid/tree/' + commit
    raw = text.encode()
    files = {'paper': raw, 'secondary': b'Independent source', 'code': b'Pinned configuration'}
    sources = []
    identities = {'paper': 'https://sources.invalid/primary', 'secondary': 'https://sources.invalid/secondary',
                  'code': 'https://code.invalid/tree/' + commit}
    for identity, data in files.items():
        path = 'inputs/' + identity + '.txt'; (broker.workspace / path).write_bytes(data)
        sources.append({'id': identity, 'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'identity': identities[identity]})
    links = []
    for identity, kind in [('secondary', 'citation'), ('code', 'code')]:
        link = identities[identity]; start = raw.index(link.encode())
        links.append({'id': 'follow-' + identity, 'from': 'paper', 'to': identity, 'kind': kind,
                      'text': link, 'byte_range': [start, start + len(link)], 'commit': commit if kind == 'code' else None})
    result = literature.follow(sources, links, broker=broker)
    assert all(row['status'] == 'located' for row in result['links'])
    assert len(broker.verify_ledger()) == 5
    changed = deepcopy(links); changed[1]['commit'] = 'b' * 40
    result = literature.follow(sources, changed, broker=broker)
    assert result['links'][1]['status'] == 'unresolved'
    assert result['links'][1]['reason'] == 'invalid_evidence'


def test_following_retains_refused_target_without_source_text(tmp_path, monkeypatch):
    from test_knowledge_broker import row
    _, broker, _ = setup(tmp_path, monkeypatch, [row(paths=['blocked.txt'])])
    raw = b'https://sources.invalid/hidden'
    (broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    (broker.workspace / 'inputs/blocked.txt').write_bytes(b'PRIVATE SOURCE')
    sources = [{'id': 'paper', 'path': 'inputs/paper.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'identity': 'primary'},
               {'id': 'blocked', 'path': 'inputs/blocked.txt', 'sha256': hashlib.sha256(b'PRIVATE SOURCE').hexdigest(), 'identity': raw.decode()}]
    link = {'id': 'follow', 'from': 'paper', 'to': 'blocked', 'kind': 'citation', 'text': raw.decode(),
            'byte_range': [0, len(raw)], 'commit': None}
    result = literature.follow(sources, [link], broker=broker)
    assert result['sources'][1]['status'] == 'refused' and result['sources'][1]['receipt_id']
    assert result['links'][0]['status'] == 'unresolved'
    assert 'PRIVATE SOURCE' not in json.dumps(result)


def test_publication_title_requires_authentic_resolved_record(monkeypatch, tmp_path):
    from test_literature_discovery import query, acquire, request, record
    base, root, host, found, _, _ = query(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='resolved'):
        literature.resolve_publication_title('A μ source method', found['product'], base_dir=base)
    resolved, _, _ = acquire(monkeypatch, root, request(base, root, operation='record', prior=found['product'], recid='123'),
                             host, 'resolved', record())
    result = literature.resolve_publication_title('A μ source method', resolved['product'], base_dir=base)
    assert result['identifiers'][0] == 'INSPIRE:123' and result['resolution_required'] is False
    with pytest.raises(ValueError, match='differs'):
        literature.resolve_publication_title('A different source method', resolved['product'], base_dir=base)


def test_cli_literature_is_append_only_registered(capsys):
    from ravel import cli
    assert cli.main(['literature', 'tier']) == 0
    assert json.loads(capsys.readouterr().out)['tier'] == 'judgment'


def test_cli_consumes_complete_large_card_request_without_stdout_truncation(tmp_path, monkeypatch, capsys):
    from ravel import cli
    from test_evidence_card import card
    _, source_broker, _ = setup(tmp_path, monkeypatch)
    raw, value = card(); (source_broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    values = [{**deepcopy(value), 'id': 'card-' + str(i)} for i in range(12)]
    (source_broker.workspace / 'inputs/cards.json').write_text(json.dumps(values))
    assert (source_broker.workspace / 'inputs/cards.json').stat().st_size > 8192
    assert cli.main(['literature', 'check-cards', '--rundir', str(source_broker.rundir),
                     '--workspace', str(source_broker.workspace), '--request', 'inputs/cards.json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['population'] == 12 and len(result['cards']) == 5 and len(result['remaining_ids']) == 7


def test_module_validator_identity_uses_source_backed_atlas_row():
    from ravel.workflow import toolbelt
    from test_toolbelt import synthetic_card
    value = synthetic_card(**{'tools.ravel_actions': ['check run'], 'must_check': [],
                              'tools.validators': ['ravel.validation.evidence_card']})
    result = toolbelt.build(value)
    checks = [row for row in result['absent'] if row['family'] == 'check']
    assert checks[0]['atlas_id'] == 'check:validation.evidence_card'
