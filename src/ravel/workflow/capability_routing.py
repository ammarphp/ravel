"""Constructive request recovery using the actual selected package source.

This is planning, not execution admission or parent-goal acceptance. Source is
parsed, never imported to discover engines. Exact component intentions may be
supplied by the host; suggestions from declared mode metadata remain provisional.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

try:
    from .source_syntax import facts as _syntax_facts
    from .operation_definitions import definitions as _chain_definitions, populate_modes as _chain_modes, source_dispatch_enabled
    from .operation_registration import (read_signatures as _read_signatures, registered_rows as _registered_rows,
                                         descriptor_document as _descriptor_document,
                                         executor_document as _executor_document)
except ImportError:  # loaded by file path out of an installed copy, with no parent package
    import importlib.util as _util
    _spec = _util.spec_from_file_location('_ravel_source_syntax', Path(__file__).with_name('source_syntax.py'))
    _syntax = _util.module_from_spec(_spec)
    _spec.loader.exec_module(_syntax)
    _syntax_facts = _syntax.facts
    # Load only the helper adjacent to this trusted loader, never selected-source code.
    _chain_spec = _util.spec_from_file_location('_ravel_operation_definitions',
                                              Path(__file__).with_name('operation_definitions.py'))
    _chain = _util.module_from_spec(_chain_spec)
    _chain_spec.loader.exec_module(_chain)
    _chain_definitions, _chain_modes = _chain.definitions, _chain.populate_modes
    source_dispatch_enabled = _chain.source_dispatch_enabled
    _registration_spec = _util.spec_from_file_location('_ravel_operation_registration',
                                                     Path(__file__).with_name('operation_registration.py'))
    _registration = _util.module_from_spec(_registration_spec)
    _registration_spec.loader.exec_module(_registration)
    _read_signatures, _registered_rows = _registration.read_signatures, _registration.registered_rows
    _descriptor_document, _executor_document = _registration.descriptor_document, _registration.executor_document


def _text(value, name):
    if type(value) is not str or not value.strip():
        raise ValueError(name + ' must be nonblank text')
    return value


def _file(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('source must be a regular file without symlinks: ' + str(path))
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}, raw


def _parsed(path):
    pin, raw = _file(path)
    return pin, ast.parse(raw.decode('utf-8'))


def _literal(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('selected source does not declare ' + name)


DESCRIPTORS = 'data/mode_descriptors.json'
CHAINS = 'data/routing/chains.json'
DESCRIPTOR_FIELDS = ('summary', 'operations', 'tools', 'inputs', 'observables', 'outputs', 'context')
APPLICABILITY_SCOPES = ('general', 'source-bound')


def _applicability(value, mode, modes):
    """A general operation needs no predicate; a source-bound one names what it is bound to and
    the term groups a request must match (every group, any term in it) before it is offered."""
    if type(value) is not dict or value.get('scope') not in APPLICABILITY_SCOPES:
        raise ValueError('applicability requires a general or source-bound scope for mode ' + str(mode))
    if value['scope'] == 'general':
        if set(value) != {'scope'}:
            raise ValueError('a general operation declares no predicate: ' + str(mode))
        return dict(value)
    if set(value) != {'scope', 'bound_to', 'select_when', 'general_operation'}:
        raise ValueError('a source-bound operation requires bound_to, select_when and general_operation: ' + str(mode))
    groups = value['select_when']
    if (type(value['bound_to']) is not str or not value['bound_to'].strip() or type(groups) is not list or not groups
            or any(type(g) is not list or not g or any(type(t) is not str or not t.strip() for t in g) for g in groups)):
        raise ValueError('a source-bound predicate requires nonblank bound_to and term groups: ' + str(mode))
    general = value['general_operation']
    if general is not None and (general not in modes or general == mode):
        raise ValueError('source-bound general_operation must name another registered mode: ' + str(mode))
    return {**value, 'select_when': [list(g) for g in groups]}


def predicate_terms(applicability, text):
    """The matched term of each predicate group, or None when a group is unmatched or the operation
    is general. Identifiers count here: an explicit source or operation name is what selects it."""
    if applicability.get('scope') != 'source-bound':
        return None
    matched = []
    for group in applicability['select_when']:
        hit = next((h for h in (_term_pattern(t).search(text) for t in group) if h), None)
        if hit is None:
            return None
        matched.append(hit.group(0))
    return matched


def _chains(document, modes):
    """Validate declared deliverable chains against the selected dispatcher."""
    if (type(document) is not dict or set(document) != {'schema_version', 'chains'}
            or document['schema_version'] != 1 or type(document['chains']) is not list):
        raise ValueError('routing chains require schema_version 1 and a chains list')
    seen = set()
    for row in document['chains']:
        if (type(row) is not dict or set(row) != {'id', 'requires', 'modes', 'task_fields', 'preconditions'}
                or type(row['id']) is not str or not row['id'].strip() or row['id'] in seen):
            raise ValueError('routing chains require distinct named rows')
        seen.add(row['id'])
        if (type(row['modes']) is not list or not row['modes']
                or any(type(m) is not str or m not in modes for m in row['modes'])
                or len(set(row['modes'])) != len(row['modes'])):
            raise ValueError('routing chain modes must be distinct selected dispatcher modes')
        required = row['requires']
        if (type(required) is not dict
                or set(required) != {'claim_kind', 'artifact', 'template_alternative', 'model_point', 'effect', 'routine'}
                or required != {'claim_kind': 'prediction', 'artifact': 'binned_values',
                                'template_alternative': True, 'model_point': True,
                                'effect': 'generates-events', 'routine': 'not_selected'}):
            raise ValueError('unsupported routing chain obligation requirements')
        fields = row['task_fields']
        if (type(fields) is not dict or set(fields) - set(row['modes'])
                or any(type(v) is not list or not v or any(type(t) is not str or not t.strip() for t in v)
                       for v in fields.values())):
            raise ValueError('routing chain task fields must name declared modes and nonblank fields')
        if (type(row['preconditions']) is not list or not row['preconditions']
                or any(type(p) is not str or not p.strip() for p in row['preconditions'])):
            raise ValueError('routing chain preconditions must be nonblank strings')
    return document['chains']


def _descriptors(document, modes):
    """Declared per-mode vocabulary. Modes without a descriptor stay listed, unmatched."""
    if type(document) is not dict or document.get('schema_version') != 1 or type(document.get('modes')) is not dict:
        raise ValueError('mode descriptors require schema_version 1 and a modes table')
    weights, threshold = document.get('weights'), document.get('threshold')
    if (type(weights) is not dict or set(weights) != set(DESCRIPTOR_FIELDS[2:])
            or any(type(v) is not int or v < 1 for v in weights.values()) or type(threshold) is not int or threshold < 1):
        raise ValueError('mode descriptors require integer category weights and threshold')
    result = {}
    for mode, row in document['modes'].items():
        if type(row) is not dict or set(row) != {*DESCRIPTOR_FIELDS, 'applicability'} or type(row['summary']) is not str:
            raise ValueError('malformed descriptor for mode ' + str(mode))
        if any(type(row[key]) is not list or any(type(t) is not str or not t.strip() for t in row[key])
               for key in DESCRIPTOR_FIELDS[1:]):
            raise ValueError('descriptor terms must be nonblank strings for mode ' + str(mode))
        applicability = _applicability(row['applicability'], mode, document['modes'])
        if mode in modes:
            result[mode] = {**row, 'applicability': applicability, 'weights': dict(weights), 'threshold': threshold}
    return result


def _term_pattern(term):
    """Plain terms match whole words (all-capital terms keep their case); 're:' terms are regexes."""
    if term.startswith('re:'):
        return re.compile(term[3:], re.I)
    body = r'[\s-]+'.join(re.escape(part) for part in re.split(r'[\s-]+', term.strip()))
    flags = 0 if re.search(r'[A-Z]', term) and not re.search(r'[a-z]', term) else re.I
    return re.compile(r'(?<![\w-])' + body + r'(?:e?s)?(?![\w])', flags)


def matching_text(text):
    """Remove quoted identifiers, paths and file names, keeping recognized input artifact types."""
    from ravel.workflow.intake import strip_locations
    return strip_locations(re.sub(r'`[^`\n]*`|"[^"\n]*"|“[^”\n]*”', ' ', text))


def suggest(prompt, by_mode, *, kind=None, operation=None):
    """Rank modes by their declared tools, inputs, observables and outputs in the request."""
    from ravel.workflow.intake import actionable_text, routing_text
    request = actionable_text(routing_text(prompt))
    active = matching_text(request)
    ranked = []
    for order, (mode, row) in enumerate(by_mode.items()):
        descriptor = row.get('descriptor')
        if not descriptor:
            continue
        matched, score = {}, 0
        applicability = descriptor.get('applicability', {'scope': 'general'})
        if applicability['scope'] == 'source-bound':
            # A source-bound adapter is never offered as a general operation.
            selected = predicate_terms(applicability, request)
            if selected is None:
                continue
            matched['applicability'] = selected
            score += descriptor['threshold']
        for category in DESCRIPTOR_FIELDS[2:]:
            for term in descriptor[category]:
                hit = _term_pattern(term).search(active)
                if hit:
                    matched.setdefault(category, []).append(hit.group(0))
                    score += descriptor['weights'][category]
        if operation and operation in descriptor['operations']:
            score += descriptor['threshold']; matched.setdefault('operations', []).append(operation)
        elif kind and kind in descriptor['operations'] and matched:
            score += 1; matched.setdefault('operations', []).append(kind)
        # Context words only support a declared tool, input, observable, output or operation.
        if score >= descriptor['threshold'] and set(matched) - {'context'}:
            ranked.append((-score, order, mode, matched, descriptor['summary'], applicability))
    return [{'mode': mode, 'score': -negative, 'matched': matched, 'summary': summary, 'applicability': applicability}
            for negative, _, mode, matched, summary, applicability in sorted(ranked)[:MAX_SUGGESTIONS]]


def screen_intents(prompt, intents, by_mode):
    """Split host intents into offered and withheld ones by each operation's applicability.

    A host may name any registered mode, but a source-bound one stays withheld unless the
    original request matches its predicate; the withheld row names the general operation.
    """
    from ravel.workflow.intake import actionable_text, routing_text
    request = actionable_text(routing_text(prompt))
    offered, withheld = [], []
    for intent in intents:
        descriptor = (by_mode.get(intent['mode']) or {}).get('descriptor') or {}
        applicability = descriptor.get('applicability', {'scope': 'general'})
        if applicability['scope'] == 'source-bound' and predicate_terms(applicability, request) is None:
            withheld.append({'mode': intent['mode'], 'selection': 'withheld_source_bound_predicate_unmatched',
                             'bound_to': applicability['bound_to'],
                             'general_operation': applicability['general_operation']})
        else:
            offered.append(intent)
    return offered, withheld


MAX_SUGGESTIONS = 8
_DECLARED = None


def declared_descriptors():
    """The packaged mode descriptors as a by-mode table for `suggest`, read once.

    This ranks hints only; `catalogue()` remains the source authority that checks
    each mode against the current dispatcher before a candidate is presented.
    """
    global _DECLARED
    if _DECLARED is None:
        package = Path(__file__).resolve().parents[1]
        document = json.loads((package / DESCRIPTORS).read_text(encoding='utf-8'))
        document = _descriptor_document(document, _read_signatures(package / 'data/operation_signatures.json'))
        rows = _descriptors(document, set(document.get('modes', {})))
        _DECLARED = {mode: {'mode': mode, 'descriptor': row} for mode, row in rows.items()}
    return _DECLARED


def catalogue(source_root=None):
    """Read current mode/dispatch contracts; no native, SDK or provider imports."""
    if source_root:
        root = Path(source_root).absolute()
        package = root / 'src/ravel'
    else:
        # The imported package is the source authority in both a checkout and
        # an installed wheel. An installation does not contain a src/ tree.
        package = Path(__file__).resolve().parents[1]
        root = package.parent.parent if package.parent.name == 'src' else package.parent
    science_pin, tree = _parsed(package / 'workflow/science.py')
    modes = _literal(tree, 'MODES')
    signatures, registration_pins = {}, {}
    signature_path = package / 'data/operation_signatures.json'
    chain_enabled = (package / 'workflow/operation_definitions.py').is_file() and source_dispatch_enabled(tree)
    if chain_enabled and (signature_path.exists() or signature_path.is_symlink()):
        signature_pin, signature_raw = _file(signature_path)
        signatures = _read_signatures(signature_path, raw=signature_raw)
        registration_pins[signature_pin['path']] = signature_pin
        if _registered_rows(signatures):
            registration_pin, _ = _file(package / 'workflow/operation_registration.py')
            registration_pins[registration_pin['path']] = registration_pin
    # Read declarations from the selected source, retaining source-only discovery.
    # Older source trees without the chain seam keep their literal dispatcher.
    chain_definitions, chain_pins = {}, {}
    if chain_enabled:
        executor_pin, executor_raw = _file(package / 'data/roles/executors.json')
        helper_pin, helper_raw = _file(package / 'workflow/operation_definitions.py')
        helper_tree = ast.parse(helper_raw.decode('utf-8'))
        compatibility = (_literal(helper_tree, 'LEGACY_BINDINGS') if any(
            isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LEGACY_BINDINGS'
                                                for t in node.targets) for node in helper_tree.body) else {})
        executors = _executor_document(json.loads(executor_raw), signatures)['operations']
        chain_definitions = _chain_definitions(signatures, executors, compatibility)
        modes = _chain_modes(modes, signatures, executors, compatibility)
        chain_pins = {pin['path']: pin for pin in (executor_pin, helper_pin)}
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'adapter')
    mapping, variants = {}, {}
    def literal_module(expression, mode):
        # Resolve the finite literal mode-derived import used by the real
        # dispatcher. Never evaluate Python or import a module for discovery.
        if isinstance(expression, ast.Constant) and type(expression.value) is str:
            return expression.value
        if (isinstance(expression, ast.Subscript) and isinstance(expression.value, ast.Name)
                and expression.value.id == 'spec' and isinstance(expression.slice, ast.Constant)
                and expression.slice.value == 'mode'):
            return mode
        if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add):
            left, right = literal_module(expression.left, mode), literal_module(expression.right, mode)
            return left + right if left is not None and right is not None else None
        if (isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute)
                and expression.func.attr == 'replace' and not expression.keywords
                and len(expression.args) == 2
                and all(isinstance(a, ast.Constant) and type(a.value) is str for a in expression.args)):
            value = literal_module(expression.func.value, mode)
            return value.replace(*(a.value for a in expression.args)) if value is not None else None
        return None
    for node in ast.walk(function):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(value, ast.Constant) and type(key.value) is str and type(value.value) is str:
                    if key.value in modes:
                        mapping[key.value] = value.value
                    elif (package / ('physics/' + value.value + '.py')).is_file():
                        variants[key.value] = value.value
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            # Literal special-mode imports in the actual dispatch function.
            tests = [x.value for x in ast.walk(node.test) if isinstance(x, ast.Constant) and type(x.value) is str]
            for mode in tests:
                if mode not in modes:
                    continue
                for child in node.body:
                    if isinstance(child, ast.Return) and isinstance(child.value, ast.Call):
                        args = child.value.args
                        selected = literal_module(args[0], mode) if args else None
                        if selected is not None and selected.startswith('ravel.'):
                            mapping[mode] = selected.removeprefix('ravel.')
                    if isinstance(child, ast.ImportFrom) and child.module == 'ravel.physics':
                        mapping[mode] = child.names[0].name
    mapping.update({'analyze': 'existing_events', 'quantities': 'quantities'})
    mapping.update({name: row['implementation']['module'].removeprefix('ravel.')
                    for name, row in chain_definitions.items()})
    operations = []
    source_pins = {science_pin['path']: science_pin, **registration_pins, **chain_pins}

    def implementation(name):
        relative = name.replace('.', '/') if '/' in name or '.' in name else 'physics/' + name
        path = package / (relative + '.py')
        if not path.is_file():
            return {'status': 'source_dispatch_unresolved', 'module': 'ravel.' + relative.replace('/', '.')}
        pin, raw = _file(path); source_pins[pin['path']] = pin
        contract, names, _ = _syntax_facts(raw, filename=str(path))
        functions = set(names)
        return {'status': 'source_present_not_admitted', 'module': 'ravel.' + relative.replace('/', '.'),
                'source': pin, 'entrypoints': sorted(functions & {'validate', 'inputs', 'run'}),
                'contract': contract, 'execution_evidence': 'not_inferred_from_source'}

    for mode in modes:
        row = {'mode': mode, 'dispatch_source': science_pin, **implementation(mapping.get(mode, '__unresolved__'))}
        if mode == 'analyze':
            row['variants'] = {name: implementation(module) for name, module in sorted(variants.items())}
            # existing_events validates these literal alternatives itself.
            row['existing_event_backend_contract'] = row.get('source')
        operations.append(row)
    native_pin, native_tree = _parsed(package / 'physics/native_capabilities.py')
    source_pins[native_pin['path']] = native_pin
    native = _literal(native_tree, 'CAPABILITIES')
    from ravel.physics.native_capabilities import discover_capabilities
    native.update(discover_capabilities())
    # A source tree without declared descriptors still lists every mode, unmatched.
    descriptors = {}
    if (package / DESCRIPTORS).exists():
        descriptor_pin, descriptor_raw = _file(package / DESCRIPTORS)
        source_pins[descriptor_pin['path']] = descriptor_pin
        descriptors = _descriptors(_descriptor_document(json.loads(descriptor_raw.decode('utf-8')), signatures), modes)
    for row in operations:
        row['descriptor'] = descriptors.get(row['mode'])
    chains = []
    planning_tools = []
    if (package / CHAINS).exists():
        chain_pin, chain_raw = _file(package / CHAINS)
        source_pins[chain_pin['path']] = chain_pin
        cli_pin, cli_tree = _parsed(package / 'cli.py')
        source_pins[cli_pin['path']] = cli_pin
        commands = _literal(cli_tree, 'FOCUSED_COMMANDS')
        chains = _chains(json.loads(chain_raw.decode('utf-8')), set(modes) | set(commands))
        tool_modes = dict.fromkeys(mode for chain in chains for mode in chain['modes'] if mode not in modes)
        for mode in tool_modes:
            module, summary = commands[mode]
            planning_tools.append({'mode': mode, 'dispatch_source': cli_pin, 'dispatch_surface': 'focused-command',
                                   'command': 'ravel ' + mode, 'summary': summary, **implementation(module)})
    for relative in ('workflow/intake.py', 'workflow/route_prompt.py', 'workflow/cost_preflight.py',
                     'validation/validate_task_contract.py', 'workflow/resource_census.py', 'workflow/routine_fetch.py',
                     'plotting/figure_target.py', 'plotting/figure_manifest.py',
                     'plotting/science_figures.py', 'analysis_catalog.py'):
        pin, _ = _file(package / relative); source_pins[pin['path']] = pin
    return {'schema_version': 1, 'kind': 'capability-source-catalogue', 'source_root': str(root),
            'operations': operations, 'planning_tools': planning_tools, 'declared_chains': chains,
            'native_compatibility_registry': native,
            'source_pins': sorted(source_pins.values(), key=lambda p: p['path']),
            'scope': 'Current source contracts only. Registration, file presence and catalogue counts do not establish runtime or scientific qualification.',
            'compute_authorized': False, 'physics_validated': False}


def _span(value, prompt):
    if type(value) is not dict or set(value) != {'start', 'end', 'text'}:
        raise ValueError('intent basis requires start, end, text')
    start, end = value['start'], value['end']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(prompt) or prompt[start:end] != value['text']:
        raise ValueError('intent basis must match the original request exactly')


def _action(stage, tool, purpose):
    return {'stage': stage, 'tool': tool, 'purpose': purpose, 'compute_authorized': False}


def _chain_candidates(contract, reading, catalog, by_mode, findings):
    """Compose obligation-shaped candidates, never infer a reusable routine's absence.

    Intake has no completed routine-search or generation-effect census. A model
    point prediction without supplied events can therefore propose the whole
    chain, but its generation and routine-reuse conditions remain unresolved for
    host review. A declared generation stage resolves only the planning effect;
    no candidate grants execution or scientific admission.
    """
    obligations = contract.get('task_requirements', {}).get('obligations', [])
    criteria = [o.get('criteria', {}) for o in obligations]
    # A single deliverable may be represented by the whole-request obligation.
    outputs = [{'claim_kind': d.get('claim_kind'), 'artifact': d.get('artifact', {}).get('kind')}
               for d in reading.get('deliverables', [])]
    outputs += [c for c in criteria if 'claim_kind' in c]
    constraints = reading.get('constraints', [])
    template = any(c.get('constraint') == 'template' for c in criteria) or any(
        c.get('type') == 'template' for c in constraints)
    stages = {c.get('value', {}).get('stage') for c in constraints if c.get('type') == 'requested_stage'}
    negated = {c.get('value', {}).get('stage') for c in constraints if c.get('type') == 'negated_stage'}
    supplied = any(f.get('type') == 'supplied_input' and f.get('value', {}).get('artifact') in
                   ('event_sample', 'events', 'lhe', 'hepmc', 'ntuples', 'reconstructed_events')
                   for f in reading.get('facts', []))
    point = bool(contract.get('targets', {}).get('masses_gev')) or any(
        f.get('type') == 'mass' for f in reading.get('facts', []))
    result = []
    for chain in catalog.get('declared_chains', []):
        required = chain['requires']
        prediction = any(o.get('claim_kind') == required['claim_kind'] and
                         (o.get('artifact') == required['artifact'] or template and required['template_alternative'])
                         for o in outputs)
        if (not prediction or not point or supplied or negated & {'generation', 'shower', 'detector'}
                or any(o.get('claim_kind') in ('exclusion', 'finding', 'document') for o in outputs)):
            continue
        conditions = {'generation_effect': 'requested' if 'generation' in stages else 'unresolved_requires_host_review',
                      'routine_reuse': 'reported_no_routine' if any(type(f) is dict and f.get('kind') == 'no-routine' for f in findings)
                                      else 'unresolved_requires_resource_census'}
        for index, mode in enumerate(chain['modes']):
            result.append({'mode': mode, 'scope': 'component', 'chain': chain['id'], 'chain_step': index + 1,
                           'selection': 'declared_chain_requires_host_review',
                           'obligation_ids': [o['id'] for o in obligations if o.get('kind') == 'deliverable'],
                           'conditions': dict(conditions), 'preconditions': list(chain['preconditions']),
                           'required_task_fields': list(chain['task_fields'].get(mode, [])),
                           'operation': by_mode[mode]})
    return result


def _retrieve_action(reading):
    """Restrict bulk value/figure acquisition through the shared source-policy seam."""
    from .source_policy import from_reading
    restrictions = from_reading(reading)
    if not restrictions:
        return _action('retrieve', 'ravel.workflow.hepdata_fetch; ravel.plotting.fetch_figures',
                       'Read public model, likelihood, response, cards, tables, figures and code; record missing or private inputs explicitly.')
    action = _action('retrieve', 'ravel.workflow.source_policy.read_receipt; policy-screened source retrieval',
                     'Check the declared restrictions before acquisition or value extraction. Public bibliographic metadata, '
                     'source definitions, code and bin definitions remain candidates only where the policy allows them; '
                     'restricted values cannot supply the requested prediction. Record missing or private inputs explicitly.')
    action['source_restrictions'] = restrictions
    action['restricted_tools'] = ['ravel.workflow.hepdata_fetch', 'ravel.plotting.fetch_figures']
    action['public_metadata'] = 'Bibliographic identifiers and resource locations, subject to the same source policy.'
    return action


PARENT_ROUTES = {
    'research': ('ravel research-orchestrate prepare/run; actual bounded whole-goal Host/Graph coordinator',
                 'Present the exact original-task assignment and unchanged scientific mode to the research coordinator. '
                 'It prepares actual context, inputs and bounded ordinary child studies; a draft proposal does not close the parent goal.'),
    'calculation': ('ravel intake-plan prepare/graph-spec; actual bounded Host/Graph intake-plan tool',
                    'Present the exact original calculation to the intake planner. It prepares an ordinary scientific '
                    'child or source development; a draft proposal does not close the parent goal.'),
    'operation': ('ravel plan --spec with a declared candidate mode; ravel intake-plan for a choice between candidates',
                  'Prepare a typed specification for the named operation from its declared candidate modes and the '
                  'actual supplied inputs, and present it as CHECK-IN 1. Unserved parts of the request stay explicit.'),
    'open': ('inputs/reading.json and the draft plan; ravel plan --spec per component; ravel research-orchestrate for open research',
             'Compose the whole request from the operation catalogue. Each requested stage, tool, deliverable and '
             'constraint is an obligation of the census; components run as ordinary children with their own CHECK-IN 1.'),
    'checkin': ('ravel.workflow.resource_census; ravel.workflow.routine_fetch; docs/workflow/steps/02-inputs.md; '
                'docs/workflow/checklists/check-ins.md',
                'Resolve inputs with the step-2 resource census and route analysis, then prepare, validate and present '
                'CHECK-IN 1 in this run directory before any generation.'),
}


FINDINGS = {'no-routine', 'shape-model', 'missing-likelihood', 'off-grid', 'missing-public-input',
            'private-unavailable-input', 'outage', 'no-adapter', 'model-ambiguity', 'optional-figure'}


def plan(prompt, *, contract=None, intents=(), findings=(), source_root=None, reading=None):
    """Return candidates and concrete next operations without replacing the request.

    intents: {mode, basis:{start,end,text}, scope:'component'|'whole_request'}.
    findings: {kind, detail, evidence:[{path,sha256}, ...]}; they are supplied
    findings, never assertions deduced from an absent file or empty search.
    """
    _text(prompt, 'original request')
    findings = tuple(findings)
    if contract is None:
        from ravel.workflow.route_prompt import route
        contract = route(prompt)
    if type(contract) is not dict or contract.get('prompt') != prompt:
        raise ValueError('routing contract must preserve the exact original request')
    catalog = catalogue(source_root)
    by_mode = {row['mode']: row for row in catalog['operations']}
    chain_by_mode = {**by_mode, **{row['mode']: row for row in catalog.get('planning_tools', [])}}
    if reading is None:
        from ravel.workflow.request_reading import document
        reading = document(prompt)
    candidates = []
    for intent in intents:
        if type(intent) is not dict or set(intent) != {'mode', 'basis', 'scope'} or intent['scope'] not in ('component', 'whole_request'):
            raise ValueError('intent requires mode, located basis and declared component/whole_request scope')
        _span(intent['basis'], prompt)
        if intent['mode'] not in by_mode:
            raise ValueError('intent mode is absent from selected current science source; retain it as an unmet requirement')
    intents, withheld = screen_intents(prompt, list(intents), by_mode)
    for intent in intents:
        candidates.append({'mode': intent['mode'], 'basis': intent['basis'], 'scope': intent['scope'],
                           'selection': 'grounded_host_candidate_not_admitted', 'operation': by_mode[intent['mode']]})
    chain_candidates = _chain_candidates(contract, reading, catalog, chain_by_mode, findings)
    for candidate in chain_candidates:
        host = next((c for c in candidates if c['mode'] == candidate['mode']), None)
        if host:
            candidate['host_intent'] = {key: host[key] for key in ('basis', 'scope', 'selection')}
    chain_modes = {c['mode'] for c in chain_candidates}
    candidates = chain_candidates + [c for c in candidates if c['mode'] not in chain_modes]
    from ravel.workflow.intake import (actionable_text, routing_text, handoff_route, requests_discovery,
                                       prospective_significance_request)
    active = actionable_text(routing_text(prompt))
    intake_record = contract.get('intake', {})
    for row in suggest(prompt, by_mode, kind=intake_record.get('kind', contract.get('task_mode')),
                       operation=intake_record.get('operation')):
        if not any(c['mode'] == row['mode'] for c in candidates):
            terms = '; '.join(f"{category}: {', '.join(values)}" for category, values in row['matched'].items())
            candidates.append({'mode': row['mode'], 'scope': 'component',
                               'selection': 'declared_metadata_match_requires_host_review',
                               'score': row['score'], 'matched': row['matched'],
                               'reason': row['summary'] + ' Matched declared ' + terms + '. Inspect the adapter contract before choosing it.'
                                         + (' Source-bound to ' + row['applicability']['bound_to'] + '; it is not a general operation.'
                                            if row['applicability']['scope'] == 'source-bound' else ''),
                               'applicability': row['applicability'],
                               'operation': by_mode[row['mode']]})
    prospective = prospective_significance_request(active)
    forbidden = requests_discovery(active)
    held_by_boundary = contract.get('task_mode') == 'unsupported' and any(
        row['class'] in ('unsupportable_claim', 'inaccessible_input', 'contradiction') for row in reading['boundaries'])
    status = ('claim_boundary' if forbidden or held_by_boundary else
              'needs_intent_resolution' if contract.get('task_mode') == 'unsupported' else
              'open_parent' if handoff_route(contract, reading) == 'open' else 'draft_route_requires_admission')
    actions = [_action('discover', 'ravel analyses list/show; ravel.workflow.resource_census',
        'Search analysis identities, publication/source resources and tool catalogues across the whole requested scope; empty vocabulary results and outages are not absence.'),
        _retrieve_action(reading),
        _action('resolve', 'grounded intake --interpretation; current scientific adapter validate/inputs',
        'Resolve the original intent and inspect exact candidate contract/input semantics. A component route does not replace generation, reinterpretation, scan or parent delivery.'),
        _action('reuse-or-adapt', 'ravel analyses assess/adapt; analyze native-construction/routine-build; source-backed model/statistical adapters',
        'Reuse compatible existing evidence or construct a declared source successor for an actual gap; preserve scientific assumptions and all unresolved requirements.'),
        _action('qualify', 'ravel plan --spec; ordinary approval/run/review',
        'Prepare the smallest relevant prospective qualification with actual inputs/runtime/source and validation checks; run only within existing valid authorization or a required concrete compute approval.'),
        _action('place-execution', 'ravel backend doctor/prepare; stage_supervisor --backend-plan; ravel partitions; ravel site doctor; ravel ntuples resolve/normalize',
        'Choose where approved stages run: native, a digest-pinned podman container for Linux-only engines, a Magnus site or HTCondor/SLURM. Split large input populations into checked partitions. Approvals and the one-local-job lease are unchanged.')]
    route = handoff_route(contract, reading)
    if route:
        parent_api, purpose = PARENT_ROUTES[route]
        actions.insert(0, _action('prepare-parent', parent_api, purpose))
    checked_findings = []
    for finding in findings:
        if type(finding) is not dict or set(finding) != {'kind', 'detail', 'evidence'} or finding['kind'] not in FINDINGS:
            raise ValueError('unknown or malformed recovery finding')
        _text(finding['detail'], 'finding detail')
        if type(finding['evidence']) is not list:
            raise ValueError('finding evidence must be a list of file pins')
        for pin in finding['evidence']:
            if type(pin) is not dict or set(pin) != {'path', 'sha256'} or _file(pin['path'])[0] != pin:
                raise ValueError('finding evidence must bind unchanged exact regular-file bytes')
        checked_findings.append(dict(finding))
        kind = finding['kind']
        if kind == 'private-unavailable-input':
            actions.append(_action('input-held', 'request owner-supplied data or explicitly consented alternative premise',
                'Private unavailable data cannot be reconstructed by inventing efficiencies/covariance. The original quantitative obligation remains unmet; independent public work may continue.'))
        elif kind == 'off-grid':
            actions.append(_action('adapt', 'source-bound model/response generation and per-point statistical admission',
                'Outside a published map forbids unsupported interpolation/extrapolation, not a new model-point study. Keep exact requested coordinates; acquire/qualify missing response and compare references only within their domain.'))
        elif kind in ('shape-model', 'missing-likelihood'):
            actions.append(_action('adapt', 'published/native/HS3 or explicit custom model contract',
                'Inspect full channels, modifiers, overlap, interference and source data. Refuse an incompatible adapter; keep the requested fit pending while testing a compatible source-backed alternative.'))
        elif kind == 'outage':
            actions.append(_action('retrieve', 'retained source/cache or independent official source', 'Unreachable data is unknown, never evidence that no resource exists.'))
        elif kind == 'optional-figure':
            actions.append(_action('deliver-partial', 'current numeric/table/figure contracts and compatible renderer',
                'Preserve checked numbers and geometry; inspect a compatible plotting fallback. Requested missing styling or figures stay unmet and no new inference is created.'))
        else:
            actions.append(_action('adapt', 'actual source/API inspection and bounded source construction', finding['detail']))
    if forbidden:
        actions.insert(0, _action('claim-held', 'preserve original goal and explain exact evidence/data boundary',
            'No unsupported observed discovery claim. Do not rewrite the request as exclusion; any alternative is separate partial work requiring its own appropriate premise.'))
    if prospective:
        actions.insert(0, _action('design', 'source-backed significance/statistical-model qualification',
            'Keep prospective significance/discovery-reach as the requested metric; expected CLs is a different quantity. No current source presence establishes a calibrated 5-sigma calculation.'))
    return {'schema_version': 1, 'kind': 'capability-recovery-plan', 'original_request': prompt,
        'original_request_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'classification_status': status,
        'legacy_draft': contract, 'capability_catalogue': catalog, 'candidates': candidates,
        'withheld_candidates': withheld,
        'findings': checked_findings, 'next_actions': actions,
        'prospective_significance': prospective, 'parent_goal_replaced': False,
        'parent_goal_acceptance': 'not_assessed', 'compute_authorized': False, 'physics_validated': False}


def assess_candidate(prompt, intent, specification, *, base_dir):
    """Connect a resolved component to ordinary validation/input preparation.

    This explicit caller operation invokes the existing adapter's metadata
    validation, never its run function or science.plan. It creates no run or
    approval. Some input inventories inspect large supplied closures, so callers
    retain their normal read/time budget. Errors remain recoverable component
    outcomes, not parent-goal refusals.
    """
    recovery = plan(prompt, intents=[intent])
    if type(specification) is not dict or specification.get('mode') != intent['mode']:
        raise ValueError('explicit scientific specification must match the grounded component mode')
    from ravel.workflow import science
    source, _ = _file(science.__file__)
    catalog_source = recovery['capability_catalogue']['operations'][0]['dispatch_source']
    if source != catalog_source:
        raise ValueError('loaded scientific dispatcher differs from the inspected source')
    outcome = {'kind': 'candidate-input-preparation', 'original_request_sha256': recovery['original_request_sha256'],
               'scope': intent['scope'], 'mode': intent['mode'], 'dispatcher': source,
               'compute_authorized': False, 'physics_validated': False, 'parent_goal_acceptance': 'not_assessed'}
    try:
        science.validate(specification)
        paths = science.task_inputs(specification, Path(base_dir))
        outcome.update(status='specification_and_inputs_checked', inputs=[_file(path)[0] for path in paths],
                       next_action='Prepare the ordinary exact-source runtime/check/budget plan; no execution approval is inferred.')
    except (OSError, ValueError) as exc:
        outcome.update(status='needs_input_or_adapter_repair', reason=str(exc), inputs=[],
                       next_action='Retrieve missing inputs or prepare a compatible source successor; retain the original obligation.')
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt-file', required=True, type=Path)
    parser.add_argument('--intents', type=Path)
    parser.add_argument('--findings', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    from ravel.workflow.state_io import read_json
    result = plan(args.prompt_file.read_text(), intents=read_json(args.intents) if args.intents else (),
                  findings=read_json(args.findings) if args.findings else (), source_root=args.source_root)
    text = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x') as stream:
            stream.write(text)
    else:
        print(text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
