# Rule — statistics & exclusion

Read when computing a limit, normalizing a cross-section, or certifying a run.

## Which statistic to deliver
RAVEL produces exclusion limits, fits, measurements, calculations and summaries of published
results. Deliver the quantity the request asks for.

- **Exclusion with no prescribed statistic:** 95% CLs exclusion limits are the default. Report
  whether the model is excluded or not excluded by the stated analysis and assumptions.
- **Prescribed statistic:** when the request prescribes a statistic, that statistic is the
  requested quantity and the primary result. Examples are an explicit formula such as
  S/√(B + δB²), an Nσ region or contour, a Δχ² threshold and a Bayesian credible interval.
  Evaluate it as written, record its definition in the plan, and add 95% CLs alongside only
  when it helps the comparison. A CLs result never replaces the prescribed one.
- **Fits, measurements and calculations:** report the fitted parameters, intervals, goodness of
  fit or calculated values with their uncertainties and conventions.

CLs is a modified frequentist ratio, not a general conversion to a Gaussian significance. A
nonexcluded model is not thereby established as viable under every other constraint. An
exclusion result is not a discovery claim.

## pyhf exclusion (`src/ravel/physics/pyhf_exclude.py`)
- **Mode A — likelihood** (preferred when published): apply the signal patch to the published
  background-only HistFactory JSON. `… likelihood --bkg <bkgonly>.json --patch <patch>.json`.
- **Mode B — counting**: one single-bin model per SR from observed+background±unc+signal; quote the
  most-sensitive SR (best expected CLs). `… counting --srs sr_yields.json`.
- The limit must reach the **true** CLs=0.05 crossing. A fixed µ grid (e.g. mapyde's 0.1–2.0) can stop
  short; `pyhf_exclude.py` brackets µ and refines each observed/expected crossing with Brent's
  method. A sparse-curve interpolation is not a verified root. Inspect the typed status, bracket,
  fitted CLs and numerical diagnostics for all six roots. An endpoint is a bound, not a resolved
  weak limit. Never replace an unresolved fit with a neighboring point or smooth it away.
- **Optimizer success is insufficient:** histosys workspaces can return the initial vector or
  different local minima while claiming success. The scalar guard retains its NaN-triggered
  MIGRAD fallback and escalation. Analytic fits must also pass finite original-objective,
  bound, fixed-parameter and projected-gradient checks. A transient invalid line-search trial
  is recorded separately from an invalid final fit. Both paths use the guarded optimizer;
  changing the tensor backend must not bypass it.
  Profile fits re-evaluate a bounded portfolio of starting points on the current objective,
  check free/fixed-fit nesting and validate roots against a frozen portfolio in both orders.
  A newly discovered branch forces re-evaluation; cached monotonicity is insufficient.
  Inspect all root checks, fallback counts, fit-start recoveries, engine/input hashes and
  failures. This finite search is a numerical consistency test, not a global-optimum proof.
  Honesty flags: `median_at_cap` (the median really IS the ceiling — `at_poi_cap` alone is
  bracket granularity) and `band_degenerate` (band spans <1.5× — quote as bound only).
  Regression: `pyhf_exclude.py selftest` for synthetic numerical invariants. Compare a
  selected source likelihood with `check_fit_reference` and supplied reference values;
  see `docs/workflow/steps/07-exclude.md`. No source likelihood is installed as a default.

## Cross-section normalization and charge accounting
- `ravel xsec lookup --request request.json` selects a pinned rate with explicit order, PDF and scale.
  Record whether the supplied signal template already uses that normalization. `pyhf_exclude.py --sigma-scale <k>` changes the reported signal
  strength convention; do not apply it again to a template already normalized by the same k.
  A fixed correction factor taken from a recipe is a recipe input, not by itself a higher-order
  calculation. Correction values come from the selected study inputs and their sources.
- The requested order must match what the analysis states.
- A charge-summed basis must be requested explicitly with `charge: "sum"`.
- Match the numerator and denominator's explicit process, charge sum, flavor/multiplicity,
  branching-ratio convention, perturbative order, masses and collision energy. Inspect the
  actual grid and generator metadata: a single-charge reference cannot normalize a both-charge
  sample without the corresponding documented conversion. A k-factor below one is not by itself
  unphysical, and a value above one does not prove matching bases. Diagnose any warning against
  these inputs; never tune the normalization to reach an expected numerical range.
- When the generated sample differs from the model's inclusive basis (a required extra parton,
  or more produced states than the model counts), selected yields are
  `L * K * sigma_generated * selected_fraction`. An inclusive-model cross-section limit is
  `mu95 * K * sigma_inclusive` only when both rates count the same states. Dividing by an
  inclusive rate does not remove events from states the template should not contain. Preserve
  both generated and inclusive rates and their source cards, including generation-level cuts.

## The tiered + attribution certification (`validate_cutflow.py`)
A×ε = (routine SR yield)/(σ·lumi), cross-section-independent. Tiers: **driving** SR (best expected CLs
+ within 1.5×) ≤12–15%; **contributing** ≤25%; **tail** (<~5 events) report-only. Every residual above
its tier emits an attribution row (`cause_class ∈ merging / k-factor / fast-sim-floor /
selection-mapping / statistics`) with a bounded µ₉₅-impact. PASS = driving within tol **and** worst
|Δµ₉₅| ≤ bound **and** the verdict can't flip. Usage: `--srs "<SR-A>,<SR-B>,…"` is a **comma list of SR
names**, not a json path. The output formatter tolerates a missing SR (`mine=None` → `-`).

## Signal regions, controls and simulation uncertainty
Use the released likelihood's actual channel definitions, including signal contamination in
control regions where supported. A background workspace plus nominal SR yields is not the full
published signal model. An adapter's full signal model requires its declared SR and CR mapping;
an SR-only signal model is an explicitly incomplete diagnostic control.

Retain per-bin sumw, sumw2 and effective counts. `sa2json_native --mc-stat shapesys` supplies an
effective-Poisson approximation from those moments; `staterror` supplies a Gaussian approximation.
Both require disjoint mapped event selections. `none` explicitly omits this uncertainty.
Zero-selected bins have unresolved precision; neither a zero template nor a large total generated
count establishes their accuracy. Pool independent replicas using original generated exposure
and same-process evidence, never by adding already normalized templates or counting selected rows.

There is no universal fast-simulation error floor that excuses a failed comparison. Detector,
trigger, ISR and theory variations require source-backed response estimates. Published benchmark
nuisance derivatives are valid for their own signal model and cannot be transferred to arbitrary
native samples without evidence. Report absent uncertainty components and validate each stage
before claiming physical reproduction. Follow the reproduction-closure checklist.
