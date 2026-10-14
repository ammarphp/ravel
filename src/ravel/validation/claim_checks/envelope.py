"""Bounded, read-only claim-check seam at completed science delivery.

A retained typed plan governs when it belongs to the approved input snapshot.
Legacy envelopes resolve their mode signature and recompute artifact checks. Existing
adapter verification still governs their I/O postconditions; no registry result grants
execution authority or bypasses review. Explicit raw claim evidence is always checked.
"""
from __future__ import annotations

from pathlib import Path

from ravel.validation import validate_request_plan as rp
from . import rows
from .registry import _context_checks, documents, evaluate, evaluate_check, resolve

MAX_FILES = 512
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


def _outputs(paths, session=None):
    from ravel.validation.certificates import read_json
    found = set()
    for value in paths:
        path = Path(value)
        if path.is_symlink():
            raise ValueError('claim-check outputs cannot traverse symlinks')
        if path.is_dir():
            if session is not None:
                session.require_inventory(path)
            for member in path.rglob('*'):
                if member.is_symlink():
                    raise ValueError('claim-check outputs cannot contain symlinks')
                if member.is_file() and member.suffix == '.json':
                    found.add(member)
        elif path.is_file():
            if path.suffix == '.json':
                found.add(path)
        else:
            raise ValueError('claim-check output is missing or not a retained document directory')
    if len(found) > MAX_FILES:
        raise ValueError('claim-check output population exceeds the bounded census')
    records, total = [], 0
    for path in sorted(found):
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('claim-check artifact bytes exceed the bounded census')
        value = session.read_document(path) if session is not None else read_json(path)
        if isinstance(value, dict):
            records.append((str(path), value))
    return records


def _approved_input(root, path, proposal):
    from ravel.workflow import execution
    absolute = str(Path(path).resolve())
    for value, record in proposal.get('stage_binding', {}).get('input_snapshot', {}).items():
        if str(execution.resolve_path(root, value).resolve()) == absolute:
            entries = record.get('files', [])
            return record.get('kind') == 'file' and len(entries) == 1 and entries[0].get('sha256') == execution.file_hash(path)
    return False


def science_errors(rundir, mode, outputs, *, _session=None):
    """Refuse computed artifact violations, including certificates, on every science mode.

    ``outputs`` are exactly the successful stage's retained paths. This is a read-only
    consumer: callers bind success/approval first. Certificates independently recheck
    science approval and require their comparison plans among its pinned stage inputs.
    """
    root = Path(rundir).resolve()
    try:
        records = _outputs(outputs, _session)
        reg = rp.registry()
        if reg.get(mode) is None:
            return [f'unresolved claim-check route {mode}']
        # Always resolve the route, even when a legacy adapter has no typed request plan.
        kinds = {d.get('kind') for _, d in records}
        kind = 'inference' if 'inference' in kinds else 'document' if 'document' in kinds else 'table'
        plan = {'inputs': [], 'nodes': [{'id': 'N1', 'kind': 'operation', 'operation': mode, 'fields': []}],
                'edges': [{'from': {'ref': 'N1', 'slot': 'output'}, 'to': {'ref': 'C1', 'slot': 'deliverable'}, 'kind': kind, 'require': {}}],
                'claims': [{'id': 'C1', 'kind': 'finding', 'deliverable': {'artifact': kind}, 'inherits': [], 'comparison': {'target': 'none'}}]}
        artifacts = {'N1': [d for _, d in records]}
        resolution = resolve(plan, artifacts=artifacts)
        # All explicit raw records are consumed, including repeated records of one row.
        checks = []
        for source, document in records:
            evidence = document.get('claim_evidence', {})
            if not isinstance(evidence, dict):
                raise ValueError('claim_evidence must map registered ids to raw observations')
            for check_id, payload in evidence.items():
                context = {'root': root}
                if check_id in ('acceptance_certificate', 'r5'):
                    subjects = {str(Path(path).relative_to(root)) for path, d in records if d.get('kind') == 'inference' or 'limits' in d}
                    subjects.add(str(Path(source).relative_to(root)))
                    context = {'root': root, 'contract': payload.get('contract'), 'required_subjects': sorted(subjects), 'science_envelope': True}
                checks.append({**evaluate_check(check_id, payload, **context), 'source': source})
        # Contextual predicates declared by retained documents require raw evidence even if
        # the producer omitted its record. Route-inferred obligations bind typed plans only:
        # legacy adapters do not yet produce that evidence.
        declared = _context_checks(plan, {'N1'}, documents(artifacts, {'N1'}), set(), set(), set())
        required = set(resolution['claims']['C1']) & set(rows.EVALUATORS) & declared
        supplied = {row['id'] for row in checks}
        for check_id in sorted(required - supplied):
            checks.append(evaluate_check(check_id, {}))
        from ravel.validation.regression_triggers import evaluate as alarms, consume_flags
        for source, document in records:
            checks += [{**row, 'source': source} for row in (alarms(document) if document.get('kind') == 'inference' else consume_flags(document))]
            if 'limits' in document:
                from ravel.limits import claim_errors
                checks += [{'id': 'limit_status', 'status': 'fail', 'detail': error, 'source': source} for error in claim_errors(document)]
        # A typed plan is authoritative only when it is an exact approved input.
        path = root / 'inputs/plan.json'
        if path.exists():
            from ravel.workflow import science
            proposal = science.verify_plan(root, approved=True, _session=_session)
            if not _approved_input(root, path, proposal):
                raise ValueError('typed claim-check plan is not bound by the science approval')
            from ravel.validation.certificates import read_json
            typed = _session.read_document(path) if _session is not None else read_json(path)
            if mode not in {n.get('operation') for n in typed.get('nodes', [])}:
                raise ValueError('typed claim-check plan does not contain the executed route')
            # Producers bind artifacts to exact node refs. Unknown refs are refused.
            grouped = {}
            known = {n['id'] for n in typed.get('nodes', [])} | {i['id'] for i in typed.get('inputs', [])} | {c['id'] for c in typed.get('claims', [])}
            for source, document in records:
                ref = document.get('source_ref')
                if ref is None:
                    if document.get('claim_evidence'):
                        raise ValueError('typed claim evidence must name its source_ref')
                    continue
                if ref not in known:
                    raise ValueError('claim artifact names an unknown lineage ref')
                grouped.setdefault(ref, []).append(document)
            checks += evaluate(typed, artifacts=grouped, root=root, science_envelope=True)
        return [f"{row.get('id', row.get('trigger', 'claim_check'))}: {row.get('detail', 'computed violation')}" for row in checks if row['status'] == 'fail']
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return ['claim checks: ' + str(exc)]


def review_checks(root, declared, receipts, *, _session=None):
    """Journal rows computed from bound outputs, in the existing located-evidence shape.

    Host files omit computed ids. Every prospectively declared computed id is filled
    here, even if missing evidence makes it fail. This introduces no new authority.
    """
    from .registry import computed_id
    from ravel.workflow import physics_review as review
    required = sorted(check_id for check_id in declared if computed_id(check_id))
    if not required:
        return []
    outputs = [p for receipt in receipts for p in receipt.get('outputs', [])]
    records = _outputs(outputs, _session)
    if not records:
        raise ValueError('computed review checks need retained output documents')
    results = []
    for check_id in required:
        name = check_id.removeprefix('check:')
        payloads = [(path, doc['claim_evidence'][name]) for path, doc in records if name in doc.get('claim_evidence', {})]
        checks = []
        if name.startswith('regression/') or '@' in name:
            from ravel.validation.regression_triggers import evaluate as alarms, consume_flags
            trigger = name.removeprefix('regression/').split('@', 1)[0]
            checks = [c for _, d in records for c in (alarms(d) if d.get('kind') == 'inference' else consume_flags(d)) if c['trigger'] == trigger]
        elif payloads:
            subjects = {str(Path(path).relative_to(root)) for path, doc in records
                        if doc.get('kind') == 'inference' or 'limits' in doc}
            for path, payload in payloads:
                context = {'root': root}
                if name in ('acceptance_certificate', 'r5'):
                    context['required_subjects'] = sorted(subjects | {str(Path(path).relative_to(root))})
                checks.append(evaluate_check(name, payload, **context))
        else:
            checks = [evaluate_check(name, {}, root=root, documents=records)]
        status = 'fail' if not checks or any(c['status'] == 'fail' for c in checks) else 'pass' if all(c['status'] == 'pass' for c in checks) else 'inconclusive'
        sources = sorted({path for path, _ in payloads} or {path for path, _ in records})
        evidence = [{'path': review._pin(root, path, _session=_session)['path'], 'location': '/claim_evidence/' + name} for path in sources]
        results.append({'id': check_id, 'status': status, 'evidence': evidence, 'attempt_ids': sorted({r['attempt_id'] for r in receipts})})
    return results


def retained_checks(paths):
    """Recompute contextual alarms at legacy review acceptance, independent of policy labels."""
    checks = []
    for source, document in _outputs(paths):
        evidence = document.get('claim_evidence', {})
        if not isinstance(evidence, dict):
            raise ValueError('claim_evidence must map check ids to raw observations')
        for name, payload in evidence.items():
            if name in rows.EVALUATORS:
                checks.append({**evaluate_check(name, payload), 'trigger': name, 'source': source,
                               'location': '/claim_evidence/' + name})
    return checks
