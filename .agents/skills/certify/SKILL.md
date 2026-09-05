---
name: certify
description: Certify acceptance×efficiency against the published values with the tiered+attribution gate — certify_acceptance.py (PER-RUN, SimpleAnalysis/Delphes/native, step 3.5) vs validate_cutflow.py (ONE-TIME per Rivet routine). Fire the moment a run in hep-agentic-pipeline has SR yields, BEFORE those yields feed a limit or a delivery.
when_to_use: after a run has SR yields and needs the tiered PASS/WARN/FAIL certification vs published acc×eff; or a new routine needs its one-time cutflow validation
allowed-tools: Bash, Read
---
# Skill — certify a run (tiered + attribution; pick the right engine)

Domain detail: `.claude/rules/statistics.md`. The gate map (step 3.5,
`workflow/checklists/detector-fidelity.md`) decides WHICH engine:

| engine | when | scope |
|---|---|---|
| `certify_acceptance.py` | **per-RUN** for SA/Delphes (incl. the native backend — the step-8 default) | this run's per-SR acc×eff vs the published acc×eff map |
| `validate_cutflow.py` | **one-time per ROUTINE** (Rivet path) | the routine's A×ε vs the published cutflow; carries across that routine's runs |

`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda`

## Per-run (SA/Delphes/native) — step 3.5's acceptance gate
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/certify_acceptance.py \
  --acceptance <the run's per-SR acceptance source> --tables-dir <hepdata acc×eff yaml dir> \
  --grid "<model phrase in the HEPData descriptions>" --m-parent <m> --m-lsp <m> \
  --srs "<comma list of SR names>"     # --dm instead of --m-lsp; --help for tier flags
```
Run it for EVERY native/SA run whose yields feed a limit — the per-point yields in a scan
inherit the routine-level cert plus this run-level check (see `checklists/detector-fidelity.md`).

## One-time per routine (Rivet) — the cutflow comparator
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/validate_cutflow.py \
  --signal <rundir>/build/analysis.yoda --routine <RIVET_ID> \
  --sigma-pb <σ> --lumi-fb <L> --tables-dir <hepdata tables dir> \
  --grid "<grid label>" --m-parent <m> --m-lsp <m> \
  --srs "2jl,2jm,2jt,4jt,5j,6jm,6jt"  --label "<model>" \
  --out <rundir>/outputs/cutflow_cert
```
`--srs` is a **comma list of SR names**, not a json path. Pass `--exclusion <exclusion.json>`
so it can tag the driving SR from the best expected CLs (else everything is "contributing" and
the verdict can't reach PASS). Optional tiers: `--driving-tol 0.15 --contributing-tol 0.25
--mu95-bound 0.10`.

## Read the verdict (both engines share the tiering)
- **PASS**: driving SR within tier **and** worst |Δµ₉₅| ≤ bound **and** the verdict can't flip.
- **WARN/FAIL**: read the attribution rows — each over-tier residual names its `cause_class`
  and bounded µ₉₅-impact. A WARN with a bounded, attributed cause on a non-driving SR is an
  honest, reportable result; an un-remediated FAIL on the driving SR is not.
- **On FAIL, read the printed FAIL CAUSE** (json `fail_reason`): it says whether the driving SR
  was **unevaluable** (fix the inputs — `--grid`, `--region-map`, tables) or **evaluated but
  over tolerance** (the comparison worked — diagnose the physics via the attribution rows).
  Don't debug the lookup for an over-tolerance FAIL or the physics for a lookup FAIL.
- **A `BASIS SUSPICION` line** (json `basis_suspicion`) means every evaluated SR sits at the same
  ratio — a global σ-basis fingerprint, not per-SR selection physics (see trap table).

Tier targets: driving ≤12–15% (Good ≤10%, Ideal ≤5%), contributing ≤25%, tail report-only.
Record the verdict in `RESULT.md`. This certification is one gate of several: the portfolio
gate is `framework/benchmark/`, and DELIVERY is gated by the step-9 panel — `verify_pack.py`
plus the adversary (`verification-panel` skill) — which audits this cert's presence too.

## What "certified" means (claim → evidence)
| Claim | Requires | Not sufficient |
|---|---|---|
| "acceptance certified" | THIS run's verdict from the right engine (table above), recorded in `RESULT.md` | the other engine, a sibling run's verdict, or "yields look close" |
| "PASS" | driving SR tagged (pass `--exclusion`) and within tier, worst \|Δµ₉₅\| ≤ bound, verdict can't flip | every SR merely "contributing" because no driving SR was tagged |
| "WARN, reportable" | attribution rows: each over-tier residual's `cause_class` + bounded µ₉₅ impact | an unattributed residual, or any residual on the driving SR |

| Thought | Reality |
|---|---|
| "The routine is certified; this run inherits it" | Catalogue B2: `ptj1min` silently dropped per-run — a ×2.14 σ_tag drift the routine-level cert can never see. The per-run gate exists for exactly this. |
| "It's a WARN, basically a PASS" | A WARN is reportable ONLY with its attribution rows; an un-remediated FAIL on the driving SR is not a reportable reproduction. |
| "Every SR is ~the same factor off — the detector model is uniformly bad" | Catalogue A4 (CR-140): a UNIFORM ratio is the σ-basis fingerprint — tagged-sample denominator vs the published INCLUSIVE denominator (uniform excess ≈ σ_incl/σ_tag; the flagship re-hit was ~2.7×). Heed the cert's `BASIS SUSPICION` line: rebase with f = σ_tag/σ_incl_LO before touching efficiencies. |

## Stop conditions
- No published acc×eff map / cutflow covers the point → the cert cannot run; that is a
  detector-fidelity finding (`workflow/checklists/detector-fidelity.md`) for the CHECK-IN
  flags — never certify against interpolated or invented reference values.
- Un-remediated FAIL on the driving SR → the yields do not feed a delivered limit; read the
  attribution rows and diagnose (or re-route) before step 9.
