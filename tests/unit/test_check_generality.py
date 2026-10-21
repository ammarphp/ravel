"""The generality gate: no named challenge, analysis, routine, literature id, person or showcase point.

Every identifier the gate must catch is assembled at run time from fragments, so this file itself
passes the gate. The names are synthetic.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ravel.validation import check_generality as cg

ROOT = Path(__file__).resolve().parents[2]
J = '-'.join
U = '_'.join


def _rules(text, denylist=None):
    return sorted({h.rule for h in cg.scan_text(text, denylist or cg.Denylist([]))})


@pytest.mark.parametrize('text,rule', [
    (J(['ATLAS', 'EXOT', '2099', '07']), 'analysis-code'),
    (J(['CMS', 'PAS', 'XYZ', '98', '012']), 'analysis-code'),
    ('see ' + J(['ABCD', '2098', '11']) + ' for the cuts', 'analysis-code'),
    ('the file ' + J(['ANA', 'ABCD', '2098', '11']) + '.cxx', 'analysis-code'),
    (J(['atlas', 'grp', '2098', '11']) + '/inputs', 'analysis-code'),
    (U(['ATLAS', '2098', 'I' + '9999999']), 'routine-id'),
    (U(['CMS', '2097', 'S' + '8888888']), 'routine-id'),
    ('Fake' + 'Search' + '2031', 'routine-name'),
    ('FakeSearch' + 'XY' + '2029', 'routine-name'),
    ('SQ' + '7L' + '2021', 'routine-name'),
    ('import ' + 'fakesearchxy' + '2029', 'routine-name'),
    (J(['atlas', '2097', 'fake', 'pair']), 'experiment-year-slug'),
    ('arXiv:' + '2601' + '.99999', 'arxiv-id'),
    ('[arXiv' + '2601' + '.99999v2]', 'arxiv-id'),
    ('https://arxiv.org/abs/' + '0912' + '.9999', 'arxiv-id'),
    ('https://arxiv.org/html/' + '2601' + '.99999v2', 'arxiv-id'),
    ('(' + '2512' + '.88888' + ')', 'arxiv-id'),
    ('hep' + '-ph/' + '0612345', 'arxiv-id'),
    ('atlas_' + '2512_' + '99999' + ' fixture', 'arxiv-id'),
    ('"#line\\n' + 'atlas_' + '2512_' + '99999' + '"', 'arxiv-id'),
    ('"\\t' + J(['ABCD', '2098', '11']) + '"', 'analysis-code'),
    ('https://inspirehep.net/literature/' + '9999991', 'inspire-id'),
    ('"inspire_id": ' + '9999992', 'inspire-id'),
    ('record ' + 'ins' + '9999993', 'inspire-id'),
    ('studies/i' + '9999994' + '-fixture.md', 'inspire-id'),
    ('https://www.hepdata.net/record/' + '99999', 'hepdata-record'),
    ('https://www.hepdata.net/record/resource/' + '2999999', 'hepdata-record'),
    ('10.' + '17182/hepdata.' + '99999', 'hepdata-record'),
    ('serves HEPData ' + '199999' + ' v1', 'hepdata-record'),
    ('doi 10.' + '1007/JHEP' + '01(2099)001', 'journal-doi'),
])
def test_patterns_catch_each_identifier_shape(text, rule):
    assert rule in _rules(text)


@pytest.mark.parametrize('text', [
    'ROUTINE_TEST_1 and FictionalRoutine700 are synthetic',
    'B-290 is a change id; dates such as 2026-10-12 are fine',
    'a 13 TeV ATLAS-style detector card with Delphes 3.5.0 and pyhf 0.7.6',
    'the value 1234.56789 is a float, and 0.12345 too',
    'MadGraph5_aMC@NLO 3.6.0, Pythia 8.312, Rivet 4.0.2, MC_JETS',
    'Run2 and Python3 and SHA256 are words, Run2016 is a data period, trigger' + '2017 a period flag',
    'a pyhf workspace hepdata field ins0001004 is zero-padded and synthetic',
    'synthetic https://www.hepdata.net/record/ins1001 and /record/data/123/7/2 and /record/resource/99',
    'particle' + '2022.csv and fsspec' + '2026.9.0 are package data and versions',
    'the PDF sets ' + 'MMHT' + '2014 and ' + 'CT' + '18, a Draft' + '202012Validator',
])
def test_generic_vocabulary_passes(text):
    assert _rules(text) == []


# Placeholder identifiers: the shapes an earlier clean-up put where sources had been cited.
ZERO = '0' * 4
PLACEHOLDERS = [
    ('arXiv:' + ZERO + '.00014, measurements', 'placeholder-arxiv-id'),
    ('"reference": "arXiv:' + ZERO + '.00521"', 'placeholder-arxiv-id'),
    ('https://arxiv.org/pdf/' + ZERO + '.00002', 'placeholder-arxiv-id'),
    ('https://arxiv.org/abs/' + ZERO + '.00003v2', 'placeholder-arxiv-id'),
    ('"arxiv": "' + ZERO + '.00758"', 'placeholder-arxiv-id'),
    ('expected file ' + ZERO + '.00002.pdf', 'placeholder-arxiv-id'),
    ('arXiv:' + '9913' + '.00001 has no real year and month', 'placeholder-arxiv-id'),
    ('arXiv:' + '2600' + '.12345 has month zero', 'placeholder-arxiv-id'),
    (J(['ANA', '9001', '01']) + ' r_obs=13.04', 'placeholder-analysis-id'),
    ('doi:10.23731/' + J(['ANA', '9003', '01']), 'placeholder-analysis-id'),
    ('report ' + J(['ATL', 'ANA', '9505', '01']), 'placeholder-analysis-id'),
    ('trial-runs/2026-07-11_' + J(['ANA', '9008', '01']) + '_projection', 'placeholder-analysis-id'),
    ('Routine' + '001 141/141 signal regions', 'placeholder-routine-name'),
    ('"routine": "Routine' + '002"', 'placeholder-routine-name'),
    ('output/Routine' + '003_patch.json', 'placeholder-routine-name'),
]


@pytest.mark.parametrize('text,rule', PLACEHOLDERS)
def test_placeholder_identifiers_are_refused(text, rule):
    assert rule in _rules(text)


@pytest.mark.parametrize('text', [
    'the value 0000.5 and the mask 0000.0 are numbers',
    'a serial 1' + ZERO + '.00014 and a version 1.' + ZERO + '.00014 are not literature numbers',
    'FictionalRoutine700 and Routine' + '0015 are not the placeholder series',
    J(['ANA', '901', '01']) + ' and ' + J(['BANANA', '9001', '01']) + ' and MANA-' + '9001-01 are other labels',
])
def test_near_placeholder_text_passes(text):
    assert not set(_rules(text)) & set(cg.PLACEHOLDER_RULES)


def test_placeholders_are_refused_in_paths_and_compressed_members(tmp_path):
    import gzip
    (tmp_path / ('fixture-' + J(['ANA', '9007', '01']).lower())).mkdir()
    (tmp_path / ('Routine' + '001_patch.json')).write_text('{}\n')
    with gzip.open(tmp_path / 'events.lhe.gz', 'wt') as handle:
        handle.write('# merging [arXiv:' + ZERO + '.00037]\n')
    found = {(h.path, h.rule) for h in cg.scan_tree(tmp_path, cg.Denylist([]), )}
    assert ('Routine' + '001_patch.json', 'placeholder-routine-name') in found
    assert ('events.lhe.gz', 'placeholder-arxiv-id') in found


# The citation list: exact identifiers in exactly the listed files.
CITED = '2601' + '.99999'          # synthetic, of the real form
OTHER = '2512' + '.88888'
REPORT = J(['CERN', '2098', '011'])
DOI = '10.' + '1103/PhysRevD.' + '999.012345'
LISTED = 'src/ravel/data/tables/SOURCE.json'


def _scan(path, text, citations):
    return sorted({(h.line, h.rule) for h in cg.scan_bytes(path, text.encode(), cg.Denylist([]), citations)})


def test_a_listed_citation_passes_in_its_file_and_is_refused_elsewhere():
    citations = {LISTED: [CITED, REPORT, DOI]}
    text = ('{"url": "https://arxiv.org/pdf/' + CITED + '", "expected_filename": "' + CITED + '.pdf",\n'
            ' "identifiers": "doi:' + DOI + '; arXiv:' + CITED + '; ' + REPORT + '"}\n')
    assert _scan(LISTED, text, citations) == []
    # the same text in a file that is not listed, and in a sibling of the listed file
    assert {rule for _, rule in _scan('docs/guide.md', text, citations)} == {'analysis-code', 'arxiv-id', 'journal-doi'}
    assert _scan('src/ravel/data/tables/OTHER.json', text, citations) != []
    assert _scan(LISTED + '.bak', text, citations) != []
    # without a list nothing is exempt
    assert _scan(LISTED, text, {}) != []


def test_a_listed_file_may_carry_only_its_listed_identifiers():
    citations = {LISTED: [CITED]}
    text = 'arXiv:' + CITED + '\nand arXiv:' + OTHER + '\nand ' + REPORT + '\n'
    assert _scan(LISTED, text, citations) == [(2, 'arxiv-id'), (3, 'analysis-code')]


def test_a_listed_identifier_its_file_no_longer_carries_is_a_finding():
    citations = {LISTED: [CITED, OTHER]}
    hits = cg.scan_bytes(LISTED, ('arXiv:' + CITED + '\n').encode(), cg.Denylist([]), citations)
    assert [(h.line, h.rule, h.text) for h in hits] == [(0, 'stale-citation', OTHER)]


def test_instruction_units_carry_their_source_files_citations():
    """A unit record copied into a derived catalogue carries exactly the identifiers listed for the
    file it states as its source; a unit from an unlisted source, another file's identifier, or a
    line that is not a unit record is refused as before."""
    catalogue = 'src/ravel/data/instructions/catalogue.json'
    citations = {LISTED: [CITED]}
    listed_unit = json.dumps({'id': LISTED + '#section/1', 'source': LISTED, 'text': ['see arXiv:' + CITED]})
    by_id = json.dumps({'id': LISTED + '#section/2', 'text': 'arXiv:' + CITED})
    unlisted = json.dumps({'id': 'docs/other.md#section/1', 'source': 'docs/other.md', 'text': ['arXiv:' + CITED]})
    foreign = json.dumps({'id': LISTED + '#section/3', 'source': LISTED, 'text': ['arXiv:' + OTHER]})
    plain = '{"note": "arXiv:' + CITED + '"}'
    assert _scan(catalogue, listed_unit + ',\n' + by_id + '\n', citations) == []
    assert _scan(catalogue, listed_unit + ',\n' + unlisted + '\n', citations) == [(2, 'arxiv-id')]
    assert _scan(catalogue, foreign + '\n', citations) == [(1, 'arxiv-id')]
    assert _scan(catalogue, plain + '\n', citations) == [(1, 'arxiv-id')]
    assert _scan(catalogue, listed_unit + '\n', {}) != []


def test_overlapping_complete_citations_retain_each_source_occurrence():
    name = 'Cobalt' + 'Search' + '2031'
    qualified = name + '-specific'
    assert _scan(LISTED, qualified, {LISTED: [name, qualified]}) == [(0, 'stale-citation')]
    assert _scan(LISTED, qualified + '\n' + name, {LISTED: [name, qualified]}) == []


def test_cited_routine_name_preserves_a_changed_hyphenated_identifier():
    name = 'Cobalt' + 'Search' + '2031'
    text = name + '\n' + name + '-other\n'
    assert _scan(LISTED, text, {LISTED: [name]}) == [(2, 'routine-name')]


@pytest.mark.parametrize('string', [CITED + ' extra', 'prefix ' + CITED, '10.' + '1103/Phys'])
def test_citations_require_a_complete_identifier(tmp_path, string):
    path = tmp_path / 'citations.json'
    path.write_text(json.dumps(cg.citations_document({LISTED: [string]})))
    with pytest.raises(ValueError, match='not a citable identifier'):
        cg.load_citations(path)


def test_one_citation_covers_one_identifier(tmp_path):
    routine = U(['QX', '2098', 'I9999999'])
    path = tmp_path / 'citations.json'
    path.write_text(json.dumps(cg.citations_document({LISTED: [routine + '/' + OTHER]})))
    with pytest.raises(ValueError, match='not a citable identifier'):
        cg.load_citations(path)


def test_complete_versioned_citations_include_the_earlier_number_width(tmp_path):
    identifier = '1310' + '.9999v2'
    path = tmp_path / 'citations.json'
    path.write_text(json.dumps(cg.citations_document({LISTED: [identifier]})))
    assert cg.load_citations(path) == {LISTED: [identifier]}
    assert _scan(LISTED, 'https://arxiv.org/abs/' + identifier, {LISTED: [identifier]}) == []


def test_complete_qualified_source_identifiers_preserve_numeric_counterfactuals(tmp_path):
    routine = U(['QX', '2098', 'I9999999', 'ALT'])
    prefixed = 'LOCAL_' + routine
    code = J(['PX', 'ABCD', '2098', '11', 'TAG'])
    doi = '10.' + '17182/hepdata.' + '999999.v1/t1'
    path = tmp_path / 'citations.json'
    path.write_text(json.dumps(cg.citations_document({LISTED: [routine, prefixed, code, doi]})))
    citations = cg.load_citations(path)
    assert _scan(LISTED, '\n'.join([routine, prefixed, code, doi]), citations) == []
    for changed in [routine.replace('9999999', '8888888'), prefixed.replace('LOCAL_', 'OTHER_'),
                    code.replace('11', '12'), doi.replace('.v1/', '.v2/')]:
        assert _scan(LISTED, '\n'.join([routine, prefixed, code, doi, changed]), citations)


def test_citation_masking_preserves_identifiers_with_changed_suffixes():
    routine = U(['QX', '2098', 'I9999999'])
    citations = {LISTED: [routine, CITED, DOI]}
    assert _scan(LISTED, routine + ' arXiv:' + CITED + ' doi:' + DOI, citations) == []
    for original, changed in [(routine, routine + '1'), (CITED, CITED + 'v2'), (DOI, DOI + '6')]:
        text = routine + ' arXiv:' + CITED + ' doi:' + DOI + '\n' + changed
        assert _scan(LISTED, text, citations), (original, changed)


def test_cited_code_preserves_other_identifiers_with_extra_segments():
    code = J(['ABCD', '2098', '11'])
    text = code + '\nQX-' + code
    assert _scan(LISTED, text, {LISTED: [code]}) == [(2, 'analysis-code')]


@pytest.mark.parametrize('escape', ['\\n', '\\r', '\\t'])
def test_exact_identifiers_follow_escaped_whitespace(escape):
    routine = U(['QX', '2098', 'I9999999'])
    assert _scan(LISTED, '"' + escape + routine + '"', {LISTED: [routine]}) == []
    assert _scan(LISTED, '"' + escape + routine + '1"', {LISTED: [routine]})


def test_prefix_migration_extracts_complete_identifiers_from_exact_source_bytes(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('expand_citations',
                ROOT / 'scripts/maintenance/expand_generality_citations.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / LISTED
    source.parent.mkdir(parents=True)
    first, second = DOI, DOI + '6'
    source.write_text('doi:' + first + '\ndoi:' + second + '\n')
    prefix = '10.' + '1103/Phys'
    migrated = module.expand(tmp_path, cg.citations_document({LISTED: [prefix]}))
    assert migrated['files'][LISTED] == sorted([first, second])
    assert _scan(LISTED, source.read_text(), migrated['files']) == []
    source.write_text('clean\n')
    with pytest.raises(ValueError, match='requires a complete source identifier'):
        module.expand(tmp_path, cg.citations_document({LISTED: [prefix]}))


def test_migration_preserves_separate_complete_identifiers_in_resource_paths(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('resource_citations',
                ROOT / 'scripts/maintenance/expand_generality_citations.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    record, code = 'ins' + '9999991', J(['ABCD', '2098', '11'])
    source = tmp_path / LISTED
    source.parent.mkdir(parents=True)
    source.write_text(record + '/' + code + '.pdf\n')
    migrated = module.expand(tmp_path, cg.citations_document({LISTED: [record, code]}))
    assert migrated['files'][LISTED] == sorted([record, code + '.pdf'])
    assert _scan(LISTED, source.read_text(), migrated['files']) == []


def test_a_cited_identifier_in_the_file_name_passes_only_for_the_listed_file():
    name = 'src/ravel/data/spectrum/decay-table-' + CITED + '.dat'
    text = 'see https://arxiv.org/abs/' + CITED + '\n'
    assert _scan(name, text, {name: [CITED]}) == []
    assert _scan(name, 'clean\n', {name: [CITED]}) == []
    assert _scan(name, text, {}) == [(1, 'arxiv-id')]


def test_a_listed_archive_passes_with_its_members_and_no_other_archive_does(tmp_path):
    import io
    import zipfile
    value = '1604' + '.63665'          # a number in copied source that has the form of a literature number
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('pkg/constants.py', 'RATES = {"a": ' + value + '}\n')
        archive.writestr('pkg/notes.md', 'clean\n')
    listed = 'tests/fixtures/source-archive.zip'
    deny = cg.Denylist([])
    assert cg.scan_bytes(listed, buffer.getvalue(), deny, {listed: [value]}) == []
    assert [(h.path, h.rule) for h in cg.scan_bytes(listed, buffer.getvalue(), deny, {})] == [
        (listed + '!pkg/constants.py', 'arxiv-id')]
    assert cg.scan_bytes('tests/fixtures/another.zip', buffer.getvalue(), deny, {listed: [value]}) != []
    hits = cg.scan_bytes(listed, buffer.getvalue(), deny, {listed: [value, CITED]})
    assert [(h.path, h.rule, h.text) for h in hits] == [(listed, 'stale-citation', CITED)]


def test_the_citation_list_never_admits_a_placeholder():
    placeholder = ZERO + '.00014'
    text = 'arXiv:' + placeholder + ' and ' + J(['ANA', '9003', '01']) + ' and Routine' + '001\n'
    # even a (hand-built) list that names them changes nothing: the loader refuses such a list
    assert {rule for _, rule in _scan(LISTED, text, {LISTED: [CITED]})} >= set(cg.PLACEHOLDER_RULES)


@pytest.mark.parametrize('files,message', [
    ({LISTED: ['some free text']}, 'not a citable identifier'),
    ({LISTED: [ZERO + '.00014']}, 'not a citable identifier'),
    ({LISTED: [J(['ANA', '9003', '01'])]}, 'not a citable identifier'),
    ({LISTED: []}, 'one exact file path'),
    ({LISTED: [CITED, CITED]}, 'one exact file path'),
    ({'src/ravel/data/**/*.json': [CITED]}, 'one exact file path'),
    ({'src/ravel/data/*/SOURCE.json': [CITED]}, 'one exact file path'),
    ({'../outside.json': [CITED]}, 'one exact file path'),
    ({'/absolute.json': [CITED]}, 'one exact file path'),
])
def test_the_citation_list_holds_exact_paths_and_citable_identifiers_only(tmp_path, files, message):
    path = tmp_path / 'citations.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': 'generality-citations', 'purpose': 'x', 'files': files}))
    with pytest.raises(ValueError, match=message):
        cg.load_citations(path)
    assert cg.main(['--tree', str(tmp_path), '--citations', str(path)]) == 2


def test_entries_of_withheld_files_sit_under_their_own_last_key(tmp_path):
    withheld = 'tests/fixtures/withheld-copy.txt'
    document = cg.citations_document({'NOTICE': [CITED]}, {withheld: [OTHER]})
    assert list(document)[-1] == 'withheld_files' and 'withheld_files' not in cg.citations_document({'NOTICE': [CITED]})
    path = tmp_path / 'citations.json'
    path.write_text(json.dumps(document))
    assert cg.load_citations(path) == {'NOTICE': [CITED], withheld: [OTHER]}
    document['withheld_files']['NOTICE'] = [CITED]
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='not a version-1 generality citation list'):
        cg.load_citations(path)


def test_command_line_applies_the_given_citation_list(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cg, '_CITATIONS', None)
    tree = tmp_path / 'tree'
    (tree / 'docs').mkdir(parents=True)
    (tree / 'NOTICE').write_text('Cite arXiv:' + CITED + ' (' + REPORT + ').\n')
    (tree / 'docs/other.md').write_text('clean\n')
    listing = tmp_path / 'citations.json'
    listing.write_text(json.dumps(cg.citations_document({'NOTICE': [CITED, REPORT]})))
    empty = tmp_path / 'none.json'
    empty.write_text(json.dumps(cg.citations_document({})))
    assert cg.main(['--tree', str(tree), '--citations', str(listing)]) == 0
    assert cg.main(['--tree', str(tree), '--citations', str(empty)]) == 1
    (tree / 'docs/other.md').write_text('Cite arXiv:' + CITED + '.\n')
    capsys.readouterr()
    assert cg.main(['--tree', str(tree), '--citations', str(listing)]) == 1
    assert capsys.readouterr().out.splitlines() == ['docs/other.md:1: arxiv-id']
    monkeypatch.setattr(cg, '_CITATIONS', None)


def test_shipped_citation_list_is_exact_for_this_tree():
    """Every listed file exists and carries each of its identifiers; the list itself and the listed
    files pass the gate, and the same identifiers are refused under any other file name."""
    citations = cg.load_citations()
    assert citations and set(json.loads(cg.CITATIONS.read_text())) - {'withheld_files'} == {'schema_version', 'kind', 'purpose', 'files'}
    deny = cg.Denylist([])
    assert cg.scan_bytes(cg.CITATION_LIST, cg.CITATIONS.read_bytes(), deny, citations) == []
    assert cg.scan_bytes('docs/copy-of-the-list.json', cg.CITATIONS.read_bytes(), deny, citations) != []
    present = [name for name in citations if (ROOT / name).is_file()]
    if (ROOT / '.git').exists():
        # A source checkout holds every listed file; a released tree may lack the withheld ones.
        assert present == list(citations)
    assert present
    source_findings = {}
    for name in present:
        data = (ROOT / name).read_bytes()
        findings = cg.scan_bytes(name, data, deny, citations)
        if findings:
            source_findings[name] = [(h.rule, h.text) for h in findings]
        copy = name.rpartition('/')[0] + '/copy-of-' + name.rpartition('/')[2] if '/' in name else 'copy-of-' + name
        assert cg.scan_bytes(copy, data, deny, citations) != [], name
        assert cg.scan_bytes(name, data, deny, {}) != [], name
    assert source_findings == {}, json.dumps(source_findings, indent=1)


def test_tracked_files_carry_no_placeholder_identifier():
    """The three placeholder shapes occur in no tracked file (a source checkout; a released tree is
    covered by the export's own run of the gate)."""
    if not (ROOT / '.git').exists():
        pytest.skip('not a source checkout')
    shapes = '|'.join(['arXiv:' + ZERO + r'\.', ZERO + r'\.[0-9]{5}', 'ANA-' + '9[0-9]{3}-[0-9]{2}', 'Routine' + '00[0-9]'])
    result = subprocess.run(['/usr/bin/git', '-C', str(ROOT), 'grep', '-I', '-l', '-E', shapes],
                            capture_output=True, text=True)
    assert result.returncode == 1 and result.stdout == '', result.stdout


def test_hashed_denylist_matches_spacing_case_and_camel_variants():
    entry = cg.entry_for('Fable Quarry', 'challenge')
    assert 'fable' not in json.dumps(entry).lower()
    deny = cg.Denylist([entry])
    for text in ('the FableQuarry suite', 'fable-quarry', 'FABLE_QUARRY', 'Fable Quarry\n', 'fablequarry'):
        assert _rules(text, deny) == ['denylist:challenge'], text
    assert _rules('fable quarrying and a fabled quarry', deny) == []


def test_single_letters_never_join_into_a_term():
    deny = cg.Denylist([cg.entry_for('QQQ', 'study')])
    assert _rules('QQQ and the qqq run', deny) == ['denylist:study']
    assert _rules('["Q", "Q", "Q"] and q q q', deny) == []


def test_binary_files_are_scanned_through_their_printable_text_only():
    deny = cg.Denylist([cg.entry_for('QQQ', 'study')])
    noise = bytes([0x89, 0xff, 0x00]) + b'QQQ' + bytes([0xfe, 0x01])
    assert cg.scan_bytes('a.png', noise, deny) == []
    embedded = bytes([0x89, 0xff]) + b'tEXtComment: the QQQ figure' + bytes([0x00])
    assert [h.rule for h in cg.scan_bytes('a.png', embedded, deny)] == ['denylist:study']


def test_external_lists_join_the_denylist(tmp_path, monkeypatch):
    terms = tmp_path / 'terms.txt'
    terms.write_text('# comment\nZebra Lantern\n')
    deny = tmp_path / 'deny.json'
    deny.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources',
                                'documents': [{'label': 'x', 'sha256': 'ab' * 32}],
                                'fingerprints': ['Quokka Tablet']}))
    monkeypatch.setenv('RAVEL_EVAL_TERMS_FILE', str(terms))
    monkeypatch.setenv('RAVEL_EVAL_TERMS', 'Marmot Index')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(deny))
    loaded = cg.load_denylist(None)
    text = 'zebra-lantern, MarmotIndex, quokka tablet, ' + 'ab' * 32
    assert _rules(text, loaded) == ['denylist:external', 'denylist:restricted-document']


def test_allowlist_is_empty_by_default_and_exact():
    assert cg.load_allowlist(None) == {}
    bad = J(['ATLAS', 'EXOT', '2099', '07'])
    hits = cg.scan_text(bad, cg.Denylist([]), path='a.md')
    assert cg.apply_allowlist(hits, {'a.md': ['analysis-code']}, {'a.md'}) == ([], [])
    kept, stale = cg.apply_allowlist(hits, {'a.md': ['arxiv-id'], 'gone.md': ['x']}, {'a.md'})
    assert [h.rule for h in kept] == ['analysis-code']
    assert sorted(stale) == ['a.md: stale allowlist rule arxiv-id', 'gone.md: allowlist names a file not scanned']


def test_paths_gzip_and_zip_members_are_scanned(tmp_path):
    import gzip
    import zipfile
    code = J(['CMS', 'XYZ', '97', '001'])
    (tmp_path / ('notes-' + code + '.md')).write_text('clean\n')
    with gzip.open(tmp_path / 'blob.json.gz', 'wt') as handle:
        handle.write('{"x": "' + 'arXiv:' + '2601' + '.99999' + '"}')
    with zipfile.ZipFile(tmp_path / 'pack.zip', 'w') as archive:
        archive.writestr('inner/' + U(['ATLAS', '2098', 'I' + '9999999']) + '.yoda', 'x')
    report = cg.scan_tree(tmp_path, cg.Denylist([]))
    found = {(h.path.split('!')[0], h.rule) for h in report}
    assert (('notes-' + code + '.md'), 'analysis-code') in found
    assert ('blob.json.gz', 'arxiv-id') in found
    assert ('pack.zip', 'routine-id') in found


def test_output_never_echoes_a_denylisted_term(tmp_path, capsys):
    (tmp_path / 'a.md').write_text('the FableQuarry suite\n')
    denyfile = tmp_path / 'deny.json'
    denyfile.write_text(json.dumps(cg.denylist_document([cg.entry_for('Fable Quarry', 'challenge')])))
    out_dir = tmp_path / 'tree'
    out_dir.mkdir()
    (out_dir / 'a.md').write_text('the FableQuarry suite\n')
    rc = cg.main(['--tree', str(out_dir), '--denylist', str(denyfile), '--show'])
    out = capsys.readouterr()
    assert rc == 1
    assert 'a.md:1: denylist:challenge' in out.out
    assert 'fable' not in (out.out + out.err).lower()


def test_add_term_writes_only_a_digest(tmp_path, monkeypatch):
    denyfile = tmp_path / 'deny.json'
    denyfile.write_text(json.dumps(cg.denylist_document([])))
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO('Velvet Otter\n'))
    assert cg.main(['--denylist', str(denyfile), '--add-term', 'person']) == 0
    text = denyfile.read_text()
    assert 'velvet' not in text.lower() and 'otter' not in text.lower()
    assert cg.load_denylist(denyfile).match('VelvetOtter') == 'person'


def test_shipped_denylist_is_valid_and_carries_no_plain_terms():
    path = ROOT / 'src/ravel/data/generality/denylist.json'
    document = json.loads(path.read_text())
    assert set(document) == {'schema_version', 'kind', 'purpose', 'entries'}
    cats = {e['category'] for e in document['entries']}
    assert cats <= set(cg.CATEGORIES)
    assert all(set(e) == {'digest', 'category', 'length'} for e in document['entries'])


def test_staged_mode_scans_the_index_content(tmp_path):
    repo = tmp_path / 'r'
    repo.mkdir()
    git = ['/usr/bin/git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
    subprocess.run(git + ['init', '-q'], check=True)
    (repo / 'a.md').write_text('clean\n')
    subprocess.run(git + ['add', 'a.md'], check=True)
    assert cg.main(['--root', str(repo), '--staged']) == 0
    (repo / 'a.md').write_text('see ' + J(['ABCD', '2098', '11']) + '\n')
    subprocess.run(git + ['add', 'a.md'], check=True)
    (repo / 'a.md').write_text('clean again, but unstaged\n')
    assert cg.main(['--root', str(repo), '--staged']) == 1


def test_script_runs_standalone_without_the_package():
    result = subprocess.run([sys.executable, '-S', str(ROOT / 'src/ravel/validation/check_generality.py'),
                             '--help'], capture_output=True, text=True)
    assert result.returncode == 0 and 'generality' in result.stdout.lower()


def test_a_large_tree_is_scanned_in_workers_with_the_same_findings(tmp_path):
    deny = cg.Denylist([cg.entry_for('Fable Quarry', 'challenge')])
    for i in range(80):
        (tmp_path / f'f{i:02d}.md').write_text('FableQuarry\n' if i % 7 == 0 else 'clean\n')
    serial = [h for p in sorted(tmp_path.iterdir()) for h in cg.scan_bytes(p.name, p.read_bytes(), deny)]
    assert sorted(cg.scan_tree(tmp_path, deny), key=str) == sorted(serial, key=str)
    assert len(serial) == 12
