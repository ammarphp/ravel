"""The sink's own inventory of the run directory (D07) and the declared population (C27).

The sink enumerates the bytes actually present in the run directory; it never uses a worker's
artifact list, a file suffix or a delivery keyword to decide what is delivered. The accepted
population is fixed by the approved plan: each mapped deliverable names one declared step
output, adopted by the governed step under ``steps/<step>/<output>`` with a custody record in the
store. A declared output is deliverable only when its latest custody verdict is ``accepted``,
its producing step completed in the same attempt, its bytes still match, and every custody
ancestor is accepted with unchanged bytes. Everything else is listed and excluded: undeclared
files, launch scratch, adopted outputs no deliverable names (extras, reviewed or not) and any
diagnostic artifact copied, renamed or nested into the accepted set (D08, C33).
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import tarfile
import zipfile

from . import common

AREAS = dict((('steps', 'adopted'), ('inputs', 'run-input'), ('logs', 'log'), ('framework', 'controller'),
              ('request.txt', 'run-input'), ('controller-run.json', 'controller')))
MAX_LISTED = 2000
MAX_DEPTH = 64
ARCHIVES = ('.zip', '.tar', '.tgz', '.tar.gz', '.tar.bz2', '.tar.xz')
DIAGNOSTIC_KEYS = (('delivery_label', 'diagnostic'), ('scientific_acceptance', False))


def excluded_top(name):
    return name == common.DELIVERY_DIR or name.startswith(common.DELIVERY_DIR + '.')


class Hashes:
    """Lazy digests of run-directory files (each file is read at most once per delivery)."""

    def __init__(self, root):
        self.root = Path(root)
        self.cache = {}

    def of(self, relative):
        if relative not in self.cache:
            path = self.root / relative
            try:
                info = os.lstat(path)
                self.cache[relative] = common.sha256_file(path) if stat.S_ISREG(info.st_mode) else None
            except OSError:
                self.cache[relative] = None
        return self.cache[relative]


def walk(run_dir):
    """Every entry under ``run_dir`` (the delivery directories excepted), with its area and size."""
    root = Path(run_dir)
    files, counts = {}, {}
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(current)
        rel_dir = here.relative_to(root)
        if rel_dir == Path('.'):
            dirnames[:] = [d for d in dirnames if not excluded_top(d)]
        if len(rel_dir.parts) > MAX_DEPTH:
            dirnames[:] = []
        for name in list(dirnames):
            if (here / name).is_symlink():
                dirnames.remove(name)
                filenames.append(name)
        for name in filenames:
            path = here / name
            relative = (rel_dir / name).as_posix() if rel_dir != Path('.') else name
            try:
                info = os.lstat(path)
            except OSError:
                continue
            kind = ('symlink' if stat.S_ISLNK(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode)
                    else 'special')
            top = relative.split('/', 1)[0]
            area = AREAS.get(top, 'other')
            if area == 'adopted' and '/attempts/' in '/' + relative.split('/', 2)[-1] + '/':
                area = 'launch-scratch'
            files[relative] = {'path': relative, 'kind': kind, 'size': info.st_size, 'area': area}
            counts[area] = counts.get(area, 0) + 1
    return {'root': str(root), 'files': files, 'counts': counts}


def declared(plan):
    """``(declared outputs, open deliverables)`` from the approved plan; one row per distinct output."""
    rows, open_rows, by_artifact = [], [], {}
    for item in (plan or {}).get('deliverables') or ():
        if type(item) is not dict or type(item.get('id')) is not str:
            continue
        step, output = item.get('step'), item.get('output')
        if item.get('status') != 'mapped' or type(step) is not str or type(output) is not str:
            open_rows.append({'deliverable': item['id'], 'reason': item.get('reason') or 'kept open by the plan',
                              'claim_kind': item.get('claim_kind'), 'artifact_kind': item.get('artifact_kind')})
            continue
        artifact = f'{step}:{output}'
        if artifact in by_artifact:
            by_artifact[artifact]['deliverables'].append(item['id'])
            continue
        row = {'artifact': artifact, 'deliverables': [item['id']], 'step': step, 'output': output,
               'destination': f'steps/{step}/{output}', 'claim_kind': item.get('claim_kind'),
               'artifact_kind': item.get('artifact_kind')}
        by_artifact[artifact] = row
        rows.append(row)
    return rows, open_rows


def _json_document(path, size):
    if size > common.TEXT_LIMIT:
        return None
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _strings(value, depth=0):
    if depth > 64:
        return
    if type(value) is str:
        yield value
    elif type(value) is dict:
        for key, item in value.items():
            yield key
            yield from _strings(item, depth + 1)
    elif type(value) is list:
        for item in value:
            yield from _strings(item, depth + 1)


def self_declared_diagnostic(document):
    return type(document) is dict and any(document.get(k) is v if type(v) is bool else document.get(k) == v
                                          for k, v in DIAGNOSTIC_KEYS)


def archive_members(path):
    """sha256 of each regular member of a zip or tar archive (bounded); None when not an archive."""
    import hashlib
    name = Path(path).name.lower()
    if not name.endswith(ARCHIVES):
        return None
    found = []
    try:
        if name.endswith('.zip'):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist()[:4096]:
                    if not info.is_dir() and info.file_size <= common.HASH_LIMIT:
                        found.append(hashlib.sha256(archive.read(info)).hexdigest())
        else:
            with tarfile.open(path) as archive:
                for member in archive.getmembers()[:4096]:
                    if member.isfile() and member.size <= common.HASH_LIMIT:
                        stream = archive.extractfile(member)
                        if stream is not None:
                            found.append(hashlib.sha256(stream.read()).hexdigest())
    except (OSError, zipfile.BadZipFile, tarfile.TarError, io.UnsupportedOperation):
        return []
    return found


def diagnostic_population(ev):
    """Digests, destinations and ids of every adopted artifact that is not an accepted result."""
    digests, names = {}, {}
    for artifact, record in ev['custody'].items():
        outcome = ev['outcomes'].get(record.get('step_id')) or {}
        accepted = (record.get('status') == 'accepted' and outcome.get('status') == 'completed'
                    and outcome.get('attempt') == record.get('attempt'))
        if accepted:
            continue
        reason = (f"custody {record.get('status')}" if record.get('status') != 'accepted'
                  else f"step {record.get('step_id')} is {outcome.get('status') or 'not completed'}")
        if type(record.get('sha256')) is str:
            digests.setdefault(record['sha256'], (artifact, reason))
        for value in (artifact, record.get('destination')):
            if type(value) is str:
                names.setdefault(value, (artifact, reason))
    # Superseded custody rows of an artifact keep their digests visible too.
    for record in ev['custody_rows']:
        if record.get('status') in ('rejected', 'staged') and type(record.get('sha256')) is str:
            latest = ev['custody'].get(record.get('artifact')) or {}
            if latest.get('sha256') != record['sha256']:
                digests.setdefault(record['sha256'], (record.get('artifact'), f"custody {record.get('status')}"))
    return digests, names


def _lineage(ev, artifact, hashes, seen, depth):
    if depth > MAX_DEPTH:
        return [f'{artifact}: custody chain deeper than {MAX_DEPTH}']
    if artifact in seen:
        return []
    seen.add(artifact)
    record = ev['custody'].get(artifact)
    if record is None:
        return [f'{artifact}: predecessor has no custody record']
    if record.get('status') != 'accepted':
        return [f'{artifact}: predecessor custody is {record.get("status")} (a diagnostic ancestor)']
    destination = record.get('destination')
    if type(destination) is not str or hashes.of(destination) != record.get('sha256'):
        return [f'{artifact}: predecessor bytes changed or are missing']
    problems = [str(e) for e in ev.get('host_receipt_errors', {}).get(artifact, [])]
    for parent in record.get('inputs') or ():
        problems.extend(_lineage(ev, parent, hashes, seen, depth + 1))
    return problems


def _settle(ev, row, files, hashes, digests, names, run):
    """Fix one row's status: ``accepted`` only when its custody, attempt, bytes, lineage and population hold."""
    record = ev['custody'].get(row['artifact'])
    outcome = ev['outcomes'].get(row['step']) or {}
    entry = files.get(row['destination'])
    row.update(status=None, sha256=None, custody=None, reasons=[], producer=None, size=None, document=None)
    if record is not None:
        row['custody'] = {'record_id': record.get('_id'), 'status': record.get('status'),
                          'sha256': record.get('sha256'), 'attempt': record.get('attempt'),
                          'kind': record.get('kind'), 'inputs': list(record.get('inputs') or [])}
        row['producer'] = record.get('producer') if type(record.get('producer')) is dict else None
    if entry is not None:
        row['size'] = entry['size']
    if record is None:
        row.update(status='unreceipted', reasons=['the declared output has no custody record in the store'])
        return row
    if record.get('status') != 'accepted':
        row.update(status='not_accepted', reasons=[f"latest custody verdict is {record.get('status')}"])
        return row
    if entry is None or entry['kind'] != 'file':
        row.update(status='missing', reasons=['the adopted bytes are missing or not a regular file'])
        return row
    sha = hashes.of(row['destination'])
    row['sha256'] = sha
    if sha != record.get('sha256'):
        row.update(status='changed', reasons=['the adopted bytes differ from their custody digest'])
        return row
    if outcome.get('status') != 'completed' or outcome.get('attempt') != record.get('attempt'):
        row.update(status='step_not_completed',
                   reasons=[f"step {row['step']} latest outcome is {outcome.get('status') or 'absent'} "
                            f"(attempt {outcome.get('attempt')}), custody attempt {record.get('attempt')}"])
        return row
    problems = [str(e) for e in ev.get('host_receipt_errors', {}).get(row['artifact'], [])]
    for parent in record.get('inputs') or ():
        problems.extend(_lineage(ev, parent, hashes, {row['artifact']}, 1))
    if problems:
        row.update(status='lineage', reasons=problems)
        return row
    # Diagnostic promotion: the same bytes, a self-declared diagnostic document, or nested bytes.
    promoted = []
    twin = digests.get(sha)
    if twin is not None and twin[0] != row['artifact']:
        promoted.append(f'the bytes are those of the diagnostic artifact {twin[0]} ({twin[1]})')
    path = run / row['destination']
    document = _json_document(path, entry['size']) if path.suffix.lower() == '.json' else None
    row['document'] = document is not None
    if self_declared_diagnostic(document):
        promoted.append('the document declares itself diagnostic')
    if document is not None:
        for text in _strings(document):
            hit = digests.get(text) or names.get(text)
            if hit is not None and hit[0] != row['artifact']:
                promoted.append(f'the document nests the diagnostic artifact {hit[0]} ({hit[1]})')
                break
    members = archive_members(path)
    if members:
        for member in members:
            hit = digests.get(member)
            if hit is not None:
                promoted.append(f'the archive nests the diagnostic artifact {hit[0]} ({hit[1]})')
                break
    if promoted:
        row.update(status='diagnostic_promotion', reasons=promoted)
        return row
    row['status'] = 'accepted'
    return row


def qualified(ev, artifacts, inv, hashes):
    """Rows for artifacts a route's ending selected for a qualified delivery, checked like declared outputs.

    Each names an adopted artifact by its custody id. It is deliverable only when its custody
    record places it at ``steps/<step>/<path>`` and the same custody, attempt, byte, lineage and
    diagnostic-promotion checks as a declared output pass. Nothing here makes it accepted science.
    """
    digests, names = diagnostic_population(ev)
    run = Path(inv['root'])
    rows = []
    for artifact in dict.fromkeys(a for a in artifacts if type(a) is str and a):
        record = ev['custody'].get(artifact) or {}
        step, output = record.get('step_id'), record.get('path')
        if type(step) is not str or type(output) is not str or not step or not output:
            rows.append({'artifact': artifact, 'deliverables': [], 'step': step, 'output': output, 'destination': None,
                         'status': 'unreceipted', 'sha256': None, 'custody': None, 'producer': None, 'size': None,
                         'document': None, 'reasons': ['the selected artifact has no custody record in the store']})
            continue
        row = {'artifact': artifact, 'deliverables': [], 'step': step, 'output': output,
               'destination': f'steps/{step}/{output}', 'claim_kind': None, 'artifact_kind': record.get('kind')}
        _settle(ev, row, inv['files'], hashes, digests, names, run)
        if row['status'] == 'accepted' and record.get('destination') != row['destination']:
            row.update(status='changed', reasons=[f"custody places the artifact at {record.get('destination')}, "
                                                  f"not {row['destination']}"])
        rows.append(row)
    return rows


def classify(ev, plan, inv, hashes):
    """The declared population's status, the open deliverables and every excluded file."""
    rows, open_rows = declared(plan)
    files = inv['files']
    digests, names = diagnostic_population(ev)
    run = Path(inv['root'])
    destinations = {}
    for artifact, record in ev['custody'].items():
        if type(record.get('destination')) is str:
            destinations[record['destination']] = artifact
    declared_destinations = {row['destination'] for row in rows}
    for row in rows:
        _settle(ev, row, files, hashes, digests, names, run)
    extras, excluded = [], []
    for relative, entry in sorted(files.items()):
        if relative in declared_destinations:
            continue
        if relative in destinations:
            artifact = destinations[relative]
            record = ev['custody'][artifact]
            credited = any(c.get('step_id') == record.get('step_id') and c.get('credited') and c.get('seats')
                           for c in ev['credits'])
            extras.append({'path': relative, 'artifact': artifact, 'size': entry['size'],
                           'custody': record.get('status'),
                           'reviewed': bool(credited and record.get('status') == 'accepted')})
            continue
        if entry['area'] in ('adopted', 'other') or entry['kind'] != 'file':
            reason = ('a symbolic link or special file' if entry['kind'] != 'file' else
                      'no custody record: bytes nobody adopted' if entry['area'] == 'adopted' else
                      'outside the adoption area and without custody')
            excluded.append({'path': relative, 'size': entry['size'], 'area': entry['area'], 'reason': reason})
    return {'declared': rows, 'open': open_rows, 'extras': extras, 'excluded': excluded[:MAX_LISTED],
            'excluded_count': len(excluded), 'counts': inv['counts']}
