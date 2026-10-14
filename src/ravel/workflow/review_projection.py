"""Reviewer packet projection driven by the role card's ``sees``.

A voting reviewer is a full-tool ``agent`` worker. Its blinding holds by construction:
its workspace receives only the packet this module projects, never the run tree.

- ``sees.profile`` selects the candidate files:
  ``full``: every run file under the card's ``tools.read_paths``;
  ``blind``: the card's read paths inside ``inputs/`` only (the spec and pinned inputs);
  ``spec-denied``: the plan and its pinned contract only (``SPEC_DENIED_FILES``);
  ``workspace`` is a producer profile and is refused here.
- ``sees.forbidden_inputs`` names classes (``CLASSES``) that are omitted whole or
  field-redacted. An unknown class refuses the projection (fail closed).
- The graph state, framework events, other packets and live worker calls are never
  projected (``ALWAYS_DENIED``). Withheld sources are the run's contract
  ``forbidden_sources`` path rows.

The packet is the review_context packet format (``manifest.json`` + ``artifacts/``),
so ``agent_worker.materialize(packet=...)`` copies and authenticates it unchanged. It
lives under the state store, outside the run tree. Every omission is listed with its
class; nothing is dropped silently. ``arm='manuscript-only'`` is the evaluation control
arm: it projects only the named subjects, never the record.

``finding_errors`` is the AG-3 rule: a blocking finding counts only with locators that
name this worker's broker receipts (``receipt:<id>``), pinned packet inputs
(``pin:<sha256>``) or a registered check or stage (``check:``/``stage:``). A finding that
cites any other pin is refused and recorded; refusal never upgrades a finding.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from . import broker, execution
from .state_io import atomic_json, read_json

SCHEMA_VERSION = 1
KIND = 'review-projection'
PROFILES = ('full', 'blind', 'spec-denied')
ARMS = (None, 'manuscript-only')
SPEC_DENIED_FILES = ('inputs/request_plan.json', 'inputs/task_contract.json')
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 64 * 1024**2
MAX_FILES = 4000
ALWAYS_DENIED = ('framework/', 'review/packets/', 'review/projections/', 'graphs/', '.ravel/', 'logs/.route-pending')
# Live call receipts of other workers are denied to blind readers (§1.9); the record
# auditor reads the published receipts through its own read paths.
BLIND_DENIED_PARTS = ('calls',)
HEADLINE_NAMES = {'result.md', 'result.json', 'verification.json', 'checkin1.json', 'checkin2.json', 'checkin3.json',
                  'checkin1_approval.json', 'checkin2_go.json', 'science-approval.json', 'headline.json'}
ROUTINE_ROLES = ('object-selection-mapper', 'trap-auditor', 'discrepancy-attributor', 'analysis-author')
CHECKLIST = 'review/routine_checklist.json'


def _headline(rel, name, parts):
    return (name in HEADLINE_NAMES or re.fullmatch(r'checkin\d.*\.md', name) is not None
            or rel.startswith('delivery/') or name == 'summary.md')


def _verdicts(rel, name, parts):
    return (rel.startswith(('review/', 'physics_review/', 'rdj/verdicts/'))
            or rel.startswith('agent-work/') and name in {'final.json', 'review.json', 'receipt.json'})


# class -> (path predicate(rel, name, parts), JSON keys redacted wherever they occur)
CLASSES = {
    'producer_headline': (_headline, ('headline', 'producer_verdict', 'conclusion', 'result_summary')),
    'other_verdicts': (_verdicts, ('verdict', 'votes', 'vote', 'disposition')),
    'lessons': (lambda rel, name, parts: 'lessons' in parts or name.startswith('lesson'), ()),
    'board_prose': (lambda rel, name, parts: rel.startswith('research/board/'), ()),
    'producer_numbers': (lambda rel, name, parts: rel.startswith(('outputs/', 'claims/')), ()),
    'critic_reasoning': (lambda rel, name, parts: rel.startswith('review/critic'), ('rationale', 'reasoning')),
    'held_out_artifacts': (lambda rel, name, parts: bool({'held_out', 'held-out', 'heldout'} & set(parts)), ()),
    'claim_quantity': (lambda rel, name, parts: rel.startswith('claims/'), ()),
    'withheld_sources': (None, ()),  # contract forbidden_sources path rows
}
LIMITATION = ('The packet holds only what the card permits. Blinding also requires the worker sandbox to deny '
              'the run tree, the state store and peer workspaces; the transport receipt records that evidence.')


class ProjectionRefused(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def digest(value):
    return execution.digest(value)


def projection_root(rundir):
    """Packets live in the state store, outside the run tree and outside worker custody."""
    run = broker.ordinary(rundir)
    base = broker._state_dir() / 'projections' / broker.digest(str(run))
    if base.is_relative_to(run) or run.is_relative_to(base):
        raise ProjectionRefused('projection_inside_run', 'review projections must be outside the run tree')
    broker._private_dirs(base)
    return broker.ordinary(base)


def _card(role):
    from . import role_registry
    card = role_registry.load(role) if type(role) is str else deepcopy(role)
    sees = card.get('sees')
    if type(sees) is not dict or sees.get('profile') not in (*PROFILES, 'workspace'):
        raise ProjectionRefused('card_sees_invalid', f"card {card.get('id')} has no valid sees")
    unknown = sorted(set(sees.get('forbidden_inputs', [])) - set(CLASSES))
    if unknown:
        raise ProjectionRefused('forbidden_class_unknown', 'unknown forbidden input classes: ' + ', '.join(unknown))
    return card


def _withheld(rundir):
    from . import knowledge_broker, source_policy
    rows = knowledge_broker.policy_rows(rundir)
    patterns = [p for row in rows for p in row.get('paths', [])]

    def hit(rel):
        inside = rel[len('inputs/'):] if rel.startswith('inputs/') else rel
        return any(source_policy._glob(p, inside) or source_policy._glob(p, rel) for p in patterns)
    return hit


def _candidates(run, card, arm, subjects):
    profile = card['sees']['profile']
    if arm == 'manuscript-only':
        return []
    if profile == 'spec-denied':
        return [rel for rel in SPEC_DENIED_FILES if (run / rel).is_file()]
    prefixes = list(card['tools']['read_paths'])
    if profile == 'blind':
        prefixes = [p for p in prefixes if p.startswith('inputs/')]
    found = []
    for prefix in prefixes:
        if '..' in Path(prefix).parts or Path(prefix).is_absolute():
            raise ProjectionRefused('read_path_invalid', 'card read paths are run-relative')
        target = run / prefix
        if prefix.endswith('/'):
            if target.is_dir() and not target.is_symlink():
                found.extend(p.relative_to(run).as_posix() for p in sorted(target.rglob('*')) if p.is_file() or p.is_symlink())
        elif target.is_file() or target.is_symlink():
            found.append(prefix)
    return [rel for rel in dict.fromkeys(found) if rel not in subjects]


def _redact(value, keys):
    removed = set()

    def walk(node):
        if type(node) is dict:
            out = {}
            for key, item in node.items():
                if key in keys:
                    removed.add(key)
                    continue
                out[key] = walk(item)
            return out
        if type(node) is list:
            return [walk(item) for item in node]
        return node
    return walk(value), sorted(removed)


def _classify(rel, forbidden, withheld, blind):
    name, parts = Path(rel).name.lower(), Path(rel).parts
    if any(rel.startswith(p) for p in ALWAYS_DENIED):
        return 'graph_or_review_state'
    if blind and any(p in BLIND_DENIED_PARTS for p in parts):
        return 'worker_calls'
    for cls in forbidden:
        predicate = CLASSES[cls][0]
        if cls == 'withheld_sources':
            if withheld(rel):
                return cls
        elif predicate(rel, name, parts):
            return cls
    return None


def _item_document(item):
    if item is None:
        return None
    keep = ('point_id', 'role', 'n', 'round', 'at', 'subject_sha256', 'claim_id', 'node_id', 'gate', 'findings')
    return {'schema_version': 1, 'kind': 'review-item-packet', **{k: deepcopy(item[k]) for k in keep if k in item}}


def build(rundir, role, *, item=None, subjects=(), arm=None, max_file_bytes=MAX_FILE_BYTES):
    """The manifest and the (relative path, bytes) pairs of one projection; nothing is written."""
    if arm not in ARMS:
        raise ProjectionRefused('arm_unknown', 'unknown projection arm')
    run = broker.ordinary(rundir)
    card = _card(role)
    profile = card['sees']['profile']
    if profile == 'workspace':
        raise ProjectionRefused('producer_profile', f"{card['id']} is a producer (sees.profile workspace); "
                                'it works in its own workspace, not a review projection')
    forbidden = sorted(card['sees'].get('forbidden_inputs', []))
    withheld = _withheld(run)
    blind = profile in ('blind', 'spec-denied')
    redact = tuple(sorted({k for cls in forbidden for k in CLASSES[cls][1]}))
    subjects = list(dict.fromkeys(subjects))
    manifest = {'schema_version': SCHEMA_VERSION, 'kind': KIND, 'role': card['id'],
                'card_sha256': broker.digest(card), 'profile': profile, 'arm': arm,
                'forbidden_inputs': forbidden, 'review_point_id': (item or {}).get('point_id'),
                'subject_sha256': (item or {}).get('subject_sha256'), 'subjects': [],
                'artifacts': [], 'omissions': [], 'access_limitation': LIMITATION}
    files = []
    total = 0

    def add(entry_id, rel, raw, *, source_sha256, projection, suffix):
        nonlocal total
        path = f'artifacts/{entry_id}{suffix}'
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ProjectionRefused('projection_too_large', 'review projection exceeds its byte bound')
        files.append((path, raw))
        manifest['artifacts'].append({'id': entry_id, 'path': path, 'sha256': hashlib.sha256(raw).hexdigest(),
                                      'source_path': rel, 'source_sha256': source_sha256, 'projection': projection})

    document = _item_document(item)
    if document is not None:
        raw = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        add('item', 'review/packets', raw, source_sha256=hashlib.sha256(raw).hexdigest(),
            projection='code-computed review item: subject, role and dependency findings without verdicts',
            suffix='.json')
    if card['id'] in ROUTINE_ROLES:
        from ravel.paths import package_data_path
        source = Path(package_data_path(CHECKLIST))
        raw = source.read_bytes()
        add('checklist', 'ravel:data/' + CHECKLIST, raw, source_sha256=hashlib.sha256(raw).hexdigest(),
            projection='exact bytes (package data)', suffix='.json')
    candidates = [(rel, 'subject') for rel in subjects] + [(rel, 'read_path') for rel in _candidates(run, card, arm, subjects)]
    if len(candidates) > MAX_FILES:
        raise ProjectionRefused('projection_too_large', 'review projection exceeds its file bound')
    for index, (rel, why) in enumerate(candidates):
        try:
            path = broker.confined(run, rel)
        except ValueError:
            manifest['omissions'].append({'source_path': rel, 'class': 'unsafe_path', 'reason': 'symlink or escape'})
            continue
        if not path.is_file():
            if why == 'subject':
                raise ProjectionRefused('subject_missing', 'review subject is not a run file: ' + rel)
            continue
        raw = path.read_bytes()
        source_sha = hashlib.sha256(raw).hexdigest()
        if why == 'subject':
            manifest['subjects'].append({'source_path': rel, 'source_sha256': source_sha})
            add(f's{index:04d}', rel, raw, source_sha256=source_sha, projection='review subject, exact bytes',
                suffix=Path(rel).suffix or '.txt')
            continue
        cls = _classify(rel, forbidden, withheld, blind)
        if cls is not None:
            manifest['omissions'].append({'source_path': rel, 'source_sha256': source_sha, 'class': cls,
                                          'reason': 'forbidden by the card' if cls in CLASSES else 'never projected'})
            continue
        if len(raw) > max_file_bytes:
            manifest['omissions'].append({'source_path': rel, 'source_sha256': source_sha, 'class': 'size',
                                          'reason': 'exceeds the per-file bound; request a bounded witness'})
            continue
        projection = 'exact bytes'
        if redact and Path(rel).suffix == '.json':
            try:
                value = json.loads(raw)
            except ValueError:
                value = None
            if value is not None:
                value, removed = _redact(value, redact)
                if removed:
                    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
                    projection = 'fields withheld: ' + ', '.join(removed)
        add(f'a{index:04d}', rel, raw, source_sha256=source_sha, projection=projection,
            suffix=Path(rel).suffix or '.txt')
    manifest['sha256'] = digest(manifest)
    return manifest, files


def project(rundir, role, *, key, item=None, subjects=(), arm=None, out_root=None):
    """Write (once) and return ``{'path', 'manifest_sha256'}`` for the current run bytes.

    The folder is addressed by ``key`` and the manifest digest, so a changed run never
    reuses an older packet; an existing packet with the same address is re-verified.
    """
    from .review_context import verify_packet
    if type(key) is not str or not key:
        raise ProjectionRefused('key_required', 'a projection key is required')
    manifest, files = build(rundir, role, item=item, subjects=subjects, arm=arm)
    base = Path(out_root) if out_root is not None else projection_root(rundir)
    folder = base / broker.digest([key, manifest['role'], arm, manifest['sha256']])[:32]
    binding = {'path': str(folder), 'manifest_sha256': manifest['sha256']}
    if (folder / 'manifest.json').is_file():
        verify_packet(folder, expected_manifest_sha256=manifest['sha256'])
        return binding
    staging = folder.with_name(folder.name + '.partial-' + str(os.getpid()) + '-' + str(id(files)))
    (staging / 'artifacts').mkdir(parents=True, exist_ok=False)
    for path, raw in files:
        with (staging / path).open('xb') as stream:
            stream.write(raw)
    atomic_json(staging / 'manifest.json', manifest)
    for path in [*(staging / 'artifacts').iterdir(), staging / 'manifest.json']:
        path.chmod(0o400)
    try:
        staging.rename(folder)
    except OSError:
        if not (folder / 'manifest.json').is_file():
            raise
    verify_packet(folder, expected_manifest_sha256=manifest['sha256'])
    return binding


def packet_for(rundir, item):
    """The review graph seam: the projected packet of one review item, or None for a producer role."""
    from . import role_registry
    card = role_registry.load(item['role'])
    if card['sees']['profile'] == 'workspace':
        return None
    return project(rundir, card, key=item['key'], item=item)


def load(packet):
    """The manifest and ``{source_path: bytes}`` of a verified packet (for checks run over it)."""
    from .review_context import _PacketIndex
    index = _PacketIndex(packet['path'], packet['manifest_sha256'])
    contents = {entry['source_path']: index.read(entry) for entry in index.manifest['artifacts']}
    index.finish()
    return index.manifest, contents


# ---- AG-3: a finding counts only with receipt or pinned-input evidence ----------------

BLOCKING = {'new_receipt', 'code_check'}


def finding_errors(rundir, finding, *, node_id, attempt, packet_manifest=None):
    """Errors for one finding; empty when every blocking locator is a receipt, pinned input or check."""
    from .review_points import finding_record
    value = finding_record(finding)
    if value.get('materiality') not in {'A', 'B'} or value.get('evidence_class') not in BLOCKING:
        return []
    locators = value.get('evidence_locators') or []
    errors = []
    if not locators:
        errors.append({'code': 'finding_unpinned', 'locator': None,
                       'message': 'a blocking finding names the receipt, pinned input or check behind it'})
    receipts = {}
    try:
        for row in broker.ledger(rundir, 'broker'):
            record = row['record']
            if record['node_id'] == node_id and record['attempt'] == attempt:
                receipts[record['path']] = record
    except (OSError, ValueError):
        receipts = {}
    pinned = {a['sha256'] for a in (packet_manifest or {}).get('artifacts', [])}
    pinned |= {a['source_sha256'] for a in (packet_manifest or {}).get('artifacts', [])}
    for locator in locators:
        if type(locator) is not str:
            errors.append({'code': 'non_receipt_pin', 'locator': locator, 'message': 'locator is not a string'})
            continue
        if locator.startswith(('check:', 'stage:')):
            continue
        if locator.startswith('receipt:'):
            receipt_id = locator[len('receipt:'):]
            ok = False
            for path, record in receipts.items():
                try:
                    body = broker.verify_broker_receipt(rundir, {'path': path, 'sha256': record['sha256']},
                                                        verify_outputs=False)
                except (OSError, ValueError, KeyError):
                    continue
                # A completed registered check counts whatever its verdict: a failing check is evidence.
                completed_check = (body.get('status') == 'failed' and body.get('derivation') == 'registered_validator'
                                   and body.get('validator_id') and body.get('output_pins'))
                if body.get('receipt_id') == receipt_id and (body.get('status') == 'ok' or completed_check):
                    ok = True
                    break
            if not ok:
                errors.append({'code': 'receipt_unknown', 'locator': locator,
                               'message': 'no ok broker receipt of this worker has that id'})
            continue
        if locator.startswith('pin:') and locator[len('pin:'):] in pinned:
            continue
        errors.append({'code': 'non_receipt_pin', 'locator': locator,
                       'message': 'a finding counts only with pins to broker receipts or pinned inputs'})
    return errors


REFUSED = 'review/refused-findings'


def screen_findings(rundir, receipt, findings, *, packet_manifest=None):
    """Record the refused findings of one reviewer receipt; returns ``(accepted, refused)``."""
    accepted, refused = [], []
    for finding in findings or []:
        if type(finding) is not dict:
            continue
        errors = finding_errors(rundir, finding, node_id=receipt['node_id'], attempt=receipt['attempt'],
                                packet_manifest=packet_manifest)
        (refused if errors else accepted).append({**deepcopy(finding), **({'refusal': errors} if errors else {})})
    if refused:
        path = Path(rundir) / REFUSED / f"{receipt['node_id']}-{receipt['attempt']}.json"
        atomic_json(path, {'schema_version': 1, 'kind': 'refused-findings', 'node_id': receipt['node_id'],
                           'attempt': receipt['attempt'], 'findings': refused})
    return accepted, refused


# ---- review graph seams (graphs/review.py) ------------------------------------------------

def screen_receipt(rundir, receipt):
    """Screen one reviewer receipt's final findings (AG-3); returns counts for the graph state."""
    from . import agent_worker
    try:
        ws = agent_worker.workspace(rundir, receipt['node_id'], receipt['attempt'])
        final = read_json(ws / 'final.json') if (ws / 'final.json').is_file() else {}
        manifest = read_json(ws / 'inputs/packet/manifest.json') if (ws / 'inputs/packet/manifest.json').is_file() else None
    except (OSError, ValueError, KeyError):
        return {'screened': False}
    accepted, refused = screen_findings(rundir, receipt, (final or {}).get('findings') or [], packet_manifest=manifest)
    return {'screened': True, 'accepted': len(accepted), 'refused': len(refused)}


DIVERGENCE_ROLE = 'analysis-author'


def compare_divergence(rundir, at):
    """Run the comparator on every implementation-divergence point at ``at`` whose two authors are credited."""
    from ravel.validation import divergence
    from . import review_points
    root = Path(rundir)
    facts = review_points._facts(root)
    points = [p for p in review_points.derive(facts) if p['when']['at'] == at and p['id'].endswith(':divergence')]
    records = list(review_points._receipt_records(root, facts)) if points else []
    out = {}
    for point in points:
        authors = []
        for rec in records:
            if (rec['_eligible'] and rec.get('review_point_id') == point['id'] and rec.get('status') == 'ok'
                    and rec.get('role', {}).get('id') == DIVERGENCE_ROLE):
                final = (root / rec['_path']).parent / rec['final_record']['path']
                authors.append(read_json(final))
        if len(authors) < 2:
            out[point['id']] = {'status': 'awaiting_pair', 'authors': len(authors)}
            continue
        value = divergence.compare(authors[0], authors[1])
        out[point['id']] = {'status': value['status'], 'record': divergence.record(root, point['id'], value)}
    return out


def divergence_a_findings(rundir, point_ids):
    """A findings of the registered divergence results of ``point_ids`` (the comparator's own check)."""
    from ravel.validation import divergence
    found = []
    for point_id, value in divergence.recorded(rundir, point_ids).items():
        if value.get('status') != 'failed':
            continue
        for finding in value.get('findings', []):
            if finding.get('materiality') == 'A':
                found.append({'point_id': point_id, **{k: deepcopy(finding[k]) for k in (
                    'id', 'materiality', 'severity', 'evidence_class', 'evidence_locators', 'summary', 'claim',
                    'location', 'status') if k in finding}})
    return found
