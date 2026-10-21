"""The step specification (``step.v1``) as the governed step reads it, and the branch it takes.

A plan step names its kind from a closed vocabulary. ``acquire`` and ``operate`` run a domain
operation by its signature: through the confined launcher when the approved step carries its
launch (``parameters.launch``), or materialised from a registered closed task signature.
Other operations run through the operation's executor role. ``author``,
``derive``, ``compare``, ``review``, ``synthesize`` and ``decide`` dispatch one worker of the
step's role. ``subgraph`` invokes one registered graph (``graph``). ``ask`` is the operator's
question and ``route`` a child plan: both belong to the controller graph, so the step returns
them as typed outcomes and never answers or expands them itself.

Operation details the plan approves travel under ``parameters``: ``launch`` (argv, environment
capsule, read roots), ``task`` (the operation task its signature reads), ``cost`` (amount and
unit), ``effects``, ``check_inputs`` (validator parameters) and ``quantities`` (output path to
the quantity kind it sets).
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from .services import StepHold, digest

KINDS = ('acquire', 'operate', 'author', 'derive', 'compare', 'review', 'synthesize', 'ask', 'decide',
         'subgraph', 'route')
WORKER_KINDS = ('author', 'derive', 'compare', 'review', 'synthesize', 'decide')
OPERATION_KINDS = ('acquire', 'operate')
PARENT_KINDS = ('ask', 'route')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
SAFE_PATH = re.compile(r'(?![/~])(?!.*(^|/)\.\.(/|$))[A-Za-z0-9_.@+=/:-]+\Z')
# Subgraph steps invoke one of these registered graphs.
SUBGRAPHS = ('research.loop', 'rdj.case', 'review.points', 'manuscript.build', 'ml.study', 'literature.scout',
             'intake.plan', 'consult.case')
REQUIRED = ('id', 'kind', 'inputs', 'outputs', 'depends_on')
# Keys the engagement decision's applied view adds to a scientific step; the approved identity excludes them.
APPLIED_STEP_KEYS = ('engagement', 'engagement_seats', 'engagement_folded_into', 'seats', 'correction_rounds')
SCHEMA = Path(__file__).resolve().parents[2] / 'data' / 'controller' / 'schemas' / 'step.v1.json'


def _schema_errors(step):
    """Errors against the published ``step.v1`` schema, when the controller core ships it."""
    if not SCHEMA.is_file():
        return []
    from jsonschema import Draft202012Validator
    schema = json.loads(SCHEMA.read_text())
    return [('/'.join(str(p) for p in e.absolute_path) or '$') + ': ' + e.message
            for e in Draft202012Validator(schema).iter_errors(step)]


def check(step):
    """The step as a plain JSON object, or a typed hold naming the first defect."""
    if type(step) is not dict or any(key not in step for key in REQUIRED):
        raise StepHold('step_spec_invalid', 'a step names its id, kind, inputs, outputs and dependencies')
    errors = _schema_errors(step)
    if errors:
        raise StepHold('step_spec_invalid', '; '.join(errors[:5]))
    if type(step['id']) is not str or not ID.fullmatch(step['id']):
        raise StepHold('step_spec_invalid', 'a step id is a short identifier')
    if step['kind'] not in KINDS:
        raise StepHold('step_kind_unknown', f"step {step['id']} kind {step['kind']!r} is outside the closed vocabulary")
    if type(step['depends_on']) is not list or any(type(d) is not str or not ID.fullmatch(d) for d in step['depends_on']):
        raise StepHold('step_spec_invalid', 'dependencies are step ids')
    if type(step['inputs']) is not list or type(step['outputs']) is not list:
        raise StepHold('step_spec_invalid', 'inputs and outputs are lists')
    for row in step['inputs']:
        if type(row) is not dict or type(row.get('artifact')) is not str or not SAFE_PATH.fullmatch(row['artifact']):
            raise StepHold('step_input_invalid', 'every input names a confined artifact')
        if row.get('sha256') is not None and (type(row['sha256']) is not str
                                              or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])):
            raise StepHold('step_input_invalid', 'an input digest is a sha256 or null')
    paths = []
    for row in step['outputs']:
        if (type(row) is not dict or type(row.get('path')) is not str or not SAFE_PATH.fullmatch(row['path'])
                or type(row.get('kind')) is not str or type(row.get('required', True)) is not bool):
            raise StepHold('step_output_invalid', 'every output is a typed confined path')
        paths.append(worker_path(row['path']))
    if len(paths) != len(set(paths)):
        raise StepHold('step_output_invalid', 'duplicate declared output')
    budget = step.get('budget') or {}
    if type(budget) is not dict or any(value is not None and (type(value) not in (int, float) or value < 0)
                                       for value in budget.values()):
        raise StepHold('step_budget_invalid', 'a step budget names nonnegative amounts per dimension')
    if type(step.get('parameters', {})) is not dict:
        raise StepHold('step_spec_invalid', 'parameters is an object')
    for key in ('review', 'protocols', 'instruction_sources', 'obligations'):
        if type(step.get(key, [])) is not list:
            raise StepHold('step_spec_invalid', f'{key} is a list')
    if step['kind'] in WORKER_KINDS and not step.get('role'):
        raise StepHold('step_role_missing', f"a {step['kind']} step names the role whose worker fills it")
    if step['kind'] == 'operate' and not step.get('operation'):
        raise StepHold('step_operation_missing', 'an operation step names its registered operation')
    if step['kind'] == 'acquire' and not step.get('operation') and not step.get('role'):
        # An acquisition is a registered operation (a launch) or a worker session of a named role.
        raise StepHold('step_operation_missing', 'an acquire step names its registered operation or the role '
                                                 'whose worker acquires')
    if step['kind'] == 'subgraph':
        graph = step.get('graph') or {}
        if graph.get('id') not in SUBGRAPHS or type(graph.get('instance', {})) is not dict:
            raise StepHold('subgraph_not_admitted', 'a subgraph step names one admitted registered graph')
    return deepcopy(step)


def parameters(step):
    return step.get('parameters') or {}


def launch(step):
    return parameters(step).get('launch')


def branch(step) -> str:
    """``worker``, ``launch``, ``subgraph`` or ``parent`` (an ask or a child route)."""
    kind = step['kind']
    if kind in PARENT_KINDS:
        return 'parent'
    if kind == 'subgraph':
        return 'subgraph'
    if kind == 'operate' or (kind in OPERATION_KINDS and launch(step)):
        return 'launch'
    return 'worker'


def attempt(context) -> int:
    value = (context or {}).get('attempt', 1)
    if type(value) is not int or not 1 <= value <= 1000:
        raise StepHold('attempt_invalid', 'the controller numbers attempts from 1')
    return value


def worker_path(path) -> str:
    """Where a worker writes a declared output: under ``outputs/`` of its own workspace."""
    return path if Path(path).parts[:1] == ('outputs',) else 'outputs/' + path


def quantities(step):
    """``output path -> quantity kind`` the approved step says each output sets."""
    found = parameters(step).get('quantities') or {}
    return {row['path']: found.get(row['path']) for row in step['outputs']}


def step_sha256(step) -> str:
    """The canonical digest of the approved step bytes."""
    return digest(step)


def scientific_step(step) -> dict:
    """The step as the approved scientific plan states it: the applied view's engagement fields removed."""
    return {k: deepcopy(v) for k, v in step.items() if k not in APPLIED_STEP_KEYS}


def worker_node(step_id, seat=None) -> str:
    """The dispatcher node id of the step's producer or of one review seat (a broker identity)."""
    raw = step_id + ('' if seat is None else '.' + seat)
    node = 'ctl.' + re.sub(r'[^A-Za-z0-9_.-]', '_', raw)
    if node != 'ctl.' + raw or len(node) > 120:
        # A rewritten or long id keeps a digest of the original, so two step ids never share a node.
        node = node[:96] + '.' + digest([step_id, seat])[:16]
    return node
