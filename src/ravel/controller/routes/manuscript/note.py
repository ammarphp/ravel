"""The governed note build: sources bound to delivered results, then the PDF or a qualified source bundle.

Two stages, each one confined launch of a governed plan step (``python -I -m
ravel.controller.routes.manuscript.note <stage> ...``), after the staged authoring step wrote the claim
map and the note text:

- ``sources``: every claim names a declared result whose bytes have the digest the claim map binds;
  every quantity a claim states equals the value at its JSON pointer in that result within the stated
  tolerance; every claim and figure is placed in the text and every marker names one; every figure is a
  declared result image. The LaTeX source, the figures and a manifest are written as a deterministic
  bundle with the integrity items (``integrity.json``). A failing item refuses the stage.
- ``pdf``: two offline ``pdflatex`` passes over the bundle (no shell escape, halt on error, bounded
  time, private scratch). Without a TeX engine the stage ends ``qualified`` with
  ``manuscript_tex_unavailable``; a failed build is ``refused`` with the log tail. The route then ends with
  a qualified delivery of the source bundle; it never waits for a TeX installation.

The note text is Markdown-like: ``# Title``, ``## Section``, paragraphs, ``- `` items, and the markers
``[[claim:<id>]]`` and ``[[figure:<id>]]``. Results are named inputs ``result.<name>`` (accepted
artifacts of earlier plan steps) or supplied files ``--result <name>=<path>@<sha256>`` (their intake
digests). A PDF is a rendering of reviewed sources, not scientific acceptance.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

SCHEMA_VERSION = 1
STAGES = ('sources', 'pdf')
OPERATIONS = {'sources': 'manuscript-note-sources', 'pdf': 'manuscript-note-pdf'}
RECEIPT = 'outputs/receipt.json'
OUTPUTS = {'sources': (('outputs/sources.tar', 'document'), ('outputs/sources/main.tex', 'document'),
                       ('outputs/integrity.json', 'document'), ('outputs/bundle.json', 'document'),
                       ('outputs/receipt.json', 'document')),
           'pdf': (('outputs/manuscript.pdf', 'document'), ('outputs/build.json', 'document'),
                   ('outputs/receipt.json', 'document'))}
CLAIM_MAP_KIND = 'manuscript-claim-map'
IMAGE_SUFFIXES = ('.png', '.pdf', '.jpg', '.jpeg')
MARKER = re.compile(r'\[\[(claim|figure):([A-Za-z0-9_.-]{1,64})\]\]')
SAFE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,63}\Z')
MAX_RESULT_BYTES = 256 * 1024 ** 2
ITEMS = ('manuscript:claims-bound', 'manuscript:quantities-traced', 'manuscript:claims-placed',
         'manuscript:figures-accepted', 'manuscript:numbers-in-text')
TEX_PASSES = 2


class StageRefused(Exception):
    status = 'refused'

    def __init__(self, code, detail, evidence=None):
        super().__init__(f'{code}: {detail}')
        self.code, self.detail, self.evidence = code, detail, deepcopy(evidence)


class StageQualified(StageRefused):
    """The stage could not produce its rendering on this host; what it could deliver is listed."""
    status = 'qualified'


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


# ---- the claim map and the results ---------------------------------------------------------------

def validate_claim_map(document):
    def bad(message):
        raise StageRefused('manuscript_claim_map_invalid', message)
    if type(document) is not dict or document.get('kind') != CLAIM_MAP_KIND or document.get('schema_version') != 1:
        bad(f'a {CLAIM_MAP_KIND} version 1 document is required')
    extra = set(document) - {'kind', 'schema_version', 'title', 'authors', 'abstract', 'results', 'claims', 'figures'}
    if extra:
        bad('unknown fields: ' + ', '.join(sorted(extra)))
    if type(document.get('title')) is not str or not document['title'].strip():
        bad('a title is required')
    results = document.get('results')
    if type(results) is not dict or not results or len(results) > 256:
        bad('one to 256 named results are required')
    for name, row in results.items():
        if not SAFE_ID.fullmatch(name) or type(row) is not dict or set(row) != {'sha256'} or not re.fullmatch(
                r'[0-9a-f]{64}', str(row['sha256'])):
            bad(f'result {name!r} names its sha256 and nothing else')
    claims = document.get('claims')
    if type(claims) is not list or not claims or len(claims) > 512:
        bad('one to 512 claims are required')
    ids = set()
    for claim in claims:
        if type(claim) is not dict or not SAFE_ID.fullmatch(str(claim.get('id'))) or claim['id'] in ids:
            bad('every claim has a unique safe id')
        ids.add(claim['id'])
        if set(claim) - {'id', 'text', 'result', 'quantity'} or type(claim.get('text')) is not str or not claim['text'].strip():
            bad(f"claim {claim.get('id')} has text, a result and optionally one quantity")
        if claim.get('result') not in results:
            bad(f"claim {claim['id']} cites the undeclared result {claim.get('result')!r}")
        quantity = claim.get('quantity')
        if quantity is not None:
            if type(quantity) is not dict or set(quantity) - {'pointer', 'value', 'tolerance', 'unit'} or \
                    type(quantity.get('pointer')) is not str or not quantity['pointer'].startswith('/') or 'value' not in quantity:
                bad(f"claim {claim['id']} quantity names a JSON pointer and a value")
            value = quantity['value']
            if type(value) not in (int, float, str, bool) and value is not None:
                bad(f"claim {claim['id']} quantity value is a JSON scalar")
            if type(value) in (int, float) and not math.isfinite(value):
                bad(f"claim {claim['id']} quantity value is finite")
            tolerance = quantity.get('tolerance', 0)
            if type(tolerance) not in (int, float) or isinstance(tolerance, bool) or not math.isfinite(tolerance) or tolerance < 0:
                bad(f"claim {claim['id']} tolerance is a nonnegative number")
    figures = document.get('figures', [])
    if type(figures) is not list or len(figures) > 64:
        bad('at most 64 figures')
    for figure in figures:
        if type(figure) is not dict or set(figure) != {'id', 'result', 'caption'} or not SAFE_ID.fullmatch(
                str(figure.get('id'))) or figure['id'] in ids or figure.get('result') not in results:
            bad('every figure has a unique id, a declared result and a caption')
        ids.add(figure['id'])
    for key in ('title', 'abstract'):
        if key in document and type(document[key]) is not str:
            bad(f'{key} is text')
    if type(document.get('authors', [])) is not list or any(type(a) is not str for a in document.get('authors', [])):
        bad('authors is a list of names')
    for figure in figures:
        if type(figure['caption']) is not str:
            bad('figure captions are text')
    return document


def pointer(document, path):
    value = document
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if type(value) is dict and part in value:
            value = value[part]
        elif type(value) is list and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise KeyError(path)
    return value


def _same(found, value, tolerance):
    numbers = all(type(v) in (int, float) and not isinstance(v, bool) for v in (found, value))
    if numbers:
        return math.isfinite(found) and abs(found - value) <= tolerance
    return found == value


NUMBER = re.compile(r'(?<![\w.])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?')


def integrity(claim_map, results, note_text):
    """The executable integrity items over the claim map, the result bytes and the note text."""
    items = []
    unbound = [n for n, row in claim_map['results'].items() if n not in results or results[n]['sha256'] != row['sha256']]
    items.append({'id': 'manuscript:claims-bound', 'verdict': 'fail' if unbound else 'pass',
                  'evidence': {'unbound_results': unbound, 'results': {n: r['sha256'] for n, r in results.items()}}})
    traced, untraced = [], []
    documents = {}
    for claim in claim_map['claims']:
        quantity = claim.get('quantity')
        if quantity is None:
            continue
        name = claim['result']
        try:
            if name not in documents:
                documents[name] = json.loads(Path(results[name]['path']).read_bytes())
            found = pointer(documents[name], quantity['pointer'])
        except (KeyError, ValueError, OSError) as exc:
            untraced.append({'claim': claim['id'], 'reason': f'{type(exc).__name__}: {str(exc)[:200]}'})
            continue
        if _same(found, quantity['value'], quantity.get('tolerance', 0)):
            traced.append({'claim': claim['id'], 'pointer': quantity['pointer'], 'value': found})
        else:
            untraced.append({'claim': claim['id'], 'pointer': quantity['pointer'], 'claimed': quantity['value'],
                             'found': found if type(found) in (int, float, str, bool) or found is None else 'non-scalar'})
    items.append({'id': 'manuscript:quantities-traced', 'verdict': 'fail' if untraced else 'pass',
                  'evidence': {'traced': traced, 'untraced': untraced}})
    markers = MARKER.findall(note_text)
    claims = {c['id'] for c in claim_map['claims']}
    figures = {f['id'] for f in claim_map.get('figures', [])}
    unknown = sorted({f'{k}:{i}' for k, i in markers if i not in (claims if k == 'claim' else figures)})
    placed = {i for _, i in markers}
    unplaced = sorted((claims | figures) - placed)
    items.append({'id': 'manuscript:claims-placed', 'verdict': 'fail' if unknown or unplaced else 'pass',
                  'evidence': {'unknown_markers': unknown, 'unplaced': unplaced}})
    bad_figures = []
    for figure in claim_map.get('figures', []):
        row = results.get(figure['result'])
        if row is None or row.get('source') != 'plan' or Path(row['path']).suffix.lower() not in IMAGE_SUFFIXES or row['sha256'] != \
                claim_map['results'][figure['result']]['sha256']:
            bad_figures.append(figure['id'])
    items.append({'id': 'manuscript:figures-accepted', 'verdict': 'fail' if bad_figures else 'pass',
                  'evidence': {'figures': [f['id'] for f in claim_map.get('figures', [])], 'refused': bad_figures}})
    stray = []
    prose = MARKER.sub('', note_text)
    prose += '\n' + claim_map['title'] + '\n' + str(claim_map.get('abstract') or '')
    prose += '\n' + '\n'.join(f['caption'] for f in claim_map.get('figures', []))
    unbound_numbers = NUMBER.findall(prose)
    if unbound_numbers:
        stray.append({'unbound_numbers': unbound_numbers[:50]})
    for claim in claim_map['claims']:
        quantity = claim.get('quantity')
        value = (quantity or {}).get('value')
        written = [float(n) for n in NUMBER.findall(claim['text'])]
        if written and (quantity is None or type(value) not in (int, float) or isinstance(value, bool)):
            stray.append({'claim': claim['id'], 'untraced_numbers': written})
            continue
        if not written:
            continue
        # The written figure may be rounded: it agrees when it is within the tolerance or its own last digit.
        if not all(abs(n - value) <= max(quantity.get('tolerance', 0), _last_digit(t))
                   for n, t in zip(written, NUMBER.findall(claim['text']))):
            stray.append({'claim': claim['id'], 'written': written, 'value': value})
    items.append({'id': 'manuscript:numbers-in-text', 'verdict': 'fail' if stray else 'pass',
                  'evidence': {'mismatched': stray}})
    return items


def _last_digit(text):
    mantissa = text.lower().split('e')[0]
    exponent = int(text.lower().split('e')[1]) if 'e' in text.lower() else 0
    decimals = len(mantissa.split('.')[1]) if '.' in mantissa else 0
    return 0.5 * 10 ** (exponent - decimals)


# ---- LaTeX rendering ------------------------------------------------------------------------------

LATEX_SPECIALS = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$', '&': r'\&', '#': r'\#',
                  '^': r'\textasciicircum{}', '_': r'\_', '%': r'\%', '~': r'\textasciitilde{}'}


def escape(text):
    return ''.join(LATEX_SPECIALS.get(c, c) for c in text)


def render(claim_map, results, note_text, figure_names):
    """``main.tex`` of the note: claims with their result digest and traced quantity as footnotes."""
    claims = {c['id']: c for c in claim_map['claims']}
    figures = {f['id']: f for f in claim_map.get('figures', [])}

    def inline(text):
        out, last = [], 0
        for match in MARKER.finditer(text):
            out.append(escape(text[last:match.start()]))
            kind, ident = match.groups()
            if kind == 'claim':
                claim = claims[ident]
                note = f"Result {claim['result']}, sha256 {claim_map['results'][claim['result']]['sha256'][:16]}"
                quantity = claim.get('quantity')
                if quantity is not None:
                    note += f", {quantity['pointer']} = {quantity['value']}"
                    if quantity.get('unit'):
                        note += f" {quantity['unit']}"
                out.append(escape(claim['text']) + r'\footnote{' + escape(note) + '}')
            else:
                out.append(f'Figure~\\ref{{fig:{ident}}}')
            last = match.end()
        out.append(escape(text[last:]))
        return ''.join(out)

    body, items, paragraph = [], False, []

    def flush():
        if paragraph:
            body.append(inline(' '.join(paragraph)) + '\n')
            paragraph.clear()
    for raw in note_text.splitlines():
        line = raw.rstrip()
        figure = re.fullmatch(r'\s*\[\[figure:([A-Za-z0-9_.-]{1,64})\]\]\s*', line)
        if not line.strip() or line.startswith('#') or line.lstrip().startswith('- ') or figure:
            flush()
        if items and not line.lstrip().startswith('- '):
            body.append(r'\end{itemize}')
            items = False
        if figure:
            ident = figure.group(1)
            row = figures[ident]
            body.append('\\begin{figure}[htbp]\\centering\n'
                        f'\\includegraphics[width=0.8\\linewidth]{{figures/{figure_names[ident]}}}\n'
                        f"\\caption{{{escape(row['caption'])} (result {escape(row['result'])}, sha256 "
                        f"{claim_map['results'][row['result']]['sha256'][:16]})}}\\label{{fig:{ident}}}\n"
                        '\\end{figure}')
        elif line.startswith('## '):
            body.append(f'\\section{{{inline(line[3:].strip())}}}')
        elif line.startswith('# '):
            continue  # the title comes from the claim map
        elif line.lstrip().startswith('- '):
            if not items:
                body.append(r'\begin{itemize}')
                items = True
            body.append(r'\item ' + inline(line.lstrip()[2:]))
        elif line.strip():
            paragraph.append(line.strip())
    flush()
    if items:
        body.append(r'\end{itemize}')
    authors = ', '.join(escape(a) for a in claim_map.get('authors') or []) or 'Generated by the governed note build'
    head = ['\\documentclass[11pt]{article}', '\\usepackage{graphicx}', '\\begin{document}',
            f"\\title{{{escape(claim_map['title'])}}}", f'\\author{{{authors}}}', '\\date{}', '\\maketitle']
    if claim_map.get('abstract'):
        head += ['\\begin{abstract}', escape(claim_map['abstract']), '\\end{abstract}']
    return '\n'.join(head + body + ['\\end{document}', ''])


def _bundle(tar_path, files):
    """A deterministic tar of ``{name: bytes}`` (fixed owner, mode and time)."""
    with tarfile.open(tar_path, 'w', format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode, info.uid, info.gid = len(files[name]), 0, 0o644, 0, 0
            info.uname = info.gname = ''
            archive.addfile(info, io.BytesIO(files[name]))


# ---- stages ---------------------------------------------------------------------------------------

def _results(inputs, supplied):
    found = {}
    for name, path in inputs.items():
        if name.startswith('result.'):
            if os.path.getsize(path) > MAX_RESULT_BYTES:
                raise StageRefused('manuscript_result_too_large', 'a result exceeds the byte bound')
            found[name[len('result.'):]] = {'path': str(path), 'sha256': file_sha256(path), 'source': 'plan'}
    for name, (path, digest) in supplied.items():
        if name in found:
            raise StageRefused('manuscript_result_ambiguous', f'result {name} is both a plan input and supplied')
        if os.path.getsize(path) > MAX_RESULT_BYTES:
            raise StageRefused('manuscript_result_too_large', f'result {name} exceeds the byte bound')
        actual = file_sha256(path)
        if actual != digest:
            raise StageRefused('manuscript_result_changed', f'supplied result {name} differs from its intake digest')
        found[name] = {'path': str(path), 'sha256': actual, 'source': 'supplied'}
    return found


def sources(inputs, options, out):
    for name in ('claim_map', 'note'):
        if name not in inputs:
            raise StageRefused('manuscript_input_missing', f'the launch names no {name}')
    claim_map = validate_claim_map(json.loads(Path(inputs['claim_map']).read_text()))
    note_text = Path(inputs['note']).read_text()
    results = _results(inputs, options.get('supplied') or {})
    items = integrity(claim_map, results, note_text)
    failing = [i['id'] for i in items if i['verdict'] != 'pass']
    figure_files, figure_names = {}, {}
    if not failing:
        for figure in claim_map.get('figures', []):
            row = results[figure['result']]
            name = f"{figure['id']}{Path(row['path']).suffix.lower()}"
            figure_names[figure['id']] = name
            figure_files[f'figures/{name}'] = Path(row['path']).read_bytes()
    tex = render(claim_map, results, note_text, figure_names) if not failing else (
        '% the integrity items failed; no source was rendered\n')
    (out / 'sources').mkdir(parents=True, exist_ok=True)
    (out / 'sources' / 'main.tex').write_text(tex)
    files = {'main.tex': tex.encode(), **figure_files}
    _bundle(out / 'sources.tar', files)
    bundle = {'schema_version': SCHEMA_VERSION, 'kind': 'manuscript-source-bundle', 'title': claim_map['title'],
              'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())},
              'claims': {c['id']: {'result': c['result'], 'sha256': claim_map['results'][c['result']]['sha256']}
                         for c in claim_map['claims']},
              'results': {n: {'sha256': r['sha256'], 'source': r['source']} for n, r in sorted(results.items())},
              'claim_map_sha256': file_sha256(inputs['claim_map']), 'note_sha256': file_sha256(inputs['note']),
              'status': 'refused' if failing else 'completed'}
    _write_json(out / 'bundle.json', bundle)
    _write_json(out / 'integrity.json', {'schema_version': SCHEMA_VERSION, 'kind': 'manuscript-integrity',
                                         'passed': not failing, 'failing': failing, 'items': items})
    if failing:
        raise StageRefused('manuscript_integrity_failed', 'integrity items fail: ' + ', '.join(failing),
                           {'failing': failing})


def _tex_engine(path):
    if not path:
        return None
    engine = Path(path)
    return engine if engine.is_file() and os.access(engine, os.X_OK) else None


def pdf(inputs, options, out):
    for name in ('sources', 'bundle'):
        if name not in inputs:
            raise StageRefused('manuscript_input_missing', f'the launch names no {name}')
    bundle = json.loads(Path(inputs['bundle']).read_text())
    if bundle.get('kind') != 'manuscript-source-bundle' or bundle.get('status') != 'completed':
        raise StageRefused('manuscript_sources_refused', 'the source bundle did not pass its integrity items')
    try:
        with tarfile.open(inputs['sources']) as archive:
            members = archive.getmembers()
            if (len(members) > 128 or len({m.name for m in members}) != len(members)
                    or any(m.name.startswith('/') or '..' in Path(m.name).parts or not m.isfile() for m in members)
                    or sum(m.size for m in members) > MAX_RESULT_BYTES):
                raise ValueError('unsafe, duplicate or oversized source member')
            files = {m.name: archive.extractfile(m).read() for m in members}
        if {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()} != bundle['files']:
            raise ValueError('source bundle differs from its manifest')
    except (tarfile.TarError, KeyError, OSError, ValueError) as exc:
        raise StageRefused('manuscript_sources_invalid', str(exc)) from None
    engine = _tex_engine(options.get('tex'))
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'manuscript-build', 'bundle_sha256': file_sha256(inputs['bundle']),
              'sources_sha256': file_sha256(inputs['sources']), 'engine': None, 'passes': 0}
    if engine is None:
        _write_json(out / 'build.json', {**record, 'status': 'qualified', 'reason': 'no TeX engine on this host'})
        raise StageQualified('manuscript_tex_unavailable', 'no TeX engine is available to this launch; the reviewed '
                             'source bundle is the deliverable', {'inputs': ['sources', 'bundle']})
    version = subprocess.run([str(engine), '--version'], capture_output=True, text=True, timeout=60)
    record['engine'] = {'path': str(engine), 'sha256': file_sha256(engine.resolve()),
                        'version': (version.stdout.splitlines() or [''])[0][:200]}
    budget = float(options.get('wall_seconds') or 900)
    with tempfile.TemporaryDirectory(prefix='note-build-') as scratch:
        build = Path(scratch)
        for name, raw in files.items():
            (build / name).parent.mkdir(parents=True, exist_ok=True)
            (build / name).write_bytes(raw)
        env = {'PATH': f'{engine.parent}{os.pathsep}/usr/bin:/bin', 'HOME': scratch, 'TEXMFVAR': str(build / '.texmf-var'),
               'TEXMFCONFIG': str(build / '.texmf-config'), 'openout_any': 'p', 'openin_any': 'p',
               'shell_escape': 'f', 'LANG': 'C'}
        log = ''
        for _ in range(TEX_PASSES):
            try:
                found = subprocess.run([str(engine), '-no-shell-escape', '-interaction=nonstopmode', '-halt-on-error',
                                        'main.tex'], cwd=build, env=env, capture_output=True, text=True,
                                       timeout=max(30.0, budget / (TEX_PASSES + 1)))
            except subprocess.TimeoutExpired:
                _write_json(out / 'build.json', {**record, 'status': 'refused', 'reason': 'a TeX pass timed out'})
                raise StageRefused('manuscript_build_failed', 'a TeX pass exceeded its time bound') from None
            log = (found.stdout or '')[-4000:]
            record['passes'] += 1
            if found.returncode != 0 or not (build / 'main.pdf').is_file():
                _write_json(out / 'build.json', {**record, 'status': 'refused', 'reason': 'the TeX build failed',
                                                 'log_tail': log})
                raise StageRefused('manuscript_build_failed', 'the TeX build failed; the log tail is recorded',
                                   {'log_tail': log[-1500:]})
        shutil.copyfile(build / 'main.pdf', out / 'manuscript.pdf')
    _write_json(out / 'build.json', {**record, 'status': 'completed', 'pdf_sha256': file_sha256(out / 'manuscript.pdf'),
                                     'log_tail': log[-1500:]})


RUNNERS = {'sources': sources, 'pdf': pdf}


def _placeholder(path, stage, status):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.json':
        _write_json(path, {'kind': 'manuscript-stage-placeholder', 'stage': stage, 'status': status, 'placeholder': True})
    elif path.suffix == '.tar':
        _bundle(path, {'PLACEHOLDER': f'the {stage} stage ended {status}\n'.encode()})
    else:
        path.write_text(f'Placeholder: the {stage} stage ended with status {status}; this is not a result.\n')


def run_stage(stage, inputs, options, workdir, *, output_root=None):
    """Write plan-relative outputs under ``workdir``, or directly in a native ``output_root``."""
    workdir = Path(workdir)
    out = Path(output_root) if output_root is not None else workdir / 'outputs'
    out.mkdir(parents=True, exist_ok=True)
    def target(path):
        return out / path.removeprefix('outputs/')
    began = time.monotonic()
    status, codes, reason, evidence = 'completed', [], None, None
    try:
        RUNNERS[stage](inputs, options, out)
    except StageRefused as exc:
        status, codes, reason, evidence = exc.status, [exc.code], exc.detail, exc.evidence
    placeholders = []
    for path, _ in OUTPUTS[stage]:
        destination = target(path)
        if path != RECEIPT and path != 'outputs/manuscript.pdf' and not destination.exists():
            _placeholder(destination, stage, status)
            placeholders.append(path)
    receipt = {'schema_version': SCHEMA_VERSION, 'kind': 'manuscript-stage-receipt', 'stage': stage,
               'operation': OPERATIONS[stage], 'status': status, 'codes': codes, 'reason': reason, 'evidence': evidence,
               'inputs': {name: {'path': str(path), 'sha256': file_sha256(path)} for name, path in sorted(inputs.items())},
               'supplied': {n: {'path': str(p), 'sha256': d} for n, (p, d) in sorted((options.get('supplied') or {}).items())},
               'outputs': {path: file_sha256(target(path)) for path, _ in OUTPUTS[stage] if path != RECEIPT and target(path).is_file()},
               'placeholders': placeholders, 'implementation': {'module': __name__, 'sha256': file_sha256(Path(__file__))},
               'wall_seconds': time.monotonic() - began, 'scientific_acceptance': False}
    _write_json(target(RECEIPT), receipt)
    return receipt


def _named(rows, root):
    found = {}
    for row in rows or ():
        name, sep, relative = row.partition('=')
        if not sep or not re.fullmatch(r'(claim_map|note|sources|bundle|result\.[A-Za-z][A-Za-z0-9_.-]{0,63})', name) \
                or name in found or os.path.isabs(relative) or '..' in Path(relative).parts:
            raise SystemExit(f'--input expects a unique known name=run-relative path, not {row!r}')
        found[name] = Path(os.path.normpath(os.path.join(root, relative)))
    return found


def _supplied(rows):
    found = {}
    for row in rows or ():
        name, sep, rest = row.partition('=')
        path, at, digest = rest.rpartition('@')
        if not sep or not at or not SAFE_ID.fullmatch(name) or not os.path.isabs(path) or not re.fullmatch(
                r'[0-9a-f]{64}', digest) or name in found:
            raise SystemExit(f'--result expects name=/absolute/path@sha256, not {row!r}')
        found[name] = (Path(path), digest)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m ravel.controller.routes.manuscript.note')
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--root', required=True)
    parser.add_argument('--input', action='append', default=[])
    parser.add_argument('--result', action='append', default=[])
    parser.add_argument('--tex', default='')
    parser.add_argument('--wall-seconds', type=int, default=900)
    args = parser.parse_args(argv)
    root = args.root if os.path.isabs(args.root) else os.path.normpath(os.path.join(os.getcwd(), args.root))
    inputs, supplied = _named(args.input, root), _supplied(args.result)
    try:
        receipt = run_stage(args.stage, inputs, {'supplied': supplied, 'tex': args.tex,
                                                 'wall_seconds': args.wall_seconds}, Path.cwd(),
                            output_root=Path.cwd())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        target = Path.cwd() / RECEIPT.removeprefix('outputs/')
        if not target.exists():
            _write_json(target, {'schema_version': SCHEMA_VERSION, 'kind': 'manuscript-stage-receipt',
                                 'stage': args.stage, 'operation': OPERATIONS[args.stage], 'status': 'failed',
                                 'codes': ['manuscript_stage_exception'], 'reason': f'{type(exc).__name__}: {exc}'[:2000]})
        return 1
    print(json.dumps({'stage': args.stage, 'status': receipt['status'], 'codes': receipt['codes']}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
