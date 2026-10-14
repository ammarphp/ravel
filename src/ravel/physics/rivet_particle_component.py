"""Typed native particle-projection construction, preserving Rivet semantics.

No particles, momenta, ancestry or weights are calculated in Python. This source
compiler complements FastJets construction through an explicit projection DAG.
The enclosing routine retains its booking, selections and finalization.
"""
from copy import deepcopy
import hashlib
import math
from . import rivet_jet_component as jets

CLASSES={'stable':'FinalState','identified':'IdentifiedFinalState','prompt':'PromptFinalState',
         'dressed':'LeptonFinder','vetoed':'VetoedFinalState','charged':'ChargedFinalState','visible':'VisibleFinalState','unstable':'UnstableParticles',
         'invisible':'InvisibleFinalState','charged_leptons':'ChargedLeptons',
         'leading':'LeadingParticlesFinalState','invariant_mass':'InvMassFinalState','merged':'MergedFinalState','partonic_tops':'PartonicTops','heavy_hadrons':'HeavyHadrons','primary_particles':'PrimaryParticles','alice_primary_particles':'ALICE::PrimaryParticles','decayed_particles':'DecayedParticles'}
# Preserve legacy recipe include bytes; add the new native header only when used.
EXTENSIONS={'unstable','invisible','charged_leptons','leading','invariant_mass','merged','partonic_tops','heavy_hadrons','primary_particles','alice_primary_particles','decayed_particles'}
EXTENSION_HEADERS={'alice_primary_particles':'Rivet/Projections/AliceCommon.hh'}
HEADERS=['Rivet/Projections/'+name+'.hh' for kind,name in CLASSES.items() if kind not in EXTENSIONS]
DECAYS={'prompt':'PROMPT','nonprompt':'NONPROMPT'}
TOP_DECAYS={'all':'ALL','electron':'ELECTRON','muon':'MUON','tau':'TAU','e_mu':'E_MU','e_mu_tau':'E_MU_TAU','hadronic':'HADRONIC'}
TOP_TYPES={'TopDecay','WhichTop','PromptEMuFromTau','InclHadronicTau'}


def is_final_state(kind):
    """Native base-type boundary; ParticleFinder alone is not FinalState."""
    return kind in CLASSES and kind not in ('partonic_tops','primary_particles','alice_primary_particles','decayed_particles')


def is_particle_finder(kind):
    """A native Projection with structured decay tables is not ParticleFinder."""
    return kind in CLASSES and kind!='decayed_particles'


def _identifier(value):
    value=jets._identifier(value)
    if value in set(CLASSES.values()) | TOP_TYPES | {'ALICE','PrimaryParticles','DressingType','TauDecaysAs','MuDecaysAs','OnlyDirect','OnlyPrompt','PdgId','Particle','Particles','DressedLeptons','UnstableFinalState'}:
        raise ValueError('native type identity cannot be a local')
    return value


def _pid_selection(selection):
    jets._keys(selection,('matching','values'))
    if selection['matching'] not in ('signed','absolute'):
        raise ValueError('explicit signed or absolute PID identity required')
    values=selection['values']
    if (type(values)is not list or not 1<=len(values)<=16
            or any(type(v)is not int or not 0<abs(v)<=1_000_000_000
                   or (selection['matching']=='absolute' and v<0)for v in values) or len(set(values))!=len(values)):
        raise ValueError('bounded distinct exact nonzero PID identities required')
    return selection['matching'],values


def _signed_number(value):
    if type(value) not in (int,float):
        raise ValueError('finite exact binary64 literal required')
    try:number=float(value)
    except (ValueError,OverflowError) as exc:
        raise ValueError('representable binary64 literal required') from exc
    if not math.isfinite(number) or (type(value)is int and int(number)!=value):
        raise ValueError('finite exact binary64 literal required')
    return number


PARTICLE_FIELDS={**jets.FIELDS,'signed_eta':('eta','1'),
    'signed_rapidity':('rap','1'),'charge':('charge','1'),'abs_charge':('abscharge','1')}
PARTICLE_RELATIONS={**jets.RELATIONS,'eq':'==','ne':'!='}


def _particle_cuts(cuts):
    """Native Cut emission only, with original legacy predicate bytes preserved.

    Ranges call native Cuts::range (lower inclusive, upper exclusive). Charge
    uses Particle::charge/abscharge, never the distinct charge3 quantities.
    """
    if type(cuts)is not list or len(cuts)>8:
        raise ValueError('at most eight conjunctive particle cuts required')
    result=[];seen=set()
    for cut in cuts:
        jets._keys(cut,('field','relation','value','unit'))
        field,relation=cut['field'],cut['relation']
        if (type(field)is not str or field not in PARTICLE_FIELDS
                or type(relation)is not str or relation not in (*PARTICLE_RELATIONS,'native_range')
                or cut['unit']!=PARTICLE_FIELDS[field][1]):
            raise ValueError('explicit supported particle observable/relation/unit required')
        if (field,relation)in seen:raise ValueError('duplicate cut predicate')
        seen.add((field,relation))
        signed=field in ('signed_eta','signed_rapidity','charge')
        number=_signed_number if signed else jets._number
        qty=PARTICLE_FIELDS[field][0];unit='*GeV'if field=='pt'else''
        if relation=='native_range':
            jets._keys(cut['value'],('low','high'))
            low=number(cut['value']['low']);high=number(cut['value']['high'])
            if low>high:raise ValueError('ordered native range endpoints required')
            result.append(f'Cuts::range(Cuts::{qty}, {repr(low)}{unit}, {repr(high)}{unit})')
        else:
            value=repr(number(cut['value']))+unit
            result.append(f'(Cuts::{qty} {PARTICLE_RELATIONS[relation]} {value})')
    return ' && '.join(result)if result else'Cuts::OPEN'


def _primary_pids(values):
    # Native isPrimaryPID compares abs(record PID) to the ordered int roster.
    # Empty means no accepted species; negatives cannot match and are refused.
    if (type(values)is not list or len(values)>128
            or any(type(v)is not int or not 0<v<=2147483647 for v in values)
            or len(set(values))!=len(values)):
        raise ValueError('bounded distinct ordered positive native int PID roster required')
    return values


def _cut(cuts,pids=None):
    result=_particle_cuts(cuts)
    if pids is not None:
        matching,values=_pid_selection(pids)
        field='pid' if matching=='signed' else 'abspid'
        pid='('+' || '.join(f'(Cuts::{field} == {v})'for v in values)+')'
        result=pid if result=='Cuts::OPEN'else '('+result+') && '+pid
    return result


def compile_component(recipe):
    """Emit native projection init and explicit optional collection access.

    Promptness uses the native ancestry predicate, with both decay treatments
    explicit. Dressing supports only the native two-FinalState CONE constructor
    (leptons first, photons second); cone=0 disables capture. Dressed cuts occur
    after native photon association. Vetoes use native raw constituent identity.
    """
    recipe=deepcopy(recipe);jets._keys(recipe,('schema_version','kind','nodes'))
    if type(recipe['schema_version'])is not int or recipe['schema_version']!=1 or recipe['kind']!='native-rivet-particle-components':
        raise ValueError('native-rivet-particle-components/v1 required')
    if type(recipe['nodes'])is not list or not 1<=len(recipe['nodes'])<=32:
        raise ValueError('one to32 bounded topological nodes required')
    known={};locals_=set();names=set();init=[];analyze=[];semantics=[]
    invisible_policy=None;mass_policies={}
    for node in recipe['nodes']:
        if type(node)is not dict or type(node.get('kind'))is not str or node.get('kind')not in CLASSES:
            raise ValueError('closed native projection kind required')
        kind=node['kind'];extra={'stable':('cuts','pids'),'unstable':('cuts','pids'),'identified':('input','pids'),
            'prompt':('input','tau_decays','muon_decays'),'dressed':('leptons','photons','radius','dressing','cuts'),
            'charged':('input',),'visible':('input',),'vetoed':('input','veto_projections','veto_pids'),
            'invisible':('prompt_only','tau_decays','muon_decays'), 'charged_leptons':('input',),
            'leading':('input','pids','leading_only','empty_policy'),
            'invariant_mass':('input','pid_pairs','mass_window','target_mass','mass_measure'),
            'merged':('first','second'),
            'partonic_tops':('cuts','decay_mode','emu_from_prompt_tau','include_hadronic_taus','which_top','record_scope'),
            'heavy_hadrons':('cuts',),
            'primary_particles':('cuts','pids','record_scope'),
            'alice_primary_particles':('cuts','record_scope'),
            'decayed_particles':('input','stable_pids','record_scope')}[kind]
        jets._keys(node,('id','kind','projection_name','output',*extra))
        identity=_identifier(node['id'])
        if identity in locals_:raise ValueError('distinct C++ locals required')
        locals_.add(identity)
        name=node['projection_name']
        if name is not None:
            jets._native_name(name)
            if name in names:raise ValueError('distinct native projection names required')
            names.add(name)
        def ref(key):
            value=node[key]
            if type(value)is not str or value not in known or not is_final_state(known[value]):
                raise ValueError('input must reference a prior native FinalState node')
            return value
        details={'id':identity,'kind':kind,'projection_name':name,'native_class':CLASSES[kind]}
        if kind in ('stable','unstable'):
            init.append(f'const {CLASSES[kind]} {identity}({_cut(node["cuts"],node["pids"])});')
            details['cut_phase']=('stable_final_state_particles' if kind=='stable' else 'after_native_record_status_parton_and_same_signed_child_filter')
            if kind=='unstable':
                details.update(native_record_selection={
                    'statuses':[1,2], 'status2_abs_pid_veto':[22,110,990,9990],
                    'all_partons_excluded':True, 'beam_status4_excluded':True,
                    'duplicate_suppression':'direct_child_same_signed_PDG_and_child_status2',
                    'stable_status1_included_subject_to_parton_and_duplicate_filters':True},
                    ancestry='native_generator_record_not_reconstructed_decay_or_detector_response')
        elif kind in ('primary_particles','alice_primary_particles'):
            if node['record_scope']!='native_generator_record':
                raise ValueError('explicit native generator-record primary-particle scope required')
            cut=_cut(node['cuts'])
            if kind=='primary_particles':
                pids=_primary_pids(node['pids'])
                init.append(f'const PrimaryParticles {identity}({{{", ".join(map(str,pids))}}}, {cut});')
                details['pid_selection']='absolute_record_PID_matches_literal_positive_ordered_roster'
                details['ordered_pid_roster']=pids
                details['cache_comparison']='native_cut_and_ordered_PID_roster_not_sorted_or_species_only'
            else:
                init.append(f'const ALICE::PrimaryParticles {identity}({cut});')
                details['pid_selection']='unchanged_native_ALICE_species_switch_and_abs_PID_above_1000000000'
                details['cache_comparison']='native_ALICE_equal_cut_mkPCmp_named_PrimaryParticles_requires_fresh_enclosing_cache_qualification'
            details.update(native_base='ParticleFinder_not_FinalState',
                cut_phase='after_native_primary_classification',
                ignored_status='status0_or_native_inRange_status_11_200',
                ancestry='native_first_parent_only_skipping_ignored_records_not_all_ancestors',
                ancestor_decision_order='beam_status3_or4_accept_then_primary_PID_reject_then_non_status2_reject',
                no_ancestor='native_accept_after_target_status_and_PID_checks',
                target_status='not_restricted_to_stable_status1',
                applicability='generator_record_primary_definition_not_prompt_lepton_or_detector_primary_track')
        elif kind=='decayed_particles':
            parent=node['input'];stable=node['stable_pids']
            if type(parent)is not str or parent not in known or not is_particle_finder(known[parent]):
                raise ValueError('decay input must reference a prior native ParticleFinder node')
            if node['record_scope']!='native_generator_record':
                raise ValueError('explicit native generator-record decay scope required')
            if (type(stable)is not list or len(stable)>128
                    or any(type(v)is not int or not -2147483648<=v<=2147483647 or v==0 for v in stable)
                    or len(set(stable))!=len(stable)):
                raise ValueError('bounded distinct exact signed native int stable-stop PID roster required')
            init.append(f'DecayedParticles {identity}({parent});')
            for pid in stable:init.append(f'{identity}.addStable({pid});')
            details.update(native_base='Projection_not_ParticleFinder_or_FinalState',
                input='native_ParticleFinder_particlesByPt_before_direct_child_multiplicity_gate',
                mother_gate='native_children_size_greater_than_one_no_status_or_decay_probability_inference',
                recursion='native_direct_children_depth_first_until_leaf_or_exact_signed_stable_stop_PID',
                stable_stop_pids=stable,
                terminal_counts='every_native_terminal_product_counted_even_unspecified_species_no_hidden_photon_drop',
                table_alignment='decaying_nStable_decayProducts_same_filtered_sorted_mother_index',
                product_identity='signed_PID_map_to_complete_native_Particles_vectors_not_absolute_or_charge_inferred',
                mode_matching='unchanged_enclosing_native_total_nStable_and_each_requested_signed_PID_multiplicity_no_automatic_CC_or_extra_key_certification',
                cache_comparison='native_parent_projection_and_stable_signed_PID_set',
                applicability='native_generator_decay_history_not_detector_decay_efficiency_branching_fraction_or_lifetime_response')
        elif kind=='partonic_tops':
            if (type(node['decay_mode'])is not str or node['decay_mode']not in TOP_DECAYS
                    or any(type(node[k])is not bool for k in ('emu_from_prompt_tau','include_hadronic_taus'))
                    or type(node['which_top'])is not str or node['which_top']not in ('first','last')
                    or node['record_scope']!='native_generator_record'):
                raise ValueError('explicit native top decay, tau flags, first/last copy and generator-record scope required')
            init.append(f'const PartonicTops {identity}(TopDecay::{TOP_DECAYS[node["decay_mode"]]}, PromptEMuFromTau::{"YES"if node["emu_from_prompt_tau"]else"NO"}, InclHadronicTau::{"YES"if node["include_hadronic_taus"]else"NO"}, {_cut(node["cuts"])}, WhichTop::{node["which_top"].upper()});')
            details.update(native_base='ParticleFinder_not_FinalState',
                input_scope='native_all_event_record_particles_cut_before_first_last_top_predicate',
                copy_selection='native_isFirstWith_isLastWith_isTop_not_status_or_final_state_selection',
                decay_selection='native_allDescendants_prompt_leptons_photon_ancestor_exclusion_not_explicit_W_reconstruction',
                tau_policy='native_prompt_tau_with_no_direct_charged_lepton_children_defines_hadronic_tau',
                negative_energy_or_mass='native_rejection_after_copy_and_decay_selection',
                applicability='native_record_top_existence_kinematics_lab_frame_not_guaranteed_not_fiducial_pseudotop',
                flags={k:node[k]for k in ('decay_mode','emu_from_prompt_tau','include_hadronic_taus','which_top')})
        elif kind=='heavy_hadrons':
            init.append(f'const HeavyHadrons {identity}({_cut(node["cuts"])});')
            details.update(native_base='FinalState',
                cut_phase='native_UnstableParticles_cut_before_heavy_flavor_and_direct_child_filter',
                selection='native_isHadron_and_hasBottom_or_hasCharm',
                terminal_copy='native_direct_genParticle_children_flavor_content_not_all_descendants_or_same_PID',
                child_filter='PID_hasBottom_or_hasCharm_no_child_hadron_status_or_kinematic_filter',
                unbound_or_undecayed='native_includes_no_genParticle_or_no_end_vertex_subject_to_parent_UFS',
                flavor_partition='bottom_priority_charm_only_if_no_bottom_Bc_in_bottom_only',
                charm_from_bottom='not_ancestry_vetoed',
                applicability='native_generator_decay_history_not_detector_btag_or_charm_efficiency')
        elif kind=='identified':
            parent=ref('input');matching,values=_pid_selection(node['pids'])
            init.append(f'IdentifiedFinalState {identity}({parent});')
            method='acceptIds'if matching=='signed'else'acceptIdPairs'
            init.append(f'{identity}.{method}({{{", ".join(map(str,values))}}});')
            details['pid_identity']='literal_'+matching+'_PDG'
        elif kind in ('charged','visible'):
            parent=ref('input')
            init.append(f'const {CLASSES[kind]} {identity}({parent});')
            details['selection']=('native_isCharged_nonzero_charge' if kind=='charged' else 'native_Particle_isVisible')
            details['response']='generator_particle_property_not_detector_efficiency'
        elif kind=='prompt':
            parent=ref('input')
            if any(type(node[k])is not str or node[k]not in DECAYS for k in ('tau_decays','muon_decays')):
                raise ValueError('explicit native tau and muon decay-promptness treatments required')
            init.append(f'const PromptFinalState {identity}({parent}, TauDecaysAs::{DECAYS[node["tau_decays"]]}, MuDecaysAs::{DECAYS[node["muon_decays"]]});')
            details['promptness']='native_isPrompt_ancestry_not_detector_displacement'
            details['decay_treatment']={k:node[k]for k in ('tau_decays','muon_decays')}
        elif kind=='invisible':
            if type(node['prompt_only'])is not bool or any(type(node[k])is not str or node[k]not in DECAYS for k in ('tau_decays','muon_decays')):
                raise ValueError('explicit native invisible promptness and tau/muon decay treatments required')
            policy=(node['prompt_only'],node['tau_decays'],node['muon_decays'])
            # Inspected Rivet4.1.4 compare() checks FS alone, not these flags.
            # Distinct names do not prevent ProjectionHandler equivalence.
            if invisible_policy is not None and invisible_policy!=policy:
                raise ValueError('native invisible cache comparison omits policy; conflicting policies cannot share one recipe')
            invisible_policy=policy
            init.append(f'const InvisibleFinalState {identity}(OnlyDirect::{"YES"if node["prompt_only"]else"NO"}, TauDecaysAs::{DECAYS[node["tau_decays"]]}, MuDecaysAs::{DECAYS[node["muon_decays"]]});')
            details.update(input_scope='native_default_whole_FinalState_no_supplied_acceptance_filter',
                visibility='native_not_Particle_isVisible_includes_all_native_invisible_species_not_neutrinos_only',
                promptness='native_isDirect_tau_muon_flags_only_if_prompt_only',
                detector_response='not_detector_MET_or_efficiency',cache_policy='one_identical_policy_per_recipe')
        elif kind=='charged_leptons':
            parent=ref('input');init.append(f'const ChargedLeptons {identity}({parent});')
            details.update(selection='native_ChargedFinalState_then_PID_isChargedLepton',
                tau_scope='stable_charged_taus_remain_if_present_in_parent_not_tau_reconstruction',
                sorting='native_pT_sorted_collection_equal_pT_order_not_redefined')
        elif kind=='leading':
            parent=ref('input');matching,values=_pid_selection(node['pids'])
            if type(node['leading_only'])is not bool or node['empty_policy']!=('native_default_particle'if node['leading_only']else'empty_collection'):
                raise ValueError('explicit native leading mode and its empty-input policy required')
            init.append(f'LeadingParticlesFinalState {identity}({parent});')
            method='addParticleId'if matching=='signed'else'addParticleIdPair'
            for value in values:init.append(f'{identity}.{method}({value});')
            init.append(f'{identity}.setLeadingOnly({"true"if node["leading_only"]else"false"});')
            details.update(pid_identity='literal_'+matching+'_PDG',
                selection='native_highest_pT_per_signed_PID_then_optional_global_leader',
                tie_rule='strict_greater_pT_retains_first_input_per_PID_global_tie_uses_signed_PID_map_order',
                ordering='signed_PID_map_order_before_explicit_particlesByPt',
                empty_policy=node['empty_policy'],
                global_zero_or_empty='native_default_Particle_if_no_selected_strictly_positive_pT_not_safe_single_particle_access')
        elif kind=='invariant_mass':
            parent=ref('input');pairs=node['pid_pairs']
            if type(pairs)is not list or not 1<=len(pairs)<=16 or any(type(pair)is not list or len(pair)!=2 or any(type(v)is not int or not 0<abs(v)<=1_000_000_000 for v in pair)or pair[0]==pair[1]for pair in pairs)or len({tuple(pair)for pair in pairs})!=len(pairs):
                raise ValueError('bounded distinct ordered signed PID pairs with unequal species required')
            window=node['mass_window'];jets._keys(window,('low','high','unit'))
            low=jets._number(window['low']);high=jets._number(window['high'])
            if window['unit']!='GeV' or low>=high:raise ValueError('ordered native GeV mass window required')
            target=node['target_mass']
            if target is None:mass=-1.0
            else:
                jets._keys(target,('value','unit'));mass=jets._number(target['value'])
                if target['unit']!='GeV' or mass<=0:raise ValueError('positive explicit GeV target mass or null all-pairs policy required')
            if type(node['mass_measure'])is not str or node['mass_measure']not in('invariant','transverse'):
                raise ValueError('explicit invariant or transverse mass-window measurement required')
            # Different local FS names may still compare equivalent natively.
            # Be conservative across all parents with these compare operands.
            cache_key=(tuple(tuple(pair)for pair in pairs),low,high,node['mass_measure'])
            if cache_key in mass_policies and mass_policies[cache_key]!=mass:
                raise ValueError('native invariant-mass cache comparison omits target; conflicting targets cannot share one recipe')
            mass_policies[cache_key]=mass
            values=', '.join('{'+str(a)+', '+str(b)+'}'for a,b in pairs)
            init.append(f'InvMassFinalState {identity}({parent}, std::vector<std::pair<PdgId, PdgId>>{{{values}}}, {repr(low)}*GeV, {repr(high)}*GeV, {repr(mass)}*GeV);')
            init.append(f'{identity}.useTransverseMass({"true"if node["mass_measure"]=="transverse"else"false"});')
            details.update(pid_identity='literal_ordered_signed_PDG_pairs_not_charge_inferred',
                window_measure=node['mass_measure'],window_operation='native_inRange_after_negative_full_mass2_rejection',
                pair_selection='all_passing_pairs'if target is None else'native_closest_full_invariant_mass_if_distance_below_1e30_native_units_else_passing_pairs',
                target_metric='full_invariant_mass_even_when_window_is_transverse',
                target_tie='strict_smaller_distance_keeps_native_first_pair',
                pair_multiplicity='native_ordered_species_bucket_iteration_retained_not_unique_PID_pair_deduplication',
                particle_deduplication='native_pointer_identity_among_selected_pair_constituents',
                cache_policy='same_pairs_window_measure_requires_identical_target_even_across_parent_aliases')
        elif kind=='merged':
            first=ref('first');second=ref('second')
            init.append(f'const MergedFinalState {identity}({first}, {second});')
            details.update(ordering='first_collection_then_second_not_present_in_first',
                duplicate_identity='native_genParticle_pointer_not_PID_or_momentum',
                duplicate_scope='second_against_first_only_not_deduplication_within_either_input',
                null_identity='native_equal_null_genParticle_behavior_retained')
        elif kind=='dressed':
            leptons=ref('leptons');photons=ref('photons');radius=jets._number(node['radius'])
            if node['dressing']!='cone' or radius>10:
                raise ValueError('only explicit native CONE dressing with0<=radius<=10 is lowered')
            init.append(f'const LeptonFinder {identity}({leptons}, {photons}, {repr(radius)}, {_cut(node["cuts"])}, DressingType::CONE);')
            details.update(constructor_order=['leptons','photons'],cut_phase='composite_momentum_after_native_dressing',
                photon_assignment='native_closest_charged_lepton_strict_dR_less_than_radius',
                equal_distance_assignment='native_bare_collection_order_not_redefined',radius=radius)
        else:
            parent=ref('input');vetoes=node['veto_projections']
            if type(vetoes)is not list or len(vetoes)>16 or any(type(v)is not str or v not in known or not is_particle_finder(known[v]) for v in vetoes)or len(set(vetoes))!=len(vetoes):
                raise ValueError('bounded distinct prior native ParticleFinder veto projections required')
            init.append(f'VetoedFinalState {identity}({parent});')
            for veto in vetoes:init.append(f'{identity}.vetoFinalState({veto});')
            if node['veto_pids']is not None:
                matching,values=_pid_selection(node['veto_pids']);method='addVetoId'if matching=='signed'else'addVetoPairId'
                for value in values:init.append(f'{identity}.{method}({value});')
            details['veto_identity']='native_rawParticles_genParticle_identity_not_geometric_overlap'
        if name is not None:init.append(f'declare({identity}, "{name}");')
        output=node['output']
        if output is not None:
            jets._keys(output,('id','access',*(['cuts'] if kind=='heavy_hadrons' else [])))
            out=_identifier(output['id'])
            if out in locals_ or name is None:raise ValueError('fresh output local and declared projection required')
            locals_.add(out)
            if kind=='decayed_particles':
                access=output['access']
                methods={'decaying':('Particles','decaying'),
                    'n_stable':('std::vector<unsigned int>','nStable'),
                    'decay_products':('std::vector<std::map<PdgId, Particles>>','decayProducts'),
                    'projection':('DecayedParticles',None)}
                if type(access)is not str or access not in methods:
                    raise ValueError('complete native decay table or projection access required; no unchecked singleton')
                typ,method=methods[access]
                call=f'apply<DecayedParticles>(event, "{name}")'
                if method is not None:call+=f'.{method}()'
                analyze.append(f'const {typ}& {out} = {call};')
                details.update(output_access=access,output_scope='complete_native_table_or_const_projection_no_relabelled_particles',sorting='native_parent_pT_order_after_mother_gate_alignment_preserved')
            else:
                access=output['access']
                if access not in ('particles','particles_by_pt','raw_particles','dressed_leptons','particle_pairs','tops','b_hadrons','c_hadrons')or(access=='tops'and kind!='partonic_tops')or(access in('b_hadrons','c_hadrons')and kind!='heavy_hadrons')or(access=='dressed_leptons'and kind!='dressed')or(access=='particle_pairs'and kind!='invariant_mass'):
                    raise ValueError('explicit compatible native collection access required')
                method={'particles':'particles','particles_by_pt':'particlesByPt','raw_particles':'rawParticles','dressed_leptons':'dressedLeptons','particle_pairs':'particlePairs','tops':'tops','b_hadrons':'bHadrons','c_hadrons':'cHadrons'}[access]
                typ='DressedLeptons'if access=='dressed_leptons'else'std::vector<std::pair<Particle, Particle>>'if access=='particle_pairs'else'Particles'
                args=''
                if kind=='heavy_hadrons':
                    if output['cuts'] is not None:
                        if access=='raw_particles':raise ValueError('rawParticles has no native Cut overload')
                        args=_cut(output['cuts'])
                    details['output_cut_phase']='after_native_heavy_hadron_selection_before_native_sort_if_requested'
                    details['output_cuts']=output['cuts']
                analyze.append(f'const {typ} {out} = apply<{CLASSES[kind]}>(event, "{name}").{method}({args});')
                details['output_access']=access
                details['sorting']='native_pT_equal_pT_order_unspecified'if access in('particles_by_pt','dressed_leptons')else'native_collection_order'
        known[identity]=kind;semantics.append(details)
    return {'schema_version':1,'kind':'native-rivet-particle-component-source','recipe':recipe,
      'recipe_sha256':jets._digest(recipe),'headers':HEADERS+[EXTENSION_HEADERS.get(k,'Rivet/Projections/'+CLASSES[k]+'.hh')for k in CLASSES if k in EXTENSIONS and any(n['kind']==k for n in recipe['nodes'])],'init':'\n'.join(init),'analyze':'\n'.join(analyze),
      'nodes':semantics,'weights':'enclosing_native_routine_unchanged_no_weight_arithmetic',
      'native_executed':False,'physics_validated':False,'remaining_obligations':[
        'fresh_Rivet_API_compile_registration_and_sole_loaded_binary',
        'event_ancestry_decay_and_stable_particle_source_applicability',
        'native_shared_photon_closest_tie_radius_and_post_dressing_cut_witness',
        'native_raw_constituent_identity_veto_and_null_genParticle_behavior',
        'whole_enclosing_routine_all_weights_booking_final_RAW_flows_and_normalization',
        'native_event_and_paper_response_statistical_validation']+([
        'native_unstable_status1_status2_veto_parton_last_signed_copy_and_decay_history_witness',
        'enclosing_ancestry_and_branching_ratio_beam_and_source_cross_section_applicability'] if any(n['kind']=='unstable' for n in recipe['nodes']) else [])+([
        'native_invisible_visibility_BSM_species_prompt_tau_muon_origin_whole_event_witness',
        'native_signed_leading_PID_ties_zero_empty_and_charged_stable_tau_witness',
        'native_mass_window_full_transverse_target_pointer_pair_and_projection_cache_witness',
        'native_merged_genParticle_identity_duplicates_and_null_identity_witness'] if any(n['kind'] in EXTENSIONS-{'unstable','partonic_tops','heavy_hadrons','primary_particles','alice_primary_particles','decayed_particles'} for n in recipe['nodes']) else [])+([
        'native_top_record_first_last_prompt_tau_photon_ancestor_negative_mass_witness',
        'native_heavy_direct_child_flavor_bottom_charm_partition_and_parent_cut_witness',
        'native_generator_history_and_physical_top_or_heavy_hadron_applicability_not_detector_tagging'] if any(n['kind'] in('partonic_tops','heavy_hadrons') for n in recipe['nodes']) else [])+([
        'native_primary_first_parent_ignored_record_beam_decay_species_and_post_classification_cut_witness',
        'ALICE_same_cut_named_subprojection_compare_and_generic_specialized_cache_registration_witness',
        'whole_cumulant_mixing_buffer_default_weight_and_primary_definition_physical_applicability'
        ] if any(n['kind'] in('primary_particles','alice_primary_particles') for n in recipe['nodes']) else [])+([
        'native_decay_signed_stop_roster_leaf_single_child_recursive_products_and_aligned_tables',
        'native_mode_total_species_multiplicity_conjugation_and_safe_enclosing_index_access',
        'whole_original_decay_observables_normalization_counters_branching_lifetime_and_all_weight_applicability'
        ] if any(n['kind']=='decayed_particles' for n in recipe['nodes']) else [])}


def instantiate(source,*,expected_sha256,recipe):
    """Fill explicit complete-source slots; arbitrary C++ translation is unserved."""
    if type(source)is not bytes or not 0<len(source)<=jets.MAX_SOURCE_BYTES or hashlib.sha256(source).hexdigest()!=expected_sha256:
        raise ValueError('bounded exact digest-bound source template required')
    text=source.decode('utf-8');component=compile_component(recipe)
    replacements={'// RAVEL_PARTICLE_HEADERS':'\n'.join('#include "'+h+'"'for h in component['headers']),
                  '// RAVEL_PARTICLE_INIT':component['init'],'// RAVEL_PARTICLE_ANALYZE':component['analyze']}
    lines=text.splitlines(keepends=True)
    for slot in replacements:
        if text.count(slot)!=1 or sum(line.strip()==slot for line in lines)!=1:
            raise ValueError('three unique whole-line particle component slots required')
    result=[]
    for line in lines:
        slot=line.strip()
        if slot in replacements:
            indent=line[:len(line)-len(line.lstrip())];ending='\r\n'if line.endswith('\r\n')else'\n'
            result.extend(indent+part+ending for part in replacements[slot].splitlines())
        else:result.append(line)
    raw=''.join(result).encode('utf-8')
    if len(raw)>jets.MAX_SOURCE_BYTES:raise ValueError('generated source exceeds budget')
    return {'source':raw,'source_sha256':hashlib.sha256(raw).hexdigest(),'original_template_sha256':expected_sha256,
      'component':component,'source_capsule_dependency_review':'incomplete_requires_fresh_native_admission'}
