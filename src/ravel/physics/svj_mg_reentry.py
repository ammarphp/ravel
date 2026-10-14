"""Finite original-MG named-run reload adapter in the existing native child.

Only _native_main imports MG, after its approved source/request authentication.
Pure controls may install the adapter on exact extracted method bodies with inert
state. It adds no generator, shower engine, optimizer or execution supervisor.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import stat
import sys

LIMIT=2*1024**2
MODE='mg_2_9_27_svj_pythia8_reload_v1'
SOURCE_HASHES={
 'bin/mg5_aMC':'8f28d327b8aa6c81e4e976a7a29b5e5dbf9871c77118b807ed148ca263567ace',
 'madgraph/interface/master_interface.py':'54c5068f43725f1aa78ea0f578d1be0cd8ea13692a1e7175a786e2fc4788045e',
 'madgraph/interface/madgraph_interface.py':'04c293c5e478b5ce525fbc625bdc8bf81b70ad9c52c8f467df4a91d1561adada',
 'madgraph/interface/madevent_interface.py':'0f59f5a9300985fabc5da3156e42a2c6dc080b632fb94a50016284354cd402d8',
 'madgraph/interface/common_run_interface.py':'0e915210fffd2fddead6b36ed06390d528e378664daba7555bce3d86c1ba1d98',
 'madgraph/interface/extended_cmd.py':'133a0109fba0958612a7ab1fb7f13624073833c2bea0426453877e7d4367c7ee',
 'madgraph/various/banner.py':'17b4b0ed0b13afa013a94e6715c47a4fb1552ee160347cd3b9db644fb89c4ee9'}


def require(ok,message):
    if not ok:raise ValueError(message)


def _unique(rows):
    result={}
    for k,v in rows:
        require(k not in result,'duplicate native adapter field');result[k]=v
    return result


def _primitive(value,depth=0):
    require(depth<=32,'bounded native reader state required')
    if value is None or type(value) in (str,bool,int):return value
    if type(value) is float:
        require(math.isfinite(value),'nonfinite native card state');return value
    if isinstance(value,(list,tuple)):
        require(len(value)<=16384,'bounded native field population required')
        return [_primitive(v,depth+1) for v in value]
    if isinstance(value,dict):
        require(len(value)<=16384 and all(type(k) is str for k in value),'literal native field identity required')
        return {k:_primitive(v,depth+1) for k,v in value.items()}
    raise ValueError('unsupported native reader value; no silent scalar conversion')


def _identity(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns


def read_pinned(path,expected):
    p=Path(path).absolute()
    require(not any(x.is_symlink() for x in (p,*p.parents)),'regular native source/input endpoint required')
    before=p.stat();require(stat.S_ISREG(before.st_mode) and before.st_size<=LIMIT,'bounded native adapter document required')
    with p.open('rb') as f:
        start=os.fstat(f.fileno());raw=f.read(LIMIT+1);end=os.fstat(f.fileno())
    require(len(raw)<=LIMIT and _identity(before)==_identity(start)==_identity(end)==_identity(p.stat()),'native adapter source/input changed during read')
    digest=hashlib.sha256(raw).hexdigest();require(digest==expected,'native adapter source/input digest differs')
    return raw


def _append(path,row):
    raw=(json.dumps(row,allow_nan=False,sort_keys=True)+'\n').encode()
    p=Path(path);require((p.stat().st_size if p.exists() else 0)+len(raw)<=LIMIT,'native reentry journal exceeds 2MiB')
    with p.open('ab') as f:f.write(raw);f.flush();os.fsync(f.fileno())


def install(cls,request,journal,*,source_path):
    """Preserve original check mutation/result, then use its same-name reload API."""
    original=cls.check_pythia8
    require(Path(original.__code__.co_filename).absolute()==Path(source_path).absolute(),
            'loaded original method belongs to foreign source')
    require(not Path(journal).exists(),'fresh original-API observation journal required')
    state={'calls':0,'failed':False}
    def checked(self,args):
        state['calls']+=1
        try:
            require(state['calls']==1,'one intended original shower check invocation required')
            require(Path(self.me_dir).absolute()==Path(request['process']).absolute(), 'foreign native exported process')
            require(self.run_name is None,'finite phase adapter requires the original fresh unselected session')
            before_args=copy.deepcopy(_primitive(args))
            returned=original(self,args)
            native_args=copy.deepcopy(_primitive(args))
            require(self.run_name=='ravel','original check selected foreign hard run')
            before=_primitive(dict(self.run_card))
            require(before.get('event_norm')=='sum' and before.get('nevents')==request['complete_N'] and
                    before.get('iseed')==request['hard_seed'],'original named selection must consume authentic hard banner law')
            card=request['operative_run_card'];read_pinned(card['path'],card['sha256'])
            self.set_run_name(self.run_name,level='pythia8',reload_card=True)
            after=_primitive(dict(self.run_card))
            require(set(before)==set(after),'complete native reloaded field population changed')
            require(after.get('event_norm')=='average' and after.get('iseed')==0 and
                    after.get('nevents')==request['complete_N'],'actual native derived representation/ending seed differs')
            require(all(after[k]==v for k,v in before.items() if k not in ('event_norm','iseed')),
                    'unapproved native card or run-tag change during reloading')
            require(_primitive(args)==native_args,'wrapper changed original argument mutations')
            require(self.options.get('delphes_path') is None,'native detector option must remain explicitly disabled')
            read_pinned(card['path'],card['sha256'])
            _append(journal,{'kind':'native_original_card_reload','mode':MODE,'original_arguments_before':before_args,
                'original_arguments_after':native_args,'original_result':_primitive(returned),'loaded_source':str(Path(source_path).absolute()),
                'process':request['process'],'before_native_fields':before,'after_native_fields':after,
                'operative_run_card':card,'driver_sha256':request['driver_sha256'],'scientific_acceptance':False})
            return returned
        except BaseException as exc:
            state['failed']=True
            _append(journal,{'kind':'native_card_reload_error','call':state['calls'],'error':type(exc).__name__,
                'message':str(exc),'scientific_acceptance':False})
            raise
    cls.check_pythia8=checked
    def restore():cls.check_pythia8=original
    return state,restore


def _native_main(argv):
    require(len(argv)==4,'closed native reentry arguments required')
    mg,request_file,journal=map(Path,argv[:3]);expected=argv[3]
    for rel,sha in SOURCE_HASHES.items():read_pinned(mg/rel,sha)
    def bad(_x):raise ValueError('nonfinite native reentry declaration')
    request=json.loads(read_pinned(request_file,expected),object_pairs_hook=_unique,parse_constant=bad)
    require(set(request)=={'schema_version','mode','script','process','operative_run_card','driver_sha256','hard_seed','complete_N'} and
            type(request['schema_version']) is int and request['schema_version']==1 and request['mode']==MODE,
            'closed original native reentry mode required')
    require(request['driver_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'native reentry driver changed')
    require(type(request['complete_N']) is int and 1<=request['complete_N']<=1000000 and
            type(request['hard_seed']) is int and 1<=request['hard_seed']<=30000081,'bounded original hard cohort/seed required')
    read_pinned(request['script']['path'],request['script']['sha256'])
    read_pinned(request['operative_run_card']['path'],request['operative_run_card']['sha256'])
    sys.path.insert(0,str(mg))
    from madgraph.interface.madevent_interface import MadEventCmd  # ONLY in approved native child.
    require(MadEventCmd.__name__=='MadEventCmd' and MadEventCmd.__module__=='madgraph.interface.madevent_interface' and
            MadEventCmd.check_pythia8.__qualname__=='CheckValidForCmd.check_pythia8',
            'actual released class/inherited method mapping differs')
    state,restore=install(MadEventCmd,request,journal,source_path=mg/'madgraph/interface/madevent_interface.py')
    try:
        require(not __debug__,'native reentry retains MG optimized interpreter mode')
        sys.argv=[str(mg/'bin/mg5_aMC'),'--nocaffeinate',request['script']['path']]
        try:runpy.run_path(str(mg/'bin/mg5_aMC'),run_name='__main__')
        except SystemExit as exc:
            if exc.code not in (0,None):raise
        require(state['calls']==1 and not state['failed'],'complete one-call native card reload observation required')
        read_pinned(request_file,expected)
        read_pinned(request['script']['path'],request['script']['sha256'])
        _append(journal,{'kind':'native_reentry_dispatch_complete','mode':MODE,'calls':1,
            'original_bin_dispatch':str(mg/'bin/mg5_aMC'),'script':request['script'],
            'driver_sha256':request['driver_sha256'],'scientific_acceptance':False})
    finally:restore()


if __name__=='__main__':_native_main(sys.argv[1:])
