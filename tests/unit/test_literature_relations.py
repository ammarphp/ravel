"""Fictional exact-ID graph witnesses and refusal/taint controls."""
import synthetic_identifiers as syn
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ravel.workflow.literature_relations import (
    GraphQuery, LiteratureGraph, RetrievalDocumentBinding, RetrievalSourceBinding,
    SourceDocument, build_graph, canonical_bytes, digest, identifier, scope_retrieval,
)


def source(name, kind, doc, lineage=()):
    return SourceDocument(name, kind, "https://example.invalid/" + name,
                          "snapshot-1", digest(doc), doc, lineage)


def chain():
    return [
        source("bibliography", "inspire", {"metadata": {"control_number": 9901,
            "titles": [{"title": "A fictional supplied publication"}],
            "arxiv_eprints": [{"value": syn.arxiv(1) + "v2"}],
            "references": [{"record": {"$ref": "https://inspirehep.net/api/literature/9902"}}]}}),
        source("preprint", "arxiv", {"arxiv_id": syn.arxiv(1) + "v2"}),
        source("tables", "hepdata", {"recid": 88001, "version": 3,
            "record": {"inspire_id": 9901, "resources": [
                {"url": "https://example.invalid/release/code", "kind": "code",
                 "implementation": {"id": "engine-a:selection_a", "revision": "a" * 40}},
                {"url": "https://example.invalid/release/workspace", "kind": "workspace",
                 "format": "json", "sha256": "b" * 64}]},
            "data_tables": [{"id": 71, "name": "Spectrum", "units": ["unit-a"],
                "axes": ["coordinate-a"], "qualifiers": [{"name": "region", "value": "region-a"}],
                "observed_expected": "expected"}]}),
        source("implementations", "catalogue", {
            "sources": {"engine-a": {"revision": "a" * 40, "repository": "https://example.invalid/repository"}},
            "entries": [{"id": "engine-a:selection_a", "framework": "engine-a",
                "source_id": "engine-a", "inspire_id": "ins9901", "analysis_ids": ["SEARCH-A"],
                "upstream_status": "released", "source_files": ["analyses/selection_a.cc"],
                "workspaces": [{"uri": "https://example.invalid/release/fit.json", "format": "json"}]}]}),
        source("model", "models", {"models": [{"id": "model-a", "revision": "model-r1",
            "topologies": ["topology-a"], "analysis_ids": ["SEARCH-A"],
            "conditions": {"width": "supplied", "lifetime": "supplied"}}]}),
    ]


def ids(result):
    return {r["node"]["id"] for r in result["results"]}


def test_exact_artifact_chain_and_source_pointer_roundtrip():
    inputs = chain()
    graph = build_graph(inputs)
    result = graph.query(GraphQuery("published_artifacts", "arxiv:" + syn.arxiv(1), max_hops=8))
    kinds = {r["node"]["kind"] for r in result["results"]}
    assert {"hepdata_record", "table", "code", "workspace"} <= kinds
    table = next(r["node"] for r in result["results"] if r["node"]["kind"] == "table")
    assert table["id"] == "hepdata:88001:v3:table:71"
    assert table["attributes"]["units"] == ["unit-a"]
    assert table["attributes"]["observed_expected"] == "expected"
    docs = {s.id: s.document for s in inputs}
    for item in result["results"]:
        for row in [item["node"], *item["path"]]:
            for evidence in row["evidence"]:
                value = docs[evidence["source_id"]]
                if evidence["pointer"]:
                    for part in evidence["pointer"][1:].split("/"):
                        part = part.replace("~1", "/").replace("~0", "~")
                        value = value[int(part)] if isinstance(value, list) else value[part]
                assert value is not None
        assert item["physics_verified"] is False
        assert item["execution_authorized"] is False
        assert {s["id"] for s in item["sources"]} >= {e["source_id"] for r in [item["node"], *item["path"]] for e in r["evidence"]}


def test_code_and_workspace_have_retrievable_revision_or_uri():
    graph = build_graph(chain())
    result = graph.query(GraphQuery("published_artifacts", "analysis:SEARCH-A", max_hops=8))
    assert any(r["node"]["attributes"].get("path") == "analyses/selection_a.cc" for r in result["results"])
    assert any(r["node"]["attributes"].get("uri") == "https://example.invalid/release/fit.json" for r in result["results"])
    impl = graph.query(GraphQuery("implementations", "inspire:9901"))
    assert ids(impl) == {"implementation:engine-a:selection_a@" + "a" * 40}
    assert impl["results"][0]["node"]["attributes"]["qualification"] == "unknown"
    # Follow only supplied attachment relations: the record reaches the exact
    # implementation through its code attachment, then its statistical release.
    linked = graph.query(GraphQuery("published_artifacts", "hepdata:88001:v3",
        kind="workspace", relation_types=("contains", "has_code", "has_workspace")))
    assert any(r["node"]["attributes"].get("uri") == "https://example.invalid/release/fit.json" for r in linked["results"])


def test_models_are_explicit_candidates_with_conditions():
    graph = build_graph(chain())
    result = graph.query(GraphQuery("models", "analysis:SEARCH-A"))
    assert ids(result) == {"model:model-a", "topology:topology-a"}
    model = next(r["node"] for r in result["results"] if r["node"]["kind"] == "model")
    assert model["attributes"]["conditions"] == {"width": "supplied", "lifetime": "supplied"}


def test_same_title_near_identifier_and_case_do_not_join():
    docs = chain()
    docs.append(source("other", "inspire", {"metadata": {"control_number": 9903,
        "titles": [{"title": "A fictional supplied publication"}], "arxiv_eprints": [{"value": syn.arxiv(2)}]}}))
    graph = build_graph(docs)
    assert not graph.query(GraphQuery("implementations", "inspire:9903"))["results"]
    assert not graph.query(GraphQuery("implementations", "analysis:search-a"))["results"]
    assert not graph.query(GraphQuery("implementations", "inspire:990"))["results"]


@pytest.mark.parametrize("namespace,value,expected", [
    ("inspire", "INSPIRE:9901", "inspire:9901"),
    ("inspire", "ins9901", "inspire:9901"),
    ("arxiv", "arXiv:" + syn.arxiv(1) + "v2", "arxiv:" + syn.arxiv(1) + "v2"),
    ("arxiv", "hep-example/9900001v1", "arxiv:hep-example" + "/9900001v1"),
    ("analysis", "Mixed_Case-A", "analysis:Mixed_Case-A"),
])
def test_only_documented_identifier_normalization(namespace, value, expected):
    assert identifier(namespace, value) == expected


@pytest.mark.parametrize("namespace,value", [("inspire", True), ("inspire", "0099"),
    ("inspire", "9901-extra"), ("arxiv", syn.arxiv(1) + "v0"), ("arxiv", syn.arxiv(1) + " "),
    ("title", "some paper"), ("arxiv", "https://arxiv.org/abs/" + syn.arxiv(1))])
def test_refuse_ambiguous_identifiers(namespace, value):
    with pytest.raises(ValueError):
        identifier(namespace, value)


def test_citation_edges_only_follow_exact_provider_links():
    graph = build_graph(chain())
    related = graph.query(GraphQuery("related_papers", "inspire:9901", relation_types=("cites",)))
    assert ids(related) == {"inspire:9902"}
    assert related["results"][0]["path"][0]["relation"] == "cites"


def test_versions_are_retained_and_no_latest_version_selection():
    docs = chain() + [source("older", "arxiv", {"arxiv_id": syn.arxiv(1) + "v1"})]
    graph = build_graph(docs)
    assert {"arxiv:" + syn.arxiv(1) + "v1", "arxiv:" + syn.arxiv(1) + "v2"} <= {n["id"] for n in graph.to_dict()["nodes"]}
    related = graph.query(GraphQuery("related_papers", "arxiv:" + syn.arxiv(1) + "v1"))
    assert "arxiv:" + syn.arxiv(1) + "v2" not in ids(related)
    versions = [source("table-v2", "hepdata", {"recid": 88001, "version": 2,
        "record": {"inspire_id": 9901}, "data_tables": [{"id": 71, "units": ["other-unit"]}]})]
    tables = build_graph(chain() + versions).query(GraphQuery("published_artifacts", "inspire:9901", kind="table"))
    assert ids(tables) == {"hepdata:88001:v2:table:71", "hepdata:88001:v3:table:71"}


def test_catalogue_publication_urls_join_only_exact_arxiv_identifiers():
    docs = chain()
    doc = deepcopy(docs[3].document)
    del doc["entries"][0]["inspire_id"]
    doc["entries"][0]["publication_urls"] = ["https://arxiv.org/abs/" + syn.arxiv(1), "https://example.invalid/title"]
    graph = build_graph([source("catalogue", "catalogue", doc)])
    assert graph.query(GraphQuery("implementations", "arxiv:" + syn.arxiv(1)))["status"] == "matched"
    assert not any(n["id"].endswith("title") for n in graph.to_dict()["nodes"])


def test_provider_record_links_require_the_exact_host():
    doc = deepcopy(chain()[0].document)
    doc["metadata"]["references"] = [{"record": {"$ref": "https://inspirehepXnet/api/literature/9902"}}]
    graph = build_graph([source("bibliography", "inspire", doc)])
    assert graph.query(GraphQuery("related_papers", "inspire:9901", relation_types=("cites",)))["status"] == "unknown"
    catalogue = deepcopy(chain()[3].document)
    del catalogue["entries"][0]["inspire_id"]
    catalogue["entries"][0]["publication_urls"] = ["https://arxivXorg/abs/" + syn.arxiv(1)]
    graph = build_graph([source("catalogue", "catalogue", catalogue)])
    assert graph.query(GraphQuery("implementations", "arxiv:" + syn.arxiv(1)))["status"] == "unknown"


def test_catalogue_source_file_records_keep_their_content_pins():
    doc = deepcopy(chain()[3].document)
    doc["entries"][0]["source_files"] = [{"path": "analyses/selection_a.cc", "git_blob": "c" * 40,
                                          "git_mode": "100644", "sha256": "d" * 64}]
    graph = build_graph([source("catalogue", "catalogue", doc)])
    code = next(n for n in graph.to_dict()["nodes"] if n["kind"] == "code")
    assert code["attributes"]["path"] == "analyses/selection_a.cc"
    assert code["attributes"]["sha256"] == "d" * 64 and code["attributes"]["git_blob"] == "c" * 40
    for bad in ({"path": "analyses/selection_a.cc", "sha256": "not-a-hash"}, {"git_blob": "c" * 40},
                {"path": "analyses/selection_a.cc", "git_blob": "main"}, {"path": "../escape.cc"}):
        doc["entries"][0]["source_files"] = [bad]
        with pytest.raises(ValueError):
            build_graph([source("catalogue", "catalogue", doc)])


def test_exact_duplicates_coalesce_and_source_order_is_deterministic():
    docs = chain()
    first = build_graph(docs)
    second = build_graph(list(reversed(docs)) + [docs[0]])
    assert first.to_dict() == second.to_dict()
    assert not first.to_dict()["issues"]
    assert len({e["id"] for e in first.to_dict()["edges"]}) == len(first.to_dict()["edges"])


def test_conflicting_aliases_quarantine_both_candidates():
    conflicting = source("conflict", "inspire", {"metadata": {"control_number": 9904,
        "arxiv_eprints": [{"value": syn.arxiv(1)}]}})
    graph = build_graph(chain() + [conflicting])
    assert any(i["kind"] == "conflicting_alias" for i in graph.to_dict()["issues"])
    for key in ("inspire:9901", "inspire:9904", "arxiv:" + syn.arxiv(1), "arxiv:" + syn.arxiv(1) + "v2"):
        assert not graph.query(GraphQuery("published_artifacts", key))["results"]


def test_conflicting_node_metadata_keeps_both_evidence_pointers():
    docs = chain()
    changed = deepcopy(docs[3].document)
    changed["entries"][0]["upstream_status"] = "withdrawn"
    graph = build_graph(docs + [source("second-catalogue", "catalogue", changed)])
    assert any(i["kind"] == "conflicting_node" for i in graph.to_dict()["issues"])
    assert not graph.query(GraphQuery("implementations", "analysis:SEARCH-A"))["results"]
    node = next(n for n in graph.to_dict()["nodes"] if n["kind"] == "implementation")
    assert {e["source_id"] for e in node["evidence"]} >= {"implementations", "second-catalogue"}


def test_forbidden_alias_and_content_copy_cannot_rescue_results():
    docs = chain()
    docs.append(source("copy", "inspire", docs[0].document))
    graph = build_graph(docs)
    for key in ("inspire:9901", "arxiv:" + syn.arxiv(1), "arxiv:" + syn.arxiv(1) + "v2"):
        result = graph.query(GraphQuery("published_artifacts", key), denied_sources=frozenset({"copy"}))
        assert result["status"] == "unknown" and result["results"] == []
        assert "bibliography" not in json.dumps(result)


def test_complete_transitive_derivative_lineage_is_denied_and_returned():
    root = source("root", "arxiv", {"arxiv_id": syn.arxiv(3)})
    middle = source("middle", "arxiv", {"arxiv_id": syn.arxiv(4)}, ("root",))
    leaf = source("leaf", "models", {"models": [{"id": "derived", "analysis_ids": ["SEARCH-A"]}]}, ("middle",))
    graph = build_graph([root, middle, leaf])
    allowed = graph.query(GraphQuery("models", "analysis:SEARCH-A"))
    assert {s["id"] for s in allowed["results"][0]["sources"]} == {"root", "middle", "leaf"}
    assert not graph.query(GraphQuery("models", "analysis:SEARCH-A"), denied_sources=frozenset({"root"}))["results"]


def test_identifier_denial_propagates_through_alias_and_version_edges():
    graph = build_graph(chain())
    for denied in ("inspire:9901", "arxiv:" + syn.arxiv(1), "arxiv:" + syn.arxiv(1) + "v2"):
        assert not graph.query(GraphQuery("published_artifacts", "inspire:9901"),
            denied_identifiers=frozenset({denied}))["results"]


def test_snapshot_and_returned_values_are_defensive_copies():
    snapshot = build_graph(chain()).to_dict()
    graph = LiteratureGraph(snapshot)
    snapshot["nodes"].clear()
    assert graph.query(GraphQuery("implementations", "analysis:SEARCH-A"))["results"]
    result = graph.query(GraphQuery("implementations", "analysis:SEARCH-A"))
    result["results"][0]["node"]["attributes"]["qualification"] = "physics"
    assert graph.query(GraphQuery("implementations", "analysis:SEARCH-A"))["results"][0]["node"]["attributes"]["qualification"] == "unknown"


@pytest.mark.parametrize("mutation", ["hash", "edge", "source", "flags", "duplicate", "field"])
def test_snapshot_tampering_and_structural_failures_refused(mutation):
    snapshot = build_graph(chain()).to_dict()
    if mutation == "hash":
        snapshot["nodes"][0]["attributes"]["bad"] = True
    else:
        if mutation == "edge": snapshot["edges"][0]["target"] = "missing"
        if mutation == "source": snapshot["nodes"][0]["evidence"][0]["source_id"] = "missing"
        if mutation == "flags": snapshot["physics_verified"] = True
        if mutation == "duplicate": snapshot["nodes"].append(snapshot["nodes"][0])
        if mutation == "field": snapshot["query_language"] = "raw"
        snapshot["graph_sha256"] = digest({k: v for k, v in snapshot.items() if k != "graph_sha256"})
    with pytest.raises(ValueError): LiteratureGraph(snapshot)


def test_external_manifest_pin_catches_self_consistently_rehashed_snapshot():
    graph = build_graph(chain())
    snapshot = graph.to_dict()
    snapshot["nodes"][0]["attributes"]["altered"] = True
    snapshot["graph_sha256"] = digest({k: v for k, v in snapshot.items() if k != "graph_sha256"})
    with pytest.raises(ValueError, match="pinned generation"):
        LiteratureGraph(snapshot, expected_sha256=graph.sha256)


def test_loaded_snapshot_rejects_wrong_relation_endpoint_types():
    snapshot = build_graph(chain()).to_dict()
    edge = snapshot["edges"][0]
    edge["relation"] = "version_of"
    edge["source"] = "analysis:SEARCH-A"
    edge["target"] = "inspire:9901"
    edge["id"] = "edge:" + digest([edge["source"], edge["relation"], edge["target"]])
    snapshot["graph_sha256"] = digest({k: v for k, v in snapshot.items() if k != "graph_sha256"})
    with pytest.raises(ValueError, match="endpoint kinds"):
        LiteratureGraph(snapshot)


def test_source_pin_missing_lineage_and_conflicting_source_id_refused():
    doc = chain()[0]
    for sources in ([replace(doc, sha256="0" * 64)], [replace(doc, lineage=("missing",))],
                    [doc, replace(doc, version="other")]):
        with pytest.raises(ValueError): build_graph(sources)


@pytest.mark.parametrize("query", [
    {"operation": "raw_sql", "identifier": "inspire:9901"},
    {"operation": "implementations", "identifier": "inspire:9901", "sql": "SELECT *"},
    {"operation": "implementations", "identifier": "inspire:9901", "max_hops": 999},
    {"operation": "implementations", "identifier": "inspire:9901", "max_results": True},
    {"operation": "implementations", "identifier": "inspire:9901", "relation_types": ["anything"]},
    {"operation": ["implementations"], "identifier": "inspire:9901"},
    {"operation": "implementations", "identifier": "inspire:9901", "kind": []},
    {"operation": "implementations", "identifier": "inspire:9901", "relation_types": [{}]},
])
def test_typed_queries_reject_free_language_and_unbounded_inputs(query):
    with pytest.raises(ValueError): GraphQuery.from_dict(query)


def test_query_hop_result_byte_bounds_and_stable_ties():
    graph = build_graph(chain())
    assert not graph.query(GraphQuery("published_artifacts", "inspire:9901", max_hops=0))["results"]
    small = graph.query(GraphQuery("published_artifacts", "inspire:9901", max_results=1))
    assert len(small["results"]) == 1 and small["truncated"]
    tiny = graph.query(GraphQuery("published_artifacts", "inspire:9901", max_bytes=1024))
    assert len(canonical_bytes(tiny)) <= 1024 and tiny["truncated"]
    assert small == graph.query(GraphQuery.from_dict({"operation": "published_artifacts", "identifier": "inspire:9901", "max_results": 1}))


@pytest.mark.parametrize("doc", [{"recid": 88001, "record": {}},
    {"recid": 88001, "version": 0, "record": {}},
    {"recid": 88001, "version": 1, "record": {"resources": [{"url": "file:///private/item"}]}},
    {"recid": 88001, "version": 1, "record": {"resources": [{"url": "https://example.invalid/a", "kind": "guessed_workspace"}]}}])
def test_hepdata_requires_explicit_versions_and_safe_resource_locators(doc):
    with pytest.raises(ValueError): build_graph([source("tables", "hepdata", doc)])


def test_resource_description_never_implies_a_workspace():
    graph = build_graph([source("tables", "hepdata", {"recid": 88001, "version": 1,
        "record": {"inspire_id": 9901, "resources": [{"url": "https://example.invalid/a",
            "description": "complete statistical workspace"}]}})])
    result = graph.query(GraphQuery("published_artifacts", "inspire:9901"))
    assert {r["node"]["kind"] for r in result["results"]} == {"hepdata_record", "resource"}


def test_oversized_item_does_not_hide_smaller_items():
    doc = {"recid": 88001, "version": 1, "record": {"inspire_id": 9901,
        "resources": [{"url": "https://example.invalid/small"}]},
        "data_tables": [{"id": 71, "qualifiers": [{"value": "large" * 10000}]}]}
    graph = build_graph([source("tables", "hepdata", doc)])
    result = graph.query(GraphQuery("published_artifacts", "inspire:9901", max_bytes=6000))
    assert result["truncated"] and result["results"]
    assert "table" not in {r["node"]["kind"] for r in result["results"]}
    assert any(r["node"]["attributes"].get("uri") == "https://example.invalid/small" for r in result["results"])
    assert len(canonical_bytes(result)) <= 6000


def test_no_shared_backend_expansion_between_unrelated_papers():
    docs = chain()
    doc = deepcopy(docs[3].document)
    doc["entries"].append({**doc["entries"][0], "id": "engine-a:selection_b",
        "inspire_id": 9903, "analysis_ids": ["SEARCH-B"], "source_files": []})
    graph = build_graph([source("catalogue", "catalogue", doc)])
    assert "inspire:9903" not in ids(graph.query(GraphQuery("related_papers", "inspire:9901")))


@pytest.mark.parametrize("kind,doc", [("inspire", {"metadata": {}}), ("arxiv", {}),
    ("catalogue", {"entries": [None]}), ("hepdata", {"recid": 88001, "version": 1, "data_tables": [None]}),
    ("models", {"models": [{"id": "m", "topologies": [None]}]})])
def test_malformed_provider_metadata_has_a_typed_refusal(kind, doc):
    with pytest.raises(ValueError): build_graph([source("malformed", kind, doc)])


def test_mutable_repository_branch_is_not_an_immutable_code_revision():
    doc = deepcopy(chain()[3].document)
    doc["sources"]["engine-a"]["revision"] = "main"
    with pytest.raises(ValueError, match="immutable"):
        build_graph([source("catalogue", "catalogue", doc)])


def test_finite_lineage_cycle_remains_taint_closed():
    first = source("first", "models", {"models": [{"id": "cyclic", "analysis_ids": ["SEARCH-A"]}]}, ("second",))
    second = source("second", "arxiv", {"arxiv_id": syn.arxiv(2)}, ("first",))
    graph = build_graph([first, second])
    allowed = graph.query(GraphQuery("models", "analysis:SEARCH-A"))
    assert {s["id"] for s in allowed["results"][0]["sources"]} == {"first", "second"}
    assert not graph.query(GraphQuery("models", "analysis:SEARCH-A"),
        denied_sources=frozenset({"second"}))["results"]


def test_empty_graph_and_legacy_physics_schema_remain_separate():
    graph = build_graph([])
    assert graph.query(GraphQuery("related_papers", "inspire:9901"))["status"] == "unknown"
    root = Path(__file__).parents[2] / "src/ravel/data/knowledge/schema"
    schema = json.loads((root / "literature-graph.json").read_text())
    assert schema["properties"]["kind"]["const"] == "literature-relations"
    assert "paper" not in json.loads((root / "entry.json").read_text()).get("properties", {}).get("kind", {}).get("enum", [])


def retrieval_request(scope=None):
    return {"schema_version": 1, "operation": "search", "request_id": "request-a",
        "budgets": {"max_tokens": 65536, "max_bytes": 65536, "max_seconds": 100.0, "max_expansions": 100},
        "args": {"query": "supplied selection", "top_k": 3, "mode": "hybrid",
                 "document_scope": scope or [], "filters": {"category": ["category-a"]}}}


def descriptor(name, *, kind="source", receipt=None):
    return {"pin": {"path": "sources/" + name + ".json", "sha256": "d" * 64,
                    "size": 23, "receipt_id": receipt},
            "identifiers": {"source": [name]}, "quantities": [], "classes": ["metadata"], "kind": kind}


def retrieval_bindings(graph):
    sources = [RetrievalSourceBinding(s["id"], s["sha256"], (descriptor(s["id"]),))
               for s in graph.to_dict()["sources"]]
    documents = [RetrievalDocumentBinding("inspire:9901", "document:a", "edition-2", (descriptor("document-a"),))]
    return sources, documents


def retrieval_view(permits=lambda _: True):
    from ravel.workflow.literature_provider import SourceView
    return SourceView("e" * 64, "run-a", "node-a", "reader", 1, permits)


def test_provider_scoping_uses_exact_explicit_identity_and_preserves_selectors():
    from ravel.workflow.literature_provider import validate_request
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    request = retrieval_request()
    before = deepcopy(request)
    result = scope_retrieval(graph, GraphQuery("implementations", "arxiv:" + syn.arxiv(1)), request,
        view=retrieval_view(), source_bindings=sources, document_bindings=documents)
    assert result["status"] == "matched"
    assert result["document_scope"] == [{"document_id": "document:a", "version": "edition-2"}]
    assert validate_request(result["request"]) == result["request"]
    for key in ("query", "filters", "top_k", "mode"):
        assert result["request"]["args"][key] == before["args"][key]
    assert result["request"]["request_id"] == before["request_id"]
    assert result["request"]["budgets"]["max_bytes"] == before["budgets"]["max_bytes"]
    assert result["request"]["budgets"]["max_tokens"] == before["budgets"]["max_tokens"]
    assert result["request"]["budgets"]["max_expansions"] + result["usage"]["expansions"] == before["budgets"]["max_expansions"]
    assert request == before
    assert result["policy_view_sha256"] == "e" * 64
    assert result["matches"][0]["graph_paths"]
    assert all(row["pin"]["sha256"] == "d" * 64 for row in result["matches"][0]["lineage"])
    assert result["physics_verified"] is False and result["execution_authorized"] is False


@pytest.mark.parametrize("existing,expected", [
    ([{"document_id": "document:b", "version": "edition-2"}], []),
    ([{"document_id": "document:a", "version": "edition-1"}], []),
    ([{"document_id": "document:a", "version": "edition-2"}, {"document_id": "document:b", "version": "edition-2"}],
     [{"document_id": "document:a", "version": "edition-2"}]),
])
def test_provider_scoping_intersects_existing_scope_without_widening(existing, expected):
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(existing),
        view=retrieval_view(), source_bindings=sources, document_bindings=documents)
    assert result["document_scope"] == expected
    assert (result["request"] is None) == (not expected)


def test_unknown_graph_and_unbound_documents_never_emit_unrestricted_request():
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    for query, bindings in ((GraphQuery("implementations", "inspire:9909"), documents),
                             (GraphQuery("implementations", "inspire:9901"), [])):
        result = scope_retrieval(graph, query, retrieval_request(), view=retrieval_view(),
            source_bindings=sources, document_bindings=bindings)
        assert result["status"] == "unknown" and result["request"] is None and result["document_scope"] == []


def test_source_view_filters_complete_graph_source_lineage_before_traversal(monkeypatch):
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    called = []
    def permits(row):
        assert set(row) == {"pin", "identifiers", "quantities", "classes", "kind"}
        called.extend(row["identifiers"]["source"])
        return "bibliography" not in row["identifiers"]["source"]
    original = graph.query
    def checked(query, **kwargs):
        assert "bibliography" in kwargs["denied_sources"]
        assert set(s.source_id for s in sources) <= set(called)
        return original(query, **kwargs)
    monkeypatch.setattr(graph, "query", checked)
    result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
        view=retrieval_view(permits), source_bindings=sources, document_bindings=documents)
    assert result["request"] is None
    assert "bibliography" not in json.dumps(result)


def test_missing_graph_source_bindings_fail_closed_and_parent_denials_close():
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    for bindings in ([], [s for s in sources if s.source_id != "bibliography"]):
        result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
            view=retrieval_view(), source_bindings=bindings, document_bindings=documents)
        assert result["request"] is None
    changed = [replace(s, descriptors=(*s.descriptors, descriptor("withheld-parent", kind="extracted", receipt="receipt-a")))
               if s.source_id == "bibliography" else s for s in sources]
    result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
        view=retrieval_view(lambda d: "withheld-parent" not in d["identifiers"]["source"]),
        source_bindings=changed, document_bindings=documents)
    assert result["request"] is None and "withheld-parent" not in json.dumps(result)


def test_forbidden_document_pin_cannot_enter_the_scope():
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
        view=retrieval_view(lambda d: "document-a" not in d["identifiers"]["source"]),
        source_bindings=sources, document_bindings=documents)
    assert result["request"] is None and "document:a" not in json.dumps(result)


def test_conflicting_or_stale_provider_bindings_refused():
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    variants = [([replace(sources[0], source_sha256="0" * 64), *sources[1:]], documents),
        (sources, [replace(documents[0], version=None)]),
        (sources, [replace(documents[0], descriptors=(descriptor("unreceipted", kind="generated"),))]),
        (sources, [documents[0], replace(documents[0], descriptors=(descriptor("other-content"),))])]
    for source_bindings, document_bindings in variants:
        with pytest.raises(ValueError):
            scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
                view=retrieval_view(), source_bindings=source_bindings, document_bindings=document_bindings)


def test_withheld_roster_cannot_be_laundered_through_a_second_document_binding():
    # One provider identity with two rosters is an index inconsistency, whichever
    # roster the policy withholds and in whichever order the bindings arrive.
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    withheld = replace(documents[0], node_id="analysis:SEARCH-A", descriptors=(*documents[0].descriptors,
        descriptor("withheld-parent", kind="extracted", receipt="receipt-a")))
    view = retrieval_view(lambda d: "withheld-parent" not in d["identifiers"]["source"])
    for bindings in ([withheld, documents[0]], [documents[0], withheld]):
        with pytest.raises(ValueError, match="conflicting retrieval document identity"):
            scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
                view=view, source_bindings=sources, document_bindings=bindings)


@pytest.mark.parametrize("operation,args", [
    ("list_papers", {"filters": {}, "limit": 2, "cursor": None}),
    ("get_paper", {"document_id": "document:a", "version": None, "section": None, "page_index": None, "cursor": None, "limit": 2}),
    ("compare_measurements", {"topic": "rate", "groups": ["group-a"], "top_k_per_group": 1, "filters": {}}),
])
def test_scope_is_not_injected_into_closed_nonsearch_operations(operation, args):
    request = {**retrieval_request(), "operation": operation, "args": args}
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    with pytest.raises(ValueError, match="only for provider search"):
        scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), request,
            view=retrieval_view(), source_bindings=sources, document_bindings=documents)


def test_graph_expansions_cannot_spend_the_provider_allowance_twice():
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    request = retrieval_request()
    request["budgets"]["max_expansions"] = 1
    result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), request,
        view=retrieval_view(), source_bindings=sources, document_bindings=documents)
    assert result["status"] == "budget_exhausted" and result["request"] is None
    assert result["usage"]["expansions"] == 1


def test_graph_scope_wall_budget_exhaustion_is_explicit(monkeypatch):
    import ravel.workflow.literature_relations as relations
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    ticks = iter([0.0, 0.1, 101.0])
    monkeypatch.setattr(relations.time, "monotonic", lambda: next(ticks))
    result = scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
        view=retrieval_view(), source_bindings=sources, document_bindings=documents)
    assert result["status"] == "budget_exhausted" and result["request"] is None


def test_graph_scope_callback_error_and_nonboolean_decision_refuse():
    graph = build_graph(chain())
    sources, documents = retrieval_bindings(graph)
    def broken(_): raise RuntimeError("private detail")
    for permits in (broken, lambda _: 1):
        with pytest.raises(ValueError) as error:
            scope_retrieval(graph, GraphQuery("implementations", "inspire:9901"), retrieval_request(),
                view=retrieval_view(permits), source_bindings=sources, document_bindings=documents)
        assert "private detail" not in str(error.value)
