"""Complete supplied mass/spectrum/lifetime recipes through ordinary studies.

Lifetime reuse never supplies a new mass, production/decay model, detector
transport or calibration. This operation constructs inputs and full moments;
generation, statistical inference and original-task acceptance stay separate.
"""
from copy import deepcopy
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import re

from ravel.workflow import task_completion as tc
from ravel.workflow.state_io import atomic_json
from ravel.physics import detector_response as dr, marked_response as mr
from ravel.physics import model_events as gen, svj_recipe as recipe
from ravel.physics import published_model as pm, signal_templates as st

SCOPE = 'supplied_llp_plane_recipe_construction'
MAX_BYTES = 128*1024**2


def require(ok, message):
    if not ok: raise ValueError(message)


def keys(d, expected):
    require(type(d) is dict and set(d) == set(expected), 'closed LLP recipe fields required')


def number(x, positive=False):
    require(type(x) in (int, float) and math.isfinite(x) and (not positive or x > 0), 'finite physical literal required')
    return x


def names(rows, maximum=128):
    require(type(rows) is list and 1 <= len(rows) <= maximum, 'bounded complete named population required')
    values = [r['id'] for r in rows]
    require(all(type(x) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,80}', x) for x in values) and len(set(values)) == len(values), 'distinct safe source identities required')
    return values


def pin(path):
    return recipe.pin(path)


def validate(task):
    keys(task, ('input',)); require(type(task['input']) is str and task['input'], 'LLP input path required')


def _doc(ref, session):
    require(type(ref) is dict and Path(ref['path']).is_absolute(), 'absolute byte-bound scientific input required')
    if set(ref) == {'path','sha256'}:
        observed = session.capture(Path(ref['path']))
        require(observed['sha256'] == ref['sha256'], 'existing two-field document pin differs')
        return session.document(observed)
    return session.document(ref)


def _sources(pins, session):
    require(type(pins) is list and pins, 'physical definition and calibration sources required')
    for p in pins:
        require(Path(p['path']).is_absolute(), 'absolute physical source pin required')
        session.file(p)


def _json_commitment(path, document):
    # Exactly state_io.atomic_json's encoding, committed before its write.
    raw = (json.dumps(document, indent=2, allow_nan=False) + '\n').encode('utf-8')
    return {'path':str(Path(path).absolute()),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def _generation_target(point, component, identity, d, session):
    request = _doc(component['generation'], session)
    require(request['goal_binding'] == d['goal_binding'], 'generator must retain original parent assignment')
    config = _doc(request['config'], session); gen.validate_config(config)
    g = config['generation']
    # This LHC source branch supports symmetric proton beams only. No guessed
    # collider-energy conversion for other beam species or asymmetric beams.
    supported = g['beam_type'] == [1,1] and g['beam_pdg'] == [2212,2212] and g['energy_gev'][0] == g['energy_gev'][1]
    if supported:
        require(sum(map(gen.number,g['energy_gev'])) == gen.number(identity['energy_tev'])*1000 == gen.number(d['analysis']['energy_tev'])*1000,
                'generator beam energy differs from physical point and analysis')
    ref = component.get('generation_target')
    if ref is None: return None
    target = _doc(ref,session)
    keys(target, ('schema_version','point_identity_sha256','component_id','beam_type','beam_pdg','energy_gev','model_manifest','process_card','parameter_card','coordinate_parameters','mass_parameters','decay','sources'))
    require(type(target['schema_version']) is int and target['schema_version'] == 1 and target['point_identity_sha256'] == point['identity']['sha256'] and target['component_id'] == component['id'], 'generator target physical point/component differs')
    require(all(target[k] == g[k] for k in ('beam_type','beam_pdg','energy_gev')), 'generator target initial state differs')
    _sources(target['sources'],session)
    config_base = Path(request['config']['path']).parent
    for name, configured in [('model_manifest',config['model_tree']['manifest']),('process_card',config['cards']['process']),('parameter_card',config['cards']['parameter'])]:
        expected = session.canonical(target[name]); session.file(target[name])
        path = gen.bridge._pin(configured,config_base)
        require(expected['path'] == str(path) and expected['sha256'] == configured['sha256'], 'generator target exact '+name+' differs')
    require(target['decay'] == config['decay'], 'generator target decay settings differ')
    parameter_path = gen.bridge._pin(config['cards']['parameter'],config_base)
    values = gen.parameter_values(gen.authenticated_text(parameter_path,config['cards']['parameter']['sha256']))
    def address(binding):
        keys(binding,('block','indices'))
        require(type(binding['block']) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',binding['block']) and type(binding['indices']) is list and binding['indices'] and all(type(i) is int for i in binding['indices']), 'literal generator parameter address required')
        key = (binding['block'].lower(),tuple(binding['indices']))
        require(key in values, 'generator target parameter address absent')
        return values[key]
    require(type(target['coordinate_parameters']) is list and len(target['coordinate_parameters']) == len(d['axes']), 'complete generator coordinate mapping required')
    for index, row in enumerate(target['coordinate_parameters']):
        keys(row,('axis_id','unit','parameter'))
        require(row['axis_id'] == d['axes'][index]['id'] and row['unit'] == d['axes'][index]['unit'] and address(row['parameter']) == gen.number(point['coordinate'][index]), 'generator target coordinate value or unit differs')
    species = next(c['llp_species'] for c in identity['components'] if c['id'] == component['id'])
    require(names(target['mass_parameters'],16) == [s['id'] for s in species], 'complete generator LLP mass mapping required')
    for row, spec in zip(target['mass_parameters'],species):
        keys(row,('id','parameter'))
        require(row['parameter']['block'].lower() == 'mass' and address(row['parameter']) == gen.number(spec['mass_GeV']), 'generator LLP mass differs from physical point')
    return target if supported else None


def _capture(task, base):
    validate(task); p = Path(task['input']); p = p if p.is_absolute() else Path(base)/p
    session = tc._Inputs(p.absolute().parent); d = session.document(session.capture(p.absolute()))
    keys(d, ('schema_version','source','goal_binding','analysis','axes','points','projection_scenarios','cells','mixture_sampling','generation_policy','inference_policy','child_seconds','assumptions',
             *(['construction_limits'] if 'construction_limits' in d else [])))
    limits=d.get('construction_limits',{'max_points':32,'max_cells':128})
    keys(limits,('max_points','max_cells'))
    require(type(limits['max_points']) is int and 1<=limits['max_points']<=512 and type(limits['max_cells']) is int and 1<=limits['max_cells']<=2048,
            'bounded declared source construction limits required; no physics-domain or child-execution change')
    require(type(d['schema_version']) is int and d['schema_version'] == 1, 'LLP recipe schema1 required')
    require(type(d['source']) is str and d['source'].strip() and d['assumptions'], 'literal source and conditional assumptions required')
    require(all(type(a) is str and a.strip() for a in d['assumptions']), 'literal assumptions required')
    goal = tc.binding_projection(d['goal_binding'], base_dir=session.base)
    for p in goal['input_pins']: session.file(p)
    a = d['analysis']; keys(a, ('id','energy_tev','lumi_fb','bins','unresolved_bins','sources','transport'))
    require(type(a['id']) is str and a['id'] and a['transport'] in ('charged_source_required','neutral_source_required'), 'explicit analysis and transport boundary required')
    number(a['energy_tev'], True); number(a['lumi_fb'], True); _sources(a['sources'], session)
    names(a['bins'], 32); seen = set()
    for b in a['bins']:
        keys(b, ('id','channel','sample','index','role'))
        require(b['role'] in ('SR','CR') and type(b['index']) is int and b['index'] >= 0 and all(type(b[k]) is str and b[k] for k in ('channel','sample')), 'complete SR/CR source mapping required')
        seen.add((b['channel'],b['sample'],b['index']))
    require(len(seen) == len(a['bins']) and type(a['unresolved_bins']) is list, 'distinct fitted-bin mapping and explicit unresolved population required')
    axes = d['axes']; names(axes, 4)
    for axis in axes:
        keys(axis, ('id','unit','values')); require(type(axis['unit']) is str and axis['unit'], 'literal plane units required')
        require(type(axis['values']) is list and 1 <= len(axis['values']) <= 32, 'complete literal plane nodes required')
        for x in axis['values']: number(x)
        require(len(set(axis['values'])) == len(axis['values']), 'duplicate plane node')
    require(math.prod(len(x['values']) for x in axes)<=limits['max_points'],'whole plane exceeds declared source construction budget')
    expected = list(product(*(x['values'] for x in axes))); names(d['points'], limits['max_points'])
    require(len(expected) == len(d['points']) <= limits['max_points'] and [p['coordinate'] for p in d['points']] == [list(x) for x in expected], 'entire ordered model plane required; no missing-node interpolation')
    for p in d['points']:
        keys(p, ('id','coordinate','identity','components','lifetimes'))
        for value in p['coordinate']: number(value)
        ident = _doc(p['identity'], session)
        keys(ident, ('schema_version','coordinate','energy_tev','spectrum','components','sources'))
        require(ident['schema_version'] == 1 and ident['coordinate'] == p['coordinate'] and ident['energy_tev'] == a['energy_tev'], 'physical point/energy identity differs')
        session.file(ident['spectrum']); _sources(ident['sources'], session)
        require(names(p['components'], 16) == names(ident['components'], 16), 'complete physical production-component population required')
        species = set()
        for c, source in zip(p['components'], ident['components']):
            keys(c, ('id','rate','cohort','response','generation', *(['generation_target'] if 'generation_target' in c else [])))
            keys(source, ('id','process','decay_channels','llp_species'))
            require(type(source['process']) is str and source['process'] and type(source['decay_channels']) is str and source['decay_channels'], 'fixed process and decay-channel identity required')
            names(source['llp_species'], 16)
            for s in source['llp_species']:
                keys(s, ('id','mass_GeV','charge_e')); number(s['mass_GeV'], True); number(s['charge_e']); species.add(s['id'])
            rate = c['rate']; keys(rate, ('sigma_pb','branching_fraction','source'))
            require(number(rate['sigma_pb']) >= 0 and 0 <= number(rate['branching_fraction']) <= 1, 'literal component cross section and BR required; no gauge-fraction acceptance')
            session.file(rate['source'])
            if c['cohort'] is not None:
                cohort = _doc(c['cohort'], session)
                _sources(cohort['sources'], session); session.file(cohort['sampling']['source'])
                for definition in cohort['weight_definitions']: session.file(definition['source'])
            if c['response'] is not None:
                response = _doc(c['response'], session)
                for k in ('selection_source','calibration_source'): session.file(response[k])
            if c['generation'] is not None:
                from ravel.workflow.model_event_plan import request_inputs
                request = _doc(c['generation'], session)
                _generation_target(p,c,ident,d,session)
                _doc(request['review_policy'],session)
                request_inputs(request, Path(c['generation']['path']).parent)
            else: require(c.get('generation_target') is None, 'target mapping without a generator request')
        names(p['lifetimes'], 16)
        for t in p['lifetimes']:
            keys(t, ('id','ctau_mm')); require(type(t['ctau_mm']) is dict and set(t['ctau_mm']) == species, 'complete target lifetime for every changed species required')
            for x in t['ctau_mm'].values(): number(x, True)
    names(d['projection_scenarios'], 8)
    for scenario in d['projection_scenarios']:
        keys(scenario, ('id','energy_tev','lumi_fb','background_scaling','signal_MC','sources'))
        number(scenario['energy_tev'], True); number(scenario['lumi_fb'], True)
        require(scenario['background_scaling'] in ('stat','syst','frozen') and scenario['signal_MC'] == 'reuse_exact_cohort', 'explicit background projection law and reused signal MC required')
        _sources(scenario['sources'], session)
    keys(d['mixture_sampling'], ('kind','source'))
    require(d['mixture_sampling']['kind'] in ('independent_component_experiments','unknown'), 'component sampling dependence must be supplied')
    session.file(d['mixture_sampling']['source'])
    require(sum(len(p['lifetimes']) for p in d['points'])*len(d['projection_scenarios'])<=limits['max_cells'],'whole cell product exceeds declared source construction budget')
    expected = [(p['id'],t['id'],s['id']) for p in d['points'] for t in p['lifetimes'] for s in d['projection_scenarios']]
    require(type(d['cells']) is list and len(d['cells']) == len(expected) <= limits['max_cells'] and [(c['point_id'],c['lifetime_id'],c['projection_id']) for c in d['cells']] == expected, 'complete point/lifetime/projection product required')
    for c in d['cells']:
        keys(c, ('point_id','lifetime_id','projection_id','published_model','template','mc_interpretation'))
        require(c['mc_interpretation'] in ('supplied_Poissonized_groups_and_source_MC_constraints','unqualified'), 'explicit independent-bin MC law required')
        if c['published_model'] is not None:
            doc = _doc(c['published_model'], session)
            pm.inputs({'input': c['published_model']['path']}, session.base)
        if c['template'] is not None:
            template = st.validate_template(_doc(c['template'], session))
            for evidence in [*template['grounding'],*[q for ch in template['channels'] for s in ch['samples'] for q in s['provenance']['evidence']]]:
                session.file({**evidence, 'path': str(recipe.located(evidence, Path(c['template']['path']).parent)), 'size': recipe.located(evidence, Path(c['template']['path']).parent).stat().st_size})
    for policy in ('generation_policy','inference_policy'): _doc(d[policy], session)
    keys(d['child_seconds'], ('generation','inference'))
    for v in d['child_seconds'].values(): require(type(v) is int and 1 <= v <= 86400, 'bounded future child scope required')
    session.finish(); return d, session


def inputs(task, base):
    d, s = _capture(task, base)
    try: return _expanded(d,s)
    finally: s.close()


def inputs_for_spec(spec, base):
    d, s = _capture(spec['task'], base)
    try:
        require(spec.get('goal_binding') == d['goal_binding'], 'outer goal must preserve whole parent assignment')
        return _expanded(d,s)
    finally: s.close()


def _expanded(d, session):
    files = [Path(x) for x in session.pins]
    from ravel.workflow.model_event_plan import request_inputs
    for point in d['points']:
        for c in point['components']:
            if c['generation'] is not None:
                files += request_inputs(_doc(c['generation'],session),Path(c['generation']['path']).parent)
    for cell in d['cells']:
        if cell['published_model'] is not None:
            files += pm.inputs({'input':cell['published_model']['path']},session.base)
    session.finish()
    return sorted(set(files))


def lifetime_ratio(particles, species, target):
    """Joint independent exponential density ratio; no truncation/censoring."""
    terms = []
    for p in particles:
        a = species[p['species']]; b = target[p['species']]; u = p['proper_length_mm']
        terms.append(math.log(a/b) + u*(1/a-1/b))
    log_ratio = math.fsum(terms)
    require(math.isfinite(log_ratio) and -700 <= log_ratio <= 700, 'unrepresentable lifetime ratio; no clipping or underflow zero')
    ratio = math.exp(log_ratio); number(ratio, True)
    return {'log_ratio': log_ratio, 'ratio': ratio}


def _component(point, c, identity, d, session, out, write, bind):
    obligations = []; result = {'id': c['id'], 'obligations': obligations, 'generation': None, 'moments': None}
    if c['generation'] is not None:
        if _generation_target(point,c,identity,d,session) is None:
            obligations.append('Source-bound generator point/component/card/parameter correspondence and supported symmetric pp initial state required before child preparation.')
        else:
            from ravel.workflow.model_event_plan import prepare
            generated = prepare(_doc(c['generation'], session), base_dir=Path(c['generation']['path']).parent, output_dir=out/'generation')
            # prepare already commits both intended documents before emission;
            # retain its specification pin and literal returned receipt, not a
            # later observed stamp that could endorse changed producer bytes.
            bind(generated['specification'])
            bind(_json_commitment(out/'generation/preparation.json',generated))
            result['generation'] = generated
    if c['cohort'] is None: obligations.append('Complete exact-point production/decay cohort, including rejected and zero-LLP events, required.')
    if c['response'] is None: obligations.append('Source-calibrated charged/neutral joint SR/CR response required; no straight charged trajectory or per-track factorization supplied.')
    if obligations: return result
    cohort = _doc(c['cohort'], session); response = _doc(c['response'], session)
    keys(cohort, ('schema_version','point_identity_sha256','component_id','species','sampling','events','weight_definitions','sources'))
    require(cohort['schema_version'] == 1 and cohort['point_identity_sha256'] == point['identity']['sha256'] and cohort['component_id'] == c['id'], 'mass/spectrum/process cohort reuse differs; lifetime reweight cannot move models')
    _sources(cohort['sources'], session); names(cohort['species'], 16)
    weight_names = names(cohort['weight_definitions'],16)
    for definition in cohort['weight_definitions']:
        keys(definition,('id','unit','meaning','source'))
        require(definition['unit']=='dimensionless' and type(definition['meaning']) is str and definition['meaning'], 'complete importance-weight definitions required')
        session.file(definition['source'])
    source_species = next(s['llp_species'] for s in identity['components'] if s['id'] == c['id'])
    require([s['id'] for s in cohort['species']] == [s['id'] for s in source_species], 'complete source unstable-species population required')
    lengths = {}
    for s in cohort['species']:
        keys(s, ('id','ctau_mm')); lengths[s['id']] = number(s['ctau_mm'], True)
    sampling = cohort['sampling']; keys(sampling, ('decay_law','design','weight_unit','weight_convention','normalization_weight','divisor','complete_exposure','joint_second_moment','source'))
    session.file(sampling['source'])
    require(sampling['decay_law'] in ('independent_untruncated_exponential','forced_or_truncated','right_censored'), 'explicit source decay sampling law required')
    if sampling['decay_law'] != 'independent_untruncated_exponential':
        obligations.append('Forced/truncated/censored decay law needs an explicit supported joint sampling density and record-measurable selection; unconditional exponential ratio unavailable.')
        return result
    require(sampling['design'] in ('iid_fixed_N_groups','independent_Poisson_groups') and sampling['complete_exposure'] is True, 'complete declared generator-group design required')
    require(sampling['joint_second_moment'] in ('source_asserted_finite','unknown'), 'explicit joint importance-weight/selection moment status required')
    if sampling['weight_unit'] != 'dimensionless' or sampling['weight_convention'] != 'known_unit_mean_nominal_group_importance_mark':
        obligations.append('Weight units/convention needs a supported fixed original exposure or explicit shared-denominator law; no selected/reweighted denominator substitution.')
        return result
    require(sampling['normalization_weight'] == weight_names[0], 'first complete source-defined weight must be the declared nominal normalization weight')
    events = cohort['events']; require(type(events) is list and 1 <= len(events) <= 20000, 'complete bounded original event population required')
    require(len(events)*len(point['lifetimes'])*len(d['analysis']['bins']) <= 65536, 'complete lifetime/region trace budget exceeded before transformation; do not drop coordinates')
    ids = []; groups = []
    for e in events:
        keys(e, ('event_id','group_id','weights','llps'))
        require(all(type(e[k]) is str and e[k] for k in ('event_id','group_id')) and type(e['weights']) is dict and e['weights'], 'event/group/weight identity required')
        for v in e['weights'].values(): number(v)
        require(list(e['weights']) == weight_names, 'complete ordered source-defined weights required at every event')
        require(type(e['llps']) is list and len(e['llps']) <= 16, 'complete unstable-particle list required, including empty products')
        names(e['llps'], 16) if e['llps'] else None
        for p in e['llps']:
            keys(p, ('id','species','proper_length_mm'))
            require(p['species'] in lengths and number(p['proper_length_mm']) >= 0, 'nonnegative complete source proper lengths required')
        ids.append(e['event_id']); groups.append(e['group_id'])
    require(len(set(ids)) == len(ids), 'duplicate event; every zero-selection original row must remain')
    group_ids = list(dict.fromkeys(groups)); divisor = number(sampling['divisor'], True)
    require(sampling['design'] != 'iid_fixed_N_groups' or divisor == len(group_ids), 'known fixed-N divisor must count all original generator groups')
    width = len(events[0]['weights'])*len(point['lifetimes'])*len(d['analysis']['bins'])
    require(width <= 512 and (width+1)**2*len(group_ids) <= 2000000, 'complete same-group covariance budget exceeded before transformations')
    keys(response, ('schema_version','point_identity_sha256','component_id','cohort_sha256','region_ids','joint_states','events','record_measurable','selection_source','calibration_source'))
    require(response['schema_version'] == 1 and response['point_identity_sha256'] == point['identity']['sha256'] and response['component_id'] == c['id'] and response['cohort_sha256'] == c['cohort']['sha256'], 'response must bind this exact cohort and physical point')
    require(response['record_measurable'] is True, 'selection must be measurable from the retained complete decay/kinematic record')
    for k in ('selection_source','calibration_source'): session.file(response[k])
    regions = [b['id'] for b in d['analysis']['bins']]
    require(response['region_ids'] == regions, 'all source SR/CR regions required in their original order')
    state_ids = names(response['joint_states'], 64); masks = []
    for state in response['joint_states']:
        keys(state, ('id','regions')); require(type(state['regions']) is list and len(set(state['regions'])) == len(state['regions']) and state['regions'] == [r for r in regions if r in state['regions']], 'canonical complete joint region mask required')
        masks.append(tuple(state['regions']))
    require(len(set(masks)) == len(masks) and () in masks, 'distinct joint masks and explicit rejection state required')
    require(type(response['events']) is list and [e['event_id'] for e in response['events']] == ids, 'response cannot drop rejected or zero-weight events')
    allocations = []
    for e in response['events']:
        keys(e, ('event_id','state_probabilities')); probabilities = e['state_probabilities']
        require(type(probabilities) is dict and set(probabilities) == set(state_ids), 'full calibrated joint-state probability census required')
        for v in probabilities.values(): require(0 <= number(v) <= 1, 'joint response probability must be in [0,1]')
        require(abs(math.fsum(probabilities.values())-1) <= 1e-12, 'complete response simplex; no renormalization')
        allocations.append([math.fsum(probabilities[s['id']] for s in response['joint_states'] if r in s['regions']) for r in regions])
    all_rows = []; trace = []; tail = []
    for t in point['lifetimes']:
        target = {k:t['ctau_mm'][k] for k in lengths}; rows = []
        finite_ratio_moment = all(target[k] < 2*a for k,a in lengths.items())
        tail.append({'lifetime_id': t['id'], 'lifetime_factor_second_moment': 'finite' if finite_ratio_moment else 'unbounded_individual_exponential_ratio_second_moment_diverges_if_species_occurs', 'joint_weight_selection_second_moment': sampling['joint_second_moment'], 'finite_variance_qualified': False})
        for e, allocation in zip(events, allocations):
            value = lifetime_ratio(e['llps'], lengths, target)
            marks = [value['ratio']*x for x in allocation]
            require(all(math.isfinite(v) and (x == 0 or v > 0) for x,v in zip(allocation,marks)), 'response mark overflow/underflow; no zero substitution')
            rows.append({'event_id':e['event_id'],'group_id':e['group_id'],'weights':e['weights'],'allocation':marks})
            trace.append({'lifetime_id':t['id'],'event_id':e['event_id'],'group_id':e['group_id'],'original_weights':e['weights'],'proper_lengths':e['llps'],'conditional_region_probabilities':allocation, **value,'weighted_response_marks':marks})
        all_rows.append(rows)
    scale = c['rate']['sigma_pb']*c['rate']['branching_fraction']*d['analysis']['lumi_fb']*1000
    # A zero-rate component is still retained. The existing moment API needs a
    # positive scale; zero it only after the complete source population is read.
    request = {'weight_name':next(iter(events[0]['weights'])), 'normalization':{'scale':scale if scale > 0 else 1.,'denominator':'fixed','fixed_denominator':divisor},'anchors':[{'point':[i]} for i in range(len(all_rows))],'axes':[{'name':'lifetime_index'}],'reference_point':{'lifetime_index':0}}
    bundle = dr.summarize(request, regions, all_rows)
    normalized_groups = {}
    for g in group_ids:
        normalized_groups[g] = [scale/divisor*x for w in weight_names for x in bundle['group_marks'][w][g][:-1]]
    if sampling['design'] == 'iid_fixed_N_groups':
        estimate = mr.empirical_group_mean([normalized_groups[g] for g in group_ids], len(group_ids))
    else:
        raw = list(normalized_groups.values()); values = [math.fsum(r[i] for r in raw) for i in range(len(raw[0]))]
        covariance = [[math.fsum(r[i]*r[j] for r in raw) for j in range(len(raw[0]))] for i in range(len(raw[0]))]
        estimate = {'values':values,'covariance':covariance,'scope':'conditional_independent_Poisson_group_Gram_known_original_divisor','population_second_moment_established':False,'likelihood_inferred':False}
    result.update({'moments':estimate,'weight_names':weight_names,'weight_definitions':cohort['weight_definitions'],'group_ids':group_ids,'normalized_group_marks':normalized_groups,'original_exposure':{'event_count':len(events),'group_count':len(group_ids),'divisor':divisor,'weight_unit':sampling['weight_unit'],'weight_convention':sampling['weight_convention']},'sampling':sampling,'tail_status':tail,'raw_full_group_moments':bundle,'raw_moment_scope':'auxiliary positive-unit-scale surrogate for zero-rate component' if scale == 0 else 'conditional Poisson Gram; physical scale retained but sampling design is stated separately','physical_scale_sigma_BR_L':scale,'calibration_qualified':False})
    trace_pin = write(out/'lifetime-trace.json',trace); write(out/'component-moments.json',result)
    result['trace'] = trace_pin; return result


def _projection_workspace(workspace, signal_samples, factor, scenario):
    """Existing background law, with fixed-cohort signal MC errors scaling f."""
    from ravel.physics.project_limits import project_workspace
    allowed = {'histosys','normsys','staterror','shapesys','lumi','normfactor','shapefactor'}
    require(all(m['type'] in allowed for c in workspace['channels'] for s in c['samples'] for m in s['modifiers']), 'unsupported projection modifier; no silent unchanged nuisance')
    projected = project_workspace(workspace, factor, scenario)
    originals = {(c['name'],s['name']):s for c in workspace['channels'] for s in c['samples']}
    for c in projected['channels']:
        for s in c['samples']:
            if (c['name'],s['name']) in signal_samples:
                s['data'] = [factor*x for x in originals[c['name'],s['name']]['data']]
                # Background scaling assumptions cannot shrink the relative
                # MC or physics uncertainty of a reused signal sample.
                s['modifiers'] = deepcopy(originals[c['name'],s['name']]['modifiers'])
                for m in s['modifiers']:
                    if m['type'] in ('staterror','shapesys'): m['data'] = [factor*x for x in m['data']]
                    if m['type'] == 'histosys':
                        for k in ('hi_data','lo_data'): m['data'][k] = [factor*x for x in m['data'][k]]
    return projected


def execution_seconds(task, base): return 60


def run(task, base, output):
    d, session = _capture(task, base); original = [gen._generated_pin(p) for p in _expanded(d,session)]
    require(len(original) <= 32768 and sum(p['size'] for p in original) <= 512*1024**2, 'complete source recipe budget exceeded')
    out = Path(output).absolute(); require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)), 'fresh regular recipe output required')
    require(not any(Path(p['path']).is_relative_to(out) for p in original), 'output cannot contain original inputs')
    out.mkdir(parents=True); held = {}
    def bind(expected):
        path = expected['path']
        require(Path(path).is_absolute() and Path(path).is_relative_to(out) and (path not in held or held[path] == expected), 'generated recipe commitment differs')
        require(pin(path) == expected, 'generated recipe changed from intended bytes')
        held[path] = expected
    def write(path, document):
        expected = _json_commitment(path,document)
        require(expected['path'] not in held and not Path(path).exists(), 'fresh intended generated member required')
        # The commitment precedes the write, not an observed post-write stamp.
        held[expected['path']] = expected
        atomic_json(path,document)
        bind(expected)
        return expected
    def hold(root):
        paths = [p for p in sorted(Path(root).rglob('*')) if p.is_file()]
        require({str(p) for p in paths} == {p for p in held if Path(p).is_relative_to(root)}, 'uncommitted generated recipe membership')
        for path in paths:
            require(pin(path) == held[str(path)], 'generated recipe changed after its producer')
    result = {'schema_version':1,'kind':'llp-plane-recipe','status':'passed','status_scope':SCOPE,'goal_binding':d['goal_binding'],'analysis':d['analysis'],'axes':d['axes'],'points':[],'cells':[],'input_pins':original,'execution_authorized':False,'physics_validated':False,'original_task_complete':False,'generated_events':0,'fits':0,'assumptions':d['assumptions']}
    mixtures = {}
    try:
        for point in d['points']:
            identity = _doc(point['identity'],session); components = []
            for c in point['components']:
                dest = out/'points'/point['id']/c['id']; dest.mkdir(parents=True)
                components.append(_component(point,c,identity,d,session,dest,write,bind)); hold(dest)
            mixture = {'id':point['id'],'coordinate':point['coordinate'],'identity':point['identity'],'lifetimes':point['lifetimes'],'components':components,'obligations':[x for c in components for x in c['obligations']]}
            if d['mixture_sampling']['kind'] != 'independent_component_experiments' and len(components) > 1:
                mixture['obligations'].append('Shared/correlated component sampling requires a complete common joint group experiment; no independent-component covariance inferred.')
            if not mixture['obligations']:
                require(all(c['weight_definitions'] == components[0]['weight_definitions'] for c in components), 'all components must retain identical complete source-bound weight definitions; no positional mixing')
                first = components[0]['moments']; width = len(first['values'])
                mixture['values'] = [math.fsum(c['moments']['values'][i] for c in components) for i in range(width)]
                mixture['covariance'] = None if any(c['moments']['covariance'] is None for c in components) else [[math.fsum(c['moments']['covariance'][i][j] for c in components) for j in range(width)] for i in range(width)]
                mixture['weight_names'] = components[0]['weight_names']; mixtures[point['id']] = mixture
                require(all(math.isfinite(v) for v in mixture['values']) and (mixture['covariance'] is None or all(math.isfinite(v) for row in mixture['covariance'] for v in row)), 'mixed component moments overflow')
                mixture['moment_scope'] = 'sum_of_explicitly_independent_component_empirical_fixed_N_or_Poisson_estimates; no auxiliary likelihood or finite-variance certification'
            result['points'].append(mixture)
        for c in d['cells']:
            point = next(p for p in d['points'] if p['id'] == c['point_id']); scenario = next(s for s in d['projection_scenarios'] if s['id'] == c['projection_id'])
            idx = next(i for i,t in enumerate(point['lifetimes']) if t['id'] == c['lifetime_id']); n = len(d['analysis']['bins'])
            mixture = mixtures.get(point['id']); cell = {**c,'id':'--'.join(c[k] for k in ('point_id','lifetime_id','projection_id')),'state':'blocked','obligations':[],'inference_specification':None}
            if mixture is None: cell['obligations'].extend(next(p for p in result['points'] if p['id'] == point['id'])['obligations'])
            if d['analysis']['unresolved_bins']: cell['obligations'].append('Full fitted SR/CR population remains unresolved: '+str(d['analysis']['unresolved_bins']))
            if scenario['energy_tev'] != d['analysis']['energy_tev']: cell['obligations'].append('New beam energy requires exact new generation/response/model source; luminosity scaling cannot provide it.')
            factor = scenario['lumi_fb']/d['analysis']['lumi_fb']; number(factor,True)
            if mixture is not None:
                # Each named variation remains separate, not summed into yield.
                width = len(point['lifetimes'])*n
                cell['predictions'] = {w:[factor*x for x in mixture['values'][wi*width+idx*n:wi*width+(idx+1)*n]] for wi,w in enumerate(mixture['weight_names'])}
                cell['covariance_scale'] = factor*factor
                cell['joint_moments_location'] = {'point_id':point['id'],'lifetime_index':idx,'full_original_covariance_retained':True}
                cell['additional_source_cohort_requirements'] = []
                for comp in mixture['components']:
                    status = comp['tail_status'][idx]
                    if status['joint_weight_selection_second_moment'] != 'source_asserted_finite':
                        cell['obligations'].append('Joint weight/selection second moment is unknown; a finite empirical covariance cannot admit statistical uncertainty without its source-supported law.')
                    if status['lifetime_factor_second_moment'] != 'finite':
                        species = next(s['llp_species'] for s in _doc(point['identity'],session)['components'] if s['id'] == comp['id'])
                        cell['additional_source_cohort_requirements'].append({'point_id':point['id'],'component_id':comp['id'],'lifetime_id':c['lifetime_id'],
                            'unchanged_physical_identity':point['identity'],'target_ctau_mm':point['lifetimes'][idx]['ctau_mm'],
                            'required_new_source_ctau_mm_strictly_greater_than':{s['id']:point['lifetimes'][idx]['ctau_mm'][s['id']]/2 for s in species},
                            'required_stages':['source-bound parameter/decay card and sampling-law derivation','ordinary model-events generation with separate approval','complete charged/neutral joint response on new full exposure'],
                            'reason':'Unbounded lifetime-factor second moment diverges; finite observed moments/ESS do not establish variance. A certified compact selection support or complete mixture sampling density is an alternative source proof.'})
                if cell['additional_source_cohort_requirements']:
                    cell['obligations'].append('Additional same-model source lifetime cohorts or certified selection-tail support needed for finite-variance qualification; raw finite sample prediction is retained.')
            if c['published_model'] is None: cell['obligations'].append('Complete likelihood with all data, nuisance responses and auxiliary constraints required; scalar limits/postfit errors are insufficient.')
            if c['template'] is None: cell['obligations'].append('Complete mixed-signal SR/CR nominal and shared nuisance model required; tree-level gauge fractions do not construct acceptance.')
            if not cell['obligations']:
                source = pm.load_published_model(_doc(c['published_model'],session),Path(c['published_model']['path']).parent)
                template = _doc(c['template'],session)
                for q in [*template['grounding'],*[q for ch in template['channels'] for s in ch['samples'] for q in s['provenance']['evidence']]]: q['path'] = str(recipe.located(q,Path(c['template']['path']).parent))
                contract = st.build_signal_template(source,template,Path(c['template']['path']).parent)
                supplied = {(ch['name'],s['name'],i):v for ch in template['channels'] for s in ch['samples'] for i,v in enumerate(s['data'])}
                require(set(supplied) == {(b['channel'],b['sample'],b['index']) for b in d['analysis']['bins']}, 'complete mixed signal bins differ')
                nominal = mixture['weight_names'][0]
                require(all(supplied[b['channel'],b['sample'],b['index']] == mixture['values'][idx*n+i] for i,b in enumerate(d['analysis']['bins'])), 'template must equal exact original-exposure mixed lifetime prediction')
                dest = out/'cells'/cell['id']; dest.mkdir(parents=True)
                workspace = _projection_workspace(contract.workspace(),set((b['channel'],b['sample']) for b in d['analysis']['bins']),factor,scenario['background_scaling'])
                cell['workspace'] = write(dest/'projected-workspace.json',workspace)
                cell['projection_semantics'] = 'expected quantiles only; scaled observed entries are a proxy, not new observed data; source signal MC reused with f² covariance and f absolute errors'
                cell['state'] = 'scientific_inputs_constructed'
                # The ordinary template route can be prepared only at the
                # original exposure with its existing fully checked MC law.
                all_poisson = all(x['sampling']['design'] == 'independent_Poisson_groups' for x in mixture['components'])
                if factor == 1 and all_poisson:
                    rows = []; ws = mixture['weight_names']; groups = {}
                    for comp in mixture['components']:
                        for g,vector in comp['normalized_group_marks'].items(): groups[comp['id']+'/'+g] = vector
                    cov = mixture['covariance']; width = len(point['lifetimes'])*n
                    response = {'destination_ids':[b['id'] for b in d['analysis']['bins']],'anchors':[{'point':[i]} for i in range(len(point['lifetimes']))],'weight_name':nominal,'group_ids':list(groups),'group_marks':{nominal:{g:v[:width] for g,v in groups.items()}},'weights':{nominal:{'normalized_values':mixture['values'][:width],'conditional_group_covariance':[row[:width] for row in cov[:width]],'moment_scope':'conditional_independent_group_Poisson_Gram_fixed_denominator'}}}
                    try: prepared = recipe._template(d, c, response, {'coordinate':[idx]}, {'published_model':c['published_model']},session,dest,writer=write)
                    except ValueError as exc:
                        if 'expected template needs' not in str(exc) and 'correlated/cancelling bins' not in str(exc): raise
                        cell['obligations'].append(str(exc))
                    else:
                        spec = recipe._spec('signal-template',{'input':prepared['bridge']['path'],'operation':'inference'},d,_doc(d['inference_policy'],session),d['child_seconds']['inference'])
                        from ravel.workflow.science import validate as admit
                        admit(spec); cell['inference_specification'] = write(dest/'inference-science.json',spec)
                        cell['state'] = 'prepared_unapproved'
                else: cell['obligations'].append('Projected or fixed-N/correlated MC inference needs a source-supported full auxiliary/ordinary bridge; covariance is not a likelihood.')
                hold(dest)
            result['cells'].append(cell)
        result['prepared_cells'] = sum(c['state'] != 'blocked' for c in result['cells']); result['blocked_cells'] = len(result['cells'])-result['prepared_cells']
        session.finish(); require(original == [gen._generated_pin(p) for p in _expanded(d,session)],'complete source graph changed during construction'); hold(out)
        result['input_pins'] = original; result['output_inventory'] = [held[k] for k in sorted(held)]
        require(sum(p['size'] for p in result['output_inventory']) <= MAX_BYTES, 'complete recipe output budget exceeded')
        receipt_pin = write(out/'llp-plane-recipe.json',result)
        session.finish()
        hold(out)
        require(pin(receipt_pin['path']) == receipt_pin, 'ending final receipt changed from intended bytes')
        require(pin(out/'llp-plane-recipe.json')['size']+sum(p['size'] for p in result['output_inventory']) <= MAX_BYTES,'complete receipt budget exceeded')
        require(original == [gen._generated_pin(p) for p in _expanded(d,session)],'ending complete source graph changed')
        return result
    except Exception:
        if (out/'llp-plane-recipe.json').exists(): (out/'llp-plane-recipe.json').rename(out/'failed-llp-plane-recipe.json')
        raise
    finally: session.close()


def write_report(result, out):
    from ravel.workflow.validation_io import _source_pin_bytes
    for p in result['output_inventory']: _source_pin_bytes(p,limit=16*1024**2)
    dest = Path(out)/'llp-plane-report'; dest.mkdir(parents=True,exist_ok=False)
    atomic_json(dest/'cells.json',result['cells'])
    lines = ['# Supplied LLP model-plane construction','',SCOPE,'','Every requested model point, production component, lifetime and projection is retained. Charged calibration and likelihood assumptions require their source evidence. No new events, fit, exclusion or original-task acceptance.','','| Cell | State | Obligations |','|---|---|---|']
    for c in result['cells']: lines.append('| '+c['id']+' | '+c['state']+' | '+'; '.join(c['obligations']).replace('|','/')+' |')
    (dest/'report.md').write_text('\n'.join(lines)+'\n')
    return [{'id':'llp-full-plane','files':['llp-plane-report/cells.json','llp-plane-report/report.md'],'scope':SCOPE,'complete_cell_count':len(result['cells'])}]
