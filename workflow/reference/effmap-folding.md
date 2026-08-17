# Reference — efficiency-map folding (step 4 · Option D)

The route for analyses/objects the standard chain cannot reconstruct (long-lived/displaced — trap
T2) and for fast simplified-model recasts without any routine: fold PUBLISHED per-SR or per-object
efficiency maps over the model point instead of simulating the detector response.

## D1 — simplified-model folding via SModelS (BUILT; the SUSY-shaped mass)
**Supply:** 90% of the SModelS database's 1113 SR-datasets are efficiency-map type (47% of its
135 analyses have EM data; 121/135 are SUSY-cascade topologies) — the capability census
(`framework/interrogations/capability-census.md`).
**Mechanics:** the model point (SLHA + σ) decomposes into simplified-model topologies; SModelS
folds each analysis's published per-SR A×ε grid → per-SR expected yields → r = σ_pred/σ_UL with
observed AND expected values + the best SR.
```bash
<conda> run -n reinterp python trial-runs/_infrastructure/reinterpret_db.py \
    --slha <card> --sigma-pb <σ> --proc "<pdg pdg>" --data-select efficiencyMap --out <dir>
```
Live acceptance test (2026-07-07, gluino (1000,100), σ=0.325 pb): 4 analyses fold and exclude,
e.g. `ATLAS-SUSY-2015-06 r_obs=13.04 r_exp=7.66` — vs the UL-type lookup's r_obs=8.07 for the
same point (different result types; EM gives best-SR + expected, UL interpolates the published
contour; both O(1/µ₉₅)).
**Honest caps (state in every deliverable):** topology coverage is partial (missed topologies →
UNDERcoverage → conservative); grids have validity envelopes; a point outside every grid returns
nothing, not zero. Non-SUSY models find only the ~14-analysis EXOT slice. `stat_mode`:
`counting` via SModelS's published grids; label `detector_mode=effmap-folded`.

## D2 — per-object efficiency-map folding (BUILT + selftest-verified; reader + statistics-half VALIDATED on real ATLAS-SUSY-2016-06 data 2026-07-07; truth-event-maker = the named last mile)
**Supply confirmed standard practice:** LLP searches publish per-object efficiency
parameterizations in YAML on HEPData (template: ATLAS-EXOT-2019-23's 6-D map with documented
~25% accuracy + explicit validity envelope; disappearing/displaced-track analyses ship
per-tracklet maps for reinterpretation).
**Design (the P7 displaced worked plan):**
1. Truth-level events (LHE→hepmc or direct parton-level with decays; NO Delphes).
2. For each truth object entering the analysis's selection, look up ε(object kinematics, decay
   position/cτ, …) from the published map; per-event weight = Π ε × selection acceptance on
   truth quantities the paper defines at truth level.
3. Per-SR expected yields = σ · L · ⟨weight⟩ → pyhf counting (or the published likelihood where
   it exists) → µ₉₅ exactly as step 7.
4. **Validation gate (ladder R5, non-negotiable):** reproduce the paper's own limit at ≥2
   published points within the map's documented accuracy BEFORE any reinterpretation ships;
   record the map version + validity envelope in the basis manifest; points outside the envelope
   are flagged, never silently extrapolated.
**Tool (built): `trial-runs/_infrastructure/effmap_fold.py`** — HEPData-style YAML/JSON row-wise
map reader (1-D..N-D; `low`/`high` bins or point-`value` bins with midpoint-synthesized edges),
envelope-honest lookup (outside any axis → `None`, counted + reported per axis/map — NEVER
clamped, never zeroed at lookup level; in-envelope grid holes counted separately), truth-object
folder (per-event weight = Π ε(object) × the upstream `"selected"` flag; generator weights
honoured; envelope-excluded events fold to 0 = conservative under-coverage over the full-sample
mean), per-SR yield = σ_pb·1000·L_fb·⟨w⟩ + a per-event weights JSONL for pyhf counting. Every
non-selftest run prints the step-4 R5 gate. `--selftest` PASS (5/5, deterministic): 2-D analytic
closure ⟨w⟩=0.414656 vs 0.4143750 exact (0.068% — MC-stat-limited; binning residual 0.0015%),
planted out-of-envelope events counted exactly (7/5/3 per axis), 2-object weight ≡ product of
the two lookups (bitwise), 1-D point-value maps, selection flag.
```bash
<conda> run -n rivet python trial-runs/_infrastructure/effmap_fold.py --selftest
<conda> run -n rivet python trial-runs/_infrastructure/effmap_fold.py inspect --map <map.yaml>
<conda> run -n rivet python trial-runs/_infrastructure/effmap_fold.py fold \
    --events <truth.jsonl> --spec <fold-spec.json> --sigma-pb <σ> --lumi-fb <L> --out <dir>
```
Spec: `{"sr_name":…, "maps":{"m":{"file":"map.yaml"}}, "objects":{"muon":{"map":"m","axes":
["pt","abseta"]}}}` (map paths relative to the spec file); events = JSONL/JSON list of
`{"objects":[{"kind":…, <axis>:<value>…}…], "weight":opt, "selected":opt}` — upstream truth code
decides which objects enter the product and precomputes `selected`; the folder does no selection.
**Validation status (2026-07-07, dev-repo validation record):**
the D2 supply assumption is CONFIRMED on a real, fully-public case — ATLAS-SUSY-2016-06
disappearing-track (arXiv:1712.02118) publishes a genuine per-object map ε(chargino η, decay-radius)
(Fig18b EW / Fig18d Strong). VALIDATED tonight without heavy generation: (a) the reader parses the
real map unmodified (no units warning); (b) the STATISTICS half — `pyhf_exclude counting` on the real
SR inputs (N_obs=9, bkg=11.8±3.1, 36.1 fb⁻¹) reproduces the published model-independent σ_vis^95%:
0.204 fb obs / 0.253 fb exp vs published 0.22 / 0.28 (+0.11−0.08), a 7–10% counting-vs-profile gap;
(c) the fold arithmetic by `--selftest` (analytic ⟨w⟩ 0.068%). **The single remaining last mile for
FULL end-to-end R5 closure** (reproduce σ_UL at ≥2 (mass, τ) points): a truth-level wino event maker
+ the disappearing-track truth selection (sample r = βγ·cτ·(−ln u), fold ε(η, r)) — parton/truth
level, NO Delphes, minutes/point; the truth (η, decay-radius) distribution is model-specific and
unpublished, so it must be generated. Fetch recipe: `hepdata-cli download ins1641262 -i inspire -f
yaml`; resources via `/record/resource/<id>?view=true`.

## Routing (when Option D fires — see `checklists/physics-traps.md`)
- T2 hit (any BSM state with cτ ≳ 0.1 mm) → D2 is THE route; the standard chain silently fails.
- No routine + the model decomposes into SUSY-cascade topologies → D1 beats Option C on speed
  and rigor (published A×ε, expected limits) — try D1 BEFORE Option C.
- Routine exists → the standard chain stays primary; D1 remains the independent cross-check
  (its original role, `framework/crosscheck/`).
