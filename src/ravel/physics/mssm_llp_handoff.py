"""Source-only MSSM point identity/lifetime join to the existing LLP recipe.

Rates, branching models, event cohorts, detector response, fitted bins and goal
binding are supplied by the original complete template. No rate/acceptance is
inferred from a neutralino or chargino mixing fraction.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from . import mssm_observable_map as mapping


def _json_bytes(value):
    return (json.dumps(value,indent=2,allow_nan=False)+'\n').encode()


def _write(path,value,observed):
    raw=_json_bytes(value)
    mapping.require(len(raw)<=mapping.MAX_INPUT_BYTES,'bounded complete handoff output required')
    path.write_bytes(raw)
    observed[path]=(raw,mapping._identity(path))
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def prepare(task,base,template_path,output):
    """Build the actual ordinary adapter input without approval or dispatch."""
    path,d,files,before=mapping._capture(task,base)
    template=mapping.custody._regular(template_path,base)
    template_raw=mapping.slha.raw_file(template);template_identity=mapping._identity(template)
    q=mapping.loads(template_raw)
    mapping.keys(q,('schema_version','source','goal_binding','analysis','axes','points','projection_scenarios','cells',
                    'mixture_sampling','generation_policy','inference_policy','child_seconds','assumptions',
                    *(['construction_limits'] if 'construction_limits' in q else [])), 'complete original LLP template')
    expected_axes=[{k:a[k] for k in ('id','unit')}|{'values':[mapping.finite(mapping.rational(x)) for x in a['values']]} for a in d['axes']]
    mapping.require(q['schema_version']==1 and q['axes']==expected_axes and q['analysis']['energy_tev']==mapping.finite(mapping.rational(d['energy_tev'])),
                    'template must retain complete original plane and collider energy')
    mapping.require(d['population']['kind']=='cartesian','the existing LLP recipe requires a complete Cartesian plane; source-listed maps remain ready for a separately explicit study')
    limits=q.get('construction_limits',{'max_points':32,'max_cells':128})
    mapping.keys(limits,('max_points','max_cells'),'declared source construction resource limits')
    mapping.require(type(limits['max_points']) is int and 1<=limits['max_points']<=512 and
                    type(limits['max_cells']) is int and 1<=limits['max_cells']<=2048,'bounded declared source construction limits required')
    mapping.require(len(q['points'])==len(d['points'])<=limits['max_points'] and
                    [p['id'] for p in q['points']]==[p['id'] for p in d['points']],
                    'entire plane must fit declared construction resources; no partition or missing-point substitution')
    for a,b in zip(q['points'],d['points']):
        mapping.keys(a,('id','coordinate','identity','components','lifetimes'),'original LLP point template')
        mapping.require(a['identity'] is None and a['lifetimes']==[{'id':'spectrum_total_width','ctau_mm':None}] and
                        a['coordinate']==[mapping.finite(mapping.rational(x)) for x in b['coordinate']],
                        'only explicit source-total-width placeholders may be materialized; existing physical inputs never overwritten')
        mapping.require([c['id'] for c in a['components']]==[c['id'] for c in d['components']], 'complete declared production components required')
    result=mapping._derive(path,d,before)
    needed=set(i for c in d['components'] for i in c['species'])
    missing=[{'point_id':p['id'],'species_id':s['id'],'lifetime_status':s['lifetime']['status']}
             for p in result['points'] for s in p['observables'] if s['id'] in needed and s['lifetime']['status']!='finite_from_supplied_total_width']
    mapping._finish(task,base,files,before)
    mapping.require(mapping.slha.raw_file(template)==template_raw and mapping._identity(template)==template_identity,
                    'original LLP template changed during map preparation')
    if missing:
        return {'schema_version':1,'status':'blocked','unresolved_lifetimes':missing,'map_population':result['population'],
                'next_action':'supply source-bound positive total widths or retain a separately appropriate stable/prompt study',
                'physics_validated':False,'execution_authorized':False,'original_task_complete':False,'inputs_written':False}
    out=Path(output).expanduser().absolute()
    mapping.require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)) and
                    not any(p.is_relative_to(out) for p in [*files,template]), 'fresh independent handoff directory required')
    out.mkdir(parents=True);written={};template_pin={'path':str(template),'sha256':hashlib.sha256(template_raw).hexdigest(),'size':len(template_raw)}
    try:
        map_pin=_write(out/'mssm-observable-map.json',result,written)
        for target,point,source in zip(q['points'],result['points'],d['points']):
            species={s['id']:s for s in point['observables']}
            identity={'schema_version':1,'coordinate':target['coordinate'],'energy_tev':q['analysis']['energy_tev'],
              'spectrum':{'path':str(mapping._pin(source['spectrum'],path.parent)), 'sha256':source['spectrum']['sha256'],
                          'size':mapping._pin(source['spectrum'],path.parent).stat().st_size},
              'components':[{'id':c['id'],'process':c['process'],'decay_channels':c['decay_channels'],
                 'llp_species':[{'id':i,'mass_GeV':mapping.finite(Fraction(species[i]['pole_mass_GeV_exact'])),
                                 'charge_e':mapping.finite(mapping.rational(species[i]['charge_e']))} for i in c['species']]} for c in d['components']],
              'sources':[map_pin,template_pin,*result['input_pins']]}
            target['identity']=_write(out/(point['id']+'-identity.json'),identity,written)
            for component in target['components']:
                for key in ('cohort','response'):
                    ref=component[key]
                    if ref is not None:
                        raw=mapping._output_bytes(mapping.custody._regular(ref['path'],path.parent))
                        mapping.require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'supplied '+key+' bytes differ')
                        body=mapping.loads(raw)
                        mapping.require(body['point_identity_sha256']==target['identity']['sha256'] and body['component_id']==component['id'],
                                        'existing '+key+' cannot be relabelled as a different MSSM physical point')
            target['lifetimes'][0]['ctau_mm']={i:mapping.finite(Fraction(species[i]['lifetime']['proper_ctau_mm_exact'])) for i in sorted(needed)}
        # All non-placeholder template values are retained, including parent,
        # source cross sections, SR/CR definitions, full scenarios and cells.
        recipe_pin=_write(out/'llp-recipe.json',q,written)
        from . import llp_plane_recipe
        dependencies=llp_plane_recipe.inputs({'input':recipe_pin['path']},out)
        mapping._finish(task,base,files,before)
        mapping.require(mapping.slha.raw_file(template)==template_raw and mapping._identity(template)==template_identity,
                        'original template changed during final ordinary input validation')
        captured={p:(mapping._output_bytes(p),mapping._identity(p)) for p in dependencies}
        pins=[{'path':str(p),'sha256':hashlib.sha256(v[0]).hexdigest(),'size':len(v[0])} for p,v in captured.items()]
        # Commit the exact dependencies used by the ordinary adapter, then
        # recheck all original and generated files before returning the handoff.
        mapping._finish(task,base,files,before)
        mapping.require(mapping.slha.raw_file(template)==template_raw and mapping._identity(template)==template_identity,
                        'original template changed at handoff return')
        for p,(raw,identity) in written.items():
            mapping.require(mapping._output_bytes(p)==raw and mapping._identity(p)==identity,'generated handoff copy changed, including restored-byte drift')
        mapping.require(dependencies==llp_plane_recipe.inputs({'input':recipe_pin['path']},out),'complete ordinary LLP input population changed at return')
        for p,(raw,identity) in captured.items():
            mapping.require(mapping._output_bytes(p)==raw and mapping._identity(p)==identity,'ordinary LLP dependency changed, including restored-byte drift')
        return {'schema_version':1,'status':'prepared','ordinary_mode':'llp-plane-recipe','ordinary_task':{'input':recipe_pin['path']},
           'recipe':recipe_pin,'map':map_pin,'goal_binding':deepcopy(q['goal_binding']),
           'ordinary_input_pins':pins,
           'prepared_points':len(q['points']),'production_and_response_supplied_unchanged':True,
           'physics_validated':False,'execution_authorized':False,'original_task_complete':False}
    except Exception:
        # Preserve exact partial artifacts and an explicit failed construction.
        (out/'HANDOFF-FAILED.txt').write_text('No completed LLP handoff returned. Exact partial artifacts are retained.\n')
        raise
