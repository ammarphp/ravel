"""Root-admitted actual tiny raster/PDF controls with inert provider boundaries.

These proposed tests have not been imported or executed by the source author.
They use required Pillow/PDFium, no model, provider, physics engine or service.
"""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph as graph, agent_host as host
from ravel.workflow import visual_presentation as visual
from ravel.workflow.state_io import atomic_json
from test_provider_transport import capabilities, document, install_http, node, request, Control, VALUE


def vision(**changes):
    result = {"models": ["fixture-model"], "max_sources": 4, "max_pages": 8,
              "max_source_bytes": 1000000, "max_page_pixels": 1000000,
              "max_total_pixels": 4000000, "max_raster_bytes": 1000000,
              "max_dimension": 1000, "pdf_scale": 1, "max_render_seconds": 20}
    result.update(changes)
    return result


def tiny_pdf(path, pages=2):
    # Original two-page test data: distinct solid rectangles, exact page geometry,
    # no fonts, external references, scripts or actions. No third-party figures.
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + j * 2} 0 R" for j in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    for j in range(pages):
        content = b"0 0 1 rg 0 0 30 20 re f" if j == 0 else b"1 0 0 rg 10 10 20 30 re f"
        objects.extend([f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] /Resources << >> /Contents {4+j*2} 0 R >>".encode(),
                        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"])
    raw = b"%PDF-1.4\n"; offsets = [0]
    for j, obj in enumerate(objects, 1):
        offsets.append(len(raw));raw += f"{j} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(raw)
    raw += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    raw += b"".join(f"{x:010d} 00000 n \n".encode() for x in offsets[1:])
    raw += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(raw)


def packet(tmp_path, *, pdf=False):
    source = tmp_path / ("figure.pdf" if pdf else "figure.png")
    if pdf:
        tiny_pdf(source)
    else:
        from PIL import Image
        image = Image.new("RGBA", (30, 20), (0, 0, 255, 255))
        image.putpixel((0, 0), (255, 0, 0, 0))
        image.save(source);image.close()
    raw = source.read_bytes();sha = hashlib.sha256(raw).hexdigest()
    pin = {"path": str(source), "sha256": sha, "size": len(raw)}
    root = tmp_path / "packet";root.mkdir();(root / "artifacts").mkdir()
    copied = root / ("artifacts/figure" + source.suffix);copied.write_bytes(raw)
    manifest = {"schema_version": 1, "role": "critic", "artifacts": [{"id": "figure",
        "path": "artifacts/figure" + source.suffix, "source_path": str(source),
        "source_sha256": sha, "sha256": sha, "projection": "exact bytes"}], "findings": [], "reviews": []}
    manifest["sha256"] = graph.digest(manifest);atomic_json(root / "manifest.json", manifest)
    return {"path": str(root), "manifest_sha256": manifest["sha256"]}, [pin]


def provider_host(adapter, **options):
    endpoint = {"responses": "http://127.0.0.1:8000/v1/responses",
                "anthropic": "http://127.0.0.1:8000/v1/messages",
                "gemini": "http://127.0.0.1:8000/v1beta/models/{model}:generateContent",
                "chat_completions": "http://127.0.0.1:8000/v1/chat/completions"}[adapter]
    return host.AgentHost(adapter=adapter, endpoint=endpoint, privacy="local_only", local_models=["fixture-model"],
        capabilities=None if adapter == "responses" else capabilities(adapter), **options)


def response(adapter):
    if adapter != "responses":
        return document(adapter)
    return {"status": "completed", "model": "observed-snapshot", "id": "fixture-response",
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(VALUE)}]}],
            "usage": {"input_tokens": 10, "output_tokens": 7, "total_tokens": 17}}


def current_receipt(tmp_path, monkeypatch, adapter="chat_completions", pdf=False):
    packet_pin, pins = packet(tmp_path, pdf=pdf)
    n = node(role="critic", packet=packet_pin);n["parameters"]["visual_sources"] = pins
    root = tmp_path / "graph"
    graph.create(root, {"schema_version": 1, "graph_id": "visual-review", "budget": {
        "max_nodes": 1, "max_calls": 1, "max_output_tokens": 120, "max_wall_seconds": 30, "max_reworks": 1}, "nodes": [n]})
    seen = install_http(monkeypatch, response(adapter))
    state = graph.execute(root, provider_host(adapter, vision=vision()))
    assert state["complete"] and state["usage"] == {"calls": 1, "reserved_output_tokens": 120}
    r = graph.role_receipt(root, "role", expected_subject_sha256=pins[0]["sha256"],
                           expected_packet_sha256=packet_pin["manifest_sha256"])
    return r, pins, packet_pin, seen


@pytest.mark.parametrize("adapter", ["responses", "anthropic", "gemini", "chat_completions"])
@pytest.mark.parametrize("pdf", [False, True])
def test_actual_complete_rasters_are_sent_in_native_image_blocks(tmp_path, monkeypatch, adapter, pdf):
    r, pins, p, seen = current_receipt(tmp_path, monkeypatch, adapter, pdf)
    proof = visual.verify_visual_presentation(r, expected_sources=pins, expected_packet_sha256=p["manifest_sha256"], expected_node_id="role")
    assert proof["pages"] == (2 if pdf else 1) and len(seen) == 1
    vr = r["isolation"]["visual_presentation"]
    assert vr["wire_request"] == seen[0]["body"]
    assert proof["wire_request_sha256"] == r["model_call_requests"][0]["request_sha256"]
    assert r["public_value"] == VALUE and not r["physics_validated"] and not r["scientific_independence_proven"]
    from PIL import Image
    images = visual._wire_images(seen[0]["body"], adapter)
    with Image.open(io.BytesIO(images[0])) as image:
        if pdf:
            assert image.size == (72, 72) and image.getpixel((1, 71)) == (0, 0, 255)
            assert image.getpixel((71, 1)) == (255, 255, 255)
        else:
            assert image.size == (30, 20) and image.getpixel((0, 0)) == (255, 255, 255)
            assert image.getpixel((1, 1)) == (0, 0, 255)


@pytest.mark.parametrize("change", ["foreign_node", "foreign_packet", "missing_page", "duplicate_page", "stale_source", "text_only", "wrong_call", "false_capability", "wrong_pixels", "partial_pdf"])
def test_omitted_foreign_stale_or_text_only_visual_receipts_refuse(tmp_path, monkeypatch, change):
    r, pins, p, seen = current_receipt(tmp_path, monkeypatch, pdf=True)
    r = deepcopy(r);v = r["isolation"]["visual_presentation"]
    if change == "foreign_node": v["node_id"] = "other"
    elif change == "foreign_packet": v["packet_sha256"] = "0" * 64
    elif change == "missing_page": v["sources"][0]["pages"].pop()
    elif change == "duplicate_page": v["sources"][0]["pages"][1]["page_index"] = 0
    elif change == "stale_source": Path(pins[0]["path"]).write_bytes(b"different original")
    elif change == "text_only":
        content = v["wire_request"]["messages"][1]["content"]
        content[:] = [{"type": "text", "text": json.dumps(content)}]
    elif change == "wrong_call": r["model_call_requests"][0]["request_sha256"] = "0" * 64
    elif change == "false_capability": r["transport"]["vision"] = None
    elif change == "wrong_pixels": v["sources"][0]["pages"][0]["raster"]["pixels_sha256"] = "0" * 64
    else:
        # Even a self-consistent shorter wire/page list cannot omit an actual
        # source PDF page: native source page-count readback is independent.
        v["sources"][0]["page_count"] = 1;v["sources"][0]["pages"].pop()
        v["wire_request"]["messages"][1]["content"] = v["wire_request"]["messages"][1]["content"][:3]
    if change in {"text_only", "partial_pdf"}:
        v["wire_request_sha256"] = graph.digest(v["wire_request"])
        r["model_call_requests"][0]["request_sha256"] = v["wire_request_sha256"]
    with pytest.raises(visual.VisualFailure):
        visual.verify_visual_presentation(r, expected_sources=pins, expected_packet_sha256=p["manifest_sha256"], expected_node_id="role")


@pytest.mark.parametrize("change", [{"max_pages": 1}, {"max_total_pixels": 1}, {"max_page_pixels": 1},
                                  {"max_dimension": 10}, {"max_source_bytes": 1}, {"max_raster_bytes": 1},
                                  {"models": ["other-model"]}])
def test_full_population_limits_refuse_before_provider_dispatch(tmp_path, monkeypatch, change):
    p, pins = packet(tmp_path, pdf=True);n = node(role="critic", packet=p);n["parameters"]["visual_sources"] = pins
    seen = install_http(monkeypatch, response("chat_completions"));c = Control()
    with pytest.raises(host.HostFailure): provider_host("chat_completions", vision=vision(**change)).execute(n, request(n), c)
    assert not seen and not c.calls


def test_undeclared_projected_or_changed_packet_copy_refuses(tmp_path, monkeypatch):
    p, pins = packet(tmp_path);n = node(role="critic", packet=p);n["parameters"]["visual_sources"] = pins
    seen = install_http(monkeypatch, response("chat_completions"))
    manifest_path = Path(p["path"]) / "manifest.json";m = json.loads(manifest_path.read_bytes())
    m["artifacts"][0]["projection"] = "header only";m.pop("sha256");m["sha256"] = graph.digest(m)
    atomic_json(manifest_path, m);n["packet"]["manifest_sha256"] = m["sha256"]
    with pytest.raises(host.HostFailure): provider_host("chat_completions", vision=vision()).execute(n, request(n), Control())
    assert not seen


def test_text_only_default_and_empty_roster_keep_the_original_wire(monkeypatch):
    seen = install_http(monkeypatch, response("chat_completions"));h = provider_host("chat_completions")
    n = node();a = h.execute(n, request(n), Control())
    n["parameters"]["visual_sources"] = [];b = h.execute(n, request(n), Control())
    assert seen[0]["body"] == seen[1]["body"] and a == b
    assert "visual_presentation" not in b["isolation"] and h.vision is None
    assert visual.verify_visual_presentation({}, expected_sources=[], expected_packet_sha256=None, expected_node_id="unused")["pages"] == 0


def test_required_visual_missing_capability_and_command_refuse(tmp_path, monkeypatch):
    p, pins = packet(tmp_path);n = node(role="critic", packet=p);n["parameters"]["visual_sources"] = pins
    seen = install_http(monkeypatch, response("chat_completions"));c = Control()
    with pytest.raises(host.HostFailure, match="vision capability"): provider_host("chat_completions").execute(n, request(n), c)
    with pytest.raises(host.HostFailure): host.AgentHost(adapter="command", command=["not-executed"], vision=vision())
    assert not seen and not c.calls


def test_changed_actual_render_runtime_refuses_current_visual_receipt(tmp_path, monkeypatch):
    r, pins, p, seen = current_receipt(tmp_path, monkeypatch)
    r = deepcopy(r);r["isolation"]["visual_presentation"]["renderer"]["files"].pop()
    with pytest.raises(visual.VisualFailure, match="population"):
        visual.verify_visual_presentation(r, expected_sources=pins, expected_packet_sha256=p["manifest_sha256"], expected_node_id="role")


def test_source_drift_after_actual_send_retains_ambiguous_call_and_no_complete_review(tmp_path, monkeypatch):
    p, pins = packet(tmp_path);n = node(role="critic", packet=p);n["parameters"]["visual_sources"] = pins
    root = tmp_path / "graph"
    graph.create(root, {"schema_version": 1, "graph_id": "visual-ending-refusal", "budget": {
        "max_nodes": 1, "max_calls": 1, "max_output_tokens": 120, "max_wall_seconds": 30, "max_reworks": 1}, "nodes": [n]})
    seen = install_http(monkeypatch, response("chat_completions"))
    original = host.AgentHost._responses
    def after_send(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        Path(pins[0]["path"]).write_bytes(b"late source replacement")
        return result
    monkeypatch.setattr(host.AgentHost, "_responses", after_send)
    state = graph.execute(root, provider_host("chat_completions", vision=vision()))
    assert not state["complete"] and len(seen) == 1 and state["usage"]["calls"] == 1
    call = next(iter(json.loads((root / "graph_state.json").read_bytes())["calls"].values()))
    assert call["status"] == "ambiguous"
    with pytest.raises(graph.GraphError): graph.role_receipt(root, "role", expected_subject_sha256=pins[0]["sha256"])
