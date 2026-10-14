"""Native Rivet detector-response source construction.

Rivet owns random draws, smearing functions, tags and MET. This compiler never
samples efficiencies, infers calibration or substitutes an idealized law.
"""
from copy import deepcopy
import hashlib
import re
from . import rivet_jet_component as jets
from . import rivet_particle_component as particles

API_VERSION='4.1.4'
CLASSES={'particles':'SmearedParticles','jets':'SmearedJets','met':'SmearedMET','tau':'TauFinder'}
TYPES={'particle_eff':'ParticleEffFn','particle_smear':'ParticleSmearFn','jet_eff':'JetEffFn',
       'jet_smear':'JetSmearFn','met_params':'METSmearParamsFn','met_smear':'METSmearFn'}
RESERVED=set(CLASSES.values())|set(TYPES.values())|{'TauDecay','LeptonOrigin','ParticleFinder','JetFinder','METFinder','ParticleEffSmearFn','JetEffSmearFn','METSmearParams','Vector3','Particles','Jets','Cuts','GeV'}
TAU_DECAYS={'all':'ANY','leptonic':'LEPTONIC','hadronic':'HADRONIC'}
TAU_ORIGINS={'all':'ANY','prompt':'NODECAY','decay':'DECAY'}
MAX_FUNCTIONS=64
MAX_NODES=32
MAX_EXPRESSION=16384
MAX_PROOF_BYTES=8000000
# Filled from released public headers: only literal unary/two-argument functions.
BUILTINS = {'ATLAS_JVT_EFF_LOOSE': 'jet_eff', 'ATLAS_JVT_EFF_MEDIUM': 'jet_eff', 'ATLAS_JVT_EFF_TIGHT': 'jet_eff', 'ELECTRON_EFF_ATLAS_RUN1_LOOSE': 'particle_eff', 'ELECTRON_EFF_ATLAS_RUN1_MEDIUM': 'particle_eff', 'ELECTRON_EFF_ATLAS_RUN1_TIGHT': 'particle_eff', 'ELECTRON_EFF_ATLAS_RUN2_LOOSE': 'particle_eff', 'ELECTRON_EFF_ATLAS_RUN2_MEDIUM': 'particle_eff', 'ELECTRON_EFF_ATLAS_RUN2_TIGHT': 'particle_eff', 'ELECTRON_EFF_CMS_RUN1': 'particle_eff', 'ELECTRON_EFF_CMS_RUN1_LOOSE': 'particle_eff', 'ELECTRON_EFF_CMS_RUN1_MEDIUM': 'particle_eff', 'ELECTRON_EFF_CMS_RUN1_TIGHT': 'particle_eff', 'ELECTRON_EFF_CMS_RUN2': 'particle_eff', 'ELECTRON_EFF_CMS_RUN2_LOOSE': 'particle_eff', 'ELECTRON_EFF_CMS_RUN2_MEDIUM': 'particle_eff', 'ELECTRON_EFF_CMS_RUN2_TIGHT': 'particle_eff', 'ELECTRON_EFF_IDENTITY_LOOSE': 'particle_eff', 'ELECTRON_EFF_IDENTITY_MEDIUM': 'particle_eff', 'ELECTRON_EFF_IDENTITY_TIGHT': 'particle_eff', 'ELECTRON_RECOEFF_ATLAS_RUN1': 'particle_eff', 'ELECTRON_RECOEFF_ATLAS_RUN2': 'particle_eff', 'ELECTRON_SMEAR_ATLAS_RUN1': 'particle_smear', 'ELECTRON_SMEAR_ATLAS_RUN2': 'particle_smear', 'ELECTRON_SMEAR_CMS_RUN1': 'particle_smear', 'ELECTRON_SMEAR_CMS_RUN2': 'particle_smear', 'ELECTRON_SMEAR_IDENTITY': 'particle_smear', 'JET_BTAG_ATLAS_RUN1': 'jet_eff', 'JET_BTAG_ATLAS_RUN1_XXX': 'jet_eff', 'JET_BTAG_ATLAS_RUN2_2016_MV2C10_77': 'jet_eff', 'JET_BTAG_ATLAS_RUN2_DL1d_77': 'jet_eff', 'JET_BTAG_ATLAS_RUN2_DL1r_77': 'jet_eff', 'JET_BTAG_ATLAS_RUN2_MV2C10': 'jet_eff', 'JET_BTAG_ATLAS_RUN2_MV2C20': 'jet_eff', 'JET_BTAG_IDENTITY': 'jet_eff', 'JET_BTAG_IDENTITY_IDENTITY': 'jet_eff', 'JET_BTAG_PERFECT': 'jet_eff', 'JET_CTAG_IDENTITY': 'jet_eff', 'JET_CTAG_PERFECT': 'jet_eff', 'JET_EFF_0': 'jet_eff', 'JET_EFF_1': 'jet_eff', 'JET_EFF_IDENTITY': 'jet_eff', 'JET_EFF_ONE': 'jet_eff', 'JET_EFF_PERFECT': 'jet_eff', 'JET_EFF_ZERO': 'jet_eff', 'JET_FN0': 'jet_eff', 'JET_FN1': 'jet_eff', 'JET_SMEAR_ATLAS_RUN1': 'jet_smear', 'JET_SMEAR_ATLAS_RUN2': 'jet_smear', 'JET_SMEAR_CMS_RUN1': 'jet_smear', 'JET_SMEAR_CMS_RUN2': 'jet_smear', 'JET_SMEAR_IDENTITY': 'jet_smear', 'JET_SMEAR_PERFECT': 'jet_smear', 'JET_TAUTAG_IDENTITY': 'jet_eff', 'JET_TAUTAG_PERFECT': 'jet_eff', 'MET_SMEARPARAMS_ATLAS_RUN1': 'met_params', 'MET_SMEARPARAMS_ATLAS_RUN2': 'met_params', 'MET_SMEARPARAMS_ATLAS_RUN2_PFLOW': 'met_params', 'MET_SMEARPARAMS_CMS_RUN1': 'met_params', 'MET_SMEARPARAMS_CMS_RUN2': 'met_params', 'MET_SMEARPARAMS_IDENTITY': 'met_params', 'MET_SMEAR_ATLAS_RUN1': 'met_smear', 'MET_SMEAR_ATLAS_RUN2': 'met_smear', 'MET_SMEAR_ATLAS_RUN2_PFLOW': 'met_smear', 'MET_SMEAR_CMS_RUN1': 'met_smear', 'MET_SMEAR_CMS_RUN2': 'met_smear', 'MET_SMEAR_IDENTITY': 'met_smear', 'MUON_EFF_ATLAS_RUN1': 'particle_eff', 'MUON_EFF_ATLAS_RUN1_LOOSE': 'particle_eff', 'MUON_EFF_ATLAS_RUN1_MEDIUM': 'particle_eff', 'MUON_EFF_ATLAS_RUN1_TIGHT': 'particle_eff', 'MUON_EFF_ATLAS_RUN2_LOOSE': 'particle_eff', 'MUON_EFF_ATLAS_RUN2_MEDIUM': 'particle_eff', 'MUON_EFF_ATLAS_RUN2_TIGHT': 'particle_eff', 'MUON_EFF_CMS_RUN1': 'particle_eff', 'MUON_EFF_CMS_RUN1_LOOSE': 'particle_eff', 'MUON_EFF_CMS_RUN1_MEDIUM': 'particle_eff', 'MUON_EFF_CMS_RUN1_TIGHT': 'particle_eff', 'MUON_EFF_CMS_RUN2': 'particle_eff', 'MUON_EFF_CMS_RUN2_LOOSE': 'particle_eff', 'MUON_EFF_CMS_RUN2_MEDIUM': 'particle_eff', 'MUON_EFF_CMS_RUN2_TIGHT': 'particle_eff', 'MUON_EFF_IDENTITY_LOOSE': 'particle_eff', 'MUON_EFF_IDENTITY_MEDIUM': 'particle_eff', 'MUON_EFF_IDENTITY_TIGHT': 'particle_eff', 'MUON_ISOEFF_ATLAS_RUN2_LOOSE': 'particle_eff', 'MUON_RECOEFF_ATLAS_RUN2': 'particle_eff', 'MUON_SMEAR_ATLAS_RUN1': 'particle_smear', 'MUON_SMEAR_ATLAS_RUN2': 'particle_smear', 'MUON_SMEAR_CMS_RUN1': 'particle_smear', 'MUON_SMEAR_CMS_RUN2': 'particle_smear', 'MUON_SMEAR_IDENTITY': 'particle_smear', 'P3_SMEAR_LEN_GAUSS': 'met_smear', 'PARTICLE_EFF_0': 'particle_eff', 'PARTICLE_EFF_1': 'particle_eff', 'PARTICLE_EFF_ONE': 'particle_eff', 'PARTICLE_EFF_PERFECT': 'particle_eff', 'PARTICLE_EFF_ZERO': 'particle_eff', 'PARTICLE_FN0': 'particle_eff', 'PARTICLE_FN1': 'particle_eff', 'PARTICLE_SMEAR_IDENTITY': 'particle_smear', 'PARTICLE_SMEAR_PERFECT': 'particle_smear', 'PHOTON_EFF_ATLAS_RUN1': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN1_LOOSE': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN1_MEDIUM': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN1_TIGHT': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN2': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN2_LOOSE': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN2_MEDIUM': 'particle_eff', 'PHOTON_EFF_ATLAS_RUN2_TIGHT': 'particle_eff', 'PHOTON_EFF_CMS_RUN1': 'particle_eff', 'PHOTON_EFF_CMS_RUN1_LOOSE': 'particle_eff', 'PHOTON_EFF_CMS_RUN1_MEDIUM': 'particle_eff', 'PHOTON_EFF_CMS_RUN1_TIGHT': 'particle_eff', 'PHOTON_EFF_CMS_RUN2': 'particle_eff', 'PHOTON_EFF_CMS_RUN2_LOOSE': 'particle_eff', 'PHOTON_EFF_CMS_RUN2_MEDIUM': 'particle_eff', 'PHOTON_EFF_CMS_RUN2_TIGHT': 'particle_eff', 'PHOTON_EFF_IDENTITY_LOOSE': 'particle_eff', 'PHOTON_EFF_IDENTITY_MEDIUM': 'particle_eff', 'PHOTON_EFF_IDENTITY_TIGHT': 'particle_eff', 'PHOTON_SMEAR_ATLAS_RUN1': 'particle_smear', 'PHOTON_SMEAR_ATLAS_RUN2': 'particle_smear', 'PHOTON_SMEAR_CMS_RUN1': 'particle_smear', 'PHOTON_SMEAR_CMS_RUN2': 'particle_smear', 'PHOTON_SMEAR_IDENTITY': 'particle_smear', 'TAUJET_EFF_ATLAS_RUN1': 'jet_eff', 'TAUJET_EFF_ATLAS_RUN2': 'jet_eff', 'TAU_EFF_ATLAS_RUN1': 'particle_eff', 'TAU_EFF_ATLAS_RUN1_LOOSE': 'particle_eff', 'TAU_EFF_ATLAS_RUN1_MEDIUM': 'particle_eff', 'TAU_EFF_ATLAS_RUN1_TIGHT': 'particle_eff', 'TAU_EFF_ATLAS_RUN2': 'particle_eff', 'TAU_EFF_ATLAS_RUN2_LOOSE': 'particle_eff', 'TAU_EFF_ATLAS_RUN2_MEDIUM': 'particle_eff', 'TAU_EFF_ATLAS_RUN2_TIGHT': 'particle_eff', 'TAU_EFF_CMS_RUN1': 'particle_eff', 'TAU_EFF_CMS_RUN1_LOOSE': 'particle_eff', 'TAU_EFF_CMS_RUN1_MEDIUM': 'particle_eff', 'TAU_EFF_CMS_RUN1_TIGHT': 'particle_eff', 'TAU_EFF_CMS_RUN2': 'particle_eff', 'TAU_EFF_CMS_RUN2_LOOSE': 'particle_eff', 'TAU_EFF_CMS_RUN2_MEDIUM': 'particle_eff', 'TAU_EFF_CMS_RUN2_TIGHT': 'particle_eff', 'TAU_EFF_IDENTITY_LOOSE': 'particle_eff', 'TAU_EFF_IDENTITY_MEDIUM': 'particle_eff', 'TAU_EFF_IDENTITY_TIGHT': 'particle_eff', 'TAU_SMEAR_ATLAS_RUN1': 'particle_smear', 'TAU_SMEAR_ATLAS_RUN2': 'particle_smear', 'TAU_SMEAR_CMS_RUN1': 'particle_smear', 'TAU_SMEAR_CMS_RUN2': 'particle_smear', 'TAU_SMEAR_IDENTITY': 'particle_smear', 'TRK_EFF_ATLAS_RUN1': 'particle_eff', 'TRK_EFF_ATLAS_RUN2': 'particle_eff', 'TRK_EFF_CMS_RUN1': 'particle_eff', 'TRK_EFF_CMS_RUN2': 'particle_eff', 'TRK_EFF_IDENTITY_TIGHT': 'particle_eff', 'TRK_SMEAR_ATLAS_RUN1': 'particle_smear', 'TRK_SMEAR_ATLAS_RUN2': 'particle_smear', 'TRK_SMEAR_CMS_RUN1': 'particle_smear', 'TRK_SMEAR_CMS_RUN2': 'particle_smear', 'TRK_SMEAR_IDENTITY': 'particle_smear'}


def _id(value):
    result=jets._identifier(value)
    if result in RESERVED or result in BUILTINS:raise ValueError('response local shadows native type/function')
    return result


def _proof(binding, source_units, consumed):
    jets._keys(binding,('path','sha256','size','start','end','expression_sha256'))
    from ravel.analysis_sources import relative_path
    relative_path(binding['path'])
    raw=source_units.get(binding['path'])
    if type(raw)is not bytes or not 0<len(raw)<=jets.MAX_SOURCE_BYTES:raise ValueError('bounded authenticated source-expression bytes required')
    if type(binding['size'])is not int or len(raw)!=binding['size'] or hashlib.sha256(raw).hexdigest()!=binding['sha256']:
        raise ValueError('source-expression proof differs from original full bytes')
    if sum(len(v)for v in consumed.values())+(0 if binding['path']in consumed else len(raw))>MAX_PROOF_BYTES:
        raise ValueError('aggregate response proof budget exceeded')
    if binding['path']in consumed and consumed[binding['path']]!=raw:raise ValueError('source proof identity conflict')
    consumed[binding['path']]=raw
    start,end=binding['start'],binding['end']
    if type(start)is not int or type(end)is not int or not 0<=start<end<=len(raw) or end-start>MAX_EXPRESSION:
        raise ValueError('bounded exact byte span required for response expression')
    expression=raw[start:end]
    if hashlib.sha256(expression).hexdigest()!=binding['expression_sha256']:raise ValueError('response expression span digest differs')
    try:text=expression.decode('utf-8')
    except UnicodeDecodeError as exc:raise ValueError('response source expression must be strict UTF-8')from exc
    if '\x00'in text or not text.strip():raise ValueError('nonempty native source expression required')
    return text


def compile_component(recipe, *, particle_inputs=None, jet_inputs=None, met_inputs=None,
                      reserved=(), projection_names=(), source_units=None):
    """Lower ordered native response nodes; no detector events are computed.

    Inputs map prior typed projection IDs to actual native C++ locals. Callback
    expressions are either released literal functions or exact byte spans from
    complete digest-bound source evidence, never free-form unbound code.
    """
    recipe=deepcopy(recipe);jets._keys(recipe,('schema_version','kind','native_api','functions','nodes'))
    if type(recipe['schema_version'])is not int or recipe['schema_version']!=1 or recipe['kind']!='native-rivet-response-components' or recipe['native_api']!=API_VERSION:
        raise ValueError('native-rivet-response-components/v1 requires explicit released4.1.4 source API')
    source_units={}if source_units is None else source_units
    if type(source_units)is not dict:raise ValueError('source proof byte map required')
    contexts={}
    for typ,values in [('particles',particle_inputs),('jets',jet_inputs),('met',met_inputs)]:
        values={}if values is None else deepcopy(values)
        if type(values)is not dict or len(values)>128:raise ValueError('bounded typed prior projection map required')
        for key,value in values.items():_id(key);_id(value)
        contexts[typ]=values
    symbols=set(reserved);names=set(projection_names)
    if symbols & RESERVED:raise ValueError('enclosing local shadows native response type')
    def symbol(value):
        value=_id(value)
        if value in symbols:raise ValueError('distinct response and enclosing locals required')
        symbols.add(value);return value
    def projection(value):
        value=jets._native_name(value)
        if value in names:raise ValueError('distinct response projection names required')
        names.add(value);return value
    functions={};consumed={}
    if type(recipe['functions'])is not list or not 0<=len(recipe['functions'])<=MAX_FUNCTIONS:raise ValueError('bounded response function census required')
    for f in recipe['functions']:
        jets._keys(f,('id','type','value'));identity=_id(f['id']);typ=f['type']
        if identity in functions or type(typ)is not str or typ not in TYPES:raise ValueError('unique typed response functions required')
        value=f['value']
        if type(value)is not dict:raise ValueError('closed native function source required')
        if value.get('kind')=='builtin':
            jets._keys(value,('kind','name'));name=value['name']
            if type(name)is not str or BUILTINS.get(name)!=typ:raise ValueError('exact released native callback type/name required')
            expression=name
        elif value.get('kind')=='source_expression':
            jets._keys(value,('kind','binding'));expression=_proof(value['binding'],source_units,consumed)
        else:raise ValueError('unbound response expression is not a scientific source')
        functions[identity]=(typ,expression)
    used=set()
    def function(identity, allowed):
        if type(identity)is not str or identity not in functions or functions[identity][0]not in allowed:raise ValueError('callback does not satisfy native operation type')
        used.add(identity);typ,expression=functions[identity]
        return f'{TYPES[typ]}({expression})'
    def input_ref(identity,typ):
        if type(identity)is not str or identity not in contexts[typ]:raise ValueError('response input must name a prior compatible native projection')
        return contexts[typ][identity]
    def steps(values,typ):
        if type(values)is not list or len(values)>16:raise ValueError('bounded ordered response function steps required')
        allowed={'particles':('particle_eff','particle_smear'),'jets':('jet_eff','jet_smear')}[typ]
        cls={'particles':'ParticleEffSmearFn','jets':'JetEffSmearFn'}[typ]
        return [f'{cls}({function(v,allowed)})'for v in values]
    headers=['Rivet/Tools/SmearingFunctions.hh'];init=[];analyze=[];semantics=[];collections={}
    if type(recipe['nodes'])is not list or not 1<=len(recipe['nodes'])<=MAX_NODES:raise ValueError('bounded nonempty response node population required')
    for node in recipe['nodes']:
        kind=node.get('kind')if type(node)is dict else None
        common=('kind','id','projection_name','outputs')
        fields={'tau':('decay','origin','cuts','pids'),'particles':('input','steps','cuts','pids'),
                'jets':('input','steps','b_tag','c_tag'),'met':('input','params','smear')}
        if kind not in fields:raise ValueError('unsupported native response family')
        jets._keys(node,common+fields[kind]);identity=symbol(node['id']);name=projection(node['projection_name']);cls=CLASSES[kind]
        headers.append('Rivet/Projections/'+cls+'.hh');detail={'id':identity,'kind':kind,'input':node.get('input'),'native_class':cls}
        if kind=='tau':
            if type(node['decay'])is not str or node['decay']not in TAU_DECAYS or type(node['origin'])is not str or node['origin']not in TAU_ORIGINS:raise ValueError('explicit supported native tau decay/origin required')
            args=['TauDecay::'+TAU_DECAYS[node['decay']],'LeptonOrigin::'+TAU_ORIGINS[node['origin']],particles._cut(node['cuts'],node['pids'])]
            contexts['particles'][identity]=identity
            detail.update(selection='native_unstable_tau_abspid_decay_stable_descendant_hadron_test_and_isPrompt_origin',cuts='on_UnstableParticles_input_not_visible_tau_or_detector_efficiency')
        elif kind=='particles':
            args=[input_ref(node['input'],'particles'),particles._cut(node['cuts'],node['pids']),*steps(node['steps'],'particles')]
            contexts['particles'][identity]=identity
            detail.update(order='ordered_native_transforms_each_step_receives_previous_smeared_particle',efficiency='native_short_circuit_random_discard_before_next_step',cuts='after_all_transforms_on_reco_particle',constituents='native_add_original_particle_only_for_kept_reco_objects')
        elif kind=='jets':
            args=[input_ref(node['input'],'jets')]
            args += ['JetEffFn{}'if node[k]is None else function(node[k],('jet_eff',))for k in ('b_tag','c_tag')]
            args += steps(node['steps'],'jets');contexts['jets'][identity]=identity
            detail.update(order='ordered_native_transforms_then_tagging_on_smeared_kinematics',constituents='native_restore_original_constituents_and_tags_if_smear_lost_them',null_tag='native_truth_tag_fallback_not_zero_efficiency',native_c_tag_warning='released4.1.4_random_ctag_branch_compares_draw_to_beff_not_ceff_preserved_requires_physics_review')
        else:
            args=[input_ref(node['input'],'met')]
            if node['params']is None and node['smear']is None:raise ValueError('MET requires a native vector or parameter response function')
            if node['params']is not None:args.append(function(node['params'],('met_params',)))
            if node['smear']is not None:args.append(function(node['smear'],('met_smear',)))
            # Released constructors require MissingMomentum, not generic METFinder.
            # SmearedMET chaining is deliberately not admitted.
            detail.update(vector_precedence='native_vector_smear_takes_precedence_when_both_supplied',scalar_sums='native_original_scalarPt_and_scalarEt_unchanged',params='native_sampling_params_for_pT_uses_SET_not_SPT',direction='native_visible_vectors_retained_missing_is_negative_visible')
        init += [f'const {cls} {identity}({", ".join(args)});',f'declare({identity}, "{name}");']
        outputs=node['outputs']
        if type(outputs)is not list or len(outputs)>12:raise ValueError('bounded complete response output list required')
        for out in outputs:
            if kind=='met':
                jets._keys(out,('id','quantity','unit'));output=symbol(out['id']);q=out['quantity']
                methods={'missing_pt':('double','missingPt','GeV'),'missing_et':('double','missingEt','GeV'),
                         'vector_missing_pt':('Vector3','vectorMissingPt','GeV'),'vector_missing_et':('Vector3','vectorMissingEt','GeV'),
                         'vector_visible_pt':('Vector3','vectorSumPt','GeV'),'vector_visible_et':('Vector3','vectorSumEt','GeV'),
                         'scalar_visible_pt':('double','scalarSumPt','GeV'),'scalar_visible_et':('double','scalarSumEt','GeV'),
                         'pt_resolution':('double','missingPtResolution','GeV'),'et_resolution':('double','missingEtResolution','GeV'),
                         'pt_significance':('double','missingPtSignf','1'),'et_significance':('double','missingEtSignf','1')}
                if type(q)is not str or q not in methods or out['unit']!=methods[q][2]:raise ValueError('explicit native MET quantity and unit required')
                if q in ('pt_resolution','et_resolution','pt_significance','et_significance')and node['params']is None:raise ValueError('native MET resolution/significance needs parameter function')
                dtype,method,unit=methods[q];div='/GeV'if unit=='GeV'else''
                analyze.append(f'const {dtype} {output} = apply<{cls}>(event, "{name}").{method}(){div};')
            else:
                jets._keys(out,('id','access','cuts'));output=symbol(out['id']);access=out['access']
                methods={'tau':{'taus':('Particles','taus',False),'particles_by_pt':('Particles','particlesByPt',True)},
                         'particles':{'particles':('Particles','particles',True),'particles_by_pt':('Particles','particlesByPt',True),'truth_particles':('Particles','truthParticles',False)},
                         'jets':{'jets':('Jets','jets',True),'jets_by_pt':('Jets','jetsByPt',True),'truth_jets':('Jets','truthJets',False)}}[kind]
                if type(access)is not str or access not in methods:raise ValueError('explicit supported native response collection access required')
                dtype,method,has_cut=methods[access]
                if not has_cut and out['cuts']!=[]:raise ValueError('native truth/tau access accepts no output cuts; cannot silently drop them')
                cuts=jets._cuts(out['cuts'])if has_cut else''
                analyze.append(f'const {dtype} {output} = apply<{cls}>(event, "{name}").{method}({cuts});')
                collections[output]='jets'if kind=='jets'else'particles'
        detail['outputs']=deepcopy(outputs);semantics.append(detail)
    if set(functions)!=used:raise ValueError('every declared response callback must have an actual operation consumer')
    source_pins=[{'path':path,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}for path,raw in sorted(consumed.items())]
    return {'schema_version':1,'kind':'native-rivet-response-component-source','recipe':recipe,'recipe_sha256':jets._digest(recipe),
            'headers':list(dict.fromkeys(headers)),'init':'\n'.join(init),'analyze':'\n'.join(analyze),'response_semantics':semantics,
            'collections':collections,'source_dependencies':source_pins,'local_symbols':sorted(symbols-set(reserved)),
            'projection_names':sorted(names-set(projection_names)),'native_executed':False,'physics_validated':False,
            'remaining_obligations':['exact_released_constructor_callback_types_native_compile_load',
              'RIVET_DISABLE_SMEARING_native_environment_branch_and_RNG_stream_observation',
              'native_function_law_selection_cache_identity_and_transform_order',
              'native_tag_constituent_provenance_and_released_ctag_behavior_review',
              'native_MET_pT_Et_SET_significance_and_massive_particle_distinction',
              'analysis_specific_calibration_response_correlations_and_paper_applicability',
              'complete_enclosing_source_assets_weight_vectors_final_RAW_output_and_normalization']}


def validate_capsule_sources(capsule, component):
    """Every consumed source expression stays an ordinary capsule input."""
    from ravel import analysis_sources
    capsule=analysis_sources.validate_capsule(deepcopy(capsule))
    for source in component.get('response_source_dependencies',[]):
        matches=[f for f in capsule['files']if f['path']==source['path']and f['sha256']==source['sha256']and f['role']in ('header','configuration','calibration')]
        if len(matches)!=1:raise ValueError('complete response-expression source proof must remain an ordinary capsule asset')
    return capsule


def _disjoint_destination(destination, original_root):
    """Reject original-root overlap before writing a derivative inventory.

    Relative roots use the invocation cwd, as do the existing dict API paths.
    Resolving existing aliases catches declared-root aliases and dot segments;
    this is an endpoint observation, not a lock against concurrent path changes.
    """
    from pathlib import Path
    destination=Path(destination).absolute()
    try:
        source=Path(original_root).absolute().resolve(strict=False)
        output=destination.resolve(strict=False)
    except (OSError,RuntimeError) as exc:
        raise ValueError('original/output root identity unavailable')from exc
    if output.is_relative_to(source)or source.is_relative_to(output):
        raise ValueError('response output and original source roots must be disjoint')
    # A canonical string can retain case spelling on a case-insensitive
    # filesystem. Compare existing endpoint directory identities as well.
    try:
        original_identity=source.stat()
    except FileNotFoundError:
        original_identity=None  # byte-supplied capsules may name an absent root
    except OSError as exc:
        raise ValueError('original source endpoint identity unavailable')from exc
    if original_identity is not None:
        identity=(original_identity.st_dev,original_identity.st_ino)
        for parent in (destination,*destination.parents):
            try:observed=parent.stat()
            except FileNotFoundError:continue
            except OSError as exc:
                raise ValueError('output endpoint identity unavailable')from exc
            if (observed.st_dev,observed.st_ino)==identity:
                raise ValueError('response output and original source roots must be disjoint')
    return destination


def materialize(original, *, compile_unit, template, expected_sha256, recipe, files, root, build_template=None):
    """Write a fresh full source capsule for the existing ordinary build route.

    ``files`` contains immutable complete bytes for EVERY original capsule file,
    including bound callback proofs. Only the selected compile unit is replaced.
    No compile, tool probing, approval, dependency review or event run occurs.
    Optional build_template is a prospective ordinary routine-build config; its
    original fields are preserved except the new capsule path. Normal admission
    still authenticates all runtime fields and refuses the unresolved capsule.
    """
    import json
    from pathlib import Path
    from ravel import analysis_sources
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    from . import rivet_event_components as event
    original=analysis_sources.validate_capsule(deepcopy(original))
    if type(files)is not dict or set(files)!={f['path']for f in original['files']} or len(files)>1024:
        raise ValueError('exact complete bounded original capsule file census required')
    if any(type(v)is not bytes or not 0<len(v)<=16*1024*1024 for v in files.values()) or sum(map(len,files.values()))>128*1024*1024:
        raise ValueError('complete materialization file byte budget exceeded')
    for f in original['files']:
        if hashlib.sha256(files[f['path']]).hexdigest()!=f['sha256']:
            raise ValueError('original materialization bytes differ from capsule')
    destination=_disjoint_destination(root,original['root'])
    result=event.instantiate(template,expected_sha256=expected_sha256,recipe=recipe,source_units=files)
    capsule=event.source_capsule(original,compile_unit=compile_unit,source=result['source'],root=str(Path(root).absolute()),component=result['component'])
    for ancestor in destination.parents:
        if ancestor.is_symlink() or not ancestor.is_dir():raise ValueError('existing ordinary materialization ancestors required')
    if destination.exists()or destination.is_symlink():raise ValueError('fresh response materialization directory required')
    if build_template is not None:
        if type(build_template)is not dict or set(build_template)!={'schema_version','source_capsule','recipe','runtime','probe'} or type(build_template['schema_version'])is not int or build_template['schema_version']!=1:
            raise ValueError('closed prospective ordinary routine-build/v1 config required')
        build_template=deepcopy(build_template)
        if type(build_template['recipe'])is not dict:raise ValueError('ordinary build recipe dictionary required')
        jets._keys(build_template['recipe'],('name','compile_units','output','flags'))
        if build_template['recipe'].get('name')!='rivet-plugin' or compile_unit not in build_template['recipe'].get('compile_units',[]):
            raise ValueError('ordinary Rivet build recipe must consume the changed compile unit')
    # Reobserve immediately before the first filesystem write; no cleanup
    # can turn an overlapping attempt into an accepted operation.
    _disjoint_destination(destination,original['root'])
    destination.mkdir()
    payloads=dict(files);payloads[compile_unit]=result['source']
    # Metadata lives outside the source root so it cannot shadow source members.
    source_root=destination/'source';source_root.mkdir();capsule['root']=str(source_root)
    def encoded(document):return (json.dumps(document,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    emitted={source_root/rel:raw for rel,raw in payloads.items()}
    capsule_path=destination/'source-capsule.json';emitted[capsule_path]=encoded(capsule)
    build_path=None
    if build_template is not None:
        build_path=destination/'build.json';build_template['source_capsule']=str(capsule_path)
        emitted[build_path]=encoded(build_template)
    def identity(s):return(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    committed={}
    for path,raw in emitted.items():
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb')as stream:stream.write(raw)
        committed[path]=identity(path.lstat())
    directories={parent:(parent.lstat().st_dev,parent.lstat().st_ino,parent.lstat().st_mode)for path in emitted for parent in path.parents}
    pins=[]
    for path,raw in emitted.items():
        _,observed=_bounded_source_snapshot(path,max(len(raw),1))
        if observed!=raw or identity(path.lstat())!=committed[path]:
            raise ValueError('generated response source/asset/metadata changed before return')
        pins.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
    # Final identities cover earlier files while later files were consumed.
    for path in emitted:
        if any(q.is_symlink()for q in(path,*path.parents)) or identity(path.lstat())!=committed[path]:
            raise ValueError('generated materialization custody changed before return')
    if any(parent.is_symlink()or(parent.lstat().st_dev,parent.lstat().st_ino,parent.lstat().st_mode)!=expected for parent,expected in directories.items()):
        raise ValueError('generated materialization ancestor identity changed before return')
    return {'schema_version':1,'kind':'native-rivet-response-materialization',
        'capsule':str(capsule_path),'build_task':None if build_path is None else{'backend':'routine-build','input':str(build_path)},
        'component':result['component'],'output_pins':pins,
        'native_executed':False,'dependency_review_complete':False,'scientific_accepted':False,
        'next_action':'fresh_dependency_and_source_review_then_ordinary_routine_build_and_existing_events_all_outputs'}
