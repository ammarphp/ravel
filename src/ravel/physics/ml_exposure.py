"""Atomic all-role population claims, independent of NPZ encoding and row order.

The decision-gate authority must protect this namespace; the machine lease must use it too.
The ledger lives under the machine state root. Only its marked test-only override relocates it,
and a test namespace never constitutes production evidence.
"""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import zipfile
import numpy as np
from ravel.workflow import execution_backend as eb
from ravel.workflow import machine_lease
from ravel.workflow.state_io import atomic_json

ROLES = ('test_split', 'crossfit_population', 'injection_evaluation_pool',
         'background_reference', 'null_toy', 'oracle_training_pool', 'train_split', 'validation_split')
# Adaptive populations may be reread by later adaptive roles; a withheld test split is read once in total.
ADAPTIVE = ('train_split', 'validation_split')
SINGLE_READ = ('test_split',)


def root():
    """The one per-machine ledger: ``machine_state_root()/ml-exposure``; RAVEL_STATE_DIR never moves it."""
    # Seam: the AGENT-INTERFACES s24 name when machine_lease defines it, else the same fixed per-uid directory.
    state_root = getattr(machine_lease, 'machine_state_root', None) or machine_lease.ensure_machine_dir
    return Path(state_root())/'ml-exposure'


def identity(pin, base):
    """Decode identities and value hashes in the evaluator, without exposing labels."""
    path=Path(pin['path']); path=path if path.is_absolute() else Path(base)/path
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('symlink population')
    raw=path.read_bytes()
    if len(raw)>64*1024**2 or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise ValueError('population pin changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(r.file_size for r in archive.infolist())>64*1024**2: raise ValueError('expanded population too large')
    with np.load(io.BytesIO(raw),allow_pickle=False) as z:
        if not {'event_id','group_id','x','weight'} <= set(z.files):
            raise ValueError('population requires event_id and group_id')
        ids=z['event_id'].astype(str); groups=z['group_id'].astype(str)
        if ids.ndim!=1 or groups.shape!=ids.shape or len(set(ids))!=len(ids):
            raise ValueError('invalid population identities')
        columns=[k for k in ('x','region','weight') if k in z.files]
        arrays={k:np.asarray(z[k],dtype='<f8') for k in columns}
        if any(len(a)!=len(ids) or not np.isfinite(a).all() for a in arrays.values()):
            raise ValueError('invalid identity value columns')
        values=[]
        for i in range(len(ids)):
            # Numeric values normalized across dtype and endianness; -0 equals +0.
            row={k:np.where(a[i]==0,0.,a[i]).tolist() for k,a in arrays.items()}
            values.append(hashlib.sha256(eb.canonical(row)).hexdigest())
    events=sorted(set(ids.tolist())); group_ids=sorted(set(groups.tolist()))
    return {'sha256':hashlib.sha256(eb.canonical(events)).hexdigest(), 'byte_sha256':pin['sha256'],
            'event_ids':events,'group_ids':group_ids,'value_hashes':sorted(set(values))}


def manifest_identity(partition,byte_sha256):
    """Identity of one partition from a pinned split manifest; no partition file is read."""
    events=partition.get('event_ids') if isinstance(partition,dict) else None
    groups=partition.get('group_ids') if isinstance(partition,dict) else None
    if (not isinstance(events,list) or not isinstance(groups,list) or not events or len(events)!=len(groups)
            or any(not isinstance(v,str) or not v for v in events+groups) or len(set(events))!=len(events)):
        raise ValueError('manifest partition requires unique event_ids with one group_id each')
    ordered=sorted(events)
    return {'sha256':hashlib.sha256(eb.canonical(ordered)).hexdigest(),'byte_sha256':byte_sha256,
            'event_ids':ordered,'group_ids':sorted(set(groups)),'value_hashes':[],'source':'manifest'}


def verify_identifiers(pin,base,expected):
    """After a charged read: the file's identifiers must be the manifest's. Only identifier columns are decoded."""
    path=Path(pin['path']); path=path if path.is_absolute() else Path(base)/path
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=pin['sha256']: raise ValueError('population pin changed')
    with np.load(io.BytesIO(raw),allow_pickle=False) as z:
        events=sorted(z['event_id'].astype(str).tolist()); groups=sorted(set(z['group_id'].astype(str).tolist()))
    if events!=expected['event_ids'] or groups!=expected['group_ids']:
        raise ValueError('population identifiers differ from the pinned split manifest')


def overlaps(a,b):
    """Shared events or groups, or a relabelled copy: every measured row of one population is a row of the other.

    Independent events that happen to share measured values are recorded as collisions, not overlap.
    """
    if any(set(a[k]) & set(b[k]) for k in ('event_ids','group_ids')): return True
    va,vb=set(a.get('value_hashes') or []),set(b.get('value_hashes') or [])
    return bool(va and vb and (va<=vb or vb<=va))


def value_collisions(a,b):
    return len(set(a.get('value_hashes') or []) & set(b.get('value_hashes') or []))


@contextmanager
def _locked():
    path=root()/'.lock'
    if any(p.is_symlink() for p in (path,*path.parents)): raise ValueError('symlink exposure namespace')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(stream,fcntl.LOCK_UN)


def _record_path(sha256):
    if not isinstance(sha256,str) or len(sha256)!=64 or any(c not in '0123456789abcdef' for c in sha256):
        raise ValueError('exposure ledger requires a logical sha256 identity')
    return root()/f'{sha256}.json'


def _load(path):
    if path.is_symlink(): raise ValueError('symlink exposure record')
    return json.loads(path.read_text()) if path.exists() else None


class Study:
    def __init__(self,spec_sha256,token=None):
        # A persisted token lets a resumed run continue its own unread claim.
        if token is not None and (not isinstance(token,str) or len(token)!=32): raise ValueError('exposure claim token invalid')
        self.spec=spec_sha256; self.token=token or secrets.token_hex(16); self.claims={}; self.closed=False

    def claim(self,population,role,*,schedule):
        self.claim_all([(population,role)],schedule=schedule)

    def claim_all(self,items,*,schedule):
        """One transaction validates the complete overlap matrix before any write."""
        for i,(population,role) in enumerate(items):
            if role not in ROLES or not isinstance(population,dict): raise ValueError('logical population and known role required')
            if population['sha256'] not in schedule: raise ValueError('full exposure schedule required')
            if len(schedule[population['sha256']])!=len(set(schedule[population['sha256']])): raise ValueError('duplicate schedule context')
            if role in SINGLE_READ and len(schedule[population['sha256']])!=1:
                raise ValueError(f'{role}: a withheld population takes exactly one scheduled read')
            if any(overlaps(population,p) for p,_ in items[:i]): raise ValueError('population roles overlap before exposure')
        with _locked():
            priors=[_load(p) for p in root().glob('*.json')]
            records=[]
            for population,role in items:
                history=[]; attempts=1; collisions=[]
                own=[p for p in priors if p.get('token')==self.token and p.get('sha256')==population['sha256']]
                if own:
                    if own[0]['spec_sha256']!=self.spec or own[0]['roles']!=[role] or own[0]['state']!='claimed':
                        raise ValueError(f'{role}: resumed claim differs from the recorded claim')
                    self.claims[population['sha256']]=own[0]['identity']
                    continue
                for prior in priors:
                    if 'identity' not in prior: raise ValueError('legacy byte-only exposure namespace requires migration')
                    if value_collisions(population,prior['identity']):
                        collisions.append({'sha256':prior['sha256'],'values':value_collisions(population,prior['identity'])})
                    if overlaps(population,prior['identity']):
                        if prior['reads'] and role in ADAPTIVE and set(prior['roles'])<=set(ADAPTIVE):
                            history.append({'spec_sha256':prior['spec_sha256'],'state':prior['state'],
                                            'reads':len(prior['reads']),'class':'adaptive_reuse'})
                            continue
                        if prior['reads']:
                            raise ValueError(f'{role}: already claimed by another study or already read/spent')
                        if prior['state']=='claimed':
                            raise ValueError(f'{role}: already claimed by another active study')
                        history.append({'spec_sha256':prior['spec_sha256'],'state':prior['state'],'reads':0})
                        attempts=max(attempts,prior['attempts']+1)
                record={'schema_version':2,'identity':population,'sha256':population['sha256'],
                        'spec_sha256':self.spec,'token':self.token,'roles':[role],'reads':[],
                        'schedule':schedule[population['sha256']], 'state':'claimed','attempts':attempts,'prior_unread':history,
                        'value_collisions':collisions}
                records.append(record)
            for record in records:
                sha=record['sha256']; atomic_json(_record_path(sha),record)
                self.claims[sha]=record['identity']
            index={key:{} for key in ('event_ids','group_ids','value_hashes')}
            for record in [_load(p) for p in root().glob('*.json')]:
                for key in index:
                    for value in record['identity'][key]: index[key][value]=record['sha256']
            directory=root()/'indices'; directory.mkdir(exist_ok=True)
            atomic_json(directory/'identity.json',index)

    def read(self,sha256,context,selection):
        if self.closed: raise ValueError('closed exposure study')
        # Callers may retain the secondary byte hash; resolve it only within this claim.
        sha256=next((s for s,p in self.claims.items() if p['byte_sha256']==sha256),sha256)
        if sha256 not in self.claims: raise ValueError('population not claimed by this study')
        try:
            path=Path(selection['path'])
            if eb.file_sha256(path)!=selection['sha256']: raise ValueError
            frozen=json.loads(path.read_text())
            if frozen.get('spec_sha256')!=self.spec or not any(k in frozen for k in ('models','checkpoints','selection')): raise ValueError
        except (OSError,KeyError,TypeError,ValueError) as exc:
            raise ValueError('frozen selection record of this specification required before read') from exc
        with _locked():
            path=_record_path(sha256); record=_load(path)
            if record is None or record['token']!=self.token or record['state']!='claimed': raise ValueError('closed or changed exposure claim')
            if context not in record['schedule']: raise ValueError('unscheduled exposure context')
            if any(r['context']==context for r in record['reads']): raise ValueError('population already read in this context')
            if set(record['roles'])&set(SINGLE_READ) and record['reads']:
                raise ValueError('withheld population already read; it is read once in total')
            record['reads'].append({'context':context,'selection':selection,'class':'evaluation'})
            atomic_json(path,record)

    def close(self,state,receipt=None):
        with _locked():
            for sha in self.claims:
                path=_record_path(sha); record=_load(path)
                if record is not None and record['token']==self.token:
                    record.update(state=state,receipt=receipt); atomic_json(path,record)
        self.closed=True

    def provenance(self):
        return {'root':str(root().resolve()),'host':socket.gethostname(),
                'test_namespace':machine_lease.domain()=='test',
                'populations':sorted(self.claims),
                'ledger_digest':hashlib.sha256(eb.canonical(self.claims)).hexdigest()}


def verify_receipt(receipt,path):
    """Both content and namespace must match the completed authority records."""
    provenance=receipt.get('exposure_ledger',{})
    if provenance.get('root')!=str(root().resolve()) or provenance.get('host')!=socket.gethostname():
        raise ValueError('receipt exposure namespace changed')
    if not provenance.get('populations'): raise ValueError('receipt has no exposure populations')
    if path.is_symlink() or not path.is_file(): raise ValueError('written receipt missing; ledger pin cannot be verified')
    if json.loads(path.read_text())!=receipt: raise ValueError('receipt bytes differ from ledger-pinned result')
    sha=eb.file_sha256(path)
    local_name=provenance['populations'][0] if receipt['kind']=='ml-training-receipt' else None
    # Resolve the primary role instead of relying on lexical population order.
    role='test_split' if receipt['kind']=='ml-training-receipt' else 'crossfit_population'
    identities={}
    for population in provenance.get('populations',[]):
        record=_load(_record_path(population))
        if not record or record.get('state') not in ('complete','complete_blinded') or (record.get('receipt') or {}).get('sha256')!=sha or record['spec_sha256']!=receipt['spec_sha256']:
            raise ValueError('receipt differs from exposure ledger pin')
        identities[population]=record['identity']
        if role in record['roles']: local_name=population
    if hashlib.sha256(eb.canonical(identities)).hexdigest()!=provenance['ledger_digest']: raise ValueError('receipt ledger identity digest changed')
    suffix='.json' if role=='test_split' else '.crossfit.json'
    local=_load(Path(receipt['input_base'])/'ml-exposure'/(str(local_name)+suffix))
    if not local or (local.get('receipt') or {}).get('sha256')!=sha: raise ValueError('receipt differs from local ledger pin')


def record_replay(provenance,spec_sha256,context,selection):
    """Append a replay class; the original evaluation count is unchanged."""
    if provenance['root']!=str(root().resolve()): raise ValueError('replay namespace changed')
    if eb.file_sha256(Path(selection['path']))!=selection['sha256']: raise ValueError('replay freeze changed')
    with _locked():
        for sha in provenance['populations']:
            path=_record_path(sha); record=_load(path)
            if not record or record['spec_sha256']!=spec_sha256: raise ValueError('replay authority changed')
            if any(r['context']==context and r['selection']==selection for r in record['reads']):
                record.setdefault('replays',[]).append({'class':'replay','context':context,'selection':selection})
                atomic_json(path,record); return
    raise ValueError('replay has no original frozen exposure')


def reserve_research(spec_sha256, populations, *, context, selection_sha256=None):
    """Reserve and consume a research exposure atomically in the ML namespace.

    Both APIs scan the same records under the same lock. Adaptive research may
    re-read adaptive populations; neither API can repurpose confirmation data.
    Failed dispatch remains spent. No campaign-local ledger can reset this one.
    """
    if not populations:
        raise ValueError('research exposure requires canonical populations')
    confirmation = selection_sha256 is not None
    role = 'research_confirmation' if confirmation else 'research_adaptive'
    with _locked():
        priors = [_load(p) for p in root().glob('*.json')]
        for population in populations:
            _record_path(population['sha256'])
            if not all(isinstance(population.get(k), list) for k in ('event_ids', 'group_ids', 'value_hashes')):
                raise ValueError('canonical research population identity required')
            for prior in priors:
                if 'identity' not in prior:
                    raise ValueError('legacy exposure namespace requires migration')
                if overlaps(population, prior['identity']):
                    if confirmation or prior['roles'] != ['research_adaptive']:
                        raise ValueError('population already claimed/read/spent in shared study ledger')
        records = []
        for population in populations:
            # Never overwrite an earlier record, including adaptive repeated reads.
            key = hashlib.sha256(eb.canonical([spec_sha256, context, population, len(priors)])).hexdigest()
            record = {'schema_version': 2, 'identity': population, 'sha256': key,
                      'spec_sha256': spec_sha256, 'token': secrets.token_hex(16), 'roles': [role],
                      'reads': [{'context': context, 'selection_sha256': selection_sha256, 'class': 'evaluation'}],
                      'schedule': [context], 'state': 'spent', 'attempts': 1, 'prior_unread': []}
            atomic_json(_record_path(key), record)
            records.append(key)
        return {'root': str(root().resolve()), 'records': records, 'role': role}


def verify_research_read(read):
    """Authenticate the journal's reference against the shared spent records."""
    ledger = read.get('ledger') or {}
    if ledger.get('root') != str(root().resolve()) or not ledger.get('records'):
        raise ValueError('confirmation shared ledger receipt missing or namespace changed')
    with _locked():
        observed = []
        for key in ledger['records']:
            record = _load(_record_path(key))
            if (not record or record['state'] != 'spent' or record['roles'] != ['research_confirmation']
                    or len(record['reads']) != 1
                    or record['reads'][0].get('selection_sha256') != read['selection_sha256']):
                raise ValueError('confirmation shared ledger record differs')
            observed.append(record['identity'])
        if observed != read.get('populations'):
            raise ValueError('confirmation ledger populations differ')
