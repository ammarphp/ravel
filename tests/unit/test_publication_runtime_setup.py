"""Authored NOT RUN: software/custody fixtures; no TeX/native/installation calls.

The inherited fixture replaces author authentication only. The actual selected
format/tree/load/inputs validators run; that stand-in is never a publication,
runtime qualification, or an actual author/model/review claim.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import pytest
from ravel.setup import manifest as mf
from ravel.workflow import publication_runtime as pr
from ravel.physics import manuscript_build as mb, reinterpret_db
from test_manuscript_build import fixture, put


def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('runtime setup must not launch a command')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(reinterpret_db, 'execute_native', forbidden)


def ready(root, monkeypatch):
    no_native(monkeypatch)
    task, config, package = fixture(root, monkeypatch)
    for name in ('pdflatex', 'pdfinfo'):
        (root / name).chmod(0o755)  # Inert readable bytes; never invoked.
    return task, config, package


def test_discovery_retains_absent_and_aliases_without_execution(tmp_path, monkeypatch):
    no_native(monkeypatch)
    p = tmp_path / 'pdftex'; p.write_text('inert'); p.chmod(0o755)
    (tmp_path / 'pdflatex').symlink_to(p)
    result = pr.discover(search_path=str(tmp_path))
    rows = {r['name']: r for r in result['tools']}
    assert rows['pdflatex']['state'] == 'located_alias_not_admitted'
    assert rows['pdflatex']['path'].endswith('/pdflatex')
    assert rows['pdflatex']['resolved_path'].endswith('/pdftex')
    assert rows['pdfinfo']['state'] == 'not_found'
    assert rows['rsvg-convert']['required_for_svg']
    assert not result['commands_executed'] and not result['runtime_qualified']


def test_exact_inventory_is_actual_worker_tree_schema_and_ending(tmp_path):
    root = tmp_path / 'assets'; root.mkdir()
    (root / 'style.sty').write_bytes(b'exact supplied style\n')
    (root / 'font.tfm').write_bytes(b'exact supplied font\n')
    out = tmp_path / 'manifest.json'
    result = pr.inventory(root, out)
    raw = out.read_bytes()
    assert result['tree']['manifest']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == {'schema_version': 1, 'files': {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
    assert set(mb._tree(result['tree'], tmp_path)) == {out, *root.iterdir()}
    assert not result['runtime_qualified'] and not result['venue_assets_authenticated_as_official']


@pytest.mark.parametrize('bad', ['alias', 'empty', 'inside', 'existing', 'file-bound', 'byte-bound'])
def test_inventory_refuses_incomplete_or_unsupported_populations(tmp_path, monkeypatch, bad):
    root = tmp_path / 'assets'; root.mkdir(); out = tmp_path / 'manifest.json'
    if bad != 'empty':
        (root / 'style.sty').write_bytes(b'exact style')
    if bad == 'alias':
        (root / 'alias.sty').symlink_to(root / 'style.sty')
    if bad == 'inside':
        out = root / 'manifest.json'
    if bad == 'existing':
        out.write_bytes(b'prior result must remain exact')
    if bad == 'file-bound':
        monkeypatch.setattr(pr, 'MAX_FILES', 1)
        (root / 'extra.sty').write_bytes(b'no clipping')
    if bad == 'byte-bound':
        monkeypatch.setattr(pr, 'MAX_BYTES', 1)
    with pytest.raises((ValueError, FileExistsError)):
        pr.inventory(root, out)
    if bad == 'existing':
        assert out.read_bytes() == b'prior result must remain exact'


def test_intended_manifest_cannot_be_rebaselined_after_emission(tmp_path, monkeypatch):
    root = tmp_path / 'assets'; root.mkdir(); (root / 'style.sty').write_text('original')
    out = tmp_path / 'manifest.json'; original = pr._identity
    def change(path):
        if Path(path) == out and out.exists():
            out.write_text('{"schema_version":1,"files":{}}\n')
        return original(path)
    monkeypatch.setattr(pr, '_identity', change)
    with pytest.raises(ValueError, match='intended'):
        pr.inventory(root, out)
    assert out.exists()  # Preserve failed output; no rewrite-to-pass.


def test_late_tree_member_cannot_disappear_from_inventory(tmp_path, monkeypatch):
    root = tmp_path / 'assets'; root.mkdir(); (root / 'style.sty').write_text('original')
    original = pr._inventory; count = 0
    def change(path, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            (root / 'last.sty').write_text('late added asset')
        return original(path, **kwargs)
    monkeypatch.setattr(pr, '_inventory', change)
    with pytest.raises(ValueError, match='population changed'):
        pr.inventory(root, tmp_path / 'manifest.json')


def test_readiness_calls_real_loader_inputs_and_never_native(tmp_path, monkeypatch):
    task, c, p = ready(tmp_path, monkeypatch)
    calls = []; original = mb.inputs
    def observe(*a, **k):
        calls.append('actual_inputs')
        return original(*a, **k)
    monkeypatch.setattr(mb, 'inputs', observe)
    result = pr.check(task['config'], expected_sha256=hashlib.sha256(Path(task['config']).read_bytes()).hexdigest())
    assert len(calls) == 2
    assert result['status'] == 'source_closure_present_runtime_checks_required'
    assert {'pdflatex', 'pdfinfo', 'runtime-manifest.json', 'synthetic.tfm', 'note.tex'} <= {
        Path(r['path']).name for r in result['input_pins']}
    assert result['required']['binaries'] == ['pdflatex', 'pdfinfo']
    assert not any(result[k] for k in ('commands_executed', 'installation_performed',
                                     'runtime_qualified', 'scientific_acceptance', 'visual_style_accepted'))


@pytest.mark.parametrize('kind', ['prd', 'epjc'])
def test_selected_native_class_and_transitive_entry_assets(tmp_path, monkeypatch, kind):
    task, c, p = ready(tmp_path, monkeypatch)
    fmt = json.loads((tmp_path / 'format.json').read_text()); fmt['profile'] = kind
    fmt['render']['class'] = 'revtex4-2' if kind == 'prd' else 'svjour3'
    p['formatting_contract'] = put(tmp_path, 'format.json', fmt)
    names = ['revtex4-2.cls', 'aps4-2.rtx', 'natbib.sty', 'url.sty', 'textcase.sty', 'bm.sty'] if kind == 'prd' else ['svjour3.cls']
    for name in names:
        (tmp_path / 'runtime' / name).write_text('inert source asset ' + name)
    m = put(tmp_path, 'runtime-manifest.json', {'schema_version': 1, 'files': {
        q.name: hashlib.sha256(q.read_bytes()).hexdigest() for q in (tmp_path / 'runtime').iterdir()}})
    c['runtime']['asset_trees'][0]['manifest'] = {k: m[k] for k in ('path', 'sha256')}
    c['package'] = put(tmp_path, 'package.json', p); put(tmp_path, 'config.json', c)
    result = pr.check(task['config'])
    assert set(names) <= set(result['required']['asset_basenames'])
    assert not result['runtime_qualified']


@pytest.mark.parametrize('change', ['missing-class', 'missing-font', 'unlisted-last', 'changed-font', 'alias', 'permissions', 'config-pin'])
def test_actual_selected_runtime_failures_never_report_ready(tmp_path, monkeypatch, change):
    task, c, p = ready(tmp_path, monkeypatch)
    if change == 'missing-class': (tmp_path / 'runtime/article.cls').unlink()
    if change == 'missing-font':
        (tmp_path / 'runtime/synthetic.tfm').unlink()
        m = put(tmp_path, 'runtime-manifest.json', {'schema_version': 1, 'files': {
            q.name: hashlib.sha256(q.read_bytes()).hexdigest() for q in (tmp_path / 'runtime').iterdir()}})
        c['runtime']['asset_trees'][0]['manifest'] = {k: m[k] for k in ('path', 'sha256')}
        put(tmp_path, 'config.json', c)
    if change == 'unlisted-last': (tmp_path / 'runtime/last.sty').write_text('unlisted')
    if change == 'changed-font': (tmp_path / 'runtime/synthetic.tfm').write_text('changed')
    if change == 'alias': (tmp_path / 'runtime/alias.sty').symlink_to(tmp_path / 'runtime/article.cls')
    if change == 'permissions': (tmp_path / 'pdflatex').chmod(0o644)
    with pytest.raises(ValueError):
        pr.check(task['config'], expected_sha256='0' * 64 if change == 'config-pin' else None)


def test_svg_converter_is_conditional_and_actual_source_bound(tmp_path, monkeypatch):
    task, c, p = ready(tmp_path, monkeypatch)
    assert pr.check(task['config'])['required']['binaries'] == ['pdflatex', 'pdfinfo']
    p['figures'] = [put(tmp_path, 'source.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>')]
    c['package'] = put(tmp_path, 'package.json', p); put(tmp_path, 'config.json', c)
    with pytest.raises(ValueError, match='rsvg-convert'):
        pr.check(task['config'])
    converter = put(tmp_path, 'rsvg-convert', 'inert, never executed'); (tmp_path / 'rsvg-convert').chmod(0o755)
    c['runtime']['svg_converter'] = {k: converter[k] for k in ('path', 'sha256')}
    put(tmp_path, 'config.json', c)
    result = pr.check(task['config'])
    assert result['required']['binaries'] == ['pdflatex', 'pdfinfo', 'rsvg-convert']
    assert result['binaries']['svg_converter']['sha256'] == converter['sha256']


def test_ending_changed_configuration_cannot_be_rebaselined(tmp_path, monkeypatch):
    task, c, p = ready(tmp_path, monkeypatch); original = mb.inputs; count = 0
    def change(*a, **k):
        nonlocal count
        count += 1
        if count == 2:
            c['max_main_pages'] = 9
            put(tmp_path, 'config.json', c)
        return original(*a, **k)
    monkeypatch.setattr(mb, 'inputs', change)
    with pytest.raises(ValueError, match='changed'):
        pr.check(task['config'])


def test_setup_population_and_instruction_mirror_retained():
    root = Path(__file__).absolute().parents[2]
    m = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    g = next(g for g in m['groups'] if g['id'] == 'publication')
    assert {r['id'] for r in g['checks']} >= {'pdfinfo', 'pdftoppm', 'neato', 'rsvg-convert'}
    steps = {s['id']: s for s in g['steps']}
    assert 'librsvg' in steps['reports-env']['specs']
    # The TeX recipe stays in development until it qualifies; the default install skips it. A source
    # tree lists it as withheld; a released tree does not declare it.
    assert 'tex' in mf.held_groups(m, {'tex'})
    for tex in (g for g in m['groups'] if g['id'] == 'tex'):
        assert {r['id'] for r in tex['checks']} >= {'pdflatex', 'publication-selected-assets'}
    assert (root / 'docs/installation.md').read_bytes() == (root / 'src/ravel/data/workflow/docs/installation.md').read_bytes()


@pytest.mark.parametrize('change', ['late-member', 'earlier-leaf'])
def test_final_inventory_leaf_read_cannot_hide_ending_changes(tmp_path, monkeypatch, change):
    root = tmp_path / 'assets'; root.mkdir()
    first = root / 'a.sty'; first.write_text('original style\n')
    last = root / 'z.tfm'; last.write_text('original font\n')
    intended = {'schema_version': 1, 'files': {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, last)}}
    original = pr._identity; last_reads = 0
    def at_last_read(path):
        nonlocal last_reads
        observed = original(path)
        if Path(path) == last:
            last_reads += 1
            if last_reads == 2:
                if change == 'late-member':
                    (root / 'm.sty').write_text('late asset after fixed iteration\n')
                else:
                    first.write_text('changed earlier captured style\n')
        return observed
    monkeypatch.setattr(pr, '_identity', at_last_read)
    out = tmp_path / 'manifest.json'
    with pytest.raises(ValueError, match='population changed'):
        pr.inventory(root, out)
    assert last_reads == 2
    assert json.loads(out.read_bytes()) == intended  # Failed intended output stays exact.


@pytest.mark.parametrize('change', ['late-member', 'earlier-leaf'])
def test_final_readiness_input_read_cannot_hide_ending_changes(tmp_path, monkeypatch, change):
    task, c, p = ready(tmp_path, monkeypatch)
    paths = mb.inputs(task, tmp_path)
    last = paths[-1]
    earlier = next(q for q in paths if q.parent == tmp_path / 'runtime' and q != last)
    original = pr._identity; last_reads = 0
    def at_last_read(path):
        nonlocal last_reads
        observed = original(path)
        if Path(path) == last:
            last_reads += 1
            if last_reads == 2:
                if change == 'late-member':
                    (tmp_path / 'runtime/ending-extra.sty').write_text('unlisted ending asset\n')
                else:
                    earlier.write_text('changed earlier captured runtime input\n')
        return observed
    monkeypatch.setattr(pr, '_identity', at_last_read)
    with pytest.raises(ValueError, match='changed'):
        pr.check(task['config'])
    assert last_reads == 2
