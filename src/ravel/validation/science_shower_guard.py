"""Source-bound, standalone pre-shower interceptor for the existing MG child.

It invokes the original admitted command unchanged after installing lhe_check
on the source-bound LO/NLO shower entry. No generator implementation is copied.
"""
import ast
import functools
import hashlib
import importlib
import json
from pathlib import Path
import runpy
import sys


def source_contract(root, order):
    module, owner, method = ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_pythia8') if order == 'LO' else (
        'madgraph.interface.amcatnlo_run_interface', 'aMCatNLOCmd', 'do_shower')
    path = Path(root) / (module.replace('.', '/') + '.py')
    raw = path.read_bytes()
    classes = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == owner]
    methods = [] if len(classes) != 1 else [n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == method]
    if len(methods) != 1:
        raise ValueError('lhe_check cannot bind the native pre-shower API')
    return {'module': module, 'owner': owner, 'method': method, 'source_sha256': hashlib.sha256(raw).hexdigest()}


def install(owner, contract, checker):
    original = getattr(owner, contract['api']['method'])
    @functools.wraps(original)
    def checked(self, *args, **kwargs):
        return checker.guard_shower(original, process=contract['process'], run_name='ravel',
            output=contract['output'], param_card=contract['parameter_card'])(self, *args, **kwargs)
    setattr(owner, contract['api']['method'], checked)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        raise ValueError('guard request/digest/original-driver/arguments required')
    request, digest, driver, *arguments = args
    raw = Path(request).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('lhe_check guard request changed')
    c = json.loads(raw)
    if source_contract(c['madgraph'], c['order']) != c['api']:
        raise ValueError('lhe_check native shower source changed')
    helper = c['helper']; data = Path(helper['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != helper['sha256']:
        raise ValueError('lhe_check helper source changed')
    import types
    checker = types.ModuleType('ravel_native_lhe_check')
    checker.__file__ = helper['path']
    checker.__package__ = 'ravel.validation'
    exec(compile(data, helper['path'], 'exec'), checker.__dict__)
    sys.path.insert(0, str(Path(c['madgraph']).absolute()))
    owner = getattr(importlib.import_module(c['api']['module']), c['api']['owner'])
    original = getattr(owner, c['api']['method'])
    source = Path(c['madgraph']) / (c['api']['module'].replace('.', '/') + '.py')
    if Path(original.__code__.co_filename).resolve() != source.resolve():
        raise ValueError('lhe_check foreign loaded shower implementation')
    install(owner, c, checker)
    sys.argv = [driver, *arguments]
    runpy.run_path(driver, run_name='__main__')
    if hashlib.sha256(Path(helper['path']).read_bytes()).hexdigest() != helper['sha256']:
        raise ValueError('lhe_check ending helper source changed')


if __name__ == '__main__':
    main()
