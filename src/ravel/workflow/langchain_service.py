"""Typed, local-observation LangChain service for an already running Graph node.

Only the canonical Graph attempt grants dispatch authority. Runnable schemas and
callbacks describe that service; the unchanged Host and Control own effects,
raw provider deliveries, budgets and ambiguous-call reconciliation. This is a
trusted in-process adapter, not an OS sandbox or actor authenticator.
"""
from __future__ import annotations

from contextvars import Context
from copy import deepcopy
from importlib.metadata import version
import math
from typing import Literal

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel

from .execution import file_hash
from .langchain_guard import GuardError as ServiceError, local_context as _local_context

REQUIRED = {"langchain-core": "1.6.7", "pydantic": "2.14.0"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InputPin(_Strict):
    id: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Packet(_Strict):
    path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Node(_Strict):
    id: str
    kind: Literal["model", "tool"]
    role: Literal["proposer", "critic", "improver", "verifier", "synthesizer", "designer", "executor",
                  "rdj_edge_reviewer", "rdj_critic", "rdj_verifier"]
    depends_on: list[str]
    inputs: list[InputPin]
    packet: Packet | None
    action: str
    parameters: dict[str, JsonValue]
    max_attempts: int = Field(ge=1, le=16)


class Dependency(_Strict):
    node_id: str
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Request(_Strict):
    schema_version: int = Field(ge=1, le=1)
    graph_id: str
    graph_revision: int = Field(ge=0)
    node_id: str
    generation: int = Field(ge=0)
    node_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_artifacts: list[InputPin]
    packet: Packet | None
    dependencies: list[Dependency]
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    goal_binding: dict[str, JsonValue] | None = None
    parent_task: dict[str, JsonValue] | None = None


class ServiceInput(_Strict):
    node: Node
    request: Request


class ServiceResult(RootModel[dict[str, JsonValue]]):
    """The original JSON Host delivery, without AIMessage/ToolMessage conversion."""
    model_config = ConfigDict(strict=True)


class _Options(_Strict):
    local_trace: bool = True


class ServiceConfig(_Strict):
    """Finite Runnable configuration; callbacks and cloud metadata are not inputs."""
    tags: list[str] = Field(default_factory=list, max_length=16)
    configurable: _Options = Field(default_factory=_Options)


def _json(value):
    """Reject non-JSON containers/type aliases before schema validation or hashing."""
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ServiceError("service JSON object keys must be strings")
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ServiceError("service values require actual JSON types")
        elif type(item) is float and not math.isfinite(item):
            raise ServiceError("service values must be finite")


def _same(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def identity():
    """Exact required framework versions plus the adapter source identity."""
    installed = {name: version(name) for name in REQUIRED}
    if installed != REQUIRED:
        raise ServiceError("charged service requires the declared LangChain/Pydantic versions")
    from . import langchain_guard
    return {"schema_version": 1, "runtime": installed, "source_sha256": file_hash(__file__),
            "guard_sha256": file_hash(langchain_guard.__file__)}


class _LocalTrace(BaseCallbackHandler):
    """Source-owned callback retains identities/hashes, never prompt/result bodies."""
    raise_error = True
    run_inline = True

    def __init__(self):
        self.events = []

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        from .agent_graph import digest
        self.events.append({"event": "start", "run_id": str(run_id), "input_sha256": digest(inputs)})

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        from .agent_graph import digest
        self.events.append({"event": "end", "run_id": str(run_id), "output_sha256": digest(outputs)})

    def on_chain_error(self, error, *, run_id, **kwargs):
        self.events.append({"event": "error", "run_id": str(run_id), "error_type": type(error).__name__})


class _BoundControl:
    """Reauthenticate the consumed envelope, then use the original Control.call."""
    def __init__(self, service, consumed):
        self._service, self._consumed = service, consumed
        original = service._control
        self.root, self.node_id, self.attempt_id = original.root, original.node_id, original.attempt_id

    def cancelled(self):
        return self._service._control.cancelled()

    def check_cancelled(self):
        return self._service._control.check_cancelled()

    def call(self, label, kind, request, function, output_tokens=0):
        self._service._current(self._consumed)

        def effect():
            # This check is after the real call reservation, immediately before
            # the Host's original effect. Exceptions retain that call outcome.
            try:
                self._service._current(self._consumed)
                _local_context()
            except Exception as exc:
                # Refused before the Host's effect was entered: nothing was dispatched,
                # so the reserved call closes as failed instead of staying ambiguous.
                exc.not_dispatched = True
                raise
            return function()

        return self._service._control.call(label, kind, request, effect, output_tokens=output_tokens)


class ChargedService:
    """One admitted attempt, typed Runnable input/output/config, local observations.

    The facade deliberately exposes only synchronous single invoke. Framework
    batch/stream/retry would create a second effect policy outside Graph custody.
    Schema reflection is available without granting any execution authority.
    """
    def __init__(self, host, node, request, control):
        from . import agent_graph as graph
        if type(control) is not graph.Control:
            raise ServiceError("charged service requires an actual Graph Control")
        envelope = {"node": node, "request": request}
        _json(envelope)
        ServiceInput.model_validate(envelope)
        self._host, self._control = host, control
        self._bound = deepcopy(envelope)
        self._host_sha = graph._host_identity(host)
        self._runtime = identity()
        self._entered = False
        self._observation = None
        self._current(envelope)
        self._runnable = RunnableLambda(self._perform, name="ravel_charged_service").with_types(
            input_type=ServiceInput, output_type=ServiceResult)

    def get_input_schema(self, config=None):
        return self._runnable.get_input_schema(config)

    def get_output_schema(self, config=None):
        return self._runnable.get_output_schema(config)

    def config_schema(self, **kwargs):
        if kwargs:
            raise ServiceError("charged service configuration schema takes no options")
        return ServiceConfig

    @property
    def observation(self):
        if self._observation is None:
            raise ServiceError("charged service has no completed observation")
        return deepcopy(self._observation)

    def _current(self, consumed):
        from . import agent_graph as graph
        _json(consumed)
        if not _same(consumed, self._bound):
            raise ServiceError("service envelope differs from the exact admitted node/request")
        if identity() != self._runtime:
            raise ServiceError("charged service runtime/source identity changed")
        if graph._host_identity(self._host) != self._host_sha:
            raise ServiceError("charged service Host identity changed")
        with graph.file_lock(self._control.root / "state.lock"):
            spec, state = graph._load(self._control.root)
            current = state["nodes"].get(self._control.node_id)
            if (current is None or current["status"] != "running"
                    or current["attempt_id"] != self._control.attempt_id):
                raise ServiceError("charged service attempt is not currently running")
            if state["cancelled"]:
                raise graph.Cancelled("graph cancelled; no further dispatch")
            graph._deadline(spec, state)
            node = next(item for item in spec["nodes"] if item["id"] == self._control.node_id)
            expected = {"node": node, "request": graph._request(spec, state, node, self._host_sha)}
            if not _same(consumed, expected):
                raise ServiceError("charged service canonical node/request/attempt changed")
            graph._artifact_checks(node)

    def _perform(self, envelope):
        self._current(envelope)
        consumed = deepcopy(envelope)
        result = self._host.execute(consumed["node"], consumed["request"], _BoundControl(self, consumed))
        self._current(consumed)
        _json(result)
        ServiceResult.model_validate(result)
        # No model_dump, AIMessage, parsed-text normalization or wrapper fields.
        return result

    def invoke(self, envelope, config=None, **kwargs):
        from .agent_graph import digest
        if kwargs:
            raise ServiceError("charged service invoke has no extra arguments")
        _json(envelope)
        ServiceInput.model_validate(envelope)
        self._current(envelope)
        options = {} if config is None else config
        _json(options)
        chosen = ServiceConfig.model_validate(options)
        if any(not tag.strip() or len(tag) > 80 for tag in chosen.tags):
            raise ServiceError("charged service tags must be bounded nonempty strings")
        if self._entered:
            raise ServiceError("charged service is single-use; reconcile through the original Graph")
        self._entered = True
        trace = _LocalTrace()
        fixed = {"callbacks": [trace] if chosen.configurable.local_trace else [],
                 "tags": list(chosen.tags), "recursion_limit": 1, "run_name": "ravel_charged_service",
                 "metadata": {"request_id": envelope["request"]["request_id"],
                              "node_sha256": envelope["request"]["node_sha256"],
                              "attempt_id": self._control.attempt_id}}

        def dispatch():
            _local_context()
            value = self._runnable.invoke(deepcopy(envelope), config=fixed)
            self._current(envelope)
            _local_context()
            return value

        result = Context().run(dispatch)
        self._observation = {"schema_version": 1, "runtime": self._runtime,
                             "request_id": envelope["request"]["request_id"],
                             "attempt_id": self._control.attempt_id, "host_sha256": self._host_sha,
                             "input_sha256": digest(envelope), "result_sha256": digest(result),
                             "config": chosen.model_dump(), "events": deepcopy(trace.events),
                             "effect_authority": "agent_graph.Control.call", "scientific_acceptance": False}
        return result

    def with_retry(self, *args, **kwargs):
        raise ServiceError("retry belongs to the canonical Graph, never a Runnable wrapper")

    def with_fallbacks(self, *args, **kwargs):
        raise ServiceError("charged service has no framework effect fallback")

    def batch(self, *args, **kwargs):
        raise ServiceError("charged service requires one current attempt per invoke")

    def stream(self, *args, **kwargs):
        raise ServiceError("charged service requires a complete receipted result")
