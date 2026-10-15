"""Copy accepted artifacts into a supplied layout and retain portable provenance."""
import argparse
import ast
import json
import math
from pathlib import Path
import shutil
import sys

from .submission_export import file_sha256, _results, _run_records, code_version

INDEX = '.ravel-delivery.json'
KEYS = {'analysis_code', 'selected_events', 'cards', 'report', 'templates', 'copy_limit_mb'}
BEGIN = '<!-- ravel-delivery provenance -->'
END = '<!-- end ravel-delivery provenance -->'


def _relative(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('layout paths must be nonempty relative paths')
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or path == Path('.'):
        raise ValueError(f'layout path must be relative and cannot escape: {value}')
    if '\\' in value:
        raise ValueError('layout paths use forward slashes')
    return path


def validate_layout(layout):
    if type(layout) is not dict or set(layout) - KEYS:
        raise ValueError('unknown layout keys or invalid layout object')
    for key in ('analysis_code', 'selected_events', 'cards', 'report'):
        if key in layout:
            _relative(layout[key])
            if any(c in layout[key] for c in '*?['):
                raise ValueError('only templates may contain glob patterns')
    templates = layout.get('templates', [])
    if type(templates) is not list:
        raise ValueError('templates must be a list of relative glob patterns')
    for value in templates:
        _relative(value)
    limit = layout.get('copy_limit_mb', 500)
    if type(limit) not in (float, int) or not math.isfinite(limit) or limit < 0:
        raise ValueError('copy_limit_mb must be finite and nonnegative')
    return layout


def _safe(root, relative):
    target = root / _relative(relative)
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError(f'symlink refused: {target}')
    if any(p.exists() and not p.is_dir() for p in target.parents):
        raise ValueError(f'destination parent must be a directory: {target}')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'path escapes workspace: {relative}')
    return target


def _regular(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError(f'regular file required, symlink refused: {path}')
    return path


def literal_scan(paths, table_lengths=()):
    """Report numeric Python lists/tuples and C-like brace arrays; never edit code.

    A matching length is a review finding, not proof that the array is a fallback.
    """
    import re
    lengths = set(table_lengths)
    findings = []
    for value in paths:
        path = _regular(value)
        text = path.read_text()
        if path.suffix == '.py':
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) in lengths:
                    def numeric(element):
                        if isinstance(element, ast.UnaryOp) and isinstance(element.op, (ast.USub, ast.UAdd)):
                            element = element.operand
                        return isinstance(element, ast.Constant) and type(element.value) in (int, float)
                    if node.elts and all(numeric(e) for e in node.elts):
                        findings.append({'path': str(path), 'line': node.lineno, 'length': len(node.elts)})
        else:
            # Remove comments before scanning literal initializer braces.
            clean = re.sub(r'/\*.*?\*/|//[^\n]*', lambda m: '\n' * m.group().count('\n'), text, flags=re.S)
            number = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[fFlL]?'
            for match in re.finditer(r'\{\s*(' + number + r'(?:\s*,\s*' + number + r')*)\s*,?\s*\}', clean):
                count = len(match.group(1).split(','))
                if count in lengths:
                    findings.append({'path': str(path), 'line': clean.count('\n', 0, match.start()) + 1, 'length': count})
    return findings


class _AcceptedResults:
    """Adapt the shared accepted-result gate without exporting its category layout."""
    @staticmethod
    def resolve(value):
        return Path(value)

    @staticmethod
    def copy(source, relative, category):
        return None


def _review(rd):
    from . import physics_review as pr, task_completion as tc
    status = pr.status(rd)
    if status.get('state') != 'accepted':
        raise ValueError('current accepted review required')
    inputs = tc._Inputs(rd)
    try:
        _, cycle = tc._accepted_review(str(rd), status['claim_scope'], inputs)
        inputs.finish()
    finally:
        inputs.close()
    reg, events = pr._read(rd)
    view = pr._view(reg, events)
    reviews = [{k: r[k] for k in ('sequence', 'role', 'actor_id', 'verdict', 'claim_scope') if k in r}
               | {'actor_kind': r.get('actor_kind', 'unrecorded')}
               for r in view['reviews']]
    return status['claim_scope'], cycle, reviews


def _physics(records):
    """Keep recorded physics fields verbatim, including explicit missing values."""
    rows = []
    for path in records:
        if path.suffix != '.json':
            continue
        try:
            doc = json.loads(path.read_text())
        except (ValueError, UnicodeError):
            continue
        if type(doc) is not dict or doc.get('kind') not in ('ravel-production-receipt', 'generation-receipt'):
            continue
        if doc['kind'] == 'generation-receipt':
            for point in doc.get('points', []):
                rows.append({'receipt': path.name, 'sha256': file_sha256(path), 'point': point['id'],
                             'generator': doc.get('generator'), 'shower': doc.get('shower'), 'detector': None,
                             'cards': point.get('cards'), 'events': point.get('events'),
                             'cross_section': point.get('cross_section'), 'pdf': doc.get('pdf'),
                             'source_table': point.get('cross_section', {}).get('source'),
                             'luminosity': None, 'ledger_recomputed_total': None})
            continue
        sigma = doc.get('sigma', doc.get('cross_section', {}))
        ledger = doc.get('normalization_ledger', sigma.get('normalization_ledger', {}))
        total = None
        if ledger.get('schema_version') == 1:
            from ravel.physics import normalization_ledger as nl
            nl.validate(ledger)
            total = nl._integrated_total(ledger, nl.expected_yields(ledger))
        sigma = {k: v for k, v in sigma.items() if k != 'normalization_ledger'}
        rows.append({'receipt': path.name, 'sha256': file_sha256(path),
                     'generator': doc.get('generator', doc.get('generation')),
                     'shower': doc.get('shower'), 'detector': doc.get('detector'),
                     'cards': doc.get('cards'), 'events': doc.get('events'),
                     'cross_section': sigma,
                     'pdf': ledger.get('sigma', {}).get('pdf', sigma.get('pdf', doc.get('lhe', {}).get('run_card', {}).get('lhaid'))),
                     'source_table': ledger.get('sigma', {}).get('source', sigma.get('source')),
                     'luminosity': ledger.get('luminosity', doc.get('luminosity_ifb')),
                     'ledger_recomputed_total': total})
    return rows


def _block(index):
    summary = {k: index[k] for k in ('run', 'code_version', 'reviews', 'physics', 'literal_findings')}
    summary['files'] = [{k: row[k] for k in ('path', 'sha256', 'category', 'size', 'reference', 'fill') if k in row}
                        for row in index['files']]
    block = '\n' + BEGIN + '\n```json\n' + json.dumps(summary, ensure_ascii=True, separators=(',', ':')) + '\n```\n' + END + '\n'
    if len(block.encode()) > 6 * 1024:
        raise ValueError('provenance block exceeds 6 kB; narrow the supplied layout')
    return block


def deliver(rundir, layout, into):
    """Preflight all sources and destinations before writing requester files."""
    validate_layout(layout)
    rd, ws = Path(rundir).absolute(), Path(into).absolute()
    _safe(ws, INDEX)
    for key in ('analysis_code', 'selected_events', 'cards', 'report'):
        if key in layout:
            _safe(ws, layout[key])
    if rd.resolve().is_relative_to(ws.resolve()) or ws.resolve().is_relative_to(rd.resolve()):
        raise ValueError('workspace and run must not overlap')
    if (ws / INDEX).exists():
        raise ValueError('workspace already has a delivery index')
    scope, cycle, reviews = _review(rd)
    records = set(_run_records(rd))
    captured = set()
    for pin in cycle['snapshots']:
        source = Path(pin['path'])
        source = source if source.is_absolute() else rd / source
        source = _regular(source)
        if file_sha256(source) != pin['sha256'] or source.stat().st_size != pin['size']:
            raise ValueError(f'accepted artifact changed: {source}')
        captured.add(source)
    # Only current reviewed artifacts are eligible for ordinary category copying.
    records = sorted(records & captured | {p for p in captured if p.suffix == '.json'})
    planned, lengths = [], []
    def add(source, relative, category, **extra):
        source = _regular(source)
        row = {'path': _relative(relative).as_posix(), 'category': category,
               'sha256': file_sha256(source), 'size': source.stat().st_size, **extra}
        planned.append((source, row))
    for source in sorted(captured):
        suffix = source.suffix.lower()
        recipe = False
        if suffix == '.json':
            try:
                document = json.loads(source.read_text())
                recipe = isinstance(document, dict) and document.get('kind') == 'columnar-analysis-recipe'
            except (ValueError, UnicodeError):
                pass
        category = ('analysis_code' if suffix in ('.py', '.cpp', '.cxx', '.cc', '.h', '.hpp') else
                    'cards' if suffix in ('.dat', '.tcl', '.card') else
                    'selected_events' if suffix in ('.root', '.parquet', '.npz', '.arrow') else None)
        if recipe:
            category = 'analysis_code'
        if category in layout:
            relative = (Path(layout[category]) / source.name).as_posix()
            reference = category == 'selected_events' and source.stat().st_size > layout.get('copy_limit_mb', 500) * 1024 ** 2
            add(source, relative, category, **({'reference': str(source)} if reference else {}))
    seen_templates = set()
    for pattern in layout.get('templates', []):
        matched = sorted(rd.glob(pattern))
        if not matched:
            raise ValueError(f'template pattern matches no files: {pattern}')
        for source in matched:
            if source in seen_templates:
                continue
            seen_templates.add(source)
            provenance = _regular(source.with_name(source.name + '.provenance.json'))
            fill = json.loads(provenance.read_text())
            if fill.get('kind') != 'filled-result-template':
                raise ValueError(f'filled template provenance required: {source}')
            expected, observed = fill['output']['sha256'], file_sha256(_regular(source))
            if expected != observed:
                raise ValueError(f'hand-edited {source}: expected {expected}, observed {observed}')
            result = Path(fill['result']['path'])
            result = result if result.is_absolute() else rd / result
            acceptance = _results(_AcceptedResults(), {'results': [str(result)], 'claim_scope': scope}, rd)
            if (fill['acceptance']['claim_scope'] != scope or
                    fill['acceptance']['review_sequence'] != acceptance['review_sequence'] or
                    fill['result']['sha256'] != file_sha256(result)):
                raise ValueError('fill provenance differs from current accepted result')
            relative = source.relative_to(rd).as_posix()
            add(source, relative, 'templates', fill={'provenance': relative + '.provenance.json',
                'output_sha256': expected, 'result_sha256': fill['result']['sha256'],
                'review_sequence': acceptance['review_sequence']})
            add(provenance, relative + '.provenance.json', 'fill_provenance')
            add(result, relative + '.result.json', 'accepted_result')
            lengths.append(len(fill['bins']))
    # Full receipt bytes travel with the workspace, independent of the source run.
    physics = _physics(records)
    for record in records:
        if any(p['sha256'] == file_sha256(record) for p in physics):
            add(record, INDEX + '.evidence/' + record.name, 'receipt')
    paths = [row['path'] for _, row in planned if 'reference' not in row]
    if (len(paths) != len(set(paths)) or INDEX in paths or layout.get('report') in paths
            or layout.get('report') == INDEX):
        raise ValueError('delivery paths collide')
    for _, row in planned:
        target = _safe(ws, row['path'])
        if 'reference' not in row and target.exists():
            raise ValueError(f'delivery target already exists: {target}')
    findings = literal_scan([source for source, row in planned if row['category'] == 'analysis_code'], lengths)
    # Findings use workspace-relative names, so no source run is needed to read them.
    for finding in findings:
        finding['path'] = next(row['path'] for source, row in planned if str(source) == finding['path'])
    index = {'schema_version': 1, 'kind': 'requester-delivery', 'run': rd.name,
             'code_version': code_version(), 'reviews': reviews, 'physics': physics,
             'literal_findings': findings, 'files': [row for _, row in planned], 'report': layout.get('report')}
    block = _block(index)
    # Serialize before copying, so malformed recorded values cannot leave a partial delivery.
    json.dumps(index, allow_nan=False)
    report = _safe(ws, layout['report']) if 'report' in layout else None
    report_before = report.read_bytes() if report is not None and report.exists() else b''
    if BEGIN.encode() in report_before:
        raise ValueError('report already contains a provenance block')
    # Refuse source drift before committing any bytes to the workspace.
    for source, row in planned:
        if file_sha256(source) != row['sha256']:
            raise ValueError(f'source changed during delivery: {source}')
    _, current_cycle, _ = _review(rd)
    if current_cycle != cycle:
        raise ValueError('accepted review changed during delivery')
    ws.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for source, row in planned:
            if 'reference' in row:
                continue
            target = _safe(ws, row['path']); target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output, source.open('rb') as stream:
                created.append(target); shutil.copyfileobj(stream, output)
            if file_sha256(target) != row['sha256']:
                raise ValueError(f'source changed during copy: {source}')
        if report is not None:
            report.parent.mkdir(parents=True, exist_ok=True)
            if (report.read_bytes() if report.exists() else b'') != report_before:
                raise ValueError('report changed during delivery')
            report.write_bytes(report_before + block.encode())
            index['report_sha256'] = file_sha256(report)
        with (ws / INDEX).open('x') as output:
            json.dump(index, output, indent=2, allow_nan=False); output.write('\n')
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        if report is not None and report.exists() and report.read_bytes() == report_before + block.encode():
            if report_before:
                report.write_bytes(report_before)
            else:
                report.unlink()
        (ws / INDEX).unlink(missing_ok=True)
        raise
    return index


def verify(into):
    ws = Path(into).absolute()
    index = json.loads(_regular(_safe(ws, INDEX)).read_text())
    if index.get('kind') != 'requester-delivery' or index.get('schema_version') != 1:
        raise ValueError('requester delivery index required')
    for row in index['files']:
        if 'reference' in row:
            # References intentionally retain external custody; verify bytes when present.
            path = _regular(row['reference'])
        else:
            path = _safe(ws, row['path'])
            if not path.is_file():
                raise ValueError(f'missing delivered file: {row["path"]}')
        observed = file_sha256(path)
        expected = row.get('fill', {}).get('output_sha256', row['sha256'])
        if observed != expected or observed != row['sha256']:
            label = 'hand-edited' if 'fill' in row else 'changed'
            raise ValueError(f'{label} {row["path"]}: expected {expected}, observed {observed}')
        if path.stat().st_size != row['size']:
            raise ValueError(f'changed size: {row["path"]}')
        if 'fill' in row:
            lineage = row['fill']
            provenance = json.loads(_regular(_safe(ws, lineage['provenance'])).read_text())
            if (provenance['output']['sha256'] != expected or
                    provenance['result']['sha256'] != lineage['result_sha256'] or
                    provenance['acceptance']['review_sequence'] != lineage['review_sequence'] or
                    file_sha256(_regular(_safe(ws, row['path'] + '.result.json'))) != lineage['result_sha256']):
                raise ValueError(f'fill provenance differs from index: {row["path"]}')
    if index.get('report'):
        path = _safe(ws, index['report'])
        if not path.is_file():
            raise ValueError(f'missing delivered report: {index["report"]}')
        if file_sha256(path) != index['report_sha256']:
            raise ValueError(f'changed report: {index["report"]}')
    return index


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    checking = bool(argv and argv[0] == 'verify')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--into', required=True)
    if not checking:
        parser.add_argument('--rundir', required=True)
        parser.add_argument('--layout', required=True)
    args = parser.parse_args(argv[1:] if checking else argv)
    try:
        result = verify(args.into) if checking else deliver(args.rundir, json.loads(Path(args.layout).read_text()), args.into)
    except (ValueError, OSError, KeyError, SyntaxError) as exc:
        print(f'deliver-workspace: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'verified': checking, 'run': result['run'], 'files': len(result['files']),
                      'literal_findings': result['literal_findings']}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
