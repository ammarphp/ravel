# Comparative experiments

These controls measure whether a requested deliverable is produced, what physics
recipe actually runs, and which failures prevent delivery. They do not turn a
successful refusal, a software exit code, or a plausible plot into a physics pass.

The [September pilot](../../docs/research/2026-09-09-comparative-pilot.md) records
the public revisions, actual execution conditions and remaining capability gaps.
It is exploratory evidence, not a leaderboard or a publication-grade success rate.

## Experimental policy

1. Freeze the framework revision, requested model, prompt bytes, supplied inputs,
   reference definition, budget and memory condition before each baseline. Keep
   modified Ravel development code separate from the frozen public baseline.
2. Use the same requested model where the framework supports it. Record actual
   parent and consultant model receipts. A paper-only system, a missing API key,
   a local-model-only interface and a framework runtime failure are different
   availability outcomes. Do not simulate an unavailable system and name it as
   the original.
3. In the scripted affirmative condition, preserve every concrete check-in and
   its proposal hash. Record `decision: yes`, `authority: standing-user-instruction`,
   `reviewer_kind: scripted_affirmative`, and `substantive_expert_review: false`.
   The record acknowledges an experimental operating policy. It supplies no
   substantive physics correction and cannot waive an invalidity gate.
4. Count a scope refusal as an unmet product request. Record what must be built
   and what would verify it. Separately judge whether stopping was scientifically
   appropriate. Never remove refusals, timeouts, crashes or missing artifacts
   from the assigned-task denominator.
5. Preserve the unmodified tool integration. A documented native route, an
   environment repair and a newly written fallback adapter must be labeled
   separately. Record retries and setup time; do not replace the first failure
   with the successful attempt.
6. Separate matched-prompt tests from matched-physics tests. Compare executed
   beams, processes, model restrictions, perturbative orders, PDFs, scales,
   cuts, normalization and response before comparing numerical predictions.
   An agent choosing a different valid scale is a recipe difference, not by
   itself an inaccurate simulator.
7. Inspect actual output records and figures. Verify numerical cells, units,
   normalization, missing bins and contour support independently. A physics
   validation requires an appropriate experimental or independently validated
   reference; internal arithmetic consistency is insufficient.

For a prospective causal comparison, use the separate
[governance experiment registry](../governance/README.md). Its deliberate
refusal controls test judgment; their success is not delivery of an unsupported
physics task. Historical probes and the pilot must not be relabeled as that
prospective experiment.

## Cheap generation audit

`audit_drell_yan.py` reads an actual LHE file independently of the producer. The
fixed pilot request is 100 SM `pp -> e+ e-` events, 13 TeV, seed 1729, built-in
cteq6l1, each lepton pT above 10 GeV and absolute eta below 2.5, and pair mass
above 40 GeV. It checks the recorded beam/seed/PDF, cross section, event census,
constant positive weights and all final-state kinematics. Threshold comparisons
allow a 1e-8 numerical rounding margin. Cross-section weights need not equal one.

```sh
python3 benchmarks/comparative/audit_drell_yan.py sample.lhe.gz --out audit.json
```

This is a delivery audit. It does not independently prove the generator's
unweighting algorithm, matrix elements, perturbative accuracy or detector response.
Retain and inspect the generator's process/run cards and execution log as well.
The auditor does not invent a reference cross section for differing scale choices.

## Next control ladder

| Control | Independent endpoint | What it can diagnose |
|---|---|---|
| SM Drell-Yan generation | Actual LHE census, cards, cuts, figures | Intake, missing execution routes, compiler/runtime setup, recipe drift |
| ATLAS 2016 2jl counting approximation | Bracketed observed/expected CLs roots and units | Likelihood construction, numerical inversion, result/plot transport |
| Published particle-level fiducial analysis | Paper object/cut definitions and cutflow on fixed events | Analysis translation and object/region semantics |
| Published reconstructed-object control | Validated response and differential migration | Detector approximations and threshold behavior |
| RRR compressed-slepton reproduction | Matched effective recipe, acceptance, fitted-bin shapes and supported contour | Full scientific fidelity, including the unresolved low-splitting behavior |

The first two controls cannot substitute for the last three. Use the cheapest
control that separates the current hypotheses before generating another sample.
