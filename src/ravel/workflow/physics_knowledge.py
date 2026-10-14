"""Located physics knowledge for the existing context, research and construction graph.

This is an immutable source index, not a second research journal. Retrieval
preserves conflicting assertions and exploratory hypotheses. Named pure checks
verify supplied algebra only; neither source custody nor a check grants physics
validation, study approval or an executable model's applicability.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_PACKET_BYTES = 512 * 1024
MAX_NODES = 512
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}")
CHECKS = {"coherent-amplitude-square", "two-body-width", "ordered-beam-prefactor"}


def _keys(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("closed physics knowledge fields required: " + ", ".join(fields))


def _text(value, maximum=8000):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("bounded nonempty physics knowledge text required")
    return value


def _id(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise ValueError("stable bounded knowledge identity required")
    return value


def _items(value, maximum, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError("bounded knowledge population required")
    return value


def _labels(value):
    for label in _items(value, 64):
        _text(label, 200)
    if len(value) != len(set(value)):
        raise ValueError("unique knowledge labels required")
    return value


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate knowledge JSON key")
            result[key] = value
        return result
    def refuse(_):
        raise ValueError("nonfinite knowledge JSON")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=refuse)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)


def _snapshot(pin, base):
    _keys(pin, ("path", "sha256", "size"))
    _text(pin["path"], 4096)
    if type(pin["size"]) is not int or not 0 < pin["size"] <= MAX_DOCUMENT_BYTES:
        raise ValueError("positive bounded source file size required")
    if type(pin["sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"]):
        raise ValueError("exact source SHA256 required")
    rawpath = Path(pin["path"])
    path = (rawpath if rawpath.is_absolute() else Path(base) / rawpath).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("source path cannot traverse symlinks")
    path = path.resolve()
    initial = path.stat()
    if not stat.S_ISREG(initial.st_mode) or initial.st_size != pin["size"]:
        raise ValueError("declared ordinary source file required")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(pin["size"] + 1)
        after = os.fstat(stream.fileno())
    if not (_identity(initial) == _identity(before) == _identity(after) == _identity(path.stat())):
        raise ValueError("source changed during bounded descriptor read")
    if len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("source bytes differ from declared pin")
    return {"path": str(path), "sha256": pin["sha256"], "size": len(raw)}, raw


def _recheck(inventory):
    for pin in inventory:
        _, raw = _snapshot(pin, Path.cwd())
        # The closed literature custody manifest authenticates large original
        # PDFs without widening ordinary member or presentation bounds.
        if b'literature-original-custody/v1' in raw:
            try:
                value = _json(raw)
            except (ValueError, UnicodeError):
                continue
            if type(value) is dict and value.get('kind') == 'literature-original-custody/v1':
                from . import literature_context
                literature_context.source_manifest(pin, base_dir=Path.cwd())


def _load(request, base):
    _keys(request, ("schema_version", "knowledge", "query"))
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("physics knowledge request/v1 required")
    query = request["query"]
    _keys(query, ("text", "tags", "roots", "domain", "max_nodes"))
    _text(query["text"], 8000); _labels(query["tags"]); _labels(query["domain"])
    for root in _items(query["roots"], MAX_NODES):
        _id(root)
    if len(query["roots"]) != len(set(query["roots"])):
        raise ValueError("unique requested roots required")
    if type(query["max_nodes"]) is not int or not 1 <= query["max_nodes"] <= MAX_NODES:
        raise ValueError("bounded positive retrieval node limit required")
    knowledge, raw = _snapshot(request["knowledge"], base)
    graph = _json(raw)
    _keys(graph, ("schema_version", "id", "sources", "nodes", "edges"))
    if type(graph["schema_version"]) is not int or graph["schema_version"] != 1:
        raise ValueError("physics knowledge source index/v1 required")
    _id(graph["id"])
    sources, inventory, texts = {}, [knowledge], {}
    for row in _items(graph["sources"], 124):
        _keys(row, ("id", "pin", "citation", "version", "format", "parents"))
        _id(row["id"]); _text(row["citation"], 2048); _text(row["version"], 500)
        _labels(row["parents"])
        if row["id"] in sources or row["format"] not in {"text", "binary"}:
            raise ValueError("unique text/binary source identities required")
        p, content = _snapshot(row["pin"], Path(knowledge["path"]).parent)
        if row["version"] == 'literature-original-custody/v1':
            if row["format"] != 'binary' or row["parents"]:
                raise ValueError('typed original literature custody is a root binary manifest')
            from . import literature_context
            literature_context.source_manifest(p, base_dir=Path(knowledge["path"]).parent)
        inventory.append(p)
        if sum(x["size"] for x in inventory) > MAX_SOURCE_BYTES:
            raise ValueError("combined knowledge corpus byte limit exceeded")
        sources[row["id"]] = {**deepcopy(row), "pin": p}
        texts[row["id"]] = content.splitlines(keepends=True) if row["format"] == "text" else None
    if len({x["path"] for x in inventory}) != len(inventory):
        raise ValueError("duplicate source file aliases are not separate knowledge evidence")
    def parent_closure(identity, visited=()):
        if identity not in sources or identity in visited:
            raise ValueError("unknown or cyclic derived source parents")
        result = {identity}
        for parent in sources[identity]["parents"]:
            result |= parent_closure(parent, (*visited, identity))
        return result
    for identity in sources:
        parent_closure(identity)
    nodes, obligations = {}, set()
    for row in _items(graph["nodes"], MAX_NODES, 1):
        _keys(row, ("id", "kind", "statement", "tags", "domain", "conventions", "applicability", "equations", "evidence", "obligations"))
        _id(row["id"]); _text(row["statement"])
        if row["id"] in nodes or row["kind"] not in {"fact", "convention", "procedure", "hypothesis"}:
            raise ValueError("unique typed knowledge nodes required")
        for key in ("tags", "domain", "conventions"):
            _labels(row[key])
        _text(row["applicability"])
        for eq in _items(row["equations"], 16):
            _keys(eq, ("expression", "unit", "basis", "domain"))
            for value in eq.values():
                _text(value, 4000)
        resolved, used = [], set()
        for ev in _items(row["evidence"], 16):
            _keys(ev, ("source", "line_start", "line_end", "excerpt_sha256", "locator"))
            source = sources.get(ev["source"])
            lines = texts.get(ev["source"])
            if source is None or lines is None:
                raise ValueError("located evidence must reference a declared text source")
            if type(ev["line_start"]) is not int or type(ev["line_end"]) is not int or not 1 <= ev["line_start"] <= ev["line_end"] <= len(lines):
                raise ValueError("exact source line range required")
            excerpt = b"".join(lines[ev["line_start"] - 1:ev["line_end"]])
            if len(excerpt) > 16000 or hashlib.sha256(excerpt).hexdigest() != ev["excerpt_sha256"]:
                raise ValueError("located evidence excerpt differs or exceeds limit")
            _text(ev["locator"], 2000)
            resolved.append({**ev, "pin": source["pin"], "citation": source["citation"], "text": excerpt.decode("utf-8")})
            used |= parent_closure(ev["source"])
        if row["kind"] != "hypothesis" and not resolved:
            raise ValueError("source assertion requires located evidence; speculative hypotheses may be unsourced")
        for obligation in _items(row["obligations"], 32):
            _keys(obligation, ("id", "description", "resource_class", "check"))
            _id(obligation["id"]); _text(obligation["description"])
            if obligation["id"] in obligations or obligation["resource_class"] not in {"pure_check", "source_inspection", "prospective_study"}:
                raise ValueError("unique obligation and explicit resource class required")
            if obligation["check"] is not None and (obligation["check"] not in CHECKS or obligation["resource_class"] != "pure_check"):
                raise ValueError("only named pure arithmetic checks may be callable")
            obligations.add(obligation["id"])
        nodes[row["id"]] = {**deepcopy(row), "source_evidence": resolved,
                            "source_ids": sorted(used)}
    edges, edge_ids = [], set()
    for edge in _items(graph["edges"], 4 * MAX_NODES):
        _keys(edge, ("id", "kind", "source", "target", "statement", "assessment"))
        _id(edge["id"]); _text(edge["statement"])
        if (edge["id"] in edge_ids or edge["kind"] not in {"requires", "contradicts", "motivates"}
            or edge["source"] not in nodes or edge["target"] not in nodes or edge["source"] == edge["target"]
            or edge["assessment"] not in {"source_assertion", "located_source_conflict", "exploratory"}):
            raise ValueError("unique located knowledge edge required")
        edges.append(deepcopy(edge)); edge_ids.add(edge["id"])
    if set(query["roots"]) - nodes.keys():
        raise ValueError("requested knowledge root absent")
    _recheck(inventory)
    return knowledge, sources, nodes, edges, inventory


def input_pins(request, base):
    """Complete graph and all source/derivation parents for ordinary explicit input binding."""
    if type(request) is dict and request.get('schema_version') == 2:
        from . import structural_models
        return structural_models.input_pins(request, base)
    _, sources, _, _, inventory = _load(request, base)
    complete = {pin['path']: pin for pin in inventory}
    for source in sources.values():
        if source['version'] == 'literature-original-custody/v1':
            from . import literature_context
            for pin in literature_context.source_manifest(source['pin'], base_dir=base):
                if pin['path'] in complete and complete[pin['path']] != pin:
                    raise ValueError('conflicting original literature identity')
                complete[pin['path']] = pin
    return [complete[path] for path in sorted(complete)]


def retrieve(request, base):
    """Find task knowledge, retaining dependencies, conflicts and the omitted census."""
    if type(request) is dict and request.get('schema_version') == 2:
        from . import structural_models
        return structural_models.retrieve(request, base)
    knowledge, sources, nodes, edges, inventory = _load(request, base)
    query = request["query"]
    words = set(re.findall(r"[\w-]+", query["text"].casefold()))
    selected = set(query["roots"])
    reasons = {identity: "explicit_root" for identity in selected}
    for identity, node in nodes.items():
        if identity in selected:
            continue
        domain_ok = not query["domain"] or set(query["domain"]).issubset(node["domain"])
        tokens = set(re.findall(r"[\w-]+", (node["id"] + " " + node["statement"]).casefold()))
        match = bool(set(query["tags"]) & set(node["tags"])) if query["tags"] else bool(words & tokens)
        if domain_ok and match:
            selected.add(identity); reasons[identity] = "task_tag_or_literal_match"
    changed = True
    while changed:
        changed = False
        for edge in edges:
            add = set()
            if edge["kind"] == "requires" and edge["source"] in selected:
                add.add(edge["target"])
            elif edge["kind"] == "contradicts" and ({edge["source"], edge["target"]} & selected):
                add.update((edge["source"], edge["target"]))
            for identity in add - selected:
                selected.add(identity); reasons[identity] = "dependency_or_conflict_closure"; changed = True
    if len(selected) > query["max_nodes"]:
        raise ValueError("retrieval limit cannot discard required knowledge/conflict closure")
    chosen = [nodes[i] for i in sorted(selected)]
    chosen_edges = [e for e in edges if e["source"] in selected and e["target"] in selected]
    premises = []
    for node in chosen:
        basis = [sources[i]["pin"] for i in node["source_ids"]]
        premises.append({"id": node["id"], "statement": node["statement"], "basis": basis})
        node["query_applicability"] = "domain_matched" if set(query["domain"]).issubset(node["domain"]) else "explicit_dependency_or_conflict_outside_query_domain"
    packet = {"schema_version": 1, "kind": "physics-knowledge-context", "request": deepcopy(request),
        "request_sha256": hashlib.sha256(_canonical(request)).hexdigest(), "knowledge": knowledge,
        "source_inventory": inventory, "nodes": chosen, "edges": chosen_edges,
        "selection": {"selected_ids": sorted(selected), "reasons": reasons,
            "omitted": [{"id": i, "reason": "not_task_selected"} for i in sorted(nodes.keys() - selected)], "dependency_complete": True},
        "premises": premises,
        "contradictions": [e for e in chosen_edges if e["kind"] == "contradicts"],
        "test_obligations": [{**o, "node_ids": [n["id"]]} for n in chosen for o in n["obligations"]],
        "claims": {"physics_verified": False, "execution_authorized": False}}
    if len(_canonical(packet)) > MAX_PACKET_BYTES:
        raise ValueError("bounded knowledge packet exceeded; narrow the task selection")
    _recheck(inventory)
    return packet


def _finite(value):
    if type(value) not in (int, float):
        raise ValueError("finite real arithmetic input required")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("finite real arithmetic input required")
    return value


def _representable(value):
    try:
        result = float(value)
    except OverflowError:
        raise ValueError("arithmetic result is not finite/nonzero representable") from None
    if not math.isfinite(result) or (value != 0 and result == 0):
        raise ValueError("arithmetic result is not finite/nonzero representable")
    return result


def check(packet, check_id, inputs, base):
    """Execute a selected named supplied-algebra check, never arbitrary source code."""
    if type(check_id) is not str or check_id not in CHECKS:
        raise ValueError("only an explicit supported named pure check may execute")
    if _canonical(retrieve(packet["request"], base)) != _canonical(packet):
        raise ValueError("knowledge packet changed or no longer binds exact source")
    if check_id not in {o["check"] for o in packet["test_obligations"] if o["resource_class"] == "pure_check"}:
        raise ValueError("pure check is not selected by this source knowledge context")
    if check_id == "coherent-amplitude-square":
        _keys(inputs, ("amplitudes", "basis", "amplitude_mass_dimension"))
        if inputs["basis"] != "same_external_helicity_colour" or type(inputs["amplitude_mass_dimension"]) is not int or inputs["amplitude_mass_dimension"] not in (0, 1):
            raise ValueError("same-state complete amplitude convention and dimension required")
        amps = []
        for a in _items(inputs["amplitudes"], 256, 1):
            _keys(a, ("real", "imag")); amps.append((Fraction(_finite(a["real"])), Fraction(_finite(a["imag"]))))
        real, imag = (sum((a[i] for a in amps), Fraction()) for i in (0, 1))
        total = real * real + imag * imag
        incoherent = sum((r*r+i*i for r,i in amps), Fraction())
        values = {"coherent_square": _representable(total), "incoherent_square": _representable(incoherent),
                  "interference": _representable(total - incoherent), "unit": "GeV^" + str(2 * inputs["amplitude_mass_dimension"]),
                  "scope": "Exact rational contraction of supplied binary values, then binary64 reporting; not an amplitude derivation."}
    elif check_id == "ordered-beam-prefactor":
        _keys(inputs, ("observable", "initial_spin_degeneracies", "initial_identical", "final_multiplicities"))
        if inputs["observable"] != "ordered_two_beam_cross_section" or type(inputs["initial_identical"]) is not bool:
            raise ValueError("ordered two-beam observable required; gas pair counting is a different quantity")
        spins = _items(inputs["initial_spin_degeneracies"], 2, 2)
        multiplicities = _items(inputs["final_multiplicities"], 32)
        if any(type(x) is not int or not 1 <= x <= 64 for x in spins + multiplicities):
            raise ValueError("positive bounded spin/final-state multiplicities required")
        spin = Fraction(1, math.prod(spins)); symmetry = Fraction(1, math.prod(math.factorial(x) for x in multiplicities))
        values = {"spin_average": _representable(spin), "final_symmetry": _representable(symmetry),
                  "initial_beam_symmetry": 1.0, "combined": _representable(spin * symmetry), "unit": "dimensionless",
                  "scope": "Complete amplitude; full labelled final phase space. Exchange diagrams are already in the supplied amplitude."}
    elif check_id == "two-body-width":
        _keys(inputs, ("parent_mass", "daughter_masses", "spin_summed_amplitude_square", "initial_spin_states", "identical_final", "unit", "basis"))
        masses = _items(inputs["daughter_masses"], 2, 2)
        M, a, b = (_finite(x) for x in [inputs["parent_mass"], *masses])
        amplitude = _finite(inputs["spin_summed_amplitude_square"])
        spins = inputs["initial_spin_states"]
        if (M <= 0 or min(a, b, amplitude) < 0 or type(spins) is not int or not 1 <= spins <= 64
            or type(inputs["identical_final"]) is not bool or (inputs["identical_final"] and a != b)
            or inputs["unit"] != "GeV" or inputs["basis"] != "complete_angle_independent_spin_sum_GeV2"):
            raise ValueError("on-shell angle-independent complete amplitude convention required")
        if M < a + b:
            raise ValueError("on-shell two-body decay below threshold")
        # Dimensionless ratios avoid M^4 overflow; no clipping of negative phase space.
        q = [1-(a+b)/M, 1+(a+b)/M, 1-(a-b)/M, 1+(a-b)/M]
        phase = math.prod(q)
        if not math.isfinite(phase) or phase < 0:
            raise ValueError("nonrepresentable on-shell phase space")
        p = _representable((M / 2) * math.sqrt(phase))
        symmetry = 0.5 if inputs["identical_final"] else 1.0
        width = (p / M) * (amplitude / M) * symmetry / (8 * math.pi * spins)
        if (M > a + b and (p == 0 or (amplitude != 0 and width == 0))) or not math.isfinite(width):
            raise ValueError("nonrepresentable nonzero phase space or width")
        values = {"momentum": p, "width": width, "unit": "GeV", "final_symmetry": symmetry,
                  "scope": "Supplied complete angle-independent spin-summed tree amplitude only; no couplings, loops or angular integrals derived."}
    else:
        raise ValueError("unsupported pure check; no check executed")
    _recheck(packet["source_inventory"])
    return {"schema_version": 1, "check": check_id, "knowledge_request_sha256": packet["request_sha256"],
            "inputs": deepcopy(inputs), "values": values, "physics_verified": False, "execution_authorized": False}
