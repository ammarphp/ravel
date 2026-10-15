# Replaying a completed run

Anyone holding a completed ordinary science run, or a submission package with its `run/`
records, can run it again and get a comparison receipt. The replay is a new run with its own
plan, its own approval and its own attempt. It never reuses the original approval or reopens a
spent attempt. The comparison checks declared quantities, not bytes. Agreement shows that the
run reproduces; it does not validate the physics.

(`ravel replay` needs one of the operation words below; the earlier bundled re-fit is
no longer shipped.)

## 1. Prepare

```console
ravel replay prepare --from /absolute/completed-run --into /absolute/replay-run
ravel replay prepare --from /absolute/package --into /absolute/replay-run --inputs-root /absolute/fetched-inputs
```

`prepare` reads the recorded specification and plan, then checks each recorded input by digest
where it now lives. Inputs are never copied. If any input is missing or has a different digest,
`prepare` names it and stops before creating the run directory. For a package, the original
base directory usually does not exist on the new machine. Fetch the inputs listed in
`inputs.json`, put them in one directory with the same relative layout, and pass that directory
with `--inputs-root`.

Then `prepare` plans the fresh run directory with the ordinary planner and compares the two
stage fingerprints. The fingerprint covers the command shape, every input digest, the outputs,
the mode, the limits and the Python version. The run-directory, base-directory and package
locations are replaced by placeholders before the comparison. The interpreter binary, platform,
package census and environment digests are not compared; differences in them are recorded under
`disclosed_differences` in `replay-of.json` and shown at CHECK-IN 1 with their original and
replay values. Any other difference refuses the replay and removes the freshly planned
directory. Correct the cause and repeat `prepare` into the same target. A refused preparation
leaves no CHECK-IN claiming an identical plan.

`replay-of.json` records the original plan sha256, the stage fingerprint, the original result
pins, the attempt-journal pins and the original approval pin. The approval pin is for reference
only.

The replay launches the same governed stage, so it carries the original's method decision.
`prepare` copies `inputs/method-decision.json` byte for byte into the replay run directory,
records its sha256 under `method_decision` in `replay-of.json` and shows the decision at
CHECK-IN 1. An original without a method decision is refused before any directory is created.

Two kinds of run are refused:

- A research-bound experiment, whose plan carries `research_binding`, runs only through its
  research cycle. That cycle owns the budget, the dispatch journal and the adjudication. To repeat
  it, add a new experiment to the cycle. A cycle experiment without that binding is an ordinary
  run and replays like any other.
- A partition child of a root-stream master is claimed in the master's journal. A second run of
  that partition needs a new master reservation.

## 2. Approve

CHECK-IN 1 of the replay carries a `replay` section and a line in `CHECKIN1.md`:
"replay of <original>: identical plan; environment differs: <names>". The section and the
markdown list every disclosed difference with both values, including differing interpreter,
platform, package census and environment digests. The section retains full digests. When no
environment difference is recorded, both say "no environment difference recorded". The run
directory and the base directory are locations, not environment: a replay always has a new run
directory, so the statement names them in a separate clause, "locations differ: <names>", and
the list still shows both values. The section is derived from `replay-of.json` and carries the
digest of the whole record as `record_sha256`. Editing any part of `replay-of.json`, including
the original result pins, the attempt-journal pins and the specification digest, or editing the
section, refuses approval. The same edit after approval invalidates that approval: the approval
gate and the run both refuse until the record is restored.

Approve the replay run directory the ordinary way, with
`ravel approve`. The approval mode is the original plan's, because the plan is identical. A
scripted or delegated machine decision is recorded as a machine decision. It is never labelled
as human or physicist review. A copy of the original approval file is refused, because it binds
the original plan's digest.

## 3. Run

```console
ravel replay run --rundir /absolute/replay-run
ravel replay run --rundir /absolute/project/replay-run --project /absolute/project --task replay
```

Both forms first check the approval. With `--project`, the replay is added to the project's
workflow-manager index and launched through Snakemake (`ravel wms`). The run directory must be
inside the project. Without it, the replay runs as an ordinary attempt (`ravel run`). The
command exits nonzero when that run does, including a lifecycle FAIL. The original's lifecycle
verdict is the reference for the replay's.

## 4. Compare

```console
ravel replay compare --original /absolute/completed-run --replay /absolute/replay-run [--tolerances tolerances.json]
```

`compare` reads the JSON documents in the selected output directory of each run, or the
`results/` folder of a package, and walks every value:

| Value | Rule |
|---|---|
| integer (counts, cutflow events) | exact |
| floating point (binned values, sumw2, fit results, limits) | relative tolerance, default 1e-9 |
| sampled quantity declared in `statistical` | both seeds required; equal seeds use the deterministic rule; differing seeds use the declared bound for floats; integers stay exact |
| boolean against number | type mismatch, including true against 1 and false against 0 |
| record metadata and declared ignore pointers | ignored and listed with their reasons |
| 64-hex digests | listed as provenance differences, not compared |
| paired non-JSON figure | listed as not compared; does not change an otherwise equal verdict |
| paired non-JSON non-figure | listed as not compared; otherwise equal JSON yields equal_json_only |

Metadata is identified by shape or by an explicit rule. Strings fully matching the timestamp
or UUID pattern are ignored at any depth. Run-directory paths are normalized and listed;
byte digests are provenance. For a package, the run directory is the one its copied plan
records as the stage working directory, so a packaged result that names a file below the
original run directory matches the same file below the replay's. A package whose plan records
no working directory keeps its paths literal. The only key ignored by name at the top level is `attempt_id`,
and only for string or null values: the execution ledger writes this field as attempt
bookkeeping, and result records carry the same identifier. Nested `attempt_id` values are
compared unless a shape rule or declared ignore covers them. There are no numeric fields
ignored by name, including durations and process identifiers. Keys `generated`, `pid`, `log`,
`date`, `created`, `updated`, `started`, `finished` and `attempt` have no name-based exemption.

Suffix rules `_utc`, `_at`, `_timestamp`, `_uuid` and `_pid` apply only to string values.
A number, boolean, list or object is never ignored by its key below the top level. To ignore
a duration or process id elsewhere, declare its JSON pointer and reason in the tolerance file.
An `ignore` pointer must be non-empty; `""` cannot suppress the whole document. A statistical
quantity pointer may be the root pointer. A seed is skipped and listed, never compared, so a
`seed_pointer` must name the recorded seed only: the tolerance file is refused when a seed
pointer is empty or covers a sampled quantity of its document.

A statistical row takes effect in a document only when it fits that document. Its quantity
pointer must resolve in both runs, and its seed pointer must name one integer or one string in
each run that records it. Otherwise the seed pointer skips nothing: the values under it are
compared as ordinary quantities, and the receipt lists the row under `not_comparable` as
`declared sampled quantity absent` or `seed pointer does not name a recorded integer or string
seed`. A row that matches nothing therefore never yields `equal`. Remove the row, or correct its
pointers, and compare again.

Figure suffixes are `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.tif`, `.tiff`, `.webp` for raster
images and `.svg`, `.eps`, `.pdf` for vector figure exports. Suffix matching is case-insensitive.
Their bytes are not declared quantities. The exemption follows the suffix alone, so a `.pdf`,
`.svg` or `.eps` file that holds a report or a table of numbers is exempt in the same way: it is
never read, and it does not change an `equal` verdict. Deliver every number that the comparison
must cover in a JSON document. Other formats, including text, CSV, ROOT and YODA,
need a declared-quantity reader before a full equality claim. Missing or extra documents are
mismatches. That includes a document that only the replay holds when the original is a
package: the package's `results/` must carry every delivered document of the run.

A sampled quantity without a recorded seed in either run is reported as
`not comparable: seed not recorded`, never as equal. The receipt is written to
`<replay>/replay-comparison.json`, or to `--out`. Its `verdict` is `equal`, `equal_json_only`,
`mismatch` or `not_comparable`, and it always carries `physics_validated: false`.
`equal` requires at least one compared leaf. Empty documents cannot establish equality.
If every leaf of a nonempty paired document is suppressed by declared ignore rows or seed
pointers, the receipt reports `not_comparable` and names that document, even when other
documents have compared leaves.
Metadata, seeds and provenance digests do not count as compared quantity leaves.
Each mismatch names its
document and JSON pointer. A changed bin reads, for example, `/histogram/sumw2/1`. The
command exits 1 unless the verdict is `equal`, and the `equal` field is false for
`equal_json_only`. `--exit-zero` keeps exit 0 once the receipt is written for callers that
request it. The receipt's verdict is authoritative regardless of the requested exit behaviour.

The tolerance file follows `src/ravel/data/governed_replay/tolerances.schema.json`:

```json
{"schema_version": 1, "default_relative": 1e-9,
 "ignore": [{"document": "result.json", "pointer": "/diagnostics/host_load", "reason": "machine load"}],
 "statistical": [{"document": "result.json", "pointer": "/sampled/mean", "seed_pointer": "/sampled/seed",
                  "n_sigma": 3, "uncertainty_pointer": "/sampled/error"}]}
```

## Snakemake template

`ravel replay template` prints the rule set that `ravel procedure` ships as
`templates/replay.smk`. It has four rules: prepare, approval gate, run and compare.

```console
snakemake -s replay.smk --cores 1 --config original=/absolute/completed-run replay=/absolute/replay-run
```

Snakemake never approves. The approval-gate rule fails until `ravel approve --rundir <replay>`
has recorded a fresh approval. Its message names that command.
The compare rule quotes the tolerance path and uses the ordinary comparison exit code.
Any verdict other than `equal` fails the workflow. The authoritative receipt stays in
`<replay>/replay-comparison.json`; successful comparison also writes the workflow output.
Snakemake can remove a failed rule's output without removing that authoritative receipt.
A receipt is never overwritten. To compare again, for example with a corrected tolerance
file, run `ravel replay compare` with a new `--out`.
