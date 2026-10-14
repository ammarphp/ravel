"""Source-only named spectrum/point preparation through ordinary CLI and Graph.

Every generated specification needs its own Check-In1 and root native lease.
The accepted UFO source and historical input cards are never modified.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path

from ravel.physics import generated_spectrum as engine, model_specific_spectrum as named, model_tool_bridge as custody, spheno_mssm as spheno, chargino_decay_table as decay_table
from . import science


def _load(request,base):
    custody._keys(request,('schema_version','operation','config','review_policy','supervisor_seconds','goal_binding'),'named spectrum preparation request')
    named.require(type(request['schema_version']) is int and request['schema_version']==1 and request['operation']=='build','explicit build preparation schema1 required')
    path=custody._pin(request['config'],base);_,c=engine._load({'config':str(path)},base)
    named.require(c['schema_version']==2 or spheno.selected(c),'explicit released named-model config required, do not relabel legacy CMSSM')
    named.require(type(request['supervisor_seconds']) is int and engine.STAGE_SECONDS<=request['supervisor_seconds']<=86400,'explicit configure/compile/solver supervisor budget required')
    return path,c


def request_inputs(request,base):
    path,c=_load(request,base);files=engine.inputs({'config':str(path)},base)+[custody._pin(request['review_policy'],base)]
    if request['goal_binding'] is not None:
        from .task_completion import binding_projection
        files += [Path(p['path']) for p in binding_projection(request['goal_binding'],base_dir=base)['input_pins']]
    return sorted(set(files))


def graph_inputs(request,base):
    path,c=_load(request,base)
    rows=[path,custody._pin(request['review_policy'],base),named.profile_path(c['profile']),custody._pin(c['input_card'],path.parent)]
    keys=('source_capsule',) if spheno.selected(c) else ('source_capsule','boost_capsule','eigen_capsule')
    rows += [custody._pin(c[key],path.parent) for key in keys]
    if spheno.selected(c):rows += spheno.inputs(c,path.parent)
    elif c['loop_library'] is not None:rows += [custody._pin(p,path.parent) for p in c['loop_library']['files']]
    if request['goal_binding'] is not None:
        from .task_completion import binding_projection
        rows += [Path(p['path']) for p in binding_projection(request['goal_binding'],base_dir=base)['input_pins']]
    return sorted(set(rows))


def _emit(spec,files,out,guards,presented_pins=None,graph_files=()):
    if presented_pins is not None:
        pins={str(Path(p['path']).resolve()):p['sha256'] for p in presented_pins}
        named.require(all(pins.get(str(p))==custody._hash(p) for p in graph_files),'complete named source/card/runtime/parent identities must be actual Graph inputs')
    science.validate(spec)
    out=Path(out).expanduser().absolute()
    named.require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),'fresh canonical named spectrum proposal required')
    named.require(not any(p==out or p.is_relative_to(out) for p in files),'preparation may not contain original inputs')
    named.require(not any(out==root or out.is_relative_to(root) or root.is_relative_to(out) for root in guards.get('source_roots',[])),'preparation may not overlap original scientific/review source trees')
    out.mkdir(parents=True);commitments=[]
    def emit(name,doc):
        pin=named.write_exact(out/name,doc);commitments.append(pin);return pin
    if 'config_document' in guards:
        if 'support_document' in guards:
            guards['config_document']['runtime']['python_manifest']=emit('downstream-python-support.json',guards['support_document'])
        cp=emit('downstream-config.json',guards['config_document']);spec['task']={'config':cp['path']}
        # This is the same public target adapter; no wrapper scientific engine.
        science.adapter(spec).inputs(spec['task'],out)
    sp=emit('science.json',spec)
    doc={'schema_version':1,'kind':'named-spectrum-preparation','specification':sp,'input_pins':[{'path':str(p),'sha256':s} for p,s in guards['before'].items()],
        'mode':spec['mode'],'goal_binding':spec.get('goal_binding'),'physics_validated':False,'execution_authorized':False,'native_calls':0,
        'next_command':['ravel','plan','--rundir','<fresh-run>','--spec',sp['path']],
        'next_requirement':'Fresh ordinary plan, exact actual Check-In1 assent, root native lease and independent actual review.'}
    pending=emit('preparation.pending.json',doc)
    def finish():
        named.require(guards['before']=={p:custody._hash(p) for p in guards['recheck']()},'original named spectrum preparation inputs changed')
        named.require(all(custody._hash(Path(p['path']))==p['sha256'] for p in commitments),'original generated proposal commitments changed')
    finish();(out/'preparation.pending.json').rename(out/'preparation.json');commitments[-1]={**pending,'path':str(out/'preparation.json')}
    try:finish()
    except Exception:
        (out/'preparation.json').rename(out/'failed-preparation.json');raise
    return doc


def prepare(request,*,base_dir,output_dir,presented_pins=None):
    base=Path(base_dir);files=request_inputs(request,base);before={p:custody._hash(p) for p in files};path,c=_load(request,base)
    policy=json.loads(named.raw_file(custody._pin(request['review_policy'],base),request['review_policy']['sha256']))
    named.require(policy['policy']['max_redos']==0,'first named-model experiment has one attempt and zero redo')
    spec={'schema_version':2,'mode':'generated-spectrum','source':c['source'],'assumptions':[
        ('Genuine released NMSSM generated source is used without a new SARAH/Wolfram export; exact supplied input is a selected point, not implicit native defaults.' if c['profile']==named.NAME else 'Genuine released lowMSSM generated source is used without a new SARAH/Wolfram export; exact supplied input is a selected point, not implicit native defaults.'),
        'Complete raw SLHA, all diagnostics, signed masses and occurrence/scale-aware couplings are retained. Native process success does not certify a physical spectrum.',
        'Decay tables require the explicitly selected bound loop library; absent channels/widths remain unknown. No automatic UFO basis/scale mapping.'],
        'max_seconds':request['supervisor_seconds'],'max_attempts':1,'approval_mode':'physicist','task':{'config':str(path)},'review_policy':policy}
    if spheno.selected(c):spec['assumptions']=['Exact complete real weak-scale MSSM SPheno input is required; native card units, branches and source constants are explicit.','Build and solver return one new consistent full spectrum and emitted decay SLHA; no lowMSSM width graft.','All raw diagnostics/channels remain; complete mixed-state hadronic lifetime and supplied parent goal remain unresolved.']
    elif c['profile']!=named.NAME:
        spec['assumptions'].append('Released lowMSSM has no generated decay calculation; missing widths/lifetimes remain unknown and need a separate source-bound decay return.')
    if request['goal_binding'] is not None:spec['goal_binding']=request['goal_binding']
    return _emit(spec,files,output_dir,{'before':before,'recheck':lambda:request_inputs(request,base)},presented_pins,graph_inputs(request,base))


def _absolute_config(c,base):
    """Relocate exact pathname references, never copy/rebind scientific source."""
    def visit(x):
        if type(x) is list:return [visit(v) for v in x]
        if type(x) is dict:
            if set(x)=={'path','sha256'}:return {'path':str(custody._pin(x,base)),'sha256':x['sha256']}
            result={k:visit(v) for k,v in x.items()}
            if set(x)=={'root','manifest'}:result['root']=str(custody._regular(x['root'],base,directory=True))
            return result
        return x
    c=visit(c)
    if 'options' in c['runtime']:
        c['runtime']['options']={k:str(custody._regular(v,base,directory=k.endswith('_path'))) if v is not None else None for k,v in c['runtime']['options'].items()}
    return c


def downstream(request,*,base_dir,output_dir,presented_pins=None):
    custody._keys(request,('schema_version','operation','handoff','config','mode','review_policy','supervisor_seconds','goal_binding'),'named spectrum downstream request')
    named.require(type(request['schema_version']) is int and request['schema_version']==1 and request['operation']=='downstream' and request['mode'] in ('model-tool-bridge','model-events'),'explicit supported downstream preparation required')
    base=Path(base_dir);hpath=custody._pin(request['handoff'],base);h=json.loads(named.raw_file(hpath,request['handoff']['sha256']))
    original=custody._pin(request['config'],base);template=json.loads(named.raw_file(original,request['config']['sha256']))
    # Validate the entire original template before making the explicit card/tree change.
    adapter=science.adapter({'mode':request['mode']});files=adapter.inputs({'config':str(original)},base)
    q=_absolute_config(template,original.parent)
    support_path=custody._pin(template['runtime']['python_manifest'],original.parent);support=deepcopy(custody._read(support_path))
    support['files']=[{'path':str(custody._pin(p,original.parent)),'sha256':p['sha256']} for p in support['files']]
    q['model_tree']=deepcopy(h['model_tree']);q['spectrum_origin']={'path':str(hpath),'sha256':request['handoff']['sha256']}
    if request['mode']=='model-events':q['cards']['parameter']=deepcopy(h['parameter_card'])
    else:q['parameter_card']=deepcopy(h['parameter_card'])
    adapter.validate_config(q)
    origin=lambda:named.origin_inputs(q['spectrum_origin'],base,h['parameter_card'],q['model_tree'])
    files=sorted(set(files+origin()+[original,hpath,custody._pin(request['review_policy'],base)]))
    if request['goal_binding'] is not None:
        from .task_completion import binding_projection
        files=sorted(set(files+[Path(p['path']) for p in binding_projection(request['goal_binding'],base_dir=base)['input_pins']]))
    before={p:custody._hash(p) for p in files}
    named.require(type(request['supervisor_seconds']) is int and q['max_seconds']<=request['supervisor_seconds']<=86400,'explicit encompassing downstream budget required')
    policy=json.loads(named.raw_file(custody._pin(request['review_policy'],base),request['review_policy']['sha256']))
    model='NMSSM' if h['profile']==named.NAME else ('MSSM' if h['profile']==spheno.NAME else 'lowMSSM')
    spec={'schema_version':2,'mode':request['mode'],'source':q['source'],'assumptions':['Actual accepted named '+model+' spectrum and accepted UFO source are joined by an explicit full external address/scale identity map; this is not a physical model or amplitude equivalence certificate.']+(q['assumptions'] if request['mode']=='model-events' else ['Full original supplied tree processes/seeds/runtime are preserved.']),
        'max_seconds':request['supervisor_seconds'],'max_attempts':1,'approval_mode':'physicist','task':{'config':str(original)},'review_policy':policy}
    named.require(policy['policy']['max_redos']==0,'explicit first downstream attempt has zero redo')
    if request['goal_binding'] is not None:spec['goal_binding']=request['goal_binding']
    graph=[original,hpath,custody._pin(request['review_policy'],base),custody._pin(h['model_tree']['manifest'],base),custody._pin(h['parameter_card'],base)]
    if request['goal_binding'] is not None:graph += [Path(p['path']) for p in binding_projection(request['goal_binding'],base_dir=base)['input_pins']]
    def check():
        adapter.inputs({'config':str(original)},base);origin();return files
    trees=[template['runtime']['madgraph_tree'],template['model_tree'],h['model_tree']]+[d['tree'] for d in template['runtime'].get('dependencies',[])]
    roots=[custody._regular(t['root'],original.parent,directory=True) for t in trees]+[custody._regular(h[k],base,directory=True) for k in ('spectrum_run','derivation_run')]
    return _emit(spec,files,output_dir,{'before':before,'recheck':check,'config_document':q,'support_document':support,'source_roots':roots},presented_pins,graph)


def table_prepare(request,*,base_dir,output_dir,presented_pins=None):
    custody._keys(request,('schema_version','operation','request','review_policy','goal_binding'),'pure-limit table preparation')
    named.require(type(request['schema_version']) is int and request['schema_version']==1 and request['operation']=='decay-table','explicit separate table preparation required')
    base=Path(base_dir);rp=custody._pin(request['request'],base);task={'request':str(rp)};files=decay_table.inputs(task,base)+[custody._pin(request['review_policy'],base)]
    if request['goal_binding'] is not None:
        from .task_completion import binding_projection
        files += [Path(p['path']) for p in binding_projection(request['goal_binding'],base_dir=base)['input_pins']]
    files=sorted(set(files));before={p:custody._hash(p) for p in files};policy=spheno.document(spheno.read(custody._pin(request['review_policy'],base),request['review_policy']['sha256']))
    named.require(policy['policy']['max_redos']==0,'pure-limit table first attempt has zero redo')
    spec={'schema_version':2,'mode':'chargino-decay-table','source':'Complete explicitly selected source decay table','assumptions':['All3794 source rows/13 columns and duplicate lineage preserved.','Explicit complete accessible daughter population; pure-limit premise is conditional and needs scientific review.','No interpolation, mixed-MSSM width graft, invented uncertainty or LLP closure.'],'max_seconds':30,'max_attempts':1,'approval_mode':'physicist','task':task,'review_policy':policy}
    if request['goal_binding'] is not None:spec['goal_binding']=request['goal_binding']
    return _emit(spec,files,output_dir,{'before':before,'recheck':lambda:files},presented_pins,files)

def grid_request(request, base):
    from .finite_grid import required, parameter_grid
    required(request, ('schema_version', 'operation', 'config', 'review_policy',
                      'supervisor_seconds', 'grid'))
    if 'goal_binding' not in request:
        from .finite_grid import SpecificationError
        raise SpecificationError('missing_input', 'goal_binding')
    custody._keys(request, ('schema_version', 'operation', 'config', 'review_policy',
                           'supervisor_seconds', 'goal_binding', 'grid'), 'finite grid preparation')
    named.require(request['operation'] == 'parameter-grid', 'explicit parameter-grid operation required')
    build = {k: request[k] for k in ('schema_version', 'config', 'review_policy', 'supervisor_seconds', 'goal_binding')}
    build['operation'] = 'build'
    path, config = _load(build, base)
    grid_path = custody._pin(request['grid'], base)
    grid = json.loads(named.raw_file(grid_path, request['grid']['sha256']))
    coordinates = parameter_grid(grid)
    evidence = [custody._pin(pin, grid_path.parent) for pin in grid['source_evidence']]
    evidence += [custody._pin(dataset['source'], grid_path.parent) for dataset in grid['dataset_population']]
    files = sorted(set(request_inputs(build, base)+[grid_path]+evidence))
    graph = sorted(set(graph_inputs(build, base)+[grid_path]+evidence))
    return build, path, config, grid, coordinates, files, graph


def _card_witness(config, raw):
    """Validate an edited input card with the provider the configuration selects."""
    if spheno.selected(config):
        return spheno.input_witness(raw)
    library = config['loop_library']['name'] if config.get('loop_library') else 'none'
    return named.input_witness(raw, config['calculate_decays'], library, config['profile'])


def prepare_grid(request, *, base_dir, output_dir, presented_pins=None):
    """Prepare every supplied coordinate; each child retains ordinary launch gates."""
    from .finite_grid import edit_card, write_delivery
    from . import execution
    build, path, config, grid, coordinates, files, graph = grid_request(request, base_dir)
    observed = execution._validation_session(base_dir)
    try:
        before = {p: observed.hash_file(observed.regular_file(str(p), base_dir)) for p in files}
        if presented_pins is not None:
            shown = {str(Path(p['path']).resolve()): p['sha256'] for p in presented_pins}
            named.require(all(shown.get(str(p)) == custody._hash(p) for p in graph),
                          'complete source/card/grid/parent identities must be actual Graph inputs')
        raw = named.raw_file(custody._pin(config['input_card'], path.parent), config['input_card']['sha256'])
        # Resolve scientific references without changing their contents.
        absolute = _absolute_config(config, path.parent)
        out = Path(output_dir).expanduser().absolute()
        named.require(not out.exists() and not any(p.is_symlink() for p in (out, *out.parents))
                      and not any(p == out or p.is_relative_to(out) for p in files), 'fresh independent grid proposal required')
        # Validate all edited cards through the selected provider before creating output.
        edits = [edit_card(raw, grid['bindings'], point) for point in coordinates]
        for card_bytes, _ in edits: _card_witness(config, card_bytes)
        out.mkdir(parents=True)
        points, commitments = [], []
        def pin_file(file):
            pin = {'path': str(file), 'sha256': custody._hash(file)}
            commitments.append(pin); return pin
        for index, (coordinate, (card_bytes, changes)) in enumerate(zip(coordinates, edits)):
            directory = out/('point-'+str(index).zfill(4)); directory.mkdir()
            card = directory/'input.slha'; card.write_bytes(card_bytes); card_pin = pin_file(card)
            child_config = deepcopy(absolute); child_config['input_card'] = card_pin
            config_pin = named.write_exact(directory/'config.json', child_config); commitments.append(config_pin)
            child = {**build, 'config': config_pin,
                     'review_policy': {'path': str(custody._pin(build['review_policy'], base_dir)),
                                       'sha256': build['review_policy']['sha256']}}
            proposal = prepare(child, base_dir=directory, output_dir=directory/'proposal')
            commitments.extend((proposal['specification'], pin_file(directory/'proposal/preparation.json')))
            points.append({'id': directory.name, 'coordinate': coordinate, 'input_card': card_pin,
                           'configuration': config_pin, 'specification': proposal['specification'],
                           'exact_row_changes': changes, 'native_calls': 0})
        document = {'schema_version': 1, 'kind': 'finite-parameter-grid-proposals',
                    'study_id': grid['study_id'], 'dataset_population': grid['dataset_population'],
                    'axes': grid['axes'], 'bindings': grid['bindings'],
                    'relations': grid['relations'], 'delivery': grid['delivery'], 'points': points,
                    'point_count': len(points), 'input_pins': [{'path': str(p), 'sha256': sha} for p, sha in before.items()],
                    'goal_binding': request['goal_binding'], 'native_calls': 0, 'execution_authorized': False,
                    'physics_validated': False, 'resources': {'proposed_runs': len(points),
                    'per_point_max_seconds': request['supervisor_seconds'],
                    'aggregate_proposed_max_seconds': len(points)*request['supervisor_seconds']},
                    'next_requirement': 'Every child requires its own ordinary plan, actual CHECK-IN 1, launch admission and review.'}
        named.require(grid['delivery']['filename'] not in {p['id'] for p in points}, 'delivery collides with point directory')
        write_delivery(out, grid['delivery'], document, points)
        commitments.append(pin_file(out/grid['delivery']['filename']))
        membership = lambda: {p.relative_to(out).as_posix(): 'directory' if p.is_dir() else 'file' for p in out.rglob('*')}
        expected = {Path(pin['path']).relative_to(out).as_posix(): 'file' for pin in commitments}
        for point in points:
            expected[point['id']] = 'directory'; expected[point['id']+'/proposal'] = 'directory'
        def finish():
            named.require(membership() == expected and not any(p.is_symlink() for p in (out, *out.parents))
                          and all(not p.is_symlink() for p in out.rglob('*')), 'complete grid output membership changed')
            named.require(grid_request(request, base_dir)[5] == files and before == {p: custody._hash(p) for p in files},
                          'complete grid input graph changed')
            for pin in commitments: named.raw_file(pin['path'], pin['sha256'])
        finish(); errors = observed.finish(); named.require(not errors, '; '.join(errors)); finish()
        return document
    finally:
        observed.close()


def host_preparation(request):
    """One dispatch seam shared by CLI and ordinary Graph source preparation."""
    from .finite_grid import SpecificationError
    methods = {'build': prepare, 'downstream': downstream, 'parameter-grid': prepare_grid, 'decay-table': table_prepare}
    if request.get('operation') not in methods:
        raise SpecificationError('missing_input', 'supported preparation operation and supplied specification')
    return methods[request['operation']]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    for action in ('prepare','point','downstream','grid','decay-table'):
        p=sub.add_parser(action);p.add_argument('--request',required=True);p.add_argument('--out',required=True)
    args=parser.parse_args(argv);path=custody._regular(args.request,Path.cwd());request=json.loads(named.raw_file(path))
    action={'prepare':prepare,'point':named.point_handoff,'downstream':downstream,'grid':prepare_grid,'decay-table':table_prepare}[args.action]
    result=action(request,base_dir=path.parent,output_dir=args.out);print(json.dumps(result,indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
