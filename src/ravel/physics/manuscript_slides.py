"""Supplied slide layouts and exact result text, compiled only by ordinary science.

The registered slide operation specializes the existing manuscript-build mode.
Source preparation never launches a compiler; builds use the same admission and
native resource supervisor as the authenticated note.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from ravel.workflow import candidate_experiments as ce, report_integrity as custody, state_io
from ravel.physics import manuscript_assets

KIND = 'manuscript-slides-build'


def _pin(path):
    path = Path(path).absolute(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _text(value):
    custody._text(value)
    from ravel.workflow.manuscript_production import _tex
    return _tex(value)


def _pointer(value, pointer):
    if type(pointer) is not str or not pointer.startswith('/'):
        raise ValueError('explicit result JSON pointer required')
    try:
        for component in pointer[1:].split('/'):
            component = component.replace('~1', '/').replace('~0', '~')
            value = value[int(component)] if type(value) is list else value[component]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError('missing supplied result pointer') from error
    if type(value) not in (str, int, float) or type(value) is bool:
        raise ValueError('rendered scalar result required')
    return value if type(value) is str else json.dumps(value, allow_nan=False)


def _render(binding, spec, minutes, base):
    from ravel.physics import manuscript_build as mb
    if type(minutes) is not int or minutes <= 0:
        raise ValueError('positive supplied duration required')
    ce.keys(spec, ['schema_version', 'kind', 'title', 'quantities', 'slides', 'audit', 'theme'])
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1 or spec['kind'] != 'supplied-slide-content':
        raise ValueError('supplied-slide-content/v1 required')
    verified = mb.verified_result(binding, base_dir=base)
    package = verified['package']; source_base = Path(package['source_base'])
    consumed = {}
    note = custody._raw(package['manuscript'], source_base, consumed).decode()
    latex = custody._raw(package['latex'], source_base, consumed).decode()
    input_paths = {str(Path(p).absolute()) for p in verified['input_paths']}
    quantities = {}; figures = {}; copies = []
    for i, pin in enumerate(package['figures']):
        path = custody._artifact_path(pin, source_base)
        raw = custody._raw(pin, source_base, consumed)
        extension = path.suffix.lower()
        if extension not in {'.pdf', '.png', '.jpg', '.jpeg'}:
            conversion = next((r for r in verified['result']['figure_conversions'] if r['source'] == pin), None)
            if conversion is None: raise ValueError('actual note figure preview required')
            raw = custody._raw(conversion['pdf'], base, consumed); extension = '.pdf'
        name = 'figure-' + str(i + 1) + extension
        figures[pin['path']] = name; copies.append((Path(name), raw))
    for row in custody._rows(spec['quantities'], 'supplied exact slide quantities'):
        ce.keys(row, ['id', 'label', 'artifact', 'pointer']); ce.identity(row['id']); _text(row['label'])
        if row['id'] in quantities: raise ValueError('duplicate supplied quantity')
        path = custody._artifact_path(row['artifact'], base)
        if str(path.absolute()) not in input_paths:
            raise ValueError('slide quantity is outside authenticated note inputs')
        rendered = _pointer(custody._json(custody._raw(row['artifact'], base, consumed)), row['pointer'])
        literal = r'(?<![\w.+-])' + re.escape(rendered) + r'(?![\w.+-])'
        native_literal = r'(?<![\w.+-])' + re.escape(_text(rendered)) + r'(?![\w.+-])'
        if not rendered or (re.search(literal, note) is None and re.search(native_literal, latex) is None):
            raise ValueError('slide number is absent from authenticated note')
        quantities[row['id']] = {'label': row['label'], 'rendered': rendered, 'artifact': row['artifact'], 'pointer': row['pointer']}
    sections = {}
    # Authenticated headings come from the formatting contract, not guessed roles.
    if spec['slides'] and any(row.get('sections') for row in spec['slides']):
        from ravel.workflow import manuscript_format as mf
        formatting = mf.load(package['formatting_contract'], source_base, consumed)
        headings = {row['heading']: row['id'] for row in mf.section_layout(formatting)}
        markers = list(re.finditer(r'^# (.+)\n', note, re.M))
        for i, marker in enumerate(markers):
            identity = headings.get(marker.group(1))
            if identity is not None:
                ending = markers[i+1].start() if i+1 < len(markers) else len(note)
                sections.setdefault(identity, []).append(note[marker.end():ending].strip())
    preamble = r'\documentclass{beamer}\usepackage{graphicx}'
    theme = spec['theme']
    if theme is not None:
        ce.keys(theme, ['name', 'bundle'])
        if type(theme['name']) is not str or re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', theme['name']) is None:
            raise ValueError('literal supplied beamer theme name required')
        assets = manuscript_assets.pins([theme['bundle']], base, verify=True, consumed=consumed)
        if not any(Path(p['path']).name == 'beamertheme' + theme['name'] + '.sty' for p in assets):
            raise ValueError('selected supplied theme file missing')
        copies += [(relative, custody._raw(pin, base, consumed)) for pin, relative in manuscript_assets.placements([theme['bundle']], base)]
        preamble += r'\usetheme{' + theme['name'] + '}'
    lines = [preamble, r'\title{' + _text(spec['title']) + '}', r'\begin{document}',
        r'\begin{frame}\titlepage\par ' + str(minutes) + r' minutes\end{frame}']
    used_quantities = set(); used_figures = set()
    for row in custody._rows(spec['slides'], 'complete supplied slide layout', empty=False):
        ce.keys(row, ['title', 'sections', 'quantities', 'figures'])
        for key in ('sections', 'quantities', 'figures'):
            if type(row[key]) is not list or any(type(x) is not str for x in row[key]):
                raise ValueError('supplied slide membership lists required')
        lines.append(r'\begin{frame}{' + _text(row['title']) + '}')
        for identity in row['sections']:
            if identity not in sections: raise ValueError('requested authored section is absent')
            lines.extend(_text(text) + r'\par' for text in sections[identity])
        for identity in row['quantities']:
            if identity not in quantities: raise ValueError('undeclared slide quantity')
            q = quantities[identity]; used_quantities.add(identity)
            lines.append(_text(q['label']) + ': ' + _text(q['rendered']) + r'\par')
        for identity in row['figures']:
            if identity not in figures: raise ValueError('foreign slide figure')
            used_figures.add(identity)
            lines.append(r'\includegraphics[width=\linewidth,height=.65\textheight,keepaspectratio]{' + figures[identity] + '}')
        lines.append(r'\end{frame}')
    if used_quantities != set(quantities): raise ValueError('supplied quantity omitted from slide layout')
    audit = custody._json(custody._raw(spec['audit'], base, consumed))
    totals = audit.get('totals')
    if type(totals) is not dict or not totals: raise ValueError('source-bound prompt log totals required')
    lines.append(r'\begin{frame}{Prompt log totals}')
    for key, value in totals.items():
        if type(value) not in (int, float, str) or type(value) is bool:
            raise ValueError('complete scalar prompt totals required')
        rendered = value if type(value) is str else json.dumps(value, allow_nan=False)
        lines.append(_text(key.replace('_', ' ')) + ': ' + _text(rendered) + r'\par')
    lines.extend([r'\end{frame}', r'\end{document}', ''])
    return {'tex': '\n'.join(lines).encode(), 'copies': copies, 'quantities': quantities,
        'totals': deepcopy(totals), 'consumed': list(consumed.values()), 'verified': verified,
        'template_assets': [] if theme is None else [deepcopy(theme['bundle'])]}


def prepare(binding, spec, out, *, minutes, base_dir):
    product = _render(binding, spec, minutes, base_dir)
    root = Path(out).absolute()
    if root.exists() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('fresh slide output required')
    # Validate collisions before any output is written.
    names = [str(p) for p, _ in product['copies']]
    if len(set(names)) != len(names) or {'slides.tex', 'slides.json', 'slides-build-config.json'} & set(names):
        raise ValueError('duplicate supplied slide asset destination')
    root.mkdir(parents=True)
    (root / 'slides.tex').write_bytes(product['tex'])
    for relative, raw in product['copies']:
        target = root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    runtime_config = product['verified']['config']
    config = {'schema_version': 1, 'kind': KIND, 'note_build': deepcopy(binding), 'content': deepcopy(spec),
        'source_base': str(Path(base_dir).absolute()), 'minutes': minutes,
        'max_seconds': runtime_config['max_seconds'], 'max_ram_mib': runtime_config.get('max_ram_mib', 512),
        'max_output_bytes': runtime_config.get('max_output_bytes', 64 << 20)}
    # Carry the grouped provenance beside the source, including supplied themes.
    config['template_assets'] = product['template_assets']
    state_io.atomic_json(root / 'slides-build-config.json', config)
    report = {'kind': 'manuscript-slide-source', 'compiled': False, 'native_calls': 0, 'minutes': minutes,
        'source': _pin(root / 'slides.tex'), 'quantities': product['quantities'], 'prompt_totals': product['totals'],
        'build_config': _pin(root / 'slides-build-config.json'), 'template_assets': product['template_assets'],
        'message': 'Source written; did not compile. ' + ('pdflatex is missing. ' if shutil.which('pdflatex') is None else '') +
            'Compilation requires an admitted manuscript-slides-build operation through ordinary manuscript-build.'}
    state_io.atomic_json(root / 'slides.json', report)
    return report


def load(task, base):
    ce.keys(task, ['config'])
    path = custody._artifact_path({'path': task['config']}, base)
    config = custody._json(custody._raw(_pin(path), base, {}))
    ce.keys(config, ['schema_version', 'kind', 'note_build', 'content', 'source_base', 'minutes',
        'max_seconds', 'max_ram_mib', 'max_output_bytes', 'template_assets'])
    if config['schema_version'] != 1 or config['kind'] != KIND or not Path(config['source_base']).is_absolute():
        raise ValueError('source-bound slide build config required')
    for key in ('max_seconds', 'max_ram_mib', 'max_output_bytes'):
        if type(config[key]) is not int or config[key] <= 0: raise ValueError('positive supplied slide resource bounds required')
    product = _render(config['note_build'], config['content'], config['minutes'], Path(config['source_base']))
    if config['template_assets'] != product['template_assets']: raise ValueError('supplied theme provenance changed')
    original = product['verified']['config']
    if any(config[k] > original[k] for k in ('max_seconds', 'max_ram_mib', 'max_output_bytes')):
        raise ValueError('slide build exceeds authenticated runtime resource bounds')
    return path, config, product


def inputs(task, base):
    path, config, product = load(task, base)
    source_base = Path(config['source_base'])
    return list(dict.fromkeys([path, *map(Path, product['verified']['input_paths']),
        *[custody._artifact_path(pin, source_base) for pin in [*product['verified']['proof_pins'], *product['consumed']]]]))


def run(task, base, output):
    from ravel.physics import manuscript_build as mb, reinterpret_db
    from ravel.workflow import publication_runtime as pr
    out = Path(output).absolute()
    plan = mb._approved(task, out)  # No source read, write or native call before admission.
    path, config, product = load(task, base)
    if config['max_seconds'] > plan['max_seconds']: raise ValueError('slide build exceeds ordinary admitted wall')
    original = product['verified']['config']; runtime = original['runtime']; runtime_base = Path(original['runtime_base'])
    before = mb._identity(inputs(task, base)); started = time.monotonic()
    available = []
    for tree in runtime['asset_trees']: available.extend(mb._tree(tree, runtime_base))
    if 'beamer.cls' not in {p.name for p in available}: raise ValueError('authenticated beamer runtime assets required')
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)): raise ValueError('fresh supervised slide output required')
    out.mkdir(parents=True); source = out / 'source'; source.mkdir()
    copied = []
    for relative, raw in [(Path('slides.tex'), product['tex']), *product['copies']]:
        target = source / relative
        if target.exists(): raise ValueError('duplicate slide source destination')
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw); copied.append(_pin(target))
    compiler = mb.custody._pin(runtime['compiler'], runtime_base)
    pdfinfo = mb.custody._pin(runtime['pdfinfo'], runtime_base)
    executions = []; recorders = []; observations = []
    def invoke(tool, argv, work):
        remaining = int(config['max_seconds'] - (time.monotonic() - started))
        if remaining <= 0: raise ValueError('complete slide build wall exhausted')
        effective = {**config, 'max_seconds': remaining}
        if original['schema_version'] == 2:
            limits = custody.custody_limits(original.get('custody_limits'))
            snapshot, _ = pr.closure_inputs(runtime, runtime_base, limits, require_qualified=True)
            env = pr.tool_environment(runtime, tool, work)
            receipt = reinterpret_db.execute_native(argv, work, effective, environment=env)
            if receipt.get('command') != argv or receipt.get('effective_environment') != env or receipt.get('environment_mode') != 'explicit':
                raise ValueError('supervised slide invocation environment differs')
            stderr = work / 'native-stderr.log'
            images = pr.observed_images(stderr.read_text(), pid=receipt['pid'], snapshot=snapshot,
                platform_dependencies=snapshot['platform_dependencies'])
            observations.append({'tool': tool, 'stderr': _pin(stderr), 'loaded_images': images})
        else: receipt = reinterpret_db.execute_native(argv, work, effective)
        executions.append(receipt)
        mb._bytes(out, config['max_output_bytes'])
    allowed = {str(p): mb.custody._hash(p) for p in available}
    allowed.update({p['path']: p['sha256'] for p in copied})
    for attempt in (1, 2):
        argv = [str(compiler), '-no-shell-escape', '-interaction=nonstopmode', '-halt-on-error', '-recorder',
            '-output-directory=' + str(source), str(source / 'slides.tex')]
        invoke('compiler', argv, source)
        recorder = source / 'slides.fls'
        if not recorder.is_file(): raise ValueError('actual slide recorder required')
        observed = set()
        for line in recorder.read_text().splitlines():
            if not line.startswith('INPUT '): continue
            leaf = Path(line[6:]); leaf = mb.custody._regular(leaf if leaf.is_absolute() else source / leaf, source)
            if str(leaf) in allowed:
                if mb.custody._hash(leaf) != allowed[str(leaf)]: raise ValueError('consumed slide/runtime source changed')
            elif leaf not in {source / ('slides' + suffix) for suffix in ('.aux', '.nav', '.snm', '.toc', '.out')}:
                raise ValueError('slide compiler consumed undeclared input')
            observed.add(str(leaf))
        if str(source / 'slides.tex') not in observed: raise ValueError('recorder omits exact slide entry')
        log = out / ('pass-' + str(attempt)); log.mkdir()
        for name in ('native-stdout.log', 'native-stderr.log', 'native-process.json', 'native-execution.json', 'slides.fls'):
            shutil.copyfile(source / name, log / name)
        if observations: observations[-1]['stderr'] = _pin(log / 'native-stderr.log')
        recorders.append({'pass': attempt, 'recorder': _pin(log / 'slides.fls'), 'inputs': sorted(observed)})
    pdf = source / 'slides.pdf'
    if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'): raise ValueError('actual compiled slide PDF required')
    info = out / 'pdfinfo'; info.mkdir(); invoke('pdfinfo', [str(pdfinfo), str(pdf)], info)
    pages = re.findall(r'^Pages:\s+([1-9][0-9]*)\s*$', (info / 'native-stdout.log').read_text(), re.M)
    if len(pages) != 1: raise ValueError('actual slide page census required')
    if mb._identity(inputs(task, base)) != before: raise ValueError('slide build inputs changed')
    for pin in copied: custody._raw(pin, source, {})
    result = {'kind': KIND, 'status': 'passed', 'physics_validated': False, 'scientific_acceptance': False,
        'execution_authorized': False, 'compiled': True, 'pdf': _pin(pdf), 'pages': int(pages[0]),
        'source': _pin(source / 'slides.tex'), 'quantities': product['quantities'], 'prompt_totals': product['totals'],
        'template_assets': product['template_assets'], 'executions': executions, 'recorders': recorders,
        'runtime_observations': observations, 'input_identity': before,
        'limitations': ['Rendered supplied presentation only; scientific correctness and visual review remain independent.']}
    state_io.atomic_json(out / 'slides-build.json', result)
    mb._bytes(out, config['max_output_bytes'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel manuscript')
    commands = parser.add_subparsers(dest='command', required=True)
    bundle = commands.add_parser('bundle', help='pin every supplied class file without redistribution rights')
    bundle.add_argument('--folder', type=Path, required=True); bundle.add_argument('--out', type=Path, required=True)
    slides = commands.add_parser('slides', help='prepare source from an authenticated note build')
    slides.add_argument('--from', dest='note_build', type=Path, required=True)
    slides.add_argument('--content', type=Path, required=True)
    slides.add_argument('--minutes', type=int, required=True); slides.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'bundle':
        if args.out.exists(): raise ValueError('new supplied bundle record required')
        value = manuscript_assets.supplied_bundle(args.folder)
        state_io.atomic_json(args.out, value)
    else:
        binding = state_io.read_json(args.note_build); spec = state_io.read_json(args.content)
        value = prepare(binding, spec, args.out, minutes=args.minutes, base_dir=args.note_build.absolute().parent)
    print(json.dumps(value, sort_keys=True, allow_nan=False))
    return 0
