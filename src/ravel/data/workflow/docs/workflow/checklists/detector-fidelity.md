# Checklist — detector fidelity  ·  [judgment] judge · [agent] run

Live delivery uses the artifact-bound plan and certificate described in `docs/reference/scientific-results.md`. The diagnostic comparators below supply measured operands and attribution; their standalone PASS/WARN labels are not serving authority. Pin exact reference points, units, process/normalization basis and the comparison policy before approving it. Keep deterministic agreement, precision checks and full detector/coverage validation distinct.

Why this matters: between the showered truth events and the analysis selection sits a **detector
model** — object reconstruction, smearing, and efficiencies. If that model does not reproduce the
**performance the analysis actually had** (its trigger/reco/ID efficiencies, especially for *soft*
objects), the per-SR acceptance×efficiency is wrong by a model-dependent factor *before* any selection
logic runs. The failure is silent: the routine still produces yields, the cutflow still runs, the
limit still comes out — it is just biased. The classic symptom is a search whose sensitive regions
target **low-pT leptons** (compressed-spectrum SUSY) where an un-matched soft-lepton efficiency curve
loses roughly **half the acceptance** versus the published value — a degeneracy that no amount of
selection tuning downstream can recover, because the objects were already thrown away at reco. So
detector fidelity is a **measurable gate**, run once per routine + detector setup, not a per-analysis
hack: pick the path your routine uses, do the work, and record the verdict.

This gate sits between **generate** (step 3) and the limit, alongside the cutflow certification — it is
the *object-level* half of one-time pipeline certification (`validation.md` §B); the cutflow cert is
the *selection-level* half. Run both before any limit from a new routine is trusted.

## When it runs — two phases (a pre-run check, then a post-run re-run decision)
The gate brackets the analysis run; it is not one point:
1. **Pre-run setup check (cheap, before step 4).** The parts that need no analysis output: the Rivet
   `verify_smearing.py` static check, and (SA/Delphes) **matching the Delphes card** efficiencies to the
   analysis's published performance. Do these *before* the full analysis run so a bad detector setup is
   caught before the compute is spent.
2. **Post-run certification + the [judgment] re-run decision (after step 4).** The acc×eff **certification**
   (`certify_acceptance.py` for SA/Delphes, `validate_cutflow.py` for Rivet) needs the per-SR yields, so
   it is inherently a **post-analysis check-in**. Read its verdict:
   - **PASS / WARN-in-tier** → accept; record the residual + caveat.
   - **FAIL** → the **[judgment] judgment step**: decide *what* to adjust (re-tune the soft-object efficiency
     to the published curve, fix the era, correct the SR mapping) and **re-run** the affected stage(s).
     An *off-grid* result ("outside the published acc×eff grid") is NOT a FAIL to chase — the analysis
     was never sensitive there; choose an on-grid point instead.
   The loop is **certify → if FAIL, adjust → re-run → re-certify**, until in-tier or a documented limit.

## Which path — read the routine, don't assume
The two routine types handle detector effects differently (`docs/workflow/steps/04-analyze.md`), so the fidelity
work differs:
- **Rivet** routine → it carries its **own** detector model (smearing + efficiency projections). The
  gate is a **verify**: confirm the model is declared and era-appropriate.
- **SimpleAnalysis / Delphes** routine → detector effects come from an **external Delphes card**. The
  gate is **match-then-certify**: match the card's object efficiencies to the analysis's published
  performance, then certify the resulting per-SR acc×eff against the published map.

## Default: do NOT run Delphes — the scope (vetted via a full installed-share census)
A full census of the installed Rivet share settled the Delphes-routing policy. Of **2059** routines only
**22 self-smear**; of the 2037 that don't, **94.8% are SM measurements** (unfolded to particle level by
design) and only **25 (1.2%) are non-smearing BSM searches**. The default is therefore **NOT Delphes**:
- **Self-smearing routine** (`verify_smearing` → PASS) → use Rivet as-is; **never** feed it Delphes
  objects — that double-counts detector response (and Rivet consumes HepMC, not Delphes ROOT).
- **Non-smearing MEASUREMENT / fiducial routine** (the 94.8%) → particle-level by design; **no Delphes**
  (applying detector effects to an already-unfolded result is physically wrong).
- **Non-smearing BSM SEARCH routine** (the 25 — almost all pre-2016 legacy, since Rivet's `Smeared*`
  API is ~2016) → **the only Delphes-warranted case**: route to SimpleAnalysis/Delphes (Path B) or mark
  approximate.

The discriminator between the last two is **search-vs-measurement** (`.info` `Keywords`
`search/susy/bsm/exotica` + name patterns `_SUSY_/_SUS_/_EXOT_/_EXO_`) — the [judgment] fork in Path A step 3
below. The installed share is the complete, authoritative population — no upstream-API sweep is needed.

---

## Path A — Rivet routine: verify the routine's smearing  ·  [agent] run · [judgment] judge edge cases

A Rivet detector-level (`rivet-mkanalysis`-style search) routine declares its detector model inside
the routine: `SmearedJets`, `SmearedParticles`, `SmearedMET`, and efficiency functions
(`*_EFF_*`, `ELECTRON_*`, `MUON_*`, `JET_BTAG_*` from `Rivet/Tools/SmearingFunctions.hh`) wired up in
`init()`. Verification is a static check on the routine source — **no Rivet re-run**.

1. **Run the verifier on the routine source.**
   ```bash
   $CONDA run -n rivet python scripts/run.py ravel.validation.verify_smearing \
       --routine <RIVET_ID> [--source <path/to/ID.cc>]   # else resolves the installed share/Rivet/<ID>.cc
   ```
   It reports, per routine: whether smearing/efficiency projections are **declared**, which
   **detector era** the efficiency functions target (for example, smearing sets from different data-taking periods), and
   whether that era **matches** the analysis's data-taking period and √s. The verdict is the same
   three-state shape as the other gates (`PASS` / `WARN` / `FAIL`).

2. **Read the verdict — and the era.**
   - **PASS** — smearing + efficiencies declared, era matches the analysis. The routine is
     detector-level and self-contained; trust it (and note its Rivet `Status:`, e.g. `VALIDATED`).
   - **WARN** — declared but the era is ambiguous or only partially matched (e.g. a generic smearing
     set rather than the analysis-specific one). Record the caveat; it feeds the systematics
     statement (`statistics.md`: the fast-detector floor).
   - **FAIL — no smearing declared** ⇒ the routine is **particle-level (fiducial)**, not
     detector-level. This is the [judgment] fork (next).

3. **[judgment] — particle-level routine: pick one, and record the choice.** A fiducial routine applies no
   detector response, so its yields are *truth-fiducial*, not reconstructed. Two valid resolutions:
   - **Treat as fiducial** — if the analysis itself publishes a **fiducial** measurement (the cross
     section is defined at particle level), the routine is correct as-is. Record "fiducial — no
     detector model required" and proceed; the comparison is truth-to-truth.
   - **Route to a detector model** — if the analysis is a reconstructed-object search (most SUSY/exotic
     SRs), a fiducial Rivet routine is the wrong tool: switch to the **SimpleAnalysis/Delphes** path
     (Path B) for this analysis, or substitute a detector-level routine if one exists. Record the
     switch and why.

   Either way, **write the decision into the run's `provenance.json` and the fidelity verdict** so a
   later reader knows the yields are reconstructed vs fiducial.

---

## Path B — SimpleAnalysis / Delphes routine: match, then certify

Detector response is the external Delphes card. Two sub-steps: **(a) match** the card to the published
performance (the [judgment] procedure), then **(b) certify** the resulting per-SR acc×eff against the
published map (the [agent]-runnable gate, the SA-path analog of `validate_cutflow.py`).

### B(a) — Match the Delphes card to the published performance  ·  [judgment]
The Delphes object efficiencies are pt/η step functions (`Efficiency` modules, `set EfficiencyFormula
{…}` in the card). The default card values are generic — they are **not** a fit to any one analysis's
detector. The matching procedure replaces the relevant efficiency plateaus with the analysis's own
**published** performance, so the simulated objects are reconstructed with the same probability the
analysis had.

> **A bundled card can already encode the tuning.** If a bundled detector card states that it
> encodes the analysis's published object-efficiency curves, verify that claim against the
> publication (compare the curves) and confirm the run uses that card; then B(a) is satisfied and
> you go to B(b). Otherwise follow the procedure below.

1. **Find the published performance curves.** The analysis (or its auxiliary material / a companion
   performance paper) publishes object **efficiency vs pT (and η)** for the working points it used —
   trigger, reconstruction, identification, isolation. For a soft-object search these are the
   **low-pT lepton** (and/or soft-jet, b-tag) efficiency curves. Sources, in order: the paper's
   performance figures, the HEPData auxiliary tables/figures, the relevant public detector
   performance note for that working point. Use `fetch_figures.py` (step 5 helper) to pull the
   paper figures and digitise the curve.

2. **Identify which card modules govern the SR-relevant objects.** Distinguish **tracking**-efficiency
   modules from the final **reconstruction/identification**-efficiency modules — it is the *reco/ID*
   blocks that the matching edits (the tracking blocks model a different, upstream effect). Within
   those, the bins that move acceptance are the ones **inside the SR's kinematic window** — for a
   soft-lepton search, the lowest few pT rungs. Cross-check against the isolation and momentum-smearing
   modules, which also gate the *effective* efficiency in the soft regime.

3. **Edit the reco/ID `EfficiencyFormula` plateaus to the digitised published values**, respecting the
   detector's η acceptance edges. Edit only the bins the published curve covers; leave kinematic
   regions the SRs never touch alone.

4. **Keep the edit auditable.** Preserve the **original** efficiency block (commented) alongside the
   **tuned** active block in the card, so the change is reviewable and reversible. Record in the run's
   `provenance.json`: which modules were edited, the published source (figure/table + DOI/Inspire),
   and that the edit is a match to published performance (not an ad-hoc raise).

5. **A re-run is required to see the effect** (Delphes → SimpleAnalysis must re-process the events).
   This is heavier compute — schedule it as a generation/analysis re-run (`docs/workflow/steps/03`–`04`), not part of
   this gate's static work. The gate's *certification* (B(b)) then scores the re-run's yields.

> **WHY, concretely:** when the soft-object efficiency is left un-matched, a compressed-spectrum search
> loses roughly half its acceptance — the simulated leptons are too often *not reconstructed* in the
> exact pT window the SRs select. Matching the curve is what closes that gap. (Worked numbers live in
> the run records / the paper, not here.)

### B(b) — Certify the per-SR acc×eff against the published map  ·  [agent] run
After matching (and the re-run), certify that the **per-SR acceptance×efficiency** reproduces the
analysis's **published acc×eff map** (often a per-SR grid over the model's mass plane on HEPData /
in the paper). This mirrors `validate_cutflow.py` exactly — same tiered tolerance, same per-residual
attribution, same three-state verdict, same node-descriptor lookup — but its published target is the
**acc×eff map** rather than a single benchmark cutflow.

```bash
$CONDA run -n rivet python scripts/run.py ravel.validation.certify_acceptance \
    --srs "<SR1,SR2,…>"                `# comma list of SR names, NOT a path` \
    --acceptance <run acc×eff source>  `# SimpleAnalysis CSV (SR,events,acceptance,err) or sr_yields json` \
    --tables-dir <hepdata yaml dir> --grid "<grid-description matcher>" \
    --m-parent <m> --m-lsp <m>         `# the run's grid point (--dm <Δm> instead of --m-lsp)` \
    --rundir <rundir>                  `# tolerances come from the approved CHECK-IN 1 section` \
    [--region-map "<SR=published-region,…>"] [--acc-unit-scale <z-axis scale>] \
    [--driving-sr-override "<SR,…>"] \
    --out <rundir>/outputs/acceff_cert.md      # writes .md + sibling .json
```

Read the verdict (the `verdict` JSON field is the authority — the benchmark gate parses it, not the
exit code; any produced cert exits 0):
- **Tiers** — **driving** SR (best expected sensitivity, + within 1.5×) ≤ `driving-tol`;
  **contributing** ≤ `contributing-tol`; **tail** (<~5 events) report-only.
- **Attribution** — every residual above its tier emits a row with a `cause_class` (for the SA/Delphes
  path the soft-object case classes as a **`fast-sim-floor`** / reco-efficiency residual) and a bounded
  µ₉₅ impact for driving SRs.
- **Verdict** — **PASS** = a driving SR exists, all driving SRs within tol, and worst |Δµ₉₅| within
  bound; **WARN** = bounded + attributed; **FAIL** otherwise.
- **Node descriptor — be honest about off-grid points.** The published acc×eff map is a *grid*; the
  lookup records which path it took: an **exact** node, a **1-D interpolation** between bracketing
  nodes, or a **flagged nearest** node. If the run's point lies **outside** the published grid (e.g. a
  mass-splitting beyond the map's last node), there is no exact node and no valid bracket — the cert
  falls back to the **flagged-nearest** node and says so. Surface that flag in the verdict; the only
  honest claim there is "nearest published node, flagged", not a clean certification.
- **FAIL CAUSE — read which failure class fired before diagnosing.** Every FAIL prints (and stores in
  the json as `fail_reason`) which cause it is: **unevaluable** (a driving SR had no computable ratio —
  wrong `--grid`/`--region-map`, absent tables, missing routine yield → fix the *inputs*, the
  comparison never happened) vs **evaluated-but-over-tolerance** (the driving SR was read at a real
  published node and missed the tolerance → the comparison *worked*; diagnose the *physics* via the
  attribution rows, not the lookup). Chasing a `--region-map` problem on an over-tolerance FAIL wastes
  the diagnosis.
- **BASIS SUSPICION (catalogue A4) — a uniform ratio is a σ-basis fingerprint.** When every
  evaluated SR sits at the *same* ratio (spread ≤1.25×) but ≥20% from unity, the cert prints a
  basis-suspicion warning (also `basis_suspicion` in the json). A uniform **excess** is the A4 trap:
  the acceptance denominator is the **tagged** generated sample while the published map's denominator
  is the **inclusive** model σ — convert with A×ε_incl = A×ε_tag × f, f = σ_tag/σ_incl_LO from the
  same σ table the scan rebase uses, then re-certify. A uniform **deficit** points at one global cause
  (missing ME/PS merging, k-factor/σ basis, fast-sim floor) — decompose the normalization before
  touching any cut.

---

## Done when
- The path is chosen from the routine (not assumed), and the choice is recorded.
- **Rivet:** `verify_smearing.py` ran; verdict + era recorded; any fiducial-vs-detector fork resolved
  and written to `provenance.json`.
- **SimpleAnalysis/Delphes:** the card's SR-relevant reco/ID efficiencies are matched to the published
  performance (original + tuned blocks both kept, source cited), and `certify_acceptance.py` produced a
  verdict whose driving SRs are within tier tolerance (or the off-grid/attribution caveat is stated).
- The fidelity verdict is cited next to the cutflow cert in the run's certification record
  (`validation.md` §B) and its approximations feed the systematics statement (`statistics.md`).

## Declared detector-response calibration

`detector-calibration` fits a finite declared grid of supplied linear per-bin response
coefficients. It executes no simulator. Pin the frozen generated/showered sample lineage,
nominal yields, knob coefficients and intermediate per-bin observables in
`inputs/calibration/calibration-spec.json`. Each node declares a distinct node, a seed, a sample identity and byte pins for both
generated and showered samples (at most 64 MiB per supplied sample). Seeds must differ between the
calibration and held-out partitions; nodes within one partition can share a seed. The specification
declares calibration and held-out nodes, nominal knob values, candidate values, affected bins, bounds,
a pinned source with JSON pointers to the band endpoints, squared-error loss, stopping threshold and
trial budget. This adapter does not infer a missing response.

A pin is not authority. Every node sample, response and observable, every band anchor and every
imported calibration must have a custody record:
- a registered acquisition (an operator fetch or user upload of exactly those bytes), or
- a registered stage output from a recognized RAVEL module or native tool, named by
  `receipt_id` in the pin.

A file the agent wrote in the run is refused. Each knob's module must be listed in
`src/ravel/data/calibration/response_modules.json`. Signal-model completeness is the
registered `signal_model_complete_before_calibration` check result from `claim_checks` or
`patch_parity`, with a passed status. A scoped RDJ-authorized approximation is the alternative.

The agreement target uses the current target registry's `reference.pins` shape.
The approval verifier resolves valid current targets and refuses substituted pins.
`ravel.validation.calibration_checks.calibration_target_disjoint` refuses any claim-reference
or held-out pin among adaptive inputs, and a held-out pin as a band anchor. A band anchor can
come from the claim's reference record. A calibration observable whose values repeat a numeric
vector of the reference pins is refused. Only signal yields, efficiency maps and cutflows
are admitted as calibration observables. A global signal scalar is refused, whether it is an
extra field or a knob that covers every bin with coefficients proportional to the nominal
response.

Before fitting, approve the exact `calibration-spec.json` bytes through the ordinary
CHECK-IN 1 workflow and obtain the R2 calibration authorization for
`detector_calibration.calibration_action(spec)`. Out-of-band candidates need R3 and a human
CHECK-IN 2 approval. The fitter replays the public approval and RDJ verifiers; it accepts no
loose approval flag. Run:

```bash
python -m ravel.physics.detector_calibration --rundir RUN fit --spec RUN/inputs/calibration/calibration-spec.json --out RUN/outputs/calibration/epoch-1
```

The producer can read only calibration artifacts. The evaluator wrapper writes every
read and trial to a hash-chained journal under the existing machine exposure authority,
with the `adaptive_full` and `withheld_confirmation` exposure labels and a per-study run copy
at `<run>/research/calibration/<study_id>.jsonl`, so a second study in the same run has its own
journal. Failed reads remain spent. The preregistration digest binds the node population; trial
counts persist across run directories. Refitting creates a new immutable response and freeze,
invalidates the previous epoch and retains the trials. A spent held-out population must not be
reused for a new calibration.

Exposure is also kept per agreement target, keyed by the sha256 of its reference pins rather
than by study. Every receipt reports the cumulative `target_trials` across studies. A held-out
value vector already scored for the target is refused in any later study, including one built
from re-serialized copies. Held-out files are ordinary run files, so each receipt records
`sealing: evaluator-convention`; operating-system separation is the worker sandbox's job.

Pin both the response and freeze in a renewed ordinary approval before confirmation,
and obtain an R2 calibration receipt for the same specification and response hash.
Only the evaluator runs:

```bash
python -m ravel.physics.detector_calibration --rundir RUN confirm --freeze RUN/outputs/calibration/epoch-1/freeze.json
```

Confirmation reads each held-out node once after the freeze, delivering uncalibrated and
calibrated per-bin predictions and scores together. Reconcile the delivered bytes and
both journal heads with `detector_calibration.verify_delivery`. It reads no held-out
artifacts. It refuses a receipt written under the test exposure namespace unless the caller
passes `allow_test_namespace=True`. Imported responses carry
`imported_calibration {source, fitted_on, response}`. The source and response need custody
records, and `fitted_on` must not name a held-out node. An import fitted on this study's
calibration nodes is in-sample for this target (`imported_in_sample`), and
`delivery_check(..., evidence_status="validated")` refuses it. The adapter emits `checked`, which establishes no detector or physics
validation. The detector-calibrator production card forbids held-out artifacts and the
claim quantity; the skeptical verifier and integrity auditor review its result.

Integration seams: the operation-signature owner merges
`src/ravel/data/calibration/operation_signature.json` after `signature_conformance --entries`.
`calibration_checks.gate_errors` is the registered `calibration` provider at `checkin2_accept`
and `delivery`. It replays a pinned `calibration_spec` action field and refuses a
`detector-calibration` action without one. The delivery owner consumes `verify_delivery` with
its proposed evidence status. The shared research
`confirm_cell` journal interface remains an integration handoff; this evaluator uses the
existing machine-wide exposure namespace and lock with its own calibration cell journal.
