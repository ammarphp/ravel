import importlib.util
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/scan_babysitter.py"

def _load():
    spec = importlib.util.spec_from_file_location("scan_babysitter_uut", SCRIPT)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def test_live_points_detects_fractional_dm_short_and_full():
    mod = _load()
    ps = ("99999 python /r/trial-runs/2026_sleptonscan_m150_dm2p5/output/"
          "native_simpleanalysis.py --input x\n")
    live = mod.live_points(ps_output=ps)
    assert "m150_dm2p5" in live          # short manifest tag (was missed: \\d+ rejects 'p')
    assert "sleptonscan_m150_dm2p5" in live

def test_stall_heal_guard_protects_live_and_fresh():
    mod = _load()
    now = 1_000_000.0
    stale = now - 40 * 60      # 40 min old STATUS mtime
    fresh = now - 60
    assert mod.stall_heal_due(stale, "m150_dm2p5", set(), now, 25.0) is True         # dead+stale -> heal
    assert mod.stall_heal_due(stale, "m150_dm2p5", {"m150_dm2p5"}, now, 25.0) is False  # LIVE -> protected
    assert mod.stall_heal_due(fresh, "m150_dm2p5", set(), now, 25.0) is False         # fresh -> no heal
