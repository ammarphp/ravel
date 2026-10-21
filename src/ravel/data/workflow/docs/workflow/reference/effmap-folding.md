# Reference — efficiency-map folding (step 4 · Option D)

Use published efficiency maps for long-lived/displaced objects (trap
T2) and for fast simplified-model recasts without any routine: fold PUBLISHED per-SR or per-object
efficiency maps over the model point instead of simulating the detector response.

## D1 — simplified-model folding via SModelS (the SUSY-shaped mass)
**Supply:** the historical capability census reported 1113 SR datasets and 135 analysis
records, with 90% efficiency-map datasets. Those dated counts are not the current pinned
database denominator. Each executed portfolio records its selected database census.
**Mechanics:** the supplied SLHA/LHE retains its production cross sections, spectrum and
decays. SModelS decomposes it into simplified topologies and evaluates the selected source
maps and native within-analysis likelihoods. The complete portfolio uses all result types,
retains every admitted prediction and native coverage group, and chooses its reported
constraint using predeclared apriori expected sensitivity. `--data-types efficiencyMap`
requests a restricted fold and omits upper-limit result types from that calculation.
```bash
ravel model-portfolio plan --input <supplied.slha> --source '<input attribution>' \
    --python <SModelS-3.1.1-python> --database <official311.pcl> \
    --database-source <trusted-HTTPS-source> --trust-database-pickle \
    --data-types efficiencyMap --review-policy <review-policy-wrapper.json> --rundir <new-study>
# Review the actual version 2 CHECK-IN 1 and prospective policy, then approve/run.
```
An efficiency-map fold and an upper-limit lookup can return different r values for the same
point: the fold reports the best signal region with an expected value, the lookup interpolates
the published contour; both scale as 1/µ₉₅.
**Honest caps (state in every deliverable):** topology and lifetime coverage is partial;
uncovered contributions do not establish a full-model non-exclusion. A point outside every
grid has no applicable prediction. Observed-only constraints remain informational when
expected sensitivity is missing. Native coverage groups overlap and must not be summed.
Report the actual native statistical backend and
the restricted/full result-type selector; `detector_mode=effmap-folded` establishes no detector
simulation fidelity. Use the default `--data-types all` for the complete supplied-model portfolio.

## D2 — per-object efficiency-map folding with supplied truth events
**Supply confirmed standard practice:** LLP searches publish per-object efficiency
parameterizations in YAML on HEPData (for example a multi-dimensional map with a documented
accuracy and an explicit validity envelope; disappearing/displaced-track analyses ship
per-tracklet maps for reinterpretation).
**Design (the displaced-LLP worked plan):**
1. Truth-level events (LHE→hepmc or direct parton-level with decays; NO Delphes).
2. For each truth object entering the analysis's selection, look up ε(object kinematics, decay
   position/cτ, …) from the published map; per-event weight = Π ε × selection acceptance on
   truth quantities the paper defines at truth level.
3. Per-SR expected yields = σ · L · ⟨weight⟩ can feed separately constructed pyhf counting
   inputs (or the published likelihood where it exists), with map-coverage and validation
   obligations retained → µ₉₅ exactly as step 7.
4. **Validation gate (ladder R5, non-negotiable):** reproduce the paper's own limit at ≥2
   published points within the map's documented accuracy BEFORE any reinterpretation ships;
   record the map version + validity envelope in the basis manifest; points outside the envelope
   are flagged, never silently extrapolated.
**Tool (built): `src/ravel/physics/effmap_fold.py`** — HEPData-style YAML/JSON row-wise
map reader (1-D..N-D; `low`/`high` bins or point-`value` bins with midpoint-synthesized edges),
envelope-honest lookup (outside any axis → `None`, counted + reported per axis/map — NEVER
clamped, never zeroed at lookup level; in-envelope grid holes counted separately), truth-object
folder (per-event weight = Π ε(object) × the upstream `"selected"` flag; generator weights
honoured; unmapped selected events fold to 0 as an explicit convention over the full-sample
mean, with unknown omitted response), per-SR yield = σ_pb·1000·L_fb·⟨w⟩ + a per-event weights
JSONL for audit. The scalar yield can feed separately constructed counting inputs, subject to
the scientific obligations below. Prepare the downstream pyhf counting inputs separately. Every
non-selftest run prints the step-4 R5 gate. `map_coverage` reports omitted event-level
signed, absolute, positive and negative generator-weight sums, plus negative-weight counts.
These sums describe the omitted population, not its unknown efficiency-weighted contribution
(`omitted_weighted_response_sum` is null unless known zero generator weights or mapped factors
force the omitted contribution to zero). Counts include
in-envelope holes. The coverage scope is only selected events and kinds named in the spec;
ignored kinds and zero-object events retain their existing diagnostics.
Zero filling does not establish a conservative yield or exclusion bound. For example, a +2
unit-efficiency mapped event and a -1 unmapped event give a zero-filled mean of 2, while a
unit response for both would give 1. Even with positive weights, a lower omitted-response
contribution requires physical nonnegative responses, and a conservative exclusion does not
follow from arithmetic alone. Retain partial coverage and unknown response in any downstream
interpretation; the separate R5 comparison must not substitute for evidence about the omitted
domain. `--selftest` PASS (5/5, deterministic): 2-D analytic
closure ⟨w⟩=0.414656 vs 0.4143750 exact (0.068% — MC-stat-limited; binning residual 0.0015%),
planted out-of-envelope events counted exactly (7/5/3 per axis), 2-object weight ≡ product of
the two lookups (bitwise), 1-D point-value maps, selection flag.
```bash
<conda> run -n rivet python scripts/run.py ravel.physics.effmap_fold --selftest
<conda> run -n rivet python scripts/run.py ravel.physics.effmap_fold inspect --map <map.yaml>
<conda> run -n rivet python scripts/run.py ravel.physics.effmap_fold fold \
    --events <truth.jsonl> --spec <fold-spec.json> --sigma-pb <σ> --lumi-fb <L> --out <dir>
```
Spec: `{"sr_name":…, "maps":{"m":{"file":"map.yaml"}}, "objects":{"muon":{"map":"m","axes":
["pt","abseta"]}}}` (map paths relative to the spec file); events = JSONL/JSON list of
`{"objects":[{"kind":…, <axis>:<value>…}…], "weight":opt, "selected":opt}` — upstream truth code
decides which objects enter the product and precomputes `selected`; the folder does no selection.
**Validation status:**
the reader parses a published per-object map unmodified; the statistics half is the counting mode of
`pyhf_exclude`; the fold arithmetic is checked by `--selftest` against an analytic mean weight.
End-to-end closure (reproducing a published σ_UL at two or more (mass, τ) points) additionally needs
a truth-level event maker and the analysis's truth selection (sample r = βγ·cτ·(−ln u), fold ε(η, r)) —
parton/truth level, no Delphes; the truth (η, decay-radius) distribution is model-specific, so it
must be generated. Fetch recipe: `hepdata-cli download <record> -i inspire -f yaml`; resources via
`/record/resource/<id>?view=true`.

## Routing (when Option D fires — see `docs/workflow/checklists/physics-traps.md`)
- T2 hit (any BSM state with cτ ≳ 0.1 mm) → D2 is THE route; the standard chain silently fails.
- No routine + the model decomposes into SUSY-cascade topologies → D1 beats Option C on speed
  and rigor (published A×ε, expected limits) — try D1 BEFORE Option C.
- Routine exists → the standard chain stays primary; D1 remains the independent cross-check.
