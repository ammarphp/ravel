# Rule — statistics & exclusion

Read when computing a limit, normalizing a cross-section, or certifying a run.

## 95% CLs, not 5σ (state this correctly)
This tool sets **95% CL exclusion limits** via the **CLs** method (≈1.64σ one-sided): is the model
*excluded or allowed* by the published data? It does **not** make **5σ discovery** claims — 5σ is for
claiming a new particle in the data, which is out of scope. Never phrase a result as a discovery.

## pyhf exclusion (`src/ravel/physics/pyhf_exclude.py`)
- **Mode A — likelihood** (preferred when published): apply the signal patch to the published
  background-only HistFactory JSON. `… likelihood --bkg <bkgonly>.json --patch <patch>.json`.
- **Mode B — counting**: one single-bin model per SR from observed+background±unc+signal; quote the
  most-sensitive SR (best expected CLs). `… counting --srs sr_yields.json`.
- The limit must reach the **true** CLs=0.05 crossing. A fixed µ grid (e.g. mapyde's 0.1–2.0) can stop
  short; `pyhf_exclude.py` brackets µ (doubles until CLs<0.05) and interpolates — a large µ₉₅ is a real
  (weakly-constrained) result, not a bug. Never hand-roll the statistical model.
- **Silent-optimizer guard (CR-005, a 🔴 trap):** histosys workspaces can have NaN pockets on which
  scipy/SLSQP returns its INIT vector claiming success (2018-06: µ₉₅ 1.192 with obs==exp, no error).
  `pyhf_exclude.py` auto-detects this, falls back to NaN-guarded iminuit MIGRAD, and escalates the
  whole model MIGRAD-first — check `exclusion.json` `"optimizer"` for `escalated`/`n_fallback`.
  Honesty flags: `median_at_cap` (CR-124, the median really IS the ceiling — `at_poi_cap` alone is
  bracket granularity) and `band_degenerate` (CR-132, band spans <1.5× — quote as bound only).
  Regression: `pyhf_exclude.py selftest` (incl. the committed 2018-06 fixture).

## NLO+NLL normalization — and the single-charge caveat (a 🔴 trap)
- `nlo_xsec.py --process <gluino|squark|stop|sbottom|wino-c1n2|slepton> --mass <m>` → σ_NLO+NLL + k.
  Pass `pyhf_exclude.py --sigma-scale <k>` to put the limit on NLO while A×ε stays σ-independent.
- The HEPi EWKino grid (`wino-c1n2`) is a **single charge state**; MadGraph `x1± n2` is **both**.
  Dividing single-charge NLO by both-charge LO gives an unphysical k<1. Compare like-for-like
  (single-charge LO vs single-charge NLO, or sum both) → expect k≈1.2–1.3. `nlo_xsec.py` warns if k<1.

## The tiered + attribution certification (`validate_cutflow.py`)
A×ε = (routine SR yield)/(σ·lumi), cross-section-independent. Tiers: **driving** SR (best expected CLs
+ within 1.5×) ≤12–15%; **contributing** ≤25%; **tail** (<~5 events) report-only. Every residual above
its tier emits an attribution row (`cause_class ∈ merging / k-factor / fast-sim-floor /
selection-mapping / statistics`) with a bounded µ₉₅-impact. PASS = driving within tol **and** worst
|Δµ₉₅| ≤ bound **and** the verdict can't flip. Usage: `--srs "2jl,2jm,…"` is a **comma list of SR
names**, not a json path. The output formatter tolerates a missing SR (`mine=None` → `-`).

## Systematics
Fast-sim+LO has an intrinsic ~10–20% floor; even the reference tool (mapyde) tunes ~15% and degrades
~10% in compressed regions. Propagate acceptance systematics where the likelihood provides them;
under-quoting systematics falsely tightens the limit. Validate in control regions when available.
