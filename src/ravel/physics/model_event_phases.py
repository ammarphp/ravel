"""Source-bound MG 2.9.27 LO phase observation; no new integrator.

The admitted engine is run unchanged. Wrappers retain exact arguments, returns
and exceptions. Survey/refine are mixed adaptation/generation, not inferred
pure integration/unweight rates. Unsupported APIs are not calibration evidence.
This standalone driver imports the actual engine only in its native entry.
"""
import ast
import functools
import hashlib
import inspect
import json
from pathlib import Path
import runpy
import sys
import time

APIS = (
    ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_survey', 'survey'),
    ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_refine', 'refine'),
    ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_combine_events', 'combine_events'),
    ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_store_events', 'store_events'),
    ('madgraph.interface.common_run_interface', 'CommonRunCmd', 'do_reweight', 'reweight'),
    ('madgraph.interface.common_run_interface', 'CommonRunCmd', 'do_decay_events', 'decay_events'),
    ('madgraph.interface.madevent_interface', 'MadEventCmd', 'do_shower', 'shower'))


def source_contract(root):
    root = Path(root); rows = []
    for module, owner, method, phase in APIS:
        path = root / (module.replace('.', '/') + '.py')
        raw = path.read_bytes(); tree = ast.parse(raw)
        classes = [x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == owner]
        methods = [] if len(classes) != 1 else [x for x in classes[0].body if isinstance(x, ast.FunctionDef) and x.name == method]
        if len(methods) != 1: raise ValueError('unsupported native phase API: ' + module + '.' + owner + '.' + method)
        fn = methods[0]
        if ([x.arg for x in fn.args.args] != ['self','line'] or fn.args.vararg or
                fn.args.kwarg or fn.args.kwonlyargs): raise ValueError('unsupported native phase signature')
        rows.append({'module': module, 'owner': owner, 'method': method, 'phase': phase,
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'definition_sha256': hashlib.sha256(ast.dump(fn, include_attributes=False).encode()).hexdigest()})
    return rows


def wrap(function, row, emit, stack, checkpoint=None):
    @functools.wraps(function)
    def observed(*args, **kwargs):
        index = emit.next_id; emit.next_id += 1
        nested = bool(stack); start = time.monotonic()
        event = {'id': index, 'phase': row['phase'], 'api': row, 'nested': nested, 'state': 'running'}
        if checkpoint is not None and row['phase']=='survey' and checkpoint[2]['policy']['candidate'] is not None:
            event.update(execution_kind='same_run_survey_restoration',native_survey_invoked=False)
        emit(event); stack.append(index)
        try:
            if checkpoint is not None and row['phase'] == 'survey':
                helper, support, contract = checkpoint
                if contract['policy']['candidate'] is None:
                    result = function(*args, **kwargs)
                    captured=helper.capture(args[0], contract, support)
                    pin={'path':str(Path(captured['tree']['root'])/'checkpoint.json'),
                        'sha256':hashlib.sha256(support.encoded(captured)).hexdigest(),'size':len(support.encoded(captured))}
                    emit(dict(event,state='captured',checkpoint=pin))
                else:
                    result = helper.restore_survey(args[0], args[1], contract, support)
                    emit(dict(event, state='restored', checkpoint=contract['checkpoint_pin']))
            else:
                result = function(*args, **kwargs)
        except BaseException as exc:
            emit(dict(event, state='failed', wall_seconds=time.monotonic()-start,
                error_type=type(exc).__name__))
            raise
        else:
            emit(dict(event, state='completed', wall_seconds=time.monotonic()-start))
            return result
        finally:
            stack.pop()
    return observed


def final_rows(journal, expected):
    rows = [json.loads(line) for line in Path(journal).read_text().splitlines() if line]
    starts = {}; ends = {}
    for row in rows:
        if row.get('api') not in expected or type(row.get('id')) is not int or type(row.get('nested')) is not bool:
            raise ValueError('foreign native phase identity')
        index = row['id']
        if row['state'] == 'running':
            if index in starts: raise ValueError('duplicate native phase start')
            starts[index] = row
        elif row['state'] in ('restored','captured'):
            if index not in starts: raise ValueError('restoration without phase boundary')
        elif row['state'] in ('completed','failed'):
            if index not in starts or index in ends or any(row.get(key) != starts[index].get(key) for key in ('phase','api','nested')):
                raise ValueError('native phase completion differs')
            ends[index] = row
        else: raise ValueError('unknown native phase state')
    return [ends.get(index, row) for index,row in starts.items()]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4: raise ValueError('root/request/journal/request-digest required')
    root, request, journal, digest = map(str, args)
    raw = Path(request).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest: raise ValueError('native phase request changed')
    contract = json.loads(raw)
    if source_contract(root) != contract['apis']: raise ValueError('native API sources changed')
    if hashlib.sha256(Path(contract['launch']['path']).read_bytes()).hexdigest() != contract['launch']['sha256']:
        raise ValueError('native phase launch changed')
    sys.path.insert(0, str(Path(root).absolute()))
    import importlib
    reuse_helper=None; capture=contract.get('reuse_capture')
    if capture is not None:
        from importlib.util import spec_from_file_location,module_from_spec
        helper_raw=Path(capture['helper']['path']).read_bytes()
        if hashlib.sha256(helper_raw).hexdigest()!=capture['helper']['sha256']:raise ValueError('reuse helper changed')
        loader=spec_from_file_location('native_generator_reuse',capture['helper']['path']);reuse_helper=module_from_spec(loader)
        sys.modules[loader.name]=reuse_helper;loader.loader.exec_module(reuse_helper)
        if reuse_helper.build_api(root)!=capture['api']:raise ValueError('static build API changed')
        raw=reuse_helper.regular_bytes(capture['export']['path'],16*1024**2)
        if hashlib.sha256(raw).hexdigest()!=capture['export']['sha256']:raise ValueError('prelaunch export pin changed')
        export=reuse_helper.read_document(capture['export']['path']);reuse_helper.verify_tree(export)
        api=capture['api'];owner=getattr(importlib.import_module(api['module']),api['owner'])
        original=owner.__dict__[api['method']]
        if Path(inspect.getsourcefile(original)).resolve()!=(Path(root)/(api['module'].replace('.','/')+'.py')).resolve():raise ValueError('foreign static build implementation')
        @functools.wraps(original)
        def observe_static(*arguments,**keywords):
            result=original(*arguments,**keywords)
            if Path(arguments[0].me_dir).resolve()!=Path(capture['process']).resolve():raise ValueError('foreign native process build')
            if not Path(capture['destination']).exists():
                try:reuse_helper.capture_static(capture['process'],capture['destination'],export,capture['static_sha256'],api)
                except (OSError,ValueError) as exc:
                    failure=Path(capture['destination']);failure.mkdir(parents=True,exist_ok=True)
                    reuse_helper.write_document(failure/'unavailable.json',{'state':'unavailable','phase':'static-source-build','reason':str(exc)})
            return result
        setattr(owner,api['method'],observe_static)
    stack = []
    checkpoint = None
    if 'integration_checkpoint' in contract:
        import importlib.util
        spec = contract['integration_checkpoint']
        def helper_module(pin, name):
            raw = Path(pin['path']).read_bytes()
            if len(raw) != pin['size'] or hashlib.sha256(raw).hexdigest() != pin['sha256']:
                raise ValueError('checkpoint helper changed')
            module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name,pin['path']))
            exec(compile(raw,pin['path'],'exec'),module.__dict__)
            return module
        helper = helper_module(spec['helper'], 'ravel_native_checkpoint')
        support = helper_module(spec['storage_helper'], 'ravel_checkpoint_storage')
        helper.source_inputs(root,support)
        checkpoint = (helper,support,spec['request'])
    with Path(journal).open('x') as stream:
        def emit(row):
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n'); stream.flush()
        emit.next_id = 0
        for row in contract['apis']:
            module = importlib.import_module(row['module']); owner = getattr(module, row['owner'])
            function = owner.__dict__[row['method']]
            if Path(inspect.getsourcefile(function)).resolve() != (Path(root)/(row['module'].replace('.', '/')+'.py')).resolve():
                raise ValueError('foreign native phase implementation')
            setattr(owner, row['method'], wrap(function, row, emit, stack, checkpoint=checkpoint))
        sys.argv = [str(Path(root)/'bin/mg5_aMC'), contract['launch']['path']]
        runpy.run_path(sys.argv[0], run_name='__main__')
        if capture is not None:
            raw=reuse_helper.regular_bytes(capture['helper']['path'],128*1024**2)
            if len(raw)!=capture['helper']['size'] or hashlib.sha256(raw).hexdigest()!=capture['helper']['sha256']:
                raise ValueError('ending static capture helper changed')
            reuse_helper.verify_tree(export)


if __name__ == '__main__': main()
