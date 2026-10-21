"""Source-bound decisions for the default open-question research coordinator.

This module prepares real ordinary model Graphs and consumes their actual
results. LangGraph owns routing/history; the campaign, scientific operations,
role journals and original task service remain the accounting/authority layer.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
from . import research_controller

from . import agent_graph as graph, research_cycle as cycle, science
from . import research_orchestrator as orchestrator
from .source_syntax import facts as _syntax_facts
from .research_protocol import fresh_delivery, instruction

MAX_CORE_BYTES = 1_500_000
RUNTIME_KEYS = {'model', 'reasoning_effort', 'adapter', 'max_output_tokens', 'max_wall_seconds'}
EXTENSIONS = {
    'protocol-register': ('ravel.workflow.research_protocol', 'register_concerns'),
    'literature-acquire': ('ravel.workflow.research_tools', 'acquire_literature'),
    'literature-discover': ('ravel.workflow.research_tools', 'discover_literature'),
    'literature-discovered-sources': ('ravel.workflow.research_tools', 'prepare_discovered_sources'),
    'literature-context': ('ravel.workflow.research_tools', 'prepare_literature_context'),
    'literature-pdf': ('ravel.workflow.research_tools', 'extract_literature_pdf'),
    'replication-prepare': ('ravel.workflow.fresh_replication', 'prepare_replication_request'),
    'replication-design': ('ravel.workflow.fresh_replication', 'design_prepared'),
    'replication-comparison': ('ravel.workflow.fresh_replication', 'prepare_comparison'),
    'model-proposals': ('ravel.workflow.research_tools', 'prepare_model_proposals'),
    'routine-workflow': ('ravel.workflow.research_tools', 'routine_workflow'),
    'routine-step': ('ravel.workflow.research_tools', 'routine_step'),
    'manuscript-story': ('ravel.workflow.manuscript_workflow', 'prepare_story'),
    'manuscript-phase': ('ravel.workflow.manuscript_workflow', 'prepare_phase'),
    'manuscript-consume-phase': ('ravel.workflow.manuscript_workflow', 'consume_phase'),
    'manuscript-resolve-sources': ('ravel.workflow.manuscript_workflow', 'resolve_sources'),
    'manuscript-assemble': ('ravel.workflow.manuscript_workflow', 'assemble'),
    'manuscript-revision': ('ravel.workflow.manuscript_workflow', 'prepare_revision'),
    'manuscript-literature': ('ravel.workflow.manuscript_workflow', 'prepare_literature'),
    'manuscript-supplementary': ('ravel.workflow.manuscript_workflow', 'prepare_supplementary'),
    'manuscript-actions': ('ravel.workflow.manuscript_workflow', 'prepare_actions'),
    'manuscript-action-meta': ('ravel.workflow.manuscript_workflow', 'prepare_action_meta'),
    'manuscript-successor': ('ravel.workflow.manuscript_workflow', 'prepare_successor'),
    'manuscript-action-resolve': ('ravel.workflow.manuscript_workflow', 'resolve_actions'),
    'manuscript-author': ('ravel.workflow.manuscript_production', 'prepare_writer'),
    'manuscript-collect': ('ravel.workflow.manuscript_production', 'collect'),
    'manuscript-build': ('ravel.workflow.manuscript_production', 'prepare_build'),
    'manuscript-review': ('ravel.workflow.manuscript_production', 'prepare_integrity_role'),
    'manuscript-consume': ('ravel.workflow.manuscript_production', 'consume_integrity_role'),
    'manuscript-finalize': ('ravel.workflow.manuscript_production', 'finalize'),
}


# Exact source-defined finite transports; no installed/scientific qualification.
EXTENSION_TRANSPORT = {'literature-discover': {'arguments':['request_pin'], 'returns':'authentic complete selected provider page or explicit record; raw provenance, unresolved fields and all original scout obligations; no read/verification claim'},
 'protocol-register': {'arguments': ['request_pin'], 'returns': 'Registered concern-to-experiment identities; ordinary planning and approval remain required'},
 'literature-discovered-sources': {'arguments':['product_pin','reason'], 'returns':'current secondary metadata located context and ordinary writer citation, primary-paper/read/relevance remain open'},
 'literature-acquire': {'arguments': ['request_pin'],
                    'returns': '{binding:pin3,product:pin3,source_artifact:pin3|null,status,claims}; selected public HTTPS source, complete response/failure provenance, not reading or acceptance'},
 'literature-context': {'arguments': ['request_pin', 'premise_map', 'reason'],
                     'returns': '{product:pin3,knowledge_request:pin3|null,context}; complete located forest and unresolved acquisitions, no reading/acceptance'},
 'literature-pdf': {'arguments': ['request_pin'],
                    'returns': '{binding:pin3,product:pin3,page_count,status,claims}; actual charged PDF text extractor, visual/OCR/table/equation unknowns retained'},
 'replication-prepare': {'arguments':['current_report_pin','method_id','check_contract_pin'], 'returns':'pinned complete request + prospective experiments; no dispatch or approval'},
 'replication-design': {'arguments':['request_pin','experiment_id'], 'returns':'ordinary design admission only; existing protocol/budget/approval gates remain'},
 'replication-comparison': {'arguments':['request_pin'], 'returns':'whole original/fresh result roster and actual review bindings + ordinary research-comparison study; unknowns/failures retained, no acceptance'},
 'model-proposals': {'arguments': ['request_pin', 'premise_map', 'reason'],
                     'returns': 'current campaign state from bind_knowledge, not scientific/model '
                                'novelty acceptance'},
 'routine-workflow': {'arguments': ['choice_pin'],
                      'returns': 'complete handoff with specification/goal_binding; paper-first '
                                 'also request/generation'},
 'routine-step': {'arguments': ['selection_pin'],
                  'returns': 'repair/close value or path+sha256 preparation result pin; read full '
                             'pinned document for ordinary specification; build/events require '
                             'workload'},
 'manuscript-author': {'arguments': ['request'],
                       'returns': 'complete writer binding after accounted execute_writer, '
                                  'consumed by manuscript-collect'},
 'manuscript-collect': {'arguments': ['binding'],
                        'returns': '{package,package_pin,integrity_preparation}; later package '
                                   'argument is package_pin'},
 'manuscript-build': {'arguments': ['package', 'arguments'],
                      'returns': '{specification,ordinary_plan,execution_authorized:false,scientific_acceptance:false}; '
                                 'only preparation, not final executed build binding'},
 'manuscript-review': {'arguments': ['package', 'arguments'],
                       'returns': '{manuscript,role_binding,execution_authorized:false}; '
                                  'execute/consume/finalize use nested ordinary role_binding; '
                                  'actual campaign/observed experiment/rundir required'},
 'manuscript-consume': {'arguments': ['package', 'binding'],
                        'returns': 'actual ordinary consume/journal result; binding is nested '
                                   'ordinary role_binding, not preparation envelope'},
 'manuscript-finalize': {'arguments': ['package',
                                       'bindings',
                                       'build_binding',
                                       'final_manifest',
                                       'completion_request',
                                       'rundir'],
                         'returns': 'current real independent roles/PDF/CI3/require_final '
                                    'delivery; bindings ordinary role_bindings, build_binding '
                                    'exact {rundir,receipt,result}'}}


EXTENSION_TRANSPORT.update({'manuscript-story': {'arguments': ['request_pin'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-phase': {'arguments': ['story', 'phase_id', 'prior_products', 'resolution'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-consume-phase': {'arguments': ['binding'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-resolve-sources': {'arguments': ['story', 'resolved_request'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-assemble': {'arguments': ['story', 'phase_products', 'synthesis_binding'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-revision': {'arguments': ['package', 'review_bindings', 'budget'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-literature': {'arguments': ['story', 'scout', 'literature_request'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}, 'manuscript-supplementary': {'arguments': ['revision', 'method_id', 'check_contract'], 'returns': 'Actual source-bound stage/product or ordinary preparation; no scientific acceptance or native execution'}})

EXTENSION_TRANSPORT.update({
    'manuscript-actions': {'arguments':['revision','actions'],'returns':'complete typed objection/dependency map; every objection remains unresolved'},
    'manuscript-action-meta': {'arguments':['action_plan','runtime'],'returns':'existing charged protocol meta Graph and actual apply result; incomplete effects remain held'},
    'manuscript-successor': {'arguments':['action_plan','replacement_request'],'returns':'current response-bound ordinary writer, objections remain open'},
    'manuscript-action-resolve': {'arguments':['successor','package','review_bindings'],'returns':'fresh actual independent manuscript response review; native build/CI3/whole parent remain required'}
})

# Existing preparation consumers only; native/model actions remain separate.
PREPARATION_TOOLS=('model-event-plan','model-spectrum-plan','response-recipes',
    'eft-toolchain-context','full-auxiliary-context','root-stream-context',
    'ntuple-inventory-context','sfitter-application-context','capability-routing',
    'scientific-context','physics-knowledge','finite-integrals-context','quantitative-predictive')

def _keys(value, keys):
    cycle.ce.keys(value, keys)


def _put(path, value):
    """Replay only the same known emitted bytes, never bless a reread baseline."""
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    import hashlib
    expected = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    if Path(path).exists():
        if cycle._pin(path) != expected:
            raise orchestrator.RecoveryHold('prepared decision effect exists with different bytes')
    elif orchestrator._emitted(Path(path), deepcopy(value)) != expected:
        raise ValueError('decision emission differs from intended bytes')
    if cycle._pin(path) != expected:
        raise ValueError('generated decision bytes changed before return')
    return expected


ADAPTERS = {'model','responses','command','external','anthropic','gemini','chat_completions'}
# Optional per-role model settings. The single
# runtime stays the default for every unlisted role.
ROLE_MODEL_KEYS = {'roles', 'tiers', 'qualification_records'}
TIERS = ('judgment', 'agent', 'cheap')
# Protocol decision classes each stage's choices carry (``rdj_classes`` in the protocol).
STAGE_DECISIONS = {'screen': ('screen', 'promote'), 'validate': ('selection',),
                   'acceptance': ('method_performance',)}
RDJ_LEVELS = ('R0', 'R1', 'R2', 'R3')


def runtime(value):
    if type(value) is not dict or not RUNTIME_KEYS <= set(value) or set(value) - RUNTIME_KEYS - ROLE_MODEL_KEYS:
        _keys(value, RUNTIME_KEYS)
    for name in ('model', 'reasoning_effort'): cycle._text(value[name], 200)
    if value['adapter'] not in ADAPTERS:
        raise ValueError('actual configured ordinary model adapter required')
    graph._integer(value['max_output_tokens'], 'decision tokens', 16, 32000)
    graph._integer(value['max_wall_seconds'], 'decision wall', 1, 86400)
    for field in ('roles', 'tiers'):
        rows = value.get(field, {})
        if type(rows) is not dict or len(rows) > 128:
            raise ValueError(field + ' must map role or tier ids to model settings')
        for key, entry in rows.items():
            if field == 'tiers' and key not in TIERS:
                raise ValueError('unknown model tier: ' + str(key))
            # A tier lists one model or several (distinct families for R2+ critics); the first is its default.
            listed = entry if field == 'tiers' and type(entry) is list and 0 < len(entry) <= 16 else [entry]
            for row in listed:
                if type(row) is dict and 'tier' in row:
                    raise ValueError(field + ' rows may not declare a tier: a role needs its card tier, and a '
                                     'model serves the tier the run\'s tiers map lists it under')
                if (type(row) is not dict or not {'model', 'reasoning_effort'} <= set(row)
                        or set(row) - {'model', 'reasoning_effort', 'adapter'}):
                    raise ValueError(field + ' rows need model and reasoning_effort (adapter optional)')
                for name in ('model', 'reasoning_effort'): cycle._text(row[name], 200)
                if row.get('adapter', value['adapter']) not in ADAPTERS:
                    raise ValueError('actual configured ordinary model adapter required')
    if type(value.get('qualification_records', [])) is not list:
        raise ValueError('qualification_records must be a list')
    return deepcopy(value)


def role_assignments(settings, roles):
    """The model each role dispatches on: its own row, its card tier's default row, else the single runtime.

    The tier a role needs comes from its card. The tier a model serves comes from the run's
    ``tiers`` map (the best tier that lists the model), or is judgment for the single runtime,
    the coordinator's judgment model; a role row never labels its own tier. A judgment-tier
    card on a model the map lists only under a lower tier, or does not list, is refused
    before dispatch. Qualification labels the exact (role, model, transport, effort) cell;
    an unqualified cell stays usable and labelled.
    """
    from . import role_registry, transport_registry
    r = runtime(settings)
    tiers = {t: (v if type(v) is list else [v]) for t, v in r.get('tiers', {}).items()}
    rows, missing = {}, []
    for role in roles:
        card = role_registry.load(role)
        tier = card['model']['tier']
        if role in r.get('roles', {}):
            row, source = r['roles'][role], 'role'
        elif tier in tiers:
            row, source = tiers[tier][0], 'tier'
        else:
            row, source = {k: r[k] for k in ('model', 'reasoning_effort')}, 'runtime'
        served = model_tier(r, tiers, row['model'])
        if served is None or TIERS.index(served) > TIERS.index(tier):
            missing.append('tier:' + role + ':' + tier)
        rows[role] = {'role': role, 'card_tier': tier, 'model_tier': served, 'source': source,
                      'model': row['model'], 'reasoning_effort': row['reasoning_effort'],
                      'adapter': row.get('adapter', r['adapter']),
                      'family': transport_registry.model_family(row['model']),
                      'kind': card['independence']['kind'],
                      'distinct_family_from': list(card['model']['distinct_family_from'])}
    if missing:
        raise transport_registry.TransportRefusal(
            'judgment-tier roles need judgment-tier models: ' + ', '.join(missing), missing)
    labels = role_registry.qualification_labels(
        [{'role': role, 'model_id': row['model'], 'transport': row['adapter'], 'effort': row['reasoning_effort'],
          'mode': row['kind']} for role, row in rows.items()], records=r.get('qualification_records', []))
    for label in labels:
        rows[label['role']]['qualification'] = label['qualification']['status']
    return rows


def model_tier(settings, tiers, model):
    """The best tier the run's tier map lists ``model`` under; judgment for the single runtime; else None."""
    listed = [t for t in TIERS if any(row['model'] == model for row in tiers.get(t, []))]
    if listed:
        return listed[0]
    return 'judgment' if model == settings['model'] else None


def stage_level(stage_id, protocol=None):
    """The highest RDJ class a stage's choices carry, from the protocol's ``rdj_classes``."""
    from . import research_protocol
    classes = (protocol or research_protocol.default_protocol())['rdj_classes']
    levels = [classes[name] for name in STAGE_DECISIONS.get(stage_id, ()) if name in classes]
    return max(levels, key=RDJ_LEVELS.index) if levels else 'R0'


def stage_proposers(stage_id, protocol=None):
    """Producer roles whose work a stage judges: its own producers, else those of the stage it reviews."""
    from . import research_protocol, role_registry
    stages = {row['id']: row for row in (protocol or research_protocol.default_protocol())['stages']}
    seen = set()
    while stage_id in stages and stage_id not in seen:
        seen.add(stage_id)
        found = [r for r in stages[stage_id]['roles'] if role_registry.load(r)['independence']['kind'] == 'producer']
        if found:
            return found
        stage_id = next((i for i in stages[stage_id]['required_inputs'] if i in stages), None)
    return []


def dispatch_check(stage_id, assignments, protocol=None, *, models=None, receipts=None):
    """Plan separate seats; credit only observed distinct actors, sessions and packets.

    A requested model identifies no session. Pre-dispatch records therefore mark
    separation pending; completion must supply authenticated role receipts. Model
    family is a descriptive label, including when the observed family is unknown.
    """
    from . import transport_registry
    level = stage_level(stage_id, protocol)
    models = {role: row.get('model') for role, row in assignments.items()} if models is None else models

    def label(role, peers):
        # The one descriptive family label; it never refuses and never credits.
        return transport_registry.check_distinct_families(
            {'id': role, 'model': {'distinct_family_from': list(peers)}},
            {r: models.get(r) for r in (role, *peers)})
    record = {}
    for role in assignments:
        peers = sorted(set(assignments) - {role})
        relations = {peer: label(role, [peer]) for peer in peers}
        relation = label(role, peers) if peers else 'not_required'
        record[role] = {'level': level, 'distinct_from': peers, 'family_check': relation,
                        'family_relations': relations,
                        'family_label': ('pending separation, ' if receipts is None else 'separate session, ')
                                        + relation + ' model family',
                        'session_check': 'pending' if receipts is None else 'distinct'}
    if receipts is not None:
        if set(receipts) != set(assignments):
            raise ValueError('every research seat requires its current role receipt')
        identities = {}
        for role, receipt in receipts.items():
            transport = receipt.get('transport') or {}
            actor = transport.get('actor_id')
            sessions = _session_identities(receipt)
            packet = receipt.get('context_manifest_sha256')
            if (not actor or not sessions or not packet or not receipt.get('context_transport_separated')):
                raise transport_registry.TransportRefusal('research seat lacks observed actor, session or packet',
                                                          ['session_independence:' + role])
            for prior, identity in identities.items():
                if actor == identity[0] or sessions & identity[1] or packet == identity[2]:
                    raise transport_registry.TransportRefusal(
                        'research roles require distinct actors, sessions and packets: ' + role + ', ' + prior,
                        ['session_independence:' + role + ':' + prior])
            identities[role] = (actor, sessions, packet)
    return record


def _session_identities(receipt):
    """Every session identity one role receipt observed; any one shared with another seat refuses.

    The transport's reported CLI session, session and invocation, the receipt's recomputed
    CLI session and a launcher-reported CLI session are compared together, so a seat cannot
    present a fresh invocation over another seat's actual session.
    """
    transport = receipt.get('transport') or {}
    launcher = ((transport.get('session_receipt') or {}).get('launcher_receipt') or {}).get('cli_reported') or {}
    session = receipt.get('session') or {}
    return {str(value) for value in (transport.get('cli_session_id'), transport.get('session_id'),
                                     transport.get('invocation_id'), session.get('cli_session_id'),
                                     launcher.get('session_id')) if value}


def observed_models(graph_root):
    """The model each delivered role of a stage Graph reports it ran on (role id to model id)."""
    from . import agent_graph
    found = {}
    for node_id, node in agent_graph.status(graph_root)['nodes'].items():
        if node.get('result'):
            transport = agent_graph._result(Path(graph_root), node['result'])['result'].get('transport') or {}
            if transport.get('observed_model'):
                found[node_id] = transport['observed_model']
    return found


def bound_stage_receipt(root, role, *, stage_id=None, state=None):
    """Recompute an earlier role's receipt from its campaign-bound, charged Graph.

    A saved receipt or model assignment is not an observation. Both the immutable
    campaign completion and the current Graph must still bind the same receipt.
    ``state`` is a campaign state the caller has just authenticated with ``_load`` and
    re-checks as unchanged after its observation; otherwise it is loaded here.
    """
    from . import research_protocol as protocol
    if root is None:
        raise ValueError('earlier stage model evidence requires its bound campaign')
    root = Path(root)
    if state is None:
        _, state = cycle._load(root)
    record = state['methodology']
    if cycle.state_io.read_json(protocol._method_path(root)) != record:
        raise ValueError('research methodology differs from its campaign journal')
    # A stage whose roles reviewed a declared not_applicable artifact also ran
    # them and retains their receipts; a stage that never dispatched has none.
    candidates = [r for r in record['stages'] if role in r['roles']
                  and r['status'] in {'done', 'not_applicable'} and r.get('worker_receipts')
                  and (stage_id is None or r['id'] == stage_id)]
    if len(candidates) > 1:
        raise ValueError('earlier role requires its exact stage identity: ' + role)
    row = candidates[0] if candidates else None
    if row is None:
        raise ValueError('earlier producer has no completed bound stage: ' + role)
    prepared = row['active_preparation']
    events = [e for e in state['events'] if e['kind'] == 'research_methodology_stage_completed'
              and e['stage'] == row['id'] and e['artifact'] == row['artifact']]
    if len(events) != 1:
        raise ValueError('earlier stage lacks its unique campaign completion')
    graph_root = Path(events[0]['graph_root'])
    spec = protocol._method_json(prepared['specification'], root)
    inherited = state['contract'].get('goal_binding')
    if inherited is not None:
        spec = {**spec, 'goal_binding': deepcopy(inherited)}
    cycle.validate_graph_reservation(state, graph_root, spec)
    node = next(n for n in spec['nodes'] if n['id'] == role)
    receipt = research_controller.role_receipt(graph_root, role,
        expected_subject_sha256=prepared['subject']['sha256'],
        expected_packet_sha256=node['packet']['manifest_sha256'],
        require_exact_subject=True, allowed_roles={node['role']})
    if receipt != protocol._method_json(row['worker_receipts'][role], root):
        raise ValueError('earlier producer receipt differs from its current bound worker: ' + role)
    return receipt


def stage_family_check(root, stage_id, models, protocol=None, *, receipts=None):
    """Keep observed producer custody; family never determines independent credit."""
    from . import research_protocol, role_registry
    definition = protocol or research_protocol.default_protocol()
    stage = next(r for r in definition['stages'] if r['id'] == stage_id)
    roles = set(stage['roles'])
    for role in stage['roles']:
        roles.update(role_registry.load(role)['model']['distinct_family_from'])
    if RDJ_LEVELS.index(stage_level(stage_id, definition)) >= 2:
        roles.update(stage_proposers(stage_id, definition))
    assigned, observed = {}, dict(models)
    actual = None if receipts is None else dict(receipts)
    for role in sorted(roles):
        card = role_registry.load(role)
        if role not in stage['roles']:
            prior = bound_stage_receipt(root, role)
            observed[role] = prior['transport'].get('observed_model')
            if actual is not None:
                actual[role] = prior
        assigned[role] = {'kind': card['independence']['kind']}
    checks = dispatch_check(stage_id, assigned, definition, models=observed, receipts=actual)
    return {role: checks[role] for role in stage['roles']}


def receipt_family_check(stage_id, graph_root, settings, protocol=None, *, root=None):
    """Credit separation from current receipts, never from requested model settings."""
    from . import agent_graph, research_protocol
    if root is None:
        raise ValueError('current campaign required for stage receipt verification')
    status = research_protocol.methodology_status(root)
    row = next(r for r in status['record']['stages'] if r['id'] == stage_id)
    prepared = row['active_preparation']
    spec = research_protocol._method_json(prepared['specification'], root)
    receipts = {node['id']: research_controller.role_receipt(graph_root, node['id'],
        expected_subject_sha256=prepared['subject']['sha256'],
        expected_packet_sha256=node['packet']['manifest_sha256'],
        require_exact_subject=True, allowed_roles={node['role']}) for node in spec['nodes']}
    return stage_family_check(root, stage_id,
        {role: receipt['transport'].get('observed_model') for role, receipt in receipts.items()},
        protocol, receipts=receipts)


def catalogue(modes):
    """Actual public source contracts, never inferred installed capabilities."""
    from . import capability_routing
    full = capability_routing.catalogue()
    rows = {r['mode']: r for r in full['operations']}
    if modes is None:modes=[m for m,r in rows.items() if r['status']=='source_present_not_admitted']
    if type(modes) is not list or not 1 <= len(modes) <= len(rows) or len(set(modes)) != len(modes) or set(modes) - rows.keys():
        raise ValueError('explicit distinct current candidate ordinary modes required')
    selected = [deepcopy(rows[m]) for m in modes]
    for row in selected:
        if row['status'] != 'source_present_not_admitted':
            raise ValueError('selected operation has no connected source dispatcher')
    package = Path(__file__).parent
    extensions = []
    for action, (module, function) in EXTENSIONS.items():
        path = package / (module.rsplit('.', 1)[1] + '.py')
        if path.is_file():
            pin, raw = capability_routing._file(path)
            _, names, _ = _syntax_facts(raw, filename=str(path))
            present = function in names
        else:
            present = False
        source = cycle._pin(path) if present else None
        if present and source != {**pin, 'size': len(raw)}:
            raise ValueError('catalogue source changed after syntax facts: ' + str(path))
        extensions.append({'action': action, 'module': module, 'function': function,
            'status': 'connected_public_source' if present else 'source_not_yet_composed',
            'source': source,
            'transport': deepcopy(EXTENSION_TRANSPORT[action])})
    host=package/'agent_host.py'
    host_pin, raw = capability_routing._file(host)
    _, _, constants = _syntax_facts(raw, filename=str(host))
    preparation=[]
    for name in PREPARATION_TOOLS:
        if name in constants:
            source = cycle._pin(host)
            if source != {**host_pin, 'size': len(raw)}:
                raise ValueError('catalogue source changed after syntax facts: ' + str(host))
            preparation.append({'action':name,'source':source})
    return {'operations': selected, 'extensions': extensions, 'preparation_tools':preparation,
        'scope': 'Source-backed choices only. Availability, registration and preparation are not native or scientific qualification.'}


def request(request_pin):
    from . import intake
    value = orchestrator._read(request_pin)
    _keys(value, {'schema_version','kind','parent_contract','handoff','campaign','runtime','evidence',
        'candidate_modes','review','max_decisions','knowledge','context_request','planning_context','direct_mapping',
        *({'research_regime'} if 'research_regime' in value else set()),
        *({'bounded_step'} if 'bounded_step' in value else set())})
    if value['schema_version'] != 1 or type(value['schema_version']) is not int or value['kind'] != 'open-research-request':
        raise ValueError('open-research-request/v1 required')
    base = Path(value['parent_contract']['path']).parent
    if intake.execution_handoff(value['parent_contract'], base_dir=base) != value['handoff']:
        raise ValueError('complete original intake/handoff changed')
    runtime(value['runtime']); catalogue(value['candidate_modes'])
    if 'bounded_step' in value:
        from .bounded_research import validate
        validate(value)
    from .research_protocol import default_protocol
    if value.get('research_regime', 'open_exploratory') not in default_protocol()['regimes']:
        raise ValueError('known declared research regime required')
    graph._integer(value['max_decisions'], 'research decisions', 1, 64)
    _keys(value['review'], {'arguments', 'allow_control'})
    if type(value['review']['arguments']) is not dict or type(value['review']['allow_control']) is not bool:
        raise ValueError('explicit scientific review configuration required')
    if type(value['evidence']) is not list or len(value['evidence']) > 32:
        raise ValueError('bounded explicit supplied evidence population required')
    names = set()
    for row in value['evidence']:
        _keys(row, {'pin','purpose'})
        if row['purpose'] not in {'model_context','execution_dependency','withheld_evaluation'}:
            raise ValueError('explicit source vs withheld vs execution-only input purpose required')
        path, actual = cycle._check_pin(row['pin'], base)
        if str(path) in names or actual != row['pin']:
            raise ValueError('canonical unique complete source pins required')
        names.add(str(path))
    if value['context_request'] is not None:
        cycle._check_pin(value['context_request'], base)
        from .task_completion import binding_projection
        projection=binding_projection(value['handoff']['goal_binding'],base_dir=base)
        cycle._context_mapping({'parent_task':projection,'base_dir':str(base)},
            orchestrator._read(value['context_request']),value['direct_mapping'])
    elif value['direct_mapping'] is not None:
        raise ValueError('direct method mapping requires its complete context declaration')
    cycle._check_pin(value['planning_context'], base)
    if value['knowledge'] is not None: cycle._knowledge_packet(value['knowledge'], base)
    return value


def _input_sources(value, selected):
    pins = [value['parent_contract'], cycle._pin(__file__), cycle._pin(orchestrator.__file__),
        cycle._pin(cycle.scientific_context.__file__), cycle._pin(science.__file__)]
    data = Path(__file__).parents[1] / 'data/research'
    pins.extend(cycle._pin(data/name) for name in ('protocol-default.json', 'instructions.json'))
    # Complete operation/source inventory is custody, not automatic body read.
    # Actual selected bodies enter only through explicit source-request turns.
    pins += [r['pin'] for r in value['evidence'] if r['purpose'] == 'model_context']
    return list({p['path']: deepcopy(p) for p in pins}.values())


def prior_effect_documents(core, inputs):
    """Resolve complete effects only from the exact normal inputs presented.

    Historical Graph cores contained the complete documents inline. Their
    content remains usable, but new contexts carry references to avoid reading
    the same document both inside the core and as a separate normal input.
    """
    supplied = {(p['path'], p['sha256']) for p in inputs}
    documents = []
    for row in core.get('prior_operation_effects', []):
        if type(row) is dict and set(row) == {'effect'}:
            pin = row['effect']
            _keys(pin, {'path', 'sha256', 'size'})
            if (pin['path'], pin['sha256']) not in supplied:
                raise ValueError('complete prior effect must be an actually supplied normal input')
            document = cycle._read(pin, Path(pin['path']).parent)
        else:
            # Compatibility is confined to the original complete public shape;
            # arbitrary partial records cannot masquerade as effect documents.
            document = deepcopy(row)
        _keys(document, {'action', 'arguments', 'origin', 'actual_effect',
                         'parent_task_accepted', 'scientific_authority_from_checkpoint'})
        documents.append(document)
    return documents


def _validate_prior_effects(root, core, inputs):
    _, state = cycle._load(root)
    documents = prior_effect_documents(core, inputs)
    supplied = {(p['path'], p['sha256']) for p in inputs}
    for row, document in zip(core.get('prior_operation_effects', []), documents):
        committed = cycle._coordinator_effect(state, document['origin'])
        if (committed is None or committed['document'] != document
                or (committed['pin']['path'], committed['pin']['sha256']) not in supplied
                or (set(row) == {'effect'} and row['effect'] != committed['pin'])):
            raise ValueError('prior effect must retain its original campaign commitment and normal input')
    return documents


def compact_decision_context(core):
    """Present identical large subtrees once, with checked local JSON references."""
    if 'context_aliases' in core:
        raise ValueError('research context metadata is reserved at the document root')
    seen, references = {}, []
    def walk(value, path):
        if isinstance(value, (dict, list)):
            raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
            if len(raw) >= 1024:
                digest = cycle.ce.digest(value)
                if digest in seen:
                    references.append(path)
                    return {'$research_context_ref': seen[digest], 'sha256': digest}
                seen[digest] = path
        if isinstance(value, dict):
            return {key: walk(item, path+'/'+key.replace('~', '~0').replace('/', '~1'))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, path+'/'+str(index)) for index, item in enumerate(value)]
        return value
    result = walk(core, '#')
    result['context_aliases'] = {'format': 'local-exact-json-v1', 'expanded_sha256': cycle.ce.digest(core),
        'references': references,
        'presentation': 'Each $research_context_ref names the complete identical subtree at that local JSON pointer. '
            'Read that full body; all failures, original obligations and feedback remain present. '
            'The sha256 verifies the expanded subtree. References grant no authority.'}
    if expand_decision_context(result) != core:
        raise ValueError('context aliases cannot replace original material')
    return result


def expand_decision_context(core):
    """Reconstruct exact historical semantics before any original authority check."""
    if 'context_aliases' not in core:
        return core
    metadata = core['context_aliases']
    if not isinstance(metadata, dict) or metadata.get('format') != 'local-exact-json-v1':
        raise ValueError('unknown research context reference format')
    references = metadata.get('references')
    if (not isinstance(references, list) or any(not isinstance(p, str) for p in references)
            or len(set(references)) != len(references)):
        raise ValueError('invalid research context reference census')
    references, used = set(references), set()
    expanded_bytes = expanded_nodes = 0
    def walk(value, active, path, depth=0):
        nonlocal expanded_bytes, expanded_nodes
        expanded_nodes += 1
        if depth > 128 or expanded_nodes > 100000:
            raise ValueError('research context reference expansion exceeds its finite structural bound')
        if path in references:
            used.add(path)
            if not isinstance(value, dict):
                raise ValueError('invalid research context reference')
            if set(value) != {'$research_context_ref', 'sha256'}:
                raise ValueError('invalid research context reference')
            pointer = value['$research_context_ref']
            if not isinstance(pointer, str) or not pointer.startswith('#/') or pointer in active:
                raise ValueError('cyclic or invalid research context reference')
            target = core
            try:
                for part in pointer[2:].split('/'):
                    key = part.replace('~1', '/').replace('~0', '~')
                    target = target[int(key)] if isinstance(target, list) else target[key]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError('missing research context reference') from exc
            result = walk(target, active | {pointer}, pointer, depth+1)
            if cycle.ce.digest(result) != value['sha256']:
                raise ValueError('research context reference digest differs')
            return result
        if isinstance(value, dict):
            expanded_bytes += 2 + max(0, len(value)-1) + sum(
                len(json.dumps(key).encode())+1 for key in value)
        elif isinstance(value, list):
            expanded_bytes += 2 + max(0, len(value)-1)
        else:
            expanded_bytes += len(json.dumps(value, allow_nan=False).encode())
        if expanded_bytes > 8 * MAX_CORE_BYTES:
            raise ValueError('research context reference expansion exceeds its finite bound')
        if isinstance(value, dict):
            return {key: walk(item, active, path+'/'+key.replace('~', '~0').replace('/', '~1'), depth+1)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, active, path+'/'+str(index), depth+1) for index, item in enumerate(value)]
        return value
    result = walk({key: value for key, value in core.items() if key != 'context_aliases'}, set(), '#')
    if used != references or cycle.ce.digest(result) != metadata.get('expanded_sha256'):
        raise ValueError('expanded research context differs from its complete original digest')
    return result


def _summarized_instrumentation(core, out):
    """Present operational instrumentation by its established summary; retain the complete record.

    Used only when the complete decision material still exceeds its bound after lossless
    aliasing. The full typed metrics stay byte-pinned beside the core. Scientific
    obligations, evidence, failures and feedback remain complete, as in the progress report.
    """
    import hashlib
    from . import research_outcome_metrics
    metrics = core['progress']['outcome_metrics']
    raw = (json.dumps(metrics, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    pin = {'path': str(Path(out) / 'outcome-metrics.json'), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    progress = {key: value for key, value in core['progress'].items() if key != 'outcome_metrics'}
    # Summarize the exact retained bytes, so the summary is reproducible from the record.
    progress['outcome_metrics_summary'] = research_outcome_metrics.markdown(json.loads(raw))
    progress['outcome_metrics_record'] = pin
    progress['outcome_metrics_presentation'] = (
        'The complete decision material exceeded its 1.5 MB bound after lossless aliasing, so operational '
        'instrumentation is shown by its established summary. Its complete typed record is retained at the '
        'pinned path for audit and is not presented here. Scientific obligations, evidence, failures and '
        'feedback remain complete.')
    return {**core, 'progress': progress}, (pin, metrics)


def _material_census(core, pins, *, limit=6):
    """Name the largest decision sections and inputs, so an operator can page them; nothing is cut."""
    def size(value):
        return len(json.dumps(value, sort_keys=True, allow_nan=False).encode())
    sections = sorted(((size(value), key) for key, value in core.items()), reverse=True)[:limit]
    parts = ['largest_core_sections=' + ','.join(f'{key}:{n}' for n, key in sections)]
    for _, key in sections[:2]:
        value = core[key]
        rows = (value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ())
        inner = sorted(((size(item), str(name)) for name, item in rows), reverse=True)[:limit]
        if inner:
            parts.append(key + '=' + ','.join(f'{name}:{n}' for n, name in inner))
    largest = sorted(pins, key=lambda p: p['size'], reverse=True)[:limit]
    parts.append('largest_normal_inputs=' + ','.join(f"{Path(p['path']).name}:{p['size']}" for p in largest))
    return '; '.join(parts)


def capability_view(value):
    """The capability catalogue and the capabilities the campaign's parent contract and reading call for."""
    from ravel.controller import capabilities
    from . import intake
    base = Path(value['parent_contract']['path']).parent
    contract = cycle._read(value['parent_contract'], base)
    try:
        reading = intake.read_reading(base, contract['prompt'])
    except (OSError, ValueError, KeyError, TypeError):
        reading = None  # facts the reading would supply stay absent; nothing is inferred
    return capabilities.view(contract, reading)


def prepare_decision(root, value, out, *, phase, stream=None, method_feedback=(), effects=(), source_origins=()):
    """Complete current obligations/evidence/search state; no peer idea broadcast."""
    _, state = cycle._load(root)
    selected = catalogue(value['candidate_modes'])
    if stream is not None and stream not in {'citation_led','speculative'}:
        raise ValueError('known isolated idea stream required')
    # Actual status and progress retain all failed, open and historically
    # accepted rows. They do not claim parent or scientific acceptance.
    progress = cycle.progress_synthesis(root, base_dir=state['base_dir'], render_text=False)
    parents = []
    for e in state['experiments']:
        if e['observation'] is not None:
            cycle._current_evidence(state, e, accepted=e['adjudication'] is not None and e['adjudication']['view']['state'] == 'accepted')
        row = {'id':e['id'], 'question':e['question'], 'parent':e['parent'], 'predictions':e['predictions'],
            'observation':deepcopy(e['observation']), 'adjudication':deepcopy(e['adjudication']),
            'quantitative_binding':deepcopy(e.get('quantitative_binding')), 'quantitative_selection':deepcopy(e.get('quantitative_selection')),
            'diagnostic_feedback':deepcopy(e.get('diagnostic_feedback'))}
        if e['adjudication'] is not None or e.get('diagnostic_feedback') is not None:
            feedback = cycle.feedback_packet(root, e['id'])
            row['feedback'] = orchestrator._read(feedback)
        parents.append(row)
    pins = _input_sources(value, selected)
    for origin in source_origins:pins.extend(requested_sources(value,origin))
    pins=list({p['path']:p for p in pins}.values())
    core = {'kind':'original-question-research-decision', 'phase':phase, 'stream':stream,
        'question':state['contract']['question'], 'original_task':value['handoff'],
        'scientific_context':deepcopy(state['context']), 'planning_only': 'scientific_context_declaration' not in state and value['context_request'] is None,
        'method_mapping':deepcopy(state.get('scientific_context_declaration',{}).get('mapping',value['direct_mapping'])),
        'premises':deepcopy(state['premises']), 'hypotheses':[] if stream is not None else deepcopy(state['hypotheses']),
        'experiments':parents, 'progress':progress, 'usage':cycle._usage(state), 'budget':state['contract']['budget'],
        'timing':deepcopy(state['timing']), 'catalogue':selected, 'complete_input_inventory':deepcopy(value['evidence']),
        'source_read_credit':'Only normal supplied model inputs contain source text. Inventory/checkpoint hashes do not establish reading. '
            'Request selected full bodies with source-context arguments modes:[mode,...] and optional extensions:[action,...].',
        'peer_ideas_presented':False if stream is not None else None,
        'scientific_acceptance':False, 'parent_task_accepted':False, 'execution_authorized':False}
    if state['contract'].get('research_protocol_required'):
        from . import research_protocol
        core['research_protocol'] = research_protocol.methodology_status(root)
        core['world_digest'] = research_protocol.world_digest(root)
    if 'bounded_step' in value:
        from .bounded_research import validate
        core['bounded_step'] = validate(value)
        core['bounded_qualification'] = (
            'One progress decision only. All unfinished scientific protocol duties remain open; '
            'no experiment, independent scientific assessment or acceptance is authorized.')
    if method_feedback:
        if phase!='declare-context':raise ValueError('method feedback belongs only to prospective repair design')
        core['actual_method_send_backs']=[]
        for origin in method_feedback:
            if cycle._graph_result(origin['root'],origin['node_id'])!=origin:
                raise ValueError('prospective method feedback changed')
            core['actual_method_send_backs'].append(origin)
    if value['knowledge'] is not None:
        packet, dependencies = cycle._knowledge_packet(value['knowledge'], state['base_dir'])
        core['knowledge'] = packet
        # The retrieved full dependency/conflict packet is presented; complete
        # raw library/source files remain authenticated custody, not read credit.
        core['knowledge_source_inventory'] = dependencies
    core['prior_operation_effects']=[]
    core['prior_operation_effects_presentation'] = (
        'Chronological effect references; each complete original effect document is supplied once '
        'as a normal input at its exact effect path and SHA256. Read that full input, including '
        'all failures and feedback. References alone establish no source reading or authority.')
    for row in effects:
        actual=cycle._graph_result(row['origin']['root'],row['origin']['node_id'])
        if actual!=row['origin']:raise ValueError('previous model effect origin changed')
        committed=cycle._coordinator_effect(state,actual)
        if committed is None or committed['pin']!=row['effect']:
            raise ValueError('checkpoint effect was not committed by the original campaign')
        effect=committed['document']
        core['prior_operation_effects'].append({'effect':deepcopy(row['effect'])})
        pins.append(row['effect'])
        produced=effect.get('actual_effect',{})
        for pin in produced.get('materialized_inputs',[]):
            cycle._check_pin(pin,state['base_dir'])
        # Complete prepared inventories stay in the core. Large populations
        # are read only when a subsequent actual source-context choice selects
        # them; inventory identity alone is never content presentation.
        for pin in produced.get('next_context_inputs',produced.get('materialized_inputs',[])):
            cycle._check_pin(pin,state['base_dir']);pins.append(pin)
    # Every deciding seat receives what RAVEL can do: the generated capability catalogue, supplied once as a
    # normal pinned input, and inline what the campaign's own intake facts call for (they compose).
    shown = capability_view(value)
    catalogue_pin = _put(Path(out) / 'capability-catalogue.json', shown['catalogue'])
    pins.append(catalogue_pin)
    # The core names the input by its bytes, never by a path of this preparation's directory.
    core['capabilities'] = {'catalogue': {'sha256': catalogue_pin['sha256'], 'size': catalogue_pin['size'],
                                          'catalogue_sha256': shown['catalogue']['sha256']},
                            'applicable': shown['applicable'],
                            'presentation': 'The complete catalogue is the normal input with this exact SHA256; '
                                            'applicable lists what the request facts call for.'}
    from . import research_controller
    governed = research_controller.loop_budget_view()
    if governed is not None:
        # Under the controller the deciding seat sees the approved loop budget, what is committed, the
        # projected cost of a further cycle and child, and the stop rule its decision reason must answer.
        core['loop_budget'] = governed
    pins=list({p['path']:p for p in pins}.values())
    def material(document):
        raw = json.dumps(document, sort_keys=True, allow_nan=False).encode()
        return raw, len(raw) + sum(p['size'] for p in pins)
    raw, total = material(core)
    retained = None
    if total > MAX_CORE_BYTES:
        complete = core
        core = compact_decision_context(complete)
        raw, total = material(core)
        if total > MAX_CORE_BYTES and 'outcome_metrics' in complete.get('progress', {}):
            core, retained = _summarized_instrumentation(complete, Path(out))
            raw, total = material(core)
            if total > MAX_CORE_BYTES:
                core = compact_decision_context(core)
                raw, total = material(core)
    if total > MAX_CORE_BYTES:
        raise ValueError('complete decision material exceeds1.5MB; prepare explicit bounded original-source pages, never truncate the task or feedback'
            f'; core_bytes={len(raw)}; normal_input_bytes={sum(p["size"] for p in pins)}; ' + _material_census(core, pins))
    if retained is not None:
        if _put(Path(retained[0]['path']), retained[1]) != retained[0]:
            raise ValueError('retained instrumentation record differs from its presented pin')
    core_pin = _put(Path(out) / 'scientific-core.json', core)
    pins = [core_pin, *pins]
    if len(pins) > 128:
        raise ValueError('complete decision context exceeds ordinary128 inputs')
    for row in [*selected['operations'], *selected['extensions']]:
        if row['source'] is not None and cycle._pin(row['source']['path'])['sha256']!=row['source']['sha256']:
            raise ValueError('complete operation source census changed during preparation')
    if cycle._load(root)[1]['sha256'] != state['sha256']:
        raise ValueError('research state changed while preparing full decision context')
    return {'core':core_pin, 'inputs':pins, 'phase':phase, 'stream':stream}


_SIGNATURE = {k: {'type': 'string', 'minLength': 1, 'maxLength': 2000} for k in ('observable', 'scope', 'prediction')}
# The typed hypothesis register declaration a research-protocol campaign adopts (research_cycle._register_hypothesis).
# Strict host schemas need every property, so ``what_is_new`` names each signature field or null.
REGISTER_FIELDS = {
    'operator': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'identity_signature': {'type': 'object', 'properties': _SIGNATURE, 'required': list(_SIGNATURE),
                           'additionalProperties': False},
    'kill_condition': {'type': 'object', 'properties': {'comparison': {'type': 'string', 'const': 'differs'},
                       'observable': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
                       'required': ['comparison', 'observable'], 'additionalProperties': False},
    'reopening_trigger': {'type': 'object', 'properties': {
        'kind': {'type': 'string', 'enum': ['new_evidence', 'changed_input', 'increased_budget']},
        'field': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'op': {'type': 'string', 'enum': ['eq', 'ne', 'gt', 'ge']},
        'value': {'type': ['string', 'number', 'boolean', 'null']}},
        'required': ['kind', 'field', 'op', 'value'], 'additionalProperties': False},
    'what_is_new': {'type': ['object', 'null'], 'properties': {k: {'type': ['string', 'null'], 'maxLength': 2000}
                    for k in _SIGNATURE}, 'required': list(_SIGNATURE), 'additionalProperties': False},
}


def decision_spec(root, prepared, settings, *, graph_id):
    r = runtime(settings)
    phase = prepared['phase']
    if phase == 'declare-context':
        fields = {'kind':{'enum':['research-context-declaration','research-source-request'],'type':'string'},
            'context_json':{'type':'string','minLength':2,'maxLength':200000},
            'obligation_mapping_json':{'type':'string','minLength':2,'maxLength':400000},
            'modes':{'type':'array','maxItems':32,'items':{'type':'string','minLength':1}},
            'reason':{'type':'string','minLength':1,'maxLength':16000}}
        instructions = (instruction('declare_context'))
    elif phase == 'hypotheses':
        text={'type':'string','minLength':1,'maxLength':8000}
        names={'type':'array','maxItems':64,'items':{'type':'string','minLength':1,'maxLength':64}}
        pin_fields={'path':{'type':'string','minLength':1,'maxLength':4096},
            'sha256':{'type':'string','minLength':64,'maxLength':64},'size':{'type':'integer','minimum':0,'maximum':64*1024*1024}}
        row={'id':{'type':'string','minLength':1,'maxLength':64},'statement':text,
            'stream':{'type':'string','const':prepared['stream']},'premise_ids':names,
            'source_basis':{'type':'array','maxItems':16,'items':{'type':'object','properties':pin_fields,
                'required':list(pin_fields),'additionalProperties':False}},'parents':names,
            **REGISTER_FIELDS}
        fields = {'hypotheses':{'type':'array','minItems':1,'maxItems':16,'items':
            {'type':'object','properties':row,'required':list(row),'additionalProperties':False}}}
        instructions = (instruction('hypothesis_proposal') + prepared['stream'] + instruction('hypothesis_evidence'))
    elif phase == 'context-assessment':
        subject = prepared['subject_sha256']
        fields = {'kind':{'type':'string','const':'context-method-assessment'},
            'subject_sha256':{'type':'string','const':subject},
            'verdict':{'type':'string','enum':['adequate_for_prospective_tests','send_back']},
            'findings':{'type':'array','maxItems':128,'items':{'type':'string','minLength':1}},
            'summary':{'type':'string','minLength':1,'maxLength':16000}}
        instructions = (instruction('context_assessment'))
    else:
        core = expand_decision_context(orchestrator._read(prepared['core']))
        actions = ['protocol-stage','experiment','source-context','preparation-tool','predictive-selection','run-selected','review','diagnose','revise-premise','propose','synthesize','progress',
                   *[r['action'] for r in core['catalogue']['extensions'] if r['status']=='connected_public_source']]
        if 'bounded_step' in core:
            actions = ['progress']
        fields = {'kind':{'type':'string','const':'research-action'}, 'action':{'type':'string','enum':actions},
            'reason':{'type':'string','minLength':1,'maxLength':16000},
            'arguments_json':{'type':'string','minLength':2,'maxLength':400000}}
        instructions = (instruction('next_action'))
        if 'loop_budget' in core:
            from ravel.controller.routes.research import loop_budget
            fields['information_gain'] = loop_budget.assessment_schema()
            instructions += '\n' + loop_budget.STOP_RULE
    schema = {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
    spec = {'schema_version':1,'graph_id':graph_id,
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':r['max_output_tokens'],
            'max_wall_seconds':r['max_wall_seconds'],'max_reworks':0},
        'nodes':[{'id':'decision','kind':'model','role':'proposer' if phase=='hypotheses' else 'designer',
            'depends_on':[],'inputs':[{'id':'scientific-core' if i==0 else 'source-'+str(i),'path':p['path'],'sha256':p['sha256']} for i,p in enumerate(prepared['inputs'])],
            'packet':None,'action':r['adapter'],'max_attempts':1,
            'parameters':{'model':r['model'],'reasoning_effort':r['reasoning_effort'],
                'max_output_tokens':r['max_output_tokens'],'output_schema':schema,'instructions':instructions}}]}
    if phase=='context-assessment':
        spec['nodes'][0].update(role=prepared['role'],
            # The exact subject already belongs to the source-bound role packet.
            # Blind reviewers receive that packet only, never extra raw inputs.
            inputs=[],
            packet=prepared['packet'])
    graph.validate(spec)
    return spec


def prepare_assessment(root, value, out, *, role):
    """Fresh blind packets through the existing complete index/Host consumer."""
    if role not in {'critic','verifier'}: raise ValueError('separate methodological roles required')
    from . import review_context
    prepared=prepare_decision(root,value,Path(out)/'source',phase='context-assessment')
    _, state=cycle._load(root)
    subject=state.get('scientific_context_declaration',{}).get('request',value['context_request'])
    if subject is None: raise ValueError('actual declared scientific context required')
    rows=[*prepared['inputs'],subject]
    rows=list({p['path']:p for p in rows}.values())
    packet=Path(out)/'packet'
    entries=[]
    for i,pin in enumerate(rows):
        path,_=cycle._check_pin(pin,state['base_dir'])
        from .research_followup import _bytes
        _, raw=_bytes(pin,state['base_dir'])
        # Complete content, not inventory-only source credit. The original
        # declaration is duplicated intentionally for direct subject reading.
        content={'source':pin,'text':raw.decode('utf-8')}
        identity='public_case' if i==0 else 'source-'+str(i)
        projected=_put(packet/'artifacts'/(identity+'.json'),content)
        entries.append({'id':identity,'path':'artifacts/'+identity+'.json',
            'source_path':str(path),'source_sha256':pin['sha256'],'sha256':projected['sha256'],
            'projection':'complete supplied UTF8 source in JSON text wrapper; no authority'})
    manifest={'schema_version':1,'role':role,'run_id':str(root),'cycle_id':subject['sha256'],
        'source_event_sha256':subject['sha256'],'artifacts':entries,'omissions':[], 'findings':[],
        'reviews':[],'allowed_claim_scopes':{},'required_checks':[],
        'access_limitation':'Fresh separated prospective context assessment; no peer model output and no scientific vote. Filesystem/model independence is not proven.'}
    manifest['sha256']=graph.digest(manifest)
    _put(packet/'manifest.json',manifest)
    review_context.verify_packet(packet,expected_manifest_sha256=manifest['sha256'])
    for pin in rows: cycle._check_pin(pin,state['base_dir'])
    return {**prepared,'packet':{'path':str(packet),'manifest_sha256':manifest['sha256']},
        'role':role,'subject':deepcopy(subject),'subject_sha256':subject['sha256']}



def assessment_receipt(origin, prepared, *, allow_control):
    from . import review_context
    if cycle._graph_result(origin['root'],origin['node_id'])!=origin:
        raise ValueError('assessment result changed')
    receipt=research_controller.role_receipt(origin['root'],origin['node_id'],
        expected_subject_sha256=prepared['subject_sha256'],
        expected_packet_sha256=prepared['packet']['manifest_sha256'],
        require_exact_subject=False,allowed_roles={prepared['role']})
    explicit=receipt['isolation'].get('evidence_presentation')
    manifest=review_context.verify_packet(prepared['packet']['path'],
        expected_manifest_sha256=prepared['packet']['manifest_sha256'])
    required={e['sha256'] for e in manifest['artifacts']}
    if (type(explicit) is not dict or explicit.get('manifest_sha256')!=prepared['packet']['manifest_sha256']
            or not required.issubset(set(explicit.get('presented_subject_sha256s',[])))
            or not fresh_delivery(receipt, extra=('control_only',) if allow_control else ())):
        raise ValueError('actual complete method core/source presentation and fresh separated role transport required')
    return receipt


def actual(root, graph_root, prepared, spec, *, host, settings):
    # Framework state is routing data. Reconstruct the actual public request
    # from source-bound inputs and the original configured runtime before calls.
    if spec != decision_spec(root,prepared,settings,graph_id=spec['graph_id']):
        raise ValueError('checkpoint changed the ordinary model/runtime contract')
    core=expand_decision_context(orchestrator._read(prepared['core']))
    for row in [*core['catalogue']['operations'], *core['catalogue']['extensions']]:
        if row['source'] is not None and cycle._pin(row['source']['path'])['sha256']!=row['source']['sha256']:
            raise ValueError('operation source changed before ordinary decision')
    if core.get('phase')!=prepared['phase'] or core.get('stream')!=prepared['stream']:
        raise ValueError('prepared decision phase or stream changed')
    _,current=cycle._load(root)
    if core['question']!=current['contract']['question'] or core['original_task']['goal_binding']!=current['contract']['goal_binding']:
        raise ValueError('decision context belongs to a different original research assignment')
    _validate_prior_effects(root, core, prepared['inputs'])
    result = cycle.execute_graph(root, graph_root, spec, host, prepared=Path(graph_root).exists())
    if not result['complete']:
        from langgraph.types import interrupt
        interrupt({'kind':'actual_model_effect_or_external_delivery_required','graph_root':str(graph_root),
            'actual_graph':result,'acceptance_from_resume':False})
        result = cycle.execute_graph(root, graph_root, spec, host, prepared=True)
        if not result['complete']: raise orchestrator.RecoveryHold('ordinary decision remains unresolved')
    origin = cycle._graph_result(graph_root, 'decision')
    if origin['value'].get('kind') != 'model_result':
        raise ValueError('actual structured model decision required; inert controls remain controls')
    if origin['inputs'] != spec['nodes'][0]['inputs']:
        raise ValueError('decision did not receive its complete actual source context')
    for pin in prepared['inputs']: cycle._check_pin(pin, Path(pin['path']).parent)
    _validate_prior_effects(root, core, origin['inputs'])
    for row in [*core['catalogue']['operations'], *core['catalogue']['extensions']]:
        if row['source'] is not None and cycle._pin(row['source']['path'])['sha256']!=row['source']['sha256']:
            raise ValueError('operation source changed during ordinary decision')
    return deepcopy(origin)


def _register_row(row):
    """The register declaration as research_cycle reads it: absent ``what_is_new`` fields are omitted."""
    changes = {k: v for k, v in (row.get('what_is_new') or {}).items() if v is not None}
    return {**row, 'what_is_new': changes or None}


def adopt_hypotheses(root, origin, *, stream=None):
    if cycle._graph_result(origin['root'],origin['node_id'])!=origin:
        raise ValueError('hypothesis checkpoint differs from actual model result')
    rows = [_register_row(row) for row in origin['value']['value']['hypotheses']]
    if stream is not None and any(row['stream'] != stream for row in rows):
        raise ValueError('independent idea streams must preserve their source-defined labels')
    _, state = cycle._load(root)
    allowed = {(p['path'],p['sha256']) for p in origin['inputs']}
    for h in rows:
        if any((p['path'],p['sha256']) not in allowed for p in h['source_basis']):
            raise ValueError('hypothesis attribution must have been actually presented')
    existing = [h for h in state['hypotheses'] if h['id'] in {r['id'] for r in rows}]
    if existing:
        if len(existing)!=len(rows) or any(h['origin']!=origin or
                {k:h[k] for k in rows[0]} != next(r for r in rows if r['id']==h['id']) for h in existing):
            raise orchestrator.RecoveryHold('partial or superseded hypothesis effect requires explicit reconciliation')
        return state
    return cycle.propose(root, rows, origin={'kind':'graph','root':origin['root'],'node_id':origin['node_id']})




def requested_sources(value, origin):
    if cycle._graph_result(origin['root'],origin['node_id'])!=origin:
        raise ValueError('source request must be the unchanged actual designer result')
    public=origin['value']['value']
    extensions=[]
    if public.get('kind')=='research-source-request':
        _keys(public,{'kind','context_json','obligation_mapping_json','modes','reason'})
        from .agent_host import _loads
        if _loads(public['context_json'])!={} or _loads(public['obligation_mapping_json'])!=[]:
            raise ValueError('nonvoting source request may not contain a partial scientific declaration')
        modes=public['modes']
    elif public.get('kind')=='research-action' and public.get('action')=='source-context':
        from .agent_host import _loads
        args=_loads(public['arguments_json']);_keys(args,{'modes'}|{key for key in ('artifacts','extensions') if key in args});modes=args['modes']
        extensions=args.get('extensions',[])
    else:raise ValueError('actual nonvoting source context request required')
    current=catalogue(value['candidate_modes'])
    rows={r['mode']:r for r in current['operations']}
    if type(modes) is not list or not 0<=len(modes)<=32 or len(set(modes))!=len(modes) or set(modes)-rows.keys():
        raise ValueError('bounded distinct actual source catalogue modes required')
    extension_rows={r['action']:r for r in current['extensions']}
    if (type(extensions) is not list or len(extensions)>32
            or any(type(name) is not str for name in extensions)
            or len(set(extensions))!=len(extensions) or set(extensions)-extension_rows.keys()):
        raise ValueError('bounded distinct actual source catalogue extensions required')
    # Exact original decision census also binds the source epoch: a later
    # current-source recapture cannot bless a substituted implementation.
    core_pin=next(p for p in origin['inputs'] if p['id']=='scientific-core')
    core=expand_decision_context(orchestrator._read({'path':core_pin['path'],'sha256':core_pin['sha256'],
        'size':Path(core_pin['path']).stat().st_size}))
    committed={r['mode']:r['source'] for r in core['catalogue']['operations']}
    committed_extensions={r['action']:r for r in core['catalogue']['extensions']}
    made=[]
    for mode in modes:
        p=cycle._pin(rows[mode]['source']['path'])
        if committed[mode]['path']!=p['path'] or committed[mode]['sha256']!=p['sha256']:
            raise ValueError('source request differs from its original committed catalogue')
        raw=Path(p['path']).read_bytes();raw.decode('utf-8')
        if len(raw)>MAX_CORE_BYTES or cycle._pin(p['path'])!=p:
            raise ValueError('full selected source requires an explicit bounded source-page preparation, no truncation')
        made.append(p)
    for name in extensions:
        row=extension_rows[name]
        original=committed_extensions.get(name)
        if (original is None or original.get('status')!='connected_public_source'
                or row['status']!='connected_public_source' or original.get('source') is None
                or row.get('source') is None):
            raise ValueError('extension source was not connected in its original committed catalogue')
        p=cycle._pin(row['source']['path'])
        if (original['source']['path']!=p['path'] or original['source']['sha256']!=p['sha256']
                or any(original[key]!=row[key] for key in ('module','function'))):
            raise ValueError('extension source request differs from its original committed catalogue')
        raw=Path(p['path']).read_bytes();raw.decode('utf-8')
        if len(raw)>MAX_CORE_BYTES or cycle._pin(p['path'])!=p:
            raise ValueError('full selected extension requires explicit bounded source pages, no truncation')
        made.append(p)
    if public.get('kind')=='research-action':
        artifacts=args.get('artifacts',[])
        if type(artifacts) is not list or len(artifacts)>32:
            raise ValueError('bounded exact prepared-artifact selections required')
        available={p['path']:p for effect in prior_effect_documents(core, origin['inputs'])
            for p in effect.get('actual_effect',{}).get('materialized_inputs',[])}
        seen=set()
        for pin in artifacts:
            _keys(pin,{'path','sha256','size'})
            if pin['path'] in seen or available.get(pin['path'])!=pin:
                raise ValueError('source selection must name an original committed preparation output')
            seen.add(pin['path']);path,current=cycle._check_pin(pin,Path(pin['path']).parent)
            raw=path.read_bytes();raw.decode('utf-8')
            if len(raw)>MAX_CORE_BYTES or cycle._pin(path)!=current:
                raise ValueError('selected prepared content requires explicit bounded pages, no truncation')
            made.append(current)
    if not made:raise ValueError('nonempty complete source-body selection required')
    return made


def authored_records(origin, records, out):
    if cycle._graph_result(origin['root'],origin['node_id'])!=origin:
        raise ValueError('authored configuration requires unchanged actual model origin')
    if type(records) is not list or len(records)>32:
        raise ValueError('at most32 prospective JSON configurations required')
    allowed={(p['path'],p['sha256']) for p in origin['inputs']};seen=set();made={}
    for row in records:
        _keys(row,{'id','purpose','value','source_basis'})
        graph._id(row['id'],'authored configuration')
        if row['id'] in seen or row['purpose']!='prospective_configuration':
            raise ValueError('distinct prospective-configuration purpose required; authored physics observations are forbidden')
        seen.add(row['id'])
        if type(row['source_basis']) is not list or not row['source_basis'] or any(
                (p['path'],p['sha256']) not in allowed for p in row['source_basis']):
            raise ValueError('configuration must identify actually supplied method sources')
        raw=json.dumps(row['value'],allow_nan=False).encode()
        if len(raw)>400000:raise ValueError('authored configuration exceeds original model envelope bound')
        made[row['id']]=_put(Path(out)/(row['id']+'.json'),row['value'])
    provenance=_put(Path(out)/'authored-configurations.json',{'kind':'model-authored-prospective-configurations',
        'origin':origin,'records':records,'materialized':made,'quantity_type':'configuration, not measured/retrieved physics inputs',
        'scientific_acceptance':False,'physics_validated':False,'execution_authorized':False})
    return made,provenance


def generated_references(value, made):
    if type(value) is dict:
        if set(value)=={'generated_record','field'}:
            identity=value['generated_record'];field=value['field']
            if identity not in made or field not in {'path','sha256','pin2','pin3'}:
                raise ValueError('exact available generated configuration reference required')
            p=made[identity]
            return {k:p[k] for k in ('path','sha256')} if field=='pin2' else deepcopy(p) if field=='pin3' else p[field]
        return {k:generated_references(v,made) for k,v in value.items()}
    if type(value) is list:return [generated_references(v,made) for v in value]
    return deepcopy(value)


def _prepared_inputs(actual, out):
    """Exact public preparation outputs, not a guessed result-file inventory.

    The complete returned tool value itself enters the next model turn. The
    two existing specification producers and marginal-recipe producer also
    publish source-defined file pins. Context-only tools confer no new asset.
    """
    public=actual['value']
    if public.get('kind')!='ravel_tool_result':
        raise ValueError('actual source-defined ordinary tool result required')
    payload=public['value'];pins=[]
    if public['action'] in {'model-event-plan','model-spectrum-plan'}:
        if 'specification' in payload:pins.append(payload['specification'])
        if payload.get('kind')=='finite-parameter-grid-proposals':
            for point in payload['points']:
                pins.extend(point[k] for k in ('input_card','configuration','specification'))
    elif public['action']=='response-recipes':
        pins.append(payload['receipt'])
        receipt=orchestrator._read(payload['receipt'])
        if receipt.get('kind')!='prepared-athena-marginal-recipes':
            raise ValueError('exact marginal-recipe producer receipt required')
        pins.extend(receipt['outputs'])
    result_pin=_put(Path(out)/'tool-result.json',deepcopy(public))
    made=[result_pin]
    for pin in pins:
        path=Path(pin['path'])
        if not path.is_absolute() or not path.is_relative_to(Path(out)/'prepared'):
            raise ValueError('preparation output must remain in its owned source-defined destination')
        current=cycle._pin(path)
        if pin.get('sha256')!=current['sha256'] or ('size' in pin and pin['size']!=current['size']):
            raise ValueError('actual committed preparation output changed')
        made.append(current)
    return list({p['path']:p for p in made}.values())


def preparation_tool(root,value,origin,arguments,out,host):
    _keys(arguments,{'action','parameters','inputs','records'})
    if arguments['action'] not in {r['action'] for r in catalogue(value['candidate_modes'])['preparation_tools']}:
        raise ValueError('existing source-defined preparation consumer required')
    made,provenance=authored_records(origin,arguments['records'],Path(out)/'authored')
    args=generated_references(arguments,made);inputs=args['inputs']
    if type(inputs) is not list or len(inputs)>128:raise ValueError('ordinary128 input cap remains')
    allowed={(p['path'],p['sha256']) for p in origin['inputs']}
    allowed.update((p['path'],p['sha256']) for p in made.values())
    allowed.update((r['pin']['path'],r['pin']['sha256']) for r in value['evidence'] if r['purpose']=='execution_dependency')
    seen=set();normal=[]
    for row in inputs:
        _keys(row,{'id','pin'});graph._id(row['id'],'preparation input')
        if row['id'] in seen or (row['pin']['path'],row['pin']['sha256']) not in allowed:
            raise ValueError('preparation inputs must be supplied/authored configuration; withheld evaluation is inaccessible')
        seen.add(row['id']);cycle._check_pin(row['pin'],Path(root))
        normal.append({'id':row['id'],'path':row['pin']['path'],'sha256':row['pin']['sha256']})
    parameters=args['parameters']
    if type(parameters) is not dict:raise ValueError('exact native preparation parameters required')
    if 'output_dir' in parameters:parameters['output_dir']=str(Path(out)/'prepared')
    settings=runtime(value['runtime'])
    spec={'schema_version':1,'graph_id':'ordinary-'+arguments['action'],
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':settings['max_wall_seconds'],'max_reworks':0},
        'nodes':[{'id':'prepare','kind':'tool','role':'executor','depends_on':[],'inputs':normal,'packet':None,
            'action':arguments['action'],'max_attempts':1,'parameters':parameters}]}
    root_graph=Path(out)/'graph'
    observed=cycle.execute_graph(root,root_graph,spec,host,prepared=root_graph.exists())
    if observed['complete']:
        actual=cycle._graph_result(root_graph,'prepare')
        prepared_inputs=_prepared_inputs(actual,out)
        return {'status':'prepared','actual_preparation':actual,'authored_configuration_provenance':provenance,
            'materialized_inputs':[*made.values(),provenance,*prepared_inputs],
            'next_context_inputs':[*made.values(),provenance,prepared_inputs[0]],'scientific_acceptance':False}
    _,current=graph._load(root_graph)
    failed=current['nodes']['prepare']
    if failed['status']=='failed' and not failed['retryable']:
        # No successful asset is fabricated. Retain the actual ordinary failed
        # call/error for the next charged design turn under the same budget.
        return {'status':'preparation_failed','graph_root':str(root_graph),'actual_graph':observed,
            'actual_node_failure':deepcopy(failed),'authored_configuration_provenance':provenance,
            'materialized_inputs':[*made.values(),provenance],'scientific_acceptance':False}
    from langgraph.types import interrupt
    interrupt({'kind':'preparation_effect_reconciliation_required','graph_root':str(root_graph),'actual_graph':observed})
    raise orchestrator.RecoveryHold('unknown/unresolved preparation cannot be repeated or promoted')


def admit_experiment(root, value, origin, out, arguments):
    _, state = cycle._load(root)
    preparation = None
    prepared_pin = arguments.get('prepared_experiment')
    if prepared_pin is not None:
        _keys(arguments, {'prepared_experiment'})
        # The ordinary Graph preserves {id,path,sha256}; the preparation
        # producer emits {path,sha256,size}. Authenticate the complete pin,
        # then compare only their canonical content identity, never record shape.
        _, current_pin = cycle._check_pin(prepared_pin, state['base_dir'])
        if (cycle._graph_result(origin['root'], origin['node_id']) != origin
                or prepared_pin != current_pin
                or (current_pin['path'], current_pin['sha256']) not in {
                    (p['path'], p['sha256']) for p in origin['inputs']}):
            raise ValueError('complete prepared experiment must enter this actual designer context')
        records = []
        for event in state['events']:
            if event['kind'] != 'coordinator_effect_committed':continue
            effect = cycle._read(event['effect'],state['base_dir'])
            if (effect['actual_effect'].get('prepared_experiment') == prepared_pin
                    and effect['actual_effect'].get('status') == 'prepared_not_admitted'):
                checked = cycle._coordinator_effect(state,effect['origin'])
                if checked is None or checked['pin'] != event['effect']:
                    raise ValueError('prepared experiment lost original campaign commitment')
                records.append(effect)
        if len(records)!=1:raise ValueError('one original committed experiment preparation required')
        preparation = orchestrator._read(prepared_pin)
        _keys(preparation, {'kind','study','experiment','source_mapping','provenance','materialized_inputs','original_origin'})
        if (preparation['kind']!='prospective-experiment-exposure-preparation'
                or preparation['original_origin']!=records[0]['origin']):
            raise ValueError('prepared experiment differs from original source-bound authoring')
        for pin in preparation['materialized_inputs']:cycle._check_pin(pin,state['base_dir'])
        expanded={'study':orchestrator._read(preparation['study']),
            'experiment':deepcopy(preparation['experiment']),'source_mapping':deepcopy(preparation['source_mapping'])}
        made={};provenance=preparation['provenance']
    else:
        _keys(arguments, {'study','experiment','source_mapping'} | ({'records'} if 'records' in arguments else set()))
        made,provenance=authored_records(origin,arguments.get('records',[]),Path(out)/'authored')
        expanded=generated_references(arguments,made)
    spec = deepcopy(expanded['study'])
    if made:
        spec['assumptions'].append('Prospective JSON configurations are model-authored from the bound decision, not measured/retrieved physics observations; all physical inputs and applicability require independent review. Provenance '+provenance['sha256'])
    science.validate(spec)
    if spec['mode'] not in value['candidate_modes'] or spec.get('goal_binding') != state['contract'].get('goal_binding'):
        raise ValueError('experiment must use a selected actual operation and exact original assignment')
    row = deepcopy(expanded['experiment'])
    if set(row['predictions']) != {h['id'] for h in state['hypotheses'] if cycle._fresh(state,h['premise_bindings'])}:
        raise ValueError('complete current rival prediction/unknown denominator required')
    if row['parent'] is not None: cycle.feedback_packet(root,row['parent'])
    context = state['context']['request']
    cycle._context_mapping(state, context, expanded['source_mapping'])
    allowed = {(p['path'],p['sha256']) for p in origin['inputs']}
    generated={(p['path'],p['sha256']) for p in made.values()}
    # Use the exact same source/base and full tool-context closure as the
    # canonical exposure producer and _append_design. An authored study is
    # emitted below into out; a prepared study keeps its original source base.
    study_base = Path(row['study']['path']).parent if preparation is not None else Path(out)
    if not study_base.is_absolute():study_base = Path(state['base_dir']) / study_base
    dependencies = [cycle._pin(p) for p in science.task_inputs(spec, study_base)]
    dependencies = cycle._tool_input_closure(row, dependencies, state['base_dir'], state=state)
    # The full original request commits worker-only bytes without giving their
    # bodies to this model. Existing exposure admission below still requires the
    # exact complete inventory as an actual input and refuses private disclosure.
    private = {(p['pin']['path'],p['pin']['sha256']) for p in value['evidence']
        if p['purpose'] in {'execution_dependency','withheld_evaluation'}}
    for evidence in value['evidence']:
        cycle._check_pin(evidence['pin'],state['base_dir'])
    if any((p['path'],p['sha256']) not in allowed | generated | private for p in dependencies):
        raise ValueError('scientific dependency lacks presented/generated or original private custody')
    for mapping in expanded['source_mapping']:
        if any((p['path'],p['sha256']) not in allowed for p in mapping['sources']):
            raise ValueError('experimental method attribution was not presented')
    if preparation is not None:
        if preparation['study'] != row['study'] or orchestrator._read(row['study']) != spec:
            raise ValueError('prepared exact study/exposure cannot be replaced')
    else:
        row['study'] = _put(Path(out)/'science.json', spec)
    if preparation is None and any((p['path'],p['sha256']) in private for p in dependencies):
        if 'input_exposure' in row:
            raise ValueError('private preparation cannot accept a guessed future-study exposure')
        purposes={(e['pin']['path'],e['pin']['sha256']):e['purpose'] for e in value['evidence']}
        classifications={p['path']:purposes.get((p['path'],p['sha256']),'model_context') for p in dependencies}
        row=cycle.bind_input_exposure(row,classifications,Path(out)/'exposure',base_dir=state['base_dir'],
            reason='Original worker-only custody; complete inventory for a fresh charged designer, no private content reading.')
        material=[*made.values(),provenance,row['study'],row['input_exposure']]
        package=_put(Path(out)/'prepared-experiment.json',{'kind':'prospective-experiment-exposure-preparation',
            'study':row['study'],'experiment':row,'source_mapping':expanded['source_mapping'],
            'provenance':provenance,'materialized_inputs':material,'original_origin':origin})
        return {'status':'prepared_not_admitted','prepared_experiment':package,
            'materialized_inputs':[*material,package],'next_context_inputs':[*material,package],
            'scientific_acceptance':False,'execution_authorized':False,'parent_task_accepted':False}
    result={'experiment':row['id'],'study':row['study'],
        'materialized_inputs':[*made.values(),provenance,row['study']]}
    if preparation is None:result['authored_configuration_provenance']=provenance
    else:
        result.update(prepared_experiment=prepared_pin,preparation_origin=preparation['original_origin'])
        result['materialized_inputs'].extend([prepared_pin,row['input_exposure']])
    existing = next((e for e in state['experiments'] if e['id']==row['id']),None)
    if existing is not None:
        if any(existing[k]!=v for k,v in row.items()) or existing.get('coordinator_origin')!=origin:
            raise orchestrator.RecoveryHold('experiment identity already belongs to another design')
        if existing['observation'] is None:
            for pin in [existing['study'],*existing['input_pins']]:cycle._check_pin(pin,state['base_dir'])
        else:cycle._current_evidence(state,existing,accepted=existing['adjudication'] is not None and existing['adjudication']['view']['state']=='accepted')
        return result
    with cycle.state_io.file_lock(Path(root)/'operation.lock',blocking=False):
        _, current = cycle._load(root)
        cycle._append_design(current,row)
        if made and current['experiments'][-1].get('input_exposure') is not None:
            raise ValueError('authored-config exposure requires an explicit separate source-bound preparation, never relabel withheld data')
        cycle._model_input_admission(current['experiments'][-1],
            [p for p in dependencies if (p['path'],p['sha256']) not in generated],origin['inputs'],state['base_dir'])
        current['experiments'][-1]['coordinator_origin']=deepcopy(origin)
        current['experiments'][-1]['source_mapping']=deepcopy(expanded['source_mapping'])
        current['experiments'][-1]['authored_configuration_provenance']=provenance
        if preparation is not None:current['experiments'][-1]['preparation_origin']=deepcopy(preparation['original_origin'])
        cycle._commit(Path(root),current,'model_designed_discriminating_experiment',experiment_id=row['id'],
            full_rivals_and_original_deliverables_retained=True,old_votes_carried=[])
    return result


def invoke_extension(action, root, args, out, host, settings):
    """Hardcoded ordinary domain APIs; never execute arbitrary named Python."""
    module_name, name = EXTENSIONS[action]
    if action=='literature-discover':
        _keys(args,{'request_pin'})
        return importlib.import_module(module_name).discover_literature(root,args['request_pin'],out,host,
            max_wall_seconds=settings['max_wall_seconds'])
    if action=='literature-discovered-sources':
        _keys(args,{'product_pin','reason'})
        return importlib.import_module(module_name).prepare_discovered_sources(root,args['product_pin'],out,reason=args['reason'])
    if action=='literature-acquire':
        _keys(args,{'request_pin'})
        return importlib.import_module(module_name).acquire_literature(root,args['request_pin'],out,host,
            max_wall_seconds=settings['max_wall_seconds'])
    if action=='literature-context':
        _keys(args,{'request_pin','premise_map','reason'})
        return importlib.import_module(module_name).prepare_literature_context(root,args['request_pin'],out,
            premise_map=args['premise_map'],reason=args['reason'])
    if action=='literature-pdf':
        _keys(args,{'request_pin'})
        return importlib.import_module(module_name).extract_literature_pdf(root,args['request_pin'],out,host,
            max_wall_seconds=settings['max_wall_seconds'])
    if action.startswith('replication-'):
        module=importlib.import_module(module_name)
        if action=='replication-prepare':
            _keys(args,{'current_report_pin','method_id','check_contract_pin'})
            return module.prepare_replication_request(root,args['current_report_pin'],args['method_id'],out,check_contract_pin=args['check_contract_pin'])
        if action=='replication-design':
            _keys(args,{'request_pin','experiment_id'})
            return module.design_prepared(root,args['request_pin'],experiment_id=args['experiment_id'])
        _keys(args,{'request_pin'})
        return module.prepare_comparison(root,args['request_pin'],out)
    if action=='model-proposals':
        _keys(args,{'request_pin','premise_map','reason'})
        return importlib.import_module(module_name).prepare_model_proposals(root,**args)
    if action.startswith('routine-'):
        module=importlib.import_module(module_name)
        if action=='routine-workflow':
            _keys(args, {'choice_pin'})
            return module.routine_workflow(root,args['choice_pin'],out,host,max_wall_seconds=settings['max_wall_seconds'])
        _keys(args, {'selection_pin'})
        return module.routine_step(root,args['selection_pin'],base_dir=Path(root),host=host,output_dir=out)
    module=importlib.import_module(module_name)
    if action in {'manuscript-actions','manuscript-action-meta','manuscript-successor','manuscript-action-resolve'}:
        module=importlib.import_module(module_name);_keys(args,set(EXTENSION_TRANSPORT[action]['arguments']))
        if action=='manuscript-actions':return module.prepare_actions(args['revision'],args['actions'],out,base_dir=Path(root),campaign=root)
        if action=='manuscript-action-meta':
            prepared=module.prepare_action_meta(args['action_plan'],out,base_dir=Path(root),campaign=root,**args['runtime'])
            spec=cycle.state_io.read_json(prepared['graph_spec']['path']);graph_root=Path(out)/'graph'
            observed=cycle.execute_graph(root,graph_root,spec,host,prepared=graph_root.exists())
            if not observed['complete']:raise orchestrator.RecoveryHold('manuscript scientific meta effect remains unresolved; retain original charged Graph')
            from . import research_protocol
            applied=research_protocol.apply_meta_review(root,graph_root=graph_root,node_id='meta',context_pin=prepared['context'])
            # An uncredited response is retained, labelled advice; it changed no protocol state.
            advice=applied.get('kind')=='review_advice'
            return {'preparation':prepared,'applied':applied,'scientific_acceptance':False,
                    'meta_action':'ADVISORY - META ACTION NOT APPLIED' if advice else 'applied'}
        if action=='manuscript-successor':
            prepared=module.prepare_successor(args['action_plan'],args['replacement_request'],out,base_dir=Path(root),campaign=root)
            module.mp.execute_writer(prepared['writer'],host)
            return prepared
        return module.resolve_actions(args['successor'],args['package'],args['review_bindings'],out,base_dir=Path(root),campaign=root)
    if action in {'manuscript-story','manuscript-phase','manuscript-consume-phase','manuscript-resolve-sources',
                  'manuscript-assemble','manuscript-revision','manuscript-literature','manuscript-supplementary'}:
        _keys(args,set(EXTENSION_TRANSPORT[action]['arguments']))
        if action=='manuscript-story':
            prepared=module.prepare_story(args['request_pin'],out,base_dir=Path(root),campaign=root)
            module.execute_phase(prepared,host)
            return prepared
        if action=='manuscript-phase':
            destination=module.phase_destination(args['story'],args['phase_id'],base_dir=Path(root),campaign=root)
            prepared=module.prepare_phase(args['story'],args['phase_id'],destination,base_dir=Path(root),campaign=root,
                prior_products=args['prior_products'],resolution_pin=args['resolution'])
            module.execute_phase(prepared,host)
            return prepared
        if action=='manuscript-consume-phase':
            destination=module.consumption_destination(args['binding'],base_dir=Path(root))
            return module.consume_phase(args['binding'],destination,base_dir=Path(root))
        if action=='manuscript-resolve-sources':return module.resolve_sources(args['story'],args['resolved_request'],out,base_dir=Path(root),campaign=root)
        if action=='manuscript-assemble':return module.assemble(args['story'],args['phase_products'],out,base_dir=Path(root),campaign=root,synthesis_binding=args['synthesis_binding'])
        if action=='manuscript-revision':return module.prepare_revision(args['package'],args['review_bindings'],out,base_dir=Path(root),campaign=root,budget=args['budget'])
        if action=='manuscript-literature':return module.prepare_literature(args['story'],args['scout'],args['literature_request'],out,base_dir=Path(root),campaign=root)
        return module.prepare_supplementary(args['revision'],args['method_id'],args['check_contract'],out,base_dir=Path(root))
    if action=='manuscript-author':
        _keys(args, {'request'})
        binding=module.prepare_writer(args['request'],out,base_dir=Path(root),campaign=root)
        module.execute_writer(binding,host)
        return binding
    if action=='manuscript-collect':
        _keys(args, {'binding'})
        return module.collect(args['binding'],out)
    if action=='manuscript-build':
        _keys(args, {'package','arguments'})
        return module.prepare_build(args['package'],out,base_dir=Path(root),**args['arguments'])
    if action=='manuscript-review':
        _keys(args,{'package','arguments'})
        prepared=module.prepare_integrity_role(args['package'],out,base_dir=Path(root),campaign=root,**args['arguments'])
        _keys(prepared, {'manuscript','role_binding','execution_authorized'})
        if prepared['execution_authorized'] is not False or type(prepared['role_binding']) is not dict:
            raise ValueError('source-defined manuscript review preparation envelope required')
        from . import scientific_judgment
        scientific_judgment.execute_role(prepared['role_binding'],host)
        return prepared
    if action=='manuscript-consume':
        _keys(args,{'package','binding'})
        return module.consume_integrity_role(args['package'],args['binding'],base_dir=Path(root))
    _keys(args,{'package','bindings','build_binding','final_manifest','completion_request','rundir'})
    return module.finalize(args['package'],args['bindings'],args['build_binding'],args['final_manifest'],
        args['completion_request'],base_dir=Path(root),rundir=args['rundir'])


def diagnose(root, value, arguments, out, host):
    """Attach/review an actual failed attempt; never rerun or certify it."""
    from . import failed_stage_review as failed
    _keys(arguments,{'experiment','intake'})
    _,state=cycle._load(root)
    e=next(row for row in state['experiments'] if row['id']==arguments['experiment'])
    if e['observation'] is None or e['observation']['execution_status']!='failed':
        raise ValueError('actual observed failed attempt required for diagnosis')
    cycle._current_evidence(state,e)
    doc=failed.intake(arguments['intake'],base_dir=e['rundir'])
    if doc['actors'] is None:
        raise ValueError('diagnostic role identities require the exact original bound policy')
    intake_pin=_put(Path(out)/'failed-intake.json',doc)
    from . import gate_wiring  # failed_stage_feedback before any role runs or feedback is attached.
    gate_wiring.require_failed_feedback(e['rundir'],intake_pin)
    if e.get('failed_intake') is None:
        cycle.attach_failed_stage(root,e['id'],intake_pin)
    elif e['failed_intake']!=intake_pin:
        raise orchestrator.RecoveryHold('diagnostic intake differs from the original attached failure')
    bindings=[]
    settings=runtime(value['runtime'])
    for role,actor_key in (('critic','physics_critic'),('verifier','skeptical_verifier')):
        packet=Path(out)/role/'context'
        if not packet.exists():
            manifest=failed.create_context(doc,role,packet,base_dir=e['rundir'])
        else:
            manifest=cycle.state_io.read_json(packet/'manifest.json')
            from . import review_context
            review_context.verify_packet(packet,expected_manifest_sha256=manifest['sha256'])
            if manifest.get('source_event_sha256')!=doc['sha256'] or manifest.get('role')!=role:
                raise ValueError('diagnostic role packet belongs to a different failure')
        fields={'kind':{'const':'failure-diagnostic','type':'string'},
            'subject_sha256':{'const':doc['sha256'],'type':'string'},
            'root_causes':{'type':'array','items':{'type':'string'},'maxItems':64},
            'unknowns':{'type':'array','items':{'type':'string'},'maxItems':64},
            'discriminating_tests':{'type':'array','items':{'type':'string'},'maxItems':64},
            'summary':{'type':'string','minLength':1,'maxLength':16000}}
        spec={'schema_version':1,'graph_id':'failure-'+role,
            'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':settings['max_output_tokens'],
                'max_wall_seconds':settings['max_wall_seconds'],'max_reworks':0},
            'nodes':[{'id':role,'kind':'model','role':role,'depends_on':[],'inputs':[],
                'packet':{'path':str(packet),'manifest_sha256':manifest['sha256']},
                'action':settings['adapter'],'max_attempts':1,
                'parameters':{'model':settings['model'],'reasoning_effort':settings['reasoning_effort'],
                    'max_output_tokens':settings['max_output_tokens'],
                    'instructions':instruction('failed_experiment_diagnosis'),
                    'output_schema':{'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}}}]}
        graph_root=Path(out)/role/'graph'
        observed=cycle.execute_graph(root,graph_root,spec,host,prepared=graph_root.exists())
        if not observed['complete']:
            from langgraph.types import interrupt
            interrupt({'kind':'actual_failed_diagnostic_role_required','graph_root':str(graph_root),'scientific_acceptance':False})
            observed=cycle.execute_graph(root,graph_root,spec,host,prepared=True)
            if not observed['complete']:raise orchestrator.RecoveryHold('diagnostic role remains unresolved')
        bindings.append({'graph_root':str(graph_root),'node_id':role,
            'context_manifest_sha256':manifest['sha256'],'actor_id':doc['actors'][actor_key]})
    feedback=failed.graph_feedback(doc,*bindings,base_dir=e['rundir'],allow_control=value['review']['allow_control'])
    feedback_pin=_put(Path(out)/'diagnostic-feedback.json',feedback)
    current=next(row for row in cycle._load(root)[1]['experiments'] if row['id']==e['id'])
    if current.get('diagnostic_feedback') is None:
        cycle.diagnostic_feedback(root,e['id'],feedback_pin,allow_control=value['review']['allow_control'])
    elif current['diagnostic_feedback']!=feedback_pin:
        raise orchestrator.RecoveryHold('actual diagnostic feedback has another prior commitment')
    return {'experiment':e['id'],'intake':intake_pin,'feedback':feedback_pin,
        'scientific_acceptance':False,'native_repeated':False,'parent_task_accepted':False}
