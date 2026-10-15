"""Synthetic container declarations and their refusal boundaries."""
import json

import pytest

from ravel.physics import dataset_resolution as dr


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


def rules(tmp_path):
    return write_json(tmp_path / 'rules.json', {
        'schema_version': 1, 'tree': 'Events', 'kind': 'background_mc',
        'process_map': {'101': 'process_a', '102': 'process_b'},
        'campaigns': {'expected': ['era_a', 'era_b']},
        'rules': [{'pattern': r':sim\.', 'dsid_pattern': r'(?<=\.)(?P<dsid>\d+)(?=\.)',
                   'campaign_pattern': r'\.(?P<campaign>era_[ab])$'}]})


class ContainerClient:
    def __init__(self):
        self.calls = []

    def list_content(self, scope, name):
        self.calls.append((scope, name))
        return iter([
            {'scope': 'scope_a', 'name': 'sim.101.era_a', 'type': 'DATASET'},
            {'scope': 'scope_b', 'name': 'sim.101.era_b', 'type': 'DATASET'},
            {'scope': 'scope_b', 'name': 'sim.102.era_a', 'type': 'DATASET'}])


def test_container_expands_three_members_in_their_own_scopes(tmp_path):
    client = ContainerClient()
    out = tmp_path / 'declaration.json'
    result = dr.expand('container_scope:bundle', rules(tmp_path), out, client=client)
    assert client.calls == [('container_scope', 'bundle')]
    assert [(s['dsid'], s['campaign'], s['process'], s['dids']) for s in result['samples']] == [
        (101, 'era_a', 'process_a', ['scope_a:sim.101.era_a']),
        (101, 'era_b', 'process_a', ['scope_b:sim.101.era_b']),
        (102, 'era_a', 'process_b', ['scope_b:sim.102.era_a'])]
    assert len({s['id'] for s in result['samples']}) == 3
    assert all(s['tree'] == 'Events' for s in result['samples'])
    assert dr.load_declaration(out) == result
    pin = result['expansion_authority']
    raw = json.loads(open(pin['path']).read())
    assert raw['members'][1]['scope'] == 'scope_b'
    assert pin['sha256'] == dr._pin(pin['path'])['sha256']


def test_expansion_lists_unmatched_and_ambiguous_members_and_pins_raw(tmp_path, capsys):
    rule_path = rules(tmp_path)
    spec = json.loads(rule_path.read_text())
    spec['rules'].append({**spec['rules'][0], 'pattern': r'101\.era_b$'})
    write_json(rule_path, spec)
    rows = list(ContainerClient().list_content('container_scope', 'bundle'))
    rows.append({'scope': 'scope_c', 'name': 'unknown', 'type': 'DATASET'})
    listing = write_json(tmp_path / 'listing.json', rows)
    out = tmp_path / 'decl.json'
    assert dr.main(['expand', '--container', 'container_scope:bundle', '--member-rule', str(rule_path),
                    '--out', str(out), '--listing', str(listing)]) == 2
    error = capsys.readouterr().err
    assert 'scope_b:sim.101.era_b: matches 2' in error
    assert 'scope_c:unknown: matches 0' in error
    assert not out.exists()
    assert out.with_name('decl.container.json').is_file()


def test_listing_matches_client_and_scope_is_not_inherited(tmp_path):
    rule_path = rules(tmp_path)
    listing = write_json(tmp_path / 'listing.json', {'container': 'container_scope:bundle',
                          'members': list(ContainerClient().list_content('container_scope', 'bundle'))})
    a = dr.expand('container_scope:bundle', rule_path, tmp_path / 'a.json', client=ContainerClient())
    b = dr.expand('container_scope:bundle', rule_path, tmp_path / 'b.json', listing=listing)
    assert a['samples'] == b['samples']
    raw = json.loads(open(b['expansion_authority']['path']).read())
    assert raw['source']['listing']['sha256'] == dr._pin(listing)['sha256']
    with pytest.raises(ValueError, match='different container'):
        dr.expand('container_scope:other', rule_path, tmp_path / 'c.json', listing=listing)


@pytest.mark.parametrize('bad_row', [
    {'scope': 'scope_c', 'name': 'sim.101.era_a', 'type': 'CONTAINER'},
    {'scope': 'scope_c', 'name': 'sim.999.era_a', 'type': 'DATASET'},
    {'scope': 'scope_c', 'name': 'sim.101.102.era_a', 'type': 'DATASET'}])
def test_expansion_refuses_nested_unmapped_and_multiple_extractions(tmp_path, bad_row):
    listing = write_json(tmp_path / 'listing.json', [bad_row])
    out = tmp_path / 'decl.json'
    with pytest.raises(ValueError, match='refused'):
        dr.expand('container_scope:bundle', rules(tmp_path), out, listing=listing)
    assert not out.exists()


def test_expanded_declaration_resolves_dataset_member_scopes(tmp_path):
    from test_dataset_resolution import FakeRucio, file_rows

    decl = tmp_path / 'declaration.json'
    expanded = dr.expand('container_scope:bundle', rules(tmp_path), decl, client=ContainerClient())
    files = {s['dids'][0]: file_rows(str(i), 1, scope=s['dids'][0].split(':')[0])
             for i, s in enumerate(expanded['samples'])}
    replicas = {f"{f['scope']}:{f['name']}": [f"root://store.example.invalid//{f['name']}"]
                for rows in files.values() for f in rows}
    client = FakeRucio(files, replicas)
    result = dr.resolve(decl, tmp_path / 'resolved.json', client=client)
    assert ('list_files', 'scope_b', 'sim.101.era_b') in client.calls
    assert [s['campaign'] for s in result['samples']] == ['era_a', 'era_b', 'era_a']
    assert result['campaigns']['expected'] == ['era_a', 'era_b']


def test_campaign_tag_mapping_and_duplicate_member_refusal(tmp_path):
    path = rules(tmp_path)
    spec = json.loads(path.read_text())
    spec['rules'][0]['campaign_map'] = {'era_a': 'period_one', 'era_b': 'period_two'}
    spec['campaigns']['expected'] = ['period_one', 'period_two']
    write_json(path, spec)
    result = dr.expand('container_scope:bundle', path, tmp_path / 'a.json', client=ContainerClient())
    assert [s['campaign'] for s in result['samples']] == ['period_one', 'period_two', 'period_one']
    row = {'scope': 'scope_a', 'name': 'sim.101.era_a'}
    listing = write_json(tmp_path / 'listing.json', [row, row])
    with pytest.raises(ValueError, match='duplicate'):
        dr.expand('container_scope:bundle', path, tmp_path / 'b.json', listing=listing)


def test_public_cli_dispatches_expand_with_supplied_inputs(tmp_path, capsys):
    from ravel import cli

    listing = write_json(tmp_path / 'listing.json', list(ContainerClient().list_content('container_scope', 'bundle')))
    out = tmp_path / 'decl.json'
    assert cli.main(['ntuples', 'expand', '--container', 'container_scope:bundle', '--member-rule', str(rules(tmp_path)),
                     '--out', str(out), '--listing', str(listing)]) == 0
    assert len(json.loads(out.read_text())['samples']) == 3


@pytest.mark.parametrize('campaign_map', [['era_a'], {'era_a': 12}])
def test_invalid_campaign_mapping_is_refused(tmp_path, campaign_map):
    path = rules(tmp_path)
    spec = json.loads(path.read_text())
    spec['rules'][0]['campaign_map'] = campaign_map
    write_json(path, spec)
    with pytest.raises(ValueError):
        dr.expand('container_scope:bundle', path, tmp_path / 'out.json', client=ContainerClient())
