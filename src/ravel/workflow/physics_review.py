"""Evidence-bound scientific reviews and bounded correction admission.

Actor IDs enforce declared role separation, not authenticated identity. Local hash
chains and checkpoints detect inconsistent/deleted records; they are not an
external trust service and cannot detect a coordinated rewrite of all local state.
A diagnostic rejection of a hypothesis can be accepted as a diagnostic result.
Nothing in this module decides physics or supplies an automatic reviewer verdict.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from . import execution, waypoint_evidence
from .state_io import atomic_json, file_lock, read_json

POLICY = "inputs/physics_review_policy.json"
DIRECTORY = "logs/physics_review"
REGISTRATION = DIRECTORY + "/registration.json"
HEAD = DIRECTORY + "/head.json"
ATTESTATION = "Declared actor separation only; actor identity and independence are not authenticated."
ROLES = ("physics_critic", "skeptical_verifier", "physics_decider")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} needs exactly {sorted(keys)}")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonblank string")
    return value


def _ids(value, label, *, empty=False):
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(v, str) or not ID.fullmatch(v) for v in value)
            or len(value) != len(set(value))):
        raise ValueError(f"{label} needs distinct identifiers")
    return value


def _relative(value):
    _text(value, "changed path")
    p = Path(value)
    if p.is_absolute() or p.as_posix() != value or any(v in (".", "..") for v in p.parts) or not p.parts:
        raise ValueError("changed paths must be canonical run-relative file paths")
    prepared_settings = {"output/native_effective_settings.json", "output/param_card.dat", "output/run_card.dat",
                         "output/run.mg5", "output/shower.cfg"}
    if (value in (POLICY, "inputs/checkin1_approval.json", "inputs/task_contract.json", "inputs/checkin1.json", "inputs/cost_preflight.json")
            or value.startswith(("logs/", "outputs/")) or (value.startswith("output/") and value not in prepared_settings)):
        raise ValueError("correction paths cannot replace approval, policy, execution or result evidence")
    return value


def validate_policy(policy):
    """Return strict schema errors. No defaults silently grant review authority."""
    try:
        _object(policy, {"schema_version", "actors", "max_redos", "allowed_changed_paths",
                         "allowed_stages", "required_checks", "claim_scopes"}, "review policy")
        if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
            raise ValueError("review policy schema_version must be integer 1")
        actors = policy["actors"]
        _object(actors, {"proposer", "executor", *ROLES}, "actors")
        for role, actor in actors.items():
            _text(actor, role)
        if (len({actors[r] for r in ROLES}) != len(ROLES) or any(
                actors[r] in (actors["proposer"], actors["executor"]) for r in ROLES)):
            raise ValueError("review actors must differ from each other, proposer and executor")
        if type(policy["max_redos"]) is not int or policy["max_redos"] < 0:
            raise ValueError("max_redos must be a nonnegative exact integer")
        paths = policy["allowed_changed_paths"]
        if not isinstance(paths, list) or len(paths) != len(set(paths)):
            raise ValueError("allowed_changed_paths must be a distinct list")
        for p in paths:
            _relative(p)
        _ids(policy["allowed_stages"], "allowed_stages", empty=True)
        checks = policy["required_checks"]
        if not isinstance(checks, list) or not checks:
            raise ValueError("required_checks must be nonempty")
        names, integrity = [], []
        for check in checks:
            _object(check, {"id", "kind"}, "required check")
            _ids([check["id"]], "check id")
            if check["kind"] not in ("integrity", "scientific"):
                raise ValueError("check kind must be integrity or scientific")
            names.append(check["id"])
            if check["kind"] == "integrity":
                integrity.append(check["id"])
        if len(names) != len(set(names)) or not integrity:
            raise ValueError("check IDs must be unique and include an integrity check")
        scopes = policy["claim_scopes"]
        if not isinstance(scopes, dict) or not scopes:
            raise ValueError("claim_scopes must be a nonempty mapping")
        for name, scope in scopes.items():
            _ids([name], "claim scope")
            _object(scope, {"checks", "actions"}, "claim scope")
            required = _ids(scope["checks"], "scope check IDs")
            _ids(scope["actions"], "scope actions")
            if not set(scope["actions"]) <= {"bulk", "delivery", "reuse"}:
                raise ValueError("invalid allowed claim-scope action")
            if not set(required) <= set(names) or not set(integrity) <= set(required):
                raise ValueError("every scope must include all integrity checks and only declared checks")
        return []
    except (ValueError, TypeError) as exc:
        return [str(exc)]


def _root(root):
    p = Path(root).resolve()
    if not p.is_dir():
        raise ValueError("review run directory does not exist")
    return p


def _path(root, value, *, allow_empty=False, _session=None):
    _text(value, "artifact path")
    if "://" in value:
        raise ValueError("review artifacts must be local files")
    if _session is not None:
        execution._check_validation_session(root, _session)
        path = _session.regular_file(value, root)
        if path.stat().st_size == 0 and not allow_empty:
            raise ValueError(f"review artifact is missing or empty: {value}")
        return path
    raw = Path(value) if Path(value).is_absolute() else root / value
    if raw.is_symlink() or any(p.is_symlink() for p in raw.parents):
        raise ValueError("review artifact paths cannot traverse symlinks")
    path = raw.resolve()
    if path.is_dir():
        raise ValueError(f"review inputs must be individual files; provide an explicit file manifest for directory: {value}")
    if not path.is_file() or (path.stat().st_size == 0 and not allow_empty):
        raise ValueError(f"review artifact is missing or empty: {value}")
    return path


def _identity(root, path):
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _pin(root, value, *, allow_empty=False, _session=None):
    if _session is not None:
        execution._check_validation_session(root, _session)
    p = _path(root, value, allow_empty=allow_empty, _session=_session)
    return {"path": _identity(root, p), "sha256": (_session.hash_file if _session is not None else execution.file_hash)(p)}


def _exclusive(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _policy(root, *, _session=None):
    if _session is not None:
        execution._check_validation_session(root, _session)
    policy = (_session.read_document if _session is not None else read_json)(root / POLICY)
    errors = validate_policy(policy)
    if errors:
        raise ValueError("; ".join(errors))
    approval, paths, errors = _approval_envelope(root, _session=_session)
    paths = [Path(p).resolve() for p in paths]
    if (root / POLICY) not in paths:
        raise ValueError("review policy must be prospectively bound into CHECK-IN 1 approval")
    if errors:
        raise ValueError("review needs valid CHECK-IN 1 approval: " + "; ".join(errors))
    return policy


def _science_run(root):
    return any((Path(root) / p).exists() for p in ('inputs/science.json', 'inputs/science-plan.json', 'inputs/science-approval.json'))


def _approval_envelope(root, *, _session=None):
    """Use the study's actual receipt; never synthesize a native compute approval."""
    if _science_run(root):
        from . import science
        return science.APPROVAL, science.approval_input_paths(root), science.verify_approval_envelope(root, _session=_session)
    from . import workflow_state
    # An optional approval input that is absent (the delegated-defaults record) is
    # covered by the approval fingerprint's absence hash; creating it later
    # invalidates the approval, so it has no file to pin here.
    paths = [p for p in workflow_state.approval_input_paths(str(root)) if os.path.lexists(p)]
    return 'inputs/checkin1_approval.json', paths, workflow_state.verify_approval(str(root))


def _waypoint_paths(root):
    if _science_run(root):
        from . import science
        return science.review_waypoint_paths(root)
    return ['inputs/checkin2.json', *waypoint_evidence.bound_paths(root)]


def _registration(root, *, create=False, _session=None, _capture_session=None):
    if _session is not None:
        execution._check_validation_session(root, _session)
    if create and _session is not None:
        raise ValueError("observation session cannot create review registration")
    if _capture_session is not None:
        if _session is not None or not create:
            raise ValueError("capture session is confined to registration creation")
        execution._check_validation_session(root, _capture_session)
    path = root / REGISTRATION
    if not path.exists():
        if not create:
            raise ValueError("review registration is missing")
        if (root / HEAD).exists() or list((root / DIRECTORY).glob("events/*.json")):
            raise ValueError("review registration disappeared; history cannot be reset")
        policy = _policy(root, _session=_capture_session)
        approval, inputs, _ = _approval_envelope(root, _session=_capture_session)
        # The valid approval envelope binds input bytes, including legitimate
        # empty runtime modules. Approval and review evidence remain nonempty.
        pins = [_pin(root, str(p), allow_empty=True, _session=_capture_session) for p in inputs]
        pins.append(_pin(root, approval, _session=_capture_session))
        rec = {"schema_version": 1, "run_id": uuid.uuid4().hex, "policy": policy,
               "bindings": pins, "attestation": ATTESTATION}
        rec["sha256"] = execution.digest(rec)
        _exclusive(path, rec)
        atomic_json(root / HEAD, {"sequence": 0, "sha256": rec["sha256"]})
    rec = (_session.read_document if _session is not None else read_json)(path)
    _object(rec, {"schema_version", "run_id", "policy", "bindings", "attestation", "sha256"}, "registration")
    if rec["sha256"] != execution.digest({k: v for k, v in rec.items() if k != "sha256"}) or validate_policy(rec["policy"]):
        raise ValueError("review registration or policy changed")
    return rec


MAX_RETAINED_BYTES = 1024 * 1024


def _read_raw_proof_document(root, value):
    """Bound the five administrative documents and retain descriptor identity."""
    from .validation_io import identity, settled
    source = _path(root, value)
    before = identity(settled(source.stat))
    if before[3] > MAX_INCIDENTAL_DOCUMENT_BYTES:
        raise ValueError('raw approved proof document exceeds retained limit')
    with source.open('rb') as stream:
        if identity(os.fstat(stream.fileno())) != before:
            raise ValueError('raw proof document changed before opening')
        raw = stream.read(MAX_INCIDENTAL_DOCUMENT_BYTES + 1)
        if (len(raw) > MAX_INCIDENTAL_DOCUMENT_BYTES
                or identity(os.fstat(stream.fileno())) != before):
            raise ValueError('raw proof document changed or exceeded bound during read')
    if (_path(root, value) != source or identity(source.stat()) != before
            or len(raw) != before[3]):
        raise ValueError('raw proof document changed after read')
    return raw


def _frozen_pin(root, pin, *, allow_empty=False, retain_large_proof_document=False, _session=None):
    source = _path(root, pin["path"], allow_empty=allow_empty, _session=_session)
    size = source.stat().st_size
    limit = MAX_INCIDENTAL_DOCUMENT_BYTES if retain_large_proof_document else MAX_RETAINED_BYTES
    if retain_large_proof_document and size > limit:
        raise ValueError("raw approved proof document exceeds retained limit")
    entry = {**pin, "size": size, "content_retained": size <= limit, "snapshot": None}
    if entry["content_retained"]:
        destination = root / DIRECTORY / "snapshots" / (pin["sha256"] + ".blob")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if retain_large_proof_document:
            raw = _read_raw_proof_document(root, pin['path'])
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != pin['sha256']:
                raise ValueError('raw proof document differs from captured source pin')
        if not destination.exists():
            with destination.open("xb") as dst:
                if retain_large_proof_document:
                    dst.write(raw)
                else:
                    with source.open("rb") as src:
                        shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
        if _session is not None:
            _session.require_regular(destination)
        if (_session.hash_file if _session is not None else execution.file_hash)(destination) != pin["sha256"]:
            raise ValueError("frozen content-addressed evidence changed")
        entry["snapshot"] = destination.relative_to(root).as_posix()
    if (_session.hash_file if _session is not None else execution.file_hash)(source) != pin["sha256"] or source.stat().st_size != size:
        raise ValueError("review evidence changed while taking snapshot")
    return entry


def _snapshots(root, values, label, *, allow_empty=(), raw_proof_documents=(), _session=None):
    allowed = set(allow_empty)
    pins = [_pin(root, v, allow_empty=v in allowed, _session=_session) for v in values]
    if len({p["path"] for p in pins}) != len(pins):
        raise ValueError("duplicate review evidence identities")
    raw_documents = set(raw_proof_documents)
    return [_frozen_pin(root, p, allow_empty=p["path"] in allowed, _session=_session, **({"retain_large_proof_document": True} if p["path"] in raw_documents else {})) for p in pins]


def _empty_input_paths(reg, cycle=None):
    """Only bound inputs may carry empty content, never located check evidence.

    Registration appends the nonempty approval document after its input pins.
    Cycle input identities come from successful, validated execution receipts.
    """
    paths = {p["path"] for p in reg["bindings"][:-1]}
    if cycle:
        paths.update(p for r in cycle["receipts"] for p in r["inputs"])
        paths.difference_update(p["path"] for p in cycle["effective_settings"])
        paths.difference_update(ref["path"] for c in cycle["checks"] for ref in c["evidence"])
    return paths


MAX_INCIDENTAL_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_INCIDENTAL_PROOF_BYTES = 4 * MAX_INCIDENTAL_DOCUMENT_BYTES


def _incidental_output_paths(reg, cycle):
    """Derive zero custody from frozen approved documents, never live labels."""
    if not cycle:
        return set()
    from .state_io import _unique
    from . import science
    pins = {p['path']: p for p in cycle['snapshots']}
    registered = {p['path']: p['sha256'] for p in reg['bindings']}
    paths = set()
    for receipt in cycle['receipts']:
        proof = receipt.get('incidental_output_proof')
        if proof is None:
            continue
        proof_keys = {'schema_version', 'specification', 'plan', 'checkin', 'approval', 'receipt'}
        if science.METHOD_DECISION in registered:
            proof_keys.add('method_decision')
        _object(proof, proof_keys, 'incidental-output proof')
        if type(proof['schema_version']) is not int or proof['schema_version'] != 1:
            raise ValueError('invalid incidental-output proof version')
        documents, total = {}, 0
        expected = {'specification': science.SPEC, 'plan': science.PLAN, 'checkin': 'inputs/checkin1.json',
                    'approval': science.APPROVAL, 'receipt': receipt['path']}
        if 'method_decision' in proof_keys:
            expected['method_decision'] = science.METHOD_DECISION
        for key, identity in expected.items():
            source = proof[key]
            _object(source, {'path', 'sha256', 'text'}, 'frozen incidental-output document')
            if type(source['text']) is not str:
                raise ValueError('frozen incidental-output document must be text')
            raw = source['text'].encode('utf-8'); total += len(raw)
            pin = pins.get(identity)
            if (source['path'] != identity or not raw or len(raw) > MAX_INCIDENTAL_DOCUMENT_BYTES
                    or total > MAX_INCIDENTAL_PROOF_BYTES or pin is None
                    or hashlib.sha256(raw).hexdigest() != source['sha256'] or pin['sha256'] != source['sha256']
                    or pin['size'] != len(raw) or pin['content_retained'] is not True
                    or pin['snapshot'] != f"{DIRECTORY}/snapshots/{source['sha256']}.blob"
                    or key != 'receipt' and registered.get(identity) != source['sha256']):
                raise ValueError('incidental-output proof is unbound, missing or oversized')
            def reject(value):
                raise ValueError('nonfinite incidental-output proof: ' + value)
            documents[key] = json.loads(source['text'], object_pairs_hook=_unique, parse_constant=reject)
            execution.digest(documents[key])  # Reject overflowing finite-token floats too.
        spec, plan, checkin, approval, record = (documents[k] for k in ('specification', 'plan', 'checkin', 'approval', 'receipt'))
        method_record = documents.get('method_decision')
        if method_record is not None:
            from .method_selection import escalation_allowed
            allowed, reason = escalation_allowed(method_record)
            if not allowed:
                raise ValueError(reason)
        science.validate(spec)
        science._keys(plan, {'schema_version', 'mode', 'base_dir', 'stages', 'stage_binding', 'max_seconds',
                             'max_attempts', 'approval_mode', 'expert_review', 'execution_task', 'mutable_inputs', 'mutable_paths'}
                     | ({'prepared_runtime'} if 'prepared_runtime' in plan else set()),
                      'frozen incidental-output science plan')
        if 'prepared_runtime' in plan:
            from .prepared_runtime import validate as validate_prepared
            validate_prepared(plan['prepared_runtime'], plan['stage_binding'], live_interpreter=False)
        science._v2_approval_keys(approval, 'frozen incidental-output approval')
        from .launch_authorization import parse_utc
        if (type(approval['schema_version']) is not int or approval['schema_version'] != 2
                or approval['generated_by'] != 'ravel.workflow.science.approve'
                or approval['approval_mode'] != spec['approval_mode']
                or type(approval['quote']) is not str or not approval['quote'].strip()
                or parse_utc(approval['utc']) > parse_utc(record['started_utc'])
                or parse_utc(record['started_utc']) > parse_utc(record['finished_utc'])):
            raise ValueError('incidental-output approval schema, mode or execution timing differs')
        if type(plan['stages']) is not list or len(plan['stages']) != 1:
            raise ValueError('incidental-output proof requires exactly one stage')
        declared = execution.output_policy_fields(spec)
        binding = plan['stage_binding']
        committed_keys = ('command', 'cwd', 'inputs', 'outputs', 'input_snapshot', 'parents', 'runtime')
        committed = {key: record[key] for key in committed_keys} | execution.stage_metadata_fields(record)
        if (execution.digest(committed) != record['fingerprint']
                or any(record[key] != binding[key] for key in committed_keys)):
            raise ValueError('incidental-output record committed specification differs from approved binding')
        if (spec['schema_version'] != 2 or 'output_policy' not in spec or plan['schema_version'] != 2
                or plan['max_attempts'] != 1 or spec['max_attempts'] != 1
                or plan['mode'] != spec['mode'] or plan['approval_mode'] != spec['approval_mode']
                or plan['max_seconds'] != spec['max_seconds'] or plan['expert_review'] is not False
                or plan['stages'][0]['outputs'] != ['outputs/attempt-1']
                or execution.output_policy_fields(plan['stages'][0]) != declared
                or execution.output_policy_fields(binding) != declared
                or execution.output_policy_fields(record) != declared
                or binding['fingerprint'] != execution.digest({k:v for k,v in binding.items() if k != 'fingerprint'})
                or record['fingerprint'] != binding['fingerprint'] or record['stage'] != 'science'
                or record['status'] != 'succeeded' or record['exit_code'] != 0
                or record['receipt_sha256'] != execution.receipt_digest(record)
                or record['receipt_sha256'] != receipt['receipt_sha256'] or record['attempt_id'] != receipt['attempt_id']
                or approval['plan_sha256'] != proof['plan']['sha256']
                or approval['checkin_sha256'] != proof['checkin']['sha256']
                or approval['expert_review'] is not False or not approval['quote'].strip()
                or checkin != science.make_checkin(spec, proof['plan']['sha256'], plan['stages'][0],
                                                   base=plan['base_dir'], method_decision=method_record)):
            raise ValueError('incidental-output proof differs from approved successful execution')
        approval_paths = [science.PLAN, science.SPEC, 'inputs/checkin1.json', science.REVIEW_POLICY]
        if method_record is not None:
            approval_paths.append(science.METHOD_DECISION)
        if (any(p not in registered for p in approval_paths)
                or approval['input_fingerprint'] != hashlib.sha256(''.join(registered[p] for p in approval_paths).encode()).hexdigest()):
            raise ValueError('incidental-output proof approval input binding differs')
        root = Path(binding['cwd'])
        if not root.is_absolute() or record['cwd'] != str(root):
            raise ValueError('incidental-output proof root differs')
        from .validation_io import _generated_sector_declaration, _generated_sector_indices
        families = [e for e in spec['output_policy']['allow_empty_directory_members'] if e['role'] == 'generated_build_marker_family']
        literal_policy = {**spec['output_policy'], 'allow_empty_directory_members': [e for e in spec['output_policy']['allow_empty_directory_members'] if e not in families]}
        execution.validate_output_policy(root, record['outputs'], literal_policy, execution.resolve_path, input_snapshot=record['input_snapshot'], input_paths=record['inputs'], require_input_binding=True)
        allowed = {entry['path'] for entry in literal_policy['allow_empty_directory_members']}
        for family in families:
            source = _generated_sector_declaration(family, record['input_snapshot'], record['inputs'], root, True)
            frozen = pins.get(source['path'])
            if (frozen is None
                    or frozen['sha256'] != source['sha256'] or frozen['size'] != source['size']
                    or frozen['content_retained'] is not True
                    or frozen['snapshot'] != f"{DIRECTORY}/snapshots/{source['sha256']}.blob"):
                raise ValueError('generated marker producer is not exact retained approved singleton input evidence')
            inventory = record['output_snapshot'].get(str(root/'outputs/attempt-1'))
            if type(inventory) is not dict or inventory.get('kind') != 'directory':
                raise ValueError('generated marker family lacks committed output census')
            prefix = family['path'][len('outputs/attempt-1/'):] + '/'
            rows = [{'name': r['name'][len(prefix):], 'size': r['size']} for r in inventory['files'] if r['name'].startswith(prefix)]
            allowed.update(family['path'] + '/' + name for name in _generated_sector_indices(family, rows))
        zero = set()
        for directory, inventory in record['output_snapshot'].items():
            if directory != str(root/'outputs/attempt-1') or inventory['kind'] != 'directory':
                raise ValueError('incidental-output proof inventory differs from declared directory')
            for entry in inventory['files']:
                if entry['size'] != 0:
                    continue
                name = entry['name']
                if type(name) is not str or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
                    raise ValueError('unsafe zero output inventory member')
                value = 'outputs/attempt-1/' + name
                if value not in allowed or entry['sha256'] != hashlib.sha256(b'').hexdigest():
                    raise ValueError('zero output is not an exact approved incidental member')
                zero.add(value)
        paths.update(zero)
    return paths


def _large_proof_document_allowed(pin, reg, cycle):
    """Retain only five exact raw approved documents beyond the generic limit.

    Historical unretained commitments retain their original oneMiB meaning.
    No scientific/hold evidence inherits the larger administrative-document cap.
    """
    if type(pin.get('size')) is not int or not MAX_RETAINED_BYTES < pin['size'] <= MAX_INCIDENTAL_DOCUMENT_BYTES:
        return False
    for receipt in cycle.get('receipts', []):
        proof = receipt.get('incidental_output_proof', {})
        for key in ('specification', 'plan', 'checkin', 'approval', 'receipt', 'method_decision'):
            document = proof.get(key)
            if (type(document) is dict and document.get('path') == pin.get('path')
                    and document.get('sha256') == pin.get('sha256')
                    and type(document.get('text')) is str
                    and len(document['text'].encode('utf-8')) == pin['size']):
                _incidental_output_paths(reg, cycle)
                return True
    return False



def _approved_zero_paths(root, record):
    """Only exact committed zero members admitted by the successful stage policy."""
    from .validation_io import _empty_directory_members
    allowed=_empty_directory_members(root,record['outputs'],True,record.get('output_policy'),execution.resolve_path,
        input_snapshot=record['input_snapshot'],input_paths=record['inputs'])
    result=set()
    for directory,inventory in record['output_snapshot'].items():
        for row in inventory['files']:
            if row['size']==0:
                path=Path(directory)/row['name']
                if path not in allowed or row['sha256']!=hashlib.sha256(b'').hexdigest():
                    raise ValueError('zero review member is outside exact approved output policy')
                result.update((str(path),_identity(root,path)))
    return result

def _empty_artifact_paths(reg, cycle=None):
    paths = _empty_input_paths(reg, cycle) | _incidental_output_paths(reg, cycle)
    if cycle:
        paths.difference_update(p['path'] for p in cycle['effective_settings'])
        paths.difference_update(ref['path'] for c in cycle['checks'] for ref in c['evidence'])
    return paths


def _empty_snapshot_allowed(pin, reg, cycle):
    return (type(pin.get("size")) is int and pin["size"] == 0
            and pin["path"] in _empty_artifact_paths(reg, cycle)
            and pin["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            and pin["content_retained"] is True
            and pin["snapshot"] == f"{DIRECTORY}/snapshots/{pin['sha256']}.blob")


def _read(root, *, _session=None):
    if _session is not None:
        execution._check_validation_session(root, _session)
    reg = _registration(root, _session=_session)
    if _session is not None:
        _session.require_inventory(root / DIRECTORY / "events")
    head = (_session.read_document if _session is not None else read_json)(root / HEAD)
    _object(head, {"sequence", "sha256"}, "review checkpoint")
    previous, events = reg["sha256"], []
    for n, path in enumerate(sorted((root / DIRECTORY / "events").glob("*.json")), 1):
        e = (_session.read_document if _session is not None else read_json)(path)
        if (path.name != f"{n:08d}.json" or e.get("sequence") != n
                or e.get("previous_sha256") != previous or e.get("run_id") != reg["run_id"]
                or e.get("sha256") != execution.digest({k: v for k, v in e.items() if k != "sha256"})
                or e.get("event") not in ("cycle", "review", "correction", "correction_failed", "scientific_hold")):
            raise ValueError("review journal sequence or digest changed")
        for pin in e.get("snapshots", []):
            cycle = e if e["event"] == "cycle" else _view(reg, events)["cycle"]
            empty_input = _empty_snapshot_allowed(pin, reg, cycle)
            if pin["size"] == 0 and not empty_input:
                raise ValueError("empty review evidence is not a bound input")
            if pin["content_retained"]:
                if pin["size"] > MAX_RETAINED_BYTES and not _large_proof_document_allowed(pin, reg, cycle):
                    raise ValueError("large retained evidence is not an exact approved raw proof document")
                p = _path(root, pin["snapshot"], allow_empty=empty_input)
                if _session is not None:
                    _session.require_regular(p)
                if not p.is_relative_to(root / DIRECTORY / "snapshots") or (_session.hash_file if _session is not None else execution.file_hash)(p) != pin["sha256"] or p.stat().st_size != pin["size"]:
                    raise ValueError("frozen review evidence changed")
            elif pin["snapshot"] is not None or pin["size"] <= MAX_RETAINED_BYTES:
                raise ValueError("invalid unretained evidence commitment")
        previous = e["sha256"]
        events.append(e)
    if type(head["sequence"]) is not int or head != {"sequence": len(events), "sha256": previous}:
        raise ValueError("review journal/checkpoint mismatch; deleted history cannot reset review")
    if events:
        errors = validate_snapshot({"schema_version": 1, "registration": reg, "events": events,
            "checkpoint": head, "action": "history", "stage": None}, require_admission=False)
        if errors:
            raise ValueError("; ".join(errors))
    return reg, events


def _append(root, reg, events, payload):
    from .launch_authorization import operational_utc, parse_utc
    stamp = operational_utc()
    if events and parse_utc(stamp) < parse_utc(events[-1]["utc"]):
        raise ValueError("review operational clock moved backwards")
    e = {"schema_version": 1, "sequence": len(events) + 1,
         "previous_sha256": events[-1]["sha256"] if events else reg["sha256"],
         "run_id": reg["run_id"], "utc": stamp, **payload}
    e["sha256"] = execution.digest(e)
    _exclusive(root / DIRECTORY / "events" / f"{e['sequence']:08d}.json", e)
    atomic_json(root / HEAD, {"sequence": e["sequence"], "sha256": e["sha256"]})
    return e


CONTEXT_SUPPORT_FIELDS = {"kind", "path", "sha256", "manifest_sha256", "cycle_id", "cycle_sha256"}


def _support_shape(pin):
    fields = CONTEXT_SUPPORT_FIELDS if isinstance(pin, dict) and pin.get("kind") == "role_context" else {"path", "sha256"}
    _object(pin, fields, "supporting judgment artifact")
    _text(pin["path"], "supporting path")
    for field in ("sha256", "manifest_sha256", "cycle_sha256"):
        if field in pin and (type(pin[field]) is not str or not re.fullmatch(r"[0-9a-f]{64}", pin[field])):
            raise ValueError("invalid supporting artifact SHA-256")
    if fields == CONTEXT_SUPPORT_FIELDS:
        _text(pin["cycle_id"], "supporting cycle identity")


def _readonly_context_sources(root, index, session):
    """Retain actual typed packet/source-capture facts past every callback.

    Used only by the explicitly Session-bound read-only correction gate. The
    default public context reader keeps its original callback and policy law.
    """
    session.require_inventory(index.root)
    session.require_inventory(index.root / "artifacts")
    # Preserve the reader's original higher-ancestor identities, not just the
    # packet root/member census. Generic Capture-only transport has no index.
    for path, expected in getattr(index, "parents", {}).items():
        session.retain_path_identity(path, expected)
    capture = index.source_capture
    if capture is None:
        return
    # SourceCapture owns the actual files and declared source population. Do not
    # reduce a native typed packet to only its copied manifest/artifact leaves.
    for path, (_, raw) in capture.files.items():
        source = session.regular_file(str(path), root)
        if session.hash_file(source) != hashlib.sha256(raw).hexdigest():
            raise ValueError("typed role context original source changed")
    for directory in capture.roots:
        session.require_inventory(directory)
    for observed in capture.paths.values():
        for path, expected in observed.items():
            session.retain_path_identity(path, expected)
    for path in getattr(capture, "review_paths", ()):
        source = session.regular_file(str(path), root)
        session.hash_file(source)


def _context_support(root, pin, session):
    """One typed commitment authenticates every indexed copy, never truncates.

    The existing 512 outer-support ceiling stays fixed. Copies retain the
    reader's explicitly bounded inventory/authentication declaration (legacy
    defaults 10000 members/256MiB; maxima 20000/512MiB), 64MiB files, plus a final
    identity/membership census in the same validation observation.
    """
    from . import review_context
    _support_shape(pin)
    reg, events = _read(root, _session=session)
    cycles = [e for e in events if e["event"] == "cycle" and e["cycle_id"] == pin["cycle_id"]
              and e["sha256"] == pin["cycle_sha256"]]
    if len(cycles) != 1:
        raise ValueError("role context belongs to an unknown scientific cycle")
    cycle = cycles[0]
    manifest_path = _path(root, pin["path"], _session=session)
    if manifest_path.name != "manifest.json":
        raise ValueError("role context must name its exact manifest")
    session.regular_file(str(manifest_path), root)
    index = review_context._PacketIndex(manifest_path.parent, pin["manifest_sha256"])
    if (index.manifest.get("cycle_id") != cycle["cycle_id"]
            or index.manifest.get("source_event_sha256") != cycle["sha256"]):
        raise ValueError("supporting role context has a foreign cycle")
    if session.hash_file(manifest_path) != pin["sha256"]:
        raise ValueError("supporting role context manifest changed")
    allowed = _empty_input_paths(reg, cycle)
    empty_sources = {p["path"]: p["sha256"] for p in cycle["snapshots"]
                     if p.get("size") == 0 and p["path"] in allowed and _empty_snapshot_allowed(p, reg, cycle)}
    for entry in index.entries.values():
        path = index.paths[entry["id"]]
        session.regular_file(str(path), root)
        raw = index.read(entry)
        if not raw and not (entry.get("source_phase") == "current_cycle"
                and entry.get("projection") == "exact bytes"
                and entry.get("source_path") in empty_sources
                and entry.get("source_sha256") == empty_sources[entry["source_path"]] == entry["sha256"]
                and re.fullmatch(r"a[0-9]{4,}", entry["id"])
                and entry["id"] == f"a{int(entry['id'][1:]):04d}"):
            raise ValueError("empty role context copy is not an exact retained SOURCE input")
    readonly = session.proofs.get(("readonly-correction-gate",)) is True
    if readonly:
        _readonly_context_sources(root, index, session)
    if readonly and getattr(session, "_readonly_frozen", False):
        # The original index callback was enrolled before freeze. A fresh
        # semantic recheck must not register a second frozen callback. Its
        # actual dependencies remain in the owning complete terminal census.
        index.finish()
    else:
        session.retain_final_check(index.finish)
    return {**pin, "path": _identity(root, manifest_path)}


def _live_pins(root, pins, *, allow_empty=(), _session=None):
    if _session is not None:
        execution._check_validation_session(root, _session)
    if _session is None and any(isinstance(p, dict) and p.get("kind") == "role_context" for p in pins):
        session = execution._validation_session(root)
        try:
            _live_pins(root, pins, allow_empty=allow_empty, _session=session)
            errors = session.finish()
            if errors: raise ValueError("; ".join(errors))
            return
        finally:
            session.close()
    allowed = set(allow_empty)
    for pin in pins:
        if isinstance(pin, dict) and pin.get("kind") == "role_context":
            _context_support(root, pin, _session)
            continue
        if _pin(root, pin["path"], allow_empty=pin["path"] in allowed, _session=_session) != {"path": pin["path"], "sha256": pin["sha256"]}:
            raise ValueError(f"review evidence changed: {pin['path']}")


def _amendment_names(approval, prior_sha256):
    """Paths named by the re-approvals recorded since the approval with this digest, or None."""
    rows = approval.get("input_changes") if isinstance(approval, dict) else None
    if not isinstance(rows, list):
        return None
    start = next((n for n, row in enumerate(rows) if isinstance(row, dict)
                  and row.get("prior_approval_sha256") == prior_sha256), None)
    return None if start is None else {row.get("path") for row in rows[start:] if isinstance(row, dict)}


def amended_paths(reg, approval, approval_sha256):
    """Registered approval inputs that an amendment re-approval names since registration.

    The registered first approval admits none. A different approval is accepted
    only when it records the CHECK-IN 1 re-approval of input changes made against
    the registered approval, and only for paths the review policy prospectively
    allows to change. Its bytes are verified by the approval itself; this
    names which registered pins it replaces and grants no execution authority.
    """
    registered = reg["bindings"][-1]
    if approval_sha256 == registered["sha256"]:
        return set()
    named = _amendment_names(approval, registered["sha256"])
    if named is None:
        raise ValueError("CHECK-IN 1 approval differs from the review registration and records no amendment "
                         "re-approval of it; record an amendment and re-approve CHECK-IN 1")
    outside = sorted(str(p) for p in named - set(reg["policy"]["allowed_changed_paths"]))
    if outside:
        raise ValueError("amendment re-approval changes inputs outside the review policy's allowed changed paths: "
                         + ", ".join(outside))
    return named | {registered["path"]}


def _approval_amendment(root, reg, *, _session=None):
    if _science_run(root):
        return set()
    # _policy has already verified this approval against the live inputs.
    from .approval_inputs import APPROVAL as approval
    pin = _pin(root, approval, _session=_session)
    record = (_session.read_document if _session is not None else read_json)(_path(root, approval, _session=_session))
    if pin["path"] != reg["bindings"][-1]["path"]:
        raise ValueError("review registration binds a different CHECK-IN 1 approval document")
    return amended_paths(reg, record, pin["sha256"])


def _base_live(root, reg, *, _session=None):
    """Return the registered inputs replaced by a CHECK-IN 1 amendment re-approval."""
    if _session is not None:
        execution._check_validation_session(root, _session)
    actual_policy = _policy(root, _session=_session)
    if actual_policy != reg["policy"]:
        raise ValueError("registered review policy cannot be widened or replaced")
    amended = _approval_amendment(root, reg, _session=_session)
    _live_pins(root, [p for p in reg["bindings"] if p["path"] not in amended],
               allow_empty=_empty_input_paths(reg), _session=_session)
    return amended


def _view(reg, events):
    cycles = [e for e in events if e["event"] == "cycle"]
    current = cycles[-1] if cycles else None
    reviews = [e for e in events if e["event"] == "review" and current and e["cycle_id"] == current["cycle_id"]]
    corrections = [e for e in events if e["event"] == "correction"]
    active = next((e for e in reversed(corrections) if current and e["cycle_id"] == current["cycle_id"]), None)
    failed = active and any(e["event"] == "correction_failed" and e["correction_id"] == active["correction_id"] for e in events)
    inherited = current["inherited_findings"] if current else []
    findings = [*inherited, *(f for e in reviews for f in e["findings"])]
    verdicts = [e["verdict"] for e in reviews]
    state = "unopened" if not current else "awaiting_review"
    if "stop" in verdicts:
        state = "stopped"
    elif "send_back" in verdicts:
        state = "correction_failed" if failed else "correction_admitted" if active else "send_back"
    elif len(reviews) == len(ROLES) and all(v == "accept" for v in verdicts):
        state = "accepted"
        findings = []
    holds = [e for e in events if e["event"] == "scientific_hold" and current and e["cycle_id"] == current["cycle_id"]]
    if holds:
        state = "scientific_hold"
        findings = [f for e in holds for f in _hold_document(e["finding_context"])["findings"]]
    return {"state": state, "cycle": current, "reviews": reviews, "correction": active, "holds": holds,
            "findings": findings, "redos_used": len(corrections), "redos_remaining": reg["policy"]["max_redos"] - len(corrections)}


def _receipt(root, value, *, _session=None):
    path = _path(root, value, _session=_session)
    record = (_session.read_document if _session is not None else read_json)(path)
    stage = record.get("stage") if isinstance(record, dict) else None
    _ids([stage], "receipt stage")
    current = execution.load_execution(root)["stages"].get(stage)
    if (current != record or not record.get("attempt_id") or record.get("status") != "succeeded"
            or not record.get("receipt_sha256") or _path(root, record["attempt_record"]) != path):
        raise ValueError("stage receipt must be a current successful retained execution attempt")
    errors = execution.stage_errors(root, stage, _session=_session)
    if errors:
        raise ValueError("stage receipt invalid: " + "; ".join(errors))
    result = {"stage": stage, "attempt_id": record["attempt_id"], "receipt_sha256": record["receipt_sha256"],
              "path": _identity(root, path), "inputs": [_identity(root, _path(root, p, allow_empty=True, _session=_session)) for p in record["inputs"]],
              "outputs": [str(execution.resolve_path(root, p)) for p in record["outputs"]]}
    if 'output_policy' in record:
        if not _science_run(root) or stage != 'science':
            raise ValueError('incidental output review proof requires prospective science')
        from . import science
        proposal = science.verify_plan(root, approved=True, _session=_session)
        if record['fingerprint'] != proposal['stage_binding']['fingerprint']:
            raise ValueError('incidental output receipt differs from exact approved stage')
        proof = {'schema_version': 1}
        files = {'specification': science.SPEC, 'plan': science.PLAN, 'checkin': 'inputs/checkin1.json',
                 'approval': science.APPROVAL, 'receipt': str(path)}
        if str(root / science.METHOD_DECISION) in science.approval_input_paths(root):
            files['method_decision'] = science.METHOD_DECISION
        total = 0
        for key, value in files.items():
            source = _path(root, value, _session=_session); raw = _read_raw_proof_document(root, value); total += len(raw)
            if len(raw) > MAX_INCIDENTAL_DOCUMENT_BYTES or total > MAX_INCIDENTAL_PROOF_BYTES:
                raise ValueError('incidental output review proof exceeds bounded retained-document budget')
            proof[key] = {'path': _identity(root, source), 'sha256': hashlib.sha256(raw).hexdigest(), 'text': raw.decode('utf-8')}
        result['incidental_output_proof'] = proof
    return result


def _checks(root, path, policy, receipts, *, _session=None):
    # Canonicalize a private working copy; the parsed source document remains
    # immutable in the observation session through its final custody check.
    doc = deepcopy((_session.read_document if _session is not None else read_json)(_path(root, path, _session=_session)))
    _object(doc, {"schema_version", "checks"}, "check results")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1 or not isinstance(doc["checks"], list):
        raise ValueError("invalid check-results schema")
    declared = {c["id"] for c in policy["required_checks"]}
    names, evidence = [], []
    attempts = {r["attempt_id"] for r in receipts}
    for c in doc["checks"]:
        _object(c, {"id", "status", "evidence", "attempt_ids"}, "check result")
        from ravel.validation.claim_checks import computed_id
        if computed_id(c["id"]):
            raise ValueError("host-asserted status refused for computed check " + c["id"])
        _ids([c["id"]], "check id")
        if c["status"] not in ("pass", "fail", "inconclusive"):
            raise ValueError("check status must be pass, fail or inconclusive")
        _ids(c["attempt_ids"], "check attempt IDs")
        if not set(c["attempt_ids"]) <= attempts:
            raise ValueError("check refers to an unbound execution attempt")
        if not isinstance(c["evidence"], list) or not c["evidence"]:
            raise ValueError("check needs located evidence")
        for ref in c["evidence"]:
            _object(ref, {"path", "location"}, "located check evidence")
            _text(ref["location"], "evidence location")
            # Store the checked canonical identity, including for absolute input
            # references, so detached role checks cannot relabel empty inputs.
            ref["path"] = _pin(root, ref["path"], _session=_session)["path"]
            evidence.append(ref["path"])
        names.append(c["id"])
    from ravel.validation.claim_checks.envelope import review_checks
    machine = review_checks(root, declared, receipts, _session=_session)
    doc["checks"] += machine
    names += [c["id"] for c in machine]
    evidence += [ref["path"] for c in machine for ref in c["evidence"]]
    if set(names) != declared or len(names) != len(declared):
        raise ValueError("check results must cover every prospectively declared check exactly once")
    return doc["checks"], evidence


def open_cycle(root, *, effective_settings, stage_receipts, check_results, correction_id=None, checkpoint=False, retained_study=False, final_results=None):
    """Freeze a waypoint and actual execution evidence, initially or after admitted correction."""
    if type(retained_study) is not bool: raise ValueError('retained_study must be explicit')
    if retained_study:
        literal = Path(root).expanduser().absolute()
        if any(p.is_symlink() for p in (literal, *literal.parents)):
            raise ValueError('retained initial opening must not traverse a symlink')
    root = _root(root)
    with file_lock(root / DIRECTORY / "write.lock"):
        session = execution._validation_session(root)
        try:
            if retained_study:
                if correction_id is not None or checkpoint or final_results is not None:
                    raise ValueError('retained opening is only the immutable first cycle')
                from .retained_science_review import capture_initial
                reg,events,payload=capture_initial(root,check_results=check_results,
                    stage_receipts=stage_receipts,effective_settings=effective_settings,session=session)
            else:
                reg, events, payload = _capture_cycle(root, effective_settings=effective_settings,
                    stage_receipts=stage_receipts, check_results=check_results,
                    correction_id=correction_id, checkpoint=checkpoint, final_results=final_results, _session=session)
            session.track(payload)
            final_errors = session.finish()
            if final_errors:
                raise ValueError("; ".join(final_errors))
            return _append(root, reg, events, payload)
        finally:
            session.close()


def _capture_cycle(root, *, effective_settings, stage_receipts, check_results,
                   correction_id, checkpoint, _session, final_results=None):
    if not registered(root):
        initial_policy = _policy(root, _session=_session)
        if not isinstance(effective_settings, list) or not effective_settings or not isinstance(stage_receipts, list) or not stage_receipts:
            raise ValueError("cycle needs actual effective settings and successful stage receipts")
        for value in effective_settings:
            _pin(root, value, _session=_session)
        initial_receipts = [_receipt(root, p, _session=_session) for p in stage_receipts]
        _checks(root, check_results, initial_policy, initial_receipts, _session=_session)
        _waypoint_paths(root)
    _registration(root, create=True, _capture_session=_session)
    reg, events = _read(root, _session=_session)
    _base_live(root, reg, _session=_session)
    view = _view(reg, events)
    _judgments_live(root, view, _session=_session)
    if not isinstance(effective_settings, list) or not effective_settings or not isinstance(stage_receipts, list) or not stage_receipts:
        raise ValueError("cycle needs actual effective settings and successful stage receipts")
    settings = [_pin(root, v, _session=_session) for v in effective_settings]
    if len({p["path"] for p in settings}) != len(settings):
        raise ValueError("duplicate effective settings")
    receipts = [_receipt(root, p, _session=_session) for p in stage_receipts]
    if len({r["stage"] for r in receipts}) != len(receipts):
        raise ValueError("duplicate stage receipt")
    checks, checked_paths = _checks(root, check_results, reg["policy"], receipts, _session=_session)
    inherited = []
    final_binding, final_paths = None, []
    if final_results is not None:
        if not checkpoint or view["state"] != "accepted" or correction_id is not None:
            raise ValueError("CHECK-IN 3 needs accepted CI2 and its unchanged correction journal")
        from . import final_results_review
        final_binding, final_paths = final_results_review.capture(root, final_results, view["cycle"], checks, session=_session)
    if type(checkpoint) is not bool:
        raise ValueError("checkpoint must be a boolean")
    if checkpoint:
        if view["state"] != "accepted" or correction_id is not None or settings != view["cycle"]["effective_settings"]:
            raise ValueError("checkpoint requires accepted work with identical effective settings")
        old_attempts = {r["attempt_id"] for r in view["cycle"]["receipts"]}
        fresh = [r for r in receipts if r["attempt_id"] not in old_attempts]
        if not fresh and final_binding is None:
            raise ValueError("checkpoint requires a newly successful execution attempt")
        if final_binding is not None and receipts != view["cycle"]["receipts"]:
            raise ValueError("final checkpoint cannot substitute execution evidence")
        fresh_ids = {r["attempt_id"] for r in fresh}
        outputs = [Path(p) for r in fresh for p in r["outputs"]]
        if final_binding is None and not any(fresh_ids.intersection(c["attempt_ids"]) and any(
                any(_path(root, ref["path"]) == out or _path(root, ref["path"]).is_relative_to(out) for out in outputs)
                for ref in c["evidence"]) for c in checks):
            raise ValueError("checkpoint must check an output of the new attempt")
    elif view["cycle"]:
        if view["state"] != "correction_admitted" or correction_id != view["correction"]["correction_id"]:
            raise ValueError("successor requires an admitted, unspent correction; no cycle reset")
        correction = view["correction"]
        _live_pins(root, correction["snapshots"], allow_empty=_empty_artifact_paths(reg, view["cycle"]))
        if settings != correction["effective_settings"]:
            raise ValueError("successor effective settings differ from admitted exact bytes")
        prior = {r["stage"]: r for r in view["cycle"]["receipts"]}
        fresh = {r["stage"]: r for r in receipts}
        for stage in correction["stages"]:
            if stage not in fresh or (stage in prior and fresh[stage]["attempt_id"] == prior[stage]["attempt_id"]):
                raise ValueError(f"correction needs a new successful attempt for {stage}")
            record = read_json(_path(root, fresh[stage]["path"]))
            actual_spec = _stage_spec(root, {"stage": stage, **{k: record[k] for k in ("command", "cwd", "inputs", "outputs", "log")},
                                            "depends_on": list(record["parents"])})
            if actual_spec != next(s for s in correction["stage_specs"] if s["stage"] == stage):
                raise ValueError("corrected execution does not match its admitted stage specification")
        for finding in view["findings"]:
            relevant = {fresh[s]["attempt_id"] for s in finding["required_stages"]}
            for cid in finding["check_ids"]:
                check = next(c for c in checks if c["id"] == cid)
                if not relevant <= set(check["attempt_ids"]):
                    raise ValueError("recheck must cite each new required-stage attempt")
                outputs = [Path(p) for s in finding["required_stages"] for p in fresh[s]["outputs"]]
                if not any(any(_path(root, e["path"]) == p or _path(root, e["path"]).is_relative_to(p) for p in outputs) for e in check["evidence"]):
                    raise ValueError("recheck evidence must include an output of the new required attempt")
        inherited = view["findings"]
    elif correction_id is not None:
        raise ValueError("initial cycle cannot claim a correction")
    waypoint_paths = _waypoint_paths(root)
    approval, approved_inputs, _ = _approval_envelope(root, _session=_session)
    input_paths = [p for r in receipts for p in r["inputs"]]
    empty_inputs = set()
    for p in [*approved_inputs, *input_paths]:
        resolved = _path(root, str(p), allow_empty=True, _session=_session)
        empty_inputs.update((str(resolved), _identity(root, resolved)))
    # Expand source-defined families from the exact successful census; no wildcard.
    for receipt in receipts:
        record=(_session.read_document if _session is not None else read_json)(_path(root,receipt['path'],_session=_session))
        empty_inputs.update(_approved_zero_paths(root,record))
    values = list(dict.fromkeys([POLICY, approval, *approved_inputs, *waypoint_paths,
                                *[s["path"] for s in settings], *[r["path"] for r in receipts],
                                check_results, *checked_paths, *input_paths, *final_paths]))
    # Normalize aliases before deduplication; pin actual files, not merely intended TOML.
    values = list(dict.fromkeys(_pin(root, p, allow_empty=p in empty_inputs, _session=_session)["path"] for p in values))
    cycle_id = uuid.uuid4().hex
    raw_documents = {document['path'] for r in receipts if 'incidental_output_proof' in r
                     for key, document in r['incidental_output_proof'].items() if key != 'schema_version'}
    snapshots = _snapshots(root, values, cycle_id, allow_empty=empty_inputs, raw_proof_documents=raw_documents, _session=_session)
    _base_live(root, reg, _session=_session)
    if final_binding is not None:
        captured = {str(_path(root, p["path"])): p["sha256"] for p in snapshots}
        if any(captured.get(str(_path(root,p["path"]))) != p["sha256"] for p in final_binding["commitments"]):
            raise ValueError("final artifact changed between declared consumption and snapshot")
    return reg, events, {"event": "cycle", "cycle_id": cycle_id,
        "correction_id": correction_id, "checkpoint": checkpoint, "effective_settings": settings, "receipts": receipts,
        "checks": checks, "inherited_findings": inherited, "snapshots": snapshots,
        **({"final_results": final_binding} if final_binding is not None else {})}


def _findings(root, findings, cycle, policy):
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    pins = {p["path"] for p in cycle["snapshots"]}
    for f in findings:
        _object(f, {"id", "summary", "evidence", "check_ids", "required_paths", "required_stages"}, "finding")
        _ids([f["id"]], "finding id")
        _text(f["summary"], "finding summary")
        _ids(f["check_ids"], "finding check IDs")
        _ids(f["required_stages"], "required stages")
        if not set(f["check_ids"]) <= {c["id"] for c in policy["required_checks"]} or not set(f["required_stages"]) <= set(policy["allowed_stages"]):
            raise ValueError("finding correction scope exceeds declared policy")
        if not isinstance(f["required_paths"], list) or len(set(f["required_paths"])) != len(f["required_paths"]):
            raise ValueError("finding required_paths must be a distinct list")
        if not set(f["required_paths"]) <= set(policy["allowed_changed_paths"]):
            raise ValueError("finding changed paths exceed declared policy")
        if not isinstance(f["evidence"], list) or not f["evidence"]:
            raise ValueError("finding needs located cycle evidence")
        for ref in f["evidence"]:
            _object(ref, {"path", "location"}, "finding evidence")
            _text(ref["location"], "finding location")
            if _pin(root, ref["path"])["path"] not in pins:
                raise ValueError("finding evidence was not bound in its cycle")


def _hold_document(context):
    """Read a bounded exact-byte finding context, including detached validation."""
    from .state_io import _unique
    _object(context, {"path", "sha256", "text"}, "late finding context")
    _text(context["path"], "late finding context path")
    raw = _text(context["text"], "late finding context text").encode("utf-8")
    if len(raw) > MAX_RETAINED_BYTES or hashlib.sha256(raw).hexdigest() != context["sha256"]:
        raise ValueError("late finding context bytes are oversized or changed")
    def invalid(value):
        raise ValueError("nonfinite late finding context: " + value)
    result = json.loads(context["text"], object_pairs_hook=_unique, parse_constant=invalid)
    execution.digest(result)
    return result


def _validate_hold_context(reg, view, context, snapshots):
    document = _hold_document(context)
    _object(document, {"schema_version", "kind", "run_id", "cycle_id", "cycle_sha256", "claim_scope",
                       "accepted_review_sha256", "role", "actor_id", "findings"}, "late finding document")
    if (type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["kind"] != "post_acceptance_scientific_finding"
            or view["state"] != "accepted" or document["run_id"] != reg["run_id"]
            or document["cycle_id"] != view["cycle"]["cycle_id"]
            or document["cycle_sha256"] != view["cycle"]["sha256"]
            or document["claim_scope"] != view["reviews"][0]["claim_scope"]
            or document["accepted_review_sha256"] != [r["sha256"] for r in view["reviews"]]):
        raise ValueError("late finding must bind the exact currently accepted run, cycle, scope and votes")
    if (document["role"] not in ("physics_critic", "skeptical_verifier")
            or document["actor_id"] != reg["policy"]["actors"][document["role"]]):
        raise ValueError("late finding must be owned by a registered independent critic or verifier")
    findings = document["findings"]
    if not isinstance(findings, list) or not findings:
        raise ValueError("scientific hold requires located new findings")
    _ids([f.get("id") for f in findings if isinstance(f, dict)], "late finding IDs")
    old = {p["path"]: p for p in view["cycle"]["snapshots"]}
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("late finding needs frozen evidence snapshots")
    for pin in snapshots:
        _object(pin, {"path", "sha256", "size", "content_retained", "snapshot"}, "late finding snapshot")
        if type(pin["size"]) is not int or pin["size"] <= 0 or type(pin["content_retained"]) is not bool:
            raise ValueError("late finding snapshots must be nonempty exact file commitments")
        if pin["size"] <= MAX_RETAINED_BYTES:
            if pin["content_retained"] is not True or pin["snapshot"] != f"{DIRECTORY}/snapshots/{pin['sha256']}.blob":
                raise ValueError("late finding snapshot omits bounded retained content")
        elif pin["content_retained"] is not False or pin["snapshot"] is not None:
            raise ValueError("invalid unretained late finding commitment")
    pins = {p["path"]: p for p in snapshots}
    if len(pins) != len(snapshots) or context["path"] in old:
        raise ValueError("late finding snapshots must be distinct and context must be new")
    context_pin = pins.get(context["path"])
    if (context_pin is None or context_pin["sha256"] != context["sha256"]
            or context_pin["size"] != len(context["text"].encode("utf-8"))):
        raise ValueError("late finding context lacks its exact frozen evidence pin")
    scope_checks = set(reg["policy"]["claim_scopes"][document["claim_scope"]]["checks"])
    scientific = {c["id"] for c in reg["policy"]["required_checks"] if c["kind"] == "scientific"}
    expected_paths = {context["path"]}
    for finding in findings:
        _object(finding, {"id", "summary", "check_ids", "accepted_evidence", "new_evidence"}, "late finding")
        _text(finding["summary"], "late finding summary")
        checks = set(_ids(finding["check_ids"], "affected late finding checks"))
        if not checks <= scope_checks or not checks.intersection(scientific):
            raise ValueError("late finding must affect a scientific check required by the accepted scope")
        affected = {ref["path"] for c in view["cycle"]["checks"] if c["id"] in checks for ref in c["evidence"]}
        located = False
        for label, available in (("accepted_evidence", old), ("new_evidence", pins)):
            refs = finding[label]
            if not isinstance(refs, list) or not refs:
                raise ValueError("late finding requires located accepted and new evidence")
            for ref in refs:
                _object(ref, {"path", "sha256", "location"}, "late finding evidence")
                _text(ref["location"], "late finding evidence location")
                pin = available.get(ref["path"])
                if pin is None or pin["sha256"] != ref["sha256"] or pin["size"] <= 0:
                    raise ValueError("late finding evidence is missing, empty or unbound")
                if label == "accepted_evidence":
                    located = located or ref["path"] in affected
                else:
                    expected_paths.add(ref["path"])
            if label == "new_evidence" and not any(ref["path"] not in old or old[ref["path"]]["sha256"] != ref["sha256"] for ref in refs):
                raise ValueError("late finding merely replays accepted evidence")
        if not located:
            raise ValueError("late finding does not locate an affected accepted check")
    if set(pins) != expected_paths:
        raise ValueError("late finding snapshots differ from its exact located evidence")
    return document


def submit_hold(root, *, actor_id, cycle_id, claim_scope, summary, finding_context, finding_context_sha256):
    """Append a decider's late-evidence hold without undoing history or granting retries.

    Existing retained review commitments establish authority. Live scientific-file
    drift does not prevent a conservative hold, and cannot confer new acceptance.
    There is deliberately no lift or correction-admission action for this hold.
    """
    root = _root(root)
    with file_lock(root / DIRECTORY / "write.lock"):
        reg, events = _read(root)
        view = _view(reg, events)
        if actor_id != reg["policy"]["actors"]["physics_decider"]:
            raise ValueError("scientific hold requires the registered physics decider")
        if (view["state"] != "accepted" or cycle_id != view["cycle"]["cycle_id"]
                or claim_scope != view["reviews"][0]["claim_scope"]):
            raise ValueError("scientific hold requires the exact currently accepted cycle and scope")
        _text(summary, "scientific hold summary")
        pin = _pin(root, finding_context)
        if pin["sha256"] != finding_context_sha256:
            raise ValueError("late finding context differs from the decider's exact source-bound request")
        source = _path(root, pin["path"])
        if source.stat().st_size > MAX_RETAINED_BYTES:
            raise ValueError("late finding context exceeds retained-document budget")
        context = {**pin, "text": source.read_bytes().decode("utf-8")}
        document = _hold_document(context)
        values = [pin["path"], *[ref["path"] for f in document["findings"] for ref in f["new_evidence"]]]
        values = list(dict.fromkeys(values))
        prepared = []
        for value in values:
            evidence = _pin(root, value)
            size = _path(root, value).stat().st_size
            prepared.append({**evidence, "size": size, "content_retained": size <= MAX_RETAINED_BYTES,
                "snapshot": f"{DIRECTORY}/snapshots/{evidence['sha256']}.blob" if size <= MAX_RETAINED_BYTES else None})
        document = _validate_hold_context(reg, view, context, prepared)
        used = {f["id"] for e in events if e["event"] == "review" for f in e["findings"]}
        if used.intersection(f["id"] for f in document["findings"]):
            raise ValueError("late finding IDs must be globally distinct")
        snapshots = _snapshots(root, values, cycle_id)
        _validate_hold_context(reg, view, context, snapshots)
        return _append(root, reg, events, {"event": "scientific_hold", "cycle_id": cycle_id,
            "claim_scope": claim_scope, "actor_id": actor_id, "summary": summary,
            "finding_context": context, "snapshots": snapshots, "attestation": ATTESTATION})


def _require_supported_closure(cycle):
    """A narrower scope cannot waive a previously recorded blocking defect.

    Initial negative diagnostic outcomes remain eligible for diagnostic scopes.
    Once a check is an inherited repair obligation, its recheck must pass before
    any reviewer can close the finding. A fail/inconclusive is still open.
    """
    checks = {check["id"]: check for check in cycle["checks"]}
    for finding in cycle["inherited_findings"]:
        for check_id in finding["check_ids"]:
            check = checks.get(check_id)
            if check is None or check["status"] != "pass":
                status = check["status"] if check is not None else "missing"
                raise ValueError(f"inherited finding {finding['id']} remains unresolved: recheck {check_id} is {status}")


def _supporting(root, values, *, _session=None):
    """Optional exact role/audit commitments with one final identity census."""
    if not isinstance(values, list) or len(values) > 512:
        raise ValueError("bounded supporting artifact list required")
    owned = _session is None
    session = execution._validation_session(root) if owned else _session
    execution._check_validation_session(root, session)
    try:
        session.track(values)
        pins = []
        for pin in values:
            _support_shape(pin)
            if pin.get("kind") == "role_context":
                pins.append(_context_support(root, pin, session))
                continue
            actual = _pin(root, pin["path"], _session=session)
            if actual["sha256"] != pin["sha256"]:
                raise ValueError("supporting scientific judgment artifact changed")
            pins.append(actual)
        if len({p["path"] for p in pins}) != len(pins):
            raise ValueError("duplicate supporting scientific judgment artifact")
        if owned:
            errors = session.finish()
            if errors: raise ValueError("; ".join(errors))
        return pins
    finally:
        if owned: session.close()


def _judgments_live(root, view, *, _session=None):
    for event in [*view["reviews"], *([view["correction"]] if view["correction"] else [])]:
        _live_pins(root, event.get("supporting_artifacts", []), _session=_session)


def computed_checks(cycle):
    """Fit and scan alarms recomputed from the cycle's retained stage outputs."""
    from ravel.validation import regression_triggers
    outputs = [p for receipt in cycle["receipts"] for p in receipt.get("outputs", [])]
    checks, _, _ = regression_triggers.from_outputs(outputs)
    from ravel.validation.claim_checks.envelope import retained_checks
    return checks + retained_checks(outputs)


def _refuse_computed_failures(reg, cycle, required):
    """A computed failure blocks any claim scope that requires a scientific check.

    Statuses come from the retained records, not from reviewers. An
    integrity-only (diagnostic) scope stays available; a correction cycle whose
    new outputs no longer fail clears the block.
    """
    kinds = {c["id"]: c["kind"] for c in reg["policy"]["required_checks"]}
    if not any(kinds.get(c) == "scientific" for c in required):
        return
    failed = [c for c in computed_checks(cycle) if c["status"] == "fail"]
    if failed:
        listed = "; ".join(f"{c['trigger']} at {Path(c['source']).name}:{c['location']} ({c['detail']})" for c in failed[:5])
        raise ValueError(f"computed check failures block this claim scope: {listed}"
                         + (f" and {len(failed) - 5} more" if len(failed) > 5 else "")
                         + ". Accept a diagnostic scope or send back for a correction.")


def submit_review(root, *, role, actor_id, verdict, summary, findings=None, closes=None,
                  claim_scope=None, supporting_artifacts=None, retained_study=False):
    root = _root(root)
    # Waypoint verdicts gate further compute, not claims; the research record is
    # enforced where a reviewed result is delivered, reused or adopted (gate_errors).
    findings, closes = [] if findings is None else findings, [] if closes is None else closes
    with file_lock(root / DIRECTORY / "write.lock"), ExitStack() as final_observation:
        if type(retained_study) is not bool: raise ValueError("retained_study must be explicit")
        retained_session = None
        if retained_study:
            from .retained_science_review import pending
            retained_session = execution._validation_session(root)
            final_observation.callback(retained_session.close)
            try:
                proof = pending(root, _session=retained_session)
                reg, events = proof["review"]["registration"], proof["review"]["events"]
            except BaseException:
                retained_session.close()
                raise
        else:
            reg, events = _read(root)
            _base_live(root, reg)
        view = _view(reg, events)
        if role not in ROLES or actor_id != reg["policy"]["actors"][role]:
            raise ValueError("review must come from its distinct declared reviewer actor")
        if view["cycle"] is None or view["state"] in ("accepted", "stopped", "correction_admitted", "correction_failed", "scientific_hold"):
            raise ValueError("current cycle cannot receive another review")
        if any(r["role"] == role for r in view["reviews"]):
            raise ValueError("a reviewer cannot overwrite its cycle decision")
        if retained_session is None:
            _live_pins(root, view["cycle"]["snapshots"], allow_empty=_empty_artifact_paths(reg, view["cycle"]))
        _text(summary, "review summary")
        if verdict not in ("accept", "send_back", "stop"):
            raise ValueError("review verdict must be accept, send_back or stop")
        _findings(root, findings, view["cycle"], reg["policy"])
        all_ids = [f["id"] for e in events if e["event"] == "review" for f in e["findings"]]
        new_ids = [f["id"] for f in findings]
        if len(set(new_ids)) != len(new_ids) or set(all_ids) & set(new_ids):
            raise ValueError("finding IDs must be globally distinct")
        _ids(closes, "closed findings", empty=True)
        if verdict == "accept":
            if view["state"] == "send_back" or findings:
                raise ValueError("a rejected cycle cannot be accepted or silently overridden")
            scopes = reg["policy"]["claim_scopes"]
            if claim_scope not in scopes:
                raise ValueError("acceptance needs a prospectively allowed claim scope")
            required = scopes[claim_scope]["checks"]
            by_id = {c["id"]: c for c in view["cycle"]["checks"]}
            if any(by_id[c]["status"] != "pass" for c in required):
                raise ValueError("required checks do not support this claim scope")
            _refuse_computed_failures(reg, view["cycle"], required)
            if set(closes) != {f["id"] for f in view["cycle"]["inherited_findings"]}:
                raise ValueError("acceptance must explicitly close every inherited finding")
            _require_supported_closure(view["cycle"])
            other = next((r for r in view["reviews"] if r["verdict"] == "accept"), None)
            if other and other["claim_scope"] != claim_scope:
                raise ValueError("all reviewers must accept the same claim scope")
        elif closes or claim_scope is not None:
            raise ValueError("only acceptance may close findings or claim a scope")
        if verdict == "send_back" and not findings:
            raise ValueError("send_back requires explicit located correction findings")
        if retained_session is None:
            _judgments_live(root, view)
        support = (_supporting(root, supporting_artifacts, _session=retained_session)
                   if supporting_artifacts is not None else None)
        if retained_session is not None:
            errors = retained_session.finish()
            if errors: raise ValueError("retained study changed before review: " + "; ".join(errors))
        return _append(root, reg, events, {"event": "review", "cycle_id": view["cycle"]["cycle_id"],
            "role": role, "actor_id": actor_id, "verdict": verdict, "summary": summary,
            "findings": findings, "closes": closes, "claim_scope": claim_scope, "attestation": ATTESTATION,
            **({"supporting_artifacts": support} if support is not None else {})})


def _stage_spec(root, spec):
    required = {"stage", "command", "cwd", "inputs", "outputs", "depends_on", "log"}
    if isinstance(spec, dict) and 'output_policy' in spec:
        required.add('output_policy')
    if isinstance(spec,dict) and 'helper_declaration' in spec:required.add('helper_declaration')
    _object(spec, required, "correction stage specification")
    _ids([spec["stage"]], "correction stage")
    if not isinstance(spec["command"], list) or not spec["command"] or any(not isinstance(v, str) or not v for v in spec["command"]):
        raise ValueError("correction command must be a nonempty argument list")
    _ids(spec["depends_on"], "correction parents", empty=True)
    _text(spec["log"], "correction stage log")
    normalized = {"stage": spec["stage"], "command": list(spec["command"]), "log": str(execution.log_path(root, spec["log"])),
                  "cwd": str(Path(spec["cwd"]).resolve()), "depends_on": list(spec["depends_on"])}
    for name in ("inputs", "outputs"):
        values = spec[name]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
            raise ValueError("correction stage needs explicit nonempty inputs and outputs")
        resolved = [str(execution.resolve_path(root, v, output=name == "outputs")) for v in values]
        if len(set(resolved)) != len(resolved):
            raise ValueError("duplicate correction stage artifact")
        normalized[name] = sorted(resolved)
    if 'output_policy' in spec:
        execution.validate_output_policy(root, spec['outputs'], spec['output_policy'], execution.resolve_path)
        from copy import deepcopy
        normalized['output_policy'] = deepcopy(spec['output_policy'])
    normalized.update(execution.helper_declaration_fields(spec))
    return normalized


def correction_execution_errors(root, stage, command, inputs, outputs, depends_on, cwd, log=None, *, helper_declaration=None, _session=None):
    """Compare a requested supervised command and IO to the exact admitted specification."""
    if _session is not None:
        execution._check_validation_session(root, _session)
        _session.proofs[("readonly-correction-gate",)] = True
    errors = gate_errors(root, "correction", stage,
                        **({} if _session is None else {"_session": _session}))
    if errors:
        return errors
    try:
        root = _root(root)
        reg, events = _read(root, **({} if _session is None else {"_session": _session}))
        admitted = _view(reg, events)["correction"]
        actual = _stage_spec(root, {"stage": stage, "command": list(command), "inputs": list(inputs),
            "outputs": list(outputs), "depends_on": list(depends_on), "cwd": str(cwd), "log": log,
            **({"helper_declaration":helper_declaration} if helper_declaration is not None else {})})
        expected = next(s for s in admitted["stage_specs"] if s["stage"] == stage)
        if actual != expected:
            raise ValueError("correction command, cwd, inputs, outputs, log or dependencies differ from admission")
        return []
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        return [str(exc)]


def _held_paths(reg, events, settings, changed_paths):
    """Carry an inherited repair only at the exact bytes admitted for that finding.

    This discharges a mutation obligation, never its execution or review obligations.
    New findings cannot borrow a previous repair of the same filename.
    """
    view = _view(reg, events)
    inherited = {f["id"] for f in view["cycle"]["inherited_findings"]}
    before = {p["path"]: p["sha256"] for p in view["cycle"]["effective_settings"]}
    proposed = {p["path"]: p["sha256"] for p in settings}
    held = []
    for finding in view["findings"]:
        for path in sorted(set(finding["required_paths"]) - set(changed_paths)):
            if finding["id"] not in inherited or proposed.get(path) != before.get(path):
                raise ValueError("correction omits a mandatory finding obligation")
            source = None
            for index in range(len(events) - 1, -1, -1):
                candidate = events[index]
                if candidate["event"] != "correction" or path not in candidate["changed_paths"]:
                    continue
                prior_findings = _view(reg, events[:index])["findings"]
                pin = next((p for p in candidate["effective_settings"] if p["path"] == path), None)
                if (any(f["id"] == finding["id"] and path in f["required_paths"] for f in prior_findings)
                        and pin is not None and pin["sha256"] == proposed.get(path)):
                    source = candidate
                    break
            if source is None:
                raise ValueError("inherited required path lacks an exact prior admitted repair")
            held.append({"finding_id": finding["id"], "path": path, "sha256": proposed[path],
                         "correction_id": source["correction_id"]})
    return held


def authorize_correction(root, *, actor_id, changed_paths, stages, recheck_checks, stage_specs=None, supporting_artifacts=None):
    """Admit exact prepared correction bytes; admission consumes a redo, even on failure."""
    root = _root(root)
    with file_lock(root / DIRECTORY / "write.lock"):
        reg, events = _read(root)
        amended = _base_live(root, reg)
        view = _view(reg, events)
        if actor_id != reg["policy"]["actors"]["physics_decider"] or view["state"] not in ("send_back", "correction_failed"):
            raise ValueError("only the physics decider may admit a correction to rejected work")
        if view["redos_remaining"] <= 0:
            raise ValueError("review redo budget exhausted")
        _ids(stages, "correction stages")
        _ids(recheck_checks, "recheck checks")
        if not isinstance(changed_paths, list) or len(set(changed_paths)) != len(changed_paths):
            raise ValueError("changed_paths must be a distinct list")
        if not set(changed_paths) <= set(reg["policy"]["allowed_changed_paths"]) or not set(stages) <= set(reg["policy"]["allowed_stages"]):
            raise ValueError("correction exceeds approved path/stage policy")
        if not set(recheck_checks) <= {c["id"] for c in reg["policy"]["required_checks"]}:
            raise ValueError("correction uses undeclared checks")
        for f in view["findings"]:
            if not set(f["required_stages"]) <= set(stages) or not set(f["check_ids"]) <= set(recheck_checks):
                raise ValueError("correction omits a mandatory finding obligation")
        old = view["cycle"]
        settings = [_pin(root, s["path"]) for s in old["effective_settings"]]
        setting_paths = {s["path"] for s in settings}
        if not set(changed_paths) <= setting_paths:
            raise ValueError("changed paths must be actual effective settings bound in the rejected cycle")
        changed = {new["path"] for before, new in zip(old["effective_settings"], settings) if before != new}
        if changed != set(changed_paths):
            raise ValueError("declared correction paths must exactly match prepared setting changes")
        old_pins = {p["path"]: p for p in old["snapshots"]}
        # An amendment re-approval since the rejected cycle admits only this correction's
        # own changed settings; its new approval document replaces that cycle's approval pin.
        approval_path = reg["bindings"][-1]["path"]
        reapproved = set()
        cycle_approval = old_pins.get(approval_path)
        if approval_path in amended and (cycle_approval is None or cycle_approval["sha256"] != _pin(root, approval_path)["sha256"]):
            since = cycle_approval and _amendment_names(read_json(_path(root, approval_path)), cycle_approval["sha256"])
            if since is None:
                raise ValueError("CHECK-IN 1 approval changed after the rejected cycle without an amendment re-approval of it")
            if not since <= set(changed_paths):
                raise ValueError("amendment re-approval names inputs outside this correction's changed paths: "
                                 + ", ".join(sorted(str(p) for p in since - set(changed_paths))))
            reapproved = {approval_path}
        held_paths = _held_paths(reg, events, settings, changed_paths)
        scientific_inputs = {p for r in old["receipts"] for p in r["inputs"]} | setting_paths
        if stage_specs is None:
            old_records = {r["stage"]: read_json(_path(root, r["path"])) for r in old["receipts"]}
            if not set(stages) <= set(old_records):
                raise ValueError("new correction stages require explicit stage_specs")
            stage_specs = [{"stage": name, **{key: old_records[name][key] for key in ("command", "cwd", "inputs", "outputs", "log")},
                            "depends_on": list(old_records[name]["parents"])} for name in stages]
        if not isinstance(stage_specs, list):
            raise ValueError("stage_specs must be a list")
        specs = [_stage_spec(root, spec) for spec in stage_specs]
        if len(specs) != len(stages) or {spec["stage"] for spec in specs} != set(stages):
            raise ValueError("stage_specs must cover each admitted stage exactly once")
        by_stage = {spec["stage"]: spec for spec in specs}
        def ancestors(name, visiting=None):
            visiting = set() if visiting is None else set(visiting)
            if name in visiting:
                raise ValueError("correction stage dependency cycle")
            visiting.add(name)
            parents = by_stage[name]["depends_on"]
            return set(parents) | {a for parent in parents if parent in by_stage for a in ancestors(parent, visiting)}
        generated = []
        for spec in specs:
            parents = ancestors(spec["stage"])
            for value in spec["inputs"]:
                path = Path(value)
                producers = [other["stage"] for other in specs if path == Path(other["log"]) or any(path == Path(out) or path.is_relative_to(Path(out)) for out in other["outputs"])]
                if producers:
                    if len(producers) != 1 or producers[0] not in parents:
                        raise ValueError("regenerated correction input needs one declared predecessor producer")
                    generated.append({"path": _identity(root, path), "producer": producers[0], "consumer": spec["stage"]})
        regenerated_paths = {p["path"] for p in generated}
        proposed_inputs = {_identity(root, execution.resolve_path(root, p)) for spec in specs for p in spec["inputs"]}
        if not proposed_inputs <= scientific_inputs | regenerated_paths:
            raise ValueError("correction introduces scientific inputs outside the reviewed cycle: "
                             + ", ".join(sorted(proposed_inputs - scientific_inputs - regenerated_paths)))
        scientific_inputs |= proposed_inputs
        held_fixed = scientific_inputs - regenerated_paths
        for p in held_fixed - set(changed_paths) - reapproved:
            if p in old_pins:
                _live_pins(root, [old_pins[p]], allow_empty=_empty_artifact_paths(reg, old))
        if setting_paths & regenerated_paths:
            raise ValueError("effective setting bytes cannot be regenerated under the same admission")
        correction_id = uuid.uuid4().hex
        snapshots = _snapshots(root, sorted(held_fixed), "correction-" + correction_id,
                               allow_empty=_empty_artifact_paths(reg, old))
        _judgments_live(root, view)
        support = _supporting(root, supporting_artifacts) if supporting_artifacts is not None else None
        return _append(root, reg, events, {"event": "correction", "cycle_id": old["cycle_id"],
            "correction_id": correction_id, "actor_id": actor_id, "changed_paths": changed_paths, "held_paths": held_paths,
            "stages": stages, "recheck_checks": recheck_checks, "effective_settings": settings,
            "stage_specs": specs, "regenerated_inputs": generated, "snapshots": snapshots, "redo_number": view["redos_used"] + 1,
            **({"supporting_artifacts": support} if support is not None else {})})


def current_correction(root):
    """Authenticate the current amendment without evaluating unrelated stage readiness.

    No review or a valid non-correction state returns None. Corrupt review state,
    stale registered inputs and scientific holds refuse. This is an inspection
    only: callers must still pass the separate, fresh launch-specific gates.
    No journal, receipt or input proof survives this call.
    """
    root = _root(root)
    controls = (root / REGISTRATION, root / HEAD, root / DIRECTORY, root / DIRECTORY / "events")
    if any(path.is_symlink() for path in controls):
        raise ValueError("review control path is a symlink; no correction fallback is permitted")
    if not registered(root):
        return None
    reg, events = _read(root)
    _base_live(root, reg)
    view = _view(reg, events)
    if view["state"] == "scientific_hold":
        raise ValueError("scientific hold blocks current correction inspection; no lift or retry authority is granted")
    if view["state"] != "correction_admitted":
        return None
    _live_pins(root, view["correction"]["snapshots"], allow_empty=_empty_artifact_paths(reg, view["cycle"]))
    return view["correction"]


def admitted_correction(root):
    """Inspect the exact current amendment; this does not authorize a particular launch."""
    correction = current_correction(root)
    if correction is None:
        raise ValueError("no current admitted correction")
    return correction


def fail_correction(root, *, correction_id, reason):
    root = _root(root)
    with file_lock(root / DIRECTORY / "write.lock"):
        reg, events = _read(root)
        view = _view(reg, events)
        if view["state"] != "correction_admitted" or view["correction"]["correction_id"] != correction_id:
            raise ValueError("no matching admitted correction to fail")
        _text(reason, "failure reason")
        return _append(root, reg, events, {"event": "correction_failed", "correction_id": correction_id, "reason": reason})


def _correction_ready(root, view, stage, *, _session=None):
    correction = view["correction"]
    state = execution.load_execution(root)
    if _session is not None:
        execution._check_validation_session(root, _session)
        _session.track(state)
        _session.track(view)
    current = state["stages"]
    old = {r["stage"]: r["attempt_id"] for r in view["cycle"]["receipts"]}
    if (current.get(stage, {}).get("status") == "succeeded"
            and current[stage].get("attempt_id") != old.get(stage)):
        raise ValueError("this admitted correction stage already succeeded; open its successor review instead of rerunning")
    bindings = [b for b in correction["regenerated_inputs"] if b["consumer"] == stage]
    if not bindings:
        return
    # Several regenerated files can belong to one predecessor. Authenticate its
    # receipt and transitive custody once in this call, then check every binding.
    # The final census is required before returning; no proof survives a launch,
    # ledger update or subsequent readiness check.
    owned = _session is None
    session = None
    try:
        session = execution._validation_session(root, state, view) if owned else _session
        verified = {}
        for binding in bindings:
            producer = binding["producer"]
            record = current.get(producer, {})
            if record.get("status") != "succeeded" or record.get("attempt_id") == old.get(producer):
                raise ValueError("downstream correction needs a fresh successful predecessor")
            if producer not in verified:
                _receipt(root, record["attempt_record"], _session=session)
                actual = _stage_spec(root, {"stage": producer, **{k: record[k] for k in ("command", "cwd", "inputs", "outputs", "log")},
                                           "depends_on": list(record["parents"])})
                if actual != next(s for s in correction["stage_specs"] if s["stage"] == producer):
                    raise ValueError("regenerated predecessor did not execute its admitted specification")
                verified[producer] = actual
            actual = verified[producer]
            if execution.resolve_path(root, binding["path"]) == Path(actual["log"]):
                if record.get("log_snapshot") != session.snapshot([actual["log"]]):
                    raise ValueError("regenerated predecessor log lacks its matching successful receipt commitment")
        if owned:
            errors = session.finish()
            if errors:
                raise ValueError("correction predecessor validation refused: " + "; ".join(errors))
    finally:
        if owned and session is not None:
            session.close()


def gate_errors(root, action, stage=None, *, _session=None, retained_study=False):
    """Actions: bulk, scoped delivery, reuse, correction, final_task delivery.

    final_task additionally checks original obligations at this parent review;
    it grants no computation or broader scientific claim than the existing gate.
    """
    from .research_admission import admission
    protocol_errors = admission(root, action)
    if protocol_errors: return protocol_errors
    if type(retained_study) is not bool:
        return ['retained_study must be explicit']
    if retained_study:
        try:
            from .retained_science_review import observe
            observe(root, action=action, stage=stage, _session=_session)
            if action is None:
                raise ValueError('retained delivery/reuse action is required')
            return []
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return [str(exc)]
    if _session is not None:
        execution._check_validation_session(root, _session)
    try:
        root = _root(root)
        reg, events = _read(root, _session=_session)
        _base_live(root, reg, _session=_session)
        view = _view(reg, events)
        _judgments_live(root, view, _session=_session)
        if view["state"] == "scientific_hold":
            raise ValueError(f"scientific hold blocks {action} for accepted claim {view['holds'][-1]['claim_scope']}; no lift or retry authority is granted")
        if action == "correction":
            if view["state"] != "correction_admitted" or stage not in view["correction"]["stages"]:
                raise ValueError("action is outside an admitted correction stage")
            _live_pins(root, view["correction"]["snapshots"], allow_empty=_empty_artifact_paths(reg, view["cycle"]), _session=_session)
            _correction_ready(root, view, stage,
                              **({"_session": _session} if _session is not None
                                 and _session.proofs.get(("readonly-correction-gate",)) is True else {}))
        elif action in ("bulk", "delivery", "reuse", "final_task"):
            if view["state"] != "accepted":
                raise ValueError(f"scientific review is {view['state']}; acceptance by all three reviewers is required")
            scope = view["reviews"][0]["claim_scope"]
            authorized_action = "delivery" if action == "final_task" else action
            if authorized_action not in reg["policy"]["claim_scopes"][scope]["actions"]:
                raise ValueError(f"accepted claim scope {scope} does not authorize {action}")
            _live_pins(root, view["cycle"]["snapshots"], allow_empty=_empty_artifact_paths(reg, view["cycle"]), _session=_session)
            if action == "final_task":
                from . import task_completion
                task_completion.final_gate(root)
        else:
            raise ValueError("unknown physics review gate action")
        return []
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return [str(exc)]


def status(root, *, _session=None, retained_study=False):
    """Read historical decisions even if current scientific files changed; report live errors separately."""
    if type(retained_study) is not bool:
        return {'schema_version':1, 'state':'invalid', 'errors':['retained_study must be explicit'], 'attestation':ATTESTATION}
    if retained_study:
        from .retained_science_review import review_status
        return review_status(root, _session=_session)
    if _session is not None:
        execution._check_validation_session(root, _session)
    try:
        root = _root(root)
        reg, events = _read(root, _session=_session)
        view = _view(reg, events)
        next_stage, completed = None, []
        if view["state"] == "correction_admitted":
            records = execution.load_execution(root)["stages"]
            old = {r["stage"]: r["attempt_id"] for r in view["cycle"]["receipts"]}
            completed = [s for s in view["correction"]["stages"] if records.get(s, {}).get("status") == "succeeded"
                         and records[s].get("attempt_id") != old.get(s)]
            pending = [s for s in view["correction"]["stages"] if s not in completed]
            next_stage = next((s for s in pending if not gate_errors(root, "correction", s, _session=_session)), pending[0] if pending else None)
            try:
                admitted_correction(root)
                live_errors = gate_errors(root, "correction", next_stage, _session=_session) if next_stage else []
            except (OSError, ValueError, KeyError, TypeError) as exc:
                live_errors = [str(exc)]
        else:
            live_errors = gate_errors(root, "delivery", _session=_session)
        return {"schema_version": 1, "state": view["state"],
            "cycle_id": view["cycle"]["cycle_id"] if view["cycle"] else None,
            "correction_id": view["correction"]["correction_id"] if view["correction"] else None,
            "claim_scope": view["reviews"][0]["claim_scope"] if view["state"] == "accepted" else None,
            "held_claim_scope": view["holds"][-1]["claim_scope"] if view["holds"] else None,
            "scientific_hold_sha256": view["holds"][-1]["sha256"] if view["holds"] else None,
            "unresolved_findings": view["findings"], "redos_used": view["redos_used"],
            "redos_remaining": view["redos_remaining"], "events": len(events),
            "live_errors": live_errors, "next_correction_stage": next_stage,
            "completed_correction_stages": completed,
            "correction_stages": view["correction"]["stages"] if view["correction"] else [],
            "attestation": ATTESTATION}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"schema_version": 1, "state": "invalid", "errors": [str(exc)], "attestation": ATTESTATION}


def bound_paths(root):
    """All current review commitments for launch snapshots; caller separately checks action admission."""
    root = _root(root)
    reg, events = _read(root)
    view = _view(reg, events)
    if view["cycle"] is None:
        raise ValueError("review has no cycle")
    approval, _, _ = _approval_envelope(root)
    paths = [POLICY, approval, REGISTRATION, HEAD]
    paths += [f"{DIRECTORY}/events/{e['sequence']:08d}.json" for e in events]
    paths += [p["snapshot"] for e in events for p in e.get("snapshots", []) if p.get("snapshot")]
    paths += [p["path"] for e in [*view["reviews"], *([view["correction"]] if view["correction"] else [])]
              for p in e.get("supporting_artifacts", [])]
    context_empty = set()
    for event in [*view["reviews"], *([view["correction"]] if view["correction"] else [])]:
        for pin in event.get("supporting_artifacts", []):
            if pin.get("kind") != "role_context": continue
            from . import review_context
            # Fresh complete verification precedes exposing the copied members.
            _live_pins(root, [pin])
            manifest = review_context.verify_packet(_path(root, pin["path"]).parent,
                expected_manifest_sha256=pin["manifest_sha256"])
            for entry in manifest["artifacts"]:
                value = str(_path(root, pin["path"]).parent / entry["path"])
                paths.append(value)
                if entry["sha256"] == hashlib.sha256(b"").hexdigest(): context_empty.add(value)
    current = view["correction"] if view["state"] == "correction_admitted" else view["cycle"]
    paths += [p["path"] for p in current["snapshots"]]
    paths += [p["path"] for hold in view["holds"] for p in hold["snapshots"]]
    empty_paths = _empty_artifact_paths(reg, view["cycle"]) | context_empty
    empty_paths.update(p["snapshot"] for e in events for p in e.get("snapshots", [])
                       if p["size"] == 0)
    return list(dict.fromkeys(str(_path(root, p, allow_empty=p in empty_paths)) for p in paths))


def registered(root):
    """Presence detection is deliberately broader than validity; corrupted state stays gated."""
    p = Path(root)
    return (p / REGISTRATION).exists() or (p / HEAD).exists() or bool(list((p / DIRECTORY / "events").glob("*.json")))


def active(root, *, _session=None):
    """Any recorded or corrupt cycle activates enforcement; absence permits initial smoke."""
    if _session is not None:
        execution._check_validation_session(root, _session)
    if not registered(root):
        return False
    try:
        reg, events = _read(_root(root), _session=_session)
        _base_live(_root(root), reg, _session=_session)
        return bool(events)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return True


def snapshot(root, *, action="bulk", stage=None, retained_study=False):
    """Detached authorization facts. Scientific file contents remain separately hash-bound."""
    if type(retained_study) is not bool:
        raise ValueError('retained_study must be explicit')
    if retained_study:
        from .retained_science_review import observe
        if action is None:
            raise ValueError('retained delivery/reuse action is required')
        return observe(root, action=action, stage=stage)['review']
    root = _root(root)
    errors = gate_errors(root, action, stage)
    if errors:
        raise ValueError("cannot snapshot inadmissible review: " + "; ".join(errors))
    reg, events = _read(root)
    result = {"schema_version": 1, "registration": reg, "events": events,
              "checkpoint": read_json(root / HEAD), "action": action, "stage": stage}
    errors = validate_snapshot(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def validate_snapshot(document, *, require_admission=True):
    """Validate detached role decisions and correction authority without consulting live files.

    A caller binds these bytes to its launch receipt. This validates local provenance
    and declared separation, not actor authentication or scientific truth.
    """
    try:
        _object(document, {"schema_version", "registration", "events", "checkpoint", "action", "stage"}, "review snapshot")
        if type(document["schema_version"]) is not int or document["schema_version"] != 1:
            raise ValueError("invalid review snapshot version")
        reg, events, head = document["registration"], document["events"], document["checkpoint"]
        _object(reg, {"schema_version", "run_id", "policy", "bindings", "attestation", "sha256"}, "registration")
        if reg["sha256"] != execution.digest({k: v for k, v in reg.items() if k != "sha256"}) or validate_policy(reg["policy"]):
            raise ValueError("invalid frozen review registration")
        if not isinstance(events, list) or not events:
            raise ValueError("review snapshot has no journal")
        prior, seen, finding_ids = reg["sha256"], [], set()
        base_keys = {"schema_version", "sequence", "previous_sha256", "run_id", "utc", "sha256", "event"}
        fields = {
            "cycle": {"cycle_id", "correction_id", "checkpoint", "effective_settings", "receipts", "checks", "inherited_findings", "snapshots"},
            "review": {"cycle_id", "role", "actor_id", "verdict", "summary", "findings", "closes", "claim_scope", "attestation"},
            "correction": {"cycle_id", "correction_id", "actor_id", "changed_paths", "held_paths", "stages", "recheck_checks", "effective_settings", "stage_specs", "regenerated_inputs", "snapshots", "redo_number"},
            "correction_failed": {"correction_id", "reason"},
            "scientific_hold": {"cycle_id", "claim_scope", "actor_id", "summary", "finding_context", "snapshots", "attestation"}}
        for n, e in enumerate(events, 1):
            kind = e.get("event") if isinstance(e, dict) else None
            if kind not in fields:
                raise ValueError("unknown review journal event")
            _object(e, base_keys | fields[kind] | ({"final_results"} if kind == "cycle" and "final_results" in e else set()) | ({"supporting_artifacts"} if kind in {"review", "correction"} and "supporting_artifacts" in e else set()), "review journal event")
            if "supporting_artifacts" in e:
                pins = e["supporting_artifacts"]
                if not isinstance(pins, list) or len(pins) > 512 or len({p.get("path") for p in pins}) != len(pins):
                    raise ValueError("invalid supporting judgment artifact list")
                for pin in pins:
                    _support_shape(pin)
            if (type(e["schema_version"]) is not int or e["schema_version"] != 1
                    or type(e["sequence"]) is not int or e["sequence"] != n
                    or e["run_id"] != reg["run_id"] or e["previous_sha256"] != prior
                    or e["sha256"] != execution.digest({k: v for k, v in e.items() if k != "sha256"})):
                raise ValueError("detached review journal chain changed")
            from .launch_authorization import parse_utc
            stamp = parse_utc(e["utc"])
            if seen and stamp < parse_utc(seen[-1]["utc"]):
                raise ValueError("review journal clock moved backwards")
            view = _view(reg, seen)
            if kind == "cycle":
                _ids([e["cycle_id"]], "cycle identity")
                if e["cycle_id"] in {x["cycle_id"] for x in seen if x["event"] == "cycle"}:
                    raise ValueError("duplicate cycle identity")
                if type(e["checkpoint"]) is not bool:
                    raise ValueError("invalid checkpoint flag")
                if 'final_results' in e:
                    f=e['final_results']
                    _object(f, {'manifest','source_cycle_id','source_cycle_sha256','commitments'}, 'final result binding')
                    if (not e['checkpoint'] or not view['cycle'] or f['source_cycle_id']!=view['cycle']['cycle_id']
                            or f['source_cycle_sha256']!=view['cycle']['sha256'] or e['receipts']!=view['cycle']['receipts']):
                        raise ValueError('final checkpoint dropped its exact accepted predecessor')
                    if type(f['commitments']) is not list or not f['commitments']:raise ValueError('final checkpoint lacks artifact commitments')
                    committed={(x['path'],x['sha256']) for x in e['snapshots']}
                    for pin in [f['manifest'],*f['commitments']]:
                        _object(pin, {'path','sha256'}, 'final commitment')
                        matches=[x for x in e['snapshots'] if x['sha256']==pin['sha256'] and x['path']==pin['path']]
                        if not matches:raise ValueError('final result commitment outside captured cycle')
                if e["checkpoint"]:
                    if (view["state"] != "accepted" or e["correction_id"] is not None or e["inherited_findings"]
                            or e["effective_settings"] != view["cycle"]["effective_settings"]
                            or ("final_results" not in e and not ({r["attempt_id"] for r in e["receipts"]} - {r["attempt_id"] for r in view["cycle"]["receipts"]}))):
                        raise ValueError("checkpoint lacks accepted predecessor, fixed settings or fresh execution")
                elif view["cycle"]:
                    if (view["state"] != "correction_admitted" or e["correction_id"] != view["correction"]["correction_id"]
                            or e["inherited_findings"] != view["findings"]
                            or e["effective_settings"] != view["correction"]["effective_settings"]):
                        raise ValueError("successor dropped obligations or correction binding")
                elif e["correction_id"] is not None or e["inherited_findings"]:
                    raise ValueError("initial cycle falsely claims prior correction")
                ids = [c["id"] for c in e["checks"]]
                if len(ids) != len(set(ids)) or set(ids) != {c["id"] for c in reg["policy"]["required_checks"]}:
                    raise ValueError("cycle omits declared checks")
                for check in e["checks"]:
                    _object(check, {"id", "status", "evidence", "attempt_ids"}, "frozen check")
                    if check["status"] not in ("pass", "fail", "inconclusive") or not check["evidence"] or not check["attempt_ids"]:
                        raise ValueError("invalid frozen check evidence")
                if not e["effective_settings"] or not e["receipts"] or not e["snapshots"]:
                    raise ValueError("cycle omits actual execution evidence")
                for pin in e["snapshots"]:
                    if pin.get("content_retained") is True and pin.get("size", 0) > MAX_RETAINED_BYTES and not _large_proof_document_allowed(pin, reg, e):
                        raise ValueError("large retained evidence is not an exact approved raw proof document")
                    if pin.get("size") == 0 and not _empty_snapshot_allowed(pin, reg, e):
                        raise ValueError("empty review evidence is not a bound input")
            elif kind == "review":
                if (not view["cycle"] or e["cycle_id"] != view["cycle"]["cycle_id"]
                        or view["state"] not in ("awaiting_review", "send_back")
                        or e["role"] not in ROLES or e["actor_id"] != reg["policy"]["actors"][e["role"]]
                        or any(r["role"] == e["role"] for r in view["reviews"])):
                    raise ValueError("invalid reviewer role, identity or cycle transition")
                _text(e["summary"], "review summary")
                if e["verdict"] == "accept":
                    scopes = reg["policy"]["claim_scopes"]
                    if (view["state"] == "send_back" or e["findings"] or e["claim_scope"] not in scopes
                            or set(e["closes"]) != {f["id"] for f in view["cycle"]["inherited_findings"]}
                            or any(r["verdict"] == "accept" and r["claim_scope"] != e["claim_scope"] for r in view["reviews"])):
                        raise ValueError("acceptance overrides rejection, closure or claim scope")
                    checks = {c["id"]: c for c in view["cycle"]["checks"]}
                    if any(checks[c]["status"] != "pass" for c in scopes[e["claim_scope"]]["checks"]):
                        raise ValueError("accepted claim has a failed required check")
                    _require_supported_closure(view["cycle"])
                elif e["verdict"] not in ("send_back", "stop") or e["closes"] or e["claim_scope"] is not None:
                    raise ValueError("invalid review verdict")
                if e["verdict"] == "send_back" and not e["findings"]:
                    raise ValueError("rejection has no correction obligations")
                for f in e["findings"]:
                    _object(f, {"id", "summary", "evidence", "check_ids", "required_paths", "required_stages"}, "frozen finding")
                    if f["id"] in finding_ids or not f["evidence"] or not f["check_ids"] or not f["required_stages"]:
                        raise ValueError("invalid or duplicate finding")
                    finding_ids.add(f["id"])
            elif kind == "scientific_hold":
                if (view["state"] != "accepted"
                        or e["actor_id"] != reg["policy"]["actors"]["physics_decider"]
                        or not view["cycle"] or e["cycle_id"] != view["cycle"]["cycle_id"]
                        or e["claim_scope"] != view["reviews"][0]["claim_scope"]
                        or e["attestation"] != ATTESTATION):
                    raise ValueError("invalid scientific hold authority, scope or cycle")
                _text(e["summary"], "scientific hold summary")
                context = _validate_hold_context(reg, view, e["finding_context"], e["snapshots"])
                ids = {f["id"] for f in context["findings"]}
                if ids.intersection(finding_ids):
                    raise ValueError("duplicate late finding identity")
                finding_ids.update(ids)
            elif kind == "correction":
                if (view["state"] not in ("send_back", "correction_failed")
                        or e["cycle_id"] != view["cycle"]["cycle_id"]
                        or e["actor_id"] != reg["policy"]["actors"]["physics_decider"]
                        or view["redos_remaining"] <= 0 or e["redo_number"] != view["redos_used"] + 1
                        or not set(e["changed_paths"]) <= set(reg["policy"]["allowed_changed_paths"])
                        or not set(e["stages"]) <= set(reg["policy"]["allowed_stages"])):
                    raise ValueError("correction exceeds reviewer authority or redo budget")
                old_settings = {p["path"]: p["sha256"] for p in view["cycle"]["effective_settings"]}
                new_settings = {p["path"]: p["sha256"] for p in e["effective_settings"]}
                if (set(old_settings) != set(new_settings)
                        or {p for p in old_settings if old_settings[p] != new_settings[p]} != set(e["changed_paths"])
                        or e["held_paths"] != _held_paths(reg, seen, e["effective_settings"], e["changed_paths"])):
                    raise ValueError("correction changed settings or inherited repair commitment")
                for f in view["findings"]:
                    if (not set(f["required_stages"]) <= set(e["stages"])
                            or not set(f["check_ids"]) <= set(e["recheck_checks"])):
                        raise ValueError("correction dropped a mandatory obligation")
                for pin in e["snapshots"]:
                    if pin.get("size") == 0 and not _empty_snapshot_allowed(pin, reg, view["cycle"]):
                        raise ValueError("empty review evidence is not a bound input")
            elif view["state"] != "correction_admitted" or e["correction_id"] != view["correction"]["correction_id"]:
                raise ValueError("failure has no admitted correction")
            prior = e["sha256"]
            seen.append(e)
        if head != {"sequence": len(events), "sha256": prior}:
            raise ValueError("detached review checkpoint changed")
        view = _view(reg, events)
        if require_admission:
            if document["action"] == "correction":
                if view["state"] != "correction_admitted" or document["stage"] not in view["correction"]["stages"]:
                    raise ValueError("snapshot does not authorize this correction")
            elif document["action"] not in ("bulk", "delivery", "reuse") or view["state"] != "accepted":
                raise ValueError("snapshot is not accepted for this action")
            elif document["action"] not in reg["policy"]["claim_scopes"][view["reviews"][0]["claim_scope"]]["actions"]:
                raise ValueError("accepted scope does not authorize the recorded action")
        return []
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return [str(exc)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rundir", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("open", "review", "correct", "fail", "hold"):
        p = sub.add_parser(action)
        p.add_argument("--request", required=True, help="Strict JSON keyword arguments for the corresponding API")
    p = sub.add_parser("status")
    p.add_argument("--retained-study", action="store_true", help="inspect an immutable initial study without regenerating its input inventory")
    p = sub.add_parser("gate")
    p.add_argument("--action", required=True, dest="gate_action")
    p.add_argument("--stage")
    p.add_argument("--retained-study", action="store_true", help="check only original scoped delivery/reuse under immutable initial-study commitments")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            result = status(args.rundir, retained_study=args.retained_study)
        elif args.action == "gate":
            result = {"errors": gate_errors(args.rundir, args.gate_action, args.stage, retained_study=args.retained_study)}
        else:
            fn = {"open": open_cycle, "review": submit_review, "correct": authorize_correction, "fail": fail_correction, "hold": submit_hold}[args.action]
            result = fn(args.rundir, **read_json(args.request))
        print(json.dumps(result, indent=2, allow_nan=False))
        return 1 if result.get("errors") or result.get("state") == "invalid" else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(1, f"physics review: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
