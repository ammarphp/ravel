# Generation-only and likelihood-only workflows

These supported calculations use shared content-bound approvals, source/runtime fingerprints,
supervision and status machinery. Their completion criteria cover the requested scope. A pass
does not certify detector acceptance, coverage, expert review or reproduction of a paper.

## Install and propose

From a checkout with Python 3.10–3.12:

```sh
python -m pip install '.[replay]'
ravel initiate --prompt "Compute a likelihood-only control from the supplied counting model." \
  --out /tmp/ravel-counting
ravel plan --rundir /tmp/ravel-counting --spec benchmarks/scoped/atlas-2jl-counting.json
```

Review `<run>/CHECKIN1.md` and `inputs/checkin1.json`: the exact recipe, source, numbered assumptions,
figure, waypoint and ceiling. Planning snapshots the statistical model or copies the installed
generator into immutable inputs. It does not generate events, fit limits or approve anything.
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

`run --resume` verifies/reuses a valid completed result without new compute. It cannot retry a
failed attempt or repair stale inputs. Source, runtime, input or output changes invalidate live
completion and comparison. Historical evidence is never silently rebound to newer software.

| Output | Purpose |
|---|---|
| `outputs/RESULT.md` | Readable result, figure and limitations |
| `outputs/result.json` | Event audit or typed limits, diagnostics and units |
| `outputs/recipe.json` | Effective physics prescription extracted from execution |
| `outputs/figure.pdf`, `figure.png`, `figure.json` | Vector/raster figure, normalization and enforced layout lint |
| `outputs/checkin2.json` | Result waypoint for physicist review before another proposal |
| `execution_state.json`, `logs/execution/` | Durable attempts and input/output/runtime fingerprints |
| `outputs/failure.json`, fit diagnostics | Preserved failure evidence |

The result check-in offers GO/ADJUST for the next proposal, not permission for another attempt.
Completion records do not pretend a human inspected a figure because mechanical checks passed.

## Generation contract

Start with [drell-yan.json](../../../benchmarks/scoped/drell-yan.json). Supply installed MadGraph,
compatible Python and Fortran compiler paths. Optional `runtime.environment.SDKROOT` and
`LIBRARY_PATH` select an existing macOS SDK. Nothing downloads a toolchain. Native run paths
cannot contain whitespace or quotes because of the upstream parser.

```sh
ravel initiate --prompt "Generate 100 parton-level Drell-Yan events without a shower or detector." \
  --out /tmp/ravel-dy
ravel plan --rundir /tmp/ravel-dy --spec /path/to/reviewed-drell-yan.json
```

The adapter supports one LO proton-proton process, an installed model/restriction, explicit
aliases, an optional complete parameter card, builtin cteq6l1 PDF (10042), and unmerged positive
uniform nominal weights. The final-state invariant-mass observable specifies exact final-state
PDG IDs, bins and optional pT, eta and mass controls. Processes are not hard-coded to Drell–Yan;
each extension still needs its own physics validation.

Checks cover producer termination, complete gzip/XML, every event's census, four-momentum
conservation, final state/cuts, seed, beams/PDF, weights and effective cards. Supplied parameters
must survive unchanged. Generator and model sources are hashed. Caches are rebuilt in a working
copy. Figures divide counts by bin width, show bin extents and retain overflow/underflow counts.
MC counting errors do not include precision-theory uncertainty.

NLO/signed/variable weights, merging, showers, detector simulation, LHAPDF provisioning, lepton
beams, arbitrary observables and spectrum generation remain product gaps for this adapter.
They are explicitly rejected, not counted as successful delivery. Existing full-analysis routes
retain their separately supported scope.

## Likelihood contract

Supply a complete pyhf workspace or explicit single-bin counting approximation. Multiple
measurements require a named selection. Data, binning, modifiers, correlations, POI bounds and
parameter settings remain as supplied; no silent bound enlargement or invented efficiencies.

Counting uses `pyhf.uncorrelated_background`, with its gamma/Poisson auxiliary constraint.
The [2jl control](../../../benchmarks/scoped/atlas-2jl-counting.json) is an approximation, not the
complete ATLAS likelihood. Generic workspaces report signal strength. Signal-event units and
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
Equal prompts, missing recipes and unverified equal-looking JSON cannot pass.

Exit 0 means recipe equivalence; exit 1 means mismatches or invalid custody. Differences are
named. No rate/shape ranking follows a failed gate. Equivalence alone is not statistical
agreement or accuracy: assess MC/integration uncertainty and independent physics references next.
External tools still need an artifact-verifying import adapter before their receipts can enter
this CLI gate; copying a claimed recipe into a Ravel run is not such an adapter.
