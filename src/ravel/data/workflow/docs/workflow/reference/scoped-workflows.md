# Generation-only and likelihood-only workflows

These supported calculations use shared content-bound approvals, source/runtime fingerprints,
supervision and status machinery. Their completion criteria cover the requested scope. A pass
does not certify detector acceptance, coverage, expert review or reproduction of a paper.

## Controller-owned plans

Controller routes prepare the typed specification and scope, then run the dry
`ordinary-study-prepare` step under its 120-second ceiling. `study.bind` consumes
the adopted preparation receipt and exact ordinary plan/specification hashes
before CHECK-IN 1. Mixed requests retain uncovered deliverables and stages.
The runtime dispatch keeps ordinary approval, production-role, source and
confinement checks; a clean process exit does not close the scientific task.

`evidence.py` checks approved descriptors against staged actual products before
custody acceptance. It retains operation-bound external recipes and their source
artifacts before generation, units and requested statistics, signed bases and
covariances, executed settings, weights, bins and perturbative order. Unknown
scientific validators leave a labelled pending obligation. Spectrum integrity
remains pending authenticated independent review; `operation-review` runs the
ordinary review graph before its waypoint. Current ordinary packet PASS is
required before synthesis and final delivery. Bounded correction keeps the
original prospective attempt and resource envelope.

For calculations, the charged `intake.plan` runner delivers its actual pinned
child through `controller_child`. Literal calculations revalidate the complete
original parent; physical children retain all parent obligations and continue
through judgment. Planning grants no child execution or parent acceptance.

Site lifecycle records reserve attempts and reconcile remote handles durably.
The final scheduler effect consumes one capability and submits its immutable
script snapshot, with exact profile, rule, task and resource scope. The shared
privileged capability channel carries subprocess credentials; an in-process
Use the privileged capability channel for subprocess credential transport. Budget and stop outcomes
retain notification, drain/reconciliation and qualified sink records.

These mechanisms have inert interface controls. Merged controller transport and
native/scientific operation qualification require their own executed evidence.
The direct CLI examples below apply to legacy runs outside controller ownership
and carry **NOT GOVERNED** status.

## Install and propose

From a checkout, follow the [compiler and native setup guide](../../installation.md), then prepare the complete Python3.12 environment:

```sh
python3.12 scripts/setup/python_installation.py
source .venv/bin/activate
ravel initiate --prompt "Compute a likelihood-only control from the supplied counting model." \
  --out /tmp/ravel-counting
ravel plan --rundir /tmp/ravel-counting --spec docs/examples/scoped/counting.json
```

Review `<run>/CHECKIN1.md` and `inputs/checkin1.json`: the exact recipe, source, numbered assumptions,
figure, waypoint and ceiling. Planning snapshots the statistical model or copies the installed
generator into immutable inputs. Approval and execution follow their separate lifecycle steps.
The source field records the supplied reference; the physicist still reviews its correctness.
Edit a specification before planning. A changed plan uses a new run directory.

## Approve and execute

After actual approval, record the physicist's response and run:

```sh
ravel approve --rundir /tmp/ravel-counting --quote "Yes, run this exact reviewed plan."
ravel run --rundir /tmp/ravel-counting
ravel status --rundir /tmp/ravel-counting --write
```

That quote is an example, not permission to manufacture assent. An explicitly authorized
scripted-YES experiment sets `approval_mode: scripted_yes` before planning and uses
`approve --scripted`. The plan and receipt bind this distinction; it is not expert review.

`full` means the complete scoped calculation. It does not schedule a detector simulation or
scan. Each plan permits one attempt, one worker and an explicit wall-clock ceiling. Numerical
libraries and MadGraph use one thread. Failed, killed and interrupted attempts consume the
attempt; their diagnostics remain. A further attempt needs a new reviewed plan.

`run --resume` verifies/reuses a valid completed result without new compute. It must not retry a
failed attempt or repair stale inputs. Source, runtime, input or output changes invalidate live
completion and comparison. Historical evidence is never silently rebound to newer software.

| Output | Purpose |
|---|---|
| `outputs/RESULT.md` | Readable result, figure and qualifications |
| `outputs/result.json` | Event audit or typed limits, diagnostics and units |
| `outputs/recipe.json` | Effective physics prescription extracted from execution |
| `outputs/figure.pdf`, `figure.png`, `figure.json` | Vector/raster figure, normalization and enforced layout lint |
| `outputs/checkin2.json` | Result waypoint for physicist review before another proposal |
| `execution_state.json`, `logs/execution/` | Durable attempts and input/output/runtime fingerprints |
| `outputs/failure.json`, fit diagnostics | Preserved failure evidence |

The result check-in offers GO/ADJUST for the next proposal, not permission for another attempt.
Completion records do not pretend a human inspected a figure because mechanical checks passed.

## Generation contract

Start with [drell-yan.json](../../examples/scoped/drell-yan.json). Supply installed MadGraph,
compatible Python and Fortran compiler paths. Optional `runtime.environment.SDKROOT` and
`LIBRARY_PATH` select an existing macOS SDK. Nothing downloads a toolchain. Native run paths
must not contain whitespace or quotes because of the upstream parser.

```sh
ravel initiate --prompt "Generate 100 parton-level Drell-Yan events without a shower or detector." \
  --out /tmp/ravel-dy
ravel plan --rundir /tmp/ravel-dy --spec /path/to/reviewed-drell-yan.json
```

The adapter supports one LO process, an installed model/restriction or a reviewed derived UFO,
explicit aliases, an optional complete parameter card and unmerged positive uniform nominal
weights. Processes are not hard-coded to Drell–Yan; each extension still needs its own physics
validation.

Generator version: give `runtime` paths, or `"generator": {"name": "madgraph", "version": "auto"}`
(or an exact version). Versions come from the toolchain manifest; `auto` picks the oldest
installed version that the process needs. Charged-lepton partons from a proton need MadGraph 3
(MadGraph 2.9.27 evaluates PDFs only for quarks, gluons and photons). CHECK-IN 1 records the
selection and the reason.

Beams: `beam_pdg` names both beam particles and `lpp1`/`lpp2` must agree with them (proton
`lpp=1`, antiproton `-1`, lepton, photon or neutrino beams `lpp=0`). The initial-state labels of
the process, expanded through `definitions` (or MadGraph's default `p` and `j`), give each
proton's parton content. Lepton or photon partons need `pdlabel=lhapdf` with a set whose
`Flavors` include them. After the run the effective `lpp` values and the LHE beam identities are
read back, so MadGraph's silent `lpp=0` for a lepton-quark initial state fails the audit.

PDFs: `run_settings.pdlabel` is a MadGraph built-in set with its identifier (`cteq6l1` 10042,
`cteq6_l` 10041, `cteq6_m` 10000, `nn23lo` 246800, `nn23lo1` 247000, `nn23nlo` 244800), or
`lhapdf` with the set's `lhaid` and `runtime.lhapdf_config` naming the installed `lhapdf-config`.
Planning resolves the identifier through the installed `pdfsets.index`, requires the set to be
pinned in `native/setup/pdf-sets.json` under the same name, reads its flavour census and binds
the info file; the LHE must carry the same identifier for both beams.

Derived models: `model_origin` names a `qualified-ufo.json` written by `ravel
model-derivation-bridge` after an accepted review. Planning checks the review, the attempt record
and the UFO bytes against the reviewed census, then copies the UFO into the run's private
generator copy only. A model that is neither installed nor reviewed is refused.

Model validation: `generation.model_validation` supplies pinned `admission` and
`widths` records for a single point. Each `parameter_points` entry supplies its
own pair. The records bind the UFO, effective process definitions, restriction
and exact selected parameter card through the shared model-admission consumer.
Planning copies the width receipt's selected card into the run and binds every
original evidence file. The worker rechecks the chain before launch and compares
the complete returned parameter/width population to that selected card. The
generation receipt retains each point's validation origin and qualifications.
An `Auto` point includes an externally or locally validated explicit effective
width card; the returned calculated widths and branches must match it. See the
[record contract](../../reference/model-events.md#model-validation-records).

Parameter points: `parameter_points` lists up to 64 points, each with an `id` and `overrides`
(`{"block": "MASS", "code": [9000005], "value": 1500.0}`; a `DECAY` value can be `"Auto"`).
Each point runs as its own MadGraph launch with seed `seed + index`; every override must reach
the executed card. A point that changes a mass without declaring that particle's width is
refused when the card carries a nonzero width.

Cross sections only: `"cross_section_only": true` drops observables and records σ ± δσ per point
from the LHE `<init>` block (integration uncertainty only). Events are still generated to
integrate; `events` sets how many.

LHE transform: `lhe_transform` names a rule file (see `ravel lhe-transform check`). After the
audit, the declared particles are rewritten before the shower; header, weights, momenta and
colour stay byte for byte. A rule that changes charge needs `Check:event = off` in the shower
settings, which planning checks. The rewrite is listed in `DEVIATIONS.md` and CHECK-IN 1.

Physics intent: an optional `physics_intent` declares processes and conjugate scope, coupling
orders, masses, widths, active parameters with their BSM blocks, PDF, collision energy,
fiducial cuts, virtuality windows and particles left undecayed. Planning compares it with the
staged cards and refuses a mismatch; after each launch it is compared again with the LHE banner.
`ravel spec-reconcile` runs the same comparison on any set of cards.

Receipt: `outputs/generation-receipt.json` records the generator version and selection, cards
with sha256, process, model identity, beams and PDF, events, σ with source and convention, the
weight convention and any transform. The shower and detector stage reads it.

Observables: either the original `observable` (final-state invariant mass with exact final-state
PDG IDs, bins and optional pT, eta and mass controls) or `observables`, a list of typed
final-state functions:

```json
{"id": "met", "kind": "missing_et", "pdg": [12, 14, 16], "abs_pdg": true,
 "bin_edges": [0, 50, 100, 200], "normalization": "unit_area"}
```

`kind` is `invariant_mass`, `pt`, `missing_et`, `eta`, `rapidity` or `phi`. `pdg` selects the
particle set (`abs_pdg` matches either charge), with optional `min_pt_gev` and `max_abs_eta`.
`combine` is `system` (the summed four-momentum of the leading `count` selected particles, or of
all of them), `leading` (the `count`-th hardest particle) or `each` (one entry per particle).
`missing_et` is the transverse momentum of the summed selection. `normalization` is `events`,
`unit_area` or `cross_section` (dσ/dx in pb per unit of the observable). Events without the
selection fill nothing for that observable. An optional generation-level `final_state_pdg`
enforces an exact per-event final-state census.

Shower: an optional `shower` stage `{"engine": "pythia8", "python": ..., "seed": ..., "settings": [...]}`
showers the audited LHE with Pythia 8 through the declared Python's `pythia8` bindings and
evaluates the same typed observables on the final-state particles. `settings` are
`Key = value` strings; beam, random-number and event-loop keys are set by the stage. Planning
imports `pythia8` under that Python and binds the interpreter and binding files. Every generated
event must be showered. The contract records `detector_mode: particle-level`, and the figure
overlays parton- and particle-level histograms.

Checks cover producer termination, complete gzip/XML, every event's census, four-momentum
conservation, final state/cuts, seed, beams/PDF, weights and effective cards. Supplied parameters
must survive unchanged. Generator and model sources are hashed. Caches are rebuilt in a working
copy. Figures divide counts by bin width, show bin extents and retain overflow/underflow counts.
MC counting errors do not include precision-theory uncertainty.

NLO/signed/variable weights, merging, detector simulation, PDF downloads, lepton ISR structure
functions (`lpp=±3/±4`) and spectrum generation belong to other routes. This adapter rejects them explicitly. Existing
full-analysis routes retain their separately supported scope.

## Likelihood contract

Supply a complete pyhf workspace or explicit single-bin counting approximation. Multiple
measurements require a named selection. Data, binning, modifiers, correlations, POI bounds and
parameter settings remain as supplied; no silent bound enlargement or invented efficiencies.

Counting uses `pyhf.uncorrelated_background`, with its gamma/Poisson auxiliary constraint.
A [single-bin counting model](../../examples/scoped/counting.json) is an approximation, not a
complete experimental likelihood. Generic workspaces report signal strength. Signal-event units and
visible-cross-section conversion require an explicit unit-signal counting model and luminosity.

The shared robust optimizer brackets and verifies all six asymptotic qtilde CLs crossings.
Fixed/ineffective POIs, invalid data, insufficient bounds and unresolved roots prevent delivery.
Numerical bounds and failed-fit diagnostics remain. Resolved roots do not prove global likelihood
optimality, asymptotic coverage or physical model adequacy.

## Compare effective recipes

```sh
ravel compare-recipes --left /tmp/ravel-dy-a --right /tmp/ravel-dy-b \
  --out /tmp/recipe-comparison.json
```

Both runs need current approval, completed execution and valid artifacts. The gate compares
model/generator sources, process settings, parameters, PDF/scales/cuts including recorded
defaults, weights and observable. Statistical runs compare workspace, measurement and inference
and normalization conventions. Only event count, seed and run tag are sampling metadata.
Equal prompts, missing recipes and unverified equal-looking JSON must not pass.

Exit 0 means recipe equivalence; exit 1 means mismatches or invalid custody. Differences are
named. No rate/shape ranking follows a failed gate. Equivalence alone is not statistical
agreement or accuracy: assess MC/integration uncertainty and independent physics references next.
External tools still need an artifact-verifying import adapter before their receipts can enter
this CLI gate; copying a claimed recipe into a Ravel run is not such an adapter.
