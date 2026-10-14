"""All table numbers here are synthetic arithmetic fixtures, never physics inputs."""
from hashlib import sha256
import json
from pathlib import Path
import pytest
from ravel.validation import constants_manifest as cm

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/higgs-reference/synthetic-tables.json'


def tables():
    return json.loads(FIXTURE.read_text())


def installed_fixture(tmp_path):
    raw = FIXTURE.read_bytes()
    (tmp_path / 'tables.json').write_bytes(raw)
    primary = b'Synthetic primary reference bytes; not physics data.\n'
    (tmp_path / 'synthetic-source.txt').write_bytes(primary)
    source = {'schema_version': 1, 'kind': 'higgs-reference-source', 'status': 'installed',
              'table': {'path': 'tables.json', 'sha256': sha256(raw).hexdigest()},
              'source_files': [{'path': 'synthetic-source.txt', 'sha256': sha256(primary).hexdigest(),
                                'url': 'synthetic://reference/source'}]}
    (tmp_path / 'SOURCE.json').write_text(json.dumps(source))
    return source


@pytest.mark.parametrize('mutation,kind', [('missing', 'uncited'), ('unknown', 'citation'), ('envelope', 'envelope')])
def test_table_refuses_missing_citation_and_outside_envelope(mutation, kind):
    doc = tables()
    if mutation == 'missing': del doc['rows'][0]['citation_key']
    elif mutation == 'unknown': doc['rows'][0]['citation_key'] = 'synthetic-unknown'
    else: doc['rows'][0]['value'] = 15
    assert any(f['kind'] == kind and f['field_path'] == 'rows[0].value'
               for f in cm.check_document(doc))


def test_ratio_is_recomputed_and_tampering_is_refused():
    doc = tables(); doc['ratios'][0]['value'] = 4
    assert any(f['kind'] == 'ratio' for f in cm.check_document(doc))
    doc['ratios'][0]['value'] = 3
    assert cm.check_document(doc) == []
    assert cm.recompute_higgs_ratios(doc) == {'synthetic-ratio': 3.0}


def test_installed_table_and_primary_bytes_are_pinned(tmp_path):
    installed_fixture(tmp_path)
    assert cm.load_higgs_tables(tmp_path, allow_synthetic=True)['synthetic'] is True
    (tmp_path / 'tables.json').write_text('{}')
    with pytest.raises(cm.ConstantsError, match='checksum'):
        cm.load_higgs_tables(tmp_path, allow_synthetic=True)


def test_changed_primary_source_is_refused(tmp_path):
    installed_fixture(tmp_path)
    (tmp_path / 'synthetic-source.txt').write_text('changed synthetic source')
    with pytest.raises(cm.ConstantsError, match='checksum'):
        cm.load_higgs_tables(tmp_path, allow_synthetic=True)


def test_synthetic_table_cannot_be_used_as_physics_reference(tmp_path):
    installed_fixture(tmp_path)
    with pytest.raises(cm.ConstantsError, match='synthetic'):
        cm.load_higgs_tables(tmp_path)


def test_installed_source_pins_primary_files_and_real_tables():
    source = cm.load_higgs_source()
    assert source['status'] == 'installed' and source['physics_values_installed'] is True
    assert all(r['url'].startswith('https://') and r['expected_filename'] for r in source['sources'])
    assert {p['path'] for p in source['source_files']} == {r['expected_filename'] for r in source['sources']}
    assert all(p['url'].startswith('https://arxiv.org/pdf/') and p['bytes'] > 0 for p in source['source_files'])
    document = cm.load_higgs_tables()
    assert document['synthetic'] is False and document['rows'] and document['ratios']
    assert not cm.check_higgs_tables(document)
    assert set(source['table_locators']) == {r['id'] for r in document['rows']}
    assert cm.recompute_higgs_ratios(document)


def test_absent_installation_is_a_hold(tmp_path):
    source = cm.load_higgs_source()
    held = dict(source, status='not installed — owner action: approve download')
    (tmp_path / 'SOURCE.json').write_text(json.dumps(held))
    with pytest.raises(cm.ConstantsError, match='approve download'):
        cm.load_higgs_tables(tmp_path)


@pytest.mark.parametrize('mutation', ['order', 'negative', 'nonfinite', 'unit', 'zero', 'duplicate', 'ratio-citation'])
def test_malformed_tables_and_ratio_inputs_are_refused(mutation):
    doc = tables()
    if mutation == 'order': del doc['rows'][0]['order']
    elif mutation == 'negative': doc['rows'][0]['uncertainty']['minus'] = -1
    elif mutation == 'nonfinite': doc['rows'][0]['value'] = float('nan')
    elif mutation == 'unit': doc['rows'][1]['unit'] = 'fb'
    elif mutation == 'zero': doc['rows'][1]['value'] = 0
    elif mutation == 'duplicate': doc['rows'][1]['id'] = doc['rows'][0]['id']
    elif mutation == 'ratio-citation': del doc['ratios'][0]['citation_key']
    assert cm.check_higgs_tables(doc)
    with pytest.raises(cm.ConstantsError):
        cm.recompute_higgs_ratios(doc)


def test_citation_locator_must_resolve_to_pinned_primary(tmp_path):
    installed_fixture(tmp_path)
    doc = tables(); doc['citations']['synthetic-source']['locator'] = 'synthetic://wrong/source'
    raw = json.dumps(doc).encode(); (tmp_path / 'tables.json').write_bytes(raw)
    source = json.loads((tmp_path / 'SOURCE.json').read_text())
    source['table']['sha256'] = sha256(raw).hexdigest()
    (tmp_path / 'SOURCE.json').write_text(json.dumps(source))
    with pytest.raises(cm.ConstantsError, match='resolve'):
        cm.load_higgs_tables(tmp_path, allow_synthetic=True)


@pytest.mark.parametrize('path', ['../tables.json', '/tables.json'])
def test_pins_cannot_escape_reference_directory(tmp_path, path):
    source = installed_fixture(tmp_path); source['table']['path'] = path
    (tmp_path / 'SOURCE.json').write_text(json.dumps(source))
    with pytest.raises(cm.ConstantsError, match='basename'):
        cm.load_higgs_tables(tmp_path, allow_synthetic=True)


def test_table_symlink_is_refused(tmp_path):
    installed_fixture(tmp_path)
    (tmp_path / 'tables.json').unlink()
    (tmp_path / 'tables.json').symlink_to(FIXTURE)
    with pytest.raises(cm.ConstantsError, match='ordinary local'):
        cm.load_higgs_tables(tmp_path, allow_synthetic=True)


def test_nested_table_findings_and_cli_failure_name_paths(tmp_path, capsys):
    doc = tables(); del doc['rows'][0]['citation_key']
    findings = cm.check_document({'nested': doc})
    assert any(f['field_path'] == 'nested.rows[0].value' and f['kind'] == 'uncited' for f in findings)
    path = tmp_path / 'tables.json'; path.write_text(json.dumps(doc))
    assert cm.main([str(path)]) == 1
    assert 'rows[0].value' in capsys.readouterr().out


def test_source_documents_are_fetched_on_demand_and_verified(tmp_path):
    source = cm.load_higgs_source()
    pin = source['source_files'][1]
    assert not list(cm.HIGGS_REFERENCE.glob('*.pdf'))
    good = b'x' * 5
    fake = dict(source, source_files=[dict(pin, bytes=5, sha256=sha256(good).hexdigest())])
    (tmp_path / 'SOURCE.json').write_text(json.dumps(fake))
    cache = tmp_path / 'cache'
    path = cm.fetch_higgs_source(pin['path'], cache, directory=tmp_path, opener=lambda url: good)
    assert path.read_bytes() == good and cache in path.parents
    with pytest.raises(cm.ConstantsError, match='pin'):
        cm.fetch_higgs_source(pin['path'], tmp_path / 'c2', directory=tmp_path, opener=lambda url: b'y' * 5)
    with pytest.raises(cm.ConstantsError, match='not a pinned'):
        cm.fetch_higgs_source('other.pdf', cache, directory=tmp_path, opener=lambda url: good)


def test_installed_record_names_one_document_in_its_link_its_file_name_and_its_identifiers():
    """Each source of the installed record is one document: the link to fetch, the landing page, the
    expected file name, the pinned file and the stated identifiers carry the same literature number,
    and that number is of the real form (a placeholder cannot be fetched or cited)."""
    from ravel.validation import check_generality as cg
    source = cm.load_higgs_source()
    pins = {p['path']: p for p in source['source_files']}
    assert len(source['sources']) == len(pins) == 2
    for row in source['sources']:
        number = row['expected_filename'].removesuffix('.pdf')
        assert row['url'] == 'https://arxiv.org/pdf/' + number
        assert row['landing_url'] == 'https://arxiv.org/abs/' + number
        assert 'arXiv:' + number in row['identifiers'].split('; ')
        assert pins[row['expected_filename']]['url'] == row['url']
        assert row['sha256'] == pins[row['expected_filename']]['sha256'] and row['bytes'] == pins[row['expected_filename']]['bytes']
        assert row['landing_url'] in source['acquired']['landing_pages']
        rules = {h.rule for h in cg.scan_text(json.dumps(row), cg.Denylist([]))}
        assert 'arxiv-id' in rules and not rules & set(cg.PLACEHOLDER_RULES)


def test_installed_record_fetch_asks_for_the_pinned_link_and_checks_the_digest_under_the_expected_name(tmp_path):
    """With a stand-in fetcher (no network): the fetch step asks for exactly the recorded link, keeps
    nothing whose bytes do not match the pin, and stores verified bytes under the expected file name."""
    source = cm.load_higgs_source()
    expected = {row['expected_filename']: row for row in source['sources']}
    for pin in source['source_files']:
        asked = []

        def wrong(url, asked=asked):
            asked.append(url)
            return b'not the pinned document'
        cache = tmp_path / ('refused-' + pin['sha256'][:8])
        with pytest.raises(cm.ConstantsError, match='does not match its pin: ' + pin['path']):
            cm.fetch_higgs_source(pin['path'], cache, opener=wrong)
        assert asked == [pin['url']] == [expected[pin['path']]['url']]
        assert not (cache / pin['path']).exists()
    # The same record with each pin re-pointed at a small stand-in document: the digest is checked
    # against the bytes the link returned and the file is kept under its expected name.
    documents = {pin['url']: ('stand-in for ' + pin['path']).encode() for pin in source['source_files']}
    local = dict(source, source_files=[dict(pin, bytes=len(documents[pin['url']]),
                                            sha256=sha256(documents[pin['url']]).hexdigest())
                                       for pin in source['source_files']])
    (tmp_path / 'SOURCE.json').write_text(json.dumps(local))
    asked = []

    def fetcher(url):
        asked.append(url)
        return documents[url]
    for name, row in expected.items():
        kept = cm.fetch_higgs_source(name, tmp_path / 'cache', directory=tmp_path, opener=fetcher)
        assert kept == tmp_path / 'cache' / row['expected_filename']
        assert sha256(kept.read_bytes()).hexdigest() == sha256(documents[row['url']]).hexdigest()
    assert asked == [row['url'] for row in expected.values()]
    # A verified cached copy is not fetched again; a link that returns another document's bytes is refused.
    assert cm.fetch_higgs_source(next(iter(expected)), tmp_path / 'cache', directory=tmp_path,
                                 opener=lambda url: pytest.fail('fetched again')).is_file()
    swapped = {a: documents[b] for a, b in zip(documents, reversed(list(documents)))}
    with pytest.raises(cm.ConstantsError, match='does not match its pin'):
        cm.fetch_higgs_source(next(iter(expected)), tmp_path / 'other', directory=tmp_path, opener=swapped.__getitem__)
