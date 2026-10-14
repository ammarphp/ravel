"""Check that the declared distribution imports without excluded modules."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import warnings
from ravel import evidence_layout


def module_name(relative):
    path=Path(relative)
    if path.suffix!='.py' or not relative.startswith('src/'):
        return None
    parts=list(path.with_suffix('').parts[1:])
    if parts[-1]=='__init__':
        parts.pop()
    return '.'.join(parts)


def import_sites(path, module):
    """Resolve lexical imports; function bodies are deferred, class bodies execute."""
    with warnings.catch_warnings():
        # Parsing only; escape-sequence warnings in shipped third-party sources are not findings.
        warnings.simplefilter('ignore',SyntaxWarning)
        tree=ast.parse(textwrap.dedent(path.read_text()),filename=str(path))
    parent=module if path.name=='__init__.py' else module.rpartition('.')[0]
    def visit(nodes, deferred=False):
        for node in nodes:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                yield from visit(node.body,True)
                continue
            if isinstance(node,ast.Import):
                for alias in node.names:
                    yield node.lineno,alias.name,deferred
            elif isinstance(node,ast.ImportFrom):
                if node.level:
                    parts=parent.split('.')
                    base='.'.join(parts[:len(parts)-node.level+1])
                    base+=(('.'+node.module) if node.module else '')
                else:
                    base=node.module or ''
                yield node.lineno,base,deferred
                for alias in node.names:
                    if alias.name!='*':
                        yield node.lineno,base+'.'+alias.name,deferred
            for field in ('body','orelse','finalbody'):
                children=getattr(node,field,[])
                if isinstance(children,list):
                    yield from visit(children,deferred)
            for handler in getattr(node,'handlers',[]):
                yield from visit(handler.body,deferred)
    return list(visit(tree.body))


_DYNAMIC = r'''
import importlib, importlib.abc, json, sys
root, names, blocked = json.loads(sys.argv[1])
sys.path.insert(0, root + '/src')
class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name+'.') for name in blocked):
            raise ModuleNotFoundError('excluded implementation: '+fullname)
sys.meta_path.insert(0, Refuse())
errors=[]
for name in names:
    try:
        importlib.import_module(name)
    except Exception as exc:
        errors.append({'module':name,'error':type(exc).__name__+': '+str(exc)})
print('__IMPORT_CLOSURE__'+json.dumps(errors))
'''


def check(root, *, registry=None, dynamic=True, extra_withheld=()):
    root=Path(root).resolve()
    # Reuse the export's selection and pattern implementation, including its safe path checks.
    declared=evidence_layout.load_registry(root) if registry is None else json.loads(Path(registry).read_text(), object_pairs_hook=evidence_layout._unique)
    selected=[source for source,_ in evidence_layout.selected_files(root,include_internal=True,registry=declared)]
    shipped=[p for p in selected if evidence_layout._is_shipped(p,declared)]
    excluded=[p for p in selected if not evidence_layout._is_shipped(p,declared)]
    blocked={module_name(p) for p in excluded if module_name(p)}|set(extra_withheld)
    names=sorted({module_name(p) for p in shipped if module_name(p) and (module_name(p)=='ravel' or module_name(p).startswith('ravel.'))})
    names=[n for n in names if n not in blocked]
    findings=[]
    for relative in shipped:
        if not relative.endswith('.py') or not relative.startswith(('src/','tests/','scripts/')):
            continue
        own=module_name(relative) or relative.removesuffix('.py').replace('/','.')
        if own in blocked:
            continue
        for line,target,deferred in import_sites(root/relative,own):
            if deferred:
                continue
            for name in blocked:
                if target==name or target.startswith(name+'.'):
                    row={'file':relative,'line':line,'module':name}
                    if row not in findings:
                        findings.append(row)
    runtime=[]
    if dynamic:
        result=subprocess.run([sys.executable,'-B','-c',_DYNAMIC,json.dumps([str(root),names,sorted(blocked)])],
                              capture_output=True,text=True,timeout=120)
        marker='__IMPORT_CLOSURE__'
        record=next((line[len(marker):] for line in reversed(result.stdout.splitlines()) if line.startswith(marker)),None)
        runtime=json.loads(record) if record is not None else [{'module':'subprocess','error':result.stderr or 'no check result'}]
    return {'ok':not findings and not runtime,'static':sorted(findings,key=lambda r:(r['file'],r['line'],r['module'])),
            'dynamic':runtime,'withheld':sorted(blocked),'imported':len(names) if dynamic else 0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--registry',type=Path)
    args=parser.parse_args(argv)
    result=check(args.root,registry=args.registry)
    print(json.dumps(result,indent=2))
    return 0 if result['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
