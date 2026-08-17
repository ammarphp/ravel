"""shape_fit.py's shape_fit.json machine artifact (Task 3.1, PRODUCT-CONTRACT S6.1).

shape_fit.py used to only PRINT the R5-gate reminder; validate_run_state.py (the lifecycle
validator, next task) needs a machine artifact to key off. These tests pin the two
non-negotiable consistencies the writer must honour:
  - excluded_obs == (mu95_obs < 1)
  - r5_status NEVER defaults to "closed" -- a run earns it only with >=2 in-tolerance
    r5_reference_points (DECISION-SHAPE-FIT.md's R5 gate); a bare synthetic/Gaussian-stand-in
    run is "na", an unclosed reproduction attempt is "held".

Import the module under test by file path, not by package import: the repo root carries a
`py.py` file that shadows the real `py` package pytest depends on internally if the repo root
ends up on sys.path. Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHAPE_FIT_PY = REPO / "trial-runs" / "_infrastructure" / "shape_fit.py"


def _load_shape_fit():
    spec = importlib.util.spec_from_file_location("shape_fit_under_test", SHAPE_FIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_passes_and_writes_json():
    """--selftest (includes checks 5/5b: JSON artifact + R5 closure logic) exits 0."""
    result = subprocess.run([sys.executable, str(SHAPE_FIT_PY), "--selftest"],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "JSON artifact" in result.stdout
    assert "r5_status=na" in result.stdout
    assert "2-in-tol-points=closed, 1-in-tol-point=held" in result.stdout


def _make_fixture(tmp_path, sf):
    import numpy as np
    edges = np.linspace(500.0, 3500.0, 61)
    sqrt_s = 13000.0
    p_true = np.array([2.2e7, 9.5, -4.2, -0.9])
    truth = sf.bkg_binned("dijet4", edges, sqrt_s, p_true)
    truth *= 2.0e5 / truth.sum()
    rng = np.random.default_rng(7)
    counts = rng.poisson(truth).astype(float)
    spec = {"edges": edges.tolist(), "counts": counts.tolist(), "sqrt_s_tev": 13.0,
            "lumi_fb": 139.0, "label": "m_jj [GeV]", "units": "counts"}
    spec_path = tmp_path / "spectrum.json"
    spec_path.write_text(json.dumps(spec))

    sig = sf.gauss_template(edges, 2000.0, 0.05, yield_mu1=150.0)
    tmpl = {"edges": edges.tolist(), "yields": sig.tolist(), "label": "toy signal"}
    sig_path = tmp_path / "signal.json"
    sig_path.write_text(json.dumps(tmpl))
    return spec_path, sig_path


def test_fit_run_writes_shape_fit_json_consistent(tmp_path):
    """A real `fit` CLI run with --out writes shape_fit.json; excluded_obs==(mu95_obs<1);
    r5_status defaults to held (a real, unclosed reproduction attempt) -- never closed."""
    sf = _load_shape_fit()
    spec_path, sig_path = _make_fixture(tmp_path, sf)
    out_stem = tmp_path / "shape_fit"
    result = subprocess.run(
        [sys.executable, str(SHAPE_FIT_PY), "fit",
         "--spectrum", str(spec_path), "--signal", str(sig_path),
         "--bkg-form", "dijet4", "--out", str(out_stem), "--no-lint",
         "--timestamp", "2026-07-08T00:00:00Z"],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

    json_path = tmp_path / "shape_fit.json"
    assert json_path.is_file(), "shape_fit.py did not write shape_fit.json beside --out"
    rec = json.loads(json_path.read_text())

    assert rec["schema_version"] == 1
    assert rec["generated_utc"] == "2026-07-08T00:00:00Z"
    assert rec["generator"] == "shape_fit.py"
    assert rec["stat_mode"] == "shape-fit"
    assert set(rec) >= {"spectrum", "bkg_form", "fit_quality", "signal", "mu95_obs", "mu95_exp",
                        "mu95_exp_band", "excluded_obs", "method", "r5_status", "r5_evidence",
                        "r5_reference_points", "plots", "caveats"}
    assert rec["excluded_obs"] == (rec["mu95_obs"] < 1.0)
    assert rec["r5_status"] in ("held", "na")
    assert rec["r5_status"] != "closed"
    assert rec["r5_reference_points"] == []
    assert rec["plots"]["png"] == str(out_stem) + ".png"
    assert rec["plots"]["pdf"] == str(out_stem) + ".pdf"


def test_gauss_stand_in_is_synthetic_na(tmp_path):
    """--gauss (explicitly 'validation only' in the CLI help) -> r5_status == 'na', never 'held'
    or 'closed', since there is no published target being reproduced."""
    sf = _load_shape_fit()
    spec_path, _ = _make_fixture(tmp_path, sf)
    out_stem = tmp_path / "shape_fit"
    result = subprocess.run(
        [sys.executable, str(SHAPE_FIT_PY), "fit",
         "--spectrum", str(spec_path), "--gauss", "2000,0.05,150",
         "--bkg-form", "dijet4", "--out", str(out_stem), "--no-lint"],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    rec = json.loads((tmp_path / "shape_fit.json").read_text())
    assert rec["r5_status"] == "na"
    assert rec["excluded_obs"] == (rec["mu95_obs"] < 1.0)


def test_r5_points_close_only_with_two_in_tolerance(tmp_path):
    """r5_status reaches 'closed' only when --r5-points supplies >=2 in_tolerance points; one
    in-tolerance point alone stays 'held' (never earns closure by half-measures)."""
    sf = _load_shape_fit()
    spec_path, sig_path = _make_fixture(tmp_path, sf)

    r5_two = tmp_path / "r5_two.json"
    r5_two.write_text(json.dumps([{"mass_gev": 20.0, "in_tolerance": True},
                                   {"mass_gev": 125.0, "in_tolerance": True}]))
    out_stem_closed = tmp_path / "closed_run"
    result = subprocess.run(
        [sys.executable, str(SHAPE_FIT_PY), "fit",
         "--spectrum", str(spec_path), "--signal", str(sig_path),
         "--bkg-form", "dijet4", "--out", str(out_stem_closed), "--no-lint",
         "--r5-points", str(r5_two)],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    rec_closed = json.loads((tmp_path / "closed_run.json").read_text())
    assert rec_closed["r5_status"] == "closed"
    assert len(rec_closed["r5_reference_points"]) == 2

    r5_one = tmp_path / "r5_one.json"
    r5_one.write_text(json.dumps([{"mass_gev": 20.0, "in_tolerance": True}]))
    out_stem_held = tmp_path / "held_run"
    result2 = subprocess.run(
        [sys.executable, str(SHAPE_FIT_PY), "fit",
         "--spectrum", str(spec_path), "--signal", str(sig_path),
         "--bkg-form", "dijet4", "--out", str(out_stem_held), "--no-lint",
         "--r5-points", str(r5_one)],
        cwd=REPO, capture_output=True, text=True)
    assert result2.returncode == 0, result2.stdout + result2.stderr
    rec_held = json.loads((tmp_path / "held_run.json").read_text())
    assert rec_held["r5_status"] == "held"


def test_json_out_path_derivation():
    """_json_out_path handles the stem/dir/full-path forms named in the brief."""
    sf = _load_shape_fit()
    assert sf._json_out_path(None) is None
    assert sf._json_out_path("outputs/shape_fit/shape_fit") == "outputs/shape_fit/shape_fit.json"
    assert sf._json_out_path("outputs/shape_fit/shape_fit.png") == "outputs/shape_fit/shape_fit.json"
    assert sf._json_out_path("outputs/shape_fit/shape_fit.pdf") == "outputs/shape_fit/shape_fit.json"


def test_mu95_exp_band_consistency_enforced():
    """A malformed mu95_exp_band (wrong length / not ascending / median != mu95_exp) is rejected."""
    sf = _load_shape_fit()
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "x.json")
        try:
            sf.write_shape_fit_json(
                out, spectrum_label="m", n_bins=10, edge_lo=0.0, edge_hi=1.0, lumi_fb=None,
                bkg_form="dijet4", chi2=1.0, ndf=6, sig_label="x", sig_yield_mu1=1.0,
                mu95_obs=0.5, mu95_exp=0.6, mu95_exp_band=[0.4, 0.45, 0.55, 0.7, 0.8],
                r5_points=[], is_synthetic=True, png_path=None, pdf_path=None, timestamp="")
            raised = False
        except ValueError:
            raised = True
        assert raised, "median(mu95_exp_band) != mu95_exp must be rejected"
