#!/usr/bin/env python
"""NLO+NLL signal cross-section + k-factor, so the limit is on the right normalisation.

Signal samples are generated at LO; the experiments normalise to NLO+NLL (NNLO_approx+NNLL for
colored, NLO+NLL for electroweak). Quoting a limit on the LO σ biases it conservative by the
k-factor. This helper returns the reference NLO+NLL σ (from the LHC SUSY x-sec Working Group values,
served as JSON by the HEPi project, computed with NNLL-fast / Resummino) and k = σ_NLO+NLL / σ_LO.
A×ε is a ratio and is unaffected; only the absolute limit moves (pyhf_exclude.py --sigma-scale k).

Processes → HEPi JSON:
  gluino   pp13_gluino_NNLO+NNLL.json        (keyed by m_gluino, squarks decoupled)
  squark   pp13_squark_NNLO+NNLL.json        (keyed by m_squark, gluino decoupled)
  stop|sbottom  pp13_stopsbottom_NNLO+NNLL.json
  wino-c1n2     13000_wino_1000023_-1000024_NNLL.json   (keyed by mass tuple)
  slepton       13000_sleptons_<pdg>_-<pdg>_NNLL.json

For slepton, --sigma-lo-pb may be OMITTED: the like-for-like LO denominator (selectron_L pair,
cteq6l1, MG5 LO 2->2 -- the same single state the HEPi NNLL file contains) is read from the local
reference table slepton_selL_lo_cteq6l1.json, so `nlo_xsec.py --process slepton --mass <m>` returns
sigma_NLO+NLL + k directly. That k(m) path is also importable (slepton_k) -- it is what
scan_orchestrator.py `assemble --nlo-renorm slepton` uses to re-normalize a scan's mu95 from the
flat LO k to the per-mass NLO+NLL one.

Usage:
  nlo_xsec.py --process gluino --mass 1000 --sigma-lo-pb 0.201 --out <run>/nlo.json
  nlo_xsec.py --process wino-c1n2 --mass 300 --m-lsp 100 --sigma-lo-pb 0.5 --out ...
  nlo_xsec.py --process slepton --mass 150 --out <run>/nlo.json     # LO from the local ref table
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse, json, math, os, ssl, sys, urllib.request

RAW = "https://raw.githubusercontent.com/APN-Pucky/HEPi/master/hepi/data/json/"
FILES = {"gluino": "pp13_gluino_NNLO+NNLL.json", "squark": "pp13_squark_NNLO+NNLL.json",
         "stop": "pp13_stopsbottom_NNLO+NNLL.json", "sbottom": "pp13_stopsbottom_NNLO+NNLL.json",
         "wino-c1n2": "13000_wino_1000023_-1000024_NNLL.json",
         "slepton": "13000_sleptons_1000011_-1000011_NNLL.json"}
# documented k-factor fallback if the network/JSON is unavailable (KNOWN-LIMITATIONS)
K_FALLBACK = {"gluino": 1.6, "squark": 1.5, "stop": 1.35, "sbottom": 1.35,
              "wino-c1n2": 1.25, "slepton": 1.25}
# local like-for-like LO reference tables (denominator of k when --sigma-lo-pb is omitted).
# slepton: sigma_LO(p p > el- el+, cteq6l1) at the scan masses -- the SAME single flavour+chirality
# state (PDG 1000011) as the HEPi NNLL numerator, so the ratio is state-for-state like-for-like.
from ..paths import package_data_path
LO_REF = {"slepton": str(package_data_path("cross_sections", "slepton_selL_lo_cteq6l1.json"))}


def _get(url):
    # CR-021 SSL policy: verified TLS only (certifi via the conda envs); never bypassed.
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = None
    try:
        return json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "hep-agentic-pipeline"}),
            timeout=30, context=ctx))
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise RuntimeError("TLS verification failed; run inside a conda env with certifi "
                               "(verification is never bypassed, CR-021)") from e
        raise


def hepi_grid(process):
    """Fetch the HEPi reference grid for `process` -> its 'data' dict. Raises on any failure
    (network/JSON) -- callers that must not silently fall back (assemble --nlo-renorm) use this."""
    d = _get(RAW + FILES[process])
    data = d.get("data", {})
    if not data:
        raise ValueError(f"HEPi {FILES[process]} has no 'data'")
    return data


def load_lo_ref(process):
    """Load the local like-for-like LO reference table -> its 'data' dict. Raises if absent."""
    path = LO_REF.get(process)
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"no local LO reference table for '{process}' "
                                f"({path or 'none registered'}) -- pass --sigma-lo-pb instead")
    data = json.load(open(path)).get("data", {})
    if not data:
        raise ValueError(f"LO reference table {path} has no 'data'")
    return data


def lookup(data, mass, loglog=False):
    """nearest-mass (interpolated) xsec_pb from a HEPi-style `data` dict keyed by mass string.

    loglog=True interpolates linearly in (ln m, ln sigma) instead of (m, sigma). SUSY production
    sigmas fall as steep power laws, so linear-in-mass interpolation between sparse nodes
    OVERSHOOTS badly (e.g. the slepton grid's 50->75 GeV gap: linear gives sigma(60) ~45% high,
    which would fake an unphysical k). Any path that feeds a k-factor uses loglog."""
    keys = sorted((float(k.split("_")[0]) if "_" in str(k) else float(k), k) for k in data)
    lo = hi = None
    for mval, k in keys:
        if mval <= mass:
            lo = (mval, k)
        if mval >= mass and hi is None:
            hi = (mval, k)
    if lo and hi and lo[0] != hi[0]:
        x0, x1 = data[lo[1]]["xsec_pb"], data[hi[1]]["xsec_pb"]
        if loglog and x0 > 0 and x1 > 0:
            f = (math.log(mass) - math.log(lo[0])) / (math.log(hi[0]) - math.log(lo[0]))
            return math.exp(math.log(x0) + f * (math.log(x1) - math.log(x0))), \
                f"loglog-interp({lo[0]:.0f},{hi[0]:.0f})"
        f = (mass - lo[0]) / (hi[0] - lo[0])
        return x0 + f * (x1 - x0), f"interp({lo[0]:.0f},{hi[0]:.0f})"
    node = lo or hi
    return data[node[1]]["xsec_pb"], f"nearest({node[0]:.0f})"


def slepton_k(mass, grid=None, lo_ref=None):
    """Per-mass slepton k(m) = sigma_NNLL(HEPi selL pair, PDF4LHC21) / sigma_LO(MG5 selL pair,
    cteq6l1) -- the multiplicative correction from a cteq6l1-LO normalization to the NLO+NLL one.

    Like-for-like by construction: numerator and denominator are BOTH the single selectron_L pair
    state (PDG 1000011 x -1000011), dodging the single-charge/single-state trap
    (.claude/rules/statistics.md): the HEPi slepton file is ONE flavour x ONE chirality, NOT the
    inclusive 6-state sum a `chsleptons chsleptons` sample produces -- dividing it by an inclusive
    LO would give k~0.5, i.e. unlike quantities. The PDF/order mix (PDF4LHC21 NNLL over cteq6l1 LO)
    is deliberate: that ratio IS the correction a cteq6l1-LO-normalized sample needs. k-factors are
    flavour/chirality-universal to good approximation (same Drell-Yan QCD corrections), so the
    selL-pair k applies to the full slepton sample.

    Interpolation: k -- NOT sigma -- is interpolated wherever possible. sigma(m) falls by orders
    of magnitude with curvature in log-log, so interpolating the NNLL numerator across its sparse
    nodes (e.g. HEPi's 50->75 GeV gap) against an EXACT LO denominator leaks the interpolation
    error straight into k (a fake +8% spike at m=60). k(m) itself is smooth and nearly flat
    (~1.38-1.41 over 50-300 GeV), so: compute k exactly at the masses BOTH tables tabulate, then
    interpolate k linearly in mass between them. Falls back to the ratio of loglog-interpolated
    sigmas only if the tables share <2 masses.

    Raises (never falls back to a flat k) on any failure -- the renorm path must fail loud.
    Returns dict(mass, sigma_nlo_nll_pb, sigma_lo_pb, k_factor, lookup_nlo, lookup_lo)."""
    grid = grid if grid is not None else hepi_grid("slepton")
    lo_ref = lo_ref if lo_ref is not None else load_lo_ref("slepton")
    sigma_nlo, how_nlo = lookup(grid, mass, loglog=True)
    sigma_lo, how_lo = lookup(lo_ref, mass, loglog=True)

    def node_masses(data):
        return {float(str(kk).split("_")[0]) for kk in data}
    common = sorted(node_masses(grid) & node_masses(lo_ref))
    if len(common) >= 2:
        ktab = {}
        for mm in common:
            n, _ = lookup(grid, mm)        # exact node -> no interpolation happens
            l, _ = lookup(lo_ref, mm)
            ktab[f"{mm:g}"] = {"xsec_pb": n / l}
        k, how_k = lookup(ktab, mass)      # linear interp of the nearly-flat k(m)
        how_nlo = f"k-interp[common nodes {common[0]:g}..{common[-1]:g}]: {how_k}"
        sigma_nlo = k * sigma_lo           # report the sigma CONSISTENT with the k used
    else:
        k = sigma_nlo / sigma_lo
    if not (1.0 <= k <= 3.0):
        raise ValueError(f"slepton k({mass:g}) = {k:.3f} outside the physical window (expect "
                         f"~1.1-1.4 for sleptons; NNLL/PDF4LHC21 over LO/cteq6l1 sits ~1.38-1.40). "
                         f"sigma_NNLL={sigma_nlo:.4g} pb vs sigma_LO={sigma_lo:.4g} pb are not "
                         f"like-for-like -- check state content / mass range of the tables.")
    return {"mass": mass, "sigma_nlo_nll_pb": sigma_nlo, "sigma_lo_pb": sigma_lo,
            "k_factor": k, "lookup_nlo": how_nlo, "lookup_lo": how_lo}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--process", required=True, choices=list(FILES))
    ap.add_argument("--mass", type=float, required=True)
    ap.add_argument("--m-lsp", type=float, default=0.0)
    ap.add_argument("--sigma-lo-pb", type=float, default=None,
                    help="the like-for-like LO sigma; may be OMITTED for processes with a local LO "
                         "reference table (slepton: selL-pair cteq6l1 MG5 LO)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sigma_lo = args.sigma_lo_pb
    lo_how = "cli"
    if sigma_lo is None:
        try:
            sigma_lo, lo_how = lookup(load_lo_ref(args.process), args.mass, loglog=True)
        except Exception as e:
            sys.exit(f"nlo_xsec: --sigma-lo-pb omitted and no usable local LO reference for "
                     f"'{args.process}': {e}")
    res = {"process": args.process, "mass": args.mass, "sigma_lo_pb": sigma_lo,
           "sigma_lo_source": lo_how}
    try:
        d = _get(RAW + FILES[args.process])
        data = d.get("data", {})
        # colored processes are keyed by a single mass; EWKino by a tuple (lookup uses the leading
        # mass). loglog: sigma(m) is a steep power law -- linear-in-mass interp overshoots between
        # sparse nodes (slepton 50->75 GeV gap: ~45% high at m=60 -> a fake k), see lookup().
        sigma_nlo, how = lookup(data, args.mass, loglog=True)
        k = round(sigma_nlo / sigma_lo, 3)
        res.update(sigma_nlo_nll_pb=round(sigma_nlo, 6), k_factor=k,
                   source=f"HEPi/{FILES[args.process]} ({d.get('order','NLO+NLL')}; {d.get('tool','')})",
                   lookup=how)
        # physical-sanity guard: for SUSY pair/associated production NLO+NLL > LO always (k ~ 1.1-2).
        # k<1 or k>3 ⇒ the LO and the reference σ are NOT like-for-like — almost always a normalisation
        # mismatch: the HEPi EWKino files are a SINGLE charge combination (e.g. 1000023 -1000024 = N2+C1⁻),
        # but `generate p p > x1+ n2` + `add p p > x1- n2` is BOTH charges (≈2× the file). Match them:
        # supply a single-charge LO, or scale the reference by the number of charge states.
        if k < 1.0 or k > 3.0:
            res["warning"] = (f"k={k} is unphysical for {args.process} (expect ~1.1-2). The LO σ "
                              f"({sigma_lo} pb) and the reference σ ({sigma_nlo:.4g} pb) are likely "
                              f"not like-for-like — check charge states / flavour sum / scale. The HEPi "
                              f"EWKino file is ONE charge combination; MadGraph 'x1± n2' is two.")
            print("WARNING:", res["warning"])
        print(f"{args.process} m={args.mass:.0f}: σ_LO={sigma_lo} pb  "
              f"σ_NLO+NLL={sigma_nlo:.4g} pb  k={k}  [{how}]")
    except Exception as e:
        k = K_FALLBACK[args.process]
        res.update(sigma_nlo_nll_pb=round(sigma_lo * k, 6), k_factor=k,
                   source=f"documented k-factor fallback (HEPi unavailable: {e!r})", lookup="fallback")
        print(f"HEPi unavailable ({e!r}); using documented k={k} fallback for {args.process}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(res, open(args.out, "w"), indent=2)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
