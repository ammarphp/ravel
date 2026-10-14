"""Real-upstream control: load a user-supplied AgentRivet checkout under the guard.

Set RAVEL_AGENTRIVET_UPSTREAM to a checkout of an allowed commit (the
agent-rivet-0.2.0 tag is the default pin). No upstream file is copied into RAVEL;
the test reads the supplied tree, admits its census, loads core, roles and Memory
from admitted buffers, checks the loaded bindings and constructs the original
ReviewLoop with inert agents. No provider, SDK, compiler or network is used.
The pinned core does not import ``utils``, so arxiv, pypdf and requests are not
needed; pydantic is a RAVEL dependency.
"""
import hashlib
import os
from pathlib import Path
import pytest
from ravel.workflow import agentrivet_construction as construction, agentrivet_pins, agentrivet_runtime

UPSTREAM = os.environ.get("RAVEL_AGENTRIVET_UPSTREAM")
pytestmark = pytest.mark.skipif(
    not UPSTREAM, reason="RAVEL_AGENTRIVET_UPSTREAM names no user-supplied AgentRivet checkout "
                         "(GPL source is never bundled; CI has none)")


def census(root):
    names = sorted(p.relative_to(root).as_posix() for p in (root / "agentrivet").rglob("*.py"))
    names += [n for n in ("pyproject.toml", "COPYING", "README.md") if (root / n).is_file()]
    return [{"path": n, "sha256": hashlib.sha256((root / n).read_bytes()).hexdigest()} for n in names]


def test_real_upstream_tree_is_admitted_loaded_and_bound_without_processes():
    root = Path(UPSTREAM).resolve()
    rows = census(root)
    commit = agentrivet_pins.admit_census(rows)
    assert commit in agentrivet_pins.ALLOWED
    construction._source(root, rows)
    request = {"upstream": {"root": str(root), "files": rows}}
    with construction._modules(request) as (core, roles, memory, pins, memory_pin):
        receipt = agentrivet_runtime.inspect_binding(core, roles, source_pins=pins)
        assert commit in receipt["upstream_role_commits"]
        assert commit in agentrivet_pins.admit_member_pins({"memory": memory_pin})
        inert = object()
        with agentrivet_pins.no_subprocess("real-upstream control"):
            loop = core.ReviewLoop(inert, inert, inert, inert, max_iterations=1)
        assert loop.max_iterations == 1
        assert hasattr(memory, "Memory")


def test_real_compile_gated_upstream_routes_compilation_through_ravel(tmp_path, monkeypatch):
    root = Path(UPSTREAM).resolve()
    rows = census(root)
    commit = agentrivet_pins.admit_census(rows)
    if not agentrivet_pins.features(commit)["compile_gate"]:
        pytest.skip("the supplied checkout has no in-loop compile gate")
    monkeypatch.chdir(tmp_path)

    class Session:
        def __init__(self):
            self.seen = []

        def build_result(self, code):
            self.seen.append(code)
            return 1, "draft.cc:3:5: error: unknown type name 'Histo1DPtr2'"

    session = Session()
    request = {"upstream": {"root": str(root), "files": rows}, "construction": {"checks": {"declared": True}}}
    with construction._modules(request) as (core, roles, memory, pins, memory_pin):
        inert = object()
        with agentrivet_pins.no_subprocess("real-upstream control"):
            loop = core.ReviewLoop(inert, inert, inert, inert, max_iterations=1)
        assert loop.compiler is True                       # RAVEL's declared checks, not `import rivet`
        original = core.build_routine
        with pytest.raises(agentrivet_pins.UpstreamExecutionRefused):
            with agentrivet_pins.no_subprocess("unaccounted upstream compile"):
                original("int main(){}")                   # upstream writes in cwd and spawns rivet-build
        with agentrivet_runtime.bind_compile(core, session):
            with agentrivet_pins.no_subprocess("real-upstream control"):
                result = core.build_routine("int main(){}")
        assert core.build_routine is original
        assert result.returncode == 1 and not result.success and "unknown type name" in result.output
        assert session.seen == ["int main(){}"]
    assert not list(tmp_path.iterdir())
