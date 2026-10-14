"""Original-task backend choice, ordinary handoffs and complete result intake.

This composes existing providers and the scientific context. It never runs,
approves or retries a study, combines overlapping analyses, changes a model,
or upgrades an observed result to a scientific decision.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re

from . import science, scientific_context, physics_review
from .state_io import atomic_json, read_json
from .tool_census import load_census
from .recast_route import rank_backends
from ravel.physics.ma5_saf import Capture, _json, _keys
from ravel.physics.ma5_pad import InputCapture

ROUTES = {
    'smodels': {'model-portfolio': 'source-map expected-sensitive constraint and complete uncovered-topology/lifetime portfolio'},
    'checkmate': {'checkmate-events': 'complete native conservative single-SR table; r_obs_cons is not CLs'},
    'ma5': {'ma5-saf': 'complete supported linear SAF outputs, raw sign channels and independent view populations',
            'ma5-pad': 'complete source-defined native PAD supplied-event linear SAF outputs'},
    'contur': {'contur-yoda': 'fresh native measurement pooling with all three explicit background modes',
               'contur-import': 'complete source-bound cached native numerical portfolio; no fresh inference'},
}
BASES = ('bsm', 'sm', 'sm_plus_bsm', 'signed_interference')


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 8000: raise ValueError('bounded explicit portfolio text required')


def _pin(path):
    path = science.regular(str(path), Path.cwd())
    return {'path': str(path), 'sha256': science.execution.file_hash(path)}


def _task_document(spec, base):
    key = 'config' if spec['mode'] == 'checkmate-events' else 'input'
    if key not in spec['task']:
        raise ValueError('configured provider needs its existing input/config document')
    return key, science.regular(spec['task'][key], base)


def _normal(spec, base):
    value = deepcopy(spec)
    key, path = _task_document(value, base)
    value['task'][key] = str(path)
    return value


def _load(request_path):
    c = InputCapture(); p, raw = c.read(str(request_path), Path.cwd()); r = _json(raw)
    _keys(r, ('schema_version', 'original_context', 'model', 'signal_basis', 'energy_tev', 'studies'), 'backend portfolio request')
    if type(r['schema_version']) is not int or r['schema_version'] != 1 or r['signal_basis'] not in BASES:
        raise ValueError('portfolio schema1 and explicit SM/BSM/interference basis required')
    if type(r['energy_tev']) not in (int, float) or not math.isfinite(r['energy_tev']) or r['energy_tev'] <= 0:
        raise ValueError('finite positive collision energy required')
    cp, b = c.pin(r['original_context'], p.parent); context_request = _json(b)
    context = scientific_context.compile_context(context_request, cp.parent)
    model = c.stream_pin(r['model'], p.parent)
    if type(r['studies']) is not list or not 1 <= len(r['studies']) <= 32: raise ValueError('complete finite configured backend population required')
    identities, entries = set(), []
    artifacts = {q['artifact'] for q in context['requested_quantities']}
    quantities = {q['id']: q for q in context['requested_quantities']}
    for row in r['studies']:
        _keys(row, ('id', 'backend', 'study', 'applicability', 'outputs', 'handoff_inputs', 'claim_scope'), 'configured backend study')
        if not re.fullmatch('[A-Za-z0-9_.-]{1,80}', str(row['id'])) or row['id'] in identities: raise ValueError('distinct safe study identity required')
        identities.add(row['id']); _text(row['claim_scope'])
        sp, b = c.pin(row['study'], p.parent); spec = _json(b)
        if row['backend'] not in ROUTES or spec['mode'] not in ROUTES[row['backend']]: raise ValueError('backend route differs from existing provider')
        if 'backend_handoff' in spec: raise ValueError('a configured offer cannot recursively contain a portfolio handoff')
        science.validate(spec)
        if spec['schema_version'] != 2 or spec['max_attempts'] != 1 or spec['review_policy']['policy']['max_redos'] != 0:
            raise ValueError('ordinary one-attempt version2 source-bound study required')
        if row['claim_scope'] not in spec['review_policy']['policy']['claim_scopes']: raise ValueError('prospective claim scope differs')
        a = row['applicability']
        _keys(a, ('routine_ids', 'energy_tev', 'model_bases', 'source_basis', 'unresolved'), 'source applicability')
        if type(a['routine_ids']) is not list or not a['routine_ids'] or len(set(a['routine_ids'])) != len(a['routine_ids']): raise ValueError('explicit distinct routine/data selection required')
        for v in a['routine_ids']: _text(v)
        if type(a['model_bases']) is not list or not a['model_bases'] or set(a['model_bases']) - set(BASES) or len(set(a['model_bases'])) != len(a['model_bases']): raise ValueError('explicit admitted source model bases required')
        if type(a['source_basis']) is not list or not a['source_basis']: raise ValueError('source applicability evidence required')
        for pin in a['source_basis']: c.stream_pin(pin, p.parent)
        if type(a['unresolved']) is not list or len(a['unresolved']) > 64: raise ValueError('explicit finite unresolved applicability obligations required')
        for value in a['unresolved']: _text(value)
        if type(row['handoff_inputs']) is not list or len(row['handoff_inputs']) > 256: raise ValueError('full model/event/analysis handoff pins required')
        for pin in row['handoff_inputs']: c.stream_pin(pin, p.parent)
        if type(row['outputs']) is not dict or not row['outputs'] or set(row['outputs']) - artifacts: raise ValueError('original requested artifact IDs required')
        for identity, output in row['outputs'].items():
            _keys(output, ('pointer', 'quantity_ids'), 'native result selector')
            if type(output['pointer']) is not str or output['pointer'] and not output['pointer'].startswith('/'): raise ValueError('literal JSON result pointer required')
            if type(output['quantity_ids']) is not list or not output['quantity_ids'] or len(set(output['quantity_ids'])) != len(output['quantity_ids']): raise ValueError('complete quantity binding required')
            if any(q not in quantities or quantities[q]['artifact'] != identity for q in output['quantity_ids']): raise ValueError('quantity belongs to another original artifact')
            if set(output['quantity_ids']) != {q for q in quantities if quantities[q]['artifact'] == identity}:
                raise ValueError('partial quantity projection cannot silently satisfy an artifact')
        # Admission expands the exact underlying configured provider, including
        # source, complete event/model/database/assets/runtime files. No process.
        expanded = science.task_inputs(spec, sp.parent)
        blockers = list(a['unresolved'])
        for group in context['request']['compatibility_groups']:
            members = set(group['artifacts'])
            if members & row['outputs'].keys() and not members <= row['outputs'].keys():
                blockers.append('Coupled original artifacts must be delivered together: '+group['id'])
        if type(a['energy_tev']) not in (int, float) or not math.isfinite(a['energy_tev']) or a['energy_tev'] != r['energy_tev']:
            blockers.append('collision energy differs from the original request')
        if r['signal_basis'] not in a['model_bases']: blockers.append('source applicability does not admit the original prediction basis')
        if row['backend'] == 'smodels' and r['signal_basis'] != 'bsm':
            blockers.append('simplified topology maps do not admit an SM-plus-BSM or interference decomposition here')
        # Native config basis must agree, never merely a producer route label.
        _, configured_path = _task_document(spec, sp.parent)
        configured = read_json(configured_path)
        if row['backend'] == 'smodels':
            mp = science.regular(configured['model_input']['file']['path'], configured_path.parent)
            if mp != model or configured['model_input']['file']['sha256'] != r['model']['sha256']:
                blockers.append('SModelS native model input differs from the original supplied model')
            if a['routine_ids'] != configured['settings']['analyses']:
                blockers.append('SModelS declared selection differs from native analysis selectors')
        if (spec['mode'] == 'ma5-saf' and configured.get('schema_version') == 2) or spec['mode'] == 'ma5-pad':
            if a['routine_ids'] != [configured['analysis']]:
                blockers.append('MA5 declared selection differs from native source routine')
        if spec['mode'] == 'checkmate-events':
            request_path = c.stream_pin(configured['request'], configured_path.parent)
            request = read_json(request_path)
            if a['routine_ids'] != [request['routine']]:
                blockers.append('CheckMATE declared selection differs from native routine')
        if spec['mode'] == 'contur-yoda':
            total = configured['settings']['sig_plus_bg']
            if total != (r['signal_basis'] == 'sm_plus_bsm'):
                blockers.append('Contur total-versus-additional prediction setting differs from original basis')
            if a['routine_ids'] != configured['settings']['only_analyses']:
                blockers.append('Contur declared selection differs from native analysis patterns')
        if spec['mode'] == 'ma5-pad' and configured['population']['basis'] != r['signal_basis']:
            blockers.append('PAD native event basis differs from the original request')
        entries.append({'row': deepcopy(row), 'specification': spec, 'specification_path': str(sp),
            'normalized_specification': _normal(spec, sp.parent), 'adapter_inputs': [str(x) for x in expanded],
            'blockers': blockers, 'applicable': not blockers})
    c.finish()
    return p, r, context, entries, c


def input_pins(request_path):
    p, request, context, entries, c = _load(request_path)
    cp = science.regular(request['original_context']['path'], p.parent)
    paths = list(set(c.files) | set(c.streams))
    paths += [science.regular(pin['path'], cp.parent) for pin in scientific_context.input_pins(context['request'], cp.parent)]
    paths += [Path(x) for entry in entries for x in entry['adapter_inputs']]
    result = [_pin(p) for p in sorted(set(paths))]
    c.finish(); return result


def assess(request_path):
    p, r, context, entries, c = _load(request_path)
    ranking = rank_backends(signal_basis=r['signal_basis'],
        routine_ids=[name for e in entries for name in e['row']['applicability']['routine_ids']])
    ranks = {row['backend']: row for row in ranking['ranking']}
    # The ranking covers only released census backends. An offer from another backend stays in
    # the portfolio after every ranked one, with no rank and the reason, never a promoted rank.
    unranked = {'rank': None, 'reasons': ['Backend is outside the released census: no rank is assigned, '
                                          'and the offer keeps its exact-source applicability result.']}
    ranked = lambda e: ranks.get(e['row']['backend'], unranked)
    entries = sorted(entries, key=lambda e: (not e['applicable'], ranked(e)['rank'] is None,
                                             ranked(e)['rank'] or 0, e['row']['id']))
    overlaps = []
    for i, left in enumerate(entries):
        for right in entries[i+1:]:
            artifacts = sorted(set(left['row']['outputs']) & set(right['row']['outputs']))
            routines = sorted(set(left['row']['applicability']['routine_ids']) & set(right['row']['applicability']['routine_ids']))
            if artifacts or routines:
                overlaps.append({'study_ids': [left['row']['id'], right['row']['id']],
                    'artifact_ids': artifacts, 'routine_ids': routines, 'combination': None})
    result = {'kind': 'backend-portfolio-choice', 'schema_version': 1, 'request': _pin(p),
        'task_id': context['request']['task_id'], 'original_request_sha256': context['request_sha256'],
        'signal_basis': r['signal_basis'], 'energy_tev': r['energy_tev'],
        'backend_ranking': ranking, 'overlaps': overlaps,
        'applicability_scope': 'Exact source evidence and native selectors are bound; applicability assertions still require actual scoped review.',
        'studies': [{'study_id': e['row']['id'], 'backend': e['row']['backend'], 'mode': e['specification']['mode'],
                    'applicable': e['applicable'], 'blockers': e['blockers'], 'capability': ROUTES[e['row']['backend']][e['specification']['mode']],
                    'ranking_reasons': ranked(e)['reasons'], 'census_rank': ranked(e)['rank'],
                    'artifact_ids': list(e['row']['outputs']), 'quantity_ids': [q for o in e['row']['outputs'].values() for q in o['quantity_ids']],
                    'complete_adapter_input_count': len(e['adapter_inputs']), 'applicability': e['row']['applicability']}
                    for e in entries],
        'cross_backend_combination': None, 'execution_authorized': False, 'physics_validated': False}
    c.finish(); return result


def prepare(request_path, selected, output):
    p, r, context, entries, c = _load(request_path)
    if type(selected) is not list or not selected or len(set(selected)) != len(selected): raise ValueError('explicit unique backend choice required')
    offers = {e['row']['id']: e for e in entries}
    if set(selected) - offers.keys() or any(not offers[x]['applicable'] for x in selected): raise ValueError('selected backend is unavailable/inapplicable; retain blockers')
    # Shared artifacts are alternative answers, not silently merged results.
    chosen = [offers[x] for x in selected]
    out = Path(output).absolute()
    if any(x.is_symlink() for x in (out, *out.parents)): raise ValueError('ordinary fresh handoff destination required')
    out.mkdir(parents=True, exist_ok=False)
    branches = []
    for entry in chosen:
        row = entry['row']; root = out/row['id']; root.mkdir()
        handoff = {'schema_version': 1, 'request': _pin(p), 'study_id': row['id'], 'original_study': row['study']}
        # Resolve original study pin at its original request base.
        handoff['original_study']['path'] = entry['specification_path']
        atomic_json(root/'handoff.json', handoff)
        spec = deepcopy(entry['normalized_specification']); spec['backend_handoff'] = str(root/'handoff.json')
        science.validate(spec); atomic_json(root/'study.json', spec)
        science.task_inputs(spec, root)
        branches.append({'study_id': row['id'], 'backend': row['backend'], 'study': _pin(root/'study.json'),
            'handoff': _pin(root/'handoff.json'), 'ordinary_rundir': str(root/'ordinary-study'),
            'outputs': deepcopy(row['outputs']), 'claim_scope': row['claim_scope'],
            'next': 'ordinary science.plan, actual CHECK-IN1, existing science.run; no approval supplied by handoff'})
    result = {'kind': 'backend-portfolio-handoff', 'schema_version': 1, 'request': _pin(p), 'branches': branches,
        'task_id': context['request']['task_id'], 'original_request_sha256': context['request_sha256'],
        'cross_backend_combination': None, 'execution_authorized': False, 'physics_validated': False}
    atomic_json(out/'handoff-portfolio.json', result); c.finish(); return result


def handoff_inputs(spec, base):
    c = Capture(); hp, raw = c.read(spec['backend_handoff'], base); h = _json(raw)
    _keys(h, ('schema_version', 'request', 'study_id', 'original_study'), 'ordinary backend handoff')
    if type(h['schema_version']) is not int or h['schema_version'] != 1: raise ValueError('backend handoff schema1 required')
    rp, _ = c.pin(h['request'], hp.parent); sp, raw = c.pin(h['original_study'], hp.parent)
    original = _json(raw); effective = deepcopy(spec); effective.pop('backend_handoff')
    if effective != _normal(original, sp.parent): raise ValueError('handoff changes underlying provider/scientific scope')
    _, _, _, entries, request_capture = _load(rp)
    rows = [x for x in entries if x['row']['id'] == h['study_id']]
    if len(rows) != 1 or rows[0]['specification_path'] != str(sp) or not rows[0]['applicable']:
        raise ValueError('handoff is not a current applicable configured offer')
    c.finish(); request_capture.finish()
    return [_pin(hp), *input_pins(rp)]


def delivery_pins(request_path, branches):
    """Complete terminal run population for the ordinary Graph's explicit inputs.

    This hashes files, not content delivery to a reviewer. The public scientific
    and review gates still independently validate each terminal run at intake.
    Append-only review events completed before this observation are included;
    changes during the observation refuse, with no across-call cache.
    """
    if type(branches) is not dict or not branches:
        raise ValueError('explicit terminal branch paths required')
    pins = input_pins(request_path)
    from ravel.physics.ma5_pad import InputCapture
    capture = InputCapture()
    memberships = {}
    for value in branches.values():
        root = science.root(value)
        members = {p for p in root.rglob('*') if p.is_file()}
        for p in root.rglob('*'):
            if p.is_symlink() or not (p.is_file() or p.is_dir()):
                raise ValueError('ordinary terminal evidence population required')
        memberships[root] = members
        for p in sorted(members):
            pin = _pin(p); capture.stream_pin(pin, root, allow_empty=True); pins.append(pin)
    capture.finish()
    for root, members in memberships.items():
        if {p for p in root.rglob('*') if p.is_file()} != members:
            raise ValueError('terminal evidence membership changed')
    return list({p['path']: p for p in pins}.values())


def ingest(request_path, branches, output):
    """Retain terminal original artifacts and continue only genuinely accepted branches.

    Unknown/failed/unreviewed branches stay in the requested denominator. Native
    results remain full objects; no cross-study confidence arithmetic is applied.
    """
    p, r, context, entries, capture = _load(request_path)
    if type(branches) is not dict or not branches or set(branches) - {e['row']['id'] for e in entries}: raise ValueError('known explicit ordinary branch paths required')
    out = Path(output).absolute()
    if any(x.is_symlink() for x in (out, *out.parents)): raise ValueError('ordinary fresh delivery destination required')
    if any(out.is_relative_to(science.root(value)) for value in branches.values()):
        raise ValueError('delivery must preserve each original run directory')
    out.mkdir(parents=True, exist_ok=False)
    descriptors, seen_artifacts = [], set()
    accepted_reviews = []
    result_capture = InputCapture(); output_memberships = {}
    for entry in entries:
        row = entry['row']; identity = row['id']; descriptor = {'study_id': identity, 'backend': row['backend'],
            'original_request_sha256': context['request_sha256'], 'model': deepcopy(r['model']), 'signal_basis': r['signal_basis'],
            'original_context': deepcopy(r['original_context']), 'energy_tev': r['energy_tev'],
            'study': {'path': entry['specification_path'], 'sha256': row['study']['sha256']},
            'mode': entry['specification']['mode'],
            'applicability': deepcopy(row['applicability']), 'requested_artifact_ids': list(row['outputs']),
            'requested_quantity_ids': [q for o in row['outputs'].values() for q in o['quantity_ids']],
            'result_pins': [], 'complete_native_result': None, 'scientific_accepted': False,
            'output_inventory': [], 'claim_scope': row['claim_scope'],
            'continuation_obligations': list(entry['blockers'])}
        if identity not in branches:
            descriptor.update(state='not_executed'); descriptor['continuation_obligations'].append('Prepare applicable configured study or resolve its named blockers')
            descriptors.append(descriptor); continue
        rd = science.root(branches[identity]); science.verify_plan(rd, approved=True)
        effective = science.execution_spec(rd)
        if 'backend_handoff' not in effective: raise ValueError('result has no original-task handoff')
        handoff_inputs(effective, rd)
        h = read_json(science.regular(effective['backend_handoff'], rd))
        if h['study_id'] != identity or h['request'] != _pin(p): raise ValueError('ordinary result belongs to another original request/branch')
        packet = science.packet(rd)
        state = packet['execution']['status']
        if state in ('planned', 'approved', 'running'): raise ValueError('terminal ordinary evidence required')
        if packet['errors']: raise ValueError('changed/invalid ordinary result cannot be silently delivered')
        execution = science.execution.load_execution(rd)['stages']['science']
        # Output path comes from the ordinary selected stage, not a user path.
        stage, _, _ = science._selected(rd, read_json(rd/science.PLAN))
        if len(stage['outputs']) != 1: raise ValueError('one exact provider output root required')
        result_path = rd/stage['outputs'][0]/'result.json'
        native_root = result_path.parent
        if native_root.exists():
            members = {x for x in native_root.rglob('*') if x.is_file()}
            output_memberships[native_root] = members
            for x in sorted(members):
                pin = _pin(x); result_capture.stream_pin(pin, native_root, allow_empty=True)
                descriptor['output_inventory'].append(pin)
        result = None
        if result_path.is_file():
            descriptor['result_pins'].append(_pin(result_path)); result = read_json(result_path)
            descriptor['complete_native_result'] = result
            descriptor['limitations'] = deepcopy(result.get('limitations', []))
        descriptor['stage_receipt'] = _pin(rd/execution['attempt_record']); descriptor['state'] = state
        accepted = False
        if state == 'succeeded' and result and result.get('status') == 'passed' and physics_review.active(rd):
            view = physics_review.status(rd)
            if view['state'] == 'accepted' and view['claim_scope'] == row['claim_scope'] and not view['live_errors']:
                snapshot = physics_review.snapshot(rd, action='delivery')
                if physics_review.validate_snapshot(snapshot): raise ValueError('actual review snapshot differs')
                atomic_json(out/(identity+'-review.json'), snapshot)
                descriptor['review_snapshot'] = _pin(out/(identity+'-review.json')); accepted = True
                accepted_reviews.append((rd, row['claim_scope'], snapshot))
        descriptor['scientific_accepted'] = accepted
        if accepted:
            overlap = set(row['outputs']) & seen_artifacts
            if overlap:
                descriptor['continuation_obligations'].append('Alternative accepted providers cover the same requested artifacts; select explicitly rather than splice or combine them')
            else:
                outputs = {}
                for number, (artifact, selector) in enumerate(row['outputs'].items()):
                    value = scientific_context._pointer(result, selector['pointer'])
                    destination = out/(identity+'-artifact-'+str(number)+'.json'); atomic_json(destination, value); outputs[artifact] = _pin(destination)
                next_experiment = {'hypothesis': 'A separately admitted calculation can serve each remaining original quantity.',
                    'change': 'Keep the original model/basis and complete source input; add the missing calculation.',
                    'measurement': 'Deliver all still-missing quantity IDs and native populations.',
                    'if_supported': 'Retain only the separately accepted scope.', 'if_not_supported': 'Preserve failure or non-applicability and choose a source-supported alternative.'}
                context = scientific_context.apply_step(context, {'id': identity, 'outputs': outputs, 'code_status': 'success',
                    'actor_complete': False, 'question': context['request']['task'], 'next_experiment': next_experiment},
                    science.regular(r['original_context']['path'], p.parent).parent)
                seen_artifacts.update(row['outputs'])
        else: descriptor['continuation_obligations'].append('Obtain actual scoped review, or diagnose the preserved failure; no old attempt is reinitialized')
        if result is not None: descriptor['continuation_obligations'] += deepcopy(result.get('follow_up', []))
        descriptors.append(descriptor)
    result = {'kind': 'backend-portfolio-delivery', 'schema_version': 1, 'request': _pin(p),
        'task_id': context['request']['task_id'], 'context': context, 'studies': descriptors,
        'quantity_completion': context['quantity_completion'], 'cross_backend_combination': None,
        'original_quantity_checks_complete': context['quantity_completion'], 'complete_task_semantics_claimed': False, 'execution_authorized': False, 'physics_validated': False}
    result_capture.finish()
    for root, members in output_memberships.items():
        if {x for x in root.rglob('*') if x.is_file()} != members:
            raise ValueError('ending native output population changed')
    for value in branches.values(): science.verify_plan(science.root(value), approved=True)
    capture.finish()
    # Terminal source/byte custody alone does not keep a reviewed result accepted.
    # Observe current authority after every dependent result/source read, and
    # preserve partial artifacts rather than return completion after a new hold.
    for rd, claim_scope, snapshot in accepted_reviews:
        if physics_review.validate_snapshot(snapshot) or not physics_review.active(rd):
            raise ValueError('ending scoped review authority differs')
        current = physics_review.status(rd)
        if current['state'] != 'accepted' or current['claim_scope'] != claim_scope or current['live_errors']:
            raise ValueError('ending scoped review authority is held or changed')
    atomic_json(out/'backend-portfolio.json', result); return result
