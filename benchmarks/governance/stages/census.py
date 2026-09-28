"""Stage 'census': the integrity and, for a complete file, the physics of one LHE sample (WP12 design §3.3).

Inputs in the run directory: ``inputs/events.lhe.gz`` (the sample as supplied), ``inputs/manifest.json``
(its production record: ``generation``, the production plan ``ravel.physics.scoped.audit_lhe`` checks
against, and ``file_sha256``, the digest of the file the record describes; other fields are not read)
and ``inputs/selection.json`` (a pair-invariant-mass selection, below). Runs only under the RAVEL stage
supervisor and writes ``outputs/census/census.json``.

First the stage's own integrity pass, standard library only. The kernel's readers give no count on a
truncated file (ElementTree raises), so they cannot provide the integrity facts (oracle appendix §3b):

- ``file_sha256``, ``file_bytes`` of the file as supplied; ``sha256_matches_record`` compares the
  digest with the record's ``file_sha256``.
- ``gzip_complete``: every gzip member ends at its end-of-stream marker and nothing follows the last
  one; otherwise ``stream_error`` is ``not_gzip``, ``truncated_stream``, ``corrupt_stream`` or
  ``trailing_data`` and the content is what decompressed before the fault.
- ``complete_events``: the event blocks closed by a ``</event>`` line inside the content (a block still
  open where the content ends is not counted; a last line cut before its newline counts only when it
  is exactly a closing tag). ``document_complete``: a ``</LesHouchesEvents>`` line closes the document
  outside any event block. ``header_nevents``: "Number of Events" in ``<MGGenerationInfo>``.

Then the physics, only when the gzip stream and the document are complete, ``complete_events`` equals
``header_nevents``, the selection's two particle ids are the plan's final state (the kernel's masses are
the invariant mass of the whole status-1 final state, so only then are they the selected pair's), and
``audit_lhe(path, manifest["generation"])`` passes: ``cross_section_pb`` and ``integration_error_pb``
(the kernel's), ``event_norm`` (the run card's, as the kernel read it), ``sum_weights`` and
``sum_weights_sq`` (math.fsum over each complete event's XWGTUP), ``selected_events`` (kernel masses
strictly inside the open window) and ``selected_sum_weights``. Otherwise every physics field is null,
``physics_status`` is ``withheld`` and ``physics_withheld_reasons`` names why: no prefix physics from a
truncated file (provisional decision D-CP, E-115). ``recipe_check`` is ``passed``, ``failed`` (with the
kernel's exception in ``recipe_check_error``) or ``not_run``. Categorical facts are booleans.

The selection: ``{observable: pair_invariant_mass, unit: GeV, pdg_ids: [two distinct integers],
status: 1, multiplicity: exactly_one_each, window: [low, high], edges: exclusive}`` with 0 <= low < high,
and an optional ``description``.
"""
import hashlib
import math
import os
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

STAGE = "census"
MAX_CONTENT_BYTES = 64 * 1024 * 1024
CHUNK = 1 << 16
GZIP_MAGIC = b"\x1f\x8b"
SELECTION_KEYS = {"observable", "unit", "pdg_ids", "status", "multiplicity", "window", "edges"}
PHYSICS_FIELDS = ("cross_section_pb", "integration_error_pb", "event_norm", "sum_weights", "sum_weights_sq",
                  "selected_events", "selected_sum_weights")
NEVENTS = re.compile(r"#?\s*Number of Events\s*:\s*([0-9]+)\s*$")
SHA256 = re.compile(r"[0-9a-f]{64}")


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def inflate(data):
    """(content, gzip_complete, stream_error) of gzip bytes. The content is what decompressed before any fault,
    fed in CHUNK-byte pieces (a corrupt piece loses its own output only)."""
    if data[:2] != GZIP_MAGIC:
        return b"", False, "not_gzip"
    content, rest = bytearray(), data
    while True:
        stream, used = zlib.decompressobj(zlib.MAX_WBITS | 16), 0
        while used < len(rest) and not stream.eof:
            piece = rest[used:used + CHUNK]
            used += len(piece)
            try:
                content += stream.decompress(piece, MAX_CONTENT_BYTES + 1 - len(content))
            except zlib.error:
                return bytes(content), False, "corrupt_stream"
            if len(content) > MAX_CONTENT_BYTES or stream.unconsumed_tail:
                raise ValueError(f"decompressed sample exceeds {MAX_CONTENT_BYTES} bytes")
        if not stream.eof:
            return bytes(content), False, "truncated_stream"
        rest = stream.unused_data + rest[used:]
        if not rest:
            return bytes(content), True, None
        if rest[:2] != GZIP_MAGIC:
            return bytes(content), False, "trailing_data"


def scan(content):
    """Integrity facts of decompressed LHE content and the XWGTUP of every complete event, in file order."""
    lines = content.split(b"\n")
    cut = lines.pop() if lines and lines[-1] != b"" else None   # a last line without its newline
    if lines and lines[-1] == b"" and cut is None:
        lines.pop()
    if cut is not None and cut.strip() in (b"</event>", b"</LesHouchesEvents>"):
        lines.append(cut)
    events, weights, nevents = 0, [], None
    inside, first, closed, generation_info = False, None, False, False
    for raw in lines:
        line = raw.strip()
        if line == b"<MGGenerationInfo>":
            generation_info = True
        elif line == b"</MGGenerationInfo>":
            generation_info = False
        elif generation_info:
            found = NEVENTS.match(line.decode("ascii", "replace"))
            if found:
                nevents = int(found.group(1))
        elif line == b"<event>" or line.startswith(b"<event "):
            inside, first = True, None
        elif line == b"</event>" and inside:
            inside, events = False, events + 1
            fields = first.split() if first is not None else []
            if len(fields) != 6:
                raise ValueError(f"event {events}: the header line needs 6 fields")
            weights.append(float(fields[2]))
        elif inside and first is None and line and not line.startswith((b"<", b"#")):
            first = line.decode("ascii")
        elif line == b"</LesHouchesEvents>" and not inside:
            closed = True
    return {"complete_events": events, "document_complete": closed and not inside, "header_nevents": nevents,
            "weights": weights}


def parse_selection(selection):
    """(pdg_ids, low, high) of a pair-invariant-mass selection with an open window, or ValueError."""
    if not isinstance(selection, dict) or not SELECTION_KEYS <= set(selection) <= SELECTION_KEYS | {"description"}:
        raise ValueError(f"selection: fields must be {sorted(SELECTION_KEYS)} (optional description)")
    ids, window = selection["pdg_ids"], selection["window"]
    checks = [
        (selection["observable"] == "pair_invariant_mass", "observable must be pair_invariant_mass"),
        (selection["unit"] == "GeV", "unit must be GeV"),
        (isinstance(ids, list) and len(ids) == 2 and all(type(v) is int for v in ids) and ids[0] != ids[1],
         "pdg_ids must be two distinct integers"),
        (selection["status"] == 1 and type(selection["status"]) is int, "status must be 1 (final state)"),
        (selection["multiplicity"] == "exactly_one_each", "multiplicity must be exactly_one_each"),
        (selection["edges"] == "exclusive", "edges must be exclusive (an open window)"),
        (isinstance(window, list) and len(window) == 2
         and all(type(v) in (int, float) and math.isfinite(v) for v in window)
         and 0 <= window[0] < window[1], "window must be [low, high] with 0 <= low < high"),
        (isinstance(selection.get("description", ""), str), "description must be text"),
    ]
    for ok, message in checks:
        if not ok:
            raise ValueError(f"selection: {message}")
    return list(ids), float(window[0]), float(window[1])


def census(path, manifest, selection):
    """The census record of one sample file (see the module docstring)."""
    from ravel.physics.scoped import audit_lhe
    data = Path(path).read_bytes()
    pdg_ids, low, high = parse_selection(selection)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("generation"), dict):
        raise ValueError("manifest: a production record with a generation plan is required")
    record_sha256 = manifest.get("file_sha256")
    if not (isinstance(record_sha256, str) and SHA256.fullmatch(record_sha256)):
        raise ValueError("manifest: file_sha256 must be 64 lowercase hex characters")
    file_sha256 = hashlib.sha256(data).hexdigest()
    content, gzip_complete, stream_error = inflate(data)
    facts = scan(content)
    reasons = []
    if not gzip_complete:
        reasons.append("gzip_incomplete")
    if not facts["document_complete"]:
        reasons.append("document_incomplete")
    if facts["header_nevents"] is None:
        reasons.append("header_nevents_missing")
    elif facts["complete_events"] != facts["header_nevents"]:
        reasons.append("event_count_mismatch")
    observable = manifest["generation"].get("observable")
    final_state = observable.get("final_state_pdg") if isinstance(observable, dict) else None
    if not (isinstance(final_state, list) and all(type(v) is int for v in final_state)
            and Counter(final_state) == Counter(pdg_ids)):
        reasons.append("selection_not_the_plan_final_state")
    physics = dict.fromkeys(PHYSICS_FIELDS)
    recipe_check, recipe_error = "not_run", None
    if not reasons:
        try:
            audit = audit_lhe(path, manifest["generation"])
        except Exception as exc:   # the kernel's own verdict on the file against the plan
            recipe_check, recipe_error = "failed", f"{type(exc).__name__}: {exc}"
            reasons.append("recipe_check_failed")
        else:
            recipe_check = "passed"
            masses, weights = audit["masses_gev"], facts["weights"]
            if not (audit["events"] == len(masses) == len(weights) == facts["complete_events"]):
                reasons.append("reader_count_disagreement")
            else:
                chosen = [w for m, w in zip(masses, weights) if low < m < high]
                physics.update(cross_section_pb=float(audit["cross_section_pb"]),
                               integration_error_pb=float(audit["integration_error_pb"]),
                               event_norm=audit["recipe"]["run_settings"].get("event_norm"),
                               sum_weights=math.fsum(weights), sum_weights_sq=math.fsum(w * w for w in weights),
                               selected_events=len(chosen), selected_sum_weights=math.fsum(chosen))
    return {"schema_version": 1, "file_sha256": file_sha256, "file_bytes": len(data), "record_sha256": record_sha256,
            "sha256_matches_record": file_sha256 == record_sha256, "gzip_complete": gzip_complete,
            "stream_error": stream_error, "document_complete": facts["document_complete"],
            "complete_events": facts["complete_events"], "header_nevents": facts["header_nevents"],
            "physics_status": "withheld" if reasons else "computed", "physics_withheld_reasons": reasons,
            "recipe_check": recipe_check, "recipe_check_error": recipe_error, **physics,
            "selection": {"pdg_ids": pdg_ids, "status": 1, "window_gev": [low, high], "edges": "exclusive"},
            "readers": {"integrity": "census stage line scan", "physics": "ravel.physics.scoped.audit_lhe"}}


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json, read_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        atomic_json(out / "census.json", census(rd / "inputs/events.lhe.gz", read_json(rd / "inputs/manifest.json"),
                                                read_json(rd / "inputs/selection.json")))
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
