"""Located literature preparation for existing knowledge and writing services.

Pure preparation makes no search/model call. Selected HTTPS acquisition and
PDF extraction run only through separately charged ordinary tools. Source assertions, generated
hypotheses and missing acquisitions remain different populations. PDF text is
produced by an explicit ordinary charged tool; its text census is not visual,
OCR, equation, table or scientific verification. No second research journal.
"""
from __future__ import annotations

from contextlib import closing
from contextvars import ContextVar
from copy import deepcopy
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import socket
import ssl
import time
from urllib.parse import urlsplit, parse_qsl

from . import physics_knowledge as knowledge

MAX_INPUT_BYTES = 64 * 1024 * 1024  # Existing ordinary research artifact bound.
MAX_JSON_BYTES = knowledge.MAX_DOCUMENT_BYTES
MAX_UNITS = 4096
SOURCE_VERSION = "literature-original-custody/v1"
FLAGS = {"physics_verified": False, "execution_authorized": False,
         "source_reading_claimed": False, "visual_completeness_claimed": False}


def _keys(value, fields):
    knowledge._keys(value, fields)


def _integer(value, maximum, minimum=1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("finite declared literature population/budget required")
    return value


def _path(path, base):
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("literature paths cannot traverse parents")
    path = (path if path.is_absolute() else Path(base) / path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("literature sources and outputs cannot traverse symlinks")
    if path.resolve(strict=False) != path:
        raise ValueError("canonical literature path required")
    return path


def _raw(value):
    return knowledge._canonical(value) + b"\n"


def _pin(path, raw):
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


class _Reader:
    """Descriptor observations retained to the ending, including file identity."""
    def __init__(self, base):
        self.base, self.observed = _path(base, Path.cwd()), {}

    def read(self, pin, maximum=MAX_INPUT_BYTES):
        _keys(pin, ("path", "sha256", "size"))
        _integer(pin["size"], maximum, 0)
        if type(pin["sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"]):
            raise ValueError("exact literature source SHA256 required")
        path = _path(pin["path"], self.base)
        # The identity is retained to the ending: observe it once the stamping clock has passed the change time.
        from .validation_io import settled
        initial = settled(path.lstat)
        if not stat.S_ISREG(initial.st_mode) or initial.st_size != pin["size"]:
            raise ValueError("bounded ordinary literature source required")
        with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read(pin["size"] + 1)
            after = os.fstat(stream.fileno())
        identity = knowledge._identity(initial)
        if not (identity == knowledge._identity(before) == knowledge._identity(after)
                == knowledge._identity(path.lstat())):
            raise ValueError("literature source identity changed while reading")
        actual = _pin(path, raw)
        if len(raw) != pin["size"] or actual["sha256"] != pin["sha256"]:
            raise ValueError("literature source differs from retained bytes")
        old = self.observed.get(str(path))
        if old is not None and old != (actual, identity):
            raise ValueError("literature source changed within one preparation")
        self.observed[str(path)] = (actual, identity)
        return actual, raw

    def document(self, pin):
        actual, raw = self.read(pin, MAX_JSON_BYTES)
        return actual, knowledge._json(raw)

    def finish(self, *, readers=(), populations=()):
        """Linear closing observations after ALL participating readers' rereads.

        This is a bounded sequential custody check, not an atomic filesystem
        snapshot or a promise that a source cannot change after return.
        """
        participants = (self, *readers)
        if len({id(reader) for reader in participants}) != len(participants):
            raise ValueError("distinct ending literature readers required")
        snapshots = [(reader, list(reader.observed.values())) for reader in participants]
        for reader, rows in snapshots:
            for pin, identity in rows:
                reader.read(pin)
        # Earlier leaves can change during the final later read. Close every
        # remembered canonical path/identity only after the entire read phase.
        for reader, rows in snapshots:
            if list(reader.observed.values()) != rows:
                raise ValueError("literature ending source population changed")
            for pin, identity in rows:
                path = _path(pin["path"], reader.base)
                if knowledge._identity(path.lstat()) != identity:
                    raise ValueError("literature source ending identity differs")
        for root, pins in populations:
            _population(root, pins)

    def pins(self):
        return [deepcopy(row[0]) for _, row in sorted(self.observed.items())]


def _emit(path, raw, reader):
    """Bind known intended bytes before writing, never a first-reread baseline."""
    expected = _pin(path, raw)
    with path.open("xb") as stream:
        stream.write(raw)
    reader.read(expected)
    return expected


def _producer_sources(reader):
    """Bind both this producer and its actual reused knowledge codec/kernel."""
    helper, _ = reader.read(_pin(Path(__file__).absolute(), Path(__file__).read_bytes()), MAX_JSON_BYTES)
    reader.read(_pin(Path(knowledge.__file__).absolute(), Path(knowledge.__file__).read_bytes()), MAX_JSON_BYTES)
    return helper


def _population(root, pins):
    wanted = {_path(pin["path"], root) for pin in pins}
    if any(p.parent != root for p in wanted):
        raise ValueError("flat owned literature output population required")
    actual = set()
    for path in root.iterdir():
        path = _path(path, root)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("ordinary complete generated literature population required")
        actual.add(path)
    if actual != wanted:
        raise ValueError("generated literature membership changed")


# An active verification frame is not accepted/cached campaign evidence. It
# exists only while the unchanged full campaign loader validates its sources.
_SCOPE_VERIFICATION = ContextVar("literature_scope_verification", default=())


def _scope_journal(root, authority, cycle):
    """Authenticate one bounded current journal before following knowledge edges.

    Dynamic journal pins belong to this local authority reader, never to an
    immutable original-literature input census. Adding legitimate knowledge is
    a journal revision, not a change to the original source/contract assignment.
    """
    head_pin, head = authority.document(cycle._pin(root / "head.json"))
    current_pin, raw = authority.read(head, cycle.ce.MAX_BYTES)
    current = knowledge._json(raw)
    revision = _integer(current["revision"], cycle.MAX_REVISIONS - 1, 0)
    previous = None
    for index in range(revision + 1):
        path = root / "history" / f"{index:04d}.json"
        _, raw = authority.read(cycle._pin(path), cycle.ce.MAX_BYTES)
        record = knowledge._json(raw)
        content = deepcopy(record)
        checksum = content.pop("sha256")
        if checksum != cycle.ce.digest(content) or record["revision"] != index:
            raise ValueError("research history content differs")
        if index and record["parent_sha256"] != previous["sha256"]:
            raise ValueError("research ancestry differs")
        previous = record
    if previous != current:
        raise ValueError("research head differs from immutable history")
    return head_pin, current_pin, current


def _scope_projection(root, value, state, cycle, authority):
    if value["contract_sha256"] != cycle.ce.digest(state["contract"]):
        raise ValueError("literature belongs to a different original research contract")
    frame = _SCOPE_VERIFICATION.get()[-1]
    phase = frame["phase"]
    frame["phase"] = "parent"
    try:
        parent = cycle._parent_goal(state)
        if parent is not None:
            for pin in parent["input_pins"]:
                authority.read(pin)
    finally:
        frame["phase"] = phase
    return {"root": str(root), "contract_sha256": value["contract_sha256"],
            "question": state["contract"]["question"], "scope": state["contract"]["scope"],
            "budget": deepcopy(state["contract"]["budget"]),
            "goal_binding": deepcopy(state["contract"].get("goal_binding")),
            "parent_task": deepcopy(parent)}


def _scope(value, reader):
    if value is None:
        return None
    _keys(value, ("root", "contract_sha256"))
    from . import research_cycle as cycle
    root = _path(value["root"], reader.base)
    stack = _SCOPE_VERIFICATION.get()
    prior = next((frame for frame in stack if frame["root"] == root), None)
    if prior is not None:
        # Only the immediate same-campaign source-reference backedge is valid.
        # Parent/source cycles and A -> B -> A dependencies cannot borrow an
        # earlier frame's reference projection or a recursive acceptance flag.
        if prior is not stack[-1] or prior["phase"] != "knowledge":
            raise ValueError("cyclic literature campaign/parent assignment reference")
        authority = prior["authority"]
        _, raw_head = authority.document(prior["head_pin"])
        _, raw_current = authority.read(prior["current_pin"], cycle.ce.MAX_BYTES)
        if raw_head != prior["current_pin"] or knowledge._json(raw_current) != prior["state"]:
            raise ValueError("literature campaign authority changed during verification")
        projection = _scope_projection(root, value, prior["state"], cycle, authority)
        if projection != prior["projection"]:
            raise ValueError("literature current parent assignment changed")
        return deepcopy(projection)
    if len(stack) >= cycle.MAX_REVISIONS:
        raise ValueError("finite literature campaign reference depth exceeded")
    authority = _Reader(root)
    head_pin, current_pin, snapshot = _scope_journal(root, authority, cycle)
    frame = {"root": root, "authority": authority, "head_pin": head_pin,
             "current_pin": current_pin, "state": snapshot, "phase": "parent"}
    token = _SCOPE_VERIFICATION.set((*stack, frame))
    try:
        projection = _scope_projection(root, value, snapshot, cycle, authority)
        frame.update(phase="knowledge", projection=projection)
        # FULL original context, premise, adaptation, knowledge and parent
        # validation remains mandatory. Nothing here grants campaign acceptance.
        _, state = cycle._load(root)
        if state != snapshot or _scope_projection(root, value, state, cycle, authority) != projection:
            raise ValueError("literature campaign authority changed during verification")
        authority.finish()
        return deepcopy(projection)
    finally:
        _SCOPE_VERIFICATION.reset(token)


def _request(value):
    _keys(value, ("schema_version", "kind", "id", "cycle_binding", "documents",
                  "query", "annotations", "hypotheses", "edges", "acquisition_tasks"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "literature-context-request":
        raise ValueError("literature-context-request/v1 required")
    knowledge._id(value["id"])
    _keys(value["query"], ("text", "tags", "roots", "domain", "max_nodes"))
    knowledge._text(value["query"]["text"])
    for name in ("tags", "domain"):
        knowledge._labels(value["query"][name])
    roots = knowledge._items(value["query"]["roots"], knowledge.MAX_NODES)
    for identity in roots:
        knowledge._id(identity)
    if len(roots) != len(set(roots)):
        raise ValueError("unique literature retrieval roots required")
    _integer(value["query"]["max_nodes"], knowledge.MAX_NODES)
    seen = set()
    for row in knowledge._items(value["documents"], 32):
        _keys(row, ("id", "pin", "citation", "version", "license", "access", "format",
                    "status", "reason", "parents", "extraction", "acquisition", "tags", "domain", "conventions", "task_ids"))
        knowledge._id(row["id"])
        if len(row["id"]) > 64:
            raise ValueError("document ID must leave room for stable unit identities")
        if row["id"] in seen:
            raise ValueError("unique original document identities required")
        seen.add(row["id"])
        for name in ("citation", "version", "license", "access"):
            knowledge._text(row[name], 2048)
        for name in ("parents", "tags", "domain", "conventions", "task_ids"):
            knowledge._labels(row[name])
        if row["format"] not in {"html", "tex", "text", "markdown", "pdf"}:
            raise ValueError("explicit supported source format required")
        if row["status"] not in {"supplied", "missing", "failed", "unsupported"}:
            raise ValueError("explicit acquisition outcome required")
        if row["status"] != "supplied":
            if row["pin"] is not None or row["extraction"] is not None:
                raise ValueError("unacquired source cannot carry fabricated bytes/extraction")
            knowledge._text(row["reason"])
        elif row["reason"] is not None or row["pin"] is None:
            raise ValueError("supplied original source and no failure reason required")
        if row["format"] != "pdf" and row["extraction"] is not None:
            raise ValueError("text parsing does not accept a caller-authored extraction")
    def parents(identity, trail=()):
        if identity not in seen or identity in trail:
            raise ValueError("unknown/cyclic original document parents")
        row = next(r for r in value["documents"] if r["id"] == identity)
        for parent in row["parents"]:
            parents(parent, (*trail, identity))
    for identity in seen:
        parents(identity)
    knowledge._items(value["annotations"], knowledge.MAX_NODES)
    knowledge._items(value["hypotheses"], knowledge.MAX_NODES)
    knowledge._items(value["edges"], 4 * knowledge.MAX_NODES)
    # The authenticated scout caller owns its phase receipt. Here the exact
    # original task rows and links survive preparation, including tasks with
    # no acquired source; these are requests, not completed acquisitions.
    tasks = knowledge._items(value['acquisition_tasks'], 128)
    task_ids = set()
    for task in tasks:
        _keys(task, ('obligation_id','query','source_scope','claim_ids','failure_or_missing'))
        knowledge._id(task['obligation_id']); knowledge._text(task['query'])
        if task['obligation_id'] in task_ids:
            raise ValueError('whole distinct acquisition task population required')
        task_ids.add(task['obligation_id'])
        knowledge._labels(task['claim_ids'])
        for field in ('source_scope','failure_or_missing'):
            knowledge._text(task[field])
        # Source scope/missingness are finite scout schema values, never code.
        if len(_raw(task)) > 16000:
            raise ValueError('bounded complete acquisition task required')
    if any(set(doc['task_ids']) - task_ids for doc in value['documents']):
        raise ValueError('document links an unknown original acquisition task')
    return deepcopy(value)


class _HTML(HTMLParser):
    """Exact source intervals, retaining unmatched markup as unresolved."""
    TAGS = {"article", "section", "p", "table", "caption", "figure", "figcaption", "math",
            "h1", "h2", "h3", "h4", "h5", "h6", "img"}
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text, self.rows, self.stack, self.errors = text, [], [], []
        self.starts = [0]
        self.starts.extend(m.end() for m in re.finditer("\n", text))

    def _source_offset(self):
        line, column = self.getpos()
        return self.starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag not in self.TAGS:
            return
        start = self._source_offset()
        row = {"tag": tag, "start": start, "end": start + len(self.get_starttag_text()),
               "parent_index": self.stack[-1] if self.stack else None}
        self.rows.append(row)
        if tag != "img":
            self.stack.append(len(self.rows) - 1)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.rows[self.stack[-1]]["start"] == self._source_offset():
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag not in self.TAGS:
            return
        if not self.stack or self.rows[self.stack[-1]]["tag"] != tag:
            self.errors.append({"offset": self._source_offset(), "reason": "unmatched structural HTML end tag", "tag": tag})
            return
        row = self.rows[self.stack.pop()]
        row["end"] = self.text.index(">", self._source_offset()) + 1

    def forest(self):
        self.feed(self.text); self.close()
        for i in self.stack:
            self.errors.append({"offset": self.rows[i]["start"], "reason": "unclosed structural HTML element", "tag": self.rows[i]["tag"]})
            self.rows[i]["end"] = len(self.text)
        return self.rows, self.errors


def _forest(identity, text, format):
    """All original characters survive in located intervals; no layout claim."""
    rows, unknowns = [], []
    if format == "html":
        rows, unknowns = _HTML(text).forest()
    else:
        starts = [0] + [m.end() for m in re.finditer("\n", text)]
        lines = text.splitlines(keepends=True)
        sections = []
        i = 0
        while i < len(lines):
            line = lines[i]
            heading = re.match(r"^(#{1,6})\s+", line) if format == "markdown" else None
            tex = re.match(r"\s*\\(section|subsection|subsubsection|chapter)\*?\{", line) if format == "tex" else None
            if heading or tex:
                level = len(heading[1]) if heading else {"chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}[tex[1]]
                while sections and sections[-1][0] >= level:
                    rows[sections.pop()[1]]["end"] = starts[i]
                rows.append({"tag": "section", "start": starts[i], "end": len(text),
                             "parent_index": sections[-1][1] if sections else None})
                sections.append((level, len(rows) - 1))
                # The heading itself remains an exact source fragment.
                rows.append({"tag": "heading", "start": starts[i], "end": starts[i] + len(line), "parent_index": sections[-1][1]})
                i += 1
                continue
            end = i + 1
            env = re.search(r"\\begin\{(equation\*?|align\*?|table\*?|figure\*?)\}", line) if format == "tex" else None
            kind = "paragraph"
            if env:
                kind = "equation" if env[1].startswith(("equation", "align")) else ("table" if env[1].startswith("table") else "figure")
                while end < len(lines) and ("\\end{" + env[1] + "}") not in "".join(lines[i:end]):
                    end += 1
                if ("\\end{" + env[1] + "}") not in "".join(lines[i:end]):
                    unknowns.append({"offset": starts[i], "reason": "unclosed TeX environment", "tag": env[1]})
            elif line.strip().startswith("$$"):
                kind = "equation"
                while end < len(lines) and "".join(lines[i:end]).count("$$") < 2:
                    end += 1
                if "".join(lines[i:end]).count("$$") < 2:
                    unknowns.append({"offset": starts[i], "reason": "unclosed display equation", "tag": "$$"})
            elif "|" in line and format == "markdown":
                kind = "table"
                while end < len(lines) and "|" in lines[end]:
                    end += 1
            elif re.match(r"\s*(Figure|Table|Fig\.)\s+\S", line) or "\\caption" in line:
                kind = "caption"
            elif not line.strip():
                kind = "source-fragment"
            else:
                while end < len(lines) and lines[end].strip() and not re.match(r"^(#|\\(?:sub)*section|\\begin|\$\$|Figure\s|Table\s)", lines[end]):
                    end += 1
            rows.append({"tag": kind, "start": starts[i], "end": starts[end] if end < len(starts) else len(text),
                         "parent_index": sections[-1][1] if sections else None})
            # Caption children of source-native TeX table/figure containers.
            if env:
                parent = len(rows) - 1
                for j in range(i, end):
                    if "\\caption" in lines[j]:
                        rows.append({"tag": "caption", "start": starts[j], "end": starts[j] + len(lines[j]), "parent_index": parent})
            i = end
    root = {"id": identity + ".root", "parent": None, "kind": "document", "start": 0, "end": len(text)}
    units = [root]
    for i, row in enumerate(rows):
        kind = row["tag"]
        kind = "section" if kind in {"article", "section", "h1", "h2", "h3", "h4", "h5", "h6"} else (
            "caption" if kind in {"caption", "figcaption"} else "equation" if kind == "math" else "figure" if kind == "img" else kind)
        units.append({"id": identity + ".u" + str(i), "parent": identity + ".u" + str(row["parent_index"]) if row["parent_index"] is not None else root["id"],
                      "kind": kind, "start": row["start"], "end": row["end"]})
    # Root-level gaps preserve front matter, unsupported markup and whitespace.
    covered = sorted((u["start"], u["end"]) for u in units[1:] if u["parent"] == root["id"])
    cursor = 0
    for first, last in covered + [(len(text), len(text))]:
        if first > cursor:
            units.append({"id": identity + ".gap" + str(cursor), "parent": root["id"], "kind": "source-fragment", "start": cursor, "end": first})
        cursor = max(cursor, last)
    # Material not inside a child survives as its own evidence-bearing leaf.
    for unit in list(units[1:]):
        children = sorted((u["start"], u["end"]) for u in units if u["parent"] == unit["id"])
        if not children:
            continue
        cursor = unit["start"]
        for first, last in children + [(unit["end"], unit["end"])]:
            if first > cursor:
                units.append({"id": unit["id"] + ".part" + str(cursor), "parent": unit["id"], "kind": "source-fragment", "start": cursor, "end": first})
            cursor = max(cursor, last)
    for unit in units:
        piece = text[unit["start"]:unit["end"]]
        unit.update(document=identity, byte_start=len(text[:unit["start"]].encode()), byte_end=len(text[:unit["end"]].encode()),
                    excerpt_sha256=hashlib.sha256(piece.encode()).hexdigest(),
                    line_start=text.count("\n", 0, unit["start"]) + 1,
                    line_end=text.count("\n", 0, max(unit["start"], unit["end"] - 1)) + 1,
                    text=piece)
    if len(units) > MAX_UNITS:
        raise ValueError("complete source unit forest exceeds declared finite population")
    return units, unknowns


def _assertions(units, doc, source, texts, annotations):
    parents = {u["parent"] for u in units}
    nodes = []
    for unit in units:
        if unit["id"] in parents or not unit["text"].strip():
            continue
        # Whole exact fragments are split under the existing node bound, never truncated.
        remaining, offset, number = unit["text"], 0, 0
        while remaining:
            count = min(2000, len(remaining))
            fragment, remaining = remaining[:count], remaining[count:]
            if not fragment.strip():
                offset += count; number += 1
                continue
            node_id = unit["id"] + ".n" + str(number)
            first = len(texts.splitlines()) + 1
            excerpt = fragment.encode() + (b"" if fragment.endswith("\n") else b"\n")
            texts += excerpt.decode()
            last = len(texts.splitlines())
            annotation = annotations.pop(node_id, None)
            extras = {"kind": "fact", "tags": doc["tags"], "domain": doc["domain"], "conventions": doc["conventions"],
                      "applicability": "Located source assertion only; source wording is not verified physics or model reading.", "equations": [], "obligations": []}
            if annotation is not None:
                _keys(annotation, ("id", *extras.keys()))
                if annotation["kind"] not in {"fact", "convention", "procedure"}:
                    raise ValueError("generated summaries belong in hypotheses, not assertion annotations")
                extras.update({k: deepcopy(annotation[k]) for k in extras})
                for equation in extras['equations']:
                    if type(equation) is not dict or equation.get('expression') not in fragment:
                        raise ValueError('source assertion equation must occur in its exact located fragment; generated equations are hypotheses')
            nodes.append({"id": node_id, "statement": fragment.strip() or fragment, **extras,
                          "evidence": [{"source": source, "line_start": first, "line_end": last,
                                        "excerpt_sha256": hashlib.sha256(excerpt).hexdigest(),
                                        "locator": doc["id"] + ":" + unit["id"] + ":" + unit.get('original_location','original text') + ":UTF8 bytes " + str(unit["byte_start"] + len(unit["text"][:offset].encode())) + ".." + str(unit["byte_start"] + len(unit["text"][:offset + count].encode()))}]})
            unit.setdefault("node_ids", []).append(node_id)
            offset += count; number += 1
    return nodes, texts


def _compile(request_pin, reader, out):
    original_pin, value = reader.document(request_pin)
    request = _request(value)
    assignment = _scope(request["cycle_binding"], reader)
    documents, units, failures, sources, nodes, files = [], [], [], [], [], {}
    annotations = {}
    for row in request["annotations"]:
        if type(row) is not dict or row.get("id") in annotations:
            raise ValueError("unique located source annotation IDs required")
        annotations[row.get("id")] = deepcopy(row)
    originals = []
    for row in request["documents"]:
        doc = deepcopy(row)
        documents.append(doc)
        if doc['acquisition'] is not None:
            acquisition = consume_acquisition(doc['acquisition'], base_dir=reader.base, _reader=reader)
            if (doc['format'] != acquisition['request_value']['format']
                    or doc['task_ids'] != [t['obligation_id'] for t in acquisition['request_value']['tasks']]
                    or any(t not in request['acquisition_tasks'] for t in acquisition['request_value']['tasks'])):
                raise ValueError('acquired document differs from exact original scout task/format population')
            if doc['status'] == 'supplied':
                if acquisition['status'] != 'acquired' or doc['pin'] != acquisition['source_artifact']:
                    raise ValueError('supplied source is not the actual complete acquired response')
            elif doc['status'] != 'failed' or acquisition['status'] != 'failed':
                raise ValueError('actual failed acquisition must remain failed, not missing or supplied')
            doc['acquisition_outcome'] = acquisition
        if doc["status"] != "supplied":
            failures.append({"document": doc["id"], "kind": "acquisition", "status": doc["status"], "reason": doc["reason"],
                             "next_action": "separately configured charged acquisition; no source bytes available"})
            continue
        doc["pin"], raw = reader.read(doc["pin"])
        if any(p['path'] == doc['pin']['path'] or p['sha256'] == doc['pin']['sha256'] for p in originals):
            raise ValueError('original source aliases are not independent literature evidence')
        originals.append(doc["pin"])
        if sum(p["size"] for p in originals) > 256 * 1024 * 1024:
            raise ValueError("complete original literature corpus exceeds prospective 256MiB input policy")
        if doc["format"] == "pdf":
            if not raw.startswith(b"%PDF-"):
                raise ValueError("actual original PDF signature required")
            if doc["extraction"] is None:
                failures.append({"document": doc["id"], "kind": "extraction", "status": "missing", "reason": "original PDF retained; no ordinary extraction result",
                                 "next_action": "literature-pdf; request source=" + doc["pin"]["path"]})
                continue
            extracted = consume_pdf(doc["extraction"], base_dir=reader.base, _reader=reader)
            if extracted["source"] != doc["pin"]:
                raise ValueError("PDF extraction belongs to another original")
            if extracted["failure"] is not None:
                failures.append({"document": doc["id"], "kind": "extraction", "status": "failed",
                                 "reason": extracted["failure"], "reported_page_count": extracted["page_count"],
                                 "next_action": "retain failed source-bound extraction; replan within original resources"})
                continue
            forest = [{"id": doc["id"] + ".root", "parent": None, "kind": "document", "document": doc["id"],
                       "start": 0, "end": 0, "byte_start": 0, "byte_end": 0, "excerpt_sha256": hashlib.sha256(b"").hexdigest(),
                       "line_start": None, "line_end": None, "text": "", "original_location": "Complete original PDF; page children locate extracted text separately"}]
            for page in extracted["pages"]:
                identity = doc["id"] + ".page" + str(page["page_index"])
                page_units, unknown = _forest(identity, page["text"], "text")
                for unit in page_units:
                    unit["document"] = doc["id"]; unit["page_index"] = page["page_index"]
                    if unit["parent"] is None:
                        unit["parent"] = doc["id"] + ".root"; unit["kind"] = "page"
                    unit["original_location"] = "PDF page " + str(page["page_index"] + 1) + "; extracted-text offsets only"
                forest.extend(page_units)
                failures.extend({"document": doc["id"], "kind": "parse", **u} for u in unknown)
                failures.extend({"document": doc["id"], "page_index": page["page_index"], "kind": k, "status": "unresolved",
                                 "reason": "text extraction does not establish " + k, "next_action": "existing configured visual_sources original PDF review or source-bound structured extraction"}
                                for k in ("visual", "structured_tables_equations", "ocr"))
                if page["status"] != "extracted":
                    failures.append({"document": doc["id"], "page_index": page["page_index"], "kind": "text", "status": page["status"], "reason": page["reason"], "next_action": "source-bound OCR/visual inspection; do not invent text"})
        else:
            raw.decode("utf-8")  # No lossy decode, silently discarded bytes or guessed encoding.
            forest, unknown = _forest(doc["id"], raw.decode("utf-8"), doc["format"])
            failures.extend({"document": doc["id"], "kind": "parse", "status": "unresolved", **u} for u in unknown)
            failures.extend({'document':doc['id'],'unit':u['id'],'kind':u['kind'],'status':'unresolved',
                             'reason':'located lexical interval only; visual or structured semantic extraction is unverified',
                             'next_action':'source-bound native visual or structured extraction; do not infer a measured quantity'}
                            for u in forest if u['kind'] in {'figure','table','equation'})
        source_id = doc["id"] + ".located"
        assertions, text = _assertions(forest, doc, source_id, "", annotations)
        if text:
            data = text.encode(); knowledge._text(text, MAX_JSON_BYTES)
            files[doc["id"] + ".txt"] = data
            sources.append({"id": source_id, "pin": _pin(out / (doc["id"] + ".txt"), data),
                            "citation": doc["citation"], "version": doc["version"], "format": "text", "parents": ["literature.originals"]})
        nodes.extend(assertions); units.extend(forest)
    if annotations:
        raise ValueError("source annotations refer to absent located assertion IDs")
    for hypothesis in request["hypotheses"]:
        _keys(hypothesis, ("id", "statement", "tags", "domain", "conventions", "applicability", "equations", "obligations"))
        nodes.append({**deepcopy(hypothesis), "kind": "hypothesis", "evidence": []})
    linked = {identity for doc in documents for identity in doc['task_ids']}
    failures.extend({'document':None,'kind':'acquisition','status':'unresolved',
                     'task':deepcopy(task),'reason':'no supplied or failed source outcome linked to this original scout task',
                     'next_action':'separately configured charged acquisition; retain original obligation'}
                    for task in request['acquisition_tasks'] if task['obligation_id'] not in linked)
    if len(units) > MAX_UNITS or len(nodes) > knowledge.MAX_NODES:
        raise ValueError("complete literature population exceeds existing knowledge limits; no dropping units/nodes")
    # All typed original sources, failed acquisitions and extraction records stay
    # in this small custody manifest. Its special consumer rechecks large PDFs.
    helper = _producer_sources(reader)
    custody = {"schema_version": 1, "kind": SOURCE_VERSION, "request": original_pin,
               "documents": documents, "input_pins": reader.pins(), "helper": helper}
    files["original-custody.json"] = _raw(custody)
    sources.insert(0, {"id": "literature.originals", "pin": _pin(out / "original-custody.json", files["original-custody.json"]),
                       "citation": "Complete original literature acquisition/extraction/source custody", "version": SOURCE_VERSION, "format": "binary", "parents": []})
    knowledge_request = None
    if nodes:
        index = {"schema_version": 1, "id": request["id"], "sources": sources, "nodes": nodes, "edges": request["edges"]}
        files["knowledge.json"] = _raw(index)
        knowledge_request = {"schema_version": 1, "knowledge": _pin(out / "knowledge.json", files["knowledge.json"]), "query": request["query"]}
        files["knowledge-request.json"] = _raw(knowledge_request)
    elif request["edges"] or request["query"]["roots"]:
        raise ValueError("requested knowledge roots/edges absent; missing sources cannot create a dummy fact")
    context = {"schema_version": 1, "kind": "located-literature-context", "assignment": assignment,
               "request": original_pin, "documents": documents, "units": units,
               "source_assertions": [n for n in nodes if n["kind"] != "hypothesis"],
               "hypotheses": [n for n in nodes if n["kind"] == "hypothesis"], "edges": request["edges"],
               "acquisition_tasks": deepcopy(request['acquisition_tasks']),
               "annotation_provenance": "Caller-authored tags/conventions/applicability are explicit annotations; only unchanged located wording/equations are source assertions.",
               "missing_and_unresolved": failures, "extraction_status": "partial_or_unresolved" if failures else "complete_supported_text_intervals",
               "knowledge_request": _pin(out / "knowledge-request.json", files["knowledge-request.json"]) if knowledge_request else None,
               "input_pins": reader.pins(), "claims": deepcopy(FLAGS),
               "reading": "Located bytes/census only; actual cited excerpts/pages must be presented in the consuming role context."}
    files["request.json"] = _raw(request)
    product = {"schema_version": 1, "kind": "located-literature-product", "context": context,
               "generated": [_pin(out / name, raw) for name, raw in sorted(files.items())],
               "producer": custody["helper"]}
    files["product.json"] = _raw(product)
    if any(len(raw) > MAX_JSON_BYTES for raw in files.values()):
        raise ValueError("complete literature output exceeds existing document bound; no truncation")
    return product, files


def prepare(request_pin, out, *, base_dir):
    """Pure source preparation, permitting known evidence plus explicit missingness."""
    reader = _Reader(base_dir); out = _path(out, reader.base)
    product, files = _compile(request_pin, reader, out)
    if out.exists():
        raise ValueError("fresh literature output directory required")
    out.mkdir(parents=True)
    emitted = [_emit(out / name, raw, reader) for name, raw in files.items()]
    request = product["context"]["knowledge_request"]
    if request is not None:
        knowledge.retrieve(knowledge._json(files["knowledge-request.json"]), out)
    _population(out, emitted); reader.finish(populations=((out, emitted),))
    if _scope(knowledge._json(files["request.json"])["cycle_binding"], reader) != product['context']['assignment']:
        raise ValueError('original literature assignment changed during preparation')
    return {"product": _pin(out / "product.json", files["product.json"]),
            "knowledge_request": deepcopy(request), "context": deepcopy(product["context"])}


def consume(product_pin, *, base_dir, _reader=None):
    """Recompute the whole source forest and intended outputs; no recaptured baseline."""
    reader = _reader or _Reader(base_dir)
    pin, actual = reader.document(product_pin)
    _keys(actual, ("schema_version", "kind", "context", "generated", "producer"))
    if actual["kind"] != "located-literature-product" or actual["schema_version"] != 1:
        raise ValueError("current located literature product required")
    out = Path(pin["path"]).parent
    inputs = _Reader(base_dir)
    expected, files = _compile(actual["context"]["request"], inputs, out)
    if actual != expected or pin != _pin(out / "product.json", files["product.json"]):
        raise ValueError("literature product differs from its complete current source derivation")
    emitted = [_pin(out / name, raw) for name, raw in files.items()]
    for p in emitted:
        reader.read(p, MAX_JSON_BYTES)
    if expected["context"]["knowledge_request"]:
        knowledge.retrieve(knowledge._json(files["knowledge-request.json"]), out)
    _population(out, emitted); inputs.finish(readers=(reader,), populations=((out, emitted),))
    if _scope(knowledge._json(files['request.json'])['cycle_binding'], inputs) != expected['context']['assignment']:
        raise ValueError('original literature assignment changed during consumption')
    return {"product": pin, "knowledge_request": deepcopy(expected["context"]["knowledge_request"]),
            "context": deepcopy(expected["context"])}


def source_manifest(pin, *, base_dir):
    """Only the closed producer-owned custody kind extends source authentication.

    Ordinary knowledge JSON/member/packet bounds stay unchanged. Original PDF
    bytes are rechecked under the existing research artifact bound, not counted
    as presented text. The returned closure is used by ordinary Graph admission.
    """
    reader = _Reader(base_dir)
    _, value = reader.document(pin)
    _keys(value, ("schema_version", "kind", "request", "documents", "input_pins", "helper"))
    if value["kind"] != SOURCE_VERSION or value["schema_version"] != 1:
        raise ValueError("closed literature original custody/v1 required")
    helper, _ = reader.read(value["helper"], MAX_JSON_BYTES)
    if helper["path"] != str(Path(__file__).absolute()):
        raise ValueError("foreign literature custody producer")
    # Recompute the exact original dependency census, not a caller replacement.
    proof_reader = _Reader(base_dir)
    expected, files = _compile(value["request"], proof_reader, Path(pin["path"]).parent)
    if value != knowledge._json(files["original-custody.json"]):
        raise ValueError("original literature custody/parents/extraction population differs")
    emitted = [_pin(Path(pin["path"]).parent / name, raw) for name, raw in files.items()]
    for generated in emitted:
        proof_reader.read(generated, MAX_JSON_BYTES)
    _population(Path(pin["path"]).parent, emitted)
    reader.finish(readers=(proof_reader,), populations=((Path(pin["path"]).parent, emitted),))
    if _scope(knowledge._json(files['request.json'])['cycle_binding'], proof_reader) != expected['context']['assignment']:
        raise ValueError('original literature assignment changed during source custody verification')
    return proof_reader.pins()


def _pdf_request(request_pin, reader):
    pin, value = reader.document(request_pin)
    _keys(value, ("schema_version", "kind", "source", "max_pages", "max_text_bytes", "max_seconds"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "literature-pdf-extraction":
        raise ValueError("literature-pdf-extraction/v1 required")
    _integer(value["max_pages"], 1024)
    _integer(value["max_text_bytes"], MAX_JSON_BYTES)
    _integer(value["max_seconds"], 3600)
    source, raw = reader.read(value["source"])
    if not raw.startswith(b"%PDF-"):
        raise ValueError("actual source-bound original PDF required")
    return pin, {**value, "source": source}, raw


def pdf_inputs(request_pin, *, base_dir):
    reader = _Reader(base_dir)
    _pdf_request(request_pin, reader)
    _producer_sources(reader)
    reader.finish()
    return reader.pins()


def extract_pdf(request_pin, out, *, base_dir):
    """Actual PDFium text extraction; invoke only in the ordinary bounded tool.

    Native calls are bounded between pages, not hard C-call preempted. Existing
    Graph/campaign and outer supervisor retain wall/RAM ownership. All pages
    survive native failures; images and structured equations/tables remain
    unknown until actual existing visual/source-parse services observe them.
    """
    from . import visual_presentation as visual
    reader = _Reader(base_dir)
    request, settings, raw = _pdf_request(request_pin, reader)
    out = _path(out, reader.base)
    if out.exists():
        raise ValueError("fresh PDF extraction output required")
    out.mkdir(parents=True)
    started = time.monotonic()
    pages, count, failure, used = [], None, None, 0
    with visual._PDFIUM_LOCK:
        runtime = visual._runtime(True)
        import pypdfium2 as pdfium
        import pypdfium2_raw as raw_api
        from PIL import Image
        known = {p["path"] for p in runtime["files"]}
        if str(Path(pdfium.__file__).absolute()) not in known or str(Path(Image.__file__).absolute()) not in known:
            raise ValueError("actual PDF extraction loaded origins differ from required renderer census")
        native_flags = knowledge._json((Path(raw_api.__file__).parent / "version.json").read_bytes())["flags"]
        if "V8" in native_flags or "XFA" in native_flags:
            raise ValueError("PDF extraction requires the existing non-JavaScript non-XFA build")
        runtime["loaded_origins"] = visual._loaded_origins(True, runtime)
        try:
            with closing(pdfium.PdfDocument(raw)) as document:
                count = len(document)
                _integer(count, settings["max_pages"])
                for i in range(count):
                    row = {"page_index": i, "text": "", "status": "failed", "reason": None,
                           "visual_status": "unobserved", "ocr_status": "not_performed", "structured_math_tables": "unverified"}
                    try:
                        if time.monotonic() - started > settings["max_seconds"]:
                            raise ValueError("original extraction wall allowance exhausted before page")
                        with closing(document[i]) as page:
                            with closing(page.get_textpage()) as textpage:
                                text = textpage.get_text_range()
                        if time.monotonic() - started > settings['max_seconds']:
                            raise ValueError('original extraction wall allowance exhausted during page; native call was not preempted')
                        size = len(text.encode("utf-8"))
                        if used + size > settings["max_text_bytes"]:
                            raise ValueError("full page text exceeds declared extraction byte budget")
                        used += size
                        row.update(text=text, status="extracted" if text.strip() else "empty_text",
                                   reason=None if text.strip() else "no extracted text; image-only/encoding/OCR status unresolved")
                    except (ValueError, RuntimeError, pdfium.PdfiumError) as exc:
                        row["reason"] = str(exc)[:2000] or type(exc).__name__
                    row["text_sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
                    pages.append(row)
        except (ValueError, RuntimeError, pdfium.PdfiumError) as exc:
            failure = str(exc)[:2000] or type(exc).__name__
        visual._runtime_matches(runtime)
    helper = _producer_sources(reader)
    record = {"schema_version": 1, "kind": "literature-pdf-extraction-result", "request": request,
              "source": settings["source"], "page_count": count, "pages": pages,
              "status": "failed" if failure else "partial" if any(p["status"] != "extracted" for p in pages) else "all_page_text_extracted",
              "failure": failure, "elapsed_seconds": time.monotonic() - started,
              "runtime": runtime, "producer": helper, "claims": deepcopy(FLAGS),
              "coverage": "PDFium text only; all original pages retained. Text/page census is not visual, OCR, table/equation or scientific completeness."}
    files = {"request.json": _raw(settings), "product.json": _raw(record)}
    if any(len(data) > MAX_JSON_BYTES for data in files.values()):
        raise ValueError("complete PDF extraction record exceeds existing document budget; raw source and failure directory retained")
    emitted = [_emit(out / name, data, reader) for name, data in files.items()]
    _population(out, emitted); reader.finish(populations=((out, emitted),))
    return {"product": _pin(out / "product.json", files["product.json"]), "page_count": count,
            "status": record["status"], "visual_sources": [settings["source"]], "claims": deepcopy(FLAGS)}


def consume_pdf(binding_pin, *, base_dir, _reader=None):
    """Require the real current completed ordinary extractor, not a forged roster."""
    from . import research_cycle as cycle, agent_graph
    reader = _reader or _Reader(base_dir)
    _, binding = reader.document(binding_pin)
    _keys(binding, ("schema_version", "kind", "graph", "node", "origin", "product"))
    if binding["schema_version"] != 1 or binding["kind"] != "ordinary-literature-pdf-binding":
        raise ValueError("ordinary source-produced PDF binding required")
    current = cycle._graph_result(binding["graph"], binding["node"])
    spec, _ = agent_graph._load(cycle._ordinary(binding["graph"]))
    node = next(n for n in spec["nodes"] if n["id"] == binding["node"])
    if (current != binding["origin"] or node["role"] != "executor" or node["action"] != "literature-pdf-extract"
            or node["kind"] != "tool" or node["max_attempts"] != 1
            or current["value"].get("kind") != "ravel_tool_result"
            or current["value"].get("action") != "literature-pdf-extract"
            or current["value"]["value"]["product"] != binding["product"]):
        raise ValueError("PDF extraction lacks its exact current ordinary tool receipt")
    pin, result = reader.document(binding["product"])
    _keys(result, ("schema_version", "kind", "request", "source", "page_count", "pages", "status", "failure",
                   "elapsed_seconds", "runtime", "producer", "claims", "coverage"))
    if result["schema_version"] != 1 or result["kind"] != "literature-pdf-extraction-result" or result["claims"] != FLAGS:
        raise ValueError("source-produced text-only extraction result required")
    request_pin, settings, _ = _pdf_request(result["request"], reader)
    actual_inputs = {(p["path"], p["sha256"]) for p in current["inputs"]}
    for dependency in pdf_inputs(request_pin, base_dir=base_dir):
        if (dependency["path"], dependency["sha256"]) not in actual_inputs:
            raise ValueError("original PDF/extractor input absent from ordinary receipt")
    if result["source"] != settings["source"]:
        raise ValueError("original PDF identity differs from extraction")
    if result["failure"] is None:
        count = _integer(result["page_count"], settings["max_pages"])
        if [p.get("page_index") for p in result["pages"]] != list(range(count)):
            raise ValueError("complete ordered original PDF page roster required")
        expected_status = 'partial' if any(p.get('status')!='extracted' for p in result['pages']) else 'all_page_text_extracted'
        if result['status'] != expected_status:
            raise ValueError('actual full page outcome status differs')
    else:
        knowledge._text(result["failure"], 2000)
        if result["status"] != "failed":
            raise ValueError("whole extraction failure cannot be called complete")
        # A page-count/resource refusal is not an extracted subset. The raw
        # original and reported whole count remain, with no completeness claim.
        if result["pages"] and [p.get('page_index') for p in result['pages']] != list(range(result['page_count'])):
            raise ValueError("failed whole-document extraction cannot advertise a successful page subset")
    total = 0
    for page in result["pages"]:
        _keys(page, ("page_index", "text", "status", "reason", "visual_status", "ocr_status", "structured_math_tables", "text_sha256"))
        if (type(page["text"]) is not str or page["status"] not in {"extracted", "empty_text", "failed"}
                or page["text_sha256"] != hashlib.sha256(page["text"].encode()).hexdigest()
                or page["visual_status"] != "unobserved" or page["ocr_status"] != "not_performed" or page["structured_math_tables"] != "unverified"):
            raise ValueError("honest text-only page outcomes required")
        if page["status"] == "extracted":
            if not page["text"].strip() or page["reason"] is not None:
                raise ValueError("extracted page text outcome differs")
        elif ((page['status']=='failed' and page['text']) or (page['status']=='empty_text' and page['text'].strip())
              or not isinstance(page["reason"], str) or not page["reason"].strip()):
            raise ValueError("empty/failed page must retain unknown reason without invented text")
        total += len(page["text"].encode())
    if total > settings["max_text_bytes"]:
        raise ValueError("complete original PDF text exceeds original budget")
    helper, _ = reader.read(result["producer"], MAX_JSON_BYTES)
    if helper["path"] != str(Path(__file__).absolute()):
        raise ValueError("foreign extraction producer")
    runtime = result["runtime"]
    _keys(runtime, ("versions", "files", "file_identities", "python", "helper", "loaded_origins"))
    if runtime["versions"].get("pypdfium2") != "5.14.0":
        raise ValueError("required PDFium source/runtime version differs")
    from . import visual_presentation as visual
    current_runtime = visual._runtime(True)  # distribution metadata/files, no native import
    if any(runtime[key] != actual for key, actual in current_runtime.items()):
        raise ValueError('complete original PDF runtime/distribution census differs')
    # The exact result pin groups the complete emitted runtime census; verify
    # every leaf now without expanding the ordinary 128-input model interface.
    # Runtime hashes are custody, never source-reading credit.
    runtime_reader = _Reader(base_dir)
    if not runtime['files'] or len({p['path'] for p in runtime['files']})!=len(runtime['files']):
        raise ValueError('complete distinct original PDF runtime files required')
    for dependency in [*runtime["files"], runtime["python"]["executable"], runtime["helper"]]:
        runtime_reader.read(dependency)
    # Original runtime identities use visual_presentation's tuple order.
    for dependency in runtime["files"]:
        s = Path(dependency['path']).lstat()
        if runtime['file_identities'].get(dependency['path']) != [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]:
            raise ValueError('original PDF runtime file identity/mode changed')
    reader.read(current["receipt"])
    reader.read(_pin(Path(pin["path"]).parent / "request.json", _raw(settings)), MAX_JSON_BYTES)
    _population(Path(pin["path"]).parent, [pin, _pin(Path(pin["path"]).parent / "request.json", _raw(settings))])
    if cycle._graph_result(binding["graph"], binding["node"]) != current:
        raise ValueError("PDF extraction ordinary receipt changed before consumption")
    runtime_reader.finish(readers=(reader,), populations=((Path(pin["path"]).parent, [pin, _pin(Path(pin["path"]).parent / "request.json", _raw(settings))]),))
    return deepcopy(result)


def _url(value):
    knowledge._text(value, 4096)
    u = urlsplit(value)
    if (u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment
            or u.port not in (None,443) or any(c in value for c in '\r\n\x00')):
        raise ValueError('exact credential-free public HTTPS URL required')
    if any(k.lower() in {'token','access_token','apikey','api_key','password','signature','credential'} for k,_ in parse_qsl(u.query)):
        raise ValueError('hidden URL credentials are not public literature acquisition')
    host = u.hostname.encode('idna').decode('ascii')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or host.lower() in {'localhost','localhost.localdomain'}:
        raise ValueError('public configured DNS origin required')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('local/private literal source addresses are refused')
    return u, 'https://' + host.lower()


def origins(values):
    knowledge._items(values, 64)
    result=[]
    for value in values:
        u, origin = _url(value)
        if u.path not in ('','/') or u.query:
            raise ValueError('configured literature origins contain no path/query')
        if origin in result:
            raise ValueError('distinct configured public literature origins required')
        result.append(origin)
    return result


def _acquisition_request(request_pin, reader):
    pin, value = reader.document(request_pin)
    _keys(value, ('schema_version','kind','url','format','expected_sha256','max_bytes','max_seconds','tasks'))
    if value['schema_version'] != 1 or type(value['schema_version']) is not int or value['kind'] != 'literature-acquisition':
        raise ValueError('literature-acquisition/v1 required')
    _url(value['url']); _integer(value['max_bytes'], MAX_INPUT_BYTES-1); _integer(value['max_seconds'],3600)
    if value['format'] not in {'pdf','html','text','tex','markdown'}:
        raise ValueError('explicit supported source media required')
    if value['expected_sha256'] is not None and not re.fullmatch('[a-f0-9]{64}',value['expected_sha256']):
        raise ValueError('optional exact prior source SHA256 required')
    # Reuse exact scout-row validation, without requiring a complete bibliography.
    _request({'schema_version':1,'kind':'literature-context-request','id':'acquisition-tasks',
              'cycle_binding':None,'documents':[],'annotations':[],'hypotheses':[],'edges':[],
              'query':{'text':'Source acquisition only','tags':[],'roots':[],'domain':[],'max_nodes':1},
              'acquisition_tasks':value['tasks']})
    return pin, deepcopy(value)


def acquisition_inputs(request_pin, *, base_dir):
    reader=_Reader(base_dir);_acquisition_request(request_pin,reader)
    _producer_sources(reader)
    reader.finish();return reader.pins()


def _wire_body_complete(headers, observed_bytes):
    """Check retained HTTP entity framing without guessing remote content.

    HTTPResponse already decodes chunked transfer framing and raises on an
    incomplete chunk sequence. Connection-close bodies have only observed EOF;
    neither case supplies a missing remote version/hash or semantic read credit.
    """
    if not isinstance(headers, dict):
        raise ValueError('retained source response headers required')
    transfer = headers.get('Transfer-Encoding')
    length = headers.get('Content-Length')
    if transfer is not None:
        if not isinstance(transfer, str) or transfer.strip(' \t').lower() != 'chunked':
            raise ValueError('unsupported literature transfer framing')
        if length is not None:
            raise ValueError('ambiguous Transfer-Encoding and Content-Length source framing')
        return 'chunked_terminal_eof'
    if length is None:
        return 'connection_eof_unknown_entity_length'
    if not isinstance(length, str) or not re.fullmatch(r'[0-9]+', length.strip(' \t')):
        raise ValueError('invalid or ambiguous advertised source Content-Length')
    # Bound conversion by the actual finite byte count instead of unbounded
    # integer parsing; excess advertised length can never match these bytes.
    advertised = length.strip(' \t').lstrip('0') or '0'
    if advertised != str(observed_bytes):
        raise ValueError('captured body differs from advertised source Content-Length')
    return 'advertised_content_length_matched'


def acquire(request_pin, out, *, base_dir, configured_origins, privacy):
    """Selected-source HTTPS GET only, explicitly charged by the calling tool.

    No environment proxy, provider credentials, redirect, cookies or cache is
    used. Wall checks bound connect/read operations, not arbitrary DNS system
    call latency; the existing outer supervisor remains the hard owner.
    """
    if privacy not in {'configured','local_only'}:
        raise ValueError('existing ordinary Host privacy policy required')
    if privacy == 'local_only':
        raise ValueError('local_only refuses external literature acquisition')
    reader=_Reader(base_dir);request,value=_acquisition_request(request_pin,reader)
    url,origin=_url(value['url']);allowed=origins(list(configured_origins))
    if origin not in allowed:
        raise ValueError('literature source origin was not explicitly configured')
    out=_path(out,reader.base)
    if out.exists():raise ValueError('fresh acquisition output required')
    out.mkdir(parents=True)
    began=time.monotonic();captured=bytearray();headers={};status=None;peer=None;failure=None
    connection=None
    def remaining():
        budget=value['max_seconds']-(time.monotonic()-began)
        if budget<=0:raise ValueError('original acquisition wall allowance exhausted')
        return budget
    try:
        addresses=socket.getaddrinfo(url.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('source resolves to local/private or unavailable network addresses')
        connection=http.client.HTTPSConnection(url.hostname,443,timeout=remaining(),context=ssl.create_default_context())
        connection.connect();transport_socket=connection.sock;peer=transport_socket.getpeername()[0]
        if not ipaddress.ip_address(peer).is_global:
            raise ValueError('actual connected source is not a public network peer')
        transport_socket.settimeout(remaining())
        connection.request('GET',(url.path or '/')+('?' + url.query if url.query else ''),
                           headers={'User-Agent':'RAVEL-located-literature/1','Accept':'application/pdf,text/html,text/plain','Accept-Encoding':'identity'})
        response=connection.getresponse();status=response.status
        headers={name:response.getheader(name) for name in ('Content-Type','Content-Length','Transfer-Encoding','Content-Encoding','ETag','Last-Modified','Location','Retry-After')}
        count=0
        while True:
            # HTTPConnection may clear .sock for a Connection: close response;
            # the retained socket is kept alive by the response's makefile.
            transport_socket.settimeout(remaining())
            chunk=response.read(min(65536,value['max_bytes']-count+1))
            if not chunk:break
            captured.extend(chunk);count+=len(chunk)
            if count>value['max_bytes']:raise ValueError('original complete source byte allowance exceeded; captured prefix is not supplied source')
        remaining()
        body=bytes(captured)
        if status != 200:raise ValueError('source HTTP status '+str(status)+'; redirects are not followed')
        _wire_body_complete(headers,len(body))
        if headers['Content-Encoding'] not in (None,'identity'):
            raise ValueError('encoded response needs a distinct source-bound decompression operation')
        if not body:raise ValueError('empty response is not a supplied literature source')
        if value['expected_sha256'] is not None and hashlib.sha256(body).hexdigest()!=value['expected_sha256']:
            raise ValueError('acquired source differs from prospectively declared original version')
        if value['format']=='pdf' and not body.startswith(b'%PDF-'):
            raise ValueError('PDF source URL did not deliver an original PDF')
        if value['format']!='pdf':body.decode('utf-8')
    except (OSError,ValueError,http.client.HTTPException) as exc:
        failure=str(exc)[:2000] or type(exc).__name__
    finally:
        if connection is not None:connection.close()
    body=bytes(captured)
    files={'request.json':_raw(value)}
    if body:files['response-body.bin']=body
    body_pin=_pin(out/'response-body.bin',body) if body else None
    helper=_producer_sources(reader)
    record={'schema_version':1,'kind':'literature-acquisition-result','request':request,'request_value':value,
            'configured_origins':allowed,'privacy':privacy,'url':value['url'],'peer':peer,'http_status':status,
            'response_headers':headers,'status':'failed' if failure else 'acquired','failure':failure,
            'captured_body':body_pin,'source_artifact':None if failure else body_pin,
            'elapsed_seconds':time.monotonic()-began,'producer':helper,'claims':deepcopy(FLAGS),
            'coverage':'Actual captured HTTP entity bytes only: advertised length must match; chunked framing uses HTTPResponse terminal-chunk checks; unknown length is connection EOF only, not verified remote entity/version completeness. Failed/truncated bytes are not a supplied source. No content reading or verification.'}
    files['product.json']=_raw(record)
    emitted=[_emit(out/name,data,reader) for name,data in files.items()]
    _population(out,emitted);reader.finish(populations=((out,emitted),))
    return {'product':_pin(out/'product.json',files['product.json']),'source_artifact':record['source_artifact'],
            'status':record['status'],'claims':deepcopy(FLAGS)}


def consume_acquisition(binding_pin, *, base_dir, _reader=None):
    from . import research_cycle as cycle, agent_graph
    reader=_reader or _Reader(base_dir);_,binding=reader.document(binding_pin)
    _keys(binding,('schema_version','kind','graph','node','origin','product'))
    if binding['schema_version']!=1 or binding['kind']!='ordinary-literature-acquisition-binding':
        raise ValueError('actual ordinary source acquisition binding required')
    origin=cycle._graph_result(binding['graph'],binding['node']);spec,_=agent_graph._load(cycle._ordinary(binding['graph']))
    node=next(n for n in spec['nodes'] if n['id']==binding['node'])
    if (origin!=binding['origin'] or node['role']!='executor' or node['kind']!='tool' or node['action']!='literature-acquire'
            or node['max_attempts']!=1 or origin['value'].get('kind')!='ravel_tool_result'
            or origin['value'].get('action')!='literature-acquire' or origin['value']['value']['product']!=binding['product']):
        raise ValueError('acquisition lacks exact current ordinary producer receipt')
    product,result=reader.document(binding['product'])
    _keys(result,('schema_version','kind','request','request_value','configured_origins','privacy','url','peer','http_status',
                  'response_headers','status','failure','captured_body','source_artifact','elapsed_seconds','producer','claims','coverage'))
    request,value=_acquisition_request(result['request'],reader)
    if (result['schema_version']!=1 or result['kind']!='literature-acquisition-result' or value!=result['request_value']
            or result['claims']!=FLAGS or result['privacy']=='local_only' or result['url']!=value['url']
            or _url(value['url'])[1] not in origins(result['configured_origins'])):
        raise ValueError('authentic public source acquisition scope required')
    actual_inputs={(p['path'],p['sha256']) for p in origin['inputs']}
    if any((p['path'],p['sha256']) not in actual_inputs for p in acquisition_inputs(request,base_dir=base_dir)):
        raise ValueError('acquisition request/source helper missing from ordinary inputs')
    helper,_=reader.read(result['producer'],MAX_JSON_BYTES)
    if helper['path']!=str(Path(__file__).absolute()):raise ValueError('foreign acquisition producer')
    expected=[product,_pin(Path(product['path']).parent/'request.json',_raw(value))]
    raw=b''
    if result['captured_body'] is not None:
        body,raw=reader.read(result['captured_body']);expected.append(body)
    if len(raw)>value['max_bytes']+1:
        raise ValueError('captured failure prefix exceeds the original finite acquisition allowance')
    if result['status']=='acquired':
        if (result['failure'] is not None or result['http_status']!=200 or not raw or len(raw)>value['max_bytes']
                or result['source_artifact']!=result['captured_body']
                or result['privacy']!='configured' or not result['peer'] or not ipaddress.ip_address(result['peer']).is_global
                or result['response_headers'].get('Content-Encoding') not in (None,'identity')
                or (value['expected_sha256'] is not None and hashlib.sha256(raw).hexdigest()!=value['expected_sha256'])):
            raise ValueError('failed or truncated bytes cannot become acquired literature')
        _wire_body_complete(result['response_headers'],len(raw))
        if value['format']=='pdf' and not raw.startswith(b'%PDF-'):
            raise ValueError('complete acquired PDF source signature differs')
        if value['format']!='pdf':raw.decode('utf-8')
    elif result['status']!='failed' or result['source_artifact'] is not None or not result['failure']:
        raise ValueError('explicit failed acquisition outcome required')
    for pin in expected:reader.read(pin)
    reader.read(origin['receipt'])
    _population(Path(product['path']).parent,expected);reader.finish(populations=((Path(product['path']).parent,expected),))
    if cycle._graph_result(binding['graph'],binding['node'])!=origin:raise ValueError('acquisition receipt changed at ending')
    return deepcopy(result)
