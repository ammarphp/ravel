"""Prospective five-vector CR-signal response qualification, with no fitting.

Import and document construction are inert. ``qualify`` is a scientific entry
point requiring separate approval. Tests inject a small arithmetic engine;
they never construct the official model. The scalar density shares compiled
main means, but assembles auxiliary Normal/Poisson terms independently.
"""
from copy import deepcopy
import hashlib
import json
import math
import time

from ravel.validation.cr_signal_switch import SWITCH, canonical, construct, require

LIMITS = {'seconds': 120, 'model_compilations': 3, 'vectors': 5,
          'evaluator_calls': 45, 'optimizer_calls': 0, 'generated_events': 0}
TOLERANCES = {'expected_atol': 1e-9, 'expected_rtol': 1e-10,
              'twice_nll_atol': 1e-7}
COMPONENTS = ('by_sample', 'expected', 'twice_nll')


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite nonboolean scalar required')
    return float(value)


def vectors(meta):
    """Initial plus four bounded simultaneous displacements; no adaptive points."""
    n = len(meta['names'])
    require(n == len(meta['inits']) == len(meta['bounds']) == len(meta['fixed']), 'Parameter dimensions differ')
    require(len(set(meta['names'])) == n, 'Parameter names must be unique')
    initial = [finite(x) for x in meta['inits']]
    for x, bounds in zip(initial, meta['bounds']):
        require(len(bounds) == 2 and finite(bounds[0]) <= x <= finite(bounds[1]), 'Initial point outside bounds')
    result = [{'label': 'initial', 'parameters': initial}]
    for amplitude in (0.125, -0.125, 0.25, -0.25):
        point = initial.copy()
        for i, (x, (lo, hi), fixed) in enumerate(zip(initial, meta['bounds'], meta['fixed'])):
            require(type(fixed) is bool, 'Literal fixed mask required')
            if fixed:
                continue
            # Shift from the initial point in an index-alternating direction,
            # with the smaller of an absolute relative scale and 1/8 box width.
            # At a physical boundary the opposite displacement is reflected.
            step = amplitude * (1 if i % 2 == 0 else -1) * min(max(1., abs(x)), (hi-lo)/8.)
            if not lo <= x+step <= hi:
                step = -step
            require(lo <= x+step <= hi, 'Prospective displacement is infeasible')
            point[i] = x+step
        result.append({'label': 'simultaneous_' + str(amplitude), 'parameters': point})
    return result


def projection(meta, original):
    """Exact original metadata after name-based alignment, plus one fixed factor."""
    require(set(meta['names']) == set(original['names']) | {SWITCH}, 'Only one new switch coordinate is allowed')
    idx = [meta['names'].index(name) for name in original['names']]
    for field in ('inits', 'bounds', 'fixed'):
        require([meta[field][i] for i in idx] == original[field], 'Original parameter ' + field + ' changed')
    for field in ('channels', 'channel_slices', 'samples', 'data', 'auxiliary', 'poi', 'modifier_settings'):
        require(meta[field] == original[field], 'Original ' + field + ' changed')
    constraint_specs=deepcopy(meta['constraint_specs'])
    require(constraint_specs.pop(SWITCH)=={'n_parameters':1,'constrained':False},'Switch must have no auxiliary constraint')
    require(constraint_specs==original['constraint_specs'],'Original parameter-set constraints changed')
    switch = meta['names'].index(SWITCH)
    require(meta['fixed'][switch] is True and meta['bounds'][switch] == [0., 1.], 'Switch must remain fixed in [0,1]')
    return idx, switch


def bind_original(meta, reference):
    """Literal retained compiled identity; no rewritten model/data hash accepted."""
    fields={'parameter_names':'names','bounds':'bounds','inits':'inits','fixed':'fixed',
            'channel_order':'channels','channel_slices':'channel_slices','sample_order':'samples',
            'observed_and_auxiliary_data':'data','constraints':'constraint_specs',
            'modifier_settings':'modifier_settings','model_compact_sha256':'model_compact_sha256'}
    for source,target in fields.items():
        require(reference[source]==meta[target],'Retained original compiled identity differs: '+source)
    require(reference['npars']==len(meta['names']) and reference['nauxdata']==len(meta['auxiliary']), 'Retained original dimensions differ')
    data=reference['observed_and_auxiliary_data']
    raw=json.dumps(data,separators=(',',':'),allow_nan=False).encode()
    require(hashlib.sha256(raw).hexdigest()==reference['data_compact_sha256'],'Original literal data digest differs')
    return {'model_compact_sha256':reference['model_compact_sha256'],
            'literal_data_compact_sha256':reference['data_compact_sha256'],'exact_values_order_bounds_mask_constraints':True}


def intervention(workspace, signal, all_controls):
    require(len(all_controls) == len(set(all_controls)), 'Control membership repeated')
    channels = {row['name']: row for row in workspace['channels']}
    require(set(all_controls) <= set(channels), 'Unknown control channel')
    rows = []
    for name in all_controls:
        matches = [s for s in channels[name]['samples'] if s['name'] == signal]
        require(len(matches) <= 1, 'Signal sample repeated')
        rows.append({'channel': name, 'signal_sample_present': bool(matches),
                     'nominal': deepcopy(matches[0]['data']) if matches else None})
    require(any(row['signal_sample_present'] for row in rows), 'At least one present CR signal is required')
    return rows


def response_flat_candidates(workspace, signal, controls, original):
    """Structural main-response possibilities, not numerical full-NLL flatness."""
    incidence = {}
    for channel in workspace['channels']:
        for sample in channel['samples']:
            for modifier in sample['modifiers']:
                incidence.setdefault(modifier['name'], []).append([channel['name'], sample['name']])
    result = []
    for name, locations in incidence.items():
        if all(channel in controls and sample == signal for channel, sample in locations):
            auxiliary = [row for row in original['auxiliary'] if row['parameter_set'] == name]
            result.append({'parameter_set': name, 'locations': locations,
                           'auxiliary_rows_retained': len(auxiliary),
                           'full_nll_flatness_established': False})
    return result


def poisson(n, mean):
    n, mean = finite(n), finite(mean)
    require(n >= 0 and mean >= 0 and (mean > 0 or n == 0), 'Invalid Poisson point')
    return 2.*(mean - (n*math.log(mean) if n else 0.) + math.lgamma(n+1.))


def independent_density(meta, point, expected):
    main = max(stop for _, stop in meta['channel_slices'].values())
    require(len(expected) == len(meta['data']) == main + len(meta['auxiliary']), 'Density dimensions differ')
    terms = [poisson(n, mu) for n, mu in zip(meta['data'][:main], expected[:main])]
    positions = {name:i for i,name in enumerate(meta['names'])}
    auxiliary_means = []
    for offset, row in enumerate(meta['auxiliary']):
        p = point[positions[row['parameter_name']]]
        observation = meta['data'][main+offset]
        if row['pdf'] == 'normal':
            sigma = finite(row['sigma'])
            require(sigma > 0, 'Normal width must be positive')
            auxiliary_means.append(p)
            terms.append(((observation-p)/sigma)**2 + 2.*math.log(sigma) + math.log(2.*math.pi))
        elif row['pdf'] == 'poisson':
            mean = p*finite(row['factor'])
            auxiliary_means.append(mean)
            terms.append(poisson(observation, mean))
        else:
            raise ValueError('Unknown auxiliary density')
    return math.fsum(terms), auxiliary_means, terms


def close(a, b):
    a, b = finite(a), finite(b)
    return abs(a-b) <= TOLERANCES['expected_atol'] + TOLERANCES['expected_rtol']*abs(b)


def compare(original, endpoints, metadata, points, present, signal):
    base = metadata['original']
    bins = [i for c in present for i in range(*base['channel_slices'][c])]
    si = base['samples'].index(signal)
    main = max(stop for _,stop in base['channel_slices'].values())
    checks = []
    for arm in ('one', 'zero'):
        values = endpoints[arm]
        rows = values['by_sample']
        old = original['by_sample']
        require(len(rows) == len(old) == len(base['samples']), 'Sample axis differs')
        require(all(len(row) == main for row in [*rows, *old]), 'Bin axis differs')
        for sample in range(len(rows)):
            for i in range(main):
                expected = 0. if arm == 'zero' and sample == si and i in bins else old[sample][i]
                # The factor-zero condition is literal, not a widened tolerance.
                require(rows[sample][i] == 0. if expected == 0. and arm == 'zero' and sample == si and i in bins else close(rows[sample][i], expected), 'Per-sample response differs: ' + arm)
        expected = original['expected'].copy()
        if arm == 'zero':
            for i in bins:
                expected[i] -= old[si][i]
        require(len(values['expected']) == len(expected) and all(close(a,b) for a,b in zip(values['expected'],expected)), 'Main/auxiliary response differs: ' + arm)
        require(all(close(sum(row[i] for row in rows),values['expected'][i]) for i in range(main)), 'Per-sample sum differs')
        scalar, auxiliary, terms = independent_density(metadata[arm], points[arm], values['expected'])
        require(all(close(a,b) for a,b in zip(auxiliary, values['expected'][main:])), 'Independent auxiliary means differ')
        require(abs(scalar-finite(values['twice_nll'])) <= TOLERANCES['twice_nll_atol'], 'Independent full density differs')
        predicted = original['twice_nll'] + math.fsum(poisson(base['data'][i], expected[i]) - poisson(base['data'][i],original['expected'][i]) for i in bins)
        require(abs(predicted-values['twice_nll']) <= TOLERANCES['twice_nll_atol'], 'NLL difference contains an undeclared change')
        checks.append({'arm':arm,'independent_twice_nll':scalar,'terms':terms,
                       'auxiliary_means':auxiliary,'predicted_twice_nll':predicted,
                       'signed_nll_residual':values['twice_nll']-predicted,'passed':True})
    scalar, auxiliary, terms = independent_density(base, points['original'], original['expected'])
    require(abs(scalar-finite(original['twice_nll'])) <= TOLERANCES['twice_nll_atol'], 'Original independent density differs')
    require(all(close(a,b) for a,b in zip(auxiliary,original['expected'][main:])), 'Original auxiliary means differ')
    return {'checks':checks,'original_independent_twice_nll':scalar,'original_terms':terms,'passed':True}


def qualify(workspace, *, measurement, signal, all_controls, original_reference, engine, persist, clock=time.monotonic):
    """Run only after scientific admission; retain each compile/call before next."""
    started = clock()
    report = {'status':'running','scope':'five_vector_CR_signal_response_qualification',
              'physics_validated':False,'limits':LIMITS.copy(),'tolerances':TOLERANCES.copy(),
              'compilations':[],'calls':[],'rows':[],'error':None,'passed':False}
    def save():
        persist(deepcopy(report))
    def tick():
        require(clock()-started <= LIMITS['seconds'], 'Numerical qualification deadline exceeded')
    def work(kind, label, fn, field):
        tick()
        item = {'kind':kind,'label':label,'status':'running'}
        report[field].append(item);save()
        try:
            result = fn()
            item.update(status='completed',result=result if kind != 'compile' else engine.describe(result))
            save();tick()
            return result
        except Exception as error:
            if item['status'] != 'completed':
                item.update(status='failed',error={'type':type(error).__name__,'message':str(error)})
            save();raise
    try:
        membership = intervention(workspace,signal,all_controls)
        report['control_membership'] = membership
        present = [row['channel'] for row in membership if row['signal_sample_present']]
        documents = {'original':workspace,'one':construct(workspace,signal_name=signal,control_channels=present,measurement_name=measurement,level=1),
                     'zero':construct(workspace,signal_name=signal,control_channels=present,measurement_name=measurement,level=0)}
        models = {};metadata = {}
        for arm, document in documents.items():
            models[arm] = work('compile',arm,lambda d=document:engine.compile(d,measurement),'compilations')
            metadata[arm] = report['compilations'][-1]['result']
            if arm=='original':
                report['original_reference_identity']=bind_original(metadata[arm],original_reference);save()
        report['metadata'] = metadata;save()
        maps = {arm:projection(metadata[arm],metadata['original']) for arm in ('one','zero')}
        require(metadata['one']['inits'][maps['one'][1]] == 1. and metadata['zero']['inits'][maps['zero'][1]] == 0., 'Fixed endpoint differs')
        report['potential_main_response_flat_sets'] = response_flat_candidates(workspace,signal,present,metadata['original'])
        for vector in vectors(metadata['original']):
            points = {'original':vector['parameters']};values={}
            row = {'label':vector['label'],'status':'running','parameters':points,'values':values}
            report['rows'].append(row);save()
            for arm in documents:
                if arm != 'original':
                    point = metadata[arm]['inits'].copy()
                    for old,new in enumerate(maps[arm][0]):point[new] = vector['parameters'][old]
                    points[arm] = point
                values[arm] = {}
                for component in COMPONENTS:
                    require(len(report['calls']) < LIMITS['evaluator_calls'], 'Evaluator call ceiling exceeded')
                    value = work(component,vector['label']+'/'+arm,
                                 lambda a=arm,c=component:engine.evaluate(models[a],points[a],c),'calls')
                    values[arm][component] = value;save()
            row['comparison'] = compare(values['original'],{k:values[k] for k in ('one','zero')},metadata,points,present,signal)
            row['status'] = 'passed';save()
        require(len(report['calls']) == 45 and len(report['compilations']) == 3, 'Work denominator differs')
        tick();report.update(status='completed',passed=True)
    except Exception as error:
        report.update(status='failed',error={'type':type(error).__name__,'message':str(error)})
    report['elapsed_seconds'] = clock()-started;save()
    return report


class PyhfEngine:
    """Explicit scientific engine; construction alone does not compile a model."""
    def compile(self, workspace, measurement):
        import pyhf
        from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
        pyhf.set_backend('numpy',precision='64b')
        ws = pyhf.Workspace(deepcopy(workspace))
        model = ws.model(measurement_name=measurement,modifier_settings=MODIFIER_SETTINGS)
        return model,[float(v) for v in ws.data(model)]

    def describe(self, bundle):
        from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
        model,data = bundle;c=model.config;aux=[];specs={}
        for name in c.par_order:
            ps=c.param_set(name)
            specs[name]={key:getattr(ps,key) for key in ('n_parameters','constrained','auxdata','sigmas','factors','pdf_type') if hasattr(ps,key)}
        for name in c.auxdata_order:
            ps=c.param_set(name);section=c.par_map[name]['slice']
            for j,i in enumerate(range(section.start,section.stop)):
                aux.append({'parameter_set':name,'parameter_name':c.par_names[i],
                            'pdf':ps.pdf_type,'sigma':float(getattr(ps,'sigmas',[1.]*ps.n_parameters)[j]) if ps.pdf_type=='normal' else None,
                            'factor':float(ps.factors[j]) if ps.pdf_type=='poisson' else None})
        return {'names':c.par_names,'inits':[float(v) for v in c.suggested_init()],
                'bounds':[[float(v) for v in pair] for pair in c.suggested_bounds()],
                'fixed':[bool(v) for v in c.suggested_fixed()], 'channels':c.channels,
                'channel_slices':{n:[s.start,s.stop] for n,s in c.channel_slices.items()},
                'samples':c.samples,'data':data,'auxiliary':aux,'poi':c.poi_name,
                'constraint_specs':json.loads(json.dumps(specs,allow_nan=False)),
                'modifier_settings':deepcopy(MODIFIER_SETTINGS),
                'model_compact_sha256':hashlib.sha256(canonical(model.spec)).hexdigest()}

    def evaluate(self,bundle,point,component):
        model,data=bundle
        if component=='by_sample':return model.main_model.expected_data(point,return_by_sample=True).tolist()
        if component=='expected':return model.expected_data(point).tolist()
        if component=='twice_nll':return float(-2.*model.logpdf(point,data)[0])
        raise ValueError('Unknown numerical component')
