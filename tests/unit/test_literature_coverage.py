"""Fictional, dated denominator and metadata-qualification controls."""
import synthetic_identifiers as syn
from copy import deepcopy

import pytest

from ravel.workflow.literature_coverage import (
    CoverageQuery, coverage_report, validate_population,
)
from ravel.workflow.literature_relations import (
    GraphQuery, SourceDocument, build_graph, canonical_bytes, digest,
)


def population():
    return {"backend": "engine-a", "as_of": "2099-01-01", "revision": "revision-a",
        "population": ["analysis:SEARCH-A", "analysis:SEARCH-B", "analysis:SEARCH-C", "analysis:SEARCH-D"],
        "entries": [
            {"member": "analysis:SEARCH-A", "analysis_id": "SEARCH-A", "inspire_id": 9901,
             "implementation_id": "engine-a:selection_a", "status": "listed", "qualification": "software",
             "signature": "signature-a", "production": "production-a", "energy": "energy-a",
             "conditions": {"source_scope": "supplied"}},
            {"member": "analysis:SEARCH-B", "analysis_id": "SEARCH-B", "status": "not_listed", "qualification": "unknown"},
            {"member": "analysis:SEARCH-C", "analysis_id": "SEARCH-C", "status": "unknown", "qualification": "declared"},
        ]}


def source(doc, name="inventory", lineage=()):
    return SourceDocument(name, "coverage", "https://example.invalid/" + name,
        "snapshot-1", digest(doc), doc, lineage)


def report(doc=None, query=None):
    return coverage_report(build_graph([source(doc or population())]), query or CoverageQuery())


def test_explicit_denominator_counts_do_not_promote_qualification():
    result = report()
    cohort = result["cohorts"][0]
    assert cohort["denominator"] == 4
    assert cohort["counts"] == {"listed": 1, "not_listed": 1, "unknown": 1, "missing": 1,
        "conflicted": 0, "filter_unresolved": 0, "filter_excluded": 0, "matched": 3, "mapped_implementation": 1}
    assert cohort["qualifications"]["software"] == 1
    assert cohort["qualifications"]["physics"] == 0
    assert result["applicability"] == "not_established"
    assert cohort["scope"] == "supplied_population_only"
    assert cohort["sources"][0]["sha256"] == digest(population())
    assert result["physics_verified"] is False and cohort["physics_verified"] is False


def test_missing_population_member_remains_missing_not_unsupported():
    cohort = report()["cohorts"][0]
    member = next(r for r in cohort["members"] if r["member"] == "analysis:SEARCH-D")
    assert member == {"member": "analysis:SEARCH-D", "state": "missing", "variants": []}
    assert "unsupported" not in canonical_bytes(cohort).decode()


def test_duplicate_rows_count_once_and_conflicts_retain_variants():
    doc = population()
    doc["entries"].append(deepcopy(doc["entries"][0]))
    doc["entries"].append({**doc["entries"][0], "status": "not_listed"})
    cohort = report(doc)["cohorts"][0]
    assert cohort["duplicate_rows"] == 1
    assert cohort["denominator"] == 4
    assert cohort["counts"]["conflicted"] == 1 and cohort["counts"]["listed"] == 0
    member = next(r for r in cohort["members"] if r["state"] == "conflicted")
    assert {v["status"] for v in member["variants"]} == {"listed", "not_listed"}


def test_revision_and_backend_denominators_are_never_pooled():
    one = population()
    two = {**population(), "backend": "engine-b", "revision": "revision-b"}
    three = {**population(), "as_of": "2099-02-01", "revision": "revision-c"}
    graph = build_graph([source(one, "a"), source(two, "b"), source(three, "c")])
    all_cohorts = coverage_report(graph, CoverageQuery())["cohorts"]
    assert len(all_cohorts) == 3
    assert {r["revision"] for r in all_cohorts} == {"revision-a", "revision-b", "revision-c"}
    selected = coverage_report(graph, CoverageQuery(backend="engine-a"))["cohorts"]
    assert len(selected) == 2 and all(r["denominator"] == 4 for r in selected)
    assert coverage_report(graph, CoverageQuery(backend="ENGINE-A"))["status"] == "unknown"


def test_filters_are_exact_and_missing_metadata_is_unresolved():
    cohort = report(query=CoverageQuery(signature="signature-a", production="production-a", energy="energy-a"))["cohorts"][0]
    assert cohort["counts"]["matched"] == 1
    assert cohort["counts"]["filter_unresolved"] == 2
    assert cohort["counts"]["missing"] == 1
    mismatch = report(query=CoverageQuery(energy="ENERGY-A"))["cohorts"][0]
    assert mismatch["counts"]["matched"] == 0
    assert mismatch["counts"]["filter_excluded"] == 1
    assert mismatch["denominator"] == 4


def test_exact_publication_and_analysis_coverage_joins():
    graph = build_graph([source(population())])
    for key in ("analysis:SEARCH-A", "inspire:9901", "backend:engine-a"):
        result = graph.query(GraphQuery("coverage", key))
        assert len(result["results"]) == 1
        assert result["results"][0]["node"]["attributes"]["population"] == population()["population"]
    assert graph.query(GraphQuery("coverage", "inspire:9902"))["status"] == "unknown"


def test_member_identity_joins_without_redundant_mapping_field():
    doc = population()
    del doc["entries"][0]["analysis_id"]
    graph = build_graph([source(doc)])
    assert graph.query(GraphQuery("coverage", "analysis:SEARCH-A"))["status"] == "matched"


def test_explicit_population_crosswalk_joins_to_a_separate_implementation():
    doc = population()
    doc["entries"][0]["arxiv_id"] = syn.arxiv(1) + "v2"
    catalogue = {"sources": {"engine-a": {"revision": "a" * 40, "repository": "https://example.invalid/repo"}},
        "entries": [{"id": "engine-a:selection_a", "framework": "engine-a", "analysis_ids": ["SEARCH-A"]}]}
    impl = SourceDocument("code", "catalogue", "https://example.invalid/code", "v1", digest(catalogue), catalogue)
    graph = build_graph([source(doc), impl])
    result = graph.query(GraphQuery("implementations", "inspire:9901"))
    assert len(result["results"]) == 1
    assert result["results"][0]["node"]["id"] == "implementation:engine-a:selection_a@" + "a" * 40
    assert graph.query(GraphQuery("implementations", "arxiv:" + syn.arxiv(1)))["status"] == "matched"


def test_denied_sources_and_identifiers_do_not_leak_in_denominators():
    graph = build_graph([source(population())])
    assert not coverage_report(graph, CoverageQuery(), denied_sources=frozenset({"inventory"}))["cohorts"]
    for denied in ("analysis:SEARCH-A", "analysis:SEARCH-D", "inspire:9901"):
        result = coverage_report(graph, CoverageQuery(), denied_identifiers=frozenset({denied}))
        assert result["cohorts"] == [] and result["status"] == "unknown"
        assert denied not in canonical_bytes(result).decode()
        generic = graph.query(GraphQuery("coverage", "backend:engine-a"), denied_identifiers=frozenset({denied}))
        assert generic["results"] == []
        assert denied not in canonical_bytes(generic).decode()


def test_inventory_derivative_lineage_and_content_copies_filtered():
    root_doc = {"arxiv_id": syn.arxiv(1)}
    root = SourceDocument("root", "arxiv", "https://example.invalid/root", "v1", digest(root_doc), root_doc)
    graph = build_graph([root, source(population(), lineage=("root",)), source(population(), "copy", ("root",))])
    assert not coverage_report(graph, CoverageQuery(), denied_sources=frozenset({"root"}))["cohorts"]
    assert not coverage_report(graph, CoverageQuery(), denied_sources=frozenset({"copy"}))["cohorts"]
    for cohort in coverage_report(graph, CoverageQuery())["cohorts"]:
        assert "root" in {s["id"] for s in cohort["sources"]}


@pytest.mark.parametrize("change", [
    {"as_of": "20990101"}, {"as_of": "invalid"}, {"revision": ""},
    {"population": ["analysis:SEARCH-A", "analysis:SEARCH-A"]},
    {"population": ["inspire:099"]},
    {"entries": [{"member": "analysis:SEARCH-X", "status": "listed", "qualification": "unknown"}]},
    {"entries": [{"member": "analysis:SEARCH-A", "status": "unsupported", "qualification": "unknown"}]},
    {"entries": [{"member": "analysis:SEARCH-A", "status": "listed", "qualification": "certified"}]},
    {"entries": [{"member": "analysis:SEARCH-A", "analysis_id": "SEARCH-B", "status": "listed", "qualification": "unknown"}]},
    {"entries": [{"member": "analysis:SEARCH-A", "status": "listed", "qualification": "unknown", "physics_verified": True}]},
])
def test_malformed_or_overclaimed_populations_refused(change):
    doc = {**population(), **change}
    with pytest.raises(ValueError): validate_population(doc)
    with pytest.raises(ValueError): build_graph([source(doc)])


@pytest.mark.parametrize("query", [CoverageQuery(max_results=0), CoverageQuery(max_bytes=100),
    CoverageQuery(max_results=True), CoverageQuery(energy=13)])
def test_untyped_or_unbounded_queries_refused(query):
    with pytest.raises(ValueError): report(query=query)


def test_result_byte_and_cohort_bounds_are_reported():
    tiny = report(query=CoverageQuery(max_bytes=1024))
    assert tiny["truncated"] and len(canonical_bytes(tiny)) <= 1024
    assert not tiny["cohorts"] and tiny["status"] == "unknown"
    graph = build_graph([source(population(), "a"), source({**population(), "revision": "other"}, "b")])
    capped = coverage_report(graph, CoverageQuery(max_results=1))
    assert len(capped["cohorts"]) == 1 and capped["truncated"]
    exact = coverage_report(build_graph([source(population())]), CoverageQuery(max_results=1))
    assert len(exact["cohorts"]) == 1 and exact["truncated"] is False
    filtered = coverage_report(build_graph([source(population(), "a"), source({**population(), "backend": "engine-b"}, "b")]),
                               CoverageQuery(backend="engine-a", max_results=1))
    assert len(filtered["cohorts"]) == 1 and filtered["truncated"] is False


def test_empty_denominator_is_explicit_and_not_a_completeness_claim():
    doc = {**population(), "population": [], "entries": []}
    result = report(doc)
    assert result["cohorts"][0]["denominator"] == 0
    assert result["cohorts"][0]["scope"] == "supplied_population_only"


def test_caller_mutation_cannot_change_a_coverage_result():
    doc = population()
    graph = build_graph([source(doc)])
    doc["population"].clear()
    result = coverage_report(graph, CoverageQuery())
    result["cohorts"][0]["members"].clear()
    assert len(coverage_report(graph, CoverageQuery())["cohorts"][0]["members"]) == 4
