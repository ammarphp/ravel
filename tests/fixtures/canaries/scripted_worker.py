"""Inert scripted worker for the canaries: a stand-in for a model CLI that never calls a model.

The canary harness installs this file as the executable of the restricted CLI worker transport,
with ``script.json`` beside it. On the governed dispatch path it behaves like the CLI: it reads
the RAVEL-built packet on standard input, starts the broker MCP server named in ``--mcp-config``
(``initialize``, ``tools/list``), writes the step's declared outputs in its workspace and prints
the CLI's final JSON envelope whose ``structured_output`` is the final record.

What it writes comes from the first rule in ``script.json`` that matches the packet (step id
pattern, role, step kind, judgment phase). The final record is generated from the packet's output
schema, then the rule's ``final`` fields are laid over it, then the acknowledgement is filled:
``instruction_ack.manifest_sha256`` and one ``checklist`` row per duty unit of the packet. A rule
can misbehave on purpose (omit acknowledgement rows, raise an escalation, write an extra output,
skip a declared output, drop a framed deliverable); the canary's oracle never trusts this
worker's own log (``scratch/canary-worker.json``) and reads the controller's records instead.

Content generators (``"$gen": name``) build documents from the worker's own inputs: the question
frame from the reading, the judgment plan from the frame, attacks on the drafted result, a toy
observable table (with the governed inputs it was computed from, when the rule asks for provenance),
a toy normalization ledger with the yields it delivers, and a trap sweep. Standard library only: this
file runs inside the worker sandbox.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

PACKET_FORMAT = 'ravel-instruction-packet-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


# ---- the packet -------------------------------------------------------------------------------

def _between(text, start, end):
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i)
    return text[i:j if j >= 0 else len(text)]


def parse_packet(text):
    """The parts of a RAVEL instruction packet the worker answers; missing parts stay None."""
    packet = {'format': PACKET_FORMAT if text.startswith(PACKET_FORMAT) else None, 'step': {}, 'role': None,
              'manifest_sha256': None, 'duty_units': [], 'schema_id': None, 'schema': None, 'inputs': []}
    match = re.search(r'manifest sha256: ([0-9a-f]{64})', text)
    packet['manifest_sha256'] = match.group(1) if match else None
    match = re.search(r'^step: (\S+)\s+role: (\S+)', text, re.M)
    if match:
        packet['role'] = None if match.group(2) == '-' else match.group(2)
    block = _between(text, '== Step specification (step.v1) ==\n', '\n\n== ')
    try:
        packet['step'] = json.loads(block) if block else {}
    except ValueError:
        packet['step'] = {}
    block = _between(text, '== Output contract ==\n', '\n\n== ')
    if block:
        first, _, rest = block.partition('\n')
        packet['schema_id'] = first.removeprefix('schema: ').strip() or None
        try:
            packet['schema'] = json.loads(rest)
        except ValueError:
            packet['schema'] = None
    block = _between(text, '== Inputs (by digest) ==\n', '\n\n')
    for line in (block or '').splitlines():
        if line.startswith('- {'):
            try:
                packet['inputs'].append(json.loads(line[2:]))
            except ValueError:
                pass
    duty = _between(text, '== Duty units', '\n== Context units') or ''
    packet['duty_units'] = re.findall(r'^--- \[duty\] (\S+) (?:index:\d+|sha256:)', duty, re.M)
    return packet


# ---- schema-driven filling --------------------------------------------------------------------

def _resolve(schema, root):
    while isinstance(schema, dict) and isinstance(schema.get('$ref'), str) and schema['$ref'].startswith('#/'):
        node = root
        for token in schema['$ref'][2:].split('/'):
            node = node.get(token, {}) if isinstance(node, dict) else {}
        schema = node
    return schema if isinstance(schema, dict) else {}


def instance(schema, root=None, depth=0):
    """A minimal value that the schema accepts for the common keywords (required properties only)."""
    root = schema if root is None else root
    schema = _resolve(schema, root)
    if depth > 12:
        return None
    if 'const' in schema:
        return schema['const']
    if schema.get('enum'):
        return schema['enum'][0]
    for key in ('anyOf', 'oneOf'):
        if schema.get(key):
            options = [_resolve(o, root) for o in schema[key]]
            preferred = next((o for o in options if o.get('type') == 'null'), options[0])
            return instance(preferred, root, depth + 1)
    if schema.get('allOf'):
        merged = {}
        for part in schema['allOf']:
            value = instance(part, root, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    kind = schema.get('type')
    if isinstance(kind, list):
        kind = 'null' if 'null' in kind else kind[0]
    if kind == 'object' or (kind is None and 'properties' in schema):
        props = schema.get('properties') or {}
        return {name: instance(props.get(name, {}), root, depth + 1) for name in schema.get('required') or ()}
    if kind == 'array':
        return [instance(schema.get('items') or {}, root, depth + 1) for _ in range(schema.get('minItems') or 0)]
    if kind == 'string':
        return 'fictional canary value'[:max(schema.get('maxLength') or 64, 1)]
    if kind == 'integer':
        return max(int(schema.get('minimum') or 0), 0)
    if kind == 'number':
        return float(schema.get('minimum') or 0)
    if kind == 'boolean':
        return False
    return None


def overlay(base, extra):
    if isinstance(base, dict) and isinstance(extra, dict):
        result = dict(base)
        for key, value in extra.items():
            result[key] = overlay(base.get(key), value)
        return result
    return extra


# ---- inputs and generators --------------------------------------------------------------------

def _input_documents(workspace):
    documents = []
    base = Path(workspace) / 'inputs'
    for path in sorted(base.rglob('*.json')) if base.is_dir() else ():
        try:
            documents.append((path, json.loads(path.read_text())))
        except (OSError, ValueError):
            continue
    return documents


def _find(documents, predicate):
    for path, value in documents:
        if predicate(path, value):
            return path, value
    return None, None


def _search_key(value, key):
    if isinstance(value, dict):
        if isinstance(value.get(key), str):
            return value[key]
        for child in value.values():
            found = _search_key(child, key)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _search_key(child, key)
            if found:
                return found
    return None


def gen_question_frame(rule, documents, packet):
    _, reading = _find(documents, lambda p, v: isinstance(v, dict) and isinstance(v.get('deliverables'), list)
                       and v.get('kind') != 'question-frame')
    request_sha = next((s for _, v in documents for s in [_search_key(v, 'request_sha256')] if s), '0' * 64)
    deliverables = []
    for row in (reading or {}).get('deliverables') or ():
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        deliverables.append({'id': re.sub(r'[^A-Za-z0-9_-]', '-', row['id'])[:64] or 'D1', 'reading_ref': row['id'],
                             'description': str(row.get('description') or row.get('quantity') or row['id']),
                             'acceptance': rule.get('acceptance', 'value with its uncertainty, reproduced twice'),
                             'statistic': row.get('statistic') if isinstance(row.get('statistic'), str) else None,
                             'units': row.get('units') if isinstance(row.get('units'), str) else None})
    if not deliverables:
        deliverables = [{'id': 'D1', 'reading_ref': None, 'description': 'the requested fictional quantity',
                         'acceptance': 'value with its uncertainty', 'statistic': None, 'units': None}]
    drop = int(rule.get('drop_deliverables', 0))
    if drop:
        deliverables = deliverables[drop:] or deliverables[:0]
    frame = {'schema_version': 1, 'kind': 'question-frame', 'request_sha256': request_sha,
             'objective': rule.get('objective', 'Answer the fictional question with a reviewed value.'),
             'deliverables': deliverables, 'constraints': rule.get('constraints', []),
             'unknowns': rule.get('unknowns', []),
             'assumptions': rule.get('assumptions', [{'number': 1, 'statement': 'The toy model is exact at tree level.',
                                                      'basis': 'stated in the request', 'physics_critical': False}]),
             'boundaries': rule.get('boundaries', [])}
    return frame


def _input_pins(packet):
    """``artifact -> {path, sha256}``: the run pins of the step's own governed inputs that carry a digest."""
    pins = {}
    for row in (packet.get('step') or {}).get('inputs') or ():
        artifact, sha = (row.get('artifact'), row.get('sha256')) if isinstance(row, dict) else (None, None)
        if isinstance(artifact, str) and isinstance(sha, str):
            path = 'steps/' + artifact.replace(':', '/', 1) if ':' in artifact else artifact
            pins[artifact] = {'path': path, 'sha256': sha}
    return pins


def _bind_inputs(value, pins):
    """Replace each ``{"$input": <pattern>}`` with the pin of the one step input whose artifact matches it; a
    check input field whose pattern matches no input (or several) is left out, so its validator says so."""
    if isinstance(value, dict) and set(value) == {'$input'}:
        found = [pin for artifact, pin in pins.items() if re.search(value['$input'], artifact)]
        return dict(found[0]) if len(found) == 1 else None
    if isinstance(value, dict):
        bound = {key: _bind_inputs(child, pins) for key, child in value.items()}
        return {key: child for key, child in bound.items() if child is not None}
    if isinstance(value, list):
        return [_bind_inputs(child, pins) for child in value]
    return value


def gen_judgment_plan(rule, documents, packet):
    # The adopted frame travels in the planner's declared context (``schema: judgment-plan.v1``, ``frame``); a
    # separately staged frame document is the fallback for a planner context that carries none.
    _, context = _find(documents, lambda p, v: isinstance(v, dict) and v.get('schema') == 'judgment-plan.v1'
                       and isinstance(v.get('frame'), dict))
    frame = (context or {}).get('frame')
    if not frame:
        _, frame = _find(documents, lambda p, v: isinstance(v, dict) and v.get('kind') == 'question-frame')
    frame = frame or {}
    template = json.loads(json.dumps(rule.get('plan', {})))
    steps = template.get('steps') or []
    # Validator inputs that name one of the planner's own inputs (``$input``) carry that input's exact pin.
    pins = _input_pins(packet)
    for step in steps:
        if isinstance(step.get('check_inputs'), dict):
            step['check_inputs'] = _bind_inputs(step['check_inputs'], pins)
    target = template.get('deliverable_step') or (steps[-1]['id'] if steps else 'synthesize')
    output = next((o['path'] for s in steps if s['id'] == target for o in s.get('outputs', [])), 'outputs/result.json')
    deliverables = [{'id': d['id'], 'status': 'planned', 'outputs': [{'step': target, 'path': output}]}
                    for d in frame.get('deliverables') or ()]
    plan = {'schema_version': 1, 'kind': 'judgment-plan', 'frame_sha256': digest(frame) if frame else '0' * 64,
            'rationale': template.get('rationale', 'Decomposed with P2 into acquire, derive and compare.'),
            'steps': steps, 'deliverables': deliverables or [{'id': 'D1', 'status': 'held', 'outputs': [],
                                                               'held_reason': 'no framed deliverable'}]}
    for key in ('revision', 'parent_plan_sha256'):
        if key in template:
            plan[key] = template[key]
    return plan


def _consumed(packet, workspace):
    """The run pins of the governed inputs whose workspace copies this worker has: its result's provenance."""
    pins = []
    base = Path(workspace) / 'inputs' / 'artifacts'
    copies = {}
    for copy in sorted(base.glob('*/*')) if base.is_dir() else ():
        copies.setdefault(copy.name, []).append(hashlib.sha256(copy.read_bytes()).hexdigest())
    for row in (packet.get('step') or {}).get('inputs') or ():
        artifact = row.get('artifact') if isinstance(row, dict) else None
        if not isinstance(artifact, str):
            continue
        name = artifact.rsplit(':', 1)[-1].rsplit('/', 1)[-1]
        found = [sha for sha in copies.get(name, ()) if row.get('sha256') in (None, sha)]
        if len(found) == 1:
            path = 'steps/' + artifact.replace(':', '/', 1) if ':' in artifact else artifact
            pins.append({'path': path, 'sha256': found[0]})
    return pins


def gen_toy_table(rule, documents, packet):
    points = rule.get('points', [0.5, 1.0])
    rows = [{'coupling': g, 'observable': round(100.0 * g * g, 6), 'uncertainty': round(1.0 + g, 6)} for g in points]
    table = {'schema_version': 1, 'kind': 'toy-observable-table', 'model': 'fictional toy model', 'rows': rows}
    if rule.get('provenance'):
        # A derived record names the governed inputs it was computed from (its input closure).
        table['inputs'] = _consumed(packet, packet.get('workspace') or os.getcwd())
    return table


# The toy model's own normalization: every factor from the generated weights to the delivered yield
# (2 pb x 1 pb^-1 x 50/100 of the generated weight selected = 1 event), so a normalization audit has a
# real subject to recompute. A rule may state its own ledger.
TOY_LEDGER = {'schema_version': 1, 'sample': 'fictional toy process',
              'luminosity': {'value': 1.0, 'unit': 'pb^-1', 'source': 'the toy model stated in the request'},
              'sigma': {'value': 2.0, 'unit': 'pb', 'order': 'LO', 'tool': 'toy model', 'pdf': 'none (toy model)',
                        'scales': 'none (toy model)', 'process_basis': 'fictional toy process',
                        'source': 'the toy model stated in the request'},
              'generated': {'sumw': 100.0, 'sumw2': 100.0},
              'selected': {'toy-region': {'sumw': [50.0], 'sumw2': [25.0]}}, 'bin_convention': 'per-bin'}


def gen_normalization_ledger(rule, documents, packet):
    return json.loads(json.dumps(rule.get('ledger', TOY_LEDGER)))


def gen_delivered_yields(rule, documents, packet):
    """The yields the ledger delivers: sigma x luminosity x selected / generated weight, per region and bin."""
    ledger = rule.get('ledger', TOY_LEDGER)
    scale = ledger['sigma']['value'] * ledger['luminosity']['value'] / ledger['generated']['sumw']
    return {region: [round(scale * w, 12) for w in row['sumw']] for region, row in ledger['selected'].items()}


def gen_attacks(rule, documents, packet):
    subject = ((packet.get('step') or {}).get('parameters') or {}).get('judgment', {}).get('subject') or {}
    return {'schema_version': 1, 'kind': 'judgment-attacks',
            'subject': {'plan_sha256': subject.get('plan_sha256', '0' * 64),
                        'draft_sha256': subject.get('draft_sha256', '0' * 64)},
            'attacks': rule.get('attacks', [])}


def gen_workflow_specification(rule, documents, packet):
    """A real external-workflow request: the supplied workflow file, its targets, cores and batch site.

    The controller's governed preparation adopts the named file, inspects it with the workflow manager
    and plans the run study; this worker only states the request the study specification carries.
    """
    policy = {'schema_version': 1, 'actors': {'proposer': 'producer', 'executor': 'executor',
                                              'physics_critic': 'critic', 'skeptical_verifier': 'skeptic',
                                              'physics_decider': 'decider'},
              'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
              'required_checks': [{'id': 'integrity', 'kind': 'integrity'}, {'id': 'scientific', 'kind': 'scientific'}],
              'claim_scopes': {'diagnostic': {'checks': ['integrity'], 'actions': ['delivery', 'reuse']}}}
    task = {'schema_version': 1, 'operation': 'run', 'snakefile': rule['workflow'],
            'targets': list(rule.get('targets', ['all'])), 'cores': 1}
    if rule.get('site'):
        task['site'] = dict(rule['site'])
    return {'schema_version': 2, 'mode': 'external-workflow', 'max_attempts': 1,
            'source': rule.get('source', 'The supplied workflow file of this request, run as written.'),
            'assumptions': list(rule.get('assumptions', ['The supplied workflow is the computation the request names.'])),
            'max_seconds': int(rule.get('max_seconds', 600)), 'approval_mode': 'scripted_yes',
            'review_policy': {'schema_version': 1, 'policy': policy,
                              'correction_contract': {'task_fields': [], 'input_slots': []}},
            'task': task}


def gen_study_scope(rule, documents, packet):
    """The study scope: every original deliverable this child covers, its stages and its child directory."""
    _, reading = _find(documents, lambda p, v: isinstance(v, dict) and isinstance(v.get('deliverables'), list)
                       and v.get('kind') not in ('question-frame', 'judgment-plan'))
    covered = [row['id'] for row in (reading or {}).get('deliverables') or ()
               if isinstance(row, dict) and isinstance(row.get('id'), str)]
    return {'schema_version': 1, 'kind': 'study-scope', 'deliverables': covered, 'stages': list(rule.get('stages', [])),
            'child_rundir': rule.get('child_rundir', 'children/study'),
            **({'compute': dict(rule['compute'])} if 'compute' in rule else {})}


# ---- analysis-route documents ------------------------------------------------------------------
#
# The prepare phase of the analysis route (01 environment, 02 route analysis, trap sweep, figure
# target and cost) and the verification documents, built from the worker's own inputs: the pinned
# reading, the task contract and the route analysis. The route analysis binds the confined launches
# of the operate steps (``launches``: the launch program ``canary_launch.py`` beside this file) and
# names the supplied run inputs each launch reads (``launch_inputs``).

LAUNCH_PROGRAM = 'canary_launch.py'
HERE = Path(__file__).resolve().parent


def _reading(documents):
    _, reading = _find(documents, lambda p, v: isinstance(v, dict) and v.get('kind') == 'request-reading')
    return reading or {}


def _stated(reading, symbol):
    """The distinct values the request assigns to ``symbol``, in the request's order."""
    values = []
    for fact in reading.get('facts') or ():
        value = fact.get('value') if isinstance(fact, dict) else None
        if fact.get('type') == 'parameter_value' and isinstance(value, dict) and value.get('symbol') == symbol:
            number = float(value['value'])
            if number not in values:
                values.append(number)
    return values


def _supplied_script(reading):
    paths = [(f.get('value') or {}).get('path') for f in reading.get('facts') or ()
             if isinstance(f, dict) and f.get('type') == 'supplied_file']
    return next((p for p in paths if isinstance(p, str) and p.endswith('.py')), None)


def point_tag(point):
    """The scan orchestrator's identity of a grid point (its coordinates' canonical digest)."""
    return 'point_' + hashlib.sha256(json.dumps(point, sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]


def _clean(value):
    return int(value) if float(value).is_integer() else float(f'{value:.12g}')


def _reading_axes(reading):
    """The grid the request fixes, read as the route reads it: ``[(axis name, values)]``, one per stated
    list or stepped range, axes named by their variable or symbol, else by their position."""
    axes, used = [], set()
    facts = [f for f in reading.get('facts') or ()
             if isinstance(f, dict) and f.get('type') in ('parameter_values', 'parameter_range')]
    for index, fact in enumerate(facts):
        value = fact.get('value') or {}
        name = re.sub(r'[^A-Za-z0-9_]+', '_', str(value.get('variable') or value.get('symbol') or '')).strip('_')
        if not name or not name[0].isalpha():
            name = f'axis{index + 1}' + (f'_{name}' if name else '')
        base, n = name[:80], 2
        name = base
        while name in used:
            name, n = f'{base[:76]}_{n}', n + 1
        used.add(name)
        if fact['type'] == 'parameter_values':
            axes.append((name, list(value.get('values') or ())))
            continue
        step = value.get('step')
        step = step.get('value') if isinstance(step, dict) else step
        low, high = sorted((value['low'], value['high']))
        count = math.floor((high - low) / step + 1e-9) + 1
        axes.append((name, [_clean(low + k * step) for k in range(count)]))
    return axes


def gen_environment(rule, documents, packet):
    """Each tool the plan needs, probed on this host (an observed status), and the planned operations."""
    import shutil
    tools = []
    for tool in rule.get('tools') or ():
        probe = tool.get('probe') or tool['name']
        path = sys.executable if probe == 'interpreter' else shutil.which(probe)
        found = bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)
        tools.append({'name': tool['name'], 'status': 'available' if found else 'missing',
                      'required': tool.get('required', True), 'required_by': list(tool.get('required_by') or ()),
                      'observed': {'probe': probe, 'path': path if found else None}})
    return {'schema_version': 1, 'kind': 'environment-record', 'tools': tools,
            'operations': sorted(rule.get('operations') or ())}


def _launch(mode, config, inputs=()):
    source = (HERE / LAUNCH_PROGRAM).read_text()
    return {'argv': [sys.executable, '-I', '-c', source, mode, json.dumps(config, sort_keys=True), *inputs]}


def gen_route_analysis(rule, documents, packet):
    """The route analysis of a supplied-script scan over the grid the request fixes: routine, modes and the
    confined launch of every operate step (one per approved grid point)."""
    reading = _reading(documents)
    template = json.loads(json.dumps(rule.get('route', {})))
    symbol, expected_symbol = rule['scan_symbol'], rule['expected_symbol']
    axes = _reading_axes(reading)
    axis, values = axes[0] if len(axes) == 1 else (None, [])
    smoke = (_stated(reading, symbol) or values or [None])[0]
    expected = (_stated(reading, expected_symbol) or [None])[0]
    script = _supplied_script(reading)
    points = [{'id': point_tag({axis: v}), 'parameters': {axis: v}} for v in values]
    common = {'routine': template['routine'], 'symbol': symbol, 'axis': axis, 'smoke': smoke, 'expected': expected,
              'detector_mode': template['detector_mode'], 'model': template['model']}
    token = '@input:' + script if script else None
    launches = {
        'recast.smoke': _launch('recast', {**common, 'step': 'recast.smoke',
                                           'outputs': ['outputs/smoke/recast.json', 'outputs/smoke/histograms.json']},
                                [token]),
        'visualize.waypoint': _launch('waypoint', {**common, 'step': 'visualize.waypoint',
                                                   'outputs': ['outputs/waypoint.json', 'outputs/waypoint.pdf']},
                                      ['@input:recast.smoke:outputs/smoke/recast.json']),
        'scan.assemble': _launch('assemble', {**common, 'step': 'scan.assemble', 'points': points,
                                              'outputs': ['outputs/scan.json', 'outputs/scan.pdf']},
                                 [f'@input:scan.point.{p["id"]}:outputs/point_result.json' for p in points]),
        'visualize.final': _launch('final', {**common, 'step': 'visualize.final',
                                             'outputs': ['outputs/figures.json', 'outputs/figure.pdf']},
                                   ['@input:scan.assemble:outputs/scan.json']),
    }
    for row in points:
        step = f'scan.point.{row["id"]}'
        launches[step] = _launch('point', {**common, 'step': step, 'tag': row['id'], 'coordinates': row['parameters'],
                                           'grid': values, 'outputs': ['outputs/point_result.json']}, [token])
    return {'schema_version': 1, 'kind': 'route-analysis', **template, 'launches': launches,
            'launch_effects': {step: ['executes_native'] for step in launches
                               if script and token in launches[step]['argv']},
            'launch_inputs': {step: [script] for step in launches if script and token in launches[step]['argv']}}


def gen_trap_sweep(rule, documents, packet):
    """The twelve-trap sweep record (the shape ``ravel.workflow.trap_sweep.build`` returns), no trap hit."""
    traps = list(rule.get('traps') or [f'T{i}' for i in range(1, 13)])
    verdicts = [{'id': t, 'hit': False, 'evidence': rule.get('evidence', 'not applicable to the toy model'),
                 'consequence': None, 'flag_number': None} for t in traps]
    return {'schema_version': 1, 'generated_by': 'ravel.workflow.trap_sweep', 'traps_checked': traps,
            'none_hit': True, 'verdicts': verdicts, 'traps_hit': [], 'escalations': [], 'obligations': []}


# Files a generator adds beside the declared outputs (written through the broker like them).
EXTRA_FILES = {}


def _validation(rule, packet, report_path):
    """Validation documents for the route's reviewer-owed checks (the launch program's toy enumeration),
    written beside this worker's outputs; returns their validator inputs and figure index."""
    namespace = {'__name__': 'canary_launch'}
    exec(compile((HERE / LAUNCH_PROGRAM).read_text(), LAUNCH_PROGRAM, 'exec'), namespace)
    workspace = Path.cwd()
    prefix = f'agent-work/{workspace.parent.name}/{workspace.name}/outputs/'
    step = (packet.get('step') or {}).get('id') or 'step'
    metadata, files = namespace['toy_inputs'](rule.get('routine', 'supplied-script'), step, int(workspace.name),
                                              report_path=report_path, output_prefix=prefix)
    for name, value in files.items():
        if isinstance(value, str) or name.endswith('.pdf'):
            EXTRA_FILES['outputs/' + name] = value.decode('ascii') if isinstance(value, bytes) else value
    return metadata


def gen_figure_target(rule, documents, packet):
    """The figure contract with a real preview of its validation figure (no target fulfilment claimed)."""
    document = json.loads(json.dumps(rule['target']))
    metadata = _validation(rule, packet, 'outputs/figure_target.json')
    document.setdefault('validator_inputs', {}).update(metadata['validator_inputs'])
    document.update({key: metadata[key] for key in ('figure_spec', 'n_figures', 'figures')})
    for figure in document['figures']:
        figure['filename'] = figure['pdf']
    return document


def gen_cost(rule, documents, packet):
    """The cost record of the plan's highest rung over the population of the grid the request fixes."""
    count = 1
    for _, values in _reading_axes(_reading(documents)):
        count *= len(values)
    return {'schema_version': 1, 'kind': 'cost-preflight', 'mode': rule.get('mode', 'scan'), 'points': count,
            'status': rule.get('status', 'uncalibrated'), 'basis': rule['basis']}


def _scan_table(documents):
    _, table = _find(documents, lambda p, v: isinstance(v, dict) and v.get('kind') == 'toy-observable-table'
                     and isinstance(v.get('point_population'), list))
    return table or {}


def gen_comparison(rule, documents, packet):
    """The comparison of the scanned value at the smoke coupling with the request's stated expectation."""
    reading = _reading(documents)
    expected = (_stated(reading, rule['expected_symbol']) or [None])[0]
    smoke = (_stated(reading, rule['scan_symbol']) or [None])[0]
    row = next((r for r in _scan_table(documents).get('rows') or () if r.get('coupling') == smoke), None)
    residual = None if row is None or expected is None else row['observable'] - expected
    document = json.loads(json.dumps(rule['document']))
    document.update({'expected': expected, 'observed': row, 'residual': residual,
                     'agrees': residual is not None and abs(residual) <= row['uncertainty']})
    document.setdefault('validator_inputs', {}).update(
        _validation(rule, packet, 'outputs/comparison.json')['validator_inputs'])
    return document


def gen_traced(rule, documents, packet):
    """A verification or results document whose numbers each name the accepted artifact they come from."""
    table = _scan_table(documents)
    document = json.loads(json.dumps(rule['document']))
    document['numbers'] = [{'artifact': rule['source'], 'pointer': f'/rows/{i}/observable', 'value': r['observable'],
                            'uncertainty': r['uncertainty'], 'coupling': r['coupling']}
                           for i, r in enumerate(table.get('rows') or ())]
    if rule.get('validated'):
        report = next((o['path'] for o in (packet.get('step') or {}).get('outputs') or ()
                       if o.get('path', '').endswith('.json')), 'outputs/report.json')
        document.setdefault('validator_inputs', {}).update(_validation(rule, packet, report)['validator_inputs'])
    return document


def _result_bytes(documents):
    """The bytes of the supplied fictional result this worker can read: an input document, else the file the
    reading names (``None`` when neither is readable)."""
    path, _ = _find(documents, lambda p, v: isinstance(v, dict) and v.get('kind') == 'toy-result')
    candidates = [path] if path else []
    for fact in _reading(documents).get('facts') or ():
        if isinstance(fact, dict) and fact.get('type') == 'supplied_file':
            candidates.append(Path(str((fact.get('value') or {}).get('path') or '')))
    for candidate in candidates:
        try:
            raw = Path(candidate).read_bytes()
            if json.loads(raw).get('kind') == 'toy-result':
                return raw
        except (OSError, ValueError, AttributeError):
            continue
    return None


def gen_assumption_audit(rule, documents, packet):
    """The delivery assumption auditor's document: every assumption of the pinned delivery-assumption subject,
    graded with the rule's severity and control, and the delivered result naming each of them as reported."""
    _, subject = _find(documents, lambda p, v: isinstance(v, dict) and v.get('kind') == 'delivery-assumption-subject')
    ids = [row['id'] for row in (subject or {}).get('assumptions') or () if isinstance(row, dict) and row.get('id')]
    items = [{'id': ident, 'severity': int(rule.get('severity', 1)), 'controlled': bool(rule.get('controlled', True))}
             for ident in ids]
    return {'audit': {'schema_version': 1, 'kind': 'assumption-audit', 'items': items},
            'result': {'assumptions_reported': ids}}


def gen_claim_map(rule, documents, packet):
    """The staged author's claim map: one claim per stated value, each bound to the supplied result's digest and
    traced to its JSON pointer (``claims`` in the rule: ``[[id, pointer, text], ...]``)."""
    raw = _result_bytes(documents)
    result = json.loads(raw) if raw else {}
    claims = []
    for ident, pointer_text, text in rule['claims']:
        value = result
        for part in pointer_text[1:].split('/'):
            value = value[int(part)] if isinstance(value, list) else (value or {}).get(part)
        claims.append({'id': ident, 'text': text, 'result': 'result',
                       'quantity': {'pointer': pointer_text, 'value': value, 'tolerance': 0}})
    return {'schema_version': 1, 'kind': 'manuscript-claim-map', 'title': rule.get('title', 'A fictional toy note'),
            'authors': [], 'results': {'result': {'sha256': hashlib.sha256(raw or b'').hexdigest()}}, 'claims': claims}


GENERATORS = {'question_frame': gen_question_frame, 'judgment_plan': gen_judgment_plan, 'toy_table': gen_toy_table,
              'attacks': gen_attacks, 'workflow_specification': gen_workflow_specification,
              'study_scope': gen_study_scope, 'environment': gen_environment, 'route_analysis': gen_route_analysis,
              'trap_sweep': gen_trap_sweep, 'cost': gen_cost, 'figure_target': gen_figure_target,
              'comparison': gen_comparison, 'traced': gen_traced, 'normalization_ledger': gen_normalization_ledger,
              'delivered_yields': gen_delivered_yields, 'claim_map': gen_claim_map,
              'assumption_audit': gen_assumption_audit}


def render(value, rule, documents, packet):
    if isinstance(value, dict) and set(value) == {'$gen'}:
        return GENERATORS[value['$gen']](rule, documents, packet)
    return value


# ---- the run ----------------------------------------------------------------------------------

def matches(rule, packet):
    when = rule.get('when') or {}
    step = packet.get('step') or {}
    phase = ((step.get('parameters') or {}).get('judgment') or {}).get('phase')
    checks = {'step': step.get('id') or '', 'role': packet.get('role') or step.get('role') or '',
              'kind': step.get('kind') or '', 'phase': phase or ''}
    return all(re.fullmatch(pattern, checks[key]) for key, pattern in when.items() if key in checks)


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1, sort_keys=True))
    return str(path)


def _broker(argv):
    if '--mcp-config' not in argv:
        return None, None
    entry = json.loads(Path(argv[argv.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']
    server = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True)
    counter = iter(range(1, 1_000_000))

    def rpc(method, params):
        server.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': next(counter), 'method': method, 'params': params}) + '\n')
        server.stdin.flush()
        line = server.stdout.readline()
        if not line:
            raise ConnectionError('broker MCP server closed its output')
        return json.loads(line)
    return server, rpc


def reviewer_items(step):
    """Ids of the reviewer items a review step carries (seat items and judgment must-check rows)."""
    parameters = step.get('parameters') or {}
    rows = list(parameters.get('reviewer_items') or ()) + list((parameters.get('judgment') or {}).get('must_check') or ())
    return list(dict.fromkeys(r['id'] for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)))


def final_record(rule, packet, written, documents):
    base = instance(packet['schema']) if isinstance(packet.get('schema'), dict) else {}
    record = overlay(base if isinstance(base, dict) else {}, render(rule.get('final', {}), rule, documents, packet))
    if not isinstance(record, dict):
        record = {}
    record['instruction_ack'] = overlay(record.get('instruction_ack') or {},
                                        {'manifest_sha256': packet.get('manifest_sha256')})
    evidence = written[0][0] + '#' if written else 'final_record#/schema_version'
    rows = [{'unit': unit, 'status': 'done', 'evidence': evidence, 'note': None} for unit in packet['duty_units']]
    omit = int(rule.get('omit_ack_rows', 0))
    record['checklist'] = rows[omit:] if omit else rows
    if 'escalation' in rule:
        record['escalation'] = rule['escalation']
    items = reviewer_items(packet.get('step') or {})
    if items or 'item_verdicts' in ((packet.get('schema') or {}).get('properties') or {}):
        verdict = rule.get('verdict', 'pass')
        record['item_verdicts'] = [{'item': item, 'verdict': verdict, 'evidence': [evidence],
                                    'note': None if verdict != 'unresolved' else 'scripted unresolved verdict'}
                                   for item in items]
    return record


def run(argv, prompt, here, workspace):
    script = json.loads((here / 'script.json').read_text())
    packet = parse_packet(prompt)
    packet['workspace'] = str(workspace)
    rule = next((r for r in script.get('rules', []) if matches(r, packet)), script.get('default', {}))
    documents = _input_documents(workspace)
    log = {'rule': rule.get('name'), 'step': (packet.get('step') or {}).get('id'), 'role': packet.get('role'),
           'duty_units': len(packet['duty_units']), 'actions': []}
    server, rpc = _broker(argv)
    try:
        if rpc is not None:
            rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                               'clientInfo': {'name': 'canary-scripted-worker'}})
            listed = rpc('tools/list', {})
            log['actions'].append({'op': 'tools/list', 'response': listed.get('result') is not None})
            # The production qualifier uses a fixed prompt, rather than an instruction packet.
            # Exercise the broker for real: a direct workspace write cannot qualify a transport.
            if 'qualify.conformance' in prompt or 'outputs/conformance.txt' in prompt:
                read = rpc('tools/call', {'name': 'ws_read', 'arguments': {'path': 'inputs/conformance.json'}})
                nonce = json.loads(read['result']['structuredContent']['stdout_tail'])['nonce']
                if not rule.get('conformance_omit_write'):
                    rpc('tools/call', {'name': 'ws_write', 'arguments': {
                        'path': 'outputs/conformance.txt', 'content': nonce}})
                names = [tool['name'] for tool in listed['result']['tools']]
                rpc('tools/call', {'name': 'ws_write', 'arguments': {
                    'path': 'outputs/surface.txt', 'content': '\n'.join('mcp__ravel__' + n for n in names)}})
                return {'completed': True, 'summary': 'inert scripted conformance'}, rule
        written = []
        skip = set(rule.get('skip_outputs', ()))
        contents = rule.get('outputs', {})
        for row in (packet.get('step') or {}).get('outputs') or ():
            path = row.get('path') if isinstance(row, dict) else None
            if not isinstance(path, str) or path in skip:
                continue
            value = render(contents.get(path, rule.get('output', {'$gen': 'toy_table'})), rule, documents, packet)
            text = value if isinstance(value, str) else json.dumps(value, indent=1, sort_keys=True)
            if rpc is None:
                raise RuntimeError('a declared output requires its broker write receipt')
            response = rpc('tools/call', {'name': 'ws_write', 'arguments': {'path': path, 'content': text}})
            if 'error' in response or response.get('result', {}).get('isError'):
                raise RuntimeError(f'broker refused declared output {path}')
            written.append((path, hashlib.sha256(text.encode()).hexdigest()))
        for path, text in sorted(EXTRA_FILES.items()):
            response = rpc('tools/call', {'name': 'ws_write', 'arguments': {'path': path, 'content': text}})
            if 'error' in response or response.get('result', {}).get('isError'):
                raise RuntimeError(f'broker refused validation file {path}')
            log['actions'].append({'op': 'validation_file', 'path': path})
        for path, text in (rule.get('extra_outputs') or {}).items():
            _write(Path(workspace) / path, text)
            log['actions'].append({'op': 'extra_output', 'path': path})
        for call in rule.get('calls') or ():
            if rpc is not None:
                response = rpc('tools/call', {'name': call['name'], 'arguments': call.get('arguments', {})})
                log['actions'].append({'op': 'call', 'name': call['name'], 'error': 'error' in response})
        record = final_record(rule, packet, written, documents)
    finally:
        if server is not None:
            server.stdin.close()
            server.wait()
    try:
        _write(Path(workspace) / 'scratch' / 'canary-worker.json', log)
    except OSError:
        pass
    return record, rule


def envelope(record, argv, rule, prompt):
    model = argv[argv.index('--model') + 1] if '--model' in argv else 'claude-fixture-model'
    # This transport is explicitly inert. Synthetic usage follows the bytes it actually reads
    # and returns, using the packet's four-byte estimate rather than a fixed tiny placeholder.
    # The provider counter reads the consumed prompt as the CLI reports it: split into fresh input, cache
    # writes and cache reads (every part a nonnegative integer), beside the output.
    consumed = (len(prompt.encode()) + 3) // 4
    usage = {'input_tokens': consumed // 3, 'cache_creation_input_tokens': consumed // 3,
             'cache_read_input_tokens': consumed - 2 * (consumed // 3),
             'output_tokens': (len(json.dumps(record).encode()) + 3) // 4}
    return {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '', 'session_id': str(uuid.uuid4()),
            'num_turns': 2, 'total_cost_usd': 0.001, 'usage': usage,
            'modelUsage': {model: {'outputTokens': usage['output_tokens']}}, 'structured_output': record}


def main(argv):
    here = Path(__file__).resolve().parent
    if argv == ['--version']:
        print((here / 'version.txt').read_text().strip() if (here / 'version.txt').is_file() else 'fake-cli 9.9.9')
        return 0
    if '--help' in argv:
        sys.stdout.write((here / 'help.txt').read_text() if (here / 'help.txt').is_file() else 'Usage\n')
        return 0
    if argv == ['auth', 'status', '--json']:  # the login preflight's prompt-free status observation
        print(json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'}))
        return 0
    prompt = sys.stdin.read()
    record, rule = run(argv, prompt, here, Path(os.getcwd()))
    print(json.dumps(envelope(record, argv, rule, prompt)))
    return int(rule.get('exit', 0))


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
