"""Actual loopback HTTP and tiny-process controls for the stateless agent host."""
from contextlib import contextmanager
from copy import deepcopy
import http.server
import hashlib
import json
from pathlib import Path
import shutil
import sys
import threading
import time

import pytest

from ravel.workflow import agent_host as host, execution, review_context
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import run, opened


BASE = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


class Control:
    def __init__(self):
        self.cancel = threading.Event()
        self.calls = []
        self.saved = {}

    def cancelled(self):
        return self.cancel.is_set()

    def check_cancelled(self):
        if self.cancelled():
            raise RuntimeError("canceled")

    def call(self, label, kind, request, function, output_tokens=0):
        key = (label, execution.digest(request))
        if key in self.saved:
            return deepcopy(self.saved[key])
        self.calls.append({"label": label, "kind": kind, "request": deepcopy(request), "output_tokens": output_tokens})
        value = function()
        self.saved[key] = deepcopy(value)
        return value


def node(*, action="responses", role="proposer", inputs=(), packet=None, parameters=None):
    return {"id": "n1", "kind": "model", "role": role, "depends_on": [], "inputs": list(inputs), "packet": packet,
            "action": action, "parameters": parameters or {"instructions": "Inspect public evidence and return the answer.",
                "model": "requested-model", "reasoning_effort": "low", "max_output_tokens": 120,
                "output_schema": deepcopy(SCHEMA)}, "max_attempts": 1}


def request(n):
    return {"schema_version": 1, "graph_id": "g", "graph_revision": "a" * 64, "node_id": n["id"],
            "generation": 1, "node_sha256": execution.digest(n), "request_id": "b" * 64,
            "input_artifacts": deepcopy(n["inputs"]), "packet": deepcopy(n["packet"]), "dependencies": []}


def pin(path, identity="case"):
    return {"id": identity, "path": str(path.resolve()), "sha256": execution.file_hash(path)}


def response(value=None, **changes):
    result = {"id": "resp-public", "model": "requested-model-snapshot", "status": "completed",
              "usage": {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20,
                        "output_tokens_details": {"reasoning_tokens": 5}},
              "output": [{"type": "reasoning", "summary": [{"text": "PRIVATE-CANARY"}],
                          "encrypted_content": "ENCRYPTED-CANARY"},
                         {"type": "message", "role": "assistant", "status": "completed",
                          "content": [{"type": "output_text", "text": json.dumps(value or {"answer": "supported fixture"}),
                                      "annotations": [{"canary": "ANNOTATION-CANARY"}]}]}]}
    result.update(changes)
    return result


class ScriptedReviewHost(host.AgentHost):
    """Exercise real packet tools inside a scripted stateless model invocation."""

    def __init__(self, *, read_mode="complete", **kwargs):
        super().__init__(**kwargs)
        self.read_mode = read_mode
        self.contexts = []

    def _responses(self, data, parameters, request, control, **kwargs):
        context = json.loads(json.loads(data)["input"][0]["content"])
        self.contexts.append(context)
        packet = request["packet"]
        manifest = review_context.verify_packet(packet["path"],
            expected_manifest_sha256=packet["manifest_sha256"])
        inline = {entry["id"] for entry in context["review_packet"]["artifacts"]}
        mode = self.read_mode
        if mode == "second_missing":
            mode = "complete" if len(self.contexts) == 1 else "missing"
        read_packet = packet
        if mode == "foreign":
            foreign = Path(packet["path"]).parent / (Path(packet["path"]).name + "-foreign")
            shutil.copytree(packet["path"], foreign)
            read_packet = {**packet, "path": str(foreign)}
        if mode != "missing":
            for entry in manifest["artifacts"]:
                if entry["id"] in inline:
                    continue
                offset = 0
                while True:
                    tool_node = tool("review-read", {"artifact_id": entry["id"],
                        "offset": offset, "max_bytes": 65536}, packet=read_packet)
                    tool_request = globals()["request"](tool_node)
                    page = self.execute(tool_node, tool_request, Control())["value"]
                    if mode == "partial" or page["complete"]:
                        break
                    assert page["next_offset"] > offset
                    offset = page["next_offset"]
        fields = parameters["output_schema"]["properties"]
        if "stage" in fields:
            value = {key: fields[key]["const"] for key in ("stage", "role_id", "subject_sha256")}
            value.update(verdict="accept", findings=[], attributed_claim_ids=[])
        else:
            value = {"answer": "supported fixture"}
        result = self._result(value, parameters, request, observed_model=parameters["model"],
            response_id="scripted-" + request["request_id"],
            usage={"input_tokens": 13, "output_tokens": 7, "total_tokens": 20})
        result["transport"].update(actor_id="scripted-role-" + request["request_id"],
            invocation_id="scripted-invocation-" + request["request_id"])
        return result


def corrupt_review_pages(monkeypatch):
    """A self-consistent page hash cannot authenticate altered whole-artifact bytes."""
    actual = review_context.read_artifact_page
    def altered(*args, **kwargs):
        page = actual(*args, **kwargs)
        assert page["content_encoding"] == "utf-8"
        content = page["content"]
        page["content"] = ("y" if content[0] != "y" else "z") + content[1:]
        page["page_sha256"] = hashlib.sha256(page["content"].encode()).hexdigest()
        return page
    monkeypatch.setattr(review_context, "read_artifact_page", altered)


def deferred_packet(tmp_path):
    packet = tmp_path / "packet"
    (packet / "artifacts").mkdir(parents=True)
    artifacts = []
    for identity, content in (("public_case", "A bounded public case."),
                              ("source-large", "x" * (host.INLINE_TEXT_BUDGET + 131072))):
        source = tmp_path / (identity + ".txt")
        source.write_text(content)
        copy = packet / "artifacts" / source.name
        copy.write_bytes(source.read_bytes())
        artifacts.append({"id": identity, "path": "artifacts/" + copy.name,
            "sha256": execution.file_hash(copy), "source_sha256": execution.file_hash(source),
            "source_path": str(source), "projection": "full_authenticated_source_or_evidence"})
    manifest = {"schema_version": 1, "role": "critic", "artifacts": artifacts,
                "omissions": [], "findings": [], "reviews": []}
    manifest["sha256"] = execution.digest(manifest)
    atomic_json(packet / "manifest.json", manifest)
    return {"path": str(packet), "manifest_sha256": manifest["sha256"]}, manifest


@pytest.mark.parametrize("mode", ["complete", "missing", "partial", "digest", "foreign"])
def test_deferred_review_receipt_requires_complete_authenticated_reads(tmp_path, monkeypatch, mode):
    packet, manifest = deferred_packet(tmp_path)
    if mode == "digest":
        corrupt_review_pages(monkeypatch)
    adapter = ScriptedReviewHost(read_mode=mode)
    n = node(role="critic", packet=packet)
    result = adapter.execute(n, request(n), Control())
    presentation = result["isolation"]["evidence_presentation"]
    assert presentation["presentation"]["deferred_count"] == 1
    inline = adapter.contexts[0]["review_packet"]["artifacts"]
    assert presentation["presented_subject_sha256s"] == sorted({
        hashlib.sha256(entry["content"].encode()).hexdigest() for entry in inline})
    expected = {"manifest_sha256": packet["manifest_sha256"], "artifacts": [{
        "id": entry["id"], "sha256": entry["sha256"],
        "bytes": (Path(packet["path"]) / entry["path"]).stat().st_size}
        for entry in sorted(manifest["artifacts"], key=lambda entry: entry["id"])
        if entry["id"] not in {row["id"] for row in inline}]}
    if mode == "complete":
        assert presentation["deferred_content_read"] == expected
    else:
        assert presentation["deferred_content_read"] is False


def test_deferred_review_reads_do_not_carry_into_next_role_invocation(tmp_path):
    packet, _ = deferred_packet(tmp_path)
    adapter = ScriptedReviewHost(read_mode="second_missing")
    n = node(role="critic", packet=packet)
    first = adapter.execute(n, request(n), Control())
    assert isinstance(first["isolation"]["evidence_presentation"]["deferred_content_read"], dict)
    second_node = deepcopy(n)
    second_node["id"] = "n2"
    second = adapter.execute(second_node, request(second_node), Control())
    assert len(adapter.contexts) == 2
    assert second["isolation"]["evidence_presentation"]["deferred_content_read"] is False


@contextmanager
def server(document=None, *, status=200, handler=None):
    seen = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(raw)})
            if handler is not None:
                handler(self)
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(document or response()).encode())

        def log_message(self, *args):
            pass
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/v1/responses", seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=2)


def test_actual_responses_transport_is_stateless_and_only_retains_public_output(tmp_path):
    evidence = tmp_path / "data.json"; atomic_json(evidence, {"measurement": 2})
    n = node(inputs=[pin(evidence, "measurement")])
    control = Control()
    with server() as (endpoint, seen):
        adapter = host.AgentHost(endpoint=endpoint, api_key="TEST-KEY")
        result = adapter.execute(n, request(n), control)
        assert adapter.execute(n, request(n), control) == result
    assert len(seen) == len(control.calls) == 1
    sent = seen[0]["body"]
    assert seen[0]["path"] == "/v1/responses"
    assert seen[0]["headers"]["Authorization"] == "Bearer TEST-KEY"
    assert sent["model"] == "requested-model" and sent["reasoning"] == {"effort": "low"}
    assert sent["max_output_tokens"] == control.calls[0]["output_tokens"] == 120
    assert sent["store"] is sent["stream"] is False and sent["tools"] == []
    assert "previous_response_id" not in sent and "conversation" not in sent and "include" not in sent
    assert sent["text"]["format"] == {"type": "json_schema", "name": "public_record", "strict": True, "schema": SCHEMA}
    assert len(sent["input"]) == 1 and sent["input"][0]["role"] == "user"
    assert result["value"] == {"answer": "supported fixture"}
    assert result["transport"]["observed_model"] == "requested-model-snapshot"
    assert result["transport"]["execution_mode"] == "responses_http_loopback_control"
    assert result["transport"]["endpoint_origin"] == endpoint.removesuffix("/v1/responses")
    assert result["usage"] == {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20}
    saved = json.dumps([control.calls, list(control.saved.values())])
    for canary in ("TEST-KEY", "PRIVATE-CANARY", "ENCRYPTED-CANARY", "ANNOTATION-CANARY"):
        assert canary not in saved
    assert result["execution_authorized"] is result["physics_validated"] is False


def test_blind_role_uses_only_matching_frozen_packet(run, tmp_path):
    root, _ = run; opened(run)
    out = tmp_path / "critic-packet"
    manifest = review_context.create(root, "critic", out)
    raw = tmp_path / "producer.txt"; raw.write_text("RAW-PRODUCER-CANARY")
    n = node(role="critic", inputs=[pin(raw, "producer")], packet={"path": str(out), "manifest_sha256": manifest["sha256"]})
    with server() as (endpoint, seen):
        result = host.AgentHost(endpoint=endpoint).execute(n, request(n), Control())
    context = json.loads(seen[0]["body"]["input"][0]["content"])
    assert "input_artifacts" not in context
    assert "RAW-PRODUCER-CANARY" not in json.dumps(seen)
    assert context["review_packet"]["context"]["role"] == "critic"
    assert context["review_packet"]["context"]["reviews"] == []
    assert result["isolation"]["parent_transcript_supplied"] is False
    assert result["transport"]["context_manifest_sha256"] == manifest["sha256"]
    changed = deepcopy(n); changed["role"] = "verifier"
    with pytest.raises(host.HostFailure, match="role does not match"):
        host.AgentHost().execute(changed, request(changed), Control())
    changed = deepcopy(n); changed["packet"]["manifest_sha256"] = "0" * 64
    with pytest.raises(host.HostFailure, match="creation digest"):
        host.AgentHost().execute(changed, request(changed), Control())


@pytest.mark.parametrize("role", ["critic", "verifier", "physics_critic", "skeptical_verifier"])
def test_reviewers_require_packet_before_any_call(role):
    control = Control(); n = node(role=role)
    with pytest.raises(host.HostFailure, match="digest-bound review packet"):
        host.AgentHost().execute(n, request(n), control)
    assert control.calls == []


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.update(status="incomplete"), "not a completed"),
    (lambda d: d.update(status="failed"), "not a completed"),
    (lambda d: d["output"].append({"type": "function_call", "arguments": "SECRET"}), "unsupported public item"),
    (lambda d: d["output"][-1]["content"][0].update(type="refusal", text="SECRET"), "refusal"),
    (lambda d: d["output"].pop(), "one public"),
    (lambda d: d["output"].append(deepcopy(d["output"][-1])), "one public"),
    (lambda d: d["output"][-1]["content"][0].update(text='{"answer":"a","answer":"b"}'), "malformed public"),
    (lambda d: d["output"][-1]["content"][0].update(text='{"answer": NaN}'), "malformed public"),
    (lambda d: d["output"][-1]["content"][0].update(text='{"answer":"a","extra":"b"}'), "fields"),
    (lambda d: d["output"][-1]["content"][0].update(text='{"answer":3}'), "match output schema"),
    (lambda d: d["usage"].update(output_tokens=True), "provider token usage"),
    (lambda d: d["usage"].update(output_tokens=-1), "provider token usage"),
    (lambda d: d["usage"].update(total_tokens=19), "inconsistent provider"),
    (lambda d: d.pop("model"), "observed model"),
    (lambda d: d.pop("id"), "response identity"),
    (lambda d: d["usage"].update(input_tokens=13, output_tokens=121, total_tokens=134), "exceeds declared bound"),
])
def test_bad_responses_do_not_become_success_or_retry(mutate, match):
    document = response(); mutate(document)
    n = node(); control = Control()
    with server(document) as (endpoint, seen):
        with pytest.raises(host.HostFailure, match=match):
            host.AgentHost(endpoint=endpoint).execute(n, request(n), control)
    assert len(seen) == len(control.calls) == 1 and not control.saved


def test_reasoning_only_and_private_json_fields_are_rejected():
    n = node(); n["parameters"]["output_schema"] = None
    with server(response({"private_reasoning": "CANARY"})) as (endpoint, _):
        with pytest.raises(host.HostFailure, match="private reasoning fields"):
            host.AgentHost(endpoint=endpoint).execute(n, request(n), Control())


@pytest.mark.parametrize("endpoint", ["http://example.com/v1/responses", "ftp://127.0.0.1/a", "https://user:secret@example.com/a",
                                       "https://example.com/a?secret=x", "https://example.com/a#x", "https://example.com"])
def test_endpoint_restrictions(endpoint):
    with pytest.raises(host.HostFailure):
        host.AgentHost(endpoint=endpoint)


def test_redirect_and_error_body_are_never_followed_or_retained():
    def redirect(h):
        h.send_response(307, "SECRET-REASON"); h.send_header("Location", "http://127.0.0.1:1/secret"); h.end_headers()
        h.wfile.write(b"SECRET-BODY")
    n = node()
    with server(handler=redirect) as (endpoint, seen):
        with pytest.raises(host.HostFailure) as failure:
            host.AgentHost(endpoint=endpoint, api_key="SECRET-KEY").execute(n, request(n), Control())
    assert str(failure.value) == "Responses endpoint returned HTTP 307"
    assert len(seen) == 1 and failure.value.retryable is False


def test_sent_timeout_is_ambiguous_and_never_automatically_retried():
    received = threading.Event()
    def wait(h):
        received.set(); time.sleep(.2)
    n = node(); control = Control()
    with server(handler=wait) as (endpoint, seen):
        with pytest.raises(host.HostFailure) as failure:
            host.AgentHost(endpoint=endpoint, timeout_seconds=.04).execute(n, request(n), control)
    assert received.is_set() and len(seen) == len(control.calls) == 1
    assert failure.value.ambiguous is True and failure.value.retryable is False


def test_http_trickle_cannot_extend_whole_call_deadline():
    def trickle(h):
        h.send_response(200); h.end_headers()
        try:
            for _ in range(30):
                h.wfile.write(b" "); h.wfile.flush(); time.sleep(.02)
        except OSError:
            pass
    n = node()
    with server(handler=trickle) as (endpoint, seen):
        before = time.monotonic()
        with pytest.raises(host.HostFailure) as failure:
            host.AgentHost(endpoint=endpoint, timeout_seconds=.08).execute(n, request(n), Control())
        assert time.monotonic() - before < .4
    assert len(seen) == 1 and failure.value.ambiguous is True


def test_cancellation_fences_received_success():
    control = Control()
    def cancel(h):
        control.cancel.set(); h.send_response(200); h.end_headers(); h.wfile.write(json.dumps(response()).encode())
    n = node()
    with server(handler=cancel) as (endpoint, seen):
        with pytest.raises(host.HostFailure, match="canceled") as failure:
            host.AgentHost(endpoint=endpoint).execute(n, request(n), control)
    assert len(seen) == 1 and not control.saved and failure.value.ambiguous is True


def test_cancel_before_dispatch_and_unsupported_schema_do_not_reserve_call():
    n = node(); control = Control(); control.cancel.set()
    with pytest.raises(host.HostFailure, match="before dispatch"):
        host.AgentHost().execute(n, request(n), control)
    control.cancel.clear(); n["parameters"]["output_schema"]["$ref"] = "#/unknown"
    with pytest.raises(host.HostFailure, match="unsupported output schema"):
        host.AgentHost().execute(n, request(n), control)
    assert control.calls == []
    n = node(); n["parameters"]["max_output_tokens"] = 15
    with pytest.raises(host.HostFailure, match="output token bound"):
        host.AgentHost().execute(n, request(n), control)
    assert control.calls == []


def test_explicit_config_reads_only_named_environment_and_never_embeds_key(monkeypatch):
    monkeypatch.setenv("TEST_HOST_KEY", "SECRET-SELECTED")
    adapter = host.AgentHost.from_config({"type": "responses", "api_key_env": "TEST_HOST_KEY"})
    assert adapter.endpoint.geturl() == host.DEFAULT_ENDPOINT
    assert adapter._api_key == "SECRET-SELECTED"
    with pytest.raises(host.HostFailure, match="unsupported host config"):
        host.AgentHost.from_config({"type": "responses", "api_key": "SECRET"})


def test_command_actual_protocol_is_correlated_and_has_explicit_environment(monkeypatch):
    monkeypatch.setenv("SECRET_PARENT_KEY", "SHOULD-NOT-BE-INHERITED")
    code = 'import json,os,sys; r=json.load(sys.stdin); print(json.dumps({"request_id":r["request_id"],"value":{"answer":os.environ.get("SECRET_PARENT_KEY","absent")},"usage":None}))'
    adapter = host.AgentHost.from_config({"type": "command", "command": [sys.executable, "-c", code]})
    n = node(action="command"); result = adapter.execute(n, request(n), Control())
    assert result["value"] == {"answer": "absent"}
    assert result["transport"]["observed_model"] is None
    assert result["usage"]["total_tokens"] is None
    assert result["isolation"]["os_sandbox"] is False
    assert "Trusted command" in result["isolation"]["limitation"]


@pytest.mark.parametrize("body,match", [
    ('print("not JSON")', "malformed public"),
    ('print("{\\\"request_id\\\":\\\"wrong\\\",\\\"value\\\":{},\\\"usage\\\":null}")', "identity"),
    ('print("{}"); sys.exit(3)', "nonzero exit"),
    ('print("{\\\"request_id\\\":1,\\\"request_id\\\":2}")', "malformed public"),
])
def test_command_bad_protocol_and_nonzero_exit_never_clear(body, match):
    n = node(action="command"); control = Control()
    adapter = host.AgentHost(adapter="command", command=[sys.executable, "-c", "import sys; " + body])
    with pytest.raises(host.HostFailure, match=match):
        adapter.execute(n, request(n), control)
    assert len(control.calls) == 1 and not control.saved


def test_command_blind_roles_refused_even_with_valid_packet(run, tmp_path):
    opened(run); out = tmp_path / "critic"
    manifest = review_context.create(run[0], "critic", out)
    n = node(action="command", role="critic", packet={"path": str(out), "manifest_sha256": manifest["sha256"]})
    control = Control()
    with pytest.raises(host.HostFailure, match="no OS sandbox"):
        host.AgentHost(adapter="command", command=[sys.executable, "-c", "pass"]).execute(n, request(n), control)
    assert not control.calls


def test_command_output_flood_is_bounded_and_killed():
    n = node(action="command"); control = Control()
    adapter = host.AgentHost(adapter="command", command=[sys.executable, "-c", "import sys,time; sys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(10)"],
                             max_response_bytes=128, timeout_seconds=1)
    before = time.monotonic()
    with pytest.raises(host.HostFailure, match="byte bound") as failure:
        adapter.execute(n, request(n), control)
    assert time.monotonic() - before < 3 and failure.value.ambiguous is True


@pytest.mark.parametrize("empty_reads", [0, 1])
def test_command_cancellation_terminates_owned_group(tmp_path, monkeypatch, empty_reads):
    marker = tmp_path / "pid.txt"
    real_read_text = Path.read_text
    pending_empty_reads = empty_reads
    def read_text(path, *args, **kwargs):
        nonlocal pending_empty_reads
        if path == marker and pending_empty_reads:
            pending_empty_reads -= 1
            return ""  # The child has created the file but has not written its PID yet.
        return real_read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read_text)
    code = "import os,time,pathlib; pathlib.Path(" + repr(str(marker)) + ").write_text(str(os.getpid())); time.sleep(10)"
    adapter = host.AgentHost(adapter="command", command=[sys.executable, "-c", code], timeout_seconds=2)
    n = node(action="command"); control = Control(); captured = []
    def execute():
        try:
            adapter.execute(n, request(n), control)
        except host.HostFailure as exc:
            captured.append(exc)
    thread = threading.Thread(target=execute); thread.start()
    try:
        deadline = time.monotonic() + 2
        pid_text = ""
        while time.monotonic() < deadline:
            if marker.exists():
                pid_text = marker.read_text()
                if pid_text:
                    break
            time.sleep(.01)
        assert pid_text, "command did not publish its PID before cancellation"
        pid = int(pid_text)
    finally:
        control.cancel.set()
        thread.join(timeout=3)
    assert not thread.is_alive() and captured[0].ambiguous is True
    assert "canceled" in str(captured[0])
    assert execution.process_identity(pid) is None
    assert not control.saved


def tool(action, parameters, inputs=(), packet=None):
    n = node(inputs=inputs, packet=packet)
    n.update(kind="tool", action=action, parameters=parameters)
    return n


def test_allocator_adapter_reuses_actual_authoritative_function():
    from ravel.workflow import experiment_allocator
    path = BASE / "prototypes/experiment-allocation-case.json"
    n = tool("allocator", {"case_input": "case", "horizon": None}, [pin(path)])
    control = Control(); result = host.AgentHost().execute(n, request(n), control)
    assert result["value"] == experiment_allocator.recommend(read_json(path))
    assert control.calls[0]["kind"] == "tool"
    assert result["value"]["execution_authorized"] is False


def test_decision_adapter_requires_every_anchor_hash_bound_before_call():
    case = BASE / "recipe-restoration-case.json"
    n = tool("decision-case", {"case_input": "case"}, [pin(case)])
    control = Control()
    with pytest.raises(host.HostFailure, match="explicitly hash-bound"):
        host.AgentHost(bound_roots=[str(BASE)]).execute(n, request(n), control)
    assert not control.calls
    for index, path in enumerate((BASE / "recipe.json", BASE / "data/baseline.json", BASE / "data/clean.json")):
        n["inputs"].append(pin(path, f"anchor{index}"))
    result = host.AgentHost().execute(n, request(n), Control())
    assert result["value"]["status"] == "supported"
    assert result["value"]["logical_entailment_proven"] is False


def test_review_read_adapter_uses_complete_packet_custody_and_allowlist(run, tmp_path):
    opened(run); out = tmp_path / "packet"
    manifest = review_context.create(run[0], "critic", out)
    selected = manifest["artifacts"][0]["id"]
    n = tool("review-read", {"artifact_id": selected}, packet={"path": str(out), "manifest_sha256": manifest["sha256"]})
    result = host.AgentHost().execute(n, request(n), Control())
    assert result["value"]["content"].encode() == review_context.read_artifact(out, selected, expected_manifest_sha256=manifest["sha256"])
    n["parameters"]["artifact_id"] = "../../inputs/checkin2.json"
    with pytest.raises(host.HostFailure, match="Ravel deterministic tool rejected its bound input") as refusal:
        host.AgentHost().execute(n, request(n), Control())
    assert isinstance(refusal.value.__context__, ValueError)
    assert "artifact ID is absent or ambiguous in this role's context" == str(refusal.value.__context__)


def test_unallowlisted_tool_and_tampered_input_fail_before_call(tmp_path):
    path = tmp_path / "case.json"; atomic_json(path, {})
    n = tool("shell", {}, [pin(path)])
    control = Control()
    with pytest.raises(host.HostFailure, match="not allowlisted"):
        host.AgentHost().execute(n, request(n), control)
    n["action"] = "allocator"; n["parameters"] = {"case_input": "case", "horizon": None}; path.write_text("changed")
    with pytest.raises(host.HostFailure, match="bytes differ"):
        host.AgentHost().execute(n, request(n), control)
    assert not control.calls


def test_public_preparation_and_validation_do_not_dispatch_or_share_mutable_input(tmp_path):
    path = tmp_path / "public.txt"; path.write_text("bound public measurement")
    n = node(action="external", inputs=[pin(path)])
    prepared = host.prepare_model_context(n, request(n))
    assert prepared["context"]["input_artifacts"][0]["content"] == "bound public measurement"
    assert prepared["parameters"] == n["parameters"]
    n["parameters"]["model"] = "changed-model"
    assert prepared["parameters"]["model"] == "requested-model"
    value = {"answer": "public conclusion"}
    validated = host.validate_public_result(value, SCHEMA)
    value["answer"] = "changed"
    assert validated == {"answer": "public conclusion"}
    with pytest.raises(host.HostFailure, match="private reasoning"):
        host.validate_public_result({"chain_of_thought": "private trace"}, None)
    numeric = {"type": "object", "properties": {"x": {"type": "number", "enum": [1.0]}},
               "required": ["x"], "additionalProperties": False}
    assert host.validate_public_result({"x": 1}, numeric) == {"x": 1}
    with pytest.raises(host.HostFailure, match="match output schema"):
        host.validate_public_result({"x": True}, numeric)


def test_packet_tampering_and_symlink_fail_before_reserving_transport(run, tmp_path):
    opened(run); out = tmp_path / "packet"
    manifest = review_context.create(run[0], "critic", out)
    n = node(role="critic", packet={"path": str(out), "manifest_sha256": manifest["sha256"]})
    target = out / manifest["artifacts"][0]["path"]
    original = target.read_bytes(); target.write_bytes(b"modified")
    control = Control()
    with pytest.raises(host.HostFailure, match="artifact custody"):
        host.AgentHost().execute(n, request(n), control)
    target.write_bytes(original)
    copied = tmp_path / "manifest-copy.json"; copied.write_bytes((out / "manifest.json").read_bytes())
    (out / "manifest.json").unlink(); (out / "manifest.json").symlink_to(copied)
    with pytest.raises(host.HostFailure, match="manifest custody is invalid.*cannot traverse symlinks"):
        host.AgentHost().execute(n, request(n), control)
    assert not control.calls


def quantity_inputs(tmp_path):
    contract = {"schema_version": 1, "axes": [{"name": "x", "unit": "1"}],
                "bins": [{"id": "low", "low": [0], "high": [1]}, {"id": "high", "low": [1], "high": [2]}],
                "weight_names": ["baseline", "candidate"], "input_weight_unit": "1", "representation": "integrated",
                "normalization": {"kind": "absolute", "scale": 1, "unit": "1"}}
    records = [{"event_id": f"source-{index}", "group_id": f"source-{index}", "shard_id": "tiny",
                "weights": {"baseline": baseline, "candidate": candidate}, "fills": [[x]]}
               for index, (x, baseline, candidate) in enumerate(((.25, 1, 1), (.75, 2, 0), (1.25, 1, 2), (1.75, 1, 1)))]
    contract_path, records_path = tmp_path / "quantity-contract.json", tmp_path / "quantity-records.json"
    atomic_json(contract_path, contract); atomic_json(records_path, records)
    return contract_path, records_path


def test_tiny_quantity_adapter_executes_paired_weight_covariance(tmp_path):
    contract_path, records_path = quantity_inputs(tmp_path)
    n = tool("quantities", {"contract_input": "contract", "records_input": "records"},
             [pin(contract_path, "contract"), pin(records_path, "records")])
    control = Control(); result = host.AgentHost().execute(n, request(n), control)
    report = result["value"]
    assert report["kind"] == "weighted_quantities"
    assert report["state"]["counts"]["records"] == 4
    assert report["values"] == {"baseline": [3., 2.], "candidate": [1., 3.]}
    assert report["covariance_order"] == [{"weight": w, "bin_id": b} for w in ("baseline", "candidate") for b in ("low", "high")]
    assert report["covariance"] == [[5., 0., 1., 0.], [0., 2., 0., 3.], [1., 0., 1., 0.], [0., 3., 0., 5.]]
    assert "Poissonized independent-group moments" in report["uncertainty_scope"]
    assert report["physics_validated"] is result["physics_validated"] is result["execution_authorized"] is False
    assert control.calls[0]["kind"] == "tool"


@pytest.mark.parametrize("mutation", ["records", "bins", "weights", "fills"])
def test_quantity_adapter_refuses_non_tiny_cases_before_call(tmp_path, mutation):
    contract_path, records_path = quantity_inputs(tmp_path)
    contract, records = read_json(contract_path), read_json(records_path)
    if mutation == "records":
        records *= 33
    elif mutation == "bins":
        contract["bins"] *= 9
    elif mutation == "weights":
        contract["weight_names"] = [str(index) for index in range(5)]
    else:
        records[0]["fills"] *= 17
    atomic_json(contract_path, contract); atomic_json(records_path, records)
    n = tool("quantities", {"contract_input": "contract", "records_input": "records"},
             [pin(contract_path, "contract"), pin(records_path, "records")])
    control = Control()
    with pytest.raises(host.HostFailure, match="bound"):
        host.AgentHost().execute(n, request(n), control)
    assert not control.calls


def test_cancel_interrupts_blocked_http_transport_without_claiming_remote_cancel():
    received, release = threading.Event(), threading.Event()
    def block(h):
        received.set(); release.wait(timeout=2)
    n = node(); control = Control(); failures = []
    with server(handler=block) as (endpoint, seen):
        adapter = host.AgentHost(endpoint=endpoint, timeout_seconds=2)
        def execute():
            try:
                adapter.execute(n, request(n), control)
            except host.HostFailure as exc:
                failures.append(exc)
        thread = threading.Thread(target=execute); thread.start()
        assert received.wait(timeout=1)
        control.cancel.set(); thread.join(timeout=.6); release.set()
        assert not thread.is_alive()
    assert len(seen) == 1 and failures[0].ambiguous is True and not control.saved


def test_command_cancel_after_pipes_close_still_reaps(tmp_path, monkeypatch):
    marker = tmp_path / "closed-pid.txt"
    code = "import os,time,pathlib; os.close(0); os.close(1); os.close(2); pathlib.Path(" + repr(str(marker)) + ").write_text(str(os.getpid())); time.sleep(10)"
    n = node(action="command"); control = Control(); failures = []
    adapter = host.AgentHost(adapter="command", command=[sys.executable, "-c", code], timeout_seconds=2)
    original = adapter._cleanup
    observed = []
    def cleanup(proc):
        observed.append(proc.poll() is None)
        return original(proc)
    monkeypatch.setattr(adapter, "_cleanup", cleanup)
    def execute():
        try:
            adapter.execute(n, request(n), control)
        except host.HostFailure as exc:
            failures.append(exc)
    thread = threading.Thread(target=execute); thread.start()
    deadline = time.monotonic() + 1
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert marker.exists(); time.sleep(.05)
    control.cancel.set(); thread.join(timeout=.6)
    assert not thread.is_alive() and observed == [True]
    assert failures[0].ambiguous is True and execution.process_identity(int(marker.read_text())) is None


def test_http_error_explicitly_closes_response_object(monkeypatch):
    closed = []
    class Response:
        status = 500
        def close(self):
            closed.append("response")
    class Connection:
        sock = None
        def __init__(self, *args, **kwargs):
            pass
        def connect(self):
            pass
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return Response()
        def close(self):
            closed.append("connection")
    monkeypatch.setattr(host.http.client, "HTTPConnection", Connection)
    n = node()
    with pytest.raises(host.HostFailure, match="HTTP 500"):
        host.AgentHost(endpoint="http://127.0.0.1:1/v1/responses").execute(n, request(n), Control())
    assert closed == ["response", "connection"]


def test_host_identity_is_source_config_bound_and_excludes_credentials(monkeypatch):
    monkeypatch.setenv("TEST_HOST_KEY", "SECRET-SELECTED")
    adapter = host.AgentHost.from_config({"type": "responses", "api_key_env": "TEST_HOST_KEY"})
    identity = adapter.identity
    assert "SECRET-SELECTED" not in json.dumps(identity)
    assert "ravel.workflow.agent_host" in identity["sources"]
    monkeypatch.setenv("TEST_HOST_KEY", "CHANGED-KEY")
    assert host.AgentHost.from_config({"type": "responses", "api_key_env": "TEST_HOST_KEY"}).identity == identity
    assert host.AgentHost(timeout_seconds=61).identity != identity


def test_external_preparation_caps_aggregate_context_before_dispatch(tmp_path):
    left, right = tmp_path / "left.txt", tmp_path / "right.txt"
    left.write_text("x" * 600); right.write_text("y" * 600)
    n = node(action="external", inputs=[pin(left, "left"), pin(right, "right")])
    with pytest.raises(host.HostFailure, match="aggregate model context"):
        host.AgentHost(max_request_bytes=1000).prepare_model_context(n, request(n))


def test_actual_host_runs_quantity_graph_and_reuses_bound_completion(tmp_path):
    from ravel.workflow import agent_graph
    contract_path, records_path = quantity_inputs(tmp_path)
    n = tool("quantities", {"contract_input": "contract", "records_input": "records"},
             [pin(contract_path, "contract"), pin(records_path, "records")])
    spec = {"schema_version": 1, "graph_id": "tiny-quantity-graph",
            "budget": {"max_nodes": 4, "max_calls": 2, "max_output_tokens": 32, "max_wall_seconds": 30, "max_reworks": 0},
            "nodes": [n]}
    root = tmp_path / "graph"; agent_graph.create(root, spec)
    adapter = host.AgentHost()
    first = agent_graph.execute(root, adapter)
    assert first["complete"] and first["usage"]["calls"] == 1
    second = agent_graph.execute(root, adapter)
    assert second["complete"] and second["usage"]["calls"] == 1


def test_blocked_connection_is_bounded_and_fenced_from_late_dispatch(monkeypatch):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    requests = []
    class Connection:
        sock = None
        def __init__(self, *args, **kwargs):
            pass
        def connect(self):
            entered.set(); release.wait(timeout=1)
        def request(self, *args, **kwargs):
            requests.append(True)
        def close(self):
            closed.set()
    monkeypatch.setattr(host.http.client, "HTTPConnection", Connection)
    n = node(); before = time.monotonic()
    with pytest.raises(host.HostFailure, match="before dispatch") as failure:
        host.AgentHost(endpoint="http://127.0.0.1:1/v1/responses", timeout_seconds=.04).execute(n, request(n), Control())
    assert entered.is_set() and time.monotonic() - before < .25
    assert failure.value.ambiguous is False
    release.set(); assert closed.wait(timeout=.2)
    time.sleep(.03)
    assert not requests
