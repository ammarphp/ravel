"""Native event-shape source construction; no Python event-shape calculation.

Caller-supplied collection types/frame are explicit declarations, not inferred
from C++ text. Instantiation binds their exact preceding source excerpts. Fresh
native compilation and event/all-output qualification remain required.
"""
from copy import deepcopy
import hashlib
import re
from . import rivet_particle_component as particles
from . import rivet_jet_component as jets

CLASSES={'sphericity':'Sphericity','thrust':'Thrust','spherocity':'Spherocity'}
SCALARS={'sphericity':('sphericity','transSphericity','aplanarity','planarity','lambda1','lambda2','lambda3'),
 'thrust':('thrust','thrustMajor','thrustMinor','oblateness'),'spherocity':('spherocity',)}
AXES={'sphericity':('sphericityAxis','sphericityMajorAxis','sphericityMinorAxis','axis1','axis2','axis3'),
 'thrust':('thrustAxis','thrustMajorAxis','thrustMinorAxis','axis1','axis2','axis3'),
 # Native Spherocity fills one axis only: major/minor/axis2/axis3 index absent state.
 'spherocity':('spherocityAxis','axis1')}
TYPES={'particles':'Particles','jets':'Jets','vector3':'vector<Vector3>',
 'four_momenta':'vector<FourMomentum>','final_state':'FinalState'}
RESERVED=set(CLASSES.values())|{'AxesDefinition','Vector3','FourMomentum','Particles','Jets','vector','event'}


def _id(value):
    if (type(value)is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',value)
            or '__' in value or re.match(r'_[A-Z]',value) or value in jets.CPP_KEYWORDS):
        raise ValueError('bounded nonreserved function-local C++ identity required')
    if value in RESERVED | set(particles.CLASSES.values()) | particles.TOP_TYPES | {'Rivet','std','Cuts','GeV','init','analyze','finalize'}:raise ValueError('native event-shape type cannot be a local')
    return value


def compile_component(recipe, *, final_states=(), collections=None, reserved=(), projection_names=()):
    recipe=deepcopy(recipe);jets._keys(recipe,('schema_version','kind','source_bindings','nodes'))
    if type(recipe['schema_version'])is not int or recipe['schema_version']!=1 or recipe['kind']!='native-rivet-shape-components':
        raise ValueError('native-rivet-shape-components/v1 required')
    if type(recipe['nodes'])is not list or not 1<=len(recipe['nodes'])<=16:
        raise ValueError('one to16 explicit native shape nodes required')
    if type(recipe['source_bindings'])is not list or len(recipe['source_bindings'])>32:
        raise ValueError('bounded explicit preceding source bindings required')
    symbols=set(reserved);names=set(projection_names);fs=set(final_states);cols=dict(collections or {})
    external=set();bindings={};used=set();init=[];analyze=[];headers=[];semantics=[]
    for b in recipe['source_bindings']:
        jets._keys(b,('id','type','frame','definition','definition_sha256'))
        identity=_id(b['id'])
        if identity in symbols or identity in fs or identity in cols:raise ValueError('source binding shadows existing native local')
        if type(b['type'])is not str or b['type']not in TYPES or b['frame']!='caller_supplied_no_transform':
            raise ValueError('explicit native collection type and unchanged caller frame required')
        text=b['definition']
        if type(text)is not str or not 0<len(text.encode())<=32768 or identity not in text:
            raise ValueError('bounded exact preceding native source definition required')
        if hashlib.sha256(text.encode()).hexdigest()!=b['definition_sha256']:
            raise ValueError('source definition digest differs')
        symbols.add(identity);external.add(identity);bindings[identity]=b
        if b['type']=='final_state':fs.add(identity)
        else:cols[identity]=b['type']
    def symbol(v):
        v=_id(v)
        if v in symbols:raise ValueError('distinct shape locals required across pipeline')
        symbols.add(v);return v
    for node in recipe['nodes']:
        jets._keys(node,('id','kind','input','projection_name','r','outputs'))
        cls=node['kind']
        if type(cls)is not str or cls not in CLASSES:raise ValueError('closed native event-shape family required')
        identity=symbol(node['id']);inp=node['input'];jets._keys(inp,('kind','id'))
        parent=inp['id']
        if type(parent)is not str:raise ValueError('exact prior native input identity required')
        used.add(parent)
        if cls=='sphericity':
            r=jets._number(node['r'])
            if r<=0:raise ValueError('positive finite explicit native sphericity r required')
        elif node['r']is not None:raise ValueError('only Sphericity accepts r')
        projection=node['projection_name'];native=CLASSES[cls]
        if inp['kind']=='projection':
            if parent not in fs:raise ValueError('cached shape input requires native FinalState, not ParticleFinder or decay table')
            projection=jets._native_name(projection)
            if projection in names:raise ValueError('distinct declared shape projection names required')
            names.add(projection)
            args=parent+(', '+repr(r)if cls=='sphericity'else'')
            init.extend((f'const {native} {identity}({args});',f'declare({identity}, "{projection}");'))
            access=f'apply<{native}>(event, "{projection}")'
        elif inp['kind']=='collection':
            if parent not in cols:raise ValueError('direct shape input requires exact declared native collection')
            if projection is not None:raise ValueError('direct calc is not a declared cached projection')
            typ=cols[parent]
            if cls!='sphericity'and typ=='jets':raise ValueError('native Thrust/Spherocity have no Jets calc overload; bind original momentum construction instead')
            if typ not in ('particles','jets','vector3','four_momenta'):raise ValueError('unsupported direct native collection type')
            analyze.extend((f'{native} {identity}'+(f'({repr(r)})'if cls=='sphericity'else'')+';',f'{identity}.calc({parent});'))
            access=identity
        else:raise ValueError('explicit projection or direct collection input required')
        outputs=node['outputs']
        if type(outputs)is not list or len(outputs)>13:raise ValueError('bounded explicit native shape outputs required')
        if inp['kind']=='collection'and not outputs:raise ValueError('direct native shape calculation requires a consuming output')
        for output in outputs:
            jets._keys(output,('id','access','unit'));out=symbol(output['id']);method=output['access']
            if method=='object':
                if output['unit']!='native_projection':raise ValueError('native object is not a dimensionless scalar')
                analyze.append(f'const {native}& {out} = {access};')
            else:
                if type(method)is not str or method not in SCALARS[cls]+AXES[cls] or output['unit']!='1':
                    raise ValueError('supported native dimensionless scalar/axis accessor required')
                typ='double'if method in SCALARS[cls]else'Vector3'
                analyze.append(f'const {typ} {out} = {access}.{method}();')
        headers.append('Rivet/Projections/'+native+'.hh')
        semantics.append(dict(id=identity,kind=cls,input=deepcopy(inp),r=node['r'],outputs=outputs,
            calculation='unchanged_native_kernel_no_python_tensor_eigenvalue_or_optimizer',
            input_frame='caller_supplied_no_boost_rotation_transverse_projection_or_ghost_insertion',
            cache='native_FinalState_and_native_r_compare'if inp['kind']=='projection'else'uncached_native_calc_on_exact_declared_collection',
            status='native_empty_degenerate_nonfinite_and_axis_orientation_unmodified_no_clipping',
            native_r='explicit_momentum_power_not_an_event_weight_or_unit_conversion'if cls=='sphericity'else'not_applicable'))
    if external-used:raise ValueError('unconsumed preceding source binding')
    return dict(schema_version=1,kind='native-rivet-shape-component-source',recipe=recipe,recipe_sha256=jets._digest(recipe),
        headers=list(dict.fromkeys(headers)),init='\n'.join(init),analyze='\n'.join(analyze),shape_semantics=semantics,
        source_binding_status='literal_excerpt_bound_native_type_and_population_require_fresh_compiler_and_event_review',
        weights='enclosing_native_routine_unchanged_no_weight_arithmetic',native_executed=False,physics_validated=False,
        remaining_obligations=['fresh_exact_native_API_ABI_compile_load_registration',
          'complete_caller_input_selection_frame_boost_ghost_multiplicity_and_native_degenerate_states',
          'full_original_classifiers_models_features_and_native_axes_and_r_distinctions',
          'all_original_final_RAW_outputs_weights_flows_units_errors_normalization_and_physical_cohort'])


def validate_source_bindings(source, recipe, *, init_slot, analyze_slot):
    """Bind exact original definitions before their consuming slot; no C++ parsing."""
    text=source.decode('utf-8')
    for b in recipe['source_bindings']:
        definition=b['definition'];slot=init_slot if b['type']=='final_state'else analyze_slot
        if text.count(definition)!=1 or text.count(slot)!=1 or text.index(definition)+len(definition)>text.index(slot):
            raise ValueError('exact source definition must uniquely precede consuming shape slot')


def instantiate(source, *, expected_sha256, recipe):
    if type(source)is not bytes or not 0<len(source)<=jets.MAX_SOURCE_BYTES or hashlib.sha256(source).hexdigest()!=expected_sha256:
        raise ValueError('bounded exact source template required')
    c=compile_component(recipe);validate_source_bindings(source,recipe,init_slot='// RAVEL_SHAPE_INIT',analyze_slot='// RAVEL_SHAPE_ANALYZE')
    text=source.decode();repl={'// RAVEL_SHAPE_HEADERS':'\n'.join('#include "'+h+'"'for h in c['headers']),
        '// RAVEL_SHAPE_INIT':c['init'],'// RAVEL_SHAPE_ANALYZE':c['analyze']}
    lines=text.splitlines(keepends=True)
    for slot in repl:
        if text.count(slot)!=1 or sum(line.strip()==slot for line in lines)!=1:raise ValueError('three unique whole-line shape slots required')
    out=[]
    for line in lines:
        if line.strip()in repl:
            indent=line[:len(line)-len(line.lstrip())];end='\r\n'if line.endswith('\r\n')else'\n'
            out.extend(indent+part+end for part in repl[line.strip()].splitlines())
        else:out.append(line)
    raw=''.join(out).encode()
    if len(raw)>jets.MAX_SOURCE_BYTES:raise ValueError('generated source too large')
    return dict(source=raw,source_sha256=hashlib.sha256(raw).hexdigest(),original_template_sha256=expected_sha256,component=c,
        source_capsule_dependency_review='incomplete_requires_fresh_native_admission')


def source_capsule(original, *, compile_unit, source, root):
    from . import rivet_components
    return rivet_components.source_capsule(original,compile_unit=compile_unit,source=source,root=root)
