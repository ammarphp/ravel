"""Finite candidate comparison from pinned empirical reports.

Reports may be supplied by independent checkers after real experiments. This
module launches nothing, authenticates no worker/reviewer, and approves nothing.
It preserves failed alternatives rather than interpreting missing evidence as a
refutation. Promotion means a request for full-case review, never acceptance.
This fixed-population intake does not implement adaptive search. An external
caller can freeze successive rounds after real outcomes, binding parent results
and retaining the existing graph/routine-candidate cumulative execution budgets.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

MAX_BYTES = 2_000_000
MAX_TOTAL_BYTES = 64_000_000
SHA = re.compile(r'[0-9a-f]{64}')
ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,127}')
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
def keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('closed fields required: ' + ','.join(names))
def identity(value):
    if type(value) is not str or not ID.fullmatch(value):
        raise ValueError('bounded identity required')
    return value
def sha(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError('exact SHA256 required')
    return value
def read_pin(pin, root):
    keys(pin, ['path', 'sha256', 'size'])
    sha(pin['sha256'])
    if type(pin['size']) is not int or not 1 <= pin['size'] <= MAX_BYTES:
        raise ValueError('bounded nonempty artifact required')
    if type(pin['path']) is not str or not pin['path']:
        raise ValueError('relative artifact path required')
    relative = Path(pin['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('relative artifact path required')
    path = root
    for component in relative.parts:
        path = path / component
        if path.is_symlink(): raise ValueError('symlink artifact refused')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('regular artifact in supplied root required')
    before = path.stat()
    with path.open('rb') as stream: raw = stream.read(MAX_BYTES + 1)
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError('artifact changed during read')
    if len(raw) != pin['size'] or hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('artifact bytes differ')
    def pairs(items):
        out = {}
        for k,v in items:
            if k in out: raise ValueError('duplicate JSON field')
            out[k] = v
        return out
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda token: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    json.dumps(value, allow_nan=False)
    return value

def summarize(plan, *, base_dir):
    """Intake a fixed complete rectangular trial population, retaining unknowns.

Experiment/evaluator files are checked as declared bytes. A caller must separately
verify supervised execution and scientific review before relying on their truth.
Scores have the plan's explicitly supplied meaning; no physics metric is invented.
"""
    keys(plan, ['schema_version', 'scope', 'metric', 'direction', 'candidates', 'cases', 'trials'])
    if type(plan['schema_version']) is not int or plan['schema_version'] != 1:
        raise ValueError('schema version must be 1')
    for text in ['scope', 'metric']:
        if type(plan[text]) is not str or not plan[text].strip() or len(plan[text]) > 4096:
            raise ValueError('bounded explicit metric/scope required')
    if plan['direction'] not in ['minimize', 'maximize']: raise ValueError('declared metric direction required')
    if type(plan['candidates']) is not list or not 1 <= len(plan['candidates']) <= 8:
        raise ValueError('one to eight candidates required')
    if type(plan['cases']) is not list or not 1 <= len(plan['cases']) <= 16:
        raise ValueError('one to sixteen cases required')
    candidates, cases = {}, {}
    for row in plan['candidates']:
        keys(row, ['id', 'kind', 'parent', 'recipe_sha256', 'components', 'reason'])
        cid = identity(row['id']); sha(row['recipe_sha256'])
        if cid in candidates: raise ValueError('duplicate candidate')
        if row['kind'] not in ['seed', 'evolved', 'ablation']: raise ValueError('candidate kind required')
        if (type(row['components']) is not list or len(row['components']) > 16 or
            len(set(row['components'])) != len(row['components'])): raise ValueError('bounded distinct components required')
        for component in row['components']: identity(component)
        if type(row['reason']) is not str or not row['reason'].strip() or len(row['reason']) > 4096:
            raise ValueError('candidate rationale required')
        if (row['kind'] == 'seed') != (row['parent'] is None): raise ValueError('seed/parent relation differs')
        candidates[cid] = deepcopy(row)
    for cid,row in candidates.items():
        seen = {cid}; parent = row['parent']
        while parent is not None:
            if parent not in candidates or parent in seen: raise ValueError('missing/cyclic lineage')
            seen.add(parent); parent = candidates[parent]['parent']
        if row['kind'] == 'ablation' and not set(row['components']) < set(candidates[row['parent']]['components']):
            raise ValueError('ablation must remove components from its parent')
    for row in plan['cases']:
        keys(row, ['id', 'partition', 'input_sha256'])
        cid = identity(row['id']); sha(row['input_sha256'])
        if cid in cases: raise ValueError('duplicate case')
        if row['partition'] not in ['development', 'held_out', 'full_case']:
            raise ValueError('explicit case partition required')
        cases[cid] = deepcopy(row)
    if type(plan['trials']) is not list or len(plan['trials']) != len(cases)*len(candidates):
        raise ValueError('full candidate/case census required')
    root = Path(base_dir).resolve(strict=True)
    if not root.is_dir(): raise ValueError('artifact root required')
    observations = {}; report_pins = []; total_bytes = 0
    for trial in plan['trials']:
        keys(trial, ['candidate_id', 'case_id', 'result', 'check'])
        pair = (trial['candidate_id'], trial['case_id'])
        if pair[0] not in candidates or pair[1] not in cases or pair in observations:
            raise ValueError('foreign/duplicate trial identity')
        if trial['result'] is None or trial['check'] is None:
            if trial['result'] is not None or trial['check'] is not None: raise ValueError('paired result/check required')
            observations[pair] = {'status': 'not_observed', 'score': None, 'reason': 'No empirical report supplied.'}
            continue
        for fact in [trial['result'], trial['check']]:
            keys(fact, ['path', 'sha256', 'size'])
            if type(fact['size']) is not int or fact['size'] < 1:
                raise ValueError('bounded nonempty artifact required')
            total_bytes += fact['size']
            if total_bytes > MAX_TOTAL_BYTES: raise ValueError('aggregate artifact byte bound exceeded')
        # The result is opaque to this generic intake; the independently supplied
        # checker binds exactly those bytes and the entire declared scientific case.
        read_pin(trial['result'], root)
        check = read_pin(trial['check'], root)
        keys(check, ['schema_version', 'candidate_id', 'case_id', 'input_sha256', 'recipe_sha256',
                     'result_sha256', 'metric', 'status', 'score', 'limitations'])
        if (type(check['schema_version']) is not int or check['schema_version'] != 1 or
            check['candidate_id'] != pair[0] or check['case_id'] != pair[1] or
            check['input_sha256'] != cases[pair[1]]['input_sha256'] or
            check['recipe_sha256'] != candidates[pair[0]]['recipe_sha256'] or
            check['result_sha256'] != trial['result']['sha256'] or check['metric'] != plan['metric']):
            raise ValueError('checker refers to a different candidate/case/result/metric')
        if check['status'] not in ['passed', 'failed', 'unresolved']: raise ValueError('checker status required')
        score = check['score']
        try:
            if score is not None and (type(score) not in [int, float] or not math.isfinite(score)):
                raise ValueError('finite scalar metric required')
        except OverflowError:
            raise ValueError('finite representable scalar metric required') from None
        if check['status'] == 'passed' and score is None: raise ValueError('passed scored report lacks score')
        if (type(check['limitations']) is not list or len(check['limitations']) > 32 or
            any(type(x) is not str or not x.strip() or len(x) > 4096 for x in check['limitations'])):
            raise ValueError('bounded checker limitations required')
        observations[pair] = deepcopy(check)
        report_pins.extend([deepcopy(trial['result']), deepcopy(trial['check'])])
    summaries = []
    for cid,row in candidates.items():
        observed = {case_id: observations[cid,case_id] for case_id in cases}
        pairs = []
        if row['parent'] is not None:
            for case_id in cases:
                own, parent = observed[case_id], observations[row['parent'],case_id]
                delta = None
                if own['status'] == parent['status'] == 'passed':
                    delta = own['score'] - parent['score']
                    try:
                        if not math.isfinite(delta): raise ValueError('unrepresentable paired metric difference')
                    except OverflowError:
                        raise ValueError('unrepresentable paired metric difference') from None
                pairs.append({'case_id': case_id, 'score_delta_vs_parent': delta,
                              'favorable': None if delta is None else (delta < 0 if plan['direction']=='minimize' else delta > 0)})
        required = [key for key,row in cases.items() if row['partition'] in ['held_out', 'full_case']]
        partitions = {cases[key]['partition'] for key in required}
        complete = {'held_out', 'full_case'} <= partitions and all(
            observed[key]['status'] == 'passed' for key in required)
        summaries.append({'candidate': row, 'observations': observed, 'paired_comparisons': pairs,
                          'next_action': 'request_full_case_review' if complete else 'continue_declared_experiments',
                          'scientific_acceptance': False, 'reuse_requires_original_execution_and_review_validation': True})
    return {'schema_version': 1, 'kind': 'advisory_candidate_experiment_intake', 'plan_sha256': digest(plan),
            'scope': plan['scope'], 'metric': plan['metric'], 'direction': plan['direction'],
            'candidate_count': len(candidates), 'case_count': len(cases), 'trial_count': len(observations),
            'candidates': summaries, 'artifact_pins': report_pins, 'execution_authorized': False,
            'physics_validated': False, 'execution_identity_checked': False,
            'limitations': ['Pinned checker reports are empirical declarations, not authenticated scientific acceptance.',
                            'Unknown/missing results do not refute a hypothesis; passing development controls do not promote a full case.',
                            'This pure intake neither dispatches experiments nor reuses historical execution authority.']}
