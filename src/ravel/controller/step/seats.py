"""Who may fill a seat, and the worker spec a seat is dispatched with (mechanisms M06, M07).

In controller mode a seat is filled only by a worker the controller itself starts through the
single dispatcher: a CLI worker whose launcher ``LAUNCHER_RESTRICTIONS`` admits (Claude, Codex and Gemini
with code-generated restrictions and broker MCP only) or the RAVEL
loop worker (``ravel.transports.ravel_loop_worker``: RAVEL's own code, broker tools only). A host
subagent, a one-shot CLI, the generic delegate, the external relay, a direct HTTP call and every
CLI the table does not admit never fill one; neither does the parent conversation, which has no seat
to fill (I03, I05, T01, T02). Each attempt is a fresh session in a fresh workspace; a session seen
before earns no credit. ``wired_kinds()`` are the kinds whose adapter implements launch and
observation; ``wired_transports()`` are the installed declarations a governed seat can run on, with
the reason for every other one. A one-call model node is a seat whose card allows no broker call
(an empty toolbelt and one turn's worth of calls), dispatched on this same path; never a one-shot CLI.

The transport comes from the operator's frozen preferences filtered to the admitted kinds and
the card's ``requires`` (tools, isolation, attestation, blind, structured output) and model tier
through ``transport_registry.select``; a seat no admitted transport meets holds with the missing
items and is never moved to another route (T09, E01). The model tier and effort the card asks
for are requested at launch and compared with what ran (I08); a ``cheap_ok`` card is requested at
the ``cheap`` tier when the frozen preferences map a cheap model to the transport. A frozen model
the model catalogue does not list is labelled under ``catalogue_problems`` with its remedy; the
label never holds a seat.
"""
from __future__ import annotations

from copy import deepcopy

from .services import StepHold

ADMITTED_KINDS = ('cli-worker', 'ravel-loop')
# The flags that make a Claude CLI worker restricted: only the broker MCP, no built-in tools.
RESTRICTED_FLAGS = ('--restricted', '--strict-mcp-config', '--tools', '--allowedTools')
CONTROLLER_SCHEMA = 'controller.v1'
REMEDY = 'ravel transport qualify {transport} --rundir <empty dir> --model <model> --for-operator'

# Per launcher: the argv and generated-configuration evidence that a CLI worker has no native write
# capability and no tool outside the broker toolbelt. A launcher is admitted only when its declaration
# template carries every listed flag and its worker surface is the listed MCP configuration; a launcher
# with ``admitted: False`` is refused as ``launcher:<launcher>`` whatever its template says, for the
# recorded reasons (docs/reference/transports.md, "Controller seats").
LAUNCHER_RESTRICTIONS = {
    # --tools is filled with '' by the adapter (no built-in tool); --allowedTools names only the broker MCP
    # tools; --strict-mcp-config loads only the --mcp-config file the adapter generates (the broker server).
    'claude': {'admitted': True, 'flags': RESTRICTED_FLAGS, 'placeholders': {'--tools': '{tools}'},
               'surface': 'mcp_config_flag'},
    # Generated per-attempt homes disable native tools. Qualification must observe the resulting
    # tool surface before this route can seat a role; a version that ignores a key earns no credit.
    'codex': {'admitted': True, 'flags': ('--sandbox', '--json', '--output-schema'),
              'placeholders': {'--sandbox': 'read-only'}, 'surface': 'codex_home'},
    'gemini': {'admitted': True, 'flags': ('--sandbox', '--output-format'),
               'placeholders': {'--output-format': 'json'}, 'surface': 'settings_json'},
    # `agy --mode accept-edits` grants native file edits; its MCP surface is unconfirmed (probe_required).
    'agy': {'admitted': False, 'reason': 'accept-edits mode grants native writes; the MCP surface is unconfirmed'},
    'opencode': {'admitted': False, 'reason': 'native tools outside the broker are not shown to be excluded'},
    'qwen': {'admitted': False, 'reason': 'no generated worker surface; native tools are not shown to be excluded'},
}


def admission_problem(document):
    """Why a transport declaration cannot fill a controller seat (None when it can)."""
    kind = document['transport_kind']
    if kind not in ADMITTED_KINDS:
        return 'transport_kind:' + kind
    if kind == 'ravel-loop':
        # RAVEL's own loop worker: only the broker tools of the pinned toolbelt and ``submit_final``.
        return None
    launcher = document.get('launcher')
    rule = LAUNCHER_RESTRICTIONS.get(launcher)
    if rule is None or not rule['admitted']:
        return 'launcher:' + str(launcher)
    template = document.get('argv_template') or []
    missing = [flag for flag in rule['flags'] if flag not in template]
    if missing:
        return 'unrestricted:' + ','.join(missing)
    for flag, placeholder in rule['placeholders'].items():
        position = template.index(flag) + 1
        if position >= len(template) or template[position] != placeholder:
            return 'unrestricted:' + flag
    if ((document.get('worker_surface') or {}).get('mcp') or {}).get('config') != rule['surface']:
        return 'unrestricted:worker_surface.mcp'
    return None


def wired_kinds():
    """The admitted kinds whose launch adapter implements a controller seat's launch and observation."""
    from ravel.workflow import transport_registry as tr
    found = []
    for kind in ADMITTED_KINDS:
        try:
            module = tr.adapter_module(kind)
        except ImportError:
            continue
        if module is not None and all(callable(getattr(module, name, None))
                                      for name in ('unsupported', 'prepare_launch', 'observe', 'current_probe')):
            found.append(kind)
    return tuple(found)


def seat_problem(document):
    """Why a governed seat cannot run on this declaration here (None when it can): admission, a wired
    adapter, the executor on this host (sandbox, adapter support) and the provider's usage split."""
    from ravel.workflow import transport_registry as tr
    from ravel.workflow.transports import provider_usage
    problem = admission_problem(document)
    if problem is not None:
        return problem
    if document['transport_kind'] not in wired_kinds():
        return 'adapter_unwired:' + document['transport_kind']
    problem = tr.executor_problem(document)
    if problem is not None:
        return problem
    return None


def wired_transports():
    """The installed declarations a governed seat can run on, and the reason for each other one.

    Returns ``{'wired': [ids], 'excluded': [{'transport', 'reason', ...}], 'kinds': wired_kinds()}``. An
    excluded row of a launcher the table refuses carries the table's ``detail``; every excluded row of an
    admitted kind names its ``usage_split`` problem too (None when the provider reports the split). A wired
    declaration still needs its probe and the operator's qualification in the run's store before a seat
    is selected, and a card holds where the declaration cannot meet it (for example ``effort``).
    """
    from ravel.workflow import transport_registry as tr
    from ravel.workflow.transports import provider_usage
    wired, excluded = [], []
    for document in tr.all_declarations(installed_only=True):
        try:
            problem = seat_problem(document)
        except (ImportError, OSError, ValueError) as exc:
            problem = 'adapter_error:' + type(exc).__name__
        if problem is None:
            wired.append(document['id'])
            continue
        row = {'transport': document['id'], 'reason': problem}
        rule = LAUNCHER_RESTRICTIONS.get(document.get('launcher'))
        if problem.startswith('launcher:') and rule is not None and not rule['admitted']:
            row['detail'] = rule['reason']
        if document['transport_kind'] in ADMITTED_KINDS:
            row['usage_split'] = provider_usage.split_problem(document)
        excluded.append(row)
    return {'wired': wired, 'excluded': excluded, 'kinds': list(wired_kinds())}


def admitted(transport_ids):
    """The admitted transports of an ordered preference list, and why each other one was dropped."""
    from ravel.workflow import transport_registry as tr
    kept, dropped = [], []
    for transport_id in transport_ids:
        try:
            document = tr.load(transport_id)
        except KeyError:
            dropped.append({'transport': transport_id, 'reason': 'undeclared'})
            continue
        problem = admission_problem(document)
        if problem is None:
            kept.append(transport_id)
        else:
            dropped.append({'transport': transport_id, 'reason': problem})
    return kept, dropped


def preferences(context, card):
    """Selection preferences from the run's frozen agent preferences, restricted to admitted transports."""
    frozen = (context or {}).get('agent_preferences')
    if type(frozen) is not dict or frozen.get('kind') != 'agent-preferences' or frozen.get('schema_version') != 1:
        raise StepHold('agent_preferences_missing', 'intake freezes the operator\'s agent preferences into the run')
    order = frozen.get('transport_preference') or []
    kept, dropped = admitted(order)
    if not kept:
        raise StepHold('no_admitted_transport', 'no transport in the frozen preferences may fill a controller seat',
                       evidence={'dropped': dropped})
    value = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: kept},
             'tier_models': deepcopy(frozen.get('tier_models') or {}),
             'model_families': deepcopy(frozen.get('model_families') or {})}
    from ravel.controller.authority.operator import agent_preference_problems
    try:
        problems = agent_preference_problems(frozen)
    except (OSError, ValueError):
        problems = []  # an unreadable catalogue leaves the label out; it never holds a seat
    if problems:
        # A run-internal label: the operator boundary refuses these, a frozen record only reports them.
        value['catalogue_problems'] = problems
    return value, kept, dropped


def select(card, prefs, *, store, sandbox_fallback=False):
    """The selected transport and model for the card, or a typed hold naming every missing item.

    ``sandbox_fallback`` (the operator's restricted unsandboxed reviewer, decided by the step from the frozen mode)
    lets a qualified restricted CLI worker serve a review seat on a host without the OS worker sandbox; the
    selection then names what the sandbox would have enforced (``sandbox_fallback``).

    Review independence in controller mode is a fresh session, a distinct actor, a RAVEL-built packet
    and confined reads; a second model family is not required. A card's ``distinct_family_from`` is
    therefore no selection constraint here: the family is recorded and labelled at credit. A CLI
    worker's live qualification counts only as the operator-run record in the run's own store
    (``transport_registry.store_qualifications``), never a same-user file (SW09).
    """
    from ravel.workflow import transport_registry as tr
    selectable = deepcopy(card)
    selectable['model'] = {**selectable['model'], 'distinct_family_from': []}
    try:
        selection = tr.select(selectable, prefs, controller=True, qualifications=tr.store_qualifications(store),
                              **({'sandbox_fallback': True} if sandbox_fallback else {}))
    except tr.TransportRefusal as exc:
        transports = (prefs.get('families') or {}).get(card['family']) or []
        raise StepHold('transport_unavailable', str(exc)[:1500], evidence={
            'missing': list(exc.missing),
            # The operator qualifies once, before the run, from their own terminal; later runs adopt it at intake.
            'remedy': [REMEDY.format(transport=t) for t in transports]}) from None
    document = tr.load(selection['transport_id'])
    problem = admission_problem(document)
    if problem is not None:
        raise StepHold('transport_not_admitted', problem)
    if document['transport_kind'] not in wired_kinds():
        raise StepHold('transport_adapter_unavailable', f"{document['transport_kind']} seats have no dispatch "
                       'adapter in this build; order a wired transport first', evidence={'selection': selection})
    problem = seat_problem(document)
    if problem is not None:
        raise StepHold('transport_adapter_unavailable', f"{document['id']} cannot run a governed seat here: {problem}",
                       evidence={'selection': selection, 'reason': problem})
    return selection


def model_matches(requested, observed):
    """The observed model is the requested one (a dated release of the same id counts)."""
    if type(requested) is not str or type(observed) is not str or not requested or not observed:
        return False
    import re
    from ravel.workflow import model_catalogue
    try:
        wanted, served = model_catalogue.lookup(requested), model_catalogue.lookup(observed)
    except (OSError, ValueError):
        wanted = served = None
    if wanted is not None and served is not None and wanted['id'] != served['id']:
        return False
    return observed == requested or re.fullmatch(re.escape(requested) + model_catalogue.VERSION_SUFFIX,
                                                observed) is not None


def model_check(card, dispatch_record, receipt):
    """Requested and observed tier, model and effort for the receipt; a mismatch refuses credit (I08).

    ``tier`` is the tier the model was selected by (``cheap`` for a ``cheap_ok`` card the preferences
    serve cheaply); ``card_tier`` is the card's own tier.
    """
    model = receipt.get('model') or {}
    selection = dispatch_record.get('selection') or {}
    requested = selection.get('model')
    observed = model.get('observed')
    effort = selection.get('effort')
    result = {'tier': selection.get('tier') or card['model']['tier'], 'card_tier': card['model']['tier'],
              'effort_requested': card['model']['effort'], 'effort_launched': effort,
              'model_requested': requested, 'model_observed': observed,
              'matches': model_matches(requested, observed) and effort == card['model']['effort']}
    if not result['matches']:
        result['reason'] = ('model_unobserved' if observed is None else
                            'model_substituted' if not model_matches(requested, observed) else 'effort_substituted')
    return result


def worker_spec(*, node_id, attempt, card, card_sha256, transports, inputs, outputs, budgets, map_id,
                review=None):
    """The dispatcher's versioned spec for one controller seat; the packet is its first pinned input."""
    parent = {'review_point_id': None, 'map_id': map_id, 'rca_ticket': None}
    if review is not None:
        parent = {'review_point_id': review['point_id'], 'map_id': map_id, 'rca_ticket': None,
                  'review_subject': {'scope': review['scope'], 'sha256': review['subject_sha256']}}
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node_id, 'attempt': attempt,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': card_sha256},
            'transport_preference': list(transports), 'inputs': deepcopy(inputs),
            'declared_outputs': deepcopy(outputs), 'budgets': deepcopy(budgets),
            'final_record_schema': CONTROLLER_SCHEMA, 'work_order': None, 'rdj_challenges': None, 'parent': parent}


def fresh_session_errors(receipt, seen_sessions):
    """A seat's session is new: the transport attested it and no earlier receipt of the run used it."""
    errors = []
    if receipt.get('attestation') != 'transport_attested':
        errors.append({'code': 'session_not_attested', 'attestation': receipt.get('attestation'),
                       'reasons': ((receipt.get('transport') or {}).get('observation') or {}).get('attestation_reasons')})
    session = receipt.get('session_id')
    if not session:
        errors.append({'code': 'session_missing'})
    elif session in seen_sessions:
        errors.append({'code': 'session_reused', 'session_id': session})
    return errors
