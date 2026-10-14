"""MG2.9.27 regular LO returned-survey state, under ordinary study authority.

This is a same-run codec, not an independent sample or an execution permission.
Unknown native types, live integration children and incomplete snapshots refuse.
The original run_generate_events body owns every remaining native operation.
"""
import builtins
from collections import defaultdict
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import subprocess
import sys

KIND = 'mg5-2.9.27-LO-completed-survey/v1'
CONTROL_KIND = 'same-run-continuation-reservations/v1'
CONTROL_BYTES = 1024**2
CONTROL_ENTRIES = 512
NATIVE_CLASSES = {
    'madgraph.madevent.gen_crossxhtml': ('AllResults', 'RunResults', 'OneTagResults'),
    'madgraph.madevent.sum_html': ('RunStatistics',),
    'madgraph.various.banner': ('Banner', 'RunCardLO'),
}
STATE_FIELDS = ('results', 'run_name', 'run_tag', 'run_card', 'banner', 'random',
                'random_orig', 'nb_refine', 'opts', 'history', 'Gdirs', '_options',
                'to_store', 'total_jobs')
ENVIRONMENT_KEYS = ('PATH','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH',
                    'LIBRARY_PATH','CPATH','CPLUS_INCLUDE_PATH','CFLAGS','CXXFLAGS','FFLAGS','FCFLAGS',
                    'LDFLAGS','LHAPDF_DATA_PATH','PDFSETS','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS',
                    'MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
SOURCE_NAMES = ('VERSION', 'madgraph/interface/madevent_interface.py',
                'madgraph/interface/common_run_interface.py',
                'madgraph/madevent/gen_crossxhtml.py', 'madgraph/madevent/sum_html.py',
                'madgraph/madevent/gen_ximprove.py', 'madgraph/various/banner.py',
                'madgraph/interface/launch_ext_program.py')
PRIMARY = {'VERSION': '3edf2639a68ac422023a59de8f5cc7709ff7a139620d51ea7ad465cfefa16f99', 'madgraph/interface/madevent_interface.py': '0f59f5a9300985fabc5da3156e42a2c6dc080b632fb94a50016284354cd402d8', 'madgraph/interface/common_run_interface.py': '0e915210fffd2fddead6b36ed06390d528e378664daba7555bce3d86c1ba1d98', 'madgraph/madevent/gen_crossxhtml.py': '6a6461eff596a9ee2fb4acdced8894ad8c7e4a3df2c286691b814d2935cb8924', 'madgraph/madevent/sum_html.py': 'b9bbf9f686025d7ab76d9b9b6e1d9990b11f90d2380c3499635e668cd0b6a5f8', 'madgraph/madevent/gen_ximprove.py': '9a0e2c45f8fa5bfef3fbaa14ee532911df31a664db948fca496d9ab3ca711515', 'madgraph/various/banner.py': '17b4b0ed0b13afa013a94e6715c47a4fb1552ee160347cd3b9db644fb89c4ee9', 'madgraph/interface/launch_ext_program.py': 'c8ae304b0fa6d878c6718a972e9c6f61312e9892958bccfbcf15523795975ba8'}


def require(ok, message):
    if not ok: raise ValueError(message)


def storage(support=None):
    if support is not None: return support
    from . import generator_reuse
    return generator_reuse


def validate(policy):
    require(type(policy) is dict and set(policy) == {'candidate', 'max_files', 'max_bytes', 'max_member_bytes'},
            'complete explicit checkpoint policy required')
    for key, limit in (('max_files', 100000), ('max_bytes', 4*1024**3), ('max_member_bytes', 128*1024**2)):
        require(type(policy[key]) is int and 1 <= policy[key] <= limit, 'finite checkpoint '+key+' required')
    require(policy['max_member_bytes'] <= policy['max_bytes'], 'checkpoint member exceeds total ceiling')
    c = policy['candidate']
    if c is not None:
        require(type(c) is dict and set(c) == {'rundir', 'attempt', 'checkpoint_sha256'}, 'exact original checkpoint origin required')
        require(type(c['rundir']) is str and c['rundir'] and type(c['attempt']) is int and c['attempt'] >= 1,
                'original run and attempt required')
        require(type(c['checkpoint_sha256']) is str and re.fullmatch('[0-9a-f]{64}', c['checkpoint_sha256']), 'checkpoint digest required')
    return policy


def source_inputs(root, support=None):
    s = storage(support)
    result = []
    for name, digest in PRIMARY.items():
        path = Path(root)/name
        require(not any(x.is_symlink() for x in (path,*path.parents)), 'checkpoint native source alias refused')
        require(hashlib.sha256(s.regular_bytes(path,16*1024**2)).hexdigest() == digest, 'checkpoint requires exact released native source: '+name)
        result.append(path)
    require(set(PRIMARY) == set(SOURCE_NAMES), 'complete native checkpoint source contract required')
    return result


def registry(root, support=None):
    """Only native classes from pinned, already admitted engine source; no pickle."""
    source_inputs(root,support); result = {}
    for module, names in NATIVE_CLASSES.items():
        loaded = importlib.import_module(module)
        require(Path(loaded.__file__).resolve() == (Path(root)/(module.replace('.', '/')+'.py')).resolve(),
                'foreign native state class module')
        for name in names:
            cls = vars(loaded)[name]
            require(type(cls) is type and cls.__module__ == module, 'foreign native state class')
            result[module+'.'+name] = cls
    return result


def encode_graph(value, classes):
    """Preserve exact builtin types, native attributes and shared current-record identity."""
    names = {cls: name for name, cls in classes.items()}; nodes = []; seen = {}
    type_names = {getattr(builtins, n): n for n in ('int', 'float', 'bool', 'str', 'list', 'dict', 'tuple')}
    def visit(v):
        t = type(v)
        if v is None or t in (bool, int, str): return {'scalar': t.__name__, 'value': v}
        if t is float:
            require(not math.isnan(v), 'NaN native state refused')
            return {'scalar': 'float', 'hex': v.hex()}
        if t is type and v in type_names: return {'builtin_type': type_names[v]}
        if t is bytes: return {'scalar': 'bytes', 'hex': v.hex()}
        require(t in (dict, list, tuple, set,defaultdict) or t in names, 'unsupported live native state type: '+t.__module__+'.'+t.__name__)
        if id(v) in seen: return {'ref': seen[id(v)]}
        i = len(nodes); require(i < 100000, 'native state graph ceiling exceeded'); seen[id(v)] = i
        kind = 'dict' if isinstance(v, dict) else 'list' if isinstance(v, list) else 'tuple' if t is tuple else 'set'
        node = {'kind': kind, 'class': 'collections.defaultdict' if t is defaultdict else names.get(t), 'items': [], 'attributes': {}}; nodes.append(node)
        if t is defaultdict:
            require(v.default_factory is list, 'only released RunCard defaultdict(list) factory supported')
            node['default_factory'] = visit(list)
        if kind == 'set':
            require(all(type(x) in (str,int,bool,float) for x in v), 'unsupported compound native set')
            values = sorted(v, key=lambda x: (type(x).__name__,repr(x)))
        else: values = v
        node['items'] = [[visit(k), visit(x)] for k,x in v.items()] if kind == 'dict' else [visit(x) for x in values]
        # Attribute insertion order is not native mapping iteration. Stable
        # traversal survives canonical JSON while dictionary items stay exact.
        if t in names: node['attributes'] = {k: visit(x) for k,x in sorted(vars(v).items())}
        return {'ref': i}
    return {'root': visit(value), 'nodes': nodes}


def decode_graph(record, classes):
    nodes = record['nodes']; require(type(nodes) is list and len(nodes) <= 100000, 'bounded native graph required')
    made = {}; constructing = set()
    def visit(v):
        if 'scalar' in v:
            t = v['scalar']
            if t == 'float': return float.fromhex(v['hex'])
            if t == 'bytes': return bytes.fromhex(v['hex'])
            require(t in ('NoneType','bool','int','str') and type(v['value']).__name__ == t, 'typed native scalar differs')
            return v['value']
        if 'builtin_type' in v:
            require(v['builtin_type'] in ('int','float','bool','str','list','dict','tuple'), 'unknown native builtin type')
            return getattr(builtins, v['builtin_type'])
        i = v['ref']; require(type(i) is int and 0 <= i < len(nodes), 'native graph reference differs')
        if i in made: return made[i]
        require(i not in constructing, 'immutable native graph cycle refused'); constructing.add(i)
        n = nodes[i]; cls = None if n['class'] is None else defaultdict if n['class']=='collections.defaultdict' else classes.get(n['class'])
        require(n['class'] is None or cls is not None, 'unknown native state class')
        if n['kind'] == 'dict':
            obj = defaultdict(list) if cls is defaultdict else dict.__new__(dict if cls is None else cls); made[i] = obj
            if cls is defaultdict: require(visit(n['default_factory']) is list, 'released native default-factory differs')
            for k,x in n['items']: dict.__setitem__(obj, visit(k), visit(x))
        elif n['kind'] == 'list':
            obj = list.__new__(list if cls is None else cls); made[i] = obj
            list.extend(obj, [visit(x) for x in n['items']])
        elif n['kind'] == 'tuple':
            require(cls is None, 'unknown tuple subtype'); obj = tuple(visit(x) for x in n['items']); made[i] = obj
        elif n['kind'] == 'set':
            require(cls is None, 'unknown set subtype'); obj = set(visit(x) for x in n['items']); made[i] = obj
        else: raise ValueError('unknown native graph kind')
        if cls is not None and cls is not defaultdict:
            for k,x in n['attributes'].items(): setattr(obj, k, visit(x))
        else: require(not n['attributes'], 'builtin state cannot carry native attributes')
        constructing.remove(i); return obj
    result = visit(record['root'])
    # This rejects malformed/extra fields and lossy decoding, not just a decoded success flag.
    require(encode_graph(result, classes) == record, 'native state intended roundtrip differs')
    return result


def process_table():
    observer = subprocess.Popen(['ps','-axo','pid=,ppid=,pgid=,stat='], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try: stdout, stderr = observer.communicate(timeout=5)
    except BaseException:
        observer.kill(); observer.communicate(); raise
    require(observer.returncode == 0, 'native process census failed')
    # Exclude only this exact source-owned transient census command.
    return [{'pid': int(a), 'parent': int(b), 'group': int(c), 'state': d}
            for a,b,c,d in (line.split() for line in stdout.splitlines()) if int(a) != observer.pid]


def quiescent_children(table, pid, group):
    by_pid = {r['pid']: r for r in table}; ancestors = set(); cursor = pid
    while cursor in by_pid and cursor not in ancestors:
        ancestors.add(cursor); cursor = by_pid[cursor]['parent']
    owned = [r for r in table if r['group'] == group]
    descendants = {pid}
    while True:
        extended = descendants | {r['pid'] for r in table if r['parent'] in descendants}
        if extended == descendants: break
        descendants = extended
    require(owned and descendants == {pid} and all(r['pid'] in ancestors for r in owned), 'integration descendants remain at survey capture')
    return owned


def native_owner(cmd, root, support):
    """Fresh marker from constructor or the released enclosing RunWebHandling."""
    marker = support.regular_bytes(Path(cmd.me_dir)/'RunWeb',128)
    require(int(marker) == os.getpid() and type(cmd.force_run) is bool, 'fresh source-owned native RunWeb marker required')
    if cmd.force_run:
        # The ordinary MG launcher owns RunWeb itself and deliberately passes
        # force_run=True to its child. This is not an arbitrary force override.
        module = importlib.import_module('madgraph.interface.launch_ext_program')
        path = Path(root)/'madgraph/interface/launch_ext_program.py'
        require(Path(module.__file__).resolve() == path.resolve(), 'foreign native owner launcher')
        method = module.MELauncher.__dict__['launch_program']
        require(Path(method.__code__.co_filename).resolve() == path.resolve(), 'foreign native owner launcher implementation')
        frame = sys._getframe(1); matched = False
        try:
            while frame is not None:
                if frame.f_code is method.__code__:
                    owner=frame.f_locals.get('self')
                    matched=(frame.f_locals.get('usecmd') is cmd and owner is not None
                             and Path(owner.running_dir) == Path(cmd.me_dir))
                    break
                frame=frame.f_back
        finally: del frame
        require(matched, 'forced native child requires actual released enclosing RunWebHandling launcher')
    return marker


def compatibility(c, base):
    r = deepcopy(c); r.pop('integration_checkpoint', None); r.pop('max_seconds'); r.pop('source')
    def paths(v):
        if type(v) is dict:
            for k,x in v.items():
                if k in ('path','root') and type(x) is str:
                    v[k] = str((Path(base)/x).resolve())
                else: paths(x)
        elif type(v) is list:
            for x in v: paths(x)
    paths(r)
    for k,x in r['runtime']['options'].items():
        if x is not None: r['runtime']['options'][k] = str((Path(base)/x).resolve())
    return r


def _relocate(value, roots, target):
    if type(value) is str:
        matches = [(role, old) for role, old in roots.items() if value == old or value.startswith(old+'/')]
        if matches:
            role, old = max(matches, key=lambda x: len(x[1])); return target[role]+value[len(old):]
    return value


def relocated_graph(graph, roots, target):
    result = deepcopy(graph)
    def walk(v):
        if type(v) is dict:
            if v.get('scalar') == 'str': v['value'] = _relocate(v['value'], roots, target)
            for x in v.values(): walk(x)
        elif type(v) is list:
            for x in v: walk(x)
    walk(result); return result


def channel_state(cmd, support, maximum, native_root):
    """Read the released symfact/Gdir/result law; zero channels remain explicit.

    The real OneResult reader is used, not a guessed coefficient/parser. This
    is operational completeness and retained diagnostics, not precision closure.
    """
    module = importlib.import_module('madgraph.madevent.sum_html')
    require(Path(module.__file__).resolve() == (Path(native_root)/'madgraph/madevent/sum_html.py').resolve(),
            'foreign native channel result reader')
    rows = []; base = Path(cmd.me_dir)
    roster = support.regular_bytes(base/'SubProcesses/subproc.mg', maximum).decode().splitlines()
    for process in roster:
        directory = base/'SubProcesses'/process
        require(all(stat.S_ISDIR(p.lstat().st_mode) for p in (base,base/'SubProcesses',directory)),
                'source subprocess directory alias refused')
        symfact = support.regular_bytes(directory/'symfact.dat', maximum)
        selected = []
        for line in symfact.decode().splitlines():
            tag, factor = line.split()
            if int(factor) > 0: selected.append(('G'+tag, factor))
        require(len(selected) == len(set(x[0] for x in selected)), 'duplicate source-selected survey channel')
        no_phase_space = directory/'ajob.no_ps.log'
        # do_survey records these source-produced zero subprocesses in Gdirs.
        excluded = cmd.Gdirs is not None and str(directory) in cmd.Gdirs[0] and not cmd.Gdirs[0][str(directory)]
        if excluded:
            raw = support.regular_bytes(no_phase_space, maximum)
            rows.append({'process': process, 'zero_phase_space': True, 'source_log': hashlib.sha256(raw).hexdigest(),
                         'symfact_sha256': hashlib.sha256(symfact).hexdigest(), 'channels': []})
            continue
        channels = []
        if cmd.Gdirs is not None and str(directory) in cmd.Gdirs[0]:
            require(sorted(cmd.Gdirs[0][str(directory)]) == sorted(str(directory/channel) for channel,_ in selected),
                    'live source-selected channel population differs')
        for channel, factor in selected:
            require(re.fullmatch(r'G[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?',channel) and stat.S_ISDIR((directory/channel).lstat().st_mode),
                    'source channel directory alias or name refused')
            path = directory/channel/'results.dat'; raw = support.regular_bytes(path, maximum)
            require(raw and len(raw.splitlines()[0].split()) >= 10, 'uncommitted or malformed native survey result')
            result = module.OneResult(channel)
            result.read_results(str(path))
            numbers = (result.axsec,result.xsec,result.xerru,result.xerrc,result.nevents,result.nw,
                       result.maxit,result.nunwgt,result.luminosity,result.wgt,result.maxwgt)
            require(all(type(x) in (int,float) and math.isfinite(x) for x in numbers), 'invalid native survey result')
            grids = []
            for name in ('ftn25','ftn26'):
                grid = directory/channel/name
                if grid.exists():
                    data = support.regular_bytes(grid, maximum)
                    require(data, 'empty committed native grid')
                    grids.append({'relative':grid.relative_to(base).as_posix(), 'sha256':hashlib.sha256(data).hexdigest(), 'size':len(data)})
            # The released split survey prepares ftn26; the unsplit survey
            # prepares ftn25. Full trees retain both whenever both exist.
            require(result.axsec == 0 or grids, 'nonzero channel lacks committed native grid')
            channels.append({'channel':channel,'symmetry_factor':factor,'result_sha256':hashlib.sha256(raw).hexdigest(),
                'result_size':len(raw),'native_result':encode_graph(vars(result), {'madgraph.madevent.sum_html.RunStatistics':module.RunStatistics}),
                'grids':grids})
        rows.append({'process':process,'zero_phase_space':False,'symfact_sha256':hashlib.sha256(symfact).hexdigest(),'channels':channels})
    return rows


def integration_products(record):
    """The sealed channel folders, seed and loop resources survive fresh setup."""
    for row in record['tree']['rows']:
        parts = Path(row['relative']).parts
        if (row['relative'] == 'SubProcesses/randinit' or
                len(parts) >= 3 and parts[0] == 'SubProcesses' and
                (parts[1] == 'MadLoop5_resources' or parts[1].startswith('P') and parts[2].startswith('G'))):
            yield row


def check_materialized(rows, process, roots, record, support, *, limits=None):
    """Ending bytes/modes/link targets are checked against intended snapshot rows."""
    effective=effective_limits(record,limits)
    for row in rows:
        p = Path(process)/support._relative(row['relative']); st = p.lstat()
        require(stat.S_IMODE(st.st_mode) == row['mode'], 'continuation member mode changed')
        if row['type'] == 'file':
            expected = support._blob_bytes(row,min(row['blob']['size'],effective['max_member_bytes']))
            if row['relative'] == 'Cards/me5_configuration.txt': expected = relocated_configuration(expected,record,roots)
            require(support.regular_bytes(p,min(len(expected),effective['max_member_bytes'])) == expected, 'continuation member bytes changed')
        elif row['type'] == 'directory': require(stat.S_ISDIR(st.st_mode), 'continuation directory kind changed')
        elif row['type'] == 'link':
            require(stat.S_ISLNK(st.st_mode) and os.readlink(p) == os.path.relpath(Path(roots[row['role']])/support._relative(row['target']),p.parent),
                    'continuation link target changed')
        else: raise ValueError('unknown checkpoint member')


def relocated_configuration(raw, record, roots):
    lines = []
    for line in raw.decode().splitlines(keepends=True):
        active = line.split('#',1)[0].strip()
        if active and active.split('=',1)[0].strip() == 'mg5_path':
            require(active.split('=',1)[1].strip() == record['tree']['roots']['madgraph'], 'unqualified original MG path')
            line = 'mg5_path = '+roots['madgraph']+'\n'
        lines.append(line)
    return ''.join(lines).encode()


def capture_tree(process, destination, policy, roots, support):
    before = support._structure(process, policy['max_files']); rows = []; total = 0; references=0
    for row in before[1]:
        p = Path(process)/row['relative']; item = {'relative': row['relative'], 'type': row['type'],
            'mode': stat.S_IMODE(row['identity'][2]), 'mtime_ns': row['identity'][4]}
        if row['type'] == 'file':
            raw = support.regular_bytes(p, policy['max_member_bytes']); total += max(len(raw), len(support.encoded(support._EMPTY)) if not raw else 0)
            require(total <= policy['max_bytes'], 'complete checkpoint byte ceiling exceeded')
            item.update(support._store_blob(Path(destination)/'tree'/row['relative'], raw))
            Path(item['blob']['path']).chmod(0o600)
        elif row['type'] == 'link':
            target = Path(os.path.abspath(p.parent/row['literal']))
            matched = [(k, Path(v)) for k,v in roots.items() if target.is_relative_to(Path(v))]
            require(matched, 'checkpoint alias outside authenticated complete roots')
            role, root = max(matched, key=lambda x: len(x[1].parts))
            item.update(role=role, target=target.relative_to(root).as_posix(), literal=row['literal'])
            if role != 'process':
                if target.is_dir():
                    remaining=dict(policy,max_files=policy['max_files']-len(before[1])-references,max_bytes=policy['max_bytes']-total)
                    require(remaining['max_files']>0 and remaining['max_bytes']>0,'checkpoint linked closure exceeds budget')
                    item['target_directory']=support._source_directory(target,remaining)
                    references+=len(item['target_directory']['rows']); total+=item['target_directory']['total_bytes']
                else:
                    raw = support.regular_bytes(target, policy['max_member_bytes']); total += len(raw); references+=1
                    item.update(target_sha256=hashlib.sha256(raw).hexdigest(), target_size=len(raw),target_mode=stat.S_IMODE(target.lstat().st_mode))
                require(total <= policy['max_bytes'] and len(before[1])+references <= policy['max_files'], 'checkpoint reference closure ceiling exceeded')
        rows.append(item)
    require(support._structure(process, policy['max_files']) == before, 'survey process changed during snapshot')
    return {'root': str(destination), 'roots': roots, 'options': policy, 'rows': rows, 'total_bytes': total, 'referenced_files': references}


def effective_limits(record, limits=None):
    old=validate(record['tree']['options'])
    if limits is None:return old
    current=validate(limits)
    return dict(current,**{k:min(old[k],current[k]) for k in ('max_files','max_bytes','max_member_bytes')})


def verify(record, support=None, *, limits=None):
    s = storage(support); require(record['kind'] == KIND and record['physics_validated'] is False, 'unqualified same-run checkpoint required')
    effective=effective_limits(record,limits)
    root = Path(record['tree']['root'])
    # Reject the complete declared closure before reading any larger payload.
    declared=sum(x['blob']['size'] for x in record['tree']['rows'] if x['type']=='file')
    for x in record['tree']['rows']:
        if x['type']=='file':require(x['blob']['size']<=effective['max_member_bytes'],'checkpoint member exceeds current ceiling')
        elif x['type']=='link' and x['role']!='process':
            if 'target_directory' in x:
                declared+=x['target_directory']['total_bytes']
                require(all(r['size']<=effective['max_member_bytes'] for r in x['target_directory']['rows'] if r['type']=='file'),'checkpoint reference member exceeds current ceiling')
            else:
                declared+=x['target_size'];require(x['target_size']<=effective['max_member_bytes'],'checkpoint reference exceeds current member ceiling')
    metadata=len(s.encoded(record))+record['survey_stdout']['size']+record['continuation_control']['genesis']['size']
    require(record['continuation_control']['genesis']['size']<=effective['max_member_bytes'],'checkpoint genesis exceeds current member ceiling')
    require(len(s.encoded(record))<=effective['max_member_bytes'] and record['survey_stdout']['size']<=effective['max_member_bytes'],'checkpoint metadata exceeds current member ceiling')
    require(declared+metadata<=effective['max_bytes'],'complete checkpoint exceeds current capacity')
    require(len(record['tree']['rows'])+record['tree']['referenced_files']+1<=effective['max_files'],'complete checkpoint exceeds current file capacity')
    genesis=record['continuation_control']['genesis'];control=_control_directory(record['original'],s)
    require(genesis['path']==str(control/'genesis.json') and record['continuation_control']['root']==str(control),'foreign checkpoint genesis')
    require(not any(p.is_symlink() for p in (control,*control.parents)),'checkpoint genesis ancestor alias refused')
    genesis_raw=s.regular_bytes(genesis['path'],min(genesis['size'],effective['max_member_bytes']))
    require(len(genesis_raw)==genesis['size'] and hashlib.sha256(genesis_raw).hexdigest()==genesis['sha256'],'checkpoint genesis changed')
    before = s._structure(root, effective['max_files']*2+4)
    expected = {'checkpoint.json', 'survey-stdout-prefix.bin'} | {'tree/'+x['relative'] for x in record['tree']['rows'] if x['type'] == 'file'}
    s._closed_storage(root, before, expected)
    require(all(stat.S_IMODE(x['identity'][2]) == (0o600 if x['type']=='file' else 0o700) for x in before[1]) and
            stat.S_IMODE(root.lstat().st_mode)==0o700, 'immutable checkpoint storage mode changed')
    require(s.regular_bytes(root/'checkpoint.json',min(len(s.encoded(record)),effective['max_bytes'],effective['max_member_bytes'])) == s.encoded(record), 'checkpoint manifest changed')
    require(len(record['tree']['rows']) == len(set(x['relative'] for x in record['tree']['rows'])), 'duplicate checkpoint member')
    total = 0; references = 0
    for row in record['tree']['rows']:
        s._relative(row['relative'])
        if row['type'] == 'file':
            require(Path(row['blob']['path']) == root/'tree'/row['relative'], 'foreign checkpoint storage')
            raw = s._blob_bytes(row, min(row['blob']['size'],effective['max_member_bytes'])); total += row['blob']['size']
        elif row['type'] == 'link' and row['role'] != 'process':
            target = Path(record['tree']['roots'][row['role']])/row['target']
            if 'target_directory' in row:
                actual=reference_directory(target,row['target_directory'],effective,s)
                require(actual==row['target_directory'],'checkpoint linked directory changed'); total+=actual['total_bytes']; references+=len(actual['rows'])
            else:
                raw = s.regular_bytes(target, min(row['target_size'],effective['max_member_bytes'])); total += len(raw)
                require(hashlib.sha256(raw).hexdigest() == row['target_sha256'] and len(raw) == row['target_size'], 'checkpoint linked source changed')
                require(stat.S_IMODE(target.lstat().st_mode)==row['target_mode'], 'checkpoint linked source mode changed')
                references+=1
    prefix = s.regular_bytes(root/'survey-stdout-prefix.bin', min(record['survey_stdout']['size'],effective['max_member_bytes']))
    require(hashlib.sha256(prefix).hexdigest() == record['survey_stdout']['sha256'] and len(prefix) == record['survey_stdout']['size'], 'original survey stdout prefix changed')
    require(total == record['tree']['total_bytes'], 'checkpoint byte census differs')
    require(references == record['tree']['referenced_files'], 'checkpoint reference census differs')
    require(total+len(prefix)+len(s.encoded(record))+record['continuation_control']['genesis']['size']<=effective['max_bytes'],'complete checkpoint capacity exceeded')
    require(len(record['tree']['rows'])+record['tree']['referenced_files']+1<=effective['max_files'],'complete checkpoint file capacity exceeded')
    require(s._structure(root, effective['max_files']*2+4) == before, 'checkpoint ending population changed')
    return record


def capture(cmd, request, support):
    policy = validate(request['policy']); require(policy['candidate'] is None, 'capture cannot replace an original checkpoint')
    require(Path(cmd.me_dir) == Path(request['process']) and cmd.run_name == 'ravel' and cmd.nb_refine == 0,
            'only first returned original survey may be captured')
    require(not cmd.run_card['gridpack'] and not cmd.param_card_iterator, 'regular non-scan LO only')
    require(cmd.cluster_mode in (0,2) and cmd.options['run_mode'] in (0,2), 'local native owner only; remote scheduler evidence unavailable')
    require(cmd.random_orig == request['config']['generation']['seed'] and cmd.run_card['iseed'] == 0, 'original operative seed state differs')
    classes = registry(request['madgraph'],support); state = {k: getattr(cmd, k) for k in STATE_FIELDS}
    require(type(cmd.results) is classes['madgraph.madevent.gen_crossxhtml.AllResults'] and
            type(cmd.results.current) is classes['madgraph.madevent.gen_crossxhtml.OneTagResults'] and
            all(type(x) is classes['madgraph.madevent.gen_crossxhtml.RunResults'] for x in cmd.results.values()),
            'actual live native result classes required')
    require(type(cmd.run_card) is classes['madgraph.various.banner.RunCardLO'] and
            type(cmd.banner) is classes['madgraph.various.banner.Banner'], 'actual native LO card/banner classes required')
    require(all(type(x) is classes['madgraph.madevent.sum_html.RunStatistics'] for x in cmd.results.current['run_statistics'].values()),
            'actual native RunStatistics values required')
    require(cmd.results.current is cmd.results[cmd.run_name][cmd.results[cmd.run_name].tags.index(cmd.run_tag)], 'live current tag identity differs')
    require(type(cmd.results.current['run_statistics']) is dict, 'complete live survey statistics required')
    require(not (Path(cmd.me_dir)/'error').exists(), 'native survey error marker cannot become checkpoint')
    roster=support.regular_bytes(Path(cmd.me_dir)/'SubProcesses/subproc.mg',policy['max_member_bytes']).decode().splitlines()
    require(roster and len(roster)==len(set(roster)) and all(re.fullmatch(r'P[^/\\]+',x) and (Path(cmd.me_dir)/'SubProcesses'/x).is_dir() for x in roster),
            'complete original source subprocess roster required')
    graph = encode_graph(state, classes); require(encode_graph(decode_graph(graph, classes), classes) == graph, 'live native state codec differs')
    channels = channel_state(cmd,support,policy['max_member_bytes'],request['madgraph'])
    table = process_table(); owned = quiescent_children(table, os.getpid(), os.getpgrp())
    marker = native_owner(cmd,request['madgraph'],support)
    # Flush authentic native logger handlers; copy bytes, never synthesize seed text.
    import logging
    sys.stdout.flush();sys.stderr.flush()
    for logger in (logging.getLogger(), logging.getLogger('madgraph.stdout')):
        for handler in logger.handlers: handler.flush()
    stdout = support.regular_bytes(Path(request['stdout']), policy['max_member_bytes'])
    require(re.findall(rb'Using random number seed offset = (\d+)\b', stdout) == [str(cmd.random_orig).encode()], 'one actual original survey seed line required')
    destination = Path(request['destination']); require(not destination.exists(), 'fresh checkpoint destination required')
    destination.mkdir(mode=0o700);destination.chmod(0o700)
    tree = capture_tree(Path(cmd.me_dir), destination, policy, request['roots'], support)
    support.write_bytes(destination/'survey-stdout-prefix.bin', stdout);(destination/'survey-stdout-prefix.bin').chmod(0o600)
    record = {'schema_version': 1, 'kind': KIND, 'physics_validated': False, 'state': graph, 'tree': tree,
        'python_random_state': encode_graph(random.getstate(), {}),
        'python_seed_marker': {'present': hasattr(random, 'mg_seedset'), 'value': encode_graph(getattr(random, 'mg_seedset', None), {})},
        'survey_stdout': {'path': request['stdout'], 'sha256': hashlib.sha256(stdout).hexdigest(), 'size': len(stdout)},
        'capture_owner': {'pid': os.getpid(), 'group': os.getpgrp(), 'quiescent_integration_children': owned, 'runweb_hex': marker.hex()},
        'original': request['original'], 'compatibility': compatibility(request['config'], request['original']['source_base']),
        'source_subprocess_roster': roster, 'channels': channels,
        'source_contract': dict(PRIMARY),
        'runtime_environment': {k:os.environ.get(k) for k in ENVIRONMENT_KEYS},
        'restoration': 'fresh native setup then exact live graph/def_current; complete released generate-events tail'}
    record['continuation_control']=initialize_control(record,support)
    raw = support.encoded(record); require(len(raw)+tree['total_bytes']+len(stdout)+record['continuation_control']['genesis']['size'] <= policy['max_bytes'], 'complete checkpoint metadata/storage exceeds ceiling')
    support.write_bytes(destination/'checkpoint.json', raw);(destination/'checkpoint.json').chmod(0o600)
    for folder in destination.rglob('*'):
        if folder.is_dir() and not folder.is_symlink():folder.chmod(0o700)
    verify(record, support)
    require(encode_graph({k: getattr(cmd, k) for k in STATE_FIELDS}, classes) == graph, 'live native state changed during capture')
    require(channel_state(cmd,support,policy['max_member_bytes'],request['madgraph']) == channels, 'native channel results changed during capture')
    source_inputs(request['madgraph'],support)
    return record


def materialize(record, process, roots, support=None, *, limits=None):
    s = storage(support); effective=effective_limits(record,limits); verify(record,s,limits=effective); process = Path(process); require(not process.exists(), 'fresh continuation process required')
    delta=0
    for row in record['tree']['rows']:
        if row['relative']=='Cards/me5_configuration.txt' and row['type']=='file':
            old=s._blob_bytes(row,min(row['blob']['size'],effective['max_member_bytes']));new=relocated_configuration(old,record,roots)
            require(len(new)<=effective['max_member_bytes'],'relocated configuration exceeds current member ceiling');delta+=len(new)-len(old)
    require(record['tree']['total_bytes']+len(s.encoded(record))+record['survey_stdout']['size']+record['continuation_control']['genesis']['size']+max(0,delta)<=effective['max_bytes'],'relocated checkpoint exceeds current total ceiling')
    process.mkdir()
    omitted = {'RunWeb', 'HTML/results.pkl'}
    for row in record['tree']['rows']:
        if row['relative'] in omitted: continue  # retain blobs as original control/database provenance
        p = process/s._relative(row['relative'])
        if row['type'] == 'directory': p.mkdir(parents=True, exist_ok=True); p.chmod(row['mode'])
        elif row['type'] == 'file':
            raw = s._blob_bytes(row, min(row['blob']['size'],effective['max_member_bytes']))
            if row['relative'] == 'Cards/me5_configuration.txt': raw = relocated_configuration(raw,record,roots)
            require(len(raw)<=effective['max_member_bytes'],'materialized checkpoint exceeds current member ceiling')
            s.write_bytes(p, raw); p.chmod(row['mode']); os.utime(p, ns=(row['mtime_ns'],row['mtime_ns']))
            require(s.regular_bytes(p, effective['max_member_bytes']) == raw, 'materialized continuation byte mismatch')
        elif row['type'] == 'link':
            target = Path(roots[row['role']])/s._relative(row['target'])
            if row['role'] != 'process':
                if 'target_directory' in row:
                    require(reference_directory(target,row['target_directory'],effective,s)==row['target_directory'],'relocated native directory differs')
                else:
                    require(hashlib.sha256(s.regular_bytes(target, min(row['target_size'],effective['max_member_bytes']))).hexdigest() == row['target_sha256'], 'relocated native library differs')
                    require(stat.S_IMODE(target.lstat().st_mode)==row['target_mode'], 'relocated native library mode differs')
            p.parent.mkdir(parents=True, exist_ok=True); p.symlink_to(os.path.relpath(target,p.parent))
        else: raise ValueError('unknown checkpoint member')
    expected = {x['relative'] for x in record['tree']['rows']} - omitted
    require({x['relative'] for x in s._structure(process, effective['max_files'])[1]} == expected, 'continuation member population differs')
    check_materialized([x for x in record['tree']['rows'] if x['relative'] not in omitted],process,roots,record,s,limits=effective)
    verify(record,s,limits=effective)


def restore_survey(cmd, line, request, support):
    """One substitution at source do_survey; never abbreviate generate-events tail."""
    record = request['record']; verify(record,support,limits=request['policy']); source_inputs(request['madgraph'],support)
    require({k:os.environ.get(k) for k in ENVIRONMENT_KEYS}==record['runtime_environment'], 'same-run native compiler/library/environment changed')
    require(not request.get('_restored'), 'survey substitution may occur once only')
    require(Path(cmd.me_dir) == Path(request['process']), 'fresh actual native ownership required')
    native_owner(cmd,request['madgraph'],support)
    target = request['roots']; graph = relocated_graph(record['state'],record['tree']['roots'],target)
    classes = registry(request['madgraph'],support); restored = decode_graph(graph,classes)
    require(restored['run_name'] == 'ravel' and restored['run_card']['iseed'] == 0 and restored['nb_refine'] == 0, 'exact original returned-survey state required')
    args = cmd.split_arg(line); cmd.check_survey(args)
    cmd.configure_directory()  # real current compilation/setup, not a copied timestamp
    check_materialized(list(integration_products(record)),cmd.me_dir,request['roots'],record,support,limits=request['policy'])
    current_configured = cmd.configured
    require(cmd.run_card == restored['run_card'], 'fresh source setup changed physical operative cards')
    for k,v in restored.items(): setattr(cmd,k,v)
    roster = encode_graph(cmd.results,classes)
    cmd.results.def_current(cmd.run_name,cmd.run_tag)
    require(encode_graph(cmd.results,classes) == roster, 'exact tag selection mutated live database')
    require(cmd.results.current is cmd.results[cmd.run_name][cmd.results[cmd.run_name].tags.index(cmd.run_tag)], 'restored current record identity differs')
    require(cmd.configured == current_configured, 'copied configured timestamp cannot bypass current setup')
    random.setstate(decode_graph(record['python_random_state'],{}))
    marker = record['python_seed_marker']
    if marker['present']: random.mg_seedset = decode_graph(marker['value'],{})
    elif hasattr(random,'mg_seedset'): del random.mg_seedset
    require(random.getstate() == decode_graph(record['python_random_state'],{}) and hasattr(random,'mg_seedset') == marker['present'], 'restored Python seed/marker differs')
    require(not marker['present'] or encode_graph(random.mg_seedset,{}) == marker['value'], 'restored native Python seed marker value differs')
    require(support.regular_bytes(Path(cmd.me_dir)/'SubProcesses/randinit',128).decode().strip() == 'r='+str(cmd.random), 'survey randinit state differs')
    require(encode_graph({k: getattr(cmd,k) for k in STATE_FIELDS},classes) == graph, 'restored complete live state differs')
    verify(record,support,limits=request['policy']); request['_restored'] = True
    return None  # pinned do_survey has no explicit return


def seed_evidence(admission, stdout_path, support=None):
    s = storage(support); record = admission['record']; effective=effective_limits(record,admission['effective_policy']); verify(record,s,limits=effective)
    full = s.regular_bytes(Path(record['survey_stdout']['path']), effective['max_member_bytes'])
    require({'path':record['survey_stdout']['path'],'sha256':hashlib.sha256(full).hexdigest(),'size':len(full)} == admission['original_stdout'],
            'closed original seed stdout changed since admission')
    manifest = Path(record['tree']['root'])/'checkpoint.json'
    require({'path':str(manifest),'sha256':hashlib.sha256(s.encoded(record)).hexdigest(),'size':len(s.encoded(record))} == admission['checkpoint_pin'],
            'exact admitted same-run checkpoint differs')
    prefix = s.regular_bytes(Path(record['tree']['root'])/'survey-stdout-prefix.bin', effective['max_member_bytes'])
    require(full.startswith(prefix), 'original closed stdout no longer contains captured actual survey prefix')
    require(re.findall(rb'Using random number seed offset = (\d+)\b',full) == [str(record['compatibility']['generation']['seed']).encode()], 'original complete seed log differs')
    current = s.regular_bytes(stdout_path, effective['max_member_bytes'])
    require(not re.findall(rb'Using random number seed offset = (\d+)\b',current), 'continued tail unexpectedly reran survey')
    return {'kind': KIND, 'checkpoint': admission['checkpoint_pin'], 'original_stdout': admission['original_stdout'],
        'current_stdout': {'path': str(stdout_path), 'sha256': hashlib.sha256(current).hexdigest(), 'size': len(current)},
        'current_source_base':admission['current_source_base'], 'effective_policy':admission['effective_policy'],
        'declared_seed': record['compatibility']['generation']['seed'], 'same_sample_lineage': True,
        'original_success_inferred': False, 'independent_sample': False}


def admit(c, base):
    """Fresh current ordinary origin admission, including failed/unknown charges."""
    from ravel.workflow import science, execution
    from . import model_tool_bridge as bridge
    s = storage(); policy = validate(c['integration_checkpoint']); candidate = policy['candidate']
    if candidate is None: return {'state': 'capture', 'inputs': []}
    rd = bridge._regular(candidate['rundir'],base,directory=True)
    with science._validation_scope(rd) as session:
        p = science.verify_plan(rd,approved=True,_session=session)
        spec = science.execution_spec(rd,_session=session); require(spec['mode'] == 'model-events' and spec.get('goal_binding') is not None, 'original goal-bound ordinary generator study required')
        stage,_,budget = science._selected(rd,p,_session=session); output = rd/stage['outputs'][0]
        attempt = session.read_document(rd/'execution_attempt.json')
        require(attempt['attempt'] == candidate['attempt'], 'foreign original checkpoint attempt')
        state = execution.load_execution(rd); session.track(state)
        require(state['stages']['science']['status'] == 'failed', 'original failed ordinary owner required; success is not a continuation origin')
        process = session.read_document(output/'native-process.json'); receipt = session.read_document(output/'native-execution.json')
        require(process['command'] == receipt['command'] and process['process_group'] == process['pid'], 'original native owner/receipt identity differs')
        require(not any(x['group'] == process['process_group'] for x in process_table()), 'old complete native owner group remains')
        failure = session.read_document(rd/'logs/science.failure.json')
        require(failure['stage'] == 'science' and failure['cleanup']['group_state'] == 'empty' and not failure['cleanup']['remaining_group_members'] and not failure['cleanup']['requires_recovery'], 'original failed/unknown cleanup required')
        original = session.read_document(output/'native-input.json')
        config_path = session.regular_file(spec['task']['config'],p['base_dir'])
        source_config = session.read_document(config_path)
        require(session.hash_file(config_path) == original['config_sha256'], 'original native configuration source changed')
        require(type(source_config['max_seconds']) is int and type(original['config']['max_seconds']) is int
                and type(receipt['max_seconds']) is int and source_config['max_seconds'] == original['config']['max_seconds'] == receipt['max_seconds'],
                'original declared/native receipt ceiling differs')
        spent = [failure['elapsed_s'],receipt['wall_seconds']]
        require(all(type(x) in (int,float) and math.isfinite(x) and x >= 0 for x in spent), 'finite original elapsed charge required')
        remaining = min(budget,source_config['max_seconds']) - max(spent)
        require(remaining > 0 and c['max_seconds'] <= remaining, 'continuation exceeds original remaining charged wall budget')
        path = output/'integration-checkpoint/checkpoint.json'; raw = s.regular_bytes(path,min(policy['max_bytes'],policy['max_member_bytes']))
        require(hashlib.sha256(raw).hexdigest() == candidate['checkpoint_sha256'], 'exact checkpoint origin digest differs')
        record = s.read_document(path,min(policy['max_bytes'],policy['max_member_bytes']))
        policy = effective_limits(record,policy)
        verify(record,s,limits=policy)
        require(record['original']['rundir'] == str(rd) and record['original']['attempt'] == candidate['attempt'] and record['capture_owner']['group'] == process['process_group'], 'checkpoint run/attempt/native group differs')
        phase_request=session.read_document(output/'native-phase-observer-request.json')
        helper=phase_request['integration_checkpoint']['helper']
        request_sha=session.hash_file(output/'native-phase-observer-request.json')
        commands=[json.loads(line) for line in s.regular_bytes(output/'command-observations.jsonl',policy['max_member_bytes']).decode().splitlines()]
        launched=[x for x in commands if x.get('phase')=='generate-decay-shower-reweight' and x.get('state')=='running']
        require(len(launched)==1 and request_sha in launched[0]['command'], 'checkpoint not bound to actual original phase invocation')
        events=[json.loads(line) for line in s.regular_bytes(output/'model-events-phase-observations.jsonl',policy['max_member_bytes']).decode().splitlines()]
        captures=[x for x in events if x.get('phase')=='survey' and x.get('state')=='captured']
        require(len(captures)==1 and captures[0]['checkpoint']=={'path':str(path),'sha256':candidate['checkpoint_sha256'],'size':len(raw)}, 'actual returned-survey capture receipt differs')
        require(record['source_contract']==PRIMARY and phase_request['integration_checkpoint']['request']['original']==record['original'], 'foreign source/actual original capture request')
        for name in ('command-observations.jsonl','model-events-phase-observations.jsonl'):
            session.hash_file(output/name)
        for key in ('helper','storage_helper'):
            pin=phase_request['integration_checkpoint'][key]
            require(session.hash_file(pin['path'])==pin['sha256'] and Path(pin['path']).stat().st_size==pin['size'],'original source-bound checkpoint helper changed')
        require(original['config_sha256'] == record['original']['config_sha256'] and compatibility(source_config,config_path.parent) == compatibility(original['config'],original['source_base']) == record['compatibility'] == compatibility(c,base), 'same-run complete source/model/cards/runtime/exposure differs')
        # The released process card retains its original import spelling, which
        # reweighting can read. Authenticate that real source, not its name alone.
        old_model=bridge._regular(original['model'],original['source_base'],directory=True)
        _,manifest,_=bridge._tree(original['config']['model_tree'],original['source_base'])
        expected_model=session.read_document(manifest)
        require(bridge.source_tree(old_model)==expected_model,'original imported model source changed')
        for name in expected_model['files']:
            session.require_regular(old_model/name);session.hash_file(old_model/name)
        session.retain_final_check(lambda: require(bridge.source_tree(old_model)==expected_model,'original imported model population changed at ending'))
        original_stdout = Path(record['survey_stdout']['path']); require(original_stdout == output/'generate-decay-shower-reweight-stdout.log', 'foreign original survey log')
        rawlog = s.regular_bytes(original_stdout,policy['max_member_bytes'])
        prefix = s.regular_bytes(path.parent/'survey-stdout-prefix.bin',policy['max_member_bytes'])
        require(rawlog.startswith(prefix), 'closed original stdout changed captured survey prefix')
        result = {'state': 'continue', 'record': record, 'checkpoint_pin': {'path': str(path), 'sha256':candidate['checkpoint_sha256'],'size':len(raw)},
            'original_stdout': {'path': str(original_stdout),'sha256':hashlib.sha256(rawlog).hexdigest(),'size':len(rawlog)},
            'goal_binding': spec['goal_binding'], 'current_source_base':str(Path(base).resolve()), 'effective_policy':policy, 'remaining_original_seconds': remaining, 'original_failure': failure,
            'origin_request': original, 'inputs': []}
        control,journal=read_control(record)
        require(sum(x['claim']['seconds'] for x in journal['entries'])<=remaining,'continuation reservations exceed original allocation')
        session.hash_file(control/'genesis.json')
        session.hash_file(original_stdout); session.hash_file(path)
        result['inputs'] = sorted(set(map(str,session.files)) | {x['blob']['path'] for x in record['tree']['rows'] if x['type'] == 'file'} | {str(path.parent/'survey-stdout-prefix.bin')})
        return result


def ending(admission):
    s = storage(); verify(admission['record'],s,limits=admission['effective_policy'])
    for pin in (admission['checkpoint_pin'],admission['original_stdout']):
        raw = s.regular_bytes(pin['path'],min(admission['effective_policy']['max_member_bytes'],admission['effective_policy']['max_bytes']))
        require(len(raw) == pin['size'] and hashlib.sha256(raw).hexdigest() == pin['sha256'], 'same-run checkpoint/original stdout changed')



def _control_directory(original,support=None):
    rd=Path(original['rundir'])
    require(rd.is_absolute() and str(rd)==str(rd.resolve()) and not any(p.is_symlink() for p in (rd,*rd.parents)), 'canonical original control owner required')
    key=storage(support).digest({k:original[k] for k in ('rundir','attempt','config_sha256','goal_binding')})
    # Mutable coordinator state is outside the immutable old run/output census.
    return rd.parent/('.'+rd.name+'-native-continuations')/key


def initialize_control(record, support):
    root=_control_directory(record['original'],support)
    require(not root.exists() and not any(p.is_symlink() for p in (root,*root.parents)), 'fresh original continuation control required')
    root.mkdir(parents=True,mode=0o700);root.chmod(0o700)
    genesis={'schema_version':1,'kind':CONTROL_KIND,'original':record['original'],
        'state_sha256':support.digest(record['state']),'tree_sha256':support.digest(record['tree']),
        'source_contract':record['source_contract'],'same_sample_lineage':True,'independent_sample':False}
    pin=support.write_document(root/'genesis.json',genesis);(root/'genesis.json').chmod(0o600)
    control={'root':str(root),'genesis':pin}
    future=dict(record,continuation_control=control)
    journal={'schema_version':1,'kind':CONTROL_KIND,'checkpoint_sha256':support.digest(future),
        'genesis':pin,'entries':[]}
    support.write_document(root/'journal.json',journal);(root/'journal.json').chmod(0o600)
    support.write_bytes(root/'control.lock',b'');(root/'control.lock').chmod(0o600)
    return control


def read_control(record):
    s=storage(); control=record['continuation_control'];root=_control_directory(record['original'])
    require(control['root']==str(root) and control['genesis']['path']==str(root/'genesis.json'), 'foreign original continuation control')
    require(not any(p.is_symlink() for p in (root,*root.parents)) and stat.S_IMODE(root.lstat().st_mode)==0o700,'ordinary original continuation control required')
    before=s._structure(root,CONTROL_ENTRIES*2+3)
    pin=control['genesis'];raw=s.regular_bytes(pin['path'],CONTROL_BYTES)
    require(len(raw)==pin['size'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'continuation genesis changed')
    genesis=s.read_document(pin['path'],CONTROL_BYTES)
    require(genesis=={'schema_version':1,'kind':CONTROL_KIND,'original':record['original'],
        'state_sha256':s.digest(record['state']),'tree_sha256':s.digest(record['tree']),
        'source_contract':record['source_contract'],'same_sample_lineage':True,'independent_sample':False},'continuation genesis origin differs')
    journal=s.read_document(root/'journal.json',CONTROL_BYTES)
    require(type(journal) is dict and set(journal)=={'schema_version','kind','checkpoint_sha256','genesis','entries'} and journal['schema_version']==1
        and journal['kind']==CONTROL_KIND and journal['checkpoint_sha256']==s.digest(record) and journal['genesis']==pin
        and type(journal['entries']) is list and len(journal['entries'])<=CONTROL_ENTRIES,'invalid original continuation journal')
    expected={'genesis.json','journal.json','control.lock'};owners=[]
    for i,entry in enumerate(journal['entries'],1):
        require(type(entry) is dict and set(entry)=={'claim','status','terminal'} and entry['status'] in ('reserved','failed','succeeded'),'invalid continuation entry')
        claim=entry['claim'];name='claim-%04d.json'%i;expected.add(name)
        require(type(claim) is dict and set(claim)=={'sequence','checkpoint_sha256','genesis','owner','seconds'} and claim['sequence']==i and claim['checkpoint_sha256']==s.digest(record)
            and claim['genesis']==pin and type(claim['seconds']) is int and claim['seconds']>0,'invalid charged continuation claim')
        require(s.regular_bytes(root/name,CONTROL_BYTES)==s.encoded(claim),'charged claim changed')
        require(claim['owner'] not in owners,'duplicate continuation owner');owners.append(claim['owner'])
        if entry['status']=='reserved':require(entry['terminal'] is None,'reserved continuation cannot infer terminal evidence')
        else:
            name='terminal-%04d.json'%i;expected.add(name)
            require(type(entry['terminal']) is dict and entry['terminal'].get('status')==entry['status'] and s.regular_bytes(root/name,CONTROL_BYTES)==s.encoded(entry['terminal']),'continuation terminal evidence changed')
    observation=s._structure(root,CONTROL_ENTRIES*2+3)
    require({x['relative'] for x in observation[1]}==expected and all(x['type']=='file' and stat.S_IMODE(x['identity'][2])==0o600 for x in observation[1]),'continuation control membership/mode changed')
    require(s._structure(root,CONTROL_ENTRIES*2+3)==before,'continuation control changed during observation')
    return root,journal


def _write_journal(root,journal):
    from ravel.workflow.state_io import atomic_json
    raw=(json.dumps(journal,indent=2,allow_nan=False)+'\n').encode()
    require(len(raw)<=CONTROL_BYTES,'continuation journal capacity exhausted')
    atomic_json(root/'journal.json',journal)
    (root/'journal.json').chmod(0o600)
    require(storage().regular_bytes(root/'journal.json',CONTROL_BYTES)==raw,'intended continuation journal changed')


def _owner(task,base,output,*,native=False):
    from ravel.workflow import science,execution
    from . import model_events
    s=storage();out=Path(output).resolve()
    if native:
        process=s.read_document(out/'native-process.json',CONTROL_BYTES)
        require(process['pid']==os.getpid() and process['process_group']==os.getpgrp() and os.getppid()==process['owner_pid'],'actual current native continuation owner required')
        rd=next((p for p in (out,*out.parents) if (p/'inputs/science-plan.json').is_file()),None)
        require(rd is not None,'ordinary current continuation run required')
    else:
        rd,_=model_events._approved(task,out);process=None
    with science._validation_scope(rd) as session:
        p=science.verify_plan(rd,approved=True,_session=session);spec=science.execution_spec(rd,_session=session)
        stage,binding,seconds=science._selected(rd,p,_session=session)
        attempt=session.read_document(rd/'execution_attempt.json');state=execution.load_execution(rd);session.track(state)
        current=state['stages'].get('science',{})
        require(spec['mode']=='model-events' and spec['task']==task and (rd/stage['outputs'][0]).resolve()==out and spec.get('goal_binding') is not None,'current ordinary continuation task/output/goal differs')
        pid=process['owner_pid'] if native else os.getpid()
        require(current.get('status')=='running' and current.get('child_pid')==pid and current.get('child_identity')==execution.process_identity(pid)
            and current.get('fingerprint')==binding['fingerprint'],'current registered ordinary continuation attempt required')
        path=session.regular_file(task['config'],p['base_dir'])
        return {'rundir':str(rd),'attempt':attempt['attempt'],'output':str(out),'fingerprint':binding['fingerprint'],
            'child_pid':pid,'child_identity':current['child_identity'],'config':{'path':str(path),'sha256':session.hash_file(path)},
            'goal_binding':spec['goal_binding']},seconds


def _terminal(claim):
    """Only current authentic terminal and complete group cleanup release ownership.

    Missing/unknown/mutated evidence holds the full reservation; it never refunds.
    """
    from ravel.workflow import science,execution
    s=storage();owner=claim['owner'];rd=Path(owner['rundir'])
    try:
        with science._validation_scope(rd) as session:
            p=science.verify_plan(rd,approved=True,_session=session);spec=science.execution_spec(rd,_session=session)
            stage,binding,seconds=science._selected(rd,p,_session=session);attempt=session.read_document(rd/'execution_attempt.json')
            require(attempt['attempt']==owner['attempt'] and binding['fingerprint']==owner['fingerprint'] and seconds==claim['seconds']
                and spec['goal_binding']==owner['goal_binding'] and str((rd/stage['outputs'][0]).resolve())==owner['output'],'previous continuation authority changed')
            path=session.regular_file(spec['task']['config'],p['base_dir'])
            require({'path':str(path),'sha256':session.hash_file(path)}==owner['config'],'previous continuation config changed')
            state=execution.load_execution(rd);session.track(state);current=state['stages'].get('science',{})
            require(current.get('fingerprint')==owner['fingerprint'] and current.get('child_pid')==owner['child_pid']
                and current.get('child_identity')==owner['child_identity'],'previous registered continuation identity differs')
            require(current.get('status') in ('failed','succeeded'),'previous continuation is not terminal')
            out=Path(owner['output']);process=session.read_document(out/'native-process.json');receipt=session.read_document(out/'native-execution.json')
            require(process['owner_pid']==owner['child_pid'] and process['process_group']==process['pid'] and receipt['command']==process['command']
                and not any(x['group']==process['process_group'] for x in process_table()),'previous native continuation cleanup unknown')
            if current['status']=='failed':
                failure=session.read_document(rd/'logs/science.failure.json')
                require(failure['stage']=='science' and failure['cleanup']['group_state']=='empty' and not failure['cleanup']['remaining_group_members'] and not failure['cleanup']['requires_recovery'],'previous ordinary continuation cleanup unknown')
            else:require(receipt['returncode']==0 and receipt['resource_violation'] is None,'successful continuation native receipt differs')
            pins=[{'path':str(path),'sha256':session.hash_file(path)} for path in sorted(session.files)]
            return {'status':current['status'],'owner':owner,'receipt_inputs':pins,'charged_seconds':claim['seconds'],'refund_seconds':0}
    except (ValueError,OSError,KeyError,TypeError):return None


def claim(c,base,task,output):
    """Serialize exact original allocation after current genuine launch admission."""
    from ravel.workflow.state_io import file_lock
    admission=admit(c,base);require(admission['state']=='continue','only original completed-survey continuation can claim')
    owner,seconds=_owner(task,base,output);require(owner['goal_binding']==admission['goal_binding'],'continuation changes original goal')
    root,_=read_control(admission['record'])
    with file_lock(root/'control.lock',blocking=False):
        require(_owner(task,base,output)==(owner,seconds),'current continuation authority changed before claim')
        require(admit(c,base)==admission,'original continuation authority changed before claim')
        root,journal=read_control(admission['record'])
        for i,entry in enumerate(journal['entries'],1):
            require(entry['claim']['owner']!=owner,'duplicate continuation dispatch refused')
            if entry['status']=='reserved':
                terminal=_terminal(entry['claim'])
                if terminal is not None:
                    storage().write_document(root/('terminal-%04d.json'%i),terminal);(root/('terminal-%04d.json'%i)).chmod(0o600)
                    entry.update(status=terminal['status'],terminal=terminal)
                    _write_journal(root,journal)
            elif entry['status']=='failed':
                require(_terminal(entry['claim'])==entry['terminal'],'previous continuation terminal custody changed')
        require(not any(e['status']=='succeeded' for e in journal['entries']),'same-run completed continuation cannot replay original RNG')
        require(not any(e['status']=='reserved' for e in journal['entries']),'previous continuation active or unknown; reservation remains charged')
        charged=sum(e['claim']['seconds'] for e in journal['entries'])
        require(type(seconds) is int and c['max_seconds']<=seconds and charged+seconds<=admission['remaining_original_seconds'],'continuation exceeds cumulative original remaining allocation')
        require(len(journal['entries'])<CONTROL_ENTRIES,'continuation journal entry ceiling exhausted')
        row={'sequence':len(journal['entries'])+1,'checkpoint_sha256':admission['checkpoint_pin']['sha256'],
            'genesis':admission['record']['continuation_control']['genesis'],'owner':owner,'seconds':seconds}
        pin=storage().write_document(root/('claim-%04d.json'%row['sequence']),row);Path(pin['path']).chmod(0o600)
        journal['entries'].append({'claim':row,'status':'reserved','terminal':None});_write_journal(root,journal)
        require(read_control(admission['record'])[1]==journal,'continuation reservation changed after commit')
        return {'claim':pin,'owner':owner,'seconds':seconds,'checkpoint_sha256':row['checkpoint_sha256'],'same_sample_lineage':True,'independent_sample':False}


def verify_claim(admission,reservation,task,base,output,*,native=False):
    owner,seconds=_owner(task,base,output,native=native)
    require(reservation['owner']==owner and reservation['seconds']==seconds and owner['goal_binding']==admission['goal_binding'],'current continuation reservation authority differs')
    root,journal=read_control(admission['record']);pin=reservation['claim'];s=storage();raw=s.regular_bytes(pin['path'],CONTROL_BYTES)
    require(hashlib.sha256(raw).hexdigest()==pin['sha256'] and len(raw)==pin['size'],'continuation claim changed')
    matching=[e for e in journal['entries'] if e['claim']['owner']==owner]
    require(len(matching)==1 and matching[0]['status']=='reserved' and s.encoded(matching[0]['claim'])==raw
        and pin['path']==str(root/('claim-%04d.json'%matching[0]['claim']['sequence'])),'exact active continuation reservation required')
    require(not any(e['status']=='reserved' and e is not matching[0] for e in journal['entries']) and
        sum(e['claim']['seconds'] for e in journal['entries'])<=admission['remaining_original_seconds'],'single owner/cumulative allocation changed')
    require(admit(storage().read_document(owner['config']['path']) ,Path(owner['config']['path']).parent)==admission,'original/current continuation admission changed')
    return reservation



def reference_directory(target,expected,limits,support):
    """Read only the authenticated complete roster under the remaining limits."""
    before=support._structure(target,limits['max_files'])
    names={r['relative']:r for r in expected['rows']}
    require(len(names)==len(expected['rows']) and {r['relative'] for r in before[1]}==set(names),'checkpoint reference population changed')
    total=0;rows=[]
    for r in before[1]:
        old=names[r['relative']]
        require(r['type']==old['type'] and stat.S_IMODE(r['identity'][2])==old['mode'],'checkpoint reference kind/mode changed')
        item={'relative':r['relative'],'type':r['type'],'mode':old['mode']}
        if r['type']=='file':
            require(r['identity'][3]==old['size'] and old['size']<=limits['max_member_bytes'],'checkpoint reference size/current ceiling changed')
            raw=support.regular_bytes(Path(target)/r['relative'],min(old['size'],limits['max_member_bytes']))
            require(hashlib.sha256(raw).hexdigest()==old['sha256'],'checkpoint reference bytes changed')
            total+=len(raw);require(total<=limits['max_bytes'],'checkpoint reference total ceiling exceeded')
            item.update(size=len(raw),sha256=old['sha256'])
        else:require(r['type']=='directory','checkpoint reference alias refused')
        rows.append(item)
    require(support._structure(target,limits['max_files'])==before,'checkpoint reference changed during read')
    require({'rows':rows,'total_bytes':total}==expected,'checkpoint reference census differs')
    return expected
