"""Supplied fit campaigns with accepted-law admission and full return retention.

The ordinary scientific lifecycle owns launch admission. Source compatibility is
byte custody; independent endpoint comparison grants no globality or coverage.
"""
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import time

import numpy as np

from ravel.physics import finite_mc_model as fm
from ravel.physics import joint_qualification as q
from ravel.physics.mc_auxiliary import compact, _read, MCAuxiliaryBlock, prepare as prepare_mc, _ledger
from ravel.physics.published_background import inspect_workspace
from ravel.physics.quantities import _keys, _number, _text
from ravel.workflow import execution, physics_review
from ravel.workflow.finite_grid import required, identifier, coordinates, delivery, write_delivery, SpecificationError


LAW_SCOPE = "full_source_law_gradient_qualification"
RUNTIME_MODULES = (
    "ravel.physics.joint_analytic", "ravel.physics.joint_profile",
    "ravel.physics.joint_likelihood", "ravel.physics.published_background",
    "ravel.physics.mc_auxiliary", "ravel.physics.finite_mc_model",
    "ravel.physics.statistical_model", "ravel.physics.quantities",
    "ravel.physics.published_model", "ravel.physics.joint_qualification",
)
MAX_CAPTURE_BYTES = 64 * 1024**2
MAX_SNAPSHOT_BYTES = 16 * 1024**2
MAX_OUTPUT_BYTES = 144 * 1024**2
MAX_JOURNAL_BYTES = 1024**2
MAX_ORACLE_RETURN_BYTES = 1024**2
_COMPATIBILITY_SEAL = object()


class _SourceCompatibility:
    """Factory-produced byte-custody proof, never a scientific admission token."""
    def __init__(self, seal, design, law, payload, captured):
        if seal is not _COMPATIBILITY_SEAL:
            raise ValueError("source compatibility must be produced by bounded byte validation")
        self._seal = seal
        self._design_sha = _digest(design); self._law_sha = _digest(law)
        self._payload = compact(payload)
        self._pins = tuple((p, hashlib.sha256(raw).hexdigest()) for p, raw in captured.items())

    def check(self, design, law, captured):
        if (self._seal is not _COMPATIBILITY_SEAL or self._design_sha != _digest(design)
                or self._law_sha != _digest(law)
                or any(p not in captured or hashlib.sha256(captured[p]).hexdigest() != sha for p, sha in self._pins)):
            raise ValueError("source compatibility proof differs from exact design/law/captured bytes")
        return json.loads(self._payload)


def validate(task):
    _keys(task, ("input",), label="private score experiment task")
    _text(task["input"], "input")
    return deepcopy(task)


def _digest(value):
    return hashlib.sha256(compact(value)).hexdigest()


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("exact lowercase SHA256 required")
    return value


def _pin(pin, base, captured):
    _keys(pin, ("path", "sha256"), label="input pin")
    _sha(pin["sha256"])
    path = fm._regular(pin["path"], base)
    raw = _read(path)
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("pinned input changed: " + str(path))
    if str(path) in captured and captured[str(path)] != raw:
        raise ValueError("input changed between captures")
    captured[str(path)] = raw
    if sum(map(len, captured.values())) > MAX_CAPTURE_BYTES:
        raise ValueError("64 MiB captured input ceiling")
    return path, json.loads(raw)


def _prepare(document):
    required(document, ("schema_version", "design", "law_prerequisite", "parent_qualification"))
    _keys(document, ("schema_version", "design", "law_prerequisite", "parent_qualification"), label="fit campaign input")
    _keys(document["parent_qualification"], ("contract", "receipt"), label="historical qualification pins")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("score experiment schema must be integer 1")
    _keys(document["design"], ("path", "sha256"), label="exact design pin")
    _sha(document["design"]["sha256"])
    p = document["law_prerequisite"]
    _keys(p, ("run_directory", "run_id", "cycle_id", "claim_scope", "review_snapshot_sha256",
              "review_event_sha256", "artifacts", "runtime_sources", "joint_contract_sha256_per_case"),
          label="accepted upstream law prerequisite")
    for key in ("run_directory", "run_id", "cycle_id", "claim_scope"):
        _text(p[key], key)
    if p["claim_scope"] != LAW_SCOPE:
        raise ValueError("scientific full-law-gradient acceptance is required, not custody-only reuse")
    _sha(p["review_snapshot_sha256"])
    _keys(p["review_event_sha256"], physics_review.ROLES, label="all three actual role decisions")
    for value in p["review_event_sha256"].values():
        _sha(value)
    _keys(p["artifacts"], ("spec", "input", "result", "compiled", "receipt"), label="upstream law artifacts")
    _keys(p["runtime_sources"], RUNTIME_MODULES, label="qualified numerical runtime source mapping")
    if not isinstance(p["joint_contract_sha256_per_case"], dict) or not p["joint_contract_sha256_per_case"]:
        raise SpecificationError("missing_input", "joint_contract_sha256_per_case")
    for identity in p["joint_contract_sha256_per_case"]: identifier(identity)
    for value in p["joint_contract_sha256_per_case"].values():
        _sha(value)
    return deepcopy(document)


def _resolve_review_pin(root, pin):
    return str(fm._regular(pin["path"], root))


def _qualification(document, base_dir, captured):
    """Pinned generic boundary; planning and custody rechecks spawn no child."""
    parent = document["parent_qualification"]
    _, contract = _pin(parent["contract"], base_dir, captured)
    _pin(parent["receipt"], base_dir, captured)
    source = contract["boundary_source"]
    path = fm._regular(source["path"], base_dir)
    raw = _read(path)
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise ValueError("historical boundary source changed")
    captured[str(path)] = raw
    spec = importlib.util.spec_from_file_location("private_source_bound_historical_qualification", path)
    boundary = importlib.util.module_from_spec(spec); spec.loader.exec_module(boundary)
    prerequisite = document["law_prerequisite"]
    required = contract["required_admission"]
    if (contract["run_directory"] != prerequisite["run_directory"]
            or any(required[key] != prerequisite[key] for key in
                ("run_id", "cycle_id", "claim_scope", "review_snapshot_sha256", "review_event_sha256"))
            or required["checks"] != {"custody": "integrity", "numerical": "scientific"}
            or contract["artifacts"] != prerequisite["artifacts"]
            or contract["qualified_numerical_modules"] != prerequisite["runtime_sources"]):
        raise ValueError("historical contract does not bind the exact score law prerequisite")
    limits = contract["budget"]
    required(limits, ("worker_inner_seconds", "solver_work_cutoff_seconds", "initial_capture_compile_gate_seconds",
                      "final_gate_reservation_seconds", "complete_worker_seconds"))
    if (any(_number(v, "positive qualification budget") <= 0 for v in limits.values())
            or not limits["initial_capture_compile_gate_seconds"] < limits["solver_work_cutoff_seconds"] < limits["worker_inner_seconds"] <= limits["complete_worker_seconds"]
            or limits["worker_inner_seconds"]-limits["solver_work_cutoff_seconds"] < limits["final_gate_reservation_seconds"]):
        raise ValueError("encompassing supplied campaign deadlines required")
    proof = boundary.verify_receipt(contract, parent["receipt"])
    return {"module": boundary, "contract": contract, "receipt": parent["receipt"], "proof": proof}


def _review_admission(prerequisite, captured, qualification):
    """Live workflow gate plus detached replay; never accept only passed JSON.

    Snapshot construction revalidates the actual live approvals and evidence.
    The detached validator checks role/cycle/action semantics. Neither proves
    authenticated actors or scientific truth; those are workflow limitations.
    """
    if prerequisite["claim_scope"] != LAW_SCOPE:
        raise ValueError("scientific full-law-gradient acceptance is required, not custody-only reuse")
    root = Path(prerequisite["run_directory"])
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError("canonical existing prerequisite run directory required")
    root = root.resolve()
    snapshot = qualification["module"].verify_receipt(qualification["contract"], qualification["receipt"])["snapshot"]
    if len(compact(snapshot)) > MAX_CAPTURE_BYTES or _digest(snapshot) != prerequisite["review_snapshot_sha256"]:
        raise ValueError("upstream review snapshot changed")
    registration = snapshot["registration"]
    if registration["run_id"] != prerequisite["run_id"]:
        raise ValueError("cross-run prerequisite registration")
    cycles = [e for e in snapshot["events"] if e["event"] == "cycle"]
    cycle = cycles[-1]
    if cycle["cycle_id"] != prerequisite["cycle_id"]:
        raise ValueError("prerequisite cycle changed")
    policy = registration["policy"]
    scope = policy["claim_scopes"].get(LAW_SCOPE, {})
    kinds = {r["id"]: r["kind"] for r in policy["required_checks"]}
    if (not {"custody", "numerical"}.issubset(scope.get("checks", []))
            or kinds.get("custody") != "integrity" or kinds.get("numerical") != "scientific"):
        raise ValueError("upstream scope does not require the full scientific law check")
    scientific = next((r for r in cycle["checks"] if r["id"] == "numerical"), None)
    if scientific is None or scientific["status"] != "pass":
        raise ValueError("upstream numerical law check did not pass")
    reviews = [e for e in snapshot["events"] if e["event"] == "review" and e["cycle_id"] == cycle["cycle_id"]]
    actual = {e["role"]: e["sha256"] for e in reviews}
    if actual != prerequisite["review_event_sha256"] or any(e["claim_scope"] != prerequisite["claim_scope"] or e["verdict"] != "accept" for e in reviews):
        raise ValueError("actual accepted reviewer identities/scope changed")
    bound = {(_resolve_review_pin(root, pin), pin["sha256"]) for pin in cycle["snapshots"]}
    registered = {(_resolve_review_pin(root, pin), pin["sha256"]) for pin in registration["bindings"]}
    documents, paths = {}, {}
    for key, pin in prerequisite["artifacts"].items():
        path, documents[key] = _pin(pin, root, captured)
        paths[key] = path
        # The operative input may be external but must be actual cycle evidence.
        if key != "input" and not path.is_relative_to(root):
            raise ValueError("cross-run upstream " + key)
        if (str(path), pin["sha256"]) not in bound:
            raise ValueError("upstream artifact absent from exact accepted cycle: " + key)
    spec, receipt = documents["spec"], documents["receipt"]
    task = spec.get("task")
    if (spec.get("mode") != "joint-qualification" or not isinstance(task, dict) or set(task) != {"input"}
            or fm._regular(task["input"], root) != paths["input"]):
        raise ValueError("upstream operation lineage is not the exact law input")
    if receipt.get("stage") != "science" or receipt.get("status") != "succeeded":
        raise ValueError("upstream law has no successful science receipt")
    lineage = [r for r in cycle["receipts"] if r["stage"] == "science"]
    if len(lineage) != 1 or any(lineage[0].get(k) != receipt.get(k) for k in ("attempt_id", "receipt_sha256")):
        raise ValueError("upstream law receipt differs from accepted attempt")
    if receipt["attempt_id"] not in scientific["attempt_ids"]:
        raise ValueError("accepted scientific law check is not bound to the current attempt")
    if _resolve_review_pin(root, {"path": lineage[0]["path"]}) != str(paths["receipt"]):
        raise ValueError("upstream accepted receipt path changed")
    proof = qualification["proof"]
    if proof["old_attempt_id"] != receipt["attempt_id"] or proof["old_receipt_sha256"] != receipt["receipt_sha256"]:
        raise ValueError("upstream law receipt is not the historical qualified attempt")
    if str(paths["input"]) not in [str(execution.resolve_path(root, p)) for p in receipt["inputs"]]:
        raise ValueError("law input absent from actual receipt inputs")
    output_roots = [execution.resolve_path(root, p) for p in receipt["outputs"]]
    for key in ("result", "compiled"):
        if not any(paths[key] == p or paths[key].is_relative_to(p) for p in output_roots):
            raise ValueError("law result is not an output of the accepted attempt")
    for module_name, pin in prerequisite["runtime_sources"].items():
        qualified_path, _ = _pin_text(pin, root, captured)
        if (str(qualified_path), pin["sha256"]) not in bound | registered:
            raise ValueError("qualified runtime source absent from review custody: " + module_name)
        module = importlib.import_module(module_name)
        current = fm._regular(module.__file__, Path.cwd())
        raw = _read(current)
        if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise ValueError("current numerical source differs from qualified law: " + module_name)
        captured[str(current)] = raw
    if sum(map(len, captured.values())) > MAX_CAPTURE_BYTES:
        raise ValueError("64 MiB captured input ceiling")
    return snapshot, documents, paths


def _pin_text(pin, base, captured):
    # Source modules can be empty __init__ files; these admitted modules are not.
    _keys(pin, ("path", "sha256"), label="qualified source pin")
    path = fm._regular(pin["path"], base)
    raw = _read(path)
    if hashlib.sha256(raw).hexdigest() != _sha(pin["sha256"]):
        raise ValueError("qualified runtime source changed")
    captured[str(path)] = raw
    return path, raw


def _source_compatibility(design, law, snapshot, upstream_root, captured):
    """Validate explicit byte-preserving relocation and enumerated metadata.

    The live accepted review is checked by the caller before this pure custody
    helper. A helper proof conveys no review authority and is tied to all exact
    design/law/captured bytes. There is no compiler or density call here.
    """
    root = Path(upstream_root)
    cycles = [e for e in snapshot["events"] if e["event"] == "cycle"]
    pins = snapshot["registration"]["bindings"]+cycles[-1]["snapshots"]
    bound = {(_resolve_review_pin(root, p), p["sha256"]) for p in pins}
    proof = {"background": None, "cases": [], "accepted_custody_snapshot_sha256": _digest(snapshot),
             "scope": "source byte compatibility only; no scientific authority"}
    def identical(oldpin, newpin, label, *, old_base=Path.cwd(), new_base=None):
        oldpath, _ = _pin(oldpin, old_base, captured)
        newpath, _ = _pin(newpin, root if new_base is None else new_base, captured)
        if captured[str(oldpath)] != captured[str(newpath)]:
            raise ValueError("relocated source content differs: "+label)
        return {"design": deepcopy(oldpin), "accepted": deepcopy(newpin), "byte_identical": True}
    proof["background"] = identical(design["background_source"], law["background_source"], "background")
    if [r["id"] for r in design["cases"]] != [r["id"] for r in law["cases"]]:
        raise ValueError("source compatibility case identities differ")
    for expected, row in zip(design["cases"], law["cases"]):
        wspair = identical(expected["workspace"], row["workspace"], row["id"]+"/workspace")
        oldpath, original = _pin(expected["mc_model"], Path.cwd(), captured)
        newpath, accepted = _pin(row["mc_model"], root, captured)
        prepare_mc(original); prepare_mc(accepted)
        if compact({k: v for k, v in original.items() if k != "sources"}) != compact({k: v for k, v in accepted.items() if k != "sources"}):
            raise ValueError("relocated MC operative fields/assumptions differ")
        old_sources = {r["id"]: r for r in original["sources"]}
        new_sources = {r["id"]: r for r in accepted["sources"]}
        # prepare_mc rejects duplicate IDs and source/schema omissions.
        if not set(old_sources).issubset(new_sources):
            raise ValueError("relocated MC deleted an original source")
        extras = set(new_sources)-set(old_sources)
        identical_envelope = captured[str(oldpath)] == captured[str(newpath)]
        if identical_envelope:
            if extras:
                raise ValueError("identical envelope cannot contain source additions")
        declared = design['source_relocations'].get(row['id'], [])
        if type(declared) is not list or any(type(r) is not dict or set(r) != {'id','reference'} for r in declared):
            raise ValueError('explicit metadata-only source relocation required')
        references = {r['id']: r['reference'] for r in declared}
        if len(references) != len(declared) or extras != set(references):
            raise ValueError('source additions differ from supplied relocation specification')
        source_pairs, old_content, new_content = [], {}, {}
        for identity, old in old_sources.items():
            new = new_sources[identity]
            if {k: v for k, v in old.items() if k != "path"} != {k: v for k, v in new.items() if k != "path"}:
                raise ValueError("original source id/reference/hash changed: "+identity)
            pair = identical({k: old[k] for k in ("path", "sha256")}, {k: new[k] for k in ("path", "sha256")}, identity,
                             old_base=oldpath.parent, new_base=newpath.parent)
            pair["id"] = identity; pair["reference"] = old["reference"]; source_pairs.append(pair)
            oldfile = fm._regular(old["path"], oldpath.parent); newfile = fm._regular(new["path"], newpath.parent)
            old_content[identity] = json.loads(captured[str(oldfile)]); new_content[identity] = json.loads(captured[str(newfile)])
        additions = []
        operative_ids = {accepted["mc_design"]["ledger_source"], accepted["mc_design"]["normalization_source"]}
        operative_ids.update(r["source"] for r in accepted["bins"]+accepted["classes"])
        if extras.intersection(operative_ids):
            raise ValueError("review metadata cannot become an operative MC source")
        for identity in sorted(extras):
            new = new_sources[identity]
            if new["reference"] != references[identity]:
                raise ValueError("additive review source reference differs: "+identity)
            path, _ = _pin({k: new[k] for k in ("path", "sha256")}, newpath.parent, captured)
            if (str(path), new["sha256"]) not in bound:
                raise ValueError("additive review source not in actual accepted custody: "+identity)
            additions.append(deepcopy(new))
        _ledger(original, old_content[original["mc_design"]["ledger_source"]])
        _ledger(accepted, new_content[accepted["mc_design"]["ledger_source"]])
        proof["cases"].append({"case": row["id"], "workspace": wspair,
                               "design_MC": deepcopy(expected["mc_model"]), "accepted_MC": deepcopy(row["mc_model"]),
                               "mode": "identical_pinned_envelope" if identical_envelope else "supplied_metadata_source_relocation",
                               "all_operative_fields_identical": True, "source_pairs": source_pairs, "additions": additions})
    return _SourceCompatibility(_COMPATIBILITY_SEAL, design, law, proof, captured)


def _design(design):
    required(design, ('schema_version','study_id','cases','parameter_grid','dataset_population','objectives',
                     'comparisons','solver','fit_protocol','resource_bounds','measurement',
                     'background_source','qualification_scope','source_relocations','delivery'))
    identifier(design['study_id']); delivery(design['delivery'])
    if type(design['schema_version']) is not int or design['schema_version'] != 1:
        raise ValueError('fit campaign design schema1 required')
    grid = coordinates(design['parameter_grid'])
    if type(design['dataset_population']) is not list or not design['dataset_population']:
        raise SpecificationError('missing_input','dataset_population')
    datasets = [identifier(x) for x in design['dataset_population']]
    if len(set(datasets)) != len(datasets): raise ValueError('unique dataset population required')
    cases = design['cases']; objectives = design['objectives']
    if type(cases) is not list or not cases or type(objectives) is not list or not objectives:
        raise SpecificationError('missing_input','cases and objectives')
    case_ids = [identifier(c['id']) for c in cases]; ids = [identifier(o['id']) for o in objectives]
    if len(set(case_ids)) != len(case_ids) or len(set(ids)) != len(ids): raise ValueError('unique campaign identities required')
    for objective in objectives:
        _keys(objective, ('id','fixed_mu'), label='objective')
        if objective['fixed_mu'] is not None: _number(objective['fixed_mu'],'fixed objective strength')
    for case in cases:
        required(case, ('parameter_point','dataset_id','expected_free_coordinates','original_named_seeds'))
        if case['parameter_point'] not in grid or case['dataset_id'] not in datasets:
            raise ValueError('case outside supplied parameter/dataset population')
        _keys(case['expected_free_coordinates'], ids, label='objective dimensions')
        if any(type(v) is not int or v < 1 for v in case['expected_free_coordinates'].values()):
            raise ValueError('positive explicit objective dimensions required')
        seeds = case['original_named_seeds']
        if type(seeds) is not list or not seeds: raise SpecificationError('missing_input','original_named_seeds')
        if len({identifier(s['id']) for s in seeds}) != len(seeds): raise ValueError('unique seed identities required')
        for seed in seeds: _keys(seed['points'], ids, label='complete objective seed points')
    if {compact(c['parameter_point']) for c in cases} != {compact(p) for p in grid} or {c['dataset_id'] for c in cases} != set(datasets):
        raise ValueError('complete supplied grid and dataset population required')
    if type(design['comparisons']) is not list: raise ValueError('explicit comparison census required')
    compare_ids = []
    for comparison in design['comparisons']:
        _keys(comparison, ('id','left','right','scale','minimum','atol'), label='comparison criterion')
        compare_ids.append(identifier(comparison['id']))
        if comparison['left'] not in ids or comparison['right'] not in ids: raise ValueError('comparison objective absent')
        for key in ('scale','minimum','atol'): _number(comparison[key], 'comparison '+key)
        if comparison['atol'] < 0: raise ValueError('nonnegative comparison tolerance required')
    if len(set(compare_ids)) != len(compare_ids): raise ValueError('unique comparison identities required')
    _keys(design['solver'], ('path','sha256'), label='supplied solver pin'); _sha(design['solver']['sha256'])
    required(design['fit_protocol'], ('mu_domain','budget_per_fit','solver_options','endpoint_budget','rate_caps'))
    return deepcopy(design)


def _law_identity(design, prerequisite, documents, compatibility, captured):
    law, result, compiled = documents['input'], documents['result'], documents['compiled']
    if type(compatibility) is not _SourceCompatibility:
        raise ValueError('computed byte-custody compatibility proof required')
    compatibility.check(design, law, captured)
    if (law.get('schema_version') != 2 or law.get('execution_scope') != 'law_only'
            or result.get('schema_version') != 2 or result.get('execution_scope') != 'law_only'
            or result.get('status') != 'passed' or result.get('law_qualification_passed') is not True
            or result.get('profile_qualification_performed') is not False
            or result.get('planned_fit_denominator') != 0 or result.get('fits') != []
            or result.get('model_id') != law.get('model_id')):
        raise ValueError('accepted result must establish an actual no-fit law prerequisite')
    if law['measurement'] != design['measurement']: raise ValueError('qualified source measurement differs')
    ids = [r['id'] for r in design['cases']]
    if ([r['id'] for r in law['cases']] != ids or [r['case'] for r in compiled] != ids
            or set(prerequisite['joint_contract_sha256_per_case']) != set(ids)):
        raise ValueError('complete ordered supplied case law required')
    qualified = result.get('qualification', [])
    if [r.get('case') for r in qualified] != ids or not all(r.get('passed') is True for r in qualified):
        raise ValueError('every actual law qualification must pass')
    scope = design['qualification_scope']
    _keys(scope, ('fixed_vector_count','central_steps','budget_used'), label='supplied law qualification scope')
    if type(scope['fixed_vector_count']) is not int or scope['fixed_vector_count'] < 1:
        raise ValueError('positive qualification vector census required')
    for expected, row, contract, checks in zip(design['cases'], law['cases'], compiled, qualified):
        for key in ('id','signal_samples','source_bin_map','source_bound_semantics','expected_source_coordinates'):
            if compact(row[key]) != compact(expected[key]): raise ValueError('qualified source/law design differs: '+key)
        free = row['expected_free_coordinates']
        for objective in design['objectives']:
            if expected['expected_free_coordinates'][objective['id']] != free-(objective['fixed_mu'] is not None):
                raise ValueError('qualified objective dimensions differ')
        if (len(checks.get('fixed_vectors', [])) != scope['fixed_vector_count']
                or not all(p.get('passed') is True for p in checks['fixed_vectors'])
                or len(checks.get('gradient_columns', [])) != free
                or not all(p.get('passed') is True and [h.get('h') for h in p.get('steps', [])] == scope['central_steps'] for p in checks['gradient_columns'])):
            raise ValueError('actual full law qualification scope differs from supplied specification')
        if _digest(contract['joint']) != prerequisite['joint_contract_sha256_per_case'][row['id']]:
            raise ValueError('qualified complete joint contract differs')
    if law['qualification']['steps'] != scope['central_steps'] or result.get('qualification_budget_used') != scope['budget_used']:
        raise ValueError('actual qualification steps or call census differs from supplied scope')
    return law


def _capture(task, base_dir):
    validate(task)
    path = fm._regular(task["input"], base_dir)
    raw = _read(path)
    document = _prepare(json.loads(raw))
    captured = {str(path): raw}
    _, design = _pin(document["design"], base_dir, captured)
    design = _design(design)
    qualification = _qualification(document, base_dir, captured)
    snapshot, documents, paths = _review_admission(document["law_prerequisite"], captured, qualification)
    law = documents["input"]
    compatibility = _source_compatibility(design, law, snapshot, document["law_prerequisite"]["run_directory"], captured)
    law = _law_identity(design, document["law_prerequisite"], documents, compatibility, captured)
    upstream_root = Path(document["law_prerequisite"]["run_directory"])
    _, background = _pin(law["background_source"], upstream_root, captured)
    _pin_text({k: design["solver"][k] for k in ("path", "sha256")}, base_dir, captured)
    cases = []
    for expected, row in zip(design["cases"], law["cases"]):
        _, workspace = _pin(row["workspace"], upstream_root, captured)
        model_path, _ = _pin(row["mc_model"], upstream_root, captured)
        mc = MCAuxiliaryBlock({"input": str(model_path)}, base=Path(base_dir))
        for p, data in mc._captured.items():
            if p in captured and captured[p] != data:
                raise ValueError("MC source changed during capture")
            captured[p] = data
        if compact(inspect_workspace(workspace, row["signal_samples"])["background_projection"]) != compact(background):
            raise ValueError("exact background projection differs")
        md = mc.document()
        cases.append((expected, row, workspace, mc))
    if sum(map(len, captured.values())) > MAX_CAPTURE_BYTES:
        raise ValueError("64 MiB captured input ceiling")
    _unchanged(captured)
    return {"input": document, "design": design, "snapshot": snapshot, "law": law,
            "compiled_law": documents["compiled"], "background": background, "cases": cases,
            "captured": captured, "source_compatibility": compatibility.check(design, law, captured),
            "upstream_paths": {k: str(v) for k, v in paths.items()}, "qualification": qualification}


def _unchanged(captured):
    for p, raw in captured.items():
        if _read(fm._regular(p, Path.cwd())) != raw:
            raise ValueError("captured bytes changed: " + p)


def inputs(task, base_dir):
    captured = _capture(task, base_dir)
    qualified = captured["qualification"]
    return sorted(set([Path(p) for p in captured["captured"]] + qualified["module"].inputs(qualified["contract"], qualified["receipt"])))


def helper_declaration(task, base_dir, output_dir, *, _session=None):
    """Declare exact attempt routes without reserving files or launching helpers.

    This public hook performs fresh admission. A supplied validation session does
    not bypass current capture; future shared-read optimization is separate work.
    """
    from ravel.workflow import helper_registration
    captured = _capture(task, base_dir)
    contract = captured["qualification"]["contract"]
    route = Path(output_dir).absolute() / "historical-qualification"
    return helper_registration.declaration(contract, {
        "initial": route / "initial", "final": route / "final"})


def _bounds(design):
    planned = _plan(design)
    seeds = sum(len(c['original_named_seeds'])*len(design['objectives']) for c in design['cases'])
    return {**deepcopy(design["resource_bounds"]), "processes": 5,
            "maximum_mathematical_workers": 1,
            "peak_processes_including_supervisor": 5,
            "peak_processes_during_math_including_supervisor": 2,
            "registered_metadata_helpers_per_worker": 2,
            "registered_metadata_anchors_per_worker": 2,
            "registered_metadata_groups_overlap": False,
            "owner_registry_output_bytes": 1024**2,
            "owner_registry_counts_against_worker_144MiB": False,
            "helper_owner_cleanup_reserve_seconds": 3.,
            "helper_owner_cleanup_is_outside_active_supervisor_clock": True,
            "original_design_processes_scope": "One mathematical worker; this composite runtime explicitly admits five processes",
            "maximum_fit_calls": len(planned),
            "original_seed_denominator": seeds, "maximum_file_input_bytes": 8*1024**2,
            "maximum_captured_input_bytes": MAX_CAPTURE_BYTES,
            "maximum_journal_bytes": MAX_JOURNAL_BYTES,
            "maximum_oracle_return_snapshot_files": seeds,
            "maximum_oracle_return_snapshot_bytes_each": MAX_ORACLE_RETURN_BYTES,
            "oracle_return_snapshots_count_against_existing_aggregate_output_limit": True,
            "mathematical_allocation_is_completion_guarantee": False,
            "supervisor_scope": "Supplied supervisor ceiling includes worker startup, custody and serialization; inner allocation is not guaranteed",
            "scientific_mode_dispatch_added": False}


def resource_bounds(task, base_dir):
    captured = _capture(task, base_dir)
    qualified = captured["qualification"]
    return {**_bounds(captured["design"]), "historical_qualification": qualified["module"].hook_resource_bounds(qualified["contract"], qualified["receipt"]),
            "historical_outputs_count_against_existing_144MiB_limit": True}


def execution_seconds(task, base_dir):
    return resource_bounds(task, base_dir)["execution_seconds"]


class Retention:
    """Hash-linked small journal and atomic, individually bounded full returns."""
    def __init__(self, directory):
        self.out = directory
        self.sequence, self.prior, self.bytes, self.journal_bytes = 0, None, 0, 0

    def actual_bytes(self):
        total, count = 0, 0
        for path in self.out.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink in retained output")
            if path.is_file():
                count += 1; total += path.stat().st_size
                if count > 4096 or total > MAX_OUTPUT_BYTES:
                    raise ValueError("aggregate retained output byte/file ceiling")
        return total

    def reserve_boundary(self):
        # Gate output16MiB plus phase/session metadata1MiB remains inside144MiB.
        if self.actual_bytes()+17*1024**2 > MAX_OUTPUT_BYTES:
            raise ValueError("insufficient aggregate output reservation for historical boundary")

    def write(self, kind, identity, state, **fields):
        self.bytes = self.actual_bytes()
        row = {"sequence": self.sequence, "previous_sha256": self.prior,
               "kind": kind, "id": identity, "state": state, **fields}
        raw = compact(row)+b"\n"
        if self.journal_bytes+len(raw) > MAX_JOURNAL_BYTES:
            raise ValueError("journal byte ceiling")
        if self.bytes+len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("aggregate retained output byte ceiling")
        with (self.out/"score-progress.jsonl").open("ab") as stream:
            stream.write(raw); stream.flush()
            import os
            os.fsync(stream.fileno())
        self.bytes += len(raw); self.journal_bytes += len(raw)
        self.sequence += 1; self.prior = hashlib.sha256(raw).hexdigest()

    def snapshot(self, filename, value, *, limit=MAX_SNAPSHOT_BYTES):
        self.bytes = self.actual_bytes()
        if Path(filename).name != filename:
            raise ValueError("flat output filename required")
        raw = compact(value)
        if len(raw) > limit or self.bytes+len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("returned snapshot/output byte ceiling")
        destination = self.out/filename
        if destination.exists():
            raise FileExistsError("returned snapshot already exists")
        temporary = self.out/(filename+".partial")
        with temporary.open("xb") as stream:
            stream.write(raw); stream.flush()
            import os
            os.fsync(stream.fileno())
        temporary.rename(destination)
        self.bytes += len(raw)
        return {"path": filename, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _solver_module(design):
    path = fm._regular(design["solver"]["path"], Path.cwd())
    if hashlib.sha256(_read(path)).hexdigest() != design["solver"]["sha256"]:
        raise ValueError("supplied score solver changed")
    spec = importlib.util.spec_from_file_location("supplied_score_solver", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _starts(problem, case, mode):
    points = [deepcopy(row["points"][mode]) for row in case["original_named_seeds"]]
    vectors, mapping = [], []
    for index, (seed, point) in enumerate(zip(case["original_named_seeds"], points)):
        _keys(point, ("mu", "source", "latent"), label="literal seed")
        _keys(point["source"], problem.source["active_parameter_names"], label="complete original source seed")
        _keys(point["latent"], [c["id"] for c in problem.document["classes"]], label="complete original MC seed")
        vector = []
        for name in problem.axes:
            value = point["mu"] if name == "mu" else point["source"][name[7:]] if name.startswith("source:") else point["latent"][name[3:]]
            vector.append(_number(value, "literal original seed"))
        actual = problem.parameters(np.array(vector))
        last = problem.document["classes"][-1]["id"]
        # The sole admitted arithmetic change is eliminated-last subtraction.
        if actual["mu"] != point["mu"] or actual["source"] != point["source"] or any(actual["latent"][k] != point["latent"][k] for k in point["latent"] if k != last):
            raise ValueError("literal seed mapping changed")
        delta = actual["latent"][last]-point["latent"][last]
        if abs(delta) > 1e-12:
            raise ValueError("complete original seed is not the declared simplex")
        vectors.append(vector)
        mapping.append({"original_seed_id": index, "declared_seed_id": seed["id"], "declared_point": point,
                        "mapped_point": actual, "eliminated_last_class": last, "last_probability_roundoff": delta})
    if not vectors:
        raise SpecificationError("missing_input", "literal seed population")
    return vectors, mapping


def _endpoint_checks(fit, oracle, retention, identity, limits):
    """Check all available raw endpoints; selected result must be one of them."""
    records = []
    for attempt in fit["attempts"]:
        index = attempt["original_seed_id"]
        if "parameters" not in attempt or "nll" not in attempt:
            records.append({"original_seed_id": index, "checked": False, "passed": None,
                            "reason": "No returned endpoint; intermediate solver memory unavailable"})
            continue
        retention.write("endpoint", identity+"/"+str(index), "running")
        independent_return = None
        try:
            independent = oracle.evaluate(attempt["parameters"])
            independent_return = retention.snapshot(
                identity.replace("/", "--")+"--oracle-return-"+str(index)+".json",
                {"fit_identity": identity, "original_seed_id": index,
                 "parameters": deepcopy(attempt["parameters"]), "independent": independent},
                limit=MAX_ORACLE_RETURN_BYTES)
            nll_error = abs(attempt["nll"]-independent["nll"])
            passed = nll_error <= limits["nll_atol"] and q._close(attempt["main_means"], independent["main_means"], limits["mean_atol"], limits["mean_rtol"])
            records.append({"original_seed_id": index, "checked": True, "passed": bool(passed),
                            "independent": independent, "nll_absolute_error": nll_error,
                            "independent_return_snapshot": independent_return})
        except Exception as error:
            records.append({"original_seed_id": index, "checked": True, "passed": False,
                            "error": str(error), "exception_type": type(error).__name__,
                            "independent_return_snapshot": independent_return})
        retention.write("endpoint", identity+"/"+str(index), "completed", passed=records[-1]["passed"],
                        independent_return_snapshot=records[-1].get("independent_return_snapshot"))
    checked = [r for r in records if r["checked"]]
    matches = []
    if "parameters" in fit and "nll" in fit:
        for attempt in fit["attempts"]:
            ok = next((r for r in checked if r["original_seed_id"] == attempt["original_seed_id"] and r["passed"]), None)
            if ok and compact(attempt["parameters"]) == compact(fit["parameters"]) and attempt["nll"] == fit["nll"]:
                matches.append(attempt["original_seed_id"])
    fit["selected_endpoint_binding"] = {"matching_independently_checked_original_seed_ids": matches,
                                         "passed": bool(matches), "exact_parameters_and_nll": True}
    fit["independent_endpoint_checks"] = records
    fit["independent_endpoint_parity"] = bool(checked and all(r["passed"] for r in checked) and (not fit["verified"] or matches))
    fit["independent_endpoint_scope"] = "All available returned endpoints: main means and complete NLL; original source aux/MC means also retained. No additional derivative or unavailable intermediate-state check."
    if not fit["independent_endpoint_parity"]:
        fit["verified"] = False; fit["endpoint_refusal"] = "available endpoint parity or exact selected binding failed"
    return fit


def _support_diagnostics(fit, case, mc, workspace):
    """Arithmetic on existing returns only: no graph/density/probe calls."""
    md = mc.document(); classes = md["classes"]; rows = []
    by_channel = {r["name"]: r for r in workspace["channels"]}
    nominal = [math.fsum(s["data"][r["bin"]] for s in by_channel[r["channel"]]["samples"]
                         if s["name"] in case["signal_samples"][r["channel"]]) for r in case["source_bin_map"]]
    branches = {m["name"] for c in workspace["channels"] for s in c["samples"] for m in s["modifiers"]
                if m["type"] in ("histosys", "normsys")}
    axes = fit["recipe"]["coordinate_order"]
    def state_diagnostics(entry):
        slacks = entry.get("stationarity", {}).get("source_slacks")
        if slacks is None:
            return {"per_bin_source_support_available": False}
        n = len(slacks)//2
        ratios = [value/reference for value, reference in zip(slacks[n:], nominal)]
        vector = entry.get("coordinates", [])
        source = {name[7:]: vector[i] for i, name in enumerate(axes) if name.startswith("source:")}
        return {"per_bin_source_support_available": True, "source_background_means": slacks[:n],
                "published_nonMC_signal_means": slacks[n:], "source_response_ratios": ratios,
                "minimum_source_response_ratio": min(ratios), "response_below_0_05_review_flag": min(ratios) < .05,
                "source_interpolation_branches": {name: "low_exterior" if source[name] <= -1 else "high_exterior" if source[name] >= 1 else "interior" for name in branches}}
    for attempt in fit["attempts"]:
        row = {"original_seed_id": attempt["original_seed_id"], "status": attempt["status"],
               "returned_endpoint_available": "parameters" in attempt,
               "stationarity": deepcopy(attempt.get("stationarity")),
               "local_identifiability": deepcopy(attempt.get("local_identifiability")),
               "metric_and_proposal_history": deepcopy(attempt.get("history", [])),
               "proposals": deepcopy(attempt.get("proposals", []))}
        if "parameters" in attempt:
            point = attempt["parameters"]; p = [point["latent"][c["id"]] for c in classes]
            denom = math.fsum(c["denominator_mark"]*v for c, v in zip(classes, p))
            net = [math.fsum(c["contribution"][i]*v for c, v in zip(classes, p)) for i in range(len(md["bins"]))]
            row.update(mu=point["mu"], complete_probabilities=p, expected_denominator=denom, raw_expected_net=net)
        row.update(state_diagnostics(attempt))
        row["accepted_history_support"] = [state_diagnostics(entry) for entry in attempt.get("history", [])]
        row["nonlinear_negative_trial_count"] = sum(p.get("status") == "nonlinear_source_infeasible" for p in attempt.get("proposals", []))
        row["rejected_trial_per_bin_support"] = "Unavailable in supplied solver returns; only recorded minimum slack/coordinates/refusal are retained, with no new source passes"
        rows.append(row)
    return {"attempts": rows, "extra_model_calls": 0,
            "scope": "Descriptive support/stall risks from returned points, not a finite-endpoint or recession proof"}


def _compile(case, row, workspace, mc, capture):
    bg, joint = q._compile(row, workspace, capture["background"], mc,
                           capture["law"]["measurement"], capture["law"]["model_id"])
    expected = next(r for r in capture["compiled_law"] if r["case"] == row["id"])
    if compact(joint.contract()) != compact(expected["joint"]) or compact(bg.contract()) != compact(expected["background"]):
        raise ValueError("recompiled law differs from accepted exact graph identity")
    source = bg.contract()
    return bg, joint


def _plan(design):
    return [{'case': case['id'], 'mode': objective['id'], 'id': case['id']+'/'+objective['id'],
             'free_dimension': case['expected_free_coordinates'][objective['id']],
             'fixed_mu': objective['fixed_mu'], 'seed_count': len(case['original_named_seeds'])}
            for case in design['cases'] for objective in design['objectives']]


def run(task, base_dir, output_dir):
    out = fm._admit_output(output_dir)  # before custody, compilation, solver work
    started = time.monotonic()
    capture = _capture(task, base_dir)
    design = capture['design']; limits = capture['qualification']['contract']['budget']
    deadline = started+limits['solver_work_cutoff_seconds']
    retention = Retention(out); planned = _plan(design)
    for row in planned:
        retention.write("fit", row["id"], "planned", recipe=row, original_seed_denominator=row["seed_count"])
    records = [{**r, "status": "not_started", "verified": False} for r in planned]
    fatal = None; source_timing = None
    session = None; initial_qualified = False; boundary_receipts = {}
    try:
        qualified = capture["qualification"]
        retention.reserve_boundary()
        session = qualified["module"].WorkerSession(qualified["contract"], qualified["receipt"],
                                                     out/"historical-qualification", worker_started=started)
        retention.write("admission", "initial", "running")
        boundary_receipts["initial"] = session.boundary("initial")
        current = qualified["module"].verify_receipt(qualified["contract"], boundary_receipts["initial"])["snapshot"]
        if current != capture["snapshot"] or time.monotonic()-started >= limits["initial_capture_compile_gate_seconds"]:
            raise ValueError("historical initial law identity/deadline differs")
        retention.write("admission", "initial", "completed", receipt=boundary_receipts["initial"])
        initial_qualified = True
        solver = _solver_module(capture["design"])
        retention.snapshot("score-input-custody.json", {"input": capture["input"], "review_snapshot": capture["snapshot"],
                           "source_compatibility": capture["source_compatibility"],
                           "source_inputs": [{"path": p, "sha256": hashlib.sha256(raw).hexdigest()} for p, raw in capture["captured"].items()]})
        compiled = []
        for case, row, workspace, mc in capture["cases"]:
            if time.monotonic()-started >= limits["initial_capture_compile_gate_seconds"]:
                raise TimeoutError("supplied source capture/compilation allocation exhausted")
            bg, joint = _compile(case, row, workspace, mc, capture)
            compiled.append((case, row, workspace, mc, bg, joint))
        source_timing = time.monotonic()-started
        if source_timing >= limits["initial_capture_compile_gate_seconds"]:
            raise TimeoutError("supplied source capture/compilation allocation exhausted")
        # Recheck actual accepted live history immediately before numerical work.
        current = qualified["module"].verify_receipt(qualified["contract"], boundary_receipts["initial"])["snapshot"]
        if current != capture["snapshot"]:
            raise ValueError("upstream admission changed before fit launch")
        _unchanged(capture["captured"])
        source_timing = time.monotonic()-started
        if source_timing >= limits["initial_capture_compile_gate_seconds"]:
            raise TimeoutError("supplied custody/capture/compilation allocation exhausted")
        for case, row, workspace, mc, bg, joint in compiled:
            for objective in design["objectives"]:
                mode = objective["id"]
                identity = case["id"]+"/"+mode
                record = next(r for r in records if r["id"] == identity)
                if time.monotonic() >= deadline:
                    raise TimeoutError("supplied common solver/endpoint cutoff exhausted before next fit")
                problem = solver.JointScoreProblem(joint, bg, mc,
                    mu_domain=capture["design"]["fit_protocol"]["mu_domain"],
                    source_bound_semantics=case["source_bound_semantics"], rate_caps=design["fit_protocol"]["rate_caps"],
                    fixed_mu=objective["fixed_mu"])
                if len(problem.axes) != record["free_dimension"]:
                    raise ValueError("full free-coordinate census changed")
                starts, mapping = _starts(problem, case, mode)
                retention.write("fit", identity, "running", original_seeds=mapping)
                record["status"] = "running"
                fitted = solver.ScoreContinuation(**design["fit_protocol"]["solver_options"]).fit(
                    problem, starts=starts, budget=capture["design"]["fit_protocol"]["budget_per_fit"],
                    wall_hook=lambda: time.monotonic() >= deadline)
                fitted["literal_original_seed_mapping"] = mapping
                raw = retention.snapshot(identity.replace("/", "--")+"--raw.json", fitted)
                record.update(status="returned", raw_snapshot=raw, fitted=fitted)
                retention.write("fit", identity, "returned", snapshot=raw,
                                scope="Complete returned solver state; future in-memory state is unavailable")
                if [attempt.get('original_seed_id') for attempt in fitted.get('attempts', [])] != list(range(len(starts))):
                    raise ValueError('complete ordered returned seed census differs from supplied starts')
                # Raw return survives an exception/timeout during the oracle.
                endpoint = deepcopy(design['fit_protocol']['endpoint_budget'])
                epbudget = q.QualificationBudget(endpoint, deadline)
                endpoint_started = time.monotonic()
                try:
                    oracle = q.IndependentSourceOracle(workspace, capture["background"], row, mc,
                                                       capture["law"]["measurement"], epbudget)
                    epbudget.check()
                    fitted = _endpoint_checks(deepcopy(fitted), oracle, retention, identity,
                                               capture["law"]["qualification"])
                except Exception as error:
                    fitted = deepcopy(fitted); fitted["verified"] = False
                    fitted["independent_endpoint_parity"] = False
                    fitted["endpoint_refusal"] = {"error": str(error), "exception_type": type(error).__name__}
                fitted["endpoint_budget"] = {"limits": endpoint, "used": dict(epbudget.used),
                                             "elapsed_seconds": time.monotonic()-endpoint_started}
                fitted["support_diagnostics"] = _support_diagnostics(fitted, case, mc, workspace)
                checked = retention.snapshot(identity.replace("/", "--")+"--checked.json", fitted)
                record.update(status="completed", verified=bool(fitted["verified"]), checked_snapshot=checked, fitted=fitted)
                retention.write("fit", identity, "completed", snapshot=checked, verified=record["verified"])
    except Exception as error:
        fatal = {"error": str(error), "exception_type": type(error).__name__}
        retention.write("stage", "supplied-fit-campaign", "failed", **fatal)
    contrasts = []
    for case in design['cases']:
        for criterion in design['comparisons']:
            left, right = [next(r for r in records if r['case'] == case['id'] and r['mode'] == mode)
                           for mode in (criterion['left'], criterion['right'])]
            delta = criterion['scale']*(right['fitted']['nll']-left['fitted']['nll']) if left['verified'] and right['verified'] else None
            contrasts.append({'case': case['id'], 'criterion': criterion['id'], 'value': delta,
                              'passed': delta is not None and delta >= criterion['minimum']-criterion['atol'],
                              'scope': 'Stationary endpoint comparison only; globality and physics remain unqualified'})
    changed = None
    if capture is not None:
        try:
            _unchanged(capture["captured"])
            if not initial_qualified:
                raise ValueError("initial historical phase did not qualify; no final helper launched")
            retention.reserve_boundary()
            retention.write("admission", "final", "running")
            boundary_receipts["final"] = session.boundary("final")
            final = qualified["module"].verify_receipt(qualified["contract"], boundary_receipts["final"])["snapshot"]
            if final != capture["snapshot"] or time.monotonic() >= started+limits["worker_inner_seconds"]:
                raise ValueError("final historical law identity/deadline differs")
            retention.write("admission", "final", "completed", receipt=boundary_receipts["final"])
            if time.monotonic() >= started+limits["worker_inner_seconds"]:
                raise TimeoutError("final qualification serialization exceeded supplied allocation")
        except Exception as error:
            changed = {"error": str(error), "exception_type": type(error).__name__}
    result = {"schema_version": 1, "operation": "supplied_fit_campaign", "study_id": design["study_id"],
              "parameter_grid": design["parameter_grid"], "dataset_population": design["dataset_population"], "delivery": design["delivery"],
              "status": "passed" if not fatal and not changed and all(r["verified"] for r in records) and all(r["passed"] for r in contrasts) else "unresolved",
              "planned_fit_denominator": len(planned), "original_seed_denominator": sum(r["seed_count"] for r in planned),
              "fits": [{k: v for k, v in r.items() if k != "fitted"} for r in records],
              "contrasts": contrasts, "fatal": fatal, "custody_refusal": changed,
              "source_capture_compile_seconds": source_timing,
              "historical_boundary_receipts": boundary_receipts,
              "common_solver_endpoint_cutoff_seconds": limits["solver_work_cutoff_seconds"],
              "common_final_gate_cutoff_seconds": limits["worker_inner_seconds"],
              "elapsed_seconds": time.monotonic()-started,
              "resource_bounds": _bounds(capture["design"]) if capture else None,
              "physics_validated": False, "global_optimum_certified": False, "coverage_qualified": False,
              "limits": ["Constructed independent marked/source response law; native generator and variation correlations are unproved.",
                         "Original derivative qualification applies at its declared vectors, not independent endpoint derivative proof.",
                         "Exact boundary/coupled support refusals and score/rank/spread gates unchanged; no retries or gate relaxation.",
                         "Supplied inner allocation and supervisor cap are bounds, not completion guarantees.",
                         "Hard kill preserves prior raw/checked returns and started identities; current unreturned solver memory is unavailable.",
                         "No old conditioned outcome repair, accepted finite-MC hold override, calibrated interval, CLs or exclusion."]}
    # Public delivery is chosen by the specification; raw/checked custody remains complete.
    if design['delivery']['filename'] == 'score-experiment-result.json':
        raise ValueError('delivery cannot replace internal custody result')
    write_delivery(out, design['delivery'], result, result['fits'])
    retention.actual_bytes()
    retention.snapshot("score-experiment-result.json", result)
    retention.write("stage", "supplied-fit-campaign", "completed", status=result["status"])
    return result
