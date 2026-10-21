"""Registered manuscript construction preserves both procedure-note routes."""
from contextlib import nullcontext

import pytest

from ravel.controller.routes.manuscript import staged
from ravel.workflow import graph_substrate as gs


@pytest.mark.parametrize("bound", [False, True])
def test_registered_manuscript_build_preserves_procedure_note_routing(tmp_path, bound):
    ctx = gs._context(tmp_path, "manuscript.build", {"request_id": "synthetic_note"})
    binding = staged.Binding(object(), tmp_path, {}, "synthetic_step")
    with staged.services(binding) if bound else nullcontext():
        compiled = gs.build("manuscript.build", ctx)
        assert gs.lint_graph(compiled) == []
        assert compiled.structure_sha256 == ctx.row["structure_sha256"]
        builder = compiled.builder
        assert {"note_assembly", "procedure_note", "procedure_export"} <= set(builder.nodes)
        assert ("note_assembly", "procedure_note") in builder.edges
        assert ("procedure_export", "checkin3") in builder.edges
        exported = builder.nodes["procedure_export"].metadata
        assert exported["ravel_kind"] == "effect"
        assert exported["gate"] == "report_integrity"
        graph = compiled.get_graph()
        assert any(edge.source == "note_assembly" and edge.target == "procedure_note" for edge in graph.edges)
        for source, targets, expected in (
            ("profile", {"note": "note_assembly", "full": "story"}, "note_assembly" if bound else "story"),
            ("procedure_note", {"controller": "__end__", "full": "procedure_export"},
             "__end__" if bound else "procedure_export"),
        ):
            branches = list(builder.branches[source].values())
            assert len(branches) == 1
            branch = branches[0]
            assert branch.ends == targets
            # Evaluate only the pure router; graph nodes and their effects stay idle.
            assert branch.ends[branch.path.func({})] == expected
