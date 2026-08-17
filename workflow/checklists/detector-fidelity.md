# Checklist — detector fidelity  ·  [judgment] judge · [agent] run

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
The two routine types handle detector effects differently (`steps/04-analyze.md`), so the fidelity
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
   $CONDA run -n rivet python trial-runs/_infrastructure/verify_smearing.py \
       --routine <RIVET_ID> [--source <path/to/ID.cc>]   # else resolves the installed share/Rivet/<ID>.cc
   ```
   It reports, per routine: whether smearing/efficiency projections are **declared**, which
   **detector era** the efficiency functions target (e.g. a Run-2 vs Run-1 ATLAS smearing set), and
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

> **Already matched for EwkCompressed2018 / slepton-bino (the RRR Fig-3 analysis):** the bundled card
> `…/share/mapyde/cards/delphes/delphes_card_ATLAS_lowptleptons_sleptons_notrackineffic.tcl` ALREADY
> encodes the RRR §3.2 soft-lepton efficiency tuning (it matches the paper's tuned e/µ low-pT curves —
> verified byte-for-byte in a prior run prep). So for THIS analysis B(a) is **pre-satisfied**: do NOT
> hand-digitize — just confirm the run uses that card (the native backend and bundled `sleptons.toml`
> both default to it), then go straight to B(b) certify. The hand-digitize procedure below is the
> general recipe for a *new* soft-object analysis that has no pre-tuned card.

1. **Find the published performance curves.** The analysis (or its auxiliary material / a companion
   performance paper) publishes object **efficiency vs pT (and η)** for the working points it used —
   trigger, reconstruction, identification, isolation. For a soft-object search these are the
   **low-pT lepton** (and/or soft-jet, b-tag) efficiency curves. Sources, in order: the paper's
   performance figures, the HEPData auxiliary tables/figures, the relevant ATLAS/CMS public
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
   This is heavier compute — schedule it as a generation/analysis re-run (`steps/03`–`04`), not part of
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
$CONDA run -n rivet python trial-runs/_infrastructure/certify_acceptance.py \
    --srs "<SR1,SR2,…>"            `# comma list of SR names, NOT a path` \
    --acceff <run acc×eff source>  `# the run's per-SR acc×eff (selected/generated)` \
    --tables-dir <hepdata yaml dir> --grid "<grid-description matcher>" \
    --m-parent <m> --m-lsp <m>     `# the run's grid point` \
    --driving-tol 0.15 --contributing-tol 0.25 --mu95-bound 0.10 \
    [--exclusion <run exclusion.json>] [--driving-sr-override "<SR,…>"] \
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
