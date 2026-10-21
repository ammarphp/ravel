"""Packaged request names extend the deterministic reading floor."""
import json

import pytest

from ravel.workflow import request_reading as reading, tool_census
from registration_tree import census_row, fragment, merger, tree


def requested(prompt):
    return [c['value']['tool'] for c in reading.document(prompt)['constraints']
            if c['type'] == 'requested_tool']


def test_requestable_required_rows_have_names():
    for row in json.loads(tool_census.census_bytes())['tools']:
        assert isinstance(row['request_names'], list)
        if row.get('request_names_reason') is not None:
            # A row a request never names (a data set, a supplied layout, RAVEL's own runtime) says why.
            assert row['request_names'] == [] and row['request_names_reason'].strip(), row['id']
        elif row['requirement'] == 'required_for_profile' and not row['id'].startswith('component-'):
            assert row['request_names'], row['id']


@pytest.mark.parametrize('prompt', [
    'Use the HEPData tables and the arXiv source of the paper; write the selection in Python.',
    'Combine the two channels, then report the particle-level vector of yields in a hist.',
])
def test_data_sources_languages_and_common_words_are_not_tool_requests(prompt):
    assert requested(prompt) == []


def test_a_pattern_name_is_reported_under_its_row_s_plain_name():
    assert requested('Run the combine tool on the datacards.') == []
    assert requested('Run the Combine tool on the datacards.') == ['HiggsCombine']
    assert requested('Use ROOT to read the trees.') == ['ROOT']


@pytest.mark.parametrize('name', ['AgentRivet', 'SFitter', 'Snakemake', 'YODA', 'Mathematica', 'SymPy'])
def test_new_tool_requests_become_constraints(name):
    assert requested(f'Use {name} for this study.') == [name]


def test_names_do_not_match_inside_other_tool_names():
    assert requested('Use AgentRivet for this study.') == ['AgentRivet']
    assert requested('Use SFitterAgents for this study.') == ['SFitterAgents']
    assert requested('Use SFitterAgents and SFitter for this study.') == ['SFitterAgents', 'SFitter']


@pytest.mark.parametrize('prompt', [
    'Study the supplied samples and report the uncertainty.',
    'Find the root of the expression, form a class, and combine the terms.',
])
def test_prose_without_tool_names_has_no_tool_constraint(prompt):
    assert requested(prompt) == []


@pytest.mark.parametrize('value', ['Tool', None, {}, [None], [''], ['  '], ['re:[']])
def test_decode_refuses_invalid_request_names(value):
    data = json.loads(tool_census.census_bytes())
    data['tools'][0]['request_names'] = value
    with pytest.raises(ValueError, match='request_names'):
        tool_census._decode(json.dumps(data), catalog=None)


def test_decode_accepts_empty_names_and_valid_expression():
    data = json.loads(tool_census.census_bytes())
    data['tools'][0]['request_names'] = []
    data['tools'][1]['request_names'] = ['FictionalTool', 're:(?-i:FX)']
    tool_census._decode(json.dumps(data), catalog=None)


def test_compilation_preserves_static_prefix_and_loads_bytes_once(monkeypatch):
    calls = []
    rows = [{'title': 'FictionalTool (local)', 'request_names': [
        'FictionalTool', 'FX', 'MadAnalysis-5', 're:(?-i:CLASS)']},
        {'title': 'OtherTool (local)', 'request_names': ['re:OtherTool']},
        {'title': 'FictionalTool', 'request_names': ['FictionalTool']}]
    def census():
        calls.append(True)
        return json.dumps({'tools': rows}).encode()
    monkeypatch.setattr(tool_census, 'census_bytes', census)
    patterns = reading._census_tool_patterns()
    assert len(calls) == 1
    assert [name for name, _ in patterns] == ['FictionalTool', 'FX', 'OtherTool']
    tool, caps, _ = [rx for _, rx in patterns]
    assert tool.search('Use fictionaltool.')
    assert not tool.search('@FictionalTool') and not tool.search('FictionalToolbox')
    assert caps.search('Use FX.') and not caps.search('Use fx.')
    assert [(name, rx.pattern) for name, rx in reading._TOOL_RES[:len(reading.TOOLS)]] == [
        (name, r'(?<![\w@])(?:' + rx + r')(?![\w@])') for name, rx in reading.TOOLS]


@pytest.mark.parametrize('error', [OSError('missing'), ValueError('invalid')])
def test_unreadable_census_falls_back_to_static_patterns(monkeypatch, error):
    def fail():
        raise error
    monkeypatch.setattr(tool_census, 'census_bytes', fail)
    assert reading._census_tool_patterns() == ()


def test_registration_copies_names_only_to_the_declaring_census_row(tmp_path):
    root = tree(tmp_path)
    row = census_row('fictional-tool', request_names=['FictionalTool', 're:(?-i:FX)'])
    fragment(root, 'tools', 'census-rows', {'schema_version': 1, 'rows': [row, census_row('other-tool')]})
    module = merger()
    module.merge(root, ['tools'])
    path = root / 'src/ravel/data/backends/census.json'
    rows = {r['id']: r for r in json.loads(path.read_text())['tools']}
    assert rows['census-fictional-tool']['request_names'] == row['request_names']
    assert 'request_names' not in rows['census-other-tool']
    mirror = json.loads((root / 'src/ravel/data/knowledge/qualification.json').read_text())['tools']
    assert all('request_names' not in r for r in mirror)
    row['request_names'] = ['RenamedTool']
    fragment(root, 'tools', 'census-rows', {'schema_version': 1, 'rows': [row]})
    module.merge(root, ['tools'])
    updated = {r['id']: r for r in json.loads(path.read_text())['tools']}
    assert updated['census-fictional-tool']['request_names'] == ['RenamedTool']
    row.pop('request_names')
    fragment(root, 'tools', 'census-rows', {'schema_version': 1, 'rows': [row]})
    before = path.read_bytes()
    module.merge(root, ['tools'])
    assert path.read_bytes() == before


def test_registration_updates_an_existing_excluded_row_without_touching_other_names(tmp_path):
    from types import SimpleNamespace
    existing = {'id': 'census-existing', 'title': 'FictionalEngine', 'status': 'excluded',
                'installer_groups': [], 'doctor_checks': [], 'request_names': ['OldEngine']}
    other = {'id': 'census-other', 'title': 'OtherEngine', 'request_names': ['OtherEngine']}
    reg = SimpleNamespace(root=tmp_path, census={'tools': [existing, other]},
                          qualification={'tools': [{'id': 'census-existing'}]},
                          groups={'python-host'}, checks={('python-host', 'host-python')})
    report = {'not_applied': [], 'reflected': [], 'applied': []}
    row = census_row('fictional-engine', request_names=['FictionalEngine'])
    row['title'] = 'FictionalEngine'
    merger()._apply_census(reg, {'rows': [row]}, 'fictional-source', report)
    assert existing['request_names'] == ['FictionalEngine']
    assert other['request_names'] == ['OtherEngine']
    assert 'request_names' not in reg.qualification['tools'][0]
    assert report['applied'] == ['census-existing']


@pytest.mark.parametrize('alias,name', [('MG5', 'MadGraph'), ('MA5', 'MadAnalysis5'),
                                        ('Pythia 8', 'Pythia'), ('MG5_aMC@NLO', 'MadGraph5_aMC@NLO')])
def test_existing_tool_aliases_keep_their_single_constraint(alias, name):
    assert requested(f'Use {alias} for this study.') == [name]


def test_ordinary_library_words_do_not_become_requested_tools():
    assert requested('Model the particle as a vector with awkward parameters.') == []
