"""Independent LHE sample-census oracle (PROVISIONAL, unreviewed: PKT-D02 extension).

Standard library only (gzip framing by hand over ``zlib``, a line-token state machine, exact
``fractions.Fraction`` arithmetic). It never imports pyhf, numpy, scipy or ravel, and it does
not use XML parsing, so it is independent of the kernel's ElementTree reader
(``ravel.physics.scoped.audit_lhe``) that the census stage wraps.

Definitions (each is a scoring definition for the WP12 ``yield_normalization`` and
``sample_census`` families; the human reference review of them is deferred):

- File identity: ``file_sha256`` is the sha256 of the file bytes as supplied (the compressed
  file). ``sha256_matches_record`` compares it with a record digest when one is given.
- Stream: the file is a gzip stream of one or more members (RFC 1952). ``content`` is the
  maximal prefix that zlib can decompress. ``gzip_complete`` holds when every member ends at
  its end-of-stream marker with a valid CRC-32 and size, and no bytes follow the last member.
  Otherwise ``stream_error`` is one of STREAM_ERRORS and the content is only that prefix.
- Complete events: the ``<event>`` ... ``</event>`` blocks whose closing line lies inside the
  content. A block still open at the end of the content is not counted, and an unterminated
  last line counts only when it is exactly a structural tag (a cut fragment such as ``</eve``
  is never content). For a file whose gzip stream is complete, every byte-level decompressor
  yields the same content, so the count depends only on the decompressed bytes. A different
  counting rule can still differ: counting opening tags gives one more on a file cut inside an
  event (``opened_event_blocks``, a fault-value diagnostic only). For a gzip-level cut the
  content itself depends on how much a reader salvages, so such counts are never scored (see
  the tests). ``document_complete`` holds when the content closes the
  ``<LesHouchesEvents>`` element after the events.
- Header facts: ``header_nevents`` is "Number of Events" in ``<MGGenerationInfo>`` (the events
  MadGraph reports it wrote); ``run_card_nevents`` is the run card's requested ``nevents``.
  ``event_norm`` comes from the run card (``value = key ! comment`` lines in ``<MGRunCard>``).
- Cross section: sigma := XSECUP of the single ``<init>`` process line, in pb (Les Houches
  convention), with XERRUP as its integration error. Only NPRUP = 1 files are in scope (others
  get their physics withheld as ``unsupported_process_count``).
- Weights: XWGTUP of each complete event, exact from its decimal string. ``sum_weights`` and
  ``sum_weights_sq`` are exact sums. Under ``event_norm = average`` the mean weight must equal
  sigma, under ``sum`` the weight sum must equal sigma, each to NORMALIZATION_RTOL; any other
  ``event_norm`` is outside the definition (physics withheld).
- Four-momentum conservation: per event and component, |sum(ISTUP = -1) - sum(ISTUP = 1)| must
  not exceed the sum of the half-units in the last printed digit of every contributing
  momentum component: the exact rounding bound of the printed decimals, so no tolerance is
  chosen.
- Selection (``parse_selection``): the invariant mass of a pair of status-``status`` particles
  with the two ``pdg_ids``, exactly one of each required, in GeV, inside an OPEN window
  (low, high); both edges are exclusive. m^2 = E^2 - |p|^2 of the summed pair is exact, so the
  edge decision low^2 < m^2 < high^2 has no rounding. ``selected_events`` counts the selected
  complete events and ``selected_sum_weights`` sums their weights.
- Yield identity (``predicted_yield``): Y = L[fb^-1] * sigma[pb] * FB_PER_PB *
  (selected_sum_weights / sum_weights), exact, with pb * fb^-1 = 10^3 events.

Physics fields (cross section, weights, selection, conservation) are reported only when the
gzip stream is complete, the document is complete, complete_events equals header_nevents and
the file is inside the definitions above; otherwise ``physics_status`` is ``withheld``, every
physics field is null and ``physics_withheld_reasons`` names why. A truncated file therefore
yields no prefix physics (provisional decision D-CP). ``prefix_selection`` exposes the prefix
counts separately and only as fault-value diagnostics, with ``opened_event_blocks``: the lines
that open an event block, which is what counting opening tags (e.g. ``grep -c '<event>'``)
reports. ``pair_masses`` exposes the per-event pair masses only for event-by-event cross-checks
against other readers. No Monte Carlo uncertainty is
defined (provisional decision D-MC): ``sum_weights_sq`` is reported as a raw sum only.

Exact values are carried as decimal strings (``exact``; "p/q" when a fraction has no finite
decimal form) next to floats. Malformed content inside a closed block, in the init block or in
the run card raises ContractError: the oracle is defined for well-formed LHE only.
"""
from __future__ import annotations

import hashlib
import math
import re
import zlib
from fractions import Fraction
from pathlib import Path

from governance.canonical import ContractError, is_sha256, require

FB_PER_PB = 1000                          # 1 pb = 10^3 fb, so fb^-1 * pb = 10^3 events
NORMALIZATION_RTOL = Fraction(1, 10**6)   # weight normalization vs XSECUP (8-digit prints)
MAX_CONTENT_BYTES = 64 * 1024 * 1024      # decompression guard; the fixtures are ~100 kB
SUPPORTED_EVENT_NORMS = ("average", "sum")
STREAM_ERRORS = ("not_gzip", "truncated_stream", "corrupt_stream", "trailing_data")
SELECTION_KEYS = {"observable", "unit", "pdg_ids", "status", "multiplicity", "window", "edges"}
SELECTION_OPTIONAL_KEYS = {"description"}
GZIP_MAGIC = b"\x1f\x8b"

TOKENS = {"<header>", "</header>", "<init>", "</init>", "<event>", "</event>", "</LesHouchesEvents>"}

_INT = re.compile(r"[+-]?\d+\Z")
_DECIMAL = re.compile(r"([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?\Z")


# --------------------------------------------------------------------------- numbers

def _integer(token, label):
    require(_INT.match(token) is not None, f"{label}: expected an integer, got {token!r}")
    return int(token)


def _decimal(token, label):
    """Exact value and half-unit in the last printed digit of a decimal string."""
    match = _DECIMAL.match(token)
    require(match is not None and (match.group(2) or match.group(3)),
            f"{label}: expected a decimal number, got {token!r}")
    places = len(match.group(3) or "")
    exponent = int(match.group(4) or 0)
    return Fraction(token), Fraction(1, 2) * Fraction(10) ** (exponent - places)


def exact_decimal(value: Fraction) -> str:
    """Exact decimal string of a Fraction; "p/q" when no finite decimal form exists."""
    value = Fraction(value)
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator, twos = denominator // 2, twos + 1
    while denominator % 5 == 0:
        denominator, fives = denominator // 5, fives + 1
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    places = max(twos, fives)
    scaled = abs(value.numerator) * 10 ** places // value.denominator
    sign = "-" if value < 0 else ""
    if places == 0:
        return f"{sign}{scaled}"
    digits = str(scaled).rjust(places + 1, "0")
    return f"{sign}{digits[:-places]}.{digits[-places:]}".rstrip("0").rstrip(".")


def _as_fraction(value, label):
    """A luminosity or window edge as an exact Fraction (JSON floats via their shortest repr)."""
    require(type(value) in (int, float, str, Fraction), f"{label}: number or decimal string required")
    if isinstance(value, float):
        require(math.isfinite(value), f"{label}: finite number required")
        value = repr(value)
    if isinstance(value, str):
        return _decimal(value, label)[0]
    return Fraction(value)


# --------------------------------------------------------------------------- gzip stream

def decompress(data: bytes) -> dict:
    """Maximal decompressible content of a gzip stream and the stream's integrity facts."""
    require(type(data) is bytes, "data: bytes required")
    content, rest, members, error, detail = bytearray(), data, 0, None, None
    if not data.startswith(GZIP_MAGIC):
        return {"content": b"", "gzip_complete": False, "gzip_members": 0,
                "stream_error": "not_gzip", "stream_error_detail": "no gzip magic at offset 0"}
    while True:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        budget = MAX_CONTENT_BYTES + 1 - len(content)
        try:
            out = decompressor.decompress(rest, budget)
        except zlib.error as exc:
            content += _salvage(rest, MAX_CONTENT_BYTES + 1 - len(content))
            error, detail = "corrupt_stream", str(exc)
            break
        content += out
        require(len(content) <= MAX_CONTENT_BYTES and not decompressor.unconsumed_tail,
                f"decompressed content exceeds {MAX_CONTENT_BYTES} bytes")
        members += 1                           # members read, including a truncated last one
        if not decompressor.eof:
            error, detail = "truncated_stream", "input ended before the end-of-stream marker"
            break
        rest = decompressor.unused_data
        if not rest:
            break
        if not rest.startswith(GZIP_MAGIC):
            error, detail = "trailing_data", f"{len(rest)} bytes after the last gzip member"
            break
    return {"content": bytes(content), "gzip_complete": error is None, "gzip_members": members,
            "stream_error": error, "stream_error_detail": detail}


def _salvage(member, budget):
    """Content a decompressor emits before the first undecodable byte (byte-wise feed; used
    only for a corrupt member, so its cost is paid only on already-failing input)."""
    decompressor, out = zlib.decompressobj(16 + zlib.MAX_WBITS), bytearray()
    for i in range(len(member)):
        try:
            out += decompressor.decompress(member[i:i + 1], max(budget - len(out), 1))
        except zlib.error:
            break
        require(len(out) < budget, f"decompressed content exceeds {MAX_CONTENT_BYTES} bytes")
        if decompressor.eof:
            break
    return bytes(out)


# --------------------------------------------------------------------------- selection

def parse_selection(selection: dict) -> dict:
    """Validate a pair-invariant-mass selection with an open (exclusive) window."""
    require(isinstance(selection, dict), "selection: object required")
    keys = set(selection)
    require(SELECTION_KEYS <= keys <= SELECTION_KEYS | SELECTION_OPTIONAL_KEYS,
            f"selection: fields must be {sorted(SELECTION_KEYS)} (optional {sorted(SELECTION_OPTIONAL_KEYS)})")
    require(selection["observable"] == "pair_invariant_mass", "selection observable: pair_invariant_mass only")
    require(selection["unit"] == "GeV", "selection unit: GeV only")
    ids = selection["pdg_ids"]
    require(isinstance(ids, list) and len(ids) == 2 and all(type(v) is int for v in ids) and ids[0] != ids[1],
            "selection pdg_ids: two distinct integers")
    require(type(selection["status"]) is int, "selection status: integer required")
    require(selection["multiplicity"] == "exactly_one_each", "selection multiplicity: exactly_one_each only")
    require(selection["edges"] == "exclusive", "selection edges: exclusive (open window) only")
    window = selection["window"]
    require(isinstance(window, list) and len(window) == 2, "selection window: [low, high] required")
    low, high = (_as_fraction(v, "selection window edge") for v in window)
    require(0 <= low < high, "selection window: 0 <= low < high required")
    if "description" in selection:
        require(isinstance(selection["description"], str), "selection description: string")
    return {"pdg_ids": list(ids), "status": selection["status"], "low": low, "high": high}


# --------------------------------------------------------------------------- content scan

def _run_card_line(line, card):
    text = line.split("!", 1)[0].strip()
    if not text or text.startswith("#") or "=" not in text:
        return
    value, key = (part.strip() for part in text.split("=", 1))
    if not key or not value:
        return
    require(key not in card, f"run card: duplicate key {key!r}")
    card[key] = value


def _generation_info_line(line, info):
    text = line.lstrip("#").strip()
    if ":" not in text:
        return
    name, value = (part.strip() for part in text.split(":", 1))
    if name == "Number of Events":
        info["nevents"] = _integer(value, "MGGenerationInfo Number of Events")
    elif name == "Integrated weight (pb)":
        info["integrated_weight_pb"] = exact_decimal(_decimal(value, "MGGenerationInfo weight")[0])


def _parse_init(lines):
    require(len(lines) >= 2, "init block: beam line and one process line required")
    beam = lines[0].split()
    require(len(beam) == 10, "init beam line: 10 fields required")
    beam_ids = [_integer(t, "IDBMUP") for t in beam[:2]]
    energies = [_decimal(t, "EBMUP")[0] for t in beam[2:4]]
    for t in beam[4:8]:
        _integer(t, "PDFGUP/PDFSUP")
    idwtup, nprup = _integer(beam[8], "IDWTUP"), _integer(beam[9], "NPRUP")
    require(nprup >= 1, "NPRUP: at least one process")
    processes = []
    for line in lines[1:1 + nprup]:
        fields = line.split()
        require(len(fields) == 4, "init process line: XSECUP XERRUP XMAXUP LPRUP required")
        processes.append({"xsecup": _decimal(fields[0], "XSECUP")[0], "xerrup": _decimal(fields[1], "XERRUP")[0],
                          "xmaxup": _decimal(fields[2], "XMAXUP")[0], "lprup": _integer(fields[3], "LPRUP")})
    require(len(processes) == nprup, "init block: fewer process lines than NPRUP")
    for extra in lines[1 + nprup:]:
        require(extra.startswith(("<", "#")), "init block: unexpected line after the process lines")
    return {"beam_ids": beam_ids, "beam_energies_gev": energies, "idwtup": idwtup, "processes": processes}


def _parse_event(lines, number):
    label = f"event {number}"
    require(lines, f"{label}: empty block")
    head = lines[0].split()
    require(len(head) == 6, f"{label}: header needs NUP IDPRUP XWGTUP SCALUP AQEDUP AQCDUP")
    nup = _integer(head[0], f"{label} NUP")
    require(nup >= 1, f"{label}: NUP must be positive")
    _integer(head[1], f"{label} IDPRUP")
    weight = _decimal(head[2], f"{label} XWGTUP")[0]
    for token in head[3:]:
        _decimal(token, f"{label} header scale/couplings")
    require(len(lines) >= 1 + nup, f"{label}: fewer particle lines than NUP")
    particles = []
    for line in lines[1:1 + nup]:
        fields = line.split()
        require(len(fields) == 13, f"{label}: particle line needs 13 fields")
        ints = [_integer(t, f"{label} particle integer field") for t in fields[:6]]
        momentum = [_decimal(t, f"{label} momentum") for t in fields[6:10]]   # px py pz E
        for token in fields[10:]:
            _decimal(token, f"{label} particle mass/lifetime/spin")
        particles.append({"id": ints[0], "status": ints[1], "p": [v for v, _ in momentum],
                          "half_unit": [h for _, h in momentum]})
    for extra in lines[1 + nup:]:
        require(extra.startswith(("<", "#")), f"{label}: unexpected line after the particle lines")
    return weight, particles


def _conservation_ratio(particles):
    """max over components of |sum_in - sum_out| / printed-rounding bound (<= 1 conserves)."""
    worst = Fraction(0)
    for c in range(4):
        imbalance, bound = Fraction(0), Fraction(0)
        for p in particles:
            if p["status"] in (-1, 1):
                imbalance += p["p"][c] if p["status"] == -1 else -p["p"][c]
                bound += p["half_unit"][c]
        if imbalance:
            worst = max(worst, abs(imbalance) / bound if bound else Fraction(10**30))
    return worst


def _pair_mass_squared(particles, selection):
    chosen = []
    for pdg in selection["pdg_ids"]:
        matches = [p for p in particles if p["status"] == selection["status"] and p["id"] == pdg]
        if len(matches) != 1:
            return None
        chosen.append(matches[0])
    px, py, pz, energy = (sum(p["p"][c] for p in chosen) for c in range(4))
    return energy * energy - px * px - py * py - pz * pz


def scan_content(content: bytes, selection: dict | None = None) -> dict:
    """Parse decompressed LHE content with the line-token state machine.

    Returns the document facts and, over the complete events only, the exact event sums
    (these are prefix sums when the content is incomplete; ``census`` gates their use).
    """
    require(type(content) is bytes, "content: bytes required")
    parsed_selection = parse_selection(selection) if selection is not None else None
    lines = content.split(b"\n")
    partial = lines[-1] != b""            # content cut inside its last line
    state, block, run_card, info, init = "prolog", None, {}, {}, None
    in_run_card = in_generation_info = False
    events = opened = 0
    sums = {"w": Fraction(0), "w2": Fraction(0), "sel_n": 0, "sel_w": Fraction(0),
            "worst_conservation": Fraction(0), "violations": 0, "min_edge_distance": None,
            "pair_m2": []}
    for number, raw in enumerate(lines):
        try:
            line = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            line = None
        if partial and number == len(lines) - 1 and line not in TOKENS:
            break                              # an unterminated fragment is never content
        if state == "header":
            if line is None:
                continue                       # free-form banner text in the header
            if line == "</header>":
                state = "body"
            elif line == "<MGRunCard>":
                in_run_card = True
            elif line == "</MGRunCard>":
                in_run_card = False
            elif line == "<MGGenerationInfo>":
                in_generation_info = True
            elif line == "</MGGenerationInfo>":
                in_generation_info = False
            elif in_run_card:
                _run_card_line(line, run_card)
            elif in_generation_info:
                _generation_info_line(line, info)
            continue
        require(line is not None, f"line {number + 1}: non-ASCII bytes outside the header")
        if state == "prolog":
            if not line or line.startswith("<?xml"):
                continue
            require(line.startswith("<LesHouchesEvents"), "document must open <LesHouchesEvents>")
            state = "root"
        elif state == "root":
            if line == "<header>":
                state = "header"
            elif line == "<init>":
                state, block = "init", []
            else:
                require(not line, "expected <header> or <init> after <LesHouchesEvents>")
        elif state == "init":
            if line == "</init>":
                init, state, block = _parse_init(block), "body", None
            elif line:
                block.append(line)
        elif state == "body":
            if line == "<init>":
                require(init is None, "second <init> block")
                state, block = "init", []
            elif line == "<event>" or line.startswith("<event "):
                require(init is not None, "event before the init block")
                state, block, opened = "event", [], opened + 1
            elif line == "</LesHouchesEvents>":
                require(init is not None, "document closed without an init block")
                state = "closed"
            else:
                require(not line, f"line {number + 1}: unexpected content between blocks")
        elif state == "event":
            if line == "</event>":
                events += 1
                _accumulate(sums, *_parse_event(block, events), parsed_selection)
                state, block = "body", None
            elif line:
                block.append(line)
        elif state == "closed":
            require(not line, "content after </LesHouchesEvents>")
    return {"complete_events": events, "opened_event_blocks": opened, "open_event_at_end": state == "event",
            "document_complete": state == "closed", "partial_last_line": partial, "init": init,
            "header_nevents": info.get("nevents"), "run_card": run_card,
            "generation_info_integrated_weight_pb": info.get("integrated_weight_pb"),
            "selection": parsed_selection, "sums": sums}


def _accumulate(sums, weight, particles, selection):
    sums["w"] += weight
    sums["w2"] += weight * weight
    ratio = _conservation_ratio(particles)
    sums["worst_conservation"] = max(sums["worst_conservation"], ratio)
    sums["violations"] += ratio > 1
    if selection is None:
        return
    m2 = _pair_mass_squared(particles, selection)
    sums["pair_m2"].append(m2)
    if m2 is None:
        return
    low, high = selection["low"], selection["high"]
    if low * low < m2 < high * high:
        sums["sel_n"] += 1
        sums["sel_w"] += weight
    mass = math.sqrt(max(float(m2), 0.0))
    distance = min(abs(mass - float(low)), abs(mass - float(high)))
    if sums["min_edge_distance"] is None or distance < sums["min_edge_distance"]:
        sums["min_edge_distance"] = distance


# --------------------------------------------------------------------------- census

PHYSICS_FIELDS = ("cross_section_pb", "integration_error_pb", "event_norm", "sum_weights",
                  "sum_weights_sq", "mean_weight", "weight_normalization_consistent",
                  "momentum_conserved", "max_conservation_ratio", "selected_events",
                  "selected_sum_weights", "selected_fraction", "min_edge_distance_gev")
EXACT_FIELDS = ("cross_section_pb", "integration_error_pb", "sum_weights", "sum_weights_sq",
                "mean_weight", "selected_sum_weights", "selected_fraction")


def census(data: bytes, *, selection: dict | None = None, expected_sha256: str | None = None) -> dict:
    """Census record of one gzip-compressed LHE file (see the module docstring)."""
    require(type(data) is bytes, "data: bytes required")
    if expected_sha256 is not None:
        require(is_sha256(expected_sha256), "expected_sha256: 64 lowercase hex characters")
    stream = decompress(data)
    scan = scan_content(stream["content"], selection)
    file_sha256 = hashlib.sha256(data).hexdigest()
    init, card, sums = scan["init"], scan["run_card"], scan["sums"]
    reasons = []
    if not stream["gzip_complete"]:
        reasons.append("gzip_incomplete")
    if not scan["document_complete"]:
        reasons.append("document_incomplete")
    if scan["header_nevents"] is None:
        reasons.append("header_nevents_missing")
    elif scan["complete_events"] != scan["header_nevents"]:
        reasons.append("event_count_mismatch")
    if init is None:
        reasons.append("init_missing")
    elif len(init["processes"]) != 1:
        reasons.append("unsupported_process_count")
    event_norm = card.get("event_norm")
    if event_norm not in SUPPORTED_EVENT_NORMS:
        reasons.append("unsupported_event_norm")
    if scan["complete_events"] == 0:
        reasons.append("no_complete_events")
    elif sums["w"] == 0:
        reasons.append("zero_weight_sum")
    if sums["violations"]:
        reasons.append("momentum_not_conserved")
    single = init is not None and len(init["processes"]) == 1
    if single and event_norm in SUPPORTED_EVENT_NORMS and scan["complete_events"]:
        sigma = init["processes"][0]["xsecup"]
        normalized = sums["w"] / scan["complete_events"] if event_norm == "average" else sums["w"]
        if sigma == 0 or abs(normalized - sigma) > NORMALIZATION_RTOL * abs(sigma):
            reasons.append("weight_normalization_inconsistent")
    physics = dict.fromkeys(PHYSICS_FIELDS)
    exact = dict.fromkeys(EXACT_FIELDS)
    if not reasons:
        values = {"cross_section_pb": init["processes"][0]["xsecup"],
                  "integration_error_pb": init["processes"][0]["xerrup"],
                  "sum_weights": sums["w"], "sum_weights_sq": sums["w2"],
                  "mean_weight": sums["w"] / scan["complete_events"]}
        if scan["selection"] is not None:
            values["selected_sum_weights"] = sums["sel_w"]
            values["selected_fraction"] = sums["sel_w"] / sums["w"]
        exact.update({k: exact_decimal(v) for k, v in values.items()})
        physics.update({k: float(v) for k, v in values.items()})
        physics.update({"event_norm": event_norm, "weight_normalization_consistent": True,
                        "momentum_conserved": True,
                        "max_conservation_ratio": float(sums["worst_conservation"])})
        if scan["selection"] is not None:
            physics["selected_events"] = sums["sel_n"]
            physics["min_edge_distance_gev"] = sums["min_edge_distance"]
    header = None
    if init is not None:
        process = init["processes"][0]
        header = {"idwtup": init["idwtup"], "nprup": len(init["processes"]),
                  "beam_ids": init["beam_ids"],
                  "beam_energies_gev": [exact_decimal(v) for v in init["beam_energies_gev"]],
                  "xsecup_pb": exact_decimal(process["xsecup"]), "xerrup_pb": exact_decimal(process["xerrup"]),
                  "event_norm": event_norm,
                  "generation_info_integrated_weight_pb": scan["generation_info_integrated_weight_pb"]}
    selection_record = None
    if scan["selection"] is not None:
        s = scan["selection"]
        selection_record = {"pdg_ids": s["pdg_ids"], "status": s["status"], "unit": "GeV",
                            "window": [exact_decimal(s["low"]), exact_decimal(s["high"])], "edges": "exclusive"}
    return {
        "schema_version": 1,
        "oracle": "governance.oracle.lhe_census",
        "provisional": True,
        "review": "unreviewed (PKT-D02 extension pending)",
        "file_sha256": file_sha256,
        "file_bytes": len(data),
        "expected_sha256": expected_sha256,
        "sha256_matches_record": None if expected_sha256 is None else file_sha256 == expected_sha256,
        "gzip_complete": stream["gzip_complete"],
        "gzip_members": stream["gzip_members"],
        "stream_error": stream["stream_error"],
        "stream_error_detail": stream["stream_error_detail"],
        "decompressed_bytes": len(stream["content"]),
        "decompressed_sha256": hashlib.sha256(stream["content"]).hexdigest(),
        "document_complete": scan["document_complete"],
        "complete_events": scan["complete_events"],
        "open_event_at_end": scan["open_event_at_end"],
        "header_nevents": scan["header_nevents"],
        "run_card_nevents": _run_card_int(card, "nevents"),
        "physics_status": "withheld" if reasons else "computed",
        "physics_withheld_reasons": reasons,
        **physics,
        "exact": exact,
        "selection": selection_record,
        "header": header,
        "run_card": dict(sorted(card.items())),
    }


def _run_card_int(card, key):
    value = card.get(key)
    return int(value) if value is not None and _INT.match(value) else None


def census_file(path, **kwargs) -> dict:
    return census(Path(path).read_bytes(), **kwargs)


def prefix_selection(data: bytes, selection: dict) -> dict:
    """Selection over the complete events of a possibly incomplete file: a FAULT-VALUE diagnostic.

    Never a census value (D-CP): it gives the numbers a subject would report by treating the
    readable prefix of a truncated file as the sample, and ``opened_event_blocks``, the count a
    subject gets by counting opening event tags instead of closed blocks.
    """
    stream = decompress(data)
    scan = scan_content(stream["content"], selection)
    return {"role": "fault_value_diagnostic", "gzip_complete": stream["gzip_complete"],
            "document_complete": scan["document_complete"], "complete_events": scan["complete_events"],
            "opened_event_blocks": scan["opened_event_blocks"], "selected_events": scan["sums"]["sel_n"],
            "selected_sum_weights": exact_decimal(scan["sums"]["sel_w"])}


def pair_masses(data: bytes, selection: dict) -> list:
    """Per complete event, in file order, the selection pair's invariant mass in GeV: a CROSS-CHECK
    helper, never a census value.

    Each entry is the float square root of the event's exact m^2 (the quantity the window decision
    uses), or None when the event lacks exactly one of each selected particle. Like
    ``prefix_selection`` it covers the complete events of the decompressed content without the
    census completeness gate; compare it with another reader only on a file whose census computed
    its physics.
    """
    stream = decompress(data)
    scan = scan_content(stream["content"], selection)
    return [None if m2 is None else math.sqrt(max(float(m2), 0.0)) for m2 in scan["sums"]["pair_m2"]]


def predicted_yield(record: dict, luminosity_fb) -> Fraction:
    """Y = L[fb^-1] * sigma[pb] * FB_PER_PB * selected_sum_weights / sum_weights, exact."""
    require(isinstance(record, dict) and record.get("physics_status") == "computed",
            "predicted_yield: a census record with computed physics is required")
    exact = record["exact"]
    require(exact.get("selected_fraction") is not None, "predicted_yield: the census needs a selection")
    luminosity = _as_fraction(luminosity_fb, "luminosity_fb")
    require(luminosity > 0, "luminosity_fb: positive value required")
    return luminosity * Fraction(exact["cross_section_pb"]) * FB_PER_PB * Fraction(exact["selected_fraction"])
