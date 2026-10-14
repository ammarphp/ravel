"""Complete, bounded figure rasters and their actual HTTP image-content custody.

The renderer imports Pillow/PDFium only for a requested visual operation. A
current accounted Graph receipt establishes transport, not human inspection,
model comprehension, scientific independence or physics acceptance.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from contextlib import closing
import hashlib
from importlib import metadata
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import threading
import time

SHA = re.compile(r"[0-9a-f]{64}")
PNG = b"\x89PNG\r\n\x1a\n"
PDFIUM_VERSION = "5.14.0"
_PDFIUM_LOCK = threading.RLock()  # PDFium is not thread-safe, even across docs.
_CEILINGS = {"max_sources": 32, "max_pages": 64,
             "max_source_bytes": 16_000_000, "max_page_pixels": 16_000_000,
             "max_total_pixels": 64_000_000, "max_raster_bytes": 12_000_000,
             "max_dimension": 8000}
_CONFIG_KEYS = set(_CEILINGS) | {"models", "pdf_scale", "max_render_seconds"}
_SETTING = {"additional_rotation": 0, "crop": [0, 0, 0, 0],
            "background": "opaque white", "color_mode": "RGB",
            "annotations": True, "acroform_appearances": True,
            "javascript": False, "xfa": False, "png_resampling": False}


class VisualFailure(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise VisualFailure("invalid " + label + " fields")


def _integer(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise VisualFailure("invalid " + label)
    return value


def configuration(value, adapter):
    """Absent config retains text-only transport; model IDs are operator chosen."""
    if value is None:
        return None
    _keys(value, _CONFIG_KEYS, "vision configuration")
    if adapter not in {"responses", "anthropic", "gemini", "chat_completions"}:
        raise VisualFailure("vision requires a configured HTTP image-content adapter")
    models = value["models"]
    if (type(models) is not list or not 1 <= len(models) <= 64
            or any(type(m) is not str or not m.strip() or len(m) > 200 for m in models)
            or len(set(models)) != len(models)):
        raise VisualFailure("explicit unique vision model allowlist required")
    for key, maximum in _CEILINGS.items():
        _integer(value[key], maximum, key)
    if (type(value["pdf_scale"]) not in (int, float)
            or not math.isfinite(value["pdf_scale"]) or not 0.25 <= value["pdf_scale"] <= 4
            or type(value["max_render_seconds"]) not in (int, float)
            or not math.isfinite(value["max_render_seconds"])
            or not 0 < value["max_render_seconds"] <= 60):
        raise VisualFailure("invalid explicit PDF scale/render time bound")
    return deepcopy(value)


def sources(value):
    if type(value) is not list or len(value) > _CEILINGS["max_sources"]:
        raise VisualFailure("complete bounded visual source roster required")
    paths = []
    for pin in value:
        _keys(pin, {"path", "sha256", "size"}, "visual source")
        p = Path(pin["path"]) if type(pin["path"]) is str else Path()
        if (not p.is_absolute() or str(p) != pin["path"] or ".." in p.parts
                or p.suffix.lower() not in {".png", ".pdf"}
                or type(pin["sha256"]) is not str or not SHA.fullmatch(pin["sha256"])):
            raise VisualFailure("canonical PNG/PDF source identity required")
        _integer(pin["size"], _CEILINGS["max_source_bytes"], "source size")
        paths.append(pin["path"])
    if len(set(paths)) != len(paths):
        raise VisualFailure("duplicate visual source")
    return deepcopy(value)


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _read(path, maximum):
    path = Path(path)
    for p in path.parents:
        if not stat.S_ISDIR(p.lstat().st_mode):
            raise VisualFailure("visual input ancestry must be ordinary")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
        raise VisualFailure("bounded ordinary visual/runtime file required")
    with path.open("rb") as stream:
        if _identity(stream_stat := os.fstat(stream.fileno())) != _identity(before):
            raise VisualFailure("visual descriptor changed before read")
        raw = stream.read(before.st_size + 1)
        if _identity(os.fstat(stream.fileno())) != _identity(stream_stat):
            raise VisualFailure("visual descriptor changed during read")
    if len(raw) != before.st_size or _identity(path.lstat()) != _identity(before):
        raise VisualFailure("visual file changed during read")
    return raw, _identity(before)


def _file_pin(path):
    raw, _ = _read(path, 256_000_000)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def _runtime(pdf):
    distributions = ["Pillow"] + (["pypdfium2"] if pdf else [])
    versions, files, identities = {}, {}, {}
    for name in distributions:
        dist = metadata.distribution(name)
        versions[name] = dist.version
        if name == "pypdfium2" and dist.version != PDFIUM_VERSION:
            raise VisualFailure("required source-pinned PDFium version unavailable")
        if not dist.files or len(dist.files) > 2048:
            raise VisualFailure("complete renderer distribution census unavailable")
        for relative in dist.files:
            if str(relative).endswith((".pyc", ".pyo")):
                continue
            path = Path(os.path.abspath(dist.locate_file(relative)))
            raw, identity = _read(path, 256_000_000)
            files[str(path)] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
            identities[str(path)] = list(identity)
    executable = Path(sys.executable).resolve()
    return {"versions": versions, "files": [files[k] for k in sorted(files)], "file_identities": identities,
            "python": {"version": sys.version.split()[0], "executable": _file_pin(executable)},
            "helper": _file_pin(Path(__file__).absolute())}


def _runtime_matches(record):
    _keys(record, {"versions", "files", "file_identities", "python", "helper", "loaded_origins"}, "renderer custody")
    actual = _runtime("pypdfium2" in record["versions"])
    if any(record[k] != actual[k] for k in actual):
        raise VisualFailure("complete renderer distribution/runtime population differs")
    for pin in record["files"] + [record["python"]["executable"], record["helper"]]:
        if _file_pin(Path(pin["path"])) != pin:
            raise VisualFailure("rendering runtime changed")
    for name, version in record["versions"].items():
        if metadata.version(name) != version:
            raise VisualFailure("renderer version changed")
    if record["helper"] != _file_pin(Path(__file__).absolute()):
        raise VisualFailure("foreign renderer helper")
    with _PDFIUM_LOCK:
        from PIL import Image  # initialize only the explicitly admitted renderer
        if "pypdfium2" in record["versions"]:
            import pypdfium2
    if record["loaded_origins"] != _loaded_origins("pypdfium2" in record["versions"], record):
        raise VisualFailure("actual renderer/native import origins changed")


def _loaded_origins(pdf, runtime):
    names = ["PIL.Image", "PIL._imaging"]
    if pdf:
        names += ["pypdfium2", "pypdfium2_raw", "pypdfium2_raw.bindings",
                  "pypdfium2._helpers.document", "pypdfium2._helpers.page", "pypdfium2._helpers.bitmap"]
    known = {p["path"]: p for p in runtime["files"]}
    result = {}
    for name in names:
        module = sys.modules.get(name)
        if module is None:
            raise VisualFailure("renderer import origin unavailable")
        path = os.path.abspath(module.__file__)
        if path not in known:
            raise VisualFailure("renderer import escaped its complete distribution census")
        result[name] = known[path]
    if pdf:
        # This source-pinned wheel loader uses search_sys=False. Record the
        # actual CDLL path, rather than assuming a same-named library loaded.
        path = os.path.abspath(sys.modules["pypdfium2_raw.bindings"]._libs["pdfium"]._name)
        if path not in known:
            raise VisualFailure("loaded native PDFium escaped the renderer census")
        result["native_pdfium"] = known[path]
    return result


def _png_dimensions(raw):
    if (len(raw) < 33 or raw[:8] != PNG or raw[12:16] != b"IHDR"
            or struct.unpack(">I", raw[8:12])[0] != 13):
        raise VisualFailure("complete PNG header required")
    return struct.unpack(">II", raw[16:24])


def _geometry(width, height, config):
    if (type(width) is not int or type(height) is not int or width < 1 or height < 1
            or max(width, height) > config["max_dimension"]
            or width * height > config["max_page_pixels"]):
        raise VisualFailure("full visual page exceeds declared pixel/dimension limit")
    return width * height


def _rgb(image):
    # Explicit alpha compositing preserves all pixels on a white page, with no
    # crop, resize, thumbnail or orientation adjustment.
    from PIL import Image
    if image.getexif().get(274, 1) != 1:
        raise VisualFailure("nontrivial PNG EXIF orientation needs explicit conversion")
    rgba = image.convert("RGBA")
    try:
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        try:
            return Image.alpha_composite(white, rgba).convert("RGB")
        finally:
            white.close()
    finally:
        rgba.close()


def _raster(image):
    rgb = _rgb(image)
    try:
        pixels = rgb.tobytes()
        out = io.BytesIO()
        rgb.save(out, format="PNG")
        raw = out.getvalue()
        return {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
                "width": rgb.width, "height": rgb.height, "mode": "RGB",
                "pixels_sha256": hashlib.sha256(pixels).hexdigest()}, raw
    finally:
        rgb.close()


class PreparedVisual:
    """One capture/render/dispatch lifetime; no cache or cross-role authority."""
    def __init__(self, index, originals, runtime, record, rasters):
        self.index, self.originals, self.runtime = index, originals, runtime
        self.record, self.rasters = record, rasters

    def check(self):
        for path, identity, pin in self.originals:
            raw, ending = _read(path, pin["size"])
            if ending != identity or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
                raise VisualFailure("visual original changed during presentation")
        _runtime_matches(self.runtime)

    def finish(self):
        self.check()
        self.index.finish()


def prepare_visuals(packet, requested, config, model, *, bound_roots=()):
    requested = sources(requested)
    if not requested:
        return None
    if config is None or model not in config["models"]:
        raise VisualFailure("selected model lacks explicit configured vision capability")
    if len(requested) > config["max_sources"] or sum(p["size"] for p in requested) > config["max_source_bytes"]:
        raise VisualFailure("complete visual source population exceeds declared limits")
    if type(packet) is not dict or set(packet) != {"path", "manifest_sha256"}:
        raise VisualFailure("visual sources require a current bound role packet")
    from . import review_context
    index = review_context._PacketIndex(packet["path"], packet["manifest_sha256"])
    original, captures = [], []
    for pin in requested:
        path = Path(pin["path"])
        if bound_roots and not any(path.is_relative_to(root) for root in bound_roots):
            raise VisualFailure("visual source outside configured bound roots")
        raw, identity = _read(path, pin["size"])
        if len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise VisualFailure("visual original differs from current source commitment")
        matching = [e for e in index.entries.values() if e.get("source_path") == pin["path"]
                    and e.get("source_sha256") == pin["sha256"]
                    and e.get("sha256") == pin["sha256"] and e.get("projection") == "exact bytes"]
        if len(matching) != 1 or index.read(matching[0]) != raw:
            raise VisualFailure("visual source lacks one exact current packet copy")
        original.append((path, identity, pin))
        captures.append((pin, matching[0]["id"], raw))
    began = time.monotonic()
    def time_check():
        if time.monotonic() - began > config["max_render_seconds"]:
            raise VisualFailure("visual render elapsed bound exceeded")
    # One lock includes import/library initialization and document lifetimes.
    # The deadline is checked between native calls, not hard C-call preemption.
    with _PDFIUM_LOCK:
        pdf = any(pin["path"].lower().endswith(".pdf") for pin in requested)
        runtime = _runtime(pdf)
        from PIL import Image
        if str(Path(Image.__file__).absolute()) not in {p["path"] for p in runtime["files"]}:
            raise VisualFailure("Pillow import origin differs from renderer census")
        if pdf:
            import pypdfium2 as pdfium
            import pypdfium2_raw as raw_api
            if str(Path(pdfium.__file__).absolute()) not in {p["path"] for p in runtime["files"]}:
                raise VisualFailure("PDFium import origin differs from renderer census")
            flags = json.loads((Path(raw_api.__file__).parent / "version.json").read_bytes())["flags"]
            if "V8" in flags or "XFA" in flags:
                raise VisualFailure("visual renderer requires the non-JavaScript non-XFA PDFium build")
        runtime["loaded_origins"] = _loaded_origins(pdf, runtime)
        rows, rasters, total_pixels, total_pages, raster_bytes = [], [], 0, 0, 0
        for pin, artifact_id, raw in captures:
            time_check()
            pages = []
            row = {"source": pin, "artifact_id": artifact_id, "format": Path(pin["path"]).suffix.lower()[1:], "pages": pages}
            if row["format"] == "png":
                width, height = _png_dimensions(raw)
                total_pixels += _geometry(width, height, config)
                row["page_count"] = 1
                total_pages += 1
                if total_pixels > config["max_total_pixels"] or total_pages > config["max_pages"]:
                    raise VisualFailure("complete visual population exceeds declared limits")
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != "PNG" or getattr(image, "n_frames", 1) != 1 or image.size != (width, height):
                        raise VisualFailure("single complete PNG image required")
                    image.load()
                    raster, data = _raster(image)
                pages.append({"page_index": 0, "canvas_size": [width, height], "raster": raster})
                rasters.append(data)
                raster_bytes += len(data)
            else:
                with pdfium.PdfDocument(raw) as document:
                    count = len(document)
                    _integer(count, config["max_pages"], "PDF page population")
                    total_pages += count
                    if total_pages > config["max_pages"]:
                        raise VisualFailure("complete visual page population exceeds declared limit")
                    if document.get_formtype() in (raw_api.FORMTYPE_XFA_FULL, raw_api.FORMTYPE_XFA_FOREGROUND):
                        raise VisualFailure("XFA document cannot be completely rendered by this build")
                    document.init_forms()
                    geometry = []
                    # Full document geometry is checked before any bitmap.
                    for j in range(count):
                        with closing(document[j]) as page:
                            w, h = page.get_size()
                        if not all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in (w, h)):
                            raise VisualFailure("invalid full PDF page geometry")
                        width, height = math.ceil(w * config["pdf_scale"]), math.ceil(h * config["pdf_scale"])
                        total_pixels += _geometry(width, height, config)
                        geometry.append((w, h, width, height))
                    if total_pixels > config["max_total_pixels"]:
                        raise VisualFailure("complete visual pixel population exceeds declared limit")
                    row["page_count"] = count
                    for j, (w, h, width, height) in enumerate(geometry):
                        time_check()
                        with closing(document[j]) as page:
                            bitmap = page.render(scale=config["pdf_scale"], rotation=0, crop=(0, 0, 0, 0),
                                may_draw_forms=True, draw_annots=True, fill_color=(255, 255, 255, 255), rev_byteorder=True)
                            try:
                                image = bitmap.to_pil().copy()  # detach before closing native storage
                                try:
                                    if image.size != (width, height):
                                        raise VisualFailure("rendered geometry differs from full page")
                                    raster, data = _raster(image)
                                finally:
                                    image.close()
                            finally:
                                bitmap.close()
                        pages.append({"page_index": j, "canvas_size": [w, h], "raster": raster})
                        rasters.append(data)
                        raster_bytes += len(data)
                        if raster_bytes > config["max_raster_bytes"]:
                            raise VisualFailure("full visual raster byte population exceeds declared limit")
            rows.append(row)
            if raster_bytes > config["max_raster_bytes"]:
                raise VisualFailure("full visual raster byte population exceeds declared limit")
            time_check()
        record = {"sources": rows, "renderer": runtime, "configuration": config, "settings": deepcopy(_SETTING),
                  "render_elapsed_seconds": time.monotonic() - began}
        prepared = PreparedVisual(index, original, runtime, record, rasters)
        prepared.check()
        return prepared


def attach_images(body, adapter, prepared):
    if prepared is None:
        return body
    body = deepcopy(body)
    labels = [f"Figure source {row['source']['path']}, page {p['page_index'] + 1}/{row['page_count']}"
              for row in prepared.record["sources"] for p in row["pages"]]
    encoded = [base64.b64encode(data).decode("ascii") for data in prepared.rasters]
    if adapter == "responses":
        content = [{"type": "input_text", "text": body["input"][0]["content"]}]
        for label, data in zip(labels, encoded):
            content.extend([{"type": "input_text", "text": label},
                            {"type": "input_image", "image_url": "data:image/png;base64," + data}])
        body["input"][0]["content"] = content
    elif adapter == "anthropic":
        content = []
        for label, data in zip(labels, encoded):
            content.extend([{"type": "text", "text": label}, {"type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": data}}])
        content.append({"type": "text", "text": body["messages"][0]["content"]})
        body["messages"][0]["content"] = content
    elif adapter == "gemini":
        for label, data in zip(labels, encoded):
            body["contents"][0]["parts"].extend([{"text": label}, {"inlineData": {"mimeType": "image/png", "data": data}}])
    elif adapter == "chat_completions":
        content = [{"type": "text", "text": body["messages"][1]["content"]}]
        for label, data in zip(labels, encoded):
            content.extend([{"type": "text", "text": label}, {"type": "image_url",
                "image_url": {"url": "data:image/png;base64," + data}}])
        body["messages"][1]["content"] = content
    else:
        raise VisualFailure("selected adapter has no image-content wire")
    return body


def _wire_images(body, adapter):
    if adapter == "responses":
        parts = body["input"][0]["content"]
        data = [p["image_url"].removeprefix("data:image/png;base64,") for p in parts if p.get("type") == "input_image"]
        if any(p.get("type") == "input_image" and not p.get("image_url", "").startswith("data:image/png;base64,") for p in parts):
            raise VisualFailure("only native inline PNG image blocks are admitted")
    elif adapter == "anthropic":
        images = [p for p in body["messages"][0]["content"] if p.get("type") == "image"]
        if any(p.get("source", {}).get("type") != "base64" or p["source"].get("media_type") != "image/png" for p in images):
            raise VisualFailure("only native inline PNG image blocks are admitted")
        data = [p["source"]["data"] for p in images]
    elif adapter == "gemini":
        images = [p["inlineData"] for p in body["contents"][0]["parts"] if "inlineData" in p]
        if any(p.get("mimeType") != "image/png" for p in images):
            raise VisualFailure("only native inline PNG image blocks are admitted")
        data = [p["data"] for p in images]
    elif adapter == "chat_completions":
        images = [p["image_url"]["url"] for p in body["messages"][1]["content"] if p.get("type") == "image_url"]
        if any(not d.startswith("data:image/png;base64,") for d in images):
            raise VisualFailure("only native inline PNG image blocks are admitted")
        data = [d.removeprefix("data:image/png;base64,") for d in images]
    else:
        raise VisualFailure("receipt adapter has no native image-content wire")
    return [base64.b64decode(d, validate=True) for d in data]


def completed_presentation(result, prepared, body, node, request):
    """Called only after this exact image request returns a valid model result."""
    if prepared is None:
        return result
    prepared.finish()
    adapter = result["transport"]["adapter"]
    if _wire_images(body, adapter) != prepared.rasters:
        raise VisualFailure("actual wire image population differs from rendered pages")
    result = deepcopy(result)
    result["isolation"]["visual_presentation"] = {"schema_version": 1,
        "kind": "native_image_content_presentation", "node_id": node["id"],
        "packet_sha256": request["packet"]["manifest_sha256"], "request_id": request["request_id"],
        "adapter": adapter, "requested_model": result["transport"]["requested_model"],
        **prepared.record, "wire_request": body, "wire_request_sha256": _digest(body),
        "provider_response_id": result["transport"]["response_id"],
        "scope": "completed image-content HTTP transport; comprehension and scientific truth are unestablished"}
    return result


def _verify_visual_presentation(receipt, *, expected_sources, expected_packet_sha256, expected_node_id):
    """Verify the ordinary current Graph receipt, never a caller visual pass bit.

    Render facts are retained observations of the source-pinned renderer, not a
    second numerical/rendering oracle. No PDF re-render or model call is made.
    """
    expected_sources = sources(expected_sources)
    if not expected_sources:
        return {"required_sources": [], "pages": 0, "scope": "no visual sources required"}
    if (receipt.get("kind") != "agent_model_receipt" or receipt.get("node_id") != expected_node_id
            or receipt.get("context_manifest_sha256") != expected_packet_sha256
            or receipt.get("execution_observation") not in {"remote_transport_observed", "local_transport_observed", "control_only"}):
        raise VisualFailure("current accounted HTTP role/packet receipt required")
    r = receipt.get("isolation", {}).get("visual_presentation")
    _keys(r, {"schema_version", "kind", "node_id", "packet_sha256", "request_id", "adapter", "requested_model",
              "sources", "renderer", "configuration", "settings", "render_elapsed_seconds", "wire_request",
              "wire_request_sha256", "provider_response_id", "scope"}, "visual presentation")
    if (type(r["schema_version"]) is not int or r["schema_version"] != 1 or r["kind"] != "native_image_content_presentation"
            or r["node_id"] != expected_node_id or r["packet_sha256"] != expected_packet_sha256
            or r["request_id"] != receipt["request_id"] or r["settings"] != _SETTING
            or r["adapter"] != receipt["transport"]["adapter"]
            or r["requested_model"] != receipt["transport"]["requested_model"]
            or r["provider_response_id"] != receipt["transport"]["response_id"]):
        raise VisualFailure("visual presentation belongs to a different current role/model")
    config = configuration(r["configuration"], r["adapter"])
    if (config is None or r["requested_model"] not in config["models"]
            or receipt["transport"].get("vision") != config
            or type(r["render_elapsed_seconds"]) not in (int, float)
            or not math.isfinite(r["render_elapsed_seconds"])
            or not 0 <= r["render_elapsed_seconds"] <= config["max_render_seconds"]):
        raise VisualFailure("configured vision capability/render accounting changed")
    body = r["wire_request"]
    if _digest(body) != r["wire_request_sha256"]:
        raise VisualFailure("actual image wire request changed")
    if r["adapter"] != "gemini" and body.get("model") != r["requested_model"]:
        raise VisualFailure("image wire selects a different model")
    calls = receipt.get("model_call_requests")
    if (type(calls) is not list or len(calls) != 1
            or calls[0].get("request_sha256") != r["wire_request_sha256"]):
        raise VisualFailure("image wire lacks the current accounted Graph call commitment")
    rows = r["sources"]
    if type(rows) is not list or [row.get("source") for row in rows] != expected_sources:
        raise VisualFailure("complete ordered figure source population differs")
    images = _wire_images(body, r["adapter"])
    _runtime_matches(r["renderer"])
    total_pages = total_pixels = total_bytes = 0
    from PIL import Image
    for row in rows:
        _keys(row, {"source", "artifact_id", "format", "page_count", "pages"}, "visual source record")
        pin = row["source"]
        raw, _ = _read(Path(pin["path"]), pin["size"])
        if len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise VisualFailure("current visual original is stale")
        count = _integer(row["page_count"], config["max_pages"], "complete page count")
        if row["format"] != Path(pin["path"]).suffix.lower()[1:] or (row["format"] == "png" and count != 1):
            raise VisualFailure("visual format/page population changed")
        if (type(row["pages"]) is not list or any(type(p.get("page_index")) is not int for p in row["pages"])
                or [p.get("page_index") for p in row["pages"]] != list(range(count))):
            raise VisualFailure("missing/reordered/truncated visual pages")
        if row["format"] == "png":
            expected_geometry = [list(_png_dimensions(raw))]
        else:
            # Independently read the complete current native PDF page census
            # and geometry, without repeating any bitmap render/model call.
            with _PDFIUM_LOCK:
                import pypdfium2 as pdfium
                with pdfium.PdfDocument(raw) as document:
                    if len(document) != count:
                        raise VisualFailure("reported PDF pages omit the actual source population")
                    expected_geometry = []
                    for j in range(count):
                        with closing(document[j]) as native_page:
                            expected_geometry.append(list(native_page.get_size()))
        for page in row["pages"]:
            _keys(page, {"page_index", "canvas_size", "raster"}, "visual page")
            canvas = expected_geometry[page["page_index"]]
            if (page["canvas_size"] != canvas
                    or not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in canvas)):
                raise VisualFailure("reported page geometry differs from actual complete source")
            if total_pages >= len(images):
                raise VisualFailure("missing actual image block")
            data = images[total_pages]
            raster = page["raster"]
            _keys(raster, {"sha256", "size", "width", "height", "mode", "pixels_sha256"}, "page raster")
            width, height = _png_dimensions(data)
            total_pixels += _geometry(width, height, config)
            scale = config["pdf_scale"] if row["format"] == "pdf" else 1
            if (width, height) != (math.ceil(canvas[0] * scale), math.ceil(canvas[1] * scale)):
                raise VisualFailure("sent raster truncates or resizes the full source page")
            if (raster["sha256"] != hashlib.sha256(data).hexdigest() or raster["size"] != len(data)
                    or (raster["width"], raster["height"]) != (width, height) or raster["mode"] != "RGB"):
                raise VisualFailure("sent image bytes differ from raster commitment")
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.mode != "RGB" or getattr(image, "n_frames", 1) != 1:
                    raise VisualFailure("one complete RGB PNG wire image required")
                image.load()
                if hashlib.sha256(image.tobytes()).hexdigest() != raster["pixels_sha256"]:
                    raise VisualFailure("sent pixels differ from renderer commitment")
            total_pages += 1
            total_bytes += len(data)
    if (total_pages != len(images) or total_pages > config["max_pages"] or total_pixels > config["max_total_pixels"]
            or total_bytes > config["max_raster_bytes"] or len(rows) > config["max_sources"]
            or sum(p["size"] for p in expected_sources) > config["max_source_bytes"]):
        raise VisualFailure("complete image population differs or exceeds declared limits")
    _runtime_matches(r["renderer"])
    return {"required_sources": expected_sources, "pages": total_pages, "pixels": total_pixels,
            "wire_request_sha256": r["wire_request_sha256"], "renderer_sha256": _digest(r["renderer"]),
            "scope": "current source/page/raster/image-wire custody; scientific inspection remains a review judgment"}


def verify_visual_presentation(receipt, *, expected_sources, expected_packet_sha256, expected_node_id):
    """Closed ordinary-role receipt verification; malformed/foreign data refuse."""
    try:
        return _verify_visual_presentation(receipt, expected_sources=expected_sources,
            expected_packet_sha256=expected_packet_sha256, expected_node_id=expected_node_id)
    except VisualFailure:
        raise
    except (KeyError, TypeError, ValueError, OSError, OverflowError, AttributeError):
        raise VisualFailure("malformed or unavailable current visual presentation") from None
