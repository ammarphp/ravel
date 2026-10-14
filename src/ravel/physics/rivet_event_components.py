"""Typed native dilepton/remaining-state/jet/recoil construction.

Rivet owns pairing, dressing, constituents and visible momentum. This module
emits complete init/access fragments; it does not calculate events or infer
histogram units, weights, detector response or a statistical model.
"""
from copy import deepcopy
import hashlib
from . import rivet_jet_component as jets
from . import rivet_particle_component as particles
from . import rivet_components as connected

RESERVED=set(particles.CLASSES.values())|{'MissingMomentum','MissingMom','DileptonFinder','ZFinder','LLFinder','LeptonOrigin','PhotonOrigin','TauDecaysAs','MuDecaysAs','DressingType','Particles','Vector3','FourMomentum','DressedLeptons'}
ORIGINS={'prompt':'PROMPT','decay':'DECAY','all':'ALL'}
PHOTONS={'none':'NONE','nodecay':'NODECAY','all':'ALL'}
MET_METHODS={'missing_pt':('double','missingPt','GeV'), 'missing_et':('double','missingEt','GeV'),
 'scalar_visible_pt':('double','scalarSumPt','GeV'), 'scalar_visible_et':('double','scalarSumEt','GeV'),
 'vector_missing_pt':('Vector3','vectorMissingPt','GeV'), 'vector_missing_et':('Vector3','vectorMissingEt','GeV'),
 'vector_visible_pt':('Vector3','vectorSumPt','GeV'), 'vector_visible_et':('Vector3','vectorSumEt','GeV')}


def _id(value):
    value=particles._identifier(value)
    if value in RESERVED:raise ValueError('native event type cannot be a local')
    return value


def _pair_cuts(value):
    jets._keys(value,('kinematics','mass_window'))
    cuts=jets._cuts(value['kinematics']);window=value['mass_window']
    if window is None:return cuts
    jets._keys(window,('low','high','unit','operation'))
    low=jets._number(window['low']);high=jets._number(window['high'])
    if window['unit']!='GeV' or window['operation']!='native_massIn' or low>=high:
        raise ValueError('ordered explicit GeV native massIn window required')
    mass=f'Cuts::massIn({repr(low)}*GeV, {repr(high)}*GeV)'
    return mass if cuts=='Cuts::OPEN' else '('+cuts+') && '+mass


def compile_component(recipe, *, source_units=None):
    """Lower a complete dependency pipeline using original native operations.

    Stages are native particle DAG, dressed OSSF pair finder, optional native
    remaining-state selection, FastJets, and visible-complement recoil. Shared
    identity checks and explicit references prevent graph/scope substitution.
    """
    recipe=deepcopy(recipe);jets._keys(recipe,('schema_version','kind','particles','dileptons','jets','missing_momentum',*(['event_shapes'] if 'event_shapes' in recipe else []),*(['response'] if 'response' in recipe else [])))
    if type(recipe['schema_version'])is not int or recipe['schema_version']!=1 or recipe['kind']!='native-rivet-event-components':
        raise ValueError('native-rivet-event-components/v1 required')
    stages=[recipe['dileptons'],recipe['jets'],recipe['missing_momentum']]
    if any(type(stage)is not list or len(stage)>16 for stage in stages):raise ValueError('bounded stage lists required')
    if recipe['particles'] is None and not any(stages) and 'event_shapes' not in recipe and 'response' not in recipe:raise ValueError('nonempty native construction pipeline required')
    headers=[];init=[];analyze=[];semantics=[];known=set();symbols=set();names=set();obligations=[]
    def symbol(value):
        value=_id(value)
        if value in symbols:raise ValueError('distinct native locals required across all stages')
        symbols.add(value);return value
    def name(value):
        value=jets._native_name(value)
        if value in names:raise ValueError('distinct declared projection names required')
        names.add(value);return value
    def ref(value):
        if type(value)is not str or value not in known:raise ValueError('input must reference a prior native FinalState projection')
        return value
    p=None
    if recipe['particles'] is not None:
        p=particles.compile_component(recipe['particles']);headers+=p['headers'];init.append(p['init']);analyze.append(p['analyze']);obligations+=p['remaining_obligations']
        for node in p['recipe']['nodes']:
            symbol(node['id'])
            if particles.is_final_state(node['kind']):known.add(node['id'])
            if node['projection_name'] is not None:name(node['projection_name'])
            if node['output'] is not None:symbol(node['output']['id'])
    for pair in recipe['dileptons']:
        jets._keys(pair,('id','projection_name','input','mass_target','radius','lepton_selection','pair_cuts','dressing','outputs','remaining'))
        identity=symbol(pair['id']);projection=name(pair['projection_name'])
        target=pair['mass_target'];jets._keys(target,('value','unit'))
        if target['unit']!='GeV':raise ValueError('explicit target mass in GeV required')
        mass=jets._number(target['value']);radius=jets._number(pair['radius'])
        if pair['dressing']!='cone' or radius>10:raise ValueError('only explicit native CONE dressing with0<=radius<=10 is lowered')
        selection=pair['lepton_selection'];jets._keys(selection,('cuts','pids'))
        lepcut=particles._cut(selection['cuts'],selection['pids']);llcut=_pair_cuts(pair['pair_cuts'])
        inp=pair['input']
        if type(inp)is not dict or inp.get('kind')not in ('native_origins','final_state','two_final_states'):raise ValueError('explicit native constructor/input required')
        args=[]
        if inp['kind']=='native_origins':
            jets._keys(inp,('kind','leptons','photons','tau_decays','muon_decays'))
            if any(type(inp[k])is not str for k in ('leptons','photons','tau_decays','muon_decays')) or inp['leptons']not in ORIGINS or inp['photons']not in PHOTONS or any(inp[k]not in particles.DECAYS for k in ('tau_decays','muon_decays')):
                raise ValueError('explicit supported native lepton/photon/decay origins required')
            args=[f'{repr(mass)}*GeV',repr(radius),lepcut,llcut,
                'LeptonOrigin::'+ORIGINS[inp['leptons']], 'PhotonOrigin::'+PHOTONS[inp['photons']],
                'TauDecaysAs::'+particles.DECAYS[inp['tau_decays']], 'MuDecaysAs::'+particles.DECAYS[inp['muon_decays']],'DressingType::CONE']
        elif inp['kind']=='final_state':
            jets._keys(inp,('kind','id'));args=[ref(inp['id']),f'{repr(mass)}*GeV',repr(radius),lepcut,llcut,'DressingType::CONE']
        else:
            jets._keys(inp,('kind','leptons','photons'));args=[ref(inp['leptons']),ref(inp['photons']),f'{repr(mass)}*GeV',repr(radius),lepcut,llcut,'DressingType::CONE']
        init += [f'const DileptonFinder {identity}({", ".join(args)});',f'declare({identity}, "{projection}");'];known.add(identity)
        outputs=pair['outputs']
        if type(outputs)is not list or len(outputs)>3:raise ValueError('bounded explicit pair outputs required')
        for output in outputs:
            jets._keys(output,('id','access'));out=symbol(output['id'])
            if output['access']not in ('bosons','leptons','raw_particles'):raise ValueError('safe complete pair collection required; no unchecked single boson access')
            method={'bosons':'bosons','leptons':'leptons','raw_particles':'rawParticles'}[output['access']]
            analyze.append(f'const Particles {out} = apply<DileptonFinder>(event, "{projection}").{method}();')
        remaining=pair['remaining']
        if remaining is not None:
            jets._keys(remaining,('id','projection_name','selection'));rem=symbol(remaining['id'])
            if remaining['selection']not in ('all','charged','visible'):raise ValueError('explicit native remaining-state selection required')
            cls={'all':'VetoedFinalState','charged':'ChargedFinalState','visible':'VisibleFinalState'}[remaining['selection']]
            init.append(f'const {cls} {rem}({identity}.remainingFinalState());');known.add(rem)
            if remaining['projection_name'] is not None:
                init.append(f'declare({rem}, "{name(remaining["projection_name"])}");')
            headers.append('Rivet/Projections/'+cls+'.hh')
        semantics.append({'kind':'dilepton','id':identity,'input':deepcopy(inp),'lepton_selection':deepcopy(selection),'pair_cuts':deepcopy(pair['pair_cuts']),
          'selection':'native_closest_mass_OSSF_per_flavor_then_across_flavors_before_pair_cuts_no_fallback_after_rejection',
          'boson_pid':23,'max_bosons':1,'constituent_order':'positive_charge_then_negative_charge_native_dressed_constituents',
          'remaining_scope':'native_default_whole_FinalState_veto_selected_boson_raw_constituents_not_lepton_input_scope',
          'dressing':'native_CONE_assignment_and_cut_phases','remaining':deepcopy(remaining)})
        headers += ['Rivet/Projections/DileptonFinder.hh']
    for c in recipe['jets']:
        jets._keys(c,('id','projection_name','input','clustering','jet_cuts','output'))
        identity=symbol(c['id']);projection=name(c['projection_name']);inp=c['input'];jets._keys(inp,('kind','id'))
        if inp['kind']!='projection':raise ValueError('jet input requires exact native projection reference')
        parent=ref(inp['id']);symbol(identity+'_fs');symbol(identity+'_finder')
        output=c['output']
        if output is None:
            if c['jet_cuts']!=[]:raise ValueError('null jet output requires empty jet_cuts; no generated collection consumes them')
            out=identity+'_collection';symbol(out)
        else:out=symbol(output)
        lower=deepcopy(c);lower['input']={'kind':'stable_final_state','cuts':[],'projection_name':None};lower['output']=out
        j=jets.compile_component({'schema_version':1,'kind':'native-rivet-jet-components','components':[lower]})
        standalone=f'const FinalState {identity}_fs(Cuts::OPEN);\n';needle=f'const FastJets {identity}_finder({identity}_fs,'
        if j['init'].count(standalone)!=1 or j['init'].count(needle)!=1:raise ValueError('native jet compiler output shape differs')
        init.append(j['init'].replace(standalone,'',1).replace(needle,f'const FastJets {identity}_finder({parent},',1));headers+=j['headers'];obligations+=j['remaining_obligations']
        if output is not None:analyze.append(j['analyze'])
        semantics.append({'kind':'jets','id':identity,'input':deepcopy(inp),'clustering':deepcopy(c['clustering']),'jet_cuts':deepcopy(c['jet_cuts']),'output':output,
          'cut_phase':'after_native_clustering_before_native_pT_sort','equal_pT_order':'native_unspecified'})
    for met in recipe['missing_momentum']:
        jets._keys(met,('id','projection_name','input','outputs'));identity=symbol(met['id']);projection=name(met['projection_name']);parent=ref(met['input'])
        init += [f'const MissingMomentum {identity}({parent});',f'declare({identity}, "{projection}");'];headers.append('Rivet/Projections/MissingMomentum.hh')
        outputs=met['outputs']
        if type(outputs)is not list or len(outputs)>8:raise ValueError('bounded explicit recoil outputs required')
        for output in outputs:
            jets._keys(output,('id','quantity','unit'));out=symbol(output['id']);quantity=output['quantity']
            if type(quantity)is not str or quantity not in MET_METHODS or output['unit']!='GeV':raise ValueError('explicit native momentum/energy quantity in GeV required')
            cls,method,_=MET_METHODS[quantity]
            analyze.append(f'const {cls} {out} = apply<MissingMomentum>(event, "{projection}").{method}()/GeV;')
        semantics.append({'kind':'missing_momentum','id':identity,'input':met['input'],'outputs':deepcopy(outputs),
          'scope':'native_VisibleFinalState_of_declared_input_not_sum_of_hard_objects_or_prompt_neutrinos',
          'direction':'missing_vectors_are_negative_visible_vector_sums',
          'momentum_energy_distinction':'pT_and_Et_sums_remain_distinct_for_massive_particles',
          'four_momentum_access':'not_lowered_no_energy_conservation_mass_inference','response':'generator_particle_visibility_not_detector_MET'})
    response_result=None
    if 'response' in recipe:
        from . import rivet_response_component as response
        particle_inputs={n['id']:n['id']for n in p['recipe']['nodes']if particles.is_particle_finder(n['kind'])}if p else{}
        particle_inputs.update({q['id']:q['id']for q in recipe['dileptons']})
        particle_inputs.update({q['remaining']['id']:q['remaining']['id']for q in recipe['dileptons']if q['remaining']is not None})
        response_result=response.compile_component(recipe['response'],particle_inputs=particle_inputs,
            jet_inputs={q['id']:q['id']+'_finder'for q in recipe['jets']},
            met_inputs={q['id']:q['id']for q in recipe['missing_momentum']},reserved=symbols,projection_names=names,source_units=source_units)
        symbols.update(response_result['local_symbols']);names.update(response_result['projection_names'])
        headers+=response_result['headers'];init.append(response_result['init']);analyze.append(response_result['analyze'])
        obligations+=response_result['remaining_obligations'];semantics+=response_result['response_semantics']
    shape_result=None
    if 'event_shapes' in recipe:
        from . import rivet_shape_component as shapes
        collections={}
        if symbols & shapes.RESERVED:raise ValueError('pipeline local shadows native event-shape type')
        if p:
            for node in p['recipe']['nodes']:
                output=node['output']
                if output is not None and output['access'] not in ('dressed_leptons','particle_pairs','projection','n_stable','decay_products'):
                    collections[output['id']]='particles'
        for pair in recipe['dileptons']:
            for output in pair['outputs']:collections[output['id']]='particles'
        for jet in recipe['jets']:
            if jet['output'] is not None:collections[jet['output']]='jets'
        if response_result:collections.update(response_result['collections'])
        shape_result=shapes.compile_component(recipe['event_shapes'],final_states=known,collections=collections,reserved=symbols,projection_names=names)
        headers+=shape_result['headers'];init.append(shape_result['init']);analyze.append(shape_result['analyze']);obligations+=shape_result['remaining_obligations']
        semantics+=shape_result['shape_semantics']
    result={'schema_version':1,'kind':'native-rivet-event-component-source','recipe':recipe,'recipe_sha256':jets._digest(recipe),
      'headers':list(dict.fromkeys(headers)),'init':'\n'.join(x for x in init if x),'analyze':'\n'.join(x for x in analyze if x),
      'particle_semantics':p['nodes'] if p else [],'event_semantics':semantics,'weights':'enclosing_native_routine_unchanged_no_weight_arithmetic',
      'native_executed':False,'physics_validated':False,'remaining_obligations':list(dict.fromkeys(obligations+[
       'exact_Rivet_API_constructor_alias_and_native_build_load_registration',
       'native_dilepton_closest_mass_flavor_charge_tie_dressing_and_pair_cut_order',
       'native_remaining_whole_event_raw_constituent_veto_scope',
       'native_visible_momentum_versus_transverse_energy_and_acceptance_witnesses',
       'complete_enclosing_source_named_weights_all_final_RAW_outputs_flows_counters_normalization',
       'generator_shower_detector_classifier_assets_and_source_statistical_applicability']))}
    if response_result:result['response_source_dependencies']=response_result['source_dependencies'];result['response_api']=response_result['recipe']['native_api']
    return result


def instantiate(source,*,expected_sha256,recipe,source_units=None):
    """Three explicit whole-source slots; arbitrary source parsing is unserved."""
    if type(source)is not bytes or not 0<len(source)<=jets.MAX_SOURCE_BYTES or hashlib.sha256(source).hexdigest()!=expected_sha256:
        raise ValueError('bounded exact digest-bound source template required')
    text=source.decode('utf-8');component=compile_component(recipe,source_units=source_units)
    if 'event_shapes' in recipe:
        from . import rivet_shape_component as shapes
        shapes.validate_source_bindings(source,recipe['event_shapes'],init_slot='// RAVEL_EVENT_INIT',analyze_slot='// RAVEL_EVENT_ANALYZE')
    replacements={'// RAVEL_EVENT_HEADERS':'\n'.join('#include "'+h+'"'for h in component['headers']),
      '// RAVEL_EVENT_INIT':component['init'],'// RAVEL_EVENT_ANALYZE':component['analyze']}
    lines=text.splitlines(keepends=True)
    for slot in replacements:
        if text.count(slot)!=1 or sum(line.strip()==slot for line in lines)!=1:raise ValueError('three unique whole-line event component slots required')
    result=[]
    for line in lines:
        slot=line.strip()
        if slot in replacements:
            indent=line[:len(line)-len(line.lstrip())];end='\r\n'if line.endswith('\r\n')else'\n'
            result.extend(indent+part+end for part in replacements[slot].splitlines())
        else:result.append(line)
    raw=''.join(result).encode('utf-8')
    if len(raw)>jets.MAX_SOURCE_BYTES:raise ValueError('generated source exceeds budget')
    return {'source':raw,'source_sha256':hashlib.sha256(raw).hexdigest(),'original_template_sha256':expected_sha256,
      'component':component,'source_capsule_dependency_review':'incomplete_requires_fresh_native_admission'}


def source_capsule(original,*,compile_unit,source,root,component=None):
    """Use the existing normal capsule lifecycle; no native review carried."""
    if component is not None:
        from . import rivet_response_component as response
        original=response.validate_capsule_sources(original,component)
    return connected.source_capsule(original,compile_unit=compile_unit,source=source,root=root)
