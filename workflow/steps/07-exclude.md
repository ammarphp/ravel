# Step 7 — Exclusion (pyhf)  ·  [judgment — script-assisted: the mode table in `checklists/exclusion-model.md` + what HEPData provides decide; `pyhf_exclude.py` runs it]  · CHECK-IN
`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda` — every `$CONDA` below.

Turn the comparison into a 95% CL upper limit on the signal strength µ with **pyhf** — the standard
statistical tool. Never hand-roll the statistical model. Pick the mode by what step 6 produced.

## Mode A — serialized likelihood (preferred when published)
A `stat_mode=published-likelihood` run pairs the chain's signal patch against the published
background-only workspace BEFORE the limit: run the likelihood↔selection pairing gate (structural
channel/bin-count agreement), which emits `pairing_check.json`:
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/pairing_check.py \
  --bkg <bkg_only>.json --patch <signal_patch>.json
#   verdict="pass" iff paired and no mismatches; `validate_run_state.py` enforces this gate
#   (the likelihood-selection-pairing invariant) whenever stat_mode=published-likelihood.
```
Then apply the signal patch to the published background-only workspace and fit:
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/pyhf_exclude.py likelihood \
  --bkg <bkg_only>.json --patch <signal_patch>.json \
  --out <rundir>/outputs/pyhf_exclusion --label "<model> vs <analysis>"
```

## Mode B — counting model (no published likelihood)
Build one single-bin counting model per SR from `sr_yields.json` (observed, background±unc, signal);
the limit is quoted from the single most-sensitive SR (best expected CLs) — the standard prescription
when SRs overlap and cannot be combined:
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/pyhf_exclude.py counting \
  --srs <rundir>/outputs/sr_yields.json \
  --out <rundir>/outputs/pyhf_exclusion --label "<model> vs <analysis>"
```

Both write `exclusion.json` (observed + expected ±1,2σ limits, the CLs-vs-µ scan) and `exclusion.png`
(CLs vs µ with the 0.05 line and the limit). **The result is the verdict on this model point:
excluded if the observed µ₉₅ < 1, otherwise allowed** — the model under test is typically one the
analysis's authors never considered, so this limit stands on its own.

## NLO+NLL normalisation (the σ the limit rides on)
MadGraph's LO σ is systematically low — for strong production the k-factor σ_NLO+NLL/σ_LO runs
typically ~1.2–2×, **but it can be < 1** (LO-PDF overshoot, or a flavour/charge-
degeneracy mismatch between the WG grid and the generated process) — so a bare-LO limit is **not always
conservative**. Always derive k for the *actual* process rather than assuming a value; `nlo_xsec.py`
warns when k < 1. Pull the higher-order σ + k-factor from the LHC SUSY x-sec WG grids
and pass it through:
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/nlo_xsec.py \
  --process <gluino|squark|stop|sbottom|wino-c1n2|slepton> --mass <m> --out <rundir>/outputs/nlo.json
#   → σ_NLO+NLL (pb), k = σ_NLO/σ_LO, source stamped into nlo.json
$CONDA run -n rivet python trial-runs/_infrastructure/pyhf_exclude.py <likelihood|counting> … \
  --sigma-scale <k>            # scales obs+exp µ₉₅ by 1/k onto the NLO normalisation
```
This keeps acceptance×efficiency cross-section-independent (the cert in `checklists/validation.md` is
unchanged) while the **limit** rides on the NLO+NLL σ. `exclusion.json` then carries `sigma_scale_k`
and the LO limit (`obs_limit_lo`) alongside the NLO one. If the process has no WG grid, quote LO and
state the k-factor range used — never silently leave the limit on LO.

## Reaching the real limit (the µ=2 lesson)
The limit must be the true 95% CL crossing — where CLs falls to 0.05. A fixed µ scan (e.g. mapyde's
default 0.1–2.0) can stop before the crossing: if CLs at the top of the grid is still ≫ 0.05, the
model is simply weakly constrained and the limit lies beyond the grid. `pyhf_exclude.py` removes that
truncation — it brackets µ (doubling until CLs < 0.05) and interpolates the crossing, so the reported
limit is real even when it is large. (For a full-likelihood fit each point is a many-parameter fit;
expect minutes, not seconds.)

## Make the limit trustworthy (intrinsic rigor)
A µ₉₅ is only as good as its inputs, and there is usually no published result for this model to lean
on. Ensure rigor at the source:
- the statistical model is the analysis's own (its published likelihood, or its observed+background
  per SR), paired with the matching selection (`checklists/data-acquisition.md`);
- the signal cross-section carries its higher-order normalisation (NLO+NLL where available), not bare
  LO (`checklists/generation-settings.md`);
- the signal yield comes from a pipeline whose acceptance×efficiency was validated once, on a
  benchmark the authors *did* publish, to a stated tolerance — see `checklists/validation.md`. That
  one-time check certifies the routine; new model points then inherit it.

A counting model on a single SR with a floored background uncertainty is an approximation of the full
likelihood; quote it as such, and prefer the published likelihood when one exists.

**Enforced (D12/G14):** `validate_run_state.py`'s `certify-before-limit` invariant hard-BLOCKS any
limit-shipping run (incl. a scan) whose acc×eff cert verdict is FAIL — or that carries **no**
discoverable cert at all — before `exclusion.json`/`scan.json`/the result-pack ships. Only a PASS/WARN
cert may feed a limit; the analysis STAGE merely WARNs on a FAIL cert (records the pointer), but this
invariant is the hard block. A complete scan's per-point `scan.json` attestation does **not** waive the
cert: the aggregator must carry a discoverable (aggregate or per-point) acc×eff cert — otherwise the
scan hard-FAILs.

**Plausibility emitter (D14):** the moment `sr_yields.json` and `exclusion.json` both exist and BEFORE
the limit ships, emit `python3 trial-runs/_infrastructure/sr_plausibility.py --rundir <rundir>` (add
`--sigma-ref-fb F --lumi-fb F` to also band the driving-SR acc×eff — catches the "956% acc×eff" defect
class). It writes `outputs/sr_plausibility.json` with an EARNED `verdict ∈ {plausible, implausible}`
(never defaults to plausible) over four analysis→statistics sanity checks — ≥1 non-trivial SR carries
signal, µ₉₅ finite and off the floor/ceiling, `excluded_obs == (µ₉₅ < 1.0)`, and the optional
driving-SR acc×eff band — exit 1 on `implausible`. This is a plausibility-domain artifact with its own
`input_fingerprint`; it is deliberately NOT a `provenance.py`-verified lifecycle artifact (D-7).

**Plausibility FOLD (D14, enforced):** `validate_run_state.py`'s `check_statistics` reads that
`sr_plausibility.json` for single-point limit modes (`exclusion.json`/`shape_fit.json`; scan mode is
attested per-point elsewhere) and folds an `implausible` verdict into a **hard statistics FAIL** — so an
all-zero-yield run can no longer ship a vacuous "not excluded". It also FAILs a `shape_fit.json` whose
`excluded_obs` contradicts `mu95_obs < 1.0`. A MISSING `sr_plausibility.json` is INFO (advisory, never
gating); a `plausible` verdict is a PASS check. Run `sr_plausibility.py` before the limit ships so the
gate has the artifact to fold.

## Sensitivity-only studies (no observed-data claim — the expected-only recipe)
When the deliverable is a SENSITIVITY comparison (tagger what-ifs, particle-level AD studies,
projections), do NOT force a pyhf observed limit: quote the expected discrimination (S/√B on
the discriminating observable, or expected-CLs with the observed column suppressed), label
everything **expected-only**, and pack with `result_pack.py --stat-mode
sensitivity-expected-only` (`none-survey` for pure surveys). The 95%-CLs-never-discovery rule
still governs the wording.

## Measurement routines (not searches)
If the routine is a **measurement** (not a search), the exclusion route is Contur instead:
```bash
$CONDA run -n rivet bash -c "cd <rundir>/build && contur analysis.yoda -c config.dat -o contur_out"
```
`config.dat` needs `[signal]`,`[uncertainties]`,`[models]`,`[calculations]`,`[theory_predictions]`
(adapt `…/share/contur/tests/sources/custom_config.dat`). Contur targets measurements; it has no
likelihood for most searches.

## The RESULT-PACK — emit `result.json` (the run's machine-checkable headline)
Once the limit is in hand, assemble the run's **RESULT-PACK headline**: a thin, versioned `result.json`
that is the run's self-describing answer. It POINTS at (does not re-store) `sr_yields.json` /
`exclusion.json` / `provenance.json` / the cert json, and carries the headline + verdict fields a reader
(the benchmark gate, the audit) would otherwise reconstruct from scattered JSON + provenance prose:
driving SR, µ₉₅ obs/exp + the 5-entry expected band, driving-SR s95, best SR, the σ reference + k-factor,
the cert verdict + A×ε tier, the fidelity verdict, and the µ₉₅-stability anchor. It REQUIRES two enums —
`stat_mode` and `detector_mode` — so a counting vs likelihood vs stability-only run, and a Rivet vs
SimpleAnalysis/Delphes vs particle-level path, are explicit rather than buried in prose:
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/result_pack.py \
  --rundir <rundir> \
  --stat-mode <published-likelihood|simplified-likelihood|best-sr-counting|combined-counting|stability-only|blocked-shape-fit> \
  --detector-mode <rivet-smearing|simpleanalysis-delphes|particle-level> \
  --m-parent <M> --m-lsp <M> --lumi-fb <L> \
  --limitations '<key>:<text> | <key2>:<text2>'      # keyed, separator '|' (or ';' before a key:)
#   → <rundir>/result.json  + <rundir>/figures.json  (schema_version=1)
```
The pack normalizes the two on-disk layout conventions (in-run `outputs/cutflow_cert.json` vs the
`framework/validation/<id>.json` sibling; bracketed pyhf channel names `SR3L[SR3L_Low]`; an absent /
stub / populated plots `INDEX.md`) into ONE shape, and fails loud if a required source artifact is
missing. Pick `stat_mode` by the mode used above (a single-best-SR counting limit is `best-sr-counting`;
a multi-SR counting combination is `combined-counting`; no-HEPData stability-only registrations are
`stability-only`). When the on-disk `exclusion.json` is NOT the scored headline (e.g. a single-SR
artifact kept while the scored mode is the combined fit), declare the scored structure in `stat_mode` and
key the discrepancy in `--limitations` (the pack reports the on-disk artifact faithfully).

Record the limit (observed + expected µ₉₅, the mode used, and the verdict for this model point) in the
run's `RESULT.md` — which is the **human narrative GENERATED-FROM / cross-checked against `result.json`**
(the numbers in the prose are the numbers in the pack). When this point IS the run's deliverable
(no step-8 scan follows), the final check-in is the **RESULTS DECK** (`checklists/check-ins.md`),
sent only after the step-9 verification panel (`steps/09-verify.md`) with its verdict + findings
appended verbatim. If a scan follows, report the point briefly and continue to `steps/08-scan.md`.
