"""Compose native particle projections and FastJets, then normal source capsules.

This is source construction. Native clustering, particle visibility, weights and
finalization remain in Rivet; no event computation or acceptance is performed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
from ravel import analysis_sources
from . import rivet_jet_component as jets
from . import rivet_particle_component as particles


def compile_component(recipe):
    """Connect explicit topological FinalState nodes to native FastJets inputs."""
    recipe=deepcopy(recipe)
    jets._keys(recipe,('schema_version','kind','particles','jets'))
    if type(recipe['schema_version']) is not int or recipe['schema_version']!=1 or recipe['kind']!='native-rivet-components':
        raise ValueError('native-rivet-components/v1 required')
    p=particles.compile_component(recipe['particles'])
    j=deepcopy(recipe['jets']);jets._keys(j,('schema_version','kind','components'))
    if type(j['components']) is not list or not j['components']:
        raise ValueError('nonempty jet components required')
    symbols=set();names=set();node_ids=set()
    for node in p['recipe']['nodes']:
        if particles.is_final_state(node['kind']):node_ids.add(node['id'])
        symbols.add(node['id'])
        if node['output'] is not None:symbols.add(node['output']['id'])
        if node['projection_name'] is not None:names.add(node['projection_name'])
    links=[]; omitted_access=[]
    for c in j['components']:
        jets._keys(c,('id','projection_name','input','clustering','jet_cuts','output'))
        inp=c['input'];jets._keys(inp,('kind','id'))
        if inp['kind']!='projection' or type(inp['id']) is not str or inp['id'] not in node_ids:
            raise ValueError('jet input must name an admitted native FinalState DAG node')
        links.append((c['id'],inp['id']))
        if c['output'] is None:
            if c['jet_cuts'] != []:
                raise ValueError('null jet output requires empty jet_cuts; no generated collection consumes them')
            c['output']=c['id']+'_collection'
            omitted_access.append(c['output'])
        # Existing compiler validates native algorithms/cuts/policies and all
        # jet-local identities. This temporary input never reaches the output.
        c['input']={'kind':'stable_final_state','cuts':[],'projection_name':None}
    lowered=jets.compile_component(j)
    for c in j['components']:
        js={c['id']+'_fs',c['id']+'_finder',c['output']}
        if c['id'] in symbols or js & symbols or c['projection_name'] in names:
            raise ValueError('particle/jet local or native projection name collision')
        # A particle-local class name must not shadow a native C++ type either.
        if js & (set(particles.CLASSES.values()) | particles.TOP_TYPES):raise ValueError('native class cannot be a jet local')
        symbols.update(js);names.add(c['projection_name'])
    if symbols & {'JetMuons','JetInvisibles','JetAlg','Jets','GeV','FastJets'}:
        raise ValueError('particle local shadows native jet type')
    init=lowered['init']
    analyze='\n'.join(line for line in lowered['analyze'].splitlines() if not any(line.startswith('const Jets '+out+' = ') for out in omitted_access))
    for identity,parent in links:
        standalone=f'const FinalState {identity}_fs(Cuts::OPEN);\n'
        needle=f'const FastJets {identity}_finder({identity}_fs,'
        if init.count(standalone)!=1 or init.count(needle)!=1:raise ValueError('compiler output shape differs')
        init=init.replace(standalone,'',1).replace(needle,f'const FastJets {identity}_finder({parent},',1)
    for details, original in zip(lowered['components'], recipe['jets']['components']):
        details['input']=deepcopy(original['input'])
        details['output']=original['output']
        details['input_cut_phase']='complete_declared_particle_DAG_before_clustering'
    return {'schema_version':1,'kind':'native-rivet-component-source','recipe':recipe,
        'recipe_sha256':jets._digest(recipe),'headers':list(dict.fromkeys(p['headers']+lowered['headers'])),
        'init':p['init']+'\n'+init,'analyze':'\n'.join(v for v in (p['analyze'],analyze) if v),
        'particle_semantics':p['nodes'],'jet_semantics':lowered['components'],
        'links':[{'jet':a,'input_projection':b,'cuts_applied_before_clustering':True} for a,b in links],
        'weights':p['weights'],'native_executed':False,'physics_validated':False,
        'remaining_obligations':list(dict.fromkeys(p['remaining_obligations']+lowered['remaining_obligations']))}


def instantiate(source, *, expected_sha256, recipe):
    """Populate only three explicit whole-line slots, preserving all other bytes."""
    if type(source) is not bytes or not 0<len(source)<=jets.MAX_SOURCE_BYTES or hashlib.sha256(source).hexdigest()!=expected_sha256:
        raise ValueError('bounded exact source template required')
    text=source.decode('utf-8');component=compile_component(recipe)
    repl={'// RAVEL_COMPONENT_HEADERS':'\n'.join('#include "'+h+'"' for h in component['headers']),
          '// RAVEL_COMPONENT_INIT':component['init'],'// RAVEL_COMPONENT_ANALYZE':component['analyze']}
    lines=text.splitlines(keepends=True)
    for slot in repl:
        if text.count(slot)!=1 or sum(line.strip()==slot for line in lines)!=1:
            raise ValueError('three unique whole-line source slots required')
    out=[]
    for line in lines:
        if line.strip() in repl:
            indent=line[:len(line)-len(line.lstrip())];end='\r\n' if line.endswith('\r\n') else '\n'
            out.extend(indent+value+end for value in repl[line.strip()].splitlines())
        else:out.append(line)
    raw=''.join(out).encode()
    if len(raw)>jets.MAX_SOURCE_BYTES:raise ValueError('generated source too large')
    return {'source':raw,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'original_template_sha256':expected_sha256,'component':component,
        'source_capsule_dependency_review':'incomplete_requires_fresh_native_admission'}


def source_capsule(original, *, compile_unit, source, root):
    """New normal capsule identity; keep original assets and unresolved obligations.

    Root must point to a fresh materialization containing the listed files. An
    unchanged source's complete dependency review never carries into this output.
    """
    original=analysis_sources.validate_capsule(deepcopy(original))
    if original['framework']!='rivet':raise ValueError('native Rivet capsule required')
    analysis_sources.relative_path(compile_unit)
    if type(source) is not bytes or not 0<len(source)<=jets.MAX_SOURCE_BYTES:raise ValueError('bounded complete generated unit required')
    if type(root) is not str or not root or root==original['root']:
        raise ValueError('distinct fresh capsule root required')
    capsule=deepcopy(original)
    selected=[f for f in capsule['files'] if f['path']==compile_unit and f['role']=='compile']
    if len(selected)!=1:raise ValueError('exact single declared compile unit required')
    selected[0]['sha256']=hashlib.sha256(source).hexdigest();capsule['root']=root
    capsule['source']={'repository':'supplied','revision':None,'description':'Fresh typed native component derivative; original source/assets retained in materialization lineage.'}
    capsule['dependency_review']={'complete':False,'description':'Fresh changed-source compile/load/all-output validation required; no original acceptance carried.'}
    for dep in capsule['dependencies']:
        if dep['kind'] in ('source','runtime','package'):
            dep['status']='unresolved';dep['reason']='Fresh changed-source admission required; original dependency record retained: '+dep['reason']
    if not any(d['name']=='changed-native-components' for d in capsule['dependencies']):
        capsule['dependencies'].append({'name':'changed-native-components','kind':'source','status':'unresolved',
            'files':[compile_unit],'reason':'Fresh exact native API, complete runtime closure, all event/weight/output and source applicability checks required.'})
    return analysis_sources.validate_capsule(capsule)
