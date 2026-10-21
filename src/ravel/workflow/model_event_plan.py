"""Source-only generation blueprint exposed to CLI and the ordinary Graph Host."""
import argparse
import json
import hashlib
import os
from pathlib import Path
from ravel.physics import model_events, model_tool_bridge as bridge
from ravel.workflow import science


def request_inputs(request, base):
    bridge._keys(request, ('schema_version','config','review_policy','supervisor_seconds','goal_binding'), 'generation preparation request')
    model_events.require(request['schema_version'] == 1 and type(request['schema_version']) is int,'preparation schema1 required')
    config=bridge._pin(request['config'],base);policy=bridge._pin(request['review_policy'],base)
    _,c=model_events._load({'config':str(config)},base,expected=request['config']['sha256'])
    model_events.require(type(request['supervisor_seconds']) is int and c['max_seconds']<=request['supervisor_seconds']<=86400,'explicit encompassing supervisor budget required')
    files=model_events.inputs({'config':str(config)},base)+[policy]
    if request['goal_binding'] is not None:
        from .task_completion import binding_projection
        projection=binding_projection(request['goal_binding'],base_dir=base)
        files += [Path(p['path']) for p in projection['input_pins']]
    return sorted(set(files))


def graph_inputs(request, base):
    """Compact source identities, whose exact complete populations inputs validates.

    A tree manifest is not accepted as evidence that its members exist: the
    adapter recomputes every declared source tree and Python support member in
    request_inputs, before and after materialization. All expanded members
    become individual ordinary science stage inputs at plan time.
    """
    config=bridge._pin(request['config'],base)
    _,c=model_events._load({'config':str(config)},base,expected=request['config']['sha256'])
    pins=[config,bridge._pin(request['review_policy'],base)]
    pins += [bridge._pin(x['manifest'],config.parent) for x in [c['runtime']['madgraph_tree'],c['model_tree'],*[d['tree'] for d in c['runtime']['dependencies']]]]
    # The support manifest binds the interpreter digest; the live interpreter
    # is expanded/hashed by request_inputs. Host text-context limits must not
    # be circumvented by presenting a large binary as a prompt artifact.
    pins += [bridge._pin(c['runtime']['python_manifest'],config.parent)]
    pins += [bridge._pin(x,config.parent) for x in c['cards'].values() if x is not None]
    pins += [bridge._pin(x['source'],config.parent) for x in c['weights']['variation_points']]
    texts={name:model_events.authenticated_text(bridge._pin(pin,config.parent),pin['sha256']) for name,pin in c['cards'].items() if pin is not None}
    model_events.validation_evidence(c, config.parent,
        bridge._regular(c['model_tree']['root'], config.parent, directory=True), texts)
    evidence = [c['model_validation'], *[point['model_validation'] for point in c['weights']['variation_points']
                                      if point['kind'] == 'parameter']]
    pins += [bridge._pin(pin, config.parent) for records in evidence for pin in records.values()]
    if 'pre_shower_lhe_transform' in c:
        from ravel.physics import svj_preshower
        texts={name:model_events.authenticated_text(bridge._pin(pin,config.parent),pin['sha256']) for name,pin in c['cards'].items() if pin is not None}
        pins += svj_preshower.inputs(c,config.parent,
            modelroot=bridge._regular(c['model_tree']['root'],config.parent,directory=True),
            mgroot=bridge._regular(c['runtime']['madgraph_tree']['root'],config.parent,directory=True),texts=texts,compact=True)
    if 'generator_reuse' in c:
        from ravel.physics import generator_reuse
        texts={name:model_events.authenticated_text(bridge._pin(pin,config.parent),pin['sha256']) for name,pin in c['cards'].items() if pin is not None}
        reuse=generator_reuse.probe(c,config.parent,texts)
        if 'capsule_pin' in reuse:pins.append(Path(reuse['capsule_pin']['path']))
    if request['goal_binding'] is not None:
        from .task_completion import binding_projection
        pins += [Path(x['path']) for x in binding_projection(request['goal_binding'],base_dir=base)['input_pins']]
    return sorted(set(pins))


def generator_reuse_selection(c, base):
    from ravel.physics import generator_reuse
    texts={name:model_events.authenticated_text(bridge._pin(pin,base),pin['sha256']) for name,pin in c['cards'].items() if pin is not None}
    return generator_reuse.probe(c,base,texts)


def prepare(request, *, base_dir, output_dir, presented_pins=None):
    """Render a fresh specification, never approve, run, or replace the parent goal."""
    base=Path(base_dir);files=request_inputs(request,base)
    original={str(p):bridge._hash(p) for p in files}
    if presented_pins is not None:
        allowed={str(Path(p['path']).resolve()):p['sha256'] for p in presented_pins}
        model_events.require(all(allowed.get(str(path))==bridge._hash(path) for path in graph_inputs(request,base)),
            'complete generator/model/card/runtime/parent source identities must be ordinary Graph inputs')
    config=bridge._pin(request['config'],base); _,c=model_events._load({'config':str(config)},base,expected=request['config']['sha256'])
    policy=json.loads(model_events.authenticated_text(bridge._pin(request['review_policy'],base),request['review_policy']['sha256']))
    spec={'schema_version':2,'mode':'model-events','source':c['source'],'assumptions':c['assumptions'],
          'max_seconds':request['supervisor_seconds'],'approval_mode':'physicist','max_attempts':1,
          'task':{'config':str(config)},'review_policy':policy,'output_policy':model_events.output_policy(c)}
    if request['goal_binding'] is not None:spec['goal_binding']=request['goal_binding']
    science.validate(spec)
    out=Path(output_dir).expanduser().absolute()
    model_events.require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),'fresh regular preparation destination required')
    roots=[bridge._regular(t['root'],config.parent,directory=True) for t in
           [c['runtime']['madgraph_tree'],c['model_tree'],*[d['tree'] for d in c['runtime']['dependencies']]]]
    model_events.require(not any(out==root or out.is_relative_to(root) or root.is_relative_to(out) for root in roots) and
                         not any(path==out or path.is_relative_to(out) for path in files),'preparation may not modify or contain original generator sources')
    out.mkdir(parents=True)
    path=out/'science.json';raw=(json.dumps(spec,indent=2,allow_nan=False)+'\n').encode();path.write_bytes(raw)
    emitted=model_events._generated_pin(path)
    model_events.require(original=={str(p):bridge._hash(p) for p in request_inputs(request,base)},'input source changed during generator preparation')
    model_events.require(path.read_bytes()==raw and model_events._generated_pin(path)==emitted,'generated specification changed before return')
    from ravel.physics import generation_conventions
    convention=generation_conventions.model_events_record(c,model_events.authenticated_text(bridge._pin(c['cards']['process'],config.parent),c['cards']['process']['sha256']),config.parent)
    result={'generation_convention':convention,'schema_version':1,'kind':'model-event-preparation','status':'prepared','specification':emitted,
        'input_pins':[{'path':p,'sha256':sha} for p,sha in original.items()],
        'graph_source_population':'Exact pinned tree/support identities are fully expanded and hashed here; ordinary plan binds every expanded member.',
        'new_events_generated':0,'future_generated_event_ceiling':c['generation']['events'],
        **({'generator_reuse':{k:v for k,v in generator_reuse_selection(c,config.parent).items() if k in ('state','reason','capsule_pin')}} if 'generator_reuse' in c else {}),
        'requested_scheme':c['generation']['scheme'],'goal_binding':request['goal_binding'],
        'execution_authorized':False,'physics_validated':False,
        'next_command':['ravel','plan','--rundir','<fresh-run>','--spec',str(path)],
        'next_requirement':'Ordinary Check-In1, exact current approval, sole native lease, then supervised execution and independent review.'}
    commitment=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode();pending=out/'preparation.pending.json'
    pending.write_bytes(commitment)
    model_events.require(original=={str(p):bridge._hash(p) for p in request_inputs(request,base)},'input source changed during commitment write')
    model_events.require(model_events._generated_pin(path)==emitted and pending.read_bytes()==commitment,'initial generated commitment changed during preparation')
    os.replace(pending,out/'preparation.json')
    try:
        model_events.require(original=={str(p):bridge._hash(p) for p in request_inputs(request,base)} and
            model_events._generated_pin(path)==emitted and (out/'preparation.json').read_bytes()==commitment,'ending preparation source or generated bytes changed')
    except Exception:
        if (out/'preparation.json').exists():os.replace(out/'preparation.json',out/'failed-preparation.json')
        raise
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='action',required=True)
    p=commands.add_parser('prepare');p.add_argument('--request',required=True);p.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    request_path=bridge._regular(args.request,Path.cwd())
    result=prepare(bridge._read(request_path),base_dir=request_path.parent,output_dir=args.out)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
