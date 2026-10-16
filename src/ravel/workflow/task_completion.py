"""Original task obligations carried through ordinary child assignments and review.

This is a derived view of task_contract, scientific-study and physics-review
records, not a second goal journal. Exact criteria are supplied interpretations;
custody and registered reviews do not prove arbitrary semantic entailment or
authenticate the human origin of an instruction. Uncertain goals stay open.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import candidate_experiments as ce

KINDS = ('experiment', 'model', 'domain', 'quantity', 'deliverable', 'quality', 'coverage', 'method', 'whole_request')
STATES = ('satisfied', 'negative', 'partial', 'blocked', 'unknown')
PARENT_ACCEPTANCE_SCOPE = 'original_task_completion'


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode()) > 32000:
        raise ValueError('bounded literal task text required')


def _criteria(value):
    if type(value) is not dict or not value or len(json.dumps(value, allow_nan=False).encode()) > 16000:
        raise ValueError('explicit finite task criteria required')


def _rows(rows, maximum=64, *, empty=False):
    if type(rows) is not list or not (0 if empty else 1) <= len(rows) <= maximum:
        raise ValueError('bounded complete task census required')


def _pin_shape(pin):
    ce.keys(pin, ('path', 'sha256', 'size')); ce.sha(pin['sha256']); _text(pin['path'])
    if type(pin['size']) is not int or not 1 <= pin['size'] <= 64_000_000:
        raise ValueError('bounded nonempty task artifact required')


def initial_requirements(prompt):
    """Keep the entire request until an explicit finer obligation census is supplied."""
    _text(prompt)
    return {'schema_version': 1, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'obligations': [{'id': 'original-request', 'kind': 'whole_request', 'statement': prompt,
            'criteria': {'request': prompt}, 'evidence': [{'start': 0, 'end': len(prompt), 'text': prompt}]}],
        'assignments': [], 'amendments': [], 'parent_acceptance_scope': PARENT_ACCEPTANCE_SCOPE}


def census_from_reading(prompt, reading):
    """The obligation census of a request: the verbatim whole request first, then every finer item.

    Requested stages and tools, deliverables, a published-figure comparison (a `quality`
    obligation), templates, prescribed statistics, other constraints and stated parameter
    ranges each become an obligation bound to exact spans of the request. A request that
    asks for exactly one thing keeps the whole-request obligation as that deliverable.
    """
    from .request_reading import check, obligation_items
    census = initial_requirements(prompt)
    errors = check(reading, prompt)
    if errors:
        raise ValueError('request reading is invalid: ' + '; '.join(errors[:4]))
    for row in obligation_items(reading):
        census['obligations'].append({'id': row['id'], 'kind': row['kind'], 'statement': row['statement'][:8000],
                                      'criteria': deepcopy(row['criteria']), 'evidence': deepcopy(row['evidence'])})
    return census


def validate_requirements(contract):
    """Structural checks only; every original dimension remains reviewable verbatim."""
    req = contract['task_requirements']; prompt = contract['prompt']
    ce.keys(req, ('schema_version', 'prompt_sha256', 'obligations', 'assignments', 'amendments', 'parent_acceptance_scope',
                  *(['completion_epoch'] if 'completion_epoch' in req else [])))
    if 'completion_epoch' in req and (type(req['completion_epoch']) is not int or req['completion_epoch'] != 1):
        raise ValueError('completion epoch1 required')
    if req['parent_acceptance_scope'] != PARENT_ACCEPTANCE_SCOPE:
        raise ValueError('reserved original_task_completion scope required for the whole parent decision')
    if type(req['schema_version']) is not int or req['schema_version'] != 1:
        raise ValueError('task requirements version1 required')
    if req['prompt_sha256'] != hashlib.sha256(prompt.encode()).hexdigest():
        raise ValueError('original task prompt binding differs')
    _rows(req['obligations']); identities = set()
    for row in req['obligations']:
        ce.keys(row, ('id', 'kind', 'statement', 'criteria', 'evidence')); ce.identity(row['id'])
        if row['id'] in identities or row['kind'] not in KINDS:
            raise ValueError('distinct named original task obligations required')
        identities.add(row['id']); _text(row['statement']); _criteria(row['criteria']); _rows(row['evidence'], 16)
        for span in row['evidence']:
            ce.keys(span, ('start', 'end', 'text'))
            if (type(span['start']) is not int or type(span['end']) is not int or
                    not 0 <= span['start'] < span['end'] <= len(prompt) or prompt[span['start']:span['end']] != span['text']):
                raise ValueError('exact original-request evidence span required')
    original = [row for row in req['obligations'] if row['id'] == 'original-request']
    if original != initial_requirements(prompt)['obligations']:
        raise ValueError('mandatory whole original request obligation cannot be narrowed by a finer census')
    _rows(req['assignments'], 128, empty=True); assignments = set()
    for row in req['assignments']:
        ce.keys(row, ('id', 'purpose', 'coverage')); ce.identity(row['id']); _text(row['purpose'])
        if row['id'] in assignments: raise ValueError('distinct task assignment IDs required')
        assignments.add(row['id']); _rows(row['coverage']); covered = set()
        for item in row['coverage']:
            ce.keys(item, ('obligation_id', 'criteria')); _criteria(item['criteria'])
            if item['obligation_id'] not in identities or item['obligation_id'] in covered:
                raise ValueError('assignment must map distinct existing original obligations')
            covered.add(item['obligation_id'])
    _rows(req['amendments'], 16, empty=True)
    for pin in req['amendments']:
        _pin_shape(pin)
        if not Path(pin['path']).is_absolute(): raise ValueError('absolute source scope-instruction pin required')
    return req


class _Inputs:
    """Bounded single-call source observations, with complete ending byte checks."""
    def __init__(self, base):
        self.base = Path(base).absolute(); self.pins = {}; self.identities = {}
        self.review_sessions = {}
        self.total = 0; self.absences = set(); self.ending_checks = []; self.populations = {}
        if any(p.is_symlink() for p in (self.base, *self.base.parents)) or not self.base.is_dir():
            raise ValueError('ordinary task evidence base required')

    def file(self, pin):
        _pin_shape(pin)
        p = Path(pin['path']); p = p if p.is_absolute() else self.base / p
        if '..' in p.parts or any(q.is_symlink() for q in (p, *p.parents)) or not p.is_file():
            raise ValueError('ordinary canonical task artifact required')
        p = p.resolve(); before = p.stat()
        if len(self.pins) >= 512 and str(p) not in self.pins: raise ValueError('task input census exceeds512')
        if before.st_size != pin['size']:
            raise ValueError('task artifact size differs before bounded read')
        with p.open('rb') as stream: raw = stream.read(pin['size'] + 1)
        after = p.stat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        actual = {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        if identity(before) != identity(after) or any(actual[k] != pin[k] for k in ('sha256', 'size')):
            raise ValueError('task artifact changed')
        if str(p) in self.pins and self.pins[str(p)] != actual: raise ValueError('conflicting task artifact pins')
        if str(p) not in self.pins:
            self.total += len(raw)
            if self.total > 64_000_000: raise ValueError('task evidence exceeds64MB')
        self.pins[str(p)] = actual; self.identities[str(p)] = identity(after)
        return raw, p

    def document(self, pin):
        raw, _ = self.file(pin)
        if len(raw) > 2_000_000: raise ValueError('task JSON exceeds2MB')
        from ravel.validation.validate_task_contract import _unique_object, _reject_constant
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)

    def capture(self, path):
        p = Path(path)
        # Name the path and the failed condition: a linked component, an absent
        # record and a non-file are different repairs for the caller.
        linked = next((q for q in (p, *p.parents) if q.is_symlink()), None)
        if linked is not None:
            raise ValueError(f'ordinary task evidence required before read: {linked} is a symbolic link')
        if not p.is_file():
            raise ValueError(f'ordinary task evidence required before read: {p} '
                             + ('is not a regular file' if p.exists() else 'does not exist'))
        size = p.stat().st_size
        if not 1 <= size <= 2_000_000: raise ValueError('task custody document size exceeds2MB before read')
        with p.open('rb') as stream: raw = stream.read(size + 1)
        pin = {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        self.file(pin)
        return pin

    def canonical(self, pin):
        _, path = self.file(pin)
        return self.pins[str(path)]

    def finish(self):
        for check in self.ending_checks: check()
        for (folder, pattern), population in self.populations.items():
            if tuple(sorted(Path(folder).rglob(pattern))) != population:
                raise ValueError('task evidence population changed during evaluation')
        if any(p.exists() or p.is_symlink() for p in self.absences):
            raise ValueError('previously absent task disclosure appeared during evaluation')
        for pin in list(self.pins.values()):
            before = self.identities[pin['path']]
            self.file(pin)
            if before != self.identities[pin['path']]: raise ValueError('task input identity changed during evaluation')
        for root, session in self.review_sessions.items():
            errors = session.finish()
            if errors: raise ValueError('contributing review custody changed before task return: ' + root + ': ' + '; '.join(errors))

    def review_session(self, root):
        from . import execution
        root = Path(root).resolve()
        if str(root) not in self.review_sessions:
            self.review_sessions[str(root)] = execution._validation_session(root)
        return self.review_sessions[str(root)]

    def absent(self, path):
        path = Path(path).absolute()
        if path.exists() or path.is_symlink(): raise ValueError('task artifact is not absent')
        self.absences.add(path)

    def population(self, folder, pattern):
        paths = tuple(sorted(Path(folder).rglob(pattern)))
        key = (str(folder), pattern)
        if key in self.populations and self.populations[key] != paths:
            raise ValueError('task evidence population changed during evaluation')
        self.populations[key] = paths
        return paths

    def close(self):
        for session in self.review_sessions.values(): session.close()
        self.review_sessions.clear()


def _contract(pin, inputs):
    from ravel.validation.validate_task_contract import validate
    contract = inputs.document(pin)
    errors = validate(contract)
    if errors: raise ValueError('invalid parent task contract: ' + '; '.join(errors))
    if 'task_requirements' not in contract: raise ValueError('parent task has no explicit obligation census')
    req = validate_requirements(contract)
    effective = {r['id']: deepcopy(r) for r in req['obligations']}
    changes = []
    for amendment in req['amendments']:
        record = inputs.document(amendment)
        ce.keys(record, ('schema_version', 'kind', 'authority', 'prompt_sha256', 'instruction', 'changes'))
        if (type(record['schema_version']) is not int or record['schema_version'] != 1 or
                record['kind'] != 'task-scope-instruction' or record['authority'] != 'direct-user-instruction' or
                record['prompt_sha256'] != req['prompt_sha256']):
            raise ValueError('material goal changes require a pinned original-request-bound user instruction')
        _text(record['instruction']); _rows(record['changes']); seen = set()
        for change in record['changes']:
            ce.keys(change, ('obligation_id', 'before_sha256', 'disposition', 'statement', 'criteria'))
            oid = change['obligation_id']
            if oid not in effective or oid in seen or ce.digest(effective[oid]) != change['before_sha256']:
                raise ValueError('scope instruction must bind each exact preceding obligation')
            seen.add(oid); _text(change['statement'])
            if change['disposition'] == 'replace': _criteria(change['criteria'])
            elif change['disposition'] != 'withdraw' or change['criteria'] is not None:
                raise ValueError('explicit replace or withdraw scope instruction required')
            changes.append({'instruction': deepcopy(amendment), 'literal_instruction': record['instruction'],
                            'before': deepcopy(effective[oid]), 'change': deepcopy(change)})
            effective[oid].update(statement=change['statement'], criteria=deepcopy(change['criteria']),
                                 withdrawn=change['disposition'] == 'withdraw')
    if changes:
        # Proposed text/actor labels are not authorization. Reuse the existing
        # original task CHECK-IN1 envelope; no extra approval for decomposition.
        _, contract_path = inputs.file(pin)
        parent = contract_path.parent.parent
        authorized = False
        from . import workflow_state
        approval_path = parent / 'inputs/checkin1_approval.json'
        if contract_path == parent / 'inputs/task_contract.json' and approval_path.is_file():
            approval = inputs.document(inputs.capture(approval_path))
            instructions = []
            for change in changes:
                if change['literal_instruction'] not in instructions: instructions.append(change['literal_instruction'])
            authorized = (not workflow_state.verify_approval(str(parent))
                          and approval.get('quote') == '\n'.join(instructions))
            if authorized:
                for path in workflow_state.approval_input_paths(str(parent)): inputs.capture(path)
        for change in changes: change['effective_authorization'] = authorized
        if not authorized:
            effective = {row['id']: deepcopy(row) for row in req['obligations']}
    return contract, req, effective, changes


def binding_projection(binding, *, base_dir):
    ce.keys(binding, ('contract', 'assignment_id')); ce.identity(binding['assignment_id'])
    if not Path(binding['contract']['path']).is_absolute():
        raise ValueError('parent assignment must bind an absolute ordinary contract path')
    inputs = _Inputs(base_dir)
    contract, req, effective, changes = _contract(binding['contract'], inputs)
    assignments = [r for r in req['assignments'] if r['id'] == binding['assignment_id']]
    if len(assignments) != 1: raise ValueError('explicit existing parent assignment required')
    inputs.finish()
    return {'kind': 'parent-task-assignment', 'contract': deepcopy(binding['contract']),
        'original_request': contract['prompt'], 'original_obligations': deepcopy(req['obligations']),
        'effective_obligations': list(effective.values()), 'scope_changes': changes,
        'assignment': deepcopy(assignments[0]), 'parent_acceptance_scope': req['parent_acceptance_scope'], 'input_pins': list(inputs.pins.values()),
        'parent_task_complete': False, 'execution_authorized': False,
        'authority_origin_authenticated': False}


FIGURE_TARGET = 'published_figure'


def _published_figure_obligations(contract, req, contract_path, inputs):
    """Obligations that owe a comparison with a published figure (intake architecture S1-10).

    A quality obligation whose criteria compare with a published figure, and every
    obligation a pinned plan's claim binds when that claim compares with one.
    """
    known = [r['id'] for r in req['obligations']]
    ids = [r['id'] for r in req['obligations'] if r['kind'] == 'quality'
           and isinstance(r['criteria'].get('comparison'), dict)
           and r['criteria']['comparison'].get('target') == FIGURE_TARGET]
    if 'request_plan' in contract:
        from ravel.validation import validate_task_contract
        rundir = contract_path.parent.parent if contract_path.parent.name == 'inputs' else contract_path.parent
        errors = validate_task_contract.validate_pins(str(rundir), contract)
        if errors: raise ValueError('pinned request plan does not verify: ' + '; '.join(errors))
        for key in validate_task_contract.PIN_KEYS:
            if inputs.capture(rundir / contract[key]['path'])['sha256'] != contract[key]['sha256']:
                raise ValueError('pinned request record changed during task evaluation')
        plan = validate_task_contract.load_pinned(str(rundir), contract, 'request_plan')
        for claim in plan['claims']:
            if claim['comparison']['target'] == FIGURE_TARGET:
                ids += [oid for oid in claim['obligation_ids'] if oid in known]
    return list(dict.fromkeys(ids))


def _figure_comparison_child(spec):
    """A figure-comparison study that digitises a published element and compares with it."""
    task = spec.get('task') if spec.get('mode') == 'figure-comparison' else None
    operations = task.get('operations') if isinstance(task, dict) else None
    kinds = {op.get('kind') for op in operations if isinstance(op, dict)} if isinstance(operations, list) else set()
    return {'digitize', 'compare'} <= kinds


def _accepted_review(rundir, scope, inputs):
    from . import physics_review
    rd = Path(rundir); rd = rd if rd.is_absolute() else inputs.base / rd
    if any(p.is_symlink() for p in (rd, *rd.parents)): raise ValueError('ordinary review root required')
    session = inputs.review_session(rd)
    view = physics_review.status(rd, _session=session)
    if view.get('state') != 'accepted' or view.get('claim_scope') != scope or physics_review.gate_errors(rd, 'delivery', _session=session):
        raise ValueError('current accepted actual review of the named scope required')
    reg, events = physics_review._read(rd, _session=session)
    cycle = physics_review._view(reg, events)['cycle']
    # Existing review implementation owns scientific decisions/holds/custody.
    # Reuse the existing full custody gate; retain its closed journal anchors,
    # not a second copy/hash of every potentially huge native input.
    paths = [rd / physics_review.HEAD, rd / physics_review.REGISTRATION, rd / physics_review.POLICY,
             rd / physics_review.DIRECTORY / 'events' / f"{cycle['sequence']:08d}.json"]
    for p in paths:
        inputs.capture(p)
    if physics_review.gate_errors(rd, 'delivery', _session=session): raise ValueError('accepted review changed during task evaluation')
    return rd, cycle


def _in_cycle(pin, rd, cycle):
    wanted = Path(pin['path']); wanted = wanted if wanted.is_absolute() else rd / wanted
    return any((Path(p['path']) if Path(p['path']).is_absolute() else rd / p['path']) == wanted
               and p['sha256'] == pin['sha256'] and p['size'] == pin['size'] for p in cycle['snapshots'])


def evaluate(request_pin, *, base_dir):
    """Retain all original obligations; accepted child scopes only contribute.

    A complete census is ready for a parent review. Final acceptance additionally
    needs an existing parent cycle bound to this request and its full evidence.
    """
    inputs = _Inputs(base_dir)
    try:
        return _evaluate(request_pin, inputs)
    finally:
        inputs.close()


def _evaluate(request_pin, inputs, *, _finish=True, _document=None):
    # A nested ordinary producer owns one final custody check after its
    # additional inputs/output are captured. Public evaluation still ends
    # here by default; this never reopens or reuses a closed review session.
    if type(_finish) is not bool: raise ValueError('exact nested ending-check flag required')
    request = inputs.document(request_pin) if _document is None else deepcopy(_document)
    ce.keys(request, ('schema_version', 'contract', 'outcomes', 'parent_review', 'report'))
    if type(request['schema_version']) is not int or request['schema_version'] != 1: raise ValueError('task completion version1 required')
    contract, req, effective, changes = _contract(request['contract'], inputs)
    _, contract_path = inputs.file(request['contract'])
    figure_ids = _published_figure_obligations(contract, req, contract_path, inputs)
    figure_compared = set()
    assignments = {r['id']: r for r in req['assignments']}
    _rows(request['outcomes'], 128, empty=True); seen = set(); children = set(); contributions = {oid: [] for oid in effective}
    for outcome in request['outcomes']:
        ce.keys(outcome, ('assignment_id', 'rundir', 'claim_scope', 'coverage')); _text(outcome['rundir']); ce.identity(outcome['claim_scope'])
        aid = outcome['assignment_id']
        if aid not in assignments: raise ValueError('existing assignment outcomes required')
        seen.add(aid); assigned = {r['obligation_id']: r for r in assignments[aid]['coverage']}
        _rows(outcome['coverage']); covered = set()
        rd = Path(outcome['rundir']); rd = rd if rd.is_absolute() else inputs.base / rd
        key = (aid, str(rd.absolute()), outcome['claim_scope'])
        if key in children: raise ValueError('duplicate child scope outcome')
        children.add(key)
        from .completion_children import specification
        _, spec_pin, spec = specification(rd, inputs)
        if spec.get('goal_binding') != {'contract': request['contract'], 'assignment_id': aid}:
            raise ValueError('child study does not bind this exact parent assignment')
        for row in outcome['coverage']:
            boundary_keys = tuple(k for k in ('boundary', 'held_node') if k in row)
            ce.keys(row, ('obligation_id', 'state', 'criteria', 'evidence', 'explanation', *boundary_keys))
            oid = row['obligation_id']; _criteria(row['criteria']); _text(row['explanation']); _rows(row['evidence'], 32, empty=True)
            if oid not in assigned or oid in covered or row['state'] not in STATES:
                raise ValueError('distinct assigned obligation statuses required')
            covered.add(oid)
            if row['criteria'] != assigned[oid]['criteria']: raise ValueError('child coverage differs from assigned scope')
            for pin in row['evidence']: inputs.file(pin)
            accepted = False
            boundary = None
            if row['state'] in ('partial', 'blocked') and boundary_keys:
                if len(boundary_keys) != 1: raise ValueError('one explicit boundary or held-node record required')
                boundary = inputs.document(row[boundary_keys[0]])
                if (boundary.get('kind') not in ('task-boundary', 'held-node')
                        or boundary.get('obligation_id') != oid or boundary.get('claim_scope') != outcome['claim_scope']
                        or not boundary.get('reason') or boundary.get('deviation') is None):
                    raise ValueError('located boundary and recorded deviation required')
                _, deviation_path = inputs.file(boundary['deviation'])
                if deviation_path.name != 'DEVIATIONS.md':
                    raise ValueError('located boundary requires recorded DEVIATIONS.md')
            if row['state'] in ('satisfied', 'negative') or boundary is not None:
                if not row['evidence']: raise ValueError('resolved or source-negative coverage requires retained evidence')
                _, cycle = _accepted_review(str(rd), outcome['claim_scope'], inputs)
                bound_pins = [row[boundary_keys[0]], boundary['deviation']] if boundary else []
                if not all(_in_cycle(inputs.canonical(p), rd, cycle) for p in [request['contract'], spec_pin, *row['evidence'], *bound_pins]):
                    raise ValueError('child review did not capture parent contract and coverage evidence')
                accepted = True
            contributions[oid].append({**deepcopy(row), 'assignment_id': aid, 'claim_scope': outcome['claim_scope'],
                'child_accepted': accepted, 'addresses_complete_criteria': row['criteria'] == effective[oid]['criteria']})
            if (oid in figure_ids and accepted and row['criteria'] == effective[oid]['criteria']
                    and _figure_comparison_child(spec)):
                figure_compared.add(oid)
        if covered != set(assigned): raise ValueError('complete assignment coverage census required, including unknowns')
    report_recipe = None
    if request['report'] is not None:
        from . import scientific_report
        report_recipe = inputs.document(request['report'])
        if 'task_completion' in report_recipe: raise ValueError('base report recipe must not contain a circular completion binding')
        scientific_report.compose(report_recipe, base_dir=inputs.base)
        for pin in scientific_report.input_pins(report_recipe, base_dir=inputs.base): inputs.file(pin)
    census = []
    for oid, row in effective.items():
        evidence = contributions[oid]
        complete = row.get('withdrawn', False) or (
            any(c['child_accepted'] and c['addresses_complete_criteria'] for c in evidence)
            and (oid not in figure_ids or oid in figure_compared))
        census.append({'id': oid, 'original': next(r for r in req['obligations'] if r['id'] == oid),
            'effective': row, 'state': 'withdrawn_by_instruction' if row.get('withdrawn', False) else 'addressed' if complete else 'open', 'contributions': evidence})
    ready = all(r['state'] != 'open' for r in census); accepted = False
    claim_records = None
    from .completion_lifecycle import required as completion_required
    from .completion_disclosure import required as disclosure_required
    parent_root = contract_path.parent.parent
    records_path = parent_root / 'inputs/claim_records.json'
    if records_path.exists() or request['parent_review'] is not None and (completion_required(contract) or disclosure_required(parent_root)):
        from .completion_claims import validate_delivery, reconcile
        claim_records = validate_delivery(parent_root, inputs.document(inputs.capture(records_path)), _inputs=inputs)
        reconcile(parent_root, claim_records, contract, inputs)
    if request['parent_review'] is not None:
        ce.keys(request['parent_review'], ('rundir', 'claim_scope'))
        if request['parent_review']['claim_scope'] != req['parent_acceptance_scope']:
            raise ValueError('parent final decision must use the original task whole-goal acceptance scope')
        owed = [oid for oid in figure_ids if oid not in figure_compared and not effective[oid].get('withdrawn', False)]
        if owed:
            raise ValueError('published-figure comparison obligation(s) ' + ', '.join(owed) + ' need an accepted '
                             "figure-comparison child that digitised the element and compared the claim's artifact with it")
        if not ready: raise ValueError('local reviews cannot accept unresolved original task obligations')
        if completion_required(contract):
            from .completion_children import ledger
            registered = ledger(parent_root, inputs)
            contributed = {(r['assignment_id'], str(Path(r['rundir']).absolute())) for r in request['outcomes']}
            if any((r['assignment_id'], r['rundir']) not in contributed for r in registered):
                raise ValueError('parent delivery cannot omit registered child nodes without outcomes')
            if any(not c['child_accepted'] for cs in contributions.values() for c in cs):
                raise ValueError('all child nodes require current accepted declared scopes or reviewed boundaries')
        if report_recipe is None: raise ValueError('final parent review requires its exact bound delivery recipe')
        required_pins = list(inputs.pins.values())
        rd, cycle = _accepted_review(request['parent_review']['rundir'], request['parent_review']['claim_scope'], inputs)
        if not all(_in_cycle(p, rd, cycle) for p in required_pins):
            raise ValueError('parent review must capture completion request and all original/child evidence')
        accepted = True
    if _finish: inputs.finish()
    figure = {'published_figure_obligations': figure_ids} if figure_ids else {}
    return {**figure, **({'claim_records': claim_records} if claim_records is not None else {}), 'kind': 'original-task-completion', 'request': deepcopy(request_pin), 'original_request': contract['prompt'],
        'original_prompt_sha256': req['prompt_sha256'], 'scope_changes': changes, 'obligation_census': census,
        'report_recipe_sha256': None if report_recipe is None else ce.digest(report_recipe),
        'unmet_obligation_ids': [r['id'] for r in census if r['state'] == 'open'],
        'unobserved_assignment_ids': sorted(set(assignments) - seen), 'ready_for_parent_review': ready,
        'parent_task_accepted': accepted, 'parent_acceptance_scope': req['parent_acceptance_scope'], 'input_pins': list(inputs.pins.values()),
        'execution_authorized': False, 'authority_origin_authenticated': False,
        'semantic_entailment_verified': False}


def _reviewed_finite_calculation(request, result, inputs):
    """A completed typed quantity keeps its reviewed original calculation scope.

    This is a delivery route, not execution authority, symbolic equivalence or
    physics certification. Other source graphs and broader research retain CI3.
    The full public evaluation has already checked both current review journals;
    this fresh observation additionally binds the exact typed result and report.
    """
    from . import intake, scientific_report, science
    import re
    contract, req, _, changes = _contract(request['contract'], inputs)
    original = initial_requirements(contract['prompt'])['obligations']
    if (contract.get('task_mode') != 'calculation'
            or contract.get('intake', {}).get('kind') != 'calculation'
            or intake.infer_kind(contract['prompt']) != 'calculation'
            # A proof/derivation request is broader than a delivered finite
            # point quantity even when the draft intake calls it calculation.
            or re.search(r'\b(?:derive|derivation|prove|proof)\b', intake.actionable_text(contract['prompt']), re.I)
            or req['obligations'] != original or req['amendments'] or changes
            or len(req['assignments']) != 1 or len(request['outcomes']) != 1
            or result['unmet_obligation_ids'] or result['unobserved_assignment_ids']
            or not result['parent_task_accepted'] or request['report'] is None):
        return False
    expected = [{'obligation_id': 'original-request', 'criteria': {'request': contract['prompt']}}]
    assignment, outcome = req['assignments'][0], request['outcomes'][0]
    if assignment['coverage'] != expected or outcome['assignment_id'] != assignment['id']:
        return False
    if (len(outcome['coverage']) != 1 or outcome['coverage'][0]['state'] != 'satisfied'
            or outcome['coverage'][0]['criteria'] != expected[0]['criteria']):
        return False
    rd = Path(outcome['rundir']); rd = rd if rd.is_absolute() else inputs.base / rd
    spec = inputs.document(inputs.capture(rd / science.SPEC))
    if (spec.get('schema_version') != 2 or spec.get('mode') != 'symbolic-evaluation'
            or spec.get('goal_binding') != {'contract': request['contract'], 'assignment_id': assignment['id']}
            or type(spec.get('task')) is not dict or set(spec['task']) != {'source', 'result'}):
        return False
    # The finite post-conversion handoff retains actual source/result pin3s.
    # Neither an arbitrary result JSON nor a symbolic backend mode is sufficient.
    source, delivered = spec['task']['source'], spec['task']['result']
    evidence = [inputs.canonical(p) for p in outcome['coverage'][0]['evidence']]
    typed_pins = [inputs.canonical(source), inputs.canonical(delivered)]
    if any(p not in evidence for p in typed_pins):
        return False
    value = inputs.document(delivered)
    keys = {'id', 'symbol', 'formula', 'status', 'symbolic_status', 'conversion_status',
            'numerical_status', 'variables', 'units', 'dimension_GeV', 'conventions',
            'assumptions', 'python_source', 'points', 'physics_validated'}
    if (type(value) is not dict or set(value) != keys
            or any(value[k] != 'delivered' for k in ('status', 'symbolic_status', 'conversion_status', 'numerical_status'))
            or value['physics_validated'] is not False
            or type(value['dimension_GeV']) is not int or not -32 <= value['dimension_GeV'] <= 32
            or type(value['assumptions']) is not list or len(value['assumptions']) > 64
            or any(type(a) is not str or not a.strip() for a in value['assumptions'])
            or type(value['points']) is not list or not 1 <= len(value['points']) <= 256
            or any(type(value[k]) is not str or not value[k].strip()
                   for k in ('id', 'symbol', 'formula', 'units', 'conventions', 'python_source'))):
        return False
    import ast, math
    try:
        tree = ast.parse(value['python_source'])
    except (SyntaxError, ValueError, TypeError):
        return False
    if (type(value['variables']) is not list or len(value['variables']) > 64
            or any(type(v) is not dict or set(v) != {'name', 'domain', 'units', 'dimension_GeV'}
                or type(v['name']) is not str or not v['name']
                or v['domain'] not in ('real', 'complex', 'positive_real', 'nonnegative_real')
                or type(v['units']) is not str or not v['units'].strip()
                or type(v['dimension_GeV']) is not int or not -32 <= v['dimension_GeV'] <= 32
                for v in value['variables'])):
        return False
    names = [v['name'] for v in value['variables']]
    if len(set(names)) != len(names):
        return False
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if (len(functions) != 1 or not isinstance(functions[0], ast.FunctionDef)
            or functions[0].name != 'result_' + value['id']
            or [a.arg for a in functions[0].args.args] != names
            or functions[0].args.posonlyargs or functions[0].args.kwonlyargs
            or functions[0].args.vararg or functions[0].args.kwarg or functions[0].args.defaults
            or len(functions[0].body) != 1 or not isinstance(functions[0].body[0], ast.Return)):
        return False
    point_ids = set()
    for point in value['points']:
        if (type(point) is not dict or set(point) != {'id', 'values', 'status', 'real', 'imag'}
                or type(point['id']) is not str or not point['id'] or point['id'] in point_ids
                or point['status'] != 'delivered' or type(point['values']) is not dict
                or set(point['values']) != set(names)):
            return False
        point_ids.add(point['id'])
        pairs = list(point['values'].values()) + [{k: point[k] for k in ('real', 'imag')}]
        if any(type(p) is not dict or set(p) != {'real', 'imag'}
               or any(type(p[k]) not in (int, float) or not math.isfinite(p[k]) for k in ('real', 'imag')) for p in pairs):
            return False
    recipe = inputs.document(request['report'])
    if ce.digest(recipe) != result['report_recipe_sha256']:
        raise ValueError('whole-parent calculation report changed after evaluation')
    report_pins = [inputs.canonical(p) for p in scientific_report.input_pins(recipe, base_dir=inputs.base)]
    return all(p in report_pins for p in typed_pins)


def require_final(request_pin, *, base_dir, _inputs=None):
    # Nested delivery consumers share one ending-custody observation. The public
    # default retains its own fresh session; this is never a cross-call cache.
    if _inputs is None:
        result = evaluate(request_pin, base_dir=base_dir)
    else:
        if type(_inputs) is not _Inputs or _inputs.base != Path(base_dir).absolute():
            raise ValueError('exact current task input session and base required')
        result = _evaluate(request_pin, _inputs)
    if not result['parent_task_accepted']: raise ValueError('original parent task remains open; progress delivery is permitted')
    final_inputs=_Inputs(Path(base_dir).resolve(strict=True))
    request=final_inputs.document(request_pin)
    parent=request.get('parent_review')
    if parent is not None:
        from . import final_results_review,physics_review as review
        contract=final_inputs.document(request['contract'])
        rd=Path(parent['rundir']);rd=rd if rd.is_absolute() else Path(base_dir)/rd
        if final_results_review.required(rd,contract=contract) and not _reviewed_finite_calculation(request,result,final_inputs):
            reg,events=review._read(review._root(rd));final=review._view(reg,events)['cycle'].get('final_results')
            if final is None:raise ValueError('whole research/analysis final delivery requires CHECK-IN 3 final-artifact review')
            if request['report'] is None:raise ValueError('current whole-parent final report recipe required')
            base_recipe=final_inputs.document(request['report'])
            if ce.digest(base_recipe)!=result['report_recipe_sha256']:raise ValueError('whole-parent report recipe changed after evaluation')
            from . import scientific_report
            final_recipe={**deepcopy(base_recipe),'task_completion':deepcopy(request_pin),'delivery':'final'}
            draft=scientific_report.prepare_final(final_recipe,base_dir=base_dir)
            result['final_results_review']=final_results_review.gate(rd,final['manifest'],report=draft['report_text'],recipe=final_recipe)
    final_inputs.finish()
    return result


def final_gate(root):
    """Whole-task delivery at its existing final review root, never a launch gate.

    The prospective completion record is an ordinary review input. Progress and
    existing scoped delivery retain their own gates without this final label.
    """
    root = Path(root).absolute()
    inputs = _Inputs(root)
    pin = inputs.capture(root / 'inputs/task_completion.json')
    request = inputs.document(pin)
    parent = request.get('parent_review')
    if type(parent) is not dict or type(parent.get('rundir')) is not str:
        raise ValueError('whole-task delivery needs its actual parent final review')
    reviewed = Path(parent['rundir'])
    reviewed = reviewed if reviewed.is_absolute() else root / reviewed
    if '..' in reviewed.parts or any(p.is_symlink() for p in (reviewed, *reviewed.parents)) or reviewed.resolve() != root.resolve():
        raise ValueError('whole-task delivery must bind this exact parent review root')
    result = require_final(pin, base_dir=root)
    inputs.finish()
    return result


def register_child(child, binding, *, run_kind):
    from .completion_children import register_child as register
    return register(child, binding, run_kind=run_kind)


def compose(parent_rundir, *, write=True):
    """AI15: derive one parent's child outcomes and coverage from current custody.

    A composition is a projection for review, never a cached acceptance token.
    Each child publishes inputs/completion_outcome.json using the existing
    evaluation outcome schema. Missing or refused children remain visible.
    """
    from . import completion_children as children, completion_choices, state_io, execution
    parent = Path(parent_rundir).absolute(); inputs = _Inputs(parent)
    try:
        cp = inputs.capture(parent / 'inputs/task_contract.json')
        contract, req, effective, _ = _contract(cp, inputs)
        assignments = {r['id']: r for r in req['assignments']}
        rows = children.ledger(parent, inputs)
        outcomes = []; covered = {oid: [] for oid in effective}; accepted = []
        for index, row in enumerate(rows, 1):
            aid = row['assignment_id']
            if aid not in assignments: raise ValueError('registered child has no existing assignment')
            rd = Path(row['rundir']); oid = 'O' + str(index)
            item = {'id': oid, 'assignment_ids': [aid],
                    'obligation_ids': [r['obligation_id'] for r in assignments[aid]['coverage']],
                    'child': {'rundir': str(rd), 'run_kind': row['run_kind'], 'contract_sha256': None},
                    'deliverables': [], 'accepted_review': None, 'status': 'pending'}
            path = rd / 'inputs/completion_outcome.json'
            if not path.exists(): path = rd / 'outputs/completion_outcome.json'
            try:
                kind, spec_pin, spec = children.specification(rd, inputs)
                item['child']['contract_sha256'] = spec_pin['sha256']
                if kind != row['run_kind'] or spec.get('goal_binding') != {'contract': cp, 'assignment_id': aid}:
                    raise ValueError('child registration differs from its actual parent binding')
                if path.exists():
                    outcome_pin = inputs.capture(path); outcome = inputs.document(outcome_pin)
                    if outcome['assignment_id'] != aid or Path(outcome['rundir']).absolute() != rd:
                        raise ValueError('child outcome contradicts registration')
                    prospective = {'schema_version': 1, 'contract': cp, 'outcomes': [outcome],
                                   'parent_review': None, 'report': None}
                    # Reuse the complete original-task evaluator without writing
                    # a temporary request or taking authority from status strings.
                    result = _evaluate_document(prospective, inputs)
                    deliverables = [inputs.canonical(p) for r in outcome['coverage'] for p in r['evidence']]
                    item['deliverables'] = list({p['path']: p for p in deliverables}.values())
                    if all(r['state'] != 'open' for r in result['obligation_census'] if r['id'] in item['obligation_ids']):
                        _, cycle = _accepted_review(str(rd), outcome['claim_scope'], inputs)
                        item['accepted_review'] = {'scope': outcome['claim_scope'], 'journal_event_sha256': cycle['sha256']}
                        item['status'] = 'accepted'; accepted.append(outcome)
                        for ident in item['obligation_ids']: covered[ident].append(oid)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                item['status'] = 'refused'; item['reason'] = str(exc)
            outcomes.append(item)
        # Evaluate all accepted contributions together: includes the published
        # figure obligation and prevents an individually accepted subset from
        # silently closing the whole domain.
        full = _evaluate_document({'schema_version': 1, 'contract': cp, 'outcomes': accepted,
                                   'parent_review': None, 'report': None}, inputs)
        roots = list(dict.fromkeys([parent, *[Path(r['rundir']) for r in rows]]))
        result = {'schema_version': 1, 'kind': 'task-composition', 'parent': str(parent),
                  'prompt_sha256': req['prompt_sha256'], 'outcomes': outcomes, 'coverage': covered,
                  'uncovered': full['unmet_obligation_ids'], 'ci3_list': completion_choices.census(roots, inputs),
                  'composed_utc': execution.utc_now(),
                  'ready_for_parent_review': not full['unmet_obligation_ids'] and all(r['status'] == 'accepted' for r in outcomes)}
        if write:
            state_io.atomic_json(parent / 'outputs/completion/composition.json', result)
        inputs.finish()
        return result
    finally: inputs.close()


def _evaluate_document(request, inputs):
    # Share exactly the evaluator's input/review sessions, without a temporary
    # file or mutation of the caller's captured request documents.
    return _evaluate(None, inputs, _finish=False, _document=request)


def _write_qualified_bytes(path, raw):
    import os
    import tempfile
    descriptor, temporary = tempfile.mkstemp(prefix='.qualified-deviation-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_qualified_deviation(path, text):
    _write_qualified_bytes(path, text.encode('utf-8'))


def _qualified_json_bytes(value):
    # Match state_io.atomic_json exactly, including its trailing newline.
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _restore_qualified_publication(previous, attempted):
    """Undo only this attempt's unchanged bytes; preserve separate edits."""
    errors = []
    for path, prior in previous.items():
        if path not in attempted:
            continue
        try:
            if any(p.is_symlink() for p in (path, *path.parents)):
                errors.append('preserved changed reporting path: ' + path.name)
                continue
            if not path.exists() and prior is None:
                continue
            if not path.is_file():
                errors.append('preserved changed reporting path: ' + path.name)
                continue
            current = path.read_bytes()
            if current == prior:
                continue  # The failed atomic write never replaced this file.
            if current != attempted[path]:
                errors.append('preserved changed reporting path: ' + path.name)
                continue
            if prior is None:
                path.unlink()
            else:
                _write_qualified_bytes(path, prior)
        except (OSError, ValueError) as exc:
            errors.append(path.name + ': ' + str(exc))
    return errors


def qualified_delivery(rundir, *, completion_request=None, claim_package=None):
    """Serialize reporting before observing its sources, never grant authority."""
    from .state_io import file_lock
    root = Path(rundir).absolute()
    # Validate the ordinary root before creating any output or lock file.
    inputs = _Inputs(root)
    inputs.close()
    folder = root / 'outputs/completion'
    if any(p.is_symlink() for p in (folder / 'qualified.lock', folder, *folder.parents)):
        raise ValueError('ordinary qualified delivery output paths required')
    folder.mkdir(parents=True, exist_ok=True)
    with file_lock(folder / 'qualified.lock'):
        return _qualified_delivery_locked(root, completion_request=completion_request, claim_package=claim_package)


def _qualified_delivery_locked(rundir, *, completion_request=None, claim_package=None):
    """Write an honest bounded ending without passing any delivery/compute gate.

    An optional completion request supplies already reviewed contributions through
    the ordinary evaluator. Without it, every original obligation remains blocked.
    A supplied claim package uses the existing final disposition validator and
    withdraws its planned claims; this fallback never establishes new claims.
    """
    from . import physics_review, scientific_autonomy, finding_routing, manuscript_claim_disposition
    from . import execution, state_io
    root = Path(rundir).absolute(); inputs = _Inputs(root)
    try:
        session = inputs.review_session(root)
        review = physics_review.status(root, _session=session)
        if review['state'] == 'invalid':
            raise ValueError('qualified delivery requires intact review custody: ' + '; '.join(review['errors']))
        registration, _ = physics_review._read(root, _session=session)
        # Reporting a terminal state is allowed; changing the approved original
        # request or its policy while retaining that journal is not.
        physics_review._base_live(root, registration, _session=session)
        if not (review['waiting_for_human'] or review['limitation_candidates']):
            raise ValueError('qualified delivery requires exhausted bounds or an escalated review')
        contract_path = root / 'inputs/task_contract.json'
        if not contract_path.is_file():
            from . import science
            spec = inputs.document(inputs.capture(root / science.SPEC))
            binding = spec.get('goal_binding')
            if type(binding) is not dict or 'contract' not in binding:
                raise ValueError('qualified delivery requires the original obligation contract')
            contract_pin = binding['contract']
        else:
            contract_pin = inputs.capture(contract_path)
        contract, req, effective, changes = _contract(contract_pin, inputs)
        _, document = scientific_autonomy.observed_run_document(root)
        delegation = scientific_autonomy.declaration(document, root) if document else None
        if delegation:
            for path in scientific_autonomy.input_paths(document, root):
                inputs.capture(path)
        revoked = root / scientific_autonomy.REVOCATION
        delegation_status = 'absent' if delegation is None else 'recorded'
        if delegation is not None and revoked.exists():
            inputs.capture(revoked)
            delegation_status = 'revoked'
        evaluation = None
        if completion_request is not None:
            request = inputs.document(completion_request)
            if inputs.canonical(request['contract']) != inputs.canonical(contract_pin):
                raise ValueError('qualified delivery cannot substitute the original contract')
            evaluation = _evaluate(completion_request, inputs, _finish=False)
        census = {r['id']: r for r in evaluation['obligation_census']} if evaluation else {}
        findings = deepcopy(review['unresolved_findings'])
        for row in review['limitation_census']:
            if row['finding'] not in findings:
                findings.append(deepcopy(row['finding']))
        reason = (review['waiting_for_human'] or {}).get('reason', 'Repeated redos made no evidenced progress.')
        obligations = []
        for original in req['obligations']:
            item = census.get(original['id'], {})
            contributions = item.get('contributions', [])
            complete = [c for c in contributions if c['child_accepted'] and c['addresses_complete_criteria']
                        and item.get('state') == 'addressed']
            states = {c['state'] for c in complete}
            state = ('satisfied' if states == {'satisfied'} else 'negative' if states == {'negative'} else
                     'partial' if any(c['child_accepted'] and c['state'] in ('satisfied', 'negative', 'partial')
                                      for c in contributions) else 'blocked')
            if effective[original['id']].get('withdrawn'):
                state = 'blocked'
            obligations.append({'obligation_id': original['id'], 'original': deepcopy(original),
                'state': state, 'contributions': deepcopy(contributions),
                'boundary_reason': reason if state in ('blocked', 'partial') else
                    'Only the existing accepted contribution and its exact scope are reported; no new acceptance.'})
        dispositions = []
        for row in finding_routing.limitation_census(findings):
            existing = next((r for r in dispositions if r['planned_claim_id'] == row['claim_id']), None)
            if existing:
                if row['bound'] not in existing['reason']:
                    existing['reason'] += '; ' + row['bound']
            else:
                dispositions.append({'planned_claim_id': row['claim_id'], 'disposition': 'withdrawn',
                                     'reason': reason + ' ' + row['bound']})
        claim_prose = None
        if claim_package is not None:
            package = inputs.document(claim_package)
            ce.keys(package, ('plan', 'rows', 'value', 'evidence'))
            if any(r.get('disposition') != 'withdrawn' for r in package['rows']):
                raise ValueError('an exhausted-run fallback can only withdraw supplied planned claims')
            dispositions = manuscript_claim_disposition.validate(package['plan'], package['rows'],
                package['value'], package['evidence'], final=True, review_findings=findings)
            claim_prose = package['value']
        finding_routing.require_dispositions(findings, dispositions)
        result = {'schema_version': 1, 'kind': 'qualified-task-delivery', 'rundir': str(root),
            'label': 'machine-produced under delegation' if delegation_status == 'recorded' else 'machine-produced status summary',
            'delegation_status': delegation_status,
            'contract': inputs.canonical(contract_pin), 'original_request': contract['prompt'],
            'obligations': obligations, 'scope_changes': changes, 'unresolved_findings': findings,
            'limitation_candidates': review['limitation_candidates'], 'claim_dispositions': dispositions,
            'claim_prose': claim_prose, 'scientific_claims_adopted': [],
            'review_state': review['state'], 'waiting_for_human': review['waiting_for_human'],
            'parent_task_accepted': False, 'execution_authorized': False,
            'authority_origin_authenticated': False, 'semantic_entailment_verified': False}
        # Retain consumed pins; the one-shot custody sessions are finished only
        # immediately before publishing the final report, after intermediate writes.
        result['input_pins'] = list(inputs.pins.values())
        identity = execution.digest(result)
        folder = root / 'outputs/completion'
        deviation = root / 'DEVIATIONS.md'
        targets = [deviation, folder / 'qualified-delivery.json', folder / 'qualified-boundary.json']
        for target in targets:
            if any(p.is_symlink() for p in (target, *target.parents)):
                raise ValueError('ordinary qualified delivery output paths required')
        previous = {target: target.read_bytes() if target.exists() else None
                    for target in (deviation, folder / 'qualified-boundary.json', folder / 'qualified-delivery.json')}
        attempted = {}
        prior = previous[deviation].decode('utf-8') if previous[deviation] is not None else '# Deviations\n'
        try:
            marker = 'qualified-delivery:' + identity
            if marker not in prior:
                entry = '\n\n## Qualified delivery boundary\n\n' + marker + '\n\n' + reason + '\n\n'
                entry += '\n'.join('- ' + r['obligation_id'] + ': ' + r['state'] + '. ' + r['boundary_reason'] for r in obligations)
                entry += '\n\nMachine-produced; no new scientific acceptance or execution authorization.\n'
                attempted[deviation] = (prior + entry).encode('utf-8')
                _write_qualified_deviation(deviation, prior + entry)
            deviation_pin = {'path': str(deviation), 'sha256': execution.file_hash(deviation), 'size': deviation.stat().st_size}
            boundary = {'schema_version': 1, 'kind': 'task-boundary', 'delivery_sha256': identity,
                        'reason': reason, 'deviation': deviation_pin,
                        'obligations': [{'obligation_id': r['obligation_id'], 'state': r['state'],
                                         'reason': r['boundary_reason']} for r in obligations],
                        'execution_authorized': False}
            boundary_path = folder / 'qualified-boundary.json'
            attempted[boundary_path] = _qualified_json_bytes(boundary)
            state_io.atomic_json(boundary_path, boundary)
            boundary_pin = {'path': str(boundary_path), 'sha256': execution.file_hash(boundary_path),
                            'size': boundary_path.stat().st_size}
            for index, row in enumerate(result['obligations']):
                row['boundary'] = {'artifact': boundary_pin, 'location': '$.obligations[' + str(index) + ']'}
                row['deviation'] = deviation_pin
            result['deviation'] = deviation_pin
            # Intermediate publication can run injected or external writers. Recheck
            # every captured source immediately before publishing the final report.
            inputs.finish()
            delivery_path = folder / 'qualified-delivery.json'
            attempted[delivery_path] = _qualified_json_bytes(result)
            state_io.atomic_json(delivery_path, result)
        except Exception as exc:
            repairs = _restore_qualified_publication(previous, attempted)
            if repairs:
                raise ValueError(str(exc) + '; reporting repair incomplete: ' + '; '.join(repairs)) from exc
            raise
        return result
    finally:
        inputs.close()


def main(argv=None):
    """Read-only public projection; it never approves or executes a study."""
    import argparse
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'qualified':
        parser = argparse.ArgumentParser(prog='ravel task-completion qualified')
        parser.add_argument('--rundir', type=Path, required=True)
        parser.add_argument('--request', type=Path)
        parser.add_argument('--claim-package', type=Path)
        args = parser.parse_args(argv[1:])
        try:
            with_inputs = _Inputs(args.rundir)
            try:
                request = with_inputs.capture(args.request.absolute()) if args.request else None
                claims = with_inputs.capture(args.claim_package.absolute()) if args.claim_package else None
            finally:
                with_inputs.close()
            result = qualified_delivery(args.rundir, completion_request=request, claim_package=claims)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.exit(1, str(exc) + '\n')
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    if argv and argv[0] == 'compose':
        parser = argparse.ArgumentParser(prog='ravel task-completion compose')
        parser.add_argument('--rundir', type=Path, required=True)
        parser.add_argument('--no-write', action='store_true')
        args = parser.parse_args(argv[1:])
        try: result = compose(args.rundir, write=not args.no_write)
        except (OSError, ValueError, KeyError, TypeError) as exc: parser.exit(1, str(exc) + '\n')
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    parser = argparse.ArgumentParser(prog='ravel task-completion')
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--require-final', action='store_true')
    args = parser.parse_args(argv)
    base = args.base if args.base is not None else args.request.absolute().parent
    try:
        inputs = _Inputs(base)
        request_pin = inputs.capture(args.request.absolute())
        function = require_final if args.require_final else evaluate
        result = function(request_pin, base_dir=base)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
