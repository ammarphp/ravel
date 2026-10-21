"""Source-pinned backend inventories; counts describe metadata, not applicability.

A denominator is the population explicitly supplied by one dated upstream list.
Missing entries/mappings remain unknown. Different revisions are separate cohorts;
their union is never advertised as the world's complete analysis population.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any

from .literature_relations import (FLAGS, LiteratureGraph, _text, canonical_bytes,
                                  identifier)

STATUSES = {"listed", "not_listed", "unknown"}
QUALIFICATIONS = {"unknown", "declared", "software", "native", "physics"}
ENTRY_FIELDS = {"member", "analysis_id", "inspire_id", "arxiv_id", "implementation_id",
                "status", "qualification", "signature", "production", "energy", "conditions"}


def _member(value: Any) -> str:
    value = _text(value, 512)
    namespace, sep, raw = value.partition(":")
    if not sep or namespace not in {"analysis", "inspire", "arxiv"} or identifier(namespace, raw) != value:
        raise ValueError("canonical exact population member required")
    return value


def validate_population(document: dict) -> None:
    """Validate supplied inventory metadata, retaining duplicate/conflicting rows."""
    if type(document) is not dict or set(document) != {"backend", "as_of", "revision", "population", "entries"}:
        raise ValueError("closed dated backend population contract required")
    _text(document["backend"], 256); _text(document["revision"], 256)
    if type(document["as_of"]) is not str:
        raise ValueError("ISO inventory date required")
    try:
        if date.fromisoformat(document["as_of"]).isoformat() != document["as_of"]:
            raise ValueError("ISO inventory date required")
    except (TypeError, ValueError) as exc:
        raise ValueError("ISO inventory date required") from exc
    population = document["population"]
    entries = document["entries"]
    if type(population) is not list or len(population) > 50000 or type(entries) is not list or len(entries) > 100000:
        raise ValueError("bounded population and entries required")
    for member in population:
        _member(member)
    members = set(population)
    if len(members) != len(population):
        raise ValueError("duplicate denominator member")
    for row in entries:
        if type(row) is not dict or set(row) - ENTRY_FIELDS or not {"member", "status", "qualification"} <= row.keys():
            raise ValueError("typed coverage entry required")
        member = _member(row["member"])
        if member not in members:
            raise ValueError("entry outside declared denominator")
        if type(row["status"]) is not str or type(row["qualification"]) is not str or row["status"] not in STATUSES or row["qualification"] not in QUALIFICATIONS:
            raise ValueError("coverage status and qualification are distinct closed fields")
        for namespace, field in (("analysis", "analysis_id"), ("inspire", "inspire_id"), ("arxiv", "arxiv_id")):
            if field in row:
                identifier(namespace, row[field])
        # A row must not attach another ID in its own namespace to a member.
        namespace, _, raw = member.partition(":")
        field = {"analysis": "analysis_id", "inspire": "inspire_id", "arxiv": "arxiv_id"}[namespace]
        if field in row and identifier(namespace, row[field]) != member:
            raise ValueError("population member identity conflict")
        for field in ("signature", "production", "energy", "implementation_id"):
            if field in row:
                _text(row[field], 512)
        if "conditions" in row and type(row["conditions"]) is not dict:
            raise ValueError("explicit conditions object required")
        canonical_bytes(row)


@dataclass(frozen=True)
class CoverageQuery:
    backend: str | None = None
    signature: str | None = None
    production: str | None = None
    energy: str | None = None
    max_results: int = 100
    max_bytes: int = 65536

    def validate(self) -> None:
        for value in (self.backend, self.signature, self.production, self.energy):
            if value is not None:
                _text(value, 512)
        if type(self.max_results) is not int or not 1 <= self.max_results <= 500:
            raise ValueError("finite coverage result budget required")
        if type(self.max_bytes) is not int or not 1024 <= self.max_bytes <= 1048576:
            raise ValueError("finite coverage byte budget required")


def coverage_report(graph: LiteratureGraph, query: CoverageQuery, *,
                    denied_sources: frozenset[str] = frozenset(),
                    denied_identifiers: frozenset[str] = frozenset()) -> dict:
    """Count unique, unambiguous rows within each supplied denominator.

    ``not_listed`` is an explicit upstream observation, never unsupported physics.
    An unlisted row, a missing row and a conflicted row have different counts.
    Filters use exact declared fields; absent fields remain unresolved.
    """
    if not isinstance(graph, LiteratureGraph) or not isinstance(query, CoverageQuery):
        raise ValueError("typed graph and coverage query required")
    query.validate()
    for policy in (denied_sources, denied_identifiers):
        if type(policy) is not frozenset or any(type(k) is not str for k in policy):
            raise ValueError("explicit frozen denial set required")
    nodes, _ = graph._view(denied_sources, denied_identifiers)
    cohorts = []
    truncated = False
    for node in sorted(nodes.values(), key=lambda n: n["id"]):
        if node["kind"] != "coverage":
            continue
        doc = node["attributes"]
        validate_population(doc)
        if query.backend is not None and doc["backend"] != query.backend:
            continue
        # A restricted member must not leak through a denominator or a row field.
        identities = set(doc["population"])
        for row in doc["entries"]:
            for ns, field in (("analysis", "analysis_id"), ("inspire", "inspire_id"), ("arxiv", "arxiv_id")):
                if field in row:
                    identities.add(identifier(ns, row[field]))
        if identities & set(denied_identifiers) or any(k in graph._nodes and k not in nodes for k in identities):
            continue
        # Report truncation only when a further qualifying cohort is withheld.
        if len(cohorts) >= query.max_results:
            truncated = True
            break
        by_member: dict[str, list[dict]] = {}
        duplicate_rows = 0
        for row in doc["entries"]:
            variants = by_member.setdefault(row["member"], [])
            if row in variants:
                duplicate_rows += 1
            else:
                variants.append(row)
        counts = {"listed": 0, "not_listed": 0, "unknown": 0, "missing": 0,
                  "conflicted": 0, "filter_unresolved": 0, "filter_excluded": 0,
                  "matched": 0, "mapped_implementation": 0}
        qualifications = {q: 0 for q in sorted(QUALIFICATIONS)}
        members = []
        for member in sorted(doc["population"]):
            variants = by_member.get(member, [])
            if not variants:
                counts["missing"] += 1
                members.append({"member": member, "state": "missing", "variants": []})
                continue
            if len(variants) > 1:
                counts["conflicted"] += 1
                members.append({"member": member, "state": "conflicted", "variants": deepcopy(variants)})
                continue
            row = variants[0]
            filters = {k: getattr(query, k) for k in ("signature", "production", "energy") if getattr(query, k) is not None}
            if any(k not in row for k in filters):
                counts["filter_unresolved"] += 1
                members.append({"member": member, "state": "filter_unresolved", "variants": deepcopy(variants)})
                continue
            if any(row[k] != value for k, value in filters.items()):
                counts["filter_excluded"] += 1
                continue
            counts["matched"] += 1
            counts[row["status"]] += 1
            qualifications[row["qualification"]] += 1
            counts["mapped_implementation"] += int(bool(row.get("implementation_id")))
            members.append({"member": member, "state": row["status"], "variants": deepcopy(variants)})
        cohorts.append({"id": node["id"], "backend": doc["backend"], "as_of": doc["as_of"],
                        "revision": doc["revision"], "denominator": len(doc["population"]),
                        "scope": "supplied_population_only", "counts": counts,
                        "qualifications": qualifications, "duplicate_rows": duplicate_rows,
                        "members": members, "evidence": deepcopy(node["evidence"]),
                        "sources": graph._source_lineage({e["source_id"] for e in node["evidence"]}), **FLAGS})
    result = {"schema_version": 1, "kind": "literature-coverage-result", "graph_sha256": graph.sha256,
              "cohorts": cohorts, "status": "matched" if cohorts else "unknown", "truncated": truncated,
              "applicability": "not_established", **FLAGS}
    while len(canonical_bytes(result)) > query.max_bytes and result["cohorts"]:
        result["cohorts"].pop(); result["truncated"] = True
    if not result["cohorts"]:
        result["status"] = "unknown"
    return result
