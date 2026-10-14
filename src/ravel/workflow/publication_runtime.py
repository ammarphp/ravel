"""Discover and bind the selected manuscript runtime without running its tools.

Installation, a real TeX/recorder build and independent visual/scientific review
are distinct operations. Readiness reuses the actual manuscript-build consumer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import shutil
import stat
import sys
import types

# Existing final-review custody ceiling; this is a resource bound, not a claim
# that every TeX distribution fits the selected operational closure.
MAX_FILES = 4096
MAX_BYTES = 16 * 1024**3
MAX_MANIFEST_BYTES = 2 * 1024**2


def _regular(value, *, directory=False, _path_observation=None):
    if _path_observation is not None:
        _check_publication_paths(_path_observation)
        return _path_observation.path(value, directory=directory)
    p = Path(value).absolute()
    if any(q.is_symlink() for q in (p, *p.parents)):
        raise ValueError('publication snapshots require regular non-alias paths')
    mode = p.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ValueError('regular publication file/directory required')
    return p.resolve(strict=True)


def _identity(path, *, _path_observation=None):
    if _path_observation is not None:
        _check_publication_paths(_path_observation)
        return _path_observation.identity(path)
    p = _regular(path)
    with p.open('rb') as handle:
        before = os.fstat(handle.fileno())
        h = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
        after = os.fstat(handle.fileno())
    fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if fields(before) != fields(after) or fields(after) != fields(_regular(p).stat()):
        raise ValueError('publication input changed while read')
    return {'path': str(p), 'sha256': h.hexdigest(), 'size': after.st_size,
            'identity': list(fields(after))}


def discover(*, search_path=None):
    """PATH discovery is a locator; aliases are reported, never admitted as pins."""
    rows = []
    for name in ('pdflatex', 'pdfinfo', 'rsvg-convert', 'kpsewhich', 'pdftoppm', 'neato'):
        found = shutil.which(name, path=search_path)
        p = Path(found).absolute() if found else None
        alias = p is not None and any(q.is_symlink() for q in (p, *p.parents))
        rows.append({'name': name, 'path': str(p) if p else None,
                     'resolved_path': str(p.resolve()) if p else None,
                     'alias': alias, 'required_for_manuscript': name in ('pdflatex', 'pdfinfo'),
                     'required_for_svg': name == 'rsvg-convert',
                     'state': 'not_found' if p is None else 'located_alias_not_admitted' if alias else 'located_not_qualified'})
    return {'schema_version': 1, 'kind': 'publication-runtime-discovery', 'tools': rows,
            'commands_executed': False, 'installation_performed': False,
            'runtime_qualified': False, 'scientific_acceptance': False,
            'limit': 'Names and paths only. Select preserved regular executables and full assets; a resolved pdftex name is not a pdflatex invocation contract.'}


def _stat_identity(path, *, _path_observation=None):
    if _path_observation is not None:
        _check_publication_paths(_path_observation)
        s = _path_observation.ending(path)
        return [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
    s = _regular(path).stat()
    return [s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def _ending_tree(root, remembered, *, limits=None, _path_observation=None):
    """Finite fresh membership/type/stat checkpoint after all full-byte reads."""
    from .report_integrity import custody_limits
    limits = custody_limits({'max_files':MAX_FILES,'max_bytes':MAX_BYTES,
        'max_metadata_bytes':MAX_MANIFEST_BYTES} if limits is None else limits)
    root = (_regular(root, directory=True) if _path_observation is None else
            _regular(root, directory=True, _path_observation=_path_observation))
    actual = {}
    total = 0
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('publication asset population changed: alias at ending')
        mode = p.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('publication asset population changed: nonregular ending member')
        if len(actual) >= limits['max_files']:
            raise ValueError('complete ending asset population exceeds file budget')
        identity = (_stat_identity(p) if _path_observation is None else
                    _stat_identity(p, _path_observation=_path_observation))
        total += identity[3]
        if total > limits['max_bytes']:
            raise ValueError('complete ending asset population exceeds byte budget')
        actual[p.relative_to(root).as_posix()] = identity
    expected = {name: row['identity'] for name, row in remembered.items()}
    if actual != expected:
        raise ValueError('publication asset population changed after completed reads')


def _ending_inputs(remembered):
    for path, row in remembered.items():
        if _stat_identity(path) != row['identity']:
            raise ValueError('complete manuscript/runtime input identity changed after completed reads')


def _inventory(root, *, limits=None, _path_observation=None):
    from .report_integrity import custody_limits
    limits = custody_limits({'max_files':MAX_FILES,'max_bytes':MAX_BYTES,
        'max_metadata_bytes':MAX_MANIFEST_BYTES} if limits is None else limits)
    root = (_regular(root, directory=True) if _path_observation is None else
            _regular(root, directory=True, _path_observation=_path_observation))
    result = {}
    total = 0
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('publication asset tree contains an alias')
        mode = p.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('publication asset tree contains a nonregular member')
        if len(result) >= limits['max_files']:
            raise ValueError('complete selected asset inventory exceeds final-review file budget')
        if total + p.stat().st_size > limits['max_bytes']:
            raise ValueError('complete selected asset inventory exceeds final-review byte budget')
        row = (_identity(p) if _path_observation is None else
               _identity(p, _path_observation=_path_observation))
        total += row['size']
        if total > limits['max_bytes']:
            raise ValueError('complete selected asset inventory exceeds final-review byte budget')
        result[p.relative_to(root).as_posix()] = row
    if not result:
        raise ValueError('nonempty complete selected asset tree required')
    if _path_observation is None:_ending_tree(root, result, limits=limits)
    else:_ending_tree(root, result, limits=limits, _path_observation=_path_observation)
    return result


def inventory(root, out, *, limits=None):
    """Emit the exact existing worker tree-manifest schema to a fresh file.

    No asset copying, dependency guessing or class/venue certification. Intended
    bytes are committed before emission; drift leaves the original failed output.
    """
    from .report_integrity import custody_limits
    limits = custody_limits({'max_files':MAX_FILES,'max_bytes':MAX_BYTES,
        'max_metadata_bytes':MAX_MANIFEST_BYTES} if limits is None else limits)
    root = _regular(root, directory=True)
    out = Path(out).absolute()
    _regular(out.parent, directory=True)
    if out.is_relative_to(root):
        raise ValueError('asset manifest must live outside its inventoried tree')
    before = _inventory(root, limits=limits)
    document = {'schema_version': 1, 'files': {name: row['sha256'] for name, row in before.items()}}
    raw = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > limits['max_metadata_bytes']:
        raise ValueError('complete selected asset manifest exceeds bounded metadata budget')
    intended = hashlib.sha256(raw).hexdigest()
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    saved = _identity(out)
    if saved['sha256'] != intended or saved['size'] != len(raw) or out.read_bytes() != raw:
        raise ValueError('emitted asset manifest differs from intended bytes')
    if _inventory(root, limits=limits) != before:
        raise ValueError('selected asset population changed during inventory emission')
    if _identity(out) != saved:
        raise ValueError('asset manifest changed at preparation ending')
    _ending_tree(root, before, limits=limits)
    _ending_inputs({str(out): saved})
    return {'schema_version': 1, 'kind': 'publication-runtime-asset-inventory',
            'tree': {'root': str(root), 'manifest': {'path': str(out), 'sha256': intended}},
            'manifest_size': len(raw), 'file_count': len(before),
            'asset_bytes': sum(row['size'] for row in before.values()),
            'commands_executed': False, 'installation_performed': False,
            'runtime_qualified': False, 'venue_assets_authenticated_as_official': False,
            'limit': 'Exact supplied bytes only. Full selected dependency closure, licenses and official venue/challenge applicability require retained sources and actual build/readback.'}


def _keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('closed publication runtime fields required: ' + ', '.join(names))


def _encoded(value, *, compact=False):
    if type(compact) is not bool:
        raise ValueError('explicit Boolean metadata encoding choice required')
    if compact:
        return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _emit(path, document, maximum, *, compact=False):
    raw = _encoded(document, compact=compact)
    if len(raw) > maximum:
        raise ValueError('complete runtime metadata exceeds declared capacity')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    pin = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    if path.read_bytes() != raw:
        raise ValueError('intended runtime emission changed')
    return pin


def _relative(value):
    if (type(value) is not str or not value or Path(value).is_absolute() or
            any(x in {'', '.', '..'} for x in value.split('/')) or '\\' in value):
        raise ValueError('explicit nontraversing relative snapshot member required')
    return value


def _resolve_alias(path, allowed):
    """Preserve lexical aliases, including parents, without executing wrappers."""
    p = Path(path)
    if not p.is_absolute(): raise ValueError('absolute selected runtime source required')
    pending = deque(p.parts[1:]); current = Path('/'); links = []; components = []
    visited = set()
    while pending:
        part = pending.popleft()
        if part == '.': continue
        if part == '..': current = current.parent; continue
        current = current / part; s = current.lstat()
        if stat.S_ISLNK(s.st_mode):
            if str(current) in visited or len(links) >= 64:
                raise ValueError('runtime alias cycle/traversal bound')
            visited.add(str(current)); target = os.readlink(current)
            after = current.lstat()
            fields = lambda x: [x.st_dev,x.st_ino,x.st_mode,x.st_size,x.st_mtime_ns,x.st_ctime_ns]
            if fields(s) != fields(after): raise ValueError('runtime link changed while read')
            proposed = Path(os.path.normpath(str(Path(target) if Path(target).is_absolute() else current.parent/target)))
            if not any(proposed.is_relative_to(root) for root in allowed):
                raise ValueError('runtime alias escapes explicitly supplied source/target roots')
            links.append({'path':str(current),'target':target,'identity':fields(s)})
            pending = deque([*proposed.parts[1:],*pending]); current = Path('/')
        else:
            if not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
                raise ValueError('special runtime source member refused')
            components.append({'path':str(current),'identity':[s.st_dev,s.st_ino,s.st_mode]})
    if not any(current.is_relative_to(root) for root in allowed):
        raise ValueError('resolved runtime source escapes supplied roots')
    return current, links, components


def _source_capture(root, allowed, limits):
    files = {}; directories = {}; total = 0
    def visit(lexical, relative, ancestors):
        nonlocal total
        terminal, links, components = _resolve_alias(lexical, allowed)
        s = terminal.stat(); identity = [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
        if stat.S_ISDIR(s.st_mode):
            key = (s.st_dev,s.st_ino)
            if key in ancestors: raise ValueError('directory alias cycle refused')
            directories[relative] = {'terminal':str(terminal),'identity':identity,'links':links,'components':components}
            if len(directories) > limits['max_files'] * 4 + 1:
                raise ValueError('runtime directory traversal bound exceeded')
            for entry in sorted(terminal.iterdir(), key=lambda q:q.name):
                visit(lexical/entry.name, entry.name if relative == '.' else relative+'/'+entry.name, {*ancestors,key})
        elif stat.S_ISREG(s.st_mode):
            if len(files) >= limits['max_files'] or total + s.st_size > limits['max_bytes']:
                raise ValueError('complete source runtime capacity exceeded')
            pin = _identity(terminal)
            if _resolve_alias(lexical, allowed) != (terminal, links, components):
                raise ValueError('runtime source alias changed after leaf read')
            total += pin['size']
            files[relative] = {'source':pin,'mode':stat.S_IMODE(s.st_mode),'links':links,'components':components}
        else: raise ValueError('regular runtime source leaf required')
    visit(Path(root), '.', set())
    if not files: raise ValueError('nonempty selected complete runtime tree required')
    return {'schema_version':1,'kind':'publication-source-inventory','root':str(Path(root)),
            'allowed_roots':[str(q) for q in allowed],'files':files,'directories':directories,
            'custody_limits':limits}


def source_inventory(root, out, *, allowed_target_roots=(), limits=None):
    """Capture a selected closure's links and bytes; readiness, not qualification."""
    from .report_integrity import custody_limits
    limits = custody_limits(limits); root = Path(root).absolute()
    allowed = sorted(set([root,*[_regular(q,directory=True) for q in allowed_target_roots]]))
    out = Path(out).absolute(); _regular(out.parent,directory=True)
    if any(out.is_relative_to(q) for q in allowed):
        raise ValueError('source inventory must be outside all selected source/target roots')
    first = _source_capture(root, allowed, limits)
    if _source_capture(root, allowed, limits) != first:
        raise ValueError('runtime source changed during complete inventory')
    pin = _emit(out, first, limits['max_metadata_bytes'])
    if _source_capture(root, allowed, limits) != first or _identity(out)['sha256'] != pin['sha256']:
        raise ValueError('runtime source/inventory changed at ending')
    return pin


def host_identity():
    """Nonexecuting kernel/platform identity, not invented shared-cache file pins."""
    u = os.uname()
    return {'sysname':u.sysname,'release':u.release,'version':u.version,'machine':u.machine}


_TEX_SEARCH = {'TEXMFCNF','TEXMFROOT','TEXMFHOME','TEXMFVAR','TEXMFCONFIG','TEXMFOUTPUT',
               'TEXINPUTS','TEXFORMATS','TFMFONTS','T1FONTS','OPENTYPEFONTS','TTFONTS','VFFONTS',
               'TEXFONTMAPS','BIBINPUTS','BSTINPUTS'}
_SCRATCH = {'TMPDIR','TEXMFHOME','TEXMFVAR','TEXMFCONFIG','TEXMFOUTPUT'}
_THREADS = {'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
            'NUMEXPR_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1'}


def environment_contract(value, root, tools, platform):
    """No inherited search elements, package generation, preload or HOME override."""
    _keys(value, tools); root = _regular(root,directory=True); result = {}
    for tool in tools:
        row = value[tool]
        if tools[tool] is None:
            if row is not None: raise ValueError('absent tool has no environment capability')
            result[tool] = None; continue
        if type(row) is not dict or not row or len(row)>32:
            raise ValueError('explicit finite per-tool environment required')
        allowed = {'PATH','LANG','LC_ALL','TZ','TMPDIR'} | (_TEX_SEARCH if tool=='compiler' else set())
        if platform=='Darwin': allowed |= {'DYLD_LIBRARY_PATH','DYLD_PRINT_LIBRARIES','DYLD_PRINT_LIBRARIES_POST_LAUNCH'}
        elif platform=='Linux': allowed |= {'LD_LIBRARY_PATH'}
        else: raise ValueError('unsupported explicit loader platform; qualification held')
        if tool=='compiler': allowed |= {'openin_any','openout_any','shell_escape','MKTEXPK','MKTEXTFM','MKTEXFMT'}
        if set(row)-allowed: raise ValueError('unlisted/injection environment variable refused')
        for key,text in row.items():
            if type(text) is not str or not text or len(text.encode())>16384 or any(c in text for c in ('\x00','$','~','\n','\r',';')):
                raise ValueError('literal bounded runtime environment value required')
            if key in {'LANG','LC_ALL','TZ'}:
                if text not in {'C','UTC','C.UTF-8'}: raise ValueError('closed nonsecret locale required')
            elif key in {'DYLD_PRINT_LIBRARIES','DYLD_PRINT_LIBRARIES_POST_LAUNCH'}:
                if text!='1': raise ValueError('loader observation cannot be disabled')
            elif key in {'openin_any','openout_any','shell_escape','MKTEXPK','MKTEXTFM','MKTEXFMT'}:
                expected={'openin_any':'p','openout_any':'p','shell_escape':'f','MKTEXPK':'0','MKTEXTFM':'0','MKTEXFMT':'0'}
                if text!=expected[key]: raise ValueError('offline/no-shell package-generation restrictions required')
            else:
                for item in text.split(':'):
                    if not item: raise ValueError('empty/trailing host search fallback refused')
                    if item.startswith('{work}/'):
                        if key not in _SCRATCH or ':' in text or any(p in {'','.','..'} for p in item[7:].split('/')):
                            raise ValueError('closed owned scratch placeholder required')
                    else:
                        directory = _regular(item.removesuffix('//'),directory=True)
                        if not directory.is_relative_to(root): raise ValueError('search path outside admitted regular snapshot')
        if 'PATH' not in row or 'TMPDIR' not in row: raise ValueError('explicit tool PATH and owned temp directory required')
        if platform=='Darwin' and not {'DYLD_PRINT_LIBRARIES','DYLD_PRINT_LIBRARIES_POST_LAUNCH'}<=set(row):
            raise ValueError('complete selected dyld load observation settings required')
        if tool=='compiler':
            required={'TEXMFCNF','TEXMFROOT','TEXMFHOME','TEXMFVAR','TEXMFCONFIG','TEXMFOUTPUT',
                      'TEXINPUTS','TEXFORMATS','openin_any','openout_any','shell_escape','MKTEXPK','MKTEXTFM','MKTEXFMT'}
            if not required<=set(row): raise ValueError('complete explicit offline TeX search/cache settings required')
        result[tool] = dict(row)
    return result


def tool_environment(runtime, tool, work, *, create=True):
    root = Path(runtime['snapshot_root']); tools={k:runtime[k] for k in ('compiler','pdfinfo','svg_converter')}
    contract=environment_contract(runtime['environment'],root,tools,runtime['platform'])
    try:work=_regular(work,directory=True)
    except FileNotFoundError as exc:
        raise ValueError('selected tool work directory is missing') from exc
    result={}
    for key,value in contract[tool].items():
        if value.startswith('{work}/'):
            q=work/value[7:]
            if create:q.mkdir(parents=True,exist_ok=True)
            try:_regular(q,directory=True)
            except FileNotFoundError as exc:
                raise ValueError('selected tool work state is missing: '+str(q)) from exc
            value=str(q)
        result[key]=value
    result.update(_THREADS)
    return result


def materialize(request_pin, out, *, base_dir=None):
    """Fresh regular copies of a complete selected alias-aware source closure.

    Select only needed trees with explicit complete inventory pins. Every alias
    spelling, terminal byte, directory and emitted duplicate is retained/bounded.
    This operation cannot run tools or grant native qualification/approval.
    """
    from . import report_integrity as ri
    base=Path(base_dir or Path(request_pin['path']).absolute().parent)
    consumed=ri.CustodyInputs(); high=ri.custody_limits({'max_files':20000,'max_bytes':MAX_BYTES,'max_metadata_bytes':16*1024**2})
    req=ri._operational_json(request_pin,base,consumed,limits=high)
    _keys(req,['schema_version','trees','allowed_target_roots','tools','environment','platform','platform_dependencies','custody_limits'])
    if type(req['schema_version']) is not int or req['schema_version']!=1: raise ValueError('runtime materialization/v1 required')
    limits=ri.custody_limits(req['custody_limits']); budget=ri.CustodyAccumulator(limits)
    budget.add(next(iter(consumed.values())))
    if request_pin['size']>limits['max_metadata_bytes']: raise ValueError('request exceeds selected metadata capacity')
    if type(req['trees']) is not list or not 1<=len(req['trees'])<=64: raise ValueError('finite selected closure trees required')
    if type(req['allowed_target_roots']) is not list or len(req['allowed_target_roots'])>64: raise ValueError('explicit allowed external target roots required')
    external=[_regular(q,directory=True) for q in req['allowed_target_roots']]
    out=Path(out).absolute(); _regular(out.parent,directory=True)
    if out.exists() or out.is_symlink(): raise ValueError('fresh snapshot output required')
    captured=[]; destinations=set()
    for row in req['trees']:
        _keys(row,['source_root','destination','inventory']); destination=_relative(row['destination'])
        if any(destination==d or destination.startswith(d+'/') or d.startswith(destination+'/') for d in destinations):
            raise ValueError('overlapping snapshot destinations refused')
        destinations.add(destination); source=Path(row['source_root'])
        if not source.is_absolute(): raise ValueError('absolute source root required')
        allowed=sorted(set([source,*external]))
        if any(out.is_relative_to(q) or q.is_relative_to(out) for q in allowed): raise ValueError('snapshot cannot overlap its source')
        declared=ri._operational_json(row['inventory'],base,consumed,limits=limits,accumulator=budget)
        actual=_source_capture(source,allowed,limits)
        if declared!=actual: raise ValueError('source inventory/link/terminal-byte commitment changed')
        captured.append((row,allowed,actual))
    _keys(req['tools'],['compiler','pdfinfo','svg_converter'])
    if any(req['tools'][k] is None for k in ('compiler','pdfinfo')): raise ValueError('compiler/pdfinfo names required')
    for k,name in req['tools'].items():
        if name is not None: _relative(name)
    if Path(req['tools']['compiler']).name!='pdflatex' or Path(req['tools']['pdfinfo']).name!='pdfinfo':
        raise ValueError('source-defined invocation basenames must be preserved')
    if type(req['platform_dependencies']) is not list or len(req['platform_dependencies'])>128:
        raise ValueError('explicit finite host/system-image declarations required')
    out.mkdir(); root=out/'runtime'; root.mkdir(); files={}; provenance=[]
    for row,allowed,capture in captured:
        for relative,leaf in capture['files'].items():
            target=root/row['destination']/relative; target.parent.mkdir(parents=True,exist_ok=True)
            source=Path(leaf['source']['path']); admitted=leaf['source']
            if len(files)>=limits['max_files'] or sum(x['size'] for x in files.values())+admitted['size']>limits['max_bytes']:
                raise ValueError('all emitted aliases/duplicates exceed selected capacity')
            source_fd=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            fields=lambda s:[s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
            h=hashlib.sha256();total=0
            try:
                initial=os.fstat(source_fd)
                if not stat.S_ISREG(initial.st_mode) or fields(initial)!=admitted['identity']:
                    raise ValueError('source identity changed before snapshot copy')
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),leaf['mode'])
                with os.fdopen(source_fd,'rb',closefd=False) as reader,os.fdopen(fd,'wb') as writer:
                    for block in iter(lambda:reader.read(1024**2),b''):
                        total+=len(block)
                        if total>admitted['size']:raise ValueError('source grew during snapshot copy')
                        h.update(block);writer.write(block)
                    writer.flush();os.fsync(writer.fileno())
                if (fields(os.fstat(source_fd))!=admitted['identity'] or fields(_regular(source).stat())!=admitted['identity'] or
                        total!=admitted['size'] or h.hexdigest()!=admitted['sha256']):
                    raise ValueError('source bytes changed during snapshot copy')
            finally:os.close(source_fd)
            target.chmod(leaf['mode']); saved=_identity(target)
            if saved['sha256']!=admitted['sha256'] or saved['size']!=admitted['size']: raise ValueError('intended snapshot bytes changed')
            files[target.relative_to(root).as_posix()]={'sha256':saved['sha256'],'size':saved['size'],'mode':leaf['mode']}
        provenance.append({'selection':row,'complete_source_inventory':capture})
    tools={k:None if name is None else {'path':str(root/name),'sha256':_identity(root/name)['sha256']} for k,name in req['tools'].items()}
    for pin in tools.values():
        if pin is not None and not os.access(pin['path'],os.X_OK): raise ValueError('snapshot invocation must remain executable')
    env=environment_contract(req['environment'],root,tools,req['platform'])
    tree_pin=_emit(out/'tree-manifest.json',{'schema_version':1,'files':{k:v['sha256'] for k,v in files.items()}},limits['max_metadata_bytes'])
    closure={'schema_version':1,'kind':'publication-runtime-snapshot','snapshot_root':str(root),
        'files':files,'source_provenance':provenance,'request':request_pin,'tools':tools,'environment':env,
        'platform':req['platform'],'platform_dependencies':req['platform_dependencies'],'custody_limits':limits,
        'tree_manifest':tree_pin,'qualification':None,'runtime_qualified':False}
    for row,allowed,capture in captured:
        if _source_capture(row['source_root'],allowed,limits)!=capture: raise ValueError('complete source changed at materialization ending')
    closure_pin=_emit(out/'closure-manifest.json',closure,limits['max_metadata_bytes'],compact=True)
    for pin in [tree_pin,closure_pin,*consumed.values()]: ri._dependency(pin,base,consumed,limits=limits,accumulator=budget)
    actual=_inventory(root,limits=limits)
    if {k:{'sha256':v['sha256'],'size':v['size'],'mode':stat.S_IMODE(Path(v['path']).stat().st_mode)} for k,v in actual.items()}!=files:
        raise ValueError('complete regular output population changed at ending')
    for row in actual.values():
        ri._dependency({k:row[k] for k in ('path','sha256','size')},base,consumed,limits=limits,accumulator=budget)
    expected={str(root/name) for name in files}|{str(out/'tree-manifest.json'),str(out/'closure-manifest.json')}
    if {str(q) for q in out.rglob('*') if q.is_file()}!=expected:
        raise ValueError('materialization output membership changed')
    for row,allowed,capture in captured:
        if _source_capture(row['source_root'],allowed,limits)!=capture:raise ValueError('source alias/bytes changed at final output boundary')
    _ending_tree(root,actual,limits=limits)
    return {'closure_manifest':closure_pin,'asset_trees':[{'root':str(root),'manifest':{k:tree_pin[k] for k in ('path','sha256')}}],
        **tools,'environment':env,'platform':req['platform'],'snapshot_root':str(root),'custody_limits':limits,
        'runtime_qualified':False,'commands_executed':False,'scientific_acceptance':False}


def observed_images(stderr, *, pid, snapshot, platform_dependencies):
    """Apple dyld logLoad UUID/path records, never a guessed ld.so log parser.

    Missing/suppressed/older untagged logs keep this capability held. A system
    image UUID is an observed image identity, not an invented shared-cache file.
    """
    system={};uuid_pattern=r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}'
    for row in platform_dependencies:
        _keys(row,['kind','path','uuid'])
        if row['kind']!='system-image' or not Path(row['path']).is_absolute() or not re.fullmatch(uuid_pattern,row['uuid']):
            raise ValueError('explicit observed system image UUID declarations required')
        if row['path'] in system: raise ValueError('duplicate system-image declaration')
        system[row['path']]=row['uuid'].upper()
    pattern=r'^dyld\['+str(pid)+r'\]:\s*<('+uuid_pattern+r')>\s+(/[^\r\n]+)$'
    rows=[];seen=set();root=Path(snapshot['snapshot_root'])
    for line in stderr.splitlines():
        if not line.startswith('dyld['+str(pid)+']:'): continue
        match=re.fullmatch(pattern,line)
        if match is None: raise ValueError('unsupported/suppressed dyld image record; qualification held')
        uuid,path=match.groups();uuid=uuid.upper();key=(path,uuid)
        if key in seen: continue
        seen.add(key); p=Path(path)
        if p.is_relative_to(root):
            relative=p.relative_to(root).as_posix();declared=snapshot['files'].get(relative)
            if declared is None: raise ValueError('unlisted native loaded snapshot image')
            actual=_identity(p)
            if actual['sha256']!=declared['sha256'] or actual['size']!=declared['size']:
                raise ValueError('loaded image changed from snapshot')
            rows.append({'path':path,'uuid':uuid,'kind':'snapshot-image','sha256':actual['sha256'],'size':actual['size']})
        elif system.get(path)==uuid:
            rows.append({'path':path,'uuid':uuid,'kind':'declared-system-image'})
        else: raise ValueError('host fallback/unlisted or changed system loaded image')
    if not rows: raise ValueError('native loader observation missing; qualification held')
    return rows


def _typed_proof_key(value):
    """Private exact-type key; unsupported values take the ordinary path."""
    if value is None:return ('none',)
    if type(value) in (bool,int,str):return (type(value).__name__,value)
    if type(value) is list:return ('list',tuple(_typed_proof_key(v) for v in value))
    if type(value) is dict and all(type(k) is str for k in value):
        return ('dict',tuple((k,_typed_proof_key(v)) for k,v in sorted(value.items())))
    raise TypeError('unsupported runtime proof key')


@contextmanager
def _publication_paths(proof):
    from . import publication_observation as observed
    factory=observed.observation
    if (factory is not observed._FACTORY_OWNER or
            type(factory) is not types.FunctionType or factory.__module__!=observed.__name__ or
            Path(factory.__code__.co_filename).resolve()!=Path(observed.__file__).resolve()):
        yield None
        return
    proof.live()
    source=proof.session.regular_file(observed.__file__,proof.run)
    proof.session.hash_file(source)
    owner=factory(proof)
    if owner is None:
        yield None
    else:
        with owner:
            yield owner


def _check_publication_paths(owner):
    from . import publication_observation as observed
    if type(owner) is not observed._PublicationPaths:
        raise ValueError('exact private publication path observation required')
    observed._CHECK_OWNER(owner)


class _BuildRuntimeProof:
    """Deterministic unqualified assets only, owned by one live science session.

    Author/Graph/review/approval checks never enter this table. Every hit retains
    complete identities/populations; finish replays the unchanged byte readers.
    """
    def __init__(self,session,context,owners):
        self.session=session;self.run=Path(session.rundir).resolve()
        self.context=deepcopy(context);self.owners=owners
        self.operations={};self.active=set()
        session.track(self.context)
        session.retain_final_check(self.finish)

    def live(self):
        from . import execution
        execution._check_validation_session(self.run,self.session)
        if any(current is not original for current,original in self.owners()):
            raise ValueError('publication validator ownership changed during live observation')

    def capture(self,files,identities):
        """Register guarded original reads, never a later unbound baseline."""
        for path,row in identities.items():
            q=self.session.regular_file(path,self.run)
            if (list(self.session.observe(q))!=row['identity'] or
                    self.session.hash_file(q)!=row['sha256']):
                raise ValueError('publication member changed between validation and registration')
        for q in files:
            if str(q) not in identities:raise ValueError('complete runtime capture missing a validated member')

    def current(self,record):
        with _publication_paths(self) as _path_observation:
            self.live()
            root=record['root'];self.session.require_inventory(root)
            if _path_observation is None:_ending_tree(root,record['inventory'],limits=record['limits'])
            else:_ending_tree(root,record['inventory'],limits=record['limits'],_path_observation=_path_observation)
            for path,row in record['identities'].items():
                q=self.session.regular_file(path,self.run)
                if (list(self.session.observe(q))!=row['identity'] or
                        self.session.hash_file(q)!=row['sha256']):
                    raise ValueError('publication proof member identity changed')

    def inventory(self,row,root,limits,*,metadata,replay):
        self.live();key=('asset-tree',_typed_proof_key(row),str(root),_typed_proof_key(limits))
        prior=self.operations.get(key)
        if prior is not None:
            self.current(prior);return deepcopy(prior['result'])
        # No partial/reentrant success or new input ceiling when storage is full.
        if key in self.active or len(self.operations)>=16:return _inventory(root,limits=limits)
        self.active.add(key)
        try:
            self.session.require_inventory(root)
            with _publication_paths(self) as _path_observation:
                actual=(_inventory(root,limits=limits) if _path_observation is None else
                    _inventory(root,limits=limits,_path_observation=_path_observation))
            identities={r['path']:deepcopy(r) for r in actual.values()}
            identities[metadata['path']]=deepcopy(metadata)
            paths=[Path(metadata['path']),*[Path(r['path']) for r in actual.values()]]
            self.capture(paths,identities)
            record={'kind':'asset-tree','root':root,'limits':deepcopy(limits),
                    'inventory':deepcopy(actual),'identities':identities,'result':deepcopy(actual),
                    'paths':paths,'replay':replay}
            self.current(record);self.operations[key]=record
            return deepcopy(actual)
        finally:self.active.discard(key)

    def closure(self,runtime,base,limits,scope):
        from . import report_integrity as ri
        self.live();key=('unqualified-closure',_typed_proof_key(runtime),str(base),_typed_proof_key(limits),False)
        # Controlling metadata is fully reread at each original consumer.
        consumed=ri.CustodyInputs();budget=ri.CustodyAccumulator(limits)
        closure=ri._operational_json(runtime['closure_manifest'],base,consumed,limits=limits,accumulator=budget)
        if (runtime.get('purpose')!='qualification' or closure.get('qualification') is not None or
                closure.get('runtime_qualified') is not False):
            return _closure_inputs(runtime,base,limits,_qualification_scope=scope)
        root=_regular(closure['snapshot_root'],directory=True)
        environment_contract(runtime['environment'],root,{k:runtime[k] for k in ('compiler','pdfinfo','svg_converter')},runtime['platform'])
        tree=ri._operational_json(closure['tree_manifest'],base,consumed,limits=limits,accumulator=budget)
        metadata={p:_identity(p) for p in consumed}
        prior=self.operations.get(key)
        if prior is not None:
            if closure!=prior['result'][0] or tree!=prior['tree']:
                raise ValueError('controlling publication closure metadata changed')
            self.current(prior)
            # Re-establish the full unique union under the selected policy.
            for path in prior['result'][1]:
                row=prior['identities'][str(path)]
                budget.add({k:row[k] for k in ('path','sha256','size')})
            result=deepcopy(prior['result']);self.session.track(result[0]);return result
        if key in self.active or len(self.operations)>=16:
            return _closure_inputs(runtime,base,limits,_qualification_scope=scope)
        self.active.add(key)
        try:
            self.session.require_inventory(root);capture={}
            with _publication_paths(self) as _path_observation:
                result=(_closure_inputs(runtime,base,limits,_qualification_scope=scope,_proof_capture=capture)
                    if _path_observation is None else
                    _closure_inputs(runtime,base,limits,_qualification_scope=scope,_proof_capture=capture,
                        _path_observation=_path_observation))
            if result[0]!=closure:raise ValueError('publication closure changed during initial validation')
            identities={r['path']:deepcopy(r) for r in capture['inventory'].values()}
            identities.update(metadata)
            for path,row in metadata.items():
                if _identity(path)!=row:raise ValueError('runtime metadata changed during first proof')
            self.capture(result[1],identities)
            record={'kind':'unqualified-closure','root':root,'limits':deepcopy(limits),
                    'inventory':deepcopy(capture['inventory']),'identities':identities,
                    'result':deepcopy(result),'tree':deepcopy(tree),'runtime':deepcopy(runtime),'base':base}
            self.current(record);self.operations[key]=record
            returned=deepcopy(result);self.session.track(returned[0]);return returned
        finally:self.active.discard(key)

    def finish(self):
        self.live()
        for record in self.operations.values():
            self.current(record)
            if record['kind']=='asset-tree':
                actual=record['replay']()
                if actual!=record['paths']:raise ValueError('complete asset-tree paths differ at uncached ending replay')
            else:
                # No session or proof in the last full replay; null closure has
                # no stage/author authority and preserves its ordinary scope.
                with _qualification_validation() as scope:
                    actual=_closure_inputs(record['runtime'],record['base'],record['limits'],_qualification_scope=scope)
                if actual!=record['result']:raise ValueError('publication proof differs at uncached ending replay')
            self.current(record)


def _build_runtime_proof(task,base,config_path,config,session,*,build_owners):
    """Admit only an original unqualified build into the existing session."""
    from . import execution,report_integrity as ri
    from . import validation_io
    ValidationSession=validation_io.ValidationSession
    if type(session) is not ValidationSession:
        if session is not None:raise ValueError('exact live scientific validation session required')
        return None
    execution._check_validation_session(session.rundir,session)
    if (type(build_owners) is not types.FunctionType or
            build_owners.__module__!='ravel.physics.manuscript_build' or
            build_owners.__name__!='_build_proof_owners'):return None
    readers=tuple((name,getattr(ri,name)) for name in (
        '_operational_json','_dependency','_artifact_path','_ordinary','_json','custody_limits'))
    if any(type(reader) is not types.FunctionType or reader.__module__!=ri.__name__ or
            reader.__name__!=name or Path(reader.__code__.co_filename).resolve()!=Path(ri.__file__).resolve()
            for name,reader in readers):return None
    owners=lambda:(tuple((globals()[name],original) for name,original in _BUILD_PROOF_OWNERS)+
        tuple((getattr(_BuildRuntimeProof,name),original) for name,original in _BUILD_PROOF_METHODS)+
        tuple((getattr(ri,name),original) for name,original in readers)+tuple(build_owners()))
    if any(current is not original for current,original in owners()):return None
    if (config['schema_version']!=2 or config['runtime'].get('purpose')!='qualification'):return None
    context={'task':task,'literal_base':str(base),'resolved_base':str(Path(base).resolve()),
             'config_path':str(config_path),'config':config,'run':str(Path(session.rundir).resolve())}
    try:key=_typed_proof_key(context)
    except TypeError:return None
    session.track(task);session.track(config)
    # Bind the parsed configuration to the bytes actually registered in this
    # session; a later stat/hash must not become a new configuration baseline.
    config_file=session.regular_file(config_path,session.rundir)
    before=session.observe(config_file);config_hash=session.hash_file(config_file)
    config_pin={'path':str(config_file),'sha256':config_hash,'size':before[3]}
    if (ri._operational_json(config_pin,Path(config_path).parent,{},
            limits=ri.custody_limits(config.get('custody_limits')))!=config or
            session.observe(config_file)!=before):
        raise ValueError('publication configuration changed during proof registration')
    sources=[]
    for p in (config_path,__file__,ri.__file__,validation_io.__file__):
        q=session.regular_file(p,session.rundir);sources.append((str(q),session.hash_file(q)))
    for current,_ in build_owners():
        q=session.regular_file(current.__code__.co_filename,session.rundir)
        sources.append((str(q),session.hash_file(q)))
    identity=('publication-unqualified-runtime-proof/v1',key,tuple(sources),tuple(original for _,original in owners()))
    found=session.proofs.get(identity)
    if found is not None:
        if type(found) is not _BuildRuntimeProof or found.session is not session:
            raise ValueError('caller-supplied publication proof refused')
        found.live();return found
    if sum(isinstance(k,tuple) and k and k[0]=='publication-unqualified-runtime-proof/v1' for k in session.proofs)>=16:return None
    # Fresh original admission; qualified/unsupported closures stay uncached.
    rt=config['runtime'];limits=ri.custody_limits(config.get('custody_limits'))
    closure=ri._operational_json(rt['closure_manifest'],Path(config['runtime_base']),{},limits=limits)
    if closure.get('qualification') is not None or closure.get('runtime_qualified') is not False:return None
    proof=_BuildRuntimeProof(session,context,owners);session.proofs[identity]=proof
    return proof


class _QualificationScope:
    """One pure publication call's live qualification stage observations.

    Only stage traversal is shared. All operational dependency reads, per-tool
    checks and ordered unions still occur at every original consumer call.
    """
    def __init__(self):
        self.closed = False
        self.active = False
        self.ledgers = {}
        self.sessions = {}

    def require_live(self):
        if self.closed or not self.active:
            raise ValueError('closed or inactive publication qualification scope')

    def stage_errors(self, rd, stage, state, record, receipt, limits, *, base):
        from . import execution, report_integrity as ri
        self.require_live()
        run = str(Path(rd).resolve())
        previous = self.ledgers.get(run)
        if previous is not None and state != previous:
            raise ValueError('method execution custody differs: qualification ledger changed within pure call')
        if previous is None:
            self.ledgers[run] = deepcopy(state)
        # Policies, receipt/stage/attempt identities cannot borrow a proof. A
        # different run has its own anchor and independently finished session.
        path = ri._artifact_path(receipt, base)
        key = (run, str(path), receipt['sha256'], receipt['size'], stage,
               execution.digest(record.get('attempt_id')), execution.digest(limits))
        session = self.sessions.get(key)
        if session is None:
            session = execution._validation_session(rd, state)
            self.sessions[key] = session
        execution._check_validation_session(rd, session)
        # Keep fresh mutable arguments tracked and observe actual receipt/ledger
        # identities even when stage_errors returns a previously traversed stage.
        for value in (state, record, receipt, limits):
            session.track(value)
        for current in (session.ledger, path):
            session.require_regular(current)
            session.hash_file(current)
        if session.hash_file(path) != receipt['sha256']:
            raise ValueError('method execution custody differs: qualification receipt changed during observation')
        return execution.stage_errors(rd, stage, state, _session=session)

    def finish(self):
        self.require_live()
        errors = []
        try:
            for session in self.sessions.values():
                errors.extend(session.finish())
            if errors:
                raise ValueError('method execution custody differs: ' + '; '.join(errors))
        finally:
            self.close()

    def close(self):
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()
        self.ledgers.clear()
        self.active = False
        self.closed = True


@contextmanager
def _qualification_validation(scope=None):
    """Own/finish a fresh outward call; nested consumers borrow only that scope."""
    owned = scope is None
    if owned:
        scope = _QualificationScope()
        scope.active = True
    if type(scope) is not _QualificationScope:
        raise ValueError('exact private publication qualification scope required')
    scope.require_live()
    try:
        yield scope
        if owned:
            scope.finish()
    finally:
        if owned:
            scope.close()


def closure_inputs(runtime, base, limits, *, require_qualified=False, _qualification_scope=None):
    # __exit__ finishes every owned session before this result can escape.
    with _qualification_validation(_qualification_scope) as scope:
        return _closure_inputs(runtime, base, limits, require_qualified=require_qualified,
                               _qualification_scope=scope)


def _closure_inputs(runtime, base, limits, *, require_qualified=False, _qualification_scope, _proof_capture=None, _path_observation=None):
    from . import report_integrity as ri
    consumed=ri.CustodyInputs();budget=ri.CustodyAccumulator(limits)
    closure=ri._operational_json(runtime['closure_manifest'],base,consumed,limits=limits,accumulator=budget)
    expected=['schema_version','kind','snapshot_root','files','source_provenance','request','tools','environment',
              'platform','platform_dependencies','custody_limits','tree_manifest','qualification','runtime_qualified']
    _keys(closure,expected)
    if (type(closure['schema_version']) is not int or closure['schema_version']!=1 or
            closure['kind']!='publication-runtime-snapshot' or closure['custody_limits']!=limits):
        raise ValueError('exact source-bound runtime closure/policy required')
    tools={k:runtime[k] for k in ('compiler','pdfinfo','svg_converter')}
    root=(_regular(closure['snapshot_root'],directory=True) if _path_observation is None else
          _regular(closure['snapshot_root'],directory=True,_path_observation=_path_observation))
    if (closure['tools']!=tools or closure['environment']!=runtime['environment'] or
            closure['platform']!=runtime['platform'] or str(root)!=runtime['snapshot_root']):
        raise ValueError('tool/name/environment differs from bound closure')
    environment_contract(runtime['environment'],root,tools,runtime['platform'])
    actual=(_inventory(root,limits=limits) if _path_observation is None else
            _inventory(root,limits=limits,_path_observation=_path_observation))
    rows={k:{'sha256':r['sha256'],'size':r['size'],'mode':stat.S_IMODE(Path(r['path']).stat().st_mode)} for k,r in actual.items()}
    if rows!=closure['files']: raise ValueError('complete snapshot membership/bytes/modes changed')
    tree=ri._operational_json(closure['tree_manifest'],base,consumed,limits=limits,accumulator=budget)
    if tree!={'schema_version':1,'files':{k:r['sha256'] for k,r in rows.items()}}:
        raise ValueError('closure tree manifest differs')
    for row in actual.values():
        ri._dependency({k:row[k] for k in ('path','sha256','size')},base,consumed,limits=limits,accumulator=budget)
    qualification=closure['qualification']
    if runtime.get('purpose')=='qualification' and qualification is not None:
        raise ValueError('qualification purpose must bind the original unqualified snapshot')
    if qualification is None:
        if closure['runtime_qualified'] is not False or require_qualified:
            raise ValueError('runtime loaded-image/format qualification remains held')
    else:
        if closure['runtime_qualified'] is not True: raise ValueError('qualification state differs')
        _keys(qualification,['original_snapshot','host_identity','observations'])
        original=ri._operational_json(qualification['original_snapshot'],base,consumed,limits=limits,accumulator=budget)
        expected_original={**closure,'qualification':None,'runtime_qualified':False}
        if original!=expected_original or qualification['host_identity']!=host_identity():
            raise ValueError('qualified snapshot or current host identity changed')
        required={k for k,v in tools.items() if v is not None}
        if set(qualification['observations'])!=required: raise ValueError('every selected tool needs actual dependency observation')
        for tool,row in qualification['observations'].items():
            _verify_observation(tool,row,closure,base,consumed,budget,limits,_qualification_scope=_qualification_scope)
    if _path_observation is None:_ending_tree(root,actual,limits=limits)
    else:_ending_tree(root,actual,limits=limits,_path_observation=_path_observation)
    if _proof_capture is not None:_proof_capture['inventory']=deepcopy(actual)
    return closure,list(Path(q) for q in consumed)


def _verify_observation(tool, binding, snapshot, base, consumed, budget, limits, *, _qualification_scope=None):
    from . import report_integrity as ri
    _keys(binding,['rundir','receipt','observation'])
    observation=ri._operational_json(binding['observation'],base,consumed,limits=limits,accumulator=budget)
    _keys(observation,['schema_version','kind','purpose','runtime_qualified','tool','host_identity','native_execution','stderr','tex_recorder'])
    if (type(observation['schema_version']) is not int or observation['schema_version']!=1 or
            observation['kind']!='publication-runtime-observation' or observation['purpose']!='qualification' or observation['runtime_qualified'] is not False or observation['tool']!=tool or
            observation['host_identity']!=host_identity() or snapshot['platform']!='Darwin'):
        raise ValueError('unsupported/current-host dependency observation required')
    located={'artifact':binding['observation'],'format':'json','location':'','value':observation}
    stage=ri._executed({k:binding[k] for k in ('rundir','receipt')},[],[located],base,consumed,limits=limits,accumulator=budget,_qualification_scope=_qualification_scope)
    if stage['state']!='current_successful_stage': raise ValueError('actual successful ordinary qualification stage required')
    record=ri._operational_json(binding['receipt'],base,consumed,limits=limits,accumulator=budget)
    from . import science
    from ravel.physics import manuscript_build
    rd=Path(binding['rundir']);rd=rd if rd.is_absolute() else Path(base)/rd
    spec=science.execution_spec(rd)
    if spec.get('schema_version')!=2 or spec.get('mode')!='manuscript-build':raise ValueError('same ordinary manuscript builder qualification required')
    # Admit the original purpose before load() follows any qualified closure.
    # A qualification observation cannot recursively authenticate itself.
    config_path=manuscript_build.custody._regular(spec['task']['config'],rd/'inputs')
    config_pin=_identity(config_path);config_pin={k:config_pin[k] for k in ('path','sha256','size')}
    if not ri._snapshot_member(record,'input_snapshot',config_pin):raise ValueError('same original qualification config omitted from ordinary input custody')
    admitted=ri._operational_json(config_pin,base,consumed,limits=limits,accumulator=budget)
    if (type(admitted.get('schema_version')) is not int or admitted['schema_version']!=2 or
            type(admitted.get('runtime')) is not dict or admitted['runtime'].get('purpose')!='qualification' or
            admitted.get('custody_limits')!=limits):
        raise ValueError('qualification belongs to different original runtime/config/purpose')
    config_path,config,_=manuscript_build.load(spec['task'],rd/'inputs',_qualification_scope=_qualification_scope)
    if config!=admitted:raise ValueError('qualification config changed during validation')
    runtime=config['runtime']
    original,_=closure_inputs(runtime,Path(config['runtime_base']),limits,_qualification_scope=_qualification_scope)
    if (config['schema_version']!=2 or runtime['purpose']!='qualification' or config['custody_limits']!=limits or
            original!={**snapshot,'qualification':None,'runtime_qualified':False}):
        raise ValueError('qualification belongs to different original runtime/config/purpose')
    ri._dependency(config_pin,base,consumed,limits=limits,accumulator=budget)
    receipt=ri._operational_json(observation['native_execution'],base,consumed,limits=limits,accumulator=budget)
    runtime={**snapshot['tools'],'environment':snapshot['environment'],'platform':snapshot['platform'],'snapshot_root':snapshot['snapshot_root']}
    work=_regular(receipt['working_directory'],directory=True)
    env=tool_environment(runtime,tool,work,create=False)
    if (receipt.get('returncode')!=0 or receipt.get('resource_violation') is not None or
            receipt.get('environment_mode')!='explicit' or receipt.get('effective_environment')!=env or
            receipt.get('command',[None])[0]!=snapshot['tools'][tool]['path'] or
            type(receipt.get('pid')) is not int or receipt['pid']<=0):
        raise ValueError('qualification native invocation/effective environment differs')
    for pin in [observation['native_execution'],observation['stderr']]:
        if pin['size']>limits['max_metadata_bytes']:raise ValueError('complete native observation exceeds metadata capacity')
        ri._dependency(pin,base,consumed,limits=limits,accumulator=budget)
        if not ri._snapshot_member(record,'output_snapshot',consumed[str(ri._artifact_path(pin,base))]):
            raise ValueError('observation is outside same ordinary output custody')
    for name,row in snapshot['files'].items():
        pin={'path':str(Path(snapshot['snapshot_root'])/name),'sha256':row['sha256'],'size':row['size']}
        if not ri._snapshot_member(record,'input_snapshot',pin): raise ValueError('qualification omitted selected closure input')
    stderr=ri._artifact_path(observation['stderr'],base).read_text()
    images=observed_images(stderr,pid=receipt['pid'],snapshot=snapshot,platform_dependencies=snapshot['platform_dependencies'])
    if not any(r['path']==snapshot['tools'][tool]['path'] for r in images):
        raise ValueError('selected executable absent from loader observation')
    recorder=observation['tex_recorder']
    if tool=='compiler':
        if recorder is None: raise ValueError('actual compiler recorder/format input required')
        if recorder['size']>limits['max_metadata_bytes']:raise ValueError('complete recorder exceeds metadata capacity')
        ri._dependency(recorder,base,consumed,limits=limits,accumulator=budget)
        if not ri._snapshot_member(record,'output_snapshot',consumed[str(ri._artifact_path(recorder,base))]):
            raise ValueError('compiler recorder outside same output custody')
        paths=[]
        for line in ri._artifact_path(recorder,base).read_text().splitlines():
            if not line.startswith('INPUT '): continue
            p=Path(line[6:]);p=_regular(p if p.is_absolute() else work/p)
            pin=_identity(p);pin={k:pin[k] for k in ('path','sha256','size')}
            if not (ri._snapshot_member(record,'input_snapshot',pin) or ri._snapshot_member(record,'output_snapshot',pin)):
                raise ValueError('qualification recorder consumed undeclared input')
            ri._dependency(pin,base,consumed,limits=limits,accumulator=budget);paths.append(p)
        if not any(p.name=='pdflatex.fmt' and p.is_relative_to(Path(snapshot['snapshot_root'])) for p in paths):
            raise ValueError('selected alias did not consume admitted pdflatex.fmt')
    elif recorder is not None: raise ValueError('non-TeX tool must not claim TeX input observation')
    return images


def qualify(snapshot_pin, observations, out, *, base_dir=None):
    """Derive qualification only from complete current ordinary native evidence.

    This reads existing observations and performs no native calls. Darwin UUID
    records are supported; other loader formats remain an explicit held input.
    """
    from . import report_integrity as ri
    base=Path(base_dir or Path(snapshot_pin['path']).absolute().parent);consumed=ri.CustodyInputs()
    high=ri.custody_limits({'max_files':20000,'max_bytes':MAX_BYTES,'max_metadata_bytes':16*1024**2})
    doc=ri._operational_json(snapshot_pin,base,consumed,limits=high); limits=ri.custody_limits(doc['custody_limits'])
    runtime={**doc['tools'],'closure_manifest':snapshot_pin,'snapshot_root':doc['snapshot_root'],
             'environment':doc['environment'],'platform':doc['platform']}
    with _qualification_validation() as scope:
        closure,paths=closure_inputs(runtime,base,limits,_qualification_scope=scope)
        if closure['qualification'] is not None: raise ValueError('fresh qualification of original materialization required')
        if type(observations) is not dict or set(observations)!={k for k,v in doc['tools'].items() if v is not None}:
            raise ValueError('complete selected tool observation population required')
        budget=ri.CustodyAccumulator(limits)
        for pin in consumed.values(): budget.add(pin)
        for tool,row in observations.items(): _verify_observation(tool,row,doc,base,consumed,budget,limits,_qualification_scope=scope)
        qualified={**doc,'qualification':{'original_snapshot':snapshot_pin,'host_identity':host_identity(),'observations':observations},'runtime_qualified':True}
    out=Path(out).absolute();_regular(out.parent,directory=True)
    pin=_emit(out,qualified,limits['max_metadata_bytes'],compact=True)
    rt={**runtime,'closure_manifest':pin}
    with _qualification_validation() as scope:
        closure_inputs(rt,base,limits,require_qualified=True,_qualification_scope=scope)
        for p in consumed.values(): ri._dependency(p,base,consumed,limits=limits,accumulator=budget)
    return pin


def check(config, *, expected_sha256=None):
    """Check the current actual package/runtime via the original native consumer."""
    from ravel.physics import manuscript_build
    from ravel.workflow import manuscript_format, report_integrity

    p = _regular(config)
    config_before = _identity(p)
    if expected_sha256 is not None and config_before['sha256'] != expected_sha256:
        raise ValueError('selected manuscript configuration differs from its commitment')
    task = {'config': str(p)}
    _, c, package = manuscript_build.load(task, p.parent)
    paths = manuscript_build.inputs(task, p.parent)
    before = {str(q): _identity(q) for q in paths}
    if before[str(p)] != config_before:
        raise ValueError('selected manuscript configuration changed before readiness')
    runtime_base = Path(c['runtime_base'])
    names = ('compiler', 'pdfinfo') + (('svg_converter',) if c['runtime']['svg_converter'] is not None else ())
    binaries = {}
    for name in names:
        q = manuscript_build.custody._pin(c['runtime'][name], runtime_base)
        if not os.access(q, os.X_OK):
            raise ValueError('selected publication executable lacks execute permission: ' + name)
        binaries[name] = {'path': str(q), 'sha256': before[str(q)]['sha256'], 'size': before[str(q)]['size']}
    consumed = {}
    contract = manuscript_format.load(package['formatting_contract'], Path(package['source_base']), consumed)
    required = manuscript_format.required_runtime(contract, has_svg=any(Path(r['path']).suffix.lower() == '.svg' for r in package['figures']))
    if any(Path(r['path']).suffix.lower() in {'.jpg', '.jpeg'} for r in package['figures']):
        required['asset_basenames'].extend(['article.cls', 'graphicx.sty'])
    # Use the actual current complete admission a second time, with exact ending
    # identities. No cross-call cache or rebaselining of changed configurations.
    ending_paths = manuscript_build.inputs(task, p.parent)
    ending = {str(q): _identity(q) for q in ending_paths}
    if ending != before or _identity(p) != config_before:
        raise ValueError('complete manuscript/runtime closure changed at readiness ending')
    for tree in c['runtime']['asset_trees']:
        root = manuscript_build.custody._regular(tree['root'], runtime_base, directory=True)
        remembered = {Path(q).relative_to(root).as_posix(): row for q, row in before.items()
                      if Path(q).is_relative_to(root)}
        _ending_tree(root, remembered,limits=c.get('custody_limits'))
    _ending_inputs(before)
    return {'schema_version': 1, 'kind': 'publication-runtime-readiness',
            'status': 'source_closure_present_runtime_checks_required',
            'config': {k: config_before[k] for k in ('path', 'sha256', 'size')},
            'profile': contract['profile'], 'required': required, 'binaries': binaries,
            'input_pins': [{k: r[k] for k in ('path', 'sha256', 'size')} for r in before.values()],
            'file_count': len(before), 'byte_count': sum(r['size'] for r in before.values()),
            'file_budget': report_integrity.custody_limits(c.get('custody_limits'))['max_files'], 'byte_budget': report_integrity.custody_limits(c.get('custody_limits'))['max_bytes'],
            'commands_executed': False, 'installation_performed': False, 'runtime_qualified': False,
            'scientific_acceptance': False, 'visual_style_accepted': False,
            'limit': 'Actual manuscript_build.load/inputs source admission only. Execute the approved ordinary build for recorder/loaded runtime evidence; official template applicability and CI3 remain separate.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--discover', action='store_true')
    action.add_argument('--inventory', type=Path, metavar='SELECTED_ASSET_ROOT')
    action.add_argument('--check', type=Path, metavar='MANUSCRIPT_BUILD_CONFIG')
    action.add_argument('--source-inventory',type=Path,metavar='SELECTED_SOURCE_ROOT')
    action.add_argument('--materialize',type=Path,metavar='PINNED_PREPARATION_REQUEST')
    action.add_argument('--qualify',type=Path,metavar='PINNED_QUALIFICATION_REQUEST')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--sha256', help='expected selected manuscript-build config digest')
    parser.add_argument('--allowed-target-root',type=Path,action='append',default=[])
    parser.add_argument('--limits',help='closed JSON operational custody limits; default legacy capacities')
    args = parser.parse_args(argv)
    writes=any(x is not None for x in (args.inventory,args.source_inventory,args.materialize,args.qualify))
    if (args.out is not None)!=writes or args.allowed_target_root and args.source_inventory is None:
        parser.error('--out required for writing actions; target roots only for source inventory')
    if (args.materialize or args.qualify) and args.sha256 is None:
        parser.error('materialize/qualify require the original request --sha256')
    if args.sha256 is not None and args.check is None and args.materialize is None and args.qualify is None:
        parser.error('--sha256 applies only to check/materialize/qualify')
    if args.limits is not None and args.inventory is None and args.source_inventory is None:
        parser.error('--limits applies only to inventory preparation; requests bind their own limits')
    try:
        limits=None if args.limits is None else json.loads(args.limits)
        if args.discover:result=discover()
        elif args.inventory:result=inventory(args.inventory,args.out,limits=limits)
        elif args.source_inventory:result=source_inventory(args.source_inventory,args.out,allowed_target_roots=args.allowed_target_root,limits=limits)
        elif args.check:result=check(args.check,expected_sha256=args.sha256)
        else:
            path=args.materialize or args.qualify;observed=_identity(path)
            if observed['sha256']!=args.sha256:raise ValueError('original preparation request differs')
            pin={k:observed[k] for k in ('path','sha256','size')}
            if args.materialize:result=materialize(pin,args.out,base_dir=path.absolute().parent)
            else:
                from . import report_integrity as ri
                req=ri._operational_json(pin,path.absolute().parent,{},limits={'max_files':20000,'max_bytes':MAX_BYTES,'max_metadata_bytes':16*1024**2})
                _keys(req,['snapshot','observations'])
                result=qualify(req['snapshot'],req['observations'],args.out,base_dir=path.absolute().parent)
                if _identity(path)!=observed:raise ValueError('qualification request changed at ending')
    except (ValueError, OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


_BUILD_PROOF_OWNERS=tuple((name,globals()[name]) for name in (
    '_typed_proof_key','_inventory','_ending_tree','_regular','_identity','_stat_identity',
    '_closure_inputs','environment_contract','_build_runtime_proof','_BuildRuntimeProof',
    '_publication_paths','_check_publication_paths'))
_BUILD_PROOF_METHODS=tuple((name,getattr(_BuildRuntimeProof,name)) for name in ('__init__','live','capture','current','inventory','closure','finish'))


if __name__ == '__main__':
    raise SystemExit(main())
