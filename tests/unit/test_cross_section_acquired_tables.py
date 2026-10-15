"""Acquired cross-section tables: pinned acquisition, declared state bases, interpolation error.

The 13 TeV NLO+NLL coloured tables are published without redistribution terms, so the registry
holds no numbers for them; a row pins the public archive and its member. The mechanism tests below
use a synthetic archive and run offline. The published-value tests acquire the real archive into a
temporary cache and skip when this host cannot reach it (set RAVEL_XSEC_TEST_ARCHIVE to a local copy).
"""
import copy
import hashlib
import io
import json
import math
import os
import tarfile
from pathlib import Path

import pytest

from ravel.physics import cross_sections as xs


def request(basis, sqrt_s=13000, order='NLO+NLL', pdf='as-published', scale='as-published', **extra):
    return {'schema_version': 1, 'basis': basis, 'sqrt_s_GeV': sqrt_s,
            'convention': {'order': order, 'pdf': pdf, 'scale': scale}, **extra}


def acquired_rows():
    return [t for t in xs.registry()['tables'] if t.get('acquisition')]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv(xs.CACHE_ENV, str(tmp_path / 'cache'))
    return tmp_path / 'cache'


# ------------------------------------------------------------------ registry rows (offline)

def test_acquired_rows_carry_no_numbers_and_state_their_terms():
    rows = acquired_rows()
    assert {(t['basis'], t['convention']['pdf']) for t in rows} == {
        (basis, pdf) for basis in ('gluino_pair', 'squark_antisquark', 'stop_pair', 'sbottom_pair')
        for pdf in ('MSTW2008NLO', 'CTEQ6.6M', 'NNPDF3.0NLO')}
    for row in rows:
        assert row['convention']['order'] == 'NLO+NLL' and row['sqrt_s_GeV'] == 13000
        assert row['redistribution'] == 'unconfirmed' and row['bundled'] is False
        assert row['licence'] == 'LicenseRef-no-licence-granted' and row['licence_evidence'].strip()
        assert row['citation']['references'] and row['citation']['page'].startswith('https://')
        assert row['acquisition']['archive_sha256'] == rows[0]['acquisition']['archive_sha256']
        assert len(row['sha256']) == 64
        assert not xs.package_data_path('cross_sections', *row['file'].split('/')).exists()
    fragment = json.loads(xs.package_data_path('cross_sections', xs.ACQUIRED_TABLES).read_text())
    assert all('data' not in row for row in fragment['tables'])
    assert fragment['licence_terms']['evidence_read']


def test_no_declared_gap_contradicts_an_acquired_row():
    for row in acquired_rows():
        assert xs._gap(row['basis'], row['sqrt_s_GeV'], 'NLO+NLL') is None


def test_squark_rows_declare_their_state_bases_and_the_others_have_none():
    for row in acquired_rows():
        if row['basis'] == 'squark_antisquark':
            assert row['state_count'] == 10 and set(row['declared_state_counts']) == {'8', '10'}
            assert row['state_rescaling']
        else:
            assert row['state_count'] is None and 'declared_state_counts' not in row


def test_verify_reports_unacquired_rows_without_the_network(cache, monkeypatch):
    def offline(*_a, **_k):
        raise AssertionError('verify must not use the network')
    monkeypatch.setattr(xs, '_download', offline)
    report = xs.verify_registry()
    assert report['passed'] and set(report['not_acquired']) == {t['id'] for t in acquired_rows()}


def test_nlo_nll_basis_is_available_but_pdf_must_be_named():
    with pytest.raises(xs.ConventionUnavailable, match='ambiguous') as excinfo:
        xs.lookup(request('gluino_pair', masses={'mass': 1000}))
    assert all(name in str(excinfo.value) for name in ('MSTW2008NLO', 'CTEQ6.6M', 'NNPDF3.0NLO'))
    with pytest.raises(xs.ConventionUnavailable, match='PDF'):
        xs.lookup(request('gluino_pair', pdf='PDF4LHC15', masses={'mass': 1000}))


# ------------------------------------------------- mechanism on a synthetic archive (offline)

HEADER_PDF_ALPHAS = ('process ms mgl LO(mu=1) LOdelmu+ LOdelmu- NLO(mu=1) NLOdelmu+ NLOdelmu- pdf+(%) pdf-(%) '
                     'as+(%) as-(%) NLO+NLL NLO+NLLdelmu+ NLO+NLLdelmu-')


def synthetic_sigma(mass):
    """A smooth, curved synthetic falling spectrum (not a physics value)."""
    x = math.log(mass / 100.0)
    return math.exp(8.0 - 2.5 * x - 0.35 * x * x)


def grid_bytes(label, masses, layout='pdf', mass_first=True):
    lines = ['# synthetic grid for the loader tests', HEADER_PDF_ALPHAS, '', '']
    for m in masses:
        nll = synthetic_sigma(m)
        nlo, lo = 0.9 * nll, 0.6 * nll
        if layout == 'pdf':
            cols = [lo, 0.3 * lo, -0.2 * lo, nlo, 0.1 * nlo, -0.1 * nlo, 5.0, -6.0, 2.0, -2.5, nll, 0.08 * nll, -0.07 * nll]
        else:
            cols = [lo, 0.3 * lo, -0.2 * lo, nlo, 0.1 * nlo, -0.1 * nlo, 4.0, nll, 0.08 * nll, -0.07 * nll, 4.5]
        mass_cols = [str(m), '1.00E+10'] if mass_first else ['1.00E+10', str(m)]
        lines.append(' '.join([label, *mass_cols, *(f'{c:.6E}' for c in cols)]))
    return ('\n'.join(lines) + '\n').encode('latin-1')


MASSES = [200, 300, 400, 500, 600, 700, 800, 900, 1000]


def synthetic_archive(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:bz2') as tar:
        for name, raw in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    return stream.getvalue()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def synthetic(monkeypatch, cache):
    members = {'sq_mstw.grid': grid_bytes('sb', MASSES),
               'gl_nn.grid': grid_bytes('gdcpl', MASSES, layout='combined', mass_first=False)}
    archive = synthetic_archive(members)
    template = next(t for t in acquired_rows() if t['id'] == 'pp13-squark-nlo-nll-mstw2008')

    def row(table_id, basis, member, layout, label, column, pct_basis, pdf, states):
        r = copy.deepcopy(template)
        r.update(id=table_id, basis=basis, file='synthetic/' + member, sha256=sha(members[member]),
                 state_count=states, source_url='https://example.invalid/archive.tar.bz2')
        r['convention'] = dict(r['convention'], pdf=pdf)
        r['acquisition'].update(archive_url='https://example.invalid/archive.tar.bz2', archive_sha256=sha(archive),
                                archive_bytes=len(archive), member=member, layout=layout, process_label=label,
                                mass_column=column, pct_basis=pct_basis)
        if states is None:
            r.pop('declared_state_counts', None)
            r['state_rescaling'] = None
        return r

    rows = [row('syn-squark', 'squark_antisquark', 'sq_mstw.grid', 'nllfast-grid-pdf-and-alphas', 'sb', 'ms', 'nlo',
                'SynPDF', 10),
            row('syn-gluino', 'gluino_pair', 'gl_nn.grid', 'nllfast-grid-pdfas-combined', 'gdcpl', 'mg', 'nll',
                'SynPDF', None)]
    monkeypatch.setattr(xs, '_REGISTRY', {'tables': rows, 'aliases': [], 'gaps': []})
    downloads = []
    monkeypatch.setattr(xs, '_download', lambda url: downloads.append(url) or archive)
    return {'rows': rows, 'members': members, 'archive': archive, 'downloads': downloads, 'cache': cache}


def test_first_use_acquires_once_verifies_and_caches(synthetic):
    first = xs.lookup(request('squark_antisquark', pdf='SynPDF', masses={'mass': 500}, state_count=10))
    assert first['sigma_pb'] == pytest.approx(synthetic_sigma(500), rel=1e-5)
    assert first['interpolation'] == 'exact node'
    assert len(synthetic['downloads']) == 1
    assert (synthetic['cache'] / 'synthetic' / 'gl_nn.grid').is_file()
    again = xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}))
    assert again['sigma_pb'] == pytest.approx(synthetic_sigma(500), rel=1e-5)
    assert len(synthetic['downloads']) == 1
    record = first['table']['acquisition']
    assert record['archive_url'] and record['archive_sha256'] == sha(synthetic['archive'])


def test_published_columns_are_kept_and_percentages_are_converted_with_their_stated_basis(synthetic):
    squark = xs.load_table(synthetic['rows'][0])['data']['500']
    nll, nlo = synthetic_sigma(500), 0.9 * synthetic_sigma(500)
    assert squark['xsec_pb'] == pytest.approx(nll, rel=1e-5) and squark['xsec_nlo_pb'] == pytest.approx(nlo, rel=1e-5)
    assert squark['unc_scale_up_pb'] == pytest.approx(0.08 * nll, rel=1e-5)
    assert squark['unc_scale_down_pb'] == pytest.approx(-0.07 * nll, rel=1e-5)
    assert squark['pdf_up_pct'] == 5.0 and squark['pdf_down_pct'] == -6.0
    assert squark['unc_pdf_up_pb'] == pytest.approx(0.05 * nlo, rel=1e-5)
    assert squark['unc_alphas_down_pb'] == pytest.approx(0.025 * nlo, rel=1e-5)
    combined = xs.load_table(synthetic['rows'][1])['data']['500']
    assert combined['pdfas_pct'] == 4.5 and combined['unc_pdfas_up_pb'] == pytest.approx(0.045 * nll, rel=1e-5)
    result = xs.lookup(request('squark_antisquark', pdf='SynPDF', masses={'mass': 500}, state_count=10))
    unc = result['uncertainty']
    assert unc['relative_up'] is None and unc['up_pb'] is None  # no total is published
    assert unc['relative_scale_up'] == pytest.approx(0.08, rel=1e-5)
    assert unc['relative_pdf_up'] == pytest.approx(0.05 * 0.9, rel=1e-5)


def test_interpolation_error_is_zero_at_nodes_and_reported_between_them(synthetic):
    node = xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 600}))
    assert node['interpolation_error']['relative'] == 0.0
    between = xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 650}))
    assert between['interpolation'].startswith('log-log between 600 and 700')
    estimate = between['interpolation_error']
    assert estimate['nodes_used_GeV'] == [500.0, 600.0, 700.0, 800.0]
    truth = synthetic_sigma(650)
    actual = abs(between['sigma_pb'] - truth) / truth
    assert 0 < estimate['relative'] < 0.05
    # The estimate tracks the true interpolation error of the linear step (here known analytically).
    assert estimate['relative'] == pytest.approx(actual, rel=0.25)


def test_interpolation_error_near_the_grid_edge_uses_the_nearest_four_nodes(synthetic):
    edge = xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 250}))
    assert edge['interpolation_error']['nodes_used_GeV'] == [200.0, 300.0, 400.0, 500.0]
    assert edge['interpolation_error']['relative'] > 0


def test_extrapolation_is_refused(synthetic):
    for mass in (150, 1100):
        with pytest.raises(ValueError, match='extrapolation'):
            xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': mass}))


def test_state_count_must_be_declared_and_be_a_declared_basis(synthetic):
    base = xs.lookup(request('squark_antisquark', pdf='SynPDF', masses={'mass': 500}, state_count=10))
    assert base['state_rescaling'] is None and base['state_basis']['state_count'] == 10
    eight = xs.lookup(request('squark_antisquark', pdf='SynPDF', masses={'mass': 500}, state_count=8))
    assert eight['sigma_pb'] == pytest.approx(0.8 * base['sigma_pb'], rel=1e-12)
    assert eight['state_rescaling']['factor'] == pytest.approx(0.8)
    assert eight['state_rescaling']['table_state_count'] == 10
    assert 'ten states' in eight['state_basis']['table_definition']
    assert 'eight states' in eight['state_basis']['definition']
    with pytest.raises(ValueError, match='declare state_count'):
        xs.lookup(request('squark_antisquark', pdf='SynPDF', masses={'mass': 500}))
    for undeclared in (1, 5, 12):
        with pytest.raises(ValueError, match='not a declared basis'):
            xs.lookup(request('squark_antisquark', pdf='SynPDF', masses={'mass': 500}, state_count=undeclared))
    with pytest.raises(ValueError, match='spectrum_assumption'):
        xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}, state_count=1))
    with pytest.raises(ValueError, match='no state count'):
        xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}, state_count=1,
                          spectrum_assumption='state count given for a table that has none'))


def test_changed_archive_is_refused_and_nothing_is_cached(synthetic, monkeypatch):
    monkeypatch.setattr(xs, '_download', lambda url: synthetic['archive'] + b'tampered')
    with pytest.raises(RuntimeError, match='pinned sha256'):
        xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}))
    assert not list(synthetic['cache'].rglob('*.grid'))


def test_changed_member_is_refused(synthetic, monkeypatch):
    members = dict(synthetic['members'], **{'gl_nn.grid': synthetic['members']['gl_nn.grid'] + b'\n'})
    archive = synthetic_archive(members)
    for row in synthetic['rows']:
        row['acquisition']['archive_sha256'] = sha(archive)
    monkeypatch.setattr(xs, '_download', lambda url: archive)
    with pytest.raises(RuntimeError, match='member gl_nn.grid differs'):
        xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}))
    assert not list(synthetic['cache'].rglob('*.grid'))


def test_offline_acquisition_fails_loudly_and_names_the_manual_route(synthetic, monkeypatch):
    def offline(_url):
        raise OSError('network unreachable')
    monkeypatch.setattr(xs, '_download', offline)
    with pytest.raises(RuntimeError, match='network unreachable') as excinfo:
        xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}))
    assert 'ravel xsec acquire --archive' in str(excinfo.value)
    assert sha(synthetic['archive']) in str(excinfo.value)


def test_local_archive_installs_without_the_network(synthetic, monkeypatch, tmp_path, capsys):
    def offline(_url):
        raise AssertionError('no download expected')
    monkeypatch.setattr(xs, '_download', offline)
    archive = tmp_path / 'copy.tar.bz2'
    archive.write_bytes(synthetic['archive'])
    assert xs.main(['acquire', '--archive', str(archive)]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert {r['id'] for r in installed} == {'syn-squark', 'syn-gluino'}
    assert xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}))['sigma_pb'] > 0
    bad = tmp_path / 'bad.tar.bz2'
    bad.write_bytes(synthetic['archive'] + b'x')
    with pytest.raises(RuntimeError, match='pinned sha256'):
        xs.acquire(archive=bad)


def test_tampered_cache_file_is_refused(synthetic):
    xs.acquire(['syn-gluino'])
    path = synthetic['cache'] / 'synthetic' / 'gl_nn.grid'
    path.write_bytes(path.read_bytes().replace(b'1.00E+10', b'2.00E+10'))
    report = xs.verify_registry()
    assert not report['passed'] and report['failures'][0]['id'] == 'syn-gluino'
    with pytest.raises(RuntimeError, match='changed'):
        xs.lookup(request('gluino_pair', pdf='SynPDF', masses={'mass': 500}))


def test_malformed_grid_rows_are_refused():
    acquisition = {'layout': 'nllfast-grid-pdf-and-alphas', 'process_label': 'sb', 'mass_column': 'ms',
                   'pct_basis': 'nlo'}
    good = grid_bytes('sb', [200, 300])
    assert set(xs.parse_published_grid(good, acquisition)['data']) == {'200', '300'}
    with pytest.raises(ValueError, match='expected'):
        xs.parse_published_grid(grid_bytes('gg', [200]), acquisition)
    with pytest.raises(ValueError, match='columns'):
        xs.parse_published_grid(good + b'sb 400 1.00E+10 1.0\n', acquisition)
    with pytest.raises(ValueError, match='twice'):
        xs.parse_published_grid(good + good.splitlines(True)[-1], acquisition)
    with pytest.raises(ValueError, match='no rows'):
        xs.parse_published_grid(b'# empty\n', acquisition)


def test_fetch_of_an_acquired_row_returns_the_verified_member(synthetic, tmp_path):
    out = tmp_path / 'member.grid'
    report = xs.fetch('syn-gluino', out)
    assert out.read_bytes() == synthetic['members']['gl_nn.grid'] and report['sha256'] == sha(out.read_bytes())


def test_list_marks_acquired_rows(capsys):
    assert xs.main(['list', '--basis', 'gluino_pair']) == 0
    out = capsys.readouterr().out
    assert out.count('[acquired at first use]') == 3 and 'pp13-gluino-nnlo-nnll' in out


# ----------------------------------------------- published values (needs the real archive)

ROW_LAYOUT = {  # zero-based whitespace columns of the published grid files
    'pdf-and-alphas': {'nll': 13, 'scale_up': 14, 'scale_down': 15, 'nlo': 6},
    'pdfas-combined': {'nll': 10, 'scale_up': 11, 'scale_down': 12, 'nlo': 6, 'pdfas': 13}}
MEMBER_MASS_COLUMN = {'gdcpl': 2, 'sdcpl': 1, 'st': 1}


@pytest.fixture(scope='module')
def real(tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp('xsec-cache')
    previous = os.environ.get(xs.CACHE_ENV)
    os.environ[xs.CACHE_ENV] = str(cache_dir)
    try:
        local = os.environ.get('RAVEL_XSEC_TEST_ARCHIVE')
        try:
            xs.acquire(archive=local or None)
        except RuntimeError as exc:
            if 'could not acquire' in str(exc):
                pytest.skip(f'NLL-fast archive not reachable from this host: {exc}')
            raise
        yield cache_dir
    finally:
        if previous is None:
            os.environ.pop(xs.CACHE_ENV, None)
        else:
            os.environ[xs.CACHE_ENV] = previous


def published_rows(entry):
    """Rows of the cached published member, read with explicit column positions."""
    layout = 'pdfas-combined' if entry['acquisition']['layout'].endswith('combined') else 'pdf-and-alphas'
    stem = entry['acquisition']['member'].split('_')[0]
    rows = {}
    for line in xs.table_path(entry).read_bytes().decode('latin-1').splitlines():
        fields = line.split()
        if fields and not fields[0].startswith('#') and fields[0] != 'process':
            rows[int(float(fields[MEMBER_MASS_COLUMN[stem]]))] = [float(f) for f in fields[1:]], layout
    return {m: (v, ROW_LAYOUT[layout]) for m, (v, layout) in rows.items()}


def column(values, index):
    return values[index - 1]  # published columns are numbered with the process label at zero


def request_for(entry, mass, **extra):
    return request(entry['basis'], pdf=entry['convention']['pdf'], masses={'mass': mass},
                   **({'state_count': 10} if entry['basis'] == 'squark_antisquark' else {}), **extra)


def test_lookup_at_every_tabulated_mass_returns_the_published_value(real):
    for entry in acquired_rows():
        rows = published_rows(entry)
        assert rows
        for mass, (values, cols) in rows.items():
            result = xs.lookup(request_for(entry, mass))
            assert result['interpolation'] == 'exact node'
            assert result['sigma_pb'] == column(values, cols['nll']), (entry['id'], mass)
            assert result['uncertainty']['relative_scale_up'] == pytest.approx(
                abs(column(values, cols['scale_up'])) / column(values, cols['nll']), rel=1e-12)
            assert result['interpolation_error']['relative'] == 0.0
            assert result['table']['id'] == entry['id']
            assert result['convention']['pdf'] == entry['convention']['pdf']


def test_published_mass_ranges_are_those_the_program_documents(real):
    spans = {}
    for entry in acquired_rows():
        masses = sorted(published_rows(entry))
        spans.setdefault(entry['basis'], set()).add((masses[0], masses[-1]))
    assert spans['gluino_pair'] == {(200, 3000)} and spans['squark_antisquark'] == {(200, 3000)}
    assert spans['stop_pair'] == {(100, 2500)} and spans['sbottom_pair'] == {(100, 2500)}
    with pytest.raises(ValueError, match='extrapolation'):
        xs.lookup(request('gluino_pair', pdf='MSTW2008', masses={'mass': 3100}))
    with pytest.raises(ValueError, match='extrapolation'):
        xs.lookup(request('stop_pair', pdf='CTEQ6.6M', masses={'mass': 90}))


def test_between_nodes_the_interpolation_error_is_reported_and_small(real):
    for entry in acquired_rows():
        nodes = sorted(published_rows(entry))
        for low, high in zip(nodes, nodes[1:]):
            mass = (low + high) / 2
            result = xs.lookup(request_for(entry, mass))
            error = result['interpolation_error']
            assert 0.0 < error['relative'] < 0.03, (entry['id'], mass, error)
            sigma = [published_rows(entry)[n][0] for n in (low, high)]
            bounds = [column(v, published_rows(entry)[low][1]['nll']) for v in sigma]
            assert min(bounds) < result['sigma_pb'] < max(bounds)


def test_nlo_nll_and_nnlo_nnll_conventions_differ_by_the_published_ratio(real):
    pairs = {'gluino_pair': ('pp13-gluino-nlo-nll-mstw2008', 'pp13-gluino-nnlo-nnll'),
             'squark_antisquark': ('pp13-squark-nlo-nll-mstw2008', 'pp13-squark-nnlo-nnll')}
    for basis, (low_id, high_id) in pairs.items():
        low_entry, high_entry = xs.table_entry(low_id), xs.table_entry(high_id)
        low_rows = published_rows(low_entry)
        high_data = xs.load_table(high_entry)['data']
        for mass in (1000, 1500, 2000):
            extra = {'state_count': 10} if basis == 'squark_antisquark' else {}
            nlo_nll = xs.lookup(request(basis, pdf='MSTW2008', masses={'mass': mass}, **extra))
            nnlo = xs.lookup(request(basis, order=high_entry['convention']['order'],
                                     masses={'mass': mass}, **extra))
            assert nlo_nll['table']['id'] == low_id and nnlo['table']['id'] == high_id
            published = high_data[str(mass)]['xsec_pb'] / column(low_rows[mass][0], low_rows[mass][1]['nll'])
            assert nnlo['sigma_pb'] / nlo_nll['sigma_pb'] == pytest.approx(published, rel=1e-12)
            assert abs(published - 1.0) > 0.01  # the two orders are not interchangeable


def test_eight_and_ten_squark_state_bases_are_distinct_and_explicit(real):
    ten = xs.lookup(request('squark_antisquark', pdf='CTEQ6.6M', masses={'mass': 1200}, state_count=10))
    eight = xs.lookup(request('squark_antisquark', pdf='CTEQ6.6M', masses={'mass': 1200}, state_count=8))
    assert eight['sigma_pb'] == pytest.approx(0.8 * ten['sigma_pb'], rel=1e-12)
    assert ten['state_basis']['definition'] != eight['state_basis']['definition']
    assert 'sbottoms' in eight['state_basis']['definition']
    assert eight['uncertainty']['relative_scale_up'] == pytest.approx(ten['uncertainty']['relative_scale_up'])
    assert eight['uncertainty']['up_pb'] is None
    with pytest.raises(ValueError, match='declare state_count'):
        xs.lookup(request('squark_antisquark', pdf='CTEQ6.6M', masses={'mass': 1200}))
    with pytest.raises(ValueError, match='not a declared basis'):
        xs.lookup(request('squark_antisquark', pdf='CTEQ6.6M', masses={'mass': 1200}, state_count=6))


def test_sbottom_pair_uses_the_documented_stop_grid_with_its_own_basis(real):
    stop = xs.lookup(request('stop_pair', pdf='NNPDF3.0', masses={'mass': 800}))
    sbottom = xs.lookup(request('sbottom_pair', pdf='NNPDF3.0', masses={'mass': 800}))
    assert stop['sigma_pb'] == sbottom['sigma_pb']
    assert stop['table']['id'] != sbottom['table']['id'] and stop['table']['sha256'] == sbottom['table']['sha256']
    assert stop['uncertainty']['relative_pdfas_up'] > 0


def test_verify_covers_acquired_rows_once_installed(real):
    report = xs.verify_registry()
    assert report['passed'] and report['not_acquired'] == []
