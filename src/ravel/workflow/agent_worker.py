"""Code-dispatched workers; durable supervisors outlive the graph runner.

The dispatcher, not the child, writes receipts, outcome labels and process
registrations. Transport adapters provide trusted launch descriptors. No raw
model result can create a work order, register a tool or satisfy a gate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid

from . import broker, sandbox
from .state_io import atomic_json, file_lock, read_json

RECEIPT_FIELDS = {'schema_version','kind','node_id','attempt','role','review_point_id','transport',
    'argv_sha256','cli_version','model','session_id','actor_id','attestation','isolation','pass_env_names',
    'request_sha256','knowledge','run_tree','broker','final_record','credited_outputs','usage','wall_seconds',
    'status','failure','transcript','started_utc','finished_utc','outcome','recovery','graph','framework_step',
    'rdj','completion_claimed_without_receipts','identity_sha256','epoch'}
# Receipt ``schema_version`` -> field set. Version 1 is the field set above, unchanged, so every
# stored receipt keeps its bytes and digest. Version 2 adds ``review_subject``: the review point's
# subject scope and digest, written when the dispatch carries one and bound into the receipt digest.
RECEIPT_VERSIONS = {1: frozenset(RECEIPT_FIELDS), 2: frozenset(RECEIPT_FIELDS | {'review_subject'})}
REVIEW_SUBJECT_FIELDS = {'scope','sha256'}
SPEC_FIELDS = {'schema_version','kind','node_id','attempt','role','transport_preference','inputs',
    'declared_outputs','budgets','final_record_schema','work_order','rdj_challenges','parent'}


PRODUCTION_MAP='production:'  # production_executor.worker_spec names its plan node this way

def _key(node_id, attempt):
    if type(node_id) is not str or not broker.ID.fullmatch(node_id) or type(attempt) is not int or not 1 <= attempt <= 1000:
        raise ValueError('invalid worker node/attempt')
    return broker.digest([node_id,attempt])


def workspace(rundir, node_id, attempt):
    _key(node_id,attempt)
    return broker.confined(broker.work_root(rundir),f'{node_id}/{attempt}')


def _record_path(rundir, node_id, attempt):
    return broker.custody(rundir)/(_key(node_id,attempt)+'.worker.json')


def capture_path(rundir, node_id, attempt, stream):
    """Supervisor custody for the child's ``stdout`` or ``stderr``: outside every sandbox write root,
    so the receipt inputs ``observe`` parses cannot be rewritten by the worker or its broker."""
    if stream not in ('stdout','stderr'):raise ValueError('unknown capture stream')
    return broker.custody(rundir)/(_key(node_id,attempt)+'.'+stream)


def _record(rundir, node_id, attempt):
    return read_json(_record_path(rundir,node_id,attempt))


def dispatched(rundir, node_id, attempt):
    """True once materialization wrote the dispatcher's custody record for this attempt."""
    return _record_path(rundir,node_id,attempt).exists()


def _final_producer(final):
    return type(final) is dict and type(final.get('completed')) is bool


REVIEW_DISPOSITIONS={'supported','not_supported','request_evidence','inconclusive'}


def _final_reviewer(final):
    findings=final.get('findings') if type(final) is dict else None
    return (type(final) is dict and type(final.get('completed')) is bool
            and final.get('disposition') in REVIEW_DISPOSITIONS and type(findings) is list
            and all(type(f) is dict and type(f.get('summary')) is str and f['summary'].strip() for f in findings))


# Code-owned final-record schemas; an undeclared schema is refused before materialization.
FINAL_SCHEMAS={'producer.v1':_final_producer,'reviewer.v1':_final_reviewer}


def _validate(spec):
    if type(spec) is not dict or set(spec) != SPEC_FIELDS or spec['schema_version'] != 1 or spec['kind'] != 'agent-worker-spec':
        raise ValueError('worker spec requires the exact versioned fields')
    _key(spec['node_id'],spec['attempt'])
    role=spec['role']
    if type(role) is not dict or set(role) != {'id','version','card_sha256'} or not broker.ID.fullmatch(role['id']):
        raise ValueError('worker role must be a pinned card')
    if type(role['card_sha256']) is not str or len(role['card_sha256']) != 64:
        raise ValueError('worker role card digest required')
    if type(spec['transport_preference']) is not list or not spec['transport_preference']:
        raise ValueError('transport preferences required')
    budget=spec['budgets']
    if type(budget) is not dict or set(budget) != {'max_turns','max_wall_seconds','max_broker_calls','max_cost_usd'}:
        raise ValueError('finite worker budgets required')
    for name in ('max_turns','max_wall_seconds','max_broker_calls'):
        if type(budget[name]) is not int or not 1 <= budget[name] <= 100000:
            raise ValueError('finite positive worker budgets required')
    cost=budget['max_cost_usd']
    if cost is not None and (type(cost) not in (int,float) or cost <= 0):
        raise ValueError('positive cost budget or null required')
    if type(spec['declared_outputs']) is not list or type(spec['inputs']) is not list:
        raise ValueError('worker input/output lists required')
    paths=[]
    for output in spec['declared_outputs']:
        if type(output) is not dict or set(output) != {'path','kind','required'} or type(output['required']) is not bool:
            raise ValueError('typed declared output required')
        p=Path(output['path'])
        if p.is_absolute() or '..' in p.parts or len(p.parts)<2 or p.parts[0] != 'outputs':
            raise ValueError('credit restricted to outputs/')
        paths.append(output['path'])
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate declared output')
    rdj=spec['rdj_challenges']
    if rdj is not None and (type(rdj) is not dict or set(rdj) != {'case_id','slot','payload_sha256'}
                           or not all(type(v) is str and v for v in rdj.values())):
        raise ValueError('RDJ binding requires case_id, slot, payload_sha256')
    parent=spec['parent']
    if type(parent) is not dict or set(parent)-{'review_subject'} != {'review_point_id','map_id','rca_ticket'}:
        raise ValueError('typed parent linkage required')
    if 'review_subject' in parent:
        _review_subject(parent['review_subject'])
        if type(parent['review_point_id']) is not str or not parent['review_point_id']:
            raise ValueError('a review subject requires its review point')
    if spec['final_record_schema'] not in FINAL_SCHEMAS:
        raise ValueError('final record schema must be one of '+', '.join(sorted(FINAL_SCHEMAS)))
    broker.digest(spec)
    return deepcopy(spec)


def _review_subject(value):
    if (type(value) is not dict or set(value) != REVIEW_SUBJECT_FIELDS or type(value['scope']) is not str
            or not value['scope'] or type(value['sha256']) is not str or len(value['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in value['sha256'])):
        raise ValueError('review subject requires its scope and sha256')
    return value


def receipt_version(receipt):
    """The receipt's schema version, after checking its field set against that version."""
    version=receipt.get('schema_version') if type(receipt) is dict else None
    if type(version) is not int or version not in RECEIPT_VERSIONS or set(receipt) != RECEIPT_VERSIONS[version]:
        raise ValueError('worker receipt schema changed')
    if version >= 2:_review_subject(receipt['review_subject'])
    return version


def _link_digest(receipt):
    """The canonical receipt projection the transcript row binds: every field except ``transcript``."""
    return broker.digest({k:v for k,v in receipt.items() if k != 'transcript'})


def _protected(rundir, spec, packet=None):
    """Digest of the worker's declared protected inputs: its input pins, work order and role packet.

    Each source is hashed where it lives now (``absent`` when gone). Writes elsewhere in
    the run, by ledgers, supervisors, graph roots or unrelated science, never void a
    worker; a change to one of its own declared sources does.
    """
    run=broker.ordinary(rundir);rows=[]
    pins=[item['pin'] for item in spec['inputs'] if type(item) is dict and type(item.get('pin')) is dict]
    if spec['work_order']:pins.append(spec['work_order'])
    for pin in pins:
        try:
            path=broker.locate(run,pin['path'])
            rows.append([pin['path'],broker.sha(path) if path.is_file() and not path.is_symlink() else 'absent'])
        except (OSError,ValueError):
            rows.append([pin['path'],'absent'])
    if packet is not None:
        root=Path(packet['path'])
        for path in [root/'manifest.json',*sorted((root/'artifacts').glob('*'))]:
            rows.append(['packet/'+path.relative_to(root).as_posix(),
                         broker.sha(path) if path.is_file() and not path.is_symlink() else 'absent'])
    return broker.digest(sorted(rows))


def _pin(rundir, value):
    path=broker.locate(rundir,value['path'])
    if not path.is_file() or broker.sha(path) != value['sha256']:
        raise ValueError('input/work-order pin changed')
    return path


def blind_roles():
    """Roles that see only a code-computed role packet (the graph's blind review roles)."""
    from .agent_graph import BLIND_GRAPH_ROLES
    return BLIND_GRAPH_ROLES


def _packet_binding(packet):
    if packet is None:return None
    if type(packet) is not dict or set(packet)!={'path','manifest_sha256'} or type(packet['path']) is not str:
        raise ValueError('role packet binding requires path and manifest_sha256')
    return {'path':str(broker.ordinary(packet['path'])),'manifest_sha256':packet['manifest_sha256']}


def _copy_packet(ws, packet, role):
    """Copy a verified role packet (manifest and indexed artifacts) into ``inputs/packet/``.

    The packet is the reviewed role's code-computed projection; nothing else of the
    producer reaches a blind worker's workspace.
    """
    from .review_context import _PacketIndex
    index=_PacketIndex(packet['path'],packet['manifest_sha256'])
    if index.manifest.get('role')!=role:raise ValueError('role packet belongs to a different role')
    copies=[]
    folder=ws/'inputs/packet/artifacts';folder.mkdir(parents=True)
    raw=(Path(packet['path'])/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=index.manifest_file_sha256:raise ValueError('role packet manifest changed')
    (ws/'inputs/packet/manifest.json').write_bytes(raw)
    for entry in index.entries.values():
        dest=ws/'inputs/packet'/entry['path'];dest.write_bytes(index.read(entry))
        copies.append(dest)
    index.finish()
    copies.append(ws/'inputs/packet/manifest.json')
    rows=[]
    for dest in copies:
        dest.chmod(0o400);rows.append({'path':dest.relative_to(ws).as_posix(),'sha256':broker.sha(dest)})
    return rows


def _effect_binding(effect):
    """``{identity_sha256, epoch, downstream}``: the ledger effect this worker closes.

    ``downstream`` is the absolute path where the supervisor writes the downstream
    document that the effect ledger's ``worker_receipt`` validator reads.
    """
    if effect is None:return None
    if (type(effect) is not dict or set(effect)!={'identity_sha256','epoch','downstream'}
            or type(effect['identity_sha256']) is not str or len(effect['identity_sha256'])!=64
            or type(effect['epoch']) is not dict or type(effect['epoch'].get('cancellation')) is not int
            or type(effect['downstream']) is not str or not Path(effect['downstream']).is_absolute()):
        raise ValueError('effect binding requires identity_sha256, epoch.cancellation and an absolute downstream path')
    return deepcopy(effect)


def materialize(rundir: Path, spec: dict, *, graph=None, framework_step=None, packet=None, protected=(), effect=None):
    """Create the workspace and custody record once; a blind role receives only its packet.

    ``protected`` names further roots (a graph root's state, checkpoints, events and
    effect store) that the denial probe must show unreadable. ``effect`` binds the
    receipt to the effect-ledger reservation it closes; a reattach keeps the first one.
    """
    spec=_validate(spec);run=broker.ordinary(rundir);packet=_packet_binding(packet);effect=_effect_binding(effect)
    protected=sorted({str(broker.ordinary(p)) for p in protected})
    blind=spec['role']['id'] in blind_roles()
    if blind and (packet is None or spec['inputs'] or spec['work_order'] is not None):
        raise ValueError('a blind role receives only its code-computed role packet; raw inputs and work orders are refused')
    ws=workspace(run,spec['node_id'],spec['attempt']);record_path=_record_path(run,spec['node_id'],spec['attempt'])
    with file_lock(record_path.with_suffix('.lock')):
        if record_path.exists():
            record=read_json(record_path)
            if (record['spec'] != spec or graph is not None and record['graph'] != graph
                    or packet is not None and record.get('packet') != packet
                    or protected and record.get('protected') != protected):
                raise ValueError('worker identity reused with changed specification')
            for pin in record['input_copies']:
                if broker.sha(broker.confined(ws,pin['path'])) != pin['sha256']:
                    raise ValueError('materialized input changed')
            # An earlier materialization does not carry the order requirement forward: the attempt is
            # dispatched again only under its plan node's sealed order as that order is now.
            _require_sealed_order(run,spec,_pinned_order(run,spec))
            return ws
        # The order is validated here, at dispatch and before anything is created: an order the
        # worker's broker would refuse is never accepted first and rejected after the supervisor started.
        order=read_json(_pin(run,spec['work_order'])) if spec['work_order'] else None
        if order is not None:
            if order.get('kind') != 'work-order' or order.get('node_id') != spec['node_id']:
                raise ValueError('work order belongs to a different node')
            if order.get('role', spec['role']['id']) != spec['role']['id']:
                raise ValueError('work order belongs to a different role')
        _require_sealed_order(run,spec,order)
        # Only the trusted dispatcher can create these directories and control files.
        ws.mkdir(parents=True,exist_ok=False)
        for folder in ('inputs','outputs','scratch','calls'):(ws/folder).mkdir()
        inputs=_copy_packet(ws,packet,spec['role']['id']) if packet is not None else []
        try:
            from .knowledge_broker import filter_inputs
            for item in filter_inputs(run, ws, spec):
                if type(item) is not dict or set(item) != {'pin','as'}:
                    raise ValueError('input copy requires pin and as')
                source=_pin(run,item['pin']);dest=broker.confined(ws,item['as'])
                if Path(item['as']).parts[0] != 'inputs' or Path(item['as']).parts[:2]==('inputs','packet'):
                    raise ValueError('input copy restricted to inputs/, outside the role packet')
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(source.read_bytes())
                if broker.sha(dest) != item['pin']['sha256']:raise ValueError('input changed during copy')
                dest.chmod(0o400);inputs.append({'path':item['as'],'sha256':broker.sha(dest)})
            # Work orders are handed in by the dispatcher; artifact contents do not construct one.
            if order is not None:
                atomic_json(ws/'inputs/work-order.json',order)
                inputs.append({'path':'inputs/work-order.json','sha256':broker.sha(ws/'inputs/work-order.json')})
            record={'spec':spec,'input_copies':inputs,'packet':packet,'protected':protected,'blind':blind,'effect':effect,
                    'run_tree_before':_protected(run,spec,packet),'graph':deepcopy(graph),
                    'framework_step':framework_step,'started_utc':broker.utc(),'started_epoch':time.time(),
                    'launch':None,'receipt':None,'execution':None}
            atomic_json(record_path,record)
        except Exception:
            # Preserve refused partial materialization for inspection; it grants no credit.
            raise
    return ws


def load_receipt(rundir: Path, node_id: str, attempt: int):
    run=broker.ordinary(rundir);record=_record(run,node_id,attempt)
    pin=record['receipt']
    if not pin:
        raise ValueError('worker has no receipt yet')
    path=_pin(run,pin)
    receipt=read_json(path)
    receipt_version(receipt)
    ws=workspace(run,node_id,attempt)
    for output in receipt['credited_outputs']:
        try:
            p=broker.confined(ws,output['path'])
            if not p.is_file() or broker.sha(p)!=output['sha256']:raise ValueError('changed')
        except (OSError,ValueError):raise ValueError('credited output changed after receipt') from None
    transcript=broker.locate(run,receipt['transcript']['path'])
    if broker.sha(transcript)!=receipt['transcript']['sha256']:
        raise ValueError('worker transcript changed after receipt')
    # Every field, ``review_subject`` included, is bound by the transcript's link digest.
    row=json.loads(transcript.read_text().splitlines()[0])
    if (row.get('ravel') or {}).get('receipt_sha256')!=_link_digest(receipt):
        raise ValueError('worker receipt digest does not match its transcript link')
    _ensure_published(run,node_id,attempt,receipt,pin)
    return receipt


def _append_public(path, value):
    path=broker.ordinary(path);path.parent.mkdir(parents=True,exist_ok=True)
    with file_lock(path.with_suffix('.lock')):
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())


def _prior(rundir, spec):
    for attempt in range(spec['attempt']-1,0,-1):
        try:r=load_receipt(rundir,spec['node_id'],attempt)
        except (OSError,ValueError):continue
        if r['status'] in {'failed','refused','voided'}:
            p=workspace(rundir,spec['node_id'],attempt)/'receipt.json'
            return {'node_id':spec['node_id'],'attempt':attempt,'path':broker.logical(rundir,p),'receipt_sha256':broker.sha(p)}
    return None


def _write_receipt(run, spec, receipt, record):
    ws=workspace(run,spec['node_id'],spec['attempt'])
    # A review dispatch writes version 2 with its subject; every other dispatch writes version 1.
    if 'review_subject' in spec['parent']:
        receipt['schema_version']=2;receipt['review_subject']=deepcopy(spec['parent']['review_subject'])
    receipt_version(receipt)
    # A mutual file hash is impossible: transcript links a documented canonical
    # receipt projection (all fields except its transcript digest).
    receipt['transcript']['link_digest_scope']='receipt_without_transcript'
    link=_link_digest(receipt)
    from .agent_audit import _record as prompt_record, _finish as finish_record
    row=prompt_record(receipt['transport'].get('id','unknown'),
        {'path':str(ws/'final.json'),'sha256':receipt['final_record']['sha256']},
        {'id':receipt['session_id'],'cli_version':receipt['cli_version']},
        {'id':f"{spec['node_id']}/{spec['attempt']}",'sidechain':False},1,receipt['started_utc'],
        json.dumps({'role':spec['role'],'work_order':spec['work_order'],'inputs':spec['inputs']},sort_keys=True))
    row=finish_record(row,{},{});row['ravel']={'node_id':spec['node_id'],'attempt':spec['attempt'],
        'role_id':spec['role']['id'],'receipt_sha256':link}
    (ws/'transcript.jsonl').write_text(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
    receipt['transcript']['sha256']=broker.sha(ws/'transcript.jsonl')
    if (ws/'receipt.json').exists():
        previous=broker.sha(ws/'receipt.json')
        history=broker.custody(run)/'receipt-versions'/ (previous+'.json')
        if not history.exists():atomic_json(history,read_json(ws/'receipt.json'))
    atomic_json(ws/'receipt.json',receipt)
    record['receipt']={'path':broker.logical(run,ws/'receipt.json'),'sha256':broker.sha(ws/'receipt.json')}
    atomic_json(_record_path(run,spec['node_id'],spec['attempt']),record)
    broker.append_ledger(run,'worker-receipts',{'pin':record['receipt'],'node_id':spec['node_id'],'attempt':spec['attempt']})
    _ensure_published(run,spec['node_id'],spec['attempt'],receipt,record['receipt'])
    return receipt


DOWNSTREAM_KIND='worker_receipt'


def _ensure_downstream(run, node_id, attempt, receipt, pin):
    """Write the downstream document the effect ledger reads after a runner crash; idempotent."""
    effect=_record(run,node_id,attempt).get('effect')
    if not effect:return
    document={'kind':'worker-downstream','identity_sha256':effect['identity_sha256'],'epoch':effect['epoch'],
              'rundir':str(run),'node_id':node_id,'attempt':attempt,'receipt':pin,'status':receipt['status']}
    target=Path(effect['downstream'])
    if target.is_file() and not target.is_symlink():
        try:
            if read_json(target)==document:return
        except ValueError:pass
    target.parent.mkdir(parents=True,exist_ok=True);atomic_json(target,document)


def validate_downstream(scope_root, saved, document):
    """Effect-ledger validator for ``worker_receipt``: the custody receipt, never the document's word.

    An ``ok`` receipt completes the effect with the receipt; ``failed``, ``refused`` and
    ``voided`` fail it; an ambiguous receipt or any mismatch leaves it open.
    """
    if document.get('kind')!='worker-downstream':raise ValueError('not a worker downstream document')
    run=broker.ordinary(document['rundir'])
    receipt=load_receipt(run,document['node_id'],document['attempt'])
    pin=_record(run,document['node_id'],document['attempt'])['receipt']
    if pin!=document['receipt'] or receipt['identity_sha256']!=saved['identity_sha256']:
        raise ValueError('worker receipt does not belong to this effect')
    if receipt['status']=='ok':return {'status':'completed','result':receipt}
    if receipt['status'] in {'failed','refused','voided'}:return {'status':'failed'}
    raise ValueError('ambiguous worker receipt needs explicit reconciliation')


def graph_node(name, *, rundir, spec, segment, to_state, packet=None, launch_spec=None, max_attempts=1):
    """A substrate ``worker`` effect node that dispatches one governed worker (``graph_nodes.agent``).

    ``spec(state)`` returns the versioned worker spec. The effect identity is the spec
    digest; the receipt carries that identity and the scope's cancellation epoch, and
    the supervisor writes the downstream document, so a runner crash after the receipt
    is closed by the ``worker_receipt`` validator instead of a second dispatch. An ``ok``
    receipt is the effect result; a failed receipt fails the effect and an ambiguous
    one stays ambiguous.
    """
    from . import effect_ledger
    from .agent_graph import AmbiguousCall, ReceiptedFailure
    from .graph_nodes import _meta, effect
    def downstream(state):
        s=_validate(spec(state))
        return {'kind':DOWNSTREAM_KIND,'path':'downstream/worker/'+broker.digest([name,s['node_id'],s['attempt']])+'.json'}
    def run(state, ident):
        meta=_meta(state);root=Path(meta['scope_root']);s=_validate(spec(state));ds=downstream(state)
        bound={'identity_sha256':effect_ledger.digest({**ident,'kind':'worker'}),
               'epoch':{'cancellation':effect_ledger.epoch(root)['cancellation']},'downstream':str(root/ds['path'])}
        # ``packet`` may be computed per state (a review item's projection).
        receipt=dispatch(Path(rundir),s,graph={'id':meta['graph_id'],'version':meta['version']},
                         framework_step=effect_ledger.framework_step(),packet=packet(state) if callable(packet) else packet,
                         protected=[str(root)],effect=bound,
                         **({'launch_spec':launch_spec} if launch_spec is not None else {}))
        if receipt['status']=='ok':return receipt
        if receipt['status']=='ambiguous':raise AmbiguousCall('worker requires explicit reconciliation')
        raise ReceiptedFailure('worker completion checks did not pass',{'status':'failed','worker_receipts':[
            {'node_id':receipt['node_id'],'attempt':receipt['attempt'],'status':receipt['status'],'sha256':broker.digest(receipt)}]})
    return effect(name,kind='worker',run=run,segment=segment,
                  identity=lambda state:{'worker_spec_sha256':broker.digest(_validate(spec(state)))},
                  to_state=to_state,downstream=downstream,max_attempts=max_attempts)


try:
    from . import effect_ledger as _effect_ledger
except ImportError:  # the effect ledger is optional for direct worker use
    pass
else:
    _effect_ledger.register_validator(DOWNSTREAM_KIND,validate_downstream)


def _ensure_published(run, node_id, attempt, receipt, pin):
    """Finish publication and downstream registration of a durable receipt; idempotent.

    A crash after the receipt's custody pointer and before or during publication is
    repaired by every reader of the receipt: each projected file is verified against
    the workspace and rewritten when absent or different, then RDJ registration runs
    once per receipt pin.
    """
    ws=workspace(run,node_id,attempt)
    _publish(run,ws,node_id,attempt)
    _ensure_downstream(run,node_id,attempt,receipt,pin)
    if receipt['rdj'] is not None and not any(r['record']['pin']==pin for r in broker.ledger(run,'rdj-registrations')):
        # The RDJ custody producer API is optional until that module is installed.
        try:from .rdj_custody import register_worker_receipt
        except ImportError:return
        register_worker_receipt(run,pin['path'])
        broker.append_ledger(run,'rdj-registrations',{'pin':pin,'node_id':node_id,'attempt':attempt})
    elif (receipt['schema_version']>=2 and receipt['rdj'] is None
          and not any(r['record']['pin']==pin for r in broker.ledger(run,'review-registrations'))):
        # A review receipt is registered with the label this dispatcher computed from the
        # transport's own verification; the review-credit reader takes the label from here.
        from .rdj_custody import WORKER_LABELS, register_worker_receipt
        label=receipt['attestation'] if receipt['attestation'] in WORKER_LABELS else 'self_attested'
        register_worker_receipt(run,pin['path'],verified_label=label)
        broker.append_ledger(run,'review-registrations',{'pin':pin,'node_id':node_id,'attempt':attempt,'label':label})


def _publish(run, ws, node_id, attempt):
    """Project the receipted workspace into ``<run>/agent-work/<node>/<attempt>/`` for run readers.

    The live workspace stays authoritative; the projection carries the same bytes, so
    every logical pin also verifies against it. ``agent-work`` is outside the run digest.
    Files already projected with the same bytes are left alone; every projected file
    is verified after the write.
    """
    target=broker.confined(run,f'{broker.WORK}/{node_id}/{attempt}')
    files=[ws/name for name in ('receipt.json','transcript.jsonl','final.json')]
    for folder in ('outputs','scratch','calls'):files+=sorted((ws/folder).rglob('*'))
    for source in files:
        if source.is_symlink() or not source.is_file():continue
        expected=broker.sha(source)
        dest=target/source.relative_to(ws)
        if dest.is_file() and not dest.is_symlink() and broker.sha(dest)==expected:continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        # A per-writer temporary: a reader repairing publication may race the supervisor;
        # both write the same bytes and each replacement is atomic.
        temporary=dest.with_name(f'{dest.name}.{uuid.uuid4().hex}.publish');temporary.write_bytes(source.read_bytes())
        os.replace(temporary,dest)
        if dest.is_symlink() or broker.sha(dest)!=expected:
            raise ValueError('published worker projection does not match its receipted workspace')


def _production_node(spec):
    """The plan node this worker produces for (the production executor's dispatch), or None."""
    identity=spec['parent'].get('map_id')
    return identity[len(PRODUCTION_MAP):] if type(identity) is str and identity.startswith(PRODUCTION_MAP) else None


def _pinned_order(run, spec):
    """The order the spec pins as its bytes are now, or None: no order, or one that changed or is gone."""
    if not spec['work_order']:return None
    try:return read_json(_pin(run,spec['work_order']))
    except (OSError,ValueError):return None


def _require_sealed_order(run, spec, order):
    """A plan node's production worker carries that node's sealed work order, checked at dispatch.

    Other workers (advisory, review, or the retained worker input format) may carry no order or a
    pinned one; they never hold production credit for a plan node."""
    node=_production_node(spec)
    if node is None:return
    from . import production_executor
    refusal='a production worker carries the sealed work order of its plan node; nothing was dispatched'
    try:sealed=production_executor.load_order(run,node)
    except (OSError,ValueError) as exc:raise ValueError(f'{refusal} ({exc})') from None
    if node!=spec['node_id'] or order is None or order!=sealed:raise ValueError(refusal)


def finish(rundir: Path, spec: dict, *, final=None, execution=None):
    spec=_validate(spec);run=broker.ordinary(rundir);path=_record_path(run,spec['node_id'],spec['attempt'])
    with file_lock(path.with_suffix('.lock')):
        record=read_json(path)
        if record['spec'] != spec:raise ValueError('worker spec differs from dispatcher custody')
        if record['receipt']:return load_receipt(run,spec['node_id'],spec['attempt'])
        ws=workspace(run,spec['node_id'],spec['attempt']);execution=deepcopy(execution or {})
        after=_protected(run,spec,record.get('packet'));unchanged=after==record['run_tree_before']
        credited=[];missing=[]
        check_receipts=[broker.verify_broker_receipt(run,{'path':r['record']['path'],'sha256':r['record']['sha256']},verify_outputs=False)
            for r in broker.ledger(run,'broker') if r['record']['node_id']==spec['node_id'] and r['record']['attempt']==spec['attempt']]
        # A declared output counts only through a broker receipt: an ok call whose output pin
        # names this path and these exact bytes. A file a native tool wrote is never credited.
        pinned={(pin['path'],pin['sha256']) for r in check_receipts if r['status']=='ok' for pin in r['output_pins']}
        for output in spec['declared_outputs']:
            try:
                p=broker.confined(ws,output['path'])
                if not p.is_file():raise ValueError('absent output')
                digest=broker.sha(p)
                if (broker.logical(run,p),digest) not in pinned:raise ValueError('output without a broker receipt')
                credited.append({**{k:v for k,v in output.items() if k!='required'},'sha256':digest})
            except (OSError,ValueError):
                if output['required']:missing.append(output['path'])
        input_checks=all(broker.confined(ws,p['path']).is_file() and broker.sha(broker.confined(ws,p['path']))==p['sha256'] for p in record['input_copies'])
        try:broker.digest(final)
        except (ValueError,TypeError):final=None
        valid_final=FINAL_SCHEMAS[spec['final_record_schema']](final)
        exit_code=execution.get('exit_status')
        order=read_json(ws/'inputs/work-order.json') if (ws/'inputs/work-order.json').exists() else None
        from .role_registry import resolve_self_checks
        required_checks=resolve_self_checks((order or {}).get('self_check',[]))
        validators={r['validator_id'] for r in check_receipts if r['derivation']=='registered_validator'
                    and r['status']=='ok' and r['exit_status']==0}
        # A plan node's production worker without its order has no requirement to meet and earns no credit.
        checks={'self_checks':all(c in validators for c in required_checks) and not (order is None and _production_node(spec)),'declared_outputs':not missing,'final_record':valid_final,'process_exit':exit_code==0,
                'run_tree':unchanged,'inputs_unchanged':input_checks,
                'budgets':not execution.get('budget_exhausted',False)}
        pending={r['record']['receipt_id'] for r in broker.ledger(run,'broker-reservations')
                 if r['record']['node_id']==spec['node_id'] and r['record']['attempt']==spec['attempt']} - {r['receipt_id'] for r in check_receipts}
        checks['broker_receipts']=not pending
        checks['broker_decision_clear']=not any(r['reply'].get('error',{}).get('code')=='decision_block'
            for r in check_receipts if r['reply'].get('error'))
        strict=all(checks.values())
        status='ok' if strict else 'failed';failure=None
        if not unchanged:
            status='voided';failure={'code':'run_modified','detail':'a declared protected input changed during worker execution'}
            broker.append_ledger(run,'findings',{'code':'run_modified','node_id':spec['node_id'],'attempt':spec['attempt'],'utc':broker.utc()})
        elif pending or execution.get('ambiguous') or type(exit_code) is int and exit_code<0:
            status='ambiguous';failure={'code':'process_error','detail':'worker termination needs explicit reconciliation'}
        elif execution.get('refusal'):
            status='refused';failure={'code':execution['refusal'],
                                      'detail':execution.get('refusal_detail','worker launch refused before child execution')}
            if execution.get('refusal_missing'):failure['missing']=list(execution['refusal_missing'])
        elif not strict:failure={'code':'schema_invalid' if not valid_final else 'process_error','detail':'computed completion checks did not pass'}
        claim=bool(type(final) is dict and final.get('completed') is True and (missing or not valid_final))
        if status!='ok':credited=[]
        if type(final) is dict:atomic_json(ws/'final.json',final)
        transport=execution.get('transport',{'id':'unknown','transport_kind':'unavailable','declaration_sha256':None,'probe_sha256':None})
        calls=[r['record'] for r in broker.ledger(run,'broker') if r['record']['node_id']==spec['node_id'] and r['record']['attempt']==spec['attempt']]
        receipt={'schema_version':1,'kind':'agent-worker-receipt','node_id':spec['node_id'],'attempt':spec['attempt'],
            'role':spec['role'],'review_point_id':spec['parent'].get('review_point_id'),
            'transport':transport,'argv_sha256':execution.get('argv_sha256'),'cli_version':execution.get('cli_version'),
            'model':execution.get('model',{'requested':None,'observed':None,'family':None,'effort':None}),
            'session_id':execution.get('session_id'),'actor_id':execution.get('actor_id'),
            'attestation':execution.get('attestation','self_attested'),
            'isolation':execution.get('isolation',{'profile':'unestablished','user_configuration_loaded':True,'evidence':{}}),
            'pass_env_names':execution.get('pass_env_names',[]),
            'request_sha256':broker.digest({'role':spec['role'],'work_order':spec['work_order'],'inputs':spec['inputs'],'budgets':spec['budgets']}),
            'knowledge':{'bundle_sha256':None,'served_ids':[],'used_ids':[]},
            'run_tree':{'before_sha256':record['run_tree_before'],'after_sha256':after,'modified':not unchanged},
            'broker':{'calls':len(calls),'calls_sha256':broker.digest(calls)},
            'final_record':{'path':'final.json','sha256':broker.sha(ws/'final.json') if (ws/'final.json').exists() else None,
                            'schema':spec['final_record_schema'],'valid':valid_final},
            'credited_outputs':credited,'usage':execution.get('usage',{'input_tokens':None,'output_tokens':None,'cost_usd':None,'reported':False}),
            'wall_seconds':max(0,time.time()-record['started_epoch']), 'status':status,'failure':failure,
            'transcript':{'path':broker.logical(run,ws/'transcript.jsonl'),'sha256':None},
            'started_utc':record['started_utc'],'finished_utc':broker.utc(),
            'outcome':{'status':status,'computed_checks':checks,'strict':strict,'label_source':'computed'},
            'recovery':_prior(run,spec) if status=='ok' else None,'graph':record['graph'],'framework_step':record['framework_step'],
            'rdj':spec['rdj_challenges'],'completion_claimed_without_receipts':claim,
            'identity_sha256':(record.get('effect') or {}).get('identity_sha256'),
            'epoch':(record.get('effect') or {}).get('epoch')}
        # Write every observed child-authored output, including uncredited files.
        for folder in ('outputs','scratch'):
            for p in sorted((ws/folder).rglob('*')):
                if p.is_file() and not p.is_symlink():
                    row={'path':broker.logical(run,p),'sha256':broker.sha(p),'session_id':receipt['session_id'],'utc':broker.utc()}
                    _append_public(run/'agent-audit/writes.jsonl',row);broker.append_ledger(run,'writes',row)
        if claim:broker.append_ledger(run,'completion-claims',{'node_id':spec['node_id'],'attempt':spec['attempt'],'cell':{
            'role':spec['role']['id'],'transport':transport.get('id'),'model':receipt['model'].get('observed'),
            'effort':receipt['model'].get('effort')},'completion_claimed_without_receipts':True})
        return _write_receipt(run,spec,receipt,record)


def completion_cells(rundir):
    cells={}
    for row in broker.ledger(rundir,'completion-claims'):
        record=row['record'];key=broker.digest(record['cell'])
        cells.setdefault(key,{**record['cell'],'completion_claimed_without_receipts':0})['completion_claimed_without_receipts']+=1
    return [cells[k] for k in sorted(cells)]


def findings(rundir):return [r['record'] for r in broker.ledger(rundir,'findings')]


def processes(rundir):
    path=broker.custody(rundir)/'processes.json'
    return read_json(path) if path.exists() else []


def _process_record(rundir, value):
    root=broker.custody(rundir)
    with file_lock(root/'processes.lock'):
        rows=read_json(root/'processes.json') if (root/'processes.json').exists() else []
        rows=[r for r in rows if (r['node_id'],r['attempt'])!=(value['node_id'],value['attempt'])]+[value]
        atomic_json(root/'processes.json',rows)
        public=Path(rundir)/'agent-work/processes.json'
        with file_lock(Path(rundir)/'agent-work/processes.lock'):
            registry=read_json(public) if public.exists() else {'schema_version':1,'kind':'process-registry','processes':[]}
            if type(registry) is not dict:raise ValueError('process registry requires the substrate record shape')
            entries=[p for p in registry['processes'] if not p.get('id','').startswith('worker-supervisor:')]
            # The control nonce stays in custody; the public run-tree registry never carries it.
            entries += [{**{k:v for k,v in p.items() if k!='token'},'id':'worker-supervisor:'+p['node_id']+'/'+str(p['attempt']),
                         'role':'worker-supervisor','state':'running' if p['status'] in ('running', 'starting') else 'exited'} for p in rows]
            registry['processes']=entries;atomic_json(public,registry)


def _control(path, token, action):
    return broker.socket_call(path,{'token':token,'action':action})


def bind_season(rundir, node_id, attempt, *, actor_id, season):
    """Trusted hypothesis-board seam: phase data comes from its replayed board, never post prose."""
    if type(actor_id) is not str or not actor_id or season.get('phase') not in {'sealed','open'} or type(season.get('participants')) is not list:
        raise ValueError('typed board season required')
    path=_record_path(rundir,node_id,attempt)
    with file_lock(path.with_suffix('.lock')):
        record=read_json(path)
        if record['launch'] is not None:raise ValueError('bind the initial sealed phase before launch')
        record['season']={'actor_id':actor_id,'season':deepcopy(season)}
        atomic_json(path,record)


# The account's login name. Claude Code reads its stored login with ``security find-generic-password
# -a $USER``; without USER and LOGNAME it reports "Not logged in". A Claude-family CLI worker names
# them in ``pass_env_names``; the supervisor sets them from the password database, never the parent.
ACCOUNT_ENV=('LOGNAME','USER')
RESERVED_ENV={'PATH','HOME','TMPDIR','PYTHONPATH','PYTHONDONTWRITEBYTECODE','RAVEL_STATE_DIR','RAVEL_WORK_ROOT',
              'RAVEL_BROKER_SOCKET',*ACCOUNT_ENV}


def _claude_cli(descriptor):
    transport=descriptor.get('transport') or {}
    return transport.get('transport_kind')=='cli-worker' and transport.get('agent')=='claude'


def _pass_env_names(descriptor):
    names=descriptor.get('pass_env_names',[])
    allowed=set(ACCOUNT_ENV) if _claude_cli(descriptor) else set()
    if (type(names) is not list or len(names)>64 or len(set(names))!=len(names)
            or not all(type(n) is str and broker.ENV_NAME.fullmatch(n) and (n not in RESERVED_ENV or n in allowed)
                       for n in names)):
        raise ValueError('pass_env_names must be distinct environment names outside the reserved set')
    return names


def _account_env(descriptor):
    """USER and LOGNAME for the names the descriptor lists, from the password database."""
    import pwd
    account=pwd.getpwuid(os.getuid()).pw_name
    return {name:account for name in descriptor.get('pass_env_names',[]) if name in ACCOUNT_ENV}


def _cli_launch(descriptor, ws):
    """The CLI adapter's launch facts carried in the trusted descriptor's ``transport`` row.

    Returns ``(stdin path or None, CLI home or None, network, launch environment)``. The
    prompt file must still match its recorded digest; launch environment values are paths
    inside the CLI home, the keychain home (see ``_user_home``) or the worker's own scratch,
    for a CLI's temporary directory, and replace only names the adapter declared.
    """
    transport=descriptor.get('transport') or {}
    if transport.get('transport_kind')!='cli-worker':return None,None,None,{}
    stdin=transport.get('stdin');home=transport.get('cli_home');env=transport.get('launch_env') or {}
    if stdin is not None and (not Path(stdin['path']).is_file() or broker.sha(Path(stdin['path']))!=stdin['sha256']):
        raise ValueError('worker prompt changed after the launch was prepared')
    home=broker.ordinary(home) if home else None
    scratch=broker.ordinary(ws/'scratch');user_home=_user_home(descriptor,ws)
    for name,value in env.items():
        inside=broker.ordinary(value)
        if (not broker.ENV_NAME.fullmatch(name)
                or not (home is not None and inside.is_relative_to(home) or inside.is_relative_to(scratch)
                        or user_home is not None and inside==user_home)):
            raise ValueError('launch environment values must be paths inside the CLI home or the worker scratch')
    return (Path(stdin['path']) if stdin else None),home,transport.get('network'),dict(env)


def _user_home(descriptor, ws):
    """The adapter's keychain home (``sandbox.user_home_for``) for a Claude-family CLI worker, or None."""
    transport=descriptor.get('transport') or {}
    value=transport.get('user_home') if transport.get('transport_kind')=='cli-worker' else None
    if value is None:return None
    if broker.ordinary(value)!=sandbox.user_home_for(ws):
        raise ValueError('the keychain home must be the workspace\'s own <attempt>.home')
    return broker.ordinary(value)


def launch(rundir: Path, spec: dict, *, launch_spec=None, wait=True, packet=None, protected=(), effect=None):
    """Start exactly one supervisor. An uncertain launch is never blindly repeated."""
    spec=_validate(spec);run=broker.ordinary(rundir);ws=materialize(run,spec,packet=packet,protected=protected,effect=effect)
    path=_record_path(run,spec['node_id'],spec['attempt'])
    # A stop refuses every new launch; under a drain an attempt whose supervisor already
    # started is left to finish, so reattaching to it does not end it.
    stopping=broker.stop_mode(run)
    if stopping=='cancel' or stopping=='drain' and read_json(path)['launch'] is None:
        return finish(run,spec,execution={'refusal':'stop_requested'})
    if sandbox.available() is None:
        return finish(run,spec,execution={'refusal':'sandbox_unavailable'})
    if launch_spec is None:
        # The transport layer owns this adapter; core never falls back to an unsandboxed oneshot.
        try:
            adapter=importlib.import_module('ravel.workflow.transports.cli_worker')
            prepare=adapter.prepare_launch
        except (ImportError,AttributeError):
            return finish(run,spec,execution={'refusal':'transport_adapter_unavailable'})
        try:launch_spec=prepare(run,spec,ws)
        except adapter.LaunchRefused as exc:
            # Named missing items; nothing started and no other route is tried.
            return finish(run,spec,execution={'refusal':'transport_refused','refusal_detail':str(exc),
                                              'refusal_missing':list(exc.missing)})
    descriptor=deepcopy(launch_spec)
    if (type(descriptor) is not dict or not descriptor.get('argv')
            or not all(type(x) is str for x in descriptor['argv'])
            or not Path(descriptor['argv'][0]).is_absolute()
            or set(descriptor)-{'argv','transport','model','pass_env_names','read_paths','allowed_actions','forbidden_sources'}):
        raise ValueError('trusted launch descriptor required')
    pass_env=_pass_env_names(descriptor)
    from . import gate_wiring
    with gate_wiring.steering_dispatch(run, spec['node_id']), file_lock(path.with_suffix('.lock')):
        record=read_json(path)
        if record['receipt']:return load_receipt(run,spec['node_id'],spec['attempt'])
        if record['launch'] is None:
            token=uuid.uuid4().hex
            descriptor_path=broker.custody(run)/(_key(spec['node_id'],spec['attempt'])+'.launch.json')
            atomic_json(descriptor_path,descriptor)
            record['launch']={'token':token,'descriptor_sha256':broker.sha(descriptor_path),'pid':None,
                              'control_socket':None,'status':'reserved'}
            atomic_json(path,record)
            # The supervisor's environment has no user config/secrets by default.
            env={'PATH':'/usr/bin:/bin','HOME':str(ws/'scratch'), 'RAVEL_STATE_DIR':str(broker.custody(run).parents[1]),
                 'RAVEL_WORK_ROOT':str(broker.work_root(run).parent),
                 'PYTHONPATH':str(Path(__file__).resolve().parents[2]), 'PYTHONDONTWRITEBYTECODE':'1',
                 'TMPDIR':str(broker.runtime_dir())}
            # Declared transport variables only; their values are never recorded.
            env.update({name:os.environ[name] for name in pass_env if name in os.environ and name not in ACCOUNT_ENV})
            env.update(_account_env(descriptor))
            # A test lock domain crosses the supervisor boundary only as this process's validated
            # grant; ordinary execution keeps the fixed machine custody domain.
            from . import machine_lease
            env.update(machine_lease.child_env())
            proc=subprocess.Popen([sys.executable,'-B','-m','ravel.workflow.agent_worker','supervise',
                '--rundir',str(run),'--node',spec['node_id'],'--attempt',str(spec['attempt'])],
                env=env,cwd=ws,start_new_session=True,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            record['launch']['pid']=proc.pid;record['launch']['status']='started'
            atomic_json(path,record)
            _process_record(run, {'node_id': spec['node_id'], 'attempt': spec['attempt'], 'pid': proc.pid,
                'pgid': proc.pid, 'status': 'starting', 'control_socket': None, 'token': token,
                'child_pid': None, 'child_pgid': None, 'verified_gone': False, 'termination': None})
    # Reattach through custody+nonce. We do not look up or signal a process by name.
    if not wait:return {'status':'running','node_id':spec['node_id'],'attempt':spec['attempt']}
    deadline=time.monotonic()+spec['budgets']['max_wall_seconds']+15
    while time.monotonic()<deadline:
        record=read_json(path)
        if record['receipt']:return load_receipt(run,spec['node_id'],spec['attempt'])
        if record['launch'].get('control_socket'):
            try:_control(record['launch']['control_socket'],record['launch']['token'],'status')
            except (OSError,ValueError):pass
        time.sleep(.05)
    return finish(run,spec,execution={'ambiguous':True})


def supervise(rundir: Path, node_id: str, attempt: int):
    """Own the broker and child process until durable completion; runner is expendable."""
    run=broker.ordinary(rundir);path=_record_path(run,node_id,attempt);record=read_json(path);spec=record['spec']
    ws=workspace(run,node_id,attempt)
    descriptor_path=broker.custody(run)/(_key(node_id,attempt)+'.launch.json')
    if broker.sha(descriptor_path)!=record['launch']['descriptor_sha256']:raise ValueError('launch descriptor changed')
    descriptor=read_json(descriptor_path)
    control_path=broker.runtime_dir()/('rv-control-'+uuid.uuid4().hex[:16]+'.sock')
    token=record['launch']['token'];stop_event=threading.Event()
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            raw=self.rfile.readline(broker.MAX_MESSAGE+1)
            value=json.loads(raw)
            if value.get('token')!=token:reply={'status':'refused'}
            else:
                if value.get('action')=='stop':stop_event.set()
                reply={'status':'stopping' if stop_event.is_set() else 'running','token':token}
            self.wfile.write((json.dumps(reply)+'\n').encode())
    try:
        server=socketserver.ThreadingUnixStreamServer(str(control_path),Handler)
    except OSError:
        execution={'refusal':'ipc_unavailable'}
        finish(run,spec,execution=execution)
        _process_record(run,{'node_id':node_id,'attempt':attempt,'pgid':os.getpgrp(),'pid':os.getpid(),
            'control_socket':str(control_path),'token':token,'status':'finished','child_pgid':None,'verified_gone':True})
        return
    os.chmod(control_path,0o600)
    # A kernel `stop --now` signals this group: stop the child and still write the receipt.
    signal.signal(signal.SIGTERM,lambda *_:stop_event.set())
    server.daemon_threads=True;thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    with file_lock(path.with_suffix('.lock')):
        record=read_json(path);record['launch']['control_socket']=str(control_path);atomic_json(path,record)
    registration={'node_id':node_id,'attempt':attempt,'pgid':os.getpgrp(),'pid':os.getpid(),
                  'control_socket':str(control_path),'token':token,'status':'running','child_pid':None,
                  'child_pgid':None,'verified_gone':False,'termination':None}
    _process_record(run,registration)
    execution={'transport':descriptor.get('transport',{'id':'stub','transport_kind':'stub'}),
               'model':descriptor.get('model',{'requested':None,'observed':None,'family':None,'effort':None}),
               'argv_sha256':broker.digest(descriptor['argv'])}
    final=None;child=None
    try:
        pass_env=_pass_env_names(descriptor);execution['pass_env_names']=pass_env
        runtime=sandbox.runtime_paths(descriptor['argv'])
        reads=descriptor.get('read_paths',runtime)
        protected=sandbox.protected_roots(run)+list(record.get('protected') or [])
        allowed_actions=descriptor.get('allowed_actions',['read','write'])
        # Declared read roots may only narrow the tool runtime; no unrelated tree is readable.
        if any(not any(broker.ordinary(p).is_relative_to(broker.ordinary(r)) for r in runtime) for p in reads):
            raise sandbox.ReadRootRefused('read roots must lie inside the tool runtime paths')
        stdin_path,cli_home,network,launch_env=_cli_launch(descriptor,ws);keychain_home=_user_home(descriptor,ws)
        verified=set((descriptor.get('transport') or {}).get('verified_env') or [])
        # A blind role uses read and write on its packet copy and its own outputs only.
        if record.get('blind') and not set(allowed_actions)<={'read','write'}:raise _BlindRefused('blind_action_refused')
        # The denial probe runs the exact profile the child launches with: its CLI home and network.
        evidence=sandbox.probe(ws,forbidden=_denied_probe_targets(run,path,record),read_paths=reads,protected=protected,
                               home=cli_home,network=network,keychain_home=keychain_home)
        # Names whose values the adapter replaced or verified (a fresh CLI home, a login-only
        # configuration directory) are not the account's configuration.
        execution['isolation']={'profile':'ravel-sandbox',
            'user_configuration_loaded':sandbox.user_configuration_exposed(reads,[n for n in pass_env if n not in verified]),
            'evidence':{**evidence,'cli_home':bool(cli_home)}}
        from .tool_gate import production_broker
        # The shared gate: allowlist, knowledge ops and argument membership all come from the pinned toolbelt.
        tool_broker=production_broker(run,ws,tools=_worker_tools(descriptor,ws,allowed_actions),role=spec['role']['id'],
            node_id=node_id,attempt=attempt,max_calls=spec['budgets']['max_broker_calls'],
            graph_id=(record.get('graph') or {}).get('id'),forbidden_sources=descriptor.get('forbidden_sources',[]),
            actor_id=record.get('season',{}).get('actor_id'),season=record.get('season',{}).get('season'))
        with broker.serve(tool_broker):
            argv=sandbox.command(ws,descriptor['argv'],read_paths=reads,broker_socket=tool_broker.socket_path,protected=protected,
                                 home=cli_home,network=network,keychain_home=keychain_home)
            env={'PATH':'/usr/bin:/bin','HOME':str(ws/'scratch'),'TMPDIR':str(ws/'scratch'),
                 'RAVEL_BROKER_SOCKET':('/tmp/ravel-broker.sock' if sandbox.available()=='linux' else str(tool_broker.socket_path)),'PYTHONDONTWRITEBYTECODE':'1'}
            env.update({name:os.environ[name] for name in pass_env if name in os.environ and name not in ACCOUNT_ENV})
            env.update(_account_env(descriptor))
            env.update(launch_env)
            if stop_event.is_set():raise _StopBeforeLaunch()
            # stdout and stderr reach supervisor custody through pipes, never a worker-writable file.
            captures={name:capture_path(run,node_id,attempt,name) for name in ('stdout','stderr')}
            with (stdin_path.open('rb') if stdin_path else open(os.devnull,'rb')) as source:
                from . import gate_wiring
                with gate_wiring.steering_dispatch(run, node_id):
                    child=subprocess.Popen(argv,cwd=ws,env=env,start_new_session=True,
                                       stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                # The child leads its own session: its pid is its process group id.
                    registration.update(child_pid=child.pid,child_pgid=os.getpgid(child.pid));_process_record(run,registration)
                counted={'stdout':0,'stderr':0}
                readers=[threading.Thread(target=_capture,args=(stream,captures[name],counted,name),daemon=True)
                         for name,stream in (('stdout',child.stdout),('stderr',child.stderr))]
                for reader in readers:reader.start()
                deadline=time.monotonic()+spec['budgets']['max_wall_seconds']
                while child.poll() is None:
                    if (stop_event.is_set() or time.monotonic()>deadline
                            or counted['stdout']>broker.MAX_MESSAGE or counted['stderr']>broker.MAX_MESSAGE):
                        registration['termination']=_terminate_child(child,registration['child_pgid'])
                        execution['ambiguous']=True
                        execution['budget_exhausted']=not stop_event.is_set()
                        break
                    time.sleep(.025)
                for reader in readers:reader.join(timeout=5)
            execution['exit_status']=child.wait(timeout=5)
            stdout=captures['stdout']
            if (descriptor.get('transport') or {}).get('transport_kind')=='cli-worker':
                # The CLI adapter parses its envelope; the session, usage and limits are observed, never assumed.
                adapter=importlib.import_module('ravel.workflow.transports.cli_worker')
                observed=adapter.observe(run,descriptor,ws,spec,execution)
                final=observed.pop('final');execution.update(observed)
            elif stdout.stat().st_size<=broker.MAX_MESSAGE:
                try:
                    envelope=json.loads(stdout.read_text())
                    final=envelope.get('final',envelope)
                    # The transport adapter must supply a verified envelope; no attestation
                    # is inferred from a model-provided session string.
                except ValueError:pass
    except sandbox.SandboxUnavailable as exc:
        execution['refusal']=str(exc)
    except sandbox.ReadRootRefused:
        execution['refusal']='read_root_refused'
    except _BlindRefused as exc:
        execution['refusal']=str(exc)
    except _StopBeforeLaunch:
        execution['refusal']='stop_requested'
    except Exception:
        execution['ambiguous']=child is not None
        if child is None:execution['refusal']='process_error'
    finally:
        if child is not None and child.poll() is None:
            registration['termination']=_terminate_child(child,registration['child_pgid'])
        elif child is not None and registration['termination'] is None and (child.returncode or 0)<0:
            # Another owner (a kernel `stop --now`) signalled the child's group.
            registration['termination']={'child_pgid':registration['child_pgid'],'signals':[],
                'observed_exit_signal':signal.Signals(-child.returncode).name}
            execution['ambiguous']=True
        if registration['termination'] is not None:
            registration['termination']['gone']=not _group_alive(registration['child_pgid'])
        # Verify the child group is gone before any completion is credited.
        gone=child is None or not _group_alive(registration['child_pgid'])
        if not gone:execution['ambiguous']=True
        transport=descriptor.get('transport') or {}
        if gone and (transport.get('cli_home_owned') or transport.get('user_home')):
            # The per-worker CLI home holds copied login material, and the keychain home links
            # the login keychain; neither outlives the child.
            importlib.import_module('ravel.workflow.transports.cli_worker').remove_home(ws,descriptor)
        finish(run,spec,final=final,execution=execution)
        registration.update(status='finished',verified_gone=gone)
        _process_record(run,registration)
        server.shutdown();server.server_close();thread.join(timeout=2);control_path.unlink(missing_ok=True)


def _capture(stream, path, counted, name):
    """Copy one child pipe into custody, keeping at most one byte past the message bound."""
    with open(path,'wb') as out:
        while True:
            chunk=stream.read(65536)
            if not chunk:break
            kept=max(0,broker.MAX_MESSAGE+1-counted[name])
            if kept:out.write(chunk[:kept])
            counted[name]+=len(chunk)
        out.flush();os.fsync(out.fileno())


def _worker_tools(descriptor, ws, allowed_actions):
    """The toolbelt the broker enforces: the CLI adapter's pinned ``inputs/toolbelt.json``, or for a
    descriptor without one, the workspace tools its allowlist names."""
    from . import toolbelt
    pin=(descriptor.get('transport') or {}).get('toolbelt')
    if pin is None:
        return toolbelt.workspace_tools([a for a in allowed_actions if a in ('read','write')])
    document=read_json(ws/'inputs'/'toolbelt.json')
    if (document.get('kind')!='toolbelt' or toolbelt.manifest_sha256(document)!=document.get('manifest_sha256')
            or document['manifest_sha256']!=pin['manifest_sha256']):
        raise ValueError('worker toolbelt differs from the pinned launch toolbelt')
    if sorted(allowed_actions)!=toolbelt.allowed_actions(document['tools']):
        raise ValueError('launch allowlist differs from the pinned toolbelt')
    return document['tools']


def _denied_probe_targets(run, record_path, record=None):
    """Every location the child must not read, by kind.

    Its custody record and the custody ledgers (receipts, broker calls, events), the
    run tree and published outputs, peer workspaces, the state store, and each
    protected graph root's state, checkpoints, call receipts, effect store and
    attempt results. A canary stands in for a location with no file yet.
    """
    def canary(folder):
        target=folder/'.sandbox-canary'
        if not target.exists():
            folder.mkdir(parents=True,exist_ok=True);target.write_text('denied')
        return target
    custody=broker.custody(run)
    targets=[record_path,canary(run/broker.WORK),canary(broker.work_root(run)),canary(custody),
             canary(custody.parents[1])]
    targets+=[custody/(name+'.jsonl') for name in ('worker-receipts','broker','broker-reservations','writes')
              if (custody/(name+'.jsonl')).is_file()]
    for root in (record or {}).get('protected') or ():
        root=Path(root)
        targets+=[root/name for name in ('graph_state.json','state.json') if (root/name).is_file()]
        for folder in ('framework','calls','effects','attempts','requests'):
            found=next((p for p in sorted((root/folder).rglob('*')) if p.is_file() and not p.is_symlink()),None) if (root/folder).is_dir() else None
            if found is not None:targets.append(found)
    return targets


class _StopBeforeLaunch(Exception):
    pass


class _BlindRefused(Exception):
    pass


def _group_alive(pgid):
    try:os.killpg(pgid,0)
    except ProcessLookupError:return False
    except PermissionError:return True
    return True


def _terminate_child(child, pgid, *, grace=2.0):
    """SIGTERM, then SIGKILL, the child's own process group within the wait; reap it."""
    signals=[]
    for name,wait in (('SIGTERM',grace),('SIGKILL',5.0)):
        if not _group_alive(pgid):break
        try:os.killpg(pgid,getattr(signal,name))
        except ProcessLookupError:break
        signals.append(name)
        try:child.wait(timeout=wait)
        except subprocess.TimeoutExpired:continue
        end=time.monotonic()+wait
        while _group_alive(pgid) and time.monotonic()<end:time.sleep(.02)
    return {'child_pgid':pgid,'signals':signals,'gone':not _group_alive(pgid)}


def dispatch(rundir: Path, spec: dict, *, graph=None, framework_step=None, packet=None, protected=(), effect=None,
             **options):
    materialize(rundir,spec,graph=graph,framework_step=framework_step,packet=packet,protected=protected,effect=effect)
    try:return load_receipt(rundir,spec['node_id'],spec['attempt'])
    except ValueError as exc:
        if str(exc)!='worker has no receipt yet':raise
    return launch(rundir,spec,packet=packet,protected=protected,effect=effect,**options)


def reconcile(rundir: Path, node_id: str, attempt: int, *, evidence=None, reason=None):
    if evidence is None or type(reason) is not str or not reason.strip():
        raise ValueError('explicit verified evidence and reconciliation reason required')
    run=broker.ordinary(rundir);_pin(run,evidence)
    path=_record_path(run,node_id,attempt)
    with file_lock(path.with_suffix('.lock')):
        record=read_json(path);receipt=load_receipt(run,node_id,attempt)
        if receipt['status']!='ambiguous':raise ValueError('only an ambiguous worker can be reconciled')
        registration=next((p for p in processes(run) if p['node_id']==node_id and p['attempt']==attempt),None)
        if registration and not registration['verified_gone']:raise ValueError('registered child not yet reaped')
        receipt['status']='failed';receipt['outcome']['status']='failed';receipt['outcome']['strict']=False
        receipt['failure']={'code':'process_error','detail':'explicitly reconciled failed worker'}
        receipt['finished_utc']=broker.utc()
        broker.append_ledger(run,'reconciliations',{'node_id':node_id,'attempt':attempt,'evidence':evidence,'reason':reason,'utc':broker.utc()})
        return _write_receipt(run,record['spec'],receipt,record)


def stop(rundir: Path, *, drain=False, pause=None):
    """Stop the run's workers: no new launch either way; ``drain`` lets admitted attempts finish.

    The record names its mode and, for a steering pause, the pause that wrote it.
    """
    run=broker.ordinary(rundir)
    # A drain never replaces a cancellation already in force.
    if not (drain and broker.stop_mode(run)=='cancel'):
        atomic_json(run/broker.STOP_RECORD,{'utc':broker.utc(),'mode':'drain' if drain else 'cancel',
                                     **({'steering_pause':pause} if pause is not None else {})})
    root=broker.custody(run);rows=read_json(root/'processes.json') if (root/'processes.json').exists() else []
    if drain:
        return {'stopped': [], 'verified_gone': all(p['status']=='finished' and p['verified_gone'] for p in rows), 'draining': True}
    stopped=[];verified=True
    for p in rows:
        if p['status']=='finished':verified=verified and p['verified_gone'];continue
        if not p.get('control_socket'):
            verified=False
            continue
        try:
            response=_control(p['control_socket'],p['token'],'stop')
            if response.get('token')!=p['token']:raise ValueError('supervisor identity changed')
            stopped.append(p['pgid'])
        except (OSError,ValueError):verified=False
    deadline=time.monotonic()+10
    while stopped and time.monotonic()<deadline:
        latest=read_json(root/'processes.json')
        if all(p['status']=='finished' and p['verified_gone'] for p in latest):break
        time.sleep(.05)
    latest=read_json(root/'processes.json') if (root/'processes.json').exists() else []
    verified=verified and all(p['status']=='finished' and p['verified_gone'] for p in latest)
    return {'stopped':stopped,'verified_gone':verified}


MAP_FIELDS={'schema_version','kind','id','spec','items','join'}
MAP_OPTIONAL={'max_item_attempts','workers'}
MAP_ITEM_ATTEMPTS=3


def validate_map(map_spec):
    """The typed map: all or quorum join, unique keys, item attempts and concurrency bounds."""
    if type(map_spec) is not dict or not MAP_FIELDS<=set(map_spec)<=MAP_FIELDS|MAP_OPTIONAL or map_spec['kind']!='agent-map':
        raise ValueError('typed map spec required')
    join=map_spec['join']
    if not (join=='all' or type(join) is str and join.startswith('quorum:') and join[7:].isdigit()):
        raise ValueError('map requires an explicit all or quorum join')
    if type(map_spec['id']) is not str or not broker.ID.fullmatch(map_spec['id']):
        raise ValueError('map identity required')
    items=map_spec['items']
    if type(items) is not list or not items or len(items)>256 or join!='all' and not 1<=int(join[7:])<=len(items):
        raise ValueError('finite map items and quorum required')
    keys=[i.get('key') if type(i) is dict else None for i in items]
    if len(keys)!=len(set(keys)) or not all(type(k) is str and broker.ID.fullmatch(k) for k in keys):
        raise ValueError('unique finite map keys required')
    for name,high in (('max_item_attempts',16),('workers',16)):
        value=map_spec.get(name,1)
        if type(value) is not int or not 1<=value<=high:raise ValueError(f'map {name} must be an integer from 1 to {high}')
    _validate({**deepcopy(map_spec['spec']),'node_id':map_spec['id']+'.'+keys[0],'attempt':1})
    return map_spec


def join_outcome(map_spec, receipts):
    """``ok``, ``failed`` or ``ambiguous`` for the map's declared join over its item receipts.

    Any ambiguous member keeps the join ambiguous: its effect may have committed. ``all``
    needs every member ``ok``; ``quorum:n`` needs at least ``n`` members ``ok``.
    """
    if any(r['status']=='ambiguous' for r in receipts):return 'ambiguous'
    ok=sum(r['status']=='ok' for r in receipts)
    need=len(map_spec['items']) if map_spec['join']=='all' else int(map_spec['join'][7:])
    return 'ok' if ok>=need else 'failed'


def dispatch_map(rundir: Path, map_spec: dict, *, workers=None, retry_failed=True, **options):
    validate_map(map_spec)
    if options.get('effect') is not None:
        raise ValueError('a map binds no single ledger effect; its items keep their own receipts')
    key=broker.digest(['map',map_spec['id']]);path=broker.custody(rundir)/(key+'.map.json')
    with file_lock(path.with_suffix('.lock')):
        if path.exists() and read_json(path)!=map_spec:raise ValueError('map specification changed; use a new map identity')
        if not path.exists():atomic_json(path,map_spec)
    items=map_spec['items']
    limit=map_spec.get('max_item_attempts',MAP_ITEM_ATTEMPTS)
    def run(item):
        node_id=map_spec['id']+'.'+item['key'];attempt=1
        while _record_path(rundir,node_id,attempt).exists():
            try:old=load_receipt(rundir,node_id,attempt)
            except ValueError:break
            if not retry_failed or old['status'] in {'ok','ambiguous','voided'} or attempt>=limit:return old
            attempt+=1
        s={**deepcopy(map_spec['spec']),'node_id':node_id,'attempt':attempt}
        s['inputs']=deepcopy(item['inputs']);s['parent']['map_id']=map_spec['id']
        return dispatch(rundir,s,**options)
    workers=map_spec.get('workers',1) if workers is None else workers
    if type(workers) is not int or not 1<=workers<=16:raise ValueError('finite worker concurrency required')
    with ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(run,sorted(items,key=lambda i:i['key'])))
    return sorted(results,key=lambda r:r['node_id'])


def join_digest(receipts):
    # Attempt wall times and completion order cannot change a result join.
    return broker.digest([{'node_id':r['node_id'],'status':r['status'],'credited_outputs':r['credited_outputs']}
                          for r in sorted(receipts,key=lambda r:r['node_id'])])


def status(rundir):
    run=broker.ordinary(rundir);receipts=[]
    for path in sorted(broker.work_root(run).glob('*/*/receipt.json')):
        try:receipt=load_receipt(run,path.parent.parent.name,int(path.parent.name))
        except (ValueError,OSError):raise ValueError('worker status encountered changed receipt custody') from None
        receipts.append(receipt)
    return {'workers':receipts,'processes':processes(run),'model_cells':completion_cells(run)}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {'adopt', 'pin-obligations'}:
        from .work_dispatch import main as work_order_main
        return work_order_main(argv)
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('supervise','dispatch','status','call','reconcile','stop'):
        command=sub.add_parser(name)
        if name=='call':
            command.add_argument('--socket',type=Path,default=os.environ.get('RAVEL_BROKER_SOCKET'))
            command.add_argument('--request',type=Path,required=True)
        else:command.add_argument('--rundir',type=Path,required=True)
        if name in {'supervise','reconcile'}:
            command.add_argument('--node',required=True);command.add_argument('--attempt',type=int,required=True)
        if name=='dispatch':command.add_argument('--spec',type=Path,required=True)
        if name=='reconcile':
            command.add_argument('--evidence',type=Path,required=True);command.add_argument('--reason',required=True)
    args=parser.parse_args(argv)
    if args.command=='supervise':
        supervise(args.rundir,args.node,args.attempt);return 0
    if args.command=='dispatch':value=dispatch(args.rundir,read_json(args.spec))
    elif args.command=='status':value=status(args.rundir)
    elif args.command=='call':
        if args.socket is None:raise ValueError('broker socket required')
        value=broker.socket_call(args.socket,read_json(args.request))
    elif args.command=='reconcile':
        value=reconcile(args.rundir,args.node,args.attempt,evidence=read_json(args.evidence),reason=args.reason)
    else:value=stop(args.rundir)
    print(json.dumps(value,indent=2,allow_nan=False))
    if args.command=='stop':return 0 if value['verified_gone'] else 1
    return 0 if value.get('status','ok')=='ok' else 1


if __name__=='__main__':raise SystemExit(main())
