"""Synthetic software controls, authored UNRUN; no science or speed claim.

The frozen baseline functions below are literal S15 source. Real descriptors,
ValidationSession and WorkerReadOnlyObservation exercise the new scope. Only
runtime/authority fixtures are synthetic; original FR/worker suites stay separate.
"""
from copy import deepcopy
from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from ravel.workflow import execution, fresh_replication as fresh, report_integrity as ri
from ravel.workflow import readonly_preparation as rp
from ravel.workflow.state_io import read_json
from ravel.workflow.validation_io import ValidationSession

OLD_SOURCE = 'def _ordinary(path):\n    path = Path(path).absolute()\n    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():\n        raise ValueError("ordinary existing manuscript evidence required")\n    return path.resolve(strict=True)\n\n\ndef _artifact_path(pin, base):\n    p = Path(pin["path"])\n    return _ordinary(p if p.is_absolute() else Path(base)/p)\n\n\ndef custody_limits(value=None):\n    """Operational capacity only; scientific text/model-presentation limits stay fixed."""\n    defaults = {\'max_files\': MAX_CUSTODY_FILES, \'max_bytes\': MAX_CUSTODY_BYTES,\n                \'max_metadata_bytes\': MAX_BYTES}\n    value = defaults if value is None else value\n    ce.keys(value, defaults)\n    ceilings = {\'max_files\': MAX_OPERATIONAL_FILES, \'max_bytes\': MAX_CUSTODY_BYTES,\n                \'max_metadata_bytes\': MAX_OPERATIONAL_METADATA_BYTES}\n    if any(type(value[k]) is not int or not 1 <= value[k] <= ceilings[k] for k in defaults):\n        raise ValueError(\'explicit finite supported operational custody limits required\')\n    return dict(value)\n\n\nclass CustodyAccumulator:\n    """One unique-path union, including ending reads; never a per-leaf budget reset."""\n    def __init__(self, limits=None):\n        self.limits = custody_limits(limits)\n        self.members = {}\n        self.total_bytes = 0\n\n    def add(self, pin):\n        old = self.members.get(pin[\'path\'])\n        if old is not None and old != pin:\n            raise ValueError(\'conflicting operational dependency identity\')\n        if old is None:\n            self.members[pin[\'path\']] = dict(pin)\n            self.total_bytes += pin[\'size\']\n        if (len(self.members) > self.limits[\'max_files\'] or self.total_bytes > self.limits[\'max_bytes\']):\n            raise ValueError(\'complete operational custody exceeds declared limits; no truncation\')\n\n\ndef _operational_json(pin, base, consumed, *, limits=None, accumulator=None):\n    """Bound complete metadata before decoding, without raising any prose/context limit."""\n    selected = custody_limits(limits)\n    ce.keys(pin, [\'path\', \'sha256\', \'size\']); ce.sha(pin[\'sha256\'])\n    if type(pin[\'size\']) is not int or not 1 <= pin[\'size\'] <= selected[\'max_metadata_bytes\']:\n        raise ValueError(\'bounded complete operational metadata required\')\n    p = _artifact_path(pin, base)\n    fd = os.open(p, os.O_RDONLY | getattr(os, \'O_NOFOLLOW\', 0) | getattr(os, \'O_NONBLOCK\', 0))\n    try:\n        before = os.fstat(fd)\n        if not stat.S_ISREG(before.st_mode):\n            raise ValueError(\'regular operational metadata required\')\n        if before.st_size != pin[\'size\']:\n            raise ValueError(\'operational metadata changed: pinned size differs\')\n        with os.fdopen(fd, \'rb\', closefd=False) as stream:\n            raw = stream.read(pin[\'size\'] + 1)\n        after = os.fstat(fd)\n    finally:\n        os.close(fd)\n    fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)\n    if (fields(before) != fields(after) or fields(after) != fields(_ordinary(p).stat()) or\n            len(raw) != pin[\'size\'] or hashlib.sha256(raw).hexdigest() != pin[\'sha256\']):\n        raise ValueError(\'operational metadata changed while read\')\n    absolute = {\'path\': str(p), \'sha256\': pin[\'sha256\'], \'size\': len(raw)}\n    if str(p) in consumed and consumed[str(p)] != absolute:\n        raise ValueError(\'conflicting operational metadata identity\')\n    consumed[str(p)] = absolute\n    budget = accumulator or CustodyAccumulator(selected)\n    if budget.limits != selected: raise ValueError(\'one exact admitted operational policy required\')\n    for row in consumed.values(): budget.add(row)\n    return _json(raw)\n\n\ndef _dependency(pin, base, consumed, *, limits=None, accumulator=None):\n    """Stream a complete executed binary/input leaf without presenting it as text.\n\n    The selected located evidence is still presented in full by _raw. A native\n    runtime/input census may contain larger binary leaves; their commitments are\n    dependencies, never a claim that a reviewer read those bytes or they loaded.\n    """\n    ce.keys(pin, ["path", "sha256", "size"]); ce.sha(pin["sha256"])\n    selected = custody_limits(limits)\n    if type(pin["size"]) is not int or not 0 <= pin["size"] <= selected[\'max_bytes\']:\n        raise ValueError("bounded complete stage dependency required")\n    p = _artifact_path(pin, base); h = hashlib.sha256(); total=0\n    fd=os.open(p,os.O_RDONLY|getattr(os,\'O_NOFOLLOW\',0)|getattr(os,\'O_NONBLOCK\',0))\n    try:\n        before=os.fstat(fd)\n        if not stat.S_ISREG(before.st_mode):\n            raise ValueError(\'regular operational dependency required\')\n        if before.st_size!=pin[\'size\']:\n            raise ValueError(\'executed dependency changed: pinned size differs\')\n        with os.fdopen(fd,\'rb\',closefd=False) as stream:\n            for chunk in iter(lambda:stream.read(1024**2),b\'\'):\n                total+=len(chunk)\n                if total>pin[\'size\']:raise ValueError(\'operational dependency grew while read\')\n                h.update(chunk)\n        after=os.fstat(fd)\n    finally:os.close(fd)\n    ending=_ordinary(p).stat(); fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")\n    if (tuple(getattr(before, k) for k in fields) != tuple(getattr(after, k) for k in fields)\n            or tuple(getattr(after,k) for k in fields)!=tuple(getattr(ending,k) for k in fields)\n            or total != pin[\'size\'] or h.hexdigest() != pin[\'sha256\']):\n        raise ValueError(\'executed dependency changed\')\n    absolute = {\'path\': str(p), \'sha256\': pin[\'sha256\'], \'size\': pin[\'size\']}\n    if str(p) in consumed and consumed[str(p)] != absolute: raise ValueError(\'conflicting stage source identity\')\n    consumed[str(p)] = absolute\n    budget = accumulator or CustodyAccumulator(selected)\n    if budget.limits != selected: raise ValueError(\'one exact admitted operational policy required\')\n    for row in consumed.values(): budget.add(row)\n    return absolute\n\n\ndef _json(raw):\n    def pairs(items):\n        result = {}\n        for key, value in items:\n            if key in result: raise ValueError("duplicate manuscript JSON field")\n            result[key] = value\n        return result\n    value = json.loads(raw, object_pairs_hook=pairs,\n        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite manuscript JSON")))\n    json.dumps(value, allow_nan=False)\n    return value\n'
OLD = {'Path':Path,'os':os,'hashlib':hashlib,'stat':__import__('stat'),'json':__import__('json'),'ce':ri.ce,
       'MAX_CUSTODY_FILES':ri.MAX_CUSTODY_FILES,'MAX_CUSTODY_BYTES':ri.MAX_CUSTODY_BYTES,'MAX_BYTES':ri.MAX_BYTES,
       'MAX_OPERATIONAL_FILES':ri.MAX_OPERATIONAL_FILES,'MAX_OPERATIONAL_METADATA_BYTES':ri.MAX_OPERATIONAL_METADATA_BYTES}
exec(compile(OLD_SOURCE,'<frozen-S15-readers>','exec'),OLD)


def pin(path):
    raw=path.read_bytes()
    return {'path':str(path),'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def session(root):
    root.mkdir(parents=True,exist_ok=True)
    return ValidationSession(root, resolve_path=lambda base,value,output=False: Path(value) if Path(value).is_absolute() else base/value,
        read_json=read_json, runtime_context=lambda:{'engineering':'synthetic'},
        digest=execution.digest,state_name='ledger.json')


def module(paths=()):
    m=SimpleNamespace()
    def inputs(task,base):return list(paths)
    def run(task,base,out):raise AssertionError('effect inside observational control')
    def observe(task,base,context):
        if paths:
            scope=fresh._readonly_producer(context)
            seen=fresh._Consumed(_observation=scope.operational)
            for path in paths:fresh._dependency(pin(path),base,seen)
            fresh._ending(seen)
        return inputs(task,base)
    def calculate(task,base,context):
        observe(task,base,context)
        return {'status':'passed','physics_validated':False,'bytes':sum(p.stat().st_size for p in paths)}
    def materialize(value,spec,context):return (('engineering.json',rp._bytes(value)),)
    m.inputs,m.run,m.observe,m.calculate,m.materialize=inputs,run,observe,calculate,materialize
    m.READONLY_WORKER_V1=rp.ReadOnlyAdapterV1(tuple((name,getattr(m,name)) for name in ('inputs','run','observe','calculate','materialize')),observe,calculate,materialize,False)
    return m


@contextmanager
def owned(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,'_validation_session',lambda root:session(Path(root)))
    root=tmp_path/'worker'
    with rp.WorkerReadOnlyObservation(root) as worker:
        m=module()
        worker.inputs(m,{},tmp_path,'original')
        worker.inputs(m,{},tmp_path,'effective')
        owner=ri._anchored_owner(worker)
        assert owner is not None and owner.session is worker.session
        yield worker,owner


def finish(worker,tmp_path):
    value=worker.calculate({},tmp_path)
    worker.materialize({'attempt':1},{'task':{}},value)
    return worker.finish()


def call(reader,path,owner=None,consumed=None,budget=None):
    consumed={} if consumed is None else consumed
    budget=ri.CustodyAccumulator() if budget is None else budget
    answer=reader(pin(path),path.parent,consumed,accumulator=budget,
                  **({} if owner is None else {'_observation':owner}))
    return answer,deepcopy(consumed),deepcopy(budget.members),budget.total_bytes


@pytest.mark.parametrize('kind',['binary','json'])
@pytest.mark.parametrize('name',['plain','space and ünicode','.hidden','nested/data','zero'])
def test_frozen_readers_actual_bytes_and_ordered_union_match(tmp_path,monkeypatch,kind,name):
    if kind=='json' and name=='zero':raw=b'{}'
    else:raw=(b'{"nested":{"x":3}}' if kind=='json' else b'\x00complete\xff') if name!='zero' else b''
    p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    old=OLD['_operational_json' if kind=='json' else '_dependency']
    new=ri._operational_json if kind=='json' else ri._dependency
    expected=call(old,p)
    with owned(tmp_path,monkeypatch) as (worker,owner):
        first=call(new,p,owner);before=tuple(owner.acquired);record=owner.records[p]
        second=call(new,p,owner)
        assert first==second==expected and tuple(owner.acquired)==before
        assert owner.records[p] is record
        bundle=finish(worker,tmp_path)
        assert bundle.result['physics_validated'] is False
    assert owner.closed and owner.acquired==[] and worker.session.closed
    assert not (tmp_path/'worker'/'outputs').exists()


@pytest.mark.parametrize('change',['missing','directory','dangling','leaf-symlink','ancestor-symlink','wrong-size','wrong-hash','empty-json','duplicate-json'])
def test_invalid_source_default_and_owned_refuse_without_custody(tmp_path,monkeypatch,change):
    parent=tmp_path/'source';parent.mkdir();p=parent/'data';p.write_bytes(b'{}');intended=pin(p)
    reader=ri._operational_json
    if change=='missing':p.unlink()
    elif change=='directory':p.unlink();p.mkdir()
    elif change=='dangling':p.unlink();p.symlink_to(parent/'absent')
    elif change=='leaf-symlink':other=parent/'other';p.rename(other);p.symlink_to(other)
    elif change=='ancestor-symlink':other=tmp_path/'other';parent.rename(other);parent.symlink_to(other,target_is_directory=True)
    elif change=='wrong-size':intended['size']+=1
    elif change=='wrong-hash':intended['sha256']='0'*64
    elif change=='empty-json':p.write_bytes(b'');intended=pin(p)
    else:p.write_bytes(b'{"x":1,"x":2}');intended=pin(p)
    results=[]
    for new in (False,True):
        consumed={};budget=ri.CustodyAccumulator()
        with owned(tmp_path,monkeypatch) as (_,owner):
            with pytest.raises((ValueError,OSError)) as error:
                (reader if new else OLD['_operational_json'])(intended,tmp_path,consumed,accumulator=budget,
                    **({'_observation':owner} if new else {}))
            results.append((type(error.value),str(error.value),deepcopy(consumed),deepcopy(budget.members),budget.total_bytes))
    assert results[0]==results[1]
    # JSON parse refusals occur after custody, exactly as in the frozen reader.
    if change!='duplicate-json':assert results[0][2]=={}


@pytest.mark.parametrize('spelling',['relative','dotdot','double-slash'])
def test_noncanonical_spelling_full_original_fallback(tmp_path,monkeypatch,spelling):
    p=tmp_path/'data';p.write_bytes(b'payload');intended=pin(p)
    if spelling=='relative':intended['path']='data'
    elif spelling=='dotdot':d=tmp_path/'dir';d.mkdir();intended['path']=str(d/'..'/'data')
    else:intended['path']=str(tmp_path)+'//data'
    expected={};OLD['_dependency'](intended,tmp_path,expected)
    with owned(tmp_path,monkeypatch) as (worker,owner):
        actual={};ri._dependency(intended,tmp_path,actual,_observation=owner)
        assert actual==expected
        if spelling!='relative':assert not owner.records
        finish(worker,tmp_path)


@pytest.mark.parametrize('case',['conflict','file-cap','byte-cap','foreign-policy'])
def test_complete_union_partial_failure_and_error_precedence_preserved(tmp_path,monkeypatch,case):
    p=tmp_path/'data';p.write_bytes(b'abc');q=tmp_path/'previous';q.write_bytes(b'a')
    results=[]
    for reader in (OLD['_dependency'],ri._dependency):
        consumed={str(q):pin(q)};budget=ri.CustodyAccumulator()
        if case=='conflict':consumed[str(p)]={**pin(p),'sha256':'0'*64}
        elif case=='file-cap':budget.limits['max_files']=1
        elif case=='byte-cap':budget.limits['max_bytes']=3
        else:budget.limits['max_metadata_bytes']=1
        with owned(tmp_path,monkeypatch) as (_,owner):
            with pytest.raises(ValueError) as error:
                reader(pin(p),tmp_path,consumed,accumulator=budget,
                       **({'limits':budget.limits} if case in ('file-cap','byte-cap') else {}),
                       **({'_observation':owner} if reader is ri._dependency else {}))
            results.append((str(error.value),deepcopy(consumed),deepcopy(budget.members),budget.total_bytes))
    assert results[0]==results[1]


@pytest.mark.parametrize('phase',['next-read','last-callback'])
@pytest.mark.parametrize('replacement',['symlink-restored','directory-hardlink','leaf-hardlink'])
def test_current_names_and_lifetime_commitments_refuse_replaced_tree(tmp_path,monkeypatch,phase,replacement):
    d=tmp_path/'tree';d.mkdir();p=d/'data';p.write_bytes(b'complete');intended=pin(p);saved=tmp_path/'saved'
    with pytest.raises(ValueError,match='ordinary|anchored|identity changed'):
        with owned(tmp_path,monkeypatch) as (worker,owner):
            seen={};ri._dependency(intended,tmp_path,seen,_observation=owner)
            held=tuple(owner.acquired)
            def alter():
                if replacement=='leaf-hardlink':
                    other=d/'other';os.link(p,other);p.unlink();os.link(other,p)
                else:
                    d.rename(saved)
                    if replacement=='symlink-restored':d.symlink_to(saved,target_is_directory=True)
                    else:d.mkdir();os.link(saved/'data',p)
            if phase=='next-read':
                alter()
                if replacement in ('directory-hardlink','leaf-hardlink'):
                    legacy={};OLD['_dependency'](intended,tmp_path,legacy)
                    assert legacy[str(p)]==intended
                try:ri._dependency(intended,tmp_path,seen,_observation=owner)
                finally:
                    if replacement=='symlink-restored':d.unlink();saved.rename(d)
            else:
                worker.add_ending_check(alter)
                finish(worker,tmp_path)
    assert owner.closed and owner.acquired==[] and worker.session.closed
    assert not (tmp_path/'worker'/'outputs').exists()
    for fd in held:
        with pytest.raises(OSError) as error:os.fstat(fd)
        assert error.value.errno==errno.EBADF


@pytest.mark.parametrize('change',['bytes','mode','leaf-delete','pin-value','limits','new-ledger','runtime','source-member'])
def test_full_postcallback_terminal_retains_facts_and_values(tmp_path,monkeypatch,change):
    p=tmp_path/'data';p.write_bytes(b'old');intended=pin(p);limits=ri.custody_limits()
    leaf_deleted=[]
    expectation=(pytest.raises(FileNotFoundError) if change=='leaf-delete' else
                 pytest.raises(ValueError,match='changed|identity|disappeared|ledger|runtime|inventory'))
    with expectation as refusal:
        with owned(tmp_path,monkeypatch) as (worker,owner):
            ri._dependency(intended,tmp_path,{},limits=limits,_observation=owner)
            directory=tmp_path/'members';directory.mkdir();(directory/'one').write_text('one')
            worker.session.require_inventory(directory)
            def change_late():
                if change=='bytes':p.write_bytes(b'new')
                elif change=='mode':p.chmod(0o600 if p.stat().st_mode&0o777!=0o600 else 0o644)
                elif change=='leaf-delete':
                    p.unlink();leaf_deleted.append(p)
                elif change=='pin-value':intended['sha256']='0'*64
                elif change=='limits':limits['max_files']-=1
                elif change=='new-ledger':worker.session.ledger.write_text('{}')
                elif change=='runtime':worker.session.runtime_context=lambda:{'engineering':'changed'}
                else:(directory/'two').write_text('two')
            worker.add_ending_check(change_late)
            finish(worker,tmp_path)
    if change=='leaf-delete':
        assert leaf_deleted==[p] and not p.exists()
        assert type(refusal.value) is FileNotFoundError
        assert refusal.value.errno==errno.ENOENT and Path(refusal.value.filename)==p
    assert owner.closed and worker.session.closed and owner.acquired==[]


def test_actual_generic_inputs_calculation_and_original_full_ending_use_one_owner(tmp_path,monkeypatch):
    paths=[]
    for name in ('one','two'):
        p=tmp_path/name;p.write_bytes(name.encode());paths.append(p)
    monkeypatch.setattr(execution,'_validation_session',lambda root:session(Path(root)))
    m=module(paths);root=tmp_path/'worker'
    with rp.WorkerReadOnlyObservation(root) as worker:
        first=worker.inputs(m,{},tmp_path,'original')
        owner=worker.resources[ri._AnchoredDependencyObservation];fds=tuple(owner.acquired)
        second=worker.inputs(m,{},tmp_path,'effective')
        result=worker.calculate({},tmp_path)
        assert first==second==paths and result['bytes']==6 and result['physics_validated'] is False
        assert tuple(owner.acquired)==fds and len(owner.records)==2
        worker.materialize({'attempt':1},{'task':{}},result);bundle=worker.finish()
        assert bundle.result==result and len(worker.resources)==2
    assert owner.closed and worker.closed and not (root/'outputs').exists()


@pytest.mark.parametrize('field',['pid','thread','session','closed','factory','source-callable','binding-reader-spoof'])
def test_owner_boundary_changes_refuse_and_close_all_descriptors(tmp_path,monkeypatch,field):
    p=tmp_path/'data';p.write_bytes(b'complete')
    with pytest.raises(ValueError,match='owner|ownership|factory|participant|changed'):
        with owned(tmp_path,monkeypatch) as (worker,owner):
            ri._dependency(pin(p),tmp_path,{},_observation=owner);held=tuple(owner.acquired)
            if field=='pid':owner.pid=-1
            elif field=='thread':owner.thread=-1
            elif field=='session':worker.session= session(tmp_path/'foreign')
            elif field=='closed':owner.closed=True
            elif field=='factory':monkeypatch.setattr(ri,'_AnchoredDependencyObservation',lambda:None)
            elif field=='binding-reader-spoof':
                canonical=ri._ANCHORED_CANONICAL_BINDINGS
                monkeypatch.setattr(ri,'_anchored_bindings',lambda:canonical)
            else:monkeypatch.setattr(ri,'_ordinary',lambda value:Path(value))
            ri._dependency(pin(p),tmp_path,{},_observation=owner)
    assert owner.closed and owner.acquired==[]
    for fd in held:
        with pytest.raises(OSError) as error:os.fstat(fd)
        assert error.value.errno==errno.EBADF


def test_preselection_injected_legacy_reader_gets_no_borrowed_owner(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,'_validation_session',lambda root:session(Path(root)))
    seen=[];original=ri._dependency
    def legacy(pin,base,consumed,*,limits=None,accumulator=None):
        seen.append(pin['path']);return original(pin,base,consumed,limits=limits,accumulator=accumulator)
    monkeypatch.setattr(ri,'_dependency',legacy)
    p=tmp_path/'data';p.write_bytes(b'full')
    with rp.WorkerReadOnlyObservation(tmp_path/'worker') as worker:
        m=module([p]);worker.inputs(m,{},tmp_path,'original')
        assert ri._anchored_owner(worker) is None
        assert ri._AnchoredDependencyObservation not in worker.resources
    assert len(seen)>=2


@pytest.mark.parametrize('primitive',['open','fstat','fdopen','close'])
def test_preselection_os_faults_preserve_exact_original_error_and_empty_custody(tmp_path,monkeypatch,primitive):
    p=tmp_path/'data';p.write_bytes(b'full');original=getattr(os,primitive);outcomes=[]
    def fail(*args,**kwargs):
        if primitive=='close':original(*args,**kwargs)
        raise OSError(errno.EIO,'declared real-read control failure')
    # No live owner is selected under replaced OS primitives.
    with owned(tmp_path,monkeypatch) as (_,owner):
        with monkeypatch.context() as change:
            change.setattr(os,primitive,fail)
            assert ri._anchored_owner(owner.context) is None
            for reader in (OLD['_dependency'],ri._dependency):
                consumed={}
                with pytest.raises(OSError) as error:reader(pin(p),tmp_path,consumed)
                outcomes.append((error.value.errno,str(error.value),dict(consumed)))
        assert outcomes[0]==outcomes[1] and outcomes[0][2]=={}


def test_descriptor_cap_is_optimization_only_complete_fallback_and_terminal(tmp_path,monkeypatch):
    p=tmp_path/'data';p.write_bytes(b'first')
    with owned(tmp_path,monkeypatch) as (worker,owner):
        ri._dependency(pin(p),tmp_path,{},_observation=owner)
        # Consume the actual finite cap with distinct real ordinary directories.
        for i in range(owner.MAX_DIRECTORY_FDS):
            d=tmp_path/('dir'+str(i));d.mkdir();q=d/'data';q.write_bytes(b'x')
            seen={};ri._dependency(pin(q),tmp_path,seen,_observation=owner)
            assert seen[str(q)]['size']==1
        assert len(owner.directories)<=owner.MAX_DIRECTORY_FDS
        q=tmp_path/'last';q.mkdir();q=q/'data';q.write_bytes(b'complete-fallback')
        actual={};ri._dependency(pin(q),tmp_path,actual,_observation=owner)
        assert q not in owner.records and actual[str(q)]==pin(q)
        assert (q,6) in worker.session.path_identities
        finish(worker,tmp_path)
    assert owner.acquired==[] and worker.closed


@pytest.mark.parametrize('roster',['records','acquired'])
def test_frozen_roster_and_new_resource_after_callbacks_refuse_before_write(tmp_path,monkeypatch,roster):
    p=tmp_path/'data';p.write_bytes(b'full')
    with pytest.raises(ValueError,match='roster changed'):
        with owned(tmp_path,monkeypatch) as (worker,owner):
            ri._dependency(pin(p),tmp_path,{},_observation=owner)
            worker.add_ending_check(lambda:getattr(owner,roster).clear())
            finish(worker,tmp_path)
    assert worker.closed and owner.acquired==[] and not (tmp_path/'worker'/'outputs').exists()


@pytest.mark.parametrize('callback_kind',['session','worker'])
def test_callback_enrolled_new_leaf_is_in_complete_terminal_tail(tmp_path,monkeypatch,callback_kind):
    old=tmp_path/'old';old.write_bytes(b'old');late=tmp_path/'late';late.write_bytes(b'first');intended=pin(late)
    with pytest.raises(ValueError,match='identity changed'):
        with owned(tmp_path,monkeypatch) as (worker,owner):
            ri._dependency(pin(old),tmp_path,{},_observation=owner)
            cache=tuple(owner.acquired)
            def enroll():
                ri._dependency(intended,tmp_path,{},_observation=owner)
                assert tuple(owner.acquired)==cache and late not in owner.records
            add=worker.session.retain_final_check if callback_kind=='session' else worker.add_ending_check
            add(enroll);add(lambda:late.write_bytes(b'other'))
            finish(worker,tmp_path)
    assert owner.closed and owner.acquired==[] and worker.session.closed


def test_transient_same_inode_ancestor_alias_refused_at_callback_read_even_if_restored(tmp_path,monkeypatch):
    tree=tmp_path/'tree';tree.mkdir();p=tree/'data';p.write_bytes(b'full');intended=pin(p);saved=tmp_path/'saved'
    with pytest.raises(ValueError,match='ordinary existing manuscript evidence required'):
        with owned(tmp_path,monkeypatch) as (worker,owner):
            ri._dependency(intended,tmp_path,{},_observation=owner)
            def probe():
                tree.rename(saved);tree.symlink_to(saved,target_is_directory=True)
                try:ri._dependency(intended,tmp_path,{},_observation=owner)
                finally:tree.unlink();saved.rename(tree)
            worker.add_ending_check(probe);finish(worker,tmp_path)
    assert tree.is_dir() and not tree.is_symlink() and p.read_bytes()==b'full'
    assert owner.closed and owner.acquired==[] and worker.session.closed


def test_core_close_failure_attempts_every_descriptor_and_preserves_failure(tmp_path,monkeypatch):
    p=tmp_path/'data';p.write_bytes(b'full')
    with owned(tmp_path,monkeypatch) as (worker,owner):
        ri._dependency(pin(p),tmp_path,{},_observation=owner);held=tuple(owner.acquired);called=[]
        def close_control(fd):
            called.append(fd);os.close(fd)
            if len(called)==1:raise OSError(errno.EIO,'declared first close failure')
        failures=owner.close_all(close_control)
        assert called==list(held) and len(failures)==1 and failures[0].errno==errno.EIO
        for fd in held:
            with pytest.raises(OSError) as error:os.fstat(fd)
            assert error.value.errno==errno.EBADF
        assert owner.acquired==[] and owner.records=={} and owner.directories=={}
        # This primitive carries no acceptance. Its caller must propagate error.
        with pytest.raises(OSError,match='declared first close failure'):raise failures[0]
    assert owner.closed and worker.session.closed


def test_actual_other_thread_cannot_borrow_owner(tmp_path,monkeypatch):
    import threading
    p=tmp_path/'data';p.write_bytes(b'full');out=[]
    with owned(tmp_path,monkeypatch) as (worker,owner):
        ri._dependency(pin(p),tmp_path,{},_observation=owner)
        def attempt():
            try:ri._dependency(pin(p),tmp_path,{},_observation=owner)
            except ValueError as error:out.append(str(error))
        thread=threading.Thread(target=attempt);thread.start();thread.join(timeout=5)
        assert not thread.is_alive() and len(out)==1 and 'ownership changed' in out[0]
        finish(worker,tmp_path)
    assert owner.closed and owner.acquired==[]


def test_no_selected_adapter_cannot_enroll_anchored_resource(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,'_validation_session',lambda root:session(Path(root)))
    with pytest.raises(ValueError,match='selected source-owned read-only adapter required'):
        with rp.WorkerReadOnlyObservation(tmp_path/'worker') as worker:
            ri._anchored_owner(worker)
    assert worker.closed and worker.resources=={} and worker.session.closed


def test_late_inert_core_cleanup_replacement_refuses_but_closes_every_descriptor(tmp_path,monkeypatch):
    p=tmp_path/'data';p.write_bytes(b'complete');called=[]
    with pytest.raises(ValueError,match='owner|ownership|changed'):
        with owned(tmp_path,monkeypatch) as (worker,owner):
            ri._dependency(pin(p),tmp_path,{},_observation=owner)
            held=tuple(owner.acquired);assert held
            def inert_cleanup(self,closer):
                called.append(self);return []
            monkeypatch.setattr(ri._AnchoredDirectoryCore,'close_all',inert_cleanup)
            finish(worker,tmp_path)
    assert called==[] and owner.closed and owner.acquired==[] and worker.session.closed
    assert not (tmp_path/'worker'/'outputs').exists()
    for fd in held:
        with pytest.raises(OSError) as error:os.fstat(fd)
        assert error.value.errno==errno.EBADF
