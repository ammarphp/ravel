# Authored analysis step

Some analysis steps cannot be written as a `columnar-analysis` recipe or computed by a quantity
tool. For those, an agent may write Python, and RAVEL runs it as a governed step: the study is
planned and approved, each attempt is pinned and runs in a sandbox, and failures are typed so a
repair loop stays bounded and honest. Use it only as a fallback.

## The study

Science mode `authored-analysis` takes:

```json
{"purpose": "The selection needs an event-level combinatoric choice that the recipe cannot state.",
 "specification": "spec.md",
 "code": "attempt.py",
 "io_contract": {"inputs": [{"name": "events", "path": "events.root"}],
                 "outputs": [{"path": "yields.json", "kind": "json", "postconditions": [
                   {"pointer": "/signal_region/yield", "check": "positive"},
                   {"pointer": "/signal_region/weights", "check": "not_all_zero"},
                   {"pointer": "/signal_region/acceptance", "check": "range", "low": 0, "high": 1,
                    "class": "scientific_unresolved"}]}]},
 "parameters": [{"name": "met_threshold", "value": 200, "expected_sensitivity": "the yield falls as it rises"}],
 "budget": 3,
 "timeout_seconds": 600,
 "reference_paths": ["published/"]}
```

CHECK-IN 1 shows the purpose, the specification, the contract, the budget and the lint of the
first attempt. Planning refuses code whose lint has errors and refuses when no sandbox is
available.

## How an attempt runs

The code runs as `python -B -s code.py` in a new working directory. It reads
`step-inputs.json` (input names mapped to absolute paths, the parameters and the declared output
paths) and writes its outputs there. It may import `ravel.toolkit`.

The process runs under `sandbox-exec` on macOS or `bwrap` on Linux. It has no network, can
write only inside its working directory and cannot read the reference paths. Without a sandbox
the step does not run.

After the run, every output is checked against its postconditions (`exists`, `finite`,
`all_finite`, `positive`, `nonzero`, `not_all_zero`, `range`). The attempt gets a failure class:

- `coding`: an exception, a missing or malformed output, a failed postcondition (including
  all-zero or non-finite weights), or a lint error;
- `infrastructure`: a timeout, a signal, or memory or disk exhaustion;
- `scientific_unresolved`: a postcondition declared with that class failed, or the code wrote
  `unresolved.json` stating a question the specification does not settle.

Coding and infrastructure failures may be repaired while the budget lasts. A scientific failure
or a spent budget sets the step to `failed_stage_review` (`docs/workflow/reference/failed-stage-review.md`).

## The repair loop

The worker runs the first attempt. When it fails, continue within the same approval:

```
ravel authored-analysis new    --rundir RUN --ledger repair/ --from RUN/outputs/attempt-1/authored-analysis
ravel authored-analysis packet --ledger repair/
ravel authored-analysis submit --ledger repair/ --code attempt-2.py
ravel authored-analysis run    --ledger repair/
```

`new` checks that the run's approved plan is this exact task. `run` checks it again before it
executes. Each attempt's code and observation are written once under `attempts/NNN/` and their
hashes are kept in `ledger.json`; a changed file is detected.

The designer packet for the next attempt holds exactly the specification pin, the input/output
contract, the previous code pin, its diff from the attempt before it, and the observation (exit
code, the end of stderr, postcondition results, lint findings and failure class). Postcondition
results say only whether a check passed. The packet never holds output values or comparisons
with reference results.

## Lint

`ravel authored-analysis lint --code attempt.py --task task.json` reports:

- errors: forbidden modules (process, network and foreign-function modules), forbidden calls
  (`os.system`, `exec`, `eval` and similar), syntax errors, and declared parameters the code never
  reads;
- warnings: Python loops over every entry or object (`range(len(x))`, `.tolist()` loops), and
  functions that reimplement a toolkit function.

## Toolkit

`ravel.toolkit` gives authored code tested functions: `p4`, `invariant_mass`, `delta_phi`,
`delta_r`, `transverse_mass`, `neutrino_pz`, `aplanarity`, `mt2`, `mt2w`, `modified_topness`,
`overlap_mask`, `leading`, `event_scale` (cross section × luminosity / sum of weights, with the
source of each input) and `asimov_significance` (the median discovery significance of a counting
experiment, with an optional background uncertainty).

## Inspecting files first

`ravel root-schema --input FILE [--tree NAME] [--max-entries N] [--draft]` lists every tree and
branch with its type, jaggedness, finite and zero fractions, range and, for weight branches, the
sums. It writes nothing. `--draft` adds a draft format descriptor and weight contract for review.
