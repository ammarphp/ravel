#!/usr/bin/env python3
"""Apply source-owned registration fragments to the shared registries.

A package that adds an operation, a census row or a refusal class writes a fragment under
src/ravel/data/<domain>/registration/. This script is the one writer that copies those
declarations into the shared registries:

  src/ravel/data/operation_signatures.json   operation signatures
  src/ravel/data/mode_descriptors.json       mode descriptors
  native/setup/toolchain-manifest.json       operations, unreleased operations and refusal classes
  src/ravel/data/knowledge/curation/<op>.json  curated use_when / do_not_use_when / examples
  src/ravel/data/backends/census.json        tool census rows
  src/ravel/data/knowledge/qualification.json  the census rows' qualification mirror

Each declaration is checked with the repository's own validators before anything is written:
signatures with ravel.validation.signature_conformance, descriptors with the capability-routing
descriptor reader (a source-bound operation needs its applicability predicate), manifest rows
against the merged manifest's groups. An operation is applied whole or not at all; a
nonconforming declaration is reported with its reason and left for its owner. A fragment that
declares a mode, census row or refusal class that is already registered with a different
implementation or content is a collision: the merge refuses and writes nothing. A census row
turns qualified only with a pinned qualification receipt, and a refusal retirement is applied
only when its pinned receipts exist. Running the script again changes nothing.

Usage: merge_registration.py [--root ROOT] [--domain NAME ...] [--check] [--json]
Exit status: 0 applied or already current; 1 --check found pending changes; 2 collision.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
SIGNATURES = 'src/ravel/data/operation_signatures.json'
DESCRIPTORS = 'src/ravel/data/mode_descriptors.json'
MANIFEST = 'native/setup/toolchain-manifest.json'
CURATION = 'src/ravel/data/knowledge/curation'
CENSUS = 'src/ravel/data/backends/census.json'
QUALIFICATION = 'src/ravel/data/knowledge/qualification.json'
CURATED_FIELDS = {'use_when', 'do_not_use_when', 'examples'}
CENSUS_STATUS = {'not-built': 'not_installed', 'not_installed': 'not_installed',
                 'built-unqualified': 'built_but_unqualified', 'built_but_unqualified': 'built_but_unqualified',
                 'qualified': 'qualified'}
REGISTERED_SCOPE = ('Registered from a source-owned registration fragment; '
                    'installation and qualification are pending until a receipt exists.')
# Fragment keys this script reads. Every other key is a handoff to another owner and is reported.
OPERATION_KEYS = {'operation_signatures', 'mode_descriptors', 'manifest', 'manifest_operations', 'curation',
                  'knowledge_curation'}
OTHER_KEYS = {'rows', 'refusal_classes', 'retire_refusals', 'retire'}
DESCRIPTIVE_KEYS = {'schema_version', 'kind', 'package', 'target', 'merge', 'handoff', 'description'}


class Collision(ValueError):
    """A fragment redefines a registered entry."""


def _read(root, relative):
    return json.loads((root / relative).read_text(encoding='utf-8'))


def _dump(value, indent, sort_keys=False, ensure_ascii=False):
    return json.dumps(value, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + '\n'


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fragments(root, domains=()):
    """Every registration fragment, in path order, optionally limited to named domains."""
    paths = sorted((root / 'src/ravel/data').glob('*/registration/*.json'))
    return [p for p in paths if not domains or p.parent.parent.name in domains]


def _signature_like(value):
    return isinstance(value, dict) and isinstance(value.get('implementation'), dict) and 'produces' in value


def operations(document):
    """The operations one fragment declares: {mode: {signature, descriptor, manifest, curation}}."""
    found = {}

    def slot(mode):
        return found.setdefault(mode, {'signature': None, 'descriptor': None, 'manifest': [], 'curation': None})

    for mode, entry in (document.get('operation_signatures') or {}).items():
        slot(mode)['signature'] = entry
    for key, entry in document.items():
        if key not in OPERATION_KEYS | OTHER_KEYS | DESCRIPTIVE_KEYS and _signature_like(entry):
            slot(key)['signature'] = entry
    for mode, entry in (document.get('mode_descriptors') or {}).items():
        slot(mode)['descriptor'] = entry
    rows = list((document.get('manifest') or {}).get('operations', [])) + list(document.get('manifest_operations') or [])
    if str(document.get('target', '')).endswith('toolchain-manifest.json'):
        rows += [r for r in document.get('operations', []) if isinstance(r, dict) and 'groups' in r]
    for row in rows:
        mode = row.get('mode') if isinstance(row, dict) else row
        slot(mode)['manifest'].append(row)
    curation = document.get('curation')
    if isinstance(curation, dict) and str(curation.get('id', '')).startswith('op:'):
        slot(curation['id'].removeprefix('op:'))['curation'] = curation
    elif curation is not None and len(found) == 1:
        next(iter(found.values()))['curation'] = curation
    for mode, entry in (document.get('knowledge_curation') or {}).items():
        slot(mode)['curation'] = entry
    return found


def _descriptor_errors(mode, descriptor, descriptors):
    from ravel.workflow.capability_routing import _descriptors
    document = dict(descriptors, modes={**descriptors['modes'], mode: descriptor})
    try:
        _descriptors(document, {mode})
    except ValueError as exc:
        return [f'{mode}: descriptor: {exc}']
    return []


def _manifest_errors(mode, rows, groups):
    errors = []
    for row in rows:
        if not isinstance(row, dict) or row.get('mode') != mode or not isinstance(row.get('groups'), list) \
                or not row['groups']:
            errors.append(f'{mode}: manifest operation row needs this mode and its installer groups')
            continue
        missing = sorted(set(row['groups']) - groups)
        if missing:
            errors.append(f'{mode}: manifest operation names undeclared groups: ' + ', '.join(missing))
    if len(rows) > 1:
        errors.append(f'{mode}: more than one manifest operation row')
    return errors


def _check_errors(mode, signature):
    from ravel.validation.claim_checks import conformance
    return [e for e in conformance(registry={mode: signature}) if e.endswith(f' on route {mode}')]


def _documented(root, mode):
    import re
    pattern = re.compile(r'(?<![\w-])' + re.escape(mode) + r'(?![\w-])')
    return any(pattern.search(p.read_text(encoding='utf-8')) for p in (root / 'docs').rglob('*.md'))


def _executor_errors(mode, signature):
    """A compute operation runs only through a production card that the executor table names for it."""
    from ravel.workflow import production_executor, role_registry
    table = production_executor.executors()
    rule = table['completeness_rule']
    compute = (signature.get('implementation', {}).get('kind') in rule['implementation_kinds']
               or set(rule['effects']) & set(signature.get('effects', [])))
    if not compute:
        return []
    role = table['operations'].get(mode)
    if role is None:
        return [f'{mode}: the executor table names no production card for this compute operation']
    cards = {c['id']: c for c in role_registry.all_cards()}
    if mode not in cards.get(role, {}).get('operations', []):
        return [f'{mode}: the production card {role} does not declare this operation']
    return []


def _knowledge_errors(root, mode, signature, record):
    """A science mode is curated and documented before it is offered (the knowledge check's rule)."""
    if signature.get('implementation', {}).get('kind') != 'science-mode':
        return []
    errors = []
    path = root / CURATION / (mode + '.json')
    fields = (record or {}).get('op') or (json.loads(path.read_text(encoding='utf-8')).get('op', {})
                                          if path.is_file() else {})
    if not fields.get('use_when') or not fields.get('do_not_use_when') or not fields.get('examples'):
        errors.append(f'{mode}: a science mode needs a curation record with use_when, do_not_use_when and examples')
    if not _documented(root, mode):
        errors.append(f'{mode}: no shipped document names this mode')
    return errors


def _curation_record(mode, curation):
    fields = curation.get('op', curation) if isinstance(curation, dict) else None
    if not isinstance(fields, dict) or not fields or set(fields) - CURATED_FIELDS:
        return None
    return {'id': 'op:' + mode, 'op': fields}


class Registries:
    """The shared registries of one tree, read once and written only when they change."""

    def __init__(self, root):
        from ravel.setup import manifest as mf
        self.root = root
        self.signatures = _read(root, SIGNATURES)
        self.descriptors = _read(root, DESCRIPTORS)
        self.manifest = _read(root, MANIFEST)
        self.census = _read(root, CENSUS)
        self.qualification = _read(root, QUALIFICATION)
        view = mf.view(root)
        self.groups = {g['id'] for g in view['groups']}
        self.held = mf.unreleased_groups(view)
        self.checks = {(g['id'], c['id']) for g in view['groups'] for c in g.get('checks', [])}
        self.curation = {}
        self.original = self.serialized()

    def serialized(self):
        out = {SIGNATURES: _dump(self.signatures, 1), DESCRIPTORS: _dump(self.descriptors, 1),
               MANIFEST: _dump(self.manifest, 1), CENSUS: _dump(self.census, 2, sort_keys=True),
               QUALIFICATION: _dump(self.qualification, 2, sort_keys=True, ensure_ascii=True)}
        for mode, record in self.curation.items():
            out[f'{CURATION}/{mode}.json'] = _dump(record, 1)
        return out

    def changes(self):
        current = self.serialized()
        changed = {}
        for relative, text in current.items():
            path = self.root / relative
            if not path.is_file() or path.read_text(encoding='utf-8') != text:
                changed[relative] = text
        return changed

    def write(self):
        changed = self.changes()
        for relative, text in changed.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        return sorted(changed)


def _apply_operation(reg, mode, op, source, report):
    registered = reg.signatures['operations'].get(mode)
    signature = op['signature']
    if registered is not None:
        declared = (signature or {}).get('implementation', {}).get('module')
        if declared is not None and registered.get('implementation', {}).get('module') != declared:
            raise Collision(f'{source}: {mode} is already registered with implementation '
                            f'{registered.get("implementation", {}).get("module")}, not {declared}')
        report['reflected'].append(mode)
        return
    from ravel.validation import signature_conformance
    errors = []
    if signature is None:
        errors.append(f'{mode}: the fragment declares no operation signature')
    else:
        errors += signature_conformance.entry_errors(mode, signature) or _check_errors(mode, signature)
    if op['descriptor'] is None:
        errors.append(f'{mode}: the fragment declares no mode descriptor')
    elif mode in reg.descriptors['modes']:
        errors.append(f'{mode}: a descriptor is registered without a signature')
    else:
        errors += _descriptor_errors(mode, op['descriptor'], reg.descriptors)
    errors += _manifest_errors(mode, op['manifest'], reg.groups)
    if any(row['mode'] == mode for row in reg.manifest['operations']):
        errors.append(f'{mode}: a manifest operation row is registered without a signature')
    record = _curation_record(mode, op['curation']) if op['curation'] is not None else None
    if signature is not None and not errors:
        errors += _executor_errors(mode, signature) + _knowledge_errors(reg.root, mode, signature, record)
    if errors:
        report['not_applied'].append({'mode': mode, 'reasons': errors})
        return
    reg.signatures['operations'][mode] = copy.deepcopy(signature)
    reg.descriptors['modes'][mode] = copy.deepcopy(op['descriptor'])
    for row in op['manifest']:
        reg.manifest['operations'].insert(_manifest_position(reg.manifest['operations'], mode),
                                          {'mode': mode, 'groups': list(row['groups'])})
        held = [g for g in row['groups'] if g in reg.held]
        if held:
            # A released main file carries no withheld list; a held fragment group starts one.
            reg.manifest.setdefault('unreleased', {'groups': [], 'operations': []})['operations'].append(
                {'mode': mode, 'groups': held})
    report['applied'].append(mode)
    if op['curation'] is not None:
        path = reg.root / CURATION / (mode + '.json')
        if record is None:
            report['not_applied'].append({'mode': mode, 'reasons': [
                f'{mode}: curation holds fields other than use_when, do_not_use_when and examples']})
        elif path.is_file() and json.loads(path.read_text(encoding='utf-8')) != record:
            raise Collision(f'{source}: {mode} already has a different curation record')
        else:
            reg.curation[mode] = record


def _manifest_position(rows, mode):
    """Science modes keep the dispatcher's order at the head of the operation list; others follow."""
    from ravel.workflow.science import MODES
    if mode not in MODES:
        return len(rows)
    earlier = set(MODES[:MODES.index(mode)])
    return max((i + 1 for i, row in enumerate(rows) if row['mode'] in earlier), default=0)


def _receipt_holds(root, receipt):
    if not isinstance(receipt, dict) or set(receipt) != {'path', 'sha256'}:
        return False
    path = root / receipt['path']
    return path.is_file() and _sha256(path) == receipt['sha256']


def _census_row(reg, row, source):
    status = CENSUS_STATUS.get(row.get('qualification'))
    errors = []
    if status is None:
        errors.append(f'{row.get("id")}: unknown qualification {row.get("qualification")!r}')
    elif status == 'qualified' and not _receipt_holds(reg.root, row.get('receipt')):
        errors.append(f'{row.get("id")}: a qualified census row needs a pinned qualification receipt')
    groups = row.get('installer_groups', [])
    if not groups or set(groups) - reg.groups:
        errors.append(f'{row.get("id")}: installer groups must be declared groups')
    checks = row.get('doctor_checks', [])
    if not checks or any(c.get('kind') != 'manifest' or (c.get('group'), c.get('check')) not in reg.checks
                         for c in checks):
        errors.append(f'{row.get("id")}: every doctor check must name a declared manifest check')
    return status, errors


def _apply_census(reg, document, source, report):
    tools = reg.census['tools']
    by_id = {r['id']: r for r in tools}
    mirror = {r['id']: r for r in reg.qualification['tools']}
    flipped = set()
    for row in document['rows']:
        status, errors = _census_row(reg, row, source)
        if errors:
            report['not_applied'].append({'census': row.get('id'), 'reasons': errors})
            continue
        # A census row that already lists this tool by name is its row: an excluded one becomes
        # installable, and one that already carries these groups and checks is current.
        target = next((r for r in tools if r['id'] != 'census-' + row['id']
                       and row['title'] in [t.strip() for t in r['title'].split(',')]), None)
        identity = target['id'] if target else 'census-' + row['id']
        current = by_id.get(identity)
        if current is not None and (target is None or target['status'] != 'excluded' and identity not in flipped):
            same = (set(row['installer_groups']) <= set(current['installer_groups'])
                    and all(c in current['doctor_checks'] for c in row['doctor_checks'])
                    and current['status'] == status)
            if not same:
                raise Collision(f'{source}: census row {identity} is already registered differently')
            report['reflected'].append(identity)
            continue
        if target is not None:
            groups = list(dict.fromkeys(target['installer_groups'] + row['installer_groups']))
            checks = [c for c in target['doctor_checks'] if c.get('kind') == 'manifest']
            checks += [c for c in row['doctor_checks'] if c not in checks]
            target.update(installer_groups=groups, doctor_checks=checks, status=status,
                          requirement='required_for_profile')
            mirror[identity].update(installer_groups=groups, status=status)
            flipped.add(identity)
            report['applied'].append(identity)
            continue
        new = {'id': identity, 'title': row['title'], 'installer_groups': list(row['installer_groups']),
               'doctor_checks': copy.deepcopy(row['doctor_checks']), 'status': status,
               'requirement': 'required_for_profile', 'summary': row.get('notes') or row['title'],
               'evidence_scope': REGISTERED_SCOPE,
               'source_locator': f'{source}#{row["id"]}', 'source_status': row['qualification']}
        tools.append(new)
        by_id[identity] = new
        mirror_row = {k: new[k] for k in ('evidence_scope', 'id', 'installer_groups', 'source_locator',
                                          'source_status', 'status', 'summary', 'title')}
        reg.qualification['tools'].append(mirror_row)
        mirror[identity] = mirror_row
        report['applied'].append(identity)


def _apply_refusals(reg, document, source, report):
    rows = reg.manifest['refusal_classes']
    by_id = {r['id']: r for r in rows}
    for row in document['refusal_classes']:
        identity = row.get('id')
        if identity in by_id:
            if by_id[identity] != row:
                raise Collision(f'{source}: refusal class {identity} is already registered differently')
            report['reflected'].append(identity)
            continue
        missing = sorted(set(row.get('groups', [])) - reg.groups)
        if not row.get('groups') or missing or not row.get('refused') or not row.get('would_make_it_possible'):
            report['not_applied'].append({'refusal_class': identity, 'reasons': [
                f'{identity}: a refusal class names what it refuses, its declared groups and what would lift it'
                + (' (undeclared: ' + ', '.join(missing) + ')' if missing else '')]})
            continue
        rows.append(copy.deepcopy(row))
        by_id[identity] = row
        report['applied'].append(identity)


def _apply_retirements(reg, document, source, report):
    rows = document.get('retire_refusals') or ([document['retire']] if document.get('retire') else [])
    for row in rows:
        identity = row.get('id')
        if not any(r['id'] == identity for r in reg.manifest['refusal_classes']):
            report['reflected'].append(identity)
            continue
        receipts = row.get('receipts')
        if not receipts or not all(_receipt_holds(reg.root, r) for r in receipts):
            report['not_applied'].append({'retirement': identity, 'reasons': [
                f'{identity}: retirement waits for its pinned installation and qualification receipts']})
            continue
        reg.manifest['refusal_classes'] = [r for r in reg.manifest['refusal_classes'] if r['id'] != identity]
        report['applied'].append('retire ' + identity)


def merge(root=REPO, domains=(), write=True):
    """Apply every fragment; return the per-fragment report and the changed registry paths."""
    root = Path(root)
    reg = Registries(root)
    reports = []
    for path in fragments(root, domains):
        source = path.relative_to(root).as_posix()
        document = json.loads(path.read_text(encoding='utf-8'))
        report = {'fragment': source, 'applied': [], 'reflected': [], 'not_applied': [], 'handoffs': []}
        for mode, op in operations(document).items():
            _apply_operation(reg, mode, op, source, report)
        if isinstance(document.get('rows'), list) and all(isinstance(r, dict) and 'qualification' in r
                                                          for r in document['rows']):
            _apply_census(reg, document, source, report)
        if isinstance(document.get('refusal_classes'), list) and all(
                isinstance(r, dict) for r in document['refusal_classes']):
            _apply_refusals(reg, document, source, report)
        if document.get('retire_refusals') or document.get('retire'):
            _apply_retirements(reg, document, source, report)
        signature_keys = {k for k, v in document.items() if _signature_like(v)}
        report['handoffs'] = sorted(set(document) - OPERATION_KEYS - OTHER_KEYS - DESCRIPTIVE_KEYS
                                    - signature_keys)
        reports.append(report)
    changed = reg.write() if write else sorted(reg.changes())
    return reports, changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', type=Path, default=REPO)
    parser.add_argument('--domain', action='append', default=[])
    parser.add_argument('--check', action='store_true', help='change nothing; exit 1 when a merge would change a registry')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        reports, changed = merge(args.root, args.domain, write=not args.check)
    except Collision as exc:
        print('collision: ' + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({'fragments': reports, 'changed': changed}, indent=1))
    else:
        for report in reports:
            print(report['fragment'])
            for key in ('applied', 'reflected'):
                if report[key]:
                    print(f'  {key}: ' + ', '.join(report[key]))
            for row in report['not_applied']:
                for reason in row['reasons']:
                    print('  not applied: ' + reason)
            if report['handoffs']:
                print('  handoffs for their owners: ' + ', '.join(report['handoffs']))
        print(('would change: ' if args.check else 'changed: ') + (', '.join(changed) or 'nothing'))
    return 1 if args.check and changed else 0


if __name__ == '__main__':
    sys.exit(main())
