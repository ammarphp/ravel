#!/usr/bin/env python
"""shape_fit -- the SCOPED binned-template fit engine (Option B, DECISION-SHAPE-FIT.md; CR-027).

Scope (deliberately narrow -- the decision memo's terms):
  * ONE observable, binned spectrum (m_jj, m_jjgamma, m_tt, ...), counts per bin.
  * Background = the analysis's own smoothly-falling FUNCTIONAL FAMILY, refit here with all
    shape parameters PROFILED in the S+B fit (never a frozen background subtraction).
  * Signal = a binned template (from our generation) or a Gaussian stand-in (validation).
  * Limit = 95% CL upper limit on the signal strength mu via the standard ASYMPTOTIC CLs
    construction (Cowan-Cranmer-Gross-Vitells): q_mu on data + the background-Asimov,
    CLs = p_{s+b}/(1-p_b), bisected to CLs = 0.05. Expected limit + band from the Asimov.
  * NON-NEGOTIABLE R5 GATE (the memo + verification-ladder): no reinterpretation number ships
    until the engine reproduces the target paper's own published limit at >=2 mass points
    within a stated tolerance. This tool prints that reminder on every non-selftest run.

Hard boundaries (refuse, don't improvise): signal-background INTERFERENCE (trap T1) is out of
scope; correlated systematics beyond a single overall signal-normalization nuisance are out of
scope unless the paper publishes them (say so in the basis manifest).

Spectrum JSON schema: {"edges": [..N+1..], "counts": [..N..], "sqrt_s_tev": 13.0,
                       "lumi_fb": 139.0, "label": "m_jjgamma [GeV]"}
Signal template JSON:  {"edges": [same], "yields": [..N.. at mu=1], "label": "..."}
(edges must MATCH; the tool refuses to rebin silently.)

Background families (--bkg-form):
  dijet3:  f(x) = p0 * (1-x)^p1 * x^p2                 x = m/sqrt(s)
  dijet4:  f(x) = p0 * (1-x)^p1 * x^(p2 + p3*ln x)     (the standard 4-par dijet function)
Integrated per bin by midpoint*width (adequate for smooth f and the bin counts here; the
fit-quality line reports chi2/ndf so a bad approximation is visible, not silent).

Usage:
  shape_fit.py fit --spectrum spec.json (--signal tmpl.json | --gauss M0,RELW)
               [--bkg-form dijet4] [--range LO,HI] [--out stem] [--no-lint]
  shape_fit.py --selftest        # synthetic known-answer checks (deterministic, seeded)
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse
import json
import math
import os
import sys

import numpy as np




# ---------------------------------------------------------------- background families
def bkg_families():
    def dijet3(x, p):
        return p[0] * (1 - x) ** p[1] * x ** p[2]

    def dijet4(x, p):
        return p[0] * (1 - x) ** p[1] * x ** (p[2] + p[3] * np.log(x))

    return {"dijet3": (dijet3, 3), "dijet4": (dijet4, 4)}


FIXED_BKG = None      # optional additive, NON-fitted background component (e.g. the paper's
                      # resonant W/Z/ttbar templates) — set via --fixed-bkg; added everywhere
                      # the smooth family is evaluated, so the smooth fit absorbs ONLY the
                      # non-resonant part (faithful to analyses that fit smooth + resonant MC)
TEMPLATE_BKG = None   # --bkg-form template: the paper's own published background SHAPE (e.g. its
                      # post-fit non-resonant column) modulated by exp(sum_k c_k u^k) — a
                      # standard transfer-function fit. params p = [norm, c1..cK]; K =
                      # --bkg-order. K matters PHYSICALLY: too rigid a background cannot absorb
                      # localized bumps and yields ANTI-CONSERVATIVE limits (measured live:
                      # norm+tilt gave 3-10x tighter than the published limits on ins2813982);
                      # match K to the flexibility of the paper's own fit family.
TEMPLATE_ORDER = 1    # K (set via --bkg-order)
SYST = None           # optional per-bin ABSOLUTE background uncertainty (the paper's published
                      # envelope): switches the NLL to Gaussian with var = max(N,1) + syst^2 —
                      # the large-N scoped stand-in for per-bin constrained NPs.


def bkg_binned(form, edges, sqrt_s_gev, p):
    if form == "template":
        n = len(edges) - 1
        u = (np.arange(n) - (n - 1) / 2.0) / max(n - 1, 1)      # [-0.5, 0.5] across bins
        mod = np.zeros(n)
        for k in range(1, TEMPLATE_ORDER + 1):
            mod = mod + p[k] * u ** k
        smooth = np.clip(p[0] * TEMPLATE_BKG * np.exp(np.clip(mod, -20, 20)), 1e-12, None)
    else:
        f, _n = bkg_families()[form]
        mid = 0.5 * (edges[:-1] + edges[1:]) / sqrt_s_gev
        w = np.diff(edges) / sqrt_s_gev
        smooth = np.clip(f(mid, p) * w, 1e-12, None)
    if FIXED_BKG is not None:
        return smooth + FIXED_BKG
    return smooth


def _npar(form):
    return (1 + TEMPLATE_ORDER) if form == "template" else bkg_families()[form][1]


# ---------------------------------------------------------------- likelihood machinery
def nll(counts, expected):
    if SYST is not None:                          # Gaussian w/ published per-bin envelope
        var = np.clip(counts, 1.0, None) + SYST ** 2
        return float(0.5 * np.sum((counts - expected) ** 2 / var))
    return float(np.sum(expected - counts * np.log(expected)))


def fit_bkg(counts, edges, sqrt_s, form, p0=None):
    """Background-only ML fit. Deterministic multi-start on the seed guess."""
    from scipy.optimize import minimize
    npar = _npar(form)
    tot = max(counts.sum(), 1.0)
    guesses = []
    if form == "template":
        base = [1.0] + [0.0] * TEMPLATE_ORDER
    else:
        base = [tot, 10.0, -4.0, -1.0][:npar]
    if p0 is not None:
        guesses.append(np.asarray(p0, float))
    for s1 in (1.0, 0.3, 3.0):
        g = np.array(base, float)
        g[0] *= s1
        guesses.append(g)
    best = None
    for g in guesses:
        # fit log(p0) for positivity; other params free
        def obj(q):
            p = np.array(q, float)
            p[0] = math.exp(p[0])
            return nll(counts, bkg_binned(form, edges, sqrt_s, p))
        q0 = np.array(g, float)
        q0[0] = math.log(max(g[0], 1e-6))
        r = minimize(obj, q0, method="Nelder-Mead",
                     options={"maxiter": 20000, "xatol": 1e-6, "fatol": 1e-6})
        if r.success and np.isfinite(r.fun) and np.all(np.isfinite(r.x)):
            if best is None or r.fun < best.fun:
                best = r
    if best is None:
        raise RuntimeError("shape background optimizer did not converge to a finite solution")
    p = np.array(best.x, float)
    p[0] = math.exp(p[0])
    return p, float(best.fun)


def fit_mu_profiled(counts, edges, sqrt_s, form, sig, mu_fixed=None, p0=None):
    """S+B ML fit; background params ALWAYS profiled; mu fixed or floating (>= 0)."""
    from scipy.optimize import minimize
    npar = _npar(form)

    def unpack(q):
        p = np.array(q[:npar], float)
        p[0] = math.exp(p[0])
        return p

    def obj_fixed(q):
        exp = bkg_binned(form, edges, sqrt_s, unpack(q)) + mu_fixed * sig
        return nll(counts, np.clip(exp, 1e-12, None))

    def obj_float(q):
        mu = max(q[npar], 0.0)
        exp = bkg_binned(form, edges, sqrt_s, unpack(q)) + mu * sig
        return nll(counts, np.clip(exp, 1e-12, None))

    pb = p0 if p0 is not None else fit_bkg(counts, edges, sqrt_s, form)[0]
    q0 = np.array(list(pb) + ([] if mu_fixed is not None else [0.1]), float)
    q0[0] = math.log(max(pb[0], 1e-6))
    r = minimize(obj_fixed if mu_fixed is not None else obj_float, q0,
                 method="Nelder-Mead",
                 options={"maxiter": 40000, "xatol": 1e-6, "fatol": 1e-6})
    if not r.success or not np.isfinite(r.fun) or not np.all(np.isfinite(r.x)):
        raise RuntimeError("shape profile optimizer did not converge to a finite solution")
    if mu_fixed is not None:
        return float(r.fun), unpack(r.x), mu_fixed
    return float(r.fun), unpack(r.x), max(float(r.x[npar]), 0.0)


def qmu(counts, edges, sqrt_s, form, sig, mu):
    """One-sided test statistic q_mu (mu_hat clipped to [0, mu])."""
    nll_free, pb, mu_hat = fit_mu_profiled(counts, edges, sqrt_s, form, sig)
    if mu_hat > mu:                       # by construction q_mu = 0 above mu_hat
        return 0.0, mu_hat
    nll_fix, _, _ = fit_mu_profiled(counts, edges, sqrt_s, form, sig, mu_fixed=mu, p0=pb)
    return max(0.0, 2.0 * (nll_fix - nll_free)), mu_hat


def cls_at_mu(counts, asimov, edges, sqrt_s, form, sig, mu):
    """Asymptotic CLs (Cowan et al.): p_sb/(1-p_b) from q_mu(data) and q_mu(Asimov)."""
    from scipy.stats import norm
    q_obs, _ = qmu(counts, edges, sqrt_s, form, sig, mu)
    q_A, _ = qmu(asimov, edges, sqrt_s, form, sig, mu)
    rq, rqa = math.sqrt(max(q_obs, 0.0)), math.sqrt(max(q_A, 0.0))
    p_sb = 1.0 - norm.cdf(rq)
    one_m_pb = norm.cdf(rqa - rq)
    return (p_sb / one_m_pb) if one_m_pb > 1e-12 else 0.0


def upper_limit(counts, edges, sqrt_s, form, sig, cl=0.05, mu_hi0=1.0, *, details=False):
    """Finite converged profile fits plus a verified CLs crossing; no calibration claim."""
    if not (math.isfinite(cl) and 0 < cl < 1 and math.isfinite(mu_hi0) and mu_hi0 > 0):
        raise ValueError("limit level and initial bracket must be finite and positive")
    pb, _ = fit_bkg(counts, edges, sqrt_s, form)
    asimov = bkg_binned(form, edges, sqrt_s, pb)

    def evaluate(mu):
        value = cls_at_mu(counts, asimov, edges, sqrt_s, form, sig, mu)
        if not math.isfinite(value) or value < 0:
            raise RuntimeError("shape CLs evaluation is non-finite or negative")
        return value

    lo, hi = 0.0, mu_hi0
    low_cls = evaluate(lo)
    if low_cls < cl:
        raise RuntimeError("shape limit has no valid lower crossing bracket at mu=0")
    for _ in range(24):
        high_cls = evaluate(hi)
        if high_cls < cl:
            break
        lo, low_cls = hi, high_cls
        hi *= 2.0
    else:
        # Last tested point, never the untested doubled endpoint.
        result = {"value": lo, "status": "above_scan", "bracket": [lo, None],
                  "cls_endpoints": [low_cls, None], "calibrated": False}
        return result if details else math.inf
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        mid_cls = evaluate(mid)
        if mid_cls < cl:
            hi, high_cls = mid, mid_cls
        else:
            lo, low_cls = mid, mid_cls
        if hi - lo < 1e-3 * max(hi, 1e-9):
            break
    if not (low_cls >= cl > high_cls):
        raise RuntimeError("shape limit lost its crossing bracket")
    result = {"value": 0.5 * (lo + hi), "status": "resolved", "bracket": [lo, hi],
              "cls_endpoints": [low_cls, high_cls], "calibrated": False}
    return result if details else result["value"]


def expected_limit(edges, sqrt_s, form, sig, counts, cl=0.05, *, details=False):
    """Median expected from the observed-data background fit's Asimov pseudo-data."""
    pb, _ = fit_bkg(counts, edges, sqrt_s, form)
    asimov = bkg_binned(form, edges, sqrt_s, pb)
    return upper_limit(asimov, edges, sqrt_s, form, sig, cl=cl, details=details)


# ---------------------------------------------------------------- signal builders
def gauss_template(edges, m0, rel_width, yield_mu1=100.0):
    from scipy.stats import norm
    s = rel_width * m0
    cdf = norm.cdf(edges, loc=m0, scale=s)
    y = np.diff(cdf)
    tot = y.sum()
    return y * (yield_mu1 / tot) if tot > 0 else y


# ---------------------------------------------------------------- machine artifact (shape_fit.json)
def _resolve_timestamp(cli_timestamp=None):
    """generated_utc: --timestamp, else $SHAPE_FIT_UTC, else "" -- NEVER datetime.now() (banned in
    some contexts here; mirrors audit.py's env-override pattern, minus the wall-clock fallback)."""
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get("SHAPE_FIT_UTC", "")


def _json_out_path(out):
    """Derive the sibling shape_fit.json path from a --out plot stem/dir/full-path."""
    if out is None:
        return None
    if out.endswith("/") or os.path.isdir(out):
        return os.path.join(out.rstrip("/"), "shape_fit.json")
    stem, ext = os.path.splitext(out)
    if ext.lower() in (".png", ".pdf"):
        return stem + ".json"
    return out + ".json"                       # out is a bare stem (the house convention)


def _r5_status(r5_points, is_synthetic):
    """Legacy point notes are diagnostics. Only a recomputed bound certificate closes R5."""
    if is_synthetic:
        return "na", "synthetic/validation run (no published target); R5 not applicable"
    return "held", ("R5 needs an artifact-bound comparison plan and certificate; "
                    f"{len(r5_points)} legacy reference notes do not establish closure")


def write_shape_fit_json(out_json, *, spectrum_label, n_bins, edge_lo, edge_hi, lumi_fb,
                          bkg_form, chi2, ndf, sig_label, sig_yield_mu1,
                          mu95_obs, mu95_exp, mu95_exp_band, r5_points, is_synthetic,
                          png_path, pdf_path, timestamp, caveats=None, validation_context=None,
                          certification_plan=None, rundir=None,
                          certificate_path="outputs/r5-certificate.json", numerical_evidence=None):
    """Write the shape_fit.json machine artifact (PRODUCT-CONTRACT S6.1: mu95_obs, mu95_exp,
    r5_status in closed|held|na, r5_evidence). Enforces the two non-negotiable consistencies:
    excluded_obs == (mu95_obs < 1), and r5_status=='closed' only earned (see _r5_status)."""
    r5_points = list(r5_points or [])
    if mu95_exp_band is not None:
        band = [float(v) for v in mu95_exp_band]
        if len(band) != 5:
            raise ValueError("mu95_exp_band must have exactly 5 entries")
        if band != sorted(band):
            raise ValueError("mu95_exp_band must be ascending")
        if abs(band[2] - float(mu95_exp)) > 1e-9 * max(abs(float(mu95_exp)), 1.0):
            raise ValueError("mu95_exp_band median (index 2) must equal mu95_exp")
    else:
        band = None
    r5_status, r5_evidence = _r5_status(r5_points, is_synthetic)
    mu95_obs = float(mu95_obs)
    record = {
        "schema_version": 1,
        "generated_utc": timestamp,
        "generator": "shape_fit.py",
        "stat_mode": "shape-fit",
        "spectrum": {"label": spectrum_label, "n_bins": int(n_bins),
                     "range": [float(edge_lo), float(edge_hi)],
                     "lumi_fb": (float(lumi_fb) if lumi_fb is not None else None),
                     "units": "counts"},
        "bkg_form": bkg_form,
        "fit_quality": {"chi2": float(chi2), "ndf": int(ndf),
                         "chi2_ndf": (float(chi2) / ndf if ndf else None)},
        "signal": {"label": sig_label, "total_yield_mu1": float(sig_yield_mu1), "kind": "template"},
        "mu95_obs": mu95_obs, "mu95_exp": float(mu95_exp), "mu95_exp_band": band,
        "excluded_obs": bool(mu95_obs < 1.0), "method": "asymptotic-CLs",
        "r5_status": r5_status, "r5_evidence": r5_evidence,
        "r5_reference_points": r5_points,
        "plots": {"png": png_path, "pdf": pdf_path},
        "caveats": list(caveats or []),
    }
    from ravel.limits import attach_limits, read_limits
    from ravel.validation import certificates
    if numerical_evidence is not None:
        observed, expected = numerical_evidence["observed"], numerical_evidence["expected"]
        if band is not None:
            raise ValueError("shape numerical evidence currently resolves only the median, not an expected band")
        for curve, scalar in ((observed, mu95_obs), (expected, float(mu95_exp))):
            if curve["value"] != scalar or curve["status"] not in ("resolved", "above_scan"):
                raise ValueError("shape numerical evidence disagrees with the measured limit")
            ends = curve["cls_endpoints"]
            if curve["status"] == "resolved" and not (ends[0] >= .05 > ends[1]):
                raise ValueError("shape numerical evidence lacks a CLs crossing")
        record["numerical_evidence"] = numerical_evidence
        record["limit_status"] = {"observed": observed["status"],
            "expected": ["missing", "missing", expected["status"], "missing", "missing"]}
        record["limit_brackets"] = {"observed": observed["bracket"],
            "expected": [None, None, expected["bracket"], None, None]}
    attach_limits(record, source="shape-fit-unverified")
    record["excluded_obs"] = read_limits(record).observed.exclusion()
    if validation_context is not None:
        quantity = validation_context.get("quantity")
        if quantity not in ("mu95_exp", "mu95_obs"):
            raise ValueError("shape validation context quantity must be mu95_exp or mu95_obs")
        record["validation_point"] = certificates.measurement(
            validation_context, record[quantity], quantity=quantity)
        record["certification_producer"] = {"module": "ravel.physics.shape_fit",
                                             "sha256": certificates.digest(__file__)}
    outdir = os.path.dirname(os.path.abspath(out_json))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(out_json, "w") as fh:
        json.dump(record, fh, indent=2)
    if certification_plan is not None:
        if is_synthetic or rundir is None:
            raise ValueError("R5 certification needs a real target and explicit rundir")
        from pathlib import Path
        subject = str(Path(out_json).resolve().relative_to(Path(rundir).resolve()))
        cert = certificates.create_certificate(rundir, certification_plan, certificate_path)
        contract = certificates.read_json(certificates.local_path(rundir, "inputs/task_contract.json"))
        checked = certificates.validate_certificate(rundir, certificate_path, kind="r5",
            contract=contract, required_subjects=[subject], live=True)
        record["r5_certificate"] = certificate_path
        record["r5_status"] = "closed" if checked["status"] == "PASS" else "held"
        record["r5_evidence"] = cert["scope"] if checked["status"] == "PASS" else "; ".join(checked["errors"])
        with open(out_json, "w") as fh:
            json.dump(record, fh, indent=2, allow_nan=False)
    return record


# ---------------------------------------------------------------- selftest
def _selftest():
    rng = np.random.default_rng(20260707)
    edges = np.linspace(500.0, 3500.0, 61)
    sqrt_s = 13000.0
    p_true = np.array([2.2e7, 9.5, -4.2, -0.9])
    truth = bkg_binned("dijet4", edges, sqrt_s, p_true)
    truth *= 2.0e5 / truth.sum()                 # a realistic ~200k-event spectrum
    # a visible-but-not-huge signal: 150 events at mu=1 in a 5%-width bump at 2 TeV
    sig = gauss_template(edges, 2000.0, 0.05, yield_mu1=150.0)
    fails = []

    # 1) IDENTITY: on the background Asimov, observed UL == expected UL (same construction)
    asimov = truth.copy()
    ul_obs = upper_limit(asimov, edges, sqrt_s, "dijet4", sig)
    ul_exp = expected_limit(edges, sqrt_s, "dijet4", sig, asimov)
    ok1 = abs(ul_obs - ul_exp) < 0.05 * ul_exp
    if not ok1:
        fails.append(f"identity: UL_obs {ul_obs:.3f} != UL_exp {ul_exp:.3f} on the Asimov")
    print(f"[selftest] 1 identity on Asimov: UL_obs={ul_obs:.3f} UL_exp={ul_exp:.3f}  "
          f"{'ok' if ok1 else 'FAIL'}")

    # 2) INJECTION: inject mu_true; the floating-mu profiled fit must recover it within ~2 sigma
    #    (sigma_mu ~ UL_exp/1.64 in the asymptotic regime)
    mu_true = 3.0
    data = rng.poisson(truth + mu_true * sig).astype(float)
    _, _, mu_hat = fit_mu_profiled(data, edges, sqrt_s, "dijet4", sig)
    sigma_mu = ul_exp / 1.64
    ok2 = abs(mu_hat - mu_true) < 2.5 * sigma_mu
    if not ok2:
        fails.append(f"injection: mu_hat {mu_hat:.2f} vs mu_true {mu_true} "
                     f"(> 2.5x sigma_mu {sigma_mu:.2f})")
    print(f"[selftest] 2 injection recovery: mu_hat={mu_hat:.2f} (true {mu_true}, "
          f"sigma_mu~{sigma_mu:.2f})  {'ok' if ok2 else 'FAIL'}")

    # 3) EXCLUSION LOGIC: the injected-signal dataset's 95% UL must sit ABOVE ~mu_true (a 95%
    #    UL should not typically exclude the truth), and above the no-signal dataset's UL.
    data0 = rng.poisson(truth).astype(float)
    ul0 = upper_limit(data0, edges, sqrt_s, "dijet4", sig)
    ul_inj = upper_limit(data, edges, sqrt_s, "dijet4", sig)
    ok3 = (ul_inj > 0.8 * mu_true) and (ul_inj > ul0 * 0.9)
    if not ok3:
        fails.append(f"exclusion ordering: UL(no-sig)={ul0:.2f}, UL(mu=3 injected)={ul_inj:.2f}")
    print(f"[selftest] 3 ordering: UL(no-sig data)={ul0:.2f}, UL(mu=3 injected)={ul_inj:.2f}  "
          f"{'ok' if ok3 else 'FAIL'}")

    # 4) LUMI SCALING: x4 statistics (bkg AND template x4 = same cross-sections, 4x lumi)
    #    -> expected UL on mu improves ~2 (the 1/sqrt(L) regime)
    ul_hi = expected_limit(edges, sqrt_s, "dijet4", 4.0 * sig, 4.0 * truth)
    ratio = ul_exp / ul_hi if ul_hi > 0 else 0.0
    ok4 = 1.5 < ratio < 3.0
    if not ok4:
        fails.append(f"lumi scaling: UL ratio {ratio:.2f} not in the ~2 ballpark")
    print(f"[selftest] 4 scaling (x4 lumi): expected-UL ratio={ratio:.2f} (want ~2)  "
          f"{'ok' if ok4 else 'FAIL'}")

    # 5) JSON ARTIFACT: shape_fit.json is written; a bare synthetic run NEVER defaults to
    #    r5_status="closed" (must be earned with >=2 in-tolerance reference points); excluded_obs
    #    is self-consistent with mu95_obs.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="shape_fit_selftest_") as tmpdir:
        json_path = os.path.join(tmpdir, "shape_fit.json")
        rec = write_shape_fit_json(
            json_path, spectrum_label="m [GeV] (selftest)", n_bins=len(edges) - 1,
            edge_lo=edges[0], edge_hi=edges[-1], lumi_fb=None, bkg_form="dijet4",
            chi2=0.0, ndf=len(edges) - 1 - 4, sig_label="Gaussian stand-in (selftest)",
            sig_yield_mu1=float(sig.sum()), mu95_obs=ul0, mu95_exp=ul_exp, mu95_exp_band=None,
            r5_points=[], is_synthetic=True, png_path=None, pdf_path=None,
            timestamp=_resolve_timestamp(), caveats=["synthetic selftest dataset"])
        with open(json_path) as fh:
            reread = json.load(fh)
        ok5 = (os.path.isfile(json_path)
               and reread["r5_status"] in ("na", "held") and reread["r5_status"] != "closed"
               and reread["excluded_obs"] is None
               and reread == rec)
        if not ok5:
            fails.append(f"JSON artifact: r5_status={rec.get('r5_status')} "
                         f"excluded_obs={rec.get('excluded_obs')}")
        print(f"[selftest] 5 JSON artifact: r5_status={rec['r5_status']} "
              f"excluded_obs={rec['excluded_obs']}  {'ok' if ok5 else 'FAIL'}")

        # 5b) the closure path only fires with >=2 in-tolerance points (never by default)
        rec_closed = write_shape_fit_json(
            os.path.join(tmpdir, "shape_fit_closed.json"), spectrum_label="m [GeV]", n_bins=10,
            edge_lo=0.0, edge_hi=1.0, lumi_fb=None, bkg_form="dijet4", chi2=1.0, ndf=6,
            sig_label="x", sig_yield_mu1=1.0, mu95_obs=0.5, mu95_exp=0.6, mu95_exp_band=None,
            r5_points=[{"mass_gev": 20.0, "in_tolerance": True},
                       {"mass_gev": 125.0, "in_tolerance": True}],
            is_synthetic=False, png_path=None, pdf_path=None, timestamp="")
        rec_one_point = write_shape_fit_json(
            os.path.join(tmpdir, "shape_fit_held.json"), spectrum_label="m [GeV]", n_bins=10,
            edge_lo=0.0, edge_hi=1.0, lumi_fb=None, bkg_form="dijet4", chi2=1.0, ndf=6,
            sig_label="x", sig_yield_mu1=1.0, mu95_obs=0.5, mu95_exp=0.6, mu95_exp_band=None,
            r5_points=[{"mass_gev": 20.0, "in_tolerance": True}],
            is_synthetic=False, png_path=None, pdf_path=None, timestamp="")
        ok5b = (rec_closed["r5_status"] == "held" and rec_one_point["r5_status"] == "held")
        if not ok5b:
            fails.append(f"R5 closure logic: 2-point={rec_closed['r5_status']} "
                         f"1-point={rec_one_point['r5_status']}")
        print(f"[selftest] 5b R5 closure logic: 2-in-tol-points={rec_closed['r5_status']}, "
              f"1-in-tol-point={rec_one_point['r5_status']}  {'ok' if ok5b else 'FAIL'}")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("shape_fit selftest: PASS (identity, injection, ordering, scaling, JSON artifact, "
          "R5 closure logic)")
    return 0


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fit")
    p.add_argument("--spectrum", required=True)
    p.add_argument("--signal", default=None, help="binned template JSON (yields at mu=1)")
    p.add_argument("--gauss", default=None, metavar="M0,RELW[,YIELD]",
                   help="Gaussian stand-in signal (validation only; label it so)")
    p.add_argument("--bkg-form", choices=list(bkg_families()) + ["template"], default="dijet4")
    p.add_argument("--bkg-template", default=None,
                   help="JSON {edges, yields}: the paper's own published background SHAPE "
                        "(post-fit non-resonant column) — required with --bkg-form template; "
                        "fitted as norm x shape x exp(poly_K(u))")
    p.add_argument("--bkg-order", type=int, default=3,
                   help="K, the transfer-polynomial order of the template modulation; too "
                        "rigid (K=1) yields ANTI-conservative limits — match the paper's fit "
                        "flexibility; report limits at K and K+1 (stability)")
    p.add_argument("--syst", default=None,
                   help="JSON {edges, yields}: the paper's per-bin ABSOLUTE background "
                        "uncertainty envelope; switches the NLL to Gaussian (large-N stand-in "
                        "for per-bin constrained NPs)")
    p.add_argument("--fixed-bkg", default=None,
                   help="JSON {edges, yields}: additive NON-fitted background (published "
                        "resonant MC, e.g. gamma+W/Z, ttbar); edges must match")
    p.add_argument("--signal-scale", type=float, default=1.0,
                   help="divide the template by this (e.g. a published 'x5' display scaling)")
    p.add_argument("--range", default=None, metavar="LO,HI", help="fit window in GeV")
    p.add_argument("--input-units", choices=["counts", "density-per-gev"], default=None,
                   help="spectrum units; density is converted to counts (x binwidth) — the "
                        "likelihood REQUIRES counts (R5-closure measured defect)")
    p.add_argument("--out", default=None, help="plot stem (house style + CR-016 lint)")
    p.add_argument("--no-lint", action="store_true")
    p.add_argument("--timestamp", default=None,
                   help="generated_utc for shape_fit.json (else $SHAPE_FIT_UTC, else \"\"; "
                        "never datetime.now())")
    p.add_argument("--r5-points", default=None,
                   help="legacy reference notes, retained for diagnostics; cannot close R5")
    p.add_argument("--validation-context", help="explicit point identity/basis JSON; measured value comes from this fit")
    p.add_argument("--certification-plan", help="approved R5 plan path relative to --rundir")
    p.add_argument("--rundir", help="run containing the approved plan and all bound artifacts")
    p.add_argument("--r5-certificate-out", default="outputs/r5-certificate.json")
    args = ap.parse_args()

    from ravel.validation.certificates import read_json
    if args.certification_plan and (not args.rundir or not args.out):
        ap.error("--certification-plan requires --rundir and --out")
    validation_context = read_json(args.validation_context) if args.validation_context else None
    r5_points = []
    if args.r5_points:
        r5_points = json.load(open(args.r5_points))
        if not isinstance(r5_points, list):
            sys.exit("shape_fit: --r5-points must be a JSON list of reference-point records")

    spec = json.load(open(args.spectrum))
    edges = np.asarray(spec["edges"], float)
    counts = np.asarray(spec["counts"], float)
    sqrt_s = float(spec.get("sqrt_s_tev", 13.0)) * 1000.0
    if len(counts) != len(edges) - 1:
        sys.exit("shape_fit: counts/edges length mismatch")
    # COUNTS-vs-DENSITY (the R5-closure measured defect): HEPData spectra are often per-GeV
    # densities; fitting a density as counts under-disperses everything (measured chi2/ndf
    # 19.9/39 -> 40.3/39 on ins2813982 after x binwidth). The likelihood needs COUNTS.
    units = (args.input_units or spec.get("units", "counts")).lower()
    if units.startswith("density"):
        counts = counts * np.diff(edges)
        print(f"input units = density-per-GeV: multiplied by bin widths -> counts "
              f"(total {counts.sum():.1f})")
    elif not np.allclose(counts, np.round(counts)) and counts.sum() > 100:
        print("WARNING: non-integer 'counts' — if this spectrum is a per-GeV DENSITY, rerun "
              "with --input-units density-per-gev (the R5-closure defect class); post-fit or "
              "weighted representations are legitimately non-integer.", file=sys.stderr)
    if args.range:
        lo, hi = (float(v) for v in args.range.split(","))
        m = (edges[:-1] >= lo) & (edges[1:] <= hi)
        idx = np.where(m)[0]
        edges = np.concatenate([edges[idx], [edges[idx[-1] + 1]]])
        counts = counts[idx]
    global FIXED_BKG, TEMPLATE_BKG, SYST
    if args.fixed_bkg:
        fb = json.load(open(args.fixed_bkg))
        if list(map(float, fb["edges"])) != list(map(float, edges)):
            sys.exit("shape_fit: fixed-bkg edges do not match the spectrum (after --range)")
        FIXED_BKG = np.asarray(fb["yields"], float)
        print(f"fixed (non-fitted) background component: {FIXED_BKG.sum():.1f} events "
              f"({fb.get('label', 'resonant MC')})")
    if args.bkg_form == "template":
        global TEMPLATE_ORDER
        TEMPLATE_ORDER = max(1, args.bkg_order)
        if not args.bkg_template:
            sys.exit("shape_fit: --bkg-form template requires --bkg-template FILE")
        tb = json.load(open(args.bkg_template))
        if list(map(float, tb["edges"])) != list(map(float, edges)):
            sys.exit("shape_fit: bkg-template edges do not match the spectrum (after --range)")
        TEMPLATE_BKG = np.asarray(tb["yields"], float)
        print(f"template background shape: {TEMPLATE_BKG.sum():.1f} events as published "
              f"({tb.get('label', 'published non-resonant')}); fitting norm + tilt")
    if args.syst:
        sy = json.load(open(args.syst))
        if list(map(float, sy["edges"])) != list(map(float, edges)):
            sys.exit("shape_fit: syst edges do not match the spectrum (after --range)")
        SYST = np.asarray(sy["yields"], float)
        print(f"per-bin systematic envelope loaded (published); NLL = Gaussian(N + syst^2)")
    if args.signal:
        tm = json.load(open(args.signal))
        if list(map(float, tm["edges"])) != list(map(float, edges)):
            sys.exit("shape_fit: signal-template edges do not match the spectrum "
                     "(after --range); rebin explicitly, never silently")
        sig = np.asarray(tm["yields"], float) / args.signal_scale
        sig_label = tm.get("label", "signal template") + (
            f" (published display scaling /{args.signal_scale:g} removed)"
            if args.signal_scale != 1.0 else "")
    elif args.gauss:
        parts = [float(v) for v in args.gauss.split(",")]
        m0, relw = parts[0], parts[1]
        y1 = parts[2] if len(parts) > 2 else 100.0
        sig = gauss_template(edges, m0, relw, yield_mu1=y1)
        sig_label = f"Gaussian stand-in m0={m0:g}, width={relw:.0%} (validation only)"
    else:
        sys.exit("shape_fit: need --signal or --gauss")

    pb, nll_b = fit_bkg(counts, edges, sqrt_s, args.bkg_form)
    bexp = bkg_binned(args.bkg_form, edges, sqrt_s, pb)
    chi2 = float(np.sum((counts - bexp) ** 2 / np.clip(bexp, 1e-9, None)))
    ndf = len(counts) - _npar(args.bkg_form)
    observed_evidence = upper_limit(counts, edges, sqrt_s, args.bkg_form, sig, details=True)
    expected_evidence = expected_limit(edges, sqrt_s, args.bkg_form, sig, counts, details=True)
    ul, ul_exp = observed_evidence["value"], expected_evidence["value"]

    print(f"background fit [{args.bkg_form}]: chi2/ndf = {chi2:.1f}/{ndf} "
          f"params = {np.array2string(pb, precision=3)}")
    print(f"signal: {sig_label}; total template yield at mu=1: {sig.sum():.2f}")
    print(f"mu95 observed = {ul:.4g}    mu95 expected = {ul_exp:.4g}   (asymptotic CLs)")
    print("R5 GATE REMINDER: no reinterpretation ships from this engine until the target "
          "analysis's OWN published limit is reproduced at >=2 points "
          "(DECISION-SHAPE-FIT.md; verification-ladder R5).")

    if args.out:
        caveats = []
        if units.startswith("density"):
            caveats.append("spectrum converted from per-GeV density to counts via bin widths "
                            "(R5-closure measured defect class)")
        if args.bkg_form == "template":
            caveats.append(f"template background (order {TEMPLATE_ORDER}); K must match the "
                            "paper's own fit flexibility or the limit is anti-conservative")
        if SYST is not None:
            caveats.append("Gaussian NLL with published per-bin systematic envelope")
        if FIXED_BKG is not None:
            caveats.append("fixed (non-fitted) resonant background component added")
        json_path = _json_out_path(args.out)
        write_shape_fit_json(
            json_path,
            spectrum_label=spec.get("label", "m [GeV]"), n_bins=len(counts),
            edge_lo=edges[0], edge_hi=edges[-1], lumi_fb=spec.get("lumi_fb"),
            bkg_form=args.bkg_form, chi2=chi2, ndf=ndf,
            sig_label=sig_label, sig_yield_mu1=float(sig.sum()),
            mu95_obs=ul, mu95_exp=ul_exp, mu95_exp_band=None,
            r5_points=r5_points, is_synthetic=bool(args.gauss),
            png_path=args.out + ".png", pdf_path=args.out + ".pdf",
            timestamp=_resolve_timestamp(args.timestamp), caveats=caveats,
            validation_context=validation_context, certification_plan=args.certification_plan,
            rundir=args.rundir, certificate_path=args.r5_certificate_out,
            numerical_evidence={"observed": observed_evidence, "expected": expected_evidence})
        print(f"wrote {json_path}")

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ..plotting import mplhep_style as house
        house.apply_style("ATLAS")
        fig, ax = plt.subplots(figsize=(8, 6))
        mid = 0.5 * (edges[:-1] + edges[1:])
        ax.errorbar(mid, counts, yerr=np.sqrt(np.clip(counts, 0, None)), fmt="ko",
                    ms=4, label="spectrum")
        ax.plot(mid, bexp, "-", color=house.OKABE_ITO["blue"], lw=2,
                label=f"{args.bkg_form} fit")
        ax.plot(mid, bexp + ul * sig, "--", color=house.OKABE_ITO["vermillion"], lw=2,
                label=rf"bkg + $\mu_{{95}}$·signal")
        ax.set_yscale("log")
        ax.set_xlabel(spec.get("label", "m [GeV]"))
        ax.set_ylabel("Events / bin")
        house.smart_legend(ax, fontsize=11)
        house.smart_annotate(ax, [rf"$\mu_{{95}}$ obs = {ul:.3g}, exp = {ul_exp:.3g}",
                                  f"fit chi2/ndf = {chi2:.0f}/{ndf}",
                                  "95% CL exclusion (CLs), not a discovery"], fontsize=10)
        house.enforce_lint(fig, where=os.path.basename(args.out), allow=args.no_lint)
        for ext in (".png", ".pdf"):
            fig.savefig(args.out + ext, dpi=200, bbox_inches="tight")
            print(f"wrote {args.out}{ext}")


if __name__ == "__main__":
    main()
