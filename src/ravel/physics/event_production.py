"""Shower and detector production for any generated sample, as a planned, approved study.

Science mode ``event-production`` takes parton-level events (LHE) from any generator and
model and produces Delphes ROOT files with a ``production-receipt.json``::

    {"events": {"lhe": "unweighted_events.lhe.gz", "generation_receipt": "generation.json"},
     "process": {"description": "p p > n2 x1+"},
     "model": {"name": "MSSM_SLHA2", "slha": "param_card.dat", "produced": [1000023, 1000024],
               "invisible": [1000022], "visible_stable": []},
     "shower": {"commands": ["Tune:pp = 14", "SLHA:useDecayTable = on"], "seed": 1234,
                "merging": {...}, "variants": [{"name": "qcut-low", "commands": ["JetMatching:qCut = 25"]}]},
     "detector": {"cards": [{"name": "cms", "card": "delphes_card_CMS.tcl",
                             "fix_invisibles": true, "keep_branches": ["Jet", "MissingET"]}]},
     "normalization": {"sigma": "lhe-init"},
     "chunks": 4, "parallel": 1, "retain_hepmc": false, "merge": "list",
     "backend": {"kind": "native"}, "tools": {...}, "resources": {...}}

Planning reads the LHE header (generator, process, model, run card and init block), checks
the declared Pythia command lines, resolves the installed shower and Delphes programs,
builds the model's invisible-state census and checks every detector card against it. A
card that would reconstruct an invisible state is refused unless ``fix_invisibles`` asks for
a managed derived card, whose every change is recorded. A sample generated with
``ickkw = 1`` is refused without a complete MLM matching block, and a matching block is
refused for a sample generated without ``ickkw = 1``.

The approved worker splits the LHE into seed-distinct chunks. Each chunk is one stage
specification for ``ravel.workflow.execution_backend`` (native by default), run under the
machine lease: Pythia 8 showers its events, the output contracts accept the shower
(``ravel.workflow.output_gate``), the stable BSM states seen in the showered events are
checked against the census, and Delphes runs every declared card on the same showered
events. Each chunk's outputs are accepted only after their contracts pass again on the
fetched files. Chunks are merged per card (a pinned file list, or ``hadd`` with the
entry count and the weight sums verified), and the receipt records generator, shower and
detector versions, cards with sha256, process, model identity, events attempted and
accepted, the cross section with its source and convention, the per-event weight
convention and the merging scheme with its matched-cross-section accounting.

``ravel event-production`` checks a task and its cards without running anything; the
production itself runs only through ordinary science plan, approval and run.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SCOPE = 'declared_shower_and_detector_production'
OUTPUT = 'event-production'
RECEIPT = 'production-receipt.json'
TASK_KEYS = {'events', 'model', 'shower', 'detector', 'normalization'}
OPTIONAL = {'process', 'chunks', 'parallel', 'backend', 'tools', 'retain_hepmc', 'resources', 'merge', 'description'}
RESERVED_PYTHIA = ('beams:frametype', 'beams:lhef', 'beams:nskiplhefatinit', 'main:numberofevents',
                   'random:setseed', 'random:seed')
MLM_REQUIRED = ('JetMatching:merge', 'JetMatching:scheme', 'JetMatching:setMad', 'JetMatching:qCut',
                'JetMatching:nJetMax', 'JetMatching:nQmatch')
QCD_PARTONS = frozenset({1, 2, 3, 4, 5, 21})
DEFAULT_RESOURCES = {'cpus_per_chunk': 1, 'memory_mib': 4096, 'wall_seconds_per_chunk': 7200}
# Disk estimates used only by the preflight (bytes per event).
DISK_ESTIMATE = {'delphes_full': 300_000, 'delphes_skimmed': 20_000, 'hepmc': 200_000}
TOOL_CHECKS = {'shower': ('shower', 'pythia8'), 'shower_merged': ('shower-merged', 'pythia8'),
               'delphes': ('delphes', 'delphes'), 'hadd': (None, 'root')}
POLL_SECONDS = 1.0


# ---------------------------------------------------------------- small helpers
def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _pin(path):
    path = Path(path)
    return {'path': str(path.resolve()), 'sha256': sha256(path)}


def _resolve(base, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(base) / path


def _regular(base, value, label):
    path = _resolve(base, value)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'{label} must be a regular file: {path}')
    return path.resolve()


def _write_new(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(document, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return path


def _opener(path):
    return gzip.open if str(path).endswith('.gz') else open


def _keys(value, required, optional, label):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError(f'{label} needs {sorted(required)} and may add {sorted(optional)}')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be stated')
    return value


# ---------------------------------------------------------------- LHE header
def read_header(path):
    """Banner blocks and the init block of an LHE file (stops at the first event)."""
    banner, init, block, lines = {}, [], None, []
    with _opener(path)(path, 'rt', errors='replace') as stream:
        for raw in stream:
            line = raw.rstrip('\n')
            stripped = line.strip()
            if stripped.startswith('<event'):
                break
            match = re.match(r'<(MGVersion|MG5ProcCard|MGProcCard|MGRunCard|slha|MGGenerationInfo)\b[^>]*>', stripped)
            if match and block is None:
                block, lines = match.group(1), []
                continue
            if block is not None and stripped.startswith(f'</{block}'):
                banner[block] = '\n'.join(lines)
                block = None
                continue
            if stripped == '<init>':
                block = 'init'
                continue
            if stripped == '</init>':
                block = None
                continue
            if block == 'init':
                init.append(stripped)
            elif block is not None:
                lines.append(line)
    if not init:
        raise ValueError('the LHE file has no init block')
    header = init[0].split()
    if len(header) != 10:
        raise ValueError('invalid LHE init header')
    nprocess = int(header[9])
    rows = [r.split() for r in init[1:nprocess + 1]]
    generator = None
    for row in init[nprocess + 1:]:
        match = re.search(r"<generator\s+name=['\"]([^'\"]+)['\"]\s+version=['\"]([^'\"]+)['\"]", row)
        if match:
            generator = {'name': match.group(1), 'version': match.group(2), 'source': 'LHE init <generator> tag'}
    if generator is None and 'MGVersion' in banner:
        match = re.search(r'([0-9]+\.[0-9]+\.[0-9]+)', banner['MGVersion'])
        if match:
            generator = {'name': 'MadGraph5_aMC@NLO', 'version': match.group(1), 'source': 'LHE banner MGVersion'}
    run_card = {}
    for line in banner.get('MGRunCard', '').splitlines():
        body = line.split('!', 1)[0].split('#', 1)[0]
        if '=' in body:
            value, key = (part.strip() for part in body.split('=', 1))
            if key and value:
                run_card[key.lower()] = value
    process_lines = [l.split('#', 1)[0].strip() for l in banner.get('MG5ProcCard', banner.get('MGProcCard', '')).splitlines()
                     if re.match(r'\s*(generate|add process|import model|define)\b', l)]
    model = next((l.split()[2] for l in process_lines if l.startswith('import model') and len(l.split()) > 2), None)
    return {'beam_pdg': [int(header[0]), int(header[1])], 'beam_energy_gev': [float(header[2]), float(header[3])],
            'pdf_ids': [int(header[6]), int(header[7])], 'idwtup': int(header[8]), 'nprocess': nprocess,
            'subprocesses': [{'sigma_pb': float(r[0]), 'error_pb': float(r[1]), 'max_weight': float(r[2]),
                              'id': int(r[3])} for r in rows],
            'generator': generator, 'run_card': run_card, 'process_lines': process_lines, 'model': model,
            'has_slha': 'slha' in banner}


def scan_events(path):
    """Event count, weights and the number of outgoing QCD partons per event."""
    n, weights, multiplicity, current, closed = 0, [], {}, None, False
    with _opener(path)(path, 'rt', errors='replace') as stream:
        for raw in stream:
            line = raw.strip()
            if line.startswith('<event'):
                current = []
            elif line.startswith('</event'):
                if not current:
                    raise ValueError('empty LHE event')
                head = current[0].split()
                count = int(head[0])
                weight = float(head[2])
                partons = sum(1 for row in current[1:count + 1]
                              if int(row.split()[1]) == 1 and abs(int(row.split()[0])) in QCD_PARTONS)
                n += 1
                weights.append(weight)
                entry = multiplicity.setdefault(partons, {'events': 0, 'sumw': 0.0})
                entry['events'] += 1
                entry['sumw'] += weight
                current = None
            elif current is not None and line and not line.startswith('<') and not line.startswith('#'):
                current.append(line)
            elif line.startswith('</LesHouchesEvents'):
                closed = True
    if not closed:
        raise ValueError('the LHE file is truncated (no closing tag)')
    return {'events': n, 'weights': weights, 'multiplicity': multiplicity}


# ---------------------------------------------------------------- Pythia commands
def _setting_lines(commands):
    out = []
    for line in commands:
        if not isinstance(line, str) or '=' not in line or '\n' in line:
            raise ValueError(f'Pythia command lines must be single "Key = value" lines: {line!r}')
        key, value = (part.strip() for part in line.split('=', 1))
        if not key or not value:
            raise ValueError(f'malformed Pythia command line {line!r}')
        out.append((key, value))
    return out


def _settings(commands):
    return {k.lower(): (k, v) for k, v in _setting_lines(commands)}


def shower_commands(shower, base):
    commands = list(shower.get('commands', []))
    if 'cmnd' in shower:
        text = _regular(base, shower['cmnd'], 'shower.cmnd').read_text()
        commands = [l.split('#', 1)[0].split('!', 1)[0].strip() for l in text.splitlines()]
        commands = [l for l in commands if l] + list(shower.get('commands', []))
    pairs = _setting_lines(commands)
    for key, _ in pairs:
        if key.lower() in RESERVED_PYTHIA:
            raise ValueError(f'{key} is set by the production stage (input file, chunking and seeds)')
    from ravel.physics.pythia_cards import parse
    parse('\n'.join(commands))
    return commands


def _merged_commands(commands, merging):
    if merging is None:
        return list(commands)
    settings = merging['settings']
    return list(commands) + [f'{k} = {v}' for k, v in settings.items()]


def check_merging(header, merging):
    """Refuse a merged plan without complete matching settings, and the reverse."""
    ickkw = header['run_card'].get('ickkw')
    generated_merged = ickkw is not None and int(float(ickkw)) == 1
    if merging is None:
        if generated_merged:
            raise ValueError('the sample was generated with ickkw = 1; showering it without MLM matching '
                             'double counts jets. Declare shower.merging with the matching settings')
        return None
    _keys(merging, ('scheme', 'settings', 'base_partons'), ('description',), 'shower.merging')
    if merging['scheme'] != 'MLM':
        raise ValueError('shower.merging.scheme must be MLM (the supervised merged shower implements MLM)')
    if type(merging['base_partons']) is not int or merging['base_partons'] < 0:
        raise ValueError('shower.merging.base_partons is the number of QCD partons in the lowest-multiplicity process')
    settings = merging['settings']
    if not isinstance(settings, dict):
        raise ValueError('shower.merging.settings maps Pythia JetMatching keys to values')
    missing = [k for k in MLM_REQUIRED if k not in settings]
    if missing:
        raise ValueError('a merged plan needs every matching setting: missing ' + ', '.join(missing))
    if str(settings['JetMatching:merge']).lower() not in ('on', 'true', '1'):
        raise ValueError('JetMatching:merge must be on')
    if str(settings['JetMatching:scheme']) != '1':
        raise ValueError('JetMatching:scheme must be 1 (MadGraph-style MLM)')
    if str(settings['JetMatching:setMad']).lower() not in ('off', 'false', '0'):
        raise ValueError('JetMatching:setMad must be off; state qCut, nJetMax and nQmatch explicitly')
    try:
        qcut = float(settings['JetMatching:qCut'])
        njetmax = int(settings['JetMatching:nJetMax'])
    except (TypeError, ValueError) as exc:
        raise ValueError('JetMatching:qCut must be a number and JetMatching:nJetMax an integer') from exc
    if not generated_merged:
        raise ValueError(f'the LHE run card states ickkw = {ickkw}; MLM matching needs a sample generated with ickkw = 1')
    xqcut = header['run_card'].get('xqcut')
    if xqcut is None:
        raise ValueError('the LHE run card does not state xqcut')
    if qcut < float(xqcut):
        raise ValueError(f'JetMatching:qCut {qcut:g} is below the generation xqcut {float(xqcut):g}')
    if njetmax < 0:
        raise ValueError('JetMatching:nJetMax must be nonnegative')
    return {'scheme': 'MLM', 'settings': {k: str(v) for k, v in settings.items()}, 'base_partons': merging['base_partons'],
            'ickkw': int(float(ickkw)), 'xqcut': float(xqcut), 'qcut': qcut, 'njetmax': njetmax}


# ---------------------------------------------------------------- tools
def installed_tool(name):
    """Path and version of an installed tool from the native toolchain manifest."""
    from ravel.setup import manifest as mf
    from ravel.setup.installer import resolve_prefix
    check_id, package = TOOL_CHECKS[name]
    repo = mf.repo_root()
    document, _ = mf.load(repo)
    values = mf.variables(resolve_prefix(repo), repo, mf.detect_platform())
    lookup = check_id or 'delphes'
    for group in document['groups']:
        check = next((c for c in group.get('checks', []) if c.get('id') == lookup), None)
        if check is None:
            continue
        specs = [s for step in group.get('steps', []) for s in step.get('specs', [])]
        version = next((s.split('=', 1)[1] for s in specs if s.split('=', 1)[0] == package), None)
        path = mf.expand(check['path'], values) if check_id else str(Path(mf.expand(check['path'], values)).parent / 'hadd')
        return {'path': path, 'version': version,
                'version_source': f'toolchain manifest group {group["id"]} ({package})' if version else None}
    raise ValueError(f'the toolchain manifest has no {name} program; declare tools.{name}')


def resolve_tools(task, merged, needs_hadd):
    declared = task.get('tools', {})
    if not isinstance(declared, dict) or set(declared) - set(TOOL_CHECKS):
        raise ValueError(f'tools may name {sorted(TOOL_CHECKS)}')
    wanted = ['shower_merged' if merged else 'shower', 'delphes'] + (['hadd'] if needs_hadd else [])
    tools = {}
    for name in wanted:
        entry = declared.get(name)
        if isinstance(entry, str):
            entry = {'path': entry}
        if entry is None:
            entry = installed_tool(name)
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise ValueError(f'tools.{name} must be a path or {{path, version}}')
        path = Path(entry['path']).expanduser()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f'{name} program not installed at {path}; run "ravel doctor" for the exact fix')
        tools[name] = {'path': str(path.resolve()), 'sha256': sha256(path), 'version': entry.get('version'),
                       'version_source': entry.get('version_source') or ('declared' if entry.get('version') else None)}
    return tools


# ---------------------------------------------------------------- task
def validate(task):
    """Structure only (no files read)."""
    _keys(task, TASK_KEYS, OPTIONAL, 'event-production task')
    _keys(task['events'], ('lhe',), ('generation_receipt', 'lhe_transform', 'max_events'), 'events')
    if 'max_events' in task['events'] and (type(task['events']['max_events']) is not int or task['events']['max_events'] < 1):
        raise ValueError('events.max_events must be a positive integer')
    _keys(task['model'], ('name', 'invisible'), ('visible_stable', 'slha', 'produced', 'closure_report', 'bsm_pdgs', 'ufo'), 'model')
    _text(task['model']['name'], 'model.name')
    _keys(task['shower'], ('seed',), ('commands', 'cmnd', 'merging', 'variants', 'census_events'), 'shower')
    if type(task['shower']['seed']) is not int or not 1 <= task['shower']['seed'] <= 900_000_000 - 10_000:
        raise ValueError('shower.seed must be an integer from 1 to 899990000 (Pythia seeds; chunks add their index)')
    for variant in task['shower'].get('variants', []):
        _keys(variant, ('name', 'commands'), ('description',), 'shower variant')
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', variant['name']) or variant['name'] == 'nominal':
            raise ValueError('a variant name is lower-case letters, digits and hyphens, and not "nominal"')
    cards = task['detector'].get('cards') if isinstance(task['detector'], dict) else None
    _keys(task['detector'], ('cards',), (), 'detector')
    if not isinstance(cards, list) or not cards:
        raise ValueError('detector.cards lists at least one Delphes card')
    names = set()
    for card in cards:
        _keys(card, ('name', 'card'), ('fix_invisibles', 'keep_branches', 'overrides', 'bytes_per_event', 'required_branches'),
              'detector card')
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', card['name']) or card['name'] in names:
            raise ValueError('detector card names are unique lower-case identifiers')
        names.add(card['name'])
    normalization = task['normalization']
    if not isinstance(normalization, dict) or normalization.get('sigma') not in ('lhe-init', 'ledger', 'generation-receipt', 'registry'):
        raise ValueError('normalization.sigma is lhe-init, ledger, generation-receipt or registry')
    if normalization['sigma'] == 'lhe-init':
        _keys(normalization, ('sigma',), (), 'normalization')
    elif normalization['sigma'] == 'ledger':
        _keys(normalization, ('sigma', 'ledger'), (), 'normalization')
    elif normalization['sigma'] == 'registry':
        _keys(normalization, ('sigma', 'request'), ('process_basis',), 'normalization')
        from ravel.physics.cross_sections import validate_request
        validate_request(normalization['request'])
    elif set(normalization) == {'sigma'}:
        pass  # the cross section of the generation-receipt point that produced the LHE file
    else:
        _keys(normalization, ('sigma', 'pointer', 'source', 'convention'), (), 'normalization')
        _keys(normalization['convention'], ('order', 'tool', 'pdf', 'scales', 'process_basis'), (), 'normalization.convention')
    chunks = task.get('chunks', 1)
    if type(chunks) is not int or not 1 <= chunks <= 10_000:
        raise ValueError('chunks must be an integer from 1 to 10000')
    parallel = task.get('parallel', 1)
    if type(parallel) is not int or not 1 <= parallel <= 512:
        raise ValueError('parallel must be an integer from 1 to 512')
    if task.get('merge', 'list') not in ('list', 'hadd'):
        raise ValueError('merge is list or hadd')
    if 'retain_hepmc' in task and type(task['retain_hepmc']) is not bool:
        raise ValueError('retain_hepmc must be true or false')
    resources = {**DEFAULT_RESOURCES, **task.get('resources', {})}
    if set(resources) - set(DEFAULT_RESOURCES) or any(type(v) is not int or v < 1 for v in resources.values()):
        raise ValueError(f'resources may set {sorted(DEFAULT_RESOURCES)} as positive integers')
    backend = task.get('backend', {'kind': 'native'})
    _keys(backend, ('kind',), ('image', 'site', 'readonly_trees', 'python', 'workdir'), 'backend')


def _sigma_block(task, base, header, generation=None):
    """The cross section before matching, with its source and convention."""
    normalization = task['normalization']
    if normalization['sigma'] == 'lhe-init':
        generator = header['generator'] or {'name': 'not stated in the LHE file', 'version': None}
        run = header['run_card']
        pdf = (f"LHAPDF {run['lhaid']}" if run.get('lhaid') and run.get('pdlabel', '').lower() == 'lhapdf'
               else run.get('pdlabel') or f"PDF ids {header['pdf_ids']}")
        scale = run.get('dynamical_scale_choice')
        return {'value_pb': math.fsum(r['sigma_pb'] for r in header['subprocesses']),
                'uncertainty_pb': math.sqrt(math.fsum(r['error_pb'] ** 2 for r in header['subprocesses'])),
                'source': 'LHE init block (sum of XSECUP over subprocesses)',
                'convention': {'order': 'LO', 'tool': f"{generator['name']} {generator.get('version') or ''}".strip(),
                               'pdf': pdf, 'scales': f'dynamical_scale_choice = {scale}' if scale else 'not stated in the run card',
                               'process_basis': '; '.join(l for l in header['process_lines'] if l.startswith(('generate', 'add process')))
                               or 'not stated in the LHE banner'}}
    if normalization['sigma'] == 'ledger':
        path = _regular(base, normalization['ledger'], 'normalization.ledger')
        ledger = json.loads(path.read_text())
        block = ledger_receipt_block(ledger)
        return {'value_pb': block['sigma_pb'], 'source': block['sigma_source'], 'convention': block['sigma_convention'],
                'ledger': {'path': str(path), 'sha256': sha256(path)}, 'normalization_ledger': block['normalization_ledger']}
    if normalization['sigma'] == 'registry':
        from ravel.physics import cross_sections, normalization_ledger
        found = cross_sections.lookup(normalization['request'])
        row = normalization_ledger.from_cross_section(found, process_basis=normalization.get('process_basis'))
        return {'value_pb': float(found['sigma_pb']), 'uncertainty': found['uncertainty'], 'source': row['source'],
                'convention': {k: _text_of(row[k]) for k in ('order', 'tool', 'pdf', 'scales', 'process_basis')},
                'cross_section_lookup': found}
    receipt = task['events'].get('generation_receipt')
    if not receipt:
        raise ValueError('normalization.sigma generation-receipt needs events.generation_receipt')
    path = _regular(base, receipt, 'events.generation_receipt')
    if 'pointer' not in normalization:
        if generation is None or generation.get('point') is None:
            raise ValueError('normalization.sigma generation-receipt without a pointer needs a RAVEL generation '
                             'receipt (kind generation-receipt) that names this LHE file')
        xs = generation['cross_section']
        return {'value_pb': float(xs['value_pb']), 'uncertainty_pb': float(xs['error_pb']),
                'source': f"{xs['source']} (generation receipt point {generation['point']})",
                'convention': generation['convention'],
                'generation_receipt': {**generation['receipt'], 'pointer': f"/points/{generation['index']}/cross_section/value_pb"}}
    from ravel.validation.output_postconditions import _pointer
    try:
        value = _pointer(json.loads(path.read_text()), normalization['pointer'])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ValueError(f'generation receipt has no value at {normalization["pointer"]}') from exc
    if isinstance(value, bool) or type(value) not in (int, float) or not value > 0 or not math.isfinite(value):
        raise ValueError('the generation receipt cross section must be a positive number in pb')
    for key, text in normalization['convention'].items():
        _text(text, f'normalization.convention.{key}')
    return {'value_pb': float(value), 'source': _text(normalization['source'], 'normalization.source'),
            'convention': dict(normalization['convention']),
            'generation_receipt': {'path': str(path), 'sha256': sha256(path), 'pointer': normalization['pointer']}}


def _text_of(value):
    if value is None:
        return 'not recorded'
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def generation_link(task, base, lhe, commands_by_variant=()):
    """The generation-receipt point (and any LHE transform) that produced ``lhe``.

    A RAVEL generation receipt (``generation-receipt.json``, kind ``generation-receipt``)
    is validated, the point whose LHE file (or whose transformed LHE file) has the same
    sha256 as the input is selected, and that point's cards and LHE file are re-hashed
    against the receipt. A transform declared in the receipt or by a separate
    ``lhe-transform`` receipt (``events.lhe_transform``) must be the one that wrote the
    input, and its required shower settings must appear in every shower variant.
    Any other JSON document is only pinned (``normalization.pointer`` reads it).
    """
    from ravel.physics import generation_receipt as receipts
    events = task['events']
    digest = sha256(lhe)
    separate = None
    if events.get('lhe_transform'):
        tpath = _regular(base, events['lhe_transform'], 'events.lhe_transform')
        separate = json.loads(tpath.read_text())
        if not isinstance(separate, dict) or separate.get('kind') != 'lhe_transform' or separate.get('schema_version') != 1:
            raise ValueError('events.lhe_transform must be an lhe-transform receipt (<output>.transform.json)')
        if separate['output']['sha256'] != digest:
            raise ValueError('events.lhe_transform describes another output file than events.lhe')
        separate = {**separate, '_pin': _pin(tpath)}
    if not events.get('generation_receipt'):
        if separate is None:
            return None
        return {'receipt': None, 'point': None, 'match': 'transformed', 'transform': _transform_record(separate, commands_by_variant)}
    path = _regular(base, events['generation_receipt'], 'events.generation_receipt')
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or document.get('kind') != 'generation-receipt':
        if separate is not None:
            raise ValueError('events.lhe_transform is linked through a RAVEL generation receipt (kind generation-receipt)')
        return {'receipt': _pin(path), 'kind': 'declared', 'point': None}
    errors = receipts.validate(document)
    if errors:
        raise ValueError('generation receipt: ' + '; '.join(errors))
    embedded = (document.get('transform') or {}).get('points') or {}
    matches = []
    for index, point in enumerate(document['points']):
        record = point['lhe']
        transformed = embedded.get(point['id'])
        # A declared transform is preferred: an identity rewrite leaves the bytes unchanged.
        if separate is not None and record and separate['original']['sha256'] == record['sha256']:
            matches.append((index, point, 'transformed', None))
        elif transformed and transformed['output']['sha256'] == digest:
            matches.append((index, point, 'transformed', transformed))
        elif record and record['sha256'] == digest:
            matches.append((index, point, 'generated', None))
    if not matches:
        raise ValueError('the generation receipt names no LHE file (generated or transformed) with the sha256 of events.lhe')
    if len(matches) > 1:
        raise ValueError('the generation receipt names this LHE file for more than one point: '
                         + ', '.join(m[1]['id'] for m in matches))
    index, point, match, transformed = matches[0]
    root = path.parent
    pinned = [*point['cards'], *([point['lhe']] if point['lhe'] else [])]
    if transformed:
        pinned += [transformed['output'], transformed['receipt']]
    stale = [r['path'] for r in pinned if not (root / r['path']).is_file() or sha256(root / r['path']) != r['sha256']]
    if stale:
        raise ValueError('generation receipt files are missing or changed: ' + ', '.join(stale))
    transform = None
    if transformed:
        record = json.loads((root / transformed['receipt']['path']).read_text())
        transform = _transform_record({**record, '_pin': _pin(root / transformed['receipt']['path'])}, commands_by_variant)
    elif separate is not None:
        transform = _transform_record(separate, commands_by_variant)
    generator = document['generator']
    xs = point['cross_section']
    process = document['process'].get('generate') if isinstance(document['process'], dict) else document['process']
    return {'receipt': _pin(path), 'kind': 'generation-receipt', 'point': point['id'], 'index': index, 'match': match,
            'lhe_sha256': digest, 'generator': generator, 'model': document['model'], 'process': document['process'],
            'beams': document['beams'], 'pdf': document['pdf'], 'weights': document['weights'],
            'events': point['events'], 'cross_section': xs, 'cards': point['cards'], 'transform': transform,
            'cross_section_only': document.get('cross_section_only'),
            'convention': {'order': xs.get('order') or 'LO',
                           'tool': f"{generator.get('name', 'generator')} {generator.get('version') or ''}".strip(),
                           'pdf': _text_of(document['pdf']),
                           'scales': 'as in the executed run card pinned by the generation receipt',
                           'process_basis': _text_of(process)}}


def _transform_record(record, commands_by_variant):
    from ravel.physics import lhe_transform
    for name, commands in commands_by_variant:
        missing = lhe_transform.missing_settings(record, commands)
        if missing:
            raise ValueError(f'shower variant {name} lacks the settings the LHE transform requires: ' + ', '.join(missing))
    return {'receipt': record['_pin'], 'name': record['name'], 'rules_sha256': record['rules_sha256'],
            'original_sha256': record['original']['sha256'], 'output_sha256': record['output']['sha256'],
            'events_changed': record['events_changed'],
            'required_downstream_settings': record['required_downstream_settings'],
            'deviations': record['deviations']}


def ledger_receipt_block(ledger):
    """The A-08 normalization ledger's receipt block (``normalization_ledger.receipt_block``)."""
    try:
        from ravel.physics import normalization_ledger
    except ImportError:
        normalization_ledger = None
    if normalization_ledger is not None:
        return normalization_ledger.receipt_block(ledger)
    # Same documented interface: sigma x k x prod(BR) x filter, with the sigma convention.
    units = {'pb': 1.0, 'fb': 1e-3, 'nb': 1e3, 'mb': 1e9}
    if not isinstance(ledger, dict) or ledger.get('schema_version') != 1 or not isinstance(ledger.get('sigma'), dict):
        raise ValueError('normalization ledger schema_version 1 with a sigma block required')
    sigma = ledger['sigma']
    if sigma.get('unit') not in units or type(sigma.get('value')) not in (int, float) or not sigma['value'] > 0:
        raise ValueError('ledger sigma needs a positive value and a unit (pb, fb, nb or mb)')
    for key in ('order', 'tool', 'pdf', 'scales', 'process_basis', 'source'):
        _text(sigma.get(key), f'ledger sigma {key}')
    applied = sigma['value'] * units[sigma['unit']]
    applied *= (ledger.get('k') or {}).get('value', 1.0)
    for row in ledger.get('br') or []:
        applied *= row['value']
    applied *= (ledger.get('filter_eff') or {}).get('value', 1.0)
    return {'normalization_ledger': {**ledger, 'applied_sigma_pb': applied}, 'sigma_pb': applied,
            'sigma_source': sigma['source'],
            'sigma_convention': {k: sigma[k] for k in ('order', 'tool', 'pdf', 'scales', 'process_basis')}}


def _model_identity(task, base, header):
    model = task['model']
    identity = {'name': model['name'], 'banner_import': header['model']}
    if header['model'] is not None:
        banner = header['model'].split('-', 1)[0].rstrip('/').split('/')[-1]
        if banner != model['name'].split('-', 1)[0]:
            raise ValueError(f'model.name {model["name"]} differs from the LHE banner model {header["model"]}')
    files = []
    if model.get('ufo'):
        ufo = _resolve(base, model['ufo'])
        if not ufo.is_dir():
            raise ValueError(f'model.ufo must be the UFO directory: {ufo}')
        files = sorted(p for p in ufo.rglob('*') if p.is_file() and not p.is_symlink()
                       and '__pycache__' not in p.parts and p.suffix != '.pyc')
        digest = hashlib.sha256()
        for p in files:
            digest.update(p.relative_to(ufo).as_posix().encode() + b'\0' + sha256(p).encode() + b'\n')
        identity['ufo'] = {'path': str(ufo.resolve()), 'tree_sha256': digest.hexdigest(), 'files': len(files)}
    if model.get('slha'):
        identity['slha'] = _pin(_regular(base, model['slha'], 'model.slha'))
    return identity, files


def _process(task, header):
    declared = task.get('process')
    if declared is not None:
        _keys(declared, ('description',), (), 'process')
        _text(declared['description'], 'process.description')
    if declared is None and not header['process_lines']:
        raise ValueError('the LHE banner states no process; declare process.description')
    return {'declared': declared['description'] if declared else None, 'banner': header['process_lines']}


def compile_task(task, base):
    """Everything planning checks; returns the compiled production (no compute, nothing written)."""
    from ravel.physics import detector_card as dc
    validate(task)
    base = Path(base)
    lhe = _regular(base, task['events']['lhe'], 'events.lhe')
    header = read_header(lhe)
    merging = check_merging(header, task['shower'].get('merging'))
    commands = shower_commands(task['shower'], base)
    variants = [{'name': 'nominal', 'commands': _merged_commands(commands, merging)}]
    for variant in task['shower'].get('variants', []):
        changed = _settings(variant['commands'])
        for key in changed:
            if key in RESERVED_PYTHIA:
                raise ValueError(f'variant {variant["name"]} may not set {changed[key][0]}')
        rows = [l for l in variants[0]['commands'] if _setting_lines([l])[0][0].lower() not in changed]
        variants.append({'name': variant['name'], 'commands': rows + list(variant['commands'])})
    if merging is not None:
        for variant in variants[1:]:
            vset = _settings(variant['commands'])
            qcut = float(vset['jetmatching:qcut'][1])
            if qcut < merging['xqcut']:
                raise ValueError(f'variant {variant["name"]}: JetMatching:qCut {qcut:g} is below xqcut {merging["xqcut"]:g}')
    extra_inputs = []
    for variant in variants:
        settings = _settings(variant['commands'])
        if 'slha:file' in settings:
            extra_inputs.append(_regular(base, settings['slha:file'][1], 'SLHA:file'))
    census = dc.invisible_census(task['model'], base)
    cards = []
    for card in task['detector']['cards']:
        path = _regular(base, card['card'], f'detector card {card["name"]}')
        report = dc.gate(path, census)
        parsed = dc.parse_card(path)
        if not report['consistent'] and not card.get('fix_invisibles', False):
            raise ValueError(f'detector card {card["name"]} would reconstruct invisible states: '
                             + '; '.join(f['message'] for f in report['findings'][:4])
                             + '. Set fix_invisibles to write a managed derived card, or supply a consistent card')
        if card.get('keep_branches') is not None:
            present = set(dc.tree_branches(parsed))
            unknown = sorted(set(card['keep_branches']) - present - {'Event', 'Weight'})
            if unknown:
                raise ValueError(f'card {card["name"]} does not write branches {", ".join(unknown)}')
        cards.append({**card, 'path': str(path), 'sha256': sha256(path), 'gate': report,
                      'sources': [Path(s['path']) for s in parsed.sources]})
    identity, ufo_files = _model_identity(task, base, header)
    generation = generation_link(task, base, lhe, [(v['name'], v['commands']) for v in variants])
    sigma = _sigma_block(task, base, header, generation)
    tools = resolve_tools(task, merging is not None, task.get('merge', 'list') == 'hadd')
    process = _process(task, header)
    return {'lhe': lhe, 'header': header, 'merging': merging, 'variants': variants, 'census': census,
            'cards': cards, 'model': identity, 'ufo_files': ufo_files, 'sigma': sigma, 'tools': tools,
            'process': process, 'extra_inputs': extra_inputs, 'generation': generation}


def inputs(task, base):
    compiled = compile_task(task, base)
    files = [compiled['lhe'], *compiled['extra_inputs'], *compiled['ufo_files']]
    for key in ('generation_receipt', 'lhe_transform'):
        if task['events'].get(key):
            files.append(_regular(base, task['events'][key], f'events.{key}'))
    model = task['model']
    for key in ('slha', 'closure_report'):
        if model.get(key):
            files.append(_regular(base, model[key], f'model.{key}'))
    if 'cmnd' in task['shower']:
        files.append(_regular(base, task['shower']['cmnd'], 'shower.cmnd'))
    if task['normalization']['sigma'] == 'ledger':
        files.append(_regular(base, task['normalization']['ledger'], 'normalization.ledger'))
    for card in compiled['cards']:
        files += [Path(card['path']), *card['sources']]
    files += [Path(t['path']) for t in compiled['tools'].values()]
    return list(dict.fromkeys(Path(f) for f in files))


def execution_seconds(task, base):
    validate(task)
    resources = {**DEFAULT_RESOURCES, **task.get('resources', {})}
    jobs = task.get('chunks', 1) * (1 + len(task['shower'].get('variants', [])))
    waves = math.ceil(jobs / task.get('parallel', 1))
    merge = resources['wall_seconds_per_chunk'] if task.get('merge', 'list') == 'hadd' else 0
    return waves * resources['wall_seconds_per_chunk'] + merge + 600


# ---------------------------------------------------------------- chunk worker (runs inside a backend job)
def _run_logged(argv, log_path, cwd):
    with Path(log_path).open('w') as log:
        process = subprocess.run([str(a) for a in argv], stdout=log, stderr=subprocess.STDOUT, cwd=cwd)
    return process.returncode, Path(log_path).read_text(errors='replace')


def _pythia_version(text):
    match = re.search(r'This is PYTHIA version\s+([0-9]+\.[0-9]+)', text)
    return match.group(1) if match else None


def _refuse_chunk(out, receipt):
    _write_new(out / 'chunk-receipt.json', receipt)
    print('production chunk refused: ' + json.dumps(receipt['failure'], sort_keys=True), file=sys.stderr, flush=True)
    return 1


def run_chunk(plan_path):
    """One chunk: shower, contracts, BSM census, Delphes for every card, contracts. Exit code 0 on success."""
    from ravel.physics import detector_card as dc
    from ravel.workflow import output_gate
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text())
    out = Path(os.environ.get('RAVEL_OUTPUT_DIR', ''))
    if not os.environ.get('RAVEL_OUTPUT_DIR') or not out.is_dir():
        raise ValueError('a production chunk runs only inside an execution-backend job (RAVEL_OUTPUT_DIR)')
    dispatch = Path(plan['dispatch_record'])
    if not dispatch.is_file() or json.loads(dispatch.read_text()).get('chunk_plan_sha256') != sha256(plan_path):
        raise ValueError('this chunk was not dispatched by an approved production run')
    work = Path.cwd()
    gate_dir = out / 'gate'
    cmnd = work / 'pythia.cmnd'
    cmnd.write_text('\n'.join(plan['commands'] + [
        'Beams:frameType = 4', f'Beams:LHEF = {plan["lhe"]}', f'Beams:nSkipLHEFatInit = {plan["skip"]}',
        f'Main:numberOfEvents = {plan["events"]}', 'Random:setSeed = on', f'Random:seed = {plan["seed"]}']) + '\n')
    hepmc = work / 'events.hepmc'
    argv = [plan['shower'], cmnd, hepmc, plan['events']]
    if plan['merged']:
        argv += ['--accounting', out / 'accounting.json', '--djr', out / 'djr.tsv']
    code, text = _run_logged(argv, out / 'shower.log', work)
    contract = {'name': 'showered events', 'kind': 'hepmc', 'path': str(hepmc), 'min_events': 1}
    if not plan['merged']:
        contract['expected_events'] = plan['events']
    verdict = output_gate.evaluate('shower', returncode=code, log_text=text, contracts=[contract], toolchains=['pythia'])
    output_gate.record(gate_dir, verdict)
    receipt = {'schema_version': 1, 'kind': 'ravel-production-chunk', 'tag': plan['tag'], 'variant': plan['variant'],
               'seed': plan['seed'], 'skip': plan['skip'], 'requested': plan['events'], 'status': 'failed',
               'pythia_version': _pythia_version(text), 'gates': ['shower']}
    if verdict['verdict'] != 'accepted':
        receipt['failure'] = {'stage': 'shower', 'class': verdict['failure_class']}
        return _refuse_chunk(out, receipt)
    showered = verdict['contracts'][0]['observed']['events']
    if plan['merged']:
        accounting = json.loads((out / 'accounting.json').read_text())
        if accounting['accepted'] != showered:
            receipt['failure'] = {'stage': 'shower', 'class': 'contract_failed',
                                  'detail': f'accounting accepted {accounting["accepted"]} but HepMC holds {showered} events'}
            return _refuse_chunk(out, receipt)
        receipt['accounting'] = accounting
        attempted, accepted = accounting['attempted'], accounting['accepted']
        receipt['sigma_gen_pb'] = accounting['sigma_gen_mb'] * 1e9
    else:
        attempted = accepted = showered
        match = re.search(r'sigma\s*=\s*([-+0-9.eE]+)\s*mb', text)
        receipt['sigma_gen_pb'] = float(match.group(1)) * 1e9 if match else None
    receipt['events'] = {'attempted': attempted, 'accepted': accepted, 'not_accepted': attempted - accepted}
    census = dc.hepmc_census(hepmc, max_events=plan['census']['events'], bsm_pdgs=plan['census']['bsm_pdgs'])
    declared = set(plan['census']['invisible']) | set(plan['census']['visible_stable'])
    undeclared = sorted(int(p) for p in census['stable_bsm'] if int(p) not in declared)
    receipt['bsm_census'] = census
    if undeclared:
        receipt['failure'] = {'stage': 'census', 'class': 'contract_failed',
                              'detail': 'showered events contain stable BSM states that the model does not declare: '
                                        + ', '.join(map(str, undeclared))}
        return _refuse_chunk(out, receipt)
    receipt['outputs'] = {}
    for card in plan['cards']:
        output_gate.require_accepted(gate_dir, ['shower'])
        root = out / f'{card["name"]}.root'
        code, text = _run_logged([plan['delphes'], card['path'], root, hepmc], out / f'delphes-{card["name"]}.log', work)
        contract = {'name': f'{card["name"]} detector events', 'kind': 'delphes-root', 'path': str(root),
                    'expected_events': accepted, 'min_events': 1, 'required': card['required_branches'],
                    'weight': 'Event.Weight', 'forbid_all_zero_weights': True}
        stage = f'delphes-{card["name"]}'
        verdict = output_gate.evaluate(stage, returncode=code, log_text=text, contracts=[contract], toolchains=['delphes'])
        output_gate.record(gate_dir, verdict)
        receipt['gates'].append(stage)
        if verdict['verdict'] != 'accepted':
            receipt['failure'] = {'stage': stage, 'class': verdict['failure_class'],
                                  'contracts': [c['failures'] for c in verdict['contracts']]}
            return _refuse_chunk(out, receipt)
        observed = verdict['contracts'][0]['observed']
        receipt['outputs'][card['name']] = {'file': root.name, 'entries': observed['entries'],
                                            'sum_weights': observed['sum_weights'], 'sum_weights2': observed['sum_weights2'],
                                            'sha256': observed['sha256']}
    if plan['retain_hepmc']:
        from ravel.physics.native_event_io import compress_events
        receipt['hepmc'] = {'file': 'events.hepmc.gz', **compress_events(hepmc, out / 'events.hepmc.gz')}
    hepmc.unlink()
    receipt['status'] = 'passed'
    _write_new(out / 'chunk-receipt.json', receipt)
    print(f'production chunk {plan["tag"]}: {attempted} attempted, {accepted} accepted, '
          f'{len(receipt["outputs"])} detector card(s)', flush=True)
    return 0


# ---------------------------------------------------------------- the approved run
def _chunks(n_events, count):
    count = min(count, n_events)
    size, extra = divmod(n_events, count)
    rows, skip = [], 0
    for i in range(count):
        n = size + (1 if i < extra else 0)
        rows.append({'index': i, 'skip': skip, 'events': n})
        skip += n
    return rows


def _disk_preflight(task, compiled, out, n_events):
    need = 0
    for card in compiled['cards']:
        per = card.get('bytes_per_event') or (DISK_ESTIMATE['delphes_skimmed'] if card.get('keep_branches')
                                               else DISK_ESTIMATE['delphes_full'])
        need += per * n_events * len(compiled['variants'])
    chunk_events = math.ceil(n_events / task.get('chunks', 1))
    need += DISK_ESTIMATE['hepmc'] * chunk_events * task.get('parallel', 1) * 2
    if task.get('retain_hepmc'):
        need += DISK_ESTIMATE['hepmc'] // 4 * n_events * len(compiled['variants'])
    free = shutil.disk_usage(out).free
    record = {'estimated_bytes': int(need), 'free_bytes': int(free),
              'estimate': 'declared bytes_per_event per card, otherwise the production stage default estimates'}
    if free < need * 1.1:
        raise ValueError(f'not enough disk: the production needs about {need / 1e9:.2f} GB and {free / 1e9:.2f} GB are free')
    return record


def _derive_cards(compiled, out):
    from ravel.physics import detector_card as dc
    final = []
    for card in compiled['cards']:
        entry = {'name': card['name'], 'source': {'path': card['path'], 'sha256': card['sha256']},
                 'gate': card['gate'], 'required_branches': card.get('required_branches', ['Event.Weight'])}
        needs = (not card['gate']['consistent']) or card.get('keep_branches') is not None or card.get('overrides')
        if needs:
            derived = out / 'cards' / f'{card["name"]}.tcl'
            record = dc.derive_card(card['path'], derived, invisible=compiled['census']['invisible'],
                                    overrides=card.get('overrides', []), keep_branches=card.get('keep_branches'),
                                    reason='managed copy for this production')
            if not record['consistent']:
                raise ValueError(f'the derived card {card["name"]} is still inconsistent: {record["remaining_findings"]}')
            _write_new(out / 'cards' / f'{card["name"]}.record.json', record)
            (out / 'cards' / f'{card["name"]}.diff').write_text(record['diff'])
            entry.update(path=record['derived_card']['path'], sha256=record['derived_card']['sha256'],
                         derived={'record': f'cards/{card["name"]}.record.json', 'diff': f'cards/{card["name"]}.diff',
                                  'edits': [{k: e[k] for k in ('module', 'action', 'text', 'reason')} for e in record['edits']]})
        else:
            entry.update(path=card['path'], sha256=card['sha256'], derived=None)
        final.append(entry)
    return final


def _backend_spec(task, compiled, plan_path, tag, cards, merged, retain, out):
    backend = task.get('backend', {'kind': 'native'})
    resources = {**DEFAULT_RESOURCES, **task.get('resources', {})}
    rel = lambda name: (Path('chunks') / tag / name).as_posix()
    outputs = [{'name': 'chunk-receipt.json', 'destination': rel('chunk-receipt.json')},
               {'name': 'shower.log', 'destination': rel('shower.log')},
               {'name': 'gate', 'kind': 'directory', 'destination': rel('gate')}]
    for card in cards:
        outputs += [{'name': f'{card["name"]}.root', 'destination': rel(f'{card["name"]}.root')},
                    {'name': f'delphes-{card["name"]}.log', 'destination': rel(f'delphes-{card["name"]}.log')}]
    if merged:
        outputs += [{'name': 'accounting.json', 'destination': rel('accounting.json')},
                    {'name': 'djr.tsv', 'destination': rel('djr.tsv')}]
    if retain:
        outputs.append({'name': 'events.hepmc.gz', 'destination': rel('events.hepmc.gz')})
    tool = compiled['tools']['shower_merged' if merged else 'shower']
    spec = {'schema_version': 1, 'backend': backend['kind'], 'stage': f'production-{tag}',
            'argv': [backend.get('python', sys.executable), '-m', 'ravel.physics.event_production', 'chunk',
                     '--plan', str(plan_path)],
            'inputs': [{'path': str(plan_path)}, {'path': str(compiled['lhe'])},
                       {'path': tool['path'], 'sha256': tool['sha256']},
                       {'path': compiled['tools']['delphes']['path'], 'sha256': compiled['tools']['delphes']['sha256']},
                       *[{'path': c['path'], 'sha256': c['sha256']} for c in cards]],
            'outputs': outputs,
            'quantities': [{'name': 'accepted', 'output': 'chunk-receipt.json', 'pointer': '/events/accepted'}],
            'resources': {'cpus': resources['cpus_per_chunk'], 'memory_mib': resources['memory_mib'],
                          'wall_seconds': resources['wall_seconds_per_chunk']},
            'description': f'shower and detector chunk {tag}'}
    for key in ('image', 'site', 'readonly_trees', 'workdir'):
        if key in backend:
            spec[key] = backend[key]
    return spec


def _run_jobs(jobs, out, journal, parallel):
    """Submit, observe and fetch chunk jobs under the machine lease (local) or remote slots.

    A stop signal or any error cancels every active job before it propagates, so no chunk keeps
    running after the approved stage that owns it has ended.
    """
    import signal
    import threading
    from ravel.workflow import execution_backend as eb
    results = {}
    pending = list(jobs)
    active = {}

    class Stop(Exception):
        pass

    def stop(signum, frame):
        raise Stop(signum)
    previous = ({sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
                if threading.current_thread() is threading.main_thread() else {})
    with ExitStack() as stack:
        try:
            local = None
            while pending or active:
                # Local chunks are native jobs: one at a time under the calling stage's lease.
                while pending and len(active) < (parallel if local is False else 1):
                    job = pending.pop(0)
                    plan = eb.prepare(job['spec'], base=out)
                    if local is None:
                        local = plan['backend']['local']
                        if local:
                            stack.enter_context(eb.machine_lease(f'event-production:{out}', nested=True))
                    if not local:
                        slot = ExitStack()
                        slot.enter_context(eb.remote_slot(f'event-production:{out}:{job["tag"]}'))
                    else:
                        slot = None
                    attempt = out / 'backend' / job['tag']
                    handle = eb.submit(plan, attempt)
                    _journal(journal, {'event': 'submitted', 'tag': job['tag'], 'plan_sha256': plan['plan_sha256'],
                                       'handle': handle['tag'], 'backend': handle['backend']})
                    active[job['tag']] = (job, plan, handle, time.monotonic(), slot)
                for tag in list(active):
                    job, plan, handle, started, slot = active[tag]
                    observation = eb.observe(plan, handle)
                    if observation['state'] not in eb.TERMINAL:
                        if time.monotonic() - started <= plan['spec']['resources']['wall_seconds']:
                            continue
                        # The wait ends at the job's declared limit: the cancellation is bounded, and a job
                        # that is still not terminal after it is a recorded failure with what was last seen.
                        last = eb.cancel(plan, handle)
                        detail = 'wall-clock ceiling reached'
                        if last['state'] not in eb.TERMINAL:
                            detail += f"; the job was still {last['state']} after cancellation"
                        if last.get('detail'):
                            detail += f": {last['detail']}"
                        observation = {**last, 'state': 'failed', 'detail': detail}
                    del active[tag]
                    row = {'state': observation['state'], 'exit_code': observation.get('exit_code'),
                           'log_tail': eb.redact(eb.get(handle['backend']).logs(plan, handle) or '')[-4000:]}
                    if observation['state'] != 'succeeded' and observation.get('detail'):
                        row['detail'] = eb.redact(str(observation['detail']))
                    if observation['state'] == 'succeeded':
                        try:
                            row['fetch'] = eb.fetch(plan, handle, out)
                        except ValueError as exc:
                            row.update(state='failed', detail=str(exc))
                        else:
                            # The fetched, hashed copies are the outputs; the job's own copies would double the disk use.
                            job_output = Path(handle['job_dir']) / 'output'
                            if plan['backend']['local'] and job_output.is_dir():
                                shutil.rmtree(job_output)
                    if slot is not None:
                        slot.close()
                    _journal(journal, {'event': 'finished', 'tag': tag, 'state': row['state'],
                                       'exit_code': row.get('exit_code'), 'detail': row.get('detail')})
                    results[tag] = row
                if active:
                    time.sleep(POLL_SECONDS)
        except BaseException as exc:
            for tag, (job, plan, handle, started, slot) in active.items():
                try:
                    observation = eb.cancel(plan, handle)
                except Exception as cancel_error:
                    observation = {'state': 'unknown', 'detail': str(cancel_error)}
                _journal(journal, {'event': 'cancelled', 'tag': tag, 'state': observation.get('state'),
                                   'reason': type(exc).__name__})
                if slot is not None:
                    slot.close()
            if isinstance(exc, Stop):
                raise KeyboardInterrupt('event production stopped; active chunks were cancelled') from None
            raise
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return results


def _journal(path, row):
    from ravel.workflow.execution_backend import utc_now
    with Path(path).open('a') as stream:
        stream.write(json.dumps({'utc': utc_now(), **row}, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _verify_chunk(out, tag, cards, receipt):
    """Re-check the fetched outputs independently of the job's own report."""
    from ravel.workflow import output_gate
    contracts = [{'name': f'{c["name"]} detector events', 'kind': 'delphes-root',
                  'path': str(out / 'chunks' / tag / f'{c["name"]}.root'), 'expected_events': receipt['events']['accepted'],
                  'min_events': 1, 'required': c['required_branches'], 'weight': 'Event.Weight'} for c in cards]
    verdict = output_gate.evaluate(f'fetched-{tag}', returncode=0, contracts=contracts)
    output_gate.record(out / 'gate', verdict)
    return verdict


def _merge_card(task, compiled, out, variant, card, tags, receipts):
    resources = {**DEFAULT_RESOURCES, **task.get('resources', {})}
    rows = []
    for tag in tags:
        o = receipts[tag]['outputs'][card['name']]
        path = out / 'chunks' / tag / o['file']
        rows.append({'chunk': tag, 'path': str(path.resolve()), 'sha256': sha256(path), 'entries': o['entries'],
                     'sum_weights': o['sum_weights'], 'sum_weights2': o['sum_weights2']})
    totals = {'entries': sum(r['entries'] for r in rows), 'sum_weights': math.fsum(r['sum_weights'] for r in rows),
              'sum_weights2': math.fsum(r['sum_weights2'] for r in rows)}
    merged = {'scheme': 'file list', 'files': rows, **totals}
    if task.get('merge', 'list') == 'hadd':
        from ravel.validation.output_postconditions import check
        target = out / 'samples' / variant / f'{card["name"]}.root'
        target.parent.mkdir(parents=True, exist_ok=True)
        hadd = compiled['tools']['hadd']['path']
        spec = {'schema_version': 1, 'backend': task.get('backend', {'kind': 'native'})['kind'],
                'stage': f'production-merge-{variant}-{card["name"]}',
                # The native launcher does not expand variables, so a shell line places the output.
                'argv': ['/bin/sh', '-c', '"$0" -f -k "$RAVEL_OUTPUT_DIR/merged.root" "$@"', hadd, *[r['path'] for r in rows]],
                'inputs': [{'path': r['path'], 'sha256': r['sha256']} for r in rows] + [{'path': hadd}],
                'outputs': [{'name': 'merged.root', 'destination': target.relative_to(out).as_posix()}],
                # The declared per-chunk limit bounds the merge too (execution_seconds counts it once).
                'resources': {'cpus': 1, 'memory_mib': 2048, 'wall_seconds': resources['wall_seconds_per_chunk']}}
        result = _run_jobs([{'tag': f'merge-{variant}-{card["name"]}', 'spec': spec}], out, out / 'journal.jsonl', 1)
        row = next(iter(result.values()))
        if row['state'] != 'succeeded':
            raise ValueError(f'merging {card["name"]} ({variant}) failed: {row.get("detail") or row.get("log_tail", "")[-500:]}')
        checked = check({'name': 'merged events', 'kind': 'delphes-root', 'path': str(target),
                         'expected_events': totals['entries'], 'min_events': 1, 'weight': 'Event.Weight'})
        if not checked['passed']:
            raise ValueError(f'merged {card["name"]} file fails its contract: {checked["failures"]}')
        observed = checked['observed']
        if not math.isclose(observed['sum_weights'], totals['sum_weights'], rel_tol=1e-6, abs_tol=1e-12):
            raise ValueError('merged sum of weights differs from the chunk sums')
        merged.update(scheme='hadd', file={'path': str(target.resolve()), 'sha256': observed['sha256']},
                      verified={'entries': observed['entries'], 'sum_weights': observed['sum_weights']})
    return merged


def _djr_histograms(paths):
    edges = [x / 10 for x in range(-10, 41)]
    hist = {}
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            fields = line.split()
            n_me = fields[0]
            for i, value in enumerate(fields[1:3]):
                v = float(value)
                if v <= 0:
                    continue
                x = math.log10(v)
                counts = hist.setdefault(f'n_me={n_me}', {}).setdefault(f'djr{i}{i + 1}', [0] * (len(edges) - 1))
                k = next((j for j in range(len(edges) - 1) if edges[j] <= x < edges[j + 1]), None)
                if k is not None:
                    counts[k] += 1
    return {'variable': "log10 of Pythia's JetMatchingMadgraph::getDJR() values (first two)", 'edges': edges,
            'counts': hist}


def _matching(compiled, scan, receipts, tags, out):
    merging = compiled['merging']
    if merging is None:
        return {'scheme': 'none'}, None
    attempted = sum(receipts[t]['events']['attempted'] for t in tags)
    accepted = sum(receipts[t]['events']['accepted'] for t in tags)
    fraction = accepted / attempted
    sigma_pre = math.fsum(r['sigma_pb'] for r in compiled['header']['subprocesses'])
    total_w = math.fsum(m['sumw'] for m in scan['multiplicity'].values())
    pre = {str(k - merging['base_partons']): sigma_pre * m['sumw'] / total_w for k, m in sorted(scan['multiplicity'].items())}
    accepted_by_me = {}
    for t in tags:
        path = out / 'chunks' / t / 'djr.tsv'
        if path.is_file():
            for line in path.read_text().splitlines():
                if line.strip() and not line.startswith('#'):
                    accepted_by_me[line.split()[0]] = accepted_by_me.get(line.split()[0], 0) + 1
    pythia = [(receipts[t]['events']['attempted'], receipts[t].get('sigma_gen_pb')) for t in tags]
    known = [(n, s) for n, s in pythia if s is not None]
    record = {'scheme': 'MLM', 'settings': merging['settings'], 'ickkw': merging['ickkw'], 'xqcut': merging['xqcut'],
              'qcut': merging['qcut'], 'njetmax': merging['njetmax'], 'base_partons': merging['base_partons'],
              'multiplicity_census': {str(k - merging['base_partons']): v for k, v in sorted(scan['multiplicity'].items())},
              'pre_veto_sigma_pb': {'total': sigma_pre, 'by_extra_partons': pre},
              'accounting': {'attempted': attempted, 'accepted': accepted, 'vetoed': attempted - accepted,
                             'matched_fraction': fraction,
                             'matched_fraction_uncertainty': math.sqrt(fraction * (1 - fraction) / attempted),
                             'accepted_by_me_partons': accepted_by_me},
              'matched_sigma_pb': sigma_pre * fraction,
              'matched_sigma_rule': 'sigma before matching (LHE init) x accepted / attempted, pooled over all chunks',
              'pythia_sigma_gen_pb': {'per_chunk': [s for _, s in pythia],
                                      'exposure_weighted': (math.fsum(n * s for n, s in known) / sum(n for n, _ in known))
                                      if known else None},
              'djr': _djr_histograms([out / 'chunks' / t / 'djr.tsv' for t in tags if (out / 'chunks' / t / 'djr.tsv').is_file()])}
    return record, sigma_pre * fraction


def run(task, base, destination):
    compiled = compile_task(task, base)
    base = Path(base)
    out = Path(destination) / OUTPUT
    out.mkdir(parents=True)
    from ravel.validation.lhe_check import check_science
    lhe_check = check_science(compiled['lhe'],
        param_card=compiled['model'].get('slha', {}).get('path') if isinstance(compiled['model'].get('slha'), dict) else None,
        allowed_bsm_pdgs=task['model'].get('bsm_pdgs'), output=out / 'science.lhe_check.json')
    from ravel.physics.native_normalization import read_lhe
    lhe_record = read_lhe(compiled['lhe'])
    scan = scan_events(compiled['lhe'])
    banner_n = compiled['header']['run_card'].get('nevents')
    if banner_n is not None and int(float(banner_n)) != scan['events']:
        raise ValueError(f'the LHE banner states {banner_n} events but the file holds {scan["events"]}; it is incomplete')
    n_events = min(scan['events'], task['events'].get('max_events', scan['events']))
    if compiled['merging'] is not None:
        magnitudes = {abs(w) for w in scan['weights']}
        if len(magnitudes) != 1 or any(w <= 0 for w in scan['weights']):
            raise ValueError('MLM accounting by event counts needs unweighted LHE events with one positive weight')
        observed = max(scan['multiplicity']) - compiled['merging']['base_partons']
        if observed != compiled['merging']['njetmax']:
            raise ValueError(f'JetMatching:nJetMax is {compiled["merging"]["njetmax"]} but the LHE holds up to '
                             f'{observed} extra partons')
    preflight = _disk_preflight(task, compiled, out, n_events)
    cards = _derive_cards(compiled, out)
    journal = out / 'journal.jsonl'
    merged = compiled['merging'] is not None
    retain = task.get('retain_hepmc', False)
    jobs, tags_by_variant = [], {}
    for v_index, variant in enumerate(compiled['variants']):
        for chunk in _chunks(n_events, task.get('chunks', 1)):
            tag = f'{variant["name"]}-{chunk["index"]:04d}'
            seed = task['shower']['seed'] + v_index * len(_chunks(n_events, task.get('chunks', 1))) + chunk['index']
            plan_path = out / 'plans' / f'{tag}.json'
            plan = {'schema_version': 1, 'tag': tag, 'variant': variant['name'], 'lhe': str(compiled['lhe']),
                    'skip': chunk['skip'], 'events': chunk['events'], 'seed': seed, 'commands': variant['commands'],
                    'merged': merged, 'retain_hepmc': retain,
                    'shower': compiled['tools']['shower_merged' if merged else 'shower']['path'],
                    'delphes': compiled['tools']['delphes']['path'],
                    'cards': [{'name': c['name'], 'path': c['path'], 'required_branches': c['required_branches']} for c in cards],
                    'census': {'invisible': compiled['census']['invisible'],
                               'visible_stable': compiled['census']['visible_stable'],
                               'bsm_pdgs': task['model'].get('bsm_pdgs', []),
                               'events': task['shower'].get('census_events', 1000)},
                    'dispatch_record': str(out / 'dispatch' / f'{tag}.json')}
            _write_new(plan_path, plan)
            _write_new(out / 'dispatch' / f'{tag}.json', {'tag': tag, 'chunk_plan_sha256': sha256(plan_path)})
            jobs.append({'tag': tag, 'spec': _backend_spec(task, compiled, plan_path.resolve(), tag, cards, merged, retain, out)})
            tags_by_variant.setdefault(variant['name'], []).append(tag)
    results = _run_jobs(jobs, out, journal, task.get('parallel', 1))
    failures = {t: r for t, r in results.items() if r['state'] != 'succeeded'}
    receipts = {}
    for tag, row in results.items():
        if row['state'] == 'succeeded':
            receipt = json.loads((out / 'chunks' / tag / 'chunk-receipt.json').read_text())
            verdict = _verify_chunk(out, tag, cards, receipt)
            if receipt['status'] != 'passed' or verdict['verdict'] != 'accepted':
                failures[tag] = {'state': 'refused', 'detail': receipt.get('failure') or verdict['failure_class']}
            receipts[tag] = receipt
    if failures:
        summary = {t: {k: v for k, v in r.items() if k in ('state', 'exit_code', 'detail', 'log_tail')} for t, r in failures.items()}
        _write_new(out / 'failures.json', summary)
        return {'status': 'failed', 'kind': 'event-production', 'status_scope': SCOPE, 'physics_validated': False,
                'output_directory': OUTPUT, 'failures': summary,
                'limitations': ['No production receipt is written while any chunk is refused.']}
    samples = {}
    for variant in compiled['variants']:
        tags = tags_by_variant[variant['name']]
        matching, matched_sigma = _matching(compiled, scan, receipts, tags, out) if merged else ({'scheme': 'none'}, None)
        outputs = {c['name']: _merge_card(task, compiled, out, variant['name'], c, tags, receipts) for c in cards}
        accepted = sum(receipts[t]['events']['accepted'] for t in tags)
        for name, merged_card in outputs.items():
            if merged_card['entries'] != accepted:
                raise ValueError(f'card {name}: {merged_card["entries"]} detector entries for {accepted} showered events')
        sigma = dict(compiled['sigma'])
        if merged and task['normalization']['sigma'] == 'lhe-init':
            sigma = {**sigma, 'value_pb': matched_sigma, 'pre_matching_pb': compiled['sigma']['value_pb'],
                     'source': compiled['sigma']['source'] + ' x matched fraction (accepted / attempted)'}
            sigma.pop('uncertainty_pb', None)
        first = next(iter(outputs.values()))
        samples[variant['name']] = {
            'shower_commands': variant['commands'],
            'events': {'lhe_events': scan['events'], 'used_lhe_events': n_events,
                       'attempted': sum(receipts[t]['events']['attempted'] for t in tags), 'accepted': accepted,
                       'detector_entries': {n: o['entries'] for n, o in outputs.items()},
                       'chunks': [{'tag': t, 'seed': receipts[t]['seed'], **receipts[t]['events']} for t in tags]},
            'sigma': sigma,
            'weights': {'branch': 'Event.Weight', 'sum': first['sum_weights'], 'sum2': first['sum_weights2'], 'n': first['entries'],
                        'origin': f'Pythia 8 event weight from the LHE event weight (IDWTUP = {compiled["header"]["idwtup"]}), '
                                  'written to HepMC and copied by Delphes',
                        'normalization': 'yield = sigma_pb x luminosity_pb^-1 x (sum of selected Event.Weight) / '
                                         '(sum of Event.Weight over every event in these files)'},
            'merging': matching,
            'outputs': outputs,
            'bsm_census': {t: receipts[t]['bsm_census'] for t in tags},
            'hepmc': {t: f'chunks/{t}/events.hepmc.gz' for t in tags} if retain else None}
    nominal = samples.pop('nominal')
    versions = {receipts[t]['pythia_version'] for t in receipts if receipts[t].get('pythia_version')}
    shower_tool = compiled['tools']['shower_merged' if merged else 'shower']
    receipt = {
        'schema_version': 1, 'kind': 'ravel-production-receipt',
        'lhe_check': {'path': 'science.lhe_check.json', 'sha256': sha256(out / 'science.lhe_check.json'), 'verdict': lhe_check['verdict']},
        'generator': compiled['header']['generator'] or {'name': 'not stated in the LHE file', 'version': None},
        'shower': {'name': 'Pythia 8', 'program': shower_tool['path'], 'program_sha256': shower_tool['sha256'],
                   'version': sorted(versions)[0] if len(versions) == 1 else shower_tool['version'],
                   'version_source': ('Pythia banner in the shower log' if len(versions) == 1
                                      else shower_tool['version_source']),
                   'versions_in_logs': sorted(versions)},
        'detector': {'name': 'Delphes', 'program': compiled['tools']['delphes']['path'],
                     'program_sha256': compiled['tools']['delphes']['sha256'],
                     'version': compiled['tools']['delphes']['version'],
                     'version_source': compiled['tools']['delphes']['version_source']},
        'cards': {'lhe': _pin(compiled['lhe']), 'delphes': {c['name']: {'path': c['path'], 'sha256': c['sha256'],
                                                                        'source': c['source'], 'derived': c['derived'],
                                                                        'invisible_gate': c['gate']} for c in cards},
                  'slha': compiled['model'].get('slha')},
        'process': compiled['process'], 'model': compiled['model'],
        'invisible_census': compiled['census'],
        'beams': {'pdg': compiled['header']['beam_pdg'], 'energy_gev': compiled['header']['beam_energy_gev']},
        'lhe': {'cross_section_pb': lhe_record['cross_section_pb'], 'events': scan['events'], 'idwtup': compiled['header']['idwtup'],
                'run_card': {k: compiled['header']['run_card'][k] for k in sorted(compiled['header']['run_card'])
                             if k in ('ickkw', 'xqcut', 'lhaid', 'pdlabel', 'dynamical_scale_choice', 'ebeam1', 'ebeam2',
                                      'lpp1', 'lpp2', 'nevents', 'iseed')}},
        **nominal,
        'variants': samples,
        'event_weight_convention': nominal['weights']['normalization'],
        'merging_scheme': nominal['merging']['scheme'],
        'disk_preflight': preflight,
        'deviations': [f'detector card {c["name"]} replaced by a managed derived card: '
                       + '; '.join(e['reason'] for e in c['derived']['edits']) for c in cards if c['derived']],
        'analysis_normalization': {'mode': 'cross-section',
                                   'cross_section_pb': ({'production_receipt': RECEIPT} if 'normalization_ledger' in nominal['sigma']
                                                        else {'production_receipt': RECEIPT, 'pointer': '/sigma/value_pb'}),
                                   'cross_section_source': nominal['sigma']['source'],
                                   'sum_of_weights': 'all-input-events'},
        'journal': 'journal.jsonl'}
    if task['events'].get('generation_receipt'):
        receipt['generation_receipt'] = _pin(_regular(base, task['events']['generation_receipt'], 'events.generation_receipt'))
    if compiled['generation'] is not None:
        receipt['generation'] = {k: v for k, v in compiled['generation'].items() if k != 'index'}
        if compiled['generation'].get('transform'):
            receipt['deviations'] += compiled['generation']['transform']['deviations']
    if retain:
        receipt['event_metadata'] = _event_metadata(out, receipt, nominal)
    path = _write_new(out / RECEIPT, receipt)
    from ravel.physics.yield_hub import delivery_checks
    ledger = nominal['sigma'].get('normalization_ledger')
    if ledger is not None:
        ledger = {k: v for k, v in ledger.items() if k != 'applied_sigma_pb'}
    delivery_findings = delivery_checks(out, path=RECEIPT, ledger=ledger)
    from ravel.validation.output_postconditions import check
    checks = [check({'name': 'production receipt', 'kind': 'json', 'path': str(path),
                     'required': ['/sigma/value_pb', '/events/accepted', '/generator', '/shower', '/detector', '/cards',
                                  '/process', '/model', '/weights/branch', '/merging/scheme']})]
    return {'status': 'passed' if all(c['passed'] for c in checks) else 'failed', 'kind': 'event-production',
            'status_scope': SCOPE, 'physics_validated': False, 'output_directory': OUTPUT,
            'receipt': {'path': f'{OUTPUT}/{RECEIPT}', 'sha256': sha256(path)},
            'outputs': {name: [f['path'] for f in o['files']] if o['scheme'] == 'file list' else [o['file']['path']]
                        for name, o in nominal['outputs'].items()},
            'events': nominal['events'], 'sigma_pb': nominal['sigma']['value_pb'], 'sigma_source': nominal['sigma']['source'],
            'merging': nominal['merging']['scheme'], 'variants': sorted(samples),
            'contracts': checks,
            'check_results': delivery_findings,
            'limitations': [
                'Shower and detector settings are the declared ones; detector fidelity is not established here.',
                'The cross section carries the declared or generator convention recorded in the receipt.',
                'Matched cross sections are estimated from accepted over attempted events with binomial uncertainty.']}


def _event_metadata(out, receipt, nominal):
    rows = {}
    for tag, path in (nominal['hepmc'] or {}).items():
        metadata = {'schema_version': 1, 'event_level': 'hadron', 'beam_pdg': receipt['beams']['pdg'],
                    'beam_energy_gev': receipt['beams']['energy_gev'], 'weight_names': ['Weight'],
                    'events': next(c['accepted'] for c in nominal['events']['chunks'] if c['tag'] == tag),
                    'groups': 'independent', 'cross_section_pb': nominal['sigma']['value_pb'],
                    'source': f'RAVEL event production chunk {tag}; cross section: {nominal["sigma"]["source"]}'}
        target = out / 'chunks' / tag / 'event-metadata.json'
        _write_new(target, metadata)
        rows[tag] = {'events': path, 'metadata': f'chunks/{tag}/event-metadata.json'}
    return rows


# ---------------------------------------------------------------- figures and tables
def write_figures(result, out):
    tables = []
    if result.get('receipt'):
        tables.append({'stem': f'{OUTPUT}/production-receipt', 'files': [result['receipt']['path']],
                       'normalization': 'Cross section with its source and convention; per-event weight convention'})
    return {'status': 'not_applicable', 'figures': [], 'tables': tables,
            'scope': 'Detector-level event production; no physics distribution is drawn by this stage'}


# ---------------------------------------------------------------- command line
def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel event-production', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check', help='check a production task, its LHE header, cards and tools without running anything')
    check.add_argument('task', help='JSON file with the event-production task')
    header = sub.add_parser('header', help='print what the LHE header states (generator, process, run card, init block)')
    header.add_argument('lhe')
    receipt = sub.add_parser('receipt', help='check a production receipt and its Delphes files against their contracts')
    receipt.add_argument('receipt')
    chunk = sub.add_parser('chunk', help=argparse.SUPPRESS)
    chunk.add_argument('--plan', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'chunk':
            return run_chunk(args.plan)
        if args.command == 'header':
            print(json.dumps(read_header(args.lhe), indent=2))
            return 0
        if args.command == 'check':
            path = Path(args.task)
            task = json.loads(path.read_text())
            compiled = compile_task(task, path.parent)
            print(json.dumps({'lhe': str(compiled['lhe']), 'generator': compiled['header']['generator'],
                              'process': compiled['process'], 'model': compiled['model'],
                              'merging': compiled['merging'], 'sigma': compiled['sigma'],
                              'invisible_census': compiled['census'], 'tools': compiled['tools'],
                              'cards': [{k: c[k] for k in ('name', 'path', 'sha256', 'gate')} for c in compiled['cards']],
                              'execution_seconds': execution_seconds(task, path.parent)}, indent=2, default=str))
            return 0
        from ravel.validation.output_postconditions import check as check_contract
        path = Path(args.receipt)
        document = json.loads(path.read_text())
        results = []
        for name, merged in document['outputs'].items():
            files = [f['path'] for f in merged['files']] if merged['scheme'] == 'file list' else [merged['file']['path']]
            for f in files:
                results.append(check_contract({'name': name, 'kind': 'delphes-root', 'path': f, 'min_events': 1}))
        print(json.dumps(results, indent=2))
        return 0 if all(r['passed'] for r in results) else 1
    except (OSError, ValueError, KeyError) as exc:
        print(f'event-production: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
