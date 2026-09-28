"""A local, SYNTHETIC Anthropic Messages API for the HP-13 offline rehearsal and for tests (smoke spec WI-7c, R5).

``MockMessagesAPI`` serves ``POST /v1/messages`` (server-sent events when the body asks to stream, one JSON
message otherwise) and ``POST /v1/messages/count_tokens`` on 127.0.0.1 from a script of turns, in a thread the
caller owns and stops by handle (``stop``). It never contacts anything. Every other path gets a JSON 404 and is
recorded, so the rehearsal learns which other endpoints a pinned CLI calls when ``ANTHROPIC_BASE_URL`` points
here.

A request is a MAIN-loop request when its body offers tools; its position in the conversation is the number of
assistant messages it carries, and the script answers position k with ``turns[k]`` (the last turn repeats).
Anything else (a side query without tools: a title, a quota check) is AUXILIARY and gets one short text reply.
A turn can first answer with HTTP 529 ``overloaded`` a given number of times (the retry probe).

Records (``requests()``), per request: seq, method, path (query string dropped), the header NAMES (lowercased,
sorted; never a value: an Authorization or x-api-key value is a credential), the body's top-level key names, and
whitelisted body facts: model, max_tokens, stream, the offered tool names, thinking, output_config, speed, effort,
temperature, top_p, top_k, tool_choice type, the number of messages, the conversation position, the prompt-cache
TTLs its cache_control markers ask for (``cache_ttls``: each marker's ``ttl``, or "default" without one), and the
role ("main", "auxiliary", "count_tokens" or "other"). Never the system prompt, the messages, a tool result or a
header value. A turn's usage may also carry ``inference_geo`` (a string) and ``cache_creation`` (the TTL breakdown),
passed through as the API reports them. Standard library only.
"""
from __future__ import annotations

import http.server
import json
import socketserver
import threading
import uuid
from dataclasses import dataclass, field

BODY_FACTS = ("model", "max_tokens", "stream", "thinking", "output_config", "speed", "effort", "temperature",
              "top_p", "top_k")
MAX_BODY = 32 << 20
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
USAGE_EXTRAS = ("inference_geo", "cache_creation")   # passed through unchanged when a turn reports them


def cache_ttls(body) -> list:
    """The sorted TTLs of every cache_control marker in a request body (system, tools and message content blocks):
    each marker's ``ttl``, or "default" when it names none."""
    found = set()

    def visit(value):
        if isinstance(value, dict):
            control = value.get("cache_control")
            if isinstance(control, dict):
                found.add(control.get("ttl") if isinstance(control.get("ttl"), str) else "default")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    for key in ("system", "tools", "messages"):
        visit(body.get(key))
    return sorted(found)


@dataclass
class Turn:
    """One scripted assistant turn. ``blocks``: [{"type": "text", "text"}] and/or
    [{"type": "tool_use", "name", "input"}] (an id is assigned). ``usage``: the counts reported for this turn
    (message_start carries the input and cache counts, message_delta the output count). ``overloaded``: answer
    this position with HTTP 529 that many times first. ``stop_reason`` defaults to tool_use when a tool is
    called, else end_turn. ``speed``: a usage speed to report (the fast-mode probe)."""
    blocks: list
    usage: dict = field(default_factory=lambda: {"input_tokens": 100, "output_tokens": 20})
    overloaded: int = 0
    stop_reason: str | None = None
    speed: str | None = None


def text(message: str, **kw) -> Turn:
    return Turn([{"type": "text", "text": message}], **kw)


def tool(name: str, tool_input: dict, **kw) -> Turn:
    return Turn([{"type": "tool_use", "name": name, "input": tool_input}], **kw)


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def server_bind(self):   # no reverse DNS lookup (loopback only)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ravel-mock-messages"
    sys_version = ""
    timeout = 30   # an idle kept-alive connection is dropped, so stop() (which joins handlers) stays bounded

    def log_message(self, *args):
        pass

    def _reply(self, status, payload: dict, headers=()):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("request-id", f"req_synthetic_{uuid.uuid4().hex[:16]}")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return None
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _dispatch(self):
        mock = self.server.mock
        path = self.path.split("?", 1)[0]
        body = self._body() if self.command in ("POST", "PUT", "PATCH") else {}
        record = mock._record(self.command, path, sorted({k.lower() for k in self.headers.keys()}), body)
        if self.command == "POST" and path == "/v1/messages/count_tokens" and body is not None:
            record["role"] = "count_tokens"
            return self._reply(200, {"input_tokens": 100})
        if self.command == "POST" and path == "/v1/messages" and body is not None:
            return mock._answer(self, body, record)
        record["role"] = "other"
        return self._reply(404, {"type": "error", "error": {"type": "not_found_error",
                                                            "message": "SYNTHETIC mock: no such endpoint"}})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _dispatch


class MockMessagesAPI:
    """The mock server; ``start()`` returns its base URL (``http://127.0.0.1:<port>``)."""

    def __init__(self, turns=None, *, auxiliary_text="SYNTHETIC auxiliary reply"):
        self._lock = threading.Lock()
        self._turns, self._requests, self._attempts = list(turns or [text("SYNTHETIC done")]), [], {}
        self._auxiliary_text = auxiliary_text
        self._server = self._thread = None

    # -- lifecycle (owned by the caller; stopped by handle, never by a signal) ----------------------------------
    def start(self) -> str:
        server = _Server(("127.0.0.1", 0), _Handler)
        server.mock = self
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="ravel-mock-messages", daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{server.server_address[1]}"

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def stop(self, join_timeout=10.0) -> None:
        server, thread = self._server, self._thread
        if server is None:
            return
        server.shutdown()
        server.server_close()
        thread.join(join_timeout)
        self._server = self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # -- script and log ---------------------------------------------------------------------------------------
    def set_script(self, turns) -> None:
        """Replace the script and clear the log (one CLI session per script)."""
        with self._lock:
            self._turns, self._requests, self._attempts = list(turns), [], {}

    def requests(self) -> list:
        with self._lock:
            return json.loads(json.dumps(self._requests))

    def _record(self, method, path, header_names, body) -> dict:
        record = {"seq": None, "method": method, "path": path, "header_names": header_names,
                  "body_keys": sorted(body) if isinstance(body, dict) else None, "role": None}
        if isinstance(body, dict):
            record.update({name: body.get(name) for name in BODY_FACTS if name in body})
            tools = body.get("tools")
            record["tools"] = sorted(t.get("name") for t in tools if isinstance(t, dict)
                                     and isinstance(t.get("name"), str)) if isinstance(tools, list) else None
            choice = body.get("tool_choice")
            record["tool_choice"] = choice.get("type") if isinstance(choice, dict) else None
            messages = body.get("messages") if isinstance(body.get("messages"), list) else []
            record["messages"] = len(messages)
            record["position"] = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "assistant")
            record["cache_ttls"] = cache_ttls(body)
        with self._lock:
            record["seq"] = len(self._requests) + 1
            self._requests.append(record)
        return record

    # -- answers ------------------------------------------------------------------------------------------------
    def _answer(self, handler, body, record):
        model = body.get("model") if isinstance(body.get("model"), str) else "synthetic-unknown-model"
        if not body.get("tools"):
            record["role"] = "auxiliary"
            turn, position = text(self._auxiliary_text, usage={"input_tokens": 10, "output_tokens": 5}), None
        else:
            record["role"] = "main"
            position = record["position"]
            with self._lock:
                turn = self._turns[min(position, len(self._turns) - 1)]
                seen = self._attempts.get(position, 0)
                self._attempts[position] = seen + 1
            if seen < turn.overloaded:
                record["answered"] = 529
                return handler._reply(529, {"type": "error", "error": {"type": "overloaded_error",
                                                                       "message": "SYNTHETIC mock overload"}})
        record["answered"] = 200
        message_id = f"msg_synthetic_{uuid.uuid4().hex[:20]}"
        blocks = []
        for block in turn.blocks:
            if block["type"] == "tool_use":
                blocks.append({"type": "tool_use", "id": f"toolu_synthetic_{uuid.uuid4().hex[:20]}",
                               "name": block["name"], "input": block["input"]})
            else:
                blocks.append({"type": "text", "text": block["text"]})
        stop = turn.stop_reason or ("tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn")
        usage = {k: int(turn.usage.get(k, 0)) for k in USAGE_KEYS}
        usage.update({k: turn.usage[k] for k in USAGE_EXTRAS if k in turn.usage})
        if turn.speed is not None:
            usage["speed"] = turn.speed
        if body.get("stream"):
            return self._stream(handler, model, message_id, blocks, stop, usage)
        return handler._reply(200, {"id": message_id, "type": "message", "role": "assistant", "model": model,
                                    "content": blocks, "stop_reason": stop, "stop_sequence": None, "usage": usage})

    @staticmethod
    def _stream(handler, model, message_id, blocks, stop, usage):
        start_usage = {**usage, "output_tokens": min(1, usage["output_tokens"])}
        events = [("message_start", {"type": "message_start", "message": {
            "id": message_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": start_usage}})]
        for index, block in enumerate(blocks):
            if block["type"] == "tool_use":
                events.append(("content_block_start", {"type": "content_block_start", "index": index,
                                                       "content_block": {**block, "input": {}}}))
                events.append(("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(block["input"])}}))
            else:
                events.append(("content_block_start", {"type": "content_block_start", "index": index,
                                                       "content_block": {"type": "text", "text": ""}}))
                events.append(("content_block_delta", {"type": "content_block_delta", "index": index,
                                                       "delta": {"type": "text_delta", "text": block["text"]}}))
            events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
        # As the API streams: message_start carries the input and cache counts (with a placeholder output count),
        # message_delta the final output count, so a client that overwrites per field never double-counts.
        delta_usage = {"output_tokens": usage["output_tokens"], **{k: usage[k] for k in ("speed", "inference_geo")
                                                                    if k in usage}}
        events.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop,
                                                                             "stop_sequence": None},
                                         "usage": delta_usage}))
        events.append(("message_stop", {"type": "message_stop"}))
        payload = b"".join(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode() for name, data in events)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("request-id", f"req_synthetic_{uuid.uuid4().hex[:16]}")
        handler.end_headers()
        handler.wfile.write(payload)


def parse_sse(data: bytes) -> list:
    """(event name, JSON data) pairs of a server-sent event stream (for tests and the mock CLI)."""
    events = []
    for chunk in data.decode("utf-8").split("\n\n"):
        name, payload = None, []
        for line in chunk.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                payload.append(line[5:].strip())
        if name is not None:
            events.append((name, json.loads("\n".join(payload)) if payload else None))
    return events
