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
V2_FIXTURE = FIXTURE.with_name('synthetic-tables-v2.json')


def tables_v2():
    return json.loads(V2_FIXTURE.read_text())


def test_v2_unresolved_citation_names_key():
    doc = tables_v2(); doc['rows'][3]['citation_key'] = 'synthetic-unknown'
    assert any(f['field_path'] == 'rows[3].citation_key' and f['kind'] == 'citation'
               for f in cm.check_higgs_tables(doc))


def test_v2_coefficient_requires_locator():
    doc = tables_v2(); del doc['rows'][4]['locator']
    assert any(f['field_path'] == 'rows[4].locator' for f in cm.check_higgs_tables(doc))


def test_v2_overlapping_bins_name_boundaries():
    doc = tables_v2(); doc['rows'][7]['boundaries']['synthetic-axis']['lower'] = 0.5
    assert any(f['field_path'] == 'rows[7].boundaries' and f['kind'] == 'overlap'
               for f in cm.check_higgs_tables(doc))


def extractor():
    import runpy
    path = Path(__file__).resolve().parents[2] / 'scripts/maintenance/extract_higgs_tables_v2.py'
    return runpy.run_path(str(path))


def test_v2_assembly_preserves_legacy_and_stamps_provenance():
    base = tables(); fixture = tables_v2()
    additions = {'citations': {}, 'rows': fixture['rows'][3:], 'ratios': []}
    doc = extractor()['assemble'](base, additions)
    assert not cm.check_higgs_tables(doc)
    assert doc['rows'][:3] == base['rows'] and doc['ratios'] == base['ratios']
    script = Path(extractor()['__file__'])
    assert all(r['locator']['extraction_script_sha256'] == sha256(script.read_bytes()).hexdigest()
               for r in doc['rows'][3:])


def test_v2_assembly_refuses_replacement_of_legacy_citation():
    additions = {'citations': {'synthetic-source': {'title': 'changed'}}, 'rows': [], 'ratios': []}
    with pytest.raises(cm.ConstantsError, match='citation'):
        extractor()['assemble'](tables(), additions)


def test_v2_install_steps_require_reviewed_table_pin(tmp_path):
    source = installed_fixture(tmp_path)
    source['table'].update(url='https://example.invalid/tables',
                           sha256='a' * 64, bytes=5, licence='CC0-1.0')
    steps = cm.higgs_reference_install_steps(source, '/supplied/cache')
    assert steps[0]['kind'] == 'download' and steps[0]['sha256'] == 'a' * 64
    source['table']['sha256'] = 'not-a-digest'
    with pytest.raises(cm.ConstantsError, match='pin'):
        cm.higgs_reference_install_steps(source, '/supplied/cache')


def test_v2_install_refuses_unreviewed_redistribution_licence():
    source = {'table': {'path': 'tables.json', 'url': 'https://example.invalid/tables',
                        'sha256': 'a' * 64, 'bytes': 5, 'licence': 'unknown'}}
    with pytest.raises(cm.ConstantsError, match='licence'):
        cm.higgs_reference_install_steps(source, '/supplied/cache')


def test_v2_fixture_covers_all_kinds_and_recomputes_ratios():
    doc = tables_v2()
    assert not cm.check_higgs_tables(doc)
    assert {'total_width', 'kappa_coefficient', 'c1_coefficient', 'stxs_bin'} <= {
        row['quantity'] for row in doc['rows']}
    computed = cm.recompute_higgs_ratios(doc)
    assert abs(computed['synthetic-width-ratio'] - 1.5) <= 1e-9
    assert abs(computed['synthetic-energy-ratio'] - 2) <= 1e-9


def test_v2_preserves_every_installed_v1_row_and_doctor_readiness():
    from ravel.workflow.recast_route import higgs_reference_readiness
    base = cm.load_higgs_tables(version=1)
    doc = extractor()['assemble'](base, {'citations': {}, 'rows': [], 'ratios': []})
    for section in ('rows', 'ratios'):
        assert json.dumps(doc[section], sort_keys=True).encode() == json.dumps(base[section], sort_keys=True).encode()
    assert higgs_reference_readiness()['readiness'] == 'ready'


def test_v2_loader_uses_installed_cache_and_refuses_wrong_version(tmp_path, monkeypatch):
    root = tmp_path / 'higgs-tables-v2'; root.mkdir()
    source = installed_fixture(root)
    raw = V2_FIXTURE.read_bytes(); (root / 'tables.json').write_bytes(raw)
    source['table']['sha256'] = sha256(raw).hexdigest()
    (root / 'SOURCE.json').write_text(json.dumps(source))
    monkeypatch.setenv('RAVEL_CACHE_DIR', str(tmp_path))
    assert cm.load_higgs_tables(version=2, allow_synthetic=True)['schema_version'] == 2
    with pytest.raises(cm.ConstantsError, match='version'):
        cm.load_higgs_tables(root, version=1, allow_synthetic=True)
    with pytest.raises(cm.ConstantsError, match='synthetic'):
        cm.load_higgs_tables(root, version=2)


@pytest.mark.parametrize('section', ['rows', 'ratios'])
def test_v2_legacy_digest_refuses_mutation_and_deletion(section):
    doc = tables_v2(); doc[section][0]['value'] += 0.1
    assert any(f['kind'] == 'identity' for f in cm.check_higgs_tables(doc))
    doc = tables_v2(); del doc[section][0]
    assert any(f['kind'] == 'identity' for f in cm.check_higgs_tables(doc))


@pytest.mark.parametrize('mutation', ['inverted', 'axis', 'unit', 'duplicate', 'nonfinite', 'empty'])
def test_v2_malformed_bins_are_refused(mutation):
    doc = tables_v2(); row = doc['rows'][7]; bounds = row['boundaries']['synthetic-axis']
    if mutation == 'inverted': bounds['lower'] = 2
    elif mutation == 'axis': row['boundaries'] = {'synthetic-other-axis': bounds}
    elif mutation == 'unit': bounds['unit'] = '1'
    elif mutation == 'duplicate': row['bin_id'] = doc['rows'][6]['bin_id']
    elif mutation == 'nonfinite': bounds['upper'] = float('inf')
    else: row['boundaries'] = {}
    assert cm.check_higgs_tables(doc)


def test_v2_bin_overlap_requires_intersection_in_every_axis():
    doc = tables_v2()
    for row in doc['rows'][6:8]:
        row['boundaries']['synthetic-axis'] = {'lower': None, 'upper': None, 'unit': '1'}
    doc['rows'][6]['boundaries']['synthetic-second-axis'] = {'lower': None, 'upper': 2, 'unit': '1'}
    doc['rows'][7]['boundaries']['synthetic-second-axis'] = {'lower': 2, 'upper': None, 'unit': '1'}
    assert not cm.check_higgs_tables(doc)
    doc['rows'][7]['boundaries']['synthetic-second-axis']['lower'] = 1
    assert any(f['kind'] == 'overlap' for f in cm.check_higgs_tables(doc))


@pytest.mark.parametrize('field', ['pdf_page', 'table', 'source_line', 'extraction_script_sha256'])
def test_v2_new_row_requires_complete_locator(field):
    doc = tables_v2(); del doc['rows'][4]['locator'][field]
    assert cm.check_higgs_tables(doc)


def test_v2_extractor_cli_keeps_existing_output(tmp_path, capsys):
    additions = tmp_path / 'additions.json'
    additions.write_text(json.dumps({'citations': {}, 'rows': [], 'ratios': []}))
    output = tmp_path / 'tables.json'
    args = ['--base', str(FIXTURE), '--additions', str(additions), '--output', str(output)]
    assert extractor()['main'](args) == 0
    assert json.loads(capsys.readouterr().out)['sha256'] == sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        extractor()['main'](args)


def test_v2_install_steps_use_existing_installer_with_fake_fetcher(tmp_path):
    from types import SimpleNamespace
    from ravel.setup.steps import run_step
    from ravel.setup.manifest import _check_step
    raw = V2_FIXTURE.read_bytes()
    cache = tmp_path / 'download.json'; cache.write_bytes(raw)
    destination = tmp_path / 'installed'; destination.mkdir()
    source = installed_fixture(destination)
    source['table'].update(url='https://example.invalid/tables', bytes=len(raw),
                           sha256=sha256(raw).hexdigest(), licence='CC0-1.0')
    (destination / 'tables.json').unlink()
    calls = []

    def fetch(url, pin):
        calls.append((url, pin))
        assert sha256(cache.read_bytes()).hexdigest() == pin['sha256']
        return cache

    context = SimpleNamespace(values={}, fetcher=SimpleNamespace(fetch=fetch), adopt=False)
    step_ids = set()
    for step in cm.higgs_reference_install_steps(source, destination):
        _check_step('synthetic-data', step, step_ids)
        run_step(step, context)
    assert len(calls) == 1
    assert cm.load_higgs_tables(destination, version=2, allow_synthetic=True) == tables_v2()


def test_v2_installer_refuses_incomplete_source_registration():
    source = {'table': {'path': 'tables.json', 'url': 'https://example.invalid/tables',
                        'sha256': 'a' * 64, 'bytes': 5, 'licence': 'CC0-1.0'}}
    with pytest.raises(cm.ConstantsError, match='registration'):
        cm.higgs_reference_install_steps(source, '/supplied/cache')


def test_v2_physics_tables_must_inherit_exactly_the_installed_v1_population(tmp_path):
    base = cm.load_higgs_tables(version=1)
    source = cm.load_higgs_source()

    def install(document, name):
        root = tmp_path / name; root.mkdir()
        raw = json.dumps(document).encode(); (root / 'tables.json').write_bytes(raw)
        pin = {'path': 'tables.json', 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
        (root / 'SOURCE.json').write_text(json.dumps({**source, 'table': pin}))
        return root

    doc = extractor()['assemble'](base, {'citations': {}, 'rows': [], 'ratios': []})
    assert cm.load_higgs_tables(install(doc, 'whole'), version=2) == doc
    dropped = json.loads(json.dumps(doc))
    used = {r[side] for r in dropped['ratios'] for side in ('numerator', 'denominator')}
    gone = next(r for r in dropped['rows'] if r['id'] not in used)
    dropped['rows'].remove(gone); del dropped['legacy_rows_sha256'][gone['id']]
    assert not cm.check_higgs_tables(dropped)  # self-consistent, yet not the installed population
    with pytest.raises(cm.ConstantsError, match='inherit'):
        cm.load_higgs_tables(install(dropped, 'dropped'), version=2)
    added = json.loads(json.dumps(doc)); new = dict(added['rows'][0], id='unlocated-row')
    added['rows'].append(new)
    added['legacy_rows_sha256'][new['id']] = cm._higgs_row_digest(new)
    with pytest.raises(cm.ConstantsError, match='inherit'):
        cm.load_higgs_tables(install(added, 'added'), version=2)
