"""Executable, bounded transports for public agent-graph records.

HTTP requests are stateless, with no scientific tools or inherited conversation.
The command adapter executes a trusted local program; it is NOT an OS sandbox.
No transport authenticates scientific judgments or authorizes physics compute.
Only public JSON results and numeric usage are returned; API reasoning items and
transport error bodies are never retained. No transport retries are automatic.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from . import provider_transport, visual_presentation

from ravel.physics import model_inputs, quantities, eft_toolchain, finite_integrals, full_auxiliary_calibration, root_stream, dataset_query_quantities, parameter_space_sampling, cosmic_evolution, cosmic_evolution_worker
from ravel.validation import numerical_witness
from . import scientific_judgment
from . import report_integrity, manuscript_production
from . import physics_knowledge, decision_case, experiment_allocator, research_transfer, review_context, constructive_contrast, scientific_context, empirical_search, adaptation_reuse, scientific_artifact, public_source_tools, scientific_task_delivery, scientific_report, scientific_phase_allocation, cosmology_backend, cosmology_runtime, sfitter_workflow, sfitter_scan_inputs
from .execution import digest, file_hash, process_group_members
from .state_io import read_json
from . import backend_portfolio, slurm_owned_step

DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
PRIVATE_FIELDS = {"chain_of_thought", "private_reasoning", "reasoning_trace", "scratchpad"}
BLIND_ROLES = {"critic": "critic", "physics_critic": "critic", "verifier": "verifier",
               "skeptical_verifier": "verifier",
               "rdj_critic": "rdj_critic", "rdj_verifier": "rdj_verifier"}
SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "items", "enum", "const",
               "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "description", "title", "anyOf"}
JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
MODEL_KEYS = {"instructions", "model", "reasoning_effort", "max_output_tokens", "output_schema"}


class HostFailure(RuntimeError):
    """Safe transport failure. Ambiguous means an already-sent effect is unknown."""

    def __init__(self, message, *, retryable=False, ambiguous=False):
        super().__init__(message)
        self.retryable = retryable
        self.ambiguous = ambiguous


def _keys(value, required, label):
    if type(value) is not dict or set(value) != set(required):
        raise HostFailure(f"invalid {label} fields")


def _text(value, label, maximum=100_000):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise HostFailure(f"invalid {label}")
    return value


def _integer(value, label, minimum=1, maximum=10_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise HostFailure(f"invalid {label}")
    return value


def _positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
        raise HostFailure(f"invalid {label}")
    return float(value)


def _json_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise HostFailure("invalid public JSON") from exc


def _loads(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON number")
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            reject(value)
        return number
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise HostFailure("malformed public JSON response") from exc


def _public(value, depth=0):
    if depth > 64:
        raise HostFailure("public result exceeds nesting bound")
    if isinstance(value, dict):
        if PRIVATE_FIELDS.intersection(value):
            raise HostFailure("private reasoning fields are not public records")
        for item in value.values():
            _public(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _public(item, depth + 1)
    _json_bytes(value)


def _schema(schema, depth=0):
    """Validate an explicit finite JSON-schema subset before any transport call."""
    if depth > 32 or type(schema) is not dict or set(schema) - SCHEMA_KEYS:
        raise HostFailure("unsupported output schema")
    types = schema.get("type")
    if isinstance(types, str):
        types = [types]
    if not isinstance(types, list) or not types or any(type(t) is not str or t not in JSON_TYPES for t in types) or len(set(types)) != len(types):
        raise HostFailure("output schema requires supported explicit types")
    for key in ("description", "title"):
        if key in schema:
            _text(schema[key], "schema annotation", 4096)
    if "object" in types:
        properties, required = schema.get("properties"), schema.get("required")
        if (type(properties) is not dict or type(required) is not list
                or any(type(key) is not str or key in PRIVATE_FIELDS for key in properties)
                or any(type(key) is not str for key in required)
                or len(set(required)) != len(required) or set(required) != set(properties)
                or schema.get("additionalProperties") is not False):
            raise HostFailure("object output schemas require all properties and no additional fields")
        for nested in properties.values():
            _schema(nested, depth + 1)
    elif any(key in schema for key in ("properties", "required", "additionalProperties")):
        raise HostFailure("object schema fields require object type")
    if "array" in types:
        _schema(schema.get("items"), depth + 1)
    elif "items" in schema:
        raise HostFailure("array schema fields require array type")
    for key in ("minItems", "maxItems", "minLength", "maxLength"):
        if key in schema:
            _integer(schema[key], "schema bound", 0)
            needed = "array" if key.endswith("Items") else "string"
            if needed not in types:
                raise HostFailure("output schema bound does not apply to its type")
    for key in ("minimum", "maximum"):
        if key in schema and (type(schema[key]) not in (int, float) or not math.isfinite(schema[key])):
            raise HostFailure("schema bounds must be finite numbers")
        if key in schema and not {"integer", "number"}.intersection(types):
            raise HostFailure("output schema bound does not apply to its type")
    for lower, upper in (("minimum", "maximum"), ("minItems", "maxItems"), ("minLength", "maxLength")):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise HostFailure("inverted output schema bounds")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise HostFailure("schema enum requires values")
    if "anyOf" in schema:
        if type(schema["anyOf"]) is not list or not 1 <= len(schema["anyOf"]) <= 16:
            raise HostFailure("bounded output alternatives required")
        for choice in schema["anyOf"]: _schema(choice, depth + 1)
    _json_bytes(schema)


def _validate(value, schema):
    types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    actual = ("null" if value is None else "boolean" if type(value) is bool else
              "integer" if type(value) is int else "number" if type(value) is float else
              "string" if type(value) is str else "array" if type(value) is list else
              "object" if type(value) is dict else "invalid")
    if actual not in types and not (actual == "integer" and "number" in types):
        raise HostFailure("public JSON does not match output schema")
    encoded = _json_bytes(value)
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try: _validate(value, choice)
            except HostFailure: continue
            break
        else: raise HostFailure("public JSON does not match conditional output alternatives")
    if "enum" in schema and all(not _same_json(value, choice) for choice in schema["enum"]):
        raise HostFailure("public JSON does not match output enum")
    if "const" in schema and not _same_json(value, schema["const"]):
        raise HostFailure("public JSON does not match output constant")
    if actual == "object":
        if set(value) != set(schema["properties"]):
            raise HostFailure("public JSON object fields do not match schema")
        for key, item in value.items():
            _validate(item, schema["properties"][key])
    if actual == "array":
        for item in value:
            _validate(item, schema["items"])
    for lower, upper, measure in (("minItems", "maxItems", len(value) if actual == "array" else None),
                                   ("minLength", "maxLength", len(value) if actual == "string" else None),
                                   ("minimum", "maximum", value if actual in ("integer", "number") else None)):
        if measure is not None and ((lower in schema and measure < schema[lower]) or
                                    (upper in schema and measure > schema[upper])):
            raise HostFailure("public JSON exceeds output schema bound")


def completion_limits(parameters):
    """Finite complete public-value and external-envelope byte limits."""
    limits = parameters.get("completion_limits", {
        "public_value_bytes": 2_000_000, "response_file_bytes": 2_000_000})
    _keys(limits, {"public_value_bytes", "response_file_bytes"}, "completion limits")
    for key in limits:
        _integer(limits[key], key, 1, 16_000_000)
    if limits["response_file_bytes"] < limits["public_value_bytes"]:
        raise HostFailure("external response envelope cannot be smaller than its public value")
    return dict(limits)


def validate_completion_value(value, parameters):
    value = validate_public_result(value, parameters["output_schema"])
    if len(_json_bytes(value)) > completion_limits(parameters)["public_value_bytes"]:
        raise HostFailure("complete public model value exceeds byte bound; no truncation")
    return value


def _completion_file(value, maximum, *, expected=None):
    """Bound before parsing, pin complete bytes, and fence alias/read races."""
    path = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise HostFailure("external completion evidence cannot traverse aliases")
    fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise HostFailure("external completion evidence exceeds complete file byte bound")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if fields(opened) != fields(before):
            raise HostFailure("external completion evidence changed before read")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != before.st_size or len(raw) > maximum or fields(after) != fields(before)
            or fields(path.stat()) != fields(before)
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise HostFailure("external completion evidence changed during complete read")
    pin = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    if expected is not None:
        if (type(expected) is not dict or set(expected) - {"path", "sha256", "size"}
                or expected.get("path") != pin["path"] or expected.get("sha256") != pin["sha256"]
                or "size" in expected and expected["size"] != pin["size"]):
            raise HostFailure("external completion evidence differs from retained pin")
    return raw, pin


def external_usage_report(report, response, *, base_dir):
    """Retained host assertions are never relabelled provider-observed usage."""
    _keys(report, {"state", "tokens", "source"}, "external usage report")
    _keys(report["tokens"], {"input_tokens", "output_tokens", "total_tokens"}, "external usage tokens")
    usage = _usage(report["tokens"])
    if report["state"] == "unknown":
        if any(v is not None for v in usage.values()) or report["source"] is not None:
            raise HostFailure("unknown external usage must remain null without invented evidence")
        return usage, {"state": "unknown", "tokens": usage, "source": None}
    if report["state"] != "host_reported" or any(v is None for v in usage.values()):
        raise HostFailure("external telemetry requires complete counts or explicit unknown usage")
    source = report["source"]
    _keys(source, {"kind", "invocation_id", "artifact"}, "external usage source")
    if source["kind"] not in ("provider_response", "host_meter") or source["invocation_id"] != response["invocation_id"]:
        raise HostFailure("external usage source belongs to a different invocation")
    _keys(source["artifact"], {"path", "sha256", "size"}, "external usage evidence pin")
    _integer(source["artifact"]["size"], "external usage evidence size", 1, 65536)
    path = Path(source["artifact"]["path"])
    path = path if path.is_absolute() else Path(base_dir) / path
    expected = {**source["artifact"], "path": str(path.absolute())}
    raw, pin = _completion_file(path, 65536, expected=expected)
    evidence = _loads(raw)
    _keys(evidence, {"schema_version", "kind", "request_id", "request_sha256", "invocation_id",
                     "observed_model", "complete_invocation", "usage"}, "public external usage evidence")
    _keys(evidence["usage"], {"input_tokens", "output_tokens", "total_tokens"}, "usage evidence tokens")
    evidence_usage = _usage(evidence["usage"])
    if (type(evidence["schema_version"]) is not int or evidence["schema_version"] != 1
            or evidence["kind"] != source["kind"] or evidence["complete_invocation"] is not True
            or any(evidence[k] != response[k] for k in ("request_id", "request_sha256", "invocation_id", "observed_model"))
            or evidence_usage != usage):
        raise HostFailure("external usage evidence differs from complete source invocation")
    _completion_file(path, 65536, expected=pin)
    return usage, {"state": "host_reported", "tokens": usage,
                   "source": {**source, "artifact": pin}}


ISOLATION_KEYS = {"transport_id", "declaration_sha256", "argv_sha256", "cli_version", "config",
                  "config_overriding_arguments", "env_names", "effort_transmitted", "user_configuration_loaded", "basis"}
ISOLATION_OPTIONAL = {"cli_session_id", "executable_sha256", "session_receipt_sha256", "project_instructions",
                      "project_run"}


def _transport_isolation(evidence):
    """The CLI transport's isolation evidence: names and digests only, never values.

    The named declaration must exist and its digest must equal the evidence's; a forged or zero digest
    is refused. Shape and digest checks do not make the evidence host-observed.
    """
    if type(evidence) is not dict or not ISOLATION_KEYS <= set(evidence) or set(evidence) - ISOLATION_KEYS - ISOLATION_OPTIONAL:
        raise HostFailure("invalid transport isolation evidence fields")
    for key in ("transport_id", "config", "basis"):
        _text(evidence[key], key, 400)
    for key in ("declaration_sha256", "argv_sha256"):
        if type(evidence[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", evidence[key]):
            raise HostFailure("transport isolation digests must be sha256 hex")
    if evidence["cli_version"] is not None:
        _text(evidence["cli_version"], "cli_version", 200)
    for key in ("env_names", "config_overriding_arguments"):
        if type(evidence[key]) is not list or any(type(n) is not str or not n or len(n) > 100 for n in evidence[key]):
            raise HostFailure("transport isolation lists hold names only")
    if type(evidence["user_configuration_loaded"]) is not bool or type(evidence["effort_transmitted"]) is not bool:
        raise HostFailure("transport isolation flags must be booleans")
    session = evidence.get("cli_session_id")
    if session is not None:
        _text(session, "cli_session_id", 256)
    supplied = evidence.get("project_instructions")
    if "project_instructions" in evidence and (
            type(supplied) is not dict or set(supplied) != {"sha256", "bytes", "mechanism"}
            or type(supplied["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", supplied["sha256"])
            or type(supplied["bytes"]) is not int or supplied["bytes"] < 1
            or type(supplied["mechanism"]) is not str or len(supplied["mechanism"]) > 64):
        raise HostFailure("transport isolation project_instructions holds the document sha256, bytes and mechanism")
    named = evidence.get("project_run")
    if "project_run" in evidence and (type(named) is not str or not 0 < len(named) <= 4096 or not os.path.isabs(named)):
        raise HostFailure("transport isolation project_run is the absolute run directory the session was started for")
    for key in ("executable_sha256", "session_receipt_sha256"):
        if key in evidence and (type(evidence[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", evidence[key])):
            raise HostFailure("transport isolation digests must be sha256 hex")
    from . import transport_registry
    try:
        declared = transport_registry.load(evidence["transport_id"])
    except (KeyError, ValueError):
        raise HostFailure(f"transport isolation evidence names an undeclared transport {evidence['transport_id']!r}") from None
    if transport_registry.declaration_sha256(declared) != evidence["declaration_sha256"]:
        raise HostFailure(f"transport isolation declaration digest does not match transport {evidence['transport_id']}")
    return evidence


def external_completion(document, response_path, *, expected=None):
    """Validate the complete sealed envelope and public host usage evidence."""
    parameters = document["parameters"]
    limits = completion_limits(parameters)
    if "completion_limits" in document and document["completion_limits"] != limits:
        raise HostFailure("prepared external completion limits changed")
    raw, pin = _completion_file(response_path, limits["response_file_bytes"], expected=expected)
    response = _loads(raw)
    version = response.get("schema_version") if type(response) is dict else None
    if type(version) is not int or version not in (1, 2, 3):
        raise HostFailure("external response schema_version must be integer 1, 2 or 3")
    names = {"schema_version", "request_id", "request_sha256", "invocation_id", "actor_id",
             "observed_model", "fresh_context", "parent_transcript_supplied", "value"}
    names |= {2: {"usage_report"}, 3: {"usage_report", "user_configuration_loaded", "isolation"}}.get(version, set())
    _keys(response, names, "external response")
    if version == 3:
        _transport_isolation(response["isolation"])
        if type(response["user_configuration_loaded"]) is not bool or \
                response["user_configuration_loaded"] != response["isolation"]["user_configuration_loaded"]:
            raise HostFailure("external user_configuration_loaded must match its isolation evidence")
        if response["user_configuration_loaded"] and response["fresh_context"]:
            raise HostFailure("a session that loaded user configuration cannot attest a fresh context")
    for key in ("request_id", "request_sha256", "invocation_id", "actor_id", "observed_model"):
        _text(response[key], key, 256)
    if (type(response["fresh_context"]) is not bool or type(response["parent_transcript_supplied"]) is not bool):
        raise HostFailure("explicit boolean external context attestations required")
    if response["request_id"] != document["request"]["request_id"] or response["request_sha256"] != document["sha256"]:
        raise HostFailure("external response belongs to a different request/context/subject")
    value = validate_completion_value(response["value"], parameters)
    report = response.get("usage_report", {"state": "unknown", "tokens": _usage(None), "source": None})
    usage, report = external_usage_report(report, response, base_dir=Path(response_path).absolute().parent)
    if usage["output_tokens"] is not None and usage["output_tokens"] > parameters["max_output_tokens"]:
        raise HostFailure("external reported output token usage exceeds declared bound")
    _completion_file(response_path, limits["response_file_bytes"], expected=pin)
    return response, value, usage, report, pin


def _responses_output_schema(schema):
    """Keep conditional public records nested under an object on the wire.

    Strict Responses schemas reject root anyOf. The external/command public
    record remains unchanged; only this transport's bound request is wrapped.
    """
    if schema is not None and "anyOf" in schema:
        return {"type": "object", "properties": {"public_record": schema},
                "required": ["public_record"], "additionalProperties": False}
    return schema


def _responses_public_value(value, schema):
    if schema is not None and "anyOf" in schema:
        _keys(value, {"public_record"}, "conditional Responses record wrapper")
        return value["public_record"]
    return value


def _same_json(left, right):
    # JSON Schema numeric equality treats 1 and 1.0 alike, while a boolean is
    # distinct from a number. Scientific anchor type checks remain separate.
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(_same_json(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def _safe_path(value):
    path = Path(value).expanduser().absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise HostFailure("host artifact path traverses a symlink")
    return path.resolve()


def _input_text_snapshot(path, sha256, maximum):
    """Decode the exact authenticated bytes presented to a model.

    Descriptor identity and ending leaf/ancestor observations refuse path
    replacement. Hashing a path after a separate text read is insufficient:
    an ABA replacement could otherwise authenticate different content.
    """
    path = _safe_path(path)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    before = path.stat()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or identity(before) != identity(opened):
            raise HostFailure("host input descriptor differs from bound artifact")
        raw = stream.read(maximum + 1)
        closed = os.fstat(stream.fileno())
    after = _safe_path(path).stat()
    if identity(opened) != identity(closed) or identity(closed) != identity(after):
        raise HostFailure("host input changed during authenticated context consumption")
    if len(raw) > maximum or hashlib.sha256(raw).hexdigest() != sha256:
        raise HostFailure("host input consumed bytes differ from bound artifact")
    try:
        # Preserve the old UTF-8 read_text universal-newline behavior.
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeError as exc:
        raise HostFailure("model inputs require UTF-8 public evidence") from exc
    return text, len(raw)


def _usage(value):
    if value is None:
        return {key: None for key in ("input_tokens", "output_tokens", "total_tokens")}
    if type(value) is not dict:
        raise HostFailure("invalid provider usage")
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(key)
        if item is not None:
            _integer(item, "provider token usage", 0, 10**12)
        result[key] = item
    if (all(result[key] is not None for key in result)
            and result["total_tokens"] != result["input_tokens"] + result["output_tokens"]):
        raise HostFailure("inconsistent provider token usage")
    return result


def validate_public_result(value, schema):
    """Validate a public JSON object without retaining any private trace fields."""
    if type(value) is not dict:
        raise HostFailure("public model result must be a JSON object")
    _public(value)
    if schema is not None:
        _schema(schema)
        if schema["type"] != "object":
            raise HostFailure("public model output schema must have object root")
        _validate(value, schema)
    return _loads(_json_bytes(value))


def prepare_model_context(node, request):
    """Prepare the exact supplied public context; no model/credential access.

    An external host must separately attest fresh sessions, reserve its call and
    enforce its access boundary. This function does not create an OS sandbox.
    """
    return AgentHost().prepare_model_context(node, request)


class AgentHost:
    """One configured transport plus an allowlist of deterministic Ravel tools."""

    def __init__(self, *, adapter="responses", endpoint=DEFAULT_ENDPOINT, api_key=None, command=None,
                 timeout_seconds=60, max_request_bytes=2_000_000, max_response_bytes=2_000_000,
                 environment=None, bound_roots=None, cosmology_runtime_binding=None,
                 privacy="configured", local_models=None, capabilities=None, vision=None, literature_origins=None,
                 transport=None, pass_env=None, auth=None):
        if adapter not in provider_transport.HTTP_ADAPTERS | {"command"}:
            raise HostFailure("unsupported host adapter")
        self.cosmology_runtime_binding = cosmology_runtime_binding
        self.adapter = adapter
        self.timeout = _positive(timeout_seconds, "host timeout")
        self.max_request = _integer(max_request_bytes, "request byte bound", 1, 16_000_000)
        self.max_response = _integer(max_response_bytes, "response byte bound", 1, 16_000_000)
        if adapter == "chat_completions" and endpoint == DEFAULT_ENDPOINT:
            raise HostFailure("compatible chat transport requires an explicit chat endpoint")
        if adapter != "responses" and endpoint == DEFAULT_ENDPOINT:
            endpoint = provider_transport.DEFAULTS.get(adapter, endpoint)
        self.endpoint = self._endpoint(endpoint)
        self.privacy, self.local_models = privacy, [] if local_models is None else local_models
        try:
            self.capabilities = provider_transport.policy(adapter, self.endpoint, privacy, self.local_models, capabilities)
        except provider_transport.ProviderFailure as exc:
            raise HostFailure(str(exc)) from None
        self.local_models = list(self.local_models)
        from . import literature_context
        try:
            self.literature_origins = literature_context.origins([] if literature_origins is None else literature_origins)
        except ValueError as exc:
            raise HostFailure(str(exc)) from None
        try:
            self.vision = visual_presentation.configuration(vision, adapter)
        except visual_presentation.VisualFailure as exc:
            raise HostFailure(str(exc)) from None
        if privacy == "local_only" and cosmology_runtime_binding is not None:
            raise HostFailure("local_only refuses an unconfined nested runtime model transport")
        if api_key is not None and (type(api_key) is not str or not api_key or any(c in api_key for c in "\r\n")):
            raise HostFailure("invalid explicitly configured API key")
        self._api_key = api_key
        self._api_key_env = None
        if adapter == "command":
            if (type(command) is not list or not command
                    or any(type(arg) is not str or not arg for arg in command)):
                raise HostFailure("command adapter requires an explicit argument list")
            self.command = tuple(command)
        else:
            self.command = None
        environment = {} if environment is None else environment
        if type(environment) is not dict or any(type(k) is not str or type(v) is not str or "=" in k or "\x00" in k + v for k, v in environment.items()):
            raise HostFailure("invalid explicit command environment")
        self.environment = {"PATH": os.defpath, "LANG": "C.UTF-8", **environment}
        if bound_roots is not None and (type(bound_roots) is not list or not bound_roots):
            raise HostFailure("bound_roots must be a nonempty list")
        self.bound_roots = tuple(_safe_path(path) for path in (bound_roots or []))
        self.transport = None
        if transport is not None:
            from . import transport_registry
            try:
                self.transport = transport_registry.load(transport)
            except (KeyError, ValueError) as exc:
                raise HostFailure(f"unknown transport declaration: {exc}") from None
        if pass_env is not None and (adapter != "command" or type(pass_env) is not list
                                     or any(type(n) is not str or not n.isidentifier() for n in pass_env)):
            raise HostFailure("pass_env lists environment variable names for a command transport")
        self.pass_env = tuple(pass_env or ())
        try:
            self.auth = provider_transport.auth_config(adapter, auth, self.privacy)
        except provider_transport.ProviderFailure as exc:
            raise HostFailure(str(exc)) from None
        if self.auth is not None and self.auth["kind"] != "env" and api_key is not None:
            raise HostFailure("an API key and a token command are alternatives")
        self.wrapper_agent = None
        if adapter == "command":
            from . import cli_agent_host
            self.wrapper_agent = cli_agent_host.wrapper_agent(self.command, self.environment)
            if self.transport is None and self.wrapper_agent is not None:
                from . import transport_registry
                self.transport = transport_registry.load(cli_agent_host.ONESHOT[self.wrapper_agent])
        self._bind_transport()

    def _bind_transport(self):
        """A transport label must describe the executor this host actually runs; refuse a mismatch."""
        if self.transport is None:
            return
        kind, identity = self.transport["transport_kind"], self.transport["id"]
        if self.adapter == "command":
            from . import cli_agent_host
            if kind != "cli-oneshot" or self.wrapper_agent is None or cli_agent_host.ONESHOT[self.wrapper_agent] != identity:
                raise HostFailure(f"transport {identity} ({kind}) is not bound to this command: a command host carries "
                                  "a transport label only when it runs the RAVEL agent-cli launcher for that transport")
            return
        if kind != "http-model":
            raise HostFailure(f"transport {identity} ({kind}) is not an HTTP model transport")
        declared = self.transport.get("endpoint")
        if declared is not None:
            expected = urlsplit(declared)
            same_path = "{" in expected.path or expected.path == self.endpoint.path
            if (expected.scheme, expected.netloc) != (self.endpoint.scheme, self.endpoint.netloc) or not same_path:
                raise HostFailure(f"transport {identity} declares endpoint {declared}; this host sends to "
                                  f"{self.endpoint.scheme}://{self.endpoint.netloc}{self.endpoint.path}")

    def _bind_auth(self, name):
        """The credential variable a labelled HTTP host reads must be one its declaration names."""
        if self.transport is None or name is None:
            return
        auth = self.transport["auth"]
        if auth["kind"] == "env" and name not in auth["env_names"]:
            raise HostFailure(f"transport {self.transport['id']} authenticates with {', '.join(auth['env_names'])}; "
                              f"this host reads {name}")

    @property
    def identity(self):
        """Nonsecret executable identity used by graph result custody and reuse."""
        sources = {module.__name__: file_hash(module.__file__) for module in
                   (cosmic_evolution, cosmic_evolution.core, cosmic_evolution_worker, slurm_owned_step, physics_knowledge, model_inputs, quantities, decision_case, experiment_allocator, research_transfer, review_context,
                    constructive_contrast, constructive_contrast.dp, constructive_contrast.event_contrasts,
                    scientific_context, scientific_context.analysis_sources, scientific_context.state_io,
                    numerical_witness, scientific_phase_allocation, cosmology_backend, cosmology_runtime, sfitter_workflow, sfitter_scan_inputs, sfitter_workflow.sfitter_native, sfitter_workflow.sfitter_inputs, empirical_search, empirical_search.ce, adaptation_reuse, adaptation_reuse.ce, adaptation_reuse.cc, scientific_artifact, scientific_artifact.ce, public_source_tools, scientific_task_delivery,
                    scientific_report, scientific_report.sa, scientific_report.ce, scientific_report.sc,
                    scientific_report.sc.analysis_sources, scientific_report.sc.state_io)}
        from . import procedure_export
        sources.update(procedure_export.dependency_sources())
        from ravel.physics import feyn_graph, diagram_analysis, feynarts_amplitude, symbolic_evaluation
        for module in (feyn_graph, diagram_analysis, feynarts_amplitude, symbolic_evaluation):
            sources[module.__name__]=file_hash(module.__file__)
        for name in ('feyn_graph_worker.py','diagram_analysis_worker.py'):
            sources['diagram.native-child:'+name]=file_hash(Path(feyn_graph.__file__).with_name(name))
        sources['diagram.upstream-api']=file_hash(feyn_graph.API)
        from . import capability_routing
        sources[capability_routing.__name__] = file_hash(capability_routing.__file__)
        from . import intake_planner, calculation_completion
        from ravel.physics import literal_calculation
        for module in (intake_planner, calculation_completion, literal_calculation):
            sources[module.__name__] = file_hash(module.__file__)
        for pin in capability_routing.catalogue()["source_pins"]:
            sources["capability-source:" + pin["path"]] = pin["sha256"]
        from . import langgraph_runtime, research_orchestrator, research_coordinator_decisions, langchain_service
        for module in (langgraph_runtime, research_orchestrator, research_coordinator_decisions, langchain_service):
            sources[module.__name__] = file_hash(module.__file__)
        from . import research_cycle
        sources[research_cycle.__name__] = file_hash(research_cycle.__file__)
        from . import quantitative_predictive_checks
        sources[quantitative_predictive_checks.__name__] = file_hash(quantitative_predictive_checks.__file__)
        sources[scientific_judgment.__name__] = file_hash(scientific_judgment.__file__)
        for module in (report_integrity, report_integrity.execution, report_integrity.decision_case,
                       report_integrity.state_io, manuscript_production, manuscript_production.manuscript_format, manuscript_production.scientific_report, scientific_judgment.review, scientific_judgment.review_context,
                       scientific_judgment.agent_graph):
            sources[module.__name__] = file_hash(module.__file__)
        from . import manuscript_workflow
        sources[manuscript_workflow.__name__] = file_hash(manuscript_workflow.__file__)
        sources[visual_presentation.__name__] = file_hash(visual_presentation.__file__)
        from . import literature_context
        sources[literature_context.__name__] = file_hash(literature_context.__file__)
        from ravel.physics import sfitter_observed_events
        sources[sfitter_observed_events.__name__] = file_hash(sfitter_observed_events.__file__)
        from ravel.physics.source_calibration import recipes
        for module in (recipes, recipes.provider, recipes._scalar, recipes.formulas, recipes.kernels):
            sources[module.__name__] = file_hash(module.__file__)
        from . import sfitter_review_protocol
        sources[sfitter_review_protocol.__name__] = file_hash(sfitter_review_protocol.__file__)
        from . import sfitter_application
        from ravel.physics import ma5_saf
        for module in (sfitter_application, sfitter_application.conductor, sfitter_application.workflow,
                       sfitter_application.task_completion, sfitter_application.research_cycle,
                       sfitter_application.physics_review, sfitter_application.science, ma5_saf):
            sources[module.__name__] = file_hash(module.__file__)
        from . import research_protocol
        sources[research_protocol.__name__] = file_hash(research_protocol.__file__)
        sources[research_protocol.comparison.__name__] = file_hash(research_protocol.comparison.__file__)
        from . import research_followup
        sources[research_followup.__name__] = file_hash(research_followup.__file__)
        from . import research_blueprint, research_tools
        sources[research_blueprint.__name__] = file_hash(research_blueprint.__file__)
        sources[research_tools.__name__] = file_hash(research_tools.__file__)
        from . import structural_models
        from ravel.physics import model_sarah, ufo_interop, model_derivation_bridge, model_tool_bridge
        for module in (structural_models, model_sarah, ufo_interop, model_derivation_bridge, model_tool_bridge):
            sources[module.__name__] = file_hash(module.__file__)
        from . import model_spectrum_plan
        sources[model_spectrum_plan.__name__] = file_hash(model_spectrum_plan.__file__)
        sources[model_spectrum_plan.engine.__name__] = file_hash(model_spectrum_plan.engine.__file__)
        sources[model_spectrum_plan.named.__name__] = file_hash(model_spectrum_plan.named.__file__)
        from ravel.physics import weak_scale_mssm
        sources[weak_scale_mssm.__name__] = file_hash(weak_scale_mssm.__file__)
        sources['spectrum.weak-scale-upstream-profile'] = file_hash(weak_scale_mssm.PROFILE)
        from ravel.physics import mssm_observable_map, mssm_llp_handoff
        for module in (mssm_observable_map,mssm_llp_handoff):
            sources[module.__name__] = file_hash(module.__file__)
        sources['mssm.observable-convention-contract'] = file_hash(mssm_observable_map.API)
        from ravel.physics import nmssm_yukawa_map
        for module in (nmssm_yukawa_map, nmssm_yukawa_map.ufo_decay):
            sources[module.__name__] = file_hash(module.__file__)
        sources['nmssm.tree-map-equation-contract'] = file_hash(nmssm_yukawa_map.API)
        sources['spectrum.named-upstream-profile'] = file_hash(model_spectrum_plan.named.PROFILE)
        sources[model_spectrum_plan.spheno.__name__] = file_hash(model_spectrum_plan.spheno.__file__)
        sources[model_spectrum_plan.decay_table.__name__] = file_hash(model_spectrum_plan.decay_table.__file__)
        sources['spectrum.spheno-upstream-profile'] = file_hash(model_spectrum_plan.spheno.PROFILE)
        sources['spectrum.pure-limit-table'] = file_hash(model_spectrum_plan.decay_table.TABLE)
        from . import model_event_plan
        sources[model_event_plan.__name__] = file_hash(model_event_plan.__file__)
        sources[model_event_plan.model_events.__name__] = file_hash(model_event_plan.model_events.__file__)
        from ravel.physics import model_event_weights
        sources[model_event_weights.__name__] = file_hash(model_event_weights.__file__)
        from . import agentrivet_runtime
        sources[agentrivet_runtime.__name__] = file_hash(agentrivet_runtime.__file__)
        from . import agentrivet_construction
        sources[agentrivet_construction.__name__] = file_hash(agentrivet_construction.__file__)
        sources['eft.coefficient-convention-transport'] = file_hash(sfitter_workflow.eft_conventions.__file__)
        sources['sfitter.native-array-export'] = file_hash(sfitter_workflow.sfitter_native.sfitter_results.__file__)
        sources['sfitter.native-child'] = file_hash(Path(sfitter_workflow.sfitter_native.__file__).with_name('sfitter_worker.py'))
        from ravel.physics import sfitter_complete_native, sfitter_complete_worker, sfitter_profiles, sfitter_compat, sfitter_card_derivation, sfitter_higgs_support, reviewed_source
        from . import sfitter_native_handoff
        for helper in (sfitter_complete_native,sfitter_complete_worker,sfitter_profiles,sfitter_compat,sfitter_card_derivation,sfitter_higgs_support,reviewed_source,sfitter_native_handoff):
            sources[helper.__name__]=file_hash(helper.__file__)
        sources['sfitter.upstream-source-census'] = file_hash(sfitter_workflow.sfitter_native.upstream_census_path())
        from ravel.physics import ma5_saf
        sources['sfitter.bounded-artifact-capture'] = file_hash(ma5_saf.__file__)
        sources[eft_toolchain.__name__] = file_hash(eft_toolchain.__file__)
        sources[eft_toolchain.core.__name__] = file_hash(eft_toolchain.core.__file__)
        sources['eft-toolchain.upstream-api'] = file_hash(eft_toolchain.API)
        sources['eft-toolchain.native-child'] = file_hash(Path(eft_toolchain.__file__).with_name('eft_toolchain_worker.py'))
        from ravel.physics import tree_array_export
        for module in (tree_array_export,):
            sources[module.__name__] = file_hash(module.__file__)
        sources[parameter_space_sampling.__name__] = file_hash(parameter_space_sampling.__file__)
        sources[parameter_space_sampling.core.__name__] = file_hash(parameter_space_sampling.core.__file__)
        sources['parameter-space-sampling.native-child'] = file_hash(Path(parameter_space_sampling.__file__).with_name('parameter_space_sampling_worker.py'))
        sources['parameter-space-sampling.observer'] = file_hash(Path(parameter_space_sampling.__file__).with_name('parameter_space_sampling_observer.py'))
        sources['parameter-space-sampling.api'] = file_hash(parameter_space_sampling.API)
        sources.update(parameter_space_sampling.context_source_hashes(file_hash))
        sources[dataset_query_quantities.__name__] = file_hash(dataset_query_quantities.__file__)
        sources[dataset_query_quantities.core.__name__] = file_hash(dataset_query_quantities.core.__file__)
        for module in (root_stream, root_stream.core):
            sources[module.__name__] = file_hash(module.__file__)
        from ravel.physics import root_stream_statistics
        sources[root_stream_statistics.__name__] = file_hash(root_stream_statistics.__file__)
        from ravel.physics import ntuple_inventory, columnar_ntuple_recipe, mc_expected_construction, asimov_sensitivity, discovery_heldout, mc_closure, columnar_selection, columnar_response
        for module in (ntuple_inventory, columnar_ntuple_recipe, mc_expected_construction, asimov_sensitivity, discovery_heldout, mc_closure, columnar_selection, columnar_response):
            sources[module.__name__] = file_hash(module.__file__)
        sources['root-stream.native-child'] = file_hash(Path(root_stream.__file__).with_name('root_stream_worker.py'))
        from ravel.physics import root_stream_partition_core, root_stream_partitions
        for module in (root_stream_partition_core, root_stream_partitions):
            sources[module.__name__] = file_hash(module.__file__)
        from . import site_workflow
        sources[site_workflow.__name__] = file_hash(site_workflow.__file__)
        sources['dataset-query-quantities.native-child'] = file_hash(Path(dataset_query_quantities.__file__).with_name('dataset_query_quantities_worker.py'))
        sources['dataset-query-quantities.api'] = file_hash(dataset_query_quantities.API)
        from ravel.physics import source_tables
        sources[source_tables.__name__] = file_hash(source_tables.__file__)
        sources[finite_integrals.__name__] = file_hash(finite_integrals.__file__)
        sources[finite_integrals.core.__name__] = file_hash(finite_integrals.core.__file__)
        for module in (full_auxiliary_calibration, full_auxiliary_calibration.native):
            sources[module.__name__] = file_hash(module.__file__)
        from ravel.physics import regional_calibration, regional_expected
        for module in (regional_calibration, regional_expected):
            sources[module.__name__] = file_hash(module.__file__)
        sources['finite-integrals.upstream-api'] = file_hash(finite_integrals.API)
        sources['finite-integrals.native-child'] = file_hash(Path(finite_integrals.__file__).with_name('finite_integrals_worker.py'))
        sources[__name__] = file_hash(__file__)
        sources[provider_transport.__name__] = file_hash(provider_transport.__file__)
        from . import provider_policy
        sources[provider_policy.__name__] = file_hash(provider_policy.__file__)
        from ravel.physics import ma5_pad, ma5_family, ma5_bookings, ma5_saf, ma5_saf_reader
        for module in (backend_portfolio, backend_portfolio.science, backend_portfolio.physics_review,
                       backend_portfolio.science.execution, ma5_pad, ma5_family, ma5_bookings, ma5_saf, ma5_saf_reader):
            sources[module.__name__] = file_hash(module.__file__)
        from ravel.physics import symbolic_evaluation
        sources[symbolic_evaluation.__name__] = file_hash(symbolic_evaluation.__file__)
        command_sources = {}
        if self.command is not None:
            executable = shutil.which(self.command[0], path=self.environment["PATH"])
            if executable and Path(executable).is_file():
                command_sources["executable"] = file_hash(Path(executable).resolve())
            for index, argument in enumerate(self.command[1:]):
                path = Path(argument)
                if path.is_absolute() and path.suffix in {".py", ".sh"} and path.is_file():
                    command_sources[f"argument{index}"] = file_hash(path)
        return {"schema_version": 1, "adapter": self.adapter,
                "endpoint": self.endpoint.geturl() if self.adapter in provider_transport.HTTP_ADAPTERS else None,
                "privacy": self.privacy, "local_models": list(self.local_models), "capabilities": self.capabilities,
                "vision": self.vision,
                "literature_origins": list(self.literature_origins),
                "api_key_environment": self._api_key_env,
                "command_sha256": digest(list(self.command)) if self.command else None,
                "command_sources": command_sources,
                "environment_sha256": digest(self.environment) if self.adapter == "command" else None,
                "bound_roots": [str(path) for path in self.bound_roots],
                "cosmology_runtime": self.cosmology_runtime_binding.identity if self.cosmology_runtime_binding else None,
                "witness_runtime": {"executable": str(Path(sys.executable).resolve()),
                                    "executable_sha256": file_hash(Path(sys.executable).resolve()),
                                    "python_version": sys.version.split()[0]},
                "timeout_seconds": self.timeout, "max_request_bytes": self.max_request,
                "max_response_bytes": self.max_response, "sources": sources,
                **({"transport": {"id": self.transport["id"], "declaration_sha256": digest(self.transport)}}
                   if self.transport else {}),
                **({"pass_env_names": list(self.pass_env)} if self.pass_env else {}),
                **({"auth": provider_transport.auth_identity(self.auth)} if self.auth else {})}

    @staticmethod
    def _endpoint(value):
        _text(value, "Responses endpoint", 4096)
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise HostFailure("invalid Responses endpoint") from exc
        if parsed.query:
            raise HostFailure("endpoint query strings are refused: classic Azure deployment URLs with ?api-version are "
                              "not supported; use the Azure /openai/v1/ endpoint")
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.fragment or not parsed.path or port == 0):
            raise HostFailure("invalid Responses endpoint")
        loopback = parsed.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise HostFailure("Responses endpoint requires HTTPS or loopback HTTP")
        return parsed

    @classmethod
    def from_config(cls, config):
        if type(config) is dict and config.get("type") == "agent-cli":
            # A fresh Claude Code / Codex CLI session behind the command adapter.
            from .cli_agent_host import host_config
            config = host_config(config)
        if type(config) is not dict or config.get("type") not in provider_transport.HTTP_ADAPTERS | {"command"}:
            raise HostFailure("host config requires a named HTTP provider or command type")
        common = {"type", "timeout_seconds", "max_request_bytes", "max_response_bytes", "bound_roots", "privacy", "local_models", "vision", "literature_origins"}
        allowed = common | {"transport"} | ({"endpoint", "api_key_env", "capabilities", "auth"} if config["type"] in provider_transport.HTTP_ADAPTERS else {"command", "environment", "pass_env"})
        if set(config) - allowed:
            raise HostFailure("unsupported host config field")
        options = {key: config[key] for key in common - {"type"} if key in config}
        options["transport"] = config.get("transport")
        if config["type"] == "command":
            return cls(adapter="command", command=config.get("command"), environment=config.get("environment"),
                       pass_env=config.get("pass_env"), **options)
        if "auth" in config:
            if "api_key_env" in config:
                raise HostFailure("auth replaces api_key_env; name the variable in auth.env_name")
            auth = config["auth"]
            name = auth.get("env_name") if type(auth) is dict else None
            endpoint = config.get("endpoint", provider_transport.DEFAULTS.get(config["type"]))
            if endpoint is None:
                raise HostFailure("compatible chat transport requires an explicit endpoint")
            result = cls(adapter=config["type"], endpoint=endpoint, auth=auth, capabilities=config.get("capabilities"),
                         api_key=os.environ.get(name) if type(name) is str and name.isidentifier() else None, **options)
            result._api_key_env = name
            result._bind_auth(name)
            return result
        name = config.get("api_key_env", "OPENAI_API_KEY" if config["type"] == "responses" and config.get("privacy") != "local_only" else None)
        if name is None and config.get("privacy") == "local_only":
            return cls(adapter=config["type"], endpoint=config.get("endpoint"), capabilities=config.get("capabilities"), **options)
        if type(name) is not str or not name.isidentifier():
            raise HostFailure("invalid API key environment name")
        # Read only this explicitly selected name. Do not inspect credential files.
        endpoint = config.get("endpoint", provider_transport.DEFAULTS.get(config["type"]))
        if endpoint is None:
            raise HostFailure("compatible chat transport requires an explicit endpoint and api_key_env (or local_only)")
        result = cls(adapter=config["type"], endpoint=endpoint, api_key=os.environ.get(name), capabilities=config.get("capabilities"), **options)
        result._api_key_env = name
        result._bind_auth(name)
        return result

    def _cancel(self, control, *, sent=False):
        if control.cancelled():
            raise HostFailure("host call canceled; remote completion is unknown" if sent else "host call canceled before dispatch",
                              ambiguous=sent)

    def _pins(self, node, request):
        pins = request.get("input_artifacts")
        if type(pins) is not list or len(pins) != len(node["inputs"]):
            raise HostFailure("host input pin mismatch")
        operational, operational_capture = {}, None
        # Operational tool binaries are authenticated data, not model context.
        # A closed quantitative request can admit its exact source population
        # under the original request/allocation minimum and existing cheap-tool
        # ceilings. Unrelated inputs and every model request retain their cap.
        if (node.get('kind') == 'tool' and node.get('action') == 'quantitative-predictive'
                and node.get('role') in {'designer', 'proposer', 'executor'}
                and type(node.get('max_attempts')) is int and node['max_attempts'] == 1):
            from . import quantitative_predictive_checks as predictive
            _keys(node['parameters'], {'request_input'}, 'quantitative tool parameters')
            identity = node['parameters']['request_input']
            rows = [p for p in pins if type(p) is dict and p.get('id') == identity]
            if len(rows) != 1 or rows[0] not in node['inputs']:
                raise HostFailure('quantitative binding requires its exact ordinary Host input')
            _keys(rows[0], {'id', 'path', 'sha256'}, 'quantitative request input')
            binding_path = _safe_path(rows[0]['path'])
            if self.bound_roots and not any(binding_path.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('quantitative binding outside configured Host roots')
            try:
                operational_capture = predictive.Capture(binding_path.parent, predictive.default_resources())
                def bootstrap(pin):
                    path = _safe_path(pin['path'])
                    if (self.bound_roots and not any(path.is_relative_to(root) for root in self.bound_roots)
                            or not path.is_file() or path.stat().st_size > self.max_request):
                        raise ValueError('quantitative bootstrap exceeds original Host input policy')
                    return operational_capture.document(pin)
                binding = predictive.validate_binding(bootstrap({'path': str(binding_path),
                    'sha256': rows[0]['sha256'], 'size': binding_path.stat().st_size}))
                allocation = predictive.validate_resources(bootstrap(binding['resources']))
                contract = predictive.validate_contract(bootstrap(binding['contract']))
                admission = predictive.requirements(contract, allocation)
                effective = admission['effective']; limits = effective['limits']
                if (admission['status'] != 'admitted' or effective['wall_seconds'] > self.timeout
                        or effective['max_rss_mib'] > 256 or limits['single_bytes'] > 16_000_000
                        or any(limits[k] > v for k, v in predictive.DEFAULT_LIMITS.items())):
                    raise ValueError('complete quantitative work requires ordinary larger allocation')
                for source in [binding['contract'], binding['resources'], *predictive._all_pins(contract)]:
                    path = Path(source['path'])
                    path = _safe_path(path if path.is_absolute() else Path(binding['contract']['path']).parent / path)
                    if self.bound_roots and not any(path.is_relative_to(root) for root in self.bound_roots):
                        raise ValueError('quantitative source outside configured Host roots')
                    canonical = {**source, 'path': str(path)}
                    if str(path) in operational and operational[str(path)] != canonical:
                        raise ValueError('conflicting quantitative operational source alias')
                    operational[str(path)] = canonical
                if (len(operational) > limits['sources']
                        or sum(p['size'] for p in operational.values()) > limits['unique_bytes']
                        or any(p['size'] > limits['single_bytes'] for p in operational.values())):
                    raise ValueError('complete quantitative source population exceeds original requested/allocation minimum')
                presented = {(p.get('path'), p.get('sha256')) for p in pins if type(p) is dict}
                if any((p['path'], p['sha256']) not in presented for p in operational.values()):
                    raise ValueError('complete quantitative operational sources must enter actual Host custody')
            except (ValueError, OSError, TypeError, KeyError) as exc:
                raise HostFailure('quantitative operational custody refused: ' + str(exc)) from None
        pdf_reader, original_pdf = None, None
        # Registered executor data custody differs from model presentation.
        # Only the exact original in this closed request may use the existing
        # 64MiB artifact policy; request/helper/all unrelated inputs keep caps.
        if (node.get('action') == 'literature-pdf-extract' and node.get('kind') == 'tool'
                and node.get('role') == 'executor' and node.get('max_attempts') == 1):
            from . import literature_context
            request_id = node.get('parameters', {}).get('request_input')
            rows = [p for p in pins if p.get('id') == request_id]
            if len(rows) != 1 or rows[0] not in node['inputs']:
                raise HostFailure('original PDF requires its explicit declared ordinary request')
            _keys(rows[0], {'id','path','sha256'}, 'PDF request input')
            request_path = _safe_path(rows[0]['path'])
            if self.bound_roots and not any(request_path.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('PDF request outside configured Host roots')
            pdf_reader = literature_context._Reader(request_path.parent)
            try:
                request_pin={'path':str(request_path),'sha256':rows[0]['sha256'],'size':request_path.stat().st_size}
                _, prospective = pdf_reader.document(request_pin)
                source_path = _safe_path(prospective['source']['path'])
                if self.bound_roots and not any(source_path.is_relative_to(root) for root in self.bound_roots):
                    raise HostFailure('original PDF outside configured Host roots')
                _, settings, _ = literature_context._pdf_request(request_pin, pdf_reader)
                original_pdf = settings['source']
            except (ValueError, OSError, TypeError, KeyError) as exc:
                raise HostFailure('original PDF operational custody refused: '+str(exc)) from None
        result = {}
        for pin in pins:
            _keys(pin, {"id", "path", "sha256", *({'restricted'} if 'restricted' in pin else set())}, "input pin")
            if pin not in node["inputs"] or pin["id"] in result:
                raise HostFailure("host input pin mismatch")
            path = _safe_path(pin["path"])
            if self.bound_roots and not any(path.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure("host input is outside configured bound roots")
            source = operational.get(str(path))
            operational_match = (source is not None and path.is_file() and pin['sha256'] == source['sha256']
                                 and path.stat().st_size == source['size'])
            is_pdf = (original_pdf is not None and str(path) == original_pdf['path']
                      and pin['sha256'] == original_pdf['sha256'] and path.stat().st_size == original_pdf['size'])
            if not path.is_file() or (path.stat().st_size > self.max_request and not (is_pdf or operational_match)) or file_hash(path) != pin["sha256"]:
                raise HostFailure("host input bytes differ from bound artifact")
            result[pin["id"]] = (path, pin["sha256"])
        if pdf_reader is not None:pdf_reader.finish()
        if operational_capture is not None:
            try: operational_capture.finish()
            except (ValueError, OSError) as exc:
                raise HostFailure('quantitative bootstrap changed at ending checkpoint: ' + str(exc)) from None
        return result

    def _packet(self, node, *, _observations=None):
        pin = node["packet"]
        if pin is None:
            return None
        _keys(pin, {"path", "manifest_sha256"}, "role packet pin")
        path = _safe_path(pin["path"])
        # Enforce the descriptor/manifest byte bound BEFORE any JSON consumption.
        try:
            index = review_context._PacketIndex(path, pin["manifest_sha256"])
            manifest = index.manifest
        except ValueError as exc:
            if str(exc) == "review context manifest changed":
                raise HostFailure("role packet differs from creation digest") from None
            raise HostFailure("role packet manifest custody is invalid: " + str(exc)) from None
        except (OSError, TypeError):
            raise HostFailure("role packet manifest custody is invalid") from None
        expected = BLIND_ROLES.get(node["role"])
        if expected is not None and manifest.get("role") != expected:
            raise HostFailure("review packet role does not match node role")
        # The complete index/copies remain bound; only initial presentation is bounded.
        priority = {"judgment_request", "public_case", "actual_role_judgments", "repair_design"}
        def rank(entry):
            identity = entry["id"]
            source = entry.get("source_path", "")
            return (0 if identity in priority else 1 if identity.startswith("anchor") else
                    2 if "/outputs/" in source or "/logs/" in source else 3, identity)
        inline, catalogue, binary_witnesses = {}, [], []
        total, bounded, text_budget = 0, False, max(0, self.max_request // 4)
        for entry in sorted(index.entries.values(), key=rank):
            try:
                content = index.read(entry)
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("role packet artifact custody is invalid") from None
            try:
                root_stream.model_artifact_source(entry['source_path'],entry['source_sha256'])
                root_stream.model_input_text(content.decode('utf-8'))
            except UnicodeError:
                pass  # Binary/visual artifacts retain their separate source-defined checks.
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('Restricted or unauthenticated site artifacts cannot enter a review packet') from None
            presentation = entry.get("presentation", "inline")
            if presentation not in {"inline", "on_demand"}:
                raise HostFailure("unknown role artifact presentation")
            metadata = review_context._catalogue_entry(entry, content)
            catalogue.append(metadata)
            try:
                text = content.decode("utf-8")
                if metadata["content_encoding"] == "binary": raise UnicodeError("binary byte witness")
            except UnicodeError:
                bounded = True
                if len(binary_witnesses) < 16:
                    binary_witnesses.append({**metadata, "witness": {"kind":"byte_header",
                        "offset":0,"bytes":min(32,len(content)),"hex":content[:32].hex(),
                        "whole_content_presented":False}})
                continue
            cost = len(_json_bytes({"id":entry["id"],"content":text}))
            if presentation == "on_demand": bounded = True
            elif total + cost <= text_budget:
                inline[entry["id"]] = {"id":entry["id"],"source_sha256":entry.get("source_sha256"),
                    "projection":entry.get("projection"),"sha256":entry["sha256"],"content":text}
                total += cost
            else:
                bounded = True
                if entry["id"] in priority:
                    raise HostFailure("exact role request/case needs a bounded declared witness")
        if _observations is not None: _observations.append(index)
        # Only declared public role context, never a raw journal or caller transcript.
        public_manifest = {key: manifest[key] for key in ("role", "cycle_id", "source_event_sha256", "findings",
            "reviews", "allowed_claim_scopes", "required_checks", "omissions", "correction", "verification_scope") if key in manifest}
        if not bounded:
            artifacts = [{k:v for k,v in inline[e["id"]].items() if k != "sha256"} for e in manifest["artifacts"]]
            if _observations is None: index.finish()
            return {"manifest_sha256":pin["manifest_sha256"],"context":public_manifest,"artifacts":artifacts}
        positions = {identity:i for i,identity in enumerate(index.entries)}
        catalogue.sort(key=lambda e: positions[e["id"]])
        binary_count = sum(row["content_encoding"] == "binary" for row in catalogue)
        presentation = {"schema_version":1,"kind":"bounded_indexed_role_evidence",
            "complete_index_sha256":digest(catalogue),"artifact_count":len(catalogue),
            "inline_ids":list(inline),"deferred_count":len(catalogue)-len(inline),
            "binary_count":binary_count,"omission_count":len(manifest.get("omissions",[])),
            "all_indexed_bytes_retained":True,"omissions_preserved_in_manifest":True,"all_content_read_by_model":False,
            "catalogue_page":{"read_action":"review-index","parameters":{
                "section":"artifacts","offset":0,"max_bytes":65536,"query":""}},
            "omission_page":{"read_action":"review-index","parameters":{
                "section":"omissions","offset":0,"max_bytes":65536,"query":""}},
            "artifact_page":{"read_action":"review-read","parameters":{
                "artifact_id":"<indexed ID>","offset":0,"max_bytes":65536}}}
        omissions = manifest.get("omissions", [])
        public_manifest["omissions"] = {"count":len(omissions),"sha256":digest(omissions),
            "preview":omissions[:8],"complete_content_presented":len(omissions)<=8,
            "read_action":"review-index","parameters":{
                "section":"omissions","offset":0,"max_bytes":65536,"query":""}}
        result = {"manifest_sha256":pin["manifest_sha256"],"context":public_manifest,
            "artifacts":list(inline.values()),"presentation":presentation,
            "index_preview":catalogue[:8],"binary_witnesses":binary_witnesses}
        if len(_json_bytes(result)) > self.max_request:
            raise HostFailure("role context metadata/witnesses exceed host byte bound")
        if _observations is None: index.finish()
        return result

    def _context(self, node, request, pins, *, _observations=None):
        packet = self._packet(node, _observations=_observations)
        if node["role"] in BLIND_ROLES and packet is None:
            raise HostFailure("critic and verifier require a matching digest-bound review packet")
        if node["role"] in BLIND_ROLES and self.adapter not in provider_transport.HTTP_ADAPTERS:
            from . import transport_registry
            if self.transport is None or not transport_registry.blind_admissible(self.transport):
                named = self.transport["id"] if self.transport else "an undeclared command transport"
                isolation = self.transport["capabilities"]["isolation"] if self.transport else "none"
                raise HostFailure(f"blind {node['role']} refused: {named} lacks capability blind; no OS sandbox "
                                  f"or RAVEL sandbox (isolation {isolation}) can enforce reviewer blinding")
        context = {"request_id": _text(request.get("request_id"), "request identity", 100), "role": node["role"]}
        if "goal_binding" in request:
            from .task_completion import binding_projection
            parent = binding_projection(request["goal_binding"], base_dir=Path.cwd())
            if request.get("parent_task") != parent: raise HostFailure("parent task projection differs from current assignment")
            context["parent_task"] = parent
        if packet is not None:
            context["review_packet"] = packet
        if node["role"] not in BLIND_ROLES:
            content = []
            total = len(_json_bytes(context))
            for identity, (path, sha) in sorted(pins.items()):
                value, size = _input_text_snapshot(path, sha, self.max_request)
                try:root_stream.model_input_text(value,source_path=path,source_sha256=sha)
                except (OSError,ValueError,KeyError,TypeError):raise HostFailure('Restricted site DATA inputs require the original allowed-model projection') from None
                total += size
                if total > self.max_request:
                    raise HostFailure("aggregate model context exceeds host byte bound")
                content.append({"id": identity, "sha256": sha, "content": value})
            context["input_artifacts"] = content
        return context

    def prepare_model_context(self, node, request):
        """Validate role custody and model parameters, without a transport call."""
        _keys(node, {"id", "kind", "role", "depends_on", "inputs", "packet", "action", "parameters", "max_attempts"}, "graph node")
        if node["kind"] != "model":
            raise HostFailure("model context preparation requires a model node")
        if request.get("packet") != node["packet"]:
            raise HostFailure("host packet pin mismatch")
        pins = self._pins(node, request)
        parameters = node["parameters"]
        _keys(parameters, MODEL_KEYS | {k for k in ("visual_sources", "completion_limits") if k in parameters}, "model parameters")
        completion_limits(parameters)
        if "visual_sources" in parameters:
            try:
                visual_presentation.sources(parameters["visual_sources"])
            except visual_presentation.VisualFailure as exc:
                raise HostFailure(str(exc)) from None
        for key in ("instructions", "model", "reasoning_effort"):
            _text(parameters[key], key)
        _integer(parameters["max_output_tokens"], "model output token bound", 16)
        schema = parameters["output_schema"]
        if schema is not None:
            _schema(schema)
            if schema["type"] != "object":
                raise HostFailure("public model output schema must have object root")
        observations = []
        prepared = {"context": self._context(node, request, pins, _observations=observations), "parameters": _loads(_json_bytes(parameters))}
        if len(_json_bytes(prepared)) > self.max_request:
            raise HostFailure("prepared model context exceeds host byte bound")
        for index in observations: index.finish()
        return prepared

    def execute(self, node, request, control):
        self._cancel(control)
        _keys(node, {"id", "kind", "role", "depends_on", "inputs", "packet", "action", "parameters", "max_attempts"}, "graph node")
        if request.get("packet") != node["packet"]:
            raise HostFailure("host packet pin mismatch")
        pins = self._pins(node, request)
        if node["kind"] == "tool":
            return self._tool(node, request, control, pins)
        if node["kind"] != "model" or node["action"] not in {self.adapter, "model"}:
            raise HostFailure("model node action differs from configured executable adapter")
        declared_run, declared = self._declared_instructions(control)
        if declared is not None and self.wrapper_agent is None:
            # Only the RAVEL agent-cli launcher delivers the document and records it; nothing is sent otherwise.
            raise HostFailure("this run pins a project instruction document and this host adapter cannot deliver it; "
                              "no request was sent. Run the node through an agent-cli host")
        from . import provider_policy
        try:
            admission = provider_transport.admit(self, getattr(control, 'root', None), request.get('input_artifacts', []))
        except provider_policy.PolicyRefused as exc:
            raise HostFailure(str(exc)) from None
        request = {**request, 'provider_policy_admission': admission}
        prepared = self.prepare_model_context(node, request)
        parameters = prepared["parameters"]
        maximum = parameters["max_output_tokens"]
        schema = parameters["output_schema"]
        context = prepared["context"]
        if self.privacy == "local_only" and parameters["model"] not in self.local_models:
            raise HostFailure("requested model is outside the exact local-only model allowlist")
        try:
            visuals = visual_presentation.prepare_visuals(node["packet"], parameters.get("visual_sources", []),
                self.vision, parameters["model"], bound_roots=self.bound_roots)
        except (visual_presentation.VisualFailure, OSError) as exc:
            raise HostFailure(str(exc)) from None
        control = provider_transport.audit_control(control, node)
        if self.adapter == "responses":
            body = {"model": parameters["model"], "reasoning": {"effort": parameters["reasoning_effort"]},
                    "instructions": "Return only public JSON claims, evidence and concise public rationales. Do not return private reasoning traces.\n" + parameters["instructions"],
                    "input": [{"role": "user", "content": _json_bytes(context).decode()}],
                    "max_output_tokens": maximum, "store": False, "stream": False, "tools": []}
            if schema is not None:
                wire_schema = _responses_output_schema(schema)
                if wire_schema is not schema:
                    body["instructions"] += "\nThe wire format wraps the entire requested public JSON record in exactly one public_record field; preserve all original conditional constraints inside it."
                body["text"] = {"format": {"type": "json_schema", "name": "public_record", "strict": True, "schema": wire_schema}}
            else:
                body["text"] = {"format": {"type": "json_object"}}
            body = visual_presentation.attach_images(body, self.adapter, visuals)
            data = _json_bytes(body)
            if len(data) > self.max_request:
                raise HostFailure("Responses request exceeds host byte bound")
            if visuals is not None: visuals.check()
            result = control.call("responses", "model", body,
                                  lambda: self._visual_result(self._responses(data, parameters, request, control), context, visuals, body, node, request), output_tokens=maximum)
        elif self.adapter in provider_transport.HTTP_ADAPTERS:
            try:
                body, path = provider_transport.request(self.adapter, parameters, _json_bytes(context).decode(),
                    _responses_output_schema(schema) if schema is not None else None,
                    self.capabilities, self.endpoint, self.privacy, self.local_models)
            except provider_transport.ProviderFailure as exc:
                raise HostFailure(str(exc)) from None
            body = visual_presentation.attach_images(body, self.adapter, visuals)
            data = _json_bytes(body)
            if len(data) > self.max_request or (visuals is not None and len(data) > self.capabilities["max_context_bytes"]):
                raise HostFailure("provider request exceeds complete host/capability byte bound")
            if visuals is not None: visuals.check()
            result = control.call(self.adapter, "model", body,
                lambda: self._visual_result(self._responses(data, parameters, request, control, path=path), context, visuals, body, node, request),
                output_tokens=maximum)
        else:
            # The command wrapper alone needs the run location; it strips it before any prompt.
            carried = ({**context, 'provider_policy_run': str(provider_policy.find_run(control.root))}
                       if admission['declared'] and getattr(control, 'root', None) is not None else context)
            body = {"schema_version": 1, "request_id": request["request_id"], "parameters": parameters, "context": carried}
            if "role_requires" in request:
                body["role_requires"] = request["role_requires"]
            if declared is not None:
                # The launcher reads the run from the request; the request digest in its receipt binds it.
                body["project_run"] = str(declared_run)
            data = _json_bytes(body)
            if len(data) > self.max_request:
                raise HostFailure("command request exceeds host byte bound")
            result = control.call("command", "model", body,
                                  lambda: self._presented_result(self._command(data, parameters, request, control), context), output_tokens=maximum)
        self._cancel(control, sent=True)
        return result

    def _declared_instructions(self, control):
        """``(run, pin)`` of the project instruction document this graph's model sessions receive, else ``(None, None)``.

        The run is the one that owns the graph (``project_instructions.owning_run``). An agent-cli host
        configured with ``rundir`` names the run: it supplies the run for a graph that lies in no run and
        settles a graph whose own run pins nothing under a tree that pins a document. A configured run
        that differs from the graph's own run is refused.
        """
        from . import project_instructions
        root = getattr(control, "root", None)
        configured = None
        if self.wrapper_agent is not None and "--rundir" in self.command:
            configured = os.path.realpath(self.command[self.command.index("--rundir") + 1])
        try:
            if configured is not None:
                run = project_instructions.nearest_run(root) if root is not None else None
                if run is not None and str(run) != configured:
                    raise HostFailure(f"this host is configured for run {configured} and the graph belongs to run {run}; "
                                      "one session receives one run's project instruction document")
                run = Path(configured)
            else:
                run = project_instructions.owning_run(root) if root is not None else None
            pinned = project_instructions.for_run(run) if run is not None else None
        except project_instructions.ProjectInstructionsError as exc:
            raise HostFailure(str(exc)) from None
        return (run, pinned) if pinned is not None else (None, None)

    def _visual_result(self, result, context, visuals, body, node, request):
        try:
            result = visual_presentation.completed_presentation(result, visuals, body, node, request)
        except (visual_presentation.VisualFailure, OSError) as exc:
            raise HostFailure(str(exc), ambiguous=True) from None
        if visuals is not None:
            result["transport"]["vision"] = self.vision
        return self._presented_result(result, context)

    @staticmethod
    def _presented_result(result, context):
        packet = context.get("review_packet")
        if packet is not None:
            result = dict(result)
            result["isolation"] = dict(result["isolation"])
            result["isolation"]["evidence_presentation"] = {
                "manifest_sha256":packet["manifest_sha256"],
                "context_sha256":digest(context),
                "presented_subject_sha256s":sorted({hashlib.sha256(e["content"].encode()).hexdigest()
                    for e in (*packet["artifacts"], *context.get("input_artifacts", []))}),
                "presentation":packet.get("presentation", {
                    "schema_version":1,"kind":"complete_inline_role_evidence",
                    "artifact_count":len(packet["artifacts"]),
                    "inline_ids":[e["id"] for e in packet["artifacts"]],
                    "deferred_count":0,"all_content_presented":True,
                    "all_content_read_by_model":False}),"deferred_content_read":False}
        return result

    def _result(self, value, parameters, request, *, observed_model=None, response_id=None, usage=None, provider_usage=None):
        value = validate_completion_value(value, parameters)
        usage = _usage(usage)
        if usage["output_tokens"] is not None and usage["output_tokens"] > parameters["max_output_tokens"]:
            raise HostFailure("provider output token usage exceeds declared bound")
        return {"kind": "model_result", "value": value, "usage": usage,
                "transport": {"adapter": self.adapter, "request_id": request["request_id"],
                    **({'provider_policy': request['provider_policy_admission']} if 'provider_policy_admission' in request else {}),
                    "requested_model": parameters["model"], "observed_model": observed_model,
                    "reasoning_effort": parameters["reasoning_effort"], "response_id": response_id,
                    "endpoint_origin": f"{self.endpoint.scheme}://{self.endpoint.netloc}" if self.adapter in provider_transport.HTTP_ADAPTERS else None,
                    "execution_mode": ("provider_http_local" if self.privacy == "local_only" else
                        "responses_http_loopback_control" if self.endpoint.scheme == "http" else
                        "responses_http" if self.adapter == "responses" else "provider_http")
                        if self.adapter in provider_transport.HTTP_ADAPTERS else "trusted_command_json",
                    "privacy": self.privacy, "local_models": list(self.local_models),
                    "server_egress_confined": False, "capabilities": self.capabilities,
                    "reasoning_effort_transmitted": self.adapter == "responses" or bool(self.capabilities and self.capabilities["reasoning_efforts"]),
                    "provider_usage": provider_usage,
                    "context_manifest_sha256": request["packet"]["manifest_sha256"] if request.get("packet") else None,
                    "remote_cancellation_supported": False},
                "isolation": {"fresh_request": True, "parent_transcript_supplied": False,
                    "model_tools_supplied": False, "structured_return_function_supplied": self.adapter in {"anthropic", "gemini"} or
                        bool(self.capabilities and self.capabilities["output_mode"] == "tool_call"), "os_sandbox": False,
                    "limitation": "Trusted command can access the local filesystem" if self.adapter == "command" else
                        "Only the supplied stateless context is sent; remote generation cannot be canceled by this adapter"},
                "public_output_only": True, "execution_authorized": False, "physics_validated": False}

    def _responses(self, data, parameters, request, control, *, path=None):
        self._cancel(control)
        key = self._api_key
        if self.auth is not None and self.auth["kind"] == "command":
            try:
                key = provider_transport.run_token_command(self.auth["command"], timeout=min(self.timeout, 60))
            except provider_transport.ProviderFailure as exc:
                raise HostFailure(str(exc)) from None
        if self.endpoint.scheme == "https" and not key and self.privacy != "local_only" and \
                not (self.auth is not None and self.auth["kind"] == "none"):
            raise HostFailure("Responses API key is unavailable in the selected environment name")
        headers = provider_transport.headers(self.adapter, key, self.auth["header_style"] if self.auth else None)
        del key
        cls = http.client.HTTPSConnection if self.endpoint.scheme == "https" else http.client.HTTPConnection
        # A loopback control must not depend on an ambient localhost DNS alias.
        hostname = "127.0.0.1" if self.endpoint.hostname == "localhost" else self.endpoint.hostname
        connection = cls(hostname, self.endpoint.port, timeout=self.timeout)
        sent = False
        stopped, expired = threading.Event(), threading.Event()
        connection_ready, connection_failed, abandoned = threading.Event(), threading.Event(), threading.Event()
        deadline = time.monotonic() + self.timeout
        response = None
        active_socket = None
        def connect_only():
            # Resolver/TLS calls can outlive socket idle timeouts. This fenced
            # worker may only connect; it can never send the model request.
            try:
                connection.connect()
            except Exception:
                connection_failed.set()
            finally:
                if abandoned.is_set():
                    connection.close()
                connection_ready.set()
        def deadline_watch():
            # Socket timeouts alone are idle deadlines and can be defeated by a
            # peer trickling bytes. Enforce the whole-call wall deadline as well.
            while not stopped.wait(min(.02, max(0, deadline - time.monotonic()))):
                if time.monotonic() < deadline and not control.cancelled():
                    continue
                if time.monotonic() >= deadline:
                    expired.set()
                sock = active_socket
                if sock is not None:
                    try:
                        import socket
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return
        watcher = threading.Thread(target=deadline_watch, daemon=True)
        watcher.start()
        connector = threading.Thread(target=connect_only, daemon=True)
        connector.start()
        try:
            # Direct stdlib connection: no automatic redirects, proxy lookup or retries.
            while not connection_ready.wait(min(.02, max(0, deadline - time.monotonic()))):
                self._cancel(control)
                if expired.is_set() or time.monotonic() >= deadline:
                    raise HostFailure("Responses deadline exceeded before dispatch")
            if connection_failed.is_set():
                raise HostFailure("Responses transport unavailable before dispatch")
            active_socket = connection.sock
            if expired.is_set():
                raise HostFailure("Responses deadline exceeded before dispatch")
            self._cancel(control)
            sent = True
            connection.request("POST", path or self.endpoint.path, body=data, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                # Never retain error bodies, headers or reason phrases.
                raise HostFailure(f"Responses endpoint returned HTTP {response.status}",
                                  retryable=response.status == 429, ambiguous=response.status >= 500)
            raw = response.read(self.max_response + 1)
            if expired.is_set():
                raise HostFailure("Responses deadline exceeded after dispatch", ambiguous=True)
            if len(raw) > self.max_response:
                raise HostFailure("Responses body exceeds host byte bound", ambiguous=True)
            self._cancel(control, sent=True)
            document = _loads(raw)
            if self.adapter != "responses":
                try:
                    value, model, identity, usage, details = provider_transport.response(self.adapter, document, self.capabilities, _loads)
                except provider_transport.ProviderFailure as exc:
                    raise HostFailure(str(exc)) from None
                return self._result(_responses_public_value(value, parameters["output_schema"]), parameters, request,
                    observed_model=model, response_id=identity, usage=usage, provider_usage=details)
            if type(document) is not dict or document.get("status") != "completed" or type(document.get("output")) is not list:
                raise HostFailure("Responses result is not a completed public message")
            messages = []
            for item in document["output"]:
                if type(item) is not dict:
                    raise HostFailure("invalid Responses output item")
                if item.get("type") == "reasoning":
                    continue  # Discard summaries, encrypted content and every reasoning field.
                if item.get("type") != "message" or item.get("role") != "assistant" or type(item.get("content")) is not list:
                    raise HostFailure("Responses output contains an unsupported public item")
                if item.get("status", "completed") != "completed":
                    raise HostFailure("Responses public message is incomplete")
                text = []
                for part in item["content"]:
                    if type(part) is not dict or part.get("type") != "output_text" or type(part.get("text")) is not str:
                        raise HostFailure("Responses public message contains refusal or unsupported content")
                    text.append(part["text"])
                messages.append("".join(text))
            if len(messages) != 1:
                raise HostFailure("Responses result requires one public assistant message")
            model = _text(document.get("model"), "observed model", 200)
            identity = _text(document.get("id"), "response identity", 200)
            return self._result(_responses_public_value(_loads(messages[0]), parameters["output_schema"]), parameters, request, observed_model=model,
                                response_id=identity, usage=document.get("usage"))
        except HostFailure:
            raise
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            if control.cancelled():
                raise HostFailure("host call canceled; remote completion is unknown", ambiguous=sent) from None
            raise HostFailure("Responses transport failed after dispatch" if sent else "Responses transport unavailable before dispatch",
                              ambiguous=sent) from None
        finally:
            abandoned.set()
            stopped.set()
            if response is not None:
                response.close()
            connection.close()
            watcher.join(timeout=.1)
            connector.join(timeout=.02)

    @staticmethod
    def _cleanup(proc):
        for sig, grace in ((signal.SIGTERM, 0.2), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                pass
            except OSError:
                return False
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                continue
            # Escaped sessions are outside this adapter's non-sandbox boundary.
            try:
                if not process_group_members(proc.pid):
                    return True
            except (OSError, subprocess.SubprocessError):
                return False
        return False

    def _command(self, data, parameters, request, control):
        self._cancel(control)
        from . import cli_agent_host
        self.wrapper_agent = cli_agent_host.wrapper_agent(self.command, self.environment)
        self._bind_transport()  # the label must still describe the command about to run
        with tempfile.TemporaryDirectory(prefix="ravel-agent-host-") as cwd:
            # Terminate/reap the process group before removing its working tree.
            return self._command_process(data, parameters, request, control, cwd)

    def _command_process(self, data, parameters, request, control, cwd):
        proc = None
        try:
            environment = {**self.environment, **{n: os.environ[n] for n in self.pass_env if n in os.environ}}
            proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=cwd, env=environment, start_new_session=True)
            deadline, pending, output, stderr_size = time.monotonic() + self.timeout, memoryview(data), bytearray(), 0
            with selectors.DefaultSelector() as selector:
                for stream, event, name in ((proc.stdin, selectors.EVENT_WRITE, "in"), (proc.stdout, selectors.EVENT_READ, "out"),
                                             (proc.stderr, selectors.EVENT_READ, "err")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, event, name)
                while selector.get_map():
                    self._cancel(control, sent=True)
                    if time.monotonic() >= deadline:
                        raise HostFailure("command deadline exceeded; effect is unknown", ambiguous=True)
                    for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                        if key.data == "in":
                            try:
                                count = os.write(key.fd, pending[:65536])
                                pending = pending[count:]
                            except BrokenPipeError:
                                pending = memoryview(b"")
                            if not pending:
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                            continue
                        content = os.read(key.fd, 65536)
                        if not content:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        elif key.data == "out":
                            output.extend(content)
                        else:
                            stderr_size += len(content)  # Error content is never retained.
                        if len(output) > self.max_response or stderr_size > self.max_response:
                            raise HostFailure("command output exceeds host byte bound", ambiguous=True)
            while proc.poll() is None:
                self._cancel(control, sent=True)
                if time.monotonic() >= deadline:
                    raise HostFailure("command deadline exceeded; effect is unknown", ambiguous=True)
                time.sleep(.02)
            if proc.returncode:
                raise HostFailure("command returned a nonzero exit", ambiguous=True)
            if process_group_members(proc.pid):
                raise HostFailure("command descendants remained active", ambiguous=True)
            self._cancel(control, sent=True)
            document = _loads(output)
            optional = {"observed_model", "isolation", "session_receipt"}
            _keys(document, {"request_id", "value", "usage"} | ({k for k in optional if k in document} if type(document) is dict else set()), "command result")
            if document["request_id"] != request["request_id"]:
                raise HostFailure("command response identity does not match request")
            observed = document.get("observed_model")
            if observed is not None:
                _text(observed, "command observed model", 256)
            result = self._result(document["value"], parameters, request, usage=document["usage"], observed_model=observed)
            result["isolation"]["independent"] = False
            result["transport"]["attestation"] = "self_attested"
            if "isolation" in document:
                # Printed by the child: a claim, never the host's verdict.
                evidence = _transport_isolation(document["isolation"])
                if self.transport is not None and evidence["transport_id"] != self.transport["id"]:
                    raise HostFailure(f"command evidence names transport {evidence['transport_id']}; "
                                      f"this host runs {self.transport['id']}")
                result["isolation"]["child_claims"] = evidence
            if "session_receipt" in document:
                self._session_receipt(document, data, result, request, control, proc, output)
            return result
        except HostFailure:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise HostFailure("command transport failed", ambiguous=proc is not None) from None
        finally:
            if proc is not None:
                clean = self._cleanup(proc)
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
                if not clean:
                    raise HostFailure("command process-group cleanup could not be confirmed", ambiguous=True)

    def _session_receipt(self, document, data, result, request, control, proc, output):
        """Verify the launcher's receipt against this host, compute attestation by rule and record both.

        Only the RAVEL agent-cli launcher, run by this host for its own declaration, writes a receipt
        this host accepts. The record is written create-only under the graph and kept in the result.
        """
        from . import cli_agent_host, transport_receipt
        receipt = document["session_receipt"]
        if self.wrapper_agent is None:
            result["isolation"]["child_claims_sha256"] = digest(receipt)
            return
        try:
            transport_receipt.shape(receipt)
        except transport_receipt.ReceiptError as exc:
            raise HostFailure(f"launcher receipt is malformed: {exc}") from None
        writer = cli_agent_host.module_sha256()
        verification = transport_receipt.verify(receipt, declaration=self.transport,
            request_sha256=hashlib.sha256(bytes(data)).hexdigest(), value=document["value"], writer_sha256=writer)
        identity = [r for r in verification if "differs" in r]
        if identity:
            raise HostFailure("launcher receipt does not match this host's launch: " + "; ".join(identity))
        root, attempt = getattr(control, "root", None), getattr(control, "attempt_id", None)
        others = transport_receipt.session_ids(root) if root is not None else set()
        tools_required = request.get("role_requires", {}).get("tools", "none")
        if receipt["configuration"].get("tools_required", "none") != tools_required:
            raise HostFailure("launcher receipt tools_required differs from the request")
        label, reasons = transport_receipt.attestation(receipt, verification=verification,
            other_session_ids=others, tools_required=tools_required)
        record = {"schema_version": 1, "kind": "transport-session-record", "request_id": request["request_id"],
                  "attempt_id": attempt,
                  "host_observed": {"command_sha256": digest(list(self.command)), "wrapper_module_sha256": writer,
                                    "wrapper_pid": proc.pid, "wrapper_exit_status": proc.returncode,
                                    "request_sha256": hashlib.sha256(bytes(data)).hexdigest(),
                                    "stdout_sha256": hashlib.sha256(bytes(output)).hexdigest()},
                  "launcher_receipt": receipt, "verification": verification,
                  "attestation": label, "attestation_reasons": reasons}
        pin = transport_receipt.write(root, request["request_id"], attempt or "unbound", record) if root is not None else None
        from . import project_instructions
        declared = self._declared_instructions(control)[1]
        if pin is not None:
            # The exact prompt stays beside the session record: rebuilt from this request and kept only
            # when it hashes to the prompt digest in the launcher's receipt.
            # A request this host did not shape as {parameters, context} has no prompt to rebuild.
            try:
                body = _loads(bytes(data))
                prompt = cli_agent_host.session_prompt(receipt, body["parameters"], body["context"], declared)
            except (KeyError, TypeError, ValueError):
                prompt = None
            if prompt is not None:
                transport_receipt.write_prompt(Path(root) / pin["path"], prompt, receipt)
        problem = project_instructions.receipt_problem(receipt, declared)
        if problem is not None:
            # The session record stays on file; a session that was not shown the pinned document earns no credit.
            raise HostFailure("launcher receipt does not show the run's pinned project instruction document "
                              f"({problem}); the session is not credited")
        configuration = receipt["configuration"]
        loaded = configuration["user_configuration_loaded"]
        result["transport"].update(attestation=label, session_receipt=record, session_receipt_pin=pin,
                                   cli_session_id=receipt["cli_reported"]["session_id"],
                                   execution_mode="transport_attested_cli" if label == "transport_attested" else "trusted_command_json")
        result["isolation"].update(fresh_request=not loaded, user_configuration_loaded=loaded,
                                   independent=label == "transport_attested", model_tools_supplied=configuration["effective_tools"] != "none",
                                   transport_evidence=cli_agent_host.legacy_isolation(receipt))

    def _tool(self, node, request, control, pins):
        action, parameters = node["action"], node["parameters"]
        if action == 'intake-plan':
            from . import intake_planner
            if node['role'] != 'executor' or node['max_attempts'] != 1:
                raise HostFailure('intake preparation requires one exact bounded executor tool')
            _keys(parameters, {'request_input', 'graph_root', 'output_dir'}, 'intake planner parameters')
            identity = parameters['request_input']
            if identity not in pins or _safe_path(parameters['graph_root']) != _safe_path(control.root):
                raise HostFailure('intake planner must consume this actual Graph and its request input')
            path, sha = pins[identity]
            destination = _safe_path(parameters['output_dir'])
            if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('intake preparation output outside configured Host roots')
            request_pin = {'path': str(path), 'sha256': sha, 'size': path.stat().st_size}
            operation = lambda: intake_planner.materialize(request_pin, parameters['graph_root'], destination,
                base_dir=path.parent, presented_pins=request['input_artifacts'])
        elif action == 'research-open-prepare':
            from . import research_orchestrator
            if node['role']!='executor' or node['max_attempts']!=1:
                raise HostFailure('open research preparation requires one bounded executor tool')
            _keys(parameters,{'request_input','output_dir'},'open research preparation')
            destination=_safe_path(parameters['output_dir'])
            if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('open research preparation outside configured Host roots')
            operation=lambda:research_orchestrator.host_prepare(parameters,pins)
        elif action == 'literature-acquire':
            from . import literature_context
            if node['role'] != 'executor' or node['max_attempts'] != 1:
                raise HostFailure('acquisition requires one ordinary bounded executor tool')
            _keys(parameters, {'request_input','output_dir'}, 'literature acquisition parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('acquisition request must be an explicit Graph input')
            path,sha=pins[identity];destination=_safe_path(parameters['output_dir'])
            if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('acquisition output outside configured Host roots')
            request_pin={'path':str(path),'sha256':sha,'size':path.stat().st_size}
            for dependency in literature_context.acquisition_inputs(request_pin,base_dir=path.parent):
                if not any(str(p)==dependency['path'] and s==dependency['sha256'] for p,s in pins.values()):
                    raise HostFailure('complete acquisition request/helper absent from Graph inputs')
            settings=literature_context._Reader(path.parent).document(request_pin)[1]
            if settings['max_seconds'] > self.timeout:
                raise HostFailure('acquisition exceeds configured ordinary Host timeout')
            operation=lambda:literature_context.acquire(request_pin,destination,base_dir=path.parent,
                configured_origins=self.literature_origins,privacy=self.privacy)
        elif action == 'literature-pdf-extract':
            from . import literature_context
            if node['role'] != 'executor' or node['max_attempts'] != 1:
                raise HostFailure('PDF extraction requires one ordinary bounded executor tool')
            _keys(parameters, {'request_input','output_dir'}, 'literature PDF parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('PDF extraction request must be an explicit Graph input')
            path,sha=pins[identity];destination=_safe_path(parameters['output_dir'])
            if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('PDF extraction output outside configured Host roots')
            request_pin={'path':str(path),'sha256':sha,'size':path.stat().st_size}
            for dependency in literature_context.pdf_inputs(request_pin,base_dir=path.parent):
                if not any(str(p)==dependency['path'] and s==dependency['sha256'] for p,s in pins.values()):
                    raise HostFailure('complete original PDF/extractor source absent from Graph inputs')
            settings=literature_context._Reader(path.parent).document(request_pin)[1]
            if settings['max_seconds'] > self.timeout:
                raise HostFailure('PDF extraction exceeds configured ordinary Host timeout')
            operation=lambda:literature_context.extract_pdf(request_pin,destination,base_dir=path.parent)
        elif action == 'response-recipes':
            from ravel.physics.source_calibration import recipes
            if node['role'] not in {'designer', 'executor', 'proposer'} or node['max_attempts'] != 1:
                raise HostFailure('response preparation requires one-attempt construction caller')
            _keys(parameters, {'request_input', 'output_dir'}, 'response preparation parameters')
            identity = parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('response request must be an ordinary Graph input')
            path, sha = pins[identity]
            destination = _safe_path(parameters['output_dir'])
            if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                raise HostFailure('response output outside configured Host roots')
            try:
                allowed = {p: h for p, h in pins.values()}
                for dependency in recipes.input_pins(path, expected_sha256=sha):
                    if allowed.get(_safe_path(dependency['path'])) != dependency['sha256']:
                        raise ValueError('every response source/configuration/population input must be presented')
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure('response source/input custody refused') from None
            operation = lambda: recipes.prepare(path, destination, expected_sha256=sha)
        elif action == 'mssm-spectrum-context':
            from ravel.physics import mssm_observable_map
            if node['role'] not in {'designer','executor','proposer'} or node['max_attempts'] != 1:
                raise HostFailure('MSSM map context requires one-attempt construction caller')
            _keys(parameters, {'request_input'}, 'MSSM spectrum context parameters')
            identity = parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('MSSM request must be an ordinary Graph input')
            path, sha = pins[identity]
            mssm_observable_map.slha.raw_file(path,sha)
            task = {'request':str(path)}
            required = mssm_observable_map.inputs(task,path.parent)
            presented = {str(Path(p['path']).resolve()):p['sha256'] for p in request['input_artifacts']}
            if any(presented.get(str(p)) != file_hash(p) for p in required):
                raise HostFailure('complete MSSM grid/card/provider/decay/source inputs must be presented')
            operation = lambda:mssm_observable_map.context(task,path.parent)
        elif action == 'nmssm-yukawa-context':
            from ravel.physics import nmssm_yukawa_map
            if node['role'] not in {'designer', 'executor', 'proposer'} or node['max_attempts'] != 1:
                raise HostFailure('finite model convention context requires a one-attempt construction caller')
            _keys(parameters, {'request_input'}, 'NMSSM convention context parameters')
            identity = parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('convention request must be an ordinary Graph input')
            path, sha = pins[identity]
            nmssm_yukawa_map.named.raw_file(path, sha)
            task = {'request': str(path)}
            required = nmssm_yukawa_map.inputs(task, path.parent)
            presented = {str(Path(p['path']).resolve()): p['sha256'] for p in request['input_artifacts']}
            if any(presented.get(str(p)) != file_hash(p) for p in required):
                raise HostFailure('complete spectrum/card/equation/accepted-origin inputs must be presented')
            operation = lambda: nmssm_yukawa_map.context(task, path.parent)
        elif action == 'model-spectrum-plan':
            from . import model_spectrum_plan
            if node['role'] not in {'designer','executor','proposer'} or node['max_attempts'] != 1:
                raise HostFailure('named spectrum preparation requires a separate one-attempt caller')
            _keys(parameters, {'request_input','output_dir'}, 'named spectrum preparation parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('named spectrum request must be an ordinary Graph input')
            path,sha=pins[identity]
            raw=model_spectrum_plan.named.raw_file(path,sha)
            obj=json.loads(raw)
            method=model_spectrum_plan.host_preparation(obj)
            operation=lambda:method(obj,base_dir=path.parent,output_dir=parameters['output_dir'],presented_pins=request['input_artifacts'])
        elif action == 'model-event-plan':
            from . import model_event_plan
            if node['role'] not in {'designer','executor','proposer'} or node['max_attempts'] != 1:
                raise HostFailure('generation preparation requires a separate one-attempt caller')
            _keys(parameters, {'request_input','output_dir'}, 'generator preparation parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('generator request must be an ordinary Graph input')
            path,sha=pins[identity]
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=sha:
                raise HostFailure('generator request changed during authenticated consumption')
            obj=json.loads(raw)
            operation=lambda:model_event_plan.prepare(obj,base_dir=path.parent,output_dir=parameters['output_dir'],
                                                      presented_pins=request['input_artifacts'])
        elif action == "scientific-judgment":
            if node["role"] not in {"executor", "designer", "proposer"}:
                raise HostFailure("judgment orchestration requires a separate caller, not its reviewer")
            from . import scientific_judgment
            return scientific_judgment.host_tool(parameters, pins)

        elif action == "research-backend":
            from . import research_tools
            if node["role"] != "executor" or node["max_attempts"] != 1:
                raise HostFailure("bounded original-package workflow requires one explicit executor attempt")
            operation = lambda: research_tools.host_backend(parameters, pins, control,
                request["input_artifacts"], self.cosmology_runtime_binding)
        elif action == "research-tools":
            from . import research_tools
            if node["role"] != "designer" or node["max_attempts"] != 1:
                raise HostFailure("task-directed tool materialization requires one designer attempt")
            _keys(parameters, {"bundle_input", "choice_input", "output_dir"}, "research tool parameters")
            _text(parameters["output_dir"], "fresh tool destination", 2048)
            sources = {}
            for key in ("bundle_input", "choice_input"):
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("tool context and choice must be explicit Graph inputs")
                path, sha = pins[identity]
                sources[key] = {"path": str(path), "sha256": sha, "size": path.stat().st_size}
            operation = lambda: research_tools.materialize(sources["bundle_input"], sources["choice_input"],
                base_dir=Path(sources["bundle_input"]["path"]).parent, output_dir=parameters["output_dir"],
                presented_pins=request["input_artifacts"])
        elif action == "research-protocol":
            from . import research_protocol
            if node["role"] in BLIND_ROLES: raise HostFailure("protocol preparation cannot impersonate blinded review")
            _keys(parameters, {"request_input"}, "staged protocol parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins: raise HostFailure("explicit protocol request input required")
            path, sha = pins[identity]
            value = research_protocol._json({"path":str(path),"sha256":sha,"size":path.stat().st_size},path.parent)
            operation = lambda: research_protocol.host_prepare(value, presented_pins=request["input_artifacts"], base_dir=path.parent)
        elif action == "sfitter-review-protocol":
            if node["role"] not in {"executor", "designer", "proposer"}:
                raise HostFailure("SFitter review preparation requires a separate caller, not its reviewer")
            from . import sfitter_review_protocol
            return sfitter_review_protocol.host_tool(parameters, pins)

        elif action == "research-blueprint":
            from . import research_blueprint, research_followup
            if node["role"] != "designer" or node["max_attempts"] != 1:
                raise HostFailure("blueprint materialization requires one explicit designer attempt")
            _keys(parameters, {"request_input", "choice_input", "output_dir"}, "research blueprint parameters")
            _text(parameters["output_dir"], "fresh blueprint destination", 2048)
            sources = {}
            for key in ("request_input", "choice_input"):
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("blueprint and choice must be explicit normal Graph inputs")
                path, sha = pins[identity]
                sources[key] = {"path": str(path), "sha256": sha, "size": path.stat().st_size}
            operation = lambda: research_blueprint.materialize(sources["request_input"], sources["choice_input"],
                base_dir=Path(sources["request_input"]["path"]).parent, output_dir=parameters["output_dir"],
                presented_pins=request["input_artifacts"])
        elif action == "research-portfolio":
            from . import research_followup
            if node["role"] != "designer": raise HostFailure("rival portfolio requires an explicit designer role")
            _keys(parameters, {"proposal_input", "context_input"}, "research portfolio parameters")
            locations, objects = {}, {}
            for key, identity in parameters.items():
                if type(identity) is not str or identity not in pins: raise HostFailure("portfolio requires explicit bound inputs")
                path, sha = pins[identity]
                pin = {"path": str(path), "sha256": sha, "size": path.stat().st_size}
                locations[key] = path
                objects[key] = research_followup._json(pin, path.parent)
            context_path = locations["context_input"]
            context_pin = {"path": str(context_path), "sha256": pins[parameters["context_input"]][1],
                           "size": context_path.stat().st_size}
            from . import research_blueprint
            operation = lambda: research_blueprint.bound_portfolio(objects["proposal_input"], objects["context_input"],
                proposal_base=locations["proposal_input"].parent, context_pin=context_pin,
                presented_pins=request["input_artifacts"])
        elif action == "capability-routing":
            from . import capability_routing
            if node["role"] in BLIND_ROLES:
                raise HostFailure("capability planning must not receive a blinded review role")
            _keys(parameters, {"request_input"}, "capability routing parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("capability request must be an explicit graph input")
            path, sha = pins[identity]
            value = read_json(path)
            if file_hash(path) != sha:
                raise HostFailure("capability request changed during read")
            _keys(value, {"prompt", "intents", "findings"}, "capability request")
            allowed = {str(location): checksum for location, checksum in pins.values()}
            for finding in value["findings"]:
                for pin in finding.get("evidence", []):
                    if allowed.get(pin.get("path")) != pin.get("sha256"):
                        raise HostFailure("every recovery finding source must be an explicit graph input")
            operation = lambda: capability_routing.plan(value["prompt"], intents=value["intents"], findings=value["findings"])
        elif action == "research-revision":
            from . import research_cycle
            if node["role"] != "improver": raise HostFailure("constructive revision requires an explicit improver role")
            _keys(parameters, {"proposal_input", "feedback_input"}, "research revision parameters")
            locations, objects = {}, {}
            for key, identity in parameters.items():
                if type(identity) is not str or identity not in pins: raise HostFailure("revision requires explicit bound inputs")
                path, sha = pins[identity]
                locations[key] = path
                objects[key] = read_json(path)
                if file_hash(path) != sha: raise HostFailure("revision input changed during read")
            feedback_path = locations["feedback_input"]
            operation = lambda: research_cycle.bound_revision(objects["proposal_input"], objects["feedback_input"],
                proposal_base=locations["proposal_input"].parent, feedback_pin=research_cycle._pin(feedback_path),
                presented_pins=request["input_artifacts"])
        elif action == "model-inputs":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("model inventory must not receive a blinded review role")
            _keys(parameters, {"slha_input", "completeness_input"}, "Ravel tool parameters")
            sources = {}
            for key in parameters:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("model preflight source and completeness manifest must be explicitly hash-bound")
                sources[key] = pins[identity]
            slha_path, slha_sha = sources["slha_input"]
            complete_path, complete_sha = sources["completeness_input"]
            manifest = read_json(complete_path)
            if file_hash(complete_path) != complete_sha:
                raise HostFailure("model completeness manifest changed during read")
            operation = lambda: model_inputs.audit_slha_file(slha_path, expected_sha256=slha_sha,
                                                            completeness_manifest=manifest)
        elif action == "grounded-allocator":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("grounded planning must not receive a blinded review role")
            _keys(parameters, {"case_input", "affordances_input"}, "Ravel tool parameters")
            objects = {}
            for key in parameters:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("grounded allocation inputs must be explicitly hash-bound")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("grounded allocation input changed during read")
            case, affordances = objects["case_input"], objects["affordances_input"]
            base = pins[parameters["affordances_input"]][0].parent
            allowed = {p: checksum for p, checksum in pins.values()}
            try:
                # Embedded source citations must be graph inputs, so resume also
                # checks their identity; a manifest alone cannot hide dependencies.
                for prerequisite in affordances["prerequisites"]:
                    for evidence in prerequisite["evidence"]:
                        source = _safe_path(base / evidence["path"])
                        if (source not in allowed or allowed[source] != evidence["sha256"]
                                or file_hash(source) != allowed[source]):
                            raise HostFailure("grounded prerequisite evidence must match an explicitly hash-bound input")
                research_transfer.assess(case, affordances, base_dir=base)
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("grounded allocation rejected its prerequisite specification") from None
            operation = lambda: research_transfer.recommend(case, affordances, base_dir=base)
        elif action in {"manuscript-author-prepare", "manuscript-source-prepare"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("author preparation cannot impersonate a blinded reviewer")
            _keys(parameters, {"request_input", "out"}|({"campaign"} if action=="manuscript-author-prepare" else set()), "manuscript author preparation")
            identity = parameters["request_input"]
            if identity not in pins: raise HostFailure("explicit original-task author request input required")
            path, sha = pins[identity]; request_document = read_json(path)
            if file_hash(path) != sha: raise HostFailure("author request changed")
            allowed = {p:s for p,s in pins.values()}
            try:
                for pin in manuscript_production.input_pins(request_document, base_dir=path.parent):
                    p = _safe_path(Path(pin["path"]))
                    if p not in allowed or allowed[p] != pin["sha256"] or file_hash(p) != pin["sha256"]:
                        raise ValueError("complete author source/quantity/model/environment inputs required")
            except (ValueError, OSError, KeyError, TypeError):
                raise HostFailure("author source context is incomplete or changed") from None
            # Creates a pending Graph only. Its eventual model call is separately
            # charged by research_cycle.execute_graph outside this tool/lock.
            if action=="manuscript-source-prepare":
                operation=lambda: manuscript_production.prepare_source_review(request_document,parameters["out"],base_dir=path.parent)
            else:
                operation = lambda: manuscript_production.prepare_writer(request_document, parameters["out"],
                    base_dir=path.parent, campaign=parameters["campaign"])
        elif action in {"manuscript-integrity", "manuscript-assess", "scientific-manuscript"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("manuscript preparation/intake is a separate caller, not a blinded scientific reviewer")
            fields = {"request_input"}
            if action != "manuscript-integrity": fields.add("bindings_input")
            if action == "scientific-manuscript": fields.add("final")
            _keys(parameters, fields, "Ravel manuscript tool parameters")
            objects, locations = {}, {}
            for key in fields - {"final"}:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("manuscript request and actual role bindings must be explicit inputs")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha: raise HostFailure("manuscript input changed during read")
                locations[key] = path
            base = locations["request_input"].parent
            specification = objects["request_input"]
            bindings = objects.get("bindings_input", [])
            allowed = {path:sha for path,sha in pins.values()}
            try:
                dependencies = (report_integrity.input_pins(specification, base_dir=base) if action == "manuscript-integrity"
                    else report_integrity.assessment_pins(specification, bindings, base_dir=base))
                for pin in dependencies:
                    raw = Path(pin["path"]); path = _safe_path(raw if raw.is_absolute() else base/raw)
                    if path not in allowed or allowed[path] != pin["sha256"] or file_hash(path) != pin["sha256"]:
                        raise ValueError("manuscript, complete source/result census and review custody must be explicit graph inputs")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("manuscript rejected missing/changed source or actual independent review custody") from None
            if action == "manuscript-integrity":
                operation = lambda: report_integrity.prepare(specification, base_dir=base)
            elif action == "manuscript-assess":
                operation = lambda: report_integrity.assess(specification, bindings, base_dir=base)
            else:
                operation = lambda: scientific_report.manuscript(specification, base_dir=base, bindings=bindings, final=parameters["final"])
        elif action in {"scientific-report", "report-revise"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("scientific report construction must not receive a blinded review role")
            fields = {"request_input"} if action == "scientific-report" else {"request_input", "draft_input"}
            _keys(parameters, fields, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in fields:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("scientific report JSON must be explicitly hash-bound")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("scientific report JSON changed during read")
                locations[key] = path
            base = locations["request_input"].parent
            allowed = {path: sha for path, sha in pins.values()}
            try:
                if action == "report-revise" and locations["draft_input"].parent != base:
                    raise ValueError("report draft and request must share their artifact base")
                specification = objects["request_input"]
                for pin in scientific_report.input_pins(specification, base_dir=base):
                    raw = Path(pin["path"])
                    path = _safe_path(raw if raw.is_absolute() else base / raw)
                    if path not in allowed or allowed[path] != pin["sha256"] or file_hash(path) != pin["sha256"]:
                        raise ValueError("report source, tool result and context history must be explicit graph inputs")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("scientific report rejected unbound source, delivered fact or context output") from None
            if action == "scientific-report":
                operation = lambda: scientific_report.compose(specification, base_dir=base)
            else:
                operation = lambda: scientific_report.revise(specification, objects["draft_input"], base_dir=base)
        elif action in {"cosmology-prepare", "cosmology-results", "cosmology-run"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("cosmology experiment preparation/result interpretation must not receive a blinded role")
            fields = {"request_input", "source_binding_input"} if action in {"cosmology-prepare", "cosmology-run"} else {"result_input"}
            _keys(parameters, fields, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in fields:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("cosmology boundary requires explicit source/result graph inputs")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("cosmology source/result changed during read")
                locations[key] = path
            if action in {"cosmology-prepare", "cosmology-run"}:
                specification = objects["request_input"]
                if specification.get("source_binding") != objects["source_binding_input"]:
                    raise HostFailure("cosmology request and released source binding differ")
                base = locations["source_binding_input"].parent
                prepared = cosmology_backend.prepare(specification, source_base=base)
                allowed = {p: checksum for p, checksum in pins.values()}
                for ref in prepared["source_inspection"]["source_pins"]:
                    path = _safe_path(ref["path"])
                    if allowed.get(path) != ref["sha256"] or file_hash(path) != ref["sha256"]:
                        raise HostFailure("every inspected upstream source must be an exact graph input")
                if action == "cosmology-run":
                    if self.cosmology_runtime_binding is None:
                        raise HostFailure("cosmology runtime needs an explicit caller-qualified loaded binding")
                    runtime_inputs = [{"path":str(path),"sha256":checksum} for path,checksum in pins.values()]
                    operation = lambda: self.cosmology_runtime_binding.run(specification, source_base=base,
                        control=control, graph_input_pins=runtime_inputs)
                else:
                    operation = lambda: cosmology_backend.prepare(specification, source_base=base)
            else:
                operation = lambda: cosmology_backend.read_results(objects["result_input"])
        elif action == "scientific-phase":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("scientific phase planning must not receive a blinded review role")
            _keys(parameters, {"request_input"}, "Ravel tool parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("scientific phase request must be an explicit graph input")
            path, sha = pins[identity]
            phase_request = read_json(path)
            if file_hash(path) != sha:
                raise HostFailure("scientific phase request changed during read")
            operation = lambda: scientific_phase_allocation.allocate(phase_request)
        elif action == "eft-toolchain-context":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("EFT drafting context is not a blinded review tool")
            _keys(parameters, {"request_input"}, "Ravel tool parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("EFT task must be an explicit graph input")
            path, sha = pins[identity]
            task = read_json(path)
            if file_hash(path) != sha: raise HostFailure("EFT task changed")
            allowed = {p:h for p,h in pins.values()}
            try:
                for dependency in eft_toolchain.context_inputs(task,path.parent):
                    if allowed.get(dependency) != file_hash(dependency):
                        raise ValueError("EFT scientific context dependency not an explicit graph input")
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure("EFT scientific context custody refused") from None
            operation = lambda: eft_toolchain.context(task,path.parent)
        elif action == 'diagram-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Diagram drafting context is not a blinded review tool')
            _keys(parameters, {'mode','request_input'}, 'Ravel tool parameters')
            mode=parameters['mode']
            if mode not in ('feyn-graph','diagram-analysis','feynarts-amplitude'):
                raise HostFailure('Explicit implemented diagram operation required')
            selected=parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact diagram task must be a declared Graph input')
            path,sha=pins[selected]
            try:
                _,raw=scientific_artifact._basis_snapshot({'path':path.name,'sha256':sha,'size':path.stat().st_size},path.parent)
                task=_loads(raw)
                from ravel.workflow import science
                implementation=science.adapter({'mode':mode,'task':task})
                allowed={p:h for p,h in pins.values()}
                for dependency in implementation.context_inputs(task,path.parent):
                    if allowed.get(dependency)!=file_hash(dependency):raise ValueError('Diagram dependency not an explicit Graph input')
                value=implementation.context(task,path.parent)
                if file_hash(path)!=sha:raise ValueError('Diagram task changed')
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('Diagram scientific context custody refused') from None
            operation=lambda:value
        elif action == 'full-auxiliary-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Calibration drafting context is not a blinded review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('Calibration task must be an explicit graph input')
            path,sha=pins[identity]
            try:
                _,text=scientific_artifact._basis_snapshot({'path':path.name,'sha256':sha,'size':path.stat().st_size},path.parent)
                task=_loads(text)
                allowed={p:h for p,h in pins.values()}
                from ravel.workflow import science
                with science._validation_scope(path.parent) as session:
                    for dependency in full_auxiliary_calibration.inputs(task,path.parent,_session=session):
                        if allowed.get(dependency)!=session.hash_file(dependency):raise ValueError('Calibration dependency not an explicit graph input')
                    value=full_auxiliary_calibration.context(task,path.parent,_session=session)
                if file_hash(path)!=sha:raise ValueError('Calibration task changed')
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('Calibration scientific context custody refused') from None
            operation=lambda:value
        elif action == 'asimov-sensitivity-context':
            from ravel.physics import asimov_sensitivity
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Discovery drafting context is not a blinded review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('Discovery task must be an explicit graph input')
            path,sha=pins[identity]
            try:
                _,text=scientific_artifact._basis_snapshot({'path':path.name,'sha256':sha,'size':path.stat().st_size},path.parent)
                task=_loads(text)
                allowed={p:h for p,h in pins.values()}
                from ravel.workflow import science
                with science._validation_scope(path.parent) as session:
                    for dependency in asimov_sensitivity.inputs(task,path.parent,_session=session):
                        if allowed.get(dependency)!=session.hash_file(dependency):raise ValueError('Discovery dependency not an explicit graph input')
                    value=asimov_sensitivity.context(task,path.parent,_session=session)
                if file_hash(path)!=sha:raise ValueError('Discovery task changed')
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('Discovery scientific context custody refused') from None
            operation=lambda:value
        elif action == 'tree-array-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Raw array drafting context is not a blinded review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            selected = parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact array task must be a declared Graph input')
            from ravel.physics import tree_array_export as arrays
            capture = arrays.InputCapture()
            try:
                path, sha = pins[selected]
                _, raw = capture.read(str(path), path.parent, sha)
                task = arrays._json(raw)
                allowed = {p:h for p,h in pins.values()}
                for dependency in arrays.inputs(task, path.parent):
                    expected = allowed.get(dependency)
                    if expected is None:
                        raise ValueError('Array dependency is not an explicit Graph input')
                    capture.stream_pin({'path':str(dependency), 'sha256':expected}, path.parent)
                value = arrays.context(task, path.parent)
                capture.finish()
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure('Array source context custody refused') from None
            def operation():
                capture.finish()
                return value
        elif action == 'parameter-space-sampling-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('EasyScan drafting context is not a blinded review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            selected=parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact EasyScan task must be a declared Graph input')
            path,sha=pins[selected]
            capture=parameter_space_sampling.core.Capture()
            try:
                _,raw=capture.read({'path':str(path),'sha256':sha,'size':path.stat().st_size},path.parent)
                task=parameter_space_sampling.core.strict(raw);allowed={p:h for p,h in pins.values()}
                for dependency in parameter_space_sampling.context_inputs(task,path.parent):
                    expected=allowed.get(dependency)
                    if expected is None:raise ValueError('EasyScan source dependency is not an explicit Graph input')
                    capture.read({'path':str(dependency),'sha256':expected,'size':dependency.stat().st_size},path.parent)
                result=parameter_space_sampling.context(task,path.parent);capture.finish()
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('EasyScan source context custody refused') from None
            def operation():
                capture.finish()
                return result
        elif action == 'ntuple-inventory-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Ntuple source design is not a blinded result review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            selected = parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact ntuple task must be a declared Graph input')
            from ravel.physics import ntuple_inventory
            path, sha = pins[selected]; capture = ntuple_inventory.c.Capture()
            try:
                _, raw = capture.read({'path':str(path),'sha256':sha,'size':path.stat().st_size},path.parent)
                task = ntuple_inventory.c.strict(raw); allowed = {p:h for p,h in pins.values()}
                for dependency in ntuple_inventory.context_inputs(task,path.parent):
                    expected = allowed.get(dependency)
                    if expected is None:
                        raise ValueError('Ntuple transitive input must be a declared Graph source')
                    capture.read({'path':str(dependency),'sha256':expected,'size':dependency.stat().st_size},path.parent,
                                 max(8*1024**2,dependency.stat().st_size))
                value = ntuple_inventory.context(task,path.parent); capture.finish()
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure('Ntuple source context custody refused') from None
            def operation():
                capture.finish()
                return value
        elif action == 'mc-closure-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Ntuple source design is not a blinded result review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            selected = parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact ntuple task must be a declared Graph input')
            from ravel.physics import mc_closure
            path, sha = pins[selected]; capture = mc_closure.c.Capture()
            try:
                _, raw = capture.read({'path':str(path),'sha256':sha,'size':path.stat().st_size},path.parent)
                task = mc_closure.c.strict(raw); allowed = {p:h for p,h in pins.values()}
                for dependency in mc_closure.inputs(task,path.parent):
                    expected = allowed.get(dependency)
                    if expected is None:
                        raise ValueError('Ntuple transitive input must be a declared Graph source')
                    capture.read({'path':str(dependency),'sha256':expected,'size':dependency.stat().st_size},path.parent,
                                 max(8*1024**2,dependency.stat().st_size))
                value = mc_closure.context(task,path.parent); capture.finish()
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure('Ntuple source context custody refused') from None
            def operation():
                capture.finish()
                return value
        elif action == 'root-stream-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('Stream source drafting context is not a blinded result review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            selected=parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact stream task must be a declared Graph input')
            path,sha=pins[selected];capture=root_stream.core.Capture()
            try:
                _,raw=capture.read({'path':str(path),'sha256':sha,'size':path.stat().st_size},path.parent)
                task=root_stream.core.strict(raw);allowed={p:h for p,h in pins.values()}
                for dependency in root_stream.context_inputs(task,path.parent):
                    expected=allowed.get(dependency)
                    if expected is None:raise ValueError('Stream metadata/kernel dependency is not an explicit Graph input')
                    capture.read({'path':str(dependency),'sha256':expected,'size':dependency.stat().st_size},path.parent)
                value=root_stream.context(task,path.parent);capture.finish()
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('Stream source context custody refused') from None
            def operation():
                capture.finish()
                return value
        elif action == 'dataset-query-quantities-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('IRIS drafting context is not a blinded review tool')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            selected=parameters['request_input']
            if type(selected) is not str or selected not in pins:
                raise HostFailure('Exact IRIS task must be a declared Graph input')
            path,sha=pins[selected]
            capture=dataset_query_quantities.core.Capture()
            try:
                _,raw=capture.read({'path':str(path),'sha256':sha,'size':path.stat().st_size},path.parent)
                task=dataset_query_quantities.core.strict(raw)
                allowed={p:h for p,h in pins.values()}
                for dependency in dataset_query_quantities.context_inputs(task,path.parent):
                    expected=allowed.get(dependency)
                    if expected is None:raise ValueError('IRIS source dependency is not an explicit Graph input')
                    capture.read({'path':str(dependency),'sha256':expected,'size':dependency.stat().st_size},path.parent)
                value=dataset_query_quantities.context(task,path.parent)
                capture.finish()
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('IRIS source context custody refused') from None
            def operation():
                capture.finish()
                return value
        elif action == 'cosmic-evolution-context':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('CosmicIC/Nyx source preparation cannot substitute for blind result review')
            _keys(parameters, {'request_input','closure_input'}, 'Ravel tool parameters')
            if any(type(parameters[k]) is not str or parameters[k] not in pins for k in parameters):
                raise HostFailure('CosmicIC/Nyx configuration and complete closure must be graph-bound')
            path, sha = pins[parameters['request_input']]
            closure_path, closure_sha = pins[parameters['closure_input']]
            try:
                _, d, captured, observations, prerequisites, _ = cosmic_evolution._capture({'input':str(path)},path.parent)
                closure = captured.json({'path':str(closure_path),'sha256':closure_sha,'size':closure_path.stat().st_size})
                cosmic_evolution.core.keys(closure, ('schema_version','configuration','inputs'), 'complete graph input closure')
                actual = [p for p in captured.pins() if p['path'] != str(closure_path)]
                expected = next(p for p in actual if p['path'] == str(path))
                if type(closure['schema_version']) is not int or closure['schema_version'] != 1 or closure['configuration'] != expected:
                    raise ValueError('Original configuration closure differs')
                if closure['inputs'] != actual or captured.files[str(path)]['sha256'] != sha:
                    raise ValueError('Whole CosmicIC/Nyx source/card/data/IC closure differs')
                value = {'kind':'cosmic-evolution-source-context','original_requests':d['original_requests'],
                         'cases':observations,'prerequisites':prerequisites,'input_pins':actual,
                         'closure':{'path':str(closure_path),'sha256':closure_sha},
                         'operation':d['operation'],'execution_authorized':False,'physics_verified':False,
                         'all_source_content_presented_to_model':False}
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('CosmicIC/Nyx source context custody refused') from None
            def operation():
                captured.finish()
                return value
        elif action == "finite-integrals-context":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("Finite integral drafting context is not a blinded review tool")
            _keys(parameters, {"request_input"}, "Ravel tool parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("Finite integral task must be an explicit graph input")
            path, sha = pins[identity]
            task = read_json(path)
            if file_hash(path) != sha: raise HostFailure("Finite integral task changed")
            allowed = {p:h for p,h in pins.values()}
            try:
                for dependency in finite_integrals.context_inputs(task,path.parent):
                    if allowed.get(dependency) != file_hash(dependency):
                        raise ValueError("Finite integral scientific context dependency not an explicit graph input")
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure("Finite integral scientific context custody refused") from None
            operation = lambda: finite_integrals.context(task,path.parent)
        elif action == 'sfitter-scan-inputs':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('SFitter scan construction cannot receive a blinded review role')
            _keys(parameters, {'request_input'}, 'Ravel tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:raise HostFailure('Explicit scan request input required')
            from ravel.physics.ma5_saf import Capture
            path,sha=pins[identity];capture=Capture()
            _,raw=capture.read(path,path.parent,sha);specification=sfitter_workflow._strict_document(raw)
            allowed={p:h for p,h in pins.values()}
            try:
                for dep in sfitter_scan_inputs.input_pins(specification,path.parent):
                    p=_safe_path(dep['path'])
                    if allowed.get(p)!=dep['sha256']:raise ValueError('whole scan source input missing')
                    capture.pin(dep,path.parent)
                capture.finish()
            except (OSError,ValueError,KeyError,TypeError):raise HostFailure('Scan source/input custody refused') from None
            def operation():
                result=sfitter_scan_inputs.compile(specification,path.parent)
                capture.finish()
                return result
        elif action in {'resonance-assess','resonance-prepare','resonance-collect'}:
            if node['role'] in BLIND_ROLES:
                raise HostFailure('resonance construction retains physical context, not a blind reviewer role')
            fields={'request_input'}
            if action!='resonance-assess':fields|={'selection_input','output_dir'}
            _keys(parameters,fields,'resonance tool parameters')
            from . import resonance_study
            from ravel.physics.ma5_saf import Capture, _json
            captured=Capture(); identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:raise HostFailure('exact resonance request input required')
            path,sha=pins[identity];captured.read(path,path.parent,sha)
            selection=None
            if action!='resonance-assess':
                identity=parameters['selection_input']
                if type(identity) is not str or identity not in pins:raise HostFailure('explicit resonance stage/result selection required')
                sp,ss=pins[identity];_,raw=captured.read(sp,sp.parent,ss);selection=_json(raw)
                _text(parameters['output_dir'],'fresh resonance destination',2048);destination=_safe_path(parameters['output_dir'])
                if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                    raise HostFailure('resonance output outside configured Host roots')
            try:
                allowed={p:h for p,h in pins.values()}
                dependencies=resonance_study.input_pins(path)
                if action=='resonance-prepare':
                    _keys(selection,{'stage_id','runs'},'explicit resonance stage selection')
                    dependencies=resonance_study.preparation_pins(path,selection['stage_id'],selection['runs'])
                elif action=='resonance-collect':
                    dependencies=resonance_study.delivery_pins(path,selection)
                for dep in dependencies:
                    dp=_safe_path(dep['path'])
                    if allowed.get(dp)!=dep['sha256']:raise ValueError('complete scientific source/run not an explicit Graph input')
                captured.finish()
            except (OSError,ValueError,KeyError,TypeError):raise HostFailure('resonance source/whole-population custody refused') from None
            def operation():
                if action=='resonance-assess':result=resonance_study.assess(path)
                elif action=='resonance-prepare':result=resonance_study.prepare_stage(path,selection['stage_id'],selection['runs'],destination)
                else:result=resonance_study.collect(path,selection,destination)
                captured.finish();return result
        elif action in {"backend-portfolio", "backend-handoff", "backend-results"}:
            if node['role'] in BLIND_ROLES:
                raise HostFailure('backend construction/intake retains context and cannot consume a blind role')
            fields = {'request_input'}
            if action != 'backend-portfolio': fields |= {'selection_input', 'output_dir'}
            _keys(parameters, fields, 'backend portfolio parameters')
            identity = parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('backend portfolio request must be an explicit Graph input')
            path, sha = pins[identity]
            selection = None
            if action != 'backend-portfolio':
                identity = parameters['selection_input']
                if type(identity) is not str or identity not in pins:
                    raise HostFailure('backend choice/result branches must be an explicit Graph input')
                source, checksum = pins[identity]; selection = read_json(source)
                if file_hash(source) != checksum: raise HostFailure('backend selection changed')
                _text(parameters['output_dir'], 'fresh backend destination', 2048)
                destination = _safe_path(parameters['output_dir'])
                if self.bound_roots and not any(destination.is_relative_to(root) for root in self.bound_roots):
                    raise HostFailure('backend output is outside configured host roots')
            allowed = {p: h for p, h in pins.values()}
            try:
                if file_hash(path) != sha: raise ValueError('backend request changed')
                dependencies = (backend_portfolio.delivery_pins(path, selection) if action == 'backend-results'
                                else backend_portfolio.input_pins(path))
                for pin in dependencies:
                    p = _safe_path(pin['path'])
                    if allowed.get(p) != pin['sha256'] or file_hash(p) != pin['sha256']:
                        raise ValueError('backend model/event/source/result must be an exact Graph input')
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure('backend portfolio rejected unbound/changed complete inputs') from None
            if action == 'backend-portfolio': operation = lambda: backend_portfolio.assess(path)
            elif action == 'backend-handoff': operation = lambda: backend_portfolio.prepare(path, selection, destination)
            else: operation = lambda: backend_portfolio.ingest(path, selection, destination)
        elif action == 'sfitter-scan-review':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('scan review preparation is source construction, not blinded judgment')
            _keys(parameters, {'request_input'}, 'scan-review tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('scan-review request must be an explicit graph input')
            from ravel.workflow import sfitter_scan_review as scan_review
            from ravel.physics.ma5_saf import Capture
            captured=Capture();path,sha=pins[identity]
            try:
                _,raw=captured.read(path,path.parent,sha)
                doc=sfitter_workflow._strict_document(raw)
                allowed={p:digest for p,digest in pins.values()}
                for pin in scan_review.input_pins(doc,path.parent):
                    dependency=_safe_path(pin['path'])
                    if allowed.get(dependency)!=pin['sha256']:
                        raise ValueError('whole scan review source graph must be explicit')
                    captured.pin(pin,path.parent)
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('scan-review source custody refused') from None
            def operation():
                result=scan_review.analyze(doc,path.parent)
                captured.finish()
                return result
        elif action == 'sfitter-observed-events':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('scan extraction is source construction, not blinded review')
            _keys(parameters, {'request_input'}, 'scan-extraction tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('scan-extraction request must be an explicit input')
            from ravel.physics import sfitter_observed_events as scan_extract
            from ravel.physics.ma5_saf import Capture
            captured=Capture();path,sha=pins[identity]
            try:
                _,raw=captured.read(path,path.parent,sha)
                doc=sfitter_workflow._strict_document(raw)
                allowed={p:digest for p,digest in pins.values()}
                for pin in scan_extract.input_pins(doc,path.parent):
                    dependency=_safe_path(pin['path'])
                    if allowed.get(dependency)!=pin['sha256']:
                        raise ValueError('whole scan source graph must be explicit')
                    captured.pin(pin,path.parent)
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('scan-extraction source custody refused') from None
            def operation():
                result=scan_extract.acquire(doc,path.parent)[0]
                captured.finish()
                return result
        elif action == 'sfitter-scan-extract':
            if node['role'] in BLIND_ROLES:
                raise HostFailure('scan extraction is source construction, not blinded review')
            _keys(parameters, {'request_input'}, 'scan-extraction tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('scan-extraction request must be an explicit input')
            from ravel.physics import sfitter_scan_extraction as scan_extract
            from ravel.physics.ma5_saf import Capture
            captured=Capture();path,sha=pins[identity]
            try:
                _,raw=captured.read(path,path.parent,sha)
                doc=sfitter_workflow._strict_document(raw)
                allowed={p:digest for p,digest in pins.values()}
                for pin in scan_extract.input_pins(doc,path.parent):
                    dependency=_safe_path(pin['path'])
                    if allowed.get(dependency)!=pin['sha256']:
                        raise ValueError('whole scan source graph must be explicit')
                    captured.pin(pin,path.parent)
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('scan-extraction source custody refused') from None
            def operation():
                result=scan_extract.extract(doc,path.parent)
                captured.finish()
                return result
        elif action == "sfitter-application-context":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("Application context contains source/memory and cannot be a blinded review")
            _keys(parameters, {"request_input"}, "Ravel tool parameters")
            identity=parameters["request_input"]
            if identity not in pins: raise HostFailure("Application request must be an explicit input")
            path,sha=pins[identity]
            from . import sfitter_application
            from ravel.physics.ma5_saf import Capture
            captured=Capture()
            try:
                _,raw=captured.read(path,path.parent,sha)
                application_request=sfitter_workflow._strict_document(raw)
                allowed={p:digest for p,digest in pins.values()}
                for ref in sfitter_application.input_pins(application_request,path.parent):
                    dependency=_safe_path(ref['path'])
                    if allowed.get(dependency)!=ref['sha256']:
                        raise ValueError('whole application context source must be explicit')
                    captured.pin(ref,path.parent)
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('Application source/session/parent custody refused') from None
            def operation():
                result=sfitter_application.context(application_request['session'],path.parent,
                    actor=application_request['actor'],skill=application_request['skill'])
                captured.finish()
                return result
        elif action in {"sfitter-context", "sfitter-handoff", "sfitter-assemble"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("SFitter drafting tools cannot receive a blinded review role")
            fields = {"request_input", "handoff_input"} if action == "sfitter-handoff" else {"request_input"}
            _keys(parameters, fields, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in fields:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("SFitter scientific artifacts must be explicit inputs")
                path, sha = pins[identity]
                if action == 'sfitter-assemble':
                    from ravel.physics.ma5_saf import Capture
                    assembly_capture=Capture()
                    _,raw=assembly_capture.read(path,path.parent,sha)
                    objects[key]=sfitter_workflow._strict_document(raw)
                else:
                    objects[key] = read_json(path)
                    if file_hash(path) != sha: raise HostFailure("SFitter scientific artifact changed")
                locations[key] = path
            base = locations['request_input'].parent
            allowed = {path:sha for path,sha in pins.values()}
            if action == 'sfitter-assemble' and node['packet'] is not None:
                from . import sfitter_source_context
                _,complete=sfitter_source_context.verified_packet_sources(node['packet'],
                    {'path':str(locations['request_input']),'sha256':pins[parameters['request_input']][1]},
                    base,purpose='assembly')
                allowed.update({_safe_path(p['path']):p['sha256'] for p in complete})
            try:
                dependencies = (sfitter_workflow.assembly_inputs(objects['request_input'],base) if action == 'sfitter-assemble' else sfitter_workflow.input_pins(objects['request_input'],base))
                if action == 'sfitter-handoff':
                    if locations['handoff_input'].parent != base: raise ValueError('handoff must share request base')
                    dependencies += list(sfitter_workflow._refs(objects['handoff_input']))
                    handoff=objects['handoff_input']
                    if handoff.get('phase')=='conventions' and 'transport_request' in handoff.get('payload',{}):
                        ref=handoff['payload']['transport_request']
                        rp=_safe_path(Path(ref['path']) if Path(ref['path']).is_absolute() else base/ref['path'])
                        dependencies += [{'path':str(p),'sha256':file_hash(p)} for p in
                            sfitter_workflow.eft_conventions.inputs({'request':str(rp)},rp.parent)]
                for pin in dependencies:
                    path = _safe_path(Path(pin['path']) if Path(pin['path']).is_absolute() else base/ pin['path'])
                    if (action == 'sfitter-assemble' and node['packet'] is not None and self.bound_roots
                            and not any(path.is_relative_to(root) for root in self.bound_roots)):
                        raise ValueError('SFitter packet dependency is outside configured Host roots')
                    if allowed.get(path) != pin['sha256'] or file_hash(path) != pin['sha256']:
                        raise ValueError('SFitter inspected source/evidence is not an exact graph input')
            except (OSError,ValueError,KeyError,TypeError):
                raise HostFailure('SFitter source/phase dependency custody refused') from None
            if action == 'sfitter-context':operation = lambda: sfitter_workflow.context(objects['request_input'],base)
            elif action == 'sfitter-assemble':
                def operation():
                    result=sfitter_workflow.assemble_datacard(objects['request_input'],base)
                    assembly_capture.finish()
                    return result
            else:operation = lambda: sfitter_workflow.apply_handoff(objects['request_input'],objects['handoff_input'],base)
        elif action in {'agentrivet-prepare','agentrivet-context'}:
            if node['role'] in BLIND_ROLES:
                raise HostFailure('routine construction source cannot be blind review context')
            from . import agentrivet_construction
            fields={'request_input','output_directory'} if action=='agentrivet-prepare' else {'request_input'}
            _keys(parameters,fields,'Ravel tool parameters')
            identity=parameters['request_input']
            if type(identity) is not str or identity not in pins:
                raise HostFailure('construction request must be an explicit original Graph input')
            path,sha=pins[identity]; pin={'path':str(path),'sha256':sha}
            try:
                _,document=agentrivet_construction._document(pin,path.parent)
                allowed={p:d for p,d in pins.values()}
                for ref in agentrivet_construction.input_pins(document,path.parent):
                    q=_safe_path(ref['path'])
                    if allowed.get(q)!=ref['sha256']:
                        raise ValueError('complete original construction source/parent missing from Graph inputs')
                if action=='agentrivet-prepare':
                    output=_safe_path(parameters['output_directory'])
                    if self.bound_roots and not any(output.is_relative_to(r) for r in self.bound_roots):
                        raise ValueError('construction preparation is outside configured Host roots')
            except (ValueError,OSError,KeyError,TypeError):
                raise HostFailure('construction source/parent custody refused') from None
            if action=='agentrivet-prepare':
                operation=lambda:agentrivet_construction.prepare(document,base_dir=path.parent,output_dir=output)
            else:
                operation=lambda:agentrivet_construction.context(pin,base_dir=path.parent)
        elif action == "physics-knowledge":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("physics knowledge retrieval retains context and cannot claim blinded review")
            _keys(parameters, {"request_input"}, "Ravel tool parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("physics knowledge request must be explicitly bound")
            path, sha = pins[identity]
            try:
                request_pin = {"path": str(path), "sha256": sha, "size": path.stat().st_size}
                _, raw = physics_knowledge._snapshot(request_pin, path.parent)
                specification = physics_knowledge._json(raw)
                dependencies = physics_knowledge.input_pins(specification, path.parent)
                allowed = {p: digest for p, digest in pins.values()}
                for dependency in dependencies:
                    bound = _safe_path(dependency["path"])
                    if bound not in allowed or allowed[bound] != dependency["sha256"]:
                        raise ValueError("knowledge graph/source parent absent from explicit inputs")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("physics knowledge request rejected unbound or changed source") from None
            operation = lambda: physics_knowledge.retrieve(specification, path.parent)
        elif action in {"scientific-context", "scientific-step"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("scientific source context must not receive a blinded review role")
            fields = {"request_input"} if action == "scientific-context" else {"context_input", "attempt_input"}
            _keys(parameters, fields, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in fields:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("scientific context JSON must be explicitly hash-bound")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("scientific context JSON changed during read")
                locations[key] = path
            base = locations["request_input" if action == "scientific-context" else "context_input"].parent
            allowed = {path: sha for path, sha in pins.values()}
            try:
                if action == "scientific-context":
                    specification = objects["request_input"]
                    dependencies = scientific_context.input_pins(specification, base)
                else:
                    if locations["attempt_input"].parent != base:
                        raise ValueError("scientific step JSON must share its artifact base")
                    context, attempt = objects["context_input"], objects["attempt_input"]
                    dependencies = scientific_context.step_pins(context, attempt, base)
                for pin in dependencies:
                    raw = Path(pin["path"])
                    path = _safe_path(raw if raw.is_absolute() else base / raw)
                    if path not in allowed or allowed[path] != pin["sha256"] or file_hash(path) != pin["sha256"]:
                        raise ValueError("scientific source and output must be explicit graph inputs")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("scientific context rejected unbound source or requested output") from None
            if action == "scientific-context":
                operation = lambda: scientific_context.compile_context(specification, base)
            else:
                operation = lambda: scientific_context.apply_step(context, attempt, base)
        elif action in {"constructive-prepare", "constructive-apply"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("constructive source tools must not receive a blinded review role")
            required = {"request_input"} if action == "constructive-prepare" else {"preparation_input", "plan_input"}
            _keys(parameters, required, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in parameters:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("constructive JSON inputs must be explicitly hash-bound")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("constructive JSON input changed during read")
                locations[key] = path
            base_key = "request_input" if action == "constructive-prepare" else "preparation_input"
            base = locations[base_key].parent
            allowed = {p: checksum for p, checksum in pins.values()}
            try:
                if action == "constructive-prepare":
                    specification = objects["request_input"]
                    dependencies = constructive_contrast.input_pins(specification)
                else:
                    if locations["plan_input"].parent != base:
                        raise ValueError("application JSON inputs must share their artifact base directory")
                    preparation = objects["preparation_input"]
                    completed_plan = objects["plan_input"]
                    dependencies = (constructive_contrast.input_pins(preparation["request"])
                                    + constructive_contrast.evaluation_pins(completed_plan))
                for evidence in dependencies:
                    raw = Path(evidence["path"])
                    source = _safe_path(raw if raw.is_absolute() else base / raw)
                    if (source not in allowed or allowed[source] != evidence["sha256"]
                            or file_hash(source) != allowed[source]):
                        raise HostFailure("constructive source and measurements must match explicitly hash-bound inputs")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("constructive specification rejected; JSON inputs must share an artifact base and all dependencies must be explicit") from None
            if action == "constructive-prepare":
                operation = lambda: constructive_contrast.prepare(specification, base)
            else:
                operation = lambda: constructive_contrast.apply_results(preparation, completed_plan, base)
        elif action in {"empirical-next", "empirical-component-prepare"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("empirical construction tools must not receive a blinded review role")
            required = {"request_input"} if action == "empirical-next" else {"round_input", "request_input"}
            _keys(parameters, required, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in parameters:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("empirical JSON inputs must be explicitly hash-bound")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("empirical JSON input changed during read")
                locations[key] = path
            base = locations["request_input"].parent
            allowed = {p: checksum for p, checksum in pins.values()}
            try:
                if action == "empirical-next":
                    specification = objects["request_input"]
                    dependencies = empirical_search.input_pins(specification, base_dir=base)
                else:
                    if locations["round_input"].parent != base:
                        raise ValueError("empirical JSON inputs must share their artifact base directory")
                    record = objects["round_input"]
                    specification = {"schema_version": 1, "contract": record["contract"],
                        "plan": record["plan"], "ledger": record["ledger"], "previous": record["previous"]}
                    dependencies = (empirical_search.input_pins(specification, base_dir=base)
                                    + constructive_contrast.input_pins(objects["request_input"]))
                for evidence in dependencies:
                    raw = Path(evidence["path"])
                    source = _safe_path(raw if raw.is_absolute() else base / raw)
                    if (source not in allowed or allowed[source] != evidence["sha256"]
                            or file_hash(source) != allowed[source]):
                        raise HostFailure("empirical history, measurements and component source must be explicit graph inputs")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("empirical specification rejected; complete nested input custody and one artifact base required") from None
            if action == "empirical-next":
                operation = lambda: empirical_search.generation_view(empirical_search.advance_request(specification, base_dir=base))
            else:
                operation = lambda: empirical_search.prepare_component_followup(record, objects["request_input"], base_dir=base)
        elif action in {"adaptation-retrieve", "adaptation-prepare"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("adaptation construction tools must not consume a blind reviewer role")
            required = {"request_input"} if action == "adaptation-retrieve" else {"retrieval_input", "bindings_input"}
            _keys(parameters, required, "Ravel tool parameters")
            objects, locations = {}, {}
            for key, identity in parameters.items():
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("adaptation JSON must be an explicit graph input")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("adaptation JSON changed during read")
                locations[key] = path
            base = locations["request_input" if action == "adaptation-retrieve" else "retrieval_input"].parent
            adaptation_request = objects["request_input"] if action == "adaptation-retrieve" else objects["retrieval_input"]["request"]
            allowed = {path: checksum for path, checksum in pins.values()}
            try:
                for evidence in adaptation_reuse.input_pins(adaptation_request, base_dir=base):
                    source = _safe_path(Path(evidence["path"]))
                    if source not in allowed or allowed[source] != evidence["sha256"] or file_hash(source) != allowed[source]:
                        raise HostFailure("complete adaptation source/catalog/observation pins required")
                if action == "adaptation-prepare":
                    if locations["bindings_input"].parent != base:
                        raise HostFailure("adaptation request artifacts must share one base")
                    _keys(objects["bindings_input"], {"entry_id", "bindings"}, "adaptation bindings")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("adaptation input inventory or source binding rejected") from None
            if action == "adaptation-retrieve":
                operation = lambda: adaptation_reuse.retrieve(adaptation_request, base_dir=base)
            else:
                operation = lambda: adaptation_reuse.prepare(objects["retrieval_input"],
                    objects["bindings_input"]["entry_id"], objects["bindings_input"]["bindings"], base_dir=base)
        elif action in {"public-source-facts", "scientific-task-delivery", "scientific-task-response"}:
            if node["role"] in BLIND_ROLES:
                raise HostFailure("task construction must not consume a blind review role")
            fields = {"request_input", "response_input"} if action == "scientific-task-response" else {"request_input"}
            _keys(parameters, fields, "Ravel tool parameters")
            objects, locations = {}, {}
            for key in fields:
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("task tool/request/response must be explicitly hash-bound")
                path, sha = pins[identity]
                if file_hash(path) != sha:
                    raise HostFailure("task request/response changed before read")
                locations[key] = path
                if key == "request_input":
                    try:
                        _, request_text = scientific_artifact._basis_snapshot(
                            {"path": path.name, "sha256": sha, "size": path.stat().st_size},
                            path.parent,
                        )
                        objects[key] = _loads(request_text)
                    except (OSError, ValueError, UnicodeError):
                        raise HostFailure("task request snapshot differs from its bound input") from None
            specification = objects["request_input"]
            base = locations["request_input"].parent
            allowed = {p: sha for p, sha in pins.values()}
            module = public_source_tools if action == "public-source-facts" else scientific_task_delivery
            try:
                for evidence in module.input_pins(specification, base_dir=base):
                    source = _safe_path(base / evidence["path"])
                    if allowed.get(source) != evidence["sha256"] or file_hash(source) != evidence["sha256"]:
                        raise ValueError("complete task source and tool custody required")
                if action == "scientific-task-response":
                    response_path = locations["response_input"]
                    response = {"path": str(response_path.relative_to(base)), "sha256": allowed[response_path], "size": response_path.stat().st_size}
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("task construction rejected unbound source or tool facts") from None
            if action == "public-source-facts":
                operation = lambda: public_source_tools.calculate(specification, base_dir=base)
            elif action == "scientific-task-response":
                operation = lambda: scientific_task_delivery.from_response(specification, response, base_dir=base)
            else:
                operation = lambda: scientific_task_delivery.deliver(specification, base_dir=base)
        elif action == "scientific-artifact":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("scientific artifact construction cannot consume a blind reviewer role")
            _keys(parameters, {"request_input"}, "Ravel tool parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("scientific artifact contract must be an explicit graph input")
            path, checksum = pins[identity]
            specification = read_json(path)
            if file_hash(path) != checksum:
                raise HostFailure("scientific artifact contract changed during read")
            base = path.parent
            allowed = {p: sha for p, sha in pins.values()}
            try:
                for evidence in scientific_artifact.input_pins(specification, base_dir=base):
                    source = _safe_path(base / evidence["path"])
                    if source not in allowed or allowed[source] != evidence["sha256"] or file_hash(source) != allowed[source]:
                        raise ValueError("complete task/API/tool custody required")
            except (OSError, ValueError, KeyError, TypeError):
                raise HostFailure("scientific artifact refused unbound source or tool fields") from None
            operation = lambda: scientific_artifact.compose(specification, base_dir=base)
        elif action == "quantitative-predictive":
            from . import quantitative_predictive_checks as predictive
            if node["role"] in BLIND_ROLES:
                raise HostFailure("quantitative calculation cannot consume a blinded review role")
            _keys(parameters, {"request_input"}, "quantitative tool parameters")
            identity = parameters["request_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("quantitative binding must enter normal source-bound Host inputs")
            path, checksum = pins[identity]
            binding = predictive.Capture(path.parent, predictive.default_resources()).document(
                {"path":str(path),"sha256":checksum,"size":path.stat().st_size})
            predictive.validate_binding(binding)
            guidance = predictive.guidance(binding,path.parent)
            resource = guidance["requirements"]["effective"]
            # Cheap Host path has an explicit effective ceiling. Larger complete
            # correlated populations use the ordinary scientific runner instead.
            if (resource["wall_seconds"] > self.timeout or resource["max_rss_mib"] > 256
                    or any(resource["limits"][k] > v for k,v in predictive.DEFAULT_LIMITS.items())):
                raise HostFailure("complete quantitative work requires ordinary larger allocation")
            allowed = {str(p):sha for p,sha in pins.values()}
            for dependency in predictive.inputs(binding,path.parent):
                pin = __import__('ravel.workflow.research_cycle',fromlist=['_pin'])._pin(dependency)
                if allowed.get(str(dependency)) != pin['sha256']:
                    raise HostFailure("all quantitative prediction/law/resource inputs must enter actual Host custody")
            operation = lambda: predictive.separation(binding,base_dir=path.parent)
        elif action == "numerical-witness":
            if node["role"] in BLIND_ROLES:
                raise HostFailure("arithmetic execution must not receive a blinded review role")
            _keys(parameters, {"input_input", "claim_input", "census_input", "checker_input", "atol", "rtol"},
                  "Ravel tool parameters")
            bound = {}
            for key in ("input_input", "claim_input", "census_input", "checker_input"):
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("numerical witness inputs and checker must be explicitly hash-bound")
                bound[key] = pins[identity]
                if bound[key][0].stat().st_size > numerical_witness.MAX_BYTES:
                    raise HostFailure("numerical witness artifact exceeds checker byte bound")
            checker, checker_sha = bound["checker_input"]
            if checker != _safe_path(numerical_witness.__file__) or checker_sha != numerical_witness.checker_sha256():
                raise HostFailure("numerical witness checker differs from allowlisted source")
            for key in ("atol", "rtol"):
                _text(parameters[key], "arithmetic tolerance", 128)
                try:
                    if not 0 <= numerical_witness._number(parameters[key], claim=True) <= 1:
                        raise ValueError("tolerance outside arithmetic domain")
                except (ValueError, TypeError):
                    raise HostFailure("invalid numerical witness arithmetic tolerance") from None
            operation = lambda: self._witness_process(bound, parameters, control)
        elif action in {"allocator", "decision-case"}:
            expected = {"case_input", "horizon"} if action == "allocator" else {"case_input"}
            _keys(parameters, expected, "Ravel tool parameters")
            identity = parameters["case_input"]
            if type(identity) is not str or identity not in pins:
                raise HostFailure("Ravel tool case input is not bound")
            path, sha = pins[identity]
            case = read_json(path)
            if file_hash(path) != sha:
                raise HostFailure("Ravel tool case changed during read")
            if action == "allocator":
                operation = lambda: experiment_allocator.recommend(case, horizon=parameters["horizon"])
            else:
                case = decision_case.validate_case(case)
                allowed = {p: checksum for p, checksum in pins.values()}
                for claim in case["nodes"]:
                    for anchor in claim["anchors"]:
                        raw = Path(anchor["artifact"]["path"])
                        source = _safe_path(raw if raw.is_absolute() else path.parent / raw)
                        if source not in allowed or allowed[source] != anchor["artifact"]["sha256"] or file_hash(source) != allowed[source]:
                            raise HostFailure("decision anchor must match an explicitly hash-bound input")
                operation = lambda: decision_case.evaluate_case(case, path.parent)
        elif action == "review-index":
            self._packet(node)  # Source-private members cannot enter an on-demand catalogue.
            _keys(parameters, {"section","offset","max_bytes","query"}, "Ravel tool parameters")
            if node["packet"] is None: raise HostFailure("review-index requires a digest-bound packet")
            operation = lambda: review_context.read_index_page(node["packet"]["path"],
                expected_manifest_sha256=node["packet"]["manifest_sha256"], **parameters)
        elif action == "review-read":
            _keys(parameters, {"artifact_id"} | ({"offset", "max_bytes"} if "offset" in parameters or "max_bytes" in parameters else set()), "Ravel tool parameters")
            if node["packet"] is None:
                raise HostFailure("review-read requires a digest-bound packet")
            # Complete start/ending custody, then exact indexed bytes; no arbitrary path.
            packet = self._packet(node)
            found = next((artifact for artifact in packet["artifacts"] if artifact["id"] == parameters["artifact_id"]), None)
            if found is None or "presentation" in packet or "offset" in parameters:
                operation = lambda: review_context.read_artifact_page(node["packet"]["path"], parameters["artifact_id"],
                    expected_manifest_sha256=node["packet"]["manifest_sha256"],
                    offset=parameters.get("offset", 0), max_bytes=parameters.get("max_bytes", 65536))
            else:
                operation = lambda: found
        elif action == "quantities":
            _keys(parameters, {"contract_input", "records_input"}, "Ravel tool parameters")
            objects = {}
            for key in ("contract_input", "records_input"):
                identity = parameters[key]
                if type(identity) is not str or identity not in pins:
                    raise HostFailure("quantity inputs must be explicitly hash-bound")
                path, sha = pins[identity]
                objects[key] = read_json(path)
                if file_hash(path) != sha:
                    raise HostFailure("quantity input changed during read")
            contract, records = objects["contract_input"], objects["records_input"]
            if (type(contract) is not dict or type(records) is not list or not 1 <= len(records) <= 128
                    or type(contract.get("axes")) is not list or not 1 <= len(contract["axes"]) <= 4
                    or type(contract.get("bins")) is not list or not 1 <= len(contract["bins"]) <= 16
                    or type(contract.get("weight_names")) is not list or not 1 <= len(contract["weight_names"]) <= 4
                    or (len(contract["bins"]) + 2) * len(contract["weight_names"]) > 64):
                raise HostFailure("quantity case exceeds tiny supplied-calculation bounds")
            fills = 0
            for record in records:
                if type(record) is not dict or type(record.get("fills")) is not list or len(record["fills"]) > 16:
                    raise HostFailure("quantity record exceeds bounded fill count")
                fills += len(record["fills"])
            if fills > 1024:
                raise HostFailure("quantity case exceeds bounded total fill count")
            operation = lambda: quantities.calculate(contract, records)
        else:
            raise HostFailure("Ravel tool action is not allowlisted")
        public_request = {"request_id": request["request_id"], "action": action, "parameters": parameters,
                          "input_artifacts": request["input_artifacts"], "packet": node["packet"]}
        def execute():
            self._cancel(control)
            try:
                value = operation()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise HostFailure("Ravel deterministic tool rejected its bound input") from None
            if len(_json_bytes(value)) > self.max_response:
                raise HostFailure("Ravel deterministic tool response exceeds host byte bound")
            self._cancel(control)
            return {"kind": "ravel_tool_result", "action": action, "value": value,
                    "execution_authorized": False, "physics_validated": False}
        return control.call(action, "tool", public_request, execute)

    def _witness_process(self, bound, parameters, control):
        """Run only the source-bound standard-library checker in a fresh process."""
        checker, checker_sha = bound["checker_input"]
        command = [sys.executable, "-I", str(checker), "verify",
                   "--input", str(bound["input_input"][0]), "--claim", str(bound["claim_input"][0]),
                   "--original-source", str(bound["census_input"][0]), "--checker-sha256", checker_sha,
                   "--input-sha256", bound["input_input"][1], "--claim-sha256", bound["claim_input"][1],
                   "--original-source-sha256", bound["census_input"][1],
                   "--atol", parameters["atol"], "--rtol", parameters["rtol"]]
        self._cancel(control)
        started = time.monotonic()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True,
                                   env={"PATH": os.defpath, "LANG": "C.UTF-8"})
        try:
            while True:
                self._cancel(control)
                if time.monotonic() - started > min(self.timeout, 40):
                    raise HostFailure("numerical witness exceeded bounded wall time")
                try:
                    stdout, stderr = process.communicate(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if len(stdout) + len(stderr) > self.max_response:
                raise HostFailure("numerical witness response exceeds host byte bound")
        finally:
            if process.poll() is None:
                self._cleanup(process)
        for path, sha in bound.values():
            if file_hash(path) != sha:
                raise HostFailure("numerical witness input changed during execution")
        if process.returncode in (0, 1):
            receipt = _loads(stdout)
            _public(receipt)
            if (receipt.get("kind") != "numerical_witness_receipt"
                    or receipt.get("physics_validated") is not False
                    or receipt.get("status") not in {"verified", "mismatch", "unresolved"}
                    or (process.returncode == 0) != (receipt.get("status") == "verified")):
                raise HostFailure("numerical witness returned inconsistent receipt")
        elif process.returncode == 2:
            receipt = {"schema_version": 1, "kind": "numerical_witness_receipt", "status": "refused",
                       "arithmetic_verified": False, "physics_validated": False,
                       "reason": "independent checker refused bound input; inspect original artifacts"}
        else:
            raise HostFailure("numerical witness process did not complete its protocol")
        return {"receipt": receipt, "fresh_process": True, "checker_sha256": checker_sha,
                "child_exit_code": process.returncode, "input_bindings": {key: sha for key, (_, sha) in bound.items()},
                "execution_authorized": False, "physics_validated": False,
                "limitations": ["Local exact/tolerance arithmetic only; physical applicability and independent scientific review are separate.",
                                "Interpreter isolation is not an OS sandbox or proof of an admitted scientific environment."]}
