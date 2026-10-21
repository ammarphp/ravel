"""Writing a delivery: the only writer of ``delivery/`` and of the trusted-side results file.

A delivery is assembled in a private staging directory beside the run's ``delivery/`` and moved
into place in one rename; a previous delivery is kept under ``delivery.superseded-<time>-<id>``,
never overwritten or deleted. It holds ``DELIVERY.md`` (the user-visible report), ``RECEIPT.json``
(the recomputed receipt), ``INVENTORY.json`` (the sink's own inventory) and ``artifacts/`` (copies
of the deliverable outputs, verified against their custody digests while they are copied; at a
bounded ending also the artifacts a route selected for it, marked qualified). Every delivered
text document begins with a sink notice block carrying the label, every notice and the host
governance label, so no worker prose can strip or override them; the original bytes follow
unchanged and their digest is recorded. Presentation artifacts carry visible provenance in
separately hashed derivatives. Scientific data stays byte-identical with an inventoried sidecar.
"""
from __future__ import annotations

import hashlib
import stat
from ravel.workflow import private_files
import json
import os
from pathlib import Path
import secrets
import shutil
import time

from . import common, receipts, presentation

NOTICE = 'RAVEL SINK NOTICE'
NOTICE_END = 'END RAVEL SINK NOTICE'
CHUNK = 1 << 20
TEXT_HEADERS = ('.md', '.markdown', '.txt', '.rst', '.tex', '.html', '.htm')


def governance_line(governance):
    """The host governance label and its reasons for every notice block (None when there is nothing to say)."""
    governance = governance or {}
    reasons = '; '.join(governance.get('reasons') or [])
    if governance.get('available') is False:
        return f"Host governance: {common.GOVERNANCE_UNKNOWN} ({governance.get('error') or 'unknown'})"
    if governance.get('label'):
        return f"Host governance: {governance['label']}" + (f' ({reasons})' if reasons else '')
    if governance and not governance.get('this_run'):
        return (f"Host governance: {common.NOT_GOVERNED} (the run directory belongs to "
                f"{governance.get('controller_run')!r}, not to this run)")
    if reasons:
        return f'Host governance: controller-owned run; {common.HOST_FINDINGS}: {reasons}'
    return None


def notice_lines(label, labels, source, sha, governance=None):
    lines = [f'RAVEL delivery label: {label.upper()}',
             'Notices rendered by the controller (not part of the worker text): ' + ('; '.join(labels) or 'none')]
    host = governance_line(governance)
    if host:
        lines.append(host)
    return lines + [f'Source: {source} (sha256 {sha})', 'Receipt: delivery/RECEIPT.json']


def notice_header(suffix, lines):
    if suffix in ('.md', '.markdown'):
        return f'<!-- {NOTICE} -->\n' + ''.join(f'> {line}\n>\n' for line in lines) + f'<!-- {NOTICE_END} -->\n\n'
    if suffix in ('.html', '.htm'):
        body = '<br>'.join(line.replace('&', '&amp;').replace('<', '&lt;') for line in lines)
        return f'<!-- {NOTICE} -->\n<div class="ravel-sink-notice"><strong>{body}</strong></div>\n<!-- {NOTICE_END} -->\n'
    if suffix == '.tex':
        return f'% {NOTICE}\n' + ''.join(f'% {line}\n' for line in lines) + f'% {NOTICE_END}\n'
    return f'==== {NOTICE} ====\n' + ''.join(f'{line}\n' for line in lines) + f'==== {NOTICE_END} ====\n\n'


def _write(path, data, *, mode=0o600):
    private_files.mkdir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), mode & 0o600)
    try:
        remaining = memoryview(data)
        while remaining:
            count = os.write(fd, remaining)
            if count <= 0:
                raise OSError('delivery write made no progress')
            remaining = remaining[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _copy_binary(source, target, row, *, mode=0o600):
    """Stream one scientific data file byte-identically with bounded memory, verifying its digest as it goes.

    The copy is private (mode narrowed to 0600 or less), exclusive and never follows a link; the file and its
    directory are made durable before the row is reported. A changed source removes the partial copy."""
    private_files.mkdir(target.parent)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), mode & 0o600)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, 'wb') as destination, source.open('rb') as stream:
            while chunk := stream.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
                destination.write(chunk)
            sha = digest.hexdigest()
            if sha != row['sha256']:
                raise common.SinkRefused(f"{row['destination']} changed while it was being delivered")
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        target.unlink()
        raise
    directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return sha, size


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def artifact_labels(findings, artifact):
    return sorted({entry['label'] for entry in findings.labels if entry.get('artifact') == artifact})


def copy_artifacts(run_dir, staging, classification, findings, label, labels, *, qualified=(), governance=None, receipt_reference=None):
    """Copy every deliverable output whose custody holds, re-verifying its bytes; returns the file rows.

    ``qualified`` rows are artifacts a route selected for a qualified ending (already verified);
    they are copied the same way and marked, with their own labels in their notice block.
    """
    rows = []
    receipt_reference = receipt_reference or ('ravel-delivery-' + secrets.token_hex(16))
    chosen = [(row, False) for row in classification['declared'] if row['status'] == 'accepted']
    chosen += [(row, True) for row in qualified if row['status'] == 'accepted']
    assumptions = getattr(findings, 'assumptions', [])
    assumption_text = '; '.join(f"{a['statement']} [source {a['locator']}]" for a in assumptions)
    for row, is_qualified in chosen:
        source = Path(run_dir) / row['destination']
        relative = f"artifacts/{row['step']}/{row['output']}"
        suffix = source.suffix.lower()
        own = artifact_labels(findings, row['artifact'])
        status = 'qualified' if is_qualified else label
        limitation = row.get('qualification') or '; '.join(labels + own) or None
        if assumptions:
            limitation = '; '.join(filter(None, (limitation,
                'Recorded assumptions: ' + assumption_text + '; complete appendix: ASSUMPTIONS.md')))
        target = staging / relative
        mode = stat.S_IMODE(source.stat().st_mode) & 0o600
        header = None
        sidecar_info = None
        if suffix in TEXT_HEADERS or presentation.presented(suffix):
            # A notice header or a visibly marked presentation derivative needs the whole document.
            raw = source.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if sha != row['sha256']:
                raise common.SinkRefused(f"{row['destination']} changed while it was being delivered")
            data = presentation.derivative(raw, suffix, status, receipt_reference, limitation)
            visible = data is not None
            if suffix in TEXT_HEADERS:
                notice = notice_lines(status, labels + [x for x in own if x not in labels],
                                      row['destination'], sha, governance)
                notice.append(f'Receipt reference: {receipt_reference}')
                if assumptions:
                    notice.append('Recorded assumptions: ' + assumption_text + '; appendix: ASSUMPTIONS.md')
                header = notice_header(suffix, notice).encode('utf-8')
                data = header + (data if data is not None else raw)
                visible = True
            if data is None:
                raise common.SinkRefused(f'{suffix} delivery produced no labelled presentation')
            _write(target, data, mode=mode)
            delivered_sha, size, derived = hashlib.sha256(data).hexdigest(), len(data), data != raw
        else:
            # Scientific data: streamed byte-identical with bounded memory; its label travels in a sidecar.
            sha, size = _copy_binary(source, target, row, mode=mode)
            delivered_sha, derived, visible = sha, False, False
            sidecar_path = relative + '.provenance.json'
            sidecar = _json_bytes({'label': status.upper(), 'qualification': limitation,
                                   'receipt_reference': receipt_reference, 'receipt_path': 'delivery/RECEIPT.json',
                                   'source': row['destination'], 'source_sha256': sha,
                                   'assumptions': assumptions,
                                   'visible_notice': False, 'reason': 'scientific data; retained byte-identical'})
            _write(staging / sidecar_path, sidecar)
            sidecar_info = {'path': sidecar_path, 'sha256': hashlib.sha256(sidecar).hexdigest(),
                            'size': len(sidecar)}
        rows.append({'artifact': row['artifact'], 'deliverables': row['deliverables'], 'path': relative,
                     'sha256': delivered_sha, 'source': row['destination'], 'source_sha256': sha,
                     'size': size, 'notice_header': header is not None, 'labels': own,
                     'presentation_derivative': derived, 'visible_notice': visible,
                     'receipt_reference': receipt_reference, 'presentation_label': status.upper(),
                     **({'provenance_sidecar': sidecar_info} if sidecar_info is not None else {}),
                     **({'qualified': True, 'qualification': row.get('qualification'), 'route': row.get('source')}
                        if is_qualified else {})})
    return rows


def _table(rows, columns):
    out = ['| ' + ' | '.join(title for title, _ in columns) + ' |', '|' + '---|' * len(columns)]
    for row in rows:
        cells = []
        for _, key in columns:
            value = key(row) if callable(key) else row.get(key)
            cells.append(str('-' if value in (None, '', []) else value).replace('|', '/').replace('\n', ' ')[:300])
        out.append('| ' + ' | '.join(cells) + ' |')
    return out


def markdown(receipt, classification, findings, ending=None):
    """The user-visible delivery report; every label and notice comes from the receipt."""
    label = receipt['label']
    lines = [f"# RAVEL delivery: {receipt.get('run_id')}", '',
             f'**Delivery label: {label.upper()}**' + (' (qualified ending)' if ending else ''), '',
             f"Architecture complete: {'yes' if receipt['architecture_complete'] else 'no'}", '']
    failed = [name for name, ok in receipt['architecture_predicates'].items() if not ok]
    if failed:
        lines += ['Predicates not met: ' + ', '.join(failed), '']
    lines += ['## Notices', '', 'Rendered by the controller from its own evidence. No worker output can add, '
              'remove or override them.', '']
    lines += [f'- {text}' for text in receipt['labels']] or ['- none']
    details = [d for d in receipt.get('label_details') or () if d.get('text')]
    if details:
        lines += ['', '### Details', '']
        lines += [f"- {d['label']}" + (f" ({d['artifact']})" if d.get('artifact') else '') + f": {d['text']}"
                  for d in details[:200]]
    host = governance_line((receipt.get('host') or {}).get('governance'))
    lines += ['', f"- {common.CUSTODY_BOUNDARY}"] + ([f'- {host}'] if host else []) + ['']
    engagement = receipt.get('engagement') or {}
    lines += ['## Engagement', '', f"Tier: {engagement.get('tier') or 'unknown'}; envelope: "
              f"{engagement.get('envelope_status') or 'unknown'}; seat plan: {engagement.get('seat_plan_sha256')}; "
              f"accepted delivery allowed: {'yes' if engagement.get('accepted_allowed') else 'no'}"
              + (f"; {engagement['error']}" if engagement.get('error') else ''), '',
              '```json', json.dumps(engagement, indent=2, sort_keys=True)[:20000], '```', '']
    files = {f['artifact']: f for f in (receipt.get('delivery') or {}).get('artifacts') or ()}
    lines += ['## Deliverables', '']
    lines += _table(classification['declared'], [
        ('Deliverable', lambda r: ', '.join(r['deliverables'])), ('Artifact', 'artifact'), ('Status', 'status'),
        ('Delivered as', lambda r: (files.get(r['artifact']) or {}).get('path')),
        ('sha256', lambda r: (r.get('sha256') or '')[:16]), ('Why', lambda r: '; '.join(r.get('reasons') or []))])
    if classification['open']:
        lines += ['', '## Original obligations not delivered', '']
        lines += _table(classification['open'], [('Deliverable', 'deliverable'), ('Reason', 'reason')])
    holes = ((receipt.get('ledger') or {}).get('deliverables') or {}).get('open') or []
    if holes:
        lines += ['', 'Ledger holes (original obligations without a covering, closed step): ' + ', '.join(holes)]
    if ending:
        lines += ['', '## Qualified ending', '', f"Reason: {ending.get('reason')}", '',
                  'Every original obligation and its state (no new claim is adopted by this ending):', '']
        lines += _table(ending.get('obligations') or [], [('Obligation', 'id'), ('State', 'state'),
                                                         ('Why', 'reason')])
        listed = ending.get('ledger_obligations') or []
        if listed:
            lines += ['', f'Ledger obligations ({len(listed)}):', '']
            lines += _table(listed[:400], [('Obligation', 'id'), ('Status', 'status'), ('Scope', 'scope'),
                                           ('Why', 'reason')])
        chosen = ending.get('qualified_artifacts') or []
        if chosen:
            lines += ['', '### Qualified artifacts', '', 'Selected by a route for this qualified ending and verified '
                      'again by the sink; they are not accepted results and every notice says so.', '']
            lines += _table(chosen, [('Artifact', 'artifact'), ('Route', 'source'), ('Qualification', 'qualification'),
                                     ('Delivered as', lambda r: (files.get(r['artifact']) or {}).get('path')
                                      or 'not delivered'), ('Why not', lambda r: '; '.join(r.get('reasons') or []))])
        for synthesis in ending.get('syntheses') or ():
            lines += ['', f"### Unfinished work recorded by {synthesis.get('source') or 'the route'}"
                      + (f" ({synthesis['kind']})" if synthesis.get('kind') else ''), '',
                      '```json', json.dumps(synthesis.get('result'), indent=2, sort_keys=True)[:20000], '```']
    if classification['extras']:
        lines += ['', '## Other adopted outputs (not declared deliverables; not delivered)', '']
        lines += _table(classification['extras'], [('Path', 'path'), ('Custody', 'custody'),
                                                   ('Reviewed', lambda r: 'yes' if r['reviewed'] else 'no')])
    if classification['excluded']:
        lines += ['', f"## Excluded files ({classification['excluded_count']})", '']
        lines += _table(classification['excluded'][:200], [('Path', 'path'), ('Reason', 'reason')])
    claims = getattr(findings, 'claims', None)
    if claims:
        lines += ['', '## Claims', '']
        lines += _table(claims, [('Claim', 'id'), ('Disposition', 'disposition'), ('Reason', 'reason')])
    defaults = (receipt.get('judgments') or {}).get('adopted_defaults') or []
    lines += ['', '## Adopted delegated defaults', '']
    lines += (_table(defaults, [('Source', 'source'), ('Id', 'id'), ('Chosen', 'chosen'),
                                ('Justification', lambda d: d.get('rationale') or d.get('default'))])
              if defaults else ['None.'])
    review = receipt.get('review') or {}
    lines += ['', '## Review', '']
    for purpose, row in sorted((review.get('rounds') or {}).items()):
        verdicts = ', '.join(f"{seat}: {(v or {}).get('verdict')} ({'credited' if (v or {}).get('credited') else 'not credited'})"
                             for seat, v in sorted((row.get('seats') or {}).items()))
        lines.append(f"- {purpose} (attempt {row.get('attempt')}): {verdicts or 'no seats'}")
    findings_rows = getattr(findings, 'review_findings', None) or []
    if findings_rows:
        lines += ['', 'Final review findings (as recorded):', '']
        lines += _table(findings_rows[:200], [('Seat', 'seat'), ('Item', 'id'), ('Severity', 'severity'),
                                              ('Verdict', 'verdict'), ('Text', 'text')])
    work = receipt.get('work') or {}
    lines += ['', '## Refusals and holds', '', f"Refusals recorded: {work.get('refused_count')} "
              f"(history {work.get('refusal_history_completeness')})"]
    lines += [f"- {r.get('source')}: {r.get('step_id') or r.get('id') or '-'}: {r.get('reason')}"
              for r in (work.get('refused') or [])[:50]]
    lines += [f"- hold: {h['step_id']}: {h['status']} ({h.get('reason')})" for h in (work.get('holds') or [])[:50]]
    costs = receipt.get('costs') or {}
    lines += ['', '## Usage', '', f"Model calls: {costs.get('model_calls') if costs.get('model_calls') is not None else 'unknown'}; "
              f"tokens: {costs.get('tokens') if costs.get('tokens') is not None else 'unknown'}; "
              f"cost: {costs.get('total') if costs.get('total') is not None else 'unknown'}"
              + (f"; not measured for every attempt: {', '.join(costs.get('unknown'))}" if costs.get('unknown') else '')]
    authority = receipt.get('authority') or {}
    lines += ['', '## Authority', '', f"Operating mode: {((authority.get('mode') or {}).get('mode'))}; labels: "
              + (', '.join(authority.get('labels') or []) or 'none') + '. Machine decisions are never labelled human.']
    for deviation in authority.get('deviations') or ():
        lines.append(f"- deviation {deviation.get('id')}: {deviation.get('decision')} ({deviation.get('label')}): "
                     f"{json.dumps(deviation.get('change'), sort_keys=True)[:300]}")
    security = receipt.get('authority_security') or {}
    probe = security.get('confinement_probe') or {}
    lines += ['', f"Authority issuer: {security.get('issuer_authentication') or 'not installed'}"
              + (f" ({security['issuer_error']})" if security.get('issuer_error') else '')
              + '. Terminal identity attested: ' + ('yes' if receipt.get('terminal_identity_attested') else 'no') + '.']
    if security.get('same_user_risk'):
        lines.append(f"Residual risk: {security['same_user_risk']}")
    lines.append(f"Confinement denial probe confirmed for {probe.get('confirmed', 0)} of {probe.get('launches', 0)} "
                 'confined launch(es).')
    lines += ['', 'Worker CLI destination confinement is unqualified. Provider port rules do not '
              'confine destinations; Linux provider profiles may also admit UDP or all ports. '
              'Restricted/internal CLI worker dispatch is refused until an endpoint-confined backend is qualified.']
    confinement = receipt.get('confinement') or {}
    for row in confinement.get('provider_egress') or ():
        lines.append(f"Worker {row.get('step_id')} provider egress: " +
                     (json.dumps(row['egress'], sort_keys=True) if row.get('egress') is not None
                      else 'unknown (historical receipt has no egress observation)'))
    for row in confinement.get('launches') or ():
        if row.get('resource_enforcement') is not None:
            protection = row['resource_enforcement']
            if protection.get('status') == 'partial':
                lines.append(f"Launch {row.get('id')}: {protection.get('label')}. "
                             'Aggregate memory, process count, retained disk and receipt headroom are unprotected. '
                             'Use a qualified execution adapter when these guarantees are required.')
            lines.append(f"Launch {row.get('id')} resource scope: " +
                         json.dumps(row['resource_enforcement'], sort_keys=True))
    if receipt.get('assumptions'):
        lines += ['', '## Recorded assumptions', '', 'Complete appendix: [ASSUMPTIONS.md](ASSUMPTIONS.md).', '']
        for assumption in receipt['assumptions']:
            lines += [f"- {assumption['statement']} (source `{assumption['locator']}`)"]
    lines += ['', '## Receipt', '', f"RECEIPT.json sha256 {receipt.get('sha256')}",
              f"Inventory sha256 {(receipt.get('delivery') or {}).get('inventory_sha256')}", '']
    return '\n'.join(lines) + '\n'


def write(run_dir, receipt, classification, findings, *, ending=None, inventory=None, qualified=()):
    """Assemble and move the delivery into place; returns the finalized receipt."""
    root = Path(run_dir)
    nonce = secrets.token_hex(4)
    staging = root / f'{common.DELIVERY_DIR}.staging-{nonce}'
    os.mkdir(staging, 0o700)
    target = root / common.DELIVERY_DIR
    superseded = None
    try:
        receipt_reference = 'ravel-delivery-' + secrets.token_hex(16)
        files = copy_artifacts(root, staging, classification, findings, receipt['label'], list(receipt['labels']),
                               qualified=qualified, governance=(receipt.get('host') or {}).get('governance'),
                               receipt_reference=receipt_reference)
        from . import procedure
        files += procedure.write(staging, getattr(findings, 'procedure', None))
        assumptions = receipt.get('assumptions') or []
        if assumptions:
            appendix = '# Recorded assumptions\n\n' + '\n\n'.join(
                f"- {a['statement']}\n  Source: `{a['locator']}`\n  Record digest: `{a['record_digest']}`"
                for a in assumptions) + '\n'
            for name, raw in [('ASSUMPTIONS.md', appendix.encode('utf-8')),
                              ('ASSUMPTIONS.json', _json_bytes({'schema_version': 1, 'assumptions': assumptions}))]:
                _write(staging / name, raw)
                files.append({'artifact': 'sink:' + name, 'deliverables': [], 'path': name,
                              'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
                              'source': 'controller:recorded-assumptions', 'source_sha256': common.digest(assumptions),
                              'receipt_reference': receipt_reference, 'labels': []})
        inventory_bytes = _json_bytes(common.plain({'classification': classification, 'walk': inventory or {},
                                                   'artifacts': files, 'receipt_reference': receipt_reference}))
        delivery = dict(receipt.get('delivery') or {})
        delivery.update(artifacts=files, directory=common.DELIVERY_DIR,
                        receipt_reference=receipt_reference, receipt_path='delivery/RECEIPT.json',
                        inventory_sha256=hashlib.sha256(inventory_bytes).hexdigest())
        if target.exists() or target.is_symlink():
            superseded = root / (f"{common.DELIVERY_DIR}.superseded-"
                                 f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{nonce}")
            delivery['superseded'] = superseded.name
        final = receipts.finalize(receipts.rederive(dict(receipt, delivery=delivery), rendered=True))
        _write(staging / 'INVENTORY.json', inventory_bytes)
        _write(staging / 'RECEIPT.json', _json_bytes(final))
        _write(staging / 'DELIVERY.md', markdown(final, classification, findings, ending).encode('utf-8'))
        if ending is not None:
            _write(staging / 'qualified-delivery.json',
                   _json_bytes(common.plain({**ending, 'receipt_sha256': final['sha256']})))
        if superseded is not None:
            os.rename(target, superseded)
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def rewrite_receipt(run_dir, receipt, classification, findings, ending=None):
    """Re-finalize a receipt after a post-delivery fact (results file, notification) and rewrite its files."""
    final = receipts.finalize(receipt)
    target = Path(run_dir) / common.DELIVERY_DIR
    for name, data in (('RECEIPT.json', _json_bytes(final)),
                       ('DELIVERY.md', markdown(final, classification, findings, ending).encode('utf-8'))):
        temporary = target / f'.{name}.{secrets.token_hex(4)}'
        _write(temporary, data)
        os.replace(temporary, target / name)
    return final


def write_results_file(target, source, *, run_dir, store_root, expected_sha256):
    """Write the accepted results document to a trusted-side path; refuse an unsafe location or changed bytes."""
    if type(target) is not str or not target:
        raise common.SinkRefused('the results file names no path')
    path = Path(target)
    if not path.is_absolute():
        raise common.SinkRefused('the results file path must be absolute')
    for forbidden, what in ((run_dir, 'the run directory'), (store_root, 'the controller store')):
        if forbidden is not None and common.inside(forbidden, path):
            raise common.SinkRefused(f'the results file must lie outside {what}')
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise common.SinkRefused('the results file directory must exist and be a real directory')
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise common.SinkRefused('the results file must be a regular file path')
    data = Path(source).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise common.SinkRefused('the accepted deliverable changed before the results file was written')
    temporary = path.with_name(f'.{path.name}.{secrets.token_hex(4)}')
    _write(temporary, data)
    os.replace(temporary, path)
    return {'status': 'written', 'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
