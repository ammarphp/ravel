"""Finite scientific calculation completion fixture, authored without execution.

Public symbolic conversion and task/review/report consumers are real. The external
converter returns an explicit synthetic constant and never calls a CAS. Compute
approval, execution receipt and reviewers are exactly the established inert unit
fixture seams, not scientific execution or physics acceptance. No subprocess is
launched by this fixture. The tested claim is source/custody/consumer connectivity.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import sys
from ravel.workflow import execution, physics_review as pr, waypoint_evidence as waypoint, workflow_state
from ravel.workflow import physics_review as review, science, task_completion as tc, scientific_report as sr
from ravel.workflow.state_io import atomic_json, read_json
from ravel.physics import symbolic_evaluation as symbolic

def policy():
    return {"schema_version": 1,
        "actors": {"proposer": "worker", "executor": "worker", "physics_decider": "physicist", "skeptical_verifier": "skeptic", "physics_critic": "critic"},
        "max_redos": 2, "allowed_changed_paths": ["inputs/settings.cfg"], "allowed_stages": ["detector"],
        "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "agreement", "kind": "scientific"}],
        "claim_scopes": {"diagnostic": {"checks": ["integrity"], "actions": ["delivery"]},
            "reproduction": {"checks": ["integrity", "agreement"], "actions": ["bulk", "delivery", "reuse"]}}}

def make_attempt(root, *, value=1, extra_inputs=()):
    # A deliberately small execution receipt avoids binding concurrently edited
    # development source files; execution's package-hashing tests live elsewhere.
    inputs = ["inputs/settings.cfg", "inputs/held-fixed.txt", *extra_inputs]
    spec = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()),
        "inputs": inputs, "outputs": ["outputs/produced.json"], "input_snapshot": execution.snapshot(root, inputs),
        "parents": {}, "runtime": execution.runtime_context()}
    spec["fingerprint"] = execution.digest(spec)
    record = execution.begin_attempt(root, "detector", spec, "logs/detector.log")
    atomic_json(root / "outputs/produced.json", {"value": value})
    (root / "logs/detector.log").write_text(f"generated value {value}\n")
    assert execution.finish_attempt(root, record, 0) == 0
    return record

def check_packet(root, record, *, agreement="pass", integrity="pass"):
    atomic_json(root / "inputs/comparison.json", {"status": "pass" if agreement == "pass" else "fail",
        "summary": "Declared comparison", "diagnostics": {"residual": 0 if agreement == "pass" else .2}})
    manifest = waypoint.create(root, produced="outputs/produced.json", reference="inputs/reference.json",
        comparison="inputs/comparison.json", inputs=["inputs/settings.cfg"])
    atomic_json(root / waypoint.MANIFEST, manifest)
    atomic_json(root / "inputs/checkin2.json", {"sections": {"evidence_manifest": waypoint.MANIFEST}})
    atomic_json(root / "inputs/checks.json", {"schema_version": 1, "checks": [
        {"id": cid, "status": status, "evidence": [{"path": "outputs/produced.json", "location": "$.value"}],
         "attempt_ids": [record["attempt_id"]]} for cid, status in (("integrity", integrity), ("agreement", agreement))]})

def accept(root, *, scope="reproduction", closes=()):
    """Critic, skeptic and decider accept through bound responses; declared names are advice."""
    from bound_review import bound_accept
    return bound_accept(root, scope=scope, closes=list(closes))

def review_run(root, extra_inputs, monkeypatch, *, scope="diagnostic"):
    p = policy(); p["claim_scopes"]["original_task_completion"] = {"checks": ["integrity", "agreement"], "actions": ["delivery", "reuse"]}
    (root / 'inputs').mkdir(parents=True, exist_ok=True)
    atomic_json(root / pr.POLICY, p)
    atomic_json(root / 'inputs/checkin1_approval.json', {'fixture': 'mocked compute approval only'})
    monkeypatch.setattr(pr, '_science_run', lambda root: False)
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'synthetic no-child hardware description')
    monkeypatch.setattr(workflow_state, 'approval_input_paths', lambda rd: [str(Path(rd) / pr.POLICY)])
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    (root / 'inputs/settings.cfg').write_text('synthetic=1\n')
    (root / 'inputs/held-fixed.txt').write_text('fixed\n')
    atomic_json(root / 'inputs/reference.json', {'reference': 1})
    record = make_attempt(root, extra_inputs=extra_inputs)
    check_packet(root, record)
    pr.open_cycle(root, effective_settings=['inputs/settings.cfg'], stage_receipts=[record['attempt_record']], check_results='inputs/checks.json')
    accept(root, scope=scope)
    return root


def pin(path):
    raw = Path(path).read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)
    return pin(path)


class InertConverter:
    """Disclosed external API stand-in: constant transport, no physical model."""
    def mathematica_to_sympy(self, formula):
        assert formula == '0'
        return SimpleNamespace(free_symbols=set())

    def mathematica_to_python_source(self, formula, names, *, function_name, dimension_comment):
        assert formula == '0' and names == [] and dimension_comment is False
        return 'def ' + function_name + '():\n    return 0\n'

    def mathematica_to_callable(self, formula, names):
        assert formula == '0' and names == []
        return lambda: 0


def typed_child(base, contract_pin, monkeypatch):
    """Real typed symbolic producer plus existing source-bound review journal.

    No vendor kernel, physical model, compute approval or reviewer inference is
    performed. These seams are explicitly inert; the delivered unit/source and
    the actual task/review consumers are not replaced with return-value mocks.
    """
    root = base / 'symbolic-child'
    source = root / 'inputs/original-formula.txt'
    source.parent.mkdir(parents=True)
    source.write_text('0\nSynthetic constant in declared GeV units; not a physical decay calculation.\n')
    declaration = {'id': 'width', 'symbol': 'width', 'variables': [], 'units': 'GeV', 'dimension_GeV': 1,
        'conventions': 'Explicit inert transport constant; no physical vertex asserted.',
        'assumptions': ['Engineering source/custody fixture; numerical physics unqualified.'],
        'points': [{'id': 'constant', 'values': {}}]}
    # The conversion is one supervised stage of the child, so the delivered typed result
    # is an emitted output of a current successful receipt. The command is inert; the
    # fixture performs the conversion between the attempt's opening and its receipt.
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'synthetic no-child hardware description')
    stage = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()),
        "inputs": ["inputs/original-formula.txt"], "outputs": ["outputs/symbolic-result.json"],
        "input_snapshot": execution.snapshot(root, ["inputs/original-formula.txt"]),
        "parents": {}, "runtime": execution.runtime_context()}
    stage["fingerprint"] = execution.digest(stage)
    conversion = execution.begin_attempt(root, "symbolic", stage, "logs/symbolic.log")
    # This is the production converter consumer; no hand-authored result bypass.
    converted = symbolic.convert_result({'id': 'width', 'symbol': 'width', 'formula': '0'}, declaration, InertConverter())
    result_pin = write(root / 'outputs/symbolic-result.json', converted)
    (root / "logs/symbolic.log").write_text("inert symbolic conversion fixture; no kernel\n")
    assert execution.finish_attempt(root, conversion, 0) == 0
    source_pin = pin(source)
    spec_pin = write(root / science.SPEC, {'schema_version': 2, 'mode': 'symbolic-evaluation',
        'source': 'Explicit inert symbolic conversion test; not an executable provider configuration',
        'goal_binding': {'contract': contract_pin, 'assignment_id': 'original-task'},
        'task': {'source': source_pin, 'result': result_pin}})
    contract = read_json(contract_pin['path'])
    assignment = next(r for r in contract['task_requirements']['assignments'] if r['id'] == 'original-task')
    outcome = {'assignment_id': 'original-task', 'rundir': str(root), 'claim_scope': 'diagnostic',
        'coverage': [{**deepcopy(row), 'state': 'satisfied', 'evidence': [source_pin, result_pin],
            'explanation': 'Synthetic reviewer fixture covers the complete original request; not physical entailment.'}
            for row in assignment['coverage']]}
    review_run(root, [contract_pin['path'], spec_pin['path'], source_pin['path'], result_pin['path']], monkeypatch)
    return outcome, converted, source_pin, result_pin


def report_recipe(base, converted, source_pin, result_pin):
    """Actual delivered quantity drives the recipe; all original typed rows retained."""
    # Artifact/report inputs are relative to the report base. Keep the exact
    # original byte/size commitments used by the child review; change only this
    # API's required path representation, never its source or units.
    def relative(original):
        return {**original, 'path': Path(original['path']).relative_to(base).as_posix()}
    point = converted['points'][0]
    tool = write(base / 'quantity.json', {'rows': [{'id': converted['id'], 'real': point['real'], 'imag': point['imag']}]})
    artifact = {'schema_version': 1, 'basis': [relative(source_pin), relative(result_pin)], 'tools': {'symbolic': relative(tool)},
        'contract': {'source_scope': 'One declared inert symbolic result and its complete numeric point; physics unqualified.',
            'tool_fields': [{'field': 'rows', 'type': {'type': 'array', 'items': {'type': 'object',
                'properties': {'id': 'string', 'real': 'number', 'imag': 'number'}}, 'max_items': 1},
                'source': {'kind': 'direct', 'tool_id': 'symbolic', 'pointer': '/rows'}}],
            'interpretation_fields': ['qualification'], 'unresolved_semantics': [], 'max_artifact_bytes': 32000},
        'interpretation': {'qualification': 'No physical decay-width validation or real model execution.'}}
    facts = [{'id': field, 'selector': {'kind': 'record', 'pointer': '/rows', 'id_field': 'id',
        'row_id': converted['id'], 'field': field}, 'quantity_id': None, 'context_selector': None,
        'label': field + ' component', 'unit': converted['units'], 'scope': 'source_bound_inert_symbolic_delivery',
        'population': 'complete declared constant point', 'limitations': ['No native/CAS/model execution or physics certificate.']}
        for field in ('real', 'imag')]
    return {'schema_version': 1, 'title': 'Complete original calculation delivery control',
        'artifact_request': artifact, 'context': None, 'facts': facts,
        'sections': [{'id': 'table', 'kind': 'table', 'caption': 'Both declared complex components and exact source unit.',
            'columns': ['Real', 'Imaginary'], 'rows': [{'id': 'width', 'facts': ['real', 'imag']}]}],
        'interpretation': ['Engineering consumer connectivity only; original physical validation remains unqualified.']}


def deliver_claims(parent, contract_pin, outcome, converted, result_pin):
    """Delivered claim records that a current-epoch parent owes before its final review.

    The child is registered with the parent, the claim binds the child's emitted typed
    result through its conversion receipt, and its trial count comes from a retained
    selection record. Every record is computed by the production functions; the claim
    carries no validator and so no certification. A research parent additionally owes
    the computed disclosure of its (here empty) candidate funnel.
    """
    from ravel.workflow import completion_children, completion_claims, completion_disclosure, completion_lifecycle
    contract = read_json(contract_pin['path'])
    if not completion_lifecycle.required(contract):
        return None
    child = Path(outcome['rundir'])
    completion_children.register_child(child, read_json(child / science.SPEC)['goal_binding'], run_kind='science')
    receipt = pin(child / execution.load_execution(child)['stages']['symbolic']['attempt_record'])
    value = converted['points'][0]['real']
    research = completion_disclosure.required(parent)
    if research:
        selection = write(parent / 'research/selection.json', {'n_trials': 0, 'trials': [], 'selected_candidate': None,
            'selected_result_on_confirm': None, 'best_of_n_select': None, 'objective': 'maximize',
            'rule': 'No research candidate was generated, screened or tried; the funnel is empty.'})
    else:
        selection = write(parent / 'inputs/claim-selection.json', {'n_trials': 1,
            'trials': [{'id': 'T1', 'candidate': 'declared-point', 'select': value, 'confirm': value}],
            'selected_candidate': 'declared-point', 'selected_result_on_confirm': value, 'best_of_n_select': value,
            'objective': 'maximize', 'rule': 'One deterministic evaluation of the declared point; no alternative was tried.'})
    declared = (['C1'] if 'request_plan' not in contract else
                [row['id'] for row in read_json(parent / contract['request_plan']['path'])['claims']])
    document = {'claims': [{'id': identity, 'rundir': str(child), 'quantity': result_pin, 'quantity_pointer': '/points/0/real',
        'execution_receipts': [receipt], 'validator_receipts': [], 'n_trials': 0 if research else 1, 'selection': selection}
        for identity in declared]}
    if research:
        document['disclosure'] = completion_disclosure.build(parent)
    records = completion_claims.validate_delivery(parent, document)
    assert [row['fidelity'] for row in records['claims']] == ['executed'] * len(declared)
    assert not any(row['certified'] for row in records['claims'])
    return write(parent / 'inputs/claim_records.json', document)


def complete_parent(parent, contract_pin, monkeypatch, *, accept_parent=True):
    outcome, converted, source_pin, result_pin = typed_child(parent, contract_pin, monkeypatch)
    recipe_pin = write(parent / 'report-recipe.json', report_recipe(parent, converted, source_pin, result_pin))
    # Written before the readiness evaluation, so the whole-parent review captures them.
    deliver_claims(parent, contract_pin, outcome, converted, result_pin)
    completion = {'schema_version': 1, 'contract': contract_pin, 'outcomes': [outcome],
                  'parent_review': None, 'report': recipe_pin}
    request_pin = write(parent / 'inputs/task_completion.json', completion)
    ready = tc.evaluate(request_pin, base_dir=parent)
    assert ready['ready_for_parent_review'] and not ready['parent_task_accepted']
    if accept_parent:
        review_root = parent / 'whole-parent-review'
        completion['parent_review'] = {'rundir': str(review_root), 'claim_scope': 'original_task_completion'}
        request_pin = write(parent / 'inputs/task_completion.json', completion)
        review_run(review_root, [request_pin['path'], *[p['path'] for p in ready['input_pins']
            if p['path'] != request_pin['path']]], monkeypatch, scope='original_task_completion')
    return request_pin, outcome, converted, source_pin, result_pin
