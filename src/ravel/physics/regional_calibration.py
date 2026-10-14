"""Fixed-truth repeated data and bounded profiles of a complete regional law.

No ROOT import. Native execution receives the already admitted ROOT facade and
reuses regional_expected's optimizer and raw RooFitResult reader unchanged.
"""
from fractions import Fraction
from pathlib import Path
import hashlib
import importlib
import importlib.util
import json
import math
import os
import stat
import random
import sys
import time

KIND = 'regional-full-auxiliary-calibration/v1'
ESTIMAND = 'pointwise_two_sided_profile_lr_inclusion'

# A finite copied source package, conditional on admitted shape terms. The
# existing fraction kernels and exact parser dependencies supply native means;
# no callback or host-installed RAVEL package does.
SHAPE_SOURCE_MEMBERS = ('__init__.py', 'physics/__init__.py',
    'workflow/__init__.py', 'workflow/state_io.py', 'physics/eft_functions.py',
    'physics/parametric_shapes.py', 'physics/continuous_dijet_shapes.py',
    'physics/statistical_construction.py')
SHAPE_SOURCE_MAX_BYTES = 8 * 1048576
SHAPE_SOURCE_KIND = 'regional-calibration-shape-source/v1'
SUPPORTED_SHAPES = ('normalized_exponential', 'normalized_power', 'normalized_dijet')


def shape_source_paths(d):
    if not any('shape' in term for term in d['terms']):
        return []
    from ravel.physics import statistical_construction
    package = Path(statistical_construction.__file__).resolve().parents[1]
    return [package / name for name in SHAPE_SOURCE_MEMBERS]


def check_shape_sources(root, binding, *, imported=True, capture=False):
    """Authenticate the fixed copied package and, after import, exact origins."""
    keys(binding, ('kind', 'files'), 'shape source binding')
    require(binding['kind'] == SHAPE_SOURCE_KIND and type(binding['files']) is dict
            and set(binding['files']) == set(SHAPE_SOURCE_MEMBERS), 'shape source members differ')
    bundle = Path(root) / 'ravel_calibration_source'
    package = bundle / 'ravel'
    allowed_files = {'ravel/' + name for name in SHAPE_SOURCE_MEMBERS}
    allowed_dirs = {'ravel', 'ravel/physics', 'ravel/workflow'}
    identity = lambda v: (v.st_dev,v.st_ino,v.st_mode,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    def census(authenticated=None):
        require(not any(p.is_symlink() for p in (bundle, *bundle.parents)) and
                stat.S_ISDIR(bundle.lstat().st_mode), 'ordinary shape source directory required')
        seen = set()
        for path in bundle.rglob('*'):
            name = path.relative_to(bundle).as_posix(); st = path.lstat()
            require(name in allowed_files | allowed_dirs and not path.is_symlink() and
                    (stat.S_ISDIR(st.st_mode) if name in allowed_dirs else stat.S_ISREG(st.st_mode)),
                    'unbound shape source package member')
            if authenticated is not None and name in allowed_files:
                require(identity(st) == authenticated[name], 'shape source ending identity changed')
            seen.add(name)
        require(seen == allowed_files | allowed_dirs, 'shape source package census differs')
    census()
    authenticated = {}
    buffers = {}
    for name, pin in binding['files'].items():
        keys(pin, ('sha256', 'bytes'), 'shape source member')
        require(type(pin['sha256']) is str and len(pin['sha256']) == 64 and
                all(c in '0123456789abcdef' for c in pin['sha256']) and
                type(pin['bytes']) is int and 0 < pin['bytes'] <= 1048576, 'bounded shape source pin required')
        path = package / name
        require(not any(p.is_symlink() for p in (path, *path.parents)), 'shape source traverses symlink')
        observed = path.lstat()
        require(stat.S_ISREG(observed.st_mode) and observed.st_size == pin['bytes'], 'shape source is not its declared regular file')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            opened = os.fstat(fd)
            require(stat.S_ISREG(opened.st_mode), 'opened shape source must be regular')
            raw = b''
            while len(raw) <= pin['bytes']:
                part = os.read(fd, pin['bytes'] + 1 - len(raw))
                if not part: break
                raw += part
            ending = os.fstat(fd)
        finally:
            os.close(fd)
        require(identity(observed) == identity(opened) == identity(ending) == identity(path.lstat()) and
                len(raw) == pin['bytes'] and hashlib.sha256(raw).hexdigest() == pin['sha256'], 'shape source bytes changed')
        buffers[name] = raw
        authenticated['ravel/' + name] = identity(observed)
    require(sum(len(raw) for raw in buffers.values()) <= SHAPE_SOURCE_MAX_BYTES,
            'shape source closed aggregate bound exceeded')
    if imported:
        for name in SHAPE_SOURCE_MEMBERS:
            module_name = 'ravel' + ('.' + name[:-3].replace('/', '.') if name != '__init__.py' else '')
            if module_name.endswith('.__init__'): module_name = module_name[:-9]
            module = sys.modules.get(module_name)
            require(module is not None and Path(module.__file__).resolve() == (package/name).resolve(), 'shape source import origin differs')
    # Reading the final member is itself inside this observation. Recheck the
    # whole namespace after all reads/origins, including earlier leaf identities.
    # This is a finite ending checkpoint, not a filesystem lock.
    census(authenticated)
    return (package, buffers) if capture else package


def bind_shape_sources(root, binding):
    """Load only this closed authenticated package in the isolated native worker."""
    package, buffers = check_shape_sources(root, binding, imported=False, capture=True)
    require(not any(n == 'ravel' or n.startswith('ravel.') for n in sys.modules),
            'native shape source namespace already imported')
    old = sys.dont_write_bytecode; sys.dont_write_bytecode = True
    loaded = []
    try:
        # Name every member before any member runs. An import statement inside a
        # member, including a package initializer probing for a module this closed
        # copy does not carry, then resolves to these objects or to nothing. The
        # import system never loads a staged file by path in place of its buffer.
        staged = []
        for name in SHAPE_SOURCE_MEMBERS:
            module_name = 'ravel' + ('.' + name[:-3].replace('/', '.') if name != '__init__.py' else '')
            if module_name.endswith('.__init__'): module_name = module_name[:-9]
            path = package/name
            options = {'submodule_search_locations':[str(path.parent)]} if name.endswith('__init__.py') else {}
            spec = importlib.util.spec_from_file_location(module_name, path, **options)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module; loaded.append(module_name)
            if '.' in module_name:
                parent, child = module_name.rsplit('.', 1)
                setattr(sys.modules[parent], child, module)
            staged.append((name, path, module))
        for name, path, module in staged:
            # Execute the same authenticated buffer, never a second path read.
            exec(compile(buffers[name], str(path), 'exec'), module.__dict__)
        require(sorted(n for n in sys.modules if n == 'ravel' or n.startswith('ravel.')) == sorted(loaded),
                'native shape source imported a module outside its bound members')
        check_shape_sources(root, binding)
    except BaseException:
        for name in reversed(loaded): sys.modules.pop(name, None)
        raise
    finally:
        sys.dont_write_bytecode = old


# Local source-reference reservations. These are neither native RooIntegrator
# calls nor fit/wall-time bounds; no state or cache survives an operation.
MAX_RESERVED_REFERENCE_EVALUATIONS = 100000000
REFERENCE_SEMANTICS = 'adaptive Simpson/Richardson estimates, not certified bounds'


def has_dijet(d):
    return any(t.get('shape', {}).get('kind') == 'normalized_dijet' for t in d['terms'])


def reference_policy(request, d):
    require('reference_budget' in request and 'reference_admissibility' in request, 'explicit dijet reference policy required')
    keys(request['reference_budget'], ('admission_reserved_evaluations', 'toy_reserved_evaluations', 'validation_reserved_evaluations'), 'reference budget')
    minimum = sum(t['shape']['integration']['reference']['max_evaluations'] for t in d['terms'] if t.get('shape',{}).get('kind') == 'normalized_dijet')
    for value in request['reference_budget'].values():
        require(type(value) is int and minimum <= value <= MAX_RESERVED_REFERENCE_EVALUATIONS,
                'finite reference reservation must admit one complete mean evaluation')
    keys(request['reference_admissibility'], ('fraction_of_existing_mean_band', 'fraction_of_existing_nll_band', 'fraction_of_existing_q_margin'), 'reference admissibility')
    for value in request['reference_admissibility'].values():
        require(0 < number(value) <= Fraction(1,10) and float(number(value)) > 0,
                'prospective estimated-accuracy fractions must be representable and at most 1/10')


class ReferenceAudit:
    """Reserve BEFORE each exact reference invocation, including failed calls.

    The public evidence dictionary is attached to the existing journal/row by
    execute. A checkpoint callback commits the reservation before evaluation.
    Kernel exceptions cannot supply a consumed count: it remains None.
    """
    def __init__(self, request, d, phase, checkpoint=None):
        require(has_dijet(d), 'reference audit is only for admitted dijet terms')
        reference_policy(request,d)
        require(phase in ('admission','toy','validation'), 'reference phase differs')
        self.truth_means = []
        self.request = request
        self.checkpoint = checkpoint
        self.evidence = {'phase':phase, 'maximum_reserved_evaluations':request['reference_budget'][phase+'_reserved_evaluations'],
                         'reserved_evaluations':0, 'known_successful_evaluations':0, 'calls':[], 'mean_checks':[],
                         'error_semantics':REFERENCE_SEMANTICS, 'native_integral_and_fit_cost':'not_measured_by_source_reference_meter'}

    def save(self):
        if self.checkpoint is not None: self.checkpoint()

    def reference(self, term, shape, coefficients, point):
        from ravel.physics import continuous_dijet_shapes as kernel
        ceiling = shape['integration']['reference']['max_evaluations']
        entry = {'term':term, 'point':{k:str(v) for k,v in point.items()}, 'effective_coefficients':[str(v) for v in coefficients],
                 'settings':shape['integration']['reference'], 'reserved_evaluations':0, 'actual_evaluations':None, 'status':'reservation_unavailable'}
        self.evidence['calls'].append(entry)
        if self.evidence['reserved_evaluations'] + ceiling > self.evidence['maximum_reserved_evaluations']:
            self.save(); raise ValueError('source reference reservation unavailable; no quadrature invoked')
        entry.update(reserved_evaluations=ceiling,status='reserved')
        self.evidence['reserved_evaluations'] += ceiling; self.save()
        try:
            result = kernel.reference(shape,coefficients)
            require(type(result['evaluations']) is int and 0 < result['evaluations'] <= ceiling and
                    result['error_semantics'] == REFERENCE_SEMANTICS and result['clipping_applied'] is False,
                    'reference diagnostics differ from admitted source')
            require(len(result['estimated_probability_error']) == len(shape['bin_windows']), 'complete reference error population required')
            require(all(finite(v,'estimated probability error') >= 0 for v in result['estimated_probability_error']), 'negative reference error estimate')
            entry.update(status='returned',actual_evaluations=result['evaluations'],result=result)
            self.evidence['known_successful_evaluations'] += result['evaluations']; self.save()
            return result
        except Exception as exc:
            entry.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
            self.save(); raise


def estimated_nll_error(expectation, errors, counts):
    """Poisson sensitivity applied to estimates, never a certified error bound."""
    keys(errors,expectation,'complete estimated mean errors');keys(counts,expectation,'complete NLL counts')
    pieces = []
    for name,mu in expectation.items():
        error=finite(errors[name],'estimated mean error');n=counts[name]
        require(type(n) is int and n >= 0 and 0 <= error < mu, 'estimated positive-mean interval unresolved')
        pieces.append((1+n/(mu-error))*error)
    return finite(math.fsum(pieces),'estimated NLL error')


def reference_admission(request, d):
    audit=ReferenceAudit(request,d,'admission')
    try:
        validate(request,d,reference=audit)
    except ValueError as exc:
        # Ordinary configuration/packet errors retain a located, bounded audit
        # in the actual error payload; no unavailable work count is guessed.
        raise ValueError(str(exc)+'; RAVEL_REFERENCE_ADMISSION='+json.dumps(audit.evidence,sort_keys=True,allow_nan=False)) from exc
    return {'truth_means':audit.truth_means, 'reference_audit':audit.evidence,
            'estimated_reference_uncertainty_is_certified':False}


def _shape_fractions(d, values, *, reference=None):
    shapes = [(i,t['shape']) for i,t in enumerate(d['terms']) if 'shape' in t]
    if not shapes: return {}, {}
    from ravel.physics import parametric_shapes, continuous_dijet_shapes
    theta=[values[n] for n in d['auxiliary']['names']];result={};errors={}
    for i,shape in shapes:
        require(type(shape) is dict and shape.get('kind') in SUPPORTED_SHAPES, 'unknown continuous calibration shape family')
        if shape['kind'] == continuous_dijet_shapes.KIND:
            require(isinstance(reference,ReferenceAudit), 'explicit prospective reference audit required for dijet evaluation')
            continuous_dijet_shapes.validate(shape,d['parameters'],d['auxiliary'],len(d['bins']))
            coefficients=continuous_dijet_shapes.effective_parameters(shape,values,theta)
            diagnostic=reference.reference(d['terms'][i]['id'],shape,coefficients,values)
            fractions=diagnostic['fractions'];errors[i]=diagnostic['estimated_probability_error']
        else:
            parametric_shapes.validate(shape,d['parameters'],d['auxiliary'],len(d['bins']))
            slope=parametric_shapes.effective_slope(shape,values,theta)
            fractions,_=parametric_shapes.fractions(shape,slope)
        require(len(fractions)==len(d['bins']), 'complete shape fractions required')
        for b,fraction in enumerate(fractions):
            finite(fraction,'shape fraction')
            require(0 <= fraction <= 1 and (shape['bin_windows'][b] is None)==(not number(d['terms'][i]['coefficients'][b])), 'shape support differs from source coefficients')
        result[i]=fractions
    return result,errors


def shape_description(d):
    shapes = [{'term':t['id'], 'shape':t['shape']} for t in d['terms'] if 'shape' in t]
    if not shapes:
        return None
    return {'terms':shapes, 'source_members':list(SHAPE_SOURCE_MEMBERS),
            'normalization':'Full declared domain; missing windows retain unobserved mass, no observed-bin renormalization.',
            'reference_dependency':'Shared admitted fraction kernels; host/source agreement is internal consistency, not independent native numerical validation.',
            'sampling':'Original disjoint Poisson counts at fixed complete truth; original conditional/unconditional MC and Gaussian auxiliary experiment.'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys(value, fields, name):
    require(type(value) is dict and set(value) == set(fields), name+' fields differ')


def number(value):
    require(type(value) is str, 'exact rational source number required')
    q = Fraction(value)
    require(math.isfinite(float(q)), 'finite source number required')
    return q


def finite(value, name):
    require(type(value) in (int, float) and math.isfinite(value), 'nonfinite '+name)
    return float(value)


def coordinates(d):
    return [p['name'] for p in d['parameters']] + ['ravel_aux_'+str(i) for i in range(len(d['auxiliary']['names']))]


def means(d, point, *, reference=None):
    """Literal polynomial/exponential TOTAL, including every MC count channel.

    Admitted continuous fractions multiply each signed source term. All SR/CR/MC
    bins remain in the original count experiment; unobserved domain mass is not
    renormalized into the observed bins. Shared kernels are internal consistency,
    not independent native numerical validation.
    """
    keys(point, coordinates(d), 'full parameter state')
    q = {n: Fraction(v) for n, v in point.items()}
    aux = d['auxiliary']
    values = {**q, **{n: number(aux['observed'][i]) + sum((number(a)*q['ravel_aux_'+str(j)] for j, a in enumerate(aux['factor'][i])), Fraction()) for i, n in enumerate(aux['names'])}}
    shape_fractions, probability_errors = _shape_fractions(d, values, reference=reference)
    result = {}; mean_errors = {}; contributions = {}
    for b, bin_ in enumerate(d['bins']):
        pieces = []; error_pieces = []; terms = []
        for t, term in enumerate(d['terms']):
            coefficient = number(term['coefficients'][b])
            if not coefficient:
                pieces.append(0.)
                continue
            monomial = coefficient * math.prod(values[n] ** k for n, k in term['powers'].items())
            exponent = sum((number(a)*values[n] for a, n in zip(term['log_response'][b], aux['names'])), Fraction())
            piece = float(monomial)*math.exp(float(exponent))
            pieces.append(piece * shape_fractions[t][b] if t in shape_fractions else piece)
            if t in probability_errors:
                estimate = abs(piece) * probability_errors[t][b]
                error_pieces.append(estimate)
                terms.append({'term':term['id'],'signed_full_domain_coefficient':piece,
                              'estimated_probability_error':probability_errors[t][b], 'absolute_estimated_mean_contribution':estimate})
        value = finite(math.fsum(pieces), 'total mean')
        require(value > 0, 'strictly positive TOTAL count mean required')
        result[bin_['id']] = value
        mean_errors[bin_['id']] = finite(math.fsum(error_pieces),'estimated TOTAL mean error')
        contributions[bin_['id']] = terms
    if has_dijet(d):
        check={'point':{n:str(q[n]) for n in coordinates(d)},'means':result,'estimated_mean_error':mean_errors,
               'absolute_signed_term_contributions':contributions, 'status':'unresolved'}
        reference.evidence['mean_checks'].append(check); reference.save()
        fraction=float(number(reference.request['reference_admissibility']['fraction_of_existing_mean_band']))
        require(all(mean_errors[n] < result[n] and mean_errors[n] <= fraction*1e-10*(1+abs(result[n])) for n in result),
                'estimated TOTAL mean accuracy screen failed; existing mean band unchanged')
        check['status']='admissible_estimate'; reference.save()
    return result


def validate(request, d, *, reference=None, _native_graph=False):
    if not _native_graph and any('shape' in t for t in d['terms']):
        require(all(type(t['shape']) is dict and t['shape'].get('kind') in SUPPORTED_SHAPES for t in d['terms'] if 'shape' in t), 'explicit supported calibration shape required')
        # The ordinary full-law validator owns background/component support,
        # parameter domains and independent MC auxiliaries. Do not reopen them.
        from ravel.physics import statistical_construction
        statistical_construction.validate(d)
    fields = ('kind', 'estimand', 'source', 'statement', 'truths', 'trials_per_truth', 'auxiliary_mode', 'seed', 'critical_q', 'confidence_level', 'numerical_margin', 'nll_absolute_tolerance', 'nll_relative_tolerance', 'reservation_seconds_per_toy', 'maximum_unresolved_fraction')
    if not _native_graph and has_dijet(d):
        fields += ('reference_budget','reference_admissibility')
    keys(request,fields,'calibration request')
    if not _native_graph and has_dijet(d):
        reference_policy(request,d)
        reference = reference or ReferenceAudit(request,d,'admission')
        reference.truth_means.clear()
    require(request['kind'] == KIND and request['estimand'] == ESTIMAND, 'only predeclared pointwise two-sided profile LR supported')
    require(request['source'] in {s['id'] for s in d['sources']} and type(request['statement']) is str and request['statement'].strip(), 'located repeated-sampling premise required')
    require('expected_data' not in d and all(type(b['observed']) is int and b['observed'] >= 0 for b in d['bins']), 'complete supplied integer observations required')
    require(d['partition']['kind'] == 'declared_disjoint_poisson_counts', 'independent count experiment required')
    require(not next(p for p in d['parameters'] if p['role']=='poi')['fixed'], 'profile LR requires a floating source POI')
    require(d['template_statistics']['kind'] in ('conditional_on_supplied_coefficients', 'explicit_independent_poisson_auxiliary'), 'fixed-N/signed MC cannot be replaced by Poisson auxiliaries')
    require(request['auxiliary_mode'] in ('conditional', 'unconditional'), 'explicit auxiliary conditioning policy required')
    require(type(request['seed']) is int and 0 <= request['seed'] < 2**64, 'bounded integer master seed required')
    require(type(request['trials_per_truth']) is int and 1 <= request['trials_per_truth'] <= 1024, 'fixed nonzero scheduled toy denominator required')
    truths = request['truths']
    require(type(truths) is list and 1 <= len(truths) <= 32 and len(truths)*request['trials_per_truth'] <= 2048, 'bounded full truth population required')
    ids = set(); states = set()
    for truth in truths:
        keys(truth, ('id', 'point'), 'truth')
        require(type(truth['id']) is str and truth['id'].isalnum() and truth['id'] not in ids, 'unique truth identity required'); ids.add(truth['id'])
        keys(truth['point'], coordinates(d), 'complete fixed truth')
        q = {n: number(v) for n, v in truth['point'].items()}
        signature = tuple(q[n] for n in coordinates(d))
        require(signature not in states, 'duplicate physical truth'); states.add(signature)
        for p in d['parameters']:
            require(number(p['bounds'][0]) <= q[p['name']] <= number(p['bounds'][1]) and (not p['fixed'] or q[p['name']] == number(p['initial'])), 'truth changes source bound/fixed value')
        for i, bounds in enumerate(d['auxiliary']['eta_bounds']):
            require(number(bounds[0]) <= q['ravel_aux_'+str(i)] <= number(bounds[1]), 'truth outside fixed physical auxiliary domain')
        if not _native_graph:
            truth_means = means(d,truth['point'],reference=reference)
            require(all(v <= 1000 for v in truth_means.values()), 'Poisson generation mean exceeds declared finite algorithm scope')
            if has_dijet(d): reference.truth_means.append({'truth_id':truth['id'],'point':truth['point'],'means':truth_means})
    require(number(request['critical_q']) >= 0 and 0 < number(request['confidence_level']) < 1 and 0 < float(number(request['confidence_level'])) < 1, 'predeclared cutoff/confidence representable in binary64 required')
    for name in ('numerical_margin', 'nll_absolute_tolerance', 'nll_relative_tolerance'):
        require(number(request[name]) > 0 and float(number(request[name])) > 0, 'positive representable predeclared numerical closure margin required')
    require(0 <= number(request['maximum_unresolved_fraction']) <= 1 and type(request['reservation_seconds_per_toy']) is int and 1 <= request['reservation_seconds_per_toy'] <= 900, 'declared unresolved tolerance/time reservation required')
    return request


def seed_for(request, truth_id, ordinal, component):
    raw = json.dumps([request['seed'], truth_id, ordinal, component], separators=(',', ':'), ensure_ascii=True).encode()
    return int.from_bytes(hashlib.sha256(raw).digest(), 'big')


def poisson(mean, rng):
    """Independent Poisson superposition, Knuth submeans <=32; no normal shortcut.

    A finite iteration refusal remains an unresolved scheduled toy, never redraw.
    """
    require(0 < finite(mean, 'Poisson mean') <= 1000, 'bounded positive Poisson mean required')
    chunks = math.ceil(mean/32); value = 0
    for _ in range(chunks):
        threshold = math.exp(-mean/chunks); product = 1.; count = 0
        while count == 0 or product > threshold:
            require(count < 10000, 'Poisson generator iteration budget exhausted')
            product *= rng.random(); count += 1
        value += count-1
    return value


def toy(request, d, truth, ordinal, *, reference=None, _graph_law=None):
    """One complete same-toy dataset; never draw parameters from constraints."""
    reference = reference or (ReferenceAudit(request,d,'toy') if _graph_law is None and has_dijet(d) else None)
    full_means = means(d, truth['point'],reference=reference) if _graph_law is None else _graph_law.begin_toy(_graph_law.current_row,truth); counts = {}; seeds = {}
    for b in d['bins']:
        component = 'count:'+b['id']; seed = seed_for(request, truth['id'], ordinal, component); seeds[component] = str(seed)
        counts[b['id']] = (b['observed'] if b['role'] == 'mc_auxiliary' and request['auxiliary_mode'] == 'conditional' else poisson(full_means[b['id']], random.Random(seed)) if _graph_law is None else _graph_law.poisson(full_means[b['id']],random.Random(seed),b['id']))
    globals_ = {}
    for i in range(len(d['auxiliary']['names'])):
        component = 'gaussian:'+str(i); seed = seed_for(request, truth['id'], ordinal, component); seeds[component] = str(seed)
        value = 0. if request['auxiliary_mode'] == 'conditional' else float(number(truth['point']['ravel_aux_'+str(i)])) + random.Random(seed).gauss(0., 1.)
        globals_['ravel_aux_'+str(i)+'_In'] = finite(value, 'Gaussian observation')
    physical = {n: float(number(d['auxiliary']['observed'][i])) + math.fsum(float(number(a))*globals_['ravel_aux_'+str(j)+'_In'] for j, a in enumerate(d['auxiliary']['factor'][i])) for i, n in enumerate(d['auxiliary']['names'])}
    result = {'counts': counts, 'globals': globals_, 'physical_gaussian_measurement': physical, 'means_at_fixed_truth': full_means, 'component_seeds': seeds, 'rng': {'algorithm': 'Python/random.Random MT19937; Poisson superposition/Knuth; Gaussian gauss' if _graph_law is None else _graph_law.rng_name, 'python_version': sys.version}, 'auxiliary_mode': request['auxiliary_mode']}
    result['sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    return result


def source_nll(d, point, observation, *, reference=None):
    expectation = means(d, point,reference=reference)
    keys(observation['counts'], expectation, 'complete repeated counts')
    total = 0.
    for n, mu in expectation.items():
        x = observation['counts'][n]
        require(type(x) is int and x >= 0, 'nonnegative integer repeated count required')
        total += mu-x*math.log(mu)+math.lgamma(x+1)
    keys(observation['globals'], ['ravel_aux_'+str(i)+'_In' for i in range(len(d['auxiliary']['names']))], 'complete Gaussian globals')
    total += .5*math.fsum((float(Fraction(point['ravel_aux_'+str(i)]))-finite(observation['globals']['ravel_aux_'+str(i)+'_In'], 'global'))**2 for i in range(len(d['auxiliary']['names'])))
    return finite(total, 'source NLL')


def _binomial_cdf(k, n, p):
    if k < 0: return 0.
    if k >= n or p == 0: return 1.
    if p == 1: return 0.
    logs = [math.lgamma(n+1)-math.lgamma(i+1)-math.lgamma(n-i+1)+i*math.log(p)+(n-i)*math.log1p(-p) for i in range(k+1)]
    peak = max(logs)
    return min(1., math.exp(peak)*math.fsum(math.exp(v-peak) for v in logs))


def clopper_pearson(k, n, confidence):
    require(type(k) is int and type(n) is int and 0 <= k <= n and n > 0 and 0 < confidence < 1, 'binomial interval inputs invalid')
    alpha = (1-confidence)/2
    def solve(index, target):
        lo, hi = 0., 1.
        for _ in range(64):
            mid = (lo+hi)/2
            if _binomial_cdf(index, n, mid) > target: lo = mid
            else: hi = mid
        return (lo+hi)/2
    return [0. if k == 0 else solve(k-1, 1-alpha), 1. if k == n else solve(k, alpha)]


def summarize(request, rows):
    expected = [(t['id'], j) for t in request['truths'] for j in range(request['trials_per_truth'])]
    require([(r['truth_id'], r['ordinal']) for r in rows] == expected, 'full original scheduled population/order required')
    cohorts = []
    for truth in request['truths']:
        selected = [r for r in rows if r['truth_id'] == truth['id']]; n = len(selected)
        k = sum(r['status'] == 'included' for r in selected); rejected = sum(r['status'] == 'excluded' for r in selected); f = n-k-rejected
        require(all(r['status'] in ('included', 'excluded', 'unresolved', 'unissued') for r in selected), 'unknown toy disposition')
        confidence = float(number(request['confidence_level']))
        cohorts.append({'truth_id': truth['id'], 'scheduled': n, 'included': k, 'excluded': rejected, 'unresolved': f, 'identification_interval': [k/n, (k+f)/n], 'conservative_binomial_interval': [clopper_pearson(k,n,confidence)[0], clopper_pearson(k+f,n,confidence)[1]], 'resolved_only_fraction': k/(n-f) if n-f else None, 'unresolved_tolerance_met': Fraction(f,n) <= number(request['maximum_unresolved_fraction']), 'bernoulli_mc_se_upper_bound': .5/math.sqrt(n)})
    return {'estimand': ESTIMAND, 'critical_q': request['critical_q'], 'inclusion_rule': 'q <= cutoff outside declared numerical ambiguity margin', 'confidence_level': request['confidence_level'], 'cohorts': cohorts, 'coverage_qualified': False, 'optimizer_globality_qualified': False, 'limitations': ['Pointwise fixed-truth repeated-sampling diagnostic; not uniform nuisance coverage, CLs or expected bands.', 'Binomial uncertainty presumes the declared independent trial law; optimizer bias/globality is not covered.', 'All unresolved fits and unissued slots remain in the identification and binomial envelope.', 'Resolved-only fractions are selection-sensitive descriptions.']}


def _write(path, value):
    """Commit intended bytes, then authenticate the same regular output."""
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'output traverses symlink')
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as stream: stream.write(raw)
    observed=path.lstat()
    require(stat.S_ISREG(observed.st_mode) and observed.st_size==len(raw), 'ordinary intended output required')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        opened=os.fstat(stream.fileno()); read=stream.read(len(raw)+1); ending=os.fstat(stream.fileno())
    identity=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    require(read==raw and identity(observed)==identity(opened)==identity(ending)==identity(path.lstat()) and not any(p.is_symlink() for p in (path,*path.parents)), 'intended calibration output changed')
    return hashlib.sha256(raw).hexdigest()


def _check_fit(row, initial, poi, mu, expected):
    state = row['state']; keys(state, initial, 'complete fitted state')
    for n, old in initial.items():
        s = state[n]; keys(s, old, 'native coordinate')
        value = finite(s['value'], 'coordinate')
        require(s['minimum'] == old['minimum'] and s['maximum'] == old['maximum'] and s['constant'] == (True if n == poi and mu is not None else old['constant']), 'fit moved physical bounds/fixed state')
        require(old['minimum'] <= value <= old['maximum'] and (not old['constant'] or value == old['value']), 'fit outside source domain/fixed value')
    if mu is not None: require(state[poi]['value'] == mu, 'exact-truth POI changed')
    free = {n for n, s in state.items() if not s['constant']}; fit = row['fit']
    if not free:
        require(fit == {'performed': False, 'reason': 'no_floating_nuisance'}, 'deterministic point performed fit')
        return
    expected.conditioning_check(fit, {'conditioning': 'fit_observed_background', 'fit': expected.PROFILE_POLICY})
    floats = fit['floating_parameters']; const = fit['constant_parameters']
    require(len(floats) == len(free) and {x['name'] for x in floats} == free and len({x['name'] for x in const}) == len(const), 'fit result parameter census differs')
    for x in floats: require(finite(x['value'], 'fit value') == state[x['name']]['value'] and finite(x['error'], 'error') >= 0, 'fit result/state differs')
    for n, s in state.items():
        if s['constant']: require(next((x['value'] for x in const if x['name'] == n), None) == s['value'], 'fit fixed result differs')
    cov = fit['covariance']; require(len(cov) == len(free) and all(len(r) == len(free) for r in cov), 'fit covariance population differs')
    for i, r in enumerate(cov):
        for j, v in enumerate(r): require(finite(v, 'covariance') == cov[j][i] and (i != j or v >= 0), 'fit covariance symmetry/diagonal differs')
    require(abs(finite(fit['min_nll'], 'saved minimum')-finite(row['nll'], 'NLL')) <= 1e-8*(1+abs(row['nll'])), 'saved fit minimum/current NLL differs')
    raw = fit['raw_result']; require(Path(raw['basename']).name == raw['basename'] and raw['bytes'] > 0 and len(raw['sha256']) == 64, 'raw RooFitResult missing')


def _check_means(actual, predicted, label):
    keys(actual, predicted, label)
    for name,value in actual.items():
        observed=finite(value,label+' '+name)
        require(observed>0, 'strictly positive '+label+' required')
        require(abs(observed-predicted[name])<=1e-10*(1+abs(predicted[name])),label+' differs from complete source law')


def _check_observation(request,d,row, *, reference=None, _native_truth_means=None, _native_rng=None):
    observation=row['observation']
    keys(observation, ('counts','globals','physical_gaussian_measurement','means_at_fixed_truth','component_seeds','rng','auxiliary_mode','sha256'), 'complete sampling observation')
    require(type(row['ordinal']) is int and 0<=row['ordinal']<request['trials_per_truth'],'original toy ordinal required')
    truth=next(t for t in request['truths'] if t['id']==row['truth_id'])
    require(observation['sha256']==hashlib.sha256(json.dumps({k:v for k,v in observation.items() if k!='sha256'},sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest(),'same-toy commitment differs')
    predicted=means(d,truth['point'],reference=reference) if _native_truth_means is None else _native_truth_means
    _check_means(observation['means_at_fixed_truth'],predicted,'declared generating means')
    keys(observation['counts'],predicted,'complete repeated count population')
    require(all(type(v) is int and v>=0 for v in observation['counts'].values()),'integer repeated observations required')
    names=['ravel_aux_'+str(i)+'_In' for i in range(len(d['auxiliary']['names']))]
    keys(observation['globals'],names,'full Gaussian observation')
    require(observation['auxiliary_mode']==request['auxiliary_mode'],'auxiliary sampling policy differs')
    for name,value in observation['globals'].items():finite(value,'Gaussian observation '+name)
    if request['auxiliary_mode']=='conditional':
        require(all(value==0. for value in observation['globals'].values()),'conditional Gaussian observation changed')
        require(all(observation['counts'][bin_['id']]==bin_['observed'] for bin_ in d['bins'] if bin_['role']=='mc_auxiliary'),'conditional MC observation changed')
    components=['count:'+bin_['id'] for bin_ in d['bins']]+['gaussian:'+str(i) for i in range(len(names))]
    require(observation['component_seeds']=={name:str(seed_for(request,truth['id'],row['ordinal'],name)) for name in components},'source-defined component seeds differ')
    keys(observation['rng'],('algorithm','python_version'),'recorded RNG')
    require(observation['rng']['algorithm']==(_native_rng or 'Python/random.Random MT19937; Poisson superposition/Knuth; Gaussian gauss') and type(observation['rng']['python_version']) is str and observation['rng']['python_version'].strip(),'declared RNG/version missing')
    aux=d['auxiliary'];physical={name:float(number(aux['observed'][i]))+math.fsum(float(number(a))*observation['globals']['ravel_aux_'+str(j)+'_In'] for j,a in enumerate(aux['factor'][i])) for i,name in enumerate(aux['names'])}
    keys(observation['physical_gaussian_measurement'],physical,'full physical Gaussian measurement')
    require(all(abs(finite(observation['physical_gaussian_measurement'][n],'physical Gaussian measurement')-value)<=1e-12*(1+abs(value)) for n,value in physical.items()),'physical Gaussian measurement differs from fixed source factor/globals')
    return observation


def classify(request, d, row, initial, expected, *, reference=None):
    """Qualify returned raw states; no clipping of negative q or missing fits."""
    reference = reference or (ReferenceAudit(request,d,'toy') if has_dijet(d) else None)
    if reference is not None: row['reference_audit'] = reference.evidence
    _check_observation(request,d,row,reference=reference)
    _check_means(row['native_truth_means'],means(d,next(t for t in request['truths'] if t['id']==row['truth_id'])['point'],reference=reference),'native generating means')
    truth = next(t for t in request['truths'] if t['id'] == row['truth_id'])
    poi = next(p['name'] for p in d['parameters'] if p['role'] == 'poi'); mu = float(number(truth['point'][poi]))
    for role in ('free', 'fixed'):
        fitrow = row[role]; _check_fit(fitrow, initial, poi, None if role == 'free' else mu, expected)
        require(fitrow['counts'] == row['observation']['counts'] and fitrow['globals'] == row['observation']['globals'], 'fit changed same-toy observations/globals')
        model_means = means(d, {n:s['value'] for n,s in fitrow['state'].items()},reference=reference)
        _check_means(fitrow['native_means'],model_means,'native fitted means')
    native_delta = finite(row['fixed']['nll'], 'fixed NLL')-finite(row['free']['nll'], 'free NLL')
    source_values = {role: source_nll(d,{n:s['value'] for n,s in row[role]['state'].items()},row['observation'],reference=reference) for role in ('free','fixed')}
    source_delta = source_values['fixed']-source_values['free']; q = 2*native_delta
    row.update(raw_q=q, source_nll=source_values, source_q=2*source_delta, nll_contrast_discrepancy=native_delta-source_delta)
    band = float(number(request['nll_absolute_tolerance'])) + float(number(request['nll_relative_tolerance']))*max(abs(native_delta), abs(source_delta))
    if reference is not None:
        # The last two checks are the exact means consumed by free/fixed source
        # NLL. Sum estimates absolutely: no cancellation or band inflation.
        checks=reference.evidence['mean_checks'][-2:]
        errors={role:estimated_nll_error(check['means'],check['estimated_mean_error'],row['observation']['counts']) for role,check in zip(('free','fixed'),checks)}
        contrast_error=math.fsum(errors.values()); q_error=2*contrast_error
        row['reference_accuracy']={'estimated_source_nll_error':errors,'estimated_contrast_error':contrast_error,
            'estimated_q_error':q_error,'unchanged_nll_band':band,'unchanged_q_margin':float(number(request['numerical_margin'])),
            'certified_bound':False,'status':'unresolved'}
        reference.save()
        policy=request['reference_admissibility']
        require(contrast_error <= float(number(policy['fraction_of_existing_nll_band']))*band and
                q_error <= float(number(policy['fraction_of_existing_q_margin']))*float(number(request['numerical_margin'])),
                'estimated NLL/q accuracy screen failed; existing closure bands unchanged')
        row['reference_accuracy']['status']='admissible_estimate';reference.save()
    require(abs(native_delta-source_delta) <= band, 'native/source full-law NLL contrast disagrees')
    require(q >= 0, 'negative raw q; free minimum/globality unresolved')
    cutoff = float(number(request['critical_q'])); margin = float(number(request['numerical_margin']))
    require(abs(q-cutoff) > margin, 'cutoff inclusion within numerical ambiguity margin')
    row['status'] = 'included' if q <= cutoff else 'excluded'
    return row


def execute(ROOT, w, mc, data, response, request, expected, out, remaining_seconds, *, _graph_law=None):
    """Native-only operation in the existing supervised native worker.

    All original files are read-only. Every scheduled slot is written before any
    draw/fit; failures update that slot, and never trigger a redraw or retry.
    """
    require((response.get('kind')=='native-source-graph/v1') == (_graph_law is not None),'explicit authenticated graph calibration consumer required')
    d = response['document']; admission=ReferenceAudit(request,d,'admission') if _graph_law is None and has_dijet(d) else None
    if admission is None and _graph_law is None: validate(request,d)
    out=Path(out)
    require(not out.exists(), 'fresh calibration journal required')
    initial=expected._state(w,response); errors=expected._errors(w,initial)
    original_counts=expected._counts(data,d['bins']); original_globals=expected._globals(w,d)
    rows=[{'truth_id':t['id'],'ordinal':j,'status':'unissued','reason':'not_started'} for t in request['truths'] for j in range(request['trials_per_truth'])]
    result={'kind':KIND,'request':request,'status':'running','initial_state':initial,'original_counts':original_counts,'original_globals':original_globals,'rows':rows,'profile_policy':expected.PROFILE_POLICY,'top_level_profile_requests':0,'optimizer_globality_qualified':False,'coverage_qualified':False}
    if _graph_law is None and shape_description(d) is not None:
        result['continuous_shapes']=shape_description(d)
    if admission is not None: result['reference_admission']={'truth_means':admission.truth_means,'reference_audit':admission.evidence,'estimated_reference_uncertainty_is_certified':False}
    deadline=time.monotonic()+remaining_seconds
    def save(): return _write(out,expected._json_evidence(result))
    def inject(counts, globals_):
        for n,v in globals_.items(): w.var(n).setVal(v)
        for b in d['bins']: w.var('n_obs_bin'+b['id']).setVal(counts[b['id']])
        data.reset(); data.add(mc.GetObservables())
        require(expected._counts(data,d['bins'])==counts and {n:s['value'] for n,s in expected._globals(w,d).items()}==globals_, 'native injected dataset/global readback differs')
    def make_nll():
        options=[]
        if mc.GetNuisanceParameters():options.append(ROOT.RooFit.Constrain(mc.GetNuisanceParameters()))
        if mc.GetGlobalObservables():options.append(ROOT.RooFit.GlobalObservables(mc.GetGlobalObservables()))
        command=ROOT.RooLinkedList()
        for option in options:command.Add(option)
        return mc.GetPdf().createNLL(data,command)
    save(); poi=next(p['name'] for p in d['parameters'] if p['role']=='poi')
    try:
        if _graph_law is not None:
            _graph_law.start(result,save,out,deadline,initial);_graph_law.admit()
        if admission is not None:
            admission.checkpoint=save
            validate(request,d,reference=admission);save()
        for index,row in enumerate(rows):
            if deadline-time.monotonic()<request['reservation_seconds_per_toy']:
                row['reason']='aggregate_budget_reservation_unavailable'; save(); continue
            required_reference = 7*sum(t['shape']['integration']['reference']['max_evaluations'] for t in d['terms'] if t.get('shape',{}).get('kind')=='normalized_dijet')
            if _graph_law is None and has_dijet(d) and request['reference_budget']['toy_reserved_evaluations'] < required_reference:
                row['reason']='complete_toy_reference_reservation_unavailable';save();continue
            if _graph_law is not None and not _graph_law.reserve_toy(row):
                row['reason']='complete_native_readback_or_state_reservation_unavailable';save();continue
            started=time.monotonic(); row.update(status='unresolved',reason='generation_or_fit_incomplete'); save()
            truth=next(t for t in request['truths'] if t['id']==row['truth_id'])
            audit=ReferenceAudit(request,d,'toy',save) if _graph_law is None and has_dijet(d) else None
            if audit is not None: row['reference_audit']=audit.evidence;save()
            try:
                if _graph_law is not None:_graph_law.current_row=row
                row['observation']=toy(request,d,truth,row['ordinal'],reference=audit,_graph_law=_graph_law); save()
                expected._restore(w,initial)
                for name,value in truth['point'].items():w.var(name).setVal(float(number(value)))
                row['native_truth_means']=({b['id']:float(w.function('ravel_mean_'+str(i)).getVal()) for i,b in enumerate(d['bins'])} if _graph_law is None else dict(row['source_graph_truth_readback']['totals']));save()
                _check_means(row['native_truth_means'],row['observation']['means_at_fixed_truth'],'native generating means')
                expected._restore(w,initial);expected._restore_errors(w,errors)
                inject(row['observation']['counts'],row['observation']['globals'])
                # New NLL only AFTER the complete dataset/globals were injected.
                nll=make_nll(); require(bool(nll),'same-toy NLL absent')
                for role in ('free','fixed'):
                    require(time.monotonic()<deadline,'aggregate native budget exhausted')
                    if _graph_law is not None:_graph_law.reset_profile(row['observation'])
                    expected._restore(w,initial);expected._restore_errors(w,errors)
                    if role=='fixed':w.var(poi).setVal(float(number(truth['point'][poi])));w.var(poi).setConstant(True)
                    start=expected._state(w,response)
                    row[role]={'start_state':start,'start_errors':expected._errors(w,initial)}
                    result['top_level_profile_requests']+=1;save()
                    row[role]['fit']=expected._profile_fit(ROOT,nll,w,response,out.parent/('ravel_calibration_fit_'+str(index)+'_'+role+'.root'),start)
                    row[role].update(state=expected._state(w,response),nll=float(nll.getVal()),counts=expected._counts(data,d['bins']),globals={n:s['value'] for n,s in expected._globals(w,d).items()});save()
                    if _graph_law is None:row[role]['native_means']={b['id']:float(w.function('ravel_mean_'+str(i)).getVal()) for i,b in enumerate(d['bins'])}
                    else:
                        row[role]['source_graph_readback']=_graph_law.fitted(row[role]['state'],'toy:'+row['truth_id']+':'+str(row['ordinal'])+':'+role)
                        row[role]['native_means']=dict(row[role]['source_graph_readback']['totals'])
                    save()
                if _graph_law is not None:
                    _graph_law.classify(row,initial)
                else:classify(request,d,row,initial,expected,reference=audit)
                row.pop('reason',None)
            except Exception as exc:
                row.update(status='unresolved',reason='failed_generation_or_profile_or_closure',error={'type':type(exc).__name__,'message':str(exc)})
            finally:
                row['wall_seconds']=time.monotonic()-started; save()
                expected._restore(w,initial);expected._restore_errors(w,errors)
                inject(original_counts,{n:s['value'] for n,s in original_globals.items()})
                if _graph_law is not None:_graph_law.state.restore(w,mc,_graph_law.original_native_state)
        if _graph_law is not None:_graph_law.finish()
        result['final_state']=expected._state(w,response);result['final_counts']=expected._counts(data,d['bins']);result['final_globals']=expected._globals(w,d)
        require(result['final_state']==initial and result['final_counts']==original_counts and result['final_globals']==original_globals and expected._errors(w,initial)==errors, 'ending full native state/data/errors differ')
        result['summary']=summarize(request,rows); result['status']='delivered'; save();return expected._json_evidence(result)
    except BaseException as exc:
        if _graph_law is not None:
            try:
                expected._restore(w,initial);expected._restore_errors(w,errors)
                inject(original_counts,{n:s['value'] for n,s in original_globals.items()})
                _graph_law.state.restore(w,mc,_graph_law.original_native_state)
                result['failed_ending_native_state']=_graph_law.state.capture(w,mc)
            except BaseException as restore_error:
                result['failed_ending_restoration_error']={'type':type(restore_error).__name__,'message':str(restore_error)}
        result['status']='failed';result['error']={'type':type(exc).__name__,'message':str(exc)};save();raise


def validate_delivery(result, response, request, expected, *, reference=None):
    d=response['document'];audit=reference or (ReferenceAudit(request,d,'validation') if has_dijet(d) else None)
    validate(request,d,reference=audit)
    require(result['kind']==KIND and result['request']==request and result['status']=='delivered' and result['coverage_qualified'] is False and result['optimizer_globality_qualified'] is False, 'current complete calibration delivery required')
    require(result['profile_policy']==expected.PROFILE_POLICY,'optimizer policy changed')
    require(result.get('continuous_shapes')==shape_description(d), 'continuous shape law disclosure differs')
    require(result['final_state']==result['initial_state'] and result['final_counts']==result['original_counts'] and result['final_globals']==result['original_globals'],'ending native original state/data changed')
    original={p['name']:{'value':float(number(p['initial'])),'minimum':float(number(p['bounds'][0])),'maximum':float(number(p['bounds'][1])),'constant':p['fixed']} for p in d['parameters']}
    original.update({'ravel_aux_'+str(i):{'value':0.,'minimum':float(number(b[0])),'maximum':float(number(b[1])),'constant':False} for i,b in enumerate(d['auxiliary']['eta_bounds'])})
    require(result['initial_state']==original and result['original_counts']=={b['id']:float(b['observed']) for b in d['bins']} and result['original_globals']=={'ravel_aux_'+str(i)+'_In':{'value':0.,'constant':True,'has_min':False,'has_max':False} for i in range(len(d['auxiliary']['names']))}, 'original source model/data/global state differs')
    requests=sum(role in row for row in result['rows'] for role in ('free','fixed'))
    require(result['top_level_profile_requests']==requests and requests<=2*len(result['rows']),'profile request population differs')
    for row in result['rows']:
        if 'observation' in row:_check_observation(request,d,row,reference=audit)
        if row['status'] in ('included','excluded'):
            # Validate a copy: persisted native-runtime diagnostics remain raw
            # evidence, not values to rewrite using the host's math library.
            recomputed=classify(request,d,dict(row),result['initial_state'],expected,reference=audit)
            diagnostics={'source_nll','source_q','nll_contrast_discrepancy','reference_audit','reference_accuracy'}
            if audit is not None:
                saved_accuracy=row['reference_accuracy']; current_accuracy=recomputed['reference_accuracy']
                keys(saved_accuracy,current_accuracy,'complete retained reference accuracy')
                keys(saved_accuracy['estimated_source_nll_error'],('free','fixed'),'full retained NLL error estimates')
                for role,value in saved_accuracy['estimated_source_nll_error'].items():
                    current=current_accuracy['estimated_source_nll_error'][role]
                    require(abs(finite(value,'retained NLL estimate')-current)<=1e-12*max(abs(current),1e-20), 'retained NLL accuracy estimate differs')
                total=math.fsum(saved_accuracy['estimated_source_nll_error'].values())
                require(saved_accuracy['estimated_contrast_error']==total and saved_accuracy['estimated_q_error']==2*total and
                        saved_accuracy['certified_bound'] is False and saved_accuracy['status']=='admissible_estimate', 'retained reference accuracy identities differ')
                policy=request['reference_admissibility']
                require(total <= float(number(policy['fraction_of_existing_nll_band']))*current_accuracy['unchanged_nll_band'] and
                        2*total <= float(number(policy['fraction_of_existing_q_margin']))*float(number(request['numerical_margin'])), 'retained reference estimate failed unchanged screens')
                saved_delta=finite(row['source_nll']['fixed'],'saved fixed source NLL')-finite(row['source_nll']['free'],'saved free source NLL')
                native_delta=finite(row['fixed']['nll'],'native fixed NLL')-finite(row['free']['nll'],'native free NLL')
                saved_band=float(number(request['nll_absolute_tolerance']))+float(number(request['nll_relative_tolerance']))*max(abs(saved_delta),abs(native_delta))
                require(saved_accuracy['unchanged_nll_band']==saved_band and saved_accuracy['unchanged_q_margin']==float(number(request['numerical_margin'])), 'retained unchanged band/margin differs')
            require(finite(row['raw_q'],'persisted raw q')==recomputed['raw_q'],'persisted raw q differs')
            require({k:v for k,v in row.items() if k not in diagnostics}=={k:v for k,v in recomputed.items() if k not in diagnostics},'persisted toy disposition/contrasts differ')
            keys(row['source_nll'],('free','fixed'),'persisted source NLL')
            saved={role:finite(row['source_nll'][role],'persisted source NLL '+role) for role in ('free','fixed')}
            saved_delta=saved['fixed']-saved['free']
            native_delta=finite(row['fixed']['nll'],'fixed NLL')-finite(row['free']['nll'],'free NLL')
            require(finite(row['source_q'],'persisted source q')==2*saved_delta and finite(row['nll_contrast_discrepancy'],'persisted contrast discrepancy')==native_delta-saved_delta,'persisted source contrast identities differ')
            source_delta=recomputed['source_nll']['fixed']-recomputed['source_nll']['free']
            # Use the unchanged declared contrast band for EACH source value;
            # a shared offset cannot hide a failed absolute component check.
            band=float(number(request['nll_absolute_tolerance']))+float(number(request['nll_relative_tolerance']))*max(abs(native_delta),abs(source_delta))
            require(all(abs(saved[role]-recomputed['source_nll'][role])<=band for role in ('free','fixed')),'persisted source NLL differs beyond declared band')
            saved_band=float(number(request['nll_absolute_tolerance']))+float(number(request['nll_relative_tolerance']))*max(abs(native_delta),abs(saved_delta))
            require(abs(native_delta-saved_delta)<=saved_band,'persisted native/source full-law NLL contrast disagrees')
    require(result['summary']==summarize(request,result['rows']),'calibration denominator/summary differs')
    if audit is not None:
        validate_reference_delivery(result,request,d,reference=audit)
    return result


def validate_reference_delivery(result, request, d, *, reference):
    """Check retained reservations/results without relabeling raw failures.

    Resolved diagnostics are recomputed by classify under a NEW validation
    reservation. Returned raw numerical diagnostics remain original evidence.
    """
    dijet_terms=[t for t in d['terms'] if t.get('shape',{}).get('kind')=='normalized_dijet']
    width=len(dijet_terms)
    def check(audit,phase,points,*,complete=False,minimum_means=0):
        keys(audit,('phase','maximum_reserved_evaluations','reserved_evaluations',
                    'known_successful_evaluations','calls','mean_checks','error_semantics',
                    'native_integral_and_fit_cost'),'complete retained reference audit')
        require(type(audit['calls']) is list and type(audit['mean_checks']) is list and
                type(audit['reserved_evaluations']) is int and
                type(audit['known_successful_evaluations']) is int and
                audit['native_integral_and_fit_cost']=='not_measured_by_source_reference_meter',
                'retained reference cost disclosure differs')
        calls=audit['calls'];checks=audit['mean_checks']
        require(minimum_means <= len(checks) <= len(points) and len(calls) <= width*len(points),
                'retained reference invocation population differs')
        if complete:
            require(len(checks)==len(points) and len(calls)==width*len(points) and
                    all(call.get('status')=='returned' for call in calls),
                    'complete successful reference invocation census required')
        else:
            # A failed kernel or TOTAL-mean calculation can end after a partial
            # call group, or after a returned group before emitting its mean.
            # Such prefixes remain unresolved; no successful count is invented.
            require(width*len(checks) <= len(calls) <= width*(len(checks)+1),
                    'failed reference prefix is not its retained invocation sequence')
        for index,call in enumerate(calls):
            group=index//width;expected_point=points[group]
            require(expected_point is not None and call.get('term')==dijet_terms[index%width]['id'],
                    'retained reference term/state order differs')
            keys(call.get('point'),set(coordinates(d))|set(d['auxiliary']['names']),
                 'retained reference state')
            require({n:Fraction(call['point'][n]) for n in coordinates(d)}==
                    {n:Fraction(v) for n,v in expected_point.items()},
                    'retained reference invocation point differs')
        for index,check_ in enumerate(checks):
            require(points[index] is not None and
                    {n:Fraction(v) for n,v in check_['point'].items()}==
                    {n:Fraction(v) for n,v in points[index].items()},
                    'retained mean invocation point/order differs')
        require(audit['phase']==phase and audit['maximum_reserved_evaluations']==request['reference_budget'][phase+'_reserved_evaluations'] and audit['error_semantics']==REFERENCE_SEMANTICS,
                'reference audit phase/policy differs')
        reserved=0;known=0
        from ravel.physics import continuous_dijet_shapes as kernel
        shapes={t['id']:t['shape'] for t in d['terms'] if t.get('shape',{}).get('kind')=='normalized_dijet'}
        for call in audit['calls']:
            shape=shapes[call['term']];ceiling=shape['integration']['reference']['max_evaluations']
            require(call['settings']==shape['integration']['reference'], 'reference settings differ')
            require(set(call['point'])==set(coordinates(d))|set(d['auxiliary']['names']), 'complete reference state census differs')
            point={k:Fraction(v) for k,v in call['point'].items()}
            auxiliary=d['auxiliary']
            require(all(point[n]==number(auxiliary['observed'][i])+sum((number(v)*point['ravel_aux_'+str(j)] for j,v in enumerate(auxiliary['factor'][i])),Fraction()) for i,n in enumerate(auxiliary['names'])), 'reference physical auxiliary factor differs')
            coefficients=kernel.effective_parameters(shape,point,[point[n] for n in auxiliary['names']])
            require(list(map(Fraction,call['effective_coefficients']))==coefficients, 'reference effective coefficient identity differs')
            require(call['status'] in ('returned','failed','reservation_unavailable'), 'unfinished reference call')
            require(call['reserved_evaluations']==(0 if call['status']=='reservation_unavailable' else ceiling), 'reference reservation differs')
            reserved+=call['reserved_evaluations']
            if call['status']=='returned':
                raw=call['result'];count=call['actual_evaluations']
                domain,windows=kernel.geometry(shape)
                integrals=1+sum(window is not None and window!=domain for window in windows)
                splits=raw.get('subdivisions')
                # The mandatory full-domain call evaluates five distinct unit
                # points. Each integration starts with five evaluation attempts;
                # each binary split adds four. The per-call cache can share
                # points across windows, so these are feasible bounds, NEVER an
                # equality to the validation host's adaptive traversal counts.
                require(type(count) is int and 5<=count<=ceiling and
                        type(raw.get('evaluations')) is int and count==raw['evaluations'] and
                        type(splits) is int and 0<=splits<=integrals*(2**shape['integration']['reference']['max_depth']-1) and
                        count<=5*integrals+4*splits and splits<=integrals*((count-5)//4) and
                        raw['error_semantics']==REFERENCE_SEMANTICS and raw['clipping_applied'] is False,
                        'reference returned diagnostics/counter structure differ')
                # Re-execute the same complete source diagnostics under the
                # independently bounded VALIDATION operation. Numerical outputs
                # are compared under fixed operational precision; raw receipts
                # are not rewritten to host values or granted physics authority.
                current=reference.reference(call['term'],shape,coefficients,point)
                require(set(raw)==set(current) and raw['normalization']==current['normalization'], 'reference result census differs')
                def same(a,b):
                    if type(a) is list and type(b) is list:
                        return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
                    if type(a) in (int,float) and type(b) in (int,float):
                        return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=1e-12*max(abs(b),1e-20)
                    return a==b
                require(all(same(raw[name],current[name]) for name in ('fractions','gradient','estimated_probability_error','estimated_gradient_error')), 'persisted full reference diagnostics differ')
                known+=count
            else: require(call['actual_evaluations'] is None, 'failed consumed reference count must remain unknown')
        require(reserved==audit['reserved_evaluations']<=audit['maximum_reserved_evaluations'] and known==audit['known_successful_evaluations'], 'reference cost census differs')
        # Reconstruct the emitted TOTAL diagnostic from the already individually
        # authenticated/replayed raw reference results. This does not call the
        # quadrature again or cache results across operations.
        from ravel.physics import parametric_shapes
        for index,check_ in enumerate(audit['mean_checks']):
            keys(check_,('point','means','estimated_mean_error','absolute_signed_term_contributions','status'),'complete retained mean diagnostic')
            keys(check_['point'],coordinates(d),'retained full mean point')
            point={n:Fraction(v) for n,v in check_['point'].items()};aux=d['auxiliary']
            values={**point,**{n:number(aux['observed'][i])+sum((number(v)*point['ravel_aux_'+str(j)] for j,v in enumerate(aux['factor'][i])),Fraction()) for i,n in enumerate(aux['names'])}}
            calls=audit['calls'][index*len(dijet_terms):(index+1)*len(dijet_terms)]
            require(len(calls)==len(dijet_terms) and all(call['status']=='returned' and call['term']==term['id'] and {n:Fraction(v) for n,v in call['point'].items()}==values for call,term in zip(calls,dijet_terms)), 'retained mean/reference invocation census differs')
            reference_results={call['term']:call['result'] for call in calls}
            fractions={};probability_errors={}
            for term in d['terms']:
                if 'shape' not in term:continue
                shape=term['shape']
                if term['id'] in reference_results:
                    fractions[term['id']]=reference_results[term['id']]['fractions']
                    probability_errors[term['id']]=reference_results[term['id']]['estimated_probability_error']
                else:
                    slope=parametric_shapes.effective_slope(shape,values,[values[n] for n in aux['names']])
                    fractions[term['id']]=parametric_shapes.fractions(shape,slope)[0]
            predicted={};errors={};terms={}
            for b,bin_ in enumerate(d['bins']):
                pieces=[];estimates=[];contributions=[]
                for term in d['terms']:
                    coefficient=number(term['coefficients'][b])
                    if not coefficient:pieces.append(0.);continue
                    monomial=coefficient*math.prod(values[n]**power for n,power in term['powers'].items())
                    exponent=sum((number(v)*values[n] for v,n in zip(term['log_response'][b],aux['names'])),Fraction())
                    amplitude=float(monomial)*math.exp(float(exponent))
                    pieces.append(amplitude*fractions[term['id']][b] if term['id'] in fractions else amplitude)
                    if term['id'] in probability_errors:
                        estimate=abs(amplitude)*probability_errors[term['id']][b];estimates.append(estimate)
                        contributions.append({'term':term['id'],'signed_full_domain_coefficient':amplitude,'estimated_probability_error':probability_errors[term['id']][b],'absolute_estimated_mean_contribution':estimate})
                predicted[bin_['id']]=math.fsum(pieces);errors[bin_['id']]=math.fsum(estimates);terms[bin_['id']]=contributions
            def equivalent(a,b):
                if type(a) is dict and type(b) is dict:
                    return set(a)==set(b) and all(equivalent(a[n],b[n]) for n in a)
                if type(a) is list and type(b) is list:
                    return len(a)==len(b) and all(equivalent(v,w) for v,w in zip(a,b))
                if type(a) in (int,float) and type(b) in (int,float):
                    return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=1e-12*max(abs(b),1e-20)
                return a==b
            require(equivalent(check_['means'],predicted) and equivalent(check_['estimated_mean_error'],errors) and equivalent(check_['absolute_signed_term_contributions'],terms), 'retained absolute TOTAL mean/error diagnostic differs')
            fraction=float(number(request['reference_admissibility']['fraction_of_existing_mean_band']))
            passed=all(errors[n]<predicted[n] and errors[n]<=fraction*1e-10*(1+abs(predicted[n])) for n in predicted)
            require(check_['status']==('admissible_estimate' if passed else 'unresolved'), 'retained mean accuracy disposition differs')

    admission=result['reference_admission']
    keys(admission,('truth_means','reference_audit','estimated_reference_uncertainty_is_certified'),
         'complete retained reference admission')
    require(admission['estimated_reference_uncertainty_is_certified'] is False and
            type(admission['truth_means']) is list and len(admission['truth_means'])==len(request['truths']),
            'full admission truth census and explicit noncertification required')
    for saved,truth,current in zip(admission['truth_means'],request['truths'],reference.truth_means):
        keys(saved,('truth_id','point','means'),'retained admission truth')
        require(saved['truth_id']==truth['id'] and saved['point']==truth['point'],
                'retained admission truth identity/order differs')
        _check_means(saved['means'],current['means'],'retained admission truth means')
    require(len(reference.truth_means)==len(request['truths']), 'current admission truth census differs')
    check(admission['reference_audit'],'admission',[truth['point'] for truth in request['truths']],complete=True)
    for saved,mean_check in zip(admission['truth_means'],admission['reference_audit']['mean_checks']):
        _check_means(saved['means'],mean_check['means'],'retained admission mean diagnostic')
    for row in result['rows']:
        resolved=row['status'] in ('included','excluded')
        if row['status']=='unissued':
            require('reference_audit' not in row, 'unissued slot cannot report consumed reference work')
            continue
        require('reference_audit' in row, 'started dijet slot requires retained reference cost/prefix')
        truth=next(t for t in request['truths'] if t['id']==row['truth_id'])
        fitted={role:({n:s['value'] for n,s in row[role]['state'].items()}
                      if role in row and 'state' in row[role] else None) for role in ('free','fixed')}
        points=[truth['point']]*3+[fitted['free'],fitted['fixed'],fitted['free'],fitted['fixed']]
        check(row['reference_audit'],'toy',points,complete=resolved,
              minimum_means=1 if 'observation' in row else 0)
        if resolved:
            require(row['reference_accuracy']['status']=='admissible_estimate' and row['reference_accuracy']['certified_bound'] is False, 'resolved dijet slot requires explicit numerical screens')
    return result
