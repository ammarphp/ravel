"""Durable default research design, review and whole-question coordination.

LangGraph owns routing/checkpoints. Existing Graph/campaign/review/science
services own calls, evidence, authority and effects. No checkpoint is a vote,
approval, native receipt or proof that a scientific question has been answered.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import TypedDict

from . import agent_graph as graph, state_io
from . import langgraph_runtime as framework


class RecoveryHold(ValueError):
    """A domain effect without a reconciled receipt must not be replayed."""


def _ordinary_approval_gate(rundir, *, selected, goal_binding):
    """Fresh preparation may request CI1; an existing receipt is never replaced."""
    from langgraph.types import interrupt
    from . import science, scientific_autonomy
    rundir = Path(rundir)
    approval = rundir / science.APPROVAL
    # A broken link is still an existing foreign receipt, not fresh absence.
    # Validate the complete current unapproved plan before requesting authority.
    if not (approval.exists() or approval.is_symlink()):
        science.verify_plan(rundir, approved=False)
        _, document = scientific_autonomy.observed_run_document(rundir)
        if 'autonomy' in document:
            scientific_autonomy.plan_authority(rundir)
            science.approve_delegated(rundir)
        else:
            interrupt({'kind': 'ordinary_checkin1_and_machine_lease_required',
                'rundir': str(rundir), 'selected': selected,
                'original_goal_binding': goal_binding, 'approval_from_resume': False})
    # Neither an ordinary retry nor an interrupt response is approval. Missing
    # inputs and missing/invalid receipts refuse through the original verifier.
    try:
        science.verify_plan(rundir, approved=True)
    except ValueError as exc:
        raise RecoveryHold('existing approval is invalid; never replace its receipt') from exc


class ResearchState(TypedDict, total=False):
    binding: dict
    bundle: dict
    compile_spec: dict
    admission_spec: dict
    materialization: dict
    selection: dict
    selected: str
    plan: dict
    handoff: dict
    result: dict
    step: dict
    index: int
    role: str
    role_binding: dict
    checked: dict
    skeptic_binding: dict
    decider_binding: dict
    proposal_binding: dict
    original_autonomy: bool
    observation: dict
    feedback: dict
    turn: int
    prepared: dict
    model_spec: dict
    origin: dict
    citation: dict
    speculative: dict
    context_critic: dict
    context_verifier: dict
    action: str
    arguments: dict
    action_results: list
    method_round: int
    method_history: list
    context_reworks: int
    source_requests: list
    prepared_ideas: dict


def _pin(path):
    from . import research_cycle as cycle
    return cycle._pin(path)


def _read(pin):
    from . import research_cycle as cycle
    return cycle._read(pin, Path(pin['path']).parent)


def _emitted(path, value):
    """Commit intended serialized bytes, never the first reread as baseline."""
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    expected = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if _pin(path) != expected:
        raise ValueError('emitted research operation bytes changed')
    return expected


def _sources():
    # Framework libraries have their own runtime identity. This closure binds
    # the actual service adapters and prevents checkpoint reuse after edits.
    from . import research_cycle, research_tools, scientific_judgment, physics_review, science, agent_host, scientific_autonomy, research_coordinator_decisions
    return [_pin(m.__file__) for m in (framework, graph, agent_host, research_cycle, research_tools,
        scientific_judgment, physics_review, science, scientific_autonomy, research_coordinator_decisions)] + [_pin(__file__)]


def _session(out, operation):
    from .review_context import _safe_path
    out = _safe_path(out)
    expected = {'schema_version': 1, 'kind': 'durable-research-operation',
                'operation': deepcopy(operation), 'source_pins': _sources(),
                'checkpoint_is_authority': False}
    raw = (json.dumps(expected, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    request = {'path': str(out / 'operation.json'), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    if out.exists():
        if not out.is_dir() or _pin(out / 'operation.json') != request or _read(request) != expected:
            raise RecoveryHold('existing operation differs or has incomplete preparation; retain and reconcile it')
    else:
        out.mkdir(parents=True, exist_ok=False)
        if _emitted(out / 'operation.json', expected) != request:
            raise ValueError('operation emission commitment differs')
    return out, request


def _fresh_effect(path):
    if Path(path).exists():
        raise RecoveryHold('uncheckpointed prepared effect already exists; do not overwrite or infer successful completion')


def _run(out, request, *, nodes, edges, conditional=(), initial, steps):
    from langgraph.graph import START, END
    # Actual framework constants are used rather than a substitute graph DSL.
    edges = [(START if a == 'START' else a, END if b == 'END' else b) for a, b in edges]
    conditional = [(name, route, {k: END if v == 'END' else v for k, v in targets.items()})
                   for name, route, targets in conditional]
    def current(s):
        if s.get('binding') != request or _pin(request['path']) != request:
            raise ValueError('research checkpoint/request changed before domain effect')
        for pin in _read(request)['source_pins']:
            if _pin(pin['path']) != pin: raise ValueError('research service source changed before domain effect')
    def bound(function):
        def node(s):
            current(s)
            result = function(s)
            current(s)
            return result
        return node
    with state_io.file_lock(out / 'orchestration.lock', blocking=False):
        result, observation = framework.run_state_machine(out / 'framework',
            thread_id=request['sha256'], state_type=ResearchState,
            nodes={name: bound(function) for name, function in nodes.items()}, edges=edges,
            conditional_edges=conditional, initial={'binding': request, **initial},
            max_steps=steps, identity_binding=request)
        if result.get('binding') != request or _pin(request['path']) != request:
            raise ValueError('orchestration checkpoint/request differs')
        for pin in _read(request)['source_pins']:
            if _pin(pin['path']) != pin:
                raise ValueError('research service source changed during orchestration')
        if observation['interrupted']:
            return {**result, 'result': {'phase': 'ordinary_effect_required',
                'checkpoint': observation, 'execution_authorized': False}}
        return result


def design(root, blueprint_pin, choice_pin, output_dir, rundir, *,
           max_wall_seconds, api_documents=(), queries=()):
    """Nine-node source→materialization→admission→selection→plan subgraph.

    No model is needed for an explicit choice. Every actual tool effect still
    passes through the cumulative campaign Graph; normal approval is a handoff.
    """
    from . import research_cycle as cycle, research_tools as tools, research_blueprint as blueprint
    from .agent_host import AgentHost
    root = cycle._ordinary(root); rundir = cycle._ordinary(rundir)
    # A lexical containment test passes for ``<cycle>/../x``; refuse the alias before the session creates it.
    if '..' in Path(output_dir).parts:
        raise ValueError('fresh destination may not contain parent traversal')
    output_dir = cycle._ordinary(output_dir)
    if output_dir == root or not output_dir.is_relative_to(root):
        raise ValueError('research design output must be inside its existing cycle')
    _, current = cycle._load(root)
    for pin in (blueprint_pin, choice_pin):
        cycle._check_pin(pin, current['base_dir'])
    for document in api_documents:
        tools.follow._bytes(document['pin'], current['base_dir'])
    out, request = _session(output_dir, {'kind': 'design', 'cycle': str(root),
        'blueprint': blueprint_pin, 'choice': choice_pin, 'rundir': str(rundir),
        'max_wall_seconds': max_wall_seconds, 'api_documents': list(api_documents), 'queries': list(queries)})
    compile_root = out / 'materialization-graph'; admit_root = out / 'admission-graph'
    def source(_):
        _fresh_effect(out / 'context')
        return {'bundle': tools.prepare(root, blueprint_pin, out / 'context',
            api_documents=api_documents, queries=queries)}
    def compile_spec(s):
        _, state = cycle._load(root)
        return {'compile_spec': tools.materialization_spec(s['bundle'], choice_pin,
            base_dir=state['base_dir'], output_dir=out / 'inputs',
            graph_id='tool-materialization', max_wall_seconds=max_wall_seconds)}
    def compile_node(s):
        observed = cycle.execute_graph(root, compile_root, s['compile_spec'], AgentHost(), prepared=compile_root.exists())
        if not observed['complete']:
            raise RecoveryHold('ordinary materialization Graph unresolved; retain its actual failed effects')
        return {'materialization': cycle._graph_result(compile_root, 'compile')['value']['value']}
    def admission_spec(s):
        return {'admission_spec': tools.admission_spec(root, compile_root, node_id='compile',
            graph_id='tool-admission', max_wall_seconds=max_wall_seconds)}
    def admit(s):
        observed = cycle.execute_graph(root, admit_root, s['admission_spec'], AgentHost(), prepared=admit_root.exists())
        if not observed['complete']:
            raise RecoveryHold('ordinary portfolio admission Graph unresolved')
        return {}
    def adopt(s):
        _, state = cycle._load(root)
        result = s['materialization']
        portfolio = tools.follow._json(result['portfolio'], state['base_dir'])
        ids = {row['id'] for row in portfolio['experiments']}
        existing = [e for e in state['experiments'] if e['id'] in ids]
        if existing:
            if ({e['id'] for e in existing} != ids or any(
                    e.get('constructive_origin', {}).get('root') != str(admit_root) for e in existing)):
                raise RecoveryHold('portfolio partially admitted or belongs to another effect')
            for e in existing:
                if e.get('tool_context') != s['bundle']:
                    raise ValueError('admitted experiment lost source/tool binding')
            tools.check_binding(s['bundle'], state['base_dir'], state=state)
        else:
            blueprint.adopt_portfolio(root, admit_root, node_id='admit', context_pin=result['context'])
        return {}
    def select(s):
        _, state = cycle._load(root)
        selected = cycle.select(root)
        candidates = {row['id'] for row in tools.follow._json(s['materialization']['portfolio'], state['base_dir'])['experiments']}
        if selected['selected'] not in candidates:
            raise RecoveryHold('current selector prefers another/unaffordable branch; retain complete selection')
        return {'selection': selected, 'selected': selected['selected']}
    def plan(s):
        _, state = cycle._load(root)
        experiment = next(e for e in state['experiments'] if e['id'] == s['selected'])
        if experiment['rundir'] is not None:
            if experiment['rundir'] != str(rundir) or experiment['plan'] is None:
                raise RecoveryHold('selected experiment has a different or incomplete ordinary plan')
            tools.science.verify_plan(rundir, approved=False)
            cycle._check_pin(experiment['plan'], state['base_dir'])
            pin = experiment['plan']
        else:
            _fresh_effect(rundir)
            prepared = tools.plan(root, s['selected'], rundir)
            pin = next(e['plan'] for e in prepared['experiments'] if e['id'] == s['selected'])
        return {'plan': pin}
    def handoff(s):
        value = {'kind': 'ordinary_research_tool_handoff', 'cycle_root': str(root), 'bundle': s['bundle'],
            'materialization_graph': str(compile_root), 'admission_graph': str(admit_root),
            'selected': s['selected'], 'selection': s['selection'], 'rundir': str(rundir), 'plan': s['plan'],
            'next_operations': {'approve': ['ravel', 'approve', '--rundir', str(rundir)],
                **{action: ['ravel', 'research-cycle', action, '--cycle', str(root), '--experiment', s['selected']]
                   for action in ('run', 'observe', 'adjudicate')}},
            'required_arguments': {'approve': {'--quote': 'Actual current CHECK-IN 1 assent; the listed approve argv is a prefix, not an approval.'}},
            'authority': 'normal original CHECK-IN 1, actual machine lease, scientific role reviews and parent acceptance remain required',
            'execution_authorized': False, 'scientific_acceptance': False, 'parent_task_accepted': False}
        path = out / 'ordinary-handoff.json'
        raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        intended = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        if path.exists():
            if _pin(path) != intended: raise ValueError('ordinary handoff differs from intended value')
        else: _emitted(path, value)
        return {'handoff': json.loads(raw)}
    result = _run(out, request, nodes={'source_context': source, 'compile_spec': compile_spec,
        'materialize': compile_node, 'admission_spec': admission_spec, 'admit': admit, 'adopt': adopt,
        'select': select, 'plan': plan, 'handoff': handoff},
        edges=[('START','source_context'), ('source_context','compile_spec'), ('compile_spec','materialize'),
            ('materialize','admission_spec'), ('admission_spec','admit'), ('admit','adopt'),
            ('adopt','select'), ('select','plan'), ('plan','handoff'), ('handoff','END')], initial={}, steps=12)
    _, current = cycle._load(root)
    if 'handoff' not in result: return result['result']
    tools.check_binding(result['bundle'], current['base_dir'], state=current)
    cycle._check_pin(result['plan'], current['base_dir'])
    tools.science.verify_plan(rundir, approved=False)
    raw = (json.dumps(result['handoff'], sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if _pin(out/'ordinary-handoff.json') != {'path':str(out/'ordinary-handoff.json'),
            'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}:
        raise ValueError('public handoff differs from its original emitted bytes')
    return deepcopy(result['handoff'])


def _consumed(root, binding):
    """Reconcile a journaled role effect; do not submit the same vote twice."""
    from . import scientific_judgment as judgment
    contract = judgment._read_pin(binding['request'])
    _, reg, events, view = judgment._live(root)
    matches = [e for e in events if e['event'] == 'review' and e['cycle_id'] == contract['cycle_id']
        and any(p['sha256'] == binding['request']['sha256']
                and p['path'] == judgment.review._identity(root, Path(binding['request']['path']))
                for p in e.get('supporting_artifacts', []))]
    if not matches: return None
    if len(matches) != 1 or view['cycle']['sha256'] != contract['cycle_sha256']:
        raise ValueError('consumed role belongs to a different/superseded cycle')
    event = matches[0]
    receipt = graph.role_receipt(binding['graph_root'], binding['node_id'],
        expected_subject_sha256=binding['subject_sha256'], expected_packet_sha256=binding['context_manifest_sha256'],
        require_exact_subject=True, allowed_roles={contract['role']})
    value = receipt['public_value']
    if (event['role'] != judgment.ROLE[contract['role']] or event['actor_id'] != contract['actor_id']
            or any(event[k] != value[k] for k in ('verdict','summary','findings','closes','claim_scope'))):
        raise ValueError('ordinary role event differs from the exact actual response')
    # _live above verifies the complete current supporting context/child census.
    for pin in [*contract['source_pins'], *contract['prepared_settings']]:
        if judgment._pin(pin['path']) != pin: raise ValueError('consumed role source/settings changed')
    return judgment.review.status(root)


def review(root, out, *, host, model, reasoning_effort, max_output_tokens, max_wall_seconds,
           claim_scope=None, case_pin=None, improver_actor=None, proposal_binding=None, allow_control=False,
           campaign=None, experiment=None, context_index_limits=None, evidence_pages=None, max_context_reworks=0):
    """Separate-role assess→prepare→dispatch→consume→revise/verify subgraph."""
    from .graphs import review as review_graph
    if review_graph.delegates(root):  # epoch-two review points run on review.points
        return review_graph.orchestrated(root, claim_scope)
    from . import scientific_judgment as j, scientific_autonomy
    from langgraph.types import interrupt
    root = j._path(root)
    _, document = scientific_autonomy.observed_run_document(root)
    autonomous = 'autonomy' in document
    if autonomous: scientific_autonomy.authorize(root, 'accept_recommendation')
    common = dict(model=model, reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
        max_wall_seconds=max_wall_seconds, case_pin=case_pin, allow_control=allow_control,
        # The operation record is JSON: a campaign given as a path object is recorded as its text.
        campaign=None if campaign is None else os.fspath(campaign),
        experiment=experiment, context_index_limits=context_index_limits,
        evidence_pages=evidence_pages, max_context_reworks=max_context_reworks)
    out, request = _session(out, {'kind': 'review', 'rundir': str(root), 'common': common,
        'claim_scope': claim_scope, 'improver_actor': improver_actor, 'proposal_binding': proposal_binding,
        'host_sha256': graph._host_identity(host)})
    def assess(s):
        if proposal_binding is not None and s['index'] == 0:
            prior = j.verify_binding(proposal_binding, allow_control=allow_control)
            if prior['receipt']['role'] != 'improver' or prior['proposal'] is None:
                raise ValueError('prepared exact nonvoting repair proposal required')
            return {'role':'verifier','step': {'phase':'repair_design'}, 'proposal_binding': proposal_binding}
        step = j.next_step(root)
        if s['index'] >= 3 or step['phase'] not in {'result_review','repair_proposal'}:
            return {'step':step,'role':'','result':step}
        if step['phase'] == 'repair_proposal' and improver_actor is None:
            return {'step':step,'role':'','result':step}
        return {'step':step,'role':step['role']}
    def prepare(s):
        role=s['role']; folder=out / (str(s['index'])+'-'+role)
        _fresh_effect(folder)
        _, reg, _, _ = j._live(root)
        kwargs = {'proposal_binding':s['proposal_binding']} if s['step']['phase']=='repair_design' else {'claim_scope':claim_scope}
        actor=improver_actor if role=='improver' else reg['policy']['actors'][j.ROLE[role]]
        return {'role_binding': j.prepare_role(root,folder,role=role,actor_id=actor,**kwargs,**common)}
    def dispatch(s):
        binding=s['role_binding']
        observed=j.execute_role(binding,host)
        if not observed['complete']:
            interrupt({'kind':'ordinary_role_effect_required','binding':binding,
                'scientific_acceptance':False,'execution_authorized':False})
            observed=j.execute_role(binding,host)
            if not observed['complete']:raise RecoveryHold('ordinary role remains unresolved')
        return {}
    def consume(s):
        checked=_consumed(root,s['role_binding'])
        if checked is None:checked=j.consume(root,s['role_binding'],allow_control=allow_control)
        return {'checked':checked}
    def decide(s):
        checked=s['checked']; binding=s['role_binding']; role=s['role']
        if checked.get('value',{}).get('kind')=='scientific_context_request':
            if s['context_reworks']>=3*max_context_reworks:
                raise RecoveryHold('original separate-role context rework population exhausted')
            return {'role':role,'step':{**s['step'],'context_followup':True}}
        if checked.get('value',{}).get('kind')=='scientific_evidence_request':
            return {'role':'','result':{'phase':'context_requested' if checked['value']['kind']=='scientific_context_request'
                else 'retained_evidence_requested','binding':binding,'actual_request':checked['value'],
                'actual_feedback':checked,'execution_authorized':False}}
        if role=='improver':
            return {'role':'','result':{'phase':'prepare_repair' if checked['proposal'] is not None
                else 'new_evidence_or_experiment_required','improver_binding':binding,
                'actual_feedback':checked,'execution_authorized':False}}
        if s['step']['phase']=='repair_design':
            adequate=checked['value']['proposal_verdict']=='adequate_for_bounded_test'
            if role=='verifier' and adequate:
                return {'index':s['index']+1,'role':'synthesizer','step':{'phase':'repair_design'},
                    'proposal_binding':binding,'skeptic_binding':binding}
            return {'role':'','result':{'phase':'admit_prepared_correction' if adequate else 'repair_design_unresolved',
                ('decider_binding' if role=='synthesizer' else 'skeptic_binding'):binding,
                'actual_feedback':checked,'execution_authorized':False}}
        return {'index':s['index']+1,'role':'continue'}
    def context_followup(s):
        binding=s['role_binding']
        prior=j.verify_binding(binding,allow_control=allow_control)
        if prior['value']['kind']!='scientific_context_request':
            raise ValueError('a current actual nonvoting page request is required')
        folder=out/'context-followups'/graph.digest(binding)
        _fresh_effect(folder)
        # The ordinary API authenticates exact pages/predecessor and revises
        # the same charged Graph. The framework grants no extra call or vote.
        continued=j.continue_role(binding,folder,allow_control=allow_control)
        return {'role_binding':continued,'context_reworks':s['context_reworks']+1,
            'step':{k:v for k,v in s['step'].items() if k!='context_followup'}}
    def authority(s):
        result=deepcopy(s['result'])
        if autonomous and result.get('phase')=='prepare_repair':
            # Mutating preparations are not silently replayed after interruption.
            # Their checkpointed node result or explicit ordinary reconciliation
            # is needed; source guards refuse a partial/uncheckpointed rewrite.
            result['prepared']=j.apply_proposal(root,result['improver_binding'],allow_control=allow_control)
            result['phase']='review_prepared_repair'
        elif autonomous and result.get('phase')=='admit_prepared_correction':
            result['correction']=j.admit_repair(root,result['decider_binding'],allow_control=allow_control)
            result['phase']='ordinary_correction_admitted'
        elif autonomous and result.get('phase') in {'scoped_delivery','final_results_reviewed'}:
            scientific_autonomy.authorize(root,'accept_recommendation')
            if result['phase']=='scoped_delivery' and not (root/'inputs/science-plan.json').exists():
                from . import workflow_state
                result['machine_checkin2_go']=workflow_state.record_delegated_go(str(root))
        if autonomous and result.get('phase') in {'review_prepared_repair','ordinary_correction_admitted','scoped_delivery','final_results_reviewed'}:
            result.update(decision_authority='machine_under_user_delegation',human_review_claimed=False)
        return {'result':result}
    def route(s):
        if s['step'].get('context_followup'):return 'context_followup'
        if s['role']=='continue':return 'assess'
        if s['role']=='synthesizer' and s['step']['phase']=='repair_design':return 'prepare'
        return 'authority'
    state=_run(out,request,nodes={'assess':assess,'prepare':prepare,'dispatch':dispatch,'consume':consume,
        'decide':decide,'context_followup':context_followup,'authority':authority},edges=[('START','assess'),('prepare','dispatch'),('context_followup','dispatch'),
        ('dispatch','consume'),('consume','decide'),('authority','END')],
        conditional=[('assess',lambda s:'prepare' if s['role'] else 'authority',{'prepare':'prepare','authority':'authority'}),
                     ('decide',route,{'assess':'assess','prepare':'prepare','context_followup':'context_followup','authority':'authority'})],
        initial={'index':0,'original_autonomy':autonomous,'context_reworks':0},steps=24+15*max_context_reworks)
    if autonomous: scientific_autonomy.authorize(root,'accept_recommendation')
    # A final completed checkpoint must still agree with the live role journal.
    if state['result'].get('phase') in {'scoped_delivery','final_results_reviewed','return_to_work'}:
        if j.next_step(root)['phase'] != state['result']['phase']:
            raise ValueError('completed research checkpoint differs from current scientific state')
    return deepcopy(state['result'])


def coordinate(root, request_pin, output_dir, *, host):
    """Default top-level design→approval handoff→ordinary work→review→synthesis.

    Supplied request and successive blueprints specify scientific content. A
    send-back exposes actual feedback and interrupts for a fresh revision;
    repeating the same request cannot renew work, reuse old votes or approve it.
    """
    from . import research_cycle as cycle, science, scientific_judgment as j
    from langgraph.types import interrupt
    root=cycle._ordinary(root); request_value=_read(request_pin)
    fields={'schema_version','kind','cycle_root','blueprint','choice','rundir','max_wall_seconds',
            'api_documents','queries','review','synthesis_request'}
    if (set(request_value)!=fields or request_value['schema_version']!=1
            or request_value['kind']!='research-orchestration' or request_value['cycle_root']!=str(root)):
        raise ValueError('complete explicit research orchestration/v1 request required')
    if set(request_value['review']) != {'arguments','check_results'}:
        raise ValueError('explicit review arguments and actual check-results location required')
    out,operation=_session(output_dir,{'kind':'coordinate','cycle':str(root),'request':request_pin,
        'host_sha256':graph._host_identity(host)})
    def design_node(_):
        handoff=design(root,request_value['blueprint'],request_value['choice'],out/'design',request_value['rundir'],
            max_wall_seconds=request_value['max_wall_seconds'],api_documents=request_value['api_documents'],queries=request_value['queries'])
        if handoff.get('kind')!='ordinary_research_tool_handoff':
            interrupt({'kind':'source_design_effect_required','actual_subgraph':handoff})
            raise RecoveryHold('complete ordinary design handoff required')
        return {'handoff':handoff,'selected':handoff['selected']}
    def gate(s):
        # Boolean resume is a routing signal only; verify_plan is the authority.
        try:science.verify_plan(s['handoff']['rundir'],approved=True)
        except ValueError:
            interrupt({'kind':'ordinary_checkin1_and_native_admission_required','handoff':s['handoff'],
                'approval_from_resume_value':False})
            science.verify_plan(s['handoff']['rundir'],approved=True)
        return {}
    def execute(s):
        packet=science.packet(s['handoff']['rundir'])
        status=packet['execution']['status']
        if status in {'approved','planned'}:
            cycle.run_experiment(root,s['selected'])
        elif status=='running':
            interrupt({'kind':'ordinary_owned_worker_reconciliation_required','rundir':s['handoff']['rundir']})
            if science.packet(s['handoff']['rundir'])['execution']['status']=='running':
                raise RecoveryHold('running native effect cannot be dispatched again')
        # Terminal failures remain observations; no generator or fit retry.
        return {}
    def observe(s):
        _,state=cycle._load(root); e=next(e for e in state['experiments'] if e['id']==s['selected'])
        if e['observation'] is None:state=cycle.observe(root,s['selected'])
        else:cycle._current_evidence(state,e,accepted=False)
        return {'observation':next(e['observation'] for e in state['experiments'] if e['id']==s['selected'])}
    def opening(s):
        rd=s['handoff']['rundir']; step=j.next_step(rd)
        if step['phase']=='failed_diagnostic':
            interrupt({'kind':'canonical_failed_stage_review_required','actual_observation':s['observation'],
                'execution_failure_is_hypothesis_falsification':False})
            raise RecoveryHold('failed work requires a separately source-bound diagnostic/revision')
        if step['phase']=='open_cycle':
            j.open_cycle(rd,check_results=request_value['review']['check_results'])
        return {}
    def review_node(s):
        result=review(s['handoff']['rundir'],out/'review',host=host,
            campaign=root,experiment=s['selected'],**request_value['review']['arguments'])
        return {'result':result}
    def review_hold(s):
        current=j.next_step(s['handoff']['rundir'])
        if current['phase'] not in {'scoped_delivery','final_results_reviewed','stopped','repair_proposal','new_experiment_required'}:
            interrupt({'kind':'ordinary_review_or_requested_evidence_required','actual_review':s['result']})
            current=j.next_step(s['handoff']['rundir'])
        if current['phase'] not in {'scoped_delivery','final_results_reviewed','stopped','repair_proposal','new_experiment_required'}:
            raise RecoveryHold('fresh presented evidence and actual terminal review remain required')
        return {'result':current}
    def adjudicate(s):
        _,state=cycle._load(root); e=next(e for e in state['experiments'] if e['id']==s['selected'])
        if e['adjudication'] is None:
            from . import gate_wiring  # research_choice before every adjudication.
            gate_wiring.require_research_choice(root,s['selected'])
            cycle.adjudicate(root,s['selected'])
        else:cycle._current_evidence(state,e,accepted=e['adjudication']['view']['state']=='accepted')
        return {'feedback':cycle.feedback_packet(root,s['selected'])}
    def synthesis(s):
        if s['result']['phase'] not in {'scoped_delivery','final_results_reviewed'}:
            interrupt({'kind':'fresh_design_or_evidence_required','actual_feedback':s['feedback'],
                'retained_incumbent_and_negative_results':True,'old_votes_carried':[]})
            raise RecoveryHold('selective revision requires a fresh source-bound orchestration request')
        _,state=cycle._load(root)
        if request_value['synthesis_request'] is None:
            # A report recipe with as-yet unobserved source digests cannot be
            # guessed during planning. Honest complete progress is deliverable
            # now; a fresh explicit current recipe still passes the final gate.
            return {'result':cycle.progress_synthesis(root,base_dir=state['base_dir'])}
        # Unchanged final gate: all original obligations/required experiments,
        # current scoped acceptance and whole-parent reporting still required.
        return {'result':cycle.synthesize(root,request_value['synthesis_request'],base_dir=state['base_dir'])}
    result=_run(out,operation,nodes={'design':design_node,'ordinary_gate':gate,'ordinary_execute':execute,
        'observation':observe,'open_review':opening,'review':review_node,'review_hold':review_hold,
        'adjudication':adjudicate,'whole_question':synthesis},
        edges=[('START','design'),('design','ordinary_gate'),('ordinary_gate','ordinary_execute'),
            ('ordinary_execute','observation'),('observation','open_review'),('open_review','review'),
            ('review_hold','adjudication'),('adjudication','whole_question'),('whole_question','END')],
        conditional=[('review',lambda s:'hold' if s['result']['phase'] in {
            'ordinary_effect_required','context_requested','retained_evidence_requested','open_cycle'} else 'adjudicate',
            {'hold':'review_hold','adjudicate':'adjudication'})],initial={},steps=14)
    if _pin(request_pin['path'])!=request_pin:raise ValueError('original orchestration request changed')
    _, current=cycle._load(root)
    if result['result'].get('kind')=='reproducible_research_synthesis':
        fresh=cycle.synthesize(root,request_value['synthesis_request'],base_dir=current['base_dir'])
        if fresh!=result['result']:raise ValueError('checkpoint synthesis differs from current whole-question evidence')
    elif result['result'].get('kind')=='research_progress_synthesis':
        result['result']=cycle.progress_synthesis(root,base_dir=current['base_dir'])
    return deepcopy(result['result'])


def prepare_open(parent_contract, output_dir, *, base_dir, campaign, runtime, evidence,
                 candidate_modes, review, max_decisions, context_request=None,
                 obligation_mapping=None, knowledge=None, research_regime='open_exploratory'):
    """Default open intake preparation: goals/inputs/bounds, no authored DAG.

    Without an independently declared scientific context the initial context
    is explicitly a planning-only whole-obligation census. A real charged
    designer must refine it before any hypothesis/test can be executed.
    """
    from . import intake, research_coordinator_decisions as decisions, research_cycle as cycle
    from .task_completion import _Inputs, binding_projection
    observed=_Inputs(base_dir)
    try:
        handoff=intake.execution_handoff(parent_contract,base_dir=base_dir)
        if handoff['task_kind'] not in intake.WHOLE_GOAL_KINDS:
            raise ValueError('whole-goal coordinator requires a complete scientific parent; scoped operations and calculations keep their ordinary routes')
        observed.file(parent_contract)
        cycle.ce.keys(campaign, {'id','budget','max_experiments','exploration_every','required_experiments','premises'})
        cycle.ce.identity(campaign['id']);cycle._vector(campaign['budget'])
        graph._integer(campaign['max_experiments'],'experiment census',1,32)
        graph._integer(campaign['exploration_every'],'exploration cadence',1,16)
        decisions.runtime(runtime);available=decisions.catalogue(candidate_modes)
        candidate_modes=[r['mode'] for r in available['operations']]
        graph._integer(max_decisions,'decision population',1,64)
        if type(evidence) is not list or len(evidence)>32:raise ValueError('at most32 declared evidence members required')
        for row in evidence:
            cycle.ce.keys(row, {'pin','purpose'}); observed.file(row['pin'])
        out=cycle._ordinary(output_dir)
        if out.exists():raise ValueError('fresh original-goal research preparation required')
        core_source=_pin(__file__)
        ids=[r['id'] for r in handoff['obligations']]
        bootstrap={'schema_version':1,'task_id':campaign['id'],'task':handoff['original_request'],
            'source_capsules':[], 'api_documents':[{'id':'research-coordinator','pin':{k:core_source[k] for k in ('path','sha256')},
                'language':'python','role':'api','version':'actual source '+core_source['sha256'],'dependencies':[]}],
            'queries':[{'id':'prepare-original-goal','symbol':'open_research','mode':'definition','documents':['research-coordinator'],'required':True}],
            'requested_quantities':[{'id':'original-obligations-pending-science','artifact':'planning-status','pointer':'/obligations',
                'check':{'kind':'symbolic-record-census','id_field':'id','expected_ids':ids,'text_fields':['basis']},
                'meaning':'Planning-only original obligation status; NEVER measurable scientific evidence or parent acceptance.'}],
            'compatibility_groups':[{'id':'planning-only','artifacts':['planning-status'],'carryover':False,
                'basis':'Complete original planning census; replaced only by actual pre-experiment scientific declaration.'}],
            'max_source_bytes':cycle.scientific_context.MAX_SOURCE,'max_context_bytes':cycle.scientific_context.MAX_CONTEXT,
            'max_steps':campaign['max_experiments']}
        cycle.scientific_context.compile_context(bootstrap,base_dir)
        planning=decisions._put(out/'planning-context.json',bootstrap)
        if context_request is not None:
            declared=observed.document(context_request)
            projection=binding_projection(handoff['goal_binding'],base_dir=base_dir)
            cycle._context_mapping({'parent_task':projection,'base_dir':str(base_dir)},declared,obligation_mapping)
            cycle.scientific_context.compile_context(declared,base_dir)
        elif obligation_mapping is not None:
            raise ValueError('supplied method mapping needs its exact independently declared context')
        from . import research_protocol
        research_protocol.bind_default(out, regime=research_regime)
        value={'schema_version':1,'kind':'open-research-request','parent_contract':parent_contract,'handoff':handoff,
            'campaign':campaign,'runtime':runtime,'evidence':evidence,'candidate_modes':candidate_modes,
            'review':review,'max_decisions':max_decisions,'knowledge':knowledge,'context_request':context_request,
            'planning_context':planning,'direct_mapping':obligation_mapping,
            'research_regime':research_regime}
        pin=decisions._put(out/'request.json',value)
        decisions.request(pin);observed.file(pin);observed.file(planning);observed.file(core_source)
        observed.finish()
        return deepcopy(pin)
    finally:observed.close()


# The open-research node table's routing, shared by both engines (``_open_plan``).
OPEN_EDGES=[('START','declare_prepare'),('declare_sources','declare_prepare'),('declare_apply','assessment_prepare'),
    ('assessment_prepare','assessment_call'),('idea_prepare','idea_call'),
    ('idea_adopt','decision_prepare'),('decision_call','selected_operation'),('selected_operation','action_effect'),('whole_question','END')]
OPEN_CONDITIONAL=[('declare_call',lambda s:'source' if s['origin']['value']['value']['kind']=='research-source-request' else 'apply',{'source':'declare_sources','apply':'declare_apply'}),
    ('declare_prepare',lambda s:'declare' if s['action']=='declare-context' else 'assess',
        {'declare':'declare_call','assess':'assessment_prepare'}),
    ('assessment_call',lambda s:'again' if s['role'] else 'ready',{'again':'assessment_prepare','ready':'assessment_gate'}),
    ('assessment_gate',lambda s:'repair' if s['action']=='revise-context' else 'ideas',{'repair':'declare_prepare','ideas':'idea_prepare'}),
    ('idea_call',lambda s:'again' if s['role'] else 'adopt',{'again':'idea_prepare','adopt':'idea_adopt'}),
    ('decision_prepare',lambda s:'choose' if s['action']=='choose' else 'finish',{'choose':'decision_call','finish':'whole_question'}),
    ('action_effect',lambda s:'finish' if s['action'] in {'progress','synthesize'} else 'again',{'finish':'whole_question','again':'decision_prepare'})]
OPEN_INITIAL={'turn':0,'role':'','action_results':[],'method_round':0,'method_history':[],'source_requests':[]}


def open_research(root, request_pin, output_dir, *, host):
    """Actual open-task decision/action/revision loop on one original campaign.

    Model choices are ordinary charged Graphs; effects are separate LangGraph
    nodes after dispatch returns. Scientific execution, final review and whole
    parent acceptance continue to use their original independent services.
    This is the legacy state-machine engine; ``research.loop`` runs the same
    node table on the graph substrate (``graphs/research_loop.py``).
    """
    from . import research_coordinator_decisions as decisions
    plan=_open_plan(root,request_pin,output_dir,host=host)
    result=_run(plan['out'],plan['operation'],nodes=plan['nodes'],edges=plan['edges'],
        conditional=plan['conditional'],initial=plan['initial'],steps=plan['steps'])
    decisions.request(request_pin)
    if result['result'].get('phase')=='ordinary_effect_required':return deepcopy(result['result'])
    return deepcopy(plan['final'](result)['result'])


def _legacy_pause(payload):
    from . import graph_substrate
    graph_substrate.legacy_pause(payload)


def _open_plan(root, request_pin, output_dir, *, host, pause=None, stage_runner=None):
    """The open-research node table, edges and bounds shared by both engines.

    ``pause(payload)`` is where a node waits for an ordinary outside effect: a
    LangGraph interrupt on the legacy engine, a typed external-delivery turn on
    the substrate. ``stage_runner`` runs one bound protocol stage.
    """
    from . import research_coordinator_decisions as decisions, research_cycle as cycle, scientific_judgment as j, science
    from .agent_host import _loads
    interrupt=pause or _legacy_pause
    stage_runner=stage_runner or run_protocol_stage
    root=cycle._ordinary(root);value=decisions.request(request_pin)
    output_dir=cycle._ordinary(output_dir)
    if output_dir==root or not output_dir.is_relative_to(root):
        raise ValueError('coordinator effects must be inside its original campaign')
    contract={'schema_version':1,**deepcopy(value['campaign']), 'question':value['handoff']['original_request'],
        'scope':'Complete original research assignment; planning/preparation remain intermediate.',
        'context_request':value['context_request'] or value['planning_context'],
        'goal_binding':value['handoff']['goal_binding'], 'research_protocol_required': True,
        'research_regime':value.get('research_regime', 'open_exploratory')}
    if not root.exists():
        cycle.create(root,contract,base_dir=Path(value['parent_contract']['path']).parent)
    else:
        _,state=cycle._load(root)
        if state['contract']!=contract:
            raise RecoveryHold('existing campaign must preserve exact original task/source/context/ceiling; never reinitialize')
    out,operation=_session(output_dir,{'kind':'open-question','cycle':str(root),'request':request_pin,
        'host_sha256':graph._host_identity(host)})
    def validate(s):
        decisions.request(request_pin)
        _,state=cycle._load(root)
        if state['contract']!=contract:raise ValueError('original research contract changed')
        for row in s.get('action_results',[]):
            actual=cycle._graph_result(row['origin']['root'],row['origin']['node_id'])
            if actual!=row['origin']:raise ValueError('completed coordinator decision differs from original effect')
            committed=cycle._coordinator_effect(state,actual)
            if committed is None or committed['pin']!=row['effect']:
                raise ValueError('routing checkpoint effect lacks the original campaign commitment')
        return state
    def declaration_prepare(s):
        state=validate(s)
        if s.get('action')!='revise-context' and (value['context_request'] is not None or 'scientific_context_declaration' in state):
            return {'action':'assess-context'}
        if s['method_round']>=value['max_decisions']:
            interrupt({'kind':'original_method_design_population_exhausted',
                'whole_original_task':value['handoff'],'actual_send_backs':s['method_history'],
                'scientific_acceptance':False,'execution_authorized':False})
            raise RecoveryHold('prospective method repair needs a separately admitted continuation, no budget reset')
        prepared=decisions.prepare_decision(root,value,out/'methods'/str(s['method_round'])/'declare',
            phase='declare-context',method_feedback=s['method_history'],source_origins=s['source_requests'])
        return {'prepared':prepared,'model_spec':decisions.decision_spec(root,prepared,value['runtime'],graph_id='declare-scientific-context'),
            'action':'declare-context'}
    def declaration_call(s):
        origin=decisions.actual(root,out/'methods'/str(s['method_round'])/'declaration-graph',s['prepared'],s['model_spec'],host=host,settings=value['runtime'])
        return {'origin':origin}
    def declaration_sources(s):
        actual=cycle._graph_result(s['origin']['root'],s['origin']['node_id'])
        if actual!=s['origin']:raise ValueError('original source request changed')
        decisions.requested_sources(value,actual)
        return {'source_requests':[*s['source_requests'],actual],'method_round':s['method_round']+1,
            'action':'revise-context','role':''}
    def declaration_apply(s):
        actual=cycle._graph_result(s['origin']['root'],s['origin']['node_id'])
        if actual!=s['origin']:raise ValueError('context declaration changed before application')
        public=actual['value']['value']
        declared=_loads(public['context_json'])
        pin=decisions._put(out/'methods'/str(s['method_round'])/'declared-scientific-context.json',declared)
        state=validate(s)
        predecessor=state['context']['context_sha256'] if 'scientific_context_declaration' in state else None
        cycle.declare_context(root,pin,_loads(public['obligation_mapping_json']),graph_root=actual['root'],node_id=actual['node_id'],
            expected_context_sha256=predecessor)
        return {}
    def assessment_prepare(s):
        validate(s)
        role=s.get('role') or 'critic'
        prepared=decisions.prepare_assessment(root,value,out/'methods'/str(s['method_round'])/role,role=role)
        return {'role':role,'prepared':prepared,'model_spec':decisions.decision_spec(root,prepared,value['runtime'],graph_id='method-'+role)}
    def assessment_call(s):
        origin=decisions.actual(root,out/'methods'/str(s['method_round'])/(s['role']+'-graph'),s['prepared'],s['model_spec'],host=host,settings=value['runtime'])
        decisions.assessment_receipt(origin,s['prepared'],allow_control=value['review']['allow_control'])
        public=origin['value']['value']
        if public['subject_sha256']!=s['prepared']['subject_sha256']:
            raise ValueError('method assessment belongs to a different scientific declaration')
        return {'context_'+s['role']:{'origin':origin,'prepared':s['prepared']},'role':'verifier' if s['role']=='critic' else ''}
    def assessment_gate(s):
        validate(s)
        feedback=[];receipts=[]
        for key in ('context_critic','context_verifier'):
            bound=s[key];actual=cycle._graph_result(bound['origin']['root'],bound['origin']['node_id'])
            if actual!=bound['origin']:raise ValueError('context assessment changed')
            receipts.append(decisions.assessment_receipt(actual,bound['prepared'],allow_control=value['review']['allow_control']))
            current=value['context_request'] or cycle._load(root)[1]['scientific_context_declaration']['request']
            if bound['prepared']['subject_sha256']!=current['sha256']:
                raise ValueError('assessment cannot be reused for a different context')
            feedback.append(actual)
        if receipts[0]['request_id']==receipts[1]['request_id'] or receipts[0]['context_manifest_sha256']==receipts[1]['context_manifest_sha256']:
            raise ValueError('method critic/verifier require separate actual role requests')
        if any(o['value']['value']['verdict']!='adequate_for_prospective_tests' for o in feedback):
            if value['context_request'] is not None:
                interrupt({'kind':'independently_supplied_method_send_back','actual_assessments':feedback,
                    'original_obligations':value['handoff']['obligations'],'scientific_acceptance':False})
                raise RecoveryHold('independently declared context needs its explicit source revision; it cannot be silently replaced')
            return {'action':'revise-context','role':'','method_round':s['method_round']+1,
                'method_history':[*s['method_history'],*feedback]}
        return {'action':'method-adequate','role':''}
    def idea_prepare(s):
        validate(s)
        from . import research_protocol
        methodology = research_protocol.methodology_status(root)
        if methodology['next_stage'] == 'limitation_census':
            interrupt({'kind': 'research_stage_required', 'stage': methodology['record']['stages'][0],
                       'command': 'ravel research-protocol stage-prepare', 'execution_authorized': False})
            if research_protocol.methodology_status(root)['next_stage'] == 'limitation_census':
                raise RecoveryHold('required limitation census and sufficiency verification remain incomplete')
        prepared = {}
        nodes = []
        for stream in ('citation_led', 'speculative'):
            item = decisions.prepare_decision(root, value, out/('ideas-'+stream),
                                             phase='hypotheses', stream=stream)
            prepared[stream] = item
            node = decisions.decision_spec(root, item, value['runtime'], graph_id='ideas-'+stream)['nodes'][0]
            node['id'] = stream
            nodes.append(node)
        spec = {'schema_version': 1, 'graph_id': 'parallel-ideas', 'nodes': nodes,
                'budget': {'max_nodes': 2, 'max_calls': 2, 'max_reworks': 0,
                           'max_output_tokens': 2 * value['runtime']['max_output_tokens'],
                           'max_wall_seconds': value['runtime']['max_wall_seconds']}}
        return {'role': '', 'prepared_ideas': prepared, 'model_spec': spec}
    def idea_call(s):
        from . import graph_substrate
        graph_root = out/'parallel-ideas-graph'
        result = graph_substrate.execute_role_graph(root, graph_root, s['model_spec'], host,
                                                     prepared=graph_root.exists(), workers=2)
        if not result['complete']:
            interrupt({'kind': 'parallel_idea_delivery_required', 'graph_root': str(graph_root),
                       'actual_graph': result, 'acceptance_from_resume': False})
            result = graph_substrate.execute_role_graph(root, graph_root, s['model_spec'], host,
                                                         prepared=True, workers=2)
            if not result['complete']:
                raise RecoveryHold('both independent idea streams must finish')
        origins = {}
        for stream, key in (('citation_led', 'citation'), ('speculative', 'speculative')):
            prepared = s['prepared_ideas'][stream]
            for pin in prepared['inputs']:
                cycle._check_pin(pin, Path(pin['path']).parent)
            origin = cycle._graph_result(graph_root, stream)
            node = next(n for n in s['model_spec']['nodes'] if n['id'] == stream)
            if origin['inputs'] != node['inputs'] or origin['value'].get('kind') != 'model_result':
                raise ValueError('parallel idea result lacks its exact source-separated request')
            origins[key] = origin
        return {**origins, 'role': ''}
    def idea_adopt(s):
        validate(s)
        # Neither stream is adopted/presented until both source-separated turns
        # finish. Real rival ideas live only in the existing hypothesis journal.
        decisions.adopt_hypotheses(root,s['citation'],stream='citation_led')
        decisions.adopt_hypotheses(root,s['speculative'],stream='speculative')
        return {}
    def decision_prepare(s):
        validate(s)
        if s['turn']>=value['max_decisions']:
            return {'action':'progress','arguments':{'reason':'Original declared decision population exhausted.'}}
        prepared=decisions.prepare_decision(root,value,out/'turns'/str(s['turn'])/'context',phase='action',effects=s['action_results'],source_origins=s['source_requests'])
        return {'prepared':prepared,'model_spec':decisions.decision_spec(root,prepared,value['runtime'],graph_id='research-action-'+str(s['turn'])),'action':'choose'}
    def decision_call(s):
        origin=decisions.actual(root,out/'turns'/str(s['turn'])/'graph',s['prepared'],s['model_spec'],host=host,settings=value['runtime'])
        public=origin['value']['value']
        if public['kind']!='research-action':raise ValueError('source-bound actual research action required')
        cycle._text(public['reason']);args=_loads(public['arguments_json'])
        return {'origin':origin,'action':public['action'],'arguments':args}
    def selected_operation(s):
        validate(s)
        # This node completes before approval/execution can interrupt. On
        # resume the chosen original identity survives selector exclusions.
        if s['action']!='run-selected':return {'selected':''}
        cycle.ce.keys(s['arguments'],set())
        selected=cycle.select(root)
        return {'selected':selected['selected'] or '','selection':selected}
    def action_effect(s):
        state=validate(s);action=s['action'];args=deepcopy(s['arguments'])
        origin=cycle._graph_result(s['origin']['root'],s['origin']['node_id'])
        public=origin['value'].get('value',{})
        if (origin!=s['origin'] or public.get('kind')!='research-action'
                or public.get('action')!=action or _loads(public['arguments_json'])!=args):
            raise ValueError('routing checkpoint differs from actual source-bound model action')
        dest=out/'turns'/str(s['turn'])/'effect'
        committed=cycle._coordinator_effect(state,origin)
        if committed is not None:
            if committed['pin']['path']!=str(dest/'coordinator-effect.json'):
                raise ValueError('committed effect belongs to another original coordinator turn')
            effect=committed['document']['actual_effect']
            return {'action_results':[*s.get('action_results',[]),{'origin':origin,'effect':committed['pin']}],
                'turn':s['turn']+1,'result':effect}
        if action=='protocol-stage':
            cycle.ce.keys(args, {'artifact'})
            effect=stage_runner(root, args['artifact'], dest/'protocol', host=host, settings=value['runtime'])
            if not effect.get('complete'):
                interrupt(effect)
                effect=stage_runner(root, args['artifact'], dest/'protocol', host=host, settings=value['runtime'])
                if not effect.get('complete'):
                    raise RecoveryHold('required research stage role delivery remains pending')
        elif action=='experiment':
            effect=decisions.admit_experiment(root,value,s['origin'],dest,args)
        elif action=='source-context':
            effect={'materialized_inputs':decisions.requested_sources(value,s['origin']),
                'source_read_credit':'Files enter the NEXT actual model request; this request has only asked for them.',
                'scientific_acceptance':False}
        elif action=='preparation-tool':
            effect=decisions.preparation_tool(root,value,s['origin'],args,dest,host)
        elif action=='propose':
            cycle.ce.keys(args,{'hypotheses'})
            # Actual response stays unchanged. The action envelope, not a forged
            # stand-in origin, must match the public producer at journal entry.
            effect=cycle.propose_action(root,s['origin'],args['hypotheses'])
        elif action=='revise-premise':
            cycle.ce.keys(args,{'identity','statement','basis','reason'})
            allowed={(p['path'],p['sha256']) for p in s['origin']['inputs']}
            if any((p['path'],p['sha256']) not in allowed for p in args['basis']):raise ValueError('premise source was not presented')
            effect=cycle.revise_premise(root,coordinator_origin=origin,**args)
        elif action=='predictive-selection':
            cycle.ce.keys(args, {'experiment','graph_root','node_id'} if 'graph_root' in args else {'experiment','rundir'})
            experiment=args['experiment']
            selected_args={k:v for k,v in args.items() if k!='experiment'}
            updated=cycle.bind_quantitative_selection(root,experiment,**selected_args)
            effect={'experiment':experiment,'state_sha256':updated['sha256'],'execution_authorized':False,'scientific_acceptance':False}
        elif action=='run-selected':
            cycle.ce.keys(args,set())
            selected=s['selected']
            if not selected:
                return {'action':'progress','result':cycle.progress_synthesis(root),'turn':s['turn']+1}
            e=next(e for e in state['experiments'] if e['id']==selected)
            rundir=dest/'study'
            if s['selection'].get('selected')!=selected:
                raise ValueError('checkpoint replaced the original selected experiment')
            if e['rundir'] is None:
                if cycle.select(root)!=s['selection']:
                    raise RecoveryHold('actual selection changed before scientific preparation; redesign explicitly')
                state=cycle.prepare_experiment(root,selected,rundir)
            elif e['rundir']!=str(rundir):
                raise RecoveryHold('selected effect already belongs to another ordinary run; retain and reconcile')
            _ordinary_approval_gate(rundir, selected=selected, goal_binding=contract['goal_binding'])
            status=science.packet(rundir)['execution']['status']
            if status in {'approved','planned'}:cycle.run_experiment(root,selected)
            elif status=='running':
                interrupt({'kind':'owned_worker_reconciliation_required','rundir':str(rundir)})
                if science.packet(rundir)['execution']['status']=='running':raise RecoveryHold('do not repeat an unknown running scientific effect')
            _,state=cycle._load(root);e=next(e for e in state['experiments'] if e['id']==selected)
            if e['observation'] is None:state=cycle.observe(root,selected)
            else:cycle._current_evidence(state,e)
            effect={'experiment':selected,'actual_observation':next(e['observation'] for e in state['experiments'] if e['id']==selected)}
        elif action=='review':
            cycle.ce.keys(args,{'experiment','check_results'})
            e=next(e for e in state['experiments'] if e['id']==args['experiment'])
            if e['observation'] is None:raise ValueError('actual observation required before scientific review')
            cycle._check_pin(args['check_results'],state['base_dir'])
            if j.next_step(e['rundir'])['phase']=='open_cycle':j.open_cycle(e['rundir'],check_results=args['check_results']['path'])
            effect=review(e['rundir'],dest/'review',host=host,campaign=root,experiment=e['id'],
                allow_control=value['review']['allow_control'],**value['review']['arguments'])
            if effect['phase'] in {'ordinary_effect_required','context_requested','retained_evidence_requested'}:
                current=j.next_step(e['rundir'])
                if current['phase'] not in {'scoped_delivery','final_results_reviewed','stopped','new_experiment_required','repair_proposal'}:
                    interrupt({'kind':'fresh_bound_role_evidence_required','actual_review':effect})
                    current=j.next_step(e['rundir'])
                if current['phase'] not in {'scoped_delivery','final_results_reviewed','stopped','new_experiment_required','repair_proposal'}:
                    raise RecoveryHold('fresh presented role evidence remains unresolved')
                effect=current
            if effect['phase'] in {'scoped_delivery','final_results_reviewed','stopped','new_experiment_required','repair_proposal'}:
                _,now=cycle._load(root);actual=next(row for row in now['experiments'] if row['id']==args['experiment'])
                if actual['adjudication'] is None and cycle.physics_review.active(e['rundir']) and cycle.physics_review.status(e['rundir'])['state'] in {'accepted','send_back','stopped'}:
                    from . import gate_wiring  # research_choice before every adjudication.
                    gate_wiring.require_research_choice(root,e['id'])
                    cycle.adjudicate(root,e['id'])
        elif action=='diagnose':
            effect=decisions.diagnose(root,value,args,dest,host)
        elif action=='synthesize':
            cycle.ce.keys(args,{'report_request'})
            recipe=_read(args['report_request'])
            effect=cycle.synthesize(root,recipe,base_dir=state['base_dir'])
        elif action=='progress':
            cycle.ce.keys(args,{'reason'});cycle._text(args['reason'])
            return {'result':cycle.progress_synthesis(root),'action':'progress','turn':s['turn']+1}
        else:
            rows=decisions.catalogue(value['candidate_modes'])['extensions']
            if not any(r['action']==action and r['status']=='connected_public_source' for r in rows):
                raise ValueError('uncomposed domain operation cannot be invoked')
            effect=decisions.invoke_extension(action,root,args,dest,host,value['runtime'])
        effect_pin=decisions._put(dest/'coordinator-effect.json',{'action':action,'arguments':args,
            'origin':s['origin'],'actual_effect':effect,'parent_task_accepted':False,'scientific_authority_from_checkpoint':False})
        cycle._record_coordinator_effect(root,s['origin'],effect_pin)
        history=[*s.get('action_results',[]),{'origin':s['origin'],'effect':effect_pin}]
        return {'action_results':history,'turn':s['turn']+1,'result':effect}
    def final(s):
        validate(s)
        for row in s.get('action_results',[]):_read(row['effect'])
        if s['action']=='synthesize':
            return {'result':cycle.synthesize(root,_read(s['arguments']['report_request']),base_dir=cycle._load(root)[1]['base_dir'])}
        return {'result':cycle.progress_synthesis(root)}
    nodes={'declare_prepare':declaration_prepare,'declare_call':declaration_call,'declare_sources':declaration_sources,'declare_apply':declaration_apply,
        'assessment_prepare':assessment_prepare,'assessment_call':assessment_call,'assessment_gate':assessment_gate,
        'idea_prepare':idea_prepare,'idea_call':idea_call,'idea_adopt':idea_adopt,
        'decision_prepare':decision_prepare,'decision_call':decision_call,'selected_operation':selected_operation,'action_effect':action_effect,'whole_question':final}
    return {'value':value,'contract':contract,'out':out,'operation':operation,'nodes':nodes,'final':final,
        'validate':validate,'edges':OPEN_EDGES,'conditional':OPEN_CONDITIONAL,
        'initial':deepcopy(OPEN_INITIAL),'steps':32+20*value['max_decisions']}


def run_protocol_stage(root, artifact, output_dir, *, host, settings):
    """Resume one required stage using ordinary charged Graph/external delivery."""
    from . import research_protocol as protocol, research_cycle as cycle
    from . import research_coordinator_decisions as decisions
    out = Path(output_dir)
    binding_path = out / 'preparation.json'
    if binding_path.exists():
        prepared = _read(_pin(binding_path))
        if prepared['artifact'] != artifact:
            raise RecoveryHold('research stage proposal changed; retain the original review and prepare a new one')
    else:
        stage = protocol.methodology_status(root)['next_stage']
        if stage is None:
            raise ValueError('all bound research stages already complete')
        from .graphs import stage as stage_graph
        options, _ = stage_graph.model_options(stage, settings)
        prepared = protocol.prepare_stage(root, stage, artifact, out/'review', **options)
        decisions._put(binding_path, prepared)
    graph_root = out / 'graph'
    spec = _read(prepared['specification'])
    result = cycle.execute_graph(root, graph_root, spec, host, prepared=graph_root.exists(),
                                 workers=prepared['workers'])
    if not result['complete']:
        return {'kind': 'research-stage-delivery-required', 'stage': prepared['stage'],
                'complete': False, 'graph_root': str(graph_root), 'graph': result,
                'execution_authorized': False}
    current = protocol.methodology_status(root)
    if next(r for r in current['record']['stages'] if r['id'] == prepared['stage'])['status'] == 'done':
        return {'complete': True, 'methodology': current, 'scientific_acceptance': False}
    decisions.receipt_family_check(prepared['stage'], graph_root, settings)  # F8: observed models, R2+
    completed = protocol.complete_stage(root, prepared, graph_root)
    return {'complete': True, 'methodology': completed, 'scientific_acceptance': False}


def host_prepare(parameters, pins):
    """Deterministic ordinary intake preparation; no nested model dispatch."""
    from . import research_cycle as cycle
    cycle.ce.keys(parameters,{'request_input','output_dir'})
    identity=parameters['request_input']
    if identity not in pins:raise ValueError('open research request must be an actual Graph input')
    path,sha=pins[identity]
    pin={'path':str(path),'sha256':sha,'size':Path(path).stat().st_size}
    request=_read(pin)
    cycle.ce.keys(request,{'parent_contract','settings'})
    allowed={(str(p),h) for p,h in pins.values()}
    required=[request['parent_contract'],*[r['pin'] for r in request['settings']['evidence']]]
    context_pin=request['settings'].get('context_request')
    if context_pin is not None:
        required.append(context_pin)
        required.extend(cycle.scientific_context.input_pins(_read(context_pin),Path(path).parent))
    knowledge_pin=request['settings'].get('knowledge')
    if knowledge_pin is not None:
        required.append(knowledge_pin)
        _,dependencies=cycle._knowledge_packet(knowledge_pin,Path(path).parent)
        required.extend(dependencies)
    from .task_completion import binding_projection
    from . import intake
    handoff=intake.execution_handoff(
        request['parent_contract'],base_dir=Path(path).parent)
    required.extend(binding_projection(handoff['goal_binding'],base_dir=Path(path).parent)['input_pins'])
    required=[cycle._check_pin(p,Path(path).parent)[1] for p in required]
    if any((p['path'],p['sha256']) not in allowed for p in required):
        raise ValueError('complete declared task/context/evidence custody must be normal preparation inputs')
    return prepare_open(request['parent_contract'],parameters['output_dir'],
        base_dir=Path(path).parent,**request['settings'])


# ---- the graph engine (research.loop) ------------------------------------------------------

ENGINES=('graph','legacy')
LOOP_GRAPH='research.loop'
PARITY_RECORD=Path(__file__).resolve().parents[1]/'data/graphs/parity/research-loop.json'


PARITY_FIXTURES=('synthetic-open-question','synthetic-protocol-stages','open-question-baseline-failure')
# The loop's implementation: the shared node table, the two graph builders and their service adapter.
PARITY_SOURCES=('workflow/research_orchestrator.py','workflow/graphs/__init__.py','workflow/graphs/research_loop.py',
    'workflow/graphs/stage.py')
PARITY_FIXTURE_SOURCES=('tests/unit/test_research_loop_graph.py',)
PARITY_NOTE=('R2 and higher stages need distinct-family critics, which need per-role stage models '
    '(prepare_stage role_models); the fixtures stop at the first R2 stage, which both engines refuse at '
    'dispatch. complete_stage re-checks a stage reservation with the campaign\'s inherited goal binding on '
    'both engines (test_goal_bound_stage_completion).')


def parity_bindings():
    """What a parity record is for: the registered loop, its child graphs and the loop's implementation bytes."""
    from . import graph_registry, graph_substrate
    row=graph_registry.get(LOOP_GRAPH)
    package=Path(__file__).resolve().parents[1]
    return {'graph_id':LOOP_GRAPH,'version':row['version'],'structure_sha256':row['structure_sha256'],
        'closure':[[gid,ver,graph_registry.get(gid)['structure_sha256']] for gid,ver in graph_substrate.closure(LOOP_GRAPH)],
        'implementation':{rel:hashlib.sha256((package/rel).read_bytes()).hexdigest() for rel in PARITY_SOURCES}}


def parity_digest(record):
    from . import agent_graph as graph
    return graph.digest({k:v for k,v in record.items() if k!='sha256'})


def parity_result(fixture_id, test, legacy_snapshot, graph_snapshot, *, run_path):
    """One fixture's computed result: run-relative digests of both engines' parity snapshots."""
    from . import agent_graph as graph
    def relative(snapshot):
        text=json.dumps({k:v for k,v in snapshot.items() if k!='sha256'},sort_keys=True,allow_nan=False)
        return graph.digest(json.loads(text.replace(str(Path(run_path)),'<run>')))
    legacy,current=relative(legacy_snapshot),relative(graph_snapshot)
    return {'id':fixture_id,'test':test,'legacy_sha256':legacy,'graph_sha256':current,'equal':legacy==current}


def parity_record(results, *, repository=None):
    """The kept parity record, computed from the parity tests' results and the current bindings."""
    fixtures=[]
    for row in sorted(results,key=lambda r:r['id']):
        fixtures.append({'id':row['id'],'test':row['test'],'legacy_sha256':row['legacy_sha256'],
                         'graph_sha256':row['graph_sha256'],'equal':row['legacy_sha256']==row['graph_sha256']})
    repository=Path(repository) if repository is not None else Path(__file__).resolve().parents[3]
    sources={rel:hashlib.sha256((repository/rel).read_bytes()).hexdigest()
             for rel in PARITY_FIXTURE_SOURCES if (repository/rel).is_file()}
    record={'schema_version':2,'kind':'graph-parity-record','bindings':parity_bindings(),
        'engines':{'legacy':'research_orchestrator.open_research (langgraph_runtime.run_state_machine)',
                   'graph':'research_orchestrator.run_graph (research.loop on graph_substrate)'},
        'comparison':('research_orchestrator.parity_snapshot, run-relative: request identities, result values, '
            'statuses, gate records, stage records, committed coordinator effects, campaign events and usage; '
            'run-unique identifiers, clocks and the digests that cover them excluded (VOLATILE_KEYS)'),
        'fixtures':fixtures,'fixture_sources':sources,'note':PARITY_NOTE}
    return {**record,'sha256':parity_digest(record)}


def parity_status():
    """The kept dual-run parity record for the registered loop; the default switches only on it.

    The record is computed by ``parity --write`` from the parity tests' results. Its digest is
    checked, equality is recomputed from each fixture's recorded snapshot digests, and the
    record lapses when the loop graph, a child graph or the loop's implementation bytes change.
    """
    try:record=json.loads(PARITY_RECORD.read_text())
    except (OSError,ValueError):return {'passed':False,'reason':'parity record absent','record':None}
    if type(record) is not dict or record.get('kind')!='graph-parity-record' or record.get('schema_version')!=2:
        return {'passed':False,'reason':'parity record has an unknown kind or schema','record':record}
    if record.get('sha256')!=parity_digest(record):
        return {'passed':False,'reason':'parity record digest differs','record':record}
    if record.get('bindings')!=parity_bindings():
        return {'passed':False,'reason':'parity record is for another loop implementation','record':record}
    fixtures=record.get('fixtures') or []
    if {f.get('id') for f in fixtures}!=set(PARITY_FIXTURES):
        return {'passed':False,'reason':'parity fixtures missing','record':record}
    if not all(type(f.get('legacy_sha256')) is str and f.get('legacy_sha256')==f.get('graph_sha256') for f in fixtures):
        return {'passed':False,'reason':'a parity fixture differs','record':record}
    return {'passed':True,'reason':None,'record':record}


def engine_label(*, experimental=False):
    """The graph engine's label: refused without a current parity record unless explicitly experimental."""
    status=parity_status()
    if status['passed']:
        return {'engine':'graph','engine_label':'graph','parity_passed':True}
    if not experimental:
        raise ValueError(f"the graph engine has no current parity record ({status['reason']}); pass "
                         "--experimental-engine to run it as an experimental engine, or use --engine legacy")
    return {'engine':'graph','engine_label':'experimental-engine','parity_passed':False}


# Run-unique identifiers and clocks are excluded from the dual-run comparison set. Digests are
# excluded too: an agent Graph request embeds a random attempt id, and every later document that
# cites a model result carries it transitively. Requests, results and records are compared by
# their normalized content instead.
VOLATILE_KEYS=('utc','epoch','instance_id','run_id','request_id','attempt_id','invocation_id','call_id','elapsed',
    'duration','pid','sequence','started','finished','deadline','created','timestamp',
    'external_response_pin','external_completion_evidence')
ATTEMPT_PATH=re.compile(r'(attempts|requests)/[0-9a-f]{32}')


def _normalized(value):
    if isinstance(value,dict):
        return {k:_normalized(v) for k,v in sorted(value.items())
                if k!='sha256' and not k.endswith(('_sha256','_sha256s'))
                and not any(k==v_ or k.endswith('_'+v_) or k.startswith(v_+'_') for v_ in VOLATILE_KEYS)}
    if isinstance(value,list):
        return [_normalized(v) for v in value]
    if isinstance(value,str):
        return ATTEMPT_PATH.sub(r'\1/<attempt>',value)
    return value


def parity_snapshot(root, graph_roots=None):
    """The normalized dual-run comparison set: request identities, result digests, statuses,
    gate records and stage records, plus committed coordinator effects.

    Substrate-only fields (graph, framework_step, charges, downstream, effect receipts) and
    run-unique identifiers and clocks (``VOLATILE_KEYS``) are excluded. Two engines running the
    same fixture at the same paths compare equal exactly when they dispatched the same roles on
    the same requests and committed the same results.
    """
    from . import agent_graph, research_cycle as cycle, research_protocol as protocol
    root=Path(root)
    def document(pin):
        return _normalized(json.loads(Path(pin['path'] if Path(pin['path']).is_absolute() else root/pin['path']).read_text()))
    status=protocol.methodology_status(root)
    stages,gates=[],{}
    for row in status['record']['stages']:
        stages.append({'id':row['id'],'status':row['status'],'reason':row.get('reason'),'round':row.get('round'),
            'roles':row['roles'],'artifact':row.get('artifact'),
            'preparation':_normalized(row.get('active_preparation')),
            'receipts':{role:document(pin) for role,pin in sorted((row.get('worker_receipts') or {}).items())}})
        gates[row['id']]=[[e.code,e.message] for e in protocol.gate_errors(root,'research_choice',{'scope':row['id']})]
    _,state=cycle._load(root)
    if graph_roots is None:
        graph_roots=sorted(row['root'] for row in state['graphs'])
    graphs=[]
    for graph_root in graph_roots:
        current=agent_graph.status(graph_root)
        nodes={}
        for node_id,node in sorted(current['nodes'].items()):
            result=agent_graph._result(Path(graph_root),node['result']) if node['result'] else None
            request=node.get('external_request')
            asked=json.loads((Path(graph_root)/request['path']).read_text()) if request else None
            nodes[node_id]={'status':node['status'],'attempts':node['attempts'],
                'request_identity_sha256':graph.digest(_normalized(asked)) if asked is not None else None,
                'result_sha256':graph.digest(_normalized(result)) if result is not None else None}
        spec=json.loads((Path(graph_root)/agent_graph.SPEC).read_text())
        graphs.append({'root':str(graph_root),'specification_sha256':graph.digest(_normalized(spec)),
            'usage':current['usage'],'nodes':nodes,
            'calls':sorted(graph.digest(_normalized(call)) for call in current['calls'].values())})
    effects=[]
    for event in state['events']:
        if event['kind']=='coordinator_effect_committed':
            effects.append(document(event['effect']))
    value={'schema_version':1,'kind':'research-parity-snapshot','methodology_complete':status['complete'],
        'stages':stages,'gates':gates,'graphs':graphs,'events':[e['kind'] for e in state['events']],
        'coordinator_effects':effects,'usage':cycle._usage(state)}
    return {**value,'sha256':graph.digest(value)}


def default_engine():
    return 'graph' if parity_status()['passed'] else 'legacy'


def engine_for(cycle_root, output_dir, requested=None, *, experimental=False):
    """The engine for this coordinator: the one that started it, else the request, else the default.

    The graph engine without a current parity record is refused unless ``experimental``.
    """
    started=('legacy' if (Path(output_dir)/'framework'/'checkpoints.sqlite').exists() else
             'graph' if (Path(cycle_root)/graph_substrate_db()).exists() else None)
    if started is not None and requested not in (None,started):
        raise ValueError(f'this coordinator started on the {started} engine; continue it with --engine {started}')
    engine=started or requested or default_engine()
    if engine=='graph':
        engine_label(experimental=experimental)
    return engine


def graph_substrate_db():
    from . import graph_substrate
    return graph_substrate.DB


def campaign_gates(root, parent_rundir):
    """Gate check for a campaign scope: the protocol provider on the campaign, the rest on the parent run.

    The research loop's scope root is its campaign; the decision gate's run facts live in
    the parent run that owns the research request. Every other provider still runs there.
    """
    from . import decision_gate, research_protocol
    root,parent_rundir=Path(root),Path(parent_rundir)
    def check(scope_root, gate, action):
        errors=list(research_protocol.gate_errors(root,gate,action)) if gate=='research_choice' else []
        errors+=[e for e in decision_gate.check(parent_rundir,gate,action) if e.provider!='research_protocol']
        return errors
    return check


def _parent_rundir(plan):
    contract=Path(plan['value']['parent_contract']['path'])
    return contract.parent.parent if contract.parent.name=='inputs' else contract.parent


def _loop_instance(plan, request_pin):
    return {'campaign':plan['value']['campaign']['id'],'request':request_pin['sha256']}


def run_graph(root, request_pin, output_dir, *, host, clear_stop=False, max_steps=None, gate_check=None,
              experimental=False):
    """``research.loop`` on the substrate: the same nodes, receipts and services as ``open_research``.

    The legacy preparation (campaign creation, the bound operation) runs first, unchanged.
    The runner holds the campaign scope; ``ravel graph stop --scope-root <campaign>`` drains it
    and this call continues it. A wait is an interrupt answered by ``ravel graph respond``
    (or ``respond_graph``); a failure ends in a typed status, never a refusal of the run.
    Without a current parity record it is refused unless ``experimental``; the outcome says which.
    """
    from . import graph_substrate
    from .graphs import hosts
    label=engine_label(experimental=experimental)
    plan=_open_plan(root,request_pin,output_dir,host=host)
    from . import research_cycle as cycle
    out=Path(plan['out']);root=cycle._ordinary(root)
    if (out/'framework'/'checkpoints.sqlite').exists():
        raise RecoveryHold('this coordinator started on the legacy engine; continue it with --engine legacy')
    instance=_loop_instance(plan,request_pin)
    parent=_parent_rundir(plan)
    with hosts(host) as key:
        observation=graph_substrate.run(root,LOOP_GRAPH,instance,input={
            'loop':{'request':deepcopy(request_pin),'out':str(out),'host':key,'operation':plan['operation']},
            **plan['initial']},max_steps=max_steps or 4*plan['steps']+64,clear_stop=clear_stop,
            gate_check=gate_check or campaign_gates(root,parent))
    return {**_graph_outcome(root,plan,instance,observation),**label}


def respond_graph(root, request_pin, output_dir, responses, *, host, gate_check=None, clear_stop=False,
                  experimental=False):
    """Answer the loop's pending interrupts (validated before resume), then continue it."""
    from . import graph_substrate
    from .graphs import hosts
    label=engine_label(experimental=experimental)
    plan=_open_plan(root,request_pin,output_dir,host=host)
    from . import research_cycle as cycle
    root=cycle._ordinary(root);instance=_loop_instance(plan,request_pin)
    parent=_parent_rundir(plan)
    with hosts(host):
        observation=graph_substrate.respond(root,LOOP_GRAPH,instance,responses,clear_stop=clear_stop,
            gate_check=gate_check or campaign_gates(root,parent))
    return {**_graph_outcome(root,plan,instance,observation),**label}


def _graph_outcome(root, plan, instance, observation):
    from . import graph_substrate
    if observation['interrupts']:
        return {'phase':'ordinary_effect_required','engine':'graph','checkpoint':observation,
                'execution_authorized':False}
    _,_,snapshot=graph_substrate._pending(root,LOOP_GRAPH,instance)
    values=snapshot.values or {}
    if observation['terminal'] is not None or observation['next']:
        failures=list((values.get('failures') or {}).values())
        return {'phase':(observation['terminal'] or {}).get('status') or 'paused','engine':'graph',
                'status':observation['terminal'],'failures':failures[-3:],'checkpoint':observation,
                'execution_authorized':False,'scientific_acceptance':False}
    return deepcopy(plan['final']({k:v for k,v in values.items() if k in ResearchState.__annotations__})['result'])


def stop(root, *, reason, now=False):
    """Drain the research loop (R-56): no new step is dispatched; running effects finish and receipt.

    ``now`` also drains every incomplete child agent Graph of the campaign, raises their
    cancellation epochs, terminates only registered process groups and verifies them gone.
    """
    from . import graph_substrate, research_cycle as cycle
    root=Path(root).absolute()
    loop=graph_substrate.stop(root,reason=reason,now=now)
    children=[]
    if now and (root/'head.json').exists():
        _,state=cycle._load(root)
        for row in state['graphs']:
            if not row.get('complete') and Path(row['root']).is_dir():
                children.append({'root':row['root'],**graph_substrate.stop(Path(row['root'])/'effects',
                                                                             reason=reason,now=True)})
    # A drained runner releases its scope; until then a running in-process call may still finish.
    running=[scope for scope in [str(root),*[str(Path(c['root'])/'effects') for c in children]]
             if graph_substrate.status(scope)['holder'] is not None]
    return {'loop':loop,'children':children,'running':running,
            'all_gone':loop['all_gone'] and all(c['all_gone'] for c in children) and not running,
            'framework_values_are_scientific_authority':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',nargs='?',choices=['prepare','run','explicit','respond','stop','parity'],default='run')
    parser.add_argument('--cycle',type=Path)
    parser.add_argument('--request',type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--host-config',type=Path)
    parser.add_argument('--parent-contract',type=Path)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--engine',choices=ENGINES,help='run engine; the default is graph once its parity record passes')
    parser.add_argument('--experimental-engine',action='store_true',
                        help='run the graph engine without a current parity record; outcomes are labelled experimental-engine')
    parser.add_argument('--clear-stop',action='store_true')
    parser.add_argument('--write',action='store_true',help='parity: compute and write the kept record from --results')
    parser.add_argument('--results',type=Path,help='parity --write: JSON lines of parity test results')
    parser.add_argument('--responses',type=Path,help='respond: JSON object of interrupt id to response value')
    parser.add_argument('--reason')
    parser.add_argument('--now',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='parity':
            if args.write:
                if args.results is None:raise ValueError('parity --write requires --results from the parity tests')
                rows=[json.loads(line) for line in args.results.read_text().splitlines() if line.strip()]
                record=parity_record(rows)
                PARITY_RECORD.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
            result={**parity_status(),'default_engine':default_engine()}
        elif args.command=='stop':
            if args.cycle is None or not args.reason:
                raise ValueError('stop requires --cycle and --reason')
            result=stop(args.cycle,reason=args.reason,now=args.now)
        elif args.command=='prepare':
            if args.out is None or args.parent_contract is None or args.settings is None:
                raise ValueError('prepare requires original parent contract and finite source/input/runtime settings, not an authored DAG')
            settings=_read(_pin(args.settings))
            result=prepare_open(_pin(args.parent_contract),args.out,base_dir=args.parent_contract.parent,**settings)
        else:
            if args.cycle is None or args.request is None or args.host_config is None or args.out is None:
                raise ValueError('run/explicit require original cycle/request and actual Host configuration')
            engine=None if args.command=='explicit' else engine_for(
                args.cycle,args.out,'graph' if args.command=='respond' else args.engine,
                experimental=args.experimental_engine)
            from .agent_host import AgentHost
            host=AgentHost.from_config(_read(_pin(args.host_config)))
            if args.command=='respond':
                if args.responses is None:raise ValueError('respond requires --responses')
                result=respond_graph(args.cycle,_pin(args.request),args.out,json.loads(args.responses.read_text()),
                    host=host,clear_stop=args.clear_stop,experimental=args.experimental_engine)
            elif args.command=='explicit':
                result=coordinate(args.cycle,_pin(args.request),args.out,host=host)
            elif engine=='graph':
                result=run_graph(args.cycle,_pin(args.request),args.out,host=host,clear_stop=args.clear_stop,
                                 experimental=args.experimental_engine)
            else:
                result=open_research(args.cycle,_pin(args.request),args.out,host=host)
        print(json.dumps(result,indent=2,allow_nan=False)); return 0
    except (OSError,ValueError,TypeError,KeyError) as error:
        print(json.dumps({'status':'refused','error':str(error),'scientific_acceptance':False})); return 2


if __name__=='__main__':
    raise SystemExit(main())
