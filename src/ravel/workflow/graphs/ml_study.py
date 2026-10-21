"""S1–S16 method study on the governed graph substrate.

The executor seam is a trusted, host-supplied object in BuildContext.extras,
never checkpoint or request data. It implements stage(stage, request, checks),
binding(scope, item), train(request), select(request), confirm(request), and
attribute(request); identity pins its implementation/environment. stage returns
pinned artifacts per check; train is a supervised training-only operation;
select names arms and pins its query ledger; confirm is evaluator-only.

Verdicts are never taken from the executor. The graph computes the checks it
owns from its own records and the exposure ledger. Every other check is
recomputed from the executor's pinned artifact by a registered validator
(BuildContext.extras['ml_validators']). Only the versioned requirement matrix
marks a check not applicable. A check without a validator is missing and blocks.

Population identities come from the pinned split manifest whose digest is the
study's split_sha256; no partition file is read to compute them. Train,
validation and confirm are claimed together before training, and the confirm
file is decoded only after its one charged read.

The supplied-data profile dispatches approved typed stages through controller.step.
Extended method studies retain every S1-S16 check and hold when their executor or
validator artifacts are missing. The atomic ml_training.run never substitutes for
a training-only stage. Graph software controls do not certify science.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import math
import re
import threading
from typing import TypedDict

from .. import effect_ledger, graph_nodes as nodes, graph_substrate, machine_lease
from ...physics import ml_exposure, ml_training

GRAPH_ID = 'ml.study'
ITEM_ID = 'ml.study_item'
IMPLEMENTATION = (__name__, 'ravel.physics.ml_exposure', 'ravel.physics.ml_training',
                  'ravel.workflow.machine_lease', 'ravel.workflow.execution_backend')
_LOCAL_LOCK = threading.Lock()  # machine_lease refuses a second holder in one process
CHECKS = {
    'S1': ('estimand-declared',),
    'S2': ('sample-provenance', 'feature-tier', 'duplicate-identities', 'observable-support',
           'trigger-plateau', 'benchmark-localization', 'statistics-sizing', 'nuisance-type', 'pretrain-disjoint'),
    'S3': ('partition-purpose', 'crossfit-audit', 'routing-coverage'),
    'S4': ('label-leakage', 'preprocessing-scope', 'duplicate-identities', 'noise-ceiling', 'sample-provenance'),
    'S5': ('baseline-set', 'oracle-labelled', 'published-isolation'),
    'S6': ('equal-budget', 'budget-curve', 'cost-preflight'),
    'S7': ('model-definition', 'nuisance-type'),
    'S8': ('inner-vs-replicate', 'replicate-count', 'seed-spread', 'test-once'),
    'S9': ('query-ledger', 'hypothesis-family', 'stopping-rule', 'confirmation-set', 'trials-accounting'),
    'S10': ('calibration-scope', 'calibration-reliability', 'paired-comparison', 'systematic-propagation',
            'null-execution', 'null-admissibility', 'null-calibration', 'injection-scope', 'toy-sizing'),
    'S11': ('selection-flatness', 'sideband-separability', 'spurious-signal', 'reference-fidelity',
            'fit-adequacy', 'control-distance', 'generator-robustness', 'score-transfer', 'input-support',
            'decorrelation-transfer', 'generator-closure', 'premise-equivalence'),
    'S12': ('test-once', 'freeze-order', 'confirm-scope', 'evaluator-immutable'),
    'S13': ('ablation-arms', 'attribution', 'confirm-scope'),
    'S14': ('claim-scope', 'report-binding', 'study-card', 'completion', 'model-definition', 'figure-scope'),
    'S15': ('repro-rerun', 'method-code-alignment', 'release-validation-pair'),
    'S16': ('claim-scope', 'completion', 'acceptance-evidence'),
}
CHECKS = {stage: tuple('check:ml-' + key for key in keys) for stage, keys in CHECKS.items()}

# Requirement matrix. Only these rules mark a check
# inapplicable; an executor or receipt cannot. Every stage result records the version.
MATRIX_VERSION = 'ml-requirement-matrix-1'
TASK_CLASSES = ('supervised_tagger', 'weakly_supervised_search', 'regression_calibration', 'surrogate', 'method_study')
_SEARCH_ONLY = tuple('check:ml-' + k for k in (
    'null-execution', 'null-admissibility', 'null-calibration', 'injection-scope', 'toy-sizing',
    'selection-flatness', 'sideband-separability', 'spurious-signal', 'reference-fidelity', 'fit-adequacy'))
_CROSSFIT_ONLY = ('check:ml-crossfit-audit', 'check:ml-routing-coverage')
_ATTRIBUTION = ('check:ml-ablation-arms', 'check:ml-attribution')
SPLIT_METHODS = ('explicit', 'hash', 'kfold_crossfit')
PARTITIONS = (('train', 'train_split', 'train'), ('validation', 'validation_split', 'train'),
              ('confirm', 'test_split', 'confirm'))
REMOTE_HOLD = 'remote placement awaits the owner decision on where remote work runs'


class State(nodes.BaseState, total=False):
    spec: dict
    item: dict
    ml_index: int
    ml_status: str
    ml_reason: str


class ItemView(TypedDict, total=False):
    meta: dict
    spec: dict
    item: dict


def executor(ctx):
    from .. import ml_executor
    value = ctx.extras.get('ml_executor') or ml_executor.current(ctx)
    if value is None:
        raise nodes.RecoveryHold('awaits the staged ML executor interface',
                                 'provide the supervised training-only and evaluator-owned stage interface')
    if not isinstance(value.identity, dict) or not value.identity:
        raise nodes.RecoveryHold('executor implementation identity required')
    return value


def _mechanism(spec):
    return any(c.get('kind') == 'mechanism' for c in spec.get('claims') or [])


def validate_spec(spec):
    if type(spec) is not dict or spec.get('claim_kind') not in ('diagnostic', 'method_performance'):
        raise nodes.RecoveryHold('ML study claim contract required')
    if type(spec.get('synthetic')) is not bool or not spec.get('study_id'):
        raise nodes.RecoveryHold('study family and evidence domain required')
    if spec.get('task_class') not in TASK_CLASSES:
        raise nodes.RecoveryHold('task class without a requirement-matrix row is unsupported')
    metrics = spec.get('metrics')
    if type(metrics) is not dict or type(metrics.get('primary')) is not str or not metrics['primary']:
        raise nodes.RecoveryHold('exactly one primary metric required')
    claims = spec.get('claims') or []
    if not claims:
        raise nodes.RecoveryHold('estimand required')
    for claim in claims:
        if claim.get('kind') not in ('performance', 'comparison', 'mechanism', 'finding'):
            raise nodes.RecoveryHold('unsupported interval or coverage claim')
        estimand = claim.get('estimand') or {}
        if not all(k in estimand for k in ('metric', 'population', 'reference', 'working_point')):
            raise nodes.RecoveryHold('estimand population, metric and working-point reference required')
        if claim['kind'] in ('comparison', 'mechanism') and not isinstance(claim.get('margin'), (int, float)):
            raise nodes.RecoveryHold('practical-equivalence margin required')
    seeds = spec.get('seeds') or []
    minimum = 3 if spec.get('rung') == 'smoke' and spec['claim_kind'] == 'diagnostic' else 5
    if len(seeds) < minimum or len(seeds) > 32 or any(type(s) is not int or s < 0 for s in seeds) or len(set(seeds)) != len(seeds):
        raise nodes.RecoveryHold('insufficient or duplicate paired replicates')
    arms = spec.get('arms') or []
    if not arms or len(arms) > 32 or len({a['id'] for a in arms}) != len(arms):
        raise nodes.RecoveryHold('bounded unique arm population required')
    if any(a.get('role') not in ('baseline', 'candidate', 'ceiling', 'ablation') for a in arms):
        raise nodes.RecoveryHold('known method arm roles required')
    if any(not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,39}', a['id']) for a in arms):
        raise nodes.RecoveryHold('safe arm identifiers required')
    if not any(a.get('role') == 'baseline' for a in arms) or not any(a.get('role') == 'candidate' for a in arms):
        raise nodes.RecoveryHold('baseline and candidate required')
    if any('budget' in a for a in arms):
        raise nodes.RecoveryHold('arms take the study budget; arm-level budgets are refused')
    budget = spec.get('budget') or {}
    cap = budget.get('cpu_seconds_per_replicate')
    if (budget.get('equal_across_arms') is not True or type(budget.get('max_select_queries')) is not int
            or budget['max_select_queries'] < 1 or type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0):
        raise nodes.RecoveryHold('equal budgets, a per-replicate CPU cap and bounded selection queries required')
    if not effect_ledger.SHA.fullmatch(spec.get('split_sha256', '')):
        raise nodes.RecoveryHold('frozen split digest required')
    if (spec.get('split_manifest') or {}).get('sha256') != spec['split_sha256']:
        raise nodes.RecoveryHold('split digest must pin the split manifest')
    attribution = spec.get('attribution')
    if attribution is None:
        if _mechanism(spec):
            raise nodes.RecoveryHold('mechanism claim requires attribution')
    else:
        if attribution.get('scope') != 'joint_confirm':
            raise nodes.RecoveryHold('reserved attribution samples await the staged executor; joint confirmation only')
        if attribution.get('mode') not in ('fixed-configuration', 'retuned'):
            raise nodes.RecoveryHold('fixed-configuration or retuned attribution required')
    if type(spec.get('placement', {}).get('local')) is not bool:
        raise nodes.RecoveryHold('declared placement required')
    if spec['placement']['local'] is not True:
        raise nodes.RecoveryHold(REMOTE_HOLD)
    return spec


def split_manifest(root, spec):
    """Per-partition identities and the evidence class from the pinned manifest; no partition file is read."""
    pin = spec['split_manifest']
    path = Path(pin['path'])
    path = path if path.is_absolute() else Path(root) / path
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise nodes.RecoveryHold('symlink split manifest refused')
    try:
        if ml_training.pin(path)['sha256'] != pin['sha256']:
            raise ValueError('split manifest changed')
        manifest = json.loads(path.read_bytes())
        if manifest.get('kind') != 'ml-split-manifest' or manifest.get('method') not in SPLIT_METHODS:
            raise ValueError('split manifest kind and method required')
        if (manifest.get('provenance') or {}).get('class') not in ('synthetic', 'observed'):
            raise ValueError('split manifest evidence class required')
        partitions = manifest.get('partitions') or {}
        identities = {}
        for name, _, _ in PARTITIONS:
            row = partitions.get(name) or {}
            identities[name] = ml_exposure.manifest_identity(row, (row.get('pin') or {}).get('sha256'))
        if partitions['confirm'].get('pin') != spec.get('confirm'):
            raise ValueError('confirm population differs from the manifest confirm partition')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise nodes.RecoveryHold('pinned split manifest required', str(exc)) from exc
    names = list(identities)
    if any(ml_exposure.overlaps(identities[a], identities[b]) for i, a in enumerate(names) for b in names[:i]):
        raise nodes.RecoveryHold('split manifest partitions overlap')
    if (manifest['provenance']['class'] == 'synthetic') is not spec['synthetic']:
        raise nodes.RecoveryHold('declared evidence class differs from the split manifest provenance')
    return {'method': manifest['method'], 'synthetic': spec['synthetic'], 'identities': identities}


def not_applicable(spec, manifest_method):
    """The matrix's inapplicable checks for this route, each with its reason."""
    rows = {}
    if spec['task_class'] != 'weakly_supervised_search':
        rows.update({c: f"task class {spec['task_class']} has no search, null or sculpting estimand" for c in _SEARCH_ONLY})
    if manifest_method != 'kfold_crossfit':
        rows.update({c: f'split method {manifest_method} has no cross-fit routing' for c in _CROSSFIT_ONLY})
    if not ablation_arms(spec) and not _mechanism(spec):
        rows.update({c: 'no mechanism claim and no attribution contrasts' for c in _ATTRIBUTION})
    if not any(a['role'] == 'ceiling' for a in spec['arms']):
        rows['check:ml-oracle-labelled'] = 'no oracle ceiling arm'
    return rows


def generated_ablations(spec):
    """Generate descriptors; the staged executor compiles them to model specs.

    They enter the training population at S7 and the selection freeze at S9.
    S13 only reads their already returned joint-confirmation scores.
    """
    rows = []
    for arm in spec['arms']:
        if arm.get('role') != 'candidate':
            continue
        components = arm.get('components', [])
        if len(components) != len(set(components)) or len(components) > 16:
            raise nodes.RecoveryHold('bounded unique components required')
        if spec.get('attribution') is None:
            continue
        contrasts = [('remove-one', [component]) for component in components]
        contrasts += [('controls-only', [])] if components else []
        contrasts += [('remove-set', group) for group in arm.get('component_groups', [])]
        contrasts += [('add-one', [component]) for component in components] if arm.get('add_one') is True else []
        for index, (kind, group) in enumerate(contrasts):
            if any(c not in components for c in group) or (kind == 'remove-set' and len(group) < 2):
                raise nodes.RecoveryHold('invalid redundant component group')
            rows.append({'id': f"{arm['id']}_ab{index}", 'role': 'ablation', 'parent': arm['id'],
                         'contrast': kind, 'components': group, 'mode': spec['attribution'].get('mode')})
    if _mechanism(spec) and not rows:
        raise nodes.RecoveryHold('mechanism claim requires generated attribution contrasts')
    if set(a['id'] for a in rows) & set(a['id'] for a in spec['arms']):
        raise nodes.RecoveryHold('generated ablation id collision')
    return rows


def ablation_arms(spec):
    return generated_ablations(spec) + [deepcopy(a) for a in spec['arms'] if a['role'] == 'ablation']


def _item_key(spec, arm_id, seed):
    return f"{arm_id}__seed_{seed}__split_{spec['split_sha256']}"


def training_items(spec):
    arms = spec['arms'] + generated_ablations(spec)
    return [{'key': _item_key(spec, arm['id'], seed), 'arm': deepcopy(arm), 'seed': seed, 'phase': 'train'}
            for arm in arms for seed in spec['seeds']]


def _public_spec(spec):
    return {k: deepcopy(v) for k, v in spec.items() if k != 'confirm'}


def _request(state, stage):
    return {'stage': stage, 'spec': _public_spec(state['spec']),
            'results': deepcopy(state.get('results') or {})}


# ---- computed checks -------------------------------------------------------------------

def _ledger_record(sha):
    return ml_exposure._load(ml_exposure._record_path(sha))


def _confirm_record(ctx, state):
    return _ledger_record(split_manifest(ctx.scope_root, state['spec'])['identities']['confirm']['sha256'])


def _confirm_reads(ctx, state):
    record = _confirm_record(ctx, state)
    return [] if record is None else record['reads']


def _batch_keys(state):
    selection = state['results']['selection']
    return sorted(selection['confirm_items'] + [_item_key(state['spec'], a['id'], seed)
                                                for a in selection['ablation_arms'] for seed in state['spec']['seeds']])


def _graph_checks(ctx, state, stage):
    """Checks the graph recomputes from its own records and the exposure ledger."""
    results = state.get('results') or {}
    out = {}
    if stage == 'S1':
        validate_spec(state['spec'])
        out['check:ml-estimand-declared'] = 'pass'
    elif stage == 'S3':
        split_manifest(ctx.scope_root, state['spec'])
        out['check:ml-partition-purpose'] = 'pass'
    elif stage == 'S6':
        out['check:ml-equal-budget'] = 'pass' if all('budget' not in a for a in state['spec']['arms']) else 'fail'
    elif stage == 'S8':
        census = results.get('replicates') or {}
        out['check:ml-replicate-count'] = 'pass' if census.get('per_arm') and not census.get('blocking') else 'fail'
        out['check:ml-test-once'] = 'pass' if _confirm_reads(ctx, state) == [] else 'fail'
    elif stage == 'S9':
        selection = results.get('selection') or {}
        try:
            intact = ml_training.pin(selection['query_ledger']['path']) == selection['query_ledger']
        except (OSError, KeyError, TypeError):
            intact = False
        out['check:ml-query-ledger'] = 'pass' if intact else 'fail'
        baselines = {a['id'] for a in state['spec']['arms'] if a['role'] == 'baseline'}
        expected = sorted(_item_key(state['spec'], arm, seed) for arm in selection.get('selected', [])
                          for seed in state['spec']['seeds'])
        out['check:ml-confirmation-set'] = ('pass' if baselines <= set(selection.get('selected', []))
                                            and expected == sorted(selection.get('confirm_items', [])) else 'fail')
    elif stage in ('S12', 'S13'):
        reads = _confirm_reads(ctx, state)
        frozen = (results.get('freeze') or {}).get('pin')
        scope = 'pass' if [r['context'] for r in reads] == ['confirm'] else 'fail'
        if stage == 'S12':
            out['check:ml-test-once'] = 'pass' if len(reads) == 1 else 'fail'
            out['check:ml-freeze-order'] = 'pass' if reads and reads[0]['selection'] == frozen else 'fail'
            out['check:ml-confirm-scope'] = scope
        else:
            out['check:ml-confirm-scope'] = scope
            scores = (results.get('confirmation') or {}).get('scores') or {}
            ablations = {_item_key(state['spec'], a['id'], seed) for a in ablation_arms(state['spec'])
                         for seed in state['spec']['seeds']}
            if ablations:
                out['check:ml-ablation-arms'] = 'pass' if ablations <= set(scores) else 'fail'
    return out


def _validator(ctx):
    value = ctx.extras.get('ml_validators')
    if value is None or not isinstance(getattr(value, 'identity', None), dict) or not value.identity:
        return None
    return value


def _artifact(ctx, pin):
    try:
        path = Path(pin['path'])
        if (any(p.is_symlink() for p in (path, *path.parents))
                or not path.resolve().is_relative_to(Path(ctx.scope_root).resolve())
                or ml_training.pin(path) != pin):
            return None
        return path.read_bytes()
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _stage(ctx, state, stage):
    if stage == 'S1':
        validate_spec(state['spec'])
        if ctx.instance['study'] != state['spec']['study_id']:
            raise nodes.RecoveryHold('graph instance differs from study family')
    manifest = split_manifest(ctx.scope_root, state['spec'])
    result = executor(ctx).stage(stage, _request(state, stage), CHECKS[stage])
    if type(result) is not dict or nodes.lint_state(result):
        raise nodes.RecoveryHold(f'{stage} invalid evaluator result')
    artifacts = result.get('artifacts') or {}
    inapplicable = not_applicable(state['spec'], manifest['method'])
    owned = _graph_checks(ctx, state, stage)
    validator = _validator(ctx)
    checks = {}
    for key in CHECKS[stage]:
        if key in owned:
            checks[key] = {'verdict': owned[key], 'source': 'graph'}
        elif key in inapplicable:
            checks[key] = {'verdict': 'not_applicable', 'source': MATRIX_VERSION, 'reason': inapplicable[key]}
        elif type(artifacts.get(key)) is not dict:
            checks[key] = {'verdict': 'missing', 'source': 'none', 'reason': 'no pinned artifact; a literal verdict is not evidence'}
        elif validator is None:
            checks[key] = {'verdict': 'missing', 'source': 'none', 'reason': 'no registered validator recomputes this check'}
        else:
            raw = _artifact(ctx, artifacts[key])
            verdict = 'missing' if raw is None else validator.validate(key, raw, {'stage': stage, 'spec': _public_spec(state['spec']),
                                                                                 'results': deepcopy(state.get('results') or {})})
            checks[key] = {'verdict': verdict if verdict in ('pass', 'fail', 'unresolved', 'missing') else 'fail',
                           'source': 'validator', 'validator': deepcopy(validator.identity), 'artifact': artifacts[key]}
    blocking = [key for key, row in checks.items() if row['verdict'] not in ('pass', 'not_applicable')]
    if stage == 'S16' and state['spec']['claim_kind'] == 'method_performance' and not _acceptance_authority(ctx, state, result):
        checks['check:ml-acceptance-evidence'] = {'verdict': 'fail', 'source': 'graph', 'reason': 'R3 acceptance authority absent'}
        blocking.append('check:ml-acceptance-evidence')
    result = {**{k: v for k, v in result.items() if k != 'checks'}, 'checks': checks, 'matrix_version': MATRIX_VERSION}
    if stage == 'S15':
        blocking += _record_rerun_replays(ctx, state, result)
    if blocking:
        # Validation outcomes are kept for reporting, but may not open confirmation.
        result['blocking'] = sorted(set(blocking))
    return result


def _acceptance_authority(ctx, state, result):
    """Synthetic fixtures may close on a machine R3 case; observed data needs the RDJ receipt with a human approver."""
    if state['spec']['synthetic']:
        rdj = result.get('rdj') or {}
        return (rdj.get('class') == 'R3' and rdj.get('claim_kind') == 'method_performance'
                and rdj.get('authority') in ('human', 'machine'))
    from .. import rdj_loop
    try:
        accepted = rdj_loop.authorizing_receipt(Path(ctx.scope_root), 'final_task', _action(state, 'S16'))
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return bool(accepted and accepted['case'].get('risk', {}).get('class') == 'R3'
                and (accepted.get('review_independence') or {}).get('human_approver') is True)


def _record_rerun_replays(ctx, state, result):
    """S15 declares its withheld reads; each one is a replay entry against the frozen confirmation."""
    reads = result.get('withheld_reads')
    if type(reads) is not int or reads < 0:
        return ['check:ml-repro-rerun']
    confirmation = state['results'].get('confirmation') or {}
    for _ in range(reads):
        try:
            ml_exposure.record_replay(confirmation['exposure_ledger'], effect_ledger.digest(state['spec']),
                                      'confirm', confirmation['freeze'])
        except (KeyError, TypeError, ValueError):
            return ['check:ml-repro-rerun']
    return []


def _write(ctx, name, record):
    path = Path(ctx.scope_root) / 'research/ml' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise nodes.RecoveryHold('symlink study artifact refused')
    if path.exists():
        if json.loads(path.read_bytes()) != record:
            raise nodes.RecoveryHold('immutable study record changed')
    else:
        ml_training._write_new(path, record)
    return ml_training.pin(path)


def _action(state, stage):
    return {'digest': effect_ledger.digest({'spec': state['spec'], 'stage': stage,
                                          'results': state.get('results') or {}})}


def _unblind_action(state):
    """The unblind gate sees what is unblinded: spec, validation verdicts, scope and evidence class."""
    results = state.get('results') or {}
    selection = results.get('selection') or {}
    body = {'spec_sha256': effect_ledger.digest(state['spec']),
            'validation': (results.get('validation') or {}).get('pin'),
            'freeze': (results.get('freeze') or {}).get('pin'),
            'selected': selection.get('selected'), 'unblinded_scope': _batch_keys(state) if selection else [],
            'observed': not state['spec']['synthetic']}
    return {'kind': 'ml_confirmation', **body, 'digest': effect_ledger.digest(body)}


def _standard(builder, graph_id):
    nodes.add(builder, 'decision_turn', nodes.decision_turn(graph_id), graph_id=graph_id)
    nodes.add(builder, 'reconcile', nodes.reconcile(), graph_id=graph_id)
    nodes.add(builder, 'hold', nodes.hold('ML study gate or contract unresolved'), graph_id=graph_id)


def _effect(ctx, name, run, *, key=None, gate=None, segment=None, kind='compute'):
    return nodes.effect(name, kind=kind, implementation=IMPLEMENTATION,
                        segment=segment or (lambda s: {'stage': name, 'split': s['spec']['split_sha256']}),
                        identity=lambda s: {'spec_sha256': effect_ledger.digest(s['spec']),
                                            'executor': executor(ctx).identity,
                                            'action_bytes_sha256': _action(s, name)['digest'],
                                            'item': s.get('item')},
                        run=run, gate=gate,
                        to_state=lambda s, r: {'results': {key or name: r}})


def _leased(ctx, item, call):
    # Threads in a Send superstep serialize in-process; independent processes
    # wait on the actual shared lease. Production bindings remain mandatory.
    service = executor(ctx)
    with _LOCAL_LOCK:
        with machine_lease.held(item['key'], rundir=str(ctx.scope_root), node_id=item['key'],
                                binding=service.binding(ctx.scope_root, item),
                                wait_seconds=machine_lease.default_wait_seconds()):
            return call()


def _train(ctx, state):
    item = state['item']
    service = executor(ctx)
    if state['spec']['placement']['local'] is not True:
        raise nodes.RecoveryHold(REMOTE_HOLD)
    request = {'key': item['key'], 'arm': item['arm'], 'seed': item['seed'], 'budget': deepcopy(state['spec']['budget']),
               'spec': _public_spec(state['spec']), 'split_sha256': state['spec']['split_sha256']}
    return _leased(ctx, item, lambda: service.train(request))


def build_item(ctx):
    from langgraph.graph import START, END, StateGraph
    builder = StateGraph(State, input_schema=ItemView)
    def run(state, ident):
        if state['item']['phase'] == 'train':
            return _train(ctx, state)
        request = {'key': state['item']['key'], 'contrast': state['item']['arm'],
                   'confirmation': state['item']['confirmation']}
        return _leased(ctx, state['item'], lambda: executor(ctx).attribute(request))
    node = _effect(ctx, 'execute', run, gate='launch', kind='native',
                   segment=lambda s: {'arm': s['item']['arm']['id'], 'seed': s['item'].get('seed', 0),
                                      'split': s['spec']['split_sha256'], 'phase': s['item']['phase']})
    original = node.function
    def completed(state):
        try:
            update = original(state)
        except nodes.GateRefused as refused:
            # A gate refusal is a hold with its cause, never a training failure.
            errors = [e if type(e) is dict else {'provider': getattr(e, 'provider', ''), 'message': str(e)}
                      for e in refused.errors or []]
            cause = '; '.join(f"{e.get('provider')}: {e.get('code', '')} {e.get('message')}".strip() for e in errors)
            return {'results': {'execute': {'status': 'gate_refused', 'gate': 'launch', 'errors': errors}},
                    'status': {'phase': 'gate', 'terminal': 'hold', 'reason': 'launch gate refused: ' + cause,
                               'would_make_possible': None}}
        receipt = update['results']['execute']
        if receipt.get('status') == 'failed':
            update['status'] = {'terminal': 'failed', 'reason': receipt.get('error', 'training failed')}
        return update
    node.function = completed
    nodes.add(builder, 'execute', node, graph_id=ITEM_ID)
    _standard(builder, ITEM_ID)
    builder.add_edge(START, 'execute')
    builder.add_edge('execute', END)
    return builder


def _claim(ctx, state, *, resume):
    """One claim of train, validation and confirm, keyed by a token persisted in the study scope."""
    spec = state['spec']
    identities = split_manifest(ctx.scope_root, spec)['identities']
    path = Path(ctx.scope_root) / 'research/ml/exposure-claim.json'
    digest = effect_ledger.digest(spec)
    if path.is_file() and not path.is_symlink():
        token = json.loads(path.read_bytes()).get('token')
    elif resume:
        raise nodes.RecoveryHold('confirm population spent or unresolved', 'no exposure claim was recorded before training')
    else:
        token = ml_exposure.Study(digest).token
    claim = _write(ctx, 'exposure-claim.json', {'spec_sha256': digest, 'token': token})
    study = ml_exposure.Study(digest, token)
    items = [(identities[name], role) for name, role, _ in PARTITIONS]
    schedule = {identities[name]['sha256']: [context] for name, _, context in PARTITIONS
                if name != 'validation'}
    schedule[identities['validation']['sha256']] = ['train']
    try:
        study.claim_all(items, schedule=schedule)
    except ValueError as exc:
        raise nodes.RecoveryHold('confirm population spent or unresolved', str(exc)) from exc
    return study, identities, claim


def _family_record(spec):
    """Append this specification to its hypothesis family's trials record; return the earlier ones."""
    directory = ml_exposure.root() / 'families'
    path = directory / (effect_ledger.digest({'study_id': spec['study_id']}) + '.json')
    digest = effect_ledger.digest(spec)
    with ml_exposure._locked():
        directory.mkdir(exist_ok=True)
        if path.is_symlink():
            raise nodes.RecoveryHold('symlink family record refused')
        record = json.loads(path.read_text()) if path.exists() else {'study_id': spec['study_id'], 'specs': []}
        prior = [row for row in record['specs'] if row != digest]
        if digest not in record['specs']:
            record['specs'].append(digest)
            ml_exposure.atomic_json(path, record)
    return prior


def training_start(ctx, state):
    """Claim every population, charge the training-phase reads once, and record the trial."""
    spec = state['spec']
    study, identities, claim = _claim(ctx, state, resume=False)
    freeze = _write(ctx, 'training-freeze.json', {'spec_sha256': effect_ledger.digest(spec),
                                                  'models': [item['key'] for item in training_items(spec)]})
    for name in ('train', 'validation'):
        sha = identities[name]['sha256']
        if not any(r['context'] == 'train' for r in (_ledger_record(sha) or {}).get('reads', [])):
            study.read(sha, 'train', freeze)
    return {'count': len(training_items(spec)), 'claim': claim, 'training_freeze': freeze,
            'family_prior_specs': _family_record(spec)}


def replicate_census(ctx, state):
    """Every arm needs one ok replicate per declared seed within the CPU cap; nothing is dropped."""
    spec = state['spec']
    rows = state['results']
    refused = [rows[i['key']] for i in training_items(spec)
               if (rows[i['key']].get('status') or {}).get('reason', '').startswith('launch gate refused')]
    if refused:
        raise nodes.RecoveryHold('training refused at the launch gate, before any training: '
                                 + refused[0]['status']['reason'].removeprefix('launch gate refused: '),
                                 'register and activate the launch providers the gate names')
    cap = spec['budget']['cpu_seconds_per_replicate']
    per_arm, blocking = {}, []
    for item in training_items(spec):
        row = rows[item['key']]
        receipt = (row.get('results') or {}).get('execute') or {}
        cpu = receipt.get('cpu_seconds')
        arm = per_arm.setdefault(item['arm']['id'], {'role': item['arm']['role'], 'expected': len(spec['seeds']),
                                                     'ok': 0, 'cpu_seconds': 0.0, 'failures': []})
        if row['outcome'] != 'ok':
            arm['failures'].append({'key': item['key'], 'outcome': row['outcome'],
                                    'reason': (row.get('status') or {}).get('reason')})
        elif type(cpu) not in (int, float) or not math.isfinite(cpu) or not 0 <= cpu <= cap:
            arm['failures'].append({'key': item['key'], 'outcome': 'budget', 'reason': 'CPU seconds missing or above the cap'})
        else:
            arm['ok'] += 1
            arm['cpu_seconds'] += cpu
    for arm_id, arm in sorted(per_arm.items()):
        if arm['ok'] != arm['expected']:
            blocking.append(f"{arm_id}: {arm['ok']} of {arm['expected']} replicates")
    return {'per_arm': per_arm, 'blocking': blocking}


def _selection(ctx, state):
    spec = state['spec']
    rows = state['results']
    roles = {a['id']: a['role'] for a in spec['arms']}
    candidates = {arm: {_item_key(spec, arm, seed): rows[_item_key(spec, arm, seed)] for seed in spec['seeds']}
                  for arm, role in roles.items() if role != 'ablation'}
    selection = executor(ctx).select({'candidates': candidates, 'spec': _public_spec(spec)})
    selected = selection.get('selected') or []
    queries = selection.get('queries')
    if not selected or len(selected) != len(set(selected)) or any(k not in candidates for k in selected):
        raise nodes.RecoveryHold('selection names whole candidate arms, never single replicates')
    if any(roles[k] == 'ceiling' for k in selected):
        # Ceilings can be reported but cannot win a real-method comparison.
        raise nodes.RecoveryHold('oracle ceiling cannot be selected as an available method')
    if not {a for a, r in roles.items() if r == 'baseline'} <= set(selected):
        raise nodes.RecoveryHold('selection must carry every baseline arm into confirmation')
    try:
        ledger_pin = selection['query_ledger']
        if ml_training.pin(ledger_pin['path']) != ledger_pin:
            raise ValueError
        entries = json.loads(Path(ledger_pin['path']).read_bytes())
        if not isinstance(entries, list) or any(type(e) is not dict or e.get('arm') not in candidates for e in entries):
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise nodes.RecoveryHold('pinned query ledger with one entry per evaluator response required') from exc
    if type(queries) is not int or queries != len(entries) or not 0 < queries <= spec['budget']['max_select_queries']:
        raise nodes.RecoveryHold('selection query count must equal its ledger and stay within budget')
    record = {'kind': 'ml-selection-receipt', 'spec_sha256': effect_ledger.digest(spec),
              **selection, 'selected': sorted(selected),
              'confirm_items': sorted(key for arm in selected for key in candidates[arm]),
              'ablation_arms': ablation_arms(spec), 'trained': candidates,
              'failures': [r for r in nodes.joined(state) if r.get('outcome') in ('failed', 'held')]}
    return {**record, 'pin': _write(ctx, 'selection.json', record)}


def freeze_confirmation(ctx, state):
    spec = state['spec']
    selected = state['results']['selection']
    batch = _batch_keys(state)
    freeze = {'spec_sha256': effect_ledger.digest(spec), 'selection': selected['selected'],
              'selected': selected['selected'], 'selection_receipt': selected['pin'],
              'ablation_arms': selected['ablation_arms'], 'split_sha256': spec['split_sha256'],
              'checkpoints': {key: state['results'][key] for key in batch}}
    return _write(ctx, 'spec-freeze.json', freeze)


CONFIRM_KEYS = {'test_reads', 'reported', 'verdict', 'scores', 'artifacts'}


def confirm_batch(ctx, state):
    """One atomic exposure, reserved before evaluation; failures permanently spend it."""
    spec = state['spec']
    selected = state['results']['selection']
    if selected['spec_sha256'] != effect_ledger.digest(spec):
        raise nodes.RecoveryHold('selection specification changed before confirm')
    if ml_training.pin(selected['pin']['path']) != selected['pin']:
        raise nodes.RecoveryHold('selection receipt changed before confirm')
    blockers = [stage for stage in ('S4', 'S5', 'S6', 'S7', 'S8', 'S9', 'S10', 'S11')
                if state['results'].get(stage, {}).get('blocking')]
    if blockers:
        raise nodes.RecoveryHold('validation blocks confirmation: ' + ', '.join(blockers))
    frozen = freeze_confirmation(ctx, state)
    if state['results'].get('freeze', {}).get('pin') != frozen:
        raise nodes.RecoveryHold('confirmation freeze must precede unblind request')
    errors = nodes.check_gate(ctx.scope_root, 'unblind', _unblind_action(state), graph_id=GRAPH_ID)
    if errors:
        raise nodes.GateRefused('unblind refused confirmation', errors)
    # The claim made before training is resumed; nothing is decoded before the charged read.
    study, identities, _ = _claim(ctx, state, resume=True)
    confirm = identities['confirm']
    try:
        study.read(confirm['sha256'], 'confirm', frozen)
    except ValueError as exc:
        raise nodes.RecoveryHold('confirm population spent or unresolved', str(exc)) from exc
    batch = _batch_keys(state)
    try:
        ml_exposure.verify_identifiers(spec['confirm'], ctx.scope_root, confirm)
        result = executor(ctx).confirm({'population': spec['confirm'], 'selected': selected['selected'],
                                       'selection_receipt': selected['pin'], 'freeze': frozen,
                                       'batch': json.loads(Path(frozen['path']).read_bytes())['checkpoints'],
                                       'ablation_arms': selected['ablation_arms']})
        if (type(result) is not dict or set(result) - CONFIRM_KEYS or type(result.get('test_reads')) is not int
                or result['test_reads'] != 1 or sorted(result.get('reported', [])) != selected['selected']
                or type(result.get('scores')) is not dict or sorted(result['scores']) != batch):
            raise nodes.RecoveryHold('one confirmation read scoring exactly the frozen batch required')
        result = {**result, 'freeze': frozen, 'exposure_ledger': study.provenance()}
        receipt = _write(ctx, 'confirmation.json', result)
        study.close('complete', receipt)
        return {**result, 'pin': receipt}
    except BaseException:
        study.close('failed')
        raise


def _role(ctx, role, name):
    """Governed role worker; host-only doubles are honoured only in the test lease domain."""
    factory = ctx.extras.get('ml_role_factory')
    if factory is not None:
        if machine_lease.domain() != 'test':
            def refused(state, ident):
                raise nodes.RecoveryHold('role doubles are test-only; governed ML role workers required')
            node = nodes.effect(name, kind='compute', implementation=IMPLEMENTATION, run=refused,
                                identity=lambda s: {'role': role, 'spec_sha256': effect_ledger.digest(s['spec'])},
                                segment=lambda s: {'role': role, 'stage': name},
                                to_state=lambda s, r: {'results': {name: r}})
        else:
            node = factory(role, name)
    else:
        def spec(state):
            service = executor(ctx)
            if not hasattr(service, 'worker_spec'):
                raise nodes.RecoveryHold('awaits ML role worker specification')
            return service.worker_spec(role, _request(state, name))
        node = nodes.agent(name, rundir=ctx.scope_root, spec=spec,
                           segment=lambda s: {'role': role, 'stage': name},
                           to_state=lambda s, r: {'results': {name: r}})
    node.role = role
    return node


def build(ctx):
    from .. import ml_executor
    from langgraph.graph import START, END, StateGraph
    builder = StateGraph(State)
    child_ctx = graph_substrate.BuildContext(ctx.scope_root, ITEM_ID, 1, ctx.instance, extras=ctx.extras)
    child = graph_substrate.build(ITEM_ID, child_ctx)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=GRAPH_ID)
    _standard(builder, GRAPH_ID)
    add('planner', _role(ctx, 'ml-planner', 'planner'))
    add('designer', _role(ctx, 'ml-trainer', 'designer'))
    builder.add_edge('planner', 'S1')
    builder.add_edge('designer', 'S7')

    def stage_run(stage):
        def run(state, ident):
            if stage == 'S16' and ('confirmation' not in state.get('results', {}) or
                                   any(state['results'].get(k, {}).get('blocking') for k in CHECKS if k != 'S16')):
                raise nodes.RecoveryHold('validation outcome reported; confirmation and acceptance remain unresolved')
            result = _stage(ctx, state, stage)
            if stage == 'S3':
                result['split_sha256'] = state['spec']['split_sha256']
            return result
        return run
    for index in range(1, 17):
        stage = f'S{index}'
        add(stage, _effect(ctx, stage, stage_run(stage)))
        if index not in (7, 8, 9, 11, 12, 13, 14, 15, 16):
            nodes.connect(builder, stage, nodes.route(lambda s, k=stage: 'blocked' if s['results'][k].get('blocking') else 'pass',
                          {'blocked': 'report', 'pass': 'designer' if index == 6 else f'S{index + 1}'}))
    # Fan-out includes generated attribution models before the withheld read.
    edge, mapped = nodes.map_node(lambda s: training_items(s['spec']), lambda item: item['key'], child,
                                  lambda s, item: {'spec': _public_spec(s['spec']), 'item': item}, name='train')
    add('train', mapped)
    add('training_start', _effect(ctx, 'training_start', lambda s, i: training_start(ctx, s), kind='journal'))
    nodes.connect(builder, 'S7', nodes.route(lambda s: 'blocked' if s['results']['S7'].get('blocking') else 'pass',
                                          {'blocked': 'report', 'pass': 'spend_gate'}))
    add('spend_gate', nodes.gate('spend_above_ceiling', lambda s: _action(s, 'training_start')))
    nodes.connect(builder, 'spend_gate', nodes.gate_route('spend_above_ceiling', passed='training_start', refused='hold'))
    nodes.connect(builder, 'training_start', edge)
    add('replicates', _effect(ctx, 'replicates', lambda s, i: replicate_census(ctx, s)))
    builder.add_edge('train', 'replicates')
    nodes.connect(builder, 'replicates', nodes.route(lambda s: 'blocked' if s['results']['replicates']['blocking'] else 'pass',
                                                   {'blocked': 'report', 'pass': 'S8'}))
    nodes.connect(builder, 'S8', nodes.route(lambda s: 'blocked' if s['results']['S8'].get('blocking') else 'pass',
                                          {'blocked': 'report', 'pass': 'select_gate'}))
    add('select_gate', nodes.gate('research_choice', lambda s: _action(s, 'selection')))
    nodes.connect(builder, 'select_gate', nodes.gate_route('research_choice', passed='selection', refused='hold'))
    add('selection', _effect(ctx, 'selection', lambda s, i: _selection(ctx, s), gate='research_choice', kind='journal'))
    builder.add_edge('selection', 'S9')
    # S9 checks the already written selection and query receipt.
    # Selection is immutable; confirmation never returns to selection.
    nodes.connect(builder, 'S9', nodes.route(lambda s: 'blocked' if s['results']['S9'].get('blocking') else 'pass',
                                          {'blocked': 'report', 'pass': 'S10'}))
    def pre_unblind(state, ident):
        checks = {stage: state['results'][stage] for stage in CHECKS if stage in state['results']}
        return {'pin': _write(ctx, 'validation-before-unblind.json', checks),
                'blocking': [stage for stage, row in checks.items() if row.get('blocking')]}
    add('validation', _effect(ctx, 'validation', pre_unblind))
    builder.add_edge('S11', 'validation')
    nodes.connect(builder, 'validation', nodes.route(lambda s: 'blocked' if s['results']['validation']['blocking'] else 'pass',
                                                   {'blocked': 'report', 'pass': 'freeze'}))
    add('freeze', _effect(ctx, 'freeze', lambda s, i: {'pin': freeze_confirmation(ctx, s)}))
    builder.add_edge('freeze', 'unblind_gate')
    add('unblind_gate', nodes.gate('unblind', _unblind_action))
    nodes.connect(builder, 'unblind_gate', nodes.gate_route('unblind', passed='confirmation', refused='hold'))
    add('confirmation', _effect(ctx, 'confirmation', lambda s, i: confirm_batch(ctx, s), gate='unblind', kind='journal'))
    builder.add_edge('confirmation', 'S12')
    def attribution_items(state):
        return [{'key': 'attribution_' + arm['id'], 'arm': arm, 'phase': 'attribute',
                 'confirmation': state['results']['confirmation']} for arm in ablation_arms(state['spec'])]
    edge, mapped = nodes.map_node(attribution_items, lambda item: item['key'], child,
                                  lambda s, item: {'spec': _public_spec(s['spec']), 'item': item}, name='attribute')
    add('attribute', mapped)
    nodes.connect(builder, 'S12', nodes.route(lambda s: 'blocked' if s['results']['S12'].get('blocking') else 'pass',
                                           {'blocked': 'report', 'pass': 'attribution_start'}))
    add('attribution_start', _effect(ctx, 'attribution_start', lambda s, i: {'count': len(attribution_items(s))}))
    nodes.connect(builder, 'attribution_start', nodes.route(lambda s: 'map' if attribution_items(s) else 'empty',
                                                           {'map': 'attribution_map', 'empty': 'S13'}))
    add('attribution_map', _effect(ctx, 'attribution_map', lambda s, i: {}))
    nodes.connect(builder, 'attribution_map', edge)
    builder.add_edge('attribute', 'S13')
    builder.add_edge('S13', 'report')
    def report(state, ident):
        census = (state.get('results') or {}).get('replicates') or {}
        return {'failures': [r for r in nodes.joined(state) if r.get('outcome') in ('failed', 'held')],
                'replicates': census.get('per_arm'), 'replicate_blocking': census.get('blocking', []),
                'validation': {s: state['results'][s] for s in CHECKS if s in state['results']},
                'confirmation': state['results'].get('confirmation'), 'physics_validated': False}
    add('report', _effect(ctx, 'report', report))
    builder.add_edge('report', 'S14')
    # Failed validation is reportable but cannot cycle through reporting/acceptance.
    nodes.connect(builder, 'S14', nodes.route(lambda s: 'blocked' if s['results']['S14'].get('blocking') else 'pass',
                                            {'blocked': 'hold', 'pass': 'S15'}))
    add('final_gate', nodes.gate('final_task', lambda s: _action(s, 'S16')))
    nodes.connect(builder, 'S15', nodes.route(lambda s: 'blocked' if s['results']['S15'].get('blocking') else 'pass',
                                            {'blocked': 'hold', 'pass': 'final_gate'}))
    nodes.connect(builder, 'final_gate', nodes.gate_route('final_task', passed='S16', refused='hold'))
    nodes.connect(builder, 'S16', nodes.route(lambda s: 'blocked' if s['results']['S16'].get('blocking') else 'pass',
                                            {'blocked': 'hold', 'pass': END}))
    add('profile', nodes.Node(kind='guard', function=lambda state: {}))
    add('governed_stage', ml_executor.stage_node(ctx))
    builder.add_edge(START, 'profile')
    nodes.connect(builder, 'profile', nodes.route(lambda state: 'staged' if (ml_executor.active() is not None
        and ml_executor.active().extended is None) else 'extended',
        {'staged': 'governed_stage', 'extended': 'planner'}))
    nodes.connect(builder, 'governed_stage', nodes.route(ml_executor.next_stage,
        {'next': 'governed_stage', 'end': END}))
    return builder
