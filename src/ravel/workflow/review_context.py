"""Role-specific, immutable evidence packets for scientific review.

The packet reader exposes only indexed copies. This is a data-access boundary for
that reader, not an OS sandbox: an orchestrator must withhold unrestricted tools
and the parent conversation to enforce reviewer blinding.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re

from . import execution, physics_review
from .state_io import read_json, _unique
from .validation_io import ValidationSession, identity

ROLES = ("critic", "improver", "verifier", "synthesizer")
EXCLUDED = {"result.md", "result.json", "verification.json", "checkin2_go.json"}
SCIENCE_PRIVATE_INPUTS = {"inputs/science.json", "inputs/science-plan.json", "inputs/science-approval.json"}
LIMITATION = ("Only the packet reader is restricted. Blinding requires a fresh agent with "
              "no parent transcript, unrestricted filesystem, shell or other reviewers' outputs. "
              "Known verdict fields are projected; review-journal custody and explicit review records are omitted. "
              "arbitrary scientific artifacts may still carry narrative and prior context is not erased. "
              "Retain the creation manifest digest outside this packet; local hashes do not authenticate actors.")


def _safe_path(value):
    raw = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (raw, *raw.parents)):
        raise ValueError("review context paths cannot traverse symlinks")
    return raw.resolve()


def _frozen_bytes(root, pin, *, _session=None):
    path = _safe_path(root / pin["snapshot"])
    if not path.is_relative_to(root / physics_review.DIRECTORY / "snapshots") or not path.is_file():
        raise ValueError("frozen context artifact escapes review custody")
    content = (path.read_bytes() if _session is None else
               _session.read_bytes(path, max_bytes=pin["size"]))
    if hashlib.sha256(content).hexdigest() != pin["sha256"] or len(content) != pin["size"]:
        raise ValueError("frozen context evidence changed")
    return content


def _identity(root, value):
    raw = Path(value)
    path = (raw if raw.is_absolute() else root / raw).resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _critique_findings(reviews):
    return [finding for review in reviews for finding in review.get("findings", [])
            if review.get("role") == "physics_critic"]


def _without(value, fields):
    if not isinstance(value, dict):
        raise ValueError("known review artifact has a malformed structured record")
    return {key: item for key, item in value.items() if key not in fields}


def _rows(value, project):
    if not isinstance(value, list):
        raise ValueError("known review artifact has a malformed structured list")
    return [project(row) for row in value]


def _project_known_judgments(document):
    """Withhold classifications from pipeline formats, not arbitrary raw data.

    Retain measured quantities, public assertions and specific evidence requests.
    The original report identity stays in the manifest; synthesis gets its exact
    bytes. Interpretive reasons can quote another verdict and are withheld too.
    """
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        return None
    if document.get("kind") == "controlled_diagnostic":
        result = _without(document, {"status"})
        def hypothesis(row):
            projected = _without(row, {"status"})
            projected["channels"] = _rows(row["channels"], lambda channel: _without(channel, {"status", "reason"}))
            return projected
        result["criterion_outcomes"] = _rows(document["criterion_outcomes"], hypothesis)
        result["integrity_checks"] = _rows(document["integrity_checks"], lambda row: _without(row, {"status", "reason"}))
        if document["capacity"] is not None:
            result["capacity"] = _without(document["capacity"], {"status", "reason"})
        return result, "diagnostic measurements and identities; outcome labels and interpretations withheld"
    if document.get("kind") == "scientific_decision_case":
        result = _without(document, {"status"})
        result["nodes"] = _rows(document["nodes"], lambda row: _without(row, {"status", "reviewer_decision"}))
        result["anchors"] = _rows(document["anchors"], lambda row: _without(row, {"status", "reason"}))
        result["obligations"] = _rows(document["obligations"], lambda row: _without(row, {"reason"}))
        return result, "decision claims, anchors and evidence requests; recorded judgments withheld"
    if set(document) == {"schema_version", "action", "root", "triggers", "budget", "nodes", "edges"}:
        result = dict(document)
        def node(row):
            projected = _without(row, {"review"})
            projected["assumptions"] = _rows(row["assumptions"], lambda assumption: _without(assumption, {"disposition", "reason"}))
            return projected
        result["nodes"] = _rows(document["nodes"], node)
        result["edges"] = _rows(document["edges"], lambda row: _without(row, {"review"}))
        return result, "public claim graph and evidence requests; reviewer and assumption dispositions withheld"
    return None


def _project_science_artifact(document, identity):
    """Keep executed scientific data and independent numerical failures visible.

    The worker recipe repeats the original proposal; only its actual task and
    input identities belong in a blinded packet. Adapter aggregate postconditions
    are withheld while raw traces, applicability and oracle evidence stay intact.
    """
    if not isinstance(document, dict):
        return None
    if Path(identity).name == "verification.json" or document.get("kind") in ("numerical_witness_receipt", "paired_normalized_moments"):
        return None
    if Path(identity).name == "recipe.json" and "specification" in document:
        specification = document["specification"]
        projected = dict(document)
        projected["specification"] = {key: specification[key] for key in ("schema_version", "mode", "task", "assumptions") if key in specification}
        return projected, "executed task and input identities; repeated producer proposal withheld"
    if "status" in document and document.get("physics_validated") is False:
        projected = _without(document, {"status"})
        if document.get("domain") == "model-probe" and isinstance(document.get("details"), dict):
            projected["details"] = _without(document["details"], {"checks_passed"})
        return projected, "scientific measurements and numerical witnesses; aggregate producer postcondition withheld"
    return None


_REVIEW_EVENT_FIELDS = {"schema_version", "sequence", "previous_sha256", "run_id", "utc",
                        "event", "cycle_id", "role", "actor_id", "verdict", "summary",
                        "findings", "closes", "claim_scope", "attestation", "sha256"}


_REVIEW_SUBMISSION_FIELDS = {
    "schema_version", "action", "request", "scope", "runtime_contract",
    "native_kernel_model_calls", "native_calls", "approval_execution_calls",
    "actor_authentication", "review_event", "imports", "metadata_identity_queries",
    "elapsed_seconds", "max_seconds",
}


def _review_journal_custody(root, identity):
    """Recognize exact review-journal ancestors, including absolute parent runs.

    Do not classify by basename or a substring such as 'review' in scientific
    filenames. The frozen source hash remains in the omission, and this helper
    does not open or decode the historical journal record.
    """
    raw = Path(identity)
    path = raw if raw.is_absolute() else root / raw
    namespace = Path(physics_review.DIRECTORY).parts
    matches = [index for index in range(len(path.parts) - len(namespace) + 1)
               if path.parts[index:index + len(namespace)] == namespace]
    if not matches:
        # Frozen non-journal evidence does not require its original live source
        # path to remain present, non-symlinked, or byte-identical after capture.
        return None
    if _safe_path(path) != path:
        raise ValueError("review-journal source custody identity is not canonical")
    # The first journal ancestor owns even a nested historical snapshot path.
    owner = Path(*path.parts[:matches[0]])
    return {"kind": "physics_review_journal", "run_root": str(owner),
            "directory": str(owner / physics_review.DIRECTORY),
            "relation": "current_run" if owner == root else "historical_run"}


def _review_event_identity(value):
    """Identify a complete self-consistent public review event, not arbitrary prose.

    This is a format/custody projection, not reviewer authentication or an
    independent validation of the historical judgment. Its original input hash
    remains committed and the current event chain is validated by _read.
    """
    if not isinstance(value, dict) or set(value) not in (_REVIEW_EVENT_FIELDS, _REVIEW_EVENT_FIELDS | {"supporting_artifacts"}):
        return None
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["sequence"]) is not int or value["sequence"] < 1
            or value["event"] != "review" or value["role"] not in physics_review.ROLES
            or value["verdict"] not in ("accept", "send_back", "stop")
            or not isinstance(value["cycle_id"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", value["cycle_id"])
            or any(not isinstance(value[key], str) or not value[key]
                   for key in ("run_id", "utc", "actor_id", "summary"))
            or not isinstance(value["findings"], list) or not isinstance(value["closes"], list)
            or value["attestation"] != physics_review.ATTESTATION
            or any(not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key])
                   for key in ("previous_sha256", "sha256"))):
        return None
    try:
        valid_digest = value["sha256"] == execution.digest({key: item for key, item in value.items()
                                                         if key != "sha256"})
    except (ValueError, TypeError, RecursionError):
        return None
    if not valid_digest:
        return None
    return {"run_id": value["run_id"], "cycle_id": value["cycle_id"],
            "review_role": value["role"], "event_sha256": value["sha256"]}


def _review_metadata_pin(value):
    """Recognize an exact metadata pin without opening its referenced source.

    Unknown nested payload, including extra fields beside a valid pin, stays
    scientific evidence. Neither this shape nor its digest authenticates actors.
    """
    if not isinstance(value, dict) or set(value) not in (
            {"path", "sha256", "bytes"}, {"path", "sha256", "size"}):
        return False
    size = value.get("bytes", value.get("size"))
    return (isinstance(value["path"], str) and bool(value["path"])
            and isinstance(value["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
            and type(size) is int and size >= 0)


def _review_submission_metadata(value):
    """Match declared receipt metadata recursively; retain ambiguous envelopes.

    Request/runtime records are recognized only as exact custody pins. Import
    maps contain only pins and identity-query rows contain only textual metadata.
    Arbitrary nested scientific data is never classified by top-level field name.
    Unknown wrapper formats remain visible even if that also retains a verdict.
    """
    if (not isinstance(value, dict) or value.get("action") != "submit"
            or not {"action", "review_event"} <= set(value)
            or not set(value) <= _REVIEW_SUBMISSION_FIELDS):
        return False
    for key, item in value.items():
        if key in ("action", "review_event"):
            continue  # The complete review event is separately validated.
        if key == "schema_version":
            if type(item) is not int or item != 1:
                return False
        elif key in ("request", "runtime_contract"):
            if not _review_metadata_pin(item):
                return False
        elif key == "imports":
            if (not isinstance(item, dict)
                    or any(not isinstance(name, str) or not name or not _review_metadata_pin(pin)
                           for name, pin in item.items())):
                return False
        elif key == "metadata_identity_queries":
            if (not isinstance(item, list) or any(
                    not isinstance(row, dict) or set(row) != {"event", "argv", "scope"}
                    or row["event"] != "subprocess.Popen"
                    or not isinstance(row["argv"], list) or not row["argv"]
                    or any(not isinstance(arg, str) for arg in row["argv"])
                    or not isinstance(row["scope"], str) or not row["scope"]
                    for row in item)):
                return False
        elif key in ("native_kernel_model_calls", "native_calls", "approval_execution_calls"):
            if type(item) is not int or item < 0:
                return False
        elif key in ("elapsed_seconds", "max_seconds"):
            if type(item) not in (int, float) or not 0 <= item < float("inf"):
                return False
        elif key in ("scope", "actor_authentication"):
            if not isinstance(item, str):
                return False
        else:
            return False
    return True


def _review_record_custody(document, cycle_id, role):
    """Omit explicit historical vote records and unrelated submission envelopes.

    Current synthesis still gets the validated current reviews in its manifest;
    a current-cycle standalone event can also remain in synthesis. Scientific
    reports with outcome/precision/failure fields are unaffected by this rule.
    """
    event = _review_event_identity(document)
    kind = "physics_review_event"
    if event is None and _review_submission_metadata(document):
        event = _review_event_identity(document.get("review_event"))
        kind = "physics_review_submission_receipt"
    if event is None:
        return None
    if event["cycle_id"] == cycle_id and role == "synthesizer":
        return None
    return {"kind": kind, **event,
            "relation": "current_cycle" if event["cycle_id"] == cycle_id else "historical_cycle"}


# Complete copy authentication is distinct from content returned in one call.
# Defaults preserve the existing ordinary packet envelope. Larger envelopes must
# be explicitly declared in the digest-bound manifest; these are finite maxima.
_INDEX_DEFAULTS = {"max_artifacts": 10_000, "max_total_bytes": 256 * 1024**2}
_INDEX_CEILINGS = {"max_artifacts": 20_000, "max_total_bytes": 512 * 1024**2}
_MANIFEST_MAX_BYTES = 16 * 1024**2


def _index_limits(value=None):
    if value is None:
        return dict(_INDEX_DEFAULTS)
    if type(value) is not dict or set(value) != set(_INDEX_DEFAULTS):
        raise ValueError("closed complete-index resource declaration required")
    for key, maximum in _INDEX_CEILINGS.items():
        if type(value[key]) is not int or not 0 < value[key] <= maximum:
            raise ValueError("invalid complete-index resource bound: " + key)
    return dict(value)


def _project_context(root, role, *, max_file_bytes, _session=None,
                     retain_ids=None, max_source_bytes=None, index_limits=None):
    """One shared role projection for creation and current-basis batch checks."""
    limits = _index_limits(index_limits)
    # Validate the complete retained chain before selecting any content.
    reg, events = physics_review._read(root, _session=_session)
    cycles = [event for event in events if event["event"] == "cycle"]
    if not cycles:
        raise ValueError("open a review cycle before preparing reviewer context")
    cycle = cycles[-1]
    science_cycle = any(pin["path"] in SCIENCE_PRIVATE_INPUTS for pin in cycle["snapshots"])
    reviews = [event for event in events if event["event"] == "review"
               and event["cycle_id"] == cycle["cycle_id"]]
    correction = next((event for event in reversed(events) if event["event"] == "correction" and
                       (event["correction_id"] == cycle.get("correction_id") or
                        event["cycle_id"] == cycle["cycle_id"])), None)
    manifest = {"schema_version": 1, "role": role, "run_id": reg["run_id"],
                "cycle_id": cycle["cycle_id"], "source_event_sha256": cycle["sha256"],
                "artifacts": [], "omissions": [], "findings": list(cycle.get("inherited_findings", [])), "reviews": [],
                "allowed_claim_scopes": reg["policy"]["claim_scopes"],
                "required_checks": reg["policy"]["required_checks"],
                "access_limitation": LIMITATION}
    if index_limits is not None:
        manifest["index_limits"] = limits
    # Original obligations accompany every role, independently of producer verdicts.
    science_pin = next((p for p in cycle["snapshots"] if p["path"] == "inputs/science.json"), None)
    if science_pin is not None:
        spec = json.loads(_frozen_bytes(root, science_pin))
        if "goal_binding" in spec:
            from .task_completion import binding_projection, _in_cycle
            parent = binding_projection(spec["goal_binding"], base_dir=Path.cwd())
            if not all(_in_cycle(p, root, cycle) for p in parent["input_pins"]):
                raise ValueError("parent goal was not captured in this child review cycle")
            manifest["parent_task"] = parent
    if role != "critic":
        manifest["findings"].extend(_critique_findings(reviews))
    if role in ("improver", "verifier", "synthesizer") and correction:
        manifest["correction"] = {key: correction[key] for key in
                                  ("correction_id", "changed_paths", "stages", "recheck_checks", "stage_specs", "regenerated_inputs")
                                  if key in correction}
        manifest["correction"]["source_event_sha256"] = correction["sha256"]
        manifest["correction"]["state"] = ("successor_cycle_opened" if cycle.get("correction_id")
                                               == correction["correction_id"] else "admitted_before_successor")
        if role == "verifier":
            manifest["verification_scope"] = {
                "finding_ids": [finding["id"] for finding in manifest["findings"]],
                "recheck_checks": correction["recheck_checks"], "stages": correction["stages"],
                "claim": "Closure of the listed repair obligations, not certification of the whole analysis",
                "fresh_attempts_available": cycle.get("correction_id") == correction["correction_id"]}
    if role == "synthesizer":
        manifest["reviews"] = reviews
    # A field-level projection of the comparison removes the producer's outcome
    # label and summary. The original identity remains in the packet for audit.
    checkin = next((pin for pin in cycle["snapshots"] if pin["path"] == "inputs/checkin2.json"), None)
    waypoint_path = physics_review.waypoint_evidence.MANIFEST
    if checkin and checkin.get("snapshot"):
        waypoint_path = _identity(root, json.loads(_frozen_bytes(root, checkin, _session=_session))["sections"]["evidence_manifest"])
    waypoint = next((pin for pin in cycle["snapshots"] if pin["path"] == waypoint_path), None)
    comparison_path = None
    if waypoint and waypoint.get("snapshot"):
        comparison_path = json.loads(_frozen_bytes(root, waypoint, _session=_session))["comparison"]["path"]
    projected = []
    source_bytes = 0
    copied_bytes = 0
    selected = [(pin, "current_cycle") for pin in cycle["snapshots"]]
    if role != "critic" and correction:
        baseline = next(event for event in cycles if event["cycle_id"] == correction["cycle_id"])
        if baseline["cycle_id"] != cycle["cycle_id"]:
            selected.extend((pin, "before_correction") for pin in baseline["snapshots"]
                            if pin["path"] in correction["changed_paths"])
        else:
            selected.extend((pin, "admitted_correction") for pin in correction["snapshots"])
        manifest["correction"]["setting_changes"] = [
            {"path": path,
             "before_sha256": next(pin["sha256"] for pin in baseline["effective_settings"] if pin["path"] == path),
             "admitted_sha256": next(pin["sha256"] for pin in correction["effective_settings"] if pin["path"] == path)}
            for path in correction["changed_paths"]]
    for index, (pin, phase) in enumerate(selected):
        identity = pin["path"]
        entry = {"id": f"a{index:04d}", "source_path": identity,
                 "source_sha256": pin["sha256"], "source_phase": phase}
        review_custody = _review_journal_custody(root, identity)
        if review_custody is not None:
            manifest["omissions"].append({**entry, "source_size": pin["size"],
                                         "reason": "review journal custody; historical or current judgments withheld",
                                         "review_custody": review_custody})
            continue
        name = Path(identity).name.lower()
        parts = Path(identity).parts
        science_output = science_cycle and len(parts) >= 3 and parts[0] == "outputs" and re.fullmatch(r"attempt-[1-9][0-9]*", parts[1])
        science_result = science_output and (name == "result.json" or len(parts) > 3 and name == "verification.json")
        if ((identity in SCIENCE_PRIVATE_INPUTS and role != "synthesizer")
                or (name in EXCLUDED and not science_result) or identity.startswith(physics_review.DIRECTORY + "/")
                or name in ("checkin1.json", "checkin1_approval.json", "checkin2.json",
                            "physics_review_policy.json")):
            manifest["omissions"].append({**entry, "reason": "producer narrative, authorization or review record"})
            continue
        frozen = pin.get("snapshot")
        if not frozen:
            manifest["omissions"].append({**entry, "reason": "content not retained; request a bounded independent computation"})
            continue
        if pin["size"] > max_file_bytes:
            manifest["omissions"].append({**entry, "reason": "exceeds context size limit; request a bounded witness"})
            continue
        source_bytes += pin["size"]
        if max_source_bytes is not None and source_bytes > max_source_bytes:
            raise ValueError("review context source projection exceeds batch byte limit")
        content = _frozen_bytes(root, pin, _session=_session)
        try:
            custody_document = json.loads(content)
        except (UnicodeError, ValueError, RecursionError):
            custody_document = None
        review_custody = _review_record_custody(custody_document, cycle["cycle_id"], role)
        if review_custody is not None:
            manifest["omissions"].append({**entry, "source_size": pin["size"],
                                         "reason": "explicit review event or submission receipt; judgments withheld",
                                         "review_custody": review_custody})
            continue
        projection = "exact bytes"
        if identity == comparison_path and role != "synthesizer":
            document = json.loads(content)
            content = (json.dumps({"diagnostics": document["diagnostics"]}, indent=2,
                                  allow_nan=False) + "\n").encode()
            projection = "diagnostics only; producer status and summary withheld"
        elif identity == waypoint_path and role != "synthesizer":
            document = json.loads(content)
            document["result"] = {"diagnostics": document["result"]["diagnostics"]}
            content = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode()
            projection = "waypoint identities and diagnostics; duplicated producer status and summary withheld"
        elif role in ("critic", "verifier"):
            # Check-result files are explicit structured records, not arbitrary
            # JSON. Their producer classification is also a potential anchor.
            try:
                document = json.loads(content)
            except (UnicodeError, ValueError):
                document = None
            if isinstance(document, dict) and set(document) == {"schema_version", "checks"} and document["checks"] == cycle["checks"]:
                document["checks"] = [{k: v for k, v in check.items() if k != "status"} for check in document["checks"]]
                content = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode()
                projection = "check identities, located evidence and attempt IDs; producer check status withheld"
            else:
                known = _project_known_judgments(document)
                if known is not None:
                    document, projection = known
                    content = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode()
                elif science_cycle:
                    scientific = _project_science_artifact(document, identity)
                    if scientific is not None:
                        document, projection = scientific
                        content = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode()
        suffix = Path(identity).suffix or ".txt"
        relative = f"artifacts/{entry['id']}{suffix}"
        if retain_ids is None or entry['id'] in retain_ids:
            projected.append((relative, content))
        copied_bytes += len(content)
        if copied_bytes > limits["max_total_bytes"]:
            raise ValueError("review context aggregate byte bound exceeded")
        manifest["artifacts"].append({**entry, "path": relative,
                                     "sha256": hashlib.sha256(content).hexdigest(),
                                     "projection": projection})
    if (len(manifest["artifacts"]) > limits["max_artifacts"]
            or len(manifest["omissions"]) > _INDEX_CEILINGS["max_artifacts"]):
        raise ValueError("bounded complete role artifact index required")
    manifest["sha256"] = execution.digest(manifest)
    manifest_bytes = len((json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode())
    if manifest_bytes > _MANIFEST_MAX_BYTES:
        raise ValueError("review context manifest exceeds its byte bound")
    if copied_bytes + manifest_bytes > limits["max_total_bytes"]:
        raise ValueError("review context aggregate byte bound exceeded")
    return manifest, projected, reg, events


def create(root, role, out, *, max_file_bytes=2_000_000, index_limits=None):
    """Project frozen evidence; never expose another verdict to critic/verifier."""
    if role not in ROLES:
        raise ValueError("unknown review context role")
    if type(max_file_bytes) is not int or max_file_bytes <= 0:
        raise ValueError("max_file_bytes must be a positive exact integer")
    root, out = _safe_path(root), _safe_path(out)
    if out.exists():
        raise FileExistsError("review context destination already exists")
    manifest, projected, _, _ = _project_context(root, role, max_file_bytes=max_file_bytes, index_limits=index_limits)
    # Build and validate all source projections before consuming an output name.
    # Exclusive creation prevents silently replacing a previous role packet.
    out.mkdir(parents=True, exist_ok=False)
    (out / "artifacts").mkdir()
    for relative, content in projected:
        with (out / relative).open("xb") as stream:
            stream.write(content)
    with (out / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest



class _PacketIndex:
    """One-call bounded index/copy custody; never a cross-call cache or authority."""
    def __init__(self, packet, expected_manifest_sha256):
        self.root = _safe_path(packet)
        self.observed = {}
        self.parents = {}
        self.total = 0
        self.closed = False
        if type(expected_manifest_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256):
            raise ValueError("the externally retained creation manifest digest is required")
        self.limits = dict(_INDEX_CEILINGS)  # only the manifest is read before its declaration
        raw = self._read(self.root / "manifest.json", _MANIFEST_MAX_BYTES)
        self.manifest_file_sha256 = hashlib.sha256(raw).hexdigest()
        self.manifest = _strict_json_bytes(raw)
        if (type(self.manifest) is not dict or self.manifest.get("sha256") != expected_manifest_sha256
                or execution.digest({k:v for k,v in self.manifest.items() if k != "sha256"}) != expected_manifest_sha256):
            raise ValueError("review context manifest changed")
        self.limits = _index_limits(self.manifest.get("index_limits"))
        if self.total > self.limits["max_total_bytes"]:
            raise ValueError("review context aggregate byte bound exceeded")
        omissions = self.manifest.get("omissions", [])
        if type(omissions) is not list or len(omissions) > _INDEX_CEILINGS["max_artifacts"]:
            raise ValueError("bounded complete role omission index required")
        entries = self.manifest.get("artifacts")
        if type(entries) is not list or len(entries) > self.limits["max_artifacts"]:
            raise ValueError("bounded complete role artifact index required")
        self.entries = {}
        self.paths = {}
        for entry in entries:
            if (type(entry) is not dict or type(entry.get("id")) is not str
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", entry["id"])
                    or entry["id"] in self.entries or type(entry.get("path")) is not str
                    or type(entry.get("sha256")) is not str or not re.fullmatch(r"[0-9a-f]{64}",entry["sha256"])):
                raise ValueError("invalid or duplicate role artifact index")
            relative = Path(entry["path"])
            if (relative.is_absolute() or relative.as_posix() != entry["path"] or len(relative.parts) != 2
                    or relative.parts[0] != "artifacts" or relative.stem != entry["id"]):
                raise ValueError("review context artifact escaped its allowlist")
            self.entries[entry["id"]] = entry
            self.paths[entry["id"]] = self.root / relative
        self.members = self._members()
        if set(self.members) != {p.name for p in self.paths.values()}:
            raise ValueError("review context artifact membership differs from complete index")
        self.source_capture = None
        if self.manifest.get("kind") == "sfitter_designer_source_packet_v1":
            from . import sfitter_source_context
            self.source_capture = sfitter_source_context.packet_capture(self)

    def _members(self):
        directory = self.root / "artifacts"
        self._parents(directory / "placeholder")
        return tuple(sorted(p.name for p in directory.iterdir()))

    def _parent_identity(self, parent):
        observed = identity(parent.lstat())
        # The owned packet namespace keeps full entry/metadata custody. Higher
        # ancestors identify the same ordinary directory, not unrelated entries
        # created by another task. Every indexed leaf keeps its full identity.
        return observed if parent in {self.root, self.root / "artifacts"} else observed[:3]

    def _parents(self, path):
        import stat
        for parent in path.parents:
            observed = self._parent_identity(parent)
            if stat.S_ISLNK(observed[2]):
                raise ValueError("review context paths cannot traverse symlinks")
            if not stat.S_ISDIR(observed[2]):
                raise ValueError("review context ancestry is not ordinary")
            old = self.parents.setdefault(parent, observed)
            if observed != old:
                raise ValueError("review context ancestor changed during read")

    def _read(self, path, maximum):
        import stat
        self._parents(path)
        before = identity(path.lstat())
        if stat.S_ISLNK(before[2]):
            raise ValueError("review context paths cannot traverse symlinks")
        if not stat.S_ISREG(before[2]) or not 0 <= before[3] <= maximum:
            raise ValueError("review context requires bounded ordinary files")
        self.total += before[3]
        if self.total > self.limits["max_total_bytes"]:
            raise ValueError("review context aggregate byte bound exceeded")
        with path.open("rb") as stream:
            if identity(os.fstat(stream.fileno())) != before:
                raise ValueError("review context descriptor changed before read")
            raw = stream.read(before[3] + 1)
            if identity(os.fstat(stream.fileno())) != before:
                raise ValueError("review context descriptor changed during read")
        if len(raw) != before[3] or identity(path.lstat()) != before:
            raise ValueError("review context file changed during read")
        self.observed[path] = before
        return raw

    def read(self, entry):
        path = self.paths[entry["id"]]
        raw = self._read(path, 64 * 1024**2)
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("review context artifact changed or escaped its allowlist")
        return raw

    def finish(self):
        if self.closed:
            raise ValueError("review context observation already closed")
        self.closed = True
        if self.source_capture is not None:
            self.source_capture.finish()
        if (self._members() != self.members or any(identity(p.lstat()) != v for p,v in self.observed.items())
                or any(self._parent_identity(p) != v for p,v in self.parents.items())):
            raise ValueError("review context ending identity or membership changed")
        if self.source_capture is not None:
            self.source_capture.finish()


def verify_packet(packet, *, expected_manifest_sha256):
    """Authenticate every indexed copy once with a fresh ending census."""
    index = _PacketIndex(packet, expected_manifest_sha256)
    for entry in index.entries.values():
        index.read(entry)
    index.finish()
    return index.manifest


def _catalogue_entry(entry, raw):
    try:
        raw.decode("utf8")
        if b"\x00" in raw: raise UnicodeError("binary NUL")
        encoding = "utf-8"
    except UnicodeError:
        encoding = "binary"
    return {**entry, "bytes": len(raw), "content_encoding": encoding,
            "content_presented": False, "read_action": "review-read",
            "page_parameters": {"artifact_id":entry["id"],"offset":0,"max_bytes":65536}}


def read_index_page(packet, *, expected_manifest_sha256, section="artifacts", offset=0,
                    max_bytes=65536, query=""):
    """Grounded full-index/omission paging; an index row is never a content read."""
    if (section not in {"artifacts","omissions"} or type(offset) is not int or offset < 0
            or type(max_bytes) is not int or not 1024 <= max_bytes <= 65536
            or type(query) is not str or len(query) > 256):
        raise ValueError("bounded role index page parameters required")
    index = _PacketIndex(packet, expected_manifest_sha256)
    rows = []
    for entry in index.entries.values():
        raw = index.read(entry)
        if section == "artifacts": rows.append(_catalogue_entry(entry, raw))
    if section == "omissions": rows = index.manifest.get("omissions", [])
    if type(rows) is not list: raise ValueError("role omission index must be a list")
    complete_sha = execution.digest(rows)
    selected = [r for r in rows if query.casefold() in json.dumps(r,sort_keys=True).casefold()]
    if offset > len(selected): raise ValueError("role index offset exceeds matched census")
    page = []
    for row in selected[offset:]:
        if len(json.dumps(page+[row],sort_keys=True).encode()) > max_bytes:
            if not page: raise ValueError("one index row exceeds page bound")
            break
        page.append(row)
    index.finish()
    return {"manifest_sha256":expected_manifest_sha256,"section":section,
            "complete_index_sha256":complete_sha,"total_entries":len(rows),"matched_entries":len(selected),
            "query":query,"offset":offset,"next_offset":offset+len(page),
            "complete":offset+len(page)==len(selected),"entries":page,"artifact_content_presented":False}


def read_artifact(packet, artifact_id, *, expected_manifest_sha256):
    """Return bytes from one hash-bound allowlisted artifact, never an arbitrary path."""
    index = _PacketIndex(packet, expected_manifest_sha256)
    if type(artifact_id) is not str or artifact_id not in index.entries:
        raise ValueError("artifact ID is absent or ambiguous in this role's context")
    content = index.read(index.entries[artifact_id])
    index.finish()
    return content



# These are ceilings for one read call, not a persistent cache or a physics gate.
_BATCH_LIMITS = {"max_artifacts": 20_000, "max_manifest_bytes": 16 * 1024**2,
                 "max_artifact_bytes": 64 * 1024**2, "max_total_bytes": 256 * 1024**2,
                 "max_source_bytes": 512 * 1024**2, "max_session_io_bytes": 4 * 1024**3}


def _strict_json_bytes(raw):
    def reject(value):
        raise ValueError("non-finite JSON number: " + value)
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject(value)
        return number
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                      parse_constant=reject, parse_float=finite_float)


class _BatchReadSession(ValidationSession):
    """Authenticated bytes and bounded session-managed I/O inside one call."""
    def __init__(self, root, validation_limit):
        self.validation_limit = validation_limit
        self.io_bytes = 0
        self.content_reads = []
        try:
            super().__init__(root, resolve_path=execution.resolve_path, read_json=self.read_document,
                             runtime_context=execution.runtime_context, digest=execution.digest,
                             state_name=execution.STATE_NAME)
        except BaseException:
            if hasattr(self, 'hashes'):
                self.close()
            raise

    def _reserve(self, size):
        if type(size) is not int or size < 0 or self.io_bytes + size > self.validation_limit:
            raise ValueError("review batch session-managed evidence I/O exceeds its byte limit")
        self.io_bytes += size

    def hash_file(self, path):
        if self.closed:
            raise ValueError('validation session is already closed')
        path = Path(path)
        before = self.observe(path)
        if before not in self.hashes:
            self._reserve(before[3])
            content_digest = hashlib.sha256()
            remaining = before[3]
            with path.open('rb') as stream:
                if identity(os.fstat(stream.fileno())) != before:
                    raise ValueError('review batch file replaced before hashing')
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('review batch file truncated while hashing')
                    content_digest.update(block)
                    remaining -= len(block)
                if stream.read(1) or identity(os.fstat(stream.fileno())) != before:
                    raise ValueError('review batch file changed while hashing')
            self.hashes[before] = content_digest.hexdigest()
            self.hash_bytes += before[3]
            self.hash_calls += 1
        if self.observe(path) != before:
            raise ValueError('review batch file changed during hash reuse')
        self.files[str(path)] = before
        return self.hashes[before]

    def read_bytes(self, value, *, max_bytes):
        path = self.regular_file(value, self.rundir)
        before = self.observe(path)
        if before[3] > max_bytes:
            raise ValueError("review batch file exceeds its byte limit")
        self._reserve(before[3])
        with path.open('rb') as stream:
            if identity(os.fstat(stream.fileno())) != before:
                raise ValueError("review batch file replaced before content read")
            raw = stream.read(before[3] + 1)
            if identity(os.fstat(stream.fileno())) != before:
                raise ValueError("review batch file changed during content read")
        if len(raw) != before[3] or self.observe(path) != before:
            raise ValueError("review batch file changed during content read")
        actual = hashlib.sha256(raw).hexdigest()
        if before in self.hashes and self.hashes[before] != actual:
            raise ValueError("review batch parsed bytes differ from authenticated bytes")
        self.hashes[before] = actual
        self.files[str(path)] = before
        self.content_reads.append((str(path), len(raw), actual))
        return raw

    def read_document(self, path):
        # The hash and parser consume the same bytes, including for journal/policy.
        raw = self.read_bytes(path, max_bytes=_BATCH_LIMITS["max_manifest_bytes"])
        doc = _strict_json_bytes(raw)
        self.track(doc)
        return doc

    def finish(self):
        # Same final census as ValidationSession, with a bounded authenticated
        # ledger read. No proof survives this operation, including on refusal.
        if self.closed:
            raise ValueError('validation session is already closed')
        try:
            for path in tuple(self.absent_inventory_paths):
                if any(p.is_symlink() for p in (path, *path.parents)) or path.exists():
                    raise ValueError('observed absent inventory appeared or traverses a symlink before return')
            for path in tuple(self.regular_paths):
                self.require_regular(path)
            for (value, outputs), previous in self.queries.items():
                path, census, _ = self.census(value, outputs)
                if (str(path), census) != previous:
                    raise ValueError('artifact path or directory inventory changed before return: ' + value)
            for path, previous in self.files.items():
                if self.observe(path) != previous:
                    raise ValueError('artifact changed before return: ' + path)
            if self.ledger.exists() != self.ledger_existed:
                raise ValueError('execution ledger appeared or disappeared during validation')
            if self.ledger_existed:
                previous = self.files[str(self.ledger)]
                raw = self.read_bytes(self.ledger, max_bytes=previous[3])
                if hashlib.sha256(raw).hexdigest() != self.ledger_digest:
                    raise ValueError('execution ledger changed during validation')
            if self.runtime_context() != self.runtime:
                raise ValueError('runtime changed during validation')
            if any(self.digest(obj) != before for obj, before in self.tracked):
                raise ValueError('supplied state or plan changed during validation')
            return []
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ['validation final census unavailable: ' + str(exc)]
        finally:
            self.close()


def read_artifacts(packet, artifact_ids, *, expected_manifest_sha256, rundir,
                   expected_role, context_max_file_bytes=2_000_000,
                   max_artifacts=10_000, max_manifest_bytes=16 * 1024**2,
                   max_artifact_bytes=8 * 1024**2, max_total_bytes=64 * 1024**2,
                   max_source_bytes=256 * 1024**2, max_session_io_bytes=512 * 1024**2):
    """Read a bounded ordered ID batch with fresh context and whole-call custody.

    Returns ``{'artifacts': [{...receipt, 'content': bytes}], 'receipt': {...}}``.
    Every requested copy is actually read and hashed. Session I/O accounting excludes
    direct approval/runtime helper reads, whose cost is unknown. It is not a total
    operation I/O or time ceiling. The receipt is observational,
    never a role vote, delivery permission or runtime/physics qualification.
    ``context_max_file_bytes`` must match the packet's original creation parameter.
    Retained pre-correction bytes remain historical; current source observations
    are reported separately rather than substituted for the frozen projection.
    """
    if expected_role not in ROLES:
        raise ValueError("unknown review context role")
    if type(expected_manifest_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256):
        raise ValueError("the externally retained creation manifest digest is required")
    limits = {k: v for k, v in locals().items() if k in _BATCH_LIMITS}
    for key, value in limits.items():
        if type(value) is not int or value <= 0 or value > _BATCH_LIMITS[key]:
            raise ValueError("invalid bounded review batch limit: " + key)
    if (type(context_max_file_bytes) is not int or context_max_file_bytes <= 0
            or context_max_file_bytes > _BATCH_LIMITS["max_artifact_bytes"]):
        raise ValueError("invalid bounded review context creation limit")
    if (type(artifact_ids) is not list or not artifact_ids or len(artifact_ids) > max_artifacts
            or any(type(v) is not str or not re.fullmatch(r"a[0-9]{4,}", v) for v in artifact_ids)
            or len(set(artifact_ids)) != len(artifact_ids)):
        raise ValueError("review batch needs distinct bounded allowlisted artifact IDs")
    packet, root = _safe_path(packet), _safe_path(rundir)
    session = None
    try:
        session = _BatchReadSession(root, max_session_io_bytes)
        session.track(artifact_ids)
        manifest_path = session.regular_file(packet / "manifest.json", root)
        manifest_raw = session.read_bytes(manifest_path, max_bytes=max_manifest_bytes)
        manifest = _strict_json_bytes(manifest_raw)
        if (type(manifest) is not dict or manifest.get("sha256") != expected_manifest_sha256
                or expected_manifest_sha256 != execution.digest({k: v for k, v in manifest.items() if k != "sha256"})):
            raise ValueError("review context manifest changed")
        session.track(manifest)
        expected, projected, reg, events = _project_context(
            root, expected_role, max_file_bytes=context_max_file_bytes, _session=session,
            retain_ids=set(artifact_ids), max_source_bytes=max_source_bytes,
            index_limits=manifest.get("index_limits"))
        physics_review._base_live(root, reg, _session=session)
        if manifest != expected:
            raise ValueError("review context differs from its current role/source/journal basis")
        if len(manifest["artifacts"]) > _index_limits(manifest.get("index_limits"))["max_artifacts"]:
            raise ValueError("review context population exceeds batch index ceiling")
        index = {entry['id']: entry for entry in manifest['artifacts']}
        if len(index) != len(manifest['artifacts']) or any(v not in index for v in artifact_ids):
            raise ValueError("artifact ID is absent or ambiguous in this role's context")
        session.require_inventory(packet / 'artifacts')
        expected_members = {packet / entry['path'] for entry in index.values()}
        if set((packet / 'artifacts').iterdir()) != expected_members:
            raise ValueError('review context artifact inventory differs from its allowlist')
        for path in expected_members:
            session.regular_file(path, root)
        projected = dict(projected)
        # Snapshot current source identities separately; never relabel old bytes.
        sources = {}
        for entry in manifest['artifacts']:
            source = Path(entry['source_path'])
            source = (source if source.is_absolute() else root / source).absolute()
            if source.exists() or source.is_symlink():
                current = session.regular_file(source, root)
                sources[entry['id']] = {'path':str(current), 'sha256':session.hash_file(current),
                                         'size':session.files[str(current)][3]}
            else:
                session.require_inventory(source)
                sources[entry['id']] = None
        result, rows, payload_total = [], [], 0
        for artifact_id in artifact_ids:
            entry = index[artifact_id]
            relative = Path(entry['path'])
            if (relative.is_absolute() or relative.as_posix() != entry['path']
                    or len(relative.parts) != 2 or relative.parts[0] != 'artifacts'
                    or relative.stem != artifact_id):
                raise ValueError("review context artifact changed or escaped its allowlist")
            path = session.regular_file(packet / relative, root)
            if not path.is_relative_to(packet / 'artifacts'):
                raise ValueError("review context artifact changed or escaped its allowlist")
            size = session.files[str(path)][3]
            if payload_total + size > max_total_bytes:
                raise ValueError("review batch content exceeds its aggregate byte limit")
            raw = session.read_bytes(path, max_bytes=max_artifact_bytes)
            if (hashlib.sha256(raw).hexdigest() != entry['sha256']
                    or raw != projected[entry['path']]):
                raise ValueError("review context artifact changed or differs from source projection")
            payload_total += len(raw)
            row = {k:entry[k] for k in ('id','path','sha256','source_path','source_sha256','source_phase','projection')}
            row.update({'size':len(raw), 'content_read':True, 'current_source':sources[artifact_id]})
            rows.append(row)
            result.append({**row,'content':raw})
        receipt = {'schema_version':1,'kind':'review_context_batch_read',
                   'packet':str(packet),'manifest_sha256':expected_manifest_sha256,
                   'manifest_file_sha256':hashlib.sha256(manifest_raw).hexdigest(),
                   'role':expected_role,'run_id':reg['run_id'],'cycle_id':manifest['cycle_id'],
                   'source_event_sha256':manifest['source_event_sha256'],
                   'journal_checkpoint':{'sequence':len(events),'sha256':events[-1]['sha256'] if events else reg['sha256']},
                   'review_state':physics_review._view(reg,events)['state'],
                   'requested_ids':list(artifact_ids),'artifacts':rows,'content_bytes':payload_total,
                   'manifest_parses':1,'requested_content_reads':len(rows),
                   'limits':{**limits,'context_max_file_bytes':context_max_file_bytes},
                   'acceptance':False,'delivery':False,'reuse':False,'role_vote':False,
                   'access_limitation':LIMITATION}
        session.track(receipt)
        errors = session.finish()
        if errors:
            raise ValueError("review batch final freshness refused: " + "; ".join(errors))
        receipt['session_io_bytes'] = session.io_bytes
        receipt['excluded_direct_proof_runtime_io'] = 'not_measured'
        receipt['total_operation_io_bytes'] = None
        receipt['sha256'] = execution.digest(receipt)
        return {'artifacts':result,'receipt':receipt}
    finally:
        if session is not None:
            session.close()

def _artifact_page(raw, artifact_id, *, offset, max_bytes):
    """Bound exact bytes without pretending a split/binary page is UTF-8."""
    if (type(offset) is not int or offset < 0 or offset > len(raw)
            or type(max_bytes) is not int or not 1 <= max_bytes <= 65536):
        raise ValueError("artifact page requires a valid byte offset and 1..65536 byte limit")
    page = raw[offset:offset + max_bytes]
    try:
        content, encoding = page.decode("utf-8"), "utf-8"
    except UnicodeError:
        content, encoding = base64.b64encode(page).decode("ascii"), "base64"
    return {"artifact_id": artifact_id, "offset": offset, "bytes": len(page),
            "total_bytes": len(raw), "next_offset": offset + len(page),
            "complete": offset + len(page) == len(raw),
            "artifact_sha256": hashlib.sha256(raw).hexdigest(),
            "page_sha256": hashlib.sha256(page).hexdigest(),
            "content_encoding": encoding, "content": content}


def read_artifact_page(packet, artifact_id, *, expected_manifest_sha256, offset=0, max_bytes=65536):
    """Authenticate the complete allowlisted blob on every selected page read."""
    raw = read_artifact(packet, artifact_id, expected_manifest_sha256=expected_manifest_sha256)
    return _artifact_page(raw, artifact_id, offset=offset, max_bytes=max_bytes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--rundir", required=True)
    create_parser.add_argument("--role", choices=ROLES, required=True)
    create_parser.add_argument("--out", required=True)
    create_parser.add_argument("--max-index-artifacts", type=int)
    create_parser.add_argument("--max-index-bytes", type=int)
    read_parser = commands.add_parser("read")
    read_parser.add_argument("--packet", required=True)
    read_parser.add_argument("--artifact", required=True)
    read_parser.add_argument("--manifest-sha256", required=True,
                             help="creation digest retained outside the packet, not re-read from its manifest")
    read_parser.add_argument("--offset", type=int)
    read_parser.add_argument("--max-bytes", type=int, default=65536)
    index_parser = commands.add_parser("index")
    index_parser.add_argument("--packet", required=True)
    index_parser.add_argument("--manifest-sha256", required=True)
    index_parser.add_argument("--section", choices=("artifacts","omissions"), default="artifacts")
    index_parser.add_argument("--offset", type=int, default=0)
    index_parser.add_argument("--max-bytes", type=int, default=65536)
    index_parser.add_argument("--query", default="")
    args = parser.parse_args(argv)
    if args.command == "index":
        print(json.dumps(read_index_page(args.packet, expected_manifest_sha256=args.manifest_sha256,
            section=args.section, offset=args.offset, max_bytes=args.max_bytes, query=args.query),indent=2))
        return 0
    if args.command == "create":
        limits = None
        if args.max_index_artifacts is not None or args.max_index_bytes is not None:
            limits = {"max_artifacts": args.max_index_artifacts if args.max_index_artifacts is not None else _INDEX_DEFAULTS["max_artifacts"],
                      "max_total_bytes": args.max_index_bytes if args.max_index_bytes is not None else _INDEX_DEFAULTS["max_total_bytes"]}
        print(json.dumps(create(args.rundir, args.role, args.out, index_limits=limits), indent=2))
    else:
        if args.offset is not None:
            print(json.dumps(read_artifact_page(args.packet, args.artifact,
                expected_manifest_sha256=args.manifest_sha256, offset=args.offset, max_bytes=args.max_bytes), indent=2))
            return 0
        # Images remain files in the packet; use the image tool on the returned
        # file after its ID/hash has been checked, rather than printing pixels.
        value = read_artifact(args.packet, args.artifact, expected_manifest_sha256=args.manifest_sha256)
        try:
            print(value.decode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("binary artifact: inspect its verified packet file with an image/file tool") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
