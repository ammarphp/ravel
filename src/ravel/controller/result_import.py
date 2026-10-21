"""Controller import of supplied evidence, with the sink's original receipt chain.

Accepted custody means the controller retained these bytes. A source delivery's acceptance label
is inherited only from a verified sink receipt; external evidence and qualified receipts remain qualified.
Saved receipt hashes alone are not credentials: the originating protected journal must agree.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.workflow.graph_nodes import RecoveryHold
from .sink import common, receipts

IMPORT = 'result-import'
USE = 'result-import-use'
EXTERNAL = 'EXTERNAL UNVERIFIED EVIDENCE'
QUALIFIED = 'QUALIFIED SOURCE RESULT'


class ImportRefused(RecoveryHold):
    """A supplied result failed the named import check; no custody is granted."""


def _read(path, *, limit=common.HASH_LIMIT):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('evidence must be a regular file reached without links')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('evidence exceeds the import byte bound')
    return raw


def _member(root, name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or not name:
        raise ValueError('receipt member must be relative to the delivery directory')
    return root / path


def _receipt_path(source, explicit):
    if explicit is not None:
        return Path(explicit)
    # The sink writes one receipt at the root of its delivery, never into artifact documents.
    for parent in source.parents:
        if parent.name == common.DELIVERY_DIR or parent.name.startswith(common.DELIVERY_DIR + '.superseded-'):
            return parent / 'RECEIPT.json'
        candidate = parent / 'RECEIPT.json'
        if candidate.exists() or candidate.is_symlink():
            return candidate
    sidecar = source.with_name(source.name + '.receipt.json')
    return sidecar if sidecar.exists() or sidecar.is_symlink() else None


def _verify_receipt(path, source, raw):
    receipt_raw = _read(path, limit=common.TEXT_LIMIT)
    saved = receipts.verify_saved(json.loads(receipt_raw))
    if saved.get('schema_version') != common.RECEIPT_SCHEMA or saved.get('label') not in common.DELIVERY_LABELS:
        raise ValueError('unsupported sink receipt')
    delivery = saved['delivery']
    inventory_raw = _read(path.parent / 'INVENTORY.json', limit=common.TEXT_LIMIT)
    if hashlib.sha256(inventory_raw).hexdigest() != delivery['inventory_sha256']:
        raise ValueError('delivery inventory differs from the receipt')
    inventory = json.loads(inventory_raw)
    if (inventory['artifacts'] != delivery['artifacts']
            or inventory['receipt_reference'] != delivery['receipt_reference']):
        raise ValueError('inventory receipt reference or artifact population differs')
    sha = hashlib.sha256(raw).hexdigest()
    rows = [r for r in delivery['artifacts'] if r['sha256'] == sha and r['size'] == len(raw)]
    located = [r for r in rows if _member(path.parent, r['path']) == source]
    rows = located or rows
    if len(rows) != 1:
        raise ValueError('supplied bytes do not identify one delivered artifact')
    item = rows[0]
    if item.get('receipt_reference') != delivery['receipt_reference']:
        raise ValueError('artifact names another receipt reference')
    retained = {'receipt': receipt_raw, 'inventory': inventory_raw}
    sidecar = item.get('provenance_sidecar')
    if sidecar is not None:
        side_raw = _read(_member(path.parent, sidecar['path']), limit=common.TEXT_LIMIT)
        if hashlib.sha256(side_raw).hexdigest() != sidecar['sha256'] or len(side_raw) != sidecar['size']:
            raise ValueError('artifact provenance sidecar differs from the inventory')
        provenance = json.loads(side_raw)
        if (provenance['receipt_reference'] != delivery['receipt_reference']
                or provenance['source_sha256'] != item['source_sha256']):
            raise ValueError('artifact provenance sidecar names another source or receipt')
        retained['sidecar'] = side_raw
    # Reuse the store and sink receipt formats, including historical (superseded) deliveries.
    origin = common.module('store').store_for(Path(saved['run']))
    if origin.run_id != saved['run_id'] or origin.check_binding(Path(saved['run'])) or origin.verify():
        raise ValueError('originating controller custody does not verify')
    records = [r for r in common.records(origin, common.STORE_RECEIPT)
               if r.get('receipt_sha256') == saved['sha256']]
    if not records or not any(receipts.verify_saved(json.loads(origin.get_blob(r['receipt_blob']))) == saved
                              for r in records):
        raise ValueError('receipt is absent from the originating controller journal')
    return saved, item, retained


def import_result(store, source, sha256, *, receipt_path=None):
    """Import one entry-pinned supplied file, or raise a typed refusal before granting custody.

    A receipt can accompany a copied result via ``receipt_path`` or ``<file>.receipt.json``;
    in a sink delivery it is discovered at the delivery root. Missing receipts admit external
    evidence only. A present but unverifiable receipt is refused, including a forged rehash.
    """
    source = Path(source).absolute()
    try:
        run = common.run_dir(store)
        if run is None or store.check_binding(run) or store.verify():
            raise ImportRefused('result_import_run_invalid', 'the importing controller custody must verify')
        supplied = [r for row in common.records(store, 'supplied') for r in row.get('inputs', [])
                    if r.get('path') == str(source) and r.get('sha256') == sha256]
        if len(supplied) != 1:
            raise ImportRefused('result_import_not_supplied', 'import requires exactly one entry-pinned supplied file')
        raw = _read(source)
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ImportRefused('result_import_bytes_changed', 'supplied bytes differ from the entry pin')
        path = _receipt_path(source, receipt_path or supplied[0].get('receipt_path'))
        saved, item, retained = None, None, {}
        if path is not None and (path.exists() or path.is_symlink()):
            try:
                saved, item, retained = _verify_receipt(path, source, raw)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ImportRefused('result_import_receipt_invalid', str(exc)) from None
        verification = 'verified' if saved is not None else 'external_unverified'
        qualified = saved is None or saved.get('accepted') is not True or saved.get('qualified') is not False \
            or saved.get('label') != 'accepted' or item.get('qualified') is True
        provenance = {'source': str(source), 'sha256': sha256, 'verification': verification,
                      'qualified': qualified, 'receipt_sha256': saved['sha256'] if saved else None,
                      'origin_run': saved['run_id'] if saved else None,
                      'origin_label': saved['label'] if saved else None,
                      'origin_labels': saved.get('labels', []) if saved else [],
                      'artifact': item['artifact'] if item else None,
                      'receipt_path': str(path) if path is not None else None,
                      'verification_reason': 'sink_receipt_chain' if saved else 'receipt_missing',
                      'evidence_blobs': {name: store.put_blob(data) for name, data in retained.items()}}
        identity = common.digest(provenance)
        prior = [r for r in common.records(store, IMPORT) if r.get('identity') == identity]
        if prior:
            from .step import custody
            index = custody.custody_index(store)
            artifact = prior[-1]['custody_artifact']
            if custody._verify(index, artifact, run, set(), 0, store):
                raise ImportRefused('result_import_custody_invalid', 'the previously imported bytes changed')
            return index[artifact]
        step_id = 'import-' + identity[:32]
        relative = 'outputs/' + source.name
        from .step import custody
        rows = custody._copy(store, run_dir=run, step={'id': step_id}, attempt=1,
                             rows=[(relative, source, sha256, 'table')], card=None,
                             producer={'kind': 'supplied-result-import', 'identity': identity},
                             quantities={}, inputs_custody=[])
        record = {**provenance, 'identity': identity, 'step_id': step_id, 'path': relative,
                  'custody_artifact': rows[0]['artifact'], 'source_blob': store.put_blob(raw)}
        identifier = store.append(IMPORT, record)
        return custody.accept(store, rows, 'accepted', evidence={'import_record': identifier,
                              'verification': verification, 'qualified': qualified})[0]
    except ImportRefused as exc:
        store.append('result-import-refusal', {'source': str(source), 'sha256': sha256,
                                               'code': exc.reason, 'message': exc.would_make_possible})
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        refusal = ImportRefused('result_import_invalid', str(exc))
        store.append('result-import-refusal', {'source': str(source), 'sha256': sha256,
                                               'code': refusal.reason, 'message': str(exc)})
        raise refusal from None


def record_use(store, step, imports):
    """Retain the controller's exact consuming step; prose cannot erase this dependency."""
    for row in imports:
        use = {'step_id': step['id'], 'step_sha256': common.digest(step), 'artifact': row['artifact']}
        if not any(common.body(r) == use for r in common.records(store, USE)):
            store.append(USE, use)


def retain_inputs(store, step):
    """Keep imported parents on accepted outputs, across later plan revisions and restarts."""
    imported = {r['custody_artifact'] for r in common.records(store, IMPORT)}
    parents = {r['artifact'] for r in common.records(store, USE) if r.get('step_id') == step['id']
               and r.get('step_sha256') == common.digest(step) and r.get('artifact') in imported}
    if not parents:
        return
    index = {r['artifact']: r for r in common.records(store, 'custody')}
    for row in index.values():
        if row.get('step_id') != step['id'] or row.get('status') != 'accepted':
            continue
        before = set(row.get('inputs') or ())
        if not parents <= before:
            store.append('custody', {**common.body(row), 'inputs': sorted(before | parents)})


def delivery_labels(store, plan, classification, findings):
    """Qualify every dependent delivery, also following ordinary artifact custody lineage."""
    steps = {s['id']: s for s in (plan or {}).get('steps', [])}
    index = {r['artifact']: r for r in common.records(store, 'custody')}
    imports = {r['custody_artifact']: r for r in common.records(store, IMPORT)}
    uses = common.records(store, USE)
    shown = []
    for artifact, imported in imports.items():
        roots = {r['step_id'] for r in uses if r.get('artifact') == artifact and r.get('step_id') in steps
                 and r.get('step_sha256') == common.digest(steps[r['step_id']])}
        lineage = {artifact}
        changed = True
        while changed:
            previous = (len(roots), len(lineage))
            lineage.update(name for name, row in index.items() if set(row.get('inputs') or ()) & lineage)
            roots.update(row['step_id'] for name, row in index.items() if name in lineage)
            roots.update(name for name, row in steps.items() if set(row.get('depends_on') or ()) & roots)
            changed = previous != (len(roots), len(lineage))
        affected = [r for r in classification.get('declared', []) if r.get('step') in roots]
        if not affected:
            continue
        shown.append(deepcopy(imported))
        row = index.get(artifact, {})
        try:
            raw = _read(Path(common.run_dir(store)) / row['destination'])
            if row.get('status') != 'accepted' or hashlib.sha256(raw).hexdigest() != imported['sha256']:
                raise ValueError('imported evidence custody changed')
        except (OSError, ValueError, KeyError) as exc:
            findings.refuse('diagnostic', code='result_import_custody_invalid', message=str(exc))
        if imported['qualified']:
            external = imported['verification'] == 'external_unverified'
            label, code = (EXTERNAL, 'external_result_unverified') if external else (QUALIFIED, 'source_result_qualified')
            for row in affected:
                text = f"{imported['source']} ({imported['sha256']}): {imported['verification']}"
                findings.label(label, artifact=row['artifact'], text=text)
                findings.refuse('qualified', code=code, artifact=row['artifact'], message=text)
    return shown
