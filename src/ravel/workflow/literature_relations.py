"""Disposable, exact-identifier literature navigation. No acquisition or authority.

Inputs are caller-acquired JSON documents with byte-independent canonical JSON pins.
Pointers refer to those documents, never to prose inferred by this module. The
broker must admit the inputs and recheck original custody when serving evidence.
This projection cannot certify a source, implementation, workspace or physics.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json
import re
import time
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, validators

SCHEMA_VERSION = 1
MAX_SOURCES = 4096
MAX_NODES = 100000
MAX_EDGES = 300000
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 128 * 1024 * 1024
MAX_VISITED = 5000
SOURCE_KINDS = {"inspire", "arxiv", "hepdata", "catalogue", "models", "coverage"}
NODE_KINDS = {"paper", "paper_version", "analysis", "hepdata_record", "table",
              "resource", "code", "workspace", "implementation", "backend", "model",
              "topology", "coverage"}
RELATIONS = {"same_publication", "version_of", "cites", "describes", "contains",
             "implements", "runs_on", "has_code", "has_workspace", "has_topology",
             "candidate_for", "covers"}
FLAGS = {"physics_verified": False, "execution_authorized": False}


def canonical_bytes(value: Any) -> bytes:
    """Stable JSON identity, deliberately distinct from an original-file hash."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("finite JSON data required") from exc


def digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _text(value: Any, limit: int = 2048) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("bounded nonempty literal string required")
    return value


def _positive(value: Any) -> str:
    if type(value) is int:
        value = str(value)
    if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,15}", value):
        raise ValueError("positive exact record/version identifier required")
    return value


def identifier(namespace: str, value: Any) -> str:
    """Normalize only documented identifier spellings; never titles or fuzzy IDs.

    arXiv versions stay in the identifier. An unversioned ID is a publication
    identity and cannot select a particular version.
    """
    if namespace == "inspire":
        if type(value) is str:
            value = re.sub(r"^(?:INSPIRE:|inspire:|ins)", "", value)
        return "inspire:" + _positive(value)
    if namespace == "arxiv":
        value = re.sub(r"^(?:arXiv:|arxiv:)", "", _text(value))
        if not re.fullmatch(r"(?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z][A-Za-z0-9.-]*/[0-9]{7})(?:v[1-9][0-9]*)?", value):
            raise ValueError("literal arXiv identifier required")
        return "arxiv:" + value
    if namespace in {"analysis", "model", "topology", "backend"}:
        return namespace + ":" + _text(value, 256)
    raise ValueError("unknown identifier namespace")


def _url(value: Any) -> str:
    value = _text(value)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("credential-free HTTPS locator required")
    return value


def _revision(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise ValueError("immutable full source revision required")
    return value


def _pointer_part(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


@dataclass(frozen=True)
class SourceDocument:
    """Supplied source snapshot; lineage names *all* contributing source IDs.

    ``sha256`` pins canonical JSON, not acquisition authenticity. ``uri`` and
    ``version`` locate the original snapshot for the caller's custody checks.
    """
    id: str
    kind: str
    uri: str
    version: str
    sha256: str
    document: Mapping[str, Any]
    lineage: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphQuery:
    operation: Literal["implementations", "published_artifacts", "related_papers", "models", "coverage"]
    identifier: str
    kind: str | None = None
    relation_types: tuple[str, ...] = ()
    max_hops: int = 6
    max_results: int = 50
    max_bytes: int = 65536
    max_expansions: int = MAX_VISITED

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GraphQuery:
        if type(value) is not dict or set(value) - set(cls.__dataclass_fields__):
            raise ValueError("typed graph query fields required")
        args = dict(value)
        if "relation_types" in args:
            if type(args["relation_types"]) is not list:
                raise ValueError("relation_types must be a list")
            args["relation_types"] = tuple(args["relation_types"])
        try:
            query = cls(**args)
        except TypeError as exc:
            raise ValueError("typed graph query required") from exc
        query.validate()
        return query

    def validate(self) -> None:
        if type(self.operation) is not str or self.operation not in {"implementations", "published_artifacts", "related_papers", "models", "coverage"}:
            raise ValueError("unsupported graph operation")
        _text(self.identifier, 1024)
        if self.kind is not None and (type(self.kind) is not str or self.kind not in NODE_KINDS):
            raise ValueError("unknown result kind")
        if type(self.relation_types) is not tuple or any(type(r) is not str or r not in RELATIONS for r in self.relation_types):
            raise ValueError("closed relation vocabulary required")
        for value, low, high in ((self.max_hops, 0, 8), (self.max_results, 1, 500), (self.max_bytes, 1024, 1048576), (self.max_expansions, 1, MAX_VISITED)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("finite graph query budget required")


class _Builder:
    def __init__(self, sources: list[SourceDocument]):
        self.sources: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.issues: list[dict] = []
        if len(sources) > MAX_SOURCES:
            raise ValueError("source budget exceeded")
        input_bytes = 0
        for source in sources:
            if not isinstance(source, SourceDocument) or type(source.kind) is not str or source.kind not in SOURCE_KINDS:
                raise ValueError("typed supported source required")
            _text(source.id, 256); _text(source.version, 256); _url(source.uri)
            if type(source.document) is not dict or len(canonical_bytes(source.document)) > MAX_INPUT_BYTES:
                raise ValueError("bounded source JSON object required")
            input_bytes += len(canonical_bytes(source.document))
            if input_bytes > MAX_TOTAL_INPUT_BYTES:
                raise ValueError("total source byte budget exceeded")
            if digest(source.document) != source.sha256:
                raise ValueError("source canonical JSON pin mismatch")
            if type(source.lineage) is not tuple or any(type(s) is not str for s in source.lineage):
                raise ValueError("complete typed source lineage required")
            row = {"id": source.id, "kind": source.kind, "uri": source.uri,
                   "version": source.version, "sha256": source.sha256,
                   "lineage": sorted(set(source.lineage))}
            if source.id in self.sources and self.sources[source.id] != row:
                raise ValueError("conflicting source ID")
            self.sources[source.id] = row
            self.documents[source.id] = deepcopy(source.document)
        for row in self.sources.values():
            if set(row["lineage"]) - self.sources.keys():
                raise ValueError("unresolved source lineage")

    def evidence(self, source: str, pointer: str) -> dict:
        # Every emitted pointer is resolved against the pinned input now.
        value: Any = self.documents[source]
        if pointer:
            if not pointer.startswith("/"):
                raise ValueError("JSON pointer required")
            for part in pointer[1:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                value = value[int(part)] if type(value) is list else value[part]
        return {"source_id": source, "pointer": pointer}

    def node(self, key: str, kind: str, attrs: dict, source: str, pointer: str) -> str:
        evidence = self.evidence(source, pointer)
        row = {"id": key, "kind": kind, "attributes": deepcopy(attrs), "evidence": [evidence], "conflicted": False}
        if key in self.nodes:
            old = self.nodes[key]
            if old["kind"] != kind or any(k in old["attributes"] and old["attributes"][k] != v for k, v in attrs.items()):
                old["conflicted"] = True
                issue = {"kind": "conflicting_node", "node_ids": [key], "evidence": [evidence]}
                if issue not in self.issues:
                    self.issues.append(issue)
            else:
                old["attributes"].update(deepcopy(attrs))
            if evidence not in old["evidence"]:
                old["evidence"].append(evidence)
        else:
            self.nodes[key] = row
        if len(self.nodes) > MAX_NODES:
            raise ValueError("node budget exceeded")
        return key

    def edge(self, start: str, relation: str, end: str, source: str, pointer: str) -> None:
        key = "edge:" + digest([start, relation, end])
        evidence = self.evidence(source, pointer)
        row = {"id": key, "source": start, "relation": relation, "target": end, "evidence": [evidence]}
        if key in self.edges:
            if evidence not in self.edges[key]["evidence"]:
                self.edges[key]["evidence"].append(evidence)
        else:
            self.edges[key] = row
        if len(self.edges) > MAX_EDGES:
            raise ValueError("edge budget exceeded")

    def paper(self, namespace: str, value: Any, source: str, pointer: str) -> str:
        key = identifier(namespace, value)
        if namespace == "arxiv" and re.search(r"v[1-9][0-9]*$", key):
            base = re.sub(r"v[1-9][0-9]*$", "", key)
            self.node(base, "paper", {}, source, pointer)
            self.node(key, "paper_version", {}, source, pointer)
            self.edge(key, "version_of", base, source, pointer)
            return key
        return self.node(key, "paper", {}, source, pointer)

    def publication_links(self, row: dict, source: str, pointer: str) -> list[str]:
        papers = []
        for field, namespace in (("inspire_id", "inspire"), ("arxiv_id", "arxiv")):
            if row.get(field) is not None:
                papers.append(self.paper(namespace, row[field], source, pointer + "/" + field))
        if len(papers) == 2:
            # Version aliases point through their explicit unversioned publication.
            base = re.sub(r"v[1-9][0-9]*$", "", papers[1]) if papers[1].startswith("arxiv:") else papers[1]
            self.edge(papers[0], "same_publication", base, source, pointer)
        return papers

    def inspire(self, source: str, doc: dict) -> None:
        md = doc.get("metadata", doc)
        root = "/metadata" if "metadata" in doc else ""
        field = "control_number" if "control_number" in md else "id"
        rec = md[field] if field in md else doc["id"]
        pointer = root + "/" + field if field in md else "/id"
        paper = self.paper("inspire", rec, source, pointer)
        for i, entry in enumerate(md.get("arxiv_eprints", [])):
            p = root + f"/arxiv_eprints/{i}/value"
            arxiv = self.paper("arxiv", entry["value"], source, p)
            base = re.sub(r"v[1-9][0-9]*$", "", arxiv)
            self.edge(paper, "same_publication", base, source, p)
        for i, entry in enumerate(md.get("references", [])):
            ref = entry.get("record", {}).get("$ref")
            if ref is None:
                continue
            # Only the exact provider record path carries an identity.
            match = re.fullmatch(r"https://inspirehep\.net/api/literature/([1-9][0-9]*)", ref)
            if match:
                p = root + f"/references/{i}/record/$ref"
                other = self.paper("inspire", match[1], source, p)
                self.edge(paper, "cites", other, source, p)

    def arxiv(self, source: str, doc: dict) -> None:
        self.paper("arxiv", doc["arxiv_id"], source, "/arxiv_id")
        self.publication_links(doc, source, "")

    def hepdata(self, source: str, doc: dict) -> None:
        rec = doc.get("record", doc)
        root = "/record" if "record" in doc else ""
        recid = _positive(doc.get("recid", rec.get("recid")))
        version = _positive(doc.get("version", rec.get("version")))
        key = "hepdata:" + recid + ":v" + version
        self.node(key, "hepdata_record", {"recid": recid, "version": version}, source, "")
        for paper in self.publication_links(rec, source, root):
            self.edge(paper, "describes", key, source, root)
        for i, table in enumerate(doc.get("data_tables", [])):
            p = f"/data_tables/{i}"
            table_id = _positive(table["id"])
            attrs = {k: table[k] for k in ("name", "doi", "qualifiers", "axes", "units", "quantity", "observed_expected") if k in table}
            node = self.node(key + ":table:" + table_id, "table", attrs, source, p)
            self.edge(key, "contains", node, source, p)
        for i, resource in enumerate(rec.get("resources", [])):
            p = root + f"/resources/{i}"
            uri = _url(resource.get("url", resource.get("location")))
            kind = resource.get("kind", "resource")
            if kind not in {"resource", "code", "workspace"}:
                raise ValueError("explicit resource/code/workspace kind required")
            attrs = {k: resource[k] for k in ("sha256", "format", "description") if k in resource}
            if "sha256" in attrs and not re.fullmatch(r"[0-9a-f]{64}", str(attrs["sha256"])):
                raise ValueError("resource content pin must be a SHA256")
            attrs["uri"] = uri
            node = self.node(key + ":resource:" + digest(uri), kind, attrs, source, p)
            self.edge(key, "contains", node, source, p)
            if "implementation" in resource:
                binding = resource["implementation"]
                revision = _revision(binding["revision"])
                impl = self.node("implementation:" + _text(binding["id"], 256) + "@" + revision,
                                 "implementation", {"revision": revision}, source, p + "/implementation")
                if kind not in {"code", "workspace"}:
                    raise ValueError("implementation binding requires explicit code/workspace resource")
                self.edge(impl, "has_code" if kind == "code" else "has_workspace", node, source, p)

    def catalogue(self, source: str, doc: dict) -> None:
        for i, entry in enumerate(doc["entries"]):
            p = f"/entries/{i}"
            backend = _text(entry["framework"], 256)
            source_key = entry.get("source_id", backend)
            upstream = doc["sources"][source_key]
            upstream_pointer = "/sources/" + _pointer_part(source_key)
            revision = _revision(upstream["revision"])
            repository = _url(upstream["repository"])
            impl = "implementation:" + _text(entry["id"], 256) + "@" + revision
            self.node(impl, "implementation", {"revision": revision, "backend": backend,
                      "availability": entry.get("upstream_status", "unknown"),
                      "qualification": "unknown"}, source, p)
            self.node(impl, "implementation", {"revision": revision}, source, upstream_pointer)
            b = self.node(identifier("backend", backend), "backend", {}, source, p + "/framework")
            self.edge(impl, "runs_on", b, source, p)
            papers = self.publication_links(entry, source, p)
            for j, url in enumerate(entry.get("publication_urls", [])):
                match = re.fullmatch(r"https://arxiv\.org/abs/((?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z][A-Za-z0-9.-]*/[0-9]{7})(?:v[1-9][0-9]*)?)", url)
                if match:
                    paper = self.paper("arxiv", match[1], source, p + f"/publication_urls/{j}")
                    if paper not in papers:
                        papers.append(paper)
                    for other in papers:
                        if other.startswith("inspire:"):
                            self.edge(other, "same_publication", re.sub(r"v[1-9][0-9]*$", "", paper), source, p + f"/publication_urls/{j}")
            analyses = []
            for j, value in enumerate(entry.get("analysis_ids", [])):
                analysis = self.node(identifier("analysis", value), "analysis", {}, source, p + f"/analysis_ids/{j}")
                analyses.append(analysis)
                self.edge(impl, "implements", analysis, source, p)
                for paper in papers:
                    self.edge(analysis, "describes", paper, source, p)
            for paper in papers:
                self.edge(impl, "implements", paper, source, p)
            for j, member in enumerate(entry.get("source_files", [])):
                # A member is a path, or a record carrying the path and its content pins.
                pins = {}
                if type(member) is dict:
                    pins = {k: member[k] for k in ("sha256", "git_blob") if k in member}
                    if "sha256" in pins and not re.fullmatch(r"[0-9a-f]{64}", str(pins["sha256"])):
                        raise ValueError("source member content pin must be a SHA256")
                    if "git_blob" in pins:
                        _revision(pins["git_blob"])
                    member = member["path"]
                path = _text(member)
                if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
                    raise ValueError("relative normalized source member required")
                code = self.node("code:" + digest([repository, revision, path]), "code",
                                 {"repository": repository, "revision": revision, "path": path, **pins}, source, p + f"/source_files/{j}")
                self.node(code, "code", {"repository": repository, "revision": revision}, source, upstream_pointer)
                self.edge(impl, "has_code", code, source, p)
            for j, workspace in enumerate(entry.get("workspaces", [])):
                uri = _url(workspace["uri"])
                attrs = {k: workspace[k] for k in ("uri", "format", "sha256", "revision", "conditions") if k in workspace}
                if "sha256" in attrs and not re.fullmatch(r"[0-9a-f]{64}", str(attrs["sha256"])):
                    raise ValueError("workspace content pin must be a SHA256")
                node = self.node("workspace:" + digest([impl, uri]), "workspace", attrs, source, p + f"/workspaces/{j}")
                self.edge(impl, "has_workspace", node, source, p)

    def models(self, source: str, doc: dict) -> None:
        for i, model in enumerate(doc["models"]):
            p = f"/models/{i}"
            key = self.node(identifier("model", model["id"]), "model",
                            {k: model[k] for k in ("revision", "conditions", "structural_key") if k in model}, source, p)
            for j, value in enumerate(model.get("topologies", [])):
                topology = self.node(identifier("topology", value), "topology", {}, source, p + f"/topologies/{j}")
                self.edge(key, "has_topology", topology, source, p)
            for j, value in enumerate(model.get("analysis_ids", [])):
                analysis = self.node(identifier("analysis", value), "analysis", {}, source, p + f"/analysis_ids/{j}")
                self.edge(key, "candidate_for", analysis, source, p)

    def coverage(self, source: str, doc: dict) -> None:
        # Validation and the denominator calculation share the coverage contract.
        from .literature_coverage import validate_population
        validate_population(doc)
        backend = self.node(identifier("backend", doc["backend"]), "backend", {}, source, "/backend")
        key = "coverage:" + digest([doc["backend"], doc["as_of"], doc["revision"], self.sources[source]["sha256"]])
        self.node(key, "coverage", {k: deepcopy(doc[k]) for k in ("backend", "as_of", "revision", "population", "entries")}, source, "")
        self.edge(backend, "covers", key, source, "")
        for i, row in enumerate(doc["entries"]):
            p = f"/entries/{i}"
            namespace, _, value = row["member"].partition(":")
            member = self.paper(namespace, value, source, p + "/member") if namespace in {"inspire", "arxiv"} else self.node(identifier(namespace, value), "analysis", {}, source, p + "/member")
            self.edge(key, "covers", member, source, p)
            mapped = {member}
            for namespace, field in (("analysis", "analysis_id"), ("inspire", "inspire_id"), ("arxiv", "arxiv_id")):
                if row.get(field) is None:
                    continue
                p = f"/entries/{i}/{field}"
                target = self.paper(namespace, row[field], source, p) if namespace in {"inspire", "arxiv"} else self.node(identifier(namespace, row[field]), "analysis", {}, source, p)
                self.edge(key, "covers", target, source, f"/entries/{i}")
                mapped.add(target)
            for analysis in sorted(k for k in mapped if k.startswith("analysis:")):
                for paper in sorted(k for k in mapped if k.startswith(("inspire:", "arxiv:"))):
                    self.edge(analysis, "describes", paper, source, f"/entries/{i}")
            for inspire in sorted(k for k in mapped if k.startswith("inspire:")):
                for arxiv in sorted(k for k in mapped if k.startswith("arxiv:")):
                    self.edge(inspire, "same_publication", re.sub(r"v[1-9][0-9]*$", "", arxiv), source, f"/entries/{i}")

    def build(self) -> LiteratureGraph:
        for source in sorted(self.sources):
            getattr(self, self.sources[source]["kind"])(source, self.documents[source])
        # Conflicting exact aliases are quarantined, never resolved by recency.
        aliases: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges.values():
            if edge["relation"] == "same_publication":
                aliases[edge["source"]].add(edge["target"])
                aliases[edge["target"]].add(edge["source"])
        for node, targets in sorted(aliases.items()):
            if len(targets) > 1:
                ids = sorted({node, *targets})
                for key in ids:
                    self.nodes[key]["conflicted"] = True
                self.issues.append({"kind": "conflicting_alias", "node_ids": ids, "evidence": []})
        for row in [*self.nodes.values(), *self.edges.values()]:
            row["evidence"].sort(key=canonical_bytes)
        snapshot = {"schema_version": SCHEMA_VERSION, "kind": "literature-relations",
                    "sources": sorted(self.sources.values(), key=lambda r: r["id"]),
                    "nodes": sorted(self.nodes.values(), key=lambda r: r["id"]),
                    "edges": sorted(self.edges.values(), key=lambda r: r["id"]),
                    "issues": sorted(self.issues, key=canonical_bytes), **FLAGS}
        snapshot["graph_sha256"] = digest(snapshot)
        return LiteratureGraph(snapshot)


def build_graph(sources: list[SourceDocument]) -> LiteratureGraph:
    """Build from explicit supplied snapshots, with no ambient files or network."""
    if type(sources) is not list:
        raise ValueError("source list required")
    try:
        return _Builder(sources).build()
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("malformed structured source metadata") from exc


class LiteratureGraph:
    """Validated immutable-by-copy snapshot and a closed query interface."""
    def __init__(self, snapshot: dict, *, expected_sha256: str | None = None):
        schema = json.loads(files("ravel").joinpath("data/knowledge/schema/literature-graph.json").read_text())
        errors = sorted(Draft202012Validator(schema).iter_errors(snapshot), key=lambda e: str(e.path))
        if errors:
            raise ValueError("invalid graph snapshot: " + errors[0].message)
        unsigned = {k: v for k, v in snapshot.items() if k != "graph_sha256"}
        if digest(unsigned) != snapshot["graph_sha256"]:
            raise ValueError("graph snapshot pin mismatch")
        if expected_sha256 is not None and snapshot["graph_sha256"] != expected_sha256:
            raise ValueError("graph does not match the caller's pinned generation")
        self._snapshot = deepcopy(snapshot)
        self._sources = {r["id"]: r for r in self._snapshot["sources"]}
        self._nodes = {r["id"]: r for r in self._snapshot["nodes"]}
        self._edges = {r["id"]: r for r in self._snapshot["edges"]}
        if len(self._sources) != len(snapshot["sources"]) or len(self._nodes) != len(snapshot["nodes"]) or len(self._edges) != len(snapshot["edges"]):
            raise ValueError("duplicate graph identities")
        for source in self._sources.values():
            if set(source["lineage"]) - self._sources.keys():
                raise ValueError("unresolved lineage")
        for row in [*self._nodes.values(), *self._edges.values()]:
            if any(e["source_id"] not in self._sources for e in row["evidence"]):
                raise ValueError("unresolved evidence source")
        for node in self._nodes.values():
            key, kind = node["id"], node["kind"]
            if kind in {"paper", "paper_version"}:
                namespace, _, raw = key.partition(":")
                if namespace not in {"inspire", "arxiv"} or identifier(namespace, raw) != key:
                    raise ValueError("canonical paper identity required")
                versioned = namespace == "arxiv" and bool(re.search(r"v[1-9][0-9]*$", key))
                if versioned != (kind == "paper_version"):
                    raise ValueError("paper and paper-version identities are distinct")
            if kind in {"analysis", "model", "topology", "backend"}:
                namespace, _, raw = key.partition(":")
                if namespace != kind or identifier(kind, raw) != key:
                    raise ValueError("canonical entity identity required")
            if kind == "coverage":
                from .literature_coverage import validate_population
                validate_population(node["attributes"])
        for issue in snapshot["issues"]:
            if set(issue["node_ids"]) - self._nodes.keys() or any(e["source_id"] not in self._sources for e in issue["evidence"]):
                raise ValueError("unresolved conflict evidence")
        for edge in self._edges.values():
            if edge["source"] not in self._nodes or edge["target"] not in self._nodes:
                raise ValueError("dangling graph edge")
            if edge["id"] != "edge:" + digest([edge["source"], edge["relation"], edge["target"]]):
                raise ValueError("edge identity mismatch")
            start, end = self._nodes[edge["source"]]["kind"], self._nodes[edge["target"]]["kind"]
            papers = {"paper", "paper_version"}
            pairs = {"same_publication": {("paper", "paper")},
                     "version_of": {("paper_version", "paper")}, "cites": {("paper", "paper")},
                     "describes": {*(('analysis', p) for p in papers), *((p, 'hepdata_record') for p in papers)},
                     "contains": {("hepdata_record", k) for k in ("table", "resource", "code", "workspace")},
                     "implements": {("implementation", k) for k in {*papers, "analysis"}},
                     "runs_on": {("implementation", "backend")}, "has_code": {("implementation", "code")},
                     "has_workspace": {("implementation", "workspace")}, "has_topology": {("model", "topology")},
                     "candidate_for": {("model", "analysis")},
                     "covers": {("backend", "coverage"), *(("coverage", k) for k in {*papers, "analysis"})}}
            if (start, end) not in pairs[edge["relation"]]:
                raise ValueError("relation endpoint kinds do not match the typed contract")

    @property
    def sha256(self) -> str:
        return self._snapshot["graph_sha256"]

    def to_dict(self) -> dict:
        return deepcopy(self._snapshot)

    def _source_lineage(self, source_ids: set[str]) -> list[dict]:
        source_ids = set(source_ids)
        pending = list(source_ids)
        while pending:
            for parent in self._sources[pending.pop()]["lineage"]:
                if parent not in source_ids:
                    source_ids.add(parent); pending.append(parent)
        return [deepcopy(self._sources[s]) for s in sorted(source_ids)]

    def _view(self, denied_sources: frozenset[str], denied_identifiers: frozenset[str]) -> tuple[dict, dict]:
        denied = set(denied_sources)
        # Closure includes identical content copies, aliases and derivative cycles.
        while True:
            hashes = {s["sha256"] for k, s in self._sources.items() if k in denied}
            more = {k for k, s in self._sources.items() if s["sha256"] in hashes or set(s["lineage"]) & denied}
            if more <= denied:
                break
            denied.update(more)
        banned_nodes = set(denied_identifiers)
        for node in self._nodes.values():
            if node["conflicted"] or any(e["source_id"] in denied for e in node["evidence"]):
                banned_nodes.add(node["id"])
        while True:
            more = set()
            for edge in self._edges.values():
                if edge["relation"] in {"same_publication", "version_of"} and {edge["source"], edge["target"]} & banned_nodes:
                    more.update((edge["source"], edge["target"]))
            # Coverage nodes contain an entire population, including members
            # without graph mappings. Do not leak those IDs in a generic query.
            for node in self._nodes.values():
                if node["kind"] != "coverage":
                    continue
                identities = set(node["attributes"]["population"])
                for row in node["attributes"]["entries"]:
                    for ns, field in (("analysis", "analysis_id"), ("inspire", "inspire_id"), ("arxiv", "arxiv_id")):
                        if field in row:
                            identities.add(identifier(ns, row[field]))
                    if "implementation_id" in row:
                        identities.add(row["implementation_id"])
                if identities & banned_nodes:
                    more.add(node["id"])
            if more <= banned_nodes:
                break
            banned_nodes.update(more)
        nodes = {k: v for k, v in self._nodes.items() if k not in banned_nodes}
        edges = {k: v for k, v in self._edges.items() if v["source"] in nodes and v["target"] in nodes and not any(e["source_id"] in denied for e in v["evidence"])}
        return nodes, edges

    def query(self, query: GraphQuery, *, denied_sources: frozenset[str] = frozenset(),
              denied_identifiers: frozenset[str] = frozenset()) -> dict:
        if not isinstance(query, GraphQuery):
            raise ValueError("GraphQuery required; query languages are unsupported")
        query.validate()
        for policy in (denied_sources, denied_identifiers):
            if type(policy) is not frozenset or any(type(k) is not str for k in policy):
                raise ValueError("explicit frozen source/identifier denial set required")
        nodes, edges = self._view(denied_sources, denied_identifiers)
        targets = {"implementations": {"implementation"}, "published_artifacts": {"hepdata_record", "table", "resource", "code", "workspace"},
                   "related_papers": {"paper", "paper_version"}, "models": {"model", "topology"}, "coverage": {"coverage"}}[query.operation]
        if query.kind is not None:
            targets &= {query.kind}
        allowed = {"implementations": {"same_publication", "version_of", "describes", "implements"},
                   "published_artifacts": {"same_publication", "version_of", "describes", "contains", "implements", "has_code", "has_workspace"},
                   "related_papers": RELATIONS - {"runs_on", "covers"}, "models": {"same_publication", "version_of", "describes", "candidate_for", "has_topology"},
                   "coverage": {"same_publication", "version_of", "describes", "covers", "implements"}}[query.operation]
        if query.relation_types:
            allowed = allowed & set(query.relation_types)
        adjacent: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for edge in edges.values():
            if edge["relation"] in allowed:
                adjacent[edge["source"]].append((edge["target"], edge))
                adjacent[edge["target"]].append((edge["source"], edge))
        queue = deque([(query.identifier, [])]) if query.identifier in nodes else deque()
        seen = {query.identifier}
        selected = []
        truncated = False
        result = {"schema_version": 1, "kind": "literature-graph-result", "operation": query.operation,
                  "graph_sha256": self.sha256, "results": selected, "truncated": False,
                  "status": "unknown", "usage": {"expansions": query.max_expansions}, **FLAGS}
        while queue:
            key, path = queue.popleft()
            node = nodes[key]
            if node["kind"] in targets and (path or query.operation != "related_papers"):
                path_nodes = {query.identifier, key, *(e["source"] for e in path), *(e["target"] for e in path)}
                source_ids = {e["source_id"] for row in [*(nodes[n] for n in path_nodes), *path] for e in row["evidence"]}
                candidate = {"node": deepcopy(node), "path": deepcopy(path),
                             "sources": self._source_lineage(source_ids), **FLAGS}
                proposed = {**result, "results": [*selected, candidate], "status": "matched"}
                if len(canonical_bytes(proposed)) <= query.max_bytes:
                    selected.append(candidate)
                else:
                    truncated = True
                if len(selected) >= query.max_results:
                    truncated |= bool(queue or any(other not in seen for other, _ in adjacent[key]))
                    break
            if len(path) >= query.max_hops:
                truncated |= any(other not in seen for other, _ in adjacent[key])
                continue
            for other, edge in sorted(adjacent[key], key=lambda pair: (pair[0], pair[1]["id"])):
                # A version can reach its base identity, but cannot select a sibling
                # version through that identity as though it were the same source.
                if edge["relation"] == "version_of" and edge["source"] == other and key != query.identifier:
                    continue
                if other not in seen:
                    if len(seen) >= query.max_expansions:
                        truncated = True
                        continue
                    seen.add(other); queue.append((other, [*path, edge]))
        result.update(truncated=truncated, status="matched" if selected else "unknown")
        result["usage"]["expansions"] = len(seen) if query.identifier in nodes else 0
        return result


@dataclass(frozen=True)
class RetrievalSourceBinding:
    """Trusted index mapping from a graph snapshot to original-byte descriptors.

    Canonical graph source hashes and retrieval original-byte hashes are distinct.
    The broker authenticates this mapping and the complete descriptor lineage.
    """
    source_id: str
    source_sha256: str
    descriptors: tuple[dict, ...]


@dataclass(frozen=True)
class RetrievalDocumentBinding:
    """Explicit provider identity for an acquired graph item, without inference."""
    node_id: str
    document_id: str
    version: str
    descriptors: tuple[dict, ...]


@lru_cache(maxsize=2)
def _retrieval_definition(name: str):
    # The committed provider schema is normative. Do not clone its wire schema
    # or use its private validators as an accidental second public interface.
    schema = json.loads(files("ravel").joinpath("data/knowledge/schema/retrieval.json").read_text())
    checker = Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda _, value: type(value) is int)
    return validators.extend(Draft202012Validator, type_checker=checker)(
        {"$defs": schema["$defs"], "$ref": "#/$defs/" + name})


def _retrieval_descriptors(rows: tuple[dict, ...]) -> tuple[dict, ...]:
    if type(rows) is not tuple or not 1 <= len(rows) <= 65 or len(canonical_bytes(rows)) > 512 * 1024:
        raise ValueError("bounded complete retrieval descriptors required")
    for row in rows:
        if not _retrieval_definition("descriptor").is_valid(row):
            raise ValueError("invalid retrieval source descriptor")
        if row["kind"] != "source" and row["pin"]["receipt_id"] is None:
            raise ValueError("derived retrieval descriptor requires its producer receipt")
    return tuple(deepcopy(row) for row in rows)


def scope_retrieval(graph: LiteratureGraph, query: GraphQuery, request: dict, *,
                    view, source_bindings: list[RetrievalSourceBinding],
                    document_bindings: list[RetrievalDocumentBinding],
                    denied_sources: frozenset[str] = frozenset(),
                    denied_identifiers: frozenset[str] = frozenset()) -> dict:
    """Narrow a provider search request; never invoke or replace its provider.

    Missing bindings and denied sources are filtered before graph traversal.
    Empty scope/intersection returns ``request=None``: the provider's empty scope
    means unrestricted search. Other operations have no document-scope field and
    are refused. Original filters, identity, token/byte caps and source view stay
    intact. Graph time and conservative node reservations consume the request's
    wall/expansion allowance; the returned request contains only the remainder.
    This is navigation metadata, not a provider evidence envelope or authority.
    """
    from .literature_provider import SourceView, validate_request

    started = time.monotonic()
    request = validate_request(request)
    if request["operation"] != "search":
        raise ValueError("graph document scope is defined only for provider search")
    if not isinstance(graph, LiteratureGraph) or not isinstance(query, GraphQuery):
        raise ValueError("typed graph and graph query required")
    query.validate()
    if not isinstance(view, SourceView) or not callable(view.permits):
        raise ValueError("trusted provider SourceView required")
    if type(view.policy_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", view.policy_sha256):
        raise ValueError("pinned provider policy view required")
    if type(source_bindings) is not list or len(source_bindings) > MAX_SOURCES or type(document_bindings) is not list or len(document_bindings) > MAX_NODES:
        raise ValueError("bounded typed retrieval bindings required")
    for policy in (denied_sources, denied_identifiers):
        if type(policy) is not frozenset or any(type(k) is not str for k in policy):
            raise ValueError("explicit frozen denial set required")

    def permitted(descriptors):
        try:
            # Pass copies: callback mutation cannot rewrite the retained pins.
            values = [view.permits(deepcopy(row)) for row in descriptors]
        except Exception as exc:
            raise ValueError("retrieval source policy evaluation failed") from exc
        if any(type(value) is not bool for value in values):
            raise ValueError("retrieval source policy must return explicit booleans")
        return all(values)

    sources: dict[str, tuple[dict, ...]] = {}
    denied = set(denied_sources)
    binding_bytes = 0
    for binding in source_bindings:
        if not isinstance(binding, RetrievalSourceBinding) or binding.source_id not in graph._sources:
            raise ValueError("binding must name an existing graph source")
        if binding.source_sha256 != graph._sources[binding.source_id]["sha256"]:
            raise ValueError("retrieval binding belongs to another graph source snapshot")
        descriptors = _retrieval_descriptors(binding.descriptors)
        binding_bytes += len(canonical_bytes(descriptors))
        if binding_bytes > MAX_TOTAL_INPUT_BYTES:
            raise ValueError("total retrieval binding byte budget exceeded")
        if binding.source_id in sources and sources[binding.source_id] != descriptors:
            raise ValueError("conflicting retrieval source binding")
        sources[binding.source_id] = descriptors
        if not permitted(descriptors):
            denied.add(binding.source_id)
    denied.update(set(graph._sources) - sources.keys())

    documents: dict[str, list[tuple[dict, tuple[dict, ...]]]] = defaultdict(list)
    identities: dict[tuple[str, str], tuple[dict, ...]] = {}
    for binding in document_bindings:
        if not isinstance(binding, RetrievalDocumentBinding) or binding.node_id not in graph._nodes:
            raise ValueError("binding must name an existing graph item")
        identity = {"document_id": binding.document_id, "version": binding.version}
        if not _retrieval_definition("identity").is_valid(identity):
            raise ValueError("exact provider document and version identity required")
        descriptors = _retrieval_descriptors(binding.descriptors)
        binding_bytes += len(canonical_bytes(descriptors))
        if binding_bytes > MAX_TOTAL_INPUT_BYTES:
            raise ValueError("total retrieval binding byte budget exceeded")
        # Check consistency before policy: a withheld roster must not leave a
        # second, shorter roster for the same identity as its admitted lineage.
        key = binding.document_id, binding.version
        if key in identities and canonical_bytes(identities[key]) != canonical_bytes(descriptors):
            raise ValueError("conflicting retrieval document identity binding")
        identities[key] = descriptors
        if not permitted(descriptors):
            continue
        if (identity, descriptors) not in documents[binding.node_id]:
            documents[binding.node_id].append((identity, descriptors))

    graph_query = replace(query, max_expansions=min(query.max_expansions, request["budgets"]["max_expansions"]))
    projected = graph.query(graph_query, denied_sources=frozenset(denied), denied_identifiers=denied_identifiers)
    existing = {(r["document_id"], r["version"]) for r in request["args"]["document_scope"]}
    matches: dict[tuple[str, str], dict] = {}
    for item in projected["results"]:
        path_nodes = {query.identifier, item["node"]["id"], *(e["source"] for e in item["path"]), *(e["target"] for e in item["path"])}
        path = [query.identifier, *(edge["id"] for edge in item["path"])]
        lineage = [descriptor for source in item["sources"] for descriptor in sources[source["id"]]]
        for node_id in sorted(path_nodes):
            for identity, descriptors in documents[node_id]:
                key = identity["document_id"], identity["version"]
                if existing and key not in existing:
                    continue
                row = matches.setdefault(key, {**identity, "node_ids": [], "graph_paths": [], "lineage": []})
                if node_id not in row["node_ids"]:
                    row["node_ids"].append(node_id)
                if path not in row["graph_paths"] and len(row["graph_paths"]) < 64:
                    row["graph_paths"].append(path)
                for descriptor in [*lineage, *descriptors]:
                    if descriptor not in row["lineage"]:
                        row["lineage"].append(deepcopy(descriptor))

    # Complete lineage may not be truncated to fit the provider's 64-parent
    # evidence contract. Such a candidate must use the separately budgeted rescue.
    selected = [matches[key] for key in sorted(matches) if len(matches[key]["lineage"]) <= 64]
    truncated = projected["truncated"] or len(selected) != len(matches) or len(selected) > 512
    selected = selected[:512]
    result = {"schema_version": 1, "kind": "literature-retrieval-scope", "graph_sha256": graph.sha256,
              "policy_view_sha256": view.policy_sha256, "status": "unknown", "request": None,
              "document_scope": [], "matches": selected, "truncated": truncated,
              "usage": {"expansions": projected["usage"]["expansions"], "elapsed_seconds": 0.0}, **FLAGS}
    cap = min(query.max_bytes, request["budgets"]["max_bytes"], request["budgets"]["max_tokens"])
    result["usage"]["elapsed_seconds"] = max(0.0, time.monotonic() - started)
    remaining = deepcopy(request["budgets"])
    remaining["max_expansions"] -= result["usage"]["expansions"]
    remaining["max_seconds"] -= result["usage"]["elapsed_seconds"]
    if remaining["max_expansions"] < 1 or remaining["max_seconds"] < 0.001:
        result.update(status="budget_exhausted", matches=[], truncated=True)
    else:
        while result["matches"]:
            scope = [{"document_id": m["document_id"], "version": m["version"]} for m in result["matches"]]
            scoped = deepcopy(request)
            scoped["args"]["document_scope"] = scope
            scoped["budgets"] = remaining
            result.update(status="matched", request=validate_request(scoped), document_scope=scope)
            if len(canonical_bytes(result)) <= cap:
                break
            result["matches"].pop(); result["truncated"] = True
        if not result["matches"]:
            result.update(status="unknown", request=None, document_scope=[])
    # Projection, request validation and output sizing also spend wall time.
    elapsed = max(0.0, time.monotonic() - started)
    result["usage"]["elapsed_seconds"] = elapsed
    seconds_left = request["budgets"]["max_seconds"] - elapsed
    if seconds_left < 0.001:
        result.update(status="budget_exhausted", matches=[], document_scope=[], request=None, truncated=True)
    elif result["request"] is not None:
        result["request"]["budgets"]["max_seconds"] = seconds_left
    if len(canonical_bytes(result)) > cap:
        raise ValueError("retrieval budget cannot fit the bounded graph scope outcome")
    return result
