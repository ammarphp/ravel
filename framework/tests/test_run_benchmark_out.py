"""framework/benchmark/run_benchmark.py must not clobber the tracked results.json by default
(Task 1.2, write-suppression only). run_benchmark.py used to default --out to the TRACKED
framework/benchmark/results.json and overwrite it on EVERY run (even --fast) — a verification run
dirtied a committed baseline. This pins the fix: the default --out target is a gitignored scratch
path (framework/benchmark/.work/results.latest.json); refreshing the tracked baseline requires the
explicit --update-baseline flag (or an explicit --out pointing at the tracked file). This is NOT a
new diff-and-fail gate — the existing exit-1 mu95/tier gate is untouched and out of scope here.

Argparse introspection only: no pyhf/conda, no physics run. Run from a clean cwd to dodge the
repo-root py.py shadow: `cd /tmp && python3 -m pytest <this file, abs path> -q`.
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN_BENCHMARK_PY = REPO / "framework" / "benchmark" / "run_benchmark.py"
TRACKED_RESULTS = REPO / "framework" / "benchmark" / "results.json"


def _load_module():
    """Load run_benchmark.py by path (not `import run_benchmark`) so this works regardless of
    cwd/sys.path — in particular from the clean /tmp cwd this test is meant to run from."""
    spec = importlib.util.spec_from_file_location("run_benchmark", RUN_BENCHMARK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_out_is_gitignored_scratch_not_tracked_baseline():
    mod = _load_module()
    parser = mod.build_parser()
    # --fast satisfies the pre-existing required mutually-exclusive selection group
    # (--fast/--full/--case); it is orthogonal to the --out default under test here.
    args = parser.parse_args(["--fast"])
    assert args.out.endswith(".work/results.latest.json"), args.out
    assert Path(args.out) != TRACKED_RESULTS
    assert Path(args.out).parent.name == ".work"
    assert not args.update_baseline


def test_update_baseline_flag_resolves_to_tracked_results_json():
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(["--fast", "--update-baseline"])
    assert args.update_baseline
    resolved = mod.resolve_out(args)
    assert Path(resolved) == TRACKED_RESULTS


def test_explicit_out_still_works_even_without_update_baseline():
    """An explicit --out pointing at the tracked path must still write there (requirement:
    'an explicit --out framework/benchmark/results.json must also still work')."""
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(["--fast", "--out", str(TRACKED_RESULTS)])
    resolved = mod.resolve_out(args)
    assert Path(resolved) == TRACKED_RESULTS


def test_no_update_baseline_no_explicit_out_keeps_scratch_default():
    mod = _load_module()
    parser = mod.build_parser()
    args = parser.parse_args(["--fast"])
    resolved = mod.resolve_out(args)
    assert Path(resolved) == REPO / "framework" / "benchmark" / ".work" / "results.latest.json"
