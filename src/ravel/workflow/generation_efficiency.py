"""Process-bound pilot preparation and empirical cost admission.

Preparation never approves or runs a study. Estimates are local operational
observations, not numerical/physics qualification or guaranteed upper bounds.
"""
import argparse
import ast
from datetime import datetime
from fractions import Fraction
from copy import deepcopy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import stat

from . import execution
from .state_io import _unique

MAX_BYTES = 8 * 1024**2

def _float(value):
    result = float(value)
    if not math.isfinite(result): raise ValueError('nonfinite cost evidence')
    return result

def _document(data):
    return json.loads(data, object_pairs_hook=_unique, parse_float=_float,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite cost evidence')))

PHASES = ('build', 'survey', 'refine', 'combine_events', 'store_events',
          'reweight', 'decay_events', 'shower')


def _keys(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('closed ' + label + ' required')


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class _Inputs:
    def __init__(self, base):
        self.base = Path(base).absolute()
        self.rows = {}

    def read(self, value, expected=None):
        p = Path(value); p = p if p.is_absolute() else self.base / p
        p = p.absolute()
        if any(q.is_symlink() for q in (p, *p.parents)):
            raise ValueError('cost evidence must not traverse aliases')
        before = p.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ValueError('bounded regular cost evidence required')
        with p.open('rb') as f:
            if _identity(os.fstat(f.fileno())) != _identity(before):
                raise ValueError('cost evidence changed before read')
            data = f.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES or _identity(os.fstat(f.fileno())) != _identity(before):
                raise ValueError('cost evidence changed during read')
        if _identity(p.stat()) != _identity(before):
            raise ValueError('cost evidence path changed during read')
        pin = {'path': str(p), 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        if expected is not None and (pin['sha256'] != expected['sha256'] or pin['size'] != expected['size']):
            raise ValueError('cost evidence commitment differs')
        old = self.rows.get(str(p))
        if old is not None and old != pin:
            raise ValueError('cost evidence changed within observation')
        self.rows[str(p)] = pin
        return data, pin

    def consume(self, pin):
        _keys(pin, ('path', 'sha256', 'size'), 'cost evidence pin')
        if (type(pin['path']) is not str or not pin['path'] or
                type(pin['sha256']) is not str or len(pin['sha256']) != 64 or
                any(c not in '0123456789abcdef' for c in pin['sha256']) or
                type(pin['size']) is not int or not 0 < pin['size'] <= MAX_BYTES):
            raise ValueError('exact cost evidence pin required')
        data, _ = self.read(pin['path'], pin)
        return data

    def document(self, pin):
        return _document(self.consume(pin))

    def finish(self):
        for row in tuple(self.rows.values()):
            self.read(row['path'], row)
        return list(self.rows.values())


def machine_observation():
    """Current host/kernel observation; neither OS authentication nor a lease."""
    u = os.uname()
    return {'schema_version': 1, 'kind': 'operational_machine_observation',
            'system': u.sysname, 'release': u.release, 'machine': u.machine,
            'hostname': u.nodename, 'logical_cpus': os.cpu_count(),
            'selected_environment': {**execution.runtime_environment(),
                **{key: os.environ.get(key) for key in ('NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}}}


def _native_environment_rebindings(body, *, initial_env=None):
    """Keep the admitted environment expression free of writes and aliases."""
    aliases = {'env', 'environment'}
    for node in ast.walk(body):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
                and node.value.id in aliases):
            # A mutable mapping handed to another local name is an unsupported
            # law; a source pin alone cannot make its later effects predictable.
            raise ValueError('unsupported native environment rebinding')
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in aliases | {'os', 'dict'} and node is not initial_env:
                raise ValueError('unsupported native environment rebinding')
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not body:
            if node.name in aliases | {'os', 'dict', 'execute_native'}:
                raise ValueError('unsupported native environment rebinding')
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for item in node.names:
                if (item.asname or item.name.split('.')[0]) in aliases | {'os', 'dict'}:
                    raise ValueError('unsupported native environment rebinding')
        value = None
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
                and node.attr == 'environ' and isinstance(node.value, ast.Name)
                and node.value.id == 'os'):
            raise ValueError('unsupported native environment rebinding')
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            value = node.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in {'items', 'keys', 'values', 'get', 'copy'}:
                value = node.func.value
        while isinstance(value, (ast.Attribute, ast.Subscript)):
            if (isinstance(value, ast.Attribute) and value.attr == 'environ'
                    and isinstance(value.value, ast.Name) and value.value.id == 'os'):
                raise ValueError('unsupported native environment rebinding')
            value = value.value
        if isinstance(value, ast.Name) and value.id in aliases:
            raise ValueError('unsupported native environment rebinding')


def _native_environment_caller(capture, *, supported_keywords):
    """Authenticate this operation's actual direct executor call and default."""
    source = Path(__file__).parent.parent / 'physics' / 'model_events.py'
    raw, pin = capture.read(source)
    tree = ast.parse(raw)
    bodies = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run']
    if len(bodies) != 1: raise ValueError('exact native caller source required')
    body = bodies[0]
    imports = [node for node in body.body if isinstance(node, ast.ImportFrom)
        and node.module == 'ravel.physics.reinterpret_db' and node.level == 0
        and len(node.names) == 1 and node.names[0].name == 'execute_native'
        and node.names[0].asname is None]
    writes = [node for node in ast.walk(body) if
        (isinstance(node, ast.Name) and node.id == 'execute_native'
            and isinstance(node.ctx, (ast.Store, ast.Del))) or
        (isinstance(node, ast.arg) and node.arg == 'execute_native') or
        (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node is not body and node.name == 'execute_native')]
    bindings = [item for node in ast.walk(body) if isinstance(node, (ast.Import, ast.ImportFrom))
        for item in node.names if (item.asname or item.name.split('.')[0]) == 'execute_native']
    calls = [node for node in ast.walk(body) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == 'execute_native']
    if len(imports) != 1 or len(bindings) != 1 or writes or len(calls) != 1:
        raise ValueError('unsupported native caller binding')
    call = calls[0]
    direct = [node.value for node in body.body if isinstance(node, (ast.Assign, ast.Expr))
        and node.value is call]
    if len(direct) != 1 or imports[0].lineno >= call.lineno:
        raise ValueError('unsupported native caller binding')
    if (len(call.args) != 3 or any(isinstance(x, ast.Starred) for x in call.args)
            or any(x.arg is None for x in call.keywords)
            or len({x.arg for x in call.keywords}) != len(call.keywords)):
        raise ValueError('unsupported native caller environment')
    if any(x.arg not in supported_keywords for x in call.keywords):
        raise ValueError('unsupported native caller keyword')
    supplied = [x.value for x in call.keywords if x.arg == 'environment']
    if supplied and ('environment' not in supported_keywords or len(supplied) != 1
            or not isinstance(supplied[0], ast.Constant) or supplied[0].value is not None):
        raise ValueError('explicit or unknown native caller environment cannot forecast inherited state')
    _native_environment_rebindings(body)
    return pin


def prospective_native_machine(capture):
    """Predict selected fields for the authenticated operation's default call.

    The current caller observation remains separate. An explicit or unresolved
    caller environment is refused, not silently replaced with inherited state.
    This is neither kernel identity, a runtime nor an execution lease.
    """
    source = Path(__file__).parent.parent / 'physics' / 'reinterpret_db.py'
    raw, pin = capture.read(source)
    tree = ast.parse(raw)
    bodies = [node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == 'execute_native']
    if len(bodies) != 1: raise ValueError('exact native executor source required')
    body = bodies[0]
    assignments = [node for node in body.body if isinstance(node, ast.Assign)
        and any(isinstance(x, ast.Name) and x.id == 'env' for x in node.targets)]
    if len(assignments) != 1 or len(assignments[0].targets) != 1:
        raise ValueError('source-defined native environment required')
    call = assignments[0].value
    inherited = ast.parse('os.environ', mode='eval').body
    optional = ast.parse('os.environ if environment is None else environment', mode='eval').body
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
            or call.func.id != 'dict' or len(call.args) != 1
            or ast.dump(call.args[0]) not in (ast.dump(inherited), ast.dump(optional))):
        raise ValueError('unsupported native environment transformation')
    arguments = body.args
    defaults = {arg.arg: default for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults)}
    supports_environment = 'environment' in defaults
    if (arguments.vararg or arguments.kwarg or arguments.posonlyargs
            or set(defaults) - {'generated_event_ceiling', 'environment'}
            or len(defaults) != len(arguments.kwonlyargs)
            or [x.arg for x in arguments.args] != ['command', 'out', 'document']
            or (supports_environment and (not isinstance(defaults['environment'], ast.Constant)
                or defaults['environment'].value is not None))
            or (ast.dump(call.args[0]) == ast.dump(optional) and not supports_environment)):
        raise ValueError('unsupported native environment default')
    keys = {'OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
            'NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'}
    if (len(call.keywords) != len(keys) or {x.arg for x in call.keywords} != keys
            or any(not isinstance(x.value, ast.Constant) or x.value.value != '1'
                   for x in call.keywords)):
        raise ValueError('unsupported native thread environment law')
    _native_environment_rebindings(body, initial_env=assignments[0].targets[0])
    _native_environment_caller(capture, supported_keywords=set(defaults))
    observed = machine_observation(); expected = deepcopy(observed)
    expected['selected_environment'].update({x.arg: x.value.value for x in call.keywords})
    return observed, expected, pin


def process_profile(task, base, *, _inputs=None):
    """Bind all scientific settings; only explicit event/seed pilot deltas vary."""
    from ravel.physics import model_events as me
    own = _inputs is None; capture = _inputs or _Inputs(base)
    configuration = Path(task['config'])
    if not configuration.is_absolute(): configuration = Path(base).absolute() / configuration
    data, config_pin = capture.read(configuration)
    c = me.validate_config(_document(data))
    root = Path(config_pin['path']).parent
    protected = deepcopy(c)
    for key in ('events', 'seed'):
        protected['generation'].pop(key)
    for key in ('nevents', 'iseed'):
        protected['generation']['run_settings'].pop(key, None)
    protected.pop('max_seconds'); protected.pop('outputs')
    cards = {}
    for name, pin in c['cards'].items():
        if pin is None:
            cards[name] = None; continue
        resolved = {**pin, 'path': str(root / pin['path']) if not Path(pin['path']).is_absolute() else pin['path']}
        # Older native config pins lack size; consume the hash-authenticated
        # buffer and retain a full pin in this new observation.
        raw, current = capture.read(resolved['path'])
        if current['sha256'] != pin['sha256']:
            raise ValueError('scientific card changed')
        if name == 'run':
            rows = me.assignments(raw.decode('utf-8'))
            for key in ('nevents', 'iseed'): rows.pop(key, None)
            cards[name] = rows
        else:
            cards[name] = current['sha256']
    # Location spellings and per-pilot run-card hashes are transport, whereas
    # admitted tree manifests and every other scientific card remain exact.
    protected['cards'] = cards
    for tree in [protected['runtime']['madgraph_tree'], protected['model_tree'],
                 *[x['tree'] for x in protected['runtime']['dependencies']]]:
        tree.pop('root')
    identity = execution.digest(protected)
    caller, prospective, executor_pin = prospective_native_machine(capture)
    result = {'schema_version': 1, 'kind': 'generation_process_profile',
              'profile_sha256': identity, 'protected': protected,
              'configuration': config_pin, 'events': c['generation']['events'],
              'seed': c['generation']['seed'], 'order': c['generation']['order'],
              'max_seconds': c['max_seconds'], 'machine': prospective,
              'caller_machine': caller, 'native_environment_source': executor_pin,
              'native_environment_caller_source': dict(capture.rows[str(
                  (Path(__file__).parent.parent / 'physics' / 'model_events.py').absolute())]),
              'interpretation': 'Equal profile permits only declared event/seed/resource/output deltas; no mass/width/coupling/cut/PDF/model extrapolation.'}
    if own: capture.finish()
    return result


def _production_parent(spec, capture):
    binding = spec.get('goal_binding')
    if binding is None: return False
    pin = binding['contract']; raw, observed = capture.read(pin['path'])
    if observed['sha256'] != pin['sha256'] or ('size' in pin and observed['size'] != pin['size']):
        raise ValueError('parent objective changed')
    contract = _document(raw)
    return contract.get('compute_plan') in ('full', 'scan')


def guidance(spec, base):
    if spec.get('mode') != 'model-events': return None
    capture = _Inputs(base)
    profile = process_profile(spec['task'], base, _inputs=capture)
    declared = spec.get('generation_efficiency')
    if declared is not None and declared['purpose'] == 'production':
        committed = capture.document(declared['forecast'])
        result = {'schema_version': 1, 'status': 'local_empirical_forecast',
            'forecast_seconds': committed['forecast_seconds'], 'process': profile,
            'authorized_wall_seconds': spec['max_seconds'], 'purpose': 'production',
            'production_feasibility_established': False,
            'next_api': 'ravel.workflow.science.approve',
            'next_required': 'Exact current forecast, estimator/target evidence and scoped review revalidated at ordinary plan/launch; cost is not a guaranteed ceiling or physics certificate.'}
    else:
        result = {'schema_version': 1, 'status': 'uncalibrated', 'forecast_seconds': None,
            'process': profile, 'authorized_wall_seconds': spec['max_seconds'],
            'purpose': 'bounded_pilot' if declared else 'explicit_fixed_bounded_observation',
            'production_feasibility_established': False,
            'next_api': 'ravel.workflow.generation_efficiency.prepare_pilot',
            'next_required': 'Supply complete same-process bounded pilot specs and resources; ordinary CI1/approval/run remain mandatory. Never extrapolate a historical tree-level anchor to loops or other models.'}
    result['parent_requests_production'] = _production_parent(spec, capture)
    capture.finish()
    return result


def validate_policy(value):
    _keys(value, ('schema_version', 'purpose', 'request', 'forecast'), 'generation efficiency declaration')
    if value['schema_version'] != 1 or type(value['schema_version']) is not int or value['purpose'] not in ('pilot', 'production'):
        raise ValueError('versioned pilot/production purpose required')
    if (value['purpose'] == 'pilot') != (value['forecast'] is None):
        raise ValueError('pilot has no production forecast; production requires one')
    return value


def prepare_pilot(production_pin, pilot_pin, rundir, *, base_dir):
    """Prepare real supplied ordinary spec, retaining its full parent objective."""
    from . import science
    capture = _Inputs(base_dir)
    production, pilot = capture.document(production_pin), capture.document(pilot_pin)
    science.validate(production); science.validate(pilot)
    if (production['mode'] != 'model-events' or pilot['mode'] != 'model-events' or
            production['schema_version'] != 2 or pilot['schema_version'] != 2 or
            production.get('goal_binding') != pilot.get('goal_binding') or
            production['review_policy'] != pilot['review_policy']):
        raise ValueError('same complete parent and ordinary generated-event review policy required')
    pbase, qbase = Path(production_pin['path']).parent, Path(pilot_pin['path']).parent
    if not pbase.is_absolute(): pbase = Path(base_dir) / pbase
    if not qbase.is_absolute(): qbase = Path(base_dir) / qbase
    p = process_profile(production['task'], pbase, _inputs=capture)
    q = process_profile(pilot['task'], qbase, _inputs=capture)
    if (p['profile_sha256'] != q['profile_sha256'] or q['events'] > p['events'] or
            pilot['max_seconds'] > production['max_seconds']):
        raise ValueError('pilot differs from production science or exceeds the declared ceiling')
    if 'generation_efficiency' in pilot:
        validate_policy(pilot['generation_efficiency'])
        if pilot['generation_efficiency']['purpose'] != 'pilot':
            raise ValueError('pilot producer cannot prepare production')
    capture.finish()
    # The existing producer binds source/input/runtime and writes real CI1.
    proposal = science.plan(rundir, pilot_pin['path'] if Path(pilot_pin['path']).is_absolute()
                            else str(Path(base_dir) / pilot_pin['path']))
    capture.finish()
    current_plan = science.verify_plan(rundir, approved=False)
    if current_plan != proposal: raise ValueError('prepared pilot plan changed before return')
    return {'schema_version': 1, 'kind': 'generation_pilot_prepared',
            'production': production_pin, 'pilot': pilot_pin, 'rundir': str(Path(rundir).absolute()),
            'process_profile_sha256': p['profile_sha256'], 'plan_sha256': execution.digest(proposal),
            'next_api': 'ravel.workflow.science.approve', 'approved': False,
            'executed': False, 'physics_validated': False}


def observe_pilot(root, *, base_dir):
    """Failed/incomplete attempts remain observations, never forecast admission.

    The source-owned command and phase journals may be absent after a very early
    failure. Their absence and running rows are retained rather than fabricated.
    """
    from . import science
    capture = _Inputs(base_dir); rd = science.root(root)
    plan = science.verify_plan(rd, approved=True)
    raw, _ = capture.read(rd / science.SPEC); spec = _document(raw)
    if spec['mode'] != 'model-events': raise ValueError('generated-event pilot required')
    profile = process_profile(spec['task'], plan['base_dir'], _inputs=capture)
    out = rd / plan['stages'][0]['outputs'][0]
    journals = {}
    for name in ('command-observations.jsonl', 'model-events-phase-observations.jsonl'):
        path = out / name
        if path.exists():
            data, pin = capture.read(path)
            journals[name] = {'pin': pin, 'rows': [_document(line) for line in data.splitlines() if line]}
        else: journals[name] = None
    errors = execution.validate_completed_execution(rd, plan['stages'])
    state, state_pin = capture.read(rd / execution.STATE_NAME)
    capture.read(rd / science.PLAN); capture.read(rd / science.APPROVAL)
    result = {'schema_version': 1, 'kind': 'generation_pilot_observation',
        'rundir': str(rd), 'profile': profile, 'execution_state': _document(state),
        'execution_state_pin': state_pin, 'completion_errors': errors, 'journals': journals,
        'ordinary_execution_completed': not errors, 'forecast_eligible': False, 'physics_validated': False,
        'scope': 'Completed phase elapsed times in unsuccessful attempts are lower bounds on attempted work only; running rows have no invented elapsed time. Source/runtime failures are RCA evidence, not a production rate.'}
    result['input_pins'] = capture.finish()
    return result


def _pilot(root, target, capture):
    from . import science
    rd = science.root(root); p = science.verify_plan(rd, approved=True)
    errors = execution.validate_completed_execution(rd, p['stages'])
    if errors: raise ValueError('pilot incomplete/stale; use observe_pilot for RCA: ' + '; '.join(errors))
    raw, _ = capture.read(rd / science.SPEC); spec = _document(raw)
    if spec['mode'] != 'model-events' or spec.get('goal_binding') != target.get('goal_binding'):
        raise ValueError('pilot parent/population differs')
    profile = process_profile(spec['task'], p['base_dir'], _inputs=capture)
    out = rd / p['stages'][0]['outputs'][0]
    raw, _ = capture.read(out / 'result.json'); result = _document(raw)
    if result.get('status') != 'passed' or result.get('physics_validated') is not False:
        raise ValueError('successful scoped operational pilot result required')
    raw, phase_pin = capture.read(out / 'model-events-phase-timing.json'); phases = _document(raw)
    if (phases.get('kind') != 'source_native_phase_observation' or phases.get('complete') is not True
            or phases.get('configuration_sha256') != profile['configuration']['sha256']):
        raise ValueError('actual complete source-bound pilot phase observation required')
    profile['machine'] = phases['machine']
    totals = phase_totals(phases['phases'], profile)
    for name in (science.PLAN, science.APPROVAL): capture.read(rd / name)
    raw, _ = capture.read(rd / execution.STATE_NAME)
    records = _document(raw)['stages']
    stage = records[p['stages'][0]['stage']]
    elapsed = (datetime.fromisoformat(stage['finished_utc']) - datetime.fromisoformat(stage['started_utc'])).total_seconds()
    if not math.isfinite(elapsed) or elapsed <= 0 or elapsed < sum(totals.values()):
        raise ValueError('ordinary stage wall observation is invalid/inconsistent; cannot calibrate overhead')
    totals['ordinary_stage_residual'] = elapsed - sum(totals.values())
    return {'rundir': str(rd), 'profile': profile, 'timing': phase_pin, 'phase_seconds': totals,
        'whole_stage_seconds': elapsed, 'clock_scope': 'Retained original stage UTC interval; clock observation, not monotonic OS authentication.'}


def phase_totals(rows, profile):
    totals = {key: 0.0 for key in PHASES}; seen = set()
    if type(rows) is not list or not rows: raise ValueError('complete phase population required')
    for row in rows:
        if row.get('phase') not in totals or row.get('state') != 'completed' or row.get('nested') is not False:
            raise ValueError('unsupported/incomplete/nested native phase cannot calibrate')
        seconds = row['wall_seconds']
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('finite phase wall time required')
        totals[row['phase']] += seconds; seen.add(row['phase'])
    required = {'build', 'survey', 'refine', 'combine_events', 'store_events'}
    c = profile['protected']
    if c['reweight']['mode'] != 'OFF': required.add('reweight')
    if c['shower']['backend'] != 'OFF': required.add('shower')
    if c['cards'].get('madspin') is not None: required.add('decay_events')
    if not required <= seen: raise ValueError('missing actual requested native phase')
    return totals


def forecast(production_pin, pilot_roots, *, base_dir, scaling_assumption, wall_margin):
    """Two comparable completed pilots; explicit local scaling, no confidence law."""
    if (type(pilot_roots) is not list or not 2 <= len(pilot_roots) <= 8 or
            len(set(pilot_roots)) != len(pilot_roots) or type(scaling_assumption) is not str or
            not scaling_assumption.strip() or type(wall_margin) not in (int,float) or
            not math.isfinite(wall_margin) or not 1 <= wall_margin <= 100):
        raise ValueError('two finite distinct pilots and an explicit empirical scaling/reserve declaration required')
    capture = _Inputs(base_dir); target = capture.document(production_pin)
    from . import science
    science.validate(target)
    if target['mode'] != 'model-events': raise ValueError('generation production spec required')
    pbase = Path(production_pin['path']).parent
    if not pbase.is_absolute(): pbase = Path(base_dir) / pbase
    profile = process_profile(target['task'], pbase, _inputs=capture)
    pilots = [_pilot(root, target, capture) for root in pilot_roots]
    for row in pilots:
        if (row['profile']['profile_sha256'] != profile['profile_sha256'] or
                row['profile']['machine'] != profile['machine'] or
                row['profile']['events'] > profile['events']):
            raise ValueError('pilot process/model/settings/machine/population differs')
    if len({row['profile']['events'] for row in pilots}) < 2:
        raise ValueError('distinct pilot sizes required before an event-count extrapolation')
    bounds = {}
    for phase in (*PHASES, 'ordinary_stage_residual'):
        values = [row['phase_seconds'][phase] * (1 if phase in ('build','survey') else
                  profile['events'] / row['profile']['events']) for row in pilots]
        bounds[phase] = [min(values), max(values) * wall_margin]
        if any(not math.isfinite(x) for x in bounds[phase]): raise ValueError('empirical cost arithmetic exceeds finite representation')
    total = [sum(row[i] for row in bounds.values()) for i in (0,1)]
    if any(not math.isfinite(x) for x in total): raise ValueError('empirical total exceeds finite representation')
    ceilings = {'ordinary_stage_seconds': target['max_seconds'],
                'native_configuration_seconds': profile['max_seconds']}
    fits = all(total[1] <= ceiling for ceiling in ceilings.values())
    result = {'schema_version': 1, 'kind': 'generation_empirical_forecast',
              'production': production_pin, 'profile': profile, 'pilots': pilots,
              'scaling_assumption': scaling_assumption, 'wall_margin': wall_margin,
              'phase_seconds': bounds, 'forecast_seconds': total, 'enforced_ceilings': ceilings,
              'decision': 'production_cost_forecast_available' if fits else 'budget_replan_required',
              'precision_status': 'requires_current_source_bound_precision_review',
              'scope': 'Local empirical cost only; scientifically accepted reuse is separate from observed timing. Survey fixed and refine/generation event-linear assumption is declared, not guaranteed. Mixed phases are not pure unweight/integration rates. No covariance/physics/production approval.',
              'execution_authorized': False, 'physics_validated': False,
              'next_api': 'ravel.workflow.research_cycle.design' if not fits else 'ravel.workflow.science.plan'}
    result['input_pins'] = capture.finish()
    for row in pilots:
        plan = science.verify_plan(row['rundir'], approved=True)
        if execution.validate_completed_execution(row['rundir'], plan['stages']):
            raise ValueError('pilot completion changed before forecast return')
    capture.finish()
    return result


def precision_evidence(declaration, target, pilots, capture, *, production_pin):
    """Check actual located estimator/target arrays AND current scoped review.

    No MC variance is invented here. The supplied estimator's scientific law is
    adjudicated by the existing review machinery, not by a generic pass label.
    """
    from . import physics_review
    _keys(declaration, ('evidence', 'review_rundir', 'check_id', 'claim_scope'), 'precision declaration')
    production = capture.document(production_pin)
    pbase = Path(production_pin['path']); pbase = pbase if pbase.is_absolute() else capture.base / pbase
    actual_profile = process_profile(production['task'], pbase.parent, _inputs=capture)
    if actual_profile != target: raise ValueError('precision production profile is not current')
    production_target = {'production': production_pin,
        'configuration': target['configuration'],
        'exposure': {'events': target['events'], 'seed': target['seed']}}
    evidence = capture.document(declaration['evidence'])
    _keys(evidence, ('schema_version', 'kind', 'profile_sha256', 'pilot_roots',
        'production', 'configuration', 'exposure', 'normalization_target',
        'estimator', 'sampling_design', 'estimator_source', 'covariance_source', 'normalization_source', 'target_source', 'unit', 'coordinates',
        'absolute_errors', 'absolute_targets'), 'precision evidence')
    if (evidence['schema_version'] != 2 or evidence['kind'] != 'generation_precision_evidence'
            or evidence['profile_sha256'] != target['profile_sha256']
            or evidence['pilot_roots'] != [row['rundir'] for row in pilots]):
        raise ValueError('precision must bind the actual process and complete pilot population')
    _keys(evidence['exposure'], ('events','seed'), 'precision exposure')
    if any(type(evidence['exposure'][key]) is not int for key in ('events','seed')):
        raise ValueError('exact integer precision exposure required')
    if any(evidence[key] != value for key, value in production_target.items()):
        raise ValueError('precision must bind exact current production/configuration/exposure')
    for key in ('estimator', 'sampling_design', 'unit', 'normalization_target'):
        if type(evidence[key]) is not str or not evidence[key].strip(): raise ValueError('explicit estimator and units required')
    for key in ('estimator_source','covariance_source','normalization_source'): capture.consume(evidence[key])
    source_target = capture.document(evidence['target_source'])
    _keys(source_target, ('schema_version','kind','profile_sha256','production','configuration',
        'exposure','normalization_target','unit','coordinates','absolute_targets'), 'precision target')
    if (source_target['schema_version'] != 2 or source_target['kind'] != 'generation_precision_target'
            or any(source_target[key] != evidence[key] for key in ('profile_sha256','production','configuration','exposure','normalization_target',
                'unit','coordinates','absolute_targets'))):
        raise ValueError('exact full precision target/population/units differs')
    coords = evidence['coordinates']
    if (type(coords) is not list or not coords or len(coords) > 4096 or
            any(type(x) is not str or not x for x in coords) or len(set(coords)) != len(coords)):
        raise ValueError('complete distinct precision coordinates required')
    for key in ('absolute_errors', 'absolute_targets'):
        values = evidence[key]
        if type(values) is not list or len(values) != len(coords): raise ValueError('precision population differs')
        if any(type(x) is not str or len(x) > 128 for x in values): raise ValueError('literal finite precision values required')
    def number(value):
        # Bound portable literal/rational decoding; no normalization or truncation.
        if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value):
            raise ValueError('decimal precision literal required')
        if 'e' in value.lower() and abs(int(value.lower().split('e')[1])) > 400:
            raise ValueError('precision exponent exceeds contract')
        result = Fraction(value)
        if max(result.numerator.bit_length(), result.denominator.bit_length()) > 2048:
            raise ValueError('precision rational exceeds contract')
        return result
    errors = [number(x) for x in evidence['absolute_errors']]
    targets = [number(x) for x in evidence['absolute_targets']]
    if any(x < 0 for x in errors) or any(x <= 0 for x in targets) or any(x > y for x,y in zip(errors,targets)):
        raise ValueError('MC precision target unmet; replan statistics/proposal/resources')
    rd = Path(declaration['review_rundir']); rd = rd if rd.is_absolute() else capture.base / rd
    status = physics_review.status(rd)
    if status.get('state') != 'accepted' or status.get('live_errors') or status.get('claim_scope') != declaration['claim_scope']:
        raise ValueError('current scientifically accepted named estimator/precision scope required')
    reg, events = physics_review._read(rd); view = physics_review._view(reg, events)
    key = declaration['check_id']
    if ({'id': key, 'kind': 'scientific'} not in reg['policy']['required_checks']
            or key not in reg['policy']['claim_scopes'][declaration['claim_scope']]['checks']):
        raise ValueError('precision check is outside accepted scientific scope')
    checks = [row for row in view['cycle']['checks'] if row['id'] == key]
    actual = Path(declaration['evidence']['path']); actual = actual if actual.is_absolute() else capture.base / actual
    if len(checks) != 1 or checks[0]['status'] != 'pass' or not any(
            physics_review._path(rd, ref['path']).absolute() == actual.absolute() for ref in checks[0]['evidence']):
        raise ValueError('accepted precision check must locate the exact estimator/target evidence')
    for path in (physics_review.HEAD, physics_review.POLICY, physics_review.REGISTRATION,
                 physics_review.DIRECTORY + '/events/' + format(view['cycle']['sequence'], '08d') + '.json'):
        capture.read(rd / path)
    return {'evidence': declaration['evidence'], 'review': declaration,
            'status': 'explicit_targets_met_in_current_scoped_review', 'physics_validated_by_this_helper': False}


def inputs(spec, base):
    capture = _Inputs(base)
    if 'generation_efficiency' not in spec:
        if _production_parent(spec, capture):
            raise ValueError('fresh full/scan generation needs same-process measured pilot and precision replan; prepare_pilot creates an ordinary bounded pilot without reducing the parent objective')
        return [Path(pin['path']) for pin in capture.finish()]
    value = validate_policy(spec['generation_efficiency'])
    request = capture.document(value['request'])
    _keys(request, ('schema_version','kind','production','pilots','scaling_assumption','wall_margin','precision'), 'generation efficiency request')
    if request['schema_version'] != 1 or request['kind'] != 'generation_efficiency_request': raise ValueError('versioned efficiency request required')
    production = capture.document(request['production'])
    current = deepcopy(spec); current.pop('generation_efficiency')
    if value['purpose'] == 'production':
        if current != production: raise ValueError('forecast must bind this exact production spec')
        committed = capture.document(value['forecast'])
        actual = forecast(request['production'], request['pilots'], base_dir=base,
            scaling_assumption=request['scaling_assumption'], wall_margin=request['wall_margin'])
        if committed != actual or actual['decision'] != 'production_cost_forecast_available':
            raise ValueError('current pilot forecast requires budget replan')
        for pin in actual['input_pins']: capture.read(pin['path'], pin)
        precision_evidence(request['precision'], actual['profile'], actual['pilots'], capture,
            production_pin=request['production'])
    else:
        profile = process_profile(current['task'], base, _inputs=capture)
        pbase = Path(request['production']['path']).parent
        if not pbase.is_absolute(): pbase = Path(base) / pbase
        target = process_profile(production['task'], pbase, _inputs=capture)
        if profile['profile_sha256'] != target['profile_sha256'] or profile['events'] > target['events']:
            raise ValueError('bounded pilot changes the production science')
    return [Path(pin['path']) for pin in capture.finish()]


def _publish(value, destination):
    # Metadata producer only: exclusive regular output, intended bytes. Consumers
    # always reauthenticate this commitment; no namespace permanence is claimed.
    p = Path(destination).absolute()
    if any(q.is_symlink() for q in (p, *p.parents)): raise ValueError('ordinary metadata destination required')
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with p.open('xb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if p.read_bytes() != raw: raise ValueError('published cost observation changed')
    return {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare-pilot','observe','forecast'))
    parser.add_argument('--request', required=True); parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv); capture = _Inputs(args.base)
    raw, _ = capture.read(args.request); request = _document(raw)
    if args.action == 'prepare-pilot':
        _keys(request, ('production','pilot','rundir'), 'pilot preparation')
        result = prepare_pilot(request['production'], request['pilot'], request['rundir'], base_dir=args.base)
    elif args.action == 'observe':
        _keys(request, ('rundir',), 'pilot observation')
        result = observe_pilot(request['rundir'], base_dir=args.base)
    else:
        _keys(request, ('production','pilots','scaling_assumption','wall_margin'), 'forecast preparation')
        result = forecast(request['production'], request['pilots'], base_dir=args.base,
            scaling_assumption=request['scaling_assumption'], wall_margin=request['wall_margin'])
    capture.finish(); pin = _publish(result, args.output); capture.finish()
    for source in result.get('input_pins', []): capture.read(source['path'], source)
    if Path(pin['path']).read_bytes() != (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n').encode():
        raise ValueError('cost output changed before return')
    print(json.dumps(pin, sort_keys=True))
    return 0


if __name__ == '__main__': main()
