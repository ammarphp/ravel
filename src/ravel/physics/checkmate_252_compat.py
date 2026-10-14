"""Exact CheckMATE2.5.2 optional-import and configured-entry source derivative.

Original installation unchanged. A single patched core is selected through an
explicit entry overlay; all other CheckMATE Python/data/Fritz paths stay original.
Moving imports to stateval removes no statistical calculation or failure there.
"""
from pathlib import Path
from ravel.physics import backend_provider as p

REVISION='bacf9d17ff8e844e3b40851849e21f0dd0f0638c'
ORIGINALS={
 'tools/python/CheckMATE.raw':'1c234150a76134f3b640f57174d13306113eeaa293d023b6b0b8c1b7d9295402',
 'tools/python/checkmate_core.py':'55f266d9ab29c437c49ad79f8ab32ae428bd208ccd2630ad7c69f62299fd351e',
 'tools/python/info.py':'308b072bbda886eff9f27eb323f681cfcda3eb0ba840b978c1c5d33a1fe6bd49'}
IMPORTS='''    import multibin_limit as mb
    import multibin_limit_full as mbfull
    import workspace_calc as wscalc
    import spey_wrapper
    import hs3_wrapper as hs3
'''
EAGER='if sys.version_info[0] == 3:\n'+IMPORTS
PATH_LINE='sys.path.append(os.path.join(os.path.split(os.path.split(os.path.realpath(__file__))[0])[0], "tools", "python"))'

def _pin(path):return {'path':str(Path(path).resolve()),'sha256':p._sha(path)}

def original(root):
    root=Path(root).resolve()
    if (root/'VERSION').read_text().strip()!='2.5.2':raise ValueError('explicit2.5.2 original required')
    for rel,h in ORIGINALS.items():
        if p._sha(root/rel)!=h:raise ValueError('original2.5.2 source differs: '+rel)
    return root

def patched_core(text):
    if text.count(EAGER)!=1 or text.count('    def stateval(self):')!=1:
        raise ValueError('exact released optional-import/stateval boundaries required')
    result=text.replace(EAGER,'# RAVEL2.5.2 derivative: optional multibin imports occur only in stateval.\n')
    result=result.replace('    def stateval(self):',
       '    def stateval(self):\n'+''.join('    '+line+'\n' for line in IMPORTS.splitlines()))
    compile(result,'changed-source-checkmate-core','exec')
    return result

def _entry(root,values,overlay):
    if set(values)!= {'python','ROOT_LIB_DIR','MADGRAPH_DIR','PYTHIA_DIR'}:
        raise ValueError('exact2.5.2 configure fields required')
    if any(not isinstance(v,str) or any(c in v for c in ("'",'"','\n','\r')) for v in values.values()):
        raise ValueError('literal configure fields required')
    for x in (str(root),str(overlay),values['python'],values['ROOT_LIB_DIR'],values['PYTHIA_DIR']):p._native_path(x)
    text=(root/'tools/python/CheckMATE.raw').read_text()
    text=text.replace('#!/usr/bin/python','#!'+values['python'])
    for k in ('ROOT_LIB_DIR','MADGRAPH_DIR','PYTHIA_DIR'):text=text.replace(k,values[k])
    # All non-core modules remain imported from the original configured source.
    derivative=text.replace(PATH_LINE,'sys.path.append('+repr(str(root/'tools/python'))+')\nsys.path.insert(0, '+repr(str(overlay))+')')
    if derivative==text:raise ValueError('released entry import boundary absent')
    compile(derivative,'changed-source-checkmate-entry','exec')
    return text,derivative

def prepare(root,values,out):
    root=original(root);out=Path(out).resolve()
    if out.exists():raise FileExistsError(out)
    baseline,entry=_entry(root,values,out/'python-overlay')
    if (root/'bin/CheckMATE').read_text()!=baseline:
        raise ValueError('configured original entry differs from exactraw substitutions')
    out.mkdir(parents=True);overlay=out/'python-overlay';overlay.mkdir()
    core=overlay/'checkmate_core.py';core.write_text(patched_core((root/'tools/python/checkmate_core.py').read_text()))
    script=out/'CheckMATE';script.write_text(entry)
    return {'kind':'explicit-checkmate252-optional-import-overlay','original_entry':_pin(root/'bin/CheckMATE'),
       'original_template':_pin(root/'tools/python/CheckMATE.raw'),'original_core':_pin(root/'tools/python/checkmate_core.py'),
       'original_info':_pin(root/'tools/python/info.py'),'overlay_core':_pin(core),'overlay_root':str(overlay),
       'changed_entry':_pin(script),'source_revision':REVISION,'runtime_qualified':False}

def verify(root,script,values,contract):
    root=original(root)
    names={'kind','original_entry','original_template','original_core','original_info','overlay_core',
           'overlay_root','changed_entry','source_revision','runtime_qualified'}
    if set(contract)!=names or contract['kind']!='explicit-checkmate252-optional-import-overlay' or contract['source_revision']!=REVISION or contract['runtime_qualified'] is not False:
        raise ValueError('exact unqualified2.5.2 changed-source overlay contract required')
    expected={'original_entry':root/'bin/CheckMATE','original_template':root/'tools/python/CheckMATE.raw',
              'original_core':root/'tools/python/checkmate_core.py','original_info':root/'tools/python/info.py',
              'changed_entry':Path(script).resolve(),'overlay_core':Path(contract['overlay_root'])/'checkmate_core.py'}
    for key,path in expected.items():
        if contract[key]!=_pin(path):raise ValueError('overlay original/derivative changed: '+key)
    overlay=Path(contract['overlay_root'])
    if overlay.is_symlink() or not overlay.is_dir() or sorted(x.name for x in overlay.iterdir())!=['checkmate_core.py']:
        raise ValueError('overlay must contain only the exact core source; no unbound import preemption')
    baseline,entry=_entry(root,values,overlay)
    if (root/'bin/CheckMATE').read_text()!=baseline or Path(script).read_text()!=entry:
        raise ValueError('entry differs from exact original/overlay transformation')
    if (overlay/'checkmate_core.py').read_text()!=patched_core((root/'tools/python/checkmate_core.py').read_text()):
        raise ValueError('optional-import derivative differs from exact source transformation')
    return {'source_root':str(root),'data_root':str(root/'data'),'python_source_root':str(root/'tools/python'),
       'fritz':str(root/'tools/fritz/bin/fritz'),'changed_core':contract['overlay_core'],'changed_entry':contract['changed_entry'],
       'scope':'Explicit2.5.2 optional-import derivative; other Info/data/Fritz paths remain original. Loaded runtime/card/library identities unobserved.'}
